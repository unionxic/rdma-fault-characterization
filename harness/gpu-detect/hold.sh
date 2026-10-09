#!/usr/bin/env bash
# gpu-detect holds (each <= 15 min, each inside ../gpu-initiated/common/cluster_run.sh -w 10800; see chain.sh). Merged from
# ../blind/hold.sh (app trials through apprun.py) and ../gpu-initiated/gin_recovery/remaining/hold.sh (regression cells
# through cells_reg.sh); neither of those files is changed.
# usage: hold.sh <resultsdir> <P1|P2|G1|G2|N1|N2|R1|R2|R3|R4>
#   P1      pilot, app trials (never scored): cells.json "P1" (pilot 2: every changed app cell once)
#   P2      pilot, regression and latency (never scored; pilot 2): on hk f1_b, f2rel_b, 4 KiB latency with the watch off,
#           at 1 ms and at 10 ms, the M-A and both M-C cells, the responder-side gap (rm4_gap, rm4_gapx), hold asked for
#           (rm4_kill3_hold), a policy mismatch (f4_mix_b); on hw the gap's control (rm4_gap)
#   G1, G2  GIN example trials of schedule.json (apprun.py hold)
#   N1, N2  NVSHMEM example trials of schedule.json
#   R1      two-rank regression on hk (6 cells x 5), then fault-free latency per watch period (0, 1, 10, 100 ms; 4 KiB and
#           256 KiB; 5 runs each, interleaved)
#   R2      four-rank regression on hk (4 cells x 5)
#   R3      the two review cells on hk: two lower REQs in one ACK wait (5), the late pair fault after a death under the
#           default rule (3) and under NCCL_GIN_TS_DEGRADED_ROUNDS=1 (3), interleaved
#   R4      the hk cells: the responder-side gap on hk (5) and its control on hw (3), the exit-after-ACK form on hk (3), hold
#           asked for (3), a policy mismatch (3), interleaved
# App trials are written to <resultsdir>/raw/<id>/, regression trials to <resultsdir>/reg/<build>/ (two ranks) and
# <resultsdir>/reg/mr_<build>/ (four ranks).
# Before and after every hold: GPU users and compute mode of both nodes; the full mlx5 kernel lines of both nodes
# (mlx5_<tag>_<node>.txt); the count of mlx5 command-error lines; rain's mlx5_1 firmware-command counters (debugfs,
# read-only). A new command-error line or a growth of the firmware-command failure counters writes <resultsdir>/STOP_mlx5;
# a CUDA memory fault in a trial (exit 139, illegal address, launch failure) writes STOP_cuda; two trials in a row that
# left a process behind write STOP_left (apprun.py, cells_reg.sh). chain.sh then runs no further hold (EXPERIMENT.md 8).
# This study adds no iptables rule. Processes are never killed here: a process of this study left by an earlier hold
# that its timeout cut is waited for (read-only count, at most 150 s), else no trial runs (STOP_left).
set -u
R=${1:?resultsdir}; H=${2:?hold}
D=$(cd "$(dirname "$0")" && pwd)
SUNNY_SSH=${SUNNY_SSH:-unionxic@192.0.2.194}
export SUNNY_SSH
CMDERR='grep -i mlx5 | grep -iE "cmd|command" | grep -icE "failed|timeout|leak"'
APAT='[b]lind_gin_ring|[g]d_gin_ring|[b]lind_nvs_rr|[g]d_nvs_rr'
AR="python3 $D/apprun.py"
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
}
mkdir -p "$R"
for i in $(seq 1 30); do
  stale=$( { pgrep -f "$APAT"; pgrep -x gin_mr; pgrep -x gin_ts2
             ssh -n "$SUNNY_SSH" "pgrep -f '$APAT'; pgrep -x gin_mr; pgrep -x gin_ts2"; } 2>/dev/null | wc -l)
  [ "$stale" -eq 0 ] && break
  echo "$(date '+%F %T') hold $H: $stale process(es) of this study still present; waiting" | tee -a "$R/stale.txt"
  sleep 5
