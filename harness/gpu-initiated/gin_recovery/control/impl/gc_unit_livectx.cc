// gc_unit_livectx.cc - CPU unit test of gin-control's progress line of every GIN context (ctxall; user decision
// 2026-10-24 (가); impl/notes_ctxall.md). No NCCL, no CUDA, no verbs, no network. Compiled as gc_unit_live.cc is
// (build_gc.sh `unit`, `unitlivectx`, BR=int3): g++ -std=c++17 with ASan and UBSan, gin-mirror's and gin-restore's
// headers, impl/rs_ctrl_api.h and the working tree's cut region "gin-control (page): pure functions" (gc_page_pure.inc).
// What it checks:
//   1. the encodings: the page's context line (head word, contexts 1..7, the reader's bound), the all-gather's count and
//      array (gdakiCtrlDevAgX, bounded by GDAKI_CTRL_DEV_MAX_CTX), the setup's bound, the device READ kinds per context
//      (context 0 keeps GDAKI_CTRL_PW_DEV), the page's 4 KiB still holding the line at the largest layout; the single
//      context's numbers unchanged (SQ 4, the 168 B control fields, the 320 B page of 4 ranks);
//   2. the per-context clocks: a change or a quiet line of one context resets that context's origin only; the stall is the
//      largest of the contexts' (the lowest index on a tie);
//   3. the rule over a reader that judges one subject every 100 ms (gdakiCtrlRDerive, the table's row): context 0 quiet and
//      context 1 pending with a frozen line: row 14 after STALL_MS, naming context 1; context 0 progressing and context 1
//      frozen with pending work: row 14 (not masked); every context quiet: row 20 only; more scenes (8 contexts, two
//      frozen contexts, a frozen context that resumes, a context not read yet, the data path's veto unchanged);
//   4. mutation checks: the old single-context rule (context 0's line only) misses the first scene; one shared clock over
//      every context's line misses the second; a quiet context that resets every clock misses the first;
//   5. the chain over a model of the QP (in-order completions, random latencies, timeouts, window READs, a QP lost now and
//      then): 1 + n READs a period, never more than GDAKI_CTRL_PROBE_SQ (4) in flight and never more than 2 of a period,
//      each period judged once after its last completion (or when the chain is given up), the next only after it; one
//      context: exactly the pair as before (2 READs, no chain).
#include <algorithm>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <functional>
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
#define CHECK(c)                                                                      \
  do {                                                                                \
    gChecks++;                                                                        \
    if (!(c)) {                                                                       \
      gFailed++;                                                                      \
      if (gFailed <= 60) fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); \
    }                                                                                 \
  } while (0)

#if !NCCL_GIN_CTRL_TCP  // the tcp build has none of phase 1 (the header's API and the region are rdma only)
#include "gc_page_pure.inc"  // the host file's "gin-control (page): pure functions" region
static uint32_t judgeRow(uint32_t L, uint32_t B, uint32_t W, uint32_t R) { return gdakiCtrlJudge(L, B, W, R).row; }

// DOCA's struct doca_gpu_dev_verbs_qp as the host file measures it (sizeof 296, sq_rsvd_index at 0, cq_sq.cqe_ci at 184)
static const uint32_t kStride = 296, kOffPosted = 0, kOffPolled = 184;
struct DevArray {
  std::vector<uint8_t> b;
  explicit DevArray(int n) : b((size_t)n * kStride, 0xa5) {
    for (int k = 0; k < n; k++) set(k, 0, 0);
  }
  void set(int k, uint64_t posted, uint64_t polled) {
    memcpy(b.data() + (size_t)k * kStride + kOffPosted, &posted, 8);
    memcpy(b.data() + (size_t)k * kStride + kOffPolled, &polled, 8);
  }
  struct gdakiCtrlDevSum sum() const {
    return gdakiCtrlDevSumOf(b.data(), (uint32_t)b.size(), kStride, kOffPosted, kOffPolled);
  }
};

