/*
 * probe.h - Unified RDMA fault-characterization harness (shared core)
 *
 * One instrument that replaces the scattered experiments 01-10 with a single
 * requester (client) / responder (server) pair speaking one control protocol.
 *
 * What it measures, per fault, per trial, into one CSV schema:
 *   - classification:   ibv_wc_status + vendor_err  -> (cause, recommended action)
 *   - detection latency: t_inject -> t_error_cqe  (CLOCK_MONOTONIC_RAW tight poll)
 *   - recovery latency:  QP-only (ERR->RESET->INIT->RTS, coordinated both ends)
 *                        vs full rebuild (QP destroy+recreate), then a verified round-trip
 *   - data-plane:        partial-write bytes landed, MEASURED by RDMA-READ readback of
 *                        the (pre-zeroed) responder buffer, compared against the
 *                        bytes sent implied by the sq_psn advance (sq_psn_delta * PMTU)
 *   - counters:          hw_counter deltas around the fault (diagnosis / early detect)
 *   - cross-layer state: the responder's QP state after the fault and the async events
 *                        (ibv_get_async_event) of both ends since GO
 *
 * Design rules learned from the old code:
 *   - TCP_NODELAY on BOTH sides of every control socket (kills the 40ms
 *     delayed-ACK artifact that contaminated the old A/B recovery numbers).
 *   - full error checking on every verbs and socket call; clean teardown.
 *   - manual RC QP setup (no rdmacm) for full control of state transitions.
 *   - client device and server device may differ (mlx5_1 vs mlx5_0): every
 *     endpoint takes its own -d/-g/-i; nothing is hardcoded.
 */
#ifndef PROBE_H
#define PROBE_H

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include <infiniband/verbs.h>

#define PROBE_DEFAULT_PORT   18580
#define PROBE_BUF_SIZE       (4u * 1024 * 1024)   /* 4 MiB region, covers partial-write tests */
#define PROBE_MAX_SEND_WR    512
#define PROBE_MAX_RECV_WR    512
#define PROBE_CQ_DEPTH       1024

/* ---- fault catalog (the meaningful RDMA-side faults from exp 01-09) ---- */
typedef enum {
    FAULT_NONE = 0,            /* F0 control: the normal 4 KiB write, no fault; success expected */
    FAULT_LOCAL_QP_ERR,        /* requester forces its own QP->ERR mid-flight -> WR_FLUSH_ERR (cheap detect baseline) */
    FAULT_REM_ACCESS,          /* write outside remote MR / bad rkey -> REM_ACCESS_ERR (10 / 0x88) */
    FAULT_REM_INV_REQ,         /* malformed request -> REM_INV_REQ_ERR (9 / 0x8a) */
    FAULT_RNR,                 /* SEND with no remote recv WQE -> RNR retry exhausted (13 / 0x87) */
    FAULT_RETRY_SERVER_QP_ERR, /* responder QP->ERR, stops ACKing -> RETRY_EXC_ERR (12 / 0x81), firmware floor */
    FAULT_RETRY_PROC_KILL,     /* responder process killed -> RETRY_EXC_ERR */
    FAULT_RETRY_LINK_DOWN,     /* responder RoCE netdev down (passwordless sudo for `ip` on server,
                                  or PROBE_LINK_DRYRUN=1 to exercise the protocol only) -> RETRY_EXC_ERR */
    FAULT_PARTIAL_WRITE,       /* interrupt a multi-packet WRITE mid-transfer; measure bytes landed */
    FAULT_RETRY_PROC_SIGKILL,  /* responder raises SIGKILL on GO: a real crash, no cleanup by the
                                  process (the runner restarts it per trial) -> as retry_proc_kill */
    /* live_peer study (harness/live_peer/EXPERIMENT.md): the responder process stays alive but is not
     * ready. All of them post one 4 KiB write and record the first CQE whatever its status. */
    FAULT_LIVE_QP_RESET,       /* responder QP -> RESET on GO */
    FAULT_LIVE_QP_INIT,        /* responder QP -> RESET -> INIT on GO */
    FAULT_LIVE_QP_RTR,         /* responder QP re-armed RESET -> INIT -> RTR with its saved receive PSN */
    FAULT_LIVE_TRANSIENT,      /* responder QP held in INIT for LIVE_TRANSIENT_MS after GOACK, then
                                  re-armed to RTS with its saved receive PSN */
    FAULT_LIVE_STOP_ERR,       /* responder QP -> ERR, then the process stops itself for LIVE_STOP_MS */
    FAULT_LIVE_STOP_OK,        /* healthy QP, the process stops itself for LIVE_STOP_MS after GOACK */
    FAULT_LIVE_CTL_CLOSE,      /* responder QP -> ERR, then the live process closes only its control
                                  connection and answers ALIVE? on a new one */
    FAULT_LIVE_QP_RECREATE,    /* responder destroys its QP and creates a new one left in INIT */
    /* live_boundary study (harness/live_peer/boundary/EXPERIMENT.md) */
    FAULT_LIVE_STOP_PROBE,     /* responder QP -> ERR on GO; the process stops itself for LIVE_STOP_MS
                                  when it receives the first PROBE (0 = no stop), then answers */
    FAULT__COUNT
} fault_type_t;

