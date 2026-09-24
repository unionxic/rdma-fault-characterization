/*
 * tr_probe.c - feasibility probe for app-transparent recovery of GPU-initiated RDMA
 * (../TRANSPARENT_RECOVERY_DESIGN.md). CPU only, mlx5 DEVX, one RC QP pair: requester on rain
 * (mlx5_1), responder on sunny (mlx5_0). WQE shapes as the GPU libraries post them (RDMA WRITE
 * with one SGE, 8-byte ATOMIC FETCH_ADD, RDMA READ; the inline-WRITE builder exists but is not
 * generated); every WQE signaled;
 * 64-byte ring CQ; the SQ doorbell record's send word is written.
 *
 * Questions (design doc, section "Probe"):
 *   Q1  Does QUERY_QP on the responder return a next expected PSN (next_rcv_psn) and MSN (rmsn)
 *       equal to the PSN / message count right after the last request it executed - after its
 *       QP went to ERR, and while it is still in RTS and only the requester failed?
 *       Ground truth: responder memory (every WRITE compared word by word with the pattern, every
 *       FETCH_ADD counter).
 *   Q2  With that PSN, is "reset, then replay exactly the requests from the first unexecuted one"
 *       exactly-once for hundreds of requests in flight? Mode B: both QPs reset (responder was in
 *       ERR). Mode A: responder untouched (RTS); only the requester is reset and continues at
 *       the responder's PSN.
 *   Q3  If only the requester is reset and rewinds into requests the responder already executed
 *       (duplicates), are WRITEs executed again, and are duplicate atomics answered from the
 *       responder's replay state or executed again (by rewind depth)?
 *   Q4  Does a send CQE's wqe_counter come from the WQE ctrl segment's index field or from the
 *       NIC's own WQE counter, and is a differing index field accepted?
 *
 * Scenarios (-S):
 *   resp_err  responder moves its QP to ERR a random delay after the first WRITE landed; the
 *             requester ends in RETRY_EXC; recovery Mode B.
 *   req_err   requester moves its own QP to ERR a random delay after the doorbell; the responder
 *             stays RTS; recovery Mode A.
 *   dup       no fault; all requests complete; the requester alone is reset, rewinds its PSN by
 *             --dup-depth requests and posts them again (WRITE targets are not overwritten first).
 *   wqeidx    Q4.
 * Every wait is bounded and each process ends on its own (alarm). Uses only its own QP pair.
 */
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <endian.h>
#include <errno.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <stdarg.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

#include <infiniband/mlx5dv.h>
#include <infiniband/verbs.h>

#include "tr_prm.h"

#define PSN_MASK 0xffffffu
#define MAXR 1600          /* plan entries incl. fresh ones */
#define BUF_LEN (64u << 20)
#define W_END (46u << 20)  /* WRITE targets [0, W_END)             */
#define R_BASE (48u << 20) /* READ sources/destinations [R_BASE, R_END) */
#define R_END (56u << 20)
#define A_BASE (56u << 20) /* FETCH_ADD counters / results, 8 B each */
#define LOG_SQ 11
#define LOG_CQ 12

enum { OP_WRITE = 0, OP_WINL = 1, OP_FADD = 2, OP_READ = 3 };
static const char OPN[] = "WIAR";

struct req { /* sent verbatim to the responder (same ABI on both nodes: x86_64, gcc) */
    uint8_t op, nwqebb, ds, pad;
    uint32_t bytes;
    uint32_t npkts;
    uint32_t psn;  /* first PSN (24 bit) */
    uint64_t roff; /* offset in the peer's buffer (same offset used locally) */
    uint64_t lidx; /* logical WQEBB index */
    uint64_t cum;  /* packets of all earlier requests */
};

struct peer_info {
    uint32_t qpn, rkey, mtu, max_rd_atom;
    uint64_t addr;
    uint8_t gid[16];
};

struct plan_hdr {
    uint32_t n, k, mtu, psn0;
    uint64_t seed, seed_r, seed_r2;
};

struct qpc_snap {
    int ok, state;
    uint32_t next_send_psn, last_acked_psn, ssn, next_rcv_psn, rmsn;
    uint32_t hw_sq, sw_sq, hw_rq, sw_rq, cur_retry;
    double query_us;
};

struct opts {
    int requester;
    const char *dev, *peer, *scen;
    int port, gid_idx, ib_port, ack_timeout, retry_cnt, life_s;
    int k, delay_max_us, dup_depth, fresh_psn, recover, trial, reads;
    unsigned long long seed;
};
static struct opts o;

struct ctx {
    struct ibv_context *ctx;
    struct ibv_pd *pd;
    uint32_t pdn;
    struct ibv_port_attr pattr;
    union ibv_gid gid;
    int max_rd_atom;
    uint8_t *buf;
    struct ibv_mr *mr;
    void *cq_buf, *cq_dbr, *sq_buf, *qp_dbr;
    struct mlx5dv_devx_umem *cq_umem, *cq_dbr_umem, *sq_umem, *qp_dbr_umem;
    struct mlx5dv_devx_uar *cq_uar, *qp_uar;
    struct mlx5dv_devx_obj *cq, *qp;
    struct ibv_ah *ah;
    uint32_t cqn, qpn, ncqe, nwqebb, qctr_id;
    uint64_t cq_ci;
    struct peer_info peer;
};

static struct timespec t_start;
static double now_us(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (t.tv_sec - t_start.tv_sec) * 1e6 + (t.tv_nsec - t_start.tv_nsec) / 1e3;
}

static void die(const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    printf("FATAL ");
    vprintf(fmt, ap);
    printf("\n");
    fflush(stdout);
    va_end(ap);
    exit(3);
}

static void *xalign(size_t align, size_t len) {
    void *p = NULL;
    if (posix_memalign(&p, align, len)) die("posix_memalign %zu", len);
    memset(p, 0, len);
    return p;
}

/* deterministic generators */
static uint64_t mix64(uint64_t x) {
    x += 0x9e3779b97f4a7c15ull;
    x = (x ^ (x >> 30)) * 0xbf58476d1ce4e5b9ull;
    x = (x ^ (x >> 27)) * 0x94d049bb133111ebull;
    return x ^ (x >> 31);
}
static uint64_t pat(uint64_t seed, uint64_t off) { return mix64(seed ^ (off * 0x100000001b3ull)); }
static uint64_t rng_state;
static uint64_t rnd(void) { return mix64(rng_state++); }

/* ------------------------------------------------------------------------------------ */
/* control socket (management network)                                                  */
/* ------------------------------------------------------------------------------------ */

static void xsend(int fd, const void *b, size_t n) {
    const char *c = b;
    while (n) {
        ssize_t r = send(fd, c, n, MSG_NOSIGNAL);
        if (r <= 0) die("ctrl send: %s", strerror(errno));
        c += r;
        n -= (size_t)r;
    }
}

static int xrecv(int fd, void *b, size_t n, int tmo_ms) {
    char *c = b;
    double t_end = now_us() + tmo_ms * 1e3;
    while (n) {
        int left = (int)((t_end - now_us()) / 1e3);
        if (left <= 0) return -1;
        struct pollfd pf = {.fd = fd, .events = POLLIN};
        if (poll(&pf, 1, left) <= 0) continue;
        ssize_t k = recv(fd, c, n, 0);
        if (k <= 0) return -1;
        c += k;
        n -= (size_t)k;
    }
    return 0;
}

static int ctrl_connect(const char *host, int port) {
    for (int i = 0; i < 100; i++) {
        int fd = socket(AF_INET, SOCK_STREAM, 0), one = 1;
        struct sockaddr_in a = {.sin_family = AF_INET, .sin_port = htons((uint16_t)port)};
        inet_pton(AF_INET, host, &a.sin_addr);
        if (connect(fd, (struct sockaddr *)&a, sizeof(a)) == 0) {
            setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));
            return fd;
        }
        close(fd);
        usleep(100000);
    }
    die("ctrl connect %s:%d failed", host, port);
    return -1;
}

