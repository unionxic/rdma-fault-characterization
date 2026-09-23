// Minimal 2-rank NCCL all-reduce driver for the 2-node RoCE test (no MPI).
// rank 0 creates the ncclUniqueId and ships it to rank 1 over TCP, then both call
// ncclCommInitRank and loop ncclAllReduce(sum, float).
//
// Result checking (every rank, every iteration):
//   * input  sbuf[i] = val(rank, it, i): distinct per rank, per iteration, per index;
//   * rbuf is poisoned (all-ones bytes = NaN) before each all-reduce, so an element
//     the collective did not write can never compare equal;
//   * the ENTIRE rbuf is copied back and compared bit-exactly with the expected sum
//     (all values are small integers, so float sums are exact);
//   * prints "iter N ok" or "iter N MISMATCH count=C first=I got=G expect=E".
// Bounded: each iteration waits at most <timeout_s>; on an async NCCL error or a
// timeout the communicator is aborted (ncclCommAbort) instead of hanging.
// Exit codes: 0 all iterations ok, 1 usage/setup, 2 NCCL call error, 3 async NCCL
// error, 4 timeout, 5 result mismatch, 6 CUDA error.
//
//   usage: nccl_ar2 <rank 0|1> <rank0_ip> <tcp_port> [iters] [count] [sleep_ms] [timeout_s]
#include <nccl.h>
#include <cuda_runtime.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cstdint>
#include <ctime>
#include <unistd.h>
#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <sys/socket.h>

static const int NRANKS = 2;
static int g_rank = -1;

#define CK(c) do { cudaError_t e_ = (c); if (e_ != cudaSuccess) { \
  fprintf(stderr, "[rank%d] CUDA %s:%d %s\n", g_rank, __FILE__, __LINE__, cudaGetErrorString(e_)); exit(6); } } while (0)
#define NK(c) do { ncclResult_t r_ = (c); if (r_ != ncclSuccess) { \
  fprintf(stderr, "[rank%d] NCCL %s:%d %s\n", g_rank, __FILE__, __LINE__, ncclGetErrorString(r_)); exit(2); } } while (0)

static int sendall(int fd, const void* b, size_t n) { const char* p = (const char*)b; size_t o = 0; while (o < n) { ssize_t k = send(fd, p+o, n-o, 0); if (k <= 0) return -1; o += k; } return 0; }
static int recvall(int fd, void* b, size_t n) { char* p = (char*)b; size_t o = 0; while (o < n) { ssize_t k = recv(fd, p+o, n-o, 0); if (k <= 0) return -1; o += k; } return 0; }

static double nowSec() { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec + t.tv_nsec * 1e-9; }

// Small integers (< 2^12) so that the float sum over ranks is exact.
static inline float val(int rank, int it, size_t i) {
  uint32_t h = (uint32_t)(i * 2654435761u) ^ (uint32_t)(it * 40503u) ^ (uint32_t)(rank * 2246822519u);
  h ^= h >> 13;
  return (float)((h & 0x3FF) + 1024u * (uint32_t)rank);
}

// Wait for the stream without hanging forever. Returns 0 ok, 3 async error, 4 timeout, 6 CUDA error.
static int boundedSync(cudaStream_t st, ncclComm_t comm, double timeoutS, int it) {
  double t0 = nowSec();
  while (1) {
    cudaError_t q = cudaStreamQuery(st);
    if (q == cudaSuccess) break;
    if (q != cudaErrorNotReady) { fprintf(stderr, "[rank%d] iter %d CUDA error %s\n", g_rank, it, cudaGetErrorString(q)); return 6; }
    ncclResult_t as = ncclSuccess;
    if (ncclCommGetAsyncError(comm, &as) != ncclSuccess || (as != ncclSuccess && as != ncclInProgress)) {
      fprintf(stderr, "[rank%d] iter %d async NCCL error: %s\n", g_rank, it, ncclGetErrorString(as));
      return 3;
    }
    if (nowSec() - t0 > timeoutS) { fprintf(stderr, "[rank%d] iter %d TIMEOUT after %.0f s\n", g_rank, it, timeoutS); return 4; }
    usleep(1000);
  }
  ncclResult_t as = ncclSuccess;
  ncclCommGetAsyncError(comm, &as);
  if (as != ncclSuccess && as != ncclInProgress) { fprintf(stderr, "[rank%d] iter %d async NCCL error after sync: %s\n", g_rank, it, ncclGetErrorString(as)); return 3; }
  return 0;
}

