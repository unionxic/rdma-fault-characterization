/*
 * server.c - RDMA QP Recovery Overhead Server (runs on Server B)
 *
 * Part of: GPU-Initiated RDMA Fault Recovery Research
 * Experiment 3: QP Recovery Overhead Decomposition
 *
 * Differs from experiment1's server:
 *   - Only handles scenario A (QP->ERR). B (kill) and C (link-down) are
 *     excluded because they require full resource rebuild, not the
 *     in-place state transitions this experiment measures.
 *   - After injecting QP->ERR and sending ACK, the server immediately
 *     runs its own recovery sequence in parallel with the client,
 *     synchronizing at two TCP barriers (post-INIT, post-RTS).
 *   - QP is never destroyed between iterations. Same QPN, same MR,
 *     same remote_info reused throughout the session.
 *   - Optionally logs per-stage server-side timings to a CSV so the
 *     client's measured coordination time can be cross-checked.
 *
 * Usage:
 *   ./server [-d <dev>] [-p <port>] [-i <ib-port>] [-g <gid-index>]
 *            [-o <server_log.csv>]
 */

#include "rdma_common.h"
#include "rdma_recovery.h"
#include "common3.h"

typedef struct {
    char dev_name[32];
    int  ib_port;
    int  gid_index;
    int  ctrl_port;
    char output_file[256];
} server_config_t;

typedef struct {
    int      iteration;
    uint64_t t_inject_ns;
    uint64_t T1_ns;        /* ERR -> RESET */
    uint64_t T2_ns;        /* RESET -> INIT */
    uint64_t coord1_ns;    /* barrier after INIT */
    uint64_t T3_ns;        /* INIT -> RTR */
    uint64_t T4_ns;        /* RTR -> RTS */
    uint64_t coord2_ns;    /* barrier after RTS */
    uint64_t drain_ns;
    bool     valid;
} server_measurement_t;

static volatile sig_atomic_t g_stop = 0;

static void sigint_handler(int sig)
{
    (void)sig;
    g_stop = 1;
}

/* ---------------------------------------------------------------- */
static int tcp_listen_accept(int port)
{
    int listenfd = socket(AF_INET, SOCK_STREAM, 0);
    if (listenfd < 0) {
        LOG_ERR("socket() failed: %s", strerror(errno));
        return -1;
    }

    int opt = 1;
    setsockopt(listenfd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));
    setsockopt(listenfd, IPPROTO_TCP, TCP_NODELAY, &opt, sizeof(opt));

    struct sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = INADDR_ANY;
    addr.sin_port = htons(port);

    if (bind(listenfd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        LOG_ERR("bind(%d) failed: %s", port, strerror(errno));
        close(listenfd);
        return -1;
    }
    if (listen(listenfd, 1) < 0) {
        LOG_ERR("listen() failed: %s", strerror(errno));
        close(listenfd);
        return -1;
    }

    LOG_INFO("Listening on port %d for client connection...", port);

    struct sockaddr_in client_addr;
    socklen_t client_len = sizeof(client_addr);
    int connfd = accept(listenfd, (struct sockaddr *)&client_addr, &client_len);
    if (connfd < 0) {
        LOG_ERR("accept() failed: %s", strerror(errno));
        close(listenfd);
        return -1;
    }

    setsockopt(connfd, IPPROTO_TCP, TCP_NODELAY, &opt, sizeof(opt));

    struct timeval tv = { .tv_sec = TCP_TIMEOUT_SEC, .tv_usec = 0 };
    setsockopt(connfd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    setsockopt(connfd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));

    char client_ip[INET_ADDRSTRLEN];
    inet_ntop(AF_INET, &client_addr.sin_addr, client_ip, sizeof(client_ip));
    LOG_INFO("Client connected from %s:%d", client_ip, ntohs(client_addr.sin_port));

    close(listenfd);
    return connfd;
}

