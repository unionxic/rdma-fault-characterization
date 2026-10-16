// gate_fenced.cc - the program of the gin-control phase-1 prediction `gate_fenced` (EXPERIMENT.md 3절, 7절, 9.4). No
// NCCL, no CUDA, no verbs, no cluster. Compiled in a build_gc.sh `unit` style (g++ ASan/UBSan), run on the CPU.
//
// The old activation gate (gin-restore's gdakiRsActExamine over /proc) treats the original process as gone the moment
// its /proc state is a zombie (Z = GO), which happens when the MAIN thread ends while another thread of the group still
// runs. The FENCED gate (gdakiCtrlActGate in a launcher-paired context) goes only once the process's pidfd is readable,
// when the LAST thread of the group has ended (what the launcher waits for before FENCED). REVIEW_P12 고칠 것 7: this is a
// real program, not a timeline model. Per trial it forks a child whose main thread ends (pthread_exit) while a second
// thread lives on 500 ms and then ends the group; the parent watches both streams every 1 ms on its own clock: /proc of
// the child (state and start time, field 22) through gdakiRsActExamine (the old gate), and poll() on a pidfd of the child
// through gdakiCtrlActGate (the new gate). The child writes its own CLOCK_MONOTONIC times of the two ends into a pipe,
// so each gate's GO time is compared with an independent clock of the event it should see. It fails when the gates do
// not differ by the second thread's life (450-700 ms), or when a gate's GO is not within 30 ms of its event.
// It exercises the real gate functions: gdakiRsActExamine (cut region rs_spare_pure.inc) and gdakiCtrlActGate (cut
// region gc_page_pure.inc).
#include <cerrno>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>

#include <fcntl.h>
#include <poll.h>
#include <pthread.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

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

#ifndef SYS_pidfd_open
#define SYS_pidfd_open 434
#endif

static long gChecks = 0, gFailed = 0;
#define CHECK(c)                                                                      \
  do {                                                                                \
    gChecks++;                                                                        \
    if (!(c)) {                                                                       \
      gFailed++;                                                                      \
      fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #c);                    \
    }                                                                                 \
  } while (0)

static double monoMs() {
  struct timespec t;
  clock_gettime(CLOCK_MONOTONIC, &t);
  return t.tv_sec * 1e3 + t.tv_nsec * 1e-6;
}
// /proc/<pid>/stat: the state (field 3) and the start time (field 22), read after the last ')' (the name may hold any
// byte). exists false: no /proc entry.
static struct gdakiRsActProbe procOf(pid_t pid) {
  struct gdakiRsActProbe p;
  char path[64], buf[1024];
  snprintf(path, sizeof(path), "/proc/%d/stat", (int)pid);
  const int fd = open(path, O_RDONLY | O_CLOEXEC);
  if (fd < 0) return p;
  const ssize_t n = read(fd, buf, sizeof(buf) - 1);
  close(fd);
  if (n <= 0) return p;
  buf[n] = 0;
  const char* q = strrchr(buf, ')');
  if (q == nullptr || q[1] != ' ') return p;
  p.exists = true;
  p.state = q[2];
  // ") S " then field 4 (ppid); the start time is field 22
  const char* f = q + 4;
  for (int k = 4; k < 22 && f != nullptr; k++) {
    f = strchr(f, ' ');
    if (f != nullptr) f++;
  }
  if (f != nullptr) p.start = strtoull(f, nullptr, 10);
  return p;
}

static int gTimes = -1;  // the child's pipe: its two end times
static double gSecondMs = 500;
static void* secondThread(void*) {
  struct timespec d = {(time_t)(gSecondMs / 1000), (long)((gSecondMs - 1000.0 * (long)(gSecondMs / 1000)) * 1e6)};
  nanosleep(&d, nullptr);
  const double t = monoMs();
  (void)!write(gTimes, &t, sizeof(t));
  _exit(0);  // the last thread ends the group here (no exit handlers: nothing else of the program runs)
  return nullptr;
}