typedef enum {
    RECOVER_NONE = 0,
    RECOVER_QP_ONLY,           /* coordinated ERR->RESET->INIT->RTS on both ends, fresh PSNs */
    RECOVER_FULL_REBUILD       /* destroy + recreate the QP only (CQ/MR/PD are kept) + re-handshake */
} recovery_method_t;

const char *fault_name(fault_type_t f);
/* strict parsers: return 0 and set *out on an exact name match, -1 otherwise
 * (unknown names are rejected, never silently mapped to none). */
int fault_from_name(const char *s, fault_type_t *out);
const char *recovery_name(recovery_method_t r);
int recovery_from_name(const char *s, recovery_method_t *out);

/* ---- RC endpoint ---- */
typedef struct {
    struct ibv_context *ctx;
    struct ibv_pd      *pd;
    struct ibv_cq      *cq;
    struct ibv_qp      *qp;
    struct ibv_mr      *mr;
    char               *buf;
    size_t              buf_size;

    char                dev_name[64];
    uint8_t             ib_port;
    int                 gid_index;
    struct ibv_port_attr port_attr;
    union ibv_gid       gid;
    int                 mtu_bytes;   /* active path MTU in bytes (for sq_psn * PMTU math) */
} probe_ep_t;

/* info exchanged over the TCP control channel to wire up the RC QP */
typedef struct {
    uint32_t      qp_num;
    uint32_t      psn;
    uint32_t      rkey;
    uint64_t      addr;
    uint32_t      buf_size;
    union ibv_gid gid;
} probe_dest_t;

/* ---- TCP control channel (always TCP_NODELAY) ---- */
int  tcp_server_listen(int port);            /* returns listening fd */
int  tcp_server_accept(int listen_fd);       /* returns connected fd, TCP_NODELAY set */
int  tcp_client_connect(const char *host, int port); /* returns connected fd, TCP_NODELAY set */
int  tcp_send_all(int fd, const void *buf, size_t len);
int  tcp_recv_all(int fd, void *buf, size_t len);
/* small line protocol for control commands */
int  ctrl_send_line(int fd, const char *line);      /* sends line + '\n' */
int  ctrl_recv_line(int fd, char *buf, size_t cap);  /* reads up to '\n', strips it */

/* ---- RC QP lifecycle ---- */
int  ep_open(probe_ep_t *ep, const char *dev_name, uint8_t ib_port, int gid_index, size_t buf_size);
int  ep_create_qp(probe_ep_t *ep);
int  ep_to_init(probe_ep_t *ep);
int  ep_to_rtr(probe_ep_t *ep, const probe_dest_t *remote);
int  ep_to_rts(probe_ep_t *ep, uint32_t local_psn);
int  ep_to_err(probe_ep_t *ep);
int  ep_to_reset(probe_ep_t *ep);
enum ibv_qp_state ep_qp_state(probe_ep_t *ep);
/* QP state by ibv_query_qp; 0 = ok, -1 = the query failed (ep_qp_state reports that as ERR) */
int  ep_query_qp_state(probe_ep_t *ep, enum ibv_qp_state *out);
const char *qp_state_name(enum ibv_qp_state s);   /* RESET INIT RTR RTS SQD SQE ERR */
void ep_fill_dest(const probe_ep_t *ep, uint32_t psn, probe_dest_t *out);
void ep_destroy_qp(probe_ep_t *ep);   /* destroys QP only (keeps ctx/pd/mr) */
void ep_close(probe_ep_t *ep);        /* full teardown; stops the async monitor of ep->ctx first */

/* ---- work requests ---- */
int  post_write(probe_ep_t *ep, uint64_t wr_id, size_t len,
                uint64_t remote_addr, uint32_t rkey, bool signaled);
int  post_read(probe_ep_t *ep, uint64_t wr_id, size_t len,
               uint64_t remote_addr, uint32_t rkey);
