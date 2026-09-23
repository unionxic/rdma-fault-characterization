/*
 * cqe_seq_client.c - GPU-initiated fault study, question Q1 (CPU verbs, no GPU).
 *
 * Question. After a fault, which CQEs does the NIC write, and in what order?
 * GPU-initiated stacks (NVSHMEM IBGDA) poll a *collapsed* CQ: a single CQE slot
 * that the NIC overwrites with every CQE it writes, so the GPU finds whatever the
 * NIC wrote last. On a normal CQ (this tool) every CQE lands in its own slot, and
 * ibv_poll_cq returns them in the order the NIC wrote them; that order is the
 * order in which a collapsed slot would be overwritten. (This is an inference:
 * it assumes the NIC writes the same CQEs in the same order to a collapsed CQ.)
 *
 * One trial (harness control protocol, unchanged harness probe_server):
 *   TRIAL <fault> qp_only -> OK -> GO -> GOACK      (retry_proc_kill: the server
 *        exits on GO and sends nothing; we wait 300 ms, as probe_client does)
 *   -> post a batch of N WQEs with ONE ibv_post_send (+ the trigger, see below)
 *   -> drain the CQ, timestamping every CQE, until the CQ has stayed empty for a
 *      quiet period after the first error CQE (bounded overall)
 *   -> ibv_query_qp (QP state) and one late sweep of the CQ
 *   -> RECOVER qp_only -> coordinated ERR->RESET->INIT->RTR->RTS -> RECOK
 *   -> verify: 4 KiB WRITE + READ-back of a fresh pattern (as probe_client does)
 *
 * The batch (WQE index i = 0..N-1; every WQE that is not the bad one is a valid
 * RDMA WRITE of -S bytes, 4 KiB by default, at its own offset):
 *   local_qp_err        all valid; trigger = move our own QP to ERR right after
 *                       the post (t0 = just before ibv_modify_qp)
 *   rem_access          WQE k = 4 KiB WRITE at remote addr + buf_size (past the
 *                       end of the remote MR)                  -> 10 / 0x88
 *   rem_inv_req         WQE k = 8-byte fetch-and-add; the responder QP does not
 *                       enable REMOTE_ATOMIC                   -> 9 / 0x8a
 *   rnr                 WQE k = 64 B SEND; the responder never posts a recv
 *                       (rnr_retry 6)                          -> 13 / 0x87
 *   retry_server_qp_err all valid; the server moved its QP to ERR before GOACK
 *   retry_proc_kill     all valid; the server process exited on GO
 *   t0 (time zero of every CQE timestamp) = just before ibv_post_send, except
 *   local_qp_err: just before ibv_modify_qp(ERR). k is 0 ("first"), N/2
 *   ("middle") or N-1 ("last"); for N = 1 only "first" runs (they are the same WQE).
 *
 * Signaling (the QP is created with sq_sig_all = 0 by the harness core):
 *   all   every WQE carries IBV_SEND_SIGNALED
 *   last  only WQE N-1 is signaled (selective signaling, as GPU-initiated stacks do)
 *
 * wr_id = 0xC5E0 << 48 | trial_uid << 16 | wqe_index, so every CQE maps back to
 * its WQE and a CQE from another trial would be flagged (foreign=1).
 *
 * Output (both files are appended to; a header is written when a file is empty):
 *   -o raw CSV     one row per CQE, in poll order, with the trial keys
 *   -O trials CSV  one row per trial (CQE count, how the drain ended, QP state,
 *                  verify result) - a trial that produced no CQE shows up here only
 *
 * Exit status: 0 = all trials completed and verified; 1 = a protocol/RDMA step
 * failed (rows already written are kept); 2 = bad arguments.
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
#include <sys/stat.h>
#include <sys/time.h>

#define MAX_N          256       /* WQEs per batch (the harness QP has max_send_wr 512) */
#define MAX_LIST       8
#define MAX_REC        4096      /* CQEs kept per trial */
#define WRID_MAGIC     0xC5E0ull /* top 16 bits of every batch wr_id */
#define WRID_VERIFY    0xC5E1ull /* top 16 bits of the verify WRITE/READ */
#define OP_UNSET       0xff      /* wc.opcode sentinel: providers leave it unset on error CQEs */
#define CTRL_TIMEOUT_S 30        /* bound on every control-channel receive */
#define HARD_MARGIN_MS 1000      /* drain hard bound = first-error timeout + quiet + this */
#define BAD_LEN_WRITE  4096
#define BAD_LEN_SEND   64

