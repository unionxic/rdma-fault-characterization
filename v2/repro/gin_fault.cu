// Reproduces NVIDIA/nccl#2483: rank 0 does put+flush N times to rank 1, one put targets an address outside
// the destination window. Shows what device code and ncclCommGetAsyncError see. No NCCL teardown on purpose
// (it can hang after the fault); the process exits right after printing.
// env: N=120 BAD=10 (-1: none) TIMED=0|1 TMO_CYCLES DELAY_CYCLES STALL_S=15
//      BURST=1 (puts per iteration before the flush; the bad one is the first) COUNTER=0|1 (put also bumps a local counter: two QPs)
//      CHUNK=65536 (bytes per put) FLUSH_EVERY=1 (0: one flush at the end, so puts are in flight when a fault is injected) LINGER_MS=0
#include <mpi.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <unistd.h>
#include "cuda_runtime.h"
#include "nccl.h"
#include "nccl_device.h"

#define CHK(x) do { int r_ = (int)(x); if (r_) { printf("FAILED %s -> %d (line %d)\n", #x, r_, __LINE__); fflush(stdout); MPI_Abort(MPI_COMM_WORLD, 1); } } while (0)
static long envl(const char* k, long d) { const char* v = getenv(k); return v ? atol(v) : d; }
static double nowMs() { timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec * 1e3 + t.tv_nsec / 1e6; }

// prog[0] = iteration in progress, prog[1] = phase (1 put, 2 flush, 9 done), prog[2+it] = 1000 + flush result
__global__ void sender(ncclDevComm dc, ncclWindow_t dst, ncclWindow_t src, size_t chunk, size_t winBytes, int n, int bad,
                       int timed, uint64_t tmo, uint64_t delay, int burst, int counter, int flushEvery, volatile int* prog) {
  ncclGin gin{dc, 0};
  for (int it = 0; it < n; it++) {
    prog[0] = it; prog[1] = 1;
    for (int b = 0; b < burst; b++) {
      size_t off = it == bad && b == 0 ? winBytes + (64ull << 20) : (size_t)it * chunk;
      if (counter) gin.put(ncclTeamWorld(dc), 1, dst, off, src, 0, chunk, ncclGin_WeakSignalInc{0}, ncclGin_WeakCounterInc{0});
      else gin.put(ncclTeamWorld(dc), 1, dst, off, src, 0, chunk, ncclGin_WeakSignalInc{0});
    }
    if (flushEvery ? (it + 1) % flushEvery == 0 : it == n - 1) {
      prog[1] = 2;
      int r = 0;
      if (timed) r = (int)gin.flush(ncclCoopCta(), cuda::memory_order_acquire, ncclGin_None{}, tmo);
      else gin.flush(ncclCoopCta());
      prog[2 + it] = 1000 + r;
    }
    for (uint64_t t0 = clock64(); clock64() - t0 < delay;) {}
  }
  prog[0] = n; prog[1] = 9;
}

__global__ void readSignal(ncclDevComm dc, uint64_t* out) { ncclGin gin{dc, 0}; *out = gin.readSignal(0); }

