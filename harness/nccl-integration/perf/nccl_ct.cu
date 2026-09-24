// nccl_ct.cu - 2-rank NCCL all-reduce job for completion-time measurements (no MPI).
//
// Same data scheme as ../nccl_ar2.cu (distinct small-integer inputs per rank, iteration and
// index, so float sums are exact), but generated and checked on the GPU so that large
// messages and many iterations stay cheap, and with timing:
//   * every iteration: fill inputs, poison rbuf (NaN), [timed: ncclAllReduce -> stream done],
//     check the whole rbuf bit-exactly (unless --check none);
//   * "IT <it> <ms>" per iteration, and one "SUMMARY key=value ..." line at the end;
//   * --start S resumes a job at iteration S (the restart-from-checkpoint baseline);
//   * the stream wait spins (no sleep), polling ncclCommGetAsyncError every 256 spins.
// Exit codes: 0 ok, 1 usage/setup, 2 NCCL call error, 3 async NCCL error, 4 timeout,
// 5 mismatch, 6 CUDA error, 7 ncclCommAbort hung after an error (watchdog).
//
// usage: nccl_ct --rank R --ip IP --port P [--iters N] [--start S] [--count C] [--warmup W]
//                [--check every|last|none] [--timeout SEC] [--quiet] [--op allreduce|bcast]
// --op bcast: ncclBroadcast from rank 0 (a one-way stream with no data dependency back from rank 1;
// rank 1's result must equal rank 0's input).
#include <nccl.h>
#include <cuda_runtime.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cstdint>
#include <ctime>
#include <vector>
#include <algorithm>
#include <unistd.h>
#include <csignal>
#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <sys/socket.h>

static const int NRANKS = 2;
static int g_rank = -1;

static void abortWatchdog(int) {
  static const char m[] = "ABORT-HANG: ncclCommAbort did not return within the watchdog; exiting 7\n";
  ssize_t w = write(2, m, sizeof(m) - 1); (void)w;
  _exit(7);
}

#define CK(c) do { cudaError_t e_ = (c); if (e_ != cudaSuccess) { \
  fprintf(stderr, "[rank%d] CUDA %s:%d %s\n", g_rank, __FILE__, __LINE__, cudaGetErrorString(e_)); exit(6); } } while (0)
#define NK(c) do { ncclResult_t r_ = (c); if (r_ != ncclSuccess) { \
  fprintf(stderr, "[rank%d] NCCL %s:%d %s\n", g_rank, __FILE__, __LINE__, ncclGetErrorString(r_)); exit(2); } } while (0)

static int sendall(int fd, const void* b, size_t n) { const char* p = (const char*)b; size_t o = 0; while (o < n) { ssize_t k = send(fd, p+o, n-o, 0); if (k <= 0) return -1; o += k; } return 0; }
static int recvall(int fd, void* b, size_t n) { char* p = (char*)b; size_t o = 0; while (o < n) { ssize_t k = recv(fd, p+o, n-o, 0); if (k <= 0) return -1; o += k; } return 0; }
static double nowSec() { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec + t.tv_nsec * 1e-9; }

// Small integers (< 2^12) so that the float sum over ranks is exact. Same as nccl_ar2.cu.
__host__ __device__ static inline float val(int rank, int it, size_t i) {
  uint32_t h = (uint32_t)(i * 2654435761u) ^ (uint32_t)(it * 40503u) ^ (uint32_t)(rank * 2246822519u);
  h ^= h >> 13;
  return (float)((h & 0x3FF) + 1024u * (uint32_t)rank);
}

__global__ void fillKernel(float* s, size_t n, int rank, int it) {
  for (size_t i = blockIdx.x * (size_t)blockDim.x + threadIdx.x; i < n; i += (size_t)gridDim.x * blockDim.x)
    s[i] = val(rank, it, i);
}

