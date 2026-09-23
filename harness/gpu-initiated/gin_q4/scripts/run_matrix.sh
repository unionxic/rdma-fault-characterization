#!/usr/bin/env bash
# run_matrix.sh - one batch of GIN GDAKI Q4 trials. Does NOT take the cluster lock:
# the caller wraps each batch in ../../common/cluster_run.sh (bounded, < 30 min),
# so the lock is released between batches.
#
# usage: run_matrix.sh <out_csv> <batch> [trials]
# batches:
#   smoke           ring/c0, ring/c1, collapsed/c1 baseline (timeout), 1 trial each
#   A-timeout       Task A: {ring,collapsed} x {none,F1,F2,F3} x timeout, CLASSIFY=1, QPWATCH 100 ms
#   A-late          Task A: collapsed x {F1,F2,F3} x timeout, CLASSIFY=1, slot re-read 500 us later
#   A-blocking      Task A: collapsed x {F1,F2,F3} x blocking, CLASSIFY=1, QPWATCH 100 ms, re-read 500 us
#   A-stock         Task A: collapsed x {F1,F2,F3} x {timeout,blocking}, CLASSIFY=0 (stock device code)
#   A-host          Task A: collapsed_host baseline (refused: no GDRCopy) + one forced attempt
#   B-on-timeout    Task B: ring x {none,F1,F2,F3,F4} x timeout, CLASSIFY=1
#   B-on-blocking   Task B: ring x {none,F1,F2,F3,F4} x blocking, CLASSIFY=1
#   B-off-timeout   Task B reference, same build: ring x {F1..F4} x timeout, CLASSIFY=0
#   B-off-blocking  Task B reference, same build: ring x {F1..F4} x blocking, CLASSIFY=0
#   lat-poll        overhead: classify=1 with NCCL_GIN_FAULT_CLASSIFY_POLL_US=1000, 2 reps per cell
#   lat             overhead: reps LAT_REP_FROM..LAT_REP_TO (default 1..2) x {off,on} x {timeout,blocking} x {4 KiB, 256 KiB}
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
RUN=$HERE/run_trial.sh
OUT=${1:?out_csv}; BATCH=${2:?batch}; NT=${3:-3}

one() {  # cq classify fault wait trial [extra env...]
  local cq=$1 c=$2 f=$3 w=$4 t=$5; shift 5
  local it=120 gap=15 wd
  if [ "$w" = blocking ]; then wd=80; else wd=55; fi
  [ "$f" = F4 ] && { it=400; gap=10; }
  echo ">>> [$cq c$c $f $w #$t] $(date +%T)" >&2
  env "$@" CQ_TYPE=$cq CLASSIFY=$c WATCHDOG_S=$wd GAP_MS=$gap INJECT_MS=${INJECT_MS:-600} KILL_DELAY_MS=2500 \
    DEV_TIMEOUT_S=${DEV_TIMEOUT_S:-5} bash "$RUN" "$f" "$w" "$t" "$OUT" "$it" 14
}

case "$BATCH" in
  smoke)
    one ring 0 none timeout 1; one ring 1 none timeout 1; one collapsed 1 none timeout 1 ;;
  A-timeout)
    for cq in ring collapsed; do for f in none F1 F2 F3; do for t in $(seq 1 "$NT"); do
      one $cq 1 $f timeout $t QPWATCH_MS=100; done; done; done ;;
  A-late)
    for f in F1 F2 F3; do for t in $(seq 1 "$NT"); do one collapsed 1 $f timeout "L$t" QPWATCH_MS=100 LATE_US=500; done; done ;;
  A-blocking)
    for f in F1 F2 F3; do for t in $(seq 1 "$NT"); do one collapsed 1 $f blocking $t QPWATCH_MS=100 LATE_US=500; done; done ;;
  A-stock)
    for w in timeout blocking; do for f in F1 F2 F3; do for t in $(seq 1 "$NT"); do one collapsed 0 $f $w $t; done; done; done ;;
  A-host)
    one collapsed_host 1 none timeout 1; one collapsed_host_force 1 none timeout 1 ;;
  B-on-timeout)
    for f in none F1 F2 F3 F4; do for t in $(seq 1 "$NT"); do one ring 1 $f timeout $t; done; done ;;
  B-on-blocking)
    for f in none F1 F2 F3 F4; do for t in $(seq 1 "$NT"); do one ring 1 $f blocking $t; done; done ;;
  B-off-timeout)
    for f in F1 F2 F3 F4; do for t in $(seq 1 "$NT"); do one ring 0 $f timeout $t; done; done ;;
  B-off-blocking)
    for f in F1 F2 F3 F4; do for t in $(seq 1 "$NT"); do one ring 0 $f blocking $t; done; done ;;
  lat)
    for bytes in 4096 262144; do for w in timeout blocking; do for rep in $(seq "${LAT_REP_FROM:-1}" "${LAT_REP_TO:-2}"); do for c in 0 1; do
      echo ">>> [lat bytes=$bytes $w rep$rep c$c] $(date +%T)" >&2
      CQ_TYPE=ring CLASSIFY=$c WATCHDOG_S=120 BYTES=$bytes DEV_TIMEOUT_S=5 LAT_ITERS=2000 LAT_REPS=5 \
        bash "$RUN" lat "$w" "b${bytes}r${rep}" "$OUT" 1 14
    done; done; done; done ;;
  lat-poll)
    # classify=1 with a slow mailbox watcher (1 ms) vs 20 us: separates the host thread's
    # effect (CPU-proxy doorbell thread contention) from the device-side change
    for bytes in 4096 262144; do for w in timeout blocking; do for rep in 1 2; do
      echo ">>> [lat-poll bytes=$bytes $w rep$rep] $(date +%T)" >&2
      CQ_TYPE=ring CLASSIFY=1 POLL_US=1000 WATCHDOG_S=120 BYTES=$bytes DEV_TIMEOUT_S=5 LAT_ITERS=2000 LAT_REPS=5 \
        bash "$RUN" lat "$w" "b${bytes}p1000r${rep}" "$OUT" 1 14
    done; done; done ;;
  *) echo "unknown batch $BATCH" >&2; exit 1 ;;
esac
echo ">>> batch '$BATCH' complete $(date +%T)" >&2
