// gin_ts1.cu - 2-rank NCCL GIN GDAKI driver for transparent recovery S1 (gin_transparent_s1.diff).
//
// This is an UNMODIFIED application: it contains no recovery code, no fault query, no handshake and
// no relaunch. Rank 0 launches ONE kernel that runs the whole loop
//     for i in 0..iters-1:  put(slot i -> slot i, bytes) + signal ADD 1 ; flush ; [gap]
// and records the return code of every flush. Rank 1 launches ONE kernel that, for every i, waits
// for its signal to reach base+i+1, then checks slot i bit-exact on the device. At the end rank 1
// copies every slot back and checks it again, and reads the final signal (must be base+iters). Both
// hosts poll ncclCommGetAsyncError the whole time. Whatever happens underneath (a fault injected by
// the NCCL test hook, a recovery inside NCCL) must be invisible: every flush returns ncclSuccess,
// every slot is bit-exact, the final signal is exact, and the host never sees an async error.
//
// The sockets below exist only to exchange the ncclUniqueId and to line the two ranks up before the
// kernels start (a start barrier); nothing is exchanged over them during the loop.
//
// usage:
//   gin_ts1 <rank 0|1> <rank0_mgmt_ip> <tcp_port> <iters> <bytes> <timeout|blocking>
//           <none|F2|lat> <dev_timeout_s> <host_watchdog_s> <out_kv_file> [gap_us]
//   F2 = the application's own bug: iteration GIN_TS_F2_IT (default 10) puts to an offset outside the
//   receiver's window (REM_ACCESS). lat = no fault, per-iteration latency, one reused slot.
//   Faults of the transport (local QP ERR, peer QP ERR, peer SIGKILL) are injected by the runner.
// env: GIN_TS_F2_IT, GIN_TS_RX_WAIT_S (receiver's per-iteration waitSignal timeout, default 30),
//      GIN_ASYNC_POLL_US (200), GIN_LAT_RAW (path: per-iteration latency CSV, lat mode),
//      GIN_TS_CONTINUE=1 (test: keep posting after a failed flush instead of stopping)
// exit: 0 all iterations ok and nothing surfaced; 2 NCCL call error; 3 async error seen by the host;
//       4 a device wait/flush returned an error or timed out; 5 data/signal check failed;
//       6 CUDA error; 7 watchdog.

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
#include <vector>
#include <algorithm>
#include <unistd.h>
#include <csignal>
#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <sys/socket.h>

static int g_rank = -1;
static FILE* g_kv = nullptr;
static ncclComm_t g_comm = nullptr;
static cudaStream_t g_stream = nullptr;  // the kernel's stream (post-abort observation only)
static const uint8_t POISON = 0xA5;

static double nowSec() {
  struct timespec t;
  clock_gettime(CLOCK_MONOTONIC, &t);
  return t.tv_sec + t.tv_nsec * 1e-9;
}
static double monoMs() { return nowSec() * 1e3; }

static void kv(const char* fmt, ...) {
  if (!g_kv) return;
  va_list ap;
  va_start(ap, fmt);
  vfprintf(g_kv, fmt, ap);
  va_end(ap);
  fputc('\n', g_kv);
  fflush(g_kv);
}

static void teardownExit(int code) {
  static std::atomic<int> once{0};
  if (once.fetch_add(1) != 0) _exit(code);
  if (g_comm) {
    const char* wd = getenv("GIN_ABORT_WATCHDOG_S");
    alarm(wd ? (unsigned)atoi(wd) : 15u);
    double a0 = monoMs();
    ncclResult_t ar = ncclCommAbort(g_comm);
    alarm(0);
    kv("teardown_ms=%.1f abort_ret=%s", monoMs() - a0, ncclGetErrorString(ar));
    // GIN_TS_POST_ABORT_WAIT_S: if the kernel was still running at the abort, watch it for up to this
    // long after ncclCommAbort returned (observation only: exited / still running / CUDA error).
    const char* pw = getenv("GIN_TS_POST_ABORT_WAIT_S");
    if (pw && g_stream) {
      const double lim = atof(pw) * 1000.0, t0 = monoMs();
      cudaError_t q = cudaStreamQuery(g_stream);
      const bool wasRunning = q == cudaErrorNotReady;
      while (q == cudaErrorNotReady && monoMs() - t0 < lim) { usleep(1000); q = cudaStreamQuery(g_stream); }
      kv("post_abort_kernel_running_at_abort_return=%d post_abort_state=%s post_abort_exit_ms=%.1f", wasRunning ? 1 : 0,
         q == cudaSuccess ? "exited" : q == cudaErrorNotReady ? "still_running" : cudaGetErrorName(q),
         q == cudaErrorNotReady ? -1.0 : monoMs() - t0);
    }
  }
  kv("exit=%d", code);
  _exit(code);
}
static void onAlarm(int) {
  static const char m[] = "WATCHDOG: abort did not return; exiting 7\n";
  ssize_t w = write(2, m, sizeof(m) - 1);
  (void)w;
  _exit(7);
}

