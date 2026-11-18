// gc_unit_ward.cc - CPU unit test of gin-control's wardfix (impl/notes_wardfix.md; Codex review 2026-10-23): the buddy's
// activation gate waits until the store thread reports the dead ward's upload QP in ERR. Cut out of the working tree's
// host file by build_gc.sh `unit` (as gc_unit_p2b.cc): the region "gin-control (store): pure" (gc_store_pure.inc: the
// ward-ERR state, the job's queue position, its verdict, the gate's ward part and its join with FENCED) and what that
// region needs (gc_unit_p2b.cc's list). No NCCL, no CUDA, no verbs: the store thread is a queue this file runs one job at
// a time (a job can be held), the ward QP a fake (exists, in ERR, the incarnation it serves) whose modify to ERR can be
// made to fail. g++ -std=c++17 with ASan and UBSan.
// What it checks:
//   1. the rules: the verdict (no QP: DONE; modify ok: DONE; failed: FAILED), the gate's ward part over every state and
//      the bound, the join with FENCED (fall back wins, go needs both);
//   2. the queue position over 2000 random queues: right after the last SERVE of the ward, else the front; never ahead
//      of a SERVE of the ward, ahead of every other job after it;
//   3. the scene: the hold start's job is queued behind nothing but held (the store thread busy); every HOLDING is in
//      and FENCED is set; the gate does not pass while the job is held, and a late WRITE of the dead incarnation still
//      lands in that window; the job runs (ahead of another ward's SERVE and a FREE queued before it), the QP is in ERR,
//      the gate passes, the late WRITE lands nowhere;
//   4. the modify failure: the job runs, the modify fails: FAILED, the gate falls back (as a FENCE_NAK); and the job held
//      past the bound: the gate falls back;
//   5. a SERVE of the ward queued before the hold start (a request of the dead incarnation in flight): the ERR goes
//      after it and finds the QP it installed; two asks (the hook twice): the first job's verdict waits for the second;
//      never asked: the gate asks; a rank that is not the ward's buddy: the gate goes at once;
//   6. 3000 random runs (random queues, held jobs, failing modifies, extra asks, SERVEs of the ward and of others): the
//      gate never goes while the ward's QP on this side exists outside ERR, and no late WRITE lands after it went.
#include <algorithm>
#include <atomic>
#include <cerrno>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <map>
#include <random>
#include <string>
#include <thread>
#include <vector>

#include <fcntl.h>
#include <netinet/in.h>
#include <poll.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

// What gin-mirror's headers and the cut text need from nccl.h and the host file (as gc_unit_p2b.cc).
typedef enum { ncclSuccess = 0, ncclSystemError = 2, ncclInternalError = 3, ncclInvalidUsage = 5 } ncclResult_t;
typedef struct {
  unsigned int magic, nqp, qpn[64], remoteQpn[64], sqPsn[64];
  unsigned long long epochWqes[64];
} ncclGinRecoverToken_t;
#define NCCL_GIN_RECOVERY_MAX_QPS 64
union ncclSocketAddress {  // nccl socket.h
  struct sockaddr sa;
  struct sockaddr_in sin;
  struct sockaddr_in6 sin6;
};
enum class gdakiCause : int { Local = 0, PeerDead = 1, PeerLeft = 2, PeerReported = 3, Unknown = 4 };  // host file
static double gdakiQ4MonoMs() {
  struct timespec t;
  clock_gettime(CLOCK_MONOTONIC, &t);
  return t.tv_sec * 1e3 + t.tv_nsec * 1e-6;
}
#define GDAKI_MI_API_NO_ENTRY_DECLS
#define GDAKI_HOLD_API_NO_ENTRY_DECLS
#include "rs_hold_api.h"
#include "rs_mirror_api.h"
#include "rs_log_api.h"
#include "rs_ckpt_api.h"
#include "rs_store_api.h"
#include "rs_spare_api.h"
#include "rs_lineage_api.h"
#define NCCL_GIN_RS_LOG_PUT 1u
#define NCCL_GIN_RS_LOG_PUTVALUE 2u
#define NCCL_GIN_RS_LOG_SIGNAL 3u
#define NCCL_GIN_RS_LOGF_SIGNAL 0x01u
static inline uint32_t ncclGinRsEntryKind(uint32_t qpKf) { return (qpKf >> 24) & 3u; }
static inline uint32_t ncclGinRsEntryFlags(uint32_t qpKf) { return qpKf >> 26; }

