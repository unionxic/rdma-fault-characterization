// gc_unit_p1.cc - CPU unit test of gin-control phase 1 (EXPERIMENT.md 9.8 "CPU 단위 모형", the status page and the fence
// models). No NCCL, no CUDA, no verbs, no network. Compiled in a build_gc.sh `unit` style: g++ -std=c++17 with ASan and
// UBSan, with gin-mirror's and gin-restore's headers and the working tree's cut pure regions:
//   - gc_page_pure.inc: the region "gin-control (page): pure functions" of the host file (the window end's W value, the
//     activation gate, the window's width and clock, the liveness READ's slots, completion classes and wr_id, the stall
//     definition, the partition guard, R, L and W, the fence word's step, the mailbox, the FREEZE_PAGE switch);
//   - rs_ctrl_api.h: the status page words, the seqlock report line, the confirm-window verdict, the fence word, the fence
//     report names and the judgement table gdakiCtrlJudge with its inputs, verdicts and causes.
// What it checks (REVIEW_P12 고칠 것 6: the counts below are scenes, not repeated checks of one property):
//   1. the judgement words model: only aligned 8 B reads give one moment's value;
//   2. the report-line seqlock model: a writer thread and randomly interleaved readers, 0 torn even-ver lines;
//   3. the stall definition, including a stalled reader (the origin reset), and the R value of one beat;
//   4. the judgement table over the whole 1 170-point grid against an independent table-driven reference (EXPERIMENT.md
//      9.3's 21 rows as data, the first match found by a generic loop), with the per-row point counts counted by hand
//      (REVIEW_P12: 234, 468, 117, 39 x 6, 3, 1, 5, 9 x 5, 36, 9, 18, 0), the floor property and the cells' rows;
//   5. the confirmation window's clock (READ1 at t_F, READ2 at t_F + W/2, the verdict at t_F + W whatever the
//      completions; late completions dropped by the window's number);
//   6. the liveness READ's send queue (one periodic READ at a time, the timeout a report, never above SQ 4) and the
//      completion classes; the dead-peer scene (timeout at 500 ms, retry exceeded at 3.66 s is R (11));
//   7. R's order, L and W;
//   8. the partition guard over four ranks (one rank stalled: judged; the reader alone sees everyone stale: not judged;
//      another survivor sees the peer fresh: not judged; two ranks);
//   9. the fence word, its step and gdakiLnFenceOf over a lineage oracle (the design 4.4 scenes);
//  10. the mailbox words and the FREEZE_PAGE switch's values.
#include <algorithm>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
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
// the hold-cell states and the lineage, as the standalone mi_unit_lineage.cc supplies them
enum { GDAKI_POLICY_FAILFAST = 0, GDAKI_POLICY_HOLD = 1 };
// the activation gate's /proc verdict values (host file next to gdakiRsActExamine)
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

// ---- 1. the judgement words model (design 3.2): an aligned 8 B store/load is one moment's value ----
static void testWords() {
  struct gdakiCtrlPageHead h;
  memset(&h, 0, sizeof(h));
  CHECK(sizeof(h) == 64);
  std::atomic<bool> stop{false};
  std::atomic<uint64_t> bad{0}, ok{0};
  // the writer advances every judgement word; a reader reads each aligned word and checks it decodes to a whole value
  std::thread wr([&] {
    for (uint64_t v = 1; !stop.load(std::memory_order_relaxed); v++) {
      gdakiCtrlWordStore(&h.watchBeat, v);
      gdakiCtrlWordStore(&h.helperBusy, gdakiCtrlBusyWord((uint32_t)(v & 0x7fffffffu) | 1u, 25000));
      gdakiCtrlWordStore(&h.incNonce, gdakiCtrlIncNonce((uint32_t)(v & 7u), v));
    }
  });
  for (int i = 0; i < 400000; i++) {
    const uint64_t b = gdakiCtrlWordLoad(&h.watchBeat);
    const uint64_t busy = gdakiCtrlWordLoad(&h.helperBusy);
    const uint64_t in = gdakiCtrlWordLoad(&h.incNonce);
    // each word decodes consistently (a torn 8 B word would give a busy number of 0 with a nonzero bound, say)
    if (busy != 0 && gdakiCtrlBusyNoOf(busy) == 0) bad++;
    else ok++;
    (void)b;
    (void)in;
  }
  stop.store(true);
  wr.join();
  CHECK(bad.load() == 0 && ok.load() > 0);
  printf("words: %llu aligned reads, %llu inconsistent\n", (unsigned long long)ok.load(), (unsigned long long)bad.load());
}

// ---- 2. the report-line seqlock model (design 3.2; rs_ctrl_api.h) ----
// Phase 1's choice (REVIEW_PREP 1단계 note 1): the report line keeps its 7-word body and the remote snapshot judges only
// on the even `ver` (gdakiCtrlLineSnapshotOk); the w[6]-repeat form (gdakiCtrlLineSnapshotOk2) is NOT used, because the
// current writer gdakiCtrlLineWrite cannot produce it (it would have to write ver into w[6] before the body) and it
// would shrink the body to 6 words. The judgement never reads report lines anyway (only the aligned 8 B words); the
// report line is reporting only, and a torn line is dropped (page_torn_n).
static void testSeqlock() {
  struct gdakiCtrlReportLine line;
  memset(&line, 0, sizeof(line));
  std::atomic<bool> stop{false};
  std::atomic<uint64_t> good{0}, retry{0}, torn{0};
  std::thread wr([&] {
    uint64_t w7[7];
    for (uint64_t v = 1; !stop.load(std::memory_order_relaxed); v++) {
      for (int i = 0; i < 7; i++) w7[i] = v;  // all seven body words equal the line's sequence
      gdakiCtrlLineWrite(&line, w7);
    }
  });
  std::vector<std::thread> rd;
  for (int t = 0; t < 3; t++)
    rd.emplace_back([&] {
      uint64_t w7[7];
      for (int i = 0; i < 300000; i++) {
        if (!gdakiCtrlLineRead(&line, w7)) { retry++; continue; }
        bool same = true;
        for (int k = 1; k < 7; k++) same = same && w7[k] == w7[0];
        if (same) good++;
        else torn++;
      }
    });
  for (auto& t : rd) t.join();
  stop.store(true);
  wr.join();
  CHECK(torn.load() == 0 && good.load() > 0);
  // the chosen remote-snapshot form: an even ver is a whole line, an odd ver is being written
  struct gdakiCtrlReportLine s;
  memset(&s, 0, sizeof(s));
  s.ver = 8;
  CHECK(gdakiCtrlLineSnapshotOk(&s));
  s.ver = 9;  // odd: being written
  CHECK(!gdakiCtrlLineSnapshotOk(&s));
  printf("seqlock: %llu consistent, %llu retries, %llu torn (7-word body form)\n", (unsigned long long)good.load(),
         (unsigned long long)retry.load(), (unsigned long long)torn.load());
}