done
[ "$stale" -eq 0 ] || echo "$(date '+%F %T') hold $H: processes of this study still present after 150 s; no trial runs" | tee -a "$R/STOP_left"
snap "before-$H" | tee "$R/snap_before-$H.txt"
c() {  # c <cell> [n] [start] [build]: a regression cell (build hk unless given; folder reg/mr_<build> for four ranks, else
       # reg/<build>)
  local b=${4:-hk} sub
  sub=$b
  case "$1" in mr4_*|rm4_*) sub=mr_$b ;; esac
  [ -e "$R/STOP_left" ] || RES=$R bash "$D/cells_reg.sh" "$R/reg/$sub" "$1" "$b" "${2:-1}" "${3:-1}"
}
app() { [ -e "$R/STOP_left" ] || $AR hold --results "$R" --hold "$1" --budget-s $BUDGET; }
case "$H" in
  P1) app P1 ;;
  P2) c f1_b; c f2rel_b; c lat_4k_w0; c lat_4k_w1; c lat_4k_w10; c mr4_twolow_stall; c rm4_late01; c rm4_late01_rounds
      c rm4_gap 1 1 hw; c rm4_gap; c rm4_gapx; c rm4_kill3_hold; c f4_mix_b ;;
  G1|G2|N1|N2) app "$H" ;;
  R1)
    for x in f1_b f3_b bidirf_sym_b f4_b f2rel_b hd_rxdeath_b; do c $x 5; done
    for k in 1 2 3 4 5; do for x in lat_4k lat_256k; do for w in 0 1 10 100; do c "${x}_w$w" 1 "$k"; done; done; done ;;
  R2) for x in mr4_none mr4_f1_01 rm4_kill3_untimed mr4_cyc_stall; do c $x 5; done ;;
  R3)
    for k in 1 2 3 4 5; do
      c mr4_twolow_stall 1 "$k"
      if [ "$k" -le 3 ]; then c rm4_late01 1 "$k"; c rm4_late01_rounds 1 "$k"; fi
    done ;;
  R4)
    for k in 1 2 3 4 5; do
      c rm4_gap 1 "$k"
      if [ "$k" -le 3 ]; then c rm4_gap 1 "$k" hw; c rm4_gapx 1 "$k"; c rm4_kill3_hold 1 "$k"; c f4_mix_b 1 "$k"; fi
    done ;;
  *) echo "unknown hold $H" >&2; exit 2 ;;
esac
snap "after-$H" | tee "$R/snap_after-$H.txt"
for node in rain sunny; do
  diff <(sort "$R/mlx5_before-${H}_$node.txt") <(sort "$R/mlx5_after-${H}_$node.txt") | grep '^>' | sed "s/^> /$node: /"
done > "$R/mlx5_new_$H.txt"
echo "new mlx5 kernel lines in hold $H: $(wc -l < "$R/mlx5_new_$H.txt")"; cat "$R/mlx5_new_$H.txt"
b=$(grep -h "cmd_err lines\|fwcmd failed sum" "$R/snap_before-$H.txt" | awk -F': ' '{s+=$2} END{print s+0}')
a=$(grep -h "cmd_err lines\|fwcmd failed sum" "$R/snap_after-$H.txt" | awk -F': ' '{s+=$2} END{print s+0}')
if [ "$a" -gt "$b" ]; then
  echo "$(date '+%F %T') hold $H: mlx5 command errors or firmware-command failures grew ($b -> $a)" | tee -a "$R/STOP_mlx5"
fi
# a CUDA memory fault in a regression trial of this hold (apprun.py checks its own trials)
cudafail=$( { find "$R/reg" -name '*_meta.txt' -newer "$R/snap_before-$H.txt" \
    -exec grep -lE ' (r[0-9]rc|rc_rain|rc_sunny)=139( |$)' {} + 2>/dev/null
  find "$R/reg" \( -name '*_r[0-9].log' -o -name '*_r[0-9].kv' \) -newer "$R/snap_before-$H.txt" \
    -exec grep -liE 'illegal address|illegal memory access|unspecified launch failure' {} + 2>/dev/null; } | sort -u)
if [ -n "$cudafail" ]; then
  echo "$(date '+%F %T') hold $H: CUDA memory fault or exit 139 in: $(echo "$cudafail" | tr '\n' ' ')" | tee -a "$R/STOP_cuda"
fi
python3 "$D/rows_gd.py" "$R" --progress