/* ---------------------------------------------------------------- */
static int exchange_qp_info(int ctrl_fd, rdma_ctx_t *rctx)
{
    ctrl_msg_t msg;

    if (recv_ctrl_msg(ctrl_fd, &msg) != 0) {
        LOG_ERR("Failed to receive client QP info");
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
    LOG_INFO("Client QP info: qpn=0x%x psn=0x%x rkey=0x%x gid=%s",
             msg.qp_info.qpn, msg.qp_info.psn, msg.qp_info.rkey, gid_str);

    if (rdma_connect_qp(rctx, &msg.qp_info) != 0) {
        LOG_ERR("Failed to connect QP");
        return -1;
    }

    qp_info_t local_info;
    rdma_get_local_info(rctx, &local_info);

    ctrl_msg_t reply;
    memset(&reply, 0, sizeof(reply));
    reply.type = MSG_EXCHANGE_QP_INFO;
    reply.qp_info = local_info;
    if (send_ctrl_msg(ctrl_fd, &reply) != 0) {
        LOG_ERR("Failed to send server QP info");
        return -1;
    }

    if (recv_ctrl_msg(ctrl_fd, &msg) != 0 || msg.type != MSG_READY) {
        LOG_ERR("Failed/unexpected client READY");
        return -1;
    }

    memset(&reply, 0, sizeof(reply));
    reply.type = MSG_READY;
    if (send_ctrl_msg(ctrl_fd, &reply) != 0) {
        LOG_ERR("Failed to send READY");
        return -1;
    }

    LOG_INFO("RDMA connection established");
    return 0;
}

/* ----------------------------------------------------------------
 * Server-side recovery sequence: runs in parallel with client, gated
 * at two TCP barriers so both sides converge on state transitions.
 * ---------------------------------------------------------------- */
static int run_server_recovery(int ctrl_fd, rdma_ctx_t *rctx,
                               server_measurement_t *m)
{
    /* Drain stale CQEs (flush errors on in-flight WRs after ERR).
     * We weren't posting writes from the server, but flushing is cheap
     * and keeps parity with the client. */
    uint64_t t_drain_start = get_time_ns();
    if (rdma_drain_all_cq(rctx) < 0)
        return -1;
    uint64_t t0 = get_time_ns();
    m->drain_ns = t0 - t_drain_start;

    if (rdma_qp_to_reset(rctx) != 0) return -1;
    uint64_t t1 = get_time_ns();
    m->T1_ns = t1 - t0;

    if (rdma_qp_to_init(rctx) != 0) return -1;
    uint64_t t2 = get_time_ns();
    m->T2_ns = t2 - t1;

    /* Barrier 1: exchange INIT_DONE so neither side proceeds to RTR
     * before the peer is at INIT. Send then recv; TCP full-duplex
     * handles simultaneous sends from both sides. */
    ctrl_msg_t bmsg;
    memset(&bmsg, 0, sizeof(bmsg));
    bmsg.type = MSG_RECOVERY_INIT_DONE;
    if (send_ctrl_msg(ctrl_fd, &bmsg) != 0) return -1;
    if (recv_ctrl_msg(ctrl_fd, &bmsg) != 0 ||
        bmsg.type != MSG_RECOVERY_INIT_DONE) {
        LOG_ERR("Barrier 1 failed (type=%u)", bmsg.type);
        return -1;
    }
    uint64_t t_bar1 = get_time_ns();
    m->coord1_ns = t_bar1 - t2;

    if (rdma_qp_to_rtr(rctx) != 0) return -1;
    uint64_t t3 = get_time_ns();
    m->T3_ns = t3 - t_bar1;

    if (rdma_qp_to_rts(rctx) != 0) return -1;
    uint64_t t4 = get_time_ns();
    m->T4_ns = t4 - t3;

    /* Barrier 2: ensure server is at RTS (able to receive writes)
     * before the client's T5 write is timed. */
    memset(&bmsg, 0, sizeof(bmsg));
    bmsg.type = MSG_RECOVERY_RTS_DONE;
    if (send_ctrl_msg(ctrl_fd, &bmsg) != 0) return -1;
    if (recv_ctrl_msg(ctrl_fd, &bmsg) != 0 ||
        bmsg.type != MSG_RECOVERY_RTS_DONE) {
        LOG_ERR("Barrier 2 failed (type=%u)", bmsg.type);
        return -1;
    }
    uint64_t t_bar2 = get_time_ns();
    m->coord2_ns = t_bar2 - t4;

    m->valid = true;
    return 0;
}

/* ---------------------------------------------------------------- */
static int handle_client(int ctrl_fd, rdma_ctx_t *rctx, FILE *csv_fp)
{
    if (exchange_qp_info(ctrl_fd, rctx) != 0)
        return -1;

    int iter = 0;
    while (!g_stop) {
        ctrl_msg_t msg;
        if (recv_ctrl_msg(ctrl_fd, &msg) != 0) {
            LOG_INFO("Control channel closed");
            return 0;
        }

        switch (msg.type) {
        case MSG_INJECT_NOW: {
            fault_type_t fault = (fault_type_t)msg.fault_type;
            if (fault != FAULT_QP_ERR) {
                LOG_ERR("Experiment 3 only supports scenario A (QP_ERR), got %u",
                        fault);
                ctrl_msg_t err;
                memset(&err, 0, sizeof(err));
                err.type = MSG_ERROR;
                send_ctrl_msg(ctrl_fd, &err);
                continue;
            }

            LOG_INFO("Received INJECT (iter=%u): transitioning QP to ERR",
                     msg.iteration);

            if (rdma_set_qp_err(rctx) != 0) {
                LOG_ERR("Failed to inject QP_ERR");
                return -1;
            }

            server_measurement_t sm;
            memset(&sm, 0, sizeof(sm));
            sm.iteration = msg.iteration;
            sm.t_inject_ns = get_time_ns();

            /* Send ACK with injection timestamp */
            ctrl_msg_t ack;
            memset(&ack, 0, sizeof(ack));
            ack.type = MSG_INJECT_ACK;
            ack.timestamp_ns = sm.t_inject_ns;
            if (send_ctrl_msg(ctrl_fd, &ack) != 0) {
                LOG_ERR("Failed to send ACK");
                return -1;
            }

            /* Run server-side recovery in parallel with client */
            if (run_server_recovery(ctrl_fd, rctx, &sm) != 0) {
                LOG_ERR("Server-side recovery failed at iter %d", iter);
                return -1;
            }

            if (csv_fp && sm.valid) {
                fprintf(csv_fp,
                        "%d,%lu,%lu,%lu,%lu,%lu,%lu,%lu,%lu\n",
                        sm.iteration, sm.t_inject_ns, sm.drain_ns,
                        sm.T1_ns, sm.T2_ns, sm.coord1_ns,
                        sm.T3_ns, sm.T4_ns, sm.coord2_ns);
                fflush(csv_fp);
            }

            LOG_INFO("  server recovery: T1=%.1fus T2=%.1fus c1=%.1fus "
                     "T3=%.1fus T4=%.1fus c2=%.1fus",
                     ns_to_us(sm.T1_ns), ns_to_us(sm.T2_ns),
                     ns_to_us(sm.coord1_ns), ns_to_us(sm.T3_ns),
                     ns_to_us(sm.T4_ns), ns_to_us(sm.coord2_ns));
            iter++;
            break;
        }

        case MSG_DONE:
            LOG_INFO("DONE received, shutting down");
            return 0;

        default:
            LOG_WARN("Unknown message type %u, ignoring", msg.type);
            break;
        }
    }
    return 0;
}

/* ---------------------------------------------------------------- */
static void print_usage(const char *prog)
{
    fprintf(stderr,
        "Usage: %s [options]\n"
        "\n"
        "Options:\n"
        "  -d, --device <name>      IB device name (default: %s)\n"
        "  -i, --ib-port <num>      IB port number (default: %d)\n"
        "  -g, --gid-index <num>    GID index for RoCE (default: %d)\n"
        "  -p, --port <num>         TCP control port (default: %d)\n"
        "  -o, --output <file>      Server-side CSV log (default: none)\n"
        "  -h, --help               Show this help\n",
        prog, DEFAULT_DEV_NAME, DEFAULT_IB_PORT, DEFAULT_GID_INDEX,
        DEFAULT_CTRL_PORT);
}

static int parse_args(int argc, char **argv, server_config_t *cfg)
{
    memset(cfg, 0, sizeof(*cfg));
    strncpy(cfg->dev_name, DEFAULT_DEV_NAME, sizeof(cfg->dev_name) - 1);
    cfg->ib_port = DEFAULT_IB_PORT;
    cfg->gid_index = DEFAULT_GID_INDEX;
    cfg->ctrl_port = DEFAULT_CTRL_PORT;

    static struct option long_options[] = {
        {"device",    required_argument, 0, 'd'},
        {"ib-port",   required_argument, 0, 'i'},
        {"gid-index", required_argument, 0, 'g'},
        {"port",      required_argument, 0, 'p'},
        {"output",    required_argument, 0, 'o'},
        {"help",      no_argument,       0, 'h'},
        {0, 0, 0, 0}
    };

    int opt;
    while ((opt = getopt_long(argc, argv, "d:i:g:p:o:h",
                              long_options, NULL)) != -1) {
        switch (opt) {
        case 'd': strncpy(cfg->dev_name, optarg, sizeof(cfg->dev_name) - 1); break;
        case 'i': cfg->ib_port = atoi(optarg); break;
        case 'g': cfg->gid_index = atoi(optarg); break;
        case 'p': cfg->ctrl_port = atoi(optarg); break;
        case 'o': strncpy(cfg->output_file, optarg, sizeof(cfg->output_file) - 1); break;
        case 'h': print_usage(argv[0]); exit(0);
        default:  print_usage(argv[0]); return -1;
        }
    }
    return 0;
}

int main(int argc, char **argv)
{
    server_config_t cfg;
    if (parse_args(argc, argv, &cfg) != 0)
        return EXIT_FAILURE;

    struct sigaction sa;
    sa.sa_handler = sigint_handler;
    sigemptyset(&sa.sa_mask);
    sa.sa_flags = 0;
    sigaction(SIGINT, &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);

    LOG_INFO("Experiment 3 Server: dev=%s port=%d gid=%d ctrl_port=%d",
             cfg.dev_name, cfg.ib_port, cfg.gid_index, cfg.ctrl_port);

    FILE *csv_fp = NULL;
    if (strlen(cfg.output_file) > 0) {
        csv_fp = fopen(cfg.output_file, "w");
        if (!csv_fp)
            LOG_FATAL("Cannot open server CSV '%s': %s",
                      cfg.output_file, strerror(errno));
        fprintf(csv_fp,
                "iteration,t_inject_ns,drain_ns,"
                "T1_ns,T2_ns,coord1_ns,T3_ns,T4_ns,coord2_ns\n");
    }

    rdma_ctx_t rctx;
    if (rdma_init_ctx(&rctx, cfg.dev_name, cfg.ib_port,
                      cfg.gid_index, RDMA_BUF_SIZE) != 0) {
        LOG_FATAL("RDMA initialization failed");
    }
    rdma_print_device_info(&rctx, cfg.dev_name);

    while (!g_stop) {
        if (rdma_create_qp(&rctx) != 0) {
            LOG_ERR("QP creation failed, retrying...");
            sleep(1);
            continue;
        }

        int ctrl_fd = tcp_listen_accept(cfg.ctrl_port);
        if (ctrl_fd < 0) {
            rdma_destroy_qp(&rctx);
            if (g_stop) break;
            sleep(1);
            continue;
        }

        int ret = handle_client(ctrl_fd, &rctx, csv_fp);
        (void)ret;

        close(ctrl_fd);
        rdma_destroy_qp(&rctx);
        LOG_INFO("Session ended, waiting for next connection");
    }

    rdma_destroy_ctx(&rctx);
    if (csv_fp) fclose(csv_fp);
    LOG_INFO("Server shutdown complete");
    return EXIT_SUCCESS;
}
