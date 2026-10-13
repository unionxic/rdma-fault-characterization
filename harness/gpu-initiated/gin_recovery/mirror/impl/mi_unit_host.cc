// mi_unit_host.cc - CPU unit test of gin-mirror's host branch (impl/PARALLEL.md row exp/gin-mirror-host; EXPERIMENT.md
// 9.2-9.5, 9.7). No NCCL, no CUDA, no network. Built by `BR=host build_mi.sh unit`: the regions "gin-restore: pure
// functions" (rs_pure.inc: Resume's local check and decision, which carry the mirror's conditions 34-40), "gin-restore
// hold: pure functions" (rs_hold_pure.inc), "gin-restore ckpt: pure functions" (rs_ckpt_pure.inc: gdakiCkptDue) and
// "gin-mirror (host): pure" (mi_pure_host.inc) cut from the working tree's
// gin_host_gdaki.cc, with impl/rs_mirror_api.h, impl/rs_hold_api.h v2 and impl/rs_ckpt_api.h; g++ with ASan and UBSan.
// What it checks:
//   1. Resume's local check: with the mirror off every gin-restore condition keeps its code (1..33) and text and the
//      mirror's facts change nothing; with it on each of 34, 35, 36, 37, 38, 40 alone, their precedence (a missing mirror
//      context is 40's, a bad 37 is not 35's, gin-restore's conditions first), and the spare (38's peers part skipped,
//      its self loop not);
//   2. Resume's decision: the mirror off gives gin-restore's verdicts and texts; the bit differing (34) and S or L
//      differing (39), named at the lowest rank and the same text whatever rank decides; a local refusal first; a spare's
//      own record among recorded ones;
//   3. the setup agreement (the policyPad bit; gin-restore's own decision ignores it) and the parameters (condition 37);
//      MIRROR_SETUP's check;
//   4. the segment state machine: switch, close, the third slot, the restart, the rollback by copy, the drops at
//      CKPT_STABLE, INJECTED and a new pool, the view and gdakiMiSegOfPos, and a random model (live segments never above S,
//      consecutive numbers, distinct slots and lanes, rollback exact);
//   5. the poll: breaks -> one DISARM per burst (and per segment), the pull once per segment at its threshold;
//   6. the absorption's decision: only the mirror context (any QP of it), the destinations a mirror QP serves (b's wards
//      but this rank; the self loop), the user scope mask;
//   7. PUBLISHED and INJECTED: the deadline rule (min(v1, D) with the gates kept odd, v1 otherwise), INJECTED's verdict
//      against every state, and the paths on a cell (RESTORED taken without a move, the watcher's timeout, INJECTED read
//      first wins, INJECTED before RESTORED ignored; the mirror off: RESTORED moves as gin-restore);
//   8. PAUSED's armable with the mirror's part (off: gin-restore's), the measurement mode's arm;
//   9. after the independent review: the ledger of one destination (the pause's switch, the rollback, host breaks during
//      the pause, CKPT_STABLE during the pause, the drops) against a model of the device's cell; MIRROR_SETUP's symmetry
//      over every combination of the two sides' facts (with the second record on = 0); the publish word (user QPs odd,
//      the mirror QP even); a stale fault record of the mirror context; the pull consumed by any idle Step; INJECTED's
//      resends.
#include <algorithm>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <random>
#include <string>
#include <thread>
#include <vector>

// what the host file has before these regions (a standalone test supplies it)
typedef enum { ncclSuccess = 0, ncclSystemError = 2, ncclInternalError = 3, ncclInvalidUsage = 5 } ncclResult_t;
enum { GDAKI_POLICY_FAILFAST = 0, GDAKI_POLICY_HOLD = 1 };  // hk's line
enum { GDAKI_TS_HELLO = 1, GDAKI_TS_REQ = 2, GDAKI_TS_ACK = 3, GDAKI_TS_NACK = 4, GDAKI_TS_DONE = 5, GDAKI_TS_FAIL = 6,
       GDAKI_TS_BYE = 10 };
#define NCCL_GIN_RS_QP_MASK 0xffffffu  // the device-host common header's (a log entry's QP field)
struct ncclGinRsLogEntry {             // impl/rs_log_api.h's standalone copy (64 bytes)
  uint32_t pos, qpKf, csum, sigWin, dstWin, srcWin;
  uint64_t dstOff, bytes, src, sigOff, sigVal;
};
#define GDAKI_HOLD_API_NO_ENTRY_DECLS
#include "rs_mirror_api.h"  // the device layout and helpers, the host API block, gdakiMiSegView
#include "rs_hold_api.h"
#include "rs_ckpt_api.h"
#include "rs_pure.inc"
#include "rs_hold_pure.inc"
#include "rs_ckpt_pure.inc"  // gdakiCkptDue (the pull model)
#include "mi_pure_host.inc"

static long gChecks = 0, gFailed = 0;
#define CHECK(c)                                                                     \
  do {                                                                               \
    gChecks++;                                                                       \
    if (!(c)) {                                                                      \
      gFailed++;                                                                     \
      if (gFailed <= 60) fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); \
    }                                                                                \
  } while (0)
static bool has(const char* s, const char* k) { return strstr(s, k) != nullptr; }
static bool startsWith(const char* s, const char* k) { return strncmp(s, k, strlen(k)) == 0; }

