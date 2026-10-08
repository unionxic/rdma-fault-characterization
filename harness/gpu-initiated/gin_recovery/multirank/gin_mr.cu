// gin_mr.cu - N-rank NCCL GIN GDAKI driver for gin-multirank (EXPERIMENT.md 9). Like ../gin_ts2.cu it is an UNMODIFIED
// application: no recovery code, no fault query, no handshake, no relaunch. gin_ts2 is not changed.
//
// Traffic. Every directed edge a->b in GIN_MR_EDGES (default: every ordered pair of ranks) is one CTA of ONE kernel on
// rank a (the sender) and one CTA of ONE kernel on rank b (the receiver):
//   sender   for i: put(slot i, bytes) + signal ADD 1 ; flush ; [gap]
//   receiver for i: waitSignal(base + i + 1) ; check slot i on the device
// and at the end every receiver's host checks every slot again and the final signal (exactly base + iters).
// Edge a->b uses its own GIN context ctx(a,b) = a*(N-1) + (b < a ? b : b-1) with signal 0 of that context, so
//  - a fault hook limited to one GIN context (NCCL_GIN_FAULT_INJECT_CTX) hits the QP of one edge only;
//  - a pair-scoped recovery round (gin-pair-reset) pauses that edge's QP only;
//  - no QP pair carries traffic in both directions (both directions on one context lost data, ../TRANSPARENT_S2.md C).
// N = 2 gives ctx(0,1) = 0 and ctx(1,0) = 1, the context split of gin_ts2's bidir mode.
// Slots: rank r's windows hold N-1 regions, one per other rank x at index idx(x, r) = x < r ? x : x-1. The sender a
// writes slot i of edge a->b from region idx(b, a) of its send window to region idx(a, b) of b's receive window. The data
// pattern of edge a->b uses seed 1 + 16a + b, so a slot that arrives on the wrong edge does not match.
//
// Flush (GIN_MR_FLUSH):
//   ctx   gin.flush(ncclCoopCta()) blocking: what gin_ts2 does. In GDAKI it waits on the context's QP to EVERY peer and
//         returns the context's sticky error (gin_gdaki.h flushImplModeCore, ncclGin::flush).
//   peer  gin.flushAsync(world, peer) + gin.wait(request, timeout GIN_MR_WAIT_S): the edge's own QP only, and the result
//         of that QP only (the timeout form of wait does not return the sticky error).
//
// usage: gin_mr <rank> <nranks> <rank0_mgmt_ip> <tcp_port> <iters> <bytes> <none|lat> <host_watchdog_s> <out_kv> [gap_us]
//   none  the loop above, one slot per iteration
//   lat   fault-free latency: one reused slot per edge, no device data check (the final signal is still checked)
// env: GIN_MR_EDGES (all | "a-b,c-d,...": the edges a->b, c->d; "-" because ">" is a shell redirection),
//   GIN_MR_FLUSH (ctx | peer), GIN_MR_WAIT_S (peer flush bound, 60), GIN_TS_RX_WAIT_S (receiver bound per waitSignal,
//   30), GIN_MR_GRACE_S (after an async error, how long the host lets the kernel run before it gives up, 2),
//   GIN_MR_SLOW_US (an iteration slower than this counts in slow_n, 5000),
//   GIN_MR_DEV (CUDA device, 0), GIN_ASYNC_POLL_US (200), GIN_ABORT_WATCHDOG_S (15), GIN_TS_END_WAIT_S (0.3)
// kv (one file per rank): rank-level keys as gin_ts2 (launch_mono_ms, devcomm_mono_ms, kernel_ms, async_first,
//   outcome, teardown_ms, abort_ret, exit) plus, per edge a->b (digits a, b):
//   sender   tx_<ab>_ctx _done _rc _rcit _nerr _p50_us _p99_us _max_us _maxit _slow_n _mean_us
//   receiver rx_<ab>_ctx _done _rc _rcit _devbad _hostbad _missing _sig _sigwant _sigexact
//   held window: win_edge win_it win_us (the slowest iteration over this rank's sending edges) and, per other sending
//   edge, w_<ab>_in (its iterations wholly inside that window) and w_<ab>_ovlmax_us (its slowest iteration overlapping it)
// exit: 0 every edge ok and no async error; 2 NCCL call error; 3 async error seen by the host; 4 a device wait/flush
//       returned an error or timed out; 5 data/signal check failed; 6 CUDA error; 7 watchdog; 1 usage.

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
#include <string>
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
static const uint8_t POISON = 0xA5;
static const int MAXN = 6;  // N(N-1) <= 30 contexts: below the 32-bit scope masks of gin-pair-reset

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
    if (us) usleep(us);
  }
}

