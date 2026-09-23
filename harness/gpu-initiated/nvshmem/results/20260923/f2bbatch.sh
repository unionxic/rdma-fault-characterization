#!/usr/bin/env bash
set -u
R="/home/unionxic/rdma-error/harness/gpu-initiated/nvshmem/results/20260923"; RT="/home/unionxic/rdma-error/harness/gpu-initiated/nvshmem/run_trial.sh"
echo "stack,backend,fault,wait_mode,trial,iters_ok_before,init_outcome,target_outcome,data_check,silent_success,host_error,host_error_ms,fp_where,status,vendor_err,teardown,notes,cqe_opcode,cqe_syndrome,cqe_vendor_err,cqe_wqe_counter" > "$R/matrix_f2b.csv"
for t in 1 2 3; do
  DEV_TIMEOUT_MS=4000 CORRUPT_AT=4 PROC_TIMEOUT=60 NVSHMEM_FAULT_WATCHDOG_S=40     bash "$RT" F2b timeout $t "$R/f2b" | tee -a "$R/matrix_f2b.csv"
done
echo "f2b done"
