#!/usr/bin/env bash
# hold_feas.sh - one hold of gin-restore's feasibility tests (EXPERIMENT.md 9.15; DRAFT stage, never scored). The main
# session runs it inside ../../../common/cluster_run.sh (tag rs-<hold>, -w 10800) under timeout -s KILL 880.
# usage: hold_feas.sh <resultsdir> <hold>
#   S3     B3 smoke: one cross-node cell, rain responder, relaxed MR, 208 iterations (setup check; not used in any verdict)
#   S3s    the same with sunny as the responder (sunny listens on the control port; run before B3s)
#   B3one-<cell>  one B3 cell again, into b3_rerun<k>/ (a cell that skipped.txt lists, or an inconclusive one; the earlier
#          run stays)
#   B3r    B3, rain is the responder: b3_x_rain_<ro|so>, b3_s_rain_<ro|so>, b3_h_rain_<ro|so>
#   B3s    B3, sunny is the responder: the same six cells with sunny
#          B3r, B3s and B3one run B3_ITERS (3 200) iterations with RS_LAST_KB=4096, both passed explicitly (EXPERIMENT.md
#          9.15.3 and 12: the 1 024 smoke had no boundary hit; 3 200 keeps rain's QUERY_QP under the 20 000 cap); the
#          contention cells (b3_h_*) also get RS_QUERY_BUDGET=19000: they end at an iteration boundary after 19 000 QUERY_QP
#          (the first rain h rerun hit the 20 000 cap) and are scored over the iterations done
#   B2     B2: four ranks interleaved (rain 0, 2; sunny 1, 3), report lines only, 2 trials, into b2/ (a repeat: b2_run<k>/)
#   B2c    B2 control (optional): four ranks consecutive (rain 0, 1; sunny 2, 3), 1 trial, into the latest B2 folder
#   B1     B1: record (2 ranks), replay rank 1 on sunny and rank 0 on rain (strace), two negative replays; 2 trials, into
#          b1/ (a repeat: b1_run<k>/)
#   B1live B1 optional (only after B1 passed): 2 ranks hold 30 s while a spare replays rank 1 on sunny; 1 trial, into the
#          latest B1 folder (its self-connect bound comes from that folder's sequential replays)
# Before and after the hold (as ../../remaining/hold.sh): GPU users and compute mode of both nodes, the mlx5 kernel lines of
# both nodes, rain's mlx5_1 firmware-command counters (debugfs, read-only, ../../scripts/ts1/fwcmd_snapshot.sh). A new mlx5
# command-error line or a growth of the firmware-command failure counters writes <resultsdir>/STOP_mlx5; a CUDA memory fault
# writes STOP_cuda; a test process left after its trial writes STOP_left. Inside B3r/B3s every cell is followed by a check:
# a NIC, rmsn, QUERY_QP-cap, setup or watchdog error in the responder's kv writes STOP_nic, a growth of rain's
# firmware-command failure counters writes STOP_mlx5, and the remaining cells are skipped. A cell or trial whose bound would
# end past 840 s of the hold is skipped (skipped.txt). No further hold should run while a STOP file exists (this script
# refuses). Processes are never killed here: every process is bounded by its own timeout; the leftover check is a
# read-only count by exact name. Before the hold, when no test process is left, this user's own leftover files of an
# earlier hold that was cut (/tmp/rs_sp_*, /tmp/rs_b3_*, and their work directories) are deleted on both nodes: they may
# hold management addresses. The same is done when the hold refuses because of a STOP file and no test process is left;
# when it refuses because a test process is still there, clean by hand once that process has ended (its own timeout).
# No iptables rule.
# env: SUNNY_SSH (required)
set -u
R=${1:?resultsdir}; H=${2:?hold}
D=$(cd "$(dirname "$0")" && pwd)
SUNNY_SSH=${SUNNY_SSH:?set SUNNY_SSH}
export SUNNY_SSH
CMDERR='grep -i mlx5 | grep -iE "cmd|command" | grep -icE "failed|timeout|leak"'
NAMES="rs_spike rs_drain_test"
mkdir -p "$R"
left() { { for n in $NAMES; do pgrep -x "$n"; done; ssh -n "$SUNNY_SSH" "for n in $NAMES; do pgrep -x \$n; done"; } 2>/dev/null | wc -l; }
OWNCLEAN='find /tmp -maxdepth 1 -user "$(id -un)" \( -name "rs_sp_*" -o -name "rs_sp.*" -o -name "rs_b3_*" -o -name "rs_b3.*" \) -exec rm -rf {} + 2>/dev/null; true'
for f in STOP_mlx5 STOP_cuda STOP_left STOP_nic; do
  if [ -e "$R/$f" ]; then
    echo "$R/$f present: no hold runs" >&2
    [ "$(left)" -eq 0 ] && { bash -c "$OWNCLEAN"; ssh -n "$SUNNY_SSH" "$OWNCLEAN"; }
    exit 3
  fi
