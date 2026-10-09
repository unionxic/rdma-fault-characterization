// nic_gate_test.cu - gin-remaining (EXPERIMENT.md 9, 5): the gate word protocol of ../gate_ce_test.cu with every host
// read and write of GPU memory made over a NIC loopback, as the hr layer's NIC copy path makes them (gin_host_gdaki.cc
// gdakiLbXfer): a host-to-device write is one RDMA WRITE from a registered host staging buffer followed by an 8-byte
// RDMA READ of the same GPU MR (signaled; its completion means the written bytes are in GPU memory); a device-to-host
// read is one RDMA READ. Loopback RC QP pair on the given HCA, port 1, in a protection domain of its own; RoCE: a
// link-local GID of type "RoCE v2" (as the layer chooses) unless an index is given; the GPU memory registered as a
// dmabuf MR (else nvidia-peermem). No NCCL.
//
// The gate is ONE 64-bit word in GPU memory: epoch in the high 32 bits (written only by the host, here a 4-byte NIC
// write), a count in the low 32 bits (SM 64-bit atomics at GPU scope, as gin_gdaki.h tsWordEnter/tsWordLeave). Device
// threads enter with one atomic add whose return value carries the epoch and leave with a release add of -1; with an odd
// epoch they back out and park. The host quiesces with: write epoch odd, read the word until count == 0, hold, publish
// the next even epoch. Checked (as gate_ce_test):
//   lost NIC write  the high half read back right after each host write must equal the value written (a 64-bit atomic
//                   read-modify-write that raced the 4-byte NIC write and put back a stale high half would show here),
//                   and after the kernel ends the high half equals the last write;
//   lost increment  after the kernel ends the low half must be exactly 0 (every +1 had its -1);
//   Dekker          once the host has written epoch 2k+1 and then read count == 0, no thread may be inside with epoch
//                   2k: entered[k] read after count == 0 must never grow later, and `inside` must read 0 while odd;
//   quiesce timeout count == 0 not seen within 2 s of the odd write;
//   line updates    threads inside also add 1 to two index words at offsets 0 and 8 of the gate's 128-byte line (as the
//                   posters' sq_rsvd_index and sq_ready_index): both must equal the enters at the end.
// Every NIC write (epochs and the stop flag) is read back over the NIC; a mismatch counts as a lost write and is written
// again (bounded), so the run goes on and the counters stay separate.
// A phase passes only with none of these and with evidence that it ran: rounds > 0, threads entered, threads backed out
// on an odd epoch the NIC wrote, and the final high half (read by cudaMemcpy after the kernel) equal to the last write.
// Two phases, each <secs> seconds: a (64 blocks x 256 threads, no work inside: the most atomic traffic on the word) and b
// (8 blocks x 256 threads, 2000 ns inside: threads are inside at most quiesces).
//
// usage: nic_gate_test <out_kv> <ib_dev> [secs (5)] [gid_index (-1: link-local RoCE v2)] [cuda_device (0)]
// kv: name, ib_dev, link (eth|ib), gid_index, gid_kind, mr (dmabuf|peermem), then per phase <p>_rounds, <p>_enters,
//   <p>_backouts, <p>_lost_writes, <p>_final_hi, <p>_expected_hi, <p>_final_count, <p>_lost_inc, <p>_dekker,
//   <p>_inside_nonzero, <p>_quiesce_timeouts, <p>_idx_ok, <p>_q_p50_ms, <p>_q_p99_ms, <p>_q_max_ms, <p>_result
//   (PASS|FAIL); nic_ops, nic_errors, result (PASS iff both phases pass), exit.
// exit: 0 PASS; 1 a violation; 2 usage or setup error (kv setup_error=...); 3 a NIC request failed or timed out during a
// phase (kv nic_error=...); 6 CUDA error; 7 watchdog (75 s).
#include <cuda.h>
#include <cuda_runtime.h>
#include <infiniband/verbs.h>
#include <algorithm>
#include <cstdarg>
#include <cstddef>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <string>
#include <thread>
#include <unistd.h>
#include <vector>

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
      kvf("cuda_error=%s exit=6\n", cudaGetErrorName(e_));                            \
      _exit(6);                                                                       \
    }                                                                                 \
  } while (0)
