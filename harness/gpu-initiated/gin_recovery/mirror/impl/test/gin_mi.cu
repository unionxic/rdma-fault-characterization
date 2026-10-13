// gin_mi.cu - gin-mirror, test branch (../../EXPERIMENT.md 7, 9.8; impl/PARALLEL.md row exp/gin-mirror-test): gin-restore's
// test workload (../../../restore/impl/test/gin_rs.cu, md5 bfcefa19, copied and then extended) with two more workloads.
// Without RS_OVERWRITE and RS_TRAIN it runs gin_rs's workload step for step (the regression cells run it so).
//   RS_OVERWRITE=1  the 4 KiB overwrite workload: ONE send slot per destination (rewritten every step), and right after the
//                   step's flush returned (the put's local completion) every sending CTA overwrites its slot with a poison
//                   value that depends on (rank, destination, step); the next step writes the real value again. The receive
//                   side keeps gin-restore's slot per (peer, step). A restore that re-reads the source (no mirror) replays
//                   poison or another step's value; the checks below see it (recv_bad, recv_poison, xhist_bad).
//   RS_TRAIN=1      the training shape of 9.8: every rank puts BYTES (default 2 MiB) to each of its three peers per step,
//                   STEPS (default 2 000) steps, the send slot overwritten with poison right after the flush as above, the
//                   receive side a ring of R = RS_RING (default 4, at least 3) slots per peer: step s lands in ring slot
//                   s mod R. Two signals by step parity (as gin_rs). The state history x(0..S) lives in a device buffer of
//                   its own registered with ncclGinRestoreRegister (after the step counters), so the windows stay 6 MiB
//                   (send: one slot per peer) and 24 MiB (receive ring) as 9.8's BAR1 budget assumes. Requirement 14
//                   holds by construction: step s's kernel waits for step s's signal target and reads only ring slot
//                   s mod R, which no put of another step writes while a sender is at most one step ahead (R >= 3).
//                   The data are 64-bit words (cellWord) instead of bytes (cellByte), so a 2 MiB slot costs a few hundred
//                   microseconds to fill and to check on one CTA.
// The step table the step-aligned import needs (rs_log_api.h v2, gdakiRsStepOfPos) comes from ncclGinRestoreStep(t), which
// this driver calls once per step after the step's kernel and its flush (gin-restore requirement 7): no other hook is needed.
// Poison: the first 64-bit word is poisonWord(rank, destination, step) (top 16 bits 0xDEAD), every other byte 0xA5. A
// received slot is counted as poison (recv_poison on the host at the end, dev_poison on the device when it is read) when
// its first word carries the tag and its next 8 bytes are all 0xA5 (a real cell has that with probability 2^-64).
// gin_mi adds: env RS_OVERWRITE, RS_TRAIN, RS_RING (above); kv workload (gin_rs|overwrite|train), overwrite, train, ring,
//   mirror_env, mirror_lane_env, mirror_slots_env, checksum_env (what this process got: the refusal cells change one rank),
//   recv_poison, dev_poison, recv_checked (received slots compared at the end: every step's, or the ring's last R steps).
//
// gin_rs.cu's head comment follows (unchanged but for this program's name; "this layer" is gin-restore's).
// gin_rs.cu - gin-restore work package 10: the test workload of EXPERIMENT.md 9.8 (DRAFT; built, not run). A 4-rank NCCL
// GIN (GDAKI) application, two ranks per GPU (NCCL_MULTI_RANK_GPU_ENABLE=1): rain holds ranks 0 and 2, sunny 1 and 3. It
// calls the three public restore hooks: ncclGinRestoreResume after ncclDevCommCreate, ncclGinRestoreStep between step
// kernels, ncclGinRestoreRegister for extra device state. As a spare process (NCCL_GIN_RESTORE_SPARE=<its logical rank>) it
// re-executes from the step Resume reports.
//
// One source, three builds (build_rs_test.sh). Each cell names the build it runs (cells_rs.json "driver"):
//   gin_rs          this layer's headers, -DNCCL_GIN_RESTORE_DEVICE (EXPERIMENT.md 12, the build-time opt-in, choice (b)):
//                   the device send path carries the hold branch. Every restore cell runs it.
//   gin_rs_nomacro  this layer's headers, no macro: the program a fail-fast user builds. Under the 2026-10-12 design change
//                   (user) the public Resume is an inline wrapper that passes the build flag, and Resume refuses on every
//                   rank ("program not built with NCCL_GIN_RESTORE_DEVICE") when the program lacks the macro; the side
//                   table is published to the device only after a successful Resume, so this build never traps and runs
//                   as hk does. The refusal cell rs4_refuse_nomacro runs it (RS_CONTINUE_AFTER_REFUSAL=1: after the
//                   refusal it runs the workload fail-fast to the end, showing no trap and an exact result).
//   gin_rs_hk       gpu-detect's hk headers, no macro, no restore API in the header: the no-restore control
//                   (rs4_kill3@hk); the three hooks are compiled out (kv rs_api=0).
// (gin-mirror: build_mi_test.sh builds gin_mi (macro) and gin_mi_nomacro against the mirror layer's headers.)
// The hooks are called through the header (not looked up by name), so the header's inline Resume wrapper passes this
// program's build flag; with the current header Resume is an exported function and the same call compiles.
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
// source slot is never rewritten (req 12: the descriptor-only log re-reads it). (gin-mirror: RS_OVERWRITE and RS_TRAIN
// break req 12 on purpose, and RS_TRAIN replaces req 3 on the receive side by the mirror's weaker form, 9.4.)
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
// usage: gin_mi <rank> <nranks> <rank0_ip> <port> <out_kv>     (a spare ignores rank0_ip and port: no rendezvous)
// env: RS_RDV_NONCE (16 hex; a rank r > 0 sends nothing before it checked rank 0's greeting "GINRS_01" + nonce),
//   RS_STEPS (40; RS_TRAIN: 2000), RS_BYTES (4096; RS_TRAIN: 2097152; multiple of 8), RS_DEV (0), RS_WATCHDOG_S (90),
//   RS_ASYNC_POLL_US (200),
//   RS_START_GATE=<path> and RS_START_GATE_S (150): rank 0 waits for the file before the first step (a spare gets ready),
//   RS_STEP_GAP_US (0: a host pause after each step's hook; pacing only), RS_END_GRACE_MS (0: a live rank's pause before
//   its final ncclCommAbort, so a revived rank finishes its last step and checks first),
//   RS_CONTINUE_AFTER_REFUSAL=1 (after a refused Resume run the workload fail-fast instead of ending: the no-macro cell),
//   GIN_RS_DIE_AT=<step>:<us> (self-SIGKILL us after launching that step's kernel: a kill during normal traffic; the
//     second-death cells and the training kill cells use it, the runner draws step and us from the cell's seed),
//   GIN_RS_DIE_IN_STEP=<every>:<us> and GIN_RS_ARM_FILE=<path> (once the file exists, SIGKILL itself us after entering the
//     checkpoint hook of the next step s with s % every == 0: a kill inside the checkpoint's input pause; not used by the
//     runners any more, gin-restore 2026-10-13)
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

