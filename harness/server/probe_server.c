/*
 * probe_server.c - responder side of the unified RDMA fault harness.
 *
 * Runs on the responder node (e.g. sunny, mlx5_0). One process per client run:
 *   - accepts one client control connection
 *   - brings up an RC QP, coordinates per-trial fault arming and recovery
 *
 * The server is a cooperative peer: for server-induced faults it acts on
 * command; for client-side faults it just responds. All QP state changes are
 * mirrored so QP-only / full-rebuild recovery stays PSN-consistent both ends.
 *
 * Per-fault responder behaviour:
 *   none (F0 control)   : nothing
 *   local_qp_err, rem_access, rem_inv_req, rnr : nothing (requester-side trigger)
 *   partial_write       : buffer zeroed at TRIAL time, so the requester can measure
 *                         the bytes that actually landed by RDMA-READ readback
 *   retry_server_qp_err : own QP -> ERR on GO (stops ACKing)
 *   retry_proc_kill     : this process exits on GO, before acking anything (the
 *                         runner restarts it per trial). There is no KILL command.
 *                         The exit is graceful: the QP, MR and device are closed first.
 *   retry_proc_sigkill  : this process raises SIGKILL on GO, before acking anything:
 *                         a real crash, the kernel tears the resources down. The
 *                         runner restarts it per trial, as for retry_proc_kill.
 *   live_* (live_peer study, harness/live_peer/EXPERIMENT.md): the process stays alive but is
 *                         not ready. Each logs "[server] fault_applied fault=<f> mono_ns=<n>".
 *     live_qp_reset     : own QP -> RESET on GO
 *     live_qp_init      : own QP -> RESET -> INIT on GO
 *     live_qp_rtr       : own QP re-armed RESET -> INIT -> RTR with its saved receive PSN
 *     live_transient    : own QP -> RESET -> INIT on GO; LIVE_TRANSIENT_MS (1250) after GOACK it is
 *                         re-armed to RTS with the saved PSNs ("[server] rearm ...")
 *     live_stop_err     : own QP -> ERR, GOACK, then this process stops itself for LIVE_STOP_MS
 *                         (8000) through the lp_stall helper (common/lp_stall.h)
 *     live_stop_ok      : GOACK, then the same stop with a healthy QP
 *     live_ctl_close    : own QP -> ERR, GOACK, then the control connection is closed while the
 *                         process lives on; a new connection gets "ALIVE <pid> <QP state>" to
 *                         "ALIVE?" (20 s), then the server exits normally
 *     live_qp_recreate  : own QP destroyed and a new one created and left in INIT
 *   RESYNC <n> is answered with RESYNCED <n> (the client drops late answers after a stop).
 *   retry_link_down     : `sudo -n ip link set dev <iface> down` on GO. Checked at
 *                         TRIAL time: if the link cannot be toggled the reply is
 *                         "ERR link_down_unavailable <why>" instead of "OK".
 *                         The link is restored on EVERY exit path: RECOVER,
 *                         NORECOVER, BYE, unexpected message, client closed, fatal
 *                         error, normal exit, SIGTERM/SIGINT/SIGHUP (the runner uses
 *                         `timeout`, which sends SIGTERM), and atexit as a backstop.
 *                         PROBE_LINK_DRYRUN=1 makes every toggle log
 *                         "[server] DRYRUN link <state>" instead of touching the link.
 *
 * After the fault the client may send QUERY; the reply is
 *   QUERIED <state of our QP (ibv_query_qp)> <our async events since GO>
 * (async_mon_format in common/probe.c). A thread records the async events of our
 * device context. At exit the server prints how long its own teardown took.
 */
#define _GNU_SOURCE
#include "probe.h"
#include "lp_stall.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <unistd.h>
#include <getopt.h>
#include <signal.h>
#include <sys/stat.h>
#include <poll.h>
#include <inttypes.h>

extern char **environ;

static uint32_t pick_psn(void) { return (uint32_t)(now_ns() & 0xffffff); }

