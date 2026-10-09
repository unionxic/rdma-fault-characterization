// rs_drain_test.cu - gin-restore feasibility test B3 (EXPERIMENT.md 9.15.3; DRAFT stage, never scored). No NCCL.
//
// Question: once the responder QP's rmsn (QUERY_QP) has reached the number M of request messages the requester posted
// before it paused, are all those RDMA writes in GPU memory for a copy-engine copy made after ONE NIC loopback RDMA READ of
// an 8-byte fence word in ANOTHER allocation through a strict loopback MR (the checkpoint, EXPERIMENT.md 9.4 step 3, as
// fixed by the test-design review)? GIN window MRs are registered with relaxed ordering by default.
//
// Roles (every QP, CQ and MR is created once per process; nothing is created or destroyed per iteration):
//   resp    window (about 2 MiB + a 4 KiB guard) and signal word: cuMem allocations with gpuDirectRDMACapable (as GIN
//           windows), dmabuf MRs with iova 0 and REMOTE_ATOMIC (as gdakiRegMr); order "ro" adds IBV_ACCESS_RELAXED_ORDERING
//           to the window MR, "so" does not; the signal MR is strict (as the GIN signal table). A loopback RC QP pair in a
//           protection domain of its own with two strict MRs: a third cuMem allocation holding the fence word (the
//           design's READ target: the side table) and the window allocation (the same-allocation READ variant).
//   writer  the source is a cuMem buffer on its own GPU (dmabuf MR). Iteration i: on GO(i, tail) a kernel writes the
//           pattern ((i + 1) << 32 | word index) into the source; then, in one doorbell: 16 small writes (64 B - 4 KiB),
//           14 writes of 64 KiB, and per tail: W = the 1 MiB write last; AW = an 8-byte fetch-add of 1 on the signal word,
//           then the 1 MiB write last; WA = the 1 MiB write, then the fetch-add last. Then, without waiting for any
//           completion, PAUSED(i, M) with M = request messages since the baseline (31 or 32 per iteration). It starts the
//           next iteration only after its own last completion and DONE(i).
//   hog     memory-bound copies on this GPU until <stopfile> exists or <secs> pass (GPU contention cells).
// Paths of the responder (one per iteration, a seeded random permutation of this list in every block of 16):
//   fence W x4, fence AW x4 (SCORED), fence WA x1; fsame W x1, AW x1 (READ inside the window allocation); nofence W x1,
//   AW x1 (no READ); cuflush W x1 (cuFlushGPUDirectRDMAWrites(CURRENT_CTX, TO_OWNER) instead of the READ); early W x1
//   (copy right after PAUSED, before rmsn: control); boundary W x1 (copy as soon as rmsn == M - 1, while the last 1 MiB
//   write executes: control).
// fence: rmsn == M -> READ of the fence word (signaled, completion polled) -> cudaMemcpyAsync D2D window -> snapshot ->
// check kernel on the snapshot; also the same check kernel on the window itself (SM reads; information). Every path ends
// with rmsn == M and the fence READ before DONE(i). The snapshot is poisoned (all ones) before every iteration; the window
// starts as "iteration 0". The check counts every word of [0, total) that is not this iteration's value: late (an earlier
// iteration's value of that word) or corrupt (anything else), separately before the last message and inside it; the
// signal word must equal the number of fetch-adds so far (late = one short). Failures are counted per iteration.
// Ordering probe (information; iters / 16 iterations with tail W after the main loop): a one-block kernel launched before
// GO spins on the last word of the window until it holds this iteration's value, then reads every other word: a late one
// means the GPU saw the NIC's writes out of order.
// QUERY_QP (DEVX on the verbs QP): the first one 0.7 x the last reach time after PAUSED, then at least 50 us between starts
// (growing to 1 ms after 50), one at a time; <= 200 per iteration and <= 20 000 per cell, and a single one longer than
// 50 ms, stop the cell (exit 3). The rmsn comparison is modulo 2^24 from a baseline (unit-tested at start).
//
// usage: rs_drain_test <out_kv> resp   <ib_dev> <gid_index> <ro|so> <iters> <listen:<port>|connect:<ip>:<port>>
//        rs_drain_test <out_kv> writer <ib_dev> <gid_index> <ro|so> <iters> <listen:<port>|connect:<ip>:<port>>
//        rs_drain_test <out_kv> hog <secs> <stopfile>
// env: RS_RDV_NONCE (16 hex; the listener greets with "RSDRAIN2"+nonce, the other side sends nothing before it has checked
//      it), RS_WATCHDOG_S (300: hard bound, exit 7), RS_CELL_S (iters / 100 + 60: soft bound, result INCOMPLETE),
//      RS_CUDA_DEV (0), RS_SEED (0x5253), RS_LAST_KB (1024: the last write; only changed if the smoke shows too few
//      edge iterations, recorded in EXPERIMENT.md 12; both sides must use the same value)
// exit: 0 PASS; 1 FENCE_FAIL; 4 INCONCLUSIVE; 5 INCOMPLETE; 2 usage or setup error; 3 NIC, rmsn, QUERY_QP-cap or
//       control-channel error; 6 CUDA error; 7 watchdog. The writer exits 0 when the responder ended the run.
#include <cuda.h>
#include <cuda_runtime.h>
#include <infiniband/verbs.h>
#include <infiniband/mlx5dv.h>
#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <unistd.h>
#include <algorithm>
#include <cerrno>
#include <chrono>
#include <cstdarg>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <string>
#include <thread>
#include <vector>
// mlx5 PRM layouts (QUERY_QP, QUERY_HCA_CAP) from the DOCA GPUNetIO copy inside NCCL (read only; build_feas.sh -I). Last:
// it defines a macro named u8.
#include "mlx5_ifc.h"

static FILE* g_kv = nullptr;
static void kvf(const char* fmt, ...) __attribute__((format(printf, 1, 2)));
static void kvf(const char* fmt, ...) {
  va_list ap;
  va_start(ap, fmt);
  vfprintf(g_kv, fmt, ap);
  va_end(ap);
  fflush(g_kv);
}
#define CK(c)                                                                         \
  do {                                                                                \
    cudaError_t e_ = (c);                                                             \
    if (e_ != cudaSuccess) {                                                          \
      fprintf(stderr, "CUDA %s:%d %s\n", __FILE__, __LINE__, cudaGetErrorString(e_)); \
      kvf("cuda_error=%s line=%d exit=6\n", cudaGetErrorName(e_), __LINE__);          \
      _exit(6);                                                                       \
    }                                                                                 \
  } while (0)
#define CU(c)                                                         \
  do {                                                                \
    CUresult r_ = (c);                                                \
    if (r_ != CUDA_SUCCESS) {                                         \
      const char* n_ = nullptr;                                       \
      cuGetErrorName(r_, &n_);                                        \
      fprintf(stderr, "CU %s:%d %s\n", __FILE__, __LINE__, n_ ? n_ : "?"); \
      kvf("cuda_error=%s line=%d exit=6\n", n_ ? n_ : "?", __LINE__); \
      _exit(6);                                                       \
    }                                                                 \
  } while (0)
static int g_ctl = -1;
[[noreturn]] static void setupFail(const char* what) {
  fprintf(stderr, "setup: %s (errno %d)\n", what, errno);
  kvf("setup_error=\"%s\" errno=%d exit=2\n", what, errno);
  _exit(2);
}
[[noreturn]] static void nicFail(const char* what) {
  fprintf(stderr, "nic: %s (errno %d)\n", what, errno);
  kvf("nic_error=\"%s\" errno=%d result=FAIL exit=3\n", what, errno);
  if (g_ctl >= 0) {  // tell the other side (best effort, one whole Msg of 24 bytes): it exits instead of waiting
    uint32_t m[6] = {4, 0, 0, 0, 0, 0};
    (void)send(g_ctl, m, sizeof(m), MSG_NOSIGNAL);
  }
  _exit(3);
}
static double nowUs() {
  struct timespec t;
  clock_gettime(CLOCK_MONOTONIC, &t);
  return t.tv_sec * 1e6 + t.tv_nsec * 1e-3;
}

