/*
 * client.c - RDMA QP Recovery Overhead Client (runs on Server A)
 *
 * Part of: GPU-Initiated RDMA Fault Recovery Research
 * Experiment 3: QP Recovery Overhead Decomposition
 *
 * Flow (per iteration):
 *   1. Post a burst of signaled RDMA Writes (traffic in flight).
 *   2. Send MSG_INJECT_NOW(QP_ERR); server transitions remote QP to ERR
 *      and sends MSG_INJECT_ACK.
 *   3. Tight-poll CQ until the first error CQE (IBV_WC_WR_FLUSH_ERR etc.)
 *      => t_detected.
 *   4. Drain any remaining flush CQEs. => drain
 *   5. Recovery, timed per stage (all ibv_modify_qp, no destroy/create):
 *        T1: ERR -> RESET
 *        T2: RESET -> INIT
 *        barrier1 (send + recv MSG_RECOVERY_INIT_DONE over TCP)
 *        T3: INIT -> RTR (uses cached remote_info — same QPN/rkey)
 *        T4: RTR -> RTS
 *        barrier2 (send + recv MSG_RECOVERY_RTS_DONE)
 *        T5: post 1 signaled RDMA Write, busy-poll for SUCCESS CQE.
 *   6. QP is back in RTS. Loop to next iteration.
 *
 * Between iterations, the TCP control channel, RDMA context, and QP
 * object are all preserved. remote_info and local_psn are reused (no
 * re-exchange) — valid because in-place modify keeps QPN/addr/rkey stable.
 *
 * Usage:
 *   ./client -s <server_ip> [-d <dev>] [-g <gid_idx>] [-n <iters>]
 *            [-o <output.csv>]
 */

#include "rdma_common.h"
#include "rdma_recovery.h"
#include "common3.h"

#define POST_BURST_COUNT (SIGNAL_INTERVAL * 4)

typedef struct {
    char server_ip[64];
    char dev_name[32];
    int  ib_port;
    int  gid_index;
    int  ctrl_port;
    int  iterations;
    char output_file[256];
} client_config_t;

typedef struct {
    int      iteration;

    uint64_t t_inject_request_ns;
    uint64_t t_ack_ns;
    uint64_t t_detected_ns;     /* first error CQE */
    uint64_t t_drain_done_ns;
    uint64_t t_reset_done_ns;
    uint64_t t_init_done_ns;
    uint64_t t_barrier1_ns;
    uint64_t t_rtr_done_ns;
    uint64_t t_rts_done_ns;
    uint64_t t_barrier2_ns;
    uint64_t t_write_cqe_ns;

    /* Derived per-stage latencies */
    uint64_t detection_ns;   /* t_detected - t_fault_est */
    uint64_t drain_ns;
    uint64_t T1_ns;          /* ERR -> RESET */
    uint64_t T2_ns;          /* RESET -> INIT */
    uint64_t coord1_ns;      /* TCP barrier 1 */
    uint64_t T3_ns;          /* INIT -> RTR */
    uint64_t T4_ns;          /* RTR -> RTS */
    uint64_t coord2_ns;      /* TCP barrier 2 */
    uint64_t T5_ns;          /* new write -> success CQE */
    uint64_t total_local_ns; /* T1+T2+T3+T4+T5 */
    uint64_t total_with_coord_ns;

    int      detect_error_status;
    bool     valid;
} measurement_t;

static volatile sig_atomic_t g_stop = 0;

static void sigint_handler(int sig)
{
    (void)sig;
    g_stop = 1;
}

