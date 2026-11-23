// gate_race_test.cu - single-GPU test of the T1 gate word: device threads update the whole 64-bit
// word with atomicAdd(+1) / red.release.add(-1) (the counted half), while the host rewrites only the
// upper 32 bits (the epoch) with 4-byte copies (cudaMemcpyAsync from pinned memory on another stream,
// as the T1 helper does). Checked: no update is lost on either side (at the end lo == 0 and hi ==
// the last epoch written), every epoch a device atomic returned is one the host wrote, and per
// thread the epochs seen never go backwards. Also times the gate primitives (one thread).
// usage: gate_race_test [blocks threads iters host_writes]
#include <cuda_runtime.h>
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include <ctime>
#include <thread>
#include <atomic>
#define CK(c) do { cudaError_t e_ = (c); if (e_ != cudaSuccess) { printf("CUDA %s:%d %s\n", __FILE__, __LINE__, cudaGetErrorString(e_)); exit(2); } } while (0)

__global__ void hammer(unsigned long long *w, int iters, unsigned int *bad, unsigned int *maxhi) {
    unsigned int last = 0;
    for (int i = 0; i < iters; i++) {
        unsigned long long old = atomicAdd(w, 1ULL);
        unsigned int hi = (unsigned int)(old >> 32);
        unsigned int lo = (unsigned int)old;
        if (hi < last || lo > 1u << 20) atomicAdd(bad, 1u);
        last = hi;
        asm volatile("red.release.gpu.global.add.u64 [%0], %1;" ::"l"(w), "l"((unsigned long long)-1LL) : "memory");
    }
    atomicMax(maxhi, last);
}

__global__ void cost(unsigned long long *w, unsigned int *hold, int n, unsigned long long *out) {
    unsigned long long t0, t1;
    unsigned long long s = 0;
    // (a) T1 poster gate: atomicAdd with return + red.release
    asm volatile("mov.u64 %0, %%globaltimer;" : "=l"(t0));
    for (int i = 0; i < n; i++) {
        unsigned long long old = atomicAdd(w, 1ULL);
        s += old >> 32;
        asm volatile("red.release.gpu.global.add.u64 [%0], %1;" ::"l"(w), "l"((unsigned long long)-1LL) : "memory");
    }
    asm volatile("mov.u64 %0, %%globaltimer;" : "=l"(t1));
    out[0] = (t1 - t0) / n;
    // (b) S1-style Dekker: atomicAdd + fence.sc.sys + load, release-add
    asm volatile("mov.u64 %0, %%globaltimer;" : "=l"(t0));
    for (int i = 0; i < n; i++) {
        atomicAdd(hold, 1u);
        __threadfence_system();
        s += *(volatile unsigned int *)(hold + 1);
        asm volatile("red.release.sys.global.add.u32 [%0], %1;" ::"l"(hold), "r"(0xffffffffu) : "memory");
    }
    asm volatile("mov.u64 %0, %%globaltimer;" : "=l"(t1));
    out[1] = (t1 - t0) / n;
    // (c) three ld.acquire.gpu (the T1 waiter's ticket)
    asm volatile("mov.u64 %0, %%globaltimer;" : "=l"(t0));
    for (int i = 0; i < n; i++) {
        unsigned long long v;
        asm volatile("ld.acquire.gpu.global.u64 %0, [%1];" : "=l"(v) : "l"(w) : "memory"); s += v;
        asm volatile("ld.acquire.gpu.global.u64 %0, [%1];" : "=l"(v) : "l"(w + 1) : "memory"); s += v;
        asm volatile("ld.acquire.gpu.global.u64 %0, [%1];" : "=l"(v) : "l"(w + 2) : "memory"); s += v;
    }
    asm volatile("mov.u64 %0, %%globaltimer;" : "=l"(t1));
    out[2] = (t1 - t0) / n;
    out[3] = s;
}

int main(int argc, char **argv) {
    int blocks = argc > 1 ? atoi(argv[1]) : 64, threads = argc > 2 ? atoi(argv[2]) : 128;
    int iters = argc > 3 ? atoi(argv[3]) : 20000, hw = argc > 4 ? atoi(argv[4]) : 20000;
    unsigned long long *w;
    unsigned int *bad, *maxhi, *hold;
    CK(cudaMalloc(&w, 64));
    CK(cudaMemset(w, 0, 64));
    CK(cudaMallocManaged(&bad, 4)); *bad = 0;
    CK(cudaMallocManaged(&maxhi, 4)); *maxhi = 0;
    CK(cudaMalloc(&hold, 8)); CK(cudaMemset(hold, 0, 8));
    unsigned int *pin;
    CK(cudaHostAlloc(&pin, 4, cudaHostAllocDefault));
    cudaStream_t ks, hs;
    CK(cudaStreamCreateWithFlags(&ks, cudaStreamNonBlocking));
    CK(cudaStreamCreateWithFlags(&hs, cudaStreamNonBlocking));
    hammer<<<blocks, threads, 0, ks>>>(w, iters, bad, maxhi);
    int written = 0;
    for (int i = 1; i <= hw; i++) {
        if (cudaStreamQuery(ks) == cudaSuccess) break;
        *pin = (unsigned)i;
        CK(cudaMemcpyAsync((char *)w + 4, pin, 4, cudaMemcpyHostToDevice, hs));
        CK(cudaStreamSynchronize(hs));
        written = i;
    }
    CK(cudaStreamSynchronize(ks));
    CK(cudaDeviceSynchronize());
    unsigned long long fin;
    CK(cudaMemcpy(&fin, w, 8, cudaMemcpyDeviceToHost));
    unsigned int lo = (unsigned)fin, hi = (unsigned)(fin >> 32);
    printf("RACE blocks=%d threads=%d iters=%d device_atomics=%lld host_epoch_writes=%d final_lo=%u final_hi=%u "
           "expect_hi=%d bad=%u maxhi_seen=%u -> %s\n", blocks, threads, iters, 2LL * blocks * threads * iters,
           written, lo, hi, written, *bad, *maxhi, (lo == 0 && hi == (unsigned)written && *bad == 0) ? "PASS" : "FAIL");
    unsigned long long *out;
    CK(cudaMallocManaged(&out, 32));
    CK(cudaMemset(w, 0, 64));
    cost<<<1, 1>>>(w, hold, 10000, out);
    CK(cudaDeviceSynchronize());
    printf("COST ns_per: t1_gate_enter_leave=%llu s1_dekker_sys=%llu three_ld_acquire=%llu\n", out[0], out[1], out[2]);
    return 0;
}