static void teardownExit(int code) {
  static std::atomic<int> once{0};
  if (once.fetch_add(1) != 0) _exit(code);
  if (g_comm) {
    const char* wd = getenv("GIN_ABORT_WATCHDOG_S");
    alarm(wd ? (unsigned)atoi(wd) : 15u);
    const double a0 = monoMs();
    ncclResult_t ar = ncclCommAbort(g_comm);
    const double a1 = monoMs();
    alarm(0);
    kv("teardown_ms=%.1f abort_ret=%s abort_start_mono_ms=%.3f", a1 - a0, ncclGetErrorString(ar), a0);
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

#define CK(c)                                                                                         \
  do {                                                                                                \
    cudaError_t e_ = (c);                                                                             \
    if (e_ != cudaSuccess) {                                                                          \
      fprintf(stderr, "[rank%d] CUDA %s:%d %s\n", g_rank, __FILE__, __LINE__, cudaGetErrorString(e_)); \
      kv("cuda_error=%s", cudaGetErrorString(e_));                                                    \
      teardownExit(6);                                                                                \
    }                                                                                                 \
  } while (0)
#define NK(c)                                                                                           \
  do {                                                                                                  \
    ncclResult_t r_ = (c);                                                                              \
    if (r_ != ncclSuccess && r_ != ncclInProgress) {                                                    \
      fprintf(stderr, "[rank%d] NCCL %s:%d %s\n", g_rank, __FILE__, __LINE__, ncclGetErrorString(r_)); \
      kv("nccl_error=%s", ncclGetErrorString(r_));                                                      \
      teardownExit(2);                                                                                  \
    }                                                                                                   \
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

// gin_ts2's pattern, with a per-edge seed
__host__ __device__ static inline uint8_t pat(int it, size_t idx, uint32_t seed) {
  uint32_t h = (uint32_t)(idx * 2654435761u) ^ (uint32_t)(it * 40503u + 0x9e3779b9u) ^ (seed * 0x85ebca6bu);
  h ^= h >> 13;
  return (uint8_t)(h & 0xff);
}
__host__ __device__ static inline int ctxOf(int a, int b, int n) { return a * (n - 1) + (b < a ? b : b - 1); }
__host__ __device__ static inline int idxOf(int x, int owner) { return x < owner ? x : x - 1; }
static inline uint32_t seedOf(int a, int b) { return 1u + 16u * (uint32_t)a + (uint32_t)b; }

__device__ __forceinline__ unsigned long long gtNow() {
  unsigned long long t;
  asm volatile("mov.u64 %0, %%globaltimer;" : "=l"(t));
  return t;
}

// One CTA per edge of this rank. role 0: send on edge (me -> peer); role 1: receive on edge (peer -> me).
struct EdgeDev {
  int role, peer, ctx;
  int lregion;               // region of this rank's window (send: idx(peer, me); receive: idx(peer, me))
  int rregion;               // send only: region of the peer's receive window, idx(me, peer)
  uint32_t seed;
  unsigned long long base;   // receive only: signal 0 of ctx before the launch
};
struct EdgeOut {
  int rc, rcIt, done, nErr;  // first non-success result, its iteration, iterations done, failed calls
  int bad, firstBad, pad0, pad1;
  unsigned long long firstErrLatNs;
};

__global__ void mrKernel(ncclWindow_t sendWin, ncclWindow_t recvWin, const uint8_t* recvBuf, size_t bytes, int iters,
                         int reuse, size_t regionBytes, unsigned long long gapNs, struct ncclDevComm devComm,
                         const EdgeDev* edges, EdgeOut* outs, unsigned long long* tS, unsigned long long* tE,
                         volatile int* progress, int flushPeer, unsigned long long waitCycles,
                         unsigned long long rxWaitCycles) {
  const EdgeDev e = edges[blockIdx.x];
  EdgeOut* out = outs + blockIdx.x;
  ncclGin gin{devComm, e.ctx};
  __shared__ int sRc;
  __shared__ int sBad;
  if (e.role == 0) {
    for (int i = 0; i < iters; i++) {
      const size_t lo = (size_t)e.lregion * regionBytes + (reuse ? 0 : (size_t)i * bytes);
      const size_t ro = (size_t)e.rregion * regionBytes + (reuse ? 0 : (size_t)i * bytes);
      const unsigned long long t0 = gtNow();
      if (threadIdx.x == 0) {
        sRc = 0;
        gin.put(ncclTeamWorld(devComm), e.peer, recvWin, ro, sendWin, lo, bytes, ncclGin_WeakSignalInc{0});
      }
      ncclResult_t rc;
      if (flushPeer) {
        if (threadIdx.x == 0) {
          ncclGinRequest_t req;
          gin.flushAsync(ncclTeamWorld(devComm), (uint32_t)e.peer, &req, ncclCoopThread());
          sRc = (int)gin.wait(req, ncclCoopThread(), ncclGin_None{}, cuda::memory_order_acquire, waitCycles);
        }
        __syncthreads();
        rc = (ncclResult_t)sRc;
      } else {
        rc = gin.flush(ncclCoopCta());
        if (rc != ncclSuccess) atomicCAS(&sRc, 0, (int)rc);
        __syncthreads();
        rc = (ncclResult_t)sRc;  // one result for the whole CTA
      }
      const unsigned long long t1 = gtNow();
      if (threadIdx.x == 0) {
        tS[(size_t)blockIdx.x * iters + i] = t0;
        tE[(size_t)blockIdx.x * iters + i] = t1;
        if (rc != ncclSuccess) {
          if (out->nErr == 0) {
            out->rc = (int)rc;
            out->rcIt = i;
            out->firstErrLatNs = t1 - t0;
          }
          out->nErr++;
        } else {
          out->done = i + 1;
        }
        progress[blockIdx.x] = i + 1;
        __threadfence_system();
      }
      __syncthreads();
      if (rc != ncclSuccess) return;
      if (gapNs) {
        const unsigned long long g0 = gtNow();
        while (gtNow() - g0 < gapNs) {}
      }
    }
  } else {
    for (int i = 0; i < iters; i++) {
      if (threadIdx.x == 0) sRc = 0;
      ncclResult_t rc = gin.waitSignal(ncclCoopCta(), 0, e.base + (unsigned long long)(i + 1), 64,
                                       cuda::memory_order_acquire, rxWaitCycles);
      if (threadIdx.x == 0) {
        if (rc != ncclSuccess) sRc = (int)rc;  // the timeout form returns the result to thread 0 only
        sBad = 0;
      }
      __syncthreads();
      rc = (ncclResult_t)sRc;
      if (rc != ncclSuccess) {
        if (threadIdx.x == 0) {
          out->rc = (int)rc;
          out->rcIt = i;
          out->nErr++;
        }
        return;
      }
      if (!reuse) {
        const uint8_t* slot = recvBuf + (size_t)e.lregion * regionBytes + (size_t)i * bytes;
        int b = 0;
        for (size_t k = threadIdx.x; k < bytes; k += blockDim.x)
          b |= (((volatile const uint8_t*)slot)[k] != pat(i, k, e.seed));
        if (b) atomicOr(&sBad, 1);
      }
      __syncthreads();
      if (threadIdx.x == 0) {
        if (sBad) {
          if (out->bad == 0) out->firstBad = i;
          out->bad++;
        }
        out->done = i + 1;
        progress[blockIdx.x] = i + 1;
        __threadfence_system();
      }
      __syncthreads();
    }
  }
}

__global__ void readSigKernel(struct ncclDevComm devComm, int ctx, unsigned long long* v) {
  ncclGin gin{devComm, ctx};
  if (threadIdx.x == 0) *v = gin.readSignal(0);
}

static void latStats(const std::string& pfx, std::vector<unsigned long long> v, unsigned long long slowNs) {
  const int n = (int)v.size();
  if (n <= 0) {
    kv("%s_p50_us=-1 %s_p99_us=-1 %s_max_us=-1 %s_maxit=-1 %s_slow_n=0 %s_mean_us=-1", pfx.c_str(), pfx.c_str(),
       pfx.c_str(), pfx.c_str(), pfx.c_str(), pfx.c_str());
    return;
  }
  const int imax = (int)(std::max_element(v.begin(), v.end()) - v.begin());
  const unsigned long long vmax = v[imax];
  int slow = 0;
  double sum = 0;
  for (auto x : v) {
    slow += x > slowNs;
    sum += (double)x;
  }
  std::sort(v.begin(), v.end());
  auto q = [&](double p) { size_t k = (size_t)(p * (n - 1) + 0.5); return v[k] / 1e3; };
  kv("%s_p50_us=%.2f %s_p99_us=%.2f %s_max_us=%.2f %s_maxit=%d %s_slow_n=%d %s_mean_us=%.2f", pfx.c_str(), q(0.5),
     pfx.c_str(), q(0.99), pfx.c_str(), vmax / 1e3, pfx.c_str(), imax, pfx.c_str(), slow, pfx.c_str(), sum / n / 1e3);
}

int main(int argc, char** argv) {
  if (argc < 10) {
    fprintf(stderr, "usage: %s <rank> <nranks> <rank0_ip> <port> <iters> <bytes> <none|lat> <host_watchdog_s> <out_kv> "
                    "[gap_us]\n", argv[0]);
    return 1;
  }
  const int rank = atoi(argv[1]);
  const int N = atoi(argv[2]);
  g_rank = rank;
  const char* rank0Ip = argv[3];
  const int port = atoi(argv[4]);
  const int iters = atoi(argv[5]);
  const size_t bytes = strtoul(argv[6], nullptr, 10);
  const char* mode = argv[7];
  const double watchdogS = atof(argv[8]);
  g_kv = fopen(argv[9], "w");
  const long gapUs = argc > 10 ? atol(argv[10]) : 0;
  const bool isLat = strcmp(mode, "lat") == 0;
  if (N < 2 || N > MAXN || rank < 0 || rank >= N || iters <= 0 || bytes == 0 || (!isLat && strcmp(mode, "none") != 0))
    return 1;
  const char* fe = getenv("GIN_MR_FLUSH");
  const bool flushPeer = fe && strcmp(fe, "peer") == 0;
  if (fe && !flushPeer && strcmp(fe, "ctx") != 0) return 1;
  const double waitS = getenv("GIN_MR_WAIT_S") ? atof(getenv("GIN_MR_WAIT_S")) : 60.0;
  const double rxWaitS = getenv("GIN_TS_RX_WAIT_S") ? atof(getenv("GIN_TS_RX_WAIT_S")) : 30.0;
  const double graceMs = getenv("GIN_MR_GRACE_S") ? atof(getenv("GIN_MR_GRACE_S")) * 1000.0 : 2000.0;
  const unsigned long long slowNs =
    (unsigned long long)((getenv("GIN_MR_SLOW_US") ? atof(getenv("GIN_MR_SLOW_US")) : 5000.0) * 1000.0);
  const int dev = getenv("GIN_MR_DEV") ? atoi(getenv("GIN_MR_DEV")) : 0;

  // edges: all ordered pairs, or the GIN_MR_EDGES list
  std::vector<std::pair<int, int>> all;
  const char* ee = getenv("GIN_MR_EDGES");
  if (ee == nullptr || *ee == '\0' || strcmp(ee, "all") == 0) {
    for (int a = 0; a < N; a++)
      for (int b = 0; b < N; b++)
        if (a != b) all.push_back({a, b});
  } else {
    for (const char* p = ee; p && *p;) {
      int a = -1, b = -1;
      if (sscanf(p, "%d-%d", &a, &b) != 2 || a < 0 || b < 0 || a >= N || b >= N || a == b) return 1;
      all.push_back({a, b});
      p = strchr(p, ',');
      if (p) p++;
    }
  }
  std::vector<EdgeDev> ed;
  std::string txList, rxList, ctxMap;
  for (auto& x : all) {
    char t[24];
    snprintf(t, sizeof(t), "%s%d>%d:%d", ctxMap.empty() ? "" : ",", x.first, x.second, ctxOf(x.first, x.second, N));
    ctxMap += t;
  }
  for (auto& x : all)
    if (x.first == rank) {
      EdgeDev d{};
      d.role = 0;
      d.peer = x.second;
      d.ctx = ctxOf(rank, x.second, N);
      d.lregion = idxOf(x.second, rank);
      d.rregion = idxOf(rank, x.second);
      d.seed = seedOf(rank, x.second);
      ed.push_back(d);
      txList += (txList.empty() ? "" : ",") + std::to_string(rank) + ">" + std::to_string(x.second);
    }
  const int nTx = (int)ed.size();
  for (auto& x : all)
    if (x.second == rank) {
      EdgeDev d{};
      d.role = 1;
      d.peer = x.first;
      d.ctx = ctxOf(x.first, rank, N);
      d.lregion = idxOf(x.first, rank);
      d.rregion = -1;
      d.seed = seedOf(x.first, rank);
      ed.push_back(d);
      rxList += (rxList.empty() ? "" : ",") + std::to_string(x.first) + ">" + std::to_string(rank);
    }
  const int nE = (int)ed.size(), nRx = nE - nTx;
  auto ename = [&](int k) {
    char t[8];
    if (ed[k].role == 0) snprintf(t, sizeof(t), "%d%d", rank, ed[k].peer);
    else snprintf(t, sizeof(t), "%d%d", ed[k].peer, rank);
    return std::string(t);
  };

  signal(SIGALRM, onAlarm);
  kv("rank=%d nranks=%d iters=%d bytes=%zu mode=%s flush=%s gap_us=%ld rx_wait_s=%.1f wait_s=%.1f grace_ms=%.0f "
     "slow_us=%.0f t0_mono_ms=%.3f", rank, N, iters, bytes, mode, flushPeer ? "peer" : "ctx", gapUs, rxWaitS, waitS,
     graceMs, slowNs / 1e3, monoMs());
  kv("tx_edges=%s rx_edges=%s n_tx=%d n_rx=%d gin_contexts=%d ctx_map=%s", txList.empty() ? "-" : txList.c_str(),
     rxList.empty() ? "-" : rxList.c_str(), nTx, nRx, N * (N - 1), ctxMap.c_str());
  std::thread([watchdogS]() {
    const double dl = nowSec() + watchdogS;
    while (nowSec() < dl) usleep(50000);
    static const char m[] = "WATCHDOG: global deadline exceeded; exiting 7\n";
    ssize_t w = write(2, m, sizeof(m) - 1);
    (void)w;
    _exit(7);
  }).detach();

  // ---- bootstrap (setup only): a TCP star around rank 0 carries the ncclUniqueId, the clock offsets, the barrier ----
  int one = 1;
  ncclUniqueId id;
  std::vector<int> socks(N, -1);  // rank 0: one socket per rank; others: socks[0]
  if (rank == 0) {
    NK(ncclGetUniqueId(&id));
    int ls = socket(AF_INET, SOCK_STREAM, 0);
    setsockopt(ls, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
    sockaddr_in a{};
    a.sin_family = AF_INET;
    a.sin_addr.s_addr = INADDR_ANY;
    a.sin_port = htons(port);
    if (bind(ls, (sockaddr*)&a, sizeof a)) { perror("bind"); return 1; }
    listen(ls, N);
    for (int k = 1; k < N; k++) {
      int s = accept(ls, nullptr, nullptr);
      int32_t r = -1;
      if (s < 0 || recvall(s, &r, sizeof r) || r <= 0 || r >= N || socks[r] >= 0) return 1;
      socks[r] = s;
    }
    close(ls);
    for (int r = 1; r < N; r++)
      if (sendall(socks[r], &id, sizeof id)) return 1;
  } else {
    sockaddr_in a{};
    a.sin_family = AF_INET;
    a.sin_port = htons(port);
    inet_pton(AF_INET, rank0Ip, &a.sin_addr);
    int s = -1;
    for (int t = 0;; t++) {
      s = socket(AF_INET, SOCK_STREAM, 0);
      if (connect(s, (sockaddr*)&a, sizeof a) == 0) break;
      close(s);
      if (t > 600) return 1;
      usleep(200000);
    }
    int32_t r = rank;
    if (sendall(s, &r, sizeof r) || recvall(s, &id, sizeof id)) return 1;
    socks[0] = s;
  }
  for (int r = 0; r < N; r++)
    if (socks[r] >= 0) setsockopt(socks[r], IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
  {  // clock offset of every rank (its CLOCK_MONOTONIC minus rank 0's), best of 32 round trips, for the logs only
    if (rank == 0) {
      std::string line;
      for (int r = 1; r < N; r++) {
        double bestRtt = 1e9, bestOff = 0;
        for (int k = 0; k < 32; k++) {
          double t0 = monoMs(), t1 = 0;
          if (sendall(socks[r], &t0, sizeof t0) || recvall(socks[r], &t1, sizeof t1)) break;
          const double t2 = monoMs();
          if (t2 - t0 < bestRtt) {
            bestRtt = t2 - t0;
            bestOff = t1 - (t0 + t2) / 2;
          }
        }
        double fin = -1;
        if (sendall(socks[r], &fin, sizeof fin) || sendall(socks[r], &bestOff, sizeof bestOff)) return 1;
        char t[96];
        snprintf(t, sizeof(t), "%sclock_offset_ms_r%d=%.3f clock_rtt_ms_r%d=%.3f", line.empty() ? "" : " ", r, bestOff, r,
                 bestRtt);
        line += t;
      }
      kv("clock_offset_ms=0.000 %s", line.c_str());
    } else {
      double off = 0;
      while (true) {
        double t0 = 0;
        if (recvall(socks[0], &t0, sizeof t0)) return 1;
        if (t0 < 0) break;
        const double t1 = monoMs();
        if (sendall(socks[0], &t1, sizeof t1)) return 1;
      }
      if (recvall(socks[0], &off, sizeof off)) return 1;
      kv("clock_offset_ms=%.3f", off);
    }
  }
  auto barrier = [&]() -> int {
    char b = 1;
    if (rank == 0) {
      for (int r = 1; r < N; r++)
        if (recvall(socks[r], &b, 1)) return -1;
      for (int r = 1; r < N; r++)
        if (sendall(socks[r], &b, 1)) return -1;
    } else {
      if (sendall(socks[0], &b, 1) || recvall(socks[0], &b, 1)) return -1;
    }
    return 0;
  };

  CK(cudaSetDevice(dev));
  int clockKHz = 0;
  CK(cudaDeviceGetAttribute(&clockKHz, cudaDevAttrClockRate, dev));
  const unsigned long long waitCycles = (unsigned long long)(waitS * clockKHz * 1000.0);
  const unsigned long long rxWaitCycles = (unsigned long long)(rxWaitS * clockKHz * 1000.0);
  {
    char bus[32] = {0};
    cudaDeviceGetPCIBusId(bus, sizeof(bus), dev);
    kv("cuda_dev=%d pci_bus=%s clock_khz=%d", dev, bus, clockKHz);
  }
  ncclConfig_t cfg = NCCL_CONFIG_INITIALIZER;
  cfg.blocking = 1;
  const double tInit0 = monoMs();
  NK(ncclCommInitRankConfig(&g_comm, N, id, rank, &cfg));
  kv("init_ms=%.1f", monoMs() - tInit0);
  const int reuse = isLat ? 1 : 0;
  const size_t regionBytes = reuse ? bytes : bytes * (size_t)iters;
  const size_t winBytes = regionBytes * (size_t)(N - 1);
  void *dSend = nullptr, *dRecv = nullptr;
  ncclWindow_t sendWin, recvWin;
  NK(ncclMemAlloc(&dSend, winBytes));
  NK(ncclMemAlloc(&dRecv, winBytes));
  NK(ncclCommWindowRegister(g_comm, dSend, winBytes, &sendWin, NCCL_WIN_COLL_SYMMETRIC));
  NK(ncclCommWindowRegister(g_comm, dRecv, winBytes, &recvWin, NCCL_WIN_COLL_SYMMETRIC));
  ncclDevComm devComm;
  ncclDevCommRequirements reqs = NCCL_DEV_COMM_REQUIREMENTS_INITIALIZER;
  reqs.ginContextCount = N * (N - 1);
  reqs.ginSignalCount = 1;
  reqs.ginConnectionType = NCCL_GIN_CONNECTION_FULL;
  const double tDc0 = monoMs();
  NK(ncclDevCommCreate(g_comm, &reqs, &devComm));
  const double tDevComm = monoMs();
  kv("devcomm_mono_ms=%.3f devcomm_ms=%.1f win_bytes=%zu", tDevComm, tDevComm - tDc0, winBytes);
  cudaStream_t st;
  CK(cudaStreamCreateWithFlags(&st, cudaStreamNonBlocking));

  // send window: region idx(b, me) of every sending edge me->b holds that edge's pattern; receive window poisoned
  {
    std::vector<uint8_t> h(winBytes, 0);
    for (int k = 0; k < nTx; k++)
      for (int i = 0; i < (reuse ? 1 : iters); i++)
        for (size_t j = 0; j < bytes; j++)
          h[(size_t)ed[k].lregion * regionBytes + (size_t)i * bytes + j] = pat(i, j, ed[k].seed);
    CK(cudaMemcpy(dSend, h.data(), winBytes, cudaMemcpyHostToDevice));
    CK(cudaMemset(dRecv, POISON, winBytes));
  }
  unsigned long long* dSig = nullptr;
  CK(cudaMalloc(&dSig, sizeof(unsigned long long)));
  std::string bases;
  for (int k = nTx; k < nE; k++) {
    readSigKernel<<<1, 32, 0, st>>>(devComm, ed[k].ctx, dSig);
    CK(cudaStreamSynchronize(st));
    CK(cudaMemcpy(&ed[k].base, dSig, sizeof(unsigned long long), cudaMemcpyDeviceToHost));
    bases += (bases.empty() ? "" : " ") + ("rx_" + ename(k) + "_base=" + std::to_string(ed[k].base));
  }
  if (!bases.empty()) kv("%s", bases.c_str());
  EdgeDev* dEd = nullptr;
  EdgeOut* dOut = nullptr;
  unsigned long long *dTS = nullptr, *dTE = nullptr;
  const int nAlloc = std::max(1, nE);
  CK(cudaMalloc(&dEd, sizeof(EdgeDev) * nAlloc));
  CK(cudaMalloc(&dOut, sizeof(EdgeOut) * nAlloc));
  CK(cudaMalloc(&dTS, sizeof(unsigned long long) * nAlloc * iters));
  CK(cudaMalloc(&dTE, sizeof(unsigned long long) * nAlloc * iters));
  if (nE) CK(cudaMemcpy(dEd, ed.data(), sizeof(EdgeDev) * nE, cudaMemcpyHostToDevice));
  CK(cudaMemset(dOut, 0, sizeof(EdgeOut) * nAlloc));
  CK(cudaMemset(dTS, 0, sizeof(unsigned long long) * nAlloc * iters));
  CK(cudaMemset(dTE, 0, sizeof(unsigned long long) * nAlloc * iters));
  int *hProg = nullptr, *dProg = nullptr;
  CK(cudaHostAlloc((void**)&hProg, sizeof(int) * nAlloc, cudaHostAllocMapped));
  CK(cudaHostGetDevicePointer((void**)&dProg, hProg, 0));
  memset(hProg, 0, sizeof(int) * nAlloc);
  {
    cudaFuncAttributes fa;
    CK(cudaFuncGetAttributes(&fa, mrKernel));  // load the kernel now (lazy loading), see ../gin_ts2.cu
    kv("stack_mr=%zu regs_mr=%d", fa.localSizeBytes, fa.numRegs);
  }
  CK(cudaDeviceSynchronize());

  AsyncMon mon;
  std::thread monTh(asyncMonRun, &mon);
  if (barrier()) teardownExit(2);  // every receiver has poisoned its slots and read its signal bases
  const double tLaunch = monoMs();
  if (nE > 0)
    mrKernel<<<nE, 128, 0, st>>>(sendWin, recvWin, (const uint8_t*)dRecv, bytes, iters, reuse, regionBytes,
                                 (unsigned long long)gapUs * 1000ull, devComm, dEd, dOut, dTS, dTE, dProg,
                                 flushPeer ? 1 : 0, waitCycles, rxWaitCycles);
  CK(cudaGetLastError());
  kv("launch_mono_ms=%.3f", tLaunch);
  int exitCode = 0;
  const char* outcome = "ok";
  auto busy = [&]() {
    cudaError_t q = cudaStreamQuery(st);
    if (q != cudaSuccess && q != cudaErrorNotReady) CK(q);
    return q == cudaErrorNotReady;
  };
  double asyncSeenMs = -1;
  std::string progAtAsync;
  while (true) {
    if (!busy()) break;
    if (mon.firstMs.load() >= 0) {  // the application lets the kernel run for its grace, then gives up
      asyncSeenMs = monoMs();
      for (int k = 0; k < nE; k++)
        progAtAsync += (progAtAsync.empty() ? "" : " ") + ((ed[k].role == 0 ? "tx_" : "rx_") + ename(k) + "_prog_at_async=" +
                                                         std::to_string(hProg[k]));
      while (busy() && monoMs() - asyncSeenMs < graceMs) usleep(1000);
      kv("async_grace_ms=%.0f kernel_exit_after_async_ms=%.1f", graceMs, busy() ? -1.0 : monoMs() - asyncSeenMs);
      if (!progAtAsync.empty()) kv("%s", progAtAsync.c_str());
      if (busy()) {
        outcome = "async_error_kernel_stuck";
        exitCode = 3;
      }
      break;
    }
    usleep(500);
  }
  const double tEnd = monoMs();
  const bool kernelDone = !busy();
  kv("kernel_done=%d kernel_ms=%.1f", kernelDone ? 1 : 0, tEnd - tLaunch);
  int txOk = 0, rxOk = 0;
  if (kernelDone && nE > 0) {
    std::vector<EdgeOut> o(nE);
    CK(cudaMemcpy(o.data(), dOut, sizeof(EdgeOut) * nE, cudaMemcpyDeviceToHost));
    std::vector<unsigned long long> ts((size_t)nE * iters), te((size_t)nE * iters);
    CK(cudaMemcpy(ts.data(), dTS, sizeof(unsigned long long) * nE * iters, cudaMemcpyDeviceToHost));
    CK(cudaMemcpy(te.data(), dTE, sizeof(unsigned long long) * nE * iters, cudaMemcpyDeviceToHost));
    std::vector<uint8_t> h(winBytes);
    CK(cudaMemcpy(h.data(), dRecv, winBytes, cudaMemcpyDeviceToHost));
    bool devErr = false, checkBad = false;
    // the held window: this rank's slowest sending iteration
    int wk = -1, wi = -1;
    unsigned long long wlat = 0;
    for (int k = 0; k < nTx; k++) {
      const std::string p = "tx_" + ename(k);
      const int nIt = std::min(iters, o[k].done + (o[k].nErr ? 1 : 0));
      std::vector<unsigned long long> lat;
      for (int i = 0; i < o[k].done; i++) {
        const unsigned long long l = te[(size_t)k * iters + i] - ts[(size_t)k * iters + i];
        lat.push_back(l);
      }
      for (int i = 0; i < nIt; i++) {
        const unsigned long long l = te[(size_t)k * iters + i] - ts[(size_t)k * iters + i];
        if (te[(size_t)k * iters + i] && l > wlat) {
          wlat = l;
          wk = k;
          wi = i;
        }
      }
      kv("%s_ctx=%d %s_done=%d %s_rc=%s %s_rcit=%d %s_nerr=%d %s_errlat_us=%.1f", p.c_str(), ed[k].ctx, p.c_str(), o[k].done,
         p.c_str(), ncclGetErrorString((ncclResult_t)o[k].rc), p.c_str(), o[k].nErr ? o[k].rcIt : -1, p.c_str(), o[k].nErr,
         p.c_str(), o[k].firstErrLatNs / 1e3);
      latStats(p, lat, slowNs);
      if (o[k].nErr) devErr = true;
      else if (o[k].done == iters) txOk++;
    }
    if (wk >= 0) {
      const unsigned long long ws = ts[(size_t)wk * iters + wi], we = te[(size_t)wk * iters + wi];
      std::string line;
      char t[160];
      snprintf(t, sizeof(t), "win_edge=%d>%d win_it=%d win_us=%.1f", rank, ed[wk].peer, wi, wlat / 1e3);
      line = t;
      for (int k = 0; k < nTx; k++) {
        if (k == wk) continue;
        int in = 0;
        unsigned long long ovl = 0;
        for (int i = 0; i < iters; i++) {
          const unsigned long long s = ts[(size_t)k * iters + i], e = te[(size_t)k * iters + i];
          if (e == 0) continue;
          if (s >= ws && e <= we) in++;
          if (e > ws && s < we && e - s > ovl) ovl = e - s;
        }
        snprintf(t, sizeof(t), " w_%s_in=%d w_%s_ovlmax_us=%.1f", ename(k).c_str(), in, ename(k).c_str(), ovl / 1e3);
        line += t;
      }
      kv("%s", line.c_str());
    }
    for (int k = nTx; k < nE; k++) {
      const std::string p = "rx_" + ename(k);
      int bad = 0, missing = 0;
      if (!reuse) {
        for (int i = 0; i < iters; i++) {
          size_t nb = 0, np = 0;
          const uint8_t* s = h.data() + (size_t)ed[k].lregion * regionBytes + (size_t)i * bytes;
          for (size_t j = 0; j < bytes; j++) {
            nb += s[j] != pat(i, j, ed[k].seed);
            np += s[j] == POISON;
          }
          if (nb) bad++;
          if (nb && np == bytes) missing++;
        }
      }
      readSigKernel<<<1, 32, 0, st>>>(devComm, ed[k].ctx, dSig);
      CK(cudaStreamSynchronize(st));
      unsigned long long fin = 0;
      CK(cudaMemcpy(&fin, dSig, sizeof(fin), cudaMemcpyDeviceToHost));
      const unsigned long long want = ed[k].base + (unsigned long long)iters;
      kv("%s_ctx=%d %s_done=%d %s_rc=%s %s_rcit=%d %s_devbad=%d %s_hostbad=%d %s_missing=%d %s_sig=%llu %s_sigwant=%llu "
         "%s_sigexact=%d", p.c_str(), ed[k].ctx, p.c_str(), o[k].done, p.c_str(), ncclGetErrorString((ncclResult_t)o[k].rc),
         p.c_str(), o[k].nErr ? o[k].rcIt : -1, p.c_str(), o[k].bad, p.c_str(), bad, p.c_str(), missing, p.c_str(), fin,
         p.c_str(), want, p.c_str(), fin == want ? 1 : 0);
      if (o[k].nErr) devErr = true;
      else if (o[k].done == iters && o[k].bad == 0 && bad == 0 && fin == want) rxOk++;
      else if (o[k].done == iters) checkBad = true;
    }
    if (devErr && exitCode == 0) {
      exitCode = 4;
      outcome = "device_error";
    }
    if (checkBad && exitCode == 0) {
      exitCode = 5;
      outcome = "check_failed";
    }
  }
  kv("tx_ok=%d rx_ok=%d", txOk, rxOk);
  if (!kernelDone && exitCode == 0) {
    exitCode = 7;
    outcome = "kernel_stuck";
  }
  const double endWaitS = getenv("GIN_TS_END_WAIT_S") ? atof(getenv("GIN_TS_END_WAIT_S")) : 0.3;
  usleep((useconds_t)(endWaitS * 1e6));
  mon.stop.store(true);
  monTh.join();
  ncclResult_t fa = ncclSuccess;
  ncclCommGetAsyncError(g_comm, &fa);
  if (mon.firstMs.load() >= 0 && exitCode == 0) {
    exitCode = 3;
    outcome = "async_error";
  }
  kv("async_first=%s async_first_ms_after_launch=%.1f async_err_samples=%ld async_samples=%ld final_async=%s",
     mon.firstMs.load() >= 0 ? ncclGetErrorString((ncclResult_t)mon.firstErr.load()) : "none",
     mon.firstMs.load() >= 0 ? mon.firstMs.load() - tLaunch : -1.0, mon.errSamples.load(), mon.samples.load(),
     ncclGetErrorString(fa));
  kv("outcome=%s", outcome);
  fprintf(stderr, "[rank%d] DONE outcome=%s exit=%d tx_ok=%d/%d rx_ok=%d/%d\n", rank, outcome, exitCode, txOk, nTx, rxOk,
          nRx);
  for (int r = 0; r < N; r++)
    if (socks[r] >= 0) close(socks[r]);
  teardownExit(exitCode);
  return exitCode;
}
