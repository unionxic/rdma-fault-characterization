/* launcher_msg.h - the wire of the per-node launcher (gin-control, EXPERIMENT.md 9.5; design v2 2.3, 2.5, 5.2, 5.4).
 *
 * Self-contained C/C++ header: plain structs, fixed-width types, no NCCL, no verbs. Included by
 * control/impl/rs_ctrl_api.h as "launcher/launcher_msg.h" (the rank side) and by gin_launcher.c (the launcher).
 *
 * Two wires:
 *   1. the node-local Unix socket (SOCK_SEQPACKET, one message per datagram, SCM_RIGHTS for the pidfd): struct
 *      glUnixMsg, 256 B, kinds GL_U_* (the seven rows of EXPERIMENT.md 9.5's table and the nonce-free INFO and its
 *      answer, impl/notes_p3.md "고침"); only GL_U_ACT_BYTES carries
 *      a payload after its 256 B (the activation blob, at most GL_U_MAX_PAYLOAD bytes);
 *   2. the RNIC side (the launcher's UD QP for pairing, one RC QP per rank for everything else): struct glMsg, 256 B
 *      (design v2 2.3: "the launcher's message is a fixed 256 B structure"), kinds GL_K_*. On the wire every UD
 *      datagram and every RC SEND starts with the 64 B control envelope (struct glCtrlEnv, the same bytes as design
 *      v2 2.3's gdakiCtrlEnv), then the 256 B glMsg: 320 B, far under the UD limit of path MTU >= 2048.
 *
 * Choices this header makes where the design leaves a size or value open (the rank side must match them):
 *   - glMsg = 64 B head + 192 B body; glUnixMsg = 64 B head + 192 B body.
 *   - envelope kinds: GL_ENV_KIND_LAUNCHER 4 (RC), GL_ENV_KIND_PAIR 5 (UD); RECORD 1, XFER 2, XFER_DONE 3 and the
 *     rank-rank CONNECTED 6 are the record path's (owned by rs_ctrl_api.h; this header follows its numbers).
 *   - envelope `from` of a launcher: GL_FROM_LAUNCHER | node (design v2 2.3).
 *   - the launcher's Q_Key: its own 31-bit value (design v2 2.5 last line), handed out in GL_U_HELLO_ACK.
 *   - GL_U_MAX_PAYLOAD 65536: the activation blob (gdakiMiActHdr + 40 B x nranks + 40 B x nExt <= 256) fits up to
 *     about 1 370 ranks.
 *   - the relayed activation-talk payloads are opaque here; their sizes are fixed below (GL_ACT_RECORD_BYTES etc.) so
 *     rs_ctrl_api.h can static_assert them against gdakiRsActivate, gdakiMiActAnswer, gdakiMiActReady, gdakiMiActDone.
 */
#ifndef GIN_LAUNCHER_MSG_H
#define GIN_LAUNCHER_MSG_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
#define GL_STATIC_ASSERT(c, m) static_assert(c, m)
#else
#define GL_STATIC_ASSERT(c, m) _Static_assert(c, m)
#endif

#define GL_WIRE_VERSION 1u

/* ---------------------------------------------------------------------------------------------------------------
 * Shared pieces
 * ------------------------------------------------------------------------------------------------------------- */

/* A QP endpoint: the same 40 bytes as rs_ctrl_api.h's gdakiCtrlEndpoint (version 2 of gin-mirror's gdakiMiQpEndpoint,
 * whose last 4 B were pad 0). RC: psn = the initial send PSN (fresh for every QP); UD: psn = the Q_Key. */
#define GL_EP_VERSION 2u
#define GL_QPT_RC 2u /* IBV_QPT_RC */
#define GL_QPT_UD 4u /* IBV_QPT_UD */
struct glEp {
  uint32_t qpn, psn;
  uint32_t lid;
  int32_t mtu;       /* enum ibv_mtu */
  uint8_t gid[16];   /* RoCE/IB GID */
  int32_t gidIndex;
  uint8_t version;   /* GL_EP_VERSION */
  uint8_t qpType;    /* GL_QPT_RC or GL_QPT_UD */
  uint16_t rsv;
};
GL_STATIC_ASSERT(sizeof(struct glEp) == 40, "a QP endpoint is 40 bytes (gdakiMiQpEndpoint)");

/* A remote-readable region (the launcher's state page, a rank's outbox half). */
struct glRegion {
  uint64_t addr;
  uint32_t rkey; /* host order */
  uint32_t len;
};
GL_STATIC_ASSERT(sizeof(struct glRegion) == 16, "a region is 16 bytes");

/* The activation record: the same 64 bytes as struct gdakiRsActivate (gin_host_gdaki.cc ln4 8889), kinds as its enum
 * (4583). The launcher reads and writes only magic, version, kind, rank, incarnation, nonce, step; it answers with the
 * buddy's record echoed (rank, incarnation, nonce, step) and kind LATER or REFUSED when it answers itself. */
