// rs_ctrl_api.h - gin-control, the preparation stage's shared interface (EXPERIMENT.md 9.8 "준비(갈아 끼우는 자리)"; the
// control-path design v2 2.0-2.5, 3.1, 5.4, 7.1-7.3, with the independent re-review of 2026-10-17, REVIEW2 5절): the
// 64 B envelope of every control SEND and UD datagram, the status page's judgement words and its seqlock report line,
// the host QP endpoint version 2 (40 B), the pairing body, the REJOIN's nrp layout, the fence word, this rank's consumed
// words for the launchers (the launcher's page itself is launcher/launcher_msg.h's), the records 52-55, the widened host
// QP template's attributes, the parameter names, and
// the swap points through which phases 1-3 replace the TCP control path with RDMA while the compile-time switch
// NCCL_GIN_CTRL_TCP keeps the whole old stack (decision 1).
//
// Base: gin-mirror build ln4 (../../mirror/impl/mi_layer.diff, md5 dcd30859; its host file md5 0ab4e636, 24 507 lines).
// A number NNNN below is a line of that host file. gin-mirror's files are read only (its PREREG.txt pins mi_layer.diff).
//
// Two blocks are pasted verbatim into src/transport/net_ib/gdaki/gin_host_gdaki.cc right after the end of the block
// "gin-mirror: store API" (6500; so they see struct gdakiTsMsg, struct gdakiTsPeer, struct gdakiRecHost, the hold API's
// records and struct gdakiMiQpEndpoint): "gin-control: ctrl API" (types, constants, pure static inline functions) and
// "gin-control: ctrl seams" (the switch: the tcp build's macros, the default build's entry-point declarations with their
// owner). build_gc.sh `paste` pastes them, `api` checks them byte for byte and compiles this header standalone.
//
// ---- the switches (decision 1, design v2 2.0, REVIEW2 고칠 것 3) ----
// -DNCCL_GIN_CTRL_TCP=1 builds the regression arm (keys gct, gctp): every swap point expands to today's call, and every
// new type, function, member and call is inside #if !NCCL_GIN_CTRL_TCP (or the #if NCCL_GIN_CTRL_TCP side of an #else
// keeps ln4's text), so the tcp build's preprocessed host file is ln4's but for the __FILE__/__LINE__ pairs (build_gc.sh
// `pre`). What the tcp control cells need on top (the test switches DIE_RST, RST_GAP, FD_HOLDER and the like, the RST
// refusal gap parameter) goes behind #if NCCL_GIN_CTRL_TCP && NCCL_GIN_CTRL_TCP_CELLS (research builds only): gct stays
// ln4's, the cell build (key gctc, -DNCCL_GIN_CTRL_TCP=1 -DNCCL_GIN_CTRL_TCP_CELLS=1) differs by exactly that code.
// Without NCCL_GIN_CTRL_TCP (keys gc, gcp) the swap points are functions; in the preparation stage they still carry
// every record on the TCP back end (the "mixed build" of 9.8 until phase 2), so the builds behave alike. Nothing is
// chosen at run time.
//
// ---- swap points and owners (9.8's table; [prep] = this stage, [1] [2] [3] = the phases; impl/gc_sites.tsv lists
// every site with its class) ----
//   gdakiCtrlSend(r, peer, ch, fd, m, timeoutMs)  [prep] 18 of ln4's 25 gdakiTsSend calls (26 lines with the
//        definition): the record path (GDAKI_CTRL_CH_RECORD), the REJOIN path (_REJOIN) and the data sockets (_DATA);
//        `fd` is the TCP back end's socket. The other 7 (BYE 8173, the reconnect machinery's FAIL answer 8498, HELLO 8609,
//        PROBE 8711, PROBE_ACK 8798, HELLO_ACK 8843, the setup's HELLO 18130) are the witness's and stay gdakiTsSend
//        calls in both builds (REVIEW2 고칠 것 4). gdakiHoldSend (15 calls; 17 lines with its declaration in the hold API's
//        shared text and its definition) keeps its name and text: its one send (12987) is a record-path gdakiCtrlSend, so
//        all its callers go through the swap point.
//   gdakiCtrlPump(r, peer, pe, out)  [prep] 5 of ln4's 6 gdakiTsPump calls (7 lines with the definition): the peers'
//        record reads. The sixth (gdakiTsRecv's, 8267) is the TCP back end's bare-socket helper (accept, REJOIN and setup
//        sockets) and stays; the record wait through gdakiTsRecv (gdakiMiSetupEnd, 22372) is marked with gdakiCtrlFd.
//   gdakiCtrlFd(pe)  [prep] the record path's uses of a peer's helper socket (26 of ln4's 56 pe.fd lines and 10 lines
//        with another spelling); every other use (the witness, the TCP back end) stays pe.fd.
//   gdakiMiHostQpCreate(..., const struct gdakiCtrlQpAttr& attr = gdakiCtrlQpAttr())  [prep] widened (QP type, SQ, RQ
//        and CQ depth, an owner thread's CQ, a completion channel, access bits, Q_Key; the RTS timeout, retry_cnt,
//        rnr_retry and min_rnr_timer that gdakiMiHostQpConnect sets): the defaults are ln4's values (the store's and the
//        FETCH's QPs are unchanged). gdakiCtrlCqCreate/Destroy [prep]: an owner thread's CQ with stats of its own.
//   gdakiTsSetup -> gdakiTsSetup (the all-gather and the agreement) + gdakiTsSetupConnect (the connect and the rest)
//        [prep split; 2 owns gdakiTsSetupConnect's pairing, MTU and fork checks].
//   gdakiRsSpareRun -> gdakiRsSpareActivateWait [3] + gdakiRsSpareRejoinAll [2] + the RESTORED tail [prep].
//   gdakiHoldActivate -> gdakiHoldActivateDecide [prep] + gdakiHoldActivateSend [3].
//   the liveness READ QP: gdakiProbeQpCreate, gdakiProbeQpEndpoint, gdakiProbeQpConnect, gdakiProbeQpReconnect (RESET,
//        a fresh PSN, connected again on its own: the record QP's pairing does not touch it, REVIEW2 막는 문제 4),
//        gdakiProbeQpIsRts, gdakiProbeQpDestroy [prep, on the template]; gdakiProbeToErr [1] (a placeholder until then).
//   hooks: gdakiCtrlPeerToErr [prep frame: gdakiCtrlRecordToErr [2], gdakiProbeToErr [1], gdakiStoreWardToErr [2]],
//        called at the hold start after the quiesce; gdakiCtrlOnHoldStart [3] (SPAWN), called there too;
//        gdakiCtrlLauncherSend [3] (phase 1 calls it; empty before); gdakiLnFenced [1] (FENCED into the fence word).
//   struct gdakiCtrlState: one pointer member `ctrl` of struct gdakiRecHost; each phase owns one pointer below it.
//   In the tcp build every one of these is a macro: the swap points today's calls, the rest no-ops.
//
// ---- where helperBusy comes from (REVIEW2 고칠 것 15; the watch thread copies it, phase 1) ----
// ts->busySinceUs (the round's clock: struct gdakiTsBusy in gdakiTsInitiate, gdakiTsRespond, gdakiHoldStart,
// gdakiHoldActivate's mirror branch, gdakiHoldCommitRound, gdakiHoldDrive, gdakiHoldTransferStep; bound
// NCCL_GIN_TS_ROUND_MS) and r->fwSinceUs (a firmware phase: gdakiRecFwGuard, gdakiRecFwMark; bound NCCL_GIN_TS_FW_MS):
// gdakiCtrlBusyOf below.
//
// Not here: the launcher's 256 B message and the node-local Unix socket's messages (launcher/launcher_msg.h, owned by the
// launcher's work package). It is included below when present and its envelope, endpoint and region are checked
// against these; the host file does not include it (the phases paste what they need of it).
#ifndef GIN_CONTROL_RS_CTRL_API_H_
#define GIN_CONTROL_RS_CTRL_API_H_

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

// A standalone syntax check needs gin-mirror's store API (struct gdakiMiQpEndpoint, version 1 of the endpoint) and the
// hold API (the record ranges): in the host file the blocks follow them. build_gc.sh `api` includes gin-mirror's seven
// headers first.
#include "rs_hold_api.h"
#include "rs_store_api.h"

#if defined(__has_include)
#if __has_include("launcher/launcher_msg.h")
#include "launcher/launcher_msg.h"
#define GDAKI_CTRL_HAVE_LAUNCHER_MSG 1
#endif
#endif

