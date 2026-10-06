// fill_copy_test.cu - does a host<->device copy (cudaMemcpyAsync on its own non-blocking stream,
// pinned host memory, cudaMalloc device memory) complete while a resident kernel occupies every SM
// thread slot? Used to explain the dci_fill cell of TRANSPARENT_T1.md.
//
//   fill_copy_test [ctas] [thread]   ctas: filler CTAs of 256 threads (default: every slot = SMs x 4 on
//   Turing); with a second argument the copies run from a second thread (cudaSetDevice first, its own
//   stream) while the main thread polls the filler's stream with cudaStreamQuery + usleep(1 ms), as
//   the T1 helper and the application's host thread do.
//
// Prints, for the idle GPU and then with the filler resident: the time of a 64-byte D2H copy, a
// 64-byte H2D copy, a 64 KiB D2H copy, and a D2H copy on the legacy (blocking) stream, each bounded
// by 3 s of polling. The filler stops by itself after 20 s (clock), so a stalled copy cannot hang it.
#include <cuda_runtime.h>
#include <cstdio>
#include <cstdlib>
#include <ctime>
#include <cuda.h>
#include <thread>
#include <unistd.h>

static double ms() {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec * 1e3 + t.tv_nsec * 1e-6;
}
#define CK(c)                                                                                 \
    do {                                                                                      \
        cudaError_t e_ = (c);                                                                 \
        if (e_ != cudaSuccess) {                                                              \
            fprintf(stderr, "CUDA %s:%d %s\n", __FILE__, __LINE__, cudaGetErrorString(e_));   \
            exit(1);                                                                          \
        }                                                                                     \
    } while (0)

__global__ void filler(volatile int *stop, unsigned long long max_ns) {
    unsigned long long t0;
    asm volatile("mov.u64 %0, %%globaltimer;" : "=l"(t0));
    if (threadIdx.x == 0) {
        for (;;) {
            if (*stop) break;
            unsigned long long t;
            asm volatile("mov.u64 %0, %%globaltimer;" : "=l"(t));
            if (t - t0 > max_ns) break;
            __nanosleep(200000);
        }
    }
    __syncthreads();
}

static const char *timed(cudaStream_t s, cudaError_t launch_err, double *out_ms) {
    if (launch_err != cudaSuccess) return cudaGetErrorString(launch_err);
    double t0 = ms();
    for (;;) {
        cudaError_t q = cudaStreamQuery(s);
        if (q == cudaSuccess) break;
        if (q != cudaErrorNotReady) return cudaGetErrorString(q);
        if (ms() - t0 > 3000) {
            *out_ms = ms() - t0;
            return "TIMEOUT";
        }
    }
    *out_ms = ms() - t0;
    return "ok";
}

static void run(const char *when, cudaStream_t sb, char *d64, char *d64k, char *h64, char *h64k) {
    double t;
    const char *r;
    r = timed(sb, cudaMemcpyAsync(h64, d64, 64, cudaMemcpyDeviceToHost, sb), &t);
    printf("%-8s D2H 64B  non-blocking stream: %s %.3f ms\n", when, r, t);
    r = timed(sb, cudaMemcpyAsync(d64, h64, 64, cudaMemcpyHostToDevice, sb), &t);
    printf("%-8s H2D 64B  non-blocking stream: %s %.3f ms\n", when, r, t);
    r = timed(sb, cudaMemcpyAsync(h64k, d64k, 65536, cudaMemcpyDeviceToHost, sb), &t);
    printf("%-8s D2H 64KiB non-blocking stream: %s %.3f ms\n", when, r, t);
    CUdeviceptr dp = (CUdeviceptr)d64;
    CUstream cs = (CUstream)sb;
    CUresult cr = cuMemcpyDtoHAsync(h64, dp, 64, cs);
    r = timed(sb, cr == CUDA_SUCCESS ? cudaSuccess : cudaErrorUnknown, &t);
    printf("%-8s D2H 64B  driver API, same stream: %s %.3f ms\n", when, r, t);
    r = timed(0, cudaMemcpyAsync(h64, d64, 64, cudaMemcpyDeviceToHost, 0), &t);
    printf("%-8s D2H 64B  legacy stream: %s %.3f ms\n", when, r, t);
}

int main(int argc, char **argv) {
    cudaDeviceProp p;
    CK(cudaGetDeviceProperties(&p, 0));
    int ctas = argc > 1 ? atoi(argv[1]) : p.multiProcessorCount * (p.maxThreadsPerMultiProcessor / 256);
    printf("GPU %s SMs=%d maxThreads/SM=%d filler ctas=%d x 256\n", p.name, p.multiProcessorCount,
           p.maxThreadsPerMultiProcessor, ctas);
    char *d64, *d64k, *h64, *h64k;
    int *stop;
    CK(cudaMalloc(&d64, 64));
    CK(cudaMalloc(&d64k, 65536));
    CK(cudaMalloc(&stop, 4));
    CK(cudaMemset(stop, 0, 4));
    CK(cudaHostAlloc(&h64, 64, cudaHostAllocDefault));
    CK(cudaHostAlloc(&h64k, 65536, cudaHostAllocDefault));
    cudaStream_t sa, sb;
    CK(cudaStreamCreateWithFlags(&sa, cudaStreamNonBlocking));
    CK(cudaStreamCreateWithFlags(&sb, cudaStreamNonBlocking));
    const bool threaded = argc > 2;
    run("idle", sb, d64, d64k, h64, h64k);
    filler<<<ctas, 256, 0, sa>>>(stop, 20000000000ULL);
    CK(cudaGetLastError());
    struct timespec w = {0, 100000000};
    nanosleep(&w, 0);
    printf("filler launched: stream query %s\n", cudaGetErrorString(cudaStreamQuery(sa)));
    int one = 1;
    double t;
    const char *r;
    if (threaded) {
        volatile bool done = false;
        std::thread th([&]() {
            CK(cudaSetDevice(0));
            cudaStream_t sc;
            CK(cudaStreamCreateWithFlags(&sc, cudaStreamNonBlocking));
            run("filled/thread", sc, d64, d64k, h64, h64k);
            double tt;
            const char *rr = timed(sc, cudaMemcpyAsync(stop, &one, 4, cudaMemcpyHostToDevice, sc), &tt);
            printf("stop flag H2D from the thread: %s %.3f ms\n", rr, tt);
            done = true;
        });
        double t0 = ms();
        while (!done) { /* the application's wait */
            cudaError_t e = cudaStreamQuery(sa);
            if (e != cudaErrorNotReady && e != cudaSuccess) printf("filler stream: %s\n", cudaGetErrorString(e));
            usleep(1000);
            if (ms() - t0 > 25000) break;
        }
        th.join();
    } else {
        run("filled", sb, d64, d64k, h64, h64k);
        r = timed(sb, cudaMemcpyAsync(stop, &one, 4, cudaMemcpyHostToDevice, sb), &t);
        printf("stop flag H2D: %s %.3f ms\n", r, t);
    }
    double t0 = ms();
    cudaStreamSynchronize(sa);
    printf("filler ended after %.1f ms\n", ms() - t0);
    run("after", sb, d64, d64k, h64, h64k);
    return 0;
}