[[noreturn]] static void setupFail(const char* what) {
  fprintf(stderr, "setup: %s (errno %d)\n", what, errno);
  kvf("setup_error=\"%s\" errno=%d exit=2\n", what, errno);
  _exit(2);
}

static const int MAXK = 1 << 20;  // epochs tracked in entered[]
static const size_t ALLOC = 8u << 20;
static const size_t ENTERED_OFF = 64u << 10;

// The first 128-byte line mirrors the library's: the gate word sits at offset 88 of doca_gpu_dev_verbs_qp, on the line
// whose offsets 0 and 8 (sq_rsvd_index, sq_ready_index) posters update with SM atomics while inside the gate.
struct Dev {
  unsigned long long idx0;      // offset 0: +1 by every thread inside (as sq_rsvd_index)
  unsigned long long idx1;      // offset 8: +1 by every thread inside (as sq_ready_index)
  unsigned long long pad0[9];   // offsets 16-87
  unsigned long long gate;      // offset 88: the gate word under test
  unsigned long long pad0b[4];  // offsets 96-127
  unsigned int inside;          // threads between enter and leave (witness)
  unsigned int stop;            // the host sets 1 (over the NIC, read back) to end the kernel; shares 8 bytes with inside
  unsigned int pad1[30];
  unsigned long long enters, backouts, iters, maxCount;
};
static_assert(offsetof(Dev, gate) == 88, "the gate word must sit at the library's offset");

__device__ __forceinline__ unsigned long long gateEnter(unsigned long long* p) {
  unsigned long long old;
  asm volatile("atom.acquire.gpu.global.add.u64 %0, [%1], 1;" : "=l"(old) : "l"(p) : "memory");
  return old;
}
__device__ __forceinline__ void gateLeave(unsigned long long* p) {
  asm volatile("red.release.gpu.global.add.u64 [%0], %1;" ::"l"(p), "l"(0xffffffffffffffffull) : "memory");
}
__device__ __forceinline__ unsigned long long ldRelaxed64(unsigned long long* p) {
  unsigned long long v;
  asm volatile("ld.relaxed.gpu.global.u64 %0, [%1];" : "=l"(v) : "l"(p) : "memory");
  return v;
}
__device__ __forceinline__ unsigned int ldRelaxed32(unsigned int* p) {
  unsigned int v;
  asm volatile("ld.relaxed.gpu.global.u32 %0, [%1];" : "=r"(v) : "l"(p) : "memory");
  return v;
}
__device__ __forceinline__ unsigned long long gtNow() {
  unsigned long long t;
  asm volatile("mov.u64 %0, %%globaltimer;" : "=l"(t));
  return t;
}

__global__ void hammer(Dev* d, unsigned int* entered, unsigned int workNs) {
  unsigned long long enters = 0, backouts = 0, iters = 0, maxc = 0;
  while (true) {
    if ((iters & 63) == 0 && ldRelaxed32(&d->stop)) break;
    iters++;
    const unsigned long long old = gateEnter(&d->gate);
    const unsigned int e = (unsigned int)(old >> 32), c = (unsigned int)old;
    if (c + 1 > maxc) maxc = c + 1;
    if (e & 1u) {  // a recovery owns the word: back out and park
      gateLeave(&d->gate);
      backouts++;
      while (((unsigned int)(ldRelaxed64(&d->gate) >> 32) & 1u) && !ldRelaxed32(&d->stop)) __nanosleep(200);
      continue;
    }
    atomicAdd(&d->inside, 1u);
    atomicAdd(&entered[(e >> 1) & (MAXK - 1)], 1u);
    atomicAdd(&d->idx0, 1ull);  // the posters' index atomics on the gate's line
    atomicAdd(&d->idx1, 1ull);
    if (workNs) {
      const unsigned long long t0 = gtNow();
      while (gtNow() - t0 < workNs) {
      }
    }
    atomicSub(&d->inside, 1u);
    gateLeave(&d->gate);
    enters++;
  }
  atomicAdd(&d->enters, enters);
  atomicAdd(&d->backouts, backouts);
  atomicAdd(&d->iters, iters);
  atomicMax(&d->maxCount, maxc);
}