typedef enum { SIG_ALL = 0, SIG_LAST } sig_mode_t;
typedef enum { POS_NONE = 0, POS_FIRST, POS_MIDDLE, POS_LAST } pos_t;
typedef enum { K_WRITE = 0, K_OOB_WRITE, K_ATOMIC, K_SEND } wqe_kind_t;
typedef enum { DRAIN_QUIET = 0, DRAIN_NO_ERROR, DRAIN_BOUND } drain_end_t;

static const char *sig_names[]   = { "all", "last" };
static const char *pos_names[]   = { "none", "first", "middle", "last" };
static const char *kind_names[]  = { "write", "oob_write", "atomic_fa", "send" };
static const char *drain_names[] = { "quiet", "no_error", "bound" };

/* one polled CQE */
typedef struct {
    uint64_t wr_id;
    int      wqe_idx;      /* -1 if the wr_id is not from this trial's batch */
    int      status;
    uint32_t vendor_err;
    int      opcode;       /* OP_UNSET if the provider did not set it */
    uint32_t byte_len;
    uint32_t qp_num;
    int64_t  t_ns;         /* poll time - t0 */
    int      late;         /* found by the sweep after ibv_query_qp */
    int      foreign;      /* wr_id not from this trial's batch */
} cqe_rec_t;

/* one matrix cell */
typedef struct {
    fault_type_t fault;
    size_t       wqe_bytes;
    int          n;
    sig_mode_t   sig;
    pos_t        pos;
    int          bad_idx;  /* -1: no bad WQE in the batch */
} cell_t;

static probe_dest_t g_remote;     /* responder QP/MR, refreshed by every bring-up */
static struct ibv_send_wr g_wr[MAX_N];
static struct ibv_sge     g_sge[MAX_N];
static wqe_kind_t         g_kind[MAX_N];
static bool               g_signaled[MAX_N];
static cqe_rec_t          g_rec[MAX_REC];

static uint32_t pick_psn(void) { return (uint32_t)((now_ns() >> 3) & 0xffffff); }

static uint64_t mk_wrid(uint64_t magic, uint32_t uid, int idx) {
    return (magic << 48) | ((uint64_t)uid << 16) | (uint64_t)(idx & 0xffff);
}

/* ---------------- QP wiring (mirrors probe_client.c) ---------------- */
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
/* qp_only recovery, client half: RESET -> INIT -> (exchange) -> RTR -> RTS.
 * RESET also makes libmlx5 discard any CQE of this QP still in the CQ, so the
 * drain + late sweep before it are the last chance to see a trial's CQEs. */
static int client_bring_up_qp_only(probe_ep_t *ep, int fd) {
    if (ep_to_reset(ep) < 0) return -1;
    if (ep_to_init(ep) < 0) return -1;
    return connect_qp_client(ep, fd, pick_psn());
}

static const char *qp_state_name(enum ibv_qp_state s) {
    switch (s) {
        case IBV_QPS_RESET: return "RESET";
        case IBV_QPS_INIT:  return "INIT";
        case IBV_QPS_RTR:   return "RTR";
        case IBV_QPS_RTS:   return "RTS";
        case IBV_QPS_SQD:   return "SQD";
        case IBV_QPS_SQE:   return "SQE";
        case IBV_QPS_ERR:   return "ERR";
        default:            return "UNKNOWN";
    }
}

/* ---------------- the batch ---------------- */
/* Build the chained WR list for one trial. Valid writes use their own offset
 * (wrapping inside the 4 MiB region) on both sides; the bad WQE is at bad_idx. */
