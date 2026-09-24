#!/usr/bin/env bash
# batch_c.sh - root-cause capture study, flag-off (stock) behaviour, no-fault overhead
HERE="$(cd "$(dirname "$0")" && pwd)"
R=${RESDIR:-$HERE/../results/b2}
STOP_AFTER_S=800 bash $HERE/run_matrix.sh $HERE/specs/capture.txt $R/capture
STOP_AFTER_S=400 bash $HERE/run_matrix.sh $HERE/specs/flagoff.txt $R/flagoff
# latency: 6 interleaved passes over the 6 cells
T=$(mktemp)
for k in 1 2 3 4 5 6; do sed -e '/^#/d' -e "s/\$/ TFIRST=$k/" $HERE/specs/lat.txt >> $T; done
STOP_AFTER_S=500 bash $HERE/run_matrix.sh $T $R/lat
rm -f $T