done
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
  bash "$D/../../scripts/ts1/fwcmd_snapshot.sh" "$1" > "$R/fwcmd_$1.txt" 2>&1
  echo "rain fwcmd failed sum: $(awk '{for(i=1;i<=NF;i++) if($i ~ /^failed=|^failed_mbox_status=/){split($i,a,"="); s+=a[2]}} END{print s+0}' "$R/fwcmd_$1.txt")"
  echo "rain fwcmd QUERY_QP n: $(awk '$1=="QUERY_QP"{for(i=1;i<=NF;i++) if($i ~ /^n=/){split($i,a,"="); print a[2]}}' "$R/fwcmd_$1.txt")"
}
n0=$(left)
[ "$n0" -eq 0 ] || { echo "$(date '+%F %T') hold $H: $n0 test process(es) present before the hold" | tee -a "$R/STOP_left"; exit 3; }
bash -c "$OWNCLEAN"; ssh -n "$SUNNY_SSH" "$OWNCLEAN"
SECONDS=0
B3_ITERS=3200; B3_LAST_KB=4096
B3_H_BUDGET=19000  # contention cells (b3_h_*): RS_QUERY_BUDGET (EXPERIMENT.md 9.15.3 and 12: the first h rerun hit the 20 000 cap)
newdir() {  # newdir <base>: $R/<base> if it holds no trial yet, else the first free $R/<base>_run<k> (k >= 2)
  if ! ls "$R/$1"/*_meta.txt >/dev/null 2>&1; then echo "$R/$1"; return; fi
  local k=2; while [ -e "$R/$1_run$k" ]; do k=$((k + 1)); done; echo "$R/$1_run$k"
}
lastdir() {  # lastdir <base>: the latest existing folder of <base> ($R/<base> if none)
  local d="$R/$1" k=2; while [ -e "$R/$1_run$k" ]; do d="$R/$1_run$k"; k=$((k + 1)); done; echo "$d"
}
fits() {  # fits <bound_s> <what>: false (and a line in skipped.txt) if the bound would end past 840 s of the hold
  if [ $((SECONDS + $1)) -gt 840 ]; then echo "$(date '+%F %T') hold $H: skipped $2 (elapsed ${SECONDS} s + bound $1 s > 840 s)" | tee -a "$R/skipped.txt"; return 1; fi
  return 0
}
fwfail() { bash "$D/../../scripts/ts1/fwcmd_snapshot.sh" "$1" 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i ~ /^failed=|^failed_mbox_status=/){split($i,a,"="); s+=a[2]}} END{print s+0}'; }
snap "before-$H" | tee "$R/snap_before-$H.txt"
FW0=$(fwfail "start-$H")
b3() {  # b3 <cell> <iters> <logdir> [main]: one cell if it fits, then the per-cell stop checks; main: RS_LAST_KB=4096
  local cell=$1 iters=$2 dir=$3 kvf
  [ -e "$R/STOP_nic" ] || [ -e "$R/STOP_mlx5" ] && { echo "skipped $cell: STOP file" >> "$R/skipped.txt"; return 0; }
  fits $((iters / 100 + 60 + 30 + 15 + 30)) "$cell" || return 0
  if [ "${4:-}" = main ]; then
    case "$cell" in
      b3_h_*) RS_LAST_KB=$B3_LAST_KB RS_QUERY_BUDGET=$B3_H_BUDGET bash "$D/run_b3.sh" "$cell" "$iters" "$dir" ;;
      *) RS_LAST_KB=$B3_LAST_KB bash "$D/run_b3.sh" "$cell" "$iters" "$dir" ;;
    esac
  else
    bash "$D/run_b3.sh" "$cell" "$iters" "$dir"
  fi
  kvf="$dir/${cell}_resp.kv"
  if [ ! -f "$kvf" ] || grep -qE 'nic_error=|setup_error=|watchdog=1|cuda_error=' "$kvf"; then
    echo "$(date '+%F %T') hold $H: $cell ended with an error ($(grep -ho 'nic_error="[^"]*"\|setup_error="[^"]*"\|watchdog=1\|cuda_error=[^ ]*' "$kvf" 2>/dev/null | head -1)); no further cell" | tee -a "$R/STOP_nic"
  fi
  local fw; fw=$(fwfail "after-$cell")
  [ "$fw" -gt "$FW0" ] && echo "$(date '+%F %T') hold $H: firmware-command failures grew after $cell ($FW0 -> $fw)" | tee -a "$R/STOP_mlx5"
  return 0
}
sp() {  # sp <cell> <trial> <logdir>: one trial if it fits
  local bound=120; [ "$1" = b1 ] && bound=380; [ "$1" = b1_live ] && bound=200
  fits "$bound" "$1 trial $2" || return 0
  bash "$D/run_spike.sh" "$@"
}
case "$H" in
  S3) b3 b3_x_rain_ro 208 "$R/b3_smoke" ;;
  S3s) b3 b3_x_sunny_ro 208 "$R/b3_smoke" ;;
  B3one-*)  # one B3 cell again (a skipped or inconclusive one) into its own folder b3_rerun<k>; summ_feas reads the latest
    k=1; while [ -e "$R/b3_rerun$k/${H#B3one-}_meta.txt" ]; do k=$((k + 1)); done
    b3 "${H#B3one-}" "$B3_ITERS" "$R/b3_rerun$k" main ;;
  B3r) for c in x s h; do for o in ro so; do b3 "b3_${c}_rain_$o" "$B3_ITERS" "$R/b3" main; done; done ;;
  B3s) for c in x s h; do for o in ro so; do b3 "b3_${c}_sunny_$o" "$B3_ITERS" "$R/b3" main; done; done ;;
  B2) d=$(newdir b2); for t in 1 2; do sp b2_inter "$t" "$d"; done ;;
  B2c) sp b2_consec 1 "$(lastdir b2)" ;;
  B1) d=$(newdir b1); for t in 1 2; do sp b1 "$t" "$d"; done ;;
  B1live) d=$(lastdir b1); t=1; while [ -e "$d/b1_live_t${t}_meta.txt" ]; do t=$((t + 1)); done; sp b1_live "$t" "$d" ;;
  *) echo "unknown hold $H" >&2; exit 2 ;;
esac
snap "after-$H" | tee "$R/snap_after-$H.txt"
for node in rain sunny; do
  diff <(sort "$R/mlx5_before-${H}_$node.txt") <(sort "$R/mlx5_after-${H}_$node.txt") | grep '^>' | sed "s/^> /$node: /"
done > "$R/mlx5_new_$H.txt"
echo "new mlx5 kernel lines in hold $H: $(wc -l < "$R/mlx5_new_$H.txt")"; cat "$R/mlx5_new_$H.txt"
b=$(grep -h "cmd_err lines\|fwcmd failed sum" "$R/snap_before-$H.txt" | awk -F': ' '{s+=$2} END{print s+0}')
a=$(grep -h "cmd_err lines\|fwcmd failed sum" "$R/snap_after-$H.txt" | awk -F': ' '{s+=$2} END{print s+0}')
[ "$a" -gt "$b" ] && echo "$(date '+%F %T') hold $H: mlx5 command errors or firmware-command failures grew ($b -> $a)" | tee -a "$R/STOP_mlx5"
cudafail=$(find "$R" \( -name '*.kv' -o -name '*.log' \) -newer "$R/snap_before-$H.txt" \
  -exec grep -liE 'illegal address|illegal memory access|unspecified launch failure|cuda_error=' {} + 2>/dev/null | sort -u)
[ -n "$cudafail" ] && echo "$(date '+%F %T') hold $H: CUDA fault in: $(echo "$cudafail" | tr '\n' ' ')" | tee -a "$R/STOP_cuda"
n1=$(left)
[ "$n1" -eq 0 ] || echo "$(date '+%F %T') hold $H: $n1 test process(es) left after the hold" | tee -a "$R/STOP_left"
[ "$n1" -eq 0 ] && { bash -c "$OWNCLEAN"; ssh -n "$SUNNY_SSH" "$OWNCLEAN"; }
echo "hold $H elapsed ${SECONDS} s"
exit 0
