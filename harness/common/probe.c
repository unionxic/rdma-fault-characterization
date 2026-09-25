/* probe.c - shared core for the unified RDMA fault harness. See probe.h. */
#define _GNU_SOURCE
#include "probe.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <unistd.h>
#include <time.h>
#include <sched.h>
#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <sys/socket.h>
#include <netdb.h>

/* ---------------- names ---------------- */
static const char *fault_names[FAULT__COUNT] = {
    [FAULT_NONE]               = "none",
    [FAULT_LOCAL_QP_ERR]       = "local_qp_err",
    [FAULT_REM_ACCESS]         = "rem_access",
    [FAULT_REM_INV_REQ]        = "rem_inv_req",
    [FAULT_RNR]                = "rnr",
    [FAULT_RETRY_SERVER_QP_ERR]= "retry_server_qp_err",
    [FAULT_RETRY_PROC_KILL]    = "retry_proc_kill",
    [FAULT_RETRY_LINK_DOWN]    = "retry_link_down",
    [FAULT_PARTIAL_WRITE]      = "partial_write",
};
const char *fault_name(fault_type_t f) {
    if (f < 0 || f >= FAULT__COUNT || !fault_names[f]) return "?";
    return fault_names[f];
}
int fault_from_name(const char *s, fault_type_t *out) {
    if (!s) return -1;
    for (int i = 0; i < FAULT__COUNT; i++)
        if (fault_names[i] && strcmp(fault_names[i], s) == 0) { *out = (fault_type_t)i; return 0; }
    return -1;
}
const char *recovery_name(recovery_method_t r) {
    switch (r) {
        case RECOVER_QP_ONLY:      return "qp_only";
        case RECOVER_FULL_REBUILD: return "full_rebuild";
        default:                   return "none";
    }
}
int recovery_from_name(const char *s, recovery_method_t *out) {
    if (!s) return -1;
    if (!strcmp(s, "qp_only"))      { *out = RECOVER_QP_ONLY;      return 0; }
    if (!strcmp(s, "full_rebuild")) { *out = RECOVER_FULL_REBUILD; return 0; }
    if (!strcmp(s, "none"))         { *out = RECOVER_NONE;         return 0; }
    return -1;
}

/* ---------------- TCP control channel ---------------- */
static int set_nodelay(int fd) {
    int one = 1;
    if (setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one)) < 0) {
        perror("setsockopt(TCP_NODELAY)");
        return -1;
    }
    return 0;
}

