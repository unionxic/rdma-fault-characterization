/*
 * ackt.c - RETRY_EXC detection vs IB ACK timeout, with timestamped port-counter sampling.
 *
 * One binary, two roles:
 *   responder (sunny):  ackt -S -d mlx5_0 -g <gid> -p <port>
 *   requester (rain):   ackt -c <responder mgmt ip> -p <port> -d mlx5_1 -g <gid>
 *                            -T <ib timeout exp> -R <retry_cnt> -n <trials>
 *                            -o <trials.csv> -e <events.csv> [-L label] [-K counters]
 *                            [-W detect cap ms] [-Q quiet ms] [-A tail ms] [-C cpu] [-X sampler cpu]
 *                            [-N (no sampler)] [-I sampler sleep us]
 *
 * Per trial: fresh RC QP pair (requester: timeout T, retry_cnt R), one warm-up 64 B WRITE
 * (must succeed), a quiet window of Q ms (background check), then the responder moves its QP
 * to ERR (it then drops our packets silently, no NAK), the requester posts one signaled
 * 64 B WRITE at t0 and tight-polls until the completion (t1). detect = t1 - t0
 * (CLOCK_MONOTONIC_RAW). The QPs are destroyed after each trial.
 *
 * Sampler thread: loops over (a) one RDMA-netlink RDMA_NLDEV_CMD_STAT_GET of the port's
 * default counter set (all hw_counters in one firmware query, not cached) and (b) the sysfs
 * IB port counters named with a leading '@' (e.g. @port_xmit_packets). Every change of a
 * selected counter is logged with a bracket [lo, hi]: the counter held the old value at some
 * instant after lo and the new one before hi (lo = start of the previous read, hi = end of
 * the read that saw the change). Times are relative to the trial's t0.
 * The port counters are shared with every other QP on the port (NVMe-oF, ...): the quiet
 * window before t0 measures that background.
 */
#define _GNU_SOURCE
#include "probe.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <unistd.h>
#include <fcntl.h>
#include <getopt.h>
#include <pthread.h>
#include <sched.h>
#include <stdatomic.h>
#include <sys/socket.h>
#include <linux/netlink.h>
#include <rdma/rdma_netlink.h>

#define MAXC   24
#define MAXEV  (1 << 20)
#define WRITE_LEN 64

/* ---------------- counters ---------------- */
typedef struct {
    char     name[64];
    int      is_port;      /* 1 = sysfs .../counters/<name>, 0 = hw counter via netlink */
    int      fd;           /* sysfs fd (is_port) */
    uint64_t last;
    uint64_t last_ta;
    int      have;
} ctr_t;

typedef struct {
    int      trial;
    int      c;
    uint64_t lo, hi;       /* absolute CLOCK_MONOTONIC_RAW ns */
    uint64_t oldv, newv;
} ev_t;

static ctr_t  C[MAXC];
static int    NC;
static int    n_hw;        /* number of hw (netlink) counters among C */
static ev_t  *EV;
static atomic_long  nev;
static atomic_int   s_active, s_trial, s_quit, s_idle_ack;
static atomic_ulong s_rounds, s_maxround, s_sumround;
static long   s_sleep_us;
static int    s_cpu = -1;

static const char *g_dev;
static int    g_port = 1;
static uint32_t g_devidx;
static __thread int      t_nl = -1;   /* per-thread netlink socket */
static __thread uint32_t t_seq = 1;

/* ---------------- RDMA netlink ---------------- */
static int nl_open(void) {
    int fd = socket(AF_NETLINK, SOCK_RAW | SOCK_CLOEXEC, NETLINK_RDMA);
    if (fd < 0) { perror("socket(NETLINK_RDMA)"); return -1; }
    struct sockaddr_nl sa = { .nl_family = AF_NETLINK };
    if (bind(fd, (struct sockaddr *)&sa, sizeof(sa)) < 0) { perror("bind netlink"); close(fd); return -1; }
    return fd;
}

static void put_u32_attr(char *buf, size_t *off, uint16_t type, uint32_t v) {
    struct nlattr *a = (struct nlattr *)(buf + *off);
    a->nla_type = type;
    a->nla_len = NLA_HDRLEN + sizeof(uint32_t);
    memcpy(buf + *off + NLA_HDRLEN, &v, sizeof(v));
    *off += NLA_ALIGN(a->nla_len);
}

