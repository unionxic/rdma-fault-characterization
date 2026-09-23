set -u
R=/home/unionxic/rdma-error/harness/gpu-initiated/nvshmem/results/20260923; RT=/home/unionxic/rdma-error/harness/gpu-initiated/nvshmem/run_trial.sh
# control: no fault, watch QP/CQ over time (QP stays RTS, CQ producer advances)
WATCH_MS=500 DEV_TIMEOUT_MS=3000 FAULT_MS=1200 PROC_TIMEOUT=60 NVSHMEM_FAULT_WATCHDOG_S=40 bash $RT none timeout 90 $R/diag >/dev/null
# F1 local QP->ERR: does QP go to ERR? does CQ producer advance? final slot?
WATCH_MS=500 DEV_TIMEOUT_MS=10000 FAULT_MS=1200 PROC_TIMEOUT=60 NVSHMEM_FAULT_WATCHDOG_S=40 bash $RT F1 timeout 90 $R/diag >/dev/null
# F3 peer QP->ERR: rain QP state / CQ counters over the retry window
WATCH_MS=500 DEV_TIMEOUT_MS=10000 FAULT_MS=1200 PROC_TIMEOUT=60 NVSHMEM_FAULT_WATCHDOG_S=40 bash $RT F3 timeout 90 $R/diag >/dev/null
# F2b invalid rkey at iter 4: prompt NAK? is an error CQE visible to the GPU?
WATCH_MS=500 DEV_TIMEOUT_MS=4000 CORRUPT_AT=4 PROC_TIMEOUT=60 NVSHMEM_FAULT_WATCHDOG_S=40 bash $RT F2b timeout 90 $R/diag >/dev/null
echo "diagbatch done"