// ---- 1. Resume's local check ----
struct Case {
  const char* key;
  void (*make)(struct gdakiRsLocalIn&);
};
static const char* toldText = "every wait word raised: abort";
// gin-restore's 33 conditions in their order (impl/rs_unit_dev.cc's list; the texts are gin-restore's)
static const Case v1Cases[] = {
  {"NULL devComm", [](struct gdakiRsLocalIn& x) { x.argsOk = false; }},
  {"another NCCL version (23100)", [](struct gdakiRsLocalIn& x) { x.devCommVersion = 23100; }},
  {"a fault already reached", [](struct gdakiRsLocalIn& x) { x.told = toldText; }},
  {"spare process", [](struct gdakiRsLocalIn& x) { x.spare = true; }},
  {"no GIN connection", [](struct gdakiRsLocalIn& x) { x.nConn = 0; }},
  {"not GDAKI (type 2)", [](struct gdakiRsLocalIn& x) { x.ginType = 2; }},
  {"GIN connection is not FULL", [](struct gdakiRsLocalIn& x) { x.commFull = false; }},
  {"rank stride is 2", [](struct gdakiRsLocalIn& x) { x.ctxStride = 2; }},
  {"has 2 GIN connections", [](struct gdakiRsLocalIn& x) { x.nConn = 2; }},
  {"host RMA is on", [](struct gdakiRsLocalIn& x) { x.numRmaCtx = 1; }},
  {"runtime connect is off", [](struct gdakiRsLocalIn& x) { x.runtimeConn = false; }},
  {"NVLS is on", [](struct gdakiRsLocalIn& x) { x.nvls = true; }},
  {"LSA team has 2 ranks", [](struct gdakiRsLocalIn& x) { x.lsaSize = 2; }},
  {"symmetric kernels made their own GIN devComm", [](struct gdakiRsLocalIn& x) { x.symGinDevComm = true; }},
  {"transparent recovery is off for this devComm", [](struct gdakiRsLocalIn& x) { x.haveSetup = false; }},
  {"has 2 GDAKI contexts", [](struct gdakiRsLocalIn& x) { x.nUserCtx = 2; }},
  {"went off on this rank after the setup agreement (the helper", [](struct gdakiRsLocalIn& x) { x.tsOn = false; }},
  {"NCCL_GIN_TS_RECONNECT is not 1", [](struct gdakiRsLocalIn& x) { x.reconnect = 0; }},
  {"QP watch is off", [](struct gdakiRsLocalIn& x) { x.qpwatchMs = 0; }},
  {"NCCL_GIN_RESTORE_MS (30000) is not between 0 and NCCL_GIN_TS_HOLD_MS (30000)",
   [](struct gdakiRsLocalIn& x) { x.restoreMs = 30000; }},
  {"NIC copy path is off", [](struct gdakiRsLocalIn& x) { x.lbOn = false; }},
  {"side table is not set up on this rank (no memory)",
   [](struct gdakiRsLocalIn& x) { x.sideOk = false; x.sideWhy = "no memory"; }},
  {"restore buffers are not in the NIC copy path (unknown)", [](struct gdakiRsLocalIn& x) { x.rsLbOk = false; }},
  {"2 window(s) were registered after", [](struct gdakiRsLocalIn& x) { x.winsAfter = 2; }},
  {"1 window(s) of this context's restore buffers were deregistered", [](struct gdakiRsLocalIn& x) { x.winsGone = 1; }},
  {"resource window could not be added to the NIC copy path (list full)",
   [](struct gdakiRsLocalIn& x) { x.resOk = false; x.resWhy = "list full"; }},
  {"round cap stopped recovery", [](struct gdakiRsLocalIn& x) { x.escalated = true; }},
  {"measurement mode is on (NCCL_GIN_RESTORE_LOG_MEASURE)", [](struct gdakiRsLocalIn& x) { x.logMeasure = true; }},
  {"program not built with NCCL_GIN_RESTORE_DEVICE", [](struct gdakiRsLocalIn& x) { x.deviceBuilt = false; }},
  {"does not record its init transcript (NCCL_GIN_RESTORE_RECORD)", [](struct gdakiRsLocalIn& x) { x.transcriptOk = false; }},
  {"replay of the init transcript was not clean (unknown)", [](struct gdakiRsLocalIn& x) { x.replayClean = false; }},
  {"atomic capability is below IBV_ATOMIC_HCA (atomic_cap 0)", [](struct gdakiRsLocalIn& x) { x.atomicCap = 0; }},
  {"NIC atomics of the restore are not ready on this rank (x)",
   [](struct gdakiRsLocalIn& x) { x.atomicOk = false; x.atomicWhy = "x"; }},
};
static const int nV1 = (int)(sizeof(v1Cases) / sizeof(v1Cases[0]));
static struct gdakiRsLocalIn okIn() {
  struct gdakiRsLocalIn ok;
  ok.ginType = 3;
  ok.nConn = 1;
  ok.haveSetup = true;
  ok.nUserCtx = 1;
  ok.tsOn = true;
  return ok;
}
// every mirror fact set to its failing value (with miAsked as given)
static void badMirror(struct gdakiRsLocalIn& x, bool asked) {
  x.miAsked = asked;
  x.miAgreed = false;
  x.miCtxOk = false;
  x.miCtxWhy = "ctx";
  x.miPoolOk = false;
  x.miPoolWhy = "pool";
  x.miCsum = true;
  x.miConfOk = false;
  x.miConfWhy = "conf";
  x.miPeersOk = false;
  x.miPeersWhy = "peers";
  x.miSelfOk = false;
}
static void testLocalMirrorOff() {
  char why[GDAKI_RS_WHY_LEN], why2[GDAKI_RS_WHY_LEN];
  struct gdakiRsLocalIn ok = okIn();
  CHECK(gdakiRsLocalCheck(ok, why, sizeof(why)) == GDAKI_RS_L_OK && has(why, "can enable"));
  CHECK(nV1 == 33);
  for (int i = 0; i < nV1; i++) {
    struct gdakiRsLocalIn x = ok;
    v1Cases[i].make(x);
    const int code = gdakiRsLocalCheck(x, why, sizeof(why));
    CHECK(code == i + 1);
    CHECK(has(why, v1Cases[i].key));
    // the mirror off (not asked): its facts, all failing, change neither code nor text
    struct gdakiRsLocalIn y = x;
    badMirror(y, false);
    CHECK(gdakiRsLocalCheck(y, why2, sizeof(why2)) == code);
    CHECK(strcmp(why, why2) == 0);
  }
  struct gdakiRsLocalIn y = ok;
  badMirror(y, false);
  CHECK(gdakiRsLocalCheck(y, why, sizeof(why)) == GDAKI_RS_L_OK && has(why, "can enable"));
  // the mirror asked and every fact good: can enable
  y = ok;
  y.miAsked = true;
  CHECK(gdakiRsLocalCheck(y, why, sizeof(why)) == GDAKI_RS_L_OK);
  // a gin-restore condition comes before every mirror condition
  for (int i = 0; i < nV1; i++) {
    struct gdakiRsLocalIn x = ok;
    v1Cases[i].make(x);
    badMirror(x, true);
    CHECK(gdakiRsLocalCheck(x, why, sizeof(why)) == i + 1);
  }
}
static void testLocalMirrorOn() {
  char why[GDAKI_RS_WHY_LEN];
  struct gdakiRsLocalIn on = okIn();
  on.miAsked = true;
  struct MCase {
    int code;
    const char* text;
    const char* detail;
    void (*make)(struct gdakiRsLocalIn&);
  };
  static const MCase cases[] = {
    {34, GDAKI_MI_R34, nullptr, [](struct gdakiRsLocalIn& x) { x.miAgreed = false; }},
    {35, GDAKI_MI_R35, "(ibv_reg_mr_iova2 failed)",
     [](struct gdakiRsLocalIn& x) { x.miPoolOk = false; x.miPoolWhy = "ibv_reg_mr_iova2 failed"; }},
    {36, GDAKI_MI_R36, nullptr, [](struct gdakiRsLocalIn& x) { x.miCsum = true; }},
    {37, GDAKI_MI_R37, "(L 63 is not", [](struct gdakiRsLocalIn& x) { x.miConfOk = false; x.miConfWhy = "L 63 is not a positive multiple of 64"; }},
    {38, GDAKI_MI_R38, "(rank 2: no MIRROR_SETUP",
     [](struct gdakiRsLocalIn& x) { x.miPeersOk = false; x.miPeersWhy = "rank 2: no MIRROR_SETUP within"; }},
    {38, GDAKI_MI_R38, "(the self loop pair", [](struct gdakiRsLocalIn& x) { x.miSelfOk = false; }},
    {40, GDAKI_MI_R40, "(32 user GIN contexts",
     [](struct gdakiRsLocalIn& x) { x.miCtxOk = false; x.miCtxWhy = "32 user GIN contexts; at most 31"; }},
  };
  for (const auto& c : cases) {
    struct gdakiRsLocalIn x = on;
    c.make(x);
    CHECK(gdakiRsLocalCheck(x, why, sizeof(why)) == c.code);
    CHECK(startsWith(why, c.text));
    if (c.detail) CHECK(has(why, c.detail));
  }
  // precedence: no mirror context is 40's (35 and 38 not judged), a bad 37 is not 35's, 34 first of all
  {
    struct gdakiRsLocalIn x = on;
    x.miCtxOk = false;
    x.miPoolOk = false;
    x.miPeersOk = false;
    x.miSelfOk = false;
    CHECK(gdakiRsLocalCheck(x, why, sizeof(why)) == 40);
    x.miConfOk = false;
    CHECK(gdakiRsLocalCheck(x, why, sizeof(why)) == 37);
    x.miCsum = true;
    CHECK(gdakiRsLocalCheck(x, why, sizeof(why)) == 36);
    x.miAgreed = false;
    CHECK(gdakiRsLocalCheck(x, why, sizeof(why)) == 34);
  }
  {
    struct gdakiRsLocalIn x = on;
    x.miConfOk = false;
    x.miPoolOk = false;  // no pool because L is bad: 37
    CHECK(gdakiRsLocalCheck(x, why, sizeof(why)) == 37);
  }
  {
    struct gdakiRsLocalIn x = on;
    badMirror(x, true);
    CHECK(gdakiRsLocalCheck(x, why, sizeof(why)) == 34);
  }
  // the spare: 38's peers part is not checked (no MIRROR_SETUP there); its self loop is; the rest as any rank
  {
    struct gdakiRsLocalIn x = on;
    x.miSpare = true;
    x.miPeersOk = false;
    x.miPeersWhy = "never exchanged";
    CHECK(gdakiRsLocalCheck(x, why, sizeof(why)) == GDAKI_RS_L_OK);
    x.miSelfOk = false;
    CHECK(gdakiRsLocalCheck(x, why, sizeof(why)) == 38);
    x.miSelfOk = true;
    x.miPoolOk = false;
    CHECK(gdakiRsLocalCheck(x, why, sizeof(why)) == 35);
    x.miPoolOk = true;
    x.miAgreed = false;
    CHECK(gdakiRsLocalCheck(x, why, sizeof(why)) == 34);
  }
  // 39 is never local: no single-rank fact gives it
  {
    for (int mask = 0; mask < 256; mask++) {
      struct gdakiRsLocalIn x = on;
      if (mask & 1) x.miAgreed = false;
      if (mask & 2) x.miCtxOk = false;
      if (mask & 4) x.miPoolOk = false;
      if (mask & 8) x.miCsum = true;
      if (mask & 16) x.miConfOk = false;
      if (mask & 32) x.miPeersOk = false;
      if (mask & 64) x.miSelfOk = false;
      if (mask & 128) x.miSpare = true;
      const int code = gdakiRsLocalCheck(x, why, sizeof(why));
      CHECK(code == GDAKI_RS_L_OK || (code >= 34 && code <= 40 && code != 39));
    }
  }
}

