// rs_unit.cc - CPU unit test of the restore layer's decision and reason functions (EXPERIMENT.md 9.14, work packages 1
// and 2). build_rs.sh unit cuts the region between the two "gin-restore: pure functions" markers out of the working
// tree's gin_host_gdaki.cc into rs_pure.inc and compiles it here, so the test runs the library's own text. No NCCL, no
// CUDA, no network. Fake record sets stand for the all-gather of a 4-rank communicator.
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <random>
#include <string>
#include <thread>
#include <vector>

enum { GDAKI_POLICY_FAILFAST = 0, GDAKI_POLICY_HOLD = 1 };  // hk's line (build_rs.sh checks the host file has it)
#include "rs_pure.inc"

static int nChecks = 0, nFail = 0;
#define CHECK(c)                                                                  \
  do {                                                                            \
    nChecks++;                                                                    \
    if (!(c)) { nFail++; fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); } \
  } while (0)

static int restoreCalls = 0;
static long long restore1() { restoreCalls++; return 1; }
static long long restore0() { restoreCalls++; return 0; }

// One rank's process: its variables (as the setup reads them) and the other facts of its record.
struct Rank {
  const char* policy;       // NCCL_GIN_FAULT_POLICY (nullptr: unset)
  long long restore;        // NCCL_GIN_RESTORE
  const char* spare;        // NCCL_GIN_RESTORE_SPARE
  long long ginType = 3, rmaDisable = 1, symGin = 0;
  int stride = 1;
  bool magicOk = true;      // hk's magic in its record (listen socket open, local checks passed)
  bool recOffLate = false;  // a later local check before the all-gather (the baseline query) turned it off
  bool strictLib = true;    // false: a library that asks for the restore but does not force (the strict bit 0 case)
};
static long long gRestore = 1;
static long long restoreVar() { return gRestore; }

// gpu-detect's scorer phrases (rows_gd.py RE_HOLD_WARN, RE_MIX_WARN, RE_POL, the transparent-recovery-off line): no reason
// of this layer may contain one, or a gpu-detect cell run on this build would count a line twice
static bool noScorerPhrase(const char* why) {
  return strstr(why, "NCCL_GIN_FAULT_POLICY differs across ranks") == nullptr &&
         strstr(why, "NCCL_GIN_FAULT_POLICY=hold requested, not available in this build") == nullptr &&
         strstr(why, "GIN/TS: fault policy") == nullptr && strstr(why, "GIN/TS: transparent recovery OFF") == nullptr;
}

struct Outcome {
  int verdict;
  std::string why;
};
// Every rank builds its record, the all-gather gives every rank the same arrays, every rank decides. Returns rank 0's
// outcome and checks that every other rank's is the same (verdict and reason, byte for byte).
static Outcome agree(const std::vector<Rank>& ranks) {
  const int n = (int)ranks.size();
  std::vector<uint32_t> pol(n), bits(n);
  std::vector<uint8_t> on(n);
  for (int p = 0; p < n; p++) {
    gRestore = ranks[p].restore;
    struct gdakiRsCfg c = gdakiRsCfgOf(ranks[p].policy, restoreVar, ranks[p].spare);
    if (!ranks[p].strictLib) c.forceStrict = false;
    pol[p] = (uint32_t)c.policy;
    bits[p] = gdakiRsMineBits(c, ranks[p].ginType, ranks[p].rmaDisable, ranks[p].symGin, ranks[p].stride,
                              !ranks[p].magicOk || ranks[p].recOffLate);
    on[p] = gdakiRsRecOn(ranks[p].magicOk, bits[p]);
  }
  Outcome first{-1, ""};
  for (int self = 0; self < n; self++) {
    char why[GDAKI_RS_WHY_LEN];
    memset(why, 'A' + self, sizeof(why));  // a different garbage on every rank
    const int v = gdakiRsDecide(n, pol.data(), bits.data(), on.data(), why, sizeof(why));
    CHECK(memchr(why, '\0', sizeof(why)) != nullptr);
    CHECK(noScorerPhrase(why));
    if (self == 0) first = {v, why};
    else {
      CHECK(v == first.verdict);
      CHECK(first.why == why);
    }
  }
  return first;
}
static bool has(const std::string& s, const char* sub) { return s.find(sub) != std::string::npos; }
static std::vector<Rank> holdAll(int n) {
  std::vector<Rank> v;
  for (int i = 0; i < n; i++) v.push_back(Rank{"hold", 1, nullptr});
  return v;
}