#define GL_RS_ACT_MAGIC 0x41535247u /* "GRSA" */
enum { GL_RS_ACT_ACTIVATE = 1, GL_RS_ACT_ABANDON = 2, GL_RS_ACT_ACCEPTED = 3, GL_RS_ACT_REFUSED = 4, GL_RS_ACT_LATER = 5 };
struct glRsActivate {
  uint32_t magic, version;
  uint32_t kind, pad;
  int32_t rank;
  uint32_t incarnation; /* the new incarnation (dead + 1) */
  uint64_t nonce;
  uint64_t step;
  int64_t pid;          /* unused on the launcher path (the launcher holds the pidfd); 0 */
  uint64_t pidStart;    /* unused on the launcher path; 0 */
  uint64_t reserved;
};
GL_STATIC_ASSERT(sizeof(struct glRsActivate) == 64, "the activation record is 64 bytes (gdakiRsActivate)");

/* Opaque relayed payloads of the activation talk (the bytes of today's TCP activation connection). */
#define GL_ACT_RECORD_BYTES 64u   /* gdakiRsActivate */
#define GL_FETCH_EP_BYTES 112u    /* gdakiMiActAnswer: magic, ok, gdakiMiQpEndpoint, why[64] */
#define GL_FETCH_READY_BYTES 72u  /* gdakiMiActReady: magic, kind, why[64] */
#define GL_FETCH_DONE_BYTES 80u   /* gdakiMiActDone: magic, ok, bytes, why[64] */

/* Reason codes (glMsg.reason, glUnixMsg.h.reason). The text of each is gl_reason_text below. */
enum glReason {
  GL_R_NONE = 0,
  GL_R_SPAWN_NOT_BUILT = 1,     /* SPAWN: this experiment's launcher does not spawn ("spawn not built") */
  GL_R_NO_SPARE = 2,            /* ACTIVATE: no pre-launched spare said HELLO for (rank, incarnation) */
  GL_R_SPARE_REPLAYING = 3,     /* LATER: the spare said HELLO, not READY yet */
  GL_R_SPARE_EXITED = 4,        /* the spare's pidfd became readable */
  GL_R_REPLAY_FAILED = 5,       /* the spare reported a replay failure */
  GL_R_SPARE_REFUSED = 6,       /* the spare answered REFUSED (its record is relayed) */
  GL_R_NOT_REGISTERED = 7,      /* no registration of (nonce, rank) here */
  GL_R_NONCE = 8,               /* nonce differs from the registration or the asker's pairing */
  GL_R_INCARNATION = 9,         /* incarnation is not the registered one (+1 for an activation) */
  GL_R_ALREADY_OFFERED = 10,    /* a second ACTIVATE for the same (rank, incarnation) */
  GL_R_ORIGINAL_ALIVE = 11,     /* ACTIVATE while the registered original's pidfd is not readable (guard) */
  GL_R_DUPLICATE = 12,          /* a second connection with the same (rank, incarnation) */
  GL_R_STALE = 13,              /* an incarnation older than (or equal to) one already seen */
  GL_R_UID = 14,                /* SO_PEERCRED uid differs from the launcher's */
  GL_R_BAD_FD = 15,             /* no fd, not a pidfd, or more than one fd */
  GL_R_BAD_MSG = 16,            /* magic, version, kind or size wrong */
  GL_R_OLDER_ALIVE = 17,        /* re-registration while the older incarnation's process is alive */
  GL_R_NOT_HELD = 18,           /* FENCE: no pidfd of (rank, incarnation) held, nothing signalled */
  GL_R_ALREADY_EXITED = 19,     /* FENCED: the process had exited before the FENCE */
  GL_R_FENCE_KILLED = 20,       /* FENCED: the launcher sent SIGKILL through the pidfd and saw the group end */
  GL_R_ALREADY_LEFT = 21,       /* FENCED: the process had left (LEAVING then exit) */
  GL_R_SPARE_NOT_ACTIVATED = 22,/* re-registration of a spare's incarnation before its activation was accepted */
  GL_R_PID_MISMATCH = 23,       /* the pidfd's process is not the connection's peer */
  GL_R_ABORTED = 24,            /* the buddy aborted the activation (hold deadline) or its launcher QP failed */
  GL_R_SEND_FAILED = 25,        /* the launcher could not hand the bytes to the spare */
  GL_R_BLOB_READ_FAILED = 26,   /* the RDMA READ of the buddy's outbox failed */
  GL_R_BLOB_TOO_BIG = 27,       /* the blob exceeds GL_U_MAX_PAYLOAD */
  GL_R_TABLE_FULL = 28,         /* no free slot */
  GL_R_SELF_EXIT = 29,          /* EXITED: the group ended without a FENCE or LEAVING */
  GL_R_PAIR_STALE = 30,         /* PAIR of an older generation or incarnation than the paired one */
  GL_R_UNKNOWN_KIND = 31,
  GL_R_COUNT
};

