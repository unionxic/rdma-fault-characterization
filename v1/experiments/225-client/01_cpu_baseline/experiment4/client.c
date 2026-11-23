/*
 * client.c - NIC Retry Boundary Client (runs on Server A)
 *
 * Part of: GPU-Initiated RDMA Fault Recovery Research
 * Experiment 4: NIC Retry Coverage and Limits
 *
 * Sweeps over (retry_cnt, qp_timeout) parameters and characterizes
 * the boundary between (i) HCA-recoverable transient packet loss and
 * (ii) failures that exhaust retry budget.
 *
 * Modes:
 *   -M netem  : passive server. Caller (run_experiment.sh) applies
 *               tc netem on the client's RDMA NIC before invocation.
 *               This client posts N RDMA Writes back-to-back and
 *               records per-write success/error and latency.
 *   -M kill   : sends MSG_INJECT_NOW(KILL); server exits abruptly.
 *               Measures time to error CQE under the chosen retry
 *               configuration. Repeats N times via reconnection
 *               (server_loop.sh on the remote end).
 *
 * Output: a single per-config CSV aggregating all writes/iterations.
 */

#include "rdma_common.h"

#define WRITE_TIMEOUT_SEC 30

typedef enum {
    MODE_NETEM = 0,
    MODE_KILL  = 1,
} run_mode_t;

typedef struct {
    char       server_ip[64];
    char       dev_name[32];
    int        ib_port;
    int        gid_index;
    int        ctrl_port;

    /* Tunable QP parameters */
    int        qp_timeout;     /* IBA-encoded: 4.096us * 2^x */
    int        qp_retry_cnt;   /* 0..7 */
    int        qp_rnr_retry;   /* 0..7 */

    run_mode_t mode;
    int        iterations;     /* netem: writes per run; kill: reconnect cycles */
    int        loss_pct;       /* metadata only — netem applied externally */

    char       output_file[256];
} client_config_t;

typedef struct {
    int      ok_count;
    int      err_retry_exc;
    int      err_rnr_retry_exc;
    int      err_wr_flush;
    int      err_other;
    int      timed_out;
    uint64_t lat_sum_ns;
    uint64_t lat_min_ns;
    uint64_t lat_max_ns;
    uint64_t *lat_samples_ns;
    int      lat_count;
} agg_t;

static volatile sig_atomic_t g_stop = 0;

static void sigint_handler(int sig) { (void)sig; g_stop = 1; }

/* ---------------------------------------------------------------- */
static int tcp_connect(const char *server_ip, int port)
{
    int sockfd = socket(AF_INET, SOCK_STREAM, 0);
    if (sockfd < 0) {
        LOG_ERR("socket: %s", strerror(errno));
        return -1;
    }
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
        LOG_ERR("Invalid server IP: %s", server_ip);
        close(sockfd);
        return -1;
    }

    if (connect(sockfd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        LOG_ERR("connect: %s", strerror(errno));
        close(sockfd);
        return -1;
    }
    return sockfd;
}

/* ----------------------------------------------------------------
 * Custom QP setup that takes timeout/retry parameters as arguments.
 * Mirrors rdma_connect_qp() but parametrizes the RTR->RTS modify.
 * ---------------------------------------------------------------- */
