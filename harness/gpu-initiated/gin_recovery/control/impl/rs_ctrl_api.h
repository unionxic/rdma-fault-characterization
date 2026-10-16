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
//        record reads. The sixth (gdakiTsRecv's, 8267) is the TCP back end's bare-socket helper and stays.
//   gdakiCtrlRecv(r, peer, pe, out, timeoutMs, stop)  [prep] 3 of ln4's 6 gdakiTsRecv calls (REVIEW_PREP 막는 문제 1):
//        the responder's DONE wait (11896), the initiator's ACK wait without serving (12024), the MIRROR_SETUP wait
//        (22372). The others are the witness's accepts (8765 also takes a DATA or a REJOIN first record: phase 2 adds
//        the UD and outbox ways beside it, the accept stays the witness's; 18148) and gdakiRsRecvOn's body (9961).
//   gdakiCtrlRecvOn(r, peer, ch, fd, out, timeoutMs, stop)  [prep] the spare's 3 gdakiRsRecvOn calls: REJOIN_ACK
//        (10192, _REJOIN), TOKEN (10235) and DONE_RS (10297, _RECORD); `fd` is the TCP back end's socket.
//   gdakiCtrlRejoinFail(r, fd, peer, round, what)  [prep] the FAIL answer to a declined rank's REJOIN (8777 on the listen
//        socket, 9536 at the park's acceptance): gdakiTsAnswerFail's two REJOIN calls; its other two (a re-dial 8815, a
//        PROBE 8785) are the witness's.
//   the record channel's state (REVIEW_PREP 막는 문제 2; the rdma build's functions, the tcp build keeps ln4's text at
//        each site under #if NCCL_GIN_CTRL_TCP / #else):
//        gdakiCtrlChanUp(r, peer, pe)  [prep] "the record channel to peer is up" at 19 sites (ln4: pe.fd >= 0 && !pe.gone,
//            or pe.fd >= 0 alone at 10306, 22339, 22372: equal there, see impl/gc_sites.tsv); gdakiCtrlChanUp(r, peer)
//            is the same through r->ts (valid once r->ts is set: not inside gdakiMiSetupEnd);
//        gdakiCtrlChanGen(r, peer, pe)  [prep] the channel's generation a kept REQ came on (11984, 17768; ln4 pe.gen);
//        gdakiCtrlPollFd(r, peer, pe)  [prep] the fd that poll and the MSG_PEEK test wait on (11950, 12035, 12041; ln4
//            pe.fd; a negative value: poll ignores the entry, the peek fails and the pump reads);
//        gdakiCtrlChanInstall(r, peer, pe, fd)  [prep] the spare installs the accepted REJOIN socket (10208; ln4 pe.fd = fd).
//        A send's TCP back end argument stays ln4's pe.fd (gdakiCtrlSend's `fd`); the witness's uses stay pe.fd.
//   gdakiMiHostQpCreate(..., const struct gdakiCtrlQpAttr& attr = gdakiCtrlQpAttr())  [prep] widened (QP type, SQ, RQ
//        and CQ depth, an owner thread's CQ, a completion channel, access bits, Q_Key; the RTS timeout, retry_cnt,
//        rnr_retry and min_rnr_timer that gdakiMiHostQpConnect sets): the defaults are ln4's values (the store's and the
//        FETCH's QPs are unchanged). gdakiCtrlCqCreate/Destroy [prep]: an owner thread's CQ with stats of its own.
//   gdakiTsSetup -> gdakiTsSetup (the all-gather and the agreement) + gdakiTsSetupConnect (the connect and the rest)
//        [prep split; 2 owns gdakiTsSetupConnect's pairing, MTU and fork checks].
//   gdakiRsSpareRun -> gdakiRsSpareActivateWait [3] + gdakiRsSpareRejoinAll [2] + the RESTORED tail [prep].
//   gdakiHoldActivate -> gdakiHoldActivateDecide [prep] + gdakiHoldActivateSend [3]; the decision's last condition
//        gdakiCtrlActFenceOk(r, peer, dead) [1] (design v3 4.4 5: FENCED, fencedPlus1 = dead + 1; true until phase 1).
//   the liveness READ QP: gdakiProbeQpCreate, gdakiProbeQpEndpoint, gdakiProbeQpConnect, gdakiProbeQpReconnect (RESET,
//        a fresh PSN, connected again on its own: the record QP's pairing does not touch it, REVIEW2 막는 문제 4),
//        gdakiProbeQpIsRts (software state, no QUERY_QP), gdakiProbeQpOkInGen and gdakiProbeQpOnSuccess (the "one
//        success in this generation" mark the confirmation window counts on), gdakiProbeQpQueryState (QUERY_QP: setup
//        and diagnostics only, never the watch thread's step), gdakiProbeQpDestroy [prep, on the template];
//        gdakiProbeToErr [1] (a placeholder until then).
//   hooks: gdakiCtrlPeerToErr [prep frame: gdakiCtrlRecordToErr [2], gdakiProbeToErr [1], gdakiStoreWardToErr [2]],
//        called at the hold start after the quiesce; gdakiCtrlOnHoldStart [3] (SPAWN), called there too;
//        gdakiCtrlLauncherSend [3] (phase 1 calls it; empty before); gdakiLnFenced [1] (FENCED into the fence word).
//   struct gdakiCtrlState: one pointer member `ctrl` of struct gdakiRecHost, made by the rdma gdakiTsSetup before the
//        connect (every process that reaches the connect has it; null before and in a context without the helper);
//        each phase owns one pointer below it and frees it in its own hook (gdakiCtrlPageFree [1], gdakiCtrlRingFree
//        [2], gdakiCtrlLauncherFree [3]) that gdakiCtrlFree [prep] calls in that order.
//   Each block below has an empty sub-block per phase ("[1] page", "[2] ring", "[3] launcher"): a phase adds its
//   declarations there and nowhere else in the blocks, so the three phases never edit the same lines (REVIEW_PREP 고칠 것
//   8); the host file's preparation region has the same three sub-regions with the placeholders each phase replaces.
//   In the tcp build every one of these is a macro: the swap points today's calls, the rest no-ops (or nothing: the
//   rdma-only seams appear only in #else branches).
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
#include <atomic>  // the receive seams' stop flag (the host file has it)

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
#if NCCL_GIN_CTRL_TCP_CELLS && !NCCL_GIN_CTRL_TCP
#error "NCCL_GIN_CTRL_TCP_CELLS is the tcp control cells' addition: it needs NCCL_GIN_CTRL_TCP=1 (key gctc)"
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
#define GDAKI_CTRL_P_LAUNCHER_STALL_MS "GIN_CTRL_LAUNCHER_STALL_MS"  // [3] the launcher page's beat stale this long (or
#define GDAKI_CTRL_LAUNCHER_STALL_MS_DEFAULT 1000                    //     its QP in ERR): the launcher is lost (v3 4.3)
#define GDAKI_CTRL_P_LATER_MS "GIN_CTRL_LATER_MS"            // [3] the buddy's bound after LATER: ABORT and the fallback
#define GDAKI_CTRL_LATER_MS_DEFAULT 5000                     //     draft; the value is the user decision list's (v3 6.3)
// The tcp control cells only [1] (behind NCCL_GIN_CTRL_TCP && NCCL_GIN_CTRL_TCP_CELLS): the refusal gap after an RST
// (ln4: the second refusal 1000 ms after the first; the user decision of 2026-10-16 night: default 1000, the RST cell 100).
#define GDAKI_CTRL_P_RST_REFUSAL_GAP_MS "GIN_TS_RST_REFUSAL_GAP_MS"
#define GDAKI_CTRL_RST_REFUSAL_GAP_MS_DEFAULT 1000