static int ctrl_accept(int port, int tmo_ms) {
    int lfd = socket(AF_INET, SOCK_STREAM, 0), one = 1;
    setsockopt(lfd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
    struct sockaddr_in a = {.sin_family = AF_INET, .sin_port = htons((uint16_t)port), .sin_addr.s_addr = INADDR_ANY};
    if (bind(lfd, (struct sockaddr *)&a, sizeof(a)) || listen(lfd, 1)) die("bind/listen %d: %s", port, strerror(errno));
    struct pollfd pf = {.fd = lfd, .events = POLLIN};
    if (poll(&pf, 1, tmo_ms) <= 0) die("no requester within %d ms", tmo_ms);
    int fd = accept(lfd, NULL, NULL);
    close(lfd);
    if (fd < 0) die("accept: %s", strerror(errno));
    setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));
    return fd;
}

/* ------------------------------------------------------------------------------------ */
/* DEVX objects                                                                         */
/* ------------------------------------------------------------------------------------ */

static uint32_t st_of(const void *out) { return DEVX_GET(modify_qp_out, out, status); }
static uint32_t sy_of(const void *out) { return DEVX_GET(modify_qp_out, out, syndrome); }

static struct mlx5dv_devx_uar *alloc_uar(struct ibv_context *c) {
    struct mlx5dv_devx_uar *u = mlx5dv_devx_alloc_uar(c, MLX5DV_UAR_ALLOC_TYPE_NC);
    if (!u) die("alloc_uar: %s", strerror(errno));
    return u;
}

static int ilog2i(int v) { int l = 0; while ((1 << (l + 1)) <= v) l++; return l; }

static void create_cq(struct ctx *c) {
    c->ncqe = 1u << LOG_CQ;
    size_t len = (size_t)c->ncqe * 64;
    c->cq_buf = xalign(65536, len);
    memset(c->cq_buf, 0xff, len); /* MLX5_CQE_INVALID owner pattern */
    c->cq_dbr = xalign(65536, 4096);
    c->cq_umem = mlx5dv_devx_umem_reg(c->ctx, c->cq_buf, len, IBV_ACCESS_LOCAL_WRITE);
    c->cq_dbr_umem = mlx5dv_devx_umem_reg(c->ctx, c->cq_dbr, 4096, IBV_ACCESS_LOCAL_WRITE);
    if (!c->cq_umem || !c->cq_dbr_umem) die("CQ umem: %s", strerror(errno));
    c->cq_uar = alloc_uar(c->ctx);
    uint32_t eqn = 0;
    if (mlx5dv_devx_query_eqn(c->ctx, 0, &eqn)) die("query_eqn");
    uint32_t in[DEVX_ST_SZ_DW(create_cq_in)] = {0}, out[DEVX_ST_SZ_DW(create_cq_out)] = {0};
    DEVX_SET(create_cq_in, in, opcode, MLX5_CMD_OP_CREATE_CQ);
    DEVX_SET(create_cq_in, in, cq_umem_id, c->cq_umem->umem_id);
    DEVX_SET(create_cq_in, in, cq_umem_valid, 1);
    void *cqc = DEVX_ADDR_OF(create_cq_in, in, cq_context);
    DEVX_SET(cqc, cqc, dbr_umem_valid, 1);
    DEVX_SET(cqc, cqc, cqe_sz, 0);
    DEVX_SET(cqc, cqc, cc, 0); /* ring CQ (not collapsed): every CQE visible */
    DEVX_SET(cqc, cqc, oi, 1);
    DEVX_SET(cqc, cqc, dbr_umem_id, c->cq_dbr_umem->umem_id);
    DEVX_SET(cqc, cqc, log_cq_size, LOG_CQ);
    DEVX_SET(cqc, cqc, uar_page, c->cq_uar->page_id);
    DEVX_SET(cqc, cqc, c_eqn, eqn);
    DEVX_SET(cqc, cqc, log_page_size, 4);
    c->cq = mlx5dv_devx_obj_create(c->ctx, in, sizeof(in), out, sizeof(out));
    if (!c->cq) die("CREATE_CQ st 0x%x sy 0x%x", st_of(out), sy_of(out));
    c->cqn = DEVX_GET(create_cq_out, out, cqn);
}

/* the per-port q counter the kernel attaches to verbs QPs (behind hw_counters) */
static void port_qcounter(struct ctx *c) {
    struct ibv_cq *vcq = ibv_create_cq(c->ctx, 4, NULL, NULL, 0);
    struct ibv_qp_init_attr ia = {.send_cq = vcq, .recv_cq = vcq, .qp_type = IBV_QPT_RC,
                                  .cap = {.max_send_wr = 1, .max_recv_wr = 1, .max_send_sge = 1, .max_recv_sge = 1}};
    struct ibv_qp *vqp = vcq ? ibv_create_qp(c->pd, &ia) : NULL;
    struct ibv_qp_attr qa = {.qp_state = IBV_QPS_INIT, .port_num = (uint8_t)o.ib_port};
    if (!vqp || ibv_modify_qp(vqp, &qa, IBV_QP_STATE | IBV_QP_PKEY_INDEX | IBV_QP_PORT | IBV_QP_ACCESS_FLAGS)) {
        c->qctr_id = 0;
        if (vqp) ibv_destroy_qp(vqp);
        if (vcq) ibv_destroy_cq(vcq);
        return;
    }
    uint32_t in[DEVX_ST_SZ_DW(query_qp_in)] = {0}, out[DEVX_ST_SZ_DW(query_qp_out)] = {0};
    DEVX_SET(query_qp_in, in, opcode, MLX5_CMD_OP_QUERY_QP);
    DEVX_SET(query_qp_in, in, qpn, vqp->qp_num);
    if (!mlx5dv_devx_qp_query(vqp, in, sizeof(in), out, sizeof(out)))
        c->qctr_id = DEVX_GET(qpc, DEVX_ADDR_OF(query_qp_out, out, qpc), counter_set_id);
    ibv_destroy_qp(vqp);
    ibv_destroy_cq(vcq);
}

static void create_qp(struct ctx *c) {
    c->nwqebb = 1u << LOG_SQ;
    size_t len = (size_t)c->nwqebb * 64;
    c->sq_buf = xalign(65536, len);
    c->qp_dbr = xalign(65536, 4096);
    c->sq_umem = mlx5dv_devx_umem_reg(c->ctx, c->sq_buf, len, IBV_ACCESS_LOCAL_WRITE);
    c->qp_dbr_umem = mlx5dv_devx_umem_reg(c->ctx, c->qp_dbr, 4096, IBV_ACCESS_LOCAL_WRITE);
    if (!c->sq_umem || !c->qp_dbr_umem) die("QP umem: %s", strerror(errno));
    c->qp_uar = alloc_uar(c->ctx);
    uint32_t in[DEVX_ST_SZ_DW(create_qp_in)] = {0}, out[DEVX_ST_SZ_DW(create_qp_out)] = {0};
    DEVX_SET(create_qp_in, in, opcode, MLX5_CMD_OP_CREATE_QP);
    DEVX_SET(create_qp_in, in, wq_umem_id, c->sq_umem->umem_id);
    DEVX_SET(create_qp_in, in, wq_umem_valid, 1);
    void *qpc = DEVX_ADDR_OF(create_qp_in, in, qpc);
    DEVX_SET(qpc, qpc, st, NRC_QPC_ST_RC);
    DEVX_SET(qpc, qpc, pm_state, NRC_QPC_PM_STATE_MIGRATED);
    DEVX_SET(qpc, qpc, pd, c->pdn);
    DEVX_SET(qpc, qpc, uar_page, c->qp_uar->page_id);
    DEVX_SET(qpc, qpc, cqn_snd, c->cqn);
    DEVX_SET(qpc, qpc, cqn_rcv, c->cqn);
    DEVX_SET(qpc, qpc, log_sq_size, LOG_SQ);
    DEVX_SET(qpc, qpc, rq_type, NRC_QPC_RQ_TYPE_ZERO_SIZE_RQ); /* responder needs no RQ WQEs for RDMA/atomic */
    DEVX_SET(qpc, qpc, dbr_umem_valid, 1);
    DEVX_SET(qpc, qpc, dbr_umem_id, c->qp_dbr_umem->umem_id);
    DEVX_SET(qpc, qpc, ts_format, 0);
    c->qp = mlx5dv_devx_obj_create(c->ctx, in, sizeof(in), out, sizeof(out));
    if (!c->qp) die("CREATE_QP st 0x%x sy 0x%x", st_of(out), sy_of(out));
    c->qpn = DEVX_GET(create_qp_out, out, qpn);
}

