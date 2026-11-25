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
//      ACCEPT=<name> (scenario name in the ACCEPT verdict line) DESTROY=0|1 (1: tear down after the run and time it; no-fault runs only)
// Every put (request) has its own destination slot and a payload naming it; the receiver checks every word of every slot.
// Lines: ACCEPT (verdict), LAT (call times, ms from kernel start), TIMES (init/teardown ms), MEM (this process at the end of the run).
#include <mpi.h>
#include <algorithm>
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
static double nowMs(clockid_t c = CLOCK_MONOTONIC) { timespec t; clock_gettime(c, &t); return t.tv_sec * 1e3 + t.tv_nsec / 1e6; }

// prog[0] = iteration in progress, prog[1] = phase (1 put, 2 flush, 3 flush returned, 9 done), prog[2+it] = 1000 + flush result
__global__ void sender(ncclDevComm dc, ncclWindow_t dst, ncclWindow_t src, size_t chunk, size_t winBytes, int n, int bad,
                       int timed, uint64_t tmo, uint64_t delay, int burst, int counter, int flushEvery, int waitCtr, volatile int* prog) {
  ncclGin gin{dc, 0};
  for (int it = 0; it < n; it++) {
    prog[0] = it; prog[1] = 1;
    for (int b = 0; b < burst; b++) {
      const size_t slot = ((size_t)it * burst + b) * chunk;
      size_t off = it == bad && b == 0 ? winBytes + (64ull << 20) : slot;
      if (counter) gin.put(ncclTeamWorld(dc), 1, dst, off, src, slot, chunk, ncclGin_WeakSignalInc{0}, ncclGin_WeakCounterInc{0});
      else gin.put(ncclTeamWorld(dc), 1, dst, off, src, slot, chunk, ncclGin_WeakSignalInc{0});
    }
    if (flushEvery ? (it + 1) % flushEvery == 0 : it == n - 1) {
      prog[1] = 2;
      int r = 0;
      const uint64_t least = (uint64_t)(it + 1) * burst;
      if (waitCtr && timed) r = (int)gin.waitCounter(ncclCoopCta(), 0, least, 56, cuda::memory_order_acquire, tmo);
      else if (waitCtr) gin.waitCounter(ncclCoopCta(), 0, least);
      else if (timed) r = (int)gin.flush(ncclCoopCta(), cuda::memory_order_acquire, ncclGin_None{}, tmo);
      else gin.flush(ncclCoopCta());
      prog[2 + it] = 1000 + r; prog[1] = 3;
    }
    for (uint64_t t0 = clock64(); clock64() - t0 < delay;) {}
  }
  prog[0] = n; prog[1] = 9;
}