// ---- gin-control: ctrl API (begin; impl/rs_ctrl_api.h, byte for byte) ----
#ifndef NCCL_GIN_CTRL_TCP
#define NCCL_GIN_CTRL_TCP 0  // the default build (rdma); the regression arm builds with -DNCCL_GIN_CTRL_TCP=1
#endif
#ifndef NCCL_GIN_CTRL_TCP_CELLS
#define NCCL_GIN_CTRL_TCP_CELLS 0  // with NCCL_GIN_CTRL_TCP: the tcp control cells' additions (key gctc); never production
#endif
#if NCCL_GIN_CTRL_TCP_CELLS && defined(NCCL_GIN_TS_PRODUCTION)
#error "NCCL_GIN_CTRL_TCP_CELLS holds test switches: not in a production build"
#endif
// ---- parameter names (macros only: nothing of this reaches the preprocessed output) ----
// NCCL_PARAM(<Name>, GDAKI_CTRL_P_<X>, GDAKI_CTRL_<X>_DEFAULT) in the phase in brackets; every rank must hold the same
// values (gdakiCtrlThresholdsOk at the setup).
#define GDAKI_CTRL_SWITCH_NAME "NCCL_GIN_CTRL_TCP"           // compile time only (the build keys gct, gctp)
#define GDAKI_CTRL_P_PROBE_MS "GIN_TS_PROBE_MS"              // [1] the liveness READ's period; 0: no READ (cost cells)
#define GDAKI_CTRL_PROBE_MS_DEFAULT 100
#define GDAKI_CTRL_P_PROBE_TIMEOUT_MS "GIN_CTRL_PROBE_TIMEOUT_MS"  // [1] a READ in flight longer: suspicion only
#define GDAKI_CTRL_PROBE_TIMEOUT_MS_DEFAULT 500
#define GDAKI_CTRL_P_CONFIRM_MS "GIN_CTRL_CONFIRM_MS"        // [1] W, the confirmation window after a witness FIN or RST
#define GDAKI_CTRL_CONFIRM_MS_DEFAULT 20                     //     draft: 20-50, phase 1's pilot fixes it (9.3)
#define GDAKI_CTRL_CONFIRM_MS_MIN 20
#define GDAKI_CTRL_P_WITNESS "GIN_CTRL_WITNESS"              // [2] the management-net witness socket (BYE and FIN only)
#define GDAKI_CTRL_WITNESS_DEFAULT 1
#define GDAKI_CTRL_P_SUSPECT_MS "GIN_TS_SUSPECT_MS"          // [1] a stale beat this long: one suspicion line
#define GDAKI_CTRL_SUSPECT_MS_DEFAULT 2000
#define GDAKI_CTRL_P_STALL_MS "GIN_TS_STALL_MS"              // [1] a stale beat this long (+ partition guard + veto): stall
#define GDAKI_CTRL_STALL_MS_DEFAULT 10000
#define GDAKI_CTRL_P_STALL_RMSN_MS "GIN_TS_STALL_RMSN_MS"    // [1] the data path's veto window
#define GDAKI_CTRL_STALL_RMSN_MS_DEFAULT 1000
#define GDAKI_CTRL_P_PROBE_FAIL_N "GIN_TS_PROBE_FAIL_N"      // [1] re-pairings of a READ that gets no answer
#define GDAKI_CTRL_PROBE_FAIL_N_DEFAULT 3
#define GDAKI_CTRL_P_RESTORE_FENCE "GIN_RESTORE_FENCE"       // [1] "lineage": fence and restore a stall; "none": decline
#define GDAKI_CTRL_RESTORE_FENCE_DEFAULT "lineage"
// The tcp control cells only [1] (behind NCCL_GIN_CTRL_TCP && NCCL_GIN_CTRL_TCP_CELLS): the refusal gap after an RST
// (ln4: the second refusal 1000 ms after the first; the user decision of 2026-10-16 night: default 1000, the RST cell 100).
#define GDAKI_CTRL_P_RST_REFUSAL_GAP_MS "GIN_TS_RST_REFUSAL_GAP_MS"
#define GDAKI_CTRL_RST_REFUSAL_GAP_MS_DEFAULT 1000
// The marker of the record path's use of a peer's helper socket (impl/gc_sites.tsv). Both builds: the same tokens as
// ln4's `pe.fd`. Its argument is always a gdakiTsPeer lvalue spelled as a postfix expression (pe, o, ts->peers[p]).
#define gdakiCtrlFd(pe) pe.fd

#if !NCCL_GIN_CTRL_TCP
// ---- the range check of the thresholds (9.3 "범위 검사"; every rank the same values, at the setup) ----
static inline bool gdakiCtrlThresholdsOk(int64_t probeMs, int64_t probeTimeoutMs, int64_t confirmMs, int64_t suspectMs,
                                         int64_t stallMs, int64_t restoreMs, int64_t spareStartMs, char* why,
                                         size_t whyLen) {
  const char* w = nullptr;
  if (probeMs < 0) w = "PROBE_MS < 0";
  else if (10 * probeMs > suspectMs) w = "10 x PROBE_MS > SUSPECT_MS";
  else if (suspectMs >= stallMs) w = "SUSPECT_MS >= STALL_MS";
  else if (stallMs + 1000 > restoreMs) w = "STALL_MS + 1000 > NCCL_GIN_RESTORE_MS";
  else if (probeTimeoutMs < 5 * probeMs) w = "PROBE_TIMEOUT_MS < 5 x PROBE_MS";
  else if (confirmMs < GDAKI_CTRL_CONFIRM_MS_MIN) w = "CONFIRM_MS < 20";
  else if (confirmMs >= probeTimeoutMs) w = "CONFIRM_MS >= PROBE_TIMEOUT_MS";
  else if (spareStartMs + 1000 > restoreMs) w = "SPARE_START_MS + 1000 > NCCL_GIN_RESTORE_MS";
  if (w != nullptr && why != nullptr && whyLen > 0) snprintf(why, whyLen, "%s", w);
  return w == nullptr;
}

// ---- the envelope (design v2 2.3; the same bytes as launcher/launcher_msg.h's glCtrlEnv) ----
// 64 B in front of every SEND of the record QP, the launcher QP and every UD datagram. Design v2's field list sums to
// 56 B against its stated 64 B (REVIEW2 고칠 것 6); rsv[16] keeps the 64 B and every named offset (launcher_msg.h too).
#define GDAKI_CTRL_ENV_MAGIC 0x45435247u  // "GRCE" in memory order
#define GDAKI_CTRL_ENV_VERSION 1u
enum : uint16_t {
  GDAKI_CTRL_K_RECORD = 1,     // body: struct gdakiTsMsg, byte for byte (1872 B)
  GDAKI_CTRL_K_XFER = 2,       // body: struct gdakiCtrlXfer (a half of the outbox is ready to READ)
  GDAKI_CTRL_K_XFER_DONE = 3,  // body: struct gdakiCtrlXfer (the receiver READ it)
  GDAKI_CTRL_K_LAUNCHER = 4,   // body: the launcher's 256 B message (launcher/launcher_msg.h)
  GDAKI_CTRL_K_PAIR = 5,       // UD only: rank-rank struct gdakiCtrlPairBody; rank-launcher: launcher_msg.h's
};
#define GDAKI_CTRL_K_MAX 5u
#define GDAKI_CTRL_FROM_LAUNCHER 0x40000000  // `from` of a launcher: GDAKI_CTRL_FROM_LAUNCHER | node
struct gdakiCtrlEnv {
  uint32_t magic;        // GDAKI_CTRL_ENV_MAGIC
  uint16_t version;      // GDAKI_CTRL_ENV_VERSION
  uint16_t kind;         // GDAKI_CTRL_K_*
  int32_t from;          // the sender's rank, or GDAKI_CTRL_FROM_LAUNCHER | node
  uint32_t gen;          // the pair's connection generation (one TCP connection's worth)
  uint64_t seq;          // from 1 per (pair, direction, generation)
  uint64_t ackSeq;       // the records of the other direction this side consumed (credit; meaningful in gen only)
  uint64_t nonce;        // the context's nonce (the body's nonce too)
  uint32_t incarnation;  // the sending process's incarnation
  uint32_t bodyBytes;    // RECORD 1872, LAUNCHER 256, XFER and XFER_DONE 32, PAIR its body
  uint8_t rsv[16];
};
static_assert(sizeof(struct gdakiCtrlEnv) == 64, "the control envelope is 64 bytes");
static_assert(offsetof(struct gdakiCtrlEnv, from) == 8 && offsetof(struct gdakiCtrlEnv, gen) == 12 &&
                  offsetof(struct gdakiCtrlEnv, seq) == 16 && offsetof(struct gdakiCtrlEnv, ackSeq) == 24 &&
                  offsetof(struct gdakiCtrlEnv, nonce) == 32 && offsetof(struct gdakiCtrlEnv, incarnation) == 40 &&
                  offsetof(struct gdakiCtrlEnv, bodyBytes) == 44,
              "the envelope's offsets (design v2 2.3)");