/* ---------------------------------------------------------------- */
static int tcp_connect(const char *server_ip, int port)
{
    int sockfd = socket(AF_INET, SOCK_STREAM, 0);
    if (sockfd < 0) {
        LOG_ERR("socket() failed: %s", strerror(errno));
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

    LOG_INFO("Connecting to %s:%d ...", server_ip, port);
    if (connect(sockfd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        LOG_ERR("connect() failed: %s", strerror(errno));
        close(sockfd);
        return -1;
    }

    LOG_INFO("TCP control channel established");
    return sockfd;
}

/* ---------------------------------------------------------------- */
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

    if (recv_ctrl_msg(ctrl_fd, &msg) != 0 || msg.type != MSG_EXCHANGE_QP_INFO) {
        LOG_ERR("Failed to recv QP info");
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
    if (send_ctrl_msg(ctrl_fd, &msg) != 0) return -1;

    if (recv_ctrl_msg(ctrl_fd, &msg) != 0 || msg.type != MSG_READY) {
        LOG_ERR("Failed/unexpected server READY");
        return -1;
    }

    LOG_INFO("RDMA connection established");
    return 0;
}

/* ---------------------------------------------------------------- */
static int warmup(rdma_ctx_t *rctx)
{
    LOG_INFO("Warming up with %d RDMA Writes ...", WARMUP_COUNT);
    uint64_t wr_id = 0;
    int outstanding = 0;

    for (int i = 0; i < WARMUP_COUNT; i++) {
        bool sig = ((i % SIGNAL_INTERVAL) == 0);
        if (rdma_post_write(rctx, sig, wr_id++) != 0) return -1;
        if (sig) outstanding++;

        if (outstanding >= (MAX_SEND_WR / SIGNAL_INTERVAL) - 1) {
            struct ibv_wc wc;
            while (outstanding > 0) {
                int ne = rdma_poll_cq(rctx, &wc, 1);
                if (ne < 0) return -1;
                if (ne == 0) continue;
                if (wc.status != IBV_WC_SUCCESS) {
                    LOG_ERR("Warmup: error CQE status=%d", wc.status);
                    return -1;
                }
                outstanding--;
            }
        }
    }

    while (outstanding > 0) {
        struct ibv_wc wc;
        int ne = rdma_poll_cq(rctx, &wc, 1);
        if (ne < 0) return -1;
        if (ne == 0) continue;
        if (wc.status != IBV_WC_SUCCESS) {
            LOG_ERR("Warmup drain: error CQE status=%d", wc.status);
            return -1;
        }
        outstanding--;
    }

    LOG_INFO("Warm-up complete");
    return 0;
}

/* ----------------------------------------------------------------
 * One recovery measurement iteration.
 * ---------------------------------------------------------------- */
static int run_one_iteration(int ctrl_fd, rdma_ctx_t *rctx, int iter,
                             uint64_t *wr_id_inout,
                             measurement_t *m)
{
    memset(m, 0, sizeof(*m));
    m->iteration = iter;

    uint64_t wr_id = *wr_id_inout;
    int outstanding = 0;

    /* Drain any stale CQEs from the prior iteration. */
    {
        struct ibv_wc wc;
        while (rdma_poll_cq(rctx, &wc, 1) > 0) { }
    }

    /* Post a burst of signaled RDMA Writes so in-flight WRs exist
     * when the fault hits, producing error CQEs to detect. */
    for (int i = 0; i < POST_BURST_COUNT; i++) {
        bool sig = ((i % SIGNAL_INTERVAL) == 0);
        if (rdma_post_write(rctx, sig, wr_id++) != 0) {
            LOG_ERR("Failed to post burst");
            return -1;
        }
        if (sig) outstanding++;
    }

    /* Send INJECT_NOW */
    ctrl_msg_t inject_msg;
    memset(&inject_msg, 0, sizeof(inject_msg));
    inject_msg.type = MSG_INJECT_NOW;
    inject_msg.fault_type = FAULT_QP_ERR;
    inject_msg.iteration = iter;

    m->t_inject_request_ns = get_time_ns();
    if (send_ctrl_msg(ctrl_fd, &inject_msg) != 0) {
        LOG_ERR("Failed to send INJECT");
        return -1;
    }

    /* Read ACK (blocking — scenario A is reliable) */
    ctrl_msg_t ack_msg;
    if (recv_ctrl_msg(ctrl_fd, &ack_msg) != 0 ||
        ack_msg.type != MSG_INJECT_ACK) {
        LOG_ERR("Failed/unexpected ACK (type=%u)", ack_msg.type);
        return -1;
    }
    m->t_ack_ns = get_time_ns();
    uint64_t tcp_rtt_ns = (m->t_ack_ns > m->t_inject_request_ns)
                          ? (m->t_ack_ns - m->t_inject_request_ns) : 0;
    uint64_t t_fault_est = m->t_inject_request_ns + tcp_rtt_ns / 2;

    /* ---- Tight-poll CQ for the first error CQE ----
     * Keep posting writes during the poll so the HCA has in-flight WRs
     * that will fail after the remote QP enters ERR. Without this,
     * the initial burst may fully complete before the fault takes
     * effect, leaving nothing to error out. */
    bool error_seen = false;
    int writes_since_signal = 0;
    uint64_t deadline_ns = m->t_inject_request_ns +
                           (uint64_t)ERROR_DETECT_TIMEOUT_SEC * 1000000000ULL;

    while (!error_seen && !g_stop) {
        if (get_time_ns() > deadline_ns) {
            LOG_ERR("Timeout waiting for error CQE");
            return -1;
        }

        struct ibv_wc wc;
        int ne = rdma_poll_cq(rctx, &wc, 1);
        if (ne < 0) return -1;
        if (ne > 0) {
            if (wc.status != IBV_WC_SUCCESS) {
                m->t_detected_ns = get_time_ns();
                m->detect_error_status = wc.status;
                error_seen = true;
                continue;
            } else {
                if (outstanding > 0) outstanding--;
            }
        }

        /* Post more writes to keep HCA engaged (ibv_post_send will
         * fail once the QP transitions to ERR on this side, which is
         * expected and handled silently). */
        if (outstanding < (MAX_SEND_WR / SIGNAL_INTERVAL) - 2) {
            writes_since_signal++;
            bool sig = (writes_since_signal >= SIGNAL_INTERVAL);
            if (sig) writes_since_signal = 0;

            if (rdma_post_write(rctx, sig, wr_id++) == 0) {
                if (sig) outstanding++;
            }
            /* post_send failure silent — expected once client QP enters ERR */
        }
    }

    if (!error_seen) return -1;

    m->detection_ns = (m->t_detected_ns > t_fault_est)
                      ? (m->t_detected_ns - t_fault_est) : 0;

    /* ---- Drain remaining CQEs (flush errors on other outstanding WRs) ---- */
    if (rdma_drain_all_cq(rctx) < 0) return -1;
    m->t_drain_done_ns = get_time_ns();
    m->drain_ns = m->t_drain_done_ns - m->t_detected_ns;

    /* ---- T1: ERR -> RESET ---- */
    if (rdma_qp_to_reset(rctx) != 0) return -1;
    m->t_reset_done_ns = get_time_ns();
    m->T1_ns = m->t_reset_done_ns - m->t_drain_done_ns;

    /* ---- T2: RESET -> INIT ---- */
    if (rdma_qp_to_init(rctx) != 0) return -1;
    m->t_init_done_ns = get_time_ns();
    m->T2_ns = m->t_init_done_ns - m->t_reset_done_ns;

    /* ---- Barrier 1: both sides at INIT ---- */
    ctrl_msg_t bmsg;
    memset(&bmsg, 0, sizeof(bmsg));
    bmsg.type = MSG_RECOVERY_INIT_DONE;
    if (send_ctrl_msg(ctrl_fd, &bmsg) != 0) return -1;
    if (recv_ctrl_msg(ctrl_fd, &bmsg) != 0 ||
        bmsg.type != MSG_RECOVERY_INIT_DONE) {
        LOG_ERR("Barrier 1 failed (type=%u)", bmsg.type);
        return -1;
    }
    m->t_barrier1_ns = get_time_ns();
    m->coord1_ns = m->t_barrier1_ns - m->t_init_done_ns;

    /* ---- T3: INIT -> RTR ---- */
    if (rdma_qp_to_rtr(rctx) != 0) return -1;
    m->t_rtr_done_ns = get_time_ns();
    m->T3_ns = m->t_rtr_done_ns - m->t_barrier1_ns;

    /* ---- T4: RTR -> RTS ---- */
    if (rdma_qp_to_rts(rctx) != 0) return -1;
    m->t_rts_done_ns = get_time_ns();
    m->T4_ns = m->t_rts_done_ns - m->t_rtr_done_ns;

    /* ---- Barrier 2: both at RTS (server can receive writes) ---- */
    memset(&bmsg, 0, sizeof(bmsg));
    bmsg.type = MSG_RECOVERY_RTS_DONE;
    if (send_ctrl_msg(ctrl_fd, &bmsg) != 0) return -1;
    if (recv_ctrl_msg(ctrl_fd, &bmsg) != 0 ||
        bmsg.type != MSG_RECOVERY_RTS_DONE) {
        LOG_ERR("Barrier 2 failed (type=%u)", bmsg.type);
        return -1;
    }
    m->t_barrier2_ns = get_time_ns();
    m->coord2_ns = m->t_barrier2_ns - m->t_rts_done_ns;

    /* ---- T5: post one signaled write, wait for SUCCESS CQE ---- */
    if (rdma_post_write(rctx, true, wr_id++) != 0) {
        LOG_ERR("Failed to post probe write after recovery");
        return -1;
    }

    while (!g_stop) {
        if (get_time_ns() > deadline_ns) {
            LOG_ERR("Timeout waiting for post-recovery CQE");
            return -1;
        }
        struct ibv_wc wc;
        int ne = rdma_poll_cq(rctx, &wc, 1);
        if (ne < 0) return -1;
        if (ne == 0) continue;
        if (wc.status != IBV_WC_SUCCESS) {
            LOG_ERR("Post-recovery write failed: status=%d (%s)",
                    wc.status, ibv_wc_status_str(wc.status));
            return -1;
        }
        m->t_write_cqe_ns = get_time_ns();
        break;
    }
    m->T5_ns = m->t_write_cqe_ns - m->t_barrier2_ns;

    m->total_local_ns     = m->T1_ns + m->T2_ns + m->T3_ns + m->T4_ns + m->T5_ns;
    m->total_with_coord_ns = m->total_local_ns + m->coord1_ns + m->coord2_ns;

    *wr_id_inout = wr_id;
    m->valid = true;

    LOG_INFO("  iter %d: detect=%.1fus drain=%.1fus "
             "T1=%.1fus T2=%.1fus c1=%.1fus T3=%.1fus T4=%.1fus c2=%.1fus T5=%.1fus "
             "total_local=%.1fus",
             iter,
             ns_to_us(m->detection_ns), ns_to_us(m->drain_ns),
             ns_to_us(m->T1_ns), ns_to_us(m->T2_ns), ns_to_us(m->coord1_ns),
             ns_to_us(m->T3_ns), ns_to_us(m->T4_ns), ns_to_us(m->coord2_ns),
             ns_to_us(m->T5_ns), ns_to_us(m->total_local_ns));

    return 0;
}

/* ---------------------------------------------------------------- */
static void write_csv_header(FILE *fp)
{
    fprintf(fp,
        "iteration,"
        "t_inject_request_ns,t_ack_ns,t_detected_ns,t_drain_done_ns,"
        "t_reset_done_ns,t_init_done_ns,t_barrier1_ns,"
        "t_rtr_done_ns,t_rts_done_ns,t_barrier2_ns,t_write_cqe_ns,"
        "detection_ns,drain_ns,T1_ns,T2_ns,coord1_ns,T3_ns,T4_ns,"
        "coord2_ns,T5_ns,total_local_ns,total_with_coord_ns,"
        "detect_error_status\n");
}

static void write_csv_row(FILE *fp, const measurement_t *m)
{
    if (!m->valid) return;
    fprintf(fp,
        "%d,"
        "%lu,%lu,%lu,%lu,"
        "%lu,%lu,%lu,"
        "%lu,%lu,%lu,%lu,"
        "%lu,%lu,%lu,%lu,%lu,%lu,%lu,"
        "%lu,%lu,%lu,%lu,"
        "%d\n",
        m->iteration,
        m->t_inject_request_ns, m->t_ack_ns, m->t_detected_ns, m->t_drain_done_ns,
        m->t_reset_done_ns, m->t_init_done_ns, m->t_barrier1_ns,
        m->t_rtr_done_ns, m->t_rts_done_ns, m->t_barrier2_ns, m->t_write_cqe_ns,
        m->detection_ns, m->drain_ns, m->T1_ns, m->T2_ns, m->coord1_ns,
        m->T3_ns, m->T4_ns,
        m->coord2_ns, m->T5_ns, m->total_local_ns, m->total_with_coord_ns,
        m->detect_error_status);
}

/* ---------------------------------------------------------------- */
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
        "  -n, --iterations <num>   Iterations (default: %d)\n"
        "  -o, --output <file>      CSV output (default: results/recovery.csv)\n"
        "  -h, --help               Show this help\n",
        prog, DEFAULT_DEV_NAME, DEFAULT_IB_PORT, DEFAULT_GID_INDEX,
        DEFAULT_CTRL_PORT, DEFAULT_RECOVERY_ITERATIONS);
}

