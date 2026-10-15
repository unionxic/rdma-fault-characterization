// mi_unit_lineage.cc - CPU unit test of gin-mirror's lineage (EXPERIMENT.md 9.9; the design's 6절, v3). No NCCL, no
// CUDA, no network. Built by `BR=ln build_mi.sh unit`: impl/rs_lineage_api.h (the view, the classification, the rules
// that need the view only), the regions "gin-mirror (lineage): pure" (mi_pure_lineage.inc: the rules that return the hold
// machine's codes), and, for the oracle's old side, the unchanged regions "gin-restore: pure functions", "gin-restore
// hold: pure functions", "gin-restore ckpt: pure functions", gin-restore's spare pure functions, "gin-mirror (host):
// pure", "gin-mirror (store): pure", cut from the working tree's gin_host_gdaki.cc; g++ with ASan and UBSan.
// What it checks:
//   1. the view table: every cell state x cell incarnation 0..3 x known (cell - 1 .. cell + 2) x declined against the
//      design's phase table (BAD included);
//   2. the classification table: every phase x x in the window against the design's table;
//   3. the oracle: for every row of the caller table, old_<row> (the snapshot's caller decision, the six shared and pure
//      functions gdakiHoldInjectedAction, gdakiHoldMsgAction, gdakiHoldArmOk, gdakiMiInjectedCheck, gdakiStoreDropReq,
//      gdakiStoreDropOldInc called as they are, the callers' state conditions transcribed with their lines H:N of the
//      snapshot lineage/snap_host.cc, md5 cc4eea3d) against new_<row> (the lineage's rule as the host calls it) over every
//      reachable view (invariant 1 and the reachability conditions (a)-(g) below) x the x window; the set of rows that
//      differ must be the design's list (the activation answer, the spare registration, STORE_REQ, the serve's answer),
//      and inside those rows the differing points must be exactly the new checks (STORE_REQ: FUTURE, and a CANCELLED
//      ward that is not declined); the BAD domain apart;
//   4. the callers' mutation: a view built from the wrong source (the cell's incarnation as the current one, or known as
//      the dead one: defect A's form) must make the oracle and defect A's scene fail;
//   5. the scenes (event scripts on a model of the processes' cells, known incarnations, parks and holders): first death
//      (mirror off and on), defect A, the buddy's and the other survivors' counting, a late CKPT_STABLE and the park check
//      at the REJOIN, the buddy restored then a second death (the REJOIN_ACK cell write; the third incarnation: with the
//      write the count fills, without it and the old arming source it never does), the fallback after the REJOIN, the
//      activation without an answer, a dead process's parked STORE_REQ, a stale STORE_ACK (a served request of the dead
//      process, seq >= 2: not sent; without the re-check the new process would take it), TIMED_OUT_HELD,
//      TIMED_OUT_PUBLISHED, CANCELLED, NOHOLD, a DISARM during the hold, survivors in different phases, the revived
//      process's own end, the reconnect fencing in HOLD_SUCC, the FETCH handshake failing after ACCEPTED.
// The reachability conditions of the oracle's domain (design v3 V1 (a)-(f), and (g) found while writing this test):
//   (a) COMMITTING, PUBLISHED, TIMED_OUT_PUBLISHED imply known = cell + 1;
//   (b) HELD, TIMED_OUT_HELD: the drive's phase is REJOIN iff known = cell (COMMITTING: READY; the published states:
//       PUBLISHED; every other state: REJOIN);
//   (c) restoredPad is 0 or <= known, and = known only after RESTORED was taken: in the published states (known = cell +
//       1), after the promotion (LIVE, known >= 1) or in a lineage that ended (FALLBACK, CANCELLED);
//   Two of these exclusions are narrower than the code (the implementation review, 2026-10-15, nit N2), and neither hides
//   a difference:
//   - (c): restoredPad is reset only at the setup and written only at RESTORED, so a rank held again after its promotion
//     (the third incarnation) is HELD with restoredPad = known. The only row that reads restoredPad is INJECTED, and the
//     lineage's rule differs from the old one only where it applies (the published states), so no excluded point could
//     differ.
//   - (b)'s "every other state: REJOIN": gdakiHoldCancel does not reset the drive's phase, so CANCELLED (and the other
//     ended states) can carry READY or PUBLISHED. The rows that read the phase (REJOIN, READY) look at it only in HELD,
//     so no excluded point could differ either.
//   (d) revivedFromValid implies revivedFrom < cell;
//   (e) a declined rank's cell is OFF, FALLBACK or CANCELLED;
//   (f) LIVE's x window starts at cur - 2 (no dead one);
//   (g) FALLBACK implies declined (gdakiHoldFallback and gdakiHoldDeclineRevived decline right after their CAS, on the
//       same helper step).
#include <algorithm>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <functional>
#include <map>
#include <mutex>
#include <new>
#include <set>
#include <string>
#include <thread>
#include <vector>

// what the host file has before these regions (a standalone test supplies it; as impl/mi_unit_host.cc)
typedef enum { ncclSuccess = 0, ncclSystemError = 2, ncclInternalError = 3, ncclInvalidUsage = 5 } ncclResult_t;
typedef struct {
  unsigned int magic, nqp, qpn[64], remoteQpn[64], sqPsn[64];
  unsigned long long epochWqes[64];
} ncclGinRecoverToken_t;
enum { GDAKI_POLICY_FAILFAST = 0, GDAKI_POLICY_HOLD = 1 };  // hk's line
enum { GDAKI_TS_HELLO = 1, GDAKI_TS_REQ = 2, GDAKI_TS_ACK = 3, GDAKI_TS_NACK = 4, GDAKI_TS_DONE = 5, GDAKI_TS_FAIL = 6,
       GDAKI_TS_BYE = 10 };
#define NCCL_GIN_RS_QP_MASK 0xffffffu  // the device-host common header's (a log entry's QP field)
struct ncclGinRsLogEntry {             // impl/rs_log_api.h's standalone copy (64 bytes)
  uint32_t pos, qpKf, csum, sigWin, dstWin, srcWin;
  uint64_t dstOff, bytes, src, sigOff, sigVal;
};
#define GDAKI_HOLD_API_NO_ENTRY_DECLS
#include "rs_mirror_api.h"
#include "rs_hold_api.h"
#include "rs_ckpt_api.h"
#include "rs_store_api.h"
#include "rs_lineage_api.h"
#include "rs_pure.inc"
#include "rs_hold_pure.inc"
#include "rs_ckpt_pure.inc"
#include "rs_spare_pure.inc"   // gdakiRsRejoinValidate (H:4600)
#include "mi_pure_host.inc"    // gdakiMiInjectedCheck (H:7351)
#include "mi_pure_store.inc"   // gdakiStoreDropReq, gdakiStoreDropOldInc (H:15952, 15959), struct gdakiStoreUp
// The host file's drive phases (its hold state region, outside every pure region: H:6081-6087), which the lineage's
// REJOIN rule names.
enum {
  GDAKI_HOLD_P_REJOIN = 0,
  GDAKI_HOLD_P_TRANSFER = 1,
  GDAKI_HOLD_P_PREPARE = 2,
  GDAKI_HOLD_P_READY = 3,
  GDAKI_HOLD_P_PUBLISHED = 4,
};
#include "mi_pure_lineage.inc"

static long gChecks = 0, gFailed = 0;
#define CHECK(c)                                                                     \
  do {                                                                               \
    gChecks++;                                                                       \
    if (!(c)) {                                                                      \
      gFailed++;                                                                     \
      if (gFailed <= 60) fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); \
    }                                                                                \
  } while (0)

static const uint32_t kStates[9] = {GDAKI_HOLD_OFF,       GDAKI_HOLD_ARMED,          GDAKI_HOLD_HELD,
                                    GDAKI_HOLD_COMMITTING, GDAKI_HOLD_PUBLISHED,      GDAKI_HOLD_TIMED_OUT_HELD,
                                    GDAKI_HOLD_TIMED_OUT_PUBLISHED, GDAKI_HOLD_FALLBACK, GDAKI_HOLD_CANCELLED};
static bool isLive(uint32_t s) { return s == GDAKI_HOLD_OFF || s == GDAKI_HOLD_ARMED; }
static bool isEnded(uint32_t s) { return s == GDAKI_HOLD_FALLBACK || s == GDAKI_HOLD_CANCELLED; }
static bool isPub(uint32_t s) { return s == GDAKI_HOLD_PUBLISHED || s == GDAKI_HOLD_TIMED_OUT_PUBLISHED; }
static bool isHeldS(uint32_t s) {
  return s == GDAKI_HOLD_HELD || s == GDAKI_HOLD_COMMITTING || s == GDAKI_HOLD_PUBLISHED ||
         s == GDAKI_HOLD_TIMED_OUT_HELD || s == GDAKI_HOLD_TIMED_OUT_PUBLISHED;
}

