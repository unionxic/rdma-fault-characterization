// hm_bench.cu - gin-remaining (EXPERIMENT.md 9, 4): what a recovery gate in host memory would cost, and whether a host
// store and a device atomic on the same host word are atomic with each other. One GPU, no NCCL, no network. Every phase is
// bounded (a fixed number of operations) and a host watchdog exits 7 after 60 s.
//
// usage: hm_bench <out_kv> [cuda_device (0)] [n_lat (20000)] [race_ms (2000)]
// kv (one line per key group):
//   name, cc, host_native_atomic (cudaDevAttrHostNativeAtomicSupported), can_map_host, clock_khz
//   lat_<kind>_ns: mean ns per operation of ONE thread doing n_lat dependent operations (each address depends on the
//     previous result), timed with %globaltimer:
//       dev_atom       atom.add.gpu (64-bit) on device memory: what the gate word does today, once on entry and once on
//                      leave of every post and wait
//       host_atom      atom.add.gpu on host-pinned mapped memory (cudaHostAllocMapped): the same word in host memory
//       host_atom_sys  atom.add.sys on host-pinned mapped memory
//       dev_ld         ld.relaxed.sys on device memory
//       host_ld        ld.relaxed.sys on host-pinned mapped memory: a poll of a host word
//   race (the gate word protocol with the word in host memory): 64 device threads each add 1 then subtract 1 on the
//     64-bit word (atom.add.sys, the count half) until the host stops them, while the host writes the high half (a 4-byte
//     store) with a new value about every 20 us and reads it back 64 times after each write. A read-back that is not the
//     value just written is a host write a device read-modify-write put back (lost). race_host_writes,
//     race_lost_host_writes, race_dev_ops, race_final_low (0 unless a device update was lost), race_ms, race_rc.
// exit: 0 done; 6 CUDA error; 7 watchdog; 1 usage.
#include <cuda_runtime.h>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <thread>
#include <unistd.h>

static FILE* g_kv = nullptr;
#define CK(c)                                                                     \
  do {                                                                            \
    cudaError_t e_ = (c);                                                         \
    if (e_ != cudaSuccess) {                                                      \
      fprintf(stderr, "CUDA %s:%d %s\n", __FILE__, __LINE__, cudaGetErrorString(e_)); \
      if (g_kv) fprintf(g_kv, "cuda_error=%s\n", cudaGetErrorString(e_));         \
      if (g_kv) fflush(g_kv);                                                     \
      _exit(6);                                                                   \
    }                                                                             \
  } while (0)

__device__ __forceinline__ unsigned long long gt() {
  unsigned long long t;
  asm volatile("mov.u64 %0, %%globaltimer;" : "=l"(t));
  return t;
}

// one thread, n dependent operations of `kind` on p (the next address depends on the previous result: bit 62 is never set)
__global__ void latKernel(unsigned long long* p, int n, int kind, unsigned long long* out) {
  unsigned long long v = 0, sum = 0;
  const unsigned long long t0 = gt();
  for (int i = 0; i < n; i++) {
    unsigned long long* a = p + ((v >> 62) & 1ull);
    switch (kind) {
      case 0:
      case 1:
        asm volatile("atom.add.gpu.global.u64 %0, [%1], 1;" : "=l"(v) : "l"(a) : "memory");
        break;
      case 2:
        asm volatile("atom.add.sys.global.u64 %0, [%1], 1;" : "=l"(v) : "l"(a) : "memory");
        break;
      default:
        asm volatile("ld.relaxed.sys.global.u64 %0, [%1];" : "=l"(v) : "l"(a) : "memory");
        break;
    }
    sum += v;
  }
  out[0] = gt() - t0;
  out[1] = sum;
}

// the gate word in host memory: +1 then -1 (atom.add.sys) until *stop or maxOps per thread
__global__ void raceKernel(unsigned long long* w, volatile int* stop, unsigned long long maxOps, unsigned long long* ops) {
  unsigned long long n = 0, v = 0;
  while (n < maxOps) {
    if ((n & 255) == 0 && *stop) break;
    // as the gate word: entry is an atomic add that returns the word, leave a reduction of -1
    asm volatile("atom.add.sys.global.u64 %0, [%1], 1;" : "=l"(v) : "l"(w) : "memory");
    asm volatile("red.add.sys.global.u64 [%0], %1;" ::"l"(w), "l"(0xffffffffffffffffull) : "memory");
    n += 2 + (v >> 63);  // (bit 63 is never set: keeps the returned value used)
  }
  atomicAdd(ops, n);
}

