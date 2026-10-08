#!/usr/bin/env bash
# gin-oneway holds (each <= 15 min; each inside ../../common/cluster_run.sh -w 10800, see chain.sh).
# usage: hold.sh <resultsdir> <H0|H1|H2|H3|H4|H5|fill:<subdir>:<cell>@<build>:<n>:<start>[,...]>
# Trial folders under <resultsdir>: ow/, pcm/, pc/ (by build) and lat/ (latency runs of both builds).
# Before and after every hold: GPU users; the full mlx5 kernel lines of both nodes (mlx5_<tag>_<node>.txt); the count of
# mlx5 command-error lines; rain's mlx5_1 firmware-command counters (debugfs, read-only). New mlx5 lines are written to
# mlx5_new_<hold>.txt and printed. A new command-error line or a growth of the firmware-command failure counters writes
# <resultsdir>/STOP_mlx5, and chain.sh runs no further hold (EXPERIMENT.md 8).
set -u
R=${1:?resultsdir}; H=${2:?hold}
D=$(cd "$(dirname "$0")" && pwd)
T=$D/../scripts/ts2
PC=$D/../pair_check
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
c() { bash "$D/cells.sh" "$R/$2" "$1" "$2" "${3:-1}" "${4:-1}"; }  # c <cell> <build> [n] [start]
next() { echo $(( $(ls "$R/$2" 2>/dev/null | grep -c "^${1}_n[0-9]*_meta.txt") + 1 )); }  # next free trial number
case "$H" in
  H0)  # smoke (not scored): the manipulation of the one-way cells twice on the reference build, the kill cell twice on
       # ow, every new cell at least once on each build, the race cell once on pc, a symmetric mute once, latency once
    for cb in ow_r1in_f1_b:pcm ow_r1in_f1_b:pcm ow_r1in_f1_b:ow ow_r0in_f1r1_b:pcm ow_r0in_f1r1_b:pcm ow_r0in_f1r1_b:ow \
              ow_kill0_b:ow ow_kill0_b:ow ow_kill0_b:pcm ow_hello_f1_b:pcm ow_hello_f1_b:ow ow_r0in_nat_f1r1_b:pc \
              rc_mute8_f1_b:ow; do
      cl=${cb%:*}; b=${cb#*:}; c "$cl" "$b" 1 "$(next "$cl" "$b")"; done
    c lat_ow_on_4k lat 1 1
    bash "$PC/cells.sh" "$R/lat" lat_pc_on_4k 1 1 ;;
  H1)  # latency (ow and the pc reference, interleaved), then the replication cells on ow
    for k in 1 2 3 4 5; do
      for x in lat_pc_on_4k lat_pc_on_256k; do bash "$PC/cells.sh" "$R/lat" $x 1 $k; done
      for x in lat_ow_on_4k lat_ow_on_256k; do c $x lat 1 $k; done
    done
    for x in f1_b f3_b bidirf_sym_b f4_b; do BUILD=ow bash "$T/batch.sh" "$R/ow" $x 5; done
    c f2rel_b ow 5 ;;
  H2)  # the symmetric-mute replications, then the lower rank receiving the reset (ow 10 and pcm 5, interleaved 2:1)
    c rc_mute8_f1_b ow 5
    c rc_mutekill_b ow 5
    for k in 1 2 3 4 5; do c ow_r1in_f1_b ow 2 $((2 * k - 1)); c ow_r1in_f1_b pcm 1 $k; done ;;
  H3)  # the higher rank receiving the reset (2:1), then the race without the timeout switch (pc and ow, 1:1)
    for k in 1 2 3 4 5; do c ow_r0in_f1r1_b ow 2 $((2 * k - 1)); c ow_r0in_f1r1_b pcm 1 $k; done
    for k in 1 2 3 4 5; do c ow_r0in_nat_f1r1_b pc 1 $k; c ow_r0in_nat_f1r1_b ow 1 $k; done ;;
  H4)  for k in 1 2 3 4 5; do c ow_kill0_b ow 2 $((2 * k - 1)); c ow_kill0_b pcm 1 $k; done ;;
  H5)  for k in 1 2 3 4 5; do c ow_hello_f1_b ow 2 $((2 * k - 1)); c ow_hello_f1_b pcm 1 $k; done ;;
  fill:*)  # replacement trials: fill:<subdir>:<cell>@<build>:<n>:<start>[,...]
    spec=${H#fill:}
    IFS=',' read -ra items <<< "$spec"
    for it in "${items[@]}"; do
      IFS=':' read -r sub cb n st <<< "$it"
      x=${cb%@*}; b=${cb#*@}
      if grep -q "^    $x)" "$D/cells.sh"; then bash "$D/cells.sh" "$R/$sub" "$x" "$b" "$n" "$st"
      elif [ "$b" = pc ]; then bash "$PC/cells.sh" "$R/$sub" "$x" "$n" "$st"
      else BUILD=$b bash "$T/batch.sh" "$R/$sub" "$x" "$n" "$st"; fi
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