// ---- 1. the view table (the design's 2.2) ----
static void testViews() {
  long n = 0, bad = 0;
  for (uint32_t s : kStates)
    for (uint32_t c = 0; c <= 3; c++)
      for (int dk = -1; dk <= 2; dk++) {
        if (c == 0 && dk < 0) continue;
        const uint32_t k = c + (uint32_t)dk;
        for (int dec = 0; dec < 2; dec++) {
          const struct gdakiLnView v = gdakiLnViewOf(s, c, k, dec != 0);
          n++;
          // the expected phase, written apart from the implementation
          uint32_t ph;
          uint32_t cur = k, dead = c;
          bool hasDead = true;
          const bool ok1 = k == c || k == c + 1;
          if (!ok1 || (isLive(s) && k == c + 1)) ph = GDAKI_LN_BAD;
          else if (dec || isEnded(s)) ph = GDAKI_LN_ENDED;
          else if (isLive(s)) { ph = GDAKI_LN_LIVE; cur = c; dead = 0; hasDead = false; }
          else ph = k == c ? GDAKI_LN_HOLD_WAIT : GDAKI_LN_HOLD_SUCC;
          if (ph == GDAKI_LN_BAD) bad++;
          CHECK(v.phase == ph);
          CHECK(v.cur == cur && v.dead == dead && v.hasDead == hasDead);
          CHECK(v.cellState == s && v.cellInc == c && v.known == k && v.declined == (dec != 0));
          if (ph == GDAKI_LN_HOLD_WAIT) CHECK(v.cur == v.dead);
          if (ph == GDAKI_LN_HOLD_SUCC) CHECK(v.cur == v.dead + 1);
        }
      }
  // an unknown state value is BAD
  CHECK(gdakiLnViewOf(99u, 1, 1, false).phase == GDAKI_LN_BAD);
  // this process itself: LIVE of its own
  const struct gdakiLnView me = gdakiLnSelfView(2);
  CHECK(me.phase == GDAKI_LN_LIVE && me.cur == 2 && !me.hasDead);
  printf("views: %ld (BAD %ld)\n", n, bad);
}

// ---- 2. the classification table (the design's 2.4) ----
static uint32_t lowerOf(const struct gdakiLnView& v) {  // the window's lower end ((f): LIVE from cur)
  const uint32_t base = (v.phase == GDAKI_LN_LIVE || v.phase == GDAKI_LN_BAD) ? v.cur : v.dead;
  return base >= 2 ? base - 2 : 0;
}
static void testClassify() {
  long n = 0;
  for (uint32_t s : kStates)
    for (uint32_t c = 0; c <= 3; c++)
      for (int dk = -1; dk <= 2; dk++) {
        if (c == 0 && dk < 0) continue;
        const uint32_t k = c + (uint32_t)dk;
        for (int dec = 0; dec < 2; dec++) {
          const struct gdakiLnView v = gdakiLnViewOf(s, c, k, dec != 0);
          for (uint32_t x = lowerOf(v); x <= v.cur + 2; x++) {
            uint32_t want;
            switch (v.phase) {
              case GDAKI_LN_ENDED: want = GDAKI_LN_STALE; break;
              case GDAKI_LN_HOLD_WAIT:
                want = x < v.dead ? GDAKI_LN_STALE : x == v.dead ? GDAKI_LN_HELD_OLD : GDAKI_LN_FUTURE;
                break;
              case GDAKI_LN_HOLD_SUCC:
                want = x < v.dead      ? GDAKI_LN_STALE
                       : x == v.dead   ? GDAKI_LN_HELD_OLD
                       : x == v.cur    ? GDAKI_LN_CURRENT
                                       : GDAKI_LN_FUTURE;
                break;
              default:  // LIVE, and BAD as LIVE with cur = known
                want = x < v.cur ? GDAKI_LN_STALE : x == v.cur ? GDAKI_LN_CURRENT : GDAKI_LN_FUTURE;
            }
            CHECK(gdakiLnClassify(v, x) == want);
            n++;
          }
        }
      }
  printf("classifications: %ld\n", n);
}

// ---- 3. the oracle ----
// One reachable point of the domain: the sources, the drive's phase and the memos.
struct Pt {
  uint32_t s = GDAKI_HOLD_OFF, c = 0, k = 0;
  bool dec = false;
  int phase = GDAKI_HOLD_P_REJOIN;
  uint32_t restoredPad = 0;
  bool rfv = false;
  uint32_t rf = 0;
};
static bool reachable(const Pt& p) {
  const bool succ = p.k == p.c + 1;
  if (!(p.k == p.c || succ)) return false;                                                // invariant 1
  if (succ && !(isHeldS(p.s) || isEnded(p.s))) return false;                              // invariant 1
  if ((p.s == GDAKI_HOLD_COMMITTING || isPub(p.s)) && !succ) return false;                // (a)
  if (p.dec && !(p.s == GDAKI_HOLD_OFF || isEnded(p.s))) return false;                     // (e)
  if (p.s == GDAKI_HOLD_FALLBACK && !p.dec) return false;                                 // (g)
  if (p.rfv && !(p.rf < p.c)) return false;                                               // (d)
  if (p.restoredPad > p.k) return false;                                                  // (c)
  if (p.restoredPad == p.k && p.k > 0) {                                                  // (c)
    const bool after = isPub(p.s) || isEnded(p.s) || (isLive(p.s) && p.k >= 1);
    if (!after) return false;
  }
  // (b) the drive's phase
  if (p.s == GDAKI_HOLD_HELD || p.s == GDAKI_HOLD_TIMED_OUT_HELD) {
    if ((p.phase == GDAKI_HOLD_P_REJOIN) != (p.k == p.c)) return false;
    if (p.phase == GDAKI_HOLD_P_PUBLISHED) return false;
  } else if (p.s == GDAKI_HOLD_COMMITTING) {
    if (p.phase != GDAKI_HOLD_P_READY) return false;
  } else if (isPub(p.s)) {
    if (p.phase != GDAKI_HOLD_P_PUBLISHED) return false;
  } else if (p.phase != GDAKI_HOLD_P_REJOIN) {
    return false;
  }
  return true;
}
template <typename F>
static void forEachPt(F f) {
  for (uint32_t s : kStates)
    for (uint32_t c = 0; c <= 3; c++)
      for (uint32_t k = c; k <= c + 1; k++)
        for (int dec = 0; dec < 2; dec++)
          for (int ph = GDAKI_HOLD_P_REJOIN; ph <= GDAKI_HOLD_P_PUBLISHED; ph++)
            for (uint32_t rp = 0; rp <= k; rp++)
              for (int rfv = 0; rfv < 2; rfv++)
                for (uint32_t rf = 0; rf <= (rfv ? 3u : 0u); rf++) {
                  Pt p;
                  p.s = s;
                  p.c = c;
                  p.k = k;
                  p.dec = dec != 0;
                  p.phase = ph;
                  p.restoredPad = rp;
                  p.rfv = rfv != 0;
                  p.rf = rf;
                  if (reachable(p)) f(p);
                }
}
// How the host builds a view from the sources (gdakiLnOf), and two wrong callers (defect A's forms).
typedef struct gdakiLnView (*Builder)(const Pt& p);
static struct gdakiLnView buildOk(const Pt& p) { return gdakiLnViewOf(p.s, p.c, p.k, p.dec); }
static struct gdakiLnView buildCellAsCur(const Pt& p) { return gdakiLnViewOf(p.s, p.c, p.c, p.dec); }  // known ignored
static struct gdakiLnView buildKnownAsDead(const Pt& p) { return gdakiLnViewOf(p.s, p.k, p.k, p.dec); }  // the cell ignored

enum Row {
  R_HOLDSTART, R_HOLDING, R_ACTIVATE, R_ACT_ANSWER, R_SPARE_REG, R_REJOIN, R_ECHO, R_READY_RKEYS, R_RESTORED,
  R_INJECTED, R_DISARM, R_NOHOLD, R_FALLBACK, R_ARM, R_SELF_FALLBACK, R_STORE_REQ, R_SERVE_ANSWER, R_CUR_SOURCE,
  R_FENCING, R_N
};
static const char* kRowName[R_N] = {"hold start", "HOLDING count", "activation", "activation answer", "spare registration",
                                    "REJOIN", "spare echo", "READY and rkey list", "RESTORED", "INJECTED", "DISARM",
                                    "NOHOLD", "FALLBACK", "arming", "FALLBACK about itself", "STORE_REQ",
                                    "serve answer", "current incarnation source", "reconnect fencing"};
struct Diff {
  int row;
  uint32_t phase, cls;
  bool operator<(const Diff& o) const {
    return row != o.row ? row < o.row : phase != o.phase ? phase < o.phase : cls < o.cls;
  }
};
struct Oracle {
  std::set<Diff> diffs;
  long points[R_N] = {};
  long differ[R_N] = {};
  long unexpectedInList = 0;  // a difference in a listed row that is not that row's new check
  void cmp(int row, const struct gdakiLnView& v, uint32_t x, long oldv, long newv, bool expectDiff) {
    points[row]++;
    if (oldv == newv) {
      if (expectDiff) unexpectedInList++;  // the new check should have fired here
      return;
    }
    differ[row]++;
    diffs.insert({row, v.phase, gdakiLnClassify(v, x)});
    if (!expectDiff) unexpectedInList++;
  }
};
// holders as the buddy keeps them (subject d = 3 of 4 ranks; its buddy is 2; survivors 0, 1, 2)
static const int kN = 4, kD = 3;
static long holdersActivation(const struct gdakiHoldHolders& h, bool ok) {  // the activation incarnation or -1
  return (h.any && !h.activated && gdakiHoldHoldersComplete(h, kN, kD) && ok) ? (long)h.inc + 1 : -1;
}