static void testCfg() {
  restoreCalls = 0;
  struct gdakiRsCfg c = gdakiRsCfgOf(nullptr, restore1, nullptr);  // unset: fail-fast, NCCL_GIN_RESTORE not read
  CHECK(c.policy == GDAKI_POLICY_FAILFAST && !c.policyBad && !c.requested && !c.forceStrict && c.spare == -1);
  CHECK(restoreCalls == 0);
  c = gdakiRsCfgOf("", restore1, "");
  CHECK(c.policy == GDAKI_POLICY_FAILFAST && !c.policyBad && !c.requested && !c.spareBad && restoreCalls == 0);
  c = gdakiRsCfgOf("failfast", restore1, nullptr);
  CHECK(c.policy == GDAKI_POLICY_FAILFAST && !c.policyBad && !c.requested && !c.forceStrict && restoreCalls == 0);
  c = gdakiRsCfgOf("bogus", restore1, nullptr);  // hk: neither -> fail-fast and a WARN
  CHECK(c.policy == GDAKI_POLICY_FAILFAST && c.policyBad && !c.requested && strcmp(c.policyEnv, "bogus") == 0);
  CHECK(restoreCalls == 0);
  c = gdakiRsCfgOf("hold", restore1, nullptr);
  CHECK(c.policy == GDAKI_POLICY_HOLD && c.restoreOn && c.requested && c.forceStrict && restoreCalls == 1);
  c = gdakiRsCfgOf("hold", restore0, nullptr);  // hold, restore off: hold but never armed, nothing forced
  CHECK(c.policy == GDAKI_POLICY_HOLD && !c.restoreOn && !c.requested && !c.forceStrict && restoreCalls == 2);
  c = gdakiRsCfgOf(nullptr, restore1, "3");  // a spare process: forced whatever its policy variable
  CHECK(c.spare == 3 && c.requested && c.forceStrict && c.policy == GDAKI_POLICY_FAILFAST && restoreCalls == 2);
  c = gdakiRsCfgOf("hold", restore0, "0");
  CHECK(c.spare == 0 && c.requested && c.forceStrict);
  for (const char* bad : {"-1", "abc", "3x", " 3", "99999999999"}) {
    c = gdakiRsCfgOf(nullptr, restore1, bad);
    CHECK(c.spareBad && c.spare == -1 && !c.requested && !c.forceStrict);
  }
  char longEnv[200];
  memset(longEnv, 'x', sizeof(longEnv) - 1);
  longEnv[sizeof(longEnv) - 1] = '\0';
  c = gdakiRsCfgOf(longEnv, restore1, nullptr);
  CHECK(c.policyBad && strlen(c.policyEnv) == sizeof(c.policyEnv) - 1);
}

static void testWinStrict() {
  const struct gdakiRsCfg ff = gdakiRsCfgOf(nullptr, restore1, nullptr);
  const struct gdakiRsCfg hold = gdakiRsCfgOf("hold", restore1, nullptr);
  const struct gdakiRsCfg off = gdakiRsCfgOf("hold", restore0, nullptr);
  const struct gdakiRsCfg spare = gdakiRsCfgOf("failfast", restore1, "1");
  // fail-fast and hold with the restore off: the window flag alone (hk's rule)
  CHECK(!gdakiRsWinStrict(false, ff) && gdakiRsWinStrict(true, ff));
  CHECK(!gdakiRsWinStrict(false, off) && gdakiRsWinStrict(true, off));
  // a process that asks for the restore, and a spare: always strict (gdakiRegMr then adds no relaxed-ordering bit)
  CHECK(gdakiRsWinStrict(false, hold) && gdakiRsWinStrict(true, hold));
  CHECK(gdakiRsWinStrict(false, spare) && gdakiRsWinStrict(true, spare));
}

static void testBits() {
  const struct gdakiRsCfg ff = gdakiRsCfgOf(nullptr, restore1, nullptr);
  const struct gdakiRsCfg off = gdakiRsCfgOf("hold", restore0, nullptr);
  const struct gdakiRsCfg hold = gdakiRsCfgOf("hold", restore1, nullptr);
  const struct gdakiRsCfg spare = gdakiRsCfgOf(nullptr, restore1, "2");
  // a rank that does not ask sends hk's 0, whatever its variables and its recovery state
  CHECK(gdakiRsMineBits(ff, -1, 0, 1, 4, true) == 0u);
  CHECK(gdakiRsMineBits(off, -1, 0, 1, 4, true) == 0u);
  CHECK(gdakiRsMineBits(hold, 3, 1, 0, 1, false) == (GDAKI_RS_REQ | GDAKI_RS_STRICT));
  CHECK(gdakiRsMineBits(hold, -1, 1, 0, 1, false) == (GDAKI_RS_REQ | GDAKI_RS_STRICT | GDAKI_RS_GINTYPE));
  CHECK(gdakiRsMineBits(hold, 2, 1, 0, 1, false) == (GDAKI_RS_REQ | GDAKI_RS_STRICT | GDAKI_RS_GINTYPE));
  CHECK(gdakiRsMineBits(hold, 3, 0, 0, 1, false) == (GDAKI_RS_REQ | GDAKI_RS_STRICT | GDAKI_RS_RMA));
  CHECK(gdakiRsMineBits(hold, 3, 2, 0, 1, false) == (GDAKI_RS_REQ | GDAKI_RS_STRICT));  // any non-zero disables the proxy
  CHECK(gdakiRsMineBits(hold, 3, 1, 1, 1, false) == (GDAKI_RS_REQ | GDAKI_RS_STRICT | GDAKI_RS_SYMGIN));
  CHECK(gdakiRsMineBits(hold, 3, 1, 0, 2, false) == (GDAKI_RS_REQ | GDAKI_RS_STRICT | GDAKI_RS_STRIDE));
  CHECK(gdakiRsMineBits(hold, 3, 1, 0, 1, true) == (GDAKI_RS_REQ | GDAKI_RS_STRICT | GDAKI_RS_RECOFF));
  CHECK(gdakiRsMineBits(spare, 3, 1, 0, 1, false) == (GDAKI_RS_REQ | GDAKI_RS_STRICT | GDAKI_RS_SPARE));
  // recovery on: hk's magic, unless a rank that asks says a later local check turned it off
  CHECK(gdakiRsRecOn(true, 0u) == 1 && gdakiRsRecOn(false, 0u) == 0);
  CHECK(gdakiRsRecOn(true, GDAKI_RS_REQ | GDAKI_RS_RECOFF) == 0 && gdakiRsRecOn(true, GDAKI_RS_REQ) == 1);
}

