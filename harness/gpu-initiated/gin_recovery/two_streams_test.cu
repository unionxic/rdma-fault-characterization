// two_streams_test.cu - do two 1-block kernels on two non-blocking streams run at the same time on this GPU?
// Launches a kernel that spins for <spin_ms> on stream A, then a trivial kernel on stream B, and reports when each
// finished (CUDA events, ms after a start event). Concurrent: quick_end_ms << spin_ms. Serialized: about equal.
// The kernels can be given a stack frame (local memory) of their own: the GIN receiver kernel has a 248 B frame and
// the GIN sender kernel 592 B (gin_bidir_min.cu), and a launch that needs more local memory than the device has
// reserved may wait for the running kernels.
// usage: two_streams_test [spin_ms=2000] [order=spinfirst|quickfirst] [spin_stack=0|256|1024|4096] [quick_stack=0|...]
//        [stack_limit=0 (cudaDeviceSetLimit(cudaLimitStackSize) before the launches)]
#include <cuda_runtime.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>

__device__ __forceinline__ unsigned long long gtNow() {
  unsigned long long t;
  asm volatile("mov.u64 %0, %%globaltimer;" : "=l"(t));
  return t;
}
// a stack frame of N bytes: a local array indexed at run time (not optimizable into registers)
template <int N>
__device__ __noinline__ unsigned touchStack(unsigned seed) {
  volatile unsigned char buf[N > 0 ? N : 1];
  for (int i = 0; i < N; i++) buf[i] = (unsigned char)(seed + i);
  unsigned s = 0;
  for (int i = 0; i < N; i++) s += buf[(i * 7 + seed) % (N > 0 ? N : 1)];
  return s;
}
template <int N>
__global__ void spinKernel(unsigned long long ns, volatile unsigned long long* flag, unsigned* sink) {
  const unsigned long long t0 = gtNow();
  unsigned s = touchStack<N>(threadIdx.x);
  while (gtNow() - t0 < ns) { if (*flag == 0xdeadbeefull) break; }
  if (s == 0xffffffffu) *sink = s;
}
template <int N>
__global__ void quickKernel(unsigned long long* out, unsigned* sink) {
  unsigned s = touchStack<N>(threadIdx.x);
  *out = gtNow();
  if (s == 0xffffffffu) *sink = s;
}

typedef void (*SpinFn)(unsigned long long, volatile unsigned long long*, unsigned*);
typedef void (*QuickFn)(unsigned long long*, unsigned*);
static SpinFn spinFor(int n) { return n >= 4096 ? spinKernel<4096> : n >= 1024 ? spinKernel<1024> : n >= 256 ? spinKernel<256> : spinKernel<0>; }
static QuickFn quickFor(int n) { return n >= 4096 ? quickKernel<4096> : n >= 1024 ? quickKernel<1024> : n >= 256 ? quickKernel<256> : quickKernel<0>; }

int main(int argc, char** argv) {
  const long spinMs = argc > 1 ? atol(argv[1]) : 2000;
  const bool quickFirst = argc > 2 && strcmp(argv[2], "quickfirst") == 0;
  const int spinStack = argc > 3 ? atoi(argv[3]) : 0, quickStack = argc > 4 ? atoi(argv[4]) : 0;
  const long stackLimit = argc > 5 ? atol(argv[5]) : 0;
  cudaStream_t sA, sB;
  cudaStreamCreateWithFlags(&sA, cudaStreamNonBlocking);
  cudaStreamCreateWithFlags(&sB, cudaStreamNonBlocking);
  unsigned long long *flag, *out;
  unsigned* sink;
  cudaMalloc(&flag, 8); cudaMalloc(&out, 8); cudaMalloc(&sink, 4);
  cudaMemset(flag, 0, 8); cudaMemset(out, 0, 8);
  SpinFn sk = spinFor(spinStack);
  QuickFn qk = quickFor(quickStack);
  cudaFuncAttributes fs, fq;
  cudaFuncGetAttributes(&fs, (const void*)sk); cudaFuncGetAttributes(&fq, (const void*)qk);
  if (stackLimit > 0) cudaDeviceSetLimit(cudaLimitStackSize, (size_t)stackLimit);
  size_t lim = 0; cudaDeviceGetLimit(&lim, cudaLimitStackSize);
  cudaEvent_t e0, eSpin, eQuick;
  cudaEventCreate(&e0); cudaEventCreate(&eSpin); cudaEventCreate(&eQuick);
  cudaDeviceSynchronize();
  int dev = 0, conc = -1; cudaGetDevice(&dev);
  cudaDeviceGetAttribute(&conc, cudaDevAttrConcurrentKernels, dev);
  cudaDeviceProp p; cudaGetDeviceProperties(&p, dev);
  cudaEventRecord(e0, sA);
  const unsigned long long ns = (unsigned long long)spinMs * 1000000ull;
  if (!quickFirst) {
    sk<<<1, 256, 0, sA>>>(ns, flag, sink); cudaEventRecord(eSpin, sA);
    qk<<<1, 1, 0, sB>>>(out, sink); cudaEventRecord(eQuick, sB);
  } else {
    qk<<<1, 1, 0, sB>>>(out, sink); cudaEventRecord(eQuick, sB);
    sk<<<1, 256, 0, sA>>>(ns, flag, sink); cudaEventRecord(eSpin, sA);
  }
  cudaError_t e = cudaDeviceSynchronize();
  float tS = -1, tQ = -1;
  cudaEventElapsedTime(&tS, e0, eSpin); cudaEventElapsedTime(&tQ, e0, eQuick);
  const char* env1 = getenv("CUDA_LAUNCH_BLOCKING"); const char* env2 = getenv("CUDA_DEVICE_MAX_CONNECTIONS");
  printf("gpu=\"%s\" concurrent_kernels_attr=%d order=%s spin_ms=%ld spin_stack=%zu quick_stack=%zu stack_limit=%zu spin_end_ms=%.1f "
         "quick_end_ms=%.1f verdict=%s cuda_launch_blocking=%s max_connections=%s cuda_rc=%s\n", p.name, conc,
         quickFirst ? "quickfirst" : "spinfirst", spinMs, fs.localSizeBytes, fq.localSizeBytes, lim, tS, tQ,
         (tQ < tS * 0.5) ? "concurrent" : "serialized", env1 ? env1 : "-", env2 ? env2 : "-", cudaGetErrorString(e));
  return 0;
}