#define GDAKI_CTRL_RECORD_BYTES 1872u    // sizeof(struct gdakiTsMsg) (the host file asserts it)
#define GDAKI_CTRL_LAUNCHER_BYTES 256u   // the launcher's message
#define GDAKI_CTRL_XFER_BYTES 32u
#define GDAKI_CTRL_SLOT_BYTES 2048u      // one receive slot of a ring: envelope + record, rounded
#define GDAKI_CTRL_RING_SLOTS 64u        // K: receive slots per sending peer (= RECVs posted per record QP)
#define GDAKI_CTRL_UD_BYTES (64u + GDAKI_CTRL_RECORD_BYTES)  // the largest datagram: 1936 B (path MTU >= 2048, 9.6)
#define GDAKI_CTRL_UD_GRH_BYTES 40u
static_assert(64u + GDAKI_CTRL_RECORD_BYTES <= GDAKI_CTRL_SLOT_BYTES, "an envelope and a record fit a slot");
static_assert(GDAKI_CTRL_UD_BYTES <= 2048u, "a datagram fits a path MTU of 2048");
static inline void gdakiCtrlEnvPack(struct gdakiCtrlEnv* e, uint16_t kind, int32_t from, uint32_t gen, uint64_t seq,
                                    uint64_t ackSeq, uint64_t nonce, uint32_t inc, uint32_t bodyBytes) {
  memset(e, 0, sizeof(*e));
  e->magic = GDAKI_CTRL_ENV_MAGIC;
  e->version = (uint16_t)GDAKI_CTRL_ENV_VERSION;
  e->kind = kind;
  e->from = from;
  e->gen = gen;
  e->seq = seq;
  e->ackSeq = ackSeq;
  e->nonce = nonce;
  e->incarnation = inc;
  e->bodyBytes = bodyBytes;
}
// 0 when the envelope heads a well-formed body of its kind; else what is wrong (lines name it).
enum : uint32_t { GDAKI_CTRL_ENV_OK = 0, GDAKI_CTRL_ENV_BAD_MAGIC = 1, GDAKI_CTRL_ENV_BAD_VERSION = 2,
                  GDAKI_CTRL_ENV_BAD_KIND = 3, GDAKI_CTRL_ENV_BAD_BYTES = 4, GDAKI_CTRL_ENV_BAD_NONCE = 5 };
static inline uint32_t gdakiCtrlEnvCheck(const struct gdakiCtrlEnv* e, uint64_t nonce, size_t received) {
  if (received < sizeof(*e) || e->magic != GDAKI_CTRL_ENV_MAGIC) return GDAKI_CTRL_ENV_BAD_MAGIC;
  if (e->version != GDAKI_CTRL_ENV_VERSION) return GDAKI_CTRL_ENV_BAD_VERSION;
  if (e->kind < 1 || e->kind > GDAKI_CTRL_K_MAX) return GDAKI_CTRL_ENV_BAD_KIND;
  uint32_t want = 0;
  switch (e->kind) {
    case GDAKI_CTRL_K_RECORD: want = GDAKI_CTRL_RECORD_BYTES; break;
    case GDAKI_CTRL_K_XFER:
    case GDAKI_CTRL_K_XFER_DONE: want = GDAKI_CTRL_XFER_BYTES; break;
    case GDAKI_CTRL_K_LAUNCHER: want = GDAKI_CTRL_LAUNCHER_BYTES; break;
    default: want = e->bodyBytes <= GDAKI_CTRL_RECORD_BYTES ? e->bodyBytes : 0; break;  // PAIR
  }
  if (want == 0 || e->bodyBytes != want || received < sizeof(*e) + (size_t)want) return GDAKI_CTRL_ENV_BAD_BYTES;
  if (e->nonce != nonce) return GDAKI_CTRL_ENV_BAD_NONCE;
  return GDAKI_CTRL_ENV_OK;
}
// The receiver's order rule (design v2 2.4): in the pair's generation g a record is taken when seq = last + 1; an older
// generation's envelope is dropped (and never counted as consumed in g: REVIEW2 막는 문제 4, 3); anything else (a gap, a
// repeat, a newer generation) is the loss of the connection.
enum : uint32_t { GDAKI_CTRL_ORDER_TAKE = 0, GDAKI_CTRL_ORDER_DROP_OLD = 1, GDAKI_CTRL_ORDER_LOST = 2 };
static inline uint32_t gdakiCtrlOrder(uint32_t gen, uint64_t lastSeq, const struct gdakiCtrlEnv* e) {
  if (e->gen < gen) return GDAKI_CTRL_ORDER_DROP_OLD;
  if (e->gen != gen || e->seq != lastSeq + 1u) return GDAKI_CTRL_ORDER_LOST;
  return GDAKI_CTRL_ORDER_TAKE;
}
// A remote-readable region (the same 16 B as launcher_msg.h's glRegion).
struct gdakiCtrlRegion {
  uint64_t addr;
  uint32_t rkey;  // host order
  uint32_t len;
};
static_assert(sizeof(struct gdakiCtrlRegion) == 16, "a region is 16 bytes");
// The outbox (design v2 2.3): 2 x 1 MiB of host memory (REMOTE_READ only); the giver fills a half and sends XFER, the
// receiver READs it over the record QP and answers XFER_DONE with the same body.
#define GDAKI_CTRL_OUTBOX_HALF_BYTES (1u << 20)
#define GDAKI_CTRL_OUTBOX_BYTES (2u * GDAKI_CTRL_OUTBOX_HALF_BYTES)
#define GDAKI_CTRL_XFER_F_END 0x1u  // the last piece of this transfer
struct gdakiCtrlXfer {
  uint64_t xferId;  // the transfer's number (per pair and direction)
  uint64_t bytes;   // the bytes in this half (<= GDAKI_CTRL_OUTBOX_HALF_BYTES)
  uint32_t half;    // 0 or 1: at the giver's outbox address + half x GDAKI_CTRL_OUTBOX_HALF_BYTES
  uint32_t rkey;    // the outbox MR's rkey (host order)
  uint32_t flags;   // GDAKI_CTRL_XFER_F_*
  uint32_t rsv;
};
static_assert(sizeof(struct gdakiCtrlXfer) == GDAKI_CTRL_XFER_BYTES, "an XFER body is 32 bytes");

// ---- records 52-55 (the empty 52-63 of the restore records' range 11-63: the park rule holds, 5494) ----
// All: from, nonce as every record; arg = the subject rank, round = its incarnation (as gdakiHoldMsgInit), so every one
// of them names (rank, incarnation, nonce) (REVIEW2 고칠 것 12; the launcher's EXITED, LEFT and FENCED carry the same in
// their head, launcher_msg.h glMsgHdr). A receiver takes them only for the current incarnation or HELD_OLD (the lineage).
#define GDAKI_TS_CTRL_STALLED 52u      // [1] a software stall judged (the broadcast; 9.3's stall row)
#define GDAKI_TS_CTRL_DISPUTE 53u      // [1] the judgements of the subject disagree
#define GDAKI_TS_CTRL_FENCED 54u       // [1] FENCED(p, i) from the launcher, handed into the hold machine (the fence word)
#define GDAKI_TS_CTRL_PROBE_SETUP 55u  // [1] phase 1's named scaffold only: the liveness READ QP's endpoint (struct
                                       //     gdakiCtrlEndpoint in nrp[], unused by every record: REVIEW2 1절 B3) over the
                                       //     helper TCP socket until phase 2's pairing is merged; it goes with phase 2
static_assert(GDAKI_TS_CTRL_STALLED >= 52u && GDAKI_TS_CTRL_PROBE_SETUP <= 63u, "the new records are in 52..63");
static inline bool gdakiCtrlIsRecord(uint32_t t) { return t >= GDAKI_TS_CTRL_STALLED && t <= GDAKI_TS_CTRL_PROBE_SETUP; }
static inline const char* gdakiCtrlRecordName(uint32_t t) {
  switch (t) {
    case GDAKI_TS_CTRL_STALLED: return "STALLED";
    case GDAKI_TS_CTRL_DISPUTE: return "DISPUTE";
    case GDAKI_TS_CTRL_FENCED: return "FENCED";
    case GDAKI_TS_CTRL_PROBE_SETUP: return "PROBE_SETUP";
    default: return "?";
  }
}

