// mirror_feas.cu - gin-mirror feasibility checks 1, 3 and 4 (EXPERIMENT.md 9.8; DRAFT stage, never scored). No NCCL.
//
// vis and store run as two processes (the runner places them on rain and sunny; a TCP control channel on the management
// address, nonce-verified as ../../restore/feas/rs_drain_test.cu); bar1 runs as three processes on one GPU. Every QP, CQ and
// MR is created once per process. GPU memory: cuMem with gpuDirectRDMACapable, dmabuf MR at iova 0 (as GIN windows). Host
// memory: page-aligned, ibv_reg_mr_iova2 at iova 0 without IBV_ACCESS_RELAXED_ORDERING (the pool and store of 9.3, 9.4), in
// the same PD as every other MR and QP of that process.
//   vis    check 1. writer, iteration i, on GO(i, n): a kernel writes ((i + 1) << 32 | word index) into n bytes of its GPU
//          buffer, ONE RC RDMA WRITE of n bytes to offset 0 of the host MR (MF_SIGNAL=flag: then an 8-byte WRITE of i + 1 to
//          the flag word behind the data, same QP), POSTED(i, m) (m: request messages so far), its own completion, DONE(i).
//          host, on POSTED: waits until the responder's completion is observable (MF_SIGNAL=msn, default, the drain of 9.4
//          step 2: QUERY_QP of the responder QP until rmsn - rmsn0 == m mod 2^24, first query 0.9 x the running reach
//          estimate after POSTED, then every max(20 us, est / 10); flag: the CPU sees the flag word == i + 1), then ONE path
//          (a seeded permutation of the three in every block of 3 iterations):
//            a1  the CPU reads the n bytes right away (last word first)
//            a2  one 8-byte RDMA READ of a pool word (behind the data, same MR) on the loopback QP pair of this PD, then
//                the CPU read (the READ fence of 9.4 step 2)
//            a3  one RDMA READ of the n bytes on a third QP (a second loopback pair, same PD) into a staging host MR
//                poisoned before GO, then the CPU reads the staging copy (the FETCH path of 9.4)
//          A wrong word is stale (an earlier iteration's value of that word) or corrupt; an iteration is bad if a word is
//          wrong. Every iteration ends with the READ fence before DONE; a bad one is read again after one more fence
//          (<path>_after_fence_bad). n: 4k | 256k | 2m | rand (seeded, 4 KiB - 2 MiB in 4 KiB steps).
//   store  check 3. src: a GPU region of MF_STORE_MIB (30) is RDMA-WRITTEN (one WRITE) to a host MR of host 2 x reps times
//          in alternating blocks of 10: no other traffic; a second QP of src sends bursts of MF_BG_K (8) WRITEs of MF_BG_MIB
//          (2) from the same region to a GPU buffer of host. Time: post to the requester's completion. Then src RDMA-READs a
//          host MR of MF_READ_MIB (150) of host into its own host buffer reps times, in READs of MF_READ_CHUNK_MIB (30).
//          theta = MF_READ_MIB / the READ p50. Data checks (information): host reads its store MR after the WRITE phase,
//          src checks the first and the last READ.
//   bar1   check 4. One of three processes on one GPU: CUDA context and cuMem windows of MF_BAR1_MIB (6,24) MiB (stage ctx);
//          on file <ctl_dir>/go_pd1 each window is registered by dmabuf in one PD (stage pd1); on go_pd2, if pd2 = 1, again
//          in a second PD (stage pd2; pd2_skipped if the file stop comes first); on stop all MRs are deregistered (stage
//          end). Each stage prints "MFSTAGE <tag> <stage> ok=<0|1>"; the runner reads nvidia-smi BAR1 in between.
// usage: mirror_feas <out_kv> vis <writer|host> <ib_dev> <gid_index> <4k|256k|2m|rand> <iters> <ctl>
//        mirror_feas <out_kv> store <src|host> <ib_dev> <gid_index> <reps (multiple of 10)> <ctl>
//        mirror_feas <out_kv> bar1 <tag> <ib_dev> <ctl_dir> <pd2 0|1>        <ctl>: listen:<port> | connect:<ip>:<port>
// env: MF_RDV_NONCE (16 hex; vis, store), MF_WATCHDOG_S (300: exit 7), MF_RUN_S (vis host: iters / 200 + 60, then INCOMPLETE),
//      MF_CUDA_DEV (0), MF_SEED (0x4d46), MF_SIGNAL (msn | flag; both sides), MF_QUERY_BUDGET (vis host, msn: 30000; the loop
//      ends at an iteration boundary at that many QUERY_QP, budget_stop=1; hard cap budget + 400, exit 3), MF_TIMING_FILE
//      (store src: every timed operation), MF_STORE_MIB, MF_READ_MIB, MF_READ_CHUNK_MIB, MF_BG_MIB, MF_BG_K (store; both
//      sides agree), MF_BAR1_MIB, MF_STAGE_WAIT_S (bar1: 120 per stage file)
// exit: 0 PASS or done; 1 FAIL (vis: a2 or a3 saw a wrong word); 2 usage or setup; 3 NIC, QUERY_QP or control error;
//       5 INCOMPLETE; 6 CUDA error; 7 watchdog; 8 bar1: a registration failed (a reading, not a tool error)
#include <cuda.h>
#include <cuda_runtime.h>
#include <infiniband/verbs.h>
#include <infiniband/mlx5dv.h>
#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <sys/resource.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <unistd.h>
#include <algorithm>
#include <atomic>
#include <cerrno>
#include <chrono>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <functional>
#include <string>
#include <thread>
#include <vector>
// mlx5 PRM layouts (QUERY_QP) from the DOCA GPUNetIO copy inside NCCL (read only; build_mf.sh -I). Last: it defines u8.
#include "mlx5_ifc.h"

static FILE* g_kv = nullptr;
static int g_ctl = -1, g_dev = 0;
static std::atomic<long> g_done{-1};                 // iterations or blocks done (-1: the loop has not started)
static std::atomic<unsigned long long> g_queryQp{0};  // QUERY_QP issued by this process
static double g_t0 = 0;
static void kvf(const char* fmt, ...) __attribute__((format(printf, 1, 2)));
static void kvf(const char* fmt, ...) {
  if (g_kv == nullptr) return;
  va_list ap;
  va_start(ap, fmt);
  vfprintf(g_kv, fmt, ap);
  va_end(ap);
  fflush(g_kv);
}
static void progressKv() {
  if (g_done.load() >= 0) kvf("progress_done=%ld progress_query_qp=%llu\n", g_done.load(), g_queryQp.load());
}
[[noreturn]] static void cudaFail(const char* name, int line) {
  fprintf(stderr, "CUDA error %s at line %d\n", name, line);
  progressKv();
  kvf("cuda_error=%s line=%d result=ERROR exit=6\n", name, line);
  _exit(6);
}
#define CK(c) do { cudaError_t e_ = (c); if (e_ != cudaSuccess) cudaFail(cudaGetErrorName(e_), __LINE__); } while (0)
#define CU(c)                                                                                \
  do {                                                                                       \
    CUresult r_ = (c);                                                                       \
    const char* n_ = "?";                                                                    \
    if (r_ != CUDA_SUCCESS) cuGetErrorName(r_, &n_), cudaFail(n_, __LINE__);                 \
  } while (0)