#define CK(c)                                                                                        \
  do {                                                                                               \
    cudaError_t e_ = (c);                                                                            \
    if (e_ != cudaSuccess) {                                                                         \
      fprintf(stderr, "[rank%d] CUDA %s:%d %s\n", g_rank, __FILE__, __LINE__, cudaGetErrorString(e_)); \
      kv("cuda_error=%s", cudaGetErrorString(e_));                                                   \
      teardownExit(6);                                                                               \
    }                                                                                                \
  } while (0)
#define NK(c)                                                                                          \
  do {                                                                                                 \
    ncclResult_t r_ = (c);                                                                             \
    if (r_ != ncclSuccess && r_ != ncclInProgress) {                                                   \
      fprintf(stderr, "[rank%d] NCCL %s:%d %s\n", g_rank, __FILE__, __LINE__, ncclGetErrorString(r_)); \
      kv("nccl_error=%s", ncclGetErrorString(r_));                                                     \
      teardownExit(2);                                                                                 \
    }                                                                                                  \
  } while (0)

static int sendall(int fd, const void* b, size_t n) {
  const char* p = (const char*)b;
  size_t o = 0;
  while (o < n) {
    ssize_t k = send(fd, p + o, n - o, MSG_NOSIGNAL);
    if (k <= 0) {
      if (k < 0 && errno == EINTR) continue;
      return -1;
    }
    o += (size_t)k;
  }
  return 0;
}
static int recvall(int fd, void* b, size_t n) {
  char* p = (char*)b;
  size_t o = 0;
  while (o < n) {
    ssize_t k = recv(fd, p + o, n - o, 0);
    if (k <= 0) {
      if (k < 0 && errno == EINTR) continue;
      return -1;
    }
    o += (size_t)k;
  }
  return 0;
}

// Deterministic per-(iteration, byte) pattern; the poison byte pattern never matches all of it.
__host__ __device__ static inline uint8_t pat(int it, size_t idx) {
  uint32_t h = (uint32_t)(idx * 2654435761u) ^ (uint32_t)(it * 40503u + 0x9e3779b9u);
  h ^= h >> 13;
  return (uint8_t)(h & 0xff);
}

__device__ __forceinline__ unsigned long long gtNow() {
  unsigned long long t;
  asm volatile("mov.u64 %0, %%globaltimer;" : "=l"(t));
  return t;
}

