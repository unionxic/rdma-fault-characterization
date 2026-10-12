// gin_rs.cu - gin-restore work package 10: the test workload of EXPERIMENT.md 9.8 (DRAFT; built, not run). A 4-rank NCCL
// GIN (GDAKI) application, two ranks per GPU (NCCL_MULTI_RANK_GPU_ENABLE=1): rain holds ranks 0 and 2, sunny 1 and 3. It
// calls the three public restore hooks: ncclGinRestoreResume after ncclDevCommCreate, ncclGinRestoreStep between step
// kernels, ncclGinRestoreRegister for extra device state. As a spare process (NCCL_GIN_RESTORE_SPARE=<its logical rank>) it
// re-executes from the step Resume reports.
//
// One source, two builds (build_rs_test.sh):
//   gin_rs     against this layer's headers with -DNCCL_GIN_RESTORE_DEVICE (EXPERIMENT.md 12, the build-time opt-in, choice
//              (b)): with the integrated library the macro puts the hold branch in the device send path.
//   gin_rs_hk  against gpu-detect's hk headers, without the macro: the no-restore control (rs4_kill3@hk). hk's libnccl has no
//              restore symbols, so the three hooks are looked up with dlsym and skipped when absent (kv rs_api=0).
//
// Not-yet-integrated library (work packages 5-9 pending): Resume returns success with *step = 0 (a first incarnation; the
// communicator stays fail-fast), Step returns ncclInvalidUsage with NCCL_GIN_RESTORE_STEP_NONE, Register is not implemented.
// The program then runs a clean exchange; a kill cell falls back (no revival); kv rs_hooks_live=0 says the Step hook did not
// run, and score.py does not score the cells that need the restore reaction (impl/notes_test.md lists what is not exercised).
//
// Workload (9.8). N = 4, one receive context per rank (ctx = the receiving rank), so every put to rank b lands on b's
// context b and b's waitSignal on that context names no peer (the target situation). Step s, one kernel per step:
//   (1) sender CTA per other rank d: build B bytes on the device from the state x_r(s) (window) and (r, d, s) into the send
//       slot (d, s), then put + signal-increment-1 into d's recv slot (r, s) on context d;
//   (2) a flush of that context (one posting thread per context, 9.7 req 5);
//   (3) the receiver CTA waits, untimed, on its own context until its step-s signal reaches the step's target (a return below
//       the target is a release: a survivor wait let go, counted);
//   (4) it reads this step's N-1 slots (each carries the sender's value in its first 8 bytes) and computes x_r(s+1);
//   (5) it increments the step-execution counter of step s (a re-execution shows as a count > 1).
// Signals by step parity (a deviation from 9.8's "signal 0", impl/notes_test.md): with one shared signal, a rank that is one
// step ahead can add its step-(s+1) put to the counter before a slower sender's step-s put to the same receiver has
// arrived, so the step-s threshold can be met with a step-s slot still empty (a race against 9.7 req 1). A sender can be at
// most one step ahead (it cannot finish step s+1 before every rank sent its step-(s+1) put, and a rank sends step s+1 only
// after its step-s receive). So step s's puts add to signal s % 2, and the step-s wait is signal (s % 2) >= (N-1) *
// (s / 2 + 1): exact, still naming no peer.
// Single assignment (9.7 req 3): a slot per (peer, step) in both windows; the state history x(0..S) is single-assignment
// too (xHist[s+1] written once). Branch only on the step number (req 2); no get (req 4, 8); one kernel per step with a
// flush (req 7); no signal reset (req 9); end with ncclCommAbort (req 10); one devComm, one GIN connection (req 11); a put's
// source slot is never rewritten (req 12: the descriptor-only log re-reads it).
//
// Exact result check (9.8): (b) at the end every recv slot of every step is compared bit-for-bit on the host with the
// reference sendValue(x_src(s), src, me, s) computed by the same host/device functions, and every state x(t) with the
// reference; the final value of both signals must be exact (a duplicated or lost signal shows); (c) the per-step execution
// counters; (a) released waits, receive/flush errors and the communicator's async error (polled); (e) is the library's.
//
// Buddy: the rank on the other node with the same local slot. With the interleaved placement (even ranks on rain, odd on
// sunny) that is r XOR 1 (buddy(3) = 2 as in EXPERIMENT.md 5). Reported in kv; the library places the checkpoint.
//
// Lines on stdout (the runner stamps each with rain's CLOCK_MONOTONIC at receipt, the house receipt-clock style):
//   GINRS start|resume|step|async|die|end ...   (one line per event; mono_ms is this process's own clock, for reference)
//
// usage: gin_rs <rank> <nranks> <rank0_ip> <port> <out_kv>     (a spare ignores rank0_ip and port: no rendezvous)
// env: RS_RDV_NONCE (16 hex; a rank r > 0 sends nothing before it checked rank 0's greeting "GINRS_01" + nonce),
//   RS_STEPS (40), RS_BYTES (4096; multiple of 8), RS_DEV (0), RS_WATCHDOG_S (90), RS_ASYNC_POLL_US (200),
//   RS_START_GATE=<path> and RS_START_GATE_S (150): rank 0 waits for the file before the first step (a spare gets ready),
//   RS_STEP_GAP_US (0: a host pause after each step's hook; pacing only), RS_END_GRACE_MS (0: a live rank's pause before
//   its final ncclCommAbort, so a revived rank finishes its last step and checks first),
//   GIN_RS_DIE_AT=<step>:<us> (self-SIGKILL us after launching that step's kernel: a kill during normal traffic),
//   GIN_RS_DIE_IN_STEP=<every>:<us> and GIN_RS_ARM_FILE=<path> (once the file exists, SIGKILL itself us after entering the
//     checkpoint hook of the next step s with s % every == 0: a kill inside the checkpoint's input pause)
// kv (one file per process; *_rc = numeric ncclResult_t): mode, rank, nranks, buddy, steps, bytes, rs_device_macro, rs_api,
//   init_rc/_ms, reg_rc/_ms, devcomm_rc/_ms, register_rc, resume_rc/_ms, resume_step, resume_why, dc_*, rs_hooks_live,
//   steps_done, released, released_step, tx_err, rx_err, dev_bad, recv_bad, xhist_bad, x_match, reexec_max, reexec_any,
//   sig0, sig0_want, sig1, sig1_want, sig_exact, async_first, async_n, stable_last, xchg (ok|bad|released|hung|refused),
//   abort_rc, abort_ms, exit
// exit: 0 every step ok and every check exact (or a refusal reported); 2 an NCCL call failed; 3 a spare not given its blob;
//   4 a check failed or a wait was released; 6 CUDA error; 7 watchdog; 1 usage or rendezvous.
#include <nccl.h>
#include "nccl_device.h"
#include <cuda_runtime.h>
#include <arpa/inet.h>
#include <dlfcn.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <sys/socket.h>
#include <unistd.h>
#include <atomic>
#include <cerrno>
#include <chrono>
#include <csignal>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <string>
#include <thread>
#include <vector>

