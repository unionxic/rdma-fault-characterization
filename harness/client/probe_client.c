/*
 * probe_client.c - requester side of the unified RDMA fault harness.
 *
 * Runs on the requester node (e.g. rain, mlx5_1). Drives N trials of one fault
 * type, measuring per trial into a single CSV schema:
 *   detection latency, (status,vendor_err) classification, recovery latency,
 *   post-recovery verification, partial-write byte accounting, counter deltas.
 *
 * One trial:
 *   TRIAL -> OK -> [read counters] -> GO -> GOACK -> inject+measure detect
 *         -> RECOVER/NORECOVER -> RECOK -> [recovery latency] -> verify -> row
 */
#define _GNU_SOURCE
#include "probe.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <getopt.h>
#include <inttypes.h>

#define WR_TRIGGER 100
#define WR_VERIFY  200

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

static int client_bring_up(probe_ep_t *ep, int fd, bool full_rebuild) {
    uint32_t psn = pick_psn();
    if (full_rebuild) {
        ep_destroy_qp(ep);
        if (ep_create_qp(ep) < 0) return -1;
    } else {
        if (ep_to_reset(ep) < 0) return -1;
    }
    if (ep_to_init(ep) < 0) return -1;
    /* receive server dest first, then send ours */
    probe_dest_t local;
    if (tcp_recv_all(fd, &g_remote, sizeof(g_remote)) < 0) return -1;
    ep_fill_dest(ep, psn, &local);
    if (tcp_send_all(fd, &local, sizeof(local)) < 0) return -1;
    if (ep_to_rtr(ep, &g_remote) < 0) return -1;
    if (ep_to_rts(ep, psn) < 0) return -1;
    return 0;
}

/* poll completions, skipping SUCCESS, until the first error CQE or timeout.
 * returns 1 with wc set on error, 0 on timeout (only successes seen). */
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

