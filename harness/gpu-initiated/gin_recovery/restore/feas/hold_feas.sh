#!/usr/bin/env bash
# hold_feas.sh - one hold of gin-restore's feasibility tests (EXPERIMENT.md 9.15; DRAFT stage, never scored). The main
# session runs it inside ../../../common/cluster_run.sh (tag rs-<hold>, -w 10800) under timeout -s KILL 880.
# usage: hold_feas.sh <resultsdir> <hold>
#   S3     B3 smoke: one cross-node cell, rain responder, relaxed MR, 208 iterations (setup check; not used in any verdict)
#   B3r    B3, rain is the responder: b3_x_rain_<ro|so>, b3_s_rain_<ro|so>, b3_h_rain_<ro|so>, 4 000 iterations each
#   B3s    B3, sunny is the responder: the same six cells with sunny
#   B2     B2: four ranks interleaved (rain 0, 2; sunny 1, 3), report lines only, 2 trials
#   B2c    B2 control (optional): four ranks consecutive (rain 0, 1; sunny 2, 3), 1 trial
#   B1     B1: record (2 ranks), replay rank 1 on sunny and rank 0 on rain (strace), two negative replays; 2 trials
#   B1live B1 optional (only after B1 passed): 2 ranks hold 30 s while a spare replays rank 1 on sunny; 1 trial
# Before and after the hold (as ../../remaining/hold.sh): GPU users and compute mode of both nodes, the mlx5 kernel lines of
# both nodes, rain's mlx5_1 firmware-command counters (debugfs, read-only, ../../scripts/ts1/fwcmd_snapshot.sh). A new mlx5
# command-error line or a growth of the firmware-command failure counters writes <resultsdir>/STOP_mlx5; a CUDA memory fault
# writes STOP_cuda; a test process left after its trial writes STOP_left. No further hold should run while a STOP file
# exists (the main session checks). Processes are never killed here: every process is bounded by its own timeout; the
# leftover check is a read-only count by exact name. No iptables rule.
# env: SUNNY_SSH (required)
set -u
R=${1:?resultsdir}; H=${2:?hold}
D=$(cd "$(dirname "$0")" && pwd)
SUNNY_SSH=${SUNNY_SSH:?set SUNNY_SSH}
export SUNNY_SSH
CMDERR='grep -i mlx5 | grep -iE "cmd|command" | grep -icE "failed|timeout|leak"'
NAMES="rs_spike rs_drain_test"
mkdir -p "$R"
for f in STOP_mlx5 STOP_cuda STOP_left; do [ -e "$R/$f" ] && { echo "$R/$f present: no hold runs" >&2; exit 3; }; done
left() { { for n in $NAMES; do pgrep -x "$n"; done; ssh -n "$SUNNY_SSH" "for n in $NAMES; do pgrep -x \$n; done"; } 2>/dev/null | wc -l; }
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
  bash "$D/../../scripts/ts1/fwcmd_snapshot.sh" "$1" > "$R/fwcmd_$1.txt" 2>&1
  echo "rain fwcmd failed sum: $(awk '{for(i=1;i<=NF;i++) if($i ~ /^failed=|^failed_mbox_status=/){split($i,a,"="); s+=a[2]}} END{print s+0}' "$R/fwcmd_$1.txt")"
  echo "rain fwcmd QUERY_QP n: $(awk '$1=="QUERY_QP"{for(i=1;i<=NF;i++) if($i ~ /^n=/){split($i,a,"="); print a[2]}}' "$R/fwcmd_$1.txt")"
}
n0=$(left)
[ "$n0" -eq 0 ] || { echo "$(date '+%F %T') hold $H: $n0 test process(es) present before the hold" | tee -a "$R/STOP_left"; exit 3; }
snap "before-$H" | tee "$R/snap_before-$H.txt"
b3() { bash "$D/run_b3.sh" "$@"; }        # b3 <cell> <iters> <logdir>
sp() { bash "$D/run_spike.sh" "$@"; }     # sp <cell> <trial> <logdir>
case "$H" in
  S3) b3 b3_x_rain_ro 208 "$R/b3_smoke" ;;
  B3r) for c in x s h; do for o in ro so; do b3 "b3_${c}_rain_$o" 4000 "$R/b3"; done; done ;;
  B3s) for c in x s h; do for o in ro so; do b3 "b3_${c}_sunny_$o" 4000 "$R/b3"; done; done ;;
  B2) for t in 1 2; do sp b2_inter "$t" "$R/b2"; done ;;
  B2c) sp b2_consec 1 "$R/b2" ;;
  B1) for t in 1 2; do sp b1 "$t" "$R/b1"; done ;;
  B1live) sp b1_live 1 "$R/b1" ;;
  *) echo "unknown hold $H" >&2; exit 2 ;;
esac
snap "after-$H" | tee "$R/snap_after-$H.txt"
for node in rain sunny; do
  diff <(sort "$R/mlx5_before-${H}_$node.txt") <(sort "$R/mlx5_after-${H}_$node.txt") | grep '^>' | sed "s/^> /$node: /"
done > "$R/mlx5_new_$H.txt"
echo "new mlx5 kernel lines in hold $H: $(wc -l < "$R/mlx5_new_$H.txt")"; cat "$R/mlx5_new_$H.txt"
b=$(grep -h "cmd_err lines\|fwcmd failed sum" "$R/snap_before-$H.txt" | awk -F': ' '{s+=$2} END{print s+0}')
a=$(grep -h "cmd_err lines\|fwcmd failed sum" "$R/snap_after-$H.txt" | awk -F': ' '{s+=$2} END{print s+0}')
[ "$a" -gt "$b" ] && echo "$(date '+%F %T') hold $H: mlx5 command errors or firmware-command failures grew ($b -> $a)" | tee -a "$R/STOP_mlx5"
cudafail=$(find "$R" \( -name '*.kv' -o -name '*.log' \) -newer "$R/snap_before-$H.txt" \
  -exec grep -liE 'illegal address|illegal memory access|unspecified launch failure|cuda_error=' {} + 2>/dev/null | sort -u)
[ -n "$cudafail" ] && echo "$(date '+%F %T') hold $H: CUDA fault in: $(echo "$cudafail" | tr '\n' ' ')" | tee -a "$R/STOP_cuda"
n1=$(left)
[ "$n1" -eq 0 ] || echo "$(date '+%F %T') hold $H: $n1 test process(es) left after the hold" | tee -a "$R/STOP_left"
exit 0
