// rs_unit_host.cc - CPU unit test of the host branch's hold state machine (work package 7; EXPERIMENT.md 9.10.7) and,
// later, of the checkpoint's accounting (work package 5). No NCCL, no CUDA, no network.
// Built by impl/build_rs_host.sh unith: impl/rs_hold_api.h (the shared interface) and the region "gin-restore hold: pure
// functions" cut from the working tree's gin_host_gdaki.cc (rs_hold_pure.inc), with g++ -std=c++17, ASan and UBSan.
// What it checks:
//   1. every state against every event of 9.10.7, through the pure decisions the host code asks (decline, record,
//      REQ, helper-socket record, watcher, helper step, arming, RESTORED's state), as an explicit expected table;
//   2. the paths of 9.10.7 end to end on a cell with the host code's own moves (gdakiHoldEndMove, CommitMove,
//      PublishMove, WatchMove, RestoreMove: success, deadlines in HELD and in PUBLISHED, RESTORED read first, FALLBACK
//      crossing RESTORED, NOHOLD, cancel, second death, TOLD against a parked RESTORED);
//   3. the deadline compare-and-swap rules with two threads (helper vs watcher), many times, on the same moves: exactly
//      one wins, the CPU writes happen only when the watcher won from HELD, COMMITTING is never touched, RESTORED wins over
//      a timed-out publish, no compare-and-swap of one hold hits another (incarnation in the word);
//   4. the parking rule (the deferral of every wait): restore records 11..63 only, arrival order and the drain's choice
//      (gdakiHoldDrainTakes, R1), the cap and the age limit, the wait (gdakiHoldRecvParked) on a simulated clock;
//   5. the deadlines' arithmetic, the time the parked device threads' clock started, and the buddy's holder count.
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include <thread>
#include <vector>
#include <algorithm>
#define GDAKI_HOLD_API_NO_ENTRY_DECLS
#include "rs_hold_api.h"
// hk's helper-socket types the tests use (gin_host_gdaki.cc)
enum { GDAKI_TS_HELLO = 1, GDAKI_TS_REQ = 2, GDAKI_TS_ACK = 3, GDAKI_TS_NACK = 4, GDAKI_TS_DONE = 5, GDAKI_TS_FAIL = 6,
       GDAKI_TS_BYE = 10 };
#include "rs_hold_pure.inc"

static long gChecks = 0, gFailed = 0;
#define CHECK(c)                                                                     \
  do {                                                                               \
    gChecks++;                                                                       \
    if (!(c)) {                                                                      \
      gFailed++;                                                                     \
      if (gFailed <= 40) fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); \
    }                                                                                \
  } while (0)

static const uint32_t kStates[] = {GDAKI_HOLD_OFF,
                                   GDAKI_HOLD_ARMED,
                                   GDAKI_HOLD_HELD,
                                   GDAKI_HOLD_COMMITTING,
                                   GDAKI_HOLD_PUBLISHED,
                                   GDAKI_HOLD_TIMED_OUT_HELD,
                                   GDAKI_HOLD_TIMED_OUT_PUBLISHED,
                                   GDAKI_HOLD_FALLBACK,
                                   GDAKI_HOLD_CANCELLED};
static bool isHeld(uint32_t s) {  // written out again: the test's own reading of 9.10.7
  return s == GDAKI_HOLD_HELD || s == GDAKI_HOLD_COMMITTING || s == GDAKI_HOLD_PUBLISHED ||
         s == GDAKI_HOLD_TIMED_OUT_HELD || s == GDAKI_HOLD_TIMED_OUT_PUBLISHED;
}
static bool isQuiet(uint32_t s) {
  return s == GDAKI_HOLD_HELD || s == GDAKI_HOLD_COMMITTING || s == GDAKI_HOLD_TIMED_OUT_HELD;
}
static bool isPublished(uint32_t s) { return s == GDAKI_HOLD_PUBLISHED || s == GDAKI_HOLD_TIMED_OUT_PUBLISHED; }

// ---- 1. the transition table ----
static void testPredicatesAndPacking() {
  for (uint32_t s : kStates) {
    CHECK(gdakiHoldIsHeldState(s) == isHeld(s));
    CHECK(gdakiHoldIsQuietState(s) == isQuiet(s));
    CHECK(strcmp(gdakiHoldStateName(s), "?") != 0);
    for (uint32_t inc : {0u, 1u, 7u, 0x7fffffffu, 0xffffffffu}) {
      const uint64_t v = gdakiHoldPack(s, inc);
      CHECK(gdakiHoldStateOf(v) == s && gdakiHoldIncOf(v) == inc);
    }
  }
  CHECK(strcmp(gdakiHoldStateName(99), "?") == 0);
  // the incarnation separates holds: a compare-and-swap expecting (HELD, i) fails on (HELD, i + 1)
  struct gdakiHoldCell c;
  c.v.store(gdakiHoldPack(GDAKI_HOLD_HELD, 4));
  uint64_t e = gdakiHoldPack(GDAKI_HOLD_HELD, 3);
  CHECK(!gdakiHoldCas(c, e, gdakiHoldPack(GDAKI_HOLD_TIMED_OUT_HELD, 3)));
  CHECK(e == gdakiHoldPack(GDAKI_HOLD_HELD, 4));
  CHECK(gdakiHoldCas(c, e, gdakiHoldPack(GDAKI_HOLD_COMMITTING, 4)));
  CHECK(gdakiHoldLoad(c) == gdakiHoldPack(GDAKI_HOLD_COMMITTING, 4));
  // record types: the restore's are 11..63 (host 11..20, dev 21..31, spare 32..47), hk's are not
  for (uint32_t t = 0; t < 80; t++) CHECK(gdakiHoldIsRestoreRecord(t) == (t >= 11 && t <= 63));
  CHECK(GDAKI_TS_CKPT_PAUSE == 11 && GDAKI_TS_FALLBACK == 19 && GDAKI_TS_HOST_RESERVED == 20);
  CHECK(GDAKI_TS_NACK_RESTORING == 17);
  // the buddy
  for (int n = 2; n <= 9; n++)
    for (int p = 0; p < n; p++) {
      const int b = gdakiHoldBuddyOf(p, n);
      CHECK(b >= 0 && b < n && b != p);
      if ((p ^ 1) < n) CHECK(b == (p ^ 1));
    }
  CHECK(gdakiHoldBuddyOf(3, 4) == 2 && gdakiHoldBuddyOf(1, 4) == 0 && gdakiHoldBuddyOf(2, 3) == 0);
  CHECK(gdakiHoldBuddyOf(0, 1) == -1);
  CHECK(gdakiHoldStrongCause("FIN") && gdakiHoldStrongCause("ECONNREFUSED"));
  for (const char* c : {"BYE", "BADMAGIC", "ECONNRESET", "ETIMEDOUT", "errno104", "", "FAIL", "unknown"})
    CHECK(!gdakiHoldStrongCause(c));
  CHECK(!gdakiHoldStrongCause(nullptr));
}

