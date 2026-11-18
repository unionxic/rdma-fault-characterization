// gc_unit_abortdec.cc - CPU model of gin-control's confirmed abort decisions (SPEC3 1 as review3 1-6 corrected it,
// 2026-10-28; impl/notes_abortdec.md): a decision this rank's own move of the communicator's wait words made reaches every
// current peer (record 57 ABORT_DECIDED) and every later incarnation (the activation blob, the resend when a peer's record
// channel is live again), and a receiver applies it through the real decline with the policy hook off once its lineage
// view allows it. No NCCL, no CUDA, no verbs, no network. Compiled as gc_unit_waitpeer.cc is (build_gc.sh `unit`,
// `unitabortdec`, BR=int3): g++ -std=c++17 with ASan and UBSan, gin-mirror's and gin-restore's headers, impl/rs_ctrl_api.h,
// the hold's pure region (rs_hold_pure.inc) and the working tree's code cut as it is (gc_ad_cut_a.inc, gc_ad_decl.inc,
// gc_ad_cut_u.inc, gc_ad_cut_b.inc: the regions "gin-control (page): abort decisions" (declarations, pure, host), gdakiTsDecline,
// gdakiUaRaisePeer, gdakiUaDegradedStep, ncclGinTsUserAbortRaise, gdakiHoldWatchdog, gdakiTsToComm, gdakiRecForPeer, the
// activation blob's UD table, struct gdakiTsMsg and gdakiTsPeer). This file is the rest: the processes of a four-rank
// communicator (each its own fake host state: QPs, gates, hold cells, known incarnations, the user devComm words in the
// real registry), the record channels between the current processes (a latency, a queue held before CONNECTED, a QP
// regeneration that drops it), the hold's decline hook (a hold starts on an ARMED peer that nothing told yet), the
// restore of a rank (fence, activation with the buddy's blob, the activation table and REJOIN_ACKs, RESTORED), the
// watcher (gdakiUaDegradedStep, gdakiHoldWatchdog) and the device's waits that name no peer (word [0]; 60 s watchdog).
// What it checks:
//   1. the pure pieces: the cause, record 57 and the blob both ways, the UD table's length, the receive rule, the key, the
//      send rule;
//   2. the scenes A1-A9 of SPEC3 as review3 corrected them and review3's additions (each run with drawn latencies);
//   3. in its mutation mode (-DGC_AD_MUT=k, the cut changed by build_gc.sh): every scene, quietly; 0 when the scenes the
//      mutation must break failed.
#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdarg>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <functional>
#include <map>
#include <memory>
#include <mutex>
#include <random>
#include <string>
#include <vector>

typedef enum {
  ncclSuccess = 0,
  ncclSystemError = 2,
  ncclInternalError = 3,
  ncclInvalidUsage = 5,
  ncclRemoteError = 6
} ncclResult_t;
typedef struct {
  unsigned int magic, nqp, qpn[64], remoteQpn[64], sqPsn[64];
  unsigned long long epochWqes[64];
} ncclGinRecoverToken_t;
#define NCCL_GIN_RECOVERY_MAX_QPS 64
enum { GDAKI_POLICY_FAILFAST = 0, GDAKI_POLICY_HOLD = 1 };
enum { GDAKI_RS_ACT_GO = 0, GDAKI_RS_ACT_WAIT = 1 };
#define GDAKI_HOLD_API_NO_ENTRY_DECLS
#include "rs_hold_api.h"
#include "rs_mirror_api.h"
#include "rs_log_api.h"
#include "rs_ckpt_api.h"
#include "rs_store_api.h"
#include "rs_spare_api.h"
#include "rs_ctrl_api.h"
#include "rs_lineage_api.h"