static void do_modify(struct ctx *c, uint32_t *in, size_t inlen, const char *what) {
    uint32_t out[DEVX_ST_SZ_DW(modify_qp_out)] = {0};
    if (mlx5dv_devx_obj_modify(c->qp, in, inlen, out, sizeof(out)))
        die("%s st 0x%x sy 0x%x: %s", what, st_of(out), sy_of(out), strerror(errno));
}

/* RST->INIT->RTR->RTS. rq_psn is the responder's expected first PSN; sq_psn our first PSN.
 * bad_mac!=0 poisons the destination MAC (ack_bh); rq_psn/sq_psn are 24-bit. */
static void bringup(struct ctx *c, const struct peer_info *pi, uint32_t rq_psn, uint32_t sq_psn, int bad_mac) {
    uint32_t in[DEVX_ST_SZ_DW(modify_qp_in)];
    void *qpc = DEVX_ADDR_OF(modify_qp_in, in, qpc);

    memset(in, 0, sizeof(in));
    DEVX_SET(modify_qp_in, in, opcode, MLX5_CMD_OP_RST2INIT_QP);
    DEVX_SET(modify_qp_in, in, qpn, c->qpn);
    DEVX_SET(qpc, qpc, rwe, 1);
    DEVX_SET(qpc, qpc, rre, 1);
    DEVX_SET(qpc, qpc, rae, 1);
    DEVX_SET(qpc, qpc, atomic_mode, 3); /* up to 8-byte atomics (IB spec) */
    DEVX_SET(qpc, qpc, primary_address_path.vhca_port_num, o.ib_port);
    DEVX_SET(qpc, qpc, primary_address_path.pkey_index, 0);
    DEVX_SET(qpc, qpc, pm_state, NRC_QPC_PM_STATE_MIGRATED);
    DEVX_SET(qpc, qpc, counter_set_id, c->qctr_id);
    do_modify(c, in, sizeof(in), "RST2INIT");

    struct ibv_ah_attr ah = {.is_global = 1, .port_num = (uint8_t)o.ib_port};
    memcpy(ah.grh.dgid.raw, pi->gid, 16);
    ah.grh.sgid_index = (uint8_t)o.gid_idx;
    ah.grh.hop_limit = 255;
    c->ah = ibv_create_ah(c->pd, &ah);
    if (!c->ah) die("create_ah: %s", strerror(errno));
    struct mlx5dv_obj dv = {0};
    struct mlx5dv_ah dah = {0};
    dv.ah.in = c->ah;
    dv.ah.out = &dah;
    if (mlx5dv_init_obj(&dv, MLX5DV_OBJ_AH)) die("init_obj ah");

    memset(in, 0, sizeof(in));
    DEVX_SET(modify_qp_in, in, opcode, MLX5_CMD_OP_INIT2RTR_QP);
    DEVX_SET(modify_qp_in, in, qpn, c->qpn);
    DEVX_SET(qpc, qpc, mtu, c->pattr.active_mtu);
    DEVX_SET(qpc, qpc, log_msg_max, 30);
    DEVX_SET(qpc, qpc, remote_qpn, pi->qpn);
    DEVX_SET(qpc, qpc, next_rcv_psn, rq_psn & PSN_MASK);
    DEVX_SET(qpc, qpc, min_rnr_nak, 12);
    DEVX_SET(qpc, qpc, log_rra_max, ilog2i(c->max_rd_atom));
    uint8_t rmac[6];
    memcpy(rmac, dah.av->rmac, 6);
    if (bad_mac) rmac[5] ^= 0xa5;
    memcpy(DEVX_ADDR_OF(qpc, qpc, primary_address_path.rmac_47_32), rmac, 6);
    DEVX_SET(qpc, qpc, primary_address_path.hop_limit, 255);
    DEVX_SET(qpc, qpc, primary_address_path.src_addr_index, o.gid_idx);
    DEVX_SET(qpc, qpc, primary_address_path.udp_sport, 0xc000);
    memcpy(DEVX_ADDR_OF(qpc, qpc, primary_address_path.rgid_rip), pi->gid, 16);
    do_modify(c, in, sizeof(in), "INIT2RTR");

    memset(in, 0, sizeof(in));
    DEVX_SET(modify_qp_in, in, opcode, MLX5_CMD_OP_RTR2RTS_QP);
    DEVX_SET(modify_qp_in, in, qpn, c->qpn);
    DEVX_SET(qpc, qpc, log_ack_req_freq, 0);
    DEVX_SET(qpc, qpc, log_sra_max, ilog2i(c->max_rd_atom));
    DEVX_SET(qpc, qpc, next_send_psn, sq_psn & PSN_MASK);
    DEVX_SET(qpc, qpc, retry_count, o.retry_cnt);
    DEVX_SET(qpc, qpc, rnr_retry, 7);
    DEVX_SET(qpc, qpc, primary_address_path.ack_timeout, o.ack_timeout);
    do_modify(c, in, sizeof(in), "RTR2RTS");
}

static int qp_to(struct ctx *c, int rst) {
    uint32_t in[DEVX_ST_SZ_DW(qp_2err_in)] = {0}, out[DEVX_ST_SZ_DW(modify_qp_out)] = {0};
    DEVX_SET(qp_2err_in, in, opcode, rst ? MLX5_CMD_OP_2RST_QP : MLX5_CMD_OP_2ERR_QP);
    DEVX_SET(qp_2err_in, in, qpn, c->qpn);
    return mlx5dv_devx_obj_modify(c->qp, in, sizeof(in), out, sizeof(out));
}

static struct qpc_snap query_qp(struct ctx *c) {
    struct qpc_snap s = {0};
    uint32_t in[DEVX_ST_SZ_DW(query_qp_in)] = {0}, out[DEVX_ST_SZ_DW(query_qp_out)] = {0};
    DEVX_SET(query_qp_in, in, opcode, MLX5_CMD_OP_QUERY_QP);
    DEVX_SET(query_qp_in, in, qpn, c->qpn);
    double t = now_us();
    if (mlx5dv_devx_obj_query(c->qp, in, sizeof(in), out, sizeof(out))) {
        s.ok = 0;
        s.state = -1;
        return s;
    }
    s.query_us = now_us() - t;
    s.ok = 1;
    void *qpc = DEVX_ADDR_OF(query_qp_out, out, qpc);
    s.state = DEVX_GET(qpc, qpc, state);
    s.next_send_psn = DEVX_GET(qpc, qpc, next_send_psn);
    s.last_acked_psn = DEVX_GET(qpc, qpc, last_acked_psn);
    s.ssn = DEVX_GET(qpc, qpc, ssn);
    s.next_rcv_psn = DEVX_GET(qpc, qpc, next_rcv_psn);
    s.rmsn = DEVX_GET(qpc, qpc, rmsn);
    s.hw_sq = DEVX_GET(qpc, qpc, hw_sq_wqebb_counter);
    s.sw_sq = DEVX_GET(qpc, qpc, sw_sq_wqebb_counter);
    s.hw_rq = DEVX_GET(qpc, qpc, hw_rq_counter);
    s.sw_rq = DEVX_GET(qpc, qpc, sw_rq_counter);
    s.cur_retry = DEVX_GET(qpc, qpc, cur_retry_count);
    return s;
}

/* ------------------------------------------------------------------------------------ */
/* WQE building and doorbell (requester)                                                */
/* ------------------------------------------------------------------------------------ */