static double nowMs() {
  struct timespec t;
  clock_gettime(CLOCK_MONOTONIC, &t);
  return t.tv_sec * 1e3 + t.tv_nsec * 1e-6;
}

// ---- the NIC loopback ----
struct Nic {
  ibv_context* ctx = nullptr;
  ibv_pd* pd = nullptr;
  ibv_cq* cq = nullptr;
  ibv_qp *qa = nullptr, *qb = nullptr;
  ibv_mr *gpuMr = nullptr, *stageMr = nullptr;
  uint8_t* stage = nullptr;  // 4096 B: [0, 64) write source, [64, 72) flush landing, [128, ...) read landing
  uintptr_t lo = 0, hi = 0;
  uint64_t nextId = 1;
  unsigned long long ops = 0, errors = 0;
  char err[160] = {0};
};
static Nic g_nic;

static bool sysfsGid(const char* dev, int idx, uint8_t out[16], char* type, size_t typeLen) {
  char path[256];
  snprintf(path, sizeof(path), "/sys/class/infiniband/%s/ports/1/gids/%d", dev, idx);
  FILE* f = fopen(path, "r");
  if (f == nullptr) return false;
  unsigned int h[8];
  const int n = fscanf(f, "%x:%x:%x:%x:%x:%x:%x:%x", &h[0], &h[1], &h[2], &h[3], &h[4], &h[5], &h[6], &h[7]);
  fclose(f);
  if (n != 8) return false;
  for (int k = 0; k < 8; k++) {
    out[2 * k] = (uint8_t)(h[k] >> 8);
    out[2 * k + 1] = (uint8_t)(h[k] & 0xff);
  }
  type[0] = '\0';
  snprintf(path, sizeof(path), "/sys/class/infiniband/%s/ports/1/gid_attrs/types/%d", dev, idx);
  f = fopen(path, "r");
  if (f != nullptr) {
    if (fgets(type, (int)typeLen, f) == nullptr) type[0] = '\0';
    fclose(f);
    type[strcspn(type, "\n")] = '\0';
  }
  return true;
}

static bool connectQp(ibv_qp* q, uint32_t dest, const ibv_port_attr& pa, bool eth, int gidIndex, const ibv_gid& gid) {
  ibv_qp_attr a;
  memset(&a, 0, sizeof(a));
  a.qp_state = IBV_QPS_INIT;
  a.pkey_index = 0;
  a.port_num = 1;
  a.qp_access_flags = IBV_ACCESS_REMOTE_READ | IBV_ACCESS_REMOTE_WRITE | IBV_ACCESS_LOCAL_WRITE;
  if (ibv_modify_qp(q, &a, IBV_QP_STATE | IBV_QP_PKEY_INDEX | IBV_QP_PORT | IBV_QP_ACCESS_FLAGS) != 0) return false;
  memset(&a, 0, sizeof(a));
  a.qp_state = IBV_QPS_RTR;
  a.path_mtu = pa.active_mtu;
  a.dest_qp_num = dest;
  a.rq_psn = 0;
  a.max_dest_rd_atomic = 1;
  a.min_rnr_timer = 12;
  a.ah_attr.port_num = 1;
  if (eth) {
    a.ah_attr.is_global = 1;
    a.ah_attr.grh.dgid = gid;
    a.ah_attr.grh.sgid_index = (uint8_t)gidIndex;
    a.ah_attr.grh.hop_limit = 255;
  } else {
    a.ah_attr.dlid = pa.lid;
  }
  if (ibv_modify_qp(q, &a, IBV_QP_STATE | IBV_QP_AV | IBV_QP_PATH_MTU | IBV_QP_DEST_QPN | IBV_QP_RQ_PSN |
                             IBV_QP_MAX_DEST_RD_ATOMIC | IBV_QP_MIN_RNR_TIMER) != 0)
    return false;
  memset(&a, 0, sizeof(a));
  a.qp_state = IBV_QPS_RTS;
  a.timeout = 14;
  a.retry_cnt = 7;
  a.rnr_retry = 7;
  a.sq_psn = 0;
  a.max_rd_atomic = 1;
  return ibv_modify_qp(q, &a, IBV_QP_STATE | IBV_QP_TIMEOUT | IBV_QP_RETRY_CNT | IBV_QP_RNR_RETRY | IBV_QP_SQ_PSN |
                                  IBV_QP_MAX_QP_RD_ATOMIC) == 0;
}