// ---- the layout of one iteration's writes ----
static const int NSMALL = 16, NMED = 14, NW = NSMALL + NMED + 1;  // 31 writes; the last (index NW - 1) is 1 MiB
struct Layout {
  size_t off[NW], len[NW], total, lastStart;
};
static Layout makeLayout() {  // RS_LAST_KB (1024): the last write's size (both sides must agree; checked at hello)
  static const size_t small[4] = {64, 256, 1024, 4096};
  const size_t lastKb = getenv("RS_LAST_KB") ? (size_t)atol(getenv("RS_LAST_KB")) : 1024;
  Layout l;
  size_t o = 0;
  for (int k = 0; k < NW; k++) {
    const size_t n = k < NSMALL ? small[k % 4] : k < NSMALL + NMED ? (size_t)64 << 10 : lastKb << 10;
    l.off[k] = o;
    l.len[k] = n;
    o += n;
  }
  l.total = o;  // a multiple of 64
  l.lastStart = l.off[NW - 1];
  return l;
}
enum Tail { T_W = 0, T_AW = 1, T_WA = 2 };
static const char* TAILN[3] = {"W", "AW", "WA"};
static int msgsOf(int tail) { return tail == T_W ? NW : NW + 1; }

// ---- GPU kernels ----
struct Res {
  unsigned long long staleBefore, staleLast, corrupt;
  unsigned int firstCorruptWord, pad;
};
__device__ __forceinline__ unsigned long long ldRelaxedSys64(const unsigned long long* p) {
  unsigned long long v;
  asm volatile("ld.relaxed.sys.global.u64 %0, [%1];" : "=l"(v) : "l"(p) : "memory");
  return v;
}
__device__ __forceinline__ void classify(unsigned long long v, size_t w, unsigned int iter1, size_t lastWord,
                                         unsigned long long* sb, unsigned long long* sl, unsigned long long* c,
                                         Res* r) {
  const unsigned long long want = ((unsigned long long)iter1 << 32) | (unsigned int)w;
  if (v == want) return;
  const unsigned int hi = (unsigned int)(v >> 32), lo = (unsigned int)v;
  if (lo == (unsigned int)w && hi < iter1) {
    if (w >= lastWord) (*sl)++;
    else (*sb)++;
  } else {
    (*c)++;
    atomicMin(&r->firstCorruptWord, (unsigned int)w);
  }
}
__global__ void checkKernel(const unsigned long long* buf, size_t nwords, size_t lastWord, unsigned int iter1, Res* r) {
  unsigned long long sb = 0, sl = 0, c = 0;
  for (size_t w = blockIdx.x * (size_t)blockDim.x + threadIdx.x; w < nwords; w += (size_t)gridDim.x * blockDim.x)
    classify(buf[w], w, iter1, lastWord, &sb, &sl, &c, r);
  if (sb) atomicAdd(&r->staleBefore, sb);
  if (sl) atomicAdd(&r->staleLast, sl);
  if (c) atomicAdd(&r->corrupt, c);
}
// the window read by SM loads that bypass L1 (the copy-free consumer)
__global__ void checkKernelSys(const unsigned long long* buf, size_t nwords, size_t lastWord, unsigned int iter1, Res* r) {
  unsigned long long sb = 0, sl = 0, c = 0;
  for (size_t w = blockIdx.x * (size_t)blockDim.x + threadIdx.x; w < nwords; w += (size_t)gridDim.x * blockDim.x)
    classify(ldRelaxedSys64(buf + w), w, iter1, lastWord, &sb, &sl, &c, r);
  if (sb) atomicAdd(&r->staleBefore, sb);
  if (sl) atomicAdd(&r->staleLast, sl);
  if (c) atomicAdd(&r->corrupt, c);
}
__global__ void fillKernel(unsigned long long* buf, size_t nwords, unsigned int iter1) {
  for (size_t w = blockIdx.x * (size_t)blockDim.x + threadIdx.x; w < nwords; w += (size_t)gridDim.x * blockDim.x)
    buf[w] = ((unsigned long long)iter1 << 32) | (unsigned int)w;
}
__device__ __forceinline__ unsigned long long gtNow() {
  unsigned long long t;
  asm volatile("mov.u64 %0, %%globaltimer;" : "=l"(t));
  return t;
}
// ordering probe: one block; thread 0 spins on the last word, then every thread reads the rest (strong loads)
__global__ void probeKernel(const unsigned long long* win, size_t nwords, unsigned int iter1, Res* r, int* timedOut) {
  __shared__ int ok;
  if (threadIdx.x == 0) {
    const unsigned long long want = ((unsigned long long)iter1 << 32) | (unsigned int)(nwords - 1);
    const unsigned long long t0 = gtNow();
    ok = 0;
    while (gtNow() - t0 < 2000000000ull) {
      if (ldRelaxedSys64(win + nwords - 1) == want) {
        ok = 1;
        break;
      }
    }
    if (!ok) *timedOut = 1;
  }
  __syncthreads();
  if (!ok) return;
  unsigned long long sb = 0, sl = 0, c = 0;
  for (size_t w = threadIdx.x; w < nwords - 1; w += blockDim.x)
    classify(ldRelaxedSys64(win + w), w, iter1, nwords, &sb, &sl, &c, r);
  if (sb) atomicAdd(&r->staleBefore, sb);
  if (c) atomicAdd(&r->corrupt, c);
}
__global__ void hogKernel(const float4* a, float4* b, size_t n) {
  for (size_t i = blockIdx.x * (size_t)blockDim.x + threadIdx.x; i < n; i += (size_t)gridDim.x * blockDim.x) b[i] = a[i];
}

// ---- cuMem allocations (as ncclMemAlloc: pinned device memory, gpuDirectRDMACapable, recommended granularity) ----
static int g_dev = 0;
static void* cuMemAllocRdma(size_t want, size_t* outSize) {
  CUmemAllocationProp prop;
  memset(&prop, 0, sizeof(prop));
  prop.type = CU_MEM_ALLOCATION_TYPE_PINNED;
  prop.location.type = CU_MEM_LOCATION_TYPE_DEVICE;
  prop.location.id = g_dev;
  prop.requestedHandleTypes = CU_MEM_HANDLE_TYPE_POSIX_FILE_DESCRIPTOR;
  prop.allocFlags.gpuDirectRDMACapable = 1;
  size_t gran = 0;
  CU(cuMemGetAllocationGranularity(&gran, &prop, CU_MEM_ALLOC_GRANULARITY_RECOMMENDED));
  const size_t size = ((want + gran - 1) / gran) * gran;
  CUmemGenericAllocationHandle h;
  CU(cuMemCreate(&h, size, &prop, 0));
  CUdeviceptr p = 0;
  CU(cuMemAddressReserve(&p, size, gran, 0, 0));
  CU(cuMemMap(p, size, 0, h, 0));
  CUmemAccessDesc acc;
  memset(&acc, 0, sizeof(acc));
  acc.location.type = CU_MEM_LOCATION_TYPE_DEVICE;
  acc.location.id = g_dev;
  acc.flags = CU_MEM_ACCESS_FLAGS_PROT_READWRITE;
  CU(cuMemSetAccess(p, size, &acc, 1));
  *outSize = size;
  return (void*)p;
}
static ibv_mr* regDmabuf(ibv_pd* pd, void* base, size_t n, int access) {
  int fd = -1;
  if (cuMemGetHandleForAddressRange((void*)&fd, (CUdeviceptr)base, n, CU_MEM_RANGE_HANDLE_TYPE_DMA_BUF_FD, 0) !=
        CUDA_SUCCESS ||
      fd < 0)
    return nullptr;
  ibv_mr* mr = ibv_reg_dmabuf_mr(pd, 0, n, 0 /* iova 0: remote addresses are offsets, as GIN */, fd, access);
  close(fd);
  return mr;
}

