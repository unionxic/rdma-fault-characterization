// nvshmem_ft_v2.cu - 2-PE NVSHMEM IBGDA fault-tolerance driver for the v2 patch
// (nvshmem_ibgda_ft_v2.diff). Same protocol and output as nvshmem_ft.cu (v1 driver), plus:
//   --oob <exact|gap|straddle|tail|heap> --oob-at IT   F2a: at iteration IT PE0 puts one window to
//        a wrong place in the peer's heap (both PEs pass the flag: the allocation layout must be
//        symmetric). exact = dbuf+bytes (the next object, sbuf); gap = dbuf+bytes where the next
//        object was freed; straddle = dbuf+bytes/2 (crosses dbuf's end); tail = past the last
//        object; heap = past the heap end. PE1 fills [bad_dst+..., +bytes) outside dbuf with a canary
//        before the loop and reports OOBCHECK (canary and dbuf state) after it.
//   NVFT_INIT_DIAG_S=<s>   a host thread dumps the RC/DCI queue state and the first CQ slots if
//        init + the first barrier have not finished after <s> s (cc=0 stock probe).
//   Ring-CQ mode: the slot diagnostic reads the slot at the ring consumer counter.
//   --mt T [--mt-reps R]  fault-free concurrency check: per iteration T threads of one CTA each put
//        bytes/T (+ signal ADD 1) and call nvshmem_quiet, R times, all on the same RC QP (concurrent
//        waiters on one send CQ); PE1 expects the signal to grow by T*R and verifies every byte.
//
// (v1 header follows)
// nvshmem_ft.cu - 2-PE NVSHMEM IBGDA fault-tolerance driver (classification, recovery, overhead).
//
// Extends ../nvshmem/nvshmem_fault.cu. PE0 (rain, initiator) puts M bytes of an (iteration,
// byte-index) pattern to PE1 (sunny, target) with nvshmem_putmem_signal_nbi (RDMA WRITE + remote
// atomic ADD 1 on a signal word), then completes the operation:
//   timeout   nvshmemx_ibgda_ft_quiet_bounded(peer, budget): 0 done, -1 error CQE (classified by the
//             device), -2 budget expired;
//   blocking  the library nvshmem_quiet() (unbounded), then nvshmemx_ibgda_ft_status(peer).
// PE1 waits for the signal (bounded spin, or nvshmem_signal_wait_until in blocking mode; the host
// can release it) and verifies every byte, then acknowledges the iteration over the OOB socket
// (lockstep), so every iteration's data and the signal count are checked exactly.
//
// With NVSHMEM_IBGDA_FT=1 the patched IBGDA transport exports nvshmemt_ibgda_ft_* (resolved here
// with dlopen(RTLD_NOLOAD)). With --recover the driver runs the recovery protocol (DESIGN.md):
//   initiator: kernel returns the error; ft_query -> class; policy (LOCAL_QP_ERR: recover;
//   RETRY_EXC: recover if the OOB socket shows the peer alive; else decline); ft_prepare
//   (quiescence, QPs -> ERR, drain, fresh PSNs); REQ{token} ->
//   responder: ft_prepare; read its signal V (side stream, its waiter may still spin);
//   d = expected - V in [0, burst]; ft_commit(token_i); <- ACK{token_r, d}
//   initiator: ft_commit(token_r); replay the last d put+ADD ops (data + only the missing signal
//   delta); a failed replay starts a new round; DONE.
// Decline: FAIL -> both sides ft_abort/mark_failed (teardown skips device collectives), the
// responder releases its own waiter by writing a cancel marker into its signal word.
//
// OOB: the unique-ID TCP socket on the management network stays open for the protocol.
// Every wait is bounded (device budgets, host alarm, OOB deadlines).
//
// Exit codes: 0 ok (all iterations verified, recovered or not), 1 usage, 2 nvshmem init,
// 3 fault surfaced and not recovered (classification-only runs), 4 target timeout/missing,
// 5 data mismatch, 6 CUDA error, 7 watchdog (hang), 8 protocol error, 9 declined.
#include <nvshmem.h>
#include <nvshmemx.h>
#include "device_host_transport/nvshmem_common_ibgda.h"
// The IBGDA device code lives in libnvshmem_device.a; the FT device API (status, bounded quiet,
// sentinel) is header-only in the patched ibgda_device.cuh, so include it here.
#include "non_abi/device/pt-to-pt/ibgda_device.cuh"

// The FT device API is defined only in the device compilation pass (inside #ifdef __CUDA_ARCH__
// in the header); the host pass still parses kernel bodies, so give it declarations.
#ifndef __CUDA_ARCH__
__device__ uint32_t nvshmemx_ibgda_ft_status(int pe);
__device__ int nvshmemx_ibgda_ft_quiet_bounded(int pe, long long budget);
__device__ void nvshmemx_ibgda_ft_sentinel(unsigned int poll_ns);
#endif

#include <cuda_runtime.h>
#include <arpa/inet.h>
#include <dlfcn.h>
#include <errno.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>
#include <algorithm>
#include <csignal>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <atomic>
#include <pthread.h>
#include <vector>

static const int NRANKS = 2;
static int g_rank = -1;

#define CK(c)                                                                             \
    do {                                                                                  \
        cudaError_t e_ = (c);                                                             \
        if (e_ != cudaSuccess) {                                                          \
            fprintf(stderr, "[PE%d] CUDA %s:%d %s\n", g_rank, __FILE__, __LINE__,         \
                    cudaGetErrorString(e_));                                              \
            exit(6);                                                                      \
        }                                                                                 \
    } while (0)

static double monoMs() {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec * 1e3 + t.tv_nsec * 1e-6;
}
static double realMs() {
    struct timespec t;
    clock_gettime(CLOCK_REALTIME, &t);
    return t.tv_sec * 1e3 + t.tv_nsec * 1e-6;
}

// ---------------------------------------------------------------- OOB socket + protocol
static int sendall(int fd, const void *b, size_t n) {
    const char *p = (const char *)b;
    size_t o = 0;
    while (o < n) {
        ssize_t k = send(fd, p + o, n - o, MSG_NOSIGNAL);
        if (k <= 0) return -1;
        o += (size_t)k;
    }
    return 0;
}
static int recvall(int fd, void *b, size_t n) {
    char *p = (char *)b;
    size_t o = 0;
    while (o < n) {
        ssize_t k = recv(fd, p + o, n - o, 0);
        if (k <= 0) return -1;
        o += (size_t)k;
    }
    return 0;
}

enum { M_ITER_OK = 1, M_REQ, M_ACK, M_NACK, M_DONE, M_FAIL, M_PING, M_PONG, M_BYE };
static const char *mname(int t) {
    static const char *n[] = {"?", "ITER_OK", "REQ", "ACK", "NACK", "DONE", "FAIL", "PING", "PONG", "BYE"};
    return (t >= 1 && t <= 9) ? n[t] : "?";
}
#define MSG_MAGIC 0x4e46544du
struct Msg {
    uint32_t magic, type;
    int32_t it, round;
    int32_t cls, d;
    uint64_t V;
    int32_t status, pad;
    double t;
    nvshmemt_ibgda_ft_token_t tok;
    char reason[96];
};

static int g_sock = -1;
// v2 driver fix: an ITER_OK that arrives while the initiator waits for a recovery ACK (the target
// verified the operation before the REQ reached it, forced d = 0 rounds) is kept, not dropped.
static bool g_have_stash = false;
static Msg g_stash;
// Host-side bounds (s), overridable for flag-off runs where the stock paths hang.
static double g_ack_limit_s = 60, g_rx_limit_s = 120, g_teardown_s = 60;

static int sendMsg(int type, int it, int round, int cls = 0, int d = 0, uint64_t V = 0, int status = 0,
                   const nvshmemt_ibgda_ft_token_t *tok = nullptr, const char *reason = nullptr) {
    Msg m;
    memset(&m, 0, sizeof(m));
    m.magic = MSG_MAGIC;
    m.type = type;
    m.it = it;
    m.round = round;
    m.cls = cls;
    m.d = d;
    m.V = V;
    m.status = status;
    m.t = monoMs();
    if (tok) m.tok = *tok;
    if (reason) snprintf(m.reason, sizeof(m.reason), "%s", reason);
    return sendall(g_sock, &m, sizeof(m));
}