// ---- 1. the encodings ----
static void testEncodings() {
  CHECK(GDAKI_CTRL_DEV_MAX_CTX == 8u);
  CHECK(sizeof(struct gdakiCtrlDevAgX) == 120 && offsetof(struct gdakiCtrlDevAgX, more) == 8);
  CHECK(!gdakiCtrlDevCtxFits(0) && gdakiCtrlDevCtxFits(1) && gdakiCtrlDevCtxFits(8) && !gdakiCtrlDevCtxFits(9) &&
        !gdakiCtrlDevCtxFits(-1));
  // the single context's numbers are unchanged
  CHECK(GDAKI_CTRL_PROBE_SQ == 4 && sizeof(struct gdakiCtrlSetupAddr) == 168 &&
        offsetof(struct gdakiCtrlSetupAddr, dev) == 152 && offsetof(struct gdakiCtrlPageHead, devLine) == 56);
  struct gdakiCtrlPageLayout l;
  CHECK(gdakiCtrlPageLayoutOf(4, 2, &l) && l.bytes == 320);
  CHECK(gdakiCtrlDevxBytes(0) == 0 && gdakiCtrlDevxBytes(1) == 0 && gdakiCtrlDevxBytes(2) == 64 && gdakiCtrlDevxBytes(8) == 64);
  // the context line fits the page at every layout (the largest: 112 ranks, 16 launchers)
  uint32_t maxBytes = 0;
  for (uint32_t n = 1; n <= GDAKI_CTRL_PAGE_MAX_RANKS; n++)
    for (uint32_t nl = 0; nl <= GDAKI_CTRL_PAGE_MAX_LAUNCHERS; nl++) {
      struct gdakiCtrlPageLayout x;
      if (!gdakiCtrlPageLayoutOf(n, nl, &x)) continue;
      maxBytes = std::max(maxBytes, x.bytes);
      CHECK(x.bytes + GDAKI_CTRL_DEVX_BYTES <= GDAKI_CTRL_PAGE_BYTES && x.bytes % 64 == 0);
    }
  CHECK(maxBytes == 4032);
  // the context line's words
  const uint64_t l0 = gdakiCtrlDevLineWord(0x100u, 1184);
  uint64_t x[8] = {gdakiCtrlDevxHead(4), gdakiCtrlDevLineWord(0x101u, 1184), gdakiCtrlDevLineWord(0x102u, 1184),
                   gdakiCtrlDevLineWord(0x103u, 1184), 0, 0, 0, 0};
  uint64_t w[GDAKI_CTRL_DEV_MAX_CTX];
  uint32_t pn = 0;
  CHECK(gdakiCtrlDevLinesOf(l0, x, 4, w, &pn) == 4 && pn == 4 && w[0] == l0 && gdakiCtrlDevLineRkey(w[3]) == 0x103u &&
        w[4] == 0 && w[7] == 0);
  CHECK(gdakiCtrlDevLinesOf(l0, x, 1, w, &pn) == 1 && pn == 1 && w[0] == l0 && w[1] == 0);   // one context: line 0 only
  CHECK(gdakiCtrlDevLinesOf(l0, nullptr, 4, w, &pn) == 1 && w[1] == 0);                     // no context line read
  CHECK(gdakiCtrlDevLinesOf(l0, x, 2, w, &pn) == 2 && pn == 4 && w[2] == 0);                 // the reader's bound
  x[0] = gdakiCtrlDevxHead(9);
  CHECK(gdakiCtrlDevLinesOf(l0, x, 8, w, &pn) == 1);  // a count above the bound: not a context line
  x[0] = ((uint64_t)0x12345678u << 32) | 4u;
  CHECK(gdakiCtrlDevLinesOf(l0, x, 8, w, &pn) == 1);  // another magic (zeros of a one-context writer too)
  uint64_t z[8] = {};
  CHECK(gdakiCtrlDevLinesOf(0, z, 8, w, &pn) == 1 && w[0] == 0);
  // the device READ kinds: context 0 is GDAKI_CTRL_PW_DEV as before; the 4-bit kind field holds every context
  CHECK(gdakiCtrlProbeDevKind(0) == GDAKI_CTRL_PW_DEV);
  for (uint32_t k = 0; k < 16; k++)
    CHECK(gdakiCtrlProbeKindIsDev(k) == (k >= GDAKI_CTRL_PW_DEV && k < GDAKI_CTRL_PW_DEV + GDAKI_CTRL_DEV_MAX_CTX));
  for (uint32_t c = 0; c < GDAKI_CTRL_DEV_MAX_CTX; c++) {
    const uint64_t id = gdakiCtrlProbeWrId(gdakiCtrlProbeDevKind(c), 111, 0xbeef, 0x12345678u);
    CHECK(gdakiCtrlProbeDevCtxOf(gdakiCtrlProbeWrKind(id)) == c && gdakiCtrlProbeWrPeer(id) == 111 &&
          gdakiCtrlProbeWrSeq(id) == 0x12345678u && gdakiCtrlProbeWrGenIs(id, 0xbeef));
  }
  CHECK(!gdakiCtrlProbeKindIsDev(GDAKI_CTRL_PW_PERIODIC) && !gdakiCtrlProbeKindIsDev(GDAKI_CTRL_PW_WIN1) &&
        !gdakiCtrlProbeKindIsDev(GDAKI_CTRL_PW_WIN2));
  printf("encodings: context line 64 B after the layout (largest layout %u B + 64 <= 4096), head DEVX + count, reader "
         "bound, all-gather count + 7 regions (120 B), bound 1..%u, READ kinds %u..%u; one context unchanged (SQ 4, 168 B, "
         "320 B)\n", maxBytes, GDAKI_CTRL_DEV_MAX_CTX, GDAKI_CTRL_PW_DEV, GDAKI_CTRL_PW_DEV + GDAKI_CTRL_DEV_MAX_CTX - 1);
}