// ---- verbs ----
static ibv_port_attr g_pa;
static int g_gid = -1;
static uint8_t g_myGid[16];
static ibv_qp* makeQp(ibv_pd* pd, ibv_cq* cq, int sendWr) {
  ibv_qp_init_attr a;
  memset(&a, 0, sizeof(a));
  a.send_cq = cq;
  a.recv_cq = cq;
  a.qp_type = IBV_QPT_RC;
  a.cap.max_send_wr = sendWr;
  a.cap.max_recv_wr = 1;
  a.cap.max_send_sge = 1;
  a.cap.max_recv_sge = 1;
  return ibv_create_qp(pd, &a);
}
static int g_pathMtu = 0;  // the path MTU of the RC connection to the peer: min of both sides (as NCCL); 0 = local
static bool connectQp(ibv_qp* q, uint32_t dest, int gidIndex, const uint8_t* dgid, int mtu = 0) {
  ibv_qp_attr a;
  memset(&a, 0, sizeof(a));
  a.qp_state = IBV_QPS_INIT;
  a.pkey_index = 0;
  a.port_num = 1;
  a.qp_access_flags = IBV_ACCESS_REMOTE_READ | IBV_ACCESS_REMOTE_WRITE | IBV_ACCESS_REMOTE_ATOMIC | IBV_ACCESS_LOCAL_WRITE;
  if (ibv_modify_qp(q, &a, IBV_QP_STATE | IBV_QP_PKEY_INDEX | IBV_QP_PORT | IBV_QP_ACCESS_FLAGS) != 0) return false;
  memset(&a, 0, sizeof(a));
  a.qp_state = IBV_QPS_RTR;
  a.path_mtu = (enum ibv_mtu)(mtu ? mtu : (int)g_pa.active_mtu);
  a.dest_qp_num = dest;
  a.rq_psn = 0;
  a.max_dest_rd_atomic = 16;
  a.min_rnr_timer = 12;
  a.ah_attr.port_num = 1;
  a.ah_attr.is_global = 1;
  memcpy(a.ah_attr.grh.dgid.raw, dgid, 16);
  a.ah_attr.grh.sgid_index = (uint8_t)gidIndex;
  a.ah_attr.grh.hop_limit = 64;
  a.ah_attr.grh.traffic_class = 0;  // NCCL_IB_TC default, as GIN
  if (ibv_modify_qp(q, &a, IBV_QP_STATE | IBV_QP_AV | IBV_QP_PATH_MTU | IBV_QP_DEST_QPN | IBV_QP_RQ_PSN |
                             IBV_QP_MAX_DEST_RD_ATOMIC | IBV_QP_MIN_RNR_TIMER) != 0)
    return false;
  memset(&a, 0, sizeof(a));
  a.qp_state = IBV_QPS_RTS;
  a.timeout = 14;
  a.retry_cnt = 7;
  a.rnr_retry = 7;
  a.sq_psn = 0;
  a.max_rd_atomic = 16;
  return ibv_modify_qp(q, &a, IBV_QP_STATE | IBV_QP_TIMEOUT | IBV_QP_RETRY_CNT | IBV_QP_RNR_RETRY | IBV_QP_SQ_PSN |
                                  IBV_QP_MAX_QP_RD_ATOMIC) == 0;
}
static bool cqWait(ibv_cq* cq, uint64_t id, double ms, char* err, size_t errn) {
  const double t0 = nowUs();
  ibv_wc wc[8];
  while (nowUs() - t0 < ms * 1e3) {
    const int n = ibv_poll_cq(cq, 8, wc);
    if (n < 0) {
      snprintf(err, errn, "ibv_poll_cq failed");
      return false;
    }
    for (int k = 0; k < n; k++) {
      if (wc[k].status != IBV_WC_SUCCESS) {
        snprintf(err, errn, "completion status %d (%s) vendor_err %#x wr_id %lu", (int)wc[k].status,
                 ibv_wc_status_str(wc[k].status), wc[k].vendor_err, (unsigned long)wc[k].wr_id);
        return false;
      }
      if (wc[k].wr_id == id) return true;
    }
  }
  snprintf(err, errn, "no completion of wr %lu within %.0f ms", (unsigned long)id, ms);
  return false;
}

// ---- QUERY_QP (rmsn) with pacing and caps ----
static const uint32_t MASK24 = 0xffffffu;
static inline uint32_t rmsnDelta(uint32_t cur, uint32_t base) { return (cur - base) & MASK24; }
static bool rmsnSelfTest() {  // T3-9: the modulo-2^24 comparison across the wrap
  struct { uint32_t base, cur, want; } c[] = {{0, 31, 31}, {0xfffff0u, 0x00000fu, 0x1fu}, {0xffffffu, 0, 1},
                                             {5, 5, 0}, {0x800000u, 0x7fffffu, 0xffffffu}};
  for (auto& x : c)
    if (rmsnDelta(x.cur, x.base) != x.want) return false;
  return true;
}
static unsigned long long g_queryQp = 0;
static std::vector<double> g_qLat;
static double g_lastQueryStart = 0;
static const long CELL_QUERY_CAP = 20000;
static bool queryRmsnRaw(ibv_qp* q, uint32_t* rmsn, uint32_t* state) {
  uint32_t in[DEVX_ST_SZ_DW(query_qp_in)];
  uint32_t out[DEVX_ST_SZ_DW(query_qp_out)];
  memset(in, 0, sizeof(in));
  memset(out, 0, sizeof(out));
  DEVX_SET(query_qp_in, in, opcode, MLX5_CMD_OP_QUERY_QP);
  DEVX_SET(query_qp_in, in, qpn, q->qp_num);
  if (mlx5dv_devx_qp_query(q, in, sizeof(in), out, sizeof(out)) != 0) return false;
  const void* qpc = DEVX_ADDR_OF(query_qp_out, out, qpc);
  *rmsn = DEVX_GET(qpc, qpc, rmsn);
  *state = DEVX_GET(qpc, qpc, state);
  return true;
}
// one paced QUERY_QP: >= gapUs after the previous start; caps and the 50 ms rule stop the cell
static void queryRmsn(ibv_qp* q, double gapUs, uint32_t* rmsn, uint32_t* state) {
  while (nowUs() - g_lastQueryStart < gapUs) {
  }
  if ((long)g_queryQp >= CELL_QUERY_CAP) nicFail("QUERY_QP cap of the cell reached");
  const double t0 = nowUs();
  g_lastQueryStart = t0;
  if (!queryRmsnRaw(q, rmsn, state)) nicFail("QUERY_QP (DEVX) failed");
  const double lat = nowUs() - t0;
  g_queryQp++;
  g_qLat.push_back(lat);
  if (lat > 50000.0) nicFail("a QUERY_QP took longer than 50 ms");
}
static int hcaRoWrite(ibv_context* ctx) {
  uint32_t in[DEVX_ST_SZ_DW(query_hca_cap_in)];
  uint32_t out[DEVX_ST_SZ_DW(query_hca_cap_out)];
  memset(in, 0, sizeof(in));
  memset(out, 0, sizeof(out));
  DEVX_SET(query_hca_cap_in, in, opcode, MLX5_CMD_OP_QUERY_HCA_CAP);
  DEVX_SET(query_hca_cap_in, in, op_mod, (0x0 << 1) | 0x1);  // general device caps, current values
  if (mlx5dv_devx_general_cmd(ctx, in, sizeof(in), out, sizeof(out)) != 0) return -1;
  const void* cap = DEVX_ADDR_OF(query_hca_cap_out, out, capability);
  return (int)DEVX_GET(cmd_hca_cap, cap, relaxed_ordering_write);
}

