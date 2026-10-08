#!/usr/bin/env bash
# gin-pair-check holds (each <= 15 min; each inside ../../common/cluster_run.sh -w 10800, see chain.sh).
# usage: hold.sh <resultsdir> <H0|H1|H2|H3|H4|fill:<subdir>:<cell>@<build>:<n>:<start>[,...]>
# Before and after every hold: GPU users; the full mlx5 kernel lines of both nodes (mlx5_<tag>_<node>.txt); the count of
# mlx5 command-error lines; rain's mlx5_1 firmware-command counters (debugfs, read-only). New mlx5 lines are written to
# mlx5_new_<hold>.txt and printed. A new command-error line or a growth of the firmware-command failure counters writes
# <resultsdir>/STOP_mlx5, and chain.sh runs no further hold (EXPERIMENT.md 8).
set -u
R=${1:?resultsdir}; H=${2:?hold}
D=$(cd "$(dirname "$0")" && pwd)
T=$D/../scripts/ts2
PR=$D/../pair_reset
SUNNY_SSH=${SUNNY_SSH:-unionxic@192.0.2.194}
HT=$(echo "$H" | cut -d: -f1)
CMDERR='grep -i mlx5 | grep -iE "cmd|command" | grep -icE "failed|timeout|leak"'
snap() {  # snap <tag>
  echo "== $1 $(date '+%F %T')"
  nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader 2>/dev/null | sed 's/^/rain gpu: /'
  ssh -n "$SUNNY_SSH" "nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader" 2>/dev/null | sed 's/^/sunny gpu: /'
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
snap "before-$HT" | tee "$R/snap_before-$HT.txt"
case "$H" in
  H0)  # smoke (not scored): the new cells (responder-broken, conflict and clean twice), the controls once, f3_b on pc twice,
       # one 4 KiB latency run of each build
    for c in pc_dual_f1c0_r1c2_b pc_dual_f1c0_r1c2_b pc_bidirf_conflict_b pc_bidirf_conflict_b pc_dual_f1c0_b pc_dual_f1c0_b \
             f3_b_nocheck pc_dual_f1c0_r1off_b lat_pc_on_4k; do
      n=$(ls "$R/smoke" 2>/dev/null | grep -c "^${c}_n[0-9]*_meta.txt"); bash "$D/cells.sh" "$R/smoke" $c 1 $((n + 1)); done
    bash "$PR/cells.sh" "$R/smoke" pr_dual_f1c0_b 1
    bash "$PR/cells.sh" "$R/smoke" lat_pr_on_4k 1
    BUILD=pc bash "$T/batch.sh" "$R/smoke" f3_b 2 ;;
  H1)  # latency (pc and the pr reference, interleaved), then the replication cells on pc
    for k in 1 2 3 4 5; do
      for c in lat_pr_on_4k lat_pr_on_256k; do bash "$PR/cells.sh" "$R/lat" $c 1 $k; done
      for c in lat_pc_on_4k lat_pc_on_256k; do bash "$D/cells.sh" "$R/lat" $c 1 $k; done
    done
    for c in f1_b bidirf_sym_b mt256_f1_b f4_b; do BUILD=pc bash "$T/batch.sh" "$R/rep_pc" $c 5; done
    bash "$D/cells.sh" "$R/rep_pc" f2rel_b 5 ;;
  H2)  # the clean responder (10) and the pr reference (5), interleaved 2:1; the responder-broken cell; responder switch off
    for k in 1 2 3 4 5; do
      bash "$D/cells.sh" "$R/dual" pc_dual_f1c0_b 2 $((2 * k - 1))
      bash "$PR/cells.sh" "$R/dual" pr_dual_f1c0_b 1 $k
    done
    bash "$D/cells.sh" "$R/dual" pc_dual_f1c0_r1c2_b 10
    bash "$D/cells.sh" "$R/dual" pc_dual_f1c0_r1off_b 5 ;;
  H3)  # f3_b on pc (10) and with the check off (5), interleaved 2:1; the dual replication cells
    for k in 1 2 3 4 5; do
      BUILD=pc bash "$T/batch.sh" "$R/f3" f3_b 2 $((2 * k - 1))
      bash "$D/cells.sh" "$R/f3" f3_b_nocheck 1 $k
    done
    bash "$D/cells.sh" "$R/dual" pc_dual_f3c0_b 5
    bash "$D/cells.sh" "$R/dual" pc_dual_f1all_b 5 ;;
  H4)  bash "$D/cells.sh" "$R/conflict" pc_bidirf_conflict_b 10 ;;
  fill:*)  # replacement trials: fill:<subdir>:<cell>@<build>:<n>:<start>[,...]
    spec=${H#fill:}
    IFS=',' read -ra items <<< "$spec"
    for it in "${items[@]}"; do
      IFS=':' read -r sub cb n st <<< "$it"
      c=${cb%@*}; b=${cb#*@}
      if grep -q "^    $c)" "$D/cells.sh"; then bash "$D/cells.sh" "$R/$sub" "$c" "$n" "$st"
      elif [ "$b" = pr ] || [ "$b" = prd ]; then bash "$PR/cells.sh" "$R/$sub" "$c" "$n" "$st"
      else BUILD=$b bash "$T/batch.sh" "$R/$sub" "$c" "$n" "$st"; fi
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