// the restore API is in the header when it defines NCCL_GIN_RESTORE_STEP_NONE (this layer); the hk headers have none
#ifdef NCCL_GIN_RESTORE_STEP_NONE
#define RS_API 1
#else
#define RS_API 0
#define NCCL_GIN_RESTORE_STEP_NONE (~0ULL)
#endif
static ncclResult_t rsResume(ncclComm_t comm, const struct ncclDevComm* dc, unsigned long long* step, void* blob,
                             size_t* bytes) {
#if RS_API
  return ncclGinRestoreResume(comm, dc, step, blob, bytes);  // the header's call: an inline wrapper passes the build flag
#else
  (void)comm; (void)dc; (void)step; (void)blob; (void)bytes;
  return ncclSuccess;
#endif
}
static ncclResult_t rsStep(ncclComm_t comm, unsigned long long step, const void* blob, size_t bytes,
                           unsigned long long* stable) {
#if RS_API
  return ncclGinRestoreStep(comm, step, blob, bytes, stable);
#else
  (void)comm; (void)step; (void)blob; (void)bytes; (void)stable;
  return ncclInvalidUsage;
#endif
}
static ncclResult_t rsRegister(ncclComm_t comm, void* buff, size_t size) {
#if RS_API
  return ncclGinRestoreRegister(comm, buff, size);
#else
  (void)comm; (void)buff; (void)size;
  return ncclSuccess;
#endif
}

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
// ---- gin-mirror: the training shape's words and the poison of the overwrite (see the head comment) ----
// word w of the cell carrying v (RS_TRAIN): word 0 is v, the rest a mix of v and w
__host__ __device__ static inline uint64_t cellWord(uint64_t v, size_t w) {
  return w == 0 ? v : mix64(v ^ ((uint64_t)w * 0xD1B54A32D192ED03ull));
}
#define MI_POISON_TAG 0xDEADull
#define MI_POISON_FILL 0xA5u
#define MI_POISON_FILL64 0xA5A5A5A5A5A5A5A5ull
// the word a sending CTA writes into its send slot right after the step's flush (top 16 bits: the tag)
__host__ __device__ static inline uint64_t poisonWord(int r, int d, int s) {
  return (MI_POISON_TAG << 48) | ((uint64_t)(r & 0xff) << 40) | ((uint64_t)(d & 0xff) << 32) | (uint64_t)(uint32_t)s;
}
// a slot whose first word is w0 and whose next 8 bytes (if any) are w1: poison (w1 ignored for a slot of 8 bytes)
__host__ __device__ static inline bool isPoison(uint64_t w0, uint64_t w1, size_t bytes) {
  return (w0 >> 48) == MI_POISON_TAG && (bytes < 16 || w1 == MI_POISON_FILL64);
}