// ---- the control channel (TCP, nonce-verified) ----
static const char kMagic[8] = {'R', 'S', 'D', 'R', 'A', 'I', 'N', '2'};
struct Greet {
  char magic[8];
  uint64_t nonce;
};
enum { M_PAUSED = 1, M_DONE = 2, M_END = 3, M_ERR = 4, M_READY = 5, M_GO = 6 };
struct Msg {
  uint32_t type, iter, tail, pad;
  uint64_t m;
};
static bool sendAll(int fd, const void* p, size_t n) {
  const char* c = (const char*)p;
  while (n) {
    const ssize_t k = send(fd, c, n, MSG_NOSIGNAL);
    if (k <= 0) {
      if (k < 0 && errno == EINTR) continue;
      return false;
    }
    c += k;
    n -= (size_t)k;
  }
  return true;
}
static bool recvAll(int fd, void* p, size_t n, int ms) {
  char* c = (char*)p;
  const double t0 = nowUs();
  while (n) {
    struct pollfd pf = {fd, POLLIN, 0};
    const int left = ms - (int)((nowUs() - t0) / 1e3);
    if (left <= 0 || poll(&pf, 1, left) != 1) return false;
    const ssize_t k = recv(fd, c, n, 0);
    if (k <= 0) {
      if (k < 0 && errno == EINTR) continue;
      return false;
    }
    c += k;
    n -= (size_t)k;
  }
  return true;
}
static void ctlOpen(const char* spec) {
  const char* s = getenv("RS_RDV_NONCE");
  if (!s || strlen(s) != 16) setupFail("RS_RDV_NONCE (16 hex digits) is required");
  const uint64_t nonce = strtoull(s, nullptr, 16);
  int one = 1;
  if (strncmp(spec, "listen:", 7) == 0) {
    const int ls = socket(AF_INET, SOCK_STREAM, 0);
    setsockopt(ls, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
    sockaddr_in a{};
    a.sin_family = AF_INET;
    a.sin_addr.s_addr = INADDR_ANY;
    a.sin_port = htons((uint16_t)atoi(spec + 7));
    if (bind(ls, (sockaddr*)&a, sizeof(a)) != 0 || listen(ls, 4) != 0) setupFail("control listen");
    int foreign = 0;
    const double t0 = nowUs();
    while (g_ctl < 0) {
      struct pollfd pf = {ls, POLLIN, 0};
      if (nowUs() - t0 > 60e6) setupFail("no verified control connection within 60 s");
      if (poll(&pf, 1, 1000) <= 0) continue;
      const int c = accept(ls, nullptr, nullptr);
      if (c < 0) continue;
      Greet g, an;
      memcpy(g.magic, kMagic, 8);
      g.nonce = nonce;
      if (sendAll(c, &g, sizeof(g)) && recvAll(c, &an, sizeof(an), 2000) && memcmp(an.magic, kMagic, 8) == 0 &&
          an.nonce == nonce) {
        g_ctl = c;
      } else {
        foreign++;
        close(c);
      }
    }
    close(ls);
    kvf("ctl=listen rdv=verified rdv_foreign=%d\n", foreign);
  } else if (strncmp(spec, "connect:", 8) == 0) {
    char host[64];
    snprintf(host, sizeof(host), "%s", spec + 8);
    char* colon = strrchr(host, ':');
    if (!colon) setupFail("connect:<ip>:<port>");
    *colon = 0;
    sockaddr_in a{};
    a.sin_family = AF_INET;
    a.sin_port = htons((uint16_t)atoi(colon + 1));
    if (inet_pton(AF_INET, host, &a.sin_addr) != 1) setupFail("bad control address");
    int rejected = 0;
    const double t0 = nowUs();
    while (g_ctl < 0) {
      if (nowUs() - t0 > 60e6) setupFail("no verified control connection within 60 s");
      const int c = socket(AF_INET, SOCK_STREAM, 0);
      if (connect(c, (sockaddr*)&a, sizeof(a)) == 0) {
        Greet g;
        if (recvAll(c, &g, sizeof(g), 2000) && memcmp(g.magic, kMagic, 8) == 0 && g.nonce == nonce &&
            sendAll(c, &g, sizeof(g))) {
          g_ctl = c;
          break;
        }
        rejected++;  // not our listener: closed without a byte of ours
      }
      close(c);
      usleep(200000);
    }
    kvf("ctl=connect rdv=verified rdv_rejected=%d\n", rejected);
  } else {
    setupFail("control spec");
  }
  setsockopt(g_ctl, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));
}
static void ctlSend(uint32_t type, uint32_t iter, uint32_t tail, uint64_t m) {
  Msg x = {type, iter, tail, 0, m};
  if (!sendAll(g_ctl, &x, sizeof(x))) nicFail("control send");
}
static Msg ctlRecv(int ms) {
  Msg x;
  if (!recvAll(g_ctl, &x, sizeof(x), ms)) nicFail("control receive (peer gone or bound)");
  if (x.type == M_ERR) nicFail("the peer reported an error");
  return x;
}

// ---- the responder ----
static Layout L;
struct Resp {
  ibv_pd *pd, *lbPd;
  ibv_cq *cq, *lbCq;
  ibv_qp *qp, *qa, *qb;
  ibv_mr *winMr, *sigMr, *lbFenceMr, *lbWinMr, *stageMr;
  uint8_t* stage;
  void *win, *sig, *fence, *snap;
  size_t winBytes, sigBytes, fenceBytes;
  Res* res;
  int* timedOut;
  cudaStream_t st, pst;
  uint32_t rmsn0;
};
static uint64_t g_wrId = 1;
enum Path { P_FENCE = 0, P_FSAME, P_NOFENCE, P_CUFLUSH, P_EARLY, P_BOUNDARY, P_PROBE, NPATH };
static const char* PATHN[NPATH] = {"fence", "fsame", "nofence", "cuflush", "early", "boundary", "probe"};
struct Tally {
  long n = 0, itersBad = 0, itersStale = 0, itersStaleBefore = 0, itersStaleLast = 0, itersCorrupt = 0, sigLate = 0,
       sigBad = 0;
  unsigned long long staleBefore = 0, staleLast = 0, corrupt = 0;
};
static Tally T[NPATH][3];        // [path][tail]
static Tally TS[3];               // fence: the SM check of the window (information)
static long probeTimeouts = 0, boundaryMissed = 0, edgeSeen = 0, scoredN = 0;
static std::vector<double> reachUs, readUs, flushUs, goPausedUs;
static long pollsMax = 0;
static std::vector<long> fenceFail;
static double estReachUs = 0;
static uint64_t g_atomics = 0;  // fetch-adds so far (the expected signal value)

