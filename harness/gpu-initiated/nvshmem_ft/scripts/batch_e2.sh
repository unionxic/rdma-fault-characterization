#!/usr/bin/env bash
# batch_e2.sh - final build: several faults per run, capture study (nvshmem_quiet path), flag-off
HERE="$(cd "$(dirname "$0")" && pwd)"
R=${RESDIR:-$HERE/../results/b2}
STOP_AFTER_S=600 bash $HERE/run_matrix.sh $HERE/specs/multi.txt $R/multi
STOP_AFTER_S=600 bash $HERE/run_matrix.sh $HERE/specs/capture_blocking.txt $R/capture_blocking
STOP_AFTER_S=300 bash $HERE/run_matrix.sh $HERE/specs/flagoff.txt $R/flagoff
