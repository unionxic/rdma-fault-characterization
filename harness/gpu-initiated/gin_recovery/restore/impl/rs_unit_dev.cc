// rs_unit_dev.cc - the dev branch's CPU unit test (impl/PARALLEL.md; a copy of rs_unit.cc whose work package 4 part is
// redone for one log ring per rank, plus the tests of work packages 6 and 9). It supersedes rs_unit.cc's work package 4
// tests (the integration keeps one of the two files). build_rs_dev.sh unit cuts the host file's regions "gin-restore: pure
// functions" (rs_pure.inc) and "gin-restore (dev): log, suppress and replay, pure" (rs_dev_pure.inc) out of the working
// tree's gin_host_gdaki.cc and compiles them here, so the test runs the library's own text. No NCCL, no CUDA, no network.
// Fake record sets stand for the all-gather of a 4-rank communicator.
// Work package 4: the working tree's device-host common header is included too: the send path's checksum (its walk run
// with an emulated device loader that allows only aligned loads inside the buffer, against the host function and an
// independent reading of the scheme), the log entry layout, the suppression plan and the ring's overflow rule.
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstddef>
#include <condition_variable>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <mutex>
#include <random>
#include <string>
#include <thread>
#include <vector>

enum { GDAKI_POLICY_FAILFAST = 0, GDAKI_POLICY_HOLD = 1 };  // hk's line (build_rs.sh checks the host file has it)
#include "nccl_device/gin/gdaki/gin_gdaki_device_host_common.h"
#include "rs_pure.inc"
// The dev branch's log API block, cut from the host file (the library's text) by build_rs_dev.sh unit: its records and
// constants for the dev pure region (work package 9); its functions are declared there and never defined here.
typedef int ncclResult_t;
#ifndef NCCL_GIN_RECOVERY_MAX_QPS
#define NCCL_GIN_RECOVERY_MAX_QPS 64  // nccl.h.in
#endif
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wunused-function"
#include "rs_dev_api.inc"
#pragma GCC diagnostic pop
#include "rs_dev_pure.inc"

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
    {"measurement mode is on (NCCL_GIN_RESTORE_LOG_MEASURE)", [](struct gdakiRsLocalIn& x) { x.logMeasure = true; }},
    {"program not built with NCCL_GIN_RESTORE_DEVICE", [](struct gdakiRsLocalIn& x) { x.deviceBuilt = false; }},
    {"atomic capability is below IBV_ATOMIC_HCA (atomic_cap 0)", [](struct gdakiRsLocalIn& x) { x.atomicCap = 0; }},
    {"NIC atomics of the restore are not ready on this rank (the self-test's fetch-and-add",
     [](struct gdakiRsLocalIn& x) {
       x.atomicOk = false;
       x.atomicWhy = "the self-test's fetch-and-add of 1 to 0 read 0 then 0x100000000000000 (not host byte order?)";
     }},
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
  {  // option (b): an HCA whose atomics are atomic beyond the HCA (IBV_ATOMIC_GLOB, 2) is accepted too
    struct gdakiRsLocalIn x = ok;
    x.atomicCap = 2;
    CHECK(gdakiRsLocalCheck(x, why, sizeof(why)) == GDAKI_RS_L_OK);
    x.atomicCap = GDAKI_RS_ATOMIC_HCA;
    CHECK(gdakiRsLocalCheck(x, why, sizeof(why)) == GDAKI_RS_L_OK);
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

// The side table's layout (work package 4 redone: one ring per context): a 128-byte header, 128 bytes per QP, then one
// ring of nEntries x 64 bytes when any QP may log; the entry count rounded down to a power of two and bounded, the ring
// 256-byte aligned, whole pages; the 4-rank values of impl/rs_log_api.h.
static void testSideLayout() {
  struct gdakiRsSideLayout L;
  CHECK(gdakiRsSideLayoutOf(4, 3, 4096, &L));
  CHECK(L.nEntries == 4096 && L.qpOff == 128);
  CHECK(L.ringsOff == ((128 + 4 * 128 + 255) & ~(size_t)255) && L.ringsOff % 256 == 0);
  CHECK(L.ringBytes == (size_t)4096 * 64);
  CHECK(L.bytes == ((L.ringsOff + L.ringBytes + 4095) & ~(size_t)4095) && L.bytes % 4096 == 0);
  CHECK(L.bytes == 266240);  // 4 ranks, 1 context: 4 QPs, one ring (65 pages)
  CHECK(gdakiRsSideLayoutOf(16, 12, 4096, &L) && L.bytes == 266240);  // 4 ranks, 4 contexts: the same ring (rs_log_api.h)
  CHECK(gdakiRsSideLayoutOf(8, 7, 5000, &L) && L.nEntries == 4096);
  CHECK(gdakiRsSideLayoutOf(1, 0, 1, &L) && L.nEntries == 0 && L.ringBytes == 0 && L.bytes == 4096);  // nothing logs
  CHECK(gdakiRsSideLayoutOf(2, 1, 1, &L) && L.nEntries == 64);
  CHECK(gdakiRsSideLayoutOf(2, 1, 1LL << 40, &L) && L.nEntries == (1u << 20));
  CHECK(!gdakiRsSideLayoutOf(2, 3, 4096, &L));                       // more logged QPs than QPs
  CHECK(gdakiRsSideLayoutOf(1 << 24, 3, 64, &L));                     // as many QPs as the entry's QP field holds
  CHECK(!gdakiRsSideLayoutOf((1 << 24) + 1, 3, 64, &L));              // more
  for (int nqp = 1; nqp <= 64; nqp += 7)
    for (int k = 0; k <= nqp; k += 3) {
      CHECK(gdakiRsSideLayoutOf(nqp, k, 100 + nqp, &L));
      CHECK(L.ringsOff >= L.qpOff + (size_t)nqp * 128 && L.ringsOff % 256 == 0 && (L.ringBytes % 256) == 0);
      CHECK(L.ringBytes == (size_t)L.nEntries * 64 && (k == 0) == (L.nEntries == 0));
      CHECK(L.nEntries == 0 || (L.nEntries & (L.nEntries - 1)) == 0);
      CHECK(L.bytes % 4096 == 0 && L.bytes >= L.ringsOff + L.ringBytes && L.bytes < L.ringsOff + L.ringBytes + 4096);
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

// ---- work package 4 ----
// An independent reading of EXPERIMENT.md 9.5's checksum: the picked words (FULL: all; SAMPLED: j mod 1024 < 16 or one of
// the last 16), little-endian 4-byte words with the last one zero-padded, the two lanes and the 64-bit mix folded to 32.
static uint32_t refCsum(uint32_t scheme, const uint8_t* p, uint64_t bytes) {
  if (scheme != 1 && scheme != 2) return 0;
  const uint64_t n = (bytes + 3) / 4;
  uint32_t a = 0, b = 0;
  for (uint64_t j = 0; j < n; j++) {
    const bool pick = scheme == 2 || (j % 1024) < 16 || j + 16 >= n;
    if (!pick) continue;
    uint32_t u = 0;
    for (uint64_t k = 0; k < 4; k++)
      if (4 * j + k < bytes) u |= (uint32_t)p[4 * j + k] << (8 * k);
    const uint32_t x = u ^ (uint32_t)((uint32_t)(j & 0xffffffffu) * 2654435761u);
    a += x * 2246822519u;
    b += (x ^ (x >> 15)) * 3266489917u;
  }
  uint64_t h = ((uint64_t)b << 32 | a) ^ (bytes * 0x9E3779B97F4A7C15ull) ^ ((uint64_t)scheme << 56);
  h = (h ^ (h >> 30)) * 0xBF58476D1CE4E5B9ull;
  h = (h ^ (h >> 27)) * 0x94D049BB133111EBull;
  h ^= h >> 31;
  return (uint32_t)(h ^ (h >> 32));
}
// The bytes the scheme reads: what the device must read, no more, no less.
static uint64_t refBytesRead(uint32_t scheme, uint64_t bytes) {
  if (scheme != 1 && scheme != 2) return 0;
  const uint64_t n = (bytes + 3) / 4;
  uint64_t r = 0;
  for (uint64_t j = 0; j < n; j++)
    if (scheme == 2 || (j % 1024) < 16 || j + 16 >= n) r += std::min<uint64_t>(4, bytes - 4 * j);
  return r;
}
// The device's loads, emulated: only aligned loads inside [lo, hi) are allowed (as ld.global.cg needs), and counted.
struct EmuDevLoad {
  const uint8_t* lo;
  const uint8_t* hi;
  mutable uint64_t bytesRead = 0;
  mutable bool bad = false;
  uint8_t b1(const uint8_t* q) const {
    if (q < lo || q + 1 > hi) { bad = true; return 0; }
    bytesRead += 1;
    return *q;
  }
  uint32_t w4(const uint8_t* q) const {
    if (((uintptr_t)q & 3) != 0 || q < lo || q + 4 > hi) { bad = true; return 0; }
    bytesRead += 4;
    uint32_t v;
    memcpy(&v, q, 4);
    return v;
  }
  struct ncclGinRsQuad w16(const uint8_t* q) const {
    struct ncclGinRsQuad v = {0, 0, 0, 0};
    if (((uintptr_t)q & 15) != 0 || q < lo || q + 16 > hi) { bad = true; return v; }
    bytesRead += 16;
    memcpy(&v, q, 16);
    return v;
  }
};
static void testCsum() {
  std::mt19937_64 rng(20261012);
  std::vector<uint8_t> mem(600000 + 64);
  for (auto& c : mem) c = (uint8_t)rng();
  uint8_t* const base = (uint8_t*)(((uintptr_t)mem.data() + 63) & ~(uintptr_t)63);  // 64-aligned, then misaligned below
  std::vector<uint64_t> lens = {0, 1, 2, 3, 4, 5, 7, 8, 15, 16, 17, 63, 64, 65, 67, 127, 128, 129, 255, 256, 4092, 4093,
                                4095, 4096, 4097, 4100, 4160, 4161, 8191, 8192, 8193, 12288 + 13, 65536, 65537, 262144,
                                262147, 524288 + 5};
  for (int i = 0; i < 400; i++) lens.push_back(rng() % 300000);
  int walks = 0;
  for (uint64_t len : lens)
    for (int mis = 0; mis < 16; mis++) {
      if (mis > 3 && (rng() % 3) != 0 && len > 4096) continue;  // keep the run short: every misalignment on short lengths
      const uint8_t* p = base + mis;
      for (uint32_t scheme = 0; scheme <= 2; scheme++) {
        const uint32_t want = refCsum(scheme, p, len);
        CHECK(ncclGinRsCsumBuf(scheme, p, len) == want);
        EmuDevLoad ld{p, p + len};
        CHECK(ncclGinRsCsumWalk(scheme, p, len, ld) == want);
        CHECK(!ld.bad);
        CHECK(ld.bytesRead == refBytesRead(scheme, len));
        walks++;
      }
    }
  CHECK(ncclGinRsCsumBuf(3, base, 100) == 0 && ncclGinRsCsumBuf(NCCL_GIN_RS_CSUM_OFF, base, 100) == 0);
  // the documented amounts: 4 KiB reads 128 bytes sampled, 256 KiB reads 4 160 bytes (EXPERIMENT.md 9.5)
  CHECK(refBytesRead(1, 4096) == 128 && refBytesRead(1, 262144) == 4160 && refBytesRead(2, 262144) == 262144);
  // detection: a changed byte in a sampled word changes both schemes; outside them only the full one
  std::vector<uint8_t> buf(262144);
  for (auto& c : buf) c = (uint8_t)rng();
  const uint32_t s0 = ncclGinRsCsumBuf(1, buf.data(), buf.size()), f0 = ncclGinRsCsumBuf(2, buf.data(), buf.size());
  int sampledHit = 0, sampledMiss = 0;
  for (int t = 0; t < 3000; t++) {
    const uint64_t pos = rng() % buf.size();
    const uint8_t old = buf[pos];
    buf[pos] = (uint8_t)(old ^ (1u + rng() % 255));
    const uint64_t j = pos / 4, n = buf.size() / 4;
    const bool sampled = (j % 1024) < 16 || j + 16 >= n;
    const uint32_t s1 = ncclGinRsCsumBuf(1, buf.data(), buf.size()), f1 = ncclGinRsCsumBuf(2, buf.data(), buf.size());
    CHECK(f1 != f0);  // one word changed: always caught
    if (sampled) { CHECK(s1 != s0); sampledHit++; }
    else { CHECK(s1 == s0); sampledMiss++; }
    buf[pos] = old;
  }
  CHECK(sampledMiss > 0);
  for (int t = 0; t < 64; t++) {  // the sampled positions themselves
    const uint64_t pos = (rng() % 64) * 4096 + rng() % 64;
    buf[pos] ^= 0x5a;
    CHECK(ncclGinRsCsumBuf(1, buf.data(), buf.size()) != s0);
    buf[pos] ^= 0x5a;
  }
  for (int t = 0; t < 2000; t++) {  // two different words swapped: the position tag catches it (full)
    const uint64_t a = rng() % (buf.size() / 4), b = rng() % (buf.size() / 4);
    uint32_t wa, wb;
    memcpy(&wa, &buf[4 * a], 4);
    memcpy(&wb, &buf[4 * b], 4);
    if (a == b || wa == wb) continue;
    memcpy(&buf[4 * a], &wb, 4);
    memcpy(&buf[4 * b], &wa, 4);
    CHECK(ncclGinRsCsumBuf(2, buf.data(), buf.size()) != f0);
    memcpy(&buf[4 * a], &wa, 4);
    memcpy(&buf[4 * b], &wb, 4);
  }
  // a whole-buffer overwrite with new data (the usual reuse) is caught by the sampled scheme
  for (int t = 0; t < 200; t++) {
    std::vector<uint8_t> nb(buf.size());
    for (auto& c : nb) c = (uint8_t)rng();
    CHECK(ncclGinRsCsumBuf(1, nb.data(), nb.size()) != s0);
  }
  (void)sampledHit;
  (void)walks;
}
static void testCsumScheme() {
  uint32_t s = 9;
  CHECK(gdakiRsCsumSchemeOf(nullptr, &s) && s == NCCL_GIN_RS_CSUM_OFF);
  CHECK(gdakiRsCsumSchemeOf("", &s) && s == NCCL_GIN_RS_CSUM_OFF);
  CHECK(gdakiRsCsumSchemeOf("off", &s) && s == NCCL_GIN_RS_CSUM_OFF);
  CHECK(gdakiRsCsumSchemeOf("0", &s) && s == NCCL_GIN_RS_CSUM_OFF);
  CHECK(gdakiRsCsumSchemeOf("sampled", &s) && s == NCCL_GIN_RS_CSUM_SAMPLED);
  CHECK(gdakiRsCsumSchemeOf("1", &s) && s == NCCL_GIN_RS_CSUM_SAMPLED);
  CHECK(gdakiRsCsumSchemeOf("full", &s) && s == NCCL_GIN_RS_CSUM_FULL);
  CHECK(gdakiRsCsumSchemeOf("2", &s) && s == NCCL_GIN_RS_CSUM_FULL);
  CHECK(!gdakiRsCsumSchemeOf("Full", &s) && s == NCCL_GIN_RS_CSUM_OFF);
  CHECK(!gdakiRsCsumSchemeOf("3", &s) && s == NCCL_GIN_RS_CSUM_OFF);
  CHECK(strcmp(gdakiRsCsumName(NCCL_GIN_RS_CSUM_SAMPLED), "sampled") == 0 && strcmp(gdakiRsCsumName(7), "off") == 0);
}
// The entry's layout as impl/rs_log_api.h's table (byte offsets), the side table's header and QP entry the host reads, and
// the identity word: position low 32 bits, qp 24 bits, kind 2 bits, flags 6 bits, in one little-endian 8-byte word.
static void testEntryLayout() {
  CHECK(sizeof(struct ncclGinRsLogEntry) == 64 && offsetof(struct ncclGinRsLogEntry, pos) == 0 &&
        offsetof(struct ncclGinRsLogEntry, qpKf) == 4 && offsetof(struct ncclGinRsLogEntry, csum) == 8 &&
        offsetof(struct ncclGinRsLogEntry, sigWin) == 12 && offsetof(struct ncclGinRsLogEntry, dstWin) == 16 &&
        offsetof(struct ncclGinRsLogEntry, srcWin) == 20 && offsetof(struct ncclGinRsLogEntry, dstOff) == 24 &&
        offsetof(struct ncclGinRsLogEntry, bytes) == 32 && offsetof(struct ncclGinRsLogEntry, src) == 40 &&
        offsetof(struct ncclGinRsLogEntry, sigOff) == 48 && offsetof(struct ncclGinRsLogEntry, sigVal) == 56);
  CHECK(sizeof(struct ncclGinRsQp) == 128 && sizeof(struct ncclGinRsSide) == 128);
  CHECK(offsetof(struct ncclGinRsSide, csum) == 16 && offsetof(struct ncclGinRsSide, nEntries) == 20 &&
        offsetof(struct ncclGinRsSide, entries) == 24 && offsetof(struct ncclGinRsSide, head) == 64 &&
        offsetof(struct ncclGinRsSide, tail) == 72 && offsetof(struct ncclGinRsSide, ovfCount) == 80);
  CHECK(offsetof(struct ncclGinRsQp, msgs) == 0 && offsetof(struct ncclGinRsQp, suppress) == 8 &&
        offsetof(struct ncclGinRsQp, ovfCount) == 16 && offsetof(struct ncclGinRsQp, ovfHead) == 24 &&
        offsetof(struct ncclGinRsQp, logOn) == 32 && offsetof(struct ncclGinRsQp, getRefused) == 36 &&
        offsetof(struct ncclGinRsQp, gets) == 40);
  CHECK(sizeof(struct ncclGinGdakiMemHandle) == 24 && offsetof(struct ncclGinGdakiMemHandle, lkey) == 8);
  // the flag bits: three flags below the 2-bit scheme field, all within 6 bits
  CHECK(((NCCL_GIN_RS_LOGF_SIGNAL | NCCL_GIN_RS_LOGF_SPLIT | NCCL_GIN_RS_LOGF_NOBASE) >> NCCL_GIN_RS_LOGF_CSUM_SHIFT) == 0);
  CHECK(((NCCL_GIN_RS_CSUM_FULL << NCCL_GIN_RS_LOGF_CSUM_SHIFT) | 7u) < 64u);
  // the identity word as a struct and as a word (the device writes the word, the host reads the struct)
  std::mt19937_64 rng(7);
  for (int t = 0; t < 20000; t++) {
    const uint64_t pos = rng();
    const uint32_t qp = (uint32_t)(rng() & NCCL_GIN_RS_QP_MASK), kind = 1 + (uint32_t)(rng() % 3),
                   flags = (uint32_t)(rng() & 0x3f);
    const uint32_t kf = ncclGinRsQpKf(qp, kind, flags);
    const uint64_t w = ncclGinRsIdWord(pos, kf);
    struct ncclGinRsLogEntry e;
    memset(&e, 0, sizeof(e));
    memcpy(&e, &w, 8);
    CHECK(e.pos == (uint32_t)pos && e.qpKf == kf);
    CHECK(ncclGinRsEntryQp(e.qpKf) == qp && ncclGinRsEntryKind(e.qpKf) == kind && ncclGinRsEntryFlags(e.qpKf) == flags);
    CHECK(ncclGinRsIdIs(w, pos) && !ncclGinRsIdIs(w, pos + 1) && !ncclGinRsIdIs(w, pos - 4096) &&
          !ncclGinRsIdIs(w, pos + (1ull << 20)));
  }
  CHECK(ncclGinRsQpKf(0x1abcdef, 1, 0) == (0xabcdefu | (1u << 24)));  // a qp past 24 bits is cut (the layout refuses it)
  // a zeroed slot (the ring starts zeroed) is no position's entry, position 0's included (review of the redo, finding 1);
  // an identity word of kind 0 never matches
  CHECK(!ncclGinRsIdIs(0, 0) && !ncclGinRsIdIs(0, 1ull << 32) && !ncclGinRsIdIs(ncclGinRsIdWord(5, ncclGinRsQpKf(3, 0, 1)), 5));
  CHECK(ncclGinRsIdIs(ncclGinRsIdWord(0, ncclGinRsQpKf(0, NCCL_GIN_RS_LOG_PUT, 0)), 0));
  // the second and third words as the device writes them, read as the struct
  for (int t = 0; t < 2000; t++) {
    const uint32_t csum = (uint32_t)rng(), sw = (uint32_t)rng(), dw = (uint32_t)rng(), srw = (uint32_t)rng();
    uint64_t w[8] = {ncclGinRsIdWord(t, ncclGinRsQpKf(1, NCCL_GIN_RS_LOG_PUT, 1)), ncclGinRsWord1(csum, sw),
                     ncclGinRsWord2(dw, srw), 11, 22, 33, 44, 55};
    struct ncclGinRsLogEntry e;
    memcpy(&e, w, sizeof(e));
    CHECK(e.csum == csum && e.sigWin == sw && e.dstWin == dw && e.srcWin == srw && e.dstOff == 11 && e.bytes == 22 &&
          e.src == 33 && e.sigOff == 44 && e.sigVal == 55 && e.pos == (uint32_t)t);
  }
  // the request messages of an entry (9.6's units), from kind, flags and bytes
  const uint64_t G = 1ull << 30;
  CHECK(ncclGinRsEntryMsgs(ncclGinRsQpKf(3, NCCL_GIN_RS_LOG_PUT, 0), 4096) == 1);
  CHECK(ncclGinRsEntryMsgs(ncclGinRsQpKf(3, NCCL_GIN_RS_LOG_PUT, NCCL_GIN_RS_LOGF_SIGNAL), 4096) == 2);
  CHECK(ncclGinRsEntryMsgs(ncclGinRsQpKf(3, NCCL_GIN_RS_LOG_PUT, NCCL_GIN_RS_LOGF_SIGNAL), 0) == 1);
  CHECK(ncclGinRsEntryMsgs(ncclGinRsQpKf(3, NCCL_GIN_RS_LOG_PUT, NCCL_GIN_RS_LOGF_SIGNAL | NCCL_GIN_RS_LOGF_SPLIT),
                           2 * G + 1) == 4);
  CHECK(ncclGinRsEntryMsgs(ncclGinRsQpKf(3, NCCL_GIN_RS_LOG_PUTVALUE, 0), 8) == 1);
  CHECK(ncclGinRsEntryMsgs(ncclGinRsQpKf(3, NCCL_GIN_RS_LOG_PUTVALUE, NCCL_GIN_RS_LOGF_SIGNAL), 8) == 2);
  CHECK(ncclGinRsEntryMsgs(ncclGinRsQpKf(3, NCCL_GIN_RS_LOG_SIGNAL, NCCL_GIN_RS_LOGF_SIGNAL), 0) == 1);
  // what the device logs for each plan (rsPutHold: kind PUT with the posted bytes, or SIGNAL when the data was held back)
  // has exactly the plan's posted messages
  for (int hs = 0; hs < 2; hs++)
    for (uint64_t bytes : {(uint64_t)0, (uint64_t)8, (uint64_t)4096, G, G + 1, 3 * G})
      for (uint64_t skip = 0; skip <= 5; skip++) {
        const struct ncclGinRsPlan pl = ncclGinRsPlanOf(true, bytes, hs != 0, skip);
        if (pl.all || pl.mPost == 0) continue;
        const uint32_t kind = pl.postData ? NCCL_GIN_RS_LOG_PUT : NCCL_GIN_RS_LOG_SIGNAL;
        const uint32_t kf = ncclGinRsQpKf(1, kind, (hs ? NCCL_GIN_RS_LOGF_SIGNAL : 0u) | (skip ? NCCL_GIN_RS_LOGF_SPLIT : 0u));
        CHECK(ncclGinRsEntryMsgs(kf, pl.postData ? bytes - pl.adv : 0) == pl.mPost);
      }
}
// The suppression plan against an explicit list of the operation's messages: chunks of 1 GiB (or one NOP for 0 bytes,
// not a message), then the signal; the first `skip` are held back.
static void testPlan() {
  const uint64_t G = 1ull << 30;
  CHECK(ncclGinRsDataMsgs(true, 0) == 0 && ncclGinRsDataMsgs(true, 1) == 1 && ncclGinRsDataMsgs(true, G) == 1 &&
        ncclGinRsDataMsgs(true, G + 1) == 2 && ncclGinRsDataMsgs(false, 4096) == 0);
  CHECK(ncclGinRsTake(0, 2) == 0 && ncclGinRsTake(1, 2) == 1 && ncclGinRsTake(5, 2) == 2 && ncclGinRsTake(5, 0) == 0);
  const uint64_t sizes[] = {0, 1, 8, 4096, 262144, G - 1, G, G + 1, 3 * G, 5 * G + 7};
  for (int hd = 0; hd < 2; hd++)
    for (uint64_t bytes : sizes)
      for (int hs = 0; hs < 2; hs++) {
        std::vector<int> msgs;  // 1 = a data chunk, 2 = the signal
        const uint64_t nChunks = hd ? (bytes + G - 1) / G : 0;
        for (uint64_t c = 0; c < nChunks; c++) msgs.push_back(1);
        if (hs) msgs.push_back(2);
        for (uint64_t skip = 0; skip <= msgs.size() + 1; skip++) {
          const struct ncclGinRsPlan pl = ncclGinRsPlanOf(hd != 0, bytes, hs != 0, skip);
          const uint64_t k = std::min<uint64_t>(skip, msgs.size());
          const uint64_t chunksLeft = nChunks > k ? nChunks - k : 0;
          CHECK(pl.m == msgs.size());
          CHECK(pl.mPost == msgs.size() - k);
          CHECK(pl.all == (k > 0 && k == msgs.size()));
          const bool wantData = hd && (chunksLeft > 0 || (nChunks == 0 && k == 0));  // a 0-byte put's NOP only if nothing held
          CHECK(pl.postData == wantData);
          CHECK(pl.adv == ((k > 0 && chunksLeft > 0) ? k * G : 0));
          if (pl.postData && bytes > 0) CHECK(bytes - pl.adv == (chunksLeft == nChunks ? bytes : bytes - k * G));
        }
      }
  // the units of EXPERIMENT.md 9.6 (data 1 below 1 GiB, signal 1, 0-byte put 0, putValue 1): put+signal with budget 1 posts
  // only the signal; a putValue is a one-chunk put
  struct ncclGinRsPlan pl = ncclGinRsPlanOf(true, 4096, true, 1);
  CHECK(!pl.postData && !pl.all && pl.mPost == 1);
  pl = ncclGinRsPlanOf(true, 0, true, 1);
  CHECK(pl.all && pl.m == 1);
  pl = ncclGinRsPlanOf(true, 0, false, 0);
  CHECK(!pl.all && pl.postData && pl.mPost == 0 && pl.m == 0);
  pl = ncclGinRsPlanOf(true, sizeof(uint64_t), false, 1);
  CHECK(pl.all && pl.m == 1);
  pl = ncclGinRsPlanOf(false, 0, true, 0);
  CHECK(!pl.postData && pl.mPost == 1);
}
// The ring (one per context, shared by every QP): rsLogPut's reservation as a model (the same fit rule and identity word):
// read the head, then the tail; take position h with a CAS only if it fits, else count an overflow and take nothing.
struct RingModel {
  uint32_t n;
  std::atomic<uint64_t> head{0}, tail{0}, ovf{0};
  std::vector<std::atomic<uint64_t>> slot;  // identity words
  std::vector<std::atomic<uint32_t>> writes;  // writes per position (test bookkeeping)
  explicit RingModel(uint32_t n_, size_t maxPos) : n(n_), slot(n_), writes(maxPos) {
    for (auto& w : slot) w.store(0);  // the library zeroes the ring (gdakiRsStart)
    for (auto& c : writes) c.store(0);
  }
  // returns the position taken, or ~0 on overflow
  uint64_t post(uint32_t qp, bool* clobber) {
    uint64_t h = head.load(std::memory_order_relaxed);
    for (;;) {
      if (!ncclGinRsLogFits(h, tail.load(std::memory_order_relaxed), n)) {
        ovf.fetch_add(1);
        return ~0ull;
      }
      if (head.compare_exchange_strong(h, h + 1)) break;
    }
    // the slot's old entry must not be kept any more: its position is below the tail the CAS saw room under
    const uint64_t old = slot[h & (n - 1)].load();
    if (old != 0 && !ncclGinRsIdIs(old, h - n)) *clobber = true;  // gapless: the slot held h - n (or nothing yet)
    slot[h & (n - 1)].store(ncclGinRsIdWord(h, ncclGinRsQpKf(qp, NCCL_GIN_RS_LOG_PUT, 0)));
    writes[h].fetch_add(1);
    return h;
  }
};
static void testRing() {
  // single-threaded: random posts and tail moves; the tail only moves over positions already written (as the host does)
  std::mt19937 rng(42);
  for (int it = 0; it < 500; it++) {
    const uint32_t n = 1u << (1 + rng() % 5);
    RingModel m(n, 4000);
    uint64_t posted = 0, ovf = 0;
    bool clobber = false;
    for (int op = 0; op < 3000 && m.head.load() < 3990; op++) {
      if (rng() % 3 == 0) {
        const uint64_t h = m.head.load(), t = m.tail.load();
        if (h > t) m.tail.store(t + rng() % (h - t + 1));
      } else {
        if (m.post(rng() % 7, &clobber) == ~0ull) ovf++;
        else posted++;
      }
      CHECK(m.head.load() - m.tail.load() <= n);  // never more than n kept
    }
    CHECK(!clobber && m.ovf.load() == ovf && m.head.load() == posted);  // an overflow takes no position: no gap
    for (uint64_t p = 0; p < m.head.load(); p++) CHECK(m.writes[p].load() == 1);
    for (uint64_t p = m.tail.load(); p < m.head.load(); p++) CHECK(ncclGinRsIdIs(m.slot[p & (n - 1)].load(), p));
  }
  // threads: posters on several QPs and a host that moves the tail only over written positions it saw (identity words)
  for (int it = 0; it < 40; it++) {
    const uint32_t n = 1u << (2 + it % 6);
    const int nThreads = 4, perThread = 3000;
    RingModel m(n, (size_t)nThreads * perThread + 1);
    std::atomic<bool> stop{false}, clobber{false};
    std::atomic<uint64_t> posted{0};
    std::thread host([&] {
      while (!stop.load()) {
        const uint64_t t = m.tail.load(), h = m.head.load();
        uint64_t nt = t;
        while (nt < h && ncclGinRsIdIs(m.slot[nt & (n - 1)].load(), nt)) nt++;  // stops at a slot still being written
        if (nt != t) m.tail.store(nt);
      }
    });
    std::vector<std::thread> th;
    for (int k = 0; k < nThreads; k++)
      th.emplace_back([&, k] {
        bool c = false;
        for (int i = 0; i < perThread; i++)
          if (m.post((uint32_t)k, &c) != ~0ull) posted.fetch_add(1);
        if (c) clobber.store(true);
      });
    for (auto& x : th) x.join();
    stop.store(true);
    host.join();
    CHECK(!clobber.load());
    CHECK(m.head.load() == posted.load() && posted.load() + m.ovf.load() == (uint64_t)nThreads * perThread);
    for (uint64_t p = 0; p < m.head.load(); p++) CHECK(m.writes[p].load() == 1);
  }
  // the fit rule (signed: a stale head below a tail the measurement mode moved is not an overflow; the CAS then fails)
  CHECK(ncclGinRsLogFits(5, 6, 4) && ncclGinRsLogFits(5, 1000, 4) && ncclGinRsLogFits(0, 1, 64));
  CHECK(ncclGinRsLogFits(9, 6, 4) && !ncclGinRsLogFits(10, 6, 4) && !ncclGinRsLogFits(4096, 0, 4096));
  CHECK(ncclGinRsLogFits(4095, 0, 4096) && ncclGinRsLogFits((1ull << 40) + 3, (1ull << 40), 4));
}
// The readout's sums over a copy of the QP entries (the ring's head, tail and overflow count are the header's).
static void testSums() {
  struct ncclGinRsQp q[4];
  memset(q, 0, sizeof(q));
  const uint8_t logged[4] = {0, 1, 1, 1};
  q[0].msgs = 7;  // this rank's own QP: no log, but a message count
  q[1].msgs = 150;
  q[2].msgs = 1000, q[2].ovfCount = 3, q[2].ovfHead = 850;
  q[3].msgs = 9, q[3].getRefused = 1, q[3].ovfCount = 2;
  const struct gdakiRsSums t = gdakiRsSumsOf(q, 4, logged);
  CHECK(t.logged == 3 && t.msgs == 1166 && t.ovfOps == 5 && t.ovfQps == 2 && t.getRefused == 1);
}

// ---- work package 6: the host log state (model test) ----
// A model of the device ring (the reservation of rsLogPut: a position only when it fits; the identity word written at
// some later step, before the peer's next pause, which quiesces that peer's QPs) and of the host's calls (pauses,
// stables in order or late, polls with overflows and gets, tail advances), with the invariants checked after each step:
//   (1) the tail never passes an entry that is not covered;
//   (2) a peer whose log is complete (and whose QPs did not overflow since its cut) has every entry posted to it at or
//       after its cut still in the ring, and the peer filter finds exactly those;
//   (3) every logged entry below coveredUpTo is covered;
//   (4) liveness: with every peer pausing and turning stable, the tail follows the head.
struct LogModel {
  int nranks, nctx, nqp;
  uint32_t n;
  uint64_t head = 0, tail = 0;
  std::vector<uint64_t> slot;  // identity words
  std::vector<uint8_t> logOn;
  std::vector<uint64_t> ovf, gets, msgs;  // msgs: every post (logged or not), as the device's count
  struct Post { uint64_t pos; int qp; bool written; };
  std::vector<Post> posts;      // every logged post, by position
  LogModel(int r, int c, uint32_t n_) : nranks(r), nctx(c), nqp(r * c), n(n_), slot(n_, ~0ull), logOn(r * c, 0),
                                        ovf(r * c, 0), gets(r * c, 0), msgs(r * c, 0) {}
  int peerOf(int qp) const { return qp % nranks; }
  void post(int qp) {
    msgs[(size_t)qp]++;
    if (!logOn[(size_t)qp]) return;
    if (!ncclGinRsLogFits(head, tail, n)) { ovf[(size_t)qp]++; return; }
    posts.push_back({head, qp, false});
    head++;
  }
  void write(Post& p) {
    if (p.written) return;
    slot[(size_t)(p.pos & (n - 1))] = ncclGinRsIdWord(p.pos, ncclGinRsQpKf((uint32_t)p.qp, NCCL_GIN_RS_LOG_PUT, 0));
    p.written = true;
  }
  void quiesce(int peer) {  // a pause: every post to the peer's QPs has written its entry
    for (auto& p : posts) if (peerOf(p.qp) == peer) write(p);
  }
  bool readIds(uint64_t from, uint64_t to, uint64_t* ids) const {
    for (uint64_t p = from; p < to; p++) ids[p - from] = slot[(size_t)(p & (n - 1))];
    return true;
  }
};
static void testLogState() {
  std::mt19937_64 rng(6);
  int completeChecks = 0, lateStables = 0, breaks = 0, getsSeen = 0, msgsChecks = 0, laterChecks = 0;
  for (int it = 0; it < 600; it++) {
    const int nranks = 2 + (int)(rng() % 3), nctx = 1 + (int)(rng() % 3);
    const uint32_t n = 1u << (3 + rng() % 4);
    LogModel m(nranks, nctx, n);
    const int self = (int)(rng() % nranks);
    struct gdakiRsLogState L;
    gdakiRsLogStateInit(&L, n, m.nqp, nranks);
    std::vector<std::vector<std::vector<struct gdakiRsPauseSnap>>> pending((size_t)nranks);  // per peer: pauses waiting
    std::vector<std::vector<int>> qpsOf((size_t)nranks);
    for (int c = 0; c < nctx; c++)
      for (int p = 0; p < nranks; p++) if (p != self) qpsOf[(size_t)p].push_back(c * nranks + p);
    const bool steady = rng() % 3 == 0;  // every peer pauses and turns stable often: liveness
    std::map<std::pair<int, uint64_t>, uint64_t> msgsAtPause;  // (qp, head) -> the message count that pause read
    uint64_t maxLag = 0;
    for (int op = 0; op < 1500; op++) {
      const int r = (int)(rng() % 100);
      if (r < 50) {  // a post to a random QP of a peer
        int p = (int)(rng() % nranks);
        if (p == self) continue;
        m.post(qpsOf[(size_t)p][rng() % qpsOf[(size_t)p].size()]);
      } else if (r < 58) {  // some in-flight entries land
        for (auto& p : m.posts) if (!p.written && rng() % 2) m.write(p);
      } else if (r < 61) {  // a get on a random QP
        int p = (int)(rng() % nranks);
        if (p == self || steady) continue;
        m.gets[(size_t)qpsOf[(size_t)p][0]]++;
      } else if (r < 72) {  // a pause toward a peer
        int p = (int)(rng() % nranks);
        if (p == self) continue;
        m.quiesce(p);
        const auto& qs = qpsOf[(size_t)p];
        std::vector<uint64_t> ov, gt, ms;
        std::vector<struct gdakiRsPauseSnap> snap;
        for (int q : qs) {
          m.logOn[(size_t)q] = 1;
          ov.push_back(m.ovf[(size_t)q]);
          gt.push_back(m.gets[(size_t)q]);
          ms.push_back(m.msgs[(size_t)q]);
          msgsAtPause[std::make_pair(q, m.head)] = m.msgs[(size_t)q];
          struct gdakiRsPauseSnap s; s.head = m.head; s.ovf = m.ovf[(size_t)q]; s.gets = m.gets[(size_t)q]; s.valid = true;
          snap.push_back(s);
        }
        gdakiRsLogStateNotePause(&L, qs.data(), (int)qs.size(), m.head, ov.data(), gt.data(), ms.data());
        pending[(size_t)p].push_back(snap);
      } else if (r < 84) {  // a peer's checkpoint turns stable: usually the oldest pending, sometimes a later one first
        int p = (int)(rng() % nranks);
        if (p == self || pending[(size_t)p].empty()) continue;
        size_t k = (rng() % 4 == 0) ? (size_t)(rng() % pending[(size_t)p].size()) : 0;
        if (k != 0) lateStables++;
        const auto& qs = qpsOf[(size_t)p];
        std::vector<uint64_t> on;
        for (int q : qs) on.push_back(m.ovf[(size_t)q]);
        breaks += gdakiRsLogStateNoteStable(&L, qs.data(), (int)qs.size(), pending[(size_t)p][k].data(), on.data());
        pending[(size_t)p].erase(pending[(size_t)p].begin() + (long)k);  // the older ones may still come (late)
      } else {  // the poll: counts, then the tail's advance
        for (int q = 0; q < m.nqp; q++) {
          bool gotGet = false;
          if (gdakiRsLogStateNoteCounts(&L, q, m.ovf[(size_t)q], m.gets[(size_t)q], &gotGet)) breaks++;
          if (gotGet) getsSeen++;
        }
        const uint64_t old = L.tail;
        bool failed = false;
        const uint64_t t = gdakiRsLogStateAdvance(&L, m.head, 1 + rng() % 9,
                                                  [&](uint64_t a, uint64_t b, uint64_t* ids) { return m.readIds(a, b, ids); },
                                                  &failed);
        CHECK(!failed && t >= old && t <= m.head);
        // (1) every position the tail passed now held a written entry that was covered then
        for (uint64_t s = old; s < t; s++) {
          bool found = false;
          for (const auto& p : m.posts)
            if (p.pos == s) {
              found = true;
              CHECK(p.written);
              CHECK(gdakiRsLogQpCovers(L.qp[(size_t)p.qp], s));
            }
          CHECK(found);
        }
        m.tail = t;  // the host writes the tail
        // after a poll: a peer the state calls complete lost nothing and had no get since its cut (review of work package
        // 6, finding 1: an overflow first seen by a pause or a stable was never reported)
        for (int p = 0; p < nranks; p++) {
          if (p == self || !gdakiRsLogStateComplete(&L, p)) continue;
          for (int q : qpsOf[(size_t)p]) {
            const auto& s = L.qp[(size_t)q];
            if (s.logs) CHECK(m.ovf[(size_t)q] == s.ovfAtCut && m.gets[(size_t)q] == s.getsAtCut);
          }
        }
      }
      if (steady && op % 20 == 19) {  // pause and stabilize every peer
        for (int p = 0; p < nranks; p++) {
          if (p == self) continue;
          m.quiesce(p);
          const auto& qs = qpsOf[(size_t)p];
          std::vector<uint64_t> ov, gt, ms;
          std::vector<struct gdakiRsPauseSnap> snap;
          for (int q : qs) {
            m.logOn[(size_t)q] = 1;
            ov.push_back(m.ovf[(size_t)q]);
            gt.push_back(m.gets[(size_t)q]);
            ms.push_back(m.msgs[(size_t)q]);
            msgsAtPause[std::make_pair(q, m.head)] = m.msgs[(size_t)q];
            struct gdakiRsPauseSnap s; s.head = m.head; s.ovf = m.ovf[(size_t)q]; s.gets = m.gets[(size_t)q]; s.valid = true;
            snap.push_back(s);
          }
          gdakiRsLogStateNotePause(&L, qs.data(), (int)qs.size(), m.head, ov.data(), gt.data(), ms.data());
          gdakiRsLogStateNoteStable(&L, qs.data(), (int)qs.size(), snap.data(), ov.data());
          pending[(size_t)p].clear();
        }
        for (auto& p : m.posts) m.write(p);
        bool failed = false;
        m.tail = gdakiRsLogStateAdvance(&L, m.head, 8,
                                        [&](uint64_t a, uint64_t b, uint64_t* ids) { return m.readIds(a, b, ids); }, &failed);
        maxLag = std::max<uint64_t>(maxLag, m.head - m.tail);
      }
      // (2) a complete peer: its entries since its cut are all in the ring and the filter finds them
      for (int p = 0; p < nranks; p++) {
        if (p == self || !gdakiRsLogStateComplete(&L, p)) continue;
        bool noOvf = true;
        uint64_t cut = ~0ull;
        for (int q : qpsOf[(size_t)p]) {
          const auto& s = L.qp[(size_t)q];
          if (!s.logs) continue;
          if (m.ovf[(size_t)q] != s.ovfAtCut || m.gets[(size_t)q] != s.getsAtCut) noOvf = false;  // not seen by a poll yet
          if (cut == ~0ull) cut = s.cut;
          CHECK(s.cut == cut);  // every QP of the peer has the same cut (one pause)
        }
        if (!noOvf) continue;  // the poll has not seen this overflow or get yet: the export re-reads the counts
        completeChecks++;
        CHECK(cut >= m.tail || [&] {  // nothing of the peer below the tail at or after its cut
          for (const auto& x : m.posts) if (m.peerOf(x.qp) == p && x.pos >= cut && x.pos < m.tail) return false;
          return true;
        }());
        const uint64_t from = std::max(cut, m.tail);
        std::vector<uint64_t> ids((size_t)(m.head - from));
        m.quiesce(p);
        m.readIds(from, m.head, ids.data());
        const std::vector<uint64_t> got = gdakiRsLogStatePeerPositions(&L, p, from, m.head, ids.data());
        std::vector<uint64_t> want;
        for (const auto& x : m.posts) if (m.peerOf(x.qp) == p && x.pos >= cut) want.push_back(x.pos);
        CHECK(got == want);
        // work package 9: M at the cut's pause is kept, and the entries since the cut are exactly M now minus M then (every
        // post since the cut is logged: none overflowed)
        for (int q : qpsOf[(size_t)p]) {
          if (!L.qp[(size_t)q].logs) continue;
          uint64_t mc = 0;
          const bool kept = gdakiRsLogStateMsgsAt(&L, q, cut, &mc);
          CHECK(kept && mc == msgsAtPause[std::make_pair(q, cut)]);
          uint64_t since = 0;
          for (const auto& x : m.posts) if (x.qp == q && x.pos >= cut) since++;
          CHECK(kept && since == m.msgs[(size_t)q] - mc);
          msgsChecks++;
        }
        // and at every later pause of the peer still pending (a checkpoint confirmed but not yet stable: the host branch
        // may export from its cut; review of work package 9, note 5)
        for (const auto& snap : pending[(size_t)p]) {
          for (size_t k = 0; k < snap.size(); k++) {
            const int q = qpsOf[(size_t)p][k];
            if (!L.qp[(size_t)q].logs || snap[k].head < cut) continue;
            uint64_t mc = 0;
            CHECK(gdakiRsLogStateMsgsAt(&L, q, snap[k].head, &mc) && mc == msgsAtPause[std::make_pair(q, snap[k].head)]);
            laterChecks++;
          }
        }
        std::vector<uint64_t> ovn, gtn;
        for (int q : qpsOf[(size_t)p]) { ovn.push_back(m.ovf[(size_t)q]); gtn.push_back(m.gets[(size_t)q]); }
        char w[160];
        const auto& qs = qpsOf[(size_t)p];
        CHECK(gdakiRsLogStateCanExport(&L, qs.data(), (int)qs.size(), cut, ovn.data(), gtn.data(), w, sizeof(w)));
        CHECK(gdakiRsLogStateCanExport(&L, qs.data(), (int)qs.size(), m.head, ovn.data(), gtn.data(), w, sizeof(w)));
        if (cut > 0) CHECK(!gdakiRsLogStateCanExport(&L, qs.data(), (int)qs.size(), cut - 1, ovn.data(), gtn.data(), w,
                                                     sizeof(w)));
        ovn[0]++;  // an overflow since the cut
        CHECK(!gdakiRsLogStateCanExport(&L, qs.data(), (int)qs.size(), cut, ovn.data(), gtn.data(), w, sizeof(w)));
        ovn[0]--;
        gtn[0]++;  // a get since the cut
        CHECK(!gdakiRsLogStateCanExport(&L, qs.data(), (int)qs.size(), cut, ovn.data(), gtn.data(), w, sizeof(w)));
      }
      // (3) the covered position
      const uint64_t cov = L.coveredUpTo.load();
      for (const auto& x : m.posts)
        if (x.pos < cov && x.pos >= m.tail) CHECK(gdakiRsLogQpCovers(L.qp[(size_t)x.qp], x.pos));
    }
    if (steady) CHECK(maxLag <= (uint64_t)n);  // (4) the tail follows the head (bounded by the ring)
  }
  CHECK(completeChecks > 1000 && lateStables > 50 && breaks > 50 && getsSeen > 20 && msgsChecks > 1000 &&
        laterChecks > 1000);
  printf("log state model: %d complete-peer checks, %d late stables, %d breaks, %d gets, %d message counts at the cut, %d "
         "at later pauses\n", completeChecks, lateStables, breaks, getsSeen, msgsChecks, laterChecks);
  // the stable step
  const uint64_t NONE = ~0ull, steps[] = {3, 4, 5, 6}, heads[] = {10, 20, 20, 35};
  CHECK(gdakiRsStableStepOf(steps, heads, 4, 9, NONE) == NONE);
  CHECK(gdakiRsStableStepOf(steps, heads, 4, 10, NONE) == 3);
  CHECK(gdakiRsStableStepOf(steps, heads, 4, 34, NONE) == 5);
  CHECK(gdakiRsStableStepOf(steps, heads, 4, ~0ull, NONE) == 6);
  CHECK(gdakiRsStableStepOf(steps, heads, 0, 100, NONE) == NONE);
}


// ---- work package 9: executed counts, budgets, the export's stream, the import plan ----
static void testExec() {
  std::mt19937_64 rng(9);
  for (int it = 0; it < 200; it++) {
    struct gdakiRsExecQp e;
    uint32_t rmsn = (uint32_t)(rng() & 0xffffff);
    uint64_t truth = 0;
    gdakiRsExecStepQp(e, rmsn | 0x5a000000u);  // the first read only sets `last` (high bits are not the MSN's)
    CHECK(e.on && e.cum == 0 && e.last == rmsn);
    for (int s = 0; s < 300; s++) {
      const int r = (int)(rng() % 10);
      if (r == 0) {  // a Commit and its Baseline: a new connection whose MSN starts anywhere (2RST may not zero it)
        rmsn = (uint32_t)(rng() & 0xffffff);
        gdakiRsExecRebaseQp(e, rmsn);
        CHECK(e.cum == truth && e.last == rmsn);
        continue;
      }
      const uint64_t d = r == 1 ? (1u << 23) - 1 : rng() % 5000;  // at most 2^23 - 1 between two reads
      rmsn = (rmsn + (uint32_t)d) & 0xffffffu;
      truth += d;
      gdakiRsExecStepQp(e, rmsn);
      CHECK(e.cum == truth);
    }
  }
  uint64_t b = 7;
  CHECK(gdakiRsBudgetOf(10, 4, &b) && b == 6);
  CHECK(gdakiRsBudgetOf(4, 4, &b) && b == 0);
  b = 7;
  CHECK(!gdakiRsBudgetOf(3, 4, &b) && b == 7);
}
static struct ncclGinRsLogEntry entryOf(uint32_t qp, uint32_t kind, uint32_t flags, uint32_t dstWin, uint32_t srcWin,
                                        uint64_t dstOff, uint64_t bytes, uint64_t src, uint32_t sigWin, uint64_t sigOff,
                                        uint64_t sigVal) {
  struct ncclGinRsLogEntry e;
  memset(&e, 0, sizeof(e));
  e.qpKf = ncclGinRsQpKf(qp, kind, flags);
  e.dstWin = dstWin, e.srcWin = srcWin, e.dstOff = dstOff, e.bytes = bytes, e.src = src;
  e.sigWin = sigWin, e.sigOff = sigOff, e.sigVal = sigVal;
  return e;
}
static void testEntryCheck() {
  const uint32_t S = NCCL_GIN_RS_LOGF_SIGNAL;
  CHECK(gdakiRsEntryCheck(entryOf(1, NCCL_GIN_RS_LOG_PUT, 0, 2, 3, 0, 100, 0, 0, 0, 0)) == nullptr);
  CHECK(gdakiRsEntryCheck(entryOf(1, NCCL_GIN_RS_LOG_PUT, S, 2, 3, 0, 0, 0, 0, 8, 1)) == nullptr);  // 0 bytes + signal
  CHECK(gdakiRsEntryCheck(entryOf(1, NCCL_GIN_RS_LOG_PUT, 0, 0, 3, 0, 100, 0, 0, 0, 0)) != nullptr);
  CHECK(gdakiRsEntryCheck(entryOf(1, NCCL_GIN_RS_LOG_PUT, 0, 2, 0, 0, 100, 0, 0, 0, 0)) != nullptr);
  CHECK(gdakiRsEntryCheck(entryOf(1, NCCL_GIN_RS_LOG_PUT, 0, 2, 3, 0, (1ull << 40) + 1, 0, 0, 0, 0)) != nullptr);
  CHECK(gdakiRsEntryCheck(entryOf(1, NCCL_GIN_RS_LOG_PUTVALUE, 0, 2, 0, 0, 8, 9, 0, 0, 0)) == nullptr);
  CHECK(gdakiRsEntryCheck(entryOf(1, NCCL_GIN_RS_LOG_PUTVALUE, 0, 2, 0, 0, 9, 9, 0, 0, 0)) != nullptr);
  CHECK(gdakiRsEntryCheck(entryOf(1, NCCL_GIN_RS_LOG_PUTVALUE, 0, 2, 0, 0, 0, 9, 0, 0, 0)) != nullptr);
  CHECK(gdakiRsEntryCheck(entryOf(1, NCCL_GIN_RS_LOG_PUTVALUE, 0, 0, 0, 0, 4, 9, 0, 0, 0)) != nullptr);
  CHECK(gdakiRsEntryCheck(entryOf(1, NCCL_GIN_RS_LOG_SIGNAL, S, 0, 0, 0, 0, 0, 5, 16, 2)) == nullptr);
  CHECK(gdakiRsEntryCheck(entryOf(1, NCCL_GIN_RS_LOG_SIGNAL, 0, 0, 0, 0, 0, 0, 5, 16, 2)) != nullptr);
  CHECK(gdakiRsEntryCheck(entryOf(1, 0, S, 0, 0, 0, 0, 0, 5, 16, 2)) != nullptr);
  // the scheme an entry was counted with
  const uint32_t full = NCCL_GIN_RS_CSUM_FULL << NCCL_GIN_RS_LOGF_CSUM_SHIFT;
  CHECK(gdakiRsEntryCsumScheme(ncclGinRsQpKf(3, NCCL_GIN_RS_LOG_PUT, full | S)) == NCCL_GIN_RS_CSUM_FULL);
  CHECK(gdakiRsEntryCsumScheme(ncclGinRsQpKf(3, NCCL_GIN_RS_LOG_PUT, full | NCCL_GIN_RS_LOGF_NOBASE)) ==
        NCCL_GIN_RS_CSUM_OFF);
  CHECK(gdakiRsEntryCsumScheme(ncclGinRsQpKf(3, NCCL_GIN_RS_LOG_PUTVALUE, full)) == NCCL_GIN_RS_CSUM_OFF);
  CHECK(gdakiRsEntryCsumScheme(ncclGinRsQpKf(3, NCCL_GIN_RS_LOG_PUT, 0)) == NCCL_GIN_RS_CSUM_OFF);
}
// The chunked count equals the device's walk over the whole data, for chunk sizes and orders the export may use.
static void testCsumChunk() {
  std::mt19937_64 rng(91);
  int n = 0;
  for (int it = 0; it < 3000; it++) {
    const uint64_t bytes = 1 + (it < 1500 ? rng() % 300 : rng() % 40000);
    std::vector<uint8_t> d((size_t)bytes);
    for (auto& c : d) c = (uint8_t)rng();
    const uint32_t scheme = (it & 1) ? NCCL_GIN_RS_CSUM_FULL : NCCL_GIN_RS_CSUM_SAMPLED;
    const uint32_t want = ncclGinRsCsumWalk(scheme, d.data(), bytes, ncclGinRsCsumHostLoad());
    const uint64_t chunk = 4 * (1 + rng() % 2048);
    std::vector<uint64_t> offs;
    for (uint64_t o = 0; o < bytes; o += chunk) offs.push_back(o);
    std::shuffle(offs.begin(), offs.end(), rng);
    uint32_t a = 0, b = 0;
    bool ok = true;
    for (uint64_t o : offs) {
      const uint64_t len = std::min<uint64_t>(chunk, bytes - o);
      std::vector<uint8_t> buf(d.begin() + (long)o, d.begin() + (long)(o + len));  // a staging buffer of its own
      ok = ok && gdakiRsCsumChunk(scheme, bytes, o, buf.data(), len, a, b);
    }
    CHECK(ok && ncclGinRsCsumFinal(a, b, bytes, scheme) == want);
    n++;
  }
  uint32_t a = 0, b = 0;
  uint8_t z[16] = {0};
  CHECK(!gdakiRsCsumChunk(NCCL_GIN_RS_CSUM_FULL, 16, 2, z, 4, a, b));   // not on a word
  CHECK(!gdakiRsCsumChunk(NCCL_GIN_RS_CSUM_FULL, 16, 4, z, 6, a, b));   // ends inside a word, not at the end
  CHECK(!gdakiRsCsumChunk(NCCL_GIN_RS_CSUM_FULL, 16, 12, z, 8, a, b));  // past the end
  CHECK(gdakiRsCsumChunk(NCCL_GIN_RS_CSUM_FULL, 14, 12, z, 2, a, b));   // the last, partial word
  printf("chunked checksum: %d data sets\n", n);
}
// A survivor's log toward one peer for the stream tests: entries and the source windows' bytes they read.
struct XLog {
  std::vector<struct ncclGinRsLogEntry> e;
  std::map<uint32_t, std::vector<uint8_t>> src;  // source window number -> its bytes
};
static XLog makeLog(std::mt19937_64& rng, int nqp, const int* qps, int nEnt, uint32_t scheme) {
  XLog x;
  for (uint32_t w = 1; w <= 3; w++) {
    x.src[w].resize(1 + rng() % 9000);
    for (auto& c : x.src[w]) c = (uint8_t)rng();
  }
  for (int i = 0; i < nEnt; i++) {
    const uint32_t qp = (uint32_t)qps[rng() % nqp];
    const int k = (int)(rng() % 3);
    const bool sig = rng() % 2;
    const uint32_t sigWin = rng() % 3 == 0 ? 0u : 4u + (uint32_t)(rng() % 2);
    const uint64_t sigOff = 8 * (rng() % 16), sigVal = 1 + rng() % 5;
    if (k == 0) {
      const uint32_t w = 1 + (uint32_t)(rng() % 3);
      const uint64_t sz = x.src[w].size(), off = rng() % sz, bytes = rng() % (sz - off + 1);
      uint32_t flags = sig ? NCCL_GIN_RS_LOGF_SIGNAL : 0u;
      uint32_t csum = 0;
      if (bytes != 0 && scheme != NCCL_GIN_RS_CSUM_OFF) {
        flags |= scheme << NCCL_GIN_RS_LOGF_CSUM_SHIFT;
        csum = ncclGinRsCsumWalk(scheme, x.src[w].data() + off, bytes, ncclGinRsCsumHostLoad());
      }
      const uint32_t dw = 4 + (uint32_t)(rng() % 2);
      const uint64_t doff = 256 + 8 * (rng() % 64);  // data at 256 and up, signal words below 128: no overlap
      struct ncclGinRsLogEntry e = entryOf(qp, NCCL_GIN_RS_LOG_PUT, flags, dw, w, doff, bytes, off, sig ? sigWin : 0,
                                           sig ? sigOff : 0, sig ? sigVal : 0);
      e.csum = csum;
      x.e.push_back(e);
    } else if (k == 1) {
      x.e.push_back(entryOf(qp, NCCL_GIN_RS_LOG_PUTVALUE, sig ? NCCL_GIN_RS_LOGF_SIGNAL : 0u, 4 + (uint32_t)(rng() % 2), 0,
                            256 + 8 * (rng() % 64), 1 + rng() % 8, rng(), sig ? sigWin : 0, sig ? sigOff : 0,
                            sig ? sigVal : 0));
    } else {
      x.e.push_back(entryOf(qp, NCCL_GIN_RS_LOG_SIGNAL, NCCL_GIN_RS_LOGF_SIGNAL, 0, 0, 0, 0, 0, sigWin, sigOff, sigVal));
    }
    x.e.back().pos = (uint32_t)i;
  }
  return x;
}
static int buildX(const XLog& x, const struct gdakiRsLogXHdr& h, uint64_t chunk, std::vector<uint8_t>* out,
                  int failReadAt = -1, int failPutAt = -1, char* why = nullptr) {
  int reads = 0, puts = 0;
  char w[160];
  auto read = [&](const struct ncclGinRsLogEntry& e, uint64_t off, uint64_t len, const char** bad) -> const uint8_t* {
    if (reads++ == failReadAt) {
      *bad = "test: no source";
      return nullptr;
    }
    auto it = x.src.find(e.srcWin);
    if (it == x.src.end() || e.src + off + len > it->second.size()) {
      *bad = "test: out of range";
      return nullptr;
    }
    return it->second.data() + e.src + off;
  };
  auto put = [&](const void* p, size_t n) {
    if (puts++ == failPutAt) return false;
    out->insert(out->end(), (const uint8_t*)p, (const uint8_t*)p + n);
    return true;
  };
  return gdakiRsLogXBuild(h, x.e.data(), x.e.size(), chunk, read, put, why ? why : w, sizeof(w));
}
static const uint64_t kTestCkpt = 41;  // the checkpoint the test exports name and the test spare restores
static struct gdakiRsLogXHdr hdrOf(int from, int to, uint32_t inc, uint64_t nonce, int nqp, uint64_t cut, size_t nEnt) {
  struct gdakiRsLogXHdr h;
  memset(&h, 0, sizeof(h));
  h.magic = GDAKI_RS_LOGX_MAGIC;
  h.version = 1;
  h.from = from, h.to = to, h.incarnation = inc, h.nonce = nonce, h.nqp = (uint32_t)nqp;
  h.ckpt = kTestCkpt, h.cut = cut, h.head = cut + nEnt + 3, h.nEntries = nEnt;
  for (int k = 0; k < nqp; k++) h.x[k] = 100 + k, h.m[k] = 200 + k;
  return h;
}
static void testLogX() {
  std::mt19937_64 rng(92);
  int whole = 0, refused = 0;
  for (int it = 0; it < 400; it++) {
    const int qps[3] = {1, 5, 9};
    const uint32_t scheme = (uint32_t)(it % 3);
    XLog x = makeLog(rng, 3, qps, (int)(rng() % 40), scheme);
    const struct gdakiRsLogXHdr h = hdrOf(1, 2, 7, 0xabcdefull, 3, 1000, x.e.size());
    std::vector<uint8_t> s;
    const uint64_t chunk = 1 + rng() % 5000;
    CHECK(buildX(x, h, chunk, &s) == GDAKI_RS_LOGX_OK);
    struct gdakiRsLogXParsed px;
    char w[200];
    CHECK(gdakiRsLogXParse(s.data(), s.size(), &px, w, sizeof(w)));
    CHECK(memcmp(&px.hdr, &h, sizeof(h)) == 0 && px.end.ok == 1 && px.items.size() == x.e.size());
    for (size_t i = 0; i < x.e.size() && i < px.items.size(); i++) {
      CHECK(memcmp(&px.items[i].e, &x.e[i], sizeof(x.e[i])) == 0);
      const auto& e = x.e[i];
      if (ncclGinRsEntryKind(e.qpKf) == NCCL_GIN_RS_LOG_PUT && e.bytes != 0)
        CHECK(px.items[i].dataOff != 0 && memcmp(s.data() + px.items[i].dataOff, x.src[e.srcWin].data() + e.src, e.bytes) == 0);
      else
        CHECK(px.items[i].dataOff == 0);
    }
    whole++;
    // a source changed after its post (FULL: any byte; SAMPLED: a sampled byte, the first): refused, the trailer says why
    for (size_t i = 0; i < x.e.size(); i++) {
      const auto& e = x.e[i];
      if (scheme == NCCL_GIN_RS_CSUM_OFF || ncclGinRsEntryKind(e.qpKf) != NCCL_GIN_RS_LOG_PUT || e.bytes == 0) continue;
      XLog y = x;
      y.src[e.srcWin][(size_t)(e.src + (scheme == NCCL_GIN_RS_CSUM_FULL ? rng() % e.bytes : 0))] ^= 0x40;
      std::vector<uint8_t> t;
      char bw[160];
      CHECK(buildX(y, h, chunk, &t, -1, -1, bw) == GDAKI_RS_LOGX_REFUSED && strstr(bw, "source buffer changed") != nullptr);
      CHECK(!gdakiRsLogXParse(t.data(), t.size(), &px, w, sizeof(w)) && strstr(w, "source buffer changed") != nullptr &&
            strstr(w, "refused") != nullptr);
      refused++;
      break;
    }
    // a failed source read: refused; a failed put: the stream is cut
    bool anyData = false;
    for (const auto& e : x.e) anyData = anyData || (ncclGinRsEntryKind(e.qpKf) == NCCL_GIN_RS_LOG_PUT && e.bytes != 0);
    if (anyData) {
      std::vector<uint8_t> t;
      CHECK(buildX(x, h, chunk, &t, 0) == GDAKI_RS_LOGX_REFUSED);
      CHECK(!gdakiRsLogXParse(t.data(), t.size(), &px, w, sizeof(w)) && strstr(w, "test: no source") != nullptr);
    }
    std::vector<uint8_t> t;
    CHECK(buildX(x, h, chunk, &t, -1, (int)(rng() % (2 + x.e.size()))) == GDAKI_RS_LOGX_STREAM);
    // damaged streams
    if (s.size() > sizeof(h) + sizeof(struct gdakiRsLogXEnd)) {
      std::vector<uint8_t> u(s.begin(), s.end() - 1);
      CHECK(!gdakiRsLogXParse(u.data(), u.size(), &px, w, sizeof(w)));
    }
    std::vector<uint8_t> u = s;
    u.insert(u.end() - sizeof(struct gdakiRsLogXEnd), 0);
    CHECK(!gdakiRsLogXParse(u.data(), u.size(), &px, w, sizeof(w)));
    u = s;
    u[0] ^= 1;
    CHECK(!gdakiRsLogXParse(u.data(), u.size(), &px, w, sizeof(w)));
    u = s;
    u[u.size() - sizeof(struct gdakiRsLogXEnd)] ^= 1;
    CHECK(!gdakiRsLogXParse(u.data(), u.size(), &px, w, sizeof(w)));
    if (!x.e.empty()) {  // an entry the spare cannot apply
      XLog y = x;
      y.e[0].qpKf = ncclGinRsQpKf(1, 0, 0);
      std::vector<uint8_t> v;
      buildX(y, h, chunk, &v);
      CHECK(!gdakiRsLogXParse(v.data(), v.size(), &px, w, sizeof(w)) && strstr(w, "unknown kind") != nullptr);
    }
    struct gdakiRsLogXHdr hb = h;  // more entries than positions
    hb.nEntries = hb.head - hb.cut + 1;
    u = s;
    memcpy(u.data(), &hb, sizeof(hb));
    CHECK(!gdakiRsLogXParse(u.data(), u.size(), &px, w, sizeof(w)));
    CHECK(!gdakiRsLogXParse(s.data(), sizeof(h), &px, w, sizeof(w)));
  }
  CHECK(whole == 400 && refused > 150);
  // the message check: per QP, the entries' messages equal M at the hold minus M at the cut
  const int qps[2] = {3, 7};
  std::vector<struct ncclGinRsLogEntry> e;
  e.push_back(entryOf(3, NCCL_GIN_RS_LOG_PUT, NCCL_GIN_RS_LOGF_SIGNAL, 1, 2, 0, (3ull << 30) + 1, 0, 0, 0, 1));  // 4 + 1
  e.push_back(entryOf(7, NCCL_GIN_RS_LOG_PUTVALUE, 0, 1, 0, 0, 8, 5, 0, 0, 0));                                // 1
  e.push_back(entryOf(3, NCCL_GIN_RS_LOG_SIGNAL, NCCL_GIN_RS_LOGF_SIGNAL, 0, 0, 0, 0, 0, 0, 8, 1));            // 1
  e.push_back(entryOf(4, NCCL_GIN_RS_LOG_SIGNAL, NCCL_GIN_RS_LOGF_SIGNAL, 0, 0, 0, 0, 0, 0, 8, 1));            // not the peer's
  const uint64_t mCut[2] = {10, 20}, mOk[2] = {16, 21}, mBad[2] = {17, 21}, mLow[2] = {9, 21};
  char w[200];
  CHECK(gdakiRsLogXMsgsCheck(e.data(), e.size(), qps, 2, mOk, mCut, w, sizeof(w)));
  CHECK(!gdakiRsLogXMsgsCheck(e.data(), e.size(), qps, 2, mBad, mCut, w, sizeof(w)) && strstr(w, "qp 3") != nullptr);
  CHECK(!gdakiRsLogXMsgsCheck(e.data(), e.size(), qps, 2, mLow, mCut, w, sizeof(w)));
  CHECK(!gdakiRsLogXMsgsCheck(e.data(), 1, qps, 2, mOk, mCut, w, sizeof(w)));  // an entry missing
  printf("export stream: %d whole, %d refused for a changed source\n", whole, refused);
}
// The import plan against a direct application of every entry in order (the memory the spare must end with).
static void testImportPlan() {
  std::mt19937_64 rng(93);
  int plans = 0, sigChecks = 0, sigTampered = 0;
  const uint64_t nonce = 0x1234567890ull;
  for (int it = 0; it < 300; it++) {
    const int nranks = 3 + (int)(rng() % 3), me = (int)(rng() % nranks), nctx = 1 + (int)(rng() % 2);
    const uint32_t inc = 2 + (uint32_t)(rng() % 5);
    std::vector<int> nqpOf((size_t)nranks, nctx);
    nqpOf[(size_t)me] = 0;
    const int noGin = rng() % 3 == 0 ? (me + 1) % nranks : -1;  // a rank with no GIN QP to this one
    if (noGin >= 0) nqpOf[(size_t)noGin] = 0;
    std::vector<struct gdakiRsImportWin> wins = {{4, 256 + 8 * 64 + 9000}, {5, 256 + 8 * 64 + 9000}};
    const uint64_t sigBytes = 8 * 16;
    std::vector<std::vector<uint8_t>> exports((size_t)nranks);
    std::vector<std::vector<uint64_t>> P((size_t)nranks);
    std::vector<struct gdakiRsImportP> pp;
    std::map<uint32_t, std::vector<uint8_t>> mem;  // the expected memory: window number (0: the signal table)
    mem[4].assign((size_t)wins[0].bytes, 0);
    mem[5].assign((size_t)wins[1].bytes, 0);
    mem[0].assign((size_t)sigBytes, 0);
    uint64_t entries = 0;
    for (int q = 0; q < nranks; q++) {
      if (nqpOf[(size_t)q] == 0) continue;
      std::vector<int> qps;
      for (int c = 0; c < nctx; c++) qps.push_back(c * nranks + me);  // the survivor's QPs to this rank
      XLog x = makeLog(rng, (int)qps.size(), qps.data(), (int)(rng() % 25), (uint32_t)(rng() % 3));
      struct gdakiRsLogXHdr h = hdrOf(q, me, inc, nonce, nctx, 50, x.e.size());
      P[(size_t)q].resize((size_t)nctx);
      for (int k = 0; k < nctx; k++) P[(size_t)q][(size_t)k] = h.x[k] - rng() % 50;
      CHECK(buildX(x, h, 4096, &exports[(size_t)q]) == GDAKI_RS_LOGX_OK);
      for (const auto& e : x.e) {  // the direct application, in order
        const uint32_t kind = ncclGinRsEntryKind(e.qpKf);
        if (kind == NCCL_GIN_RS_LOG_PUT && e.bytes)
          memcpy(mem[e.dstWin].data() + e.dstOff, x.src[e.srcWin].data() + e.src, e.bytes);
        if (kind == NCCL_GIN_RS_LOG_PUTVALUE) memcpy(mem[e.dstWin].data() + e.dstOff, &e.src, e.bytes);
        if (ncclGinRsEntryFlags(e.qpKf) & NCCL_GIN_RS_LOGF_SIGNAL) {
          uint64_t v;
          memcpy(&v, mem[e.sigWin].data() + e.sigOff, 8);
          v += e.sigVal;
          memcpy(mem[e.sigWin].data() + e.sigOff, &v, 8);
        }
        entries++;
      }
    }
    for (int q = 0; q < nranks; q++)
      if (!P[(size_t)q].empty()) pp.push_back({q, (uint32_t)nctx, P[(size_t)q].data()});
    std::shuffle(pp.begin(), pp.end(), rng);
    struct gdakiRsImportPlan plan;
    char w[256];
    const bool ok = gdakiRsImportPlanOf(me, kTestCkpt, inc, nonce, nqpOf.data(), nranks, pp.data(), (int)pp.size(), exports,
                                        wins.data(), (int)wins.size(), sigBytes, &plan, w, sizeof(w));
    CHECK(ok);
    if (!ok) {
      fprintf(stderr, "import plan: %s\n", w);
      continue;
    }
    plans++;
    CHECK(plan.entries == entries);
    std::map<uint32_t, std::vector<uint8_t>> got;
    got[4].assign((size_t)wins[0].bytes, 0);
    got[5].assign((size_t)wins[1].bytes, 0);
    got[0].assign((size_t)sigBytes, 0);
    for (const auto& c : plan.copies) memcpy(got[c.win].data() + c.off, c.data ? c.data : (const uint8_t*)&c.value, c.bytes);
    for (const auto& s : plan.sigs) {
      uint64_t v;
      memcpy(&v, got[s.win].data() + s.off, 8);
      v += s.add;
      memcpy(got[s.win].data() + s.off, &v, 8);
    }
    CHECK(got == mem);
    // option (b): the CPU-side check of the signal additions the import posts as NIC atomics (an independent second pass
    // over the exports) passes and gives the entries' total; a plan whose additions differ in any way fails it
    {
      uint64_t want = 0, tot = ~0ull;
      for (const auto& ex : exports) {
        if (ex.empty()) continue;
        struct gdakiRsLogXParsed px;
        char pw[200];
        CHECK(gdakiRsLogXParse(ex.data(), ex.size(), &px, pw, sizeof(pw)));
        for (const auto& itm : px.items)
          if (ncclGinRsEntryFlags(itm.e.qpKf) & NCCL_GIN_RS_LOGF_SIGNAL) want += itm.e.sigVal;
      }
      char cw[256];
      CHECK(gdakiRsImportSigCheck(exports, plan, &tot, cw, sizeof(cw)) && tot == want);
      sigChecks++;
      if (!plan.sigs.empty()) {
        const size_t k = (size_t)(rng() % plan.sigs.size());
        struct gdakiRsImportPlan t = plan;  // one addition off by one
        t.sigs[k].add++;
        CHECK(!gdakiRsImportSigCheck(exports, t, &tot, cw, sizeof(cw)));
        t = plan;  // one target dropped (and its count)
        t.sigAdds -= 1;
        t.sigs.erase(t.sigs.begin() + (long)k);
        CHECK(!gdakiRsImportSigCheck(exports, t, &tot, cw, sizeof(cw)));
        t = plan;  // one target split in two (same total, same count of entries)
        t.sigs.insert(t.sigs.begin() + (long)k, t.sigs[k]);
        t.sigs[k].add = 0;
        CHECK(!gdakiRsImportSigCheck(exports, t, &tot, cw, sizeof(cw)));
        t = plan;  // one target moved to another word (same total)
        t.sigs[k].off += 8;
        CHECK(!gdakiRsImportSigCheck(exports, t, &tot, cw, sizeof(cw)));
        t = plan;  // two targets' additions swapped (same total; caught when they differ)
        if (plan.sigs.size() > 1 && plan.sigs[0].add != plan.sigs[1].add) {
          std::swap(t.sigs[0].add, t.sigs[1].add);
          CHECK(!gdakiRsImportSigCheck(exports, t, &tot, cw, sizeof(cw)));
        }
        t = plan;  // the count of signal entries
        t.sigAdds++;
        CHECK(!gdakiRsImportSigCheck(exports, t, &tot, cw, sizeof(cw)));
        sigTampered++;
      }
    }
    for (size_t i = 1; i < plan.sigs.size(); i++)  // one addition per target, in target order
      CHECK(plan.sigs[i - 1].win < plan.sigs[i].win ||
            (plan.sigs[i - 1].win == plan.sigs[i].win && plan.sigs[i - 1].off < plan.sigs[i].off));
    for (const auto& pe : plan.peers) {
      CHECK(pe.nqp == nctx && !P[(size_t)pe.rank].empty());
      for (int k = 0; k < pe.nqp; k++)
        CHECK(pe.budget[k] == 100 + (uint64_t)k - P[(size_t)pe.rank][(size_t)k] && pe.x[k] == 100 + (uint64_t)k &&
              pe.m[k] == 200 + (uint64_t)k);
    }
    // refusals, nothing planned
    auto refuseCk = [&](const std::vector<std::vector<uint8_t>>& ex, const std::vector<struct gdakiRsImportP>& p,
                        uint64_t ck, uint32_t incn, uint64_t non, const char* frag) {
      struct gdakiRsImportPlan pl;
      char rw[256];
      const bool r = gdakiRsImportPlanOf(me, ck, incn, non, nqpOf.data(), nranks, p.data(), (int)p.size(), ex, wins.data(),
                                         (int)wins.size(), sigBytes, &pl, rw, sizeof(rw));
      CHECK(!r && strstr(rw, frag) != nullptr);
      if (r || strstr(rw, frag) == nullptr) fprintf(stderr, "expected '%s', got '%s'\n", frag, r ? "(accepted)" : rw);
    };
    auto refuse = [&](const std::vector<std::vector<uint8_t>>& ex, const std::vector<struct gdakiRsImportP>& p,
                      uint32_t incn, uint64_t non, const char* frag) { refuseCk(ex, p, kTestCkpt, incn, non, frag); };
    refuse(exports, pp, inc + 1, nonce, "not for this restore");
    refuseCk(exports, pp, kTestCkpt + 1, inc, nonce, "not for this restore");  // an export of another checkpoint
    refuse(exports, pp, inc, nonce ^ 1, "not for this restore");
    int q0 = -1;
    for (int q = 0; q < nranks && q0 < 0; q++) if (nqpOf[(size_t)q] > 0) q0 = q;
    {
      auto ex = exports;
      ex[(size_t)q0].clear();
      refuse(ex, pp, inc, nonce, "no log export from rank");
      if (noGin >= 0) {
        ex = exports;
        ex[(size_t)noGin] = exports[(size_t)q0];
        refuse(ex, pp, inc, nonce, "has no QP to this rank");
      }
      ex = exports;
      std::vector<uint8_t>& v = ex[(size_t)q0];
      struct gdakiRsLogXHdr h;
      memcpy(&h, v.data(), sizeof(h));
      h.to = (me + 1) % nranks;
      memcpy(v.data(), &h, sizeof(h));
      refuse(ex, pp, inc, nonce, "not for this restore");
      ex = exports;
      struct gdakiRsLogXEnd en;
      memcpy(&en, ex[(size_t)q0].data() + ex[(size_t)q0].size() - sizeof(en), sizeof(en));
      en.ok = 0;
      snprintf(en.why, sizeof(en.why), "source buffer changed (test)");
      memcpy(ex[(size_t)q0].data() + ex[(size_t)q0].size() - sizeof(en), &en, sizeof(en));
      refuse(ex, pp, inc, nonce, "source buffer changed");
    }
    {
      auto p = pp;
      p.erase(std::remove_if(p.begin(), p.end(), [&](const struct gdakiRsImportP& a) { return a.rank == q0; }), p.end());
      refuse(exports, p, inc, nonce, "no P of rank");
      p = pp;
      for (const auto& a : pp) if (a.rank == q0) p.push_back(a);
      refuse(exports, p, inc, nonce, "two P records");
      std::vector<uint64_t> big((size_t)nctx, ~0ull);
      p = pp;
      for (auto& a : p) if (a.rank == q0) a.p = big.data();
      refuse(exports, p, inc, nonce, "at the checkpoint");
    }
    {  // a target outside this process's windows, a misaligned signal
      XLog x;
      x.src[1].assign(64, 1);
      x.e.push_back(entryOf((uint32_t)me, NCCL_GIN_RS_LOG_PUT, 0, 4, 1, wins[0].bytes - 8, 16, 0, 0, 0, 0));
      auto ex = exports;
      ex[(size_t)q0].clear();
      struct gdakiRsLogXHdr h = hdrOf(q0, me, inc, nonce, nctx, 50, 1);
      CHECK(buildX(x, h, 4096, &ex[(size_t)q0]) == GDAKI_RS_LOGX_OK);
      refuse(ex, pp, inc, nonce, "is not a window of this process");
      x.e[0] = entryOf((uint32_t)me, NCCL_GIN_RS_LOG_SIGNAL, NCCL_GIN_RS_LOGF_SIGNAL, 0, 0, 0, 0, 0, 0, 4, 1);
      ex[(size_t)q0].clear();
      CHECK(buildX(x, h, 4096, &ex[(size_t)q0]) == GDAKI_RS_LOGX_OK);
      refuse(ex, pp, inc, nonce, "is not in this process");
      x.e[0] = entryOf((uint32_t)me, NCCL_GIN_RS_LOG_SIGNAL, NCCL_GIN_RS_LOGF_SIGNAL, 0, 0, 0, 0, 0, 9, 8, 1);
      ex[(size_t)q0].clear();
      CHECK(buildX(x, h, 4096, &ex[(size_t)q0]) == GDAKI_RS_LOGX_OK);
      refuse(ex, pp, inc, nonce, "is not in this process");
      // a put over a signal word of the same window (here the put carries it; any entry's would do): refused
      for (uint64_t at : {0ull, 8ull, 128ull}) {
        x.e[0] = entryOf((uint32_t)me, NCCL_GIN_RS_LOG_PUT, NCCL_GIN_RS_LOGF_SIGNAL, 5, 1, at, 16, 0, 5, 8, 1);
        struct gdakiRsLogXHdr h2 = hdrOf(q0, me, inc, nonce, nctx, 50, 1);
        ex[(size_t)q0].clear();
        CHECK(buildX(x, h2, 4096, &ex[(size_t)q0]) == GDAKI_RS_LOGX_OK);
        if (at == 128) {  // [128, 144) touches no signal word (the random ones are below 128): accepted
          struct gdakiRsImportPlan pl;
          char rw[256];
          const bool r = gdakiRsImportPlanOf(me, kTestCkpt, inc, nonce, nqpOf.data(), nranks, pp.data(), (int)pp.size(), ex,
                                             wins.data(), (int)wins.size(), sigBytes, &pl, rw, sizeof(rw));
          CHECK(r);
        } else {
          refuse(ex, pp, inc, nonce, "overlaps the signal word");
        }
      }
    }
    const std::vector<struct gdakiRsImportWin> dup = {{4, 100}, {4, 200}};
    struct gdakiRsImportPlan pl;
    CHECK(!gdakiRsImportPlanOf(me, kTestCkpt, inc, nonce, nqpOf.data(), nranks, pp.data(), (int)pp.size(), exports, dup.data(), 2,
                               sigBytes, &pl, w, sizeof(w)));
  }
  CHECK(plans == 300 && sigChecks == 300 && sigTampered > 250);
  printf("import plan: %d plans equal to the direct application; signal sum check %d, refused tampered plans %d\n", plans,
         sigChecks, sigTampered);
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
  testCsum();
  testCsumScheme();
  testEntryLayout();
  testPlan();
  testRing();
  testSums();
  testLogState();
  testExec();
  testEntryCheck();
  testCsumChunk();
  testLogX();
  testImportPlan();
  printf("rs_unit_dev: %d checks, %d failed\n", nChecks, nFail);
  return nFail == 0 ? 0 : 1;
}
