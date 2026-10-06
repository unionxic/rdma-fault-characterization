/* fp_devx.c - an RC QP created as a DEVX object (as DOCA GPUNetIO / GDAKI and
 * NVSHMEM IBGDA create theirs), for the responder side only.
 *
 * Why: on this OFED (25.10) the uverbs file release first runs
 * mlx5_ib_ufile_hw_cleanup(), which destroys every DEVX *QP* object before the
 * generic uverbs cleanup walks the remaining objects (MRs, CQs, ...). A verbs
 * QP gets no such head start. This file lets the victim use either kind.
 *
 * Layouts come from rdma-core's providers/mlx5/mlx5_ifc.h (third_party/). The QP
 * has a 1-WQEBB send queue (never used) and a zero-length receive queue; its WQ
 * and doorbell record live in one 8 KiB host umem. The RoCE address path is
 * taken from an ibv_ah via mlx5dv_init_obj(), as NVSHMEM does.
 */
#define _GNU_SOURCE
#include "fp_devx.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <infiniband/mlx5dv.h>
#include "third_party/mlx5_ifc.h"

#define FP_MLX5_ZERO_LEN_RQ 0x3

int fp_devx_qp_create(struct ibv_context *ctx, struct ibv_pd *pd, struct ibv_cq *cq, fp_devx_qp_t *q) {
    memset(q, 0, sizeof(*q));
    struct mlx5dv_pd dpd;
    struct mlx5dv_cq dcq;
    struct mlx5dv_obj o;
    memset(&o, 0, sizeof(o));
    o.pd.in = pd;
    o.pd.out = &dpd;
    o.cq.in = cq;
    o.cq.out = &dcq;
    if (mlx5dv_init_obj(&o, MLX5DV_OBJ_PD | MLX5DV_OBJ_CQ)) { fprintf(stderr, "mlx5dv_init_obj pd/cq failed\n"); return -1; }

    q->uar = mlx5dv_devx_alloc_uar(ctx, MLX5DV_UAR_ALLOC_TYPE_NC);
    if (!q->uar) q->uar = mlx5dv_devx_alloc_uar(ctx, MLX5DV_UAR_ALLOC_TYPE_BF);
    if (!q->uar) { perror("mlx5dv_devx_alloc_uar"); return -1; }

    if (posix_memalign(&q->wq_buf, 4096, 8192)) return -1;
    memset(q->wq_buf, 0, 8192);
    q->umem = mlx5dv_devx_umem_reg(ctx, q->wq_buf, 8192, IBV_ACCESS_LOCAL_WRITE);
    if (!q->umem) { perror("mlx5dv_devx_umem_reg"); return -1; }

    uint32_t in[DEVX_ST_SZ_DW(create_qp_in)];
    uint32_t out[DEVX_ST_SZ_DW(create_qp_out)];
    memset(in, 0, sizeof(in));
    memset(out, 0, sizeof(out));
    DEVX_SET(create_qp_in, in, opcode, MLX5_CMD_OP_CREATE_QP);
    DEVX_SET(create_qp_in, in, wq_umem_id, q->umem->umem_id);
    DEVX_SET(create_qp_in, in, wq_umem_valid, 1);
    void *qpc = DEVX_ADDR_OF(create_qp_in, in, qpc);
    DEVX_SET(qpc, qpc, st, MLX5_QPC_ST_RC);
    DEVX_SET(qpc, qpc, pm_state, MLX5_QPC_PM_STATE_MIGRATED);
    DEVX_SET(qpc, qpc, pd, dpd.pdn);
    DEVX_SET(qpc, qpc, uar_page, q->uar->page_id);
    DEVX_SET(qpc, qpc, rq_type, FP_MLX5_ZERO_LEN_RQ);
    DEVX_SET(qpc, qpc, cqn_snd, dcq.cqn);
    DEVX_SET(qpc, qpc, cqn_rcv, dcq.cqn);
    DEVX_SET(qpc, qpc, log_sq_size, 0);
    DEVX_SET(qpc, qpc, log_page_size, 0);          /* 4 KiB */
    DEVX_SET(qpc, qpc, dbr_umem_valid, 1);
    DEVX_SET(qpc, qpc, dbr_umem_id, q->umem->umem_id);
    DEVX_SET64(qpc, qpc, dbr_addr, 4096);
    q->obj = mlx5dv_devx_obj_create(ctx, in, sizeof(in), out, sizeof(out));
    if (!q->obj) {
        fprintf(stderr, "DEVX CREATE_QP failed: errno %d status 0x%x syndrome 0x%x\n", errno,
                DEVX_GET(create_qp_out, out, status), DEVX_GET(create_qp_out, out, syndrome));
        return -1;
    }
    q->qpn = DEVX_GET(create_qp_out, out, qpn);
    return 0;
}