static void build_batch(probe_ep_t *ep, const cell_t *c, uint32_t uid) {
    for (int i = 0; i < c->n; i++) {
        struct ibv_send_wr *wr = &g_wr[i];
        struct ibv_sge *sge = &g_sge[i];
        memset(wr, 0, sizeof(*wr));
        memset(sge, 0, sizeof(*sge));
        wqe_kind_t kind = K_WRITE;
        if (i == c->bad_idx) {
            if (c->fault == FAULT_REM_ACCESS)       kind = K_OOB_WRITE;
            else if (c->fault == FAULT_REM_INV_REQ) kind = K_ATOMIC;
            else if (c->fault == FAULT_RNR)         kind = K_SEND;
        }
        g_kind[i] = kind;
        g_signaled[i] = (c->sig == SIG_ALL) || (i == c->n - 1);

        wr->wr_id = mk_wrid(WRID_MAGIC, uid, i);
        wr->sg_list = sge;
        wr->num_sge = 1;
        wr->send_flags = g_signaled[i] ? IBV_SEND_SIGNALED : 0;
        wr->next = (i + 1 < c->n) ? &g_wr[i + 1] : NULL;
        sge->lkey = ep->mr->lkey;

        switch (kind) {
            case K_WRITE: {
                size_t off = ((size_t)i * c->wqe_bytes) % ep->buf_size;
                if (off + c->wqe_bytes > ep->buf_size || off + c->wqe_bytes > g_remote.buf_size) off = 0;
                sge->addr = (uint64_t)(uintptr_t)(ep->buf + off);
                sge->length = (uint32_t)c->wqe_bytes;
                wr->opcode = IBV_WR_RDMA_WRITE;
                wr->wr.rdma.remote_addr = g_remote.addr + off;
                wr->wr.rdma.rkey = g_remote.rkey;
                break;
            }
            case K_OOB_WRITE:   /* valid rkey, address just past the end of the remote MR */
                sge->addr = (uint64_t)(uintptr_t)ep->buf;
                sge->length = BAD_LEN_WRITE;
                wr->opcode = IBV_WR_RDMA_WRITE;
                wr->wr.rdma.remote_addr = g_remote.addr + g_remote.buf_size;
                wr->wr.rdma.rkey = g_remote.rkey;
                break;
            case K_ATOMIC:      /* responder QP has no REMOTE_ATOMIC -> operation not enabled */
                sge->addr = (uint64_t)(uintptr_t)(ep->buf + ep->buf_size - 8);
                sge->length = 8;
                wr->opcode = IBV_WR_ATOMIC_FETCH_AND_ADD;
                wr->wr.atomic.remote_addr = g_remote.addr;
                wr->wr.atomic.rkey = g_remote.rkey;
                wr->wr.atomic.compare_add = 1;
                break;
            case K_SEND:        /* responder never posts a receive */
                sge->addr = (uint64_t)(uintptr_t)ep->buf;
                sge->length = BAD_LEN_SEND;
                wr->opcode = IBV_WR_SEND;
                break;
        }
    }
}

/* ---------------- the drain ---------------- */
static void record_wc(const struct ibv_wc *wc, uint32_t uid, int n, int64_t t_ns, int late, int *nrec, int *ndrop) {
    if (*nrec >= MAX_REC) { (*ndrop)++; return; }
    cqe_rec_t *r = &g_rec[(*nrec)++];
    r->wr_id = wc->wr_id;
    r->status = (int)wc->status;
    r->vendor_err = wc->vendor_err;
    r->opcode = (int)wc->opcode;
    r->byte_len = wc->byte_len;
    r->qp_num = wc->qp_num;
    r->t_ns = t_ns;
    r->late = late;
    uint64_t idx = wc->wr_id & 0xffff;
    if ((wc->wr_id >> 48) == WRID_MAGIC && ((wc->wr_id >> 16) & 0xffffffffull) == uid && (int)idx < n) {
        r->wqe_idx = (int)idx;
        r->foreign = 0;
    } else {
        r->wqe_idx = -1;
        r->foreign = 1;
    }
}

static void wc_reset(struct ibv_wc *wc) {
    memset(wc, 0, sizeof(*wc));
    wc->opcode = (enum ibv_wc_opcode)OP_UNSET;
}

