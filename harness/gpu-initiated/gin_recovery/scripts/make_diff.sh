#!/usr/bin/env bash
# Regenerate gin_recovery.diff from the scratch recovery tree (whose HEAD commit is
# v2.32.3-1 + ../gin/gin_fault_inject.diff + ../gin_q4/gin_q4_classify.diff).
set -euo pipefail
SRC=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad/gi/gin_recovery/nccl-src
OUT=$(cd "$(dirname "$0")/.." && pwd)/gin_recovery.diff
{
cat <<'HDR'
# GIN GDAKI recovery (research build): bilateral QP reset with fresh PSNs + GPU-side state resync,
# host API for the application's recovery handshake, multi-shot fault hook. Env-gated, default OFF.
#
# base tag: v2.32.3-1  commit: 12df1a11afad322be5a204a2db890161cbf8131d
# LAYERED on top of ../gin/gin_fault_inject.diff and ../gin_q4/gin_q4_classify.diff; apply all three
# from the NCCL source root, in this order:
#   git apply ../gin/gin_fault_inject.diff && git apply ../gin_q4/gin_q4_classify.diff && \
#   git apply gin_recovery.diff
#
# env:
#   NCCL_GIN_FAULT_RECOVERY=1        enable (needs NCCL_GIN_FAULT_CLASSIFY=1; user devComms, GDAKI, ring CQ,
#                                    CPU-proxy doorbell, no counter/companion QPs; otherwise declined)
#   NCCL_GIN_RECOVERY_DRAIN_MS=N     bound on waiting for the CQE of the last posted WQE (default 1000)
#   NCCL_GIN_FAULT_INJECT=local_err:<ms>[,<ms>...] | peer_err:...   (test hook from gin_fault_inject.diff)
#                                    with recovery on: shot k>1 fires <ms> after the recovery commit that
#                                    followed shot k-1 on this rank; -1 = inside that commit (after RTS)
#   NCCL_GIN_FAULT_INJECT_WAIT_S=N   multi-shot hook: give up waiting for a commit after N s (default 60)
#   NCCL_GIN_RECOVERY_DIAG=doca_cqe_rsvd|keep_proxy_db   negative controls only: break one resync step
#                                    on purpose (DOCA's non-cumulative cqe_rsvd / stale proxy doorbell)
#
# files:
#   nccl.h.in  ncclGinFaultInfo_t / ncclGinRecoverToken_t / ncclGinRecoverStats_t,
#              ncclGinFaultQuery, ncclGinRecoverPrepare, ncclGinRecoverCommit, ncclGinRecoverAbort
#   gin/gin_host.cc  thread-local comm key while a devComm's GIN contexts are created
#   transport/net_ib/gdaki/gin_host_gdaki.cc  gdakiConnectQp(rqPsn, sqPsn) (stock callers pass 0),
#              per-QP connect-time info, recovery registry, proxy-progress pause, Prepare (quiescence
#              check, QP->ERR, drain), Commit (2RST, doorbell/proxy/device-index resync, cqe_rsvd advance,
#              get tickets, reconnect, Q4 error clear), Abort, FaultQuery; multi-shot hook
# Design and safety argument: RECOVERY_DESIGN.md.
#
HDR
cd "$SRC" && git diff HEAD -- src
} > "$OUT"
echo "wrote $OUT ($(grep -c '^+' "$OUT") added / $(grep -c '^-' "$OUT") removed lines incl. headers)"
