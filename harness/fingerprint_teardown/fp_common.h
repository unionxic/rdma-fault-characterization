/* fp_common.h - shared helpers for the teardown-fingerprint experiment.
 *
 * Three programs:
 *   fp_launcher  (responder node) forks the victim, SIGKILLs it on request, and
 *                timestamps the victim's exit and the FIN of every "marker" socket
 *                the victim opened (each marker = one file in its fd table).
 *   fp_responder (responder node) the victim: RC QP + MR over host or GPU memory,
 *                with the order of CUDA init / ibv_open_device and MR / QP selectable.
 *   fp_requester (requester node) streams signaled RDMA WRITEs into the victim's MR,
 *                triggers the fault, records the first error CQE.
 * All times are CLOCK_MONOTONIC_RAW nanoseconds.
 */
#ifndef FP_COMMON_H
#define FP_COMMON_H

#include <stdint.h>
#include <stddef.h>
#include <infiniband/verbs.h>

#define FP_IB_TIMEOUT   14   /* 4.096 us * 2^14 = 67 ms per attempt */
#define FP_RETRY_CNT    7
#define FP_RNR_RETRY    6    /* finite (7 = infinite); WRITEs never RNR anyway */

uint64_t fp_now_ns(void);

/* TCP */
int fp_listen(const char *bind_ip, int port);           /* SO_REUSEADDR, backlog 16 */
int fp_accept(int lfd);                                  /* TCP_NODELAY */
int fp_connect(const char *host, int port);              /* TCP_NODELAY; -1 on failure */
int fp_send_all(int fd, const void *buf, size_t len);
int fp_recv_all(int fd, void *buf, size_t len);
int fp_send_line(int fd, const char *fmt, ...) __attribute__((format(printf, 2, 3)));
/* read one '\n'-terminated line (without the '\n'); returns length, -1 on EOF/error */
int fp_recv_line(int fd, char *buf, size_t cap);
void fp_set_cloexec(int fd);

/* RDMA endpoint (no MR: the responder chooses its own memory) */
typedef struct {
    uint32_t qpn;
    uint32_t psn;
    uint32_t rkey;
    uint32_t pad;
    uint64_t addr;
    uint64_t size;
    union ibv_gid gid;
} fp_dest_t;

typedef struct {
    struct ibv_context *ctx;
    struct ibv_pd *pd;
    struct ibv_cq *cq;
    struct ibv_qp *qp;
    struct ibv_port_attr port_attr;
    union ibv_gid gid;
    int gid_index;
    uint8_t port;
} fp_ep_t;

/* index of the RoCE v2 IPv4-mapped GID of dev/port, or -1 */
int fp_find_roce_v2_ipv4_gid(const char *dev, int port);
/* ctx+pd+cq; devx=1 opens the context with mlx5dv_open_device(MLX5DV_CONTEXT_FLAGS_DEVX) */
int fp_open(fp_ep_t *ep, const char *dev, int port, int gid_index, int devx);
int fp_create_qp(fp_ep_t *ep, int max_send_wr);
int fp_qp_to_rts(fp_ep_t *ep, const fp_dest_t *remote, uint32_t local_psn);  /* INIT->RTR->RTS */
/* responder-side RNR NAK timer code written at RTR (IB encoding, default 12 = 0.64 ms) */
extern int fp_min_rnr_timer;

const char *fp_status_short(int st);

#endif
