// gate_ce_test.cu - targeted micro-test for the S2 gate word (GIN transparent recovery S2).
//
// The S2 gate is ONE 64-bit word per QP in GPU memory: epoch in the high 32 bits (written only by the host,
// as a 4-byte copy-engine write, exactly like the library: cudaMemcpyAsync from pinned memory on a
// non-blocking stream + cudaStreamSynchronize), a count in the low 32 bits (SM 64-bit atomics). A device
// thread enters with ONE atomic add whose return value carries the epoch (single-location check, no fence)
// and leaves with a release add of -1. The host quiesces with: write epoch odd (CE), then read the word (CE)
// until count == 0.
//
// What this test checks, with many threads hammering the word while the host runs the quiesce/publish
// cycle continuously:
//   lost CE write   the high half read back right after each host write must equal the value written
//                   (a 64-bit atomic RMW that raced the partial write and wrote back a stale high half
//                   would show here), and after the kernel ends the high half equals the last write;
//   lost increment  after the kernel ends the low half must be exactly 0 (every +1 had its -1);
//   Dekker          once the host has written epoch 2k+1 and then read count == 0, no thread may be
//                   inside with epoch 2k: every thread that entered with 2k increments entered[k] before
//                   its release decrement, so entered[k] read after count == 0 must never grow later;
//                   and `inside` (threads between enter and leave) must read 0 while the epoch is odd.
//
// usage: gate_ce_test <blocks> <threads/block> <seconds> <gpu|sys|cas> [work_ns]
//   gpu / sys: the entry is an atomic add at GPU / system scope; cas: a CAS loop (the S2 late-failure path)
// exit 0 = no violation of any kind; 1 = a violation; 2 = setup error.
#include <cuda_runtime.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cstdint>
#include <ctime>
#include <vector>
#include <algorithm>

#define CK(c)                                                                            \
  do {                                                                                   \
    cudaError_t e_ = (c);                                                                \
    if (e_ != cudaSuccess) {                                                             \
      fprintf(stderr, "CUDA %s:%d %s\n", __FILE__, __LINE__, cudaGetErrorString(e_));    \
      exit(2);                                                                           \
    }                                                                                    \
  } while (0)

static const int MAXK = 1 << 20;  // epochs tracked in entered[]

struct Dev {
  unsigned long long gate;      // the gate word under test (own 128-byte line below)
  unsigned long long pad0[15];
  unsigned int inside;          // threads between enter and leave (witness)
  unsigned int stop;            // host (CE) sets 1 to end the kernel
  unsigned int pad1[30];
  unsigned long long enters, backouts, iters, maxCount;  // statistics (atomics, own line)
};

