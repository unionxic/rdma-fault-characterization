// gc_unit_live.cc - CPU unit test of gin-control's GPU-progress liveness words (user decision 2026-10-22; impl/notes_live.md).
// No NCCL, no CUDA, no verbs, no network. Compiled as gc_unit_p1.cc is (build_gc_live.sh `unit`, `unitlive`): g++ -std=c++17
// with ASan and UBSan, gin-mirror's and gin-restore's headers, impl/rs_ctrl_api.h (with rs_ctrl_api_live.diff) and the
// working tree's cut region "gin-control (page): pure functions" (gc_page_pure.inc). What it checks:
//   1. the layout: the status page's devLine word (line 0, byte 56), the setup all-gather's dev region (byte 152, the
//      record still 168 B), the device line word's fields;
//   2. the device line's sums over a model of DOCA's device QP array (stride 296, sq_rsvd_index at 0, cq_sq.cqe_ci at
//      184) and the GPU's stall clock (a changed line and a quiet line reset the origin; a reader gap of more than
//      2 x PROBE_MS resets it; an unchanged line with work pending is a stall);
//   3. the judgement inputs from the device line, four ranks reading each other every 100 ms, rank 0 judging rank 3
//      (gdakiCtrlRDerive with the partition guard and the data path's veto): the GPU stalled under live host beats is
//      row 14; host beats stalled with the GPU progressing is row 15 (both beats, the helper beat alone, a quiet GPU);
//      both stalled is row 14; both alive is row 20; a long compute phase with no sends (a quiet line) under a live host
//      is never 14; the first period after a pairing (line not read yet) is row 13; a peer without a device line keeps
//      the watch beat (row 14 on a watch-beat stall, as before);
//   4. the two-READ probe over a model of the QP (in-order completions, random latencies, stalls past the timeout, window
//      READs between): never more than GDAKI_CTRL_PROBE_SQ (4) in flight, never more than 2 of the periodic pair, a pair
//      judged once and only after both completions, the next pair only after both;
//   5. the confirmation window over the host's watch beat (smoke3, 2a-2-C step 5: READ1 at t_F, READ2 at t_F + W/2, the
//      verdict at t_F + W; line 0's watchBeat whether or not the peer names a device line): an advanced beat alive, an
//      unchanged (or older) one STALE, READ2 not done NORESP, a remote access error REMACC, another process unconfirmed;
//      2 000 kill scenes in which the device line keeps advancing 100 ms after the FIN (smoke3's 9/9 "alive" windows)
//      still end FIN+STALE (row 4) at t_F + W, and 2 000 live-peer scenes (beat gaps up to 1.1 ms) never STALE;
//   6. the judgement table over the whole 1 170-point grid: the per-row counts (234, 468, 117, 39 x 6, 3, 1, 5, 9 x 5,
//      36, 9, 18, 0) still hold (the table itself is unchanged).
#include <algorithm>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
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

// DOCA's struct doca_gpu_dev_verbs_qp as the host file measures it (sizeof 296, sq_rsvd_index at 0, cq_sq.cqe_ci at 184;
// the host file takes sizeof and offsetof, this model the numbers)
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

// ---- 1. the layout ----
static void testLayout() {
  CHECK(sizeof(struct gdakiCtrlPageHead) == 64 && offsetof(struct gdakiCtrlPageHead, devLine) == 56);
  CHECK(sizeof(struct gdakiCtrlSetupAddr) == 168 && offsetof(struct gdakiCtrlSetupAddr, dev) == 152);
  CHECK(offsetof(struct gdakiCtrlSetupAddr, path) == 116 && offsetof(struct gdakiCtrlSetupAddr, ud) == 32);
  CHECK(gdakiCtrlDevLineWord(0, 1184) == 0 && gdakiCtrlDevLineWord(7, 0) == 0);
  const uint64_t w = gdakiCtrlDevLineWord(0x1234abcdu, 1184);
  CHECK(gdakiCtrlDevLineRkey(w) == 0x1234abcdu && gdakiCtrlDevLineBytes(w) == 1184);
  struct gdakiCtrlState st;
  CHECK(st.dev == nullptr && st.page == nullptr);
  struct gdakiCtrlPageLayout l;  // the page layout is unchanged: line 0 holds the word
  CHECK(gdakiCtrlPageLayoutOf(4, 2, &l) && l.bytes == 320);
  CHECK(GDAKI_CTRL_PROBE_SQ == 4);
  printf("layout: devLine at page byte 56, the all-gather's dev region at byte 152 of 168, the page still 320 B (4 ranks, "
         "2 launchers)\n");
}