// ---- 3. the stall definition model (design 3.4), including a stalled reader ----
static void testStall() {
  const double probe = 100.0, suspect = 2000.0, stall = 10000.0;
  struct gdakiCtrlStale s;
  s = gdakiCtrlStale();
  // a steadily rising beat: the stall stays 0
  for (int i = 0; i < 50; i++) CHECK(gdakiCtrlStaleOnRead(&s, (uint64_t)(i + 1), i * probe, probe) == 0.0);
  // the beat freezes at t = 5000; the stall grows with the reader's own clock
  s = gdakiCtrlStale();
  double t = 0;
  gdakiCtrlStaleOnRead(&s, 1, t, probe);  // the first sighting sets the origin at t = 0
  for (int i = 1; i <= 120; i++) {
    t = i * probe;
    const double st = gdakiCtrlStaleOnRead(&s, 1, t, probe);  // the value never changes from 1
    CHECK(st == t);                                           // the stall grows from the first sighting at t = 0
  }
  // a stalled reader: a gap larger than 2 x probe resets the origin, so the reader's own stall is not the peer's
  s = gdakiCtrlStale();
  gdakiCtrlStaleOnRead(&s, 7, 0, probe);
  gdakiCtrlStaleOnRead(&s, 7, probe, probe);        // normal gap: stall = probe
  const double afterGap = gdakiCtrlStaleOnRead(&s, 7, probe + 5000.0, probe);  // a 5 s reader gap
  CHECK(afterGap == 0.0);                            // the origin was reset to now
  // the R value from the stall length and the partition guard
  double others[3] = {stall, stall, stall};
  CHECK(gdakiCtrlStallGuard(others, 3, stall, probe));
  others[1] = stall - 2 * probe;  // exactly at the bar (>= passes)
  CHECK(gdakiCtrlStallGuard(others, 3, stall, probe));
  others[1] = stall - 2 * probe - 1.0;
  CHECK(!gdakiCtrlStallGuard(others, 3, stall, probe));
  CHECK(gdakiCtrlRofStale(true, 50000, suspect, stall, true, true, false) == GDAKI_CTRL_R_ROSE);
  CHECK(gdakiCtrlRofStale(false, 500, suspect, stall, true, true, false) == GDAKI_CTRL_R_STALE_LT_SUSPECT);
  CHECK(gdakiCtrlRofStale(false, 5000, suspect, stall, true, true, false) == GDAKI_CTRL_R_STALE_SUSPECT);
  CHECK(gdakiCtrlRofStale(false, 11000, suspect, stall, false, true, false) == GDAKI_CTRL_R_STALE_GUARDED);
  CHECK(gdakiCtrlRofStale(false, 11000, suspect, stall, true, false, false) == GDAKI_CTRL_R_STALE_GUARDED);
  CHECK(gdakiCtrlRofStale(false, 11000, suspect, stall, true, true, false) == GDAKI_CTRL_R_STALL);
  CHECK(gdakiCtrlRofStale(false, 500, suspect, stall, true, true, true) == GDAKI_CTRL_R_ROSE);  // helper < SUSPECT is (1)
  CHECK(gdakiCtrlRofStale(false, 5000, suspect, stall, true, true, true) == GDAKI_CTRL_R_HELPER_SUSPECT);
  CHECK(gdakiCtrlRofStale(false, 11000, suspect, stall, true, true, true) == GDAKI_CTRL_R_HELPER_STALL);
  // W's width (결정 대기 5: factor 10, clamped 20..50)
  CHECK(gdakiCtrlConfirmW(10, 1.0) == 20);   // 10 ms -> clamp up to 20
  CHECK(gdakiCtrlConfirmW(10, 3.0) == 30);   // 30 ms
  CHECK(gdakiCtrlConfirmW(10, 8.0) == 50);   // 80 ms -> clamp down to 50
  CHECK(gdakiCtrlConfirmW(5, 3.0) == 20);    // the 5x option would give 15 -> clamp to 20
  printf("stall: ok\n");
}