// wait for the signaled request `id` (2 s bound); false on an error completion or the bound (g_nic.err says which)
static bool nicWait(uint64_t id) {
  const double t0 = nowMs();
  ibv_wc wc[4];
  while (nowMs() - t0 < 2000.0) {
    const int n = ibv_poll_cq(g_nic.cq, 4, wc);
    if (n < 0) {
      snprintf(g_nic.err, sizeof(g_nic.err), "ibv_poll_cq failed");
      return false;
    }
    for (int k = 0; k < n; k++) {
      if (wc[k].status != IBV_WC_SUCCESS) {
        snprintf(g_nic.err, sizeof(g_nic.err), "completion status %d (%s) vendor_err %#x", (int)wc[k].status,
                 ibv_wc_status_str(wc[k].status), wc[k].vendor_err);
        return false;
      }
      if (wc[k].wr_id == id) return true;
    }
  }
  snprintf(g_nic.err, sizeof(g_nic.err), "no completion within 2000 ms");
  return false;
}

static bool nicPost(bool write, uintptr_t dev, size_t n) {
  if (dev < g_nic.lo || dev + n > g_nic.hi || n > 1024) {
    snprintf(g_nic.err, sizeof(g_nic.err), "address outside the GPU MR");
    return false;
  }
  const uint64_t id = g_nic.nextId++;
  ibv_sge sg, fsg;
  ibv_send_wr wr, fwr, *bad = nullptr;
  memset(&wr, 0, sizeof(wr));
  memset(&fwr, 0, sizeof(fwr));
  sg.addr = (uint64_t)(uintptr_t)(g_nic.stage + (write ? 0 : 128));
  sg.length = (uint32_t)n;
  sg.lkey = g_nic.stageMr->lkey;
  wr.wr_id = id;
  wr.sg_list = &sg;
  wr.num_sge = 1;
  wr.opcode = write ? IBV_WR_RDMA_WRITE : IBV_WR_RDMA_READ;
  wr.send_flags = write ? 0 : IBV_SEND_SIGNALED;
  wr.wr.rdma.remote_addr = (uint64_t)dev;
  wr.wr.rdma.rkey = g_nic.gpuMr->rkey;
  if (write) {  // the flushing 8-byte READ of the same MR, as gdakiLbXfer
    uintptr_t fa = dev & ~(uintptr_t)7;
    if (fa < g_nic.lo || fa + 8 > g_nic.hi) fa = g_nic.lo;
    fsg.addr = (uint64_t)(uintptr_t)(g_nic.stage + 64);
    fsg.length = 8;
    fsg.lkey = g_nic.stageMr->lkey;
    fwr.wr_id = id;
    fwr.sg_list = &fsg;
    fwr.num_sge = 1;
    fwr.opcode = IBV_WR_RDMA_READ;
    fwr.send_flags = IBV_SEND_SIGNALED;
    fwr.wr.rdma.remote_addr = (uint64_t)fa;
    fwr.wr.rdma.rkey = g_nic.gpuMr->rkey;
    wr.next = &fwr;
  }
  if (ibv_post_send(g_nic.qa, &wr, &bad) != 0) {
    snprintf(g_nic.err, sizeof(g_nic.err), "ibv_post_send failed (errno %d)", errno);
    return false;
  }
  g_nic.ops++;
  return nicWait(id);
}