static struct gdakiHoldDeclineIn allGood(uint32_t s) {
  struct gdakiHoldDeclineIn in;
  in.state = s;
  in.policyHold = in.commArmed = in.deathEvidence = in.strongCause = in.buddyReachable = true;
  in.lostAfterCommit = in.told = in.otherHeld = false;
  return in;
}
static void testDeclineTable() {
  // G2 (R1, RL1, N4, Q1, 9.10.5): every state x every combination of the nine facts
  for (uint32_t s : kStates)
    for (int bits = 0; bits < 512; bits++) {
      struct gdakiHoldDeclineIn in;
      in.state = s;
      in.policyHold = bits & 1;
      in.commArmed = bits & 2;
      in.deathEvidence = bits & 4;
      in.strongCause = bits & 8;
      in.lostAfterCommit = bits & 16;
      in.told = bits & 32;
      in.otherHeld = bits & 64;
      in.buddyReachable = bits & 128;
      in.stopping = bits & 256;
      const char* why = nullptr;
      bool fb = true;
      const int a = gdakiHoldDeclineAction(in, &why, &fb);
      int want;
      if (isHeld(s)) want = GDAKI_HOLD_D_FALLBACK;  // (가): any decline of a held peer is its fallback
      else if (s != GDAKI_HOLD_ARMED) want = GDAKI_HOLD_D_PASS;
      else if (!in.stopping && in.policyHold && in.commArmed && in.deathEvidence && in.strongCause &&
               !in.lostAfterCommit && !in.told && !in.otherHeld && in.buddyReachable)
        want = GDAKI_HOLD_D_START;  // (나)
      else want = GDAKI_HOLD_D_PASS_NOHOLD;  // N4: an ARMED peer declined without a hold
      CHECK(a == want);
      CHECK(why != nullptr);
      if (a == GDAKI_HOLD_D_PASS_NOHOLD) CHECK(why[0] != '\0');
      // a second failure while another peer is held ends that hold (single failure scope), never for the held peer itself
      CHECK(fb == (!isHeld(s) && in.otherHeld));
    }
  // the reasons name the first missing condition
  const char* why;
  bool fb;
  struct gdakiHoldDeclineIn in = allGood(GDAKI_HOLD_ARMED);
  in.lostAfterCommit = true;
  CHECK(gdakiHoldDeclineAction(in, &why, &fb) == GDAKI_HOLD_D_PASS_NOHOLD && strstr(why, "commit") != nullptr);
  in = allGood(GDAKI_HOLD_ARMED);
  in.strongCause = false;
  CHECK(gdakiHoldDeclineAction(in, &why, &fb) == GDAKI_HOLD_D_PASS_NOHOLD && strstr(why, "weak") != nullptr);
  in = allGood(GDAKI_HOLD_ARMED);
  in.told = true;
  CHECK(gdakiHoldDeclineAction(in, &why, &fb) == GDAKI_HOLD_D_PASS_NOHOLD && strstr(why, "application") != nullptr);
  in = allGood(GDAKI_HOLD_ARMED);
  in.stopping = true;  // the teardown: no new hold, NOHOLD so the other survivors do not wait for this rank
  CHECK(gdakiHoldDeclineAction(in, &why, &fb) == GDAKI_HOLD_D_PASS_NOHOLD && strstr(why, "stopping") != nullptr);
}

static void testMsgTable() {
  // DISARM, NOHOLD, HOLDING, FALLBACK about p and the spare's RESTORED, every state, incarnations around the cell's
  const uint32_t types[] = {GDAKI_TS_DISARM, GDAKI_TS_NOHOLD, GDAKI_TS_HOLDING, GDAKI_TS_FALLBACK, GDAKI_TS_CKPT_PAUSE,
                            GDAKI_TS_PAUSED, GDAKI_TS_CKPT_STABLE, GDAKI_TS_HOST_RESERVED};
  for (uint32_t s : kStates)
    for (uint32_t inc : {0u, 1u, 5u})
      for (int dm = -2; dm <= 2; dm++)
        for (int rv = 0; rv < 3; rv++) {  // revived: none, from inc - 1, from something else
          if ((int)inc + dm < 0) continue;
          const uint32_t mi = (uint32_t)((int)inc + dm);
          struct gdakiHoldMsgIn in;
          in.state = s;
          in.inc = inc;
          in.msgInc = mi;
          in.revivedFromValid = rv != 0;
          in.revivedFrom = rv == 1 ? inc - 1u : inc + 7u;
          for (uint32_t t : types) {
            in.type = t;
            in.restored = false;
            const int a = gdakiHoldMsgAction(in);
            int want = GDAKI_HOLD_M_NONE;
            if (t == GDAKI_TS_DISARM) want = isHeld(s) ? GDAKI_HOLD_M_DISARM_LATER : s == GDAKI_HOLD_ARMED ? GDAKI_HOLD_M_OFF
                                                                                                       : GDAKI_HOLD_M_NONE;
            else if (t == GDAKI_TS_NOHOLD) {
              if (mi == inc) want = isHeld(s) ? GDAKI_HOLD_M_FALLBACK : s == GDAKI_HOLD_ARMED ? GDAKI_HOLD_M_OFF
                                                                                               : GDAKI_HOLD_M_NONE;
            } else if (t == GDAKI_TS_HOLDING) want = GDAKI_HOLD_M_HOLDING;
            else if (t == GDAKI_TS_FALLBACK) {
              const bool revived = rv == 1 && inc >= 1 && mi == inc - 1u;  // this rank revived the incarnation named
              if (isHeld(s)) want = (mi == inc || revived) ? GDAKI_HOLD_M_FALLBACK : GDAKI_HOLD_M_NONE;  // P2 when held
              else if ((s == GDAKI_HOLD_ARMED || s == GDAKI_HOLD_OFF) && revived)
                want = GDAKI_HOLD_M_DECLINE;  // P2: it revived that incarnation
              else if (s == GDAKI_HOLD_ARMED && mi == inc) want = GDAKI_HOLD_M_OFF;  // Q1: never held here: OFF only
            }
            CHECK(a == want);
          }
          // RESTORED (pad = i + 1)
          in.type = 37;
          in.restored = true;
          const int a = gdakiHoldMsgAction(in);
          CHECK(a == ((isPublished(s) && mi == inc + 1u) ? GDAKI_HOLD_M_RESTORED : GDAKI_HOLD_M_NONE));
        }
}