// ---- 2. Resume's decision ----
static struct gdakiRsXRec xrec(int rank, int localCode, const char* localWhy, uint32_t miReq, uint32_t S, uint64_t L) {
  struct gdakiRsXRec r;
  memset(&r, 0, sizeof(r));
  r.magic = GDAKI_RS_X_MAGIC;
  r.rank = rank;
  r.req = 1;
  r.policy = GDAKI_POLICY_HOLD;
  r.setupVerdict = GDAKI_RS_ENABLE;
  snprintf(r.setupWhy, sizeof(r.setupWhy), "every rank asks for the restore and meets its conditions");
  r.localCode = localCode;
  snprintf(r.localWhy, sizeof(r.localWhy), "%s", localWhy);
  r.miReq = miReq;
  r.miSlots = miReq ? S : 0;
  r.miLane = miReq ? L : 0;
  return r;
}
static int decide(const std::vector<struct gdakiRsXRec>& x, std::string* why) {
  char w[GDAKI_RS_RWHY_LEN];
  const int v = gdakiRsResumeDecide((int)x.size(), x.data(), w, sizeof(w));
  *why = w;
  return v;
}
static void testDecide() {
  std::string why;
  for (int n : {2, 3, 4, 8}) {
    // the mirror off: gin-restore's verdicts and texts
    std::vector<struct gdakiRsXRec> x;
    for (int p = 0; p < n; p++) x.push_back(xrec(p, 0, "this rank can enable the restore", 0, 0, 0));
    CHECK(decide(x, &why) == GDAKI_RS_ENABLE && why == "every rank asks for the restore and can enable it");
    x[n - 1].localCode = 22;
    snprintf(x[n - 1].localWhy, sizeof(x[n - 1].localWhy), "the side table is not set up on this rank (x)");
    CHECK(decide(x, &why) == GDAKI_RS_REFUSE);
    CHECK(why == std::string("rank ") + std::to_string(n - 1) + ": the side table is not set up on this rank (x)");
    x[n - 1].localCode = 0;
    x[0].req = 0;
    x[0].policy = GDAKI_POLICY_FAILFAST;
    CHECK(decide(x, &why) == GDAKI_RS_REFUSE && has(why.c_str(), "the restore request differs"));
    x[0].req = 1;
    x[0].magic = 0x32535247u;  // a library without the mirror's record ("GRS2")
    CHECK(decide(x, &why) == GDAKI_RS_REFUSE && has(why.c_str(), "rank 0 sent no valid restore record"));
    x[0].magic = GDAKI_RS_X_MAGIC;
    // the mirror on everywhere, the same S and L: enabled
    std::vector<struct gdakiRsXRec> y;
    for (int p = 0; p < n; p++) y.push_back(xrec(p, 0, "this rank can enable the restore", 1, 3, 1 << 20));
    CHECK(decide(y, &why) == GDAKI_RS_ENABLE);
    // a rank whose bit differs: 34 at the lowest asking rank, naming the lowest one that does not ask
    for (int b = 0; b < n; b++) {
      std::vector<struct gdakiRsXRec> z = y;
      z[b].miReq = 0;
      z[b].miSlots = 0;
      z[b].miLane = 0;
      CHECK(decide(z, &why) == GDAKI_RS_REFUSE);
      const int a = b == 0 ? 1 : 0;
      CHECK(why == std::string("rank ") + std::to_string(a) + ": " + GDAKI_MI_R34 + " (rank " + std::to_string(b) +
                     " does not ask for it)");
    }
    // S or L differing: 39 at the lowest rank that differs from the lowest asking one
    for (int b = 1; b < n; b++) {
      std::vector<struct gdakiRsXRec> z = y;
      z[b].miSlots = 2;
      CHECK(decide(z, &why) == GDAKI_RS_REFUSE);
      CHECK(startsWith(why.c_str(), (std::string("rank ") + std::to_string(b) + ": " + GDAKI_MI_R39).c_str()));
      z = y;
      z[b].miLane = 2 << 20;
      CHECK(decide(z, &why) == GDAKI_RS_REFUSE && has(why.c_str(), GDAKI_MI_R39));
    }
    // a local refusal comes first
    {
      std::vector<struct gdakiRsXRec> z = y;
      z[n - 1].miSlots = 4;
      z[n - 1].localCode = 38;
      snprintf(z[n - 1].localWhy, sizeof(z[n - 1].localWhy), "%s (rank 0: x)", GDAKI_MI_R38);
      CHECK(decide(z, &why) == GDAKI_RS_REFUSE && has(why.c_str(), GDAKI_MI_R38) && !has(why.c_str(), GDAKI_MI_R39));
    }
    // every rank prints alike: the decision depends on the records only (a shuffled copy of the order of evaluation
    // is not possible: the function has no "self" argument); deciding twice gives the same text
    {
      std::vector<struct gdakiRsXRec> z = y;
      z[n / 2].miLane = 64;
      std::string w1, w2;
      decide(z, &w1);
      decide(z, &w2);
      CHECK(w1 == w2);
    }
  }
  // the spare: its own record is fresh (38's peers part skipped: can enable), the others recorded
  {
    char lw[GDAKI_RS_WHY_LEN];
    struct gdakiRsLocalIn sp = okIn();
    sp.miAsked = true;
    sp.miSpare = true;
    sp.miPeersOk = false;
    const int code = gdakiRsLocalCheck(sp, lw, sizeof(lw));
    CHECK(code == GDAKI_RS_L_OK);
    std::vector<struct gdakiRsXRec> z;
    for (int p = 0; p < 4; p++) z.push_back(xrec(p, 0, "this rank can enable the restore", 1, 3, 1 << 20));
    z[2] = xrec(2, code, lw, 1, 3, 1 << 20);
    CHECK(decide(z, &why) == GDAKI_RS_ENABLE);
  }
}

