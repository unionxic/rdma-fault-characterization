/*
 * probe_client.c - requester side of the unified RDMA fault harness.
 *
 * Runs on the requester node (e.g. rain, mlx5_1). Drives N trials of one fault
 * type, measuring per trial into a single CSV schema:
 *   detection latency, (status,vendor_err) classification, recovery latency,
 *   post-recovery verification, partial-write byte accounting, counter deltas.
 *
 * One trial:
 *   TRIAL -> OK | "ERR <why>" -> [read counters] -> GO -> GOACK -> inject+measure detect
 *         -> [PROBE -> PROBED: liveness for RETRY_EXC, REM_ACCESS, REM_INV_REQ]
 *         -> [QUERY -> QUERIED <responder QP state> <responder async events since GO>;
 *             skipped when the responder is dead] + our own async events since GO
 *         -> RECOVER/NORECOVER -> RECOK -> [recovery latency]
 *         -> [partial_write: RDMA-READ readback of the landed bytes] -> verify -> row
 *
 * Fault "none" (F0) is a control: the normal 4 KiB write, polled to its completion,
 * then the same QUERY, recovery and verify steps as any other trial.
 * A thread records the async events of our device context (common/probe.c).
 * At exit the client prints how long its own teardown (ep_close) took.
 *
 * Exit status: 0 = all requested trials completed (and verified);
 *              1 = a protocol/RDMA step failed or fewer trials completed
 *                  (rows already written are kept);
 *              2 = bad arguments;
 *              3 = the server refused the fault (e.g. "ERR link_down_unavailable").
 */
#define _GNU_SOURCE
#include "probe.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <getopt.h>
#include <inttypes.h>
#include <signal.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <errno.h>

#define WR_TRIGGER  100
#define WR_VERIFY   200
#define WR_READBACK 300

/* Wait after detection before QUERY and before reading our own async events, so an
 * async event raised together with the fault has reached its monitor thread. */
#define QUERY_SETTLE_MS 10

/* remote target info kept for the trial loop */
static probe_dest_t g_remote;

static uint32_t pick_psn(void) { return (uint32_t)((now_ns() >> 3) & 0xffffff); }

/* client exchange: receive server dest first, then send ours; go RTR->RTS */
static int connect_qp_client(probe_ep_t *ep, int fd, uint32_t local_psn) {
    probe_dest_t local;
    if (tcp_recv_all(fd, &g_remote, sizeof(g_remote)) < 0) return -1;
    ep_fill_dest(ep, local_psn, &local);
    if (tcp_send_all(fd, &local, sizeof(local)) < 0) return -1;
    if (ep_to_rtr(ep, &g_remote) < 0) return -1;
    if (ep_to_rts(ep, local_psn) < 0) return -1;
    return 0;
}

/* full rebuild = destroy+recreate the QP only (CQ/MR/PD kept); qp-only = RESET */
static int client_bring_up(probe_ep_t *ep, int fd, bool full_rebuild) {
    if (full_rebuild) {
        ep_destroy_qp(ep);
        if (ep_create_qp(ep) < 0) return -1;
    } else {
        if (ep_to_reset(ep) < 0) return -1;
    }
    if (ep_to_init(ep) < 0) return -1;
    return connect_qp_client(ep, fd, pick_psn());
}

/* poll completions, skipping SUCCESS, until the first error CQE or timeout.
 * returns 1 with wc set on error, 0 on timeout (only successes seen), -1 on poll error. */
static int poll_until_error(probe_ep_t *ep, struct ibv_wc *wc, long timeout_ms) {
    uint64_t deadline = now_ns() + (uint64_t)timeout_ms * 1000000ull;
    for (;;) {
        int n = ibv_poll_cq(ep->cq, 1, wc);
        if (n < 0) return -1;
        if (n == 1) {
            if (wc->status == IBV_WC_SUCCESS) continue;
            return 1;
        }
        if (now_ns() >= deadline) return 0;
    }
}

/* the per-trial data pattern: byte i = seed + (i & 0xff) */
static inline uint8_t pattern_byte(uint8_t seed, size_t i) { return (uint8_t)(seed + (i & 0xff)); }
static void fill_pattern(probe_ep_t *ep, uint8_t seed) {
    for (size_t i = 0; i < ep->buf_size; i++)
        ep->buf[i] = (char)pattern_byte(seed, i);
}

