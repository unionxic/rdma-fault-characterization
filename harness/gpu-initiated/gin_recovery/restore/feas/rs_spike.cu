// rs_spike.cu - gin-restore feasibility tests B1 and B2 (EXPERIMENT.md 9.15.2, 9.15.4; DRAFT stage, never scored).
// An N-rank NCCL GIN (GDAKI) application with the init path of ../../remaining/gin_mr.cu: ncclCommInitRankConfig
// (blocking), two ncclMemAlloc + ncclCommWindowRegister (NCCL_WIN_COLL_SYMMETRIC), ncclDevCommCreate with N(N-1) GIN
// contexts, one signal, FULL. It reports what the library built (kv) and ends with ncclCommAbort.
//   normal mode: a verified TCP rendezvous around rank 0 carries the ncclUniqueId (rank 0 calls ncclGetUniqueId), then a
//     short fault-free exchange: every directed edge a->b puts RS_ITERS slots of RS_BYTES with a signal increment on its
//     own context ctx(a, b) = a(N-1) + (b < a ? b : b-1) (as gin_mr), the receiver waits for each signal (timed) and checks
//     the slot on the device; a TCP barrier; RS_HOLD_S seconds of sleep (the live-replay cell); ncclCommAbort.
//   spare mode (RS_SPARE=1, B1): no rendezvous and no ncclGetUniqueId (the rsx library replays the recorded commId and
//     every exchange from NCCL_GIN_RESTORE_REPLAY), the same init calls, the report, ncclCommAbort. No kernel.
// usage: rs_spike <rank> <nranks> <rank0_ip> <port> <out_kv>     (spare: rank0_ip and port are ignored)
// env: RS_SPARE, RS_RDV_NONCE (16 hex; normal mode: rank 0 greets with "RSSPIKE1"+nonce, the others send nothing before
//      they checked it), RS_ITERS (20), RS_BYTES (4096), RS_HOLD_S (0), RS_WATCHDOG_S (90), RS_DEV (0), RS_WAIT_S (10)
// kv (every *_rc is the numeric ncclResult_t, 0 = success): mode, rank, nranks, init_rc, init_ms, reg_rc, reg_ms, devcomm_rc, devcomm_ms, comm_rank, comm_count, dc_rank,
//   dc_nranks, dc_lsa_rank, dc_lsa_size, dc_gin_contexts, dc_gin_signals, dc_gin_counters, dc_gin_connections, win_bytes,
//   ts_contexts, xchg (ok|bad|skipped), tx_err, rx_err, rx_bad, abort_rc, abort_ms, exit
// exit: 0 every step ok; 2 an NCCL call failed; 4 the exchange failed; 6 CUDA error; 7 watchdog; 1 usage or rendezvous.
#include <nccl.h>
#include "nccl_device.h"
#include <cuda_runtime.h>
#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <sys/socket.h>
#include <unistd.h>
#include <atomic>
#include <cerrno>
#include <chrono>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <thread>
#include <vector>

static FILE* g_kv = nullptr;
static void kv(const char* fmt, ...) __attribute__((format(printf, 1, 2)));
static void kv(const char* fmt, ...) {
  if (!g_kv) return;
  va_list ap;
  va_start(ap, fmt);
  vfprintf(g_kv, fmt, ap);
  va_end(ap);
  fputc('\n', g_kv);
  fflush(g_kv);
}
static double monoMs() {
  struct timespec t;
  clock_gettime(CLOCK_MONOTONIC, &t);
  return t.tv_sec * 1e3 + t.tv_nsec * 1e-6;
}
#define CK(c)                                                                         \
  do {                                                                                \
    cudaError_t e_ = (c);                                                             \
    if (e_ != cudaSuccess) {                                                          \
      fprintf(stderr, "CUDA %s:%d %s\n", __FILE__, __LINE__, cudaGetErrorString(e_)); \
      kv("cuda_error=%s line=%d exit=6", cudaGetErrorName(e_), __LINE__);             \
      _exit(6);                                                                       \
    }                                                                                 \
  } while (0)

