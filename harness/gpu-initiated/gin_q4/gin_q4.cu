// gin_q4.cu - 2-rank NCCL GIN fault driver, Q4 edition.
//
// Copied from ../gin/gin_fault.cu (Q2 driver) and extended for the Q4 prototype
// (device-side CQE classification + host mailbox, gin_q4_classify.diff in this directory):
//   * blocking mode records the return code of the blocking gin.flush(), which the Q4
//     patch makes return ncclRemoteError for an operation that completed with an error
//     CQE (stock: always success) -> exit code 8 "device reported a classified error";
//   * a %globaltimer <-> CLOCK_MONOTONIC calibration (gt_off_ns) so the device detection
//     time in the mailbox record can be placed on the host clock;
//   * ncclCommGetAsyncError poll period GIN_ASYNC_POLL_US (default 2000 us);
//   * fault "lat": no fault, per-iteration latency of put+signal+flush measured on the
//     GPU with %globaltimer (GIN_LAT_ITERS x GIN_LAT_REPS), for the overhead comparison.
// Everything else (bootstrap, lockstep barrier, F2/F4 handling, watchdogs, exit codes) is
// the Q2 driver's; see the original header below.
//
// ---- original header (gin_fault.cu) ----
// gin_fault.cu - 2-rank NCCL GIN (GPU-initiated networking) fault driver.
//
// Answers Q2 of the GPU-initiated RDMA study for NCCL GIN, on both backends
// (proxy and GDAKI, selected with NCCL_GIN_TYPE). rank 0 (rain, initiator)
// repeatedly `put`s M bytes into rank 1's (sunny, target) symmetric window and
// signals; rank 1 waits for the signal and byte-compares; rank 0 waits for its
// own local completion (flush). A fault is injected mid-run (see the fault
// catalog in ../DESIGN.md); the driver measures which layer notices, whether
// the device wait times out / hangs / falsely succeeds, whether the delivered
// data is intact, how long until the host learns via ncclCommGetAsyncError, and
// whether teardown (ncclCommAbort on a non-blocking comm) returns.
//
// House style follows ../../nccl-integration/nccl_ar2.cu: TCP bootstrap of the
// ncclUniqueId, NaN/poison-filled receive buffer, exact per-byte compare, every
// wait bounded (device *Timeout variants OR a host watchdog), abort under an
// alarm watchdog.
//
// Two wait modes:
//   timeout  - the device API's *Timeout variants (bounded on the GPU).
//   blocking - the plain waits (unbounded on the GPU; the library gives user
//              devComms no abort flag, so these can only be bounded by the host
//              watchdog killing the process).
//
// Bootstrap runs on the management network (eno1); NCCL's own out-of-band
// bootstrap is pinned to it with NCCL_SOCKET_IFNAME=eno1 (set by the runner) so
// it never rides the RoCE link that carries the user's NVMe-oF storage. The GIN
// data path uses NCCL_IB_HCA (mlx5_1 on rain / mlx5_0 on sunny).
//
// Exit codes (initiator-centric; the receiver uses the same scheme):
//   0 all iterations ok, 1 usage/setup, 2 NCCL call error, 3 async NCCL error,
//   4 device wait timed out, 5 data mismatch/missing, 6 CUDA error,
//   7 watchdog fired (device wait or teardown hung),
//   8 device wait returned ncclRemoteError (Q4 classified error CQE).
//
// usage:
//   gin_q4 <rank 0|1> <rank0_mgmt_ip> <tcp_port> <iters> <bytes>
//          <timeout|blocking> <none|F1|F2|F3|F4|lat> <dev_timeout_s>
//          <host_watchdog_s> <out_kv_file> [gap_ms]

#include <nccl.h>
#include "nccl_device.h"
#include <cuda_runtime.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cstdint>
#include <cstdarg>
#include <ctime>
#include <atomic>
#include <thread>
#include <unistd.h>
#include <csignal>
#include <climits>
#include <vector>
#include <algorithm>
#include <sys/resource.h>
#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <sys/socket.h>

static const int NRANKS = 2;
static int g_rank = -1;
static FILE* g_kv = nullptr;             // KEY=VALUE results file for the runner
static ncclComm_t g_comm = nullptr;
static int g_sock = -1;                  // management-net TCP socket to the peer
static const uint8_t POISON = 0xA5;      // receive-buffer fill; "missing" == all bytes still POISON

// ---- small helpers --------------------------------------------------------
static double nowSec() {
  struct timespec t;
  clock_gettime(CLOCK_MONOTONIC, &t);
  return t.tv_sec + t.tv_nsec * 1e-9;
}
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