// ---- 4. the judgement table: an independent table-driven reference ----
// EXPERIMENT.md 9.3's 21 rows as data: per row the L, B, W and R values it holds as bit sets read off the table's columns
// (an empty cell: every value); R by the design's numbers (1)..(13) (RD), not the header's names. The first row whose four
// sets hold the point matches (a generic loop, nothing of gdakiCtrlJudge's if chain).
struct RefRow {
  uint32_t l, b, w, r;
};
#define ALLV 0xffffffffu
#define BITV(x) (1u << (x))
#define RD(k) (1u << ((k) - 1))  // R value (k) of design v3 4.2
static const RefRow kRef[21] = {
    /* 1 */ {BITV(GDAKI_CTRL_L_LEFT), ALLV, ALLV, ALLV},
    /* 2 */ {ALLV, BITV(GDAKI_CTRL_B_SEEN), ALLV, ALLV},
    /* 3 */ {BITV(GDAKI_CTRL_L_ENDED), ALLV, ALLV, ALLV},
    /* 4 */ {ALLV, ALLV, BITV(GDAKI_CTRL_W_END_STALE), ALLV},
    /* 5 */ {ALLV, ALLV, BITV(GDAKI_CTRL_W_END_NORESP), ALLV},
    /* 6 */ {ALLV, ALLV, BITV(GDAKI_CTRL_W_END_REMACC), ALLV},
    /* 7 */ {ALLV, ALLV, BITV(GDAKI_CTRL_W_OPEN), ALLV},
    /* 8 */ {ALLV, ALLV, BITV(GDAKI_CTRL_W_END_ALIVE), ALLV},
    /* 9 */ {ALLV, ALLV, BITV(GDAKI_CTRL_W_END_UNCONFIRMED), ALLV},
    /* 10 */ {BITV(GDAKI_CTRL_L_NORESP), ALLV, ALLV, RD(11)},
    /* 11 */ {BITV(GDAKI_CTRL_L_NOINFO), ALLV, BITV(GDAKI_CTRL_W_OFF), RD(11)},
    /* 12 */ {ALLV, ALLV, ALLV, RD(11)},
    /* 13 */ {ALLV, ALLV, ALLV, RD(13)},
    /* 14 */ {ALLV, ALLV, ALLV, RD(5)},
    /* 15 */ {ALLV, ALLV, ALLV, RD(9)},
    /* 16 */ {ALLV, ALLV, ALLV, RD(10)},
    /* 17 */ {ALLV, ALLV, ALLV, RD(12)},
    /* 18 */ {ALLV, ALLV, ALLV, RD(3) | RD(4) | RD(7) | RD(8)},
    /* 19 */ {ALLV, ALLV, ALLV, RD(6)},
    /* 20 */ {ALLV, ALLV, ALLV, RD(1) | RD(2)},
    /* 21 */ {ALLV, ALLV, ALLV, ALLV},
};
static uint32_t refRow(uint32_t L, uint32_t B, uint32_t W, uint32_t R) {
  for (uint32_t i = 0; i < 21; i++) {
    const RefRow& x = kRef[i];
    if (((x.l >> L) & 1u) && ((x.b >> B) & 1u) && ((x.w >> W) & 1u) && ((x.r >> R) & 1u)) return i + 1;
  }
  return 0;
}
// The points per row, counted by hand from the table (REVIEW_P12 고칠 것 6): 5 x 2 x 9 x 13 = 1 170.
static const long kRowPoints[22] = {0, 234, 468, 117, 39, 39, 39, 39, 39, 39, 3, 1, 5, 9, 9, 9, 9, 9, 36, 9, 18, 0};
static void testJudge() {
  static_assert(GDAKI_CTRL_R_ROSE == 0 && GDAKI_CTRL_R_UNCONFIRMED == 12, "R (k) is the header's value k - 1");
  long points = 0, reach[22] = {}, sum = 0;
  for (int r = 0; r < 22; r++) sum += kRowPoints[r];
  CHECK(sum == 1170);
  for (uint32_t L = 0; L < GDAKI_CTRL_L_N; L++)
    for (uint32_t B = 0; B < GDAKI_CTRL_B_N; B++)
      for (uint32_t W = 0; W < GDAKI_CTRL_W_N; W++)
        for (uint32_t R = 0; R < GDAKI_CTRL_R_N; R++) {
          const uint32_t row = judgeRow(L, B, W, R);
          CHECK(row >= 1 && row <= 21);
          CHECK(row == refRow(L, B, W, R));
          reach[row < 22 ? row : 0]++;
          points++;
          const struct gdakiCtrlJudgement j = gdakiCtrlJudge(L, B, W, R);
          CHECK(j.verdict == gdakiCtrlJudgementOfRow(row).verdict && j.cause == gdakiCtrlJudgementOfRow(row).cause);
          // the floor property: a row that holds or refuses rests on ended / a confirmed window / no response / a stall
          const uint32_t v = j.verdict;
          if (v == GDAKI_CTRL_V_ENDED || v == GDAKI_CTRL_V_UNREACHABLE || v == GDAKI_CTRL_V_STALL ||
              v == GDAKI_CTRL_V_STALL_HELPER) {
            const bool floor =
                (L == GDAKI_CTRL_L_ENDED) || (W == GDAKI_CTRL_W_END_STALE) || (W == GDAKI_CTRL_W_END_NORESP) ||
                (W == GDAKI_CTRL_W_END_REMACC) || (R == GDAKI_CTRL_R_HW_NORESP) || (R == GDAKI_CTRL_R_STALL) ||
                (R == GDAKI_CTRL_R_HELPER_STALL);
            CHECK(floor);
          }
          if ((R == GDAKI_CTRL_R_TIMEOUT_ONLY || R == GDAKI_CTRL_R_REMACC) && row >= 12) CHECK(v == GDAKI_CTRL_V_NONE);
        }
  CHECK(points == 1170);
  for (int r = 1; r <= 21; r++) CHECK(reach[r] == kRowPoints[r]);  // the order of the chain is the table's
  // the cells' scenarios (EXPERIMENT.md 9.3, 3절)
  CHECK(judgeRow(GDAKI_CTRL_L_NOINFO, GDAKI_CTRL_B_NONE, GDAKI_CTRL_W_END_NORESP, GDAKI_CTRL_R_ROSE) == 5);
  CHECK(judgeRow(GDAKI_CTRL_L_NOINFO, GDAKI_CTRL_B_NONE, GDAKI_CTRL_W_END_STALE, GDAKI_CTRL_R_ROSE) == 4);
  CHECK(judgeRow(GDAKI_CTRL_L_NOINFO, GDAKI_CTRL_B_NONE, GDAKI_CTRL_W_END_REMACC, GDAKI_CTRL_R_ROSE) == 6);
  CHECK(judgeRow(GDAKI_CTRL_L_ENDED, GDAKI_CTRL_B_NONE, GDAKI_CTRL_W_OK, GDAKI_CTRL_R_ROSE) == 3);
  CHECK(judgeRow(GDAKI_CTRL_L_NOINFO, GDAKI_CTRL_B_NONE, GDAKI_CTRL_W_OFF, GDAKI_CTRL_R_HW_NORESP) == 11);
  CHECK(judgeRow(GDAKI_CTRL_L_NORESP, GDAKI_CTRL_B_NONE, GDAKI_CTRL_W_UNKNOWN, GDAKI_CTRL_R_HW_NORESP) == 10);
  CHECK(judgeRow(GDAKI_CTRL_L_NORESP, GDAKI_CTRL_B_NONE, GDAKI_CTRL_W_OK, GDAKI_CTRL_R_STALL) == 14);
  CHECK(judgeRow(GDAKI_CTRL_L_NORESP, GDAKI_CTRL_B_NONE, GDAKI_CTRL_W_OK, GDAKI_CTRL_R_HELPER_STALL) == 15);
  CHECK(judgeRow(GDAKI_CTRL_L_ALIVE, GDAKI_CTRL_B_NONE, GDAKI_CTRL_W_END_ALIVE, GDAKI_CTRL_R_ROSE) == 8);
  CHECK(judgeRow(GDAKI_CTRL_L_ALIVE, GDAKI_CTRL_B_SEEN, GDAKI_CTRL_W_END_STALE, GDAKI_CTRL_R_ROSE) == 2);
  CHECK(judgeRow(GDAKI_CTRL_L_LEFT, GDAKI_CTRL_B_NONE, GDAKI_CTRL_W_END_STALE, GDAKI_CTRL_R_STALL) == 1);
  // every row's verdict, written plainly from EXPERIMENT.md 9.3's 판정 column (row 21 has none: 닿지 않음)
  static const uint32_t kVerdict[22] = {0, GDAKI_CTRL_V_LEFT, GDAKI_CTRL_V_LEFT, GDAKI_CTRL_V_ENDED, GDAKI_CTRL_V_ENDED,
      GDAKI_CTRL_V_ENDED, GDAKI_CTRL_V_ENDED, GDAKI_CTRL_V_WAIT, GDAKI_CTRL_V_ALIVE_WITNESS_LOST, GDAKI_CTRL_V_NONE,
      GDAKI_CTRL_V_UNREACHABLE, GDAKI_CTRL_V_ENDED, GDAKI_CTRL_V_RDMA_PATH, GDAKI_CTRL_V_NONE, GDAKI_CTRL_V_STALL,
      GDAKI_CTRL_V_STALL_HELPER, GDAKI_CTRL_V_NONE, GDAKI_CTRL_V_NONE, GDAKI_CTRL_V_SUSPECT, GDAKI_CTRL_V_HELPER_BUSY,
      GDAKI_CTRL_V_ALIVE, GDAKI_CTRL_V_NONE};
  for (uint32_t r = 1; r <= 21; r++) CHECK(gdakiCtrlJudgementOfRow(r).verdict == kVerdict[r] && gdakiCtrlJudgementOfRow(r).row == r);
  std::set<std::string> holdCauses;
  for (uint32_t r = 1; r <= 21; r++) {
    const struct gdakiCtrlJudgement j = gdakiCtrlJudgementOfRow(r);
    if (j.verdict == GDAKI_CTRL_V_ENDED || j.verdict == GDAKI_CTRL_V_STALL || j.verdict == GDAKI_CTRL_V_STALL_HELPER)
      holdCauses.insert(gdakiCtrlCauseName(j.cause));
    else if (r == 10) CHECK(std::string(gdakiCtrlCauseName(j.cause)) == "LINKDOWN");
    else CHECK(j.cause == GDAKI_CTRL_C_NONE && gdakiCtrlCauseName(j.cause)[0] == 0);
  }
  CHECK(holdCauses == std::set<std::string>({"EXITED", "FIN+STALE", "FIN+NORESP", "REMACC+FIN", "NORESP", "STALL", "STALL_HELPER"}));
  printf("judge: %ld points; per row (1..21):", points);
  for (int r = 1; r <= 21; r++) printf(" %ld", reach[r]);
  printf(" (the hand counts; row 21 unreached)\n");
}