static void testWatcherRouteReqStepArm() {
  // G8: deadlines; COMMITTING is never touched (N1); TIMED_OUT_* and the others are left as they are
  for (uint32_t s : kStates)
    for (int64_t dl : {(int64_t)0, (int64_t)1000, (int64_t)2000})
      for (int64_t now : {(int64_t)999, (int64_t)1000, (int64_t)5000}) {
        const int a = gdakiHoldWatchdogAction(s, dl, now);
        int want = GDAKI_HOLD_W_NONE;
        if (dl != 0 && now >= dl) {
          if (s == GDAKI_HOLD_HELD) want = GDAKI_HOLD_W_TIMEOUT_HELD;
          if (s == GDAKI_HOLD_PUBLISHED) want = GDAKI_HOLD_W_TIMEOUT_PUBLISHED;
        }
        CHECK(a == want);
      }
  // G4: records
  for (uint32_t s : kStates)
    for (uint32_t ep : {0u, 2u, 4u, 6u})
      for (uint32_t cov : {0u, 4u}) {
        const int a = gdakiHoldRouteAction(s, ep, cov);
        int want = GDAKI_HOLD_R_ROUTE;
        if (isQuiet(s)) want = GDAKI_HOLD_R_ABSORB;
        else if (isPublished(s)) want = ep < cov ? GDAKI_HOLD_R_STALE : GDAKI_HOLD_R_FALLBACK;
        CHECK(a == want);
      }
  // RL20: REQs
  for (uint32_t s : kStates) {
    const int a = gdakiHoldReqAction(s);
    CHECK(a == (isPublished(s) ? GDAKI_HOLD_Q_NACK_FALLBACK : isHeld(s) ? GDAKI_HOLD_Q_NACK : GDAKI_HOLD_Q_ANSWER));
  }
  // RL4: the helper's step for the held peer, every state x every combination
  for (uint32_t s : kStates)
    for (int bits = 0; bits < 16; bits++) {
      struct gdakiHoldStepIn in;
      in.state = s;
      in.cancelled = bits & 1;
      in.told = bits & 2;
      in.pendingFallback = bits & 4;
      in.commLost = bits & 8;
      const char* why = nullptr;
      const int a = gdakiHoldStepAction(in, &why);
      int want;
      if (!isHeld(s)) want = GDAKI_HOLD_S_NONE;
      else if (in.cancelled) want = GDAKI_HOLD_S_CANCEL;  // 9.10.5 priority 1: the application's choice wins
      else if (in.pendingFallback || in.told || in.commLost) want = GDAKI_HOLD_S_FALLBACK;  // priority 2, single failure
      else if (s == GDAKI_HOLD_TIMED_OUT_HELD) want = GDAKI_HOLD_S_FALLBACK;             // priority 4: the deadline
      else if (s == GDAKI_HOLD_TIMED_OUT_PUBLISHED) want = GDAKI_HOLD_S_RESTORED_FIRST;  // Q2: below TOLD
      else if (s == GDAKI_HOLD_COMMITTING) want = GDAKI_HOLD_S_FALLBACK;
      else want = GDAKI_HOLD_S_DRIVE;
      CHECK(a == want);
      CHECK(why != nullptr);
      if (a == GDAKI_HOLD_S_FALLBACK || a == GDAKI_HOLD_S_CANCEL) CHECK(why[0] != '\0');
      // taken before the held peer's parked records are handed over: exactly the cancel and the fallbacks
      CHECK(gdakiHoldStepBeforeRecords(a) == (a == GDAKI_HOLD_S_CANCEL || a == GDAKI_HOLD_S_FALLBACK));
    }
  // arming
  for (uint32_t s : kStates)
    for (int bits = 0; bits < 8; bits++)
      for (uint32_t cur : {0u, 2u})
        for (uint32_t inc : {1u, 2u, 3u}) {
          const bool declined = bits & 1, comm = bits & 2, seqSame = bits & 4;
          const char* why = nullptr;
          const bool ok = gdakiHoldArmOk(s, cur, inc, declined, comm, 5, seqSame ? 5 : 4, &why);
          const bool want = !isHeld(s) && s != GDAKI_HOLD_FALLBACK && s != GDAKI_HOLD_CANCELLED && !declined && comm &&
                            seqSame && inc >= cur;
          CHECK(ok == want);
          if (!ok) CHECK(why != nullptr && why[0] != '\0');
        }
  // RESTORED's next state (P5)
  for (int bits = 0; bits < 8; bits++) {
    const uint32_t ns = gdakiHoldRestoredState(bits & 1, bits & 2, bits & 4);
    CHECK(ns == (((bits & 1) && !(bits & 2) && (bits & 4)) ? GDAKI_HOLD_ARMED : GDAKI_HOLD_OFF));
  }
}

