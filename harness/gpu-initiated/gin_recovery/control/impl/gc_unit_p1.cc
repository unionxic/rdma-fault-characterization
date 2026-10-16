// gc_unit_p1.cc - CPU unit test of gin-control phase 1 (EXPERIMENT.md 9.8 "CPU 단위 모형", the status page and the fence
// models). No NCCL, no CUDA, no verbs, no network. Compiled in a build_gc.sh `unit` style: g++ -std=c++17 with ASan and
// UBSan, with gin-mirror's and gin-restore's headers and the working tree's cut pure regions:
//   - gc_page_pure.inc: the region "gin-control (page): pure functions" of the host file (the judgement table, the fence
//     report names, the activation gate, the stall definition and the confirmation window's width);
//   - rs_ctrl_api.h: the status page words, the seqlock report line, the confirm-window verdict, the fence word.
// What it checks (the models EXPERIMENT.md 9.8 lists for the status page and the fence):
//   1. the judgement words model: only aligned 8 B reads give one moment's value (the head's offsets and stores);
//   2. the report-line seqlock model: a writer thread and randomly interleaved readers, 0 torn even-ver lines;
//   3. the stall definition model, including a stalled reader (the origin reset) and the partition guard;
//   4. the judgement pure function over the whole 1 170-point input grid: the count, every combination matches exactly
//      one row (an independent reference), row 21 is unreached, every row 1..20 is reached, and the floor property;
//      plus the expected row of each cell's scenario (kill, RST, FIN-less read fail, stall, live RST, the decision-wait
//      defaults);
//   5. the confirmation-window timing model: the verdict is always decided at t_F + W, and the "cannot confirm" rule;
//   6. the fence word and gdakiLnFenceOf over a lineage oracle: the only difference from the no-fence gate is the gate
//      cell (HOLD_WAIT), and the design 4.4 scenes.
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <random>
#include <set>
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
// the activation gate's /proc verdict values (host file next to gdakiRsActExamine, 4554)
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
#include "gc_page_pure.inc"  // the host file's "gin-control (page): pure functions" region

static long gChecks = 0, gFailed = 0;
#define CHECK(c)                                                                      \
  do {                                                                                \
    gChecks++;                                                                        \
    if (!(c)) {                                                                       \
      gFailed++;                                                                      \
      if (gFailed <= 60) fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); \
    }                                                                                 \
  } while (0)

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
  CHECK(gdakiCtrlRofStale(true, 50000, suspect, stall, true, true, false) == GDAKI_CTRL_R_RISING);
  CHECK(gdakiCtrlRofStale(false, 500, suspect, stall, true, true, false) == GDAKI_CTRL_R_STALE_BELOW);
  CHECK(gdakiCtrlRofStale(false, 5000, suspect, stall, true, true, false) == GDAKI_CTRL_R_STALE_SUSPECT);
  CHECK(gdakiCtrlRofStale(false, 11000, suspect, stall, false, true, false) == GDAKI_CTRL_R_STALE_GUARD);
  CHECK(gdakiCtrlRofStale(false, 11000, suspect, stall, true, false, false) == GDAKI_CTRL_R_STALE_GUARD);
  CHECK(gdakiCtrlRofStale(false, 11000, suspect, stall, true, true, false) == GDAKI_CTRL_R_STALL);
  CHECK(gdakiCtrlRofStale(false, 500, suspect, stall, true, true, true) == GDAKI_CTRL_R_RISING);  // helper < SUSPECT is (1)
  CHECK(gdakiCtrlRofStale(false, 5000, suspect, stall, true, true, true) == GDAKI_CTRL_R_HELPER_SUSPECT);
  CHECK(gdakiCtrlRofStale(false, 11000, suspect, stall, true, true, true) == GDAKI_CTRL_R_HELPER_STALL);
  // W's width (결정 대기 5: factor 10, clamped 20..50)
  CHECK(gdakiCtrlConfirmW(10, 1.0) == 20);   // 10 ms -> clamp up to 20
  CHECK(gdakiCtrlConfirmW(10, 3.0) == 30);   // 30 ms
  CHECK(gdakiCtrlConfirmW(10, 8.0) == 50);   // 80 ms -> clamp down to 50
  CHECK(gdakiCtrlConfirmW(5, 3.0) == 20);    // the 5x option would give 15 -> clamp to 20
  printf("stall: ok\n");
}

