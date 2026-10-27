// gc_unit_waitpeer.cc - CPU model of gin-control's waitpeer rule (SPEC2, 2026-10-27; impl/notes_waitpeer.md): a rank
// whose stalled QPs go only to stalled ranks (DEPENDENT) is not judged while they are unresolved. No NCCL, no CUDA, no
// verbs, no network. Compiled as gc_unit_livectx.cc is (build_gc.sh `unit`, `unitwaitpeer`, BR=int3): g++ -std=c++17
// with ASan and UBSan, gin-mirror's and gin-restore's headers, impl/rs_ctrl_api.h, the working tree's cut regions
// "gin-control (page): pure functions" (gc_page_pure.inc: the element clocks, the classifier, the wait gate, the page
// word, the mail order, R, the guard, the table) and "gin-restore hold: pure functions" (rs_hold_pure.inc: the decline's
// action). The glue of the host file (the snapshot over every rank, the page word, the helper's mail order, the hold's
// decline and TOLD, the restore's fence, commit, re-pairing and hold end) is modelled here around those functions.
// What it checks:
//   1. the pure pieces: element clock (rewrite hold, torn READ, gap rule), the classifier on small graphs, the gate, the
//      page word against the guard (9 799 FRESH, 9 800 and 9 999 PASS, a host part that passes), the mail order;
//   2. the scenes of ANALYSIS 4 and SPEC2 (가)-(사) over four observers (every rank's process, the hung one's too, and
//      the restored incarnation's), each with its own READ phases, its own local read of its own line, its page words
//      read by the others, its helper's mail order and the hold glue; READ phases and stall offsets drawn per run;
//   3. the mutations m1-m10: each must fail at least one scene (the counts are printed).
#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <functional>
#include <map>
#include <memory>
#include <queue>
#include <random>
#include <set>
#include <string>
#include <thread>
#include <vector>

typedef enum { ncclSuccess = 0, ncclSystemError = 2, ncclInternalError = 3, ncclInvalidUsage = 5 } ncclResult_t;
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

static long gChecks = 0, gFailed = 0;
[[maybe_unused]] static bool gQuiet = false;  // a mutation run: failures are counted per scene, not reported
#define CHECK(c)                                                                      \
  do {                                                                                \
    gChecks++;                                                                        \
    if (!(c)) {                                                                       \
      gFailed++;                                                                      \
      if (!gQuiet && gFailed <= 60) fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); \
    }                                                                                 \
  } while (0)

#if !NCCL_GIN_CTRL_TCP  // the tcp build has none of it (the page region is rdma only)
enum { GDAKI_TS_HELLO = 1, GDAKI_TS_REQ = 2, GDAKI_TS_ACK = 3, GDAKI_TS_NACK = 4, GDAKI_TS_DONE = 5, GDAKI_TS_FAIL = 6,
       GDAKI_TS_BYE = 10 };
#include "rs_hold_pure.inc"  // the host file's "gin-restore hold: pure functions" region (gdakiHoldDeclineAction)
#include "gc_page_pure.inc"  // the host file's "gin-control (page): pure functions" region

static const double kProbe = GDAKI_CTRL_PROBE_MS_DEFAULT, kSuspect = GDAKI_CTRL_SUSPECT_MS_DEFAULT;
static const double kStall = GDAKI_CTRL_STALL_MS_DEFAULT, kG = kSuspect, kHard = 2.0 * kStall;
static const double kTz = kSuspect - 2.0 * kProbe;

// ---- the mutations (m0: the rule as implemented) ----
enum Mut {
  M0 = 0,
  M1_OLD,         // the old rule: the context sums' clocks, no classification, no gate, raw page word, helper by rank
  M2_HELPER_ASC,  // the helper takes the step's mails by rank, none dropped (SPEC2 helper off)
  M3_ONE_PEER,    // the roles and gates of the judged peer only, at its own judgement (no snapshot over every rank)
  M4_NO_REWRITE,  // the commit's (0, 0) rewrite is quiet (the restart check off)
  M5_EXEMPT,      // "a stalled peer exempts": DEPENDENT without reaching a SOURCE (no CYCLE)
  M6_ONE_STEP,    // DEPENDENT only when a direct target is a SOURCE (one step along T)
  M7_RESET,       // X's clocks reset when a target leaves Z
  M8_RAW_WORD,    // the page word raw while the gate is closed
  M9_WORD_9999,   // the page word capped at STALL_MS - 1 (9 999: PASS in the guard)
  M10_NO_HARD,    // the hard bound off
  M11_YOUNG,      // a view younger than STALL_MS - 2 x PROBE_MS is a witness of the guard (FRESH or PASS) as before
  M_N
};
static const char* kMutName[M_N] = {"m0 rule",       "m1 old rule",   "m2 helper by rank", "m3 one peer",
                                    "m4 no restart check", "m5 stalled exempts", "m6 one step", "m7 reset on leave",
                                    "m8 raw page word", "m9 page word 9999", "m10 no hard bound",
                                    "m11 young views witness"};
static int gMut = M0;
static long gCycleLate2 = 0, gCycleLate4 = 0, gLa3Judged = 0, gLa3Runs = 0;  // reports
static const char* gCur = "";  // the scene being run (GC_WP_ONLY selects the trace)