// ---- 2. the paths of 9.10.7 on one cell, with the host code's own moves ----
// The decisions and the compare-and-swap moves are the pure region's (the same functions the host code calls); what the
// host code does around them (the decline, the CPU writes, the records it sends) is counted here.
struct Model {
  struct gdakiHoldCell c;
  bool wordRaised = false, asyncRaised = false;  // the watcher's CPU writes (HELD timeout)
  int declines = 0, fallbacks = 0, nohold = 0, fallbackRecords = 0, cpuWrites = 0;
  bool revivedValid = false;
  uint32_t revivedFrom = 0;
  bool parkedRestored = false;  // a RESTORED (pad = parkedPad) waits in the held peer's park
  uint32_t parkedPad = 0;
  uint32_t st() const { return gdakiHoldStateOf(gdakiHoldLoad(c)); }
  uint32_t inc() const { return gdakiHoldIncOf(gdakiHoldLoad(c)); }
  void fallback() {  // gdakiHoldFallback
    uint32_t from = 0, i = 0;
    const bool moved = gdakiHoldEndMove(c, GDAKI_HOLD_FALLBACK, &from, &i);
    CHECK(moved == isHeld(from));  // unconditional: the check count does not depend on a race's outcome
    if (!moved) return;
    c.deadlineUs.store(0);
    fallbacks++;
    fallbackRecords++;
    declines++;  // the PeerDead decline that follows (its G2 passes: FALLBACK is not held)
  }
  // a decline toward the peer: G2
  void decline(bool strong, bool told = false, bool otherHeld = false, bool death = true) {
    struct gdakiHoldDeclineIn in = allGood(st());
    in.strongCause = strong;
    in.told = told;
    in.otherHeld = otherHeld;
    in.deathEvidence = death;
    const char* why;
    bool fb;
    switch (gdakiHoldDeclineAction(in, &why, &fb)) {
      case GDAKI_HOLD_D_FALLBACK: fallback(); break;
      case GDAKI_HOLD_D_START: {
        uint64_t v = gdakiHoldLoad(c);
        c.deadlineUs.store(0);
        CHECK(gdakiHoldCas(c, v, gdakiHoldPack(GDAKI_HOLD_HELD, gdakiHoldIncOf(v))));
        break;
      }
      case GDAKI_HOLD_D_PASS_NOHOLD: {
        uint64_t v = gdakiHoldLoad(c);
        CHECK(gdakiHoldCas(c, v, gdakiHoldPack(GDAKI_HOLD_OFF, gdakiHoldIncOf(v))));
        nohold++;
        declines++;
        break;
      }
      default: declines++;
    }
  }
  void watcher(int64_t nowUs) {  // gdakiHoldWatchdog
    uint32_t i = 0;
    if (gdakiHoldWatchMove(c, nowUs, &i) == GDAKI_HOLD_W_TIMEOUT_HELD) {
      wordRaised = asyncRaised = true;
      cpuWrites++;
    }
  }
  bool commitCas() { return gdakiHoldCommitMove(c); }                      // gdakiHoldBeforeCommitPoint
  void published(int64_t deadline) { (void)gdakiHoldPublishMove(c, deadline); }  // gdakiHoldAfterPublish
  bool restored(uint32_t pad, bool armOk) {  // gdakiHoldApplyRestored
    uint32_t from = 0, i = 0;
    if (!gdakiHoldRestoreMove(c, pad, gdakiHoldRestoredState(armOk, false, armOk), &from, &i)) return false;
    CHECK(isPublished(from) && pad == i + 1u);
    revivedValid = true;
    revivedFrom = i;
    c.deadlineUs.store(0);
    return true;
  }
  void msg(uint32_t type, uint32_t mi) {  // gdakiHoldOnMsg
    struct gdakiHoldMsgIn in;
    in.type = type;
    in.state = st();
    in.inc = inc();
    in.msgInc = mi;
    in.revivedFromValid = revivedValid;
    in.revivedFrom = revivedFrom;
    uint64_t v = gdakiHoldLoad(c);
    switch (gdakiHoldMsgAction(in)) {
      case GDAKI_HOLD_M_OFF: (void)gdakiHoldCas(c, v, gdakiHoldPack(GDAKI_HOLD_OFF, in.inc)); break;
      case GDAKI_HOLD_M_FALLBACK: fallback(); break;
      case GDAKI_HOLD_M_DECLINE:
        if (gdakiHoldCas(c, v, gdakiHoldPack(GDAKI_HOLD_FALLBACK, in.inc))) declines++;
        break;
      default: break;
    }
  }
  // gdakiHoldStep for the held peer: the action first; unless it is a cancel or a fallback, the peer's parked records
  // (here: a parked RESTORED) are handed over and the action is asked again
  void step(bool cancelled, bool told) {
    struct gdakiHoldStepIn in;
    in.state = st();
    in.cancelled = cancelled;
    in.told = told;
    const char* why;
    int a = gdakiHoldStepAction(in, &why);
    if (!gdakiHoldStepBeforeRecords(a)) {
      if (parkedRestored) {
        parkedRestored = false;
        (void)restored(parkedPad, true);
      }
      in.state = st();
      a = gdakiHoldStepAction(in, &why);
    }
    switch (a) {
      case GDAKI_HOLD_S_CANCEL: {
        uint32_t from = 0, i = 0;
        (void)gdakiHoldEndMove(c, GDAKI_HOLD_CANCELLED, &from, &i);
        break;
      }
      case GDAKI_HOLD_S_FALLBACK: fallback(); break;
      case GDAKI_HOLD_S_RESTORED_FIRST:
        if (st() == GDAKI_HOLD_TIMED_OUT_PUBLISHED) fallback();
        break;
      default: break;
    }
  }
};
static void testPaths() {
  {  // success: ARMED(0) -> HELD(0) -> COMMITTING -> PUBLISHED -> RESTORED -> ARMED(1)
    Model m;
    m.c.v.store(gdakiHoldPack(GDAKI_HOLD_ARMED, 0));
    m.decline(true);
    CHECK(m.st() == GDAKI_HOLD_HELD && m.inc() == 0 && m.declines == 0);
    m.c.deadlineUs.store(1000);
    m.watcher(999);
    CHECK(m.st() == GDAKI_HOLD_HELD && !m.wordRaised);
    CHECK(m.commitCas() && m.st() == GDAKI_HOLD_COMMITTING);
    m.watcher(5000);  // COMMITTING: never touched
    CHECK(m.st() == GDAKI_HOLD_COMMITTING && !m.wordRaised);
    m.published(10000);
    CHECK(m.st() == GDAKI_HOLD_PUBLISHED);
    CHECK(!m.restored(0, true) && m.st() == GDAKI_HOLD_PUBLISHED);  // RESTORED of the wrong incarnation: ignored
    CHECK(m.restored(1, true) && m.st() == GDAKI_HOLD_ARMED && m.inc() == 1 && m.c.deadlineUs.load() == 0);
    CHECK(m.fallbacks == 0 && m.declines == 0 && m.cpuWrites == 0);
    // a second death of incarnation 1 holds again (P5 with the conditions)
    m.decline(true);
    CHECK(m.st() == GDAKI_HOLD_HELD && m.inc() == 1);
  }
  {  // RESTORED without the arming conditions: OFF(1); a death then declines fail-fast without NOHOLD
    Model m;
    m.c.v.store(gdakiHoldPack(GDAKI_HOLD_ARMED, 0));
    m.decline(true);
    CHECK(m.commitCas());
    m.published(10000);
    CHECK(m.restored(1, false) && m.st() == GDAKI_HOLD_OFF && m.inc() == 1);
    m.decline(true);
    CHECK(m.st() == GDAKI_HOLD_OFF && m.declines == 1 && m.nohold == 0);
  }
  {  // the deadline in HELD: TIMED_OUT_HELD with the CPU writes, then the helper's fallback; the commit CAS loses
    Model m;
    m.c.v.store(gdakiHoldPack(GDAKI_HOLD_ARMED, 3));
    m.decline(true);
    m.c.deadlineUs.store(1000);
    m.watcher(1000);
    CHECK(m.st() == GDAKI_HOLD_TIMED_OUT_HELD && m.wordRaised && m.asyncRaised && m.cpuWrites == 1);
    m.watcher(2000);  // once
    CHECK(m.cpuWrites == 1);
    CHECK(!m.commitCas());  // the restore round fails before its commit point
    m.step(false, true);  // told (the word is up) and timed out: the fallback either way
    CHECK(m.st() == GDAKI_HOLD_FALLBACK && m.inc() == 3 && m.fallbacks == 1 && m.declines == 1);
    m.decline(true);  // never held again (FALLBACK is final for the incarnation)
    CHECK(m.st() == GDAKI_HOLD_FALLBACK && m.declines == 2);
  }
  {  // the deadline in PUBLISHED: state alone; a RESTORED read first still wins (Q2)
    Model m;
    m.c.v.store(gdakiHoldPack(GDAKI_HOLD_ARMED, 0));
    m.decline(true);
    CHECK(m.commitCas());
    m.published(1000);
    m.watcher(1000);
    CHECK(m.st() == GDAKI_HOLD_TIMED_OUT_PUBLISHED && !m.wordRaised && m.cpuWrites == 0);
    CHECK(m.restored(1, true) && m.st() == GDAKI_HOLD_ARMED && m.inc() == 1 && m.fallbacks == 0);
  }
  {  // the deadline in PUBLISHED, no RESTORED: the fallback
    Model m;
    m.c.v.store(gdakiHoldPack(GDAKI_HOLD_ARMED, 0));
    m.decline(true);
    CHECK(m.commitCas());
    m.published(1000);
    m.watcher(1000);
    m.step(false, false);
    CHECK(m.st() == GDAKI_HOLD_FALLBACK && m.fallbacks == 1);
  }
  {  // P2: FALLBACK of incarnation 0 after this rank took RESTORED: the revived incarnation 1 is declined
    Model m;
    m.c.v.store(gdakiHoldPack(GDAKI_HOLD_ARMED, 0));
    m.decline(true);
    CHECK(m.commitCas());
    m.published(9000);
    CHECK(m.restored(1, true));
    m.msg(GDAKI_TS_FALLBACK, 0);
    CHECK(m.st() == GDAKI_HOLD_FALLBACK && m.inc() == 1 && m.declines == 1);
  }
  {  // P2 the other way: FALLBACK first (in PUBLISHED), RESTORED later is ignored
    Model m;
    m.c.v.store(gdakiHoldPack(GDAKI_HOLD_ARMED, 0));
    m.decline(true);
    CHECK(m.commitCas());
    m.published(9000);
    m.msg(GDAKI_TS_FALLBACK, 0);
    CHECK(m.st() == GDAKI_HOLD_FALLBACK && m.fallbacks == 1);
    CHECK(!m.restored(1, true) && m.st() == GDAKI_HOLD_FALLBACK);
  }
  {  // Q1: a FALLBACK or NOHOLD of an incarnation this rank did not hold: OFF only, no decline
    Model m;
    m.c.v.store(gdakiHoldPack(GDAKI_HOLD_ARMED, 2));
    m.msg(GDAKI_TS_FALLBACK, 2);
    CHECK(m.st() == GDAKI_HOLD_OFF && m.declines == 0);
    m.c.v.store(gdakiHoldPack(GDAKI_HOLD_ARMED, 2));
    m.msg(GDAKI_TS_NOHOLD, 1);  // stale
    CHECK(m.st() == GDAKI_HOLD_ARMED);
    m.msg(GDAKI_TS_NOHOLD, 2);
    CHECK(m.st() == GDAKI_HOLD_OFF && m.declines == 0);
  }
  {  // N4: a NOHOLD of the held incarnation: the fallback
    Model m;
    m.c.v.store(gdakiHoldPack(GDAKI_HOLD_ARMED, 0));
    m.decline(true);
    m.msg(GDAKI_TS_NOHOLD, 0);
    CHECK(m.st() == GDAKI_HOLD_FALLBACK && m.fallbacks == 1);
  }
  {  // weak evidence on an ARMED peer: fail-fast and NOHOLD; a held peer's decline of any kind: its fallback (V1)
    Model m;
    m.c.v.store(gdakiHoldPack(GDAKI_HOLD_ARMED, 0));
    m.decline(false);
    CHECK(m.st() == GDAKI_HOLD_OFF && m.nohold == 1 && m.declines == 1);
    Model n;
    n.c.v.store(gdakiHoldPack(GDAKI_HOLD_ARMED, 0));
    n.decline(true);
    n.decline(false, false, false, false);  // e.g. a scan's "a device waiter gave up" (Local, DECLINED)
    CHECK(n.st() == GDAKI_HOLD_FALLBACK && n.fallbacks == 1);
  }
  {  // cancel (abort, revoke, shrink): CANCELLED from any held state, no decline
    for (uint32_t s : {GDAKI_HOLD_HELD, GDAKI_HOLD_PUBLISHED, GDAKI_HOLD_TIMED_OUT_HELD, GDAKI_HOLD_TIMED_OUT_PUBLISHED}) {
      Model m;
      m.c.v.store(gdakiHoldPack(s, 4));
      m.step(true, true);
      CHECK(m.st() == GDAKI_HOLD_CANCELLED && m.inc() == 4 && m.declines == 0);
    }
  }
  {  // TOLD while HELD or PUBLISHED: the fallback
    for (uint32_t s : {GDAKI_HOLD_HELD, GDAKI_HOLD_PUBLISHED}) {
      Model m;
      m.c.v.store(gdakiHoldPack(s, 0));
      m.step(false, true);
      CHECK(m.st() == GDAKI_HOLD_FALLBACK);
    }
  }
  {  // 9.10.5: TOLD in PUBLISHED or TIMED_OUT_PUBLISHED with a RESTORED parked: the fallback, the RESTORED is not applied
    for (uint32_t s : {GDAKI_HOLD_PUBLISHED, GDAKI_HOLD_TIMED_OUT_PUBLISHED}) {
      Model m;
      m.c.v.store(gdakiHoldPack(s, 2));
      m.parkedRestored = true;
      m.parkedPad = 3;
      m.step(false, true);
      CHECK(m.st() == GDAKI_HOLD_FALLBACK && m.inc() == 2 && m.fallbacks == 1 && !m.revivedValid);
    }
  }
  {  // Q2: no TOLD, the deadline passed in PUBLISHED, a RESTORED parked: the RESTORED wins
    Model m;
    m.c.v.store(gdakiHoldPack(GDAKI_HOLD_TIMED_OUT_PUBLISHED, 2));
    m.parkedRestored = true;
    m.parkedPad = 3;
    m.step(false, false);
    CHECK(m.st() == GDAKI_HOLD_ARMED && m.inc() == 3 && m.fallbacks == 0 && m.revivedValid && m.revivedFrom == 2);
    // and a parked RESTORED in PUBLISHED on time: applied in the same step, no fallback
    Model n;
    n.c.v.store(gdakiHoldPack(GDAKI_HOLD_PUBLISHED, 0));
    n.parkedRestored = true;
    n.parkedPad = 1;
    n.step(false, false);
    CHECK(n.st() == GDAKI_HOLD_ARMED && n.inc() == 1 && n.fallbacks == 0);
  }
  {  // P2 when the revived incarnation is held again: a late FALLBACK of the old one is the new hold's fallback
    Model m;
    m.c.v.store(gdakiHoldPack(GDAKI_HOLD_ARMED, 0));
    m.decline(true);
    CHECK(m.commitCas());
    m.published(9000);
    CHECK(m.restored(1, true) && m.st() == GDAKI_HOLD_ARMED && m.inc() == 1);
    m.decline(true);  // incarnation 1 died: held
    CHECK(m.st() == GDAKI_HOLD_HELD && m.inc() == 1);
    m.msg(GDAKI_TS_FALLBACK, 0);  // another survivor gave up the restore of incarnation 0
    CHECK(m.st() == GDAKI_HOLD_FALLBACK && m.inc() == 1 && m.fallbacks == 1);
    m.msg(GDAKI_TS_FALLBACK, 7);  // anything else about it: nothing
    CHECK(m.fallbacks == 1);
  }
  {  // the end move: nothing from a state that is not held; the state it found is reported
    for (uint32_t s : kStates) {
      struct gdakiHoldCell c;
      c.v.store(gdakiHoldPack(s, 6));
      uint32_t from = 99, i = 99;
      const bool moved = gdakiHoldEndMove(c, GDAKI_HOLD_CANCELLED, &from, &i);
      CHECK(moved == isHeld(s) && from == s && i == 6);
      CHECK(gdakiHoldStateOf(gdakiHoldLoad(c)) == (moved ? GDAKI_HOLD_CANCELLED : s));
    }
    // the commit move: a peer that is not held is not a restore round (true, unchanged)
    for (uint32_t s : kStates) {
      struct gdakiHoldCell c;
      c.v.store(gdakiHoldPack(s, 1));
      const bool ok = gdakiHoldCommitMove(c);
      CHECK(ok == (!isHeld(s) || s == GDAKI_HOLD_HELD));
      CHECK(gdakiHoldStateOf(gdakiHoldLoad(c)) == (s == GDAKI_HOLD_HELD ? GDAKI_HOLD_COMMITTING : s));
    }
    // the publish move: COMMITTING only, deadline first
    for (uint32_t s : kStates) {
      struct gdakiHoldCell c;
      c.v.store(gdakiHoldPack(s, 1));
      const bool ok = gdakiHoldPublishMove(c, 777);
      CHECK(ok == (s == GDAKI_HOLD_COMMITTING));
      CHECK(c.deadlineUs.load() == (ok ? 777 : 0));
    }
  }
}