// ---- 4. the judgement table over the whole input grid ----
// An independent reference matcher, written plainly from EXPERIMENT.md 9.3's 21 rows (not calling gdakiCtrlJudgeRow).
static uint32_t refRow(uint32_t L, uint32_t B, uint32_t W, uint32_t R) {
  const bool left = (L == GDAKI_CTRL_L_LEFT);
  const bool bye = (B == GDAKI_CTRL_B_BYE);
  const bool ended = (L == GDAKI_CTRL_L_ENDED);
  const bool hwNoResp = (R == GDAKI_CTRL_R_HWNORESP);
  if (left) return 1;
  if (bye) return 2;
  if (ended) return 3;
  if (W == GDAKI_CTRL_W_CW_STALE) return 4;
  if (W == GDAKI_CTRL_W_CW_NORESP) return 5;
  if (W == GDAKI_CTRL_W_CW_REMACC) return 6;
  if (W == GDAKI_CTRL_W_WINDOW) return 7;
  if (W == GDAKI_CTRL_W_CW_ALIVE) return 8;
  if (W == GDAKI_CTRL_W_CW_UNCONFIRMED) return 9;
  if (L == GDAKI_CTRL_L_NORESP && hwNoResp) return 10;
  if (L == GDAKI_CTRL_L_NOINFO && W == GDAKI_CTRL_W_OFF && hwNoResp) return 11;
  if (hwNoResp) return 12;
  if (R == GDAKI_CTRL_R_CANNOT_CONFIRM) return 13;
  if (R == GDAKI_CTRL_R_STALL) return 14;
  if (R == GDAKI_CTRL_R_HELPER_STALL) return 15;
  if (R == GDAKI_CTRL_R_REMACC) return 16;
  if (R == GDAKI_CTRL_R_TIMEOUT) return 17;
  if (R == GDAKI_CTRL_R_STALE_SUSPECT || R == GDAKI_CTRL_R_STALE_GUARD || R == GDAKI_CTRL_R_HELPER_SUSPECT ||
      R == GDAKI_CTRL_R_HELPER_GUARD)
    return 18;
  if (R == GDAKI_CTRL_R_HELPER_BUSY) return 19;
  if (R == GDAKI_CTRL_R_RISING || R == GDAKI_CTRL_R_STALE_BELOW) return 20;
  return 21;
}
static void testJudge() {
  long points = 0, reach[22] = {};
  for (uint32_t L = 0; L < GDAKI_CTRL_L_MAX; L++)
    for (uint32_t B = 0; B < GDAKI_CTRL_B_MAX; B++)
      for (uint32_t W = 0; W < GDAKI_CTRL_W_MAX; W++)
        for (uint32_t R = 0; R < GDAKI_CTRL_R_MAX; R++) {
          const uint32_t row = gdakiCtrlJudgeRow(L, B, W, R);
          CHECK(row >= 1 && row <= 21);
          CHECK(row == refRow(L, B, W, R));  // exactly one row (the reference and the code agree)
          reach[row]++;
          points++;
          // the floor property: a row that holds or refuses rests on ended / a confirmed window / no response / a stall
          const uint32_t v = gdakiCtrlRowVerdict(row);
          if (v == GDAKI_CTRL_V_ENDED || v == GDAKI_CTRL_V_REFUSE || v == GDAKI_CTRL_V_STALL) {
            const bool floor =
                (L == GDAKI_CTRL_L_ENDED) || (W == GDAKI_CTRL_W_CW_STALE) || (W == GDAKI_CTRL_W_CW_NORESP) ||
                (W == GDAKI_CTRL_W_CW_REMACC) || (R == GDAKI_CTRL_R_HWNORESP) || (R == GDAKI_CTRL_R_STALL) ||
                (R == GDAKI_CTRL_R_HELPER_STALL);
            CHECK(floor);
          }
          // a lone timeout or remote-access error never holds or refuses
          if ((R == GDAKI_CTRL_R_TIMEOUT || R == GDAKI_CTRL_R_REMACC) && row >= 12)
            CHECK(gdakiCtrlRowVerdict(row) == GDAKI_CTRL_V_NONE);
        }
  CHECK(points == 1170);
  CHECK(reach[21] == 0);  // no input reaches the catch-all row
  for (int r = 1; r <= 20; r++) CHECK(reach[r] >= 1);
  // the cells' scenarios (EXPERIMENT.md 9.3, 3절)
  CHECK(gdakiCtrlJudgeRow(GDAKI_CTRL_L_NOINFO, GDAKI_CTRL_B_NONE, GDAKI_CTRL_W_CW_NORESP, GDAKI_CTRL_R_RISING) == 5);  // kill FIN+NORESP
  CHECK(gdakiCtrlJudgeRow(GDAKI_CTRL_L_NOINFO, GDAKI_CTRL_B_NONE, GDAKI_CTRL_W_CW_STALE, GDAKI_CTRL_R_RISING) == 4);   // FIN+STALE
  CHECK(gdakiCtrlJudgeRow(GDAKI_CTRL_L_NOINFO, GDAKI_CTRL_B_NONE, GDAKI_CTRL_W_CW_REMACC, GDAKI_CTRL_R_RISING) == 6);  // REMACC+FIN
  CHECK(gdakiCtrlJudgeRow(GDAKI_CTRL_L_ENDED, GDAKI_CTRL_B_NONE, GDAKI_CTRL_W_NORMAL, GDAKI_CTRL_R_RISING) == 3);      // launcher EXITED, kill witness-off
  CHECK(gdakiCtrlJudgeRow(GDAKI_CTRL_L_NOINFO, GDAKI_CTRL_B_NONE, GDAKI_CTRL_W_OFF, GDAKI_CTRL_R_HWNORESP) == 11);     // FIN-less read fail (NORESP)
  CHECK(gdakiCtrlJudgeRow(GDAKI_CTRL_L_NORESP, GDAKI_CTRL_B_NONE, GDAKI_CTRL_W_UNKNOWN, GDAKI_CTRL_R_HWNORESP) == 10); // LINKDOWN
  CHECK(gdakiCtrlJudgeRow(GDAKI_CTRL_L_NORESP, GDAKI_CTRL_B_NONE, GDAKI_CTRL_W_NORMAL, GDAKI_CTRL_R_STALL) == 14);     // stop12000 STALL
  CHECK(gdakiCtrlJudgeRow(GDAKI_CTRL_L_NORESP, GDAKI_CTRL_B_NONE, GDAKI_CTRL_W_NORMAL, GDAKI_CTRL_R_HELPER_STALL) == 15); // helper_freeze STALL_HELPER
  CHECK(gdakiCtrlJudgeRow(GDAKI_CTRL_L_ALIVE, GDAKI_CTRL_B_NONE, GDAKI_CTRL_W_CW_ALIVE, GDAKI_CTRL_R_RISING) == 8);    // live RST: the window ends alive
  CHECK(gdakiCtrlJudgeRow(GDAKI_CTRL_L_ALIVE, GDAKI_CTRL_B_BYE, GDAKI_CTRL_W_CW_STALE, GDAKI_CTRL_R_RISING) == 2);     // BYE wins over a stale window
  CHECK(gdakiCtrlJudgeRow(GDAKI_CTRL_L_LEFT, GDAKI_CTRL_B_NONE, GDAKI_CTRL_W_CW_STALE, GDAKI_CTRL_R_STALL) == 1);      // LEFT wins over all
  // 결정 대기 7: EXITED wins over a rising beat
  CHECK(gdakiCtrlJudgeRow(GDAKI_CTRL_L_ENDED, GDAKI_CTRL_B_NONE, GDAKI_CTRL_W_NORMAL, GDAKI_CTRL_R_RISING) == 3);
  // the strong-evidence cause names (design 4.5): seven of them
  std::set<std::string> holdCauses;
  for (int r = 1; r <= 21; r++) {
    const uint32_t v = gdakiCtrlRowVerdict(r);
    if (v == GDAKI_CTRL_V_ENDED || v == GDAKI_CTRL_V_STALL) holdCauses.insert(gdakiCtrlCauseName(r));
  }
  CHECK(holdCauses == std::set<std::string>({"EXITED", "FIN+STALE", "FIN+NORESP", "REMACC+FIN", "NORESP", "STALL", "STALL_HELPER"}));
  printf("judge: %ld points, row21 %ld, rows reached 1..20 all >=1\n", points, reach[21]);
}