__global__ void readSignal(ncclDevComm dc, int counter, uint64_t* out) { ncclGin gin{dc, 0}; out[0] = gin.readSignal(0); if (counter) out[1] = gin.readCounter(0); }

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
static double initMs;
static void phase(ncclComm_t comm, int rank, bool first) {
  const int n = envl("N", 120), bad = first ? envl("BAD", 10) : -1, timed = envl("TIMED", 0), burst = envl("BURST", 1), counter = envl("COUNTER", 0);
  const size_t chunk = envl("CHUNK", 64 << 10), nreq = (size_t)n * burst, winBytes = nreq * chunk, words = chunk / 8;
  void *dSrc, *dDst; ncclWindow_t wSrc, wDst;
  CHK(ncclMemAlloc(&dSrc, winBytes)); CHK(ncclMemAlloc(&dDst, winBytes));
  uint64_t* pat = (uint64_t*)malloc(winBytes); // word w of request i's slot: (i + 1) << 32 | w
  for (size_t w = 0; w < winBytes / 8; w++) pat[w] = (w / words + 1) << 32 | w % words;
  CHK(cudaMemcpy(dSrc, pat, winBytes, cudaMemcpyHostToDevice)); CHK(cudaMemset(dDst, 0, winBytes));
  double t = nowMs();
  CHK(ncclCommWindowRegister(comm, dSrc, winBytes, &wSrc, NCCL_WIN_COLL_SYMMETRIC));
  CHK(ncclCommWindowRegister(comm, dDst, winBytes, &wDst, NCCL_WIN_COLL_SYMMETRIC));
  const double winMs = nowMs() - t;
  ncclDevComm dc; ncclDevCommRequirements reqs = NCCL_DEV_COMM_REQUIREMENTS_INITIALIZER;
  reqs.ginSignalCount = 1; reqs.ginCounterCount = counter; reqs.ginConnectionType = NCCL_GIN_CONNECTION_FULL;
  t = nowMs(); CHK(ncclDevCommCreate(comm, &reqs, &dc)); const double devMs = nowMs() - t;
  if (first) MPI_Barrier(MPI_COMM_WORLD); // later runs have lost a rank: the receivers wait for the message from rank 0
  const bool accept = dc.nRanks > 1 && !(first && dead == 1); // comm rank 1 is alive and reports its check to rank 0
  uint64_t* vals; CHK(cudaHostAlloc(&vals, 2 * sizeof *vals, cudaHostAllocMapped)); vals[0] = vals[1] = ~0ull; // signal, counter

  if (rank == 0) {
    int* prog; CHK(cudaHostAlloc(&prog, (2 + n) * sizeof(int), cudaHostAllocMapped));
    for (int i = 0; i < 2 + n; i++) prog[i] = 0;
    int* dProg; CHK(cudaHostGetDevicePointer(&dProg, prog, 0));
    const int waitCtr = (int)envl("WAITCTR", 0);
    printf("CONFIG n=%d bad=%d timed=%d burst=%d counter=%d waitctr=%d chunk=%zu\n", n, bad, timed, burst, counter, waitCtr, chunk);
    double t0 = nowMs(), t0Wall = nowMs(CLOCK_REALTIME), lastMove = t0, stallMs = envl("STALL_S", 15) * 1e3;
    sender<<<1, 1>>>(dc, wDst, wSrc, chunk, winBytes, n, bad, timed, (uint64_t)envl("TMO_CYCLES", 5000000000L),
                     (uint64_t)envl("DELAY_CYCLES", 15000000L), burst, counter, (int)envl("FLUSH_EVERY", 1), waitCtr, dProg);
    int lastIt = -1, lastPhase = 0, stalled = 0; ncclResult_t lastAsync = ncclSuccess; long asyncErrSamples = 0;
    long qCalls = 0, qSlow = 0; double qSlowMs = 0, qMaxMs = 0;
    double* tIt = (double*)calloc(n + 1, sizeof(double));
    const int noAsk = (int)envl("NOASK", 0);
    int scan = 0, failIt = -1, longIt = -1; double tFail = -1, tCall = 0, longMs = 0, longStart = -1; // first failed and longest flush/wait
    for (int fin = 0; !fin; usleep(1000)) { // one more pass after the kernel is done, to see its last call return
      fin = prog[1] == 9;
      double tq = nowMs();
      ncclResult_t a = ncclSuccess; if (!noAsk) CHK(ncclCommGetAsyncError(comm, &a));
      double t = nowMs();
      qCalls++; if (t - tq > 0.05) { qSlow++; qSlowMs += t - tq; if (t - tq > qMaxMs) qMaxMs = t - tq; } // > 50 us: a host error query ran
      if (a != ncclSuccess) asyncErrSamples++;
      if (a != lastAsync) { printf("ASYNC t=%.0f ms value=%s\n", t - t0, ncclGetErrorString(a)); lastAsync = a; }
      int it = prog[0], ph = prog[1];
      if (lastPhase == 2 && (ph != 2 || it != lastIt) && t - tCall > longMs) { longMs = t - tCall; longIt = lastIt; longStart = tCall - t0; }
      if (ph == 2 && (lastPhase != 2 || it != lastIt)) tCall = t;
      for (; scan < n && (scan < it || prog[2 + scan]); scan++) if (prog[2 + scan] > 1000 && failIt < 0) { failIt = scan; tFail = t - t0; }
      if (it != lastIt || ph != lastPhase) { lastMove = t; if (it != lastIt && it <= n) tIt[it] = t - t0; lastIt = it; lastPhase = ph; }
      if (t - lastMove > stallMs) { printf("STALL at=%s it=%d after %.0f ms without progress\n", ph == 1 ? "put" : "flush", it, t - lastMove); stalled = 1; break; }
    }
    const double endMs = nowMs() - t0;
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
    printf("LAT t0_wall_ms=%.1f bad_start_ms=%.1f first_fail_it=%d first_fail_ms=%.1f longest_call_it=%d longest_call_start_ms=%.1f longest_call_ms=%.1f end_ms=%.1f\n",
           t0Wall, bad >= 0 && bad < n ? tIt[bad] : -1.0, failIt, tFail, longIt, longStart, longMs, endMs);
    if (counter && !stalled) { readSignal<<<1, 1>>>(dc, 1, vals); CHK(cudaDeviceSynchronize()); }
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
    long res[3] = {-1, -1, -1}; // from comm rank 1: requests arrived intact, slots holding anything else, signal
    if (accept) {
      MPI_Recv(res, 3, MPI_LONG, MPI_ANY_SOURCE, 2, MPI_COMM_WORLD, MPI_STATUS_IGNORE);
      const bool hasBad = bad >= 0 && bad < n; const long expArr = nreq - hasBad, expFail = timed && hasBad, ctr = counter ? (long)vals[1] : 0;
      char ex[32] = "all_arrive"; if (hasBad) snprintf(ex, sizeof ex, "only_req%zu_fails", (size_t)bad * burst);
      const bool pass = res[0] == expArr && !res[1] && res[2] == expArr && ctr == (counter ? expArr : 0) && nonSuccess == expFail && !stalled;
      // a duplicate write of the same payload to its own slot leaves no trace in memory: only signal and counter excess show it
      printf("ACCEPT scenario=%s expect=%s arrived=%ld/%ld duplicates=%ld wrong_content=%ld signal=%ld/%ld counter=%ld/%ld failed_calls=%d/%ld stalled=%d => %s\n",
             getenv("ACCEPT") ? getenv("ACCEPT") : "-", ex, res[0], expArr, std::max({0L, res[2] - expArr, ctr - expArr}), res[1], res[2], expArr,
             ctr, counter ? expArr : 0, nonSuccess, expFail, stalled, pass ? "PASS" : "FAIL");
    }
  } else {
    int go; MPI_Recv(&go, 1, MPI_INT, 0, 0, MPI_COMM_WORLD, MPI_STATUS_IGNORE);
    uint64_t* g = (uint64_t*)malloc(winBytes); CHK(cudaMemcpy(g, dDst, winBytes, cudaMemcpyDeviceToHost));
    long got = 0, wrong = 0; int firstMissing = -1, late = 0;
    for (size_t i = 0; i < nreq; i++) { // a slot holds its request's payload, zeros, or anything else (wrong)
      size_t eq = 0, zero = 0;
      for (size_t w = i * words; w < (i + 1) * words; w++) { eq += g[w] == pat[w]; zero += !g[w]; }
      if (eq < words) { if (firstMissing < 0) firstMissing = i; wrong += zero < words; continue; }
      got++; late += firstMissing >= 0;
    }
    readSignal<<<1, 1>>>(dc, 0, vals); CHK(cudaDeviceSynchronize());
    printf("RECV slots_arrived=%ld of %zu first_missing=%d arrived_after_first_missing=%d signal=%llu\n", got, nreq, firstMissing, late, (unsigned long long)vals[0]);
    long res[3] = {got, wrong, (long)vals[0]};
    if (accept && rank == 1) MPI_Send(res, 3, MPI_LONG, 0, 2, MPI_COMM_WORLD);
  }
  fflush(stdout);
  char cmd[512]; // MEM: this process with the communicator up (gpu_mib: nvidia-smi's per-process used memory)
  snprintf(cmd, sizeof cmd, "echo MEM rank=%d $(grep -E '^(VmHWM|VmRSS|VmPin|VmLck|Threads):' /proc/$PPID/status | tr -d ' \\t' | tr ':\\n' '= ')"
           "fds=$(ls /proc/$PPID/fd | wc -l) gpu_mib=$(nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader,nounits | awk -F', ' -v p=$PPID '$1==p{print $2}')", rank);
  if (system(cmd)) {}
  double tDestroy = -1;
  if (envl("DESTROY", 0)) {
    t = nowMs(); CHK(ncclDevCommDestroy(comm, &dc)); CHK(ncclCommWindowDeregister(comm, wSrc)); CHK(ncclCommWindowDeregister(comm, wDst));
    CHK(ncclMemFree(dSrc)); CHK(ncclMemFree(dDst)); CHK(ncclCommFinalize(comm)); CHK(ncclCommDestroy(comm)); tDestroy = nowMs() - t;
  }
  printf("TIMES rank=%d init_ms=%.1f winreg_ms=%.1f devcomm_ms=%.1f destroy_ms=%.1f\n", rank, initMs, winMs, devMs, tDestroy);
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
  ncclComm_t comm; double t = nowMs(); CHK(ncclCommInitRank(&comm, nranks, id, rank)); initMs = nowMs() - t;
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