// ---- 3. the compare-and-swap rules with two threads ----
static void testRaces() {
  const int rounds = 20000;
  int helperWon = 0, watcherWon = 0;
  for (int i = 0; i < rounds; i++) {  // HELD: the helper's commit CAS against the watcher's deadline
    Model m;
    m.c.v.store(gdakiHoldPack(GDAKI_HOLD_HELD, (uint32_t)i));
    m.c.deadlineUs.store(1);
    std::atomic<int> ready{0};
    bool won = false;
    auto meet = [&] {
      ready.fetch_add(1);
      while (ready.load() < 2) {}
    };
    std::thread w([&] {
      meet();
      if (i & 1) for (volatile int k = 0; k < (i % 7) * 10; k++) {}
      m.watcher(2);
    });
    std::thread hlp([&] {
      meet();
      if (!(i & 1)) for (volatile int k = 0; k < (i % 7) * 10; k++) {}
      won = m.commitCas();
    });
    w.join();
    hlp.join();
    const uint32_t s = m.st();
    CHECK(won == (s == GDAKI_HOLD_COMMITTING));
    CHECK(won != (s == GDAKI_HOLD_TIMED_OUT_HELD));
    CHECK(m.cpuWrites == (s == GDAKI_HOLD_TIMED_OUT_HELD ? 1 : 0));  // CPU writes only when the watcher won
    CHECK(m.inc() == (uint32_t)i);
    // the same number of checks whoever won (the run's check count is then the same every time)
    m.watcher(100);
    if (won) {
      helperWon++;
      CHECK(m.st() == GDAKI_HOLD_COMMITTING && m.cpuWrites == 0);  // COMMITTING stays untouched afterwards
    } else {
      watcherWon++;
      CHECK(m.st() == GDAKI_HOLD_TIMED_OUT_HELD && m.cpuWrites == 1);  // the CPU writes once
    }
    m.step(false, !won);  // the watcher's writes are TOLD; a COMMITTING left at a helper step falls back either way
    CHECK(m.st() == GDAKI_HOLD_FALLBACK);
  }
  CHECK(helperWon + watcherWon == rounds);
  int restoredWins = 0, fbWatcherFirst = 0;
  for (int i = 0; i < rounds; i++) {  // PUBLISHED: RESTORED against the deadline: RESTORED always wins when read first
    Model m;
    m.c.v.store(gdakiHoldPack(GDAKI_HOLD_PUBLISHED, 0));
    m.c.deadlineUs.store(1);
    std::atomic<int> ready{0};
    bool ok = false;
    auto meet = [&] {
      ready.fetch_add(1);
      while (ready.load() < 2) {}
    };
    std::thread w([&] {
      meet();
      m.watcher(2);
    });
    std::thread hlp([&] {
      meet();
      if (i & 1) for (volatile int k = 0; k < (i % 7) * 10; k++) {}
      ok = m.restored(1, true);
    });
    w.join();
    hlp.join();
    CHECK(ok && m.st() == GDAKI_HOLD_ARMED && m.inc() == 1 && m.cpuWrites == 0 && m.fallbacks == 0);
    restoredWins += ok;
  }
  CHECK(restoredWins == rounds);
  for (int i = 0; i < rounds; i++) {  // HELD: the helper's fallback against the watcher: one fallback, writes iff it won
    Model m;
    m.c.v.store(gdakiHoldPack(GDAKI_HOLD_HELD, 9));
    m.c.deadlineUs.store(1);
    std::atomic<int> ready{0};
    auto meet = [&] {
      ready.fetch_add(1);
      while (ready.load() < 2) {}
    };
    std::thread w([&] {
      meet();
      m.watcher(2);
    });
    std::thread hlp([&] {
      meet();
      m.fallback();
    });
    w.join();
    hlp.join();
    CHECK(m.st() == GDAKI_HOLD_FALLBACK && m.inc() == 9 && m.fallbacks == 1 && m.cpuWrites <= 1);
    fbWatcherFirst += m.cpuWrites;
  }
  printf("races: fallback after the watcher's timeout %d of %d\n", fbWatcherFirst, rounds);
  printf("races: commit CAS won by the helper %d, by the watcher %d of %d\n", helperWon, watcherWon, rounds);
}