/* iterate attributes in [p, p+len) */
#define FOR_ATTR(a, p, len) \
    for (struct nlattr *a = (struct nlattr *)(p); \
         (char *)a + NLA_HDRLEN <= (char *)(p) + (len) && a->nla_len >= NLA_HDRLEN && \
         (char *)a + a->nla_len <= (char *)(p) + (len); \
         a = (struct nlattr *)((char *)a + NLA_ALIGN(a->nla_len)))

static int nl_find_dev(const char *name, uint32_t *idx) {
    char req[256] = {0};
    struct nlmsghdr *h = (struct nlmsghdr *)req;
    h->nlmsg_len = NLMSG_HDRLEN;
    h->nlmsg_type = RDMA_NL_GET_TYPE(RDMA_NL_NLDEV, RDMA_NLDEV_CMD_GET);
    h->nlmsg_flags = NLM_F_REQUEST | NLM_F_DUMP;
    h->nlmsg_seq = t_seq++;
    if (send(t_nl, req, h->nlmsg_len, 0) < 0) { perror("nl send"); return -1; }
    static char rbuf[1 << 16];
    int found = 0;
    for (;;) {
        ssize_t n = recv(t_nl, rbuf, sizeof(rbuf), 0);
        if (n < 0) { if (errno == EINTR) continue; perror("nl recv"); return -1; }
        for (struct nlmsghdr *m = (struct nlmsghdr *)rbuf; NLMSG_OK(m, (size_t)n); m = NLMSG_NEXT(m, n)) {
            if (m->nlmsg_type == NLMSG_DONE) return found ? 0 : -1;
            if (m->nlmsg_type == NLMSG_ERROR) {
                struct nlmsgerr *e = NLMSG_DATA(m);
                if (e->error) { fprintf(stderr, "nl dev get: %s\n", strerror(-e->error)); return -1; }
                continue;
            }
            uint32_t di = UINT32_MAX; const char *dn = NULL;
            FOR_ATTR(a, NLMSG_DATA(m), m->nlmsg_len - NLMSG_HDRLEN) {
                int t = a->nla_type & NLA_TYPE_MASK;
                if (t == RDMA_NLDEV_ATTR_DEV_INDEX) memcpy(&di, (char *)a + NLA_HDRLEN, 4);
                if (t == RDMA_NLDEV_ATTR_DEV_NAME) dn = (char *)a + NLA_HDRLEN;
            }
            if (dn && di != UINT32_MAX && strcmp(dn, name) == 0) { *idx = di; found = 1; }
        }
    }
}

/* one STAT_GET of the port's default counter set; fills vals[] for the hw counters in C[] */
static int nl_query(uint64_t *vals) {
    char req[256] = {0};
    struct nlmsghdr *h = (struct nlmsghdr *)req;
    size_t off = NLMSG_HDRLEN;
    h->nlmsg_type = RDMA_NL_GET_TYPE(RDMA_NL_NLDEV, RDMA_NLDEV_CMD_STAT_GET);
    h->nlmsg_flags = NLM_F_REQUEST | NLM_F_ACK;
    h->nlmsg_seq = t_seq++;
    put_u32_attr(req, &off, RDMA_NLDEV_ATTR_DEV_INDEX, g_devidx);
    put_u32_attr(req, &off, RDMA_NLDEV_ATTR_PORT_INDEX, (uint32_t)g_port);
    h->nlmsg_len = (uint32_t)off;
    if (send(t_nl, req, off, 0) < 0) return -1;
    static __thread char rbuf[1 << 16];
    int got = 0, acked = 0;
    while (!acked) {
        ssize_t n = recv(t_nl, rbuf, sizeof(rbuf), 0);
        if (n < 0) { if (errno == EINTR) continue; return -1; }
        for (struct nlmsghdr *m = (struct nlmsghdr *)rbuf; NLMSG_OK(m, (size_t)n); m = NLMSG_NEXT(m, n)) {
            if (m->nlmsg_type == NLMSG_ERROR) {
                struct nlmsgerr *e = NLMSG_DATA(m);
                if (e->error) { fprintf(stderr, "nl stat get: %s\n", strerror(-e->error)); return -1; }
                acked = 1; continue;
            }
            if (m->nlmsg_type == NLMSG_DONE) { acked = 1; continue; }
            FOR_ATTR(a, NLMSG_DATA(m), m->nlmsg_len - NLMSG_HDRLEN) {
                if ((a->nla_type & NLA_TYPE_MASK) != RDMA_NLDEV_ATTR_STAT_HWCOUNTERS) continue;
                FOR_ATTR(e, (char *)a + NLA_HDRLEN, a->nla_len - NLA_HDRLEN) {
                    const char *nm = NULL; uint64_t v = 0; int hv = 0;
                    FOR_ATTR(f, (char *)e + NLA_HDRLEN, e->nla_len - NLA_HDRLEN) {
                        int t = f->nla_type & NLA_TYPE_MASK;
                        if (t == RDMA_NLDEV_ATTR_STAT_HWCOUNTER_ENTRY_NAME) nm = (char *)f + NLA_HDRLEN;
                        if (t == RDMA_NLDEV_ATTR_STAT_HWCOUNTER_ENTRY_VALUE) { memcpy(&v, (char *)f + NLA_HDRLEN, 8); hv = 1; }
                    }
                    if (!nm || !hv) continue;
                    for (int i = 0; i < NC; i++)
                        if (!C[i].is_port && strcmp(C[i].name, nm) == 0) { vals[i] = v; got++; }
                }
            }
        }
    }
    return got == n_hw ? 0 : -1;
}