// ---- 1. the pure pieces ----
static const uint32_t kStride = 296, kOffPosted = 0, kOffPolled = 184;
static void putElem(std::vector<uint8_t>& b, uint32_t k, uint64_t posted, uint64_t polled) {
  memcpy(b.data() + (size_t)k * kStride + kOffPosted, &posted, 8);
  memcpy(b.data() + (size_t)k * kStride + kOffPolled, &polled, 8);
}
static struct gdakiCtrlRMask maskOf(std::initializer_list<uint32_t> ks) {
  struct gdakiCtrlRMask m;
  for (uint32_t k : ks) gdakiCtrlRMaskSet(&m, k);
  return m;
}
static void testPure() {
  // the element of a line, and its clock
  std::vector<uint8_t> line(4 * kStride, 0);
  putElem(line, 2, 50, 40);
  struct gdakiCtrlDevSum d = gdakiCtrlDevElemOf(line.data(), (uint32_t)line.size(), kStride, kOffPosted, kOffPolled, 2);
  CHECK(d.posted == 50 && d.polled == 40 && d.pending == 10);
  d = gdakiCtrlDevElemOf(line.data(), (uint32_t)line.size(), kStride, kOffPosted, kOffPolled, 4);  // out of the line
  CHECK(d.posted == 0 && d.polled == 0 && d.pending == 0);
  struct gdakiCtrlDevElem e;
  struct gdakiCtrlDevSum p;
  p.posted = 12;
  p.polled = 10;
  p.pending = 2;
  bool prog = true;
  for (int t = 0; t <= 3000; t += 100) (void)gdakiCtrlDevElemOnRead(&e, p, t, kProbe, true, &prog);
  CHECK(gdakiCtrlDevElemStale(e) == 3000 && !prog);
  struct gdakiCtrlDevSum z;  // the commit's (0, 0): held pending while the gate holds it
  (void)gdakiCtrlDevElemOnRead(&e, z, 3100, kProbe, true, &prog);
  CHECK(e.rw && gdakiCtrlDevElemStale(e) == 3100 && !prog);
  struct gdakiCtrlDevSum torn;  // a torn READ (posted 0, the old polled): still the rewrite
  torn.polled = 10;
  (void)gdakiCtrlDevElemOnRead(&e, torn, 3200, kProbe, false, &prog);
  CHECK(e.rw && gdakiCtrlDevElemStale(e) == 3200 && !prog);
  (void)gdakiCtrlDevElemOnRead(&e, z, 3600, kProbe, false, &prog);  // the reader's own gap (> 200 ms): the origin
  CHECK(e.rw && gdakiCtrlDevElemStale(e) == 0);
  struct gdakiCtrlDevSum one;  // the first post after the rewrite: progress
  one.posted = 1;
  one.pending = 1;
  (void)gdakiCtrlDevElemOnRead(&e, one, 3700, kProbe, false, &prog);
  CHECK(!e.rw && prog && gdakiCtrlDevElemStale(e) == 0);
  struct gdakiCtrlDevElem f;  // without the hold the rewrite is a quiet element (the old rule)
  for (int t = 0; t <= 3000; t += 100) (void)gdakiCtrlDevElemOnRead(&f, p, t, kProbe, false);
  (void)gdakiCtrlDevElemOnRead(&f, z, 3100, kProbe, false, &prog);
  CHECK(!f.rw && prog && gdakiCtrlDevElemStale(f) == 0);
  // the row: T at T_z, the raw stall and its context
  std::vector<struct gdakiCtrlDevElem> row(2 * 4);
  for (int t = 0; t <= 2000; t += 100) {
    struct gdakiCtrlDevSum a, b;
    a.posted = 5;
    a.polled = 3;
    a.pending = 2;
    b.posted = b.polled = 9;
    (void)gdakiCtrlDevElemOnRead(&row[1 * 4 + 3], a, t, kProbe, false);  // context 1, element 3 frozen with pending
    (void)gdakiCtrlDevElemOnRead(&row[0 * 4 + 1], b, t, kProbe, false);  // context 0, element 1 quiet
    struct gdakiCtrlDevSum m;
    m.posted = 100 + (uint64_t)t;
    m.polled = 98 + (uint64_t)t;
    m.pending = 2;
    (void)gdakiCtrlDevElemOnRead(&row[0 * 4 + 2], m, t, kProbe, false);  // element 2 progressing
  }
  struct gdakiCtrlRMask t;
  int ctx = -2;
  double fm = 0;
  const double raw = gdakiCtrlStallTargets(row.data(), 2, 4, kTz, &t, &ctx, &fm);
  CHECK(raw == 2000 && ctx == 1 && gdakiCtrlRMaskHas(t, 3) && !gdakiCtrlRMaskHas(t, 1) && !gdakiCtrlRMaskHas(t, 2) &&
        fm == 0);
  CHECK(gdakiCtrlStallTz(kSuspect, kProbe) == 1800);
  // the classifier
  uint32_t role[8];
  {  // cell B: 3 -> {0, 1, 2} with 0, 2 quiet; 1 -> {3}
    struct gdakiCtrlRMask tt[4] = {gdakiCtrlRMask(), maskOf({3}), gdakiCtrlRMask(), maskOf({0, 1, 2})};
    gdakiCtrlStallRoles(tt, 4, role);
    CHECK(role[0] == GDAKI_CTRL_ROLE_NONE && role[1] == GDAKI_CTRL_ROLE_DEPENDENT && role[2] == GDAKI_CTRL_ROLE_NONE &&
          role[3] == GDAKI_CTRL_ROLE_SOURCE);
  }
  {  // a two-rank cycle: CYCLE both
    struct gdakiCtrlRMask tt[4] = {gdakiCtrlRMask(), maskOf({3}), gdakiCtrlRMask(), maskOf({1})};
    gdakiCtrlStallRoles(tt, 4, role);
    CHECK(role[1] == GDAKI_CTRL_ROLE_CYCLE && role[3] == GDAKI_CTRL_ROLE_CYCLE);
  }
  {  // a chain 0 -> 1 -> 2 -> {3 quiet}: SOURCE 2, DEPENDENT 1 and 0
    struct gdakiCtrlRMask tt[4] = {maskOf({1}), maskOf({2}), maskOf({3}), gdakiCtrlRMask()};
    gdakiCtrlStallRoles(tt, 4, role);
    CHECK(role[2] == GDAKI_CTRL_ROLE_SOURCE && role[1] == GDAKI_CTRL_ROLE_DEPENDENT && role[0] == GDAKI_CTRL_ROLE_DEPENDENT);
  }
  {  // a cycle 0 <-> 1 with a branch 1 -> 2 (SOURCE): the cycle's members are DEPENDENT; a disjoint cycle is CYCLE
    struct gdakiCtrlRMask tt[6] = {maskOf({1}), maskOf({0, 2}), maskOf({3}), gdakiCtrlRMask(), maskOf({5}), maskOf({4})};
    gdakiCtrlStallRoles(tt, 6, role);
    CHECK(role[0] == GDAKI_CTRL_ROLE_DEPENDENT && role[1] == GDAKI_CTRL_ROLE_DEPENDENT && role[2] == GDAKI_CTRL_ROLE_SOURCE &&
          role[4] == GDAKI_CTRL_ROLE_CYCLE && role[5] == GDAKI_CTRL_ROLE_CYCLE);
  }
  {  // X's QP to itself stalled: SOURCE (X itself in T(X)); every rank in Z with no way out: CYCLE
    struct gdakiCtrlRMask tt[3] = {maskOf({0, 1}), maskOf({0}), gdakiCtrlRMask()};
    gdakiCtrlStallRoles(tt, 3, role);
    CHECK(role[0] == GDAKI_CTRL_ROLE_SOURCE && role[1] == GDAKI_CTRL_ROLE_DEPENDENT);
    struct gdakiCtrlRMask rr[4] = {maskOf({1}), maskOf({2}), maskOf({3}), maskOf({0})};
    gdakiCtrlStallRoles(rr, 4, role);
    CHECK(role[0] == GDAKI_CTRL_ROLE_CYCLE && role[1] == GDAKI_CTRL_ROLE_CYCLE && role[2] == GDAKI_CTRL_ROLE_CYCLE &&
          role[3] == GDAKI_CTRL_ROLE_CYCLE);
  }
  // the gate: closed on DEPENDENT; quiet target never resolves; G after the resolution; hard bound
  {
    struct gdakiCtrlWaitGate g;
    uint32_t ev[4] = {0, 0, 0, 0};
    const struct gdakiCtrlRMask tX = maskOf({3}), none;
    struct gdakiCtrlRMask inZ = maskOf({1, 3}), seen = maskOf({0, 1, 2, 3}), quiet;
    CHECK(gdakiCtrlWaitGateStep(&g, GDAKI_CTRL_ROLE_DEPENDENT, tX, 1900, inZ, seen, quiet, ev, 4, 1900, kG, kHard) ==
          GDAKI_CTRL_WGE_BEGAN && g.st == GDAKI_CTRL_WG_CLOSED);
    CHECK(gdakiCtrlWaitGateStep(&g, GDAKI_CTRL_ROLE_SOURCE, tX, 9000, maskOf({1}), maskOf({0, 1, 2}), quiet, ev, 4, 9000,
                                kG, kHard) == GDAKI_CTRL_WGE_NONE && g.st == GDAKI_CTRL_WG_CLOSED);  // sticky
    quiet = maskOf({3});  // held: never resolved, even when q left Z and a new line came
    ev[3] = 1;
    CHECK(gdakiCtrlWaitGateStep(&g, GDAKI_CTRL_ROLE_SOURCE, tX, 15000, maskOf({1}), seen, quiet, ev, 4, 15000, kG, kHard) ==
              GDAKI_CTRL_WGE_NONE && g.resMs < 0);
    quiet = none;
    CHECK(gdakiCtrlWaitGateStep(&g, GDAKI_CTRL_ROLE_SOURCE, tX, 15100, maskOf({1}), seen, quiet, ev, 4, 15100, kG, kHard) ==
              GDAKI_CTRL_WGE_NONE && g.resMs == 15100);
    CHECK(gdakiCtrlWaitGateStep(&g, GDAKI_CTRL_ROLE_SOURCE, tX, 17000, maskOf({1}), seen, quiet, ev, 4, 17000, kG, kHard) ==
          GDAKI_CTRL_WGE_NONE);
    CHECK(gdakiCtrlWaitGateStep(&g, GDAKI_CTRL_ROLE_SOURCE, tX, 17100, maskOf({1}), seen, quiet, ev, 4, 17100, kG, kHard) ==
              GDAKI_CTRL_WGE_OPEN_G && g.st == GDAKI_CTRL_WG_OPEN);
    CHECK(gdakiCtrlWaitGateStep(&g, GDAKI_CTRL_ROLE_SOURCE, none, 0, maskOf({}), seen, quiet, ev, 4, 17200, kG, kHard) ==
              GDAKI_CTRL_WGE_ENDED && g.st == GDAKI_CTRL_WG_NONE);
    struct gdakiCtrlWaitGate h;  // the hard bound whatever the target (held)
    (void)gdakiCtrlWaitGateStep(&h, GDAKI_CTRL_ROLE_DEPENDENT, tX, 1900, inZ, seen, none, ev, 4, 1900, kG, kHard);
    CHECK(gdakiCtrlWaitGateStep(&h, GDAKI_CTRL_ROLE_DEPENDENT, tX, 19999, inZ, seen, maskOf({3}), ev, 4, 19999, kG,
                                kHard) == GDAKI_CTRL_WGE_NONE);
    CHECK(gdakiCtrlWaitGateStep(&h, GDAKI_CTRL_ROLE_DEPENDENT, tX, 20000, inZ, seen, maskOf({3}), ev, 4, 20000, kG,
                                kHard) == GDAKI_CTRL_WGE_OPEN_HARD);
    struct gdakiCtrlWaitGate m;  // two targets: G counts after both are resolved
    const struct gdakiCtrlRMask t2 = maskOf({1, 2});
    uint32_t e2[4] = {0, 0, 0, 0};
    (void)gdakiCtrlWaitGateStep(&m, GDAKI_CTRL_ROLE_DEPENDENT, t2, 1900, maskOf({0, 1, 2}), seen, none, e2, 4, 1900, kG,
                                kHard);
    (void)gdakiCtrlWaitGateStep(&m, GDAKI_CTRL_ROLE_DEPENDENT, t2, 5000, maskOf({0, 2}), seen, none, e2, 4, 5000, kG, kHard);
    CHECK(m.resMs < 0);
    (void)gdakiCtrlWaitGateStep(&m, GDAKI_CTRL_ROLE_SOURCE, t2, 6000, maskOf({0}), seen, none, e2, 4, 6000, kG, kHard);
    CHECK(m.resMs == 6000);
    CHECK(gdakiCtrlWaitGateStep(&m, GDAKI_CTRL_ROLE_SOURCE, t2, 8000, maskOf({0}), seen, none, e2, 4, 8000, kG, kHard) ==
          GDAKI_CTRL_WGE_OPEN_G);
  }
  // the judgement's cap and the page word against the partition guard (review2 2)
  CHECK(gdakiCtrlWaitCap(12000, true, kStall) == kStall - 1 && gdakiCtrlWaitCap(12000, false, kStall) == 12000 &&
        gdakiCtrlWaitCap(5000, true, kStall) == 5000);
  CHECK(gdakiCtrlWaitPageGpu(12000, true, kStall, kProbe) == 9799 && gdakiCtrlWaitPageGpu(12000, false, kStall, kProbe) ==
        12000 && gdakiCtrlWaitPageGpu(3000, true, kStall, kProbe) == 3000);
  {
    bool v[1] = {true};
    double o[1] = {9799};
    CHECK(gdakiCtrlPartitionGuard(o, v, 1, kStall, kProbe) == GDAKI_CTRL_PG_FRESH);
    o[0] = 9800;
    CHECK(gdakiCtrlPartitionGuard(o, v, 1, kStall, kProbe) == GDAKI_CTRL_PG_PASS);
    o[0] = 9999;  // review2 2: 9 999 is PASS evidence
    CHECK(gdakiCtrlPartitionGuard(o, v, 1, kStall, kProbe) == GDAKI_CTRL_PG_PASS);
    o[0] = std::max(9900.0, gdakiCtrlWaitPageGpu(12000, true, kStall, kProbe));  // a host part alone passes (a limit)
    CHECK(gdakiCtrlPartitionGuard(o, v, 1, kStall, kProbe) == GDAKI_CTRL_PG_PASS);
    bool inv[2] = {false, true};
    double o2[2] = {9799, 12000};  // an invalid opponent is skipped (as before): the valid one passes
    CHECK(gdakiCtrlPartitionGuard(o2, inv, 2, kStall, kProbe) == GDAKI_CTRL_PG_PASS);
  }
  // the young view (coordinator decision): flagged in the word, the value kept; old words read as before
  {
    const uint64_t y = gdakiCtrlStaleWordAged(true, 120, true), m = gdakiCtrlStaleWordAged(true, 120, false);
    CHECK(gdakiCtrlStaleYoungOfWord(y) && gdakiCtrlStaleOfWord(y) == 120 && !gdakiCtrlStaleYoungOfWord(m) &&
          gdakiCtrlStaleOfWord(m) == 120 && m == gdakiCtrlStaleWord(true, 120));
    CHECK(!gdakiCtrlStaleYoungOfWord(GDAKI_CTRL_STALE_UNSEEN) &&
          gdakiCtrlStaleWordAged(false, 120, true) == GDAKI_CTRL_STALE_UNSEEN &&
          gdakiCtrlStaleOfWord(GDAKI_CTRL_STALE_UNSEEN) == -1.0);
    CHECK(gdakiCtrlViewAgeOk(9800, kStall, kProbe) && !gdakiCtrlViewAgeOk(9799, kStall, kProbe));
  }
  // the mail order and the re-check
  const uint32_t wDepC = gdakiCtrlRoleWord(GDAKI_CTRL_ROLE_SOURCE, GDAKI_CTRL_WG_CLOSED, false);
  const uint32_t wDepO = gdakiCtrlRoleWord(GDAKI_CTRL_ROLE_DEPENDENT, GDAKI_CTRL_WG_OPEN, false);
  const uint32_t wDepH = gdakiCtrlRoleWord(GDAKI_CTRL_ROLE_DEPENDENT, GDAKI_CTRL_WG_CLOSED, true);
  const uint32_t wSrc = gdakiCtrlRoleWord(GDAKI_CTRL_ROLE_SOURCE, GDAKI_CTRL_WG_NONE, false);
  const uint32_t wCyc = gdakiCtrlRoleWord(GDAKI_CTRL_ROLE_CYCLE, GDAKI_CTRL_WG_NONE, false);
  CHECK(gdakiCtrlRoleWordRole(wDepC) == GDAKI_CTRL_ROLE_DEPENDENT);  // closed: DEPENDENT whatever the snapshot said
  CHECK(gdakiCtrlStallMailFirst(true, wSrc) && gdakiCtrlStallMailFirst(true, wCyc) && !gdakiCtrlStallMailFirst(true, wDepC) &&
        !gdakiCtrlStallMailFirst(true, wDepO) && gdakiCtrlStallMailFirst(true, wDepH) && gdakiCtrlStallMailFirst(false, wDepC));
  CHECK(!gdakiCtrlStallMailKeep(true, wDepC) && gdakiCtrlStallMailKeep(true, wDepO) && gdakiCtrlStallMailKeep(true, wDepH) &&
        gdakiCtrlStallMailKeep(false, wDepC) && gdakiCtrlStallMailKeep(true, wSrc));
  printf("pure: element clock (rewrite held, torn READ, gap rule, first post), row T at 1800 ms, classifier (cell B, "
         "cycle, chain, cycle with a branch, disjoint cycle, self QP, ring), gate (sticky, quiet target, G, hard, two "
         "targets), cap 9999 / page word 9799 (guard FRESH; 9800, 9999 PASS; a host part passes), young view flag (value kept, old words as before, 9 800 ms age), mail order and re-check\n");
}

