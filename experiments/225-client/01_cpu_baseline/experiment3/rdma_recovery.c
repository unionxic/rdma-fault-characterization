/*
 * rdma_recovery.c - In-place QP state transition helpers
 *
 * Mirrors the transitions in rdma_common.c::rdma_connect_qp() but
 * exposes them as individual functions so each can be timed.
 * Parameters (path_mtu, min_rnr_timer, timeout, retry_cnt, rnr_retry)
 * match rdma_common.c exactly — experiment3 must measure the same
 * configuration used in experiments 1 and 2.
 */

#include "rdma_recovery.h"

int rdma_qp_to_reset(rdma_ctx_t *rctx)
{
    struct ibv_qp_attr attr;
    memset(&attr, 0, sizeof(attr));
    attr.qp_state = IBV_QPS_RESET;

    int ret = ibv_modify_qp(rctx->qp, &attr, IBV_QP_STATE);
    if (ret != 0) {
        LOG_ERR("ERR->RESET failed: %s (ret=%d)", strerror(errno), ret);
        return -1;
    }
    return 0;
}

int rdma_qp_to_init(rdma_ctx_t *rctx)
{
    struct ibv_qp_attr attr;
    memset(&attr, 0, sizeof(attr));
    attr.qp_state        = IBV_QPS_INIT;
    attr.pkey_index      = 0;
    attr.port_num        = rctx->ib_port;
    attr.qp_access_flags = IBV_ACCESS_REMOTE_WRITE |
                           IBV_ACCESS_REMOTE_READ |
                           IBV_ACCESS_LOCAL_WRITE;

    int flags = IBV_QP_STATE | IBV_QP_PKEY_INDEX |
                IBV_QP_PORT | IBV_QP_ACCESS_FLAGS;

    int ret = ibv_modify_qp(rctx->qp, &attr, flags);
    if (ret != 0) {
        LOG_ERR("RESET->INIT failed: %s (ret=%d)", strerror(errno), ret);
        return -1;
    }
    return 0;
}

int rdma_qp_to_rtr(rdma_ctx_t *rctx)
{
    struct ibv_qp_attr attr;
    memset(&attr, 0, sizeof(attr));
    attr.qp_state           = IBV_QPS_RTR;
    attr.path_mtu           = IBV_MTU_1024;
    attr.dest_qp_num        = rctx->remote_info.qpn;
    attr.rq_psn             = rctx->remote_info.psn;
    attr.max_dest_rd_atomic = 1;
    attr.min_rnr_timer      = 12;

    attr.ah_attr.is_global     = 1;
    attr.ah_attr.port_num      = rctx->ib_port;
    attr.ah_attr.sl            = 0;
    memcpy(attr.ah_attr.grh.dgid.raw, rctx->remote_info.gid, 16);
    attr.ah_attr.grh.sgid_index    = rctx->gid_index;
    attr.ah_attr.grh.hop_limit     = 64;
    attr.ah_attr.grh.flow_label    = 0;
    attr.ah_attr.grh.traffic_class = 0;

    int flags = IBV_QP_STATE | IBV_QP_AV | IBV_QP_PATH_MTU |
                IBV_QP_DEST_QPN | IBV_QP_RQ_PSN |
                IBV_QP_MAX_DEST_RD_ATOMIC | IBV_QP_MIN_RNR_TIMER;

    int ret = ibv_modify_qp(rctx->qp, &attr, flags);
    if (ret != 0) {
        LOG_ERR("INIT->RTR failed: %s (ret=%d)", strerror(errno), ret);
        return -1;
    }
    return 0;
}

int rdma_qp_to_rts(rdma_ctx_t *rctx)
{
    struct ibv_qp_attr attr;
    memset(&attr, 0, sizeof(attr));
    attr.qp_state      = IBV_QPS_RTS;
    attr.sq_psn        = rctx->local_psn;
    attr.timeout       = 14;
    attr.retry_cnt     = 7;
    attr.rnr_retry     = 7;
    attr.max_rd_atomic = 1;

    int flags = IBV_QP_STATE | IBV_QP_SQ_PSN | IBV_QP_TIMEOUT |
                IBV_QP_RETRY_CNT | IBV_QP_RNR_RETRY | IBV_QP_MAX_QP_RD_ATOMIC;

    int ret = ibv_modify_qp(rctx->qp, &attr, flags);
    if (ret != 0) {
        LOG_ERR("RTR->RTS failed: %s (ret=%d)", strerror(errno), ret);
        return -1;
    }
    return 0;
}

int rdma_drain_all_cq(rdma_ctx_t *rctx)
{
    struct ibv_wc wc[32];
    int total = 0;
    int ne;
    do {
        ne = ibv_poll_cq(rctx->cq, 32, wc);
        if (ne < 0) {
            LOG_ERR("ibv_poll_cq failed during drain: %s", strerror(errno));
            return -1;
        }
        total += ne;
    } while (ne > 0);
    return total;
}