// ---- 2. the device line's sums and the GPU's stall clock ----
static void testDevClock() {
  DevArray a(4);
  a.set(0, 10, 10);
  a.set(1, 7, 5);
  a.set(2, 3, 4);  // a poll index ahead of the post index (a rebase): no pending from it
  a.set(3, 0, 0);
  struct gdakiCtrlDevSum d = a.sum();
  CHECK(d.posted == 20 && d.polled == 19 && d.pending == 2);
  CHECK(gdakiCtrlDevSumOf(nullptr, 100, kStride, 0, 184).posted == 0);
  CHECK(gdakiCtrlDevSumOf(a.b.data(), (uint32_t)a.b.size(), kStride, 0, kStride).posted == 0);  // a bad offset: nothing
  CHECK(gdakiCtrlDevSumOf(a.b.data(), kStride * 2 + 5, kStride, 0, 184).posted == 17);  // whole elements only
  // the clock: pending work, unchanged: the stall grows from the first READ that saw the value
  struct gdakiCtrlStale s;
  bool rose = false, quiet = false;
  double st = gdakiCtrlDevOnRead(&s, d, 0, 100, &rose, &quiet);
  CHECK(st == 0 && !rose && !quiet);
  for (int t = 100; t <= 5000; t += 100) st = gdakiCtrlDevOnRead(&s, d, t, 100, &rose, &quiet);
  CHECK(st == 5000 && !rose);
  // a change resets it
  a.set(1, 8, 5);
  st = gdakiCtrlDevOnRead(&s, a.sum(), 5100, 100, &rose, &quiet);
  CHECK(st == 0 && rose && !quiet);
  st = gdakiCtrlDevOnRead(&s, a.sum(), 5200, 100, &rose, &quiet);
  CHECK(st == 100 && !rose);
  // a reader gap above 2 x PROBE_MS resets the origin (the reader stalled)
  st = gdakiCtrlDevOnRead(&s, a.sum(), 5500, 100, &rose, &quiet);
  CHECK(st == 0);
  // a quiet line (nothing pending) is never a stall, however long it stays the same
  DevArray q(4);
  for (int k = 0; k < 4; k++) q.set(k, 1000 + k, 1000 + k);
  struct gdakiCtrlStale sq;
  for (int t = 0; t <= 30000; t += 100) {
    st = gdakiCtrlDevOnRead(&sq, q.sum(), t, 100, &rose, &quiet);
    CHECK(st == 0 && quiet);
  }
  // a recovery's rebase (indices back to 0) is a change
  q.set(0, 0, 0);
  q.set(1, 2, 0);
  st = gdakiCtrlDevOnRead(&sq, q.sum(), 30100, 100, &rose, &quiet);
  CHECK(st == 0 && rose && !quiet);
  printf("device clock: sums and pending over 4 QPs, stall 5000 ms of an unchanged busy line, reset by a change, a reader "
         "gap and a quiet line (30 000 ms quiet: 0)\n");
}

