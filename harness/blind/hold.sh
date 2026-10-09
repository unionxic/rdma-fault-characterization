#!/usr/bin/env bash
# blind-apps holds (each <= 15 min, each inside ../gpu-initiated/common/cluster_run.sh -w 10800; see chain.sh).
# usage: hold.sh <resultsdir> <P1|P2|B0|B9|D1..D4|G1|G2|N1|N2>
#   P1  pilot (never scored): two fault-free runs per workload, then the DDP hook probes for calib.py
#   P2  pilot (never scored): one demo of every runtime fault and of the GIN and NVSHMEM hooks, with calib.json
#   B0  fault-free reference runs before the blind trials (ddp 3, gin 3, nvs 3); B9 one more of each after them
#   D*, G*, N*  the sealed schedule's trials of that hold (blindrun.py hold; the schedule is read by the runner only)
# Before and after every hold: GPU users and compute mode of both nodes; the full mlx5 kernel lines of both nodes
# (mlx5_<tag>_<node>.txt); the count of mlx5 command-error lines; rain's mlx5_1 firmware-command counters (debugfs,
# read-only); the iptables rules tagged blind- on rain. A new command-error line or a growth of the firmware-command
# failure counters writes <resultsdir>/STOP_mlx5; a blind- rule still present after the hold writes STOP_iptables;
# blindrun.py writes STOP_cuda (exit 139 or a CUDA memory fault) and STOP_left (processes left in two trials in a row).
# chain.sh runs no further hold after a STOP file. Processes are never killed here: a blind_gin_ring, blind_nvs_rr or
# ddp_entry.py left by an earlier hold is waited for (read-only count, at most 150 s), else no trial runs (STOP_left).
set -u
R=${1:?resultsdir}; H=${2:?hold}
D=$(cd "$(dirname "$0")" && pwd)
SUNNY_SSH=${SUNNY_SSH:-unionxic@192.0.2.194}
export SUNNY_SSH
CMDERR='grep -i mlx5 | grep -iE "cmd|command" | grep -icE "failed|timeout|leak"'
PAT='[b]lind_gin_ring|[b]lind_nvs_rr|[d]dp_entry.py'
BR="python3 $D/blindrun.py"
BUDGET=800
snap() {  # snap <tag>
  echo "== $1 $(date '+%F %T')"
  nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader 2>/dev/null | sed 's/^/rain gpu: /'
  ssh -n "$SUNNY_SSH" "nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader" 2>/dev/null | sed 's/^/sunny gpu: /'
  nvidia-smi --query-gpu=index,name,compute_mode --format=csv,noheader 2>/dev/null | sed 's/^/rain gpu mode: /'
  ssh -n "$SUNNY_SSH" "nvidia-smi --query-gpu=index,name,compute_mode --format=csv,noheader" 2>/dev/null | sed 's/^/sunny gpu mode: /'
  sudo -n dmesg 2>/dev/null | grep -i mlx5 > "$R/mlx5_$1_rain.txt"
  ssh -n "$SUNNY_SSH" "sudo -n dmesg 2>/dev/null | grep -i mlx5" > "$R/mlx5_$1_sunny.txt"
  echo "rain mlx5 dmesg lines: $(wc -l < "$R/mlx5_$1_rain.txt")"
  echo "sunny mlx5 dmesg lines: $(wc -l < "$R/mlx5_$1_sunny.txt")"
  echo "rain mlx5 cmd_err lines: $(eval "cat $R/mlx5_$1_rain.txt | $CMDERR")"
  echo "sunny mlx5 cmd_err lines: $(eval "cat $R/mlx5_$1_sunny.txt | $CMDERR")"
  bash "$D/../gpu-initiated/gin_recovery/scripts/ts1/fwcmd_snapshot.sh" "$1" > "$R/fwcmd_$1.txt" 2>&1
  echo "rain fwcmd failed sum: $(awk '{for(i=1;i<=NF;i++) if($i ~ /^failed=|^failed_mbox_status=/){split($i,a,"="); s+=a[2]}} END{print s+0}' "$R/fwcmd_$1.txt")"
  echo "rain iptables rules tagged blind-: $(sudo -n iptables -w 5 -S 2>/dev/null | grep -c -- 'blind-')"
}
mkdir -p "$R"
HT=$H
for i in $(seq 1 30); do
  stale=$( { pgrep -f "$PAT"; ssh -n "$SUNNY_SSH" "pgrep -f '$PAT'"; } 2>/dev/null | wc -l)
  [ "$stale" -eq 0 ] && break
  echo "$(date '+%F %T') hold $HT: $stale process(es) of this study still present; waiting" | tee -a "$R/stale.txt"
  sleep 5