// ---- 4. the parking rule ----
struct Msg {
  uint32_t type;
  int32_t arg;
  uint64_t round;
  int id;
};
static void testPark() {
  struct gdakiHoldPark<Msg> pk;
  uint32_t dt = 0;
  int id = 0;
  // arrival order: DISARM, READY, RESTORED, NOHOLD, a FALLBACK about this rank (5), HOLDING
  const uint32_t seq[] = {GDAKI_TS_DISARM, 35, 37, GDAKI_TS_NOHOLD, GDAKI_TS_FALLBACK, GDAKI_TS_HOLDING};
  for (uint32_t t : seq) CHECK(pk.push(Msg{t, t == GDAKI_TS_FALLBACK ? 5 : 1, 0, id++}, 0.0, &dt));
  const int me = 5;
  auto mine = [me](const Msg& m) { return gdakiHoldDrainTakes(m.type, m.arg, me, 37u); };  // gdakiHoldDrain's choice
  for (uint32_t ty = 0; ty < 70; ty++)
    for (int arg : {me, me + 1}) {
      const bool want = ty == GDAKI_TS_DISARM || ty == GDAKI_TS_NOHOLD || ty == GDAKI_TS_HOLDING || ty == 37u ||
                        (ty == GDAKI_TS_FALLBACK && arg != me);
      CHECK(gdakiHoldDrainTakes(ty, arg, me, 37u) == want);
    }
  std::vector<int> got;
  Msg m;
  while (pk.takeIf(mine, &m)) got.push_back(m.id);
  CHECK((got == std::vector<int>{0, 2, 3, 5}));  // the host types in arrival order (R1)
  CHECK(pk.q.size() == 2);                        // READY for the restore round, the FALLBACK about this rank for its owner
  CHECK(pk.take(35, &m) && m.id == 1);
  CHECK(!pk.take(35, &m));
  CHECK(pk.take(GDAKI_TS_FALLBACK, &m) && m.id == 4);
  CHECK(pk.q.empty());
  // the cap: the oldest goes
  for (int i = 0; i < GDAKI_HOLD_PARK_MAX + 44; i++) {
    const bool ok = pk.push(Msg{(uint32_t)(11 + i % 9), 0, 0, 1000 + i}, (double)i, &dt);
    CHECK(ok == (i < GDAKI_HOLD_PARK_MAX));
  }
  CHECK(pk.q.size() == (size_t)GDAKI_HOLD_PARK_MAX && pk.dropped == 44 && pk.q.front().m.id == 1044);
  // the age limit
  uint32_t one = 0;
  const int n = pk.expire(44.0 + GDAKI_HOLD_PARK_MS + 0.5, GDAKI_HOLD_PARK_MS, &one);  // record 1044 came at 44 ms
  CHECK(n == 1 && pk.q.front().m.id == 1045);
  CHECK(pk.expire(1e12, GDAKI_HOLD_PARK_MS, &one) == GDAKI_HOLD_PARK_MAX - 1 && pk.q.empty());
  // the wait (hk's DONE wait as changed: gdakiHoldRecvParked) on a simulated clock. Each record arrives after `gap` ms;
  // the first receive gets the bound unchanged; after parked records the wait goes on to the same end
  for (int hold = 0; hold < 2; hold++)
    for (int gap : {0, 3, 400, 2000}) {
      const std::vector<uint32_t> arrive = {GDAKI_TS_CKPT_STABLE, GDAKI_TS_HOLDING, 36, GDAKI_TS_DONE};
      double now = 1000.0;
      size_t k = 0;
      std::vector<int> asked;
      uint32_t last = 0;
      int parked = 0;
      auto recv = [&](int ms) {
        asked.push_back(ms);
        if (k >= arrive.size()) {
          now += ms;
          return 0;
        }
        if (gap > ms) {  // nothing within the bound
          now += ms;
          return 0;
        }
        now += gap;
        last = arrive[k++];
        return 1;
      };
      auto park = [&] {
        if (hold && gdakiHoldIsRestoreRecord(last)) {
          parked++;
          return true;
        }
        return false;
      };
      const int got = gdakiHoldRecvParked(2500, recv, park, [&] { return now; });
      CHECK(!asked.empty() && asked[0] == 2500);  // hk's bound for the first receive, unchanged
      CHECK(now <= 1000.0 + 2500.0 + 1.0);         // never beyond the bound (+ the rounding up of one receive)
      if (!hold) CHECK(got == (gap <= 2500 ? 1 : 0) && parked == 0 && asked.size() == 1);  // the first record decides
      if (hold && gap * 4 <= 2500) CHECK(got == 1 && last == GDAKI_TS_DONE && parked == 3);
      if (hold && gap * 4 > 2500) CHECK(got == 0);
      for (size_t i = 1; i < asked.size(); i++) CHECK(asked[i] <= asked[i - 1]);  // what is left, never more
    }
  for (uint32_t t : {(uint32_t)GDAKI_TS_REQ, (uint32_t)GDAKI_TS_ACK, (uint32_t)GDAKI_TS_NACK, (uint32_t)GDAKI_TS_FAIL,
                     (uint32_t)GDAKI_TS_BYE, 0u, 10u, 64u, 100u})
    CHECK(!gdakiHoldIsRestoreRecord(t));  // hk's types and anything outside 11..63 keep hk's handling
}