static inline const char* gl_reason_text(uint32_t r) {
  switch (r) {
    case GL_R_NONE: return "none";
    case GL_R_SPAWN_NOT_BUILT: return "spawn not built";
    case GL_R_NO_SPARE: return "no pre-launched spare for this rank and incarnation";
    case GL_R_SPARE_REPLAYING: return "the spare is replaying";
    case GL_R_SPARE_EXITED: return "the spare exited";
    case GL_R_REPLAY_FAILED: return "the spare's replay failed";
    case GL_R_SPARE_REFUSED: return "the spare refused";
    case GL_R_NOT_REGISTERED: return "not registered here";
    case GL_R_NONCE: return "nonce mismatch";
    case GL_R_INCARNATION: return "incarnation mismatch";
    case GL_R_ALREADY_OFFERED: return "already offered";
    case GL_R_ORIGINAL_ALIVE: return "the original process is still alive";
    case GL_R_DUPLICATE: return "second connection with the same rank and incarnation";
    case GL_R_STALE: return "stale incarnation";
    case GL_R_UID: return "peer uid differs";
    case GL_R_BAD_FD: return "no pidfd";
    case GL_R_BAD_MSG: return "malformed message";
    case GL_R_OLDER_ALIVE: return "the older incarnation is still alive";
    case GL_R_NOT_HELD: return "no pidfd held for this rank and incarnation";
    case GL_R_ALREADY_EXITED: return "already exited";
    case GL_R_FENCE_KILLED: return "killed through the pidfd";
    case GL_R_ALREADY_LEFT: return "already left";
    case GL_R_SPARE_NOT_ACTIVATED: return "the spare's activation was not accepted";
    case GL_R_PID_MISMATCH: return "the pidfd is not the peer's process";
    case GL_R_ABORTED: return "aborted";
    case GL_R_SEND_FAILED: return "could not hand over to the spare";
    case GL_R_BLOB_READ_FAILED: return "reading the activation blob failed";
    case GL_R_BLOB_TOO_BIG: return "activation blob too large";
    case GL_R_TABLE_FULL: return "table full";
    case GL_R_SELF_EXIT: return "exited";
    case GL_R_PAIR_STALE: return "stale pairing";
    case GL_R_UNKNOWN_KIND: return "unknown kind";
    default: return "?";
  }
}

/* ---------------------------------------------------------------------------------------------------------------
 * 1. The node-local Unix socket (EXPERIMENT.md 9.5's table: seven rows, plus INFO and INFO_ACK = nine kinds)
 * ------------------------------------------------------------------------------------------------------------- */

#define GL_U_MAGIC 0x554c5247u /* "GRLU" */
#define GL_U_MAX_PAYLOAD 65536u
/* Socket path: the launcher's --sock argument, else this variable; the rank side reads the same variable. The path's
 * directory must be the user's own with mode 0700 (the launcher creates it so and refuses anything else). */
#define GL_SOCK_ENV "NCCL_GIN_CTRL_LAUNCHER_SOCK"
#define GL_NODE_ENV "NCCL_GIN_CTRL_LAUNCHER_NODE"

enum glUnixKind {
  GL_U_REGISTER = 1,     /* rank -> launcher: (rank, incarnation, nonce) + its own pidfd (SCM_RIGHTS); uid by SO_PEERCRED */
  GL_U_HELLO_ACK = 2,    /* launcher -> rank or spare: the answer to REGISTER and SPARE_HELLO (body glUHelloAck) */
  GL_U_LEAVING = 3,      /* rank -> launcher: (rank, incarnation), before BYE, when the communicator is destroyed */
  GL_U_SPARE_HELLO = 4,  /* spare -> launcher: (rank, new incarnation, nonce) + its own pidfd; second (rank, inc) refused */
  GL_U_SPARE_STATUS = 5, /* spare -> launcher: sub GL_US_READY (replay, FETCH buffer join, Resume entry done) or
                            GL_US_REPLAY_FAILED (body: why) */
  GL_U_ACT_BYTES = 6,    /* launcher -> spare: body = the 64 B activation record, payload = the activation blob */
  GL_U_ACT_TALK = 7,     /* spare <-> launcher: sub GL_UT_* (answer, FETCH QP endpoint, READY, DONE, ABORT) */
  GL_U_INFO = 8,         /* rank -> launcher, before the all-gather (impl/notes_p3.md "고침"): head only (bodyBytes 0, no
                            payload, no fd), nonce 0, incarnation 0, rank = the sender. Nonce-free: no registration entry,
                            no page slot, no count of REGISTER's; any connection, before, without or after a REGISTER */
  GL_U_INFO_ACK = 9      /* launcher -> rank, the same connection: head echoes INFO's rank, incarnation and nonce, sub =
                            GL_U_INFO, reason; body glUHelloAck (GL_UA_OK: node, qkey, pageSlot 0xffffffff, ud, page,
                            why "ok"; GL_UA_REFUSED: reason GL_R_UID, GL_R_BAD_FD (an fd came with it) or GL_R_BAD_MSG) */
};
/* Layout note: kinds 8 and 9 were added after 897641f3 (GL_U_KIND_MAX 7 -> 9). No size, field or GL_WIRE_VERSION
 * change: every Unix message stays 256 B and glUHelloAck 136 B; a launcher of 897641f3 drops INFO as an unknown kind. */
#define GL_U_KIND_MAX 9
GL_STATIC_ASSERT(GL_U_KIND_MAX == GL_U_INFO_ACK, "GL_U_KIND_MAX is the last Unix kind");

