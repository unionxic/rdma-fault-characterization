#!/usr/bin/env bash
# run_matrix.sh - one batch of GIN GDAKI recovery trials. Does NOT take the cluster lock: the caller
# wraps each batch in ../../common/cluster_run.sh (bounded, < 30 min), so the lock is released
# between batches.
#
# usage: run_matrix.sh <logdir> <batch> [trials] [first_trial]
# batches (all NCCL_IB_TIMEOUT=14, 256 KiB put + signal per iteration, 15 ms gap):
#   base       no fault, recovery on, {timeout,blocking}
#   f1         F1 (rank 0 local QP -> ERR at 600 ms), {timeout,blocking}
#   f3         F3 (rank 1 QPs -> ERR at 600 ms, peer alive), {timeout,blocking}
#   f1multi    F1 x 5 shots "300,150,-1,200,100" (shot 3 fires inside the commit of shot 2 -> hits its replay)
#   f3multi    F3 x 5 shots "600,300,-1,300,300" (shot 3 inside rank 1's commit of shot 2)
#   f2         F2 (put at a 64 MiB offset -> REM_ACCESS), {timeout,blocking}
#   f4         F4 (SIGKILL rank 1 at 2.5 s), {timeout,blocking}
#   d0         no fault; forced recovery after iterations 30,60,90 (the ADD had landed -> d = 0, no replay)
#   flagoff    F1 and F3 with NCCL_GIN_FAULT_RECOVERY=0 (Q4 behaviour), {timeout,blocking}
#   lat        overhead: classify=1, recovery {0,1} x {timeout,blocking} x {4 KiB, 256 KiB}, reps
#              LAT_REP_FROM..LAT_REP_TO (default 1..2)
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
RUN=$HERE/run_trial.sh
L=${1:?logdir}; BATCH=${2:?batch}; NT=${3:-3}; T0=${4:-1}
TL=$(seq "$T0" $((T0 + NT - 1)))

one() {  # fault wait trial iters [env...]
  local f=$1 w=$2 t=$3 it=$4; shift 4
  echo ">>> [$BATCH $f $w #$t] $(date +%T)" >&2
  env "$@" bash "$RUN" "$f" "$w" "$t" "$L" "$it" 14
}

case "$BATCH" in
  base)
    for w in timeout blocking; do for t in $TL; do one none $w t$t 120 REC=1 WATCHDOG_S=60; done; done ;;
  f1)
    for w in timeout blocking; do for t in $TL; do one F1 $w t$t 120 REC=1 INJECT=600 WATCHDOG_S=60; done; done ;;
  f3)
    for w in timeout blocking; do for t in $TL; do one F3 $w t$t 120 REC=1 INJECT=600 WATCHDOG_S=60; done; done ;;
  f1multi)
    for w in timeout blocking; do for t in $TL; do one F1 $w m$t 160 REC=1 INJECT=300,150,-1,200,100 WATCHDOG_S=70; done; done ;;
  f3multi)
    for w in timeout blocking; do for t in $TL; do one F3 $w m$t 200 REC=1 INJECT=600,300,-1,300,300 WATCHDOG_S=100 GIN_POST_POLL_S=5; done; done ;;
  f2)
    for w in timeout blocking; do for t in $TL; do one F2 $w t$t 120 REC=1 WATCHDOG_S=60; done; done ;;
  f4)
    for w in timeout blocking; do for t in $TL; do one F4 $w t$t 400 REC=1 GAP_MS=10 KILL_DELAY_MS=2500 WATCHDOG_S=60; done; done ;;
  d0)
    for w in timeout blocking; do for t in $TL; do one D0 $w t$t 120 REC=1 WATCHDOG_S=60; done; done ;;
  flagoff)
    for w in timeout blocking; do for f in F1 F3; do for t in $TL; do one $f $w o$t 120 REC=0 INJECT=600 WATCHDOG_S=70; done; done; done ;;
  lat)
    for bytes in 4096 262144; do for w in timeout blocking; do for rep in $(seq "${LAT_REP_FROM:-1}" "${LAT_REP_TO:-2}"); do for r in 0 1; do
      one lat $w "b${bytes}r${rep}" 1 REC=$r WATCHDOG_S=120 BYTES=$bytes LAT_ITERS=2000 LAT_REPS=5
    done; done; done; done ;;
  *) echo "unknown batch $BATCH" >&2; exit 1 ;;
esac
echo ">>> batch '$BATCH' complete $(date +%T)" >&2