// ---- 3. the judgement inputs from the device line, four ranks ----
// Every rank reads every other rank's page and device line each 100 ms and publishes its view of each (staleMs[], the
// larger of the GPU's, the watch beat's and the helper beat's stall, as gdakiPageBeatStep). Rank 0 judges rank 3.
struct LiveScene {
  double gpuStallFrom = 1e18;   // rank 3's GPU stops with work pending (posted, not polled)
  double gpuQuietFrom = 1e18;   // rank 3's GPU stops with nothing pending (a compute phase, a finished kernel)
  double gpuQuietTo = 1e18;
  double hostStallFrom = 1e18;  // both of rank 3's beats stop
  double helperStallFrom = 1e18;  // its helper beat alone stops
  bool noLine = false;          // rank 3's page names no device line (the fallback: the watch beat is the progress)
  bool unreadFirst = false;     // rank 0 has not read rank 3's line yet in this generation (the first period)
  // results
  double firstRowAt[22];
  std::set<uint32_t> rows;
  LiveScene() {
    for (double& x : firstRowAt) x = -1;
  }
  void gpuOf(int q, double t, uint64_t* posted, uint64_t* polled) const {
    uint64_t a = (uint64_t)t + 3, c = (uint64_t)t + 1;  // a post every ms, two WQEs pending
    if (q == 3 && t >= gpuStallFrom) a = (uint64_t)gpuStallFrom + 3, c = (uint64_t)gpuStallFrom + 1;
    if (q == 3 && t >= gpuQuietFrom && t < gpuQuietTo) a = c = (uint64_t)gpuQuietFrom;
    *posted = a;
    *polled = c;
  }
  bool gpuSends(int q, double t) const {
    return !(q == 3 && (t >= gpuStallFrom || (t >= gpuQuietFrom && t < gpuQuietTo)));
  }
  void run(double until) {
    const int n = 4, subject = 3;
    const double probe = 100, suspect = 2000, stall = 10000;
    std::vector<std::vector<gdakiCtrlStale>> ds((size_t)n, std::vector<gdakiCtrlStale>((size_t)n)), ws = ds, hs = ds;
    std::vector<std::vector<double>> pub((size_t)n, std::vector<double>((size_t)n, 0.0)), seen = pub;
    std::vector<double> lastOk((size_t)n, -1e18);
    bool watchRose = false;
    for (double t = 0; t <= until; t += probe) {
      for (int r = 0; r < n; r++)
        for (int q = 0; q < n; q++) {
          if (q == r) continue;
          const bool hostFrozen = q == subject && t >= hostStallFrom;
          const bool helperFrozen = q == subject && (t >= hostStallFrom || t >= helperStallFrom);
          const uint64_t watchBeat = (uint64_t)((hostFrozen ? hostStallFrom : t)) + 1;
          const uint64_t helperBeat = (uint64_t)((helperFrozen ? std::min(hostStallFrom, helperStallFrom) : t) * 1000.0) + 1;
          bool rose = false;
          gdakiCtrlStaleOnRead(&ws[(size_t)r][(size_t)q], watchBeat, t, probe, &rose);
          gdakiCtrlStaleOnRead(&hs[(size_t)r][(size_t)q], helperBeat, t, probe);
          if (r == 0 && q == subject) watchRose = rose;
          double v = std::max(t - ws[(size_t)r][(size_t)q].firstMs, t - hs[(size_t)r][(size_t)q].firstMs);
          if (!(noLine && q == subject)) {
            DevArray a(n);
            uint64_t posted = 0, polled = 0;
            gpuOf(q, t, &posted, &polled);
            a.set(r, posted, polled);  // q's QP toward r carries its posts (the other elements stay 0)
            gdakiCtrlDevOnRead(&ds[(size_t)r][(size_t)q], a.sum(), t, probe);
            v = std::max(v, t - ds[(size_t)r][(size_t)q].firstMs);
          }
          pub[(size_t)r][(size_t)q] = v;
          if (r == 0) {
            lastOk[(size_t)q] = t;
            seen[(size_t)q] = pub[(size_t)q];
          }
        }
      double others[2];
      bool valid[2];
      int no = 0;
      for (int k = 1; k < n; k++) {
        if (k == subject) continue;
        others[no] = seen[(size_t)k][(size_t)subject];
        const double kStale = ws[0][(size_t)k].lastMs - ws[0][(size_t)k].firstMs;  // k's host beat (the page's writer)
        valid[no] = t - lastOk[(size_t)k] <= 3 * probe && kStale < suspect;
        no++;
      }
      struct gdakiCtrlRFacts f;
      f.okInGen = true;
      f.devMode = !noLine;
      f.devOk = !unreadFirst;
      const gdakiCtrlStale& d03 = ds[0][(size_t)subject];
      f.devStaleMs = d03.have ? d03.lastMs - d03.firstMs : 0;
      f.watchRose = watchRose;
      f.watchStaleMs = ws[0][(size_t)subject].lastMs - ws[0][(size_t)subject].firstMs;
      f.helperStaleMs = hs[0][(size_t)subject].lastMs - hs[0][(size_t)subject].firstMs;
      f.guardOk = gdakiCtrlPartitionGuard(others, valid, no, stall, probe) == GDAKI_CTRL_PG_PASS;
      // the data path's veto (NCCL_GIN_TS_STALL_RMSN_MS): clear 1 000 ms after the subject's GPU stopped sending
      if (!gpuSends(subject, t)) {
        const double from = std::min(gpuStallFrom, gpuQuietFrom);
        f.vetoClear = t - from > 1000;
      } else {
        f.vetoClear = false;
      }
      if (noLine) f.vetoClear = true;  // the fallback scenes stop the host only (as gc_unit_p1's guard scenes)
      const uint32_t R = gdakiCtrlRDerive(f);
      const uint32_t row = judgeRow(GDAKI_CTRL_L_NORESP, GDAKI_CTRL_B_NONE, GDAKI_CTRL_W_OK, R);
      rows.insert(row);
      if (firstRowAt[row] < 0) firstRowAt[row] = t;
    }
  }
};
static void testLiveScenes() {
  // the GPU stalls with work pending, its host stays alive: row 14 (STALL) 10 000-10 300 ms after
  LiveScene a;
  a.gpuStallFrom = 1000;
  a.run(30000);
  CHECK(a.firstRowAt[14] >= 0 && a.firstRowAt[14] - 1000 >= 10000 && a.firstRowAt[14] - 1000 <= 10300);
  CHECK(a.firstRowAt[15] < 0 && a.firstRowAt[18] >= 0 && a.firstRowAt[18] < a.firstRowAt[14]);
  CHECK(gdakiCtrlJudgementOfRow(14).verdict == GDAKI_CTRL_V_STALL &&
        std::string(gdakiCtrlCauseName(gdakiCtrlJudgementOfRow(14).cause)) == "STALL");
  // the host's beats stop (a stopped process) while its GPU keeps posting: row 15 (STALL_HELPER), never 14
  LiveScene b;
  b.hostStallFrom = 1000;
  b.run(30000);
  CHECK(b.firstRowAt[15] >= 0 && b.firstRowAt[15] - 1000 >= 10000 && b.firstRowAt[15] - 1000 <= 10300);
  CHECK(b.firstRowAt[14] < 0);
  CHECK(std::string(gdakiCtrlCauseName(gdakiCtrlJudgementOfRow(15).cause)) == "STALL_HELPER");
  // the helper beat alone (watch beat and GPU going): row 15 as before
  LiveScene b2;
  b2.helperStallFrom = 1000;
  b2.run(30000);
  CHECK(b2.firstRowAt[15] >= 0 && b2.firstRowAt[15] - 1000 >= 10000 && b2.firstRowAt[15] - 1000 <= 10300 &&
        b2.firstRowAt[14] < 0);
  // a stopped host whose GPU finished its work (a quiet line): row 15, never 14
  LiveScene b3;
  b3.hostStallFrom = 1000;
  b3.gpuQuietFrom = 1000;
  b3.run(30000);
  CHECK(b3.firstRowAt[15] >= 0 && b3.firstRowAt[15] - 1000 >= 10000 && b3.firstRowAt[15] - 1000 <= 10300 &&
        b3.firstRowAt[14] < 0);
  // both stalled (a stopped host, its GPU stuck with work pending): row 14 first
  LiveScene c;
  c.gpuStallFrom = 1000;
  c.hostStallFrom = 1000;
  c.run(30000);
  CHECK(c.firstRowAt[14] >= 0 && c.firstRowAt[14] - 1000 >= 10000 && c.firstRowAt[14] - 1000 <= 10300);
  CHECK(c.firstRowAt[15] < 0 || c.firstRowAt[15] > c.firstRowAt[14]);
  // both alive: row 20 only
  LiveScene d;
  d.run(30000);
  CHECK(d.rows == std::set<uint32_t>({20}));
  // a long compute phase with no sends (a quiet line, 25 s) under a live host: never a stall or a suspicion
  LiveScene e;
  e.gpuQuietFrom = 1000;
  e.gpuQuietTo = 26000;
  e.run(30000);
  CHECK(e.rows == std::set<uint32_t>({20}));
  // the first period of a pairing: the line not read yet in this generation: row 13 (no verdict), never 14
  LiveScene f;
  f.unreadFirst = true;
  f.gpuStallFrom = 1000;
  f.run(15000);
  CHECK(f.rows == std::set<uint32_t>({13}));
  // a peer whose page names no line: the watch beat is the progress input as before (its stall is row 14)
  LiveScene g;
  g.noLine = true;
  g.hostStallFrom = 1000;
  g.run(30000);
  CHECK(g.firstRowAt[14] >= 0 && g.firstRowAt[14] - 1000 >= 10000 && g.firstRowAt[14] - 1000 <= 10300);
  LiveScene g2;
  g2.noLine = true;
  g2.gpuStallFrom = 1000;  // without a line the GPU's stall is not seen (the host-beat design's blind spot)
  g2.run(30000);
  CHECK(g2.rows == std::set<uint32_t>({20}));
  // R directly: the order of the two inputs
  struct gdakiCtrlRFacts x;
  x.okInGen = true;
  x.devMode = true;
  x.devOk = true;
  x.devStaleMs = 5000;
  x.watchStaleMs = 11000;
  x.helperStaleMs = 11000;
  CHECK(gdakiCtrlRDerive(x) == GDAKI_CTRL_R_HELPER_STALL);  // a host stall beats a GPU suspicion (row 15 before 18)
  x.devStaleMs = 11000;
  CHECK(gdakiCtrlRDerive(x) == GDAKI_CTRL_R_STALL);  // both: the GPU's (row 14)
  x.vetoClear = false;
  CHECK(gdakiCtrlRDerive(x) == GDAKI_CTRL_R_HELPER_STALL);  // the veto holds the GPU's stall back, not the host's
  x.vetoClear = true;
  x.guardOk = false;
  CHECK(gdakiCtrlRDerive(x) == GDAKI_CTRL_R_STALE_GUARDED);  // the guard holds both (row 18)
  x.guardOk = true;
  x.devStaleMs = 0;
  x.watchStaleMs = 0;
  x.helperStaleMs = 500;
  CHECK(gdakiCtrlRDerive(x) == GDAKI_CTRL_R_ROSE);
  x.devStaleMs = 300;
  CHECK(gdakiCtrlRDerive(x) == GDAKI_CTRL_R_STALE_LT_SUSPECT);  // an unchanged busy line below SUSPECT_MS: (2), row 20
  x.devStaleMs = 0;
  x.busy = GDAKI_CTRL_BZ_IN;
  x.helperStaleMs = 12000;
  CHECK(gdakiCtrlRDerive(x) == GDAKI_CTRL_R_HELPER_BUSY);  // busy within its bound (row 19)
  x.watchStaleMs = 12000;
  CHECK(gdakiCtrlRDerive(x) == GDAKI_CTRL_R_HELPER_STALL);  // the watch thread's own stall: no busy bound excuses it
  x.lastCls = GDAKI_CTRL_CQ_REMACC;
  CHECK(gdakiCtrlRDerive(x) == GDAKI_CTRL_R_REMACC);  // the READ facts first, as before
  x.lastCls = GDAKI_CTRL_CQ_OK;
  x.devOk = false;
  CHECK(gdakiCtrlRDerive(x) == GDAKI_CTRL_R_UNCONFIRMED);
  printf("live scenes (4 ranks, rank 0 judges rank 3): GPU stalled, host alive: row 14 at +%.0f ms; host stalled, GPU "
         "posting: row 15 at +%.0f ms; helper only: row 15 at +%.0f ms; host stalled, GPU quiet: row 15 at +%.0f ms; both: "
         "row 14 at +%.0f ms; both alive: row 20 only; 25 s quiet GPU: row 20 only; line unread: row 13 only; no line: "
         "watch stall row 14 at +%.0f ms, GPU stall unseen\n", a.firstRowAt[14] - 1000, b.firstRowAt[15] - 1000,
         b2.firstRowAt[15] - 1000, b3.firstRowAt[15] - 1000, c.firstRowAt[14] - 1000, g.firstRowAt[14] - 1000);
}