static int sysfs_read(int fd, uint64_t *v) {
    char b[64];
    ssize_t n = pread(fd, b, sizeof(b) - 1, 0);
    if (n <= 0) return -1;
    b[n] = 0;
    *v = strtoull(b, NULL, 10);
    return 0;
}

/* read every selected counter once: one netlink query for all hw counters, then each sysfs
 * port counter. Per-counter read brackets go to ta_p/tb_p (optional). 0 on success. */
static int read_all(uint64_t *vals, uint64_t *ta_hw, uint64_t *tb_hw, uint64_t *ta_p, uint64_t *tb_p) {
    uint64_t a = now_ns();
    int rc = n_hw ? nl_query(vals) : 0;
    uint64_t b = now_ns();
    if (ta_hw) *ta_hw = a;
    if (tb_hw) *tb_hw = b;
    for (int i = 0; i < NC; i++) {
        if (!C[i].is_port) { if (ta_p) ta_p[i] = a; if (tb_p) tb_p[i] = b; continue; }
        uint64_t x = now_ns();
        if (sysfs_read(C[i].fd, &vals[i])) rc = -1;
        uint64_t y = now_ns();
        if (ta_p) ta_p[i] = x;
        if (tb_p) tb_p[i] = y;
    }
    return rc;
}

static void *sampler(void *arg) {
    (void)arg;
    if (s_cpu >= 0) pin_to_cpu(s_cpu);
    uint64_t vals[MAXC], ta[MAXC], tb[MAXC];
    int nlfd_ok = 1;
    if (n_hw && (t_nl = nl_open()) < 0) { fprintf(stderr, "sampler: netlink open failed\n"); return NULL; }
    while (!atomic_load(&s_quit)) {
        if (!atomic_load(&s_active)) {
            for (int i = 0; i < NC; i++) C[i].have = 0;
            atomic_store(&s_idle_ack, 1);
            usleep(200);
            continue;
        }
        atomic_store(&s_idle_ack, 0);
        uint64_t r0 = now_ns();
        if (read_all(vals, NULL, NULL, ta, tb)) { if (nlfd_ok) fprintf(stderr, "sampler: counter read failed\n"); nlfd_ok = 0; }
        int tr = atomic_load(&s_trial);
        for (int i = 0; i < NC; i++) {
            if (C[i].have && vals[i] != C[i].last) {
                long k = atomic_fetch_add(&nev, 1);
                if (k < MAXEV) EV[k] = (ev_t){ tr, i, C[i].last_ta, tb[i], C[i].last, vals[i] };
            }
            C[i].last = vals[i]; C[i].last_ta = ta[i]; C[i].have = 1;
        }
        uint64_t r1 = now_ns(), d = r1 - r0;
        atomic_fetch_add(&s_rounds, 1);
        atomic_fetch_add(&s_sumround, d);
        uint64_t mx = atomic_load(&s_maxround);
        while (d > mx && !atomic_compare_exchange_weak(&s_maxround, &mx, d)) {}
        if (s_sleep_us > 0) usleep((useconds_t)s_sleep_us);
    }
    return NULL;
}

