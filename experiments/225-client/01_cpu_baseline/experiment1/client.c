/*
 * client.c - RDMA Fault Detection Latency Measurement (runs on Server A)
 *
 * Part of: GPU-Initiated RDMA Fault Recovery Research
 * Experiment 1: CPU-mediated fault detection baseline latency
 *
 * This program:
 *   1. Connects to Server B via TCP control channel
 *   2. Establishes an RC QP for RDMA Write operations
 *   3. Runs continuous RDMA Writes with CQ polling
 *   4. Requests fault injection from Server B
 *   5. Measures time from fault injection to error CQE detection
 *   6. Repeats for multiple fault scenarios and iterations
 *   7. Outputs machine-readable CSV results and summary statistics
 *
 * Usage:
 *   ./client -s <server_ip> [-d <dev>] [-p <port>] [-n <iterations>]
 *            [-g <gid_index>] [--scenarios <a,b,c>]
 *
 * [UNTESTED: requires RDMA NIC]
 * Compile: gcc -O2 -Wall -Werror -o client client.c rdma_common.c \
 *          -libverbs -lrdmacm -lpthread -lm
 */

#include "rdma_common.h"

/* ----------------------------------------------------------------
 * Configuration parsed from command-line arguments
 * ---------------------------------------------------------------- */

typedef struct {
    char        server_ip[64];
    char        dev_name[32];
    int         ib_port;
    int         gid_index;
    int         ctrl_port;
    int         iterations;
    bool        scenarios[FAULT_NUM_TYPES]; /* which scenarios to run */
    char        output_file[256];
} client_config_t;

/* ----------------------------------------------------------------
 * Per-iteration measurement record
 * ---------------------------------------------------------------- */

typedef struct {
    fault_type_t    scenario;
    int             iteration;
    uint64_t        t_inject_request_ns;    /* when we sent INJECT command */
    uint64_t        t_ack_ns;               /* when we received ACK */
    uint64_t        tcp_rtt_ns;             /* t_ack - t_inject_request */
    uint64_t        t_error_cqe_ns;         /* when error CQE was polled */
    uint64_t        detection_latency_ns;   /* t_error_cqe - estimated fault time */
    int             error_status;           /* ibv_wc_status value */
    uint32_t        vendor_err;             /* vendor-specific error code */
    bool            valid;                  /* whether measurement is valid */
} measurement_t;

/* ----------------------------------------------------------------
 * Global state
 * ---------------------------------------------------------------- */

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

    /* Disable Nagle for low-latency control messages */
    int flag = 1;
    if (setsockopt(sockfd, IPPROTO_TCP, TCP_NODELAY, &flag, sizeof(flag)) < 0) {
        LOG_WARN("setsockopt TCP_NODELAY failed: %s", strerror(errno));
    }

    /* Set send/recv timeout */
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
 * Exchange QP info over TCP, establish RDMA connection
 * ---------------------------------------------------------------- */

