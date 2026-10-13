// rs_hold_api.h v2 - gin-mirror (impl/PARALLEL.md; EXPERIMENT.md 9.4 "게이트를 INJECTED까지 홀수로", "바뀌는 규칙"): gin-restore's
// rs_hold_api.h (copied unchanged in commit 6cde95d6, md5 534884e3) with the mirror's changes, all inside the shared
// text: the record INJECTED (38, in the spare range: the restored rank sends it), PUBLISHED's end and deadline with the
// mirror, HOLDING's mirror flag (its payload is impl/rs_mirror_api.h's), and the host branch's entry points for them.
// With the mirror off every rule of v1 holds unchanged (no INJECTED is ever sent: RESTORED ends PUBLISHED).
// The rule with the mirror on, in one paragraph (user decision 2026-10-13, (가)): the survivor's restore round publishes
// as v1 (lbase, the plan with U = S and n = 0) but leaves the gate epoch of every USER QP to the revived rank odd (the
// mirror QP's gate is published even; its cells stay invalid). RESTORED is taken (gdakiRsTakeRestored), recorded and
// applied for its bookkeeping (the incarnation, gdakiCkptPeerReset, the survivor's own DISARM) but moves no state. The
// revived rank, once its import injected the inputs of its last tagged step, sends INJECTED to every survivor; the
// survivor then publishes those gates even (a write like the empty round's: the next even epoch, lbase unchanged),
// moves PUBLISHED or TIMED_OUT_PUBLISHED -> ARMED or OFF of incarnation i + 1 (gdakiHoldRestoredState, as v1 at
// RESTORED), clears the deadline and heldPeer, and drops the revived rank's closed segments (gdakiMiSegDropClosed).
// Until INJECTED the PUBLISHED deadline is min(v1's PUBLISHED deadline, D) with D = the hold's device bound
// (hp.deviceBoundUs: gates first odd + NCCL_GIN_TS_HOLD_MS - share - 1000 ms, 6897), because the device threads parked
// at those gates are still parked; past it the watcher moves PUBLISHED -> TIMED_OUT_PUBLISHED (state only) and the
// helper falls back (its decline's 2ERR first releases the parked threads with the error). INJECTED read before the
// helper's fallback wins over TIMED_OUT_PUBLISHED, as RESTORED does in v1 (Q2). Everything else of PUBLISHED (its QP
// watch, a fault record's fallback, the stale-record check, RESTORED and FALLBACK crossing, a REQ from the revived
// rank: NACK and fallback) is v1's, now until INJECTED.
// Line numbers NNNN are lines of ../../restore/impl/rs_layer.diff (md5 f005bb67). The rest of this head comment is
// v1's.
//
// v1: rs_hold_api.h - gin-restore, work package 7 (host branch; EXPERIMENT.md 9.2, 9.10.4, 9.10.5, 9.10.7, 9.11): the
// hold state machine's interface for the other branches: the per-peer state cell and its read and compare-and-swap
// helpers, the helper-socket record types this branch adds, the rule every wait follows for the records of the restore,
// and the entry points the other branches call.
//
// Binding interface between branches (impl/PARALLEL.md). The part between the two "shared text" fences below is also in
// src/transport/net_ib/gdaki/gin_host_gdaki.cc, verbatim, at the start of the region
//   "// ==== gin-restore (rs, work package 7): hold state (begin) ===="
// (after struct gdakiTs; the definitions of the entry points follow later in the same file, in the region
//   "// ==== gin-restore (rs, work package 7): hold machine (begin) ====").
// The CPU unit test (impl/rs_unit_host.cc) includes this file. A difference between this file and the host file is a bug
// of the host branch. Entry points are static functions of the host file: this file restates their declarations
// (struct gdakiRecHost and struct gdakiTsMsg come from the host file).
//
// Who drives a restore on a survivor (decided with the spare branch, impl/rs_spare_api.h): the hold state machine runs on
// the survivor's helper thread. For a held peer it calls, in order, the spare branch's gdakiRsRejoinAccept, then (work
// packages 5 and 9) the state transfer, ncclGinRecoverPrepare and gdakiRsSendToken, takes READY with gdakiRsTakeReady,
// gdakiRsSwapEndpoint, ncclGinRecoverCommit, gdakiTsBaseline, gdakiRsSwapRkeys, the publish (gdakiTsRepostApply with
// every old WQE counted executed; its hook takes HELD -> COMMITTING right before the commit point and COMMITTING ->
// PUBLISHED after the last publish), gdakiRsSendDone; and, in PUBLISHED, RESTORED through gdakiRsTakeRestored.
//
// Threads. The cell (state and incarnation in one 64-bit atomic, and the deadline) is read without a lock by any thread
// and changed only by compare-and-swap (N3: G9 is read under outMu and G8's CPU writes take outMu, the helper's decline
// takes outMu after the policy hook, so a lock here could invert that order; G8's compare-and-swap takes no lock).
// Writers: the helper thread (every transition but two) and the Q4 watcher thread (G8 only: HELD -> TIMED_OUT_HELD with
// the CPU writes, PUBLISHED -> TIMED_OUT_PUBLISHED, the state alone). Every other entry point runs on the helper thread only (gdakiTsInHelper) and takes no lock of its own.
// A process that does not ask for the restore (fail-fast; NCCL_GIN_RESTORE=0) has no hold state: every query answers
// GDAKI_HOLD_OFF and every hook returns what hk does.