// ---- the fence word (REVIEW2 막는 문제 1) ----
// The hold cell's neighbour word of rank p: 0 = no incarnation of p is fenced (the value of zeroed memory and of every
// rank right after the setup), i + 1 = incarnation i is fenced. Never the incarnation itself: the first death is almost
// always incarnation 0, and a word 0 read as "0 is fenced" would let the activation go without FENCED. The lineage's
// phases (gdakiLnViewOf, GDAKI_LN_*) are not touched: FENCING and FENCED are report names only, and the one rule that
// changes is the ACTIVATE and REJOIN acceptance's added condition gdakiCtrlFencedIs(word, dead).
#define GDAKI_CTRL_FENCE_NONE 0ull
static inline uint64_t gdakiCtrlFenceWord(uint32_t inc) { return (uint64_t)inc + 1u; }
static inline bool gdakiCtrlFencedIs(uint64_t word, uint32_t dead) {
  return word != GDAKI_CTRL_FENCE_NONE && word == (uint64_t)dead + 1u;
}
static_assert(GDAKI_CTRL_FENCE_NONE == 0ull, "a zeroed fence word means no fence");

// ---- the status page (design v2 3.1-3.3; REVIEW2 고칠 것 7) ----
// One 4 KiB host region per rank (REMOTE_READ only), written by the watch thread alone. The judgement reads aligned 8 B
// words only, each meaningful by itself; a word is written with one 8 B store (gdakiCtrlWordStore). Line 0 below; then
// the per-peer words rxConsumed[N], the launchers' rxConsumedL[nL] (the consumed count of this rank's ring share of each
// launcher: the launcher's credit, its second source), staleMs[N]; then the report lines (seqlock).
#define GDAKI_CTRL_PAGE_BYTES 4096u
#define GDAKI_CTRL_PAGE_VERSION 2u  // version 2: the launchers' consumed words (REVIEW2 고칠 것 7)
struct alignas(64) gdakiCtrlPageHead {
  uint64_t watchBeat;       // +1 every 1 ms by the watch thread ("the process runs")
  uint64_t helperBeat;      // the copy of ts->heartbeatUs ("the helper runs")
  uint64_t helperBusy;      // gdakiCtrlBusyWord(busy number, bound ms); 0: not busy (firmware phase, round)
  uint64_t incNonce;        // gdakiCtrlIncNonce(incarnation, nonce): a changed value is another process
  uint64_t flags;           // GDAKI_CTRL_PF_*, the page version in the top byte
  uint64_t appStep;         // the last ncclGinRestoreStep's step (report only)
  uint64_t lastStableCkpt;  // this rank's last stable checkpoint (report and the buddy's check)
  uint64_t rsv;
};
static_assert(sizeof(struct gdakiCtrlPageHead) == 64 && alignof(struct gdakiCtrlPageHead) == 64, "line 0 is 64 B");
static_assert(offsetof(struct gdakiCtrlPageHead, watchBeat) == 0 && offsetof(struct gdakiCtrlPageHead, helperBeat) == 8 &&
                  offsetof(struct gdakiCtrlPageHead, helperBusy) == 16 && offsetof(struct gdakiCtrlPageHead, incNonce) == 24 &&
                  offsetof(struct gdakiCtrlPageHead, flags) == 32 && offsetof(struct gdakiCtrlPageHead, appStep) == 40 &&
                  offsetof(struct gdakiCtrlPageHead, lastStableCkpt) == 48,
              "the judgement words are 8 B aligned at fixed offsets");
#define GDAKI_CTRL_PF_LEAVING 0x1ull  // BYE sent: the rank is leaving
#define GDAKI_CTRL_PF_RESTORE 0x2ull  // the restore is on
#define GDAKI_CTRL_PF_MIRROR 0x4ull   // the mirror is on
#define GDAKI_CTRL_PF_VERSION_SHIFT 56
static inline uint64_t gdakiCtrlPageFlags(bool leaving, bool restore, bool mirror) {
  return (leaving ? GDAKI_CTRL_PF_LEAVING : 0) | (restore ? GDAKI_CTRL_PF_RESTORE : 0) | (mirror ? GDAKI_CTRL_PF_MIRROR : 0) |
         ((uint64_t)GDAKI_CTRL_PAGE_VERSION << GDAKI_CTRL_PF_VERSION_SHIFT);
}
// (incarnation << 32) | the low 32 bits of the context's nonce
static inline uint64_t gdakiCtrlIncNonce(uint32_t inc, uint64_t nonce) { return ((uint64_t)inc << 32) | (uint32_t)nonce; }
static inline uint32_t gdakiCtrlIncOf(uint64_t w) { return (uint32_t)(w >> 32); }
static inline uint32_t gdakiCtrlNonce32Of(uint64_t w) { return (uint32_t)w; }
// (busy number << 32) | bound ms; the number is never 0 (0 = not busy); the reader times the bound on its own clock from
// the moment it first sees a new number
static inline uint64_t gdakiCtrlBusyWord(uint32_t busyNo, uint32_t boundMs) {
  return busyNo == 0 ? 0 : ((uint64_t)busyNo << 32) | boundMs;
}
static inline uint32_t gdakiCtrlBusyNoOf(uint64_t w) { return (uint32_t)(w >> 32); }
static inline uint32_t gdakiCtrlBusyBoundOf(uint64_t w) { return (uint32_t)w; }
// The word the watch thread writes from the helper's two clocks (see the head of this file): a round (busySinceUs != 0,
// bound roundMs) or a firmware phase (fwSinceUs != 0, bound fwMs); both: the later start, the larger bound. The busy
// number is the start's microseconds folded to 31 bits, | 1 (never 0); a new start is a new number.
static inline uint64_t gdakiCtrlBusyOf(int64_t busySinceUs, int64_t roundMs, int64_t fwSinceUs, int64_t fwMs) {
  if (busySinceUs <= 0 && fwSinceUs <= 0) return 0;
  const int64_t start = busySinceUs > fwSinceUs ? busySinceUs : fwSinceUs;
  int64_t bound = 0;
  if (busySinceUs > 0 && roundMs > bound) bound = roundMs;
  if (fwSinceUs > 0 && fwMs > bound) bound = fwMs;
  const uint32_t no = ((uint32_t)((uint64_t)start ^ ((uint64_t)start >> 31)) & 0x7fffffffu) | 1u;
  return gdakiCtrlBusyWord(no, bound > 0xffffffffll ? 0xffffffffu : (uint32_t)bound);
}
// (generation << 32) | count: the consumed word of a peer's (or a launcher's) share (credit, design v2 2.2)
static inline uint64_t gdakiCtrlGenCount(uint32_t gen, uint32_t count) { return ((uint64_t)gen << 32) | count; }
static inline uint32_t gdakiCtrlGenOf(uint64_t w) { return (uint32_t)(w >> 32); }
static inline uint32_t gdakiCtrlCountOf(uint64_t w) { return (uint32_t)w; }
// The sender may post one more SEND in generation `gen` after `sent` SENDs when the consumed word is of that generation
// and sent - consumed < K (no RNR: a RECV waits for every SEND in flight); a word of another generation counts as none
// consumed yet in `gen` (the receiver posted K RECVs before RTR).
static inline bool gdakiCtrlCanSend(uint32_t gen, uint64_t sent, uint64_t consumedWord) {
  if (gdakiCtrlGenOf(consumedWord) != gen) return sent < GDAKI_CTRL_RING_SLOTS;
  return (uint32_t)((uint32_t)sent - gdakiCtrlCountOf(consumedWord)) < GDAKI_CTRL_RING_SLOTS;
}
// One aligned 8 B word: one store, one load (x86: atomic; a READ of it gives one moment's value, design v2 3.2)
static inline void gdakiCtrlWordStore(uint64_t* w, uint64_t v) { __atomic_store_n(w, v, __ATOMIC_RELEASE); }
static inline uint64_t gdakiCtrlWordLoad(const uint64_t* w) { return __atomic_load_n(w, __ATOMIC_ACQUIRE); }
// A report line: several words of one meaning, under the line's own seqlock (ver odd while it is written).
struct alignas(64) gdakiCtrlReportLine {
  uint64_t ver;
  uint64_t w[7];
};
static_assert(sizeof(struct gdakiCtrlReportLine) == 64, "a report line is 64 B");
static inline void gdakiCtrlLineWrite(struct gdakiCtrlReportLine* l, const uint64_t* w7) {
  const uint64_t v = __atomic_load_n(&l->ver, __ATOMIC_RELAXED);
  __atomic_store_n(&l->ver, v | 1u, __ATOMIC_RELAXED);  // odd
  __atomic_thread_fence(__ATOMIC_RELEASE);
  for (int i = 0; i < 7; i++) __atomic_store_n(&l->w[i], w7[i], __ATOMIC_RELAXED);
  __atomic_store_n(&l->ver, (v | 1u) + 1u, __ATOMIC_RELEASE);  // even again
}
// A local reader (a model, or the writer's own process): true with a consistent copy.
static inline bool gdakiCtrlLineRead(const struct gdakiCtrlReportLine* l, uint64_t* w7) {
  const uint64_t v0 = __atomic_load_n(&l->ver, __ATOMIC_ACQUIRE);
  if (v0 & 1u) return false;
  for (int i = 0; i < 7; i++) w7[i] = __atomic_load_n(&l->w[i], __ATOMIC_RELAXED);
  __atomic_thread_fence(__ATOMIC_ACQUIRE);
  return __atomic_load_n(&l->ver, __ATOMIC_RELAXED) == v0;
}
// A remote snapshot (one READ of the line): usable only with an even ver. One ver word cannot show a line torn inside
// the READ (EXPERIMENT.md 9.2: whether the NIC reads a 64 B line at one moment is [미확인]); a writer that repeats ver in
// w[6] lets the reader see it (the second form; phase 1 picks).
static inline bool gdakiCtrlLineSnapshotOk(const struct gdakiCtrlReportLine* s) { return (s->ver & 1u) == 0; }
static inline bool gdakiCtrlLineSnapshotOk2(const struct gdakiCtrlReportLine* s) {
  return (s->ver & 1u) == 0 && s->w[6] == s->ver;
}
// The page's layout for N ranks and nL launchers: line 0, rxConsumed[N], rxConsumedL[nL], staleMs[N] (8 B each, from
// byte 64), then the report lines (from a 64 B boundary): ceil(N / 7) lines of the lineage view (one word per logical
// rank) and as many of the hold summary (one word per peer). Rank 4 with 2 launchers: 256 B (design v2 3.1's size with
// the launchers' two words in the second line's slack). False beyond one page.
struct gdakiCtrlPageLayout {
  uint32_t nranks = 0, nLaunchers = 0;
  uint32_t rxConsumedOff = 0, rxConsumedLOff = 0, staleMsOff = 0;
  uint32_t lineageOff = 0, holdOff = 0;  // the first report line of each
  uint32_t nLineageLines = 0, nHoldLines = 0;
  uint32_t bytes = 0;                    // the part of the page in use (what one READ fetches)
};
#define GDAKI_CTRL_PAGE_MAX_RANKS 112u
#define GDAKI_CTRL_PAGE_MAX_LAUNCHERS 16u
static inline bool gdakiCtrlPageLayoutOf(uint32_t nranks, uint32_t nLaunchers, struct gdakiCtrlPageLayout* out) {
  struct gdakiCtrlPageLayout l;
  if (nranks == 0 || nranks > GDAKI_CTRL_PAGE_MAX_RANKS || nLaunchers > GDAKI_CTRL_PAGE_MAX_LAUNCHERS) return false;
  l.nranks = nranks;
  l.nLaunchers = nLaunchers;
  l.rxConsumedOff = (uint32_t)sizeof(struct gdakiCtrlPageHead);
  l.rxConsumedLOff = l.rxConsumedOff + 8u * nranks;
  l.staleMsOff = l.rxConsumedLOff + 8u * nLaunchers;
  const uint32_t lines = (nranks + 6u) / 7u;
  l.lineageOff = (l.staleMsOff + 8u * nranks + 63u) & ~63u;
  l.nLineageLines = lines;
  l.holdOff = l.lineageOff + 64u * lines;
  l.nHoldLines = lines;
  l.bytes = l.holdOff + 64u * lines;
  if (l.bytes > GDAKI_CTRL_PAGE_BYTES) return false;
  *out = l;
  return true;
}