static void readFence(Resp& r, bool sameAlloc, bool record) {
  ibv_sge sg;
  ibv_send_wr wr, *bad = nullptr;
  memset(&wr, 0, sizeof(wr));
  sg.addr = (uint64_t)(uintptr_t)r.stage;
  sg.length = 8;
  sg.lkey = r.stageMr->lkey;
  wr.wr_id = g_wrId++;
  wr.sg_list = &sg;
  wr.num_sge = 1;
  wr.opcode = IBV_WR_RDMA_READ;
  wr.send_flags = IBV_SEND_SIGNALED;
  wr.wr.rdma.remote_addr = sameAlloc ? L.total + 64 : 0;  // the window's guard, or the fence word
  wr.wr.rdma.rkey = sameAlloc ? r.lbWinMr->rkey : r.lbFenceMr->rkey;
  const double t0 = nowUs();
  if (ibv_post_send(r.qa, &wr, &bad) != 0) nicFail("fence READ post");
  char err[192];
  if (!cqWait(r.lbCq, wr.wr_id, 2000, err, sizeof(err))) nicFail(err);
  if (record) readUs.push_back(nowUs() - t0);
}
// poll until rmsn - rmsn0 == target (mod 2^24); returns the number of polls; sawBelow: a poll saw less than target
// *reachStart (if not null): start of the poll that saw the target, after tPaused (the poll's own latency is not in it)
static long waitRmsn(Resp& r, uint64_t target, double tPaused, bool* sawBelow, bool stopAtBelowOne,
                     double* reachStart = nullptr) {
  const double start = tPaused + 0.7 * estReachUs;
  while (nowUs() < start) {
  }
  const uint32_t want = (uint32_t)(target & MASK24);
  long polls = 0;
  const double t0 = nowUs();
  *sawBelow = false;
  while (true) {
    uint32_t rmsn = 0, st = 0;
    queryRmsn(r.qp, polls < 50 ? 50.0 : std::min(1000.0, 50.0 * (polls - 48)), &rmsn, &st);
    polls++;
    const uint32_t got = rmsnDelta(rmsn, r.rmsn0);
    if (got == want) {
      if (reachStart) *reachStart = g_lastQueryStart - tPaused;
      break;
    }
    const uint32_t behind = (want - got) & MASK24;
    if (behind > (uint32_t)(NW + 1)) nicFail("rmsn outside the window of this iteration");
    if (stopAtBelowOne && behind == 1) {
      *sawBelow = true;
      return -polls;  // boundary: rmsn == target - 1
    }
    *sawBelow = true;
    if (st != 0x3) nicFail("responder QP not in RTS");
    if (polls >= 200) nicFail("more than 200 QUERY_QP in one iteration");
    if (nowUs() - t0 > 2e6) nicFail("rmsn did not reach M within 2 s");
  }
  return polls;
}
static void snapshotCheck(Resp& r, int path, int tail, uint32_t iter, bool alsoSm) {
  Res z;
  memset(&z, 0, sizeof(z));
  z.firstCorruptWord = 0xffffffffu;
  CK(cudaMemcpyAsync(r.snap, r.win, L.total, cudaMemcpyDeviceToDevice, r.st));
  uint64_t sig = 0;
  CK(cudaMemcpyAsync(&sig, r.sig, 8, cudaMemcpyDeviceToHost, r.st));
  CK(cudaMemcpyAsync(r.res, &z, sizeof(z), cudaMemcpyHostToDevice, r.st));
  checkKernel<<<120, 256, 0, r.st>>>((const unsigned long long*)r.snap, L.total / 8, L.lastStart / 8, iter + 1, r.res);
  CK(cudaGetLastError());
  Res h;
  CK(cudaMemcpyAsync(&h, r.res, sizeof(h), cudaMemcpyDeviceToHost, r.st));
  Res hs;
  memset(&hs, 0, sizeof(hs));
  if (alsoSm) {
    CK(cudaMemcpyAsync(r.res, &z, sizeof(z), cudaMemcpyHostToDevice, r.st));
    checkKernelSys<<<120, 256, 0, r.st>>>((const unsigned long long*)r.win, L.total / 8, L.lastStart / 8, iter + 1,
                                          r.res);
    CK(cudaGetLastError());
    CK(cudaMemcpyAsync(&hs, r.res, sizeof(hs), cudaMemcpyDeviceToHost, r.st));
  }
  CK(cudaStreamSynchronize(r.st));
  auto tally = [&](Tally& t, const Res& x, bool withSig) {
    t.n++;
    t.staleBefore += x.staleBefore;
    t.staleLast += x.staleLast;
    t.corrupt += x.corrupt;
    if (x.staleBefore || x.staleLast) t.itersStale++;
    if (x.staleBefore) t.itersStaleBefore++;
    if (x.staleLast) t.itersStaleLast++;
    if (x.corrupt) t.itersCorrupt++;
    bool sigWrong = false;
    if (withSig) {
      if (sig == g_atomics) {
      } else if (sig + 1 == g_atomics) {
        t.sigLate++;
        sigWrong = true;
      } else {
        t.sigBad++;
        sigWrong = true;
      }
    }
    if (x.staleBefore || x.staleLast || x.corrupt || sigWrong) t.itersBad++;
    return x.staleBefore || x.staleLast || x.corrupt || sigWrong;
  };
  const bool bad = tally(T[path][tail], h, true);
  if (alsoSm) tally(TS[tail], hs, false);
  if (path == P_FENCE && tail != T_WA && bad && fenceFail.size() < 8) fenceFail.push_back(iter);
}
static void respSetup(Resp& r, ibv_context* ctx, ibv_pd* pd, ibv_cq* cq, bool relaxed) {
  r.pd = pd;
  r.cq = cq;
  r.win = cuMemAllocRdma(L.total + 4096, &r.winBytes);
  r.sig = cuMemAllocRdma(4096, &r.sigBytes);
  r.fence = cuMemAllocRdma(4096, &r.fenceBytes);
  size_t snapBytes = 0;
  r.snap = cuMemAllocRdma(L.total, &snapBytes);
  CK(cudaMalloc((void**)&r.res, sizeof(Res)));
  CK(cudaMalloc((void**)&r.timedOut, sizeof(int)));
  CK(cudaStreamCreateWithFlags(&r.st, cudaStreamNonBlocking));
  CK(cudaStreamCreateWithFlags(&r.pst, cudaStreamNonBlocking));
  fillKernel<<<120, 256>>>((unsigned long long*)r.win, L.total / 8, 0);  // "iteration 0"
  CK(cudaGetLastError());
  CK(cudaMemset(r.sig, 0, r.sigBytes));
  CK(cudaMemset(r.fence, 0, r.fenceBytes));
  CK(cudaDeviceSynchronize());
  const int base = IBV_ACCESS_LOCAL_WRITE | IBV_ACCESS_REMOTE_WRITE | IBV_ACCESS_REMOTE_READ | IBV_ACCESS_REMOTE_ATOMIC;
  r.winMr = regDmabuf(pd, r.win, r.winBytes, base | (relaxed ? IBV_ACCESS_RELAXED_ORDERING : 0));
  r.sigMr = regDmabuf(pd, r.sig, r.sigBytes, base);
  if (!r.winMr || !r.sigMr) setupFail("dmabuf MR of the window or the signal word");
  r.qp = makeQp(pd, cq, 4);
  if (!r.qp) setupFail("responder QP");
  r.lbPd = ibv_alloc_pd(ctx);
  r.lbCq = ibv_create_cq(ctx, 64, nullptr, nullptr, 0);
  if (!r.lbPd || !r.lbCq) setupFail("loopback PD/CQ");
  r.qa = makeQp(r.lbPd, r.lbCq, 16);
  r.qb = makeQp(r.lbPd, r.lbCq, 16);
  if (!r.qa || !r.qb) setupFail("loopback QPs");
  if (!connectQp(r.qa, r.qb->qp_num, g_gid, g_myGid) || !connectQp(r.qb, r.qa->qp_num, g_gid, g_myGid))
    setupFail("loopback connect");
  r.lbFenceMr = regDmabuf(r.lbPd, r.fence, r.fenceBytes, base);  // strict
  r.lbWinMr = regDmabuf(r.lbPd, r.win, r.winBytes, base);        // strict, the same allocation as the window
  if (posix_memalign((void**)&r.stage, 4096, 4096) != 0) setupFail("staging");
  memset(r.stage, 0, 4096);
  r.stageMr = ibv_reg_mr(r.lbPd, r.stage, 4096, IBV_ACCESS_LOCAL_WRITE);
  if (!r.lbFenceMr || !r.lbWinMr || !r.stageMr) setupFail("loopback MRs");
}
// the 16-path block (a seeded random permutation per block)
struct Arm {
  int path, tail;
};
static const Arm BLOCK[16] = {{P_FENCE, T_W},   {P_FENCE, T_W},    {P_FENCE, T_W},    {P_FENCE, T_W},
                              {P_FENCE, T_AW},  {P_FENCE, T_AW},   {P_FENCE, T_AW},   {P_FENCE, T_AW},
                              {P_FENCE, T_WA},  {P_FSAME, T_W},    {P_FSAME, T_AW},   {P_NOFENCE, T_W},
                              {P_NOFENCE, T_AW}, {P_CUFLUSH, T_W}, {P_EARLY, T_W},    {P_BOUNDARY, T_W}};