static int connect_qp_custom(rdma_ctx_t *rctx, const qp_info_t *remote,
                             int qp_timeout, int qp_retry_cnt, int qp_rnr_retry)
{
    int ret;
    struct ibv_qp_attr attr;
    int flags;

    rctx->remote_info = *remote;

    /* RESET -> INIT */
    memset(&attr, 0, sizeof(attr));
    attr.qp_state        = IBV_QPS_INIT;
    attr.pkey_index      = 0;
    attr.port_num        = rctx->ib_port;
    attr.qp_access_flags = IBV_ACCESS_REMOTE_WRITE |
                           IBV_ACCESS_REMOTE_READ |
                           IBV_ACCESS_LOCAL_WRITE;
    flags = IBV_QP_STATE | IBV_QP_PKEY_INDEX | IBV_QP_PORT | IBV_QP_ACCESS_FLAGS;
    ret = ibv_modify_qp(rctx->qp, &attr, flags);
    CHECK(ret == 0, "RESET->INIT failed: %s", strerror(errno));

    /* INIT -> RTR */
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
    attr.ah_attr.grh.flow_label    = 0;
    attr.ah_attr.grh.traffic_class = 0;
    flags = IBV_QP_STATE | IBV_QP_AV | IBV_QP_PATH_MTU |
            IBV_QP_DEST_QPN | IBV_QP_RQ_PSN |
            IBV_QP_MAX_DEST_RD_ATOMIC | IBV_QP_MIN_RNR_TIMER;
    ret = ibv_modify_qp(rctx->qp, &attr, flags);
    CHECK(ret == 0, "INIT->RTR failed: %s", strerror(errno));

    /* RTR -> RTS with custom timeout/retry */
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
    CHECK(ret == 0, "RTR->RTS failed: %s", strerror(errno));

    LOG_INFO("QP RTS (timeout=%d retry_cnt=%d rnr_retry=%d) -> remote QPN 0x%x",
             qp_timeout, qp_retry_cnt, qp_rnr_retry, remote->qpn);
    return 0;
}

/* ---------------------------------------------------------------- */
static int exchange_qp_info_and_connect(int ctrl_fd, rdma_ctx_t *rctx,
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

    if (recv_ctrl_msg(ctrl_fd, &msg) != 0 || msg.type != MSG_EXCHANGE_QP_INFO) {
        LOG_ERR("Failed/unexpected QP info");
        return -1;
    }

    if (connect_qp_custom(rctx, &msg.qp_info,
                          qp_timeout, qp_retry_cnt, qp_rnr_retry) != 0) {
        return -1;
    }

    memset(&msg, 0, sizeof(msg));
    msg.type = MSG_READY;
    if (send_ctrl_msg(ctrl_fd, &msg) != 0) return -1;
    if (recv_ctrl_msg(ctrl_fd, &msg) != 0 || msg.type != MSG_READY) return -1;
    return 0;
}

/* ---------------------------------------------------------------- */
static void agg_init(agg_t *a, int reserve)
{
    memset(a, 0, sizeof(*a));
    a->lat_min_ns = (uint64_t)-1;
    a->lat_samples_ns = calloc(reserve > 0 ? reserve : 1, sizeof(uint64_t));
}

static void agg_record_ok(agg_t *a, uint64_t lat_ns)
{
    a->ok_count++;
    a->lat_sum_ns += lat_ns;
    if (lat_ns < a->lat_min_ns) a->lat_min_ns = lat_ns;
    if (lat_ns > a->lat_max_ns) a->lat_max_ns = lat_ns;
    a->lat_samples_ns[a->lat_count++] = lat_ns;
}

static void agg_record_err(agg_t *a, int wc_status)
{
    switch (wc_status) {
    case IBV_WC_RETRY_EXC_ERR:     a->err_retry_exc++;     break;
    case IBV_WC_RNR_RETRY_EXC_ERR: a->err_rnr_retry_exc++; break;
    case IBV_WC_WR_FLUSH_ERR:      a->err_wr_flush++;      break;
    default:                        a->err_other++;         break;
    }
}

static int cmp_u64(const void *a, const void *b)
{
    uint64_t va = *(const uint64_t *)a;
    uint64_t vb = *(const uint64_t *)b;
    if (va < vb) return -1;
    if (va > vb) return 1;
    return 0;
}

static void agg_finalize(agg_t *a, double *p50, double *p99)
{
    if (a->lat_count == 0) {
        *p50 = *p99 = 0.0;
        return;
    }
    qsort(a->lat_samples_ns, a->lat_count, sizeof(uint64_t), cmp_u64);
    *p50 = (double)a->lat_samples_ns[a->lat_count / 2];
    int p99_idx = (int)((double)(a->lat_count - 1) * 0.99);
    *p99 = (double)a->lat_samples_ns[p99_idx];
}

/* ----------------------------------------------------------------
 * netem mode: post N signaled writes one at a time, time each.
 * tc netem is applied externally before this function runs.
 * Each write is fully drained before the next is posted, so we
 * measure end-to-end latency including all retries.
 * ---------------------------------------------------------------- */
