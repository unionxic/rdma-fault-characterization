// Reproduces NVIDIA/nccl#2483: rank 0 does put+flush N times to rank 1, one put targets an address outside
// the destination window. Shows what device code and ncclCommGetAsyncError see. No NCCL teardown on purpose
// (it can hang after the fault); the process exits right after printing.
// env: N=120 BAD=10 (-1: none) TIMED=0|1 TMO_CYCLES DELAY_CYCLES STALL_S=15
//      BURST=1 (puts per iteration before the flush; the bad one is the first) COUNTER=0|1 (put also bumps a local counter: two QPs)
//      KILL_RANK=r (rank r dies, the others call ncclCommShrink and run again; needs mpirun --enable-recovery) KILL_AFTER_MS=0 (0: it dies after the run, else this long after init)
//      SPARE=0|1 (1: the last MPI process stays out of the communicator; after the shrink it is added with ncclCommGrow as the last rank and the run is on the grown communicator)
//      NOASK=0|1 (1: never call ncclCommGetAsyncError before the summary, as an application that does not ask)
//      CHUNK=65536 (bytes per put) FLUSH_EVERY=1 (0: one flush at the end, so puts are in flight when a fault is injected) LINGER_MS=0
//      WAITCTR=0|1 (1: wait on the local counter instead of the flush, so the main CQ is not polled; needs COUNTER=1)
//      HOLD_MS=0 (rank 0 stays alive this long after MPI_Finalize while the other ranks exit)
#include <mpi.h>
#include <signal.h>
#include <sys/time.h>
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
                       int timed, uint64_t tmo, uint64_t delay, int burst, int counter, int flushEvery, int waitCtr, volatile int* prog) {
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
      const uint64_t least = (uint64_t)(it + 1) * burst;
      if (waitCtr && timed) r = (int)gin.waitCounter(ncclCoopCta(), 0, least, 56, cuda::memory_order_acquire, tmo);
      else if (waitCtr) gin.waitCounter(ncclCoopCta(), 0, least);
      else if (timed) r = (int)gin.flush(ncclCoopCta(), cuda::memory_order_acquire, ncclGin_None{}, tmo);
      else gin.flush(ncclCoopCta());
      prog[2 + it] = 1000 + r;
    }
    for (uint64_t t0 = clock64(); clock64() - t0 < delay;) {}
  }
  prog[0] = n; prog[1] = 9;
}

__global__ void readSignal(ncclDevComm dc, uint64_t* out) { ncclGin gin{dc, 0}; *out = gin.readSignal(0); }

// The GPU's own send indices (main and companion QP: sq_rsvd_index, cqe_ci), per context, for one peer
__global__ void readQp(ncclDevComm dc, int peer, unsigned long long* out) {
#if NCCL_GIN_GDAKI_ENABLE // the GDAKI types exist in the device pass only
  for (int c = 0; c < (int)dc.ginContextCount; c++) {
    auto ctx = ncclGin{dc, c}._makeCtx();
    ncclGinGdakiGPUContext* g = &((ncclGinGdakiGPUContext*)ctx.handle)[ctx.contextId];
    out[4 * c] = g->gdqp[peer].sq_rsvd_index; out[4 * c + 1] = g->gdqp[peer].cq_sq.cqe_ci;
    out[4 * c + 2] = g->companion_gdqp ? g->companion_gdqp[peer].sq_rsvd_index : 0;
    out[4 * c + 3] = g->companion_gdqp ? g->companion_gdqp[peer].cq_sq.cqe_ci : 0;
  }
#endif
}