static uint64_t splitmix(uint64_t* s) {
  uint64_t z = (*s += 0x9e3779b97f4a7c15ull);
  z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9ull;
  z = (z ^ (z >> 27)) * 0x94d049bb133111ebull;
  return z ^ (z >> 31);
}
static std::vector<Arm> schedule(long iters, uint64_t seed) {
  std::vector<Arm> v;
  uint64_t s = seed;
  for (long b = 0; b * 16 < iters; b++) {
    Arm blk[16];
    memcpy(blk, BLOCK, sizeof(blk));
    for (int k = 15; k > 0; k--) std::swap(blk[k], blk[splitmix(&s) % (uint64_t)(k + 1)]);
    for (int k = 0; k < 16 && (long)v.size() < iters; k++) v.push_back(blk[k]);
  }
  return v;
}
static double pct(std::vector<double> v, double p) {
  if (v.empty()) return -1;
  std::sort(v.begin(), v.end());
  return v[(size_t)(p * (v.size() - 1) + 0.5)];
}

static int runHog(int argc, char** argv) {
  if (argc < 5) setupFail("hog <secs> <stopfile>");
  const double secs = atof(argv[3]);
  const char* stop = argv[4];
  CK(cudaSetDevice(g_dev));
  const size_t n = (size_t)(256u << 20) / sizeof(float4);
  float4 *a = nullptr, *b = nullptr;
  CK(cudaMalloc(&a, n * sizeof(float4)));
  CK(cudaMalloc(&b, n * sizeof(float4)));
  CK(cudaMemset(a, 1, n * sizeof(float4)));
  const double t0 = nowUs();
  long rounds = 0;
  struct stat sb;
  while ((nowUs() - t0) / 1e6 < secs && stat(stop, &sb) != 0) {
    for (int k = 0; k < 8; k++) hogKernel<<<240, 256>>>(rounds & 1 ? b : a, rounds & 1 ? a : b, n);
    CK(cudaDeviceSynchronize());
    rounds++;
  }
  kvf("role=hog rounds=%ld bytes_per_round=%zu run_s=%.2f stopped_by=%s result=HOG_DONE exit=0\n", rounds,
      (size_t)8 * 2 * n * sizeof(float4), (nowUs() - t0) / 1e6, stat(stop, &sb) == 0 ? "file" : "bound");
  return 0;
}