// ---- shared text (begin) ----
#ifndef GIN_RESTORE_RS_HOLD_API_H_
#define GIN_RESTORE_RS_HOLD_API_H_

#include <atomic>
#include <stddef.h>
#include <stdint.h>

// ---- helper-socket records of the restore (struct gdakiTsMsg, fixed size, magic GDAKI_TS_MAGIC) ----
// hk uses types 1..10. The restore's records use 11..63: this branch 11..20, the dev branch 21..31 (impl/rs_log_api.h:
// none used yet), the spare branch 32..47 (impl/rs_spare_api.h: REJOIN 32 .. RESTORED 37; gin-mirror: INJECTED 38,
// below); gin-mirror 48..51 (impl/rs_mirror_api.h, impl/rs_store_api.h); 52..63 are free. The spare's
// activation is not a helper-socket record (struct gdakiRsActivate on the spare's own port), and the log export, the
// spare's rkey list and the checkpoint blocks go over the data socket (work package 5), not the helper socket.
enum : uint32_t {
  GDAKI_TS_CKPT_PAUSE = 11,   // r -> every peer q: checkpoint k's input pause (work package 5)
  GDAKI_TS_PAUSED = 12,       // q -> r: paused; its log write position, messages sent to r, executed from r; armable
  GDAKI_TS_BUSY = 13,         // q -> r: cannot pause now (a round, a suppress budget left, a hold): r skips checkpoint k
  GDAKI_TS_CKPT_RESUME = 14,  // r -> q: end of the input pause (q publishes an empty round)
  GDAKI_TS_CKPT_STABLE = 15,  // r -> every peer: checkpoint k is stable at the buddy (logs trimmed; arming)
  GDAKI_TS_DISARM = 16,       // any -> every rank: subject p must not be held until p's next stable checkpoint
  GDAKI_TS_NOHOLD = 17,       // any -> every rank: this rank declined subject p (incarnation i) without holding it
  GDAKI_TS_HOLDING = 18,      // survivor -> p's buddy: this rank holds subject p (the death of incarnation i)
  GDAKI_TS_FALLBACK = 19,     // survivor -> every rank and p's spare: the restore of p's incarnation i is given up
  GDAKI_TS_HOST_RESERVED = 20,
};
// Fields of the host branch's records: from = the sender's rank, nonce = the GIN context's nonce, arg = the subject rank
// p (the rank the record is about), round = the incarnation it concerns (DISARM: the incarnation the sender knows;
// NOHOLD, HOLDING, FALLBACK: the incarnation that died, i, also after the spare's REJOIN of i + 1 was accepted: every
// survivor holds i, while gdakiRsPeerInc differs between survivors that accepted the REJOIN and those that did not),
// pad = flags (v2: GDAKI_HOLD_F_MIRROR on HOLDING, impl/rs_mirror_api.h, its payload in executed), nqp = 0. CKPT_*:
// round = the checkpoint number; their payload is fixed by work package 5 (v2: impl/rs_store_api.h's CKPT_STABLE flag).
// Incarnations: 0 at setup; a restore of the death of incarnation i brings i + 1 (the spare's gdakiRsPeerInc is i + 1
// once its REJOIN is accepted).
// NACK reason 17 (gdakiTsMsg::arg of a NACK): "restoring": the REQ came from a peer this rank holds (9.10.7 Q5; RL20).
#define GDAKI_TS_NACK_RESTORING 17
// A record of the restore: types 11..63.
static inline bool gdakiHoldIsRestoreRecord(uint32_t type) { return type >= 11u && type <= 63u; }
// v2 (gin-mirror): INJECTED, revived rank -> every survivor (the spare range's 38; sent by the revived rank's helper
// once gdakiMiInjectedReady was called). Fields: from = the revived rank, nonce, arg = the revived rank, round = the
// last step whose inputs it injected, pad = its incarnation (i + 1), nqp = 0, executed[0] = GDAKI_RS_WIRE_VERSION,
// executed[1] = its own incarnation (as the spare's records 32..37). The survivor's state machine takes it with the
// host branch's types (gdakiHoldDrain's filter), in arrival order after RESTORED.
#define GDAKI_TS_RS_INJECTED 38u