// ---- 5. the confirmation window's clock (design v3 4.2): the verdict at t_F + W, late completions dropped ----
struct WinEv {
  double at;     // the completion's time (1e18: none within reach)
  uint32_t cls;  // GDAKI_CTRL_CQ_*
};
static void testWindow() {
  std::mt19937_64 rng(0x77696e646f77ull);
  const double step = 0.02;
  long scenes = 0, byV[5] = {}, late = 0, atOnce = 0, atEnd = 0, ignored = 0;
  for (int i = 0; i < 6000; i++) {
    const double W = 20 + (double)(rng() % 31), tF = (double)(rng() % 1000);
    struct gdakiCtrlWindow w;
    w.no = (uint32_t)(rng() % 100);
    const bool countable0 = rng() % 6 != 0;
    CHECK(gdakiCtrlWindowOpen(&w, GDAKI_CTRL_WSRC_FIN, tF, countable0));
    CHECK(!gdakiCtrlWindowOpen(&w, GDAKI_CTRL_WSRC_RST, tF + 1, true));  // a new FIN while open: ignored
    ignored += w.ignored;
    const uint32_t no = w.no;
    const bool postOk[2] = {rng() % 20 != 0, rng() % 20 != 0};
    WinEv ev[2];
    double postAt[2] = {-1, -1};
    for (int k = 0; k < 2; k++) {
      const uint32_t c = (uint32_t)(rng() % 20);
      ev[k].cls = c < 16 ? GDAKI_CTRL_CQ_OK : c < 17 ? GDAKI_CTRL_CQ_REMACC : c < 18 ? GDAKI_CTRL_CQ_NORESP : GDAKI_CTRL_CQ_BROKEN;
      ev[k].at = (double)(rng() % 70) + 0.005;  // the delay after its post
      if (ev[k].cls == GDAKI_CTRL_CQ_NORESP) ev[k].at = 3660.0;  // retry exceeded: long after the verdict
    }
    const uint64_t incExp = gdakiCtrlIncNonce((uint32_t)(rng() % 8), rng());
    const bool otherPage = rng() % 10 == 0;
    const uint64_t beat1 = rng() % 4 == 0 ? 0xfffffffffffffffeull : rng();
    const uint64_t beat2 = rng() % 2 ? beat1 + 1 + rng() % 5 : beat1;
    const uint64_t incs[2] = {incExp, otherPage ? incExp ^ 1 : incExp};
    const uint64_t beats[2] = {beat1, beat2};
    bool delivered[2] = {false, false};
    double judgeAt = -1;
    uint32_t v = 99;
    for (double t = tF; t <= tF + W + 1.0; t += step) {
      for (int k = 0; k < 2; k++)  // the completions due by now
        if (postAt[k] >= 0 && postOk[k] && !delivered[k] && postAt[k] + ev[k].at <= t) {
          delivered[k] = true;
          CHECK(gdakiCtrlWindowOnCqe(&w, no, (uint32_t)k + 1, ev[k].cls, beats[k], incs[k], t));
        }
      bool judged = false;
      for (int guard = 0; guard < 3; guard++) {
        const uint32_t a = gdakiCtrlWindowStep(&w, t, W);
        if (a == GDAKI_CTRL_WA_NONE) break;
        if (a == GDAKI_CTRL_WA_JUDGE) {
          judgeAt = t;
          v = gdakiCtrlWindowJudge(&w, incExp, t);
          judged = true;
          break;
        }
        const int k = a == GDAKI_CTRL_WA_POST1 ? 0 : 1;
        postAt[k] = t;
        gdakiCtrlWindowPosted(&w, (uint32_t)k + 1, postOk[k]);
      }
      if (judged) break;
    }
    CHECK(judgeAt >= 0 && w.state == GDAKI_CTRL_WS_IDLE);
    // after the verdict: every completion still due is dropped by the window's number
    for (int k = 0; k < 2; k++)
      if (postAt[k] >= 0 && postOk[k] && !delivered[k]) {
        CHECK(!gdakiCtrlWindowOnCqe(&w, no, (uint32_t)k + 1, ev[k].cls, beats[k], incs[k], postAt[k] + ev[k].at));
        late++;
      }
    // the independent expectation, from the events before the verdict
    bool countable = countable0, remacc = false, d1 = false, d2 = false;
    for (int k = 0; k < 2; k++) {
      if (postAt[k] >= 0 && !postOk[k]) countable = false;
      if (!delivered[k]) continue;
      if (ev[k].cls == GDAKI_CTRL_CQ_BROKEN) countable = false;
      if (ev[k].cls == GDAKI_CTRL_CQ_REMACC) remacc = true;
      if (ev[k].cls == GDAKI_CTRL_CQ_OK) (k == 0 ? d1 : d2) = true;
    }
    uint32_t want;
    if (!countable) want = GDAKI_CTRL_CW_UNCONFIRMED;
    else if (remacc) want = GDAKI_CTRL_CW_REMACC;
    else if (!d1 || !d2) want = GDAKI_CTRL_CW_NORESP;
    else if (otherPage) want = GDAKI_CTRL_CW_UNCONFIRMED;
    else want = (int64_t)(beat2 - beat1) > 0 ? GDAKI_CTRL_CW_ALIVE : GDAKI_CTRL_CW_STALE;
    CHECK(v == want);
    // the time: at t_F + W (one step of the watch thread) unless it cannot confirm, then at once
    const bool early = !countable0 || (postAt[0] >= 0 && !postOk[0]) || (postAt[1] >= 0 && !postOk[1]) ||
                       (delivered[0] && ev[0].cls == GDAKI_CTRL_CQ_BROKEN) || (delivered[1] && ev[1].cls == GDAKI_CTRL_CQ_BROKEN);
    if (!early) {
      CHECK(judgeAt >= tF + W - 1e-9 && judgeAt < tF + W + step + 1e-9);
      atEnd++;
    } else {
      CHECK(judgeAt <= tF + W + step);
      atOnce++;
    }
    if (!countable0) CHECK(judgeAt == tF);
    // the W value into the table
    const uint32_t row = judgeRow(GDAKI_CTRL_L_NOINFO, GDAKI_CTRL_B_NONE, gdakiCtrlWofConfirm(v), GDAKI_CTRL_R_ROSE);
    static const uint32_t kRowOf[5] = {8, 4, 5, 6, 9};
    CHECK(v < 5 && row == kRowOf[v]);
    if (v < 5) byV[v]++;
    scenes++;
  }
  for (int k = 0; k < 5; k++) CHECK(byV[k] > 0);
  CHECK(gdakiCtrlBeatAdvanced(0xffffffffffffffffull, 0) && !gdakiCtrlBeatAdvanced(0, 0xffffffffffffffffull));
  printf("window: %ld scenes (alive %ld, STALE %ld, NORESP %ld, REMACC %ld, unconfirmed %ld): %ld judged at t_F + W, %ld at "
         "once (cannot confirm), %ld late completions dropped, %ld second FINs ignored\n",
         scenes, byV[0], byV[1], byV[2], byV[3], byV[4], atEnd, atOnce, late, ignored);
}