// ---- 2. the model ----
static const int MAXR = 4;
// One element's script: segments of kinds over time (ms ticks), each from its own start values.
enum Kind { K_PROG = 0, K_QUIET = 1, K_FROZEN = 2, K_ZERO = 3 };
struct Seg {
  double from;
  int kind;
  uint64_t p0, c0;
};
struct Elem {
  std::vector<Seg> s;
  Elem() { s.push_back({-1e18, K_QUIET, 0, 0}); }
  void at(double t, uint64_t* p, uint64_t* c) const {
    const Seg* g = &s[0];
    for (const Seg& x : s)
      if (x.from <= t) g = &x;
    const uint64_t m = g->kind == K_PROG ? (uint64_t)std::floor(t - g->from) : 0;
    switch (g->kind) {
      case K_PROG: *p = g->p0 + 2 + m; *c = g->p0 + m; break;
      case K_ZERO: *p = 0; *c = 0; break;
      default: *p = g->p0; *c = g->c0; break;
    }
  }
  // from `from` on: kind (FROZEN keeps a pending value, or posts 2 that are never polled; bump: one post and one poll)
  void set(double from, int kind, bool bump = false) {
    uint64_t p = 0, c = 0;
    at(from - 1e-6, &p, &c);
    Seg g{from, kind, p, c};
    if (kind == K_QUIET) g.c0 = g.p0 = p;
    if (kind == K_FROZEN && p <= c) g.p0 = p + 2;
    if (bump) {
      g.p0 = p + 1;
      g.c0 = c + 1;
    }
    while (!s.empty() && s.back().from >= from) s.pop_back();
    s.push_back(g);
  }
};

struct Mail {
  int p;
  uint32_t inc;
  bool gpu;
  double at;
};
struct Peer {  // observer O's probe of rank p
  double phase = 0;
  uint32_t pairInc = 0;          // the incarnation this pairing reads
  bool paired = true;            // the QP is RTS toward that incarnation
  struct gdakiCtrlStale watchStale, helperStale;
  std::vector<struct gdakiCtrlDevElem> e;
  struct gdakiCtrlStale ctxClk[MAXR];
  struct gdakiCtrlRMask wT;
  double wRaw = 0, wFirstMin = GDAKI_CTRL_FIRST_NONE, devOkMs = -1e18, lastOkMs = -1e18;
  int wCtx = -1;
  bool devSeen = false;
  struct gdakiCtrlWaitGate gate;
  uint32_t wEv = 0;
  int64_t wLineInc = -1;
  bool wHeld = false, needName = true;
  uint32_t roleWord = 0, latchedInc = 0, stallDrop = 0;
  std::vector<double> theirStale;
  std::vector<uint8_t> theirYoung;
  double viewSinceMs = -1e18;  // the first page READ of this pairing (the view's age)
};
struct Proc {
  int rank = 0;
  uint32_t inc = 0;
  bool alive = true;
  double startMs = -1e18;
  Peer peer[MAXR];
  std::vector<struct gdakiCtrlDevElem> selfE;
  struct gdakiCtrlRMask selfT;
  double selfWMs = -1e18, selfPhase = 0;
  struct gdakiCtrlRMask prevInZ;  // m7
  // the hold, by peer
  uint32_t hst[MAXR] = {};
  int heldPeer = -1;
  bool declined[MAXR] = {};
  uint32_t lnCur[MAXR] = {};
  bool asyncErr = false;
  double degradedAt = 0;
  std::deque<Mail> mails;
  bool helperDue = false;
  double helperFree = -1e18;
};
struct Proc;
enum { E_FN = 0, E_READ = 1, E_SELF = 2, E_HELPER = 3 };
struct Ev {
  double t;
  uint64_t seq;
  int type;
  Proc* o;
  int p;
  std::function<void()> f;
  bool operator<(const Ev& x) const { return t != x.t ? t > x.t : seq > x.seq; }
};
struct Judged {
  int obs, obsInc, p;
  double t;
};
struct Decl {
  int obs, p, action;
  double t;
};
struct Knobs {
  bool selfOff[MAXR] = {};             // the rank's process cannot read its own line locally
  bool noView[MAXR][MAXR] = {};        // [O][p]: O never reads p's line or page (a broken probe QP)
  bool pageUnread[MAXR][MAXR] = {};    // [O][k]: O cannot read k's page (k's view invalid at O)
  bool gap[MAXR] = {};                 // O's READs skip 250 ms every 1 500 ms
  bool spareUnread = false;            // nobody reads the restored incarnation's page (an ablation)
  std::function<bool(int, double)> veto;  // (p, t): the data path's veto holds p's GPU stall
  double hdelay = -1;                  // the helper's delay after a mail (-1: drawn)
  double phase[MAXR][MAXR + 1];        // fixed phases ([O][MAXR]: the self read), when fixedPhases
  bool fixedPhases = false;
};
struct World;
using Script = std::function<void(World&)>;
using OnRestored = std::function<void(World&, int, double)>;
struct World {
  int n = 4, spare = -1;
  double until = 30000;
  Knobs k;
  std::mt19937_64 rng;
  Elem line[MAXR][MAXR][MAXR];  // [rank][context][element]
  bool hostAlive[MAXR] = {true, true, true, true};
  std::vector<std::unique_ptr<Proc>> procs;
  int cur[MAXR] = {};
  std::priority_queue<Ev> q;
  uint64_t seq = 0;
  double now = 0;
  OnRestored onRestored;
  // the restore coordinator (the spare's rank)
  std::set<int> holding;
  bool fenced = false, restored = false, restoreFailed = false;
  double firstHolding = -1, restoredAt = -1;
  int committed = 0, holdEnded = 0;
  // results
  std::vector<Judged> judged;  // row 14 verdicts (the latch: once per (observer process, subject incarnation))
  std::vector<Decl> decls;
  int degradedN = 0, fallbackN = 0, holdStarts = 0, dropped = 0, waitBegan = 0;
  struct gdakiCtrlRMask gateTgt[MAXR][MAXR];  // [obs][subject]: every target a closed gate held
  double gateOpenAt[MAXR][MAXR];              // [obs][subject]: the first opening (-1: none), and how
  uint32_t gateHow[MAXR][MAXR] = {};
  double commitAt[MAXR] = {-1, -1, -1, -1}, fencedAt = -1;
  World() {
    for (auto& r : gateOpenAt)
      for (double& x : r) x = -1;
  }
  std::vector<std::string> trace;  // (바): the waiter's judgements as seen
  int traceSubject = -1;
  double traceUntil[MAXR];

  double U(double a, double b) { return std::uniform_real_distribution<double>(a, b)(rng); }
  void at(double t, std::function<void()> f) { q.push({t, seq++, E_FN, nullptr, 0, std::move(f)}); }
  void atEv(double t, int type, Proc* o, int p) { q.push({t, seq++, type, o, p, nullptr}); }
  Proc& P(int r) { return *procs[(size_t)cur[r]]; }
};