static int run_netem(rdma_ctx_t *rctx, int n_writes, agg_t *a)
{
    uint64_t wr_id = 0;
    for (int i = 0; i < n_writes && !g_stop; i++) {
        uint64_t t0 = get_time_ns();

        int post_ret = rdma_post_write(rctx, true, wr_id++);
        if (post_ret != 0) {
            /* QP may have entered ERR after a previous failure.
             * Count as flush/other and stop — once in ERR, every
             * subsequent post_send fails the same way. */
            agg_record_err(a, IBV_WC_WR_FLUSH_ERR);
            return 0;
        }

        /* Wait for completion */
        struct ibv_wc wc;
        uint64_t deadline = t0 + (uint64_t)WRITE_TIMEOUT_SEC * 1000000000ULL;
        bool got = false;
        while (!got && !g_stop) {
            if (get_time_ns() > deadline) {
                a->timed_out++;
                LOG_WARN("Write %d timed out", i);
                /* QP is likely stuck — abort run */
                return 0;
            }
            int ne = rdma_poll_cq(rctx, &wc, 1);
            if (ne < 0) return -1;
            if (ne == 0) continue;
            got = true;
        }
        if (!got) return 0;

        uint64_t t1 = get_time_ns();
        if (wc.status == IBV_WC_SUCCESS) {
            agg_record_ok(a, t1 - t0);
        } else {
            agg_record_err(a, wc.status);
            /* On error, QP goes to ERR. Subsequent posts will flush.
             * Stop; remaining "writes" are not meaningful. */
            return 0;
        }
    }
    return 0;
}

/* ----------------------------------------------------------------
 * kill mode: per iteration, fresh TCP+RDMA, send INJECT_KILL,
 * busy-poll for first error CQE, record latency.
 * Server restart handled externally (server_loop.sh).
 * ---------------------------------------------------------------- */