__host__ __device__ static inline uint8_t pat(int it, size_t idx, uint32_t seed) {
  uint32_t h = (uint32_t)(idx * 2654435761u) ^ (uint32_t)(it * 40503u + 0x9e3779b9u) ^ (seed * 0x85ebca6bu);
  h ^= h >> 13;
  return (uint8_t)(h & 0xff);
}
__host__ __device__ static inline int ctxOf(int a, int b, int n) { return a * (n - 1) + (b < a ? b : b - 1); }
__host__ __device__ static inline int idxOf(int x, int owner) { return x < owner ? x : x - 1; }
__host__ __device__ static inline uint32_t seedOf(int a, int b) { return 1u + 16u * (uint32_t)a + (uint32_t)b; }

struct Out {
  int txErr, rxErr, rxBad, done;
};
// CTA k < N-1: sender to peer k-th; CTA k >= N-1: receiver from the (k-(N-1))-th peer
__global__ void xchgKernel(ncclWindow_t sendWin, ncclWindow_t recvWin, const uint8_t* recvBuf, size_t bytes, int iters,
                           size_t regionBytes, struct ncclDevComm devComm, int me, int n, unsigned long long waitCycles,
                           Out* outs) {
  const int k = blockIdx.x;
  const bool send = k < n - 1;
  const int j = send ? k : k - (n - 1);
  const int peer = j < me ? j : j + 1;
  Out* o = outs + k;
  __shared__ int sRc, sBad;
  if (send) {
    ncclGin gin{devComm, ctxOf(me, peer, n)};
    for (int i = 0; i < iters; i++) {
      if (threadIdx.x == 0) {
        sRc = 0;
        gin.put(ncclTeamWorld(devComm), peer, recvWin, (size_t)idxOf(me, peer) * regionBytes + (size_t)i * bytes, sendWin,
                (size_t)idxOf(peer, me) * regionBytes + (size_t)i * bytes, bytes, ncclGin_WeakSignalInc{0});
      }
      ncclResult_t rc = gin.flush(ncclCoopCta());
      if (rc != ncclSuccess) atomicCAS(&sRc, 0, (int)rc);
      __syncthreads();
      if (sRc != 0) {
        if (threadIdx.x == 0) o->txErr++;
        return;
      }
      if (threadIdx.x == 0) o->done = i + 1;
    }
  } else {
    ncclGin gin{devComm, ctxOf(peer, me, n)};
    for (int i = 0; i < iters; i++) {
      if (threadIdx.x == 0) {
        sRc = 0;
        sBad = 0;
      }
      __syncthreads();
      ncclResult_t rc =
        gin.waitSignal(ncclCoopCta(), 0, (unsigned long long)(i + 1), 64, cuda::memory_order_acquire, waitCycles);
      if (threadIdx.x == 0 && rc != ncclSuccess) sRc = (int)rc;
      __syncthreads();
      if (sRc != 0) {
        if (threadIdx.x == 0) o->rxErr++;
        return;
      }
      const uint8_t* slot = recvBuf + (size_t)idxOf(peer, me) * regionBytes + (size_t)i * bytes;
      int b = 0;
      for (size_t x = threadIdx.x; x < bytes; x += blockDim.x)
        b |= (((volatile const uint8_t*)slot)[x] != pat(i, x, seedOf(peer, me)));
      if (b) atomicOr(&sBad, 1);
      __syncthreads();
      if (threadIdx.x == 0) {
        if (sBad) o->rxBad++;
        o->done = i + 1;
      }
    }
  }
}

