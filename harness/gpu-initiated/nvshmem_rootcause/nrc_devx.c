/*
 * nrc_devx.c - CPU-only reproduction of the NVSHMEM IBGDA "no error CQE" problem.
 *
 * Creates one CQ and one RC QP through mlx5 DEVX, with every context field taken from a
 * named preset: "nvshmem" = the fields and values NVSHMEM 7bb2e99c's IBGDA transport sets,
 * "doca" = the fields and values NCCL 2.32.3 GIN GDAKI (bundled DOCA GPUNetIO) sets.
 * Every field on which the two presets differ can be overridden on its own with
 * "--set key=value", so the difference that matters can be bisected. Queues and doorbell
 * records are in host memory so the CPU can read the CQ directly. WQEs are shaped like
 * NVSHMEM's put + signal (RDMA WRITE, then ATOMIC FETCH_ADD) and the doorbell is rung the
 * way each stack's CPU proxy rings it. See PRESETS.md for the field-by-field table with
 * source references.
 *
 * One binary, two roles (one QP pair per process pair, one fault per run):
 *   target    (sunny): creates its QP with the same preset, registers a buffer, waits for
 *                      commands on a TCP control socket (management network).
 *   requester (rain) : connects, runs a short baseline (put+signal, wait for the CQE),
 *                      injects one fault, then observes for --observe-ms: spins over the
 *                      whole CQ buffer (logs every CQE write), and every --sample-ms issues
 *                      QUERY_QP / QUERY_CQ and reads the port counters.
 *
 * Faults: none | f1 (N big puts outstanding, then local 2ERR) | f1post (local 2ERR with
 *         nothing outstanding, then post) | f2b (invalid rkey) | f3 (target moves its QP
 *         to ERR, then post).
 * dbrk test (added 2026-09-25, requester only; the target path is unchanged):
 *         kerr (target QP to ERR, then a batch of --kn signaled WRITEs; local 2ERR after
 *         --k2err-ms, or RETRY_EXC when it is < 0) | knak (batch WRITE --kbad has a bad rkey).
 *         The UAR is rung with the true pi, the SQ doorbell-record word gets pi_before + --kdbr
 *         (valid signaled NOPs fill any slots above pi). --klate-ms/--klate-uar correct the
 *         record (and re-ring) later. Use a ring CQ (--set cq_cc=0) to see every CQE.
 *
 * Output: "EV ..." event lines, a per-sample timeline CSV (-T), and one "SUMMARY ..." line.
 * Every wait is bounded; the target exits on its own after --life-s seconds.
 */
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <endian.h>
#include <errno.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <signal.h>
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

#include "nrc_prm.h"

/* ------------------------------------------------------------------------------------ */
/* presets                                                                              */
/* ------------------------------------------------------------------------------------ */

struct preset {
    /* CQ */
    int cq_cc;            /* cqc.cc (collapsed)                                 */
    int cq_oi;            /* cqc.oi (overrun ignore)                            */
    int cq_log_size;      /* cqc.log_cq_size                                    */
    int cq_log_page_size; /* cqc.log_page_size                                  */
    int cq_init;          /* 0: memset 0xff (NVSHMEM), 1: op_own=0xf1 per CQE (DOCA) */
    int cq_ci_update;     /* 1: write the consumer index to the CQ DBR after a poll */
    /* QP create */
    int log_sq_size;      /* qpc.log_sq_size (WQEBBs)                           */
    int rq_srq;           /* 1: rq_type=SRQ + verbs SRQ + verbs recv CQ (NVSHMEM); 0: zero-size RQ */
    int send_dbr_mode;    /* qpc.send_dbr_mode                                  */
    int cd_master;        /* qpc.cd_master                                      */
    int user_index;       /* qpc.user_index                                     */
    int uar_type;         /* 0: NC, 1: BF, 2: NC_DEDICATED                      */
    /* RST2INIT */
    int r2i_rae;          /* rae + atomic_mode in RST2INIT                      */
    int atomic_mode;      /* qpc.atomic_mode value                              */
    int counter_set_id;   /* qpc.counter_set_id (overridden by --qcounter)      */
    /* INIT2RTR */
    int rtr_rwe_rae;      /* rwe, rae + atomic_mode again in INIT2RTR (DOCA)    */
    int rtr_opt_mask;     /* init2rtr opt_param_mask                            */
    int udp_sport;        /* -1: random in [0xc000,0xffff] (DOCA), else value   */
    int eth_prio_set;     /* explicitly set eth_prio = 0 (NVSHMEM)              */
    int log_msg_max;
    int min_rnr_nak;
    /* RTR2RTS */
    int rts_rwe;          /* rwe in RTR2RTS qpc (DOCA)                          */
    int rnr_retry;
    int log_ack_req_freq;
    /* WQEs */
    int write_ce;         /* fm_ce_se of the RDMA WRITE (0 NVSHMEM, 8 DOCA)     */
    int atomic_ce;        /* fm_ce_se of the signal atomic                      */
    /* doorbell, as the CPU proxy rings it */
    int dbr_word;         /* which 32-bit word of the QP DBR gets the SQ producer index: 0 (NVSHMEM proxy) or 1 (MLX5_SND_DBR) */
    int db_style;         /* 0: DBR, fence, UAR (NVSHMEM); 1: UAR, DBR, fence, UAR (DOCA full-assisted) */
};

static const struct preset preset_nvshmem = {
    .cq_cc = 1, .cq_oi = 1, .cq_log_size = 10, .cq_log_page_size = 4, .cq_init = 0, .cq_ci_update = 0,
    .log_sq_size = 10, .rq_srq = 1, .send_dbr_mode = 0, .cd_master = 0, .user_index = 1, .uar_type = 0,
    .r2i_rae = 1, .atomic_mode = 3, .counter_set_id = 0,
    .rtr_rwe_rae = 0, .rtr_opt_mask = 0, .udp_sport = 0xc000, .eth_prio_set = 1, .log_msg_max = 30,
    .min_rnr_nak = 12,
    .rts_rwe = 0, .rnr_retry = 7, .log_ack_req_freq = 0,
    .write_ce = 0, .atomic_ce = 8,
    .dbr_word = 0, .db_style = 0,
};

static const struct preset preset_doca = {
    .cq_cc = 0, .cq_oi = 1, .cq_log_size = 7, .cq_log_page_size = 0, .cq_init = 1, .cq_ci_update = 0,
    .log_sq_size = 7, .rq_srq = 0, .send_dbr_mode = 0, .cd_master = 0, .user_index = 0, .uar_type = 0,
    .r2i_rae = 0, .atomic_mode = 1, .counter_set_id = 0,
    .rtr_rwe_rae = 1, .rtr_opt_mask = 0x4, .udp_sport = -1, .eth_prio_set = 0, .log_msg_max = 30,
    .min_rnr_nak = 12,
    .rts_rwe = 1, .rnr_retry = 7, .log_ack_req_freq = 0,
    .write_ce = 8, .atomic_ce = 8,
    .dbr_word = 1, .db_style = 1,
};

#define PF(f) { #f, offsetof(struct preset, f) }
static const struct { const char *name; size_t off; } preset_fields[] = {
    PF(cq_cc), PF(cq_oi), PF(cq_log_size), PF(cq_log_page_size), PF(cq_init), PF(cq_ci_update),
    PF(log_sq_size), PF(rq_srq), PF(send_dbr_mode), PF(cd_master), PF(user_index), PF(uar_type),
    PF(r2i_rae), PF(atomic_mode), PF(counter_set_id),
    PF(rtr_rwe_rae), PF(rtr_opt_mask), PF(udp_sport), PF(eth_prio_set), PF(log_msg_max), PF(min_rnr_nak),
    PF(rts_rwe), PF(rnr_retry), PF(log_ack_req_freq),
    PF(write_ce), PF(atomic_ce), PF(dbr_word), PF(db_style),
};
#define N_PF (sizeof(preset_fields) / sizeof(preset_fields[0]))

static int *pfield(struct preset *p, size_t i) { return (int *)((char *)p + preset_fields[i].off); }

/* ------------------------------------------------------------------------------------ */
/* options and state                                                                    */
/* ------------------------------------------------------------------------------------ */

struct opts {
    int requester;
    const char *dev, *peer, *preset_name, *fault, *timeline, *sets;
    int port, gid_idx, ib_port;
    int ack_timeout, retry_cnt;
    int observe_ms, sample_ms, life_s;
    int baseline;         /* put+signal pairs before the fault           */
    unsigned put_bytes;   /* baseline / f2b / f3 put size                 */
    unsigned f1_bytes;    /* f1 put size                                  */
    int f1_n;             /* f1: number of put+signal pairs outstanding   */
    int f1_delay_us;      /* f1: delay between doorbell and 2ERR          */
    int f2b_all;          /* f2b: signal also carries the bad rkey        */
    int qcounter;         /* allocate a q counter and attach it           */
    /* ---- dbrk test (2026-09-25), faults kerr / knak; see README "Scope and mechanism checks" ---- */
    int kn;               /* WQEs in the batch: single signaled RDMA WRITEs, 1 WQEBB each      */
    int kdbr;             /* SQ doorbell-record value = pi_before + kdbr (KDBR_PI: = pi, correct) */
    int kbad;             /* knak: batch index of the WRITE that carries the bad rkey         */
    int k2err_ms;         /* kerr: local 2ERR this long after the ring (-1: none, RETRY_EXC)  */
    int klate_ms;         /* write the SQ DBR = pi this long into the observation (-1: never) */
    int klate_uar;        /* ... and ring the UAR with pi right after that write              */
    unsigned kbytes;      /* size of each WRITE of the batch                                  */
};
#define KDBR_PI (-100000)