// bad[0] = mismatch count, bad[1] = first mismatching index (min), bad[2..3] = got/expect bits of it.
// bcast != 0: expected = rank 0's input (broadcast), else the sum over ranks (all-reduce).
__global__ void checkKernel(const float* r, size_t n, int it, unsigned long long* bad, int bcast) {
  for (size_t i = blockIdx.x * (size_t)blockDim.x + threadIdx.x; i < n; i += (size_t)gridDim.x * blockDim.x) {
    float e = 0.f;
    if (bcast) e = val(0, it, i);
    else for (int k = 0; k < NRANKS; k++) e += val(k, it, i);
    float g = r[i];
    if (__float_as_uint(g) != __float_as_uint(e)) {
      unsigned long long c = atomicAdd(&bad[0], 1ull);
      if (atomicMin(&bad[1], (unsigned long long)i) > i || c == 0) {
        bad[2] = __float_as_uint(g); bad[3] = __float_as_uint(e);
      }
    }
  }
}

// Spin until the stream is done. 0 ok, 3 async NCCL error, 4 timeout, 6 CUDA error.
static int boundedSync(cudaStream_t st, ncclComm_t comm, double timeoutS, int it) {
  double t0 = nowSec();
  for (unsigned spins = 0;; spins++) {
    cudaError_t q = cudaStreamQuery(st);
    if (q == cudaSuccess) break;
    if (q != cudaErrorNotReady) { fprintf(stderr, "[rank%d] iter %d CUDA error %s\n", g_rank, it, cudaGetErrorString(q)); return 6; }
    if ((spins & 255) == 255) {
      ncclResult_t as = ncclSuccess;
      if (ncclCommGetAsyncError(comm, &as) != ncclSuccess || (as != ncclSuccess && as != ncclInProgress)) {
        fprintf(stderr, "[rank%d] iter %d async NCCL error: %s\n", g_rank, it, ncclGetErrorString(as));
        return 3;
      }
      if (nowSec() - t0 > timeoutS) { fprintf(stderr, "[rank%d] iter %d TIMEOUT after %.0f s\n", g_rank, it, timeoutS); return 4; }
    }
  }
  ncclResult_t as = ncclSuccess;
  ncclCommGetAsyncError(comm, &as);
  if (as != ncclSuccess && as != ncclInProgress) { fprintf(stderr, "[rank%d] iter %d async NCCL error after sync: %s\n", g_rank, it, ncclGetErrorString(as)); return 3; }
  return 0;
}

static double pct(std::vector<double> v, double p) {
  if (v.empty()) return 0;
  std::sort(v.begin(), v.end());
  size_t k = (size_t)(p * (v.size() - 1) + 0.5);
  return v[k];
}