#if !NCCL_GIN_CTRL_TCP
// ---- the range check of the thresholds (9.3 "범위 검사", design v3 4.3; every rank the same values, at the setup) ----
// PROBE_MS = 0 (the cost cells: no periodic READ, no confirmation window) skips the W checks (v3 4.3).
struct gdakiCtrlThresholds {
  int64_t probeMs = GDAKI_CTRL_PROBE_MS_DEFAULT, probeTimeoutMs = GDAKI_CTRL_PROBE_TIMEOUT_MS_DEFAULT;
  int64_t confirmMs = GDAKI_CTRL_CONFIRM_MS_DEFAULT, suspectMs = GDAKI_CTRL_SUSPECT_MS_DEFAULT;
  int64_t stallMs = GDAKI_CTRL_STALL_MS_DEFAULT;
  int64_t restoreMs = 0;     // NCCL_GIN_RESTORE_MS (the caller fills it in)
  int64_t spareStartMs = 5000;  // NCCL_GIN_RESTORE_SPARE_START_MS
  int64_t launcherStallMs = GDAKI_CTRL_LAUNCHER_STALL_MS_DEFAULT, laterMs = GDAKI_CTRL_LATER_MS_DEFAULT;
};
static inline bool gdakiCtrlThresholdsOk(const struct gdakiCtrlThresholds& t, char* why, size_t whyLen) {
  const char* w = nullptr;
  if (t.probeMs < 0) w = "PROBE_MS < 0";
  else if (10 * t.probeMs > t.suspectMs) w = "10 x PROBE_MS > SUSPECT_MS";
  else if (t.suspectMs >= t.stallMs) w = "SUSPECT_MS >= STALL_MS";
  else if (t.stallMs + 1000 > t.restoreMs) w = "STALL_MS + 1000 > NCCL_GIN_RESTORE_MS";
  else if (t.probeTimeoutMs < 5 * t.probeMs) w = "PROBE_TIMEOUT_MS < 5 x PROBE_MS";
  else if (t.probeMs > 0 && t.confirmMs < GDAKI_CTRL_CONFIRM_MS_MIN) w = "CONFIRM_MS < 20";
  else if (t.probeMs > 0 && t.confirmMs >= t.probeTimeoutMs) w = "CONFIRM_MS >= PROBE_TIMEOUT_MS";
  else if (t.spareStartMs + 1000 > t.restoreMs) w = "SPARE_START_MS + 1000 > NCCL_GIN_RESTORE_MS";
  else if (t.probeMs > t.launcherStallMs) w = "PROBE_MS > LAUNCHER_STALL_MS";
  else if (t.laterMs + 1000 > t.restoreMs) w = "LATER_MS + 1000 > NCCL_GIN_RESTORE_MS";
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
  GDAKI_CTRL_K_PAIR = 5,       // UD only: rank-rank struct gdakiCtrlPairBody (144 B); rank-launcher: launcher_msg.h's glMsg
  GDAKI_CTRL_K_CONNECTED = 6,  // rank-rank record QP only, no body: the pairing starter's first RC SEND after its RTS
                               // (design v3 2.5 step 3; the other side sends nothing on that QP before it). It takes a
                               // RECV slot and seq 1 of the generation like a record and is never handed to the record
                               // layer (no record number: the new records stay 52-55). launcher_msg.h reserves 6 too;
                               // a launcher's CONNECTED is its GL_K_CONNECTED inside a LAUNCHER message.
};
#define GDAKI_CTRL_K_MAX 6u
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
  uint32_t bodyBytes;    // RECORD 1872, LAUNCHER 256, XFER and XFER_DONE 32, CONNECTED 0, PAIR 144 (a launcher's 256)
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
#define GDAKI_CTRL_PAIR_BODY_BYTES 144u  // sizeof(struct gdakiCtrlPairBody) (asserted below)
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
    case GDAKI_CTRL_K_CONNECTED: want = 0; break;
    default:  // PAIR: a rank's body or a launcher's message (REVIEW_PREP nit 3: nothing else)
      want = (e->bodyBytes == GDAKI_CTRL_PAIR_BODY_BYTES || e->bodyBytes == GDAKI_CTRL_LAUNCHER_BYTES) ? e->bodyBytes : ~0u;
      break;
  }
  if (want == ~0u || e->bodyBytes != want || received < sizeof(*e) + (size_t)want) return GDAKI_CTRL_ENV_BAD_BYTES;
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
// The word is 64-bit (design v3 4.4 4 says 32-bit: a 64-bit word keeps i + 1 from wrapping at i = 0xffffffff; the
// design follows this header, REVIEW_PREP nit 4).
static_assert(sizeof(gdakiCtrlFenceWord(0)) == 8, "the fence word is one 8 B word");
// The report name of the fence in the lineage's HOLD_WAIT (design v3 4.4 4; the lineage's phases are not touched): the
// view's phase and dead incarnation (gdakiLnView, rs_lineage_api.h; it follows these blocks in the host file, so its
// two fields come in by value), the fence word, and whether this rank sent FENCE for that dead incarnation. Outside
// HOLD_WAIT: NONE.
#define GDAKI_CTRL_LN_HOLD_WAIT 1u  // = GDAKI_LN_HOLD_WAIT (the host file's preparation region asserts it)
enum : uint32_t { GDAKI_LN_FENCE_NONE = 0, GDAKI_LN_FENCE_FENCING = 1, GDAKI_LN_FENCE_FENCED = 2 };
static inline uint32_t gdakiLnFenceOf(uint32_t viewPhase, uint32_t viewDead, uint64_t fencedPlus1, bool fenceSent) {
  if (viewPhase != GDAKI_CTRL_LN_HOLD_WAIT) return GDAKI_LN_FENCE_NONE;
  if (gdakiCtrlFencedIs(fencedPlus1, viewDead)) return GDAKI_LN_FENCE_FENCED;
  return fenceSent ? GDAKI_LN_FENCE_FENCING : GDAKI_LN_FENCE_NONE;
}
static inline const char* gdakiLnFenceName(uint32_t f) {
  switch (f) {
    case GDAKI_LN_FENCE_NONE: return "NONE";
    case GDAKI_LN_FENCE_FENCING: return "FENCING";
    case GDAKI_LN_FENCE_FENCED: return "FENCED";
    default: return "?";
  }
}