/* ---------------- link control (retry_link_down) ---------------- */
static const char *g_iface = NULL;              /* RoCE netdev (-I / $PROBE_IFACE) */
static int g_dryrun = 0;                        /* $PROBE_LINK_DRYRUN=1: log, never toggle */
static int g_no_probe_reply = 0;                /* $PROBE_TEST_NO_PROBE_REPLY=1: test only, ignore PROBE */
/* Set BEFORE the link is downed (so a signal in between still restores) and
 * cleared only after a successful restore. */
static volatile sig_atomic_t g_link_downed = 0;
static probe_ep_t *g_ep = NULL;                 /* for waiting on port ACTIVE after restore */
static char g_sig_restore_script[256];          /* prebuilt: the handler may not format */

/* interface names are interpolated into shell commands: allow only [A-Za-z0-9_.:-] */
static int iface_name_ok(const char *s) {
    if (!s || !s[0] || strlen(s) > 32) return 0;
    for (const char *p = s; *p; p++)
        if (!((*p >= 'a' && *p <= 'z') || (*p >= 'A' && *p <= 'Z') || (*p >= '0' && *p <= '9') ||
              *p == '_' || *p == '.' || *p == ':' || *p == '-')) return 0;
    return 1;
}

/* bring the local RoCE netdev up/down via passwordless sudo (never a password).
 * SIGTERM/SIGINT/SIGHUP are deferred while the command runs, so a signal-time
 * restore can never race a still-running `down`. Returns 0 on success. */
static int link_set(const char *state) {
    if (g_dryrun) { fprintf(stderr, "[server] DRYRUN link %s\n", state); return 0; }
    if (!g_iface || !g_iface[0]) { fprintf(stderr, "[server] link %s: no iface set\n", state); return -1; }
    char cmd[256];
    snprintf(cmd, sizeof(cmd), "sudo -n ip link set dev %s %s", g_iface, state);
    sigset_t blk, old;
    sigemptyset(&blk);
    sigaddset(&blk, SIGTERM); sigaddset(&blk, SIGINT); sigaddset(&blk, SIGHUP);
    sigprocmask(SIG_BLOCK, &blk, &old);
    int rc = system(cmd);
    sigprocmask(SIG_SETMASK, &old, NULL);   /* a deferred signal is delivered here */
    fprintf(stderr, "[server] link %s: '%s' rc=%d\n", state, cmd, rc);
    return rc == 0 ? 0 : -1;
}

/* wait until the RDMA port reaches the wanted state (link comes back up async) */
static int wait_port_state(probe_ep_t *ep, enum ibv_port_state want, int tries) {
    for (int i = 0; i < tries; i++) {
        struct ibv_port_attr pa;
        if (!ibv_query_port(ep->ctx, ep->ib_port, &pa) && pa.state == want) return 0;
        usleep(200000);
    }
    fprintf(stderr, "[server] WARNING: port did not reach state %d within %d ms\n", (int)want, tries * 200);
    return -1;
}

/* restore the link if (and only if) we downed it. Idempotent; used on every path. */
static void link_restore(const char *why) {
    if (!g_link_downed) return;
    fprintf(stderr, "[server] restoring link (%s)\n", why);
    if (link_set("up") == 0) {
        if (g_ep && g_ep->ctx) wait_port_state(g_ep, IBV_PORT_ACTIVE, 100);
        g_link_downed = 0;
    } else {
        fprintf(stderr, "[server] LINK RESTORE FAILED: run 'sudo ip link set dev %s up' on this host\n",
                g_iface ? g_iface : "?");
    }
}
static void link_restore_atexit(void) { link_restore("atexit"); }

/* Can we toggle the link? Checked before acking a retry_link_down TRIAL.
 * `sudo -n -l <cmd>` asks the policy whether <cmd> may run without a password,
 * without running it. */
static int link_down_precheck(char *why, size_t cap) {
    if (g_dryrun) return 0;
    if (!g_iface || !g_iface[0]) { snprintf(why, cap, "no_iface(-I)"); return -1; }
    char path[128];
    struct stat sb;
    snprintf(path, sizeof(path), "/sys/class/net/%s", g_iface);
    if (stat(path, &sb) != 0) { snprintf(why, cap, "iface_missing(%s)", g_iface); return -1; }
    char cmd[256];
    snprintf(cmd, sizeof(cmd),
             "sudo -n -l ip link set dev %s down >/dev/null 2>&1 && "
             "sudo -n -l ip link set dev %s up >/dev/null 2>&1", g_iface, g_iface);
    if (system(cmd) != 0) { snprintf(why, cap, "no_passwordless_sudo_for_ip"); return -1; }
    return 0;
}

