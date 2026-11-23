// nvshmem_fault.cu - 2-PE NVSHMEM IBGDA fault-characterization driver (Q2/Q3).
//
// PE0 (rain, initiator) puts M bytes of an (iteration, byte-index) pattern to
// PE1 (sunny, target) with nvshmem_putmem_signal_nbi, then completes the op with
// one of four wait modes; PE1 waits for the signal and verifies every byte.
//
//   wait_mode = timeout      PE0 runs its OWN bounded CQ poll (clock64), which
//                            reads the collapsed CQ's wqe_counter AND op_own and
//                            classifies REQ_ERR itself; PE1 bounded-spins on the
//                            signal word. Neither side calls the library's
//                            unbounded ibgda_quiet.
//   wait_mode = blocking     PE0 calls the library nvshmem_quiet() (its poll_cq
//                            has the on-error assert compiled out under NDEBUG,
//                            so it returns even on an error CQE). Bounded only by
//                            a host-side alarm() watchdog.
//   wait_mode = deepep_poll  PE0 runs a bounded poll that spins on wqe_counter
//                            ONLY, never inspecting op_own for the success/return
//                            decision - the DeepEP-legacy behaviour - to show
//                            whether an error CQE is taken as success.
//
// Q3: after the wait ends (success or bounded-spin expiry) PE0's device code
// reads the collapsed CQ slot of the RC QP it used, through the internal device
// state in the non_abi headers, and records op_own>>4, syndrome (byte 55),
// vendor_err_synd (byte 54), wqe_counter (bytes 60-61 BE) and qpn into
// host-mapped memory; the host logs them.
//
// Faults are injected out of band: F1/F3 by the NVSHMEM_IBGDA_FAULT_INJECT test
// hook (QP->ERR), F2 by passing --oob (PE0 puts past the end of the peer's
// symmetric heap), F4 by the runner SIGKILLing PE1. This driver only performs
// the transfer and the measurement; it never brings the link down.
//
// Bootstrap: unique-ID over our own TCP socket on the management network (no MPI).
// Every wait is bounded (device clock64 budget or host alarm watchdog).
//
// Exit codes: 0 all iterations ok (baseline), 1 usage/setup, 2 nvshmem/init,
// 3 an initiator error/timeout was observed (fault surfaced), 4 target
// timeout/missing, 5 data mismatch, 6 CUDA error, 7 host watchdog (hang).
//
//   usage: nvshmem_fault <rank 0|1> <peer_mgmt_ip> <tcp_port>
//                        <timeout|blocking|deepep_poll|snapshot>
//                        [iters] [msg_bytes] [cadence_ms] [dev_timeout_ms] [--oob] [--burst N]
#include <nvshmem.h>
#include <nvshmemx.h>
#include "device_host_transport/nvshmem_common_ibgda.h"  // device state + QP/CQ structs

#include <cuda_runtime.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cstdint>
#include <ctime>
#include <unistd.h>
#include <csignal>
#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <sys/socket.h>

static const int NRANKS = 2;
static int g_rank = -1;

#define CK(c)                                                                                    \
    do {                                                                                         \
        cudaError_t e_ = (c);                                                                    \
        if (e_ != cudaSuccess) {                                                                 \
            fprintf(stderr, "[PE%d] CUDA %s:%d %s\n", g_rank, __FILE__, __LINE__,                \
                    cudaGetErrorString(e_));                                                     \
            exit(6);                                                                             \
        }                                                                                        \
    } while (0)

