/* fp_devx.h - RC QP as a DEVX object (see fp_devx.c) */
#ifndef FP_DEVX_H
#define FP_DEVX_H
#include "fp_common.h"

struct mlx5dv_devx_obj;
struct mlx5dv_devx_uar;
struct mlx5dv_devx_umem;

typedef struct {
    struct mlx5dv_devx_obj *obj;
    struct mlx5dv_devx_uar *uar;
    struct mlx5dv_devx_umem *umem;
    struct ibv_ah *ah;
    void *wq_buf;
    uint32_t qpn;
} fp_devx_qp_t;

/* ctx must come from mlx5dv_open_device(..., MLX5DV_CONTEXT_FLAGS_DEVX) */
int fp_devx_qp_create(struct ibv_context *ctx, struct ibv_pd *pd, struct ibv_cq *cq, fp_devx_qp_t *q);
int fp_devx_qp_connect(fp_devx_qp_t *q, struct ibv_pd *pd, uint8_t port, int gid_index, enum ibv_mtu mtu,
                       const fp_dest_t *remote, uint32_t local_psn);
int fp_devx_qp_destroy(fp_devx_qp_t *q);
#endif