#ifndef NCCL_GIN_RESTORE_STEP_NONE
#define NCCL_GIN_RESTORE_STEP_NONE (~0ULL)  // the hk headers have no restore API
#endif
typedef ncclResult_t (*RsResumeFn)(ncclComm_t, const struct ncclDevComm*, unsigned long long*, void*, size_t*);
typedef ncclResult_t (*RsStepFn)(ncclComm_t, unsigned long long, const void*, size_t, unsigned long long*);
typedef ncclResult_t (*RsRegisterFn)(ncclComm_t, void*, size_t);

static FILE* g_kv = nullptr;
static int g_rank = -1;
static ncclComm_t g_comm = nullptr;
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

// ---- the deterministic state cascade (host and device compute the same bytes) ----
__host__ __device__ static inline uint64_t seedState(int r) {
  return 0x9E3779B97F4A7C15ull ^ (0xA5A5A5A5ull * (uint64_t)(r + 1));
}
__host__ __device__ static inline uint64_t mix64(uint64_t z) {
  z += 0x9E3779B97F4A7C15ull;
  z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ull;
  z = (z ^ (z >> 27)) * 0x94D049BB133111EBull;
  return z ^ (z >> 31);
}
// the value rank r sends to d at step s, from its state x_r(s)
__host__ __device__ static inline uint64_t sendValue(uint64_t xr, int r, int d, int s) {
  return mix64(xr ^ (0x100000001B3ull * (uint64_t)(r * 131 + d * 17 + s * 7 + 1)));
}
// byte idx of the cell carrying v: the first 8 bytes are v itself (little-endian), the rest a mix of v and idx
__host__ __device__ static inline uint8_t cellByte(uint64_t v, size_t idx) {
  if (idx < 8) return (uint8_t)((v >> (8 * idx)) & 0xff);
  return (uint8_t)(mix64(v ^ ((uint64_t)idx * 2654435761ull)) & 0xff);
}
__host__ __device__ static inline int idxOf(int x, int owner) { return x < owner ? x : x - 1; }
// x_r(s+1): fold the values rank r received at step s (recvVals[src], src != r) into x_r(s)
__host__ __device__ static inline uint64_t nextState(uint64_t xr, int r, int n, const uint64_t* recvVals) {
  uint64_t acc = xr;
  for (int src = 0; src < n; src++)
    if (src != r) acc = mix64(acc ^ recvVals[src]);
  return acc;
}
// the step-s target of signal (s % 2): (N-1) puts per step of that parity, steps 0..s of that parity
__host__ __device__ static inline unsigned long long stepTarget(int n, int s) {
  return (unsigned long long)(n - 1) * (unsigned long long)(s / 2 + 1);
}