// ---- 2. the per-context clocks ----
static void testClocks() {
  struct gdakiCtrlStale s[GDAKI_CTRL_DEV_MAX_CTX];
  DevArray a0(4), a1(4);
  a0.set(1, 10, 8);  // context 0: pending 2
  a1.set(1, 20, 17);  // context 1: pending 3
  int ctx = 7;
  CHECK(gdakiCtrlDevStaleOf(s, 2, &ctx) == 0 && ctx == -1);  // nothing read: 0, no context
  for (int t = 0; t <= 3000; t += 100) {
    if (t >= 1000) a0.set(1, 10 + (uint64_t)t, 8 + (uint64_t)t);  // context 0 moves from 1000 on
    (void)gdakiCtrlDevOnRead(&s[0], a0.sum(), t, 100);
    (void)gdakiCtrlDevOnRead(&s[1], a1.sum(), t, 100);
  }
  CHECK(s[0].lastMs - s[0].firstMs == 0 && s[1].lastMs - s[1].firstMs == 3000);  // context 0's change did not reset 1
  CHECK(gdakiCtrlDevStaleOf(s, 2, &ctx) == 3000 && ctx == 1);
  CHECK(gdakiCtrlDevStaleOf(s, 1, &ctx) == 0 && ctx == -1);  // context 0 alone (the old rule) sees no stall
  CHECK(gdakiCtrlDevStaleAt(s, 2, 3050) == 3050);
  // a quiet context 1 resets its own clock, context 0 (frozen with pending) keeps its stall
  struct gdakiCtrlStale q[2];
  DevArray b0(4), b1(4);
  b0.set(2, 50, 40);
  b1.set(2, 9, 9);
  for (int t = 0; t <= 2000; t += 100) {
    bool quiet = false;
    (void)gdakiCtrlDevOnRead(&q[0], b0.sum(), t, 100);
    (void)gdakiCtrlDevOnRead(&q[1], b1.sum(), t, 100, nullptr, &quiet);
    CHECK(quiet);
  }
  CHECK(gdakiCtrlDevStaleOf(q, 2, &ctx) == 2000 && ctx == 0);
  // a tie: the lowest index
  struct gdakiCtrlStale e[3];
  for (int t = 0; t <= 500; t += 100)
    for (int c = 0; c < 3; c++) (void)gdakiCtrlDevOnRead(&e[c], c == 0 ? b1.sum() : b0.sum(), t, 100);
  CHECK(gdakiCtrlDevStaleOf(e, 3, &ctx) == 500 && ctx == 1);
  printf("clocks: a change or a quiet line of one context resets that context only; the stall is the largest (ties: "
         "lowest index)\n");
}