enum { GL_US_READY = 1, GL_US_REPLAY_FAILED = 2 };
enum {
  GL_UT_ANSWER = 1,      /* spare -> launcher: 64 B gdakiRsActivate (ACCEPTED, LATER or REFUSED) */
  GL_UT_FETCH_EP = 2,    /* spare -> launcher: 112 B gdakiMiActAnswer (its FETCH QP endpoint) */
  GL_UT_FETCH_READY = 3, /* launcher -> spare: 72 B gdakiMiActReady (from the buddy) */
  GL_UT_FETCH_DONE = 4,  /* spare -> launcher: 80 B gdakiMiActDone */
  GL_UT_ABORT = 5        /* launcher -> spare: the buddy gave up (hold deadline, its launcher QP failed); no body */
};
enum { GL_UA_OK = 0, GL_UA_REFUSED = 1 }; /* glUHelloAck.status */

struct glUnixHdr {
  uint32_t magic;        /* GL_U_MAGIC */
  uint16_t version;      /* GL_WIRE_VERSION */
  uint16_t kind;         /* GL_U_* */
  int32_t rank;
  uint32_t incarnation;
  uint64_t nonce;
  uint32_t sub;          /* GL_US_*, GL_UT_*, or 0 */
  uint32_t reason;       /* GL_R_* */
  uint32_t payloadBytes; /* bytes after the 256 B message (GL_U_ACT_BYTES only) */
  uint16_t bodyBytes;    /* used bytes of body[] */
  uint16_t flags;
  int64_t pid;           /* the sender's getpid(), for the log only (identity is SO_PEERCRED and the pidfd) */
  uint64_t monoNs;       /* the sender's CLOCK_MONOTONIC */
  uint64_t rsv;
};
GL_STATIC_ASSERT(sizeof(struct glUnixHdr) == 64, "the Unix message head is 64 bytes");

#define GL_U_BODY_BYTES 192u
struct glUnixMsg {
  struct glUnixHdr h;
  uint8_t body[GL_U_BODY_BYTES];
};
GL_STATIC_ASSERT(sizeof(struct glUnixMsg) == 256, "a Unix-socket message is 256 bytes");

/* GL_U_HELLO_ACK's and GL_U_INFO_ACK's body: the launcher's node number, UD endpoint and Q_Key (EXPERIMENT.md 9.5 row
 * 2), its state page, and which page registration slot is (rank)'s (INFO_ACK: always 0xffffffff, no slot is bound). */
struct glUHelloAck {
  uint32_t status;       /* GL_UA_* (reason in the head) */
  uint32_t node;
  uint32_t qkey;         /* the launcher UD QP's own Q_Key */
  uint32_t pageSlot;     /* the index of (rank)'s glPageReg on the launcher page (0xffffffff: none) */
  struct glEp ud;        /* the launcher's UD QP (qpn; psn unused) */
  struct glRegion page;  /* the launcher's state page (REMOTE_READ) */
  char why[64];
};
GL_STATIC_ASSERT(sizeof(struct glUHelloAck) == 136, "glUHelloAck is 136 bytes");
GL_STATIC_ASSERT(sizeof(struct glUHelloAck) <= GL_U_BODY_BYTES, "glUHelloAck fits a Unix body");
GL_STATIC_ASSERT(GL_ACT_RECORD_BYTES <= GL_U_BODY_BYTES && GL_FETCH_EP_BYTES <= GL_U_BODY_BYTES &&
                     GL_FETCH_READY_BYTES <= GL_U_BODY_BYTES && GL_FETCH_DONE_BYTES <= GL_U_BODY_BYTES,
                 "every relayed activation-talk payload fits a Unix body");

/* ---------------------------------------------------------------------------------------------------------------
 * 2. The RNIC side: control envelope + 256 B launcher message
 * ------------------------------------------------------------------------------------------------------------- */

#define GL_ENV_MAGIC 0x45435247u /* "GRCE" (design v2 2.3) */
/* GL_ENV_KIND_CONNECTED 6: rs_ctrl_api.h's bodiless first RC SEND of a rank-rank record QP (design v3 2.5 step 3); never
 * to or from a launcher (gl_env_check refuses it: a launcher's CONNECTED is GL_K_CONNECTED inside a LAUNCHER message). */
enum { GL_ENV_KIND_RECORD = 1, GL_ENV_KIND_XFER = 2, GL_ENV_KIND_XFER_DONE = 3, GL_ENV_KIND_LAUNCHER = 4,
       GL_ENV_KIND_PAIR = 5, GL_ENV_KIND_CONNECTED = 6 };
#define GL_FROM_LAUNCHER 0x40000000 /* envelope `from` of a launcher: GL_FROM_LAUNCHER | node */

/* The 64 B control envelope, the same field order as design v2 2.3's gdakiCtrlEnv (rs_ctrl_api.h should static_assert
 * the offsets equal). Design v2 lists magic .. bodyBytes plus rsv[8], which sums to 56 B against its stated 64 B; this
 * header keeps the stated 64 B by rsv[16] (offsets of every named field unchanged). For the launcher's own traffic:
 * gen = the pairing's generation, seq from 1 per (QP, direction, gen), ackSeq = how many of the other side's messages
 * this side consumed (credit), bodyBytes = 256. */