// ---- rank 0: the whole loop in one kernel ----------------------------------------------------------
// The application code of an ordinary GIN user: put + signal, flush, check the return code.
struct TxOut {
  int rc;                      // first non-success flush return code (0 = none)
  int rcIt;                    // its iteration
  int done;                    // iterations completed
  int nErr;                    // flushes that did not return ncclSuccess (continue mode counts them all)
  unsigned long long tStart;   // globaltimer at kernel start
  unsigned long long firstErrLatNs;  // latency of the first failing put+flush
  unsigned long long maxLaterErrLatNs;  // longest failing put+flush after the first one (continue mode)
};
__global__ void txKernel(ncclWindow_t sendWin, ncclWindow_t recvWin, size_t bytes, int iters, int reuseSlot,
                         int badIt, size_t badOff, unsigned long long gapNs, struct ncclDevComm devComm,
                         int useTimeout, unsigned long long timeoutCycles, unsigned long long* lat,
                         volatile int* progress, TxOut* out, int contOnErr) {
  ncclGin gin{devComm, 0};
  if (threadIdx.x == 0) out->tStart = gtNow();
  for (int i = 0; i < iters; i++) {
    const size_t off = reuseSlot ? 0 : (size_t)i * bytes;
    const size_t dst = (i == badIt) ? badOff : off;
    unsigned long long t0 = gtNow();
    gin.put(ncclTeamWorld(devComm), 1, recvWin, dst, sendWin, off, bytes, ncclGin_WeakSignalInc{0});
    ncclResult_t rc;
    if (useTimeout) rc = gin.flush(ncclCoopCta(), cuda::memory_order_acquire, ncclGin_None{}, timeoutCycles);
    else rc = gin.flush(ncclCoopCta());
    unsigned long long t1 = gtNow();
    if (threadIdx.x == 0) {
      lat[i] = t1 - t0;
      *progress = i + 1;
      __threadfence_system();
    }
    if (rc != ncclSuccess) {
      if (threadIdx.x == 0) {
        if (out->nErr == 0) {
          out->rc = (int)rc;
          out->rcIt = i;
          out->done = i;
          out->firstErrLatNs = t1 - t0;
        } else if (t1 - t0 > out->maxLaterErrLatNs) {
          out->maxLaterErrLatNs = t1 - t0;
        }
        out->nErr++;
      }
      // An ordinary application stops at the first error; GIN_TS_CONTINUE=1 keeps posting (test of the
      // bounded poster/waiter paths after a failure).
      if (!contOnErr) return;
    }
    if (gapNs) {
      unsigned long long g0 = gtNow();
      while (gtNow() - g0 < gapNs) {}
    }
  }
  if (threadIdx.x == 0 && out->nErr == 0) out->done = iters;
}

// ---- rank 1: wait for every iteration's signal and check its slot on the device -------------------
struct RxOut {
  int rc;                       // first non-success waitSignal return code
  int rcIt;
  int done;                     // iterations whose signal arrived
  int badSlots;                 // slots whose data was not bit-exact when their signal said "done"
  int firstBad;
  int pad;
};
__global__ void rxKernel(ncclWindow_t recvWin, const uint8_t* recvBuf, size_t bytes, int iters, int reuseSlot,
                         unsigned long long base, struct ncclDevComm devComm, unsigned long long waitCycles,
                         unsigned long long* tSig, unsigned long long* sigSeen, volatile int* progress, RxOut* out) {
  ncclGin gin{devComm, 0};
  __shared__ int bad;
  for (int i = 0; i < iters; i++) {
    ncclResult_t rc = gin.waitSignal(ncclCoopCta(), 0, base + (unsigned long long)(i + 1), 64,
                                     cuda::memory_order_acquire, waitCycles);
    if (rc != ncclSuccess) {
      if (threadIdx.x == 0) {
        out->rc = (int)rc;
        out->rcIt = i;
        out->done = i;
      }
      return;
    }
    if (threadIdx.x == 0) {
      tSig[i] = gtNow();
      sigSeen[i] = gin.readSignal(0);
      bad = 0;
    }
    __syncthreads();
    if (!reuseSlot) {
      const uint8_t* slot = recvBuf + (size_t)i * bytes;
      int b = 0;
      for (size_t k = threadIdx.x; k < bytes; k += blockDim.x) b |= (((volatile const uint8_t*)slot)[k] != pat(i, k));
      if (b) atomicOr(&bad, 1);
    }
    __syncthreads();
    if (threadIdx.x == 0) {
      if (bad) {
        if (out->badSlots == 0) out->firstBad = i;
        out->badSlots++;
      }
      *progress = i + 1;
      __threadfence_system();
    }
  }
  if (threadIdx.x == 0) out->done = iters;
}

__global__ void readSigKernel(struct ncclDevComm devComm, unsigned long long* v) {
  ncclGin gin{devComm, 0};
  if (threadIdx.x == 0) *v = gin.readSignal(0);
}

struct AsyncMon {
  std::atomic<bool> stop{false};
  std::atomic<int> firstErr{0};
  std::atomic<double> firstMs{-1.0};
  std::atomic<long> samples{0}, errSamples{0};
};
static void asyncMonRun(AsyncMon* m) {
  const char* pu = getenv("GIN_ASYNC_POLL_US");
  useconds_t us = pu ? (useconds_t)atoi(pu) : 200u;
  while (!m->stop.load()) {
    ncclResult_t s = ncclSuccess;
    if (ncclCommGetAsyncError(g_comm, &s) == ncclSuccess) {
      m->samples++;
      if (s != ncclSuccess && s != ncclInProgress) {
        m->errSamples++;
        if (m->firstMs.load() < 0) {
          m->firstErr.store((int)s);
          m->firstMs.store(monoMs());
        }
      }
    }
    usleep(us);
  }
}