static cudaStream_t g_ks = nullptr, g_hs = nullptr;
static Dev* g_dev = nullptr;

// a NIC request failed inside a phase: stop the kernel with a stream copy (not the NIC), record, exit 3
[[noreturn]] static void nicFail() {
  g_nic.errors++;
  kvf("nic_error=\"%s\" nic_ops=%llu nic_errors=%llu\n", g_nic.err, g_nic.ops, g_nic.errors);
  static unsigned int one = 1;
  if (cudaMemcpyAsync(&g_dev->stop, &one, 4, cudaMemcpyHostToDevice, g_hs) == cudaSuccess) {
    (void)cudaStreamSynchronize(g_hs);
    (void)cudaStreamSynchronize(g_ks);
  }
  kvf("result=FAIL exit=3\n");
  _exit(3);
}
static void h2d4(void* dst, uint32_t v) {
  memcpy(g_nic.stage, &v, 4);
  if (!nicPost(true, (uintptr_t)dst, 4)) nicFail();
}
static void d2h(void* dst, const void* src, size_t n) {
  if (!nicPost(false, (uintptr_t)src, n)) nicFail();
  memcpy(dst, g_nic.stage + 128, n);
}

static bool phase(const char* label, int blocks, int tpb, unsigned workNs, double secs, unsigned int* entered) {
  Dev* d = g_dev;
  CK(cudaMemset(d, 0, sizeof(Dev)));
  CK(cudaMemset(entered, 0, sizeof(unsigned int) * MAXK));
  CK(cudaDeviceSynchronize());
  hammer<<<blocks, tpb, 0, g_ks>>>(d, entered, workNs);
  CK(cudaGetLastError());
  const double tStart = nowMs();
  while (nowMs() - tStart < 200) {
  }
  uint8_t* hiHalf = (uint8_t*)&d->gate + 4;  // little endian: the epoch half
  uint32_t epoch = 0;
  long rounds = 0, lostWrite = 0, dekker = 0, insideNonZero = 0, quiesceTimeouts = 0;
  std::vector<double> qms;
  const double tEnd = nowMs() + secs * 1000.0;
  while (nowMs() < tEnd && epoch / 2 + 2 < (uint32_t)MAXK) {
    const uint32_t odd = epoch + 1;
    const double q0 = nowMs();
    h2d4(hiHalf, odd);
    uint64_t w = 0;
    bool zero = false;
    // wait for count == 0 with the odd epoch in the same 8-byte read; a lost write is counted and written again
    while (nowMs() - q0 < 2000) {
      d2h(&w, &d->gate, 8);
      if ((uint32_t)(w >> 32) != odd) {
        lostWrite++;
        h2d4(hiHalf, odd);
        continue;
      }
      if ((uint32_t)w == 0) {
        zero = true;
        break;
      }
    }
    if (!zero) {
      quiesceTimeouts++;
      break;
    }
    qms.push_back(nowMs() - q0);
    uint32_t snap = 0, ins = 0;
    d2h(&snap, &entered[(epoch >> 1) & (MAXK - 1)], 4);
    d2h(&ins, &d->inside, 4);
    if (ins != 0) insideNonZero++;
    const double h0 = nowMs();
    while (nowMs() - h0 < 0.2) {
      d2h(&ins, &d->inside, 4);
      if (ins != 0) insideNonZero++;
    }
    uint32_t snap2 = 0;
    d2h(&snap2, &entered[(epoch >> 1) & (MAXK - 1)], 4);
    if (snap2 != snap) dekker++;
    epoch = odd + 1;
    h2d4(hiHalf, epoch);
    for (int k = 0; k < 100; k++) {  // read back; a lost write is counted and written again
      d2h(&w, &d->gate, 8);
      if ((uint32_t)(w >> 32) == epoch) break;
      lostWrite++;
      h2d4(hiHalf, epoch);
    }
    const double s0 = nowMs();
    const double stableMs = 0.05 + (rounds % 7) * 0.1;
    while (nowMs() - s0 < stableMs) {
    }
    uint32_t snap3 = 0;
    d2h(&snap3, &entered[((odd - 1) >> 1) & (MAXK - 1)], 4);
    if (snap3 != snap) dekker++;
    rounds++;
  }
  // stop: a 4-byte NIC write next to the device's 32-bit atomics on `inside` (same 8 bytes), read back like the epochs
  h2d4(&d->stop, 1u);
  for (int k = 0; k < 100; k++) {
    uint32_t st = 0;
    d2h(&st, &d->stop, 4);
    if (st == 1u) break;
    lostWrite++;
    h2d4(&d->stop, 1u);
  }
  CK(cudaStreamSynchronize(g_ks));
  Dev hd;
  CK(cudaMemcpy(&hd, d, sizeof(Dev), cudaMemcpyDeviceToHost));
  const uint32_t finalHi = (uint32_t)(hd.gate >> 32), finalLo = (uint32_t)hd.gate;
  std::sort(qms.begin(), qms.end());
  auto pct = [&](double p) { return qms.empty() ? -1.0 : qms[(size_t)(p * (qms.size() - 1) + 0.5)]; };
  // a pass also needs evidence that the test ran: rounds done, threads entered, and threads that saw an odd epoch the NIC
  // wrote (backouts), with the final high half read by cudaMemcpy (not the NIC) equal to the last NIC write
  const bool idxOk = hd.idx0 == hd.enters && hd.idx1 == hd.enters;  // no lost update of the line's index words
  const bool ok = finalLo == 0 && finalHi == epoch && lostWrite == 0 && dekker == 0 && insideNonZero == 0 &&
                  quiesceTimeouts == 0 && idxOk && rounds > 0 && hd.enters > 0 && hd.backouts > 0;
  kvf("%s_blocks=%d %s_tpb=%d %s_work_ns=%u %s_secs=%.1f %s_rounds=%ld %s_enters=%llu %s_backouts=%llu %s_max_count=%llu "
      "%s_lost_writes=%ld %s_final_hi=%u %s_expected_hi=%u %s_final_count=%u %s_lost_inc=%d %s_dekker=%ld "
      "%s_inside_nonzero=%ld %s_quiesce_timeouts=%ld %s_idx_ok=%d %s_q_p50_ms=%.3f %s_q_p99_ms=%.3f %s_q_max_ms=%.3f "
      "%s_result=%s\n",
      label, blocks, label, tpb, label, workNs, label, secs, label, rounds, label, hd.enters, label, hd.backouts, label,
      hd.maxCount, label, lostWrite, label, finalHi, label, epoch, label, finalLo, label, finalLo != 0 ? 1 : 0, label,
      dekker, label, insideNonZero, label, quiesceTimeouts, label, idxOk ? 1 : 0, label, pct(0.5), label, pct(0.99), label,
      qms.empty() ? -1.0 : qms.back(), label, ok ? "PASS" : "FAIL");
  return ok;
}