struct glCtrlEnv {
  uint32_t magic;
  uint16_t version, kind;
  int32_t from;
  uint32_t gen;
  uint64_t seq;
  uint64_t ackSeq;
  uint64_t nonce;
  uint32_t incarnation;
  uint32_t bodyBytes;
  uint8_t rsv[16];
};
GL_STATIC_ASSERT(sizeof(struct glCtrlEnv) == 64, "the control envelope is 64 bytes");
GL_STATIC_ASSERT(offsetof(struct glCtrlEnv, from) == 8 && offsetof(struct glCtrlEnv, gen) == 12 &&
                     offsetof(struct glCtrlEnv, seq) == 16 && offsetof(struct glCtrlEnv, ackSeq) == 24 &&
                     offsetof(struct glCtrlEnv, nonce) == 32 && offsetof(struct glCtrlEnv, incarnation) == 40 &&
                     offsetof(struct glCtrlEnv, bodyBytes) == 44,
                 "envelope offsets as design v2 2.3");

#define GL_MAGIC 0x414c5247u /* "GRLA" */
enum glKind {
  GL_K_PAIR = 1,        /* UD, either side may start (REVIEW2 block 4): sub = GL_PAIR_RECORD or GL_PAIR_PROBE, body
                           glPairBody (subject rank, its incarnation, nonce in the head; the QP carries a fresh PSN) */
  GL_K_PAIR_ACK = 2,    /* UD answer: same sub, body glPairAckBody; the same PAIR again gets the same answer */
  GL_K_CONNECTED = 3,   /* RC, the record QP's first message, from the side that started the pairing; the other side
                           sends nothing on that QP before it (design v2 2.5 step 3) */
  GL_K_REG_NOTE = 4,    /* launcher -> ranks: the registration word and the spare word of (rank) (glRegNoteBody); on
                           every change and to a newly connected rank (the same words are on the launcher page) */
  GL_K_EXITED = 5,      /* launcher -> every rank of that nonce: (rank, incarnation, nonce) of the head ended, no FENCE
                           and no LEAVING before; never for a spare that was not accepted as the rank */
  GL_K_LEFT = 6,        /* the same after a LEAVING notice */
  GL_K_FENCED = 8,      /* the same when a FENCE had come (one event, one message: it replaces EXITED and LEFT), and the
                           answer to a FENCE of something already ended; never switched off (NO_EXIT_REPORT stops EXITED
                           only) */
  GL_K_FENCE = 7,       /* buddy -> launcher: end (rank, inc) and confirm */
  GL_K_FENCE_NAK = 9,   /* launcher -> the asker: nothing held for (rank, inc); nothing was signalled */
  GL_K_ACTIVATE = 10,   /* buddy -> launcher: body glActivateBody (the 64 B record + where the blob is) */
  GL_K_ACT_ANSWER = 11, /* launcher -> buddy: body glActAnswerBody; sub = GL_RS_ACT_LATER (at most once per activation),
                           GL_RS_ACT_ACCEPTED or GL_RS_ACT_REFUSED (final) */
  GL_K_FETCH_EP = 12,   /* launcher -> buddy: the spare's gdakiMiActAnswer (GL_FETCH_EP_BYTES) */
  GL_K_FETCH_READY = 13,/* buddy -> launcher: gdakiMiActReady for the spare (GL_FETCH_READY_BYTES) */
  GL_K_FETCH_DONE = 14, /* launcher -> buddy: the spare's gdakiMiActDone (GL_FETCH_DONE_BYTES) */
  GL_K_ABORT = 15,      /* buddy -> launcher: the activation of (rank, inc) is given up (hold deadline, its own bound) */
  GL_K_SPAWN = 16,      /* buddy -> launcher: spawn a spare for (rank, inc) (decision 12; kind only in gin-control) */
  GL_K_REFUSED = 17     /* launcher -> the asker: sub = the refused kind (GL_K_SPAWN: reason GL_R_SPAWN_NOT_BUILT). Not an
                           activation answer: the buddy never falls back on it (REVIEW2 fix 1) */
};
#define GL_K_KIND_MAX 17
enum { GL_PAIR_RECORD = 1, GL_PAIR_PROBE = 2 }; /* glMsgHdr.sub of PAIR and PAIR_ACK */

struct glMsgHdr {
  uint32_t magic;       /* GL_MAGIC */
  uint16_t version;     /* GL_WIRE_VERSION */
  uint16_t kind;        /* GL_K_* */
  int32_t rank;         /* the subject rank (the process the message is about) */
  uint32_t incarnation; /* the subject incarnation */
  uint64_t nonce;       /* the communicator nonce */
  int32_t from;         /* sender: a rank, or GL_FROM_LAUNCHER | node */
  uint32_t node;        /* the launcher's node number (sender or addressee) */
  uint32_t seq;         /* the sender's message number (from 1; per sender, for matching answers) */
  uint32_t reqSeq;      /* the request this answers (its seq), else 0 */
  uint32_t sub;         /* kind-specific (answer kind, refused kind, pairing kind) */
  uint32_t reason;      /* GL_R_* */
  uint16_t bodyBytes;   /* used bytes of body[] */
  uint16_t flags;
  uint32_t rsv;
  uint64_t monoNs;      /* the sender's CLOCK_MONOTONIC */
};
GL_STATIC_ASSERT(sizeof(struct glMsgHdr) == 64, "the launcher message head is 64 bytes");