static void testDecide() {
  // all fail-fast: nobody asks, no error (hk's world)
  {
    std::vector<Rank> v(4, Rank{nullptr, 1, nullptr});
    Outcome o = agree(v);
    CHECK(o.verdict == GDAKI_RS_NOT_REQUESTED);
  }
  // all hold with NCCL_GIN_RESTORE=0: hold but never armed, no error (7: the cell with the restore off)
  {
    std::vector<Rank> v(4, Rank{"hold", 0, nullptr});
    CHECK(agree(v).verdict == GDAKI_RS_NOT_REQUESTED);
  }
  // all hold, every condition met
  {
    Outcome o = agree(holdAll(4));
    CHECK(o.verdict == GDAKI_RS_ENABLE);
  }
  // one rank with the restore off (the refusal cell with NCCL_GIN_RESTORE=0 on one rank)
  {
    std::vector<Rank> v = holdAll(4);
    v[2].restore = 0;
    Outcome o = agree(v);
    CHECK(o.verdict == GDAKI_RS_REFUSE);
    CHECK(has(o.why, "request differs") && has(o.why, "rank 0 asks") && has(o.why, "rank 2 does not: hold with "
          "NCCL_GIN_RESTORE=0"));
  }
  {  // the lowest rank is the one with the restore off
    std::vector<Rank> v = holdAll(4);
    v[0].restore = 0;
    Outcome o = agree(v);
    CHECK(o.verdict == GDAKI_RS_REFUSE && has(o.why, "rank 1 asks") && has(o.why, "rank 0 does not: hold"));
  }
  // policies mixed (hk's G1 also WARNs and stays fail-fast)
  {
    std::vector<Rank> v = holdAll(4);
    v[1].policy = "failfast";
    Outcome o = agree(v);
    CHECK(o.verdict == GDAKI_RS_REFUSE && has(o.why, "request differs") && has(o.why, "rank 1 does not: failfast"));
    v[1].policy = nullptr;  // unset counts as fail-fast
    CHECK(agree(v).why == o.why);
    v[1].policy = "bogus";  // so does an unknown value
    CHECK(agree(v).why == o.why);
  }
  {  // one hold rank among fail-fast ranks
    std::vector<Rank> v(4, Rank{"failfast", 1, nullptr});
    v[3].policy = "hold";
    Outcome o = agree(v);
    CHECK(o.verdict == GDAKI_RS_REFUSE && has(o.why, "rank 3 asks") && has(o.why, "rank 0 does not: failfast"));
  }
  {  // hold with the restore off on one rank, fail-fast on another: the lowest rank that does not ask names the variable
    std::vector<Rank> v = holdAll(4);
    v[1].restore = 0;
    v[2].policy = "failfast";
    Outcome o = agree(v);
    CHECK(o.verdict == GDAKI_RS_REFUSE && has(o.why, "rank 1 does not: hold with NCCL_GIN_RESTORE=0"));
  }
  // not FULL: this devComm's GIN contexts skip ranks (rank stride above 1; the same on every rank)
  {
    std::vector<Rank> v = holdAll(4);
    for (auto& r : v) r.stride = 2;
    Outcome o = agree(v);
    CHECK(o.verdict == GDAKI_RS_REFUSE && has(o.why, "rank stride is above 1") && has(o.why, "rank 0"));
  }
  // symmetric kernels' GIN on (one rank, then every rank)
  {
    std::vector<Rank> v = holdAll(4);
    v[3].symGin = 1;
    Outcome o = agree(v);
    CHECK(o.verdict == GDAKI_RS_REFUSE && has(o.why, "NCCL_SYM_GIN_KERNELS_ENABLE") && has(o.why, "rank 3"));
    for (auto& r : v) r.symGin = 1;
    CHECK(has(agree(v).why, "on rank 0"));
  }
  // NCCL_GIN_TYPE not 3 (the proxy), NCCL_RMA_DISABLE not set
  {
    std::vector<Rank> v = holdAll(4);
    v[1].ginType = 2;
    Outcome o = agree(v);
    CHECK(o.verdict == GDAKI_RS_REFUSE && has(o.why, "NCCL_GIN_TYPE is not 3") && has(o.why, "rank 1"));
    v = holdAll(4);
    v[2].rmaDisable = 0;
    o = agree(v);
    CHECK(o.verdict == GDAKI_RS_REFUSE && has(o.why, "NCCL_RMA_DISABLE") && has(o.why, "rank 2"));
  }
  // the strict bit 0 on a rank that asks: the one verdict that ends the devComm creation
  {
    std::vector<Rank> v = holdAll(4);
    v[1].strictLib = false;
    Outcome o = agree(v);
    CHECK(o.verdict == GDAKI_RS_REFUSE_FATAL && has(o.why, "rank 1") && has(o.why, "strict"));
  }
  // transparent recovery off on one rank (hk's magic 0 in its record)
  {
    std::vector<Rank> v = holdAll(4);
    v[2].magicOk = false;
    Outcome o = agree(v);
    CHECK(o.verdict == GDAKI_RS_REFUSE && has(o.why, "transparent recovery is off on rank 2"));
    v = holdAll(4);  // the baseline query failed after the magic was set: hk keeps the magic, the record bit says so
    v[1].recOffLate = true;
    o = agree(v);
    CHECK(o.verdict == GDAKI_RS_REFUSE && has(o.why, "transparent recovery is off on rank 1"));
  }
  // a spare process inside a live setup
  {
    std::vector<Rank> v = holdAll(4);
    v[3].spare = "3";
    Outcome o = agree(v);
    CHECK(o.verdict == GDAKI_RS_REFUSE && has(o.why, "rank 3 runs as a spare"));
  }
  // precedence: request differs > strict > recovery off > spare > the variables (in the order of the list), lowest rank
  {
    std::vector<Rank> v = holdAll(4);
    v[3].strictLib = false;
    v[0].symGin = 1;
    CHECK(agree(v).verdict == GDAKI_RS_REFUSE_FATAL);
    v[2].restore = 0;  // a rank that does not ask: the request differs first, not fatal
    CHECK(agree(v).verdict == GDAKI_RS_REFUSE && has(agree(v).why, "request differs"));
  }
  {
    std::vector<Rank> v = holdAll(4);
    v[0].rmaDisable = 0;
    v[2].ginType = -1;
    CHECK(has(agree(v).why, "NCCL_GIN_TYPE is not 3") && has(agree(v).why, "rank 2"));
    v[3].magicOk = false;
    CHECK(has(agree(v).why, "transparent recovery is off on rank 3"));
  }
  // one and two ranks
  {
    CHECK(agree(holdAll(1)).verdict == GDAKI_RS_ENABLE);
    std::vector<Rank> v = holdAll(2);
    v[1].policy = "failfast";
    CHECK(agree(v).verdict == GDAKI_RS_REFUSE);
  }
  CHECK(strcmp(gdakiRsVerdictName(GDAKI_RS_ENABLE), "can be enabled") == 0);
  CHECK(strcmp(gdakiRsVerdictName(GDAKI_RS_NOT_REQUESTED), "not requested") == 0);
  CHECK(strcmp(gdakiRsVerdictName(GDAKI_RS_REFUSE), "refused") == 0);
  CHECK(strcmp(gdakiRsVerdictName(GDAKI_RS_REFUSE_FATAL), "refused") == 0);
  // a short reason buffer is cut, never overrun
  {
    uint32_t pol[2] = {GDAKI_POLICY_HOLD, GDAKI_POLICY_FAILFAST}, bits[2] = {GDAKI_RS_REQ | GDAKI_RS_STRICT, 0};
    uint8_t on[2] = {1, 1};
    char small[8];
    CHECK(gdakiRsDecide(2, pol, bits, on, small, sizeof(small)) == GDAKI_RS_REFUSE && strlen(small) == 7);
  }
}

