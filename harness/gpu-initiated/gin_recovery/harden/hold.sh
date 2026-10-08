#!/usr/bin/env bash
# gin-harden holds (each <= 15 min; each inside ../../common/cluster_run.sh -w 10800, see chain.sh).
# usage: hold.sh <resultsdir> <H0|H1|...|H8|fill:<subdir>:<cell>@<build>:<n>:<start>[,...]>
# Trial folders under <resultsdir>, one per build: hd/, ow/, ow2/, hdp/, stk/ (latency runs included).
# Before and after every hold: GPU users; the full mlx5 kernel lines of both nodes (mlx5_<tag>_<node>.txt); the count of
# mlx5 command-error lines; rain's mlx5_1 firmware-command counters (debugfs, read-only); this study's iptables rules on
# rain (comment "gin-harden-<pid>", added only by run_trial_hd.sh's MGMT_MUTE). New mlx5 lines are written to
# mlx5_new_<hold>.txt and printed. A new command-error line, a growth of the firmware-command failure counters, or a
# gin-harden iptables rule that is still present after the hold writes <resultsdir>/STOP_mlx5 (or STOP_iptables), and
# chain.sh runs no further hold (EXPERIMENT.md 8). So does a CUDA memory fault in a trial (STOP_cuda). Processes are never killed here (run_trial_hd.sh kills only PIDs it
# recorded).
set -u
R=${1:?resultsdir}; H=${2:?hold}
D=$(cd "$(dirname "$0")" && pwd)
SUNNY_SSH=${SUNNY_SSH:-unionxic@192.0.2.194}
HT=$(echo "$H" | cut -d: -f1)
CMDERR='grep -i mlx5 | grep -iE "cmd|command" | grep -icE "failed|timeout|leak"'
ipt_ours() { sudo -n iptables -w 5 -S INPUT 2>/dev/null | grep -c -- "gin-harden-" ; }
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
  echo "rain gin-harden iptables rules: $(ipt_ours)"
}
mkdir -p "$R"
snap "before-$HT" | tee "$R/snap_before-$HT.txt"
c() { bash "$D/cells.sh" "$R/$3" "$1" "$2" "${4:-1}" "${5:-1}"; }  # c <cell> <build> <subdir> [n] [start]
next() { echo $(( $(ls "$R/$3" 2>/dev/null | grep -c "^${1}_n[0-9]*_meta.txt") + 1 )); }  # next <cell> <build> <subdir>
one() { c "$1" "$2" "$3" 1 "$(next "$1" "$2" "$3")"; }  # one more trial with the next free number
case "$H" in
  H0)  # pilot (not scored): every new cell once on hd, every contrast once, the production cells once, latency once per
       # build, both IB-timeout-20 cells once, two regression cells whose log lines changed (BYE, two refusals)
    for x in hd_ref1_f1_b hd_ref2_f1_b hd_nonce_f1_b hd_rround_f1_b hd_rxdeath_b hd_hog_f1_b hd_fwslow_f1_b \
             hd_copystall_f1_b hd_repost_f1_b hd_esc_f1_b hd_shrink_b rc_mute8_f1_b ow_kill0_b; do one $x hd hd; done
    for x in hd_rround_f1_b hd_rxdeath_b hd_fwslow_f1_b hd_esc_f1_b; do one $x ow ow; done
    one hd_shrink_b ow2 ow2
    one hdp_kill_b hdp hdp
    one hdp_mute_b hdp hdp
    for b in hdp ow stk; do one lat_4k $b $b; done
    one to20_f3_t hd hd
    one to20_f3_b hd hd ;;
  H1)  # regression part A (hd), then latency (hdp, ow, stk interleaved)
    for x in f1_b f3_b bidirf_sym_b f4_b f2rel_b pc_dual_f1c0_r1c2_b; do c $x hd hd 5; done
    for k in 1 2 3 4 5; do for x in lat_4k lat_256k; do for b in hdp ow stk; do c $x $b $b 1 $k; done; done; done ;;
  H2)  # regression part B: the mute and kill cells of gin-reconnect and gin-oneway (hd)
    for x in rc_mute8_f1_b rc_mutekill_b ow_r1in_f1_b ow_r0in_f1r1_b ow_kill0_b; do c $x hd hd 5; done ;;
  H3)  # the refused-HELLO regression, then refusal once and twice (hd)
    c ow_hello_f1_b hd hd 5
    c hd_ref1_f1_b hd hd 10
    c hd_ref2_f1_b hd hd 10 ;;
  H4)  # wrong nonce (hd), then the reset inside a round (hd 10 and ow 5, interleaved 2:1)
    c hd_nonce_f1_b hd hd 10
    for k in 1 2 3 4 5; do c hd_rround_f1_b hd hd 2 $((2 * k - 1)); c hd_rround_f1_b ow ow 1 $k; done ;;
  H5)  # receive-only peer death (2:1), the GPU full of an application kernel (hd), the slow firmware phase (2:1)
    for k in 1 2 3 4 5; do c hd_rxdeath_b hd hd 2 $((2 * k - 1)); c hd_rxdeath_b ow ow 1 $k; done
    c hd_hog_f1_b hd hd 10
    for k in 1 2 3 4 5; do c hd_fwslow_f1_b hd hd 2 $((2 * k - 1)); c hd_fwslow_f1_b ow ow 1 $k; done ;;
  H6)  # escalation (2:1), shrink hand-off (hd 10, ow2 5, 2:1), the stalled copy and the rejected re-post plan (hd)
    for k in 1 2 3 4 5; do c hd_esc_f1_b hd hd 2 $((2 * k - 1)); c hd_esc_f1_b ow ow 1 $k; done
    for k in 1 2 3 4 5; do c hd_shrink_b hd hd 2 $((2 * k - 1)); c hd_shrink_b ow2 ow2 1 $k; done
    c hd_copystall_f1_b hd hd 10
    c hd_repost_f1_b hd hd 10 ;;
  H7)  # production cells without any hook or switch, then the IB timeout 20 cell with the device-side timeout (hd)
    c hdp_kill_b hdp hdp 5
    c hdp_mute_b hdp hdp 5
    c to20_f3_t hd hd 3 ;;
  H8)  # the IB timeout 20 cell with the blocking flush (hd): about 60-70 s per trial, at most 110 s (its watchdog)
    c to20_f3_b hd hd 5 ;;
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
left=$(ipt_ours)
if [ "$left" != 0 ]; then
  echo "$(date '+%F %T') hold $H: $left gin-harden iptables rule(s) still present after the hold" | tee -a "$R/STOP_iptables"
fi
# a CUDA memory fault in any trial of this hold (the user devComm's abort word is freed with the communicator: a kernel
# still reading it would fault; EXPERIMENT.md 8): rank exit code 139 or an illegal-address / launch-failure line
cudafail=$( { find "$R" -name '*_meta.txt' -newer "$R/snap_before-$HT.txt" -exec grep -lE ' r[01]rc=139 ' {} + 2>/dev/null
  find "$R" \( -name '*_r0.log' -o -name '*_r1.log' -o -name '*_r0.kv' -o -name '*_r1.kv' \) -newer "$R/snap_before-$HT.txt" \
    -exec grep -liE 'illegal address|illegal memory access|unspecified launch failure' {} + 2>/dev/null; } | sort -u)
if [ -n "$cudafail" ]; then
  echo "$(date '+%F %T') hold $H: CUDA memory fault or exit 139 in: $(echo "$cudafail" | tr '\n' ' ')" | tee -a "$R/STOP_cuda"
fi