// -------- host TCP unique-id exchange (management network, no MPI) ------------
static int sendall(int fd, const void *b, size_t n) {
    const char *p = (const char *)b;
    size_t o = 0;
    while (o < n) {
        ssize_t k = send(fd, p + o, n - o, 0);
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

static double nowSec() {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec + t.tv_nsec * 1e-9;
}

// Per-iteration (iteration, byte-index) pattern byte. Distinct per iteration so
// stale data from a previous iteration compares unequal (acts as its own poison).
__host__ __device__ static inline unsigned char patByte(int it, size_t b) {
    uint32_t h = (uint32_t)(b * 2654435761u) ^ (uint32_t)((it + 1) * 40503u);
    h ^= h >> 13;
    return (unsigned char)(h & 0xff);
}

// -------- host-mapped mailbox that the device fills after the wait -----------
struct cqe_probe {
    int wait_rc;              // 0 ok, 1 bounded-timeout, 2 REQ_ERR seen (only when classified)
    unsigned int qpn;         // RC QP the put used
    unsigned int cqn;
    unsigned int ncqes;
    unsigned char op_own;     // raw CQE byte 63
    unsigned char opcode;     // op_own >> 4  (13/0xd == MLX5_CQE_REQ_ERR)
    unsigned char syndrome;   // CQE byte 55
    unsigned char vendor_err; // CQE byte 54
    unsigned int wqe_counter; // CQE bytes 60-61 (BE)
    unsigned long long cons_idx;
    unsigned long long ready_head;
    unsigned long long wait_cycles;
};

// One recorded transition of the collapsed CQ slot (continuous-snapshot mode).
struct cqe_sample {
    unsigned long long t_cycles;  // clock64() at first observation of this tuple
    unsigned char opcode;         // op_own >> 4
    unsigned char syndrome;       // byte 55
    unsigned char vendor_err;     // byte 54
    unsigned int wqe_counter;     // bytes 60-61 BE
};

// Full-buffer scan result: an opcode histogram over EVERY entry of a CQ buffer
// (not just slot 0), plus full detail of any error-class CQE (opcode 0xd/0xe).
struct cq_scan {
    unsigned int rc_ncqes, dci_ncqes;
    unsigned int rc_hist[16];   // count of entries by op_own>>4 in the RC send CQ
    unsigned int dci_hist[16];  // ... in the DCI send CQ
    int ndet;                   // number of detail entries captured
    struct {
        unsigned int which;     // 0 = RC tx CQ, 1 = DCI tx CQ
        unsigned int idx;       // entry index in the CQ buffer
        unsigned char opcode;   // op_own >> 4
        unsigned char syndrome; // byte 55
        unsigned char vendor;   // byte 54
        unsigned int wqe;       // bytes 60-61 BE
        unsigned int sqopqpn;   // s_wqe_opcode_qpn, bytes 56-59 BE
    } det[16];
};

// Scan every 64-byte entry of one CQ buffer; bump the histogram and, for any
// error-class opcode (0xd REQ_ERR / 0xe RESP_ERR), record full detail.
__device__ static void scan_one_cq(nvshmemi_ibgda_device_cq_t *cq, unsigned int which,
                                    unsigned int *hist, cq_scan *s) {
    if (!cq || !cq->cqe) return;
    unsigned int n = cq->ncqes;
    volatile unsigned char *base = (volatile unsigned char *)cq->cqe;
    for (unsigned int i = 0; i < n; i++) {
        volatile unsigned char *c = base + (size_t)i * 64;
        unsigned char op = (unsigned char)(c[63] >> 4);
        hist[op & 0xf]++;
        if ((op == 0xd || op == 0xe) && s->ndet < 16) {
            int k = s->ndet++;
            s->det[k].which = which;
            s->det[k].idx = i;
            s->det[k].opcode = op;
            s->det[k].syndrome = c[55];
            s->det[k].vendor = c[54];
            s->det[k].wqe = (unsigned int)(((unsigned int)c[60] << 8) | c[61]);
            s->det[k].sqopqpn = (unsigned int)(((unsigned int)c[56] << 24) |
                                               ((unsigned int)c[57] << 16) |
                                               ((unsigned int)c[58] << 8) | c[59]);
        }
    }
}

// Scan the RC(peer) send CQ and the DCI[0] send CQ in full.
__device__ static void scan_all_cqs(int peer, cq_scan *s) {
    for (int i = 0; i < 16; i++) { s->rc_hist[i] = 0; s->dci_hist[i] = 0; }
    s->ndet = 0;
    nvshmemi_ibgda_device_qp_t *rc = &nvshmemi_ibgda_device_state_d.globalmem.rcs[peer];
    s->rc_ncqes = rc->tx_wq.cq ? rc->tx_wq.cq->ncqes : 0;
    scan_one_cq(rc->tx_wq.cq, 0, s->rc_hist, s);
    nvshmemi_ibgda_device_qp_t *dci = nvshmemi_ibgda_device_state_d.globalmem.dcis
                                          ? &nvshmemi_ibgda_device_state_d.globalmem.dcis[0]
                                          : nullptr;
    s->dci_ncqes = (dci && dci->tx_wq.cq) ? dci->tx_wq.cq->ncqes : 0;
    if (dci) scan_one_cq(dci->tx_wq.cq, 1, s->dci_hist, s);
}

// Read the collapsed CQ slot of rcs[peer] into the probe (Q3). op_own etc. read
// as raw bytes so the layout matches mlx5_cqe64 / mlx5_err_cqe exactly.
__device__ static void read_cqe(int peer, cqe_probe *pb) {
    nvshmemi_ibgda_device_qp_t *qp = &nvshmemi_ibgda_device_state_d.globalmem.rcs[peer];
    nvshmemi_ibgda_device_cq_t *cq = qp->tx_wq.cq;
    volatile unsigned char *c = (volatile unsigned char *)cq->cqe;
    pb->qpn = qp->qpn;
    pb->cqn = cq->cqn;
    pb->ncqes = cq->ncqes;
    pb->op_own = c[63];
    pb->opcode = (unsigned char)(c[63] >> 4);
    pb->vendor_err = c[54];
    pb->syndrome = c[55];
    pb->wqe_counter = (unsigned int)(((unsigned int)c[60] << 8) | (unsigned int)c[61]);
    pb->cons_idx = cq->cons_idx ? *cq->cons_idx : 0ull;
    pb->ready_head = qp->mvars.tx_wq.ready_head;
}

// -------- PE0 (initiator) kernel ---------------------------------------------
// mode: 0 timeout, 1 blocking, 2 deepep_poll, 3 snapshot.
// burst: number of put_signal_nbi posted before the wait (each adds 1 to the
//        signal), so burst>1 leaves more WQEs outstanding behind a failing one.
__global__ void put_kernel(char *dst, const char *src, size_t bytes, uint64_t *sig,
                           int peer, int mode, unsigned long long budget, int burst,
                           cqe_probe *pb, cqe_sample *ring, int ring_cap, int *ring_len,
                           cq_scan *scan) {
    if (threadIdx.x || blockIdx.x) return;

    // Post burst RDMA write + signal atomics on the RC QP (non-blocking: no quiet).
    for (int i = 0; i < burst; i++) {
        nvshmem_putmem_signal_nbi(dst, src, bytes, sig, 1ull, NVSHMEM_SIGNAL_ADD, peer);
    }

    nvshmemi_ibgda_device_qp_t *qp = &nvshmemi_ibgda_device_state_d.globalmem.rcs[peer];
    nvshmemi_ibgda_device_cq_t *cq = qp->tx_wq.cq;
    volatile unsigned char *c = (volatile unsigned char *)cq->cqe;
    const unsigned int ncqes = cq->ncqes;
    uint64_t target = qp->mvars.tx_wq.ready_head;  // wqe idx + 1 we must see complete

    int wait_rc = 0;
    unsigned long long t0 = clock64();
    unsigned long long spent = 0;

    if (mode == 3) {
        // snapshot: continuously record every change of the collapsed CQ slot
        // for the whole budget, so we can see whether the root-cause CQE is ever
        // observable and for how long before flush CQEs overwrite slot 0.
        unsigned char lop = 0xff, lsyn = 0xff, lven = 0xff;
        unsigned int lwqe = 0xffffffffu;
        int n = 0;
        for (;;) {
            unsigned char op = (unsigned char)(c[63] >> 4);
            unsigned char syn = c[55], ven = c[54];
            unsigned int wqe = (unsigned int)(((unsigned int)c[60] << 8) | (unsigned int)c[61]);
            if (op != lop || syn != lsyn || ven != lven || wqe != lwqe) {
                if (n < ring_cap) {
                    ring[n].t_cycles = clock64() - t0;
                    ring[n].opcode = op;
                    ring[n].syndrome = syn;
                    ring[n].vendor_err = ven;
                    ring[n].wqe_counter = wqe;
                    n++;
                }
                lop = op; lsyn = syn; lven = ven; lwqe = wqe;
            }
            if ((unsigned long long)(clock64() - t0) > budget) break;
        }
        *ring_len = n;
        spent = clock64() - t0;
    } else if (mode == 1) {
        // blocking: the library's own unbounded completion path.
        nvshmem_quiet();
        spent = clock64() - t0;
    } else {
        // timeout / deepep_poll: our own bounded poll on the collapsed CQ.
        for (;;) {
            unsigned int wqe = (unsigned int)(((unsigned int)c[60] << 8) | (unsigned int)c[61]);
            // Same completion test as ibgda_poll_cq: done when wqe_counter+1 >= target.
            bool done = !((uint16_t)((uint16_t)target - (uint16_t)wqe - (uint16_t)2) < ncqes);
            if (mode == 0) {
                // timeout mode also classifies the error CQE itself.
                unsigned char opcode = (unsigned char)(c[63] >> 4);
                if (opcode == 13 /* MLX5_CQE_REQ_ERR */) {
                    wait_rc = 2;
                    break;
                }
            }
            if (done) {  // deepep_poll: decides success on wqe_counter alone.
                wait_rc = 0;
                break;
            }
            spent = clock64() - t0;
            if (spent > budget) {
                wait_rc = 1;
                break;
            }
        }
        if (spent == 0) spent = clock64() - t0;
    }

    __threadfence_system();
    read_cqe(peer, pb);
    if (scan) scan_all_cqs(peer, scan);  // full-buffer scan of RC + DCI send CQs
    pb->wait_rc = wait_rc;
    pb->wait_cycles = spent;
}

// -------- PE1 (target) kernel ------------------------------------------------
// Waits (bounded in timeout/deepep modes, library-unbounded in blocking mode)
// for the signal to reach expect, then compares every byte.
__global__ void recv_kernel(const char *buf, size_t bytes, uint64_t *sig, uint64_t expect, int it,
                            int mode, unsigned long long budget, int *arrived,
                            unsigned long long *mismatch) {
    if (threadIdx.x || blockIdx.x) return;
    int got = 0;
    if (mode == 1) {
        nvshmem_signal_wait_until(sig, NVSHMEM_CMP_GE, expect);  // unbounded; host watchdog bounds it
        got = 1;
    } else {
        unsigned long long t0 = clock64();
        while (*(volatile uint64_t *)sig < expect) {
            if ((unsigned long long)(clock64() - t0) > budget) break;
        }
        got = (*(volatile uint64_t *)sig >= expect);
    }
    *arrived = got;
    unsigned long long bad = 0;
    if (got) {
        for (size_t b = 0; b < bytes; b++) {
            if ((unsigned char)buf[b] != patByte(it, b)) bad++;
        }
    }
    *mismatch = bad;
}

// -------- host watchdog for a possibly-hung kernel ---------------------------
static void hangWatchdog(int) {
    static const char m[] = "WATCHDOG: kernel/quiet did not return; exiting 7\n";
    ssize_t w = write(2, m, sizeof(m) - 1);
    (void)w;
    _exit(7);
}

int main(int argc, char **argv) {
    if (argc < 5) {
        fprintf(stderr,
                "usage: %s <rank 0|1> <peer_mgmt_ip> <tcp_port> "
                "<timeout|blocking|deepep_poll|snapshot> "
                "[iters] [msg_bytes] [cadence_ms] [dev_timeout_ms] [--oob] [--burst N]\n",
                argv[0]);
        return 1;
    }
    int rank = atoi(argv[1]);
    g_rank = rank;
    const char *peer_ip = argv[2];
    int port = atoi(argv[3]);
    const char *modestr = argv[4];
    int iters = argc > 5 ? atoi(argv[5]) : 8;
    size_t bytes = argc > 6 ? strtoul(argv[6], 0, 10) : (256u * 1024u);
    int cadence_ms = argc > 7 ? atoi(argv[7]) : 200;
    int dev_timeout_ms = argc > 8 ? atoi(argv[8]) : 800;
    int oob = 0, burst = 1, corrupt_rkey_at = -1, prefault_ms = 0;
    for (int i = 5; i < argc; i++) {
        if (!strcmp(argv[i], "--oob")) oob = 1;
        else if (!strcmp(argv[i], "--burst") && i + 1 < argc) burst = atoi(argv[i + 1]);
        else if (!strcmp(argv[i], "--corrupt-rkey") && i + 1 < argc) corrupt_rkey_at = atoi(argv[i + 1]);
        // Sleep <ms> after the post-init barrier, before iteration 0's put, so a
        // hook-injected fault (small FAULT_MS) has already fired -> the very first
        // put is the failing one. Needed for cc=0 A/B runs (ITERS=1).
        else if (!strcmp(argv[i], "--prefault-ms") && i + 1 < argc) prefault_ms = atoi(argv[i + 1]);
    }
    if (burst < 1) burst = 1;

    int mode = -1;
    if (!strcmp(modestr, "timeout"))
        mode = 0;
    else if (!strcmp(modestr, "blocking"))
        mode = 1;
    else if (!strcmp(modestr, "deepep_poll"))
        mode = 2;
    else if (!strcmp(modestr, "snapshot"))
        mode = 3;
    if (mode < 0 || (rank != 0 && rank != 1) || iters <= 0 || bytes == 0) {
        fprintf(stderr, "bad arguments\n");
        return 1;
    }

    // --- unique-id bootstrap over TCP on the management network ---
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
        fprintf(stderr, "[PE0] waiting for PE1 on :%d\n", port);
        int cs = accept(ls, 0, 0);
        setsockopt(cs, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
        if (sendall(cs, &id, sizeof id)) {
            perror("send id");
            return 1;
        }
        close(cs);
        close(ls);
    } else {
        sockaddr_in a{};
        a.sin_family = AF_INET;
        a.sin_port = htons(port);
        inet_pton(AF_INET, peer_ip, &a.sin_addr);
        int cs = -1;
        for (int tries = 0;; tries++) {
            cs = socket(AF_INET, SOCK_STREAM, 0);
            if (connect(cs, (sockaddr *)&a, sizeof a) == 0) break;
            close(cs);
            if (tries > 600) {
                fprintf(stderr, "[PE1] cannot reach PE0\n");
                return 1;
            }
            usleep(200000);
        }
        setsockopt(cs, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
        if (recvall(cs, &id, sizeof id)) {
            perror("recv id");
            return 1;
        }
        close(cs);
    }

    nvshmemx_init_attr_t attr = NVSHMEMX_INIT_ATTR_INITIALIZER;
    nvshmemx_set_attr_uniqueid_args(rank, NRANKS, &id, &attr);
    if (nvshmemx_init_attr(NVSHMEMX_INIT_WITH_UNIQUEID, &attr)) {
        fprintf(stderr, "[PE%d] nvshmemx_init_attr failed\n", rank);
        return 2;
    }
    int mype = nvshmem_my_pe();
    int npes = nvshmem_n_pes();
    if (npes != NRANKS) {
        fprintf(stderr, "[PE%d] npes=%d (expected 2)\n", mype, npes);
        return 2;
    }
    int peer = 1 - mype;
    CK(cudaSetDevice(0));

    // Clock rate -> convert the bounded device budget from ms to SM cycles.
    cudaDeviceProp prop;
    CK(cudaGetDeviceProperties(&prop, 0));
    unsigned long long budget = (unsigned long long)dev_timeout_ms * (unsigned long long)prop.clockRate;  // kHz*ms

    // Symmetric buffers. Over-allocate the destination heap object so an --oob
    // put lands inside our allocation math but past the object the peer expects.
    size_t heap_obj = bytes;
    char *dbuf = (char *)nvshmem_malloc(heap_obj);
    char *sbuf = (char *)nvshmem_malloc(bytes);
    uint64_t *sig = (uint64_t *)nvshmem_malloc(sizeof(uint64_t));
    if (!dbuf || !sbuf || !sig) {
        fprintf(stderr, "[PE%d] nvshmem_malloc failed\n", mype);
        return 2;
    }
    CK(cudaMemset(sig, 0, sizeof(uint64_t)));
    CK(cudaMemset(dbuf, 0, heap_obj));

    cqe_probe *pb = nullptr;
    int *arrived = nullptr;
    unsigned long long *mismatch = nullptr;
    const int RING_CAP = 512;
    cqe_sample *ring = nullptr;
    int *ring_len = nullptr;
    CK(cudaHostAlloc(&pb, sizeof(*pb), cudaHostAllocMapped));
    CK(cudaHostAlloc(&arrived, sizeof(*arrived), cudaHostAllocMapped));
    CK(cudaHostAlloc(&mismatch, sizeof(*mismatch), cudaHostAllocMapped));
    CK(cudaHostAlloc(&ring, sizeof(cqe_sample) * RING_CAP, cudaHostAllocMapped));
    CK(cudaHostAlloc(&ring_len, sizeof(*ring_len), cudaHostAllocMapped));
    cq_scan *scan = nullptr;
    CK(cudaHostAlloc(&scan, sizeof(*scan), cudaHostAllocMapped));

    char *hsrc = (char *)malloc(bytes);
    if (!hsrc) {
        fprintf(stderr, "[PE%d] host alloc failed\n", mype);
        return 1;
    }

    fprintf(stderr, "[PE%d of %d] ready: mode=%s iters=%d bytes=%zu cadence=%dms devto=%dms oob=%d\n",
            mype, npes, modestr, iters, bytes, cadence_ms, dev_timeout_ms, oob);

    nvshmem_barrier_all();  // one healthy sync before any fault

    // Let a hook-injected fault fire before the first put (cc=0 A/B, ITERS=1).
    if (prefault_ms > 0) {
        fprintf(stderr, "[PE%d] pre-fault delay %d ms before iter 0\n", mype, prefault_ms);
        usleep((useconds_t)prefault_ms * 1000);
    }

    signal(SIGALRM, hangWatchdog);
    // Per-iteration host watchdog (s). Blocking / long-IB-timeout references need
    // it larger than the retry-exhausted window; overridable via env.
    const char *wdenv = getenv("NVSHMEM_FAULT_WATCHDOG_S");
    unsigned wd_block = wdenv ? (unsigned)atoi(wdenv) : 30u;
    unsigned wd_other = wdenv ? (unsigned)atoi(wdenv) : 20u;
    int rc = 0;

    for (int it = 0; it < iters && rc == 0; it++) {
        double t0 = nowSec();
        if (mype == 0) {
            for (size_t b = 0; b < bytes; b++) hsrc[b] = (char)patByte(it, b);
            CK(cudaMemcpy(sbuf, hsrc, bytes, cudaMemcpyHostToDevice));
            memset(pb, 0, sizeof(*pb));
            *ring_len = 0;
            // F2b (--corrupt-rkey <it>): at iteration <it>, overwrite the peer's
            // device-side rkey (constmem, since chunk 0 targeting peer maps to
            // idx = proxy_pe = peer < MAX_CONST_RKEYS) with an invalid key via
            // cudaMemcpyToSymbol on the __constant__ device-state symbol we already
            // link. The next put should then be NAKed by the responder (a prompt
            // remote error, no retries), directly testing whether ANY error CQE is
            // ever visible in this configuration.
            if (it == corrupt_rkey_at) {
                // The device picks constmem.rkeys[idx] where idx depends on dbuf's
                // heap chunk (heapextra pushes dbuf off chunk 0), so corrupt ALL
                // MAX_CONST_RKEYS entries to guarantee the used one is invalid.
                uint32_t bad = 0xdeadbee0u;
                int nbad = 0;
                for (int k = 0; k < NVSHMEMI_IBGDA_MAX_CONST_RKEYS; k++) {
                    size_t off = offsetof(nvshmemi_ibgda_device_state_t, constmem.rkeys) +
                                 (size_t)k * sizeof(nvshmemi_ibgda_device_key_t) +
                                 offsetof(nvshmemi_ibgda_device_key_t, key);
                    if (cudaMemcpyToSymbol(nvshmemi_ibgda_device_state_d, &bad, sizeof(bad), off,
                                           cudaMemcpyHostToDevice) == cudaSuccess)
                        nbad++;
                }
                CK(cudaDeviceSynchronize());
                fprintf(stderr, "[PE0] F2b corrupted %d/%d constmem rkeys -> 0x%x\n", nbad,
                        NVSHMEMI_IBGDA_MAX_CONST_RKEYS, bad);
            }
            // --oob (F2): write one window PAST the destination buffer. The device
            // path (ibgda_get_raddr_rkey) has its bounds assert compiled out under
            // NDEBUG, so it does no checking: a small overrun that is still inside
            // the registered heap gets a valid rkey and lands at the wrong remote
            // offset -> the initiator sees a normal success CQE while the peer's
            // data is silently wrong (a much larger offset past the whole heap
            // instead indexes the rkey array out of bounds and faults the GPU;
            // neither path ever yields a REM_ACCESS CQE on IBGDA).
            char *dst = oob ? (dbuf + bytes) : dbuf;
            // Blocking/snapshot modes can spin the whole budget; bound with alarm.
            alarm(mode == 1 ? wd_block : wd_other);
            memset(scan, 0, sizeof(*scan));
            put_kernel<<<1, 1>>>(dst, sbuf, bytes, sig, peer, mode, budget, burst, pb, ring,
                                 RING_CAP, ring_len, scan);
            cudaError_t se = cudaDeviceSynchronize();
            alarm(0);
            double dt = (nowSec() - t0) * 1e3;
            if (se != cudaSuccess) {
                fprintf(stderr, "[PE0] iter %d kernel error %s\n", it, cudaGetErrorString(se));
                printf("ITER %d rank 0 wait=%s wait_rc=CUDAERR dt_ms=%.1f\n", it, modestr, dt);
                rc = 6;
                break;
            }
            printf(
                "ITER %d rank 0 wait=%s burst=%d wait_rc=%d dt_ms=%.1f wait_cycles=%llu qpn=0x%x "
                "cqn=0x%x cqe_opcode=0x%x cqe_syndrome=0x%02x cqe_vendor_err=0x%02x "
                "cqe_wqe_counter=%u ready_head=%llu\n",
                it, modestr, burst, pb->wait_rc, dt, pb->wait_cycles, pb->qpn, pb->cqn, pb->opcode,
                pb->syndrome, pb->vendor_err, pb->wqe_counter, pb->ready_head);
            fflush(stdout);
            // Full-buffer CQ scan: histogram of every entry's opcode across the
            // whole RC and DCI send CQ buffers (not just slot 0), plus any
            // error-class (0xd/0xe) CQE found anywhere.
            {
                char rh[128], dh[128];
                int ro = 0, dofs = 0;
                for (int k = 0; k < 16; k++) {
                    if (scan->rc_hist[k])
                        ro += snprintf(rh + ro, sizeof(rh) - ro, "%x:%u ", k, scan->rc_hist[k]);
                    if (scan->dci_hist[k])
                        dofs += snprintf(dh + dofs, sizeof(dh) - dofs, "%x:%u ", k, scan->dci_hist[k]);
                }
                printf("SCAN iter %d rank 0 rc_ncqes=%u rc_hist{%s} dci_ncqes=%u dci_hist{%s} errs=%d\n",
                       it, scan->rc_ncqes, rh, scan->dci_ncqes, dh, scan->ndet);
                for (int k = 0; k < scan->ndet; k++)
                    printf("SCAN iter %d rank 0 ERRCQE which=%u idx=%u op=0x%x syn=0x%02x ven=0x%02x "
                           "wqe=%u sqopqpn=0x%x\n",
                           it, scan->det[k].which, scan->det[k].idx, scan->det[k].opcode,
                           scan->det[k].syndrome, scan->det[k].vendor, scan->det[k].wqe,
                           scan->det[k].sqopqpn);
                fflush(stdout);
            }
            if (mode == 3) {  // dump the collapsed-slot transition trace
                int n = *ring_len;
                printf("SNAP iter %d rank 0 samples=%d\n", it, n);
                for (int s = 0; s < n; s++)
                    printf("SNAP iter %d rank 0 s=%d t_cyc=%llu op=0x%x syn=0x%02x ven=0x%02x wqe=%u\n",
                           it, s, ring[s].t_cycles, ring[s].opcode, ring[s].syndrome,
                           ring[s].vendor_err, ring[s].wqe_counter);
                fflush(stdout);
            }
            if (pb->wait_rc == 1)
                rc = 3;  // bounded-spin expired: initiator did not complete
            else if (pb->wait_rc == 2)
                rc = 3;  // initiator classified an error CQE
        } else {
            *arrived = 0;
            *mismatch = 0;
            // Signal is ADD 1 per put; PE0 posts `burst` puts/iteration.
            uint64_t expect = (uint64_t)(it + 1) * (uint64_t)burst;
            int rmode = (mode == 3) ? 0 : mode;  // snapshot is PE0-only; PE1 bounded-waits
            alarm(mode == 1 ? wd_block : wd_other);
            recv_kernel<<<1, 1>>>(dbuf, bytes, sig, expect, it, rmode, budget, arrived, mismatch);
            cudaError_t se = cudaDeviceSynchronize();
            alarm(0);
            double dt = (nowSec() - t0) * 1e3;
            if (se != cudaSuccess) {
                fprintf(stderr, "[PE1] iter %d kernel error %s\n", it, cudaGetErrorString(se));
                printf("ITER %d rank 1 wait=%s arrived=CUDAERR dt_ms=%.1f\n", it, modestr, dt);
                rc = 6;
                break;
            }
            const char *dc = !*arrived ? "missing" : (*mismatch ? "mismatch" : "ok");
            printf("ITER %d rank 1 wait=%s arrived=%d dt_ms=%.1f data_check=%s mismatch=%llu\n", it,
                   modestr, *arrived, dt, dc, *mismatch);
            fflush(stdout);
            if (!*arrived)
                rc = 4;
            else if (*mismatch)
                rc = 5;
        }
        // Pace the loop so an ms-scheduled fault lands mid-run. No collective here.
        double slept = (nowSec() - t0) * 1e3;
        if (slept < cadence_ms) usleep((useconds_t)((cadence_ms - slept) * 1000));
    }

    printf("SUMMARY rank %d wait=%s rc=%d\n", mype, modestr, rc);
    fflush(stdout);

    // Best-effort teardown. finalize can itself block after a transport error;
    // bound it and report teardown=hang via exit 7 if it does not return.
    signal(SIGALRM, hangWatchdog);
    alarm(15);
    nvshmem_free(dbuf);
    nvshmem_free(sbuf);
    nvshmem_free(sig);
    nvshmem_finalize();
    alarm(0);
    free(hsrc);
    return rc;
}
