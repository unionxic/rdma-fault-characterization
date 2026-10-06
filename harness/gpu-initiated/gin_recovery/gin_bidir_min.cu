// gin_bidir_min.cu - minimal 2-rank NCCL GIN GDAKI program for the bidirectional-traffic question (no recovery
// code; meant for the unpatched gpudb build, but it compiles against any of the trees).
//
// Two directions, each with its own GIN context, its own source and destination windows and its own signal:
//   direction A: rank 0 -> rank 1, context 0, windows txA (source, on rank 0) / rxA (destination, on rank 1), signal 0
//   direction B: rank 1 -> rank 0, context 1, windows txB / rxB, signal 1
// Every rank registers all four windows (symmetric registration is collective). The sender of a direction runs
//   for i: put(peer, rx, i*bytes, tx, i*bytes, bytes, WeakSignalInc{sig}); flush()
// in one kernel; the receiver runs  for i: waitSignal(sig, base+i+1, timeout); check slot i  in another kernel.
//
// usage: gin_bidir_min <rank> <rank0_ip> <port> <iters> <bytes> <mode> <out_kv> [timeout_s]
//   mode: both  = both directions at once (two kernels per rank, two streams)
//         d01   = direction A only (rank 0 sends, rank 1 receives)
//         d10   = direction B only (rank 1 sends, rank 0 receives)
//         seq   = direction A to completion, then a socket barrier, then direction B
//         hostrx = both directions, but no receiver kernel: the host polls the signal (readSig kernel every 1 ms) and
//                  the data are checked at the end
//         txonly = both directions send; nobody waits; the data and signals are checked after a socket barrier
//         fused  = both directions, sender and receiver as two CTAs of ONE kernel; txfirst = both, sender launched first
// env: MIN_SAME_CTX=1 puts both directions on context 0. Diagnostics: MIN_TX_DELAY_MS, MIN_TX_GAP_US, MIN_RX_THREADS,
// MIN_STACK_LIMIT (see main).
// exit: 0 every direction that ran delivered every slot bit-exact and its signal is exact; 4 a device call returned an
//       error or timed out; 5 a data/signal check failed; 2 NCCL error; 6 CUDA error.
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
#include <vector>
#include <unistd.h>
#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <sys/socket.h>

static int g_rank = -1;
static FILE* g_kv = nullptr;
static ncclComm_t g_comm = nullptr;

static double monoMs() {
  struct timespec t;
  clock_gettime(CLOCK_MONOTONIC, &t);
  return t.tv_sec * 1e3 + t.tv_nsec * 1e-6;
}
static void kv(const char* fmt, ...) {
  va_list ap;
  va_start(ap, fmt);
  if (g_kv) {
    vfprintf(g_kv, fmt, ap);
    fputc('\n', g_kv);
    fflush(g_kv);
  }
  va_end(ap);
}
static void die(int code) {
  if (g_comm) {
    alarm(15);
    ncclCommAbort(g_comm);
    alarm(0);
  }
  kv("exit=%d", code);
  _exit(code);
}
#define CK(c) do { cudaError_t e_ = (c); if (e_ != cudaSuccess) { fprintf(stderr, "[rank%d] CUDA %s:%d %s\n", g_rank, __FILE__, __LINE__, cudaGetErrorString(e_)); kv("cuda_error=%s", cudaGetErrorString(e_)); die(6); } } while (0)
#define NK(c) do { ncclResult_t r_ = (c); if (r_ != ncclSuccess && r_ != ncclInProgress) { fprintf(stderr, "[rank%d] NCCL %s:%d %s\n", g_rank, __FILE__, __LINE__, ncclGetErrorString(r_)); kv("nccl_error=%s", ncclGetErrorString(r_)); die(2); } } while (0)

static int sendall(int fd, const void* b, size_t n) {
  const char* p = (const char*)b;
  size_t o = 0;
  while (o < n) {
    ssize_t k = send(fd, p + o, n - o, MSG_NOSIGNAL);
    if (k <= 0) { if (k < 0 && errno == EINTR) continue; return -1; }
    o += (size_t)k;
  }
  return 0;
}
static int recvall(int fd, void* b, size_t n) {
  char* p = (char*)b;
  size_t o = 0;
  while (o < n) {
    ssize_t k = recv(fd, p + o, n - o, 0);
    if (k <= 0) { if (k < 0 && errno == EINTR) continue; return -1; }
    o += (size_t)k;
  }
  return 0;
}
static void barrier(int sock) {
  char b = 1;
  if (g_rank == 0) { if (recvall(sock, &b, 1) || sendall(sock, &b, 1)) die(2); }
  else { if (sendall(sock, &b, 1) || recvall(sock, &b, 1)) die(2); }
}

