#!/usr/bin/env bash
# batch_b.sh - multi-fault recovery, root-cause capture study, flag-off (stock) behaviour
HERE="$(cd "$(dirname "$0")" && pwd)"
R=${RESDIR:-$HERE/../results/b2}
STOP_AFTER_S=700 bash $HERE/run_matrix.sh $HERE/specs/multi.txt $R/multi
STOP_AFTER_S=700 bash $HERE/run_matrix.sh $HERE/specs/capture.txt $R/capture
STOP_AFTER_S=400 bash $HERE/run_matrix.sh $HERE/specs/flagoff.txt $R/flagoff
