#!/usr/bin/env bash
set -u
RT="/home/unionxic/rdma-error/harness/gpu-initiated/nvshmem/run_trial.sh"; O="/home/unionxic/rdma-error/harness/gpu-initiated/nvshmem/results/20260923/qptl"
# F3: query-only watch, start at 800ms (past init), 300ms period, to catch rain's
# RC QP state transition relative to the ~4s retransmission stop.
WATCH_MS=300 WATCH_QPONLY=1 WATCH_DELAY_MS=800 DEV_TIMEOUT_MS=10000 FAULT_MS=1500   PROC_TIMEOUT=60 NVSHMEM_FAULT_WATCHDOG_S=40 bash "$RT" F3 timeout 1 "$O" >/dev/null
echo "qptl done"