static void runOracle(Builder build, Oracle& o) {
  forEachPt([&](const Pt& p) {
    const struct gdakiLnView v = build(p);
    const struct gdakiLnView ok = buildOk(p);  // the classification key of a difference is the true lineage's
    const uint32_t lo = lowerOf(ok);
    // ---- hold start (H:12770-12863): from ARMED only; HELD(x), HOLDING(d, x), the buddy's own count x ----
    if (p.s == GDAKI_HOLD_ARMED && !p.dec) {
      const long oldv = p.c;                          // gdakiHoldIncOf(v) of the ARMED word
      const long newv = v.cur;                        // gdakiLnOf(r, p).cur
      o.cmp(R_HOLDSTART, ok, p.c, oldv, newv, false);
    }
    for (uint32_t x = lo; x <= ok.cur + 2; x++) {
      // ---- HOLDING at the buddy (H:13077-13079), then the activation check (H:13652-13657, 13264) ----
      for (int any = 0; any < 2; any++)
        for (uint32_t hi = 0; hi <= (any ? 4u : 0u); hi++)
          for (int by = 0; by < (any ? 8 : 1); by++)
            for (int act = 0; act < (any ? 2 : 1); act++)
              for (int from = 0; from < 2; from++) {
                struct gdakiHoldHolders h;
                if (any) {
                  h.any = true;
                  h.inc = hi;
                  h.by.assign(kN, 0);
                  for (int b = 0; b < 3; b++) h.by[(size_t)b] = (uint8_t)((by >> b) & 1);
                  h.activated = act != 0;
                }
                struct gdakiHoldHolders ho = h, hn = h;
                (void)gdakiHoldHoldersAdd(ho, kN, from, x);
                const long oldv =
                  holdersActivation(ho, p.s == GDAKI_HOLD_HELD && p.c == ho.inc);
                if (gdakiLnHoldingAction(v, x) != GDAKI_LN_HOLDING_DROP) (void)gdakiHoldHoldersAdd(hn, kN, from, x);
                const long newv = holdersActivation(hn, gdakiLnActivateOk(v, hn.inc));
                o.cmp(R_HOLDING, ok, x, oldv, newv, false);
              }
      // ---- the activation (H:13264-13289): ACTIVATE inc + 1 and the sequence key ----
      {
        const uint32_t holdersInc = x;
        const long oldv = (p.s == GDAKI_HOLD_HELD && p.c == holdersInc) ? (long)holdersInc * 16 + holdersInc + 1 : -1;
        const long newv = gdakiLnActivateOk(v, holdersInc) ? (long)v.dead * 16 + v.dead + 1 : -1;
        o.cmp(R_ACTIVATE, ok, x, oldv, newv, false);
      }
      // ---- the activation's answer (H:9599, 20581-): only where an activation goes (HELD with holders = dead) ----
      if (p.s == GDAKI_HOLD_HELD)
        for (int rk = 0; rk < 2; rk++) {
          const int ansRank = rk ? kD : 1;
          const long oldv = 1;  // the kind is taken (magic only)
          const long newv = gdakiLnActAnswerOk(kD, v.dead, ansRank, x) ? 1 : 0;
          const bool echoBad = !(ansRank == kD && x == p.c + 1);
          o.cmp(R_ACT_ANSWER, ok, x, oldv, newv, echoBad);
        }
      // ---- the spare registration (H:13279, 15262-15276, 16960-16968): registered of incarnation x ----
      if (p.s == GDAKI_HOLD_HELD) {
        const long oldv = 1;
        const long newv = gdakiLnRegisteredOk(v, x) ? 1 : 0;
        o.cmp(R_SPARE_REG, ok, x, oldv, newv, x != p.c);
      }
      // ---- REJOIN (H:8492-8495 and 9213 FAIL, 13411-13416 drive, 9218 HELD, 4600 known + 1, 13421 after) ----
      {
        long oldv;
        if (p.dec) oldv = 1;  // FAIL
        else if (!(p.s == GDAKI_HOLD_HELD && p.phase == GDAKI_HOLD_P_REJOIN)) oldv = 0;  // waits parked
        else {
          uint32_t q[2] = {7, 8};
          char why[192];
          if (!gdakiRsRejoinValidate(1u, 5, 5, x, p.k, 2, 2, q, q, why, sizeof(why))) oldv = 2;  // refused
          else oldv = (x != p.c + 1) ? 4 : 3;  // accepted; then the drive's check (known' = cell + 1) or the fallback
        }
        long newv;
        const int a = gdakiLnRejoinAction(v, p.phase, x);
        if (a == GDAKI_LN_REJOIN_FAIL) newv = 1;
        else if (a == GDAKI_LN_REJOIN_WAIT) newv = 0;
        else if (a == GDAKI_LN_REJOIN_REFUSE) newv = 2;
        else newv = gdakiLnRejoinAfterOk(gdakiLnViewOf(p.s, p.c, x, p.dec), v.dead) ? 3 : 4;
        o.cmp(R_REJOIN, ok, x, oldv, newv, false);
      }
      // ---- READY (H:9297) and the rkey list (H:9447): taken in HELD, phase READY (the drive and its commit round) ----
      {
        const bool taken = p.s == GDAKI_HOLD_HELD && p.phase == GDAKI_HOLD_P_READY;
        const bool haveAccepted = p.k == p.c + 1;  // an accepted REJOIN of known is in effect
        const long oldv = !taken ? 0 : (haveAccepted && x == p.k) ? 1 : 2;
        const long newv = !taken ? 0 : (haveAccepted && gdakiLnIsCurrent(v, x)) ? 1 : 2;
        o.cmp(R_READY_RKEYS, ok, x, oldv, newv, false);
      }
      // ---- RESTORED (H:13002 gdakiHoldMsgAction restored, 9517 gdakiRsTakeRestored pad = known) ----
      {
        struct gdakiHoldMsgIn in;
        in.restored = true;
        in.state = p.s;
        in.inc = p.c;
        in.msgInc = x;
        const long oldv = (gdakiHoldMsgAction(in) == GDAKI_HOLD_M_RESTORED && x == p.k) ? 1 : 0;
        const long newv = gdakiLnRestoredOk(v, x) ? 1 : 0;
        o.cmp(R_RESTORED, ok, x, oldv, newv, false);
      }
      // ---- INJECTED (H:22465-22467: gdakiMiInjectedCheck with the cell's word) ----
      for (int fmt = 0; fmt < 4; fmt++)
        for (int mi = 0; mi < 2; mi++) {
          const int from = kD, arg = fmt == 1 ? 1 : kD;
          const uint32_t ver = fmt == 2 ? 9u : 1u, senderInc = fmt == 3 ? x + 1 : x;
          const long oldv = gdakiMiInjectedCheck(mi != 0, from, arg, ver, 1u, senderInc, x, p.s, p.c, p.restoredPad);
          const long newv = gdakiLnInjectedCheck(v, mi != 0, from, arg, ver, 1u, senderInc, x, p.restoredPad);
          o.cmp(R_INJECTED, ok, x, oldv, newv, false);
        }
      // ---- DISARM, NOHOLD, FALLBACK (H:13053-13060: gdakiHoldMsgAction with the cell's word) ----
      {
        const uint32_t types[3] = {GDAKI_TS_DISARM, GDAKI_TS_NOHOLD, GDAKI_TS_FALLBACK};
        const int rows[3] = {R_DISARM, R_NOHOLD, R_FALLBACK};
        for (int t = 0; t < 3; t++) {
          struct gdakiHoldMsgIn in;
          in.type = types[t];
          in.state = p.s;
          in.inc = p.c;
          in.msgInc = x;
          in.revivedFromValid = p.rfv;
          in.revivedFrom = p.rf;
          const long oldv = gdakiHoldMsgAction(in);
          const long newv = gdakiLnMsgAction(v, types[t], x, p.rfv, p.rf);
          o.cmp(rows[t], ok, x, oldv, newv, false);
        }
      }
      // ---- STORE_REQ (H:16535-16549: gdakiStoreDropReq with the cell's incarnation, gdakiStoreDropOldInc with known) ----
      {
        const bool held = isHeldS(p.s);
        const long oldv = (gdakiStoreDropReq(p.dec, held, x, p.c) || gdakiStoreDropOldInc(x, p.k)) ? 0 : 1;
        const long newv = gdakiLnStoreServes(v, x) ? 1 : 0;
        const uint32_t cls = gdakiLnClassify(ok, x);
        const bool listed = (ok.phase != GDAKI_LN_ENDED && cls == GDAKI_LN_FUTURE) ||
                            (p.s == GDAKI_HOLD_CANCELLED && !p.dec && x >= p.k);
        o.cmp(R_STORE_REQ, ok, x, oldv, newv, listed);
      }
      // ---- the serve's answer (H:16636-16647: sent as it is; now classified again right before) ----
      {
        const long oldv = 1;
        const long newv = gdakiLnStoreServes(v, x) ? 1 : 0;
        o.cmp(R_SERVE_ANSWER, ok, x, oldv, newv, gdakiLnClassify(ok, x) != GDAKI_LN_CURRENT);
      }
      // ---- the reconnect fencing (H:9110-9114) ----
      {
        const long oldv = (p.k == 0 || x == p.k) ? 1 : 0;
        const long newv = gdakiLnReconnectOk(v, x) ? 1 : 0;
        o.cmp(R_FENCING, ok, x, oldv, newv, false);
      }
    }
    // ---- arming (H:14303-14309 the caller passes the cell's incarnation; H:12932 gdakiHoldArmOk; the CAS writes it) ----
    for (int armed = 0; armed < 2; armed++)
      for (int seqSame = 0; seqSame < 2; seqSame++) {
        const char* w = "";
        const bool okOld = gdakiHoldArmOk(p.s, p.c, p.c, p.dec, armed != 0, 5, seqSame ? 5 : 4, &w);
        const long oldv = okOld ? (long)p.c + 1 : 0;
        const bool okNew = gdakiLnArmOk(v, v.cur, armed != 0, 5, seqSame ? 5 : 4, &w);
        const long newv = okNew ? (long)v.cur + 1 : 0;
        o.cmp(R_ARM, ok, p.c, oldv, newv, false);
      }
    // ---- the current incarnation's source (H:9282, 9509, 14998, 16751, 16982, 20540, 9867: known(q)) ----
    o.cmp(R_CUR_SOURCE, ok, p.k, p.k, v.cur, false);
  });
  // ---- the spare's echo checks (H:9838, 9861, 9922) and a FALLBACK about this restored process (H:13538) ----
  for (uint32_t self = 0; self <= 3; self++) {
    const struct gdakiLnView sv = gdakiLnSelfView(self);
    for (uint32_t x = self >= 2 ? self - 2 : 0; x <= self + 2; x++) {
      o.cmp(R_ECHO, sv, x, x == self ? 1 : 0, gdakiLnIsCurrent(sv, x) ? 1 : 0, false);
      const uint64_t rounds[2] = {(uint64_t)x, (uint64_t)x + (1ull << 32)};
      for (uint64_t round : rounds) {
        const long oldv = (self != 0 && (uint32_t)round + 1u == self) ? 1 : 0;
        const long newv = (self != 0 && gdakiLnSelfFallbackOk(sv, round)) ? 1 : 0;
        o.cmp(R_SELF_FALLBACK, sv, (uint32_t)round + 1u, oldv, newv, false);
      }
    }
  }
}
static void testOracle() {
  Oracle o;
  runOracle(buildOk, o);
  std::set<int> rows;
  for (const Diff& d : o.diffs) rows.insert(d.row);
  const std::set<int> want = {R_ACT_ANSWER, R_SPARE_REG, R_STORE_REQ, R_SERVE_ANSWER};
  CHECK(rows == want);
  CHECK(o.unexpectedInList == 0);
  long total = 0;
  for (int r = 0; r < R_N; r++) {
    total += o.points[r];
    CHECK(o.points[r] > 0);
    printf("oracle row %-27s points %7ld differ %6ld%s\n", kRowName[r], o.points[r], o.differ[r],
           want.count(r) ? "  (listed)" : "");
  }
  // STORE_REQ's differing cells are exactly FUTURE outside ENDED and ENDED's (CANCELLED, not declined)
  std::set<std::pair<uint32_t, uint32_t>> storeCells;
  for (const Diff& d : o.diffs)
    if (d.row == R_STORE_REQ) storeCells.insert({d.phase, d.cls});
  const std::set<std::pair<uint32_t, uint32_t>> storeWant = {{GDAKI_LN_LIVE, GDAKI_LN_FUTURE},
                                                             {GDAKI_LN_HOLD_WAIT, GDAKI_LN_FUTURE},
                                                             {GDAKI_LN_HOLD_SUCC, GDAKI_LN_FUTURE},
                                                             {GDAKI_LN_ENDED, GDAKI_LN_STALE}};
  CHECK(storeCells == storeWant);
  printf("oracle: %ld points, %zu differing (row, phase, class) cells, rows %zu (the design's list: activation answer, "
         "spare registration, STORE_REQ FUTURE and CANCELLED, serve answer); unexpected %ld\n",
         total, o.diffs.size(), rows.size(), o.unexpectedInList);
  for (const Diff& d : o.diffs)
    printf("  differs: %s / %s / %s\n", kRowName[d.row], gdakiLnPhaseName(d.phase), gdakiLnClassName(d.cls));
}