struct peer_info {
    uint32_t qpn;
    uint8_t gid[16];
    uint64_t addr;
    uint32_t rkey;
    uint32_t pad;
} __attribute__((packed));

struct ctx {
    struct preset p;
    struct ibv_context *ctx;
    struct ibv_pd *pd;
    uint32_t pdn;
    struct ibv_port_attr pattr;
    union ibv_gid gid;
    int max_rd_atom;
    /* data buffers */
    uint8_t *buf;
    size_t buf_len;
    struct ibv_mr *mr;
    uint64_t *ibuf; /* atomic result */
    struct ibv_mr *imr;
    /* CQ */
    void *cq_buf, *cq_dbr;
    size_t cq_buf_len;
    struct mlx5dv_devx_umem *cq_umem, *cq_dbr_umem;
    struct mlx5dv_devx_uar *cq_uar;
    struct mlx5dv_devx_obj *cq;
    uint32_t cqn, ncqe;
    /* QP */
    void *sq_buf, *qp_dbr;
    size_t sq_buf_len;
    struct mlx5dv_devx_umem *sq_umem, *qp_dbr_umem;
    struct mlx5dv_devx_uar *qp_uar;
    struct mlx5dv_devx_obj *qp;
    uint32_t qpn, nwqebb;
    struct ibv_srq *srq;
    struct ibv_cq *rcq;
    struct ibv_ah *ah;
    struct mlx5dv_devx_obj *qctr;
    int qctr_id;
    /* posting */
    uint64_t pi;
    uint64_t cq_ci; /* ring CQ consumer (baseline polling only) */
};

static struct opts o;
static struct timespec t_start;

static double now_ms(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (t.tv_sec - t_start.tv_sec) * 1e3 + (t.tv_nsec - t_start.tv_nsec) / 1e6;
}

static void die(const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    fprintf(stdout, "FATAL ");
    vfprintf(stdout, fmt, ap);
    fprintf(stdout, "\n");
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

/* ------------------------------------------------------------------------------------ */
/* control socket                                                                       */
/* ------------------------------------------------------------------------------------ */

static void xsend(int fd, const void *b, size_t n) {
    const char *c = b;
    while (n) {
        ssize_t r = send(fd, c, n, MSG_NOSIGNAL);
        if (r <= 0) die("ctrl send: %s", strerror(errno));
        c += r;
        n -= r;
    }
}

/* receive exactly n bytes within tmo_ms; returns 0 or -1 on timeout/EOF */
static int xrecv(int fd, void *b, size_t n, int tmo_ms) {
    char *c = b;
    double t_end = now_ms() + tmo_ms;
    while (n) {
        int left = (int)(t_end - now_ms());
        if (left <= 0) return -1;
        struct pollfd pf = {.fd = fd, .events = POLLIN};
        int r = poll(&pf, 1, left);
        if (r <= 0) continue;
        ssize_t k = recv(fd, c, n, 0);
        if (k <= 0) return -1;
        c += k;
        n -= k;
    }
    return 0;
}

static int ctrl_connect(const char *host, int port) {
    for (int i = 0; i < 100; i++) { /* the target may still be starting: 10 s */
        int fd = socket(AF_INET, SOCK_STREAM, 0);
        struct sockaddr_in a = {.sin_family = AF_INET, .sin_port = htons(port)};
        inet_pton(AF_INET, host, &a.sin_addr);
        if (connect(fd, (struct sockaddr *)&a, sizeof(a)) == 0) {
            int one = 1;
            setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));
            return fd;
        }
        close(fd);
        usleep(100000);
    }
    die("ctrl connect %s:%d failed", host, port);
    return -1;
}

