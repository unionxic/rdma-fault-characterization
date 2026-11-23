/*
 * client.c - CPU Polling Interval Blind Window Measurement (runs on Server A)
 *
 * Part of: GPU-Initiated RDMA Fault Recovery Research
 * Experiment 2: How detection latency grows with CPU polling interval
 *
 * Measures detection_delay = max(HCA_retry_time, sleep_time) by:
 *   1. Establishing RC QP, posting RDMA Writes to fill pipeline
 *   2. Sending INJECT command, then sleeping for a configurable duration
 *   3. After wakeup, busy-polling CQ until error CQE arrives
 *   4. Recording t_inject_request, t_wakeup, t_detected
 *
 * The server binary is reused from experiment1 without modification.
 *
 * Usage:
 *   ./client -s <server_ip> -T <sleep_us> -S <a|b|c> [-n <iterations>] ...
 *
 * [UNTESTED: requires RDMA NIC]
 */

#include "rdma_common.h"

#define POST_BURST_COUNT  (SIGNAL_INTERVAL * 4)

typedef struct {
    char        server_ip[64];
    char        dev_name[32];
    int         ib_port;
    int         gid_index;
    int         ctrl_port;
    int         iterations;
    uint64_t    sleep_us;
    fault_type_t fault;
    char        output_file[256];
} client_config_t;

typedef struct {
    uint64_t    sleep_us;
    fault_type_t scenario;
    int         iteration;
    uint64_t    t_inject_request_ns;
    uint64_t    t_ack_ns;
    uint64_t    tcp_rtt_ns;
    uint64_t    t_wakeup_ns;
    uint64_t    t_detected_ns;
    uint64_t    detection_delay_ns;
    uint64_t    wakeup_to_detection_ns;
    int         error_status;
    uint32_t    vendor_err;
    bool        valid;
} measurement_t;

static volatile sig_atomic_t g_stop = 0;

static void sigint_handler(int sig)
{
    (void)sig;
    g_stop = 1;
}

/* ----------------------------------------------------------------
 * TCP control channel
 * ---------------------------------------------------------------- */