// The rule for every wait on an installed helper socket (hk's ACK wait, DONE wait, the waits that serve other peers, the
// idle loop's pump after a kept REQ, and every wait the restore adds): a record of the restore (gdakiHoldIsRestoreRecord)
// is never dropped and never a reason to decline; it is parked for its peer in arrival order (gdakiHoldDefer) and the wait
// goes on. The idle loop parks them too and the state machine, at the top of each helper loop, handles the host branch's
// types in arrival order per peer (9.10.7 R1; before that peer's REQ is answered: gdakiTsRespond's hook drains them
// first). The other branches' types stay parked until their owner takes them (gdakiHoldTakeMsg; a record nobody takes is
// dropped after GDAKI_HOLD_PARK_MS, with a log line, and at most GDAKI_HOLD_PARK_MAX are kept per peer).
#define GDAKI_HOLD_PARK_MS 60000.0
#define GDAKI_HOLD_PARK_MAX 256

// ---- the per-peer state (9.10.7) ----
// OFF          no restore for this peer (not armed, disarmed, or declined without a hold)
// ARMED        a stable checkpoint of the peer covers it on every rank: its strong death evidence starts a hold
// HELD         held: the peer's QPs in ERR, gates odd, no word, no async error; waiting for the spare and the restore round
// COMMITTING   the restore round passed its compare-and-swap and is past the commit point (the watcher leaves it alone)
// PUBLISHED    published (gates even, QPs RTS with the spare); the spare's RESTORED ends it. v2, mirror on: the user
//              QPs' gates stay odd and INJECTED ends it (RESTORED is taken but moves nothing)
// TIMED_OUT_HELD       the watcher's deadline won from HELD and made the CPU writes (word, async error, blame, degraded);
//                      the helper declines next (the fallback)
// TIMED_OUT_PUBLISHED  the deadline won from PUBLISHED (state only); a RESTORED read first still wins, else the fallback
//                      (v2, mirror on: an INJECTED read first wins)
// FALLBACK     given up for this incarnation: the peer was declined (PeerDead, GDAKI_UA_PEER_DEAD); never held again
// CANCELLED    ncclCommAbort, ncclCommRevoke or an aborting shrink ended a hold (ncclCommDestroy's teardown stops the
//              helper and leaves the state as it is)
enum : uint32_t {
  GDAKI_HOLD_OFF = 0,
  GDAKI_HOLD_ARMED = 1,
  GDAKI_HOLD_HELD = 2,
  GDAKI_HOLD_COMMITTING = 3,
  GDAKI_HOLD_PUBLISHED = 4,
  GDAKI_HOLD_TIMED_OUT_HELD = 5,
  GDAKI_HOLD_TIMED_OUT_PUBLISHED = 6,
  GDAKI_HOLD_FALLBACK = 7,
  GDAKI_HOLD_CANCELLED = 8,
};
static inline const char* gdakiHoldStateName(uint32_t s) {
  switch (s) {
    case GDAKI_HOLD_OFF: return "off";
    case GDAKI_HOLD_ARMED: return "armed";
    case GDAKI_HOLD_HELD: return "held";
    case GDAKI_HOLD_COMMITTING: return "committing";
    case GDAKI_HOLD_PUBLISHED: return "published";
    case GDAKI_HOLD_TIMED_OUT_HELD: return "timed-out-held";
    case GDAKI_HOLD_TIMED_OUT_PUBLISHED: return "timed-out-published";
    case GDAKI_HOLD_FALLBACK: return "fallback";
    case GDAKI_HOLD_CANCELLED: return "cancelled";
    default: return "?";
  }
}
// "A held peer" (9.10.7): HELD, COMMITTING, PUBLISHED and the two timed-out states (the helper has not declined it yet).
static inline bool gdakiHoldIsHeldState(uint32_t s) {
  return s == GDAKI_HOLD_HELD || s == GDAKI_HOLD_COMMITTING || s == GDAKI_HOLD_PUBLISHED ||
         s == GDAKI_HOLD_TIMED_OUT_HELD || s == GDAKI_HOLD_TIMED_OUT_PUBLISHED;
}
// The held states whose QPs are in ERR (or not yet published): the QP watch (G3), the lost-record check (G5) and the fault
// records (G4: absorbed) leave them alone. PUBLISHED and TIMED_OUT_PUBLISHED are watched (their QPs are RTS with the spare).
static inline bool gdakiHoldIsQuietState(uint32_t s) {
  return s == GDAKI_HOLD_HELD || s == GDAKI_HOLD_COMMITTING || s == GDAKI_HOLD_TIMED_OUT_HELD;
}
// v2 (gin-mirror):
// What a survivor does with INJECTED of `peer`: apply it only in PUBLISHED or TIMED_OUT_PUBLISHED of the death of
// incarnation inc, when it is for incarnation inc + 1 and RESTORED of that incarnation was taken before it.
enum { GDAKI_HOLD_INJ_IGNORE = 0, GDAKI_HOLD_INJ_APPLY = 1 };
static inline int gdakiHoldInjectedAction(uint32_t state, uint32_t inc, uint32_t msgInc, bool restoredTaken) {
  const bool published = state == GDAKI_HOLD_PUBLISHED || state == GDAKI_HOLD_TIMED_OUT_PUBLISHED;
  return published && msgInc == inc + 1u && restoredTaken ? GDAKI_HOLD_INJ_APPLY : GDAKI_HOLD_INJ_IGNORE;
}
// PUBLISHED's deadline with the mirror, until INJECTED (us, CLOCK_MONOTONIC): v1's (gdakiHoldPublishedDeadlineUs) but
// never past the hold's device bound (gdakiHoldDeviceBoundUs at the hold start).
static inline int64_t gdakiHoldInjectWaitDeadlineUs(int64_t publishedDeadlineUs, int64_t deviceBoundUs) {
  return publishedDeadlineUs < deviceBoundUs ? publishedDeadlineUs : deviceBoundUs;
}

