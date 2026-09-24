#!/usr/bin/env bash
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
OUT=${1:-$HERE/../results/smoke}
RECOVER=1 bash $HERE/run_trial.sh F4 blocking 1 $OUT
RECOVER=1 bash $HERE/run_trial.sh F4 timeout 1 $OUT
bash $HERE/run_trial.sh F4 timeout 2 $OUT