/* Tight-poll the CQ from t0, recording every CQE with its poll time. Ends when
 * the CQ has been empty for quiet_ms after the last CQE AND either an error CQE
 * was seen (DRAIN_QUIET) or first_err_ms passed without one (DRAIN_NO_ERROR);
 * hard bound first_err_ms + quiet_ms + HARD_MARGIN_MS (DRAIN_BOUND). */
static int drain_cq(probe_ep_t *ep, uint64_t t0, long first_err_ms, long quiet_ms, uint32_t uid, int n,
                    int *nrec, int *ndrop, drain_end_t *end, uint64_t *t_end) {
    const uint64_t quiet = (uint64_t)quiet_ms * 1000000ull;
    const uint64_t first_deadline = t0 + (uint64_t)first_err_ms * 1000000ull;
    const uint64_t hard = first_deadline + quiet + (uint64_t)HARD_MARGIN_MS * 1000000ull;
    uint64_t t_last = t0;
    bool seen_err = false;
    struct ibv_wc wc;
    for (;;) {
        wc_reset(&wc);
        int got = ibv_poll_cq(ep->cq, 1, &wc);
        uint64_t now = now_ns();
        if (got < 0) { fprintf(stderr, "[cqe_seq] ibv_poll_cq < 0\n"); return -1; }
        if (got == 1) {
            record_wc(&wc, uid, n, (int64_t)(now - t0), 0, nrec, ndrop);
            t_last = now;
            if (wc.status != IBV_WC_SUCCESS) seen_err = true;
            continue;
        }
        if (now - t_last >= quiet && (seen_err || now >= first_deadline)) {
            *end = seen_err ? DRAIN_QUIET : DRAIN_NO_ERROR;
            *t_end = now;
            return 0;
        }
        if (now >= hard) { *end = DRAIN_BOUND; *t_end = now; return 0; }
    }
}

/* ---------------- verify (as probe_client.c) ---------------- */
static int poll_expect(probe_ep_t *ep, uint64_t wr_id, long timeout_ms) {
    struct ibv_wc wc;
    wc_reset(&wc);
    int got = poll_one(ep, &wc, timeout_ms);
    if (got != 1) { fprintf(stderr, "[cqe_seq] verify: no CQE (got=%d)\n", got); return -1; }
    if (wc.wr_id != wr_id || wc.status != IBV_WC_SUCCESS) {
        fprintf(stderr, "[cqe_seq] verify: unexpected CQE wr_id=0x%" PRIx64 " status=%s vendor_err=0x%x\n",
                (uint64_t)wc.wr_id, ibv_wc_status_str(wc.status), wc.vendor_err);
        return -1;
    }
    return 0;
}
static int verify_path(probe_ep_t *ep, uint32_t uid) {
    const uint8_t seed = (uint8_t)(0xA5 + uid);
    for (int b = 0; b < 4096; b++) ep->buf[b] = (char)(uint8_t)(seed + (b & 0xff));
    uint64_t w = mk_wrid(WRID_VERIFY, uid, 0), r = mk_wrid(WRID_VERIFY, uid, 1);
    if (post_write(ep, w, 4096, g_remote.addr, g_remote.rkey, true) < 0) return 0;
    if (poll_expect(ep, w, 2000) < 0) return 0;
    memset(ep->buf, 0, 4096);
    if (post_read(ep, r, 4096, g_remote.addr, g_remote.rkey) < 0) return 0;
    if (poll_expect(ep, r, 2000) < 0) return 0;
    for (int b = 0; b < 4096; b++)
        if ((uint8_t)ep->buf[b] != (uint8_t)(seed + (b & 0xff))) return 0;
    return 1;
}

/* ---------------- CSV ---------------- */
static FILE *open_append(const char *path, const char *header) {
    FILE *f = fopen(path, "a");
    if (!f) { perror(path); return NULL; }
    struct stat sb;
    if (fstat(fileno(f), &sb) == 0 && sb.st_size == 0) { fputs(header, f); fflush(f); }
    return f;
}
#define RAW_HEADER "run_id,fault,wqe_bytes,n_wqe,signaling,bad_pos,bad_idx,trial,trial_uid,seq," \
                   "wqe_idx,wqe_kind,wqe_signaled,wr_id,status,status_name,vendor_err,opcode," \
                   "byte_len,qp_num,t_ns,late,foreign\n"