// ---- 5. the confirmation-window timing model (design 4.2): the verdict is always decided at t_F + W ----
// Phase 1 uses gdakiCtrlConfirmP1 (REVIEW_PREP note 4: the incNonce check and a wrapping beat compare); the header's
// gdakiCtrlConfirmVerdict lacks both and is a header-change request. READ1 is posted at t_F, READ2 at t_F + W/2, and the
// verdict is decided at t_F + W whatever the completion times.
static void testConfirm() {
  std::mt19937_64 rng(0x636f6e6669726dull);
  for (int i = 0; i < 40000; i++) {
    const double tF = (double)(rng() % 1000);
    const int W = 20 + (int)(rng() % 31);
    const bool countable = rng() % 5 != 0;       // the QP RTS and a success in its generation
    const bool incOk = rng() % 4 != 0;           // the peer's incNonce is unchanged across the window
    const bool remacc = rng() % 7 == 0;
    const double r1 = tF + (double)(rng() % (W + 40));                   // READ1 completion time
    const double r2 = tF + (double)W / 2 + (double)(rng() % (W + 40));   // READ2 completion time
    const uint64_t beat1 = rng(), beat2 = (rng() % 2) ? beat1 + (1 + rng() % 5) : beat1;  // some advance, some do not
    const double judgeMs = tF + W;               // the model: the verdict is decided here, always
    const bool r1Done = r1 <= judgeMs, r2Done = r2 <= judgeMs;
    const uint32_t v = gdakiCtrlConfirmP1(countable, incOk, remacc, r1Done, r2Done, beat1, beat2);
    // an independent expectation (the design 4.2 order: REMACC, NORESP, incNonce, then the wrapping beat compare)
    uint32_t want;
    if (!countable) want = GDAKI_CTRL_CW_UNCONFIRMED;
    else if (remacc) want = GDAKI_CTRL_CW_REMACC;
    else if (!r1Done || !r2Done) want = GDAKI_CTRL_CW_NORESP;
    else if (!incOk) want = GDAKI_CTRL_CW_UNCONFIRMED;
    else want = ((int64_t)(beat2 - beat1) > 0) ? GDAKI_CTRL_CW_ALIVE : GDAKI_CTRL_CW_STALE;
    CHECK(v == want);
    // the W mapping into the judgement table
    const uint32_t Wv = gdakiCtrlWofConfirm(v);
    const uint32_t row = gdakiCtrlJudgeRow(GDAKI_CTRL_L_NOINFO, GDAKI_CTRL_B_NONE, Wv, GDAKI_CTRL_R_RISING);
    if (v == GDAKI_CTRL_CW_ALIVE) CHECK(row == 8);
    else if (v == GDAKI_CTRL_CW_STALE) CHECK(row == 4);
    else if (v == GDAKI_CTRL_CW_NORESP) CHECK(row == 5);
    else if (v == GDAKI_CTRL_CW_REMACC) CHECK(row == 6);
    else CHECK(row == 9);  // UNCONFIRMED
  }
  // "cannot confirm": the QP is not RTS or had no success in its generation -> countable false
  CHECK(gdakiCtrlConfirmP1(false, true, false, true, true, 1, 2) == GDAKI_CTRL_CW_UNCONFIRMED);
  // a changed incNonce across the window (another process at the peer's page slot): cannot confirm, not STALE
  CHECK(gdakiCtrlConfirmP1(true, false, false, true, true, 5, 5) == GDAKI_CTRL_CW_UNCONFIRMED);
  // the wrapping beat compare: a near-wrap beat still counts as advanced
  CHECK(gdakiCtrlBeatAdvanced(0xffffffffffffffffull, 0) && !gdakiCtrlBeatAdvanced(0, 0xffffffffffffffffull));
  printf("confirm: ok (verdict at t_F + W, incNonce and wrapping beat)\n");
}

// ---- 6. the fence word and gdakiLnFenceOf over a lineage oracle (design 4.4): the difference is the gate cell only ----
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
              const uint32_t fn = gdakiLnFenceOf(v, word, fs != 0);
              uint32_t wantFn = GDAKI_CTRL_FN_NONE;
              if (v.phase == GDAKI_LN_HOLD_WAIT) wantFn = fenced ? GDAKI_CTRL_FN_FENCED : (fs ? GDAKI_CTRL_FN_FENCING : GDAKI_CTRL_FN_NONE);
              CHECK(fn == wantFn);
              if (fn != GDAKI_CTRL_FN_NONE) nameDiff++;
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

int main() {
  testWords();
  testSeqlock();
  testStall();
  testJudge();
  testConfirm();
  testFence();
  printf("gc_unit_p1: %ld checks, %ld failed\n", gChecks, gFailed);
  return gFailed == 0 ? 0 : 1;
}
