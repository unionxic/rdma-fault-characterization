// gin_rec.cu - 2-rank NCCL GIN GDAKI recovery driver.
//
// Copied from ../gin_q4/gin_q4.cu (Q4 driver) and extended for the recovery prototype
// (gin_recovery.diff in this directory, NCCL_GIN_FAULT_RECOVERY=1). See RECOVERY_DESIGN.md.
//
//   * The management-net socket carries typed records (barrier, REQ/ACK/NACK/DONE/FAIL) so the
//     two hosts can run the recovery handshake while the receiver's waiter kernel still runs.
//   * Sender (rank 0, put initiator): when the device flush returns ncclRemoteError (Q4) it
//     queries the classified fault (ncclGinFaultQuery), applies the policy (LOCAL_QP_ERR ->
//     recover; RETRY_EXC -> recover iff the peer is alive on the OOB socket; anything else ->
//     decline), and runs Prepare -> REQ -> ACK -> Commit -> replay. The replay re-puts the data
//     and applies only the missing signal delta d that the receiver computed.
//   * Receiver (rank 1): its waiter kernel keeps spinning on its own signal memory. On REQ it
//     runs Prepare (its QPs -> ERR), reads its signal V on a side stream, computes
//     d = expected - V (must be 0 or 1), commits with the sender's token and replies ACK.
//     A timed-out waiter is re-armed while the peer is alive. On FAIL (declined) it releases
//     its own waiter with a signal to itself and stops without checking the data.
//   * Every iteration's data is checked bit-exact on the receiver and its signal must equal
//     the expected value exactly (a double-counted signal would exceed it); the final signal
//     must be base + iters.
//
// Exit codes: 0 ok (all iterations, recovered or not), 1 usage/setup, 2 NCCL call error,
//   3 async NCCL error, 4 device wait timed out, 5 data mismatch / signal not exact,
//   6 CUDA error, 7 watchdog, 8 device error without recovery (flag off),
//   9 recovery declined (error surfaced cleanly).
//
// usage:
//   gin_rec <rank 0|1> <rank0_mgmt_ip> <tcp_port> <iters> <bytes>
//           <timeout|blocking> <none|F1|F2|F3|F4|lat> <dev_timeout_s>
//           <host_watchdog_s> <out_kv_file> [gap_ms]
// env: GIN_RECOVERY=1 (app protocol; the runner also sets NCCL_GIN_FAULT_RECOVERY=1),
//      GIN_REC_MAX_PER_ITER (4), GIN_REC_HANDSHAKE_MS (3000), GIN_RX_ITER_CAP_S (30),
//      GIN_BLOCK_CAP_S, GIN_POST_POLL_S, GIN_ASYNC_POLL_US, GIN_LAT_* as in gin_q4.
//      live_peer study (harness/live_peer/EXPERIMENT.md), rank 1 only:
//        GIN_REC_TEST_STALL_MS=<ms> (0 = off) stops rank 1 once for <ms> through the lp_stall helper
//        (../../common/lp_stall.h), at GIN_REC_TEST_STALL_ON=req (first line of the first REQ it
//        handles, before Prepare) or iter:<k> (right after it sends BAR_ACK and launches the wait
//        kernel of iteration k). The kv gets "stall on= it= ms= begin_mono_ms= end_mono_ms=
//        measured_ms=". Without the variable the helper is not even forked.

#include <nccl.h>
#include "nccl_device.h"
#include <cuda_runtime.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cstdint>
#include <cstdarg>
#include <cerrno>
#include <ctime>
#include <atomic>
#include <thread>
#include <unistd.h>
#include <csignal>
#include <climits>
#include <vector>
#include <algorithm>
#include <poll.h>
#include <sys/resource.h>
#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <sys/socket.h>
#include "../../common/lp_stall.h"

static const int NRANKS = 2;
static int g_rank = -1;
static FILE* g_kv = nullptr;             // KEY=VALUE results file for the runner
static ncclComm_t g_comm = nullptr;
static int g_sock = -1;                  // management-net TCP socket to the peer
static const uint8_t POISON = 0xA5;      // receive-buffer fill; "missing" == all bytes still POISON
// live_peer stall switch (rank 1 only; see the header)
static lp_stall_t g_stall = { -1, -1 };
static unsigned g_stallMs = 0;
static bool g_stallOnReq = false;
static int g_stallIter = -1;
static bool g_stallDone = false;

// ---- small helpers --------------------------------------------------------
static double nowSec() {
  struct timespec t;
  clock_gettime(CLOCK_MONOTONIC, &t);
  return t.tv_sec + t.tv_nsec * 1e-9;
}
static double monoMs() { return nowSec() * 1e3; }
static double g_t0;                       // program start (CLOCK_MONOTONIC)
static double relMs() { return (nowSec() - g_t0) * 1e3; }

static void kv(const char* fmt, ...) {
  if (!g_kv) return;
  va_list ap; va_start(ap, fmt);
  vfprintf(g_kv, fmt, ap);
  va_end(ap);
  fputc('\n', g_kv);
  fflush(g_kv);
}

static void doStall(const char* on, int it) {
  if (g_stallDone || g_stallMs == 0) return;
  g_stallDone = true;
  uint64_t t0 = 0, t1 = 0;
  if (lp_stall_self(&g_stall, g_stallMs, &t0, &t1) != 0) {
    fprintf(stderr, "[rank%d] stall helper gone\n", g_rank);
    kv("stall on=%s it=%d ms=%u error=helper_gone", on, it, g_stallMs);
    return;
  }
  kv("stall on=%s it=%d ms=%u begin_mono_ms=%.3f end_mono_ms=%.3f measured_ms=%.3f", on, it, g_stallMs, t0 / 1e6,
     t1 / 1e6, (t1 - t0) / 1e6);
  fprintf(stderr, "[rank%d] stall on=%s it=%d ms=%u begin_mono_ms=%.3f end_mono_ms=%.3f\n", g_rank, on, it, g_stallMs,
          t0 / 1e6, t1 / 1e6);
}

#define CK(c) do { cudaError_t e_ = (c); if (e_ != cudaSuccess) { \
  fprintf(stderr, "[rank%d] CUDA %s:%d %s\n", g_rank, __FILE__, __LINE__, cudaGetErrorString(e_)); \
  kv("cuda_error=%s", cudaGetErrorString(e_)); _teardownExit(6); } } while (0)
#define NK(c) do { ncclResult_t r_ = (c); if (r_ != ncclSuccess && r_ != ncclInProgress) { \
  fprintf(stderr, "[rank%d] NCCL %s:%d %s\n", g_rank, __FILE__, __LINE__, ncclGetErrorString(r_)); \
  kv("nccl_error=%s", ncclGetErrorString(r_)); _teardownExit(2); } } while (0)

static void _teardownExit(int code);      // fwd

static int sendall(int fd, const void* b, size_t n) {
  const char* p = (const char*)b; size_t o = 0;
  while (o < n) { ssize_t k = send(fd, p + o, n - o, MSG_NOSIGNAL); if (k <= 0) { if (k < 0 && errno == EINTR) continue; return -1; } o += (size_t)k; }
  return 0;
}
static int recvall(int fd, void* b, size_t n) {
  char* p = (char*)b; size_t o = 0;
  while (o < n) { ssize_t k = recv(fd, p + o, n - o, 0); if (k <= 0) { if (k < 0 && errno == EINTR) continue; return -1; } o += (size_t)k; }
  return 0;
}

// Deterministic per-(iter,byte) pattern; poison never matches it.
static inline uint8_t pat(int it, size_t idx) {
  uint32_t h = (uint32_t)(idx * 2654435761u) ^ (uint32_t)(it * 40503u + 0x9e3779b9u);
  h ^= h >> 13;
  return (uint8_t)(h & 0xff);
}

// ---- OOB records on the management socket ----------------------------------
enum MsgType : uint32_t { M_BAR = 1, M_BAR_ACK = 2, M_REQ = 3, M_ACK = 4, M_NACK = 5, M_DONE = 6, M_FAIL = 7 };
static const char* msgName(uint32_t t) {
  switch (t) { case M_BAR: return "BAR"; case M_BAR_ACK: return "BAR_ACK"; case M_REQ: return "REQ"; case M_ACK: return "ACK";
    case M_NACK: return "NACK"; case M_DONE: return "DONE"; case M_FAIL: return "FAIL"; default: return "?"; }
}
static const uint32_t MSG_MAGIC = 0x47494e52u;  // "GINR"
struct Msg {
  uint32_t magic, type;
  int32_t iter, arg;     // REQ: class; ACK: d; NACK/FAIL: reason; DONE: replayed
  uint64_t v;            // ACK: receiver signal V
  double t;              // sender's CLOCK_MONOTONIC ms
  double f[4];           // ACK: receiver prepare_us, commit_us, drain_us, epoch_wqes
  ncclGinRecoverToken_t tok;
};