// The byte offset in this rank's page of its consumed word for launcher i's messages (glPairBody.creditOff).
static inline uint32_t gdakiCtrlPageCreditOffL(const struct gdakiCtrlPageLayout& l, uint32_t i) {
  return l.rxConsumedLOff + 8u * i;
}

// ---- the launcher's side that a rank reads and writes (launcher/launcher_msg.h owns it; the coordinator's decision of
// 2026-10-17: its layout, not this header's) ----
// The launcher's page is glPage (4 KiB: line 0 magicVer, beat, monoMs, node, qkey, nRegs, nCredits; GL_PAGE_REGS slots
// glPageReg {nonce, registration word, spare word, spareSinceMs}; GL_PAGE_CREDITS slots glPageCredit {nonce, peer,
// consumed}), read with gl_page_word_state/_rank/_inc (registration states GL_RS_ALIVE 1, EXITED 2, LEFT 3, FENCED 4).
// The credit is per paired rank, not per registration: a rank on another node sends to a launcher it is not registered
// at. The rank side's half lives here: this rank's consumed count of each launcher's share is the rank page's
// rxConsumedL[i] (gdakiCtrlPageCreditOffL: the creditOff a rank puts in its glPairBody), and the launcher's of this rank's
// share is glPageCredit.consumed (GL_PAGE_CREDIT_OFF); both are gdakiCtrlGenCount words.
// What the launcher needs of the rank side (its README; the phases' contracts):
//   - the registering Unix connection stays open for the process's life, FD_CLOEXEC, and is closed in a forked child
//     (pthread_atfork): LEAVING counts only on that connection [3];
//   - every envelope's ackSeq carries this side's consumed count of the other side's messages [2, 3];
//   - the PAIR body to a launcher carries this rank's page and creditOff [3];
//   - this rank's launcher record QP has max_dest_rd_atomic >= 1 (the template's maxRdAtomic) and the outbox MR is
//     REMOTE_READ: the launcher READs the activation blob from it (gdakiCtrlQpAttrLauncher) [3];
//   - SPAWN's answer (GL_K_REFUSED, sub GL_K_SPAWN, "spawn not built") is never a reason for a fallback: report only;
//     only ACTIVATE's answers (GL_K_ACT_ANSWER) decide [3].

// ---- the host QP endpoint, version 2 (40 B; design v2 5.4: the REJOIN's nrp carries three of them) ----
// The same bytes as gin-mirror's struct gdakiMiQpEndpoint (version 1) but for its last 4 B (pad 0 there): the version
// and the QP type. UD: psn holds the Q_Key (a UD QP has no peer PSN).
#define GDAKI_CTRL_EP_VERSION 2u
#define GDAKI_CTRL_QPT_RC 2u  // IBV_QPT_RC (the host file asserts both)
#define GDAKI_CTRL_QPT_UD 4u  // IBV_QPT_UD
struct gdakiCtrlEndpoint {
  uint32_t qpn, psn;  // QP number; RC: the initial send PSN (fresh at every pairing), UD: the Q_Key
  uint32_t lid;
  int32_t mtu;        // enum ibv_mtu (the port's active MTU)
  uint8_t gid[16];    // RoCE/IB GID
  int32_t gidIndex;
  uint8_t version;    // GDAKI_CTRL_EP_VERSION (version 1: 0, its pad)
  uint8_t qpType;     // GDAKI_CTRL_QPT_RC or GDAKI_CTRL_QPT_UD
  uint16_t rsv;
};
static_assert(sizeof(struct gdakiCtrlEndpoint) == 40, "a host QP endpoint is 40 bytes");
static_assert(sizeof(struct gdakiCtrlEndpoint) == sizeof(struct gdakiMiQpEndpoint) &&
                  offsetof(struct gdakiCtrlEndpoint, gidIndex) == offsetof(struct gdakiMiQpEndpoint, gidIndex) &&
                  offsetof(struct gdakiCtrlEndpoint, version) == offsetof(struct gdakiMiQpEndpoint, pad),
              "version 2 keeps version 1's bytes");
static inline struct gdakiCtrlEndpoint gdakiCtrlEndpointOf(const struct gdakiMiQpEndpoint& v1, uint32_t qpType) {
  struct gdakiCtrlEndpoint e;
  memcpy(&e, &v1, sizeof(e));
  e.version = (uint8_t)GDAKI_CTRL_EP_VERSION;
  e.qpType = (uint8_t)qpType;
  e.rsv = 0;
  return e;
}
static inline struct gdakiMiQpEndpoint gdakiCtrlEndpointV1(const struct gdakiCtrlEndpoint& e) {
  struct gdakiMiQpEndpoint v1;
  memcpy(&v1, &e, sizeof(v1));
  v1.pad = 0;
  return v1;
}
// Well formed: version 2, a known type, a 24-bit QPN that is not 0, an MTU of enum ibv_mtu (1..5); UD needs >= 2048 (4).
static inline bool gdakiCtrlEndpointOk(const struct gdakiCtrlEndpoint& e) {
  if (e.version != GDAKI_CTRL_EP_VERSION || e.rsv != 0) return false;
  if (e.qpType != GDAKI_CTRL_QPT_RC && e.qpType != GDAKI_CTRL_QPT_UD) return false;
  if (e.qpn == 0 || e.qpn > 0xffffffu || e.mtu < 1 || e.mtu > 5) return false;
  if (e.qpType == GDAKI_CTRL_QPT_RC && e.psn > 0xffffffu) return false;
  return e.qpType != GDAKI_CTRL_QPT_UD || e.mtu >= 4;
}