// The page word staleMs[q'] of process `o` at t (the beat step's computation, the glue of gdakiPageBeatStep).
static uint64_t pageWord(World& w, Proc& o, int qq, double t) {
  if (qq == o.rank) return GDAKI_CTRL_STALE_UNSEEN;
  Peer& pp = o.peer[qq];
  const bool seen = pp.watchStale.have;
  if (!seen) return GDAKI_CTRL_STALE_UNSEEN;
  double s = std::max(t - pp.watchStale.firstMs, pp.helperStale.have ? t - pp.helperStale.firstMs : 0.0);
  if (gMut == M1_OLD) {
    s = std::max(s, gdakiCtrlDevStaleAt(pp.ctxClk, (uint32_t)w.n, t));
  } else if (pp.wFirstMin != GDAKI_CTRL_FIRST_NONE) {
    const double raw = t - pp.wFirstMin;
    const bool closed = pp.gate.st == GDAKI_CTRL_WG_CLOSED;
    double g = gdakiCtrlWaitPageGpu(raw, closed, kStall, kProbe);
    if (gMut == M8_RAW_WORD) g = raw;
    if (gMut == M9_WORD_9999) g = closed ? std::min(raw, kStall - 1) : raw;
    s = std::max(s, g);
  }
  const bool young = pp.viewSinceMs < -1e17 || !gdakiCtrlViewAgeOk(t - pp.viewSinceMs, kStall, kProbe);
  return gdakiCtrlStaleWordAged(true, s, young);
}
static bool viewValid(World& w, Proc& o, int x, double t) {
  if (x == o.rank) return o.selfWMs > -1e17 && t - o.selfWMs <= 3.0 * kProbe;
  Peer& pp = o.peer[x];
  (void)w;
  return pp.devSeen && t - pp.devOkMs <= 3.0 * kProbe;
}
// the classifier under the mutations m5, m6 (the test's own copies of the rule they replace)
static void rolesOf(const struct gdakiCtrlRMask* t, uint32_t n, uint32_t* role) {
  if (gMut != M5_EXEMPT && gMut != M6_ONE_STEP) {
    gdakiCtrlStallRoles(t, n, role);
    return;
  }
  struct gdakiCtrlRMask z, src;
  for (uint32_t x = 0; x < n; x++)
    if (gdakiCtrlRMaskAny(t[x])) gdakiCtrlRMaskSet(&z, x);
  for (uint32_t x = 0; x < n; x++) {
    role[x] = GDAKI_CTRL_ROLE_NONE;
    if (!gdakiCtrlRMaskHas(z, x)) continue;
    bool out = gdakiCtrlRMaskHas(t[x], x);
    for (uint32_t k = 0; k < n; k++)
      if (gdakiCtrlRMaskHas(t[x], k) && !gdakiCtrlRMaskHas(z, k)) out = true;
    role[x] = out ? GDAKI_CTRL_ROLE_SOURCE : GDAKI_CTRL_ROLE_CYCLE;
    if (out) gdakiCtrlRMaskSet(&src, x);
  }
  for (uint32_t x = 0; x < n; x++)
    if (role[x] == GDAKI_CTRL_ROLE_CYCLE)
      role[x] = gMut == M5_EXEMPT || gdakiCtrlRMaskMeets(t[x], src) ? GDAKI_CTRL_ROLE_DEPENDENT : GDAKI_CTRL_ROLE_CYCLE;
}
// gdakiCtrlWaitStep's glue: one snapshot, the classifier, every gate (m3: the judged peer's only), the role words.
static void waitStep(World& w, Proc& o, int judgedP, double t) {
  const uint32_t n = (uint32_t)w.n;
  struct gdakiCtrlRMask tt[MAXR], inZ, seen, quiet;
  uint32_t role[MAXR], ev[MAXR];
  for (uint32_t x = 0; x < n; x++) {
    ev[x] = 0;
    const bool valid = viewValid(w, o, (int)x, t);
    if ((int)x == o.rank) {
      tt[x] = valid ? o.selfT : gdakiCtrlRMask();
    } else {
      Peer& px = o.peer[x];
      tt[x] = valid ? px.wT : gdakiCtrlRMask();
      const bool held = gdakiHoldIsHeldState(o.hst[x]);
      if (px.wHeld && !held) px.wEv++;
      px.wHeld = held;
      if (gdakiHoldIsQuietState(o.hst[x])) gdakiCtrlRMaskSet(&quiet, x);
      ev[x] = px.wEv;
    }
    if (valid) gdakiCtrlRMaskSet(&seen, x);
    if (gdakiCtrlRMaskAny(tt[x])) gdakiCtrlRMaskSet(&inZ, x);
  }
  rolesOf(tt, n, role);
  const double hard = gMut == M10_NO_HARD ? 1e18 : kHard;
  for (uint32_t x = 0; x < n; x++) {
    if ((int)x == o.rank) continue;
    if (gMut == M3_ONE_PEER && (int)x != judgedP) continue;
    Peer& px = o.peer[x];
    if (gdakiCtrlRMaskHas(seen, x)) {
      if (gMut == M7_RESET && px.gate.st == GDAKI_CTRL_WG_CLOSED) {  // a target left Z: X's clocks start again
        bool left = false;
        for (uint32_t k = 0; k < n; k++)
          if (gdakiCtrlRMaskHas(px.gate.tgt, k) && gdakiCtrlRMaskHas(o.prevInZ, k) && !gdakiCtrlRMaskHas(inZ, k)) left = true;
        if (left) {
          for (auto& el : px.e) el.s.firstMs = el.s.lastMs;
          px.wRaw = 0;
          px.wFirstMin = t;
        }
      }
      const uint32_t prev = px.gate.st;
      const uint32_t ge = gdakiCtrlWaitGateStep(&px.gate, role[x], tt[x], px.wRaw, inZ, seen, quiet, ev, n, t, kG, hard);
      if ((ge == GDAKI_CTRL_WGE_OPEN_G || ge == GDAKI_CTRL_WGE_OPEN_HARD) && o.inc == 0 && w.gateOpenAt[o.rank][x] < 0) {
        w.gateOpenAt[o.rank][x] = t;
        w.gateHow[o.rank][x] = ge;
      }
      if (prev == GDAKI_CTRL_WG_NONE && px.gate.st != GDAKI_CTRL_WG_NONE) w.waitBegan++;
      if (px.gate.st == GDAKI_CTRL_WG_CLOSED)
        for (uint32_t wd = 0; wd < GDAKI_CTRL_RMASK_W; wd++) w.gateTgt[o.rank][x].w[wd] |= px.gate.tgt.w[wd];
    }
    px.roleWord = gdakiCtrlRoleWord(gdakiCtrlRMaskHas(seen, x) ? role[x] : GDAKI_CTRL_ROLE_NONE, px.gate.st, px.wRaw >= hard);
  }
  o.prevInZ = inZ;
}
static void helperStep(World& w, Proc& o);
static void schedHelper(World& w, Proc& o, double t) {
  if (o.helperDue) return;
  o.helperDue = true;
  const double d = w.k.hdelay >= 0 ? w.k.hdelay : w.U(0.2, 1.5);
  w.atEv(std::max(t + d, o.helperFree), E_HELPER, &o, 0);
}
// gdakiProbeJudge's glue (one observer process, peer p) with the real R, guard and table
static void judge(World& w, Proc& o, int p, double t) {
  Peer& pp = o.peer[p];
  if (gMut != M1_OLD) waitStep(w, o, p, t);
  if (pp.stallDrop != 0 && pp.stallDrop == pp.latchedInc) pp.latchedInc = 0;
  pp.stallDrop = 0;
  struct gdakiCtrlRFacts f;
  f.okInGen = true;
  f.pageOk = true;
  f.watchRose = pp.watchStale.have && pp.watchStale.lastMs == pp.watchStale.firstMs;
  f.watchStaleMs = pp.watchStale.have ? pp.watchStale.lastMs - pp.watchStale.firstMs : 0;
  f.helperStaleMs = pp.helperStale.have ? pp.helperStale.lastMs - pp.helperStale.firstMs : 0;
  f.suspectMs = kSuspect;
  f.stallMs = kStall;
  f.devMode = true;
  f.devOk = pp.devSeen;
  if (gMut == M1_OLD) f.devStaleMs = gdakiCtrlDevStaleOf(pp.ctxClk, (uint32_t)w.n);
  else f.devStaleMs = gdakiCtrlWaitCap(pp.wRaw, pp.gate.st == GDAKI_CTRL_WG_CLOSED, kStall);
  double others[MAXR];
  bool valid[MAXR];
  int no = 0;
  for (int k = 0; k < w.n; k++) {
    if (k == o.rank || k == p) continue;
    Peer& pk = o.peer[k];
    others[no] = pk.theirStale.size() > (size_t)p ? pk.theirStale[(size_t)p] : -1.0;
    const double kStale = pk.watchStale.have ? pk.watchStale.lastMs - pk.watchStale.firstMs : 1e18;
    const bool young = gMut != M11_YOUNG && pk.theirYoung.size() > (size_t)p && pk.theirYoung[(size_t)p];
    valid[no] = t - pk.lastOkMs <= 3.0 * kProbe && kStale < kSuspect && !young;
    no++;
  }
  f.guardOk = gdakiCtrlPartitionGuard(others, valid, no, kStall, kProbe) == GDAKI_CTRL_PG_PASS;
  f.vetoClear = !(w.k.veto && w.k.veto(p, t));
  const uint32_t R = gdakiCtrlRDerive(f);
  const struct gdakiCtrlJudgement j = gdakiCtrlJudge(GDAKI_CTRL_L_NORESP, GDAKI_CTRL_B_NONE, GDAKI_CTRL_W_OK, R);
  {  // GC_WP_TRACE=<observer * 10 + peer> [GC_WP_FROM=<ms>] [GC_WP_ONLY=<scene>]: the judgements of 700 ms (debugging)
    static const char* tr = getenv("GC_WP_TRACE");
    static const char* only = getenv("GC_WP_ONLY");
    static const double from = getenv("GC_WP_FROM") != nullptr ? atof(getenv("GC_WP_FROM")) : 9800.0;
    if (tr != nullptr && strstr(gCur, only != nullptr ? only : "") != nullptr && atoi(tr) == o.rank * 10 + p &&
        t > from && t < from + 700) {
      fprintf(stderr, "   t=%.1f obs %d p %d raw=%.1f gate=%u word=%u R=%u row=%u guard:", t, o.rank, p, pp.wRaw,
              pp.gate.st, pp.roleWord, R, j.row);
      for (int i = 0; i < no; i++) fprintf(stderr, " %.1f/%d", others[i], (int)valid[i]);
      fprintf(stderr, "\n");
    }
  }
  if (p == w.traceSubject && t < w.traceUntil[o.rank]) {
    char b[96];
    snprintf(b, sizeof(b), "%d@%.0f:r%u g%u w%u", o.rank, t, gdakiCtrlRoleWordRole(pp.roleWord), pp.gate.st, j.row);
    w.trace.push_back(b);
  }
  if (j.verdict == GDAKI_CTRL_V_STALL && pp.latchedInc != pp.pairInc + 1u) {
    pp.latchedInc = pp.pairInc + 1u;
    w.judged.push_back({o.rank, (int)o.inc, p, t});
    o.mails.push_back({p, pp.pairInc, R == GDAKI_CTRL_R_STALL, t});
    schedHelper(w, o, t);
  }
}
static void broadcast(World& w, Proc& from, int kind, int peerOf);
static void coordCheck(World& w);
static void startProc(World& w, int rank, uint32_t inc, double t);
static void raiseDecline(World& w, Proc& o, double t) {
  if (o.degradedAt == 0) {  // gdakiUaRaisePeer: the first death schedules the degraded raise
    o.degradedAt = t + 2000;
    w.degradedN++;
  }
  o.asyncErr = true;
}
static void holdFallback(World& w, Proc& o, int qq, double t, bool tell) {
  if (!gdakiHoldIsHeldState(o.hst[qq])) return;
  o.hst[qq] = GDAKI_HOLD_FALLBACK;
  if (o.heldPeer == qq) o.heldPeer = -1;
  o.declined[qq] = true;
  w.fallbackN++;
  w.restoreFailed = true;
  raiseDecline(w, o, t);
  if (tell) broadcast(w, o, 1, qq);
}
// gdakiCtrlStallDecline -> gdakiTsDecline -> gdakiHoldOnDecline's glue, with the real gdakiHoldDeclineAction
static void stallDecline(World& w, Proc& o, int p, double t) {
  struct gdakiHoldDeclineIn in;
  in.state = o.hst[p];
  in.policyHold = true;
  in.commArmed = true;
  in.deathEvidence = true;
  in.strongCause = true;
  in.lostAfterCommit = false;
  in.otherHeld = o.heldPeer >= 0 && o.heldPeer != p;
  in.buddyReachable = true;
  in.stopping = false;
  if (in.state == GDAKI_HOLD_ARMED && !in.otherHeld)  // TOLD last (gdakiHoldTold: a degraded raise scheduled, async)
    in.told = o.degradedAt != 0 || o.asyncErr;
  const char* why = "";
  bool fbOther = false;
  const int a = gdakiHoldDeclineAction(in, &why, &fbOther);
  w.decls.push_back({o.rank, p, a, t});
  if (fbOther) holdFallback(w, o, o.heldPeer, t, true);
  switch (a) {
    case GDAKI_HOLD_D_FALLBACK: holdFallback(w, o, p, t, true); break;
    case GDAKI_HOLD_D_START: {
      o.hst[p] = GDAKI_HOLD_HELD;
      o.heldPeer = p;
      o.peer[p].paired = false;  // the hold start's ERR: no READ of p until the re-pairing
      w.holdStarts++;
      Proc* po = &o;
      w.at(t + w.U(1, 3), [&w, po, p] {
        if (p != w.spare || w.fenced || po->hst[p] != GDAKI_HOLD_HELD) return;
        if (w.firstHolding < 0) {  // the hold's deadline: 20 s from the first HOLDING
          w.firstHolding = w.now;
          w.at(w.now + 20000, [&w, p] {
            if (w.fenced) return;
            for (int r = 0; r < w.n; r++)
              if (r != p) holdFallback(w, w.P(r), p, w.now, false);
          });
        }
        w.holding.insert(po->rank);
        coordCheck(w);
      });
      break;
    }
    default:  // PASS, PASS_NOHOLD: the decline runs
      o.declined[p] = true;
      raiseDecline(w, o, t);
      if (a == GDAKI_HOLD_D_PASS_NOHOLD) {
        o.hst[p] = GDAKI_HOLD_OFF;
        broadcast(w, o, 0, p);
      }
  }
}
// NOHOLD (kind 0) and FALLBACK (kind 1) of peerOf to every other process, 1-5 ms later
static void broadcast(World& w, Proc& from, int kind, int peerOf) {
  for (int r = 0; r < w.n; r++) {
    if (r == from.rank) continue;
    Proc* po = &w.P(r);
    w.at(w.now + w.U(1, 5), [&w, po, kind, peerOf] {
      if (!po->alive) return;
      if (gdakiHoldIsHeldState(po->hst[peerOf])) holdFallback(w, *po, peerOf, w.now, false);
      else if (kind == 0 && po->hst[peerOf] == GDAKI_HOLD_ARMED) po->hst[peerOf] = GDAKI_HOLD_OFF;
    });
  }
}
// gdakiCtrlPageHelperStep's glue: the step's mails, SOURCE and CYCLE first, DEPENDENT re-checked (m1, m2: by rank)
static void helperStep(World& w, Proc& o) {
  o.helperDue = false;
  if (!o.alive) return;
  std::vector<Mail> ms(o.mails.begin(), o.mails.end());
  o.mails.clear();
  double t = w.now;
  std::sort(ms.begin(), ms.end(), [](const Mail& a, const Mail& b) { return a.p < b.p; });
  const bool asc = gMut == M1_OLD || gMut == M2_HELPER_ASC;
  for (int pass = 0; pass < 2; pass++)
    for (Mail& m : ms) {
      if (m.p < 0) continue;
      Peer& pp = o.peer[m.p];
      if (!asc && pass == 0 && !gdakiCtrlStallMailFirst(m.gpu, pp.roleWord)) continue;
      const int p = m.p;
      m.p = -1;
      if (!asc && pass == 1 && !gdakiCtrlStallMailKeep(m.gpu, pp.roleWord)) {
        pp.stallDrop = m.inc + 1u;
        w.dropped++;
        continue;
      }
      if (m.inc != o.lnCur[p] || o.declined[p]) continue;
      w.now = t;
      stallDecline(w, o, p, t);
      t += w.U(1.8, 3.7);  // the decline's own time; the next mail waits for it
    }
  o.helperFree = t;
  if (!o.mails.empty()) schedHelper(w, o, t);
}
// One READ (the page, then every context's line) of rank p by process o at t, then the judgement.
static void readPeer(World& w, Proc& o, int p, double t) {
  if (!o.alive) return;
  Peer& pp = o.peer[p];
  Proc& tp = w.P(p);
  const bool can = pp.paired && tp.alive && tp.inc == pp.pairInc && !w.k.noView[o.rank][p] &&
                   !(w.k.gap[o.rank] && std::fmod(t, 1500.0) >= 1000.0 && std::fmod(t, 1500.0) < 1250.0) &&
                   !(w.k.spareUnread && tp.inc > 0) && !w.k.pageUnread[o.rank][p];
  if (!can) return;
  // the page: the beats, the page words (the other's view of every rank, computed at t), the line's name
  (void)gdakiCtrlStaleOnRead(&pp.watchStale, w.hostAlive[p] ? (uint64_t)std::floor(t) + 1 : 1, t, kProbe);
  (void)gdakiCtrlStaleOnRead(&pp.helperStale, w.hostAlive[p] ? (uint64_t)std::floor(t) + 1 : 1, t, kProbe);
  pp.lastOkMs = t;
  if (pp.viewSinceMs < -1e17) pp.viewSinceMs = t;
  pp.theirStale.assign((size_t)w.n, -1.0);
  pp.theirYoung.assign((size_t)w.n, 0);
  for (int qq = 0; qq < w.n; qq++) {
    const uint64_t word = pageWord(w, tp, qq, t);
    pp.theirStale[(size_t)qq] = gdakiCtrlStaleOfWord(word);
    pp.theirYoung[(size_t)qq] = gdakiCtrlStaleYoungOfWord(word) ? 1 : 0;
  }
  if (pp.needName) {  // the line named on this pairing's page (another incarnation's: a resolution event)
    pp.needName = false;
    if (pp.wLineInc >= 0 && (int64_t)tp.inc != pp.wLineInc) pp.wEv++;
    pp.wLineInc = tp.inc;
  }
  // the lines
  const uint32_t n = (uint32_t)w.n;
  const bool gated = pp.gate.st != GDAKI_CTRL_WG_NONE;  // closed, or opened and X still in Z
  for (uint32_t c = 0; c < n; c++) {
    struct gdakiCtrlDevSum sum;
    for (uint32_t k = 0; k < n; k++) {
      struct gdakiCtrlDevSum d;
      w.line[p][c][k].at(t, &d.posted, &d.polled);
      d.pending = d.posted > d.polled ? d.posted - d.polled : 0;
      sum.posted += d.posted;
      sum.polled += d.polled;
      sum.pending += d.pending;
      const bool hold = gMut != M4_NO_REWRITE && gated && gdakiCtrlRMaskHas(pp.gate.tgt, k);
      (void)gdakiCtrlDevElemOnRead(&pp.e[c * n + k], d, t, kProbe, hold);
    }
    (void)gdakiCtrlDevOnRead(&pp.ctxClk[c], sum, t, kProbe);
  }
  pp.wRaw = gdakiCtrlStallTargets(pp.e.data(), n, n, kTz, &pp.wT, &pp.wCtx, &pp.wFirstMin);
  pp.devOkMs = t;
  pp.devSeen = true;
  judge(w, o, p, t);
}
static void readSelf(World& w, Proc& o, double t) {
  if (!o.alive || w.k.selfOff[o.rank]) return;
  const uint32_t n = (uint32_t)w.n;
  for (uint32_t c = 0; c < n; c++)
    for (uint32_t k = 0; k < n; k++) {
      struct gdakiCtrlDevSum d;
      w.line[o.rank][c][k].at(t, &d.posted, &d.polled);
      d.pending = d.posted > d.polled ? d.posted - d.polled : 0;
      (void)gdakiCtrlDevElemOnRead(&o.selfE[c * n + k], d, t, kProbe, false);
    }
  (void)gdakiCtrlStallTargets(o.selfE.data(), n, n, kTz, &o.selfT);
  o.selfWMs = t;
}
static void startProc(World& w, int rank, uint32_t inc, double t) {
  std::unique_ptr<Proc> pr(new Proc());
  pr->rank = rank;
  pr->inc = inc;
  pr->startMs = t;
  pr->selfE.assign((size_t)w.n * w.n, gdakiCtrlDevElem());
  for (int p = 0; p < w.n; p++) {
    pr->peer[p].e.assign((size_t)w.n * w.n, gdakiCtrlDevElem());
    pr->peer[p].phase = w.k.fixedPhases ? w.k.phase[rank][p] : w.U(0, 100);
    pr->hst[p] = p == w.spare && p != rank ? GDAKI_HOLD_ARMED : GDAKI_HOLD_OFF;
    pr->peer[p].pairInc = p == rank ? 0 : w.procs.empty() || w.cur[p] >= (int)w.procs.size() ? 0 : 0;
  }
  pr->selfPhase = w.k.fixedPhases ? w.k.phase[rank][MAXR] : w.U(0, 100);
  Proc* po = pr.get();
  w.procs.push_back(std::move(pr));
  w.cur[rank] = (int)w.procs.size() - 1;
  // the periodic READs and the local read
  for (int p = 0; p < w.n; p++) {
    if (p == rank) continue;
    w.atEv(std::ceil((t - po->peer[p].phase) / kProbe) * kProbe + po->peer[p].phase, E_READ, po, p);
  }
  w.atEv(std::ceil((t - po->selfPhase) / kProbe) * kProbe + po->selfPhase, E_SELF, po, 0);
}
// The restore of the spare's rank q: every survivor HOLDING -> FENCE -> FENCED (the old process gone) -> the spare's
// incarnation; per survivor: the commit (its QPs to q rewritten to (0, 0)), PUBLISHED, the re-pairing of its probe of q,
// the hold's end. The hold's deadline (20 s from the first HOLDING) falls back.
static void coordCheck(World& w);
static void coordinator(World& w) { (void)w; }  // event-driven: coordCheck at every HOLDING, the deadline's event
static void repair(World& w, Proc* po, int q) {  // the re-pairing of po's probe of q with the restored incarnation
  if (w.restoreFailed) return;
  Peer& pp = po->peer[q];
  const uint32_t ev = pp.wEv;  // kept: this peer's resolution events as a target (gdakiProbeDevReset keeps them)
  const int64_t li = pp.wLineInc;
  const bool held = pp.wHeld;
  const size_t ne = pp.e.size();
  pp = Peer();
  pp.e.assign(ne, gdakiCtrlDevElem());
  pp.wEv = ev;
  pp.wLineInc = li;
  pp.wHeld = held;
  pp.pairInc = 1;
  pp.paired = true;
  po->lnCur[q] = 1;
}
static void coordCheck(World& w) {
  const int q = w.spare;
  if (w.fenced || q < 0 || w.restoreFailed) return;
  for (int r = 0; r < w.n; r++)
    if (r != q && !w.holding.count(r)) return;
  w.fenced = true;
  const double tf = w.now + 2 + w.U(40, 100);
  w.at(tf, [&w, q, tf] {  // FENCED: the old process is gone
    if (w.restoreFailed) return;
    w.P(q).alive = false;
    w.fencedAt = tf;
    for (int c = 0; c < w.n; c++)
      for (int k = 0; k < w.n; k++) w.line[q][c][k].set(tf, K_ZERO);
    const double ts = tf + w.U(100, 150);
    w.at(ts, [&w, q, ts] {  // the spare's incarnation
      if (w.restoreFailed) return;
      startProc(w, q, 1, ts);
      w.restoredAt = ts;
    });
    for (int r = 0; r < w.n; r++) {
      if (r == q) continue;
      Proc* po = &w.P(r);
      const double tc = ts + w.U(30, 120);
      w.at(tc, [&w, po, q, tc] {  // this survivor's commit: its QPs to q rewritten to (0, 0)
        if (!gdakiHoldIsHeldState(po->hst[q])) return;
        po->hst[q] = GDAKI_HOLD_COMMITTING;
        w.committed++;
        w.commitAt[po->rank] = tc;
        for (int c = 0; c < w.n; c++) w.line[po->rank][c][q].set(tc, K_ZERO);
        const double tp = tc + w.U(5, 20);
        w.at(tc + w.U(20, 80), [&w, po, q] { repair(w, po, q); });
        w.at(tp, [&w, po, q, tp] {
          if (po->hst[q] != GDAKI_HOLD_COMMITTING) return;
          po->hst[q] = GDAKI_HOLD_PUBLISHED;
          w.at(tp + w.U(10, 40), [&w, po, q] {  // the hold's end (INJECTED)
            if (po->hst[q] != GDAKI_HOLD_PUBLISHED) return;
            po->hst[q] = GDAKI_HOLD_OFF;
            po->heldPeer = -1;
            w.holdEnded++;
            if (w.holdEnded == w.n - 1 && !w.restoreFailed) {
              w.restored = true;
              if (w.onRestored) w.onRestored(w, q, w.now);
            }
          });
        });
      });
    }
  });
}
static void runWorld(World& w) {
  while (!w.q.empty()) {
    Ev e = w.q.top();
    w.q.pop();
    if (e.t > w.until + 1) break;
    w.now = e.t;
    switch (e.type) {
      case E_READ:
        if (!e.o->alive) break;
        readPeer(w, *e.o, e.p, e.t);
        w.atEv(e.t + kProbe, E_READ, e.o, e.p);
        break;
      case E_SELF:
        if (!e.o->alive) break;
        readSelf(w, *e.o, e.t);
        w.atEv(e.t + kProbe, E_SELF, e.o, 0);
        break;
      case E_HELPER: helperStep(w, *e.o); break;
      default: e.f(); break;
    }
  }
}
// every rank's used elements (context = destination) progress before the scene
static void baseline(World& w) {
  for (int r = 0; r < w.n; r++)
    for (int k = 0; k < w.n; k++)
      if (k != r) w.line[r][k][k].set(-2000, K_PROG);
}
static void freezeTo(World& w, int r, std::initializer_list<int> ks, double t) {  // r stops with pending toward ks
  for (int k = 0; k < w.n; k++) {
    if (k == r) continue;
    bool f = false;
    for (int x : ks) f = f || x == k;
    w.line[r][k][k].set(t, f ? K_FROZEN : K_QUIET);
  }
}
static void quietAll(World& w, int r, double t) { freezeTo(w, r, {}, t); }
static void resume(World& w, int r, double t) {
  for (int k = 0; k < w.n; k++)
    if (k != r) w.line[r][k][k].set(t, K_PROG);
}
static void prepare(World& w, uint64_t seed, int n, int spare, double until) {
  w.rng.seed(seed);
  w.n = n;
  w.spare = spare;
  w.until = until;
  baseline(w);
}
static void launch(World& w) {
  for (int r = 0; r < w.n; r++) startProc(w, r, 0, -1000);
  coordinator(w);
  runWorld(w);
}
// results
static double firstJudged(const World& w, int p, int obs = -1, double after = -1e18) {
  double m = -1;
  for (const Judged& j : w.judged)
    if (j.p == p && (obs < 0 || j.obs == obs) && j.t >= after && (m < 0 || j.t < m)) m = j.t;
  return m;
}
static int judgedN(const World& w, int p) {
  int c = 0;
  for (const Judged& j : w.judged) c += j.p == p;
  return c;
}
static int nonHoldDecls(const World& w) {
  int c = 0;
  for (const Decl& d : w.decls) c += d.action != GDAKI_HOLD_D_START;
  return c;
}