int main(int argc, char** argv) {
  MPI_Init(&argc, &argv);
  int rank, nranks; MPI_Comm_rank(MPI_COMM_WORLD, &rank); MPI_Comm_size(MPI_COMM_WORLD, &nranks);
  const int n = envl("N", 120), bad = envl("BAD", 10), timed = envl("TIMED", 0), burst = envl("BURST", 1), counter = envl("COUNTER", 0);
  const size_t chunk = envl("CHUNK", 64 << 10), winBytes = (size_t)n * chunk;
  ncclUniqueId id; if (rank == 0) CHK(ncclGetUniqueId(&id));
  MPI_Bcast(&id, sizeof id, MPI_BYTE, 0, MPI_COMM_WORLD);
  ncclComm_t comm; CHK(ncclCommInitRank(&comm, nranks, id, rank));
  void *dSrc, *dDst; ncclWindow_t wSrc, wDst;
  CHK(ncclMemAlloc(&dSrc, winBytes)); CHK(ncclMemAlloc(&dDst, winBytes));
  CHK(cudaMemset(dSrc, 0x5a, winBytes)); CHK(cudaMemset(dDst, 0, winBytes));
  CHK(ncclCommWindowRegister(comm, dSrc, winBytes, &wSrc, NCCL_WIN_COLL_SYMMETRIC));
  CHK(ncclCommWindowRegister(comm, dDst, winBytes, &wDst, NCCL_WIN_COLL_SYMMETRIC));
  ncclDevComm dc; ncclDevCommRequirements reqs = NCCL_DEV_COMM_REQUIREMENTS_INITIALIZER;
  reqs.ginSignalCount = 1; reqs.ginCounterCount = counter; reqs.ginConnectionType = NCCL_GIN_CONNECTION_FULL;
  CHK(ncclDevCommCreate(comm, &reqs, &dc));
  MPI_Barrier(MPI_COMM_WORLD);

  if (rank == 0) {
    int* prog; CHK(cudaHostAlloc(&prog, (2 + n) * sizeof(int), cudaHostAllocMapped));
    for (int i = 0; i < 2 + n; i++) prog[i] = 0;
    int* dProg; CHK(cudaHostGetDevicePointer(&dProg, prog, 0));
    printf("CONFIG n=%d bad=%d timed=%d burst=%d counter=%d chunk=%zu\n", n, bad, timed, burst, counter, chunk);
    double t0 = nowMs(), lastMove = t0, stallMs = envl("STALL_S", 15) * 1e3;
    sender<<<1, 1>>>(dc, wDst, wSrc, chunk, winBytes, n, bad, timed, (uint64_t)envl("TMO_CYCLES", 5000000000L),
                     (uint64_t)envl("DELAY_CYCLES", 15000000L), burst, counter, (int)envl("FLUSH_EVERY", 1), dProg);
    int lastIt = -1, lastPhase = 0, stalled = 0; ncclResult_t lastAsync = ncclSuccess; long asyncErrSamples = 0;
    long qCalls = 0, qSlow = 0; double qSlowMs = 0, qMaxMs = 0;
    double* tIt = (double*)calloc(n + 1, sizeof(double));
    while (prog[1] != 9) {
      double tq = nowMs();
      ncclResult_t a; CHK(ncclCommGetAsyncError(comm, &a));
      double t = nowMs();
      qCalls++; if (t - tq > 0.05) { qSlow++; qSlowMs += t - tq; if (t - tq > qMaxMs) qMaxMs = t - tq; } // > 50 us: a host error query ran
      if (a != ncclSuccess) asyncErrSamples++;
      if (a != lastAsync) { printf("ASYNC t=%.0f ms value=%s\n", t - t0, ncclGetErrorString(a)); lastAsync = a; }
      int it = prog[0], ph = prog[1];
      if (it != lastIt || ph != lastPhase) { lastMove = t; if (it != lastIt && it <= n) tIt[it] = t - t0; lastIt = it; lastPhase = ph; }
      if (t - lastMove > stallMs) { printf("STALL at=%s it=%d after %.0f ms without progress\n", ph == 1 ? "put" : "flush", it, t - lastMove); stalled = 1; break; }
      usleep(1000);
    }
    // LINGER_MS: keep the host error query running after the kernel, so its WARN (cause, WQE index) is printed
    for (double tEnd = nowMs() + envl("LINGER_MS", 0); nowMs() < tEnd; usleep(1000)) { ncclResult_t a; CHK(ncclCommGetAsyncError(comm, &a)); }
    for (int it = 0; it < n; it++) {
      int r = prog[2 + it];
      if (r == 0) continue;
      if (it < 3 || (bad >= 0 && it >= bad - 1 && it <= bad + 3) || r != 1000 || it == n - 1)
        printf("REC it=%d started t=%.1f ms flush_result=%s\n", it, tIt[it], ncclGetErrorString((ncclResult_t)(r - 1000)));
    }
    int done = 0, nonSuccess = 0; for (int it = 0; it < n; it++) { if (prog[2 + it]) done++; if (prog[2 + it] > 1000) nonSuccess++; }
    ncclResult_t a; CHK(ncclCommGetAsyncError(comm, &a));
    printf("SUMMARY iterations_returned=%d of %d non_success_flush=%d stalled=%d async_error_samples=%ld async_final=%s elapsed=%.0f ms\n",
           done, n, nonSuccess, stalled, asyncErrSamples, ncclGetErrorString(a), nowMs() - t0);
    printf("ASYNCQ calls=%ld slow=%ld slow_mean_us=%.0f max_us=%.0f\n", qCalls, qSlow, qSlow ? 1e3 * qSlowMs / qSlow : 0.0, 1e3 * qMaxMs);
    int go = 1; MPI_Send(&go, 1, MPI_INT, 1, 0, MPI_COMM_WORLD);
  } else {
    int go; MPI_Recv(&go, 1, MPI_INT, 0, 0, MPI_COMM_WORLD, MPI_STATUS_IGNORE);
    unsigned char* h = (unsigned char*)malloc(winBytes); CHK(cudaMemcpy(h, dDst, winBytes, cudaMemcpyDeviceToHost));
    int got = 0, firstMissing = -1, late = 0;
    for (int it = 0; it < n; it++) {
      if (h[(size_t)it * chunk] != 0x5a || h[(size_t)it * chunk + chunk - 1] != 0x5a) { if (firstMissing < 0) firstMissing = it; continue; }
      got++; late += firstMissing >= 0;
    }
    uint64_t* sig; CHK(cudaHostAlloc(&sig, sizeof *sig, cudaHostAllocMapped)); *sig = ~0ull;
    readSignal<<<1, 1>>>(dc, sig); CHK(cudaDeviceSynchronize());
    printf("RECV slots_arrived=%d of %d first_missing=%d arrived_after_first_missing=%d signal=%llu\n", got, n, firstMissing, late, (unsigned long long)*sig);
  }
  fflush(stdout); MPI_Barrier(MPI_COMM_WORLD); MPI_Finalize(); _exit(0);
}