// One 64-bit word: the state in bits 0..31, the incarnation it concerns in bits 32..63. A hold of incarnation i happens at
// most once (a fallback is final for i, a restore moves to i + 1), so (state, incarnation) never repeats within a hold and
// a compare-and-swap that expects it cannot hit a later hold (no ABA).
static inline uint64_t gdakiHoldPack(uint32_t state, uint32_t inc) { return ((uint64_t)inc << 32) | (uint64_t)state; }
static inline uint32_t gdakiHoldStateOf(uint64_t v) { return (uint32_t)v; }
static inline uint32_t gdakiHoldIncOf(uint64_t v) { return (uint32_t)(v >> 32); }

struct gdakiHoldCell {
  std::atomic<uint64_t> v{0};          // gdakiHoldPack(state, incarnation); OFF, incarnation 0 at setup
  std::atomic<int64_t> deadlineUs{0};  // HELD or PUBLISHED: when the watcher times it out (CLOCK_MONOTONIC us; 0: none).
                                       // Written by the helper only: 0 before it enters HELD (release), the deadline once
                                       // known (release); the watcher loads the state (acquire), then this.
};
static inline uint64_t gdakiHoldLoad(const struct gdakiHoldCell& c) { return c.v.load(std::memory_order_acquire); }
// Compare-and-swap of the whole word: true if it held `expect` and now holds `want`; else false and `expect` is updated to
// what it holds.
static inline bool gdakiHoldCas(struct gdakiHoldCell& c, uint64_t& expect, uint64_t want) {
  return c.v.compare_exchange_strong(expect, want, std::memory_order_acq_rel, std::memory_order_acquire);
}

// The buddy of logical rank p (9.4: it keeps p's checkpoint; p's HOLDING goes to it): p xor 1 (the testbed's alternating
// placement puts it on the other node), or rank 0 for the last rank of an odd count. Never p itself when nranks >= 2.
static inline int gdakiHoldBuddyOf(int p, int nranks) {
  if (nranks < 2) return -1;
  const int b = p ^ 1;
  return b < nranks ? b : (p == 0 ? 1 : 0);
}

// ---- entry points (static functions of the host file) ----
// (The CPU unit test defines GDAKI_HOLD_API_NO_ENTRY_DECLS: it has no definitions.)
#ifndef GDAKI_HOLD_API_NO_ENTRY_DECLS
struct gdakiRecHost;  // the host file
struct gdakiTsMsg;    // the host file