static void sampler_stop_round(void) {
    atomic_store(&s_active, 0);
    for (int i = 0; i < 20000 && !atomic_load(&s_idle_ack); i++) usleep(100);
}

/* ---------------- QP helpers ---------------- */
static int to_rts_T(probe_ep_t *ep, uint32_t psn, int T, int R) {
    struct ibv_qp_attr a = {0};
    a.qp_state = IBV_QPS_RTS;
    a.timeout = (uint8_t)T;
    a.retry_cnt = (uint8_t)R;
    a.rnr_retry = 6;
    a.sq_psn = psn;
    a.max_rd_atomic = 1;
    int flags = IBV_QP_STATE | IBV_QP_TIMEOUT | IBV_QP_RETRY_CNT | IBV_QP_RNR_RETRY |
                IBV_QP_SQ_PSN | IBV_QP_MAX_QP_RD_ATOMIC;
    if (ibv_modify_qp(ep->qp, &a, flags)) { perror("modify->RTS"); return -1; }
    return 0;
}

static int query_timeout_retry(probe_ep_t *ep, int *T, int *R) {
    struct ibv_qp_attr a; struct ibv_qp_init_attr ia;
    if (ibv_query_qp(ep->qp, &a, IBV_QP_TIMEOUT | IBV_QP_RETRY_CNT, &ia)) return -1;
    *T = a.timeout; *R = a.retry_cnt;
    return 0;
}

static int connect_qp(probe_ep_t *ep, int fd, int is_server, int T, int R, probe_dest_t *rem) {
    if (ep_create_qp(ep) || ep_to_init(ep)) return -1;
    uint32_t psn = (uint32_t)(lrand48() & 0xffffff);
    probe_dest_t me;
    ep_fill_dest(ep, psn, &me);
    if (is_server) {
        if (tcp_recv_all(fd, rem, sizeof(*rem)) || tcp_send_all(fd, &me, sizeof(me))) return -1;
    } else {
        if (tcp_send_all(fd, &me, sizeof(me)) || tcp_recv_all(fd, rem, sizeof(*rem))) return -1;
    }
    if (ep_to_rtr(ep, rem)) return -1;
    if (is_server) return ep_to_rts(ep, psn);
    return to_rts_T(ep, psn, T, R);
}

/* ---------------- responder ---------------- */
static int run_server(const char *dev, int gid, int port) {
    probe_ep_t ep;
    if (ep_open(&ep, dev, (uint8_t)g_port, gid, 1u << 20)) return 1;
    int lfd = tcp_server_listen(port);
    if (lfd < 0) return 1;
    fprintf(stderr, "[ackt-srv] listening on %d dev %s gid %d\n", port, dev, gid);
    int fd = tcp_server_accept(lfd);
    if (fd < 0) return 1;
    char line[256];
    int rc = 0;
    for (;;) {
        int n = ctrl_recv_line(fd, line, sizeof(line));
        if (n < 0) { fprintf(stderr, "[ackt-srv] peer closed\n"); break; }
        if (!strcmp(line, "QP")) {
            probe_dest_t rem;
            if (connect_qp(&ep, fd, 1, 0, 0, &rem)) { rc = 1; break; }
        } else if (!strcmp(line, "ERR")) {
            int e = ep_to_err(&ep);
            char r[64];
            snprintf(r, sizeof(r), "ERRD %d %d", e, (int)ep_qp_state(&ep));
            if (ctrl_send_line(fd, r)) { rc = 1; break; }
        } else if (!strcmp(line, "DESTROY")) {
            ep_destroy_qp(&ep);
            if (ctrl_send_line(fd, "OK")) { rc = 1; break; }
        } else if (!strcmp(line, "BYE")) {
            break;
        } else {
            fprintf(stderr, "[ackt-srv] unknown line '%s'\n", line);
            rc = 1; break;
        }
    }
    close(fd); close(lfd);
    ep_close(&ep);
    return rc;
}