#define TRIAL_HEADER "run_id,fault,wqe_bytes,n_wqe,signaling,bad_pos,bad_idx,trial,trial_uid," \
                     "n_cqes,n_late,n_foreign,n_dropped,drain_end,drain_ns,post_ns,trigger_ns," \
                     "qp_state_after,verify_ok\n"

static void cell_keys(FILE *f, const char *run_id, const cell_t *c, int trial, uint32_t uid) {
    fprintf(f, "%s,%s,%zu,%d,%s,%s,%d,%d,%u,", run_id, fault_name(c->fault), c->wqe_bytes, c->n,
            sig_names[c->sig], pos_names[c->pos], c->bad_idx, trial, uid);
}

/* ---------------- argument lists ---------------- */
static int parse_int_list(const char *s, int *out, int cap) {
    int n = 0;
    char buf[128];
    snprintf(buf, sizeof(buf), "%s", s);
    for (char *save = NULL, *tok = strtok_r(buf, ",", &save); tok; tok = strtok_r(NULL, ",", &save)) {
        char *end = NULL;
        long v = strtol(tok, &end, 10);
        if (!end || *end || v < 1 || v > MAX_N || n >= cap) return -1;
        out[n++] = (int)v;
    }
    return n > 0 ? n : -1;
}
static int parse_name_list(const char *s, const char *const *names, int nnames, int first, int *out, int cap) {
    int n = 0;
    char buf[128];
    snprintf(buf, sizeof(buf), "%s", s);
    for (char *save = NULL, *tok = strtok_r(buf, ",", &save); tok; tok = strtok_r(NULL, ",", &save)) {
        int found = -1;
        for (int i = first; i < nnames; i++) if (!strcmp(tok, names[i])) found = i;
        if (found < 0 || n >= cap) return -1;
        out[n++] = found;
    }
    return n > 0 ? n : -1;
}

static void usage(const char *prog) {
    fprintf(stderr,
      "usage: %s -s server -d dev -i port -g gid -p ctrlport -f fault -o raw.csv -O trials.csv\n"
      "          [-N 1,4,16,64] [-m all,last] [-k first,middle[,last]] [-n trials] [-S wqe_bytes]\n"
      "          [-q quiet_ms] [-t first_err_timeout_ms] [-T trial_uid_base] [-b trial_index_base]\n"
      "          [-R run_id] [-C cpu]\n"
      "faults: local_qp_err rem_access rem_inv_req rnr retry_server_qp_err retry_proc_kill\n"
      "-k applies to rem_access, rem_inv_req and rnr (the other faults have no bad WQE).\n"
      "retry_proc_kill ends the server on GO: exactly one N, one mode and -n 1 per run.\n"
      "exit: 0 ok, 1 failure/incomplete, 2 bad args\n", prog);
}