// Any thread, lock-free.
// What impl/rs_spare_api.h asks for: whether `peer` is HELD on this context (not COMMITTING, PUBLISHED, timed out or
// FALLBACK). False in a process that does not ask for the restore.
static bool gdakiRsHoldIsHeld(struct gdakiRecHost* r, int peer);
// The state of `peer` and the incarnation it concerns (*inc may be NULL). GDAKI_HOLD_OFF and 0 in a process that does not
// ask for the restore, for this rank itself and for a rank outside the communicator.
static uint32_t gdakiHoldPeerState(struct gdakiRecHost* r, int peer, uint32_t* inc);

// Helper thread only.
// Park a record of the restore read inside a wait (see the rule above). Records of other types are not parked (false).
static bool gdakiHoldDefer(struct gdakiRecHost* r, int peer, const struct gdakiTsMsg* m);
// Take the oldest parked record of `type` from `peer` (false: none). The owner of a type calls it (the state machine for
// 11..20 and for the spare's READY and RESTORED of a held peer).
static bool gdakiHoldTakeMsg(struct gdakiRecHost* r, int peer, uint32_t type, struct gdakiTsMsg* out);
// Send one record to `to` on its installed helper socket (magic, from and nonce are filled in; bounded, 200 ms).
// 0 sent, -1 not sent (no installed socket, or the send failed).
static int gdakiHoldSend(struct gdakiRecHost* r, int to, struct gdakiTsMsg* m);
// Milliseconds left before the hold of `peer` times out (the bound for any wait inside its restore); 0 when it is not held
// or has no deadline yet.
static int gdakiHoldLeftMs(struct gdakiRecHost* r, int peer);
// Give up the restore of a held peer (any failure of the restore: a refused or lost spare, a failed state transfer, a
// failed round step): FALLBACK(p, i) to every rank and to the spare's socket, then the decline with cause PeerDead and
// GDAKI_UA_PEER_DEAD (9.10.5: the same state as when fail-fast declines a dead peer). Nothing when `peer` is not held.
static void gdakiHoldFallback(struct gdakiRecHost* r, int peer, const char* why);
// Arming (work packages 5 and 9): ARMED(inc) from OFF when this communicator is armed (ncclGinRestoreResume enabled the
// restore and its conditions still hold), `peer` is not declined and no DISARM of `peer` arrived since the input pause of
// the checkpoint that arms it (the caller says which: disarmSeq is the value gdakiHoldDisarmSeq returned at that pause).
// False: not armed (the reason in *why, may be NULL).
static bool gdakiHoldArm(struct gdakiRecHost* r, int peer, uint32_t inc, uint64_t disarmSeq, const char** why);
// The count of DISARM(peer) this rank has received or made so far (for gdakiHoldArm).
static uint64_t gdakiHoldDisarmSeq(struct gdakiRecHost* r, int peer);
// ARMED -> OFF for `peer` on this rank and, with broadcast, DISARM(peer) to every rank (a log overflow, a get toward the
// peer, a window deregistered, a lost arming condition). A held peer keeps its hold; the DISARM is applied at its RESTORED
// (v2, mirror on: at its INJECTED).
static void gdakiHoldDisarm(struct gdakiRecHost* r, int peer, const char* why, bool broadcast);
// v2 (gin-mirror), the host branch's PUBLISHED and INJECTED package:
// Any thread (the revived rank's import, impl/rs_log_api.h v2): the inputs of every tagged step up to lastStep are in;
// the helper sends INJECTED(lastStep) to every survivor at its next step, once per incarnation. Nothing with the mirror
// off.
static void gdakiMiInjectedReady(struct gdakiRecHost* r, uint64_t lastStep);
// Helper: the restore round's publish (gdakiTsRepostApply in gdakiHoldCommitRound, 7403-7404) keeps the gates of the
// user QPs to `peer` odd (true with the mirror on).
static bool gdakiMiKeepGatesOdd(struct gdakiRecHost* r, int peer);
// Helper: an INJECTED record from `peer` (gdakiHoldOnMsg): gdakiHoldInjectedAction, then the even gates, the state
// move, the deadline and heldPeer cleared, gdakiMiSegDropClosed(peer). A gate write that fails: the decline (as a
// failed round).
static void gdakiHoldApplyInjected(struct gdakiRecHost* r, int peer, const struct gdakiTsMsg& m);
#endif  // GDAKI_HOLD_API_NO_ENTRY_DECLS

#endif  // GIN_RESTORE_RS_HOLD_API_H_
// ---- shared text (end) ----