struct Oob {
  int fd = -1;
  uint8_t buf[sizeof(Msg)];
  size_t have = 0;
  int send(uint32_t type, int iter, int arg = 0, uint64_t v = 0, const ncclGinRecoverToken_t* tok = nullptr,
           const double* f = nullptr) {
    Msg m; memset(&m, 0, sizeof(m));
    m.magic = MSG_MAGIC; m.type = type; m.iter = iter; m.arg = arg; m.v = v; m.t = monoMs();
    if (tok) m.tok = *tok;
    if (f) for (int i = 0; i < 4; i++) m.f[i] = f[i];
    return sendall(fd, &m, sizeof(m));
  }
  // 1 = one record in *m, 0 = timeout, -1 = closed / error / desync
  int recv(Msg* m, int timeoutMs) {
    double deadline = monoMs() + timeoutMs;
    while (have < sizeof(Msg)) {
      int rem = (int)(deadline - monoMs());
      if (rem < 0) rem = 0;
      struct pollfd p = {fd, POLLIN, 0};
      int pr = poll(&p, 1, rem);
      if (pr == 0) return 0;
      if (pr < 0) { if (errno == EINTR) continue; return -1; }
      ssize_t k = ::recv(fd, buf + have, sizeof(Msg) - have, MSG_DONTWAIT);
      if (k == 0) return -1;
      if (k < 0) { if (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR) continue; return -1; }
      have += (size_t)k;
    }
    memcpy(m, buf, sizeof(Msg));
    have = 0;
    if (m->magic != MSG_MAGIC) { fprintf(stderr, "[rank%d] OOB desync (magic %#x)\n", g_rank, m->magic); return -1; }
    return 1;
  }
  // Liveness from the socket, as in the CPU classifier: FIN or RST/TCP error = dead.
  bool peerAlive() {
    if (have > 0) return true;
    char c;
    ssize_t k = ::recv(fd, &c, 1, MSG_PEEK | MSG_DONTWAIT);
    if (k > 0) return true;
    if (k == 0) return false;                                   // FIN
    if (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR) return true;
    return !(errno == ECONNRESET || errno == EPIPE || errno == ETIMEDOUT || errno == ENOTCONN);
  }
};
static Oob g_oob;

// ---- host watchdog --------------------------------------------------------
static std::atomic<int> g_phase{0};        // 0 setup, 1 running, 2 teardown
static void abortAlarm(int) {
  static const char m[] = "WATCHDOG: abort/teardown did not return; exiting 7\n";
  ssize_t w = write(2, m, sizeof(m) - 1); (void)w;
  _exit(7);
}

static void _teardownExit(int code) {
  static std::atomic<int> once{0};
  if (once.fetch_add(1) != 0) _exit(code);   // reentrancy guard
  g_phase.store(2);
  if (g_comm) {
    const char* wd = getenv("GIN_ABORT_WATCHDOG_S");
    unsigned s = wd ? (unsigned)atoi(wd) : 15u;
    signal(SIGALRM, abortAlarm);
    alarm(s);
    double a0 = relMs();
    ncclResult_t ar = ncclCommAbort(g_comm);
    alarm(0);
    double dt = relMs() - a0;
    kv("teardown=%s teardown_ms=%.1f abort_ret=%s", "clean", dt, ncclGetErrorString(ar));
    fprintf(stderr, "[rank%d] ncclCommAbort returned %s after %.1f ms\n", g_rank, ncclGetErrorString(ar), dt);
    g_comm = nullptr;
  } else {
    kv("teardown=n/a");
  }
  _exit(code);
}

// ================= device kernels =========================================
// rank 0: one put + weak-signal-increment (withSignal) to rank 1, then flush (local completion).
__global__ void putKernel(ncclWindow_t sendWin, size_t sendOff,
                          ncclWindow_t recvWin, size_t recvOff, size_t bytes,
                          unsigned signalIndex, int withSignal, struct ncclDevComm devComm,
                          int useTimeout, unsigned long long timeoutCycles, int* d_rc,
                          volatile int* d_phase) {
  ncclGin gin{devComm, 0};
  if (d_phase) { *d_phase = 1; __threadfence_system(); }
  if (withSignal)
    gin.put(ncclTeamWorld(devComm), 1, recvWin, recvOff, sendWin, sendOff, bytes, ncclGin_WeakSignalInc{signalIndex});
  else
    gin.put(ncclTeamWorld(devComm), 1, recvWin, recvOff, sendWin, sendOff, bytes);
  if (d_phase) { *d_phase = 2; __threadfence_system(); }
  ncclResult_t rc = ncclSuccess;
  if (useTimeout) rc = gin.flush(ncclCoopCta(), cuda::memory_order_acquire, ncclGin_None{}, timeoutCycles);
  else rc = gin.flush(ncclCoopCta());   // blocking; returns ncclRemoteError on a classified error CQE (Q4)
  if (d_phase) { *d_phase = 3; __threadfence_system(); }
  if (threadIdx.x == 0) *d_rc = (int)rc;
}

__device__ __forceinline__ unsigned long long gtNow() {
  unsigned long long t;
  asm volatile("mov.u64 %0, %%globaltimer;" : "=l"(t));
  return t;
}

__global__ void gtKernel(volatile unsigned long long* out, volatile int* stop) {
  while (!*stop) {
    *out = gtNow();
    __threadfence_system();
  }
}

__global__ void latKernel(ncclWindow_t sendWin, ncclWindow_t recvWin, size_t bytes, struct ncclDevComm devComm,
                          int useTimeout, unsigned long long timeoutCycles, int n, unsigned long long* d_lat,
                          int* d_rc) {
  ncclGin gin{devComm, 0};
  ncclResult_t rc = ncclSuccess;
  for (int i = 0; i < n; i++) {
    unsigned long long t0 = gtNow();
    gin.put(ncclTeamWorld(devComm), 1, recvWin, 0, sendWin, 0, bytes, ncclGin_WeakSignalInc{0});
    if (useTimeout) rc = gin.flush(ncclCoopCta(), cuda::memory_order_acquire, ncclGin_None{}, timeoutCycles);
    else rc = gin.flush(ncclCoopCta());
    unsigned long long t1 = gtNow();
    if (threadIdx.x == 0) d_lat[i] = t1 - t0;
    if (rc != ncclSuccess) break;
  }
  if (threadIdx.x == 0) *d_rc = (int)rc;
}

__global__ void readSigKernel(unsigned signalIndex, struct ncclDevComm devComm, unsigned long long* d_sig) {
  ncclGin gin{devComm, 0};
  if (threadIdx.x == 0) *d_sig = gin.readSignal(signalIndex);
}

// rank 1: wait for the signal to reach `expected`, then report what it saw.
__global__ void waitKernel(unsigned signalIndex, unsigned long long expected,
                           struct ncclDevComm devComm, int useTimeout,
                           unsigned long long timeoutCycles,
                           int* d_rc, unsigned long long* d_sig) {
  ncclGin gin{devComm, 0};
  ncclResult_t rc = ncclSuccess;
  if (useTimeout) {
    rc = gin.waitSignal(ncclCoopCta(), signalIndex, expected, 64, cuda::memory_order_acquire, timeoutCycles);
  } else {
    gin.waitSignal(ncclCoopCta(), signalIndex, expected);   // unbounded
  }
  if (threadIdx.x == 0) {
    *d_rc = (int)rc;
    *d_sig = gin.readSignal(signalIndex);
  }
}

// rank 1, decline path: release this rank's own (blocking) waiter with a signal to itself over the
// self-loop QP. The iteration is then reported as failed, its data is not checked.
// It has a 336-byte stack frame (the waiter has none): launched for the first time while the waiter
// spins, it would need a local-memory resize, which the driver only does with the device idle, so
// it would not start until the waiter exits (measured: never, in blocking mode). It is therefore
// launched once with dry=1 at init to size the local memory before any waiter runs.
__global__ void cancelKernel(struct ncclDevComm devComm, int self, unsigned long long timeoutCycles, int* d_rc,
                             volatile int* d_cphase, int dry) {
  if (dry) return;
  if (d_cphase) { *d_cphase = 1; __threadfence_system(); }
  ncclGin gin{devComm, 0};
  gin.signal(ncclTeamWorld(devComm), self, ncclGin_WeakSignalInc{0});
  if (d_cphase) { *d_cphase = 2; __threadfence_system(); }
  ncclResult_t rc = gin.flush(ncclCoopCta(), cuda::memory_order_acquire, ncclGin_None{}, timeoutCycles);
  if (d_cphase) { *d_cphase = 3; __threadfence_system(); }
  if (threadIdx.x == 0) *d_rc = (int)rc;
}

