/*
 * client.c - Instrumented retry decomposition client
 *
 * Based on experiment4/client.c (kill mode only).
 * Adds per-CQE timestamp ring buffer to decompose the 3.7s detection
 * latency into: (t1-t0) server-alive window + (t2-t1) HCA retry wait.
 *
 * Timestamps (CLOCK_MONOTONIC, ns):
 *   t0: just before sending INJECT_NOW(KILL)
 *   t1: last successful CQE polled
 *   t2: first error CQE polled
 *
 * Ring buffer records last CQE_RING_SIZE successful CQE timestamps
 * to show write completion cadence leading up to the error.
 */

#include <sys/stat.h>
#include "rdma_common.h"

#define WRITE_TIMEOUT_SEC 30
#define CQE_RING_SIZE     100

typedef struct {
    uint64_t ts[CQE_RING_SIZE];
    int      head;
    int      count;
} cqe_ring_t;

static void ring_init(cqe_ring_t *r) {
    memset(r, 0, sizeof(*r));
}

static void ring_push(cqe_ring_t *r, uint64_t ts) {
    r->ts[r->head] = ts;
    r->head = (r->head + 1) % CQE_RING_SIZE;
    if (r->count < CQE_RING_SIZE) r->count++;
}

static uint64_t ring_get(const cqe_ring_t *r, int idx) {
    int pos = (r->head - r->count + idx + CQE_RING_SIZE) % CQE_RING_SIZE;
    return r->ts[pos];
}

typedef struct {
    char       server_ip[64];
    char       dev_name[32];
    int        ib_port;
    int        gid_index;
    int        ctrl_port;
    int        qp_timeout;
    int        qp_retry_cnt;
    int        qp_rnr_retry;
    int        iterations;
    char       output_file[256];
} client_config_t;

static volatile sig_atomic_t g_stop = 0;
static void sigint_handler(int sig) { (void)sig; g_stop = 1; }

