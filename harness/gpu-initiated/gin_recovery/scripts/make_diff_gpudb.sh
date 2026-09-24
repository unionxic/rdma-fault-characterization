#!/usr/bin/env bash
# Regenerate gin_recovery_gpudb.diff from the scratch v2 worktree (HEAD = v2.32.3-1 + the Q2 hook +
# the Q4 classifier + gin_recovery.diff; working changes = GPU-doorbell support).
set -euo pipefail
SRC=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad/gi/gin_recovery/nccl-src-gpudb
OUT=$(cd "$(dirname "$0")/.." && pwd)/gin_recovery_gpudb.diff
{
cat <<'HDR'
# GIN GDAKI recovery v2: GPU-rung doorbells (DOCA nic_handler GPU_SM_DB, e.g. PeerMappingOverride=1)
# and a doorbell-mode log line. Env-gated as before: nothing changes unless NCCL_GIN_FAULT_RECOVERY=1
# (the log line is an INFO line with recovery and classification off, a WARN otherwise).
#
# base tag: v2.32.3-1  commit: 12df1a11afad322be5a204a2db890161cbf8131d
# LAYERED on top of ../gin/gin_fault_inject.diff, ../gin_q4/gin_q4_classify.diff and gin_recovery.diff;
# apply all four from the NCCL source root, in this order:
#   git apply ../gin/gin_fault_inject.diff && git apply ../gin_q4/gin_q4_classify.diff && \
#   git apply gin_recovery.diff && git apply gin_recovery_gpudb.diff
#
# What changes (transport/net_ib/gdaki/gin_host_gdaki.cc only):
#   gdakiDbModeLog      once per GDAKI context: "GIN/GDAKI: doorbell mode=GPU|CPU_PROXY|MIXED ... first_nic_handler=
#                       ... needsProxyProgress=" (stock NCCL/DOCA never log the doorbell path)
#   gdakiRecDbMode      per QP: CPU proxy (cpu_proxy, nic_handler CPU_PROXY, valid DBR) or GPU (no proxy,
#                       nic_handler GPU_SM_DB, valid DBR); anything else (BlueFlame, no-DBR, SW-emulated DBR,
#                       free-flow proxy) is declined. v1 declined every non-proxy QP.
#   Prepare, GPU mode   quiescence = sq_ready_index == sq_rsvd_index == sq_wqe_pi (the GPU's submitted
#                       producer index) and the GPU-memory doorbell record == sq_rsvd_index & 0xffff; no
#                       proxy mailbox/counter exists (v1 dereferenced them).
#   Commit, GPU mode    zero the doorbell record in GPU memory (cudaMemsetAsync on the recovery stream)
#                       instead of the host-memory record + proxy mailbox + proxy counter; sq_wqe_pi is
#                       reset with the device QP struct (as in v1).
#   NCCL_GIN_RECOVERY_DIAG=keep_gpu_pi|keep_gpu_dbr   negative controls for the two GPU-mode resync steps.
#
HDR
cd "$SRC" && git diff HEAD -- src
} > "$OUT"
echo "wrote $OUT ($(grep -c '^+' "$OUT") + / $(grep -c '^-' "$OUT") - lines incl. headers)"