struct wqe_ctrl { uint32_t opmod_idx_opcode, qpn_ds; uint8_t signature, rsvd[2], fm_ce_se; uint32_t imm; };
struct wqe_raddr { uint64_t raddr; uint32_t rkey, rsvd; };
struct wqe_data { uint32_t byte_count, lkey; uint64_t addr; };
struct wqe_atomic { uint64_t swap_add, compare; };

static void *wqe_at(struct ctx *c, uint64_t idx) { return (uint8_t *)c->sq_buf + (idx & (c->nwqebb - 1)) * 64; }

/* number of WQEBBs a request occupies (index-field spacing = physical spacing) */
static int req_nwqebb(const struct req *r) {
    if (r->op == OP_WINL) {
        int seg = 16 + 16 + 4 + (int)r->bytes; /* ctrl + raddr + inline hdr + data */
        return (seg + 63) / 64;
    }
    return 1; /* WRITE(one SGE)=ctrl+raddr+data=48B, FADD=ctrl+raddr+atomic+data=64B, READ=48B */
}

/* idxfield override: normally the WQEBB index; for wqeidx test we pass a different value */
static void build_wqe(struct ctx *c, const struct req *r, uint64_t idxfield) {
    uint8_t *w = wqe_at(c, r->lidx);
    memset(w, 0, (size_t)r->nwqebb * 64);
    struct wqe_ctrl *ctl = (void *)w;
    ctl->qpn_ds = htobe32((c->qpn << 8) | r->ds);
    ctl->fm_ce_se = 8; /* MLX5_WQE_CTRL_CQ_UPDATE: signal every WQE */
    uint64_t la = (uint64_t)(uintptr_t)c->buf;
    if (r->op == OP_WRITE) {
        ctl->opmod_idx_opcode = htobe32(((uint32_t)(idxfield & 0xffff) << 8) | 0x08);
        struct wqe_raddr *ra = (void *)(w + 16);
        struct wqe_data *d = (void *)(w + 32);
        ra->raddr = htobe64(c->peer.addr + r->roff);
        ra->rkey = htobe32(c->peer.rkey);
        d->byte_count = htobe32(r->bytes);
        d->lkey = htobe32(c->mr->lkey);
        d->addr = htobe64(la + r->roff);
    } else if (r->op == OP_WINL) {
        ctl->opmod_idx_opcode = htobe32(((uint32_t)(idxfield & 0xffff) << 8) | 0x08);
        struct wqe_raddr *ra = (void *)(w + 16);
        ra->raddr = htobe64(c->peer.addr + r->roff);
        ra->rkey = htobe32(c->peer.rkey);
        uint32_t *inl = (uint32_t *)(w + 32);
        inl[0] = htobe32(0x80000000u | r->bytes); /* inline data seg header */
        uint8_t *dst = (uint8_t *)(inl + 1);
        for (uint32_t i = 0; i < r->bytes; i++) dst[i] = (uint8_t)(c->buf[r->roff + i]);
    } else if (r->op == OP_FADD) {
        ctl->opmod_idx_opcode = htobe32(((uint32_t)(idxfield & 0xffff) << 8) | 0x12);
        struct wqe_raddr *ra = (void *)(w + 16);
        struct wqe_atomic *at = (void *)(w + 32);
        struct wqe_data *d = (void *)(w + 48);
        ra->raddr = htobe64(c->peer.addr + r->roff);
        ra->rkey = htobe32(c->peer.rkey);
        at->swap_add = htobe64(1);
        d->byte_count = htobe32(8);
        d->lkey = htobe32(c->mr->lkey);
        d->addr = htobe64(la + A_BASE + r->lidx * 8); /* local result slot (unique per lidx) */
    } else { /* OP_READ: read peer [roff,roff+bytes) into local R_BASE+... */
        ctl->opmod_idx_opcode = htobe32(((uint32_t)(idxfield & 0xffff) << 8) | 0x10);
        struct wqe_raddr *ra = (void *)(w + 16);
        struct wqe_data *d = (void *)(w + 32);
        ra->raddr = htobe64(c->peer.addr + r->roff);
        ra->rkey = htobe32(c->peer.rkey);
        d->byte_count = htobe32(r->bytes);
        d->lkey = htobe32(c->mr->lkey);
        d->addr = htobe64(la + R_BASE + (r->lidx * 4096) % (R_END - R_BASE));
    }
}

static inline void mmio64(void *reg, uint64_t v) { *(volatile uint64_t *)reg = v; }

static void ring_db(struct ctx *c, uint64_t pi) {
    struct wqe_ctrl ctl = {0};
    ctl.opmod_idx_opcode = htobe32((uint32_t)(pi << 8));
    ctl.qpn_ds = htobe32(c->qpn << 8);
    uint64_t db;
    memcpy(&db, &ctl, 8);
    volatile uint32_t *dbr = (volatile uint32_t *)c->qp_dbr;
    __sync_synchronize();
    dbr[1] = htobe32((uint32_t)(pi & 0xffff)); /* MLX5_SND_DBR = word 1 (correct word) */
    __atomic_thread_fence(__ATOMIC_RELEASE);
    mmio64(c->qp_uar->reg_addr, db);
}

/* ------------------------------------------------------------------------------------ */
/* CQ reading (requester, ring CQ)                                                      */
/* ------------------------------------------------------------------------------------ */

struct cqe_view { uint8_t op, owner, syndrome, vendor; uint16_t wqe; };
static struct cqe_view read_cqe(struct ctx *c, uint32_t slot) {
    volatile uint8_t *e = (volatile uint8_t *)c->cq_buf + (size_t)slot * 64;
    uint8_t op_own = e[63];
    __atomic_thread_fence(__ATOMIC_ACQUIRE);
    struct cqe_view v;
    v.op = op_own >> 4;
    v.owner = op_own & 1;
    v.vendor = e[54];
    v.syndrome = e[55];
    v.wqe = (uint16_t)((e[60] << 8) | e[61]);
    return v;
}

/* Drain the CQ: consume every CQE (good, error, or flush) up to `target`, advancing cq_ci past
 * errors. This is the ib_drain-style step the design requires: after a QP error every posted WQE
 * flushes with its own CQE, and those must be consumed before the CQ is reused for the replay,
 * or the replay poll would misread a stale flush/error CQE. Returns #errors seen. */
static int drain_cq(struct ctx *c, uint64_t target, int tmo_ms, int *timed_out) {
    double t_end = now_us() + tmo_ms * 1e3;
    int errs = 0;
    *timed_out = 0;
    while (c->cq_ci < target) {
        if (now_us() > t_end) { *timed_out = 1; break; }
        uint32_t slot = (uint32_t)(c->cq_ci & (c->ncqe - 1));
        int sw_owner = (int)((c->cq_ci >> LOG_CQ) & 1);
        struct cqe_view v = read_cqe(c, slot);
        if (v.op == 0xf || v.owner != sw_owner) continue;
        if (v.op == 0xd || v.op == 0xe) errs++;
        c->cq_ci++;
    }
    return errs;
}

/* poll until cons index reaches want (0 ok, 1 first error CQE seen, 2 timeout).
 * On success advances c->cq_ci to want. On error returns the error CQE. */
static int poll_to(struct ctx *c, uint64_t want, int tmo_ms, struct cqe_view *err) {
    double t_end = now_us() + tmo_ms * 1e3;
    while (c->cq_ci < want) {
        if (now_us() > t_end) return 2;
        uint32_t slot = (uint32_t)(c->cq_ci & (c->ncqe - 1));
        int sw_owner = (int)((c->cq_ci >> LOG_CQ) & 1);
        struct cqe_view v = read_cqe(c, slot);
        if (v.op == 0xf || v.owner != sw_owner) continue; /* invalid / not yet written */
        if (v.op == 0xd || v.op == 0xe) { *err = v; return 1; }
        c->cq_ci++;
    }
    return 0;
}