static int cmpU64(const void* a, const void* b) {
  unsigned long long x = *(const unsigned long long*)a, y = *(const unsigned long long*)b;
  return x < y ? -1 : x > y ? 1 : 0;
}

int main(int argc, char** argv) {
  if (argc < 11) {
    fprintf(stderr, "usage: %s <rank> <rank0_ip> <port> <iters> <bytes> <timeout|blocking> <none|F2|lat> "
                    "<dev_timeout_s> <host_watchdog_s> <out_kv> [gap_us]\n", argv[0]);
    return 1;
  }
  const int rank = atoi(argv[1]);
  g_rank = rank;
  const char* peerIp = argv[2];
  const int port = atoi(argv[3]);
  const int iters = atoi(argv[4]);
  const size_t bytes = strtoul(argv[5], nullptr, 10);
  const bool useTimeout = strcmp(argv[6], "timeout") == 0;
  const char* mode = argv[7];
  const double devTimeoutS = atof(argv[8]);
  const double watchdogS = atof(argv[9]);
  g_kv = fopen(argv[10], "w");
  const long gapUs = argc > 11 ? atol(argv[11]) : 0;
  const bool isLat = strcmp(mode, "lat") == 0;
  const bool isF2 = strcmp(mode, "F2") == 0;
  const int badIt = isF2 ? (getenv("GIN_TS_F2_IT") ? atoi(getenv("GIN_TS_F2_IT")) : 10) : -1;
  const double rxWaitS = getenv("GIN_TS_RX_WAIT_S") ? atof(getenv("GIN_TS_RX_WAIT_S")) : 30.0;
  const bool contOnErr = getenv("GIN_TS_CONTINUE") && atoi(getenv("GIN_TS_CONTINUE")) != 0;
  if ((rank != 0 && rank != 1) || iters <= 0 || bytes == 0) return 1;
  signal(SIGALRM, onAlarm);
  kv("rank=%d iters=%d bytes=%zu wait_mode=%s mode=%s dev_timeout_s=%.1f gap_us=%ld t0_mono_ms=%.3f", rank, iters,
     bytes, argv[6], mode, devTimeoutS, gapUs, monoMs());
  std::thread([watchdogS]() {
    double dl = nowSec() + watchdogS;
    while (nowSec() < dl) usleep(50000);
    static const char m[] = "WATCHDOG: global deadline exceeded; exiting 7\n";
    ssize_t w = write(2, m, sizeof(m) - 1);
    (void)w;
    _exit(7);
  }).detach();

  // ncclUniqueId over TCP (setup only)
  int one = 1, sock = -1;
  ncclUniqueId id;
  if (rank == 0) {
    NK(ncclGetUniqueId(&id));
    int ls = socket(AF_INET, SOCK_STREAM, 0);
    setsockopt(ls, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
    sockaddr_in a{};
    a.sin_family = AF_INET;
    a.sin_addr.s_addr = INADDR_ANY;
    a.sin_port = htons(port);
    if (bind(ls, (sockaddr*)&a, sizeof a)) { perror("bind"); return 1; }
    listen(ls, 1);
    sock = accept(ls, nullptr, nullptr);
    close(ls);
    if (sendall(sock, &id, sizeof id)) return 1;
  } else {
    sockaddr_in a{};
    a.sin_family = AF_INET;
    a.sin_port = htons(port);
    inet_pton(AF_INET, peerIp, &a.sin_addr);
    for (int t = 0;; t++) {
      sock = socket(AF_INET, SOCK_STREAM, 0);
      if (connect(sock, (sockaddr*)&a, sizeof a) == 0) break;
      close(sock);
      if (t > 600) return 1;
      usleep(200000);
    }
    if (recvall(sock, &id, sizeof id)) return 1;
  }
  setsockopt(sock, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
  {  // clock offset (rank 1 CLOCK_MONOTONIC minus rank 0), best of 32 round trips, for the logs only
    double bestRtt = 1e9, bestOff = 0;
    for (int k = 0; k < 32; k++) {
      double t0 = 0, t1 = 0, t2 = 0;
      if (rank == 0) {
        t0 = monoMs();
        if (sendall(sock, &t0, sizeof t0) || recvall(sock, &t1, sizeof t1)) break;
        t2 = monoMs();
        if (t2 - t0 < bestRtt) { bestRtt = t2 - t0; bestOff = t1 - (t0 + t2) / 2; }
      } else {
        if (recvall(sock, &t0, sizeof t0)) break;
        t1 = monoMs();
        if (sendall(sock, &t1, sizeof t1)) break;
      }
    }
    if (rank == 0) kv("clock_offset_ms=%.3f clock_rtt_ms=%.3f", bestOff, bestRtt);
  }

  CK(cudaSetDevice(0));
  int clockKHz = 0;
  CK(cudaDeviceGetAttribute(&clockKHz, cudaDevAttrClockRate, 0));
  const unsigned long long timeoutCycles = (unsigned long long)(devTimeoutS * clockKHz * 1000.0);
  const unsigned long long rxWaitCycles = (unsigned long long)(rxWaitS * clockKHz * 1000.0);
  ncclConfig_t cfg = NCCL_CONFIG_INITIALIZER;
  cfg.blocking = 1;
  NK(ncclCommInitRankConfig(&g_comm, 2, id, rank, &cfg));
  const int reuse = isLat ? 1 : 0;
  const size_t winBytes = reuse ? bytes : bytes * (size_t)iters;
  void *dSend = nullptr, *dRecv = nullptr;
  ncclWindow_t sendWin, recvWin;
  NK(ncclMemAlloc(&dSend, winBytes));
  NK(ncclMemAlloc(&dRecv, winBytes));
  NK(ncclCommWindowRegister(g_comm, dSend, winBytes, &sendWin, NCCL_WIN_COLL_SYMMETRIC));
  NK(ncclCommWindowRegister(g_comm, dRecv, winBytes, &recvWin, NCCL_WIN_COLL_SYMMETRIC));
  ncclDevComm devComm;
  ncclDevCommRequirements reqs = NCCL_DEV_COMM_REQUIREMENTS_INITIALIZER;
  reqs.ginSignalCount = 1;
  reqs.ginConnectionType = NCCL_GIN_CONNECTION_FULL;
  NK(ncclDevCommCreate(g_comm, &reqs, &devComm));
  const double tDevComm = monoMs();
  kv("devcomm_mono_ms=%.3f", tDevComm);
  cudaStream_t st;
  CK(cudaStreamCreateWithFlags(&st, cudaStreamNonBlocking));
  g_stream = st;

  std::vector<uint8_t> h(winBytes);
  unsigned long long base = 0;
  if (rank == 0) {
    for (int i = 0; i < (reuse ? 1 : iters); i++)
      for (size_t k = 0; k < bytes; k++) h[(size_t)i * bytes + k] = pat(i, k);
    CK(cudaMemcpy(dSend, h.data(), winBytes, cudaMemcpyHostToDevice));
  } else {
    CK(cudaMemset(dRecv, POISON, winBytes));
    unsigned long long* dv;
    CK(cudaMalloc(&dv, sizeof(*dv)));
    readSigKernel<<<1, 1, 0, st>>>(devComm, dv);
    CK(cudaStreamSynchronize(st));
    CK(cudaMemcpy(&base, dv, sizeof(base), cudaMemcpyDeviceToHost));
    CK(cudaFree(dv));
    kv("signal_base=%llu", base);
  }
  CK(cudaDeviceSynchronize());

  unsigned long long *dLat = nullptr, *dSig = nullptr;
  CK(cudaMalloc(&dLat, sizeof(unsigned long long) * iters));
  CK(cudaMalloc(&dSig, sizeof(unsigned long long) * iters));
  CK(cudaMemset(dLat, 0, sizeof(unsigned long long) * iters));
  CK(cudaMemset(dSig, 0, sizeof(unsigned long long) * iters));
  int *hProg = nullptr, *dProg = nullptr;
  CK(cudaHostAlloc((void**)&hProg, sizeof(int), cudaHostAllocMapped));
  CK(cudaHostGetDevicePointer((void**)&dProg, hProg, 0));
  *hProg = 0;
  TxOut* dTx = nullptr;
  RxOut* dRx = nullptr;
  CK(cudaMalloc(&dTx, sizeof(TxOut)));
  CK(cudaMalloc(&dRx, sizeof(RxOut)));
  CK(cudaMemset(dTx, 0, sizeof(TxOut)));
  CK(cudaMemset(dRx, 0, sizeof(RxOut)));
  CK(cudaDeviceSynchronize());

  AsyncMon mon;
  std::thread monTh(asyncMonRun, &mon);

  // start barrier (the receiver's buffer is poisoned and its signal base read before the sender starts)
  char b = 1;
  if (rank == 0) { if (recvall(sock, &b, 1) || sendall(sock, &b, 1)) teardownExit(2); }
  else { if (sendall(sock, &b, 1) || recvall(sock, &b, 1)) teardownExit(2); }
  const double tLaunch = monoMs();
  if (rank == 0) {
    const size_t badOff = winBytes + (size_t)64 * 1024 * 1024;
    txKernel<<<1, 1, 0, st>>>(sendWin, recvWin, bytes, iters, reuse, badIt, badOff,
                              (unsigned long long)gapUs * 1000ull, devComm, useTimeout ? 1 : 0, timeoutCycles, dLat,
                              dProg, dTx, contOnErr ? 1 : 0);
  } else {
    rxKernel<<<1, 256, 0, st>>>(recvWin, (const uint8_t*)dRecv, bytes, iters, reuse, base, devComm, rxWaitCycles, dLat,
                                dSig, dProg, dRx);
  }
  CK(cudaGetLastError());
  kv("launch_mono_ms=%.3f", tLaunch);
  // wait for the kernel; if the host sees an async error the application gives up (exit 3), bounded
  int exitCode = 0;
  const char* outcome = "ok";
  while (true) {
    cudaError_t q = cudaStreamQuery(st);
    if (q == cudaSuccess) break;
    if (q != cudaErrorNotReady) CK(q);
    if (mon.firstMs.load() >= 0) {
      // The application learns that the communicator failed: it reports and aborts (the device wait
      // it is stuck in cannot be recovered by the application).
      // GIN_TS_ASYNC_GRACE_S: how long it lets the kernel finish on its own first (default 2 s).
      const double graceMs = getenv("GIN_TS_ASYNC_GRACE_S") ? atof(getenv("GIN_TS_ASYNC_GRACE_S")) * 1000.0 : 2000.0;
      double t = monoMs();
      while (cudaStreamQuery(st) == cudaErrorNotReady && monoMs() - t < graceMs) usleep(1000);
      kv("async_grace_ms=%.0f kernel_exit_after_async_ms=%.1f", graceMs,
         cudaStreamQuery(st) == cudaErrorNotReady ? -1.0 : monoMs() - t);
      if (cudaStreamQuery(st) == cudaErrorNotReady) {
        outcome = "async_error_kernel_stuck";
        exitCode = 3;
        break;
      }
      break;
    }
    usleep(500);
  }
  const double tEnd = monoMs();
  const bool kernelDone = cudaStreamQuery(st) == cudaSuccess;
  kv("kernel_done=%d kernel_ms=%.1f progress=%d", kernelDone ? 1 : 0, tEnd - tLaunch, *hProg);
  std::vector<unsigned long long> lat(iters), sig(iters);
  if (kernelDone) {
    CK(cudaMemcpy(lat.data(), dLat, sizeof(unsigned long long) * iters, cudaMemcpyDeviceToHost));
    CK(cudaMemcpy(sig.data(), dSig, sizeof(unsigned long long) * iters, cudaMemcpyDeviceToHost));
  }
  if (rank == 0 && kernelDone) {
    TxOut o;
    CK(cudaMemcpy(&o, dTx, sizeof(o), cudaMemcpyDeviceToHost));
    kv("tx_done=%d tx_rc=%s tx_rc_it=%d tx_start_gt=%llu tx_err_n=%d tx_err_first_lat_us=%.1f "
       "tx_err_later_max_lat_us=%.1f", o.done, ncclGetErrorString((ncclResult_t)o.rc), o.rc ? o.rcIt : -1, o.tStart,
       o.nErr, o.firstErrLatNs / 1e3, o.maxLaterErrLatNs / 1e3);
    if (o.rc != 0 && exitCode == 0) { exitCode = 4; outcome = "device_error"; }
    // per-iteration flush latency: max (the iteration a recovery was hidden in) and the rest
    int n = o.done;
    if (n > 0) {
      std::vector<unsigned long long> v(lat.begin(), lat.begin() + n);
      int imax = (int)(std::max_element(v.begin(), v.end()) - v.begin());
      unsigned long long vmax = v[imax];
      qsort(v.data(), n, sizeof(unsigned long long), cmpU64);
      double sum = 0;
      for (int i = 0; i < n; i++) sum += (double)v[i];
      auto q = [&](double p) { size_t k = (size_t)(p * (n - 1) + 0.5); return v[k] / 1e3; };
      kv("lat_n=%d lat_min_us=%.2f lat_p50_us=%.2f lat_p90_us=%.2f lat_p99_us=%.2f lat_max_us=%.2f lat_mean_us=%.2f "
         "lat_max_it=%d",
         n, v[0] / 1e3, q(0.5), q(0.9), q(0.99), vmax / 1e3, sum / n / 1e3, imax);
      const char* raw = getenv("GIN_LAT_RAW");
      if (raw) {
        FILE* f = fopen(raw, "w");
        if (f) {
          for (int i = 0; i < n; i++) fprintf(f, "%d,%llu\n", i, lat[i]);
          fclose(f);
        }
      }
    }
  }
  if (rank == 1 && kernelDone) {
    RxOut o;
    CK(cudaMemcpy(&o, dRx, sizeof(o), cudaMemcpyDeviceToHost));
    kv("rx_done=%d rx_rc=%s rx_rc_it=%d dev_bad_slots=%d dev_first_bad=%d", o.done,
       ncclGetErrorString((ncclResult_t)o.rc), o.rc ? o.rcIt : -1, o.badSlots, o.badSlots ? o.firstBad : -1);
    if (o.rc != 0 && exitCode == 0) { exitCode = 4; outcome = "device_error"; }
    // host re-check of every slot, and the exact final signal
    int badSlots = 0, firstBad = -1, missing = 0;
    if (!reuse) {
      CK(cudaMemcpy(h.data(), dRecv, winBytes, cudaMemcpyDeviceToHost));
      for (int i = 0; i < iters; i++) {
        size_t bad = 0, pois = 0;
        for (size_t k = 0; k < bytes; k++) {
          uint8_t x = h[(size_t)i * bytes + k];
          if (x != pat(i, k)) bad++;
          if (x == POISON) pois++;
        }
        if (bad) {
          if (firstBad < 0) firstBad = i;
          badSlots++;
          if (pois == bytes) missing++;
        }
      }
    }
    unsigned long long* dv;
    unsigned long long fin = 0;
    CK(cudaMalloc(&dv, sizeof(*dv)));
    readSigKernel<<<1, 1, 0, st>>>(devComm, dv);
    CK(cudaStreamSynchronize(st));
    CK(cudaMemcpy(&fin, dv, sizeof(fin), cudaMemcpyDeviceToHost));
    const unsigned long long want = base + (unsigned long long)iters;
    // signal monotonicity per iteration: after iteration i's wait, the signal is >= base+i+1 (it can be
    // ahead: the sender runs on); a double-counted ADD shows up in the final value.
    kv("host_bad_slots=%d host_first_bad=%d host_missing_slots=%d final_signal=%llu expected_final=%llu "
       "signal_exact=%d",
       badSlots, firstBad, missing, fin, want, fin == want ? 1 : 0);
    if (o.done == iters && (badSlots || o.badSlots || fin != want) && exitCode == 0) {
      exitCode = 5;
      outcome = "check_failed";
    }
  }
  if (!kernelDone && exitCode == 0) { exitCode = 7; outcome = "kernel_stuck"; }
  // let the async monitor sample a little longer (an error raised at the end would still count)
  usleep(300000);
  mon.stop.store(true);
  monTh.join();
  ncclResult_t fa = ncclSuccess;
  ncclCommGetAsyncError(g_comm, &fa);
  if (mon.firstMs.load() >= 0 && exitCode == 0) { exitCode = 3; outcome = "async_error"; }
  kv("async_first=%s async_first_ms_after_launch=%.1f async_err_samples=%ld async_samples=%ld final_async=%s",
     mon.firstMs.load() >= 0 ? ncclGetErrorString((ncclResult_t)mon.firstErr.load()) : "none",
     mon.firstMs.load() >= 0 ? mon.firstMs.load() - tLaunch : -1.0, mon.errSamples.load(), mon.samples.load(),
     ncclGetErrorString(fa));
  kv("outcome=%s", outcome);
  fprintf(stderr, "[rank%d] DONE outcome=%s exit=%d progress=%d/%d\n", rank, outcome, exitCode, *hProg, iters);
  teardownExit(exitCode);
  return exitCode;
}