int main(int argc, char** argv) {
  if (argc < 4) { fprintf(stderr, "usage: %s <rank 0|1> <rank0_ip> <port> [iters] [count] [sleep_ms] [timeout_s]\n", argv[0]); return 1; }
  int rank = atoi(argv[1]); g_rank = rank;
  const char* peer = argv[2]; int port = atoi(argv[3]);
  int iters = argc > 4 ? atoi(argv[4]) : 20;
  size_t count = argc > 5 ? strtoul(argv[5], 0, 10) : (1 << 20);
  int sleep_ms = argc > 6 ? atoi(argv[6]) : 500;
  double timeoutS = argc > 7 ? atof(argv[7]) : 120.0;
  if ((rank != 0 && rank != 1) || iters <= 0 || count == 0) { fprintf(stderr, "bad arguments\n"); return 1; }
  int one = 1; ncclUniqueId id;

  if (rank == 0) {
    NK(ncclGetUniqueId(&id));
    int ls = socket(AF_INET, SOCK_STREAM, 0); setsockopt(ls, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
    sockaddr_in a{}; a.sin_family = AF_INET; a.sin_addr.s_addr = INADDR_ANY; a.sin_port = htons(port);
    if (bind(ls, (sockaddr*)&a, sizeof a)) { perror("bind"); return 1; }
    listen(ls, 1);
    fprintf(stderr, "[rank0] waiting for rank1 on :%d\n", port);
    int cs = accept(ls, 0, 0); setsockopt(cs, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
    if (sendall(cs, &id, sizeof id)) { perror("send id"); return 1; }
    close(cs); close(ls);
  } else {
    int cs;
    sockaddr_in a{}; a.sin_family = AF_INET; a.sin_port = htons(port); inet_pton(AF_INET, peer, &a.sin_addr);
    for (int tries = 0; ; tries++) {
      cs = socket(AF_INET, SOCK_STREAM, 0);
      if (connect(cs, (sockaddr*)&a, sizeof a) == 0) break;
      close(cs);
      if (tries > 600) { fprintf(stderr, "[rank1] cannot reach rank0\n"); return 1; }
      usleep(200000);
    }
    setsockopt(cs, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
    if (recvall(cs, &id, sizeof id)) { perror("recv id"); return 1; }
    close(cs);
  }

  CK(cudaSetDevice(0));
  float *sbuf, *rbuf;
  CK(cudaMalloc(&sbuf, count * sizeof(float)));
  CK(cudaMalloc(&rbuf, count * sizeof(float)));
  float* hin  = (float*)malloc(count * sizeof(float));
  float* hout = (float*)malloc(count * sizeof(float));
  float* hexp = (float*)malloc(count * sizeof(float));
  if (!hin || !hout || !hexp) { fprintf(stderr, "[rank%d] host alloc failed\n", rank); return 1; }
  cudaStream_t st; CK(cudaStreamCreate(&st));
  ncclComm_t comm; NK(ncclCommInitRank(&comm, NRANKS, id, rank));
  fprintf(stderr, "[rank%d] comm ready, %d iters count=%zu timeout=%.0fs\n", rank, iters, count, timeoutS);

  int okIters = 0, rc = 0;
  for (int it = 0; it < iters && rc == 0; it++) {
    for (size_t i = 0; i < count; i++) {
      hin[i] = val(rank, it, i);
      float e = 0.f;
      for (int r = 0; r < NRANKS; r++) e += val(r, it, i);
      hexp[i] = e;
    }
    CK(cudaMemcpy(sbuf, hin, count * sizeof(float), cudaMemcpyHostToDevice));
    CK(cudaMemset(rbuf, 0xFF, count * sizeof(float)));  // poison: NaN everywhere
    CK(cudaDeviceSynchronize());
    double t0 = nowSec();
    ncclResult_t r = ncclAllReduce(sbuf, rbuf, count, ncclFloat, ncclSum, comm, st);
    if (r != ncclSuccess) { fprintf(stderr, "[rank%d] iter %d ncclAllReduce -> %s\n", rank, it, ncclGetErrorString(r)); rc = 2; break; }
    rc = boundedSync(st, comm, timeoutS, it);
    if (rc) break;
    double dt = nowSec() - t0;
    CK(cudaMemcpy(hout, rbuf, count * sizeof(float), cudaMemcpyDeviceToHost));
    size_t bad = 0, first = 0;
    for (size_t i = 0; i < count; i++) {
      if (memcmp(&hout[i], &hexp[i], sizeof(float)) != 0) { if (bad == 0) first = i; bad++; }
    }
    if (bad) {
      fprintf(stderr, "[rank%d] iter %2d MISMATCH count=%zu first=%zu got=%g expect=%g\n", rank, it, bad, first, hout[first], hexp[first]);
      rc = 5; break;
    }
    okIters++;
    fprintf(stderr, "[rank%d] iter %2d ok (%zu elems exact, %.3f ms)\n", rank, it, count, dt * 1e3);
    if (sleep_ms > 0) usleep(sleep_ms * 1000);
  }

  if (rc == 0) {
    fprintf(stderr, "[rank%d] done: %d/%d iterations ok\n", rank, okIters, iters);
    ncclCommDestroy(comm);
    cudaFree(sbuf); cudaFree(rbuf); free(hin); free(hout); free(hexp);
  } else {
    fprintf(stderr, "[rank%d] FAILED rc=%d after %d ok iterations; aborting communicator\n", rank, rc, okIters);
    ncclCommAbort(comm);  // tears down the (possibly stuck) kernel instead of hanging
  }
  return rc;
}
