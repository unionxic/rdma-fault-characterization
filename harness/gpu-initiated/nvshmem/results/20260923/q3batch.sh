set -u
R=/home/unionxic/rdma-error/harness/gpu-initiated/nvshmem/results/20260923; RT=/home/unionxic/rdma-error/harness/gpu-initiated/nvshmem/run_trial.sh
echo "stack,backend,fault,wait_mode,trial,iters_ok_before,init_outcome,target_outcome,data_check,silent_success,host_error,host_error_ms,fp_where,status,vendor_err,teardown,notes,cqe_opcode,cqe_syndrome,cqe_vendor_err,cqe_wqe_counter" > $R/matrix_ref.csv
# F3 reference at DEFAULT IB timeout 20, device poll up to 40s
NVSHMEM_IB_TIMEOUT=20 DEV_TIMEOUT_MS=40000 FAULT_MS=1200 NVSHMEM_FAULT_WATCHDOG_S=90 PROC_TIMEOUT=110 bash $RT F3 timeout 1 $R/ref | tee -a $R/matrix_ref.csv
# F3 long-window probe at IB timeout 14, device poll up to 15s
DEV_TIMEOUT_MS=15000 FAULT_MS=1200 NVSHMEM_FAULT_WATCHDOG_S=40 PROC_TIMEOUT=60 bash $RT F3 timeout 2 $R/ref | tee -a $R/matrix_ref.csv
# Q3 snapshots (lead asks): F3 burst 1 and 16, F1 burst 16
DEV_TIMEOUT_MS=15000 FAULT_MS=1200 NVSHMEM_FAULT_WATCHDOG_S=40 PROC_TIMEOUT=60 BURST=1  bash $RT F3 snapshot 1 $R/snap >/dev/null
DEV_TIMEOUT_MS=15000 FAULT_MS=1200 NVSHMEM_FAULT_WATCHDOG_S=40 PROC_TIMEOUT=60 BURST=16 bash $RT F3 snapshot 2 $R/snap >/dev/null
DEV_TIMEOUT_MS=3000  FAULT_MS=800  NVSHMEM_FAULT_WATCHDOG_S=30 PROC_TIMEOUT=45 BURST=16 bash $RT F1 snapshot 3 $R/snap >/dev/null
echo "q3batch done"