// ---- 4. the two-READ probe within the SQ bound ----
// One QP: the periodic pair every 100 ms (the page READ, then the device line's READ with the same sequence; a peer
// without a line posts the page READ alone), the window's two READs when a window opens (it needs 2 free slots), every
// READ completing in posting order after a random latency (sometimes past the 500 ms timeout). 1 ms steps.
struct Posted {
  uint32_t kind, seq;
  double doneAt;
};
static void testPairIo() {
  long pairs = 0, judged = 0, windows = 0, winJudged = 0, timeouts = 0, singles = 0;
  uint32_t maxOut = 0, maxLeft = 0;
  for (int run = 0; run < 40; run++) {
    std::mt19937_64 rng(0x6c697665ull + (uint64_t)run);
    std::uniform_real_distribution<double> u(0, 1);
    struct gdakiCtrlProbeIo io;
    struct gdakiCtrlWindow win;
    std::deque<Posted> fifo;
    double next = 0, lastDone = 0;
    const bool devLine = run % 4 != 3;  // every fourth run: a peer without a device line (one READ per period)
    uint32_t pairNeed = 0, pairSeen = 0, pairSeq = 0;
    for (double t = 0; t < 60000; t += 1) {
      // completions, in order
      while (!fifo.empty() && fifo.front().doneAt <= t) {
        const Posted x = fifo.front();
        fifo.pop_front();
        const bool ofPair = gdakiCtrlProbeIsPeriodic(&io, x.kind, x.seq);
        const bool done = gdakiCtrlProbeOnCqe(&io, x.kind, x.seq);
        CHECK(io.outstanding == fifo.size());
        if (ofPair) {
          CHECK(x.seq == pairSeq);
          pairSeen++;
          CHECK(done == (pairSeen == pairNeed));
          if (done) judged++;
        } else {
          CHECK(!done);
          if (x.kind == GDAKI_CTRL_PW_WIN1 || x.kind == GDAKI_CTRL_PW_WIN2)
            (void)gdakiCtrlWindowOnCqe(&win, x.seq, x.kind == GDAKI_CTRL_PW_WIN1 ? 1u : 2u, GDAKI_CTRL_CQ_OK, (uint64_t)t,
                                       0, t);
        }
      }
      auto post = [&](uint32_t kind, uint32_t seq) {
        CHECK(gdakiCtrlProbeCanPost(&io, 1));
        double lat = 0.02 + 0.3 * u(rng);
        if (u(rng) < 0.002) lat = 600 + 400 * u(rng);  // a READ past the timeout (the peer's NIC slow, or gone a while)
        const double at = std::max(t + lat, lastDone);  // in order
        lastDone = at;
        fifo.push_back({kind, seq, at});
        gdakiCtrlProbeOnPosted(&io, kind, seq, t);
        maxOut = std::max(maxOut, io.outstanding);
        maxLeft = std::max(maxLeft, io.periodicLeft);
        CHECK(io.outstanding <= GDAKI_CTRL_PROBE_SQ && io.periodicLeft <= 2);
      };
      if (gdakiCtrlProbeTimedOut(&io, t, 500)) timeouts++;
      // a window now and then
      if (u(rng) < 0.002 && gdakiCtrlWindowOpen(&win, GDAKI_CTRL_WSRC_FIN, t, gdakiCtrlProbeCanPost(&io, 2)))
        windows++;
      const uint32_t wa = gdakiCtrlWindowStep(&win, t, 20);
      if (wa == GDAKI_CTRL_WA_JUDGE) {
        (void)gdakiCtrlWindowJudge(&win, 0, t);
        winJudged++;
      } else if (wa == GDAKI_CTRL_WA_POST1 || wa == GDAKI_CTRL_WA_POST2) {
        const bool ok = gdakiCtrlProbeCanPost(&io, 1);
        if (ok) post(wa == GDAKI_CTRL_WA_POST1 ? GDAKI_CTRL_PW_WIN1 : GDAKI_CTRL_PW_WIN2, win.no);
        gdakiCtrlWindowPosted(&win, wa == GDAKI_CTRL_WA_POST1 ? 1u : 2u, ok, t);
        CHECK(ok);  // the window's slots are kept for it
      }
      // the periodic pair, never into the window's reserved slots
      const uint32_t reserve = win.state == GDAKI_CTRL_WS_OPEN && win.countable ? (uint32_t)!win.r1Posted + (uint32_t)!win.r2Posted : 0u;
      const uint32_t need = devLine ? 2u : 1u;
      const bool wasOut = io.periodicOut;
      const uint32_t seq = gdakiCtrlProbePeriodicDue(&io, t, next, reserve, need);
      if (seq != 0) {
        CHECK(!wasOut);  // the next pair only after both READs of the last one
        next = t + 100;
        pairSeq = seq;
        pairNeed = need;
        pairSeen = 0;
        post(GDAKI_CTRL_PW_PERIODIC, seq);
        if (devLine) post(GDAKI_CTRL_PW_DEV, seq);
        else singles++;
        pairs++;
      }
    }
  }
  CHECK(maxOut <= GDAKI_CTRL_PROBE_SQ && maxOut == 4 && maxLeft == 2);
  CHECK(judged > 0 && judged <= pairs && pairs - judged <= 40 && windows > 0 && winJudged > 0 && timeouts > 0);
  printf("pair io: 40 runs x 60 s, %ld periods (%ld of one READ), %ld judged (each after its last completion), %ld windows "
         "(%ld judged), %ld timeouts; at most %u READs in flight (SQ %u), at most %u of a pair\n", pairs, singles, judged,
         windows, winJudged, timeouts, maxOut, GDAKI_CTRL_PROBE_SQ, maxLeft);
}