static int nChecks = 0, nFail = 0;
#define CHECK(c) do { nChecks++; if (!(c)) { nFail++; if (nFail <= 40) fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); } } while (0)

#if !NCCL_GIN_CTRL_TCP
#include "gc_ln4_sock.inc"   // struct gdakiTsMsg, gdakiTsSend (ln4's text)
#include "gc_p2b_rs.inc"     // the rkey list text (the store region names its types)
#include "rs_ckpt_pure.inc"
#include "mi_pure_store.inc"
#include "mi_pure_spare.inc"
#include "gc_api.inc"
#include "gc_ring_model.inc"
#include "gc_store_pure.inc"

// The store thread's job kinds as the host file numbers them (gin-mirror's SERVE 1, FREE 2; gin-control's WARD_ERR 3).
enum { J_SERVE = 1, J_FREE = 2, J_WARD_ERR = 3 };
struct Job {
  int kind = 0;
  int d = -1;
  uint32_t inc = 0;  // SERVE: the incarnation whose request it serves
};
struct FakeQp {
  bool exists = false, inErr = false;
  uint32_t inc = 0;  // the ward process it serves
};
// One rank as a buddy (its store state of n ranks): the queue, its side of every ward's upload QP, the ward-ERR words.
struct Store {
  int me = 0, n = 0;
  std::vector<Job> jobs;  // the store thread's queue (step runs its front)
  std::vector<FakeQp> qp;
  std::vector<int> wardErr;
  std::vector<double> wardErrAskMs;
  bool stop = false;
  int modifyFails = 0;  // the next modifies to ERR that fail
  long long nModify = 0;
};
static Store mkStore(int me, int n) {
  Store s;
  s.me = me;
  s.n = n;
  s.qp.assign((size_t)n, FakeQp());
  return s;
}
// gdakiCtrlStoreWardErrQueueLocked's steps (the host text with st->mu held)
static void queueLocked(Store& s, int peer, double now) {
  if (s.wardErr.size() != (size_t)s.n) {
    s.wardErr.assign((size_t)s.n, GDAKI_CTRL_WERR_NONE);
    s.wardErrAskMs.assign((size_t)s.n, 0.0);
  }
  Job j;
  j.kind = J_WARD_ERR;
  j.d = peer;
  s.jobs.insert(s.jobs.begin() + (ptrdiff_t)gdakiCtrlStoreWardErrPos(s.jobs, peer, J_SERVE), j);
  s.wardErr[(size_t)peer] = GDAKI_CTRL_WERR_ASKED;
  s.wardErrAskMs[(size_t)peer] = now;
}
static bool due(const Store& s, int peer) { return gdakiCtrlStoreWardErrDue(s.me, s.n, peer, gdakiHoldBuddyOf(peer, s.n)); }
// gdakiCtrlStoreWardToErrAsk (the hold start's hook)
static void ask(Store& s, int peer, double now) {
  if (!due(s, peer) || s.stop) return;
  queueLocked(s, peer, now);
}
// gdakiCtrlStoreWardErrRun over the fake verbs
static void wardErrRun(Store& s, int d) {
  FakeQp& q = s.qp[(size_t)d];
  const bool haveQp = q.exists;
  bool moved = false;
  if (haveQp) {
    s.nModify++;
    if (s.modifyFails > 0) {
      s.modifyFails--;
    } else {
      moved = true;
      q.inErr = true;
    }
  }
  const int v = gdakiCtrlStoreWardErrOutcome(haveQp, moved);
  bool later = false;
  for (const Job& j : s.jobs) later = later || (j.kind == J_WARD_ERR && j.d == d);
  if (!later && (size_t)d < s.wardErr.size()) s.wardErr[(size_t)d] = v;
}
// The store thread's one step: the front job (false: none)
static bool step(Store& s) {
  if (s.jobs.empty()) return false;
  const Job j = s.jobs.front();
  s.jobs.erase(s.jobs.begin());
  if (j.kind == J_WARD_ERR) {
    wardErrRun(s, j.d);
  } else if (j.kind == J_SERVE) {  // gdakiStoreServe: the old QP destroyed, a new one (RTS) for the request's process
    s.qp[(size_t)j.d] = FakeQp();
    s.qp[(size_t)j.d].exists = true;
    s.qp[(size_t)j.d].inc = j.inc;
  } else if (j.kind == J_FREE) {
    // an MR's deregistration (no QP)
  }
  return true;
}
static void runAll(Store& s) {
  while (step(s)) {
  }
}
// gdakiCtrlStoreWardGateOf
static int wardGate(Store& s, int peer, double now, const char** why) {
  if (!due(s, peer)) return 1;
  if (s.stop) {
    *why = "the store is being torn down";
    return -1;
  }
  if (s.wardErr.size() != (size_t)s.n || s.wardErr[(size_t)peer] == GDAKI_CTRL_WERR_NONE) queueLocked(s, peer, now);
  return gdakiCtrlStoreWardGate(true, s.wardErr[(size_t)peer], s.wardErrAskMs[(size_t)peer], now,
                                GDAKI_CTRL_WARD_ERR_WAIT_MS, why);
}
// gdakiCtrlActFenceOk's decision once every HOLDING is in: FENCED from the launcher, then the join (1 go, 0 not now, -1
// fall back)
static int actGate(Store& s, int peer, bool holdingAll, bool fenced, double now, const char** why) {
  if (!holdingAll) return 0;  // gdakiHoldActivateDecide asks the gate only then
  const int wg = wardGate(s, peer, now, why);
  return gdakiCtrlActWardJoin(fenced, wg);
}
// A late upload WRITE of incarnation `inc` of ward d into this buddy's store: lands only through a QP of that process
// outside ERR
static bool lateWriteLands(const Store& s, int d, uint32_t inc) {
  const FakeQp& q = s.qp[(size_t)d];
  return q.exists && !q.inErr && q.inc == inc;
}
static void serveNow(Store& s, int d, uint32_t inc) {
  s.qp[(size_t)d] = FakeQp();
  s.qp[(size_t)d].exists = true;
  s.qp[(size_t)d].inc = inc;
}