// ---- 6. the liveness READ's send queue and completion classes (REVIEW_P12 막는 문제 4, 5) ----
static void testProbeIo() {
  // the classes: retry exceeded (both kinds) is no response, a remote access error REMACC, everything else broken
  CHECK(gdakiCtrlProbeCqeClass(GDAKI_CTRL_WC_SUCCESS) == GDAKI_CTRL_CQ_OK);
  CHECK(gdakiCtrlProbeCqeClass(GDAKI_CTRL_WC_RETRY_EXC_ERR) == GDAKI_CTRL_CQ_NORESP);
  CHECK(gdakiCtrlProbeCqeClass(GDAKI_CTRL_WC_RNR_RETRY_EXC_ERR) == GDAKI_CTRL_CQ_NORESP);
  CHECK(gdakiCtrlProbeCqeClass(GDAKI_CTRL_WC_REM_ACCESS_ERR) == GDAKI_CTRL_CQ_REMACC);
  long broken = 0;
  for (int st = 1; st <= 21; st++) {
    if (st == GDAKI_CTRL_WC_RETRY_EXC_ERR || st == GDAKI_CTRL_WC_RNR_RETRY_EXC_ERR || st == GDAKI_CTRL_WC_REM_ACCESS_ERR) continue;
    CHECK(gdakiCtrlProbeCqeClass(st) == GDAKI_CTRL_CQ_BROKEN);  // flush (5), local (1, 2, 4, 8), remote op (11), ...
    // a broken QP never feeds rows 10-12: R is (13), whatever L and W
    struct gdakiCtrlRFacts f;
    f.lastCls = gdakiCtrlProbeCqeClass(st);
    f.okInGen = false;
    CHECK(gdakiCtrlRDerive(f) == GDAKI_CTRL_R_UNCONFIRMED);
    for (uint32_t L = 0; L < GDAKI_CTRL_L_N; L++)
      for (uint32_t W = 0; W < GDAKI_CTRL_W_N; W++) {
        const uint32_t row = judgeRow(L, GDAKI_CTRL_B_NONE, W, gdakiCtrlRDerive(f));
        CHECK(row != 10 && row != 11 && row != 12);
      }
    broken++;
  }
  // the wr_id
  std::mt19937_64 rng(0x70726f6265ull);
  for (int i = 0; i < 2000; i++) {
    const uint32_t k = 1 + (uint32_t)(rng() % 3), p = (uint32_t)(rng() % 4096), g = (uint32_t)rng(), s = (uint32_t)rng();
    const uint64_t id = gdakiCtrlProbeWrId(k, p, g, s);
    CHECK(gdakiCtrlProbeWrKind(id) == k && gdakiCtrlProbeWrPeer(id) == p && gdakiCtrlProbeWrSeq(id) == s);
    CHECK(gdakiCtrlProbeWrGenIs(id, g) && !gdakiCtrlProbeWrGenIs(id, g + 1));
  }
  // the dead peer: the READ posted at 0 is answered by retry exceeded 3 660 ms later; one READ in flight all along
  {
    struct gdakiCtrlProbeIo io;
    double next = 0;
    int posts = 0, timeouts = 0;
    double firstTimeout = -1;
    uint32_t seq = 0;
    struct gdakiCtrlRFacts f;
    f.okInGen = true;
    f.watchRose = true;
    uint32_t rowAtTimeout = 0, rowAtCqe = 0;
    for (double t = 0; t <= 5000; t += 1.0) {
      const uint32_t s = gdakiCtrlProbePeriodicDue(&io, t, next, 0);
      if (s != 0) {
        gdakiCtrlProbeOnPosted(&io, GDAKI_CTRL_PW_PERIODIC, s, t);
        seq = s;
        next = t + 100;
        posts++;
      }
      if (gdakiCtrlProbeTimedOut(&io, t, 500)) {
        timeouts++;
        if (firstTimeout < 0) firstTimeout = t;
        f.timedOut = true;
        rowAtTimeout = judgeRow(GDAKI_CTRL_L_NORESP, GDAKI_CTRL_B_NONE, GDAKI_CTRL_W_OK, gdakiCtrlRDerive(f));
      }
      if (t == 3660.0) {  // the retry-exceeded completion of that READ
        CHECK(posts == 1);
        CHECK(gdakiCtrlProbeOnCqe(&io, GDAKI_CTRL_PW_PERIODIC, seq));
        f.timedOut = false;
        f.lastCls = gdakiCtrlProbeCqeClass(GDAKI_CTRL_WC_RETRY_EXC_ERR);
        f.okInGen = false;  // the QP broke with it
        rowAtCqe = judgeRow(GDAKI_CTRL_L_NORESP, GDAKI_CTRL_B_NONE, GDAKI_CTRL_W_OK, gdakiCtrlRDerive(f));
        CHECK(gdakiCtrlRDerive(f) == GDAKI_CTRL_R_HW_NORESP);
        CHECK(judgeRow(GDAKI_CTRL_L_NOINFO, GDAKI_CTRL_B_NONE, GDAKI_CTRL_W_OFF, gdakiCtrlRDerive(f)) == 11);
        CHECK(judgeRow(GDAKI_CTRL_L_NOINFO, GDAKI_CTRL_B_NONE, GDAKI_CTRL_W_OK, gdakiCtrlRDerive(f)) == 12);
        break;
      }
    }
    CHECK(posts == 1 && timeouts == 1 && firstTimeout == 501.0 && io.maxOutstanding == 1);
    CHECK(rowAtTimeout == 17 && rowAtCqe == 10);
    printf("probe: the dead peer: 1 READ in flight 0-3660 ms, the timeout once at %.0f ms (row %u), retry exceeded at "
           "3660 ms is R (11) (row %u with no launcher; 11 with the witness off and no information; 12 else)\n",
           firstTimeout, rowAtTimeout, rowAtCqe);
  }
  // random traffic: windows open, READs complete in any order, never above the SQ depth
  long steps = 0, windows = 0, refused = 0;
  for (int run = 0; run < 200; run++) {
    struct gdakiCtrlProbeIo io;
    struct gdakiCtrlWindow w;
    std::vector<std::pair<uint32_t, uint32_t>> inflight;  // (kind, seq)
    double next = 0;
    for (double t = 0; t < 3000; t += 1.0, steps++) {
      if (rng() % 50 == 0 && w.state == GDAKI_CTRL_WS_IDLE)
        windows += gdakiCtrlWindowOpen(&w, GDAKI_CTRL_WSRC_FIN, t, gdakiCtrlProbeCanPost(&io, 2));
      for (int g = 0; g < 3; g++) {
        const uint32_t a = gdakiCtrlWindowStep(&w, t, 20);
        if (a == GDAKI_CTRL_WA_NONE) break;
        if (a == GDAKI_CTRL_WA_JUDGE) {
          (void)gdakiCtrlWindowJudge(&w, 0, t);
          break;
        }
        const uint32_t kind = a == GDAKI_CTRL_WA_POST1 ? GDAKI_CTRL_PW_WIN1 : GDAKI_CTRL_PW_WIN2;
        const bool ok = gdakiCtrlProbeCanPost(&io, 1);
        if (ok) {
          gdakiCtrlProbeOnPosted(&io, kind, w.no, t);
          inflight.push_back({kind, w.no});
        } else {
          refused++;
        }
        gdakiCtrlWindowPosted(&w, a == GDAKI_CTRL_WA_POST1 ? 1u : 2u, ok);
      }
      const uint32_t reserve = w.state == GDAKI_CTRL_WS_OPEN ? (uint32_t)!w.r1Posted + (uint32_t)!w.r2Posted : 0u;
      const uint32_t s = gdakiCtrlProbePeriodicDue(&io, t, next, reserve);
      if (s != 0) {
        gdakiCtrlProbeOnPosted(&io, GDAKI_CTRL_PW_PERIODIC, s, t);
        inflight.push_back({GDAKI_CTRL_PW_PERIODIC, s});
        next = t + 100;
      }
      CHECK(io.outstanding <= GDAKI_CTRL_PROBE_SQ && io.outstanding == inflight.size());
      if (!inflight.empty() && rng() % 40 == 0) {  // a dead peer's READs come back late, in any order
        const size_t k = (size_t)(rng() % inflight.size());
        const bool per = gdakiCtrlProbeOnCqe(&io, inflight[k].first, inflight[k].second);
        CHECK(per == (inflight[k].first == GDAKI_CTRL_PW_PERIODIC));
        inflight.erase(inflight.begin() + (long)k);
      }
    }
    CHECK(io.maxOutstanding <= GDAKI_CTRL_PROBE_SQ);
  }
  printf("probe: %ld broken completion statuses never reach rows 10-12; %ld steps of random traffic with %ld windows: the "
         "SQ never above %u (%ld window READs refused for want of a slot)\n",
         broken, steps, windows, GDAKI_CTRL_PROBE_SQ, refused);
}