// ---- 3. the agreement, the parameters, MIRROR_SETUP ----
static void testSetup() {
  for (int n : {1, 2, 3, 4, 7}) {
    std::vector<uint32_t> pads((size_t)n, GDAKI_RS_REQ | GDAKI_RS_STRICT | GDAKI_MI_PAD_MIRROR);
    CHECK(gdakiMiAgreed(n, pads.data(), true) == (n >= 2));
    CHECK(!gdakiMiAgreed(n, pads.data(), false));
    if (n >= 2) {
      pads[(size_t)n - 1] &= ~GDAKI_MI_PAD_MIRROR;
      CHECK(!gdakiMiAgreed(n, pads.data(), true));
    }
  }
  // gin-restore's own decision ignores the mirror bit (the same verdict and text with or without it)
  {
    const int n = 4;
    std::vector<uint32_t> pol(n, GDAKI_POLICY_HOLD), a(n, GDAKI_RS_REQ | GDAKI_RS_STRICT), b(n);
    std::vector<uint8_t> on(n, 1);
    for (int i = 0; i < n; i++) b[(size_t)i] = a[(size_t)i] | GDAKI_MI_PAD_MIRROR;
    char w1[GDAKI_RS_WHY_LEN], w2[GDAKI_RS_WHY_LEN];
    CHECK(gdakiRsDecide(n, pol.data(), a.data(), on.data(), w1, sizeof(w1)) ==
          gdakiRsDecide(n, pol.data(), b.data(), on.data(), w2, sizeof(w2)));
    CHECK(strcmp(w1, w2) == 0);
    a[1] |= GDAKI_RS_SYMGIN;
    b[1] |= GDAKI_RS_SYMGIN;
    CHECK(gdakiRsDecide(n, pol.data(), a.data(), on.data(), w1, sizeof(w1)) == GDAKI_RS_REFUSE);
    CHECK(gdakiRsDecide(n, pol.data(), b.data(), on.data(), w2, sizeof(w2)) == GDAKI_RS_REFUSE && strcmp(w1, w2) == 0);
    CHECK((GDAKI_MI_PAD_MIRROR & (GDAKI_RS_REQ | GDAKI_RS_STRICT | GDAKI_RS_SPARE | GDAKI_RS_RECOFF | GDAKI_RS_GINTYPE |
                                  GDAKI_RS_RMA | GDAKI_RS_SYMGIN | GDAKI_RS_STRIDE)) == 0);
  }
  char why[128];
  uint64_t pb = 0;
  struct gdakiMiConf c;
  CHECK(gdakiMiConfOk(c, 1, 4, &pb, why, sizeof(why)) && pb == 3ull * 3 * (1 << 20));  // 9 MiB (EXPERIMENT.md 9.3)
  CHECK(gdakiMiConfOk(c, 2, 5, &pb, why, sizeof(why)) && pb == 2ull * 3 * 4 * (1 << 20));
  CHECK(gdakiMiConfOk(c, 0, 4, &pb, why, sizeof(why)) && pb == 0);
  c.lane = 80ll << 20;  // the training shape: 720 MiB with S 3, n 4
  CHECK(gdakiMiConfOk(c, 1, 4, &pb, why, sizeof(why)) && pb == 720ull << 20);
  c.poolMaxMb = 720;
  CHECK(gdakiMiConfOk(c, 1, 4, &pb, why, sizeof(why)));
  c.poolMaxMb = 719;
  CHECK(!gdakiMiConfOk(c, 1, 4, &pb, why, sizeof(why)) && has(why, "above 719 MiB") && pb == 0);
  c = gdakiMiConf();
  for (int64_t L : {0ll, -64ll, 1ll, 63ll, 65ll, 100ll}) {
    c.lane = L;
    CHECK(!gdakiMiConfOk(c, 1, 4, &pb, why, sizeof(why)) && has(why, "positive multiple of 64"));
  }
  c.lane = 64;
  CHECK(gdakiMiConfOk(c, 1, 4, &pb, why, sizeof(why)));
  for (int64_t S : {-1ll, 0ll, 1ll, 5ll, 9ll}) {
    c.slots = S;
    CHECK(!gdakiMiConfOk(c, 1, 4, &pb, why, sizeof(why)) && has(why, "is not 2..4"));
  }
  for (int64_t S : {2ll, 3ll, 4ll}) {
    c.slots = S;
    CHECK(gdakiMiConfOk(c, 1, 4, &pb, why, sizeof(why)));
  }
  c = gdakiMiConf();
  c.lane = 1ll << 60;  // overflow-safe
  CHECK(!gdakiMiConfOk(c, 2, 64, &pb, why, sizeof(why)));
  c = gdakiMiConf();
  c.poolMaxMb = 0;
  CHECK(!gdakiMiConfOk(c, 1, 4, &pb, why, sizeof(why)) && gdakiMiConfOk(c, 0, 4, &pb, why, sizeof(why)));
  // MIRROR_SETUP's check
  struct gdakiMiSetup s;
  memset(&s, 0, sizeof(s));
  s.version = GDAKI_MI_WIRE_VERSION;
  s.on = 1;
  s.qpn = 0x1234;
  CHECK(gdakiMiSetupRecCheck(GDAKI_TS_MI_SETUP, 3, 3, 77, 3, 77, s) == GDAKI_MI_SR_OK);
  CHECK(gdakiMiSetupRecCheck(GDAKI_TS_CKPT_PULL, 3, 3, 77, 3, 77, s) == GDAKI_MI_SR_TYPE);
  CHECK(gdakiMiSetupRecCheck(GDAKI_TS_MI_SETUP, 2, 3, 77, 3, 77, s) == GDAKI_MI_SR_FROM);
  CHECK(gdakiMiSetupRecCheck(GDAKI_TS_MI_SETUP, 3, 2, 77, 3, 77, s) == GDAKI_MI_SR_FROM);
  CHECK(gdakiMiSetupRecCheck(GDAKI_TS_MI_SETUP, 3, 3, 78, 3, 77, s) == GDAKI_MI_SR_FROM);
  s.version = 2;
  CHECK(gdakiMiSetupRecCheck(GDAKI_TS_MI_SETUP, 3, 3, 77, 3, 77, s) == GDAKI_MI_SR_VERSION);
  s.version = GDAKI_MI_WIRE_VERSION;
  s.on = 0;
  CHECK(gdakiMiSetupRecCheck(GDAKI_TS_MI_SETUP, 3, 3, 77, 3, 77, s) == GDAKI_MI_SR_OFF);
  s.on = 1;
  s.qpn = 0;
  CHECK(gdakiMiSetupRecCheck(GDAKI_TS_MI_SETUP, 3, 3, 77, 3, 77, s) == GDAKI_MI_SR_QPN);
  s.qpn = 0x1000000;
  CHECK(gdakiMiSetupRecCheck(GDAKI_TS_MI_SETUP, 3, 3, 77, 3, 77, s) == GDAKI_MI_SR_QPN);
  for (int k = 0; k <= 5; k++) CHECK(strcmp(gdakiMiSetupRecWhy(k), "?") != 0);
  CHECK(sizeof(struct gdakiMiSetup) <= sizeof(uint32_t) * 64);  // gdakiTsMsg::executed
}

