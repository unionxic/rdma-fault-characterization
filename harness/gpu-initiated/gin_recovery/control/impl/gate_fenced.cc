// gate_fenced.cc - CPU program for the gin-control phase-1 prediction `gate_fenced` (EXPERIMENT.md 3절, 9.4). No NCCL,
// no CUDA, no verbs, no cluster. Compiled in a build_gc.sh `unit` style (g++ ASan/UBSan).
//
// The old activation gate (gin-restore's gdakiRsActExamine over /proc) treats the original process as gone the moment
// its /proc state is a zombie (Z = GO) -- which happens when the MAIN thread ends, even while another thread of the
// group still runs. The new FENCED gate (gdakiCtrlActGate in a launcher-paired context) is GO only once the launcher's
// pidfd becomes readable, which is when the LAST thread of the group ends. The launcher unit measured that gap at
// +301.1-301.5 ms for a 300 ms second thread (EXPERIMENT.md 9.5); the prediction's program here uses a 500 ms second
// thread and asserts the two gates differ by about that length (10/10).
//
// This models the two observation streams (what /proc shows, and when the pidfd is readable) over a timeline; it does
// not fork or touch verbs (the live pidfd facts are the launcher unit's). It exercises the real gate functions:
// gdakiRsActExamine (cut region rs_spare_pure.inc) and gdakiCtrlActGate (cut region gc_page_pure.inc).
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <random>

typedef enum { ncclSuccess = 0, ncclSystemError = 2, ncclInternalError = 3, ncclInvalidUsage = 5 } ncclResult_t;
typedef struct {
  unsigned int magic, nqp, qpn[64], remoteQpn[64], sqPsn[64];
  unsigned long long epochWqes[64];
} ncclGinRecoverToken_t;
#define NCCL_GIN_RECOVERY_MAX_QPS 64
enum { GDAKI_POLICY_FAILFAST = 0, GDAKI_POLICY_HOLD = 1 };
// GDAKI_RS_ACT_GO/WAIT and gdakiRsActProbe/gdakiRsActExamine come from the cut spare region (self-contained; it also
// defines GDAKI_RS_ACT_ACTIVATE.. and gdakiRsEndpoint, so rs_spare_api.h must NOT be included here).
#define GDAKI_HOLD_API_NO_ENTRY_DECLS
#include "rs_hold_api.h"
#include "rs_store_api.h"
#include "rs_ctrl_api.h"
#include "rs_lineage_api.h"
#include "rs_spare_pure.inc"  // gdakiRsActProbe, gdakiRsActExamine, gdakiRsActAnswerOf, GDAKI_RS_ACT_* (host region)
#include "gc_page_pure.inc"   // gdakiCtrlActGate (host region)

static long gChecks = 0, gFailed = 0;
#define CHECK(c)                                                                      \
  do {                                                                                \
    gChecks++;                                                                        \
    if (!(c)) {                                                                       \
      gFailed++;                                                                       \
      fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #c);                    \
    }                                                                                 \
  } while (0)

// /proc of the original (pid, start time `st0`) at monotonic time `tMs` after the main thread ended at 0, with the last
// thread ending at `lastMs`: a zombie (Z) from the moment the main thread ends until the group ends, then gone.
static struct gdakiRsActProbe procAt(unsigned long long st0, double tMs, double lastMs) {
  struct gdakiRsActProbe p;
  if (tMs >= lastMs) {
    p.exists = false;  // the whole group ended; /proc/<pid> is gone (not yet reaped, then reaped: absent either way here)
    p.state = '?';
    p.start = 0;
  } else {
    p.exists = true;
    p.state = 'Z';  // the main thread ended: the launcher unit saw /proc Z while another thread lived (EXPERIMENT.md 9.5)
    p.start = st0;
  }
  return p;
}

int main() {
  std::mt19937_64 rng(0x67617465665f31ull);  // "gatef_1"
  const long long pid = 4242;
  const unsigned long long st0 = 987654321ull;
  int trials = 0, diffOk = 0;
  for (int t = 0; t < 10; t++) {
    const double lastMs = 500.0 + (double)((int)(rng() % 7) - 3);  // the second thread lives about 500 ms (+/- jitter)
    double oldGoMs = -1, newGoMs = -1;
    for (double tMs = 0; tMs <= 1000.0; tMs += 1.0) {
      char why[192];
      const struct gdakiRsActProbe pr = procAt(st0, tMs, lastMs);
      const int procVerdict = gdakiRsActExamine(pid, st0, pr, why, sizeof(why));  // the old gate's verdict
      // the pidfd is readable only once the last thread ends (the launcher unit's fact); the fence word is set then
      const bool pidfdReadable = tMs >= lastMs;
      const int oldGate = procVerdict;                                     // old: /proc Z = GO
      const int newGate = gdakiCtrlActGate(true, pidfdReadable, procVerdict);  // new: FENCED (launcher-paired)
      if (oldGate == GDAKI_RS_ACT_GO && oldGoMs < 0) oldGoMs = tMs;
      if (newGate == GDAKI_RS_ACT_GO && newGoMs < 0) newGoMs = tMs;
    }
    // the old gate GOes at the main thread's end (0); the new gate only at the last thread's end (~500)
    CHECK(oldGoMs == 0.0);
    CHECK(newGoMs >= lastMs && newGoMs <= lastMs + 1.0);
    const double diff = newGoMs - oldGoMs;
    if (diff >= 490.0 && diff <= 510.0) diffOk++;
    trials++;
    printf("gate_fenced trial %d: old GO at %.0f ms, FENCED GO at %.0f ms (diff %.0f ms, second thread %.0f ms)\n", t,
           oldGoMs, newGoMs, diff, lastMs);
  }
  // the pure gate in both contexts: launcher-paired requires fenced; no launcher is the /proc verdict
  CHECK(gdakiCtrlActGate(true, false, GDAKI_RS_ACT_GO) == GDAKI_RS_ACT_WAIT);  // Z = GO old, but not fenced -> WAIT
  CHECK(gdakiCtrlActGate(true, true, GDAKI_RS_ACT_GO) == GDAKI_RS_ACT_GO);
  CHECK(gdakiCtrlActGate(false, false, GDAKI_RS_ACT_GO) == GDAKI_RS_ACT_GO);   // phase 1: no launcher, /proc stands
  CHECK(diffOk == trials);
  printf("gate_fenced: %d/%d trials show the FENCED gate waits about 500 ms longer than Z=GO; %ld checks, %ld failed\n",
         diffOk, trials, gChecks, gFailed);
  return gFailed == 0 ? 0 : 1;
}