// ---- 1. the rules ----
static void testRules() {
  CHECK(gdakiCtrlStoreWardErrOutcome(false, false) == GDAKI_CTRL_WERR_DONE);
  CHECK(gdakiCtrlStoreWardErrOutcome(false, true) == GDAKI_CTRL_WERR_DONE);
  CHECK(gdakiCtrlStoreWardErrOutcome(true, true) == GDAKI_CTRL_WERR_DONE);
  CHECK(gdakiCtrlStoreWardErrOutcome(true, false) == GDAKI_CTRL_WERR_FAILED);
  const double B = GDAKI_CTRL_WARD_ERR_WAIT_MS;
  for (int st = GDAKI_CTRL_WERR_NONE; st <= GDAKI_CTRL_WERR_FAILED; st++)
    for (double dt : {0.0, 1.0, B - 1, B, B + 1, 10 * B}) {
      const char* w = nullptr;
      CHECK(gdakiCtrlStoreWardGate(false, st, 100.0, 100.0 + dt, B, &w) == 1 && w == nullptr);  // not this rank's ward
      const int g = gdakiCtrlStoreWardGate(true, st, 100.0, 100.0 + dt, B, &w);
      const int want = st == GDAKI_CTRL_WERR_DONE     ? 1
                       : st == GDAKI_CTRL_WERR_FAILED ? -1
                       : st == GDAKI_CTRL_WERR_ASKED  ? (dt >= B ? -1 : 0)
                                                      : 0;
      CHECK(g == want);
      CHECK((g < 0) == (w != nullptr));
    }
  for (bool f : {false, true})
    for (int w = -1; w <= 1; w++) CHECK(gdakiCtrlActWardJoin(f, w) == (w < 0 ? -1 : (f && w > 0) ? 1 : 0));
  printf("  rules: verdict, ward gate over 4 states x 6 times, join: %d checks\n", nChecks);
}