int tcp_server_listen(int port) {
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) { perror("socket"); return -1; }
    int one = 1;
    setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
    struct sockaddr_in a = {0};
    a.sin_family = AF_INET;
    a.sin_addr.s_addr = htonl(INADDR_ANY);
    a.sin_port = htons((uint16_t)port);
    if (bind(fd, (struct sockaddr *)&a, sizeof(a)) < 0) { perror("bind"); close(fd); return -1; }
    if (listen(fd, 1) < 0) { perror("listen"); close(fd); return -1; }
    return fd;
}
int tcp_server_accept(int listen_fd) {
    int fd = accept(listen_fd, NULL, NULL);
    if (fd < 0) { perror("accept"); return -1; }
    if (set_nodelay(fd) < 0) { close(fd); return -1; }
    return fd;
}
int tcp_client_connect(const char *host, int port) {
    char portstr[16];
    snprintf(portstr, sizeof(portstr), "%d", port);
    struct addrinfo hints = {0}, *res = NULL, *rp;
    hints.ai_family = AF_INET;
    hints.ai_socktype = SOCK_STREAM;
    int gai = getaddrinfo(host, portstr, &hints, &res);
    if (gai != 0) { fprintf(stderr, "getaddrinfo(%s): %s\n", host, gai_strerror(gai)); return -1; }
    int fd = -1;
    for (rp = res; rp; rp = rp->ai_next) {
        fd = socket(rp->ai_family, rp->ai_socktype, rp->ai_protocol);
        if (fd < 0) continue;
        if (connect(fd, rp->ai_addr, rp->ai_addrlen) == 0) break;
        close(fd); fd = -1;
    }
    freeaddrinfo(res);
    if (fd < 0) { fprintf(stderr, "connect(%s:%d) failed: %s\n", host, port, strerror(errno)); return -1; }
    if (set_nodelay(fd) < 0) { close(fd); return -1; }
    return fd;
}
int tcp_send_all(int fd, const void *buf, size_t len) {
    const char *p = buf; size_t off = 0;
    while (off < len) {
        ssize_t n = send(fd, p + off, len - off, 0);
        if (n < 0) { if (errno == EINTR) continue; perror("send"); return -1; }
        if (n == 0) { fprintf(stderr, "send: peer closed\n"); return -1; }
        off += (size_t)n;
    }
    return 0;
}
int tcp_recv_all(int fd, void *buf, size_t len) {
    char *p = buf; size_t off = 0;
    while (off < len) {
        ssize_t n = recv(fd, p + off, len - off, 0);
        if (n < 0) { if (errno == EINTR) continue; perror("recv"); return -1; }
        if (n == 0) { fprintf(stderr, "recv: peer closed\n"); return -1; }
        off += (size_t)n;
    }
    return 0;
}
int ctrl_send_line(int fd, const char *line) {
    size_t len = strlen(line);
    char tmp[512];
    if (len + 1 >= sizeof(tmp)) { fprintf(stderr, "ctrl line too long\n"); return -1; }
    memcpy(tmp, line, len);
    tmp[len] = '\n';
    return tcp_send_all(fd, tmp, len + 1);
}
int ctrl_recv_line(int fd, char *buf, size_t cap) {
    size_t i = 0;
    while (i + 1 < cap) {
        char c;
        ssize_t n = recv(fd, &c, 1, 0);
        if (n < 0) { if (errno == EINTR) continue; perror("recv"); return -1; }
        if (n == 0) { if (i == 0) { errno = ECONNRESET; return -1; } break; }   /* EOF: peer closed */
        if (c == '\n') break;
        buf[i++] = c;
    }
    buf[i] = '\0';
    return (int)i;
}

/* ---------------- RC QP lifecycle ---------------- */
static int mtu_to_bytes(enum ibv_mtu m) {
    switch (m) {
        case IBV_MTU_256:  return 256;
        case IBV_MTU_512:  return 512;
        case IBV_MTU_1024: return 1024;
        case IBV_MTU_2048: return 2048;
        case IBV_MTU_4096: return 4096;
        default:           return 1024;
    }
}

int ep_open(probe_ep_t *ep, const char *dev_name, uint8_t ib_port, int gid_index, size_t buf_size) {
    memset(ep, 0, sizeof(*ep));
    ep->ib_port = ib_port;
    ep->gid_index = gid_index;
    ep->buf_size = buf_size;
    snprintf(ep->dev_name, sizeof(ep->dev_name), "%s", dev_name);

    int num = 0;
    struct ibv_device **list = ibv_get_device_list(&num);
    if (!list) { perror("ibv_get_device_list"); return -1; }
    struct ibv_device *dev = NULL;
    for (int i = 0; i < num; i++)
        if (strcmp(ibv_get_device_name(list[i]), dev_name) == 0) { dev = list[i]; break; }
    if (!dev) { fprintf(stderr, "device %s not found\n", dev_name); ibv_free_device_list(list); return -1; }

    ep->ctx = ibv_open_device(dev);
    ibv_free_device_list(list);
    if (!ep->ctx) { fprintf(stderr, "ibv_open_device(%s) failed\n", dev_name); return -1; }

    if (ibv_query_port(ep->ctx, ib_port, &ep->port_attr)) { perror("ibv_query_port"); goto err; }
    ep->mtu_bytes = mtu_to_bytes(ep->port_attr.active_mtu);
    if (ibv_query_gid(ep->ctx, ib_port, gid_index, &ep->gid)) { perror("ibv_query_gid"); goto err; }

    ep->pd = ibv_alloc_pd(ep->ctx);
    if (!ep->pd) { perror("ibv_alloc_pd"); goto err; }

    ep->buf = aligned_alloc(4096, buf_size);
    if (!ep->buf) { perror("aligned_alloc"); goto err; }
    memset(ep->buf, 0, buf_size);

    /* No REMOTE_ATOMIC here, and ep_to_init leaves atomic disabled on the QP:
     * an incoming atomic is then rejected at the QP level as REM_INV_REQ (0x8a),
     * which is exactly how the rem_inv_req fault is triggered. */
    ep->mr = ibv_reg_mr(ep->pd, ep->buf, buf_size,
                        IBV_ACCESS_LOCAL_WRITE | IBV_ACCESS_REMOTE_WRITE |
                        IBV_ACCESS_REMOTE_READ);
    if (!ep->mr) { perror("ibv_reg_mr"); goto err; }

    ep->cq = ibv_create_cq(ep->ctx, PROBE_CQ_DEPTH, NULL, NULL, 0);
    if (!ep->cq) { perror("ibv_create_cq"); goto err; }
    return 0;
err:
    ep_close(ep);
    return -1;
}