// ---- the rank-rank pairing over UD (design v2 2.5, REVIEW2 막는 문제 4) ----
// One body for PAIR and PAIR_ACK, of one QP kind each: the record QP and the liveness READ QP pair separately (a record
// QP in ERR leaves the READ QP alone), each with its own generation and a fresh PSN at every pairing (an old
// generation's packet never lands in a new generation's RECV). Either side may start: the side that sees its QP in ERR
// sends PAIR(gen + 1); when both PAIRs of one (kind, gen) cross, the lower rank's wins (gdakiCtrlPairResolve). The PAIR
// also carries the sender's page and outbox (a stale rkey is mended by the pairing, REVIEW2 nit 8) and its UD Q_Key
// (where the answer goes, nit 9).
enum : uint32_t { GDAKI_CTRL_PAIR_QP_RECORD = 1, GDAKI_CTRL_PAIR_QP_PROBE = 2 };
enum : uint32_t { GDAKI_CTRL_PAIR_STEP_PAIR = 1, GDAKI_CTRL_PAIR_STEP_ACK = 2 };
struct gdakiCtrlPairBody {
  uint32_t qpKind;       // GDAKI_CTRL_PAIR_QP_*
  uint32_t step;         // GDAKI_CTRL_PAIR_STEP_*
  uint32_t gen;          // the pairing's generation of this QP kind (the envelope's gen is the same)
  uint32_t incarnation;  // the sender's
  int32_t from, to;      // ranks
  uint64_t nonce;
  struct gdakiCtrlEndpoint qp;  // the sender's QP of that kind (PAIR: INIT with its RECVs posted; ACK: RTS), fresh PSN
  struct gdakiCtrlEndpoint ud;  // the sender's UD QP (psn = its Q_Key)
  struct gdakiCtrlRegion page, outbox;
};
static_assert(sizeof(struct gdakiCtrlPairBody) == 144 && sizeof(struct gdakiCtrlPairBody) <= GDAKI_CTRL_RECORD_BYTES,
              "the pairing body fits a datagram");
// What a received PAIR(kind, gen) does at a side whose current generation of that kind is `cur` and which itself may
// have a PAIR(kind, mineGen) outstanding (mineGen 0: none).
enum : uint32_t { GDAKI_CTRL_PAIR_TAKE = 0, GDAKI_CTRL_PAIR_KEEP_MINE = 1, GDAKI_CTRL_PAIR_STALE = 2,
                  GDAKI_CTRL_PAIR_REPEAT = 3 };
static inline uint32_t gdakiCtrlPairResolve(int myRank, int peerRank, uint32_t cur, uint32_t mineGen, uint32_t theirGen,
                                            bool answeredTheirs) {
  if (theirGen < cur) return GDAKI_CTRL_PAIR_STALE;
  if (theirGen == cur) return answeredTheirs ? GDAKI_CTRL_PAIR_REPEAT : GDAKI_CTRL_PAIR_STALE;  // the same answer again
  if (mineGen != 0 && mineGen >= theirGen && myRank < peerRank) return GDAKI_CTRL_PAIR_KEEP_MINE;
  return GDAKI_CTRL_PAIR_TAKE;
}

// ---- the REJOIN's and REJOIN_ACK's nrp (design v2 5.4; REVIEW2 1절 B3: both leave gdakiTsMsg::nrp unused, 10146-10166,
// 9563-9570) ----
// REJOIN (spare -> survivor): its record QP and liveness READ QP (INIT, RECVs posted, fresh PSNs), its UD QP, its page
// and outbox. REJOIN_ACK (survivor -> spare): the survivor's two QPs (RTR toward those, fresh PSNs), its page and outbox
// (its UD QP is known from the activation blob).
#define GDAKI_CTRL_NRP_VERSION 1u
struct gdakiCtrlRejoinNrp {
  uint32_t version;  // GDAKI_CTRL_NRP_VERSION; 0: nothing here (a tcp-path REJOIN)
  uint32_t gen;      // the record QP pairing's generation the REJOIN starts (the survivor's next)
  struct gdakiCtrlEndpoint rec, probe, ud;
  struct gdakiCtrlRegion page, outbox;
};
static_assert(sizeof(struct gdakiCtrlRejoinNrp) == 160, "the REJOIN nrp layout is 160 bytes");
#define GDAKI_CTRL_NRP_BYTES 256u  // gdakiTsMsg::nrp: NCCL_GIN_RECOVERY_MAX_QPS x 4 B (the host file asserts it)
static_assert(sizeof(struct gdakiCtrlRejoinNrp) <= GDAKI_CTRL_NRP_BYTES, "it fits gdakiTsMsg::nrp");

// ---- the confirmation window (REVIEW2 막는 문제 3; 9.3) ----
// Opened by a witness FIN or RST without a BYE (a record QP in ERR opens it for the report only): at t_F READ1 of line
// 0, at t_F + W/2 READ2, the verdict at t_F + W. Only READs posted on a liveness READ QP that is RTS and had one success
// in its generation count (REVIEW2 고칠 것 9); else the window cannot confirm.
enum : uint32_t {
  GDAKI_CTRL_CW_ALIVE = 0,        // both READs done, the beat rose
  GDAKI_CTRL_CW_STALE = 1,        // the beat did not change: FIN+STALE
  GDAKI_CTRL_CW_NORESP = 2,       // a READ not done by t_F + W: FIN+NORESP
  GDAKI_CTRL_CW_REMACC = 3,       // a remote access error: REMACC+FIN
  GDAKI_CTRL_CW_UNCONFIRMED = 4,  // no countable READ (the QP not RTS, never a success in its generation)
};
static inline uint32_t gdakiCtrlConfirmVerdict(bool countable, bool remacc, bool read1Done, bool read2Done, uint64_t beat1,
                                               uint64_t beat2) {
  if (!countable) return GDAKI_CTRL_CW_UNCONFIRMED;
  if (remacc) return GDAKI_CTRL_CW_REMACC;
  if (!read1Done || !read2Done) return GDAKI_CTRL_CW_NORESP;
  return beat2 != beat1 ? GDAKI_CTRL_CW_ALIVE : GDAKI_CTRL_CW_STALE;
}