// ---- 5. the confirmation window over the host's watch beat (smoke3, 2a-2-C step 5) ----
// t_F = 0, W = 20: READ1 posted at 0 and done at 0.1, READ2 posted at 10 and done at 10.1 (unless `r2None`), the verdict at
// 20. `b1`, `b2`: line 0's watchBeat at READ1 and READ2.
static uint32_t beatWindow(uint64_t b1, uint64_t b2, bool r2None, bool remacc1, uint64_t inc2) {
  struct gdakiCtrlWindow w;
  CHECK(gdakiCtrlWindowOpen(&w, GDAKI_CTRL_WSRC_FIN, 0, true));
  CHECK(gdakiCtrlWindowStep(&w, 0, 20) == GDAKI_CTRL_WA_POST1);
  gdakiCtrlWindowPosted(&w, 1, true, 0);
  (void)gdakiCtrlWindowOnCqe(&w, w.no, 1, remacc1 ? GDAKI_CTRL_CQ_REMACC : GDAKI_CTRL_CQ_OK, b1, 7, 0.1);
  CHECK(gdakiCtrlWindowStep(&w, 5, 20) == GDAKI_CTRL_WA_NONE);
  uint32_t a = gdakiCtrlWindowStep(&w, 10, 20);
  if (!remacc1) {
    CHECK(a == GDAKI_CTRL_WA_POST2);
    gdakiCtrlWindowPosted(&w, 2, true, 10);
    if (!r2None) (void)gdakiCtrlWindowOnCqe(&w, w.no, 2, GDAKI_CTRL_CQ_OK, b2, inc2, 10.1);
    a = gdakiCtrlWindowStep(&w, 19.9, 20);
    CHECK(a == GDAKI_CTRL_WA_NONE);
    a = gdakiCtrlWindowStep(&w, 20, 20);
  } else {
    CHECK(a == GDAKI_CTRL_WA_NONE);  // REMACC decided it: no READ2
    a = gdakiCtrlWindowStep(&w, 20, 20);
  }
  CHECK(a == GDAKI_CTRL_WA_JUDGE);
  const uint32_t cw = gdakiCtrlWindowJudge(&w, 7, 20);
  CHECK(w.endMs == 20);
  return cw;
}
// One window over a model of the subject (rank 3) after its witness socket's FIN or RST at t_F: its watch thread writes
// line 0's watchBeat every 0.9-1.1 ms until `beatStop` (the kill; never for a live peer), its GPU keeps posting on the
// device line until t_F + 100 ms (a SIGKILLed process's kernel runs until the thread group ends, smoke3); the reader
// steps every 0.05-1 ms; a READ reads its word halfway through its 2-300 us latency. Returns the verdict, *row the table's
// row at the verdict (L no information: the launcher's report comes later; R from the periodic READs: the line advances),
// *at the verdict's time, *devMoved whether the device line differed between READ1 and READ2 (the old device-line
// window would have called it alive).
struct BeatModel {
  double beatStop = 1e18;
  std::vector<double> beatAt;  // the watch beat's write times
  explicit BeatModel(std::mt19937_64& rng, double until, double stop) : beatStop(stop) {
    std::uniform_real_distribution<double> g(0.9, 1.1);
    for (double t = -500; t < until && t < stop; t += g(rng)) beatAt.push_back(t);
  }
  uint64_t beat(double t) const {  // writes done by t (the beat's value)
    return (uint64_t)(std::upper_bound(beatAt.begin(), beatAt.end(), t) - beatAt.begin());
  }
  static uint64_t dev(double t, double tF) { return (uint64_t)(std::min(t, tF + 100.0) * 4.0 + 4000.0); }  // a post / 0.25 ms
};
static uint32_t beatScene(std::mt19937_64& rng, bool kill, double W, uint32_t* row, double* at, bool* devMoved) {
  std::uniform_real_distribution<double> u(0, 1);
  const double tF = 200.0 + 100.0 * u(rng);
  const double tKill = tF - (0.07 + 0.24 * u(rng));  // the FIN comes 0.07-0.31 ms after the kill (design v2 4.1)
  BeatModel m(rng, tF + 3 * W + 300, kill ? tKill : 1e18);
  struct gdakiCtrlWindow w;
  // the periodic READs before t_F (every 100 ms): R's facts from the device line and the beats (both still rising)
  struct gdakiCtrlStale ds, ws, hs;
  for (double t = tF - 600; t <= tF + W; t += 100) {
    DevArray a(4);
    a.set(0, BeatModel::dev(t, tF) + 2, BeatModel::dev(t, tF));
    (void)gdakiCtrlDevOnRead(&ds, a.sum(), t, 100);
    (void)gdakiCtrlStaleOnRead(&ws, m.beat(t), t, 100);
    (void)gdakiCtrlStaleOnRead(&hs, m.beat(t) * 3, t, 100);
  }
  CHECK(gdakiCtrlWindowOpen(&w, kill ? GDAKI_CTRL_WSRC_FIN : GDAKI_CTRL_WSRC_RST, tF, true));
  double done[2] = {-1, -1}, readAt[2] = {-1, -1};
  uint64_t dev[2] = {0, 0};
  uint32_t v = GDAKI_CTRL_CW_UNCONFIRMED;
  *at = -1;
  for (double t = tF + 0.01; t <= tF + 3 * W; t += 0.05 + 0.95 * u(rng)) {
    for (int k = 0; k < 2; k++)
      if (done[k] >= 0 && t >= done[k]) {
        done[k] = -1;
        CHECK(gdakiCtrlWindowOnCqe(&w, w.no, (uint32_t)k + 1, GDAKI_CTRL_CQ_OK, m.beat(readAt[k]), 7, t));
      }
    const uint32_t a = gdakiCtrlWindowStep(&w, t, W);
    if (a == GDAKI_CTRL_WA_POST1 || a == GDAKI_CTRL_WA_POST2) {
      const int k = a == GDAKI_CTRL_WA_POST1 ? 0 : 1;
      const double lat = 0.002 + 0.298 * u(rng);
      readAt[k] = t + lat / 2;
      done[k] = t + lat;
      dev[k] = BeatModel::dev(readAt[k], tF);
      gdakiCtrlWindowPosted(&w, (uint32_t)k + 1, true, t);
    } else if (a == GDAKI_CTRL_WA_JUDGE) {
      v = gdakiCtrlWindowJudge(&w, 7, t);
      *at = t;
      break;
    }
  }
  struct gdakiCtrlRFacts f;
  f.okInGen = true;
  f.devMode = true;
  f.devOk = true;
  f.devStaleMs = ds.have ? ds.lastMs - ds.firstMs : 0;
  f.watchRose = true;
  f.watchStaleMs = ws.have ? ws.lastMs - ws.firstMs : 0;
  f.helperStaleMs = hs.have ? hs.lastMs - hs.firstMs : 0;
  f.vetoClear = false;  // the GPU still sends
  const uint32_t R = gdakiCtrlRDerive(f);
  *row = judgeRow(GDAKI_CTRL_L_NOINFO, GDAKI_CTRL_B_NONE, gdakiCtrlWofConfirm(v), R);
  *devMoved = dev[1] != dev[0];
  *at -= tF;
  return v;
}
static void testBeatWindow() {
  CHECK(beatWindow(100, 109, false, false, 7) == GDAKI_CTRL_CW_ALIVE);
  CHECK(beatWindow(100, 100, false, false, 7) == GDAKI_CTRL_CW_STALE);
  CHECK(beatWindow(100, 99, false, false, 7) == GDAKI_CTRL_CW_STALE);  // a beat that went back is not alive
  CHECK(beatWindow(100, 100, true, false, 7) == GDAKI_CTRL_CW_NORESP);
  CHECK(beatWindow(100, 100, false, true, 7) == GDAKI_CTRL_CW_REMACC);
  CHECK(beatWindow(100, 109, false, false, 8) == GDAKI_CTRL_CW_UNCONFIRMED);
  // the rows the verdicts give (the table unchanged): STALE row 4, NORESP 5, REMACC 6, alive 8
  CHECK(judgeRow(GDAKI_CTRL_L_NOINFO, GDAKI_CTRL_B_NONE, gdakiCtrlWofConfirm(GDAKI_CTRL_CW_STALE), GDAKI_CTRL_R_ROSE) == 4);
  CHECK(judgeRow(GDAKI_CTRL_L_NOINFO, GDAKI_CTRL_B_NONE, gdakiCtrlWofConfirm(GDAKI_CTRL_CW_ALIVE), GDAKI_CTRL_R_ROSE) == 8);
  CHECK(std::string(gdakiCtrlCauseName(gdakiCtrlJudgementOfRow(4).cause)) == "FIN+STALE");
  // smoke3's kill: the device line moves on for 100 ms after the FIN, the watch beat stopped at the kill
  std::mt19937_64 rng(0x6b696c6c33ull);
  long kills = 0, killStale = 0, devMovedN = 0, lives = 0, liveAlive = 0;
  double atMin = 1e18, atMax = -1;
  for (int i = 0; i < 2000; i++) {
    const double W = 20 + (double)(rng() % 31);
    uint32_t row = 0;
    double at = 0;
    bool moved = false;
    const uint32_t v = beatScene(rng, true, W, &row, &at, &moved);
    kills++;
    if (v == GDAKI_CTRL_CW_STALE && row == 4) killStale++;
    CHECK(v == GDAKI_CTRL_CW_STALE && row == 4);
    CHECK(at >= W - 1e-9 && at <= W + 2.0 + 1e-9);  // at t_F + W (+ READ2's late post and one reader step)
    atMin = std::min(atMin, at - W);
    atMax = std::max(atMax, at - W);
    devMovedN += moved;
    CHECK(moved);  // the device line did move between the two READs (the old window's "alive")
    const uint32_t v2 = beatScene(rng, false, W, &row, &at, &moved);
    lives++;
    liveAlive += v2 == GDAKI_CTRL_CW_ALIVE && row == 8;
    CHECK(v2 == GDAKI_CTRL_CW_ALIVE && row == 8);  // never a false STALE for a live peer (W/2 >= 10 ms, gaps <= 1.1 ms)
  }
  printf("beat window (W 20): advanced alive, unchanged or older STALE (row 4), READ2 missing NORESP, REMACC at READ1, "
         "another process unconfirmed; %ld kill scenes with the device line moving 100 ms after the FIN (%ld moved "
         "between READ1 and READ2): %ld FIN+STALE (row 4) at t_F + W + %.3f-%.3f ms; %ld live scenes: %ld alive (row 8)\n",
         kills, devMovedN, killStale, atMin, atMax, lives, liveAlive);
}