static void dump(const World& w, const char* what) {
  if (getenv("GC_WP_DEBUG") == nullptr || gQuiet) return;
  fprintf(stderr, "-- %s: restored=%d failed=%d restoredAt=%.1f holdStarts=%d fallbacks=%d degraded=%d dropped=%d\n",
          what, (int)w.restored, (int)w.restoreFailed, w.restoredAt, w.holdStarts, w.fallbackN, w.degradedN, w.dropped);
  for (const Judged& j : w.judged) fprintf(stderr, "   judged: obs %d (inc %d) -> rank %d at %.1f\n", j.obs, j.obsInc, j.p, j.t);
  for (const Decl& d : w.decls) fprintf(stderr, "   decline: obs %d -> rank %d action %d at %.1f\n", d.obs, d.p, d.action, d.t);
}
// The scene's verdict: 0 passed; else a failure (the mutation runs count them). `strict`: CHECK each condition.
struct SceneStat {
  const char* name;
  long runs = 0, failed = 0;
};
static std::vector<SceneStat> gStats;
static SceneStat& stat(const char* name) {
  for (auto& s : gStats)
    if (!strcmp(s.name, name)) return s;
  gStats.push_back({name});
  return gStats.back();
}
#define SCENE_CHECK(st, c)       \
  do {                           \
    const long f0 = gFailed;     \
    CHECK(c);                    \
    if (gFailed != f0) bad = true; \
  } while (0)