[[maybe_unused]] static long gChecks = 0, gFailed = 0;
[[maybe_unused]] static long gSceneFailed = 0;  // the scene's failures (the mutation mode counts scenes)
#ifdef GC_AD_MUT
[[maybe_unused]] static const bool gQuiet = true;
#else
[[maybe_unused]] static const bool gQuiet = false;
#endif
#define CHECK(c)                                                                                \
  do {                                                                                          \
    gChecks++;                                                                                  \
    if (!(c)) {                                                                                 \
      gFailed++;                                                                                \
      gSceneFailed++;                                                                           \
      if (!gQuiet && gFailed <= 80) fprintf(stderr, "FAIL %s:%d (%s): %s\n", __FILE__, __LINE__, gScene, #c); \
    }                                                                                           \
  } while (0)
[[maybe_unused]] static const char* gScene = "";

#if !NCCL_GIN_CTRL_TCP  // the tcp build has none of it (the abort decisions are rdma only)
// ---- the log and the clock ----
static double gNow = 0;
static std::vector<std::string> gLines;
static void gLog(const char* fmt, ...) __attribute__((format(printf, 1, 2)));
static void gLog(const char* fmt, ...) {
  char b[1024];
  va_list ap;
  va_start(ap, fmt);
  vsnprintf(b, sizeof(b), fmt, ap);
  va_end(ap);
  gLines.push_back(b);
  if (getenv("GC_AD_TRACE") != nullptr) fprintf(stderr, "[%10.3f] %s\n", gNow, b);
}
#define NCCL_NET 0
#define WARN(...) gLog(__VA_ARGS__)
#define INFO(flags, ...) gLog(__VA_ARGS__)
#define GIN_TS_NOTE(...) gLog(__VA_ARGS__)
static double gdakiQ4MonoMs() { return gNow; }
static int64_t gdakiTsNowUs() { return (int64_t)llround(gNow * 1000.0); }
static int64_t gDegMs = 2000;
static int64_t ncclParamGinTsDegradedMs() { return gDegMs; }
#define NCCL_DEVCOMM_ABORT_ERROR 0x80000000u
#define NCCL_GIN_TS_W_HOST_FAILED 0x40000000u
union ncclSocketAddress {
  char b[128];
};
enum { GDAKI_TS_HELLO = 1, GDAKI_TS_REQ = 2, GDAKI_TS_ACK = 3, GDAKI_TS_NACK = 4, GDAKI_TS_DONE = 5, GDAKI_TS_FAIL = 6,
       GDAKI_TS_BYE = 10 };
#include "rs_hold_pure.inc"  // the host file's "gin-restore hold: pure functions" region (gdakiHoldWatchMove)
#include "gc_ad_cut_a.inc"

// ---- the host state the cut code reads (the fields it names) ----
struct ncclComm;
typedef struct ncclComm* ncclComm_t;
struct doca_gpu_verbs_qp {
  int dummy;
};
struct doca_gpu_verbs_qp_hl {
  struct doca_gpu_verbs_qp* qp_gverbs = nullptr;
};
struct gdakiRecQp {
  bool used = false;
  int qpIdx = 0, ctxIdx = 0, peer = 0;
};
struct gdakiQ4Host {
  ncclResult_t* asyncResult = nullptr;
  std::atomic<int> setAsync{0}, hasError{0};
};
struct gdaki_context {
  int rank = 0;
  int nContexts = 1;
  std::vector<struct doca_gpu_verbs_qp_hl*> gqps;
  struct gdakiQ4Host* q4 = nullptr;
};
struct gdakiTsQp {
  uint32_t epoch = 2;
};
struct gdakiTs {
  std::vector<struct gdakiTsPeer> peers;
  std::vector<struct gdakiTsQp> qs;
  int nDeclined = 0;
  std::atomic<int> cDeclined{0};
  uint64_t nonce = 0x5eed;
  std::mutex outMu;
  std::atomic<int> life{GDAKI_TS_LIFE_RUNNING};
  std::atomic<int64_t> busySinceUs{0};
};
struct gdakiHold {
  int rank = -1, nranks = 0;
  struct gdakiHoldCell* cells = nullptr;
  std::atomic<int> heldPeer{-1};
  std::atomic<int> nTimeouts{0};
  ~gdakiHold() { delete[] cells; }
};
struct gdakiRecHost {
  void* commKey = nullptr;
  struct gdaki_context* ctx = nullptr;
  std::vector<struct gdakiRecQp> qps;
  std::mutex opMu;
  int nranks = 0;
  struct gdakiTs* ts = nullptr;
  struct gdakiHold* hold = nullptr;
  std::vector<uint8_t> prepared;
};
static thread_local bool gdakiTsInHelper = false;
static thread_local struct gdakiRecHost* gdakiTsOwner = nullptr;
#include "gc_ad_decl.inc"
#include "gc_ad_cut_u.inc"  // the QP walk, the communicator write, the user devComm words

// ---- the model: processes, record channels ----
static const int kN = 4;
static const uint64_t kComm = 0xc0ffee12345678ull, kGen = 0x9e11a7ull;
struct Proc {
  int rank = 0;
  uint32_t inc = 0;
  bool helperOn = true;
  bool gone = false;  // fenced (its process ended)
  struct gdaki_context ctx;
  struct gdakiQ4Host q4;
  ncclResult_t async = ncclSuccess;
  struct gdakiTs ts;
  struct gdakiHold hold;
  struct gdakiRecHost r;
  std::vector<uint32_t> known;
  std::vector<struct doca_gpu_verbs_qp> qv;
  std::vector<struct doca_gpu_verbs_qp_hl> qh;
  std::vector<int> qpErr;
  std::vector<uint32_t> gateWord;
  uint32_t* words = nullptr;
  int holdStarts = 0, policyCalls = 0, policyInApply = 0, recoverAborts = 0, failSent = 0, pauseEnded = 0, gateFailN = 0;
  int fallbacks = 0;
  double releasedAt = -1;
  ~Proc() { free(words); }
};
static std::vector<std::unique_ptr<Proc>> gProcs;
static Proc* gCur[kN];
struct Msg {
  int from;
  struct gdakiTsMsg m;
  double at;
};
struct Chan {
  bool up = false;
  bool held = false;  // queued, not delivered (before the peer's CONNECTED)
  uint32_t gen = 1;
  std::deque<struct Msg> q;
};
static Chan gChan[kN][kN];
static std::mt19937 gRng(1);
static double gLatLo = 0.05, gLatHi = 3.0;
static double gLat() { return std::uniform_real_distribution<double>(gLatLo, gLatHi)(gRng); }
static Proc* P(struct gdakiRecHost* r) { return (Proc*)r->commKey; }
static struct gdakiUa* uaOf(Proc* p) {
  for (auto& x : gdakiUaReg)
    if (x.comm == (void*)p) return &x;
  return nullptr;
}
static Proc* newProc(int rank, uint32_t inc, int nCtx = 2) {
  gProcs.emplace_back(new Proc());
  Proc* p = gProcs.back().get();
  p->rank = rank;
  p->inc = inc;
  p->ctx.rank = rank;
  p->ctx.nContexts = nCtx;
  p->ctx.q4 = &p->q4;
  p->q4.asyncResult = &p->async;
  p->r.commKey = (void*)p;
  p->r.ctx = &p->ctx;
  p->r.nranks = kN;
  p->r.ts = &p->ts;
  p->r.hold = &p->hold;
  p->r.prepared.assign(kN, 0);
  const int nq = kN * nCtx;
  p->qv.resize((size_t)nq);
  p->qh.resize((size_t)nq);
  p->ctx.gqps.resize((size_t)nq);
  p->r.qps.resize((size_t)nq);
  for (int i = 0; i < nq; i++) {
    p->qh[(size_t)i].qp_gverbs = &p->qv[(size_t)i];
    p->ctx.gqps[(size_t)i] = &p->qh[(size_t)i];
    p->r.qps[(size_t)i].used = i % kN != rank;
    p->r.qps[(size_t)i].qpIdx = i;
    p->r.qps[(size_t)i].ctxIdx = i / kN;
    p->r.qps[(size_t)i].peer = i % kN;
  }
  p->ts.peers.resize(kN);
  p->ts.qs.resize((size_t)nq);
  p->qpErr.assign((size_t)nq, 0);
  p->gateWord.assign((size_t)nq, 0);
  p->hold.rank = rank;
  p->hold.nranks = kN;
  p->hold.cells = new gdakiHoldCell[kN];
  p->known.assign(kN, 0);
  p->known[(size_t)rank] = inc;
  p->words = (uint32_t*)calloc(kN + 1, sizeof(uint32_t));
  struct gdakiUa u;
  u.comm = (void*)p;
  u.rank = rank;
  u.n = kN;
  u.word = p->words;
  u.why = 0;
  u.peerWhy.assign(kN, 0);
  u.expected.assign(kN, 1);
  u.expected[(size_t)rank] = 0;
  gdakiUaReg.push_back(u);
  gdakiAdSetGen(&p->r, kGen);
  gdakiAdSetCommHash(&p->r, kComm);
  return p;
}
static void pairUp(int a, int b, bool up) {
  for (int k = 0; k < 2; k++) {
    Chan& c = k == 0 ? gChan[a][b] : gChan[b][a];
    c.up = up;
    c.q.clear();
    c.held = false;
    c.gen++;
  }
}
static void regen(int a, int b) {  // a QP regeneration of the pair: the queued records are gone, a new generation
  for (int k = 0; k < 2; k++) {
    Chan& c = k == 0 ? gChan[a][b] : gChan[b][a];
    c.q.clear();
    c.held = false;
    c.gen++;
  }
}
static void reset() {
  for (int a = 0; a < kN; a++)
    for (int b = 0; b < kN; b++) gChan[a][b] = Chan();
  for (auto& p : gProcs) gdakiAdFree(&p->r);
  gProcs.clear();
  gdakiUaReg.clear();
  gdakiUaDegradedPending.store(0);
  gLines.clear();
  gNow = 0;
  gDegMs = 2000;
  gdakiTsScope = GDAKI_TS_SCOPE_ALL;
  for (int q = 0; q < kN; q++) gCur[q] = newProc(q, 0);
  for (int a = 0; a < kN; a++)
    for (int b = a + 1; b < kN; b++) pairUp(a, b, true);
}

// ---- the fakes the cut code calls ----
static ncclResult_t ncclGinRecoverAbort(ncclComm_t c, int peer) {
  Proc* p = (Proc*)(void*)c;
  p->recoverAborts++;
  p->r.prepared[(size_t)peer] = 0;
  return ncclSuccess;
}
static int gdakiRecPrepared(struct gdakiRecHost* r, int peer) { return (int)r->prepared[(size_t)peer]; }
static void gdakiRecAllToErr(struct gdakiRecHost* r, int peer) {
  gdakiRecForPeer(r, peer, [&](gdakiRecQp& rq, struct doca_gpu_verbs_qp_hl*) { P(r)->qpErr[(size_t)rq.qpIdx]++; });
}
static void gdakiBlameNote(const void*, int, gdakiCause) {}
static bool gdakiCtrlChanUp(struct gdakiRecHost* r, int peer) { return gChan[P(r)->rank][peer].up; }
static bool gdakiCtrlChanUp(struct gdakiRecHost* r, int peer, const struct gdakiTsPeer&) { return gdakiCtrlChanUp(r, peer); }
static uint32_t gdakiCtrlChanGen(struct gdakiRecHost* r, int peer, const struct gdakiTsPeer&) { return gChan[P(r)->rank][peer].gen; }
static int gdakiCtrlSend(struct gdakiRecHost* r, int, uint32_t, int, struct gdakiTsMsg* m, int) {
  if (m->type == GDAKI_TS_FAIL) P(r)->failSent++;
  return 0;
}
static ncclResult_t gdakiTsWordHiWrite(struct gdakiRecHost* r, struct doca_gpu_verbs_qp* v, uint32_t hi) {
  Proc* p = P(r);
  if (p->gateFailN > 0) {
    p->gateFailN--;
    return ncclSystemError;
  }
  p->gateWord[(size_t)(v - p->qv.data())] = hi;
  return ncclSuccess;
}
static void gdakiCkptPauseGatesEnded(struct gdakiRecHost* r, int) { P(r)->pauseEnded++; }
static struct gdakiHold* gdakiHoldOf(struct gdakiRecHost* r) { return r != nullptr ? r->hold : nullptr; }
static uint32_t gdakiRsPeerInc(struct gdakiRecHost* r, int d) { return P(r)->known[(size_t)d]; }
static uint32_t gdakiRsSelfInc(struct gdakiRecHost* r) { return P(r)->inc; }
static struct gdakiLnView gdakiLnOf(struct gdakiRecHost* r, int d) {
  Proc* p = P(r);
  const uint32_t known = p->known[(size_t)d];
  if (d == p->rank) return gdakiLnSelfView(known);
  const uint64_t v = gdakiHoldLoad(p->hold.cells[d]);
  return gdakiLnViewOf(gdakiHoldStateOf(v), gdakiHoldIncOf(v), known, p->ts.peers[(size_t)d].declined);
}
static bool uaTold(Proc* p, int peer) {
  struct gdakiUa* e = uaOf(p);
  return e != nullptr && (e->allWhy != 0 || e->why != 0 || e->peerWhy[(size_t)peer] != 0 || e->degradedAtMs != 0);
}
// the hold's decline hook (gdakiHoldOnDecline's outline): a held peer falls back; an ARMED one is held on a death that
// nothing told the application yet (a hold start), else declined without a hold (NOHOLD: OFF)
static bool gdakiPolicyOnDecline(struct gdakiRecHost* r, int peer, const char*, gdakiCause, int uaWhy) {
  Proc* p = P(r);
  p->policyCalls++;
  if (gdakiAdApplyAt != nullptr) p->policyInApply++;
  struct gdakiHoldCell& c = p->hold.cells[peer];
  const uint64_t v = gdakiHoldLoad(c);
  const uint32_t st = gdakiHoldStateOf(v);
  if (gdakiHoldIsHeldState(st)) {
    c.v.store(gdakiHoldPack(GDAKI_HOLD_FALLBACK, gdakiHoldIncOf(v)));
    p->hold.heldPeer.store(-1);
    p->fallbacks++;
    return false;
  }
  if (st == GDAKI_HOLD_ARMED && uaWhy == GDAKI_UA_PEER_DEAD) {
    if (!uaTold(p, peer)) {
      c.v.store(gdakiHoldPack(GDAKI_HOLD_HELD, gdakiHoldIncOf(v)));
      p->hold.heldPeer.store(peer);
      p->holdStarts++;
      return true;
    }
    c.v.store(gdakiHoldPack(GDAKI_HOLD_OFF, gdakiHoldIncOf(v)));
  }
  return false;
}
static int gdakiHoldSend(struct gdakiRecHost* r, int to, struct gdakiTsMsg* m) {
  Proc* p = P(r);
  if (to < 0 || to >= kN || to == p->rank || !gChan[p->rank][to].up) return -1;
  m->from = p->rank;
  m->nonce = p->ts.nonce;
  gChan[p->rank][to].q.push_back({p->rank, *m, gNow + gLat()});
  return 0;
}
#include "gc_ad_cut_b.inc"

// ---- the model's steps ----
template <typename F>
static void onHelper(Proc* p, F f) {
  gdakiTsInHelper = true;
  gdakiTsOwner = &p->r;
  f();
  gdakiTsInHelper = false;
  gdakiTsOwner = nullptr;
}
static std::multimap<double, std::function<void()>> gEv;
static void at(double t, std::function<void()> f) { gEv.insert({t, std::move(f)}); }
static void deliverTo(Proc* p) {
  for (int x = 0; x < kN; x++) {
    if (x == p->rank) continue;
    Chan& c = gChan[x][p->rank];
    while (!c.q.empty() && !c.held && c.q.front().at <= gNow) {
      const struct Msg msg = c.q.front();
      c.q.pop_front();
      gdakiAdOnRecord(&p->r, msg.from, msg.m);
    }
  }
}
static const double kTick = 0.25;
static void run(double until) {
  while (gNow <= until) {
    while (!gEv.empty() && gEv.begin()->first <= gNow) {
      auto f = gEv.begin()->second;
      gEv.erase(gEv.begin());
      f();
    }
    gdakiUaDegradedStep();
    for (int q = 0; q < kN; q++) gdakiHoldWatchdog(&gCur[q]->r);  // the watchers (record only)
    for (int q = 0; q < kN; q++) {
      Proc* p = gCur[q];
      if (!p->helperOn || p->gone) continue;
      onHelper(p, [&] {
        deliverTo(p);
        gdakiAdHelperStep(&p->r);
      });
    }
    for (auto& p : gProcs)
      if (p->releasedAt < 0 && __atomic_load_n(&p->words[0], __ATOMIC_ACQUIRE) != 0) p->releasedAt = gNow;
    gNow += kTick;
  }
  gEv.clear();
}
// rank p judges rank t stalled on its helper (gdakiCtrlStallDecline's decline; STALLED is a line and not modelled)
static void judge(Proc* p, int t, const char* cause = "STALL") {
  onHelper(p, [&] {
    snprintf(p->ts.peers[(size_t)t].lostCause, sizeof(p->ts.peers[(size_t)t].lostCause), "%s", cause);
    char why[96];
    snprintf(why, sizeof(why), "liveness stall judged (%s)", cause);
    gdakiTsDecline(&p->r, t, why, false, 0, gdakiCause::PeerDead, GDAKI_UA_PEER_DEAD);
  });
}
// the restore of rank d (the death of its incarnation): every survivor holds it at tF (its channels down, its process
// ends), the buddy builds the activation blob at tA (the spare stores what it carries), the activation table and every
// REJOIN_ACK at tJ (the spare's lineage view complete; the pairs up again in a new generation), RESTORED at tR (the
// survivors' cell LIVE of the new incarnation, the spare's helper starts). table[q]: the incarnations the table names.
struct Restore {
  Proc* spare = nullptr;
};
static std::vector<std::shared_ptr<Restore>> gRestores;
static std::shared_ptr<Restore> restore(int d, double tF, double tA, double tJ, double tR, bool blob = true) {
  auto R = std::make_shared<Restore>();
  gRestores.push_back(R);
  at(tF, [=] {
    Proc* dead = gCur[d];
    for (int q = 0; q < kN; q++) {
      if (q == d) continue;
      Proc* s = gCur[q];
      s->hold.cells[d].v.store(gdakiHoldPack(GDAKI_HOLD_HELD, dead->inc));
      s->hold.cells[d].deadlineUs.store(0);
      s->hold.heldPeer.store(d);
      pairUp(q, d, false);
    }
    dead->gone = true;
  });
  at(tA, [=] {
    const uint32_t inc = gCur[d]->inc + 1;
    Proc* b = gCur[gdakiHoldBuddyOf(d, kN)];
    std::vector<uint8_t> bytes;
    gdakiCtrlActUdPut(std::vector<struct gdakiCtrlActUd>(), &bytes);
    if (blob) onHelper(b, [&] { gdakiAdBlobFor(&b->r, d, &bytes); });
    Proc* s = newProc(d, inc);
    s->helperOn = false;
    const size_t udN = gdakiCtrlActUdLenOf(bytes.data(), bytes.size(), kN);
    std::vector<struct gdakiCtrlActUd> ud;
    CHECK(gdakiCtrlActUdGet(bytes.data(), udN, kN, &ud));
    CHECK(gdakiAdBlobTake(&s->r, bytes.data() + udN, bytes.size() - udN));
    gCur[d] = s;
    R->spare = s;
  });
  at(tJ, [=] {
    Proc* s = gCur[d];
    for (int q = 0; q < kN; q++) {
      if (q == d) continue;
      Proc* sv = gCur[q];
      s->known[(size_t)q] = sv->inc;  // the activation table, then the survivor's REJOIN_ACK
      s->hold.cells[q].v.store(gdakiHoldPack(GDAKI_HOLD_OFF, sv->inc));
      sv->known[(size_t)d] = s->inc;  // HOLD_SUCC: the successor's REJOIN accepted
      pairUp(q, d, true);
    }
    gdakiAdLineageComplete(&s->r);
  });
  at(tR, [=] {
    Proc* s = gCur[d];
    for (int q = 0; q < kN; q++) {
      if (q == d) continue;
      Proc* sv = gCur[q];
      sv->hold.cells[d].v.store(gdakiHoldPack(GDAKI_HOLD_OFF, s->inc));
      int e = d;
      sv->hold.heldPeer.compare_exchange_strong(e, -1);
    }
    s->helperOn = true;
  });
  return R;
}
static const struct gdakiAdState* adOf(Proc* p) { return gdakiAdOf(&p->r); }
static int nOwn(Proc* p, uint32_t cause = 0) {
  int n = 0;
  for (const auto& l : adOf(p)->log) n += l.e.state == GDAKI_AD_S_OWN && (cause == 0 || l.e.cause == cause);
  return n;
}
static int nState(Proc* p, uint32_t st) {
  int n = 0;
  for (const auto& l : adOf(p)->log) n += l.e.state == st;
  return n;
}
static const struct gdakiAdPeerSt& ps(Proc* p, int q) { return adOf(p)->peers[(size_t)q]; }
static int qpErrTo(Proc* p, int peer) {
  int n = 0;
  for (size_t i = 0; i < p->qpErr.size(); i++) n += (int)i % kN == peer ? p->qpErr[i] : 0;
  return n;
}
static double ownDeadline(Proc* p) {
  for (const auto& l : adOf(p)->log)
    if (l.e.state == GDAKI_AD_S_OWN) return l.e.deadlineMs;
  return -1;
}
static bool near(double a, double b, double lo, double hi) { return a >= b - lo && a <= b + hi; }
static double slack(int hops) { return hops * (gLatHi + kTick) + kTick + 0.01; }  // the transits, their ticks, the release's
static struct gdakiTsMsg craft(int target, uint32_t tInc, int decider, uint32_t dInc, uint32_t no, double remainingMs,
                               uint32_t fwdInc, uint64_t comm = kComm, uint64_t gen = kGen) {
  struct gdakiAdEntry e;
  e.commHash = comm;
  e.gen = gen;
  e.target = target;
  e.targetInc = tInc;
  e.decider = decider;
  e.deciderInc = dInc;
  e.no = no;
  e.cause = GDAKI_AD_C_STALL;
  e.deadlineMs = remainingMs < 0 ? -1 : gNow + remainingMs;
  e.deciderDeadlineMs = e.deadlineMs;
  struct gdakiTsMsg m;
  gdakiAdMsgOf(e, fwdInc, gNow, &m);
  m.from = decider;
  return m;
}
static void give(Proc* to, int from, const struct gdakiTsMsg& m) {
  onHelper(to, [&] { gdakiAdOnRecord(&to->r, from, m); });
}

// ---- 1. the pure pieces ----
static void testPure() {
  gScene = "pure";
  CHECK(gdakiAdCauseFrom("STALL", "liveness stall judged (STALL)") == GDAKI_AD_C_STALL);
  CHECK(gdakiAdCauseFrom("", "liveness stall judged (STALL)") == GDAKI_AD_C_STALL);
  CHECK(gdakiAdCauseFrom("STALL_HELPER", "liveness stall judged (STALL_HELPER)") == GDAKI_AD_C_STALL_HELPER);
  CHECK(gdakiAdCauseFrom("FIN+STALE", "peer judged dead: the judgement table shows FIN+STALE") == GDAKI_AD_C_FIN);
  CHECK(gdakiAdCauseFrom("FIN+NORESP", "x") == GDAKI_AD_C_FIN);
  CHECK(gdakiAdCauseFrom("NORESP", "x") == GDAKI_AD_C_NORESP);
  CHECK(gdakiAdCauseFrom("STALL", "restore fallback: the deadline") == GDAKI_AD_C_FALLBACK);
  CHECK(gdakiAdCauseFrom("", "the peer declined") == GDAKI_AD_C_OTHER);
  CHECK(gdakiAdCauseFrom(nullptr, nullptr) == GDAKI_AD_C_OTHER);
  // record 57 both ways: the remaining time on the way, the receiver's own clock
  struct gdakiAdEntry e;
  e.commHash = kComm;
  e.gen = kGen;
  e.target = 1;
  e.targetInc = 3;
  e.decider = 2;
  e.deciderInc = 1;
  e.no = 7;
  e.cause = GDAKI_AD_C_STALL;
  e.deadlineMs = 5000;
  e.deciderDeadlineMs = 4321;
  struct gdakiTsMsg m;
  gdakiAdMsgOf(e, 9, 3500, &m);
  CHECK(m.type == GDAKI_TS_CTRL_ABORT_DECIDED && m.arg == 1 && m.round == 3 && m.nqp == 7 && m.pad == GDAKI_AD_C_STALL);
  CHECK(m.executed[0] == 2 && m.executed[1] == 1 && m.executed[2] == 9 && m.t[0] == 1500 && m.t[3] == 4321);
  uint32_t fwd = 0;
  const struct gdakiAdEntry f = gdakiAdOfMsg(m, 0, 100, &fwd);
  CHECK(fwd == 9 && f.commHash == kComm && f.gen == kGen && f.target == 1 && f.targetInc == 3 && f.decider == 2 &&
        f.deciderInc == 1 && f.no == 7 && f.deadlineMs == 1600 && f.from == 0 && !f.blob);
  gdakiAdMsgOf(e, 9, 6000, &m);  // past its release: 0 left (raised at once there)
  CHECK(m.t[0] == 0);
  e.deadlineMs = -1;
  gdakiAdMsgOf(e, 9, 6000, &m);
  CHECK(m.t[0] == -1 && gdakiAdOfMsg(m, 0, 100, &fwd).deadlineMs == -1);
  // the blob: none, entries, damaged
  std::vector<struct gdakiAdWire> w, r;
  CHECK(gdakiAdBlobGet(nullptr, 0, kN, &r) && r.empty());
  e.deadlineMs = 5000;
  w.push_back(gdakiAdWireOf(e, 4, 4000));
  e.no = 8;
  w.push_back(gdakiAdWireOf(e, 4, 4000));
  std::vector<uint8_t> b;
  gdakiCtrlActUdPut(std::vector<struct gdakiCtrlActUd>(1), &b);  // one UD entry first (rank 0)
  const size_t ud = b.size();
  gdakiAdBlobPut(w, &b);
  CHECK(gdakiCtrlActUdLenOf(b.data(), b.size(), kN) == ud);
  CHECK(gdakiAdBlobGet(b.data() + ud, b.size() - ud, kN, &r) && r.size() == 2 && r[1].no == 8 && r[0].remainingMs == 1000);
  CHECK(gdakiAdOfWire(r[0], 3, 200).deadlineMs == 1200 && gdakiAdOfWire(r[0], 3, 200).blob);
  CHECK(!gdakiAdBlobGet(b.data() + ud, b.size() - ud - 1, kN, &r));  // cut
  std::vector<uint8_t> bad(b.begin() + (long)ud, b.end());
  bad[0] ^= 1;  // the magic
  CHECK(!gdakiAdBlobGet(bad.data(), bad.size(), kN, &r));
  w[0].target = kN;  // a rank outside
  std::vector<uint8_t> b2;
  gdakiAdBlobPut(w, &b2);
  CHECK(!gdakiAdBlobGet(b2.data(), b2.size(), kN, &r));
  std::vector<uint8_t> u0;
  gdakiCtrlActUdPut(std::vector<struct gdakiCtrlActUd>(), &u0);
  CHECK(gdakiCtrlActUdLenOf(u0.data(), u0.size(), kN) == 8 && gdakiCtrlActUdLenOf(u0.data(), 3, kN) == 3);
  // the receive rule
  struct gdakiAdRxIn in;
  in.sameComm = in.sameGen = true;
  CHECK(gdakiAdRxAction(in) == GDAKI_AD_RX_APPLY);
  in.targetCls = GDAKI_LN_HELD_OLD;
  CHECK(gdakiAdRxAction(in) == GDAKI_AD_RX_DEFER);
  in.targetCls = GDAKI_LN_STALE;
  CHECK(gdakiAdRxAction(in) == GDAKI_AD_RX_STALE);
  in.targetCls = GDAKI_LN_FUTURE;
  CHECK(gdakiAdRxAction(in) == GDAKI_AD_RX_STALE);
  in.targetCls = GDAKI_LN_CURRENT;
  in.applied = true;
  CHECK(gdakiAdRxAction(in) == GDAKI_AD_RX_LATE);
  in.applied = false;
  in.ownJudged = true;
  CHECK(gdakiAdRxAction(in) == GDAKI_AD_RX_LATE);
  in.lnComplete = false;
  CHECK(gdakiAdRxAction(in) == GDAKI_AD_RX_PEND);
  in.self = true;
  CHECK(gdakiAdRxAction(in) == GDAKI_AD_RX_SELF);
  in.fwdCurrent = false;
  CHECK(gdakiAdRxAction(in) == GDAKI_AD_RX_FWD_STALE);
  in.dup = true;
  CHECK(gdakiAdRxAction(in) == GDAKI_AD_RX_DUP);
  in.sameGen = false;
  CHECK(gdakiAdRxAction(in) == GDAKI_AD_RX_OTHER);
  // the key and the send rule
  struct gdakiAdKey k;
  bool first = false;
  CHECK(!gdakiAdKeyMove(&k, 0, 5, &first) && first && k.epoch == 1);
  CHECK(!gdakiAdKeyMove(&k, 0, 5, &first) && !first && k.epoch == 1);
  CHECK(gdakiAdKeyMove(&k, 0, 6, &first) && !first && k.epoch == 2);  // a QP regeneration
  CHECK(gdakiAdKeyMove(&k, 1, 6, &first) && k.epoch == 3);             // a new incarnation
  CHECK(gdakiAdTxWhat(true, 1, 0, 1, false) == 1);   // own, its epoch: once, open or not
  CHECK(gdakiAdTxWhat(true, 1, 1, 1, true) == 0);    // sent in this epoch
  CHECK(gdakiAdTxWhat(true, 1, 1, 2, true) == 2);    // a later key: again while open
  CHECK(gdakiAdTxWhat(true, 1, 1, 2, false) == 0);   // ... not after its release
  CHECK(gdakiAdTxWhat(false, 1, 0, 1, true) == 0);   // taken in this epoch: not sent on (no re-broadcast)
  CHECK(gdakiAdTxWhat(false, 1, 0, 2, true) == 2);   // a later key: forwarded
  CHECK(gdakiAdTxWhat(true, 0, 0, 0, true) == 0);    // a peer never keyed
}

// ---- 2. the scenes ----
// A1: the waiter-hung shape of pilot 5: rank 3 restored (incarnation 1) at about 10.2 s, then rank 1 (hung) judged by r0
// at about 12.26 s and by r2 about 96 ms later; the restored rank 3 releases its waits with the survivors, no hold, no fence
static void sceneA1() {
  reset();
  restore(3, 10050, 10170, 10200, 10240);
  const double j0 = 12261 + std::uniform_real_distribution<double>(-30, 30)(gRng);
  const double j2 = j0 + std::uniform_real_distribution<double>(20, 150)(gRng);
  at(j0, [] { judge(gCur[0], 1); });
  at(j2, [] { judge(gCur[2], 1); });
  run(60000);
  Proc *r0 = gCur[0], *r2 = gCur[2], *s3 = gCur[3];
  CHECK(s3->inc == 1);
  CHECK(nOwn(r0, GDAKI_AD_C_STALL) == 1 && nOwn(r2) == 0 && nOwn(s3) == 0);
  const double rel = ownDeadline(r0);
  CHECK(near(rel, j0 + 2000, 0.01, kTick + 0.01));
  CHECK(near(r0->releasedAt, rel, 0, kTick + 0.01));
  CHECK(near(s3->releasedAt, rel, 0, slack(1)));  // with the survivors, not by the watchdog
  CHECK(s3->releasedAt > 0 && s3->releasedAt < 60000);
  CHECK(near(r2->releasedAt, rel, 0, slack(1)));
  CHECK(ps(s3, 0).rxApplied == 1 && ps(r2, 0).rxApplied == 1 && ps(r0, 3).tx == 1 && ps(r0, 2).tx == 1 && ps(r0, 1).tx == 0);
  CHECK(s3->ts.peers[1].declined && qpErrTo(s3, 1) == 2 && s3->failSent == 0 && s3->policyInApply == 0);
  CHECK(s3->holdStarts == 0 && r2->holdStarts == 0 && r0->holdStarts == 0);
  CHECK(r2->ts.peers[1].declined && r2->policyInApply == 0 && r2->policyCalls == 1);  // r2's own judgement: the hook once
}
// A2: a decision about rank 3's incarnation 0 at rank 3's incarnation 1 (about itself) and at a survivor that restored it
static void sceneA2() {
  reset();
  restore(3, 1000, 1100, 1150, 1200);
  run(1300);
  give(gCur[3], 0, craft(3, 0, 0, 0, 1, 1500, 0));
  give(gCur[2], 0, craft(3, 0, 0, 0, 1, 1500, 0));
  run(5000);
  CHECK(!gCur[3]->ts.peers[3].declined && gCur[3]->releasedAt < 0 && ps(gCur[3], 0).rxStale == 1);
  CHECK(!gCur[2]->ts.peers[3].declined && qpErrTo(gCur[2], 3) == 0 && gCur[2]->releasedAt < 0 && ps(gCur[2], 0).rxStale == 1);
}
// A3: the same record twice, and two deciders' decisions about one target: applied once, the release unchanged
static void sceneA3() {
  reset();
  Proc* x = gCur[3];
  run(1000);
  const struct gdakiTsMsg a = craft(1, 0, 0, 0, 1, 2000, 0);
  give(x, 0, a);
  const double d0 = uaOf(x)->degradedAtMs;
  give(x, 0, a);
  run(1500);
  give(x, 2, craft(1, 0, 2, 0, 1, 1500, 0));
  run(5000);
  CHECK(ps(x, 0).rxApplied == 1 && ps(x, 0).rxDup == 1 && ps(x, 2).rxLate == 1 && ps(x, 2).rxApplied == 0);
  CHECK(d0 > 0 && near(x->releasedAt, d0, 0, kTick + 0.01) && qpErrTo(x, 1) == 2);
}
// A4: a decision after this rank's own decline and release: no word, no schedule, one late line
static void sceneA4() {
  reset();
  Proc* x = gCur[2];
  at(1000, [x] { judge(x, 1); });
  run(4000);
  const double rel = x->releasedAt;
  const size_t lines = gLines.size();
  const uint32_t w0 = x->words[0], w1 = x->words[2];
  give(x, 0, craft(1, 0, 0, 0, 1, 1500, 0));
  run(6000);
  CHECK(rel > 0 && x->releasedAt == rel && x->words[0] == w0 && x->words[2] == w1 && uaOf(x)->degradedAtMs == 0);
  CHECK(ps(x, 0).rxLate == 1 && gLines.size() == lines + 1);
}
// A5a: the decision before the activation: rank 1 was restored before (incarnation 1), the decision names (1, 1), rank 3's
// spare stores it from its blob (its transcript knows rank 1 as incarnation 0) and checks it once its lineage is complete
static void sceneA5a() {
  reset();
  restore(1, 1000, 1100, 1150, 1200);
  restore(3, 10050, 10170, 10200, 10240);
  const double j = 10100;
  at(j, [] { judge(gCur[0], 1); });
  run(60000);
  Proc *r0 = gCur[0], *s3 = gCur[3];
  CHECK(gCur[1]->inc == 1 && s3->inc == 1);
  const double rel = ownDeadline(r0);
  CHECK(near(rel, j + 2000, 0.01, kTick + 0.01));
  CHECK(s3->releasedAt > 0 && near(s3->releasedAt, rel, 0, slack(2)));
  CHECK(ps(s3, 2).rxDeferred == 1 && ps(s3, 2).rxApplied == 1);  // the blob's, stored, applied at the helper's start
  CHECK(ps(s3, 0).rxDup + ps(s3, 2).rxDup >= 1);                  // the survivors' resend on live
  CHECK(s3->ts.peers[1].declined && s3->holdStarts == 0 && s3->policyInApply == 0);
}
// A5b, A5c: the decision after the blob (before the REJOIN_ACKs; between them and RESTORED): the resend on live
static void sceneA5b(double j) {
  reset();
  restore(3, 10050, 10170, 10200, 10240);
  at(j, [] { judge(gCur[0], 1); });
  run(60000);
  Proc *r0 = gCur[0], *s3 = gCur[3];
  const double rel = ownDeadline(r0);
  CHECK(s3->releasedAt > 0 && near(s3->releasedAt, rel, 0, slack(2)));
  CHECK(ps(r0, 3).resend == 1 && ps(s3, 0).rxApplied + ps(s3, 2).rxApplied == 1);
}
// A6: another communicator, another generation: dropped
static void sceneA6() {
  reset();
  Proc* x = gCur[2];
  give(x, 0, craft(1, 0, 0, 0, 1, 1500, 0, kComm ^ 1));
  give(x, 0, craft(1, 0, 0, 0, 2, 1500, 0, kComm, kGen + 1));
  run(4000);
  CHECK(ps(x, 0).rxOther == 2 && !x->ts.peers[1].declined && x->releasedAt < 0 && qpErrTo(x, 1) == 0);
}
// A7: two decisions about two targets, the second number first: both applied, the release the earlier one
static void sceneA7() {
  reset();
  Proc* x = gCur[2];
  run(100);
  give(x, 0, craft(3, 0, 0, 0, 2, 1800, 0));
  give(x, 0, craft(1, 0, 0, 0, 1, 1500, 0));
  run(4000);
  CHECK(ps(x, 0).rxApplied == 2 && x->ts.peers[1].declined && x->ts.peers[3].declined);
  CHECK(near(x->releasedAt, 100 + 1500, 0, slack(0)));
}
// A8 (review3 5: no young-view rule): a survivor with its own judgement 96 ms behind applies the decision at once (its
// release the decider's), its own judgement then moves nothing (no decision of its own, nothing sent)
static void sceneA8() {
  reset();
  at(3000, [] { judge(gCur[0], 1); });
  at(3096, [] { judge(gCur[2], 1); });
  run(8000);
  CHECK(near(gCur[2]->releasedAt, 3000 + 2000, 0, slack(1)) && nOwn(gCur[2]) == 0 && ps(gCur[2], 3).tx == 0);
  CHECK(ps(gCur[2], 0).rxApplied == 1);
}
// A9: the target ARMED at the receiver: no hold starts (the policy hook is off for the apply)
static void sceneA9() {
  reset();
  for (int q = 0; q < kN; q++) gCur[q]->hold.cells[1].v.store(gdakiHoldPack(GDAKI_HOLD_ARMED, 0));
  gCur[0]->hold.cells[1].v.store(gdakiHoldPack(GDAKI_HOLD_OFF, 0));  // the decider's: not armed (it declines)
  at(3000, [] { judge(gCur[0], 1); });
  run(6000);
  CHECK(gCur[2]->holdStarts == 0 && gCur[3]->holdStarts == 0 && gCur[2]->policyInApply == 0 && gCur[3]->policyInApply == 0);
  CHECK(ps(gCur[2], 0).rxApplied == 1 && ps(gCur[3], 0).rxApplied == 1 && gCur[2]->ts.peers[1].declined);
}
// review3 1: the watcher moves first (a held peer's deadline), the helper declines after it: one decision (DEADLINE),
// recorded by the watcher with nothing sent from it, sent by the helper; a holder that took it deferred it (its hold in
// progress) and found it late at its own deadline
static void sceneWatcherFirst() {
  reset();
  for (int q = 0; q < 3; q++) {
    Proc* s = gCur[q];
    s->hold.cells[3].v.store(gdakiHoldPack(GDAKI_HOLD_HELD, 0));
    s->hold.cells[3].deadlineUs.store((int64_t)((20000 + 300 * q) * 1000.0));
    s->hold.heldPeer.store(3);
    pairUp(q, 3, false);
  }
  gCur[3]->gone = true;
  run(20000 - kTick);
  gNow = 20000;  // r0's watcher by hand: its move recorded, nothing sent from it
  gdakiHoldWatchdog(&gCur[0]->r);
  CHECK(nOwn(gCur[0], GDAKI_AD_C_DEADLINE) == 1 && gChan[0][1].q.empty() && gChan[0][2].q.empty());
  at(20001, [] {  // the helper declines it next (its hold falls back): no second decision
    onHelper(gCur[0], [] {
      gdakiTsDecline(&gCur[0]->r, 3, "restore fallback: the deadline", false, 0, gdakiCause::PeerDead, GDAKI_UA_PEER_DEAD);
    });
  });
  run(30000);
  CHECK(nOwn(gCur[0]) == 1 && ps(gCur[0], 1).tx == 1 && ps(gCur[0], 2).tx == 1 && gCur[0]->fallbacks == 1);
  CHECK(ps(gCur[1], 0).rxDeferred == 1 && ps(gCur[1], 0).rxLate == 1 && ps(gCur[1], 0).rxApplied == 0);
  CHECK(nOwn(gCur[1], GDAKI_AD_C_DEADLINE) == 1 && nOwn(gCur[2], GDAKI_AD_C_DEADLINE) == 1);
  CHECK(near(gCur[0]->releasedAt, 22000, 0, kTick + 0.01));
}
// review3 1: NCCL_GIN_TS_DEGRADED_MS 0 and -1, every, duplicate calls
static void sceneDegraded() {
  reset();
  gDegMs = 0;  // released at once: a decision with 0 left; the receiver's word [0] at once
  at(1000, [] { judge(gCur[0], 1); });
  run(1100);
  CHECK(nOwn(gCur[0]) == 1 && near(gCur[0]->releasedAt, 1000, 0, kTick + 0.01) && ownDeadline(gCur[0]) == 1000);
  CHECK(near(gCur[2]->releasedAt, 1000, 0, slack(1)) && ps(gCur[2], 0).rxApplied == 1);
  reset();
  gDegMs = -1;  // the switch off: no move, no decision, nothing sent
  at(1000, [] { judge(gCur[0], 1); });
  run(4000);
  CHECK(nOwn(gCur[0]) == 0 && ps(gCur[0], 2).tx == 0 && gCur[2]->releasedAt < 0 && !gCur[2]->ts.peers[1].declined);
  give(gCur[2], 0, craft(1, 0, 0, 0, 1, 500, 0));  // a decision from a decider with the switch on: declined, not released
  run(6000);
  CHECK(gCur[2]->ts.peers[1].declined && gCur[2]->releasedAt < 0 && ps(gCur[2], 0).rxApplied == 1);
  reset();  // every gated peer declined (not dead): word [0] at once, a decision of cause every (its peers declined)
  onHelper(gCur[0], [] {
    gdakiTsDecline(&gCur[0]->r, 1, "the peer declined", false, 0, gdakiCause::Unknown);
    gdakiTsDecline(&gCur[0]->r, 2, "the peer declined", false, 0, gdakiCause::Unknown);
    gdakiTsDecline(&gCur[0]->r, 3, "the peer declined", false, 0, gdakiCause::Unknown);
  });
  run(100);
  CHECK(nOwn(gCur[0], GDAKI_AD_C_EVERY) == 1 && nOwn(gCur[0]) == 1 && gCur[0]->releasedAt == 0);
  CHECK(ps(gCur[0], 1).tx + ps(gCur[0], 2).tx + ps(gCur[0], 3).tx == 0);  // every peer declined: none current
  reset();  // duplicate calls: two raises, two declines of one peer: one decision
  onHelper(gCur[0], [] {
    struct gdakiUaTrans t1, t2;
    gdakiUaRaisePeer(gCur[0]->r.commKey, 1, GDAKI_UA_PEER_DEAD, nullptr, &t1);
    gdakiUaRaisePeer(gCur[0]->r.commKey, 1, GDAKI_UA_PEER_DEAD, nullptr, &t2);
    CHECK(t1.kind == 1 && t1.deadlineMs == 2000 && t2.kind == 0);
  });
  reset();
  at(1000, [] { judge(gCur[0], 1); });
  at(1001, [] { judge(gCur[0], 1); });
  at(1200, [] { judge(gCur[0], 2); });  // a second death: degraded already scheduled, no move
  run(4000);
  CHECK(nOwn(gCur[0]) == 1 && ps(gCur[0], 3).tx == 1);
}
// review3 2: a decision taken while this rank holds the target (HELD_OLD: deferred), the target's spare REJOINs (still
// held), the restore ends: checked again it is stale (the new incarnation untouched)
static void sceneRejoinRecheck() {
  reset();
  restore(3, 1000, 1100, 1150, 1200);
  at(1050, [] { give(gCur[2], 0, craft(3, 0, 0, 0, 1, 2000, 0)); });
  run(6000);
  Proc* s2 = gCur[2];
  CHECK(ps(s2, 0).rxDeferred == 1 && ps(s2, 0).rxStale == 1 && ps(s2, 0).rxApplied == 0);
  CHECK(!s2->ts.peers[3].declined && qpErrTo(s2, 3) == 0 && s2->releasedAt < 0);
}
// review3 2: a historical decider: rank 0's incarnation 0 decided, rank 0 died and came back as incarnation 1, rank 3
// is restored later from a buddy that took the decision: applied (the decider need not be current)
static void sceneHistorical() {
  reset();
  at(3000, [] { judge(gCur[0], 1); });
  restore(0, 3200, 3300, 3350, 3400);
  restore(3, 3600, 3700, 3750, 3800);
  run(60000);
  Proc* s3 = gCur[3];
  CHECK(gCur[0]->inc == 1 && s3->inc == 1);
  CHECK(s3->ts.peers[1].declined && near(s3->releasedAt, 5000, 0, slack(2)));
  CHECK(ps(s3, 2).rxApplied == 1);  // the blob's (rank 0's incarnation 0's decision), forwarded by rank 2
  CHECK(gCur[0]->ts.peers[1].declined && gCur[0]->releasedAt > 0);  // rank 0's new incarnation took its predecessor's
}
// review3 3: a record queued (before the peer's CONNECTED), the QP regenerated: the resend covers it
static void sceneRegen() {
  reset();
  at(2999, [] { gChan[0][2].held = true; });
  at(3000, [] { judge(gCur[0], 1); });
  at(3010, [] { regen(0, 2); });
  run(8000);
  CHECK(ps(gCur[0], 2).tx == 2 && ps(gCur[0], 2).resend == 1);
  CHECK(near(gCur[2]->releasedAt, 5000, 0, slack(1)) && ps(gCur[2], 0).rxApplied == 1);
}
// review3 6: two relays, the remaining time kept: rank 3 restored 500 ms after the decision (relay 1: rank 2), rank 2
// restored after it (relay 2: rank 3's spare, its buddy): every release at the decider's
static void sceneRelays() {
  reset();
  at(3000, [] { judge(gCur[0], 1); });
  restore(3, 3200, 3500, 3550, 3600);
  restore(2, 3700, 4000, 4050, 4100);
  run(60000);
  CHECK(gCur[3]->inc == 1 && gCur[2]->inc == 1);
  CHECK(near(gCur[3]->releasedAt, 5000, 0, slack(2)));
  CHECK(near(gCur[2]->releasedAt, 5000, 0, slack(3)));
  CHECK(ps(gCur[2], 3).rxApplied == 1);  // its blob came from rank 3's spare (relay 2)
}
// review3 4: through the real decline: prepared (its abort), a narrow scope (every context's QPs), deadJudged and
// failedPending, a gate write that fails (failPending), COMMITTING and PUBLISHED (deferred: nothing touched), another
// peer's hold left as it is (the TOLD rule is the hold's, later)
static void sceneApply() {
  reset();
  Proc* x = gCur[2];
  x->r.prepared[1] = 1;
  x->ts.peers[1].deadJudged = true;
  x->ts.peers[1].failedPending = true;
  x->gateFailN = 1;
  x->hold.cells[3].v.store(gdakiHoldPack(GDAKI_HOLD_COMMITTING, 0));
  x->hold.heldPeer.store(3);
  gdakiTsScope = 1u;  // inside a round of context 0 only
  const uint32_t e0 = x->ts.qs[1].epoch;
  give(x, 0, craft(1, 0, 0, 0, 1, 1500, 0));
  CHECK(gdakiTsScope == GDAKI_TS_SCOPE_ALL && qpErrTo(x, 1) == 2 && x->qpErr[1] == 1 && x->qpErr[1 + kN] == 1);
  CHECK(x->recoverAborts == 1 && x->r.prepared[1] == 0 && !x->ts.peers[1].deadJudged && !x->ts.peers[1].failedPending);
  CHECK(x->ts.peers[1].failPending && x->ts.nDeclined == 1 && x->async == ncclRemoteError && x->q4.hasError.load() == 1);
  CHECK(x->ts.qs[1].epoch == ((e0 | 1u) + 1u) && x->gateWord[1 + kN] == (NCCL_GIN_TS_W_HOST_FAILED | x->ts.qs[1 + kN].epoch));
  CHECK(x->failSent == 0 && x->policyInApply == 0 && x->pauseEnded == 1 && (x->words[2] & NCCL_DEVCOMM_ABORT_ERROR) != 0);
  CHECK(gdakiHoldStateOf(gdakiHoldLoad(x->hold.cells[3])) == GDAKI_HOLD_COMMITTING && x->hold.heldPeer.load() == 3);
  CHECK(uaTold(x, 3));  // the hold of rank 3 is told now: the hold's TOLD rule falls it back at its step (not this piece)
  for (uint32_t st : {(uint32_t)GDAKI_HOLD_COMMITTING, (uint32_t)GDAKI_HOLD_PUBLISHED, (uint32_t)GDAKI_HOLD_HELD}) {
    reset();
    Proc* y = gCur[2];
    y->hold.cells[1].v.store(gdakiHoldPack(st, 0));
    y->r.prepared[1] = 1;
    give(y, 0, craft(1, 0, 0, 0, 1, 1500, 0));
    run(100);
    CHECK(ps(y, 0).rxDeferred == 1 && ps(y, 0).rxApplied == 0 && qpErrTo(y, 1) == 0 && y->recoverAborts == 0);
    CHECK(gdakiHoldStateOf(gdakiHoldLoad(y->hold.cells[1])) == st && y->releasedAt < 0);
  }
}
// m1 with the record handler off: the restored rank waits for its watchdog (pilot 5's 2 of 2); the scenes below say
// which mutation must break which scene
struct Scene {
  const char* name;
  std::function<void()> f;
  int runs;
};

int main() {
  testPure();
  const long pureFailed = gFailed;
  std::vector<struct Scene> S = {
      {"A1 waiter hung (pilot 5's shape)", sceneA1, 40},
      {"A2 a stale incarnation's decision", sceneA2, 1},
      {"A3 duplicates and a second decider", sceneA3, 1},
      {"A4 late after the release", sceneA4, 1},
      {"A5a decision before the activation (its table)", sceneA5a, 20},
      {"A5b decision after the blob, before the REJOIN_ACKs", [] { sceneA5b(10185); }, 20},
      {"A5c decision between the REJOIN_ACKs and RESTORED", [] { sceneA5b(10220); }, 20},
      {"A6 another communicator or generation", sceneA6, 1},
      {"A7 two targets, the numbers reversed", sceneA7, 1},
      {"A8 an own judgement 96 ms behind", sceneA8, 10},
      {"A9 the target armed at the receiver", sceneA9, 5},
      {"watcher first, then the helper", sceneWatcherFirst, 5},
      {"DEGRADED_MS 0 and -1, every, duplicate calls", sceneDegraded, 3},
      {"receipt, the target's REJOIN, the re-check", sceneRejoinRecheck, 5},
      {"a historical decider forwarded", sceneHistorical, 10},
      {"queued, then the QP regenerated", sceneRegen, 10},
      {"two relays, the remaining time kept", sceneRelays, 20},
      {"the real decline's terminal effect", sceneApply, 1},
  };
  std::map<std::string, long> failedScene;
  for (const auto& s : S) {
    long bad = 0;
    for (int k = 0; k < s.runs; k++) {
      gScene = s.name;
      gRng.seed(1000u + (unsigned)k * 7919u + (unsigned)(&s - &S[0]) * 104729u);
      gSceneFailed = 0;
      s.f();
      if (gSceneFailed) bad++;
    }
    failedScene[s.name] = bad;
    printf("gc_unit_abortdec: scene %-52s %3d run(s), %3ld failed\n", s.name, s.runs, bad);
  }
  for (auto& p : gProcs) gdakiAdFree(&p->r);
  gProcs.clear();
  gdakiUaReg.clear();
  gRestores.clear();
#ifdef GC_AD_MUT
  // the scenes each mutation must break (build_gc.sh's text change of the cut)
  static const std::map<int, std::vector<std::string>> kMust = {
      {1, {"A1 waiter hung (pilot 5's shape)"}},                      // the record 57 handler off: the watchdog path
      {2, {"A5a decision before the activation (its table)"}},        // applied before the lineage view is complete
      {3, {"receipt, the target's REJOIN, the re-check"}},            // no re-check before a deferred apply
      {4, {"queued, then the QP regenerated", "A5b decision after the blob, before the REJOIN_ACKs"}},  // no resend
      {5, {"A3 duplicates and a second decider"}},                    // no duplicate check
      {6, {"A6 another communicator or generation"}},                 // no communicator check
      {7, {"two relays, the remaining time kept"}},                   // the remaining time ignored
      {8, {"A9 the target armed at the receiver"}},                   // the policy hook on for the apply
      {9, {"watcher first, then the helper"}},                        // the watcher's move not recorded
  };
  bool caught = true;
  for (const auto& n : kMust.at(GC_AD_MUT)) {
    printf("gc_unit_abortdec: mutation %d: scene %s: %ld failed run(s)\n", GC_AD_MUT, n.c_str(), failedScene[n]);
    if (failedScene[n] == 0) caught = false;
  }
  printf("gc_unit_abortdec: mutation %d %s\n", GC_AD_MUT, caught ? "caught" : "NOT caught");
  (void)pureFailed;
  return caught ? 0 : 1;
#else
  printf("gc_unit_abortdec (rdma): %ld checks, %ld failed (pure pieces: %ld)\n", gChecks, gFailed, pureFailed);
  return gFailed == 0 ? 0 : 1;
#endif
}
#else
int main() {
  printf("gc_unit_abortdec (tcp): 0 checks, 0 failed (the abort decisions are rdma only)\n");
  return 0;
}
#endif
