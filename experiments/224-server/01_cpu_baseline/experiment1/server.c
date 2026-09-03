/*
 * server.c - RDMA Fault Injection Server (runs on Server B)
 *
 * Part of: GPU-Initiated RDMA Fault Recovery Research
 * Experiment 1: CPU-mediated fault detection baseline latency
 *
 * This program:
 *   1. Listens for TCP control connections from the client
 *   2. Registers an MR for the client to RDMA Write into
 *   3. Establishes an RC QP
 *   4. On command, performs fault injection:
 *      (a) Transitions local QP to IBV_QPS_ERR
 *      (b) Exits the process (simulating kill -9)
 *      (c) Brings the local NIC link down (requires root)
 *   5. For (a): supports QP reset for next iteration
 *   6. For (c): brings link back up after measurement
 *
 * Usage:
 *   ./server [-d <dev>] [-p <port>] [-i <ib-port>] [-g <gid-index>]
 *            [--nic <iface>]
 *
 * Note: Scenario (c) requires root privileges for `ip link set`.
 *
 * [UNTESTED: requires RDMA NIC]
 * Compile: gcc -O2 -Wall -Werror -o server server.c rdma_common.c \
 *          -libverbs -lrdmacm -lpthread -lm
 */

#include "rdma_common.h"

/* ----------------------------------------------------------------
 * Configuration
 * ---------------------------------------------------------------- */

typedef struct {
    char        dev_name[32];
    int         ib_port;
    int         gid_index;
    int         ctrl_port;
    char        nic_iface[32];  /* Network interface for link-down scenario */
    char        nic_ip[32];     /* IP address to restore after link-down (e.g. 10.0.0.3/24) */
} server_config_t;

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

static int tcp_listen_accept(int port)
{
    int listenfd = socket(AF_INET, SOCK_STREAM, 0);
    if (listenfd < 0) {
        LOG_ERR("socket() failed: %s", strerror(errno));
        return -1;
    }

    int opt = 1;
    if (setsockopt(listenfd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt)) < 0) {
        LOG_WARN("setsockopt SO_REUSEADDR failed: %s", strerror(errno));
    }

    /* Disable Nagle */
    if (setsockopt(listenfd, IPPROTO_TCP, TCP_NODELAY, &opt, sizeof(opt)) < 0) {
        LOG_WARN("setsockopt TCP_NODELAY failed: %s", strerror(errno));
    }

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

    /* Set TCP_NODELAY on accepted socket too */
    setsockopt(connfd, IPPROTO_TCP, TCP_NODELAY, &opt, sizeof(opt));

    /* Set timeouts */
    struct timeval tv;
    tv.tv_sec = TCP_TIMEOUT_SEC;
    tv.tv_usec = 0;
    setsockopt(connfd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    setsockopt(connfd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));

    char client_ip[INET_ADDRSTRLEN];
    inet_ntop(AF_INET, &client_addr.sin_addr, client_ip, sizeof(client_ip));
    LOG_INFO("Client connected from %s:%d", client_ip, ntohs(client_addr.sin_port));

    close(listenfd); /* Only accept one client */
    return connfd;
}

/* ----------------------------------------------------------------
 * Exchange QP info with client
 * ---------------------------------------------------------------- */

static int exchange_qp_info(int ctrl_fd, rdma_ctx_t *rctx)
{
    ctrl_msg_t msg;

    /* Receive client's QP info */
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

    /* Connect our QP to the client */
    if (rdma_connect_qp(rctx, &msg.qp_info) != 0) {
        LOG_ERR("Failed to connect QP");
        return -1;
    }

    /* Send our QP info */
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

    /* Wait for client READY */
    if (recv_ctrl_msg(ctrl_fd, &msg) != 0) {
        LOG_ERR("Failed to receive READY");
        return -1;
    }
    if (msg.type != MSG_READY) {
        LOG_ERR("Expected MSG_READY, got type=%u", msg.type);
        return -1;
    }

    /* Send READY */
    memset(&reply, 0, sizeof(reply));
    reply.type = MSG_READY;
    if (send_ctrl_msg(ctrl_fd, &reply) != 0) {
        LOG_ERR("Failed to send READY");
        return -1;
    }

    LOG_INFO("RDMA connection established, waiting for commands");
    return 0;
}

/* ----------------------------------------------------------------
 * Fault injection implementations
 * ---------------------------------------------------------------- */

static int inject_qp_err(rdma_ctx_t *rctx)
{
    LOG_INFO("FAULT INJECTION: transitioning QP to ERR state");
    return rdma_set_qp_err(rctx);
}