// ---- the BAD domain (apart): known outside {cell, cell + 1}, or OFF/ARMED with known = cell + 1 ----
static void testBad() {
  long n = 0;
  for (uint32_t s : kStates)
    for (uint32_t c = 0; c <= 3; c++)
      for (int dk = -2; dk <= 3; dk++) {
        if ((int)c + dk < 0) continue;
        const uint32_t k = (uint32_t)((int)c + dk);
        const bool bad = !(k == c || k == c + 1) || (isLive(s) && k == c + 1);
        if (!bad) continue;
        const struct gdakiLnView v = gdakiLnViewOf(s, c, k, false);
        n++;
        CHECK(v.phase == GDAKI_LN_BAD && v.cur == k && v.dead == c);
        // classified as LIVE with cur = known: the restored process's STORE_REQ (known) is served (not dropped as
        // STALE: the second death's defect A form, design 2.2)
        CHECK(gdakiLnStoreServes(v, k));
        CHECK(!gdakiLnStoreServes(v, c) || c == k);
        // arming takes the current (known) incarnation
        const char* w = "";
        if (isLive(s)) CHECK(gdakiLnArmOk(v, v.cur, true, 1, 1, &w) && v.cur == k);
        // a held cell of a BAD lineage never activates, and a REJOIN accepted from it fails the after-check unless the
        // lineage became HOLD_SUCC of the cell's + 1
        if (s == GDAKI_HOLD_HELD) {
          CHECK(!gdakiLnActivateOk(v, c));
          CHECK(!gdakiLnRejoinAfterOk(v, c));
        }
      }
  // the second death's case (before the REJOIN_ACK cell write): the spare's cell of a survivor OFF(0), known 1
  const struct gdakiLnView sp = gdakiLnViewOf(GDAKI_HOLD_OFF, 0, 1, false);
  CHECK(sp.phase == GDAKI_LN_BAD && sp.cur == 1 && gdakiLnStoreServes(sp, 1) && !gdakiLnStoreServes(sp, 0));
  printf("BAD views: %ld\n", n);
}

// ---- 4. the callers' mutation ----
static void testMutation() {
  int caught = 0;
  const Builder wrong[2] = {buildCellAsCur, buildKnownAsDead};
  for (int m = 0; m < 2; m++) {
    Oracle o;
    runOracle(wrong[m], o);
    std::set<int> rows;
    for (const Diff& d : o.diffs) rows.insert(d.row);
    const bool fails = o.unexpectedInList > 0 || rows != std::set<int>({R_ACT_ANSWER, R_SPARE_REG, R_STORE_REQ,
                                                                         R_SERVE_ANSWER});
    if (fails) caught++;
    printf("mutation %d (%s): the oracle %s (%ld unexpected differences)\n", m,
           m == 0 ? "the cell's incarnation as the current one" : "known as the dead one", fails ? "fails" : "PASSES",
           o.unexpectedInList);
  }
  CHECK(caught == 2);
}

