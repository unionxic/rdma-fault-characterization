/*
 * client.c - Pure HCA retry measurement via ibv_modify_qp(ERR)
 *
 * Eliminates SSH overhead and kernel QP cleanup from the measurement path.
 * The server calls ibv_modify_qp(ERR) directly; client measures
 * t2 - t1 = pure HCA retry/timeout time.
 *
 * Uses existing experiment1/server on 224 (FAULT_QP_ERR mode).
 * Server stays alive across iterations; RESET protocol reuses TCP.
 */

#include <sys/stat.h>
#include "rdma_common.h"

#define WRITE_TIMEOUT_SEC 30

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
    attr.ah_attr.grh.sgid_index = rctx->gid_index;
    attr.ah_attr.grh.hop_limit  = 64;
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

static int reset_for_next(int ctrl_fd, rdma_ctx_t *rctx,
                          int qp_timeout, int qp_retry_cnt, int qp_rnr_retry)
{
    ctrl_msg_t msg;

    memset(&msg, 0, sizeof(msg));
    msg.type = MSG_RESET;
    if (send_ctrl_msg(ctrl_fd, &msg) != 0) {
        LOG_ERR("Failed to send RESET");
        return -1;
    }

    if (recv_ctrl_msg(ctrl_fd, &msg) != 0 || msg.type != MSG_RESET_ACK) {
        LOG_ERR("Failed to receive RESET_ACK");
        return -1;
    }

    rdma_destroy_qp(rctx);
    if (rdma_create_qp(rctx) != 0) {
        LOG_ERR("Failed to recreate QP");
        return -1;
    }

    if (exchange_and_connect(ctrl_fd, rctx,
                             qp_timeout, qp_retry_cnt, qp_rnr_retry) != 0) {
        LOG_ERR("Failed to re-exchange after reset");
        return -1;
    }

    return 0;
}