static void inject_process_kill(void)
{
    LOG_INFO("FAULT INJECTION: killing process (exit)");
    /*
     * Use _exit() to simulate an abrupt crash.
     * This skips cleanup handlers, which is what kill -9 does.
     * Resources (QP, MR, etc.) will be cleaned up by the kernel/driver.
     */
    _exit(137); /* 128 + 9 = SIGKILL exit code */
}

static int inject_link_down(const char *iface)
{
    LOG_INFO("FAULT INJECTION: bringing down interface %s", iface);

    char cmd[256];
    snprintf(cmd, sizeof(cmd), "ip link set %s down", iface);

    int ret = system(cmd);
    if (ret != 0) {
        LOG_ERR("Failed to bring down %s (exit code %d). Need root?", iface, ret);
        return -1;
    }

    LOG_INFO("Interface %s is DOWN", iface);
    return 0;
}

static int restore_link_up(const server_config_t *cfg, rdma_ctx_t *rctx)
{
    const char *iface = cfg->nic_iface;
    char cmd[256];

    LOG_INFO("Restoring interface %s UP", iface);
    snprintf(cmd, sizeof(cmd), "ip link set %s up", iface);
    if (system(cmd) != 0) {
        LOG_ERR("Failed to bring up %s", iface);
        return -1;
    }

    /* Wait for link state UP */
    for (int i = 0; i < LINK_UP_SETTLE_SEC; i++) {
        sleep(1);
        snprintf(cmd, sizeof(cmd),
                 "ip link show %s | grep -q 'state UP'", iface);
        if (system(cmd) == 0) {
            LOG_INFO("Link UP after %d seconds", i + 1);
            break;
        }
        LOG_INFO("  ... link not UP yet (%d/%d)", i + 1, LINK_UP_SETTLE_SEC);
    }

    /* Restore IP address (link down removes it) */
    if (strlen(cfg->nic_ip) > 0) {
        snprintf(cmd, sizeof(cmd),
                 "ip addr add %s dev %s 2>/dev/null; true", cfg->nic_ip, iface);
        int ip_ret = system(cmd);
        if (ip_ret != 0) {
            LOG_WARN("ip addr add returned %d (may already exist)", ip_ret);
        }
        LOG_INFO("Restored IP %s on %s", cfg->nic_ip, iface);
    }

    /* Wait for RoCE GID to repopulate */
    char gid_path[256];
    snprintf(gid_path, sizeof(gid_path),
             "/sys/class/infiniband/%s/ports/%d/gids/%d",
             cfg->dev_name, rctx->ib_port, rctx->gid_index);

    LOG_INFO("Waiting for GID[%d] to repopulate...", rctx->gid_index);
    for (int i = 0; i < LINK_UP_SETTLE_SEC; i++) {
        sleep(1);
        FILE *f = fopen(gid_path, "r");
        if (f) {
            char gid_str[64] = {0};
            if (fgets(gid_str, sizeof(gid_str), f)) {
                /* Check it's not all zeros */
                bool all_zero = true;
                for (int j = 0; gid_str[j]; j++) {
                    if (gid_str[j] != '0' && gid_str[j] != ':' &&
                        gid_str[j] != '\n') {
                        all_zero = false;
                        break;
                    }
                }
                if (!all_zero) {
                    LOG_INFO("GID[%d] restored: %s", rctx->gid_index, gid_str);
                    fclose(f);
                    /* Re-read GID into context */
                    ibv_query_gid(rctx->ctx, rctx->ib_port,
                                  rctx->gid_index,
                                  &rctx->local_gid);
                    sleep(1);
                    return 0;
                }
            }
            fclose(f);
        }
        LOG_INFO("  ... GID still empty (%d/%d)", i + 1, LINK_UP_SETTLE_SEC);
    }

    LOG_WARN("GID did not repopulate within %d seconds", LINK_UP_SETTLE_SEC);
    return -1;
}

/* ----------------------------------------------------------------
 * Handle one client session
 *
 * Processes commands until DONE or connection breaks.
 * Returns: 0 = clean shutdown, 1 = killed (scenario B), -1 = error
 * ---------------------------------------------------------------- */

