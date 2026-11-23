/* fp_requester.c - requester side of the teardown-fingerprint experiment (one trial).
 *
 * 1. connects to fp_launcher (management network), measures the clock offset
 *    (min-RTT of 32 pings), asks it to SPAWN the victim fp_responder;
 * 2. connects to the victim's OOB port, exchanges QP info, waits for READY;
 * 3. streams signaled RDMA WRITEs (-S bytes, <= -D outstanding, one post every
 *    >= -I us) into the victim's MR;
 * 4. after -w ms of successful streaming, triggers the fault:
 *      -a kill        : launcher SIGKILLs the victim (t_trigger = launcher's timestamp)
 *      -a <action>    : victim performs <action> itself and stays alive
 *                       (dereg_mr, destroy_qp, cuda_free, cuda_reset, qp_err)
 * 5. records the first error CQE (status, vendor_err) and its time, the last
 *    successful completion, the OOB socket's FIN/RST time, and (from the launcher)
 *    the victim's reap time and the release time of every marker fd;
 * 6. appends one CSV row to -o. All times are on the responder's clock, relative
 *    to the trigger, in ms.
 */
#define _GNU_SOURCE
#include "fp_common.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <unistd.h>
#include <getopt.h>
#include <signal.h>
#include <sys/socket.h>

#define MAXMK 32

static int64_t g_off;     /* responder_clock - requester_clock, ns */
static uint64_t g_rtt;

static int clock_sync(int cfd) {
    char line[128];
    uint64_t best = UINT64_MAX;
    for (int i = 0; i < 32; i++) {
        uint64_t t0 = fp_now_ns();
        if (fp_send_line(cfd, "T") < 0 || fp_recv_line(cfd, line, sizeof(line)) < 0) return -1;
        uint64_t t1 = fp_now_ns();
        unsigned long ts = 0;
        if (sscanf(line, "T %lu", &ts) != 1) return -1;
        if (t1 - t0 < best) {
            best = t1 - t0;
            g_off = (int64_t)ts - (int64_t)((t0 + t1) / 2);
        }
    }
    g_rtt = best;
    return 0;
}

/* non-blocking line reader for a socket */
typedef struct { int fd; char buf[4096]; int len; int eof; int err; uint64_t t_eof; } nbline_t;
static int nb_poll(nbline_t *s) {           /* returns 1 if a full line is buffered */
    if (s->eof) return strchr(s->buf, '\n') != NULL;
    for (;;) {
        if (s->len >= (int)sizeof(s->buf) - 1) break;
        ssize_t k = recv(s->fd, s->buf + s->len, sizeof(s->buf) - 1 - (size_t)s->len, MSG_DONTWAIT);
        if (k > 0) { s->len += (int)k; s->buf[s->len] = 0; continue; }
        if (k == 0) { s->eof = 1; s->t_eof = fp_now_ns(); break; }
        if (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR) break;
        s->eof = 1; s->err = errno; s->t_eof = fp_now_ns(); break;
    }
    return strchr(s->buf, '\n') != NULL;
}
static int nb_take(nbline_t *s, char *out, size_t cap) {
    char *nl = strchr(s->buf, '\n');
    if (!nl) return -1;
    size_t l = (size_t)(nl - s->buf);
    if (l >= cap) l = cap - 1;
    memcpy(out, s->buf, l);
    out[l] = 0;
    size_t rest = (size_t)s->len - (size_t)(nl + 1 - s->buf);
    memmove(s->buf, nl + 1, rest);
    s->len = (int)rest;
    s->buf[s->len] = 0;
    return (int)l;
}

/* requester-side port HW counters, snapshotted at the trigger, at the first error CQE and
 * at the end: they show whether the requester retransmitted before the error arrived */
#define NCTR 6
static const char *ctr_names[NCTR] = { "roce_adp_retrans", "roce_adp_retrans_to", "local_ack_timeout_err",
                                       "packet_seq_err", "req_remote_access_errors", "rnr_nak_retry_err" };