static int parse_args(int argc, char **argv, client_config_t *cfg)
{
    memset(cfg, 0, sizeof(*cfg));
    strncpy(cfg->dev_name, DEFAULT_DEV_NAME, sizeof(cfg->dev_name) - 1);
    cfg->ib_port    = DEFAULT_IB_PORT;
    cfg->gid_index  = DEFAULT_GID_INDEX;
    cfg->ctrl_port  = DEFAULT_CTRL_PORT;
    cfg->iterations = DEFAULT_RECOVERY_ITERATIONS;
    strncpy(cfg->output_file, "results/recovery.csv",
            sizeof(cfg->output_file) - 1);

    bool have_server = false;

    static struct option long_options[] = {
        {"server",     required_argument, 0, 's'},
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
    while ((opt = getopt_long(argc, argv, "s:d:i:g:p:n:o:h",
                              long_options, NULL)) != -1) {
        switch (opt) {
        case 's': strncpy(cfg->server_ip, optarg, sizeof(cfg->server_ip) - 1);
                  have_server = true; break;
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

    if (!have_server) {
        LOG_ERR("Server IP is required (-s)");
        print_usage(argv[0]);
        return -1;
    }
    return 0;
}

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

    LOG_INFO("Experiment 3 Client: server=%s dev=%s gid=%d iters=%d",
             cfg.server_ip, cfg.dev_name, cfg.gid_index, cfg.iterations);

    FILE *csv_fp = fopen(cfg.output_file, "w");
    if (!csv_fp)
        LOG_FATAL("Cannot open output '%s': %s",
                  cfg.output_file, strerror(errno));
    write_csv_header(csv_fp);

    int ctrl_fd = tcp_connect(cfg.server_ip, cfg.ctrl_port);
    if (ctrl_fd < 0) {
        fclose(csv_fp);
        return EXIT_FAILURE;
    }

    rdma_ctx_t rctx;
    if (rdma_init_ctx(&rctx, cfg.dev_name, cfg.ib_port,
                      cfg.gid_index, RDMA_BUF_SIZE) != 0) {
        close(ctrl_fd);
        fclose(csv_fp);
        LOG_FATAL("RDMA init failed");
    }
    rdma_print_device_info(&rctx, cfg.dev_name);

    if (rdma_create_qp(&rctx) != 0) goto cleanup;

    if (exchange_qp_info_and_connect(ctrl_fd, &rctx) != 0) goto cleanup;

    if (warmup(&rctx) != 0) goto cleanup;

    uint64_t wr_id = 0;
    int valid_count = 0;

    for (int iter = 0; iter < cfg.iterations && !g_stop; iter++) {
        measurement_t m;
        if (run_one_iteration(ctrl_fd, &rctx, iter, &wr_id, &m) != 0) {
            LOG_ERR("Iteration %d failed, aborting", iter);
            break;
        }
        write_csv_row(csv_fp, &m);
        fflush(csv_fp);
        if (m.valid) valid_count++;
    }

    /* Send DONE so server shuts down cleanly */
    ctrl_msg_t done;
    memset(&done, 0, sizeof(done));
    done.type = MSG_DONE;
    send_ctrl_msg(ctrl_fd, &done); /* best effort */

    LOG_INFO("Completed: %d/%d valid iterations", valid_count, cfg.iterations);

cleanup:
    rdma_destroy_ctx(&rctx);
    if (ctrl_fd >= 0) close(ctrl_fd);
    fclose(csv_fp);
    LOG_INFO("Results written to: %s", cfg.output_file);
    return EXIT_SUCCESS;
}