/* ------------------------------------------------------------------------------------ */
/* common setup                                                                         */
/* ------------------------------------------------------------------------------------ */

static void setup(struct ctx *c) {
    int n = 0;
    struct ibv_device **l = ibv_get_device_list(&n), *d = NULL;
    for (int i = 0; l && i < n; i++)
        if (!strcmp(ibv_get_device_name(l[i]), o.dev)) d = l[i];
    if (!d) die("device %s not found", o.dev);
    struct mlx5dv_context_attr ca = {.flags = MLX5DV_CONTEXT_FLAGS_DEVX};
    c->ctx = mlx5dv_open_device(d, &ca);
    if (!c->ctx) die("open_device DEVX: %s", strerror(errno));
    ibv_free_device_list(l);
    c->pd = ibv_alloc_pd(c->ctx);
    if (!c->pd) die("alloc_pd");
    struct mlx5dv_obj dv = {0};
    struct mlx5dv_pd dpd = {0};
    dv.pd.in = c->pd;
    dv.pd.out = &dpd;
    if (mlx5dv_init_obj(&dv, MLX5DV_OBJ_PD)) die("init_obj pd");
    c->pdn = dpd.pdn;
    if (ibv_query_port(c->ctx, o.ib_port, &c->pattr)) die("query_port");
    if (ibv_query_gid(c->ctx, o.ib_port, o.gid_idx, &c->gid)) die("query_gid");
    struct ibv_device_attr da;
    if (ibv_query_device(c->ctx, &da)) die("query_device");
    c->max_rd_atom = da.max_qp_rd_atom;
    c->buf = xalign(4096, BUF_LEN);
    c->mr = ibv_reg_mr(c->pd, c->buf, BUF_LEN,
                       IBV_ACCESS_LOCAL_WRITE | IBV_ACCESS_REMOTE_WRITE | IBV_ACCESS_REMOTE_READ | IBV_ACCESS_REMOTE_ATOMIC);
    if (!c->mr) die("reg_mr: %s", strerror(errno));
    port_qcounter(c);
    create_cq(c);
    create_qp(c);
}

/* ------------------------------------------------------------------------------------ */
/* plan (identical on both ends)                                                        */
/* ------------------------------------------------------------------------------------ */

static struct req plan[MAXR];
static struct plan_hdr ph;

/* fill the write-source region of the requester's buffer with the write pattern */
static void fill_write_src(struct ctx *c, uint64_t seed_w) {
    for (uint64_t off = 0; off + 8 <= W_END; off += 8) {
        uint64_t v = pat(seed_w, off);
        memcpy(c->buf + off, &v, 8);
    }
}
/* responder: prefill its whole buffer: background in write region, read pattern in read region */
static void fill_resp(struct ctx *c, uint64_t seed_bg, uint64_t seed_r) {
    for (uint64_t off = 0; off + 8 <= W_END; off += 8) {
        uint64_t v = pat(seed_bg, off);
        memcpy(c->buf + off, &v, 8);
    }
    for (uint64_t off = R_BASE; off + 8 <= R_END; off += 8) {
        uint64_t v = pat(seed_r, off);
        memcpy(c->buf + off, &v, 8);
    }
    memset(c->buf + A_BASE, 0, BUF_LEN - A_BASE); /* atomic counters start at 0 */
}

/* generate a mixed plan; requires ctx for mtu */
static void gen_plan(uint32_t mtu, uint32_t psn0) {
    int N = o.k;
    if (N > MAXR - 8) N = MAXR - 8;
    ph.n = (uint32_t)N;
    ph.k = (uint32_t)N;
    ph.mtu = mtu;
    ph.psn0 = psn0;
    ph.seed = o.seed ^ 0x5717ull;
    ph.seed_r = o.seed ^ 0x9931ull;
    ph.seed_r2 = o.seed ^ 0xbb00ull; /* background pattern in the responder write region */
    uint64_t wcur = 0, rcur = R_BASE, fcur = 0, cum = 0, lidx = 0;
    rng_state = o.seed ^ 0xa1b2c3d4ull;
    for (int i = 0; i < N; i++) {
        struct req *r = &plan[i];
        uint32_t roll = (uint32_t)(rnd() % 100);
        uint8_t op;
        if (o.reads) {
            if (roll < 70) op = OP_WRITE;
            else if (roll < 85) op = OP_FADD;
            else op = OP_READ;
        } else {
            if (roll < 82) op = OP_WRITE;
            else op = OP_FADD;
        }
        uint32_t bytes;
        uint64_t roff;
        if (op == OP_WRITE) {
            /* spread of sizes incl. small single-packet and large multi-packet writes */
            uint32_t choice = (uint32_t)(rnd() % 5);
            bytes = choice == 0 ? 64 : choice == 1 ? 256 : choice == 2 ? 4096
                    : choice == 3 ? (mtu * 3 + 100) : (mtu * 7 + 33);
            roff = wcur;
            wcur += (bytes + 4095) & ~4095ull;
            if (wcur + (1u << 16) > W_END) wcur = 0; /* wrap; distinct enough for a prefix test */
        } else if (op == OP_FADD) {
            bytes = 8;
            roff = A_BASE + (uint64_t)fcur * 8;
            fcur++;
        } else { /* READ */
            uint32_t choice = (uint32_t)(rnd() % 3);
            bytes = choice == 0 ? 256 : choice == 1 ? 8192 : (mtu * 4 + 7);
            roff = rcur;
            rcur += (bytes + 4095) & ~4095ull;
            if (rcur + (1u << 17) > R_END) rcur = R_BASE;
        }
        uint32_t npkts = op == OP_FADD ? 1 : (bytes + mtu - 1) / mtu;
        r->op = op;
        r->bytes = bytes;
        r->npkts = npkts;
        r->roff = roff;
        r->lidx = lidx;
        r->cum = cum;
        r->psn = (uint32_t)((psn0 + cum) & PSN_MASK);
        r->nwqebb = (uint8_t)req_nwqebb(r);
        r->ds = op == OP_FADD ? 4 : 3; /* WRITE/READ: ctrl+raddr+data=3; FADD: +atomic=4 */
        lidx += r->nwqebb;
        cum += npkts;
    }
    ph.k = (uint32_t)N;
    int nw = 0, nf = 0, nr = 0;
    for (int i = 0; i < N; i++) { if (plan[i].op == OP_FADD) nf++; else if (plan[i].op == OP_READ) nr++; else nw++; }
    printf("EV what=plan n=%d writes=%d fadd=%d read=%d total_pkts=%llu total_wqebb=%llu op0=%c\n", N, nw, nf, nr,
           (unsigned long long)cum, (unsigned long long)lidx, OPN[plan[0].op]);
}

/* which requests are fully executed given the responder's next expected PSN */
static int executed_prefix_from_psn(uint32_t next_rcv_psn, uint32_t psn0) {
    uint32_t exec_pkts = (next_rcv_psn - psn0) & PSN_MASK;
    int p = 0;
    for (int i = 0; i < (int)ph.n; i++) {
        if (plan[i].cum + plan[i].npkts <= exec_pkts) p = i + 1;
        else break;
    }
    return p;
}

/* ------------------------------------------------------------------------------------ */
/* responder ground truth                                                                */
/* ------------------------------------------------------------------------------------ */

struct verify {
    int landed_writes, notlanded_writes, corrupt_writes;
    int fadd_zero, fadd_one, fadd_multi;
    int reads;
    int mem_prefix;   /* longest in-order executed prefix from memory */
    int mem_gap;      /* 1 if an executed request appears after a non-executed one (out of order) */
};

/* is write i landed in the responder buffer? 1 yes, 0 background(no), -1 corrupt/partial */
static int write_landed(struct ctx *c, const struct req *r, uint64_t seed_w, uint64_t seed_bg) {
    int good = 0, bg = 0, other = 0;
    for (uint64_t off = 0; off + 8 <= r->bytes; off += 8) {
        uint64_t v;
        memcpy(&v, c->buf + r->roff + off, 8);
        uint64_t exp = pat(seed_w, r->roff + off);
        uint64_t expbg = pat(seed_bg, r->roff + off);
        if (v == exp) good++;
        else if (v == expbg) bg++;
        else other++;
    }
    int total = (int)(r->bytes / 8);
    if (total == 0) total = 1;
    if (other) return -1;
    if (good == total) return 1;
    if (bg == total) return 0;
    return -1; /* mix of good and background = partial */
}