static int run_kill_one(client_config_t *cfg, agg_t *a, int iter)
{
    int ctrl_fd = -1;
    rdma_ctx_t rctx;
    bool rdma_init = false;
    int rc = -1;

    /* Retry connect — server may still be restarting from previous iter */
    int max_retries = 5;
    for (int r = 0; r < max_retries; r++) {
        ctrl_fd = tcp_connect(cfg->server_ip, cfg->ctrl_port);
        if (ctrl_fd >= 0) break;
        sleep(2);
    }
    if (ctrl_fd < 0) {
        LOG_ERR("kill[%d]: TCP connect failed", iter);
        return -1;
    }

    if (rdma_init_ctx(&rctx, cfg->dev_name, cfg->ib_port,
                      cfg->gid_index, RDMA_BUF_SIZE) != 0) goto cleanup;
    rdma_init = true;
    if (rdma_create_qp(&rctx) != 0) goto cleanup;
    if (exchange_qp_info_and_connect(ctrl_fd, &rctx,
                                     cfg->qp_timeout, cfg->qp_retry_cnt,
                                     cfg->qp_rnr_retry) != 0) goto cleanup;

    /* Light warmup: post a few writes to make sure path is alive */
    uint64_t wr_id = 0;
    for (int i = 0; i < 16; i++) {
        if (rdma_post_write(&rctx, (i % 8 == 0), wr_id++) != 0) goto cleanup;
    }
    {
        struct ibv_wc wc;
        int drained = 0;
        uint64_t dl = get_time_ns() + 2000000000ULL;
        while (drained < 2 && get_time_ns() < dl) {
            int ne = rdma_poll_cq(&rctx, &wc, 1);
            if (ne <= 0) continue;
            if (wc.status != IBV_WC_SUCCESS) goto cleanup;
            drained++;
        }
    }

    /* Post a burst right before injection */
    int outstanding = 0;
    for (int i = 0; i < SIGNAL_INTERVAL * 4; i++) {
        bool sig = (i % SIGNAL_INTERVAL == 0);
        if (rdma_post_write(&rctx, sig, wr_id++) != 0) goto cleanup;
        if (sig) outstanding++;
    }

    /* Send INJECT_NOW(KILL) */
    ctrl_msg_t inject_msg;
    memset(&inject_msg, 0, sizeof(inject_msg));
    inject_msg.type = MSG_INJECT_NOW;
    inject_msg.fault_type = FAULT_KILL;
    inject_msg.iteration = iter;

    uint64_t t_inject = get_time_ns();
    if (send_ctrl_msg(ctrl_fd, &inject_msg) != 0) goto cleanup;

    /* Try ACK with short timeout (server kills itself after sending it) */
    uint64_t t_ack = 0;
    {
        struct pollfd pfd = { .fd = ctrl_fd, .events = POLLIN };
        if (poll(&pfd, 1, 200) > 0 && (pfd.revents & POLLIN)) {
            ctrl_msg_t ack;
            if (recv_ctrl_msg(ctrl_fd, &ack) == 0 && ack.type == MSG_INJECT_ACK)
                t_ack = get_time_ns();
        }
    }

    /* Tight-poll, posting more writes to keep HCA engaged */
    bool error_seen = false;
    int writes_since_signal = 0;
    int wc_status = -1;
    uint64_t deadline_ns = t_inject + (uint64_t)WRITE_TIMEOUT_SEC * 1000000000ULL;

    while (!error_seen && !g_stop) {
        if (get_time_ns() > deadline_ns) {
            a->timed_out++;
            LOG_WARN("kill[%d]: timeout waiting for error CQE", iter);
            break;
        }
        struct ibv_wc wc;
        int ne = rdma_poll_cq(&rctx, &wc, 1);
        if (ne > 0) {
            if (wc.status != IBV_WC_SUCCESS) {
                wc_status = wc.status;
                error_seen = true;
                break;
            } else {
                if (outstanding > 0) outstanding--;
            }
        }
        if (!error_seen && outstanding < (MAX_SEND_WR / SIGNAL_INTERVAL) - 2) {
            writes_since_signal++;
            bool sig = (writes_since_signal >= SIGNAL_INTERVAL);
            if (sig) writes_since_signal = 0;
            if (rdma_post_write(&rctx, sig, wr_id++) == 0) {
                if (sig) outstanding++;
            }
        }
    }

    if (error_seen) {
        uint64_t t_err = get_time_ns();
        uint64_t t_fault_est = (t_ack > t_inject)
                               ? t_inject + (t_ack - t_inject) / 2
                               : t_inject;
        uint64_t lat = (t_err > t_fault_est) ? (t_err - t_fault_est) : 0;
        agg_record_ok(a, lat);   /* success = error CQE within budget */
        agg_record_err(a, wc_status); /* also count error code */
        LOG_INFO("kill[%d]: detect=%.1fms status=%d", iter,
                 ns_to_ms(lat), wc_status);
        rc = 0;
    } else {
        rc = 0; /* timed_out already counted */
    }

cleanup:
    if (rdma_init) rdma_destroy_ctx(&rctx);
    if (ctrl_fd >= 0) close(ctrl_fd);
    return rc;
}

/* ---------------------------------------------------------------- */
static const char *mode_str(run_mode_t m)
{
    return (m == MODE_NETEM) ? "netem" : "kill";
}

static void write_csv(FILE *fp, const client_config_t *cfg, const agg_t *a,
                      int n_attempted, double p50_ns, double p99_ns)
{
    int n_total = a->ok_count + a->err_retry_exc + a->err_rnr_retry_exc +
                  a->err_wr_flush + a->err_other + a->timed_out;
    double mean_us = (a->ok_count > 0)
                     ? ns_to_us(a->lat_sum_ns / a->ok_count) : 0.0;

    fprintf(fp,
        "%s,%d,%d,%d,%d,"
        "%d,%d,%d,%d,%d,%d,%d,"
        "%.2f,%.2f,%.2f,%.2f,%.2f\n",
        mode_str(cfg->mode), cfg->qp_retry_cnt, cfg->qp_timeout,
        cfg->qp_rnr_retry, cfg->loss_pct,
        n_attempted, n_total, a->ok_count,
        a->err_retry_exc, a->err_rnr_retry_exc,
        a->err_wr_flush, a->err_other,
        mean_us,
        ns_to_us(p50_ns), ns_to_us(p99_ns),
        ns_to_us(a->lat_min_ns == (uint64_t)-1 ? 0 : a->lat_min_ns),
        ns_to_us(a->lat_max_ns));
}