int main(int argc, char** argv) {
  if (argc < 3) {
    fprintf(stderr, "usage: %s <out_kv> <ib_dev> [secs] [gid_index] [cuda_device]\n", argv[0]);
    return 2;
  }
  g_kv = fopen(argv[1], "w");
  if (g_kv == nullptr) return 2;
  const char* devName = argv[2];
  const double secs = argc > 3 ? atof(argv[3]) : 5.0;
  int gidIndex = argc > 4 ? atoi(argv[4]) : -1;
  const int cudaDev = argc > 5 ? atoi(argv[5]) : 0;
  if (!(secs > 0 && secs <= 20)) setupFail("secs must be in (0, 20]");
  std::thread([]() {
    std::this_thread::sleep_for(std::chrono::seconds(75));
    static const char m[] = "WATCHDOG: nic_gate_test exceeded 75 s; exiting 7\n";
    ssize_t k = write(2, m, sizeof(m) - 1);
    (void)k;
    if (g_kv) {
      fprintf(g_kv, "watchdog=1 exit=7\n");
      fflush(g_kv);
    }
    _exit(7);
  }).detach();
  CK(cudaSetDevice(cudaDev));
  CK(cudaFree(nullptr));
  cudaDeviceProp prop;
  CK(cudaGetDeviceProperties(&prop, cudaDev));
  for (char* c = prop.name; *c; c++)
    if (*c == ' ') *c = '_';
  kvf("name=%s cc=%d.%d ib_dev=%s\n", prop.name, prop.major, prop.minor, devName);
  void* base = nullptr;
  CK(cudaMalloc(&base, ALLOC));
  CK(cudaMemset(base, 0, ALLOC));
  CK(cudaDeviceSynchronize());
  if (((uintptr_t)base & 0xfff) != 0) setupFail("the GPU allocation is not page aligned");
  g_dev = (Dev*)base;
  unsigned int* entered = (unsigned int*)((uint8_t*)base + ENTERED_OFF);
  CK(cudaStreamCreateWithFlags(&g_ks, cudaStreamNonBlocking));
  CK(cudaStreamCreateWithFlags(&g_hs, cudaStreamNonBlocking));

  // the HCA, its own PD, CQ, two RC QPs
  int nd = 0;
  ibv_device** list = ibv_get_device_list(&nd);
  if (list == nullptr) setupFail("ibv_get_device_list");
  for (int i = 0; i < nd && g_nic.ctx == nullptr; i++)
    if (strcmp(ibv_get_device_name(list[i]), devName) == 0) g_nic.ctx = ibv_open_device(list[i]);
  ibv_free_device_list(list);
  if (g_nic.ctx == nullptr) setupFail("cannot open the HCA");
  ibv_port_attr pa;
  if (ibv_query_port(g_nic.ctx, 1, &pa) != 0) setupFail("ibv_query_port");
  const bool eth = pa.link_layer == IBV_LINK_LAYER_ETHERNET;
  g_nic.pd = ibv_alloc_pd(g_nic.ctx);
  if (g_nic.pd == nullptr) setupFail("ibv_alloc_pd");
  g_nic.cq = ibv_create_cq(g_nic.ctx, 64, nullptr, nullptr, 0);
  if (g_nic.cq == nullptr) setupFail("ibv_create_cq");
  ibv_qp_init_attr ia;
  memset(&ia, 0, sizeof(ia));
  ia.send_cq = g_nic.cq;
  ia.recv_cq = g_nic.cq;
  ia.qp_type = IBV_QPT_RC;
  ia.cap.max_send_wr = 16;
  ia.cap.max_recv_wr = 1;
  ia.cap.max_send_sge = 1;
  ia.cap.max_recv_sge = 1;
  g_nic.qa = ibv_create_qp(g_nic.pd, &ia);
  g_nic.qb = ibv_create_qp(g_nic.pd, &ia);
  if (g_nic.qa == nullptr || g_nic.qb == nullptr) setupFail("ibv_create_qp");
  ibv_gid gid;
  memset(&gid, 0, sizeof(gid));
  const char* gidKind = "lid";
  if (eth) {
    if (gidIndex < 0) {
      for (int k = 0; k < pa.gid_tbl_len; k++) {
        uint8_t g[16];
        char type[32];
        if (!sysfsGid(devName, k, g, type, sizeof(type))) continue;
        if (g[0] == 0xfe && (g[1] & 0xc0) == 0x80 && strcmp(type, "RoCE v2") == 0) {
          gidIndex = k;
          gidKind = "link-local";
          break;
        }
      }
      if (gidIndex < 0) setupFail("no link-local RoCE v2 GID");
    } else {
      gidKind = "given";
    }
    if (ibv_query_gid(g_nic.ctx, 1, gidIndex, &gid) != 0) setupFail("ibv_query_gid");
  }
  if (!connectQp(g_nic.qa, g_nic.qb->qp_num, pa, eth, gidIndex, gid) ||
      !connectQp(g_nic.qb, g_nic.qa->qp_num, pa, eth, gidIndex, gid))
    setupFail("cannot connect the loopback QPs");
  // the MRs: host staging, the GPU allocation (dmabuf, else nvidia-peermem); strict ordering (no relaxed ordering flag)
  if (posix_memalign((void**)&g_nic.stage, 4096, 4096) != 0) setupFail("posix_memalign");
  memset(g_nic.stage, 0, 4096);
  g_nic.stageMr = ibv_reg_mr(g_nic.pd, g_nic.stage, 4096, IBV_ACCESS_LOCAL_WRITE);
  if (g_nic.stageMr == nullptr) setupFail("ibv_reg_mr (staging)");
  const int access = IBV_ACCESS_LOCAL_WRITE | IBV_ACCESS_REMOTE_READ | IBV_ACCESS_REMOTE_WRITE;
  const char* mrKind = "dmabuf";
  int fd = -1;
  if (cuMemGetHandleForAddressRange((void*)&fd, (CUdeviceptr)base, ALLOC, CU_MEM_RANGE_HANDLE_TYPE_DMA_BUF_FD, 0) ==
        CUDA_SUCCESS &&
      fd >= 0) {
    g_nic.gpuMr = ibv_reg_dmabuf_mr(g_nic.pd, 0, ALLOC, (uint64_t)(uintptr_t)base, fd, access);
    close(fd);
  }
  if (g_nic.gpuMr == nullptr) {
    mrKind = "peermem";
    g_nic.gpuMr = ibv_reg_mr(g_nic.pd, base, ALLOC, access);
  }
  if (g_nic.gpuMr == nullptr) setupFail("cannot register the GPU memory");
  g_nic.lo = (uintptr_t)base;
  g_nic.hi = (uintptr_t)base + ALLOC;
  kvf("link=%s gid_index=%d gid_kind=%s mr=%s mtu=%d\n", eth ? "eth" : "ib", gidIndex, gidKind, mrKind,
      (int)pa.active_mtu);
  // a loopback self-check before the phases: write a pattern over the NIC, read it back over the NIC and by cudaMemcpy
  {
    const uint32_t pat = 0x6e676174u;
    uint32_t back = 0, viaCuda = 0;
    memcpy(g_nic.stage, &pat, 4);
    if (!nicPost(true, (uintptr_t)&g_dev->pad1[0], 4)) {
      kvf("setup_error=\"loopback self-check: %s\" exit=2\n", g_nic.err);
      _exit(2);
    }
    if (!nicPost(false, (uintptr_t)&g_dev->pad1[0], 4)) {
      kvf("setup_error=\"loopback self-check: %s\" exit=2\n", g_nic.err);
      _exit(2);
    }
    memcpy(&back, g_nic.stage + 128, 4);
    CK(cudaMemcpy(&viaCuda, &g_dev->pad1[0], 4, cudaMemcpyDeviceToHost));
    if (back != pat || viaCuda != pat) setupFail("loopback self-check: the pattern did not round-trip");
  }
  const bool a = phase("a", 64, 256, 0, secs, entered);
  const bool b = phase("b", 8, 256, 2000, secs, entered);
  const bool ok = a && b;
  kvf("nic_ops=%llu nic_errors=%llu result=%s exit=%d\n", g_nic.ops, g_nic.errors, ok ? "PASS" : "FAIL", ok ? 0 : 1);
  ibv_destroy_qp(g_nic.qa);
  ibv_destroy_qp(g_nic.qb);
  ibv_destroy_cq(g_nic.cq);
  ibv_dereg_mr(g_nic.gpuMr);
  ibv_dereg_mr(g_nic.stageMr);
  ibv_dealloc_pd(g_nic.pd);
  ibv_close_device(g_nic.ctx);
  fclose(g_kv);
  return ok ? 0 : 1;
}