// ---- 7. R's order, L and W (REVIEW_P12 고칠 것 1, 2) ----
static void testRLW() {
  struct gdakiCtrlRFacts f;
  f.okInGen = true;
  f.watchRose = true;
  CHECK(gdakiCtrlRDerive(f) == GDAKI_CTRL_R_ROSE);
  struct gdakiCtrlRFacts g = f;
  g.probeOff = true;
  g.lastCls = GDAKI_CTRL_CQ_REMACC;
  CHECK(gdakiCtrlRDerive(g) == GDAKI_CTRL_R_UNCONFIRMED);  // PROBE_MS = 0 first
  g = f;
  g.lastCls = GDAKI_CTRL_CQ_REMACC;
  g.timedOut = true;
  CHECK(gdakiCtrlRDerive(g) == GDAKI_CTRL_R_REMACC);  // the error class before the timeout
  g.lastCls = GDAKI_CTRL_CQ_NORESP;
  g.okInGen = false;
  CHECK(gdakiCtrlRDerive(g) == GDAKI_CTRL_R_HW_NORESP);  // before "no success in this generation"
  g = f;
  g.timedOut = true;
  g.okInGen = false;
  CHECK(gdakiCtrlRDerive(g) == GDAKI_CTRL_R_TIMEOUT_ONLY);
  g = f;
  g.okInGen = false;
  CHECK(gdakiCtrlRDerive(g) == GDAKI_CTRL_R_UNCONFIRMED);
  g = f;
  g.pageOk = false;
  CHECK(gdakiCtrlRDerive(g) == GDAKI_CTRL_R_UNCONFIRMED);  // another process's page (incNonce)
  // the watch beat not risen: (2)-(5), the guard and the veto
  g = f;
  g.watchRose = false;
  g.watchStaleMs = 500;
  CHECK(gdakiCtrlRDerive(g) == GDAKI_CTRL_R_STALE_LT_SUSPECT);
  g.watchStaleMs = 5000;
  CHECK(gdakiCtrlRDerive(g) == GDAKI_CTRL_R_STALE_SUSPECT);
  g.watchStaleMs = 11000;
  CHECK(gdakiCtrlRDerive(g) == GDAKI_CTRL_R_STALL);
  g.vetoClear = false;
  CHECK(gdakiCtrlRDerive(g) == GDAKI_CTRL_R_STALE_GUARDED);
  g.vetoClear = true;
  g.guardOk = false;
  CHECK(gdakiCtrlRDerive(g) == GDAKI_CTRL_R_STALE_GUARDED);
  // risen: the helper side
  g = f;
  g.helperStaleMs = 12000;
  CHECK(gdakiCtrlRDerive(g) == GDAKI_CTRL_R_HELPER_STALL);
  g.busy = GDAKI_CTRL_BZ_IN;
  CHECK(gdakiCtrlRDerive(g) == GDAKI_CTRL_R_HELPER_BUSY);
  g.busy = GDAKI_CTRL_BZ_OVER;
  g.busyOverMs = 500;
  CHECK(gdakiCtrlRDerive(g) == GDAKI_CTRL_R_ROSE);  // the stall counts from the bound's end: 500 ms < SUSPECT_MS
  g.busyOverMs = 4000;
  CHECK(gdakiCtrlRDerive(g) == GDAKI_CTRL_R_HELPER_SUSPECT);
  g.busy = GDAKI_CTRL_BZ_NONE;
  g.guardOk = false;
  CHECK(gdakiCtrlRDerive(g) == GDAKI_CTRL_R_HELPER_GUARDED);
  // the busy word on the reader's clock
  struct gdakiCtrlBusySeen bs;
  double over = 0;
  CHECK(gdakiCtrlBusySeenStep(&bs, gdakiCtrlBusyWord(3, 1000), 100, &over) == GDAKI_CTRL_BZ_IN);
  CHECK(gdakiCtrlBusySeenStep(&bs, gdakiCtrlBusyWord(3, 1000), 1100, &over) == GDAKI_CTRL_BZ_IN);
  CHECK(gdakiCtrlBusySeenStep(&bs, gdakiCtrlBusyWord(3, 1000), 1600, &over) == GDAKI_CTRL_BZ_OVER && over == 500);
  CHECK(gdakiCtrlBusySeenStep(&bs, gdakiCtrlBusyWord(4, 1000), 1700, &over) == GDAKI_CTRL_BZ_IN);  // a new number
  CHECK(gdakiCtrlBusySeenStep(&bs, 0, 1800, &over) == GDAKI_CTRL_BZ_NONE);
  // L (phase 1: no launcher pairing is 무응답) and W
  CHECK(gdakiCtrlLOf(false, false, false, false, false, false) == GDAKI_CTRL_L_NORESP);
  CHECK(gdakiCtrlLOf(false, true, true, false, false, false) == GDAKI_CTRL_L_LEFT);
  CHECK(gdakiCtrlLOf(false, false, true, false, false, false) == GDAKI_CTRL_L_ENDED);
  CHECK(gdakiCtrlLOf(true, false, false, true, true, false) == GDAKI_CTRL_L_ALIVE);
  CHECK(gdakiCtrlLOf(true, false, false, true, false, false) == GDAKI_CTRL_L_NOINFO);
  CHECK(gdakiCtrlLOf(true, false, false, true, false, true) == GDAKI_CTRL_L_LEFT);
  CHECK(gdakiCtrlLOf(true, false, false, false, true, false) == GDAKI_CTRL_L_NORESP);
  CHECK(gdakiCtrlWOf(true, true, false, 0, false) == GDAKI_CTRL_W_OPEN);
  for (uint32_t cw = 0; cw <= GDAKI_CTRL_CW_UNCONFIRMED; cw++)
    CHECK(gdakiCtrlWOf(true, false, true, cw, true) == GDAKI_CTRL_W_END_ALIVE + cw);
  CHECK(gdakiCtrlWOf(false, false, false, 0, true) == GDAKI_CTRL_W_OFF);
  CHECK(gdakiCtrlWOf(true, false, false, 0, true) == GDAKI_CTRL_W_UNKNOWN);
  CHECK(gdakiCtrlWOf(true, false, false, 0, false) == GDAKI_CTRL_W_OK);
  printf("rlw: R's order (PROBE_MS=0, error class, timeout, generation, watch, helper), the busy bound, L and W: ok\n");
}