/* Measure what actually landed at the responder: RDMA-READ the remote region
 * [0,len) (zeroed by the server at TRIAL time) into a zeroed local buffer and
 * compare with this trial's pattern.
 *   *prefix = length of the matching prefix (bytes landed in order)
 *   *total  = matching bytes anywhere in the region (> prefix => non-prefix landing)
 * A pattern byte that is 0x00 cannot be told apart from the zero fill; it is
 * judged by a neighbour in the same 256-byte-aligned block, which always lies in
 * the same packet (PMTU >= 256, and the write starts at remote offset 0), so both
 * counts are exact at packet granularity. Returns 0 on success, -1 on failure. */
static int readback_landed(probe_ep_t *ep, size_t len, uint8_t seed, long *prefix, long *total) {
    struct ibv_wc wc;
    memset(ep->buf, 0, len);
    if (post_read(ep, WR_READBACK, len, g_remote.addr, g_remote.rkey) < 0) return -1;
    int got = poll_one(ep, &wc, 5000);
    if (got != 1 || wc.wr_id != WR_READBACK || wc.status != IBV_WC_SUCCESS) {
        fprintf(stderr, "[client] readback READ failed: got=%d wr_id=%" PRIu64 " status=%s\n",
                got, got == 1 ? (uint64_t)wc.wr_id : 0, got == 1 ? ibv_wc_status_str(wc.status) : "-");
        return -1;
    }
    const uint8_t *b = (const uint8_t *)ep->buf;
    long pre = 0, tot = 0;
    bool in_prefix = true;
    for (size_t i = 0; i < len; i++) {
        size_t j = i;
        if (pattern_byte(seed, i) == 0) {
            j = (i & 0xff) ? i - 1 : i + 1;
            if (j >= len) j = i;
        }
        bool ok = (b[j] == pattern_byte(seed, j));
        if (ok) tot++;
        if (in_prefix) { if (ok) pre++; else in_prefix = false; }
    }
    *prefix = pre;
    *total = tot;
    return 0;
}

/* Ask the live responder for its QP state and its async events since GO:
 *   QUERY -> "QUERIED <state> <events>"
 * Lines that are not the answer (a late PROBED) are skipped. Without an answer
 * within 2 s both fields stay "?". */
static void query_server(int fd, char *qp, size_t qcap, char *ev, size_t ecap) {
    snprintf(qp, qcap, "?");
    snprintf(ev, ecap, "?");
    struct timeval tv = { 2, 0 };
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    char line[512];
    if (ctrl_send_line(fd, "QUERY") == 0) {
        for (int k = 0; k < 4; k++) {
            if (ctrl_recv_line(fd, line, sizeof(line)) < 0) break;
            if (strncmp(line, "QUERIED ", 8) != 0) {
                fprintf(stderr, "[client] skipping '%s' while waiting for QUERIED\n", line);
                continue;
            }
            char *st = line + 8, *sp = strchr(st, ' ');
            if (!sp) break;
            *sp = '\0';
            snprintf(qp, qcap, "%.15s", st);
            snprintf(ev, ecap, "%s", sp + 1);
            break;
        }
    }
    tv.tv_sec = 0;
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    if (strcmp(qp, "?") == 0) fprintf(stderr, "[client] WARNING: no QUERIED answer from the server\n");
}

/* our own teardown: async monitor stop + QP/CQ/MR/PD destroy + device close */
static void client_teardown(probe_ep_t *ep) {
    uint64_t t0 = now_ns();
    ep_close(ep);
    fprintf(stderr, "[client] teardown (ep_close) returned after %.3f ms\n", (double)(now_ns() - t0) / 1e6);
}

static void usage(const char *prog) {
    fprintf(stderr,
      "usage: %s -s server -d dev -i port -g gid -p ctrlport\n"
      "         -f fault -r recovery -n iters -o out.csv [-C cpu] [-S msgsize] [-k counter] [-t detect_ms]\n"
      "faults: none local_qp_err rem_access rem_inv_req rnr retry_server_qp_err retry_proc_kill\n"
      "        retry_proc_sigkill retry_link_down partial_write\n"
      "recovery: qp_only full_rebuild none\n"
      "exit: 0 ok, 1 failure/incomplete, 2 bad args, 3 fault refused by server\n", prog);
}