// ---- 5. the scenes ----
namespace sim {
// One process's state about one rank d (the hold cell, the known incarnation, the declined flag, the drive's phase, the
// buddy's holders, the memos, the park of records without an incarnation).
struct PeerSt {
  struct gdakiHoldCell cell;
  uint32_t known = 0;
  bool declined = false;
  int phase = GDAKI_HOLD_P_REJOIN;
  struct gdakiHoldHolders holders;
  bool revivedFromValid = false;
  uint32_t revivedFrom = 0;
  uint32_t restoredPad = 0;
  bool disarmDuringHold = false;
  std::vector<uint32_t> park;  // record types parked from d
};
struct Proc {
  int rank = 0;
  bool mirror = true;
  int lnLines = 0;          // GIN/LN lines this process wrote
  PeerSt p[kN];
  Builder build = buildOk;  // how the caller makes the view (a mutation passes a wrong one)
  bool oldArmSource = false;  // mutation: arming passes the cell's incarnation (before the lineage)
  bool selfEnded = false;
};
static struct gdakiLnView viewOf(const Proc& P, int d) {
  if (d == P.rank) return gdakiLnSelfView(P.p[d].known);
  Pt pt;
  const uint64_t w = gdakiHoldLoad(P.p[d].cell);
  pt.s = gdakiHoldStateOf(w);
  pt.c = gdakiHoldIncOf(w);
  pt.k = P.p[d].known;
  pt.dec = P.p[d].declined;
  return P.build(pt);
}
static uint32_t stateOf(const Proc& P, int d) { return gdakiHoldStateOf(gdakiHoldLoad(P.p[d].cell)); }
static uint32_t incOf(const Proc& P, int d) { return gdakiHoldIncOf(gdakiHoldLoad(P.p[d].cell)); }
static void setCell(Proc& P, int d, uint32_t s, uint32_t inc) { P.p[d].cell.v.store(gdakiHoldPack(s, inc)); }
static bool arm(Proc& P, int d) {
  const struct gdakiLnView v = viewOf(P, d);
  if (v.phase == GDAKI_LN_BAD) P.lnLines++;
  const uint32_t inc = P.oldArmSource ? incOf(P, d) : v.cur;
  const char* why = "";
  bool ok;
  if (P.oldArmSource) ok = gdakiHoldArmOk(v.cellState, v.cellInc, inc, v.declined, true, 0, 0, &why);
  else ok = gdakiLnArmOk(v, inc, true, 0, 0, &why);
  if (!ok) return false;
  uint64_t e = gdakiHoldLoad(P.p[d].cell);
  return gdakiHoldCas(P.p[d].cell, e, gdakiHoldPack(GDAKI_HOLD_ARMED, inc));
}
// The hold start: ARMED -> HELD of the current incarnation; returns HOLDING's round (the buddy's own count uses it).
static uint32_t holdStart(Proc& P, int d) {
  const uint32_t inc = P.oldArmSource ? incOf(P, d) : viewOf(P, d).cur;
  uint64_t e = gdakiHoldLoad(P.p[d].cell);
  CHECK(gdakiHoldStateOf(e) == GDAKI_HOLD_ARMED);
  CHECK(gdakiHoldCas(P.p[d].cell, e, gdakiHoldPack(GDAKI_HOLD_HELD, inc)));
  P.p[d].phase = GDAKI_HOLD_P_REJOIN;
  P.p[d].disarmDuringHold = false;
  if (gdakiHoldBuddyOf(d, kN) == P.rank) (void)gdakiHoldHoldersAdd(P.p[d].holders, kN, P.rank, inc);
  return inc;
}
// HOLDING(d, x) from `from` at the buddy.
static void holding(Proc& B, int from, int d, uint32_t x) {
  if (gdakiHoldBuddyOf(d, kN) != B.rank) return;
  const struct gdakiLnView v = viewOf(B, d);
  const int a = gdakiLnHoldingAction(v, x);
  if (a == GDAKI_LN_HOLDING_DROP) return;
  if (a == GDAKI_LN_HOLDING_COUNT_FUTURE) B.lnLines++;
  (void)gdakiHoldHoldersAdd(B.p[d].holders, kN, from, x);
}
// The buddy's activation check (every helper step): the incarnation ACTIVATE names, or 0.
static uint32_t activate(Proc& B, int d) {
  struct gdakiHoldHolders& h = B.p[d].holders;
  if (!(h.any && !h.activated && gdakiHoldHoldersComplete(h, kN, d))) return 0;
  const struct gdakiLnView v = viewOf(B, d);
  if (!gdakiLnActivateOk(v, h.inc)) return 0;
  h.activated = true;
  return v.dead + 1;
}
// A spare's REJOIN at survivor S: the lineage's rule, the park check, the acceptance; returns the rule's code.
static int rejoin(Proc& S, int d, uint32_t pad) {
  const struct gdakiLnView v = viewOf(S, d);
  const int a = gdakiLnRejoinAction(v, S.p[d].phase, pad);
  if (a != GDAKI_LN_REJOIN_ACCEPT) return a;
  int left = 0;
  for (uint32_t t : S.p[d].park) left += gdakiLnRecordHasNoInc(t) ? 1 : 0;
  if (left > 0) S.lnLines++;
  S.p[d].park.erase(std::remove_if(S.p[d].park.begin(), S.p[d].park.end(),
                                   [](uint32_t t) { return gdakiLnRecordHasNoInc(t); }),
                    S.p[d].park.end());
  S.p[d].known = pad;
  if (!gdakiLnRejoinAfterOk(viewOf(S, d), v.dead)) return -1;
  S.p[d].phase = GDAKI_HOLD_P_TRANSFER;
  return a;
}
static void commitPublish(Proc& S, int d) {
  S.p[d].phase = GDAKI_HOLD_P_READY;
  CHECK(gdakiHoldCommitMove(S.p[d].cell));
  CHECK(gdakiHoldPublishMove(S.p[d].cell, 1000));
  S.p[d].phase = GDAKI_HOLD_P_PUBLISHED;
}
// RESTORED (mirror off: the promotion; mirror on: recorded only).
static bool restored(Proc& S, int d, uint32_t pad) {
  const struct gdakiLnView v = viewOf(S, d);
  if (!gdakiLnRestoredOk(v, pad)) return false;
  if (S.mirror) {
    S.p[d].restoredPad = pad;
    return true;
  }
  uint32_t from = 0, inc = 0;
  const uint32_t ns = gdakiHoldRestoredState(true, S.p[d].disarmDuringHold, false);
  if (!gdakiHoldRestoreMove(S.p[d].cell, pad, ns, &from, &inc)) return false;
  S.p[d].revivedFromValid = true;
  S.p[d].revivedFrom = inc;
  S.p[d].phase = GDAKI_HOLD_P_REJOIN;
  return true;
}
static bool injected(Proc& S, int d, uint32_t pad) {
  const struct gdakiLnView v = viewOf(S, d);
  if (gdakiLnInjectedCheck(v, S.mirror, d, d, 1u, 1u, pad, pad, S.p[d].restoredPad) != GDAKI_MI_INJ_APPLY) return false;
  uint32_t from = 0, inc = 0;
  const uint32_t ns = gdakiHoldRestoredState(true, S.p[d].disarmDuringHold, false);
  if (!gdakiHoldRestoreMove(S.p[d].cell, pad, ns, &from, &inc)) return false;
  S.p[d].revivedFromValid = true;
  S.p[d].revivedFrom = inc;
  S.p[d].phase = GDAKI_HOLD_P_REJOIN;
  return true;
}
static void fallback(Proc& S, int d) {
  uint32_t from = 0, inc = 0;
  if (gdakiHoldEndMove(S.p[d].cell, GDAKI_HOLD_FALLBACK, &from, &inc)) {
    S.p[d].declined = true;
    S.p[d].phase = GDAKI_HOLD_P_REJOIN;
  }
}
// A record about d from another rank (DISARM, NOHOLD, FALLBACK): the host's moves for each action.
static int msg(Proc& S, uint32_t type, int d, uint32_t x) {
  const struct gdakiLnView v = viewOf(S, d);
  const uint64_t w = gdakiHoldLoad(S.p[d].cell);
  const int a = gdakiLnMsgAction(v, type, x, S.p[d].revivedFromValid, S.p[d].revivedFrom);
  switch (a) {
    case GDAKI_HOLD_M_OFF: {
      uint64_t e = w;
      (void)gdakiHoldCas(S.p[d].cell, e, gdakiHoldPack(GDAKI_HOLD_OFF, gdakiLnCellIncOf(v)));
      break;
    }
    case GDAKI_HOLD_M_DISARM_LATER: S.p[d].disarmDuringHold = true; break;
    case GDAKI_HOLD_M_FALLBACK: fallback(S, d); break;
    case GDAKI_HOLD_M_DECLINE: {
      uint64_t e = w;
      if (gdakiHoldCas(S.p[d].cell, e, gdakiHoldPack(GDAKI_HOLD_FALLBACK, gdakiHoldIncOf(w)))) S.p[d].declined = true;
      break;
    }
    default: break;
  }
  return a;
}
static bool storeServes(Proc& B, int d, uint32_t reqInc) {
  const struct gdakiLnView v = viewOf(B, d);
  if (gdakiLnClassify(v, reqInc) == GDAKI_LN_FUTURE) B.lnLines++;
  return gdakiLnStoreServes(v, reqInc);
}
// The spare's REJOIN_ACK from survivor q of incarnation s: known and (unless the mutation leaves it out) the cell write.
static void spareRejoinAck(Proc& Sp, int q, uint32_t s, bool cellWrite = true) {
  Sp.p[q].known = s;
  if (!cellWrite) return;
  uint64_t e = gdakiHoldPack(GDAKI_HOLD_OFF, 0u);
  if (!gdakiHoldCas(Sp.p[q].cell, e, gdakiHoldPack(GDAKI_HOLD_OFF, s)) && e != gdakiHoldPack(GDAKI_HOLD_OFF, s))
    Sp.lnLines++;
}
// A world of 4 ranks, one process each (index = rank); the spare of rank d replaces procs[d].
struct World {
  Proc procs[kN];
  explicit World(bool mirror) {
    for (int r = 0; r < kN; r++) {
      procs[r].rank = r;
      procs[r].mirror = mirror;
    }
  }
  // the process of rank d becomes its spare of incarnation inc: a fresh process (cells OFF(0), knowns 0), its own known
  void respawn(int d, uint32_t inc) {
    Proc& P = procs[d];
    const bool mi = P.mirror;
    const Builder b = P.build;
    const bool oas = P.oldArmSource;
    P.~Proc();
    new (&P) Proc();
    P.rank = d;
    P.mirror = mi;
    P.build = b;
    P.oldArmSource = oas;
    P.p[d].known = inc;
  }
  int lines() const {
    int n = 0;
    for (const Proc& P : procs) n += P.lnLines;
    return n;
  }
  // every survivor arms d, d dies, the holds start, HOLDING to the buddy, the activation; returns ACTIVATE's incarnation
  uint32_t deathAndActivation(int d, const std::vector<int>& order = {}) {
    const int b = gdakiHoldBuddyOf(d, kN);
    std::vector<int> surv;
    for (int r = 0; r < kN; r++)
      if (r != d) surv.push_back(r);
    const std::vector<int>& ord = order.empty() ? surv : order;
    uint32_t act = 0;
    for (int r : ord) {
      const uint32_t x = holdStart(procs[r], d);
      if (r != b) holding(procs[b], r, d, x);
      if (act == 0) act = activate(procs[b], d);
    }
    return act;
  }
  // the spare of d (incarnation inc) REJOINs every survivor (its REJOIN_ACKs carry their own incarnations)
  bool rejoinAll(int d, uint32_t inc, bool cellWrite = true) {
    bool ok = true;
    std::vector<uint32_t> own(kN, 0);
    for (int r = 0; r < kN; r++) own[(size_t)r] = procs[r].p[r].known;
    respawn(d, inc);
    for (int r = 0; r < kN; r++) {
      if (r == d) continue;
      ok = ok && rejoin(procs[r], d, inc) == GDAKI_LN_REJOIN_ACCEPT;
      spareRejoinAck(procs[d], r, own[(size_t)r], cellWrite);
    }
    return ok;
  }
  void publishAll(int d) {
    for (int r = 0; r < kN; r++)
      if (r != d) commitPublish(procs[r], d);
  }
  bool promoteAll(int d, uint32_t inc) {  // RESTORED (mirror off) or RESTORED + INJECTED (mirror on)
    bool ok = true;
    for (int r = 0; r < kN; r++) {
      if (r == d) continue;
      ok = ok && restored(procs[r], d, inc);
      if (procs[r].mirror) ok = ok && injected(procs[r], d, inc);
    }
    return ok;
  }
  bool allLive(int d, uint32_t inc) const {
    for (int r = 0; r < kN; r++) {
      if (r == d) continue;
      const struct gdakiLnView v = viewOf(procs[r], d);
      if (!(v.phase == GDAKI_LN_LIVE && v.cur == inc)) return false;
    }
    return true;
  }
};
}  // namespace sim

