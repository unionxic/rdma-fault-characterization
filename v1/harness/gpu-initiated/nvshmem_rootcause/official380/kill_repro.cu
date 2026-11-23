// kill_repro.cu - what nvshmem_quiet() does on IBGDA after the peer PE is killed.
// Uses only the public NVSHMEM API, so it runs against an unmodified NVSHMEM build.
//
// PE 0 loops: one kernel per iteration doing nvshmem_putmem_signal_nbi() to PE 1 and then
// nvshmem_quiet(). PE 1 waits for each signal and prints it. The runner SIGKILLs PE 1 mid-loop.
// PE 0's host bounds every iteration: if the kernel has not finished after hang_s seconds, it
// reports that nvshmem_quiet() did not return and exits without nvshmem_finalize() (which
// cannot complete with a dead peer anyway).
//
// FINALIZE=1 (env, optional): wherever the run ends (all iterations returned, the hang_s bound,
// or a failed kernel), the PE calls nvshmem_finalize() under a 30 s watchdog thread and prints
// "PE <n>: nvshmem_finalize returned after X ms" or
// "PE <n>: nvshmem_finalize did not return after 30 s". The exit code is the one of the end path
// (0, 3 or 4) if finalize returned, and 5 if it did not. Without FINALIZE the program never calls
// nvshmem_finalize, as before.
//
// usage: nvs_kill_repro <rank 0|1> <pe0_ip> <tcp_port> [iters] [bytes] [period_ms] [hang_s]
// Bootstrap: NVSHMEM unique id, sent from PE 0 to PE 1 over a plain TCP socket.
#include <atomic>
#include <thread>
#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

#include <cuda_runtime.h>
#include <nvshmem.h>
#include <nvshmemx.h>

