#!/usr/bin/env bash
# cells_mi.sh - gin-mirror, test branch: run one cell of ../../EXPERIMENT.md 7 a given number of times, inside a hold of
# hold_mi.sh (itself inside ../../../../common/cluster_run.sh through chain_mi.sh). gin-restore's cells_rs.sh (copied and
# then changed): kind rs -> run_mi.sh (the 4-rank workload gin_mi), kind reg -> ../../../remaining/run_mr_hr.sh
# (gin-remaining's 4-rank runner, unchanged: gin-restore's regression cells, here against the mirror layer). The cost cells
# run through hold_mi.sh's interleave (run_cost_mi.sh), not here.
#
# Regression cells: run_mr_hr.sh takes its library as $HOME/gi-bundle/gin_ts2/$LIB and its driver as
# $HOME/gi-bundle/gin_ts2/mr/$MRKEY/gin_mr; this study's files live in the set ~/rs-bundle/<RS_SET>/ (nothing is written
# into ~/gi-bundle), so LIB=../../rs-bundle/<RS_SET>/lib/<mi|mip> and MRKEY=../../../rs-bundle/<RS_SET>/mr/<ff|hold>. After
# its trial a second line with rs_set, lib_md5 and driver_md5 is appended to its meta file (as cells_rs.sh does). The
# mirror's variables reach it through EXTRA_ENV (MIRROR, cells_mi.json; default 0: gin-restore's regression).
# A trial whose <stem>_meta.txt exists is skipped ("already done"). run_mi.sh's exit 5 (host memory short, section 8)
# writes <results>/STOP_mem and ends the cell.
#
# usage: cells_mi.sh <logdir> <cell> <build> <kind> <n> <start> [k=v ...]   (each k=v is one argument: spaces are kept)
set -u
L=${1:?logdir}; CELL=${2:?cell}; B=${3:?build}; KIND=${4:?kind}; NRUN=${5:?n}; START=${6:?start}
shift 6
D=$(cd "$(dirname "$0")" && pwd)
RES=$(dirname "$L")
for kv in "$@"; do export "${kv%%=*}"="${kv#*=}"; done
RS_SET=${RS_SET:-}
. "$D/rs_set_mi.sh"
rs_set_check || exit 1
export RS_SET
SETP=rs-bundle/$RS_SET   # the deployment set, relative to $HOME
run_rs() { CELL=$CELL LIB=$B bash "$D/run_mi.sh" "$@"; }
run_reg() {
  local t=$1 ldir=$2 extra mrkey m
  extra="NCCL_GIN_RESTORE=${RESTORE:-1} NCCL_GIN_RESTORE_MIRROR=${MIRROR:-0} NCCL_NUM_RMA_CTX=0 NCCL_RMA_DISABLE=1 NCCL_SYM_GIN_KERNELS_ENABLE=0 NCCL_RAS_ENABLE=0 NCCL_GIN_Q4_QPWATCH_MS=0 ${MR_EXTRA:-}"
  [ "${FAULT_POLICY:-}" = hold ] && extra="NCCL_GIN_FAULT_POLICY=hold $extra"
  case "${DRIVER:-}" in mr/ff) mrkey=ff ;; mr/hold) mrkey=hold ;; *) echo "cell $CELL names no regression driver" >&2; return 1 ;; esac
  env CELL="$CELL" LIB="../../$SETP/lib/$B" MRKEY="../../../$SETP/mr/$mrkey" N=4 ABORT_WD_S=20 \
    ${MR_KILL_RANK:+KILL_RANK=$MR_KILL_RANK} ${MR_KILL_RANK:+KILL_DELAY_MS=${MR_KILL_DELAY_MS:-9000}} \
    ${MR_FLUSH:+FLUSH=$MR_FLUSH} EXTRA_ENV="$extra" \
    bash "$D/../../../remaining/run_mr_hr.sh" "$t" "$ldir"
  m="$ldir/${CELL}_${t}_meta.txt"
  if [ -f "$m" ]; then
    echo "rs_set=$RS_SET mirror=${MIRROR:-0} lib_md5=$(md5sum < "$HOME/$SETP/lib/$B/libnccl.so.2" 2>/dev/null | cut -c1-32) driver_md5=$(md5sum < "$HOME/$SETP/mr/$mrkey/gin_mr" 2>/dev/null | cut -c1-32)" >> "$m"
  fi
}
stem_of() { case "$KIND" in rs) echo "${CELL}_${B}_$1" ;; *) echo "${CELL}_$1" ;; esac; }
streak() {  # after trial $1: two trials in a row that left a process behind write $RES/STOP_left (EXPERIMENT.md 8)
  local left; left=$(sed -n 's/.* left=\([0-9]*\) .*/\1/p' "$L/$(stem_of "$1")_meta.txt" 2>/dev/null)
  if [ -n "$left" ] && [ "$left" -gt 0 ]; then
    echo $(( $(cat "$RES/LEFT_STREAK" 2>/dev/null || echo 0) + 1 )) > "$RES/LEFT_STREAK"
  else echo 0 > "$RES/LEFT_STREAK"; fi
  [ "$(cat "$RES/LEFT_STREAK")" -ge 2 ] && echo "$(date '+%F %T') $(stem_of "$1"): a process left behind in two trials in a row" | tee -a "$RES/STOP_left"
  return 0
}
for ((k = START; k < START + NRUN; k++)); do
  if ls "$RES"/STOP_* > /dev/null 2>&1; then echo "skipped ${CELL}_n$k: STOP file" >&2; break; fi
  t=n$k
  if [ -f "$L/$(stem_of "$t")_meta.txt" ]; then echo "${CELL}_n$k ($B): already done" >&2; continue; fi
  case "$KIND" in
    rs)  run_rs "$t" "$L"; rc=$?
         if [ "$rc" = 5 ]; then echo "$(date '+%F %T') ${CELL}_n$k: host memory short at the trial's start (section 8)" | tee -a "$RES/STOP_mem"; break; fi ;;
    reg) run_reg "$t" "$L" ;;
    *) echo "unknown kind $KIND for cell $CELL (cost cells run through hold_mi.sh)" >&2; exit 1 ;;
  esac
  streak "$t"
done