static struct verify verify_all(struct ctx *c) {
    struct verify v = {0};
    int last_exec = -1, seen_notexec = 0;
    for (int i = 0; i < (int)ph.n; i++) {
        struct req *r = &plan[i];
        int exec = 0;
        if (r->op == OP_WRITE || r->op == OP_WINL) {
            int l = write_landed(c, r, ph.seed, ph.seed_r2);
            if (l == 1) { v.landed_writes++; exec = 1; }
            else if (l == 0) v.notlanded_writes++;
            else { v.corrupt_writes++; exec = -1; }
        } else if (r->op == OP_FADD) {
            uint64_t cnt;
            memcpy(&cnt, c->buf + r->roff, 8);
            if (cnt == 0) v.fadd_zero++;
            else if (cnt == 1) { v.fadd_one++; exec = 1; }
            else { v.fadd_multi++; exec = 1; }
        } else { /* READ: responder cannot see it; treat as neutral (ignore for prefix) */
            v.reads++;
            exec = -2;
        }
        if (exec == 1) {
            if (seen_notexec) v.mem_gap = 1;
            last_exec = i;
        } else if (exec == 0) {
            seen_notexec = 1;
        }
        /* exec==-2 (read) neutral: does not break the prefix, inherits neighbours */
    }
    /* mem_prefix = count of requests up to and including the last executed non-read,
     * with reads in between counted as executed (they run in order between writes) */
    v.mem_prefix = last_exec + 1;
    return v;
}

/* ------------------------------------------------------------------------------------ */
/* plan transfer over ctrl                                                               */
/* ------------------------------------------------------------------------------------ */

static void send_plan(int fd) {
    xsend(fd, &ph, sizeof(ph));
    xsend(fd, plan, sizeof(struct req) * ph.n);
}
static void recv_plan(int fd) {
    if (xrecv(fd, &ph, sizeof(ph), 10000)) die("recv plan_hdr");
    if (ph.n > MAXR) die("plan too big");
    if (xrecv(fd, plan, sizeof(struct req) * ph.n, 10000)) die("recv plan");
}

/* fixed 96-byte reply record for Q/V */
struct rep {
    int32_t state, mem_prefix, mem_gap;
    uint32_t next_rcv_psn, rmsn, hw_rq, sw_rq;
    int32_t landed, notlanded, corrupt, fadd_zero, fadd_one, fadd_multi, reads;
    double query_us;
    uint32_t pad;
};

/* ------------------------------------------------------------------------------------ */
/* responder                                                                            */
/* ------------------------------------------------------------------------------------ */

static int run_responder(struct ctx *c) {
    int fd = ctrl_accept(o.port, o.life_s * 1000);
    struct peer_info me = {.qpn = c->qpn, .rkey = c->mr->rkey, .mtu = c->pattr.active_mtu,
                           .max_rd_atom = (uint32_t)c->max_rd_atom, .addr = (uint64_t)(uintptr_t)c->buf}, peer;
    memcpy(me.gid, c->gid.raw, 16);
    xsend(fd, &me, sizeof(me));
    if (xrecv(fd, &peer, sizeof(peer), 10000)) die("responder: no peer info");
    c->peer = peer;
    recv_plan(fd);
    fill_resp(c, ph.seed_r2, ph.seed_r);
    bringup(c, &peer, ph.psn0, 0, 0); /* expect requester's first request at psn0 */
    xsend(fd, "R", 1);

    for (;;) {
        char cmd;
        if (xrecv(fd, &cmd, 1, o.life_s * 1000)) { printf("EV what=resp_ctrl_closed t=%.0f\n", now_us()); break; }
        if (cmd == 'E') { /* force this QP to ERR (resp_err) */
            int rc = qp_to(c, 0);
            struct qpc_snap s = query_qp(c);
            printf("EV what=resp_2err rc=%d state=%d next_rcv_psn=0x%x t=%.0f\n", rc, s.state, s.next_rcv_psn, now_us());
            char ok = rc == 0 ? 'y' : 'n';
            xsend(fd, &ok, 1);
        } else if (cmd == 'Q' || cmd == 'V' || cmd == 'X') {
            struct qpc_snap s = query_qp(c);
            struct rep rp = {0};
            rp.state = s.state;
            rp.next_rcv_psn = s.next_rcv_psn;
            rp.rmsn = s.rmsn;
            rp.hw_rq = s.hw_rq;
            rp.sw_rq = s.sw_rq;
            rp.query_us = s.query_us;
            if (cmd != 'Q') {
                struct verify v = verify_all(c);
                rp.mem_prefix = v.mem_prefix;
                rp.mem_gap = v.mem_gap;
                rp.landed = v.landed_writes;
                rp.notlanded = v.notlanded_writes;
                rp.corrupt = v.corrupt_writes;
                rp.fadd_zero = v.fadd_zero;
                rp.fadd_one = v.fadd_one;
                rp.fadd_multi = v.fadd_multi;
                rp.reads = v.reads;
            }
            xsend(fd, &rp, sizeof(rp));
            if (cmd == 'X') break;
        } else if (cmd == 'B') { /* Mode B commit: reset + re-bringup at a new expected PSN */
            uint32_t newpsn;
            if (xrecv(fd, &newpsn, 4, 10000)) die("responder: no B psn");
            qp_to(c, 1); /* 2RST (from ERR or RTS) */
            bringup(c, &c->peer, newpsn, 0, 0);
            char ok = 'y';
            xsend(fd, &ok, 1);
            printf("EV what=resp_rebringup newpsn=0x%x t=%.0f\n", newpsn, now_us());
        } else {
            char q = '?';
            xsend(fd, &q, 1);
        }
    }
    close(fd);
    return 0;
}

/* ------------------------------------------------------------------------------------ */
/* requester helpers                                                                    */
/* ------------------------------------------------------------------------------------ */

/* Lay out requests idx[0..cnt) at consecutive physical WQEBB slots starting at lidx_base,
 * PSNs starting at psn_base. idxfield_from_lidx: use the physical lidx as the ctrl index field
 * (normal); otherwise use idx_override + position. Returns final pi (physical WQEBB count). */
static uint64_t post_pass(struct ctx *c, const int *idx, int cnt, uint32_t psn_base, uint64_t lidx_base,
                          int64_t idx_override) {
    uint64_t lidx = lidx_base;
    uint32_t psn = psn_base;
    for (int i = 0; i < cnt; i++) {
        struct req r = plan[idx[i]];
        r.lidx = lidx;
        r.psn = psn;
        uint64_t idxfield = idx_override < 0 ? (lidx & 0xffff) : (uint64_t)(idx_override + i);
        build_wqe(c, &r, idxfield);
        lidx += r.nwqebb;
        psn = (uint32_t)((psn + r.npkts) & PSN_MASK);
    }
    return lidx;
}

/* verify the requester's READ results: for each read in idx[0..cnt), the local dst must equal
 * the responder's read pattern at that offset */
static int verify_reads(struct ctx *c, const int *idx, int cnt, uint64_t seed_r) {
    int bad = 0;
    for (int i = 0; i < cnt; i++) {
        struct req *r = &plan[idx[i]];
        if (r->op != OP_READ) continue;
        uint64_t dst = R_BASE + (r->lidx * 4096) % (R_END - R_BASE); /* NB: lidx from last pass */
        for (uint64_t off = 0; off + 8 <= r->bytes; off += 8) {
            uint64_t v;
            memcpy(&v, c->buf + dst + off, 8);
            if (v != pat(seed_r, r->roff + off)) { bad++; break; }
        }
    }
    return bad;
}