int fp_devx_qp_connect(fp_devx_qp_t *q, struct ibv_pd *pd, uint8_t port, int gid_index, enum ibv_mtu mtu,
                       const fp_dest_t *r, uint32_t local_psn) {
    /* RST -> INIT */
    {
        uint32_t in[DEVX_ST_SZ_DW(rst2init_qp_in)], out[DEVX_ST_SZ_DW(rst2init_qp_out)];
        memset(in, 0, sizeof(in));
        memset(out, 0, sizeof(out));
        DEVX_SET(rst2init_qp_in, in, opcode, MLX5_CMD_OP_RST2INIT_QP);
        DEVX_SET(rst2init_qp_in, in, qpn, q->qpn);
        void *qpc = DEVX_ADDR_OF(rst2init_qp_in, in, qpc);
        DEVX_SET(qpc, qpc, rwe, 1);
        DEVX_SET(qpc, qpc, rre, 1);
        DEVX_SET(qpc, qpc, pm_state, MLX5_QPC_PM_STATE_MIGRATED);
        DEVX_SET(qpc, qpc, primary_address_path.vhca_port_num, port);
        if (mlx5dv_devx_obj_modify(q->obj, in, sizeof(in), out, sizeof(out))) {
            fprintf(stderr, "DEVX RST2INIT failed: status 0x%x syndrome 0x%x\n",
                    DEVX_GET(rst2init_qp_out, out, status), DEVX_GET(rst2init_qp_out, out, syndrome));
            return -1;
        }
    }
    /* address vector from an AH */
    struct ibv_ah_attr aa;
    memset(&aa, 0, sizeof(aa));
    aa.is_global = 1;
    aa.port_num = port;
    aa.grh.dgid = r->gid;
    aa.grh.sgid_index = (uint8_t)gid_index;
    aa.grh.hop_limit = 64;
    q->ah = ibv_create_ah(pd, &aa);
    if (!q->ah) { perror("ibv_create_ah"); return -1; }
    struct mlx5dv_ah dah;
    struct mlx5dv_obj o;
    memset(&o, 0, sizeof(o));
    o.ah.in = q->ah;
    o.ah.out = &dah;
    if (mlx5dv_init_obj(&o, MLX5DV_OBJ_AH)) { fprintf(stderr, "mlx5dv_init_obj ah failed\n"); return -1; }
    /* INIT -> RTR */
    {
        uint32_t in[DEVX_ST_SZ_DW(init2rtr_qp_in)], out[DEVX_ST_SZ_DW(init2rtr_qp_out)];
        memset(in, 0, sizeof(in));
        memset(out, 0, sizeof(out));
        DEVX_SET(init2rtr_qp_in, in, opcode, MLX5_CMD_OP_INIT2RTR_QP);
        DEVX_SET(init2rtr_qp_in, in, qpn, q->qpn);
        void *qpc = DEVX_ADDR_OF(init2rtr_qp_in, in, qpc);
        DEVX_SET(qpc, qpc, mtu, mtu);
        DEVX_SET(qpc, qpc, log_msg_max, 30);
        DEVX_SET(qpc, qpc, remote_qpn, r->qpn);
        DEVX_SET(qpc, qpc, next_rcv_psn, r->psn);
        DEVX_SET(qpc, qpc, min_rnr_nak, fp_min_rnr_timer);
        DEVX_SET(qpc, qpc, log_rra_max, 0);
        memcpy(DEVX_ADDR_OF(qpc, qpc, primary_address_path.rmac_47_32), &dah.av->rmac, sizeof(dah.av->rmac));
        memcpy(DEVX_ADDR_OF(qpc, qpc, primary_address_path.rgid_rip), &dah.av->rgid, sizeof(dah.av->rgid));
        DEVX_SET(qpc, qpc, primary_address_path.hop_limit, 64);
        DEVX_SET(qpc, qpc, primary_address_path.src_addr_index, gid_index);
        DEVX_SET(qpc, qpc, primary_address_path.udp_sport, 0xC000 | (q->qpn & 0x3fff));
        DEVX_SET(qpc, qpc, primary_address_path.vhca_port_num, port);
        if (mlx5dv_devx_obj_modify(q->obj, in, sizeof(in), out, sizeof(out))) {
            fprintf(stderr, "DEVX INIT2RTR failed: status 0x%x syndrome 0x%x\n",
                    DEVX_GET(init2rtr_qp_out, out, status), DEVX_GET(init2rtr_qp_out, out, syndrome));
            return -1;
        }
    }
    /* RTR -> RTS */
    {
        uint32_t in[DEVX_ST_SZ_DW(rtr2rts_qp_in)], out[DEVX_ST_SZ_DW(rtr2rts_qp_out)];
        memset(in, 0, sizeof(in));
        memset(out, 0, sizeof(out));
        DEVX_SET(rtr2rts_qp_in, in, opcode, MLX5_CMD_OP_RTR2RTS_QP);
        DEVX_SET(rtr2rts_qp_in, in, qpn, q->qpn);
        void *qpc = DEVX_ADDR_OF(rtr2rts_qp_in, in, qpc);
        DEVX_SET(qpc, qpc, next_send_psn, local_psn);
        DEVX_SET(qpc, qpc, retry_count, FP_RETRY_CNT);
        DEVX_SET(qpc, qpc, rnr_retry, FP_RNR_RETRY);
        DEVX_SET(qpc, qpc, log_sra_max, 0);
        DEVX_SET(qpc, qpc, primary_address_path.ack_timeout, FP_IB_TIMEOUT);
        if (mlx5dv_devx_obj_modify(q->obj, in, sizeof(in), out, sizeof(out))) {
            fprintf(stderr, "DEVX RTR2RTS failed: status 0x%x syndrome 0x%x\n",
                    DEVX_GET(rtr2rts_qp_out, out, status), DEVX_GET(rtr2rts_qp_out, out, syndrome));
            return -1;
        }
    }
    return 0;
}

int fp_devx_qp_destroy(fp_devx_qp_t *q) {
    int rc = q->obj ? mlx5dv_devx_obj_destroy(q->obj) : 0;
    q->obj = NULL;
    return rc;
}
