/*
 * rdma_common.c - RDMA resource management implementation
 *
 * Part of: GPU-Initiated RDMA Fault Recovery Research
 * Experiment 1: CPU-mediated fault detection baseline latency
 *
 * Implements manual QP setup for RoCE (GID-based addressing, no LID).
 * All ibv_* calls have return-value checks. Resource cleanup is
 * performed in reverse allocation order.
 *
 * [UNTESTED: requires RDMA NIC]
 * The GID index default (3) is typical for RoCEv2 on mlx5 but may
 * vary by system. Run `show_gids` or `ibv_devinfo -v` to verify
 * the correct GID index for your setup.
 */

#include "rdma_common.h"

/* ----------------------------------------------------------------
 * rdma_init_ctx - Open device, create PD/CQ/MR
 * ---------------------------------------------------------------- */
int rdma_init_ctx(rdma_ctx_t *rctx, const char *dev_name, int ib_port,
                  int gid_index, size_t buf_size)
{
    int ret;

    memset(rctx, 0, sizeof(*rctx));
    rctx->ib_port = ib_port;
    rctx->gid_index = gid_index;
    rctx->buf_size = buf_size;
    rctx->max_inline_data = 0; /* will be set after QP creation */

    /* --- Get device list --- */
    int num_devices = 0;
    rctx->dev_list = ibv_get_device_list(&num_devices);
    CHECK(rctx->dev_list && num_devices > 0,
          "No IB devices found (num_devices=%d)", num_devices);

    /* --- Find the requested device --- */
    struct ibv_device *ib_dev = NULL;
    for (int i = 0; i < num_devices; i++) {
        if (strcmp(ibv_get_device_name(rctx->dev_list[i]), dev_name) == 0) {
            ib_dev = rctx->dev_list[i];
            break;
        }
    }
    CHECK(ib_dev != NULL, "IB device '%s' not found", dev_name);

    /* --- Open device context --- */
    rctx->ctx = ibv_open_device(ib_dev);
    CHECK(rctx->ctx != NULL, "ibv_open_device failed for '%s'", dev_name);

    /* --- Query device attributes --- */
    ret = ibv_query_device(rctx->ctx, &rctx->dev_attr);
    CHECK(ret == 0, "ibv_query_device failed: %s", strerror(errno));

    /* --- Query port attributes --- */
    ret = ibv_query_port(rctx->ctx, ib_port, &rctx->port_attr);
    CHECK(ret == 0, "ibv_query_port(%d) failed: %s", ib_port, strerror(errno));

    CHECK(rctx->port_attr.state == IBV_PORT_ACTIVE,
          "Port %d is not active (state=%d). Check link and run ibstat.",
          ib_port, rctx->port_attr.state);

    /* --- Query GID for RoCE --- */
    ret = ibv_query_gid(rctx->ctx, ib_port, gid_index, &rctx->local_gid);
    CHECK(ret == 0, "ibv_query_gid(port=%d, idx=%d) failed: %s",
          ib_port, gid_index, strerror(errno));

    {
        char gid_str[80];
        gid_to_str(&rctx->local_gid, gid_str, sizeof(gid_str));
        LOG_INFO("Local GID[%d]: %s", gid_index, gid_str);
    }

    /* --- Allocate Protection Domain --- */
    rctx->pd = ibv_alloc_pd(rctx->ctx);
    CHECK(rctx->pd != NULL, "ibv_alloc_pd failed");

    /* --- Create Completion Queue --- */
    rctx->cq = ibv_create_cq(rctx->ctx, MAX_CQ_ENTRIES, NULL, NULL, 0);
    CHECK(rctx->cq != NULL, "ibv_create_cq(%d) failed", MAX_CQ_ENTRIES);

    /* --- Allocate and register buffer --- */
    ret = posix_memalign(&rctx->buf, 4096, buf_size);
    CHECK(ret == 0, "posix_memalign(%zu) failed", buf_size);
    memset(rctx->buf, 0xAB, buf_size); /* fill with pattern for debugging */

    rctx->mr = ibv_reg_mr(rctx->pd, rctx->buf, buf_size,
                           IBV_ACCESS_LOCAL_WRITE |
                           IBV_ACCESS_REMOTE_WRITE |
                           IBV_ACCESS_REMOTE_READ);
    CHECK(rctx->mr != NULL, "ibv_reg_mr failed: %s", strerror(errno));

    LOG_INFO("RDMA context initialized: dev=%s port=%d gid_idx=%d buf=%zuB",
             dev_name, ib_port, gid_index, buf_size);

    return 0;
}