static int handle_client(int ctrl_fd, rdma_ctx_t *rctx, server_config_t *cfg)
{
    fault_type_t last_fault = FAULT_NUM_TYPES; /* sentinel: no fault yet */

    /* Exchange QP info and establish RDMA connection */
    if (exchange_qp_info(ctrl_fd, rctx) != 0) {
        return -1;
    }

    /* Command processing loop */
    while (!g_stop) {
        ctrl_msg_t msg;
        if (recv_ctrl_msg(ctrl_fd, &msg) != 0) {
            LOG_INFO("Control channel closed (client disconnected or fault)");
            return 0;
        }

        switch (msg.type) {
        case MSG_INJECT_NOW: {
            fault_type_t fault = (fault_type_t)msg.fault_type;
            LOG_INFO("Received INJECT command: scenario=%s, iteration=%u",
                     fault_type_names[fault], msg.iteration);

            int inject_ret = 0;
            uint64_t t_injected = 0;

            switch (fault) {
            case FAULT_QP_ERR:
                inject_ret = inject_qp_err(rctx);
                t_injected = get_time_ns();
                break;

            case FAULT_KILL:
                /*
                 * Send ACK first, then kill ourselves.
                 * The ACK lets the client know the exact moment of injection.
                 */
                {
                    ctrl_msg_t ack;
                    memset(&ack, 0, sizeof(ack));
                    ack.type = MSG_INJECT_ACK;
                    ack.timestamp_ns = get_time_ns();
                    send_ctrl_msg(ctrl_fd, &ack); /* best effort */
                }
                inject_process_kill();
                /* Not reached */
                return 1;

            case FAULT_LINK_DOWN:
                inject_ret = inject_link_down(cfg->nic_iface);
                t_injected = get_time_ns();
                if (inject_ret == 0) {
                    ctrl_msg_t ack;
                    memset(&ack, 0, sizeof(ack));
                    ack.type = MSG_INJECT_ACK;
                    ack.timestamp_ns = t_injected;
                    send_ctrl_msg(ctrl_fd, &ack); /* best effort */
                    LOG_INFO("Link down injected, exiting for wrapper restart");
                    return 2;
                }
                break;

            default:
                LOG_ERR("Unknown fault type: %u", msg.fault_type);
                inject_ret = -1;
                break;
            }

            if (inject_ret != 0) {
                LOG_ERR("Fault injection failed");
                ctrl_msg_t err;
                memset(&err, 0, sizeof(err));
                err.type = MSG_ERROR;
                send_ctrl_msg(ctrl_fd, &err);
                continue;
            }

            /* Send ACK with injection timestamp */
            if (fault != FAULT_KILL) {
                ctrl_msg_t ack;
                memset(&ack, 0, sizeof(ack));
                ack.type = MSG_INJECT_ACK;
                ack.timestamp_ns = t_injected;

                /*
                 * For link-down, the TCP channel may be broken.
                 * Try to send ACK but don't fail if it doesn't work.
                 */
                if (fault == FAULT_LINK_DOWN) {
                    send_ctrl_msg(ctrl_fd, &ack); /* best effort */
                } else {
                    if (send_ctrl_msg(ctrl_fd, &ack) != 0) {
                        LOG_ERR("Failed to send INJECT_ACK");
                        return -1;
                    }
                }
            }
            last_fault = fault;
            break;
        }

        case MSG_RESET: {
            LOG_INFO("Received RESET command (iteration=%u)", msg.iteration);

            /*
             * If the previous fault was link-down, restore the link first.
             * We track the last fault type to know whether this is needed.
             */
            if (last_fault == FAULT_LINK_DOWN) {
                if (restore_link_up(cfg, rctx) != 0) {
                    LOG_ERR("Failed to restore link");
                    return -1;
                }

                /* Re-query port state after link recovery */
                int ret = ibv_query_port(rctx->ctx, rctx->ib_port,
                                         &rctx->port_attr);
                if (ret != 0) {
                    LOG_ERR("ibv_query_port failed after link restore: %s",
                            strerror(errno));
                    return -1;
                }
                if (rctx->port_attr.state != IBV_PORT_ACTIVE) {
                    LOG_ERR("Port not ACTIVE after link restore (state=%d)",
                            rctx->port_attr.state);
                    return -1;
                }
                LOG_INFO("Port confirmed ACTIVE after link restore");
            }

            /* Destroy and recreate QP */
            rdma_destroy_qp(rctx);

            if (rdma_create_qp(rctx) != 0) {
                LOG_ERR("Failed to recreate QP");
                return -1;
            }

            /* Send RESET_ACK */
            ctrl_msg_t ack;
            memset(&ack, 0, sizeof(ack));
            ack.type = MSG_RESET_ACK;
            if (send_ctrl_msg(ctrl_fd, &ack) != 0) {
                LOG_ERR("Failed to send RESET_ACK");
                return -1;
            }

            /* Re-exchange QP info (client will initiate) */
            if (exchange_qp_info(ctrl_fd, rctx) != 0) {
                LOG_ERR("Failed to re-establish RDMA connection after reset");
                return -1;
            }
            break;
        }

        case MSG_DONE:
            LOG_INFO("Received DONE command, shutting down gracefully");
            return 0;

        default:
            LOG_WARN("Unknown message type: %u, ignoring", msg.type);
            break;
        }
    }

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
        "Options:\n"
        "  -d, --device <name>      IB device name (default: %s)\n"
        "  -i, --ib-port <num>      IB port number (default: %d)\n"
        "  -g, --gid-index <num>    GID index for RoCE (default: %d)\n"
        "  -p, --port <num>         TCP control port (default: %d)\n"
        "  -I, --nic <iface>        NIC interface for link-down scenario\n"
        "                           (default: enp1s0f0np0)\n"
        "  -a, --ip <addr/mask>     IP to restore after link-down (e.g. 10.0.0.3/24)\n"
        "  -h, --help               Show this help\n"
        "\n"
        "Notes:\n"
        "  - Scenario (c) link-down requires root privileges.\n"
        "  - For scenario (b) kill, the process will exit. Use\n"
        "    run_experiment.sh to handle automatic restarts.\n",
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
    strncpy(cfg->nic_iface, "enp1s0f0np0", sizeof(cfg->nic_iface) - 1);

    static struct option long_options[] = {
        {"device",    required_argument, 0, 'd'},
        {"ib-port",   required_argument, 0, 'i'},
        {"gid-index", required_argument, 0, 'g'},
        {"port",      required_argument, 0, 'p'},
        {"nic",       required_argument, 0, 'I'},
        {"ip",        required_argument, 0, 'a'},
        {"help",      no_argument,       0, 'h'},
        {0, 0, 0, 0}
    };

    int opt;
    while ((opt = getopt_long(argc, argv, "d:i:g:p:I:a:h",
                              long_options, NULL)) != -1) {
        switch (opt) {
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
        case 'I':
            strncpy(cfg->nic_iface, optarg, sizeof(cfg->nic_iface) - 1);
            break;
        case 'a':
            strncpy(cfg->nic_ip, optarg, sizeof(cfg->nic_ip) - 1);
            break;
        case 'h':
            print_usage(argv[0]);
            exit(0);
        default:
            print_usage(argv[0]);
            return -1;
        }
    }

    return 0;
}