struct Out {
  int txErr, rxErr, devBad, released, reexec, pad0;
  unsigned long long got, want;
};
// CTA k < N-1: the sender to the k-th other rank (context = that rank); CTA N-1: the receiver (context = this rank)
__global__ void stepKernel(ncclWindow_t sendWin, ncclWindow_t recvWin, uint8_t* sendBuf, const uint8_t* recvBuf,
                           uint64_t* xHist, int* execCnt, size_t bytes, int n, int me, int s, size_t regionBytes,
                           struct ncclDevComm devComm, Out* out) {
  const int k = blockIdx.x;
  __shared__ int sRc, sBad, sRel;
  __shared__ uint64_t sRecv[8];
  if (k < n - 1) {
    const int d = k < me ? k : k + 1;
    const uint64_t x = ((volatile uint64_t*)xHist)[s];  // x_me(s): written before this launch (host or step s-1)
    const uint64_t v = sendValue(x, me, d, s);
    const size_t lo = (size_t)idxOf(d, me) * regionBytes + (size_t)s * bytes;  // send slot (d, s) of this rank
    const size_t ro = (size_t)idxOf(me, d) * regionBytes + (size_t)s * bytes;  // recv slot (me, s) of rank d
    for (size_t b = threadIdx.x; b < bytes; b += blockDim.x) sendBuf[lo + b] = cellByte(v, b);
    __threadfence_system();  // the slot is GPU memory the NIC reads: every thread's bytes visible before the post
    if (threadIdx.x == 0) sRc = 0;
    __syncthreads();
    ncclGin gin{devComm, d};
    if (threadIdx.x == 0)
      gin.put(ncclTeamWorld(devComm), d, recvWin, ro, sendWin, lo, bytes, ncclGin_WeakSignalInc{(unsigned)(s & 1)});
    ncclResult_t rc = gin.flush(ncclCoopCta());
    if (rc != ncclSuccess) atomicCAS(&sRc, 0, (int)rc);
    __syncthreads();
    if (threadIdx.x == 0 && sRc != 0) atomicAdd(&out->txErr, 1);
  } else {
    ncclGin gin{devComm, me};
    const unsigned sig = (unsigned)(s & 1);
    const unsigned long long want = stepTarget(n, s);
    // untimed: returns at the target, or when the devComm abort word rises (a release)
    gin.waitSignal(ncclCoopCta(), sig, want, 64, cuda::memory_order_acquire);
    if (threadIdx.x == 0) {
      const unsigned long long got = (unsigned long long)gin.readSignal(sig);
      out->got = got;
      out->want = want;
      sRel = got < want ? 1 : 0;
      out->released = sRel;
      sBad = 0;
    }
    __syncthreads();
    if (sRel) return;  // a released survivor: do not read slots that may not have arrived
    for (int src = 0; src < n; src++) {
      if (src == me) continue;
      const uint8_t* slot = recvBuf + (size_t)idxOf(src, me) * regionBytes + (size_t)s * bytes;
      if (threadIdx.x == 0) {
        uint64_t v = 0;
        for (int b = 0; b < 8; b++) v |= (uint64_t)((volatile const uint8_t*)slot)[b] << (8 * b);
        sRecv[src] = v;
      }
      __syncthreads();
      const uint64_t v = sRecv[src];
      int bad = 0;
      for (size_t b = threadIdx.x; b < bytes; b += blockDim.x)
        if (((volatile const uint8_t*)slot)[b] != cellByte(v, b)) bad = 1;
      if (bad) atomicOr(&sBad, 1);
      __syncthreads();
    }
    if (threadIdx.x == 0) {
      if (sBad) out->devBad = 1;
      xHist[s + 1] = nextState(((volatile uint64_t*)xHist)[s], me, n, sRecv);
      __threadfence_system();
      const int c = ++execCnt[s];
      out->reexec = c;
    }
  }
}
__global__ void readSigKernel(struct ncclDevComm devComm, int ctx, unsigned long long* v) {
  ncclGin gin{devComm, ctx};
  if (threadIdx.x == 0) {
    v[0] = (unsigned long long)gin.readSignal(0);
    v[1] = (unsigned long long)gin.readSignal(1);
  }
}