/* fill local buffer with a detectable pattern */
static void fill_pattern(probe_ep_t *ep, uint8_t seed) {
    for (size_t i = 0; i < ep->buf_size; i++)
        ep->buf[i] = (uint8_t)(seed + (i & 0xff));
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
            case 'h': default:
                fprintf(stderr,
                  "usage: %s -s server -d dev -i port -g gid -p ctrlport\n"
                  "         -f fault -r recovery -n iters -o out.csv [-C cpu] [-S msgsize] [-k counter] [-t detect_ms]\n"
                  "faults: local_qp_err rem_access rem_inv_req rnr retry_server_qp_err retry_proc_kill partial_write\n"
                  "recovery: qp_only full_rebuild none\n", argv[0]);
                return (opt == 'h') ? 0 : 1;
        }
    }
    if (!server) { fprintf(stderr, "ERROR: -s server required\n"); return 1; }
    fault_type_t fault = fault_from_name(fault_s);
    recovery_method_t recovery = recovery_from_name(recov_s);
    if (msg_size > PROBE_BUF_SIZE) msg_size = PROBE_BUF_SIZE;
    pin_to_cpu(cpu);

    probe_ep_t ep;
    if (ep_open(&ep, dev, (uint8_t)ib_port, gid_index, PROBE_BUF_SIZE) < 0) return 1;
    if (ep_create_qp(&ep) < 0) { ep_close(&ep); return 1; }
    if (ep_to_init(&ep) < 0) { ep_close(&ep); return 1; }

    int fd = tcp_client_connect(server, ctrl_port);
    if (fd < 0) { ep_close(&ep); return 1; }

    char line[512];
    if (ctrl_send_line(fd, "HELLO") < 0) goto fail;
    if (connect_qp_client(&ep, fd, pick_psn()) < 0) goto fail;
    if (ctrl_recv_line(fd, line, sizeof(line)) < 0 || strcmp(line, "SYNC") != 0) {
        fprintf(stderr, "[client] handshake failed: '%s'\n", line); goto fail;
    }
    fprintf(stderr, "[client] connected to %s, dev %s gid %d, mtu %d B\n",
            server, dev, gid_index, ep.mtu_bytes);

    FILE *fo = out ? fopen(out, "w") : stdout;
    if (!fo) { perror("fopen"); goto fail; }
    fprintf(fo, "fault,iter,recovery,detect_ns,status,status_name,vendor_err,cause,action,"
                "peer_alive,auto_recoverable,recover_ns,verify_ok,bytes_landed,sq_psn_delta,mtu_bytes,"
                "counter,cnt_delta\n");

    for (int it = 0; it < iters; it++) {
        /* announce trial */
        snprintf(line, sizeof(line), "TRIAL %s %s", fault_name(fault), recovery_name(recovery));
        if (ctrl_send_line(fd, line) < 0) break;
        if (ctrl_recv_line(fd, line, sizeof(line)) < 0 || strcmp(line, "OK") != 0) break;

        /* g_remote is populated by the handshake (connect_qp_client) and refreshed
           by each recovery (client_bring_up), so it is always current here. */
        uint64_t cnt_before = counter_read(dev, (uint8_t)ib_port, counter);
        uint32_t sq_before = 0;
        ep_query_sq_psn(&ep, &sq_before);

        fill_pattern(&ep, (uint8_t)(0x40 + it));

        /* barrier */
        if (ctrl_send_line(fd, "GO") < 0) break;
        if (fault == FAULT_RETRY_PROC_KILL) {
            /* server exits on GO (no GOACK); let its QP be fully torn down so the
             * subsequent write has no responder and hits RETRY_EXC deterministically */
            usleep(300000);
        } else {
            if (ctrl_recv_line(fd, line, sizeof(line)) < 0 || strcmp(line, "GOACK") != 0) break;
        }

        uint64_t t_inject = 0, t_detect = 0;
        struct ibv_wc wc; memset(&wc, 0, sizeof(wc));
        int got = 0;
        uint32_t bytes_landed = 0, sq_delta = 0;

        switch (fault) {
            case FAULT_LOCAL_QP_ERR: {
                /* keep the send queue deep so WRs are still outstanding when we
                 * force ERR, then measure inject -> first WR_FLUSH_ERR CQE */
                for (int b = 0; b < 32; b++)
                    post_write(&ep, WR_TRIGGER + b, msg_size, g_remote.addr, g_remote.rkey, true);
                t_inject = now_ns();
                ep_to_err(&ep);
                got = poll_until_error(&ep, &wc, detect_timeout_ms);
                t_detect = now_ns();
                break;
            }
            case FAULT_REM_ACCESS: {
                /* valid rkey but write past the end of the remote MR */
                post_write(&ep, WR_TRIGGER, 4096, g_remote.addr + g_remote.buf_size, g_remote.rkey, true);
                t_inject = now_ns();
                got = poll_until_error(&ep, &wc, detect_timeout_ms);
                t_detect = now_ns();
                break;
            }
            case FAULT_REM_INV_REQ: {
                /* atomic to a responder QP that does not enable atomics ->
                 * operation-not-enabled at QP level -> REM_INV_REQ_ERR (9 / 0x8a) */
                post_atomic_fa(&ep, WR_TRIGGER, g_remote.addr, g_remote.rkey);
                t_inject = now_ns();
                got = poll_until_error(&ep, &wc, detect_timeout_ms);
                t_detect = now_ns();
                break;
            }
            case FAULT_RNR: {
                /* SEND with no remote recv WQE -> RNR retries exhausted */
                post_send(&ep, WR_TRIGGER, 64);
                t_inject = now_ns();
                got = poll_until_error(&ep, &wc, detect_timeout_ms);
                t_detect = now_ns();
                break;
            }
            case FAULT_RETRY_SERVER_QP_ERR:
            case FAULT_RETRY_PROC_KILL: {
                /* server stopped ACKing -> transport retries exhausted */
                post_write(&ep, WR_TRIGGER, 4096, g_remote.addr, g_remote.rkey, true);
                t_inject = now_ns();
                got = poll_until_error(&ep, &wc, detect_timeout_ms);
                t_detect = now_ns();
                break;
            }
            case FAULT_PARTIAL_WRITE: {
                /* large multi-packet write, force ERR mid-transfer, measure sq_psn advance */
                post_write(&ep, WR_TRIGGER, msg_size, g_remote.addr, g_remote.rkey, false);
                t_inject = now_ns();
                ep_to_err(&ep);
                uint32_t sq_after = 0;
                ep_query_sq_psn(&ep, &sq_after);
                sq_delta = sq_after - sq_before;
                bytes_landed = sq_delta * (uint32_t)ep.mtu_bytes;
                got = poll_until_error(&ep, &wc, detect_timeout_ms);
                t_detect = now_ns();
                break;
            }
            default:
                fprintf(stderr, "unsupported fault\n"); goto endloop;
        }

        long detect_ns = got == 1 ? (long)(t_detect - t_inject) : -1;
        enum ibv_wc_status st = (got == 1) ? wc.status : IBV_WC_GENERAL_ERR;
        uint32_t ven = (got == 1) ? wc.vendor_err : 0;
        classify_t cl = classify(st, ven);

        /* recovery */
        uint64_t t_rec0 = 0, t_rec1 = 0;
        int verify_ok = -1;
        bool proc_kill = (fault == FAULT_RETRY_PROC_KILL);
        if (!proc_kill) {
            if (recovery == RECOVER_NONE) {
                if (ctrl_send_line(fd, "NORECOVER") < 0) break;
            } else {
                snprintf(line, sizeof(line), "RECOVER %s", recovery_name(recovery));
                t_rec0 = now_ns();
                if (ctrl_send_line(fd, line) < 0) break;
            }
            /* client rewire mirrors server; server sends dest first */
            if (client_bring_up(&ep, fd, recovery == RECOVER_FULL_REBUILD) < 0) {
                fprintf(stderr, "[client] bring_up failed\n"); break;
            }
            if (ctrl_recv_line(fd, line, sizeof(line)) < 0 || strcmp(line, "RECOK") != 0) break;
            t_rec1 = now_ns();

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

        fprintf(fo, "%s,%d,%s,%ld,%d,%s,0x%x,\"%s\",\"%s\",%d,%d,%ld,%d,%u,%u,%d,%s,%ld\n",
                fault_name(fault), it, recovery_name(recovery),
                detect_ns, (int)st, cl.status_name, ven, cl.cause, cl.action,
                cl.peer_alive, cl.auto_recoverable, recover_ns, verify_ok,
                bytes_landed, sq_delta, ep.mtu_bytes, counter, cnt_delta);
        fflush(fo);

        fprintf(stderr, "[trial %d] %s: detect=%ldns status=%s(%d) vendor=0x%x recover=%ldns verify=%d\n",
                it, fault_name(fault), detect_ns, cl.status_name, (int)st, ven, recover_ns, verify_ok);

        if (proc_kill) {
            fprintf(stderr, "[client] proc_kill trial ends server; stopping after one trial\n");
            break;
        }
    }
endloop:
    if (fo && fo != stdout) fclose(fo);
    ctrl_send_line(fd, "BYE");
    close(fd);
    ep_close(&ep);
    return 0;

fail:
    close(fd);
    ep_close(&ep);
    return 1;
}
