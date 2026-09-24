#!/usr/bin/env bash
# gpu_gin.sh - NCCL GIN GDAKI + Q4 device classifier (bundle ~/gi-bundle/gin_q4, unchanged),
# fault F3 (sunny's QP -> ERR at 600 ms, so rain's puts end in RETRY_EXC), timeout-mode wait,
# ring CQ, NCCL_GIN_FAULT_CLASSIFY=1, NCCL_IB_TIMEOUT=<T> (retry_cnt: NCCL default 7).
# Uses the gin_q4 runner (../../gpu-initiated/gin_q4/scripts/run_trial.sh) as is; only the
# output location and the IB timeout differ. Run inside cluster_run.sh (and ackfloor_window.sh
# for floor-off).
#   gpu_gin.sh <outdir> <label> <T> <N> [first_trial]
set -u
OUT=$1; LABEL=$2; T=$3; N=$4; FIRST=${5:-1}
HERE=$(cd "$(dirname "$0")" && pwd)
Q4=$HERE/../../gpu-initiated/gin_q4/scripts
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad/agent_ack
mkdir -p "$OUT" "$SCR/q4work"
CSV=$OUT/gin_${LABEL}_T${T}.csv
for t in $(seq "$FIRST" $((FIRST + N - 1))); do
  echo ">>> gin $LABEL T=$T trial $t $(date +%T) floor=$(sudo -n mlxreg -d 17:00.1 --reg_name ROCE_ACCL --get 2>/dev/null | awk -F'|' '/^min_ack_timeout_limit_disabled /{gsub(/ /,"",$2); print $2}')" >&2
  env Q4_WORKDIR="$SCR/q4work" CQ_TYPE=ring CLASSIFY=1 WATCHDOG_S=55 GAP_MS=15 INJECT_MS=600 \
      DEV_TIMEOUT_S=5 bash "$Q4/run_trial.sh" F3 timeout "${LABEL}T${T}_$t" "$CSV" 120 "$T"
done