done
[ "$stale" -eq 0 ] || echo "$(date '+%F %T') hold $HT: processes of this study still present after 150 s; no trial runs" | tee -a "$R/STOP_left"
snap "before-$HT" | tee "$R/snap_before-$HT.txt"
demo() { [ -e "$R/STOP_left" ] || $BR demo --results "$R" --budget-s $BUDGET "$@"; }
case "$H" in
  P1)  # pilot: fault-free runs, then the DDP hook probes (two k per hook; calib.py fits k(t) through them)
    for wl in ddp gin nvs; do for k in 1 2; do demo --workload $wl --cls none --name $wl-none-$k; done; done
    demo --workload ddp --cls sqp --target 0 --k 500 --name ddp-sqp-k500
    demo --workload ddp --cls sqp --target 0 --k 5000 --name ddp-sqp-k5000
    demo --workload ddp --cls rqp --target 1 --k 500 --name ddp-rqp-k500
    demo --workload ddp --cls rqp --target 1 --k 5000 --name ddp-rqp-k5000
    demo --workload ddp --cls srq --target 1 --k 200 --name ddp-srq-k200
    demo --workload ddp --cls srq --target 1 --k 2000 --name ddp-srq-k2000 ;;
  P2)  # pilot: one demo of each runtime fault and of the GIN and NVSHMEM hooks (u = 0.5 through calib.json)
    demo --workload ddp --cls kill --target 1 --name ddp-kill
    demo --workload ddp --cls stop --target 1 --name ddp-stop
    demo --workload ddp --cls mute --dir both --name ddp-mute
    demo --workload gin --cls qperr --target 0 --name gin-qperr
    demo --workload gin --cls kill --target 1 --name gin-kill
    demo --workload gin --cls stop --target 0 --name gin-stop
    demo --workload gin --cls mute --dir both --name gin-mute
    demo --workload nvs --cls qperr --target 1 --name nvs-qperr
    demo --workload nvs --cls remacc --target 1 --name nvs-remacc
    demo --workload nvs --cls kill --target 1 --name nvs-kill
    demo --workload nvs --cls stop --target 0 --name nvs-stop
    demo --workload nvs --cls mute --dir oneway --name nvs-mute ;;
  B0)  # fault-free references before the blind trials
    for wl in ddp gin nvs; do [ -e "$R/STOP_left" ] || $BR baseline --results "$R" --workload $wl --n 3 --first 1 --budget-s $BUDGET; done ;;
  B9)  # one more reference of each after the blind trials (drift check)
    for wl in ddp gin nvs; do [ -e "$R/STOP_left" ] || $BR baseline --results "$R" --workload $wl --n 1 --first 4 --budget-s $BUDGET; done ;;
  D[0-9]*|G[0-9]*|N[0-9]*)
    [ -e "$R/STOP_left" ] || $BR hold --results "$R" --hold "$H" --budget-s $BUDGET ;;
  *) echo "unknown hold $H" >&2; exit 2 ;;
esac
snap "after-$HT" | tee "$R/snap_after-$HT.txt"
for node in rain sunny; do
  diff <(sort "$R/mlx5_before-${HT}_$node.txt") <(sort "$R/mlx5_after-${HT}_$node.txt") | grep '^>' | sed "s/^> /$node: /"
done > "$R/mlx5_new_$HT.txt"
echo "new mlx5 kernel lines in hold $HT: $(wc -l < "$R/mlx5_new_$HT.txt")"; cat "$R/mlx5_new_$HT.txt"
b=$(grep -h "cmd_err lines\|fwcmd failed sum" "$R/snap_before-$HT.txt" | awk -F': ' '{s+=$2} END{print s+0}')
a=$(grep -h "cmd_err lines\|fwcmd failed sum" "$R/snap_after-$HT.txt" | awk -F': ' '{s+=$2} END{print s+0}')
if [ "$a" -gt "$b" ]; then
  echo "$(date '+%F %T') hold $H: mlx5 command errors or firmware-command failures grew ($b -> $a)" | tee -a "$R/STOP_mlx5"
fi
left=$(sudo -n iptables -w 5 -S 2>/dev/null | grep -c -- 'blind-')
[ "$left" = 0 ] || echo "$(date '+%F %T') hold $H: $left iptables rule(s) tagged blind- still present" | tee -a "$R/STOP_iptables"
python3 "$D/rows_blind.py" "$R" --progress