int ep_create_qp(probe_ep_t *ep) {
    struct ibv_qp_init_attr qia = {0};
    qia.send_cq = ep->cq;
    qia.recv_cq = ep->cq;
    qia.qp_type = IBV_QPT_RC;
    qia.sq_sig_all = 0;
    qia.cap.max_send_wr = PROBE_MAX_SEND_WR;
    qia.cap.max_recv_wr = PROBE_MAX_RECV_WR;
    qia.cap.max_send_sge = 1;
    qia.cap.max_recv_sge = 1;
    ep->qp = ibv_create_qp(ep->pd, &qia);
    if (!ep->qp) { perror("ibv_create_qp"); return -1; }
    return 0;
}

int ep_to_init(probe_ep_t *ep) {
    struct ibv_qp_attr a = {0};
    a.qp_state = IBV_QPS_INIT;
    a.pkey_index = 0;
    a.port_num = ep->ib_port;
    a.qp_access_flags = IBV_ACCESS_LOCAL_WRITE | IBV_ACCESS_REMOTE_WRITE | IBV_ACCESS_REMOTE_READ;
    int flags = IBV_QP_STATE | IBV_QP_PKEY_INDEX | IBV_QP_PORT | IBV_QP_ACCESS_FLAGS;
    if (ibv_modify_qp(ep->qp, &a, flags)) { perror("modify->INIT"); return -1; }
    return 0;
}

int ep_to_rtr(probe_ep_t *ep, const probe_dest_t *remote) {
    struct ibv_qp_attr a = {0};
    a.qp_state = IBV_QPS_RTR;
    a.path_mtu = ep->port_attr.active_mtu;
    a.dest_qp_num = remote->qp_num;
    a.rq_psn = remote->psn;
    a.max_dest_rd_atomic = 1;
    a.min_rnr_timer = 12;               /* ~0.64 ms */
    a.ah_attr.is_global = 1;            /* RoCE: always global (GRH) */
    a.ah_attr.port_num = ep->ib_port;
    a.ah_attr.grh.hop_limit = 1;
    a.ah_attr.grh.dgid = remote->gid;
    a.ah_attr.grh.sgid_index = (uint8_t)ep->gid_index;
    a.ah_attr.grh.traffic_class = 0;
    int flags = IBV_QP_STATE | IBV_QP_AV | IBV_QP_PATH_MTU | IBV_QP_DEST_QPN |
                IBV_QP_RQ_PSN | IBV_QP_MAX_DEST_RD_ATOMIC | IBV_QP_MIN_RNR_TIMER;
    if (ibv_modify_qp(ep->qp, &a, flags)) { perror("modify->RTR"); return -1; }
    return 0;
}

int ep_to_rts(probe_ep_t *ep, uint32_t local_psn) {
    struct ibv_qp_attr a = {0};
    a.qp_state = IBV_QPS_RTS;
    a.timeout = 14;        /* ~67 ms per attempt (see firmware floor note) */
    a.retry_cnt = 7;
    a.rnr_retry = 6;       /* 7 == retry forever; 6 lets RNR NAKs exhaust (finite) */
    a.sq_psn = local_psn;
    a.max_rd_atomic = 1;
    int flags = IBV_QP_STATE | IBV_QP_TIMEOUT | IBV_QP_RETRY_CNT |
                IBV_QP_RNR_RETRY | IBV_QP_SQ_PSN | IBV_QP_MAX_QP_RD_ATOMIC;
    if (ibv_modify_qp(ep->qp, &a, flags)) { perror("modify->RTS"); return -1; }
    return 0;
}