/* ----------------------------------------------------------------
 * Main
 * ---------------------------------------------------------------- */

int main(int argc, char **argv)
{
    server_config_t cfg;
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

    LOG_INFO("RDMA Fault Detection Latency Experiment - Server");
    LOG_INFO("Device: %s, Port: %d, GID: %d, NIC: %s",
             cfg.dev_name, cfg.ib_port, cfg.gid_index, cfg.nic_iface);

    /* Initialize RDMA context (persists across client sessions) */
    rdma_ctx_t rctx;
    if (rdma_init_ctx(&rctx, cfg.dev_name, cfg.ib_port,
                      cfg.gid_index, RDMA_BUF_SIZE) != 0) {
        LOG_FATAL("RDMA initialization failed");
    }
    rdma_print_device_info(&rctx, cfg.dev_name);

    /*
     * Main loop: accept client connections and handle commands.
     * This allows the server to be restarted between kill-scenario
     * iterations by the orchestration script.
     */
    while (!g_stop) {
        /* Create a fresh QP for each client session */
        if (rdma_create_qp(&rctx) != 0) {
            LOG_ERR("QP creation failed, retrying...");
            sleep(1);
            continue;
        }

        /* Accept client connection */
        int ctrl_fd = tcp_listen_accept(cfg.ctrl_port);
        if (ctrl_fd < 0) {
            LOG_ERR("Failed to accept client connection");
            rdma_destroy_qp(&rctx);
            if (g_stop) break;
            sleep(1);
            continue;
        }

        /* Handle client commands */
        int ret = handle_client(ctrl_fd, &rctx, &cfg);

        close(ctrl_fd);
        rdma_destroy_qp(&rctx);

        if (ret == 2) {
            /* Link-down scenario: exit process so wrapper can restore network */
            LOG_INFO("Exiting for link-down recovery (wrapper will restart)");
            rdma_destroy_ctx(&rctx);
            return 0;
        }

        LOG_INFO("Client session ended, waiting for next connection...");
    }

    rdma_destroy_ctx(&rctx);
    LOG_INFO("Server shutdown complete");
    return EXIT_SUCCESS;
}