// 1 message received, 0 none within timeout_ms, -1 peer closed / error.
static int recvMsg(Msg *m, int timeout_ms) {
    struct pollfd p = {g_sock, POLLIN, 0};
    int r = poll(&p, 1, timeout_ms);
    if (r == 0) return 0;
    if (r < 0) return errno == EINTR ? 0 : -1;
    if (recvall(g_sock, m, sizeof(*m))) return -1;
    if (m->magic != MSG_MAGIC) return -1;
    return 1;
}

// Liveness from the OOB socket (as in the CPU harness): FIN or RST = dead; EAGAIN = no evidence.
static const char *peerLiveness() {
    char b;
    ssize_t k = recv(g_sock, &b, 1, MSG_PEEK | MSG_DONTWAIT);
    if (k == 0) return "dead(FIN)";
    if (k < 0) {
        if (errno == EAGAIN || errno == EWOULDBLOCK) return "alive";
        if (errno == ECONNRESET) return "dead(RST)";
        if (errno == EPIPE || errno == ETIMEDOUT || errno == ENOTCONN) return "dead(err)";
        return "alive";
    }
    return "alive(data)";
}

// ---------------------------------------------------------------- transport FT API (dlsym)
typedef int (*ft_enabled_fn)(void);
typedef int (*ft_query_fn)(nvshmemt_ibgda_ft_info_t *, int);
typedef int (*ft_prepare_fn)(int, nvshmemt_ibgda_ft_token_t *, nvshmemt_ibgda_ft_stats_t *);
typedef int (*ft_commit_fn)(int, const nvshmemt_ibgda_ft_token_t *, nvshmemt_ibgda_ft_stats_t *);
typedef int (*ft_abort_fn)(int);
typedef int (*ft_mark_failed_fn)(void);
typedef int (*ft_sentinel_stop_fn)(int, uint64_t *);
static struct {
    ft_enabled_fn enabled;
    ft_query_fn query;
    ft_prepare_fn prepare;
    ft_commit_fn commit;
    ft_abort_fn abort;
    ft_mark_failed_fn mark_failed;
    ft_sentinel_stop_fn sentinel_stop;
    int on;
} FT;

static void loadFtApi() {
    memset(&FT, 0, sizeof(FT));
    void *h = dlopen("nvshmem_transport_ibgda.so.7", RTLD_NOW | RTLD_NOLOAD);
    if (!h) {
        fprintf(stderr, "[PE%d] FT api: transport not loaded (%s)\n", g_rank, dlerror());
        return;
    }
    FT.enabled = (ft_enabled_fn)dlsym(h, "nvshmemt_ibgda_ft_enabled");
    FT.query = (ft_query_fn)dlsym(h, "nvshmemt_ibgda_ft_query");
    FT.prepare = (ft_prepare_fn)dlsym(h, "nvshmemt_ibgda_ft_prepare");
    FT.commit = (ft_commit_fn)dlsym(h, "nvshmemt_ibgda_ft_commit");
    FT.abort = (ft_abort_fn)dlsym(h, "nvshmemt_ibgda_ft_abort");
    FT.mark_failed = (ft_mark_failed_fn)dlsym(h, "nvshmemt_ibgda_ft_mark_failed");
    FT.sentinel_stop = (ft_sentinel_stop_fn)dlsym(h, "nvshmemt_ibgda_ft_sentinel_stop");
    FT.on = (FT.enabled && FT.query && FT.prepare && FT.commit && FT.abort && FT.mark_failed)
                ? FT.enabled()
                : 0;
}

// ---------------------------------------------------------------- device side
__host__ __device__ static inline unsigned char patByte(int it, size_t b) {
    uint32_t h = (uint32_t)(b * 2654435761u) ^ (uint32_t)((it + 1) * 40503u);
    h ^= h >> 13;
    return (unsigned char)(h & 0xff);
}

static const uint64_t CANCEL_MARK = 1ull << 40;  // host-written into the signal to release a waiter

struct PutResult {
    int rc;                 // 0 done, -1 error (FT), -2 budget expired
    uint32_t fp;            // nvshmemx_ibgda_ft_status(peer)
    unsigned long long gt_start, gt_post, gt_end;  // %globaltimer
    uint32_t slot_op, slot_syn, slot_ven, slot_wqe;  // collapsed slot at the end (what a stock poll sees)
    unsigned long long ready_head;
};

__device__ static inline unsigned long long gtimer() {
    unsigned long long t;
    asm volatile("mov.u64 %0, %%globaltimer;" : "=l"(t));
    return t;
}

__global__ void put_kernel(char *dst, const char *src, size_t bytes, uint64_t *sig, int peer, int mode,
                           long long budget, int nops, long long delay_cycles, PutResult *res) {
    if (threadIdx.x || blockIdx.x) return;
    res->gt_start = gtimer();
    for (int i = 0; i < nops; i++)
        nvshmem_putmem_signal_nbi(dst, src, bytes, sig, 1ull, NVSHMEM_SIGNAL_ADD, peer);
    res->gt_post = gtimer();
    if (delay_cycles > 0) {  // "compute" between posting and completing (capture study)
        long long t0 = clock64();
        while (clock64() - t0 < delay_cycles) {
        }
    }
    int rc;
    if (mode == 0) {
        rc = nvshmemx_ibgda_ft_quiet_bounded(peer, budget);
    } else {
        nvshmem_quiet();
        rc = nvshmemx_ibgda_ft_status(peer) ? -1 : 0;
    }
    res->gt_end = gtimer();
    res->rc = rc;
    res->fp = nvshmemx_ibgda_ft_status(peer);
    nvshmemi_ibgda_device_qp_t *qp = &nvshmemi_ibgda_device_state_d.globalmem.rcs[peer];
    volatile unsigned char *c = (volatile unsigned char *)qp->tx_wq.cq->cqe;
    if (nvshmemi_ibgda_device_state_d.ft_flags & NVSHMEMI_IBGDA_FT_FLAG_RING_CQ) {
        // v2 ring mode: the slot at the consumer counter (holds the error CQE after a failure)
        uint64_t ci = *(volatile uint64_t *)&qp->mvars.ft_ring_ci;
        c += (size_t)(ci & (qp->tx_wq.cq->ncqes - 1)) * 64;
    }
    res->slot_op = c[63] >> 4;
    res->slot_syn = c[55];
    res->slot_ven = c[54];
    res->slot_wqe = ((unsigned)c[60] << 8) | c[61];
    res->ready_head = qp->mvars.tx_wq.ready_head;
}

// v2 --mt: T threads, each puts its slice + signal and quiets, R times (concurrent CQ waiters).
__global__ void mt_put_kernel(char *dst, const char *src, size_t bytes, uint64_t *sig, int peer, int reps,
                              PutResult *res) {
    const size_t slice = bytes / blockDim.x;
    const size_t o = (size_t)threadIdx.x * slice;
    if (threadIdx.x == 0) res->gt_start = gtimer();
    for (int r = 0; r < reps; r++) {
        nvshmem_putmem_signal_nbi(dst + o, src + o, slice, sig, 1ull, NVSHMEM_SIGNAL_ADD, peer);
        nvshmem_quiet();
    }
    __syncthreads();
    if (threadIdx.x == 0) {
        res->gt_end = gtimer();
        res->fp = nvshmemx_ibgda_ft_status(peer);
        res->rc = res->fp ? -1 : 0;
        res->ready_head = nvshmemi_ibgda_device_state_d.globalmem.rcs[peer].mvars.tx_wq.ready_head;
    }
}