static const char *ctr_short[NCTR] = { "adp", "adp_to", "ack_to", "pse", "rae", "rnr_exc" };
static void ctr_snap(const char *dev, int port, uint64_t *v) {
    for (int i = 0; i < NCTR; i++) {
        char p[256];
        snprintf(p, sizeof(p), "/sys/class/infiniband/%s/ports/%d/hw_counters/%s", dev, port, ctr_names[i]);
        FILE *f = fopen(p, "r");
        unsigned long long x = 0;
        if (!f || fscanf(f, "%llu", &x) != 1) x = 0;
        if (f) fclose(f);
        v[i] = x;
    }
}
static void ctr_fmt(char *out, size_t cap, const uint64_t *a, const uint64_t *b) {
    size_t o = 0;
    out[0] = 0;
    for (int i = 0; i < NCTR && o + 32 < cap; i++)
        o += (size_t)snprintf(out + o, cap - o, "%s%s=%ld", i ? " " : "", ctr_short[i], (long)(b[i] - a[i]));
}

static double rel_ms(uint64_t t_req, uint64_t t_trig_resp) {   /* requester time -> ms after trigger */
    if (!t_req || !t_trig_resp) return -1;
    return ((double)((int64_t)t_req + g_off) - (double)t_trig_resp) / 1e6;
}
static double rel_ms_resp(uint64_t t_resp, uint64_t t_trig_resp) {
    if (!t_resp || !t_trig_resp) return -1;
    return ((double)t_resp - (double)t_trig_resp) / 1e6;
}