// ---- 4. segments ----
static const uint64_t kL = 1 << 20;
static void testSegmentsBasic() {
  struct gdakiMiSegs s;
  bool restart = false;
  CHECK(!s.hasOpen() && s.lastSeg == 0);
  // the first switch (the cell was never valid: cursor 0, broken 0): no closed segment, the open one is 1
  CHECK(gdakiMiSegsSwitch(s, 20, 1000, 0, 0, 3, kL, &restart) == 1 && !restart);
  CHECK(s.live.size() == 1 && s.hasOpen() && s.live[0].start == 1000 && s.live[0].closedAt == GDAKI_MI_OPEN);
  // checkpoint 40: segment 1 closes at head 2000 with its fill, 2 opens
  CHECK(gdakiMiSegsSwitch(s, 40, 2000, 4096 + 64, 0, 3, kL, &restart) == 2 && !restart);
  CHECK(s.live.size() == 2 && s.live[0].seg == 1 && s.live[0].cut == 2000 && s.live[0].fill == 4160 &&
        s.live[0].closedAt == 40 && s.live[0].broken == 0 && s.live[1].seg == 2 && s.live[1].start == 2000);
  // CKPT_STABLE(40): segment 1 goes
  CHECK(gdakiMiSegsStable(s, 40) == 1 && s.live.size() == 1 && s.live[0].seg == 2);
  // a late stable: 60 and 80 close 2 and 3 (third slot), stable(60) drops only 2
  CHECK(gdakiMiSegsSwitch(s, 60, 3000, kL + 4096, 2, 3, kL, &restart) == 3 && !restart);  // cursor past L: fill L
  CHECK(s.live[0].fill == kL && s.live[0].broken == 2);
  CHECK(gdakiMiSegsSwitch(s, 80, 4000, 128, 2, 3, kL, &restart) == 4 && !restart && s.live.size() == 3);
  CHECK(gdakiMiSegsStable(s, 60) == 1 && s.live.size() == 2 && s.live[0].seg == 3);
  CHECK(gdakiMiSegsStable(s, 79) == 0);  // nothing closed at or below 79 remains
  // two voided checkpoints (100, 120): three live, then the fourth would be needed: restart
  CHECK(gdakiMiSegsSwitch(s, 100, 5000, 0, 2, 3, kL, &restart) == 5 && !restart && s.live.size() == 3);
  CHECK(gdakiMiSegsSwitch(s, 120, 6000, 64, 2, 3, kL, &restart) == 6 && restart);
  CHECK(s.live.size() == 1 && s.live[0].seg == 6 && s.live[0].start == 6000 && s.hasOpen());
  // host breaks and a counter that went back count in the closed segment
  s.hostBreaks = 2;
  CHECK(gdakiMiSegsSwitch(s, 140, 7000, 64, 7, 3, kL, &restart) == 7);
  CHECK(s.live[0].broken == 5 + 2 && s.hostBreaks == 0);
  CHECK(gdakiMiSegsSwitch(s, 160, 8000, 64, 3, 3, kL, &restart) == 8);  // 3 < 7: went back
  CHECK(s.live[1].broken == 1);
  // INJECTED: every closed one goes, the open one stays
  CHECK(gdakiMiSegsDropClosed(s) == 2 && s.live.size() == 1 && s.live[0].seg == 8 && s.hasOpen());
  // a new pool of the buddy: every one goes, the numbers go on
  gdakiMiSegsDropAll(s);
  CHECK(s.live.empty() && !s.hasOpen() && s.lastSeg == 8);
  CHECK(gdakiMiSegsSwitch(s, 180, 9000, 0, 3, 3, kL, &restart) == 9 && !restart && s.live.size() == 1);
  // S 2: the restart comes one slot earlier
  struct gdakiMiSegs t;
  CHECK(gdakiMiSegsSwitch(t, 1, 10, 0, 0, 2, kL, &restart) == 1 && !restart);
  CHECK(gdakiMiSegsSwitch(t, 2, 20, 0, 0, 2, kL, &restart) == 2 && !restart && t.live.size() == 2);
  CHECK(gdakiMiSegsSwitch(t, 3, 30, 0, 0, 2, kL, &restart) == 3 && restart && t.live.size() == 1);
  // the rollback: a copy taken before the switch, restored exactly
  struct gdakiMiSegs u = s, before = s;
  gdakiMiSegsSwitch(u, 200, 9500, 4096, 3, 3, kL, &restart);
  CHECK(u.live.size() == 2);
  u = before;
  CHECK(u.live.size() == before.live.size() && u.lastSeg == before.lastSeg && u.live[0].closedAt == GDAKI_MI_OPEN);
  // the switch verdict of the header
  for (uint32_t S = 2; S <= 4; S++)
    for (uint32_t live = 0; live <= 6; live++)
      CHECK((gdakiMiSwitchVerdict(live, S) == GDAKI_MI_SW_RESTART) == (live + 1 > S));
}
static void testSegmentsView() {
  struct gdakiMiSegs s;
  bool restart = false;
  struct gdakiMiSegView v;
  CHECK(!gdakiMiSegsViewOf(s, false, 0, &v) && v.openSeg == 0 && v.cuts.empty());
  gdakiMiSegsSwitch(s, 20, 100, 0, 5, 3, kL, &restart);   // seg 1 from 100
  gdakiMiSegsSwitch(s, 40, 200, 640, 5, 3, kL, &restart);  // seg 1 closed at 200, seg 2 from 200
  gdakiMiSegsSwitch(s, 60, 300, 128, 6, 3, kL, &restart);  // seg 2 closed at 300 (1 break), seg 3 from 300
  CHECK(gdakiMiSegsViewOf(s, true, 4096, &v));
  CHECK(v.cuts.size() == 2 && v.cuts[0] == 200 && v.cuts[1] == 300 && v.segs[0] == 1 && v.segs[1] == 2);
  CHECK(v.fills[0] == 640 && v.fills[1] == 128 && v.closedAt[0] == 40 && v.closedAt[1] == 60);
  CHECK(v.broken[0] == 0 && v.broken[1] == 1);
  CHECK(v.openSeg == 3 && v.openCursor == 4096 && v.openBroken == 6 && v.floor == 100 && v.cellValid);
  // the segment of an entry by its ring position (impl/rs_mirror_api.h gdakiMiSegOfPos)
  const int nc = (int)v.cuts.size();
  CHECK(gdakiMiSegOfPos(v.cuts.data(), v.segs.data(), nc, v.openSeg, v.floor, 99) == 0);
  CHECK(gdakiMiSegOfPos(v.cuts.data(), v.segs.data(), nc, v.openSeg, v.floor, 100) == 1);
  CHECK(gdakiMiSegOfPos(v.cuts.data(), v.segs.data(), nc, v.openSeg, v.floor, 199) == 1);
  CHECK(gdakiMiSegOfPos(v.cuts.data(), v.segs.data(), nc, v.openSeg, v.floor, 200) == 2);
  CHECK(gdakiMiSegOfPos(v.cuts.data(), v.segs.data(), nc, v.openSeg, v.floor, 299) == 2);
  CHECK(gdakiMiSegOfPos(v.cuts.data(), v.segs.data(), nc, v.openSeg, v.floor, 300) == 3);
  CHECK(gdakiMiSegOfPos(v.cuts.data(), v.segs.data(), nc, v.openSeg, v.floor, 1u << 30) == 3);
  // after CKPT_STABLE(40) the floor moves to segment 2's start: an entry below it is refused (segment 0)
  gdakiMiSegsStable(s, 40);
  CHECK(gdakiMiSegsViewOf(s, false, 0, &v) && v.floor == 200 && v.cuts.size() == 1 && !v.cellValid);
  CHECK(gdakiMiSegOfPos(v.cuts.data(), v.segs.data(), 1, v.openSeg, v.floor, 150) == 0);
  CHECK(gdakiMiSegsLiveBytes(s, 4096, kL) == 128 + 4096);
  CHECK(gdakiMiSegsLiveBytes(s, kL * 2, kL) == 128 + kL);
}
// A random model of one (sender, destination) pair over many pauses: switches with a random outcome (confirmed, voided,
// rolled back), stables, INJECTED, a new pool. Live segments never exceed S, their numbers are consecutive, their slots
// (seg mod S) distinct, their lanes in the pool disjoint, and a rollback restores the copy exactly.
static void testSegmentsModel() {
  std::mt19937 rng(20261013);
  long switches = 0, restarts = 0, rollbacks = 0, thirds = 0;
  for (int run = 0; run < 400; run++) {
    const uint64_t S = 2 + run % 3;
    const int n = 2 + run % 7;
    int d = (int)(rng() % (uint32_t)n), me = (int)(rng() % (uint32_t)n);
    if (me == d) me = (d + 1) % n;
    const int wardIdx = ncclGinMiWardIdx(d, n), lane = ncclGinMiLaneOf(me, d);
    CHECK(wardIdx >= 0 && wardIdx <= 1 && lane >= 0 && lane < n - 1);
    struct gdakiMiSegs s;
    uint64_t ckpt = 0, head = 0, broken = 0;
    std::vector<uint64_t> unstable;  // checkpoints closed and not yet stable (or voided)
    for (int step = 0; step < 300; step++) {
      const int ev = (int)(rng() % 10);
      if (ev < 6) {  // a pause: the switch
        ckpt += 20;
        head += 1 + rng() % 1000;
        if (rng() % 7 == 0) broken++;
        const struct gdakiMiSegs copy = s;
        bool restart = false;
        const uint64_t seg = gdakiMiSegsSwitch(s, ckpt, head, rng() % (2 * kL), broken, S, kL, &restart);
        switches++;
        restarts += restart;
        CHECK(seg == copy.lastSeg + 1 && s.lastSeg == seg && s.hasOpen() && s.live.back().seg == seg);
        CHECK(restart == (copy.live.size() + 1 > S));
        if (s.live.size() == 3) thirds++;
        if (rng() % 4 == 0) {  // given up before its own publish: rolled back (the checkpoint's number stays used)
          s = copy;
          rollbacks++;
          CHECK(s.lastSeg == copy.lastSeg && s.live.size() == copy.live.size());
        } else {
          unstable.push_back(ckpt);  // its end published; its CKPT_STABLE comes later, or never (voided)
        }
      } else if (ev < 8) {  // CKPT_STABLE of one of them (the earlier ones were voided)
        if (!unstable.empty()) {
          const size_t k = rng() % unstable.size();
          const uint64_t sk = unstable[k];
          gdakiMiSegsStable(s, sk);
          unstable.erase(unstable.begin(), unstable.begin() + (long)k + 1);
          for (const auto& g : s.live) CHECK(g.closedAt == GDAKI_MI_OPEN || g.closedAt > sk);
        }
      } else if (ev == 8) {
        if (rng() % 5 == 0) {
          gdakiMiSegsDropClosed(s);  // INJECTED of d
          CHECK(s.live.size() <= 1);
        }
      } else if (rng() % 9 == 0) {
        gdakiMiSegsDropAll(s);  // d's buddy restored
        CHECK(s.live.empty());
      }
      // invariants
      CHECK(s.live.size() <= S);
      for (size_t i = 0; i + 1 < s.live.size(); i++) {
        CHECK(s.live[i].seg + 1 == s.live[i + 1].seg);
        CHECK(s.live[i].closedAt != GDAKI_MI_OPEN);
        CHECK(s.live[i].cut == s.live[i + 1].start);  // closed at the head the next one opened at
        if (s.live[i + 1].closedAt != GDAKI_MI_OPEN) CHECK(s.live[i].closedAt < s.live[i + 1].closedAt);
      }
      std::vector<uint64_t> offs;
      for (const auto& g : s.live) offs.push_back(ncclGinMiLaneOff(wardIdx, g.seg % S, lane, n, S, kL));
      std::sort(offs.begin(), offs.end());
      for (size_t i = 0; i + 1 < offs.size(); i++) CHECK(offs[i] + kL <= offs[i + 1]);
      int ww[2];
      const int nw = ncclGinMiWardsOf(ncclGinMiBuddyOf(d, n), n, ww);
      for (uint64_t o : offs) CHECK(o + kL <= ncclGinMiPoolBytes(nw, S, n, kL));
    }
  }
  CHECK(switches > 50000 && restarts > 0 && rollbacks > 0 && thirds > 0);
}

// ---- 5. the poll ----
static void testPoll() {
  struct gdakiMiPollMem m;
  bool dis = false, pull = false;
  uint32_t pct = 0;
  gdakiMiPollBase(m, 5);  // the first switch's baseline
  gdakiMiPollBase(m, 9);  // only once
  CHECK(m.seen && m.broken == 5);
  gdakiMiPollStep(m, 1, 0, 5, kL, 50, &dis, &pull, &pct);
  CHECK(!dis && !pull && pct == 0);
  gdakiMiPollStep(m, 1, kL / 4, 6, kL, 50, &dis, &pull, &pct);  // a break: DISARM
  CHECK(dis && !pull && pct == 25);
  gdakiMiPollStep(m, 1, kL / 4, 8, kL, 50, &dis, &pull, &pct);  // still breaking: the same burst
  CHECK(!dis);
  gdakiMiPollStep(m, 1, kL / 2, 8, kL, 50, &dis, &pull, &pct);  // quiet: the burst ends; 50%: the pull
  CHECK(!dis && pull && pct == 50);
  gdakiMiPollStep(m, 1, kL, 8, kL, 50, &dis, &pull, &pct);  // the pull went out for segment 1 already
  CHECK(!dis && !pull && pct == 100);
  gdakiMiPollStep(m, 1, kL, 9, kL, 50, &dis, &pull, &pct);  // a new burst
  CHECK(dis);
  gdakiMiPollStep(m, 2, 0, 10, kL, 50, &dis, &pull, &pct);  // still breaking but a new segment: DISARM again
  CHECK(dis && !pull);
  gdakiMiPollStep(m, 2, kL * 3 / 4, 10, kL, 50, &dis, &pull, &pct);
  CHECK(!dis && pull && pct == 75);
  gdakiMiPollStep(m, 3, kL, 10, kL, 0, &dis, &pull, &pct);  // pull 0: never
  CHECK(!pull);
  gdakiMiPollStep(m, 3, kL * 2, 3, kL, 50, &dis, &pull, &pct);  // a counter that went back: a break; past L: 100%
  CHECK(dis && pull && pct == 100);
  // a cell never valid does not move: nothing
  struct gdakiMiPollMem q;
  for (int i = 0; i < 10; i++) {
    gdakiMiPollStep(q, 0, 0, 0, kL, 50, &dis, &pull, &pct);
    CHECK(!dis && !pull);
  }
}