int main(int argc, char **argv) {
    const char *server = NULL, *dev = "mlx5_1", *raw_path = NULL, *trials_path = NULL;
    const char *fault_s = NULL, *run_id = "manual";
    const char *ns_s = "1,4,16,64", *sigs_s = "all,last", *poss_s = "first,middle";
    int ib_port = 1, gid_index = 3, ctrl_port = PROBE_DEFAULT_PORT, cpu = -1, trials = 5;
    long quiet_ms = 500, first_err_ms = 10000;
    unsigned long uid_base = 0;
    int trial_base = 0;
    size_t wqe_bytes = 4096;
    int opt;
    while ((opt = getopt(argc, argv, "s:d:i:g:p:f:o:O:N:m:k:n:S:q:t:T:b:R:C:h")) != -1) {
        switch (opt) {
            case 's': server = optarg; break;
            case 'd': dev = optarg; break;
            case 'i': ib_port = atoi(optarg); break;
            case 'g': gid_index = atoi(optarg); break;
            case 'p': ctrl_port = atoi(optarg); break;
            case 'f': fault_s = optarg; break;
            case 'o': raw_path = optarg; break;
            case 'O': trials_path = optarg; break;
            case 'N': ns_s = optarg; break;
            case 'm': sigs_s = optarg; break;
            case 'k': poss_s = optarg; break;
            case 'n': trials = atoi(optarg); break;
            case 'S': wqe_bytes = (size_t)strtoull(optarg, NULL, 0); break;
            case 'q': quiet_ms = atol(optarg); break;
            case 't': first_err_ms = atol(optarg); break;
            case 'T': uid_base = strtoul(optarg, NULL, 0); break;
            case 'b': trial_base = atoi(optarg); break;
            case 'R': run_id = optarg; break;
            case 'C': cpu = atoi(optarg); break;
            case 'h': usage(argv[0]); return 0;
            default:  usage(argv[0]); return 2;
        }
    }
    fault_type_t fault;
    if (!server || !fault_s || !raw_path || !trials_path) { usage(argv[0]); return 2; }
    if (fault_from_name(fault_s, &fault) < 0 ||
        !(fault == FAULT_LOCAL_QP_ERR || fault == FAULT_REM_ACCESS || fault == FAULT_REM_INV_REQ ||
          fault == FAULT_RNR || fault == FAULT_RETRY_SERVER_QP_ERR || fault == FAULT_RETRY_PROC_KILL)) {
        fprintf(stderr, "ERROR: unsupported fault '%s'\n", fault_s); usage(argv[0]); return 2;
    }
    int ns[MAX_LIST], sigs[MAX_LIST], poss[MAX_LIST];
    int n_ns = parse_int_list(ns_s, ns, MAX_LIST);
    int n_sigs = parse_name_list(sigs_s, sig_names, 2, 0, sigs, MAX_LIST);
    int n_poss = parse_name_list(poss_s, pos_names, 4, 1, poss, MAX_LIST);
    if (n_ns < 0 || n_sigs < 0 || n_poss < 0) {
        fprintf(stderr, "ERROR: bad -N (1..%d), -m (all,last) or -k (first,middle,last) list\n", MAX_N); return 2;
    }
    const bool has_bad = (fault == FAULT_REM_ACCESS || fault == FAULT_REM_INV_REQ || fault == FAULT_RNR);
    if (!has_bad) { poss[0] = POS_NONE; n_poss = 1; }
    if (trials <= 0 || quiet_ms <= 0 || first_err_ms <= 0) {
        fprintf(stderr, "ERROR: -n, -q and -t must be > 0\n"); return 2;
    }
    if (wqe_bytes < 8 || wqe_bytes > PROBE_BUF_SIZE) {
        fprintf(stderr, "ERROR: -S must be in [8, %u]\n", PROBE_BUF_SIZE); return 2;
    }
    if (strchr(run_id, ',') || strchr(run_id, '"')) { fprintf(stderr, "ERROR: -R must not contain , or \"\n"); return 2; }
    const bool proc_kill = (fault == FAULT_RETRY_PROC_KILL);
    if (proc_kill && (n_ns != 1 || n_sigs != 1 || trials != 1)) {
        fprintf(stderr, "ERROR: retry_proc_kill ends the server each trial: one -N value, one -m value "
                        "and -n 1 per run (the runner restarts the server per trial)\n");
        return 2;
    }
    pin_to_cpu(cpu);
    signal(SIGPIPE, SIG_IGN);   /* a dead peer must not kill us */

    FILE *fraw = open_append(raw_path, RAW_HEADER);
    FILE *ftr = fraw ? open_append(trials_path, TRIAL_HEADER) : NULL;
    if (!fraw || !ftr) { if (fraw) fclose(fraw); return 1; }

    probe_ep_t ep;
    if (ep_open(&ep, dev, (uint8_t)ib_port, gid_index, PROBE_BUF_SIZE) < 0) { fclose(fraw); fclose(ftr); return 1; }
    if (ep_create_qp(&ep) < 0 || ep_to_init(&ep) < 0) { ep_close(&ep); fclose(fraw); fclose(ftr); return 1; }

    int fd = tcp_client_connect(server, ctrl_port);
    if (fd < 0) { ep_close(&ep); fclose(fraw); fclose(ftr); return 1; }
    /* every control-channel receive is bounded */
    struct timeval tv = { CTRL_TIMEOUT_S, 0 };
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));

    char line[512] = "";
    int completed = 0, planned = 0;
    bool failed = false;
    if (ctrl_send_line(fd, "HELLO") < 0 || connect_qp_client(&ep, fd, pick_psn()) < 0 ||
        ctrl_recv_line(fd, line, sizeof(line)) < 0 || strcmp(line, "SYNC") != 0) {
        fprintf(stderr, "[cqe_seq] handshake failed: '%s'\n", line);
        failed = true;
        goto out;
    }
    fprintf(stderr, "[cqe_seq] connected to %s, dev %s gid %d, mtu %d B, fault %s, wqe %zu B, "
                    "quiet %ld ms, first-error timeout %ld ms\n",
            server, dev, gid_index, ep.mtu_bytes, fault_name(fault), wqe_bytes, quiet_ms, first_err_ms);

    uint32_t uid = (uint32_t)uid_base;
    for (int a = 0; a < n_ns && !failed; a++)
    for (int b = 0; b < n_sigs && !failed; b++)
    for (int p = 0; p < n_poss && !failed; p++) {
        cell_t c = { fault, wqe_bytes, ns[a], (sig_mode_t)sigs[b], (pos_t)poss[p], -1 };
        if (c.pos >= POS_MIDDLE && c.n == 1) continue;      /* identical to "first" */
        if (c.pos == POS_FIRST)  c.bad_idx = 0;
        if (c.pos == POS_MIDDLE) c.bad_idx = c.n / 2;
        if (c.pos == POS_LAST)   c.bad_idx = c.n - 1;

        for (int t = 0; t < trials && !failed; t++, uid++) {
            planned++;
/* abort the run: the client exits non-zero, rows already written are kept */
#define TRIAL_FAIL(...) do { fprintf(stderr, "[cqe_seq] N=%d %s %s trial %d FAILED: ", c.n, \
                                     sig_names[c.sig], pos_names[c.pos], t);                   \
                             fprintf(stderr, __VA_ARGS__); fputc('\n', stderr);                 \
                             failed = true; goto next; } while (0)
            snprintf(line, sizeof(line), "TRIAL %s qp_only", fault_name(fault));
            if (ctrl_send_line(fd, line) < 0) TRIAL_FAIL("send TRIAL");
            if (ctrl_recv_line(fd, line, sizeof(line)) < 0) TRIAL_FAIL("no reply to TRIAL");
            if (strcmp(line, "OK") != 0) TRIAL_FAIL("expected OK, got '%s'", line);

            build_batch(&ep, &c, uid);

            if (ctrl_send_line(fd, "GO") < 0) TRIAL_FAIL("send GO");
            if (proc_kill) {
                usleep(300000);   /* server exits on GO; let its QP be torn down (as probe_client) */
            } else {
                if (ctrl_recv_line(fd, line, sizeof(line)) < 0) TRIAL_FAIL("no GOACK");
                if (strcmp(line, "GOACK") != 0) TRIAL_FAIL("expected GOACK, got '%s'", line);
            }

            /* post (+ trigger); t0 = the moment the fault is set in motion */
            struct ibv_send_wr *bad_wr = NULL;
            uint64_t t0, t_post0, t_post1, t_trig1 = 0;
            t_post0 = now_ns();
            int prc = ibv_post_send(ep.qp, &g_wr[0], &bad_wr);
            t_post1 = now_ns();
            if (prc) TRIAL_FAIL("ibv_post_send: %s", strerror(prc));
            if (fault == FAULT_LOCAL_QP_ERR) {
                t0 = now_ns();
                if (ep_to_err(&ep) < 0) TRIAL_FAIL("modify own QP -> ERR");
                t_trig1 = now_ns();
            } else {
                t0 = t_post0;
            }

            int nrec = 0, ndrop = 0;
            drain_end_t dend;
            uint64_t t_end = 0;
            if (drain_cq(&ep, t0, first_err_ms, quiet_ms, uid, c.n, &nrec, &ndrop, &dend, &t_end) < 0)
                TRIAL_FAIL("ibv_poll_cq error");
            enum ibv_qp_state qps = ep_qp_state(&ep);
            /* late sweep: anything that arrived after the quiet period */
            int nlate = 0;
            for (;;) {
                struct ibv_wc wc;
                wc_reset(&wc);
                int got = ibv_poll_cq(ep.cq, 1, &wc);
                if (got <= 0) break;
                record_wc(&wc, uid, c.n, (int64_t)(now_ns() - t0), 1, &nrec, &ndrop);
                nlate++;
            }
            int nforeign = 0;
            for (int i = 0; i < nrec; i++) {
                const cqe_rec_t *r = &g_rec[i];
                nforeign += r->foreign;
                cell_keys(fraw, run_id, &c, trial_base + t, uid);
                fprintf(fraw, "%d,%d,%s,%d,0x%" PRIx64 ",%d,%s,0x%x,%d,%u,0x%x,%" PRId64 ",%d,%d\n",
                        i, r->wqe_idx, r->wqe_idx >= 0 ? kind_names[g_kind[r->wqe_idx]] : "-",
                        r->wqe_idx >= 0 ? (int)g_signaled[r->wqe_idx] : -1, r->wr_id, r->status,
                        ibv_wc_status_str((enum ibv_wc_status)r->status), r->vendor_err, r->opcode,
                        r->byte_len, r->qp_num, r->t_ns, r->late, r->foreign);
            }
            fflush(fraw);

            /* recovery + verify, exactly as the harness does (qp_only); none for proc_kill */
            int verify_ok = -1;
            bool rec_failed = false;
            if (!proc_kill) {
                verify_ok = 0;
                if (ctrl_send_line(fd, "RECOVER qp_only") < 0 || client_bring_up_qp_only(&ep, fd) < 0 ||
                    ctrl_recv_line(fd, line, sizeof(line)) < 0 || strcmp(line, "RECOK") != 0) {
                    rec_failed = true;
                } else {
                    verify_ok = verify_path(&ep, uid);
                }
            }
            cell_keys(ftr, run_id, &c, trial_base + t, uid);
            fprintf(ftr, "%d,%d,%d,%d,%s,%" PRIu64 ",%" PRIu64 ",%" PRId64 ",%s,%d\n",
                    nrec, nlate, nforeign, ndrop, drain_names[dend], t_end - t0, t_post1 - t_post0,
                    fault == FAULT_LOCAL_QP_ERR ? (int64_t)(t_trig1 - t0) : (int64_t)-1,
                    qp_state_name(qps), verify_ok);
            fflush(ftr);

            /* one-line trace: idx:status/vendor_err@t_us for the first CQEs */
            fprintf(stderr, "[N=%d %s %s t%d] %d CQE qp=%s drain=%s verify=%d:", c.n, sig_names[c.sig],
                    pos_names[c.pos], trial_base + t, nrec, qp_state_name(qps), drain_names[dend], verify_ok);
            for (int i = 0; i < nrec && i < 6; i++)
                fprintf(stderr, " %d:%d/0x%x@%.1fus", g_rec[i].wqe_idx, g_rec[i].status, g_rec[i].vendor_err,
                        (double)g_rec[i].t_ns / 1e3);
            if (nrec > 6)
                fprintf(stderr, " ... %d:%d/0x%x@%.1fus", g_rec[nrec - 1].wqe_idx, g_rec[nrec - 1].status,
                        g_rec[nrec - 1].vendor_err, (double)g_rec[nrec - 1].t_ns / 1e3);
            fputc('\n', stderr);

            if (rec_failed) TRIAL_FAIL("recovery (RECOVER qp_only / bring-up / RECOK) failed");
            if (!proc_kill && verify_ok != 1) TRIAL_FAIL("post-recovery verify failed; connection unusable");
            completed++;
        next:;
#undef TRIAL_FAIL
        }
    }

out:
    if (!proc_kill) ctrl_send_line(fd, "BYE");   /* proc_kill: the server already exited */
    close(fd);
    ep_close(&ep);
    fclose(fraw);
    fclose(ftr);
    if (failed || completed < planned) {
        fprintf(stderr, "[cqe_seq] FAILED: %d/%d trials completed\n", completed, planned);
        return 1;
    }
    fprintf(stderr, "[cqe_seq] done: %d/%d trials\n", completed, planned);
    return 0;
}