// ---- the scenes ----
// Cell B: src hangs at 0 with pending toward every other rank, the waiter stops at delta with pending toward src only,
// the other ranks are quiet receivers. variant 1: the waiter leads (delta in [-300, 0]); 2: the source a period ahead
// (delta in [100, 300]); 3: the numbers swapped (waiter 3 > source 1). healthy: the waiter resumes after the restore.
struct CellB {
  int src, wait;
  double delta;
};
static CellB cellB(World& w, int variant, bool healthy, bool stuckSpareUnread) {
  CellB c{3, 1, 0};
  if (variant == 3) c = {1, 3, 0};
  c.delta = variant == 1 ? w.U(-300, 0) : variant == 2 ? w.U(100, 300) : w.U(-300, 300);
  freezeTo(w, c.src, {0, 1, 2, 3}, 0);
  freezeTo(w, c.wait, {c.src}, c.delta);
  for (int r = 0; r < w.n; r++)
    if (r != c.src && r != c.wait) quietAll(w, r, w.U(0, 30));
  const int wt = c.wait;
  w.k.spareUnread = stuckSpareUnread;
  w.onRestored = [healthy, wt](World& ww, int q, double ta) {
    for (int r = 0; r < ww.n; r++) {
      if (r == wt && !healthy) continue;
      resume(ww, r, ta + ww.U(80, 200));
    }
    (void)q;
  };
  return c;
}
static bool sceneCellB(uint64_t seed, int variant, bool strict) {
  World w;
  prepare(w, seed, 4, variant == 3 ? 1 : 3, 26000);
  const CellB c = cellB(w, variant, true, false);
  launch(w);
  bool bad = false;
  SceneStat& st = stat(variant == 1 ? "B1 waiter leads" : variant == 2 ? "B2 source ahead" : "B3 waiter > source");
  st.runs++;
  (void)strict;
  // the source alone: row 14 at every survivor near STALL_MS, the holds, the restore; the waiter never; no degraded
  for (int r = 0; r < 4; r++) {
    if (r == c.src) continue;
    const double t = firstJudged(w, c.src, r);
    SCENE_CHECK(st, t >= 9990 && t <= 10400);
  }
  SCENE_CHECK(st, judgedN(w, c.wait) == 0);
  SCENE_CHECK(st, w.restored && !w.restoreFailed && w.holdStarts == 3);
  SCENE_CHECK(st, w.degradedN == 0 && nonHoldDecls(w) == 0);
  SCENE_CHECK(st, w.waitBegan >= 2);
  if (bad) st.failed++;
  if (bad) dump(w, st.name);
  return !bad;
}
// the waiter itself stuck (only toward the source): after the restore it does not move. spareUnread: the restored
// incarnation's page is not read by the others (its young view is no FRESH witness); else as on the cluster.
static bool sceneStuckWaiter(uint64_t seed, bool spareUnread) {
  World w;
  prepare(w, seed, 4, 3, 40000);
  const CellB c = cellB(w, 2, false, spareUnread);
  launch(w);
  bool bad = false;
  SceneStat& st = stat(spareUnread ? "stuck waiter (spare's page unread)" : "stuck waiter (spare's view counted)");
  st.runs++;
  SCENE_CHECK(st, w.restored && !w.restoreFailed);
  const double tw = firstJudged(w, c.wait);
  // judged after the restore within G and a few periods of the last survivor's hold end (never during the restore). With
  // the spare's page read: its view of the waiter is young (the commit made the element (0, 0): quiet to it) and is no
  // witness of the guard (m11 counts it FRESH: the waiter is never judged)
  SCENE_CHECK(st, w.restored && tw >= w.restoredAt + kG && tw <= w.restoredAt + kG + 700);
  if (bad) st.failed++;
  if (bad) dump(w, st.name);
  return !bad;
}
// a two-rank cycle 1 <-> 3 in four ranks, and a two-rank communicator (0 <-> 1)
static bool sceneCycle(uint64_t seed, bool twoRanks) {
  World w;
  const int n = twoRanks ? 2 : 4;
  const int a = twoRanks ? 1 : 3, b = twoRanks ? 0 : 1;
  prepare(w, seed, n, a, 24000);
  const double d = w.U(-300, 300);
  freezeTo(w, a, {b}, 0);
  freezeTo(w, b, {a}, d);
  for (int r = 0; r < n; r++)
    if (r != a && r != b) quietAll(w, r, w.U(0, 30));
  launch(w);
  bool bad = false;
  SceneStat& st = stat(twoRanks ? "(사) cycle of a two-rank communicator" : "(사) cycle 1<->3 of four");
  st.runs++;
  const double ta = firstJudged(w, a), tb = firstJudged(w, b);
  // a (the spare's rank) at STALL_MS; b at STALL_MS too, unless the restore came first: two ranks, a's process fenced
  // before b's mark (no one else sees b); four ranks, b's own commit rewrote its pending QP to (0, 0) before its mark
  // (b is not gated: a CYCLE; the residual is counted, notes_waitpeer.md)
  SCENE_CHECK(st, ta >= 9990 && ta <= 10400);
  const bool bJudged = tb >= d + 9990 && tb <= d + 10400;
  const bool bFirst = twoRanks ? w.fencedAt >= 0 && w.fencedAt < d + 10400
                               : w.commitAt[b] >= 0 && w.commitAt[b] < d + 10400 && tb < 0;
  SCENE_CHECK(st, bJudged || bFirst);
  // b judged during a's hold: its decline ends the hold; after the restore: a second failure (the restore stands)
  if (!twoRanks) SCENE_CHECK(st, bJudged ? !w.restored || tb >= w.restoredAt : w.restored);
  if (!bJudged) (twoRanks ? gCycleLate2 : gCycleLate4)++;
  if (bad) st.failed++;
  if (bad) dump(w, st.name);
  return !bad;
}
// a chain X=0 -> q=1 -> s=2 -> {3 quiet}
static bool sceneChain(uint64_t seed) {
  World w;
  prepare(w, seed, 4, 2, 26000);
  const double d1 = w.U(0, 300), d2 = d1 + w.U(0, 300);
  freezeTo(w, 2, {3}, 0);
  freezeTo(w, 1, {2}, d1);
  freezeTo(w, 0, {1}, d2);
  quietAll(w, 3, w.U(0, 30));
  w.onRestored = [](World& ww, int, double ta) {
    const double t1 = ta + ww.U(80, 200);
    resume(ww, 1, t1);
    resume(ww, 0, t1 + ww.U(20, 150));
    resume(ww, 3, ta + ww.U(80, 200));
  };
  launch(w);
  bool bad = false;
  SceneStat& st = stat("chain 0->1->2");
  st.runs++;
  for (int r : {0, 1, 3}) {
    const double t = firstJudged(w, 2, r);
    SCENE_CHECK(st, t >= 9990 && t <= 10400);
  }
  SCENE_CHECK(st, judgedN(w, 0) == 0 && judgedN(w, 1) == 0);
  SCENE_CHECK(st, w.restored && w.degradedN == 0);
  if (bad) st.failed++;
  if (bad) dump(w, st.name);
  return !bad;
}
// (마): the chain's middle alone stuck; the end waiter alone stuck; two sources; a cycle with a branch to a source
static bool sceneMa(uint64_t seed, int kind) {
  World w;
  static const char* names[4] = {"(마) middle only", "(마) end waiter only", "(마) two sources",
                                 "(마) cycle with a branch to a source"};
  bool bad = false;
  SceneStat& st = stat(names[kind]);
  st.runs++;
  if (kind == 0) {  // 0 -> 1, 1 stuck toward 2 (a quiet receiver)
    prepare(w, seed, 4, 1, 26000);
    freezeTo(w, 1, {2}, 0);
    freezeTo(w, 0, {1}, w.U(0, 300));
    quietAll(w, 2, w.U(0, 30));
    quietAll(w, 3, w.U(0, 30));
    w.onRestored = [](World& ww, int, double ta) {
      for (int r : {0, 2, 3}) resume(ww, r, ta + ww.U(80, 200));
    };
    launch(w);
    for (int r : {0, 2, 3}) {
      const double t = firstJudged(w, 1, r);
      SCENE_CHECK(st, t >= 9990 && t <= 10400);
    }
    SCENE_CHECK(st, judgedN(w, 0) == 0 && w.restored && w.degradedN == 0);
  } else if (kind == 1) {  // 0 stuck toward 1 (quiet): 0 is the source
    prepare(w, seed, 4, 0, 26000);
    freezeTo(w, 0, {1}, 0);
    for (int r : {1, 2, 3}) quietAll(w, r, w.U(0, 30));
    w.onRestored = [](World& ww, int, double ta) {
      for (int r : {1, 2, 3}) resume(ww, r, ta + ww.U(80, 200));
    };
    launch(w);
    for (int r : {1, 2, 3}) {
      const double t = firstJudged(w, 0, r);
      SCENE_CHECK(st, t >= 9990 && t <= 10400);
    }
    SCENE_CHECK(st, w.restored && w.degradedN == 0);
  } else if (kind == 2) {  // 0 -> {1, 2}; 1 and 2 stuck toward 3 (quiet); no spare (both are declined)
    prepare(w, seed, 4, -1, 26000);
    freezeTo(w, 1, {3}, 0);
    freezeTo(w, 2, {3}, w.U(0, 300));
    const double d = w.U(0, 300);
    freezeTo(w, 0, {1, 2}, d);
    quietAll(w, 3, w.U(0, 30));
    launch(w);
    const double t1 = firstJudged(w, 1), t2 = firstJudged(w, 2), t0 = firstJudged(w, 0);
    SCENE_CHECK(st, t1 >= 9990 && t1 <= 10400 && t2 >= 9990 && t2 <= 10700);
    // neither resolves (declined, still in Z): the hard bound; the gate waited on both
    SCENE_CHECK(st, t0 >= d + 19990 && t0 <= d + 20500 && w.gateTgt[3][0].w[0] == 0x6u);
  } else {  // 0 <-> 1, 1 -> 2, 2 stuck toward 3
    prepare(w, seed, 4, 2, 26000);
    freezeTo(w, 2, {3}, 0);
    freezeTo(w, 1, {0, 2}, w.U(0, 300));
    freezeTo(w, 0, {1}, w.U(0, 300));
    quietAll(w, 3, w.U(0, 30));
    w.onRestored = [](World& ww, int, double ta) {
      const double t1 = ta + ww.U(80, 200);
      resume(ww, 1, t1);
      resume(ww, 0, t1 + ww.U(20, 150));
      resume(ww, 3, ta + ww.U(80, 200));
    };
    launch(w);
    for (int r : {0, 1, 3}) {
      const double t = firstJudged(w, 2, r);
      SCENE_CHECK(st, t >= 9990 && t <= 10400);
    }
    SCENE_CHECK(st, judgedN(w, 0) == 0 && judgedN(w, 1) == 0 && w.restored && w.degradedN == 0);
  }
  if (bad) st.failed++;
  if (bad) dump(w, st.name);
  return !bad;
}
// (라): 1. q moves every 2.5 s and X is stuck toward q; 2. 20 s pass, q ARMED with no hold (its stall held by the veto);
// 3. q's hold starts just before X's hard bound; 4. READ gaps over 200 ms again and again (one observer; every one).
static bool sceneLa(uint64_t seed, int kind) {
  World w;
  static const char* names[5] = {"(라)1 q moves every 2.5 s", "(라)2 20 s, q armed, no hold", "(라)3 HELD just before",
                                 "(라)4 one observer's READ gaps", "(라)4 every observer's READ gaps"};
  bool bad = false;
  SceneStat& st = stat(names[kind]);
  st.runs++;
  gCur = names[kind];
  prepare(w, seed, 4, 3, 24000);
  const double d = w.U(0, 50);
  if (kind == 0) {
    freezeTo(w, 3, {0}, 0);
    for (double t = 2500; t < 24000; t += 2500) w.line[3][0][0].set(t, K_FROZEN, true);
  } else {
    freezeTo(w, 3, {0, 1, 2}, 0);
  }
  freezeTo(w, 1, {3}, d);
  quietAll(w, 0, w.U(0, 30));
  quietAll(w, 2, w.U(0, 30));
  if (kind == 1) w.k.veto = [](int p, double) { return p == 3; };
  double tv = 0;
  if (kind == 2) {
    tv = 19800 + w.U(0, 50);
    w.k.veto = [tv](int p, double t) { return p == 3 && t < tv; };
  }
  if (kind == 3) w.k.gap[0] = true;
  if (kind == 4)
    for (int r = 0; r < 4; r++) w.k.gap[r] = true;
  w.onRestored = [](World& ww, int, double ta) {  // X (rank 1) is stuck: it does not move after a restore
    for (int r : {0, 2}) resume(ww, r, ta + ww.U(80, 200));
  };
  launch(w);
  const double tx = firstJudged(w, 1);
  if (kind <= 2) {
    SCENE_CHECK(st, tx >= d + 19990 && tx <= d + 20500);  // the hard bound, whatever q's state
    if (kind == 1) SCENE_CHECK(st, judgedN(w, 3) == 0 && w.holdStarts == 0);
    if (kind == 2) {  // the gate opens at the hard bound with q already HELD (the hold started first)
      for (int r : {0, 2})
        SCENE_CHECK(st, w.gateHow[r][1] == GDAKI_CTRL_WGE_OPEN_HARD && w.gateOpenAt[r][1] >= d + 19990 &&
                            w.gateOpenAt[r][1] <= d + 20200 && w.firstHolding >= 0 && w.firstHolding < w.gateOpenAt[r][1]);
      gLa3Runs++;
      gLa3Judged += tx >= 0;
    }
  } else {  // nobody judges (a limit, the existing rules): the gapped observer's clocks start again at every gap, and its
            // young view is FRESH in the others' guard
    SCENE_CHECK(st, w.judged.empty());
  }
  if (bad) st.failed++;
  if (bad) dump(w, st.name);
  return !bad;
}
// (나): cell B where observer 0 never reads rank 3 (rank 1 is a SOURCE to it). 1: rank 2 and rank 3 see rank 1
// DEPENDENT, their page words (9 799) make observer 0's guard FRESH; 2: rank 3 cannot read its own line and observer 0
// cannot read rank 2's page: the only valid opponent sees rank 1 as a SOURCE (raw): observer 0 judges rank 1 (the
// residual of an invalid opponent, recorded).
static bool sceneNa(uint64_t seed, int kind) {
  World w;
  bool bad = false;
  SceneStat& st = stat(kind == 1 ? "(나)1 valid opponent" : "(나)2 invalid opponent (residual)");
  st.runs++;
  prepare(w, seed, 4, 3, 19500);  // before the hard bound (no restore: observer 0 never holds rank 3)
  const CellB c = cellB(w, 1, true, false);
  w.k.noView[0][3] = true;
  if (kind == 2) w.k.noView[2][3] = true;
  launch(w);
  const double t0 = firstJudged(w, c.wait, 0), t2 = firstJudged(w, c.wait, 2);
  if (kind == 1) SCENE_CHECK(st, t0 < 0 && judgedN(w, c.wait) == 0);
  else SCENE_CHECK(st, t0 >= c.delta + 9990 && t0 <= c.delta + 10500 && t2 >= c.delta + 9990 && t2 <= c.delta + 10500 &&
                       firstJudged(w, c.wait, 3) < 0);
  if (bad) st.failed++;
  if (bad) dump(w, st.name);
  return !bad;
}
// (바): the same trace with two meanings (the waiter healthy, the waiter stuck): the observers' view of it (role, gate,
// row) is the same until the first resolution; after it, the healthy one moves and the stuck one is judged.
static bool sceneBa(uint64_t seed) {
  bool bad = false;
  SceneStat& st = stat("(바) one trace, two meanings");
  st.runs++;
  std::vector<std::string> tr[2];
  double tj[2] = {-1, -1};
  for (int m = 0; m < 2; m++) {
    World w;
    prepare(w, seed, 4, 3, 30000);
    const CellB c = cellB(w, 2, m == 0, true);
    w.traceSubject = c.wait;
    for (int r = 0; r < 4; r++) w.traceUntil[r] = 10000;  // before any hold: both meanings look the same
    launch(w);
    tr[m] = w.trace;
    tj[m] = firstJudged(w, c.wait);
  }
  SCENE_CHECK(st, !tr[0].empty() && tr[0] == tr[1]);
  SCENE_CHECK(st, tj[0] < 0 && tj[1] > 0);
  if (bad) st.failed++;
  return !bad;
}
// The race: a two-rank cycle 1 <-> 3 turns into a source (3 gets a stalled QP toward a quiet rank 0) within observer 0's
// helper step: rank 1's mail (CYCLE when made) and rank 3's (SOURCE) come in one step; the helper takes 3 first and
// drops 1's (DEPENDENT now). Fixed phases (one run).
static bool sceneRace() {
  World w;
  bool bad = false;
  SceneStat& st = stat("race: a cycle turns into a source in one helper step");
  st.runs++;
  w.k.fixedPhases = true;
  const double ph[4][5] = {{0, 50, 2, 51, 5}, {40, 0, 45, 20, 15}, {30, 60, 0, 10, 25}, {75, 70, 80, 0, 5}};
  memcpy(w.k.phase, ph, sizeof(ph));
  w.k.hdelay = 1.6;
  prepare(w, 7, 4, 3, 24000);
  freezeTo(w, 3, {1}, 0);
  w.line[3][0][0].set(-2000, K_PROG);
  w.line[3][0][0].set(8200.5, K_FROZEN);
  freezeTo(w, 1, {3}, 0);
  quietAll(w, 0, 0);
  quietAll(w, 2, 0);
  w.onRestored = [](World& ww, int, double ta) {
    for (int r : {0, 1, 2}) resume(ww, r, ta + 100);
  };
  launch(w);
  SCENE_CHECK(st, judgedN(w, 1) >= 0 && w.restored && !w.restoreFailed && w.degradedN == 0 && nonHoldDecls(w) == 0);
  SCENE_CHECK(st, firstJudged(w, 1, 0) == 10050 && w.dropped >= 1);  // the mail was made, and dropped
  if (bad) st.failed++;
  if (bad) dump(w, st.name);
  return !bad;
}
// the ring allreduce shape (failure 1: X waits on X-1, pending toward X+1): reported only
static void sceneRing(uint64_t seed, int* judgedRanks, bool* restored) {
  World w;
  prepare(w, seed, 4, 3, 24000);
  freezeTo(w, 3, {0}, 0);
  freezeTo(w, 0, {1}, w.U(0, 300));
  freezeTo(w, 1, {2}, w.U(0, 300));
  freezeTo(w, 2, {3}, w.U(0, 300));
  launch(w);
  *judgedRanks = 0;
  for (int r = 0; r < 4; r++) *judgedRanks += judgedN(w, r) > 0;
  *restored = w.restored;
}

