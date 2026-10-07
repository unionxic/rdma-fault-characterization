#!/usr/bin/env bash
# gin-s2-close holds (each <= 15 min; run each one inside ../../common/cluster_run.sh -w 10800, see chain.sh).
# usage: hold.sh <resultsdir> <H0|H1|H2|H3|H4|H5|H6|fill:<subdir>:<cell>@<build>:<n>:<start>[,...]>
# Results: <resultsdir>/<subdir>/ per hold. Before and after: GPU users, mlx5 kernel lines and mlx5 command-error lines on
# both nodes, rain's mlx5_1 firmware-command counters (debugfs, read-only). If a new mlx5 command-error line appears or
# a failure counter grows, the hold writes <resultsdir>/STOP_mlx5 and chain.sh runs no further hold (EXPERIMENT.md 8).
set -u
R=${1:?resultsdir}; H=${2:?hold}
D=$(cd "$(dirname "$0")" && pwd)
T=$D/../scripts/ts2
SUNNY_SSH=${SUNNY_SSH:-unionxic@192.0.2.194}
CMDERR='grep -i mlx5 | grep -iE "cmd|command" | grep -icE "failed|timeout|leak"'
snap() {  # snap <tag>
  echo "== $1 $(date '+%F %T')"
  nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader 2>/dev/null | sed 's/^/rain gpu: /'
  ssh -n "$SUNNY_SSH" "nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader" 2>/dev/null | sed 's/^/sunny gpu: /'
  echo "rain mlx5 dmesg lines: $(sudo -n dmesg 2>/dev/null | grep -ic mlx5)"
  echo "sunny mlx5 dmesg lines: $(ssh -n "$SUNNY_SSH" "sudo -n dmesg 2>/dev/null | grep -ic mlx5")"
  echo "rain mlx5 cmd_err lines: $(sudo -n dmesg 2>/dev/null | eval "$CMDERR")"
  echo "sunny mlx5 cmd_err lines: $(ssh -n "$SUNNY_SSH" "sudo -n dmesg 2>/dev/null | $CMDERR")"
  bash "$D/../scripts/ts1/fwcmd_snapshot.sh" "$1" > "$R/fwcmd_$1.txt" 2>&1
  echo "rain fwcmd failed sum: $(awk '{for(i=1;i<=NF;i++) if($i ~ /^failed=|^failed_mbox_status=/){split($i,a,"="); s+=a[2]}} END{print s+0}' "$R/fwcmd_$1.txt")"
}
mkdir -p "$R"
snap "before-$H" | tee "$R/snap_before-$H.txt"
case "$H" in
  H0)  # smoke (not scored): one of each new and control cell, the 8 s mute twice, one new-library latency run
    for c in f2rel_b ringf2rel_b f2rel_off_b get_none_b get_f1_b mt1024_norescue_b mute1_f1_b mute_f3_b lat_s2r_on_4k; do
      bash "$D/cells.sh" "$R/smoke" $c 1; done
    bash "$D/cells.sh" "$R/smoke" mute8_f1_b 2
    BUILD=s2r bash "$T/batch.sh" "$R/smoke" off_f1_b 1
    BUILD=s2r bash "$T/batch.sh" "$R/smoke" f1_b 1 ;;
  H1)  # gate micro-test, then latency: the twelve step-2 latency cells and the two new-library cells, interleaved
    bash "$T/gate_test.sh" "$R/gate_test.txt" 10
    for k in 1 2 3 4 5; do
      for c in lat_base_4k lat_s1off_4k lat_s1on_4k lat_s2off_4k lat_s2on_4k lat_s2sys_4k \
               lat_base_256k lat_s1off_256k lat_s1on_256k lat_s2off_256k lat_s2on_256k lat_s2sys_256k; do
        bash "$T/batch.sh" "$R/lat" $c 1 $k; done
      for c in lat_s2r_on_4k lat_s2r_on_256k; do bash "$D/cells.sh" "$R/lat" $c 1 $k; done
    done ;;
  H2)  # final step-2 build: 16 and 64 threads, symmetric initiation with real bidirectional traffic (tie-break on/off)
    for c in mt16_f1_b mt64_f1_b bidirf_sym_b bidirf_sym_notie_b; do bash "$T/batch.sh" "$R/rep_s2" $c 5; done ;;
  H3)  # the receiving rank's wait released at abort; controls
    bash "$D/cells.sh" "$R/rel" f2rel_b 10
    bash "$D/cells.sh" "$R/rel" ringf2rel_b 10
    bash "$D/cells.sh" "$R/rel" f2rel_off_b 5
    BUILD=s2r bash "$T/batch.sh" "$R/rel" off_f1_b 5 ;;
  H4)  # new library: recovered and declined cells re-run
    for c in f1_b f3_b f1g0_b mt256_f1_b bidirf_f1both_b f4_b; do BUILD=s2r bash "$T/batch.sh" "$R/rep_s2r" $c 5; done ;;
  H5)  # a get in the epoch; the rescue area off
    bash "$D/cells.sh" "$R/nonmsg" get_f1_b 10
    bash "$D/cells.sh" "$R/nonmsg" get_none_b 5
    bash "$D/cells.sh" "$R/nonmsg" mt1024_norescue_b 5 ;;
  H6)  # the management socket muted
    bash "$D/cells.sh" "$R/mute" mute8_f1_b 10
    bash "$D/cells.sh" "$R/mute" mute_f3_b 10
    bash "$D/cells.sh" "$R/mute" mute1_f1_b 5 ;;
  fill:*)  # replacement trials for excluded ones: fill:<subdir>:<cell>@<build>:<n>:<start>[,...]
    spec=${H#fill:}
    IFS=',' read -ra items <<< "$spec"
    for it in "${items[@]}"; do
      IFS=':' read -r sub cb n st <<< "$it"
      c=${cb%@*}; b=${cb#*@}
      if grep -q "^    $c)" "$D/cells.sh"; then bash "$D/cells.sh" "$R/$sub" "$c" "$n" "$st"
      elif [ "$b" = s2 ]; then bash "$T/batch.sh" "$R/$sub" "$c" "$n" "$st"
      else BUILD=$b bash "$T/batch.sh" "$R/$sub" "$c" "$n" "$st"; fi
    done ;;
  *) echo "unknown hold $H" >&2; exit 2 ;;
esac
snap "after-$H" | tee "$R/snap_after-$H.txt"
b=$(grep -h "cmd_err lines\|fwcmd failed sum" "$R/snap_before-$H.txt" | awk -F': ' '{s+=$2} END{print s+0}')
a=$(grep -h "cmd_err lines\|fwcmd failed sum" "$R/snap_after-$H.txt" | awk -F': ' '{s+=$2} END{print s+0}')
if [ "$a" -gt "$b" ]; then
  echo "$(date '+%F %T') hold $H: mlx5 command errors or firmware-command failures grew ($b -> $a)" | tee -a "$R/STOP_mlx5"
fi