int  post_send(probe_ep_t *ep, uint64_t wr_id, size_t len);
/* fetch-and-add atomic; used to trigger REM_INV_REQ when the responder QP
 * does not enable atomics (operation-not-enabled -> NAK 1 -> 0x8a). */
int  post_atomic_fa(probe_ep_t *ep, uint64_t wr_id, uint64_t remote_addr, uint32_t rkey);
int  post_recv(probe_ep_t *ep, uint64_t wr_id, size_t len);
/* poll one completion, blocking up to timeout_ms (<=0 = spin forever). returns:
 *  1 = got wc, 0 = timeout, -1 = error. wc filled when return==1. */
int  poll_one(probe_ep_t *ep, struct ibv_wc *wc, long timeout_ms);

/* current send-queue PSN of the QP (for partial-write byte accounting) */
int  ep_query_sq_psn(probe_ep_t *ep, uint32_t *sq_psn);
/* next send PSN and next expected receive PSN of the QP (ibv_query_qp SQ_PSN | RQ_PSN) */
int  ep_query_psns(probe_ep_t *ep, uint32_t *sq_psn, uint32_t *rq_psn);
/* RESET -> INIT -> RTR toward `remote` with rq_psn in place of remote->psn, then RTS with sq_psn if
 * to_rts (live_peer: re-arm a responder QP without the requester noticing a PSN change) */
int  ep_rearm(probe_ep_t *ep, const probe_dest_t *remote, uint32_t rq_psn, uint32_t sq_psn, bool to_rts);

/* ---- timing ---- */
uint64_t now_ns(void);      /* CLOCK_MONOTONIC_RAW nanoseconds */
uint64_t mono_ns(void);     /* CLOCK_MONOTONIC nanoseconds (async events; the clock evrec uses) */
void     pin_to_cpu(int cpu); /* sched_setaffinity if cpu >= 0; no-op otherwise */

/* ---- async events of the device context (ibv_get_async_event) ----
 * One monitor per process. async_mon_start() starts a thread that takes every async
 * event delivered to ctx, acks it, keeps it for async_mon_format(), and logs it to
 * stderr as
 *   [<tag>] async event <IBV_EVENT_*> <qpn=0x..|port=N|wqn=0x..|cq|srq|-> mono_ns=<CLOCK_MONOTONIC ns>
 * The thread blocks every signal, so signals are still handled by the main thread.
 * It only reads events: it posts, polls and modifies nothing. ep_close() stops it
 * before the device is closed. Returns 0 on success. */
#define PROBE_ASYNC_FMT_MAX 400
int  async_mon_start(struct ibv_context *ctx, const char *tag);
void async_mon_stop(void);
/* The events recorded at or after since_mono_ns, oldest first, as
 *   <IBV_EVENT_*>/<element>/dt_ns=<ns after since_mono_ns>
 * joined by ';' (no commas or blanks, so it fits a CSV field and a control line).
 * "none" if there is none, "?" if the monitor never ran. If cap is too small the
 * list ends with ";+N_more". */
void async_mon_format(uint64_t since_mono_ns, char *out, size_t cap);
const char *async_event_name(enum ibv_event_type t);

/* ---- hardware counters (sysfs .../ports/N/hw_counters/<name>) ---- */
uint64_t counter_read(const char *dev_name, uint8_t ib_port, const char *counter);
/* netdev traffic counter (/sys/class/net/<iface>/statistics/<stat>), e.g. rx_packets.
 * This is the "ethtool traffic" signal used to tell a live-but-broken peer (its NIC
 * still receives our retransmits) from a dead one. UINT64_MAX if unavailable. */
uint64_t netdev_counter(const char *iface, const char *stat);
/* IB/RoCE port counter (/sys/class/infiniband/<dev>/ports/<port>/counters/<name>),
 * e.g. port_rcv_packets. Unlike netdev rx_packets, this counts RoCE traffic (which
 * bypasses the kernel net stack). UINT64_MAX if unavailable. */
uint64_t port_counter_read(const char *dev_name, uint8_t ib_port, const char *name);
enum ibv_port_state ep_port_state(probe_ep_t *ep);

/* ---- classification: the paper's core contribution as one function ---- */
typedef struct {
    const char *status_name;   /* ibv_wc_status string */
    const char *cause;         /* human cause */
    const char *action;        /* recommended recovery action */
    bool        peer_alive;    /* is the remote peer believed reachable? */
    bool        auto_recoverable; /* software auto-recovery vs human intervention */
} classify_t;
classify_t classify(enum ibv_wc_status status, uint32_t vendor_err);

#endif /* PROBE_H */