// (다): the restore phase at the gate's level, one observer (0), waiter X = 1, target q = 3 held from 10 000: the five
// events A (q's restored line named), B (X's element rewritten to (0, 0)), C (a stall mail of X at the helper), D (the
// hold's end), E (X's first post) in every order, gaps drawn; with E (healthy) and without (stuck).
static int scenePhases(uint64_t seed, long* runs, long* perms) {
  std::mt19937_64 rng(seed);
  std::uniform_real_distribution<double> gap(10, 400), ph(0, 100);
  int fails = 0;
  int order[5] = {0, 1, 2, 3, 4};
  do {
    (*perms)++;
    for (int healthy = 0; healthy < 2; healthy++)
      for (int draw = 0; draw < 4; draw++) {
        (*runs)++;
        double at[5];
        double t = 10100;
        for (int i = 0; i < 5; i++) {
          t += gap(rng);
          at[order[i]] = t;
        }
        const double A = at[0], B = at[1], C = at[2], D = at[3], E = healthy ? at[4] : 1e18;
        const double phase = ph(rng);
        std::vector<struct gdakiCtrlDevElem> e(16);
        struct gdakiCtrlWaitGate g;
        uint32_t ev[4] = {0, 0, 0, 0};
        bool wHeld = false, mailChecked = false, ok = true;
        double judgedAt = -1, resAt = -1;
        for (double tt = phase; tt < (healthy ? 16000 : 26000); tt += kProbe) {
          // X's element toward q: frozen at 0, (0, 0) from B, posting from E
          struct gdakiCtrlDevSum d;
          if (tt >= E) {
            d.posted = 2 + (uint64_t)(tt - E);
            d.polled = (uint64_t)(tt - E);
          } else if (tt >= B) {
            d.posted = d.polled = 0;
          } else {
            d.posted = 12;
            d.polled = 10;
          }
          d.pending = d.posted > d.polled ? d.posted - d.polled : 0;
          const bool gated = g.st != GDAKI_CTRL_WG_NONE;
          (void)gdakiCtrlDevElemOnRead(&e[3 * 4 + 3], d, tt, kProbe, gMut != M4_NO_REWRITE && gated &&
                                                                         gdakiCtrlRMaskHas(g.tgt, 3));
          struct gdakiCtrlRMask tX;
          int ctx = -1;
          const double raw = gdakiCtrlStallTargets(e.data(), 4, 4, kTz, &tX, &ctx);
          // q: in Z (a source) until held; held (quiet) in [10 000, D); seen again from A, quiet (not in Z)
          const bool held = tt >= 10000 && tt < D;
          const bool qSeen = tt < 10000 || tt >= A;
          const bool qInZ = tt < 10000 && tt >= 1800;
          if (wHeld && !held) ev[3]++;  // the hold's end (D)
          wHeld = held;
          const uint32_t evA = tt >= A ? 1u : 0u;  // the restored line named (A)
          uint32_t evv[4] = {0, 0, 0, ev[3] + evA};
          struct gdakiCtrlRMask t4[4] = {gdakiCtrlRMask(), tX, gdakiCtrlRMask(), qInZ ? maskOf({0, 2}) : gdakiCtrlRMask()};
          uint32_t role[4];
          gdakiCtrlStallRoles(t4, 4, role);
          struct gdakiCtrlRMask inZ, seen = maskOf({0, 1, 2}), quiet;
          if (gdakiCtrlRMaskAny(tX)) gdakiCtrlRMaskSet(&inZ, 1);
          if (qInZ) gdakiCtrlRMaskSet(&inZ, 3);
          if (qSeen) gdakiCtrlRMaskSet(&seen, 3);
          if (held && tt < D) gdakiCtrlRMaskSet(&quiet, 3);
          (void)gdakiCtrlWaitGateStep(&g, role[1], tX, raw, inZ, seen, quiet, evv, 4, tt, kG,
                                      gMut == M10_NO_HARD ? 1e18 : kHard);
          if (g.resMs >= 0 && resAt < 0) resAt = g.resMs;
          if (held && g.st == GDAKI_CTRL_WG_OPEN) ok = false;  // never open while q is held
          if (!mailChecked && tt >= C) {
            mailChecked = true;
            const uint32_t word = gdakiCtrlRoleWord(role[1], g.st, raw >= kHard);
            if (g.st == GDAKI_CTRL_WG_CLOSED && gdakiCtrlStallMailKeep(true, word)) ok = false;
          }
          struct gdakiCtrlRFacts f;
          f.okInGen = true;
          f.devMode = true;
          f.devOk = true;
          f.watchRose = true;
          f.devStaleMs = gdakiCtrlWaitCap(raw, g.st == GDAKI_CTRL_WG_CLOSED, kStall);
          const uint32_t R = gdakiCtrlRDerive(f);
          if (gdakiCtrlJudge(GDAKI_CTRL_L_NORESP, GDAKI_CTRL_B_NONE, GDAKI_CTRL_W_OK, R).row == 14 && judgedAt < 0)
            judgedAt = tt;
        }
        if (healthy) {
          if (judgedAt >= 0) ok = false;
        } else {
          const double resolvedFrom = std::max(D, 10000.0);
          if (!(judgedAt >= resolvedFrom + kG && resAt >= resolvedFrom && judgedAt <= resAt + kG + kProbe)) ok = false;
        }
        if (!ok) fails++;
      }
  } while (std::next_permutation(order, order + 5));
  return fails;
}