// ---- 6. the absorption's decision ----
static void testAbsorb() {
  for (int n = 2; n <= 9; n++) {
    for (int miCtx : {1, 2, 4, 31}) {
      for (int qp = 0; qp < (miCtx + 1) * n; qp++) {
        CHECK(gdakiMiIsMirrorQp(true, qp, n, miCtx) == (qp / n == miCtx));
        CHECK(!gdakiMiIsMirrorQp(false, qp, n, miCtx));  // the mirror off: gin-restore's routes
      }
      for (int ctx = 0; ctx <= miCtx; ctx++) {
        CHECK(gdakiMiIsMirrorCtx(true, ctx, miCtx) == (ctx == miCtx));
        CHECK(!gdakiMiIsMirrorCtx(false, ctx, miCtx));
      }
    }
    CHECK(!gdakiMiIsMirrorQp(true, 0, n, -1) && !gdakiMiIsMirrorQp(true, -1, n, 1) && !gdakiMiIsMirrorQp(true, 5, 0, 1));
    for (int me = 0; me < n; me++)
      for (int b = 0; b < n; b++) {
        int t[2] = {-1, -1};
        const int k = gdakiMiServedBy(b, me, n, t);
        int w[2];
        const int kw = ncclGinMiWardsOf(b, n, w);
        CHECK(k == kw - ((kw > 0 && (w[0] == me || (kw > 1 && w[1] == me))) ? 1 : 0));
        for (int i = 0; i < k; i++) {
          CHECK(t[i] != me && ncclGinMiBuddyOf(t[i], n) == b);
        }
        // every destination d != me whose buddy is b is served: its lanes break when the QP to b is given up
        int expect = 0;
        for (int d = 0; d < n; d++)
          if (d != me && ncclGinMiBuddyOf(d, n) == b) expect++;
        CHECK(k == expect);
      }
  }
  CHECK(gdakiMiUserScopeOf(false, 1) == 0xffffffffu && gdakiMiUserScopeOf(true, -1) == 0xffffffffu);
  CHECK(gdakiMiUserScopeOf(true, 1) == 0xfffffffdu && gdakiMiUserScopeOf(true, 31) == 0x7fffffffu);
  CHECK(gdakiMiUserScopeOf(true, 32) == 0xffffffffu);  // no such bit: the context count above GDAKI_MI_MAX_USER_CTX
  CHECK(GDAKI_MI_MAX_USER_CTX == 31);
}

// ---- 7. PUBLISHED and INJECTED ----
static const uint32_t kStates[] = {GDAKI_HOLD_OFF,       GDAKI_HOLD_ARMED,         GDAKI_HOLD_HELD,
                                   GDAKI_HOLD_COMMITTING, GDAKI_HOLD_PUBLISHED,    GDAKI_HOLD_TIMED_OUT_HELD,
                                   GDAKI_HOLD_TIMED_OUT_PUBLISHED, GDAKI_HOLD_FALLBACK, GDAKI_HOLD_CANCELLED};
static void testDeadline() {
  std::mt19937 rng(7);
  for (int i = 0; i < 20000; i++) {
    const int64_t gateOdd = (int64_t)(1000000 + rng() % 1000000) * 1000;  // CLOCK_MONOTONIC us: well above 0
    const int64_t holdMs = 1000 + rng() % 60000, roundMs = 100 + rng() % 30000, hsMs = 100 + rng() % 5000;
    const int64_t shareMs = std::min<int64_t>(roundMs / 2, 4 * 2000);
    const int64_t D = gdakiHoldDeviceBoundUs(gateOdd, holdMs, shareMs, 1000);
    const int64_t publish = gateOdd + (int64_t)(rng() % 2000000);
    const int64_t rejoin = rng() % 2 ? publish - 1000 : 0;
    const int64_t v1 = gdakiHoldPublishedDeadlineUs(publish, 20000, roundMs, hsMs, rejoin, holdMs);
    // the mirror off (gates even at the publish): v1 unchanged
    CHECK(gdakiMiPublishedDeadlineUs(false, v1, D) == v1);
    // kept odd: never past the device bound, never later than v1
    const int64_t m = gdakiMiPublishedDeadlineUs(true, v1, D);
    CHECK(m == std::min(v1, D) && m <= D && m <= v1);
    CHECK(gdakiMiPublishedDeadlineUs(true, v1, 0) == v1);  // a bound not known
    CHECK(gdakiMiPublishedDeadlineUs(true, v1, -5) == v1);
  }
}
static void testInjectedVerdict() {
  const uint32_t W = 1;  // GDAKI_RS_WIRE_VERSION
  for (uint32_t s : kStates)
    for (uint32_t inc : {0u, 1u, 5u})
      for (uint32_t pad : {0u, inc, inc + 1u, inc + 2u})
        for (uint32_t rp : {0u, inc + 1u, inc + 2u}) {
          const int v = gdakiMiInjectedCheck(true, 3, 3, W, W, pad, pad, s, inc, rp);
          const bool published = s == GDAKI_HOLD_PUBLISHED || s == GDAKI_HOLD_TIMED_OUT_PUBLISHED;
          const bool apply = published && pad == inc + 1u && rp == pad && pad != 0;
          CHECK((v == GDAKI_MI_INJ_APPLY) == apply);
          if (!apply && pad != 0) {
            if (published && pad == inc + 1u) CHECK(v == GDAKI_MI_INJ_NO_RESTORED);
            else CHECK(v == GDAKI_MI_INJ_STATE);
          }
          // the mirror off: never applied (no INJECTED exists there)
          CHECK(gdakiMiInjectedCheck(false, 3, 3, W, W, pad, pad, s, inc, rp) == GDAKI_MI_INJ_OFF);
        }
  // malformed: another sender in arg, another wire version, its own incarnation not the pad
  CHECK(gdakiMiInjectedCheck(true, 3, 2, W, W, 2, 2, GDAKI_HOLD_PUBLISHED, 1, 2) == GDAKI_MI_INJ_FORMAT);
  CHECK(gdakiMiInjectedCheck(true, 3, 3, 2, W, 2, 2, GDAKI_HOLD_PUBLISHED, 1, 2) == GDAKI_MI_INJ_FORMAT);
  CHECK(gdakiMiInjectedCheck(true, 3, 3, W, W, 3, 2, GDAKI_HOLD_PUBLISHED, 1, 2) == GDAKI_MI_INJ_FORMAT);
  CHECK(gdakiMiInjectedCheck(true, 3, 3, W, W, 2, 2, GDAKI_HOLD_PUBLISHED, 1, 2) == GDAKI_MI_INJ_APPLY);
  for (int c = 0; c <= 4; c++) CHECK(strcmp(gdakiMiInjectedWhy(c), "?") != 0);
}
// The survivor's paths on its cell, with the host code's moves: RESTORED taken moves nothing (mirror on), the watcher's
// deadline (state only), INJECTED read first wins; INJECTED before RESTORED is ignored; mirror off: RESTORED moves.
static void testInjectedPaths() {
  const uint32_t W = 1;
  // the state INJECTED (mirror on) and RESTORED (mirror off) move to: the host code's gdakiHoldRestoredState (a restored
  // rank's new spare is never registered at its RESTORED in gin-restore: OFF, armed again at its next stable checkpoint)
  const uint32_t ns = gdakiHoldRestoredState(true, false, false);
  CHECK(ns == GDAKI_HOLD_OFF);
  for (int path = 0; path < 6; path++) {
    // 0 in time; 1 RESTORED, the watcher's timeout, INJECTED read first; 2 RESTORED, timeout, the helper's fallback first;
    // 3 INJECTED before RESTORED; 4 the timeout before RESTORED, then RESTORED and INJECTED; 5 the mirror off
    struct gdakiHoldCell c;
    const uint32_t i = 2;
    c.v.store(gdakiHoldPack(GDAKI_HOLD_HELD, i));
    CHECK(gdakiHoldCommitMove(c));
    CHECK(gdakiHoldPublishMove(c, 1000));
    uint32_t restoredPad = 0, from = 0, inc = 0;
    auto takeRestored = [&](bool mirror) {  // gdakiHoldApplyRestored's first check, then the mirror's bookkeeping
      struct gdakiHoldMsgIn in;
      in.restored = true;
      in.state = gdakiHoldStateOf(gdakiHoldLoad(c));
      in.inc = gdakiHoldIncOf(gdakiHoldLoad(c));
      in.msgInc = i + 1;
      CHECK(gdakiHoldMsgAction(in) == GDAKI_HOLD_M_RESTORED);
      if (mirror) restoredPad = i + 1;  // no move
      else CHECK(gdakiHoldRestoreMove(c, i + 1, ns, &from, &inc));
    };
    auto injected = [&]() {
      const uint64_t v = gdakiHoldLoad(c);
      return gdakiMiInjectedCheck(path != 5, 3, 3, W, W, i + 1, i + 1, gdakiHoldStateOf(v), gdakiHoldIncOf(v), restoredPad);
    };
    if (path == 5) {
      takeRestored(false);
      CHECK(gdakiHoldLoad(c) == gdakiHoldPack(ns, i + 1));
      CHECK(injected() == GDAKI_MI_INJ_OFF);
      continue;
    }
    if (path == 4) CHECK(gdakiHoldWatchMove(c, 2000, &inc) == GDAKI_HOLD_W_TIMEOUT_PUBLISHED);
    if (path == 3) {
      CHECK(injected() == GDAKI_MI_INJ_NO_RESTORED);  // ignored: the state stays
      CHECK(gdakiHoldStateOf(gdakiHoldLoad(c)) == GDAKI_HOLD_PUBLISHED);
      continue;
    }
    takeRestored(true);
    CHECK(gdakiHoldIncOf(gdakiHoldLoad(c)) == i);  // RESTORED moved nothing
    CHECK(gdakiHoldStateOf(gdakiHoldLoad(c)) == (path == 4 ? GDAKI_HOLD_TIMED_OUT_PUBLISHED : GDAKI_HOLD_PUBLISHED));
    if (path == 1 || path == 2) CHECK(gdakiHoldWatchMove(c, 2000, &inc) == GDAKI_HOLD_W_TIMEOUT_PUBLISHED);
    if (path == 2) {
      uint32_t f = 0, fi = 0;
      CHECK(gdakiHoldEndMove(c, GDAKI_HOLD_FALLBACK, &f, &fi) && f == GDAKI_HOLD_TIMED_OUT_PUBLISHED);
      CHECK(injected() == GDAKI_MI_INJ_STATE);
      continue;
    }
    CHECK(injected() == GDAKI_MI_INJ_APPLY);  // in time, or read before the timed-out publish fell back
    CHECK(gdakiHoldRestoreMove(c, i + 1, ns, &from, &inc));
    CHECK(gdakiHoldLoad(c) == gdakiHoldPack(ns, i + 1) && inc == i);
    CHECK(from == (path == 0 ? GDAKI_HOLD_PUBLISHED : GDAKI_HOLD_TIMED_OUT_PUBLISHED));
    CHECK(injected() == GDAKI_MI_INJ_STATE);  // a second (or stale) INJECTED is ignored
  }
}

