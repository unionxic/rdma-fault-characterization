// rs_unit_host.cc - CPU unit test of the host branch's hold state machine (work package 7; EXPERIMENT.md 9.10.7) and of
// the checkpoint's accounting (work package 5; 9.4). No NCCL, no CUDA, no network.
// Built by impl/build_rs_host.sh unith: impl/rs_hold_api.h and impl/rs_ckpt_api.h (the shared interfaces) and the regions
// "gin-restore hold: pure functions" and "gin-restore ckpt: pure functions" cut from the working tree's gin_host_gdaki.cc
// (rs_hold_pure.inc, rs_ckpt_pure.inc), with g++ -std=c++17, ASan and UBSan.
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
//   5. the deadlines' arithmetic (with the spare's one-at-a-time driver: the turn's HELD deadline and a PUBLISHED deadline
//      that covers the later survivors, as a model over random schedules), the time the parked device threads' clock
//      started, and the buddy's holder count;
//   6. the checkpoint (work package 5): when one is due, the drain verdict, the image layout and blocks, the changed
//      blocks, PAUSED's P, the answers to CKPT_PAUSE and CKPT_RESUME, the covered epoch over empty rounds (G6), the replies,
//      the stable step, a peer's cuts, the buddy's store, the spare's fetch (answer kind, region match), and the
//      stable-checkpoint protocol as a model with the subject dying at every point.
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
#include "rs_ckpt_api.h"
// hk's helper-socket types the tests use (gin_host_gdaki.cc)
enum { GDAKI_TS_HELLO = 1, GDAKI_TS_REQ = 2, GDAKI_TS_ACK = 3, GDAKI_TS_NACK = 4, GDAKI_TS_DONE = 5, GDAKI_TS_FAIL = 6,
       GDAKI_TS_BYE = 10 };
#include "rs_hold_pure.inc"
#include "rs_ckpt_pure.inc"

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
  // PUBLISHED: publish + max(restoreMs, roundMs + handshakeMs), and at least rejoin + holdMs + handshakeMs
  CHECK(gdakiHoldPublishedDeadlineUs(5000000, 20000, 25000, 3000, 0, 30000) == 5000000 + 28000LL * 1000);
  CHECK(gdakiHoldPublishedDeadlineUs(5000000, 40000, 25000, 3000, 0, 30000) == 5000000 + 40000LL * 1000);
  CHECK(gdakiHoldPublishedDeadlineUs(5000000, 20000, 25000, 3000, 4000000, 30000) == 4000000 + 33000LL * 1000);
  CHECK(gdakiHoldPublishedDeadlineUs(5000000, 40000, 25000, 3000, 4000000, 30000) == 5000000 + 40000LL * 1000);
  // the turn at the REJOIN: at least rejoin + turn, never earlier than before, never past the device bound
  CHECK(gdakiHoldTurnMs(3000, 3000) == 12000);
  CHECK(gdakiHoldDeviceBoundUs(1000000, 30000, 8000, 1000) == 1000000 + 21000LL * 1000);
  CHECK(gdakiHoldTurnDeadlineUs(21000000, 22000000, 2000000, 12000) == 21000000);  // early turn: unchanged
  CHECK(gdakiHoldTurnDeadlineUs(21000000, 30000000, 15000000, 12000) == 27000000);  // late turn: rejoin + turn
  CHECK(gdakiHoldTurnDeadlineUs(21000000, 25000000, 15000000, 12000) == 25000000);  // capped by the device bound
  for (int i = 0; i < 5000; i++) {
    const int64_t dev = 10000000 + (int64_t)((i * 7919) % 20000) * 1000, held = dev - (int64_t)((i * 31) % 9000) * 1000,
                  rejoin = (int64_t)((i * 104729) % 30000) * 1000, turn = (i * 13) % 15000;
    const int64_t d = gdakiHoldTurnDeadlineUs(held, dev, rejoin, turn);
    CHECK(d >= held && d <= dev);
    CHECK(d == dev || d == held || d == rejoin + turn * 1000);
    if (d < dev) CHECK(d >= rejoin + turn * 1000);
  }
  // the one-at-a-time driver as a model: m survivors hold before the activation; the spare serves them in order; survivor
  // j's turn starts at its REJOIN and ends at its publish (before its gateOdd + holdMs: the device bound and its share);
  // RESTORED reaches everyone within a handshake of the last publish. Every survivor's PUBLISHED deadline covers it.
  {
    uint64_t rng = 99;
    auto rnd = [&](int n) {
      rng = rng * 6364136223846793005ULL + 1442695040888963407ULL;
      return (int64_t)((rng >> 33) % (uint64_t)n);
    };
    int runs = 0;
    for (int trial = 0; trial < 20000; trial++) {
      const int m = 1 + (int)rnd(7);
      const int64_t holdMs = 30000, restoreMs = 5000 + rnd(30000), roundMs = 1000 + rnd(30000), hs = 100 + rnd(5000);
      std::vector<int64_t> gateOdd((size_t)m), holdStart((size_t)m), rejoin((size_t)m), publish((size_t)m);
      int64_t act = 0;
      for (int j = 0; j < m; j++) {
        holdStart[(size_t)j] = rnd(5000) * 1000;
        gateOdd[(size_t)j] = holdStart[(size_t)j] - rnd(3000) * 1000;
        act = std::max(act, holdStart[(size_t)j] + rnd(500) * 1000);
      }
      int64_t t = act;
      bool ok = true;
      for (int j = 0; j < m && ok; j++) {
        rejoin[(size_t)j] = t + rnd(50) * 1000 + 1000;
        publish[(size_t)j] = rejoin[(size_t)j] + rnd(15000) * 1000;
        if (publish[(size_t)j] > gateOdd[(size_t)j] + holdMs * 1000) ok = false;  // that survivor fell back: no RESTORED
        t = publish[(size_t)j];
      }
      if (!ok) continue;
      runs++;
      const int64_t restored = t + rnd(hs) * 1000;
      for (int j = 0; j < m; j++)
        CHECK(gdakiHoldPublishedDeadlineUs(publish[(size_t)j], restoreMs, roundMs, hs, rejoin[(size_t)j], holdMs) >=
              restored);
    }
    CHECK(runs > 1000);
  }
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

