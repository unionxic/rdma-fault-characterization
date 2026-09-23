#!/usr/bin/env bash
# run_matrix.sh - run a batch of matrix cells and append one CSV row per trial.
# Invoke from inside cluster_run.sh (holds the lock). Keep each batch bounded.
#
#   run_matrix.sh <outdir> <cell> [cell ...]
#     cell = FAULT:WAIT:TRIALS   e.g. none:timeout:5  F3:blocking:3
# Per-cell tuning comes from the environment (passed straight to run_trial.sh):
#   NVSHMEM_IB_TIMEOUT, DEV_TIMEOUT_MS, FAULT_MS, BURST, ITERS, MSG, CADENCE_MS.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
OUTDIR="$1"; shift
mkdir -p "$OUTDIR"
CSV="$OUTDIR/matrix.csv"
HDR="stack,backend,fault,wait_mode,trial,iters_ok_before,init_outcome,target_outcome,data_check,silent_success,host_error,host_error_ms,fp_where,status,vendor_err,teardown,notes,cqe_opcode,cqe_syndrome,cqe_vendor_err,cqe_wqe_counter"
[ -f "$CSV" ] || echo "$HDR" > "$CSV"

for cell in "$@"; do
  fault="${cell%%:*}"; rest="${cell#*:}"; wait="${rest%%:*}"; trials="${rest##*:}"
  for t in $(seq 1 "$trials"); do
    echo "$(date '+%T') [matrix] $fault $wait trial $t/$trials (IB_TIMEOUT=${NVSHMEM_IB_TIMEOUT:-14} DEV_TIMEOUT_MS=${DEV_TIMEOUT_MS:-} BURST=${BURST:-1})" >&2
    row=$(bash "$HERE/run_trial.sh" "$fault" "$wait" "$t" "$OUTDIR")
    echo "$row" | tee -a "$CSV"
  done
done
echo "$(date '+%T') [matrix] batch done -> $CSV" >&2