// ================= main ====================================================
struct AsyncMon {                          // background ncclCommGetAsyncError poller
  ncclComm_t comm;
  std::atomic<bool> stop{false};
  std::atomic<int> firstErr{(int)ncclSuccess};
  std::atomic<double> firstMs{-1.0};
  std::atomic<int> nErrSamples{0};
};
static void asyncMonRun(AsyncMon* m) {
  const char* pu = getenv("GIN_ASYNC_POLL_US");
  useconds_t pollUs = pu ? (useconds_t)atoi(pu) : 2000u;
  while (!m->stop.load()) {
    ncclResult_t s = ncclSuccess;
    if (ncclCommGetAsyncError(m->comm, &s) == ncclSuccess) {
      if (s != ncclSuccess && s != ncclInProgress) {
        m->nErrSamples++;
        if (m->firstMs.load() < 0) {
          m->firstErr.store((int)s);
          m->firstMs.store(relMs());
        }
      }
    }
    usleep(pollUs);
  }
}

static long long calibrateGlobalTimer(double* spreadUs) {
  volatile unsigned long long* h_gt = nullptr; unsigned long long* d_gt = nullptr;
  volatile int* h_stop = nullptr; int* d_stop = nullptr;
  if (cudaHostAlloc((void**)&h_gt, sizeof(unsigned long long), cudaHostAllocMapped) != cudaSuccess) return 0;
  if (cudaHostAlloc((void**)&h_stop, sizeof(int), cudaHostAllocMapped) != cudaSuccess) return 0;
  cudaHostGetDevicePointer((void**)&d_gt, (void*)h_gt, 0);
  cudaHostGetDevicePointer((void**)&d_stop, (void*)h_stop, 0);
  *h_gt = 0; *h_stop = 0;
  cudaStream_t s; cudaStreamCreateWithFlags(&s, cudaStreamNonBlocking);
  gtKernel<<<1, 1, 0, s>>>(d_gt, d_stop);
  double t0 = nowSec();
  while (*h_gt == 0 && nowSec() - t0 < 2.0) {}
  long long best = LLONG_MIN, worst = LLONG_MAX;
  unsigned long long prev = 0;
  for (int k = 0; k < 200000; k++) {
    struct timespec a, b;
    clock_gettime(CLOCK_MONOTONIC, &a);
    unsigned long long g = *h_gt;
    clock_gettime(CLOCK_MONOTONIC, &b);
    if (g == prev) continue;
    prev = g;
    long long t2 = (long long)b.tv_sec * 1000000000LL + b.tv_nsec;
    long long t1 = (long long)a.tv_sec * 1000000000LL + a.tv_nsec;
    long long lo = (long long)g - t2, hi = (long long)g - t1;
    if (lo > best) best = lo;
    if (hi < worst) worst = hi;
  }
  *h_stop = 1;
  cudaStreamSynchronize(s);
  cudaStreamDestroy(s);
  cudaFreeHost((void*)h_gt); cudaFreeHost((void*)h_stop);
  if (best == LLONG_MIN) return 0;
  if (spreadUs) *spreadUs = (worst - best) / 1e3;
  return best;
}

static int cmpU64(const void* a, const void* b) {
  unsigned long long x = *(const unsigned long long*)a, y = *(const unsigned long long*)b;
  return x < y ? -1 : x > y ? 1 : 0;
}

// ---- shared state of one run ----------------------------------------------
struct Run {
  int rank = 0;
  bool useTimeout = true;
  bool recOn = false;
  size_t bytes = 0;
  int iters = 0;
  double devTimeoutS = 5, blockCapS = 25, rxCapS = 30;
  unsigned long long timeoutCycles = 0;
  long long gtOffNs = 0;
  int maxPerIter = 4, handshakeMs = 3000;
  cudaStream_t st = nullptr, side = nullptr;
  ncclDevComm devComm;
  ncclWindow_t sendWin, recvWin;
  void *d_send = nullptr, *d_recv = nullptr;
  size_t recvOff = 0;
  int* h_rc = nullptr; int* d_rc = nullptr;
  volatile int* h_phase = nullptr; int* d_phase = nullptr;
  unsigned long long* h_sig = nullptr; unsigned long long* d_sig = nullptr;
  unsigned long long* h_sig2 = nullptr; unsigned long long* d_sig2 = nullptr;
  int* h_rc2 = nullptr; int* d_rc2 = nullptr;
  volatile int* h_cphase = nullptr; int* d_cphase = nullptr;
  unsigned long long sigBase = 0;
  int nRecEvents = 0, nRecovered = 0, nReplays = 0, nDeltaZero = 0;
  const char* declineReason = nullptr;
};

// Launch the put kernel and wait for it (bounded). Returns the device rc, or -1 on host timeout.
static int runPut(Run& R, int it, int withSignal, double* tRet) {
  *R.h_rc = 123456;
  *R.h_phase = 0;
  putKernel<<<1, 1, 0, R.st>>>(R.sendWin, 0, R.recvWin, R.recvOff, R.bytes, 0, withSignal, R.devComm,
                               R.useTimeout ? 1 : 0, R.timeoutCycles, R.d_rc, R.d_phase);
  cudaError_t le = cudaGetLastError();
  if (le != cudaSuccess) { kv("cuda_error=%s", cudaGetErrorString(le)); _teardownExit(6); }
  double dl = nowSec() + (R.useTimeout ? R.devTimeoutS + 5.0 : R.blockCapS);
  while (true) {
    cudaError_t q = cudaStreamQuery(R.st);
    if (q == cudaSuccess) break;
    if (q != cudaErrorNotReady) { kv("cuda_error=%s", cudaGetErrorString(q)); _teardownExit(6); }
    if (nowSec() > dl) { *tRet = monoMs(); return -1; }
    usleep(200);
  }
  *tRet = monoMs();
  (void)it;
  return *R.h_rc;
}