// ---- 6. the checkpoint (work package 5) ----
static void testCkptPure() {
  // when a checkpoint is due
  CHECK(gdakiCkptDue(7, false, 0, 20));
  CHECK(!gdakiCkptDue(26, true, 7, 20) && gdakiCkptDue(27, true, 7, 20) && gdakiCkptDue(90, true, 7, 20));
  CHECK(gdakiCkptDue(8, true, 7, 0) && !gdakiCkptDue(7, true, 7, 1) && !gdakiCkptDue(3, true, 7, 1));
  // the drain verdict
  {
    uint64_t m[3] = {5, 0, 9}, x[3] = {5, 0, 9};
    CHECK(gdakiCkptDrainVerdict(x, m, 3) == GDAKI_CKPT_DRAINED);
    x[2] = 8;
    CHECK(gdakiCkptDrainVerdict(x, m, 3) == GDAKI_CKPT_DRAIN_WAIT);
    x[0] = 6;
    CHECK(gdakiCkptDrainVerdict(x, m, 3) == GDAKI_CKPT_DRAIN_VOID);  // more than posted wins over waiting
    CHECK(gdakiCkptDrainVerdict(x, m, 0) == GDAKI_CKPT_DRAINED);
  }
  // the layout and the blocks
  {
    uint64_t b[4] = {1, 300, 0, 65536}, off[4], total = 0;
    CHECK(gdakiCkptLayout(b, 4, off, &total));
    CHECK(off[0] == 0 && off[1] == 256 && off[2] == 768 && off[3] == 768 && total == 768 + 65536);
    for (int i = 0; i < 4; i++) CHECK(off[i] % 256 == 0);
    uint64_t big[1] = {(1ULL << 40) + 1};
    CHECK(!gdakiCkptLayout(big, 1, off, &total));
    CHECK(gdakiCkptNBlocks(0) == 0 && gdakiCkptNBlocks(1) == 1 && gdakiCkptNBlocks(GDAKI_CKPT_BLOCK) == 1 &&
          gdakiCkptNBlocks(GDAKI_CKPT_BLOCK + 1) == 2);
    CHECK(gdakiCkptBlockLen(0, 100) == 100 && gdakiCkptBlockLen(1, 100) == 0 &&
          gdakiCkptBlockLen(1, GDAKI_CKPT_BLOCK + 7) == 7 && gdakiCkptBlockLen(0, GDAKI_CKPT_BLOCK + 7) == GDAKI_CKPT_BLOCK);
  }
  // the changed blocks
  {
    std::vector<uint64_t> base = {1, 2, 3}, cur = {1, 9, 3};
    CHECK((gdakiCkptChanged(base, true, cur) == std::vector<uint64_t>{1}));
    CHECK((gdakiCkptChanged(base, false, cur) == std::vector<uint64_t>{0, 1, 2}));
    CHECK((gdakiCkptChanged(base, true, base).empty()));
    CHECK((gdakiCkptChanged(base, true, std::vector<uint64_t>{1, 2, 3, 4}) == std::vector<uint64_t>{0, 1, 2, 3}));
  }
  // P in PAUSED
  for (uint64_t p : {0ULL, 1ULL, 0xffffffffULL, 0x100000000ULL, 0xdeadbeefcafef00dULL}) {
    uint32_t lo = 0, hi = 0;
    gdakiCkptPackP(p, &lo, &hi);
    CHECK(gdakiCkptUnpackP(lo, hi) == p);
  }
  // the answer to CKPT_PAUSE: every combination, in its order of priority
  for (int bits = 0; bits < 64; bits++) {
    const bool has = bits & 1, hold = bits & 2, sup = bits & 4, dec = bits & 8, told = bits & 16, round = bits & 32;
    const uint32_t r = gdakiCkptBusyReason(has, hold, sup, dec, told, round);
    const uint32_t want = !has ? GDAKI_CKPT_BUSY_OFF : (dec || told) ? GDAKI_CKPT_BUSY_DECLINED : hold ? GDAKI_CKPT_BUSY_HOLD
                          : round ? GDAKI_CKPT_BUSY_ROUND : sup ? GDAKI_CKPT_BUSY_SUPPRESS : 0u;
    CHECK(r == want);
  }
  // the answer to CKPT_RESUME (9.11.9 C1): every combination
  for (int bits = 0; bits < 64; bits++) {
    const bool paused = bits & 1, same = bits & 2, gaveUp = bits & 4, dec = bits & 8, epoch = bits & 16, odd = bits & 32;
    const int v = gdakiCkptResumeVerdict(paused, 5, same ? 5 : 6, gaveUp, dec, epoch, odd);
    int want;
    if (!paused || !same) want = GDAKI_CKPT_R_IGNORE;
    else if (gaveUp) want = (dec || !epoch || !odd) ? GDAKI_CKPT_R_IGNORE : GDAKI_CKPT_R_UNPAUSE;
    else want = (dec || !epoch || !odd) ? GDAKI_CKPT_R_VOIDED : GDAKI_CKPT_R_HELD;
    CHECK(v == want);
  }
  // G6: the covered epoch over empty rounds and real ones; the stale-record rule (rec < covered) on top of it
  {
    bool valid = false;
    uint32_t top = 0, base = 0, epoch = 4;
    CHECK(gdakiCkptCovered(epoch, valid, top, base) == 4);
    const uint32_t recAtPause = 4;  // a fault record a device thread published in epoch 4, before or during the pause
    gdakiCkptAfterEmpty(epoch, &valid, &top, &base);
    epoch += 2;  // the empty round publishes 6
    CHECK(gdakiCkptCovered(epoch, valid, top, base) == 4 && !(recAtPause < gdakiCkptCovered(epoch, valid, top, base)));
    gdakiCkptAfterEmpty(epoch, &valid, &top, &base);
    epoch += 2;  // a second empty round: still covered 4
    CHECK(gdakiCkptCovered(epoch, valid, top, base) == 4 && top == 8);
    epoch += 2;  // a real round publishes 10: covered again, the old record is stale now
    CHECK(gdakiCkptCovered(epoch, valid, top, base) == 10 && recAtPause < gdakiCkptCovered(epoch, valid, top, base));
    epoch = (epoch | 1u) + 1u;  // a decline (12)
    CHECK(gdakiCkptCovered(epoch, valid, top, base) == 12);
    gdakiCkptAfterEmpty(epoch, &valid, &top, &base);  // an empty round after a real one starts from that one
    epoch += 2;
    CHECK(gdakiCkptCovered(epoch, valid, top, base) == 12);
  }
  // the replies of one checkpoint
  {
    struct gdakiCkptReplies rp;
    rp.reset(4, 2);
    CHECK(!rp.allPausedOrBusy() && !rp.anyBusy() && !rp.allConfirmed());
    rp.state[0] = 1, rp.armable[0] = 1;
    rp.state[1] = 1, rp.armable[1] = 1;
    rp.state[3] = 1, rp.armable[3] = 0;
    CHECK(rp.allPausedOrBusy() && !rp.anyBusy() && !rp.allArmable());
    rp.armable[3] = 1;
    CHECK(rp.allArmable());
    rp.state[0] = rp.state[1] = 3;
    CHECK(!rp.allConfirmed());
    rp.state[3] = 4;
    CHECK(rp.anyBusy() && !rp.allConfirmed());
    rp.state[3] = 3;
    CHECK(rp.allConfirmed() && !rp.anyBusy());
    // a give-up releases every peer that was sent CKPT_PAUSE and did not answer BUSY (paused, or its PAUSED on the way)
    struct gdakiCkptReplies ab;
    ab.reset(5, 1);
    ab.sent[0] = ab.sent[2] = ab.sent[3] = 1;  // rank 4: the send loop stopped before it
    ab.state[0] = 1;                          // paused
    ab.state[2] = 0;                          // its PAUSED still on the way (a BUSY of another peer came first)
    ab.state[3] = 2;                          // BUSY: never paused
    CHECK(ab.releaseOnAbort(0) && !ab.releaseOnAbort(1) && ab.releaseOnAbort(2) && !ab.releaseOnAbort(3) &&
          !ab.releaseOnAbort(4) && !ab.releaseOnAbort(-1) && !ab.releaseOnAbort(5));
    ab.state[0] = 3;  // confirmed or voided peers are past their pause
    ab.state[2] = 4;
    CHECK(!ab.releaseOnAbort(0) && !ab.releaseOnAbort(2));
  }
  // the gates against a pause (9.11.9 C1): every combination
  for (int bits = 0; bits < 64; bits++) {
    const bool dec = bits & 1, round = bits & 2, same = bits & 4, rf = bits & 8, all = bits & 16, any = bits & 32;
    const int v = gdakiCkptPauseVerdict(dec, round, same, rf, all, any);
    int want;
    if (dec || round || !same) want = GDAKI_CKPT_P_ENDED;  // something else ended it: no empty round, no decline
    else if (rf) want = GDAKI_CKPT_P_BROKEN;                 // unknown gates: declined (never left odd)
    else if (all) want = GDAKI_CKPT_P_INTACT;
    else want = any ? GDAKI_CKPT_P_BROKEN : GDAKI_CKPT_P_ENDED;  // a partial write is broken; no odd gate: nothing paused
    CHECK(v == want);
  }
  // the stable step (with the dev branch's gdakiRsStableStepOf as documented)
  {
    struct gdakiCkptStepLog sl;
    const uint64_t NONE = ~0ULL;
    for (uint64_t t = 0; t < 10; t++) sl.add(t, 100 + 10 * t, 1000);
    auto stableOf = [&](uint64_t covered) {
      uint64_t s = NONE;
      for (size_t i = 0; i < sl.steps.size(); i++)
        if (sl.heads[i] <= covered) s = sl.steps[i];
      return s;
    };
    sl.settle(stableOf(99), NONE);
    CHECK(!sl.haveStable && sl.steps.size() == 10);
    sl.settle(stableOf(135), NONE);  // steps 0..3 have heads <= 135
    CHECK(sl.haveStable && sl.stable == 3 && sl.steps.size() == 6 && sl.steps.front() == 4);
    sl.settle(stableOf(135), NONE);  // nothing new: still 3
    CHECK(sl.stable == 3 && sl.steps.size() == 6);
    sl.settle(stableOf(1000), NONE);
    CHECK(sl.stable == 9 && sl.steps.empty());
    struct gdakiCkptStepLog cap;
    for (uint64_t t = 0; t < 20; t++) cap.add(t, t, 8);
    CHECK(cap.steps.size() == 8 && cap.steps.front() == 12);
  }
  // a peer's cuts toward one subject
  {
    struct Rec {
      uint64_t head;
    };
    struct gdakiCkptCuts<Rec> c;
    c.confirmed(20, Rec{200});
    c.confirmed(40, Rec{400});
    CHECK(c.find(20) && c.find(20)->rec.head == 200 && c.find(40) && !c.find(30));
    CHECK(c.markStable(20) && c.v.front().stable && c.v.size() == 2);
    c.confirmed(60, Rec{600});
    CHECK(c.markStable(60) && c.v.size() == 1 && c.v.front().ckpt == 60 && !c.find(20) && !c.find(40));
    CHECK(!c.markStable(80));
    for (uint64_t k = 70; k < 200; k += 10) c.confirmed(k, Rec{k * 10});
    CHECK(c.v.size() == 8 && c.find(60) != nullptr && c.v.front().stable);  // the cap never drops the last stable cut
  }
}
static void fillHdr(struct gdakiCkptHdr& h, int rank, uint64_t ckpt, uint64_t base, uint64_t bytes, uint64_t nChanged) {
  memset(&h, 0, sizeof(h));
  h.magic = GDAKI_CKPT_MAGIC;
  h.version = GDAKI_CKPT_VERSION;
  h.rank = rank;
  h.ckpt = ckpt;
  h.baseCkpt = base;
  h.imageBytes = bytes;
  h.blockBytes = GDAKI_CKPT_BLOCK;
  h.nChanged = nChanged;
}
static void testCkptStore() {
  const uint64_t bytes = 3 * GDAKI_CKPT_BLOCK + 100;
  std::vector<uint8_t> img(bytes), blk(GDAKI_CKPT_BLOCK);
  for (size_t i = 0; i < bytes; i++) img[i] = (uint8_t)(i * 7 + 3);
  struct gdakiCkptStore st;
  struct gdakiCkptHdr* h = new gdakiCkptHdr();
  const char* why = nullptr;
  fillHdr(*h, 3, 20, 5, bytes, 1);  // a delta without any stable image here
  CHECK(!st.begin(*h, &why) && strstr(why, "base") != nullptr);
  fillHdr(*h, 3, 20, ~0ULL, bytes, 2);  // no base but not every block
  CHECK(!st.begin(*h, &why));
  fillHdr(*h, 3, 20, ~0ULL, bytes, gdakiCkptNBlocks(bytes));
  CHECK(st.begin(*h, &why));
  for (uint64_t i = 0; i < gdakiCkptNBlocks(bytes); i++)
    CHECK(st.block(i, img.data() + i * GDAKI_CKPT_BLOCK, gdakiCkptBlockLen(i, bytes)));
  CHECK(!st.block(3, img.data(), 99));  // a wrong length
  const uint8_t blob[3] = {1, 2, 3};
  st.finish(blob, 3);
  CHECK(!st.markStable(19) && st.havePending && !st.haveStable);
  CHECK(st.markStable(20) && st.haveStable && !st.havePending && st.stable.data == img && st.stable.blob.size() == 3);
  // a delta on the stable image: block 1 changes
  std::vector<uint8_t> img2 = img;
  for (size_t i = GDAKI_CKPT_BLOCK; i < 2 * GDAKI_CKPT_BLOCK; i++) img2[i] ^= 0x5a;
  fillHdr(*h, 3, 40, 20, bytes, 1);
  CHECK(st.begin(*h, &why));
  CHECK(st.block(1, img2.data() + GDAKI_CKPT_BLOCK, GDAKI_CKPT_BLOCK));
  st.finish(nullptr, 0);
  // the stable image stays 20 until its CKPT_STABLE; a restore meanwhile uses 20
  CHECK(st.stable.ckpt == 20 && st.stable.data == img && st.pending.complete && st.pending.data == img2);
  CHECK(st.markStable(40) && st.stable.data == img2);
  // a delta naming an older base is refused
  fillHdr(*h, 3, 60, 20, bytes, 1);
  CHECK(!st.begin(*h, &why));
  // malformed headers
  fillHdr(*h, 3, 60, ~0ULL, bytes, gdakiCkptNBlocks(bytes));
  h->blockBytes = 4096;
  CHECK(!st.begin(*h, &why));
  fillHdr(*h, 3, 60, ~0ULL, bytes, gdakiCkptNBlocks(bytes) + 1);
  CHECK(!st.begin(*h, &why));
  fillHdr(*h, 3, 60, ~0ULL, bytes, gdakiCkptNBlocks(bytes));
  h->nRegions = GDAKI_CKPT_MAX_REGIONS + 1;
  CHECK(!st.begin(*h, &why));
  delete h;
  // the hash: equal data equal hash, a byte changed changes it (this test's blocks)
  CHECK(gdakiCkptHash(img.data(), 1000, GDAKI_CKPT_HASH_SEED) == gdakiCkptHash(img.data(), 1000, GDAKI_CKPT_HASH_SEED));
  img[500] ^= 1;
  CHECK(gdakiCkptHash(img.data(), 1000, GDAKI_CKPT_HASH_SEED) != gdakiCkptHash(img2.data(), 1000, GDAKI_CKPT_HASH_SEED));
}
// The stable-checkpoint protocol, as the host code runs it, with the subject r dying at every point: r takes checkpoints
// 1, 2, ...; each peer confirms (or voids) its pause; the buddy stores the upload; r sends CKPT_STABLE to the buddy first,
// then to the others, and may die after any number of them. Invariant at the restore: the checkpoint the buddy would
// activate with (its newest stable image) has a confirmed cut on every survivor, and no survivor trimmed its log past it.
static void testCkptProtocolModel() {
  uint64_t rng = 0x1234567;
  auto rnd = [&](int n) {
    rng = rng * 6364136223846793005ULL + 1442695040888963407ULL;
    return (int)((rng >> 33) % (uint64_t)n);
  };
  struct Rec {
    uint64_t head;
  };
  int restores = 0, withImage = 0;
  for (int trial = 0; trial < 3000; trial++) {
    const int n = 2 + rnd(5), subject = rnd(n), buddy = gdakiHoldBuddyOf(subject, n);
    std::vector<struct gdakiCkptCuts<Rec>> cuts((size_t)n);
    std::vector<uint64_t> tail((size_t)n, 0), head((size_t)n, 0);  // each peer's log toward the subject
    struct gdakiCkptStore st;  // at the buddy (the image bytes do not matter here)
    bool dead = false;
    for (uint64_t k = 1; k <= 12 && !dead; k++) {
      for (int q = 0; q < n; q++) head[(size_t)q] += (uint64_t)rnd(5);  // puts toward the subject between checkpoints
      std::vector<uint64_t> cutHead(head);  // the pause: every peer's head now
      // the confirmations (a round or an early end voids a peer's pause; r then never makes k stable)
      bool allHeld = true;
      for (int q = 0; q < n; q++) {
        if (q == subject) continue;
        if (rnd(10) == 0) allHeld = false;
        else cuts[(size_t)q].confirmed(k, Rec{cutHead[(size_t)q]});
      }
      // the upload (may fail); the buddy's pending image
      const bool uploaded = rnd(8) != 0;
      if (uploaded) {
        struct gdakiCkptHdr* h = new gdakiCkptHdr();
        fillHdr(*h, subject, k, ~0ULL, 10, 1);
        const char* why;
        CHECK(st.begin(*h, &why));
        delete h;
        uint8_t b[10] = {0};
        CHECK(st.block(0, b, 10));
        st.finish(nullptr, 0);
      }
      if (rnd(6) == 0) {  // r dies before it decides
        dead = true;
        break;
      }
      if (!allHeld || !uploaded) continue;
      // CKPT_STABLE: the buddy first, then the others; r may die after any number of them
      std::vector<int> order;
      order.push_back(buddy);
      for (int q = 0; q < n; q++)
        if (q != subject && q != buddy) order.push_back(q);
      const int sent = rnd(4) == 0 ? rnd((int)order.size() + 1) : (int)order.size();
      for (int j = 0; j < sent; j++) {
        const int q = order[(size_t)j];
        if (q == buddy) CHECK(st.markStable(k));
        const auto* c = cuts[(size_t)q].find(k);
        CHECK(c != nullptr);
        if (c) {
          tail[(size_t)q] = c->rec.head;  // the trim (gdakiRsLogStable)
          CHECK(cuts[(size_t)q].markStable(k));
        }
      }
      if (sent < (int)order.size()) dead = true;
    }
    restores++;
    if (!st.haveStable) {  // no stable image: the subject was never armed (no restore); nothing to check
      for (int q = 0; q < n; q++) CHECK(q == subject || tail[(size_t)q] == 0);
      continue;
    }
    withImage++;
    const uint64_t k = st.stable.ckpt;
    for (int q = 0; q < n; q++) {
      if (q == subject) continue;
      const auto* c = cuts[(size_t)q].find(k);
      CHECK(c != nullptr);                                // every survivor can export from that checkpoint's cut
      if (c) CHECK(tail[(size_t)q] <= c->rec.head);      // and still holds every entry from it
    }
  }
  printf("checkpoint protocol model: %d runs, %d with a stable image at the buddy\n", restores, withImage);
}
// The spare's fetch: the buddy's answer and the region match; the records the drain hands over.
static void testCkptFetch() {
  CHECK(gdakiCkptFetchAnswer(GDAKI_CKPT_MAGIC, GDAKI_CKPT_VERSION) == 1);
  CHECK(gdakiCkptFetchAnswer(GDAKI_CKPT_MAGIC, 0) == 0);
  CHECK(gdakiCkptFetchAnswer(GDAKI_CKPT_MAGIC, 7) == -1 && gdakiCkptFetchAnswer(0, GDAKI_CKPT_VERSION) == -1);
  {  // the header and the ack start the same way: the second word tells them apart
    struct gdakiCkptAck a;
    memset(&a, 0, sizeof(a));
    a.magic = GDAKI_CKPT_MAGIC;
    uint32_t w[2];
    memcpy(w, &a, sizeof(w));
    CHECK(gdakiCkptFetchAnswer(w[0], w[1]) == 0);
    struct gdakiCkptHdr* h = new gdakiCkptHdr();
    fillHdr(*h, 1, 2, ~0ULL, 10, 1);
    memcpy(w, h, sizeof(w));
    CHECK(gdakiCkptFetchAnswer(w[0], w[1]) == 1);
    delete h;
  }
  struct gdakiCkptRegion img[4] = {{GDAKI_CKPT_REGION_WINDOW, 1, 0, 4096},
                                   {GDAKI_CKPT_REGION_WINDOW, 2, 4096, 100},
                                   {GDAKI_CKPT_REGION_SIGNALS, 0, 4352, 64},
                                   {GDAKI_CKPT_REGION_REGISTERED, 0, 4608, 8}};
  uint32_t kind[4] = {GDAKI_CKPT_REGION_SIGNALS, GDAKI_CKPT_REGION_WINDOW, GDAKI_CKPT_REGION_REGISTERED,
                      GDAKI_CKPT_REGION_WINDOW};
  uint32_t id[4] = {0, 2, 0, 1};
  uint64_t bytes[4] = {64, 100, 8, 4096};
  int map[4];
  const char* why = nullptr;
  CHECK(gdakiCkptRegionMatch(img, 4, kind, id, bytes, 4, map, &why));
  CHECK(map[0] == 3 && map[1] == 1 && map[2] == 0 && map[3] == 2);
  bytes[1] = 101;  // another size
  CHECK(!gdakiCkptRegionMatch(img, 4, kind, id, bytes, 4, map, &why) && strstr(why, "size") != nullptr);
  bytes[1] = 100;
  CHECK(!gdakiCkptRegionMatch(img, 3, kind, id, bytes, 4, map, &why));  // another count
  id[1] = 3;  // no window 2 here
  CHECK(!gdakiCkptRegionMatch(img, 4, kind, id, bytes, 4, map, &why));
  id[1] = 1;  // two local windows numbered 1
  CHECK(!gdakiCkptRegionMatch(img, 4, kind, id, bytes, 4, map, &why));
  id[1] = 2;
  img[1].id = 1;  // two image windows numbered 1
  bytes[1] = 4096;
  CHECK(!gdakiCkptRegionMatch(img, 4, kind, id, bytes, 4, map, &why));
  CHECK(gdakiCkptRegionMatch(img, 0, kind, id, bytes, 0, map, &why));  // nothing to restore: an empty match
  // the checkpoint's records (11..15) are the hold machine's to hand over, nothing else
  for (uint32_t ty = 0; ty < 70; ty++)
    CHECK(gdakiCkptIsRecord(ty) == (ty >= GDAKI_TS_CKPT_PAUSE && ty <= GDAKI_TS_CKPT_STABLE));
  CHECK(GDAKI_TS_DATA == GDAKI_TS_HOST_RESERVED && gdakiHoldIsRestoreRecord(GDAKI_TS_DATA));
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
  testCkptPure();
  testCkptStore();
  testCkptProtocolModel();
  testCkptFetch();
  printf("rs_unit_host: %ld checks, %ld failed\n", gChecks, gFailed);
  return gFailed == 0 ? 0 : 1;
}
