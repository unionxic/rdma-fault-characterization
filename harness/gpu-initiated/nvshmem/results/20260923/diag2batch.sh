set -u
R=/home/unionxic/rdma-error/harness/gpu-initiated/nvshmem/results/20260923; RT=/home/unionxic/rdma-error/harness/gpu-initiated/nvshmem/run_trial.sh
# F3 with CQ in GPU memory (default) — confirm periodic slot never shows op 0xd
WATCH_MS=400 DEV_TIMEOUT_MS=9000 FAULT_MS=1200 PROC_TIMEOUT=60 NVSHMEM_FAULT_WATCHDOG_S=40   bash $RT F3 timeout 95 $R/diag2 >/dev/null
# F3 with CQ/WQ in HOST memory — does the error CQE appear there?
NVSHMEM_IBGDA_FORCE_NIC_BUF_MEMTYPE=hostmem WATCH_MS=400 DEV_TIMEOUT_MS=9000 FAULT_MS=1200   PROC_TIMEOUT=60 NVSHMEM_FAULT_WATCHDOG_S=40 bash $RT F3 timeout 96 $R/diag2 >/dev/null
# F1 with CQ/WQ in HOST memory — local err, does an error/flush CQE appear?
NVSHMEM_IBGDA_FORCE_NIC_BUF_MEMTYPE=hostmem WATCH_MS=400 DEV_TIMEOUT_MS=9000 FAULT_MS=1200   PROC_TIMEOUT=60 NVSHMEM_FAULT_WATCHDOG_S=40 bash $RT F1 timeout 96 $R/diag2 >/dev/null
echo "diag2 done"