// ---- the widened host QP template's attributes (gdakiMiHostQpCreate, 16457; gdakiMiHostQpConnect, 16526) ----
// The defaults are ln4's values: an RC QP, SQ GDAKI_MI_HOSTQP_DEPTH (64), RQ 1, a CQ of its own of 2 x 64 without a
// channel, the access bits LOCAL_WRITE | REMOTE_WRITE | REMOTE_READ; RTS timeout 12, retry_cnt 7, rnr_retry 7,
// min_rnr_timer 12. Lifetime (REVIEW2 고칠 것 5): a CQ of its own carries the QP's ncclIbStats as cq_context (ln4); an
// owner thread's CQ (`cq`) carries its own stats (gdakiCtrlCqCreate), outlives every QP on it and is destroyed after
// them; the async-event thread dereferences either. A QP on an owner thread's CQ is never handed to gdakiMiHostQpXfer
// (it polls q->cq as its own): that CQ's owner polls it.
#define GDAKI_CTRL_ACC_LOCAL_WRITE 0x1u   // IBV_ACCESS_LOCAL_WRITE (the host file asserts the three)
#define GDAKI_CTRL_ACC_REMOTE_WRITE 0x2u  // IBV_ACCESS_REMOTE_WRITE
#define GDAKI_CTRL_ACC_REMOTE_READ 0x4u   // IBV_ACCESS_REMOTE_READ
#define GDAKI_CTRL_HOSTQP_SQ_LN4 64u      // = GDAKI_MI_HOSTQP_DEPTH (asserted)
struct gdakiCtrlQpAttr {
  uint32_t qpType = GDAKI_CTRL_QPT_RC;
  uint32_t sqDepth = GDAKI_CTRL_HOSTQP_SQ_LN4;
  uint32_t rqDepth = 1;
  uint32_t cqDepth = 2u * GDAKI_CTRL_HOSTQP_SQ_LN4;  // a CQ of its own; ignored with `cq`
  void* cq = nullptr;       // an owner thread's struct ibv_cq* (design v2 2.1: one per thread), or null: a CQ of its own
  void* channel = nullptr;  // a struct ibv_comp_channel* for a CQ of its own (ignored with `cq`: the owner's CQ has its)
  uint32_t access = GDAKI_CTRL_ACC_LOCAL_WRITE | GDAKI_CTRL_ACC_REMOTE_WRITE | GDAKI_CTRL_ACC_REMOTE_READ;
  uint32_t qkey = 0;        // UD only
  uint8_t timeout = 12, retryCnt = 7, rnrRetry = 7, minRnrTimer = 12;
};
static inline bool gdakiCtrlQpAttrIsLn4(const struct gdakiCtrlQpAttr& a) {
  const struct gdakiCtrlQpAttr d;
  return a.qpType == d.qpType && a.sqDepth == d.sqDepth && a.rqDepth == d.rqDepth && a.cqDepth == d.cqDepth &&
         a.cq == nullptr && a.channel == nullptr && a.access == d.access && a.qkey == d.qkey && a.timeout == d.timeout &&
         a.retryCnt == d.retryCnt && a.rnrRetry == d.rnrRetry && a.minRnrTimer == d.minRnrTimer;
}
// The record QP (EXPERIMENT.md 9.1's table): SQ 96 (K 64 + READ 16 + 16), RQ 64, REMOTE_READ only (a peer may READ the
// outbox and the consumed word, never write), timeout = NCCL_IB_TIMEOUT, retry_cnt 7, rnr_retry 3 (finite), the
// helper's CQ (max_rd_atomic 16 is the template's own argument).
#define GDAKI_CTRL_RECORD_SQ 96u
#define GDAKI_CTRL_RECORD_RQ 64u
#define GDAKI_CTRL_RNR_RETRY 3u
static inline struct gdakiCtrlQpAttr gdakiCtrlQpAttrRecord(uint8_t ibTimeout, void* helperCq) {
  struct gdakiCtrlQpAttr a;
  a.sqDepth = GDAKI_CTRL_RECORD_SQ;
  a.rqDepth = GDAKI_CTRL_RECORD_RQ;
  a.cq = helperCq;
  a.access = GDAKI_CTRL_ACC_REMOTE_READ;
  a.timeout = ibTimeout;
  a.retryCnt = 7;
  a.rnrRetry = GDAKI_CTRL_RNR_RETRY;
  return a;
}
// This rank's record QP to a launcher: the record QP's attributes (REMOTE_READ: the launcher READs the activation blob
// from the outbox, so the template's maxRdAtomic, which is max_dest_rd_atomic too, must be >= 1; it always is).
static inline struct gdakiCtrlQpAttr gdakiCtrlQpAttrLauncher(uint8_t ibTimeout, void* helperCq) {
  return gdakiCtrlQpAttrRecord(ibTimeout, helperCq);
}
// The liveness READ QP: SQ 4, RQ 0, REMOTE_READ only, the record QP's timeout, retry_cnt 7, the watch thread's CQ
// (max_rd_atomic 1).
#define GDAKI_CTRL_PROBE_SQ 4u
static inline struct gdakiCtrlQpAttr gdakiCtrlQpAttrProbe(uint8_t ibTimeout, void* watchCq) {
  struct gdakiCtrlQpAttr a;
  a.sqDepth = GDAKI_CTRL_PROBE_SQ;
  a.rqDepth = 0;
  a.cqDepth = 2u * GDAKI_CTRL_PROBE_SQ;
  a.cq = watchCq;
  a.access = GDAKI_CTRL_ACC_REMOTE_READ;
  a.timeout = ibTimeout;
  a.retryCnt = 7;
  a.rnrRetry = GDAKI_CTRL_RNR_RETRY;
  return a;
}
// The context's UD QP: SQ 64, RQ 64, no access bits, the Q_Key (the low 31 bits of the context's nonce), the helper's CQ.
#define GDAKI_CTRL_UD_SQ 64u
#define GDAKI_CTRL_UD_RQ 64u
static inline uint32_t gdakiCtrlQkeyOf(uint64_t nonce) { return (uint32_t)nonce & 0x7fffffffu; }
static inline struct gdakiCtrlQpAttr gdakiCtrlQpAttrUd(uint32_t qkey, void* helperCq) {
  struct gdakiCtrlQpAttr a;
  a.qpType = GDAKI_CTRL_QPT_UD;
  a.sqDepth = GDAKI_CTRL_UD_SQ;
  a.rqDepth = GDAKI_CTRL_UD_RQ;
  a.cq = helperCq;
  a.access = 0;
  a.qkey = qkey;
  return a;
}
// The owner threads' CQs (design v2 2.1): the helper's takes every record and launcher QP's SQ and RQ and the UD QP's;
// the watch thread's the liveness READ QPs'. An overrun puts every QP of the CQ in ERR: a context that does not fit
// stays fail-fast (false).
#define GDAKI_CTRL_HELPER_CQ 1024u
#define GDAKI_CTRL_WATCH_CQ 64u
static inline bool gdakiCtrlCqFits(uint32_t nPeers, uint32_t nLaunchers) {
  const uint64_t helper = (uint64_t)(nPeers + nLaunchers) * (GDAKI_CTRL_RECORD_SQ + GDAKI_CTRL_RECORD_RQ) +
                          GDAKI_CTRL_UD_SQ + GDAKI_CTRL_UD_RQ;
  const uint64_t watch = (uint64_t)nPeers * GDAKI_CTRL_PROBE_SQ;
  return helper <= GDAKI_CTRL_HELPER_CQ && watch <= GDAKI_CTRL_WATCH_CQ;
}

// ---- what a swapped send is (gdakiCtrlSend's `ch`; impl/gc_sites.tsv has every site) ----
// The witness's sends are not swapped (they stay gdakiTsSend calls in both builds): there is no witness channel here.
enum : uint32_t {
  GDAKI_CTRL_CH_RECORD = 1,  // a record on the peer's installed helper socket; rdma: the pair's ring [2]
  GDAKI_CTRL_CH_REJOIN = 2,  // the spare's REJOIN dial and the survivor's REJOIN_ACK on it; rdma: UD [2]
  GDAKI_CTRL_CH_DATA = 3,    // a data connection's first record and the spare's STATE answer; rdma: outbox, store [2]
};
static inline const char* gdakiCtrlChName(uint32_t ch) {
  switch (ch) {
    case GDAKI_CTRL_CH_RECORD: return "record";
    case GDAKI_CTRL_CH_REJOIN: return "rejoin";
    case GDAKI_CTRL_CH_DATA: return "data";
    default: return "?";
  }
}