// ---- the judgement's inputs and result (design v3 4.2; the values here, the table is phase 1's gdakiCtrlJudge) ----
// L, the launcher (5 values); B, a BYE (2); W, the witness and the confirmation window (9); R, the liveness READ (13):
// 5 x 2 x 9 x 13 = 1 170 points, each of which phase 1's CPU model walks.
enum : uint32_t { GDAKI_CTRL_L_LEFT = 0, GDAKI_CTRL_L_ENDED = 1, GDAKI_CTRL_L_ALIVE = 2, GDAKI_CTRL_L_NOINFO = 3,
                  GDAKI_CTRL_L_NORESP = 4, GDAKI_CTRL_L_N = 5 };
enum : uint32_t { GDAKI_CTRL_B_NONE = 0, GDAKI_CTRL_B_SEEN = 1, GDAKI_CTRL_B_N = 2 };
enum : uint32_t { GDAKI_CTRL_W_OK = 0, GDAKI_CTRL_W_UNKNOWN = 1, GDAKI_CTRL_W_OFF = 2, GDAKI_CTRL_W_OPEN = 3,
                  GDAKI_CTRL_W_END_ALIVE = 4, GDAKI_CTRL_W_END_STALE = 5, GDAKI_CTRL_W_END_NORESP = 6,
                  GDAKI_CTRL_W_END_REMACC = 7, GDAKI_CTRL_W_END_UNCONFIRMED = 8, GDAKI_CTRL_W_N = 9 };
