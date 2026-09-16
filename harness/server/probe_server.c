/*
 * probe_server.c - responder side of the unified RDMA fault harness.
 *
 * Runs on the responder node (e.g. sunny, mlx5_0). One long-lived process:
 *   - accepts one client control connection
 *   - brings up an RC QP, coordinates per-trial fault arming and recovery
 *
 * The server is a cooperative peer: for server-induced faults it acts on
 * command; for client-side faults it just responds. All QP state changes are
 * mirrored so QP-only / full-rebuild recovery stays PSN-consistent both ends.
 *
 * Faults handled fully in-band (server stays alive, no root):
 *   local_qp_err, rem_access, rem_inv_req, rnr, retry_server_qp_err, partial_write
 * Faults needing process death / root are driven by the runner (proc_kill,
 * link_down); this server also supports proc_kill via the KILL command.
 */
#define _GNU_SOURCE
#include "probe.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <getopt.h>

static uint32_t pick_psn(void) { return (uint32_t)(now_ns() & 0xffffff); }

/* RoCE netdev to toggle for the link_down fault (from -I / $PROBE_IFACE) */
static const char *g_iface = NULL;

/* bring the local RoCE netdev up/down via passwordless sudo. Requires a sudoers
 * rule for `ip` (or full NOPASSWD); we never embed a password. Returns 0 on ok. */
static int link_set(const char *state) {
    if (!g_iface || !g_iface[0]) { fprintf(stderr, "[server] link_%s: no iface set\n", state); return -1; }
    char cmd[256];
    snprintf(cmd, sizeof(cmd), "sudo -n ip link set %s %s", g_iface, state);
    int rc = system(cmd);
    if (rc != 0) fprintf(stderr, "[server] '%s' failed (rc=%d) - need NOPASSWD sudo for ip\n", cmd, rc);
    return rc == 0 ? 0 : -1;
}
/* wait until the RDMA port reaches the wanted state (link comes back up async) */
static void wait_port_state(probe_ep_t *ep, enum ibv_port_state want, int tries) {
    for (int i = 0; i < tries; i++) {
        struct ibv_port_attr pa;
        if (!ibv_query_port(ep->ctx, ep->ib_port, &pa) && pa.state == want) return;
        usleep(200000);
    }
}

/* exchange dest (server sends first, then receives) and go RTR->RTS */
static int connect_qp_server(probe_ep_t *ep, int fd, uint32_t local_psn) {
    probe_dest_t local, remote;
    ep_fill_dest(ep, local_psn, &local);
    if (tcp_send_all(fd, &local, sizeof(local)) < 0) return -1;
    if (tcp_recv_all(fd, &remote, sizeof(remote)) < 0) return -1;
    if (ep_to_rtr(ep, &remote) < 0) return -1;
    if (ep_to_rts(ep, local_psn) < 0) return -1;
    return 0;
}

/* bring the server QP up from scratch (full rebuild) or via reset (qp-only) */
static int server_bring_up(probe_ep_t *ep, int fd, bool full_rebuild) {
    uint32_t psn = pick_psn();
    if (full_rebuild) {
        ep_destroy_qp(ep);
        if (ep_create_qp(ep) < 0) return -1;
    } else {
        if (ep_to_reset(ep) < 0) return -1;
    }
    if (ep_to_init(ep) < 0) return -1;
    return connect_qp_server(ep, fd, psn);
}

