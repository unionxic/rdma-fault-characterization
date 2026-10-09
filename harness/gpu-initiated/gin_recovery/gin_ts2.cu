// gin_ts2.cu - 2-rank NCCL GIN GDAKI driver for transparent recovery S2 (gin_transparent_s2.diff).
// An extended copy of gin_ts1.cu (the S1 modes are unchanged); still an UNMODIFIED application: no
// recovery code, no fault query, no handshake, no relaunch.
//
// Modes (argument 7):
//   none | F2 | lat   as gin_ts1: rank 0 launches ONE kernel, one thread,
//                       for i: put(slot i, bytes) + signal ADD 1 ; flush ; [gap]
//                     rank 1 launches ONE kernel that waits for every signal and checks slot i on the device.
//   burst             many operations in flight, many posting threads: rank 0 launches ONE kernel of
//                     GIN_TS_TX_BLOCKS x GIN_TS_TX_THREADS threads, all posting to the same QP (GIN's default
//                     GPU-wide resource sharing); every thread t runs
//                       for i: K x put(slot (i,t,k), bytes) [unsignaled; with GIN_TS_AGG=1 aggregated, i.e.
//                              ncclGinOptFlagsAggregateRequests: no doorbell until a later post rings] ;
//                              signal(StrongSignalInc on signal t) ; flush(thread) ; [gap]
//                     rank 1 launches ONE kernel with the same number of threads; thread t waits for signal t to
//                     reach base_t + i + 1, then checks its K slots of iteration i on the device. At the end
//                     rank 1 checks every slot on the host and every signal t == base_t + iters (exactly once).
//   bidir             both directions at once: every rank runs the S1 sender loop to the other rank and the S1
//                     receiver loop from it, in two kernels on two streams (data patterns differ per direction).
//                     Each direction uses the GIN context numbered by its sending rank (GIN_TS_BIDIR_CTX=same:
//                     both on context 0).
// Both hosts poll ncclCommGetAsyncError the whole time. A run is transparent iff every flush returned
// ncclSuccess and all iterations ran, every slot is bit-exact (device at arrival, host at the end), every
// final signal is exact, and no host saw an async error.
//
// usage:
//   gin_ts2 <rank 0|1> <rank0_mgmt_ip> <tcp_port> <iters> <bytes> <timeout|blocking>
//           <none|F2|lat|burst|bidir> <dev_timeout_s> <host_watchdog_s> <out_kv_file> [gap_us]
// env (in addition to gin_ts1's): GIN_TS_TX_BLOCKS (1), GIN_TS_TX_THREADS (1), GIN_TS_BURST_K (8),
//   GIN_TS_AGG (1: the K puts are aggregated), GIN_TS_QDEPTH (0: NCCL's default GIN queue depth),
//   GIN_TS_MAX_SIGNALS (256: with more senders, signal t % 256 is shared and rank 1 checks at the end),
//   GIN_TS_STACK_LIMIT (0: bytes of local memory per thread reserved before the launches, see main),
//   GIN_TS_BIDIR_FUSED (bidir: 1 = sender and receiver as two CTAs of one kernel instead of two kernels),
//   GIN_TS_AGG_GAP_US (burst: 0; a pause between the K aggregated puts and the signal that rings for them),
//   GIN_TS_BURST_BADIT (burst: -1; F2 in burst mode: thread 0's first put of that iteration goes to an invalid
//   remote offset), GIN_TS_R1_BYTES (bidir: rank 1's message size; default = bytes)
// gin-s2-close: GIN_TS_GET=1 (the one-thread loop of mode none, rank 0 sends): a get of GIN_TS_GET_BYTES (65536) per
//   iteration from rank 1's send window into rank 0's receive window, checked after a successful flush (kv get_n, get_bad).
// gin-pair-reset: GIN_TS_DUAL=1 (mode none): the one-thread loop on two GIN contexts at once. Rank 0 runs ONE kernel of two
//   CTAs; CTA c sends on context c into its own slot region (c * iters * bytes, pattern seed c + 1) with context c's
//   signal 0, and keeps every iteration's start and end (globaltimer). Rank 1 runs ONE kernel of two CTAs; CTA c waits for
//   context c's signal 0 and checks region c on the device; the host then checks every slot and both final signals. The
//   usual kv keys combine both contexts (tx_done: the smaller; tx_rc, rx_rc: the first error; slots and signals: both);
//   rank 0 adds dual_* keys about context 1 while context 0 was held (its longest iteration), see dualReport.
// gin-harden (all optional; without them the program does what it did):
//   rx_phantom (kv, every receiver of the one-thread loop): iterations whose signal wait returned ncclSuccess while the
//     signal value it read was still below the iteration's target (a wait released without its signal).
//   GIN_TS_HOG_MS=<ms>: once the GIN kernel(s) made their first iteration, launch a kernel that fills every SM (blocks
//     per SM from the occupancy calculator x SMs, 256 threads) and spins <ms> on its own stream (kv hog_*).
//   GIN_TS_SHRINK=1 (rank 0): after the main wait, ncclCommShrink(comm, {1}, NCCL_SHRINK_ABORT); if it returns a
//     communicator, check it with a 1024-float ncclAllReduce (bounded 5 s) and destroy it (kv ho_*); then wait up to
//     GIN_TS_HO_WAIT_S (3) for the old kernel; after the final ncclCommAbort the receiver's results are read again
//     (kv post_abort_rx_*), so a wait the abort released with ncclSuccess shows as a phantom.
//   rs_* (kv): ncclGinGetRecoveryStats of the communicator before the teardown, looked up with dlsym (rs_api=0 when the
//     library has no such API).
//   -DGIN_TS_STOCK_API: build against pristine NCCL (the blocking flush returns void there).
// gin-handoff (all optional; without them the program does what it did; the latency loop is unchanged):
//   with GIN_TS_HOG_MS, the GPU-filling blocks record their start (globaltimer) in a host-mapped array made before the
//     GIN launch; kv hog_started_probe (blocks started when the probe ran), and after the main wait hog_started_end,
//     hog_start_spread_ms (last start - first start), hog_first_start_rel_ms and hog_last_start_rel_ms (against the host's
//     real-time clock at the launch call; approximate). Between the GIN launch and the GPU-filling launch the program
//     makes exactly gin-harden's calls (occupancy query, which loads hogKernel under lazy loading; cudaMalloc of the sink;
//     the stream), unless GIN_TS_HOG_PREALLOC=1.
//   GIN_TS_HOG_PREALLOC=1: make those calls before the GIN launch (and read hogKernel's attributes: kv hog_local_bytes),
//     so that nothing is allocated, loaded or created between the two launches (kv hog_prealloc).
//   GIN_TS_HOG_SLACK=<k> (0): launch the GPU-filling kernel with k blocks fewer than SMs x blocks per SM (kv hog_slack),
//     so that it can be fully resident next to a resident GIN kernel that holds k block slots.
//   GIN_TS_HOG_PROBE=1: before the GIN launch create P non-blocking streams and events (P = CUDA_DEVICE_MAX_CONNECTIONS,
//     default 8) with their device word and staging; 20 ms after the GPU-filling launch issue one 4-byte device-to-host
//     copy (+ event) on each and poll them for 200 ms (kv probe_n, probe_done_200ms, probe_stuck = the indices still
//     running, probe_max_ms); after the main wait, probe_done_end. No kernel, allocation or default-stream call is issued
//     between the GPU-filling launch and the end of the probe.
//   GIN_TS_SHRINK=1: kv ho_parent_async_after, the parent's ncclCommGetAsyncError right after ncclCommShrink.
//   GIN_TS_SHRINK_DEVCOMM_DESTROY=1 (with GIN_TS_SHRINK): ncclDevCommDestroy before the shrink, once the old kernel has
//     ended (kv ho_devcomm_destroy_rc, ho_devcomm_destroy_ms); the final signal read is then skipped
//     (kv final_signal_read=skipped_devcomm_destroyed).
// gin-peer (optional; without it the program does what it did):
//   GIN_RDV_NONCE=<16 hex digits>: a verified rendezvous. Rank 0 greets every connection on its port with a 16-byte
//     record (magic "GINRDV01" + the nonce) and accepts only a connection that answers with the same record and rank 1;
//     rank 1 sends nothing until it has read and checked that greeting (a foreign listener on the port gets no byte from
//     it; a foreign greeting is closed and the connect retried). kv rdv=verified|legacy, rdv_rejected (rank 1: greetings
//     that failed the check), rdv_foreign (rank 0: connections that did not answer correctly), rdv_port.
//   GIN_RDV_TEST_DECOY_PORT=<p> (rank 1, test): before the real rendezvous, connect once to <p> (a decoy listener of the
//     runner that sends a wrong greeting) and check it the same way (kv rdv_decoy=rejected|accepted|no_connect).
// gin-remaining (optional; without it the program does what it did):
//   GIN_TS_HOG_CALLS=<comma list of load, malloc, stream | all | none> (with GIN_TS_HOG_MS; default all = gin-harden's
//     order): which of gin-harden's three calls run between the GIN launch and the GPU-filling launch; the others run before
//     the GIN launch. load = the occupancy query of hogKernel (its first use loads the kernel under lazy loading; run before
//     the GIN launch it is followed by a read of the kernel's attributes, kv hog_preloaded), malloc = cudaMalloc of the
//     sink, stream = the creation of its stream. GIN_TS_HOG_PREALLOC=1 is none. kv hog_calls_after=<list|none>.
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
#include <string>
#include <algorithm>
#include <unistd.h>
#include <csignal>
#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <dlfcn.h>

// gin-harden: pristine NCCL's blocking flush returns void; the research builds return the classified error.
#ifdef GIN_TS_STOCK_API
#define GIN_TS_FLUSH_BLOCKING(gin, coop) ((gin).flush(coop), ncclSuccess)
#else
#define GIN_TS_FLUSH_BLOCKING(gin, coop) (gin).flush(coop)
#endif

static int g_rank = -1;
static FILE* g_kv = nullptr;
static ncclComm_t g_comm = nullptr;
static cudaStream_t g_stream = nullptr;  // the kernel's stream (post-abort observation only)
// gin-harden (GIN_TS_SHRINK): what teardownExit reads again after the final ncclCommAbort
struct RxOut;
static bool g_hoPost = false;
static RxOut* g_hoRx = nullptr;
static unsigned long long* g_hoSig = nullptr;
static unsigned long long g_hoBase = 0;
static int g_hoIters = 0;
static cudaStream_t g_hoStream2 = nullptr;
static void hoPostAbortRead();  // below
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

