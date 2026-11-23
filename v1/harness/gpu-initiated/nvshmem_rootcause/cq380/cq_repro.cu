// cq_repro.cu - ../official380/kill_repro.cu plus a read of every IBGDA completion queue on PE 0.
// With CQSCAN=1, just before PE 0 ends (all iterations returned, or the hang_s bound), a kernel on a
// separate stream reads nvshmemi_ibgda_device_state_d (NVSHMEM's internal device state, declared
// in the installed device_host_transport/nvshmem_common_ibgda.h) and every CQE of every DCI and RC
// completion queue, and prints one "CQSCAN" line per queue: valid CQEs, error CQEs (opcode 0xd
// REQ_ERR or 0xe RESP_ERR), and the first error's syndrome and vendor syndrome. The NVSHMEM library
// itself is not modified. The rest is kill_repro.cu unchanged:
// what nvshmem_quiet() does on IBGDA after the peer PE is killed.
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
#include "device_host_transport/nvshmem_common_ibgda.h"

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

extern __constant__ nvshmemi_ibgda_device_state_t nvshmemi_ibgda_device_state_d;

struct CqSum {
    uint32_t qpn, ncqes, valid, err, first_err_idx;
    uint8_t first_synd, first_vend, last_op, pad;
    int is_dci;
};
static const int MAX_CQ = 16;

// One thread: walks the CQ array of the internal device state. CQEs are read volatile.
__global__ void cq_scan(CqSum *out, int *nout, int npes) {
    if (threadIdx.x || blockIdx.x) return;
    const nvshmemi_ibgda_device_state_t *st = &nvshmemi_ibgda_device_state_d;
    int ndci = st->num_shared_dcis + st->num_exclusive_dcis;
    int nrc = st->num_rc_per_pe * st->num_devices_initialized * npes;
    int n = ndci + nrc, k = 0;
    if (!st->globalmem.cqs) n = 0;
    for (int i = 0; i < n && k < MAX_CQ; i++) {
        const nvshmemi_ibgda_device_cq_t *cq = &st->globalmem.cqs[i];
        if (!cq->cqe || cq->ncqes == 0 || cq->ncqes > 65536) continue;
        CqSum c = {};
        c.qpn = cq->qpn; c.ncqes = cq->ncqes; c.is_dci = i < ndci; c.first_err_idx = 0xffffffffu;
        for (uint32_t j = 0; j < cq->ncqes; j++) {
            const volatile uint8_t *e = (const volatile uint8_t *)cq->cqe + 64 * (size_t)j;
            uint8_t op = e[63] >> 4;
            if (op == 0xf) continue;            // never written (MLX5_CQE_INVALID)
            c.valid++;
            c.last_op = op;
            if (op == 0xd || op == 0xe) {        // REQ_ERR, RESP_ERR
                if (!c.err) { c.first_err_idx = j; c.first_synd = e[55]; c.first_vend = e[54]; }
                c.err++;
            }
        }
        out[k++] = c;
    }
    *nout = k;
}

// Everything the scan needs is prepared before the first iteration (cq_scan_prepare): allocating,
// or copying through pageable memory, while a kernel is stuck can block, and a scan kernel can
// queue behind the stuck kernel. So the CQ array is copied to the host at start. A queue whose
// buffer is host memory (the cpu_host_memory handler) is then read directly by the CPU, with no
// CUDA call. Otherwise a kernel on its own non-blocking stream reads it, with a bounded wait.
static cudaStream_t g_scan_stream;
static CqSum *g_scan_d, *g_scan_h;
static int *g_scan_dn, *g_scan_hn;
static bool g_scan_on = false;
static int g_ncq = 0, g_ndci = 0;
static nvshmemi_ibgda_device_cq_t g_cq[MAX_CQ];
static const volatile uint8_t *g_cqe_host[MAX_CQ];
static bool g_all_host = false;

