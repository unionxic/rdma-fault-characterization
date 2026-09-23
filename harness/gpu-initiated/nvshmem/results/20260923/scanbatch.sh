#!/usr/bin/env bash
set -u
RT="/home/unionxic/rdma-error/harness/gpu-initiated/nvshmem/run_trial.sh"; O="/home/unionxic/rdma-error/harness/gpu-initiated/nvshmem/results/20260923/scan"
DEV_TIMEOUT_MS=10000 FAULT_MS=1200 PROC_TIMEOUT=60 NVSHMEM_FAULT_WATCHDOG_S=40 bash "$RT" none timeout 1 "$O" >/dev/null
DEV_TIMEOUT_MS=10000 FAULT_MS=1200 PROC_TIMEOUT=60 NVSHMEM_FAULT_WATCHDOG_S=40 bash "$RT" F1 timeout 1 "$O" >/dev/null
DEV_TIMEOUT_MS=10000 CORRUPT_AT=4 PROC_TIMEOUT=60 NVSHMEM_FAULT_WATCHDOG_S=40 bash "$RT" F2b timeout 1 "$O" >/dev/null
DEV_TIMEOUT_MS=10000 FAULT_MS=1200 PROC_TIMEOUT=60 NVSHMEM_FAULT_WATCHDOG_S=40 bash "$RT" F3 timeout 1 "$O" >/dev/null
echo "scanbatch done"