int ep_to_err(probe_ep_t *ep) {
    struct ibv_qp_attr a = {0};
    a.qp_state = IBV_QPS_ERR;
    if (ibv_modify_qp(ep->qp, &a, IBV_QP_STATE)) { perror("modify->ERR"); return -1; }
    return 0;
}
int ep_to_reset(probe_ep_t *ep) {
    struct ibv_qp_attr a = {0};
    a.qp_state = IBV_QPS_RESET;
    if (ibv_modify_qp(ep->qp, &a, IBV_QP_STATE)) { perror("modify->RESET"); return -1; }
    return 0;
}
enum ibv_qp_state ep_qp_state(probe_ep_t *ep) {
    struct ibv_qp_attr a; struct ibv_qp_init_attr ia;
    if (ibv_query_qp(ep->qp, &a, IBV_QP_STATE, &ia)) return IBV_QPS_ERR;
    return a.qp_state;
}
void ep_fill_dest(const probe_ep_t *ep, uint32_t psn, probe_dest_t *out) {
    memset(out, 0, sizeof(*out));
    out->qp_num = ep->qp->qp_num;
    out->psn = psn;
    out->rkey = ep->mr->rkey;
    out->addr = (uint64_t)(uintptr_t)ep->buf;
    out->buf_size = (uint32_t)ep->buf_size;
    out->gid = ep->gid;
}
void ep_destroy_qp(probe_ep_t *ep) {
    if (ep->qp) { ibv_destroy_qp(ep->qp); ep->qp = NULL; }
}
void ep_close(probe_ep_t *ep) {
    if (ep->qp) { ibv_destroy_qp(ep->qp); ep->qp = NULL; }
    if (ep->cq) { ibv_destroy_cq(ep->cq); ep->cq = NULL; }
    if (ep->mr) { ibv_dereg_mr(ep->mr); ep->mr = NULL; }
    if (ep->buf){ free(ep->buf); ep->buf = NULL; }
    if (ep->pd) { ibv_dealloc_pd(ep->pd); ep->pd = NULL; }
    if (ep->ctx){ ibv_close_device(ep->ctx); ep->ctx = NULL; }
}