// ---- 2. the queue position ----
static void testPos(std::mt19937_64& rng) {
  long long fronts = 0, behind = 0;
  for (int it = 0; it < 2000; it++) {
    const int n = 2 + (int)(rng() % 7);
    std::vector<Job> q((size_t)(rng() % 9));
    for (Job& j : q) {
      j.kind = 1 + (int)(rng() % 3);
      j.d = (int)(rng() % n);
    }
    const int d = (int)(rng() % n);
    const size_t p = gdakiCtrlStoreWardErrPos(q, d, J_SERVE);
    CHECK(p <= q.size());
    for (size_t i = p; i < q.size(); i++) CHECK(!(q[i].kind == J_SERVE && q[i].d == d));  // never ahead of a SERVE of d
    if (p > 0) CHECK(q[p - 1].kind == J_SERVE && q[p - 1].d == d);                    // right after the last one
    (p == 0 ? fronts : behind)++;
  }
  CHECK(fronts > 100 && behind > 100);
  printf("  queue position: 2000 random queues, %lld at the front, %lld behind a SERVE of the ward\n", fronts, behind);
}

// ---- 3., 4., 5. the scenes ----
static void testScenes() {
  const int n = 4;
  const int dead = 1, b = gdakiHoldBuddyOf(dead, n), other = (b + 1) % n == dead ? (b + 2) % n : (b + 1) % n;
  const char* w = nullptr;
  CHECK(b != dead && other != b && other != dead);
  // 3. the hold start's job held: no pass while held, the late WRITE still lands; then the job runs first
  {
    Store s = mkStore(b, n);
    serveNow(s, dead, 7);
    if (gdakiHoldBuddyOf(other, n) == b) serveNow(s, other, 3);
    s.jobs.push_back({J_SERVE, other, 3});  // another ward's request (an MR registration) queued before
    s.jobs.push_back({J_FREE, -1, 0});
    double t = 1000.0;
    ask(s, dead, t);
    CHECK(s.jobs.size() == 3 && s.jobs.front().kind == J_WARD_ERR && s.jobs.front().d == dead);
    CHECK(s.wardErr[(size_t)dead] == GDAKI_CTRL_WERR_ASKED);
    for (int k = 0; k < 20; k++) {  // the store thread is busy: the job is held; every HOLDING in, FENCED set
      t += 50.0;
      w = nullptr;
      CHECK(actGate(s, dead, true, true, t, &w) == 0);
      CHECK(lateWriteLands(s, dead, 7));  // the window the gate now covers: the old process could still write
    }
    CHECK(actGate(s, dead, false, true, t, &w) == 0 && actGate(s, dead, true, false, t, &w) == 0);
    CHECK(step(s));  // the ERR job first (ahead of the SERVE and the FREE)
    CHECK(s.jobs.size() == 2 && s.jobs.front().kind == J_SERVE);
    CHECK(s.wardErr[(size_t)dead] == GDAKI_CTRL_WERR_DONE && s.qp[(size_t)dead].inErr);
    CHECK(actGate(s, dead, true, false, t, &w) == 0);  // FENCED still needed
    CHECK(actGate(s, dead, true, true, t, &w) == 1);
    CHECK(!lateWriteLands(s, dead, 7));
    runAll(s);
    CHECK(!lateWriteLands(s, dead, 7) && actGate(s, dead, true, true, t, &w) == 1);
    serveNow(s, dead, 8);  // the successor's request: a new QP that works
    CHECK(lateWriteLands(s, dead, 8) && !lateWriteLands(s, dead, 7));
  }
  // 4. the modify fails: FAILED, the gate falls back; the job held past the bound: falls back
  {
    Store s = mkStore(b, n);
    serveNow(s, dead, 7);
    ask(s, dead, 0.0);
    s.modifyFails = 1;
    CHECK(actGate(s, dead, true, true, 10.0, &w) == 0);
    CHECK(step(s));
    CHECK(s.wardErr[(size_t)dead] == GDAKI_CTRL_WERR_FAILED && !s.qp[(size_t)dead].inErr);
    w = nullptr;
    CHECK(actGate(s, dead, true, true, 20.0, &w) == -1 && w != nullptr &&
          strcmp(w, "the store thread's modify to ERR failed") == 0);
    CHECK(actGate(s, dead, true, false, 20.0, &w) == -1);  // whatever the fence says
    Store h = mkStore(b, n);
    serveNow(h, dead, 7);
    ask(h, dead, 0.0);
    CHECK(actGate(h, dead, true, true, GDAKI_CTRL_WARD_ERR_WAIT_MS - 1, &w) == 0);
    w = nullptr;
    CHECK(actGate(h, dead, true, true, GDAKI_CTRL_WARD_ERR_WAIT_MS, &w) == -1 && w != nullptr);
    CHECK(lateWriteLands(h, dead, 7));  // (the hold falls back: the old process is not replaced by this hold)
  }
  // 5a. a SERVE of the ward in flight before the hold start: the ERR after it finds the QP it installed
  {
    Store s = mkStore(b, n);
    serveNow(s, dead, 7);
    s.jobs.push_back({J_FREE, -1, 0});
    s.jobs.push_back({J_SERVE, dead, 7});  // the dead incarnation's last request, dispatched before its hold
    s.jobs.push_back({J_SERVE, other, 3});
    ask(s, dead, 0.0);
    CHECK(s.jobs.size() == 4 && s.jobs[2].kind == J_WARD_ERR && s.jobs[1].kind == J_SERVE && s.jobs[1].d == dead);
    CHECK(step(s) && step(s));  // FREE, then the SERVE: a new QP of incarnation 7
    CHECK(lateWriteLands(s, dead, 7) && actGate(s, dead, true, true, 5.0, &w) == 0);
    CHECK(step(s));
    CHECK(!lateWriteLands(s, dead, 7) && actGate(s, dead, true, true, 6.0, &w) == 1);
  }
  // 5b. two asks: the first job's verdict waits for the second
  {
    Store s = mkStore(b, n);
    serveNow(s, dead, 7);
    ask(s, dead, 0.0);
    ask(s, dead, 1.0);
    CHECK(s.jobs.size() == 2);
    s.modifyFails = 0;
    CHECK(step(s));
    CHECK(s.wardErr[(size_t)dead] == GDAKI_CTRL_WERR_ASKED && actGate(s, dead, true, true, 2.0, &w) == 0);
    CHECK(step(s));
    CHECK(s.wardErr[(size_t)dead] == GDAKI_CTRL_WERR_DONE && actGate(s, dead, true, true, 3.0, &w) == 1);
    CHECK(s.nModify == 2);  // the second modify of a QP in ERR (verbs: any state to ERR)
  }
  // 5c. never asked: the gate asks; 5d. no QP on this side: DONE at once; 5e. not the ward's buddy: go
  {
    Store s = mkStore(b, n);
    serveNow(s, dead, 7);
    CHECK(s.wardErr.empty() && actGate(s, dead, true, true, 0.0, &w) == 0 && s.jobs.size() == 1);
    runAll(s);
    CHECK(actGate(s, dead, true, true, 1.0, &w) == 1 && !lateWriteLands(s, dead, 7));
    Store z = mkStore(b, n);
    ask(z, dead, 0.0);
    runAll(z);
    CHECK(z.nModify == 0 && z.wardErr[(size_t)dead] == GDAKI_CTRL_WERR_DONE && actGate(z, dead, true, true, 1.0, &w) == 1);
    for (int me = 0; me < n; me++) {
      if (me == b || me == dead) continue;
      Store o = mkStore(me, n);
      serveNow(o, dead, 7);  // (a QP it would not have: the rule alone decides)
      ask(o, dead, 0.0);
      CHECK(o.jobs.empty() && actGate(o, dead, true, true, 0.0, &w) == 1 && actGate(o, dead, true, false, 0.0, &w) == 0);
    }
    Store t = mkStore(b, n);
    serveNow(t, dead, 7);
    t.stop = true;  // the teardown: the hook queues nothing, the gate falls back
    ask(t, dead, 0.0);
    CHECK(t.jobs.empty() && actGate(t, dead, true, true, 0.0, &w) == -1);
  }
  printf("  scenes: held job (no pass while held, then ERR first), modify failure and bound (fall back), SERVE of the "
         "ward ahead, two asks, never asked, no QP, not the buddy, teardown: %d checks so far\n", nChecks);
}