int main(int argc, char** argv) {
  if (argc < 3) {
    fprintf(stderr, "usage: %s <out_kv> resp|writer <ib_dev> <gid_index> <ro|so> <iters> <ctl> | hog <secs> <stopfile>\n",
            argv[0]);
    return 2;
  }
  g_kv = fopen(argv[1], "w");
  if (!g_kv) return 2;
  const std::string role = argv[2];
  g_dev = getenv("RS_CUDA_DEV") ? atoi(getenv("RS_CUDA_DEV")) : 0;
  const int wdS = getenv("RS_WATCHDOG_S") ? atoi(getenv("RS_WATCHDOG_S")) : 300;
  std::thread([wdS]() {
    std::this_thread::sleep_for(std::chrono::seconds(wdS));
    static const char m[] = "WATCHDOG: rs_drain_test exceeded its bound; exiting 7\n";
    ssize_t k = write(2, m, sizeof(m) - 1);
    (void)k;
    if (g_kv) {
      fprintf(g_kv, "watchdog=1 exit=7\n");
      fflush(g_kv);
    }
    _exit(7);
  }).detach();
  if (role == "hog") return runHog(argc, argv);
  if (argc < 8) setupFail("usage");
  const char* dev = argv[3];
  g_gid = atoi(argv[4]);
  const std::string order = argv[5];
  const long iters = atol(argv[6]);
  const char* ctl = argv[7];
  if (role != "resp" && role != "writer") setupFail("role");
  if (order != "ro" && order != "so") setupFail("order");
  if (iters < 16 || iters > 100000 || iters % 16) setupFail("iters must be a multiple of 16 in 16..100000");
  const double cellS = getenv("RS_CELL_S") ? atof(getenv("RS_CELL_S")) : iters / 100.0 + 60.0;
  const uint64_t seed = getenv("RS_SEED") ? strtoull(getenv("RS_SEED"), nullptr, 0) : 0x5253ull;
  if (!rmsnSelfTest()) setupFail("rmsn modulo-2^24 self-test");
  L = makeLayout();
  const bool isResp = role == "resp";
  CK(cudaSetDevice(g_dev));
  CK(cudaFree(nullptr));
  cudaDeviceProp prop;
  CK(cudaGetDeviceProperties(&prop, g_dev));
  for (char* c = prop.name; *c; c++)
    if (*c == ' ') *c = '_';
  CUdevice cdev;
  CU(cuDeviceGet(&cdev, g_dev));
  int aOrder = -1, aFlush = -1, aGdr = -1;
  CU(cuDeviceGetAttribute(&aOrder, CU_DEVICE_ATTRIBUTE_GPU_DIRECT_RDMA_WRITES_ORDERING, cdev));
  CU(cuDeviceGetAttribute(&aFlush, CU_DEVICE_ATTRIBUTE_GPU_DIRECT_RDMA_FLUSH_WRITES_OPTIONS, cdev));
  CU(cuDeviceGetAttribute(&aGdr, CU_DEVICE_ATTRIBUTE_GPU_DIRECT_RDMA_SUPPORTED, cdev));
  kvf("name=%s cc=%d.%d gdr_supported=%d gdr_writes_ordering=%d gdr_flush_options=%d rmsn_selftest=ok\n", prop.name,
      prop.major, prop.minor, aGdr, aOrder, aFlush);
  kvf("role=%s ib_dev=%s order=%s iters=%ld window_bytes=%zu last_msg_bytes=%zu writes_per_iter=%d seed=%#lx\n",
      role.c_str(), dev, order.c_str(), iters, L.total, L.len[NW - 1], NW, (unsigned long)seed);
  int nd = 0;
  ibv_device** list = ibv_get_device_list(&nd);
  ibv_context* ctx = nullptr;
  for (int i = 0; i < nd && !ctx; i++) {
    if (strcmp(ibv_get_device_name(list[i]), dev) != 0) continue;
    mlx5dv_context_attr a;
    memset(&a, 0, sizeof(a));
    a.flags = MLX5DV_CONTEXT_FLAGS_DEVX;
    ctx = mlx5dv_open_device(list[i], &a);
  }
  ibv_free_device_list(list);
  if (!ctx) setupFail("cannot open the HCA with DEVX");
  if (ibv_query_port(ctx, 1, &g_pa) != 0) setupFail("ibv_query_port");
  ibv_gid gid;
  if (ibv_query_gid(ctx, 1, g_gid, &gid) != 0) setupFail("ibv_query_gid");
  memcpy(g_myGid, gid.raw, 16);
  kvf("link=%s gid_index=%d mtu=%d traffic_class=0 hca_ro_write_cap=%d qp_ordering=ibta_default\n",
      g_pa.link_layer == IBV_LINK_LAYER_ETHERNET ? "eth" : "ib", g_gid, (int)g_pa.active_mtu, hcaRoWrite(ctx));
  ibv_pd* pd = ibv_alloc_pd(ctx);
  ibv_cq* cq = ibv_create_cq(ctx, 256, nullptr, nullptr, 0);
  if (!pd || !cq) setupFail("PD/CQ");
  Resp r;
  memset(&r, 0, sizeof(r));
  // writer state
  ibv_qp* wqp = nullptr;
  ibv_mr *srcMr = nullptr, *atoMr = nullptr;
  void* src = nullptr;
  uint64_t* ato = nullptr;
  cudaStream_t wst = nullptr;
  if (isResp) {
    respSetup(r, ctx, pd, cq, order == "ro");
    kvf("mr=dmabuf alloc=cumem_gdr window_mr_relaxed=%d signal_mr_relaxed=0 fence_mr_relaxed=0 fence_target=other_alloc\n",
        order == "ro" ? 1 : 0);
  } else {
    size_t srcBytes = 0;
    src = cuMemAllocRdma(L.total, &srcBytes);
    srcMr = regDmabuf(pd, src, srcBytes, IBV_ACCESS_LOCAL_WRITE | IBV_ACCESS_REMOTE_READ | IBV_ACCESS_REMOTE_WRITE);
    if (posix_memalign((void**)&ato, 4096, 4096) != 0) setupFail("atomic result buffer");
    atoMr = ibv_reg_mr(pd, ato, 4096, IBV_ACCESS_LOCAL_WRITE);
    wqp = makeQp(pd, cq, 64);
    if (!srcMr || !atoMr || !wqp) setupFail("writer QP or MRs");
    CK(cudaStreamCreateWithFlags(&wst, cudaStreamNonBlocking));
    kvf("mr=dmabuf alloc=cumem_gdr source=gpu\n");
  }
  ctlOpen(ctl);
  struct Hello {
    uint32_t qpn, iters, order, nw, winRkey, sigRkey, mtu, lastKb;
    uint8_t gid[16];
    uint64_t total;
  } me, peer;
  memset(&me, 0, sizeof(me));
  me.qpn = isResp ? r.qp->qp_num : wqp->qp_num;
  me.iters = (uint32_t)iters;
  me.order = order == "ro" ? 1 : 2;
  me.nw = NW;
  me.winRkey = isResp ? r.winMr->rkey : 0;
  me.sigRkey = isResp ? r.sigMr->rkey : 0;
  memcpy(me.gid, g_myGid, 16);
  me.total = L.total;
  me.mtu = (uint32_t)g_pa.active_mtu;
  me.lastKb = (uint32_t)(L.len[NW - 1] >> 10);
  if (!sendAll(g_ctl, &me, sizeof(me)) || !recvAll(g_ctl, &peer, sizeof(peer), 10000)) setupFail("hello exchange");
  if (peer.iters != me.iters || peer.order != me.order || peer.nw != me.nw || peer.total != me.total || peer.lastKb != me.lastKb)
    setupFail("the two sides disagree on iters, order or layout");
  g_pathMtu = (int)std::min(me.mtu, peer.mtu);
  kvf("path_mtu=%d peer_mtu=%u\n", g_pathMtu, peer.mtu);
  if (!connectQp(isResp ? r.qp : wqp, peer.qpn, g_gid, peer.gid, g_pathMtu)) setupFail("connect to the peer");
  {
    Msg x = {M_READY, 0, 0, 0, 0}, y;
    if (!sendAll(g_ctl, &x, sizeof(x)) || !recvAll(g_ctl, &y, sizeof(y), 10000) || y.type != M_READY)
      setupFail("ready exchange");
  }
  const double tRun0 = nowUs();
  if (!isResp) {  // ---- writer loop: GO -> fill -> post -> PAUSED -> own completion -> DONE ----
    uint64_t m = 0;
    long n = 0;
    char err[192];
    while (true) {
      const Msg go = ctlRecv(30000);
      if (go.type == M_END) break;
      if (go.type != M_GO) nicFail("unexpected control message (writer)");
      fillKernel<<<120, 256, 0, wst>>>((unsigned long long*)src, L.total / 8, go.iter + 1);
      CK(cudaGetLastError());
      CK(cudaStreamSynchronize(wst));
      ibv_sge sg[NW + 1];
      ibv_send_wr wr[NW + 1], *bad = nullptr;
      memset(wr, 0, sizeof(wr));
      int k = 0;
      auto addWrite = [&](int idx) {
        sg[k].addr = (uint64_t)L.off[idx];  // the source MR is registered with iova 0: local addresses are offsets
        sg[k].length = (uint32_t)L.len[idx];
        sg[k].lkey = srcMr->lkey;
        wr[k].wr_id = g_wrId++;
        wr[k].sg_list = &sg[k];
        wr[k].num_sge = 1;
        wr[k].opcode = IBV_WR_RDMA_WRITE;
        wr[k].wr.rdma.remote_addr = L.off[idx];
        wr[k].wr.rdma.rkey = peer.winRkey;
        k++;
      };
      auto addAtomic = [&]() {
        sg[k].addr = (uint64_t)(uintptr_t)ato;
        sg[k].length = 8;
        sg[k].lkey = atoMr->lkey;
        wr[k].wr_id = g_wrId++;
        wr[k].sg_list = &sg[k];
        wr[k].num_sge = 1;
        wr[k].opcode = IBV_WR_ATOMIC_FETCH_AND_ADD;
        wr[k].wr.atomic.remote_addr = 0;
        wr[k].wr.atomic.rkey = peer.sigRkey;
        wr[k].wr.atomic.compare_add = 1;
        k++;
      };
      for (int i = 0; i < NW - 1; i++) addWrite(i);
      if (go.tail == T_AW) addAtomic();
      addWrite(NW - 1);
      if (go.tail == T_WA) addAtomic();
      for (int i = 0; i < k - 1; i++) wr[i].next = &wr[i + 1];
      wr[k - 1].send_flags = IBV_SEND_SIGNALED;  // RC completes in order: the last completion covers all
      if (ibv_post_send(wqp, wr, &bad) != 0) nicFail("writer post");
      m += (uint64_t)k;
      ctlSend(M_PAUSED, go.iter, go.tail, m);
      if (!cqWait(cq, wr[k - 1].wr_id, 2000, err, sizeof(err))) nicFail(err);
      const Msg d = ctlRecv(30000);
      if (d.type != M_DONE || d.iter != go.iter) nicFail("control message out of order (writer)");
      n++;
    }
    kvf("iterations=%ld messages=%lu run_s=%.2f result=WRITER_DONE exit=0\n", n, (unsigned long)m,
        (nowUs() - tRun0) / 1e6);
    return 0;
  }
  // ---- responder loop ----
  {
    uint32_t st = 0;
    if (!queryRmsnRaw(r.qp, &r.rmsn0, &st)) setupFail("QUERY_QP (DEVX) refused");
    g_queryQp++;
    kvf("rmsn0=%u qp_state=%u\n", r.rmsn0, st);
    const uint64_t pat = 0x7273647261696e32ull;  // self-check: both loopback READ targets
    CK(cudaMemcpy(r.fence, &pat, 8, cudaMemcpyHostToDevice));
    CK(cudaMemcpy((uint8_t*)r.win + L.total + 64, &pat, 8, cudaMemcpyHostToDevice));
    for (int same = 0; same < 2; same++) {
      memset(r.stage, 0, 8);
      readFence(r, same == 1, false);
      uint64_t back = 0;
      memcpy(&back, r.stage, 8);
      if (back != pat) setupFail("loopback READ self-check");
    }
  }
  const std::vector<Arm> sched = schedule(iters, seed);
  const long probeIters = iters / 16;
  uint64_t m = 0;
  bool incomplete = false;
  long done = 0;
  for (long i = 0; i < iters + probeIters; i++) {
    if ((nowUs() - tRun0) / 1e6 > cellS) {
      incomplete = true;
      break;
    }
    const bool probe = i >= iters;
    const Arm a = probe ? Arm{P_PROBE, T_W} : sched[(size_t)i];
    const uint32_t it = (uint32_t)i;
    // prepare: poison the snapshot; the probe kernel starts before GO
    CK(cudaMemsetAsync(r.snap, 0xff, L.total, r.st));
    CK(cudaStreamSynchronize(r.st));
    Res z;
    memset(&z, 0, sizeof(z));
    z.firstCorruptWord = 0xffffffffu;
    if (probe) {
      int zero = 0;
      CK(cudaMemcpyAsync(r.res, &z, sizeof(z), cudaMemcpyHostToDevice, r.pst));
      CK(cudaMemcpyAsync(r.timedOut, &zero, sizeof(int), cudaMemcpyHostToDevice, r.pst));
      probeKernel<<<1, 1024, 0, r.pst>>>((const unsigned long long*)r.win, L.total / 8, it + 1, r.res, r.timedOut);
      CK(cudaGetLastError());
    }
    const double tGo = nowUs();
    ctlSend(M_GO, it, (uint32_t)a.tail, 0);
    const Msg x = ctlRecv(10000);
    const double tp = nowUs();
    goPausedUs.push_back(tp - tGo);
    if (x.type != M_PAUSED || x.iter != it) nicFail("control message out of order (responder)");
    m += (uint64_t)msgsOf(a.tail);
    if (x.m != m) nicFail("PAUSED count differs from the expected M");
    if (a.tail != T_W) g_atomics++;
    bool sawBelow = false;
    long polls = 0;
    switch (a.path) {
      case P_EARLY:
        snapshotCheck(r, P_EARLY, a.tail, it, false);
        (void)waitRmsn(r, m, tp, &sawBelow, false);
        readFence(r, false, false);
        break;
      case P_BOUNDARY: {
        const long p = waitRmsn(r, m, tp, &sawBelow, true);
        if (p < 0) snapshotCheck(r, P_BOUNDARY, a.tail, it, false);
        else boundaryMissed++;
        (void)waitRmsn(r, m, nowUs(), &sawBelow, false);
        readFence(r, false, false);
        break;
      }
      default: {
        double reach = 0;
        polls = waitRmsn(r, m, tp, &sawBelow, false, &reach);
        reachUs.push_back(reach);
        pollsMax = std::max(pollsMax, polls);
        estReachUs = estReachUs == 0 ? reach : 0.8 * estReachUs + 0.2 * reach;
        if (a.path == P_FENCE) {
          readFence(r, false, true);
          snapshotCheck(r, P_FENCE, a.tail, it, true);
          if (a.tail != T_WA) {
            scoredN++;
            if (sawBelow) edgeSeen++;
          }
        } else if (a.path == P_FSAME) {
          readFence(r, true, false);
          snapshotCheck(r, P_FSAME, a.tail, it, false);
        } else if (a.path == P_NOFENCE) {
          snapshotCheck(r, P_NOFENCE, a.tail, it, false);
          readFence(r, false, false);
        } else if (a.path == P_CUFLUSH) {
          const double f0 = nowUs();
          const CUresult fr = cuFlushGPUDirectRDMAWrites(CU_FLUSH_GPU_DIRECT_RDMA_WRITES_TARGET_CURRENT_CTX,
                                                         CU_FLUSH_GPU_DIRECT_RDMA_WRITES_TO_OWNER);
          if (fr != CUDA_SUCCESS) {
            const char* n = nullptr;
            cuGetErrorName(fr, &n);
            kvf("cuflush_error=%s\n", n ? n : "?");
          } else {
            flushUs.push_back(nowUs() - f0);
            snapshotCheck(r, P_CUFLUSH, a.tail, it, false);
          }
          readFence(r, false, false);
        } else if (a.path == P_PROBE) {
          readFence(r, false, false);
          CK(cudaStreamSynchronize(r.pst));
          Res h;
          int to = 0;
          CK(cudaMemcpy(&h, r.res, sizeof(h), cudaMemcpyDeviceToHost));
          CK(cudaMemcpy(&to, r.timedOut, sizeof(int), cudaMemcpyDeviceToHost));
          Tally& t = T[P_PROBE][T_W];
          t.n++;
          if (to) probeTimeouts++;
          t.staleBefore += h.staleBefore;
          t.corrupt += h.corrupt;
          if (h.staleBefore) t.itersStaleBefore++;
          if (h.corrupt) t.itersCorrupt++;
          if (h.staleBefore || h.corrupt || to) t.itersBad++;
        }
        break;
      }
    }
    ctlSend(M_DONE, it, (uint32_t)a.tail, 0);
    done++;
  }
  ctlSend(M_END, (uint32_t)done, 0, 0);
  const double runS = (nowUs() - tRun0) / 1e6;
  for (int p = 0; p < NPATH; p++)
    for (int t = 0; t < 3; t++) {
      const Tally& x = T[p][t];
      if (x.n == 0) continue;
      kvf("%s_%s_n=%ld %s_%s_iters_bad=%ld %s_%s_iters_stale_before=%ld %s_%s_iters_stale_last=%ld "
          "%s_%s_iters_corrupt=%ld %s_%s_stale_before_words=%llu %s_%s_stale_last_words=%llu %s_%s_corrupt_words=%llu "
          "%s_%s_sig_late=%ld %s_%s_sig_bad=%ld\n",
          PATHN[p], TAILN[t], x.n, PATHN[p], TAILN[t], x.itersBad, PATHN[p], TAILN[t], x.itersStaleBefore, PATHN[p],
          TAILN[t], x.itersStaleLast, PATHN[p], TAILN[t], x.itersCorrupt, PATHN[p], TAILN[t], x.staleBefore, PATHN[p],
          TAILN[t], x.staleLast, PATHN[p], TAILN[t], x.corrupt, PATHN[p], TAILN[t], x.sigLate, PATHN[p], TAILN[t],
          x.sigBad);
    }
  for (int t = 0; t < 3; t++)
    if (TS[t].n)
      kvf("fencesm_%s_n=%ld fencesm_%s_iters_bad=%ld fencesm_%s_stale_words=%llu fencesm_%s_corrupt_words=%llu\n",
          TAILN[t], TS[t].n, TAILN[t], TS[t].itersBad, TAILN[t], TS[t].staleBefore + TS[t].staleLast, TAILN[t],
          TS[t].corrupt);
  std::string ff;
  for (long v : fenceFail) ff += (ff.empty() ? "" : ",") + std::to_string(v);
  kvf("reach_p50_us=%.1f reach_p99_us=%.1f reach_max_us=%.1f polls_max=%ld query_qp_total=%llu query_p50_us=%.1f "
      "query_p99_us=%.1f query_max_us=%.1f read_p50_us=%.1f read_max_us=%.1f cuflush_p50_us=%.1f boundary_missed=%ld "
      "probe_timeouts=%ld scored_n=%ld edge_seen=%ld iterations_done=%ld run_s=%.2f fence_fail_iters=%s go_paused_p50_us=%.1f\n",
      pct(reachUs, 0.5), pct(reachUs, 0.99), pct(reachUs, 1.0), pollsMax, g_queryQp, pct(g_qLat, 0.5),
      pct(g_qLat, 0.99), pct(g_qLat, 1.0), pct(readUs, 0.5), pct(readUs, 1.0), pct(flushUs, 0.5), boundaryMissed,
      probeTimeouts, scoredN, edgeSeen, done, runS, ff.empty() ? "none" : ff.c_str(), pct(goPausedUs, 0.5));
  const Tally &fw = T[P_FENCE][T_W], &faw = T[P_FENCE][T_AW], &ea = T[P_EARLY][T_W], &bd = T[P_BOUNDARY][T_W];
  const bool fenceClean = fw.itersBad == 0 && faw.itersBad == 0;
  const bool valid = ea.itersStale >= 10 && ea.corrupt == 0 && bd.itersStaleLast >= 10 &&
                     scoredN > 0 && 2 * edgeSeen >= scoredN;
  const char* result = !fenceClean ? "FENCE_FAIL" : incomplete ? "INCOMPLETE" : valid ? "PASS" : "INCONCLUSIVE";
  const int ex = !fenceClean ? 1 : incomplete ? 5 : valid ? 0 : 4;
  kvf("fence_clean=%d valid=%d early_iters_stale=%ld boundary_iters_stale_last=%ld edge_fraction=%.3f result=%s exit=%d\n",
      fenceClean ? 1 : 0, valid ? 1 : 0, ea.itersStale, bd.itersStaleLast,
      scoredN ? (double)edgeSeen / scoredN : 0.0, result, ex);
  fclose(g_kv);
  return ex;
}
