#!/usr/bin/env bash
# Regenerate ../../gin_transparent_s1.diff: the FULL diff of the S1 source tree against pristine NCCL
# v2.32.3-1 (12df1a11), i.e. the four earlier layers plus S1, in one patch. The scratch tree is a git
# repo with commit 1 = pristine v2.32.3-1 (git archive) and commit 2 = the four earlier diffs applied;
# the working tree = + S1. S1 alone is `git diff HEAD` there (printed as a stat below).
set -euo pipefail
SRC=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad/agent_ts1/nccl-src
OUT=$(cd "$(dirname "$0")/../.." && pwd)/gin_transparent_s1.diff
BASE=$(git -C "$SRC" rev-list --max-parents=0 HEAD)
{
cat <<'HDR'
# GIN GDAKI transparent recovery, step S1 (research build): an unmodified put+signal+flush application
# survives a local QP ERR or a peer QP ERR (RETRY_EXC) with no error returned to its kernel or host and
# no relaunch. Env-gated: nothing changes unless NCCL_GIN_FAULT_TRANSPARENT=1 (default 0).
#
# base tag: v2.32.3-1  commit: 12df1a11afad322be5a204a2db890161cbf8131d
# This is a FULL diff against the pristine base. It contains, unchanged, the same four layers that
# gin_recovery_gpudb.diff sits on, plus S1:
#   1. ../gin/gin_fault_inject.diff        fault-injection hook (NCCL_GIN_FAULT_INJECT)
#   2. ../gin_q4/gin_q4_classify.diff      device error-CQE classifier + host mailbox (NCCL_GIN_FAULT_CLASSIFY)
#   3. gin_recovery.diff                   Prepare/Commit recovery API (NCCL_GIN_FAULT_RECOVERY)
#   4. gin_recovery_gpudb.diff             GPU-rung doorbells in Prepare/Commit
#   5. S1 (this layer)                     device pause gate + hold-and-rebase waits + in-library helper
# Apply to a pristine tree:  git apply gin_transparent_s1.diff   (equivalently: 1-4 in order, then S1 alone)
#
# env (S1): NCCL_GIN_FAULT_TRANSPARENT=1 (needs NCCL_GIN_FAULT_CLASSIFY=1 NCCL_GIN_FAULT_RECOVERY=1, on every
#   rank); NCCL_GIN_TS_HANDSHAKE_MS (3000), NCCL_GIN_TS_HOLD_MS (10000), NCCL_GIN_TS_QUIESCE_MS (5000),
#   NCCL_GIN_TS_CONNECT_MS (15000); NCCL_GIN_TS_DIAG=norebase|noring (negative controls only).
#
# S1 files:
#   include/nccl_device/gin/gdaki/gin_gdaki_device_host_common.h  struct ncclGinTsGate (64 B, in the reserved2
#       padding of the DOCA device QP) and ncclGinTsGate2 (8 B, reserved1); Q4 record ts_epoch (reserved bytes)
#   include/nccl_device/gin/gdaki/gin_gdaki.h  pause gate around every post (put/signal/p/get/mcst), counted
#       poll region for waiters, logical tickets (lbase + physical), tsPoll (park across a recovery, re-map the
#       ticket), commit-point give-up (tsGiveUp), request carries the logical count
#   transport/net_ib/gdaki/gin_host_gdaki.cc  helper thread per GDAKI context: library TCP socket per peer
#       (set up at context creation over the GIN collComm), policy, quiesce, existing Prepare/Commit,
#       executed-count exchange (responder rmsn), re-post + host doorbell, epoch publish, decline; Q4 watcher
#       hands faults to the helper; queryLastError reports only declined faults; helper QP state changes are
#       serialized with the fault hook (opMu); periodic gate scan (lost records / give-ups -> decline)
#   transport/net_ib/gdaki/doca-gpunetio/{include/host/doca_verbs.h,src/doca_verbs_qp.{cpp,hpp}}
#       doca_verbs_qp_query_seq: QPC rmsn / next_rcv_psn / next_send_psn / state via DEVX QUERY_QP
# Design, tests and results: TRANSPARENT_S1.md
#
HDR
cd "$SRC" && git diff "$BASE" -- src
} > "$OUT"
echo "wrote $OUT"
git -C "$SRC" diff --stat HEAD -- src | tail -1
