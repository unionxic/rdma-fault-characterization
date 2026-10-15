// rs_lineage_api.h - gin-mirror, the lineage (EXPERIMENT.md 9.9; user decision 2026-10-15: before the pre-registration
// the restore layer's incarnation decisions are gathered into one place). The restore layer writes the incarnation of
// logical rank d (the number of the process that serves d: 0 at setup, the restore of the death of incarnation i makes
// i + 1) in two places: the hold cell's incarnation (gdakiHoldPack, impl/rs_hold_api.h; + 1 only at the promotion,
// gdakiHoldRestoreMove) and the known incarnation (gdakiRsPeerInc; + 1 at an accepted REJOIN; the spare's own from
// ACTIVATE, a survivor's from its REJOIN_ACK). The two differ by one on purpose from the REJOIN's acceptance to the
// promotion (mirror off: RESTORED; mirror on: INJECTED). Pilot 1's defect A was a decision that read the wrong one.
// This block reads both at once into a phase and a view (gdakiLnViewOf) and classifies the incarnation x a record
// carries against the view (gdakiLnClassify); the callers' rules that need the view only follow. The lineage changes
// the incarnation comparisons only: every state condition (HELD only, FAIL to a declined rank, the published states,
// the arming conditions) stays the caller's and is read first. No wire, device or side-table change.
//
// One block is pasted verbatim: "gin-mirror: lineage API" goes into src/transport/net_ib/gdaki/gin_host_gdaki.cc right
// after the end of the region "gin-restore (rs, work package 5): checkpoint state" (after the hold and store blocks
// whose states and record numbers it names); build_mi.sh `api` checks it (BR=ln). Types, constants and pure static
// inline functions only. The rules that return the hold machine's own codes (they call impl/rs_hold_api.h's and the
// host branch's unchanged pure functions with inputs chosen from the view, design v3 V3) are the host file's region
// "gin-mirror (lineage): pure", after the region "gin-mirror (host): pure".
//
// Lines: one new head, "GIN/LN: " (GDAKI_LN_HEAD), for what never happens in a correct run: a BAD lineage, a FUTURE
// incarnation where none is expected (HOLDING, STORE_REQ, the spare's echo checks), the REJOIN_ACK cell write finding
// another value than OFF(0), a record without an incarnation still parked at a REJOIN's acceptance, a mismatch of the
// activation answer's echo or of the spare registration's incarnation. A GIN/LN line never carries a "why=" key
// (gin-restore's scorer reads why=(declined|peer-dead|degraded) anywhere in a line) and never the texts the scorers
// read ("judged dead", "is given up", "restored as incarnation"). The scorer column lineage_warn counts these lines.
#ifndef GIN_MIRROR_RS_LINEAGE_API_H_
#define GIN_MIRROR_RS_LINEAGE_API_H_

#include <stddef.h>
#include <stdint.h>

// A standalone syntax check needs the hold states and records (impl/rs_hold_api.h) and the record numbers 48..51 (in the
// host file the block follows them).
#include "rs_hold_api.h"
#include "rs_mirror_api.h"
#include "rs_store_api.h"