int main(int argc, char **argv) {
    const char *server = NULL, *dev = "mlx5_1", *out = NULL;
    const char *fault_s = "local_qp_err", *recov_s = "qp_only";
    const char *counter = "roce_adp_retrans";
    int ib_port = 1, gid_index = 3, ctrl_port = PROBE_DEFAULT_PORT;
    int iters = 30, cpu = -1;
    size_t msg_size = 1u << 20; /* 1 MiB default trigger size */
    long detect_timeout_ms = 10000; /* cap detection wait (RETRY_EXC can be seconds) */
    int opt;
    while ((opt = getopt(argc, argv, "s:d:i:g:p:f:r:n:o:C:S:k:t:h")) != -1) {
        switch (opt) {
            case 's': server = optarg; break;
            case 'd': dev = optarg; break;
            case 'i': ib_port = atoi(optarg); break;
            case 'g': gid_index = atoi(optarg); break;
            case 'p': ctrl_port = atoi(optarg); break;
            case 'f': fault_s = optarg; break;
            case 'r': recov_s = optarg; break;
            case 'n': iters = atoi(optarg); break;
            case 'o': out = optarg; break;
            case 'C': cpu = atoi(optarg); break;
            case 'S': msg_size = (size_t)strtoull(optarg, NULL, 0); break;
            case 'k': counter = optarg; break;
            case 't': detect_timeout_ms = atol(optarg); break;
            case 'h': usage(argv[0]); return 0;
            default:  usage(argv[0]); return 2;
        }
    }
    if (!server) { fprintf(stderr, "ERROR: -s server required\n"); return 2; }
    fault_type_t fault;
    recovery_method_t recovery;
    if (fault_from_name(fault_s, &fault) < 0) {
        fprintf(stderr, "ERROR: unknown fault '%s'\n", fault_s); usage(argv[0]); return 2;
    }
    if (recovery_from_name(recov_s, &recovery) < 0) {
        fprintf(stderr, "ERROR: unknown recovery '%s'\n", recov_s); usage(argv[0]); return 2;
    }
    if (iters <= 0) { fprintf(stderr, "ERROR: -n must be > 0\n"); return 2; }
    /* both end the server on GO: retry_proc_kill by exiting, retry_proc_sigkill by SIGKILL */
    const bool proc_kill = (fault == FAULT_RETRY_PROC_KILL || fault == FAULT_RETRY_PROC_SIGKILL);
    if (proc_kill && iters != 1) {
        fprintf(stderr, "ERROR: %s ends the server each trial: use -n 1 "
                        "(run.sh restarts the server per trial)\n", fault_name(fault));
        return 2;
    }
    if (msg_size == 0) { fprintf(stderr, "ERROR: -S must be > 0\n"); return 2; }
    if (msg_size > PROBE_BUF_SIZE) msg_size = PROBE_BUF_SIZE;
    if (detect_timeout_ms <= 0) { fprintf(stderr, "ERROR: -t must be > 0\n"); return 2; }
    pin_to_cpu(cpu);
    signal(SIGPIPE, SIG_IGN);   /* a dead peer must not kill us mid-PROBE */

    probe_ep_t ep;
    if (ep_open(&ep, dev, (uint8_t)ib_port, gid_index, PROBE_BUF_SIZE) < 0) return 1;
    if (async_mon_start(ep.ctx, "client") < 0) { ep_close(&ep); return 1; }
    if (ep_create_qp(&ep) < 0) { ep_close(&ep); return 1; }
    if (ep_to_init(&ep) < 0) { ep_close(&ep); return 1; }

    int fd = tcp_client_connect(server, ctrl_port);
    if (fd < 0) { ep_close(&ep); return 1; }

    char line[512] = "";
    FILE *fo = NULL;
    if (ctrl_send_line(fd, "HELLO") < 0) goto fail;
    if (connect_qp_client(&ep, fd, pick_psn()) < 0) goto fail;
    if (ctrl_recv_line(fd, line, sizeof(line)) < 0 || strcmp(line, "SYNC") != 0) {
        fprintf(stderr, "[client] handshake failed: '%s'\n", line); goto fail;
    }
    fprintf(stderr, "[client] connected to %s, dev %s gid %d, mtu %d B, fault %s, recovery %s, n %d\n",
            server, dev, gid_index, ep.mtu_bytes, fault_name(fault), recovery_name(recovery), iters);

    fo = out ? fopen(out, "w") : stdout;
    if (!fo) { perror("fopen"); goto fail; }
    fprintf(fo, "fault,iter,recovery,detect_ns,status,status_name,vendor_err,cause,action,"
                "peer_alive,auto_recoverable,recover_ns,verify_ok,"
                "bytes_sent_psn,sq_psn_delta,bytes_landed_readback,matching_bytes_total,mtu_bytes,"
                "counter,cnt_delta,sub_cause,peer_rx_delta,"
                "srv_qp_state,srv_async,cli_async\n");
    fflush(fo);

    int completed = 0;
    bool failed = false, refused = false;

/* abort the run: the current trial is NOT recorded, the client exits non-zero */
#define TRIAL_FAIL(...) do {                                         \
        fprintf(stderr, "[client] trial %d FAILED: ", it);           \
        fprintf(stderr, __VA_ARGS__);                                \
        fputc('\n', stderr);                                         \
        failed = true;                                               \
        goto endloop;                                                \
    } while (0)

    for (int it = 0; it < iters; it++) {
        /* announce trial */
        snprintf(line, sizeof(line), "TRIAL %s %s", fault_name(fault), recovery_name(recovery));
        if (ctrl_send_line(fd, line) < 0) TRIAL_FAIL("send TRIAL");
        if (ctrl_recv_line(fd, line, sizeof(line)) < 0) TRIAL_FAIL("no reply to TRIAL (server gone?)");
        if (strncmp(line, "ERR", 3) == 0) {
            fprintf(stderr, "[client] ABORT: server refused fault %s: '%s'\n", fault_name(fault), line);
            if (fault == FAULT_RETRY_LINK_DOWN)
                fprintf(stderr, "[client] retry_link_down needs passwordless sudo for `ip` on the responder "
                                "(and a valid -I/SERVER_IFACE), or PROBE_LINK_DRYRUN=1 on the server to "
                                "exercise the protocol without touching the link\n");
            refused = true;
            goto endloop;
        }
        if (strcmp(line, "OK") != 0) TRIAL_FAIL("expected OK, got '%s'", line);

        /* g_remote is populated by the handshake (connect_qp_client) and refreshed
           by each recovery (client_bring_up), so it is always current here. */
        uint64_t cnt_before = counter_read(dev, (uint8_t)ib_port, counter);
        uint32_t sq_before = 0;
        if (fault == FAULT_PARTIAL_WRITE && ep_query_sq_psn(&ep, &sq_before) < 0)
            TRIAL_FAIL("query sq_psn (before)");

        const uint8_t seed = (uint8_t)(0x40 + it);
        fill_pattern(&ep, seed);

        /* barrier; async events from here on belong to this trial */
        const uint64_t t_go_mono = mono_ns();
        if (ctrl_send_line(fd, "GO") < 0) TRIAL_FAIL("send GO");
        if (proc_kill) {
            /* server exits on GO (no GOACK); let its QP be fully torn down so the
             * subsequent write has no responder and hits RETRY_EXC deterministically */
            usleep(300000);
        } else {
            if (ctrl_recv_line(fd, line, sizeof(line)) < 0) TRIAL_FAIL("no GOACK (server gone?)");
            if (strcmp(line, "GOACK") != 0) TRIAL_FAIL("expected GOACK, got '%s'", line);
        }

        uint64_t t_inject = 0, t_detect = 0;
        struct ibv_wc wc; memset(&wc, 0, sizeof(wc));
        int got = 0;
        /* partial-write accounting (-1 = not applicable) */
        long bytes_sent_psn = -1, sq_delta = -1, landed_rb = -1, match_total = -1;

        switch (fault) {
            case FAULT_NONE: {
                /* F0 control: the normal write, polled to its own completion (success
                 * expected; an error CQE is recorded like any other) */
                if (post_write(&ep, WR_TRIGGER, 4096, g_remote.addr, g_remote.rkey, true) < 0)
                    TRIAL_FAIL("post_write");
                t_inject = now_ns();
                got = poll_one(&ep, &wc, detect_timeout_ms);
                t_detect = now_ns();
                break;
            }
            case FAULT_LOCAL_QP_ERR: {
                /* keep the send queue deep so WRs are still outstanding when we
                 * force ERR, then measure inject -> first WR_FLUSH_ERR CQE */
                for (int b = 0; b < 32; b++)
                    if (post_write(&ep, WR_TRIGGER + b, msg_size, g_remote.addr, g_remote.rkey, true) < 0)
                        TRIAL_FAIL("post_write #%d", b);
                t_inject = now_ns();
                if (ep_to_err(&ep) < 0) TRIAL_FAIL("modify QP->ERR");
                got = poll_until_error(&ep, &wc, detect_timeout_ms);
                t_detect = now_ns();
                break;
            }
            case FAULT_REM_ACCESS: {
                /* valid rkey but write past the end of the remote MR */
                if (post_write(&ep, WR_TRIGGER, 4096, g_remote.addr + g_remote.buf_size, g_remote.rkey, true) < 0)
                    TRIAL_FAIL("post_write");
                t_inject = now_ns();
                got = poll_until_error(&ep, &wc, detect_timeout_ms);
                t_detect = now_ns();
                break;
            }
            case FAULT_REM_INV_REQ: {
                /* atomic to a responder QP that does not enable atomics ->
                 * operation-not-enabled at QP level -> REM_INV_REQ_ERR (9 / 0x8a) */
                if (post_atomic_fa(&ep, WR_TRIGGER, g_remote.addr, g_remote.rkey) < 0)
                    TRIAL_FAIL("post_atomic_fa");
                t_inject = now_ns();
                got = poll_until_error(&ep, &wc, detect_timeout_ms);
                t_detect = now_ns();
                break;
            }
            case FAULT_RNR: {
                /* SEND with no remote recv WQE -> RNR retries exhausted */
                if (post_send(&ep, WR_TRIGGER, 64) < 0) TRIAL_FAIL("post_send");
                t_inject = now_ns();
                got = poll_until_error(&ep, &wc, detect_timeout_ms);
                t_detect = now_ns();
                break;
            }
            case FAULT_RETRY_SERVER_QP_ERR:
            case FAULT_RETRY_PROC_KILL:
            case FAULT_RETRY_PROC_SIGKILL:
            case FAULT_RETRY_LINK_DOWN: {
                /* responder stopped ACKing (QP ERR / process gone / link down)
                 * -> transport retries exhausted */
                if (post_write(&ep, WR_TRIGGER, 4096, g_remote.addr, g_remote.rkey, true) < 0)
                    TRIAL_FAIL("post_write");
                t_inject = now_ns();
                got = poll_until_error(&ep, &wc, detect_timeout_ms);
                t_detect = now_ns();
                break;
            }
            case FAULT_PARTIAL_WRITE: {
                /* large multi-packet write, force ERR mid-transfer. The sq_psn advance
                 * gives the bytes SENT; the bytes that LANDED are measured after
                 * recovery by reading the (pre-zeroed) remote buffer back. */
                if (post_write(&ep, WR_TRIGGER, msg_size, g_remote.addr, g_remote.rkey, false) < 0)
                    TRIAL_FAIL("post_write");
                t_inject = now_ns();
                if (ep_to_err(&ep) < 0) TRIAL_FAIL("modify QP->ERR");
                uint32_t sq_after = 0;
                if (ep_query_sq_psn(&ep, &sq_after) < 0) TRIAL_FAIL("query sq_psn (after)");
                sq_delta = (long)((sq_after - sq_before) & 0xFFFFFFu);   /* PSNs are 24-bit */
                bytes_sent_psn = sq_delta * (long)ep.mtu_bytes;
                got = poll_until_error(&ep, &wc, detect_timeout_ms);
                t_detect = now_ns();
                break;
            }
            default:
                TRIAL_FAIL("unsupported fault %s", fault_name(fault));
        }
        if (got < 0) TRIAL_FAIL("ibv_poll_cq error");

        long detect_ns = -1;
        int st_code = -1, peer_alive = -1, auto_rec = -1;
        uint32_t ven = 0;
        const char *st_name = "no_error_cqe";
        const char *cause = "no error CQE within the detect timeout (fault did not manifest)";
        const char *action = "-";
        if (got == 1) {
            classify_t cl = classify(wc.status, wc.vendor_err);
            /* a SUCCESS here is only possible for F0: nothing was detected */
            detect_ns = (wc.status != IBV_WC_SUCCESS) ? (long)(t_detect - t_inject) : -1;
            st_code = (int)wc.status; ven = wc.vendor_err;
            st_name = cl.status_name; cause = cl.cause; action = cl.action;
            peer_alive = cl.peer_alive; auto_rec = cl.auto_recoverable;
        } else if (fault == FAULT_NONE) {
            st_name = "no_cqe";
            cause = "F0 control: the write did not complete within the detect timeout";
            fprintf(stderr, "[client] trial %d: WARNING: F0 write did not complete within %ld ms\n",
                    it, detect_timeout_ms);
        } else {
            fprintf(stderr, "[client] trial %d: WARNING: no error CQE within %ld ms (fault did not manifest)\n",
                    it, detect_timeout_ms);
        }

        /* RETRY_EXC (0x81) is ambiguous from the CQE alone. Split it by
         * (a) link state: our RDMA port, or the peer's as reported in PROBED;
         * (b) peer liveness on the control channel (PROBE answered => node up,
         *     QP broken; no answer => process dead). peer_rx/peer_tx are the
         * responder's fault-window RDMA port deltas: diagnostics only (the
         * verification showed they do NOT separate server_qp_err from proc_kill).
         * REM_ACCESS (10/0x88) and REM_INV_REQ (9) get the same liveness check: a
         * SIGKILLed peer whose MR is torn down before its QP NAKs with 0x88 instead of
         * going silent (../teardown_order/), so an unanswered PROBE turns them into
         * proc_kill (peer dead, not recoverable) instead of an access bug. */
        char sub_cause[24] = "-";
        long peer_rx = -1, peer_tx = -1;
        int peer_port_up = -1;
        bool retry_exc = got == 1 && wc.status == IBV_WC_RETRY_EXC_ERR;
        bool rem_nak = got == 1 && (wc.status == IBV_WC_REM_ACCESS_ERR || wc.status == IBV_WC_REM_INV_REQ_ERR);
        if (retry_exc || rem_nak) {
            if (retry_exc && ep_port_state(&ep) != IBV_PORT_ACTIVE) {
                snprintf(sub_cause, sizeof(sub_cause), "link_down");
            } else {
                struct timeval tv = { 1, 0 };
                setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
                errno = 0;
                if (ctrl_send_line(fd, "PROBE") == 0 &&
                    ctrl_recv_line(fd, line, sizeof(line)) > 0 &&
                    sscanf(line, "PROBED %ld %ld %d", &peer_rx, &peer_tx, &peer_port_up) >= 1) {
                    if (retry_exc)
                        snprintf(sub_cause, sizeof(sub_cause), peer_port_up == 0 ? "link_down" : "server_qp_err");
                } else if (errno == EAGAIN || errno == EWOULDBLOCK) {
                    /* no answer within 1 s, connection still open: a hung or slow peer, not proof of
                     * death. Recorded apart from proc_kill; liveness unknown (-1). */
                    snprintf(sub_cause, sizeof(sub_cause), "no_answer");
                    peer_alive = -1; auto_rec = 0;
                } else {
                    /* EOF or reset on the control connection: the peer process is gone */
                    snprintf(sub_cause, sizeof(sub_cause), "proc_kill");
                    peer_alive = 0; auto_rec = 0;
                }
                tv.tv_sec = 0; tv.tv_usec = 0;
                setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
            }
        }

        /* Cross-layer state at fault time, before any recovery: the responder's QP state
         * and its async events since its GO, and our own async events since our GO.
         * "-" = the responder is dead (proc_kill faults, or an EOF on PROBE); "?" = no answer. */
        char srv_qp[16] = "-", srv_async[PROBE_ASYNC_FMT_MAX] = "-", cli_async[PROBE_ASYNC_FMT_MAX];
        usleep(QUERY_SETTLE_MS * 1000);
        if (!proc_kill && strcmp(sub_cause, "proc_kill") != 0)
            query_server(fd, srv_qp, sizeof(srv_qp), srv_async, sizeof(srv_async));
        async_mon_format(t_go_mono, cli_async, sizeof(cli_async));

        /* recovery */
        uint64_t t_rec0 = 0, t_rec1 = 0;
        int verify_ok = -1;
        if (!proc_kill) {
            if (recovery == RECOVER_NONE) {
                if (ctrl_send_line(fd, "NORECOVER") < 0) TRIAL_FAIL("send NORECOVER");
            } else {
                snprintf(line, sizeof(line), "RECOVER %s", recovery_name(recovery));
                t_rec0 = now_ns();
                if (ctrl_send_line(fd, line) < 0) TRIAL_FAIL("send RECOVER");
            }
            /* client rewire mirrors server; server sends dest first */
            if (client_bring_up(&ep, fd, recovery == RECOVER_FULL_REBUILD) < 0) TRIAL_FAIL("QP bring-up");
            if (ctrl_recv_line(fd, line, sizeof(line)) < 0) TRIAL_FAIL("no RECOK (server gone?)");
            if (strcmp(line, "RECOK") != 0) TRIAL_FAIL("expected RECOK, got '%s'", line);
            t_rec1 = now_ns();

            /* partial_write: measure landed bytes BEFORE the verify step overwrites
             * remote [0,4096). Done after NORECOVER too (the QP is RTS either way). */
            if (fault == FAULT_PARTIAL_WRITE) {
                size_t rb_len = msg_size <= g_remote.buf_size ? msg_size : g_remote.buf_size;
                if (readback_landed(&ep, rb_len, seed, &landed_rb, &match_total) < 0)
                    TRIAL_FAIL("partial_write readback (RDMA READ) failed");
            }

            /* verify: write pattern then read it back */
            fill_pattern(&ep, 0xA5);
            if (post_write(&ep, WR_VERIFY, 4096, g_remote.addr, g_remote.rkey, true) == 0 &&
                poll_one(&ep, &wc, 2000) == 1 && wc.status == IBV_WC_SUCCESS) {
                memset(ep.buf, 0, 4096);
                if (post_read(&ep, WR_VERIFY, 4096, g_remote.addr, g_remote.rkey) == 0 &&
                    poll_one(&ep, &wc, 2000) == 1 && wc.status == IBV_WC_SUCCESS) {
                    verify_ok = 1;
                    for (int b = 0; b < 4096; b++)
                        if ((uint8_t)ep.buf[b] != (uint8_t)(0xA5 + (b & 0xff))) { verify_ok = 0; break; }
                } else verify_ok = 0;
            } else verify_ok = 0;
        }

        uint64_t cnt_after = counter_read(dev, (uint8_t)ib_port, counter);
        long cnt_delta = (cnt_before != UINT64_MAX && cnt_after != UINT64_MAX)
                         ? (long)(cnt_after - cnt_before) : -1;
        long recover_ns = (t_rec1 > t_rec0 && t_rec0) ? (long)(t_rec1 - t_rec0) : -1;

        fprintf(fo, "%s,%d,%s,%ld,%d,%s,0x%x,\"%s\",\"%s\",%d,%d,%ld,%d,%ld,%ld,%ld,%ld,%d,%s,%ld,%s,%ld,"
                    "%s,%s,%s\n",
                fault_name(fault), it, recovery_name(recovery),
                detect_ns, st_code, st_name, ven, cause, action,
                peer_alive, auto_rec, recover_ns, verify_ok,
                bytes_sent_psn, sq_delta, landed_rb, match_total, ep.mtu_bytes,
                counter, cnt_delta, sub_cause, peer_rx,
                srv_qp, srv_async, cli_async);
        fflush(fo);
        completed++;

        fprintf(stderr, "[trial %d] %s: detect=%ldns status=%s(%d) vendor=0x%x sub=%s(peer_rx=%ld peer_tx=%ld) "
                        "recover=%ldns verify=%d srv_qp=%s srv_async=%s cli_async=%s",
                it, fault_name(fault), detect_ns, st_name, st_code, ven,
                sub_cause, peer_rx, peer_tx, recover_ns, verify_ok, srv_qp, srv_async, cli_async);
        if (fault == FAULT_PARTIAL_WRITE)
            fprintf(stderr, " sent_psn=%ld (sq_delta=%ld) landed_readback=%ld match_total=%ld",
                    bytes_sent_psn, sq_delta, landed_rb, match_total);
        fputc('\n', stderr);

        if (verify_ok == 0)
            TRIAL_FAIL("post-recovery verify failed (row recorded); connection unusable, stopping");
    }
#undef TRIAL_FAIL

endloop:
    if (fo && fo != stdout) fclose(fo);
    if (!proc_kill) ctrl_send_line(fd, "BYE");   /* proc_kill: the server already exited */
    close(fd);
    client_teardown(&ep);
    if (refused) {
        fprintf(stderr, "[client] aborted: fault %s unavailable on the server (%d/%d trials)\n",
                fault_name(fault), completed, iters);
        return 3;
    }
    if (failed || completed < iters) {
        fprintf(stderr, "[client] FAILED: %d/%d trials completed\n", completed, iters);
        return 1;
    }
    fprintf(stderr, "[client] done: %d/%d trials\n", completed, iters);
    return 0;

fail:
    if (fo && fo != stdout) fclose(fo);
    close(fd);
    client_teardown(&ep);
    return 1;
}
