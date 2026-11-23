// Reproduces NVIDIA/nvshmem#120 on one node: PE 0 does p + quiet + g to PE 1 N times; one p targets an address
// outside the symmetric heap. Shows whether quiet returns, what g returns, and what arrived. Exits without finalize.
// env: N=40 BAD=10 (-1: none) STALL_S=15 KIND=0 (bad op: 0 p far outside the heap, 1 atomic add on a misaligned address) HOLD_S=0 (sleep before exit) CHECK=0 (1: the kernel asks nvshmemx_get_op_error after quiet and stops) THREADS=1 (GPU threads sharing the QP; only thread 0 sends the bad op; with CHECK=1 they stop together one iteration after it)
#include <mpi.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <unistd.h>
#include "nvshmem.h"
#include "nvshmemx.h"

#define CHK(x) do { int r_ = (int)(x); if (r_) { printf("FAILED %s -> %d (line %d)\n", #x, r_, __LINE__); fflush(stdout); MPI_Abort(MPI_COMM_WORLD, 1); } } while (0)
static long envl(const char* k, long d) { const char* v = getenv(k); return v ? atol(v) : d; }
static double nowMs() { timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec * 1e3 + t.tv_nsec / 1e6; }

// prog[0] = iteration in progress, prog[1] = 9 when done (8: stopped on an error), prog[2+it] = 1 after quiet returned, got[it] = value from g
// miss[0] = quiets that returned after the bad iteration while the query still said "no error", miss[1] = last query status
__global__ void sender(int* dst, int n, int bad, int kind, int check, volatile int* prog, int* got, int* miss) {
  const bool t0 = threadIdx.x == 0, many = blockDim.x > 1;
  for (int it = 0; it < n; it++) {
    if (t0) prog[0] = it;
    int* p = it == bad && t0 ? dst + (2ull << 30) / sizeof(int) : dst + it;
    if (it == bad && t0 && kind == 1) nvshmem_long_atomic_add((long*)((char*)dst + 1), 1, 1);
    else nvshmem_int_p(p, 1000 + it, 1);
    nvshmem_quiet();
    nvshmemx_op_error_t e;
    int st = nvshmemx_get_op_error(&e);
    const bool seen = e.error_class != NVSHMEMX_OP_ERROR_NONE, afterBad = bad >= 0 && it > bad;
    if (t0) miss[1] = st;
    if (afterBad && !seen) atomicAdd(miss, 1); // this thread's op at it > bad was flushed, so the record must be set by now
    if (check && (many ? afterBad : seen)) { if (t0) prog[1] = 8; return; } // the same decision in every thread
    if (t0) { prog[2 + it] = 1; got[it] = nvshmem_int_g(dst + it, 1); }
    __syncthreads(); // no thread starts iteration bad + 1 before thread 0 has sent the bad op
  }
  if (t0) prog[1] = 9;
}

int main(int argc, char** argv) {
  MPI_Init(&argc, &argv);
  MPI_Comm c = MPI_COMM_WORLD; nvshmemx_init_attr_t attr = NVSHMEMX_INIT_ATTR_INITIALIZER; attr.mpi_comm = &c;
  CHK(nvshmemx_init_attr(NVSHMEMX_INIT_WITH_MPI_COMM, &attr));
  const int me = nvshmem_my_pe(), n = envl("N", 40), bad = envl("BAD", 10);
  CHK(cudaSetDevice(0)); // NVSHMEM finishes its init only once the application has picked a device
  int* dst = (int*)nvshmem_calloc(n, sizeof(int)); CHK(dst == NULL);
  MPI_Barrier(c);
  if (me == 0) {
    int *prog, *dProg, *got, *dGot, *miss, *dMiss; const int threads = envl("THREADS", 1);
    CHK(cudaHostAlloc(&miss, 2 * sizeof(int), cudaHostAllocMapped)); CHK(cudaHostGetDevicePointer(&dMiss, miss, 0)); miss[0] = miss[1] = 0;
    CHK(cudaHostAlloc(&prog, (2 + n) * sizeof(int), cudaHostAllocMapped)); CHK(cudaHostGetDevicePointer(&dProg, prog, 0));
    CHK(cudaHostAlloc(&got, n * sizeof(int), cudaHostAllocMapped)); CHK(cudaHostGetDevicePointer(&dGot, got, 0));
    for (int i = 0; i < 2 + n; i++) prog[i] = 0;
    for (int i = 0; i < n; i++) got[i] = -1;
    printf("CONFIG n=%d bad=%d\n", n, bad);
    sender<<<1, threads>>>(dst, n, bad, envl("KIND", 0), envl("CHECK", 0), dProg, dGot, dMiss);
    CHK(cudaGetLastError());
    double last = nowMs(), stallMs = envl("STALL_S", 15) * 1e3; int lastIt = -1, stalled = 0;
    while (prog[1] == 0) {
      if (prog[0] != lastIt) { lastIt = prog[0]; last = nowMs(); }
      if (nowMs() - last > stallMs) { printf("STALL it=%d\n", lastIt); stalled = 1; break; }
      usleep(1000);
    }
    if (!stalled) CHK(cudaDeviceSynchronize()); // the kernel has ended: its writes to prog/got/miss are complete
    int quiet = 0, right = 0, firstWrong = -1;
    for (int it = 0; it < n; it++) {
      quiet += prog[2 + it];
      if (got[it] == 1000 + it) right++; else if (firstWrong < 0 && prog[2 + it]) firstWrong = it;
    }
    printf("SUMMARY quiet_returned=%d of %d fetch_right=%d first_wrong_fetch=%d value=%d stalled=%d\n", quiet, n, right,
           firstWrong, firstWrong < 0 ? 0 : got[firstWrong], stalled);
    nvshmemx_op_error_t e; CHK(nvshmemx_get_op_error(&e));
    printf("QUERY kernel_stopped_at=%d class=%d syndrome=%#x vendor_err=%#x wqe_counter=%u threads=%d device_query_status=%d missed_after_bad=%d\n",
           prog[1] == 8 ? prog[0] : -1, e.error_class, e.syndrome, e.vendor_err, e.wqe_counter, threads, miss[1], miss[0]);
    int go = 1; MPI_Send(&go, 1, MPI_INT, 1, 0, c);
  } else {
    int go; MPI_Recv(&go, 1, MPI_INT, 0, 0, c, MPI_STATUS_IGNORE);
    int* h = (int*)malloc(n * sizeof(int)); CHK(cudaMemcpy(h, dst, n * sizeof(int), cudaMemcpyDeviceToHost));
    int arrived = 0, firstMissing = -1;
    for (int it = 0; it < n; it++) { if (h[it] == 1000 + it) arrived++; else if (firstMissing < 0) firstMissing = it; }
    printf("RECV slots_arrived=%d of %d first_missing=%d\n", arrived, n, firstMissing);
  }
  fflush(stdout); sleep(envl("HOLD_S", 0)); MPI_Barrier(c); _exit(0);
}
