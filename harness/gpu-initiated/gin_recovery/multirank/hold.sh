#!/usr/bin/env bash
# gin-multirank holds (each <= 15 min; each inside ../../common/cluster_run.sh -w 10800, see chain.sh).
# usage: LIB=<recovery build> [MRKEY=<driver key>] hold.sh <resultsdir> <P0|H1..H7|fill:<subdir>:<cell>:<n>:<start>[,...]>
# Trial folders under <resultsdir>: one per hold (p0/, h1/ ... h7/, or the fill's <subdir>).
# Before and after every hold: GPU users and compute mode of both nodes; the full mlx5 kernel lines of both nodes
# (mlx5_<tag>_<node>.txt); the count of mlx5 command-error lines; rain's mlx5_1 firmware-command counters (debugfs,
# read-only). New mlx5 lines are written to mlx5_new_<hold>.txt and printed. A new command-error line or a growth of the
# firmware-command failure counters writes <resultsdir>/STOP_mlx5, and chain.sh runs no further hold (EXPERIMENT.md 8).
# P0 is the pilot (never scored): it stops after the first four-rank fault-free trial unless every rank ended "ok"
# (writes <resultsdir>/PILOT_STOP), so a setup that cannot work costs two trials, not the whole hold.
set -u
R=${1:?resultsdir}; H=${2:?hold}
LIB=${LIB:?LIB (the recovery build key, e.g. ow for the pilot)}
D=$(cd "$(dirname "$0")" && pwd)
SUNNY_SSH=${SUNNY_SSH:-unionxic@192.0.2.194}
HT=$(echo "$H" | cut -d: -f1)
CMDERR='grep -i mlx5 | grep -iE "cmd|command" | grep -icE "failed|timeout|leak"'
snap() {  # snap <tag>
  echo "== $1 $(date '+%F %T') lib=$LIB mrkey=${MRKEY:-$LIB}"
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
  bash "$D/../scripts/ts1/fwcmd_snapshot.sh" "$1" > "$R/fwcmd_$1.txt" 2>&1
  echo "rain fwcmd failed sum: $(awk '{for(i=1;i<=NF;i++) if($i ~ /^failed=|^failed_mbox_status=/){split($i,a,"="); s+=a[2]}} END{print s+0}' "$R/fwcmd_$1.txt")"
}
mkdir -p "$R"
# gin_mr left by an earlier hold that its timeout cut is still bounded by its own timeout wrapper (WATCHDOG_S + 20 s):
# wait for it (read-only count, nothing is killed); if it is still there after 150 s, run no trial (STOP_left)
for i in $(seq 1 30); do
  stale=$( { pgrep -x gin_mr; ssh -n "$SUNNY_SSH" "pgrep -x gin_mr"; } 2>/dev/null | wc -l)
  [ "$stale" -eq 0 ] && break
  echo "$(date '+%F %T') hold $HT: $stale gin_mr process(es) still present; waiting" | tee -a "$R/stale.txt"
  sleep 5
done
[ "$stale" -eq 0 ] || echo "$(date '+%F %T') hold $HT: gin_mr still present after 150 s; no trial runs" | tee -a "$R/STOP_left"
snap "before-$HT" | tee "$R/snap_before-$HT.txt"
c() { [ -e "$R/STOP_left" ] || bash "$D/cells.sh" "$R/$2" "$1" "$LIB" "${3:-1}" "${4:-1}"; }  # c <cell> <subdir> [n] [start]
okall() {  # okall <subdir> <cell> <trial> <n>: every rank's kv says outcome=ok
  local r; for ((r = 0; r < $4; r++)); do grep -qx 'outcome=ok' "$R/$1/${2}_${3}_r$r.kv" 2>/dev/null || return 1; done
}
case "$H" in
  P0)  # pilot (not scored): the driver at N=2, the negative control, then the gate on two four-rank fault-free trials
    c mr2_none p0 1 1
    c mr4_nomrge p0 1 1
    c mr4_none p0 2 1
    if okall p0 mr4_none n1 4 || okall p0 mr4_none n2 4; then
      for x in mr3_none mr4_none_peer mr4_f1_01 mr4_f1_02 mr4_f3_01 mr4_f1all0 mr4_f1_10_30 mr4_kill3 mr4_kill3_peer \
               mr4_cyc_stall mr4_lat mr4_lat_solo mr2_lat; do
        c $x p0 1 1
      done
    else
      echo "$(date '+%F %T') pilot: no four-rank fault-free trial ended ok on every rank; the rest of P0 is skipped" | tee -a "$R/PILOT_STOP"
    fi ;;
  H1)  # fault-free: 4 ranks with the context flush (10) and the per-peer flush (5), interleaved 2:1; 2 ranks (5)
    for k in 1 2 3 4 5; do c mr4_none h1 2 $((2 * k - 1)); c mr4_none_peer h1 1 $k; done
    c mr2_none h1 5 1 ;;
  H2)  # latency (2 ranks, 4 ranks with one pair, 4 ranks with every pair; interleaved), then 3 ranks fault-free and faulted
    for k in 1 2 3 4 5; do for x in mr2_lat mr4_lat_solo mr4_lat; do c $x h2 1 $k; done; done
    for k in 1 2 3 4 5; do c mr3_none h2 1 $k; c mr3_f1_01 h2 1 $k; done ;;
  H3)  for k in $(seq 1 10); do c mr4_f1_01 h3 1 $k; c mr4_f1_02 h3 1 $k; done ;;
  H4)  for k in $(seq 1 10); do c mr4_f3_01 h4 1 $k; c mr4_f1_01_23 h4 1 $k; done ;;
  H5)  for k in $(seq 1 10); do c mr4_f1_10_30 h5 1 $k; c mr4_f1all0 h5 1 $k; done ;;
  H6)  for k in 1 2 3 4 5; do c mr4_kill3 h6 2 $((2 * k - 1)); c mr4_kill3_peer h6 1 $k; done ;;
  H7)  c mr4_kill3_peer h7 5 6
       for k in 1 2 3 4 5; do c mr4_chain_stall h7 1 $k; c mr4_cyc_stall h7 1 $k; done ;;
  fill:*)  # replacement trials: fill:<subdir>:<cell>:<n>:<start>[,...]
    spec=${H#fill:}
    IFS=',' read -ra items <<< "$spec"
    for it in "${items[@]}"; do
      IFS=':' read -r sub cl n st <<< "$it"
      c "$cl" "$sub" "$n" "$st"
    done ;;
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