enum : uint32_t { GDAKI_CTRL_R_ROSE = 0, GDAKI_CTRL_R_STALE_LT_SUSPECT = 1, GDAKI_CTRL_R_STALE_SUSPECT = 2,
                  GDAKI_CTRL_R_STALE_GUARDED = 3, GDAKI_CTRL_R_STALL = 4, GDAKI_CTRL_R_HELPER_BUSY = 5,
                  GDAKI_CTRL_R_HELPER_SUSPECT = 6, GDAKI_CTRL_R_HELPER_GUARDED = 7, GDAKI_CTRL_R_HELPER_STALL = 8,
                  GDAKI_CTRL_R_REMACC = 9, GDAKI_CTRL_R_HW_NORESP = 10, GDAKI_CTRL_R_TIMEOUT_ONLY = 11,
                  GDAKI_CTRL_R_UNCONFIRMED = 12, GDAKI_CTRL_R_N = 13 };
// The verdicts (the table's 판정 column) and the causes (원인 이름; design v3 4.5: seven hold causes; LINKDOWN refuses).
enum : uint32_t { GDAKI_CTRL_V_NONE = 0, GDAKI_CTRL_V_LEFT = 1, GDAKI_CTRL_V_ENDED = 2, GDAKI_CTRL_V_WAIT = 3,
                  GDAKI_CTRL_V_ALIVE_WITNESS_LOST = 4, GDAKI_CTRL_V_UNREACHABLE = 5, GDAKI_CTRL_V_RDMA_PATH = 6,
                  GDAKI_CTRL_V_STALL = 7, GDAKI_CTRL_V_STALL_HELPER = 8, GDAKI_CTRL_V_SUSPECT = 9,
                  GDAKI_CTRL_V_HELPER_BUSY = 10, GDAKI_CTRL_V_ALIVE = 11 };
enum : uint32_t { GDAKI_CTRL_C_NONE = 0, GDAKI_CTRL_C_EXITED = 1, GDAKI_CTRL_C_FIN_STALE = 2, GDAKI_CTRL_C_FIN_NORESP = 3,
                  GDAKI_CTRL_C_REMACC_FIN = 4, GDAKI_CTRL_C_LINKDOWN = 5, GDAKI_CTRL_C_NORESP = 6, GDAKI_CTRL_C_STALL = 7,
                  GDAKI_CTRL_C_STALL_HELPER = 8 };