struct AsyncMon {
  std::atomic<bool> stop{false};
  std::atomic<int> firstErr{0};
  std::atomic<double> firstMs{-1.0};
  std::atomic<long> samples{0}, errSamples{0};
  std::atomic<double> abortStartMs{-1.0};
  double abortLimitMs = -1.0;  // -1: stopped before the abort (default); 0: full
  std::atomic<long> abortSamples{0}, abortCallErrs{0};
  std::atomic<double> lastAbortSampleMs{-1.0};
};
static void asyncMonRun(AsyncMon* m) {
  const char* pu = getenv("GIN_ASYNC_POLL_US");
  useconds_t us = pu ? (useconds_t)atoi(pu) : 200u;
  while (!m->stop.load()) {
    const double a0 = m->abortStartMs.load();
    if (a0 >= 0 && m->abortLimitMs > 0 && monoMs() - a0 > m->abortLimitMs) break;
    ncclResult_t s = ncclSuccess;
    const ncclResult_t rc = ncclCommGetAsyncError(g_comm, &s);
    if (a0 >= 0) {
      m->abortSamples++;
      if (rc != ncclSuccess) m->abortCallErrs++;
      m->lastAbortSampleMs.store(monoMs());
    }
    if (rc == ncclSuccess) {
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
static AsyncMon* g_mon = nullptr;
static std::thread* g_monTh = nullptr;

static void teardownExit(int code) {
  static std::atomic<int> once{0};
  if (once.fetch_add(1) != 0) _exit(code);
  if (g_comm) {
    const char* wd = getenv("GIN_ABORT_WATCHDOG_S");
    alarm(wd ? (unsigned)atoi(wd) : 15u);
    double a0 = monoMs();
    if (g_mon && g_monTh) g_mon->abortStartMs.store(a0);
    ncclResult_t ar = ncclCommAbort(g_comm);
    const double a1 = monoMs();
    alarm(0);
    kv("teardown_ms=%.1f abort_ret=%s abort_start_mono_ms=%.3f", a1 - a0, ncclGetErrorString(ar), a0);
    if (g_mon && g_monTh) {
      g_mon->stop.store(true);
      g_monTh->join();
      kv("abort_mon_mode=%s abort_mon_samples=%ld abort_mon_call_errs=%ld abort_mon_last_after_start_ms=%.3f",
         g_mon->abortLimitMs == 0 ? "full" : "bounded", g_mon->abortSamples.load(), g_mon->abortCallErrs.load(),
         g_mon->lastAbortSampleMs.load() < 0 ? -1.0 : g_mon->lastAbortSampleMs.load() - a0);
    }
    const char* pw = getenv("GIN_TS_POST_ABORT_WAIT_S");
    if (pw && g_stream && g_hoPost) {  // gin-harden: the old kernel finished only after the abort: read it now
      const double lim = atof(pw) * 1000.0, t0 = monoMs();
      while ((cudaStreamQuery(g_stream) == cudaErrorNotReady ||
              (g_hoStream2 && cudaStreamQuery(g_hoStream2) == cudaErrorNotReady)) && monoMs() - t0 < lim)
        usleep(1000);
      hoPostAbortRead();
    }
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

// gin-peer: verified rendezvous (see the header). 16-byte greeting from rank 0; 24-byte answer (greeting + rank).
struct RdvGreet {
  char magic[8];
  uint64_t nonce;
};
struct RdvAnswer {
  char magic[8];
  uint64_t nonce;
  int32_t rank;
  int32_t pad;
};
static const char kRdvMagic[8] = {'G', 'I', 'N', 'R', 'D', 'V', '0', '1'};
static bool rdvNonce(uint64_t* n) {
  const char* e = getenv("GIN_RDV_NONCE");
  if (e == nullptr || *e == '\0') return false;
  *n = strtoull(e, nullptr, 16);
  return true;
}
static void rdvTimeout(int fd, int ms) {
  struct timeval tv;
  tv.tv_sec = ms / 1000;
  tv.tv_usec = (ms % 1000) * 1000;
  setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof tv);
  setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof tv);
}
// the connecting side: read the greeting (bounded) and check it before sending anything; true if it is rank 0's
static bool rdvCheckGreeting(int fd, uint64_t nonce, int ms) {
  rdvTimeout(fd, ms);
  RdvGreet g;
  if (recvall(fd, &g, sizeof g)) return false;
  return memcmp(g.magic, kRdvMagic, 8) == 0 && g.nonce == nonce;
}

// Deterministic per-(iteration, byte) pattern (gin_ts1's for seed 0; bidir uses seed = sender rank + 1).
__host__ __device__ static inline uint8_t pat(int it, size_t idx, uint32_t seed = 0) {
  uint32_t h = (uint32_t)(idx * 2654435761u) ^ (uint32_t)(it * 40503u + 0x9e3779b9u) ^ (seed * 0x85ebca6bu);
  h ^= h >> 13;
  return (uint8_t)(h & 0xff);
}
// burst: per 32-bit word of slot (it, t, k); never equal to the poison word for all words of a slot.
__host__ __device__ static inline uint32_t patW(int it, int t, int k, size_t w) {
  uint32_t h = (uint32_t)(w * 2654435761u) ^ (uint32_t)(it * 40503u + 0x9e3779b9u) ^ (uint32_t)(t * 0x85ebca6bu) ^
               (uint32_t)(k * 0xc2b2ae35u);
  h ^= h >> 15;
  h *= 0x2c1b3c6du;
  h ^= h >> 12;
  return h;
}

__device__ __forceinline__ unsigned long long gtNow() {
  unsigned long long t;
  asm volatile("mov.u64 %0, %%globaltimer;" : "=l"(t));
  return t;
}

// ---- S1 sender: the whole loop in one kernel ------------------------------------------------------
struct TxOut {
  int rc;                      // first non-success flush return code (0 = none)
  int rcIt;                    // its iteration
  int done;                    // iterations completed
  int nErr;                    // flushes that did not return ncclSuccess (continue mode counts them all)
  unsigned long long tStart;   // globaltimer at kernel start
  unsigned long long firstErrLatNs;
  unsigned long long maxLaterErrLatNs;
};
// (a __device__ body so that bidirFusedKernel can run it in one CTA next to the receiver's; thread 0 posts, the
//  CTA flushes: txKernel launches it with one thread, the fused kernel with 256)
__device__ void txBody(ncclWindow_t sendWin, ncclWindow_t recvWin, size_t bytes, int iters, int reuseSlot,
                       int badIt, size_t badOff, unsigned long long gapNs, struct ncclDevComm devComm,
                       int useTimeout, unsigned long long timeoutCycles, unsigned long long* lat,
                       volatile int* progress, TxOut* out, int contOnErr, int peer, int ctx) {
  ncclGin gin{devComm, ctx};
  if (threadIdx.x == 0) out->tStart = gtNow();
  for (int i = 0; i < iters; i++) {
    const size_t off = reuseSlot ? 0 : (size_t)i * bytes;
    const size_t dst = (i == badIt) ? badOff : off;
    unsigned long long t0 = gtNow();
    if (threadIdx.x == 0) gin.put(ncclTeamWorld(devComm), peer, recvWin, dst, sendWin, off, bytes, ncclGin_WeakSignalInc{0});
    ncclResult_t rc;
    if (useTimeout) rc = gin.flush(ncclCoopCta(), cuda::memory_order_acquire, ncclGin_None{}, timeoutCycles);
    else rc = GIN_TS_FLUSH_BLOCKING(gin, ncclCoopCta());
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
      if (!contOnErr) return;
    }
    if (gapNs) {
      unsigned long long g0 = gtNow();
      while (gtNow() - g0 < gapNs) {}
    }
  }
  if (threadIdx.x == 0 && out->nErr == 0) out->done = iters;
}
__global__ void txKernel(ncclWindow_t sendWin, ncclWindow_t recvWin, size_t bytes, int iters, int reuseSlot,
                         int badIt, size_t badOff, unsigned long long gapNs, struct ncclDevComm devComm,
                         int useTimeout, unsigned long long timeoutCycles, unsigned long long* lat,
                         volatile int* progress, TxOut* out, int contOnErr, int peer, int ctx) {
  txBody(sendWin, recvWin, bytes, iters, reuseSlot, badIt, badOff, gapNs, devComm, useTimeout, timeoutCycles, lat, progress,
         out, contOnErr, peer, ctx);
}

// ---- gin-s2-close: the S1 loop with a get (RDMA READ) per iteration (GIN_TS_GET=1, rank 0 only) ---------
// for i: put(slot i, bytes) + signal ADD 1 ; get(getBytes from the peer's send window at i*getBytes into this rank's
// receive window at the same offset) ; flush ; when the flush returned ncclSuccess, check the got bytes against the
// pattern the peer wrote (seed 7) ; [gap]. A separate kernel, so the other modes' kernels are unchanged.
struct GetOut {
  int n;           // gets checked (iterations whose flush returned ncclSuccess)
  int bad;         // of those, gets whose bytes did not match
  int firstBadIt;  // first such iteration (-1 = none)
  int pad;
};
__global__ void txGetKernel(ncclWindow_t sendWin, ncclWindow_t recvWin, size_t bytes, int iters, size_t getBytes,
                            const uint8_t* getBuf, unsigned long long gapNs, struct ncclDevComm devComm, int useTimeout,
                            unsigned long long timeoutCycles, unsigned long long* lat, volatile int* progress, TxOut* out,
                            GetOut* gout, int peer, int ctx) {
  ncclGin gin{devComm, ctx};
  out->tStart = gtNow();
  gout->firstBadIt = -1;
  for (int i = 0; i < iters; i++) {
    const size_t off = (size_t)i * bytes, goff = (size_t)i * getBytes;
    unsigned long long t0 = gtNow();
    gin.put(ncclTeamWorld(devComm), peer, recvWin, off, sendWin, off, bytes, ncclGin_WeakSignalInc{0});
    gin.get(ncclTeamWorld(devComm), peer, sendWin, goff, recvWin, goff, getBytes);
    ncclResult_t rc;
    if (useTimeout) rc = gin.flush(ncclCoopCta(), cuda::memory_order_acquire, ncclGin_None{}, timeoutCycles);
    else rc = GIN_TS_FLUSH_BLOCKING(gin, ncclCoopCta());
    unsigned long long t1 = gtNow();
    lat[i] = t1 - t0;
    if (rc != ncclSuccess) {
      out->rc = (int)rc;
      out->rcIt = i;
      out->done = i;
      out->firstErrLatNs = t1 - t0;
      out->nErr++;
      *progress = i + 1;
      __threadfence_system();
      return;
    }
    int b = 0;
    for (size_t k = 0; k < getBytes; k++)
      b |= (((volatile const uint8_t*)getBuf)[goff + k] != pat(i, k, 7u));
    gout->n++;
    if (b) {
      if (gout->bad == 0) gout->firstBadIt = i;
      gout->bad++;
    }
    *progress = i + 1;
    __threadfence_system();
    if (gapNs) {
      unsigned long long g0 = gtNow();
      while (gtNow() - g0 < gapNs) {}
    }
  }
  out->done = iters;
}

// ---- S1 receiver ----------------------------------------------------------------------------------
struct RxOut {
  int rc;
  int rcIt;
  int done;
  int badSlots;
  int firstBad;
  int pad;
};
__device__ void rxBody(ncclWindow_t recvWin, const uint8_t* recvBuf, size_t bytes, int iters, int reuseSlot,
                       unsigned long long base, struct ncclDevComm devComm, unsigned long long waitCycles,
                       unsigned long long* tSig, unsigned long long* sigSeen, volatile int* progress, RxOut* out,
                       uint32_t seed, int ctx) {
  ncclGin gin{devComm, ctx};
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
      for (size_t k = threadIdx.x; k < bytes; k += blockDim.x)
        b |= (((volatile const uint8_t*)slot)[k] != pat(i, k, seed));
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
__global__ void rxKernel(ncclWindow_t recvWin, const uint8_t* recvBuf, size_t bytes, int iters, int reuseSlot,
                         unsigned long long base, struct ncclDevComm devComm, unsigned long long waitCycles,
                         unsigned long long* tSig, unsigned long long* sigSeen, volatile int* progress, RxOut* out,
                         uint32_t seed, int ctx) {
  rxBody(recvWin, recvBuf, bytes, iters, reuseSlot, base, devComm, waitCycles, tSig, sigSeen, progress, out, seed, ctx);
}
// bidir with GIN_TS_BIDIR_FUSED=1: the sender and the receiver as two CTAs of ONE kernel (block 0 sends, block 1
// receives), co-scheduled by construction. On this testbed a GIN sender kernel launched on a second stream while a GIN
// receiver kernel runs does not start until the receiver exits (TRANSPARENT_S2.md, C); one kernel with both roles is
// also how a real GIN application is written.
__global__ void bidirFusedKernel(ncclWindow_t sendWin, ncclWindow_t recvWin, size_t txBytes, size_t rxBytes, int iters,
                                 int reuseSlot, int badIt, size_t badOff, unsigned long long gapNs, struct ncclDevComm devComm,
                                 int useTimeout, unsigned long long timeoutCycles, unsigned long long* lat,
                                 volatile int* progress, TxOut* out, int contOnErr, int peer, int txCtx,
                                 const uint8_t* recvBuf, unsigned long long base, unsigned long long waitCycles,
                                 unsigned long long* tSig, unsigned long long* sigSeen, volatile int* progressR, RxOut* outR,
                                 uint32_t rxSeed, int rxCtx) {
  if (blockIdx.x == 0)
    txBody(sendWin, recvWin, txBytes, iters, reuseSlot, badIt, badOff, gapNs, devComm, useTimeout, timeoutCycles, lat, progress,
           out, contOnErr, peer, txCtx);
  else
    rxBody(recvWin, recvBuf, rxBytes, iters, reuseSlot, base, devComm, waitCycles, tSig, sigSeen, progressR, outR, rxSeed, rxCtx);
}

// ---- S2 burst sender: many threads, K unsignaled puts + one signal + one flush per iteration ---------
struct TxThr {
  int rc, rcIt, done, pad;
  unsigned long long maxLatNs;
  int maxLatIt, pad2;
};
__global__ void txBurstKernel(ncclWindow_t sendWin, ncclWindow_t recvWin, size_t bytes, int iters, int K, int agg, int NS,
                              unsigned long long gapNs, unsigned long long aggGapNs, int badIt, size_t badOff,
                              struct ncclDevComm devComm, int useTimeout, unsigned long long timeoutCycles,
                              unsigned long long* lat0, volatile int* progress, TxThr* out) {
  ncclGin gin{devComm, 0};
  const int t = blockIdx.x * blockDim.x + threadIdx.x;
  const int P = gridDim.x * blockDim.x;
  TxThr o = {0, -1, 0, 0, 0ull, -1, 0};
  const uint32_t opt = agg ? (uint32_t)ncclGinOptFlagsAggregateRequests : (uint32_t)ncclGinOptFlagsDefault;
  for (int i = 0; i < iters; i++) {
    const unsigned long long t0 = gtNow();
    for (int k = 0; k < K; k++) {
      const size_t off = (((size_t)i * P + t) * K + k) * bytes;
      // GIN_TS_BURST_BADIT (F2 in burst mode): the first put of iteration badIt goes to an invalid remote offset
      const size_t dst = (i == badIt && k == 0 && t == 0) ? badOff : off;
      gin.put(ncclTeamWorld(devComm), 1, recvWin, dst, sendWin, off, bytes, ncclGin_None{}, ncclGin_None{},
              ncclCoopThread{}, ncclGin_None{}, cuda::thread_scope_thread, cuda::thread_scope_device, opt);
    }
    if (aggGapNs) {  // GIN_TS_AGG_GAP_US: the aggregated puts stay unrung for a while before the signal rings
      const unsigned long long g0 = gtNow();
      while (gtNow() - g0 < aggGapNs) {}
    }
    gin.signal(ncclTeamWorld(devComm), 1, ncclGin_StrongSignalInc{(ncclGinSignal_t)(t % NS)}, ncclCoopThread{});
    ncclResult_t rc;
    if (useTimeout) rc = gin.flush(ncclCoopThread(), cuda::memory_order_acquire, ncclGin_None{}, timeoutCycles);
    else rc = GIN_TS_FLUSH_BLOCKING(gin, ncclCoopThread());
    const unsigned long long dt = gtNow() - t0;
    if (dt > o.maxLatNs) {
      o.maxLatNs = dt;
      o.maxLatIt = i;
    }
    if (t == 0) {
      lat0[i] = dt;
      *progress = i + 1;
      __threadfence_system();
    }
    if (rc != ncclSuccess) {
      o.rc = (int)rc;
      o.rcIt = i;
      o.done = i;
      out[t] = o;
      return;
    }
    if (gapNs) {
      const unsigned long long g0 = gtNow();
      while (gtNow() - g0 < gapNs) {}
    }
  }
  o.done = iters;
  out[t] = o;
}

// ---- S2 burst receiver: thread s waits for signal s. With one signal per sending thread (NS == P) it checks
// the K slots of every iteration as the signal reaches base_s + i + 1. With fewer signals than senders (each
// signal shared by P/NS senders that do not run in lockstep), it waits for the final value base_s + iters*P/NS
// and then checks every slot of its senders. -------------------------------------------------------------------
struct RxThr {
  int rc, rcIt, done, badSlots, firstBad, pad;
};
__global__ void rxBurstKernel(const uint32_t* recvBuf, size_t bytes, int iters, int K, int P, const unsigned long long* bases,
                              struct ncclDevComm devComm, unsigned long long waitCycles, volatile int* progress,
                              RxThr* out) {
  ncclGin gin{devComm, 0};
  const int s = blockIdx.x * blockDim.x + threadIdx.x;
  const int NS = gridDim.x * blockDim.x;
  const int per = P / NS;
  RxThr o = {0, -1, 0, 0, -1, 0};
  const size_t words = bytes / 4;
  auto check = [&](int i, int t) {
    for (int k = 0; k < K; k++) {
      const volatile uint32_t* slot = recvBuf + (((size_t)i * P + t) * K + k) * words;
      bool b = false;
      for (size_t w = 0; w < words; w++) b |= (slot[w] != patW(i, t, k, w));
      if (b) {
        if (o.badSlots == 0) o.firstBad = (i * P + t) * K + k;
        o.badSlots++;
      }
    }
  };
  if (per == 1) {
    for (int i = 0; i < iters; i++) {
      const ncclResult_t rc = gin.waitSignal(ncclCoopThread(), (ncclGinSignal_t)s, bases[s] + (unsigned long long)(i + 1),
                                             64, cuda::memory_order_acquire, waitCycles);
      if (rc != ncclSuccess) {
        o.rc = (int)rc;
        o.rcIt = i;
        o.done = i;
        out[s] = o;
        return;
      }
      check(i, s);
      if (s == 0) {
        *progress = i + 1;
        __threadfence_system();
      }
    }
  } else {
    // the final value, one bound per iteration's worth of waiting
    const ncclResult_t rc =
      gin.waitSignal(ncclCoopThread(), (ncclGinSignal_t)s, bases[s] + (unsigned long long)iters * per, 64,
                     cuda::memory_order_acquire, waitCycles * (unsigned long long)iters);
    if (rc != ncclSuccess) {
      o.rc = (int)rc;
      o.rcIt = 0;
      o.done = 0;
      out[s] = o;
      return;
    }
    for (int t = s; t < P; t += NS)
      for (int i = 0; i < iters; i++) check(i, t);
    if (s == 0) {
      *progress = iters;
      __threadfence_system();
    }
  }
  o.done = iters;
  out[s] = o;
}

__global__ void readSigKernel(struct ncclDevComm devComm, unsigned long long* v, int n, int ctx) {
  ncclGin gin{devComm, ctx};
  for (int s = threadIdx.x; s < n; s += blockDim.x) v[s] = gin.readSignal((ncclGinSignal_t)s);
}

// ---- gin-pair-reset: two contexts at once (GIN_TS_DUAL=1) ------------------------------------------------------
__global__ void dualTxKernel(ncclWindow_t sendWin, ncclWindow_t recvWin, size_t bytes, int iters, unsigned long long gapNs,
                             struct ncclDevComm devComm, int useTimeout, unsigned long long timeoutCycles,
                             unsigned long long* tS, unsigned long long* tE, volatile int* progress, TxOut* outs, int peer) {
  const int c = blockIdx.x;
  ncclGin gin{devComm, c};
  TxOut* out = outs + c;
  const size_t region = (size_t)c * (size_t)iters * bytes;
  if (threadIdx.x == 0) out->tStart = gtNow();
  for (int i = 0; i < iters; i++) {
    const size_t off = region + (size_t)i * bytes;
    const unsigned long long t0 = gtNow();
    if (threadIdx.x == 0) gin.put(ncclTeamWorld(devComm), peer, recvWin, off, sendWin, off, bytes, ncclGin_WeakSignalInc{0});
    ncclResult_t rc;
    if (useTimeout) rc = gin.flush(ncclCoopCta(), cuda::memory_order_acquire, ncclGin_None{}, timeoutCycles);
    else rc = GIN_TS_FLUSH_BLOCKING(gin, ncclCoopCta());
    const unsigned long long t1 = gtNow();
    if (threadIdx.x == 0) {
      tS[(size_t)c * iters + i] = t0;
      tE[(size_t)c * iters + i] = t1;
      if (c == 0) {
        *progress = i + 1;
        __threadfence_system();
      }
    }
    if (rc != ncclSuccess) {
      if (threadIdx.x == 0) {
        out->rc = (int)rc;
        out->rcIt = i;
        out->done = i;
        out->firstErrLatNs = t1 - t0;
        out->nErr++;
      }
      return;
    }
    if (gapNs) {
      const unsigned long long g0 = gtNow();
      while (gtNow() - g0 < gapNs) {}
    }
  }
  if (threadIdx.x == 0) out->done = iters;
}
__global__ void dualRxKernel(const uint8_t* recvBuf, size_t bytes, int iters, const unsigned long long* bases,
                             struct ncclDevComm devComm, unsigned long long waitCycles, volatile int* progress, RxOut* outs) {
  const int c = blockIdx.x;
  ncclGin gin{devComm, c};
  RxOut* out = outs + c;
  __shared__ int bad;
  for (int i = 0; i < iters; i++) {
    const ncclResult_t rc = gin.waitSignal(ncclCoopCta(), 0, bases[c] + (unsigned long long)(i + 1), 64,
                                           cuda::memory_order_acquire, waitCycles);
    if (rc != ncclSuccess) {
      if (threadIdx.x == 0) {
        out->rc = (int)rc;
        out->rcIt = i;
        out->done = i;
      }
      return;
    }
    if (threadIdx.x == 0) bad = 0;
    __syncthreads();
    const uint8_t* slot = recvBuf + ((size_t)c * iters + i) * bytes;
    int b = 0;
    for (size_t k = threadIdx.x; k < bytes; k += blockDim.x) b |= (((volatile const uint8_t*)slot)[k] != pat(i, k, (uint32_t)c + 1));
    if (b) atomicOr(&bad, 1);
    __syncthreads();
    if (threadIdx.x == 0) {
      if (bad) {
        if (out->badSlots == 0) out->firstBad = c * iters + i;
        out->badSlots++;
      }
      if (c == 0) {
        *progress = i + 1;
        __threadfence_system();
      }
    }
  }
  if (threadIdx.x == 0) out->done = iters;
}

// ---- gin-harden: a kernel that fills every SM for a while (GIN_TS_HOG_MS) ------------------------------------------
__global__ void hogKernel(unsigned long long ns, unsigned long long* sink, unsigned long long* starts) {
  const unsigned long long t0 = gtNow();
  if (starts != nullptr && threadIdx.x == 0) {  // gin-handoff: when this block started (host-mapped, nonzero)
    starts[blockIdx.x] = t0 | 1ull;
    __threadfence_system();
  }
  unsigned long long x = 0;
  while (gtNow() - t0 < ns) x += threadIdx.x;
  if (x == 1ull) *sink = x;  // never true in practice; keeps the loop
}

// gin-harden: count the receiver's iterations whose wait returned ncclSuccess while the signal it read (sigSeen) was
// below the iteration's target base + i + 1 (a wait released without its signal).
static int phantomCount(const unsigned long long* seen, int done, unsigned long long base, int* first) {
  int n = 0;
  *first = -1;
  for (int i = 0; i < done; i++)
    if (seen[i] < base + (unsigned long long)(i + 1)) {
      if (n == 0) *first = i;
      n++;
    }
  return n;
}

static void hoPostAbortRead() {
  if (!g_hoRx || !g_hoSig || g_hoIters <= 0) return;
  RxOut o;
  std::vector<unsigned long long> seen((size_t)g_hoIters);
  const cudaError_t e1 = cudaMemcpy(&o, g_hoRx, sizeof(o), cudaMemcpyDeviceToHost);
  const cudaError_t e2 = cudaMemcpy(seen.data(), g_hoSig, sizeof(unsigned long long) * g_hoIters, cudaMemcpyDeviceToHost);
  if (e1 != cudaSuccess || e2 != cudaSuccess) {
    kv("post_abort_read=failed post_abort_cuda=%s", cudaGetErrorName(e1 != cudaSuccess ? e1 : e2));
    return;
  }
  int first = -1;
  const int ph = phantomCount(seen.data(), std::max(0, std::min(o.done, g_hoIters)), g_hoBase, &first);
  kv("post_abort_read=ok post_abort_rx_done=%d post_abort_rx_rc=%s post_abort_rx_phantom=%d post_abort_rx_phantom_first=%d "
     "post_abort_dev_bad_slots=%d", o.done, ncclGetErrorString((ncclResult_t)o.rc), ph, first, o.badSlots);
}

// gin-harden: ncclGinGetRecoveryStats (research builds only), looked up at run time so that one binary runs with every
// library (rs_api=0 when the symbol is absent).
static void recoveryStats(ncclComm_t comm) {
#ifdef NCCL_GIN_RECOVERY_STATS_VERSION
  typedef ncclResult_t (*fn_t)(ncclComm_t, ncclGinRecoveryStats_t*);
  fn_t f = (fn_t)dlsym(RTLD_DEFAULT, "ncclGinGetRecoveryStats");
  if (f == nullptr) {
    kv("rs_api=0");
    return;
  }
  ncclGinRecoveryStats_t st;
  const ncclResult_t rc = f(comm, &st);
  kv("rs_api=1 rs_rc=%s rs_version=%d rs_contexts=%d rs_rounds=%llu rs_recovered=%llu rs_declined=%llu rs_reconnects=%llu "
     "rs_deaths=%llu rs_escalations=%llu rs_cancelled=%llu rs_fw_overruns=%llu rs_copy_timeouts=%llu rs_escalated=%d",
     ncclGetErrorString(rc), st.version, st.contexts, st.roundsStarted, st.recovered, st.declined, st.reconnects,
     st.deathsJudged, st.escalations, st.cancelled, st.fwOverruns, st.copyTimeouts, st.escalatedNow);
#else
  (void)comm;
  kv("rs_api=0");
#endif
}

static int cmpU64(const void* a, const void* b) {
  unsigned long long x = *(const unsigned long long*)a, y = *(const unsigned long long*)b;
  return x < y ? -1 : x > y ? 1 : 0;
}

static void latStats(const char* pfx, std::vector<unsigned long long> v) {
  const int n = (int)v.size();
  if (n <= 0) return;
  int imax = (int)(std::max_element(v.begin(), v.end()) - v.begin());
  unsigned long long vmax = v[imax];
  qsort(v.data(), n, sizeof(unsigned long long), cmpU64);
  double sum = 0;
  for (int i = 0; i < n; i++) sum += (double)v[i];
  auto q = [&](double p) { size_t k = (size_t)(p * (n - 1) + 0.5); return v[k] / 1e3; };
  kv("%sn=%d %smin_us=%.2f %sp50_us=%.2f %sp90_us=%.2f %sp99_us=%.2f %smax_us=%.2f %smean_us=%.2f %smax_it=%d", pfx, n,
     pfx, v[0] / 1e3, pfx, q(0.5), pfx, q(0.9), pfx, q(0.99), pfx, vmax / 1e3, pfx, sum / n / 1e3, pfx, imax);
}

int main(int argc, char** argv) {
  if (argc < 11) {
    fprintf(stderr, "usage: %s <rank> <rank0_ip> <port> <iters> <bytes> <timeout|blocking> <none|F2|lat|burst|bidir> "
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
  const bool isBurst = strcmp(mode, "burst") == 0;
  const bool isBidir = strcmp(mode, "bidir") == 0;
  // F2 (an invalid remote offset at iteration badIt): mode F2 for the one-thread loop; in burst mode by env
  const int badIt = isF2 ? (getenv("GIN_TS_F2_IT") ? atoi(getenv("GIN_TS_F2_IT")) : 10)
                         : (isBurst && getenv("GIN_TS_BURST_BADIT")) ? atoi(getenv("GIN_TS_BURST_BADIT")) : -1;
  const long aggGapUs = (isBurst && getenv("GIN_TS_AGG_GAP_US")) ? atol(getenv("GIN_TS_AGG_GAP_US")) : 0;
  const double rxWaitS = getenv("GIN_TS_RX_WAIT_S") ? atof(getenv("GIN_TS_RX_WAIT_S")) : 30.0;
  // gin-s2-close: a get per iteration in the one-thread loop (rank 0 reads from rank 1's send window)
  const bool getMode = getenv("GIN_TS_GET") && atoi(getenv("GIN_TS_GET")) != 0;
  const size_t getBytes = getenv("GIN_TS_GET_BYTES") ? strtoul(getenv("GIN_TS_GET_BYTES"), nullptr, 10) : 65536;
  const bool contOnErr = getenv("GIN_TS_CONTINUE") && atoi(getenv("GIN_TS_CONTINUE")) != 0;
  const int txBlocks = getenv("GIN_TS_TX_BLOCKS") ? atoi(getenv("GIN_TS_TX_BLOCKS")) : 1;
  const int txThreads = getenv("GIN_TS_TX_THREADS") ? atoi(getenv("GIN_TS_TX_THREADS")) : 1;
  const int burstK = getenv("GIN_TS_BURST_K") ? atoi(getenv("GIN_TS_BURST_K")) : 8;
  const int agg = getenv("GIN_TS_AGG") ? atoi(getenv("GIN_TS_AGG")) : 1;
  const int qDepth = getenv("GIN_TS_QDEPTH") ? atoi(getenv("GIN_TS_QDEPTH")) : 0;
  const int P = isBurst ? txBlocks * txThreads : 1;
  // signals: one per sending thread, at most GIN_TS_MAX_SIGNALS (default 256; must divide P)
  const int maxSig = getenv("GIN_TS_MAX_SIGNALS") ? atoi(getenv("GIN_TS_MAX_SIGNALS")) : 256;
  const int NS = P <= maxSig ? P : maxSig;
  const int K = isBurst ? burstK : 1;
  if ((rank != 0 && rank != 1) || iters <= 0 || bytes == 0 || P <= 0 || K <= 0 || (isBurst && bytes % 4) || P % NS)
    return 1;
  if (getMode && (isBurst || isBidir || isLat || getBytes == 0 || getBytes > bytes)) return 1;  // one-thread loop only
  // gin-pair-reset: two contexts at once (the one-thread loop of mode none only)
  const bool dual = getenv("GIN_TS_DUAL") && atoi(getenv("GIN_TS_DUAL")) != 0;
  if (dual && (strcmp(mode, "none") != 0 || getMode)) return 1;
  signal(SIGALRM, onAlarm);
  kv("rank=%d iters=%d bytes=%zu wait_mode=%s mode=%s dev_timeout_s=%.1f gap_us=%ld t0_mono_ms=%.3f", rank, iters,
     bytes, argv[6], mode, devTimeoutS, gapUs, monoMs());
  if (getMode) kv("get_mode=1 get_bytes=%zu", getBytes);
  if (dual) kv("dual=1 dual_contexts=2");
  if (isBurst) kv("burst_blocks=%d burst_threads=%d burst_P=%d burst_K=%d burst_agg=%d qdepth=%d burst_signals=%d "
                  "burst_agg_gap_us=%ld burst_bad_it=%d", txBlocks, txThreads, P, K, agg, qDepth, NS, aggGapUs, badIt);
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
  uint64_t rdvN = 0;
  const bool rdv = rdvNonce(&rdvN);  // gin-peer: verified rendezvous
  if (rank == 0) {
    NK(ncclGetUniqueId(&id));
    int ls = socket(AF_INET, SOCK_STREAM, 0);
    setsockopt(ls, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
    sockaddr_in a{};
    a.sin_family = AF_INET;
    a.sin_addr.s_addr = INADDR_ANY;
    a.sin_port = htons(port);
    if (bind(ls, (sockaddr*)&a, sizeof a)) { perror("bind"); return 1; }
    listen(ls, 4);
    int foreign = 0;
    while (true) {
      sock = accept(ls, nullptr, nullptr);
      if (sock < 0) {
        if (errno == EINTR) continue;
        return 1;
      }
      if (!rdv) break;
      RdvGreet g;
      memcpy(g.magic, kRdvMagic, 8);
      g.nonce = rdvN;
      RdvAnswer an;
      rdvTimeout(sock, 2000);
      if (sendall(sock, &g, sizeof g) == 0 && recvall(sock, &an, sizeof an) == 0 && memcmp(an.magic, kRdvMagic, 8) == 0 &&
          an.nonce == rdvN && an.rank == 1) {
        rdvTimeout(sock, 0);
        break;
      }
      foreign++;  // not our rank 1: closed, nothing of ours was read from it
      close(sock);
    }
    close(ls);
    kv("rdv=%s rdv_foreign=%d rdv_port=%d", rdv ? "verified" : "legacy", foreign, port);
    if (sendall(sock, &id, sizeof id)) return 1;
  } else {
    sockaddr_in a{};
    a.sin_family = AF_INET;
    a.sin_port = htons(port);
    inet_pton(AF_INET, peerIp, &a.sin_addr);
    if (rdv && getenv("GIN_RDV_TEST_DECOY_PORT")) {  // gin-peer (test): a decoy listener first; nothing is sent to it
      sockaddr_in d = a;
      d.sin_port = htons(atoi(getenv("GIN_RDV_TEST_DECOY_PORT")));
      int ds = socket(AF_INET, SOCK_STREAM, 0);
      const char* res = "no_connect";
      if (connect(ds, (sockaddr*)&d, sizeof d) == 0) res = rdvCheckGreeting(ds, rdvN, 1000) ? "accepted" : "rejected";
      close(ds);
      kv("rdv_decoy=%s rdv_decoy_port=%d", res, ntohs(d.sin_port));
    }
    int rejected = 0;
    for (int t = 0;; t++) {
      sock = socket(AF_INET, SOCK_STREAM, 0);
      if (connect(sock, (sockaddr*)&a, sizeof a) == 0) {
        if (!rdv) break;
        if (rdvCheckGreeting(sock, rdvN, 2000)) {
          RdvAnswer an;
          memcpy(an.magic, kRdvMagic, 8);
          an.nonce = rdvN;
          an.rank = rank;
          an.pad = 0;
          if (sendall(sock, &an, sizeof an) == 0) {
            rdvTimeout(sock, 0);
            break;
          }
        }
        rejected++;  // not our rank 0 (or it went away): closed without a byte of ours unless it greeted correctly
      }
      close(sock);
      if (t > 600) return 1;
      usleep(200000);
    }
    kv("rdv=%s rdv_rejected=%d rdv_port=%d", rdv ? "verified" : "legacy", rejected, port);
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
  // bidir: rank 1's messages may differ in size (GIN_TS_R1_BYTES); slots are sized by the sender's messages
  const size_t bytesR1 = (isBidir && getenv("GIN_TS_R1_BYTES")) ? strtoul(getenv("GIN_TS_R1_BYTES"), nullptr, 10) : bytes;
  const size_t txBytes = (isBidir && rank == 1) ? bytesR1 : bytes, rxBytes = (isBidir && rank == 0) ? bytesR1 : bytes;
  const size_t maxBytes = std::max(bytes, bytesR1);
  const size_t winBytes = (reuse ? maxBytes : maxBytes * (size_t)iters * (size_t)P * (size_t)K) * (dual ? 2 : 1);
  void *dSend = nullptr, *dRecv = nullptr;
  ncclWindow_t sendWin, recvWin;
  NK(ncclMemAlloc(&dSend, winBytes));
  NK(ncclMemAlloc(&dRecv, winBytes));
  NK(ncclCommWindowRegister(g_comm, dSend, winBytes, &sendWin, NCCL_WIN_COLL_SYMMETRIC));
  NK(ncclCommWindowRegister(g_comm, dRecv, winBytes, &recvWin, NCCL_WIN_COLL_SYMMETRIC));
  ncclDevComm devComm;
  ncclDevCommRequirements reqs = NCCL_DEV_COMM_REQUIREMENTS_INITIALIZER;
  reqs.ginSignalCount = NS;
  reqs.ginConnectionType = NCCL_GIN_CONNECTION_FULL;
  if (qDepth > 0) reqs.ginQueueDepth = qDepth;
  NK(ncclDevCommCreate(g_comm, &reqs, &devComm));
  const double tDevComm = monoMs();
  kv("devcomm_mono_ms=%.3f", tDevComm);
  cudaStream_t st, st2;
  CK(cudaStreamCreateWithFlags(&st, cudaStreamNonBlocking));
  CK(cudaStreamCreateWithFlags(&st2, cudaStreamNonBlocking));
  g_stream = st;

  const bool sender = (rank == 0) || isBidir;
  const bool receiver = (rank == 1) || isBidir;
  const uint32_t txSeed = isBidir ? (uint32_t)rank + 1 : 0, rxSeed = isBidir ? (uint32_t)(1 - rank) + 1 : 0;
  // bidir: each direction on its own GIN context (context = the sending rank), unless GIN_TS_BIDIR_CTX=same.
  // Both directions on one context's QP pair lost data on every build here, including the gpudb build.
  const bool splitCtx = isBidir && !(getenv("GIN_TS_BIDIR_CTX") && strcmp(getenv("GIN_TS_BIDIR_CTX"), "same") == 0);
  const int txCtx = splitCtx ? rank : 0, rxCtx = splitCtx ? 1 - rank : 0;
  std::vector<uint8_t> h(winBytes);
  if (sender) {
    if (isBurst) {
      uint32_t* hw = (uint32_t*)h.data();
      const size_t words = bytes / 4;
      for (int i = 0; i < iters; i++)
        for (int t = 0; t < P; t++)
          for (int k = 0; k < K; k++)
            for (size_t w = 0; w < words; w++) hw[(((size_t)i * P + t) * K + k) * words + w] = patW(i, t, k, w);
    } else if (dual) {  // gin-pair-reset: region c with seed c + 1
      for (int c = 0; c < 2; c++)
        for (int i = 0; i < iters; i++)
          for (size_t k = 0; k < txBytes; k++) h[((size_t)c * iters + i) * txBytes + k] = pat(i, k, (uint32_t)c + 1);
    } else {
      for (int i = 0; i < (reuse ? 1 : iters); i++)
        for (size_t k = 0; k < txBytes; k++) h[(size_t)i * txBytes + k] = pat(i, k, txSeed);
    }
    CK(cudaMemcpy(dSend, h.data(), winBytes, cudaMemcpyHostToDevice));
  }
  if (getMode) {  // gin-s2-close: rank 1's send window holds the get source (seed 7); rank 0's receive window is poisoned
    if (rank == 1) {
      std::vector<uint8_t> g(winBytes, 0);
      for (int i = 0; i < iters; i++)
        for (size_t k = 0; k < getBytes; k++) g[(size_t)i * getBytes + k] = pat(i, k, 7u);
      CK(cudaMemcpy(dSend, g.data(), winBytes, cudaMemcpyHostToDevice));
    } else {
      CK(cudaMemset(dRecv, POISON, winBytes));
    }
  }
  std::vector<unsigned long long> bases(NS, 0);
  unsigned long long* dBases = nullptr;
  CK(cudaMalloc(&dBases, sizeof(unsigned long long) * NS));
  if (receiver) {
    CK(cudaMemset(dRecv, POISON, winBytes));
    readSigKernel<<<1, 256, 0, st>>>(devComm, dBases, NS, rxCtx);
    CK(cudaStreamSynchronize(st));
    CK(cudaMemcpy(bases.data(), dBases, sizeof(unsigned long long) * NS, cudaMemcpyDeviceToHost));
    kv("signal_base=%llu", bases[0]);
  }
  std::vector<unsigned long long> dualBases(2, 0);  // gin-pair-reset: signal 0 of contexts 0 and 1
  unsigned long long* dDualBases = nullptr;
  CK(cudaMalloc(&dDualBases, sizeof(unsigned long long) * 2));
  if (dual && receiver) {
    for (int c = 0; c < 2; c++) {
      readSigKernel<<<1, 256, 0, st>>>(devComm, dBases, 1, c);
      CK(cudaStreamSynchronize(st));
      CK(cudaMemcpy(&dualBases[c], dBases, sizeof(unsigned long long), cudaMemcpyDeviceToHost));
    }
    CK(cudaMemcpy(dDualBases, dualBases.data(), sizeof(unsigned long long) * 2, cudaMemcpyHostToDevice));
    kv("dual_signal_base0=%llu dual_signal_base1=%llu", dualBases[0], dualBases[1]);
  }
  CK(cudaDeviceSynchronize());

  unsigned long long *dLat = nullptr, *dSig = nullptr, *dLatR = nullptr;
  CK(cudaMalloc(&dLat, sizeof(unsigned long long) * iters));
  CK(cudaMalloc(&dSig, sizeof(unsigned long long) * iters));
  CK(cudaMalloc(&dLatR, sizeof(unsigned long long) * iters));
  CK(cudaMemset(dLat, 0, sizeof(unsigned long long) * iters));
  CK(cudaMemset(dSig, 0, sizeof(unsigned long long) * iters));
  CK(cudaMemset(dLatR, 0, sizeof(unsigned long long) * iters));
  int *hProg = nullptr, *dProg = nullptr, *hProgR = nullptr, *dProgR = nullptr;
  CK(cudaHostAlloc((void**)&hProg, sizeof(int), cudaHostAllocMapped));
  CK(cudaHostGetDevicePointer((void**)&dProg, hProg, 0));
  CK(cudaHostAlloc((void**)&hProgR, sizeof(int), cudaHostAllocMapped));
  CK(cudaHostGetDevicePointer((void**)&dProgR, hProgR, 0));
  *hProg = 0;
  *hProgR = 0;
  TxOut* dTx = nullptr;
  RxOut* dRx = nullptr;
  TxThr* dTxT = nullptr;
  RxThr* dRxT = nullptr;
  CK(cudaMalloc(&dTx, sizeof(TxOut)));
  CK(cudaMalloc(&dRx, sizeof(RxOut)));
  CK(cudaMalloc(&dTxT, sizeof(TxThr) * P));
  CK(cudaMalloc(&dRxT, sizeof(RxThr) * P));
  CK(cudaMemset(dTx, 0, sizeof(TxOut)));
  GetOut* dGet = nullptr;
  CK(cudaMalloc(&dGet, sizeof(GetOut)));
  CK(cudaMemset(dGet, 0, sizeof(GetOut)));
  CK(cudaMemset(dRx, 0, sizeof(RxOut)));
  CK(cudaMemset(dTxT, 0, sizeof(TxThr) * P));
  CK(cudaMemset(dRxT, 0, sizeof(RxThr) * P));
  TxOut* dTxD = nullptr;  // gin-pair-reset: per context
  RxOut* dRxD = nullptr;
  unsigned long long *dTS = nullptr, *dTE = nullptr;
  CK(cudaMalloc(&dTxD, sizeof(TxOut) * 2));
  CK(cudaMalloc(&dRxD, sizeof(RxOut) * 2));
  CK(cudaMalloc(&dTS, sizeof(unsigned long long) * 2 * iters));
  CK(cudaMalloc(&dTE, sizeof(unsigned long long) * 2 * iters));
  CK(cudaMemset(dTxD, 0, sizeof(TxOut) * 2));
  CK(cudaMemset(dRxD, 0, sizeof(RxOut) * 2));
  CK(cudaMemset(dTS, 0, sizeof(unsigned long long) * 2 * iters));
  CK(cudaMemset(dTE, 0, sizeof(unsigned long long) * 2 * iters));
  CK(cudaDeviceSynchronize());

  // Load every kernel now (CUDA lazy loading) and record their stack frames. GIN_TS_STACK_LIMIT=<bytes> reserves
  // that much local memory per thread up front: a kernel that needs more local memory than the device has
  // reserved makes the driver grow the reservation at launch, which waits for the kernels already running (bidir:
  // the receiver kernel, 248 B, runs first; the sender kernel, 592 B, then started only when it exited).
  {
    cudaFuncAttributes ft, fr, fb, frb, fg;
    CK(cudaFuncGetAttributes(&ft, txKernel));
    CK(cudaFuncGetAttributes(&fr, rxKernel));
    CK(cudaFuncGetAttributes(&fb, txBurstKernel));
    CK(cudaFuncGetAttributes(&frb, rxBurstKernel));
    CK(cudaFuncGetAttributes(&fg, readSigKernel));
    cudaFuncAttributes fdt, fdr;  // gin-pair-reset
    CK(cudaFuncGetAttributes(&fdt, dualTxKernel));
    CK(cudaFuncGetAttributes(&fdr, dualRxKernel));
    size_t lim = 0, lim2 = 0;
    CK(cudaDeviceGetLimit(&lim, cudaLimitStackSize));
    const long want = getenv("GIN_TS_STACK_LIMIT") ? atol(getenv("GIN_TS_STACK_LIMIT")) : 0;
    if (want > 0) CK(cudaDeviceSetLimit(cudaLimitStackSize, (size_t)want));
    CK(cudaDeviceGetLimit(&lim2, cudaLimitStackSize));
    kv("stack_tx=%zu stack_rx=%zu stack_txburst=%zu stack_rxburst=%zu stack_readsig=%zu stack_limit_before=%zu stack_limit_after=%zu",
       ft.localSizeBytes, fr.localSizeBytes, fb.localSizeBytes, frb.localSizeBytes, fg.localSizeBytes, lim, lim2);
  }

  // gin-harden: GIN_TS_HOG_MS (the GPU-filling kernel, launched after the GIN kernel, below).
  // gin-handoff: what it needs that gin-harden's driver did not have is made here, before the GIN launch, so that nothing
  // new is allocated or created between the two launches: the host-mapped array of block start times (sized for the
  // largest grid), and with GIN_TS_HOG_PROBE=1 the probe's device word, staging and P streams and events. With
  // GIN_TS_HOG_PREALLOC=1 gin-harden's own calls (occupancy query, which loads hogKernel; the sink; the stream) are made
  // here too, and hogKernel's attributes are read, so that the GIN launch and the GPU-filling launch have no allocation,
  // module load or stream creation between them.
  const long hogMs = getenv("GIN_TS_HOG_MS") ? atol(getenv("GIN_TS_HOG_MS")) : 0;
  const bool hogPrealloc = getenv("GIN_TS_HOG_PREALLOC") && atoi(getenv("GIN_TS_HOG_PREALLOC")) != 0;
  // gin-remaining: GIN_TS_HOG_CALLS, which of the three calls run after the GIN launch (default all; PREALLOC: none)
  bool hogLoadAfter = !hogPrealloc, hogMallocAfter = !hogPrealloc, hogStreamAfter = !hogPrealloc;
  if (!hogPrealloc && getenv("GIN_TS_HOG_CALLS") && *getenv("GIN_TS_HOG_CALLS") &&
      strcmp(getenv("GIN_TS_HOG_CALLS"), "all") != 0) {
    const std::string hc = std::string(",") + getenv("GIN_TS_HOG_CALLS") + ",";
    hogLoadAfter = hc.find(",load,") != std::string::npos;
    hogMallocAfter = hc.find(",malloc,") != std::string::npos;
    hogStreamAfter = hc.find(",stream,") != std::string::npos;
  }
  const int hogSlack = getenv("GIN_TS_HOG_SLACK") ? std::max(0, atoi(getenv("GIN_TS_HOG_SLACK"))) : 0;
  cudaStream_t st3 = nullptr;
  unsigned long long *hHogStart = nullptr, *hogStartDev = nullptr, *hogSink = nullptr, hogLaunchRtNs = 0;
  int hogSms = 0, hogPerSm = 0, hogCap = 0, hogBlocks = 0;
  unsigned int *probeD = nullptr, *probeH = nullptr;
  std::vector<cudaStream_t> probeSt;
  std::vector<cudaEvent_t> probeEv;
  if (hogMs > 0) {
    int sms = 0, maxPerSm = 0;
    CK(cudaDeviceGetAttribute(&sms, cudaDevAttrMultiProcessorCount, 0));
    CK(cudaDeviceGetAttribute(&maxPerSm, cudaDevAttrMaxBlocksPerMultiprocessor, 0));
    hogCap = std::max(1, sms * maxPerSm);
    CK(cudaHostAlloc((void**)&hHogStart, sizeof(unsigned long long) * hogCap, cudaHostAllocMapped));
    memset(hHogStart, 0, sizeof(unsigned long long) * hogCap);
    CK(cudaHostGetDevicePointer((void**)&hogStartDev, hHogStart, 0));
    if (getenv("GIN_TS_HOG_PROBE") && atoi(getenv("GIN_TS_HOG_PROBE")) != 0) {
      const char* mc = getenv("CUDA_DEVICE_MAX_CONNECTIONS");
      const int np = std::max(1, std::min(32, mc ? atoi(mc) : 8));
      CK(cudaMalloc(&probeD, sizeof(unsigned int) * np));
      CK(cudaHostAlloc((void**)&probeH, sizeof(unsigned int) * np, cudaHostAllocDefault));
      probeSt.resize(np);
      probeEv.resize(np);
      for (int i = 0; i < np; i++) CK(cudaStreamCreateWithFlags(&probeSt[i], cudaStreamNonBlocking));
      for (int i = 0; i < np; i++) CK(cudaEventCreateWithFlags(&probeEv[i], cudaEventDisableTiming));
    }
    // gin-handoff: GIN_TS_HOG_PREALLOC=1 makes all three calls here; gin-remaining: each call not listed in
    // GIN_TS_HOG_CALLS is made here
    if (!hogLoadAfter) {
      hogSms = sms;
      CK(cudaOccupancyMaxActiveBlocksPerMultiprocessor(&hogPerSm, hogKernel, 256, 0));
      cudaFuncAttributes fh;
      CK(cudaFuncGetAttributes(&fh, hogKernel));
      kv("hog_preloaded=1 hog_local_bytes=%zu hog_regs=%d", fh.localSizeBytes, fh.numRegs);
    }
    if (!hogMallocAfter) CK(cudaMalloc(&hogSink, sizeof(unsigned long long)));
    if (!hogStreamAfter) CK(cudaStreamCreateWithFlags(&st3, cudaStreamNonBlocking));
    {
      std::string after;
      if (hogLoadAfter) after += "load";
      if (hogMallocAfter) after += std::string(after.empty() ? "" : ",") + "malloc";
      if (hogStreamAfter) after += std::string(after.empty() ? "" : ",") + "stream";
      kv("hog_calls_after=%s", after.empty() ? "none" : after.c_str());
    }
  }
  // hog blocks started so far (the start-time array), and the first and last start (globaltimer, ns)
  auto hogStarted = [&](double* spreadMs, unsigned long long* first, unsigned long long* last) {
    int n = 0;
    unsigned long long lo = ~0ull, hi = 0;
    for (int b = 0; b < hogBlocks; b++) {
      const unsigned long long s = ((volatile unsigned long long*)hHogStart)[b];
      if (s == 0) continue;
      n++;
      lo = std::min(lo, s);
      hi = std::max(hi, s);
    }
    if (spreadMs) *spreadMs = n ? (double)(hi - lo) / 1e6 : -1.0;
    if (first) *first = n ? lo : 0;
    if (last) *last = n ? hi : 0;
    return n;
  };

  AsyncMon mon;
  std::thread monTh(asyncMonRun, &mon);

  // start barrier (the receiver's buffer is poisoned and its signal bases read before the sender starts)
  char b = 1;
  if (rank == 0) { if (recvall(sock, &b, 1) || sendall(sock, &b, 1)) teardownExit(2); }
  else { if (sendall(sock, &b, 1) || recvall(sock, &b, 1)) teardownExit(2); }
  const double tLaunch = monoMs();
  const int peer = 1 - rank;
  // receiver first on its own stream (bidir: both kernels on every rank; GIN_TS_BIDIR_FUSED=1: one kernel, two CTAs)
  const bool fusedBidir = isBidir && getenv("GIN_TS_BIDIR_FUSED") && atoi(getenv("GIN_TS_BIDIR_FUSED")) != 0;
  if (fusedBidir) {
    const size_t badOff = winBytes + (size_t)64 * 1024 * 1024;
    bidirFusedKernel<<<2, 256, 0, st>>>(sendWin, recvWin, txBytes, rxBytes, iters, reuse, badIt, badOff,
                                        (unsigned long long)gapUs * 1000ull, devComm, useTimeout ? 1 : 0, timeoutCycles, dLat,
                                        dProg, dTx, contOnErr ? 1 : 0, peer, txCtx, (const uint8_t*)dRecv, bases[0], rxWaitCycles,
                                        dLatR, dSig, dProgR, dRx, rxSeed, rxCtx);
    kv("bidir_fused=1");
  }
  if (dual && receiver) {
    dualRxKernel<<<2, 256, 0, st>>>((const uint8_t*)dRecv, bytes, iters, dDualBases, devComm, rxWaitCycles, dProg, dRxD);
  } else if (receiver && !fusedBidir) {
    cudaStream_t rs = isBidir ? st2 : st;
    if (isBurst)
      rxBurstKernel<<<(NS + 255) / 256, NS < 256 ? NS : 256, 0, rs>>>((const uint32_t*)dRecv, bytes, iters, K, P, dBases, devComm,
                                                    rxWaitCycles, isBidir ? dProgR : dProg, dRxT);
    else
      rxKernel<<<1, 256, 0, rs>>>(recvWin, (const uint8_t*)dRecv, rxBytes, iters, reuse, bases[0], devComm, rxWaitCycles,
                                  isBidir ? dLatR : dLat, dSig, isBidir ? dProgR : dProg, dRx, rxSeed, rxCtx);
  }
  if (dual && sender) {
    dualTxKernel<<<2, 256, 0, st>>>(sendWin, recvWin, bytes, iters, (unsigned long long)gapUs * 1000ull, devComm,
                                    useTimeout ? 1 : 0, timeoutCycles, dTS, dTE, dProg, dTxD, peer);
  } else if (sender && !fusedBidir) {
    const size_t badOff = winBytes + (size_t)64 * 1024 * 1024;
    if (isBurst)
      txBurstKernel<<<txBlocks, txThreads, 0, st>>>(sendWin, recvWin, bytes, iters, K, agg, NS,
                                                    (unsigned long long)gapUs * 1000ull, (unsigned long long)aggGapUs * 1000ull,
                                                    badIt, badOff, devComm, useTimeout ? 1 : 0, timeoutCycles, dLat, dProg, dTxT);
    else if (getMode)
      txGetKernel<<<1, 1, 0, st>>>(sendWin, recvWin, txBytes, iters, getBytes, (const uint8_t*)dRecv,
                                   (unsigned long long)gapUs * 1000ull, devComm, useTimeout ? 1 : 0, timeoutCycles, dLat, dProg,
                                   dTx, dGet, peer, txCtx);
    else
      txKernel<<<1, 1, 0, st>>>(sendWin, recvWin, txBytes, iters, reuse, badIt, badOff, (unsigned long long)gapUs * 1000ull,
                                devComm, useTimeout ? 1 : 0, timeoutCycles, dLat, dProg, dTx, contOnErr ? 1 : 0, peer, txCtx);
  }
  CK(cudaGetLastError());
  kv("launch_mono_ms=%.3f", tLaunch);
  // gin-harden: GIN_TS_HOG_MS fills every SM with a spinning kernel once the GIN kernel(s) made their first iteration
  // (they are resident by then), so a recovery has to run while the application occupies the whole GPU.
  // gin-handoff: without GIN_TS_HOG_PREALLOC the calls after the GIN launch are exactly gin-harden's (occupancy query, which
  // loads hogKernel under lazy loading, cudaMalloc of the sink, the stream); the start-time array and the probe's buffers
  // and streams are made before the GIN launch (see there), so they add nothing between the two launches.
  if (hogMs > 0) {
    // gin-harden's order of the three calls; gin-remaining: only the ones GIN_TS_HOG_CALLS lists
    if (hogLoadAfter) {
      CK(cudaDeviceGetAttribute(&hogSms, cudaDevAttrMultiProcessorCount, 0));
      CK(cudaOccupancyMaxActiveBlocksPerMultiprocessor(&hogPerSm, hogKernel, 256, 0));
    }
    if (hogMallocAfter) CK(cudaMalloc(&hogSink, sizeof(unsigned long long)));
    if (hogStreamAfter) CK(cudaStreamCreateWithFlags(&st3, cudaStreamNonBlocking));
    hogBlocks = std::min(hogCap, std::max(1, hogSms * hogPerSm - hogSlack));
    const double w0 = monoMs();
    while (*(volatile int*)hProg < 1 && *(volatile int*)hProgR < 1 && monoMs() - w0 < 2000.0) usleep(100);
    const double tHog = monoMs();
    struct timespec rt;
    clock_gettime(CLOCK_REALTIME, &rt);
    hogLaunchRtNs = (unsigned long long)rt.tv_sec * 1000000000ull + (unsigned long long)rt.tv_nsec;
    hogKernel<<<hogBlocks, 256, 0, st3>>>((unsigned long long)hogMs * 1000000ull, hogSink, hogStartDev);
    const cudaError_t he = cudaGetLastError();
    kv("hog_ms=%ld hog_sms=%d hog_blocks_per_sm=%d hog_blocks=%d hog_launch_after_launch_ms=%.1f hog_launch_err=%s "
       "hog_slack=%d hog_prealloc=%d", hogMs, hogSms, hogPerSm, hogBlocks, tHog - tLaunch, cudaGetErrorName(he), hogSlack,
       hogPrealloc ? 1 : 0);
    if (!probeSt.empty()) {
      const int np = (int)probeSt.size();
      usleep(20000);  // the GPU-filling kernel takes every block slot it can get
      const int started = hogStarted(nullptr, nullptr, nullptr);
      const double p0 = monoMs();
      for (int i = 0; i < np; i++) {
        CK(cudaMemcpyAsync(probeH + i, probeD + i, sizeof(unsigned int), cudaMemcpyDeviceToHost, probeSt[i]));
        CK(cudaEventRecord(probeEv[i], probeSt[i]));
      }
      std::vector<double> doneMs(np, -1.0);
      int nDone = 0;
      while (nDone < np && monoMs() - p0 < 200.0) {
        for (int i = 0; i < np; i++) {
          if (doneMs[i] >= 0) continue;
          const cudaError_t q = cudaEventQuery(probeEv[i]);
          if (q == cudaSuccess) {
            doneMs[i] = monoMs() - p0;
            nDone++;
          } else if (q != cudaErrorNotReady) {
            CK(q);
          }
        }
        usleep(100);
      }
      std::string stuck;
      double maxMs = 0;
      for (int i = 0; i < np; i++) {
        if (doneMs[i] < 0) stuck += (stuck.empty() ? "" : ",") + std::to_string(i);
        else maxMs = std::max(maxMs, doneMs[i]);
      }
      kv("probe_n=%d probe_done_200ms=%d probe_stuck=%s probe_max_ms=%.3f hog_started_probe=%d probe_after_hog_ms=%.1f", np,
         nDone, stuck.empty() ? "none" : stuck.c_str(), maxMs, started, p0 - tHog);
    }
  }
  // wait for the kernel(s); if the host sees an async error the application gives up (exit 3), bounded
  int exitCode = 0;
  const char* outcome = "ok";
  auto busy = [&]() {
    cudaError_t q1 = cudaStreamQuery(st), q2 = cudaStreamQuery(st2);
    if (q1 != cudaSuccess && q1 != cudaErrorNotReady) CK(q1);
    if (q2 != cudaSuccess && q2 != cudaErrorNotReady) CK(q2);
    return q1 == cudaErrorNotReady || q2 == cudaErrorNotReady;
  };
  while (true) {
    if (!busy()) break;
    if (mon.firstMs.load() >= 0) {
      const double graceMs = getenv("GIN_TS_ASYNC_GRACE_S") ? atof(getenv("GIN_TS_ASYNC_GRACE_S")) * 1000.0 : 2000.0;
      double t = monoMs();
      while (busy() && monoMs() - t < graceMs) usleep(1000);
      kv("async_grace_ms=%.0f kernel_exit_after_async_ms=%.1f", graceMs, busy() ? -1.0 : monoMs() - t);
      if (busy()) {
        outcome = "async_error_kernel_stuck";
        exitCode = 3;
      }
      break;
    }
    usleep(500);
  }
  double tEnd = monoMs();
  // gin-harden: GIN_TS_SHRINK=1 on rank 0 (rank 1 is killed by the runner): hand the failure to the application, which
  // shrinks the communicator to the survivors with NCCL_SHRINK_ABORT and checks that the result works.
  const bool shrinkMode = rank == 0 && getenv("GIN_TS_SHRINK") && atoi(getenv("GIN_TS_SHRINK")) != 0;
  bool devCommGone = false;  // gin-handoff: GIN_TS_SHRINK_DEVCOMM_DESTROY destroyed it before the shrink
  if (shrinkMode) {
    const bool doneBefore = !busy();
    kv("ho_kernel_done_before_shrink=%d ho_async_seen=%d kernel_ms_before_shrink=%.1f", doneBefore ? 1 : 0,
       mon.firstMs.load() >= 0 ? 1 : 0, tEnd - tLaunch);
    const double wdS = getenv("GIN_TS_SHRINK_WD_S") ? atof(getenv("GIN_TS_SHRINK_WD_S")) : 30.0;
    // gin-handoff: GIN_TS_SHRINK_DEVCOMM_DESTROY=1: the application-side way around the parent's GIN error: destroy the
    // devComm (its GDAKI contexts and their error state) first, only once the old kernel has ended; nothing below
    // launches a kernel on it afterwards
    if (getenv("GIN_TS_SHRINK_DEVCOMM_DESTROY") && atoi(getenv("GIN_TS_SHRINK_DEVCOMM_DESTROY")) != 0) {
      if (doneBefore) {
        const double d0 = monoMs();
        alarm((unsigned)wdS);
        const ncclResult_t dr = ncclDevCommDestroy(g_comm, &devComm);
        alarm(0);
        devCommGone = true;
        kv("ho_devcomm_destroy_rc=%s ho_devcomm_destroy_ms=%.1f", ncclGetErrorString(dr), monoMs() - d0);
      } else {
        kv("ho_devcomm_destroy_rc=skipped_kernel_running");
      }
    }
    int excl[1] = {1};
    ncclComm_t nc = nullptr;
    const double s0 = monoMs();
    kv("ho_shrink_start_mono_ms=%.3f", s0);
    alarm((unsigned)wdS);
    const ncclResult_t sr = ncclCommShrink(g_comm, excl, 1, &nc, nullptr, NCCL_SHRINK_ABORT);
    alarm(0);
    const double s1 = monoMs();
    kv("ho_shrink_rc=%s ho_shrink_ms=%.1f ho_newcomm=%d", ncclGetErrorString(sr), s1 - s0, nc != nullptr ? 1 : 0);
    {  // gin-handoff: the parent keeps its error after the shrink
      ncclResult_t pa = ncclSuccess;
      (void)ncclCommGetAsyncError(g_comm, &pa);
      kv("ho_parent_async_after=%s", ncclGetErrorString(pa));
    }
    if (sr == ncclSuccess && nc != nullptr) {
      int nr = -1;
      (void)ncclCommCount(nc, &nr);
      float* dbuf = nullptr;
      std::vector<float> hin(1024), hout(1024, -1.0f);
      for (int i = 0; i < 1024; i++) hin[i] = (float)(i + 1);
      cudaStream_t s4;
      CK(cudaStreamCreateWithFlags(&s4, cudaStreamNonBlocking));
      CK(cudaMalloc(&dbuf, 2 * 1024 * sizeof(float)));
      CK(cudaMemcpy(dbuf, hin.data(), 1024 * sizeof(float), cudaMemcpyHostToDevice));
      const double c0 = monoMs();
      const ncclResult_t ar = ncclAllReduce(dbuf, dbuf + 1024, 1024, ncclFloat, ncclSum, nc, s4);
      bool fin = false;
      while (ar == ncclSuccess && monoMs() - c0 < 5000.0) {
        const cudaError_t q = cudaStreamQuery(s4);
        if (q == cudaSuccess) { fin = true; break; }
        if (q != cudaErrorNotReady) break;
        usleep(200);
      }
      int ok = 0;
      if (fin && cudaMemcpy(hout.data(), dbuf + 1024, 1024 * sizeof(float), cudaMemcpyDeviceToHost) == cudaSuccess) {
        ok = 1;
        for (int i = 0; i < 1024; i++) ok &= (hout[i] == hin[i] * (float)nr);
      }
      ncclResult_t na = ncclSuccess;
      ncclCommGetAsyncError(nc, &na);
      kv("ho_newcomm_nranks=%d ho_allreduce_rc=%s ho_allreduce_done=%d ho_check_ok=%d ho_check_ms=%.1f ho_newcomm_async=%s",
         nr, ncclGetErrorString(ar), fin ? 1 : 0, ok, monoMs() - c0, ncclGetErrorString(na));
      alarm(15);
      const double d0 = monoMs();
      const ncclResult_t dr = ncclCommDestroy(nc);
      alarm(0);
      kv("ho_newcomm_destroy_rc=%s ho_newcomm_destroy_ms=%.1f", ncclGetErrorString(dr), monoMs() - d0);
    }
    // the old kernel: exited by now? (released with an error in the research build; see post_abort_* otherwise)
    const double hoWaitMs = (getenv("GIN_TS_HO_WAIT_S") ? atof(getenv("GIN_TS_HO_WAIT_S")) : 3.0) * 1000.0;
    const double w0 = monoMs();
    while (busy() && monoMs() - w0 < hoWaitMs) usleep(1000);
    kv("ho_old_kernel_done=%d ho_old_kernel_exit_after_shrink_ms=%.1f", busy() ? 0 : 1, busy() ? -1.0 : monoMs() - s1);
    tEnd = monoMs();
  }
  const bool kernelDone = !busy();
  kv("kernel_done=%d kernel_ms=%.1f progress=%d progress_rx=%d", kernelDone ? 1 : 0, tEnd - tLaunch, *hProg, *hProgR);
  if (shrinkMode && !kernelDone && receiver && !dual && !isBurst) {  // read the receiver again after the final abort
    g_hoPost = true;
    g_hoRx = dRx;
    g_hoSig = dSig;
    g_hoBase = bases[0];
    g_hoIters = iters;
    g_hoStream2 = st2;
  }
  if (sender && kernelDone && dual) {
    std::vector<TxOut> o(2);
    CK(cudaMemcpy(o.data(), dTxD, sizeof(TxOut) * 2, cudaMemcpyDeviceToHost));
    std::vector<unsigned long long> tS(2 * (size_t)iters), tE(2 * (size_t)iters);
    CK(cudaMemcpy(tS.data(), dTS, sizeof(unsigned long long) * 2 * iters, cudaMemcpyDeviceToHost));
    CK(cudaMemcpy(tE.data(), dTE, sizeof(unsigned long long) * 2 * iters, cudaMemcpyDeviceToHost));
    const int firstRc = o[0].rc ? o[0].rc : o[1].rc, firstRcIt = o[0].rc ? o[0].rcIt : o[1].rc ? o[1].rcIt : -1;
    kv("tx_done=%d tx_rc=%s tx_rc_it=%d dual_c0_done=%d dual_c1_done=%d dual_c0_rc=%s dual_c1_rc=%s",
       std::min(o[0].done, o[1].done), ncclGetErrorString((ncclResult_t)firstRc), firstRcIt, o[0].done, o[1].done,
       ncclGetErrorString((ncclResult_t)o[0].rc), ncclGetErrorString((ncclResult_t)o[1].rc));
    if (firstRc != 0 && exitCode == 0) { exitCode = 4; outcome = "device_error"; }
    // the held window W of context 0 (its longest completed iteration) and context 1 around it
    auto lat = [&](int c, int i) { return tE[(size_t)c * iters + i] - tS[(size_t)c * iters + i]; };
    int m = -1;
    for (int i = 0; i < o[0].done; i++)
      if (m < 0 || lat(0, i) > lat(0, m)) m = i;
    if (m >= 0 && o[1].done > 0) {
      const unsigned long long ws = tS[m], we = tE[m];
      int inWin = 0;
      long long maxIn = -1;
      unsigned long long max1 = 0;
      for (int i = 0; i < o[1].done; i++) {
        const unsigned long long s1 = tS[(size_t)iters + i], e1 = tE[(size_t)iters + i];
        if (s1 >= ws && e1 <= we) inWin++;
        if (e1 > ws && s1 < we && (long long)(e1 - s1) > maxIn) maxIn = (long long)(e1 - s1);
        if (e1 - s1 > max1) max1 = e1 - s1;
      }
      const unsigned long long last1 = tE[(size_t)iters + o[1].done - 1];
      kv("dual_win_us=%.1f dual_win_it=%d dual_c1_in_win=%d dual_c1_max_in_win_us=%.1f dual_c1_end_after_win=%d "
         "dual_c1_max_us=%.1f dual_win_start_gt=%llu dual_win_end_gt=%llu dual_c1_last_end_gt=%llu",
         (we - ws) / 1e3, m, inWin, maxIn < 0 ? -1.0 : maxIn / 1e3, last1 > we ? 1 : 0, max1 / 1e3, ws, we, last1);
    }
    for (int c = 0; c < 2; c++) {
      std::vector<unsigned long long> l((size_t)std::max(0, o[c].done));
      for (int i = 0; i < o[c].done; i++) l[i] = lat(c, i);
      latStats(c == 0 ? "lat_" : "lat1_", l);
    }
  } else if (sender && kernelDone) {
    if (isBurst) {
      std::vector<TxThr> o(P);
      CK(cudaMemcpy(o.data(), dTxT, sizeof(TxThr) * P, cudaMemcpyDeviceToHost));
      int nErr = 0, firstRc = 0, firstRcIt = -1, minDone = iters, worstT = 0;
      unsigned long long maxLat = 0;
      for (int t = 0; t < P; t++) {
        if (o[t].rc != 0) {
          if (nErr == 0) { firstRc = o[t].rc; firstRcIt = o[t].rcIt; }
          nErr++;
        }
        minDone = std::min(minDone, o[t].done);
        if (o[t].maxLatNs > maxLat) { maxLat = o[t].maxLatNs; worstT = t; }
      }
      kv("tx_done=%d tx_rc=%s tx_rc_it=%d tx_err_threads=%d tx_threads=%d tx_max_iter_us=%.1f tx_max_iter_thread=%d "
         "tx_max_iter_it=%d", minDone, ncclGetErrorString((ncclResult_t)firstRc), firstRcIt, nErr, P, maxLat / 1e3, worstT,
         o[worstT].maxLatIt);
      if (nErr && exitCode == 0) { exitCode = 4; outcome = "device_error"; }
      std::vector<unsigned long long> lat(iters);
      CK(cudaMemcpy(lat.data(), dLat, sizeof(unsigned long long) * iters, cudaMemcpyDeviceToHost));
      lat.resize(std::max(0, o[0].done));
      latStats("lat_", lat);
    } else {
      TxOut o;
      CK(cudaMemcpy(&o, dTx, sizeof(o), cudaMemcpyDeviceToHost));
      kv("tx_done=%d tx_rc=%s tx_rc_it=%d tx_start_gt=%llu tx_err_n=%d tx_err_first_lat_us=%.1f "
         "tx_err_later_max_lat_us=%.1f", o.done, ncclGetErrorString((ncclResult_t)o.rc), o.rc ? o.rcIt : -1, o.tStart,
         o.nErr, o.firstErrLatNs / 1e3, o.maxLaterErrLatNs / 1e3);
      if (o.rc != 0 && exitCode == 0) { exitCode = 4; outcome = "device_error"; }
      if (getMode) {
        GetOut go;
        CK(cudaMemcpy(&go, dGet, sizeof(go), cudaMemcpyDeviceToHost));
        kv("get_n=%d get_bad=%d get_first_bad_it=%d", go.n, go.bad, go.firstBadIt);
        if (go.bad && exitCode == 0) { exitCode = 5; outcome = "get_data_bad"; }
      }
      std::vector<unsigned long long> lat(iters);
      CK(cudaMemcpy(lat.data(), dLat, sizeof(unsigned long long) * iters, cudaMemcpyDeviceToHost));
      lat.resize(std::max(0, o.done));
      latStats("lat_", lat);
      const char* raw = getenv("GIN_LAT_RAW");
      if (raw) {
        FILE* f = fopen(raw, "w");
        if (f) {
          for (int i = 0; i < o.done; i++) fprintf(f, "%d,%llu\n", i, lat[i]);
          fclose(f);
        }
      }
    }
  }
  if (receiver && kernelDone && dual) {
    std::vector<RxOut> o(2);
    CK(cudaMemcpy(o.data(), dRxD, sizeof(RxOut) * 2, cudaMemcpyDeviceToHost));
    const int rxRc = o[0].rc ? o[0].rc : o[1].rc, rxRcIt = o[0].rc ? o[0].rcIt : o[1].rc ? o[1].rcIt : -1;
    const int rxDone = std::min(o[0].done, o[1].done), devBad = o[0].badSlots + o[1].badSlots;
    const int devFirstBad = o[0].badSlots ? o[0].firstBad : o[1].badSlots ? o[1].firstBad : -1;
    kv("rx_done=%d rx_rc=%s rx_rc_it=%d dev_bad_slots=%d dev_first_bad=%d dual_rx_c0_done=%d dual_rx_c1_done=%d", rxDone,
       ncclGetErrorString((ncclResult_t)rxRc), rxRcIt, devBad, devFirstBad, o[0].done, o[1].done);
    if (rxRc != 0 && exitCode == 0) { exitCode = 4; outcome = "device_error"; }
    int badSlots = 0, firstBad = -1, missing = 0;
    const long nSlots = 2L * iters;
    CK(cudaMemcpy(h.data(), dRecv, winBytes, cudaMemcpyDeviceToHost));
    for (long s = 0; s < nSlots; s++) {
      const int c = (int)(s / iters), i = (int)(s % iters);
      size_t bad = 0, pois = 0;
      for (size_t k = 0; k < bytes; k++) {
        const uint8_t x = h[(size_t)s * bytes + k];
        if (x != pat(i, k, (uint32_t)c + 1)) bad++;
        if (x == POISON) pois++;
      }
      if (bad && pois == bytes) missing++;
      if (bad) {
        if (firstBad < 0) firstBad = (int)s;
        badSlots++;
      }
    }
    std::vector<unsigned long long> fin(2);
    for (int c = 0; c < 2 && !devCommGone; c++) {  // gin-handoff: not on a destroyed devComm (kv final_signal_read)
      readSigKernel<<<1, 256, 0, st>>>(devComm, dBases, 1, c);
      CK(cudaStreamSynchronize(st));
      CK(cudaMemcpy(&fin[c], dBases, sizeof(unsigned long long), cudaMemcpyDeviceToHost));
    }
    if (devCommGone) kv("final_signal_read=skipped_devcomm_destroyed");
    int sigBad = 0, sigHigh = 0, sigLow = 0;
    for (int c = 0; c < 2; c++) {
      const unsigned long long want = dualBases[c] + (unsigned long long)iters;
      if (fin[c] != want) {
        sigBad++;
        if (fin[c] > want) sigHigh++;
        else sigLow++;
      }
    }
    kv("host_bad_slots=%d host_first_bad=%d host_missing_slots=%d host_slots=%ld final_signal=%llu expected_final=%llu "
       "signal_exact=%d signals=2 signals_bad=%d signals_high=%d signals_low=%d dual_final_signal1=%llu dual_expected_final1=%llu",
       badSlots, firstBad, missing, nSlots, fin[0], dualBases[0] + (unsigned long long)iters, sigBad == 0 ? 1 : 0, sigBad,
       sigHigh, sigLow, fin[1], dualBases[1] + (unsigned long long)iters);
    if (rxDone == iters && (badSlots || devBad || sigBad) && exitCode == 0) {
      exitCode = 5;
      outcome = "check_failed";
    }
  } else if (receiver && kernelDone) {
    int rxRc = 0, rxRcIt = -1, rxDone = iters, devBad = 0, devFirstBad = -1;
    if (isBurst) {
      std::vector<RxThr> o(NS);
      CK(cudaMemcpy(o.data(), dRxT, sizeof(RxThr) * NS, cudaMemcpyDeviceToHost));
      for (int t = 0; t < NS; t++) {
        if (o[t].rc != 0 && rxRc == 0) { rxRc = o[t].rc; rxRcIt = o[t].rcIt; }
        rxDone = std::min(rxDone, o[t].done);
        if (o[t].badSlots && devFirstBad < 0) devFirstBad = o[t].firstBad;
        devBad += o[t].badSlots;
      }
    } else {
      RxOut o;
      CK(cudaMemcpy(&o, dRx, sizeof(o), cudaMemcpyDeviceToHost));
      rxRc = o.rc;
      rxRcIt = o.rc ? o.rcIt : -1;
      rxDone = o.done;
      devBad = o.badSlots;
      devFirstBad = o.badSlots ? o.firstBad : -1;
      // gin-harden: waits that returned ncclSuccess without their signal (the value read was below the target)
      std::vector<unsigned long long> seen((size_t)iters);
      CK(cudaMemcpy(seen.data(), dSig, sizeof(unsigned long long) * iters, cudaMemcpyDeviceToHost));
      int pf = -1;
      const int ph = phantomCount(seen.data(), std::max(0, std::min(o.done, iters)), bases[0], &pf);
      kv("rx_phantom=%d rx_phantom_first=%d", ph, pf);
    }
    kv("rx_done=%d rx_rc=%s rx_rc_it=%d dev_bad_slots=%d dev_first_bad=%d", rxDone,
       ncclGetErrorString((ncclResult_t)rxRc), rxRcIt, devBad, devFirstBad);
    if (rxRc != 0 && exitCode == 0) { exitCode = 4; outcome = "device_error"; }
    // host re-check of every slot, and every signal exactly once
    int badSlots = 0, firstBad = -1, missing = 0;
    const long nSlots = reuse ? 0 : (long)iters * P * K;
    if (!reuse) {
      CK(cudaMemcpy(h.data(), dRecv, winBytes, cudaMemcpyDeviceToHost));
      for (long s = 0; s < nSlots; s++) {
        size_t bad = 0, pois = 0;
        if (isBurst) {
          const int k = (int)(s % K), t = (int)((s / K) % P), i = (int)(s / K / P);
          const uint32_t* hw = (const uint32_t*)(h.data() + (size_t)s * bytes);
          for (size_t w = 0; w < bytes / 4; w++) {
            if (hw[w] != patW(i, t, k, w)) bad++;
            if (hw[w] == 0xA5A5A5A5u) pois++;
          }
          if (bad && pois == bytes / 4) missing++;
        } else {
          for (size_t k = 0; k < rxBytes; k++) {
            uint8_t x = h[(size_t)s * rxBytes + k];
            if (x != pat((int)s, k, rxSeed)) bad++;
            if (x == POISON) pois++;
          }
          if (bad && pois == rxBytes) missing++;
        }
        if (bad) {
          if (firstBad < 0) firstBad = (int)s;
          badSlots++;
        }
      }
    }
    std::vector<unsigned long long> fin(NS);
    if (!devCommGone) {  // gin-handoff: not on a destroyed devComm
      readSigKernel<<<1, 256, 0, st>>>(devComm, dBases, NS, rxCtx);
      CK(cudaStreamSynchronize(st));
      CK(cudaMemcpy(fin.data(), dBases, sizeof(unsigned long long) * NS, cudaMemcpyDeviceToHost));
    } else {
      kv("final_signal_read=skipped_devcomm_destroyed");
    }
    int sigBad = 0, sigHigh = 0, sigLow = 0;
    for (int t = 0; t < NS; t++) {
      const unsigned long long want = bases[t] + (unsigned long long)iters * (P / NS);
      if (fin[t] != want) {
        sigBad++;
        if (fin[t] > want) sigHigh++;
        else sigLow++;
      }
    }
    kv("host_bad_slots=%d host_first_bad=%d host_missing_slots=%d host_slots=%ld final_signal=%llu expected_final=%llu "
       "signal_exact=%d signals=%d signals_bad=%d signals_high=%d signals_low=%d",
       badSlots, firstBad, missing, nSlots, fin[0], bases[0] + (unsigned long long)iters * (P / NS), sigBad == 0 ? 1 : 0, NS, sigBad,
       sigHigh, sigLow);
    if (rxDone == iters && (badSlots || devBad || sigBad) && exitCode == 0) {
      exitCode = 5;
      outcome = "check_failed";
    }
  }
  if (!kernelDone && exitCode == 0) { exitCode = 7; outcome = "kernel_stuck"; }
  const double endWaitS = getenv("GIN_TS_END_WAIT_S") ? atof(getenv("GIN_TS_END_WAIT_S")) : 0.3;
  usleep((useconds_t)(endWaitS * 1e6));
  const char* monAbort = getenv("GIN_TS_MON_ABORT");
  if (monAbort && *monAbort) {
    mon.abortLimitMs = strcmp(monAbort, "full") == 0 ? 0.0 : atof(monAbort);
    g_mon = &mon;
    g_monTh = &monTh;
  } else {
    mon.stop.store(true);
    monTh.join();
  }
  ncclResult_t fa = ncclSuccess;
  ncclCommGetAsyncError(g_comm, &fa);
  if (mon.firstMs.load() >= 0 && exitCode == 0) { exitCode = 3; outcome = "async_error"; }
  recoveryStats(g_comm);  // gin-harden
  if (st3 != nullptr) kv("hog_running_at_end=%d", cudaStreamQuery(st3) == cudaErrorNotReady ? 1 : 0);
  if (st3 != nullptr) {  // gin-handoff
    // first and last block start against the host's CLOCK_REALTIME at the launch call (globaltimer follows the host's
    // real-time clock; approximate, for telling "at once" from "seconds later")
    double spread = -1.0;
    unsigned long long first = 0, last = 0;
    const int started = hogStarted(&spread, &first, &last);
    int pDone = 0;
    for (auto& e : probeEv) pDone += cudaEventQuery(e) == cudaSuccess ? 1 : 0;
    kv("hog_started_end=%d hog_start_spread_ms=%.1f hog_first_start_rel_ms=%.1f hog_last_start_rel_ms=%.1f probe_done_end=%d",
       started, spread, started ? ((double)first - (double)hogLaunchRtNs) / 1e6 : -1.0,
       started ? ((double)last - (double)hogLaunchRtNs) / 1e6 : -1.0, pDone);
  }
  kv("async_first=%s async_first_ms_after_launch=%.1f async_err_samples=%ld async_samples=%ld final_async=%s",
     mon.firstMs.load() >= 0 ? ncclGetErrorString((ncclResult_t)mon.firstErr.load()) : "none",
     mon.firstMs.load() >= 0 ? mon.firstMs.load() - tLaunch : -1.0, mon.errSamples.load(), mon.samples.load(),
     ncclGetErrorString(fa));
  kv("outcome=%s", outcome);
  fprintf(stderr, "[rank%d] DONE outcome=%s exit=%d progress=%d/%d rx=%d\n", rank, outcome, exitCode, *hProg, iters,
          *hProgR);
  teardownExit(exitCode);
  return exitCode;
}