// ---- 5. deadlines and the buddy's count ----
static void testDeadlinesAndHolders() {
  // HELD: min(start + restoreMs, gateOdd + holdMs - share - margin)
  CHECK(gdakiHoldHeldDeadlineUs(1000000, 1000000, 20000, 30000, 8000, 1000) == 1000000 + 20000 * 1000);
  CHECK(gdakiHoldHeldDeadlineUs(1000000, 1000000, 25000, 30000, 8000, 1000) == 1000000 + 21000 * 1000);
  CHECK(gdakiHoldHeldDeadlineUs(10000000, 1000000, 20000, 30000, 8000, 1000) == 1000000 + 21000 * 1000);  // odd 9 s before
  CHECK(gdakiHoldHeldDeadlineUs(40000000, 1000000, 20000, 30000, 8000, 1000) < 40000000);  // no time left: caller falls back
  // PUBLISHED: publish + max(restoreMs, roundMs + handshakeMs)
  CHECK(gdakiHoldPublishedDeadlineUs(5000000, 20000, 25000, 3000) == 5000000 + 28000LL * 1000);
  CHECK(gdakiHoldPublishedDeadlineUs(5000000, 40000, 25000, 3000) == 5000000 + 40000LL * 1000);
  // the parked device threads' clock: min of the hold start's quiesce and the oldest record; with odd gates the time they
  // went odd (or the pause), unknown -> < 0
  CHECK(gdakiHoldGateOddMs(5000, false, 0, 0, 0) == 5000);
  CHECK(gdakiHoldGateOddMs(5000, false, 4200, 0, 0) == 4200);  // waiters parked at their error CQE, gates still even
  CHECK(gdakiHoldGateOddMs(5000, false, 4200, 1000, 900) == 4200);  // even gates: the odd marks do not count
  CHECK(gdakiHoldGateOddMs(5000, false, 6000, 0, 0) == 5000);
  CHECK(gdakiHoldGateOddMs(5000, true, 0, 0, 0) < 0);  // odd since an unknown time: the caller falls back
  CHECK(gdakiHoldGateOddMs(5000, true, 4200, 3000, 0) == 3000);  // a cancelled round's quiesce
  CHECK(gdakiHoldGateOddMs(5000, true, 2000, 3000, 0) == 2000);
  CHECK(gdakiHoldGateOddMs(5000, true, 0, 0, 2500) == 2500);    // the checkpoint's pause
  CHECK(gdakiHoldGateOddMs(5000, true, 0, 3000, 2500) == 2500);
  for (int i = 0; i < 2000; i++) {  // never later than any input that counts
    const double q = 1000 + (i * 37) % 5000, rec = (i % 3) ? (i * 53) % 7000 : 0, odd = (i % 5) ? (i * 71) % 6000 : 0,
                 pause = (i % 7) ? (i * 13) % 6500 : 0;
    const bool wasOdd = i & 1;
    const double g = gdakiHoldGateOddMs(q, wasOdd, rec, odd, pause);
    if (g < 0) {
      CHECK(wasOdd && odd <= 0 && pause <= 0);
      continue;
    }
    CHECK(g <= q && (rec <= 0 || g <= rec));
    if (wasOdd) CHECK((odd <= 0 || g <= odd) && (pause <= 0 || g <= pause));
    CHECK(g == q || g == rec || (wasOdd && (g == odd || g == pause)));
  }
  // the buddy's holders: rank 2 is the buddy of 3 in 4 ranks; 0, 1, 2 must hold incarnation i
  struct gdakiHoldHolders h;
  CHECK(!gdakiHoldHoldersComplete(h, 4, 3));
  CHECK(gdakiHoldHoldersAdd(h, 4, 2, 0) && gdakiHoldHoldersAdd(h, 4, 0, 0));
  CHECK(!gdakiHoldHoldersComplete(h, 4, 3));
  CHECK(gdakiHoldHoldersAdd(h, 4, 1, 0) && gdakiHoldHoldersComplete(h, 4, 3));
  CHECK(!gdakiHoldHoldersComplete(h, 4, 0));  // subject 0 would need 1, 2, 3
  CHECK(!gdakiHoldHoldersAdd(h, 4, 4, 0) && !gdakiHoldHoldersAdd(h, 4, -1, 0));
  h.activated = true;
  CHECK(gdakiHoldHoldersAdd(h, 4, 0, 1) && h.inc == 1 && !h.activated);  // a newer incarnation starts over
  CHECK(!gdakiHoldHoldersComplete(h, 4, 3));
  CHECK(!gdakiHoldHoldersAdd(h, 4, 1, 0));  // stale
  CHECK(!gdakiHoldHoldersComplete(h, 4, 3));
  CHECK(gdakiHoldHoldersAdd(h, 4, 1, 1) && gdakiHoldHoldersAdd(h, 4, 2, 1) && gdakiHoldHoldersComplete(h, 4, 3));
  // two ranks: the buddy of 1 is 0, which holds it alone
  struct gdakiHoldHolders t;
  CHECK(gdakiHoldHoldersAdd(t, 2, 0, 0) && gdakiHoldHoldersComplete(t, 2, 1));
}

int main() {
  testPredicatesAndPacking();
  testDeclineTable();
  testMsgTable();
  testWatcherRouteReqStepArm();
  testPaths();
  testRaces();
  testPark();
  testDeadlinesAndHolders();
  printf("rs_unit_host: %ld checks, %ld failed\n", gChecks, gFailed);
  return gFailed == 0 ? 0 : 1;
}