#define CK(c) do { cudaError_t e_ = (c); if (e_ != cudaSuccess) { \
  fprintf(stderr, "[rank%d] CUDA %s:%d %s\n", g_rank, __FILE__, __LINE__, cudaGetErrorString(e_)); \
  kv("cuda_error=%s", cudaGetErrorString(e_)); _teardownExit(6); } } while (0)
#define NK(c) do { ncclResult_t r_ = (c); if (r_ != ncclSuccess && r_ != ncclInProgress) { \
  fprintf(stderr, "[rank%d] NCCL %s:%d %s\n", g_rank, __FILE__, __LINE__, ncclGetErrorString(r_)); \
  kv("nccl_error=%s", ncclGetErrorString(r_)); _teardownExit(2); } } while (0)

static void _teardownExit(int code);      // fwd

static int sendall(int fd, const void* b, size_t n) {
  const char* p = (const char*)b; size_t o = 0;
  while (o < n) { ssize_t k = send(fd, p + o, n - o, 0); if (k <= 0) return -1; o += (size_t)k; }
  return 0;
}
static int recvall(int fd, void* b, size_t n) {
  char* p = (char*)b; size_t o = 0;
  while (o < n) { ssize_t k = recv(fd, p + o, n - o, 0); if (k <= 0) return -1; o += (size_t)k; }
  return 0;
}

// Deterministic per-(iter,byte) pattern; poison never matches it.
static inline uint8_t pat(int it, size_t idx) {
  uint32_t h = (uint32_t)(idx * 2654435761u) ^ (uint32_t)(it * 40503u + 0x9e3779b9u);
  h ^= h >> 13;
  return (uint8_t)(h & 0xff);
}

// ---- non-blocking comm progress ------------------------------------------
// With config.blocking=0 all NCCL calls (except Destroy/Abort) may return
// ncclInProgress; spin on ncclCommGetAsyncError until the op settles. Bounded
// by the host watchdog thread.
static ncclResult_t commPoll(ncclComm_t comm) {
  ncclResult_t s = ncclInProgress;
  while (s == ncclInProgress) {
    if (ncclCommGetAsyncError(comm, &s) != ncclSuccess) return ncclInternalError;
  }
  return s;
}

// ---- host watchdog --------------------------------------------------------
static std::atomic<int> g_phase{0};        // 0 setup, 1 running, 2 teardown
// Teardown timing. Both ranks print how long ncclCommAbort took, or that it did not
// return within GIN_ABORT_WATCHDOG_S (alarm) or before the global deadline.
static std::atomic<double> g_abortT0{-1.0};  // relMs() when ncclCommAbort was called; -1 = not running
static int g_kvFd = -1;                      // g_kv's descriptor, for the write()-only reporters
static char g_abortHangMsg[128], g_abortHangKv[96];   // prebuilt: the alarm handler may not format
static size_t g_abortHangMsgLen = 0, g_abortHangKvLen = 0;
static size_t clampLen(int n, size_t cap) { return n < 0 ? 0 : ((size_t)n < cap ? (size_t)n : cap - 1); }
static void abortAlarm(int) {
  static const char m[] = "WATCHDOG: abort/teardown did not return; exiting 7\n";
  ssize_t w = write(2, m, sizeof(m) - 1); (void)w;
  if (g_abortHangMsgLen) { w = write(2, g_abortHangMsg, g_abortHangMsgLen); (void)w; }
  if (g_kvFd >= 0 && g_abortHangKvLen) { w = write(g_kvFd, g_abortHangKv, g_abortHangKvLen); (void)w; }
  _exit(7);
}