// Latency: K x (put + signal + quiet) timed on the GPU.
__global__ void lat_kernel(char *dst, const char *src, size_t bytes, uint64_t *sig, int peer, int K,
                           unsigned int *times_ns, int *err) {
    if (threadIdx.x || blockIdx.x) return;
    for (int k = 0; k < K; k++) {
        unsigned long long t0 = gtimer();
        nvshmem_putmem_signal_nbi(dst, src, bytes, sig, 1ull, NVSHMEM_SIGNAL_ADD, peer);
        nvshmem_quiet();
        times_ns[k] = (unsigned int)(gtimer() - t0);
    }
    *err = nvshmemx_ibgda_ft_status(peer) ? 1 : 0;
}

struct RecvResult {
    int arrived, cancelled;
    unsigned long long mismatch;
    unsigned long long sig;
};

__global__ void recv_kernel(const unsigned char *buf, size_t bytes, uint64_t *sig, uint64_t expect,
                            int it, int mode, long long budget, RecvResult *out) {
    __shared__ int s_arrived, s_cancel;
    if (threadIdx.x == 0) {
        int got;
        if (mode == 1) {
            nvshmem_signal_wait_until(sig, NVSHMEM_CMP_GE, expect);
            got = 1;
        } else {
            long long t0 = clock64();
            while (*(volatile uint64_t *)sig < expect) {
                if (clock64() - t0 > budget) break;
            }
            got = (*(volatile uint64_t *)sig >= expect);
        }
        uint64_t v = *(volatile uint64_t *)sig;
        s_arrived = got;
        s_cancel = (v >= CANCEL_MARK);
        out->sig = v;
        out->mismatch = 0;
    }
    __syncthreads();
    if (!s_arrived || s_cancel) {
        if (threadIdx.x == 0) {
            out->arrived = s_arrived;
            out->cancelled = s_cancel;
        }
        return;
    }
    unsigned long long bad = 0;
    for (size_t b = threadIdx.x; b < bytes; b += blockDim.x)
        if (buf[b] != patByte(it, b)) bad++;
    atomicAdd(&out->mismatch, bad);
    __syncthreads();
    if (threadIdx.x == 0) {
        out->arrived = 1;
        out->cancelled = 0;
    }
}

__global__ void sentinel_kernel(unsigned int poll_ns) { nvshmemx_ibgda_ft_sentinel(poll_ns); }

// v2 F2a: canary fill / check of the region a misdirected put would hit (outside dbuf).
__host__ __device__ static inline unsigned char canByte(size_t b) { return (unsigned char)(0xa5 ^ (b * 131)); }
__global__ void canary_fill(unsigned char *p, size_t n) {
    for (size_t b = blockIdx.x * blockDim.x + threadIdx.x; b < n; b += gridDim.x * blockDim.x) p[b] = canByte(b);
}
__global__ void canary_check(const unsigned char *p, size_t n, unsigned long long *bad) {
    unsigned long long k = 0;
    for (size_t b = blockIdx.x * blockDim.x + threadIdx.x; b < n; b += gridDim.x * blockDim.x)
        if (p[b] != canByte(b)) k++;
    atomicAdd(bad, k);
}
__global__ void pattern_check(const unsigned char *p, size_t n, int it, unsigned long long *bad) {
    unsigned long long k = 0;
    for (size_t b = blockIdx.x * blockDim.x + threadIdx.x; b < n; b += gridDim.x * blockDim.x)
        if (p[b] != patByte(it, b)) k++;
    atomicAdd(bad, k);
}

__global__ void gtimer_kernel(volatile unsigned long long *out) { *out = gtimer(); }

// ---------------------------------------------------------------- host helpers
static void hangWatchdog(int) {
    static const char m[] = "WATCHDOG: kernel/teardown did not return; exiting 7\n";
    ssize_t w = write(2, m, sizeof(m) - 1);
    (void)w;
    _exit(7);
}

// %globaltimer (ns) -> CLOCK_MONOTONIC (ms): offset from the tightest of 50 bracketed samples.
static double g_gt_off_ms = 0, g_gt_err_ms = 1e9;
static void calibrateGtimer() {
    unsigned long long *m;
    CK(cudaHostAlloc(&m, sizeof(*m), cudaHostAllocMapped));
    for (int i = 0; i < 50; i++) {
        double a = monoMs();
        gtimer_kernel<<<1, 1>>>(m);
        CK(cudaDeviceSynchronize());
        double b = monoMs();
        double err = (b - a) / 2;
        if (err < g_gt_err_ms) {
            g_gt_err_ms = err;
            g_gt_off_ms = (a + b) / 2 - (double)(*m) * 1e-6;
        }
    }
    CK(cudaFreeHost(m));
}
static double gtToMono(unsigned long long gt) { return gt ? (double)gt * 1e-6 + g_gt_off_ms : 0; }

// v2: init diagnostic (NVFT_INIT_DIAG_S). If init and the first barrier have not finished after
// the delay, copy the IBGDA device state and the first CQ slots of the RC QP to the peer and of
// DCI 0 on a separate non-blocking stream and print them (a hung kernel does not block the copy).
static std::atomic<int> g_phase(0);
static int g_diag_peer = 1;
static void dumpQp(cudaStream_t s, const char *tag, nvshmemi_ibgda_device_qp_t *qp_d) {
    nvshmemi_ibgda_device_qp_t qp;
    if (cudaMemcpyAsync(&qp, qp_d, sizeof(qp), cudaMemcpyDeviceToHost, s) || cudaStreamSynchronize(s)) {
        fprintf(stderr, "INITDIAG %s: qp copy failed\n", tag);
        return;
    }
    nvshmemi_ibgda_device_cq_t cq;
    if (!qp.tx_wq.cq || cudaMemcpyAsync(&cq, qp.tx_wq.cq, sizeof(cq), cudaMemcpyDeviceToHost, s) ||
        cudaStreamSynchronize(s)) {
        fprintf(stderr, "INITDIAG %s: cq copy failed\n", tag);
        return;
    }
    fprintf(stderr, "INITDIAG %s qpn=0x%x cqn=0x%x ncqes=%u resv=%llu ready=%llu prod=%llu cons=%llu lock=%d\n",
            tag, qp.qpn, cq.cqn, cq.ncqes, (unsigned long long)qp.mvars.tx_wq.resv_head,
            (unsigned long long)qp.mvars.tx_wq.ready_head, (unsigned long long)qp.mvars.tx_wq.prod_idx,
            (unsigned long long)qp.mvars.tx_wq.cons_idx, qp.mvars.post_send_lock);
    unsigned char b[8 * 64];
    if (cudaMemcpyAsync(b, cq.cqe, sizeof(b), cudaMemcpyDeviceToHost, s) || cudaStreamSynchronize(s)) return;
    for (int k = 0; k < 8; k++) {
        const unsigned char *e = b + 64 * k;
        fprintf(stderr, "INITDIAG %s slot %d op_own=0x%02x opcode=0x%x owner=%d wqe_counter=%u syndrome=0x%02x vendor=0x%02x\n",
                tag, k, e[63], e[63] >> 4, e[63] & 1, ((unsigned)e[60] << 8) | e[61], e[55], e[54]);
    }
}
static void *initDiagThread(void *arg) {
    double s = *(double *)arg;
    double t0 = monoMs();
    while (monoMs() - t0 < s * 1000) {
        if (g_phase.load() >= 2) return nullptr;
        usleep(100000);
    }
    fprintf(stderr, "INITDIAG phase=%d after %.1f s: dumping IBGDA queue state\n", g_phase.load(), s);
    cudaStream_t st;
    if (cudaStreamCreateWithFlags(&st, cudaStreamNonBlocking)) return nullptr;
    nvshmemi_ibgda_device_state_t ds;
    if (cudaMemcpyFromSymbolAsync(&ds, nvshmemi_ibgda_device_state_d, sizeof(ds), 0, cudaMemcpyDeviceToHost, st) ||
        cudaStreamSynchronize(st)) {
        fprintf(stderr, "INITDIAG state copy failed\n");
        return nullptr;
    }
    fprintf(stderr, "INITDIAG rcs=%p dcis=%p ft=%p ft_flags=0x%x\n", (void *)ds.globalmem.rcs,
            (void *)ds.globalmem.dcis, ds.ft, ds.ft_flags);
    if (ds.globalmem.rcs) dumpQp(st, "rc_to_peer", &ds.globalmem.rcs[g_diag_peer]);
    if (ds.globalmem.dcis) dumpQp(st, "dci0", &ds.globalmem.dcis[0]);
    return nullptr;
}