int main(int argc, char** argv) {
  double tProc = nowSec();
  int rank = -1, port = 0, iters = 20, start = 0, warmup = 5, quiet = 0;
  const char* ip = nullptr; const char* check = "every"; int bcast = 0;
  size_t count = 1 << 20; double timeoutS = 120.0;
  for (int a = 1; a < argc; a++) {
    auto need = [&](void) { if (a + 1 >= argc) { fprintf(stderr, "missing value for %s\n", argv[a]); exit(1); } return argv[++a]; };
    if (!strcmp(argv[a], "--rank")) rank = atoi(need());
    else if (!strcmp(argv[a], "--ip")) ip = need();
    else if (!strcmp(argv[a], "--port")) port = atoi(need());
    else if (!strcmp(argv[a], "--iters")) iters = atoi(need());
    else if (!strcmp(argv[a], "--start")) start = atoi(need());
    else if (!strcmp(argv[a], "--count")) count = strtoull(need(), 0, 10);
    else if (!strcmp(argv[a], "--warmup")) warmup = atoi(need());
    else if (!strcmp(argv[a], "--check")) check = need();
    else if (!strcmp(argv[a], "--timeout")) timeoutS = atof(need());
    else if (!strcmp(argv[a], "--quiet")) quiet = 1;
    else if (!strcmp(argv[a], "--op")) { const char* o = need(); if (!strcmp(o, "bcast")) bcast = 1; else if (strcmp(o, "allreduce")) { fprintf(stderr, "bad --op\n"); return 1; } }
    else { fprintf(stderr, "unknown argument %s\n", argv[a]); return 1; }
  }
  g_rank = rank;
  int checkMode = !strcmp(check, "every") ? 2 : !strcmp(check, "last") ? 1 : !strcmp(check, "none") ? 0 : -1;
  if ((rank != 0 && rank != 1) || !ip || !port || iters <= 0 || start < 0 || start >= iters || count == 0 || checkMode < 0) {
    fprintf(stderr, "usage: %s --rank 0|1 --ip IP --port P [--iters N] [--start S] [--count C] [--warmup W] [--check every|last|none] [--timeout SEC] [--quiet]\n", argv[0]);
    return 1;
  }
  int one = 1; ncclUniqueId id;
  if (rank == 0) {
    NK(ncclGetUniqueId(&id));
    int ls = socket(AF_INET, SOCK_STREAM, 0); setsockopt(ls, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
    sockaddr_in a{}; a.sin_family = AF_INET; a.sin_addr.s_addr = INADDR_ANY; a.sin_port = htons(port);
    if (bind(ls, (sockaddr*)&a, sizeof a)) { perror("bind"); return 1; }
    listen(ls, 1);
    int cs = accept(ls, 0, 0); setsockopt(cs, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
    if (sendall(cs, &id, sizeof id)) { perror("send id"); return 1; }
    close(cs); close(ls);
  } else {
    int cs;
    sockaddr_in a{}; a.sin_family = AF_INET; a.sin_port = htons(port); inet_pton(AF_INET, ip, &a.sin_addr);
    for (int tries = 0; ; tries++) {
      cs = socket(AF_INET, SOCK_STREAM, 0);
      if (connect(cs, (sockaddr*)&a, sizeof a) == 0) break;
      close(cs);
      if (tries > 3000) { fprintf(stderr, "[rank1] cannot reach rank0\n"); return 1; }
      usleep(20000);
    }
    setsockopt(cs, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
    if (recvall(cs, &id, sizeof id)) { perror("recv id"); return 1; }
    close(cs);
  }
  double tId = nowSec();

  CK(cudaSetDevice(0));
  CK(cudaFree(0));
  double tCuda = nowSec();
  float *sbuf, *rbuf; unsigned long long* dbad;
  CK(cudaMalloc(&sbuf, count * sizeof(float)));
  CK(cudaMalloc(&rbuf, count * sizeof(float)));
  CK(cudaMalloc(&dbad, 4 * sizeof(unsigned long long)));
  cudaStream_t st; CK(cudaStreamCreateWithFlags(&st, cudaStreamNonBlocking));
  ncclComm_t comm;
  double tInit0 = nowSec();
  NK(ncclCommInitRank(&comm, NRANKS, id, rank));
  double tReady = nowSec();
  fprintf(stderr, "[rank%d] comm ready: cuda %.1f ms, commInit %.1f ms, process->ready %.1f ms; iters %d..%d count=%zu\n",
          rank, (tCuda - tId) * 1e3, (tReady - tInit0) * 1e3, (tReady - tProc) * 1e3, start, iters - 1, count);

  int grid = 160, block = 512;
  // Warm-up on iteration-independent data (not counted, not checked).
  for (int w = 0; w < warmup; w++) {
    fillKernel<<<grid, block, 0, st>>>(sbuf, count, rank, -1 - w);
    ncclResult_t r = bcast ? ncclBroadcast(sbuf, rbuf, count, ncclFloat, 0, comm, st)
                           : ncclAllReduce(sbuf, rbuf, count, ncclFloat, ncclSum, comm, st);
    if (r != ncclSuccess) { fprintf(stderr, "[rank%d] warmup ncclAllReduce -> %s\n", rank, ncclGetErrorString(r)); return 2; }
    int rc = boundedSync(st, comm, timeoutS, -1 - w);
    if (rc) { fprintf(stderr, "[rank%d] warmup failed rc=%d\n", rank, rc); return rc; }
  }

  std::vector<double> ms;
  int rc = 0, it = start, okIters = 0;
  double tLoop0 = nowSec();
  for (; it < iters && rc == 0; it++) {
    fillKernel<<<grid, block, 0, st>>>(sbuf, count, rank, it);
    if (checkMode) CK(cudaMemsetAsync(rbuf, 0xFF, count * sizeof(float), st));
    CK(cudaStreamSynchronize(st));
    double t0 = nowSec();
    ncclResult_t r = bcast ? ncclBroadcast(sbuf, rbuf, count, ncclFloat, 0, comm, st)
                           : ncclAllReduce(sbuf, rbuf, count, ncclFloat, ncclSum, comm, st);
    if (r != ncclSuccess) { fprintf(stderr, "[rank%d] iter %d ncclAllReduce -> %s\n", rank, it, ncclGetErrorString(r)); rc = 2; break; }
    rc = boundedSync(st, comm, timeoutS, it);
    if (rc) break;
    double dt = nowSec() - t0;
    if (checkMode == 2 || (checkMode == 1 && it == iters - 1)) {
      unsigned long long hb[4] = {0, ~0ull, 0, 0};
      CK(cudaMemcpyAsync(dbad, hb, sizeof hb, cudaMemcpyHostToDevice, st));
      checkKernel<<<grid, block, 0, st>>>(rbuf, count, it, dbad, bcast);
      CK(cudaMemcpyAsync(hb, dbad, sizeof hb, cudaMemcpyDeviceToHost, st));
      CK(cudaStreamSynchronize(st));
      if (hb[0]) {
        float g, e; uint32_t gb = (uint32_t)hb[2], eb = (uint32_t)hb[3]; memcpy(&g, &gb, 4); memcpy(&e, &eb, 4);
        fprintf(stderr, "[rank%d] iter %d MISMATCH count=%llu first=%llu got=%g expect=%g\n", rank, it, hb[0], hb[1], g, e);
        rc = 5; break;
      }
    }
    ms.push_back(dt * 1e3);
    okIters++;
    if (!quiet) fprintf(stderr, "IT %d %.4f\n", it, dt * 1e3);
  }
  double tLoop1 = nowSec();

  double bytes = (double)count * sizeof(float);
  double med = pct(ms, 0.5);
  double algbw = med > 0 ? bytes / (med * 1e-3) / 1e9 : 0;
  fprintf(stderr, "SUMMARY rank=%d rc=%d start=%d iters=%d ok=%d fail_iter=%d count=%zu bytes=%.0f "
          "cuda_ms=%.1f init_ms=%.1f ready_ms=%.1f loop_ms=%.3f med_ms=%.4f p10_ms=%.4f p90_ms=%.4f p99_ms=%.4f max_ms=%.4f "
          "algbw_GBs=%.3f busbw_GBs=%.3f\n",
          rank, rc, start, iters, okIters, rc ? it : -1, count, bytes,
          (tCuda - tId) * 1e3, (tReady - tInit0) * 1e3, (tReady - tProc) * 1e3, (tLoop1 - tLoop0) * 1e3,
          med, pct(ms, 0.1), pct(ms, 0.9), pct(ms, 0.99), ms.empty() ? 0 : *std::max_element(ms.begin(), ms.end()),
          algbw, algbw * 2.0 * (NRANKS - 1) / NRANKS);

  if (rc == 0) {
    ncclCommDestroy(comm);
  } else {
    const char* wd = getenv("NCCL_CT_ABORT_WATCHDOG_S");
    signal(SIGALRM, abortWatchdog);
    alarm(wd ? (unsigned)atoi(wd) : 20u);
    ncclCommAbort(comm);
    alarm(0);
    fprintf(stderr, "[rank%d] ncclCommAbort returned\n", rank);
  }
  return rc;
}