// ---- the per-context state (one member of struct gdakiRecHost: `struct gdakiCtrlState* ctrl`, null until used) ----
// Each phase allocates, uses and frees its own pointer only (gin-mirror's rule for struct gdakiMiState); gdakiCtrlFree
// [prep] runs at the context's teardown after the helper and the watch thread stopped.
struct gdakiCtrlPage;      // [1] this rank's status page, the probe state per peer, the judgement
struct gdakiCtrlRing;      // [2] the record QPs, the rings, the credit, the inboxes, the UD QP, the outbox
struct gdakiCtrlLauncher;  // [3] the node's launcher link (the Unix socket, the launcher QPs)
struct gdakiCtrlState {
  struct gdakiCtrlPage* page = nullptr;
  struct gdakiCtrlRing* ring = nullptr;
  struct gdakiCtrlLauncher* launcher = nullptr;
};
// The liveness READ QP of one pair (the API below).
struct gdakiMiHostQp;
struct gdakiProbeQp {
  struct gdakiMiHostQp* q = nullptr;
  struct gdakiCtrlEndpoint local;  // version 2, RC; its psn is fresh at the create and at every reconnect
  struct gdakiCtrlEndpoint remote;
  int peer = -1;
  uint32_t gen = 0;                // the READ QP pairing's generation (GDAKI_CTRL_PAIR_QP_PROBE)
  bool connected = false;
};
#endif  // !NCCL_GIN_CTRL_TCP
// ---- gin-control: ctrl API (end) ----
// ---- gin-control: ctrl seams (begin; impl/rs_ctrl_api.h, byte for byte) ----
#if NCCL_GIN_CTRL_TCP
// The regression arm: every swap point is today's call, every hook nothing (the preprocessed output is ln4's).
#define gdakiCtrlSend(r, peer, ch, fd, m, timeoutMs) gdakiTsSend(fd, m, timeoutMs)
#define gdakiCtrlPump(r, peer, pe, out) gdakiTsPump(pe, out)
#define gdakiProbeQpCreate(r, peer, out, why, whyLen) (ncclSuccess)
#define gdakiProbeQpEndpoint(q, out) ((void)0)
#define gdakiProbeQpConnect(q, remote, gen, why, whyLen) (ncclSuccess)
#define gdakiProbeQpReconnect(q, remote, gen, why, whyLen) (ncclSuccess)
#define gdakiProbeQpIsRts(q) (false)
#define gdakiProbeQpDestroy(q) ((void)0)
#define gdakiProbeToErr(r, peer) ((void)0)
#define gdakiCtrlRecordToErr(r, peer) ((void)0)
#define gdakiStoreWardToErr(r, peer) ((void)0)
#define gdakiCtrlPeerToErr(r, peer) ((void)0)
#define gdakiCtrlOnHoldStart(r, peer, inc) ((void)0)
#define gdakiCtrlLauncherSend(r, node, msg, bytes) (-1)
#define gdakiLnFenced(r, peer, inc) ((void)0)
#else
#ifndef GDAKI_CTRL_API_NO_ENTRY_DECLS
struct gdakiRecHost;  // the host file
struct gdakiTsMsg;    // the host file
struct gdakiTsPeer;   // the host file
// [prep] Send one record on `fd` (the TCP back end's socket) toward `peer` (-1: none), as `ch` says; 0 sent, -1 not
// (gdakiTsSend's contract: bounded by timeoutMs, magic filled in). The preparation stage: the TCP back end for every ch.
static int gdakiCtrlSend(struct gdakiRecHost* r, int peer, uint32_t ch, int fd, struct gdakiTsMsg* m, int timeoutMs);
// [prep] Read what is there of `peer`'s record channel (gdakiTsPump's contract: 1 a whole record in *out, 0 not yet, -1
// FIN, error or bad magic with pe.closeCause). The preparation stage: the TCP back end.
static int gdakiCtrlPump(struct gdakiRecHost* r, int peer, struct gdakiTsPeer& pe, struct gdakiTsMsg* out);
// [prep] The liveness READ QP of (this rank, peer) on the widened template (gdakiCtrlQpAttrProbe: NCCL_IB_TIMEOUT; a CQ
// of its own until phase 1 hands the watch thread's): created in INIT with a fresh PSN, its endpoint version 2,
// connected RTR/RTS for pairing generation `gen`, reconnected (ERR or RTS -> RESET -> INIT -> RTR/RTS with a new fresh
// PSN, the new endpoint in q->local: send it in the new PAIR), asked whether it is RTS (the confirmation window counts
// only such READs), destroyed.
static ncclResult_t gdakiProbeQpCreate(struct gdakiRecHost* r, int peer, struct gdakiProbeQp* out, char* why, size_t whyLen);
static void gdakiProbeQpEndpoint(const struct gdakiProbeQp* q, struct gdakiCtrlEndpoint* out);
static ncclResult_t gdakiProbeQpConnect(struct gdakiProbeQp* q, const struct gdakiCtrlEndpoint* remote, uint32_t gen,
                                        char* why, size_t whyLen);
static ncclResult_t gdakiProbeQpReconnect(struct gdakiProbeQp* q, const struct gdakiCtrlEndpoint* remote, uint32_t gen,
                                          char* why, size_t whyLen);
static bool gdakiProbeQpIsRts(const struct gdakiProbeQp* q);
static void gdakiProbeQpDestroy(struct gdakiProbeQp* q);
// [1] the liveness READ QP to `peer` into ERR through the watch thread (its request word; design v2 2.1's handoff).
static void gdakiProbeToErr(struct gdakiRecHost* r, int peer);
// [2] the record QP to `peer` into ERR; [2] the store's responder QP of ward `peer` into ERR (9.4 step 1).
static void gdakiCtrlRecordToErr(struct gdakiRecHost* r, int peer);
static void gdakiStoreWardToErr(struct gdakiRecHost* r, int peer);
// [prep] the frame: every control QP toward `peer` into ERR (the three above). The hold start calls it after the quiesce
// moved the user and mirror QPs to ERR and before HOLDING (the fence's step 1, EXPERIMENT.md 9.4).
static void gdakiCtrlPeerToErr(struct gdakiRecHost* r, int peer);
// [3] the hold start's hook (the launcher's SPAWN; the hold start calls it after gdakiCtrlPeerToErr). Never blocks
// (one WR); its answer (GL_K_REFUSED with sub GL_K_SPAWN) is never a reason for a fallback.
static void gdakiCtrlOnHoldStart(struct gdakiRecHost* r, int peer, uint32_t inc);
// [3] one launcher message (launcher/launcher_msg.h, `bytes` of it) to the launcher of `node`; 0 sent, -1 not (no
// launcher: the preparation stage and phase 1 alone). Its envelope's ackSeq carries this rank's consumed count of that
// launcher's messages.
static int gdakiCtrlLauncherSend(struct gdakiRecHost* r, int node, const void* msg, size_t bytes);
// [1] FENCED(peer, inc): the fence word of `peer` = gdakiCtrlFenceWord(inc) (design v2 4.4, REVIEW2 막는 문제 1).
static void gdakiLnFenced(struct gdakiRecHost* r, int peer, uint32_t inc);
#endif  // GDAKI_CTRL_API_NO_ENTRY_DECLS
#endif  // NCCL_GIN_CTRL_TCP
// ---- gin-control: ctrl seams (end) ----

// ---- outside the blocks: the launcher's copies (when launcher/launcher_msg.h is present) ----
#if defined(GDAKI_CTRL_HAVE_LAUNCHER_MSG) && !NCCL_GIN_CTRL_TCP
static_assert(sizeof(struct glCtrlEnv) == sizeof(struct gdakiCtrlEnv) && GL_ENV_MAGIC == GDAKI_CTRL_ENV_MAGIC &&
                  GL_WIRE_VERSION == GDAKI_CTRL_ENV_VERSION && GL_FROM_LAUNCHER == GDAKI_CTRL_FROM_LAUNCHER,
              "launcher_msg.h's envelope is this one");
static_assert(offsetof(struct glCtrlEnv, from) == offsetof(struct gdakiCtrlEnv, from) &&
                  offsetof(struct glCtrlEnv, gen) == offsetof(struct gdakiCtrlEnv, gen) &&
                  offsetof(struct glCtrlEnv, seq) == offsetof(struct gdakiCtrlEnv, seq) &&
                  offsetof(struct glCtrlEnv, ackSeq) == offsetof(struct gdakiCtrlEnv, ackSeq) &&
                  offsetof(struct glCtrlEnv, nonce) == offsetof(struct gdakiCtrlEnv, nonce) &&
                  offsetof(struct glCtrlEnv, incarnation) == offsetof(struct gdakiCtrlEnv, incarnation) &&
                  offsetof(struct glCtrlEnv, bodyBytes) == offsetof(struct gdakiCtrlEnv, bodyBytes),
              "launcher_msg.h's envelope offsets are this one's");
static_assert((int)GL_ENV_KIND_RECORD == (int)GDAKI_CTRL_K_RECORD && (int)GL_ENV_KIND_XFER == (int)GDAKI_CTRL_K_XFER &&
                  (int)GL_ENV_KIND_XFER_DONE == (int)GDAKI_CTRL_K_XFER_DONE &&
                  (int)GL_ENV_KIND_LAUNCHER == (int)GDAKI_CTRL_K_LAUNCHER && (int)GL_ENV_KIND_PAIR == (int)GDAKI_CTRL_K_PAIR,
              "launcher_msg.h's envelope kinds are this one's");
static_assert(sizeof(struct glMsg) == GDAKI_CTRL_LAUNCHER_BYTES, "the launcher's message is 256 B");
static_assert(sizeof(struct glEp) == sizeof(struct gdakiCtrlEndpoint) &&
                  offsetof(struct glEp, gidIndex) == offsetof(struct gdakiCtrlEndpoint, gidIndex) &&
                  offsetof(struct glEp, version) == offsetof(struct gdakiCtrlEndpoint, version) &&
                  offsetof(struct glEp, qpType) == offsetof(struct gdakiCtrlEndpoint, qpType) &&
                  GL_EP_VERSION == GDAKI_CTRL_EP_VERSION && GL_QPT_RC == GDAKI_CTRL_QPT_RC && GL_QPT_UD == GDAKI_CTRL_QPT_UD,
              "launcher_msg.h's endpoint is this one (version 2, the QP type in the last 4 B)");
static_assert(sizeof(((struct glPageCredit*)nullptr)->consumed) == 8 && sizeof(struct glPage) == GDAKI_CTRL_PAGE_BYTES,
              "the launcher's consumed word is one 8 B word on a 4 KiB page");
static_assert(sizeof(struct glRegion) == sizeof(struct gdakiCtrlRegion) &&
                  offsetof(struct glRegion, rkey) == offsetof(struct gdakiCtrlRegion, rkey) &&
                  offsetof(struct glRegion, len) == offsetof(struct gdakiCtrlRegion, len),
              "launcher_msg.h's region is this one");
#endif

#endif  // GIN_CONTROL_RS_CTRL_API_H_