// One run on a communicator: windows, device communicator, rank 0 sends to rank 1, the other ranks report.
static int mpiSize, dead = -1, spare = -1; // dead: the MPI rank that is gone, spare: the MPI rank that is not in the communicator
static void phase(ncclComm_t comm, int rank, bool first) {
  const int n = envl("N", 120), bad = first ? envl("BAD", 10) : -1, timed = envl("TIMED", 0), burst = envl("BURST", 1), counter = envl("COUNTER", 0);
  const size_t chunk = envl("CHUNK", 64 << 10), winBytes = (size_t)n * chunk;
  void *dSrc, *dDst; ncclWindow_t wSrc, wDst;
  CHK(ncclMemAlloc(&dSrc, winBytes)); CHK(ncclMemAlloc(&dDst, winBytes));
  CHK(cudaMemset(dSrc, 0x5a, winBytes)); CHK(cudaMemset(dDst, 0, winBytes));
  CHK(ncclCommWindowRegister(comm, dSrc, winBytes, &wSrc, NCCL_WIN_COLL_SYMMETRIC));
  CHK(ncclCommWindowRegister(comm, dDst, winBytes, &wDst, NCCL_WIN_COLL_SYMMETRIC));
  ncclDevComm dc; ncclDevCommRequirements reqs = NCCL_DEV_COMM_REQUIREMENTS_INITIALIZER;
  reqs.ginSignalCount = 1; reqs.ginCounterCount = counter; reqs.ginConnectionType = NCCL_GIN_CONNECTION_FULL;
  CHK(ncclDevCommCreate(comm, &reqs, &dc));
  if (first) MPI_Barrier(MPI_COMM_WORLD); // later runs have lost a rank: the receivers wait for the message from rank 0

  if (rank == 0) {
    int* prog; CHK(cudaHostAlloc(&prog, (2 + n) * sizeof(int), cudaHostAllocMapped));
    for (int i = 0; i < 2 + n; i++) prog[i] = 0;
    int* dProg; CHK(cudaHostGetDevicePointer(&dProg, prog, 0));
    const int waitCtr = (int)envl("WAITCTR", 0);
    printf("CONFIG n=%d bad=%d timed=%d burst=%d counter=%d waitctr=%d chunk=%zu\n", n, bad, timed, burst, counter, waitCtr, chunk);
    double t0 = nowMs(), lastMove = t0, stallMs = envl("STALL_S", 15) * 1e3;
    sender<<<1, 1>>>(dc, wDst, wSrc, chunk, winBytes, n, bad, timed, (uint64_t)envl("TMO_CYCLES", 5000000000L),
                     (uint64_t)envl("DELAY_CYCLES", 15000000L), burst, counter, (int)envl("FLUSH_EVERY", 1), waitCtr, dProg);
    int lastIt = -1, lastPhase = 0, stalled = 0; ncclResult_t lastAsync = ncclSuccess; long asyncErrSamples = 0;
    long qCalls = 0, qSlow = 0; double qSlowMs = 0, qMaxMs = 0;
    double* tIt = (double*)calloc(n + 1, sizeof(double));
    const int noAsk = (int)envl("NOASK", 0);
    while (prog[1] != 9) {
      double tq = nowMs();
      ncclResult_t a = ncclSuccess; if (!noAsk) CHK(ncclCommGetAsyncError(comm, &a));
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
    for (double tEnd = nowMs() + envl("LINGER_MS", 0); nowMs() < tEnd; usleep(1000)) { ncclResult_t a; if (!noAsk) CHK(ncclCommGetAsyncError(comm, &a)); }
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
    for (int p = 1; p < dc.nRanks && !stalled; p++) { // a stalled kernel would block this one
      unsigned long long* q; CHK(cudaHostAlloc(&q, 4 * dc.ginContextCount * sizeof *q, cudaHostAllocMapped));
      readQp<<<1, 1>>>(dc, p, q); CHK(cudaDeviceSynchronize());
      printf("QPIDX peer=%d", p);
      for (int c = 0; c < (int)dc.ginContextCount; c++) printf(" ctx%d main_rsvd=%llu main_cqe_ci=%#llx comp_rsvd=%llu comp_cqe_ci=%#llx", c, q[4 * c], q[4 * c + 1], q[4 * c + 2], q[4 * c + 3]);
      printf("\n"); CHK(cudaFreeHost(q));
    }
    printf("ASYNCQ calls=%ld slow=%ld slow_mean_us=%.0f max_us=%.0f\n", qCalls, qSlow, qSlow ? 1e3 * qSlowMs / qSlow : 0.0, 1e3 * qMaxMs);
    // CPU time of NCCL's error thread: /proc schedstat = ns on CPU, ns waiting, times scheduled
    if (!system("for t in /proc/$PPID/task/*; do grep -q 'NCCL GIN Err' $t/comm 2>/dev/null && echo ERRTHREAD cpu_ns,wait_ns,scheduled=$(tr ' ' , < $t/schedstat); done")) fflush(stdout);
    int go = 1; for (int r = 1; r < mpiSize; r++) if (r != dead && r != spare) MPI_Send(&go, 1, MPI_INT, r, 0, MPI_COMM_WORLD); // ranks >= 2 only hold their QPs
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
  fflush(stdout);
}

int main(int argc, char** argv) {
  MPI_Init(&argc, &argv);
  int rank, nranks; MPI_Comm_rank(MPI_COMM_WORLD, &rank); MPI_Comm_size(MPI_COMM_WORLD, &nranks); mpiSize = nranks;
  ncclUniqueId id; if (rank == 0) CHK(ncclGetUniqueId(&id));
  MPI_Bcast(&id, sizeof id, MPI_BYTE, 0, MPI_COMM_WORLD);
  const int victim = envl("KILL_RANK", -1), afterMs = envl("KILL_AFTER_MS", 0);
  if (envl("SPARE", 0)) spare = --nranks; // nranks: the size of the communicator from here on
  if (rank == spare) { // waits for the grow id, joins as the last rank, then runs as a rank that only holds its QPs
    MPI_Barrier(MPI_COMM_WORLD);
    ncclUniqueId gid; MPI_Recv(&gid, sizeof gid, MPI_BYTE, 0, 1, MPI_COMM_WORLD, MPI_STATUS_IGNORE);
    ncclComm_t grown; double t0 = nowMs(); CHK(ncclCommGrow(NULL, nranks, &gid, nranks - 1, &grown, NULL));
    printf("GROW new rank=%d grow_ms=%.0f\n", nranks - 1, nowMs() - t0); fflush(stdout);
    spare = -1; phase(grown, nranks - 1, false); pause();
  }
  ncclComm_t comm; CHK(ncclCommInitRank(&comm, nranks, id, rank));
  if (afterMs) dead = victim; // it dies during the run: rank 0 does not message it
  if (afterMs && rank == victim) { itimerval t = {{0, 0}, {afterMs / 1000, afterMs % 1000 * 1000}}; setitimer(ITIMER_REAL, &t, NULL); } // SIGALRM ends the process
  phase(comm, rank, true);
  if (victim >= 0) { // the victim has died (or dies now) as with kill -9; the others shrink the communicator and run again
    if (rank == victim) raise(SIGKILL);
    dead = victim;
    sleep(1);
    ncclResult_t a; CHK(ncclCommGetAsyncError(comm, &a));
    ncclComm_t shrunk; double t0 = nowMs();
    CHK(ncclCommShrink(comm, &dead, 1, &shrunk, NULL, NCCL_SHRINK_ABORT));
    printf("SHRINK rank=%d async_before=%s shrink_ms=%.0f\n", rank, ncclGetErrorString(a), nowMs() - t0); fflush(stdout);
    if (spare >= 0) { // the survivors keep their shrunk ranks, the spare becomes the last rank
      ncclUniqueId gid; if (rank == 0) { CHK(ncclCommGetUniqueId(shrunk, &gid)); MPI_Send(&gid, sizeof gid, MPI_BYTE, spare, 1, MPI_COMM_WORLD); }
      ncclComm_t grown; t0 = nowMs(); CHK(ncclCommGrow(shrunk, nranks, rank == 0 ? &gid : NULL, -1, &grown, NULL));
      printf("GROW rank=%d grow_ms=%.0f\n", rank, nowMs() - t0); fflush(stdout);
      spare = -1; shrunk = grown;
    }
    phase(shrunk, rank - (rank > victim), false);
    if (rank == 0) { sleep(1); MPI_Abort(MPI_COMM_WORLD, 0); } // MPI_COMM_WORLD has lost a rank: no barrier, no finalize
    pause();
  }
  MPI_Barrier(MPI_COMM_WORLD); MPI_Finalize();
  if (rank == 0 && envl("HOLD_MS", 0)) { // the communicator and its error thread stay up while the others are gone
    timeval tv; gettimeofday(&tv, NULL); printf("HOLD ms=%ld from wall=%ld.%03ld\n", envl("HOLD_MS", 0), (long)tv.tv_sec, (long)tv.tv_usec / 1000); fflush(stdout);
    usleep(envl("HOLD_MS", 0) * 1000);
  }
  _exit(0);
}