// Random record sets: the verdict follows the rules, whatever the mix.
static void testRandom() {
  static const uint32_t factBits[] = {GDAKI_RS_SPARE, GDAKI_RS_GINTYPE, GDAKI_RS_RMA, GDAKI_RS_SYMGIN, GDAKI_RS_STRIDE};
  std::mt19937 rng(20261011);
  for (int it = 0; it < 200000; it++) {
    const int n = 1 + (int)(rng() % 8);
    std::vector<uint32_t> pol(n), bits(n);
    std::vector<uint8_t> on(n);
    for (int p = 0; p < n; p++) {
      pol[p] = rng() % 2;
      bits[p] = (rng() % 3 == 0) ? 0u : (GDAKI_RS_REQ | ((rng() % 8) ? GDAKI_RS_STRICT : 0u));
      if ((bits[p] & GDAKI_RS_REQ) && rng() % 4 == 0)
        bits[p] |= factBits[rng() % (sizeof(factBits) / sizeof(factBits[0]))];
      if ((bits[p] & GDAKI_RS_REQ) && rng() % 10 == 0) bits[p] |= GDAKI_RS_RECOFF;
      on[p] = gdakiRsRecOn(rng() % 10 != 0, bits[p]);
    }
    char why[GDAKI_RS_WHY_LEN];
    const int v = gdakiRsDecide(n, pol.data(), bits.data(), on.data(), why, sizeof(why));
    int nReq = 0;
    bool allStrict = true, allOn = true, anyFact = false;
    for (int p = 0; p < n; p++) {
      if (bits[p] & GDAKI_RS_REQ) nReq++;
      if (!(bits[p] & GDAKI_RS_STRICT)) allStrict = false;
      if (!on[p]) allOn = false;
      if (bits[p] & ~(GDAKI_RS_REQ | GDAKI_RS_STRICT | GDAKI_RS_RECOFF)) anyFact = true;
    }
    const int want = nReq == 0 ? GDAKI_RS_NOT_REQUESTED
                     : nReq < n ? GDAKI_RS_REFUSE
                     : !allStrict ? GDAKI_RS_REFUSE_FATAL
                     : (!allOn || anyFact) ? GDAKI_RS_REFUSE
                     : GDAKI_RS_ENABLE;
    CHECK(v == want);
    CHECK(why[0] != '\0' && memchr(why, '\0', sizeof(why)) != nullptr);
    CHECK(noScorerPhrase(why));
  }
}