/* ---------------- work requests ---------------- */
int post_write(probe_ep_t *ep, uint64_t wr_id, size_t len,
               uint64_t remote_addr, uint32_t rkey, bool signaled) {
    struct ibv_sge sge = { .addr = (uint64_t)(uintptr_t)ep->buf, .length = (uint32_t)len, .lkey = ep->mr->lkey };
    struct ibv_send_wr wr = {0}, *bad = NULL;
    wr.wr_id = wr_id;
    wr.sg_list = &sge;
    wr.num_sge = 1;
    wr.opcode = IBV_WR_RDMA_WRITE;
    wr.send_flags = signaled ? IBV_SEND_SIGNALED : 0;
    wr.wr.rdma.remote_addr = remote_addr;
    wr.wr.rdma.rkey = rkey;
    int rc = ibv_post_send(ep->qp, &wr, &bad);
    if (rc) { fprintf(stderr, "ibv_post_send(write): %s\n", strerror(rc)); return -1; }
    return 0;
}
int post_read(probe_ep_t *ep, uint64_t wr_id, size_t len,
              uint64_t remote_addr, uint32_t rkey) {
    struct ibv_sge sge = { .addr = (uint64_t)(uintptr_t)ep->buf, .length = (uint32_t)len, .lkey = ep->mr->lkey };
    struct ibv_send_wr wr = {0}, *bad = NULL;
    wr.wr_id = wr_id;
    wr.sg_list = &sge;
    wr.num_sge = 1;
    wr.opcode = IBV_WR_RDMA_READ;
    wr.send_flags = IBV_SEND_SIGNALED;
    wr.wr.rdma.remote_addr = remote_addr;
    wr.wr.rdma.rkey = rkey;
    int rc = ibv_post_send(ep->qp, &wr, &bad);
    if (rc) { fprintf(stderr, "ibv_post_send(read): %s\n", strerror(rc)); return -1; }
    return 0;
}
int post_send(probe_ep_t *ep, uint64_t wr_id, size_t len) {
    struct ibv_sge sge = { .addr = (uint64_t)(uintptr_t)ep->buf, .length = (uint32_t)len, .lkey = ep->mr->lkey };
    struct ibv_send_wr wr = {0}, *bad = NULL;
    wr.wr_id = wr_id;
    wr.sg_list = &sge;
    wr.num_sge = 1;
    wr.opcode = IBV_WR_SEND;
    wr.send_flags = IBV_SEND_SIGNALED;
    int rc = ibv_post_send(ep->qp, &wr, &bad);
    if (rc) { fprintf(stderr, "ibv_post_send(send): %s\n", strerror(rc)); return -1; }
    return 0;
}
int post_atomic_fa(probe_ep_t *ep, uint64_t wr_id, uint64_t remote_addr, uint32_t rkey) {
    struct ibv_sge sge = { .addr = (uint64_t)(uintptr_t)ep->buf, .length = 8, .lkey = ep->mr->lkey };
    struct ibv_send_wr wr = {0}, *bad = NULL;
    wr.wr_id = wr_id;
    wr.sg_list = &sge;
    wr.num_sge = 1;
    wr.opcode = IBV_WR_ATOMIC_FETCH_AND_ADD;
    wr.send_flags = IBV_SEND_SIGNALED;
    wr.wr.atomic.remote_addr = remote_addr;
    wr.wr.atomic.rkey = rkey;
    wr.wr.atomic.compare_add = 1;
    int rc = ibv_post_send(ep->qp, &wr, &bad);
    if (rc) { fprintf(stderr, "ibv_post_send(atomic): %s\n", strerror(rc)); return -1; }
    return 0;
}
int post_recv(probe_ep_t *ep, uint64_t wr_id, size_t len) {
    struct ibv_sge sge = { .addr = (uint64_t)(uintptr_t)ep->buf, .length = (uint32_t)len, .lkey = ep->mr->lkey };
    struct ibv_recv_wr wr = {0}, *bad = NULL;
    wr.wr_id = wr_id;
    wr.sg_list = &sge;
    wr.num_sge = 1;
    int rc = ibv_post_recv(ep->qp, &wr, &bad);
    if (rc) { fprintf(stderr, "ibv_post_recv: %s\n", strerror(rc)); return -1; }
    return 0;
}
int poll_one(probe_ep_t *ep, struct ibv_wc *wc, long timeout_ms) {
    uint64_t deadline = (timeout_ms > 0) ? now_ns() + (uint64_t)timeout_ms * 1000000ull : 0;
    for (;;) {
        int n = ibv_poll_cq(ep->cq, 1, wc);
        if (n < 0) { fprintf(stderr, "ibv_poll_cq < 0\n"); return -1; }
        if (n == 1) return 1;
        if (timeout_ms > 0 && now_ns() >= deadline) return 0;
    }
}
int ep_query_sq_psn(probe_ep_t *ep, uint32_t *sq_psn) {
    struct ibv_qp_attr a; struct ibv_qp_init_attr ia;
    if (ibv_query_qp(ep->qp, &a, IBV_QP_SQ_PSN, &ia)) { perror("query sq_psn"); return -1; }
    *sq_psn = a.sq_psn;
    return 0;
}

/* ---------------- timing ---------------- */
uint64_t now_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC_RAW, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;
}
void pin_to_cpu(int cpu) {
    if (cpu < 0) return;
    cpu_set_t set;
    CPU_ZERO(&set);
    CPU_SET(cpu, &set);
    if (sched_setaffinity(0, sizeof(set), &set) != 0)
        fprintf(stderr, "warning: pin_to_cpu(%d): %s\n", cpu, strerror(errno));
}