/* ----------------------------------------------------------------
 * rdma_create_qp - Create RC QP in RESET state
 * ---------------------------------------------------------------- */
int rdma_create_qp(rdma_ctx_t *rctx)
{
    struct ibv_qp_init_attr qp_init_attr;
    memset(&qp_init_attr, 0, sizeof(qp_init_attr));

    qp_init_attr.send_cq = rctx->cq;
    qp_init_attr.recv_cq = rctx->cq;
    qp_init_attr.qp_type = IBV_QPT_RC;

    qp_init_attr.cap.max_send_wr  = MAX_SEND_WR;
    qp_init_attr.cap.max_recv_wr  = 16;  /* We don't use RDMA recv, but need >0 */
    qp_init_attr.cap.max_send_sge = 1;
    qp_init_attr.cap.max_recv_sge = 1;
    qp_init_attr.cap.max_inline_data = 256; /* Request inline for small msgs */

    qp_init_attr.sq_sig_all = 0; /* We control signaling per-WR */

    rctx->qp = ibv_create_qp(rctx->pd, &qp_init_attr);
    CHECK(rctx->qp != NULL, "ibv_create_qp failed: %s", strerror(errno));

    /* Record actual inline data capability */
    rctx->max_inline_data = qp_init_attr.cap.max_inline_data;

    /* Generate a random PSN */
    srand48(getpid() * time(NULL));
    rctx->local_psn = lrand48() & 0xFFFFFF;

    LOG_INFO("QP created: qpn=0x%x, psn=0x%x, max_inline=%d",
             rctx->qp->qp_num, rctx->local_psn, rctx->max_inline_data);

    return 0;
}

/* ----------------------------------------------------------------
 * rdma_get_local_info - Fill qp_info_t for exchange
 * ---------------------------------------------------------------- */
void rdma_get_local_info(const rdma_ctx_t *rctx, qp_info_t *info)
{
    memset(info, 0, sizeof(*info));
    info->qpn  = rctx->qp->qp_num;
    info->psn  = rctx->local_psn;
    info->addr = (uint64_t)(uintptr_t)rctx->buf;
    info->rkey = rctx->mr->rkey;
    memcpy(info->gid, rctx->local_gid.raw, 16);
}

/* ----------------------------------------------------------------
 * rdma_connect_qp - Transition RESET -> INIT -> RTR -> RTS
 *
 * RoCE-specific: is_global=1, GRH fields filled from remote GID.
 * ---------------------------------------------------------------- */
