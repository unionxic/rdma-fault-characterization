#!/usr/bin/env bash
# run_gpudb.sh <logdir> <part> - the GPU-doorbell matrix (PeerMappingOverride=1 permanent since
# 2026-09-24 13:53). Uses BUNDLE (default ~/gi-bundle/gin_recovery_gpudb = gin_recovery.diff +
# gin_recovery_gpudb.diff). Every trial logs the doorbell mode (NCCL WARN "GIN/GDAKI: doorbell
# mode=..."), DOCA's own warnings (DOCA_GPUNETIO_LOG=4) and the GIN proxy-thread probe.
# Run inside ../../common/cluster_run.sh.
#   parts: main (none, F1, F3, F1x5, F3x5, F2, F4, D0), neg (negative controls), proxy (same
#   build with the CPU proxy forced: NCCL_GIN_GDAKI_NIC_HANDLER=1), lat (overhead), v1 (the
#   committed gin_recovery.diff build under GPU doorbells)
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
RUN=$HERE/run_trial.sh
L=${1:?logdir}; PART=${2:?part}
export BUNDLE=${BUNDLE:-/home/unionxic/gi-bundle/gin_recovery_gpudb}
export DOCA_LOG=4
one() {  # fault wait trial iters [env...]
  local f=$1 w=$2 t=$3 it=$4; shift 4
  echo ">>> [$PART $f $w #$t] $(date +%T)" >&2
  env "$@" bash "$RUN" "$f" "$w" "$t" "$L" "$it" 14
}
case "$PART" in
  main)
    for w in timeout blocking; do
      for t in 1 2; do one none $w t$t 120 REC=1 WATCHDOG_S=60; done
      for t in 1 2 3; do one F1 $w t$t 120 REC=1 INJECT=600 WATCHDOG_S=60; done
      for t in 1 2 3; do one F3 $w t$t 120 REC=1 INJECT=600 WATCHDOG_S=60; done
      for t in 1 2; do one F2 $w t$t 120 REC=1 WATCHDOG_S=60; done
      for t in 1 2; do one F4 $w t$t 400 REC=1 GAP_MS=10 KILL_DELAY_MS=2500 WATCHDOG_S=60; done
      one D0 $w t1 120 REC=1 WATCHDOG_S=60
    done
    for t in 1 2 3; do one F1 blocking m$t 160 REC=1 INJECT=300,150,-1,200,100 WATCHDOG_S=70; done
    for t in 1 2 3; do one F3 blocking m$t 200 REC=1 INJECT=600,300,-1,300,300 WATCHDOG_S=100 GIN_POST_POLL_S=5; done ;;
  neg)
    for t in 1 2; do
      one F1 timeout n${t}_keepgpupi 120 REC=1 INJECT=300,150 WATCHDOG_S=70 EXTRA_ENV=NCCL_GIN_RECOVERY_DIAG=keep_gpu_pi
      one F1 timeout n${t}_keepgpudbr 120 REC=1 INJECT=300,150 WATCHDOG_S=70 EXTRA_ENV=NCCL_GIN_RECOVERY_DIAG=keep_gpu_dbr
    done ;;
  proxy)
    X=NCCL_GIN_GDAKI_NIC_HANDLER=1
    for t in 1 2; do one F1 timeout p$t 120 REC=1 INJECT=600 WATCHDOG_S=60 EXTRA_ENV=$X; done
    one F3 blocking p1 120 REC=1 INJECT=600 WATCHDOG_S=60 EXTRA_ENV=$X
    one F1 blocking pm1 160 REC=1 INJECT=300,150,-1,200,100 WATCHDOG_S=70 EXTRA_ENV=$X ;;
  lat)
    for bytes in 4096 262144; do for w in timeout blocking; do for rep in 1 2; do for r in 0 1; do
      one lat $w "b${bytes}r${rep}" 1 REC=$r WATCHDOG_S=120 BYTES=$bytes LAT_ITERS=2000 LAT_REPS=5
    done; done; done; done
    for rep in 1 2; do one lat timeout "b262144px${rep}" 1 REC=1 WATCHDOG_S=120 BYTES=262144 LAT_ITERS=2000 LAT_REPS=5 \
      EXTRA_ENV=NCCL_GIN_GDAKI_NIC_HANDLER=1; done ;;
  v1)
    export BUNDLE=/home/unionxic/gi-bundle/gin_recovery
    one F1 timeout v1a 120 REC=1 INJECT=600 WATCHDOG_S=60
    one F3 blocking v1a 120 REC=1 INJECT=600 WATCHDOG_S=60 ;;
  *) echo "unknown part $PART" >&2; exit 1 ;;
esac
echo ">>> part '$PART' complete $(date +%T)" >&2