/* ---------------- hardware counters ---------------- */
uint64_t counter_read(const char *dev_name, uint8_t ib_port, const char *counter) {
    char path[256];
    snprintf(path, sizeof(path),
             "/sys/class/infiniband/%s/ports/%u/hw_counters/%s", dev_name, ib_port, counter);
    FILE *f = fopen(path, "r");
    if (!f) return UINT64_MAX;
    unsigned long long v = 0;
    if (fscanf(f, "%llu", &v) != 1) { fclose(f); return UINT64_MAX; }
    fclose(f);
    return (uint64_t)v;
}

uint64_t netdev_counter(const char *iface, const char *stat) {
    if (!iface || !iface[0]) return UINT64_MAX;
    char path[256];
    snprintf(path, sizeof(path), "/sys/class/net/%s/statistics/%s", iface, stat);
    FILE *f = fopen(path, "r");
    if (!f) return UINT64_MAX;
    unsigned long long v = 0;
    if (fscanf(f, "%llu", &v) != 1) { fclose(f); return UINT64_MAX; }
    fclose(f);
    return (uint64_t)v;
}
uint64_t port_counter_read(const char *dev_name, uint8_t ib_port, const char *name) {
    char path[256];
    snprintf(path, sizeof(path),
             "/sys/class/infiniband/%s/ports/%u/counters/%s", dev_name, ib_port, name);
    FILE *f = fopen(path, "r");
    if (!f) return UINT64_MAX;
    unsigned long long v = 0;
    if (fscanf(f, "%llu", &v) != 1) { fclose(f); return UINT64_MAX; }
    fclose(f);
    return (uint64_t)v;
}
enum ibv_port_state ep_port_state(probe_ep_t *ep) {
    struct ibv_port_attr pa;
    if (ibv_query_port(ep->ctx, ep->ib_port, &pa)) return IBV_PORT_DOWN;
    return pa.state;
}

/* ---------------- classification ---------------- */
classify_t classify(enum ibv_wc_status status, uint32_t vendor_err) {
    classify_t c = { ibv_wc_status_str(status), "unknown", "inspect", true, false };
    switch (status) {
        case IBV_WC_SUCCESS:
            c.cause = "no error"; c.action = "none"; c.auto_recoverable = true; break;
        case IBV_WC_WR_FLUSH_ERR: /* 5 */
            c.cause = "WR flushed (local QP left RTS, e.g. forced ERR)";
            c.action = "drain CQ, QP-only recover, repost";
            c.peer_alive = true; c.auto_recoverable = true; break;
        case IBV_WC_REM_ACCESS_ERR: /* 10 */
            c.cause = (vendor_err == 0x88) ? "remote access: invalid rkey or out-of-bounds addr"
                                           : "remote access violation";
            c.action = "refresh rkey / clamp to remote MR bounds, QP-only recover";
            c.peer_alive = true; c.auto_recoverable = true; break;
        case IBV_WC_REM_INV_REQ_ERR: /* 9 */
            c.cause = "remote invalid request (malformed WR / len / opcode)";
            c.action = "fix request params, QP-only recover";
            c.peer_alive = true; c.auto_recoverable = true; break;
        case IBV_WC_RNR_RETRY_EXC_ERR: /* 13 */
            c.cause = "RNR retries exhausted (responder had no recv WQE)";
            c.action = "ensure remote posts recvs, QP-only recover";
            c.peer_alive = true; c.auto_recoverable = true; break;
        case IBV_WC_RETRY_EXC_ERR: /* 12 */
            c.cause = "transport retries exhausted (no ACK): responder QP ERR, process dead, or link down";
            c.action = "probe peer liveness (counters/ctrl); if dead -> human intervention, else QP-only";
            c.peer_alive = false; c.auto_recoverable = false; break;
        case IBV_WC_LOC_PROT_ERR: /* 4 */
            c.cause = "local protection (bad lkey / local MR bounds)";
            c.action = "fix local MR/lkey, QP-only recover";
            c.peer_alive = true; c.auto_recoverable = true; break;
        case IBV_WC_LOC_LEN_ERR: /* 1 */
            c.cause = "local length error";
            c.action = "fix SGE length, QP-only recover";
            c.peer_alive = true; c.auto_recoverable = true; break;
        default:
            c.cause = "other"; c.action = "inspect status+vendor_err";
            c.peer_alive = true; c.auto_recoverable = false; break;
    }
    return c;
}
