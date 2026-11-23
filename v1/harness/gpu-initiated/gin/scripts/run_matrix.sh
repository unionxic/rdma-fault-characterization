#!/usr/bin/env bash
# run_matrix.sh - run a batch of GIN fault trials. This does NOT take the cluster
# lock itself; the caller wraps each batch in one cluster_run.sh so the lock is
# held per BATCH (bounded, < 30 min) and released between batches.
#
# Matrix: backend {proxy,gdaki} x fault {none,F1,F2,F3,F4} x wait {timeout,blocking},
# 3 trials/cell (5 for baseline), NCCL_IB_TIMEOUT=14.
#
# usage: run_matrix.sh <proxy|gdaki> <out_csv> <baseline|faults|faults-timeout|faults-blocking>
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
RUN=$HERE/run_trial.sh
BACKEND=${1:?backend}; OUT=${2:?out_csv}; BATCH=${3:?batch}

one() {  # fault wait trial
  local f=$1 w=$2 t=$3 wd it=120 gap=15 kd=3000
  # watchdog covers setup + fault + device timeout/block cap + 15 s post-fault
  # poll + a possibly hanging abort (15 s)
  if [ "$w" = blocking ]; then wd=75; else wd=50; fi
  # F4: lockstep barrier + post-kill drain; kill 2.5 s after launch, enough iters
  if [ "$f" = F4 ]; then it=400; gap=10; kd=2500; fi
  echo ">>> [$BACKEND $f $w #$t]" >&2
  WATCHDOG_S=$wd INJECT_MS=${INJECT_MS:-600} KILL_DELAY_MS=$kd GAP_MS=$gap DEV_TIMEOUT_S=${DEV_TIMEOUT_S:-5} \
    bash "$RUN" "$BACKEND" "$f" "$w" "$t" "$OUT" "$it" 14
}

case "$BATCH" in
  baseline)        for w in timeout blocking; do for t in 1 2 3 4 5; do one none "$w" "$t"; done; done ;;
  faults)          for f in F1 F2 F3 F4; do for w in timeout blocking; do for t in 1 2 3; do one "$f" "$w" "$t"; done; done; done ;;
  faults-timeout)  for f in F1 F2 F3 F4; do for t in 1 2 3; do one "$f" timeout "$t"; done; done ;;
  faults-blocking) for f in F1 F2 F3 F4; do for t in 1 2 3; do one "$f" blocking "$t"; done; done ;;
  *) echo "unknown batch $BATCH" >&2; exit 1 ;;
esac
echo ">>> batch '$BATCH' for $BACKEND complete" >&2