static int exchange_qp_info_and_connect(int ctrl_fd, rdma_ctx_t *rctx)
{
    ctrl_msg_t msg;
    qp_info_t local_info;

    /* Get local QP info */
    rdma_get_local_info(rctx, &local_info);

    /* Send our QP info to server */
    memset(&msg, 0, sizeof(msg));
    msg.type = MSG_EXCHANGE_QP_INFO;
    msg.qp_info = local_info;

    if (send_ctrl_msg(ctrl_fd, &msg) != 0) {
        LOG_ERR("Failed to send QP info");
        return -1;
    }

    /* Receive server's QP info */
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

    /* Connect QP */
    if (rdma_connect_qp(rctx, &msg.qp_info) != 0) {
        LOG_ERR("Failed to connect QP");
        return -1;
    }

    /* Send READY */
    memset(&msg, 0, sizeof(msg));
    msg.type = MSG_READY;
    if (send_ctrl_msg(ctrl_fd, &msg) != 0) {
        LOG_ERR("Failed to send READY");
        return -1;
    }

    /* Wait for server READY */
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
 * Warm-up: post RDMA writes and drain completions
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
        if (sig) {
            outstanding_signaled++;
        }

        /* Drain completions to avoid SQ overflow */
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

    /* Drain any remaining */
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
 * Core measurement: inject fault and detect error CQE
 *
 * Protocol:
 * 1. Post RDMA Writes continuously
 * 2. Send INJECT command to server, record t_inject_request
 * 3. Continue polling CQ in tight loop
 * 4. Receive ACK from server, record t_ack
 *    (ACK may arrive before or after error CQE -- handle both)
 * 5. When error CQE arrives, record t_error_cqe
 * 6. Compute detection latency
 * ---------------------------------------------------------------- */

static int run_one_measurement(int ctrl_fd, rdma_ctx_t *rctx,
                               fault_type_t fault, int iteration,
                               measurement_t *result)
{
    memset(result, 0, sizeof(*result));
    result->scenario = fault;
    result->iteration = iteration;
    result->valid = false;

    uint64_t wr_id = 0;
    int outstanding_signaled = 0;
    bool error_detected = false;
    bool ack_received = false;

    /* Post some initial writes to have traffic in flight */
    for (int i = 0; i < SIGNAL_INTERVAL * 2; i++) {
        bool sig = ((i % SIGNAL_INTERVAL) == 0);
        if (rdma_post_write(rctx, sig, wr_id++) != 0) {
            LOG_ERR("Failed to post initial writes");
            return -1;
        }
        if (sig) outstanding_signaled++;
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
     * Now enter tight poll loop:
     * - Poll CQ for error completions
     * - Check TCP socket (non-blocking) for ACK
     * - Continue posting writes (to keep probing the failed path)
     * - Timeout after ERROR_DETECT_TIMEOUT_SEC
     */
    uint64_t timeout_ns = (uint64_t)ERROR_DETECT_TIMEOUT_SEC * 1000000000ULL;
    uint64_t start_ns = result->t_inject_request_ns;
    int writes_since_signal = 0;

    /* Make TCP socket non-blocking for the polling loop */
    struct pollfd pfd;
    pfd.fd = ctrl_fd;
    pfd.events = POLLIN;

    while (!error_detected && !g_stop) {
        uint64_t now = get_time_ns();
        if (now - start_ns > timeout_ns) {
            LOG_ERR("Timeout waiting for error CQE (%d sec)", ERROR_DETECT_TIMEOUT_SEC);
            return -1;
        }

        /* --- Poll CQ --- */
        struct ibv_wc wc;
        int ne = rdma_poll_cq(rctx, &wc, 1);
        if (ne < 0) {
            LOG_ERR("CQ poll error");
            return -1;
        }
        if (ne > 0) {
            if (wc.status != IBV_WC_SUCCESS) {
                result->t_error_cqe_ns = get_time_ns();
                result->error_status = wc.status;
                result->vendor_err = wc.vendor_err;
                error_detected = true;
                LOG_INFO("  Error CQE detected: status=%d (%s) vendor_err=0x%x wr_id=%lu",
                         wc.status, ibv_wc_status_str(wc.status),
                         wc.vendor_err, wc.wr_id);
                /* Don't break yet -- still need ACK if not received */
            } else {
                if (outstanding_signaled > 0)
                    outstanding_signaled--;
            }
        }

        /* --- Check for ACK (non-blocking) --- */
        if (!ack_received) {
            int poll_ret = poll(&pfd, 1, 0); /* non-blocking */
            if (poll_ret > 0 && (pfd.revents & POLLIN)) {
                ctrl_msg_t ack_msg;
                if (recv_ctrl_msg(ctrl_fd, &ack_msg) == 0) {
                    if (ack_msg.type == MSG_INJECT_ACK) {
                        result->t_ack_ns = get_time_ns();
                        ack_received = true;
                    }
                }
            }
        }

        /* --- Post more writes (to keep probing) --- */
        if (!error_detected) {
            /*
             * Only post if we have room. With signaling every SIGNAL_INTERVAL,
             * we can have at most MAX_SEND_WR outstanding WRs.
             */
            if (outstanding_signaled < (MAX_SEND_WR / SIGNAL_INTERVAL) - 2) {
                writes_since_signal++;
                bool sig = (writes_since_signal >= SIGNAL_INTERVAL);
                if (sig) writes_since_signal = 0;

                int post_ret = rdma_post_write(rctx, sig, wr_id++);
                if (post_ret != 0) {
                    /*
                     * Post may fail if QP is already in error state.
                     * This is expected -- the QP error was detected via
                     * the post_send failure rather than a CQE.
                     * We still wait for the CQE from previously posted WRs.
                     */
                    LOG_INFO("  post_send failed (QP may be in error state), "
                             "waiting for error CQE from outstanding WRs");
                    /* Stop posting but keep polling */
                }
                if (sig && post_ret == 0) {
                    outstanding_signaled++;
                }
            }
        }

        /* If we have the error CQE, we can exit even without ACK for scenario C */
        if (error_detected && (ack_received || fault == FAULT_LINK_DOWN)) {
            break;
        }

        /* For scenario C, the TCP channel may break. Wait a bit then give up on ACK. */
        if (error_detected && !ack_received && fault == FAULT_LINK_DOWN) {
            break;
        }
    }

    if (!error_detected) {
        LOG_ERR("Measurement %d: no error detected (stopped=%d)", iteration, g_stop);
        return -1;
    }

    /* Compute detection latency */
    result->tcp_rtt_ns = 0;
    if (ack_received && result->t_ack_ns > result->t_inject_request_ns) {
        result->tcp_rtt_ns = result->t_ack_ns - result->t_inject_request_ns;
    }

    /*
     * Estimated fault injection time from client's clock:
     *   t_fault_est = t_inject_request + tcp_one_way_latency
     *   tcp_one_way_latency = tcp_rtt / 2
     *
     * For scenario C (link down), if ACK was not received, we report
     * total latency from inject request to error CQE.
     */
    uint64_t t_fault_est;
    if (ack_received) {
        t_fault_est = result->t_inject_request_ns + result->tcp_rtt_ns / 2;
    } else {
        /* Fallback: use inject request time (upper bound) */
        t_fault_est = result->t_inject_request_ns;
    }

    if (result->t_error_cqe_ns > t_fault_est) {
        result->detection_latency_ns = result->t_error_cqe_ns - t_fault_est;
    } else {
        /*
         * Error CQE arrived before our estimated fault time.
         * This can happen if TCP RTT estimate is too high, or if
         * the error was from a previously posted WR that was already
         * in flight when the fault was injected. Report 0.
         */
        result->detection_latency_ns = 0;
        LOG_WARN("  Error CQE arrived before estimated fault time "
                 "(t_error=%lu, t_fault_est=%lu)", result->t_error_cqe_ns, t_fault_est);
    }

    result->valid = true;

    LOG_INFO("  Iteration %d/%s: detection_latency=%.1f us "
             "(tcp_rtt=%.1f us, error_status=%d)",
             iteration, fault_type_names[fault],
             ns_to_us(result->detection_latency_ns),
             ns_to_us(result->tcp_rtt_ns),
             result->error_status);

    return 0;
}

/* ----------------------------------------------------------------
 * Request QP reset for next iteration
 * ---------------------------------------------------------------- */

static int request_reset(int ctrl_fd, rdma_ctx_t *rctx, fault_type_t fault,
                         int iteration)
{
    ctrl_msg_t msg;

    /*
     * For scenario C (link down), we need to tell server to bring
     * the link back up first, via a separate management channel.
     * Since we're using the same TCP connection (which may be on
     * the same NIC), we handle the case where the connection is
     * broken.
     *
     * In a real deployment, the management channel would be on a
     * separate NIC. For this experiment, we reconnect the TCP
     * session after the link is brought back up by the server's
     * watchdog timer or external script.
     *
     * For simplicity in this prototype: for scenario C, the server
     * runs a watchdog that brings the link back up after a timeout,
     * and the client reconnects.
     *
     * For scenarios A and B: we send RESET over the existing TCP
     * connection.
     */

    if (fault == FAULT_KILL) {
        /*
         * For kill scenario, the server process is dead.
         * The orchestration script handles restarting it.
         * Return a special value so the caller knows.
         */
        return 1; /* signal: need server restart */
    }

    /* Destroy local QP */
    rdma_destroy_qp(rctx);

    /* Send RESET request */
    memset(&msg, 0, sizeof(msg));
    msg.type = MSG_RESET;
    msg.iteration = iteration;
    if (send_ctrl_msg(ctrl_fd, &msg) != 0) {
        LOG_ERR("Failed to send RESET");
        return -1;
    }

    /* Wait for RESET_ACK (server has recreated its QP) */
    if (recv_ctrl_msg(ctrl_fd, &msg) != 0) {
        LOG_ERR("Failed to receive RESET_ACK");
        return -1;
    }
    if (msg.type != MSG_RESET_ACK) {
        LOG_ERR("Expected RESET_ACK, got type=%u", msg.type);
        return -1;
    }

    /* Recreate local QP */
    if (rdma_create_qp(rctx) != 0) {
        LOG_ERR("Failed to recreate QP");
        return -1;
    }

    /* Re-exchange QP info and connect */
    if (exchange_qp_info_and_connect(ctrl_fd, rctx) != 0) {
        LOG_ERR("Failed to re-establish RDMA connection");
        return -1;
    }

    return 0;
}

/* ----------------------------------------------------------------
 * Statistics computation
 * ---------------------------------------------------------------- */

static int cmp_uint64(const void *a, const void *b)
{
    uint64_t va = *(const uint64_t *)a;
    uint64_t vb = *(const uint64_t *)b;
    if (va < vb) return -1;
    if (va > vb) return 1;
    return 0;
}

typedef struct {
    double mean_us;
    double stddev_us;
    double median_us;
    double p99_us;
    double min_us;
    double max_us;
    int    count;
} stats_t;

static void compute_stats(const measurement_t *results, int n,
                          fault_type_t scenario, stats_t *st)
{
    /* Collect valid detection latencies */
    uint64_t *values = calloc(n, sizeof(uint64_t));
    if (!values) {
        LOG_FATAL("malloc failed");
    }

    int valid = 0;
    for (int i = 0; i < n; i++) {
        if (results[i].valid && results[i].scenario == scenario) {
            values[valid++] = results[i].detection_latency_ns;
        }
    }

    if (valid == 0) {
        memset(st, 0, sizeof(*st));
        free(values);
        return;
    }

    /* Sort for percentiles */
    qsort(values, valid, sizeof(uint64_t), cmp_uint64);

    /* Mean */
    double sum = 0;
    for (int i = 0; i < valid; i++) {
        sum += (double)values[i];
    }
    double mean = sum / valid;

    /* Stddev */
    double sq_sum = 0;
    for (int i = 0; i < valid; i++) {
        double diff = (double)values[i] - mean;
        sq_sum += diff * diff;
    }
    double stddev = (valid > 1) ? sqrt(sq_sum / (valid - 1)) : 0;

    st->mean_us   = mean / 1000.0;
    st->stddev_us = stddev / 1000.0;
    st->median_us = ns_to_us(values[valid / 2]);
    st->min_us    = ns_to_us(values[0]);
    st->max_us    = ns_to_us(values[valid - 1]);
    st->count     = valid;

    /* P99 */
    int p99_idx = (int)((double)(valid - 1) * 0.99);
    st->p99_us = ns_to_us(values[p99_idx]);

    free(values);
}

/* ----------------------------------------------------------------
 * CSV output
 * ---------------------------------------------------------------- */

static int write_csv_header(FILE *fp)
{
    fprintf(fp, "scenario,iteration,t_inject_request_ns,t_ack_ns,"
                "tcp_rtt_ns,t_error_cqe_ns,detection_latency_ns,"
                "error_status,error_vendor_err\n");
    return 0;
}

static int write_csv_row(FILE *fp, const measurement_t *m)
{
    if (!m->valid) return 0;

    fprintf(fp, "%s,%d,%lu,%lu,%lu,%lu,%lu,%d,0x%x\n",
            fault_type_names[m->scenario],
            m->iteration,
            m->t_inject_request_ns,
            m->t_ack_ns,
            m->tcp_rtt_ns,
            m->t_error_cqe_ns,
            m->detection_latency_ns,
            m->error_status,
            m->vendor_err);
    return 0;
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
        "\n"
        "Optional:\n"
        "  -d, --device <name>      IB device name (default: %s)\n"
        "  -i, --ib-port <num>      IB port number (default: %d)\n"
        "  -g, --gid-index <num>    GID index for RoCE (default: %d)\n"
        "  -p, --port <num>         TCP control port (default: %d)\n"
        "  -n, --iterations <num>   Iterations per scenario (default: %d)\n"
        "  -o, --output <file>      CSV output file (default: results/detection_latency.csv)\n"
        "  -S, --scenarios <list>   Comma-separated scenarios: a,b,c (default: a)\n"
        "                           a = QP->ERR, b = kill, c = link-down\n"
        "  -h, --help               Show this help\n",
        prog, DEFAULT_DEV_NAME, DEFAULT_IB_PORT, DEFAULT_GID_INDEX,
        DEFAULT_CTRL_PORT, DEFAULT_ITERATIONS);
}

static int parse_args(int argc, char **argv, client_config_t *cfg)
{
    /* Defaults */
    memset(cfg, 0, sizeof(*cfg));
    strncpy(cfg->dev_name, DEFAULT_DEV_NAME, sizeof(cfg->dev_name) - 1);
    cfg->ib_port = DEFAULT_IB_PORT;
    cfg->gid_index = DEFAULT_GID_INDEX;
    cfg->ctrl_port = DEFAULT_CTRL_PORT;
    cfg->iterations = DEFAULT_ITERATIONS;
    strncpy(cfg->output_file, "results/detection_latency.csv",
            sizeof(cfg->output_file) - 1);
    /* Default: only scenario A */
    cfg->scenarios[FAULT_QP_ERR] = true;

    static struct option long_options[] = {
        {"server",     required_argument, 0, 's'},
        {"device",     required_argument, 0, 'd'},
        {"ib-port",    required_argument, 0, 'i'},
        {"gid-index",  required_argument, 0, 'g'},
        {"port",       required_argument, 0, 'p'},
        {"iterations", required_argument, 0, 'n'},
        {"output",     required_argument, 0, 'o'},
        {"scenarios",  required_argument, 0, 'S'},
        {"help",       no_argument,       0, 'h'},
        {0, 0, 0, 0}
    };

    int opt;
    while ((opt = getopt_long(argc, argv, "s:d:i:g:p:n:o:S:h",
                              long_options, NULL)) != -1) {
        switch (opt) {
        case 's':
            strncpy(cfg->server_ip, optarg, sizeof(cfg->server_ip) - 1);
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
        case 'S': {
            /* Parse scenario list: "a,b,c" or "a" etc. */
            memset(cfg->scenarios, 0, sizeof(cfg->scenarios));
            char *tok = strtok(optarg, ",");
            while (tok) {
                if (strcmp(tok, "a") == 0 || strcmp(tok, "A") == 0)
                    cfg->scenarios[FAULT_QP_ERR] = true;
                else if (strcmp(tok, "b") == 0 || strcmp(tok, "B") == 0)
                    cfg->scenarios[FAULT_KILL] = true;
                else if (strcmp(tok, "c") == 0 || strcmp(tok, "C") == 0)
                    cfg->scenarios[FAULT_LINK_DOWN] = true;
                else {
                    LOG_ERR("Unknown scenario: '%s'", tok);
                    return -1;
                }
                tok = strtok(NULL, ",");
            }
            break;
        }
        case 'h':
            print_usage(argv[0]);
            exit(0);
        default:
            print_usage(argv[0]);
            return -1;
        }
    }

    if (strlen(cfg->server_ip) == 0) {
        LOG_ERR("Server IP is required (-s)");
        print_usage(argv[0]);
        return -1;
    }

    return 0;
}

/* ----------------------------------------------------------------
 * Run all iterations for one scenario
 * ---------------------------------------------------------------- */

static int run_scenario(client_config_t *cfg, fault_type_t fault,
                        measurement_t *results, int num_iterations,
                        FILE *csv_fp)
{
    LOG_INFO("========== Scenario %s: %d iterations ==========",
             fault_type_names[fault], num_iterations);

    /*
     * For each iteration:
     * 1. Connect TCP + establish RDMA
     * 2. Warm up
     * 3. Run measurement
     * 4. Record result
     * 5. Reset (or reconnect for kill/link-down)
     *
     * For scenario B (kill): each iteration needs a fresh TCP+RDMA connection
     * because the server process is killed. The orchestration script restarts it.
     *
     * For scenario A (QP->ERR): we can reuse the TCP connection and just
     * reset the QP between iterations.
     *
     * For scenario C (link-down): TCP may break. Like B, each iteration
     * may need a fresh connection.
     */

    int ctrl_fd = -1;
    rdma_ctx_t rctx;
    bool rdma_initialized = false;
    bool need_fresh_connection = true;

    for (int iter = 0; iter < num_iterations && !g_stop; iter++) {
        LOG_INFO("--- Iteration %d/%d for %s ---",
                 iter + 1, num_iterations, fault_type_names[fault]);

        if (need_fresh_connection) {
            /* Clean up any previous state */
            if (rdma_initialized) {
                rdma_destroy_ctx(&rctx);
                rdma_initialized = false;
            }
            if (ctrl_fd >= 0) {
                close(ctrl_fd);
                ctrl_fd = -1;
            }

            /* Connect TCP */
            ctrl_fd = tcp_connect(cfg->server_ip, cfg->ctrl_port);
            if (ctrl_fd < 0) {
                LOG_ERR("TCP connect failed, retrying in 2 seconds...");
                sleep(2);
                ctrl_fd = tcp_connect(cfg->server_ip, cfg->ctrl_port);
                if (ctrl_fd < 0) {
                    LOG_ERR("TCP connect failed again, aborting scenario");
                    return -1;
                }
            }

            /* Initialize RDMA */
            if (rdma_init_ctx(&rctx, cfg->dev_name, cfg->ib_port,
                              cfg->gid_index, RDMA_BUF_SIZE) != 0) {
                LOG_ERR("RDMA init failed");
                close(ctrl_fd);
                return -1;
            }
            rdma_initialized = true;

            if (iter == 0) {
                rdma_print_device_info(&rctx, cfg->dev_name);
            }

            /* Create QP and connect */
            if (rdma_create_qp(&rctx) != 0) {
                LOG_ERR("QP creation failed");
                goto cleanup;
            }

            if (exchange_qp_info_and_connect(ctrl_fd, &rctx) != 0) {
                LOG_ERR("QP info exchange failed");
                goto cleanup;
            }

            need_fresh_connection = false;
        }

        /* Warm up */
        if (warmup(&rctx) != 0) {
            LOG_ERR("Warmup failed");
            goto cleanup;
        }

        /* Run measurement */
        if (run_one_measurement(ctrl_fd, &rctx, fault, iter,
                                &results[iter]) != 0) {
            LOG_ERR("Measurement failed at iteration %d", iter);
            results[iter].valid = false;
            /* Try to continue with next iteration */
            need_fresh_connection = true;
            continue;
        }

        /* Write CSV row immediately (for crash resilience) */
        if (csv_fp) {
            write_csv_row(csv_fp, &results[iter]);
            fflush(csv_fp);
        }

        /* Reset for next iteration */
        if (iter < num_iterations - 1) {
            int reset_ret = request_reset(ctrl_fd, &rctx, fault, iter);
            if (reset_ret < 0) {
                LOG_ERR("Reset failed");
                need_fresh_connection = true;
            } else if (reset_ret == 1) {
                /* Scenario B: server was killed, need fresh connection */
                need_fresh_connection = true;
                /*
                 * Wait for the orchestration script to restart the server.
                 * The script should handle this, but add a delay here.
                 */
                LOG_INFO("Server process killed, waiting for restart...");
                sleep(3);
            }
        }
    }

    /* Send DONE message if TCP is still up */
    if (ctrl_fd >= 0 && fault != FAULT_KILL) {
        ctrl_msg_t done;
        memset(&done, 0, sizeof(done));
        done.type = MSG_DONE;
        send_ctrl_msg(ctrl_fd, &done); /* best effort */
    }

cleanup:
    if (rdma_initialized) {
        rdma_destroy_ctx(&rctx);
    }
    if (ctrl_fd >= 0) {
        close(ctrl_fd);
    }

    return 0;
}

/* ----------------------------------------------------------------
 * Main
 * ---------------------------------------------------------------- */

int main(int argc, char **argv)
{
    client_config_t cfg;
    if (parse_args(argc, argv, &cfg) != 0) {
        return EXIT_FAILURE;
    }

    /* Install signal handler */
    struct sigaction sa;
    sa.sa_handler = sigint_handler;
    sigemptyset(&sa.sa_mask);
    sa.sa_flags = 0;
    sigaction(SIGINT, &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);

    LOG_INFO("RDMA Fault Detection Latency Experiment - Client");
    LOG_INFO("Server: %s, Device: %s, Port: %d, GID: %d, Iterations: %d",
             cfg.server_ip, cfg.dev_name, cfg.ib_port, cfg.gid_index,
             cfg.iterations);

    /* Open CSV output file */
    FILE *csv_fp = fopen(cfg.output_file, "w");
    if (!csv_fp) {
        LOG_FATAL("Cannot open output file '%s': %s",
                  cfg.output_file, strerror(errno));
    }
    write_csv_header(csv_fp);

    /* Allocate results storage for all scenarios */
    int total_max = cfg.iterations * FAULT_NUM_TYPES;
    measurement_t *all_results = calloc(total_max, sizeof(measurement_t));
    if (!all_results) {
        LOG_FATAL("malloc failed for results");
    }

    int result_offset = 0;

    /* Run each enabled scenario */
    for (int s = 0; s < FAULT_NUM_TYPES && !g_stop; s++) {
        if (!cfg.scenarios[s]) continue;

        measurement_t *scenario_results = &all_results[result_offset];
        int ret = run_scenario(&cfg, (fault_type_t)s, scenario_results,
                               cfg.iterations, csv_fp);
        if (ret != 0) {
            LOG_ERR("Scenario %s failed", fault_type_names[s]);
        }
        result_offset += cfg.iterations;
    }

    fclose(csv_fp);

    /* Print summary statistics to stdout */
    printf("\n");
    printf("================================================================\n");
    printf("  RDMA Fault Detection Latency - Summary\n");
    printf("================================================================\n");
    printf("  Device: %s, Port: %d, GID index: %d\n",
           cfg.dev_name, cfg.ib_port, cfg.gid_index);
    printf("  Buffer: %d bytes, Signal interval: %d\n",
           RDMA_BUF_SIZE, SIGNAL_INTERVAL);
    printf("================================================================\n\n");

    result_offset = 0;
    for (int s = 0; s < FAULT_NUM_TYPES; s++) {
        if (!cfg.scenarios[s]) continue;

        stats_t st;
        compute_stats(&all_results[result_offset], cfg.iterations,
                      (fault_type_t)s, &st);

        if (st.count > 0) {
            printf("Scenario %s:\n", fault_type_names[s]);
            printf("  N=%d, median=%.1f us, mean=%.1f us, stddev=%.1f us\n",
                   st.count, st.median_us, st.mean_us, st.stddev_us);
            printf("  p99=%.1f us, min=%.1f us, max=%.1f us\n\n",
                   st.p99_us, st.min_us, st.max_us);
        } else {
            printf("Scenario %s: NO VALID RESULTS\n\n", fault_type_names[s]);
        }
        result_offset += cfg.iterations;
    }

    printf("Results written to: %s\n", cfg.output_file);

    free(all_results);
    return EXIT_SUCCESS;
}