template <int Mode>  // 0 gpu-scope add, 1 sys-scope add, 2 CAS loop (the S2 device failure path uses a CAS)
__device__ __forceinline__ unsigned long long gateEnter(unsigned long long* p) {
  unsigned long long old;
  if (Mode == 1) asm volatile("atom.acquire.sys.global.add.u64 %0, [%1], 1;" : "=l"(old) : "l"(p) : "memory");
  else if (Mode == 0) asm volatile("atom.acquire.gpu.global.add.u64 %0, [%1], 1;" : "=l"(old) : "l"(p) : "memory");
  else {
    old = *(volatile unsigned long long*)p;
    while (true) {
      const unsigned long long prev = atomicCAS(p, old, old + 1);
      if (prev == old) break;
      old = prev;
    }
    __threadfence();
  }
  return old;
}
template <int Mode>
__device__ __forceinline__ void gateLeave(unsigned long long* p) {
  if (Mode == 1) asm volatile("red.release.sys.global.add.u64 [%0], %1;" ::"l"(p), "l"(0xffffffffffffffffull) : "memory");
  else asm volatile("red.release.gpu.global.add.u64 [%0], %1;" ::"l"(p), "l"(0xffffffffffffffffull) : "memory");
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

template <int Mode>
__global__ void hammer(Dev* d, unsigned int* entered, unsigned int workNs) {
  unsigned long long enters = 0, backouts = 0, iters = 0, maxc = 0;
  while (true) {
    if ((iters & 63) == 0 && ldRelaxed32(&d->stop)) break;
    iters++;
    const unsigned long long old = gateEnter<Mode>(&d->gate);
    const unsigned int e = (unsigned int)(old >> 32), c = (unsigned int)old;
    if (c + 1 > maxc) maxc = c + 1;
    if (e & 1u) {  // a recovery owns the word: back out and park (no counter traffic while parked)
      gateLeave<Mode>(&d->gate);
      backouts++;
      while (((unsigned int)(ldRelaxed64(&d->gate) >> 32) & 1u) && !ldRelaxed32(&d->stop)) __nanosleep(200);
      continue;
    }
    // inside with even epoch e
    atomicAdd(&d->inside, 1u);
    atomicAdd(&entered[(e >> 1) & (MAXK - 1)], 1u);
    if (workNs) {
      const unsigned long long t0 = gtNow();
      while (gtNow() - t0 < workNs) {}
    }
    atomicSub(&d->inside, 1u);
    gateLeave<Mode>(&d->gate);  // release: the witness updates above are visible before the decrement
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

int main(int argc, char** argv) {
  if (argc < 5) {
    fprintf(stderr, "usage: %s <blocks> <threads/block> <seconds> <gpu|sys|cas> [work_ns]\n", argv[0]);
    return 2;
  }
  const int blocks = atoi(argv[1]), tpb = atoi(argv[2]);
  const double secs = atof(argv[3]);
  const int mode = strcmp(argv[4], "sys") == 0 ? 1 : strcmp(argv[4], "cas") == 0 ? 2 : 0;
  const unsigned workNs = argc > 5 ? (unsigned)atoi(argv[5]) : 0;
  CK(cudaSetDevice(0));
  cudaDeviceProp prop;
  CK(cudaGetDeviceProperties(&prop, 0));
  Dev* d = nullptr;
  unsigned int* entered = nullptr;
  CK(cudaMalloc(&d, sizeof(Dev)));
  CK(cudaMalloc(&entered, sizeof(unsigned int) * MAXK));
  CK(cudaMemset(d, 0, sizeof(Dev)));
  CK(cudaMemset(entered, 0, sizeof(unsigned int) * MAXK));
  CK(cudaDeviceSynchronize());
  // host side exactly as the library: a private non-blocking stream and pinned staging
  cudaStream_t hs, ks;
  CK(cudaStreamCreateWithFlags(&hs, cudaStreamNonBlocking));
  CK(cudaStreamCreateWithFlags(&ks, cudaStreamNonBlocking));
  uint8_t* pin = nullptr;
  CK(cudaHostAlloc((void**)&pin, 4096, cudaHostAllocDefault));
  auto h2d4 = [&](void* dst, uint32_t v) {
    memcpy(pin, &v, 4);
    CK(cudaMemcpyAsync(dst, pin, 4, cudaMemcpyHostToDevice, hs));
    CK(cudaStreamSynchronize(hs));
  };
  auto d2h = [&](void* dst, const void* src, size_t n) {
    CK(cudaMemcpyAsync(pin + 64, src, n, cudaMemcpyDeviceToHost, hs));
    CK(cudaStreamSynchronize(hs));
    memcpy(dst, pin + 64, n);
  };
  uint8_t* hiHalf = (uint8_t*)&d->gate + 4;  // little endian: the epoch half

  if (mode == 1) hammer<1><<<blocks, tpb, 0, ks>>>(d, entered, workNs);
  else if (mode == 2) hammer<2><<<blocks, tpb, 0, ks>>>(d, entered, workNs);
  else hammer<0><<<blocks, tpb, 0, ks>>>(d, entered, workNs);
  CK(cudaGetLastError());
  // let every thread start hammering
  const double tStart = nowMs();
  while (nowMs() - tStart < 200) {}

  uint32_t epoch = 0;
  long rounds = 0, lostWrite = 0, dekker = 0, insideNonZero = 0, quiesceTimeouts = 0, zeroReads = 0;
  std::vector<double> qms;  // time from the odd write to count == 0
  unsigned long long maxSeen = 0;
  const double tEnd = nowMs() + secs * 1000.0;
  while (nowMs() < tEnd && epoch / 2 + 2 < (uint32_t)MAXK) {
    // quiesce: epoch odd
    const uint32_t odd = epoch + 1;
    const double q0 = nowMs();
    h2d4(hiHalf, odd);
    uint64_t w = 0;
    d2h(&w, &d->gate, 8);
    if ((uint32_t)(w >> 32) != odd) lostWrite++;
    // wait for count == 0 (bounded 2 s)
    bool zero = false;
    while (nowMs() - q0 < 2000) {
      d2h(&w, &d->gate, 8);
      if ((uint32_t)(w >> 32) != odd) { lostWrite++; break; }
      if ((uint32_t)w > maxSeen) maxSeen = (uint32_t)w;
      if ((uint32_t)w == 0) { zero = true; break; }
    }
    if (!zero) { quiesceTimeouts++; break; }
    zeroReads++;
    qms.push_back(nowMs() - q0);
    // Dekker: with count == 0 seen after the odd write, nobody is inside with the old epoch, and nobody
    // may enter with it later
    uint32_t snap = 0, ins = 0;
    d2h(&snap, &entered[(epoch >> 1) & (MAXK - 1)], 4);
    d2h(&ins, &d->inside, 4);
    if (ins != 0) insideNonZero++;
    // hold the odd epoch a little (a recovery takes ms), re-checking the witnesses
    const double h0 = nowMs();
    while (nowMs() - h0 < 0.2) {
      d2h(&ins, &d->inside, 4);
      if (ins != 0) insideNonZero++;
    }
    uint32_t snap2 = 0;
    d2h(&snap2, &entered[(epoch >> 1) & (MAXK - 1)], 4);
    if (snap2 != snap) dekker++;
    // publish the next stable epoch
    epoch = odd + 1;
    h2d4(hiHalf, epoch);
    d2h(&w, &d->gate, 8);
    if ((uint32_t)(w >> 32) != epoch) lostWrite++;
    // run stable for a short random time so threads pile up in the next round
    const double s0 = nowMs();
    const double stableMs = 0.05 + (rounds % 7) * 0.1;
    while (nowMs() - s0 < stableMs) {}
    // the previous epoch's entered[] count must still equal the snapshot taken at count == 0
    uint32_t snap3 = 0;
    d2h(&snap3, &entered[((odd - 1) >> 1) & (MAXK - 1)], 4);
    if (snap3 != snap) dekker++;
    rounds++;
  }
  // stop the kernel
  h2d4(&d->stop, 1u);
  CK(cudaStreamSynchronize(ks));
  Dev hd;
  CK(cudaMemcpy(&hd, d, sizeof(Dev), cudaMemcpyDeviceToHost));
  const uint32_t finalHi = (uint32_t)(hd.gate >> 32), finalLo = (uint32_t)hd.gate;
  const bool lostInc = finalLo != 0;
  const bool finalHiBad = finalHi != epoch;
  std::sort(qms.begin(), qms.end());
  auto pct = [&](double p) { return qms.empty() ? -1.0 : qms[(size_t)(p * (qms.size() - 1) + 0.5)]; };
  const bool ok = !lostInc && !finalHiBad && lostWrite == 0 && dekker == 0 && insideNonZero == 0 && quiesceTimeouts == 0;
  printf("gate_ce_test gpu=\"%s\" sm=%d%d blocks=%d tpb=%d threads=%d scope=%s work_ns=%u secs=%.1f rounds=%ld "
         "enters=%llu backouts=%llu iters=%llu max_count_dev=%llu max_count_host=%llu "
         "lost_ce_writes=%ld final_hi=%u expected_hi=%u final_count=%u lost_increments=%d dekker_violations=%ld "
         "inside_nonzero_while_odd=%ld quiesce_timeouts=%ld quiesce_ms_p50=%.3f p99=%.3f max=%.3f result=%s\n",
         prop.name, prop.major, prop.minor, blocks, tpb, blocks * tpb, mode == 1 ? "sys" : mode == 2 ? "cas" : "gpu", workNs, secs, rounds,
         hd.enters, hd.backouts, hd.iters, hd.maxCount, maxSeen, lostWrite, finalHi, epoch, finalLo, lostInc ? 1 : 0,
         dekker, insideNonZero, quiesceTimeouts, pct(0.5), pct(0.99), qms.empty() ? -1.0 : qms.back(),
         ok ? "PASS" : "FAIL");
  return ok ? 0 : 1;
}
