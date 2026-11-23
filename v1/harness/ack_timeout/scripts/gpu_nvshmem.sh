#!/usr/bin/env bash
# gpu_nvshmem.sh - NVSHMEM IBGDA with the FT patch (bundle ~/gi-bundle/nvshmem_ft, unchanged),
# GPU NIC handler, fault F3 (sunny's RC QP -> ERR 800 ms after connect, rain's put ends in
# RETRY_EXC), timeout-mode wait (bounded quiet), NVSHMEM_IBGDA_FT=1, no recovery (classify and
# decline), NVSHMEM_IB_TIMEOUT=<T>, NVSHMEM_IB_RETRY_CNT=7 (the env_ft.sh default).
# Uses the nvshmem_ft runner (../../gpu-initiated/nvshmem_ft/scripts/run_trial.sh) as is.
# Run inside cluster_run.sh (and ackfloor_window.sh for floor-off).
#   gpu_nvshmem.sh <outdir> <label> <T> <N> [first_trial] [RECOVER=0|1]
set -u
OUT=$1; LABEL=$2; T=$3; N=$4; FIRST=${5:-1}; REC=${6:-0}
HERE=$(cd "$(dirname "$0")" && pwd)
NV=$HERE/../../gpu-initiated/nvshmem_ft/scripts
D=$OUT/nvshmem_${LABEL}_T${T}${REC:+_rec$REC}
mkdir -p "$D"
for t in $(seq "$FIRST" $((FIRST + N - 1))); do
  echo ">>> nvshmem $LABEL T=$T rec=$REC trial $t $(date +%T) floor=$(sudo -n mlxreg -d 17:00.1 --reg_name ROCE_ACCL --get 2>/dev/null | awk -F'|' '/^min_ack_timeout_limit_disabled /{gsub(/ /,"",$2); print $2}')" >&2
  env NVSHMEM_IB_TIMEOUT="$T" NVSHMEM_IB_RETRY_CNT=7 FT=1 RECOVER="$REC" PROC_TIMEOUT=60 \
      bash "$NV/run_trial.sh" F3 timeout "$t" "$D" | tee -a "$D/matrix.out"
done