// ---- work package 2: Resume ----
static bool namesRank(const char* s) {
  for (const char* q = strstr(s, "rank "); q != nullptr; q = strstr(q + 1, "rank "))
    if (q[5] >= '0' && q[5] <= '9') return true;
  return false;
}
// Every local condition alone, then all of them in order: each gives its own code and text, the first one wins.
static void testLocal() {
  char why[GDAKI_RS_WHY_LEN];
  struct gdakiRsLocalIn ok;  // a rank that can enable: GDAKI, one connection, FULL, setup with recovery on, ...
  ok.ginType = 3;
  ok.nConn = 1;
  ok.haveSetup = true;
  ok.nUserCtx = 1;
  ok.tsOn = true;
  CHECK(gdakiRsLocalCheck(ok, why, sizeof(why)) == GDAKI_RS_L_OK && has(why, "can enable"));
  struct Case {
    const char* key;
    void (*make)(struct gdakiRsLocalIn&);
  };
  static const char* toldText = "every wait word raised: abort";
  static const Case cases[] = {
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
    {"side table is not set up on this rank (no memory)", [](struct gdakiRsLocalIn& x) { x.sideOk = false; x.sideWhy = "no memory"; }},
    {"restore buffers are not in the NIC copy path (unknown)", [](struct gdakiRsLocalIn& x) { x.rsLbOk = false; }},
    {"2 window(s) were registered after", [](struct gdakiRsLocalIn& x) { x.winsAfter = 2; }},
    {"1 window(s) of this context's restore buffers were deregistered", [](struct gdakiRsLocalIn& x) { x.winsGone = 1; }},
    {"resource window could not be added to the NIC copy path (list full)",
     [](struct gdakiRsLocalIn& x) { x.resOk = false; x.resWhy = "list full"; }},
    {"round cap stopped recovery", [](struct gdakiRsLocalIn& x) { x.escalated = true; }},
  };
  const int nCases = (int)(sizeof(cases) / sizeof(cases[0]));
  for (int i = 0; i < nCases; i++) {
    struct gdakiRsLocalIn x = ok;
    cases[i].make(x);
    memset(why, 'Z', sizeof(why));
    const int code = gdakiRsLocalCheck(x, why, sizeof(why));
    CHECK(code == i + 1);
    CHECK(has(why, cases[i].key));
    CHECK(!namesRank(why));  // the local text names no rank number (the decision adds "rank p: "); the told text
                             // used here names none either (a real one may name the peer whose word was raised)
    CHECK(noScorerPhrase(why));
  }
  {  // all at once: the first in the order
    struct gdakiRsLocalIn x = ok;
    for (int i = nCases - 1; i >= 0; i--) cases[i].make(x);
    CHECK(gdakiRsLocalCheck(x, why, sizeof(why)) == 1);
  }
  {  // a known reason why recovery went off is named
    struct gdakiRsLocalIn x = ok;
    x.tsOn = false;
    x.offWhy = "connect timed out";
    gdakiRsLocalCheck(x, why, sizeof(why));
    CHECK(has(why, "(connect timed out)"));
    x.restoreMs = 0;  // a zero deadline is refused too (after the earlier conditions are met)
    x.tsOn = true;
    CHECK(gdakiRsLocalCheck(x, why, sizeof(why)) == 20);  // the deadline condition's place in the order
    x.restoreMs = 29999;
    CHECK(gdakiRsLocalCheck(x, why, sizeof(why)) == GDAKI_RS_L_OK);
  }
}

// The side table's layout: sizes rounded down to powers of two and bounded, rings 256-byte aligned, no overlap.
static void testSideLayout() {
  struct gdakiRsSideLayout L;
  CHECK(gdakiRsSideLayoutOf(4, 3, 4096, 1 << 20, &L));
  CHECK(L.nEntries == 4096 && L.payBytes == (1u << 20) && L.qpOff == 64);
  CHECK(L.ringsOff == ((64 + 4 * 128 + 255) & ~(size_t)255) && L.ringsOff % 256 == 0);
  CHECK(L.ringBytes == (size_t)4096 * 64 + (1u << 20));
  CHECK(L.bytes == ((L.ringsOff + 3 * L.ringBytes + 4095) & ~(size_t)4095) && L.bytes % 4096 == 0);
  CHECK(gdakiRsSideLayoutOf(8, 7, 5000, 3000000, &L) && L.nEntries == 4096 && L.payBytes == (1u << 21));
  CHECK(gdakiRsSideLayoutOf(1, 0, 1, 1, &L) && L.nEntries == 64 && L.payBytes == 4096 && L.bytes == 4096);
  CHECK(gdakiRsSideLayoutOf(2, 1, 1LL << 40, 1LL << 40, &L) && L.nEntries == (1u << 20) && L.payBytes == (1ull << 30));
  CHECK(!gdakiRsSideLayoutOf(2, 3, 4096, 4096, &L));                     // more logged QPs than QPs
  CHECK(!gdakiRsSideLayoutOf(2000000, 2000000, 1 << 20, 1 << 30, &L));    // past the bound (1 TiB)
  for (int nqp = 1; nqp <= 64; nqp += 7)
    for (int k = 0; k <= nqp; k += 3) {
      CHECK(gdakiRsSideLayoutOf(nqp, k, 100 + nqp, 10000 * k + 1, &L));
      CHECK(L.ringsOff >= L.qpOff + (size_t)nqp * 128 && L.ringsOff % 256 == 0 && (L.ringBytes % 256) == 0);
      CHECK((L.nEntries & (L.nEntries - 1)) == 0 && (L.payBytes & (L.payBytes - 1)) == 0);
      CHECK(L.bytes % 4096 == 0 && L.bytes >= L.ringsOff + (size_t)k * L.ringBytes && L.bytes < L.ringsOff + (size_t)k * L.ringBytes + 4096);
    }
  CHECK(gdakiRsPow2Floor(1) == 1 && gdakiRsPow2Floor(2) == 2 && gdakiRsPow2Floor(3) == 2 && gdakiRsPow2Floor(4096) == 4096);
}