// ---- the rendezvous (normal mode) ----
static const char kMagic[8] = {'R', 'S', 'S', 'P', 'I', 'K', 'E', '1'};
struct Greet {
  char magic[8];
  uint64_t nonce;
};
struct Answer {
  char magic[8];
  uint64_t nonce;
  int32_t rank, pad;
};
static int sendall(int s, const void* p, size_t n) {
  const char* c = (const char*)p;
  while (n) {
    ssize_t k = send(s, c, n, MSG_NOSIGNAL);
    if (k <= 0) {
      if (k < 0 && errno == EINTR) continue;
      return -1;
    }
    c += k;
    n -= (size_t)k;
  }
  return 0;
}
static int recvall(int s, void* p, size_t n) {
  char* c = (char*)p;
  while (n) {
    ssize_t k = recv(s, c, n, 0);
    if (k <= 0) {
      if (k < 0 && errno == EINTR) continue;
      return -1;
    }
    c += k;
    n -= (size_t)k;
  }
  return 0;
}
static void rcvTimeout(int s, int ms) {
  struct timeval tv = {ms / 1000, (ms % 1000) * 1000};
  setsockopt(s, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
}

int main(int argc, char** argv) {
  setvbuf(stdout, nullptr, _IOLBF, 0);  // NCCL logs to stdout: keep its lines on a later _exit
  if (argc < 6) {
    fprintf(stderr, "usage: %s <rank> <nranks> <rank0_ip> <port> <out_kv>\n", argv[0]);
    return 1;
  }
  const int rank = atoi(argv[1]), N = atoi(argv[2]), port = atoi(argv[4]);
  const char* rank0Ip = argv[3];
  g_kv = fopen(argv[5], "w");
  if (!g_kv || N < 2 || N > 6 || rank < 0 || rank >= N) return 1;
  const bool spare = getenv("RS_SPARE") && atoi(getenv("RS_SPARE")) == 1;
  const int iters = getenv("RS_ITERS") ? atoi(getenv("RS_ITERS")) : 20;
  const size_t bytes = getenv("RS_BYTES") ? (size_t)atol(getenv("RS_BYTES")) : 4096;
  const double holdS = getenv("RS_HOLD_S") ? atof(getenv("RS_HOLD_S")) : 0;
  const int wdS = getenv("RS_WATCHDOG_S") ? atoi(getenv("RS_WATCHDOG_S")) : 90;
  const int dev = getenv("RS_DEV") ? atoi(getenv("RS_DEV")) : 0;
  const double waitS = getenv("RS_WAIT_S") ? atof(getenv("RS_WAIT_S")) : 10;
  kv("mode=%s rank=%d nranks=%d iters=%d bytes=%zu hold_s=%.1f", spare ? "spare" : "normal", rank, N, iters, bytes, holdS);
  std::thread([wdS]() {
    std::this_thread::sleep_for(std::chrono::seconds(wdS));
    static const char m[] = "WATCHDOG: rs_spike exceeded its bound; exiting 7\n";
    ssize_t w = write(2, m, sizeof(m) - 1);
    (void)w;
    if (g_kv) {
      fprintf(g_kv, "watchdog=1 exit=7\n");
      fflush(g_kv);
    }
    _exit(7);
  }).detach();

  ncclUniqueId id;
  memset(&id, 0, sizeof(id));
  std::vector<int> socks(N, -1);
  int one = 1;
  if (!spare) {
    const char* ns = getenv("RS_RDV_NONCE");
    if (!ns || strlen(ns) != 16) {
      kv("rdv_error=no_nonce exit=1");
      return 1;
    }
    const uint64_t nonce = strtoull(ns, nullptr, 16);
    if (rank == 0) {
      if (ncclGetUniqueId(&id) != ncclSuccess) {
        kv("nccl_error=getUniqueId exit=2");
        return 2;
      }
      int ls = socket(AF_INET, SOCK_STREAM, 0);
      setsockopt(ls, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
      sockaddr_in a{};
      a.sin_family = AF_INET;
      a.sin_addr.s_addr = INADDR_ANY;
      a.sin_port = htons((uint16_t)port);
      if (bind(ls, (sockaddr*)&a, sizeof a) || listen(ls, N + 4)) {
        kv("rdv_error=bind exit=1");
        return 1;
      }
      int foreign = 0;
      for (int k = 1; k < N;) {
        int s = accept(ls, nullptr, nullptr);
        if (s < 0) {
          if (errno == EINTR) continue;
          return 1;
        }
        Greet g;
        memcpy(g.magic, kMagic, 8);
        g.nonce = nonce;
        Answer an;
        rcvTimeout(s, 2000);
        if (sendall(s, &g, sizeof g) == 0 && recvall(s, &an, sizeof an) == 0 && memcmp(an.magic, kMagic, 8) == 0 &&
            an.nonce == nonce && an.rank > 0 && an.rank < N && socks[an.rank] < 0) {
          rcvTimeout(s, 0);
          socks[an.rank] = s;
          k++;
        } else {
          foreign++;
          close(s);
        }
      }
      close(ls);
      kv("rdv=verified rdv_foreign=%d", foreign);
      for (int r = 1; r < N; r++)
        if (sendall(socks[r], &id, sizeof id)) return 1;
    } else {
      sockaddr_in a{};
      a.sin_family = AF_INET;
      a.sin_port = htons((uint16_t)port);
      inet_pton(AF_INET, rank0Ip, &a.sin_addr);
      int s = -1, rejected = 0;
      for (int t = 0;; t++) {
        s = socket(AF_INET, SOCK_STREAM, 0);
        if (connect(s, (sockaddr*)&a, sizeof a) == 0) {
          Greet g;
          rcvTimeout(s, 2000);
          if (recvall(s, &g, sizeof g) == 0 && memcmp(g.magic, kMagic, 8) == 0 && g.nonce == nonce) {
            Answer an;
            memcpy(an.magic, kMagic, 8);
            an.nonce = nonce;
            an.rank = rank;
            an.pad = 0;
            if (sendall(s, &an, sizeof an) == 0) {
              rcvTimeout(s, 0);
              break;
            }
          }
          rejected++;  // not our rank 0: closed without a byte of ours
        }
        close(s);
        if (t > 300) return 1;
        usleep(200000);
      }
      kv("rdv=verified rdv_rejected=%d", rejected);
      if (recvall(s, &id, sizeof id)) return 1;
      socks[0] = s;
    }
    for (int r = 0; r < N; r++)
      if (socks[r] >= 0) setsockopt(socks[r], IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
  }
  auto barrier = [&]() -> int {
    if (spare) return 0;
    char b = 1;
    if (rank == 0) {
      for (int r = 1; r < N; r++)
        if (recvall(socks[r], &b, 1)) return -1;
      for (int r = 1; r < N; r++)
        if (sendall(socks[r], &b, 1)) return -1;
    } else if (sendall(socks[0], &b, 1) || recvall(socks[0], &b, 1)) {
      return -1;
    }
    return 0;
  };

  CK(cudaSetDevice(dev));
  int clockKHz = 0;
  CK(cudaDeviceGetAttribute(&clockKHz, cudaDevAttrClockRate, dev));
  ncclComm_t comm = nullptr;
  ncclConfig_t cfg = NCCL_CONFIG_INITIALIZER;
  cfg.blocking = 1;
  double t0 = monoMs();
  ncclResult_t r0 = ncclCommInitRankConfig(&comm, N, id, rank, &cfg);
  kv("init_rc=%d init_ms=%.1f", (int)r0, monoMs() - t0);
  if (r0 != ncclSuccess) {
    kv("exit=2");
    return 2;
  }
  const size_t regionBytes = bytes * (size_t)iters;
  const size_t need = regionBytes * (size_t)(N - 1);
  const size_t winBytes = ((need + (2u << 20) - 1) / (2u << 20)) * (2u << 20);
  void *dSend = nullptr, *dRecv = nullptr;
  ncclWindow_t sendWin = nullptr, recvWin = nullptr;
  t0 = monoMs();
  ncclResult_t r1 = ncclMemAlloc(&dSend, winBytes);
  if (r1 == ncclSuccess) r1 = ncclMemAlloc(&dRecv, winBytes);
  if (r1 == ncclSuccess) r1 = ncclCommWindowRegister(comm, dSend, winBytes, &sendWin, NCCL_WIN_COLL_SYMMETRIC);
  if (r1 == ncclSuccess) r1 = ncclCommWindowRegister(comm, dRecv, winBytes, &recvWin, NCCL_WIN_COLL_SYMMETRIC);
  kv("reg_rc=%d reg_ms=%.1f win_bytes=%zu", (int)r1, monoMs() - t0, winBytes);
  if (r1 != ncclSuccess) {
    kv("exit=2");
    _exit(2);
  }
  ncclDevComm devComm;
  memset(&devComm, 0, sizeof(devComm));
  ncclDevCommRequirements reqs = NCCL_DEV_COMM_REQUIREMENTS_INITIALIZER;
  reqs.ginContextCount = N * (N - 1);
  reqs.ginSignalCount = 1;
  reqs.ginConnectionType = NCCL_GIN_CONNECTION_FULL;
  t0 = monoMs();
  ncclResult_t r2 = ncclDevCommCreate(comm, &reqs, &devComm);
  kv("devcomm_rc=%d devcomm_ms=%.1f", (int)r2, monoMs() - t0);
  if (r2 != ncclSuccess) {
    kv("exit=2");
    _exit(2);
  }
  int cr = -1, cc = -1;
  ncclCommUserRank(comm, &cr);
  ncclCommCount(comm, &cc);
  ncclGinRecoveryStats_t st;
  memset(&st, 0, sizeof(st));
  const ncclResult_t rs = ncclGinGetRecoveryStats(comm, &st);
  kv("comm_rank=%d comm_count=%d dc_rank=%d dc_nranks=%d dc_lsa_rank=%d dc_lsa_size=%d dc_gin_contexts=%u dc_gin_signals=%d "
     "dc_gin_counters=%d dc_gin_connections=%d ts_contexts=%d ts_stats_rc=%d",
     cr, cc, devComm.rank, devComm.nRanks, devComm.lsaRank, devComm.lsaSize, devComm.ginContextCount,
     devComm.ginSignalCount, devComm.ginCounterCount, (int)devComm.ginConnectionCount, (int)st.contexts, (int)rs);

  int ex = 0;
  if (spare) {
    kv("xchg=skipped");
  } else {
    // send window: region idx(peer, me) of edge me->peer holds that edge's pattern; receive window: zero
    std::vector<uint8_t> h(winBytes, 0);
    for (int peer = 0; peer < N; peer++) {
      if (peer == rank) continue;
      for (int i = 0; i < iters; i++)
        for (size_t x = 0; x < bytes; x++)
          h[(size_t)idxOf(peer, rank) * regionBytes + (size_t)i * bytes + x] = pat(i, x, seedOf(rank, peer));
    }
    CK(cudaMemcpy(dSend, h.data(), winBytes, cudaMemcpyHostToDevice));
    CK(cudaMemset(dRecv, 0, winBytes));
    Out* outs = nullptr;
    CK(cudaMalloc(&outs, sizeof(Out) * 2 * (N - 1)));
    CK(cudaMemset(outs, 0, sizeof(Out) * 2 * (N - 1)));
    CK(cudaDeviceSynchronize());
    if (barrier()) {
      kv("barrier_error=1 exit=1");
      _exit(1);
    }
    const unsigned long long waitCycles = (unsigned long long)(waitS * clockKHz * 1000.0);
    xchgKernel<<<2 * (N - 1), 128>>>(sendWin, recvWin, (const uint8_t*)dRecv, bytes, iters, regionBytes, devComm, rank, N,
                                     waitCycles, outs);
    CK(cudaGetLastError());
    CK(cudaDeviceSynchronize());
    std::vector<Out> ho(2 * (N - 1));
    CK(cudaMemcpy(ho.data(), outs, sizeof(Out) * ho.size(), cudaMemcpyDeviceToHost));
    int txErr = 0, rxErr = 0, rxBad = 0, short_ = 0;
    for (auto& o : ho) {
      txErr += o.txErr;
      rxErr += o.rxErr;
      rxBad += o.rxBad;
      if (o.done != iters) short_++;
    }
    const bool ok = txErr == 0 && rxErr == 0 && rxBad == 0 && short_ == 0;
    kv("xchg=%s tx_err=%d rx_err=%d rx_bad=%d edges_short=%d", ok ? "ok" : "bad", txErr, rxErr, rxBad, short_);
    if (!ok) ex = 4;
    if (barrier()) kv("barrier_error=2");
    if (holdS > 0) {
      kv("hold_start_mono_ms=%.1f", monoMs());
      std::this_thread::sleep_for(std::chrono::milliseconds((long)(holdS * 1000)));
      ncclGinRecoveryStats_t s2;
      memset(&s2, 0, sizeof(s2));
      ncclGinGetRecoveryStats(comm, &s2);
      kv("hold_end_mono_ms=%.1f after_hold_rounds=%llu after_hold_declined=%llu after_hold_reconnects=%llu "
         "after_hold_deaths=%llu",
         monoMs(), s2.roundsStarted, s2.declined, s2.reconnects, s2.deathsJudged);
      if (barrier()) kv("barrier_error=3");
    }
  }
  t0 = monoMs();
  const ncclResult_t ra = ncclCommAbort(comm);
  kv("abort_rc=%d abort_ms=%.1f exit=%d", (int)ra, monoMs() - t0, ra == ncclSuccess ? ex : 2);
  fflush(stdout);
  _exit(ra == ncclSuccess ? ex : 2);
}