static int gScenes = 0;
// first death, mirror off and on: LIVE -> HOLD_WAIT ('later' changes nothing) -> HOLD_SUCC -> PUBLISHED -> LIVE(1)
static void sceneFirstDeath(bool mirror) {
  sim::World w(mirror);
  for (int r = 0; r < 3; r++) CHECK(sim::arm(w.procs[r], 3));
  CHECK(w.deathAndActivation(3) == 1);
  for (int r = 0; r < 3; r++) CHECK(sim::viewOf(w.procs[r], 3).phase == GDAKI_LN_HOLD_WAIT);
  // 'later': the buddy asks again; nothing moves (the activation is done once ACCEPTED; before it, HELD stays)
  CHECK(sim::viewOf(w.procs[2], 3).phase == GDAKI_LN_HOLD_WAIT);
  CHECK(w.rejoinAll(3, 1));
  for (int r = 0; r < 3; r++) {
    const struct gdakiLnView v = sim::viewOf(w.procs[r], 3);
    CHECK(v.phase == GDAKI_LN_HOLD_SUCC && v.dead == 0 && v.cur == 1);
    CHECK(gdakiLnClassify(v, 1) == GDAKI_LN_CURRENT && gdakiLnClassify(v, 0) == GDAKI_LN_HELD_OLD);
  }
  // the spare's view of every survivor: LIVE of its own incarnation after the REJOIN_ACK cell write
  for (int r = 0; r < 3; r++) CHECK(sim::viewOf(w.procs[3], r).phase == GDAKI_LN_LIVE);
  w.publishAll(3);
  CHECK(w.promoteAll(3, 1));
  CHECK(w.allLive(3, 1));
  CHECK(w.lines() == 0);
  gScenes++;
}
// defect A (mirror on): PUBLISHED(i) with i + 1 known: STORE_REQ(i + 1, seq 1) served before INJECTED; STORE_REQ(i, any
// seq) dropped; both wrong callers drop the restored process's first request (the scene catches them)
static void sceneDefectA() {
  for (uint32_t i = 0; i < 3; i++) {
    int caught = 0;
    for (int m = 0; m < 3; m++) {
      sim::World w(true);
      for (int r = 0; r < kN; r++) w.procs[r].build = m == 0 ? buildOk : m == 1 ? buildCellAsCur : buildKnownAsDead;
      // the ward 3 at incarnation i (as if restored i times), every survivor armed of it
      for (int r = 0; r < 3; r++) {
        sim::setCell(w.procs[r], 3, GDAKI_HOLD_OFF, i);
        w.procs[r].p[3].known = i;
        CHECK(sim::arm(w.procs[r], 3) || m != 0);
      }
      w.procs[3].p[3].known = i;
      if (w.deathAndActivation(3) != i + 1 && m == 0) CHECK(false);
      if (!w.rejoinAll(3, i + 1) && m == 0) CHECK(false);
      w.publishAll(3);
      sim::Proc& b = w.procs[2];  // the ward's buddy
      for (int r = 0; r < 3; r++) (void)sim::restored(w.procs[r], 3, i + 1);
      const bool newServed = sim::storeServes(b, 3, i + 1);
      const bool oldDropped = !sim::storeServes(b, 3, i);
      if (m == 0) {
        CHECK(sim::stateOf(b, 3) == GDAKI_HOLD_PUBLISHED);
        CHECK(newServed && oldDropped);
        CHECK(sim::injected(b, 3, i + 1));
        CHECK(sim::storeServes(b, 3, i + 1) && !sim::storeServes(b, 3, i));  // after INJECTED: LIVE(i + 1), i STALE
      } else if (!newServed) {
        caught++;
      }
    }
    CHECK(caught == 2);
  }
  gScenes++;
}
// the buddy's own count and the others' HOLDING in every order: one activation of dead + 1; a STALE HOLDING is not
// counted; a FUTURE one is counted with a GIN/LN line
static void sceneCounting() {
  const std::vector<std::vector<int>> orders = {{0, 1, 2}, {2, 0, 1}, {1, 2, 0}, {0, 2, 1}};
  for (const auto& ord : orders) {
    sim::World w(false);
    for (int r = 0; r < 3; r++) CHECK(sim::arm(w.procs[r], 3));
    CHECK(w.deathAndActivation(3, ord) == 1);
    CHECK(sim::activate(w.procs[2], 3) == 0);  // once
    CHECK(w.lines() == 0);
  }
  {  // a HOLDING arriving while the buddy is still LIVE (its own death evidence later): CURRENT, counted
    sim::World w(false);
    for (int r = 0; r < 3; r++) CHECK(sim::arm(w.procs[r], 3));
    sim::holding(w.procs[2], 0, 3, sim::holdStart(w.procs[0], 3));
    CHECK(w.procs[2].p[3].holders.any && w.procs[2].p[3].holders.inc == 0);
    sim::holding(w.procs[2], 1, 3, sim::holdStart(w.procs[1], 3));
    CHECK(sim::activate(w.procs[2], 3) == 0);  // the buddy does not hold it yet
    (void)sim::holdStart(w.procs[2], 3);
    CHECK(sim::activate(w.procs[2], 3) == 1);
    // a STALE HOLDING (an older incarnation) after that: not counted, no line
    sim::World w2(false);
    sim::setCell(w2.procs[2], 3, GDAKI_HOLD_HELD, 2);
    w2.procs[2].p[3].known = 2;
    sim::holding(w2.procs[2], 0, 3, 1);
    CHECK(!w2.procs[2].p[3].holders.any && w2.lines() == 0);
    // a FUTURE one: counted (as before) with a GIN/LN line
    sim::holding(w2.procs[2], 0, 3, 3);
    CHECK(w2.procs[2].p[3].holders.any && w2.procs[2].p[3].holders.inc == 3 && w2.lines() == 1);
  }
  gScenes++;
}
static const uint32_t kReady = 35u;  // the spare's READY (impl/rs_spare_api.h: REJOIN 32 .. RESTORED 37)
// the park check at the REJOIN's acceptance: in HELD the dead process's records without an incarnation are taken before
// the activation (the helper step), so none is left: no line; a synthetic one left behind is dropped with a line
static void scenePark() {
  for (int violate = 0; violate < 2; violate++) {
    sim::World w(true);
    for (int r = 0; r < 3; r++) CHECK(sim::arm(w.procs[r], 3));
    // the dead process's last CKPT_STABLE (15) and a STORE_REQ (50) parked at rank 0, taken in HELD before the activation
    w.procs[0].p[3].park = {GDAKI_TS_CKPT_STABLE, GDAKI_TS_STORE_REQ};
    CHECK(w.deathAndActivation(3) == 1);
    if (!violate) w.procs[0].p[3].park.clear();  // the helper step's takes (H:13611-13616, 13658)
    w.procs[0].p[3].park.push_back(kReady);  // a record with an incarnation stays parked
    CHECK(w.rejoinAll(3, 1));
    CHECK(w.lines() == violate);
    CHECK(w.procs[0].p[3].park.size() == 1 && w.procs[0].p[3].park[0] == kReady);
  }
  gScenes++;
}
// the buddy restored, then a second death (mi4_kill2_kill3_ow): the spare of rank 2 (incarnation 1) writes its cells of
// the survivors at their REJOIN_ACKs; every one of its views is LIVE; it then arms rank 3 and is rank 3's buddy. The
// third incarnation: rank 2 dies again after it was re-armed (a model of the re-arm): with the cell write the count
// fills and ACTIVATE(2) goes; without it and with the old arming source (the cell's incarnation 0) the buddy's own count
// is 0 against the others' 1 and nothing is activated (hidden problem 2); without it but with the lineage's source the
// BAD lineage is named by a GIN/LN line and the count fills.
static void sceneSecondDeath() {
  for (int variant = 0; variant < 3; variant++) {
    const bool cellWrite = variant == 0, oldSource = variant == 1;
    sim::World w(true);
    for (int r = 0; r < kN; r++) w.procs[r].oldArmSource = oldSource;
    // rank 2 dies first and is restored as incarnation 1
    for (int r : {0, 1, 3}) CHECK(sim::arm(w.procs[r], 2));
    CHECK(w.deathAndActivation(2) == 1);
    CHECK(w.rejoinAll(2, 1, cellWrite));
    w.publishAll(2);
    CHECK(w.promoteAll(2, 1));
    CHECK(w.allLive(2, 1));
    if (cellWrite)
      for (int q : {0, 1, 3}) CHECK(sim::viewOf(w.procs[2], q).phase == GDAKI_LN_LIVE);
    else
      CHECK(sim::viewOf(w.procs[2], 0).phase == GDAKI_LN_LIVE);  // incarnation 0 survivors: OFF(0) known 0 anyway
    // rank 3 dies (incarnation 0) and is restored as 1: its buddy is the revived rank 2
    for (int r : {0, 1, 2}) CHECK(sim::arm(w.procs[r], 3));
    CHECK(w.deathAndActivation(3) == 1);
    CHECK(w.rejoinAll(3, 1, cellWrite));
    w.publishAll(3);
    CHECK(w.promoteAll(3, 1));
    CHECK(w.allLive(3, 1));
    // the revived rank 3's views: rank 2 is incarnation 1
    const struct gdakiLnView v32 = sim::viewOf(w.procs[3], 2);
    if (cellWrite) CHECK(v32.phase == GDAKI_LN_LIVE && v32.cur == 1);
    else CHECK(v32.phase == GDAKI_LN_BAD && v32.cur == 1);
    // the second death's store request of rank 2 (incarnation 1) at its new buddy rank 3: served (BAD uses known)
    CHECK(sim::storeServes(w.procs[3], 2, 1));
    // the third incarnation: rank 2 re-armed everywhere, dies again
    for (int r : {0, 1, 3}) CHECK(sim::arm(w.procs[r], 2));
    const uint32_t act = w.deathAndActivation(2);
    if (variant == 0) CHECK(act == 2 && w.lines() == 0);
    if (variant == 1) CHECK(act == 0);  // hidden problem 2: no activation (the deadline's fallback)
    if (variant == 2) CHECK(act == 2 && w.lines() > 0);
  }
  gScenes++;
}
// the fallback after the REJOIN (mi4_kill3_ow_sampled): HOLD_SUCC -> ENDED; FALLBACK(d, dead) to the others, who held
// it (HELD_OLD): their fallback; a later REJOIN of the declined rank: FAIL; the spare's own end on FALLBACK about itself
static void sceneFallbackAfterRejoin() {
  sim::World w(false);
  for (int r = 0; r < 3; r++) CHECK(sim::arm(w.procs[r], 3));
  CHECK(w.deathAndActivation(3) == 1);
  CHECK(w.rejoinAll(3, 1));
  sim::fallback(w.procs[0], 3);  // the export refused at rank 0
  CHECK(sim::viewOf(w.procs[0], 3).phase == GDAKI_LN_ENDED);
  for (int r : {1, 2}) {
    CHECK(sim::msg(w.procs[r], GDAKI_TS_FALLBACK, 3, 0) == GDAKI_HOLD_M_FALLBACK);
    CHECK(sim::viewOf(w.procs[r], 3).phase == GDAKI_LN_ENDED);
  }
  CHECK(gdakiLnRejoinAction(sim::viewOf(w.procs[1], 3), GDAKI_HOLD_P_REJOIN, 1) == GDAKI_LN_REJOIN_FAIL);
  // the spare (incarnation 1): FALLBACK about itself with round 0 -> its own end; an older restore's (round 5 + 1 != 1)
  // is stale
  CHECK(gdakiLnSelfFallbackOk(gdakiLnSelfView(1), 0) && !gdakiLnSelfFallbackOk(gdakiLnSelfView(1), 5));
  // a STORE_REQ of either process to the declined ward's buddy: dropped
  CHECK(!sim::storeServes(w.procs[2], 3, 1) && !sim::storeServes(w.procs[2], 3, 0));
  gScenes++;
}
// the activation without an answer (rs4_kill3_spareabsent), 'later' then the deadline: HOLD_WAIT; TIMED_OUT_HELD stops
// the activation and the REJOIN's acceptance (a state condition); then the fallback and FALLBACK to the others
static void sceneNoAnswerAndTimedOutHeld() {
  sim::World w(false);
  for (int r = 0; r < 3; r++) CHECK(sim::arm(w.procs[r], 3));
  CHECK(w.deathAndActivation(3) == 1);
  w.procs[2].p[3].holders.activated = false;  // 'later' or no answer: asked again
  w.procs[2].p[3].cell.deadlineUs.store(10);
  uint32_t inc = 0;
  CHECK(gdakiHoldWatchMove(w.procs[2].p[3].cell, 20, &inc) == GDAKI_HOLD_W_TIMEOUT_HELD);
  CHECK(sim::viewOf(w.procs[2], 3).phase == GDAKI_LN_HOLD_WAIT);  // the phase stays; the state condition stops
  CHECK(sim::activate(w.procs[2], 3) == 0);
  CHECK(gdakiLnRejoinAction(sim::viewOf(w.procs[2], 3), GDAKI_HOLD_P_REJOIN, 1) == GDAKI_LN_REJOIN_WAIT);
  sim::fallback(w.procs[2], 3);
  for (int r : {0, 1}) CHECK(sim::msg(w.procs[r], GDAKI_TS_FALLBACK, 3, 0) == GDAKI_HOLD_M_FALLBACK);
  // the two-strike rule's input: an answer that names another incarnation counts as none
  CHECK(!gdakiLnActAnswerOk(3, 0, 3, 2) && !gdakiLnActAnswerOk(3, 0, 2, 1) && gdakiLnActAnswerOk(3, 0, 3, 1));
  // the spare registration must be the dead incarnation's
  const struct gdakiLnView v = gdakiLnViewOf(GDAKI_HOLD_HELD, 1, 1, false);
  CHECK(gdakiLnRegisteredOk(v, 1) && !gdakiLnRegisteredOk(v, 0) && !gdakiLnRegisteredOk(v, 2));
  gScenes++;
}
// the activation ACCEPTED, then the FETCH handshake failed (gdakiHoldActivate's FETCH_FAILED): the buddy's fallback,
// HOLD_WAIT -> ENDED; FALLBACK(d, dead) ends the other holds; the spare that FETCHed nothing gets FAIL to its REJOIN
static void sceneFetchFailed() {
  sim::World w(true);
  for (int r = 0; r < 3; r++) CHECK(sim::arm(w.procs[r], 3));
  CHECK(w.deathAndActivation(3) == 1);
  sim::fallback(w.procs[2], 3);
  CHECK(sim::viewOf(w.procs[2], 3).phase == GDAKI_LN_ENDED);
  for (int r : {0, 1}) CHECK(sim::msg(w.procs[r], GDAKI_TS_FALLBACK, 3, 0) == GDAKI_HOLD_M_FALLBACK);
  for (int r = 0; r < 3; r++)
    CHECK(gdakiLnRejoinAction(sim::viewOf(w.procs[r], 3), GDAKI_HOLD_P_REJOIN, 1) == GDAKI_LN_REJOIN_FAIL);
  CHECK(w.lines() == 0);
  gScenes++;
}
// the dead process's parked STORE_REQ: dropped in HOLD_WAIT and HOLD_SUCC (HELD_OLD) and after the promotion (STALE)
static void sceneParkedStoreReq() {
  sim::World w(true);
  sim::Proc& b = w.procs[2];
  for (int r = 0; r < 3; r++) CHECK(sim::arm(w.procs[r], 3));
  CHECK(w.deathAndActivation(3) == 1);
  CHECK(!sim::storeServes(b, 3, 0));
  CHECK(w.rejoinAll(3, 1));
  CHECK(!sim::storeServes(b, 3, 0) && sim::storeServes(b, 3, 1));
  w.publishAll(3);
  CHECK(w.promoteAll(3, 1));
  CHECK(!sim::storeServes(b, 3, 0) && sim::storeServes(b, 3, 1));
  CHECK(w.lines() == 0);
  gScenes++;
}
// a stale STORE_ACK (the hidden problem 1, a synthetic state): the buddy served the ward's request (incarnation 0, seq k
// >= 2: an armed process already had one answer) while the ward died; the new process (incarnation 1) has its own seq k
// outstanding (it got there by retries); the old serve ends after the REJOIN: classified again, it is HELD_OLD and not
// sent. Without the re-check the new process would take it (its request machine sees only the seq).
static void sceneStaleStoreAck() {
  for (uint64_t k = 2; k <= 4; k++) {
    sim::World w(true);
    sim::Proc& b = w.procs[2];
    for (int r = 0; r < 3; r++) CHECK(sim::arm(w.procs[r], 3));
    CHECK(sim::storeServes(b, 3, 0));  // dispatched while LIVE(0)
    CHECK(w.deathAndActivation(3) == 1);
    CHECK(w.rejoinAll(3, 1));
    // the new process's request machine with seq k outstanding
    struct gdakiStoreUp u;
    u.sent(true, k, 0.0, 30 << 20, 0x100, gdakiStoreSlotBytes(30 << 20), 0);
    struct gdakiStoreAck a;
    memset(&a, 0, sizeof(a));
    a.version = GDAKI_MI_WIRE_VERSION;
    a.seq = k;
    a.ok = 1;
    a.gen = 7;
    a.slotBytes = gdakiStoreSlotBytes(30 << 20);
    a.slotOff[0] = 0;
    a.slotOff[1] = a.slotBytes;
    a.up.qpn = 0x55;
    a.up.mtu = 5;
    const bool send = gdakiLnStoreServes(sim::viewOf(b, 3), 0);  // the serve's answer, classified again
    CHECK(!send);
    struct gdakiStoreUp u2 = u;  // the mutation: sent as before
    CHECK(u2.onAck(a, k, 1.0) == GDAKI_STORE_A_OK);  // taken as the new process's own answer: what the re-check stops
    CHECK(u.reqOut);  // without it, the new process still waits for its own answer
  }
  gScenes++;
}
// TIMED_OUT_PUBLISHED: a RESTORED (mirror off) or an INJECTED (mirror on) read before the helper's fallback wins
static void sceneTimedOutPublished(bool mirror) {
  sim::World w(mirror);
  for (int r = 0; r < 3; r++) CHECK(sim::arm(w.procs[r], 3));
  CHECK(w.deathAndActivation(3) == 1);
  CHECK(w.rejoinAll(3, 1));
  w.publishAll(3);
  sim::Proc& s = w.procs[0];
  if (mirror) CHECK(sim::restored(s, 3, 1));
  s.p[3].cell.deadlineUs.store(10);
  uint32_t inc = 0;
  CHECK(gdakiHoldWatchMove(s.p[3].cell, 20, &inc) == GDAKI_HOLD_W_TIMEOUT_PUBLISHED);
  CHECK(sim::viewOf(s, 3).phase == GDAKI_LN_HOLD_SUCC);
  if (mirror) CHECK(sim::injected(s, 3, 1));
  else CHECK(sim::restored(s, 3, 1));
  CHECK(sim::viewOf(s, 3).phase == GDAKI_LN_LIVE && sim::viewOf(s, 3).cur == 1);
  gScenes++;
}
// CANCELLED (abort, revoke, an aborting shrink): ENDED; a STORE_REQ of either incarnation is dropped (before: the
// known one's was served: one of the listed differences, not reached); a REJOIN waits parked (not HELD)
static void sceneCancelled() {
  for (int afterRejoin = 0; afterRejoin < 2; afterRejoin++) {
    sim::World w(true);
    for (int r = 0; r < 3; r++) CHECK(sim::arm(w.procs[r], 3));
    CHECK(w.deathAndActivation(3) == 1);
    if (afterRejoin) CHECK(w.rejoinAll(3, 1));
    uint32_t from = 0, inc = 0;
    CHECK(gdakiHoldEndMove(w.procs[2].p[3].cell, GDAKI_HOLD_CANCELLED, &from, &inc));
    const struct gdakiLnView v = sim::viewOf(w.procs[2], 3);
    CHECK(v.phase == GDAKI_LN_ENDED);
    CHECK(!gdakiLnStoreServes(v, 0) && !gdakiLnStoreServes(v, 1));
    CHECK(!gdakiStoreDropOldInc(v.known, v.known));  // before: served (the listed CANCELLED difference)
    CHECK(gdakiLnRejoinAction(v, GDAKI_HOLD_P_REJOIN, 1) == GDAKI_LN_REJOIN_WAIT);
  }
  gScenes++;
}
// NOHOLD: an armed rank declined without a hold (weak evidence) goes OFF and NOHOLD(d, c) goes out; a receiver that has
// it ARMED goes OFF, one that holds it falls back, a stale or future one changes nothing
static void sceneNoHold() {
  sim::World w(false);
  for (int r = 0; r < 3; r++) CHECK(sim::arm(w.procs[r], 3));
  (void)sim::holdStart(w.procs[1], 3);  // rank 1 holds it (strong evidence there)
  // rank 0 declines it without a hold: OFF
  {
    uint64_t e = gdakiHoldLoad(w.procs[0].p[3].cell);
    CHECK(gdakiHoldCas(w.procs[0].p[3].cell, e, gdakiHoldPack(GDAKI_HOLD_OFF, 0)));
  }
  CHECK(sim::msg(w.procs[2], GDAKI_TS_NOHOLD, 3, 0) == GDAKI_HOLD_M_OFF && sim::stateOf(w.procs[2], 3) == GDAKI_HOLD_OFF);
  CHECK(sim::msg(w.procs[1], GDAKI_TS_NOHOLD, 3, 0) == GDAKI_HOLD_M_FALLBACK);
  CHECK(sim::viewOf(w.procs[1], 3).phase == GDAKI_LN_ENDED);
  sim::World w2(false);
  CHECK(sim::arm(w2.procs[0], 3));
  CHECK(sim::msg(w2.procs[0], GDAKI_TS_NOHOLD, 3, 1) == GDAKI_HOLD_M_NONE);  // FUTURE: ignored
  CHECK(sim::stateOf(w2.procs[0], 3) == GDAKI_HOLD_ARMED);
  gScenes++;
}
// a DISARM during the hold: applied at the promotion (OFF of the new incarnation); a DISARM of a live rank: OFF
static void sceneDisarmDuringHold() {
  sim::World w(false);
  for (int r = 0; r < 3; r++) CHECK(sim::arm(w.procs[r], 3));
  CHECK(w.deathAndActivation(3) == 1);
  CHECK(sim::msg(w.procs[0], GDAKI_TS_DISARM, 3, 7) == GDAKI_HOLD_M_DISARM_LATER);  // the round is not read
  CHECK(w.rejoinAll(3, 1));
  w.publishAll(3);
  CHECK(w.promoteAll(3, 1));
  CHECK(sim::stateOf(w.procs[0], 3) == GDAKI_HOLD_OFF && sim::incOf(w.procs[0], 3) == 1);
  CHECK(sim::arm(w.procs[1], 3) && sim::msg(w.procs[1], GDAKI_TS_DISARM, 3, 0) == GDAKI_HOLD_M_OFF);
  gScenes++;
}
// survivors in different phases (the spare serves them one at a time): rank 0 HOLD_SUCC, rank 1 HOLD_WAIT; FALLBACK(d,
// dead) ends both (HELD_OLD in both); a DISARM is applied later in both
static void sceneDifferentPhases() {
  sim::World w(false);
  for (int r = 0; r < 3; r++) CHECK(sim::arm(w.procs[r], 3));
  CHECK(w.deathAndActivation(3) == 1);
  CHECK(sim::rejoin(w.procs[0], 3, 1) == GDAKI_LN_REJOIN_ACCEPT);
  CHECK(sim::viewOf(w.procs[0], 3).phase == GDAKI_LN_HOLD_SUCC && sim::viewOf(w.procs[1], 3).phase == GDAKI_LN_HOLD_WAIT);
  CHECK(sim::msg(w.procs[0], GDAKI_TS_DISARM, 3, 0) == GDAKI_HOLD_M_DISARM_LATER);
  CHECK(sim::msg(w.procs[1], GDAKI_TS_DISARM, 3, 0) == GDAKI_HOLD_M_DISARM_LATER);
  // a FALLBACK naming the successor (CURRENT at rank 0, FUTURE at rank 1) is ignored by both
  CHECK(sim::msg(w.procs[0], GDAKI_TS_FALLBACK, 3, 1) == GDAKI_HOLD_M_NONE);
  CHECK(sim::msg(w.procs[1], GDAKI_TS_FALLBACK, 3, 1) == GDAKI_HOLD_M_NONE);
  CHECK(sim::msg(w.procs[0], GDAKI_TS_FALLBACK, 3, 0) == GDAKI_HOLD_M_FALLBACK);
  CHECK(sim::msg(w.procs[1], GDAKI_TS_FALLBACK, 3, 0) == GDAKI_HOLD_M_FALLBACK);
  // a STORE_REQ of the successor at the buddy (rank 2, HOLD_WAIT still): FUTURE there, dropped with a line
  CHECK(!sim::storeServes(w.procs[2], 3, 1) && w.lines() == 1);
  gScenes++;
}
// the revived process's own end after RESTORED (gdakiHoldSelfEnd with FALLBACK(self, self - 1)): a survivor that took
// its RESTORED (LIVE(1), revived from 0) declines incarnation 1 (P2); one still PUBLISHED(0) (HOLD_SUCC) falls back
static void sceneRevivedSelfEnd() {
  sim::World w(false);
  for (int r = 0; r < 3; r++) CHECK(sim::arm(w.procs[r], 3));
  CHECK(w.deathAndActivation(3) == 1);
  CHECK(w.rejoinAll(3, 1));
  w.publishAll(3);
  CHECK(sim::restored(w.procs[0], 3, 1) && sim::restored(w.procs[1], 3, 1));
  CHECK(sim::msg(w.procs[0], GDAKI_TS_FALLBACK, 3, 0) == GDAKI_HOLD_M_DECLINE);
  CHECK(sim::stateOf(w.procs[0], 3) == GDAKI_HOLD_FALLBACK && w.procs[0].p[3].declined);
  CHECK(sim::viewOf(w.procs[0], 3).phase == GDAKI_LN_ENDED);
  CHECK(sim::msg(w.procs[2], GDAKI_TS_FALLBACK, 3, 0) == GDAKI_HOLD_M_FALLBACK);  // still PUBLISHED(0): HELD_OLD
  // rank 1 armed it again meanwhile (LIVE(1) ARMED): P2 too
  CHECK(sim::arm(w.procs[1], 3) && sim::msg(w.procs[1], GDAKI_TS_FALLBACK, 3, 0) == GDAKI_HOLD_M_DECLINE);
  gScenes++;
}
// the reconnect fencing: HOLD_WAIT takes the dead process's pad (its socket is still the rank's), HOLD_SUCC only the
// successor's; incarnation 0 takes any pad; ENDED takes the current one (as before)
static void sceneFencing() {
  CHECK(gdakiLnReconnectOk(gdakiLnViewOf(GDAKI_HOLD_HELD, 1, 1, false), 1));
  CHECK(!gdakiLnReconnectOk(gdakiLnViewOf(GDAKI_HOLD_HELD, 1, 1, false), 2));
  CHECK(!gdakiLnReconnectOk(gdakiLnViewOf(GDAKI_HOLD_HELD, 1, 2, false), 1));
  CHECK(gdakiLnReconnectOk(gdakiLnViewOf(GDAKI_HOLD_HELD, 1, 2, false), 2));
  CHECK(gdakiLnReconnectOk(gdakiLnViewOf(GDAKI_HOLD_HELD, 0, 0, false), 5));
  CHECK(gdakiLnReconnectOk(gdakiLnViewOf(GDAKI_HOLD_CANCELLED, 1, 2, false), 2));
  CHECK(!gdakiLnReconnectOk(gdakiLnViewOf(GDAKI_HOLD_CANCELLED, 1, 2, false), 1));
  gScenes++;
}
// a FUTURE echo at the spare (a survivor that names an incarnation ahead of the spare's own): not taken
static void sceneSpareEcho() {
  const struct gdakiLnView s = gdakiLnSelfView(1);
  CHECK(gdakiLnIsCurrent(s, 1) && !gdakiLnIsCurrent(s, 0) && !gdakiLnIsCurrent(s, 2));
  CHECK(gdakiLnClassify(s, 2) == GDAKI_LN_FUTURE);
  // the records the park check names
  for (uint32_t t = 0; t < 64; t++)
    CHECK(gdakiLnRecordHasNoInc(t) == ((t >= 11 && t <= 15) || (t >= 48 && t <= 51)));
  gScenes++;
}

int main() {
  testViews();
  testClassify();
  testOracle();
  testBad();
  testMutation();
  sceneFirstDeath(false);
  sceneFirstDeath(true);
  sceneDefectA();
  sceneCounting();
  scenePark();
  sceneSecondDeath();
  sceneFallbackAfterRejoin();
  sceneNoAnswerAndTimedOutHeld();
  sceneFetchFailed();
  sceneParkedStoreReq();
  sceneStaleStoreAck();
  sceneTimedOutPublished(false);
  sceneTimedOutPublished(true);
  sceneCancelled();
  sceneNoHold();
  sceneDisarmDuringHold();
  sceneDifferentPhases();
  sceneRevivedSelfEnd();
  sceneFencing();
  sceneSpareEcho();
  printf("scenes: %d\n", gScenes);
  printf("mi_unit_lineage: %ld checks, %ld failed\n", gChecks, gFailed);
  return gFailed == 0 ? 0 : 1;
}