int rdma_connect_qp(rdma_ctx_t *rctx, const qp_info_t *remote)
{
    int ret;
    struct ibv_qp_attr attr;
    int flags;

    /* Save remote info */
    rctx->remote_info = *remote;

    /* --- RESET -> INIT --- */
    memset(&attr, 0, sizeof(attr));
    attr.qp_state        = IBV_QPS_INIT;
    attr.pkey_index      = 0;
    attr.port_num        = rctx->ib_port;
    attr.qp_access_flags = IBV_ACCESS_REMOTE_WRITE |
                           IBV_ACCESS_REMOTE_READ |
                           IBV_ACCESS_LOCAL_WRITE;

    flags = IBV_QP_STATE | IBV_QP_PKEY_INDEX | IBV_QP_PORT | IBV_QP_ACCESS_FLAGS;
    ret = ibv_modify_qp(rctx->qp, &attr, flags);
    CHECK(ret == 0, "RESET->INIT failed: %s (ret=%d)", strerror(errno), ret);
    LOG_INFO("QP state: RESET -> INIT");

    /* --- INIT -> RTR --- */
    memset(&attr, 0, sizeof(attr));
    attr.qp_state              = IBV_QPS_RTR;
    attr.path_mtu              = IBV_MTU_1024; /* Safe default; CX-5 supports 4096 */
    attr.dest_qp_num           = remote->qpn;
    attr.rq_psn                = remote->psn;
    attr.max_dest_rd_atomic    = 1;
    attr.min_rnr_timer         = 12; /* 0.01ms */

    /* RoCE: must use global routing (GRH) */
    attr.ah_attr.is_global     = 1;
    attr.ah_attr.port_num      = rctx->ib_port;
    attr.ah_attr.sl            = 0;

    /* Fill GRH with remote GID */
    memcpy(attr.ah_attr.grh.dgid.raw, remote->gid, 16);
    attr.ah_attr.grh.sgid_index = rctx->gid_index;
    attr.ah_attr.grh.hop_limit  = 64;
    attr.ah_attr.grh.flow_label = 0;
    attr.ah_attr.grh.traffic_class = 0;

    flags = IBV_QP_STATE | IBV_QP_AV | IBV_QP_PATH_MTU |
            IBV_QP_DEST_QPN | IBV_QP_RQ_PSN |
            IBV_QP_MAX_DEST_RD_ATOMIC | IBV_QP_MIN_RNR_TIMER;
    ret = ibv_modify_qp(rctx->qp, &attr, flags);
    CHECK(ret == 0, "INIT->RTR failed: %s (ret=%d)", strerror(errno), ret);
    LOG_INFO("QP state: INIT -> RTR");

    /* --- RTR -> RTS --- */
    memset(&attr, 0, sizeof(attr));
    attr.qp_state      = IBV_QPS_RTS;
    attr.sq_psn         = rctx->local_psn;
    attr.timeout        = 14;  /* ~67ms */
    attr.retry_cnt      = 7;   /* Max retries before error */
    attr.rnr_retry      = 7;   /* Max RNR retries */
    attr.max_rd_atomic  = 1;

    flags = IBV_QP_STATE | IBV_QP_SQ_PSN | IBV_QP_TIMEOUT |
            IBV_QP_RETRY_CNT | IBV_QP_RNR_RETRY | IBV_QP_MAX_QP_RD_ATOMIC;
    ret = ibv_modify_qp(rctx->qp, &attr, flags);
    CHECK(ret == 0, "RTR->RTS failed: %s (ret=%d)", strerror(errno), ret);
    LOG_INFO("QP state: RTR -> RTS (connected to remote QPN 0x%x)", remote->qpn);

    return 0;
}

/* ----------------------------------------------------------------
 * rdma_set_qp_err - Move QP to ERROR state
 * ---------------------------------------------------------------- */
int rdma_set_qp_err(rdma_ctx_t *rctx)
{
    struct ibv_qp_attr attr;
    memset(&attr, 0, sizeof(attr));
    attr.qp_state = IBV_QPS_ERR;

    int ret = ibv_modify_qp(rctx->qp, &attr, IBV_QP_STATE);
    CHECK(ret == 0, "Failed to move QP to ERR: %s", strerror(errno));
    LOG_INFO("QP state: -> ERR (fault injected)");

    return 0;
}

/* ----------------------------------------------------------------
 * rdma_drain_cq - Drain all CQEs (required before QP destruction)
 * ---------------------------------------------------------------- */
int rdma_drain_cq(rdma_ctx_t *rctx)
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

    if (total > 0) {
        LOG_INFO("Drained %d CQEs from CQ", total);
    }
    return total;
}

/* ----------------------------------------------------------------
 * rdma_destroy_qp - Destroy QP only
 * ---------------------------------------------------------------- */
void rdma_destroy_qp(rdma_ctx_t *rctx)
{
    if (rctx->qp) {
        rdma_drain_cq(rctx);
        int ret = ibv_destroy_qp(rctx->qp);
        if (ret != 0) {
            LOG_WARN("ibv_destroy_qp failed: %s", strerror(errno));
        }
        rctx->qp = NULL;
    }
}

/* ----------------------------------------------------------------
 * rdma_destroy_ctx - Destroy all resources
 * ---------------------------------------------------------------- */
void rdma_destroy_ctx(rdma_ctx_t *rctx)
{
    /* Destroy in reverse allocation order */
    rdma_destroy_qp(rctx);

    if (rctx->mr) {
        if (ibv_dereg_mr(rctx->mr) != 0)
            LOG_WARN("ibv_dereg_mr failed: %s", strerror(errno));
        rctx->mr = NULL;
    }

    if (rctx->cq) {
        if (ibv_destroy_cq(rctx->cq) != 0)
            LOG_WARN("ibv_destroy_cq failed: %s", strerror(errno));
        rctx->cq = NULL;
    }

    if (rctx->pd) {
        if (ibv_dealloc_pd(rctx->pd) != 0)
            LOG_WARN("ibv_dealloc_pd failed: %s", strerror(errno));
        rctx->pd = NULL;
    }

    if (rctx->ctx) {
        if (ibv_close_device(rctx->ctx) != 0)
            LOG_WARN("ibv_close_device failed: %s", strerror(errno));
        rctx->ctx = NULL;
    }

    if (rctx->dev_list) {
        ibv_free_device_list(rctx->dev_list);
        rctx->dev_list = NULL;
    }

    if (rctx->buf) {
        free(rctx->buf);
        rctx->buf = NULL;
    }

    LOG_INFO("RDMA context destroyed");
}