struct Out {
  int txErr, rxErr, devBad, released, reexec, devPoison;
  unsigned long long got, want;
};
// CTA k < N-1: the sender to the k-th other rank (context = that rank); CTA N-1: the receiver (context = this rank).
// overwrite (gin-mirror, RS_OVERWRITE): one send slot per destination, poisoned right after the flush returned.
__global__ void stepKernel(ncclWindow_t sendWin, ncclWindow_t recvWin, uint8_t* sendBuf, const uint8_t* recvBuf,
                           uint64_t* xHist, int* execCnt, size_t bytes, int n, int me, int s, size_t regionBytes,
                           int overwrite, struct ncclDevComm devComm, Out* out) {
  const int k = blockIdx.x;
  __shared__ int sRc, sBad, sRel, sPois;
  __shared__ uint64_t sRecv[8];
  if (k < n - 1) {
    const int d = k < me ? k : k + 1;
    const uint64_t x = ((volatile uint64_t*)xHist)[s];  // x_me(s): written before this launch (host or step s-1)
    const uint64_t v = sendValue(x, me, d, s);
    // send slot (d, s) of this rank; with overwrite the one slot of d
    const size_t lo = overwrite ? (size_t)idxOf(d, me) * bytes : (size_t)idxOf(d, me) * regionBytes + (size_t)s * bytes;
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
    if (overwrite) {  // the put's local completion was seen (the flush returned): the application reuses the slot at once
      const uint64_t pw = poisonWord(me, d, s);
      for (size_t b = threadIdx.x; b < bytes; b += blockDim.x)
        sendBuf[lo + b] = b < 8 ? (uint8_t)((pw >> (8 * b)) & 0xff) : (uint8_t)MI_POISON_FILL;
      __threadfence_system();
    }
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
      sPois = 0;
    }
    __syncthreads();
    if (sRel) return;  // a released survivor: do not read slots that may not have arrived
    for (int src = 0; src < n; src++) {
      if (src == me) continue;
      const uint8_t* slot = recvBuf + (size_t)idxOf(src, me) * regionBytes + (size_t)s * bytes;
      if (threadIdx.x == 0) {
        uint64_t v = 0, w1 = 0;
        for (int b = 0; b < 8; b++) v |= (uint64_t)((volatile const uint8_t*)slot)[b] << (8 * b);
        for (int b = 8; b < 16 && (size_t)b < bytes; b++) w1 |= (uint64_t)((volatile const uint8_t*)slot)[b] << (8 * (b - 8));
        sRecv[src] = v;
        if (isPoison(v, w1, bytes)) sPois++;
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
      out->devPoison = sPois;
      xHist[s + 1] = nextState(((volatile uint64_t*)xHist)[s], me, n, sRecv);
      __threadfence_system();
      const int c = ++execCnt[s];
      out->reexec = c;
    }
  }
}
// gin-mirror, RS_TRAIN: the training shape (the head comment). words = BYTES / 8; ring = R. The send slot of d is word
// offset idxOf(d, me) x words; the receive slot of (src, s) is word offset (idxOf(src, me) x R + s mod R) x words.
__global__ void trainKernel(ncclWindow_t sendWin, ncclWindow_t recvWin, uint64_t* sendBuf, const uint64_t* recvBuf,
                            uint64_t* xHist, int* execCnt, size_t words, int ring, int n, int me, int s,
                            struct ncclDevComm devComm, Out* out) {
  const int k = blockIdx.x;
  const size_t bytes = words * 8;
  __shared__ int sRc, sBad, sRel, sPois;
  __shared__ uint64_t sRecv[8];
  if (k < n - 1) {
    const int d = k < me ? k : k + 1;
    const uint64_t x = ((volatile uint64_t*)xHist)[s];
    const uint64_t v = sendValue(x, me, d, s);
    uint64_t* slot = sendBuf + (size_t)idxOf(d, me) * words;
    for (size_t w = threadIdx.x; w < words; w += blockDim.x) slot[w] = cellWord(v, w);
    __threadfence_system();
    if (threadIdx.x == 0) sRc = 0;
    __syncthreads();
    ncclGin gin{devComm, d};
    const size_t lo = (size_t)idxOf(d, me) * bytes;
    const size_t ro = ((size_t)idxOf(me, d) * (size_t)ring + (size_t)(s % ring)) * bytes;  // ring slot (me, s) of d
    if (threadIdx.x == 0)
      gin.put(ncclTeamWorld(devComm), d, recvWin, ro, sendWin, lo, bytes, ncclGin_WeakSignalInc{(unsigned)(s & 1)});
    ncclResult_t rc = gin.flush(ncclCoopCta());
    if (rc != ncclSuccess) atomicCAS(&sRc, 0, (int)rc);
    __syncthreads();
    // the put's local completion was seen: the slot is reused at once (poison until the next step writes it)
    const uint64_t pw = poisonWord(me, d, s);
    for (size_t w = threadIdx.x; w < words; w += blockDim.x) slot[w] = w == 0 ? pw : MI_POISON_FILL64;
    __threadfence_system();
    if (threadIdx.x == 0 && sRc != 0) atomicAdd(&out->txErr, 1);
  } else {
    ncclGin gin{devComm, me};
    const unsigned sig = (unsigned)(s & 1);
    const unsigned long long want = stepTarget(n, s);
    gin.waitSignal(ncclCoopCta(), sig, want, 64, cuda::memory_order_acquire);
    if (threadIdx.x == 0) {
      const unsigned long long got = (unsigned long long)gin.readSignal(sig);
      out->got = got;
      out->want = want;
      sRel = got < want ? 1 : 0;
      out->released = sRel;
      sBad = 0;
      sPois = 0;
    }
    __syncthreads();
    if (sRel) return;
    for (int src = 0; src < n; src++) {
      if (src == me) continue;
      const volatile uint64_t* slot =
        (const volatile uint64_t*)recvBuf + ((size_t)idxOf(src, me) * (size_t)ring + (size_t)(s % ring)) * words;
      if (threadIdx.x == 0) {
        const uint64_t v = slot[0];
        sRecv[src] = v;
        if (isPoison(v, words > 1 ? slot[1] : 0, bytes)) sPois++;
      }
      __syncthreads();
      const uint64_t v = sRecv[src];
      int bad = 0;
      for (size_t w = threadIdx.x; w < words; w += blockDim.x)
        if (slot[w] != cellWord(v, w)) bad = 1;
      if (bad) atomicOr(&sBad, 1);
      __syncthreads();
    }
    if (threadIdx.x == 0) {
      if (sBad) out->devBad = 1;
      out->devPoison = sPois;
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
static std::string envTok(const char* name) { return token(getenv(name) ? getenv(name) : "unset"); }

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
  // gin-mirror: the workload (head comment); RS_TRAIN implies the overwrite
  const bool train = getenv("RS_TRAIN") && atoi(getenv("RS_TRAIN")) == 1;
  const bool overwrite = train || (getenv("RS_OVERWRITE") && atoi(getenv("RS_OVERWRITE")) == 1);
  const int ring = train ? (getenv("RS_RING") ? atoi(getenv("RS_RING")) : 4) : 0;
  const int steps = getenv("RS_STEPS") ? atoi(getenv("RS_STEPS")) : (train ? 2000 : 40);
  size_t bytes = getenv("RS_BYTES") ? (size_t)atol(getenv("RS_BYTES")) : (train ? (size_t)2097152 : (size_t)4096);
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
  const int rsApi = RS_API;
  // the no-macro refusal cell: after a refused Resume, run the workload fail-fast to the end (no trap, exact result)
  const bool continueAfterRefusal = getenv("RS_CONTINUE_AFTER_REFUSAL") && atoi(getenv("RS_CONTINUE_AFTER_REFUSAL")) == 1;
  const int buddy = rank ^ 1;
  kv("mode=%s rank=%d nranks=%d buddy=%d steps=%d bytes=%zu rs_device_macro=%d rs_api=%d die_at=%d:%ld die_in_step=%d:%ld "
     "arm_file=%d",
     spare ? "spare" : "live", rank, N, buddy, steps, bytes, macro, rsApi, dieStep, dieUs, dieEvery, dieInUs,
     armFile ? 1 : 0);
  kv("workload=%s overwrite=%d train=%d ring=%d mirror_env=%s mirror_lane_env=%s mirror_slots_env=%s checksum_env=%s",
     train ? "train" : (overwrite ? "overwrite" : "gin_rs"), overwrite ? 1 : 0, train ? 1 : 0, ring,
     envTok("NCCL_GIN_RESTORE_MIRROR").c_str(), envTok("NCCL_GIN_RESTORE_MIRROR_LANE").c_str(),
     envTok("NCCL_GIN_RESTORE_MIRROR_SLOTS").c_str(), envTok("NCCL_GIN_RESTORE_CHECKSUM").c_str());
  if (train && (ring < 3 || bytes < 16 || steps < 1)) {  // 9.4: the step-aligned import needs R >= 3
    kv("usage_error=train_ring_or_bytes exit=1");
    return 1;
  }
  printf("GINRS start rank=%d mode=%s mono_ms=%.3f\n", rank, spare ? "spare" : "live", monoMs());

  std::thread([wdS]() {
    std::this_thread::sleep_for(std::chrono::seconds(wdS));
    static const char m[] = "WATCHDOG: gin_mi exceeded its bound; exiting 7\n";
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

  // gin_rs: send window: N-1 regions of `steps` slots, then the state history x(0..steps) (256-byte aligned); recv window:
  // N-1 regions of `steps` slots. Both are windows, so the restore checkpoints them (9.4 (a)).
  // RS_OVERWRITE: the send window's N-1 regions are one slot each (the history follows them); the recv window as gin_rs.
  // RS_TRAIN: send window N-1 slots, recv window N-1 rings of R slots; the history in a registered buffer of its own.
  const size_t regionBytes = bytes * (size_t)steps;
  const size_t slotsBytes = train ? bytes * (size_t)ring * (size_t)(N - 1) : regionBytes * (size_t)(N - 1);
  const size_t sendSlots = overwrite ? bytes * (size_t)(N - 1) : slotsBytes;
  const size_t xOff = (sendSlots + 255) & ~(size_t)255;
  const size_t sendNeed = train ? sendSlots : xOff + sizeof(uint64_t) * (size_t)(steps + 1);
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
  // the step-execution counters: extra device state, registered with the restore (9.4 (b)); RS_TRAIN: the history too
  int* dExec = nullptr;
  CK(cudaMalloc(&dExec, sizeof(int) * (size_t)steps));
  CK(cudaMemset(dExec, 0, sizeof(int) * (size_t)steps));
  uint64_t* dxHist = nullptr;
  if (train) {
    CK(cudaMalloc(&dxHist, sizeof(uint64_t) * (size_t)(steps + 1)));
    CK(cudaMemset(dxHist, 0, sizeof(uint64_t) * (size_t)(steps + 1)));
  } else {
    dxHist = (uint64_t*)((char*)dSend + xOff);
  }
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

  ncclResult_t rreg = rsApi ? rsRegister(comm, dExec, sizeof(int) * (size_t)steps) : ncclSuccess;
  // RS_TRAIN: the history second (every rank in the same order, as the header asks)
  if (train && rsApi && rreg == ncclSuccess) rreg = rsRegister(comm, dxHist, sizeof(uint64_t) * (size_t)(steps + 1));
  kv("register_rc=%d registered=%d", (int)rreg, rsApi ? (train ? 2 : 1) : 0);

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
  // silently after a refused Resume; except the no-macro cell, which runs on fail-fast on purpose (the refusal is reported
  // in kv, and the run shows the program does not trap)
  if (r3 != ncclSuccess && continueAfterRefusal) kv("refused_then_ran=1");
  if (r3 != ncclSuccess && !continueAfterRefusal) {
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
  int hooksLive = 0, devPoison = 0;
  long long stableLast = -1;
  for (int s = startStep; s < steps; s++) {
    CK(cudaMemset(dOut, 0, sizeof(Out)));
    if (train)
      trainKernel<<<N, 256>>>(sendWin, recvWin, (uint64_t*)dSend, (const uint64_t*)dRecv, dxHist, dExec, bytes / 8, ring, N,
                              rank, s, devComm, dOut);
    else
      stepKernel<<<N, 128>>>(sendWin, recvWin, (uint8_t*)dSend, (const uint8_t*)dRecv, dxHist, dExec, bytes, N, rank, s,
                             regionBytes, overwrite ? 1 : 0, devComm, dOut);
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
    devPoison += ho.devPoison;
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
  int recvBad = 0, recvPoison = 0, recvChecked = 0;
  // RS_TRAIN keeps only the ring's last R steps; the other workloads every step's slot
  const int firstChecked = train ? (stepsDone > ring ? stepsDone - ring : 0) : 0;
  for (int s = firstChecked; s < stepsDone; s++)
    for (int src = 0; src < N; src++) {
      if (src == rank) continue;
      const uint64_t v = sendValue(xAll[(size_t)s][(size_t)src], src, rank, s);
      const size_t off = train ? ((size_t)idxOf(src, rank) * (size_t)ring + (size_t)(s % ring)) * bytes
                               : (size_t)idxOf(src, rank) * regionBytes + (size_t)s * bytes;
      const uint8_t* slot = hr.data() + off;
      uint64_t w0 = 0, w1 = 0;
      memcpy(&w0, slot, 8);
      if (bytes >= 16) memcpy(&w1, slot + 8, 8);
      if (isPoison(w0, w1, bytes)) recvPoison++;
      recvChecked++;
      if (train) {
        const uint64_t* sw = (const uint64_t*)slot;
        for (size_t w = 0; w < bytes / 8; w++)
          if (sw[w] != cellWord(v, w)) {
            recvBad++;
            break;
          }
      } else {
        for (size_t b = 0; b < bytes; b++)
          if (slot[b] != cellByte(v, b)) {
            recvBad++;
            break;
          }
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
                  sigExact && recvPoison == 0 && devPoison == 0 && g_asyncN.load() == 0 && !hung;
  kv("rs_hooks_live=%d steps_done=%d released=%d released_step=%d tx_err=%d rx_err=%d dev_bad=%d recv_bad=%d xhist_bad=%d "
     "x_match=%d reexec_max=%d reexec_any=%d sig0=%llu sig0_want=%llu sig1=%llu sig1_want=%llu sig_exact=%d "
     "async_first=%d async_n=%ld stable_last=%lld recv_poison=%d dev_poison=%d recv_checked=%d xchg=%s",
     hooksLive, stepsDone, released, releasedStep, txErr, rxErr, devBad, recvBad, xhistBad, xMatch, reexecMax, reexecAny,
     hSig[0], sig0Want, hSig[1], sig1Want, sigExact, g_asyncFirst.load(), g_asyncN.load(), stableLast, recvPoison,
     devPoison, recvChecked, released ? "released" : (hung ? "hung" : (ok ? "ok" : "bad")));
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