#define GL_BODY_BYTES 192u
struct glMsg {
  struct glMsgHdr h;
  uint8_t body[GL_BODY_BYTES];
};
GL_STATIC_ASSERT(sizeof(struct glMsg) == 256, "the launcher message is 256 bytes (EXPERIMENT.md 9.1, 9.8)");
#define GL_WIRE_BYTES (sizeof(struct glCtrlEnv) + sizeof(struct glMsg)) /* 320 B per SEND or datagram */
GL_STATIC_ASSERT(sizeof(struct glCtrlEnv) + sizeof(struct glMsg) == 320, "envelope + message = 320 bytes");

/* GL_K_PAIR. The record QP (sub GL_PAIR_RECORD) carries the launcher messages; the liveness-READ QP (sub GL_PAIR_PROBE)
 * only lets the rank READ the launcher page (the launcher never posts on it). The two pair and re-pair apart: an error of
 * one does not touch the other. Every PAIR carries a QP created for it (never a RESET one): a fresh random PSN. The rank
 * may start (setup, its QP in error), and so may the launcher (its record QP in error: gen + 1 to the rank's last UD
 * endpoint and Q_Key, every 500 ms within GL_REPAIR_MS). When both start the same generation, the rank's PAIR wins
 * (the lower `from`). */
struct glPairBody {
  uint32_t gen;          /* the pairing's generation (per kind; + 1 per re-pairing) */
  uint32_t qkey;         /* the sender's UD Q_Key (a rank: its nonce's low 31 bits), where the answer goes */
  struct glEp qp;        /* the sender's QP of this kind (INIT, RECVs posted for a record QP; fresh PSN) */
  struct glEp ud;        /* the sender's UD QP */
  struct glRegion page;  /* the sender's state page (a rank's: its page; the launcher's: its page) */
  uint32_t creditOff;    /* the byte offset in that page of the sender's consumed-count word for the receiver's
                            messages ((gen << 32) | count, design v2 2.2); for a rank: its rxConsumed slot of this
                            launcher; for the launcher: glPageCredit.consumed of that rank */
  uint32_t pad;
};
GL_STATIC_ASSERT(sizeof(struct glPairBody) == 112, "glPairBody is 112 bytes");

struct glPairAckBody {   /* GL_K_PAIR_ACK */
  uint32_t gen;          /* echo */
  uint32_t status;       /* 0 ok; else refused (reason in the head) */
  struct glEp qp;        /* the answering side's QP of this kind (already RTR/RTS; fresh PSN) */
  struct glRegion page;  /* the answering side's state page */
  uint32_t qkey;         /* the answering side's UD Q_Key */
  uint32_t creditOff;    /* as glPairBody.creditOff, for the answering side */
};
GL_STATIC_ASSERT(sizeof(struct glPairAckBody) == 72, "glPairAckBody is 72 bytes");
#define GL_REPAIR_MS 10000 /* NCCL_GIN_TS_RECONNECT_MS's default: the launcher's re-pairing bound */
#define GL_REPAIR_EVERY_MS 500

/* Spare states (glRegNoteBody.spareState, the page's spare word). */
enum { GL_SP_NONE = 0, GL_SP_REPLAYING = 1, GL_SP_READY = 2, GL_SP_OFFERED = 3, GL_SP_ACCEPTED = 4, GL_SP_FAILED = 5,
       GL_SP_ABORTED = 6 };
/* Registration states (the page's registration word). */
enum { GL_RS_NONE = 0, GL_RS_ALIVE = 1, GL_RS_EXITED = 2, GL_RS_LEFT = 3, GL_RS_FENCED = 4 };

struct glRegNoteBody {   /* GL_K_REG_NOTE (subject rank and nonce in the head; incarnation = regInc) */
  uint32_t regState;     /* GL_RS_*: ALIVE = the launcher holds the pidfd of (rank, regInc) */
  uint32_t regInc;
  uint32_t spareState;   /* GL_SP_* of the pre-launched spare of (rank, spareInc) */
  uint32_t spareInc;
  uint32_t spareAgeMs;   /* how long the spare has been in spareState (the launcher's clock) */
  uint32_t pad;
};
GL_STATIC_ASSERT(sizeof(struct glRegNoteBody) == 24, "glRegNoteBody is 24 bytes");

struct glExitBody {      /* GL_K_EXITED, GL_K_LEFT, GL_K_FENCED: the subject is the head's (rank, incarnation, nonce) */
  uint64_t observedMonoNs; /* when the launcher saw the pidfd readable */
  uint64_t fenceMonoNs;  /* FENCED after a signal: when it sent SIGKILL; else 0 */
};
GL_STATIC_ASSERT(sizeof(struct glExitBody) == 16, "glExitBody is 16 bytes");

struct glActivateBody {  /* GL_K_ACTIVATE */
  struct glRsActivate record;  /* the 64 B record, bytes as today's */
  struct glRegion blob;  /* the activation blob in the buddy's outbox (len 0: none) */
  uint64_t xferId;       /* the buddy's transfer number (echoed nowhere; for its log) */
};
GL_STATIC_ASSERT(sizeof(struct glActivateBody) == 88, "glActivateBody is 88 bytes");