/* ---------------------------------------------------------------- */
static void print_usage(const char *prog)
{
    fprintf(stderr,
        "Usage: %s [options]\n"
        "\n"
        "Required:\n"
        "  -s, --server <ip>\n"
        "  -M, --mode <netem|kill>\n"
        "\n"
        "QP retry tuning (sweeps these externally):\n"
        "  -R, --retry-cnt <0..7>     (default 7)\n"
        "  -O, --qp-timeout <0..31>   (default 14, ~67ms)\n"
        "  -N, --rnr-retry <0..7>     (default 7)\n"
        "  -L, --loss-pct <int>       Metadata only (tc applied externally)\n"
        "\n"
        "Optional:\n"
        "  -d <dev>      (default mlx5_0)\n"
        "  -i <ib-port>  (default 1)\n"
        "  -g <gid>      (default 3)\n"
        "  -p <port>     (default %d)\n"
        "  -n <N>        Iterations or write count (default 100)\n"
        "  -o <file>     CSV output (default results/exp4.csv)\n"
        "  -h            help\n",
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
    cfg->mode         = MODE_NETEM;
    cfg->iterations   = 100;
    cfg->loss_pct     = 0;
    strncpy(cfg->output_file, "results/exp4.csv", sizeof(cfg->output_file) - 1);

    bool have_server = false, have_mode = false;

    static struct option lo[] = {
        {"server",     required_argument, 0, 's'},
        {"mode",       required_argument, 0, 'M'},
        {"retry-cnt",  required_argument, 0, 'R'},
        {"qp-timeout", required_argument, 0, 'O'},
        {"rnr-retry",  required_argument, 0, 'N'},
        {"loss-pct",   required_argument, 0, 'L'},
        {"device",     required_argument, 0, 'd'},
        {"ib-port",    required_argument, 0, 'i'},
        {"gid-index",  required_argument, 0, 'g'},
        {"port",       required_argument, 0, 'p'},
        {"iterations", required_argument, 0, 'n'},
        {"output",     required_argument, 0, 'o'},
        {"help",       no_argument,       0, 'h'},
        {0, 0, 0, 0}
    };
    int opt;
    while ((opt = getopt_long(argc, argv, "s:M:R:O:N:L:d:i:g:p:n:o:h",
                              lo, NULL)) != -1) {
        switch (opt) {
        case 's': strncpy(cfg->server_ip, optarg, sizeof(cfg->server_ip) - 1);
                  have_server = true; break;
        case 'M':
            if (strcmp(optarg, "netem") == 0) cfg->mode = MODE_NETEM;
            else if (strcmp(optarg, "kill") == 0) cfg->mode = MODE_KILL;
            else { LOG_ERR("Unknown mode: %s", optarg); return -1; }
            have_mode = true; break;
        case 'R': cfg->qp_retry_cnt = atoi(optarg); break;
        case 'O': cfg->qp_timeout   = atoi(optarg); break;
        case 'N': cfg->qp_rnr_retry = atoi(optarg); break;
        case 'L': cfg->loss_pct     = atoi(optarg); break;
        case 'd': strncpy(cfg->dev_name, optarg, sizeof(cfg->dev_name) - 1); break;
        case 'i': cfg->ib_port = atoi(optarg); break;
        case 'g': cfg->gid_index = atoi(optarg); break;
        case 'p': cfg->ctrl_port = atoi(optarg); break;
        case 'n': cfg->iterations = atoi(optarg);
                  if (cfg->iterations < 1) { LOG_ERR("-n >= 1"); return -1; }
                  break;
        case 'o': strncpy(cfg->output_file, optarg, sizeof(cfg->output_file) - 1); break;
        case 'h': print_usage(argv[0]); exit(0);
        default:  print_usage(argv[0]); return -1;
        }
    }
    if (!have_server) { LOG_ERR("Server IP required (-s)"); return -1; }
    if (!have_mode)   { LOG_ERR("Mode required (-M netem|kill)"); return -1; }
    if (cfg->qp_retry_cnt < 0 || cfg->qp_retry_cnt > 7) {
        LOG_ERR("retry_cnt must be 0..7"); return -1;
    }
    if (cfg->qp_rnr_retry < 0 || cfg->qp_rnr_retry > 7) {
        LOG_ERR("rnr_retry must be 0..7"); return -1;
    }
    if (cfg->qp_timeout < 0 || cfg->qp_timeout > 31) {
        LOG_ERR("qp_timeout must be 0..31"); return -1;
    }
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

    LOG_INFO("Exp4: server=%s mode=%s retry=%d timeout=%d rnr=%d loss=%d%% n=%d",
             cfg.server_ip, mode_str(cfg.mode), cfg.qp_retry_cnt, cfg.qp_timeout,
             cfg.qp_rnr_retry, cfg.loss_pct, cfg.iterations);

    /* Open output (append-friendly: header only if new/empty) */
    bool need_header = true;
    {
        FILE *probe = fopen(cfg.output_file, "r");
        if (probe) {
            fseek(probe, 0, SEEK_END);
            if (ftell(probe) > 0) need_header = false;
            fclose(probe);
        }
    }
    FILE *fp = fopen(cfg.output_file, "a");
    if (!fp) LOG_FATAL("Cannot open '%s': %s", cfg.output_file, strerror(errno));
    if (need_header) {
        fprintf(fp,
            "mode,retry_cnt,qp_timeout,rnr_retry,loss_pct,"
            "n_attempted,n_observed,n_ok,n_retry_exc,n_rnr_retry_exc,"
            "n_wr_flush,n_other,"
            "mean_us,p50_us,p99_us,min_us,max_us\n");
    }

    agg_t a;
    agg_init(&a, cfg.iterations + 1);

    if (cfg.mode == MODE_NETEM) {
        /* Single connection, run all writes */
        int ctrl_fd = tcp_connect(cfg.server_ip, cfg.ctrl_port);
        if (ctrl_fd < 0) goto out;

        rdma_ctx_t rctx;
        if (rdma_init_ctx(&rctx, cfg.dev_name, cfg.ib_port,
                          cfg.gid_index, RDMA_BUF_SIZE) != 0) {
            close(ctrl_fd); goto out;
        }
        if (rdma_create_qp(&rctx) != 0) {
            rdma_destroy_ctx(&rctx); close(ctrl_fd); goto out;
        }
        if (exchange_qp_info_and_connect(ctrl_fd, &rctx,
                                         cfg.qp_timeout, cfg.qp_retry_cnt,
                                         cfg.qp_rnr_retry) != 0) {
            rdma_destroy_ctx(&rctx); close(ctrl_fd); goto out;
        }

        run_netem(&rctx, cfg.iterations, &a);

        ctrl_msg_t done = { .type = MSG_DONE };
        send_ctrl_msg(ctrl_fd, &done);
        rdma_destroy_ctx(&rctx);
        close(ctrl_fd);
    } else {
        /* kill mode: reconnect per iteration */
        for (int i = 0; i < cfg.iterations && !g_stop; i++) {
            run_kill_one(&cfg, &a, i);
            /* Allow server_loop.sh to restart */
            sleep(1);
        }
    }

out:
    {
        double p50, p99;
        agg_finalize(&a, &p50, &p99);
        write_csv(fp, &cfg, &a, cfg.iterations, p50, p99);
        LOG_INFO("Result: ok=%d retry_exc=%d rnr=%d flush=%d other=%d timeout=%d "
                 "mean=%.1fus p50=%.1fus p99=%.1fus",
                 a.ok_count, a.err_retry_exc, a.err_rnr_retry_exc,
                 a.err_wr_flush, a.err_other, a.timed_out,
                 (a.ok_count > 0 ? ns_to_us(a.lat_sum_ns / a.ok_count) : 0.0),
                 ns_to_us(p50), ns_to_us(p99));
        free(a.lat_samples_ns);
    }
    fclose(fp);
    return EXIT_SUCCESS;
}