// Resume's view of a collComm's windows: after the context, deregistered since, the resource window by address.
static void testCountWins() {
  const uint64_t ctx = 10;  // the context started when the registry's sequence was 10
  std::vector<struct gdakiRsWinView> w = {
    {0x1000, 0x2000, 3, 0, false},   // before the context, still registered: covered
    {0x3000, 0x4000, 5, 12, true},   // before, deregistered after the context: counted as deregistered since
    {0x5000, 0x6000, 7, 9, true},    // before, deregistered before the context: not covered, not counted
    {0x7000, 0x8000, 11, 0, false},  // after the context: counted
    {0x9000, 0xa000, 13, 14, true},  // after, already deregistered: not counted
    {0xb000, 0xc000, 15, 0, false},  // the resource window (after the context): found, to be added
  };
  struct gdakiRsWinCount c = gdakiRsCountWins(w.data(), (int)w.size(), ctx, 0xb800);
  CHECK(c.after == 1 && c.goneSince == 1 && c.resFound && c.res == 5);
  c = gdakiRsCountWins(w.data(), (int)w.size(), ctx, 0);  // no resource window: found by definition, the last counts
  CHECK(c.after == 2 && c.goneSince == 1 && c.resFound && c.res == -1);
  c = gdakiRsCountWins(w.data(), (int)w.size(), ctx, 0xd000);  // an address no window holds
  CHECK(!c.resFound && c.res == -1 && c.after == 2);
  c = gdakiRsCountWins(w.data(), (int)w.size(), ctx, 0x1800);  // a resource window registered before: covered already
  CHECK(c.resFound && c.res == -1 && c.after == 2);
  c = gdakiRsCountWins(w.data(), (int)w.size(), ctx, 0x9800);  // its window is gone: not found
  CHECK(!c.resFound);
  c = gdakiRsCountWins(w.data(), 0, ctx, 0x1800);
  CHECK(!c.resFound && c.after == 0 && c.goneSince == 0);
  CHECK(gdakiRsCountWins(w.data(), (int)w.size(), ctx, 0x2000).resFound == false);  // the range's end is outside
}

static struct gdakiRsXRec xrec(int rank, bool req, int policy, int setupVerdict, const char* setupWhy, int localCode,
                               const char* localWhy) {
  struct gdakiRsXRec r;
  memset(&r, 0, sizeof(r));
  r.magic = GDAKI_RS_X_MAGIC;
  r.rank = rank;
  r.req = req ? 1u : 0u;
  r.policy = (uint32_t)policy;
  r.setupVerdict = setupVerdict;
  snprintf(r.setupWhy, sizeof(r.setupWhy), "%s", setupWhy);
  r.localCode = localCode;
  snprintf(r.localWhy, sizeof(r.localWhy), "%s", localWhy);
  return r;
}
// Every rank decides from the same exchanged records: same verdict, same text.
static Outcome resumeAgree(const std::vector<struct gdakiRsXRec>& x) {
  Outcome first{-1, ""};
  for (int self = 0; self < (int)x.size(); self++) {
    char why[GDAKI_RS_RWHY_LEN];
    memset(why, 'a' + self, sizeof(why));
    const int v = gdakiRsResumeDecide((int)x.size(), x.data(), why, sizeof(why));
    CHECK(memchr(why, '\0', sizeof(why)) != nullptr && noScorerPhrase(why));
    if (self == 0) first = {v, why};
    else CHECK(v == first.verdict && first.why == why);
  }
  return first;
}
static void testResumeDecide() {
  const int H = GDAKI_POLICY_HOLD, F = GDAKI_POLICY_FAILFAST;
  std::vector<struct gdakiRsXRec> x;
  for (int p = 0; p < 4; p++) x.push_back(xrec(p, true, H, GDAKI_RS_ENABLE, "every rank asks", 0, "ok"));
  CHECK(resumeAgree(x).verdict == GDAKI_RS_ENABLE);
  {  // nobody asks: success, whatever the local judgments
    auto y = x;
    for (auto& r : y) { r.req = 0; r.policy = F; r.localCode = 4; r.setupVerdict = -1; }
    CHECK(resumeAgree(y).verdict == GDAKI_RS_NOT_REQUESTED);
  }
  {  // one rank with the restore off (the refusal cell): every rank refuses with the same text
    auto y = x;
    y[2].req = 0;
    Outcome o = resumeAgree(y);
    CHECK(o.verdict == GDAKI_RS_REFUSE && has(o.why, "rank 0 asks for it, rank 2 does not: hold with NCCL_GIN_RESTORE=0"));
    y[2].policy = F;
    CHECK(has(resumeAgree(y).why, "rank 2 does not: failfast policy"));
  }
  {  // a setup decision that refused (e.g. NCCL_SYM_GIN_KERNELS_ENABLE): named as the setup agreement's
    auto y = x;
    for (auto& r : y) {
      r.setupVerdict = GDAKI_RS_REFUSE;
      snprintf(r.setupWhy, sizeof(r.setupWhy), "NCCL_SYM_GIN_KERNELS_ENABLE is not 0 on rank 1");
    }
    Outcome o = resumeAgree(y);
    CHECK(o.verdict == GDAKI_RS_REFUSE && has(o.why, "setup agreement: NCCL_SYM_GIN_KERNELS_ENABLE is not 0 on rank 1"));
    y[3].localCode = 5;  // a setup refusal comes before local judgments
    CHECK(resumeAgree(y).why == o.why);
  }
  {  // the strict-bit setup verdict (the context was not created) reaches Resume as well
    auto y = x;
    for (auto& r : y) {
      r.setupVerdict = GDAKI_RS_REFUSE_FATAL;
      snprintf(r.setupWhy, sizeof(r.setupWhy), "rank 1 asks for the restore but does not register strict");
    }
    CHECK(resumeAgree(y).verdict == GDAKI_RS_REFUSE && has(resumeAgree(y).why, "setup agreement: rank 1"));
  }
  {  // a local judgment that refuses (non-GDAKI backend on rank 3, NCCL_GIN_TYPE): the lowest rank's text
    auto y = x;
    y[3].localCode = 5;
    snprintf(y[3].localWhy, sizeof(y[3].localWhy), "the devComm's GIN backend is not GDAKI (type 2)");
    Outcome o = resumeAgree(y);
    CHECK(o.verdict == GDAKI_RS_REFUSE && o.why == "rank 3: the devComm's GIN backend is not GDAKI (type 2)");
    y[1].localCode = 16;
    snprintf(y[1].localWhy, sizeof(y[1].localWhy), "transparent recovery went off on this rank after the setup "
             "agreement (connect timed out)");
    CHECK(has(resumeAgree(y).why, "rank 1: transparent recovery went off"));
  }
  {  // a record of another library or another rank's slot
    auto y = x;
    y[2].magic = 0;
    CHECK(resumeAgree(y).verdict == GDAKI_RS_REFUSE && has(resumeAgree(y).why, "rank 2 sent no valid restore record"));
    y = x;
    y[1].rank = 3;
    CHECK(has(resumeAgree(y).why, "rank 1 sent no valid"));
  }
  {  // a setup text that fills its whole field (no terminator) is read within the field
    auto y = x;
    for (auto& r : y) { r.setupVerdict = GDAKI_RS_REFUSE; memset(r.setupWhy, 'q', sizeof(r.setupWhy)); }
    Outcome o = resumeAgree(y);
    CHECK(o.verdict == GDAKI_RS_REFUSE && o.why.size() < GDAKI_RS_RWHY_LEN);
  }
}