// ---- running the scenes ----
struct Plan {
  int drawsB, drawsOther, drawsPhases;
};
static int runAll(const Plan& pl, uint64_t base, bool print) {
  gStats.clear();
  int fails = 0;
  long t0 = gFailed;
  for (int v = 1; v <= 3; v++)
    for (int d = 0; d < pl.drawsB; d++) fails += !sceneCellB(base + 1000u * v + (uint64_t)d, v, true);
  for (int d = 0; d < pl.drawsOther; d++) {
    fails += !sceneStuckWaiter(base + 5000 + (uint64_t)d, true);
    fails += !sceneStuckWaiter(base + 6000 + (uint64_t)d, false);
    fails += !sceneCycle(base + 7000 + (uint64_t)d, false);
    fails += !sceneCycle(base + 8000 + (uint64_t)d, true);
    fails += !sceneChain(base + 9000 + (uint64_t)d);
    for (int k = 0; k < 4; k++) fails += !sceneMa(base + 10000 + 1000u * (uint64_t)k + (uint64_t)d, k);
    for (int k = 0; k < 5; k++) fails += !sceneLa(base + 20000 + 1000u * (uint64_t)k + (uint64_t)d, k);
    fails += !sceneNa(base + 30000 + (uint64_t)d, 1);
    fails += !sceneNa(base + 31000 + (uint64_t)d, 2);
    fails += !sceneBa(base + 32000 + (uint64_t)d);
  }
  fails += !sceneRace();
  long runs = 0, perms = 0;
  const int pf = scenePhases(base + 40000, &runs, &perms);
  {
    SceneStat& st = stat("(다) restore phase, 5 events in every order");
    st.runs += runs;
    st.failed += pf;
    if (gMut == M0) CHECK(pf == 0);
    fails += pf;
  }
  if (print) {
    for (const auto& s : gStats) printf("  scene %-50s runs %5ld failed %ld\n", s.name, s.runs, s.failed);
  }
  (void)t0;
  return fails;
}
static void report(uint64_t seed) {
  int jr[8];
  bool rs[8];
  for (int i = 0; i < 8; i++) sceneRing(seed + (uint64_t)i, &jr[i], &rs[i]);
  int all = 0, rest = 0;
  for (int i = 0; i < 8; i++) {
    all += jr[i] == 4;
    rest += rs[i];
  }
  printf("ring allreduce shape (failure 1, report only): 8 runs, every rank judged in %d, restored in %d (every rank is "
         "a CYCLE: judged at STALL_MS, fallback)\n", all, rest);
}
#endif

int main(int argc, char** argv) {
#if !NCCL_GIN_CTRL_TCP
  const char* env = getenv("GC_WP_DRAWS");
  const int drawsB = env != nullptr ? atoi(env) : 1000;
  testPure();
  Plan pl{drawsB, std::max(1, drawsB / 5), 4};
  printf("scenes (m0, the rule): cell B %d draws per variant, the others %d draws each:\n", pl.drawsB, pl.drawsOther);
  const long f0 = gFailed;
  const int fails = runAll(pl, 0x77616974ull, true);
  CHECK(fails == 0 && gFailed == f0);
  printf("residuals (recorded, not failures): the cycle's second member not judged because the restore came first: "
         "two-rank communicator %ld of %d (its observer fenced), four ranks %ld of %d (its own commit rewrote its QP to "
         "(0, 0) before its mark: hidden, a limitation); (라)3 the waiter judged in %ld of %ld\n",
         gCycleLate2, pl.drawsOther, gCycleLate4, pl.drawsOther, gLa3Judged, gLa3Runs);
  report(0x72696e67ull);
  // the mutations: each must fail at least one scene (the scenes' own failures are not the test's then)
  const char* only = argc > 1 ? argv[1] : nullptr;
  Plan pm{20, 4, 4};
  int caught = 0;
  for (int m = 1; m < M_N; m++) {
    if (only != nullptr && atoi(only) != m) continue;
    gMut = m;
    gQuiet = true;
    const long c0 = gChecks, fa0 = gFailed;
    const int mf = runAll(pm, 0x6d757461ull + (uint64_t)m, false);
    gChecks = c0;
    gFailed = fa0;
    gQuiet = false;
    gMut = M0;
    std::string which;
    for (const auto& s : gStats)
      if (s.failed > 0) which += std::string(which.empty() ? "" : "; ") + s.name + " " + std::to_string(s.failed) + "/" +
                                 std::to_string(s.runs);
    printf("mutation %-22s failed %d scene runs: %s\n", kMutName[m], mf, which.empty() ? "(none)" : which.c_str());
    CHECK(mf > 0);
    caught += mf > 0;
  }
  printf("mutations caught: %d of %d\n", caught, only != nullptr ? 1 : M_N - 1);
#else
  (void)argc;
  (void)argv;
#endif
  printf("gc_unit_waitpeer (%s): %ld checks, %ld failed\n", NCCL_GIN_CTRL_TCP ? "tcp" : "rdma", gChecks, gFailed);
  return gFailed == 0 ? 0 : 1;
}