// ---- 6. the 1 170-point grid: the per-row counts (the table is unchanged) ----
static const long kRowPoints[22] = {0, 234, 468, 117, 39, 39, 39, 39, 39, 39, 3, 1, 5, 9, 9, 9, 9, 9, 36, 9, 18, 0};
static void testGrid() {
  long reach[22] = {}, points = 0;
  for (uint32_t L = 0; L < GDAKI_CTRL_L_N; L++)
    for (uint32_t B = 0; B < GDAKI_CTRL_B_N; B++)
      for (uint32_t W = 0; W < GDAKI_CTRL_W_N; W++)
        for (uint32_t R = 0; R < GDAKI_CTRL_R_N; R++) {
          const uint32_t row = judgeRow(L, B, W, R);
          CHECK(row >= 1 && row <= 21);
          reach[row <= 21 ? row : 0]++;
          points++;
        }
  CHECK(points == 1170);
  for (int r = 1; r <= 21; r++) CHECK(reach[r] == kRowPoints[r]);
  printf("grid: %ld points; per row (1..21):", points);
  for (int r = 1; r <= 21; r++) printf(" %ld", reach[r]);
  printf("\n");
}
#endif

int main() {
#if !NCCL_GIN_CTRL_TCP
  testLayout();
  testDevClock();
  testLiveScenes();
  testPairIo();
  testBeatWindow();
  testGrid();
#endif
  printf("gc_unit_live (%s): %ld checks, %ld failed\n", NCCL_GIN_CTRL_TCP ? "tcp" : "rdma", gChecks, gFailed);
  return gFailed == 0 ? 0 : 1;
}
