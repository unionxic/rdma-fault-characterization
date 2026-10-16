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
//   5. the confirmation window over a model of the QP (READ1 at t_F, READ2 at t_F + W/2, the verdict at
//      max(t_F + W, READ2 + W/2); in-order completions, flushes after the first error, no READ2 on a broken QP; a
//      late and stalling reader; late completions dropped by the window's number; REVIEW_FIX12_P2B 막는 문제 1, 2);
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
  // the data path's veto is the watch beat's only (design v3 4.2 R (8), (9); REVIEW_FIX12_P2B 막는 문제 3)
  CHECK(gdakiCtrlRofStale(false, 11000, suspect, stall, true, false, true) == GDAKI_CTRL_R_HELPER_STALL);
  CHECK(gdakiCtrlRofStale(false, 11000, suspect, stall, false, false, true) == GDAKI_CTRL_R_HELPER_GUARDED);
  CHECK(gdakiCtrlRofStale(false, 5000, suspect, stall, true, false, true) == GDAKI_CTRL_R_HELPER_SUSPECT);
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

// ---- 5. the confirmation window over a model of the QP (design v3 4.2; REVIEW_FIX12_P2B 막는 문제 1, 2) ----
// The QP model is the verbs rule (REVIEW_FIX12_P2B 막는 문제 1: no READ2 of its own on a broken QP): completions come in
// posting order; the first error completion moves the QP to ERR, and a READ posted before it that is still outstanding,
// or posted after it (the host's software state still RTS until it polls the error), completes as a flush after it. The
// host posts only while no error completion has been polled (gdakiProbeQpIsRts). The reader steps at irregular times:
// mostly 0.02-1 ms apart, sometimes a stall up to W (the watch thread's other peers, its mailbox; 막는 문제 2), and it
// first steps after the request at a random delay (sometimes past t_F + W/2: the late reader).
struct WinRead {
  bool posted = false, polled = false;
  double postAt = -1, doneAt = 1e18;
  uint32_t cls = GDAKI_CTRL_CQ_OK;
};
static void testWindow() {
  std::mt19937_64 rng(0x77696e646f77ull);
  long scenes = 0, byV[5] = {}, late = 0, atOnce = 0, atEnd = 0, ignored = 0, lateReaders = 0, remacc1 = 0, flushed2 = 0;
  long liveStalled = 0, read2Late = 0;
  for (int i = 0; i < 20000; i++) {
    const double W = 20 + (double)(rng() % 31), tF = (double)(rng() % 1000);
    struct gdakiCtrlWindow w;
    w.no = (uint32_t)(rng() % 100);
    const bool countable0 = rng() % 8 != 0;
    const bool live = rng() % 4 == 0;  // a live peer: both READs succeed within 1 ms
    uint32_t want[2];
    double delay[2];
    for (int k = 0; k < 2; k++) {
      const uint32_t c = (uint32_t)(rng() % 20);
      want[k] = live || c < 14 ? GDAKI_CTRL_CQ_OK : c < 16 ? GDAKI_CTRL_CQ_REMACC : c < 18 ? GDAKI_CTRL_CQ_NORESP : GDAKI_CTRL_CQ_BROKEN;
      delay[k] = live ? 0.005 + (double)(rng() % 1000) / 1000.0 : (double)(rng() % 70) + 0.005;
      if (want[k] == GDAKI_CTRL_CQ_NORESP) delay[k] = 3660.0;  // retry exceeded: long after the verdict
    }
    const uint64_t incExp = gdakiCtrlIncNonce((uint32_t)(rng() % 8), rng());
    const bool otherPage = !live && rng() % 10 == 0;
    const uint64_t beat1 = rng() % 4 == 0 ? 0xfffffffffffffffeull : rng();
    const uint64_t beat2 = live || rng() % 2 ? beat1 + 1 + rng() % 5 : beat1;
    const uint64_t incs[2] = {incExp, otherPage ? incExp ^ 1 : incExp};
    const uint64_t beats[2] = {beat1, beat2};
    const double openDelay = rng() % 5 == 0 ? (double)(rng() % (uint64_t)W) : (double)(rng() % 2000) / 1000.0;
    WinRead rd[2];
    bool swErr = false;     // the host polled an error completion: no post from now
    double hwErrAt = 1e18;  // the QP went to ERR (the first error completion's time)
    bool refused = false, sawRemacc = false, sawBroken = false, r2AfterRemacc = false;
    double judgeAt = -1, firstStep = -1, prevStep = -1, stepBeforeJudge = -1;
    uint32_t v = 99;
    CHECK(gdakiCtrlWindowOpen(&w, GDAKI_CTRL_WSRC_FIN, tF, countable0));
    CHECK(!gdakiCtrlWindowOpen(&w, GDAKI_CTRL_WSRC_RST, tF + 1, true));  // a new FIN while open: ignored
    ignored += w.ignored;
    const uint32_t no = w.no;
    for (double t = tF + openDelay; t <= tF + 3 * W + 5; ) {
      if (firstStep < 0) firstStep = t;
      // the poll: completions due by now, in posting order
      for (int k = 0; k < 2; k++) {
        if (!rd[k].posted || rd[k].polled || rd[k].doneAt > t) continue;
        if (k == 1 && !rd[0].polled) break;  // in order
        rd[k].polled = true;
        CHECK(gdakiCtrlWindowOnCqe(&w, no, (uint32_t)k + 1, rd[k].cls, beats[k], incs[k], t));
        if (rd[k].cls != GDAKI_CTRL_CQ_OK) swErr = true;
        if (rd[k].cls == GDAKI_CTRL_CQ_REMACC) sawRemacc = true;
        if (rd[k].cls == GDAKI_CTRL_CQ_BROKEN && !sawRemacc) sawBroken = true;
      }
      // one window action per step
      const uint32_t a = gdakiCtrlWindowStep(&w, t, W);
      if (a == GDAKI_CTRL_WA_JUDGE) {
        judgeAt = t;
        stepBeforeJudge = prevStep;
        v = gdakiCtrlWindowJudge(&w, incExp, t);
        break;
      }
      if (a == GDAKI_CTRL_WA_POST1 || a == GDAKI_CTRL_WA_POST2) {
        const int k = a == GDAKI_CTRL_WA_POST1 ? 0 : 1;
        const bool ok = !swErr;
        if (ok) {
          rd[k].posted = true;
          rd[k].postAt = t;
          if (t >= hwErrAt) {  // the QP is in ERR already (the error not polled yet): a flush
            rd[k].cls = GDAKI_CTRL_CQ_BROKEN;
            rd[k].doneAt = t + 0.001;
          } else {
            rd[k].cls = want[k];
            rd[k].doneAt = t + delay[k];
            if (k == 1 && rd[0].posted && !rd[0].polled) {
              if (rd[0].cls != GDAKI_CTRL_CQ_OK && rd[0].doneAt < 1e17) {  // READ1 errs later: READ2 is flushed after it
                rd[1].cls = GDAKI_CTRL_CQ_BROKEN;
                rd[1].doneAt = rd[0].doneAt + 0.001;
              } else if (rd[1].doneAt < rd[0].doneAt) {
                rd[1].doneAt = rd[0].doneAt;  // in order
              }
            }
            if (rd[k].cls != GDAKI_CTRL_CQ_OK && rd[k].doneAt < hwErrAt) hwErrAt = rd[k].doneAt;
          }
          if (k == 1 && rd[1].cls == GDAKI_CTRL_CQ_BROKEN && rd[0].cls != GDAKI_CTRL_CQ_OK) flushed2++;
          if (k == 1 && sawRemacc) r2AfterRemacc = true;
        } else {
          refused = true;
        }
        gdakiCtrlWindowPosted(&w, (uint32_t)k + 1, ok, t);
      }
      prevStep = t;
      t += rng() % 10 == 0 ? (double)(rng() % (uint64_t)W) + 0.02 : 0.02 + (double)(rng() % 1000) / 1000.0;
    }
    CHECK(judgeAt >= 0 && w.state == GDAKI_CTRL_WS_IDLE);
    CHECK(!r2AfterRemacc);  // READ2 is never posted once a REMACC was polled (the window is decided)
    // after the verdict: every completion still due is dropped by the window's number
    for (int k = 0; k < 2; k++)
      if (rd[k].posted && !rd[k].polled) {
        CHECK(!gdakiCtrlWindowOnCqe(&w, no, (uint32_t)k + 1, rd[k].cls, beats[k], incs[k], rd[k].doneAt));
        late++;
      }
    // the expectation, from the observed events (design 4.2's verdict order)
    const bool lateReader = countable0 && firstStep > tF + W / 2.0;
    const bool d1 = rd[0].polled && rd[0].cls == GDAKI_CTRL_CQ_OK, d2 = rd[1].polled && rd[1].cls == GDAKI_CTRL_CQ_OK;
    uint32_t wantV;
    if (!countable0 || lateReader) wantV = GDAKI_CTRL_CW_UNCONFIRMED;
    else if (sawRemacc) wantV = GDAKI_CTRL_CW_REMACC;
    else if (refused || sawBroken) wantV = GDAKI_CTRL_CW_UNCONFIRMED;
    else if (!d1 || !d2) wantV = GDAKI_CTRL_CW_NORESP;
    else if (otherPage) wantV = GDAKI_CTRL_CW_UNCONFIRMED;
    else wantV = gdakiCtrlBeatAdvanced(beat1, beat2) ? GDAKI_CTRL_CW_ALIVE : GDAKI_CTRL_CW_STALE;
    CHECK(v == wantV);
    CHECK(w.lateReader == lateReader);
    if (lateReader) {
      CHECK(judgeAt == firstStep && !rd[0].posted);
      lateReaders++;
    }
    // NORESP is always a READ out W/2 or more without its completion (never the reader's own delay)
    if (v == GDAKI_CTRL_CW_NORESP) {
      bool outLong = false;
      for (int k = 0; k < 2; k++)
        if (rd[k].posted && !rd[k].polled && judgeAt - rd[k].postAt >= W / 2.0 - 1e-9) outLong = true;
      CHECK(outLong);
    }
    if (live) {
      CHECK(v != GDAKI_CTRL_CW_NORESP && v != GDAKI_CTRL_CW_STALE && v != GDAKI_CTRL_CW_REMACC);
      if (w.stepGapMaxMs > W / 4.0) liveStalled++;
    }
    // READ1's remote access error decides the window: REMACC at the verdict (REVIEW_FIX12_P2B 막는 문제 1)
    if (countable0 && !lateReader && rd[0].posted && rd[0].cls == GDAKI_CTRL_CQ_REMACC && rd[0].polled) {
      CHECK(v == GDAKI_CTRL_CW_REMACC);
      remacc1++;
    }
    // the time: the first step at or after max(t_F + W, READ2's post + W/2) unless it cannot confirm
    const bool early = !countable0 || lateReader || refused || sawBroken;
    if (!early) {
      const double at = std::max(tF + W, rd[1].posted ? rd[1].postAt + W / 2.0 : tF + W);
      CHECK(judgeAt >= at - 1e-9 && stepBeforeJudge < at);
      if (rd[1].posted && rd[1].postAt + W / 2.0 > tF + W) read2Late++;
      atEnd++;
    } else {
      atOnce++;
    }
    // the W value into the table
    const uint32_t row = judgeRow(GDAKI_CTRL_L_NOINFO, GDAKI_CTRL_B_NONE, gdakiCtrlWofConfirm(v), GDAKI_CTRL_R_ROSE);
    static const uint32_t kRowOf[5] = {8, 4, 5, 6, 9};
    CHECK(v < 5 && row == kRowOf[v]);
    if (v < 5) byV[v]++;
    scenes++;
  }
  for (int k = 0; k < 5; k++) CHECK(byV[k] > 0);
  CHECK(lateReaders > 0 && remacc1 > 0 && flushed2 > 0 && liveStalled > 0 && read2Late > 0);
  CHECK(gdakiCtrlBeatAdvanced(0xffffffffffffffffull, 0) && !gdakiCtrlBeatAdvanced(0, 0xffffffffffffffffull));
  printf("window: %ld scenes over the QP model (alive %ld, STALE %ld, NORESP %ld, REMACC %ld, unconfirmed %ld): %ld judged "
         "at max(t_F + W, READ2 + W/2) (%ld of them after t_F + W: READ2 posted after t_F + W/2), %ld at once; READ1 REMACC decided %ld (READ2 flushed after "
         "an error %ld); late readers %ld (all unconfirmed); live peers with a step gap > W/4: %ld, none NORESP; %ld late "
         "completions dropped, %ld second FINs ignored\n",
         scenes, byV[0], byV[1], byV[2], byV[3], byV[4], atEnd, read2Late, atOnce, remacc1, flushed2, lateReaders,
         liveStalled, late, ignored);
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
      {
        const uint32_t a = gdakiCtrlWindowStep(&w, t, 20);  // one action per step (REVIEW_FIX12_P2B 막는 문제 2)
        if (a == GDAKI_CTRL_WA_JUDGE) {
          (void)gdakiCtrlWindowJudge(&w, 0, t);
        } else if (a != GDAKI_CTRL_WA_NONE) {
          const uint32_t kind = a == GDAKI_CTRL_WA_POST1 ? GDAKI_CTRL_PW_WIN1 : GDAKI_CTRL_PW_WIN2;
          const bool ok = gdakiCtrlProbeCanPost(&io, 1);
          if (ok) {
            gdakiCtrlProbeOnPosted(&io, kind, w.no, t);
            inflight.push_back({kind, w.no});
          } else {
            refused++;
          }
          gdakiCtrlWindowPosted(&w, a == GDAKI_CTRL_WA_POST1 ? 1u : 2u, ok, t);
        }
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
  // the SQ full (REVIEW_FIX12_P2B nit 6): a window cannot open countable without two slots, and a window READ refused
  // for want of a slot makes it unconfirmed (never NORESP)
  {
    struct gdakiCtrlProbeIo io;
    for (uint32_t k = 0; k < GDAKI_CTRL_PROBE_SQ; k++) gdakiCtrlProbeOnPosted(&io, GDAKI_CTRL_PW_WIN1, k, 0);
    struct gdakiCtrlWindow w;
    CHECK(gdakiCtrlWindowOpen(&w, GDAKI_CTRL_WSRC_FIN, 0, gdakiCtrlProbeCanPost(&io, 2)) && !w.countable);
    CHECK(gdakiCtrlWindowStep(&w, 0, 20) == GDAKI_CTRL_WA_JUDGE && gdakiCtrlWindowJudge(&w, 0, 0) == GDAKI_CTRL_CW_UNCONFIRMED);
    (void)gdakiCtrlProbeOnCqe(&io, GDAKI_CTRL_PW_WIN1, 0);
    (void)gdakiCtrlProbeOnCqe(&io, GDAKI_CTRL_PW_WIN1, 1);
    CHECK(gdakiCtrlWindowOpen(&w, GDAKI_CTRL_WSRC_FIN, 100, gdakiCtrlProbeCanPost(&io, 2)) && w.countable);
    CHECK(gdakiCtrlWindowStep(&w, 100, 20) == GDAKI_CTRL_WA_POST1);
    gdakiCtrlProbeOnPosted(&io, GDAKI_CTRL_PW_WIN1, w.no, 100);
    gdakiCtrlWindowPosted(&w, 1, true, 100);
    gdakiCtrlProbeOnPosted(&io, GDAKI_CTRL_PW_PERIODIC, 9, 101);  // something else took the last slot
    CHECK(gdakiCtrlWindowStep(&w, 110, 20) == GDAKI_CTRL_WA_POST2);
    gdakiCtrlWindowPosted(&w, 2, gdakiCtrlProbeCanPost(&io, 1), 110);
    CHECK(!w.countable && gdakiCtrlWindowStep(&w, 110.02, 20) == GDAKI_CTRL_WA_JUDGE &&
          gdakiCtrlWindowJudge(&w, 0, 110.02) == GDAKI_CTRL_CW_UNCONFIRMED);
  }
  printf("probe: %ld broken completion statuses never reach rows 10-12; %ld steps of random traffic with %ld windows: the "
         "SQ never above %u (%ld window READs refused for want of a slot)\n",
         broken, steps, windows, GDAKI_CTRL_PROBE_SQ, refused);
}

// ---- 6b. the handoff of the liveness READ QP (REVIEW_FIX12_P2B 막는 문제 2, 고칠 것 1, 4, 9; the fix pass's own two
// bugs without scenes: this rank's re-pairing during an open window, hasQp) ----
// One peer's probe as the host runs it, over a model of the QP: the watch thread's step (the handoff's watch part, the
// poll, the bounded drain, one window action, the periodic READ) and the helper's step (the ERR of a drain, the
// firmware of FW, the hold start's ERR), interleaved at random times. The QP model is the verbs rule of section 5 plus
// RESET/INIT/RTS; every firmware command asserts it runs on the helper, every QP access of the watch thread asserts the
// QP is not the helper's (phase FW). The helper's pairing asks PREPARE then CONNECT (incarnation `inc`) at the start, again
// after a break (the "this QP broke" word), and at random; the hold start comes at random, often right after a CONNECT
// was asked (the race of REVIEW_FIX12_P2B 고칠 것 1); some runs lose the flushes (the drain gives up: a new QP), some
// fail the QP create once (hasQp: the peer stays stepped and the next request makes the QP).
struct HRead {
  uint32_t kind, seq, gen;
  double doneAt;
  uint32_t cls;
};
struct HWorld {
  int thread = 0;  // 1 the watch thread, 2 the helper
  // the QP model
  bool exists = true, flushLost = false, createFailOnce = false;
  int hw = 0;  // 0 RESET or INIT, 1 RTS, 2 ERR
  uint32_t hwInc = 0;
  std::vector<HRead> sq;
  // the software state (struct gdakiProbeQp's) and the probe's
  bool connected = false, err = false, okInGen = false;
  uint32_t gen = 0, preparedGen = 0;
  bool haveRemote = false, toErrReq = false, holdErr = false, watchOwns = true;
  struct gdakiCtrlProbeHand hand;
  struct gdakiCtrlProbeIo io;
  struct gdakiCtrlWindow win;
  uint32_t reqOp = 0, reqGen = 0, reqInc = 0;
  bool resOk = false;
  bool errWord = false;
  // the peer and the lineage
  int peer = 0;  // from killAt: 1 its page MR gone (every READ REMACC), 2 dead (retry exceeded 3 660 ms after each READ)
  double killAt = 1e18;
  uint32_t lnInc = 0;
  bool held = false;
  double heldAt = -1;
  // counts
  long watchFw = 0, fwInFw = 0, rtsOld = 0, drainMaxMs = 0, repairJudged = 0, remaccKept = 0;
  double nextPeriodic = 0;
  bool lnCurrent(uint32_t inc) const { return !held && inc == lnInc; }
  void fwCheck() {
    if (thread != 2) watchFw++;
  }
  void touch() {  // a QP access of the watch thread
    if (hand.phase == GDAKI_CTRL_PH_FW) fwInFw++;
  }
  void hwToErr(double t) {  // modify_qp(ERR): outstanding READs are flushed
    fwCheck();
    if (!exists) return;
    hw = 2;
    for (auto& r : sq)
      if (r.doneAt > t) {
        r.cls = GDAKI_CTRL_CQ_BROKEN;
        r.doneAt = flushLost ? 1e18 : t + 0.01;
      }
  }
  void post(uint32_t kind, uint32_t seq, double t) {
    touch();
    HRead r{kind, seq, gen, 0, GDAKI_CTRL_CQ_OK};
    bool before = false;  // an earlier READ errs: this one is flushed after it
    double prev = 0;
    for (const auto& x : sq) {
      prev = std::max(prev, x.doneAt);
      if (x.cls != GDAKI_CTRL_CQ_OK) before = true;
    }
    if (hw != 1 || before) {
      r.cls = GDAKI_CTRL_CQ_BROKEN;
      r.doneAt = flushLost ? 1e18 : std::max(t, prev) + 0.01;
    } else if (peer == 1 && t >= killAt) {
      r.cls = GDAKI_CTRL_CQ_REMACC;
      r.doneAt = t + 0.01;
    } else if (peer == 2 && t >= killAt) {
      r.cls = GDAKI_CTRL_CQ_NORESP;
      r.doneAt = t + 3660.0;
    } else {
      r.doneAt = std::max(t + 0.005, prev);
    }
    sq.push_back(r);
  }
  // the watch thread's step (gdakiProbePeerStep's order)
  void watch(double t, double W, long* winVerdicts, bool* ownRepairInWin, bool* sawRemacc) {
    thread = 1;
    // the handoff, watch part (gdakiProbeHandWatch)
    if (hand.phase == GDAKI_CTRL_PH_BACK) {
      if (hand.plan != GDAKI_CTRL_PP_REUSE) gdakiCtrlProbeIoReset(&io);
      if (resOk && reqOp == GDAKI_CTRL_PO_PREPARE) preparedGen = reqGen;
      if (resOk && reqOp == GDAKI_CTRL_PO_CONNECT) {
        haveRemote = true;
        holdErr = false;
        nextPeriodic = t;
      }
      gdakiCtrlHandBack(&hand);
    }
    if (toErrReq) {
      toErrReq = false;
      haveRemote = false;
      preparedGen = 0;
      if (win.state == GDAKI_CTRL_WS_OPEN) *ownRepairInWin = true;
      gdakiCtrlWindowQpLost(&win);
      if (gdakiCtrlHandWatchOwns(&hand)) {
        connected = false;
        err = true;
        okInGen = false;
      }
    }
    if (hand.phase == GDAKI_CTRL_PH_NEW) {
      touch();
      if (gdakiCtrlHandTake(&hand, exists, connected, exists && err, preparedGen, io.outstanding)) {
        if (win.state == GDAKI_CTRL_WS_OPEN) *ownRepairInWin = true;
        gdakiCtrlWindowQpLost(&win);
        connected = false;
        err = true;
        okInGen = false;
      }
      preparedGen = 0;
    }
    watchOwns = gdakiCtrlHandWatchOwns(&hand);
    // the poll, in order
    if (watchOwns && exists && io.outstanding > 0) {
      touch();
      int n = 0;
      while (!sq.empty() && sq.front().doneAt <= t && n < 8) {
        const HRead r = sq.front();
        sq.erase(sq.begin());
        n++;
        const bool periodic = gdakiCtrlProbeOnCqe(&io, r.kind, r.seq);
        const bool thisGen = r.gen == gen && connected;
        if (r.cls != GDAKI_CTRL_CQ_OK && thisGen && !holdErr) {
          connected = false;
          err = true;
          okInGen = false;
          errWord = true;
        }
        if (r.gen != gen) continue;
        if (r.cls == GDAKI_CTRL_CQ_OK && connected) okInGen = true;
        if (r.kind != GDAKI_CTRL_PW_PERIODIC) {
          if (r.cls == GDAKI_CTRL_CQ_REMACC && win.state == GDAKI_CTRL_WS_OPEN && r.seq == win.no) *sawRemacc = true;
          (void)gdakiCtrlWindowOnCqe(&win, r.seq, r.kind == GDAKI_CTRL_PW_WIN1 ? 1u : 2u, r.cls, (uint64_t)t, 0, t);
        }
        (void)periodic;
      }
    }
    // the drain
    const double from = hand.drainFromMs;
    if (gdakiCtrlHandDrain(&hand, io.outstanding, t) == 1) {
      drainMaxMs = std::max(drainMaxMs, (long)(t - from));
      if (!hand.drainOk) gdakiCtrlProbeIoReset(&io);
    }
    watchOwns = gdakiCtrlHandWatchOwns(&hand);
    // one window action
    const uint32_t wa = gdakiCtrlWindowStep(&win, t, W);
    if (wa == GDAKI_CTRL_WA_JUDGE) {
      const uint32_t v = gdakiCtrlWindowJudge(&win, 0, t);
      winVerdicts[v < 5 ? v : 4]++;
      if (*ownRepairInWin) {  // this rank's re-pairing (or the hold start) in the open window: never NORESP
        CHECK(v == GDAKI_CTRL_CW_UNCONFIRMED || (v == GDAKI_CTRL_CW_REMACC && *sawRemacc));
        repairJudged++;
        if (v == GDAKI_CTRL_CW_REMACC) remaccKept++;
      }
      if (v == GDAKI_CTRL_CW_REMACC) CHECK(*sawRemacc);
      *ownRepairInWin = false;
      *sawRemacc = false;
    } else if (wa == GDAKI_CTRL_WA_POST1 || wa == GDAKI_CTRL_WA_POST2) {
      const uint32_t which = wa == GDAKI_CTRL_WA_POST1 ? 1u : 2u;
      const bool ok = watchOwns && exists && connected && !err && haveRemote && gdakiCtrlProbeCanPost(&io, 1);
      if (ok) {
        post(which == 1 ? GDAKI_CTRL_PW_WIN1 : GDAKI_CTRL_PW_WIN2, win.no, t);
        gdakiCtrlProbeOnPosted(&io, which == 1 ? GDAKI_CTRL_PW_WIN1 : GDAKI_CTRL_PW_WIN2, win.no, t);
      }
      gdakiCtrlWindowPosted(&win, which, ok, t);
    }
    // the periodic READ
    if (watchOwns && exists && connected && !err && haveRemote) {
      const uint32_t reserve = win.state == GDAKI_CTRL_WS_OPEN ? (uint32_t)!win.r1Posted + (uint32_t)!win.r2Posted : 0u;
      const uint32_t s = gdakiCtrlProbePeriodicDue(&io, t, nextPeriodic, reserve);
      if (s != 0) {
        nextPeriodic = t + 100;
        post(GDAKI_CTRL_PW_PERIODIC, s, t);
        gdakiCtrlProbeOnPosted(&io, GDAKI_CTRL_PW_PERIODIC, s, t);
      }
    }
    CHECK(io.outstanding <= GDAKI_CTRL_PROBE_SQ);
    thread = 0;
  }
  // the helper's part of the handoff (gdakiProbeHandHelper)
  void helper(double t) {
    thread = 2;
    if (hand.phase == GDAKI_CTRL_PH_ERR) {
      hwToErr(t);
      gdakiCtrlHandErrDone(&hand, t);
    } else if (hand.phase == GDAKI_CTRL_PH_FW) {
      const uint32_t fw = gdakiCtrlProbeFwPlan(&hand, exists, lnCurrent(reqInc));
      resOk = false;
      if (fw & (GDAKI_CTRL_FW_REFUSE_HOLD | GDAKI_CTRL_FW_REFUSE_LINEAGE)) {
        if (fw & GDAKI_CTRL_FW_NEWQP) {  // the drain gave up: a new QP (not RTS)
          fwCheck();
          sq.clear();
          hw = 0;
          exists = true;
        } else {
          hwToErr(t);
        }
        connected = false;
        err = true;
        if (fw & GDAKI_CTRL_FW_REFUSE_HOLD) hand.refusedHold++;
        else hand.refusedLineage++;
      } else {
        bool ok = true;
        if (fw & GDAKI_CTRL_FW_NEWQP) {
          fwCheck();
          sq.clear();  // destroyed: nothing of the old QP completes
          exists = !createFailOnce;
          createFailOnce = false;
          hw = 0;
          ok = exists;
        }
        if (ok && (fw & GDAKI_CTRL_FW_RESET)) {
          fwCheck();
          for (const auto& r : sq) CHECK(r.doneAt <= t);  // nothing in flight at a RESET (drained)
          sq.clear();
          hw = 0;
          connected = false;
          err = false;
          gen = reqGen;
        }
        if (ok) gen = reqGen;
        if (ok && (fw & GDAKI_CTRL_FW_CONNECT)) {
          fwCheck();
          CHECK(lnCurrent(reqInc));
          hw = 1;
          hwInc = reqInc;
          connected = true;
          okInGen = false;
        }
        resOk = ok;
      }
      gdakiCtrlHandFwDone(&hand);
    }
    if (held && exists && hw == 1 && hwInc == lnInc) rtsOld++;  // RTS toward the held incarnation (design 4.4)
    thread = 0;
  }
  void holdStart(double t) {  // gdakiProbeToErr on the helper
    thread = 2;
    held = true;
    heldAt = t;
    holdErr = true;
    toErrReq = true;
    gdakiCtrlHandCancel(&hand);
    hwToErr(t);
    thread = 0;
  }
};
static void testHandoff() {
  std::mt19937_64 rng(0x68616e646f6666ull);
  long madeAfterFail = 0;
  long runs = 0, answered = 0, okConnect = 0, refusedHold = 0, refusedLineage = 0, giveUps = 0, createFails = 0;
  long repairInWin = 0, remaccKept = 0, verdicts[5] = {}, raceRuns = 0, plans[3] = {}, maxAnswerMs = 0;
  for (int run = 0; run < 3000; run++) {
    HWorld w;
    w.peer = (int)(rng() % 3);
    w.killAt = 300 + (double)(rng() % 1500);
    w.flushLost = rng() % 8 == 0;
    w.createFailOnce = rng() % 8 == 0;
    const double W = 20 + (double)(rng() % 31);
    const bool hold = rng() % 2 == 0;
    double holdAt = hold ? 50 + (double)(rng() % 1500) : 1e18;
    const bool race = hold && rng() % 2 == 0;  // the hold start right after a CONNECT was asked
    bool raceArmed = race;
    long winV[5] = {};
    bool ownRepair = false, sawRemacc = false;
    std::vector<std::pair<uint32_t, uint32_t>> plan = {{GDAKI_CTRL_PO_PREPARE, 1}, {GDAKI_CTRL_PO_CONNECT, 1}};
    size_t nextReq = 0;
    uint32_t seq = 0, nextGen = 2, repairs = 0;
    double askedAt = -1, nextHelper = 0, nextFin = 100 + (double)(rng() % 300), nextRepair = 200 + (double)(rng() % 1500);
    bool createFailSeen = false;
    for (double t = 0; t < 2500;) {
      if (t >= nextHelper) {  // the helper's loop: its requests, their answers, the firmware, the hold start
        w.helper(t);
        if (seq != 0 && w.hand.done == seq) {
          answered++;
          maxAnswerMs = std::max(maxAnswerMs, (long)(t - askedAt));
          if (w.hand.refusedHold + w.hand.refusedLineage == 0 && !w.resOk) createFailSeen = true;
          if (w.resOk && w.reqOp == GDAKI_CTRL_PO_CONNECT) {
            okConnect++;
            if (createFailSeen) madeAfterFail++;  // hasQp: the next request made the QP
          }
          if (!w.resOk && nextReq < plan.size() && plan[nextReq - 1].first == GDAKI_CTRL_PO_PREPARE) nextReq = plan.size();
          seq = 0;
        }
        if (seq == 0 && nextReq < plan.size()) {
          const uint32_t s = gdakiCtrlHandAsk(&w.hand, plan[nextReq].first, plan[nextReq].second);
          if (s != 0) {
            seq = s;
            askedAt = t;
            w.reqOp = plan[nextReq].first;
            w.reqGen = plan[nextReq].second;
            w.reqInc = w.lnInc;  // the incarnation the PAIR carried
            if (w.reqOp == GDAKI_CTRL_PO_CONNECT && raceArmed) {
              holdAt = t + (double)(rng() % 3000) / 1000.0;  // in NEW, ERR, DRAIN or FW
              raceArmed = false;
            }
            nextReq++;
          }
        }
        if (t >= holdAt && !w.held) w.holdStart(t);
        if (seq == 0 && nextReq >= plan.size() && repairs < 4 && (w.errWord || t >= nextRepair)) {  // a re-pairing
          w.errWord = false;
          repairs++;
          nextRepair = t + 300 + (double)(rng() % 900);
          plan.push_back({GDAKI_CTRL_PO_PREPARE, nextGen});
          plan.push_back({GDAKI_CTRL_PO_CONNECT, nextGen});
          nextGen++;
        }
        nextHelper = t + 0.5 + (double)(rng() % 1500) / 1000.0;
      }
      if (t >= nextFin && w.win.state == GDAKI_CTRL_WS_IDLE) {  // a witness FIN: the window opens at this step
        const bool countable = w.watchOwns && w.exists && w.connected && !w.err && w.okInGen && w.haveRemote &&
                               gdakiCtrlProbeCanPost(&w.io, 2);
        (void)gdakiCtrlWindowOpen(&w.win, GDAKI_CTRL_WSRC_FIN, t, countable);
        nextFin = t + 50 + (double)(rng() % 400);
      }
      const uint32_t ph = w.hand.phase;
      w.watch(t, W, winV, &ownRepair, &sawRemacc);
      if (ph == GDAKI_CTRL_PH_NEW && w.hand.phase != GDAKI_CTRL_PH_NEW) plans[w.hand.plan]++;
      t += rng() % 50 == 0 ? (double)(rng() % 30) + 0.02 : 0.02 + (double)(rng() % 1000) / 1000.0;
    }
    CHECK(w.watchFw == 0 && w.fwInFw == 0);  // no firmware on the watch thread; it never touches the helper's QP
    CHECK(w.rtsOld == 0);                    // never RTS toward the held incarnation
    CHECK(w.drainMaxMs <= (long)GDAKI_CTRL_PROBE_DRAIN_MS + 31);  // the bound (plus one step, a stall at most 30 ms)
    CHECK(w.hand.phase == GDAKI_CTRL_PH_IDLE || seq != 0);
    refusedHold += (long)w.hand.refusedHold;
    refusedLineage += (long)w.hand.refusedLineage;
    giveUps += (long)w.hand.drainGiveUps;
    createFails += createFailSeen;
    if (race) raceRuns++;
    repairInWin += w.repairJudged;
    remaccKept += w.remaccKept;
    for (int k = 0; k < 5; k++) verdicts[k] += winV[k];
    runs++;
  }
  CHECK(refusedHold > 0 && refusedLineage > 0 && giveUps > 0 && createFails > 0 && repairInWin > 0 && okConnect > 0);
  CHECK(remaccKept > 0 && verdicts[GDAKI_CTRL_CW_REMACC] > 0 && madeAfterFail > 0);
  CHECK(plans[GDAKI_CTRL_PP_REUSE] > 0 && plans[GDAKI_CTRL_PP_RESET] > 0 && plans[GDAKI_CTRL_PP_DRAIN] > 0);
  CHECK(maxAnswerMs <= (long)GDAKI_CTRL_PROBE_DRAIN_MS + 100);
  printf("handoff: %ld runs (%ld with the hold start right after a CONNECT ask): %ld answers (%ld CONNECTs ok; plans reuse "
         "%ld, reset %ld, drain %ld; the slowest %ld ms), refused: hold started %ld, not the current incarnation %ld; "
         "drains given up %ld (a new QP), QP create failures answered %ld (the peer stays stepped: hasQp; a later CONNECT "
         "made it in %ld); 0 firmware commands on the watch thread, 0 QP accesses of it in FW, 0 RTS toward a held incarnation; "
         "%ld windows judged after this rank's own re-pairing or hold start (none NORESP; %ld kept REMACC: READ1's remote "
         "access error broke the QP, the re-pairing followed); all windows: alive %ld, STALE %ld, NORESP %ld, REMACC %ld, "
         "unconfirmed %ld\n",
         runs, raceRuns, answered, okConnect, plans[0], plans[1], plans[2], maxAnswerMs, refusedHold, refusedLineage,
         giveUps, createFails, madeAfterFail, repairInWin, remaccKept, verdicts[0], verdicts[1], verdicts[2], verdicts[3], verdicts[4]);
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
  g.vetoClear = false;  // the GPU still sends: no veto on the helper side (R (9))
  CHECK(gdakiCtrlRDerive(g) == GDAKI_CTRL_R_HELPER_STALL);
  g.vetoClear = true;
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
  int unseen = 0;                  // rank 2 never read rank 3: 1 its page word says "never seen", 2 it says 0 (the old
                                   // word; REVIEW_FIX12_P2B 고칠 것 2)
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
          pub[(size_t)r][(size_t)q] = gdakiCtrlStaleOfWord(gdakiCtrlStaleWord(true, s));
          if (unseen != 0 && r == 2 && q == subject)
            pub[(size_t)r][(size_t)q] = unseen == 1 ? gdakiCtrlStaleOfWord(gdakiCtrlStaleWord(false, s)) : 0.0;
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
  // a survivor that never saw the peer is not a view of it: judged on the other one's view; the old word 0 blocked it
  GuardWorld e;
  e.stopAt = 1000;
  e.unseen = 1;
  const double tE = e.judge(4);
  CHECK(tE >= 0 && tE - e.stopAt >= 10000 && tE - e.stopAt <= 10300);
  GuardWorld e0 = e;
  e0.unseen = 2;
  CHECK(e0.judge(4) < 0);
  CHECK(gdakiCtrlStaleWord(false, 5) == GDAKI_CTRL_STALE_UNSEEN && gdakiCtrlStaleOfWord(GDAKI_CTRL_STALE_UNSEEN) < 0);
  CHECK(gdakiCtrlStaleWord(true, 0) == 0 && gdakiCtrlStaleOfWord(gdakiCtrlStaleWord(true, 9800.4)) == 9800.0);
  const double unseenBoth[2] = {-1.0, -1.0}, unseenOne[2] = {-1.0, 12000};
  const bool bothValid2[2] = {true, true};
  CHECK(gdakiCtrlPartitionGuard(unseenBoth, bothValid2, 2, 10000, 100) == GDAKI_CTRL_PG_SELF);
  CHECK(gdakiCtrlPartitionGuard(unseenOne, bothValid2, 2, 10000, 100) == GDAKI_CTRL_PG_PASS);
  // the guard's three answers directly
  const double fresh[2] = {200, 12000}, stale[2] = {11000, 12000};
  const bool bothValid[2] = {true, true}, none[2] = {false, false};
  CHECK(gdakiCtrlPartitionGuard(stale, bothValid, 2, 10000, 100) == GDAKI_CTRL_PG_PASS);
  CHECK(gdakiCtrlPartitionGuard(fresh, bothValid, 2, 10000, 100) == GDAKI_CTRL_PG_FRESH);
  CHECK(gdakiCtrlPartitionGuard(stale, none, 2, 10000, 100) == GDAKI_CTRL_PG_SELF);
  CHECK(gdakiCtrlPartitionGuard(nullptr, nullptr, 0, 10000, 100) == GDAKI_CTRL_PG_PASS);
  printf("guard: four ranks, one stalled: judged %.0f ms after the stall; the reader alone sees everyone stale: not "
         "judged; another survivor sees it fresh: not judged; two ranks: judged %.0f ms after; a survivor that never saw "
         "it: judged %.0f ms after on the other view (the old word 0: never)\n", tA - a.stopAt, tD - d.stopAt, tE - e.stopAt);
}

// ---- 8b. the cell gc4_helper_freeze12000 (EXPERIMENT.md 9.3 row 15, prediction helper_stall_fence; REVIEW_FIX12_P2B
// 막는 문제 3) ----
// Four ranks read each other's pages every 100 ms. Rank 3's helperBeat stops for 12 000 ms from t = 1000 while its
// watchBeat rises and its GPU keeps sending (the data path's veto never clears: the helper's QP watch samples every
// 10 ms). Every reader publishes staleMs[q] as the host does (the larger of the two beats' stalls); rank 0 judges rank 3
// with gdakiCtrlRDerive. `vetoOnHelper` puts the veto back on the helper side (the code before this fix) for contrast.
static double helperFreezeScene(bool vetoOnHelper, uint32_t* lastRow) {
  const int n = 4, subject = 3;
  const double probe = 100, suspect = 2000, stall = 10000, from = 1000, len = 12000;
  std::vector<std::vector<gdakiCtrlStale>> ws((size_t)n, std::vector<gdakiCtrlStale>((size_t)n)), hs = ws;
  std::vector<std::vector<double>> pub((size_t)n, std::vector<double>((size_t)n, 0.0)), seen = pub;
  std::vector<double> lastOk((size_t)n, -1e18);
  bool rose03 = false;
  *lastRow = 0;
  for (double t = 0; t <= 30000; t += probe) {
    for (int r = 0; r < n; r++)
      for (int q = 0; q < n; q++) {
        if (q == r) continue;
        const uint64_t watchBeat = (uint64_t)t + 1;
        const bool frozen = q == subject && t >= from && t < from + len;
        const uint64_t helperBeat = (uint64_t)((frozen ? from : t) * 1000.0) + 1;
        bool rose = false;
        gdakiCtrlStaleOnRead(&ws[(size_t)r][(size_t)q], watchBeat, t, probe, &rose);
        gdakiCtrlStaleOnRead(&hs[(size_t)r][(size_t)q], helperBeat, t, probe);
        pub[(size_t)r][(size_t)q] = std::max(t - ws[(size_t)r][(size_t)q].firstMs, t - hs[(size_t)r][(size_t)q].firstMs);
        if (r == 0) {
          lastOk[(size_t)q] = t;
          seen[(size_t)q] = pub[(size_t)q];
          if (q == subject) rose03 = rose;
        }
      }
    double others[2];
    bool valid[2];
    int no = 0;
    for (int k = 1; k < n; k++) {
      if (k == subject) continue;
      others[no] = seen[(size_t)k][(size_t)subject];
      valid[no] = t - lastOk[(size_t)k] <= 3 * probe && pub[0][(size_t)k] < suspect;
      no++;
    }
    struct gdakiCtrlRFacts f;
    f.okInGen = true;
    f.watchRose = rose03;
    f.watchStaleMs = ws[0][(size_t)subject].lastMs - ws[0][(size_t)subject].firstMs;
    f.helperStaleMs = hs[0][(size_t)subject].lastMs - hs[0][(size_t)subject].firstMs;
    f.guardOk = gdakiCtrlPartitionGuard(others, valid, no, stall, probe) == GDAKI_CTRL_PG_PASS;
    f.vetoClear = false;  // the GPU sends all along
    uint32_t R = gdakiCtrlRDerive(f);
    if (vetoOnHelper && R == GDAKI_CTRL_R_HELPER_STALL) R = GDAKI_CTRL_R_HELPER_GUARDED;
    const struct gdakiCtrlJudgement j = gdakiCtrlJudge(GDAKI_CTRL_L_NORESP, GDAKI_CTRL_B_NONE, GDAKI_CTRL_W_OK, R);
    if (j.row != 20) *lastRow = j.row;
    if (j.row == 15) {
      CHECK(j.verdict == GDAKI_CTRL_V_STALL_HELPER && std::string(gdakiCtrlCauseName(j.cause)) == "STALL_HELPER");
      return t - from;
    }
    CHECK(j.row == 20 || j.row == 18);  // alive, or suspected (never another row in this cell)
  }
  return -1;
}
static void testHelperFreeze() {
  uint32_t row = 0, rowOld = 0;
  const double t = helperFreezeScene(false, &row);
  CHECK(t >= 10000 && t <= 10300 && row == 15);
  const double tOld = helperFreezeScene(true, &rowOld);
  CHECK(tOld < 0 && rowOld == 18);  // the veto on the helper side: the cell stayed suspected (the blocking finding)
  printf("helper freeze (gc4_helper_freeze12000): helperBeat stopped 12000 ms, watchBeat and the GPU going: row 15 "
         "(STALL_HELPER) %.0f ms after the freeze; with the veto on the helper side: never (row %u)\n", t, rowOld);
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
  testHandoff();
  testRLW();
  testGuard();
  testHelperFreeze();
  testFence();
  testFenceScenes();
  testMailFreeze();
#endif
  printf("gc_unit_p1 (%s): %ld checks, %ld failed\n", NCCL_GIN_CTRL_TCP ? "tcp" : "rdma", gChecks, gFailed);
  return gFailed == 0 ? 0 : 1;
}
