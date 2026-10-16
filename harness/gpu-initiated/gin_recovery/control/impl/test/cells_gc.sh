#!/usr/bin/env bash
# cells_gc.sh - gin-control, test side: run one cell of ../../EXPERIMENT.md 7 a given number of times, inside a hold of
# hold_gc.sh (itself inside ../../../../common/cluster_run.sh through chain_gc.sh). gin-mirror's cells_mi.sh (copied and
# then changed): kind rs -> run_gc.sh (the 4-rank workload gin_mi against a gc build), kind reg -> ../../../remaining/
# run_mr_hr.sh (gin-remaining's 4-rank runner, unchanged: gin-mirror's regression cells R1, here against gct or gc).
#
# Regression cells: run_mr_hr.sh takes its library as $HOME/gi-bundle/gin_ts2/$LIB and its driver as
# $HOME/gi-bundle/gin_ts2/mr/$MRKEY/gin_mr; this study's files live in the set ~/rs-bundle/<RS_SET>/ (nothing is written into
# ~/gi-bundle), so LIB=../../rs-bundle/<RS_SET>/lib/<build> and MRKEY=../../../rs-bundle/<RS_SET>/mr/<ff|hold>. After its
# trial a second line with rs_set, lib_md5 and driver_md5 is appended to its meta file (as cells_mi.sh does).
# A trial whose <stem>_meta.txt exists is skipped ("already done"). run_gc.sh's exit 5 (host memory short) writes
# <results>/STOP_mem; its exit 6 (the launchers not ready at the trial's start: section 8's start check; the trial's meta
# says launcher_ready=0 and score_gc.py excludes it) and its exit 7 (a launcher's registration table not empty at the trial's
# start: the coordinator's check of 2026-10-17; meta launcher_table) write <results>/STOP_launcher. Each ends the cell.
#
# usage: cells_gc.sh <logdir> <cell> <build> <kind> <n> <start> [k=v ...]   (each k=v is one argument: spaces are kept)
set -u
L=${1:?logdir}; CELL=${2:?cell}; B=${3:?build}; KIND=${4:?kind}; NRUN=${5:?n}; START=${6:?start}
shift 6
D=$(cd "$(dirname "$0")" && pwd)
RES=$(dirname "$L")
for kv in "$@"; do export "${kv%%=*}"="${kv#*=}"; done
RS_SET=${RS_SET:-}
# shellcheck source=../../../mirror/impl/test/rs_set_mi.sh
. "$D/../../../mirror/impl/test/rs_set_mi.sh"
rs_set_check || exit 1
export RS_SET
case "$B" in gc|gct|gctc|gcp|gctp) ;; *) echo "build $B is not a gin-control build" >&2; exit 1 ;; esac
SETP=rs-bundle/$RS_SET
run_rs() { CELL=$CELL LIB=$B bash "$D/run_gc.sh" "$@"; }
run_reg() {
  local t=$1 ldir=$2 extra mrkey m
  extra="NCCL_GIN_RESTORE=${RESTORE:-1} NCCL_GIN_RESTORE_MIRROR=${MIRROR:-0} NCCL_NUM_RMA_CTX=0 NCCL_RMA_DISABLE=1 NCCL_SYM_GIN_KERNELS_ENABLE=0 NCCL_RAS_ENABLE=0 NCCL_GIN_Q4_QPWATCH_MS=0 ${MR_EXTRA:-}"
  [ "${FAULT_POLICY:-}" = hold ] && extra="NCCL_GIN_FAULT_POLICY=hold $extra"
  case "${DRIVER:-}" in mr/ff) mrkey=ff ;; mr/hold) mrkey=hold ;; *) echo "cell $CELL names no regression driver" >&2; return 1 ;; esac
  # TODO(phase3): a regression trial of gin-remaining's runner at @gc starts no launcher (that runner is unchanged); the
  # restore is off in those cells (gin-mirror R1), so no launcher pairing is asked (Resume condition 41 needs a restore)
  env CELL="$CELL" LIB="../../$SETP/lib/$B" MRKEY="../../../$SETP/mr/$mrkey" N=4 ABORT_WD_S=20 \
    ${MR_KILL_RANK:+KILL_RANK=$MR_KILL_RANK} ${MR_KILL_RANK:+KILL_DELAY_MS=${MR_KILL_DELAY_MS:-9000}} \
    ${MR_FLUSH:+FLUSH=$MR_FLUSH} EXTRA_ENV="$extra" \
    bash "$D/../../../remaining/run_mr_hr.sh" "$t" "$ldir"
  m="$ldir/${CELL}_${t}_meta.txt"
  if [ -f "$m" ]; then
    echo "rs_set=$RS_SET mirror=${MIRROR:-0} lib_md5=$(md5sum < "$HOME/$SETP/lib/$B/libnccl.so.2" 2>/dev/null | cut -c1-32) driver_md5=$(md5sum < "$HOME/$SETP/mr/$mrkey/gin_mr" 2>/dev/null | cut -c1-32) hold=${HOLD_TAG:-}" >> "$m"
  fi
}
stem_of() { case "$KIND" in rs) echo "${CELL}_${B}_$1" ;; *) echo "${CELL}_$1" ;; esac; }
streak() {  # after trial $1: two trials in a row that left a process behind write $RES/STOP_left (gin-mirror section 8)
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
         if [ "$rc" = 5 ]; then echo "$(date '+%F %T') ${CELL}_n$k: host memory short at the trial's start (section 8)" | tee -a "$RES/STOP_mem"; break; fi
         if [ "$rc" = 6 ]; then echo "$(date '+%F %T') ${CELL}_n$k: the launchers were not ready on both nodes at the trial's start (section 8)" | tee -a "$RES/STOP_launcher"; break; fi
         if [ "$rc" = 7 ]; then echo "$(date '+%F %T') ${CELL}_n$k: a launcher's registration table was not empty at the trial's start" | tee -a "$RES/STOP_launcher"; break; fi ;;
    reg) run_reg "$t" "$L" ;;
    *) echo "unknown kind $KIND for cell $CELL (cost cells run through hold_gc.sh)" >&2; exit 1 ;;
  esac
  streak "$t"
done