// ---- gin-mirror: lineage API (begin; impl/rs_lineage_api.h, byte for byte) ----
// The phase of rank d's lineage (the incarnation axis only: HELD and TIMED_OUT_HELD, COMMITTING and PUBLISHED are told
// apart by the callers' state conditions).
enum : uint32_t {
  GDAKI_LN_LIVE = 0,       // the cell OFF or ARMED and known = its incarnation: cur = that one, no dead one
  GDAKI_LN_HOLD_WAIT = 1,  // the cell held and known = its incarnation: dead = cur = the cell's (no successor accepted)
  GDAKI_LN_HOLD_SUCC = 2,  // the cell held and known = its incarnation + 1: dead = the cell's, cur = known (the
                           // successor's REJOIN accepted, not promoted yet)
  GDAKI_LN_ENDED = 3,      // the cell FALLBACK or CANCELLED, or the rank declined: every incarnation is stale
  GDAKI_LN_BAD = 4,        // anything else (invariant 1 broken): classified as LIVE with cur = known, one GIN/LN line
};
// The class of an incarnation x against a view.
enum : uint32_t {
  GDAKI_LN_CURRENT = 0,   // x = cur: the process that serves the rank now
  GDAKI_LN_HELD_OLD = 1,  // x = dead while the rank is held (HOLD_WAIT, HOLD_SUCC): the dead process
  GDAKI_LN_STALE = 2,     // older than the view's lower bound, or anything of an ENDED lineage
  GDAKI_LN_FUTURE = 3,    // newer than cur (normal only for the successor's REJOIN, x = dead + 1, in HOLD_WAIT)
};
// Invariants (EXPERIMENT.md 9.9): (1) cell <= known <= cell + 1, and known = cell + 1 only in a held state or the
// FALLBACK or CANCELLED that ended that hold; (2) the cell's incarnation rises only at the promotion, the known one only
// at an accepted REJOIN (a spare's: at ACTIVATE and REJOIN_ACK); (3) at the buddy, d's successor is CURRENT only after its
// FETCH ended; (4) at a REJOIN's acceptance d's park holds no record without an incarnation (gdakiLnRecordHasNoInc).
struct gdakiLnView {
  uint32_t phase = GDAKI_LN_LIVE;
  uint32_t cur = 0;    // the incarnation that serves the rank (LIVE: the cell's; HOLD_SUCC, ENDED, BAD: known)
  uint32_t dead = 0;   // the hold's dead incarnation (HOLD_WAIT, HOLD_SUCC); ENDED and BAD: the cell's
  bool hasDead = false;
  // the sources, for the callers' state conditions and their lines
  uint32_t cellState = GDAKI_HOLD_OFF;
  uint32_t cellInc = 0;
  uint32_t known = 0;
  bool declined = false;
};
static inline struct gdakiLnView gdakiLnViewOf(uint32_t cellState, uint32_t cellInc, uint32_t known, bool declined) {
  struct gdakiLnView v;
  v.cellState = cellState;
  v.cellInc = cellInc;
  v.known = known;
  v.declined = declined;
  const bool live = cellState == GDAKI_HOLD_OFF || cellState == GDAKI_HOLD_ARMED;
  const bool held = gdakiHoldIsHeldState(cellState);
  const bool ended = cellState == GDAKI_HOLD_FALLBACK || cellState == GDAKI_HOLD_CANCELLED;
  const bool same = known == cellInc;
  const bool succ = (uint64_t)known == (uint64_t)cellInc + 1u;
  v.cur = known;
  v.dead = cellInc;
  v.hasDead = true;
  if ((!same && !succ) || (live && succ) || (!live && !held && !ended)) {
    v.phase = GDAKI_LN_BAD;
  } else if (declined || ended) {
    v.phase = GDAKI_LN_ENDED;
  } else if (live) {
    v.phase = GDAKI_LN_LIVE;
    v.cur = cellInc;
    v.dead = 0;
    v.hasDead = false;
  } else {
    v.phase = same ? GDAKI_LN_HOLD_WAIT : GDAKI_LN_HOLD_SUCC;
  }
  return v;
}
static inline uint32_t gdakiLnClassify(const struct gdakiLnView& v, uint32_t x) {
  switch (v.phase) {
    case GDAKI_LN_ENDED:
      return GDAKI_LN_STALE;
    case GDAKI_LN_HOLD_WAIT:
    case GDAKI_LN_HOLD_SUCC:
      if (x < v.dead) return GDAKI_LN_STALE;
      if (x == v.dead) return GDAKI_LN_HELD_OLD;
      if (x == v.cur) return GDAKI_LN_CURRENT;  // HOLD_SUCC (cur = dead + 1)
      return x > v.cur ? GDAKI_LN_FUTURE : GDAKI_LN_STALE;
    default:  // LIVE; BAD as LIVE with cur = known
      if (x < v.cur) return GDAKI_LN_STALE;
      return x == v.cur ? GDAKI_LN_CURRENT : GDAKI_LN_FUTURE;
  }
}
static inline const char* gdakiLnPhaseName(uint32_t p) {
  switch (p) {
    case GDAKI_LN_LIVE: return "live";
    case GDAKI_LN_HOLD_WAIT: return "hold-wait";
    case GDAKI_LN_HOLD_SUCC: return "hold-succ";
    case GDAKI_LN_ENDED: return "ended";
    case GDAKI_LN_BAD: return "bad";
    default: return "?";
  }
}
static inline const char* gdakiLnClassName(uint32_t c) {
  switch (c) {
    case GDAKI_LN_CURRENT: return "current";
    case GDAKI_LN_HELD_OLD: return "held-old";
    case GDAKI_LN_STALE: return "stale";
    case GDAKI_LN_FUTURE: return "future";
    default: return "?";
  }
}
// This process itself (and a process without hold state): its own known incarnation, LIVE.
static inline struct gdakiLnView gdakiLnSelfView(uint32_t self) { return gdakiLnViewOf(GDAKI_HOLD_OFF, self, self, false); }