__host__ __device__ static inline uint32_t patW(int dir, int it, size_t w) {
  uint32_t h = (uint32_t)(w * 2654435761u) ^ (uint32_t)(it * 40503u + 0x9e3779b9u) ^ (uint32_t)((dir + 1) * 0x85ebca6bu);
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

struct Out {
  int rc, rcIt, done, bad, firstBad;
  unsigned long long maxLatNs;
};

// sender body: thread 0 of the CTA posts, the CTA flushes (one thread in sendKernel; 256 in fusedKernel's block 0)
__device__ void sendBody(ncclWindow_t tx, ncclWindow_t rx, size_t bytes, int iters, int peer, int ctx, int sig,
                         struct ncclDevComm devComm, unsigned long long timeoutCycles, unsigned long long gapNs, Out* out) {
  ncclGin gin{devComm, ctx};
  Out o = {0, -1, 0, 0, -1, 0ull};
  for (int i = 0; i < iters; i++) {
    if (gapNs && i) {  // MIN_TX_GAP_US: pace the sender
      const unsigned long long g0 = gtNow();
      while (gtNow() - g0 < gapNs) {}
    }
    const unsigned long long t0 = gtNow();
    if (threadIdx.x == 0)
      gin.put(ncclTeamWorld(devComm), peer, rx, (size_t)i * bytes, tx, (size_t)i * bytes, bytes,
              ncclGin_WeakSignalInc{(ncclGinSignal_t)sig});
    const ncclResult_t rc = gin.flush(ncclCoopCta(), cuda::memory_order_acquire, ncclGin_None{}, timeoutCycles);
    const unsigned long long dt = gtNow() - t0;
    if (dt > o.maxLatNs) o.maxLatNs = dt;
    if (rc != ncclSuccess) {
      o.rc = (int)rc;
      o.rcIt = i;
      o.done = i;
      if (threadIdx.x == 0) *out = o;
      return;
    }
    o.done = i + 1;
  }
  if (threadIdx.x == 0) *out = o;
}
__global__ void sendKernel(ncclWindow_t tx, ncclWindow_t rx, size_t bytes, int iters, int peer, int ctx, int sig,
                           struct ncclDevComm devComm, unsigned long long timeoutCycles, unsigned long long gapNs, Out* out) {
  sendBody(tx, rx, bytes, iters, peer, ctx, sig, devComm, timeoutCycles, gapNs, out);
}

__device__ void recvBody(const uint32_t* rxBuf, size_t bytes, int iters, int dir, int ctx, int sig,
                         unsigned long long base, struct ncclDevComm devComm, unsigned long long timeoutCycles,
                         unsigned long long* tSig, Out* out) {
  ncclGin gin{devComm, ctx};
  __shared__ int bad;
  Out o = {0, -1, 0, 0, -1, 0ull};
  const size_t words = bytes / 4;
  if (threadIdx.x == 0) tSig[iters] = gtNow();  // entry time (tSig has iters + 1 entries)
  for (int i = 0; i < iters; i++) {
    const ncclResult_t rc = gin.waitSignal(ncclCoopCta(), (ncclGinSignal_t)sig, base + (unsigned long long)(i + 1), 64,
                                           cuda::memory_order_acquire, timeoutCycles);
    if (rc != ncclSuccess) {
      o.rc = (int)rc;
      o.rcIt = i;
      o.done = i;
      if (threadIdx.x == 0) *out = o;
      return;
    }
    if (threadIdx.x == 0) { tSig[i] = gtNow(); bad = 0; }
    __syncthreads();
    int b = 0;
    for (size_t w = threadIdx.x; w < words; w += blockDim.x) b |= (((volatile const uint32_t*)rxBuf)[(size_t)i * words + w] != patW(dir, i, w));
    if (b) atomicOr(&bad, 1);
    __syncthreads();
    if (bad) { if (o.bad == 0) o.firstBad = i; o.bad++; }
    o.done = i + 1;
  }
  if (threadIdx.x == 0) *out = o;
}
__global__ void recvKernel(const uint32_t* rxBuf, size_t bytes, int iters, int dir, int ctx, int sig,
                           unsigned long long base, struct ncclDevComm devComm, unsigned long long timeoutCycles,
                           unsigned long long* tSig, Out* out) {
  recvBody(rxBuf, bytes, iters, dir, ctx, sig, base, devComm, timeoutCycles, tSig, out);
}
// one grid of two CTAs: block 0 sends, block 1 receives (co-scheduled by construction; `fused` mode)
__global__ void fusedKernel(ncclWindow_t tx, ncclWindow_t rx, int peer, int ctxSend, int sigSend, const uint32_t* rxBuf,
                            int dirRecv, int ctxRecv, int sigRecv, unsigned long long base, size_t bytes, int iters,
                            struct ncclDevComm devComm, unsigned long long timeoutCycles, unsigned long long gapNs,
                            unsigned long long* tSig, Out* outTx, Out* outRx, int doSend, int doRecv) {
  if (blockIdx.x == 0) {
    if (doSend) sendBody(tx, rx, bytes, iters, peer, ctxSend, sigSend, devComm, timeoutCycles, gapNs, outTx);
  } else {
    if (doRecv) recvBody(rxBuf, bytes, iters, dirRecv, ctxRecv, sigRecv, base, devComm, timeoutCycles, tSig, outRx);
  }
}
__global__ void readSigKernel(struct ncclDevComm devComm, int ctx, int sig, unsigned long long* v) {
  ncclGin gin{devComm, ctx};
  if (threadIdx.x == 0) *v = gin.readSignal((ncclGinSignal_t)sig);
}

int main(int argc, char** argv) {
  if (argc < 8) {
    fprintf(stderr, "usage: %s <rank> <rank0_ip> <port> <iters> <bytes> <both|d01|d10|seq> <out_kv> [timeout_s]\n", argv[0]);
    return 1;
  }
  const int rank = atoi(argv[1]);
  g_rank = rank;
  const char* ip = argv[2];
  const int port = atoi(argv[3]);
  const int iters = atoi(argv[4]);
  const size_t bytes = strtoul(argv[5], nullptr, 10);
  const char* mode = argv[6];
  g_kv = fopen(argv[7], "w");
  const double timeoutS = argc > 8 ? atof(argv[8]) : 10.0;
  const bool sameCtx = getenv("MIN_SAME_CTX") && atoi(getenv("MIN_SAME_CTX"));
  // diagnostics (bmin2): MIN_TX_DELAY_MS = this rank launches its sender that much after the barrier; MIN_TX_GAP_US = pause
  // between this rank's puts; MIN_RX_THREADS = threads of this rank's receiver kernel (256)
  const long txDelayMs = getenv("MIN_TX_DELAY_MS") ? atol(getenv("MIN_TX_DELAY_MS")) : 0;
  const long txGapUs = getenv("MIN_TX_GAP_US") ? atol(getenv("MIN_TX_GAP_US")) : 0;
  const int rxThreads = getenv("MIN_RX_THREADS") ? atoi(getenv("MIN_RX_THREADS")) : 256;
  if ((rank != 0 && rank != 1) || iters <= 0 || bytes < 4 || bytes % 4) return 1;
  const bool runA = strcmp(mode, "d10") != 0, runB = strcmp(mode, "d01") != 0, seq = strcmp(mode, "seq") == 0;
  const bool hostRx = strcmp(mode, "hostrx") == 0, txOnly = strcmp(mode, "txonly") == 0;
  const bool fused = strcmp(mode, "fused") == 0, txFirst = strcmp(mode, "txfirst") == 0;
  kv("rank=%d iters=%d bytes=%zu mode=%s same_ctx=%d t0_mono_ms=%.3f", rank, iters, bytes, mode, sameCtx ? 1 : 0, monoMs());

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
    inet_pton(AF_INET, ip, &a.sin_addr);
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

  CK(cudaSetDevice(0));
  int clockKHz = 0;
  CK(cudaDeviceGetAttribute(&clockKHz, cudaDevAttrClockRate, 0));
  const unsigned long long timeoutCycles = (unsigned long long)(timeoutS * clockKHz * 1000.0);
  ncclConfig_t cfg = NCCL_CONFIG_INITIALIZER;
  cfg.blocking = 1;
  NK(ncclCommInitRankConfig(&g_comm, 2, id, rank, &cfg));
  const size_t winBytes = bytes * (size_t)iters;
  // four windows: txA (0), rxA (1), txB (2), rxB (3); every rank allocates and registers all of them
  void* buf[4];
  ncclWindow_t win[4];
  for (int w = 0; w < 4; w++) {
    NK(ncclMemAlloc(&buf[w], winBytes));
    NK(ncclCommWindowRegister(g_comm, buf[w], winBytes, &win[w], NCCL_WIN_COLL_SYMMETRIC));
  }
  ncclDevComm devComm;
  ncclDevCommRequirements reqs = NCCL_DEV_COMM_REQUIREMENTS_INITIALIZER;
  reqs.ginSignalCount = 2;
  reqs.ginConnectionType = NCCL_GIN_CONNECTION_FULL;
  NK(ncclDevCommCreate(g_comm, &reqs, &devComm));
  kv("devcomm_mono_ms=%.3f", monoMs());
  // this rank sends direction (rank) and receives direction (1 - rank): A = 0 -> 1, B = 1 -> 0
  const int myDir = rank, peerDir = 1 - rank;
  const bool iSend = (myDir == 0) ? runA : runB, iRecv = (peerDir == 0) ? runA : runB;
  const int ctxSend = sameCtx ? 0 : myDir, ctxRecv = sameCtx ? 0 : peerDir;
  std::vector<uint32_t> h(winBytes / 4);
  if (iSend) {
    for (int i = 0; i < iters; i++)
      for (size_t w = 0; w < bytes / 4; w++) h[(size_t)i * (bytes / 4) + w] = patW(myDir, i, w);
    CK(cudaMemcpy(buf[2 * myDir], h.data(), winBytes, cudaMemcpyHostToDevice));
  }
  unsigned long long base = 0, *dv = nullptr;
  CK(cudaMalloc(&dv, 8));
  if (iRecv) {
    CK(cudaMemset(buf[2 * peerDir + 1], 0xA5, winBytes));
    readSigKernel<<<1, 32>>>(devComm, ctxRecv, peerDir, dv);
    CK(cudaDeviceSynchronize());
    CK(cudaMemcpy(&base, dv, 8, cudaMemcpyDeviceToHost));
  }
  Out *dTx = nullptr, *dRx = nullptr;
  unsigned long long* dT = nullptr;
  CK(cudaMalloc(&dTx, sizeof(Out)));
  CK(cudaMalloc(&dRx, sizeof(Out)));
  CK(cudaMalloc(&dT, 8 * (iters + 1)));
  CK(cudaMemset(dTx, 0, sizeof(Out)));
  CK(cudaMemset(dRx, 0, sizeof(Out)));
  CK(cudaMemset(dT, 0, 8 * (iters + 1)));
  cudaStream_t sA, sB;
  CK(cudaStreamCreateWithFlags(&sA, cudaStreamNonBlocking));
  CK(cudaStreamCreateWithFlags(&sB, cudaStreamNonBlocking));
  {  // load every kernel before any of them spins (lazy loading), and record their stack frames (local memory)
    cudaFuncAttributes fs, fr, fg, ff;
    CK(cudaFuncGetAttributes(&fs, sendKernel));
    CK(cudaFuncGetAttributes(&fr, recvKernel));
    CK(cudaFuncGetAttributes(&fg, readSigKernel));
    CK(cudaFuncGetAttributes(&ff, fusedKernel));
    // MIN_STACK_LIMIT: reserve this much local memory per thread up front. A kernel that needs more local memory than
    // the device currently has reserved makes the driver grow the reservation at launch, which waits for the running
    // kernels; with the receiver kernel (248 B) running first, the sender kernel (592 B) then starts only when the
    // receiver exits (bmin2/bmin3).
    size_t lim = 0;
    CK(cudaDeviceGetLimit(&lim, cudaLimitStackSize));
    const long want = getenv("MIN_STACK_LIMIT") ? atol(getenv("MIN_STACK_LIMIT")) : 0;
    if (want > 0) CK(cudaDeviceSetLimit(cudaLimitStackSize, (size_t)want));
    size_t lim2 = 0;
    CK(cudaDeviceGetLimit(&lim2, cudaLimitStackSize));
    kv("stack_send=%zu stack_recv=%zu stack_readsig=%zu stack_fused=%zu stack_limit_before=%zu stack_limit_after=%zu", fs.localSizeBytes,
       fr.localSizeBytes, fg.localSizeBytes, ff.localSizeBytes, lim, lim2);
  }
  CK(cudaDeviceSynchronize());
  kv("signal_base=%llu send=%d recv=%d ctx_send=%d ctx_recv=%d", base, iSend ? 1 : 0, iRecv ? 1 : 0, ctxSend, ctxRecv);
  barrier(sock);
  const double tLaunch = monoMs();
  cudaEvent_t e0, eTx, eRx;  // e0 at the launches; eTx/eRx after each kernel: when it finished (shows whether they overlapped)
  CK(cudaEventCreate(&e0)); CK(cudaEventCreate(&eTx)); CK(cudaEventCreate(&eRx));
  CK(cudaEventRecord(e0, sA));
  bool txLaunched = false, rxLaunched = false;
  double txLaunchCallMs = -1;  // host time spent inside the sender's launch statement (a blocked launch shows here)
  auto launchSend = [&]() {
    if (txDelayMs > 0) usleep(txDelayMs * 1000);
    const double l0 = monoMs();
    sendKernel<<<1, 1, 0, sA>>>(win[2 * myDir], win[2 * myDir + 1], bytes, iters, 1 - rank, ctxSend, myDir, devComm,
                                 timeoutCycles, (unsigned long long)txGapUs * 1000ull, dTx);
    txLaunchCallMs = monoMs() - l0;
    CK(cudaGetLastError());
    CK(cudaEventRecord(eTx, sA));
    txLaunched = true;
  };
  auto launchRecv = [&]() {
    recvKernel<<<1, rxThreads, 0, sB>>>((const uint32_t*)buf[2 * peerDir + 1], bytes, iters, peerDir, ctxRecv, peerDir, base,
                                        devComm, timeoutCycles, dT, dRx);
    CK(cudaGetLastError());
    CK(cudaEventRecord(eRx, sB));
    rxLaunched = true;
  };
  if (seq) {  // A first, then B; every rank takes part in both
    if (rank == 1) launchRecv(); else launchSend();
    CK(cudaDeviceSynchronize());
    barrier(sock);
    if (rank == 0) launchRecv(); else launchSend();
    CK(cudaDeviceSynchronize());
  } else if (hostRx || txOnly) {
    if (iSend) launchSend();
    if (hostRx) {  // the host waits for the final signal value, polling with a tiny kernel
      const double dl = monoMs() + timeoutS * 1000.0 * 3;
      unsigned long long v = 0;
      while (monoMs() < dl) {
        readSigKernel<<<1, 32, 0, sB>>>(devComm, ctxRecv, peerDir, dv);
        CK(cudaStreamSynchronize(sB));
        CK(cudaMemcpy(&v, dv, 8, cudaMemcpyDeviceToHost));
        if (v >= base + (unsigned long long)iters) break;
        usleep(1000);
      }
      Out o = {v >= base + (unsigned long long)iters ? 0 : (int)ncclTimeout, -1, (int)(v - base), 0, -1, 0ull};
      CK(cudaMemcpy(dRx, &o, sizeof(o), cudaMemcpyHostToDevice));
    }
    CK(cudaDeviceSynchronize());
    if (txOnly) {
      barrier(sock);  // both senders are done: check what arrived
      readSigKernel<<<1, 32, 0, sB>>>(devComm, ctxRecv, peerDir, dv);
      CK(cudaDeviceSynchronize());
      unsigned long long v = 0;
      CK(cudaMemcpy(&v, dv, 8, cudaMemcpyDeviceToHost));
      Out o = {v >= base + (unsigned long long)iters ? 0 : (int)ncclTimeout, -1, (int)(v - base), 0, -1, 0ull};
      CK(cudaMemcpy(dRx, &o, sizeof(o), cudaMemcpyHostToDevice));
    }
  } else if (fused) {  // both roles in one grid (block 0 sends, block 1 receives)
    fusedKernel<<<2, 256, 0, sA>>>(win[2 * myDir], win[2 * myDir + 1], 1 - rank, ctxSend, myDir, (const uint32_t*)buf[2 * peerDir + 1],
                                   peerDir, ctxRecv, peerDir, base, bytes, iters, devComm, timeoutCycles,
                                   (unsigned long long)txGapUs * 1000ull, dT, dTx, dRx, iSend ? 1 : 0, iRecv ? 1 : 0);
    CK(cudaGetLastError());
    CK(cudaEventRecord(eTx, sA));
    txLaunched = iSend; rxLaunched = false;
    CK(cudaDeviceSynchronize());
  } else if (txFirst) {  // as `both`, the sender launched before the receiver
    if (iSend) launchSend();
    if (iRecv) launchRecv();
    CK(cudaDeviceSynchronize());
  } else {
    if (iRecv) launchRecv();
    if (iSend) launchSend();
    CK(cudaDeviceSynchronize());
  }
  const double tEnd = monoMs();
  int code = 0;
  Out tx, rx;
  CK(cudaMemcpy(&tx, dTx, sizeof(tx), cudaMemcpyDeviceToHost));
  CK(cudaMemcpy(&rx, dRx, sizeof(rx), cudaMemcpyDeviceToHost));
  kv("kernels_ms=%.1f", tEnd - tLaunch);
  {
    float tx = -1, rx = -1;
    if (txLaunched) CK(cudaEventElapsedTime(&tx, e0, eTx));
    if (rxLaunched) CK(cudaEventElapsedTime(&rx, e0, eRx));
    const char* mc = getenv("CUDA_DEVICE_MAX_CONNECTIONS");
    const char* ml = getenv("CUDA_MODULE_LOADING");
    kv("tx_kernel_end_ms=%.1f rx_kernel_end_ms=%.1f tx_launch_call_ms=%.1f tx_delay_ms=%ld tx_gap_us=%ld rx_threads=%d "
       "max_connections=%s module_loading=%s", tx, rx, txLaunchCallMs, txDelayMs, txGapUs, rxThreads, mc ? mc : "-", ml ? ml : "-");
  }
  if (iSend) {
    kv("tx_dir=%d tx_done=%d tx_rc=%s tx_rc_it=%d tx_max_lat_us=%.1f", myDir, tx.done, ncclGetErrorString((ncclResult_t)tx.rc),
       tx.rcIt, tx.maxLatNs / 1e3);
    if (tx.rc != 0 || tx.done != iters) code = 4;
  }
  if (iRecv) {
    // host re-check of every slot of the received direction, and the final signal
    CK(cudaMemcpy(h.data(), buf[2 * peerDir + 1], winBytes, cudaMemcpyDeviceToHost));
    int badSlots = 0, missing = 0, firstBad = -1;
    for (int i = 0; i < iters; i++) {
      size_t bad = 0, pois = 0;
      for (size_t w = 0; w < bytes / 4; w++) {
        const uint32_t x = h[(size_t)i * (bytes / 4) + w];
        if (x != patW(peerDir, i, w)) bad++;
        if (x == 0xA5A5A5A5u) pois++;
      }
      if (bad) { if (firstBad < 0) firstBad = i; badSlots++; if (pois == bytes / 4) missing++; }
    }
    readSigKernel<<<1, 32>>>(devComm, ctxRecv, peerDir, dv);
    CK(cudaDeviceSynchronize());
    unsigned long long fin = 0;
    CK(cudaMemcpy(&fin, dv, 8, cudaMemcpyDeviceToHost));
    std::vector<unsigned long long> ts(iters + 1);
    CK(cudaMemcpy(ts.data(), dT, 8 * (iters + 1), cudaMemcpyDeviceToHost));
    // when the receiver kernel saw its first and last signal, ms after its own entry (0 if it saw none)
    const double sigFirst = (rx.done > 0 && ts[0] > ts[iters]) ? (ts[0] - ts[iters]) / 1e6 : 0.0;
    const double sigLast = (rx.done > 0 && ts[rx.done - 1] > ts[iters]) ? (ts[rx.done - 1] - ts[iters]) / 1e6 : 0.0;
    kv("rx_sig_first_ms=%.1f rx_sig_last_ms=%.1f", sigFirst, sigLast);
    kv("rx_dir=%d rx_done=%d rx_rc=%s rx_rc_it=%d dev_bad_slots=%d host_bad_slots=%d host_missing_slots=%d host_first_bad=%d "
       "final_signal=%llu expected_final=%llu signal_exact=%d", peerDir, rx.done, ncclGetErrorString((ncclResult_t)rx.rc), rx.rcIt,
       rx.bad, badSlots, missing, firstBad, fin, base + (unsigned long long)iters, fin == base + (unsigned long long)iters);
    if (rx.rc != 0 || rx.done != iters) code = code ? code : 4;
    else if (badSlots || rx.bad || fin != base + (unsigned long long)iters) code = code ? code : 5;
  }
  usleep(300000);
  ncclResult_t fa = ncclSuccess;
  ncclCommGetAsyncError(g_comm, &fa);
  kv("final_async=%s", ncclGetErrorString(fa));
  fprintf(stderr, "[rank%d] DONE exit=%d\n", rank, code);
  die(code);
  return code;
}