// ---- 9. the review's points: the ledger with a modelled cell, MIRROR_SETUP's symmetry, the publish word, a stale
// record, the pull's consumption, INJECTED's resends ----
static bool same40(const struct ncclGinMiCell& a, const struct ncclGinMiCell& b) {
  return memcmp(&a, &b, offsetof(struct ncclGinMiCell, broken)) == 0;
}
static void testLedgerModel() {
  std::mt19937 rng(41);
  long rollbacks = 0, breaksInPause = 0, failedSwitches = 0;
  for (int run = 0; run < 300; run++) {
    const uint64_t S = 2 + run % 3, L = 4096;
    const int n = 2 + run % 6;
    const int d = 1 % n, me = 0;
    const int wardIdx = ncclGinMiWardIdx(d, n), lane = ncclGinMiLaneOf(me, d);
    struct gdakiMiLedger x;
    struct ncclGinMiCell dev;  // the device's cell
    memset(&dev, 0, sizeof(dev));
    uint64_t ckpt = 0, head = 0;
    bool inPause = false;
    struct ncclGinMiCell preCell;
    struct gdakiMiSegs preSegs;
    bool preValid = false;
    uint32_t breaksThisPause = 0, preHostBreaks = 0;
    std::vector<uint64_t> stableSince;  // CKPT_STABLEs applied during the pause
    for (int step = 0; step < 400; step++) {
      const int ev = (int)(rng() % 12);
      if (!inPause && ev < 4) {  // the device between pauses: puts into the open segment, breaks
        if (dev.valid) dev.cursor += 64 * (1 + rng() % 8);
        if (rng() % 9 == 0) dev.broken++;
      } else if (!inPause && ev < 7) {  // a pause starts: the switch
        ckpt += 20;
        head += 1 + rng() % 100;
        preCell = dev;
        preSegs = x.segs;
        preValid = x.cellValid;
        preHostBreaks = x.segs.hostBreaks;
        breaksThisPause = 0;
        stableSince.clear();
        bool restart = false;
        struct ncclGinMiCell w;
        const bool want = rng() % 5 != 0;
        const uint64_t seg = gdakiMiLedgerSwitch(x, dev, ckpt, head, want, 0x11223344u, wardIdx, lane, n, S, L, &restart, &w);
        CHECK(seg == preSegs.lastSeg + 1 && w.seg == seg && w.cursor == 0 && w.laneBytes == L && w.rkeyBe == 0x11223344u);
        CHECK(w.laneBase == ncclGinMiLaneOff(wardIdx, seg % S, lane, n, S, L) && w.valid == (want ? 1u : 0u));
        CHECK(w.broken == dev.broken);  // the switch never writes broken (the device's counter)
        const bool ok = rng() % 7 != 0;
        if (ok) memcpy(&dev, &w, offsetof(struct ncclGinMiCell, broken));
        else {
          dev.valid = 0;  // the host's fallback write of `valid` alone
          failedSwitches++;
        }
        gdakiMiLedgerSwitchWritten(x, w, ok);
        if (!ok) breaksThisPause++;
        inPause = true;
      } else if (inPause && ev < 6) {  // during the pause: a host break (a mirror QP given up), or a CKPT_STABLE
        if (rng() % 2) {
          gdakiMiLedgerHostBreak(x);
          dev.valid = 0;
          breaksThisPause++;
          breaksInPause++;
        } else if (!x.segs.live.empty()) {
          const uint64_t k = ckpt - 20 * (rng() % 3);
          gdakiMiLedgerStable(x, k);
          stableSince.push_back(k);
        }
      } else if (inPause) {  // the pause ends
        const bool rollback = rng() % 3 == 0;
        CHECK(x.pend && x.pendCkpt == ckpt);
        const bool write = gdakiMiLedgerPauseEnd(x, ckpt, rollback);
        CHECK(write == rollback && !x.pend);
        CHECK(!gdakiMiLedgerPauseEnd(x, ckpt, rollback));  // once
        if (write) {
          const bool ok = rng() % 6 != 0;
          if (ok) memcpy(&dev, &x.pendCell, offsetof(struct ncclGinMiCell, broken));
          else dev.valid = 0;
          gdakiMiLedgerRolledBack(x, ok);
          if (ok) {
            rollbacks++;
            // the cell is the one before the switch, but invalid when the host saw a break meanwhile
            struct ncclGinMiCell expect = preCell;
            if (breaksThisPause > 0) expect.valid = 0;
            CHECK(same40(dev, expect));
            CHECK(x.cellValid == (preValid && breaksThisPause == 0));
            CHECK(x.segs.lastSeg == preSegs.lastSeg && x.segs.hostBreaks == preHostBreaks + breaksThisPause);
            // the segments are the ones before, without those a CKPT_STABLE of the pause dropped
            struct gdakiMiSegs e = preSegs;
            for (uint64_t k : stableSince) gdakiMiSegsStable(e, k);
            CHECK(e.live.size() == x.segs.live.size());
            for (size_t q = 0; q < e.live.size() && q < x.segs.live.size(); q++)
              CHECK(e.live[q].seg == x.segs.live[q].seg && e.live[q].closedAt == x.segs.live[q].closedAt);
          } else {
            CHECK(!x.cellValid && x.segs.hostBreaks >= 1);
          }
        }
        inPause = false;
      } else if (ev == 7 && !inPause) {
        gdakiMiLedgerHostBreak(x);  // a break outside a pause
        dev.valid = 0;
      } else if (ev == 8 && !inPause && rng() % 4 == 0) {
        gdakiMiLedgerDropClosed(x);
        CHECK(x.segs.live.size() <= 1 && !x.pend);
      } else if (ev == 9 && rng() % 6 == 0) {
        gdakiMiLedgerDropAll(x);  // d's buddy restored (its round may end a pause too)
        dev.valid = 0;
        CHECK(x.segs.live.empty() && !x.pend && !x.cellValid);
        inPause = false;
      }
      // invariants: the host's view of `valid` is the device's; no more than S live segments; consecutive numbers
      CHECK(x.cellValid == (dev.valid != 0));
      CHECK(x.segs.live.size() <= S);
      for (size_t q = 0; q + 1 < x.segs.live.size(); q++) CHECK(x.segs.live[q].seg + 1 == x.segs.live[q + 1].seg);
      if (x.pend) CHECK(x.pendCell.valid == 0 || breaksThisPause == 0);
    }
  }
  CHECK(rollbacks > 100 && breaksInPause > 100 && failedSwitches > 100);
}
static void testSetupSymmetry() {
  long combos = 0, asym = 0;
  for (int m = 0; m < (1 << 12); m++) {
    bool mineOn[2], send1[2], inTime[2], conn[2], send2[2];
    for (int k = 0; k < 2; k++) {
      mineOn[k] = m & (1 << (k * 6 + 0));
      send1[k] = m & (1 << (k * 6 + 1));
      inTime[k] = m & (1 << (k * 6 + 2));
      conn[k] = m & (1 << (k * 6 + 3));
      send2[k] = m & (1 << (k * 6 + 4));
    }
    bool connected[2], offSent[2];
    for (int k = 0; k < 2; k++) {
      const int o = 1 - k;
      // what k reads from o within its wait: o's first record (on = o's side), else nothing (a nonzero code)
      int code = GDAKI_MI_SR_TYPE;
      if (send1[o] && inTime[k]) code = mineOn[o] ? GDAKI_MI_SR_OK : GDAKI_MI_SR_OFF;
      connected[k] = gdakiMiSetupConnects(mineOn[k], code, conn[k]);
      offSent[k] = gdakiMiSetupSendsOff(mineOn[k], connected[k]) && send2[k];
    }
    bool used[2];
    for (int k = 0; k < 2; k++) used[k] = connected[k] && !(offSent[1 - k] && gdakiMiSetupDemotes(connected[k], 0));
    combos++;
    const bool bothSecondOk = send2[0] && send2[1];
    if (bothSecondOk) CHECK(used[0] == used[1]);
    if (used[0] != used[1]) asym++;
    // a rank whose own side is off never connects; one that connects read an "on" record of the other
    for (int k = 0; k < 2; k++) {
      if (!mineOn[k]) CHECK(!connected[k]);
      if (connected[k]) CHECK(mineOn[1 - k]);
    }
  }
  CHECK(combos == 4096 && asym > 0);  // only with a failed second send (the socket broke: Resume refuses, 38)
  CHECK(!gdakiMiSetupDemotes(false, 0) && !gdakiMiSetupDemotes(true, 1) && gdakiMiSetupDemotes(true, 0));
}
static void testSmallRules() {
  for (int miCtx : {1, 3, 31})
    for (int ctx = 0; ctx <= miCtx; ctx++)
      for (uint32_t e : {0u, 2u, 1000u}) {
        CHECK(gdakiMiPublishWord(false, ctx, miCtx, e) == e);  // the mirror off, or not a restore round: even
        const uint32_t w = gdakiMiPublishWord(true, ctx, miCtx, e);
        CHECK(ctx == miCtx ? w == e : w == (e | 1u));            // user QPs odd, the mirror QP even
        CHECK((w & ~1u) == e);                                  // the epoch is the new one (INJECTED writes e + 2)
      }
  for (uint32_t rec : {0u, 2u, 4u, 6u})
    for (uint32_t cov : {0u, 2u, 4u, 6u}) {
      CHECK(gdakiMiAbsorbVerdict(false, 1, 1, rec, cov) == GDAKI_MI_AB_NOT_MINE);
      CHECK(gdakiMiAbsorbVerdict(true, 0, 1, rec, cov) == GDAKI_MI_AB_NOT_MINE);
      CHECK(gdakiMiAbsorbVerdict(true, 1, -1, rec, cov) == GDAKI_MI_AB_NOT_MINE);
      CHECK(gdakiMiAbsorbVerdict(true, 1, 1, rec, cov) == (rec < cov ? GDAKI_MI_AB_STALE : GDAKI_MI_AB_GIVE_UP));
    }
  // the pull: consumed whenever a checkpoint can be asked for, whether the interval made the Step due or not
  for (int m = 0; m < 8; m++) {
    const bool on = m & 1, idle = m & 2, retry = m & 4;
    CHECK(gdakiMiPullConsumes(on, idle, retry) == (on && idle && retry));
  }
  {  // a model of Steps: interval 20, pulls arriving now and then; a pull is never left over past an idle Step
    std::mt19937 rng(5);
    bool pending = false, haveLast = false;
    uint64_t last = 0;
    int extra = 0;
    for (uint64_t step = 0; step < 5000; step++) {
      if (rng() % 37 == 0) pending = true;
      const bool idle = rng() % 4 != 0;
      bool due = idle && gdakiCkptDue(step, haveLast, last, 20);
      const bool consume = gdakiMiPullConsumes(true, idle, true) && pending;
      if (consume) pending = false;
      if (consume && !due) extra++;
      due = due || consume;
      if (due) {
        haveLast = true;
        last = step;
      }
      if (idle) CHECK(!pending);  // consumed by the first idle Step, due or not
    }
    CHECK(extra > 0);
  }
  // INJECTED's sends: owed to every other rank not told yet and not declined
  std::vector<uint8_t> sent(4, 0);
  sent[2] = 1;
  CHECK(!gdakiMiInjOwed(sent, 0, 0, false) && gdakiMiInjOwed(sent, 1, 0, false) && !gdakiMiInjOwed(sent, 2, 0, false));
  CHECK(!gdakiMiInjOwed(sent, 3, 0, true) && !gdakiMiInjOwed(sent, 4, 0, false) && !gdakiMiInjOwed(sent, -1, 0, false));
}

