#!/usr/bin/env bash
# gin-reconnect holds (each <= 15 min; each inside ../../common/cluster_run.sh -w 10800, see chain.sh).
# usage: hold.sh <resultsdir> <H0|H1|H2|H3|H4|fill:<subdir>:<cell>@<build>:<n>:<start>[,...]>
# Before and after every hold: GPU users; the full mlx5 kernel lines of both nodes (mlx5_<tag>_<node>.txt); the count of
# mlx5 command-error lines; rain's mlx5_1 firmware-command counters (debugfs, read-only). New mlx5 lines are written to
# mlx5_new_<hold>.txt and printed. A new command-error line or a growth of the firmware-command failure counters writes
# <resultsdir>/STOP_mlx5, and chain.sh runs no further hold (EXPERIMENT.md 8).
set -u
R=${1:?resultsdir}; H=${2:?hold}
D=$(cd "$(dirname "$0")" && pwd)
T=$D/../scripts/ts2
S2C=$D/../s2_close
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
  H0)  # smoke (not scored): one of each new, control and rc-only cell, the 8 s mute twice, one run of each latency build
    for c in rc_mute8_f1_b rc_mute8_f1_b rc_mutef3s_b rc_mutef3l_b rc_mutekill_b rc_mute1_f1_b rc_mute8off_b f2rel_b lat_rc_on_4k; do
      n=$(ls "$R/smoke" 2>/dev/null | grep -c "^${c}_n[0-9]*_meta.txt"); bash "$D/cells.sh" "$R/smoke" $c 1 $((n + 1)); done
    bash "$S2C/cells.sh" "$R/smoke" lat_s2r_on_4k 1
    BUILD=rc bash "$T/batch.sh" "$R/smoke" f4_b 1
    BUILD=rc bash "$T/batch.sh" "$R/smoke" f1_b 1 ;;
  H0b) # smoke 2 (not scored), after the mute-schedule fix (DEVIATIONS.md): every mute cell once, the short mute twice
    for c in rc_mutef3s_b rc_mutef3s_b rc_mute8_f1_b rc_mutef3l_b rc_mutekill_b rc_mute1_f1_b rc_mute8off_b; do
      n=$(ls "$R/smoke2" 2>/dev/null | grep -c "^${c}_n[0-9]*_meta.txt"); bash "$D/cells.sh" "$R/smoke2" $c 1 $((n + 1)); done ;;
  H1)  # latency (rc and the s2r reference, interleaved), then the regression cells on rc
    for k in 1 2 3 4 5; do
      for c in lat_s2r_on_4k lat_s2r_on_256k; do bash "$S2C/cells.sh" "$R/lat" $c 1 $k; done
      for c in lat_rc_on_4k lat_rc_on_256k; do bash "$D/cells.sh" "$R/lat" $c 1 $k; done
    done
    for c in f1_b f3_b f1g0_b mt256_f1_b bidirf_f1both_b bidirf_sym_b f4_b; do BUILD=rc bash "$T/batch.sh" "$R/rep_rc" $c 5; done
    bash "$D/cells.sh" "$R/rep_rc" f2rel_b 5 ;;
  H2)  bash "$D/cells.sh" "$R/mute" rc_mute8_f1_b 10
       bash "$D/cells.sh" "$R/mute" rc_mute1_f1_b 5
       bash "$D/cells.sh" "$R/mute" rc_mute8off_b 5 ;;
  H3)  bash "$D/cells.sh" "$R/mute" rc_mutef3s_b 10
       bash "$D/cells.sh" "$R/mute" rc_mutekill_b 10 ;;
  H4)  bash "$D/cells.sh" "$R/mute" rc_mutef3l_b 10 ;;
  fill:*)  # replacement trials: fill:<subdir>:<cell>@<build>:<n>:<start>[,...]
    spec=${H#fill:}
    IFS=',' read -ra items <<< "$spec"
    for it in "${items[@]}"; do
      IFS=':' read -r sub cb n st <<< "$it"
      c=${cb%@*}; b=${cb#*@}
      if grep -q "^    $c)" "$D/cells.sh"; then bash "$D/cells.sh" "$R/$sub" "$c" "$n" "$st"
      elif [ "$b" = s2r ]; then bash "$S2C/cells.sh" "$R/$sub" "$c" "$n" "$st"
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