int main(int argc, char **argv) {
    if (argc < 5) {
        fprintf(stderr,
                "usage: %s <rank 0|1> <peer_mgmt_ip> <tcp_port> <timeout|blocking> [--iters N] "
                "[--bytes B] [--gap-ms G] [--dev-timeout-ms T] [--recover] [--corrupt-rkey IT] "
                "[--burst N] [--quiet-delay-us D] [--sentinel POLL_NS] [--lat K] [--lat-reps R] "
                "[--max-rounds R]\n",
                argv[0]);
        return 1;
    }
    int rank = atoi(argv[1]);
    g_rank = rank;
    const char *peer_ip = argv[2];
    int port = atoi(argv[3]);
    const char *modestr = argv[4];
    int iters = 40, gap_ms = 15, dev_timeout_ms = 10000, recover = 0, corrupt_at = -1, burst = 1;
    int sentinel = -1, lat = 0, lat_reps = 1, max_rounds = 6, force_at = -1;
    const char *oob = nullptr;  // v2 F2a kind
    int oob_at = -1;
    int mt = 0, mt_reps = 4;  // v2 --mt
    double quiet_delay_us = 0;
    size_t bytes = 256u * 1024u;
    for (int i = 5; i < argc; i++) {
        auto nxt = [&](void) -> const char * { return i + 1 < argc ? argv[++i] : "0"; };
        if (!strcmp(argv[i], "--iters")) iters = atoi(nxt());
        else if (!strcmp(argv[i], "--bytes")) bytes = strtoul(nxt(), 0, 10);
        else if (!strcmp(argv[i], "--gap-ms")) gap_ms = atoi(nxt());
        else if (!strcmp(argv[i], "--dev-timeout-ms")) dev_timeout_ms = atoi(nxt());
        else if (!strcmp(argv[i], "--recover")) recover = 1;
        else if (!strcmp(argv[i], "--corrupt-rkey")) corrupt_at = atoi(nxt());
        else if (!strcmp(argv[i], "--burst")) burst = atoi(nxt());
        else if (!strcmp(argv[i], "--quiet-delay-us")) quiet_delay_us = atof(nxt());
        else if (!strcmp(argv[i], "--sentinel")) sentinel = atoi(nxt());
        else if (!strcmp(argv[i], "--lat")) lat = atoi(nxt());
        else if (!strcmp(argv[i], "--lat-reps")) lat_reps = atoi(nxt());
        else if (!strcmp(argv[i], "--max-rounds")) max_rounds = atoi(nxt());
        else if (!strcmp(argv[i], "--force-rec-at")) force_at = atoi(nxt());
        else if (!strcmp(argv[i], "--oob")) oob = nxt();
        else if (!strcmp(argv[i], "--oob-at")) oob_at = atoi(nxt());
        else if (!strcmp(argv[i], "--mt")) mt = atoi(nxt());
        else if (!strcmp(argv[i], "--mt-reps")) mt_reps = atoi(nxt());
        else {
            fprintf(stderr, "unknown arg %s\n", argv[i]);
            return 1;
        }
    }
    int mode = !strcmp(modestr, "timeout") ? 0 : !strcmp(modestr, "blocking") ? 1 : -1;
    if (oob && strcmp(oob, "exact") && strcmp(oob, "gap") && strcmp(oob, "straddle") &&
        strcmp(oob, "tail") && strcmp(oob, "heap")) {
        fprintf(stderr, "bad --oob kind\n");
        return 1;
    }
    if (mt < 0 || mt > 1024 || (mt && (bytes % (size_t)mt || recover || burst != 1 || mt_reps < 1))) {
        fprintf(stderr, "bad --mt arguments (bytes %% T == 0, no --recover, burst 1)\n");
        return 1;
    }
    if (mode < 0 || (rank != 0 && rank != 1) || iters <= 0 || bytes == 0 || burst < 1) {
        fprintf(stderr, "bad arguments\n");
        return 1;
    }
    signal(SIGPIPE, SIG_IGN);
    if (getenv("NVFT_ACK_LIMIT_S")) g_ack_limit_s = atof(getenv("NVFT_ACK_LIMIT_S"));
    if (getenv("NVFT_RX_LIMIT_S")) g_rx_limit_s = atof(getenv("NVFT_RX_LIMIT_S"));
    if (getenv("NVFT_TEARDOWN_S")) g_teardown_s = atof(getenv("NVFT_TEARDOWN_S"));

    // --- unique-id bootstrap over TCP on the management network; the socket stays open (OOB) ---
    int one = 1;
    nvshmemx_uniqueid_t id = NVSHMEMX_UNIQUEID_INITIALIZER;
    if (rank == 0) {
        nvshmemx_get_uniqueid(&id);
        int ls = socket(AF_INET, SOCK_STREAM, 0);
        setsockopt(ls, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
        sockaddr_in a{};
        a.sin_family = AF_INET;
        a.sin_addr.s_addr = INADDR_ANY;
        a.sin_port = htons(port);
        if (bind(ls, (sockaddr *)&a, sizeof a)) {
            perror("bind");
            return 1;
        }
        listen(ls, 1);
        struct pollfd p = {ls, POLLIN, 0};
        if (poll(&p, 1, 60000) <= 0) {
            fprintf(stderr, "[PE0] PE1 did not connect in 60 s\n");
            return 1;
        }
        g_sock = accept(ls, 0, 0);
        close(ls);
        setsockopt(g_sock, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
        if (sendall(g_sock, &id, sizeof id)) {
            perror("send id");
            return 1;
        }
    } else {
        sockaddr_in a{};
        a.sin_family = AF_INET;
        a.sin_port = htons(port);
        inet_pton(AF_INET, peer_ip, &a.sin_addr);
        for (int tries = 0;; tries++) {
            g_sock = socket(AF_INET, SOCK_STREAM, 0);
            if (connect(g_sock, (sockaddr *)&a, sizeof a) == 0) break;
            close(g_sock);
            if (tries > 300) {
                fprintf(stderr, "[PE1] cannot reach PE0\n");
                return 1;
            }
            usleep(200000);
        }
        setsockopt(g_sock, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
        if (recvall(g_sock, &id, sizeof id)) {
            perror("recv id");
            return 1;
        }
    }

    g_diag_peer = 1 - rank;
    static double diag_s = 0;
    if (getenv("NVFT_INIT_DIAG_S")) diag_s = atof(getenv("NVFT_INIT_DIAG_S"));
    if (diag_s > 0) {
        pthread_t th;
        pthread_create(&th, nullptr, initDiagThread, &diag_s);
        pthread_detach(th);
    }
    nvshmemx_init_attr_t attr = NVSHMEMX_INIT_ATTR_INITIALIZER;
    nvshmemx_set_attr_uniqueid_args(rank, NRANKS, &id, &attr);
    if (nvshmemx_init_attr(NVSHMEMX_INIT_WITH_UNIQUEID, &attr)) {
        fprintf(stderr, "[PE%d] nvshmemx_init_attr failed\n", rank);
        return 2;
    }
    g_phase.store(1);
    fprintf(stderr, "[PE%d] PHASE init returned\n", rank);
    int mype = nvshmem_my_pe(), npes = nvshmem_n_pes();
    if (npes != NRANKS) return 2;
    int peer = 1 - mype;
    CK(cudaSetDevice(0));

    cudaDeviceProp prop;
    CK(cudaGetDeviceProperties(&prop, 0));
    const long long cyc_per_ms = (long long)prop.clockRate;  // kHz
    const long long budget = (long long)dev_timeout_ms * cyc_per_ms;
    const long long delay_cycles = (long long)(quiet_delay_us * cyc_per_ms / 1000.0);

    char *dbuf = (char *)nvshmem_malloc(bytes);
    fprintf(stderr, "[PE%d] PHASE malloc dbuf returned\n", rank);
    char *gapbuf = (oob && !strcmp(oob, "gap")) ? (char *)nvshmem_malloc(bytes) : nullptr;
    char *sbuf = (char *)nvshmem_malloc(bytes);
    fprintf(stderr, "[PE%d] PHASE malloc sbuf returned\n", rank);
    uint64_t *sig = (uint64_t *)nvshmem_malloc(sizeof(uint64_t));
    char *tbuf = (oob && !strcmp(oob, "tail")) ? (char *)nvshmem_malloc(bytes) : nullptr;
    if (!dbuf || !sbuf || !sig) return 2;
    if (gapbuf) nvshmem_free(gapbuf);  // leaves a free hole of `bytes` right after dbuf
    // v2 F2a: the misdirected destination and the canary region (outside dbuf) on the peer
    char *bad_dst = nullptr, *can = nullptr;
    size_t can_len = bytes;
    if (oob) {
        if (!strcmp(oob, "exact") || !strcmp(oob, "gap")) bad_dst = dbuf + bytes;
        else if (!strcmp(oob, "straddle")) bad_dst = dbuf + bytes / 2;
        else if (!strcmp(oob, "tail")) bad_dst = tbuf + bytes;
        // heap: set below to heap_base + heap_size (the first byte past the symmetric heap)
        if (strcmp(oob, "heap")) can = !strcmp(oob, "tail") ? tbuf + bytes : dbuf + bytes;
        if (!strcmp(oob, "straddle")) can_len = bytes / 2;
    }
    {
        nvshmemi_device_host_state_t hs;
        CK(cudaMemcpyFromSymbol(&hs, nvshmemi_device_state_d, sizeof(hs)));
        uintptr_t hb = (uintptr_t)hs.heap_base;
        if (oob && !strcmp(oob, "heap")) bad_dst = (char *)(hb + hs.heap_size);
        printf("LAYOUT rank %d heap_base=%p heap_size=%zu dbuf=+0x%lx sbuf=+0x%lx sig=+0x%lx tbuf=%s0x%lx "
               "gap_freed=%d oob=%s oob_at=%d bad_dst=+0x%lx canary=+0x%lx/%zu\n",
               mype, (void *)hb, hs.heap_size, (unsigned long)((uintptr_t)dbuf - hb),
               (unsigned long)((uintptr_t)sbuf - hb), (unsigned long)((uintptr_t)sig - hb),
               tbuf ? "+" : "-", tbuf ? (unsigned long)((uintptr_t)tbuf - hb) : 0ul, gapbuf ? 1 : 0,
               oob ? oob : "-", oob_at, bad_dst ? (unsigned long)((uintptr_t)bad_dst - hb) : 0ul,
               can ? (unsigned long)((uintptr_t)can - hb) : 0ul, can ? can_len : 0);
        fflush(stdout);
    }
    CK(cudaMemset(sig, 0, sizeof(uint64_t)));
    CK(cudaMemset(dbuf, 0, bytes));
    if (can && mype == 1) canary_fill<<<32, 256>>>((unsigned char *)can, can_len);
    CK(cudaDeviceSynchronize());

    PutResult *pr;
    RecvResult *rr;
    uint64_t *pin64;  // pinned staging for side-stream signal reads/writes
    CK(cudaHostAlloc(&pr, sizeof(*pr), cudaHostAllocMapped));
    CK(cudaHostAlloc(&rr, sizeof(*rr), cudaHostAllocMapped));
    CK(cudaHostAlloc(&pin64, 2 * sizeof(uint64_t), cudaHostAllocDefault));
    cudaStream_t side, mainS;
    CK(cudaStreamCreateWithFlags(&side, cudaStreamNonBlocking));
    CK(cudaStreamCreateWithFlags(&mainS, cudaStreamNonBlocking));
    std::vector<char> hsrc(bytes);

    calibrateGtimer();
    // Clock offset rank1 - rank0 (CLOCK_MONOTONIC), min-RTT of 30 ping-pongs over the OOB socket.
    double off10 = 0, best_rtt = 1e9;
    for (int i = 0; i < 30; i++) {
        Msg m;
        if (mype == 0) {
            double a = monoMs();
            sendMsg(M_PING, i, 0);
            if (recvMsg(&m, 5000) != 1 || m.type != M_PONG) {
                fprintf(stderr, "[PE0] clock sync failed\n");
                return 8;
            }
            double b = monoMs();
            if (b - a < best_rtt) {
                best_rtt = b - a;
                off10 = m.t - (a + b) / 2;
            }
        } else {
            if (recvMsg(&m, 5000) != 1 || m.type != M_PING) {
                fprintf(stderr, "[PE1] clock sync failed\n");
                return 8;
            }
            sendMsg(M_PONG, i, 0);
        }
    }
    fprintf(stderr, "[PE%d] ready: mode=%s iters=%d bytes=%zu gap=%dms devto=%dms recover=%d burst=%d "
                    "quiet_delay_us=%.1f sentinel=%d lat=%d gt_off_err_us=%.1f mt=%d mt_reps=%d\n",
            mype, modestr, iters, bytes, gap_ms, dev_timeout_ms, recover, burst, quiet_delay_us,
            sentinel, lat, g_gt_err_ms * 1e3, mt, mt_reps);
    printf("CLOCK rank %d mono_minus_real_ms=%.3f gt_off_ms=%.6f gt_err_us=%.1f off_r1_minus_r0_ms=%.3f "
           "rtt_ms=%.3f\n",
           mype, monoMs() - realMs(), g_gt_off_ms, g_gt_err_ms * 1e3, off10, best_rtt);
    fflush(stdout);

    nvshmem_barrier_all();  // one healthy sync before any fault
    g_phase.store(2);
    fprintf(stderr, "[PE%d] PHASE first barrier returned\n", mype);
    // The IBGDA transport is loaded and connected lazily (during the first heap allocation), so
    // resolve the FT API only now.
    loadFtApi();
    fprintf(stderr, "[PE%d] FT api %s (version %d)\n", mype, FT.on ? "on" : "off", FT.on);

    // Warm every kernel this rank may launch while another of its kernels runs (local-memory
    // sizing; see gin_recovery), then start the sentinel if asked.
    if (mype == 0) {
        put_kernel<<<1, 1, 0, mainS>>>(dbuf, sbuf, bytes, sig, peer, mode, budget, 0, 0, pr);
        CK(cudaStreamSynchronize(mainS));
        lat_kernel<<<1, 1, 0, mainS>>>(dbuf, sbuf, bytes, sig, peer, 0, nullptr, &pr->rc);
        CK(cudaStreamSynchronize(mainS));
    } else {
        pin64[0] = 0;
        recv_kernel<<<1, 256, 0, mainS>>>((unsigned char *)dbuf, bytes, sig, 0, -1, 0, 1000, rr);
        CK(cudaStreamSynchronize(mainS));
    }
    cudaStream_t sentS = nullptr;
    if (sentinel >= 0 && FT.on) {
        CK(cudaStreamCreateWithFlags(&sentS, cudaStreamNonBlocking));
        sentinel_kernel<<<1, 1, 0, sentS>>>((unsigned)sentinel);
        CK(cudaGetLastError());
        fprintf(stderr, "[PE%d] device sentinel started (poll_ns=%d)\n", mype, sentinel);
    }

    signal(SIGALRM, hangWatchdog);
    int rc = 0;
    int ok_iters = 0, rec_rounds = 0, rec_ok_ops = 0, declined = 0;
    uint64_t expected_final = 0;

    // ------------------------------------------------------------------------ latency mode
    if (lat > 0) {
        unsigned int *times;
        int *lerr;
        CK(cudaHostAlloc(&times, sizeof(unsigned) * lat, cudaHostAllocMapped));
        CK(cudaHostAlloc(&lerr, sizeof(int), cudaHostAllocMapped));
        for (int rep = 0; rep < lat_reps && rc == 0; rep++) {
            Msg m;
            uint64_t expect = (uint64_t)(rep + 1) * lat;
            alarm(60);
            if (mype == 0) {
                lat_kernel<<<1, 1, 0, mainS>>>(dbuf, sbuf, bytes, sig, peer, lat, times, lerr);
                CK(cudaStreamSynchronize(mainS));
                std::vector<unsigned> v(times, times + lat);
                std::sort(v.begin(), v.end());
                double sum = 0;
                for (unsigned x : v) sum += x;
                printf("LAT rep %d bytes=%zu n=%d p50_us=%.3f p90_us=%.3f p99_us=%.3f max_us=%.3f mean_us=%.3f "
                       "err=%d ft=%d sentinel=%d\n",
                       rep, bytes, lat, v[lat / 2] / 1e3, v[(size_t)(lat * 0.9)] / 1e3,
                       v[(size_t)(lat * 0.99)] / 1e3, v[lat - 1] / 1e3, sum / lat / 1e3, *lerr, FT.on,
                       sentinel);
                fflush(stdout);
                if (recvMsg(&m, 30000) != 1 || m.type != M_ITER_OK) rc = 4;
                if (m.status) rc = 4;
            } else {
                recv_kernel<<<1, 256, 0, mainS>>>((unsigned char *)dbuf, 0, sig, expect, 0, 0,
                                                  30000LL * cyc_per_ms, rr);
                CK(cudaStreamSynchronize(mainS));
                printf("LATRX rep %d arrived=%d sig=%llu\n", rep, rr->arrived, rr->sig);
                fflush(stdout);
                sendMsg(M_ITER_OK, rep, 0, 0, 0, rr->sig, rr->arrived ? 0 : 1);
                if (!rr->arrived) rc = 4;
            }
            alarm(0);
        }
        goto teardown;
    }

    // ------------------------------------------------------------------------ initiator
    if (mype == 0) {
        bool peer_gone = false;
        int gone_iters = 0;
        double t_gone = 0;
        for (int it = 0; it < iters && rc == 0; it++) {
            double t0 = monoMs();
            for (size_t b = 0; b < bytes; b++) hsrc[b] = (char)patByte(it, b);
            CK(cudaMemcpy(sbuf, hsrc.data(), bytes, cudaMemcpyHostToDevice));
            double t_fault_f2 = 0;
            if (it == corrupt_at) {  // F2b: every constmem rkey -> invalid (see ../nvshmem)
                uint32_t bad = 0xdeadbee0u;
                for (int k = 0; k < NVSHMEMI_IBGDA_MAX_CONST_RKEYS; k++) {
                    size_t off = offsetof(nvshmemi_ibgda_device_state_t, constmem.rkeys) +
                                 (size_t)k * sizeof(nvshmemi_ibgda_device_key_t) +
                                 offsetof(nvshmemi_ibgda_device_key_t, key);
                    CK(cudaMemcpyToSymbol(nvshmemi_ibgda_device_state_d, &bad, sizeof(bad), off,
                                          cudaMemcpyHostToDevice));
                }
                // Not cudaDeviceSynchronize(): a running device sentinel never returns.
                CK(cudaStreamSynchronize(0));
                t_fault_f2 = monoMs();
                printf("FAULT F2b corrupt_rkey it=%d fire_mono_ms=%.3f\n", it, t_fault_f2);
                fflush(stdout);
            }
            int nops = burst;
            int round = 0;
            bool done = false;
            while (!done) {
                alarm(mode == 1 ? 90 : (dev_timeout_ms / 1000 + 30));
                memset(pr, 0, sizeof(*pr));
                double tl = monoMs();
                char *pdst = (oob && it == oob_at) ? bad_dst : dbuf;  // v2 F2a
                if (oob && it == oob_at && round == 0) {
                    printf("FAULT F2a oob=%s it=%d dst=%p fire_mono_ms=%.3f\n", oob, it, (void *)pdst, monoMs());
                    fflush(stdout);
                }
                if (mt)
                    mt_put_kernel<<<1, mt, 0, mainS>>>(dbuf, sbuf, bytes, sig, peer, mt_reps, pr);
                else
                put_kernel<<<1, 1, 0, mainS>>>(pdst, sbuf, bytes, sig, peer, mode, budget, nops,
                                               round == 0 ? delay_cycles : 0, pr);
                cudaError_t se = cudaStreamSynchronize(mainS);
                alarm(0);
                double tr = monoMs();
                if (se != cudaSuccess) {
                    fprintf(stderr, "[PE0] it %d kernel error %s\n", it, cudaGetErrorString(se));
                    rc = 6;
                    break;
                }
                printf("ITER %d rank 0 round %d nops=%d rc=%d fp=0x%08x dt_ms=%.3f slot=%x/0x%02x/0x%02x@%u "
                       "ready_head=%llu t_launch=%.3f t_ret=%.3f gt_start_mono=%.3f gt_post_mono=%.3f "
                       "gt_end_mono=%.3f\n",
                       it, round, nops, pr->rc, pr->fp, tr - tl, pr->slot_op, pr->slot_syn, pr->slot_ven,
                       pr->slot_wqe, pr->ready_head, tl, tr, gtToMono(pr->gt_start), gtToMono(pr->gt_post),
                       gtToMono(pr->gt_end));
                fflush(stdout);
                // --force-rec-at: run one recovery round after an operation that succeeded (its ADD
                // executed), to exercise the d = 0 branch.
                const bool forced = recover && pr->rc == 0 && it == force_at && round == 0;
                if (pr->rc == 0 && !forced) {
                    if (round > 0) {
                        rec_ok_ops++;
                        sendMsg(M_DONE, it, round);
                    }
                    done = true;
                    break;
                }
                // ---- error or timeout: classify
                nvshmemt_ibgda_ft_info_t info;
                memset(&info, 0, sizeof(info));
                int have = (FT.on && !forced) ? FT.query(&info, 200) : 0;
                if (forced) snprintf(info.name, sizeof(info.name), "FORCED");
                double tq = monoMs();
                const char *live = peerLiveness();
                printf("FAULTREC it=%d round=%d kernel_rc=%d have=%d class=%s fp=%d/0x%02x syndrome=0x%02x "
                       "opcode=0x%x wqe=%u path=%d trailing=%d upgrade=%d peer=%d qpn=0x%x seq=%u "
                       "t_dev=%.3f t_mbx=%.3f t_ret=%.3f t_query=%.3f liveness=%s fault_f2=%.3f kind=%d "
                       "ring_ci=%llu oob_op=%d oob_off=0x%llx oob_len=%llu oob_chunk_end=0x%llx\n",
                       it, round, pr->rc, have, have ? info.name : (forced ? "FORCED" : "NONE"), info.wc_status, info.vendor_err,
                       info.syndrome, info.opcode, info.wqe_counter, info.path, info.trailing,
                       info.upgrade, info.peer, info.qpn, info.seq, gtToMono(info.gtimer_ns),
                       info.host_mono_ms, tr, tq, live, t_fault_f2, info.kind,
                       (unsigned long long)info.ring_ci, info.oob_op, (unsigned long long)info.oob_off,
                       (unsigned long long)info.oob_len, (unsigned long long)info.oob_chunk_end);
                fflush(stdout);
                // ---- policy
                const char *why = nullptr;
                if (forced) why = nullptr;
                else if (!recover) why = "recovery not enabled (classification run)";
                else if (!have) why = pr->rc == -2 ? "device wait expired, no error record" : "no FT record";
                else if (info.cls == NVSHMEMI_IBGDA_FT_CLASS_LOCAL_QP_ERR) why = nullptr;
                else if (info.cls == NVSHMEMI_IBGDA_FT_CLASS_RETRY_EXC)
                    why = (strncmp(live, "alive", 5) == 0) ? nullptr : "RETRY_EXC with the peer dead";
                else why = "class not recoverable";
                if (!why && round >= max_rounds) why = "too many recovery rounds";
                if (why) {
                    printf("DECLINE it=%d round=%d class=%s reason=\"%s\" t=%.3f\n", it, round,
                           have ? info.name : "NONE", why, monoMs());
                    fflush(stdout);
                    sendMsg(M_FAIL, it, round, info.cls, 0, 0, 0, nullptr, why);
                    if (FT.on) FT.abort(peer);
                    declined = 1;
                    rc = recover ? 9 : 3;
                    break;
                }
                // ---- recovery round
                rec_rounds++;
                nvshmemt_ibgda_ft_token_t tok_i, tok_r;
                nvshmemt_ibgda_ft_stats_t sp, sc;
                double r0 = monoMs();
                int pst = FT.prepare(peer, &tok_i, &sp);
                double r1 = monoMs();
                if (pst) {
                    printf("DECLINE it=%d round=%d reason=\"prepare %d: %s\"\n", it, round, pst, sp.msg);
                    sendMsg(M_FAIL, it, round, info.cls, 0, 0, 0, nullptr, "initiator prepare failed");
                    FT.abort(peer);
                    declined = 1;
                    rc = 9;
                    break;
                }
                sendMsg(M_REQ, it, round, info.cls, 0, 0, 0, &tok_i);
                Msg m;
                int got = 0;
                double dl = monoMs() + 5000;
                while (monoMs() < dl) {
                    int k = recvMsg(&m, 100);
                    if (k < 0) { got = -1; break; }
                    if (k == 1 && m.type == M_ITER_OK && m.it == it) {  // v2: keep it
                        g_stash = m;
                        g_have_stash = true;
                        printf("STASH it=%d ITER_OK received during the handshake\n", it);
                        continue;
                    }
                    if (k == 1 && (m.type == M_ACK || m.type == M_NACK || m.type == M_FAIL)) { got = 1; break; }
                }
                double r2 = monoMs();
                if (got != 1 || m.type != M_ACK) {
                    printf("DECLINE it=%d round=%d reason=\"handshake: %s %s\"\n", it, round,
                           got < 0 ? "peer closed" : got == 0 ? "deadline" : mname(m.type),
                           got == 1 ? m.reason : "");
                    if (got >= 0) sendMsg(M_FAIL, it, round, info.cls, 0, 0, 0, nullptr, "handshake failed");
                    FT.abort(peer);
                    declined = 1;
                    rc = 9;
                    break;
                }
                tok_r = m.tok;
                int cst = FT.commit(peer, &tok_r, &sc);
                double r3 = monoMs();
                if (cst) {
                    printf("DECLINE it=%d round=%d reason=\"commit %d: %s\"\n", it, round, cst, sc.msg);
                    sendMsg(M_FAIL, it, round, info.cls, 0, 0, 0, nullptr, "initiator commit failed");
                    FT.abort(peer);
                    declined = 1;
                    rc = 9;
                    break;
                }
                printf("REC it=%d round=%d class=%s d=%d V=%llu prepare_ms=%.3f (to_err %.3f drain %.3f) "
                       "handshake_ms=%.3f commit_ms=%.3f (rst %.3f resync %.3f connect %.3f dci %u) "
                       "peer_prepare_ms=%.3f peer_commit_ms=%.3f qp_state_before=%u prod_before=%u "
                       "t_ret=%.3f t_commit_done=%.3f ring_ci_old=%llu ring_scan=%u ring_pi=%u skip=0x%x\n",
                       it, round, info.name, m.d, (unsigned long long)m.V, r1 - r0, sp.to_err_ms,
                       sp.drain_ms, r2 - r1, r3 - r2, sc.rst_ms, sc.resync_ms, sc.connect_ms,
                       sc.ndci_reset, (double)m.status / 1000.0, (double)m.pad / 1000.0,
                       sp.qp_state[0], sp.prod_idx[0], tr, r3, (unsigned long long)sc.ring_ci_old[0],
                       sc.ring_scan[0], sc.ring_pi[0], sc.skip_mask);
                fflush(stdout);
                round++;
                if (m.d == 0) {  // the missing work already executed
                    rec_ok_ops++;
                    sendMsg(M_DONE, it, round);
                    printf("REPLAY it=%d round=%d nothing (d=0)\n", it, round);
                    done = true;
                    break;
                }
                nops = m.d;  // replay the last d put+ADD ops only
            }
            if (rc) break;
            if (peer_gone) {
                // The OOB socket closed but the put completed (the dead peer's QP outlives its
                // socket briefly): keep going at the normal pace (a GPU application does not
                // consult the OOB channel per operation) until a put meets the dead peer.
                gone_iters++;
                (void)gone_iters;
                if (monoMs() - t_gone > 10000) {
                    rc = 4;
                    break;
                }
                double el = monoMs() - t0;
                if (el < gap_ms) usleep((useconds_t)((gap_ms - el) * 1000));
                continue;
            }
            // lockstep: the target verified this iteration
            Msg m;
            int k;
            double dl = monoMs() + g_ack_limit_s * 1000.0;
            if (g_have_stash) {  // v2: the target's ITER_OK came during the recovery handshake
                m = g_stash;
                g_have_stash = false;
                k = 1;
            } else {
                do {
                    k = recvMsg(&m, 1000);
                } while (k == 0 && monoMs() < dl);
            }
            if (k < 0) {
                peer_gone = true;
                t_gone = monoMs();
                printf("PEERGONE it=%d t=%.3f liveness=%s (continuing with RDMA only)\n", it, monoMs(),
                       peerLiveness());
                fflush(stdout);
                continue;
            }
            if (k != 1 || m.type != M_ITER_OK || m.it != it) {
                fprintf(stderr, "[PE0] it %d: no ITER_OK (k=%d type=%s it=%d)\n", it, k,
                        k == 1 ? mname(m.type) : "-", k == 1 ? m.it : -1);
                rc = k < 0 ? 4 : 8;
                break;
            }
            if (m.status) {
                printf("ITERFAIL it=%d target_status=%d\n", it, m.status);
                rc = m.status;
                break;
            }
            ok_iters++;
            expected_final = (uint64_t)(it + 1) * (mt ? (uint64_t)mt * mt_reps : (uint64_t)burst);
            double el = monoMs() - t0;
            if (el < gap_ms) usleep((useconds_t)((gap_ms - el) * 1000));
        }
    } else {
        // -------------------------------------------------------------------- target
        int it = 0;
        while (it < iters && rc == 0) {
            uint64_t expect = (uint64_t)(it + 1) * (mt ? (uint64_t)mt * mt_reps : (uint64_t)burst);
            memset(rr, 0, sizeof(*rr));
            recv_kernel<<<1, 256, 0, mainS>>>((unsigned char *)dbuf, bytes, sig, expect, it, mode,
                                              (long long)(dev_timeout_ms * 2) * cyc_per_ms, rr);
            double tl = monoMs();
            bool kdone = false, failed = false;
            int rearm = 0;
            while (!kdone) {
                cudaError_t q = cudaStreamQuery(mainS);
                if (q == cudaSuccess) {
                    if (!rr->arrived && !rr->cancelled && strncmp(peerLiveness(), "alive", 5) == 0 &&
                        rearm < 3 && !failed) {  // timeout mode: re-arm while the peer lives
                        rearm++;
                        printf("REARM it=%d n=%d\n", it, rearm);
                        fflush(stdout);
                        recv_kernel<<<1, 256, 0, mainS>>>((unsigned char *)dbuf, bytes, sig, expect, it,
                                                          mode, (long long)(dev_timeout_ms * 2) * cyc_per_ms, rr);
                        continue;
                    }
                    kdone = true;
                    break;
                }
                if (q != cudaErrorNotReady) {
                    fprintf(stderr, "[PE1] kernel error %s\n", cudaGetErrorString(q));
                    rc = 6;
                    break;
                }
                if (monoMs() - tl > g_rx_limit_s * 1000.0) {
                    fprintf(stderr, "[PE1] it %d: waiter not done in %.0f s (host bound)\n", it, g_rx_limit_s);
                    printf("RXLIMIT it=%d t=%.3f\n", it, monoMs());
                    fflush(stdout);
                    _exit(7);
                }
                Msg m;
                int k = recvMsg(&m, 1);
                if (k < 0) {  // initiator gone: release own waiter, fail
                    if (!failed) {
                        printf("PEERGONE it=%d t=%.3f\n", it, monoMs());
                        fflush(stdout);
                        pin64[0] = CANCEL_MARK;
                        CK(cudaMemcpyAsync(sig, pin64, 8, cudaMemcpyHostToDevice, side));
                        CK(cudaStreamSynchronize(side));
                        if (FT.on) FT.mark_failed();
                        failed = true;
                    }
                    continue;
                }
                if (k == 0) continue;
                if (m.type == M_FAIL) {
                    printf("FAILMSG it=%d req_it=%d reason=\"%s\" t=%.3f\n", it, m.it, m.reason, monoMs());
                    fflush(stdout);
                    pin64[0] = CANCEL_MARK;
                    double c0 = monoMs();
                    CK(cudaMemcpyAsync(sig, pin64, 8, cudaMemcpyHostToDevice, side));
                    CK(cudaStreamSynchronize(side));
                    printf("RELEASE it=%d cancel_write_ms=%.3f\n", it, monoMs() - c0);
                    if (FT.on) FT.abort(peer);
                    failed = true;
                    declined = 1;
                    continue;
                }
                if (m.type == M_DONE) {
                    printf("DONEMSG it=%d req_it=%d round=%d t=%.3f\n", it, m.it, m.round, monoMs());
                    fflush(stdout);
                    continue;
                }
                if (m.type != M_REQ) {
                    fprintf(stderr, "[PE1] unexpected %s\n", mname(m.type));
                    continue;
                }
                // ---- recovery request for m.it (current iteration, or the one just verified)
                double q0 = monoMs();
                nvshmemt_ibgda_ft_token_t tok_r;
                nvshmemt_ibgda_ft_stats_t sp, sc;
                const char *nack = nullptr;
                int d = -1;
                uint64_t V = 0;
                if (!FT.on) nack = "FT off";
                else if (m.it != it && m.it != it - 1) nack = "REQ for an unexpected iteration";
                if (!nack && FT.prepare(peer, &tok_r, &sp)) nack = sp.msg;
                if (!nack) {
                    CK(cudaMemcpyAsync(pin64, sig, 8, cudaMemcpyDeviceToHost, side));
                    CK(cudaStreamSynchronize(side));
                    V = pin64[0];
                    long long dd = (long long)((uint64_t)(m.it + 1) * burst) - (long long)V;
                    if (dd < 0 || dd > burst) nack = "signal outside [expected-burst, expected]";
                    else d = (int)dd;
                }
                double q1 = monoMs();
                if (!nack && FT.commit(peer, &m.tok, &sc)) nack = sc.msg;
                double q2 = monoMs();
                if (nack) {
                    printf("NACK it=%d req_it=%d reason=\"%s\"\n", it, m.it, nack);
                    fflush(stdout);
                    Msg a;
                    memset(&a, 0, sizeof(a));
                    sendMsg(M_NACK, m.it, m.round, 0, 0, V, 0, nullptr, nack);
                    if (FT.on) FT.abort(peer);
                    continue;
                }
                {
                    Msg a;
                    memset(&a, 0, sizeof(a));
                    a.magic = MSG_MAGIC;
                    a.type = M_ACK;
                    a.it = m.it;
                    a.round = m.round;
                    a.d = d;
                    a.V = V;
                    a.status = (int)((q1 - q0) * 1000);  // responder prepare (+V read), us
                    a.pad = (int)((q2 - q1) * 1000);     // responder commit, us
                    a.t = monoMs();
                    a.tok = tok_r;
                    sendall(g_sock, &a, sizeof(a));
                }
                printf("RXREC it=%d req_it=%d round=%d d=%d V=%llu prepare_ms=%.3f (to_err %.3f drain %.3f) "
                       "commit_ms=%.3f (rst %.3f resync %.3f connect %.3f dci %u) qp_state_before=%u "
                       "ring_ci_old=%llu ring_scan=%u ring_pi=%u skip=0x%x\n",
                       it, m.it, m.round, d, (unsigned long long)V, q1 - q0, sp.to_err_ms, sp.drain_ms,
                       q2 - q1, sc.rst_ms, sc.resync_ms, sc.connect_ms, sc.ndci_reset, sp.qp_state[0],
                       (unsigned long long)sc.ring_ci_old[0], sc.ring_scan[0], sc.ring_pi[0], sc.skip_mask);
                fflush(stdout);
            }
            if (rc) break;
            const char *dc = rr->cancelled ? "cancelled"
                             : !rr->arrived ? "missing"
                             : rr->mismatch ? "mismatch"
                                            : "ok";
            printf("ITER %d rank 1 arrived=%d data_check=%s mismatch=%llu sig=%llu expect=%llu dt_ms=%.3f\n",
                   it, rr->arrived, dc, rr->mismatch, rr->sig, (unsigned long long)expect, monoMs() - tl);
            fflush(stdout);
            if (failed || rr->cancelled) {
                rc = declined ? 9 : 4;
                break;
            }
            int st = !rr->arrived ? 4 : rr->mismatch ? 5 : (rr->sig != expect ? 5 : 0);
            sendMsg(M_ITER_OK, it, 0, 0, 0, rr->sig, st);
            if (st) {
                rc = st;
                break;
            }
            ok_iters++;
            expected_final = expect;
            it++;
        }
    }

teardown:
    if (mype == 1 && oob) {  // v2 F2a: was anything written outside dbuf, and is dbuf untouched?
        unsigned long long *bad;
        CK(cudaHostAlloc(&bad, 2 * sizeof(unsigned long long), cudaHostAllocMapped));
        bad[0] = bad[1] = 0;
        if (can) canary_check<<<32, 256, 0, side>>>((const unsigned char *)can, can_len, &bad[0]);
        // dbuf must still hold the last verified iteration's data (oob_at - 1)
        if (oob_at > 0) pattern_check<<<32, 256, 0, side>>>((const unsigned char *)dbuf, bytes, oob_at - 1, &bad[1]);
        CK(cudaStreamSynchronize(side));
        printf("OOBCHECK rank 1 oob=%s oob_at=%d canary_len=%zu canary_bad=%llu dbuf_vs_prev_bad=%llu\n", oob,
               oob_at, can ? can_len : 0, bad[0], bad[1]);
        fflush(stdout);
    }
    {
        // final signal (target) and summary
        uint64_t final_sig = 0;
        CK(cudaMemcpyAsync(pin64, sig, 8, cudaMemcpyDeviceToHost, side));
        CK(cudaStreamSynchronize(side));
        final_sig = pin64[0];
        uint64_t sent_polls = 0;
        if (sentS) {
            int s = FT.sentinel_stop ? FT.sentinel_stop(2000, &sent_polls) : -1;
            fprintf(stderr, "[PE%d] sentinel stop rc=%d polls=%llu\n", mype, s, (unsigned long long)sent_polls);
            cudaStreamSynchronize(sentS);
        }
        printf("SUMMARY rank %d mode=%s rc=%d ok_iters=%d rec_rounds=%d rec_ok_ops=%d declined=%d "
               "final_sig=%llu expected_sig=%llu ft=%d sentinel_polls=%llu\n",
               mype, modestr, rc, ok_iters, rec_rounds, rec_ok_ops, declined,
               (unsigned long long)final_sig, (unsigned long long)expected_final, FT.on,
               (unsigned long long)sent_polls);
        fflush(stdout);
        // Teardown: bounded. After a decline (or any failure) the transport is marked failed and
        // the library skips the device barriers of nvshmem_free/finalize.
        if (rc != 0 && FT.on) FT.mark_failed();
        double td0 = monoMs();
        alarm((unsigned)g_teardown_s);
        nvshmem_free(dbuf);
        nvshmem_free(sbuf);
        nvshmem_free(sig);
        double td1 = monoMs();
        nvshmem_finalize();
        alarm(0);
        printf("TEARDOWN rank %d free_ms=%.1f finalize_ms=%.1f returned=1\n", mype, td1 - td0,
               monoMs() - td1);
        fflush(stdout);
        sendMsg(M_BYE, 0, 0);
        close(g_sock);
    }
    return rc;
}