enum { M_GO = 1, M_POSTED = 2, M_DONE = 3, M_END = 4, M_ERR = 5, M_READY = 6, M_PHASE = 7 };
struct Msg { uint32_t type, iter, a, b; uint64_t m; };
[[noreturn]] static void failExit(const char* key, const char* what, int code) {
  const int e = errno;
  fprintf(stderr, "%s: %s (errno %d)\n", key, what, e);
  progressKv();
  kvf("%s=\"%s\" errno=%d result=ERROR exit=%d\n", key, what, e, code);
  Msg x = {M_ERR, 0, 0, 0, 0};  // tell the other side (best effort, one whole Msg): it exits instead of waiting
  if (g_ctl >= 0 && code == 3) (void)send(g_ctl, &x, sizeof(x), MSG_NOSIGNAL);
  _exit(code);
}
[[noreturn]] static void setupFail(const char* what) { failExit("setup_error", what, 2); }
[[noreturn]] static void nicFail(const char* what) { failExit("nic_error", what, 3); }
static double nowUs() {
  struct timespec t;
  clock_gettime(CLOCK_MONOTONIC, &t);
  return t.tv_sec * 1e6 + t.tv_nsec * 1e-3;
}
static long envL(const char* n, long d) {
  const char* s = getenv(n);
  return (s != nullptr && *s != 0) ? strtol(s, nullptr, 0) : d;
}
static double pct(std::vector<double> v, double p) {  // the rank rule of rs_drain_test (summ_mf.py uses the same)
  if (v.empty()) return -1;
  std::sort(v.begin(), v.end());
  return v[(size_t)(p * (v.size() - 1) + 0.5)];
}
static uint64_t splitmix(uint64_t* s) {
  uint64_t z = (*s += 0x9e3779b97f4a7c15ull);
  z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9ull;
  z = (z ^ (z >> 27)) * 0x94d049bb133111ebull;
  return z ^ (z >> 31);
}

// ---- GPU and host memory ----
__global__ void fillKernel(unsigned long long* buf, size_t nwords, unsigned int iter1) {
  for (size_t w = blockIdx.x * (size_t)blockDim.x + threadIdx.x; w < nwords; w += (size_t)gridDim.x * blockDim.x)
    buf[w] = ((unsigned long long)iter1 << 32) | (unsigned int)w;
}
static void cudaInit() {
  CK(cudaSetDevice(g_dev));
  CK(cudaFree(nullptr));
  cudaDeviceProp prop;
  CK(cudaGetDeviceProperties(&prop, g_dev));
  for (char* c = prop.name; *c; c++)
    if (*c == ' ') *c = '_';
  CUdevice cdev;
  CU(cuDeviceGet(&cdev, g_dev));
  int aOrder = -1, aFlush = -1, aGdr = -1, drv = 0;
  CU(cuDeviceGetAttribute(&aOrder, CU_DEVICE_ATTRIBUTE_GPU_DIRECT_RDMA_WRITES_ORDERING, cdev));
  CU(cuDeviceGetAttribute(&aFlush, CU_DEVICE_ATTRIBUTE_GPU_DIRECT_RDMA_FLUSH_WRITES_OPTIONS, cdev));
  CU(cuDeviceGetAttribute(&aGdr, CU_DEVICE_ATTRIBUTE_GPU_DIRECT_RDMA_SUPPORTED, cdev));
  CK(cudaDriverGetVersion(&drv));
  kvf("gpu=%s cc=%d.%d cuda_dev=%d cuda_driver=%d gdr_supported=%d gdr_writes_ordering=%d gdr_flush_options=%d\n", prop.name,
      prop.major, prop.minor, g_dev, drv, aGdr, aOrder, aFlush);
}
// as ncclMemAlloc: pinned device memory, gpuDirectRDMACapable, recommended granularity
static void* cuMemAllocRdma(size_t want, size_t* outSize) {
  CUmemAllocationProp prop;
  memset(&prop, 0, sizeof(prop));
  prop.type = CU_MEM_ALLOCATION_TYPE_PINNED, prop.location.type = CU_MEM_LOCATION_TYPE_DEVICE, prop.location.id = g_dev;
  prop.requestedHandleTypes = CU_MEM_HANDLE_TYPE_POSIX_FILE_DESCRIPTOR, prop.allocFlags.gpuDirectRDMACapable = 1;
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
  acc.location.type = CU_MEM_LOCATION_TYPE_DEVICE, acc.location.id = g_dev, acc.flags = CU_MEM_ACCESS_FLAGS_PROT_READWRITE;
  CU(cuMemSetAccess(p, size, &acc, 1));
  *outSize = size;
  return (void*)p;
}
static ibv_mr* regDmabuf(ibv_pd* pd, void* base, size_t n, int access) {
  int fd = -1;
  if (cuMemGetHandleForAddressRange((void*)&fd, (CUdeviceptr)base, n, CU_MEM_RANGE_HANDLE_TYPE_DMA_BUF_FD, 0) != CUDA_SUCCESS ||
      fd < 0)
    return nullptr;
  ibv_mr* mr = ibv_reg_dmabuf_mr(pd, 0, n, 0 /* iova 0: remote addresses are offsets, as GIN */, fd, access);
  const int e = errno;
  close(fd);
  errno = e;
  return mr;
}
static const int ACC_WIN = IBV_ACCESS_LOCAL_WRITE | IBV_ACCESS_REMOTE_WRITE | IBV_ACCESS_REMOTE_READ | IBV_ACCESS_REMOTE_ATOMIC;
static const int ACC_POOL = IBV_ACCESS_LOCAL_WRITE | IBV_ACCESS_REMOTE_WRITE | IBV_ACCESS_REMOTE_READ;  // no RO (9.3)
static void* hostAlloc(size_t n) {
  void* p = nullptr;
  if (posix_memalign(&p, 4096, n) != 0 || p == nullptr) setupFail("host allocation");
  memset(p, 0, n);
  return p;
}
static ibv_mr* regPool(ibv_pd* pd, void* p, size_t n) { return ibv_reg_mr_iova2(pd, p, n, 0, ACC_POOL); }

