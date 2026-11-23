/*
 * rdma_common.h - RDMA resource management for fault detection experiment
 *
 * Provides setup/teardown of IB resources (context, PD, CQ, QP, MR)
 * with manual QP setup suitable for RoCE (GID-based addressing).
 *
 * All ibv_* return values are checked. Resources are tracked for
 * clean teardown even on error paths.
 */

#ifndef RDMA_COMMON_H
#define RDMA_COMMON_H

#include <infiniband/verbs.h>
#include "common.h"

/* ----------------------------------------------------------------
 * RDMA resource context - tracks all allocated resources
 * ---------------------------------------------------------------- */

typedef struct {
    /* Device */
    struct ibv_context      *ctx;
    struct ibv_device       **dev_list;
    struct ibv_port_attr    port_attr;
    union ibv_gid           local_gid;
    int                     ib_port;
    int                     gid_index;

    /* Protection domain */
    struct ibv_pd           *pd;

    /* Completion queue */
    struct ibv_cq           *cq;

    /* Queue pair */
    struct ibv_qp           *qp;
    uint32_t                local_psn;

    /* Memory region */
    struct ibv_mr           *mr;
    void                    *buf;
    size_t                  buf_size;

    /* Remote side info (filled after exchange) */
    qp_info_t               remote_info;

    /* Device capabilities */
    struct ibv_device_attr  dev_attr;
    int                     max_inline_data;
} rdma_ctx_t;

/* ----------------------------------------------------------------
 * Function declarations
 * ---------------------------------------------------------------- */

/*
 * Open the specified IB device and allocate basic resources:
 * context, PD, CQ, buffer, MR.
 *
 * Does NOT create a QP - call rdma_create_qp() separately.
 *
 * Returns 0 on success, -1 on failure.
 */
int rdma_init_ctx(rdma_ctx_t *rctx, const char *dev_name, int ib_port,
                  int gid_index, size_t buf_size);

/*
 * Create a Reliable Connected (RC) QP in RESET state.
 * Returns 0 on success, -1 on failure.
 */
int rdma_create_qp(rdma_ctx_t *rctx);

/*
 * Fill a qp_info_t structure with local QP parameters for exchange.
 */
void rdma_get_local_info(const rdma_ctx_t *rctx, qp_info_t *info);

/*
 * Transition QP through RESET -> INIT -> RTR -> RTS using
 * the remote QP info. RoCE-specific: sets is_global=1 and
 * fills GRH fields.
 *
 * Returns 0 on success, -1 on failure.
 */
int rdma_connect_qp(rdma_ctx_t *rctx, const qp_info_t *remote);

/*
 * Transition QP to ERR state (for fault injection scenario A).
 * Returns 0 on success, -1 on failure.
 */
int rdma_set_qp_err(rdma_ctx_t *rctx);

/*
 * Drain all remaining CQEs from the CQ.
 * Must be called after QP enters error state and before QP destruction,
 * per libibverbs requirements.
 * Returns number of CQEs drained, or -1 on error.
 */
int rdma_drain_cq(rdma_ctx_t *rctx);

/*
 * Destroy the QP only (for reset between iterations).
 * Other resources (PD, CQ, MR) remain valid.
 */
void rdma_destroy_qp(rdma_ctx_t *rctx);

/*
 * Destroy all RDMA resources and free memory.
 */
void rdma_destroy_ctx(rdma_ctx_t *rctx);

/*
 * Post an RDMA Write work request.
 *
 * Parameters:
 *   rctx      - RDMA context with connected QP
 *   signaled  - whether to request a completion signal
 *   wr_id     - work request ID for tracking
 *
 * Returns 0 on success, -1 on failure.
 */
int rdma_post_write(rdma_ctx_t *rctx, bool signaled, uint64_t wr_id);

/*
 * Poll the CQ for up to `max_entries` completions.
 * Returns number of completions polled (0 if none), -1 on error.
 * Fills `wc` array with completions.
 */
int rdma_poll_cq(rdma_ctx_t *rctx, struct ibv_wc *wc, int max_entries);

/*
 * Print device information to stderr for environment documentation.
 */
void rdma_print_device_info(const rdma_ctx_t *rctx, const char *dev_name);

#endif /* RDMA_COMMON_H */