// ---- 3. the rule, one reader judging one subject every 100 ms ----
// The subject's GPU has n contexts; each context's line (its QP array of 4 QPs; the QP toward the reader carries its
// posts, unless `toOthers`) follows a mode over time. The host beats stay alive (the reader's R (6)-(9) are fresh), the
// partition guard passes, the data path's veto is clear unless `vetoHeld` (the subject's traffic reaches the reader).
enum Mode { M_PROGRESS = 0, M_QUIET = 1, M_FROZEN = 2 };
struct CtxPlan {
  Mode before = M_PROGRESS, after = M_PROGRESS;
  double from = 1e18, to = 1e18;  // `after` in [from, to)
  Mode at(double t) const { return t >= from && t < to ? after : before; }
};
enum Rule { RULE_CTXALL = 0, RULE_CTX0_ONLY = 1, RULE_SHARED_CLOCK = 2, RULE_QUIET_RESETS_ALL = 3 };
struct CtxScene {
  int n = 2;
  CtxPlan plan[GDAKI_CTRL_DEV_MAX_CTX];
  bool vetoHeld = false;
  uint32_t unreadMask = 0;  // contexts whose line this reader has not read yet in this generation
  Rule rule = RULE_CTXALL;
  // results
  double firstRowAt[22];
  std::set<uint32_t> rows;
  int stallCtx = -2, suspectCtx = -2;  // the context named at the first row 14 / row 18 (-1: none)
  CtxScene() {
    for (double& x : firstRowAt) x = -1;
  }
  // context c's (posted, polled) at t: progress posts every ms with 2 pending; quiet: everything polled; frozen: the
  // values when it froze, 2 pending
  void lineOf(int c, double t, uint64_t* posted, uint64_t* polled) const {
    const CtxPlan& p = plan[c];
    const Mode m = p.at(t);
    const double t0 = m == p.after && t >= p.from ? p.from : 0;
    const uint64_t base = 1000u * (uint64_t)(c + 1);
    if (m == M_PROGRESS) {
      *posted = base + (uint64_t)t + 2;
      *polled = base + (uint64_t)t;
    } else if (m == M_QUIET) {
      *posted = *polled = base + (uint64_t)t0;
    } else {
      *posted = base + (uint64_t)t0 + 2;
      *polled = base + (uint64_t)t0;
    }
  }
  void run(double until) {
    const double probe = 100, suspect = 2000, stall = 10000;
    struct gdakiCtrlStale s[GDAKI_CTRL_DEV_MAX_CTX], shared, ws, hs;
    for (double t = 0; t <= until; t += probe) {
      struct gdakiCtrlDevSum all;
      bool anyQuiet = false;
      for (int c = 0; c < n; c++) {
        DevArray a(4);
        uint64_t po = 0, pl = 0;
        lineOf(c, t, &po, &pl);
        a.set(0, po, pl);  // the subject's QP toward rank 0 (the reader)
        const struct gdakiCtrlDevSum d = a.sum();
        bool quiet = false;
        if ((unreadMask & (1u << c)) == 0) (void)gdakiCtrlDevOnRead(&s[c], d, t, probe, nullptr, &quiet);
        anyQuiet = anyQuiet || quiet;
        all.posted += d.posted * (uint64_t)(c + 1);
        all.polled += d.polled;
        all.pending += d.pending;
      }
      (void)gdakiCtrlDevOnRead(&shared, all, t, probe);  // RULE_SHARED_CLOCK's one clock over every line
      if (rule == RULE_QUIET_RESETS_ALL && anyQuiet)
        for (int c = 0; c < n; c++) s[c].firstMs = t;
      (void)gdakiCtrlStaleOnRead(&ws, (uint64_t)t + 1, t, probe);
      (void)gdakiCtrlStaleOnRead(&hs, (uint64_t)t * 1000 + 1, t, probe);
      struct gdakiCtrlRFacts f;
      f.okInGen = true;
      f.devMode = true;
      f.devOk = unreadMask == 0;
      int ctx = -1;
      if (rule == RULE_CTX0_ONLY)
        f.devStaleMs = gdakiCtrlDevStaleOf(s, 1, &ctx);
      else if (rule == RULE_SHARED_CLOCK)
        f.devStaleMs = gdakiCtrlDevStaleOf(&shared, 1, &ctx);
      else
        f.devStaleMs = gdakiCtrlDevStaleOf(s, (uint32_t)n, &ctx);
      f.watchRose = true;
      f.watchStaleMs = ws.lastMs - ws.firstMs;
      f.helperStaleMs = hs.lastMs - hs.firstMs;
      f.guardOk = true;
      f.vetoClear = !vetoHeld;
      f.suspectMs = suspect;
      f.stallMs = stall;
      const uint32_t R = gdakiCtrlRDerive(f);
      const uint32_t row = judgeRow(GDAKI_CTRL_L_NORESP, GDAKI_CTRL_B_NONE, GDAKI_CTRL_W_OK, R);
      rows.insert(row);
      if (firstRowAt[row] < 0) {
        firstRowAt[row] = t;
        if (row == 14) stallCtx = R == GDAKI_CTRL_R_STALL ? ctx : -1;  // as the watch thread latches stallCtx
        if (row == 18) suspectCtx = ctx;
      }
    }
  }
};
static bool stallAt(const CtxScene& s, double from) {
  return s.firstRowAt[14] >= 0 && s.firstRowAt[14] - from >= 10000 && s.firstRowAt[14] - from <= 10300;
}
static CtxScene sceneQuietAndFrozen(Rule rule) {  // context 0 quiet, context 1 pending with a frozen line from 1000
  CtxScene s;
  s.rule = rule;
  s.plan[0].before = M_QUIET;
  s.plan[0].after = M_QUIET;
  s.plan[1].after = M_FROZEN;
  s.plan[1].from = 1000;
  s.run(30000);
  return s;
}
static CtxScene sceneProgressAndFrozen(Rule rule, bool vetoHeld) {  // context 0 progressing, context 1 frozen from 1000
  CtxScene s;
  s.rule = rule;
  s.vetoHeld = vetoHeld;
  s.plan[1].after = M_FROZEN;
  s.plan[1].from = 1000;
  s.run(30000);
  return s;
}
static void testRule() {
  // the first scene: context 0 quiet, context 1 pending with a frozen line: row 14 after STALL_MS, naming context 1
  const CtxScene a = sceneQuietAndFrozen(RULE_CTXALL);
  CHECK(stallAt(a, 1000) && a.stallCtx == 1 && a.firstRowAt[18] >= 0 && a.firstRowAt[18] < a.firstRowAt[14] &&
        a.suspectCtx == 1 && a.firstRowAt[15] < 0);
  // the second: context 0 progressing, context 1 frozen with pending work: row 14, not masked by context 0
  const CtxScene b = sceneProgressAndFrozen(RULE_CTXALL, false);
  CHECK(stallAt(b, 1000) && b.stallCtx == 1 && b.firstRowAt[15] < 0);
  // every context quiet (a compute phase without sends, 25 s): row 20 only
  CtxScene c;
  for (int k = 0; k < 2; k++) {
    c.plan[k].after = M_QUIET;
    c.plan[k].from = 1000;
    c.plan[k].to = 26000;
  }
  c.run(30000);
  CHECK(c.rows == std::set<uint32_t>({20}));
  CtxScene c8;  // eight contexts, all quiet from the start
  c8.n = 8;
  for (int k = 0; k < 8; k++) c8.plan[k].before = c8.plan[k].after = M_QUIET;
  c8.run(30000);
  CHECK(c8.rows == std::set<uint32_t>({20}));
  // every context progressing: row 20 only
  CtxScene d;
  d.n = 4;
  d.run(30000);
  CHECK(d.rows == std::set<uint32_t>({20}));
  // eight contexts, mixed quiet and progressing, context 5 frozen from 2000: row 14 naming context 5
  CtxScene e;
  e.n = 8;
  for (int k = 0; k < 8; k++) e.plan[k].before = e.plan[k].after = k % 2 ? M_QUIET : M_PROGRESS;
  e.plan[5].before = M_PROGRESS;
  e.plan[5].after = M_FROZEN;
  e.plan[5].from = 2000;
  e.run(30000);
  CHECK(stallAt(e, 2000) && e.stallCtx == 5);
  // two frozen contexts: the first to freeze decides the time and the context
  CtxScene g;
  g.n = 3;
  g.plan[2].after = M_FROZEN;
  g.plan[2].from = 1000;
  g.plan[1].after = M_FROZEN;
  g.plan[1].from = 3000;
  g.run(30000);
  CHECK(stallAt(g, 1000) && g.stallCtx == 2);
  // a frozen context that resumes before STALL_MS: a suspicion (row 18), never row 14
  CtxScene h;
  h.plan[0].before = h.plan[0].after = M_QUIET;
  h.plan[1].after = M_FROZEN;
  h.plan[1].from = 1000;
  h.plan[1].to = 7000;
  h.run(30000);
  CHECK(h.firstRowAt[14] < 0 && h.firstRowAt[18] >= 0 && h.firstRowAt[18] - 1000 >= 2000 && h.firstRowAt[18] - 1000 <= 2300);
  // a context whose line this reader has not read yet in this generation: row 13 only (no verdict)
  CtxScene u = CtxScene();
  u.plan[1].after = M_FROZEN;
  u.plan[1].from = 1000;
  u.unreadMask = 2;
  u.run(15000);
  CHECK(u.rows == std::set<uint32_t>({13}));
  // the data path's veto (unchanged): context 0's traffic reaches the reader, so its responder count moves: the GPU
  // stall of context 1 is held back (row 18), as for one context
  const CtxScene v = sceneProgressAndFrozen(RULE_CTXALL, true);
  CHECK(v.firstRowAt[14] < 0 && v.firstRowAt[18] >= 0);
  // one context (n = 1) frozen: row 14 naming context 0 (the old scene)
  CtxScene o;
  o.n = 1;
  o.plan[0].after = M_FROZEN;
  o.plan[0].from = 1000;
  o.run(30000);
  CHECK(stallAt(o, 1000) && o.stallCtx == 0);
  printf("rule (1 reader, 100 ms): ctx0 quiet + ctx1 frozen: row 14 at +%.0f ms ctx=%d; ctx0 progressing + ctx1 frozen: "
         "row 14 at +%.0f ms ctx=%d; all quiet (2 and 8 contexts): row 20 only; all progressing: row 20 only; 8 contexts, "
         "ctx5 frozen: row 14 at +%.0f ms ctx=%d; two frozen: ctx=%d first; resumed at +6000: row 18 only; unread: row 13 "
         "only; veto held: row 18, no 14; one context: row 14 ctx=0\n", a.firstRowAt[14] - 1000, a.stallCtx,
         b.firstRowAt[14] - 1000, b.stallCtx, e.firstRowAt[14] - 2000, e.stallCtx, g.stallCtx);
}

