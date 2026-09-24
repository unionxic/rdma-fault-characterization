/* fp_common.c - see fp_common.h */
#define _GNU_SOURCE
#include "fp_common.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <time.h>
#include <netdb.h>
#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <sys/socket.h>
#include <infiniband/mlx5dv.h>

uint64_t fp_now_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC_RAW, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;
}

void fp_set_cloexec(int fd) {
    int fl = fcntl(fd, F_GETFD);
    if (fl >= 0) fcntl(fd, F_SETFD, fl | FD_CLOEXEC);
}

static void nodelay(int fd) {
    int one = 1;
    setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));
}

int fp_listen(const char *bind_ip, int port) {
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) { perror("socket"); return -1; }
    int one = 1;
    setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
    struct sockaddr_in a;
    memset(&a, 0, sizeof(a));
    a.sin_family = AF_INET;
    a.sin_port = htons((uint16_t)port);
    if (!bind_ip || inet_pton(AF_INET, bind_ip, &a.sin_addr) != 1) a.sin_addr.s_addr = htonl(INADDR_ANY);
    if (bind(fd, (struct sockaddr *)&a, sizeof(a)) < 0) { perror("bind"); close(fd); return -1; }
    if (listen(fd, 16) < 0) { perror("listen"); close(fd); return -1; }
    return fd;
}

int fp_accept(int lfd) {
    int fd;
    do { fd = accept(lfd, NULL, NULL); } while (fd < 0 && errno == EINTR);
    if (fd < 0) { perror("accept"); return -1; }
    nodelay(fd);
    return fd;
}

int fp_connect(const char *host, int port) {
    char ps[16];
    snprintf(ps, sizeof(ps), "%d", port);
    struct addrinfo h, *res = NULL, *rp;
    memset(&h, 0, sizeof(h));
    h.ai_family = AF_INET;
    h.ai_socktype = SOCK_STREAM;
    if (getaddrinfo(host, ps, &h, &res) != 0) return -1;
    int fd = -1;
    for (rp = res; rp; rp = rp->ai_next) {
        fd = socket(rp->ai_family, rp->ai_socktype, rp->ai_protocol);
        if (fd < 0) continue;
        if (connect(fd, rp->ai_addr, rp->ai_addrlen) == 0) break;
        close(fd);
        fd = -1;
    }
    freeaddrinfo(res);
    if (fd >= 0) nodelay(fd);
    return fd;
}

int fp_send_all(int fd, const void *buf, size_t len) {
    const char *p = buf;
    size_t off = 0;
    while (off < len) {
        ssize_t n = send(fd, p + off, len - off, MSG_NOSIGNAL);
        if (n < 0) { if (errno == EINTR) continue; return -1; }
        if (n == 0) return -1;
        off += (size_t)n;
    }
    return 0;
}

int fp_recv_all(int fd, void *buf, size_t len) {
    char *p = buf;
    size_t off = 0;
    while (off < len) {
        ssize_t n = recv(fd, p + off, len - off, 0);
        if (n < 0) { if (errno == EINTR) continue; return -1; }
        if (n == 0) return -1;
        off += (size_t)n;
    }
    return 0;
}

int fp_send_line(int fd, const char *fmt, ...) {
    char buf[1024];
    va_list ap;
    va_start(ap, fmt);
    int n = vsnprintf(buf, sizeof(buf) - 1, fmt, ap);
    va_end(ap);
    if (n < 0 || n >= (int)sizeof(buf) - 1) return -1;
    buf[n++] = '\n';
    return fp_send_all(fd, buf, (size_t)n);
}

int fp_recv_line(int fd, char *buf, size_t cap) {
    size_t i = 0;
    while (i + 1 < cap) {
        char c;
        ssize_t n = recv(fd, &c, 1, 0);
        if (n < 0) { if (errno == EINTR) continue; return -1; }
        if (n == 0) { if (i == 0) return -1; break; }
        if (c == '\n') break;
        buf[i++] = c;
    }
    buf[i] = '\0';
    return (int)i;
}

int fp_find_roce_v2_ipv4_gid(const char *dev, int port) {
    for (int g = 0; g < 256; g++) {
        char p[256], t[64] = "", v[128] = "";
        snprintf(p, sizeof(p), "/sys/class/infiniband/%s/ports/%d/gid_attrs/types/%d", dev, port, g);
        FILE *f = fopen(p, "r");
        if (!f) continue;
        if (!fgets(t, sizeof(t), f)) t[0] = 0;
        fclose(f);
        if (strncmp(t, "RoCE v2", 7) != 0) continue;
        snprintf(p, sizeof(p), "/sys/class/infiniband/%s/ports/%d/gids/%d", dev, port, g);
        f = fopen(p, "r");
        if (!f) continue;
        if (!fgets(v, sizeof(v), f)) v[0] = 0;
        fclose(f);
        if (strncmp(v, "0000:0000:0000:0000:0000:ffff:", 30) == 0) return g;
    }
    return -1;
}

