#!/usr/bin/env bash
# batch_e1.sh - final build: classification, recovery, forced d=0, unsupported config, overhead
HERE="$(cd "$(dirname "$0")" && pwd)"
R=${RESDIR:-$HERE/../results/b2}
STOP_AFTER_S=400 bash $HERE/run_matrix.sh $HERE/specs/classify.txt $R/classify
STOP_AFTER_S=400 bash $HERE/run_matrix.sh $HERE/specs/recover.txt $R/recover
STOP_AFTER_S=150 bash $HERE/run_matrix.sh $HERE/specs/d0.txt $R/d0
STOP_AFTER_S=150 bash $HERE/run_matrix.sh $HERE/specs/config.txt $R/config
T=$(mktemp)
for k in 1 2 3 4 5 6; do sed -e '/^#/d' -e "s/\$/ TFIRST=$k/" $HERE/specs/lat.txt >> $T; done
STOP_AFTER_S=400 bash $HERE/run_matrix.sh $T $R/lat
rm -f $T
