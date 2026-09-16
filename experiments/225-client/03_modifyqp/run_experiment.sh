#!/usr/bin/env bash
#
# run_experiment.sh - modify_qp(ERR) retry decomposition
#
# Sweeps retry_cnt 0..7 with qp_timeout=8.
# Server must be running on 224 BEFORE starting this script.
#
# Usage:
#   ./run_experiment.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

SERVER_IP="${SERVER_IP:-10.0.0.3}"
RETRY_VALUES="${RETRY_VALUES:-0 1 2 3 4 5 6 7}"
TIMEOUT="${TIMEOUT:-8}"
ITERS="${ITERS:-30}"
CLIENT="${SCRIPT_DIR}/client"

# Optional: pin the busy-polling client to a dedicated core to reduce
# scheduler jitter in the sub-millisecond t1/t2 timing. Unset -> no pinning
# (default behaviour unchanged). Example: CPU_PIN=2 ./run_experiment.sh
CPU_PIN="${CPU_PIN:-}"
PIN=""
if [ -n "$CPU_PIN" ]; then
    if command -v taskset >/dev/null 2>&1; then
        PIN="taskset -c $CPU_PIN"
    else
        echo "[WARN] taskset not found; CPU_PIN ignored" >&2
    fi
fi

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
CSV="${SCRIPT_DIR}/results/modifyqp_${TIMESTAMP}.csv"
LOG_FILE="${SCRIPT_DIR}/results/log_${TIMESTAMP}.txt"

mkdir -p "${SCRIPT_DIR}/results"

log() { echo "[$(date '+%H:%M:%S')] $*" >&2; }

if [ ! -x "$CLIENT" ]; then
    log "ERROR: Build first: make -C $SCRIPT_DIR"
    exit 1
fi

n_retry=$(echo $RETRY_VALUES | wc -w | tr -d ' ')

log "=== modify_qp(ERR) Retry Decomposition ==="
log "Configs: R={$RETRY_VALUES} × T=$TIMEOUT × N=$ITERS"
log "Output: $CSV"
log ""

config_idx=0
for R in $RETRY_VALUES; do
    config_idx=$((config_idx + 1))
    log "[$config_idx/$n_retry] R=$R T=$TIMEOUT × N=$ITERS"

    $PIN "$CLIENT" -s "$SERVER_IP" \
        -R "$R" -O "$TIMEOUT" -n "$ITERS" \
        -o "$CSV" 2>&1 | tee -a "$LOG_FILE" >&2

    log "  → R=$R done"

    if [ "$config_idx" -lt "$n_retry" ]; then
        sleep 1
    fi
done

log "============================================="
log "Results: $CSV"
log "Log:     $LOG_FILE"
log "============================================="