// Sender: recovery of operation `it` after its flush returned ncclRemoteError.
// Returns 1 recovered, 0 declined (R.declineReason set; FAIL sent to the peer).
static int senderRecover(Run& R, int it, double tKernelRet, bool forced = false) {
  for (int attempt = 1;; attempt++) {
    R.nRecEvents++;
    const int ev = R.nRecEvents;
    auto decline = [&](const char* why, bool sendFail) {
      R.declineReason = why;
      if (sendFail) g_oob.send(M_FAIL, it, 1);
      kv("rec ev=%d it=%d attempt=%d outcome=declined reason=%s t_kret=%.3f t_decl=%.3f", ev, it, attempt, why,
         tKernelRet, monoMs());
      fprintf(stderr, "[rank0] it %d recovery DECLINED: %s\n", it, why);
      return 0;
    };
    if (attempt > R.maxPerIter) return decline("too_many_attempts", true);
    ncclGinFaultInfo_t fi;
    ncclResult_t qr = ncclSuccess;
    if (forced && attempt == 1) {
      // Test D0: no fault; the operation completed. Exercises the d = 0 branch (the ADD had landed).
      memset(&fi, 0, sizeof(fi));
      fi.valid = 1;
      fi.recoverable = 1;
      snprintf(fi.className, sizeof(fi.className), "FORCED_TEST");
    } else {
      qr = ncclGinFaultQuery(g_comm, 200, &fi);
    }
    double tQuery = monoMs();
    if (qr != ncclSuccess) return decline("fault_query_failed", true);
    if (!fi.valid) return decline("no_classified_record", true);
    const double tDev = fi.gtimerNs ? (double)((long long)fi.gtimerNs - R.gtOffNs) / 1e6 : -1.0;
    kv("fault ev=%d it=%d attempt=%d class=%s cls=%d fp=%d/%#x qpn=%#x wqe=%u nrec=%u recoverable=%d t_dev=%.3f "
       "t_mbx=%.3f t_kret=%.3f t_query=%.3f",
       ev, it, attempt, fi.className, fi.cls, fi.wcStatus, fi.vendorErr, fi.qpn, fi.wqeCounter, fi.nRecords,
       fi.recoverable, tDev, fi.hostMonoMs, tKernelRet, tQuery);
    bool alive = g_oob.peerAlive();
    if (fi.recoverable == 0) {
      static char why[64];
      snprintf(why, sizeof(why), "class_%s", fi.className);
      return decline(why, alive);
    }
    if (fi.recoverable == 2 && !alive) return decline("retry_exc_peer_dead", false);
    ncclGinRecoverToken_t tokS;
    ncclGinRecoverStats_t stS;
    memset(&stS, 0, sizeof(stS));
    double tp0 = monoMs();
    if (ncclGinRecoverPrepare(g_comm, 1, &tokS, &stS) != ncclSuccess) return decline("prepare_failed", true);
    double tPrep = monoMs();
    if (g_oob.send(M_REQ, it, fi.cls, 0, &tokS)) { ncclGinRecoverAbort(g_comm, 1); return decline("oob_send_failed", false); }
    // wait for ACK (bounded)
    Msg m;
    memset(&m, 0, sizeof(m));
    double dl = monoMs() + R.handshakeMs;
    int got = 0;
    while (true) {
      int rem = (int)(dl - monoMs());
      if (rem <= 0) { got = 0; break; }
      got = g_oob.recv(&m, rem);
      if (got <= 0) break;
      if (m.iter == it && (m.type == M_ACK || m.type == M_NACK || m.type == M_FAIL)) break;
      fprintf(stderr, "[rank0] it %d: ignoring %s(%d) during handshake\n", it, msgName(m.type), m.iter);
    }
    double tAck = monoMs();
    if (got == 0) { ncclGinRecoverAbort(g_comm, 1); return decline("handshake_timeout", true); }
    if (got < 0) { ncclGinRecoverAbort(g_comm, 1); return decline("peer_closed_during_handshake", false); }
    if (m.type != M_ACK) {
      ncclGinRecoverAbort(g_comm, 1);
      return decline(m.type == M_NACK ? "peer_nack" : "peer_fail", false);
    }
    const int d = m.arg;
    if (d != 0 && d != 1) { ncclGinRecoverAbort(g_comm, 1); return decline("bad_delta", true); }
    if (ncclGinRecoverCommit(g_comm, 1, &m.tok, &stS) != ncclSuccess) return decline("commit_failed", true);
    double tCommit = monoMs();
    ncclResult_t ae = ncclSuccess;
    ncclCommGetAsyncError(g_comm, &ae);
    int replayRc = 0;
    double tReplay = tCommit;
    if (d == 1) {
      R.nReplays++;
      replayRc = runPut(R, it, /*withSignal=*/1, &tReplay);
    } else {
      R.nDeltaZero++;
    }
    kv("rec ev=%d it=%d attempt=%d class=%s d=%d V=%llu outcome=%s t_kret=%.3f t_query=%.3f t_prep0=%.3f "
       "t_prep=%.3f t_ack=%.3f t_commit=%.3f t_replay=%.3f replay_rc=%d async_after_commit=%s prep_us=%.0f err_us=%.0f "
       "drain_us=%.0f commit_us=%.0f reset_us=%.0f resync_us=%.0f connect_us=%.0f nqp=%d epoch_wqes=%llu cqe_err=%u "
       "cqe_ok=%u rx_prep_us=%.0f rx_commit_us=%.0f rx_drain_us=%.0f rx_epoch_wqes=%.0f",
       ev, it, attempt, fi.className, d, (unsigned long long)m.v,
       (d == 0 || replayRc == (int)ncclSuccess) ? "recovered" : "replay_failed", tKernelRet, tQuery, tp0, tPrep, tAck,
       tCommit, tReplay, replayRc, ncclGetErrorString(ae), stS.prepareUs, stS.errUs, stS.drainUs, stS.commitUs,
       stS.resetUs, stS.resyncUs, stS.connectUs, stS.nqp, stS.epochWqes, stS.cqeErr, stS.cqeOk, m.f[0], m.f[1], m.f[2],
       m.f[3]);
    fprintf(stderr, "[rank0] it %d recovery ev %d (%s): d=%d commit %.2f ms after kernel return, replay rc=%d\n", it,
            ev, fi.className, d, tCommit - tKernelRet, replayRc);
    if (d == 0 || replayRc == (int)ncclSuccess) {
      g_oob.send(M_DONE, it, d);
      R.nRecovered++;
      return 1;
    }
    if (replayRc == (int)ncclRemoteError) {  // fault during the replay: next round, V is read again
      tKernelRet = tReplay;
      continue;
    }
    return decline(replayRc < 0 ? "replay_host_timeout" : "replay_error", true);
  }
}

// Receiver: answer a REQ for iteration i (current, or the one just completed).
static void receiverHandleReq(Run& R, const Msg& req, int curIt, int lastDone, bool* recovering) {
  if (g_stallOnReq) doStall("req", req.iter);   // live_peer: stop before anything of the request is handled
  const int i = req.iter;
  const double tReq = monoMs();
  if (i != curIt && i != lastDone) {
    g_oob.send(M_NACK, i, 1);
    kv("rxrec it=%d outcome=nack reason=wrong_iter cur=%d last_done=%d", i, curIt, lastDone);
    return;
  }
  ncclGinRecoverToken_t tokR;
  ncclGinRecoverStats_t stR;
  memset(&stR, 0, sizeof(stR));
  if (ncclGinRecoverPrepare(g_comm, 0, &tokR, &stR) != ncclSuccess) {
    g_oob.send(M_NACK, i, 2);
    kv("rxrec it=%d outcome=nack reason=prepare_failed", i);
    return;
  }
  double tPrep = monoMs();
  // V: read after this rank's QPs are in ERR (and the sender's already were). Side stream: the
  // waiter kernel may still be spinning on the main stream.
  *R.h_sig2 = ~0ULL;
  readSigKernel<<<1, 1, 0, R.side>>>(0, R.devComm, R.d_sig2);
  if (cudaGetLastError() != cudaSuccess || cudaStreamSynchronize(R.side) != cudaSuccess) {
    ncclGinRecoverAbort(g_comm, 0);
    g_oob.send(M_NACK, i, 3);
    kv("rxrec it=%d outcome=nack reason=read_signal_failed", i);
    return;
  }
  const unsigned long long V = *R.h_sig2;
  const unsigned long long expected = R.sigBase + (unsigned long long)i + 1ULL;
  const long long d = (long long)(expected - V);
  if (d != 0 && d != 1) {
    ncclGinRecoverAbort(g_comm, 0);
    g_oob.send(M_NACK, i, 4, V);
    kv("rxrec it=%d outcome=nack reason=bad_delta V=%llu expected=%llu", i, V, expected);
    return;
  }
  if (ncclGinRecoverCommit(g_comm, 0, &req.tok, &stR) != ncclSuccess) {
    g_oob.send(M_NACK, i, 5, V);
    kv("rxrec it=%d outcome=nack reason=commit_failed", i);
    return;
  }
  double tCommit = monoMs();
  double f[4] = {stR.prepareUs, stR.commitUs, stR.drainUs, (double)stR.epochWqes};
  g_oob.send(M_ACK, i, (int)d, V, &tokR, f);
  *recovering = true;
  kv("rxrec it=%d outcome=ack V=%llu expected=%llu d=%lld cur=%d t_req=%.3f t_prep=%.3f t_commit=%.3f "
     "prep_us=%.0f err_us=%.0f drain_us=%.0f commit_us=%.0f reset_us=%.0f resync_us=%.0f connect_us=%.0f epoch_wqes=%llu",
     i, V, expected, d, curIt, tReq, tPrep, tCommit, stR.prepareUs, stR.errUs, stR.drainUs, stR.commitUs, stR.resetUs,
     stR.resyncUs, stR.connectUs, stR.epochWqes);
  fprintf(stderr, "[rank1] it %d: REQ answered (V=%llu d=%lld) in %.2f ms\n", i, V, d, tCommit - tReq);
}