/* ---- async-signal-safe termination: write(), sigaction(), execve(), _exit() only ---- */
static void put_str(const char *s) {
    size_t n = 0;
    while (s[n]) n++;
    while (n) {
        ssize_t w = write(STDERR_FILENO, s, n);
        if (w <= 0) return;
        s += w; n -= (size_t)w;
    }
}
static void on_term_signal(int sig) {
    char num[4] = { (char)('0' + (sig / 10) % 10), (char)('0' + sig % 10), '\n', '\0' };
    put_str("[server] caught signal ");
    put_str(sig >= 10 ? num : num + 1);
    if (!g_link_downed) _exit(128 + sig);
    if (g_dryrun) {
        put_str("[server] restoring link (signal)\n[server] DRYRUN link up\n");
        g_link_downed = 0;
        _exit(128 + sig);
    }
    /* Ignore further termination signals (this also discards a pending duplicate,
     * e.g. timeout's group-wide SIGTERM; SIG_IGN survives execve), then replace
     * this process with a shell that restores the link and exits 128+sig. */
    struct sigaction ign;
    memset(&ign, 0, sizeof(ign));
    ign.sa_handler = SIG_IGN;
    sigaction(SIGTERM, &ign, NULL);
    sigaction(SIGINT, &ign, NULL);
    sigaction(SIGHUP, &ign, NULL);
    char code[4] = { (char)('0' + (128 + sig) / 100), (char)('0' + ((128 + sig) / 10) % 10),
                     (char)('0' + (128 + sig) % 10), '\0' };
    char *const av[] = { "sh", "-c", g_sig_restore_script, "sh", code, NULL };
    put_str("[server] restoring link (signal)\n");
    execve("/bin/sh", av, environ);
    put_str("[server] LINK RESTORE FAILED (execve)\n");
    _exit(128 + sig);
}

/* ---------------- QP wiring ---------------- */
static probe_dest_t g_peer;          /* the requester's QP info of the current connection (live_*) */
static lp_stall_t g_stall = { -1, -1 };

static long env_ms(const char *name, long def) {
    const char *v = getenv(name);
    return (v && v[0]) ? atol(v) : def;
}

/* exchange dest (server sends first, then receives) and go RTR->RTS */
static int connect_qp_server(probe_ep_t *ep, int fd, uint32_t local_psn) {
    probe_dest_t local, remote;
    ep_fill_dest(ep, local_psn, &local);
    if (tcp_send_all(fd, &local, sizeof(local)) < 0) return -1;
    if (tcp_recv_all(fd, &remote, sizeof(remote)) < 0) return -1;
    g_peer = remote;
    if (ep_to_rtr(ep, &remote) < 0) return -1;
    if (ep_to_rts(ep, local_psn) < 0) return -1;
    return 0;
}

/* bring the server QP up again: full rebuild = destroy+recreate the QP only
 * (CQ/MR/PD kept); qp-only = ERR->RESET->INIT->RTR->RTS on the same QP */
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

/* live_ctl_close: after the control connection is closed, answer "ALIVE?" on a new connection
 * (up to 20 s), so the requester can tell a live process from a dead one. */