/* ---------------------------------------------------------------- */
static int tcp_connect(const char *server_ip, int port)
{
    int sockfd = socket(AF_INET, SOCK_STREAM, 0);
    if (sockfd < 0) { LOG_ERR("socket: %s", strerror(errno)); return -1; }
    int flag = 1;
    setsockopt(sockfd, IPPROTO_TCP, TCP_NODELAY, &flag, sizeof(flag));
    struct timeval tv = { .tv_sec = TCP_TIMEOUT_SEC, .tv_usec = 0 };
    setsockopt(sockfd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    setsockopt(sockfd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));

    struct sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port = htons(port);
    if (inet_pton(AF_INET, server_ip, &addr.sin_addr) != 1) {
        close(sockfd); return -1;
    }
    if (connect(sockfd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        LOG_ERR("connect: %s", strerror(errno));
        close(sockfd); return -1;
    }
    return sockfd;
}

/* ---------------------------------------------------------------- */
static int connect_qp_custom(rdma_ctx_t *rctx, const qp_info_t *remote,
                             int qp_timeout, int qp_retry_cnt, int qp_rnr_retry)
{
    int ret;
    struct ibv_qp_attr attr;
    int flags;

    rctx->remote_info = *remote;

    memset(&attr, 0, sizeof(attr));
    attr.qp_state        = IBV_QPS_INIT;
    attr.pkey_index      = 0;
    attr.port_num        = rctx->ib_port;
    attr.qp_access_flags = IBV_ACCESS_REMOTE_WRITE |
                           IBV_ACCESS_REMOTE_READ |
                           IBV_ACCESS_LOCAL_WRITE;
    flags = IBV_QP_STATE | IBV_QP_PKEY_INDEX | IBV_QP_PORT | IBV_QP_ACCESS_FLAGS;
    ret = ibv_modify_qp(rctx->qp, &attr, flags);
    CHECK(ret == 0, "RESET->INIT: %s", strerror(errno));

    memset(&attr, 0, sizeof(attr));
    attr.qp_state           = IBV_QPS_RTR;
    attr.path_mtu           = IBV_MTU_1024;
    attr.dest_qp_num        = remote->qpn;
    attr.rq_psn             = remote->psn;
    attr.max_dest_rd_atomic = 1;
    attr.min_rnr_timer      = 12;
    attr.ah_attr.is_global  = 1;
    attr.ah_attr.port_num   = rctx->ib_port;
    attr.ah_attr.sl         = 0;
    memcpy(attr.ah_attr.grh.dgid.raw, remote->gid, 16);
    attr.ah_attr.grh.sgid_index    = rctx->gid_index;
    attr.ah_attr.grh.hop_limit     = 64;
    flags = IBV_QP_STATE | IBV_QP_AV | IBV_QP_PATH_MTU |
            IBV_QP_DEST_QPN | IBV_QP_RQ_PSN |
            IBV_QP_MAX_DEST_RD_ATOMIC | IBV_QP_MIN_RNR_TIMER;
    ret = ibv_modify_qp(rctx->qp, &attr, flags);
    CHECK(ret == 0, "INIT->RTR: %s", strerror(errno));

    memset(&attr, 0, sizeof(attr));
    attr.qp_state      = IBV_QPS_RTS;
    attr.sq_psn        = rctx->local_psn;
    attr.timeout       = qp_timeout;
    attr.retry_cnt     = qp_retry_cnt;
    attr.rnr_retry     = qp_rnr_retry;
    attr.max_rd_atomic = 1;
    flags = IBV_QP_STATE | IBV_QP_SQ_PSN | IBV_QP_TIMEOUT |
            IBV_QP_RETRY_CNT | IBV_QP_RNR_RETRY | IBV_QP_MAX_QP_RD_ATOMIC;
    ret = ibv_modify_qp(rctx->qp, &attr, flags);
    CHECK(ret == 0, "RTR->RTS: %s", strerror(errno));

    LOG_INFO("QP RTS (timeout=%d retry_cnt=%d) -> remote QPN 0x%x",
             qp_timeout, qp_retry_cnt, remote->qpn);
    return 0;
}

/* ---------------------------------------------------------------- */
static int exchange_and_connect(int ctrl_fd, rdma_ctx_t *rctx,
                                int qp_timeout, int qp_retry_cnt,
                                int qp_rnr_retry)
{
    ctrl_msg_t msg;
    qp_info_t local_info;
    rdma_get_local_info(rctx, &local_info);

    memset(&msg, 0, sizeof(msg));
    msg.type = MSG_EXCHANGE_QP_INFO;
    msg.qp_info = local_info;
    if (send_ctrl_msg(ctrl_fd, &msg) != 0) return -1;
    if (recv_ctrl_msg(ctrl_fd, &msg) != 0 || msg.type != MSG_EXCHANGE_QP_INFO)
        return -1;

    if (connect_qp_custom(rctx, &msg.qp_info,
                          qp_timeout, qp_retry_cnt, qp_rnr_retry) != 0)
        return -1;

    memset(&msg, 0, sizeof(msg));
    msg.type = MSG_READY;
    if (send_ctrl_msg(ctrl_fd, &msg) != 0) return -1;
    if (recv_ctrl_msg(ctrl_fd, &msg) != 0 || msg.type != MSG_READY) return -1;
    return 0;
}

/* ----------------------------------------------------------------
 * Instrumented kill iteration
 *
 * Records t0 (inject), t1 (last success CQE), t2 (first error CQE)
 * and a ring buffer of all successful CQE timestamps.
 * ---------------------------------------------------------------- */
static int run_kill_one(client_config_t *cfg, int iter, FILE *csv_fp)
{
    int ctrl_fd = -1;
    rdma_ctx_t rctx;
    bool rdma_ok = false;
    int rc = -1;

    for (int r = 0; r < 5; r++) {
        ctrl_fd = tcp_connect(cfg->server_ip, cfg->ctrl_port);
        if (ctrl_fd >= 0) break;
        sleep(2);
    }
    if (ctrl_fd < 0) { LOG_ERR("kill[%d]: TCP failed", iter); return -1; }

    if (rdma_init_ctx(&rctx, cfg->dev_name, cfg->ib_port,
                      cfg->gid_index, RDMA_BUF_SIZE) != 0) goto out;
    rdma_ok = true;
    if (rdma_create_qp(&rctx) != 0) goto out;
    if (exchange_and_connect(ctrl_fd, &rctx,
                             cfg->qp_timeout, cfg->qp_retry_cnt,
                             cfg->qp_rnr_retry) != 0) goto out;

    /* Warmup */
    {
        uint64_t wr_id = 0;
        for (int i = 0; i < 16; i++)
            if (rdma_post_write(&rctx, (i % 8 == 0), wr_id++) != 0) goto out;
        struct ibv_wc wc;
        int drained = 0;
        uint64_t dl = get_time_ns() + 2000000000ULL;
        while (drained < 2 && get_time_ns() < dl) {
            int ne = rdma_poll_cq(&rctx, &wc, 1);
            if (ne <= 0) continue;
            if (wc.status != IBV_WC_SUCCESS) goto out;
            drained++;
        }
    }

    /* Pre-inject burst */
    uint64_t wr_id = 1000;
    int outstanding = 0;
    for (int i = 0; i < SIGNAL_INTERVAL * 4; i++) {
        bool sig = (i % SIGNAL_INTERVAL == 0);
        if (rdma_post_write(&rctx, sig, wr_id++) != 0) goto out;
        if (sig) outstanding++;
    }

    /* ---- t0: INJECT ---- */
    ctrl_msg_t inject_msg;
    memset(&inject_msg, 0, sizeof(inject_msg));
    inject_msg.type = MSG_INJECT_NOW;
    inject_msg.fault_type = FAULT_KILL;
    inject_msg.iteration = iter;

    uint64_t t0 = get_time_ns();
    if (send_ctrl_msg(ctrl_fd, &inject_msg) != 0) goto out;

    /* Try ACK */
    uint64_t t_ack = 0;
    {
        struct pollfd pfd = { .fd = ctrl_fd, .events = POLLIN };
        if (poll(&pfd, 1, 200) > 0 && (pfd.revents & POLLIN)) {
            ctrl_msg_t ack;
            if (recv_ctrl_msg(ctrl_fd, &ack) == 0 && ack.type == MSG_INJECT_ACK)
                t_ack = get_time_ns();
        }
    }

    /* ---- Tight-poll with instrumentation ---- */
    cqe_ring_t ring;
    ring_init(&ring);
    uint64_t t1 = 0;  /* last successful CQE */
    uint64_t t2 = 0;  /* first error CQE */
    int success_count = 0;
    int wc_status = -1;
    int writes_since_signal = 0;
    uint64_t deadline_ns = t0 + (uint64_t)WRITE_TIMEOUT_SEC * 1000000000ULL;

    while (t2 == 0 && !g_stop) {
        if (get_time_ns() > deadline_ns) {
            LOG_WARN("kill[%d]: timeout", iter);
            break;
        }

        struct ibv_wc wc;
        int ne = rdma_poll_cq(&rctx, &wc, 1);
        if (ne > 0) {
            uint64_t now = get_time_ns();
            if (wc.status == IBV_WC_SUCCESS) {
                ring_push(&ring, now);
                t1 = now;
                success_count++;
                if (outstanding > 0) outstanding--;
            } else {
                t2 = now;
                wc_status = wc.status;
            }
        }

        if (t2 == 0 && outstanding < (MAX_SEND_WR / SIGNAL_INTERVAL) - 2) {
            writes_since_signal++;
            bool sig = (writes_since_signal >= SIGNAL_INTERVAL);
            if (sig) writes_since_signal = 0;
            if (rdma_post_write(&rctx, sig, wr_id++) == 0) {
                if (sig) outstanding++;
            }
        }
    }

    if (t2 > 0) {
        uint64_t t_fault_est = (t_ack > t0) ? t0 + (t_ack - t0) / 2 : t0;

        /* Compat line for run_experiment.sh stderr parser */
        LOG_INFO("kill[%d]: detect=%.1fms status=%d",
                 iter, ns_to_ms(t2 - t0), wc_status);

        LOG_INFO("kill[%d] R=%d T=%d: DECOMPOSITION", iter,
                 cfg->qp_retry_cnt, cfg->qp_timeout);
        LOG_INFO("  t0 (inject):     %llu", (unsigned long long)t0);
        LOG_INFO("  t_ack:           %llu (+%.3f ms)",
                 (unsigned long long)t_ack, t_ack > 0 ? ns_to_ms(t_ack - t0) : 0.0);
        LOG_INFO("  t1 (last ok):    %llu (+%.3f ms from t0)",
                 (unsigned long long)t1, ns_to_ms(t1 - t0));
        LOG_INFO("  t2 (first err):  %llu (+%.3f ms from t0)",
                 (unsigned long long)t2, ns_to_ms(t2 - t0));
        LOG_INFO("  ---");
        LOG_INFO("  t1 - t0 = %.3f ms  (server QP alive window)",
                 ns_to_ms(t1 - t0));
        LOG_INFO("  t2 - t1 = %.3f ms  (HCA retry wait)",
                 ns_to_ms(t2 - t1));
        LOG_INFO("  t2 - t0 = %.3f ms  (total detection)",
                 ns_to_ms(t2 - t0));
        LOG_INFO("  t2 - t_fault_est = %.3f ms  (adjusted)",
                 ns_to_ms(t2 - t_fault_est));
        LOG_INFO("  success CQEs after inject: %d", success_count);
        LOG_INFO("  error status: %d (%s)", wc_status,
                 ibv_wc_status_str(wc_status));

        /* Dump last 20 CQE intervals */
        int n = ring.count < 20 ? ring.count : 20;
        if (n > 1) {
            LOG_INFO("  --- Last %d successful CQE intervals ---", n);
            for (int i = 1; i < n; i++) {
                uint64_t prev = ring_get(&ring, ring.count - n + i - 1);
                uint64_t curr = ring_get(&ring, ring.count - n + i);
                LOG_INFO("  cqe[-%d] delta=%.3f us",
                         n - i, ns_to_us(curr - prev));
            }
        }

        /* CSV output */
        if (csv_fp) {
            fprintf(csv_fp, "%d,%d,%d,%d,"
                    "%llu,%llu,%llu,%llu,"
                    "%.3f,%.3f,%.3f,"
                    "%d,%d,%d\n",
                    iter, cfg->qp_retry_cnt, cfg->qp_timeout, cfg->qp_rnr_retry,
                    (unsigned long long)t0, (unsigned long long)t_ack,
                    (unsigned long long)t1, (unsigned long long)t2,
                    ns_to_ms(t1 - t0), ns_to_ms(t2 - t1), ns_to_ms(t2 - t0),
                    success_count, wc_status, ring.count);
            fflush(csv_fp);
        }
        rc = 0;
    }

out:
    if (rdma_ok) rdma_destroy_ctx(&rctx);
    if (ctrl_fd >= 0) close(ctrl_fd);
    return rc;
}

/* ---------------------------------------------------------------- */
static void print_usage(const char *prog)
{
    fprintf(stderr,
        "Usage: %s -s <ip> [options]\n"
        "  -s <ip>     Server IP\n"
        "  -R <0..7>   retry_cnt (default 7)\n"
        "  -O <0..31>  qp_timeout (default 14)\n"
        "  -n <N>      iterations (default 5)\n"
        "  -d <dev>    IB device (default mlx5_0)\n"
        "  -i <port>   IB port (default 1)\n"
        "  -g <gid>    GID index (default 3)\n"
        "  -p <port>   TCP port (default %d)\n"
        "  -o <file>   CSV output (default results/decomp.csv)\n",
        prog, DEFAULT_CTRL_PORT);
}

static int parse_args(int argc, char **argv, client_config_t *cfg)
{
    memset(cfg, 0, sizeof(*cfg));
    strncpy(cfg->dev_name, DEFAULT_DEV_NAME, sizeof(cfg->dev_name) - 1);
    cfg->ib_port      = DEFAULT_IB_PORT;
    cfg->gid_index    = DEFAULT_GID_INDEX;
    cfg->ctrl_port    = DEFAULT_CTRL_PORT;
    cfg->qp_timeout   = 14;
    cfg->qp_retry_cnt = 7;
    cfg->qp_rnr_retry = 7;
    cfg->iterations   = 5;
    strncpy(cfg->output_file, "results/decomp.csv", sizeof(cfg->output_file) - 1);

    bool have_server = false;
    int opt;
    while ((opt = getopt(argc, argv, "s:R:O:n:d:i:g:p:o:h")) != -1) {
        switch (opt) {
        case 's': strncpy(cfg->server_ip, optarg, sizeof(cfg->server_ip)-1);
                  have_server = true; break;
        case 'R': cfg->qp_retry_cnt = atoi(optarg); break;
        case 'O': cfg->qp_timeout   = atoi(optarg); break;
        case 'n': cfg->iterations    = atoi(optarg); break;
        case 'd': strncpy(cfg->dev_name, optarg, sizeof(cfg->dev_name)-1); break;
        case 'i': cfg->ib_port   = atoi(optarg); break;
        case 'g': cfg->gid_index = atoi(optarg); break;
        case 'p': cfg->ctrl_port = atoi(optarg); break;
        case 'o': strncpy(cfg->output_file, optarg, sizeof(cfg->output_file)-1); break;
        case 'h': print_usage(argv[0]); exit(0);
        default:  print_usage(argv[0]); return -1;
        }
    }
    if (!have_server) { LOG_ERR("-s required"); return -1; }
    return 0;
}

/* ---------------------------------------------------------------- */
int main(int argc, char **argv)
{
    client_config_t cfg;
    if (parse_args(argc, argv, &cfg) != 0) return EXIT_FAILURE;

    struct sigaction sa;
    sa.sa_handler = sigint_handler;
    sigemptyset(&sa.sa_mask);
    sa.sa_flags = 0;
    sigaction(SIGINT, &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);

    LOG_INFO("Retry Decomposition: server=%s R=%d T=%d n=%d",
             cfg.server_ip, cfg.qp_retry_cnt, cfg.qp_timeout, cfg.iterations);

    mkdir("results", 0755);

    /* Append across (R,T) configs; write header only if file is new/empty. */
    bool need_header = true;
    {
        FILE *probe = fopen(cfg.output_file, "r");
        if (probe) {
            fseek(probe, 0, SEEK_END);
            if (ftell(probe) > 0) need_header = false;
            fclose(probe);
        }
    }
    FILE *csv_fp = fopen(cfg.output_file, "a");
    if (!csv_fp) LOG_FATAL("Cannot open %s", cfg.output_file);
    if (need_header) {
        fprintf(csv_fp, "iter,retry_cnt,qp_timeout,rnr_retry,"
                        "t0_ns,t_ack_ns,t1_ns,t2_ns,"
                        "t1_t0_ms,t2_t1_ms,t2_t0_ms,"
                        "success_after_inject,wc_status,ring_count\n");
    }

    for (int i = 0; i < cfg.iterations && !g_stop; i++) {
        run_kill_one(&cfg, i, csv_fp);
        sleep(1);
    }

    fclose(csv_fp);
    LOG_INFO("Results written to %s", cfg.output_file);
    return EXIT_SUCCESS;
}
