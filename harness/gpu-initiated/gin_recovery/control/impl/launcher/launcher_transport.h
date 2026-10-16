/* launcher_transport.h - the launcher's thin RNIC transport (gin-control, EXPERIMENT.md 9.5).
 *
 * The launcher's state machine (gin_launcher.c) never touches verbs. It talks to the RNIC through this table:
 *   - one UD QP with the launcher's own Q_Key (pairing: PAIR in, PAIR_ACK out),
 *   - one RC QP per paired rank (every other launcher message; RDMA READ of a buddy's outbox for the activation blob),
 *   - one REMOTE_READ region, the launcher's state page.
 * The transport adds and strips the 64 B control envelope (struct glCtrlEnv) and keeps the per-QP sequence numbers and
 * credit; the core sees whole struct glMsg values only.
 *
 * Implementations: launcher_transport_verbs.c (libibverbs; built, not executed in this repository's tests) and the
 * in-process test transport of launcher_unit.cc.
 */
#ifndef GIN_LAUNCHER_TRANSPORT_H
#define GIN_LAUNCHER_TRANSPORT_H

#include <stddef.h>
#include <stdint.h>

#include "launcher_msg.h"

#ifdef __cplusplus
extern "C" {
#endif

enum glTpEventType {
  GL_TP_UD_RECV = 1,    /* a launcher message arrived on the UD QP (msg) */
  GL_TP_RC_RECV = 2,    /* a launcher message arrived on peer's RC QP (peer, msg) */
  GL_TP_READ_DONE = 3,  /* an RDMA READ finished (peer, cookie, status: 0 ok) */
  GL_TP_RC_ERROR = 4,   /* peer's RC QP failed (a send or READ completion with an error, an async event, or a gap
                           in the sequence numbers) */
  GL_TP_FATAL = 5       /* the transport itself failed (its CQ: every QP is gone): the launcher stops (status) */
};

/* A handle names one QP for its life: a closed QP's handle is never given to another QP (REVIEW_PREP fix 11), so an event
 * of a closed QP that was already queued can never be taken for a newer QP's. rc_close also drops its queued events. */
struct glTpEvent {
  int type;
  int peer;             /* RC handle (GL_TP_RC_*, GL_TP_READ_DONE), else -1 */
  int status;           /* 0 ok, else an error code of the transport */
  uint64_t cookie;      /* GL_TP_READ_DONE: the cookie given to rc_read */
  struct glMsg msg;     /* GL_TP_*_RECV */
};

struct glTransport;
struct glTransportOps {
  /* Fill up to `max` fds the core must poll for POLLIN (a completion channel, ...); returns the count. */
  int (*fds)(struct glTransport* tp, int* fds, int max);
  /* Drain up to `max` events without blocking; returns the count (0: none). */
  int (*poll)(struct glTransport* tp, struct glTpEvent* ev, int max);
  /* The launcher's UD endpoint (qpn, gid, ...). */
  int (*local_ud)(struct glTransport* tp, struct glEp* ud);
  /* Register the state page (REMOTE_READ); fills its region (addr, rkey, len). */
  int (*page_register)(struct glTransport* tp, void* page, size_t len, struct glRegion* out);
  /* Send one launcher message on the UD QP to `to` (the rank's UD QP) with the rank's Q_Key. 0 ok. The verbs transport
   * keeps one address handle per destination (GID, LID) with the GIN QPs' traffic class (REVIEW_PREP fix 13). */
  int (*ud_send)(struct glTransport* tp, const struct glEp* to, uint32_t qkey, const struct glMsg* m);
  /* Create an RC QP for one rank: kind GL_PAIR_RECORD (SEND/RECV of launcher messages; RECVs posted before it leaves
   * INIT) or GL_PAIR_PROBE (passive: the rank READs the launcher page on it; REMOTE_READ only, no RQ). A new QP every
   * time, with a fresh random PSN in `local`. gen and nonce go into every envelope sent on it. Returns the handle (>= 0)
   * or -1. */
  int (*rc_create)(struct glTransport* tp, int kind, uint32_t gen, uint64_t nonce, struct glEp* local);
  /* Connect handle's QP to `remote` (RTR, RTS). 0 ok. */
  int (*rc_connect)(struct glTransport* tp, int handle, const struct glEp* remote);
  /* Send one launcher message on peer's RC QP. 0 ok (queued or posted), -1 failed (the QP is gone or in error). */
  int (*rc_send)(struct glTransport* tp, int peer, const struct glMsg* m);
  /* Start an RDMA READ of `len` bytes at (addr, rkey) of peer into dst; completion is a GL_TP_READ_DONE event. */
  int (*rc_read)(struct glTransport* tp, int peer, uint64_t addr, uint32_t rkey, uint32_t len, void* dst,
                 uint64_t cookie);
  /* Set where the rank keeps its consumed count of this launcher's messages (its page + creditOff, from the PAIR):
   * the transport may READ that word when its send window is shut (design v2 2.2 path 3). */
  void (*rc_credit_at)(struct glTransport* tp, int peer, const struct glRegion* page, uint32_t creditOff);
  /* Destroy peer's RC QP: no event of it follows (queued ones are dropped), no DMA into a READ's buffer after it. */
  void (*rc_close)(struct glTransport* tp, int peer);
  /* Destroy the transport. */
  void (*close)(struct glTransport* tp);
};

struct glTransport {
  const struct glTransportOps* ops;
  void* impl;
};

/* The verbs transport (launcher_transport_verbs.c). dev: an IB device name (e.g. mlx5_1), port: 1-based, gidIndex: the
 * GID index of the GIN QPs, trafficClass: theirs (NCCL_IB_TC; design v3 2.5), qkey: the launcher's own Q_Key, node: for
 * the envelope's `from`. Returns NULL on failure
 * (the reason on stderr). Not built when GL_NO_VERBS is defined. */
struct glTransport* gl_transport_verbs_open(const char* dev, int port, int gidIndex, int trafficClass, uint32_t qkey,
                                            uint32_t node);

#ifdef __cplusplus
}
#endif

#endif /* GIN_LAUNCHER_TRANSPORT_H */