static void serve_alive_query(int lfd, probe_ep_t *ep) {
    struct pollfd p = { .fd = lfd, .events = POLLIN, .revents = 0 };
    if (poll(&p, 1, 20000) <= 0) { fprintf(stderr, "[server] no ALIVE? connection within 20 s\n"); return; }
    int afd = tcp_server_accept(lfd);
    if (afd < 0) return;
    struct timeval tv = { 5, 0 };
    setsockopt(afd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    char line[128];
    if (ctrl_recv_line(afd, line, sizeof(line)) > 0 && strcmp(line, "ALIVE?") == 0) {
        enum ibv_qp_state qs;
        const char *qsn = (ep_query_qp_state(ep, &qs) == 0) ? qp_state_name(qs) : "?";
        char rep[96];
        snprintf(rep, sizeof(rep), "ALIVE %d %s", (int)getpid(), qsn);
        ctrl_send_line(afd, rep);
        fprintf(stderr, "[server] answered '%s' mono_ns=%" PRIu64 "\n", rep, mono_ns());
    } else {
        fprintf(stderr, "[server] unexpected line on the ALIVE? connection: '%s'\n", line);
    }
    close(afd);
}

int main(int argc, char **argv) {
    const char *dev = "mlx5_0";
    int ib_port = 1, gid_index = 3, ctrl_port = PROBE_DEFAULT_PORT, cpu = -1;
    g_iface = getenv("PROBE_IFACE");
    const char *dr = getenv("PROBE_LINK_DRYRUN");
    g_dryrun = (dr && dr[0] && strcmp(dr, "0") != 0);
    const char *npr = getenv("PROBE_TEST_NO_PROBE_REPLY");
    g_no_probe_reply = (npr && npr[0] && strcmp(npr, "0") != 0);
    if (g_no_probe_reply) fprintf(stderr, "[server] PROBE_TEST_NO_PROBE_REPLY=1: PROBE is ignored (test of the client's no_answer path)\n");
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
                fprintf(stderr, "usage: %s -d dev -i port -g gid -p ctrlport [-C cpu] [-I roce_netdev]\n"
                                "env: PROBE_LINK_DRYRUN=1 logs link toggles instead of doing them\n", argv[0]);
                return (opt == 'h') ? 0 : 2;
        }
    }
    if (g_iface && g_iface[0] && !iface_name_ok(g_iface)) {
        fprintf(stderr, "[server] ERROR: invalid interface name '%s'\n", g_iface);
        return 2;
    }
    snprintf(g_sig_restore_script, sizeof(g_sig_restore_script),
             "sudo -n ip link set dev %s up; r=$?; "
             "echo \"[server] link up (signal restore): rc=$r\" >&2; exit \"$1\"",
             (g_iface && g_iface[0]) ? g_iface : "none");

    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_handler = on_term_signal;
    sigemptyset(&sa.sa_mask);
    sigaddset(&sa.sa_mask, SIGTERM); sigaddset(&sa.sa_mask, SIGINT); sigaddset(&sa.sa_mask, SIGHUP);
    sigaction(SIGTERM, &sa, NULL);
    sigaction(SIGINT, &sa, NULL);
    sigaction(SIGHUP, &sa, NULL);
    signal(SIGPIPE, SIG_IGN);           /* a vanished client must not skip the restore */
    atexit(link_restore_atexit);
    if (g_dryrun) fprintf(stderr, "[server] PROBE_LINK_DRYRUN=1: link toggles are logged, not performed\n");

    pin_to_cpu(cpu);

    /* live_peer: the stop helper is forked before the device and the sockets are opened */
    if (lp_stall_start(&g_stall) != 0) { perror("lp_stall_start"); return 1; }
    const long live_stop_ms = env_ms("LIVE_STOP_MS", 8000);
    const long live_transient_ms = env_ms("LIVE_TRANSIENT_MS", 1250);
    fprintf(stderr, "[server] pid %d, lp_stall helper pid %d, LIVE_STOP_MS=%ld LIVE_TRANSIENT_MS=%ld\n",
            (int)getpid(), (int)g_stall.pid, live_stop_ms, live_transient_ms);

    probe_ep_t ep;
    if (ep_open(&ep, dev, (uint8_t)ib_port, gid_index, PROBE_BUF_SIZE) < 0) return 1;
    if (async_mon_start(ep.ctx, "server") < 0) { ep_close(&ep); return 1; }
    if (ep_create_qp(&ep) < 0) { ep_close(&ep); return 1; }
    if (ep_to_init(&ep) < 0) { ep_close(&ep); return 1; }
    g_ep = &ep;

    int rc = 1;
    int fd = -1;
    int lfd = tcp_server_listen(ctrl_port);
    if (lfd < 0) goto done;
    fprintf(stderr, "[server] %s port %d gid %d, listening on tcp %d\n",
            dev, ib_port, gid_index, ctrl_port);

    fd = tcp_server_accept(lfd);
    if (fd < 0) goto done;
    fprintf(stderr, "[server] client connected\n");

    /* handshake */
    char line[512];
    if (ctrl_recv_line(fd, line, sizeof(line)) < 0 || strcmp(line, "HELLO") != 0) {
        fprintf(stderr, "[server] bad hello\n"); goto done;
    }
    if (connect_qp_server(&ep, fd, pick_psn()) < 0) goto done;
    if (ctrl_send_line(fd, "SYNC") < 0) goto done;

    /* trial loop */
    for (;;) {
        int n = ctrl_recv_line(fd, line, sizeof(line));
        if (n < 0) { fprintf(stderr, "[server] client closed\n"); rc = 0; break; }
        if (strcmp(line, "BYE") == 0) { fprintf(stderr, "[server] bye\n"); rc = 0; break; }

        char fault_s[64] = {0}, recov_s[64] = {0};
        if (sscanf(line, "TRIAL %63s %63s", fault_s, recov_s) != 2) {
            fprintf(stderr, "[server] bad trial line: '%s'\n", line); break;
        }
        fault_type_t fault;
        if (fault_from_name(fault_s, &fault) < 0) {
            fprintf(stderr, "[server] unknown fault '%s'\n", fault_s);
            if (ctrl_send_line(fd, "ERR unknown_fault") < 0) break;
            continue;                   /* client decides; it will send BYE */
        }
        if (fault == FAULT_RETRY_LINK_DOWN) {
            char why[96] = "";
            if (link_down_precheck(why, sizeof(why)) < 0) {
                char rep[160];
                snprintf(rep, sizeof(rep), "ERR link_down_unavailable %s", why);
                fprintf(stderr, "[server] retry_link_down refused: %s\n", why);
                if (ctrl_send_line(fd, rep) < 0) break;
                continue;
            }
        }
        if (fault == FAULT_PARTIAL_WRITE)
            memset(ep.buf, 0, ep.buf_size);   /* so landed bytes are measurable */
        if (ctrl_send_line(fd, "OK") < 0) break;

        /* barrier: wait for GO */
        if (ctrl_recv_line(fd, line, sizeof(line)) < 0) { fprintf(stderr, "[server] client closed before GO\n"); break; }
        if (strcmp(line, "GO") != 0) {
            fprintf(stderr, "[server] expected GO, got '%s'\n", line);
            if (strcmp(line, "BYE") == 0) rc = 0;
            break;
        }
        const uint64_t t_go_mono = mono_ns();    /* async events from here on belong to this trial */

        /* proc_kill: die on GO, BEFORE acking anything, so no in-flight write can
         * be ACKed in a race window; the requester then hits RETRY_EXC cleanly. */
        if (fault == FAULT_RETRY_PROC_SIGKILL) {
            /* a real crash: no ep_close, no close(); the kernel tears everything down */
            fprintf(stderr, "[server] proc_sigkill: raising SIGKILL on command\n");
            raise(SIGKILL);
        }
        if (fault == FAULT_RETRY_PROC_KILL) {
            fprintf(stderr, "[server] proc_kill: exiting on command\n");
            g_ep = NULL;
            ep_close(&ep); close(fd); close(lfd);
            return 0;
        }
        if (fault == FAULT_RETRY_LINK_DOWN) {
            /* control channel rides the mgmt IP, so it survives the RoCE link going down */
            g_link_downed = 1;          /* before the toggle: any exit from here restores */
            if (link_set("down") < 0) {
                link_restore("down failed");
                if (ctrl_send_line(fd, "ERR link_down_failed") < 0) break;
                continue;
            }
        }
        /* live_peer faults and the peer QP error: change our QP before GOACK */
        uint32_t saved_sq = 0, saved_rq = 0;
        bool applied = true;
        switch (fault) {
            case FAULT_RETRY_SERVER_QP_ERR:
            case FAULT_LIVE_STOP_ERR:
            case FAULT_LIVE_CTL_CLOSE:
                applied = ep_to_err(&ep) == 0; break;
            case FAULT_LIVE_QP_RESET:
                applied = ep_to_reset(&ep) == 0; break;
            case FAULT_LIVE_QP_INIT:
                applied = ep_to_reset(&ep) == 0 && ep_to_init(&ep) == 0; break;
            case FAULT_LIVE_QP_RECREATE:
                ep_destroy_qp(&ep);
                applied = ep_create_qp(&ep) == 0 && ep_to_init(&ep) == 0; break;
            case FAULT_LIVE_QP_RTR:
                applied = ep_query_psns(&ep, &saved_sq, &saved_rq) == 0 &&
                          ep_rearm(&ep, &g_peer, saved_rq, saved_sq, false) == 0; break;
            case FAULT_LIVE_TRANSIENT:
                applied = ep_query_psns(&ep, &saved_sq, &saved_rq) == 0 &&
                          ep_to_reset(&ep) == 0 && ep_to_init(&ep) == 0; break;
            default: break;
        }
        if (!applied) { fprintf(stderr, "[server] could not apply %s\n", fault_s); break; }
        const bool live_fault = fault == FAULT_RETRY_SERVER_QP_ERR || fault >= FAULT_LIVE_QP_RESET;
        if (ctrl_send_line(fd, "GOACK") < 0) break;
        const uint64_t t_goack = mono_ns();
        if (live_fault)
            fprintf(stderr, "[server] fault_applied fault=%s mono_ns=%" PRIu64 " rq_psn=%u sq_psn=%u\n",
                    fault_s, t_goack, saved_rq, saved_sq);
        if (fault == FAULT_LIVE_TRANSIENT) {
            const uint64_t until = t_goack + (uint64_t)live_transient_ms * 1000000ull;
            for (uint64_t now = mono_ns(); now < until; now = mono_ns()) {
                uint64_t left = until - now;
                struct timespec d = { (time_t)(left / 1000000000ull), (long)(left % 1000000000ull) };
                nanosleep(&d, NULL);
            }
            if (ep_rearm(&ep, &g_peer, saved_rq, saved_sq, true) < 0) { fprintf(stderr, "[server] rearm failed\n"); break; }
            fprintf(stderr, "[server] rearm mono_ns=%" PRIu64 " rq_psn=%u sq_psn=%u\n", mono_ns(), saved_rq, saved_sq);
        }
        if (fault == FAULT_LIVE_STOP_ERR || fault == FAULT_LIVE_STOP_OK) {
            uint64_t t_stop = 0, t_cont = 0;
            if (lp_stall_self(&g_stall, (uint32_t)live_stop_ms, &t_stop, &t_cont) < 0) {
                fprintf(stderr, "[server] stall helper gone\n"); break;
            }
            fprintf(stderr, "[server] stall_begin mono_ns=%" PRIu64 " ms=%ld\n", t_stop, live_stop_ms);
            fprintf(stderr, "[server] stall_end mono_ns=%" PRIu64 " measured_ms=%.3f\n", t_cont,
                    (double)(t_cont - t_stop) / 1e6);
        }
        if (fault == FAULT_LIVE_CTL_CLOSE) {
            fprintf(stderr, "[server] ctl_close pid=%d mono_ns=%" PRIu64 "\n", (int)getpid(), mono_ns());
            shutdown(fd, SHUT_RDWR);
            close(fd);
            fd = -1;
            serve_alive_query(lfd, &ep);
            rc = 0;
            break;   /* the process exits normally after answering */
        }

        /* Baseline the responder RDMA port counters at fault time. They are reported
         * in the PROBE reply as DIAGNOSTICS ONLY: VERIFICATION_0x81.md showed that
         * port_rcv_packets advances by ~40-52 for both server_qp_err and proc_kill
         * and port_xmit_packets stays 0 for both, so they do NOT disambiguate
         * RETRY_EXC. The discriminator is liveness: does this PROBE get a reply. */
        uint64_t rx0 = port_counter_read(ep.dev_name, ep.ib_port, "port_rcv_packets");
        uint64_t tx0 = port_counter_read(ep.dev_name, ep.ib_port, "port_xmit_packets");

        /* recovery coordination (client drives), answering PROBE liveness queries */
        bool trial_done = false, stop = false;
        while (!trial_done) {
            n = ctrl_recv_line(fd, line, sizeof(line));
            if (n < 0) { fprintf(stderr, "[server] client closed mid-trial\n"); stop = true; break; }
            if (strcmp(line, "PROBE") == 0) {
                if (g_no_probe_reply) continue;   /* test only: a live peer that does not answer */
                uint64_t rx = port_counter_read(ep.dev_name, ep.ib_port, "port_rcv_packets");
                uint64_t tx = port_counter_read(ep.dev_name, ep.ib_port, "port_xmit_packets");
                long rxd = (rx0 != UINT64_MAX && rx != UINT64_MAX) ? (long)(rx - rx0) : -1;
                long txd = (tx0 != UINT64_MAX && tx != UINT64_MAX) ? (long)(tx - tx0) : -1;
                int port_up = (ep_port_state(&ep) == IBV_PORT_ACTIVE);
                char rep[96];
                /* fault-window deltas (pre-recovery) + our RDMA port state */
                snprintf(rep, sizeof(rep), "PROBED %ld %ld %d", rxd, txd, port_up);
                if (ctrl_send_line(fd, rep) < 0) { stop = true; break; }
                continue;   /* peer is alive; keep waiting for RECOVER/NORECOVER */
            }
            unsigned rs = 0;
            if (sscanf(line, "RESYNC %u", &rs) == 1) {
                char rep[48];
                snprintf(rep, sizeof(rep), "RESYNCED %u", rs);
                fprintf(stderr, "[server] %s mono_ns=%" PRIu64 "\n", rep, mono_ns());
                if (ctrl_send_line(fd, rep) < 0) { stop = true; break; }
                continue;
            }
            if (strcmp(line, "QUERY") == 0) {
                /* fault-time state, before any recovery: our QP state and our async events */
                enum ibv_qp_state qs;
                const char *qsn = (ep_query_qp_state(&ep, &qs) == 0) ? qp_state_name(qs) : "?";
                char evs[PROBE_ASYNC_FMT_MAX], rep[PROBE_ASYNC_FMT_MAX + 32];
                async_mon_format(t_go_mono, evs, sizeof(evs));
                snprintf(rep, sizeof(rep), "QUERIED %s %s", qsn, evs);
                fprintf(stderr, "[server] %s\n", rep);
                if (ctrl_send_line(fd, rep) < 0) { stop = true; break; }
                continue;
            }
            char method_s[64] = {0};
            if (sscanf(line, "RECOVER %63s", method_s) == 1) {
                recovery_method_t method;
                if (recovery_from_name(method_s, &method) < 0 || method == RECOVER_NONE) {
                    fprintf(stderr, "[server] bad recovery method '%s'\n", method_s); stop = true; break;
                }
                link_restore("recover");       /* before rewiring */
                if (server_bring_up(&ep, fd, method == RECOVER_FULL_REBUILD) < 0) {
                    fprintf(stderr, "[server] rebuild failed\n"); stop = true; break;
                }
                if (ctrl_send_line(fd, "RECOK") < 0) { stop = true; break; }
                trial_done = true;
            } else if (strcmp(line, "NORECOVER") == 0) {
                link_restore("norecover");
                if (server_bring_up(&ep, fd, false) < 0) { stop = true; break; }
                if (ctrl_send_line(fd, "RECOK") < 0) { stop = true; break; }
                trial_done = true;
            } else if (strcmp(line, "BYE") == 0) {
                fprintf(stderr, "[server] bye mid-trial\n"); stop = true; break;
            } else {
                fprintf(stderr, "[server] unexpected: '%s'\n", line); stop = true; break;
            }
        }
        if (stop) break;
    }

done:
    link_restore("exit");
    if (fd >= 0) close(fd);
    if (lfd >= 0) close(lfd);
    g_ep = NULL;
    uint64_t t_td = now_ns();
    ep_close(&ep);
    fprintf(stderr, "[server] teardown (ep_close) returned after %.3f ms\n", (double)(now_ns() - t_td) / 1e6);
    return rc;
}