#define CK(x)                                                                             \
    do {                                                                                  \
        cudaError_t e_ = (x);                                                             \
        if (e_ != cudaSuccess) {                                                          \
            fprintf(stderr, "%s:%d %s: %s\n", __FILE__, __LINE__, #x, cudaGetErrorString(e_)); \
            _exit(4);                                                                     \
        }                                                                                 \
    } while (0)

static double now_ms() {
    timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec * 1e3 + t.tv_nsec / 1e6;
}

// ---- FINALIZE=1: nvshmem_finalize() at the end, bounded by a watchdog thread ----
static const int FINALIZE_BOUND_S = 30;
static bool g_finalize = false;
static std::atomic<int> g_fin_state{0};  // 0 running, 1 returned, 2 watchdog fired

// Ends the process. With FINALIZE=1 it first calls nvshmem_finalize(); a watchdog thread exits
// with code 5 if that has not returned after FINALIZE_BOUND_S.
[[noreturn]] static void end_run(int mype, int code) {
    fflush(stdout);
    if (g_finalize) {
        double t0 = now_ms();
        std::thread([mype, t0]() {
            while (now_ms() - t0 < FINALIZE_BOUND_S * 1e3) {
                if (g_fin_state.load() != 0) return;
                usleep(10000);
            }
            int running = 0;
            if (!g_fin_state.compare_exchange_strong(running, 2)) return;
            char m[96];
            int n = snprintf(m, sizeof m, "PE %d: nvshmem_finalize did not return after %d s\n", mype,
                             FINALIZE_BOUND_S);
            if (n > 0 && write(1, m, (size_t)n) < 0) {}
            _exit(5);
        }).detach();
        nvshmem_finalize();
        int running = 0;
        if (!g_fin_state.compare_exchange_strong(running, 1))
            for (;;) pause();  // the watchdog fired first and is exiting
        printf("PE %d: nvshmem_finalize returned after %.1f ms\n", mype, now_ms() - t0);
        fflush(stdout);
    }
    _exit(code);
}

static int xfer(int fd, void *p, size_t n, int send_) {
    char *c = (char *)p;
    while (n) {
        ssize_t r = send_ ? send(fd, c, n, 0) : recv(fd, c, n, 0);
        if (r <= 0) return -1;
        c += r;
        n -= r;
    }
    return 0;
}

__global__ void put_signal_quiet(void *dst, const void *src, size_t bytes, uint64_t *sig, int peer) {
    if (threadIdx.x == 0 && blockIdx.x == 0) {
        nvshmem_putmem_signal_nbi(dst, src, bytes, sig, 1, NVSHMEM_SIGNAL_ADD, peer);
        nvshmem_quiet();
    }
}

__global__ void wait_signal(uint64_t *sig, uint64_t value) {
    if (threadIdx.x == 0 && blockIdx.x == 0) nvshmem_signal_wait_until(sig, NVSHMEM_CMP_GE, value);
}

int main(int argc, char **argv) {
    if (argc < 4) {
        fprintf(stderr, "usage: %s <rank 0|1> <pe0_ip> <tcp_port> [iters] [bytes] [period_ms] [hang_s]\n",
                argv[0]);
        return 1;
    }
    int rank = atoi(argv[1]);
    const char *pe0_ip = argv[2];
    int port = atoi(argv[3]);
    int iters = argc > 4 ? atoi(argv[4]) : 40;
    size_t bytes = argc > 5 ? strtoul(argv[5], 0, 10) : 262144;
    int period_ms = argc > 6 ? atoi(argv[6]) : 250;
    int hang_s = argc > 7 ? atoi(argv[7]) : 30;
    const char *fin = getenv("FINALIZE");
    g_finalize = fin && fin[0] && strcmp(fin, "0") != 0;
    setvbuf(stdout, NULL, _IOLBF, 0);

    nvshmemx_uniqueid_t id = NVSHMEMX_UNIQUEID_INITIALIZER;
    int one = 1;
    sockaddr_in a{};
    a.sin_family = AF_INET;
    a.sin_port = htons(port);
    if (rank == 0) {
        nvshmemx_get_uniqueid(&id);
        int ls = socket(AF_INET, SOCK_STREAM, 0);
        setsockopt(ls, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
        a.sin_addr.s_addr = INADDR_ANY;
        if (bind(ls, (sockaddr *)&a, sizeof a) || listen(ls, 1)) {
            perror("bind/listen");
            return 1;
        }
        int cs = accept(ls, 0, 0);
        if (cs < 0 || xfer(cs, &id, sizeof id, 1)) {
            perror("send id");
            return 1;
        }
        close(cs);
        close(ls);
    } else {
        inet_pton(AF_INET, pe0_ip, &a.sin_addr);
        int cs = -1;
        for (int tries = 0;; tries++) {
            cs = socket(AF_INET, SOCK_STREAM, 0);
            if (connect(cs, (sockaddr *)&a, sizeof a) == 0) break;
            close(cs);
            if (tries > 300) {
                fprintf(stderr, "cannot reach PE 0\n");
                return 1;
            }
            usleep(200000);
        }
        if (xfer(cs, &id, sizeof id, 0)) {
            perror("recv id");
            return 1;
        }
        close(cs);
    }

    CK(cudaSetDevice(0));
    nvshmemx_init_attr_t attr = NVSHMEMX_INIT_ATTR_INITIALIZER;
    nvshmemx_set_attr_uniqueid_args(rank, 2, &id, &attr);
    if (nvshmemx_init_attr(NVSHMEMX_INIT_WITH_UNIQUEID, &attr)) {
        fprintf(stderr, "nvshmemx_init_attr failed\n");
        return 2;
    }
    int mype = nvshmem_my_pe();
    char *dst = (char *)nvshmem_malloc(bytes);
    char *src = (char *)nvshmem_malloc(bytes);
    uint64_t *sig = (uint64_t *)nvshmem_malloc(sizeof(uint64_t));
    if (!dst || !src || !sig) {
        fprintf(stderr, "nvshmem_malloc failed\n");
        return 2;
    }
    CK(cudaMemset(sig, 0, sizeof(uint64_t)));
    CK(cudaMemset(src, 0x5a, bytes));
    CK(cudaDeviceSynchronize());
    nvshmem_barrier_all();
    printf("PE %d ready: iters=%d bytes=%zu period_ms=%d hang_s=%d%s\n", mype, iters, bytes, period_ms,
           hang_s, g_finalize ? " finalize=1" : "");
    const char *end_how = g_finalize ? "calling nvshmem_finalize" : "exiting without nvshmem_finalize";

    cudaStream_t st;
    CK(cudaStreamCreateWithFlags(&st, cudaStreamNonBlocking));
    for (int i = 0; i < iters; i++) {
        double t0 = now_ms();
        if (mype == 0)
            put_signal_quiet<<<1, 1, 0, st>>>(dst, src, bytes, sig, 1);
        else
            wait_signal<<<1, 1, 0, st>>>(sig, (uint64_t)i + 1);
        CK(cudaGetLastError());
        cudaError_t q;
        while ((q = cudaStreamQuery(st)) == cudaErrorNotReady) {
            if (now_ms() - t0 > hang_s * 1e3) {
                if (mype == 0)
                    printf("PE 0 iter %d: nvshmem_quiet() has not returned after %d s; %s\n", i, hang_s,
                           end_how);
                else
                    printf("PE 1 iter %d: no signal after %d s; %s\n", i, hang_s,
                           g_finalize ? end_how : "exiting");
                end_run(mype, 3);
            }
            usleep(1000);
        }
        if (q != cudaSuccess) {
            printf("PE %d iter %d: kernel failed: %s\n", mype, i, cudaGetErrorString(q));
            end_run(mype, 4);
        }
        if (mype == 0)
            printf("PE 0 iter %d: put + signal + nvshmem_quiet() returned after %.1f ms\n", i, now_ms() - t0);
        else
            printf("PE 1 iter %d: signal arrived after %.1f ms\n", i, now_ms() - t0);
        if (mype == 0) usleep(period_ms * 1000);
    }
    // No nvshmem_finalize() by default: its barrier cannot complete once the peer is gone.
    printf("PE %d: all %d iterations returned; %s\n", mype, iters, end_how);
    end_run(mype, 0);
}
