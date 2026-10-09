#!/usr/bin/env bash
# gin-remaining holds (each <= 15 min; each inside ../../common/cluster_run.sh -w 10800, see chain.sh). A copy of
# ../peer/hold.sh with this study's holds, the benchmark's files in the stale and CUDA-fault checks, nothing else changed.
# usage: hold.sh <resultsdir> <P0|P1|H1|...|H5|fill:<subdir>:<cell>@<build>:<n>:<start>[,...]>
# Trial folders under <resultsdir>: two-rank trials in <build>/ (hr/, hq/, hrp/, hqp/), N-rank trials in mr_<lib>/
# (mr_hr/, mr_hq/), the benchmark in bench/, the NIC gate test in ngt/. P0, P1 and P2 are pilots (never scored; chain.sh
# writes them into their own results folder).
# Before and after every hold: GPU users and compute mode of both nodes; the full mlx5 kernel lines of both nodes
# (mlx5_<tag>_<node>.txt); the count of mlx5 command-error lines; rain's mlx5_1 firmware-command counters (debugfs,
# read-only). New mlx5 lines go to mlx5_new_<hold>.txt. A new command-error line or a growth of the firmware-command
# failure counters writes <resultsdir>/STOP_mlx5; a CUDA memory fault in a trial (exit 139, illegal address) writes
# STOP_cuda; two trials in a row that left a process behind write STOP_left (cells.sh). chain.sh then runs no further
# hold (EXPERIMENT.md 8). This study adds no iptables rule. Processes are never killed here (the runners kill only PIDs
# they recorded); a gin_ts2 or gin_mr left by an earlier hold that its timeout cut is waited for (read-only count, at
# most 150 s), else no trial runs (STOP_left).
set -u
R=${1:?resultsdir}; H=${2:?hold}
D=$(cd "$(dirname "$0")" && pwd)
SUNNY_SSH=${SUNNY_SSH:-unionxic@192.0.2.194}
HT=$(echo "$H" | cut -d: -f1)
CMDERR='grep -i mlx5 | grep -iE "cmd|command" | grep -icE "failed|timeout|leak"'
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
  bash "$D/../scripts/ts1/fwcmd_snapshot.sh" "$1" > "$R/fwcmd_$1.txt" 2>&1
  echo "rain fwcmd failed sum: $(awk '{for(i=1;i<=NF;i++) if($i ~ /^failed=|^failed_mbox_status=/){split($i,a,"="); s+=a[2]}} END{print s+0}' "$R/fwcmd_$1.txt")"
}
mkdir -p "$R"
for i in $(seq 1 30); do
  stale=$( { pgrep -x gin_mr; pgrep -x gin_ts2; pgrep -x hm_bench; pgrep -x nic_gate_test
             ssh -n "$SUNNY_SSH" "pgrep -x gin_mr; pgrep -x gin_ts2; pgrep -x hm_bench; pgrep -x nic_gate_test"; } 2>/dev/null | wc -l)
  [ "$stale" -eq 0 ] && break
  echo "$(date '+%F %T') hold $HT: $stale gin_mr/gin_ts2/hm_bench/nic_gate_test process(es) still present; waiting" | tee -a "$R/stale.txt"
  sleep 5