// ---- 4. mutation checks ----
static void testMutations() {
  const CtxScene m1 = sceneQuietAndFrozen(RULE_CTX0_ONLY);  // the old rule: context 0's line only
  CHECK(m1.firstRowAt[14] < 0 && m1.rows == std::set<uint32_t>({20}));
  const CtxScene m2 = sceneProgressAndFrozen(RULE_SHARED_CLOCK, false);  // one clock over every line
  CHECK(m2.firstRowAt[14] < 0 && m2.rows == std::set<uint32_t>({20}));
  const CtxScene m3 = sceneQuietAndFrozen(RULE_QUIET_RESETS_ALL);  // a quiet context resets every clock
  CHECK(m3.firstRowAt[14] < 0 && m3.rows == std::set<uint32_t>({20}));
  // and the per-context rule catches what each missed
  CHECK(stallAt(sceneQuietAndFrozen(RULE_CTXALL), 1000) && stallAt(sceneProgressAndFrozen(RULE_CTXALL, false), 1000));
  printf("mutations: context 0 only misses the first scene (rows {20}); one shared clock misses the second (rows {20}); a "
         "quiet context resetting every clock misses the first (rows {20}); the per-context rule catches both\n");
}

// ---- 5. the chain within the SQ bound ----
// One QP: every 100 ms the page READ and the first context's line READ (the pair), then the other contexts' READs one by
// one as the period's slots free (gdakiCtrlProbeChainDue), the window's two READs when a window opens, every READ
// completing in posting order after a random latency (sometimes past the 500 ms timeout); now and then the QP is not
// this thread's for a step (the chain given up, gdakiCtrlProbeChainDrop). 1 ms steps.
struct Posted {
  uint32_t kind, seq;
  double doneAt;
};
static void testChain() {
  long periods = 0, judged = 0, dropped = 0, windows = 0, timeouts = 0, reads = 0, fullPeriods = 0;
  uint32_t maxOut = 0, maxLeft = 0;
  long readsByN[GDAKI_CTRL_DEV_MAX_CTX + 1] = {}, periodsByN[GDAKI_CTRL_DEV_MAX_CTX + 1] = {};
  for (int run = 0; run < 64; run++) {
    std::mt19937_64 rng(0x63747861ull + (uint64_t)run);
    std::uniform_real_distribution<double> u(0, 1);
    const uint32_t nCtx = 1u + (uint32_t)(run % (int)GDAKI_CTRL_DEV_MAX_CTX);
    const bool lossy = run % 3 == 2;  // QP lost now and then
    struct gdakiCtrlProbeIo io;
    struct gdakiCtrlWindow win;
    std::deque<Posted> fifo;
    double next = 0, lastDone = 0;
    uint32_t perSeq = 0, perPosted = 0, perDone = 0, nextCtx = 0;
    bool perJudged = true, perDropped = false;  // perDropped: this period's chain was given up (its rest not posted)
    uint32_t ctxSeen = 0;
    auto post = [&](uint32_t kind, uint32_t seq, double t) {
      CHECK(gdakiCtrlProbeCanPost(&io, 1));
      double lat = 0.02 + 0.3 * u(rng);
      if (u(rng) < 0.002) lat = 600 + 400 * u(rng);
      const double at = std::max(t + lat, lastDone);
      lastDone = at;
      fifo.push_back({kind, seq, at});
      gdakiCtrlProbeOnPosted(&io, kind, seq, t);
      maxOut = std::max(maxOut, io.outstanding);
      maxLeft = std::max(maxLeft, io.periodicLeft);
      CHECK(io.outstanding <= GDAKI_CTRL_PROBE_SQ && io.periodicLeft <= 2);
      if (seq == perSeq && (kind == GDAKI_CTRL_PW_PERIODIC || gdakiCtrlProbeKindIsDev(kind))) perPosted++;
      reads++;
    };
    auto endPeriod = [&](bool viaDrop) {
      CHECK(!perJudged);  // once per period
      perJudged = true;
      judged++;
      if (viaDrop || perDropped) {
        dropped++;
        CHECK(perDone == perPosted && perDone < 1 + nCtx);  // every posted READ completed, the rest never posted
      } else {
        CHECK(perDone == 1 + nCtx && perPosted == 1 + nCtx && ctxSeen == (1u << nCtx) - 1u);  // 1 + n READs, each context
        fullPeriods++;
        readsByN[nCtx] += perDone;
        periodsByN[nCtx]++;
      }
    };
    for (double t = 0; t < 60000; t += 1) {
      while (!fifo.empty() && fifo.front().doneAt <= t) {
        const Posted x = fifo.front();
        fifo.pop_front();
        const bool ofPer = gdakiCtrlProbeIsPeriodic(&io, x.kind, x.seq);
        const bool done = gdakiCtrlProbeOnCqe(&io, x.kind, x.seq);
        CHECK(io.outstanding == fifo.size());
        if (ofPer) {
          CHECK(x.seq == perSeq);
          perDone++;
          if (gdakiCtrlProbeKindIsDev(x.kind)) ctxSeen |= 1u << gdakiCtrlProbeDevCtxOf(x.kind);
          if (done) endPeriod(false);
        } else {
          CHECK(!done);
          if (x.kind == GDAKI_CTRL_PW_WIN1 || x.kind == GDAKI_CTRL_PW_WIN2)
            (void)gdakiCtrlWindowOnCqe(&win, x.seq, x.kind == GDAKI_CTRL_PW_WIN1 ? 1u : 2u, GDAKI_CTRL_CQ_OK, (uint64_t)t,
                                       0, t);
        }
      }
      // the chain (gdakiProbeDevChainStep): the QP lost for this step gives it up; never into the window's reserved slots
      if (io.periodicMore > 0) {
        const uint32_t wres =
            win.state == GDAKI_CTRL_WS_OPEN && win.countable ? (uint32_t)!win.r1Posted + (uint32_t)!win.r2Posted : 0u;
        if (lossy && u(rng) < 0.02) {
          perDropped = true;
          if (gdakiCtrlProbeChainDrop(&io)) endPeriod(true);
          CHECK(io.periodicMore == 0 && (io.periodicOut == (io.periodicLeft > 0)));
        } else {
          while (gdakiCtrlProbeChainDue(&io, wres)) {
            CHECK(nextCtx < nCtx);
            post(gdakiCtrlProbeDevKind(nextCtx), io.periodicSeq, t);
            nextCtx++;
          }
        }
      }
      if (gdakiCtrlProbeTimedOut(&io, t, 500)) timeouts++;
      if (u(rng) < 0.002 && gdakiCtrlWindowOpen(&win, GDAKI_CTRL_WSRC_FIN, t, gdakiCtrlProbeCanPost(&io, 2))) windows++;
      const uint32_t wa = gdakiCtrlWindowStep(&win, t, 20);
      if (wa == GDAKI_CTRL_WA_JUDGE) {
        (void)gdakiCtrlWindowJudge(&win, 0, t);
      } else if (wa == GDAKI_CTRL_WA_POST1 || wa == GDAKI_CTRL_WA_POST2) {
        const bool ok = gdakiCtrlProbeCanPost(&io, 1);
        if (ok) post(wa == GDAKI_CTRL_WA_POST1 ? GDAKI_CTRL_PW_WIN1 : GDAKI_CTRL_PW_WIN2, win.no, t);
        gdakiCtrlWindowPosted(&win, wa == GDAKI_CTRL_WA_POST1 ? 1u : 2u, ok, t);
        CHECK(ok);  // the window's slots are kept for it (the period never holds more than 2)
      }
      const uint32_t reserve =
          win.state == GDAKI_CTRL_WS_OPEN && win.countable ? (uint32_t)!win.r1Posted + (uint32_t)!win.r2Posted : 0u;
      const bool wasOut = io.periodicOut;
      const uint32_t seq = gdakiCtrlProbePeriodicDue(&io, t, next, reserve, 2u);
      if (seq != 0) {
        CHECK(!wasOut && perJudged);  // the next period only after the last one ended
        next = t + 100;
        perSeq = seq;
        perPosted = perDone = 0;
        perJudged = false;
        perDropped = false;
        ctxSeen = 0;
        post(GDAKI_CTRL_PW_PERIODIC, seq, t);
        post(gdakiCtrlProbeDevKind(0), seq, t);
        gdakiCtrlProbeChainSet(&io, nCtx - 1u);
        nextCtx = 1;
        if (nCtx == 1) CHECK(io.periodicMore == 0);  // one context: the pair as before, no chain
        periods++;
      }
    }
  }
  CHECK(maxOut <= GDAKI_CTRL_PROBE_SQ && maxOut == 4 && maxLeft == 2);
  CHECK(judged > 0 && periods - judged <= 64 && windows > 0 && timeouts > 0 && dropped > 0 && fullPeriods > 0);
  for (uint32_t n = 1; n <= GDAKI_CTRL_DEV_MAX_CTX; n++) CHECK(periodsByN[n] > 0 && readsByN[n] == periodsByN[n] * (1 + n));
  printf("chain: 64 runs x 60 s (1..8 contexts), %ld periods, %ld ended (%ld whole, %ld by a given-up chain), %ld windows, "
         "%ld timeouts, %ld READs; READs per whole period = 1 + contexts (1: 2, 8: 9); at most %u in flight (SQ %u), at most "
         "%u of a period\n", periods, judged, fullPeriods, dropped, windows, timeouts, reads, maxOut, GDAKI_CTRL_PROBE_SQ,
         maxLeft);
}
#endif

int main() {
#if !NCCL_GIN_CTRL_TCP
  testEncodings();
  testClocks();
  testRule();
  testMutations();
  testChain();
#endif
  printf("gc_unit_livectx (%s): %ld checks, %ld failed\n", NCCL_GIN_CTRL_TCP ? "tcp" : "rdma", gChecks, gFailed);
  return gFailed == 0 ? 0 : 1;
}
