#!/usr/bin/env bash
# batch_a.sh - classification matrix + recovery matrix (one cluster hold)
HERE="$(cd "$(dirname "$0")" && pwd)"
R=${RESDIR:-$HERE/../results/b2}
STOP_AFTER_S=1500 bash $HERE/run_matrix.sh $HERE/specs/classify.txt $R/classify
STOP_AFTER_S=1500 bash $HERE/run_matrix.sh $HERE/specs/recover.txt $R/recover
