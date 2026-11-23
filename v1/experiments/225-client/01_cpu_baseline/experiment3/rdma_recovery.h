/*
 * rdma_recovery.h - In-place QP state transitions for recovery
 *
 * Part of: GPU-Initiated RDMA Fault Recovery Research
 * Experiment 3: QP Recovery Overhead Decomposition
 *
 * Exposes individual ibv_modify_qp transitions so each stage can be
 * timed in isolation. Reuses the existing rdma_ctx_t (same QPN, same
 * MR, same remote_info, same local_psn) — no destroy/create, no
 * re-exchange of QP info with the peer.
 */

#ifndef RDMA_RECOVERY_H
#define RDMA_RECOVERY_H

#include "rdma_common.h"

/* ERR -> RESET (clears in-flight state, QP becomes unusable). */
int rdma_qp_to_reset(rdma_ctx_t *rctx);

/* RESET -> INIT (port/pkey/access). */
int rdma_qp_to_init(rdma_ctx_t *rctx);

/*
 * INIT -> RTR. Uses rctx->remote_info (remote qpn/psn/gid) which was
 * cached on initial connection; valid for in-place recovery because
 * the peer's QPN and MR rkey don't change.
 */
int rdma_qp_to_rtr(rdma_ctx_t *rctx);

/*
 * RTR -> RTS. Reuses rctx->local_psn, retry/timeout values identical
 * to the original connection (timeout=14, retry_cnt=7, rnr_retry=7).
 */
int rdma_qp_to_rts(rdma_ctx_t *rctx);

/*
 * Drain every CQE currently in the CQ. Used after detecting the first
 * error CQE to consume flush errors for the other outstanding WRs, so
 * the next post's successful CQE is not preceded by stale flushes.
 * Returns count drained, -1 on error.
 */
int rdma_drain_all_cq(rdma_ctx_t *rctx);

#endif /* RDMA_RECOVERY_H */
