#!/usr/bin/env bash
# gin-handoff holds (each <= 15 min; each inside ../../common/cluster_run.sh -w 10800, see chain.sh).
# usage: hold.sh <resultsdir> <H0|H1|H2|H3|H4|fill:<subdir>:<cell>@<build>:<n>:<start>[,...]>
# Trial folders under <resultsdir>, one per build: hf/, hfp/, hd/, hdp/ (latency runs included).
# Before and after every hold (as ../harden/hold.sh): GPU users; the full mlx5 kernel lines of both nodes
# (mlx5_<tag>_<node>.txt); the count of mlx5 command-error lines; rain's mlx5_1 firmware-command counters (debugfs,
# read-only); the number of iptables INPUT rules on rain tagged "gin-harden-" (this study never adds one: no cell sets
# MGMT_MUTE, the only switch of ../harden/run_trial_hd.sh that does; nothing is deleted here). New mlx5 lines are written
# to mlx5_new_<hold>.txt and printed. A new command-error line or a growth of the firmware-command failure counters
# writes <resultsdir>/STOP_mlx5, more tagged iptables rules after the hold than before writes STOP_iptables, and a CUDA
# memory fault in a trial writes STOP_cuda; chain.sh then runs no further hold (EXPERIMENT.md 8). Processes are never
# killed here (run_trial_hd.sh kills only PIDs it recorded).
set -u
R=${1:?resultsdir}; H=${2:?hold}
D=$(cd "$(dirname "$0")" && pwd)
SUNNY_SSH=${SUNNY_SSH:-unionxic@192.0.2.194}
HT=$(echo "$H" | cut -d: -f1)
CMDERR='grep -i mlx5 | grep -iE "cmd|command" | grep -icE "failed|timeout|leak"'
ipt_tagged() { sudo -n iptables -w 5 -S INPUT 2>/dev/null | grep -c -- "gin-harden-" ; }
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
  echo "rain gin-harden-tagged iptables rules: $(ipt_tagged)"
}
mkdir -p "$R"
snap "before-$HT" | tee "$R/snap_before-$HT.txt"
c() { bash "$D/cells.sh" "$R/$3" "$1" "$2" "${4:-1}" "${5:-1}"; }  # c <cell> <build> <subdir> [n] [start]
next() { echo $(( $(ls "$R/$3" 2>/dev/null | grep -c "^${1}_n[0-9]*_meta.txt") + 1 )); }  # next <cell> <build> <subdir>
one() { c "$1" "$2" "$3" 1 "$(next "$1" "$2" "$3")"; }  # one more trial with the next free number
case "$H" in
  H0)  # pilot (not scored): every new cell once, the shrink cell once per build, two regression cells, 4 KiB latency
       # once per build
    one hd_shrink_b hf hf
    one hd_shrink_b hd hd
    one hd_shrink_b hfp hfp
    one hf_shrinkoff_b hf hf
    one hf_shrinkdc_b hf hf
    for x in hf_hog_f1_b hf_hogslack_f1_b hf_hogpre_f1_b hf_hogpreslack_f1_b; do one $x hf hf; done
    one f1_b hf hf
    one f4_b hf hf
    for b in hfp hdp hd; do one lat_4k $b $b; done ;;
  H1)  # shrink hand-off: hf 10, hd 5 (control), hfp 5, switch off 5, devComm destroyed first 5, interleaved
    for k in 1 2 3 4 5; do
      c hd_shrink_b hf hf 2 $((2 * k - 1))
      c hd_shrink_b hd hd 1 $k
      c hd_shrink_b hfp hfp 1 $k
      c hf_shrinkoff_b hf hf 1 $k
      c hf_shrinkdc_b hf hf 1 $k
    done ;;
  H2)  # the GPU full of an application kernel: the 2 x 2 (calls between the launches or none; full grid or one block
       # smaller), 5 each, interleaved
    for k in 1 2 3 4 5; do
      for x in hf_hog_f1_b hf_hogslack_f1_b hf_hogpre_f1_b hf_hogpreslack_f1_b; do c $x hf hf 1 $k; done
    done ;;
  H3)  # regression (hf, and the production kill on hfp)
    for x in f1_b f3_b bidirf_sym_b f4_b f2rel_b hd_rxdeath_b; do c $x hf hf 5; done
    c hdp_kill_b hfp hfp 5 ;;
  H4)  # latency: hfp, hdp, hd interleaved, 4 KiB and 256 KiB, 5 runs each
    for k in 1 2 3 4 5; do for x in lat_4k lat_256k; do for b in hfp hdp hd; do c $x $b $b 1 $k; done; done; done ;;
  fill:*)  # replacement trials: fill:<subdir>:<cell>@<build>:<n>:<start>[,...]
    spec=${H#fill:}
    IFS=',' read -ra items <<< "$spec"
    for it in "${items[@]}"; do
      IFS=':' read -r sub cb n st <<< "$it"
      c "${cb%@*}" "${cb#*@}" "$sub" "$n" "$st"
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
ib=$(grep -h "iptables rules" "$R/snap_before-$HT.txt" | awk -F': ' '{print $2+0}')
ia=$(grep -h "iptables rules" "$R/snap_after-$HT.txt" | awk -F': ' '{print $2+0}')
if [ "${ia:-0}" -gt "${ib:-0}" ]; then
  echo "$(date '+%F %T') hold $H: gin-harden-tagged iptables rules grew ($ib -> $ia); this study adds none" | tee -a "$R/STOP_iptables"
fi
# a CUDA memory fault in any trial of this hold: rank exit code 139 or an illegal-address / launch-failure line
cudafail=$( { find "$R" -name '*_meta.txt' -newer "$R/snap_before-$HT.txt" -exec grep -lE ' r[01]rc=139 ' {} + 2>/dev/null
  find "$R" \( -name '*_r0.log' -o -name '*_r1.log' -o -name '*_r0.kv' -o -name '*_r1.kv' \) -newer "$R/snap_before-$HT.txt" \
    -exec grep -liE 'illegal address|illegal memory access|unspecified launch failure' {} + 2>/dev/null; } | sort -u)
if [ -n "$cudafail" ]; then
  echo "$(date '+%F %T') hold $H: CUDA memory fault or exit 139 in: $(echo "$cudafail" | tr '\n' ' ')" | tee -a "$R/STOP_cuda"
fi
