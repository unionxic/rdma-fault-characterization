#!/usr/bin/env bash
# One trial of every cell (two for single F1) on the final build, both wait modes.
# Run inside ../../common/cluster_run.sh.
set -u
cd "$(dirname "$0")/.."
L=${1:-results/20260924/confirm/logs}
for w in timeout blocking; do
  REC=1 WATCHDOG_S=60 bash scripts/run_trial.sh none $w c1 $L 120 14
  for t in c1 c2; do REC=1 INJECT=600 WATCHDOG_S=60 bash scripts/run_trial.sh F1 $w $t $L 120 14; done
  REC=1 INJECT=600 WATCHDOG_S=60 bash scripts/run_trial.sh F3 $w c1 $L 120 14
  REC=1 INJECT=300,150,-1,200,100 WATCHDOG_S=70 bash scripts/run_trial.sh F1 $w cm1 $L 160 14
  REC=1 INJECT=600,300,-1,300,300 WATCHDOG_S=100 GIN_POST_POLL_S=5 bash scripts/run_trial.sh F3 $w cm1 $L 200 14
  REC=1 WATCHDOG_S=60 bash scripts/run_trial.sh D0 $w c1 $L 120 14
  REC=1 WATCHDOG_S=60 bash scripts/run_trial.sh F2 $w c1 $L 120 14
  REC=1 GAP_MS=10 KILL_DELAY_MS=2500 WATCHDOG_S=60 bash scripts/run_trial.sh F4 $w c1 $L 400 14
done
echo ">>> confirm batch complete $(date +%T)" >&2