// Attempt an orderly teardown, bounded by an alarm. Records whether abort
// returned. Called on every exit path.
static void _teardownExit(int code) {
  static std::atomic<int> once{0};
  if (once.fetch_add(1) != 0) _exit(code);   // reentrancy guard
  g_phase.store(2);
  if (g_comm) {
    const char* wd = getenv("GIN_ABORT_WATCHDOG_S");
    unsigned s = wd ? (unsigned)atoi(wd) : 15u;
    g_abortHangMsgLen = clampLen(snprintf(g_abortHangMsg, sizeof g_abortHangMsg,
                                          "[rank%d] ncclCommAbort did not return within %u s\n", g_rank, s),
                                 sizeof g_abortHangMsg);
    g_abortHangKvLen = clampLen(snprintf(g_abortHangKv, sizeof g_abortHangKv,
                                         "teardown=hang teardown_bound_s=%u\n", s), sizeof g_abortHangKv);
    g_kvFd = g_kv ? fileno(g_kv) : -1;
    signal(SIGALRM, abortAlarm);
    alarm(s);
    double a0 = relMs();
    g_abortT0.store(a0);
    ncclResult_t ar = ncclCommAbort(g_comm);   // safe on a non-blocking comm
    alarm(0);
    g_abortT0.store(-1.0);
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
// rank 0: one put + weak-signal-increment to rank 1, then flush (local
// completion). signalIndex 0, single CTA, single GIN context.
__global__ void putKernel(ncclWindow_t sendWin, size_t sendOff,
                          ncclWindow_t recvWin, size_t recvOff, size_t bytes,
                          unsigned signalIndex, struct ncclDevComm devComm,
                          int useTimeout, unsigned long long timeoutCycles, int* d_rc,
                          volatile int* d_phase) {
  ncclGin gin{devComm, 0};
  // Phase marker in mapped host memory (1 = in put, 2 = in flush, 3 = done) so the host can
  // tell where a kernel that never returns is stuck.
  if (d_phase) { *d_phase = 1; __threadfence_system(); }
  gin.put(ncclTeamWorld(devComm), 1, recvWin, recvOff, sendWin, sendOff, bytes,
          ncclGin_WeakSignalInc{signalIndex});
  if (d_phase) { *d_phase = 2; __threadfence_system(); }
  ncclResult_t rc = ncclSuccess;
  if (useTimeout) {
    rc = gin.flush(ncclCoopCta(), cuda::memory_order_acquire, ncclGin_None{}, timeoutCycles);
  } else {
    // unbounded; only the host watchdog bounds it. With the Q4 patch the blocking flush
    // returns ncclRemoteError for an op that completed with an error CQE (flag on); stock
    // (flag off) it always returns ncclSuccess.
    rc = gin.flush(ncclCoopCta());
  }
  if (d_phase) { *d_phase = 3; __threadfence_system(); }
  if (threadIdx.x == 0) *d_rc = (int)rc;
}

__device__ __forceinline__ unsigned long long gtNow() {
  unsigned long long t;
  asm volatile("mov.u64 %0, %%globaltimer;" : "=l"(t));
  return t;
}

// %globaltimer publisher for the host-side clock calibration.
__global__ void gtKernel(volatile unsigned long long* out, volatile int* stop) {
  while (!*stop) {
    *out = gtNow();
    __threadfence_system();
  }
}

// Overhead ("lat"): n x (put + weak-signal-inc + flush), per-iteration latency on the GPU clock.
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

// Read the current value of a GIN signal into the mailbox (used once to grab a
// base, because signals are cumulative / not reset to 0 at devComm creation).
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

// ================= main ====================================================
struct AsyncMon {                          // background ncclCommGetAsyncError poller
  ncclComm_t comm;
  std::atomic<bool> stop{false};
  std::atomic<int> firstErr{(int)ncclSuccess};
  std::atomic<double> firstMs{-1.0};
};
static void asyncMonRun(AsyncMon* m) {
  const char* pu = getenv("GIN_ASYNC_POLL_US");
  useconds_t pollUs = pu ? (useconds_t)atoi(pu) : 2000u;
  while (!m->stop.load()) {
    ncclResult_t s = ncclSuccess;
    if (ncclCommGetAsyncError(m->comm, &s) == ncclSuccess) {
      if (s != ncclSuccess && s != ncclInProgress && m->firstMs.load() < 0) {
        m->firstErr.store((int)s);
        m->firstMs.store(relMs());
      }
    }
    usleep(pollUs);
  }
}

// %globaltimer - CLOCK_MONOTONIC offset (ns). A kernel publishes %globaltimer to mapped host
// memory continuously; a value g read by the host at t2 was written at some host time <= t2, so
// off = g - t_write >= g - t2. The max over samples is the estimate (error ~ write period +
// PCIe latency, a few us). Returns 0 on failure.
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

int main(int argc, char** argv) {
  g_t0 = nowSec();
  if (argc < 11) {
    fprintf(stderr, "usage: %s <rank 0|1> <rank0_ip> <port> <iters> <bytes> "
                    "<timeout|blocking> <none|F1|F2|F3|F4|lat> <dev_timeout_s> "
                    "<host_watchdog_s> <out_kv_file>\n", argv[0]);
    return 1;
  }
  int rank        = atoi(argv[1]); g_rank = rank;
  const char* peer= argv[2];
  int port        = atoi(argv[3]);
  int iters       = atoi(argv[4]);
  size_t bytes    = strtoul(argv[5], nullptr, 10);
  bool useTimeout = strcmp(argv[6], "timeout") == 0;
  const char* fault = argv[7];
  double devTimeoutS = atof(argv[8]);
  double watchdogS   = atof(argv[9]);
  g_kv = fopen(argv[10], "w");
  int gapMs = (argc > 11) ? atoi(argv[11]) : 0;   // inter-iteration pacing so a fault lands mid-run
  // In blocking mode the device wait is unbounded; cap each op below the global
  // watchdog so we can still record the hang AND test whether abort returns.
  // blocking-mode per-op cap (the device wait itself is unbounded) and the
  // post-fault host polling window (keep ncclCommGetAsyncError running after a
  // device timeout / peer loss so a slow host-side detector -- e.g. GDAKI's
  // 10 s QP-state check -- still gets a chance to report before teardown).
  double blockCapS = getenv("GIN_BLOCK_CAP_S") ? atof(getenv("GIN_BLOCK_CAP_S")) : 25.0;
  double postPollS = getenv("GIN_POST_POLL_S") ? atof(getenv("GIN_POST_POLL_S")) : 15.0;
  kv("t0_mono_ms=%.3f block_cap_s=%.1f post_poll_s=%.1f", g_t0 * 1e3, blockCapS, postPollS);

  if ((rank != 0 && rank != 1) || iters <= 0 || bytes == 0) { fprintf(stderr, "bad args\n"); return 1; }
  bool isRemAccess = strcmp(fault, "F2") == 0;   // put past the end of the remote window (no patch)
  bool isProcKill  = strcmp(fault, "F4") == 0;   // drain puts to the killed peer to surface RETRY_EXC
  bool isLat       = strcmp(fault, "lat") == 0;  // Q4 overhead: per-iteration latency, no fault
  kv("rank=%d bytes=%zu iters=%d wait_mode=%s fault=%s dev_timeout_s=%.1f", rank, bytes, iters, argv[6], fault, devTimeoutS);

  // ---- global host watchdog: bound the whole run no matter what hangs -----
  std::thread([watchdogS]() {
    double deadline = nowSec() + watchdogS;
    while (nowSec() < deadline) usleep(50000);
    static const char m[] = "WATCHDOG: global deadline exceeded; exiting 7\n";
    ssize_t w = write(2, m, sizeof(m) - 1); (void)w;
    double a0 = g_abortT0.load();
    if (a0 >= 0) {                         // the deadline cut a running ncclCommAbort
      char b[160];
      double ran = relMs() - a0;
      size_t n = clampLen(snprintf(b, sizeof b, "[rank%d] ncclCommAbort did not return within %.1f ms "
                                   "(global watchdog)\n", g_rank, ran), sizeof b);
      w = write(2, b, n); (void)w;
      if (g_kvFd >= 0) {
        n = clampLen(snprintf(b, sizeof b, "teardown=hang teardown_ms=%.1f teardown_cut_by=global_watchdog\n",
                              ran), sizeof b);
        w = write(g_kvFd, b, n); (void)w;
      }
    }
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

  // ---- clock offset between the two hosts' CLOCK_MONOTONIC ----------------
  // NTP-style ping-pong over the management socket; keep the min-RTT sample.
  // offset = rank1_clock - rank0_clock (ms), so t_rank0 = t_rank1 - offset.
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

  // Connectivity self-test: exchange the id over TCP only, then exit before any
  // RoCE/NCCL init (so it needs no cluster lock).
  if (getenv("GIN_BOOTSTRAP_TEST")) {
    fprintf(stderr, "[rank%d] bootstrap ok (id exchanged over TCP)\n", rank);
    kv("bootstrap=ok");
    return 0;
  }

  CK(cudaSetDevice(0));
  {
    // Q4: place %globaltimer (device detection stamps in the mailbox records) on CLOCK_MONOTONIC.
    double spreadUs = 0;
    long long gtOff = calibrateGlobalTimer(&spreadUs);
    kv("gt_off_ns=%lld gt_cal_spread_us=%.1f", gtOff, spreadUs);
    fprintf(stderr, "[rank%d] globaltimer offset %lld ns (spread %.1f us)\n", rank, gtOff, spreadUs);
  }
  int clockKHz = 0; CK(cudaDeviceGetAttribute(&clockKHz, cudaDevAttrClockRate, 0));
  unsigned long long timeoutCycles = (unsigned long long)(devTimeoutS * clockKHz * 1000.0);

  // Communicator. The 2.32 docs recommend a non-blocking comm so ncclCommAbort
  // is safe at any point; but non-blocking symmetric-window registration is
  // finicky (every call must be drained), so we default to a blocking comm
  // (as the shipped GIN example does) and bound ncclCommAbort with the alarm
  // watchdog instead. Set GIN_NONBLOCKING=1 to force non-blocking.
  bool nonblocking = getenv("GIN_NONBLOCKING") != nullptr;
  ncclConfig_t cfg = NCCL_CONFIG_INITIALIZER;
  cfg.blocking = nonblocking ? 0 : 1;
  NK(ncclCommInitRankConfig(&g_comm, NRANKS, id, rank, &cfg));
  if (nonblocking && commPoll(g_comm) != ncclSuccess) { kv("init_outcome=error"); _teardownExit(2); }
  kv("comm_blocking=%d", cfg.blocking);
  fprintf(stderr, "[rank%d] comm ready (blocking=%d)\n", rank, cfg.blocking);

  // Verify GIN is actually active and which backend.
  ncclCommProperties_t props = NCCL_COMM_PROPERTIES_INITIALIZER;
  NK(ncclCommQueryProperties(g_comm, &props));
  if (!props.deviceApiSupport || props.ginType == NCCL_GIN_TYPE_NONE) {
    fprintf(stderr, "[rank%d] GIN not available (deviceApi=%d ginType=%d)\n", rank, props.deviceApiSupport, props.ginType);
    kv("gin_available=0 gin_type=%d", props.ginType);
    _teardownExit(2);
  }
  kv("gin_available=1 gin_type=%d", props.ginType);      // 2=proxy 3=gdaki
  fprintf(stderr, "[rank%d] GIN active, ginType=%d\n", rank, props.ginType);

  // ---- symmetric memory + windows -----------------------------------------
  // recv window is exactly `bytes` so an F2 put at offset==bytes is fully OOB.
  void *d_send = nullptr, *d_recv = nullptr;
  NK(ncclMemAlloc(&d_send, bytes));
  NK(ncclMemAlloc(&d_recv, bytes));
  ncclWindow_t sendWin, recvWin;
  NK(ncclCommWindowRegister(g_comm, d_send, bytes, &sendWin, NCCL_WIN_COLL_SYMMETRIC));
  NK(ncclCommWindowRegister(g_comm, d_recv, bytes, &recvWin, NCCL_WIN_COLL_SYMMETRIC));

  cudaStream_t st; CK(cudaStreamCreateWithFlags(&st, cudaStreamNonBlocking));
  ncclDevComm devComm;
  ncclDevCommRequirements reqs = NCCL_DEV_COMM_REQUIREMENTS_INITIALIZER;
  reqs.worldGinBarrierCount = 1;
  reqs.ginSignalCount = 1;                 // signal index 0
  reqs.ginConnectionType = NCCL_GIN_CONNECTION_FULL;
  NK(ncclDevCommCreate(g_comm, &reqs, &devComm));
  fprintf(stderr, "[rank%d] devComm created (clock=%d kHz, timeoutCycles=%llu)\n", rank, clockKHz, timeoutCycles);

  // host + device staging buffers and a mapped mailbox for kernel results
  uint8_t* hbuf = (uint8_t*)malloc(bytes);
  int* h_rc; int* d_rc; unsigned long long* h_sig; unsigned long long* d_sig;
  CK(cudaHostAlloc((void**)&h_rc, sizeof(int), cudaHostAllocMapped));
  CK(cudaHostGetDevicePointer((void**)&d_rc, h_rc, 0));
  volatile int* h_phase; int* d_phase;
  CK(cudaHostAlloc((void**)&h_phase, sizeof(int), cudaHostAllocMapped));
  CK(cudaHostGetDevicePointer((void**)&d_phase, (void*)h_phase, 0));
  *h_phase = 0;
  CK(cudaHostAlloc((void**)&h_sig, sizeof(unsigned long long), cudaHostAllocMapped));
  CK(cudaHostGetDevicePointer((void**)&d_sig, h_sig, 0));

  // rank 1: grab the signal base once (signals are cumulative, not zeroed).
  unsigned long long sigBase = 0;
  if (rank == 1) {
    *h_sig = 0;
    readSigKernel<<<1, 1, 0, st>>>(0, devComm, d_sig);
    CK(cudaStreamSynchronize(st));
    sigBase = *h_sig;
    kv("signal_base=%llu", sigBase);
    fprintf(stderr, "[rank1] signal base=%llu\n", sigBase);
  }

  AsyncMon mon; mon.comm = g_comm;
  std::thread monTh(asyncMonRun, &mon);
  g_phase.store(1);

  if (isLat) {
    // ---- Q4 overhead: GIN_LAT_REPS x GIN_LAT_ITERS (put + signal + flush), no fault ----
    int latIters = getenv("GIN_LAT_ITERS") ? atoi(getenv("GIN_LAT_ITERS")) : 2000;
    int latReps = getenv("GIN_LAT_REPS") ? atoi(getenv("GIN_LAT_REPS")) : 5;
    if (latIters <= 0) latIters = 2000;
    if (latReps <= 0) latReps = 5;
    unsigned long long* d_lat = nullptr;
    CK(cudaMalloc((void**)&d_lat, sizeof(unsigned long long) * latIters));
    std::vector<unsigned long long> lat((size_t)latIters * latReps, 0ULL);
    if (rank == 0) {
      for (size_t i = 0; i < bytes; i++) hbuf[i] = pat(0, i);
      CK(cudaMemcpy(d_send, hbuf, bytes, cudaMemcpyHostToDevice));
    } else {
      CK(cudaMemset(d_recv, (int)POISON, bytes));
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
      *h_rc = 123456;
      if (rank == 0) {
        latKernel<<<1, 1, 0, st>>>(sendWin, recvWin, bytes, devComm, useTimeout ? 1 : 0, timeoutCycles, latIters, d_lat, d_rc);
      } else {
        waitKernel<<<1, 1, 0, st>>>(0, sigBase + (unsigned long long)(r + 1) * latIters, devComm, 1, timeoutCycles * 4, d_rc, d_sig);
      }
      CK(cudaGetLastError());
      double dl = nowSec() + (useTimeout ? devTimeoutS * 4 + 30.0 : blockCapS);
      bool to = false;
      while (true) { cudaError_t q = cudaStreamQuery(st); if (q == cudaSuccess) break; if (q != cudaErrorNotReady) { CK(q); } if (nowSec() > dl) { to = true; break; } usleep(200); }
      if (to) { latOutcome = "hang"; break; }
      latRc = *h_rc;
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
      fprintf(stderr, "[rank0] lat n=%zu p50=%.2f us p99=%.2f us max=%.2f us cpu=%.1f ms wall=%.1f ms\n", n, q(0.5), q(0.99),
              v[n - 1] / 1e3, cpuMs, wallMs);
    }
    if (rank == 1 && repsDone == latReps) {
      CK(cudaMemcpy(hbuf, d_recv, bytes, cudaMemcpyDeviceToHost));
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

  int okIters = 0;
  int exitCode = 0;
  const char* outcome = "ok";
  const char* dataCheck = "n/a";
  int silent = 0;
  bool peerGone = false;

  for (int it = 0; it < iters; it++) {
    // per-iteration host barrier over the management socket so both ranks
    // start the same iteration together and stay lockstep-alive (so F4's kill
    // lands while the peer is genuinely up). On peer death the barrier fails;
    // for F4 rank 0 then DRAINS extra puts to the dead peer (below) so the
    // RDMA-level fault surfaces on the initiator instead of being masked by the
    // TCP FIN.
    {
      char sync = (char)it;
      if (rank == 0) { if (sendall(g_sock, &sync, 1) || recvall(g_sock, &sync, 1)) { fprintf(stderr,"[rank0] peer gone at it %d\n", it); peerGone = true; break; } }
      else           { if (recvall(g_sock, &sync, 1) || sendall(g_sock, &sync, 1)) { fprintf(stderr,"[rank1] peer gone at it %d\n", it); peerGone = true; break; } }
    }

    *h_rc = 123456;                        // sentinel
    double tStart = relMs();

    if (rank == 0) {
      for (size_t i = 0; i < bytes; i++) hbuf[i] = pat(it, i);
      CK(cudaMemcpy(d_send, hbuf, bytes, cudaMemcpyHostToDevice));
      CK(cudaDeviceSynchronize());
      // F2 (rem_access): aim the data put far past the end of the remote MR.
      // ncclMemAlloc rounds the allocation up to the cuMem granularity (~2 MiB),
      // so a small overrun (offset==bytes) lands in valid-but-wrong memory and
      // raises NO protection error (silent loss). Use a 64 MiB offset so the
      // address is unambiguously outside the registered MR -> REM_ACCESS.
      size_t recvOff = isRemAccess ? (size_t)64 * 1024 * 1024 : 0;
      if (isRemAccess && it == 0) kv("fault_mono_ms=%.3f", nowSec() * 1e3);   // F2 fires with the first OOB put
      *h_phase = 0;
      putKernel<<<1, 1, 0, st>>>(sendWin, 0, recvWin, recvOff, bytes, 0, devComm, useTimeout ? 1 : 0, timeoutCycles, d_rc, d_phase);
    } else {
      CK(cudaMemset(d_recv, (int)POISON, bytes));   // poison so missing bytes never match
      CK(cudaDeviceSynchronize());
      waitKernel<<<1, 1, 0, st>>>(0, sigBase + (unsigned long long)(it + 1), devComm, useTimeout ? 1 : 0, timeoutCycles, d_rc, d_sig);
    }
    cudaError_t launchErr = cudaGetLastError();
    if (launchErr != cudaSuccess) { fprintf(stderr, "[rank%d] launch %s\n", rank, cudaGetErrorString(launchErr)); kv("cuda_error=%s", cudaGetErrorString(launchErr)); exitCode = 6; outcome = "error"; break; }

    // Bounded wait on the kernel: poll the stream, watch async error, cap time.
    double devDeadline = nowSec() + (useTimeout ? devTimeoutS + 5.0 : blockCapS);
    bool timedOut = false, hung = false;
    while (true) {
      cudaError_t q = cudaStreamQuery(st);
      if (q == cudaSuccess) break;
      if (q != cudaErrorNotReady) { fprintf(stderr, "[rank%d] it %d CUDA %s\n", rank, it, cudaGetErrorString(q)); kv("cuda_error=%s", cudaGetErrorString(q)); exitCode = 6; outcome = "error"; break; }
      if (nowSec() > devDeadline) { if (useTimeout) timedOut = true; else hung = true; break; }
      usleep(500);
    }
    if (exitCode == 6) break;

    double dt = relMs() - tStart;

    if (hung) {
      // blocking-mode device wait never returned: this is the hang result.
      fprintf(stderr, "[rank%d] it %d HANG: device wait did not return (blocking mode)\n", rank, it);
      kv("iters_ok_before=%d hang_it=%d hang_ms=%.1f hang_phase=%d", okIters, it, dt, rank == 0 ? *h_phase : -1);
      outcome = "hang_killed"; exitCode = 7;
      break;
    }
    if (timedOut) {
      fprintf(stderr, "[rank%d] it %d device-wait wrapper timed out\n", rank, it);
      kv("iters_ok_before=%d timeout_it=%d timeout_ms=%.1f timeout_phase=%d", okIters, it, dt, rank == 0 ? *h_phase : -1);
      outcome = "timeout"; exitCode = 4;
      break;
    }

    int rc = *h_rc;                         // ncclResult_t written by the kernel
    if (rc != (int)ncclSuccess && rc != (int)ncclTimeout) {
      // Q4: the device wait/flush returned an error (ncclRemoteError = classified error CQE).
      // The op is NOT counted as done, so it cannot be a silent success.
      fprintf(stderr, "[rank%d] it %d device wait returned %s (%.1f ms)\n", rank, it, ncclGetErrorString((ncclResult_t)rc), dt);
      kv("iters_ok_before=%d device_rc=%s device_rc_it=%d device_rc_mono_ms=%.3f device_rc_ms=%.1f", okIters,
         ncclGetErrorString((ncclResult_t)rc), it, nowSec() * 1e3, dt);
      outcome = "error"; exitCode = 8;
      break;
    }
    if (rc == (int)ncclTimeout) {
      fprintf(stderr, "[rank%d] it %d device wait returned ncclTimeout (%.1f ms)\n", rank, it, dt);
      kv("iters_ok_before=%d device_rc=ncclTimeout timeout_ms=%.1f", okIters, dt);
      outcome = "timeout"; exitCode = 4;
      // For the receiver, also record what data (if any) landed.
      if (rank == 1) {
        CK(cudaMemcpy(hbuf, d_recv, bytes, cudaMemcpyDeviceToHost));
        size_t bad = 0, poisoned = 0;
        for (size_t i = 0; i < bytes; i++) { if (hbuf[i] != pat(it, i)) bad++; if (hbuf[i] == POISON) poisoned++; }
        dataCheck = (bad == 0) ? "ok" : (poisoned == bytes) ? "missing" : "mismatch";
        kv("recv_signal=%llu data_bad=%zu data_total=%zu data_check=%s", *h_sig, bad, bytes, dataCheck);
      }
      break;
    }

    // Kernel's wait returned "success" (rc==ncclSuccess). Check the data.
    if (rank == 1) {
      CK(cudaMemcpy(hbuf, d_recv, bytes, cudaMemcpyDeviceToHost));
      size_t bad = 0, first = 0, poisoned = 0;
      for (size_t i = 0; i < bytes; i++) { if (hbuf[i] != pat(it, i)) { if (!bad) first = i; bad++; } if (hbuf[i] == POISON) poisoned++; }
      if (bad) {
        dataCheck = (poisoned == bytes) ? "missing" : "mismatch";
        silent = 1;                         // wait said success but data is wrong
        fprintf(stderr, "[rank%d] it %d SILENT-SUCCESS: wait ok but %zu/%zu bytes bad (first=%zu) sig=%llu\n",
                rank, it, bad, bytes, first, *h_sig);
        kv("iters_ok_before=%d data_bad=%zu data_total=%zu recv_signal=%llu silent=1", okIters, bad, bytes, *h_sig);
        outcome = "error"; exitCode = 5;
        break;
      }
      dataCheck = "ok";
    }

    okIters++;
    kv("okit=%d", okIters);                 // progress survives a SIGKILL (F4)
    if ((it % 5) == 0 || it == iters - 1)
      fprintf(stderr, "[rank%d] it %2d ok (%.3f ms)%s\n", rank, it, dt, rank==1?" data exact":"");
    if (gapMs > 0) usleep(gapMs * 1000);
  }

  // ---- F4 drain: rank 0 keeps putting to the just-killed peer --------------
  // The barrier failed because rank 1 was SIGKILLed; rank 1's QP is being torn
  // down by its kernel. Issue bounded put+flush ops to that QP so the RDMA-level
  // fault (RETRY_EXC / REM_ACCESS) surfaces on the initiator, instead of only
  // seeing the peer's TCP FIN.
  if (isProcKill && peerGone && rank == 0 && exitCode == 0) {
    fprintf(stderr, "[rank0] F4 drain: peer gone, putting to dead QP to surface the RDMA fault\n");
    double drainT0 = relMs();
    int drc = ncclSuccess;
    for (int j = 0; j < 60; j++) {
      *h_rc = 123456;
      putKernel<<<1, 1, 0, st>>>(sendWin, 0, recvWin, 0, bytes, 0, devComm, /*useTimeout=*/1, timeoutCycles, d_rc, d_phase);
      if (cudaGetLastError() != cudaSuccess) break;
      double dd = nowSec() + devTimeoutS + 5.0;
      bool to = false;
      while (true) { cudaError_t q = cudaStreamQuery(st); if (q == cudaSuccess) break; if (q != cudaErrorNotReady) { drc = ncclSystemError; break; } if (nowSec() > dd) { to = true; break; } usleep(500); }
      drc = *h_rc;
      if (!to && drc != (int)ncclSuccess && drc != (int)ncclTimeout && drc != 123456) {
        // Q4: the drain's flush returned an error (ncclRemoteError = classified error CQE)
        kv("device_rc=%s device_rc_it=drain%d device_rc_mono_ms=%.3f", ncclGetErrorString((ncclResult_t)drc), j,
           nowSec() * 1e3);
        outcome = "error"; exitCode = (drc == (int)ncclRemoteError) ? 8 : 3; break;
      }
      // stop as soon as the device wait times out (RDMA retry exhausted) or the
      // host async monitor has recorded the error
      if (mon.firstMs.load() >= 0) { outcome = "error"; exitCode = 3; break; }          // host saw it
      if (to || drc == (int)ncclTimeout) { outcome = "timeout"; exitCode = 4; break; }   // device wait timed out
      if (drc != (int)ncclSuccess) { outcome = "error"; exitCode = 3; break; }
      usleep(20 * 1000);
    }
    fprintf(stderr, "[rank0] F4 drain done after %.1f ms (device_rc=%d)\n", relMs() - drainT0, drc);
    kv("drain_device_rc=%d drain_ms=%.1f drain_outcome=%s", drc, relMs() - drainT0, outcome);
  }

  // ---- post-fault host polling ---------------------------------------------
  // After an abnormal end (device timeout, hang, peer loss, drain) keep the
  // async-error monitor running for up to postPollS so slower host-side
  // detection is observed instead of being cut off by our own teardown.
  if (okIters < iters && mon.firstMs.load() < 0 && postPollS > 0) {
    double pp0 = nowSec();
    fprintf(stderr, "[rank%d] post-fault poll: waiting up to %.0f s for ncclCommGetAsyncError\n", rank, postPollS);
    while (nowSec() - pp0 < postPollS && mon.firstMs.load() < 0) usleep(20000);
    kv("post_poll_ms=%.1f", (nowSec() - pp0) * 1e3);
  }

  // ---- record outcome and tear down --------------------------------------
  mon.stop.store(true);
  monTh.join();
  double hostErrMs = mon.firstMs.load();
  ncclResult_t hostErr = (ncclResult_t)mon.firstErr.load();
  kv("iters_ok=%d init_outcome=%s data_check=%s silent_success=%d host_error=%s host_error_ms=%.1f",
     okIters, outcome, dataCheck, silent,
     (hostErrMs >= 0 ? ncclGetErrorString(hostErr) : "none"),
     hostErrMs);
  fprintf(stderr, "[rank%d] DONE okIters=%d outcome=%s data=%s host_error=%s@%.1fms exit=%d\n",
          rank, okIters, outcome, dataCheck,
          (hostErrMs >= 0 ? ncclGetErrorString(hostErr) : "none"), hostErrMs, exitCode);

  _teardownExit(exitCode);
  return exitCode;
}