/* ---------------- requester ---------------- */
static void usage(const char *p) {
    fprintf(stderr,
        "usage: %s -S -d dev -g gid -p port                      (responder)\n"
        "       %s -c host -p port -d dev -g gid -T t -R r -n N -o trials.csv -e events.csv\n"
        "          [-L label] [-K c1,c2,@portctr] [-W cap_ms] [-Q quiet_ms] [-A tail_ms]\n"
        "          [-C cpu] [-X sampler_cpu] [-N] [-I sampler_sleep_us]\n"
        "       %s -M ms -d dev [-K ...]                            (counter monitor only)\n", p, p, p);
}

int main(int argc, char **argv) {
    int server = 0, gid = -1, ctrl_port = 18591, T = 14, R = 7, n = 5, cpu = -1, nosampler = 0;
    const char *host = NULL, *out = NULL, *evout = NULL, *label = "run";
    const char *klist = "local_ack_timeout_err,roce_adp_retrans,roce_adp_retrans_to,roce_slow_restart,"
                        "roce_slow_restart_trans,packet_seq_err,out_of_sequence,implied_nak_seq_err,"
                        "duplicate_request,req_cqe_error,@port_xmit_packets,@port_rcv_packets";
    long cap_ms = 120000, quiet_ms = 300, tail_ms = 60, mon_ms = 0;
    int opt;
    while ((opt = getopt(argc, argv, "Sc:p:d:g:i:T:R:n:o:e:L:K:W:Q:A:C:X:NI:M:h")) != -1) {
        switch (opt) {
            case 'S': server = 1; break;
            case 'c': host = optarg; break;
            case 'p': ctrl_port = atoi(optarg); break;
            case 'd': g_dev = optarg; break;
            case 'g': gid = atoi(optarg); break;
            case 'i': g_port = atoi(optarg); break;
            case 'T': T = atoi(optarg); break;
            case 'R': R = atoi(optarg); break;
            case 'n': n = atoi(optarg); break;
            case 'o': out = optarg; break;
            case 'e': evout = optarg; break;
            case 'L': label = optarg; break;
            case 'K': klist = optarg; break;
            case 'W': cap_ms = atol(optarg); break;
            case 'Q': quiet_ms = atol(optarg); break;
            case 'A': tail_ms = atol(optarg); break;
            case 'C': cpu = atoi(optarg); break;
            case 'X': s_cpu = atoi(optarg); break;
            case 'N': nosampler = 1; break;
            case 'I': s_sleep_us = atol(optarg); break;
            case 'M': mon_ms = atol(optarg); break;
            default: usage(argv[0]); return 2;
        }
    }
    if (!g_dev || gid < 0) { usage(argv[0]); return 2; }
    srand48((long)now_ns() ^ getpid());
    if (server) return run_server(g_dev, gid, ctrl_port);
    if (mon_ms <= 0 && (!host || !out || !evout)) { usage(argv[0]); return 2; }
    if (T < 0 || T > 31 || R < 0 || R > 7 || n < 1) { usage(argv[0]); return 2; }
    pin_to_cpu(cpu);

    /* counters */
    char kbuf[1024];
    snprintf(kbuf, sizeof(kbuf), "%s", klist);
    for (char *s = strtok(kbuf, ","); s && NC < MAXC; s = strtok(NULL, ",")) {
        ctr_t *c = &C[NC];
        memset(c, 0, sizeof(*c));
        c->fd = -1;
        if (s[0] == '@') {
            c->is_port = 1;
            snprintf(c->name, sizeof(c->name), "%s", s + 1);
            char path[256];
            snprintf(path, sizeof(path), "/sys/class/infiniband/%s/ports/%d/counters/%s", g_dev, g_port, c->name);
            c->fd = open(path, O_RDONLY | O_CLOEXEC);
            if (c->fd < 0) { fprintf(stderr, "open %s: %s\n", path, strerror(errno)); return 1; }
        } else {
            snprintf(c->name, sizeof(c->name), "%s", s);
            n_hw++;
        }
        NC++;
    }
    if (n_hw) {
        t_nl = nl_open();
        if (t_nl < 0 || nl_find_dev(g_dev, &g_devidx)) { fprintf(stderr, "netlink: device %s not found\n", g_dev); return 1; }
    }
    uint64_t v0[MAXC];
    if (read_all(v0, NULL, NULL, NULL, NULL)) { fprintf(stderr, "initial counter read failed (name typo?)\n"); return 1; }

    EV = calloc(MAXEV, sizeof(ev_t));
    if (!EV) { perror("calloc"); return 1; }

    if (mon_ms > 0) {   /* monitor only: sample for mon_ms, print rounds and every change */
        pthread_t mt;
        atomic_store(&s_trial, 0);
        atomic_store(&s_active, 1);
        uint64_t m0 = now_ns();
        if (pthread_create(&mt, NULL, sampler, NULL)) { perror("pthread_create"); return 1; }
        usleep((useconds_t)(mon_ms * 1000));
        sampler_stop_round();
        atomic_store(&s_quit, 1);
        pthread_join(mt, NULL);
        unsigned long rounds = atomic_load(&s_rounds);
        printf("monitor %ld ms: rounds %lu mean_round_us %.1f max_round_us %.1f events %ld\n", mon_ms, rounds,
               rounds ? (double)atomic_load(&s_sumround) / rounds / 1000.0 : 0, atomic_load(&s_maxround) / 1000.0,
               (long)atomic_load(&nev));
        for (long k = 0; k < atomic_load(&nev) && k < MAXEV; k++)
            printf("  %s at %.3f..%.3f ms: %llu -> %llu\n", C[EV[k].c].name, (EV[k].lo - m0) / 1e6, (EV[k].hi - m0) / 1e6,
                   (unsigned long long)EV[k].oldv, (unsigned long long)EV[k].newv);
        return 0;
    }

    probe_ep_t ep;
    if (ep_open(&ep, g_dev, (uint8_t)g_port, gid, 1u << 20)) return 1;
    int fd = tcp_client_connect(host, ctrl_port);
    if (fd < 0) return 1;

    FILE *fo = fopen(out, "a");
    if (!fo) { perror(out); return 1; }
    fseek(fo, 0, SEEK_END);
    if (ftell(fo) == 0) {
        fprintf(fo, "label,trial,T,R,T_q,R_q,nominal_us,t0_abs_ns,detect_ns,status,status_name,vendor_err,qp_state_after,"
                    "warm_ok,sampler,rounds,mean_round_us,max_round_us,quiet_ms");
        for (int i = 0; i < NC; i++) fprintf(fo, ",bg_%s", C[i].name);
        for (int i = 0; i < NC; i++) fprintf(fo, ",d_%s", C[i].name);
        fprintf(fo, "\n");
    }

    pthread_t th;
    if (!nosampler && pthread_create(&th, NULL, sampler, NULL)) { perror("pthread_create"); return 1; }

    int rc = 0;
    double nominal_us = 4.096 * (double)(1ull << T);
    for (int t = 1; t <= n; t++) {
        char line[256];
        probe_dest_t rem;
        if (ctrl_send_line(fd, "QP") || connect_qp(&ep, fd, 0, T, R, &rem)) { rc = 1; break; }
        int Tq = -1, Rq = -1;
        query_timeout_retry(&ep, &Tq, &Rq);
        /* warm-up write: path must work before the fault */
        struct ibv_wc wc;
        int warm_ok = 0;
        if (post_write(&ep, 1, WRITE_LEN, rem.addr, rem.rkey, true) == 0 &&
            poll_one(&ep, &wc, 2000) == 1 && wc.status == IBV_WC_SUCCESS) warm_ok = 1;
        if (!warm_ok) fprintf(stderr, "[ackt] trial %d: warm-up write failed\n", t);

        uint64_t A[MAXC], B[MAXC], Cv[MAXC];
        read_all(A, NULL, NULL, NULL, NULL);
        atomic_store(&s_trial, t);
        atomic_store(&s_rounds, 0); atomic_store(&s_maxround, 0); atomic_store(&s_sumround, 0);
        atomic_store(&s_active, nosampler ? 0 : 1);
        usleep((useconds_t)(quiet_ms * 1000));
        read_all(B, NULL, NULL, NULL, NULL);

        if (ctrl_send_line(fd, "ERR") || ctrl_recv_line(fd, line, sizeof(line)) < 0 || strncmp(line, "ERRD 0", 6)) {
            fprintf(stderr, "[ackt] trial %d: responder ERR failed: '%s'\n", t, line);
            rc = 1; break;
        }
        uint64_t t0 = now_ns();
        if (post_write(&ep, 2, WRITE_LEN, rem.addr, rem.rkey, true)) { rc = 1; break; }
        int got = poll_one(&ep, &wc, cap_ms);
        uint64_t t1 = now_ns();
        usleep((useconds_t)(tail_ms * 1000));
        if (!nosampler) sampler_stop_round();
        read_all(Cv, NULL, NULL, NULL, NULL);
        int qs = (int)ep_qp_state(&ep);
        long long det = (got == 1) ? (long long)(t1 - t0) : -1;
        int st = (got == 1) ? (int)wc.status : -1;
        unsigned ve = (got == 1) ? wc.vendor_err : 0;
        unsigned long rounds = atomic_load(&s_rounds);
        double mean_r = rounds ? (double)atomic_load(&s_sumround) / rounds / 1000.0 : 0;
        fprintf(fo, "%s,%d,%d,%d,%d,%d,%.3f,%llu,%lld,%d,%s,0x%x,%d,%d,%d,%lu,%.1f,%.1f,%ld",
                label, t, T, R, Tq, Rq, nominal_us, (unsigned long long)t0, det, st,
                st >= 0 ? ibv_wc_status_str((enum ibv_wc_status)st) : "none", ve, qs, warm_ok,
                !nosampler, rounds, mean_r, atomic_load(&s_maxround) / 1000.0, quiet_ms);
        for (int i = 0; i < NC; i++) fprintf(fo, ",%lld", (long long)(B[i] - A[i]));
        for (int i = 0; i < NC; i++) fprintf(fo, ",%lld", (long long)(Cv[i] - B[i]));
        fprintf(fo, "\n");
        fflush(fo);
        /* events of this trial, relative to t0 */
        fprintf(stderr, "[ackt] %s T=%d R=%d trial %d: detect %.3f ms status %d vendor 0x%x d_timeout=%lld\n",
                label, T, R, t, det / 1e6, st, ve, (long long)(Cv[0] - B[0]));
        /* stash t0 per trial via a sentinel event (c = -1) */
        long k = atomic_fetch_add(&nev, 1);
        if (k < MAXEV) EV[k] = (ev_t){ t, -1, t0, t1, (uint64_t)det, 0 };

        if (ctrl_send_line(fd, "DESTROY") || ctrl_recv_line(fd, line, sizeof(line)) < 0) { rc = 1; break; }
        ep_destroy_qp(&ep);
    }
    ctrl_send_line(fd, "BYE");
    if (!nosampler) { atomic_store(&s_quit, 1); pthread_join(th, NULL); }
    fclose(fo);

    /* events: rows relative to the owning trial's t0 */
    long ne = atomic_load(&nev);
    if (ne > MAXEV) { fprintf(stderr, "warning: %ld events dropped\n", ne - MAXEV); ne = MAXEV; }
    uint64_t t0s[4096] = {0};
    for (long k = 0; k < ne; k++) if (EV[k].c == -1 && EV[k].trial < 4096) t0s[EV[k].trial] = EV[k].lo;
    FILE *fe = fopen(evout, "a");
    if (!fe) { perror(evout); return 1; }
    fseek(fe, 0, SEEK_END);
    if (ftell(fe) == 0) fprintf(fe, "label,T,R,trial,counter,lo_us,hi_us,mid_us,old,new\n");
    for (long k = 0; k < ne; k++) {
        if (EV[k].c < 0) continue;
        int tr = EV[k].trial;
        uint64_t base = (tr > 0 && tr < 4096) ? t0s[tr] : 0;
        double lo = ((double)EV[k].lo - (double)base) / 1000.0, hi = ((double)EV[k].hi - (double)base) / 1000.0;
        fprintf(fe, "%s,%d,%d,%d,%s,%.1f,%.1f,%.1f,%llu,%llu\n", label, T, R, tr, C[EV[k].c].name,
                lo, hi, (lo + hi) / 2, (unsigned long long)EV[k].oldv, (unsigned long long)EV[k].newv);
    }
    fclose(fe);
    close(fd);
    ep_close(&ep);
    return rc;
}