// Receiver: release its own waiter (decline path).
static void receiverCancel(Run& R) {
  *R.h_rc2 = 123456;
  *R.h_cphase = 0;
  const double t0 = monoMs();
  cancelKernel<<<1, 1, 0, R.side>>>(R.devComm, 1, R.timeoutCycles, R.d_rc2, R.d_cphase, 0);
  cudaError_t e = cudaGetLastError();
  double dl = nowSec() + R.devTimeoutS + 2.0;
  double tStart = -1, tSig = -1;
  while (e == cudaSuccess && cudaStreamQuery(R.side) == cudaErrorNotReady && nowSec() < dl) {
    if (tStart < 0 && *R.h_cphase >= 1) tStart = monoMs() - t0;
    if (tSig < 0 && *R.h_cphase >= 2) tSig = monoMs() - t0;
    usleep(100);
  }
  kv("rx_cancel_rc=%d rx_cancel_launch=%s rx_cancel_phase=%d rx_cancel_start_ms=%.2f rx_cancel_signal_ms=%.2f "
     "rx_cancel_total_ms=%.2f waiter_done=%d",
     *R.h_rc2, cudaGetErrorString(e), *R.h_cphase, tStart, tSig, monoMs() - t0,
     cudaStreamQuery(R.st) == cudaSuccess ? 1 : 0);
}