// ---- 8. the partition guard over four ranks (design v3 3.4; REVIEW_P12 막는 문제 3) ----
// Every rank reads every other rank's page each 100 ms (watchBeat +1 per ms) and publishes its stall of each in its own
// page (staleMs[]); rank 0 judges rank 3 with the others' published view of 3. A scene returns when rank 0 judged 3
// stalled (ms after the stall began), -1 never.
struct GuardWorld {
  int n = 4;
  double stopAt = 1e18;            // rank 3's watch beat stops
  bool readerFrozen = false;       // rank 0 sees every page frozen from t = 1000 (it alone is cut off)
  bool onlyReaderSees3 = false;    // only rank 0's view of rank 3 freezes (the others see 3 fresh)
  double judge(int nRanks) {
    n = nRanks;
    const int subject = n - 1;
    const double probe = 100, suspect = 2000, stall = 10000;
    std::vector<std::vector<gdakiCtrlStale>> st((size_t)n, std::vector<gdakiCtrlStale>((size_t)n));
    std::vector<std::vector<double>> pub((size_t)n, std::vector<double>((size_t)n, 0.0));   // staleMs[] of each page
    std::vector<std::vector<double>> seen((size_t)n, std::vector<double>((size_t)n, 0.0));  // rank 0's copy of pub
    std::vector<double> lastOk((size_t)n, -1e18);
    std::vector<uint64_t> frozenBeat((size_t)n, 0);
    for (double t = 0; t <= 40000; t += probe) {
      for (int r = 0; r < n; r++)
        for (int q = 0; q < n; q++) {
          if (q == r) continue;
          uint64_t beat = (uint64_t)t + 1;
          if (q == subject && t >= stopAt) beat = (uint64_t)stopAt + 1;
          if (r == 0 && t >= 1000 && (readerFrozen || (onlyReaderSees3 && q == subject))) {
            if (frozenBeat[(size_t)q] == 0) frozenBeat[(size_t)q] = beat;
            beat = frozenBeat[(size_t)q];
          }
          const double s = gdakiCtrlStaleOnRead(&st[(size_t)r][(size_t)q], beat, t, probe);
          pub[(size_t)r][(size_t)q] = s;
          if (r == 0) {
            lastOk[(size_t)q] = t;
            seen[(size_t)q] = pub[(size_t)q];  // the page of q as rank 0 read it (q's own view of everyone)
          }
        }
      // rank 0 judges the subject
      double others[8];
      bool valid[8];
      int no = 0;
      for (int k = 1; k < n; k++) {
        if (k == subject) continue;
        others[no] = seen[(size_t)k][(size_t)subject];
        valid[no] = t - lastOk[(size_t)k] <= 3 * probe && pub[0][(size_t)k] < suspect;
        no++;
      }
      const uint32_t guard = gdakiCtrlPartitionGuard(others, valid, no, stall, probe);
      const uint32_t R = gdakiCtrlRofStale(false, pub[0][(size_t)subject], suspect, stall, guard == GDAKI_CTRL_PG_PASS,
                                           true, false);
      if (judgeRow(GDAKI_CTRL_L_NORESP, GDAKI_CTRL_B_NONE, GDAKI_CTRL_W_OK, R) == 14) return t;
    }
    return -1;
  }
};
static void testGuard() {
  GuardWorld a;
  a.stopAt = 1000;  // one rank stalled: the others see it too
  const double tA = a.judge(4);
  CHECK(tA >= 0 && tA - a.stopAt >= 10000 && tA - a.stopAt <= 10300);
  GuardWorld b;
  b.readerFrozen = true;  // the reader alone sees everyone stale: it suspects itself
  CHECK(b.judge(4) < 0);
  GuardWorld c;
  c.onlyReaderSees3 = true;  // the others see rank 3 fresh
  CHECK(c.judge(4) < 0);
  GuardWorld d;
  d.stopAt = 1000;  // two ranks: no third view, the reader's own (a line for the design)
  const double tD = d.judge(2);
  CHECK(tD >= 0 && tD - d.stopAt >= 10000 && tD - d.stopAt <= 10300);
  // the guard's three answers directly
  const double fresh[2] = {200, 12000}, stale[2] = {11000, 12000};
  const bool bothValid[2] = {true, true}, none[2] = {false, false};
  CHECK(gdakiCtrlPartitionGuard(stale, bothValid, 2, 10000, 100) == GDAKI_CTRL_PG_PASS);
  CHECK(gdakiCtrlPartitionGuard(fresh, bothValid, 2, 10000, 100) == GDAKI_CTRL_PG_FRESH);
  CHECK(gdakiCtrlPartitionGuard(stale, none, 2, 10000, 100) == GDAKI_CTRL_PG_SELF);
  CHECK(gdakiCtrlPartitionGuard(nullptr, nullptr, 0, 10000, 100) == GDAKI_CTRL_PG_PASS);
  printf("guard: four ranks, one stalled: judged %.0f ms after the stall; the reader alone sees everyone stale: not "
         "judged; another survivor sees it fresh: not judged; two ranks: judged %.0f ms after\n", tA - a.stopAt, tD - d.stopAt);
}

// ---- 9. the fence word and gdakiLnFenceOf over a lineage oracle (design 4.4): the difference is the gate cell only ----
static const uint32_t kStates[9] = {GDAKI_HOLD_OFF,        GDAKI_HOLD_ARMED,              GDAKI_HOLD_HELD,
                                    GDAKI_HOLD_COMMITTING, GDAKI_HOLD_PUBLISHED,          GDAKI_HOLD_TIMED_OUT_HELD,
                                    GDAKI_HOLD_TIMED_OUT_PUBLISHED, GDAKI_HOLD_FALLBACK,   GDAKI_HOLD_CANCELLED};
static void testFence() {
  // the fence word (REVIEW2 막는 문제 1): 0 = no fence, so a hold of incarnation 0 is not fenced right after the setup
  CHECK(!gdakiCtrlFencedIs(GDAKI_CTRL_FENCE_NONE, 0) && !gdakiCtrlFencedIs(GDAKI_CTRL_FENCE_NONE, 1));
  CHECK(gdakiCtrlFencedIs(gdakiCtrlFenceWord(0), 0) && !gdakiCtrlFencedIs(gdakiCtrlFenceWord(0), 1));
  CHECK(gdakiCtrlFencedIs(gdakiCtrlFenceWord(1), 1) && !gdakiCtrlFencedIs(gdakiCtrlFenceWord(1), 0));
  // an old incarnation's FENCED does not unblock a later hold: FENCED(i-1) is not dead = i
  CHECK(!gdakiCtrlFencedIs(gdakiCtrlFenceWord(0), 1) && !gdakiCtrlFencedIs(gdakiCtrlFenceWord(1), 2));

  long points = 0, gateDiff = 0, nameDiff = 0;
  std::set<int> diffPhases;
  for (uint32_t s : kStates)
    for (uint32_t c = 0; c <= 3; c++)
      for (int dk = -1; dk <= 1; dk++) {
        if (c == 0 && dk < 0) continue;
        const uint32_t k = c + (uint32_t)dk;
        if (!(k == c || k == c + 1)) continue;  // invariant 1
        for (int dec = 0; dec < 2; dec++)
          for (int wf = 0; wf < 2; wf++)         // the fence word: none, or dead's
            for (int fs = 0; fs < 2; fs++) {     // FENCE sent or not
              const struct gdakiLnView v = gdakiLnViewOf(s, c, k, dec != 0);
              const uint64_t word = wf ? gdakiCtrlFenceWord(v.dead) : GDAKI_CTRL_FENCE_NONE;
              const bool fenced = gdakiCtrlFencedIs(word, v.dead);
              points++;
              // the report name: FENCING/FENCED only in HOLD_WAIT, an independent expectation
              const uint32_t fn = gdakiLnFenceOf(v.phase, v.dead, word, fs != 0);
              uint32_t wantFn = GDAKI_LN_FENCE_NONE;
              if (v.phase == GDAKI_LN_HOLD_WAIT) wantFn = fenced ? GDAKI_LN_FENCE_FENCED : (fs ? GDAKI_LN_FENCE_FENCING : GDAKI_LN_FENCE_NONE);
              CHECK(fn == wantFn);
              if (fn != GDAKI_LN_FENCE_NONE) nameDiff++;
              // the activation gate is consulted only where the buddy attempts an activation: the peer is held with all
              // HOLDING gathered, i.e. HOLD_WAIT with the dead incarnation. There the old gate (HOLDING complete -> GO)
              // vs the new gate (and fenced) differ exactly when not yet fenced. Outside HOLD_WAIT no activation is
              // attempted, so the gate is not reached (no difference by construction).
              if (v.phase == GDAKI_LN_HOLD_WAIT) {
                const int oldGate = GDAKI_RS_ACT_GO;  // the pre-fence gate would activate once HOLDING is complete
                const int newGate = gdakiCtrlActGate(true, fenced, GDAKI_RS_ACT_GO);
                if (oldGate != newGate) {
                  gateDiff++;
                  diffPhases.insert((int)v.phase);
                  CHECK(!fenced);  // the only cell that differs: HOLD_WAIT, not yet fenced
                }
              }
            }
      }
  // the gate differs only in HOLD_WAIT
  CHECK(diffPhases == std::set<int>({(int)GDAKI_LN_HOLD_WAIT}));
  // phase 1 (no launcher): the gate is the /proc verdict, unchanged
  CHECK(gdakiCtrlActGate(false, false, GDAKI_RS_ACT_GO) == GDAKI_RS_ACT_GO);
  CHECK(gdakiCtrlActGate(false, false, GDAKI_RS_ACT_WAIT) == GDAKI_RS_ACT_WAIT);
  printf("fence: %ld points, %ld gate differences (HOLD_WAIT only), %ld non-NONE report names\n", points, gateDiff, nameDiff);
}