// ---- rendezvous (live ranks only) ----
static const char kMagic[8] = {'G', 'I', 'N', 'R', 'S', '_', '0', '1'};
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
// a reason string as one kv token (whitespace, '=' and quotes replaced)
static std::string token(const char* s) {
  std::string t = s ? s : "";
  for (auto& ch : t)
    if (ch == ' ' || ch == '\t' || ch == '=' || ch == '\n' || ch == '"') ch = '_';
  if (t.empty()) t = "none";
  return t;
}

// the host-side reference: every rank's state at every step
static void hostReference(int n, int steps, std::vector<std::vector<uint64_t>>& xAll /* [step][rank] */) {
  xAll.assign((size_t)steps + 1, std::vector<uint64_t>((size_t)n, 0));
  for (int r = 0; r < n; r++) xAll[0][(size_t)r] = seedState(r);
  for (int s = 0; s < steps; s++)
    for (int r = 0; r < n; r++) {
      uint64_t recv[8] = {0};
      for (int src = 0; src < n; src++)
        if (src != r) recv[src] = sendValue(xAll[(size_t)s][(size_t)src], src, r, s);
      xAll[(size_t)s + 1][(size_t)r] = nextState(xAll[(size_t)s][(size_t)r], r, n, recv);
    }
}

// the communicator's async error, polled (9.8 (a): a survivor must see none)
static std::atomic<bool> g_asyncStop{false};
static std::atomic<int> g_asyncFirst{0};
static std::atomic<long> g_asyncN{0};
static void asyncPoll(useconds_t us) {
  while (!g_asyncStop.load()) {
    ncclResult_t s = ncclSuccess;
    if (g_comm && ncclCommGetAsyncError(g_comm, &s) == ncclSuccess && s != ncclSuccess && s != ncclInProgress) {
      if (g_asyncN.fetch_add(1) == 0) {
        g_asyncFirst.store((int)s);
        printf("GINRS async rank=%d err=%d mono_ms=%.3f\n", g_rank, (int)s, monoMs());
      }
    }
    usleep(us);
  }
}