static int tcp_connect(const char *server_ip, int port)
{
    int sockfd = socket(AF_INET, SOCK_STREAM, 0);
    if (sockfd < 0) {
        LOG_ERR("socket() failed: %s", strerror(errno));
        return -1;
    }

    int flag = 1;
    if (setsockopt(sockfd, IPPROTO_TCP, TCP_NODELAY, &flag, sizeof(flag)) < 0)
        LOG_WARN("setsockopt TCP_NODELAY failed: %s", strerror(errno));

    struct timeval tv;
    tv.tv_sec = TCP_TIMEOUT_SEC;
    tv.tv_usec = 0;
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

    LOG_INFO("Connecting to %s:%d ...", server_ip, port);
    if (connect(sockfd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        LOG_ERR("connect() failed: %s", strerror(errno));
        close(sockfd);
        return -1;
    }

    LOG_INFO("TCP control channel established");
    return sockfd;
}

/* ----------------------------------------------------------------
 * Exchange QP info and establish RDMA connection
 * ---------------------------------------------------------------- */

static int exchange_qp_info_and_connect(int ctrl_fd, rdma_ctx_t *rctx)
{
    ctrl_msg_t msg;
    qp_info_t local_info;

    rdma_get_local_info(rctx, &local_info);

    memset(&msg, 0, sizeof(msg));
    msg.type = MSG_EXCHANGE_QP_INFO;
    msg.qp_info = local_info;

    if (send_ctrl_msg(ctrl_fd, &msg) != 0) {
        LOG_ERR("Failed to send QP info");
        return -1;
    }

    if (recv_ctrl_msg(ctrl_fd, &msg) != 0) {
        LOG_ERR("Failed to receive QP info");
        return -1;
    }

    if (msg.type != MSG_EXCHANGE_QP_INFO) {
        LOG_ERR("Expected MSG_EXCHANGE_QP_INFO, got type=%u", msg.type);
        return -1;
    }

    char gid_str[80];
    union ibv_gid remote_gid;
    memcpy(remote_gid.raw, msg.qp_info.gid, 16);
    gid_to_str(&remote_gid, gid_str, sizeof(gid_str));
    LOG_INFO("Remote QP info: qpn=0x%x psn=0x%x rkey=0x%x gid=%s",
             msg.qp_info.qpn, msg.qp_info.psn, msg.qp_info.rkey, gid_str);

    if (rdma_connect_qp(rctx, &msg.qp_info) != 0) {
        LOG_ERR("Failed to connect QP");
        return -1;
    }

    memset(&msg, 0, sizeof(msg));
    msg.type = MSG_READY;
    if (send_ctrl_msg(ctrl_fd, &msg) != 0) {
        LOG_ERR("Failed to send READY");
        return -1;
    }

    if (recv_ctrl_msg(ctrl_fd, &msg) != 0) {
        LOG_ERR("Failed to receive READY");
        return -1;
    }
    if (msg.type != MSG_READY) {
        LOG_ERR("Expected MSG_READY, got type=%u", msg.type);
        return -1;
    }

    LOG_INFO("RDMA connection established and both sides ready");
    return 0;
}

/* ----------------------------------------------------------------
 * Warm-up
 * ---------------------------------------------------------------- */

static int warmup(rdma_ctx_t *rctx)
{
    LOG_INFO("Warming up with %d RDMA Writes ...", WARMUP_COUNT);
    uint64_t wr_id = 0;
    int outstanding_signaled = 0;

    for (int i = 0; i < WARMUP_COUNT; i++) {
        bool sig = ((i % SIGNAL_INTERVAL) == 0);
        if (rdma_post_write(rctx, sig, wr_id++) != 0) {
            LOG_ERR("Warmup write failed at iteration %d", i);
            return -1;
        }
        if (sig)
            outstanding_signaled++;

        if (outstanding_signaled >= (MAX_SEND_WR / SIGNAL_INTERVAL) - 1) {
            struct ibv_wc wc;
            int drained = 0;
            while (drained < outstanding_signaled) {
                int ne = rdma_poll_cq(rctx, &wc, 1);
                if (ne < 0) return -1;
                if (ne == 0) continue;
                if (wc.status != IBV_WC_SUCCESS) {
                    LOG_ERR("Warmup: error CQE status=%d (%s)",
                            wc.status, ibv_wc_status_str(wc.status));
                    return -1;
                }
                drained++;
            }
            outstanding_signaled = 0;
        }
    }

    while (outstanding_signaled > 0) {
        struct ibv_wc wc;
        int ne = rdma_poll_cq(rctx, &wc, 1);
        if (ne < 0) return -1;
        if (ne == 0) continue;
        if (wc.status != IBV_WC_SUCCESS) {
            LOG_ERR("Warmup drain: error CQE status=%d", wc.status);
            return -1;
        }
        outstanding_signaled--;
    }

    LOG_INFO("Warm-up complete");
    return 0;
}

/* ----------------------------------------------------------------
 * Core measurement: inject fault, sleep, then poll for error CQE
 *
 * Protocol:
 * 1. Post burst of signaled RDMA Writes (outstanding work for HCA)
 * 2. Record t_inject_request, send INJECT command
 * 3. Receive ACK (blocking, before sleep)
 * 4. usleep(sleep_us) -- simulated CPU busyness
 * 5. Record t_wakeup
 * 6. Busy-poll CQ until error CQE, record t_detected
 * ---------------------------------------------------------------- */

static int run_one_measurement(int ctrl_fd, rdma_ctx_t *rctx,
                               fault_type_t fault, uint64_t sleep_us,
                               int iteration, measurement_t *result)
{
    memset(result, 0, sizeof(*result));
    result->scenario = fault;
    result->sleep_us = sleep_us;
    result->iteration = iteration;
    result->valid = false;

    uint64_t wr_id = 0;
    int outstanding_signaled = 0;

    /*
     * Drain any stale CQEs from warmup or previous operations,
     * then post a burst of signaled writes so the HCA has outstanding
     * work that will fail after fault injection.
     */
    {
        struct ibv_wc wc;
        while (rdma_poll_cq(rctx, &wc, 1) > 0)
            ;
    }

    for (int i = 0; i < POST_BURST_COUNT; i++) {
        bool sig = ((i % SIGNAL_INTERVAL) == 0);
        if (rdma_post_write(rctx, sig, wr_id++) != 0) {
            LOG_ERR("Failed to post burst writes");
            return -1;
        }
        if (sig)
            outstanding_signaled++;
    }

    /* Drain successful completions from the burst before injecting */
    {
        struct ibv_wc wc;
        int ne;
        uint64_t drain_deadline = get_time_ns() + 500000000ULL; /* 500ms */
        while (outstanding_signaled > 0 && get_time_ns() < drain_deadline) {
            ne = rdma_poll_cq(rctx, &wc, 1);
            if (ne < 0) return -1;
            if (ne == 0) continue;
            if (wc.status != IBV_WC_SUCCESS) {
                LOG_ERR("Unexpected error during pre-inject drain: status=%d (%s)",
                        wc.status, ibv_wc_status_str(wc.status));
                return -1;
            }
            outstanding_signaled--;
        }
    }

    /*
     * Post another burst of signaled writes right before injection.
     * These are the WRs whose error CQEs we will measure.
     */
    for (int i = 0; i < POST_BURST_COUNT; i++) {
        bool sig = ((i % SIGNAL_INTERVAL) == 0);
        if (rdma_post_write(rctx, sig, wr_id++) != 0) {
            LOG_ERR("Failed to post pre-inject burst writes");
            return -1;
        }
        if (sig)
            outstanding_signaled++;
    }

    /* Send INJECT command */
    ctrl_msg_t inject_msg;
    memset(&inject_msg, 0, sizeof(inject_msg));
    inject_msg.type = MSG_INJECT_NOW;
    inject_msg.fault_type = fault;
    inject_msg.iteration = iteration;

    result->t_inject_request_ns = get_time_ns();

    if (send_ctrl_msg(ctrl_fd, &inject_msg) != 0) {
        LOG_ERR("Failed to send INJECT command");
        return -1;
    }

    /*
     * For scenario A (QP->ERR), the server ACKs over TCP.
     * For scenario B (kill), the server dies -- no ACK.
     * For scenario C (link down), TCP may break -- no reliable ACK.
     *
     * Try to receive ACK non-blockingly for a short window.
     * For scenario A: block briefly since ACK is reliable and fast.
     */
    bool ack_received = false;
    if (fault == FAULT_QP_ERR) {
        ctrl_msg_t ack_msg;
        if (recv_ctrl_msg(ctrl_fd, &ack_msg) == 0 &&
            ack_msg.type == MSG_INJECT_ACK) {
            result->t_ack_ns = get_time_ns();
            ack_received = true;
        }
    } else {
        /* Non-blocking ACK attempt for kill/link-down */
        struct pollfd pfd = { .fd = ctrl_fd, .events = POLLIN };
        int poll_ret = poll(&pfd, 1, 100);
        if (poll_ret > 0 && (pfd.revents & POLLIN)) {
            ctrl_msg_t ack_msg;
            if (recv_ctrl_msg(ctrl_fd, &ack_msg) == 0 &&
                ack_msg.type == MSG_INJECT_ACK) {
                result->t_ack_ns = get_time_ns();
                ack_received = true;
            }
        }
    }

    /* Sleep (simulated CPU busyness) */
    if (sleep_us > 0)
        usleep((useconds_t)sleep_us);

    result->t_wakeup_ns = get_time_ns();

    /* Busy-poll CQ for error CQE */
    bool error_detected = false;
    uint64_t timeout_ns = (uint64_t)ERROR_DETECT_TIMEOUT_SEC * 1000000000ULL;

    while (!error_detected && !g_stop) {
        uint64_t now = get_time_ns();
        if (now - result->t_inject_request_ns > timeout_ns) {
            LOG_ERR("Timeout waiting for error CQE (%d sec)", ERROR_DETECT_TIMEOUT_SEC);
            return -1;
        }

        struct ibv_wc wc;
        int ne = rdma_poll_cq(rctx, &wc, 1);
        if (ne < 0) {
            LOG_ERR("CQ poll error");
            return -1;
        }
        if (ne > 0) {
            if (wc.status != IBV_WC_SUCCESS) {
                result->t_detected_ns = get_time_ns();
                result->error_status = wc.status;
                result->vendor_err = wc.vendor_err;
                error_detected = true;
                LOG_INFO("  Error CQE: status=%d (%s) vendor_err=0x%x wr_id=%lu",
                         wc.status, ibv_wc_status_str(wc.status),
                         wc.vendor_err, wc.wr_id);
            }
        }

        /*
         * Post additional writes only when not yet errored, to keep
         * the HCA probing the dead path and generate fresh CQEs.
         */
        if (!error_detected && outstanding_signaled < (MAX_SEND_WR / SIGNAL_INTERVAL) - 2) {
            bool sig = true;
            int post_ret = rdma_post_write(rctx, sig, wr_id++);
            if (post_ret == 0) {
                outstanding_signaled++;
            }
            /* post_send failure is expected once QP enters error state */
        }
    }

    if (!error_detected) {
        LOG_ERR("Measurement %d: no error detected (stopped=%d)", iteration, g_stop);
        return -1;
    }

    /* Compute timing */
    result->tcp_rtt_ns = 0;
    if (ack_received && result->t_ack_ns > result->t_inject_request_ns)
        result->tcp_rtt_ns = result->t_ack_ns - result->t_inject_request_ns;

    uint64_t t_fault_est;
    if (ack_received)
        t_fault_est = result->t_inject_request_ns + result->tcp_rtt_ns / 2;
    else
        t_fault_est = result->t_inject_request_ns;

    if (result->t_detected_ns > t_fault_est)
        result->detection_delay_ns = result->t_detected_ns - t_fault_est;
    else
        result->detection_delay_ns = 0;

    if (result->t_detected_ns > result->t_wakeup_ns)
        result->wakeup_to_detection_ns = result->t_detected_ns - result->t_wakeup_ns;
    else
        result->wakeup_to_detection_ns = 0;

    result->valid = true;

    LOG_INFO("  Iter %d/%s sleep=%lu us: detection=%.1f ms, wakeup_to_detect=%.1f ms",
             iteration, fault_type_names[fault], sleep_us,
             ns_to_ms(result->detection_delay_ns),
             ns_to_ms(result->wakeup_to_detection_ns));

    return 0;
}

/* ----------------------------------------------------------------
 * Request QP reset for next iteration (scenario A only)
 * ---------------------------------------------------------------- */

static int request_reset(int ctrl_fd, rdma_ctx_t *rctx, fault_type_t fault)
{
    if (fault == FAULT_KILL || fault == FAULT_LINK_DOWN)
        return 1; /* signal: need server restart */

    rdma_destroy_qp(rctx);

    ctrl_msg_t msg;
    memset(&msg, 0, sizeof(msg));
    msg.type = MSG_RESET;
    if (send_ctrl_msg(ctrl_fd, &msg) != 0) {
        LOG_ERR("Failed to send RESET");
        return -1;
    }

    if (recv_ctrl_msg(ctrl_fd, &msg) != 0) {
        LOG_ERR("Failed to receive RESET_ACK");
        return -1;
    }
    if (msg.type != MSG_RESET_ACK) {
        LOG_ERR("Expected RESET_ACK, got type=%u", msg.type);
        return -1;
    }

    if (rdma_create_qp(rctx) != 0) {
        LOG_ERR("Failed to recreate QP");
        return -1;
    }

    if (exchange_qp_info_and_connect(ctrl_fd, rctx) != 0) {
        LOG_ERR("Failed to re-establish RDMA connection");
        return -1;
    }

    return 0;
}

/* ----------------------------------------------------------------
 * CSV output
 * ---------------------------------------------------------------- */

static void write_csv_header(FILE *fp)
{
    fprintf(fp, "sleep_us,scenario,iteration,"
                "t_inject_request_ns,t_ack_ns,tcp_rtt_ns,"
                "t_wakeup_ns,t_detected_ns,"
                "detection_delay_ns,wakeup_to_detection_ns,"
                "error_status,vendor_err\n");
}

static void write_csv_row(FILE *fp, const measurement_t *m)
{
    if (!m->valid) return;

    fprintf(fp, "%lu,%s,%d,%lu,%lu,%lu,%lu,%lu,%lu,%lu,%d,0x%x\n",
            m->sleep_us,
            fault_type_names[m->scenario],
            m->iteration,
            m->t_inject_request_ns,
            m->t_ack_ns,
            m->tcp_rtt_ns,
            m->t_wakeup_ns,
            m->t_detected_ns,
            m->detection_delay_ns,
            m->wakeup_to_detection_ns,
            m->error_status,
            m->vendor_err);
}

/* ----------------------------------------------------------------
 * Usage and argument parsing
 * ---------------------------------------------------------------- */

static void print_usage(const char *prog)
{
    fprintf(stderr,
        "Usage: %s [options]\n"
        "\n"
        "Required:\n"
        "  -s, --server <ip>        Server B IP address\n"
        "  -T, --sleep <us>         Sleep duration in microseconds after INJECT\n"
        "  -S, --scenario <a|b|c>   Fault scenario: a=QP->ERR, b=kill, c=link-down\n"
        "\n"
        "Optional:\n"
        "  -d, --device <name>      IB device name (default: %s)\n"
        "  -i, --ib-port <num>      IB port number (default: %d)\n"
        "  -g, --gid-index <num>    GID index for RoCE (default: %d)\n"
        "  -p, --port <num>         TCP control port (default: %d)\n"
        "  -n, --iterations <num>   Iterations (default: %d)\n"
        "  -o, --output <file>      CSV output file (default: results/blind_window.csv)\n"
        "  -h, --help               Show this help\n",
        prog, DEFAULT_DEV_NAME, DEFAULT_IB_PORT, DEFAULT_GID_INDEX,
        DEFAULT_CTRL_PORT, DEFAULT_ITERATIONS);
}

static int parse_args(int argc, char **argv, client_config_t *cfg)
{
    memset(cfg, 0, sizeof(*cfg));
    strncpy(cfg->dev_name, DEFAULT_DEV_NAME, sizeof(cfg->dev_name) - 1);
    cfg->ib_port = DEFAULT_IB_PORT;
    cfg->gid_index = DEFAULT_GID_INDEX;
    cfg->ctrl_port = DEFAULT_CTRL_PORT;
    cfg->iterations = DEFAULT_ITERATIONS;
    cfg->sleep_us = 0;
    cfg->fault = FAULT_QP_ERR;
    strncpy(cfg->output_file, "results/blind_window.csv",
            sizeof(cfg->output_file) - 1);

    bool have_server = false;
    bool have_sleep = false;
    bool have_scenario = false;

    static struct option long_options[] = {
        {"server",     required_argument, 0, 's'},
        {"sleep",      required_argument, 0, 'T'},
        {"scenario",   required_argument, 0, 'S'},
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
    while ((opt = getopt_long(argc, argv, "s:T:S:d:i:g:p:n:o:h",
                              long_options, NULL)) != -1) {
        switch (opt) {
        case 's':
            strncpy(cfg->server_ip, optarg, sizeof(cfg->server_ip) - 1);
            have_server = true;
            break;
        case 'T':
            cfg->sleep_us = (uint64_t)strtoull(optarg, NULL, 10);
            have_sleep = true;
            break;
        case 'S':
            have_scenario = true;
            if (strcmp(optarg, "a") == 0 || strcmp(optarg, "A") == 0)
                cfg->fault = FAULT_QP_ERR;
            else if (strcmp(optarg, "b") == 0 || strcmp(optarg, "B") == 0)
                cfg->fault = FAULT_KILL;
            else if (strcmp(optarg, "c") == 0 || strcmp(optarg, "C") == 0)
                cfg->fault = FAULT_LINK_DOWN;
            else {
                LOG_ERR("Unknown scenario: '%s' (use a, b, or c)", optarg);
                return -1;
            }
            break;
        case 'd':
            strncpy(cfg->dev_name, optarg, sizeof(cfg->dev_name) - 1);
            break;
        case 'i':
            cfg->ib_port = atoi(optarg);
            break;
        case 'g':
            cfg->gid_index = atoi(optarg);
            break;
        case 'p':
            cfg->ctrl_port = atoi(optarg);
            break;
        case 'n':
            cfg->iterations = atoi(optarg);
            if (cfg->iterations < 1) {
                LOG_ERR("Iterations must be >= 1");
                return -1;
            }
            break;
        case 'o':
            strncpy(cfg->output_file, optarg, sizeof(cfg->output_file) - 1);
            break;
        case 'h':
            print_usage(argv[0]);
            exit(0);
        default:
            print_usage(argv[0]);
            return -1;
        }
    }

    if (!have_server) {
        LOG_ERR("Server IP is required (-s)");
        print_usage(argv[0]);
        return -1;
    }
    if (!have_sleep) {
        LOG_ERR("Sleep duration is required (-T)");
        print_usage(argv[0]);
        return -1;
    }
    if (!have_scenario) {
        LOG_ERR("Fault scenario is required (-S)");
        print_usage(argv[0]);
        return -1;
    }

    return 0;
}

/* ----------------------------------------------------------------
 * Run all iterations for a single (sleep_us, fault_type) pair
 * ---------------------------------------------------------------- */

static int run_all_iterations(client_config_t *cfg, FILE *csv_fp)
{
    LOG_INFO("===== sleep=%lu us, scenario=%s, iterations=%d =====",
             cfg->sleep_us, fault_type_names[cfg->fault], cfg->iterations);

    int ctrl_fd = -1;
    rdma_ctx_t rctx;
    bool rdma_initialized = false;
    bool need_fresh_connection = true;
    int valid_count = 0;

    for (int iter = 0; iter < cfg->iterations && !g_stop; iter++) {
        LOG_INFO("--- Iteration %d/%d ---", iter + 1, cfg->iterations);

        if (need_fresh_connection) {
            if (rdma_initialized) {
                rdma_destroy_ctx(&rctx);
                rdma_initialized = false;
            }
            if (ctrl_fd >= 0) {
                close(ctrl_fd);
                ctrl_fd = -1;
            }

            int max_retries = (cfg->fault == FAULT_LINK_DOWN) ? 10 : 3;
            for (int r = 0; r < max_retries; r++) {
                ctrl_fd = tcp_connect(cfg->server_ip, cfg->ctrl_port);
                if (ctrl_fd >= 0) break;
                LOG_INFO("TCP connect retry %d/%d in 3s...", r + 1, max_retries);
                sleep(3);
            }
            if (ctrl_fd < 0) {
                LOG_ERR("TCP connect failed after retries");
                return -1;
            }

            if (rdma_init_ctx(&rctx, cfg->dev_name, cfg->ib_port,
                              cfg->gid_index, RDMA_BUF_SIZE) != 0) {
                LOG_ERR("RDMA init failed");
                close(ctrl_fd);
                return -1;
            }
            rdma_initialized = true;

            if (iter == 0)
                rdma_print_device_info(&rctx, cfg->dev_name);

            if (rdma_create_qp(&rctx) != 0) {
                LOG_ERR("QP creation failed");
                goto cleanup;
            }

            if (exchange_qp_info_and_connect(ctrl_fd, &rctx) != 0) {
                LOG_ERR("QP exchange failed");
                goto cleanup;
            }

            need_fresh_connection = false;
        }

        if (warmup(&rctx) != 0) {
            LOG_ERR("Warmup failed");
            goto cleanup;
        }

        measurement_t m;
        if (run_one_measurement(ctrl_fd, &rctx, cfg->fault, cfg->sleep_us,
                                iter, &m) != 0) {
            LOG_ERR("Measurement failed at iteration %d", iter);
            need_fresh_connection = true;
            continue;
        }

        if (csv_fp && m.valid) {
            write_csv_row(csv_fp, &m);
            fflush(csv_fp);
            valid_count++;
        }

        if (iter < cfg->iterations - 1) {
            int reset_ret = request_reset(ctrl_fd, &rctx, cfg->fault);
            if (reset_ret < 0) {
                LOG_ERR("Reset failed");
                need_fresh_connection = true;
            } else if (reset_ret == 1) {
                need_fresh_connection = true;
                int wait_sec = (cfg->fault == FAULT_LINK_DOWN) ? 30 : 3;
                LOG_INFO("Server needs restart, waiting %d sec...", wait_sec);
                sleep(wait_sec);
            }
        }
    }

    if (ctrl_fd >= 0 && cfg->fault == FAULT_QP_ERR) {
        ctrl_msg_t done;
        memset(&done, 0, sizeof(done));
        done.type = MSG_DONE;
        send_ctrl_msg(ctrl_fd, &done);
    }

cleanup:
    if (rdma_initialized)
        rdma_destroy_ctx(&rctx);
    if (ctrl_fd >= 0)
        close(ctrl_fd);

    LOG_INFO("Completed: %d/%d valid measurements", valid_count, cfg->iterations);
    return 0;
}

/* ----------------------------------------------------------------
 * Main
 * ---------------------------------------------------------------- */

int main(int argc, char **argv)
{
    client_config_t cfg;
    if (parse_args(argc, argv, &cfg) != 0)
        return EXIT_FAILURE;

    struct sigaction sa;
    sa.sa_handler = sigint_handler;
    sigemptyset(&sa.sa_mask);
    sa.sa_flags = 0;
    sigaction(SIGINT, &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);

    LOG_INFO("Experiment 2: CPU Polling Interval Blind Window");
    LOG_INFO("Server=%s Dev=%s Port=%d GID=%d Sleep=%lu us Scenario=%s Iters=%d",
             cfg.server_ip, cfg.dev_name, cfg.ib_port, cfg.gid_index,
             cfg.sleep_us, fault_type_names[cfg.fault], cfg.iterations);

    FILE *csv_fp = fopen(cfg.output_file, "w");
    if (!csv_fp) {
        LOG_FATAL("Cannot open output file '%s': %s",
                  cfg.output_file, strerror(errno));
    }
    write_csv_header(csv_fp);

    int ret = run_all_iterations(&cfg, csv_fp);

    fclose(csv_fp);

    return (ret == 0) ? EXIT_SUCCESS : EXIT_FAILURE;
}