// ---- verbs ----
static ibv_port_attr g_pa;
static int g_gid = 0, g_pathMtu = 0;
static uint8_t g_myGid[16];
static ibv_context* openDev(const char* dev, bool devx) {
  int nd = 0;
  ibv_device** list = ibv_get_device_list(&nd);
  ibv_context* ctx = nullptr;
  for (int i = 0; list != nullptr && i < nd && ctx == nullptr; i++) {
    if (strcmp(ibv_get_device_name(list[i]), dev) != 0) continue;
    mlx5dv_context_attr a;
    memset(&a, 0, sizeof(a));
    a.flags = MLX5DV_CONTEXT_FLAGS_DEVX;
    ctx = devx ? mlx5dv_open_device(list[i], &a) : ibv_open_device(list[i]);
  }
  if (list != nullptr) ibv_free_device_list(list);
  if (ctx == nullptr) setupFail(devx ? "cannot open the HCA with DEVX" : "cannot open the HCA");
  ibv_gid gid;
  if (ibv_query_port(ctx, 1, &g_pa) != 0 || ibv_query_gid(ctx, 1, g_gid, &gid) != 0) setupFail("ibv_query_port or _gid");
  memcpy(g_myGid, gid.raw, 16);
  kvf("ib_dev=%s link=%s gid_index=%d active_mtu=%d max_msg_sz=%u devx=%d\n", dev,
      g_pa.link_layer == IBV_LINK_LAYER_ETHERNET ? "eth" : "ib", g_gid, (int)g_pa.active_mtu, g_pa.max_msg_sz, devx ? 1 : 0);
  return ctx;
}
static ibv_qp* makeQp(ibv_pd* pd, ibv_cq* cq, int sendWr) {
  ibv_qp_init_attr a;
  memset(&a, 0, sizeof(a));
  a.send_cq = a.recv_cq = cq;
  a.qp_type = IBV_QPT_RC;
  a.cap.max_send_wr = sendWr;
  a.cap.max_recv_wr = a.cap.max_send_sge = a.cap.max_recv_sge = 1;
  ibv_qp* q = ibv_create_qp(pd, &a);
  if (q == nullptr) setupFail("ibv_create_qp");
  return q;
}
static bool connectQp(ibv_qp* q, uint32_t dest, const uint8_t* dgid, int mtu) {
  ibv_qp_attr a;
  memset(&a, 0, sizeof(a));
  a.qp_state = IBV_QPS_INIT, a.port_num = 1;
  a.qp_access_flags = IBV_ACCESS_REMOTE_READ | IBV_ACCESS_REMOTE_WRITE | IBV_ACCESS_REMOTE_ATOMIC | IBV_ACCESS_LOCAL_WRITE;
  if (ibv_modify_qp(q, &a, IBV_QP_STATE | IBV_QP_PKEY_INDEX | IBV_QP_PORT | IBV_QP_ACCESS_FLAGS) != 0) return false;
  memset(&a, 0, sizeof(a));
  a.qp_state = IBV_QPS_RTR, a.path_mtu = (enum ibv_mtu)mtu, a.dest_qp_num = dest;
  a.max_dest_rd_atomic = 16, a.min_rnr_timer = 12;
  a.ah_attr.port_num = a.ah_attr.is_global = 1;
  memcpy(a.ah_attr.grh.dgid.raw, dgid, 16);
  a.ah_attr.grh.sgid_index = (uint8_t)g_gid, a.ah_attr.grh.hop_limit = 64;  // traffic class 0: NCCL_IB_TC default, as GIN
  if (ibv_modify_qp(q, &a, IBV_QP_STATE | IBV_QP_AV | IBV_QP_PATH_MTU | IBV_QP_DEST_QPN | IBV_QP_RQ_PSN |
                             IBV_QP_MAX_DEST_RD_ATOMIC | IBV_QP_MIN_RNR_TIMER) != 0)
    return false;
  memset(&a, 0, sizeof(a));
  a.qp_state = IBV_QPS_RTS, a.timeout = 14;  // NCCL_IB_TIMEOUT=14, as the restore runs
  a.retry_cnt = a.rnr_retry = 7, a.max_rd_atomic = 16;
  return ibv_modify_qp(q, &a, IBV_QP_STATE | IBV_QP_TIMEOUT | IBV_QP_RETRY_CNT | IBV_QP_RNR_RETRY | IBV_QP_SQ_PSN |
                                  IBV_QP_MAX_QP_RD_ATOMIC) == 0;
}
static void loopPair(ibv_qp* a, ibv_qp* b) {
  if (!connectQp(a, b->qp_num, g_myGid, (int)g_pa.active_mtu) || !connectQp(b, a->qp_num, g_myGid, (int)g_pa.active_mtu))
    setupFail("loopback connect");
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
// a chain of one-SGE work requests on q, the last one signaled (RC completes in order); returns its wr_id, 0 on failure
struct Op { uint64_t laddr; uint32_t lkey, len; uint64_t raddr; uint32_t rkey; };
static std::atomic<uint64_t> g_wrId{1};
static uint64_t postChain(ibv_qp* q, ibv_wr_opcode op, const Op* ops, int n) {
  ibv_sge sg[32];
  ibv_send_wr wr[32], *bad = nullptr;
  if (n < 1 || n > 32) return 0;
  memset(wr, 0, sizeof(wr));
  for (int k = 0; k < n; k++) {
    sg[k].addr = ops[k].laddr, sg[k].length = ops[k].len, sg[k].lkey = ops[k].lkey;
    wr[k].wr_id = g_wrId.fetch_add(1), wr[k].sg_list = &sg[k], wr[k].num_sge = 1, wr[k].opcode = op;
    wr[k].wr.rdma.remote_addr = ops[k].raddr, wr[k].wr.rdma.rkey = ops[k].rkey;
    wr[k].next = k + 1 < n ? &wr[k + 1] : nullptr;
  }
  wr[n - 1].send_flags = IBV_SEND_SIGNALED;
  return ibv_post_send(q, wr, &bad) == 0 ? wr[n - 1].wr_id : 0;
}
static void runChain(ibv_qp* q, ibv_cq* cq, ibv_wr_opcode op, const Op* ops, int n, double ms, const char* what) {
  const uint64_t id = postChain(q, op, ops, n);
  if (id == 0) nicFail(what);
  char err[192];
  if (!cqWait(cq, id, ms, err, sizeof(err))) nicFail(err);
}

// ---- QUERY_QP (rmsn) ----
static const uint32_t MASK24 = 0xffffffu;
static bool queryRmsnRaw(ibv_qp* q, uint32_t* rmsn, uint32_t* state) {
  uint32_t in[DEVX_ST_SZ_DW(query_qp_in)], out[DEVX_ST_SZ_DW(query_qp_out)];
  memset(in, 0, sizeof(in)), memset(out, 0, sizeof(out));
  DEVX_SET(query_qp_in, in, opcode, MLX5_CMD_OP_QUERY_QP);
  DEVX_SET(query_qp_in, in, qpn, q->qp_num);
  if (mlx5dv_devx_qp_query(q, in, sizeof(in), out, sizeof(out)) != 0) return false;
  const void* qpc = DEVX_ADDR_OF(query_qp_out, out, qpc);
  *rmsn = DEVX_GET(qpc, qpc, rmsn), *state = DEVX_GET(qpc, qpc, state);
  return true;
}
static bool rmsnSelfTest() {  // the modulo-2^24 difference across the wrap (as rs_drain_test)
  const uint32_t c[5][3] = {{0, 31, 31}, {0xfffff0u, 0xfu, 0x1fu}, {0xffffffu, 0, 1}, {5, 5, 0},
                            {0x800000u, 0x7fffffu, MASK24}};
  for (auto& x : c)
    if (((x[1] - x[0]) & MASK24) != x[2]) return false;
  return true;
}

// ---- the control channel (TCP, nonce-verified: the listener greets, the other side sends nothing before checking) ----
static const char kMagic[8] = {'M', 'I', 'R', 'F', 'E', 'A', 'S', '1'};
struct Greet { char magic[8]; uint64_t nonce; };
static bool sendAll(int fd, const void* p, size_t n) {
  for (const char* c = (const char*)p; n;) {
    const ssize_t k = send(fd, c, n, MSG_NOSIGNAL);
    if (k < 0 && errno == EINTR) continue;
    if (k <= 0) return false;
    c += k, n -= (size_t)k;
  }
  return true;
}
static bool recvAll(int fd, void* p, size_t n, int ms) {
  const double t0 = nowUs();
  for (char* c = (char*)p; n;) {
    struct pollfd pf = {fd, POLLIN, 0};
    const int left = ms - (int)((nowUs() - t0) / 1e3);
    if (left <= 0 || poll(&pf, 1, left) != 1) return false;
    const ssize_t k = recv(fd, c, n, 0);
    if (k < 0 && errno == EINTR) continue;
    if (k <= 0) return false;
    c += k, n -= (size_t)k;
  }
  return true;
}
static bool greetOk(const Greet& g, uint64_t nonce) { return memcmp(g.magic, kMagic, 8) == 0 && g.nonce == nonce; }
static void ctlOpen(const char* spec) {
  const char* s = getenv("MF_RDV_NONCE");
  if (s == nullptr || strlen(s) != 16) setupFail("MF_RDV_NONCE (16 hex digits) is required");
  Greet me, an;
  memcpy(me.magic, kMagic, 8);
  me.nonce = strtoull(s, nullptr, 16);
  int one = 1, other = 0;
  sockaddr_in a{};
  a.sin_family = AF_INET;
  const double t0 = nowUs();
  const bool lis = strncmp(spec, "listen:", 7) == 0;
  if (lis) {
    const int ls = socket(AF_INET, SOCK_STREAM, 0);
    setsockopt(ls, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
    a.sin_addr.s_addr = INADDR_ANY;
    a.sin_port = htons((uint16_t)atoi(spec + 7));
    if (bind(ls, (sockaddr*)&a, sizeof(a)) != 0 || listen(ls, 4) != 0) setupFail("control listen");
    while (g_ctl < 0) {
      struct pollfd pf = {ls, POLLIN, 0};
      if (nowUs() - t0 > 60e6) setupFail("no verified control connection within 60 s");
      if (poll(&pf, 1, 1000) <= 0) continue;
      const int c = accept(ls, nullptr, nullptr);
      if (c < 0) continue;
      if (sendAll(c, &me, sizeof(me)) && recvAll(c, &an, sizeof(an), 2000) && greetOk(an, me.nonce)) g_ctl = c;
      else other++, close(c);
    }
    close(ls);
  } else {
    char host[64];
    snprintf(host, sizeof(host), "%s", strncmp(spec, "connect:", 8) == 0 ? spec + 8 : "");
    char* colon = strrchr(host, ':');
    if (colon == nullptr) setupFail("control spec: listen:<port> or connect:<ip>:<port>");
    *colon = 0;
    a.sin_port = htons((uint16_t)atoi(colon + 1));
    if (inet_pton(AF_INET, host, &a.sin_addr) != 1) setupFail("bad control address");
    while (g_ctl < 0) {
      if (nowUs() - t0 > 60e6) setupFail("no verified control connection within 60 s");
      const int c = socket(AF_INET, SOCK_STREAM, 0);
      if (connect(c, (sockaddr*)&a, sizeof(a)) == 0) {
        if (recvAll(c, &an, sizeof(an), 2000) && greetOk(an, me.nonce) && sendAll(c, &me, sizeof(me))) {
          g_ctl = c;
          break;
        }
        other++;  // not our listener: closed without a byte of ours
      }
      close(c);
      usleep(200000);
    }
  }
  kvf("ctl=%s rdv=verified rdv_%s=%d\n", lis ? "listen" : "connect", lis ? "foreign" : "rejected", other);
  setsockopt(g_ctl, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));
}
static void ctlSend(uint32_t type, uint32_t iter, uint32_t a, uint64_t m) {
  Msg x = {type, iter, a, 0, m};
  if (!sendAll(g_ctl, &x, sizeof(x))) nicFail("control send");
}
static Msg ctlRecv(int ms) {
  Msg x;
  if (!recvAll(g_ctl, &x, sizeof(x), ms)) nicFail("control receive (peer gone or bound)");
  if (x.type == M_ERR) nicFail("the peer reported an error");
  return x;
}
// the setup record both sides exchange (unused fields are 0); b3 is a digest of the layout both must agree on
struct Hello {
  uint32_t mode, sig, iters, sizeCode, mtu, qpn0, qpn1, rkey0, rkey1, rkey2;
  uint8_t gid[16];
  uint64_t b3;
};
static Hello exchange(Hello me) {
  me.mtu = (uint32_t)g_pa.active_mtu;
  memcpy(me.gid, g_myGid, 16);
  Hello peer;
  if (!sendAll(g_ctl, &me, sizeof(me)) || !recvAll(g_ctl, &peer, sizeof(peer), 10000)) setupFail("hello exchange");
  if (peer.mode != me.mode || peer.sig != me.sig || peer.iters != me.iters || peer.sizeCode != me.sizeCode || peer.b3 != me.b3)
    setupFail("the two sides disagree on mode, signal, count, size or layout");
  g_pathMtu = (int)std::min(me.mtu, peer.mtu);
  kvf("path_mtu=%d peer_mtu=%u\n", g_pathMtu, peer.mtu);
  return peer;  // the caller connects its QPs, then ready()
}
static void ready() {
  Msg x = {M_READY, 0, 0, 0, 0}, y;
  if (!sendAll(g_ctl, &x, sizeof(x)) || !recvAll(g_ctl, &y, sizeof(y), 10000) || y.type != M_READY)
    setupFail("ready exchange");
  g_t0 = nowUs();
}

// ================================================================ vis (check 1)
static const size_t VIS_MAX = (size_t)2 << 20, VIS_BYTES = VIS_MAX + 4096, FLAG_OFF = VIS_MAX, FENCE_OFF = VIS_MAX + 64;
enum { P_A1 = 0, P_A2 = 1, P_A3 = 2 };
static const char* PN[3] = {"a1", "a2", "a3"};
static int sizeCodeOf(const std::string& s) { return s == "4k" ? 1 : s == "256k" ? 2 : s == "2m" ? 3 : s == "rand" ? 4 : 0; }
static uint32_t sizeOf(int code, uint64_t* rng) {  // rand: 4 KiB - 2 MiB in 4 KiB steps
  if (code < 4) return code == 1 ? 4096u : code == 2 ? 256u << 10 : (uint32_t)VIS_MAX;
  return 4096u * (uint32_t)(1 + splitmix(rng) % 512);
}
struct Cnt { long n = 0, bad = 0, edge = 0, afterBad = 0; unsigned long long stale = 0, corrupt = 0; };
// every word of [0, nw) against this iteration's value, last word first (the a1 read meets the last-written bytes first)
static void scanWords(const volatile uint64_t* p, size_t nw, uint32_t iter1, unsigned long long* stale,
                      unsigned long long* corrupt) {
  for (size_t k = nw; k-- > 0;) {
    const uint64_t v = p[k];
    if (v == (((uint64_t)iter1 << 32) | (uint32_t)k)) continue;
    if ((uint32_t)v == (uint32_t)k && (uint32_t)(v >> 32) < iter1) (*stale)++;
    else (*corrupt)++;
  }
}
struct VisHost { ibv_cq* lcq; ibv_qp *rq, *fa, *fb, *ra, *rb; uint64_t *buf, *stg, *fst; ibv_mr *mr, *stgMr, *fstMr; };
static unsigned long long g_queryCap = 0;
static std::vector<double> g_qLat, g_fenceUs, g_read3Us;
// QUERY_QP until rmsn - base == target (mod 2^24); edge: a query saw less; reach: start of the query that saw it - tp
static long waitRmsn(ibv_qp* q, uint32_t base, uint64_t target, uint32_t perIter, double tp, double est, bool* edge,
                     double* reach) {
  while (nowUs() < tp + 0.9 * est) continue;
  const uint32_t want = (uint32_t)(target & MASK24);
  const double gap0 = std::max(20.0, est / 10.0);
  double last = 0;
  for (long polls = 1;; polls++) {
    const double gap = polls <= 10 ? gap0 : std::min(1000.0, gap0 * (double)(polls - 9));
    while (polls > 1 && nowUs() - last < gap) continue;
    if (g_queryQp.load() >= g_queryCap) nicFail("QUERY_QP cap of the run reached");
    uint32_t rm = 0, state = 0;
    const double t0 = last = nowUs();
    if (!queryRmsnRaw(q, &rm, &state)) nicFail("QUERY_QP (DEVX) failed");
    const double lat = nowUs() - t0;
    g_queryQp++;
    g_qLat.push_back(lat);
    if (lat > 50000.0) nicFail("a QUERY_QP took longer than 50 ms");
    const uint32_t got = (rm - base) & MASK24;
    if (got == want) {
      *reach = t0 - tp;
      return polls;
    }
    if (((want - got) & MASK24) > perIter) nicFail("rmsn outside the window of this iteration");
    *edge = true;
    if (state != 0x3) nicFail("responder QP not in RTS");
    if (polls >= 200) nicFail("more than 200 QUERY_QP in one iteration");
    if (nowUs() - tp > 2e6) nicFail("rmsn did not reach the posted count within 2 s");
  }
}
static void visFence(VisHost& h, bool record) {  // one 8-byte READ of the pool word at FENCE_OFF (loopback pair, same PD)
  Op op = {(uint64_t)(uintptr_t)h.fst, h.fstMr->lkey, 8, FENCE_OFF, h.mr->rkey};
  const double t0 = nowUs();
  runChain(h.fa, h.lcq, IBV_WR_RDMA_READ, &op, 1, 2000, "fence READ post");
  if (record) g_fenceUs.push_back(nowUs() - t0);
}
static int visWriter(ibv_cq* cq, ibv_qp* wqp, const Hello& peer, uint32_t perIter) {
  size_t srcBytes = 0;
  void* src = cuMemAllocRdma(VIS_MAX, &srcBytes);
  ibv_pd* pd = wqp->pd;
  ibv_mr* srcMr = regDmabuf(pd, src, srcBytes, ACC_WIN);
  uint64_t* fsrc = (uint64_t*)hostAlloc(4096);
  ibv_mr* fsrcMr = ibv_reg_mr(pd, fsrc, 4096, IBV_ACCESS_LOCAL_WRITE);
  if (srcMr == nullptr || fsrcMr == nullptr) setupFail("writer MRs");
  cudaStream_t st = nullptr;
  CK(cudaStreamCreateWithFlags(&st, cudaStreamNonBlocking));
  kvf("source=gpu alloc=cumem_gdr mr=dmabuf mr_relaxed=0\n");
  ready();
  uint64_t m = 0;
  long n = 0;
  char err[192];
  for (g_done = 0;;) {  // GO -> fill -> WRITE (+ flag) -> POSTED -> own completion -> DONE
    const Msg go = ctlRecv(30000);
    if (go.type == M_END) break;
    if (go.type != M_GO || go.a == 0 || go.a > VIS_MAX || go.a % 8 != 0) nicFail("unexpected control message (writer)");
    fillKernel<<<120, 256, 0, st>>>((unsigned long long*)src, go.a / 8, go.iter + 1);
    CK(cudaGetLastError());
    CK(cudaStreamSynchronize(st));
    *fsrc = (uint64_t)go.iter + 1;
    const Op ops[2] = {{0 /* iova 0: local addresses are offsets */, srcMr->lkey, go.a, 0, peer.rkey0},
                       {(uint64_t)(uintptr_t)fsrc, fsrcMr->lkey, 8, FLAG_OFF, peer.rkey0}};
    const uint64_t last = postChain(wqp, IBV_WR_RDMA_WRITE, ops, (int)perIter);
    if (last == 0) nicFail("writer post");
    m += perIter;
    ctlSend(M_POSTED, go.iter, go.a, m);
    if (!cqWait(cq, last, 2000, err, sizeof(err))) nicFail(err);
    const Msg d = ctlRecv(30000);
    if (d.type != M_DONE || d.iter != go.iter) nicFail("control message out of order (writer)");
    g_done = ++n;
  }
  kvf("iterations=%ld messages=%llu run_s=%.2f result=WRITER_DONE exit=0\n", n, (unsigned long long)m, (nowUs() - g_t0) / 1e6);
  return 0;
}
static int runVis(int argc, char** argv) {
  if (argc < 9) setupFail("usage: vis <writer|host> <ib_dev> <gid_index> <4k|256k|2m|rand> <iters> <ctl>");
  const std::string role = argv[3], szs = argv[6];
  g_gid = atoi(argv[5]);
  const long iters = atol(argv[7]);
  const int code = sizeCodeOf(szs);
  const char* sigs = getenv("MF_SIGNAL") && *getenv("MF_SIGNAL") ? getenv("MF_SIGNAL") : "msn";
  const bool flag = strcmp(sigs, "flag") == 0, host = role == "host";
  if ((role != "writer" && !host) || code == 0 || iters < 3 || iters > 300000 || (!flag && strcmp(sigs, "msn") != 0))
    setupFail("role writer|host, size 4k|256k|2m|rand, iters 3..300000, MF_SIGNAL msn|flag");
  if (!rmsnSelfTest()) setupFail("rmsn modulo-2^24 self-test");
  const uint64_t seed = (uint64_t)envL("MF_SEED", 0x4d46);
  const uint32_t perIter = flag ? 2 : 1;
  kvf("mode=vis role=%s size=%s iters=%ld signal=%s seed=%#lx rmsn_selftest=ok\n", role.c_str(), szs.c_str(), iters, sigs,
      (unsigned long)seed);
  ibv_context* ctx = openDev(argv[4], host && !flag);  // DEVX only where QUERY_QP is issued
  ibv_pd* pd = ibv_alloc_pd(ctx);
  ibv_cq* cq = ibv_create_cq(ctx, 64, nullptr, nullptr, 0);
  if (pd == nullptr || cq == nullptr) setupFail("PD/CQ");
  Hello me{};
  me.mode = 1, me.sig = perIter, me.iters = (uint32_t)iters, me.sizeCode = (uint32_t)code, me.b3 = VIS_BYTES;
  if (!host) {
    cudaInit();
    ibv_qp* wqp = makeQp(pd, cq, 8);
    me.qpn0 = wqp->qp_num;
    ctlOpen(argv[8]);
    const Hello peer = exchange(me);
    if (!connectQp(wqp, peer.qpn0, peer.gid, g_pathMtu)) setupFail("connect to the peer");
    return visWriter(cq, wqp, peer, perIter);
  }
  VisHost h;  // the pool and every other MR and QP of this process in ONE PD (9.3, 9.4: the GIN PD)
  h.lcq = ibv_create_cq(ctx, 64, nullptr, nullptr, 0);
  if (h.lcq == nullptr) setupFail("loopback CQ");
  h.buf = (uint64_t*)hostAlloc(VIS_BYTES), h.stg = (uint64_t*)hostAlloc(VIS_MAX), h.fst = (uint64_t*)hostAlloc(4096);
  for (size_t w = 0; w < VIS_MAX / 8; w++) h.buf[w] = w;  // "iteration 0"
  h.mr = regPool(pd, h.buf, VIS_BYTES);
  h.stgMr = ibv_reg_mr(pd, h.stg, VIS_MAX, IBV_ACCESS_LOCAL_WRITE);
  h.fstMr = ibv_reg_mr(pd, h.fst, 4096, IBV_ACCESS_LOCAL_WRITE);
  if (h.mr == nullptr || h.stgMr == nullptr || h.fstMr == nullptr) setupFail("host MRs");
  h.rq = makeQp(pd, cq, 4), h.fa = makeQp(pd, h.lcq, 8), h.fb = makeQp(pd, h.lcq, 8);
  h.ra = makeQp(pd, h.lcq, 8), h.rb = makeQp(pd, h.lcq, 8);
  loopPair(h.fa, h.fb);
  loopPair(h.ra, h.rb);
  kvf("pool=host pool_bytes=%zu pool_iova=0 pool_relaxed=0 same_pd=1 fence=loopback_read_8B a3=loopback_read_third_qp\n",
      VIS_BYTES);
  me.qpn0 = h.rq->qp_num, me.rkey0 = h.mr->rkey;
  ctlOpen(argv[8]);
  const Hello peer = exchange(me);
  if (!connectQp(h.rq, peer.qpn0, peer.gid, g_pathMtu)) setupFail("connect to the peer");
  std::vector<int> path((size_t)iters);
  std::vector<uint32_t> size((size_t)iters);
  uint64_t s1 = seed, s2 = seed ^ 0x5a5a5a5a5a5a5a5aull;
  for (long b = 0; b * 3 < iters; b++) {
    int blk[3] = {P_A1, P_A2, P_A3};
    for (int k = 2; k > 0; k--) std::swap(blk[k], blk[splitmix(&s1) % (uint64_t)(k + 1)]);
    for (int k = 0; k < 3 && b * 3 + k < iters; k++) path[(size_t)(b * 3 + k)] = blk[k];
  }
  for (uint32_t& x : size) x = sizeOf(code, &s2);
  const unsigned long long budget = (unsigned long long)envL("MF_QUERY_BUDGET", 30000);
  g_queryCap = budget + 400;
  uint32_t rmsn0 = 0, qs = 0;
  if (!flag) {
    if (!queryRmsnRaw(h.rq, &rmsn0, &qs)) setupFail("QUERY_QP (DEVX) refused");
    g_queryQp++;
    kvf("rmsn0=%u qp_state=%u query_budget=%llu query_cap=%llu\n", rmsn0, qs, budget, g_queryCap);
  }
  h.buf[FENCE_OFF / 8] = 0x6d6972726f723121ull;  // self-check of both loopback READ targets: known pool words come back
  visFence(h, false);
  if (*h.fst != h.buf[FENCE_OFF / 8]) setupFail("loopback READ self-check (fence pair)");
  const Op sop = {(uint64_t)(uintptr_t)h.stg, h.stgMr->lkey, 4096, 0, h.mr->rkey};
  runChain(h.ra, h.lcq, IBV_WR_RDMA_READ, &sop, 1, 2000, "self-check READ post");
  if (memcmp(h.stg, h.buf, 4096) != 0) setupFail("loopback READ self-check (third pair)");
  kvf("selfcheck=ok\n");
  ready();
  const double runS = getenv("MF_RUN_S") ? atof(getenv("MF_RUN_S")) : iters / 200.0 + 60.0;
  Cnt C[3];
  std::vector<double> reachUs;
  long pollsMax = 0, pollsSum = 0, done = 0;
  double est = 0;
  uint64_t m = 0;
  bool incomplete = false, budgetStop = false;
  g_done = 0;
  for (long i = 0; i < iters; i++) {
    if ((incomplete = (nowUs() - g_t0) / 1e6 > runS)) break;
    if ((budgetStop = !flag && budget > 0 && g_queryQp.load() >= budget)) break;
    const int p = path[(size_t)i];
    const uint32_t n = size[(size_t)i], it1 = (uint32_t)i + 1;
    if (p == P_A3) memset(h.stg, 0xff, n);  // poisoned: a READ that delivered nothing cannot pass
    ctlSend(M_GO, (uint32_t)i, n, 0);
    const Msg x = ctlRecv(10000);
    const double tp = nowUs();
    if (x.type != M_POSTED || x.iter != (uint32_t)i || x.a != n) nicFail("control message out of order (host)");
    if (x.m != (m += perIter)) nicFail("POSTED count differs from the expected messages");
    bool edge = false;
    if (flag) {
      const volatile uint64_t* fw = (const volatile uint64_t*)((char*)h.buf + FLAG_OFF);
      for (long spins = 0; *fw != (uint64_t)it1; spins++) {
        edge = true;
        if ((spins & 1023) == 1023 && nowUs() - tp > 2e6) nicFail("the flag word did not arrive within 2 s");
      }
      reachUs.push_back(nowUs() - tp);
    } else {
      double reach = 0;
      const long polls = waitRmsn(h.rq, rmsn0, m, perIter, tp, est, &edge, &reach);
      reachUs.push_back(reach);
      est = est == 0 ? reach : 0.8 * est + 0.2 * reach;
      pollsMax = std::max(pollsMax, polls);
      pollsSum += polls;
    }
    std::atomic_thread_fence(std::memory_order_acquire);
    unsigned long long stale = 0, corrupt = 0;
    if (p == P_A2) visFence(h, true);
    if (p != P_A3) {
      scanWords(h.buf, n / 8, it1, &stale, &corrupt);
    } else {
      const Op op = {(uint64_t)(uintptr_t)h.stg, h.stgMr->lkey, n, 0, h.mr->rkey};
      const double t0 = nowUs();
      runChain(h.ra, h.lcq, IBV_WR_RDMA_READ, &op, 1, 2000, "third-QP READ post");
      g_read3Us.push_back(nowUs() - t0);
      scanWords(h.stg, n / 8, it1, &stale, &corrupt);
    }
    Cnt& c = C[p];
    c.n++, c.stale += stale, c.corrupt += corrupt, c.edge += edge ? 1 : 0;
    if (p != P_A2) visFence(h, false);  // every iteration ends fenced
    if (stale || corrupt) {
      c.bad++;
      visFence(h, false);
      unsigned long long s3 = 0, c3 = 0;
      scanWords(h.buf, n / 8, it1, &s3, &c3);
      if (s3 || c3) c.afterBad++;
    }
    ctlSend(M_DONE, (uint32_t)i, 0, 0);
    g_done = ++done;
  }
  ctlSend(M_END, (uint32_t)done, 0, 0);
  for (int p = 0; p < 3; p++)
    kvf("%s_n=%ld %s_bad=%ld %s_stale_words=%llu %s_corrupt_words=%llu %s_edge=%ld %s_after_fence_bad=%ld\n", PN[p], C[p].n,
        PN[p], C[p].bad, PN[p], C[p].stale, PN[p], C[p].corrupt, PN[p], C[p].edge, PN[p], C[p].afterBad);
  kvf("reach_p50_us=%.1f reach_p99_us=%.1f reach_max_us=%.1f query_qp_total=%llu query_p50_us=%.1f query_max_us=%.1f "
      "polls_max=%ld polls_per_iter_mean=%.2f fence_p50_us=%.1f fence_max_us=%.1f read3_p50_us=%.1f read3_max_us=%.1f\n",
      pct(reachUs, 0.5), pct(reachUs, 0.99), pct(reachUs, 1.0), g_queryQp.load(), pct(g_qLat, 0.5), pct(g_qLat, 1.0),
      pollsMax, done ? (double)pollsSum / (double)done : 0.0, pct(g_fenceUs, 0.5), pct(g_fenceUs, 1.0), pct(g_read3Us, 0.5),
      pct(g_read3Us, 1.0));
  const bool fail = C[P_A2].bad > 0 || C[P_A3].bad > 0;
  const int ex = fail ? 1 : incomplete ? 5 : 0;
  kvf("iterations_done=%ld budget_stop=%d run_s=%.2f result=%s exit=%d\n", done, budgetStop ? 1 : 0, (nowUs() - g_t0) / 1e6,
      fail ? "FAIL" : incomplete ? "INCOMPLETE" : "PASS", ex);
  return ex;
}

// ================================================================ store (check 3)
struct Bg {  // the second stream: bursts of K WRITEs on its own QP while on
  std::atomic<int> on{0}, busy{0}, stop{0}, err{0};
  std::atomic<long> rounds{0};
  std::atomic<unsigned long long> bytes{0}, ns{0};
  char msg[192] = {0};
};
static void bgWait(Bg& bg, bool running) {  // running: one more burst completed; else: the stream is idle
  const long r0 = bg.rounds.load();
  const double t0 = nowUs();
  while (running ? bg.rounds.load() <= r0 : bg.busy.load() != 0) {
    if (bg.err.load()) nicFail(bg.msg);
    if (nowUs() - t0 > 5e6) nicFail(running ? "no background burst within 5 s" : "the background stream did not stop in 5 s");
    std::this_thread::sleep_for(std::chrono::microseconds(20));
  }
  if (bg.err.load()) nicFail(bg.msg);
}
static void bgLoop(Bg& bg, ibv_qp* bq, ibv_cq* bcq, const Op* ops, int k) {
  while (!bg.stop.load()) {
    bg.busy = 1;  // before reading on (seq_cst): the main thread that cleared on then sees busy until this burst ends
    if (!bg.on.load()) {
      bg.busy = 0;
      std::this_thread::sleep_for(std::chrono::microseconds(20));
      continue;
    }
    const double t0 = nowUs();
    const uint64_t id = postChain(bq, IBV_WR_RDMA_WRITE, ops, k);
    if (id == 0 || !cqWait(bcq, id, 5000, bg.msg, sizeof(bg.msg))) {
      if (id == 0) snprintf(bg.msg, sizeof(bg.msg), "background post");
      bg.err = 1;
      break;
    }
    for (int j = 0; j < k; j++) bg.bytes += ops[j].len;
    bg.ns += (unsigned long long)((nowUs() - t0) * 1e3);
    bg.rounds++;
  }
  bg.busy = 0;
}
static int runStore(int argc, char** argv) {
  if (argc < 8) setupFail("usage: store <src|host> <ib_dev> <gid_index> <reps> <ctl>");
  const std::string role = argv[3];
  g_gid = atoi(argv[5]);
  const long reps = atol(argv[6]);
  if ((role != "src" && role != "host") || reps < 10 || reps > 10000 || reps % 10 != 0)
    setupFail("role src|host, reps a multiple of 10 in 10..10000");
  const size_t MiB = (size_t)1 << 20, storeB = (size_t)envL("MF_STORE_MIB", 30) * MiB;
  const size_t readB = (size_t)envL("MF_READ_MIB", 150) * MiB, chunkB = (size_t)envL("MF_READ_CHUNK_MIB", 30) * MiB;
  const size_t bgB = (size_t)envL("MF_BG_MIB", 2) * MiB;
  const int bgK = (int)envL("MF_BG_K", 8);
  if (storeB == 0 || storeB > ((size_t)1 << 30) || readB == 0 || readB > ((size_t)4 << 30) || chunkB == 0 ||
      chunkB > ((size_t)1 << 30) || (readB + chunkB - 1) / chunkB > 32 || bgB == 0 || bgK < 1 || bgK > 32 ||
      bgB * (size_t)bgK > storeB)
    setupFail("MF_STORE_MIB, MF_READ_MIB, MF_READ_CHUNK_MIB, MF_BG_MIB or MF_BG_K out of range");
  const bool src = role == "src";
  kvf("mode=store role=%s reps=%ld store_bytes=%zu read_bytes=%zu read_chunk_bytes=%zu bg_bytes=%zu bg_k=%d\n", role.c_str(),
      reps, storeB, readB, chunkB, bgB, bgK);
  ibv_context* ctx = openDev(argv[4], false);
  cudaInit();
  ibv_pd* pd = ibv_alloc_pd(ctx);
  ibv_cq *fcq = ibv_create_cq(ctx, 256, nullptr, nullptr, 0), *bcq = ibv_create_cq(ctx, 256, nullptr, nullptr, 0);
  if (pd == nullptr || fcq == nullptr || bcq == nullptr) setupFail("PD/CQ");
  ibv_qp *fq = makeQp(pd, fcq, 64), *bq = makeQp(pd, bcq, 64);
  Hello me{};
  uint64_t *sbuf = nullptr, *rbuf = nullptr;
  ibv_mr *regMr = nullptr, *rbufMr = nullptr;
  if (src) {  // the GPU region (the image) and the host buffer the READs land in (the spare's FETCH buffer)
    size_t rb = 0;
    void* region = cuMemAllocRdma(storeB, &rb);
    fillKernel<<<120, 256>>>((unsigned long long*)region, storeB / 8, 1);
    CK(cudaGetLastError());
    CK(cudaDeviceSynchronize());
    regMr = regDmabuf(pd, region, rb, ACC_WIN);
    rbuf = (uint64_t*)hostAlloc(readB);
    rbufMr = ibv_reg_mr(pd, rbuf, readB, IBV_ACCESS_LOCAL_WRITE);
    if (regMr == nullptr || rbufMr == nullptr) setupFail("src MRs (pinned memory limit? see memlock_kib)");
    kvf("region=gpu alloc=cumem_gdr mr=dmabuf mr_relaxed=0 fetch_buffer=host\n");
  } else {  // the store MR, the MR the READs fetch from (both as the pool: iova 0, no RO), the background target (GPU)
    sbuf = (uint64_t*)hostAlloc(storeB);
    uint64_t* rsrc = (uint64_t*)hostAlloc(readB);
    for (size_t w = 0; w < readB / 8; w++) rsrc[w] = (7ull << 32) | (uint32_t)w;
    size_t bb = 0;
    void* bgt = cuMemAllocRdma(bgB * (size_t)bgK, &bb);
    ibv_mr *smr = regPool(pd, sbuf, storeB), *rmr = regPool(pd, rsrc, readB), *bmr = regDmabuf(pd, bgt, bb, ACC_WIN);
    if (smr == nullptr || rmr == nullptr || bmr == nullptr) setupFail("host MRs (pinned memory limit? see memlock_kib)");
    me.rkey0 = smr->rkey, me.rkey1 = rmr->rkey, me.rkey2 = bmr->rkey;
    kvf("store=host read_source=host pool_iova=0 pool_relaxed=0 bg_target=gpu same_pd=1\n");
  }
  ctlOpen(argv[7]);
  me.mode = 2, me.iters = (uint32_t)reps, me.qpn0 = fq->qp_num, me.qpn1 = bq->qp_num;
  me.b3 = (storeB ^ (readB << 1) ^ (chunkB << 2) ^ (bgB << 3)) + (uint64_t)bgK;
  const Hello peer = exchange(me);
  if (!connectQp(fq, peer.qpn0, peer.gid, g_pathMtu) || !connectQp(bq, peer.qpn1, peer.gid, g_pathMtu))
    setupFail("connect to the peer");
  ready();
  if (!src) {  // ---- host: passive; after the WRITE phase it reads its store MR once (information) ----
    for (Msg x = ctlRecv(300000); x.type != M_END; x = ctlRecv(300000)) {
      if (x.type != M_PHASE) nicFail("unexpected control message (host)");
      std::this_thread::sleep_for(std::chrono::milliseconds(2));
      unsigned long long bad = 0;
      const volatile uint64_t* v = sbuf;
      for (size_t w = 0; w < storeB / 8; w++) bad += v[w] != ((1ull << 32) | (uint32_t)w) ? 1 : 0;
      kvf("store_check_bad_words=%llu\n", bad);
    }
    kvf("run_s=%.2f result=HOST_DONE exit=0\n", (nowUs() - g_t0) / 1e6);
    return 0;
  }
  // ---- src: the WRITE phase (blocks of 10: no traffic, background bursts, alternating) ----
  Bg bg;
  Op bops[32];
  for (int k = 0; k < bgK; k++) bops[k] = {(uint64_t)k * bgB, regMr->lkey, (uint32_t)bgB, (uint64_t)k * bgB, peer.rkey2};
  std::thread bgT(bgLoop, std::ref(bg), bq, bcq, bops, bgK);
  struct Row { int phase, arm; long rep; double ms; };
  std::vector<Row> rows;
  std::vector<double> wArm[2], rd;
  g_done = 0;
  for (long j = 0; j < 2 * reps / 10; j++) {
    const int arm = (int)(j & 1);
    bg.on = arm;
    bgWait(bg, arm == 1);  // the stream runs (or is idle) before the first timed WRITE of the block
    for (int r = 0; r < 10; r++) {
      const Op op = {0, regMr->lkey, (uint32_t)storeB, 0, peer.rkey0};
      const double t0 = nowUs();
      runChain(fq, fcq, IBV_WR_RDMA_WRITE, &op, 1, 10000, "store WRITE post");
      wArm[arm].push_back((nowUs() - t0) / 1e3);
      rows.push_back(Row{0, arm, (long)wArm[arm].size() - 1, wArm[arm].back()});
    }
    if (bg.err.load()) nicFail(bg.msg);
    g_done = j + 1;
  }
  bg.on = 0;
  bgWait(bg, false);
  bg.stop = 1, bgT.join();
  ctlSend(M_PHASE, 1, 0, 0);
  // ---- the READ phase (the FETCH of 9.4: image + segments from one host MR) ----
  Op ops[32];
  int nc = 0;
  for (size_t o = 0; o < readB; o += chunkB, nc++)
    ops[nc] = {(uint64_t)(uintptr_t)rbuf + o, rbufMr->lkey, (uint32_t)std::min(chunkB, readB - o), o, peer.rkey1};
  unsigned long long readBad = 0;
  for (long r = 0; r < reps; r++) {
    const bool check = r == 0 || r == reps - 1;
    if (check) memset(rbuf, 0xff, readB);
    const double t0 = nowUs();
    runChain(fq, fcq, IBV_WR_RDMA_READ, ops, nc, 20000, "store READ post");
    rd.push_back((nowUs() - t0) / 1e3);
    rows.push_back(Row{1, 0, r, rd.back()});
    for (size_t w = 0; check && w < readB / 8; w++) readBad += rbuf[w] != ((7ull << 32) | (uint32_t)w) ? 1 : 0;
  }
  ctlSend(M_END, 0, 0, 0);
  const char* tf = getenv("MF_TIMING_FILE");
  FILE* f = (tf != nullptr && *tf != 0) ? fopen(tf, "w") : nullptr;
  if (f != nullptr) {
    fprintf(f, "phase\tarm\trep\tms\n");
    for (const Row& x : rows) fprintf(f, "%s\t%s\t%ld\t%.4f\n", x.phase ? "read" : "write", x.arm ? "bg" : "none", x.rep, x.ms);
    fclose(f);
  }
  kvf("timing_file_rows=%zu\n", f != nullptr ? rows.size() : (size_t)0);
  const double gib = 1.0 / (1 << 30), bgS = bg.ns.load() / 1e9;
  for (int a = 0; a < 2; a++) {
    const char* an = a ? "bg" : "none";
    kvf("write_%s_n=%zu write_%s_p50_ms=%.3f write_%s_p99_ms=%.3f write_%s_max_ms=%.3f write_%s_gibps_at_p50=%.2f\n", an,
        wArm[a].size(), an, pct(wArm[a], 0.5), an, pct(wArm[a], 0.99), an, pct(wArm[a], 1.0), an,
        (double)storeB * gib / (pct(wArm[a], 0.5) / 1e3));
  }
  kvf("bg_rounds=%ld bg_gibps=%.2f\n", bg.rounds.load(), bgS > 0 ? (double)bg.bytes.load() * gib / bgS : 0.0);
  kvf("read_n=%zu read_p50_ms=%.3f read_p99_ms=%.3f read_max_ms=%.3f theta_gibps=%.2f theta_gbps=%.2f read_bad_words=%llu\n",
      rd.size(), pct(rd, 0.5), pct(rd, 0.99), pct(rd, 1.0), (double)readB * gib / (pct(rd, 0.5) / 1e3),
      (double)readB / 1e9 / (pct(rd, 0.5) / 1e3), readBad);
  kvf("run_s=%.2f result=DONE exit=0\n", (nowUs() - g_t0) / 1e6);
  return 0;
}

// ================================================================ bar1 (check 4)
// 1: the go file exists; 2: the stop file came first; 0: neither within s seconds
static int fileWait(const std::string& go, const std::string& stop, double s) {
  const double t0 = nowUs();
  struct stat sb;
  for (;; usleep(10000)) {
    if (stat(go.c_str(), &sb) == 0) return 1;
    if (stat(stop.c_str(), &sb) == 0) return 2;
    if (nowUs() - t0 > s * 1e6) return 0;
  }
}
static void stage(const char* tag, const char* s, int ok) {
  printf("MFSTAGE %s %s ok=%d\n", tag, s, ok);
  fflush(stdout);
  kvf("stage=%s ok=%d t_s=%.3f\n", s, ok, (nowUs() - g_t0) / 1e6);
}
static int runBar1(int argc, char** argv) {
  if (argc < 7) setupFail("usage: bar1 <tag> <ib_dev> <ctl_dir> <pd2 0|1>");
  const char* tag = argv[3];
  const std::string dir = argv[5], spec = getenv("MF_BAR1_MIB") && *getenv("MF_BAR1_MIB") ? getenv("MF_BAR1_MIB") : "6,24";
  const bool pd2 = atoi(argv[6]) != 0;
  std::vector<size_t> mib;
  for (size_t a = 0; a < spec.size();) {
    const size_t b = std::min(spec.find(',', a), spec.size());
    mib.push_back((size_t)atol(spec.substr(a, b - a).c_str()));
    a = b + 1;
  }
  if (mib.empty() || mib.size() > 4) setupFail("MF_BAR1_MIB: one to four sizes in MiB");
  for (size_t x : mib)
    if (x == 0 || x > 256) setupFail("MF_BAR1_MIB: sizes in 1..256 MiB");
  const double waitS = (double)envL("MF_STAGE_WAIT_S", 120);
  g_t0 = nowUs();
  kvf("mode=bar1 tag=%s pd2=%d windows_mib=%s pid=%d\n", tag, pd2 ? 1 : 0, spec.c_str(), (int)getpid());
  ibv_context* ctx = openDev(argv[4], false);
  ibv_pd* pds[2] = {ibv_alloc_pd(ctx), pd2 ? ibv_alloc_pd(ctx) : nullptr};
  if (pds[0] == nullptr || (pd2 && pds[1] == nullptr)) setupFail("PD");
  cudaInit();
  std::vector<void*> win;
  std::vector<size_t> bytes(mib.size());
  for (size_t j = 0; j < mib.size(); j++) win.push_back(cuMemAllocRdma(mib[j] << 20, &bytes[j]));
  CK(cudaDeviceSynchronize());
  stage(tag, "ctx", 1);
  std::vector<ibv_mr*> mrs;
  int fails = 0;
  const char* sn[2] = {"pd1", "pd2"};
  const std::string stopF = dir + "/stop";
  for (int k = 0; k < 2; k++) {
    const int w = fileWait(dir + "/go_" + sn[k], stopF, waitS);
    if (w != 1) {
      if (w == 0) kvf("stage_wait_timeout=go_%s\n", sn[k]);
      else stage(tag, k ? "pd2_skipped" : "pd1_skipped", 1);
      break;
    }
    int ok = 1;
    for (size_t j = 0; pds[k] != nullptr && j < win.size(); j++) {
      const double t0 = nowUs();
      errno = 0;
      ibv_mr* mr = regDmabuf(pds[k], win[j], bytes[j], ACC_WIN);
      kvf("reg_%s_%zumib_ok=%d reg_%s_%zumib_ms=%.2f reg_%s_%zumib_errno=%d\n", sn[k], mib[j], mr ? 1 : 0, sn[k], mib[j],
          (nowUs() - t0) / 1e3, sn[k], mib[j], mr ? 0 : errno);
      if (mr != nullptr) mrs.push_back(mr);
      else ok = 0, fails++;
    }
    stage(tag, sn[k], ok);
  }
  if (fileWait(stopF, stopF, waitS) == 0) kvf("stage_wait_timeout=stop\n");
  for (ibv_mr* mr : mrs) ibv_dereg_mr(mr);
  stage(tag, "end", 1);
  kvf("registrations=%zu registrations_failed=%d run_s=%.2f result=%s exit=%d\n", mrs.size() + (size_t)fails, fails,
      (nowUs() - g_t0) / 1e6, fails ? "REG_FAIL" : "DONE", fails ? 8 : 0);
  return fails ? 8 : 0;
}

int main(int argc, char** argv) {
  if (argc < 3) {
    fprintf(stderr, "usage: %s <out_kv> vis|store|bar1 ... (see the head of mirror_feas.cu)\n", argv[0]);
    return 2;
  }
  g_kv = fopen(argv[1], "w");
  if (g_kv == nullptr) return 2;
  const std::string mode = argv[2];
  g_dev = (int)envL("MF_CUDA_DEV", 0);
  const long wdS = envL("MF_WATCHDOG_S", 300);
  std::thread([wdS]() {
    std::this_thread::sleep_for(std::chrono::seconds(wdS));
    static const char m[] = "WATCHDOG: mirror_feas exceeded its bound; exiting 7\n";
    ssize_t k = write(2, m, sizeof(m) - 1);
    (void)k;
    progressKv();
    kvf("watchdog=1 result=ERROR exit=7\n");
    _exit(7);
  }).detach();
  struct rlimit rl;
  if (getrlimit(RLIMIT_MEMLOCK, &rl) == 0)
    kvf("memlock_kib=%s hard_bound_s=%ld\n",
        rl.rlim_cur == RLIM_INFINITY ? "unlimited" : std::to_string((unsigned long long)rl.rlim_cur / 1024).c_str(), wdS);
  if (mode == "vis") return runVis(argc, argv);
  if (mode == "store") return runStore(argc, argv);
  if (mode == "bar1") return runBar1(argc, argv);
  setupFail("mode must be vis, store or bar1");
}