int main(int argc, char **argv) {
    const char *dev = "mlx5_0";
    int ib_port = 1, gid_index = 3, ctrl_port = PROBE_DEFAULT_PORT, cpu = -1;
    g_iface = getenv("PROBE_IFACE");
    int opt;
    while ((opt = getopt(argc, argv, "d:i:g:p:C:I:h")) != -1) {
        switch (opt) {
            case 'd': dev = optarg; break;
            case 'i': ib_port = atoi(optarg); break;
            case 'g': gid_index = atoi(optarg); break;
            case 'p': ctrl_port = atoi(optarg); break;
            case 'C': cpu = atoi(optarg); break;
            case 'I': g_iface = optarg; break;   /* RoCE netdev for link_down fault */
            case 'h': default:
                fprintf(stderr, "usage: %s -d dev -i port -g gid -p ctrlport [-C cpu] [-I roce_netdev]\n", argv[0]);
                return (opt == 'h') ? 0 : 1;
        }
    }
    pin_to_cpu(cpu);

    probe_ep_t ep;
    if (ep_open(&ep, dev, (uint8_t)ib_port, gid_index, PROBE_BUF_SIZE) < 0) return 1;
    if (ep_create_qp(&ep) < 0) { ep_close(&ep); return 1; }
    if (ep_to_init(&ep) < 0) { ep_close(&ep); return 1; }

    int lfd = tcp_server_listen(ctrl_port);
    if (lfd < 0) { ep_close(&ep); return 1; }
    fprintf(stderr, "[server] %s port %d gid %d, listening on tcp %d\n",
            dev, ib_port, gid_index, ctrl_port);

    int fd = tcp_server_accept(lfd);
    if (fd < 0) { close(lfd); ep_close(&ep); return 1; }
    fprintf(stderr, "[server] client connected\n");

    /* handshake */
    char line[512];
    if (ctrl_recv_line(fd, line, sizeof(line)) < 0 || strcmp(line, "HELLO") != 0) {
        fprintf(stderr, "[server] bad hello: '%s'\n", line); goto done;
    }
    if (connect_qp_server(&ep, fd, pick_psn()) < 0) goto done;
    if (ctrl_send_line(fd, "SYNC") < 0) goto done;

    /* trial loop */
    for (;;) {
        int n = ctrl_recv_line(fd, line, sizeof(line));
        if (n < 0) { fprintf(stderr, "[server] client closed\n"); break; }
        if (strcmp(line, "BYE") == 0) { fprintf(stderr, "[server] bye\n"); break; }

        char fault_s[64] = {0}, recov_s[64] = {0};
        if (sscanf(line, "TRIAL %63s %63s", fault_s, recov_s) != 2) {
            fprintf(stderr, "[server] bad trial line: '%s'\n", line); break;
        }
        fault_type_t fault = fault_from_name(fault_s);
        if (ctrl_send_line(fd, "OK") < 0) break;

        /* barrier: wait for GO */
        if (ctrl_recv_line(fd, line, sizeof(line)) < 0 || strcmp(line, "GO") != 0) break;

        /* proc_kill: die on GO, BEFORE acking anything, so no in-flight write can
         * be ACKed in a race window; the requester then hits RETRY_EXC cleanly. */
        if (fault == FAULT_RETRY_PROC_KILL) {
            fprintf(stderr, "[server] proc_kill: exiting on command\n");
            ep_close(&ep); close(fd); close(lfd);
            return 0;
        }
        /* other server-induced faults act here */
        if (fault == FAULT_RETRY_LINK_DOWN) {
            link_set("down");  /* control channel is on the mgmt IP, so it survives */
        }
        if (fault == FAULT_RETRY_SERVER_QP_ERR) {
            if (ep_to_err(&ep) < 0) break;
        }
        if (ctrl_send_line(fd, "GOACK") < 0) break;

        /* baseline the responder NIC's rx traffic at fault time; the requester's
         * retransmits over the next ~3.7s will advance it iff our NIC is alive and
         * reachable — this is the signal that disambiguates the RETRY_EXC causes. */
        uint64_t rx0 = port_counter_read(ep.dev_name, ep.ib_port, "port_rcv_packets");

        /* recovery coordination (client drives), answering PROBE liveness queries */
        bool done = false, fatal = false;
        while (!done) {
            n = ctrl_recv_line(fd, line, sizeof(line));
            if (n < 0) { fatal = true; break; }
            if (strcmp(line, "PROBE") == 0) {
                uint64_t rx = port_counter_read(ep.dev_name, ep.ib_port, "port_rcv_packets");
                long rxd = (rx0 != UINT64_MAX && rx != UINT64_MAX) ? (long)(rx - rx0) : -1;
                char rep[64];
                snprintf(rep, sizeof(rep), "PROBED %ld", rxd);
                if (ctrl_send_line(fd, rep) < 0) { fatal = true; break; }
                continue;   /* peer is alive; keep waiting for RECOVER/NORECOVER */
            }
            if (strncmp(line, "RECOVER", 7) == 0) {
                char method_s[64] = {0};
                recovery_method_t method = RECOVER_QP_ONLY;
                if (sscanf(line, "RECOVER %63s", method_s) == 1)
                    method = recovery_from_name(method_s);
                bool full = (method == RECOVER_FULL_REBUILD);
                if (fault == FAULT_RETRY_LINK_DOWN) {  /* restore the link before rewiring */
                    link_set("up");
                    wait_port_state(&ep, IBV_PORT_ACTIVE, 100);
                }
                if (server_bring_up(&ep, fd, full) < 0) { fprintf(stderr, "[server] rebuild failed\n"); fatal = true; break; }
                if (ctrl_send_line(fd, "RECOK") < 0) { fatal = true; break; }
                done = true;
            } else if (strcmp(line, "NORECOVER") == 0) {
                if (server_bring_up(&ep, fd, false) < 0) { fatal = true; break; }
                if (ctrl_send_line(fd, "RECOK") < 0) { fatal = true; break; }
                done = true;
            } else {
                fprintf(stderr, "[server] unexpected: '%s'\n", line); fatal = true; break;
            }
        }
        if (fatal) break;
    }

done:
    close(fd);
    close(lfd);
    ep_close(&ep);
    return 0;
}