int main(int argc, char **argv) {
    const char *dev = "mlx5_1", *lhost = NULL, *rargs = NULL, *rlog = "/tmp/fp_resp.log";
    const char *action = "kill", *variant = "?", *out = NULL;
    int port = 1, gid = -1, cport = 18931, oport = 18932, trial = 0, depth = 8, opt;
    size_t msg = 65536;
    long warm_ms = 300, timeout_ms = 8000, interval_us = 50, quiet_ok_ms = 1500;
    while ((opt = getopt(argc, argv, "d:i:g:L:p:P:R:l:a:w:S:D:I:T:Q:v:n:o:")) != -1) {
        switch (opt) {
            case 'd': dev = optarg; break;
            case 'i': port = atoi(optarg); break;
            case 'g': gid = atoi(optarg); break;
            case 'L': lhost = optarg; break;
            case 'p': cport = atoi(optarg); break;
            case 'P': oport = atoi(optarg); break;
            case 'R': rargs = optarg; break;
            case 'l': rlog = optarg; break;
            case 'a': action = optarg; break;
            case 'w': warm_ms = atol(optarg); break;
            case 'S': msg = (size_t)strtoull(optarg, NULL, 0); break;
            case 'D': depth = atoi(optarg); break;
            case 'I': interval_us = atol(optarg); break;
            case 'T': timeout_ms = atol(optarg); break;
            case 'Q': quiet_ok_ms = atol(optarg); break;
            case 'v': variant = optarg; break;
            case 'n': trial = atoi(optarg); break;
            case 'o': out = optarg; break;
            default: fprintf(stderr, "see source header for usage\n"); return 2;
        }
    }
    if (!lhost || !rargs) { fprintf(stderr, "-L launcher_host and -R responder_argv are required\n"); return 2; }
    signal(SIGPIPE, SIG_IGN);
    const int is_kill = !strcmp(action, "kill");

    /* local RDMA resources first, so the victim is not kept waiting */
    fp_ep_t ep;
    if (fp_open(&ep, dev, port, gid, 0) < 0 || fp_create_qp(&ep, depth + 8) < 0) return 1;
    size_t lbytes = msg * (size_t)depth;
    char *lbuf = aligned_alloc(4096, lbytes);
    if (!lbuf) return 1;
    for (size_t i = 0; i < lbytes; i++) lbuf[i] = (char)(i * 7 + trial);
    struct ibv_mr *lmr = ibv_reg_mr(ep.pd, lbuf, lbytes, IBV_ACCESS_LOCAL_WRITE);
    if (!lmr) { perror("ibv_reg_mr"); return 1; }

    int cfd = fp_connect(lhost, cport);
    if (cfd < 0) { fprintf(stderr, "cannot reach launcher %s:%d\n", lhost, cport); return 1; }
    if (clock_sync(cfd) < 0) { fprintf(stderr, "clock sync failed\n"); return 1; }
    char line[4096];
    if (fp_send_line(cfd, "SPAWN %s %s", rlog, rargs) < 0 || fp_recv_line(cfd, line, sizeof(line)) < 0 ||
        strncmp(line, "PID ", 4) != 0) { fprintf(stderr, "spawn failed: %s\n", line); return 1; }
    int vpid = atoi(line + 4);

    int ofd = -1;
    uint64_t tc = fp_now_ns();
    while ((ofd = fp_connect(lhost, oport)) < 0) {
        if ((fp_now_ns() - tc) / 1000000ull > 30000) { fprintf(stderr, "victim OOB not reachable\n"); goto bye; }
        usleep(20000);
    }
    fp_dest_t rem, me;
    if (fp_recv_all(ofd, &rem, sizeof(rem)) < 0) { fprintf(stderr, "no dest from victim\n"); goto bye; }
    memset(&me, 0, sizeof(me));
    me.qpn = ep.qp->qp_num;
    me.psn = (uint32_t)((fp_now_ns() >> 5) & 0xffffff);
    me.gid = ep.gid;
    if (fp_send_all(ofd, &me, sizeof(me)) < 0 || fp_qp_to_rts(&ep, &rem, me.psn) < 0) goto bye;
    if (fp_recv_line(ofd, line, sizeof(line)) < 0 || strncmp(line, "READY", 5) != 0) {
        fprintf(stderr, "victim not ready: '%s'\n", line); goto bye;
    }
    int r_pid = 0, r_cmdfd = -1, r_nmk = 0;
    char fds[2048] = "";
    sscanf(line, "READY %d %d %d %2047s", &r_pid, &r_cmdfd, &r_nmk, fds);

    /* ---- stream ---- */
    nbline_t os = { .fd = ofd }, cs = { .fd = cfd };
    uint64_t t_start = fp_now_ns(), t_last_post = 0, t_trig_sent = 0, t_trig_resp = 0, t_act_end = 0;
    uint64_t t_err = 0, t_last_ok = 0, n_ok = 0, n_ok_after = 0, posted = 0;
    int outstanding = 0, triggered = 0, err_status = -1, stop_post = 0, trig_rc = 0;
    uint32_t err_vendor = 0;
    uint64_t err_wrid = 0;
    int n_flush = 0, n_other_err = 0;
    const char *end_reason = "timeout";
    struct ibv_wc wc[32];
    uint64_t c_trig[NCTR] = {0}, c_err[NCTR] = {0}, c_end[NCTR] = {0};
    for (;;) {
        uint64_t now = fp_now_ns();
        int n = ibv_poll_cq(ep.cq, 32, wc);
        if (n < 0) { end_reason = "poll_error"; break; }
        for (int k = 0; k < n; k++) {
            outstanding--;
            if (wc[k].status == IBV_WC_SUCCESS) {
                n_ok++;
                t_last_ok = now;
                if (triggered) n_ok_after++;
            } else if (err_status < 0) {
                err_status = (int)wc[k].status;
                err_vendor = wc[k].vendor_err;
                err_wrid = wc[k].wr_id;
                t_err = now;
                stop_post = 1;
                if (triggered) ctr_snap(dev, port, c_err);
            } else if (wc[k].status == IBV_WC_WR_FLUSH_ERR) {
                n_flush++;
            } else {
                n_other_err++;
            }
        }
        while (!stop_post && outstanding < depth && (now - t_last_post) >= (uint64_t)interval_us * 1000ull) {
            struct ibv_sge sge = { .addr = (uint64_t)(uintptr_t)(lbuf + (posted % (uint64_t)depth) * msg),
                                   .length = (uint32_t)msg, .lkey = lmr->lkey };
            struct ibv_send_wr wr, *bad = NULL;
            memset(&wr, 0, sizeof(wr));
            wr.wr_id = posted;
            wr.sg_list = &sge;
            wr.num_sge = 1;
            wr.opcode = IBV_WR_RDMA_WRITE;
            wr.send_flags = IBV_SEND_SIGNALED;
            wr.wr.rdma.remote_addr = rem.addr + (posted % (rem.size / msg)) * msg;
            wr.wr.rdma.rkey = rem.rkey;
            if (ibv_post_send(ep.qp, &wr, &bad)) { stop_post = 1; break; }
            posted++;
            outstanding++;
            t_last_post = now;
        }
        /* OOB (victim) socket: FIN/RST and ACTED replies */
        if (nb_poll(&os)) {
            while (nb_take(&os, line, sizeof(line)) >= 0) {
                unsigned long a0 = 0, a1 = 0;
                char an[64];
                if (sscanf(line, "ACTED %63s %d %lu %lu", an, &trig_rc, &a0, &a1) == 4) {
                    t_trig_resp = a0;
                    t_act_end = a1;
                }
            }
        }
        /* launcher socket: KILLED reply */
        if (nb_poll(&cs)) {
            while (nb_take(&cs, line, sizeof(line)) >= 0) {
                unsigned long tk = 0;
                if (sscanf(line, "KILLED %lu", &tk) == 1) t_trig_resp = tk;
            }
        }
        if (!triggered && (now - t_start) / 1000000ull >= (uint64_t)warm_ms) {
            if (n_ok == 0 || err_status >= 0) { end_reason = "no_success_before_trigger"; break; }
            triggered = 1;
            t_trig_sent = fp_now_ns();
            ctr_snap(dev, port, c_trig);
            if (is_kill) fp_send_line(cfd, "KILL");
            else fp_send_line(ofd, "ACT %s", action);
        }
        if (triggered) {
            uint64_t since = now > t_trig_sent ? (now - t_trig_sent) / 1000000ull : 0;   /* t_trig_sent may be later than now */
            int drained = (err_status >= 0 && outstanding == 0);
            if (is_kill && drained && os.eof) { end_reason = "error_and_oob_closed"; break; }
            if (!is_kill && drained && t_trig_resp) { end_reason = "error"; break; }
            if (!is_kill && err_status < 0 && t_trig_resp && since >= (uint64_t)quiet_ok_ms &&
                n_ok_after > 0 && (now - t_last_ok) < 5000000ull) { end_reason = "no_error_writes_ok"; break; }
            if (since >= (uint64_t)timeout_ms) { end_reason = "timeout"; break; }
        }
    }
    uint64_t t_end = fp_now_ns();
    (void)t_end;
    ctr_snap(dev, port, c_end);
    char cerr[160] = "-", cend[160] = "-";
    if (triggered && t_err) ctr_fmt(cerr, sizeof(cerr), c_trig, c_err);
    if (triggered) ctr_fmt(cend, sizeof(cend), c_trig, c_end);

    /* after an explicit action the victim is still alive: kill it now (cleanup) */
    if (!is_kill) {
        fp_send_line(cfd, "KILL");
    }
    /* collect the launcher's report (drain any pending KILLED line first) */
    fp_send_line(cfd, "REPORT 8000");
    char mkstr[2048] = "";
    size_t mo = 0;
    uint64_t t_kill = 0, t_reap = 0;
    int wst = -1;
    struct { char l[32]; int fd; uint64_t to, tcl; } mks[MAXMK];
    int nm = 0;
    for (;;) {
        /* blocking line read through the same buffer the stream loop used */
        while (!strchr(cs.buf, '\n')) {
            if (cs.len >= (int)sizeof(cs.buf) - 1) { cs.len = 0; cs.buf[0] = 0; }
            ssize_t k = recv(cfd, cs.buf + cs.len, sizeof(cs.buf) - 1 - (size_t)cs.len, 0);
            if (k <= 0) break;
            cs.len += (int)k;
            cs.buf[cs.len] = 0;
        }
        if (nb_take(&cs, line, sizeof(line)) < 0) break;
        unsigned long a = 0, b = 0;
        if (!strcmp(line, "END")) break;
        if (!strncmp(line, "MK ", 3) && nm < MAXMK) {
            if (sscanf(line, "MK %31s %d %lu %lu", mks[nm].l, &mks[nm].fd, &a, &b) == 4) {
                mks[nm].to = a; mks[nm].tcl = b; nm++;
            }
        } else if (sscanf(line, "RP %lu %lu %d", &a, &b, &wst) == 3) {
            t_kill = a; t_reap = b;
        } else if (sscanf(line, "KILLED %lu", &a) == 1 && is_kill && !t_trig_resp) {
            t_trig_resp = a;
        }
    }
    if (is_kill && !t_trig_resp) t_trig_resp = t_kill;
    /* markers sorted by close time */
    for (int i = 0; i < nm; i++)
        for (int j = i + 1; j < nm; j++)
            if ((mks[j].tcl ? mks[j].tcl : UINT64_MAX) < (mks[i].tcl ? mks[i].tcl : UINT64_MAX)) {
                __typeof__(mks[0]) t = mks[i]; mks[i] = mks[j]; mks[j] = t;
            }
    for (int i = 0; i < nm && mo + 64 < sizeof(mkstr); i++)
        mo += (size_t)snprintf(mkstr + mo, sizeof(mkstr) - mo, "%s%s@fd%d:%.3f", i ? "|" : "",
                               mks[i].l, mks[i].fd, rel_ms_resp(mks[i].tcl, t_trig_resp));

    const char *fin_kind = !os.eof ? "none" : os.err ? (os.err == ECONNRESET ? "RST" : "ERR") : "FIN";
    double err_ms = rel_ms(t_err, t_trig_resp);
    double lastok_ms = t_last_ok > t_trig_sent ? rel_ms(t_last_ok, t_trig_resp) : -1;
    double fin_ms = os.eof ? rel_ms(os.t_eof, t_trig_resp) : -1;
    double reap_ms = is_kill ? rel_ms_resp(t_reap, t_trig_resp) : -1;
    double act_ms = (!is_kill && t_act_end) ? rel_ms_resp(t_act_end, t_trig_resp) : -1;

    fprintf(stderr, "[req] %s #%d %s: first_err=%s(%d) vendor=0x%x after %.3f ms; last_ok %.3f ms; "
                    "ok_after=%lu flush=%d; OOB %s at %.3f ms; reaped %.3f ms; act_dur %.3f ms; end=%s; "
                    "rtt=%.3f ms\n  counters trigger->error: %s | trigger->end: %s\n"
                    "  markers(close order): %s\n  victim fds: %s\n",
            variant, trial, action, err_status >= 0 ? fp_status_short(err_status) : "none", err_status,
            err_vendor, err_ms, lastok_ms, (unsigned long)n_ok_after, n_flush, fin_kind, fin_ms, reap_ms,
            act_ms, end_reason, g_rtt / 1e6, cerr, cend, mkstr, fds);
    if (out) {
        FILE *f = fopen(out, "a");
        if (f) {
            fseek(f, 0, SEEK_END);
            if (ftell(f) == 0)
                fprintf(f, "variant,trial,trigger,status,status_name,vendor_err,err_ms,last_ok_ms,ok_after,"
                           "n_flush,n_other_err,oob_close,oob_close_ms,reap_ms,act_ms,trig_rc,end_reason,"
                           "victim_pid,uverbs_fd,clock_rtt_ms,err_wrid,posted,markers_close_order,victim_fds,"
                           "ctr_trig_to_err,ctr_trig_to_end\n");
            fprintf(f, "%s,%d,%s,%d,%s,0x%x,%.3f,%.3f,%lu,%d,%d,%s,%.3f,%.3f,%.3f,%d,%s,%d,%d,%.3f,%lu,%lu,%s,\"%s\",%s,%s\n",
                    variant, trial, action, err_status, err_status >= 0 ? fp_status_short(err_status) : "none",
                    err_vendor, err_ms, lastok_ms, (unsigned long)n_ok_after, n_flush, n_other_err, fin_kind,
                    fin_ms, reap_ms, act_ms, trig_rc, end_reason, r_pid ? r_pid : vpid, r_cmdfd, g_rtt / 1e6,
                    (unsigned long)err_wrid, (unsigned long)posted, mkstr, fds, cerr, cend);
            fclose(f);
        }
    }
    fp_send_line(cfd, "BYE");
    fp_recv_line(cfd, line, sizeof(line));
    close(ofd);
    close(cfd);
    return err_status >= 0 || !strcmp(end_reason, "no_error_writes_ok") ? 0 : 1;

bye:
    fp_send_line(cfd, "BYE");
    fp_recv_line(cfd, line, sizeof(line));
    return 1;
}
