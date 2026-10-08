#!/usr/bin/env bash
# gin-peer holds (each <= 15 min; each inside ../../common/cluster_run.sh -w 10800, see chain.sh).
# usage: hold.sh <resultsdir> <P0|P1|P2|H1|...|H8|fill:<subdir>:<cell>@<build>:<n>:<start>[,...]>
# Trial folders under <resultsdir>: two-rank trials in <build>/ (hq/, hf/, hqp/, hfp/), N-rank trials in mr_<lib>/
# (mr_hq/, mr_hf/). P0, P1 and P2 are pilots (never scored; chain.sh writes them into their own results folder).
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
  stale=$( { pgrep -x gin_mr; pgrep -x gin_ts2; ssh -n "$SUNNY_SSH" "pgrep -x gin_mr; pgrep -x gin_ts2"; } 2>/dev/null | wc -l)
  [ "$stale" -eq 0 ] && break
  echo "$(date '+%F %T') hold $HT: $stale gin_mr/gin_ts2 process(es) still present; waiting" | tee -a "$R/stale.txt"
  sleep 5
done
[ "$stale" -eq 0 ] || echo "$(date '+%F %T') hold $HT: gin_mr/gin_ts2 still present after 150 s; no trial runs" | tee -a "$R/STOP_left"
snap "before-$HT" | tee "$R/snap_before-$HT.txt"
sub() { case "$1" in mr4_*|pq4_*) echo "mr_$2" ;; *) echo "$2" ;; esac; }  # sub <cell> <build>: the trial folder
c() { [ -e "$R/STOP_left" ] || bash "$D/cells.sh" "$R/$(sub "$1" "$2")" "$1" "$2" "${3:-1}" "${4:-1}"; }  # c <cell> <build> [n] [start]
alt21() {  # alt21 <cell> <new build> <control build>: 10 trials of the new build and 5 of the control, 2:1
  local k; for k in 1 2 3 4 5; do c "$1" "$2" 2 $((2 * k - 1)); c "$1" "$3" 1 "$k"; done
}
case "$H" in
  P0)  # pilot, two ranks (not scored): every new two-rank cell and its control once, the regression form of 3b, the
       # port-fix cell, one transparent regression cell, one latency run per build
    for x in pq_repost_r1_b pq_ackrace_f1_b pq_ackrace_f1r1_b pq_copystall_shrink_b; do c $x hq; c $x hf; done
    for x in hd_fwslow_f1_b pq_copystall1_shrink_b pq_rdv_b f1_b; do c $x hq; done
    c lat_4k hqp; c lat_4k hfp ;;
  P2)  # second pilot after the first (not scored): the two ACK-race cells changed after P0 (the responder now stays
       # 12 s; EXPERIMENT.md 12), once per build
    for x in pq_ackrace_f1_b pq_ackrace_f1r1_b; do c $x hq; c $x hf; done ;;
  P1)  # pilot, four ranks (not scored): every new four-rank cell and its control once
    c mr4_kill3_peer hq; c mr4_kill3_peer hf
    c pq4_fwslow hq; c pq4_fwslow hf
    c pq4_kill3_shrink hq
    c pq4_local_shrink hq; c pq4_local_shrink hf
    c pq4_rdv hq ;;
  H1)  # two-rank regression (hq), the production kill (hqp), then latency (hqp, hfp, two sizes, interleaved)
    for x in f1_b f3_b bidirf_sym_b f4_b f2rel_b hd_rxdeath_b; do c $x hq 5; done
    c hdp_kill_b hqp 5
    for k in 1 2 3 4 5; do for x in lat_4k lat_256k; do for b in hqp hfp; do c $x $b 1 $k; done; done; done ;;
  H2)  # 3a (responder rejects: hq 10, hf 5, 2:1; initiator rejects: hq 5), 3b at two ranks (hq 5), the port-fix cell (hq 5)
    alt21 pq_repost_r1_b hq hf
    c hd_repost_f1_b hq 5
    c hd_fwslow_f1_b hq 5
    c pq_rdv_b hq 5 ;;
  H3)  # 3c: the HELLO form (hq 10, hf 5, 2:1), the PROBE form (hq 5, hf 5, 1:1)
    alt21 pq_ackrace_f1_b hq hf
    for k in 1 2 3 4 5; do c pq_ackrace_f1r1_b hq 1 $k; c pq_ackrace_f1r1_b hf 1 $k; done ;;
  H4)  # 4 at two ranks: a cause on rank 0 (hq 10, hf 5, 2:1), a cause on rank 1 (hq 5), the peer's death (hq 5)
    alt21 pq_copystall_shrink_b hq hf
    c pq_copystall1_shrink_b hq 5
    c hd_shrink_b hq 5 ;;
  H5)  # 2 at four ranks: rank 3 killed, per-peer flush (hq 10, hf 5, 2:1), context-wide flush (hq 5)
    alt21 mr4_kill3_peer hq hf
    c mr4_kill3 hq 5 ;;
  H6)  # 3b at four ranks (hq 10, hf 5, 2:1)
    alt21 pq4_fwslow hq hf ;;
  H7)  # 4 at four ranks with a child devComm (hq 10), then the four-rank regression (hq 5 each)
    c pq4_kill3_shrink hq 10
    c mr4_none hq 5
    c mr4_f1_01 hq 5 ;;
  H8)  # 4 at four ranks with a cause on rank 0 (hq 5, hf 5, 1:1), the port-fix cell at four ranks (hq 3)
    for k in 1 2 3 4 5; do c pq4_local_shrink hq 1 $k; c pq4_local_shrink hf 1 $k; done
    c pq4_rdv hq 3 ;;
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
cudafail=$( { find "$R" -name '*_meta.txt' -newer "$R/snap_before-$HT.txt" -exec grep -lE ' r[0-9]rc=139( |$)' {} + 2>/dev/null
  find "$R" \( -name '*_r[0-9].log' -o -name '*_r[0-9].kv' \) -newer "$R/snap_before-$HT.txt" \
    -exec grep -liE 'illegal address|illegal memory access|unspecified launch failure' {} + 2>/dev/null; } | sort -u)
if [ -n "$cudafail" ]; then
  echo "$(date '+%F %T') hold $H: CUDA memory fault or exit 139 in: $(echo "$cudafail" | tr '\n' ' ')" | tee -a "$R/STOP_cuda"
fi
