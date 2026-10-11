// rs_unit.cc - CPU unit test of the restore layer's decision and reason functions (EXPERIMENT.md 9.14, work packages 1
// and 2). build_rs.sh unit cuts the region between the two "gin-restore: pure functions" markers out of the working
// tree's gin_host_gdaki.cc into rs_pure.inc and compiles it here, so the test runs the library's own text. No NCCL, no
// CUDA, no network. Fake record sets stand for the all-gather of a 4-rank communicator.
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <random>
#include <string>
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

int main() {
  testCfg();
  testWinStrict();
  testBits();
  testDecide();
  testRandom();
  printf("rs_unit: %d checks, %d failed\n", nChecks, nFail);
  return nFail == 0 ? 0 : 1;
}