// ---- 8. PAUSED's armable, the measurement arm ----
static void testArmableAndMeasure() {
  for (int m = 0; m < 64; m++) {
    const bool rs = m & 1, sw = m & 2, path = m & 4, pool = m & 8, rest = m & 16, on = m & 32;
    const bool v = gdakiMiPausedArmable(rs, on, sw, path, pool, rest);
    CHECK(v == (on ? (rs && sw && path && pool && !rest) : rs));  // the mirror off: gin-restore's verdict
  }
  CHECK(gdakiMiMeasureArmOf(nullptr) == 0 && gdakiMiMeasureArmOf("") == 0 && gdakiMiMeasureArmOf("0") == 0);
  CHECK(gdakiMiMeasureArmOf("self") == 1 && gdakiMiMeasureArmOf("peer") == 2 && gdakiMiMeasureArmOf("both") == -1);
  for (int n = 2; n <= 9; n++)
    for (int me = 0; me < n; me++)
      for (int d = 0; d < n; d++)
        for (int arm : {1, 2}) {
          int target = -1;
          uint64_t lb = 0;
          const bool ok = gdakiMiMeasureLane(arm, me, d, n, 3, kL, &target, &lb);
          int w[2];
          const int tgt = arm == 1 ? me : d;
          CHECK(target == tgt);
          CHECK(ok == (d != me && ncclGinMiWardsOf(tgt, n, w) > 0));
          if (ok) CHECK(lb + kL <= ncclGinMiPoolBytes(ncclGinMiWardsOf(tgt, n, w), 3, n, kL));
        }
  int t = 0;
  uint64_t lb = 0;
  CHECK(!gdakiMiMeasureLane(0, 0, 1, 4, 3, kL, &t, &lb) && t == -1);
}

int main() {
  testLocalMirrorOff();
  testLocalMirrorOn();
  testDecide();
  testSetup();
  testSegmentsBasic();
  testSegmentsView();
  testSegmentsModel();
  testPoll();
  testAbsorb();
  testDeadline();
  testInjectedVerdict();
  testInjectedPaths();
  testArmableAndMeasure();
  testLedgerModel();
  testSetupSymmetry();
  testSmallRules();
  printf("mi_unit_host: %ld checks, %ld failed (16 test functions)\n", gChecks, gFailed);
  return gFailed == 0 ? 0 : 1;
}
