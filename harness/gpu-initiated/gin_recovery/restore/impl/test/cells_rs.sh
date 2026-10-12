#!/usr/bin/env bash
# cells_rs.sh - gin-restore work package 10: run one cell of EXPERIMENT.md 7 a given number of times, inside a hold of
# hold_rs.sh (itself inside ../../../../common/cluster_run.sh through chain_rs.sh). It maps a cell to its runner, as
# ../../../remaining/cells.sh does. Two runners here: run_rs.sh (the 4-rank restore workload, kind rs) and
# ../../../remaining/run_mr_hr.sh (gin-remaining's 4-rank runner, unchanged: the regression cells, kind reg). The cost cells
# run through hold_rs.sh's interleave (run_cost.sh), not here. The runners kill only PIDs they recorded and pick a checked
# rendezvous port (portpick.sh).
#
# Regression cells: run_mr_hr.sh takes its library as $HOME/gi-bundle/gin_ts2/$LIB and its driver as
# $HOME/gi-bundle/gin_ts2/mr/$MRKEY/gin_mr and is not changed here; this study's files live under ~/rs-bundle (9.15.1: nothing
# is written into ~/gi-bundle), so LIB and MRKEY are relative paths that resolve there:
#   LIB=../../rs-bundle/lib/<rs|rsp>           -> $HOME/rs-bundle/lib/<rs|rsp>
#   MRKEY=../../../rs-bundle/mr/<ff|hold>      -> $HOME/rs-bundle/mr/<ff|hold>/gin_mr (gin_mr.cu built against this layer's
#                                                 headers: the cell's DRIVER, mr/ff without the macro, mr/hold with it)
# CELL is the unique cells_rs.json name (run_mr_hr.sh uses it as the label of its files: no two cells share a stem); the mr
# behaviour comes from MR_KILL_RANK, MR_FLUSH, MR_EXTRA of the cell, as gin-remaining's cells.sh passes them.
#
# usage: cells_rs.sh <logdir> <cell> <build> <kind> <n> <start> [k=v ...]   (each k=v is one argument: spaces are kept)
set -u
L=${1:?logdir}; CELL=${2:?cell}; B=${3:?build}; KIND=${4:?kind}; NRUN=${5:?n}; START=${6:?start}
shift 6
D=$(cd "$(dirname "$0")" && pwd)
RES=$(dirname "$L")
for kv in "$@"; do export "${kv%%=*}"="${kv#*=}"; done
run_rs() { CELL=$CELL LIB=$B bash "$D/run_rs.sh" "$@"; }
run_reg() {
  local t=$1 ldir=$2 extra mrkey
  extra="NCCL_GIN_RESTORE=${RESTORE:-1} NCCL_NUM_RMA_CTX=0 NCCL_RMA_DISABLE=1 NCCL_SYM_GIN_KERNELS_ENABLE=0 NCCL_RAS_ENABLE=0 NCCL_GIN_Q4_QPWATCH_MS=0 ${MR_EXTRA:-}"
  [ "${FAULT_POLICY:-}" = hold ] && extra="NCCL_GIN_FAULT_POLICY=hold $extra"
  # the driver build the cell names: mr/ff (gin_mr.cu, this layer's headers, no macro) or mr/hold (the same with the macro)
  case "${DRIVER:-}" in mr/ff) mrkey=ff ;; mr/hold) mrkey=hold ;; *) echo "cell $CELL names no regression driver" >&2; return 1 ;; esac
  env CELL="$CELL" LIB="../../rs-bundle/lib/$B" MRKEY="../../../rs-bundle/mr/$mrkey" N=4 ABORT_WD_S=20 \
    ${MR_KILL_RANK:+KILL_RANK=$MR_KILL_RANK} ${MR_KILL_RANK:+KILL_DELAY_MS=${MR_KILL_DELAY_MS:-9000}} \
    ${MR_FLUSH:+FLUSH=$MR_FLUSH} EXTRA_ENV="$extra" \
    bash "$D/../../../remaining/run_mr_hr.sh" "$t" "$ldir"
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
  if [ -e "$RES/STOP_left" ] || [ -e "$RES/STOP_mlx5" ] || [ -e "$RES/STOP_cuda" ] || [ -e "$RES/STOP_nic" ]; then
    echo "skipped ${CELL}_n$k: STOP file" >&2; break
  fi
  t=n$k
  case "$KIND" in
    rs)  run_rs "$t" "$L" ;;
    reg) run_reg "$t" "$L" ;;
    *) echo "unknown kind $KIND for cell $CELL (cost cells run through hold_rs.sh)" >&2; exit 1 ;;
  esac
  streak "$t"
done