// ---- 9b. the fence word's step and the design 4.4 scenes ----
static void testFenceScenes() {
  // gdakiLnFencedStep over every lineage class: CURRENT and HELD_OLD raise to max, FUTURE and STALE leave the word
  const uint32_t classes[4] = {GDAKI_LN_CURRENT, GDAKI_LN_HELD_OLD, GDAKI_LN_STALE, GDAKI_LN_FUTURE};
  for (uint32_t c : classes)
    for (uint64_t w0 = 0; w0 < 4; w0++)
      for (uint32_t inc = 0; inc < 4; inc++) {
        const uint64_t w = gdakiLnFencedStep(w0, c, inc);
        if (c == GDAKI_LN_STALE || c == GDAKI_LN_FUTURE) CHECK(w == w0);
        else CHECK(w == std::max<uint64_t>(w0, gdakiCtrlFenceWord(inc)));
        CHECK(w >= w0);  // never down
      }
  // right after the setup: no rank is fenced; incarnation 0's hold right after its start: the activation waits
  const struct gdakiLnView live0 = gdakiLnViewOf(GDAKI_HOLD_ARMED, 0, 0, false);
  const struct gdakiLnView held0 = gdakiLnViewOf(GDAKI_HOLD_HELD, 0, 0, false);
  CHECK(live0.phase == GDAKI_LN_LIVE && held0.phase == GDAKI_LN_HOLD_WAIT && held0.dead == 0);
  uint64_t word = GDAKI_CTRL_FENCE_NONE;
  CHECK(gdakiCtrlActGate(true, gdakiCtrlFencedIs(word, held0.dead), GDAKI_RS_ACT_GO) == GDAKI_RS_ACT_WAIT);
  // EXITED(0) before the hold (LIVE: CURRENT), then the hold with every HOLDING: the activation goes
  word = gdakiLnFencedStep(word, gdakiLnClassify(live0, 0), 0);
  CHECK(word == gdakiCtrlFenceWord(0));
  CHECK(gdakiCtrlActGate(true, gdakiCtrlFencedIs(word, held0.dead), GDAKI_RS_ACT_GO) == GDAKI_RS_ACT_GO);
  CHECK(gdakiLnFenceOf(held0.phase, held0.dead, word, false) == GDAKI_LN_FENCE_FENCED);
  // incarnation 1 held later: the old FENCED(0) does not open it, an old incarnation's FENCED again does not either
  const struct gdakiLnView held1 = gdakiLnViewOf(GDAKI_HOLD_HELD, 1, 1, false);
  CHECK(held1.phase == GDAKI_LN_HOLD_WAIT && held1.dead == 1);
  CHECK(!gdakiCtrlFencedIs(word, held1.dead));
  word = gdakiLnFencedStep(word, gdakiLnClassify(held1, 0), 0);  // FENCED(0) while 1 is held: STALE
  CHECK(word == gdakiCtrlFenceWord(0) && gdakiLnClassify(held1, 0) == GDAKI_LN_STALE);
  CHECK(gdakiLnFenceOf(held1.phase, held1.dead, word, true) == GDAKI_LN_FENCE_FENCING);
  // a FUTURE one (the successor's) does not fence either; FENCED(1) of the held one (HELD_OLD) does
  CHECK(gdakiLnClassify(held1, 2) == GDAKI_LN_FUTURE && gdakiLnFencedStep(word, GDAKI_LN_FUTURE, 2) == word);
  word = gdakiLnFencedStep(word, gdakiLnClassify(held1, 1), 1);
  CHECK(gdakiLnClassify(held1, 1) == GDAKI_LN_HELD_OLD && gdakiCtrlFencedIs(word, 1));
  // and it never goes down
  CHECK(gdakiLnFencedStep(word, GDAKI_LN_CURRENT, 0) == word);
  printf("fence: the step over every class (CURRENT, HELD_OLD raise to max; STALE, FUTURE leave it; never down) and the "
         "design 4.4 scenes: ok\n");
}

// ---- 10. the mailbox words and the FREEZE_PAGE values ----
static void testMailFreeze() {
  const uint64_t m = gdakiCtrlMailPack(14, GDAKI_CTRL_V_STALL, GDAKI_CTRL_C_STALL, 0xfffffffeu);
  CHECK(m != 0 && gdakiCtrlMailRow(m) == 14 && gdakiCtrlMailVerdict(m) == GDAKI_CTRL_V_STALL &&
        gdakiCtrlMailCause(m) == GDAKI_CTRL_C_STALL && gdakiCtrlMailInc(m) == 0xfffffffeu);
  CHECK(gdakiCtrlMailPack(0, 0, 0, 0) != 0);  // never the empty word
  // the latch: one exchange takes it, the second finds nothing
  std::atomic<uint64_t> box{0};
  box.store(m);
  CHECK(box.exchange(0) == m && box.exchange(0) == 0);
  struct gdakiCtrlFreezeSpec f;
  CHECK(gdakiCtrlFreezeParse("12000", &f) && f.on && !f.helperOnly && f.lenMs == 12000 && f.afterMs == 0);
  CHECK(gdakiCtrlFreezeParse("12000:helper", &f) && f.helperOnly && f.lenMs == 12000);
  CHECK(gdakiCtrlFreezeParse("500@3000", &f) && !f.helperOnly && f.afterMs == 3000);
  CHECK(gdakiCtrlFreezeParse("500:helper@10", &f) && f.helperOnly && f.afterMs == 10);
  CHECK(!gdakiCtrlFreezeParse("", &f) && !gdakiCtrlFreezeParse("x", &f) && !gdakiCtrlFreezeParse("0", &f) &&
        !gdakiCtrlFreezeParse("12000:helpers", &f) && !gdakiCtrlFreezeParse("100@", &f));
  printf("mail and freeze: ok\n");
}
#endif  // !NCCL_GIN_CTRL_TCP

int main() {
#if !NCCL_GIN_CTRL_TCP
  testWords();
  testSeqlock();
  testStall();
  testJudge();
  testWindow();
  testProbeIo();
  testRLW();
  testGuard();
  testFence();
  testFenceScenes();
  testMailFreeze();
#endif
  printf("gc_unit_p1 (%s): %ld checks, %ld failed\n", NCCL_GIN_CTRL_TCP ? "tcp" : "rdma", gChecks, gFailed);
  return gFailed == 0 ? 0 : 1;
}