/* GL_K_ACT_ANSWER. After a LATER the launcher sets no time limit of its own in gin-control (the HELLO 2 000 ms and
 * READY 5 000 ms limits are gin-dynamic's): it ends the wait at READY (hand-over), a replay failure, the spare's exit,
 * or the buddy's ABORT. So the rank side bounds it: the LATER says how long the spare has been replaying, the page's
 * spare word and its age move on, and the page beat shows the launcher alive (glPage). Which bound gin-control
 * pre-registers is an open question (README_launcher.md). */
struct glActAnswerBody {
  struct glRsActivate record;  /* the spare's answer record, or the buddy's echoed with kind LATER or REFUSED */
  uint32_t spareState;   /* GL_SP_* when the answer was sent */
  uint32_t spareAgeMs;   /* ms since the spare entered that state (LATER: since its HELLO) */
  uint32_t pageSlot;     /* the index of (rank)'s glPageReg on the launcher page */
  uint32_t pad;
  char why[64];
};
GL_STATIC_ASSERT(sizeof(struct glActAnswerBody) == 144, "glActAnswerBody is 144 bytes");
GL_STATIC_ASSERT(sizeof(struct glPairBody) <= GL_BODY_BYTES && sizeof(struct glPairAckBody) <= GL_BODY_BYTES &&
                     sizeof(struct glActivateBody) <= GL_BODY_BYTES && sizeof(struct glActAnswerBody) <= GL_BODY_BYTES &&
                     GL_FETCH_EP_BYTES <= GL_BODY_BYTES,
                 "every launcher body fits 192 bytes");

/* ---------------------------------------------------------------------------------------------------------------
 * 3. The launcher's state page (REMOTE_READ, 4 KiB, single writer: the launcher's thread; only aligned 8 B words, each
 *    meaningful alone, written with one 8 B store). Ranks READ it over their liveness-READ QP to this launcher.
 *    line 0: head; then GL_PAGE_REGS registration slots of 32 B; then GL_PAGE_CREDITS credit slots of 32 B.
 *    A slot is bound to its (nonce, rank) at first use and never rebound while the launcher lives, so a reader that
 *    matched the nonce and key words can read the state words of the same READ.
 * ------------------------------------------------------------------------------------------------------------- */
#define GL_PAGE_MAGIC 0x504c5247u /* "GRLP" */
#define GL_PAGE_LAYOUT 2u         /* (magicVer & 0xffff): this layout */
#define GL_PAGE_REGS 62
#define GL_PAGE_CREDITS 64
#define GL_BEAT_MS 10

/* registration word: ((uint64_t)GL_RS_* << 56) | ((uint64_t)(rank & 0xffffff) << 32) | incarnation */
/* spare word:        ((uint64_t)GL_SP_* << 56) | ((uint64_t)(rank & 0xffffff) << 32) | spare incarnation */
static inline uint64_t gl_page_word(uint32_t state, int32_t rank, uint32_t inc) {
  return ((uint64_t)(state & 0xffu) << 56) | ((uint64_t)((uint32_t)rank & 0xffffffu) << 32) | inc;
}
static inline uint32_t gl_page_word_state(uint64_t w) { return (uint32_t)(w >> 56); }
static inline int32_t gl_page_word_rank(uint64_t w) { return (int32_t)((w >> 32) & 0xffffffu); }
static inline uint32_t gl_page_word_inc(uint64_t w) { return (uint32_t)w; }

struct glPageReg {
  uint64_t nonce;        /* 0: free */
  uint64_t reg;          /* registration word (the original or the re-registered rank) */
  uint64_t spare;        /* spare word (the pre-launched spare of the next incarnation) */
  uint64_t spareSinceMs; /* the launcher's monoMs when the spare entered its state (compare with glPage.monoMs) */
};
struct glPageCredit {
  uint64_t nonce;        /* 0: free */
  uint64_t peer;         /* ((uint64_t)(rank & 0xffffff) << 32) | that rank's incarnation as paired */
  uint64_t consumed;     /* ((uint64_t)gen << 32) | how many of that rank's record-QP messages the launcher consumed in
                            that generation (design v2 2.2: the rank's credit toward the launcher) */
  uint64_t rsv;
};
struct glPage {
  uint64_t magicVer;     /* (GL_PAGE_MAGIC << 32) | (GL_WIRE_VERSION << 16) | GL_PAGE_LAYOUT */
  uint64_t beat;         /* +1 every loop pass (at least every GL_BEAT_MS) */
  uint64_t monoMs;       /* the launcher's CLOCK_MONOTONIC in ms at the last pass */
  uint64_t node;
  uint64_t qkey;
  uint64_t nRegs;        /* slots in use (bound) */
  uint64_t nCredits;
  uint64_t rsv;
  struct glPageReg reg[GL_PAGE_REGS];
  struct glPageCredit credit[GL_PAGE_CREDITS];
};
GL_STATIC_ASSERT(sizeof(struct glPageReg) == 32 && sizeof(struct glPageCredit) == 32, "page slots are 32 bytes");
GL_STATIC_ASSERT(sizeof(struct glPage) == 4096, "the launcher page is 4 KiB");
GL_STATIC_ASSERT(offsetof(struct glPage, reg) == 64 && offsetof(struct glPage, credit) == 64 + 32 * GL_PAGE_REGS,
                 "page layout");
#define GL_PAGE_CREDIT_OFF(i) ((uint32_t)(offsetof(struct glPage, credit) + 32u * (uint32_t)(i) + 16u))