static void cq_scan_prepare(int npes) {
    const char *e = getenv("CQSCAN");
    if (!e || !e[0] || !strcmp(e, "0")) return;
    if (cudaStreamCreateWithFlags(&g_scan_stream, cudaStreamNonBlocking) ||
        cudaMalloc(&g_scan_d, sizeof(CqSum) * MAX_CQ) || cudaMalloc(&g_scan_dn, sizeof(int)) ||
        cudaMallocHost(&g_scan_h, sizeof(CqSum) * MAX_CQ) || cudaMallocHost(&g_scan_hn, sizeof(int))) {
        printf("CQSCAN failed: allocation\n");
        return;
    }
    g_scan_on = true;
    static nvshmemi_ibgda_device_state_t st;
    if (cudaMemcpyFromSymbol(&st, nvshmemi_ibgda_device_state_d, sizeof st) || !st.globalmem.cqs) {
        printf("CQSCAN note: device state not readable from the host; kernel path only\n");
        return;
    }
    g_ndci = st.num_shared_dcis + st.num_exclusive_dcis;
    int n = g_ndci + st.num_rc_per_pe * st.num_devices_initialized * npes;
    if (n > MAX_CQ) n = MAX_CQ;
    if (cudaMemcpy(g_cq, st.globalmem.cqs, sizeof(g_cq[0]) * n, cudaMemcpyDeviceToHost)) return;
    g_ncq = n;
    g_all_host = true;
    printf("CQSCAN prep queues=%d dcis=%d\n", n, g_ndci);
    for (int i = 0; i < n; i++) {
        g_cqe_host[i] = nullptr;
        if (!g_cq[i].cqe || g_cq[i].ncqes == 0 || g_cq[i].ncqes > 65536) continue;
        cudaPointerAttributes at;
        cudaError_t ae = cudaPointerGetAttributes(&at, g_cq[i].cqe);
        printf("CQSCAN prep cq=%d type=%s qpn=0x%x ncqes=%u cqe=%p ptr_type=%d host_ptr=%s\n", i,
               i < g_ndci ? "dci" : "rc", g_cq[i].qpn, g_cq[i].ncqes, g_cq[i].cqe,
               ae == cudaSuccess ? (int)at.type : -1, (ae == cudaSuccess && at.hostPointer) ? "yes" : "no");
        if (ae == cudaSuccess && at.type == cudaMemoryTypeHost && at.hostPointer)
            g_cqe_host[i] = (const volatile uint8_t *)at.hostPointer;
        else
            g_all_host = false;
    }
    cudaGetLastError();
}

static void cq_print(const CqSum *h, int hn, const char *path) {
    int total = 0;
    for (int i = 0; i < hn; i++) {
        const CqSum &c = h[i];
        printf("CQSCAN cq=%d type=%s qpn=0x%x ncqes=%u valid=%u err=%u", i, c.is_dci ? "dci" : "rc", c.qpn,
               c.ncqes, c.valid, c.err);
        if (c.err) printf(" first_err_at=%u syndrome=0x%02x vendor=0x%02x", c.first_err_idx, c.first_synd, c.first_vend);
        printf(" last_opcode=0x%x\n", c.last_op);
        total += c.err;
    }
    printf("CQSCAN queues=%d total_err=%d path=%s\n", hn, total, path);
}

static void cq_scan_print(int npes) {
    if (!g_scan_on) return;
    if (g_all_host && g_ncq > 0) {
        CqSum h[MAX_CQ]; int k = 0;
        for (int i = 0; i < g_ncq; i++) {
            if (!g_cqe_host[i]) continue;
            CqSum c = {};
            c.qpn = g_cq[i].qpn; c.ncqes = g_cq[i].ncqes; c.is_dci = i < g_ndci; c.first_err_idx = 0xffffffffu;
            for (uint32_t j = 0; j < g_cq[i].ncqes; j++) {
                const volatile uint8_t *e = g_cqe_host[i] + 64 * (size_t)j;
                uint8_t op = e[63] >> 4;
                if (op == 0xf) continue;
                c.valid++; c.last_op = op;
                if (op == 0xd || op == 0xe) {
                    if (!c.err) { c.first_err_idx = j; c.first_synd = e[55]; c.first_vend = e[54]; }
                    c.err++;
                }
            }
            h[k++] = c;
        }
        cq_print(h, k, "host");
        return;
    }
    *g_scan_hn = -1;
    cq_scan<<<1, 1, 0, g_scan_stream>>>(g_scan_d, g_scan_dn, npes);
    cudaMemcpyAsync(g_scan_h, g_scan_d, sizeof(CqSum) * MAX_CQ, cudaMemcpyDeviceToHost, g_scan_stream);
    cudaMemcpyAsync(g_scan_hn, g_scan_dn, sizeof(int), cudaMemcpyDeviceToHost, g_scan_stream);
    double t0 = now_ms();
    cudaError_t q;
    while ((q = cudaStreamQuery(g_scan_stream)) == cudaErrorNotReady && now_ms() - t0 < 5000) usleep(1000);
    if (q != cudaSuccess) {
        printf("CQSCAN failed: %s\n", q == cudaErrorNotReady ? "scan did not finish in 5 s" : cudaGetErrorString(q));
        const char *hold = getenv("CQSCAN_HOLD_S");
        if (hold && atoi(hold) > 0) {
            printf("CQSCAN hold %d s for an external dump\n", atoi(hold));
            fflush(stdout);
            sleep(atoi(hold));
        }
        return;
    }
    cq_print(g_scan_h, *g_scan_hn, "kernel");
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
    if (mype == 0) cq_scan_prepare(2);
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
                if (mype == 0) {
                    printf("PE 0 iter %d: nvshmem_quiet() has not returned after %d s; %s\n", i, hang_s,
                           end_how);
                    cq_scan_print(2);
                }
                else
                    printf("PE 1 iter %d: no signal after %d s; %s\n", i, hang_s,
                           g_finalize ? end_how : "exiting");
                end_run(mype, 3);
            }
            usleep(1000);
        }
        if (q != cudaSuccess) {
            printf("PE %d iter %d: kernel failed: %s\n", mype, i, cudaGetErrorString(q));
            if (mype == 0) cq_scan_print(2);
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
    if (mype == 0) cq_scan_print(2);
    end_run(mype, 0);
}
