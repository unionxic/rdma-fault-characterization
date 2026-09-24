#!/usr/bin/env bash
# batch_d.sh - capture study on the nvshmem_quiet path, forced d = 0 recoveries, CPU-proxy decline
HERE="$(cd "$(dirname "$0")" && pwd)"
R=${RESDIR:-$HERE/../results/b2}
STOP_AFTER_S=800 bash $HERE/run_matrix.sh $HERE/specs/capture_blocking.txt $R/capture_blocking
STOP_AFTER_S=300 bash $HERE/run_matrix.sh $HERE/specs/d0.txt $R/d0
STOP_AFTER_S=300 bash $HERE/run_matrix.sh $HERE/specs/config.txt $R/config