int main(int argc, char** argv) {
  if (argc < 2) {
    fprintf(stderr, "usage: %s <out_kv> [cuda_device] [n_lat] [race_ms]\n", argv[0]);
    return 1;
  }
  g_kv = fopen(argv[1], "w");
  if (g_kv == nullptr) return 1;
  const int dev = argc > 2 ? atoi(argv[2]) : 0;
  const int nLat = argc > 3 ? atoi(argv[3]) : 20000;
  const int raceMs = argc > 4 ? atoi(argv[4]) : 2000;
  std::thread([]() {
    std::this_thread::sleep_for(std::chrono::seconds(60));
    static const char m[] = "WATCHDOG: hm_bench exceeded 60 s; exiting 7\n";
    ssize_t k = write(2, m, sizeof(m) - 1);
    (void)k;
    _exit(7);
  }).detach();
  CK(cudaSetDevice(dev));
  cudaDeviceProp prop;
  CK(cudaGetDeviceProperties(&prop, dev));
  int native = -1, canMap = -1, clk = 0;
  CK(cudaDeviceGetAttribute(&native, cudaDevAttrHostNativeAtomicSupported, dev));
  CK(cudaDeviceGetAttribute(&canMap, cudaDevAttrCanMapHostMemory, dev));
  CK(cudaDeviceGetAttribute(&clk, cudaDevAttrClockRate, dev));
  for (char* c = prop.name; *c; c++)
    if (*c == ' ') *c = '_';
  fprintf(g_kv, "name=%s cc=%d.%d host_native_atomic=%d can_map_host=%d clock_khz=%d n_lat=%d\n", prop.name, prop.major,
          prop.minor, native, canMap, clk, nLat);
  fflush(g_kv);
  unsigned long long *dWord = nullptr, *hWord = nullptr, *hWordDev = nullptr, *dOut = nullptr, hOut[2];
  CK(cudaMalloc(&dWord, 2 * sizeof(unsigned long long)));
  CK(cudaMemset(dWord, 0, 2 * sizeof(unsigned long long)));
  CK(cudaHostAlloc((void**)&hWord, 2 * sizeof(unsigned long long), cudaHostAllocMapped));
  memset(hWord, 0, 2 * sizeof(unsigned long long));
  CK(cudaHostGetDevicePointer((void**)&hWordDev, hWord, 0));
  CK(cudaMalloc(&dOut, 2 * sizeof(unsigned long long)));
  const char* names[] = {"dev_atom", "host_atom", "host_atom_sys", "dev_ld", "host_ld"};
  for (int k = 0; k < 5; k++) {
    const int kind = k == 3 || k == 4 ? 3 : k;
    unsigned long long* p = (k == 0 || k == 3) ? dWord : hWordDev;
    latKernel<<<1, 1>>>(p, 64, kind, dOut);  // warm-up
    CK(cudaDeviceSynchronize());
    latKernel<<<1, 1>>>(p, nLat, kind, dOut);
    CK(cudaDeviceSynchronize());
    CK(cudaMemcpy(hOut, dOut, sizeof(hOut), cudaMemcpyDeviceToHost));
    fprintf(g_kv, "lat_%s_ns=%.1f\n", names[k], (double)hOut[0] / nLat);
    fflush(g_kv);
  }
  // race
  unsigned long long *rw = nullptr, *rwDev = nullptr, *dOps = nullptr;
  int *stop = nullptr, *stopDev = nullptr;
  CK(cudaHostAlloc((void**)&rw, sizeof(unsigned long long), cudaHostAllocMapped));
  CK(cudaHostAlloc((void**)&stop, sizeof(int), cudaHostAllocMapped));
  CK(cudaHostGetDevicePointer((void**)&rwDev, rw, 0));
  CK(cudaHostGetDevicePointer((void**)&stopDev, stop, 0));
  CK(cudaMalloc(&dOps, sizeof(unsigned long long)));
  CK(cudaMemset(dOps, 0, sizeof(unsigned long long)));
  *rw = 0;
  *(volatile int*)stop = 0;
  cudaStream_t s;
  CK(cudaStreamCreateWithFlags(&s, cudaStreamNonBlocking));
  raceKernel<<<2, 32, 0, s>>>(rwDev, stopDev, 4000000ull, dOps);
  CK(cudaGetLastError());
  volatile uint32_t* hi = ((volatile uint32_t*)rw) + 1;
  unsigned long long writes = 0, lost = 0;
  uint32_t v = 0;
  const auto t0 = std::chrono::steady_clock::now();
  while (std::chrono::steady_clock::now() - t0 < std::chrono::milliseconds(raceMs)) {
    v += 2;
    std::atomic_thread_fence(std::memory_order_seq_cst);
    *hi = v;
    std::atomic_thread_fence(std::memory_order_seq_cst);
    writes++;
    bool bad = false;
    for (int k = 0; k < 64; k++)
      if (*hi != v) bad = true;
    if (bad) lost++;
    std::this_thread::sleep_for(std::chrono::microseconds(20));
  }
  *(volatile int*)stop = 1;
  std::atomic_thread_fence(std::memory_order_seq_cst);
  const cudaError_t re = cudaStreamSynchronize(s);
  const double ms =
    std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
  unsigned long long ops = 0;
  if (re == cudaSuccess) CK(cudaMemcpy(&ops, dOps, sizeof(ops), cudaMemcpyDeviceToHost));
  fprintf(g_kv, "race_host_writes=%llu race_lost_host_writes=%llu race_dev_ops=%llu race_final_low=%u race_ms=%.1f race_rc=%s\n",
          writes, lost, ops, (unsigned)(*(volatile uint32_t*)rw), ms, cudaGetErrorName(re));
  fprintf(g_kv, "exit=0\n");
  fclose(g_kv);
  return 0;
}