/* ----------------------------------------------------------------
 * rdma_post_write - Post RDMA Write WR
 * ---------------------------------------------------------------- */
int rdma_post_write(rdma_ctx_t *rctx, bool signaled, uint64_t wr_id)
{
    struct ibv_sge sge;
    memset(&sge, 0, sizeof(sge));
    sge.addr   = (uint64_t)(uintptr_t)rctx->buf;
    sge.length = rctx->buf_size;
    sge.lkey   = rctx->mr->lkey;

    struct ibv_send_wr wr;
    memset(&wr, 0, sizeof(wr));
    wr.wr_id                  = wr_id;
    wr.opcode                 = IBV_WR_RDMA_WRITE;
    wr.sg_list                = &sge;
    wr.num_sge                = 1;
    wr.send_flags             = signaled ? IBV_SEND_SIGNALED : 0;
    wr.wr.rdma.remote_addr    = rctx->remote_info.addr;
    wr.wr.rdma.rkey           = rctx->remote_info.rkey;

    /* Use inline for small payloads if supported */
    if ((int)rctx->buf_size <= rctx->max_inline_data) {
        wr.send_flags |= IBV_SEND_INLINE;
    }

    struct ibv_send_wr *bad_wr = NULL;
    int ret = ibv_post_send(rctx->qp, &wr, &bad_wr);
    if (ret != 0) {
        LOG_ERR("ibv_post_send failed: %s (ret=%d, wr_id=%lu)",
                strerror(errno), ret, wr_id);
        return -1;
    }

    return 0;
}

/* ----------------------------------------------------------------
 * rdma_poll_cq - Poll CQ for completions
 * ---------------------------------------------------------------- */
int rdma_poll_cq(rdma_ctx_t *rctx, struct ibv_wc *wc, int max_entries)
{
    int ne = ibv_poll_cq(rctx->cq, max_entries, wc);
    if (ne < 0) {
        LOG_ERR("ibv_poll_cq failed: %s", strerror(errno));
        return -1;
    }
    return ne;
}

/* ----------------------------------------------------------------
 * rdma_print_device_info - Document the hardware environment
 * ---------------------------------------------------------------- */
void rdma_print_device_info(const rdma_ctx_t *rctx, const char *dev_name)
{
    fprintf(stderr, "\n=== RDMA Device Information ===\n");
    fprintf(stderr, "Device:         %s\n", dev_name);
    fprintf(stderr, "FW version:     %s\n", rctx->dev_attr.fw_ver);
    fprintf(stderr, "Max QP:         %d\n", rctx->dev_attr.max_qp);
    fprintf(stderr, "Max QP WR:      %d\n", rctx->dev_attr.max_qp_wr);
    fprintf(stderr, "Max CQ:         %d\n", rctx->dev_attr.max_cq);
    fprintf(stderr, "Max CQE:        %d\n", rctx->dev_attr.max_cqe);
    fprintf(stderr, "Max MR:         %d\n", rctx->dev_attr.max_mr);
    fprintf(stderr, "Port:           %d\n", rctx->ib_port);
    fprintf(stderr, "Port state:     %d (4=ACTIVE)\n", rctx->port_attr.state);
    fprintf(stderr, "Port MTU:       %d\n", rctx->port_attr.active_mtu);
    fprintf(stderr, "Max msg size:   %u\n", rctx->port_attr.max_msg_sz);
    fprintf(stderr, "GID index:      %d\n", rctx->gid_index);

    char gid_str[80];
    gid_to_str(&rctx->local_gid, gid_str, sizeof(gid_str));
    fprintf(stderr, "Local GID:      %s\n", gid_str);
    fprintf(stderr, "================================\n\n");
}