int main(int argc, char** argv) {
  setvbuf(stdout, nullptr, _IOLBF, 0);
  if (argc < 6) {
    fprintf(stderr, "usage: %s <rank> <nranks> <rank0_ip> <port> <out_kv>\n", argv[0]);
    return 1;
  }
  const int rank = atoi(argv[1]), N = atoi(argv[2]), port = atoi(argv[4]);
  const char* rank0Ip = argv[3];
  g_rank = rank;
  g_kv = fopen(argv[5], "w");
  if (!g_kv || N < 2 || N > 6 || rank < 0 || rank >= N) return 1;
  const char* spareEnv = getenv("NCCL_GIN_RESTORE_SPARE");
  const bool spare = spareEnv && *spareEnv && atoi(spareEnv) == rank;
  const int steps = getenv("RS_STEPS") ? atoi(getenv("RS_STEPS")) : 40;
  size_t bytes = getenv("RS_BYTES") ? (size_t)atol(getenv("RS_BYTES")) : 4096;
  if (bytes < 8) bytes = 8;
  bytes &= ~(size_t)7;
  const int wdS = getenv("RS_WATCHDOG_S") ? atoi(getenv("RS_WATCHDOG_S")) : 90;
  const int dev = getenv("RS_DEV") ? atoi(getenv("RS_DEV")) : 0;
  const useconds_t pollUs = getenv("RS_ASYNC_POLL_US") ? (useconds_t)atoi(getenv("RS_ASYNC_POLL_US")) : 200u;
  // a host pause after each step's hook (pacing only: no effect on the data; it lets a kill land inside the traffic)
  const useconds_t gapUs = getenv("RS_STEP_GAP_US") ? (useconds_t)atoi(getenv("RS_STEP_GAP_US")) : 0u;
  // a pause before the final ncclCommAbort (a kill cell: the revived rank may still be in its last step and checks)
  const long endGraceMs = getenv("RS_END_GRACE_MS") ? atol(getenv("RS_END_GRACE_MS")) : 0;
  const char* dieAt = getenv("GIN_RS_DIE_AT");
  const int dieStep = dieAt ? atoi(dieAt) : -1;
  const long dieUs = (dieAt && strchr(dieAt, ':')) ? atol(strchr(dieAt, ':') + 1) : 0;
  // a kill inside the checkpoint hook: GIN_RS_DIE_IN_STEP=<every>:<us>: once armed (GIN_RS_ARM_FILE exists, checked before
  // each hook; no file named: armed from the start), at the first step s with s % every == 0 a thread SIGKILLs this process
  // us after the hook (ncclGinRestoreStep) was entered, so the kill lands inside the checkpoint's input pause when the pause
  // lasts longer than us (`every` = NCCL_GIN_RESTORE_CKPT_STEPS: the steps that take a checkpoint)
  const char* dieIn = getenv("GIN_RS_DIE_IN_STEP");
  const int dieEvery = dieIn ? atoi(dieIn) : 0;
  const long dieInUs = (dieIn && strchr(dieIn, ':')) ? atol(strchr(dieIn, ':') + 1) : 300;
  const char* armFile = getenv("GIN_RS_ARM_FILE");
  const int macro =
#ifdef NCCL_GIN_RESTORE_DEVICE
    1;
#else
    0;
#endif
  RsResumeFn rsResume = (RsResumeFn)dlsym(RTLD_DEFAULT, "ncclGinRestoreResume");
  RsStepFn rsStep = (RsStepFn)dlsym(RTLD_DEFAULT, "ncclGinRestoreStep");
  RsRegisterFn rsRegister = (RsRegisterFn)dlsym(RTLD_DEFAULT, "ncclGinRestoreRegister");
  const int rsApi = (rsResume && rsStep && rsRegister) ? 1 : 0;
  const int buddy = rank ^ 1;
  kv("mode=%s rank=%d nranks=%d buddy=%d steps=%d bytes=%zu rs_device_macro=%d rs_api=%d die_at=%d:%ld die_in_step=%d:%ld "
     "arm_file=%d",
     spare ? "spare" : "live", rank, N, buddy, steps, bytes, macro, rsApi, dieStep, dieUs, dieEvery, dieInUs,
     armFile ? 1 : 0);
  printf("GINRS start rank=%d mode=%s mono_ms=%.3f\n", rank, spare ? "spare" : "live", monoMs());

  std::thread([wdS]() {
    std::this_thread::sleep_for(std::chrono::seconds(wdS));
    static const char m[] = "WATCHDOG: gin_rs exceeded its bound; exiting 7\n";
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
          rejected++;
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

  CK(cudaSetDevice(dev));
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
  g_comm = comm;

  // send window: N-1 regions of `steps` slots, then the state history x(0..steps) (256-byte aligned); recv window: N-1
  // regions of `steps` slots. Both are windows, so the restore checkpoints them (9.4 (a)).
  const size_t regionBytes = bytes * (size_t)steps;
  const size_t slotsBytes = regionBytes * (size_t)(N - 1);
  const size_t xOff = (slotsBytes + 255) & ~(size_t)255;
  const size_t sendNeed = xOff + sizeof(uint64_t) * (size_t)(steps + 1);
  const size_t round2M = (size_t)2 << 20;
  const size_t sendBytes = ((sendNeed + round2M - 1) / round2M) * round2M;
  const size_t recvBytes = ((slotsBytes + round2M - 1) / round2M) * round2M;
  void *dSend = nullptr, *dRecv = nullptr;
  ncclWindow_t sendWin = nullptr, recvWin = nullptr;
  t0 = monoMs();
  ncclResult_t r1 = ncclMemAlloc(&dSend, sendBytes);
  if (r1 == ncclSuccess) r1 = ncclMemAlloc(&dRecv, recvBytes);
  if (r1 == ncclSuccess) r1 = ncclCommWindowRegister(comm, dSend, sendBytes, &sendWin, NCCL_WIN_COLL_SYMMETRIC);
  if (r1 == ncclSuccess) r1 = ncclCommWindowRegister(comm, dRecv, recvBytes, &recvWin, NCCL_WIN_COLL_SYMMETRIC);
  kv("reg_rc=%d reg_ms=%.1f send_win_bytes=%zu recv_win_bytes=%zu", (int)r1, monoMs() - t0, sendBytes, recvBytes);
  if (r1 != ncclSuccess) {
    kv("exit=2");
    _exit(2);
  }
  uint64_t* dxHist = (uint64_t*)((char*)dSend + xOff);
  // the step-execution counters: extra device state, registered with the restore (9.4 (b))
  int* dExec = nullptr;
  CK(cudaMalloc(&dExec, sizeof(int) * (size_t)steps));
  CK(cudaMemset(dExec, 0, sizeof(int) * (size_t)steps));
  CK(cudaMemset(dRecv, 0, recvBytes));
  CK(cudaMemset(dSend, 0, sendBytes));
  const uint64_t x0 = seedState(rank);
  CK(cudaMemcpy(dxHist, &x0, sizeof(uint64_t), cudaMemcpyHostToDevice));
  CK(cudaDeviceSynchronize());

  ncclDevComm devComm;
  memset(&devComm, 0, sizeof(devComm));
  ncclDevCommRequirements reqs = NCCL_DEV_COMM_REQUIREMENTS_INITIALIZER;
  reqs.ginContextCount = N;  // one context per receiving rank (ctx = dst)
  reqs.ginSignalCount = 2;   // signal (s % 2) of the step parity (see the header)
  reqs.ginConnectionType = NCCL_GIN_CONNECTION_FULL;
  t0 = monoMs();
  ncclResult_t r2 = ncclDevCommCreate(comm, &reqs, &devComm);
  kv("devcomm_rc=%d devcomm_ms=%.1f", (int)r2, monoMs() - t0);
  if (r2 != ncclSuccess) {
    kv("exit=2");
    _exit(2);
  }
  kv("dc_rank=%d dc_nranks=%d dc_lsa_rank=%d dc_lsa_size=%d dc_gin_contexts=%u dc_gin_signals=%d dc_gin_connections=%d",
     devComm.rank, devComm.nRanks, devComm.lsaRank, devComm.lsaSize, devComm.ginContextCount, devComm.ginSignalCount,
     (int)devComm.ginConnectionCount);

  const ncclResult_t rreg = rsApi ? rsRegister(comm, dExec, sizeof(int) * (size_t)steps) : ncclSuccess;
  kv("register_rc=%d", (int)rreg);

  // the application host blob of a step: what Resume hands back to a revived rank
  struct Blob {
    unsigned long long step;
    uint64_t x;
    int rank, nranks;
  } blob;
  memset(&blob, 0, sizeof(blob));
  blob.x = x0;
  blob.rank = rank;
  blob.nranks = N;
  unsigned long long resumeStep = 0;
  size_t blobBytes = sizeof(blob);
  ncclResult_t r3 = ncclSuccess;
  std::string why = "none";
  if (spare) {  // init replay done; Resume now waits for the activation. rt_s (CLOCK_REALTIME) lines up with strace -ttt
    struct timespec rt;
    clock_gettime(CLOCK_REALTIME, &rt);
    printf("GINRS spare_ready rank=%d mono_ms=%.3f rt_s=%.6f\n", rank, monoMs(), rt.tv_sec + rt.tv_nsec * 1e-9);
  }
  t0 = monoMs();
  if (rsApi) {
    r3 = rsResume(comm, &devComm, &resumeStep, &blob, &blobBytes);
    if (r3 != ncclSuccess) why = token(ncclGetLastError(comm));
  }
  kv("resume_rc=%d resume_ms=%.1f resume_step=%llu resume_bytes=%zu resume_why=%s", (int)r3, monoMs() - t0, resumeStep,
     blobBytes, why.c_str());
  printf("GINRS resume rank=%d rc=%d step=%llu mono_ms=%.3f\n", rank, (int)r3, resumeStep, monoMs());
  // a refusal (the "cannot be enabled" cells): every rank reports it and ends after the abort, so nothing runs fail-fast
  // silently after a refused Resume
  if (r3 != ncclSuccess) {
    t0 = monoMs();
    const ncclResult_t ar = ncclCommAbort(comm);
    kv("xchg=refused abort_rc=%d abort_ms=%.1f exit=0", (int)ar, monoMs() - t0);
    _exit(0);
  }
  // a revived rank resumes at the step its own blob names (the blob of checkpoint k was written after step k: blob.step =
  // k + 1, the next step to run, and blob.x = x(k + 1)); this does not depend on whether *step is the checkpoint's name
  // or the next step. The windows (x history, slots) and the registered counters are restored by the library.
  // revived: a spare whose Resume handed back a blob of this program (whatever *step names; a first incarnation gets
  // *bytes = 0, so a live rank never matches)
  const bool revived = spare && blobBytes == sizeof(blob) && blob.rank == rank && blob.nranks == N && blob.step > 0 &&
                       (int)blob.step <= steps;
  const int startStep = revived ? (int)blob.step : 0;
  kv("revived=%d start_step=%d blob_step=%llu", revived ? 1 : 0, startStep, blob.step);
  if (spare && !revived) {  // Resume returned to a spare without its blob: running from step 0 would corrupt the survivors
    kv("spare_not_revived=1");
    t0 = monoMs();
    const ncclResult_t ar = ncclCommAbort(comm);
    kv("abort_rc=%d abort_ms=%.1f exit=3", (int)ar, monoMs() - t0);
    _exit(3);
  }
  if (revived) CK(cudaMemcpy(dxHist + startStep, &blob.x, sizeof(uint64_t), cudaMemcpyHostToDevice));

  // a start gate (kill cells with a spare): rank 0 waits, bounded, until the runner creates RS_START_GATE (the spare is
  // ready), so the run cannot end before the kill; the barrier below holds every live rank behind rank 0
  const char* gate = getenv("RS_START_GATE");
  if (!spare && rank == 0 && gate && *gate) {
    const double g0 = monoMs();
    const double gs = getenv("RS_START_GATE_S") ? atof(getenv("RS_START_GATE_S")) : 150.0;
    while (access(gate, F_OK) != 0 && monoMs() - g0 < gs * 1000.0) usleep(2000);
    kv("start_gate_ms=%.1f start_gate_open=%d", monoMs() - g0, access(gate, F_OK) == 0 ? 1 : 0);
  }
  if (!spare) {  // a barrier of the live ranks before the first step
    char b = 1;
    int berr = 0;
    if (rank == 0) {
      for (int r = 1; r < N; r++) berr |= recvall(socks[r], &b, 1);
      for (int r = 1; r < N; r++) berr |= sendall(socks[r], &b, 1);
    } else {
      berr |= sendall(socks[0], &b, 1);
      berr |= recvall(socks[0], &b, 1);
    }
    if (berr) {
      kv("barrier_error=1 exit=1");
      _exit(1);
    }
  }
  std::thread poller(asyncPoll, pollUs);

  Out* dOut = nullptr;
  CK(cudaMalloc(&dOut, sizeof(Out)));
  int txErr = 0, rxErr = 0, devBad = 0, released = 0, releasedStep = -1, reexecMax = 0, stepsDone = startStep;
  int hooksLive = 0;
  long long stableLast = -1;
  for (int s = startStep; s < steps; s++) {
    CK(cudaMemset(dOut, 0, sizeof(Out)));
    stepKernel<<<N, 128>>>(sendWin, recvWin, (uint8_t*)dSend, (const uint8_t*)dRecv, dxHist, dExec, bytes, N, rank, s,
                           regionBytes, devComm, dOut);
    CK(cudaGetLastError());
    if (!spare && dieStep == s) {  // a kill during normal traffic
      std::thread([dieUs, s, rank]() {
        usleep((useconds_t)dieUs);
        printf("GINRS die rank=%d step=%d where=kernel delay_us=%ld mono_ms=%.3f\n", rank, s, dieUs, monoMs());
        fflush(stdout);
        raise(SIGKILL);
      }).detach();
    }
    CK(cudaDeviceSynchronize());
    Out ho;
    CK(cudaMemcpy(&ho, dOut, sizeof(Out), cudaMemcpyDeviceToHost));
    txErr += ho.txErr;
    rxErr += ho.rxErr;
    devBad += ho.devBad;
    if (ho.reexec > reexecMax) reexecMax = ho.reexec;
    if (ho.released) {
      released++;
      releasedStep = s;
      printf("GINRS step rank=%d step=%d released=1 got=%llu want=%llu tx_err=%d mono_ms=%.3f\n", rank, s, ho.got, ho.want,
             ho.txErr, monoMs());
      break;  // a let-go wait: the run ends here for this rank (the slots of this step may be missing)
    }
    stepsDone = s + 1;
    // the checkpoint hook between kernels (after the step's flush: every put of this rank in step s has completed)
    blob.step = (unsigned long long)s + 1;
    CK(cudaMemcpy(&blob.x, dxHist + s + 1, sizeof(uint64_t), cudaMemcpyDeviceToHost));
    unsigned long long stable = NCCL_GIN_RESTORE_STEP_NONE;
    // a kill inside this hook (the checkpoint's input pause): armed, and a checkpoint step
    if (!spare && dieEvery > 0 && s % dieEvery == 0 && (!armFile || access(armFile, F_OK) == 0)) {
      printf("GINRS die rank=%d step=%d where=hook delay_us=%ld mono_ms=%.3f\n", rank, s, dieInUs, monoMs());
      fflush(stdout);
      std::thread([dieInUs]() {
        usleep((useconds_t)dieInUs);
        raise(SIGKILL);
      }).detach();
    }
    const ncclResult_t rstep = rsApi ? rsStep(comm, (unsigned long long)s, &blob, sizeof(blob), &stable) : ncclInvalidUsage;
    if (rstep == ncclSuccess) hooksLive = 1;
    if (stable != NCCL_GIN_RESTORE_STEP_NONE) stableLast = (long long)stable;
    printf("GINRS step rank=%d step=%d released=0 tx_err=%d hook_rc=%d stable=%lld mono_ms=%.3f\n", rank, s, ho.txErr,
           (int)rstep, stable == NCCL_GIN_RESTORE_STEP_NONE ? -1LL : (long long)stable, monoMs());
    if (gapUs) usleep(gapUs);
  }
  g_asyncStop.store(true);
  poller.join();

  // the exact checks against the host reference
  std::vector<std::vector<uint64_t>> xAll;
  hostReference(N, steps, xAll);
  std::vector<uint64_t> hx((size_t)steps + 1, 0);
  CK(cudaMemcpy(hx.data(), dxHist, sizeof(uint64_t) * (size_t)(steps + 1), cudaMemcpyDeviceToHost));
  int xhistBad = 0;
  for (int t = 0; t <= stepsDone; t++)
    if (hx[(size_t)t] != xAll[(size_t)t][(size_t)rank]) xhistBad++;
  std::vector<uint8_t> hr(slotsBytes, 0);
  CK(cudaMemcpy(hr.data(), dRecv, slotsBytes, cudaMemcpyDeviceToHost));
  int recvBad = 0;
  for (int s = 0; s < stepsDone; s++)
    for (int src = 0; src < N; src++) {
      if (src == rank) continue;
      const uint64_t v = sendValue(xAll[(size_t)s][(size_t)src], src, rank, s);
      const uint8_t* slot = hr.data() + (size_t)idxOf(src, rank) * regionBytes + (size_t)s * bytes;
      for (size_t b = 0; b < bytes; b++)
        if (slot[b] != cellByte(v, b)) {
          recvBad++;
          break;
        }
    }
  std::vector<int> hExec((size_t)steps, 0);
  CK(cudaMemcpy(hExec.data(), dExec, sizeof(int) * (size_t)steps, cudaMemcpyDeviceToHost));
  int reexecAny = 0;
  for (int s = 0; s < steps; s++)
    if (hExec[(size_t)s] > 1) reexecAny = 1;
  unsigned long long* dSig = nullptr;
  unsigned long long hSig[2] = {0, 0};
  CK(cudaMalloc(&dSig, sizeof(hSig)));
  readSigKernel<<<1, 32>>>(devComm, rank, dSig);
  CK(cudaGetLastError());
  CK(cudaMemcpy(hSig, dSig, sizeof(hSig), cudaMemcpyDeviceToHost));
  const unsigned long long sig0Want = (unsigned long long)(N - 1) * (unsigned long long)((stepsDone + 1) / 2);
  const unsigned long long sig1Want = (unsigned long long)(N - 1) * (unsigned long long)(stepsDone / 2);
  const int sigExact = (hSig[0] == sig0Want && hSig[1] == sig1Want) ? 1 : 0;
  const int xMatch = (stepsDone == steps && hx[(size_t)steps] == xAll[(size_t)steps][(size_t)rank]) ? 1 : 0;
  const bool hung = stepsDone < steps && released == 0;
  const bool ok = txErr == 0 && rxErr == 0 && devBad == 0 && released == 0 && recvBad == 0 && xhistBad == 0 && xMatch &&
                  sigExact && g_asyncN.load() == 0 && !hung;
  kv("rs_hooks_live=%d steps_done=%d released=%d released_step=%d tx_err=%d rx_err=%d dev_bad=%d recv_bad=%d xhist_bad=%d "
     "x_match=%d reexec_max=%d reexec_any=%d sig0=%llu sig0_want=%llu sig1=%llu sig1_want=%llu sig_exact=%d "
     "async_first=%d async_n=%ld stable_last=%lld xchg=%s",
     hooksLive, stepsDone, released, releasedStep, txErr, rxErr, devBad, recvBad, xhistBad, xMatch, reexecMax, reexecAny,
     hSig[0], sig0Want, hSig[1], sig1Want, sigExact, g_asyncFirst.load(), g_asyncN.load(), stableLast,
     released ? "released" : (hung ? "hung" : (ok ? "ok" : "bad")));
  const int exitCode = ok ? 0 : 4;
  printf("GINRS end rank=%d xchg=%s steps_done=%d mono_ms=%.3f\n", rank, released ? "released" : (ok ? "ok" : "bad"),
         stepsDone, monoMs());

  if (!spare && released == 0) {  // a closing barrier of the live ranks (skipped after a release: a peer may be gone)
    char b = 1;
    if (rank == 0) {
      for (int r = 1; r < N; r++) (void)recvall(socks[r], &b, 1);
      for (int r = 1; r < N; r++) (void)sendall(socks[r], &b, 1);
    } else {
      (void)sendall(socks[0], &b, 1);
      (void)recvall(socks[0], &b, 1);
    }
  }
  if (!spare && endGraceMs > 0) usleep((useconds_t)(endGraceMs * 1000));
  t0 = monoMs();
  const ncclResult_t ar = ncclCommAbort(comm);
  kv("abort_rc=%d abort_ms=%.1f exit=%d", (int)ar, monoMs() - t0, exitCode);
  _exit(exitCode);
}