// ---- 6. random runs ----
static void testRandom(std::mt19937_64& rng) {
  long long gos = 0, falls = 0, waits = 0, heldSteps = 0;
  for (int it = 0; it < 3000; it++) {
    const int n = 2 + (int)(rng() % 7);
    const int dead = (int)(rng() % n), b = gdakiHoldBuddyOf(dead, n);
    Store s = mkStore(b, n);
    const uint32_t inc = 5 + (uint32_t)(rng() % 3);
    if (rng() % 8) serveNow(s, dead, inc);
    for (int k = (int)(rng() % 5); k > 0; k--) {  // jobs queued before the hold start
      const int kind = 1 + (int)(rng() % 2), d = (int)(rng() % n);
      if (kind == J_FREE) s.jobs.push_back({J_FREE, -1, 0});
      else if (d == dead) s.jobs.push_back({J_SERVE, dead, inc});  // the dead incarnation's request in flight
      else if (d != b) s.jobs.push_back({J_SERVE, d, 1});         // another ward's (or a non-ward's: the model is loose)
    }
    s.modifyFails = rng() % 6 == 0 ? 1 + (int)(rng() % 2) : 0;
    double t = 0;
    ask(s, dead, t);
    bool went = false, fell = false;
    for (int k = 0; k < 40 && !fell; k++) {
      t += (double)(rng() % 120);
      const int a = (int)(rng() % 10);
      if (a < 5) {
        step(s);
      } else if (a == 5) {
        ask(s, dead, t);  // the hook again
      } else {
        heldSteps++;  // the store thread busy: nothing runs
      }
      const bool fenced = rng() % 4 != 0;
      const char* w = nullptr;
      const int g = actGate(s, dead, true, fenced, t, &w);
      if (g > 0) {
        gos++;
        went = true;
        const FakeQp& q = s.qp[(size_t)dead];
        CHECK(!q.exists || q.inErr);  // never a go while the ward's QP here is outside ERR
      } else if (g < 0) {
        falls++;
        fell = true;
        CHECK(w != nullptr);
      } else {
        waits++;
      }
      if (went) CHECK(!lateWriteLands(s, dead, inc));  // and nothing of the old process lands after it
    }
  }
  CHECK(gos > 1000 && falls > 50 && waits > 1000);
  printf("  random: 3000 runs: %lld goes (the QP in ERR at every one, no late WRITE after), %lld fall-backs, %lld waits, "
         "%lld held steps\n", gos, falls, waits, heldSteps);
}
#endif  // !NCCL_GIN_CTRL_TCP

int main() {
#if NCCL_GIN_CTRL_TCP
  printf("gc_unit_ward (tcp): the store region is not in the tcp build: %d checks, %d failed\n", nChecks, nFail);
  return 0;
#else
  std::mt19937_64 rng(0x3a4d3a4dull);
  testRules();
  testPos(rng);
  testScenes();
  testRandom(rng);
  printf("gc_unit_ward (rdma): %d checks, %d failed\n", nChecks, nFail);
  return nFail == 0 ? 0 : 1;
#endif
}