// Random exchanged record sets: the verdict follows the order of the rules, and every rank's text is the same.
static void testResumeRandom() {
  std::mt19937 rng(20261012);
  for (int it = 0; it < 50000; it++) {
    const int n = 1 + (int)(rng() % 6);
    std::vector<struct gdakiRsXRec> x;
    for (int p = 0; p < n; p++) {
      const bool req = rng() % 4 != 0;
      const int sv = (int)(rng() % 5) - 1;  // -1 .. 3
      const int lc = rng() % 3 == 0 ? 1 + (int)(rng() % 21) : 0;
      x.push_back(xrec(p, req, (int)(rng() % 2), sv, "setup text", lc, "local text"));
    }
    if (rng() % 50 == 0) x[rng() % n].magic = 7;
    int nReq = 0;
    bool bad = false, setupRefused = false, localRefused = false;
    for (int p = 0; p < n; p++) {
      if (x[p].magic != GDAKI_RS_X_MAGIC) bad = true;
      if (x[p].req) nReq++;
      if (x[p].setupVerdict == GDAKI_RS_REFUSE || x[p].setupVerdict == GDAKI_RS_REFUSE_FATAL) setupRefused = true;
      if (x[p].localCode != 0) localRefused = true;
    }
    const int want = bad ? GDAKI_RS_REFUSE
                     : nReq == 0 ? GDAKI_RS_NOT_REQUESTED
                     : (nReq < n || setupRefused || localRefused) ? GDAKI_RS_REFUSE
                     : GDAKI_RS_ENABLE;
    Outcome o = resumeAgree(x);
    CHECK(o.verdict == want);
    if (!bad && nReq == n && setupRefused) CHECK(has(o.why, "setup agreement: setup text"));
    if (!bad && nReq == n && !setupRefused && localRefused) CHECK(has(o.why, ": local text"));
  }
}