static int ctrl_listen_accept(int port, int tmo_ms) {
    int lfd = socket(AF_INET, SOCK_STREAM, 0), one = 1;
    setsockopt(lfd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
    struct sockaddr_in a = {.sin_family = AF_INET, .sin_port = htons(port), .sin_addr.s_addr = INADDR_ANY};
    if (bind(lfd, (struct sockaddr *)&a, sizeof(a)) || listen(lfd, 1)) die("ctrl bind/listen %d: %s", port, strerror(errno));
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

static uint32_t devx_status(const void *out) { return DEVX_GET(modify_qp_out, out, status); }
static uint32_t devx_syndrome(const void *out) { return DEVX_GET(modify_qp_out, out, syndrome); }

static struct mlx5dv_devx_uar *alloc_uar(struct ibv_context *c, int type) {
    uint32_t t = type == 1 ? MLX5DV_UAR_ALLOC_TYPE_BF : type == 2 ? (1U << 31) : MLX5DV_UAR_ALLOC_TYPE_NC;
    struct mlx5dv_devx_uar *u = mlx5dv_devx_alloc_uar(c, t);
    if (!u) die("mlx5dv_devx_alloc_uar type %d: %s", type, strerror(errno));
    return u;
}

static void create_cq(struct ctx *c) {
    struct preset *p = &c->p;
    c->ncqe = 1u << p->cq_log_size;
    c->cq_buf_len = (size_t)c->ncqe * 64;
    if (c->cq_buf_len < 4096) c->cq_buf_len = 4096;
    c->cq_buf = xalign(65536, c->cq_buf_len);
    if (p->cq_init == 0) {
        memset(c->cq_buf, 0xff, c->cq_buf_len); /* ibgda.cpp:1447 */
    } else {
        for (uint32_t i = 0; i < c->ncqe; i++) ((uint8_t *)c->cq_buf)[i * 64 + 63] = 0xf1; /* DOCA mlx5_init_cqes */
    }
    c->cq_dbr = xalign(65536, 4096);
    c->cq_umem = mlx5dv_devx_umem_reg(c->ctx, c->cq_buf, c->cq_buf_len, IBV_ACCESS_LOCAL_WRITE);
    c->cq_dbr_umem = mlx5dv_devx_umem_reg(c->ctx, c->cq_dbr, 4096, IBV_ACCESS_LOCAL_WRITE);
    if (!c->cq_umem || !c->cq_dbr_umem) die("CQ umem reg: %s", strerror(errno));
    c->cq_uar = alloc_uar(c->ctx, 0);
    uint32_t eqn = 0;
    if (mlx5dv_devx_query_eqn(c->ctx, 0, &eqn)) die("query_eqn");

    uint32_t in[DEVX_ST_SZ_DW(create_cq_in)] = {0}, out[DEVX_ST_SZ_DW(create_cq_out)] = {0};
    DEVX_SET(create_cq_in, in, opcode, MLX5_CMD_OP_CREATE_CQ);
    DEVX_SET(create_cq_in, in, cq_umem_id, c->cq_umem->umem_id);
    DEVX_SET(create_cq_in, in, cq_umem_valid, 1);
    DEVX_SET64(create_cq_in, in, cq_umem_offset, 0);
    void *cqc = DEVX_ADDR_OF(create_cq_in, in, cq_context);
    DEVX_SET(cqc, cqc, dbr_umem_valid, 1);
    DEVX_SET(cqc, cqc, cqe_sz, 0); /* 64 B */
    DEVX_SET(cqc, cqc, cc, p->cq_cc);
    DEVX_SET(cqc, cqc, oi, p->cq_oi);
    DEVX_SET(cqc, cqc, dbr_umem_id, c->cq_dbr_umem->umem_id);
    DEVX_SET(cqc, cqc, log_cq_size, p->cq_log_size);
    DEVX_SET(cqc, cqc, uar_page, c->cq_uar->page_id);
    DEVX_SET(cqc, cqc, c_eqn, eqn);
    DEVX_SET(cqc, cqc, log_page_size, p->cq_log_page_size);
    DEVX_SET64(cqc, cqc, dbr_addr, 0);
    c->cq = mlx5dv_devx_obj_create(c->ctx, in, sizeof(in), out, sizeof(out));
    if (!c->cq) die("CREATE_CQ: %s status 0x%x syndrome 0x%x", strerror(errno), devx_status(out), devx_syndrome(out));
    c->cqn = DEVX_GET(create_cq_out, out, cqn);
}

/* qcounter mode 2: the per-port q counter the kernel attaches to verbs QPs (the one behind
 * /sys/class/infiniband/<dev>/ports/<p>/hw_counters). Learned from a throwaway verbs QP. */
static void port_qcounter(struct ctx *c) {
    struct ibv_cq *vcq = ibv_create_cq(c->ctx, 4, NULL, NULL, 0);
    struct ibv_qp_init_attr ia = {.send_cq = vcq, .recv_cq = vcq, .qp_type = IBV_QPT_RC,
                                  .cap = {.max_send_wr = 1, .max_recv_wr = 1, .max_send_sge = 1, .max_recv_sge = 1}};
    struct ibv_qp *vqp = vcq ? ibv_create_qp(c->pd, &ia) : NULL;
    struct ibv_qp_attr qa = {.qp_state = IBV_QPS_INIT, .port_num = o.ib_port};
    if (!vqp || ibv_modify_qp(vqp, &qa, IBV_QP_STATE | IBV_QP_PKEY_INDEX | IBV_QP_PORT | IBV_QP_ACCESS_FLAGS))
        die("verbs probe QP");
    uint32_t in[DEVX_ST_SZ_DW(query_qp_in)] = {0}, out[DEVX_ST_SZ_DW(query_qp_out)] = {0};
    DEVX_SET(query_qp_in, in, opcode, MLX5_CMD_OP_QUERY_QP);
    DEVX_SET(query_qp_in, in, qpn, vqp->qp_num);
    if (mlx5dv_devx_qp_query(vqp, in, sizeof(in), out, sizeof(out))) die("devx_qp_query verbs QP: %s", strerror(errno));
    c->qctr_id = DEVX_GET(qpc, DEVX_ADDR_OF(query_qp_out, out, qpc), counter_set_id);
    printf("EV what=port_qcounter counter_set_id=%d (from verbs QP 0x%x)\n", c->qctr_id, vqp->qp_num);
    ibv_destroy_qp(vqp);
    ibv_destroy_cq(vcq);
}

static void alloc_qcounter(struct ctx *c) {
    uint32_t in[DEVX_ST_SZ_DW(alloc_q_counter_in)] = {0}, out[DEVX_ST_SZ_DW(alloc_q_counter_out)] = {0};
    DEVX_SET(alloc_q_counter_in, in, opcode, MLX5_CMD_OP_ALLOC_Q_COUNTER);
    c->qctr = mlx5dv_devx_obj_create(c->ctx, in, sizeof(in), out, sizeof(out));
    if (!c->qctr) {
        printf("EV what=qcounter_alloc_failed err=\"%s\" status=0x%x syndrome=0x%x (continuing without)\n",
               strerror(errno), devx_status(out), devx_syndrome(out));
        o.qcounter = 0;
        return;
    }
    c->qctr_id = DEVX_GET(alloc_q_counter_out, out, counter_set_id);
}

struct qctr_vals {
    uint32_t local_ack_timeout_err, req_transport_retries_exceeded, req_cqe_error, req_cqe_flush_error,
        req_remote_access_errors, req_remote_invalid_request, packet_seq_err, out_of_sequence, duplicate_request,
        implied_nak_seq_err, rnr_nak_retry_err, roce_adp_retrans, roce_adp_retrans_to;
};

static int query_qcounter(struct ctx *c, struct qctr_vals *v) {
    uint32_t in[DEVX_ST_SZ_DW(query_q_counter_in)] = {0}, out[DEVX_ST_SZ_DW(query_q_counter_out)] = {0};
    DEVX_SET(query_q_counter_in, in, opcode, MLX5_CMD_OP_QUERY_Q_COUNTER);
    DEVX_SET(query_q_counter_in, in, counter_set_id, c->qctr_id);
    if (mlx5dv_devx_obj_query(c->qctr, in, sizeof(in), out, sizeof(out)) &&
        mlx5dv_devx_general_cmd(c->ctx, in, sizeof(in), out, sizeof(out)))
        return -1;
#define QG(f) v->f = DEVX_GET(query_q_counter_out, out, f)
    QG(local_ack_timeout_err); QG(req_transport_retries_exceeded); QG(req_cqe_error); QG(req_cqe_flush_error);
    QG(req_remote_access_errors); QG(req_remote_invalid_request); QG(packet_seq_err); QG(out_of_sequence);
    QG(duplicate_request); QG(implied_nak_seq_err); QG(rnr_nak_retry_err); QG(roce_adp_retrans);
    QG(roce_adp_retrans_to);
#undef QG
    return 0;
}

static void create_qp(struct ctx *c) {
    struct preset *p = &c->p;
    c->nwqebb = 1u << p->log_sq_size;
    c->sq_buf_len = (size_t)c->nwqebb * 64;
    if (c->sq_buf_len < 4096) c->sq_buf_len = 4096;
    c->sq_buf = xalign(65536, c->sq_buf_len);
    c->qp_dbr = xalign(65536, 4096);
    c->sq_umem = mlx5dv_devx_umem_reg(c->ctx, c->sq_buf, c->sq_buf_len, IBV_ACCESS_LOCAL_WRITE);
    c->qp_dbr_umem = mlx5dv_devx_umem_reg(c->ctx, c->qp_dbr, 4096, IBV_ACCESS_LOCAL_WRITE);
    if (!c->sq_umem || !c->qp_dbr_umem) die("QP umem reg: %s", strerror(errno));
    c->qp_uar = alloc_uar(c->ctx, p->uar_type);

    uint32_t srqn = 0, rcqn = 0;
    if (p->rq_srq) { /* ibgda.cpp:2224-2258: verbs SRQ + verbs recv CQ in host memory */
        struct ibv_srq_init_attr sa = {.attr = {.max_wr = 1024, .max_sge = 1}};
        c->srq = ibv_create_srq(c->pd, &sa);
        c->rcq = ibv_create_cq(c->ctx, 1024, NULL, NULL, 0);
        if (!c->srq || !c->rcq) die("verbs SRQ/CQ");
        struct mlx5dv_obj dv = {0};
        struct mlx5dv_srq dsrq = {.comp_mask = MLX5DV_SRQ_MASK_SRQN};
        struct mlx5dv_cq dcq = {0};
        dv.srq.in = c->srq;
        dv.srq.out = &dsrq;
        dv.cq.in = c->rcq;
        dv.cq.out = &dcq;
        if (mlx5dv_init_obj(&dv, MLX5DV_OBJ_SRQ | MLX5DV_OBJ_CQ)) die("mlx5dv_init_obj srq/cq");
        srqn = dsrq.srqn;
        rcqn = dcq.cqn;
    }

    uint32_t in[DEVX_ST_SZ_DW(create_qp_in)] = {0}, out[DEVX_ST_SZ_DW(create_qp_out)] = {0};
    DEVX_SET(create_qp_in, in, opcode, MLX5_CMD_OP_CREATE_QP);
    DEVX_SET(create_qp_in, in, wq_umem_id, c->sq_umem->umem_id);
    DEVX_SET64(create_qp_in, in, wq_umem_offset, 0);
    DEVX_SET(create_qp_in, in, wq_umem_valid, 1);
    void *qpc = DEVX_ADDR_OF(create_qp_in, in, qpc);
    DEVX_SET(qpc, qpc, st, NRC_QPC_ST_RC);
    DEVX_SET(qpc, qpc, pm_state, NRC_QPC_PM_STATE_MIGRATED);
    DEVX_SET(qpc, qpc, pd, c->pdn);
    DEVX_SET(qpc, qpc, uar_page, c->qp_uar->page_id);
    DEVX_SET(qpc, qpc, cqn_snd, c->cqn);
    DEVX_SET(qpc, qpc, log_sq_size, p->log_sq_size);
    if (p->rq_srq) {
        DEVX_SET(qpc, qpc, rq_type, NRC_QPC_RQ_TYPE_SRQ);
        DEVX_SET(qpc, qpc, srqn_rmpn_xrqn, srqn);
        DEVX_SET(qpc, qpc, cqn_rcv, rcqn);
        DEVX_SET(qpc, qpc, log_rq_size, 0);
        DEVX_SET(qpc, qpc, cs_req, 0);
        DEVX_SET(qpc, qpc, cs_res, 0);
    } else {
        DEVX_SET(qpc, qpc, rq_type, NRC_QPC_RQ_TYPE_ZERO_SIZE_RQ);
    }
    DEVX_SET(qpc, qpc, send_dbr_mode, p->send_dbr_mode);
    DEVX_SET(qpc, qpc, cd_master, p->cd_master);
    DEVX_SET(qpc, qpc, dbr_umem_valid, 1);
    DEVX_SET64(qpc, qpc, dbr_addr, 0);
    DEVX_SET(qpc, qpc, dbr_umem_id, c->qp_dbr_umem->umem_id);
    DEVX_SET(qpc, qpc, user_index, p->user_index);
    DEVX_SET(qpc, qpc, page_offset, 0);
    DEVX_SET(qpc, qpc, log_page_size, 0);
    printf("EV what=uars qp_uar_type=%d qp_uar_page=%u qp_reg_addr=%p cq_uar_page=%u\n", p->uar_type,
           c->qp_uar->page_id, c->qp_uar->reg_addr, c->cq_uar->page_id);
    c->qp = mlx5dv_devx_obj_create(c->ctx, in, sizeof(in), out, sizeof(out));
    if (!c->qp) die("CREATE_QP: %s status 0x%x syndrome 0x%x", strerror(errno), devx_status(out), devx_syndrome(out));
    c->qpn = DEVX_GET(create_qp_out, out, qpn);
}

static int ilog2i(int v) { int l = 0; while ((1 << (l + 1)) <= v) l++; return l; }

static void modify(struct ctx *c, uint32_t *in, size_t inlen, const char *what) {
    uint32_t out[DEVX_ST_SZ_DW(modify_qp_out)] = {0};
    if (mlx5dv_devx_obj_modify(c->qp, in, inlen, out, sizeof(out)))
        die("%s: %s status 0x%x syndrome 0x%x", what, strerror(errno), devx_status(out), devx_syndrome(out));
}

static void connect_qp(struct ctx *c, const struct peer_info *pi) {
    struct preset *p = &c->p;
    uint32_t in[DEVX_ST_SZ_DW(modify_qp_in)];
    void *qpc = DEVX_ADDR_OF(modify_qp_in, in, qpc);

    /* RST2INIT */
    memset(in, 0, sizeof(in));
    DEVX_SET(modify_qp_in, in, opcode, MLX5_CMD_OP_RST2INIT_QP);
    DEVX_SET(modify_qp_in, in, qpn, c->qpn);
    DEVX_SET(qpc, qpc, rwe, 1);
    DEVX_SET(qpc, qpc, rre, 1);
    if (p->r2i_rae) {
        DEVX_SET(qpc, qpc, rae, 1);
        DEVX_SET(qpc, qpc, atomic_mode, p->atomic_mode);
    }
    DEVX_SET(qpc, qpc, primary_address_path.vhca_port_num, o.ib_port);
    DEVX_SET(qpc, qpc, primary_address_path.pkey_index, 0);
    DEVX_SET(qpc, qpc, pm_state, NRC_QPC_PM_STATE_MIGRATED);
    DEVX_SET(qpc, qpc, counter_set_id, o.qcounter ? c->qctr_id : p->counter_set_id);
    modify(c, in, sizeof(in), "RST2INIT");

    /* remote MAC through a verbs AH (NVSHMEM ibgda.cpp:1834-1870, DOCA resolve_remote_mac) */
    struct ibv_ah_attr ah = {.is_global = 1, .port_num = o.ib_port};
    memcpy(ah.grh.dgid.raw, pi->gid, 16);
    ah.grh.sgid_index = o.gid_idx;
    ah.grh.hop_limit = 255;
    c->ah = ibv_create_ah(c->pd, &ah);
    if (!c->ah) die("ibv_create_ah: %s", strerror(errno));
    struct mlx5dv_obj dv = {0};
    struct mlx5dv_ah dah = {0};
    dv.ah.in = c->ah;
    dv.ah.out = &dah;
    if (mlx5dv_init_obj(&dv, MLX5DV_OBJ_AH)) die("mlx5dv_init_obj ah");

    /* INIT2RTR */
    memset(in, 0, sizeof(in));
    DEVX_SET(modify_qp_in, in, opcode, MLX5_CMD_OP_INIT2RTR_QP);
    DEVX_SET(modify_qp_in, in, qpn, c->qpn);
    DEVX_SET(modify_qp_in, in, opt_param_mask, p->rtr_opt_mask);
    DEVX_SET(qpc, qpc, mtu, c->pattr.active_mtu);
    DEVX_SET(qpc, qpc, log_msg_max, p->log_msg_max);
    DEVX_SET(qpc, qpc, remote_qpn, pi->qpn);
    DEVX_SET(qpc, qpc, next_rcv_psn, 0);
    DEVX_SET(qpc, qpc, min_rnr_nak, p->min_rnr_nak);
    DEVX_SET(qpc, qpc, log_rra_max, ilog2i(c->max_rd_atom));
    memcpy(DEVX_ADDR_OF(qpc, qpc, primary_address_path.rmac_47_32), dah.av->rmac, 6);
    DEVX_SET(qpc, qpc, primary_address_path.hop_limit, 255);
    DEVX_SET(qpc, qpc, primary_address_path.src_addr_index, o.gid_idx);
    if (p->eth_prio_set) DEVX_SET(qpc, qpc, primary_address_path.eth_prio, 0);
    int sport = p->udp_sport >= 0 ? p->udp_sport : 0xc000 + (int)((unsigned)time(NULL) * 2654435761u % 0x4000u);
    DEVX_SET(qpc, qpc, primary_address_path.udp_sport, sport);
    DEVX_SET(qpc, qpc, primary_address_path.dscp, 0);
    DEVX_SET(qpc, qpc, primary_address_path.stat_rate, 0);
    DEVX_SET(qpc, qpc, primary_address_path.pkey_index, 0);
    memcpy(DEVX_ADDR_OF(qpc, qpc, primary_address_path.rgid_rip), pi->gid, 16);
    if (p->rtr_rwe_rae) {
        DEVX_SET(qpc, qpc, rwe, 1);
        DEVX_SET(qpc, qpc, rae, 1);
        DEVX_SET(qpc, qpc, atomic_mode, p->atomic_mode);
    }
    modify(c, in, sizeof(in), "INIT2RTR");

    /* RTR2RTS */
    memset(in, 0, sizeof(in));
    DEVX_SET(modify_qp_in, in, opcode, MLX5_CMD_OP_RTR2RTS_QP);
    DEVX_SET(modify_qp_in, in, qpn, c->qpn);
    DEVX_SET(qpc, qpc, log_ack_req_freq, p->log_ack_req_freq);
    DEVX_SET(qpc, qpc, log_sra_max, ilog2i(c->max_rd_atom));
    DEVX_SET(qpc, qpc, next_send_psn, 0);
    DEVX_SET(qpc, qpc, retry_count, o.retry_cnt);
    DEVX_SET(qpc, qpc, rnr_retry, p->rnr_retry);
    DEVX_SET(qpc, qpc, primary_address_path.ack_timeout, o.ack_timeout);
    if (p->rts_rwe) DEVX_SET(qpc, qpc, rwe, 1);
    modify(c, in, sizeof(in), "RTR2RTS");
    printf("EV t_ms=%.3f what=connected qpn=0x%x cqn=0x%x peer_qpn=0x%x udp_sport=0x%x ncqe=%u nwqebb=%u qctr=%d\n",
           now_ms(), c->qpn, c->cqn, pi->qpn, sport, c->ncqe, c->nwqebb, o.qcounter ? c->qctr_id : -1);
}

static int qp_2err(struct ctx *c) {
    uint32_t in[DEVX_ST_SZ_DW(qp_2err_in)] = {0}, out[DEVX_ST_SZ_DW(modify_qp_out)] = {0};
    DEVX_SET(qp_2err_in, in, opcode, MLX5_CMD_OP_2ERR_QP);
    DEVX_SET(qp_2err_in, in, qpn, c->qpn);
    return mlx5dv_devx_obj_modify(c->qp, in, sizeof(in), out, sizeof(out));
}

struct qp_snap {
    int ok, state, hw_sq, sw_sq, cur_retry, cur_rnr, last_acked_psn, next_send_psn;
};

static struct qp_snap query_qp(struct ctx *c) {
    struct qp_snap s = {0};
    uint32_t in[DEVX_ST_SZ_DW(query_qp_in)] = {0}, out[DEVX_ST_SZ_DW(query_qp_out)] = {0};
    DEVX_SET(query_qp_in, in, opcode, MLX5_CMD_OP_QUERY_QP);
    DEVX_SET(query_qp_in, in, qpn, c->qpn);
    if (mlx5dv_devx_obj_query(c->qp, in, sizeof(in), out, sizeof(out))) {
        s.ok = 0;
        s.state = -1;
        return s;
    }
    s.ok = 1;
    void *qpc = DEVX_ADDR_OF(query_qp_out, out, qpc);
    s.state = DEVX_GET(qpc, qpc, state);
    s.hw_sq = DEVX_GET(qpc, qpc, hw_sq_wqebb_counter);
    s.sw_sq = DEVX_GET(qpc, qpc, sw_sq_wqebb_counter);
    s.cur_retry = DEVX_GET(qpc, qpc, cur_retry_count);
    s.cur_rnr = DEVX_GET(qpc, qpc, cur_rnr_retry);
    s.last_acked_psn = DEVX_GET(qpc, qpc, last_acked_psn);
    s.next_send_psn = DEVX_GET(qpc, qpc, next_send_psn);
    return s;
}

struct cq_snap {
    int ok, status, pc, cc;
};

static struct cq_snap query_cq(struct ctx *c) {
    struct cq_snap s = {0};
    uint32_t in[DEVX_ST_SZ_DW(query_cq_in)] = {0}, out[DEVX_ST_SZ_DW(query_cq_out)] = {0};
    DEVX_SET(query_cq_in, in, opcode, MLX5_CMD_OP_QUERY_CQ);
    DEVX_SET(query_cq_in, in, cqn, c->cqn);
    if (mlx5dv_devx_obj_query(c->cq, in, sizeof(in), out, sizeof(out))) {
        s.status = -1;
        return s;
    }
    s.ok = 1;
    void *cqc = DEVX_ADDR_OF(query_cq_out, out, cq_context);
    s.status = DEVX_GET(cqc, cqc, status);
    s.pc = DEVX_GET(cqc, cqc, producer_counter);
    s.cc = DEVX_GET(cqc, cqc, consumer_counter);
    return s;
}

/* ------------------------------------------------------------------------------------ */
/* WQEs and doorbell                                                                    */
/* ------------------------------------------------------------------------------------ */

struct wqe_ctrl { uint32_t opmod_idx_opcode, qpn_ds; uint8_t signature, rsvd[2], fm_ce_se; uint32_t imm; };
struct wqe_raddr { uint64_t raddr; uint32_t rkey, rsvd; };
struct wqe_data { uint32_t byte_count, lkey; uint64_t addr; };
struct wqe_atomic { uint64_t swap_add, compare; };

static void *wqe_at(struct ctx *c, uint64_t idx) { return (uint8_t *)c->sq_buf + (idx & (c->nwqebb - 1)) * 64; }

static void write_rdma_write(struct ctx *c, uint64_t idx, uint64_t laddr, uint32_t lkey, uint64_t raddr, uint32_t rkey,
                             uint32_t bytes, uint8_t ce) {
    uint8_t *w = wqe_at(c, idx);
    memset(w, 0, 64);
    struct wqe_ctrl *ctl = (void *)w;
    struct wqe_raddr *ra = (void *)(w + 16);
    struct wqe_data *d = (void *)(w + 32);
    ctl->opmod_idx_opcode = htobe32(((uint32_t)(idx & 0xffff) << 8) | 0x08); /* RDMA_WRITE */
    ctl->qpn_ds = htobe32((c->qpn << 8) | 3);
    ctl->fm_ce_se = ce;
    ra->raddr = htobe64(raddr);
    ra->rkey = htobe32(rkey);
    d->byte_count = htobe32(bytes);
    d->lkey = htobe32(lkey);
    d->addr = htobe64(laddr);
}

static void write_atomic_fa(struct ctx *c, uint64_t idx, uint64_t raddr, uint32_t rkey, uint64_t add, uint8_t ce) {
    uint8_t *w = wqe_at(c, idx);
    memset(w, 0, 64);
    struct wqe_ctrl *ctl = (void *)w;
    struct wqe_raddr *ra = (void *)(w + 16);
    struct wqe_atomic *at = (void *)(w + 32);
    struct wqe_data *d = (void *)(w + 48);
    ctl->opmod_idx_opcode = htobe32(((uint32_t)(idx & 0xffff) << 8) | 0x12); /* ATOMIC_FA */
    ctl->qpn_ds = htobe32((c->qpn << 8) | 4);
    ctl->fm_ce_se = ce;
    ra->raddr = htobe64(raddr);
    ra->rkey = htobe32(rkey);
    at->swap_add = htobe64(add);
    d->byte_count = htobe32(8);
    d->lkey = htobe32(c->imr->lkey);
    d->addr = htobe64((uint64_t)(uintptr_t)c->ibuf);
}

static inline void mmio_write64(void *reg, uint64_t v) { *(volatile uint64_t *)reg = v; }

/* ring the UAR with producer index pi, the way the preset's CPU proxy does, but write dbr_val
 * (normally = pi) into the doorbell-record word. dbr_val != pi only in the dbrk test. */
static void ring_db_val(struct ctx *c, uint64_t pi, uint64_t dbr_val) {
    struct wqe_ctrl ctl = {0};
    ctl.opmod_idx_opcode = htobe32((uint32_t)(pi << 8));
    ctl.qpn_ds = htobe32(c->qpn << 8);
    uint64_t db;
    memcpy(&db, &ctl, 8);
    volatile uint32_t *dbr = (volatile uint32_t *)c->qp_dbr;
    void *reg = c->qp_uar->reg_addr;
    __sync_synchronize(); /* WQEs visible before anything else */
    if (c->p.db_style == 0) {
        /* NVSHMEM ibgda_rc_progress (ibgda.cpp:581-591) */
        dbr[c->p.dbr_word] = htobe32((uint32_t)(dbr_val & 0xffff));
        __atomic_thread_fence(__ATOMIC_RELEASE);
        mmio_write64(reg, db);
    } else {
        /* DOCA priv_cpu_proxy_progress_full_assisted (doca_gpunetio.cpp:1234-1252) */
        mmio_write64(reg, db);
        dbr[c->p.dbr_word] = htobe32((uint32_t)(dbr_val & 0xffff));
        __atomic_thread_fence(__ATOMIC_RELEASE);
        mmio_write64(reg, db);
    }
}

/* ring the doorbell for producer index pi, the way the preset's CPU proxy does */
static void ring_db(struct ctx *c, uint64_t pi) { ring_db_val(c, pi, pi); }

/* ---- dbrk test (2026-09-25) ---- */
/* a valid, signaled NOP WQE (ctrl segment only, ds 1): fills the slots between pi and a
 * doorbell-record value above pi, so the NIC never meets an unwritten WQE there */
static void write_nop(struct ctx *c, uint64_t idx, uint8_t ce) {
    uint8_t *w = wqe_at(c, idx);
    memset(w, 0, 64);
    struct wqe_ctrl *ctl = (void *)w;
    ctl->opmod_idx_opcode = htobe32(((uint32_t)(idx & 0xffff) << 8) | 0x00); /* MLX5_OPCODE_NOP */
    ctl->qpn_ds = htobe32((c->qpn << 8) | 1);
    ctl->fm_ce_se = ce;
}

/* post one put + signal pair (2 WQEs); returns the index of the signal WQE */
static uint64_t post_put_signal(struct ctx *c, const struct peer_info *pi, uint64_t roff, uint32_t bytes,
                                uint32_t rkey_put, uint32_t rkey_sig) {
    uint64_t i = c->pi;
    write_rdma_write(c, i, (uint64_t)(uintptr_t)c->buf + (roff % (c->buf_len - bytes + 1)), c->mr->lkey,
                     pi->addr + roff, rkey_put, bytes, (uint8_t)c->p.write_ce);
    write_atomic_fa(c, i + 1, pi->addr + c->buf_len - 64, rkey_sig, 1, (uint8_t)c->p.atomic_ce);
    c->pi += 2;
    return i + 1;
}

/* ------------------------------------------------------------------------------------ */
/* CQ reading                                                                           */
/* ------------------------------------------------------------------------------------ */

struct cqe_view { uint8_t op, owner, syndrome, vendor, hw_err, hw_type; uint16_t wqe; uint32_t s_wqe_opcode_qpn; };

static struct cqe_view read_cqe(struct ctx *c, uint32_t i) {
    volatile uint8_t *e = (volatile uint8_t *)c->cq_buf + (size_t)i * 64;
    struct cqe_view v;
    uint8_t op_own = e[63];
    __atomic_thread_fence(__ATOMIC_ACQUIRE);
    v.op = op_own >> 4;
    v.owner = op_own & 1;
    v.hw_err = e[52];
    v.hw_type = e[53];
    v.vendor = e[54];
    v.syndrome = e[55];
    v.s_wqe_opcode_qpn = ((uint32_t)e[56] << 24) | ((uint32_t)e[57] << 16) | ((uint32_t)e[58] << 8) | e[59];
    v.wqe = (uint16_t)((e[60] << 8) | e[61]);
    return v;
}

static int is_err_op(int op) { return op == 0xd || op == 0xe; }

/* wait for the CQE of WQE index 'want' (baseline only). 0 ok, 1 error CQE, 2 timeout */
static int wait_cqe(struct ctx *c, uint64_t want, int tmo_ms, struct cqe_view *got) {
    double t_end = now_ms() + tmo_ms;
    while (now_ms() < t_end) {
        if (c->p.cq_cc) {
            struct cqe_view v = read_cqe(c, 0);
            if (v.op != 0xf && v.wqe == (uint16_t)want) {
                *got = v;
                return is_err_op(v.op) ? 1 : 0;
            }
            if (is_err_op(v.op)) { *got = v; return 1; }
        } else {
            uint32_t slot = (uint32_t)(c->cq_ci & (c->ncqe - 1));
            struct cqe_view v = read_cqe(c, slot);
            int sw_owner = (int)((c->cq_ci >> c->p.cq_log_size) & 1);
            if (v.op != 0xf && v.owner == sw_owner) {
                c->cq_ci++;
                if (c->p.cq_ci_update) ((volatile uint32_t *)c->cq_dbr)[0] = htobe32((uint32_t)(c->cq_ci & 0xffffff));
                if (is_err_op(v.op)) { *got = v; return 1; }
                if (v.wqe == (uint16_t)want) { *got = v; return 0; }
            }
        }
    }
    return 2;
}

/* ------------------------------------------------------------------------------------ */
/* port counters                                                                        */
/* ------------------------------------------------------------------------------------ */

static long long read_ll(const char *path) {
    FILE *f = fopen(path, "r");
    long long v = -1;
    if (f) {
        if (fscanf(f, "%lld", &v) != 1) v = -1;
        fclose(f);
    }
    return v;
}

static long long port_ctr(const char *name) {
    char p[256];
    snprintf(p, sizeof(p), "/sys/class/infiniband/%s/ports/%d/counters/%s", o.dev, o.ib_port, name);
    return read_ll(p);
}

static const char *hwc_names[] = {"local_ack_timeout_err", "req_cqe_error", "req_cqe_flush_error",
                                  "req_remote_access_errors", "req_remote_invalid_request", "packet_seq_err",
                                  "out_of_sequence", "implied_nak_seq_err", "rnr_nak_retry_err", "duplicate_request"};
#define HWC_N ((int)(sizeof(hwc_names) / sizeof(hwc_names[0])))

static void read_hw(long long *v) {
    char p[256];
    for (int k = 0; k < HWC_N; k++) {
        snprintf(p, sizeof(p), "/sys/class/infiniband/%s/ports/%d/hw_counters/%s", o.dev, o.ib_port, hwc_names[k]);
        v[k] = read_ll(p);
    }
}

/* ------------------------------------------------------------------------------------ */
/* setup common to both roles                                                           */
/* ------------------------------------------------------------------------------------ */

static void setup(struct ctx *c) {
    int n = 0;
    struct ibv_device **l = ibv_get_device_list(&n), *d = NULL;
    for (int i = 0; l && i < n; i++)
        if (!strcmp(ibv_get_device_name(l[i]), o.dev)) d = l[i];
    if (!d) die("device %s not found", o.dev);
    struct mlx5dv_context_attr ca = {.flags = MLX5DV_CONTEXT_FLAGS_DEVX};
    c->ctx = mlx5dv_open_device(d, &ca);
    if (!c->ctx) die("mlx5dv_open_device DEVX: %s", strerror(errno));
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

    c->buf_len = 64u << 20;
    c->buf = xalign(4096, c->buf_len);
    for (size_t i = 0; i < c->buf_len; i += 4096) c->buf[i] = (uint8_t)(i >> 12);
    c->mr = ibv_reg_mr(c->pd, c->buf, c->buf_len,
                       IBV_ACCESS_LOCAL_WRITE | IBV_ACCESS_REMOTE_WRITE | IBV_ACCESS_REMOTE_READ | IBV_ACCESS_REMOTE_ATOMIC);
    c->ibuf = xalign(4096, 4096);
    c->imr = ibv_reg_mr(c->pd, c->ibuf, 4096, IBV_ACCESS_LOCAL_WRITE);
    if (!c->mr || !c->imr) die("reg_mr: %s", strerror(errno));
    if (o.qcounter == 1) alloc_qcounter(c);
    else if (o.qcounter == 2) port_qcounter(c);
    create_cq(c);
    create_qp(c);
}

static void print_preset(const struct preset *p, const char *name) {
    printf("PRESET name=%s", name);
    for (size_t i = 0; i < N_PF; i++) printf(" %s=%d", preset_fields[i].name, *pfield((struct preset *)p, i));
    printf("\n");
}

/* ------------------------------------------------------------------------------------ */
/* target                                                                               */
/* ------------------------------------------------------------------------------------ */

static int run_target(struct ctx *c) {
    int fd = ctrl_listen_accept(o.port, o.life_s * 1000);
    struct peer_info me = {.qpn = c->qpn, .addr = (uint64_t)(uintptr_t)c->buf, .rkey = c->mr->rkey}, peer;
    memcpy(me.gid, c->gid.raw, 16);
    xsend(fd, &me, sizeof(me));
    if (xrecv(fd, &peer, sizeof(peer), 10000)) die("target: no peer info");
    connect_qp(c, &peer);
    xsend(fd, "R", 1);
    for (;;) {
        char cmd;
        if (xrecv(fd, &cmd, 1, o.life_s * 1000)) {
            printf("EV t_ms=%.3f what=target_ctrl_closed\n", now_ms());
            break;
        }
        char rep[48];
        if (cmd == 'E') {
            int rc = qp_2err(c);
            struct qp_snap s = query_qp(c);
            printf("EV t_ms=%.3f what=target_2err rc=%d state=%d\n", now_ms(), rc, s.state);
            snprintf(rep, sizeof(rep), "%d %d", rc, s.state);
        } else if (cmd == 'Q' || cmd == 'X') {
            struct qp_snap s = query_qp(c);
            uint64_t sig;
            memcpy(&sig, c->buf + c->buf_len - 64, 8);
            snprintf(rep, sizeof(rep), "%d %llu", s.state, (unsigned long long)sig);
            printf("EV t_ms=%.3f what=target_query state=%d hw_sq=%d signal=%llu\n", now_ms(), s.state, s.hw_sq,
                   (unsigned long long)sig);
        } else {
            snprintf(rep, sizeof(rep), "?");
        }
        char fixed[64] = {0};
        snprintf(fixed, sizeof(fixed), "%s", rep);
        xsend(fd, fixed, sizeof(fixed));
        if (cmd == 'X') break;
    }
    close(fd);
    return 0;
}

/* ------------------------------------------------------------------------------------ */
/* requester                                                                            */
/* ------------------------------------------------------------------------------------ */

static int ctrl_cmd(int fd, char cmd, char *rep64) {
    xsend(fd, &cmd, 1);
    return xrecv(fd, rep64, 64, 5000);
}

static const char *state_name(int s) {
    static const char *n[] = {"RST", "INIT", "RTR", "RTS", "SQER", "SQD", "ERR"};
    return (s >= 0 && s <= 6) ? n[s] : "?";
}

static int run_requester(struct ctx *c) {
    int fd = ctrl_connect(o.peer, o.port);
    struct peer_info me = {.qpn = c->qpn, .addr = (uint64_t)(uintptr_t)c->buf, .rkey = c->mr->rkey}, peer;
    memcpy(me.gid, c->gid.raw, 16);
    if (xrecv(fd, &peer, sizeof(peer), 10000)) die("requester: no peer info");
    xsend(fd, &me, sizeof(me));
    connect_qp(c, &peer);
    char r;
    if (xrecv(fd, &r, 1, 10000)) die("requester: target not ready");

    /* baseline: put+signal pairs, one at a time, each waited for */
    struct cqe_view v = {0};
    int base_ok = 0;
    for (int i = 0; i < o.baseline; i++) {
        uint64_t sig = post_put_signal(c, &peer, (uint64_t)i * o.put_bytes, o.put_bytes, peer.rkey, peer.rkey);
        ring_db(c, c->pi);
        int rc = wait_cqe(c, sig, 2000, &v);
        if (rc) die("baseline %d: rc=%d op=0x%x syn=0x%x ven=0x%x wqe=%u", i, rc, v.op, v.syndrome, v.vendor, v.wqe);
        base_ok++;
    }
    printf("EV t_ms=%.3f what=baseline_ok n=%d last_wqe=%u op=0x%x\n", now_ms(), base_ok, v.wqe, v.op);

    struct qp_snap q0 = query_qp(c);
    struct qctr_vals qc0 = {0}, qc1 = {0};
    if (o.qcounter == 1 && query_qcounter(c, &qc0)) printf("EV what=qcounter_query_failed\n");
    long long hw0[HWC_N], hw1[HWC_N];
    read_hw(hw0);
    long long x0 = port_ctr("port_xmit_packets"), r0 = port_ctr("port_rcv_packets");

    /* shadow of the whole CQ buffer, to log every CQE write after the fault */
    struct cqe_view *shadow = calloc(c->ncqe, sizeof(*shadow));
    for (uint32_t i = 0; i < c->ncqe; i++) shadow[i] = read_cqe(c, i);

    /* ---- inject ---- */
    double t0 = 0, t_2err = -1;
    uint64_t pi_before = c->pi, last_sig = 0;
    char rep[64];
    struct cq_snap cs0 = query_cq(c); /* dbrk: CQ producer counter before the fault */
    uint64_t k_dbr_val = 0;           /* dbrk: value written to the SQ doorbell record */
    if (!strcmp(o.fault, "none")) {
        t0 = now_ms();
        last_sig = post_put_signal(c, &peer, 0, o.put_bytes, peer.rkey, peer.rkey);
        ring_db(c, c->pi);
    } else if (!strcmp(o.fault, "f1")) {
        for (int i = 0; i < o.f1_n; i++)
            last_sig = post_put_signal(c, &peer, (uint64_t)i * o.f1_bytes, o.f1_bytes, peer.rkey, peer.rkey);
        ring_db(c, c->pi);
        if (o.f1_delay_us) usleep(o.f1_delay_us);
        t0 = now_ms();
        int rc = qp_2err(c);
        t_2err = now_ms() - t0;
        printf("EV t_ms=%.3f what=local_2err rc=%d took_ms=%.3f\n", now_ms(), rc, t_2err);
    } else if (!strcmp(o.fault, "f1post")) {
        int rc = qp_2err(c);
        printf("EV t_ms=%.3f what=local_2err rc=%d state=%s\n", now_ms(), rc, state_name(query_qp(c).state));
        usleep(10000);
        t0 = now_ms();
        last_sig = post_put_signal(c, &peer, 0, o.put_bytes, peer.rkey, peer.rkey);
        ring_db(c, c->pi);
    } else if (!strcmp(o.fault, "f2b")) {
        uint32_t bad = peer.rkey ^ 0x00a5a500u;
        t0 = now_ms();
        last_sig = post_put_signal(c, &peer, 0, o.put_bytes, bad, o.f2b_all ? bad : peer.rkey);
        ring_db(c, c->pi);
    } else if (!strcmp(o.fault, "f3")) {
        if (ctrl_cmd(fd, 'E', rep)) die("target did not ack 2ERR");
        printf("EV t_ms=%.3f what=target_2err_ack rep=\"%s\"\n", now_ms(), rep);
        t0 = now_ms();
        last_sig = post_put_signal(c, &peer, 0, o.put_bytes, peer.rkey, peer.rkey);
        ring_db(c, c->pi);
    } else if (!strcmp(o.fault, "kerr") || !strcmp(o.fault, "knak")) {
        /* ---- dbrk test (2026-09-25) ----
         * kerr: the target moves its QP to ERR first, so none of the batch is ever acked; then
         *       either a local 2ERR k2err_ms after the ring, or (k2err_ms < 0) RETRY_EXC.
         * knak: live target; batch WRITE kbad carries a bad rkey (REM_ACCESS NAK).
         * The UAR is rung with the true pi; the SQ doorbell-record word gets pi_before + kdbr. */
        int is_nak = !strcmp(o.fault, "knak");
        if (!is_nak) {
            if (ctrl_cmd(fd, 'E', rep)) die("target did not ack 2ERR");
            printf("EV t_ms=%.3f what=target_2err_ack rep=\"%s\"\n", now_ms(), rep);
        }
        long long dv = o.kdbr == KDBR_PI ? (long long)(pi_before + o.kn) : (long long)pi_before + o.kdbr;
        if (o.kn < 1 || o.kn > 64 || o.kbytes < 1 || o.kbytes > (1u << 20)) die("kn 1..64, kbytes 1..1MiB");
        if (dv < 0 || dv > (long long)(pi_before + o.kn + 4)) die("kdbr out of the safe range [-pi_before, kn+4]");
        if (pi_before + o.kn + 4 >= c->nwqebb) die("batch does not fit the SQ without wrapping");
        if (is_nak && (o.kbad < 0 || o.kbad >= o.kn)) die("knak needs 0 <= kbad < kn");
        uint32_t bad = peer.rkey ^ 0x00a5a500u;
        k_dbr_val = (uint64_t)dv;
        t0 = now_ms();
        for (int i = 0; i < o.kn; i++) {
            write_rdma_write(c, c->pi, (uint64_t)(uintptr_t)c->buf + (uint64_t)i * o.kbytes, c->mr->lkey,
                             peer.addr + (uint64_t)i * o.kbytes, (is_nak && i == o.kbad) ? bad : peer.rkey, o.kbytes,
                             8 /* CQ_UPDATE: every WQE signaled */);
            c->pi++;
        }
        last_sig = c->pi - 1;
        for (uint64_t j = c->pi; j < k_dbr_val; j++) write_nop(c, j, 8); /* only when kdbr > kn */
        ring_db_val(c, c->pi, k_dbr_val);
        printf("EV t_ms=%.3f what=kbatch_rung pi_before=%llu pi=%llu dbr_val=%llu nops=%lld kbad=%d\n", now_ms(),
               (unsigned long long)pi_before, (unsigned long long)c->pi, (unsigned long long)k_dbr_val,
               (long long)k_dbr_val > (long long)c->pi ? (long long)(k_dbr_val - c->pi) : 0LL, is_nak ? o.kbad : -1);
        if (!is_nak && o.k2err_ms >= 0) {
            if (o.k2err_ms) usleep((useconds_t)o.k2err_ms * 1000);
            double ta = now_ms();
            int rc = qp_2err(c);
            t_2err = now_ms() - t0;
            printf("EV t_ms=%.3f what=local_2err rc=%d at_ms=%.3f took_ms=%.3f\n", now_ms(), rc, t_2err,
                   now_ms() - ta);
        }
    } else {
        die("unknown fault %s", o.fault);
    }
    printf("EV t_ms=%.3f what=fault_injected fault=%s t0_ms=%.3f pi_before=%llu pi_after=%llu last_sig_wqe=%llu\n",
           now_ms(), o.fault, t0, (unsigned long long)pi_before, (unsigned long long)c->pi,
           (unsigned long long)last_sig);

    /* ---- observe ---- */
    FILE *tl = o.timeline ? fopen(o.timeline, "w") : NULL;
    if (tl)
        fprintf(tl, "t_ms,qp_state,hw_sq,sw_sq,cur_retry,cur_rnr,last_acked_psn,next_send_psn,cq_status,cq_pc,cq_cc,"
                    "slot0_op,slot0_syn,slot0_ven,slot0_wqe,n_ok,n_err,n_inval,xmit_pkts,rcv_pkts,dbr0,dbr1\n");
    double next_sample = 0;
    int first_err_seen = 0, n_cqe_writes = 0, last_state = q0.state;
    double t_first_err = -1, t_qp_err = -1, t_last_xmit_change = -1;
    struct cqe_view first_err = {0};
    uint32_t first_err_idx = 0;
    long long last_x = x0;
    struct qp_snap qs = q0;
    struct cq_snap cs = {0};
    /* dbrk: every CQE written after the fault, "wqe:op/syndrome/vendor" in order of detection */
    char kcqes[4096] = "";
    size_t kcqes_len = 0;
    int k_n_ok = 0, k_n_err = 0, k_n_after_late = 0, k_late_done = 0, err_hw_sq = -1, err_sw_sq = -1;
    int k_err_wqe_min = -1, k_err_wqe_max = -1;
    double t_late = -1;
    for (;;) {
        double t = now_ms() - t0;
        if (t > o.observe_ms) break;
        if (o.klate_ms >= 0 && !k_late_done && t >= o.klate_ms) {
            /* dbrk: correct the SQ doorbell record late (and optionally ring the UAR again) */
            volatile uint32_t *kd = (volatile uint32_t *)c->qp_dbr;
            __sync_synchronize();
            kd[c->p.dbr_word] = htobe32((uint32_t)(c->pi & 0xffff));
            __atomic_thread_fence(__ATOMIC_RELEASE);
            if (o.klate_uar) {
                struct wqe_ctrl lc = {0};
                lc.opmod_idx_opcode = htobe32((uint32_t)(c->pi << 8));
                lc.qpn_ds = htobe32(c->qpn << 8);
                uint64_t ldb;
                memcpy(&ldb, &lc, 8);
                mmio_write64(c->qp_uar->reg_addr, ldb);
            }
            k_late_done = 1;
            t_late = now_ms() - t0;
            /* no QUERY_QP here: a firmware command right after the write could itself be the trigger */
            printf("EV t_ms=%.3f what=late_dbr value=%llu uar=%d\n", t_late, (unsigned long long)c->pi, o.klate_uar);
        }
        for (uint32_t i = 0; i < c->ncqe; i++) {
            struct cqe_view e = read_cqe(c, i);
            if (memcmp(&e, &shadow[i], sizeof(e))) {
                shadow[i] = e;
                n_cqe_writes++;
                double te = now_ms() - t0;
                printf("EV t_ms=%.3f what=cqe idx=%u op=0x%x owner=%u syndrome=0x%02x vendor=0x%02x hw=0x%02x/0x%02x "
                       "wqe=%u s_wqe_opcode_qpn=0x%08x\n",
                       te, i, e.op, e.owner, e.syndrome, e.vendor, e.hw_err, e.hw_type, e.wqe, e.s_wqe_opcode_qpn);
                if (is_err_op(e.op) && !first_err_seen) {
                    first_err_seen = 1;
                    t_first_err = te;
                    first_err = e;
                    first_err_idx = i;
                }
                /* dbrk bookkeeping */
                if (e.op == 0) k_n_ok++;
                if (is_err_op(e.op)) {
                    k_n_err++;
                    if (k_err_wqe_min < 0 || e.wqe < k_err_wqe_min) k_err_wqe_min = e.wqe;
                    if (e.wqe > k_err_wqe_max) k_err_wqe_max = e.wqe;
                }
                if (k_late_done) k_n_after_late++;
                if (kcqes_len + 32 < sizeof(kcqes))
                    kcqes_len += (size_t)snprintf(kcqes + kcqes_len, sizeof(kcqes) - kcqes_len, "%s%u:%x/%02x/%02x",
                                                  kcqes_len ? "," : "", e.wqe, e.op, e.syndrome, e.vendor);
            }
        }
        if (t >= next_sample) {
            next_sample += o.sample_ms;
            qs = query_qp(c);
            cs = query_cq(c);
            long long x = port_ctr("port_xmit_packets"), rr = port_ctr("port_rcv_packets");
            if (x != last_x) t_last_xmit_change = t;
            last_x = x;
            if (qs.state != last_state) {
                printf("EV t_ms=%.3f what=qp_state %s->%s hw_sq=%d sw_sq=%d cur_retry=%d\n", t, state_name(last_state),
                       state_name(qs.state), qs.hw_sq, qs.sw_sq, qs.cur_retry);
                if (qs.state == 6 && t_qp_err < 0) {
                    t_qp_err = t;
                    err_hw_sq = qs.hw_sq; /* dbrk: first sample in ERR */
                    err_sw_sq = qs.sw_sq;
                }
                last_state = qs.state;
            }
            if (tl) {
                int nok = 0, nerr = 0, ninv = 0;
                for (uint32_t i = 0; i < c->ncqe; i++) {
                    int op = shadow[i].op;
                    if (op == 0) nok++; else if (is_err_op(op)) nerr++; else if (op == 0xf) ninv++;
                }
                volatile uint32_t *dbr = c->qp_dbr;
                fprintf(tl, "%.1f,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,0x%x,0x%x,0x%x,%u,%d,%d,%d,%lld,%lld,%u,%u\n", t, qs.state,
                        qs.hw_sq, qs.sw_sq, qs.cur_retry, qs.cur_rnr, qs.last_acked_psn, qs.next_send_psn, cs.status,
                        cs.pc, cs.cc, shadow[0].op, shadow[0].syndrome, shadow[0].vendor, shadow[0].wqe, nok, nerr,
                        ninv, x - x0, rr - r0, be32toh(dbr[0]), be32toh(dbr[1]));
            }
        }
    }
    if (tl) fclose(tl);

    /* ---- final state ---- */
    struct qp_snap qf = query_qp(c);
    struct cq_snap cf = query_cq(c);
    int nok = 0, nerr = 0, ninv = 0;
    for (uint32_t i = 0; i < c->ncqe; i++) {
        struct cqe_view e = read_cqe(c, i);
        if (e.op == 0) nok++; else if (is_err_op(e.op)) nerr++; else if (e.op == 0xf) ninv++;
    }
    if (o.qcounter == 1 && query_qcounter(c, &qc1)) printf("EV what=qcounter_query_failed\n");
    read_hw(hw1);
    long long x1 = port_ctr("port_xmit_packets"), r1 = port_ctr("port_rcv_packets");
    int tgt_state = -1;
    unsigned long long tgt_sig = 0;
    if (!ctrl_cmd(fd, 'X', rep)) sscanf(rep, "%d %llu", &tgt_state, &tgt_sig);
    close(fd);
    volatile uint32_t *dbr = c->qp_dbr;
    struct cqe_view s0 = read_cqe(c, 0);

    printf("SUMMARY fault=%s preset=%s sets=%s ack_timeout=%d observe_ms=%d err_cqe=%d t_first_err_ms=%.3f "
           "first_err_idx=%u first_err_syndrome=0x%02x first_err_vendor=0x%02x first_err_wqe=%u "
           "n_cqe_writes=%d cq_ok=%d cq_err=%d cq_inval=%d slot0=0x%x/0x%02x/0x%02x@%u "
           "qp_state_final=%s t_qp_err_ms=%.1f hw_sq=%d sw_sq=%d cur_retry=%d last_acked_psn=%d next_send_psn=%d "
           "cq_status=%d cq_pc=%d cq_cc=%d dbr0=%u dbr1=%u pi=%llu t_last_xmit_change_ms=%.1f xmit_pkts=%lld "
           "rcv_pkts=%lld target_state=%s target_signal=%llu",
           o.fault, o.preset_name, o.sets ? o.sets : "-", o.ack_timeout, o.observe_ms, first_err_seen, t_first_err,
           first_err_idx, first_err.syndrome, first_err.vendor, first_err.wqe, n_cqe_writes, nok, nerr, ninv, s0.op,
           s0.syndrome, s0.vendor, s0.wqe, state_name(qf.state), t_qp_err, qf.hw_sq, qf.sw_sq, qf.cur_retry,
           qf.last_acked_psn, qf.next_send_psn, cf.status, cf.pc, cf.cc, be32toh(dbr[0]), be32toh(dbr[1]),
           (unsigned long long)c->pi, t_last_xmit_change, x1 - x0, r1 - r0, state_name(tgt_state), tgt_sig);
    for (int k = 0; k < HWC_N; k++) printf(" hw_%s=%lld", hwc_names[k], hw1[k] - hw0[k]);
    if (o.qcounter == 1)
        printf(" qc_local_ack_timeout_err=%u qc_req_transport_retries_exceeded=%u qc_req_cqe_error=%u "
               "qc_req_cqe_flush_error=%u qc_req_remote_access_errors=%u qc_req_remote_invalid_request=%u "
               "qc_packet_seq_err=%u qc_out_of_sequence=%u qc_implied_nak_seq_err=%u qc_rnr_nak_retry_err=%u "
               "qc_roce_adp_retrans=%u qc_roce_adp_retrans_to=%u",
               qc1.local_ack_timeout_err - qc0.local_ack_timeout_err,
               qc1.req_transport_retries_exceeded - qc0.req_transport_retries_exceeded,
               qc1.req_cqe_error - qc0.req_cqe_error, qc1.req_cqe_flush_error - qc0.req_cqe_flush_error,
               qc1.req_remote_access_errors - qc0.req_remote_access_errors,
               qc1.req_remote_invalid_request - qc0.req_remote_invalid_request,
               qc1.packet_seq_err - qc0.packet_seq_err, qc1.out_of_sequence - qc0.out_of_sequence,
               qc1.implied_nak_seq_err - qc0.implied_nak_seq_err, qc1.rnr_nak_retry_err - qc0.rnr_nak_retry_err,
               qc1.roce_adp_retrans - qc0.roce_adp_retrans, qc1.roce_adp_retrans_to - qc0.roce_adp_retrans_to);
    if (!strcmp(o.fault, "kerr") || !strcmp(o.fault, "knak") || o.klate_ms >= 0) /* dbrk (2026-09-25) */
        printf(" kn=%d kdbr=%d dbr_val=%llu kbad=%d k2err_ms=%d klate_ms=%d klate_uar=%d pi_before=%llu "
               "err_hw_sq=%d err_sw_sq=%d cq_pc0=%d cq_pc_delta=%d k_n_ok=%d k_n_err=%d k_err_wqe_min=%d "
               "k_err_wqe_max=%d t_late_ms=%.1f k_n_after_late=%d k_cqes=%s",
               o.kn, o.kdbr, (unsigned long long)k_dbr_val, o.kbad, o.k2err_ms, o.klate_ms, o.klate_uar,
               (unsigned long long)pi_before, err_hw_sq, err_sw_sq, cs0.pc, cf.pc - cs0.pc, k_n_ok, k_n_err,
               k_err_wqe_min, k_err_wqe_max, t_late, k_n_after_late, kcqes_len ? kcqes : "-");
    printf("\n");
    (void)t_2err;
    return 0;
}

/* ------------------------------------------------------------------------------------ */

static void usage(void) {
    fprintf(stderr,
            "usage: nrc_devx -m req|tgt -d <dev> -g <gid_idx> -p <tcp_port> [-s <target_mgmt_ip>]\n"
            "  --preset nvshmem|doca   --set k=v[,k=v...]   -f none|f1|f1post|f2b|f3\n"
            "  --timeout <ack_timeout=14> --retry <7> --observe-ms <8000> --sample-ms <100> --life-s <90>\n"
            "  --baseline <4> --put-bytes <262144> --f1-bytes <4194304> --f1-n <8> --f1-delay-us <0>\n"
            "  --f2b-all <1> --qcounter <0|1> -T <timeline.csv>\n"
            "  dbrk test (-f kerr|knak): --kn <16> --kdbr <rel|pi> --kbad <8> --k2err-ms <20|-1>\n"
            "                           --klate-ms <-1> --klate-uar <0|1> --kbytes <64>\n");
    exit(2);
}

int main(int argc, char **argv) {
    clock_gettime(CLOCK_MONOTONIC, &t_start);
    setvbuf(stdout, NULL, _IOLBF, 0);
    o = (struct opts){.preset_name = "nvshmem", .fault = "none", .port = 18633, .gid_idx = -1, .ib_port = 1,
                      .ack_timeout = 14, .retry_cnt = 7, .observe_ms = 8000, .sample_ms = 100, .life_s = 90,
                      .baseline = 4, .put_bytes = 262144, .f1_bytes = 4194304, .f1_n = 8, .f2b_all = 1,
                      .kn = 16, .kdbr = KDBR_PI, .kbad = 8, .k2err_ms = 20, .klate_ms = -1, .klate_uar = 0,
                      .kbytes = 64};
    for (int i = 1; i < argc; i++) {
        const char *a = argv[i];
        const char *v = i + 1 < argc ? argv[i + 1] : NULL;
#define OPT(s) (!strcmp(a, s) && v && ++i)
        if (OPT("-m")) o.requester = !strcmp(v, "req");
        else if (OPT("-d")) o.dev = v;
        else if (OPT("-g")) o.gid_idx = atoi(v);
        else if (OPT("-p")) o.port = atoi(v);
        else if (OPT("-s")) o.peer = v;
        else if (OPT("--preset")) o.preset_name = v;
        else if (OPT("--set")) o.sets = v;
        else if (OPT("-f")) o.fault = v;
        else if (OPT("--timeout")) o.ack_timeout = atoi(v);
        else if (OPT("--retry")) o.retry_cnt = atoi(v);
        else if (OPT("--observe-ms")) o.observe_ms = atoi(v);
        else if (OPT("--sample-ms")) o.sample_ms = atoi(v);
        else if (OPT("--life-s")) o.life_s = atoi(v);
        else if (OPT("--baseline")) o.baseline = atoi(v);
        else if (OPT("--put-bytes")) o.put_bytes = (unsigned)strtoul(v, NULL, 0);
        else if (OPT("--f1-bytes")) o.f1_bytes = (unsigned)strtoul(v, NULL, 0);
        else if (OPT("--f1-n")) o.f1_n = atoi(v);
        else if (OPT("--f1-delay-us")) o.f1_delay_us = atoi(v);
        else if (OPT("--f2b-all")) o.f2b_all = atoi(v);
        else if (OPT("--qcounter")) o.qcounter = atoi(v);
        else if (OPT("-T")) o.timeline = v;
        else if (OPT("--kn")) o.kn = atoi(v); /* dbrk (2026-09-25) */
        else if (OPT("--kdbr")) o.kdbr = strcmp(v, "pi") ? atoi(v) : KDBR_PI;
        else if (OPT("--kbad")) o.kbad = atoi(v);
        else if (OPT("--k2err-ms")) o.k2err_ms = atoi(v);
        else if (OPT("--klate-ms")) o.klate_ms = atoi(v);
        else if (OPT("--klate-uar")) o.klate_uar = atoi(v);
        else if (OPT("--kbytes")) o.kbytes = (unsigned)strtoul(v, NULL, 0);
        else usage();
#undef OPT
    }
    if (!o.dev || o.gid_idx < 0 || (o.requester && !o.peer)) usage();
    if ((uint64_t)o.f1_n * o.f1_bytes > (48u << 20)) die("f1_n * f1_bytes must stay under 48 MiB");

    /* bound everything: the process ends on its own no matter what */
    alarm(o.life_s + (o.requester ? o.observe_ms / 1000 + 30 : 0));

    struct ctx *c = calloc(1, sizeof(*c));
    if (!strcmp(o.preset_name, "nvshmem")) c->p = preset_nvshmem;
    else if (!strcmp(o.preset_name, "doca")) c->p = preset_doca;
    else die("unknown preset %s", o.preset_name);
    if (o.sets) {
        char *s = strdup(o.sets), *save = NULL;
        for (char *kv = strtok_r(s, ",", &save); kv; kv = strtok_r(NULL, ",", &save)) {
            char *eq = strchr(kv, '=');
            if (!eq) die("bad --set item %s", kv);
            *eq = 0;
            size_t k;
            for (k = 0; k < N_PF; k++)
                if (!strcmp(preset_fields[k].name, kv)) break;
            if (k == N_PF) die("unknown preset field %s", kv);
            *pfield(&c->p, k) = (int)strtol(eq + 1, NULL, 0);
        }
        free(s);
    }
    printf("EV t_ms=%.3f what=start role=%s dev=%s fault=%s pid=%d\n", now_ms(), o.requester ? "req" : "tgt", o.dev,
           o.fault, getpid());
    print_preset(&c->p, o.preset_name);
    setup(c);
    return o.requester ? run_requester(c) : run_target(c);
}