done
[ "$stale" -eq 0 ] || echo "$(date '+%F %T') hold $HT: gin_mr/gin_ts2/hm_bench/nic_gate_test still present after 150 s; no trial runs" | tee -a "$R/STOP_left"
snap "before-$HT" | tee "$R/snap_before-$HT.txt"
sub() { case "$1" in mr4_*|rm4_*) echo "mr_$2" ;; hm_bench) echo bench ;; nic_gate) echo ngt ;; *) echo "$2" ;; esac; }  # the trial folder
c() { [ -e "$R/STOP_left" ] || bash "$D/cells.sh" "$R/$(sub "$1" "$2")" "$1" "$2" "${3:-1}" "${4:-1}"; }  # c <cell> <build> [n] [start]
alt21() {  # alt21 <cell> <new build> <control build>: 10 trials of the new build and 5 of the control, 2:1
  local k; for k in 1 2 3 4 5; do c "$1" "$2" 2 $((2 * k - 1)); c "$1" "$3" 1 "$k"; done
}
case "$H" in
  P0)  # pilot, two ranks (not scored): every new two-rank cell and control once, two regression cells, one latency run per
       # build
    c rh_hog_f1_b hr; c rh_hog_f1_b hq; c rh_hog_copystream_f1_b hr
    for x in rh_hogcall_load_f1_b rh_hogcall_malloc_f1_b rh_hogcall_stream_f1_b; do c $x hq; c $x hr; done
    c f1_b hr; c f4_b hr
    c lat_4k hrp; c lat_4k hqp ;;
  P1)  # pilot, four ranks and the benchmark (not scored): every new four-rank cell and control once
    c mr4_cyc_stall hr; c mr4_cyc_stall hq
    c rm4_kill3_untimed hr; c rm4_kill3_untimed hq
    c mr4_kill3_peer hr; c mr4_chain_stall hr
    c hm_bench hr ;;
  P2)  # pilot after the first pilot (not scored): the NIC gate test once (added after P0 and P1, EXPERIMENT.md 12)
    c nic_gate hr ;;
  H1)  # two-rank regression (hr), the production kill (hrp), then latency (hrp, hqp, two sizes, interleaved)
    for x in f1_b f3_b bidirf_sym_b f4_b f2rel_b hd_rxdeath_b; do c $x hr 5; done
    c hdp_kill_b hrp 5
    for k in 1 2 3 4 5; do for x in lat_4k lat_256k; do for b in hrp hqp; do c $x $b 1 $k; done; done; done ;;
  H2)  # problem 3: the GPU-full order (hr 10, hq 5, 2:1), the stream copies inside hr (5), the three calls one at a time
       # (hq 5 each, hr 3 each, interleaved)
    alt21 rh_hog_f1_b hr hq
    c rh_hog_copystream_f1_b hr 5
    for k in 1 2 3 4 5; do
      for x in rh_hogcall_load_f1_b rh_hogcall_malloc_f1_b rh_hogcall_stream_f1_b; do
        c $x hq 1 $k
        [ "$k" -le 3 ] && c $x hr 1 $k
      done
    done ;;
  H3)  # problem 1: the cycle (hr 10, hq 5, 2:1), the chain (hr 5)
    alt21 mr4_cyc_stall hr hq
    c mr4_chain_stall hr 5 ;;
  H4)  # problem 2: rank 3 killed with untimed receives (hr 10, hq 5, 2:1), gin-peer's timed form (hr 5)
    alt21 rm4_kill3_untimed hr hq
    c mr4_kill3_peer hr 5 ;;
  H5)  # four-rank regression (hr 5 each), the host-memory benchmark (5 runs, each on both nodes), then the NIC gate test
       # (5 runs, each on both nodes)
    c mr4_none hr 5
    c mr4_f1_01 hr 5
    c hm_bench hr 5
    c nic_gate hr 5 ;;
  fill:*)  # replacement trials: fill:<subdir>:<cell>@<build>:<n>:<start>[,...] (subdir as above: <build> or mr_<lib>)
    spec=${H#fill:}
    IFS=',' read -ra items <<< "$spec"
    for it in "${items[@]}"; do
      IFS=':' read -r sd cb n st <<< "$it"
      [ -e "$R/STOP_left" ] || bash "$D/cells.sh" "$R/$sd" "${cb%@*}" "${cb#*@}" "$n" "$st"
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
# a CUDA memory fault in any trial of this hold (a kernel still reading a freed abort word would fault): a rank exit code
# 139 or an illegal-address / launch-failure line
cudafail=$( { find "$R" -name '*_meta.txt' -newer "$R/snap_before-$HT.txt" \
    -exec grep -lE ' (r[0-9]rc|rc_rain|rc_sunny)=139( |$)' {} + 2>/dev/null
  find "$R" \( -name '*_r[0-9].log' -o -name '*_r[0-9].kv' -o -name '*_rain.kv' -o -name '*_rain.log' \
    -o -name '*_sunny.kv' -o -name '*_sunny.log' \) \
    -newer "$R/snap_before-$HT.txt" \
    -exec grep -liE 'illegal address|illegal memory access|unspecified launch failure' {} + 2>/dev/null; } | sort -u)
if [ -n "$cudafail" ]; then
  echo "$(date '+%F %T') hold $H: CUDA memory fault or exit 139 in: $(echo "$cudafail" | tr '\n' ' ')" | tee -a "$R/STOP_cuda"
fi