// A stand-in for the communicator's bootstrap all-gather: each rank's call blocks until every rank has called, or until
// that rank's own abort flag is set (as the bootstrap socket loops end on the communicator's abort flag).
struct FakeBoot {
  int n;
  std::mutex mu;
  std::condition_variable cv;
  int arrived = 0;
  bool completed = false, broken = false;  // a rank that aborted before completion breaks the ring for good
  std::vector<struct gdakiRsXRec> buf;
  std::vector<int> aborted, abortCalls;
  explicit FakeBoot(int n_) : n(n_), buf((size_t)n_), aborted((size_t)n_, 0), abortCalls((size_t)n_, 0) {}
  int allGather(int self, struct gdakiRsXRec* data) {
    std::unique_lock<std::mutex> lk(mu);
    buf[(size_t)self] = data[self];
    arrived++;
    if (arrived == n && !broken) completed = true;
    cv.notify_all();
    cv.wait(lk, [&] { return completed || aborted[(size_t)self]; });
    if (!completed) return 3;  // ncclInternalError from the socket loop
    for (int p = 0; p < n; p++) data[p] = buf[(size_t)p];
    return 0;
  }
  void abortRank(int self) {
    std::lock_guard<std::mutex> lk(mu);
    aborted[(size_t)self] = 1;
    abortCalls[(size_t)self]++;
    if (!completed) broken = true;
    cv.notify_all();
  }
};
struct RankResult {
  int verdict = -1;
  bool expired = false;
  int xr = -1;
  std::string why;
  double ms = 0;
};
// One rank's Resume as the library runs it: its record, the bounded exchange, the decision.
static RankResult runRank(FakeBoot& fb, int self, const struct gdakiRsXRec& mine, long long boundMs) {
  RankResult rr;
  std::vector<struct gdakiRsXRec> all((size_t)fb.n);
  all[(size_t)self] = mine;
  const auto t0 = std::chrono::steady_clock::now();
  rr.xr = gdakiRsRunBounded([&] { return fb.allGather(self, all.data()); }, [&] { fb.abortRank(self); }, boundMs,
                            &rr.expired);
  rr.ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
  if (!rr.expired && rr.xr == 0) {
    char why[GDAKI_RS_RWHY_LEN];
    rr.verdict = gdakiRsResumeDecide(fb.n, all.data(), why, sizeof(why));
    rr.why = why;
  }
  return rr;
}
static void testExchange() {
  const int H = GDAKI_POLICY_HOLD;
  {  // four ranks, rank 2 cannot enable: every rank returns the same refusal, no bound expired, no abort
    FakeBoot fb(4);
    std::vector<RankResult> res(4);
    std::vector<std::thread> th;
    for (int p = 0; p < 4; p++)
      th.emplace_back([&, p] {
        std::this_thread::sleep_for(std::chrono::milliseconds(10 * p));  // ranks arrive at different times
        struct gdakiRsXRec mine = xrec(p, true, H, GDAKI_RS_ENABLE, "ok", p == 2 ? 9 : 0,
                                       p == 2 ? "host RMA is on (1 contexts; NCCL_NUM_RMA_CTX=0 turns it off)" : "ok");
        res[(size_t)p] = runRank(fb, p, mine, 5000);
      });
    for (auto& t : th) t.join();
    for (int p = 0; p < 4; p++) {
      CHECK(!res[(size_t)p].expired && res[(size_t)p].xr == 0 && fb.abortCalls[(size_t)p] == 0);
      CHECK(res[(size_t)p].verdict == GDAKI_RS_REFUSE && res[(size_t)p].why == res[0].why);
    }
    CHECK(has(res[0].why, "rank 2: host RMA is on"));
  }
  {  // every rank can enable
    FakeBoot fb(4);
    std::vector<RankResult> res(4);
    std::vector<std::thread> th;
    for (int p = 0; p < 4; p++)
      th.emplace_back([&, p] { res[(size_t)p] = runRank(fb, p, xrec(p, true, H, GDAKI_RS_ENABLE, "ok", 0, "ok"), 5000); });
    for (auto& t : th) t.join();
    for (int p = 0; p < 4; p++) CHECK(res[(size_t)p].verdict == GDAKI_RS_ENABLE && res[(size_t)p].why == res[0].why);
  }
  {  // rank 3 never calls Resume: the others end within the bound (+ slack), each sets its own abort flag once
    const long long bound = 300;
    FakeBoot fb(4);
    std::vector<RankResult> res(3);
    std::vector<std::thread> th;
    for (int p = 0; p < 3; p++)
      th.emplace_back([&, p] { res[(size_t)p] = runRank(fb, p, xrec(p, true, H, GDAKI_RS_ENABLE, "ok", 0, "ok"), bound); });
    for (auto& t : th) t.join();
    for (int p = 0; p < 3; p++) {
      CHECK(res[(size_t)p].expired && res[(size_t)p].xr != 0 && fb.abortCalls[(size_t)p] == 1);
      CHECK(res[(size_t)p].ms >= bound - 5 && res[(size_t)p].ms < bound + 2000);
    }
    CHECK(fb.abortCalls[3] == 0);
    // the late rank arrives after the others aborted: its exchange cannot complete either (its own bound, short here)
    RankResult late = runRank(fb, 3, xrec(3, true, H, GDAKI_RS_ENABLE, "ok", 0, "ok"), 100);
    CHECK(late.expired && late.verdict == -1 && fb.abortCalls[3] == 1);
  }
  {  // no bound (<= 0): the exchange runs alone, nothing is aborted
    FakeBoot fb(1);
    RankResult r = runRank(fb, 0, xrec(0, false, GDAKI_POLICY_FAILFAST, -1, "", 0, "ok"), 0);
    CHECK(!r.expired && r.xr == 0 && r.verdict == GDAKI_RS_NOT_REQUESTED && fb.abortCalls[0] == 0);
  }
  {  // the exchange ending near the bound: either it completed (no abort) or the bound expired (abort called once)
    for (int it = 0; it < 200; it++) {
      int aborts = 0;
      bool expired = false;
      const int rc = gdakiRsRunBounded(
        [&] { std::this_thread::sleep_for(std::chrono::microseconds(1000 + (it % 7) * 150)); return 0; },
        [&] { aborts++; }, 1, &expired);
      CHECK(rc == 0 && aborts == (expired ? 1 : 0));
    }
  }
}

int main() {
  testCfg();
  testWinStrict();
  testBits();
  testDecide();
  testRandom();
  testLocal();
  testSideLayout();
  testCountWins();
  testResumeDecide();
  testResumeRandom();
  testExchange();
  printf("rs_unit: %d checks, %d failed\n", nChecks, nFail);
  return nFail == 0 ? 0 : 1;
}