struct gdakiCtrlJudgement {
  uint32_t row = 21;  // the first matching row, 1..21 (21: no row above matched; the CPU model asserts no input gets here)
  uint32_t verdict = GDAKI_CTRL_V_NONE;
  uint32_t cause = GDAKI_CTRL_C_NONE;
};
// The signature (its body is phase 1's, in the "[1] page" sub-block below; a frame until then):
//   static inline struct gdakiCtrlJudgement gdakiCtrlJudge(uint32_t L, uint32_t B, uint32_t W, uint32_t R);

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
// number is a serial of the writer's own (REVIEW_PREP nit 2: a start time folded to a number could repeat): every start
// the watch thread sees that differs from the one before, or that follows a step it saw not busy, takes the next
// number (never 0). One tracker per page, written by the watch thread alone (no atomics needed).
struct gdakiCtrlBusyTrack {
  int64_t start = 0;  // the busy start the current number belongs to (0: not busy at the last call)
  uint32_t no = 0;    // the last number given
};
static inline uint64_t gdakiCtrlBusyOf(struct gdakiCtrlBusyTrack* t, int64_t busySinceUs, int64_t roundMs, int64_t fwSinceUs,
                                       int64_t fwMs) {
  if (busySinceUs <= 0 && fwSinceUs <= 0) {
    t->start = 0;
    return 0;
  }
  const int64_t start = busySinceUs > fwSinceUs ? busySinceUs : fwSinceUs;
  if (start != t->start) {
    t->start = start;
    t->no = t->no + 1u == 0 ? 1u : t->no + 1u;
  }
  int64_t bound = 0;
  if (busySinceUs > 0 && roundMs > bound) bound = roundMs;
  if (fwSinceUs > 0 && fwMs > bound) bound = fwMs;
  return gdakiCtrlBusyWord(t->no, bound > 0xffffffffll ? 0xffffffffu : (uint32_t)bound);
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
// rank) and as many of the hold summary (one word per peer). Rank 4 with 2 launchers: 320 B (design v2 3.1's 256 B is
// rank 4 without launchers; the launchers' two words push the report lines one line down). False beyond one page.
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
// Steps (REVIEW_PREP 고칠 것 5, design v3 2.5 step 3): PAIR, PAIR_ACK, and PAIR_DONE (the starter's last datagram for a
// liveness READ QP, the same body: the answerer READs from it on, or 500 ms after its PAIR_ACK). A record QP has no
// PAIR_DONE: the starter's first RC SEND on it is the bodiless envelope GDAKI_CTRL_K_CONNECTED.
enum : uint32_t { GDAKI_CTRL_PAIR_STEP_PAIR = 1, GDAKI_CTRL_PAIR_STEP_ACK = 2, GDAKI_CTRL_PAIR_STEP_DONE = 3 };
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
static_assert(sizeof(struct gdakiCtrlPairBody) == GDAKI_CTRL_PAIR_BODY_BYTES &&
                  sizeof(struct gdakiCtrlPairBody) <= GDAKI_CTRL_RECORD_BYTES,
              "the pairing body is 144 B and fits a datagram");
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
// Both QP kinds pair with a generation of their own (design v3 2.5, 5.4 5: "two generations, 8 B"); the UD endpoint's
// psn is the sender's Q_Key. gdakiTsMsg::nrp is uint32_t[64]: never read this struct through a cast of it (aliasing and
// alignment); gdakiCtrlNrpPut and gdakiCtrlNrpGet copy the bytes (REVIEW_PREP 고칠 것 4).
#define GDAKI_CTRL_NRP_VERSION 1u
struct gdakiCtrlRejoinNrp {
  uint32_t version;   // GDAKI_CTRL_NRP_VERSION; 0: nothing here (a tcp-path REJOIN)
  uint32_t gen;       // the record QP pairing's generation the REJOIN starts (the survivor's next)
  struct gdakiCtrlEndpoint rec, probe, ud;
  struct gdakiCtrlRegion page, outbox;
  uint32_t probeGen;  // the liveness READ QP pairing's generation the REJOIN starts (its own counter)
  uint32_t rsv;
};
static_assert(sizeof(struct gdakiCtrlRejoinNrp) == 168, "the REJOIN nrp layout is 168 bytes");
#define GDAKI_CTRL_NRP_BYTES 256u  // gdakiTsMsg::nrp: NCCL_GIN_RECOVERY_MAX_QPS x 4 B (the host file asserts it)
static_assert(sizeof(struct gdakiCtrlRejoinNrp) <= GDAKI_CTRL_NRP_BYTES, "it fits gdakiTsMsg::nrp");
// Into a record's nrp (nrpBytes = sizeof(gdakiTsMsg::nrp)): the layout, the rest zero. False when it does not fit.
static inline bool gdakiCtrlNrpPut(void* nrp, size_t nrpBytes, const struct gdakiCtrlRejoinNrp& n) {
  if (nrp == nullptr || nrpBytes < sizeof(n)) return false;
  memset(nrp, 0, nrpBytes);
  memcpy(nrp, &n, sizeof(n));
  return true;
}
// Out of a record's nrp: true with a layout of this version (version 0: the tcp path's empty nrp, false).
static inline bool gdakiCtrlNrpGet(const void* nrp, size_t nrpBytes, struct gdakiCtrlRejoinNrp* out) {
  if (nrp == nullptr || out == nullptr || nrpBytes < sizeof(*out)) return false;
  memcpy(out, nrp, sizeof(*out));
  return out->version == GDAKI_CTRL_NRP_VERSION && out->rsv == 0;
}

// ---- the confirmation window (REVIEW2 막는 문제 3; design v3 4.2; 9.3) ----
// Opened only by a witness FIN or RST with no BYE on the ring or the witness; a record QP in ERR, a timeout or a remote
// access error never opens it (design v3: the floor rule). At t_F READ1 of line 0, at t_F + W/2 READ2, the verdict at
// t_F + W. Only READs posted on a liveness READ QP that is RTS and had one success in its generation count (REVIEW2 고칠
// 것 9); else the window cannot confirm. The order (design v3 4.2): REMACC, then NORESP, then a page of another process
// (incNonce of either READ not the expected one: cannot confirm), then the beat: READ2's watchBeat ahead of READ1's
// (wrapping compare: a beat that went back is not alive) alive, else STALE.
enum : uint32_t {
  GDAKI_CTRL_CW_ALIVE = 0,        // both READs done, the beat advanced
  GDAKI_CTRL_CW_STALE = 1,        // the beat did not advance: FIN+STALE
  GDAKI_CTRL_CW_NORESP = 2,       // a READ not done by t_F + W: FIN+NORESP
  GDAKI_CTRL_CW_REMACC = 3,       // a remote access error: REMACC+FIN
  GDAKI_CTRL_CW_UNCONFIRMED = 4,  // no countable READ, or a page of another process (incNonce)
};
// a ahead of b on a wrapping 64-bit counter
static inline bool gdakiCtrlBeatAdvanced(uint64_t b, uint64_t a) { return (int64_t)(a - b) > 0; }
static inline uint32_t gdakiCtrlConfirmVerdict(bool countable, bool remacc, bool read1Done, bool read2Done,
                                               uint64_t incExpected, uint64_t inc1, uint64_t inc2, uint64_t beat1,
                                               uint64_t beat2) {
  if (!countable) return GDAKI_CTRL_CW_UNCONFIRMED;
  if (remacc) return GDAKI_CTRL_CW_REMACC;
  if (!read1Done || !read2Done) return GDAKI_CTRL_CW_NORESP;
  if (inc1 != incExpected || inc2 != incExpected) return GDAKI_CTRL_CW_UNCONFIRMED;
  return gdakiCtrlBeatAdvanced(beat1, beat2) ? GDAKI_CTRL_CW_ALIVE : GDAKI_CTRL_CW_STALE;
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
// The owner threads' CQs (design v3 2.1): the helper's takes every record QP's and launcher record QP's SQ and RQ and
// the UD QP's; the watch thread's every liveness READ QP's SQ: one per peer and one per launcher (REVIEW_PREP 고칠 것 3;
// rank 4 with 2 launchers: 5 x 4 = 20). An overrun puts every QP of the CQ in ERR: a context that does not fit stays
// fail-fast (false).
#define GDAKI_CTRL_HELPER_CQ 1024u
#define GDAKI_CTRL_WATCH_CQ 64u
static inline uint64_t gdakiCtrlHelperCqNeed(uint32_t nPeers, uint32_t nLaunchers) {
  return (uint64_t)((uint64_t)nPeers + nLaunchers) * (GDAKI_CTRL_RECORD_SQ + GDAKI_CTRL_RECORD_RQ) + GDAKI_CTRL_UD_SQ +
         GDAKI_CTRL_UD_RQ;
}
static inline uint64_t gdakiCtrlWatchCqNeed(uint32_t nPeers, uint32_t nLaunchers) {
  return (uint64_t)((uint64_t)nPeers + nLaunchers) * GDAKI_CTRL_PROBE_SQ;
}
static inline bool gdakiCtrlCqFits(uint32_t nPeers, uint32_t nLaunchers) {
  return gdakiCtrlHelperCqNeed(nPeers, nLaunchers) <= GDAKI_CTRL_HELPER_CQ &&
         gdakiCtrlWatchCqNeed(nPeers, nLaunchers) <= GDAKI_CTRL_WATCH_CQ;
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

// the window's results are W's window ends in order (W = GDAKI_CTRL_W_END_ALIVE + the verdict)
static_assert(GDAKI_CTRL_W_END_ALIVE + GDAKI_CTRL_CW_ALIVE == GDAKI_CTRL_W_END_ALIVE &&
                  GDAKI_CTRL_W_END_ALIVE + GDAKI_CTRL_CW_STALE == GDAKI_CTRL_W_END_STALE &&
                  GDAKI_CTRL_W_END_ALIVE + GDAKI_CTRL_CW_NORESP == GDAKI_CTRL_W_END_NORESP &&
                  GDAKI_CTRL_W_END_ALIVE + GDAKI_CTRL_CW_REMACC == GDAKI_CTRL_W_END_REMACC &&
                  GDAKI_CTRL_W_END_ALIVE + GDAKI_CTRL_CW_UNCONFIRMED == GDAKI_CTRL_W_END_UNCONFIRMED,
              "W's window ends are the confirmation window's results");

// ---- the per-context state (one member of struct gdakiRecHost: `struct gdakiCtrlState* ctrl`) ----
// Made by the rdma gdakiTsSetup before its connect part (gdakiTsSetupConnect; the setup thread, before the helper and
// the watch thread start), so every process that reaches the connect has it, a spare too; null before and in a context
// without the helper (check it). Each phase allocates, uses and frees its own pointer only (gin-mirror's rule for
// struct gdakiMiState), in its own free hook; gdakiCtrlFree [prep] runs at the context's teardown after the helper and
// the watch thread stopped and calls gdakiCtrlPageFree [1], gdakiCtrlRingFree [2], gdakiCtrlLauncherFree [3] in that
// order, then deletes the state.
struct gdakiCtrlPage;      // [1] this rank's status page, the probe state per peer, the judgement
struct gdakiCtrlRing;      // [2] the record QPs, the rings, the credit, the inboxes, the UD QP, the outbox
struct gdakiCtrlLauncher;  // [3] the node's launcher link (the Unix socket, the launcher QPs)
struct gdakiCtrlState {
  struct gdakiCtrlPage* page = nullptr;
  struct gdakiCtrlRing* ring = nullptr;
  struct gdakiCtrlLauncher* launcher = nullptr;
};
// The liveness READ QP of one pair (the API below). Its state is software, written by its owner thread alone (the watch
// thread once phase 1 hands it over; REVIEW_PREP 고칠 것 7, design v3 2.1): `connected` from the connect until an error
// or a reconnect; `okInGen` from the first successful READ completion of generation `gen` until the next reconnect or
// error. The confirmation window counts a READ only when gdakiProbeQpOkInGen; nothing on that path issues QUERY_QP (a
// firmware command: design v3 4.3, the W cells run without it).
struct gdakiMiHostQp;
struct gdakiProbeQp {
  struct gdakiMiHostQp* q = nullptr;
  struct gdakiCtrlEndpoint local;  // version 2, RC; its psn is fresh at the create and at every reconnect
  struct gdakiCtrlEndpoint remote;
  int peer = -1;
  uint32_t gen = 0;                // the READ QP pairing's generation (GDAKI_CTRL_PAIR_QP_PROBE)
  bool connected = false;
  bool okInGen = false;            // a READ of generation `gen` completed with success
};

// ---- [1] page: the status page, the liveness READ, the judgement, the fence (begin) ----
// gdakiCtrlJudge: a frame until phase 1 writes the table (design v3 4.2's 21 rows, first match wins).
static inline struct gdakiCtrlJudgement gdakiCtrlJudge(uint32_t L, uint32_t B, uint32_t W, uint32_t R) {
  (void)L;
  (void)B;
  (void)W;
  (void)R;
  return gdakiCtrlJudgement();
}
// ---- [1] page (end) ----
// ---- [2] ring: the record QPs, the rings, the UD pairing, the outbox (begin) ----
// ---- [2] ring (end) ----
// ---- [3] launcher: the rank side of the launcher (begin) ----
// ---- [3] launcher (end) ----
#endif  // !NCCL_GIN_CTRL_TCP
// ---- gin-control: ctrl API (end) ----
// ---- gin-control: ctrl seams (begin; impl/rs_ctrl_api.h, byte for byte) ----
#if NCCL_GIN_CTRL_TCP
// The regression arm: every swap point is today's call, every hook nothing (the preprocessed output is ln4's). The
// record channel's gdakiCtrlChanUp and gdakiCtrlChanGen have no tcp form: their sites keep ln4's text under
// #if NCCL_GIN_CTRL_TCP.
#define gdakiCtrlSend(r, peer, ch, fd, m, timeoutMs) gdakiTsSend(fd, m, timeoutMs)
#define gdakiCtrlPump(r, peer, pe, out) gdakiTsPump(pe, out)
#define gdakiCtrlRecv(r, peer, pe, out, timeoutMs, stop) gdakiTsRecv(pe, out, timeoutMs, stop)
#define gdakiCtrlRecvOn(r, peer, ch, fd, out, timeoutMs, stop) gdakiRsRecvOn(fd, out, timeoutMs, stop)
#define gdakiCtrlRejoinFail(r, fd, peer, round, what) gdakiTsAnswerFail(r, fd, peer, round, what)
#define gdakiCtrlPollFd(r, peer, pe) pe.fd
#define gdakiCtrlChanInstall(r, peer, pe, fd) pe.fd = fd
#define gdakiProbeQpCreate(r, peer, out, why, whyLen) (ncclSuccess)
#define gdakiProbeQpEndpoint(q, out) ((void)0)
#define gdakiProbeQpConnect(q, remote, gen, why, whyLen) (ncclSuccess)
#define gdakiProbeQpReconnect(q, remote, gen, why, whyLen) (ncclSuccess)
#define gdakiProbeQpIsRts(q) (false)
#define gdakiProbeQpOkInGen(q) (false)
#define gdakiProbeQpOnSuccess(q, gen) ((void)0)
#define gdakiProbeQpOnError(q) ((void)0)
#define gdakiProbeQpDestroy(q) ((void)0)
#define gdakiProbeToErr(r, peer) ((void)0)
#define gdakiCtrlRecordToErr(r, peer) ((void)0)
#define gdakiStoreWardToErr(r, peer) ((void)0)
#define gdakiCtrlPeerToErr(r, peer) ((void)0)
#define gdakiCtrlOnHoldStart(r, peer, inc) ((void)0)
#define gdakiCtrlLauncherSend(r, node, msg, bytes) (-1)
#define gdakiLnFenced(r, peer, inc) ((void)0)
#define gdakiCtrlActFenceOk(r, peer, dead) (true)
#else
#ifndef GDAKI_CTRL_API_NO_ENTRY_DECLS
struct gdakiRecHost;  // the host file
struct gdakiTsMsg;    // the host file
struct gdakiTsPeer;   // the host file
// ---- the swap points [prep bodies; phase 2 replaces them in the host file's "[2] ring" sub-region] ----
// Send one record on `fd` (the TCP back end's socket) toward `peer` (-1: none), as `ch` says; 0 sent, -1 not
// (gdakiTsSend's contract: bounded by timeoutMs, magic filled in). The preparation stage: the TCP back end for every ch.
static int gdakiCtrlSend(struct gdakiRecHost* r, int peer, uint32_t ch, int fd, struct gdakiTsMsg* m, int timeoutMs);
// Read what is there of `peer`'s record channel (gdakiTsPump's contract: 1 a whole record in *out, 0 not yet, -1 FIN,
// error or bad magic with pe.closeCause). The preparation stage: the TCP back end.
static int gdakiCtrlPump(struct gdakiRecHost* r, int peer, struct gdakiTsPeer& pe, struct gdakiTsMsg* out);
// Wait up to timeoutMs for one record of `peer`'s record channel (gdakiTsRecv's contract: 1 a record, 0 timeout or stop,
// -1 FIN or error). The preparation stage: gdakiTsRecv on pe (REVIEW_PREP 막는 문제 1).
static int gdakiCtrlRecv(struct gdakiRecHost* r, int peer, struct gdakiTsPeer& pe, struct gdakiTsMsg* out, int timeoutMs,
                         std::atomic<bool>* stop);
// The spare's wait for one record of `peer` on `fd` (the dial it holds), as `ch` says (_REJOIN: the REJOIN's answer,
// _RECORD: TOKEN and DONE_RS); gdakiRsRecvOn's contract. The preparation stage: gdakiRsRecvOn.
static int gdakiCtrlRecvOn(struct gdakiRecHost* r, int peer, uint32_t ch, int fd, struct gdakiTsMsg* out, int timeoutMs,
                           std::atomic<bool>* stop);
// The FAIL answer to a REJOIN of declined rank `peer` that came on `fd` (closes fd). The preparation stage:
// gdakiTsAnswerFail. Phase 2: the UD answer (and REJOIN's WAIT and REFUSE, which TCP told with a FIN; REVIEW_PREP 알릴 것 9).
static void gdakiCtrlRejoinFail(struct gdakiRecHost* r, int fd, int peer, uint64_t round, const char* what);
// The record channel to `peer` is up (the preparation stage: pe.fd >= 0 && !pe.gone; phase 2: the pair's record QP is
// CONNECTED and not lost, the witness's socket state aside). The two-argument form reads r->ts->peers[peer]: valid only
// once r->ts is set (not inside gdakiMiSetupEnd, which runs before; its sites use the three-argument form).
static bool gdakiCtrlChanUp(struct gdakiRecHost* r, int peer, const struct gdakiTsPeer& pe);
static bool gdakiCtrlChanUp(struct gdakiRecHost* r, int peer);
// The generation of `peer`'s record channel a kept REQ is tied to (the preparation stage: pe.gen, the helper socket's).
static uint32_t gdakiCtrlChanGen(struct gdakiRecHost* r, int peer, const struct gdakiTsPeer& pe);
// The fd poll() and the MSG_PEEK test wait on for `peer`'s records (the preparation stage: pe.fd; phase 2 may give the
// helper CQ's completion channel fd, or -1: poll ignores it and the peek fails, so the pump reads).
static int gdakiCtrlPollFd(struct gdakiRecHost* r, int peer, const struct gdakiTsPeer& pe);
// The spare installs the accepted REJOIN socket `fd` as `peer`'s record channel (the preparation stage: pe.fd = fd).
static void gdakiCtrlChanInstall(struct gdakiRecHost* r, int peer, struct gdakiTsPeer& pe, int fd);
// ---- the liveness READ QP [prep] ----
// The QP of (this rank, peer) on the widened template (gdakiCtrlQpAttrProbe: NCCL_IB_TIMEOUT; a CQ of its own until
// phase 1 hands the watch thread's): created in INIT with a fresh PSN, its endpoint version 2, connected RTR/RTS for
// pairing generation `gen`, reconnected (ERR or RTS -> RESET -> INIT -> RTR/RTS with a new fresh PSN, the new endpoint in
// q->local: send it in the new PAIR), destroyed. Its state is software (struct gdakiProbeQp): gdakiProbeQpIsRts (connected,
// no error seen), gdakiProbeQpOkInGen (and one success in this generation), gdakiProbeQpOnSuccess (a success completion
// of generation `gen`; another generation's is ignored), gdakiProbeQpOnError (an error completion or a failed post).
// gdakiProbeQpQueryState is QUERY_QP (a firmware command): setup and diagnostics only, never in the watch thread's step.
static ncclResult_t gdakiProbeQpCreate(struct gdakiRecHost* r, int peer, struct gdakiProbeQp* out, char* why, size_t whyLen);
static void gdakiProbeQpEndpoint(const struct gdakiProbeQp* q, struct gdakiCtrlEndpoint* out);
static ncclResult_t gdakiProbeQpConnect(struct gdakiProbeQp* q, const struct gdakiCtrlEndpoint* remote, uint32_t gen,
                                        char* why, size_t whyLen);
static ncclResult_t gdakiProbeQpReconnect(struct gdakiProbeQp* q, const struct gdakiCtrlEndpoint* remote, uint32_t gen,
                                          char* why, size_t whyLen);
static bool gdakiProbeQpIsRts(const struct gdakiProbeQp* q);
static bool gdakiProbeQpOkInGen(const struct gdakiProbeQp* q);
static void gdakiProbeQpOnSuccess(struct gdakiProbeQp* q, uint32_t gen);
static void gdakiProbeQpOnError(struct gdakiProbeQp* q);
static int gdakiProbeQpQueryState(const struct gdakiProbeQp* q);
static void gdakiProbeQpDestroy(struct gdakiProbeQp* q);
// ---- the hooks ----
// [1] the liveness READ QP to `peer` into ERR through the watch thread (its request word; design v2 2.1's handoff).
static void gdakiProbeToErr(struct gdakiRecHost* r, int peer);
// [2] the record QP to `peer` into ERR; [2] the store's responder QP of ward `peer` into ERR (9.4 step 1).
static void gdakiCtrlRecordToErr(struct gdakiRecHost* r, int peer);
static void gdakiStoreWardToErr(struct gdakiRecHost* r, int peer);
// [prep] the frame: every control QP toward `peer` into ERR (the three above). The hold start calls it after the quiesce
// moved the user and mirror QPs to ERR and before HOLDING (the fence's step 1, EXPERIMENT.md 9.4). The hold start may
// call it for a peer whose restore falls back right after (REVIEW_PREP 알릴 것 11): every hook is idempotent.
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
// [1] the activation decision's last condition (design v3 4.4 5, REVIEW_PREP 고칠 것 9): the buddy's ACTIVATE of dead
// + 1 goes only when the fence word of `peer` says incarnation `dead` is fenced. The decision (gdakiHoldActivateDecide)
// calls it after every other check; false: not now (the hold step asks again). The preparation stage: true.
static bool gdakiCtrlActFenceOk(struct gdakiRecHost* r, int peer, uint32_t dead);
// [1] [2] [3] each phase's pointer in r->ctrl, freed (and set null) by its own hook; gdakiCtrlFree [prep] calls them.
static void gdakiCtrlPageFree(struct gdakiRecHost* r);
static void gdakiCtrlRingFree(struct gdakiRecHost* r);
static void gdakiCtrlLauncherFree(struct gdakiRecHost* r);
// ---- [1] page: entry points (begin) ----
// ---- [1] page (end) ----
// ---- [2] ring: entry points (begin) ----
// ---- [2] ring (end) ----
// ---- [3] launcher: entry points (begin) ----
// ---- [3] launcher (end) ----
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
                  (int)GL_ENV_KIND_LAUNCHER == (int)GDAKI_CTRL_K_LAUNCHER && (int)GL_ENV_KIND_PAIR == (int)GDAKI_CTRL_K_PAIR &&
                  (int)GL_ENV_KIND_CONNECTED == (int)GDAKI_CTRL_K_CONNECTED,
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