static const char *classify(uint8_t syn) {
    switch (syn) {
        case 0xf5: return "WR_FLUSH_f5";
        case 0xf9: return "WR_FLUSH_f9";
        case 0x81: return "RETRY_EXC";
        case 0x88: return "REM_ACCESS";
        case 0x8a: return "REM_INV_REQ";
        default: return "other";
    }
}

static struct rep ask_rep(int fd, char cmd) {
    xsend(fd, &cmd, 1);
    struct rep rp;
    if (xrecv(fd, &rp, sizeof(rp), 8000)) die("no rep for '%c'", cmd);
    return rp;
}

/* ------------------------------------------------------------------------------------ */
/* requester main flow                                                                  */
/* ------------------------------------------------------------------------------------ */

static int all_idx[MAXR];

static int run_requester(struct ctx *c) {
    int fd = ctrl_connect(o.peer, o.port);
    struct peer_info me = {.qpn = c->qpn, .rkey = c->mr->rkey, .mtu = c->pattr.active_mtu,
                           .max_rd_atom = (uint32_t)c->max_rd_atom, .addr = (uint64_t)(uintptr_t)c->buf}, peer;
    memcpy(me.gid, c->gid.raw, 16);
    if (xrecv(fd, &peer, sizeof(peer), 10000)) die("requester: no peer info");
    xsend(fd, &me, sizeof(me));
    c->peer = peer;

    uint32_t mtu_bytes = 256u << (c->pattr.active_mtu - 1); /* IBV_MTU enum -> bytes (5=>4096) */
    uint32_t psn0 = 0x000100u + (uint32_t)(o.seed & 0xff0u);
    fill_write_src(c, o.seed ^ 0x5717ull);
    gen_plan(mtu_bytes, psn0);
    send_plan(fd);
    char r;
    if (xrecv(fd, &r, 1, 10000)) die("requester: responder not ready");

    int N = (int)ph.n;
    for (int i = 0; i < N; i++) all_idx[i] = i;
    int num_fadd = 0, num_write = 0, num_read = 0;
    uint64_t total_pkts = 0;
    for (int i = 0; i < N; i++) {
        if (plan[i].op == OP_FADD) num_fadd++;
        else if (plan[i].op == OP_READ) num_read++;
        else num_write++;
        total_pkts += plan[i].npkts;
    }

    bringup(c, &peer, 0, psn0, 0);

    /* ---- wqeidx (Q4): post 4 writes whose ctrl index field != physical WQEBB slot ---- */
    if (!strcmp(o.scen, "wqeidx")) {
        int idx4[4] = {0, 1, 2, 3};
        int nw = 0, wi[4];
        for (int i = 0; i < N && nw < 4; i++) if (plan[i].op == OP_WRITE) wi[nw++] = i;
        if (nw < 4) die("need 4 writes in the plan for wqeidx");
        (void)idx4;
        int64_t override = 1000; /* ctrl index field = 1000,1001,... physical slot = 0,1,... */
        uint64_t wpi = post_pass(c, wi, 4, psn0, 0, override);
        ring_db(c, wpi);
        struct cqe_view we = {0};
        int wrc = poll_to(c, 4, 4000, &we);
        /* read the CQE wqe_counter of the 4 completions from the ring */
        printf("EV what=wqeidx override=%ld phys_lidx=0..3 poll_rc=%d ", (long)override, wrc);
        for (uint32_t s = 0; s < 4; s++) {
            struct cqe_view cv = read_cqe(c, s);
            printf("cqe%u:op=0x%x wqe_counter=%u; ", s, cv.op, cv.wqe);
        }
        printf("\n");
        struct rep vv = ask_rep(fd, 'V');
        printf("SUMMARY scen=wqeidx poll_rc=%d landed=%d (index-field vs NIC-counter; see wqe_counter)\n", wrc,
               vv.landed);
        char x = 'X';
        struct rep fx = ask_rep(fd, x);
        (void)fx;
        close(fd);
        return 0;
    }

    /* ---- first burst ---- */
    uint64_t pi = post_pass(c, all_idx, N, psn0, 0, -1);
    double t_ring = now_us();
    ring_db(c, pi);

    int is_reqerr = !strcmp(o.scen, "req_err");
    int is_resperr = !strcmp(o.scen, "resp_err");
    int is_dup = !strcmp(o.scen, "dup");

    /* trigger the fault */
    int d = o.delay_max_us ? (int)(rnd() % (unsigned)o.delay_max_us) : 0;
    if (is_resperr) {
        usleep((useconds_t)d);
        char cmd = 'E', ack;
        xsend(fd, &cmd, 1);
        if (xrecv(fd, &ack, 1, 8000)) die("resp did not ack E");
    } else if (is_reqerr) {
        usleep((useconds_t)d);
        qp_to(c, 0); /* local 2ERR */
    }

    /* poll the first burst */
    struct cqe_view err = {0};
    int rc = poll_to(c, (uint64_t)N, is_dup ? 8000 : 6000, &err);
    uint64_t completed1 = c->cq_ci;
    struct qpc_snap myqp = query_qp(c);
    printf("EV what=burst1 scen=%s N=%d total_pkts=%llu completed=%llu poll_rc=%d err=%s(0x%02x) "
           "my_state=%d my_nsp=0x%x delay_us=%d t_since_ring=%.0f\n",
           o.scen, N, (unsigned long long)total_pkts, (unsigned long long)completed1, rc,
           rc == 1 ? classify(err.syndrome) : "-", err.syndrome, myqp.state, myqp.next_send_psn, d,
           now_us() - t_ring);

    /* ---- Q1: responder PSN vs ground truth ---- */
    struct rep q = ask_rep(fd, 'Q');
    struct rep v = ask_rep(fd, 'V');
    int prefix_from_psn = executed_prefix_from_psn(q.next_rcv_psn, psn0);
    int q1_match = (prefix_from_psn == v.mem_prefix);
    printf("EV what=Q1 resp_state=%d next_rcv_psn=0x%x rmsn=%u query_us=%.1f prefix_from_psn=%d "
           "mem_prefix=%d mem_gap=%d landed=%d notlanded=%d corrupt=%d fadd0=%d fadd1=%d faddM=%d reads=%d "
           "Q1_MATCH=%d\n",
           q.state, q.next_rcv_psn, q.rmsn, q.query_us, prefix_from_psn, v.mem_prefix, v.mem_gap,
           v.landed, v.notlanded, v.corrupt, v.fadd_zero, v.fadd_one, v.fadd_multi, v.reads, q1_match);

    /* ---- dup (Q3): rewind the requester alone into already-executed requests ---- */
    if (is_dup) {
        if (rc != 0) die("dup needs a clean first burst (rc=%d)", rc);
        int depth = o.dup_depth;
        if (depth > N) depth = N;
        int rewind = N - depth;
        uint32_t rewind_psn = (uint32_t)((psn0 + plan[rewind].cum) & PSN_MASK);
        /* count how many of the replayed (duplicate) requests are fadds - those risk double-add */
        int dup_fadd = 0;
        for (int i = rewind; i < N; i++) if (plan[i].op == OP_FADD) dup_fadd++;
        qp_to(c, 1);                              /* reset the requester only */
        bringup(c, &peer, 0, rewind_psn, 0);      /* responder stays RTS at psn0+total_pkts */
        uint64_t cq_before = c->cq_ci;            /* CQ producer continues past the clean burst */
        uint64_t dpi = post_pass(c, all_idx + rewind, depth, rewind_psn, 0, -1);
        ring_db(c, dpi);
        struct cqe_view derr = {0};
        int drc = poll_to(c, cq_before + (uint64_t)depth, 6000, &derr);
        struct qpc_snap dqp = query_qp(c);
        struct rep fx = ask_rep(fd, 'X');
        printf("EV what=dup depth=%d dup_fadd=%d rewind_psn=0x%x poll_rc=%d derr=%s(0x%02x) my_state=%d "
               "final_fadd1=%d fadd_multi=%d landed=%d/%d corrupt=%d\n",
               depth, dup_fadd, rewind_psn, drc, drc == 1 ? classify(derr.syndrome) : "-", derr.syndrome,
               dqp.state, fx.fadd_one, fx.fadd_multi, fx.landed, num_write, fx.corrupt);
        printf("SUMMARY scen=dup depth=%d dup_fadd=%d poll_rc=%d duperr=0x%02x my_state=%d fadd_multi=%d "
               "corrupt=%d (fadd_multi>0 => atomic re-executed on replay; poll_rc=1 => responder NAKed the "
               "duplicate)\n",
               depth, dup_fadd, drc, derr.syndrome, dqp.state, fx.fadd_multi, fx.corrupt);
        close(fd);
        return 0;
    }

    if (!o.recover) {
        char x = 'X';
        struct rep fx = ask_rep(fd, x);
        (void)fx;
        printf("SUMMARY scen=%s recover=0 Q1_MATCH=%d prefix_from_psn=%d mem_prefix=%d fadd_multi=%d corrupt=%d\n",
               o.scen, q1_match, prefix_from_psn, v.mem_prefix, v.fadd_multi, v.corrupt);
        close(fd);
        return 0;
    }

    /* ---- recovery ---- */
    double t_rec0 = now_us();
    /* drain the requester CQ: consume every flush CQE of the failed burst before the SQ/CQ is
     * reused, so the replay poll cannot misread a stale completion (the design's drain step). */
    int drain_to = 0;
    { int td = 0; int de = drain_cq(c, (uint64_t)N, 2000, &td);
      drain_to = (int)c->cq_ci;
      printf("EV what=drain to=%d target=%d errs=%d timed_out=%d\n", drain_to, N, de, td); }
    int first_unexec = prefix_from_psn; /* the transparent path: derived from the responder PSN */
    int cnt = N - first_unexec;
    uint32_t replay_psn;
    if (is_reqerr) {
        /* Mode A: responder untouched. Replay WHOLE requests from the first not-fully-executed
         * one, at their ORIGINAL PSN boundary. If the responder had advanced next_rcv_psn into a
         * partially-received multi-packet WRITE, the first replayed packets are duplicates (PSN <
         * next_rcv_psn) that the responder absorbs, and the message completes idempotently. */
        replay_psn = first_unexec < N ? plan[first_unexec].psn : q.next_rcv_psn;
        qp_to(c, 1); /* reset only the requester */
        bringup(c, &peer, 0, replay_psn, 0);
    } else {
        /* Mode B: reset both, fresh PSN */
        replay_psn = 0x00d000u + (uint32_t)(rnd() & 0xfffu);
        qp_to(c, 1);
        xsend(fd, "B", 1);
        xsend(fd, &replay_psn, 4);
        char ack;
        if (xrecv(fd, &ack, 1, 8000)) die("resp did not ack B");
        bringup(c, &peer, 0, replay_psn, 0);
    }
    uint64_t cq_before_replay = c->cq_ci; /* CQ producer continues; replay CQEs land after the drain */
    uint64_t rpi = post_pass(c, all_idx + first_unexec, cnt, replay_psn, 0, -1);
    ring_db(c, rpi);
    struct cqe_view rerr = {0};
    int rrc = cnt > 0 ? poll_to(c, cq_before_replay + (uint64_t)cnt, 6000, &rerr) : 0;
    /* re-read the last-pass lidx for read verification */
    int rbad = verify_reads(c, all_idx + first_unexec, cnt, ph.seed_r);
    double t_rec = now_us() - t_rec0;

    struct rep fx = ask_rep(fd, 'X');
    int ok = (rrc == 0) && (fx.corrupt == 0) && (fx.notlanded == 0) && (fx.fadd_multi == 0) &&
             (fx.fadd_zero == 0) && (fx.landed == num_write) && (fx.fadd_one == num_fadd) && (rbad == 0);
    printf("EV what=recovered mode=%s first_unexec=%d replayed=%d replay_psn=0x%x poll_rc=%d rerr=%s "
           "final: state=%d landed=%d/%d fadd1=%d/%d faddM=%d notlanded=%d corrupt=%d read_bad=%d t_rec_us=%.0f\n",
           is_reqerr ? "A" : "B", first_unexec, cnt, replay_psn, rrc,
           rrc == 1 ? classify(rerr.syndrome) : "-", fx.state, fx.landed, num_write, fx.fadd_one, num_fadd,
           fx.fadd_multi, fx.notlanded, fx.corrupt, rbad, t_rec);
    printf("SUMMARY scen=%s recover=1 mode=%s Q1_MATCH=%d prefix_from_psn=%d mem_prefix=%d "
           "EXACTLY_ONCE=%d replayed=%d fadd_multi=%d corrupt=%d notlanded=%d read_bad=%d t_rec_us=%.0f\n",
           o.scen, is_reqerr ? "A" : "B", q1_match, prefix_from_psn, v.mem_prefix, ok, cnt, fx.fadd_multi,
           fx.corrupt, fx.notlanded, rbad, t_rec);
    close(fd);
    return 0;
}