/* ---------------------------------------------------------------------------------------------------------------
 * 4. Pure helpers (both sides)
 * ------------------------------------------------------------------------------------------------------------- */

static inline void gl_env_pack(struct glCtrlEnv* e, uint16_t kind, int32_t from, uint32_t gen, uint64_t seq,
                               uint64_t ackSeq, uint64_t nonce, uint32_t inc) {
  uint8_t* p = (uint8_t*)e;
  for (size_t i = 0; i < sizeof(*e); i++) p[i] = 0;
  e->magic = GL_ENV_MAGIC;
  e->version = (uint16_t)GL_WIRE_VERSION;
  e->kind = kind;
  e->from = from;
  e->gen = gen;
  e->seq = seq;
  e->ackSeq = ackSeq;
  e->nonce = nonce;
  e->incarnation = inc;
  e->bodyBytes = (uint32_t)sizeof(struct glMsg);
}
/* 0 when the envelope heads a launcher message of `kind` (LAUNCHER or PAIR); else a GL_R_* code. */
static inline uint32_t gl_env_check(const struct glCtrlEnv* e, uint16_t kind) {
  if (e->magic != GL_ENV_MAGIC || e->version != GL_WIRE_VERSION) return GL_R_BAD_MSG;
  if (e->kind != kind || e->bodyBytes != sizeof(struct glMsg)) return GL_R_BAD_MSG;
  return GL_R_NONE;
}
/* 0 when m is a well-formed launcher message; else a GL_R_* code. */
static inline uint32_t gl_msg_check(const struct glMsg* m) {
  if (m->h.magic != GL_MAGIC || m->h.version != GL_WIRE_VERSION) return GL_R_BAD_MSG;
  if (m->h.kind < 1 || m->h.kind > GL_K_KIND_MAX) return GL_R_UNKNOWN_KIND;
  if (m->h.bodyBytes > GL_BODY_BYTES) return GL_R_BAD_MSG;
  return GL_R_NONE;
}
/* 0 when u is a well-formed Unix message of n received bytes; else a GL_R_* code. */
static inline uint32_t gl_unix_check(const struct glUnixMsg* u, size_t n) {
  if (n < sizeof(struct glUnixMsg)) return GL_R_BAD_MSG;
  if (u->h.magic != GL_U_MAGIC || u->h.version != GL_WIRE_VERSION) return GL_R_BAD_MSG;
  if (u->h.kind < 1 || u->h.kind > GL_U_KIND_MAX) return GL_R_UNKNOWN_KIND;
  if (u->h.bodyBytes > GL_U_BODY_BYTES) return GL_R_BAD_MSG;
  if (u->h.payloadBytes > GL_U_MAX_PAYLOAD) return GL_R_BAD_MSG;
  if (n != sizeof(struct glUnixMsg) + u->h.payloadBytes) return GL_R_BAD_MSG;
  if (u->h.payloadBytes != 0 && u->h.kind != GL_U_ACT_BYTES) return GL_R_BAD_MSG;
  return GL_R_NONE;
}

/* The arming condition on the rdma path (EXPERIMENT.md 9.5 "등록", design v2 5.4 1 and 7, REVIEW2 fix 8): "a spare is
 * registered" becomes "paired with that node's launcher, the launcher holds this incarnation's pidfd, and it noted a
 * pre-launched spare of the next incarnation that said HELLO". The rank side fills glArmView from what its launcher(s)
 * answered; today's decision is `allArmable && haveSpare` (gdakiCkptOnStable, ln4 14981).
 *   regAcked / regAckInc: the own launcher's GL_U_HELLO_ACK answered GL_UA_OK to REGISTER(rank, inc) for this inc;
 *   ownPaired: the record QP to the own launcher is CONNECTED;
 *   notedReg / notedInc: its latest REG_NOTE (or page) registration word is ALIVE for this inc;
 *   notedSpare / notedSpareInc: its spare word is REPLAYING, READY or OFFERED for inc + 1;
 *   allPaired: every launcher of the communicator is paired (a revived rank re-arms only after both, design v2 5.4 7);
 *   leaving: this rank sent LEAVING. */
struct glArmView {
  uint32_t inc;
  uint32_t regAcked, regAckInc;
  uint32_t ownPaired;
  uint32_t notedReg, notedInc;
  uint32_t notedSpare, notedSpareInc;
  uint32_t allPaired;
  uint32_t leaving;
};
static inline int gl_spare_usable(uint32_t sp) {
  return sp == GL_SP_REPLAYING || sp == GL_SP_READY || sp == GL_SP_OFFERED;
}
static inline int gl_path_exists(const struct glArmView* v) {
  return v->regAcked && v->regAckInc == v->inc && v->ownPaired && v->notedReg == GL_RS_ALIVE && v->notedInc == v->inc &&
         gl_spare_usable(v->notedSpare) && (uint64_t)v->notedSpareInc == (uint64_t)v->inc + 1u && v->allPaired &&
         !v->leaving;
}
/* The rdma build's CKPT_STABLE armable bit: when the path exists it is today's decision with a spare registered. */
static inline int gl_armable(int allArmable, const struct glArmView* v) { return allArmable && gl_path_exists(v); }

#endif /* GIN_LAUNCHER_MSG_H */