int fp_open(fp_ep_t *ep, const char *dev, int port, int gid_index, int devx) {
    memset(ep, 0, sizeof(*ep));
    ep->port = (uint8_t)port;
    if (gid_index < 0) gid_index = fp_find_roce_v2_ipv4_gid(dev, port);
    if (gid_index < 0) { fprintf(stderr, "no RoCE v2 IPv4 GID on %s/%d\n", dev, port); return -1; }
    ep->gid_index = gid_index;
    int num = 0;
    struct ibv_device **list = ibv_get_device_list(&num);
    if (!list) { perror("ibv_get_device_list"); return -1; }
    struct ibv_device *d = NULL;
    for (int i = 0; i < num; i++)
        if (!strcmp(ibv_get_device_name(list[i]), dev)) d = list[i];
    if (!d) { fprintf(stderr, "device %s not found\n", dev); ibv_free_device_list(list); return -1; }
    if (devx) {
        struct mlx5dv_context_attr da;
        memset(&da, 0, sizeof(da));
        da.flags = MLX5DV_CONTEXT_FLAGS_DEVX;
        ep->ctx = mlx5dv_open_device(d, &da);
    } else {
        ep->ctx = ibv_open_device(d);
    }
    ibv_free_device_list(list);
    if (!ep->ctx) { fprintf(stderr, "ibv_open_device failed\n"); return -1; }
    if (ibv_query_port(ep->ctx, ep->port, &ep->port_attr)) { perror("ibv_query_port"); return -1; }
    if (ibv_query_gid(ep->ctx, ep->port, gid_index, &ep->gid)) { perror("ibv_query_gid"); return -1; }
    ep->pd = ibv_alloc_pd(ep->ctx);
    if (!ep->pd) { perror("ibv_alloc_pd"); return -1; }
    ep->cq = ibv_create_cq(ep->ctx, 4096, NULL, NULL, 0);
    if (!ep->cq) { perror("ibv_create_cq"); return -1; }
    return 0;
}

int fp_create_qp(fp_ep_t *ep, int max_send_wr) {
    struct ibv_qp_init_attr a;
    memset(&a, 0, sizeof(a));
    a.send_cq = ep->cq;
    a.recv_cq = ep->cq;
    a.qp_type = IBV_QPT_RC;
    a.cap.max_send_wr = (uint32_t)max_send_wr;
    a.cap.max_recv_wr = 1;
    a.cap.max_send_sge = 1;
    a.cap.max_recv_sge = 1;
    ep->qp = ibv_create_qp(ep->pd, &a);
    if (!ep->qp) { perror("ibv_create_qp"); return -1; }
    struct ibv_qp_attr m;
    memset(&m, 0, sizeof(m));
    m.qp_state = IBV_QPS_INIT;
    m.port_num = ep->port;
    m.qp_access_flags = IBV_ACCESS_LOCAL_WRITE | IBV_ACCESS_REMOTE_WRITE | IBV_ACCESS_REMOTE_READ;
    if (ibv_modify_qp(ep->qp, &m, IBV_QP_STATE | IBV_QP_PKEY_INDEX | IBV_QP_PORT | IBV_QP_ACCESS_FLAGS)) {
        perror("modify INIT");
        return -1;
    }
    return 0;
}

int fp_min_rnr_timer = 12;

int fp_qp_to_rts(fp_ep_t *ep, const fp_dest_t *r, uint32_t local_psn) {
    struct ibv_qp_attr a;
    memset(&a, 0, sizeof(a));
    a.qp_state = IBV_QPS_RTR;
    a.path_mtu = ep->port_attr.active_mtu;
    a.dest_qp_num = r->qpn;
    a.rq_psn = r->psn;
    a.max_dest_rd_atomic = 1;
    a.min_rnr_timer = (uint8_t)fp_min_rnr_timer;
    a.ah_attr.is_global = 1;
    a.ah_attr.port_num = ep->port;
    a.ah_attr.grh.hop_limit = 1;
    a.ah_attr.grh.dgid = r->gid;
    a.ah_attr.grh.sgid_index = (uint8_t)ep->gid_index;
    if (ibv_modify_qp(ep->qp, &a, IBV_QP_STATE | IBV_QP_AV | IBV_QP_PATH_MTU | IBV_QP_DEST_QPN |
                                  IBV_QP_RQ_PSN | IBV_QP_MAX_DEST_RD_ATOMIC | IBV_QP_MIN_RNR_TIMER)) {
        perror("modify RTR");
        return -1;
    }
    memset(&a, 0, sizeof(a));
    a.qp_state = IBV_QPS_RTS;
    a.timeout = FP_IB_TIMEOUT;
    a.retry_cnt = FP_RETRY_CNT;
    a.rnr_retry = FP_RNR_RETRY;
    a.sq_psn = local_psn;
    a.max_rd_atomic = 1;
    if (ibv_modify_qp(ep->qp, &a, IBV_QP_STATE | IBV_QP_TIMEOUT | IBV_QP_RETRY_CNT |
                                  IBV_QP_RNR_RETRY | IBV_QP_SQ_PSN | IBV_QP_MAX_QP_RD_ATOMIC)) {
        perror("modify RTS");
        return -1;
    }
    return 0;
}

const char *fp_status_short(int st) {
    switch (st) {
        case IBV_WC_SUCCESS:          return "SUCCESS";
        case IBV_WC_WR_FLUSH_ERR:     return "WR_FLUSH";
        case IBV_WC_REM_ACCESS_ERR:   return "REM_ACCESS";
        case IBV_WC_REM_INV_REQ_ERR:  return "REM_INV_REQ";
        case IBV_WC_REM_OP_ERR:       return "REM_OP";
        case IBV_WC_RETRY_EXC_ERR:    return "RETRY_EXC";
        case IBV_WC_RNR_RETRY_EXC_ERR:return "RNR_RETRY_EXC";
        case IBV_WC_LOC_PROT_ERR:     return "LOC_PROT";
        default:                      return "OTHER";
    }
}
