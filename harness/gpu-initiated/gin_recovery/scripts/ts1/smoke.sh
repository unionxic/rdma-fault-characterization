#!/usr/bin/env bash
# First end-to-end smoke of S1 (inside cluster_run): fault-free, F1, F3 once each.
set -u
L=${1:?logdir}
cd "$(dirname "$0")"
bash run_trial.sh none blocking s1 "$L" 40
bash run_trial.sh F1 blocking s1 "$L" 120
bash run_trial.sh F3 blocking s1 "$L" 120