/* ------------------------------------------------------------------------------------ */

static void usage(void) {
    fprintf(stderr,
            "usage: tr_probe -m req|tgt -d <dev> -g <gid_idx> -p <port> [-s <target_ip>]\n"
            "  -S resp_err|req_err|dup|wqeidx   -k <num_reqs=256>  --recover <0|1>\n"
            "  --delay-max-us <2000>  --dup-depth <8>  --seed <n>  --timeout <14> --retry <7>\n"
            "  --life-s <90>  --trial <n>\n");
    exit(2);
}

int main(int argc, char **argv) {
    clock_gettime(CLOCK_MONOTONIC, &t_start);
    setvbuf(stdout, NULL, _IOLBF, 0);
    o = (struct opts){.dev = NULL, .peer = NULL, .scen = "resp_err", .port = 18744, .gid_idx = -1, .ib_port = 1,
                      .ack_timeout = 14, .retry_cnt = 7, .life_s = 90, .k = 256, .delay_max_us = 2000,
                      .dup_depth = 8, .recover = 1, .seed = 1, .reads = -1};
    for (int i = 1; i < argc; i++) {
        const char *a = argv[i], *val = i + 1 < argc ? argv[i + 1] : NULL;
#define OPT(s) (!strcmp(a, s) && val && ++i)
        if (OPT("-m")) o.requester = !strcmp(val, "req");
        else if (OPT("-d")) o.dev = val;
        else if (OPT("-g")) o.gid_idx = atoi(val);
        else if (OPT("-p")) o.port = atoi(val);
        else if (OPT("-s")) o.peer = val;
        else if (OPT("-S")) o.scen = val;
        else if (OPT("-k")) o.k = atoi(val);
        else if (OPT("--recover")) o.recover = atoi(val);
        else if (OPT("--delay-max-us")) o.delay_max_us = atoi(val);
        else if (OPT("--dup-depth")) o.dup_depth = atoi(val);
        else if (OPT("--reads")) o.reads = atoi(val);
        else if (OPT("--seed")) o.seed = strtoull(val, NULL, 0);
        else if (OPT("--timeout")) o.ack_timeout = atoi(val);
        else if (OPT("--retry")) o.retry_cnt = atoi(val);
        else if (OPT("--life-s")) o.life_s = atoi(val);
        else if (OPT("--trial")) o.trial = atoi(val);
        else usage();
#undef OPT
    }
    if (o.reads < 0) o.reads = !strcmp(o.scen, "dup") ? 1 : 0;
    if (!o.dev || o.gid_idx < 0 || (o.requester && !o.peer)) usage();
    alarm((unsigned)(o.life_s + 40));
    struct ctx *c = calloc(1, sizeof(*c));
    printf("EV what=start role=%s dev=%s scen=%s k=%d recover=%d seed=%llu pid=%d\n",
           o.requester ? "req" : "tgt", o.dev, o.scen, o.k, o.recover, o.seed, getpid());
    setup(c);
    return o.requester ? run_requester(c) : run_responder(c);
}