struct Trial {
  bool ok = false;
  double mainEndMs = -1, lastEndMs = -1, oldGoMs = -1, newGoMs = -1;
  char oldWhy[192] = {0};
};
static Trial runTrial(double secondMs) {
  Trial tr;
  int go[2], times[2];
  if (pipe(go) != 0 || pipe(times) != 0) {
    perror("pipe");
    return tr;
  }
  gSecondMs = secondMs;
  const pid_t pid = fork();
  if (pid < 0) {
    perror("fork");
    return tr;
  }
  if (pid == 0) {  // the child: wait for the go, start the second thread, end the main thread
    close(go[1]);
    close(times[0]);
    gTimes = times[1];
    char c;
    if (read(go[0], &c, 1) != 1) _exit(3);
    pthread_t th;
    if (pthread_create(&th, nullptr, secondThread, nullptr) != 0) _exit(4);
    const double t = monoMs();
    (void)!write(gTimes, &t, sizeof(t));
    pthread_exit(nullptr);  // the main thread ends; the group lives on in the second thread
  }
  close(go[0]);
  close(times[1]);
  const int pidfd = (int)syscall(SYS_pidfd_open, pid, 0);
  const struct gdakiRsActProbe at0 = procOf(pid);  // the start time recorded while the original lives
  const unsigned long long st0 = at0.start;
  CHECK(pidfd >= 0 && at0.exists && st0 != 0);
  char c = 'g';
  (void)!write(go[1], &c, 1);
  const double t0 = monoMs();
  while (monoMs() - t0 < 3000) {
    const double now = monoMs();
    char why[192];
    const struct gdakiRsActProbe pr = procOf(pid);
    const int procVerdict = gdakiRsActExamine((long long)pid, st0, pr, why, sizeof(why));  // the old gate
    struct pollfd pf = {pidfd, POLLIN, 0};
    const bool readable = pidfd >= 0 && poll(&pf, 1, 0) == 1 && (pf.revents & POLLIN);
    const int newGate = gdakiCtrlActGate(true, readable, procVerdict);  // the FENCED gate (launcher-paired)
    if (procVerdict == GDAKI_RS_ACT_GO && tr.oldGoMs < 0) {
      tr.oldGoMs = now;
      snprintf(tr.oldWhy, sizeof(tr.oldWhy), "%s", why);
    }
    if (newGate == GDAKI_RS_ACT_GO && tr.newGoMs < 0) tr.newGoMs = now;
    if (tr.oldGoMs >= 0 && tr.newGoMs >= 0) break;
    struct timespec d = {0, 1000000};
    nanosleep(&d, nullptr);
  }
  double t[2] = {-1, -1};
  for (int k = 0; k < 2; k++)
    if (read(times[0], &t[k], sizeof(t[k])) != (ssize_t)sizeof(t[k])) t[k] = -1;
  tr.mainEndMs = t[0];
  tr.lastEndMs = t[1];
  int status = 0;
  (void)waitpid(pid, &status, 0);
  if (pidfd >= 0) close(pidfd);
  close(go[1]);
  close(times[0]);
  tr.ok = tr.oldGoMs >= 0 && tr.newGoMs >= 0 && tr.mainEndMs >= 0 && tr.lastEndMs >= 0;
  return tr;
}

int main() {
  int trials = 0, diffOk = 0;
  for (int t = 0; t < 10; t++) {
    const Trial tr = runTrial(500.0);
    trials++;
    CHECK(tr.ok);
    if (!tr.ok) continue;
    const double diff = tr.newGoMs - tr.oldGoMs;
    // each gate against its own event on the child's clock (CLOCK_MONOTONIC is one clock for both processes)
    CHECK(tr.oldGoMs >= tr.mainEndMs - 1.0 && tr.oldGoMs <= tr.mainEndMs + 30.0);  // Z: the main thread's end
    CHECK(tr.newGoMs >= tr.lastEndMs - 1.0 && tr.newGoMs <= tr.lastEndMs + 30.0);  // pidfd: the group's end
    CHECK(strstr(tr.oldWhy, "zombie") != nullptr);  // the old gate went on the zombie, not on an absent /proc
    const bool inRange = diff >= 450.0 && diff <= 700.0;
    CHECK(inRange);
    diffOk += inRange;
    printf("gate_fenced trial %d: main thread ended +0, old gate GO +%.1f ms (%s); last thread ended +%.1f ms, FENCED "
           "gate GO +%.1f ms; the gates differ by %.1f ms\n", t, tr.oldGoMs - tr.mainEndMs, tr.oldWhy,
           tr.lastEndMs - tr.mainEndMs, tr.newGoMs - tr.mainEndMs, diff);
  }
  // the pure gate in both contexts: launcher-paired requires FENCED; no launcher is the /proc verdict
  CHECK(gdakiCtrlActGate(true, false, GDAKI_RS_ACT_GO) == GDAKI_RS_ACT_WAIT);
  CHECK(gdakiCtrlActGate(true, true, GDAKI_RS_ACT_GO) == GDAKI_RS_ACT_GO);
  CHECK(gdakiCtrlActGate(false, false, GDAKI_RS_ACT_GO) == GDAKI_RS_ACT_GO);
  CHECK(diffOk == trials);
  printf("gate_fenced: %d/%d trials of a real process (main thread ends, a second thread lives 500 ms): the FENCED gate "
         "(pidfd) went 450-700 ms after the /proc gate (Z), each within 30 ms of its event; %ld checks, %ld failed\n",
         diffOk, trials, gChecks, gFailed);
  return gFailed == 0 ? 0 : 1;
}