int main(int argc, char** argv) {
  g_t0 = nowSec();
  // live_peer: fork the stall helper before any file, thread or CUDA call (rank 1, switch set)
  if (argc > 1 && atoi(argv[1]) == 1 && getenv("GIN_REC_TEST_STALL_MS") && atoi(getenv("GIN_REC_TEST_STALL_MS")) > 0) {
    g_stallMs = (unsigned)atoi(getenv("GIN_REC_TEST_STALL_MS"));
    const char* on = getenv("GIN_REC_TEST_STALL_ON") ? getenv("GIN_REC_TEST_STALL_ON") : "req";
    if (strcmp(on, "req") == 0) g_stallOnReq = true;
    else if (strncmp(on, "iter:", 5) == 0) g_stallIter = atoi(on + 5);
    else { fprintf(stderr, "bad GIN_REC_TEST_STALL_ON=%s\n", on); return 1; }
    if (lp_stall_start(&g_stall) != 0) { perror("lp_stall_start"); return 1; }
    fprintf(stderr, "[rank1] live_peer stall switch: %u ms on %s (helper pid %d)\n", g_stallMs, on, (int)g_stall.pid);
  }
  if (argc < 11) {
    fprintf(stderr, "usage: %s <rank 0|1> <rank0_ip> <port> <iters> <bytes> "
                    "<timeout|blocking> <none|F1|F2|F3|F4|lat> <dev_timeout_s> "
                    "<host_watchdog_s> <out_kv_file> [gap_ms]\n", argv[0]);
    return 1;
  }
  Run R;
  int rank        = atoi(argv[1]); g_rank = rank; R.rank = rank;
  const char* peer= argv[2];
  int port        = atoi(argv[3]);
  int iters       = atoi(argv[4]); R.iters = iters;
  size_t bytes    = strtoul(argv[5], nullptr, 10); R.bytes = bytes;
  bool useTimeout = strcmp(argv[6], "timeout") == 0; R.useTimeout = useTimeout;
  const char* fault = argv[7];
  double devTimeoutS = atof(argv[8]); R.devTimeoutS = devTimeoutS;
  double watchdogS   = atof(argv[9]);
  g_kv = fopen(argv[10], "w");
  int gapMs = (argc > 11) ? atoi(argv[11]) : 0;
  R.blockCapS = getenv("GIN_BLOCK_CAP_S") ? atof(getenv("GIN_BLOCK_CAP_S")) : 25.0;
  double postPollS = getenv("GIN_POST_POLL_S") ? atof(getenv("GIN_POST_POLL_S")) : 15.0;
  R.recOn = getenv("GIN_RECOVERY") && atoi(getenv("GIN_RECOVERY")) != 0;
  R.maxPerIter = getenv("GIN_REC_MAX_PER_ITER") ? atoi(getenv("GIN_REC_MAX_PER_ITER")) : 4;
  R.handshakeMs = getenv("GIN_REC_HANDSHAKE_MS") ? atoi(getenv("GIN_REC_HANDSHAKE_MS")) : 3000;
  R.rxCapS = getenv("GIN_RX_ITER_CAP_S") ? atof(getenv("GIN_RX_ITER_CAP_S")) : 30.0;
  kv("t0_mono_ms=%.3f block_cap_s=%.1f post_poll_s=%.1f recovery=%d max_per_iter=%d handshake_ms=%d rx_iter_cap_s=%.1f",
     g_t0 * 1e3, R.blockCapS, postPollS, R.recOn ? 1 : 0, R.maxPerIter, R.handshakeMs, R.rxCapS);

  if ((rank != 0 && rank != 1) || iters <= 0 || bytes == 0) { fprintf(stderr, "bad args\n"); return 1; }
  bool isRemAccess = strcmp(fault, "F2") == 0;
  bool isProcKill  = strcmp(fault, "F4") == 0;
  bool isLat       = strcmp(fault, "lat") == 0;
  // D0: no fault; after each iteration listed in GIN_TEST_D0_ITERS (default 30,60,90) the sender runs a
  // full recovery of the (healthy) QPs for the operation that just completed -> the receiver must
  // report d = 0 and nothing may be replayed.
  std::vector<int> d0Iters;
  if (strcmp(fault, "D0") == 0) {
    const char* l = getenv("GIN_TEST_D0_ITERS") ? getenv("GIN_TEST_D0_ITERS") : "30,60,90";
    for (const char* p = l; p && *p; p = strchr(p, ',') ? strchr(p, ',') + 1 : nullptr) d0Iters.push_back(atoi(p));
  }
  kv("rank=%d bytes=%zu iters=%d wait_mode=%s fault=%s dev_timeout_s=%.1f", rank, bytes, iters, argv[6], fault, devTimeoutS);

  std::thread([watchdogS]() {
    double deadline = nowSec() + watchdogS;
    while (nowSec() < deadline) usleep(50000);
    static const char m[] = "WATCHDOG: global deadline exceeded; exiting 7\n";
    ssize_t w = write(2, m, sizeof(m) - 1); (void)w;
    _exit(7);
  }).detach();

  // ---- bootstrap the ncclUniqueId over our own TCP (management net) -------
  int one = 1; ncclUniqueId id;
  if (rank == 0) {
    NK(ncclGetUniqueId(&id));
    int ls = socket(AF_INET, SOCK_STREAM, 0);
    setsockopt(ls, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
    sockaddr_in a{}; a.sin_family = AF_INET; a.sin_addr.s_addr = INADDR_ANY; a.sin_port = htons(port);
    if (bind(ls, (sockaddr*)&a, sizeof a)) { perror("bind"); return 1; }
    listen(ls, 1);
    fprintf(stderr, "[rank0] waiting for rank1 on :%d\n", port);
    int cs = accept(ls, nullptr, nullptr);
    setsockopt(cs, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
    if (sendall(cs, &id, sizeof id)) { perror("send id"); return 1; }
    close(ls);
    g_sock = cs;
  } else {
    sockaddr_in a{}; a.sin_family = AF_INET; a.sin_port = htons(port); inet_pton(AF_INET, peer, &a.sin_addr);
    int cs = -1;
    for (int t = 0; ; t++) {
      cs = socket(AF_INET, SOCK_STREAM, 0);
      if (connect(cs, (sockaddr*)&a, sizeof a) == 0) break;
      close(cs);
      if (t > 600) { fprintf(stderr, "[rank1] cannot reach rank0\n"); return 1; }
      usleep(200000);
    }
    setsockopt(cs, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
    if (recvall(cs, &id, sizeof id)) { perror("recv id"); return 1; }
    g_sock = cs;
  }
  g_oob.fd = g_sock;

  {
    double bestRtt = 1e9, bestOff = 0;
    for (int k = 0; k < 32; k++) {
      double t0 = 0, t1 = 0, t2 = 0;
      if (rank == 0) {
        t0 = nowSec() * 1e3;
        if (sendall(g_sock, &t0, sizeof t0) || recvall(g_sock, &t1, sizeof t1)) break;
        t2 = nowSec() * 1e3;
        if (t2 - t0 < bestRtt) { bestRtt = t2 - t0; bestOff = t1 - (t0 + t2) / 2; }
      } else {
        if (recvall(g_sock, &t0, sizeof t0)) break;
        t1 = nowSec() * 1e3;
        if (sendall(g_sock, &t1, sizeof t1)) break;
      }
    }
    if (rank == 0) kv("clock_offset_ms=%.3f clock_rtt_ms=%.3f", bestOff, bestRtt);
  }

  if (getenv("GIN_BOOTSTRAP_TEST")) {
    fprintf(stderr, "[rank%d] bootstrap ok (id exchanged over TCP)\n", rank);
    kv("bootstrap=ok");
    return 0;
  }

  CK(cudaSetDevice(0));
  {
    double spreadUs = 0;
    R.gtOffNs = calibrateGlobalTimer(&spreadUs);
    kv("gt_off_ns=%lld gt_cal_spread_us=%.1f", R.gtOffNs, spreadUs);
  }
  int clockKHz = 0; CK(cudaDeviceGetAttribute(&clockKHz, cudaDevAttrClockRate, 0));
  R.timeoutCycles = (unsigned long long)(devTimeoutS * clockKHz * 1000.0);

  ncclConfig_t cfg = NCCL_CONFIG_INITIALIZER;
  cfg.blocking = 1;
  NK(ncclCommInitRankConfig(&g_comm, NRANKS, id, rank, &cfg));
  kv("comm_blocking=%d", cfg.blocking);

  ncclCommProperties_t props = NCCL_COMM_PROPERTIES_INITIALIZER;
  NK(ncclCommQueryProperties(g_comm, &props));
  if (!props.deviceApiSupport || props.ginType == NCCL_GIN_TYPE_NONE) {
    kv("gin_available=0 gin_type=%d", props.ginType);
    _teardownExit(2);
  }
  kv("gin_available=1 gin_type=%d", props.ginType);

  NK(ncclMemAlloc(&R.d_send, bytes));
  NK(ncclMemAlloc(&R.d_recv, bytes));
  NK(ncclCommWindowRegister(g_comm, R.d_send, bytes, &R.sendWin, NCCL_WIN_COLL_SYMMETRIC));
  NK(ncclCommWindowRegister(g_comm, R.d_recv, bytes, &R.recvWin, NCCL_WIN_COLL_SYMMETRIC));

  CK(cudaStreamCreateWithFlags(&R.st, cudaStreamNonBlocking));
  CK(cudaStreamCreateWithFlags(&R.side, cudaStreamNonBlocking));
  ncclDevCommRequirements reqs = NCCL_DEV_COMM_REQUIREMENTS_INITIALIZER;
  reqs.worldGinBarrierCount = 1;
  reqs.ginSignalCount = 1;
  reqs.ginConnectionType = NCCL_GIN_CONNECTION_FULL;
  NK(ncclDevCommCreate(g_comm, &reqs, &R.devComm));
  fprintf(stderr, "[rank%d] devComm created (clock=%d kHz)\n", rank, clockKHz);

  uint8_t* hbuf = (uint8_t*)malloc(bytes);
  CK(cudaHostAlloc((void**)&R.h_rc, sizeof(int), cudaHostAllocMapped));
  CK(cudaHostGetDevicePointer((void**)&R.d_rc, R.h_rc, 0));
  CK(cudaHostAlloc((void**)&R.h_rc2, sizeof(int), cudaHostAllocMapped));
  CK(cudaHostGetDevicePointer((void**)&R.d_rc2, R.h_rc2, 0));
  CK(cudaHostAlloc((void**)&R.h_cphase, sizeof(int), cudaHostAllocMapped));
  CK(cudaHostGetDevicePointer((void**)&R.d_cphase, (void*)R.h_cphase, 0));
  *R.h_cphase = 0;
  CK(cudaHostAlloc((void**)&R.h_phase, sizeof(int), cudaHostAllocMapped));
  CK(cudaHostGetDevicePointer((void**)&R.d_phase, (void*)R.h_phase, 0));
  *R.h_phase = 0;
  CK(cudaHostAlloc((void**)&R.h_sig, sizeof(unsigned long long), cudaHostAllocMapped));
  CK(cudaHostGetDevicePointer((void**)&R.d_sig, R.h_sig, 0));
  CK(cudaHostAlloc((void**)&R.h_sig2, sizeof(unsigned long long), cudaHostAllocMapped));
  CK(cudaHostGetDevicePointer((void**)&R.d_sig2, R.h_sig2, 0));

  if (rank == 1) {
    // Warm the decline-path kernel (see cancelKernel) while no other kernel runs.
    cancelKernel<<<1, 1, 0, R.side>>>(R.devComm, 1, R.timeoutCycles, R.d_rc2, R.d_cphase, 1);
    CK(cudaStreamSynchronize(R.side));
    *R.h_sig = 0;
    readSigKernel<<<1, 1, 0, R.st>>>(0, R.devComm, R.d_sig);
    CK(cudaStreamSynchronize(R.st));
    R.sigBase = *R.h_sig;
    kv("signal_base=%llu", R.sigBase);
  }

  AsyncMon mon; mon.comm = g_comm;
  std::thread monTh(asyncMonRun, &mon);
  g_phase.store(1);

  if (isLat) {
    // ---- overhead: GIN_LAT_REPS x GIN_LAT_ITERS (put + signal + flush), no fault (as gin_q4) ----
    int latIters = getenv("GIN_LAT_ITERS") ? atoi(getenv("GIN_LAT_ITERS")) : 2000;
    int latReps = getenv("GIN_LAT_REPS") ? atoi(getenv("GIN_LAT_REPS")) : 5;
    if (latIters <= 0) latIters = 2000;
    if (latReps <= 0) latReps = 5;
    unsigned long long* d_lat = nullptr;
    CK(cudaMalloc((void**)&d_lat, sizeof(unsigned long long) * latIters));
    std::vector<unsigned long long> lat((size_t)latIters * latReps, 0ULL);
    if (rank == 0) {
      for (size_t i = 0; i < bytes; i++) hbuf[i] = pat(0, i);
      CK(cudaMemcpy(R.d_send, hbuf, bytes, cudaMemcpyHostToDevice));
    } else {
      CK(cudaMemset(R.d_recv, (int)POISON, bytes));
    }
    CK(cudaDeviceSynchronize());
    struct rusage ru0, ru1;
    getrusage(RUSAGE_SELF, &ru0);
    double w0 = nowSec();
    int latRc = 0, repsDone = 0;
    const char* latOutcome = "ok";
    for (int r = 0; r < latReps; r++) {
      char sync = (char)r;
      if (rank == 0) { if (sendall(g_sock, &sync, 1) || recvall(g_sock, &sync, 1)) { latOutcome = "peer_gone"; break; } }
      else           { if (recvall(g_sock, &sync, 1) || sendall(g_sock, &sync, 1)) { latOutcome = "peer_gone"; break; } }
      *R.h_rc = 123456;
      if (rank == 0) {
        latKernel<<<1, 1, 0, R.st>>>(R.sendWin, R.recvWin, bytes, R.devComm, useTimeout ? 1 : 0, R.timeoutCycles, latIters, d_lat, R.d_rc);
      } else {
        waitKernel<<<1, 1, 0, R.st>>>(0, R.sigBase + (unsigned long long)(r + 1) * latIters, R.devComm, 1, R.timeoutCycles * 4, R.d_rc, R.d_sig);
      }
      CK(cudaGetLastError());
      double dl = nowSec() + (useTimeout ? devTimeoutS * 4 + 30.0 : R.blockCapS);
      bool to = false;
      while (true) { cudaError_t q = cudaStreamQuery(R.st); if (q == cudaSuccess) break; if (q != cudaErrorNotReady) { CK(q); } if (nowSec() > dl) { to = true; break; } usleep(200); }
      if (to) { latOutcome = "hang"; break; }
      latRc = *R.h_rc;
      if (latRc != (int)ncclSuccess) { latOutcome = "error"; break; }
      if (rank == 0) CK(cudaMemcpy(lat.data() + (size_t)r * latIters, d_lat, sizeof(unsigned long long) * latIters, cudaMemcpyDeviceToHost));
      repsDone++;
    }
    getrusage(RUSAGE_SELF, &ru1);
    double wallMs = (nowSec() - w0) * 1e3;
    double cpuMs = ((ru1.ru_utime.tv_sec - ru0.ru_utime.tv_sec) + (ru1.ru_stime.tv_sec - ru0.ru_stime.tv_sec)) * 1e3 +
                   ((ru1.ru_utime.tv_usec - ru0.ru_utime.tv_usec) + (ru1.ru_stime.tv_usec - ru0.ru_stime.tv_usec)) * 1e-3;
    kv("lat_outcome=%s lat_rc=%d lat_reps_done=%d lat_iters=%d lat_wall_ms=%.1f lat_cpu_ms=%.1f", latOutcome, latRc,
       repsDone, latIters, wallMs, cpuMs);
    if (rank == 0 && repsDone > 0) {
      size_t n = (size_t)repsDone * latIters;
      const char* rawPath = getenv("GIN_LAT_RAW");
      if (rawPath) {
        FILE* f = fopen(rawPath, "w");
        if (f) { for (size_t i = 0; i < n; i++) fprintf(f, "%zu,%llu\n", i, lat[i]); fclose(f); }
      }
      std::vector<unsigned long long> v(lat.begin(), lat.begin() + n);
      qsort(v.data(), n, sizeof(unsigned long long), cmpU64);
      double sum = 0; for (size_t i = 0; i < n; i++) sum += (double)v[i];
      auto q = [&](double p) { size_t k = (size_t)(p * (n - 1) + 0.5); return v[k] / 1e3; };
      kv("lat_n=%zu lat_min_us=%.2f lat_p50_us=%.2f lat_p90_us=%.2f lat_p99_us=%.2f lat_p999_us=%.2f lat_max_us=%.2f lat_mean_us=%.2f",
         n, v[0] / 1e3, q(0.5), q(0.9), q(0.99), q(0.999), v[n - 1] / 1e3, sum / n / 1e3);
    }
    if (rank == 1 && repsDone == latReps) {
      CK(cudaMemcpy(hbuf, R.d_recv, bytes, cudaMemcpyDeviceToHost));
      size_t bad = 0;
      for (size_t i = 0; i < bytes; i++) if (hbuf[i] != pat(0, i)) bad++;
      kv("lat_data_bad=%zu data_check=%s", bad, bad ? "mismatch" : "ok");
    }
    CK(cudaFree(d_lat));
    mon.stop.store(true);
    monTh.join();
    int ec = (strcmp(latOutcome, "ok") == 0) ? 0 : (strcmp(latOutcome, "hang") == 0 ? 7 : 2);
    kv("iters_ok=%d init_outcome=%s data_check=n/a silent_success=0 host_error=none host_error_ms=-1.0",
       repsDone * latIters, latOutcome);
    _teardownExit(ec);
  }

  R.recvOff = isRemAccess ? (size_t)64 * 1024 * 1024 : 0;
  int okIters = 0;
  int exitCode = 0;
  const char* outcome = "ok";
  const char* dataCheck = "n/a";
  int silent = 0;
  bool peerGone = false;
  int rearmsTotal = 0, recoveredIters = 0;

  if (rank == 0) {
    // =========================== sender ===========================
    for (int it = 0; it < iters; it++) {
      if (g_oob.send(M_BAR, it)) { peerGone = true; fprintf(stderr, "[rank0] peer gone at it %d (send)\n", it); break; }
      Msg m; memset(&m, 0, sizeof(m)); int got = 0;
      double bdl = monoMs() + (R.blockCapS + 10.0) * 1e3;
      while (true) {
        got = g_oob.recv(&m, 200);
        if (got < 0) break;
        if (got == 1 && m.type == M_BAR_ACK && m.iter == it) break;
        if (got == 1 && m.type == M_FAIL) break;
        if (got == 1) fprintf(stderr, "[rank0] it %d: unexpected %s(%d) at barrier\n", it, msgName(m.type), m.iter);
        if (monoMs() > bdl) { got = -2; break; }
      }
      if (got == -1) { peerGone = true; fprintf(stderr, "[rank0] peer gone at it %d\n", it); break; }
      if (got == -2) { outcome = "barrier_timeout"; exitCode = 7; break; }
      if (m.type == M_FAIL) { outcome = "peer_failed"; exitCode = 5; kv("peer_fail_it=%d reason=%d", m.iter, m.arg); break; }

      for (size_t i = 0; i < bytes; i++) hbuf[i] = pat(it, i);
      CK(cudaMemcpy(R.d_send, hbuf, bytes, cudaMemcpyHostToDevice));
      CK(cudaDeviceSynchronize());
      if (isRemAccess && it == 0) kv("fault_mono_ms=%.3f", monoMs());
      double tStart = relMs(), tRet = 0;
      int rc = runPut(R, it, 1, &tRet);
      double dt = relMs() - tStart;
      if (rc < 0) {
        kv("iters_ok_before=%d %s_it=%d %s_ms=%.1f phase=%d", okIters, useTimeout ? "timeout" : "hang", it,
           useTimeout ? "timeout" : "hang", dt, *R.h_phase);
        outcome = useTimeout ? "timeout" : "hang_killed"; exitCode = useTimeout ? 4 : 7;
        break;
      }
      if (rc == (int)ncclRemoteError && R.recOn) {
        fprintf(stderr, "[rank0] it %d device flush returned ncclRemoteError (%.1f ms); recovering\n", it, dt);
        if (senderRecover(R, it, tRet)) { recoveredIters++; okIters++; kv("okit=%d rec=1", okIters); continue; }
        outcome = "declined"; exitCode = 9;
        break;
      }
      if (rc != (int)ncclSuccess && rc != (int)ncclTimeout) {
        kv("iters_ok_before=%d device_rc=%s device_rc_it=%d device_rc_mono_ms=%.3f device_rc_ms=%.1f", okIters,
           ncclGetErrorString((ncclResult_t)rc), it, monoMs(), dt);
        outcome = "error"; exitCode = 8;
        break;
      }
      if (rc == (int)ncclTimeout) {
        kv("iters_ok_before=%d device_rc=ncclTimeout timeout_ms=%.1f", okIters, dt);
        outcome = "timeout"; exitCode = 4;
        break;
      }
      okIters++;
      kv("okit=%d", okIters);
      if ((it % 20) == 0 || it == iters - 1) fprintf(stderr, "[rank0] it %3d ok (%.3f ms)\n", it, dt);
      if (R.recOn && std::find(d0Iters.begin(), d0Iters.end(), it) != d0Iters.end()) {
        fprintf(stderr, "[rank0] it %d: forced recovery test (D0)\n", it);
        if (!senderRecover(R, it, tRet, /*forced=*/true)) { outcome = "declined"; exitCode = 9; break; }
      }
      if (gapMs > 0) usleep(gapMs * 1000);
    }

    // F4: the barrier failed because rank 1 was SIGKILLed. Drain puts so the RDMA fault surfaces.
    if (isProcKill && peerGone && exitCode == 0) {
      fprintf(stderr, "[rank0] F4 drain: peer gone, putting to dead QP to surface the RDMA fault\n");
      double drainT0 = relMs();
      int drc = ncclSuccess;
      for (int j = 0; j < 60; j++) {
        double tRet = 0;
        drc = runPut(R, -1, 1, &tRet);
        if (drc == (int)ncclRemoteError) {
          kv("device_rc=%s device_rc_it=drain%d device_rc_mono_ms=%.3f", ncclGetErrorString((ncclResult_t)drc), j, tRet);
          if (R.recOn) {
            senderRecover(R, iters + j, tRet);   // policy: RETRY_EXC with a dead peer -> declined
            outcome = "declined"; exitCode = 9;
          } else {
            outcome = "error"; exitCode = 8;
          }
          break;
        }
        if (mon.firstMs.load() >= 0) { outcome = "error"; exitCode = 3; break; }
        if (drc < 0 || drc == (int)ncclTimeout) { outcome = "timeout"; exitCode = 4; break; }
        if (drc != (int)ncclSuccess) { outcome = "error"; exitCode = 3; break; }
        usleep(20 * 1000);
      }
      kv("drain_device_rc=%d drain_ms=%.1f drain_outcome=%s", drc, relMs() - drainT0, outcome);
    }
  } else {
    // =========================== receiver ===========================
    int lastDone = -1;
    bool failed = false;
    for (int it = 0; it < iters && !failed; it++) {
      // barrier (serve late REQ for the operation just completed, DONE, FAIL)
      Msg m; memset(&m, 0, sizeof(m)); int got = 0;
      double bdl = monoMs() + (R.blockCapS + 10.0) * 1e3;
      bool recovering = false;
      while (true) {
        got = g_oob.recv(&m, 200);
        if (got < 0) break;
        if (got == 0) { if (monoMs() > bdl) { got = -2; break; } continue; }
        if (m.type == M_BAR && m.iter == it) break;
        if (m.type == M_REQ) { receiverHandleReq(R, m, it, lastDone, &recovering); continue; }
        if (m.type == M_DONE) { kv("rxdone it=%d d=%d t=%.3f", m.iter, m.arg, monoMs()); continue; }
        if (m.type == M_FAIL) { failed = true; break; }
        fprintf(stderr, "[rank1] it %d: unexpected %s(%d) at barrier\n", it, msgName(m.type), m.iter);
      }
      if (got == -1) { peerGone = true; fprintf(stderr, "[rank1] peer gone at it %d\n", it); break; }
      if (got == -2) { outcome = "barrier_timeout"; exitCode = 7; break; }
      if (failed) { outcome = "declined"; exitCode = 9; kv("rx_declined_it=%d reason=%d at=barrier", m.iter, m.arg); break; }
      // Poison before acknowledging the barrier: the sender may put as soon as it has the ack. (The
      // Q4 driver poisoned after the ack; a slow first cudaMemset could then overwrite data that had
      // already landed while the signal said "done".)
      CK(cudaMemset(R.d_recv, (int)POISON, bytes));
      CK(cudaDeviceSynchronize());
      if (g_oob.send(M_BAR_ACK, it)) { peerGone = true; break; }
      const unsigned long long expected = R.sigBase + (unsigned long long)(it + 1);
      *R.h_rc = 123456;
      waitKernel<<<1, 1, 0, R.st>>>(0, expected, R.devComm, useTimeout ? 1 : 0, R.timeoutCycles, R.d_rc, R.d_sig);
      CK(cudaGetLastError());
      if (it == g_stallIter) doStall("iter", it);   // live_peer: rank 0's put of this iteration lands while we are stopped
      const double tStart = relMs();
      const double iterCap = useTimeout ? R.rxCapS : R.blockCapS;
      int rearms = 0;
      bool cancelled = false, done = false;
      while (!done) {
        cudaError_t q = cudaStreamQuery(R.st);
        if (q != cudaSuccess && q != cudaErrorNotReady) { kv("cuda_error=%s", cudaGetErrorString(q)); exitCode = 6; outcome = "error"; done = true; break; }
        if (q == cudaSuccess) {
          int rc = *R.h_rc;
          if (cancelled) { outcome = "declined"; exitCode = 9; done = true; break; }
          if (rc == (int)ncclTimeout) {
            // Device timeout: re-arm while the peer is alive (it may be detecting / recovering).
            if (R.recOn && g_oob.peerAlive() && (relMs() - tStart) / 1e3 < iterCap) {
              rearms++;
              *R.h_rc = 123456;
              waitKernel<<<1, 1, 0, R.st>>>(0, expected, R.devComm, 1, R.timeoutCycles, R.d_rc, R.d_sig);
              CK(cudaGetLastError());
              continue;
            }
            CK(cudaMemcpy(hbuf, R.d_recv, bytes, cudaMemcpyDeviceToHost));
            size_t bad = 0, poisoned = 0;
            for (size_t i = 0; i < bytes; i++) { if (hbuf[i] != pat(it, i)) bad++; if (hbuf[i] == POISON) poisoned++; }
            dataCheck = (bad == 0) ? "ok" : (poisoned == bytes) ? "missing" : "mismatch";
            kv("iters_ok_before=%d device_rc=ncclTimeout timeout_ms=%.1f recv_signal=%llu data_check=%s", okIters,
               relMs() - tStart, *R.h_sig, dataCheck);
            outcome = "timeout"; exitCode = 4; done = true; break;
          }
          if (rc != (int)ncclSuccess) {
            kv("iters_ok_before=%d device_rc=%s", okIters, ncclGetErrorString((ncclResult_t)rc));
            outcome = "error"; exitCode = 8; done = true; break;
          }
          // success: bit-exact data and an exact signal (a double-counted ADD would exceed it)
          const double tWaitDone = monoMs();
          CK(cudaMemcpy(hbuf, R.d_recv, bytes, cudaMemcpyDeviceToHost));
          size_t bad = 0, first = 0, poisoned = 0;
          for (size_t i = 0; i < bytes; i++) { if (hbuf[i] != pat(it, i)) { if (!bad) first = i; bad++; } if (hbuf[i] == POISON) poisoned++; }
          const unsigned long long sig = *R.h_sig;
          if (bad || sig != expected) {
            dataCheck = bad ? ((poisoned == bytes) ? "missing" : "mismatch") : "signal_not_exact";
            silent = bad ? 1 : 0;
            fprintf(stderr, "[rank1] it %d CHECK FAILED: %zu/%zu bytes bad (first=%zu) sig=%llu expected=%llu\n", it,
                    bad, bytes, first, sig, expected);
            kv("iters_ok_before=%d data_bad=%zu data_total=%zu recv_signal=%llu expected_signal=%llu check=%s", okIters,
               bad, bytes, sig, expected, dataCheck);
            g_oob.send(M_FAIL, it, 9);
            outcome = "error"; exitCode = 5; done = true; break;
          }
          dataCheck = "ok";
          okIters++;
          lastDone = it;
          if (recovering || rearms) { recoveredIters++; kv("rxok it=%d recovered=%d rearms=%d t_verified=%.3f", it, recovering ? 1 : 0, rearms, tWaitDone); }
          kv("okit=%d", okIters);
          if ((it % 20) == 0 || it == iters - 1) fprintf(stderr, "[rank1] it %3d ok, data exact\n", it);
          done = true;
          break;
        }
        // kernel still running: serve the OOB channel
        got = g_oob.recv(&m, 0);
        if (got == 1) {
          if (m.type == M_REQ) receiverHandleReq(R, m, it, lastDone, &recovering);
          else if (m.type == M_DONE) kv("rxdone it=%d d=%d t=%.3f", m.iter, m.arg, monoMs());
          else if (m.type == M_FAIL) {
            failed = true;
            kv("rx_declined_it=%d reason=%d at=wait", m.iter, m.arg);
            fprintf(stderr, "[rank1] it %d: sender declined recovery; releasing own waiter\n", it);
            receiverCancel(R);
            cancelled = true;
          } else fprintf(stderr, "[rank1] it %d: unexpected %s(%d) during wait\n", it, msgName(m.type), m.iter);
        } else if (got < 0 && !peerGone) {
          peerGone = true;
          fprintf(stderr, "[rank1] it %d: peer gone during wait; releasing own waiter\n", it);
          receiverCancel(R);
          cancelled = true;
        }
        if ((relMs() - tStart) / 1e3 > iterCap + 5.0) {
          kv("iters_ok_before=%d hang_it=%d hang_ms=%.1f", okIters, it, relMs() - tStart);
          outcome = "hang_killed"; exitCode = 7; done = true; break;
        }
        usleep(200);
      }
      rearmsTotal += rearms;
      if (exitCode != 0) break;
      if (gapMs > 0) usleep(gapMs * 1000);
    }
    // final signal: base + iters exactly (no loss, no double count)
    if (exitCode == 0 && !peerGone) {
      *R.h_sig2 = 0;
      readSigKernel<<<1, 1, 0, R.side>>>(0, R.devComm, R.d_sig2);
      CK(cudaStreamSynchronize(R.side));
      kv("final_signal=%llu expected_final=%llu signal_exact=%d", *R.h_sig2, R.sigBase + (unsigned long long)iters,
         *R.h_sig2 == R.sigBase + (unsigned long long)iters ? 1 : 0);
      if (*R.h_sig2 != R.sigBase + (unsigned long long)iters) { outcome = "error"; exitCode = 5; }
    }
    kv("rearms=%d", rearmsTotal);
  }

  if (okIters < iters && mon.firstMs.load() < 0 && postPollS > 0 && exitCode != 9) {
    double pp0 = nowSec();
    while (nowSec() - pp0 < postPollS && mon.firstMs.load() < 0) usleep(20000);
    kv("post_poll_ms=%.1f", (nowSec() - pp0) * 1e3);
  }

  mon.stop.store(true);
  monTh.join();
  ncclResult_t finalAsync = ncclSuccess;
  ncclCommGetAsyncError(g_comm, &finalAsync);
  double hostErrMs = mon.firstMs.load();
  ncclResult_t hostErr = (ncclResult_t)mon.firstErr.load();
  kv("iters_ok=%d init_outcome=%s data_check=%s silent_success=%d host_error=%s host_error_ms=%.1f final_async=%s "
     "rec_events=%d recovered_ops=%d replays=%d delta_zero=%d recovered_iters=%d decline_reason=%s",
     okIters, outcome, dataCheck, silent, (hostErrMs >= 0 ? ncclGetErrorString(hostErr) : "none"), hostErrMs,
     ncclGetErrorString(finalAsync), R.nRecEvents, R.nRecovered, R.nReplays, R.nDeltaZero, recoveredIters,
     R.declineReason ? R.declineReason : "none");
  fprintf(stderr, "[rank%d] DONE okIters=%d/%d outcome=%s data=%s recovered=%d events=%d final_async=%s exit=%d\n", rank,
          okIters, iters, outcome, dataCheck, R.nRecovered, R.nRecEvents, ncclGetErrorString(finalAsync), exitCode);
  _teardownExit(exitCode);
  return exitCode;
}