// ---- the callers' rules that need the view only (EXPERIMENT.md 9.9's caller table) ----
// x names the process that serves the rank now: the spare's echo checks (REJOIN_ACK, TOKEN, DONE_RS against its own
// view), READY, the rkey list, RESTORED's pad, a FALLBACK about this restored process (x = round + 1).
static inline bool gdakiLnIsCurrent(const struct gdakiLnView& v, uint32_t x) {
  return gdakiLnClassify(v, x) == GDAKI_LN_CURRENT;
}
// STORE_REQ at the buddy (gdakiStoreDropNow), and the answer of a served one right before the helper sends it (decision
// 2026-10-15, (나)): only the current incarnation's; the verdict of gdakiStoreReqVerdict (seq, sizes) follows as before.
static inline bool gdakiLnStoreServes(const struct gdakiLnView& v, uint32_t reqInc) { return gdakiLnIsCurrent(v, reqInc); }
// The reconnect fencing (HELLO, HELLO-ACK, PROBE, PROBE-ACK of a restore-requesting process): every pad while the rank's
// current incarnation is 0, else that one's only (in every phase: HOLD_WAIT's cur is the dead one, whose socket is still
// the rank's; HOLD_SUCC's the successor's; ENDED's too, as before: design v3 r1).
static inline bool gdakiLnReconnectOk(const struct gdakiLnView& v, uint32_t pad) { return v.cur == 0 || pad == v.cur; }
// The buddy's activation of d's spare: the answer must echo the rank and the incarnation dead + 1 asked for (else it
// counts as no answer, the two-strike rule); the spare registration must be the dead incarnation's own.
static inline bool gdakiLnActAnswerOk(int d, uint32_t dead, int32_t ansRank, uint32_t ansInc) {
  return ansRank == (int32_t)d && (uint64_t)ansInc == (uint64_t)dead + 1u;
}
static inline bool gdakiLnRegisteredOk(const struct gdakiLnView& v, uint32_t regInc) {
  return v.hasDead && regInc == v.dead;
}
// The records that carry no incarnation (they are checked at a REJOIN's acceptance: none may be left from the dead
// process): the checkpoint's 11..15 (round = a checkpoint number), MIRROR_SETUP 48, CKPT_PULL 49, STORE_REQ 50 (its
// record fields), STORE_ACK 51.
static inline bool gdakiLnRecordHasNoInc(uint32_t type) {
  return (type >= (uint32_t)GDAKI_TS_CKPT_PAUSE && type <= (uint32_t)GDAKI_TS_CKPT_STABLE) ||
         (type >= GDAKI_TS_MI_SETUP && type <= GDAKI_TS_STORE_ACK);
}
#define GDAKI_LN_HEAD "GIN/LN: "
// ---- gin-mirror: lineage API (end) ----

#endif  // GIN_MIRROR_RS_LINEAGE_API_H_