static int run_one(int ctrl_fd, rdma_ctx_t *rctx,
                   client_config_t *cfg, int iter, FILE *csv_fp)
{
    /* Warmup */
    {
        uint64_t wr_id = 0;
        for (int i = 0; i < 16; i++)
            if (rdma_post_write(rctx, (i % 8 == 0), wr_id++) != 0) return -1;
        struct ibv_wc wc;
        int drained = 0;
        uint64_t dl = get_time_ns() + 2000000000ULL;
        while (drained < 2 && get_time_ns() < dl) {
            int ne = rdma_poll_cq(rctx, &wc, 1);
            if (ne <= 0) continue;
            if (wc.status != IBV_WC_SUCCESS) {
                LOG_ERR("warmup error: %s", ibv_wc_status_str(wc.status));
                return -1;
            }
            drained++;
        }
    }

    /* Pre-inject burst */
    uint64_t wr_id = 1000;
    int outstanding = 0;
    for (int i = 0; i < SIGNAL_INTERVAL * 4; i++) {
        bool sig = (i % SIGNAL_INTERVAL == 0);
        if (rdma_post_write(rctx, sig, wr_id++) != 0) return -1;
        if (sig) outstanding++;
    }

    /* ---- t0: INJECT QP_ERR ---- */
    ctrl_msg_t inject_msg;
    memset(&inject_msg, 0, sizeof(inject_msg));
    inject_msg.type = MSG_INJECT_NOW;
    inject_msg.fault_type = FAULT_QP_ERR;
    inject_msg.iteration = iter;

    uint64_t t0 = get_time_ns();
    if (send_ctrl_msg(ctrl_fd, &inject_msg) != 0) {
        LOG_ERR("Failed to send INJECT");
        return -1;
    }

    /* Server always sends ACK for QP_ERR (after calling modify_qp) */
    ctrl_msg_t ack;
    if (recv_ctrl_msg(ctrl_fd, &ack) != 0 || ack.type != MSG_INJECT_ACK) {
        LOG_ERR("Failed to receive INJECT_ACK");
        return -1;
    }
    uint64_t t_ack = get_time_ns();

    /* ---- Tight-poll ---- */
    uint64_t t1 = 0;
    uint64_t t2 = 0;
    int success_count = 0;
    int wc_status = -1;
    int writes_since_signal = 0;
    uint64_t deadline_ns = t0 + (uint64_t)WRITE_TIMEOUT_SEC * 1000000000ULL;

    while (t2 == 0 && !g_stop) {
        if (get_time_ns() > deadline_ns) {
            LOG_WARN("iter[%d]: timeout", iter);
            break;
        }

        struct ibv_wc wc;
        int ne = rdma_poll_cq(rctx, &wc, 1);
        if (ne > 0) {
            uint64_t now = get_time_ns();
            if (wc.status == IBV_WC_SUCCESS) {
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
            if (rdma_post_write(rctx, sig, wr_id++) == 0) {
                if (sig) outstanding++;
            }
        }
    }

    if (t2 > 0) {
        double tcp_rtt_ms = ns_to_ms(t_ack - t0);

        LOG_INFO("iter[%d] R=%d T=%d: t1-t0=%.3fms  t2-t1=%.3fms  t2-t0=%.3fms  "
                 "tcp_rtt=%.3fms  status=%d(%s)",
                 iter, cfg->qp_retry_cnt, cfg->qp_timeout,
                 ns_to_ms(t1 - t0), ns_to_ms(t2 - t1), ns_to_ms(t2 - t0),
                 tcp_rtt_ms, wc_status, ibv_wc_status_str(wc_status));

        if (csv_fp) {
            fprintf(csv_fp, "%d,%d,%d,%d,"
                    "%llu,%llu,%llu,%llu,"
                    "%.3f,%.3f,%.3f,%.3f,"
                    "%d,%d\n",
                    iter, cfg->qp_retry_cnt, cfg->qp_timeout, cfg->qp_rnr_retry,
                    (unsigned long long)t0, (unsigned long long)t_ack,
                    (unsigned long long)t1, (unsigned long long)t2,
                    ns_to_ms(t1 - t0), ns_to_ms(t2 - t1), ns_to_ms(t2 - t0),
                    tcp_rtt_ms,
                    success_count, wc_status);
            fflush(csv_fp);
        }
        return 0;
    }

    LOG_ERR("iter[%d]: no error CQE detected", iter);
    return -1;
}

static void print_usage(const char *prog)
{
    fprintf(stderr,
        "Usage: %s -s <ip> [options]\n"
        "  -s <ip>     Server IP (10.0.0.x)\n"
        "  -R <0..7>   retry_cnt (default 7)\n"
        "  -O <0..31>  qp_timeout (default 14)\n"
        "  -n <N>      iterations (default 30)\n"
        "  -d <dev>    IB device (default mlx5_0)\n"
        "  -i <port>   IB port (default 1)\n"
        "  -g <gid>    GID index (default 3)\n"
        "  -p <port>   TCP port (default %d)\n"
        "  -o <file>   CSV output (default results/modifyqp.csv)\n",
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
    cfg->iterations   = 30;
    strncpy(cfg->output_file, "results/modifyqp.csv", sizeof(cfg->output_file) - 1);

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

    LOG_INFO("modify_qp(ERR) experiment: server=%s R=%d T=%d n=%d",
             cfg.server_ip, cfg.qp_retry_cnt, cfg.qp_timeout, cfg.iterations);

    mkdir("results", 0755);

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
                        "t1_t0_ms,t2_t1_ms,t2_t0_ms,tcp_rtt_ms,"
                        "success_after_inject,wc_status\n");
    }

    /* TCP connect to server */
    int ctrl_fd = -1;
    for (int r = 0; r < 5; r++) {
        ctrl_fd = tcp_connect(cfg.server_ip, cfg.ctrl_port);
        if (ctrl_fd >= 0) break;
        sleep(2);
    }
    if (ctrl_fd < 0) LOG_FATAL("TCP connect failed");

    /* RDMA init */
    rdma_ctx_t rctx;
    if (rdma_init_ctx(&rctx, cfg.dev_name, cfg.ib_port,
                      cfg.gid_index, RDMA_BUF_SIZE) != 0)
        LOG_FATAL("RDMA init failed");
    if (rdma_create_qp(&rctx) != 0)
        LOG_FATAL("QP creation failed");

    /* Initial QP exchange */
    if (exchange_and_connect(ctrl_fd, &rctx,
                             cfg.qp_timeout, cfg.qp_retry_cnt,
                             cfg.qp_rnr_retry) != 0)
        LOG_FATAL("Initial QP exchange failed");

    /* Run iterations */
    int success = 0, fail = 0;
    for (int i = 0; i < cfg.iterations && !g_stop; i++) {
        if (run_one(ctrl_fd, &rctx, &cfg, i, csv_fp) == 0)
            success++;
        else
            fail++;

        if (i < cfg.iterations - 1 && !g_stop) {
            if (reset_for_next(ctrl_fd, &rctx,
                               cfg.qp_timeout, cfg.qp_retry_cnt,
                               cfg.qp_rnr_retry) != 0) {
                LOG_ERR("Reset failed at iteration %d", i);
                break;
            }
            usleep(100000);
        }
    }

    /* Clean shutdown */
    ctrl_msg_t done_msg;
    memset(&done_msg, 0, sizeof(done_msg));
    done_msg.type = MSG_DONE;
    send_ctrl_msg(ctrl_fd, &done_msg);

    fclose(csv_fp);
    rdma_destroy_ctx(&rctx);
    close(ctrl_fd);

    LOG_INFO("Complete: %d/%d success. Results: %s",
             success, success + fail, cfg.output_file);
    return (fail > 0) ? EXIT_FAILURE : EXIT_SUCCESS;
}
