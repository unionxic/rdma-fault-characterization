// nvshmem_t1.cu - an NVSHMEM application with no recovery code, for the T1 transparent-recovery
// build (nvshmem_ibgda_transparent.diff). Two PEs; PE0 (rain) puts, PE1 (sunny) receives.
//
//   loop   PE0: ONE kernel for the whole run: for i: fill the source with pattern(i),
//               nvshmem_putmem_signal_nbi(slot i, bytes, sig, 1, NVSHMEM_SIGNAL_ADD, peer),
//               nvshmem_quiet(), optional gap. PE1: ONE kernel: for i:
//               nvshmem_signal_wait_until(sig, GE, i + 1), check slot i on the GPU.
//   mt     PE0: C CTAs x T threads post on the one RC QP to the peer; each thread does R rounds of
//               B back-to-back put+signal (its own slots) then nvshmem_quiet() and the gap. PE1 waits
//               for the final signal, then checks every slot on the GPU.
//   lat    PE0: N x (put+signal + quiet), one thread, %globaltimer per operation; p50/p99.
//   --fetch (loop): after the put+signal of every K-th iteration (--fetch-every K, default 1), a
//               fetching atomic nvshmem_long_atomic_fetch_add(ctr, 1) on PE1's counter; its return
//               value is recorded (expected: the number of fetches before it, i.e. exactly once; a
//               failed fetch returns the library's poison value, all bits 1).
//   --fill-sms [N] (loop, PE0): after the loop kernel starts, a second kernel occupies every remaining
//               thread slot of every SM (CTAs sleeping until the loop ends), so that no other kernel,
//               e.g. a memset launched by a library thread, can run meanwhile. N = 1 (default): the
//               grid is exactly the free capacity; N = 2: one CTA more than fits, i.e. a CTA that
//               stays pending in the compute queue until the loop ends (workload shape only).
//
// Nothing here knows about faults: no status checks inside the loop that change control flow, no
// relaunch, no handshake. The kernel records, per iteration, its duration and (observation only)
// nvshmemx_ibgda_ft_status(peer); the hosts check everything at the end: every slot bit-exact on the
// GPU and again on the host, the final signal exact, the library's host error view (FT query, if
// the FT API is present) and the device status after the run.
//
// usage: nvshmem_t1 <rank> <pe0_mgmt_ip> <port> <mode> [--iters N] [--bytes B] [--gap-us G]
//        [--ctas C] [--threads T] [--burst B] [--reps R] [--kernel-timeout-s S] [--bad-at I] [--fetch] [--fetch-every K] [--fill-sms [1|2]]
// Exit: 0 ok (everything verified), 3 an iteration's status showed an error (declined), 4 PE1
//       missing data or signal, 5 data mismatch, 6 CUDA error, 7 kernel did not finish in time, 2 init.
#include <nvshmem.h>
#include <nvshmemx.h>
#include "device_host_transport/nvshmem_common_ibgda.h"
#include "non_abi/device/pt-to-pt/ibgda_device.cuh"
#ifndef __CUDA_ARCH__
__device__ uint32_t nvshmemx_ibgda_ft_status(int pe);
#endif

#include <cuda_runtime.h>
#include <arpa/inet.h>
#include <dlfcn.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>
#include <algorithm>
#include <climits>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <vector>

#define CK(c)                                                                                  \
    do {                                                                                       \
        cudaError_t e_ = (c);                                                                  \
        if (e_ != cudaSuccess) {                                                               \
            fprintf(stderr, "[t1app] CUDA %s:%d %s\n", __FILE__, __LINE__, cudaGetErrorString(e_)); \
            exit(6);                                                                           \
        }                                                                                      \
    } while (0)

static double monoMs() {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec * 1e3 + t.tv_nsec * 1e-6;
}

__device__ __forceinline__ uint64_t gtimer() {
    uint64_t t;
    asm volatile("mov.u64 %0, %%globaltimer;" : "=l"(t)::"memory");
    return t;
}
__host__ __device__ __forceinline__ unsigned char patByte(uint32_t it, size_t b) {
    return (unsigned char)((it * 131u + (uint32_t)b * 7u + (uint32_t)(b >> 9)) & 0xff);
}

struct IterRec {
    unsigned long long t0, t1; /* %globaltimer around put+signal+quiet */
    unsigned int status;       /* nvshmemx_ibgda_ft_status(peer) after the quiet (observation) */
    unsigned int pad;
    long long fetch;           /* --fetch: value returned by the fetch-add (expected: the iteration) */
    long long pad2;
};

// ---------------------------------------------------------------- loop mode
__global__ void put_loop(unsigned char *dst, unsigned char *src, size_t bytes, uint64_t *sig, int peer,
                         int iters, long long gap_cycles, IterRec *rec, int bad_at, unsigned char *bad_dst,
                         long *ctr, int fetch_every) {
    for (int it = 0; it < iters; it++) {
        for (size_t b = threadIdx.x; b < bytes; b += blockDim.x) src[b] = patByte((uint32_t)it, b);
        __syncthreads();
        if (threadIdx.x == 0) {
            __threadfence();
            unsigned long long t0 = gtimer();
            /* F2 (the application's own bug, test knob): one put to an address past the symmetric heap */
            unsigned char *d = (it == bad_at) ? bad_dst : dst + (size_t)it * bytes;
            nvshmem_putmem_signal_nbi(d, src, bytes, sig, 1, NVSHMEM_SIGNAL_ADD, peer);
            /* --fetch: a fetching atomic in flight right after the put (its result is needed here) */
            rec[it].fetch = LLONG_MIN; /* no fetch in this iteration */
            if (ctr != nullptr && it % fetch_every == 0)
                rec[it].fetch = (long long)nvshmem_long_atomic_fetch_add(ctr, 1, peer);
            nvshmem_quiet();
            unsigned long long t1 = gtimer();
            rec[it].t0 = t0;
            rec[it].t1 = t1;
            rec[it].status = nvshmemx_ibgda_ft_status(peer);
            if (gap_cycles > 0) {
                long long c0 = clock64();
                while (clock64() - c0 < gap_cycles);
            }
        }
        __syncthreads();
    }
}

__global__ void recv_loop(const unsigned char *dst, size_t bytes, uint64_t *sig, int iters,
                          unsigned int *bad, unsigned long long *t_arrive) {
    for (int it = 0; it < iters; it++) {
        if (threadIdx.x == 0) {
            nvshmem_signal_wait_until(sig, NVSHMEM_CMP_GE, (uint64_t)it + 1);
            t_arrive[it] = gtimer();
        }
        __syncthreads();
        unsigned int nb = 0;
        const unsigned char *s = dst + (size_t)it * bytes;
        for (size_t b = threadIdx.x; b < bytes; b += blockDim.x)
            if (s[b] != patByte((uint32_t)it, b)) nb++;
        if (nb) atomicAdd(&bad[it], nb);
        __syncthreads();
    }
}

// ---------------------------------------------------------------- mt mode
// thread g = blockIdx.x * blockDim.x + threadIdx.x owns slots [g * reps * burst, (g+1) * reps * burst)
__global__ void put_mt(unsigned char *dst, const unsigned char *src, size_t bytes, uint64_t *sig, int peer,
                       int reps, int burst, long long gap_cycles, IterRec *rec) {
    const int g = blockIdx.x * blockDim.x + threadIdx.x;
    for (int r = 0; r < reps; r++) {
        unsigned long long t0 = gtimer();
        for (int k = 0; k < burst; k++) {
            const size_t slot = ((size_t)g * reps + r) * burst + k;
            nvshmem_putmem_signal_nbi(dst + slot * bytes, src + slot * bytes, bytes, sig, 1,
                                      NVSHMEM_SIGNAL_ADD, peer);
        }
        nvshmem_quiet();
        unsigned long long t1 = gtimer();
        IterRec *x = &rec[(size_t)g * reps + r];
        x->t0 = t0;
        x->t1 = t1;
        x->status = nvshmemx_ibgda_ft_status(peer);
        if (gap_cycles > 0) {
            long long c0 = clock64();
            while (clock64() - c0 < gap_cycles);
        }
    }
}
__global__ void fill_src(unsigned char *src, size_t bytes, size_t nslots) {
    for (size_t i = blockIdx.x * (size_t)blockDim.x + threadIdx.x; i < bytes * nslots;
         i += (size_t)gridDim.x * blockDim.x)
        src[i] = patByte((uint32_t)(i / bytes), i % bytes);
}
__global__ void recv_mt(const unsigned char *dst, size_t bytes, size_t nslots, uint64_t *sig,
                        unsigned int *bad, unsigned long long *t_arrive) {
    if (threadIdx.x == 0 && blockIdx.x == 0) {
        nvshmem_signal_wait_until(sig, NVSHMEM_CMP_GE, (uint64_t)nslots);
        *t_arrive = gtimer();
    }
    __syncthreads();
}
__global__ void check_mt(const unsigned char *dst, size_t bytes, size_t nslots, unsigned int *bad) {
    for (size_t i = blockIdx.x * (size_t)blockDim.x + threadIdx.x; i < bytes * nslots;
         i += (size_t)gridDim.x * blockDim.x)
        if (dst[i] != patByte((uint32_t)(i / bytes), i % bytes)) atomicAdd(&bad[i / bytes], 1u);
}

// ---------------------------------------------------------------- lat mode
__global__ void lat_kernel(unsigned char *dst, const unsigned char *src, size_t bytes, uint64_t *sig, int peer,
                           int n, unsigned int *times) {
    for (int i = 0; i < n; i++) {
        unsigned long long t0 = gtimer();
        nvshmem_putmem_signal_nbi(dst, src, bytes, sig, 1, NVSHMEM_SIGNAL_ADD, peer);
        nvshmem_quiet();
        times[i] = (unsigned int)(gtimer() - t0);
    }
}
__global__ void wait_sig(uint64_t *sig, uint64_t v) { nvshmem_signal_wait_until(sig, NVSHMEM_CMP_GE, v); }
__global__ void fill_sms(volatile int *stop) {
    /* the flag is in device memory (a host-mapped flag polled by ~50k threads saturates PCIe and
     * stalls every host<->device copy, the NIC's included); one thread per CTA polls it */
    if (threadIdx.x == 0)
        while (!*stop) __nanosleep(200000);
    __syncthreads();
}
__global__ void status_kernel(int peer, unsigned int *out) { *out = nvshmemx_ibgda_ft_status(peer); }
__global__ void gt_kernel(unsigned long long *out) { *out = gtimer(); }

// ---------------------------------------------------------------- host helpers
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

/* Wait for a stream with a bound (the application's own timeout, not recovery). */
static int waitStream(cudaStream_t s, double limit_s) {
    double t0 = monoMs();
    for (;;) {
        cudaError_t e = cudaStreamQuery(s);
        if (e == cudaSuccess) return 0;
        if (e != cudaErrorNotReady) {
            fprintf(stderr, "[t1app] kernel error %s\n", cudaGetErrorString(e));
            return 6;
        }
        if (monoMs() - t0 > limit_s * 1e3) return 7;
        usleep(1000);
    }
}

/* End-of-run observation of the library's host error view (FT API, if exported). */
static int hostErrorView(char *name, size_t n) {
    void *h = dlopen("nvshmem_transport_ibgda.so.7", RTLD_NOW | RTLD_NOLOAD);
    if (!h) return -1;
    auto q = (int (*)(nvshmemt_ibgda_ft_info_t *, int))dlsym(h, "nvshmemt_ibgda_ft_query");
    if (!q) return -1;
    nvshmemt_ibgda_ft_info_t info;
    memset(&info, 0, sizeof(info));
    int r = q(&info, 0);
    snprintf(name, n, "%s", r == 1 ? info.name : "none");
    return r == 1 ? 1 : 0;
}

int main(int argc, char **argv) {
    if (argc < 5) {
        fprintf(stderr, "usage: %s <rank> <pe0_ip> <port> <loop|mt|lat> [options]\n", argv[0]);
        return 1;
    }
    setvbuf(stdout, NULL, _IOLBF, 0);
    const int rank = atoi(argv[1]);
    const char *pe0_ip = argv[2];
    const int port = atoi(argv[3]);
    const char *mode = argv[4];
    int iters = 160, ctas = 4, threads = 8, burst = 1, reps = 1, bad_at = -1, do_fetch = 0, fill = 0,
        fetch_every = 1, no_finalize = 0;
    long gap_us = 15000;
    double ktimeout_s = 120;
    size_t bytes = 256u * 1024u;
    for (int i = 5; i < argc; i++) {
        auto nxt = [&]() -> const char * { return i + 1 < argc ? argv[++i] : "0"; };
        if (!strcmp(argv[i], "--iters")) iters = atoi(nxt());
        else if (!strcmp(argv[i], "--bytes")) bytes = strtoul(nxt(), 0, 10);
        else if (!strcmp(argv[i], "--gap-us")) gap_us = atol(nxt());
        else if (!strcmp(argv[i], "--ctas")) ctas = atoi(nxt());
        else if (!strcmp(argv[i], "--threads")) threads = atoi(nxt());
        else if (!strcmp(argv[i], "--burst")) burst = atoi(nxt());
        else if (!strcmp(argv[i], "--reps")) reps = atoi(nxt());
        else if (!strcmp(argv[i], "--kernel-timeout-s")) ktimeout_s = atof(nxt());
        else if (!strcmp(argv[i], "--bad-at")) bad_at = atoi(nxt());
        else if (!strcmp(argv[i], "--fetch")) do_fetch = 1;
        else if (!strcmp(argv[i], "--no-finalize")) no_finalize = 1; /* t1_close: exit through atexit only */
        else if (!strcmp(argv[i], "--fetch-every")) fetch_every = std::max(1, atoi(nxt()));
        else if (!strcmp(argv[i], "--fill-sms")) {
            fill = 1;
            if (i + 1 < argc && (argv[i + 1][0] == '1' || argv[i + 1][0] == '2') && !argv[i + 1][1]) fill = atoi(argv[++i]);
        }
        else {
            fprintf(stderr, "unknown arg %s\n", argv[i]);
            return 1;
        }
    }
    const bool loop = !strcmp(mode, "loop"), mt = !strcmp(mode, "mt"), lat = !strcmp(mode, "lat");
    if (!(loop || mt || lat) || iters <= 0 || bytes == 0) return 1;

    // unique-id bootstrap over TCP on the management network (closed after init)
    nvshmemx_uniqueid_t id = NVSHMEMX_UNIQUEID_INITIALIZER;
    int one = 1, sk = -1;
    if (rank == 0) {
        nvshmemx_get_uniqueid(&id);
        int ls = socket(AF_INET, SOCK_STREAM, 0);
        setsockopt(ls, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
        sockaddr_in a{};
        a.sin_family = AF_INET;
        a.sin_addr.s_addr = INADDR_ANY;
        a.sin_port = htons(port);
        if (bind(ls, (sockaddr *)&a, sizeof a) || listen(ls, 1)) {
            perror("bind");
            return 2;
        }
        struct pollfd p = {ls, POLLIN, 0};
        if (poll(&p, 1, 60000) <= 0) return 2;
        sk = accept(ls, 0, 0);
        close(ls);
        if (sendall(sk, &id, sizeof id)) return 2;
    } else {
        sockaddr_in a{};
        a.sin_family = AF_INET;
        a.sin_port = htons(port);
        inet_pton(AF_INET, pe0_ip, &a.sin_addr);
        for (int tries = 0;; tries++) {
            sk = socket(AF_INET, SOCK_STREAM, 0);
            if (connect(sk, (sockaddr *)&a, sizeof a) == 0) break;
            close(sk);
            if (tries > 300) return 2;
            usleep(200000);
        }
        if (recvall(sk, &id, sizeof id)) return 2;
    }
    setsockopt(sk, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
    // clock offset (for cross-host timelines only): min-RTT ping-pong
    double off10 = 0, best = 1e9;
    for (int i = 0; i < 20; i++) {
        double t[2];
        if (rank == 0) {
            double a0 = monoMs();
            if (sendall(sk, &a0, 8) || recvall(sk, t, 8)) return 2;
            double b0 = monoMs();
            if (b0 - a0 < best) {
                best = b0 - a0;
                off10 = t[0] - (a0 + b0) / 2;
            }
        } else {
            if (recvall(sk, t, 8)) return 2;
            t[0] = monoMs();
            if (sendall(sk, t, 8)) return 2;
        }
    }
    close(sk);

    nvshmemx_init_attr_t attr = NVSHMEMX_INIT_ATTR_INITIALIZER;
    nvshmemx_set_attr_uniqueid_args(rank, 2, &id, &attr);
    if (nvshmemx_init_attr(NVSHMEMX_INIT_WITH_UNIQUEID, &attr)) return 2;
    const int me = nvshmem_my_pe(), peer = 1 - me;
    CK(cudaSetDevice(0));
    cudaDeviceProp prop;
    CK(cudaGetDeviceProperties(&prop, 0));
    const long long cyc_per_us = (long long)prop.clockRate / 1000;

    const size_t nslots = mt ? (size_t)ctas * threads * reps * burst : lat ? 1 : (size_t)iters;
    unsigned char *dst = (unsigned char *)nvshmem_malloc(bytes * nslots);
    unsigned char *src = (unsigned char *)nvshmem_malloc(mt ? bytes * nslots : bytes);
    uint64_t *sig = (uint64_t *)nvshmem_malloc(sizeof(uint64_t));
    long *ctr = (long *)nvshmem_malloc(sizeof(long)); /* --fetch: the fetch-add target on PE1 */
    if (!dst || !src || !sig || !ctr) {
        fprintf(stderr, "[t1app] nvshmem_malloc failed\n");
        return 2;
    }
    CK(cudaMemset(sig, 0, 8));
    CK(cudaMemset(ctr, 0, 8));
    CK(cudaMemset(dst, 0, bytes * nslots));
    if (mt) fill_src<<<64, 256>>>(src, bytes, nslots);
    CK(cudaDeviceSynchronize());
    cudaStream_t st;
    CK(cudaStreamCreateWithFlags(&st, cudaStreamNonBlocking));
    // %globaltimer -> CLOCK_MONOTONIC (for timelines only): best of 20 bracketed reads
    double gt_off_ms = 0;
    {
        unsigned long long *g;
        CK(cudaHostAlloc(&g, 8, cudaHostAllocMapped));
        double bw = 1e9;
        for (int i = 0; i < 20; i++) {
            double a0 = monoMs();
            gt_kernel<<<1, 1, 0, st>>>(g);
            CK(cudaStreamSynchronize(st));
            double b0 = monoMs();
            if (b0 - a0 < bw) {
                bw = b0 - a0;
                gt_off_ms = *g / 1e6 - (a0 + b0) / 2;
            }
        }
        printf("CALIB rank %d gt_minus_mono_ms=%.3f err_ms=%.3f\n", me, gt_off_ms, bw / 2);
    }
    nvshmem_barrier_all();
    printf("T1APP rank %d mode=%s iters=%d bytes=%zu gap_us=%ld ctas=%d threads=%d burst=%d reps=%d nslots=%zu "
           "fetch=%d fetch_every=%d fill_sms=%d off_r1_minus_r0_ms=%.3f rtt_ms=%.3f start_mono_ms=%.3f\n",
           me, mode, iters, bytes, gap_us, ctas, threads, burst, reps, nslots, do_fetch, fetch_every, fill, off10,
           best, monoMs());

    int rc = 0;
    if (lat) {
        unsigned int *times;
        CK(cudaHostAlloc(&times, sizeof(unsigned) * iters, cudaHostAllocMapped));
        for (int r = 0; r < reps && rc == 0; r++) {
            if (me == 0) {
                lat_kernel<<<1, 1, 0, st>>>(dst, src, bytes, sig, peer, iters, times);
                rc = waitStream(st, ktimeout_s);
                if (rc) break;
                std::vector<unsigned> v(times, times + iters);
                std::sort(v.begin(), v.end());
                double sum = 0;
                for (unsigned x : v) sum += x;
                printf("LAT rep %d bytes=%zu n=%d p50_us=%.3f p90_us=%.3f p99_us=%.3f max_us=%.3f mean_us=%.3f\n", r,
                       bytes, iters, v[iters / 2] / 1e3, v[(size_t)(iters * 0.9)] / 1e3, v[(size_t)(iters * 0.99)] / 1e3,
                       v[iters - 1] / 1e3, sum / iters / 1e3);
            } else {
                wait_sig<<<1, 1, 0, st>>>(sig, (uint64_t)(r + 1) * iters);
                rc = waitStream(st, ktimeout_s);
            }
            nvshmem_barrier_all();
        }
    } else if (me == 0) {
        const size_t nrec = mt ? (size_t)ctas * threads * reps : (size_t)iters;
        IterRec *rec;
        CK(cudaHostAlloc(&rec, sizeof(IterRec) * nrec, cudaHostAllocMapped));
        memset(rec, 0, sizeof(IterRec) * nrec);
        double tl = monoMs();
        if (mt)
            put_mt<<<ctas, threads, 0, st>>>(dst, src, bytes, sig, peer, reps, burst, (long long)gap_us * cyc_per_us, rec);
        else
        {
            /* F2 test knob: an address just past the heap's last 2 MiB key granule; its rkey entry is
             * empty (key 0) as long as the heap has fewer than 32 granules per PE */
            nvshmemi_device_host_state_t hs;
            CK(cudaMemcpyFromSymbol(&hs, nvshmemi_device_state_d, sizeof(hs)));
            const size_t g = (size_t)2 << 20;
            unsigned char *bad = (unsigned char *)hs.heap_base + ((hs.heap_size + g - 1) / g) * g + g / 2;
            if (bad_at >= 0)
                printf("F2BAD rank 0 bad_at=%d heap_size=%zu bad_off=%zu\n", bad_at, (size_t)hs.heap_size,
                       (size_t)(bad - (unsigned char *)hs.heap_base));
            put_loop<<<1, 256, 0, st>>>(dst, src, bytes, sig, peer, iters, (long long)gap_us * cyc_per_us, rec,
                                        bad_at, bad, do_fetch ? ctr : nullptr, fetch_every);
        }
        int *fill_stop = nullptr;
        cudaStream_t fst = nullptr;
        if (fill) {
            /* every SM to its thread limit: the loop kernel's one CTA is resident, the filler takes
             * the rest (its last CTA waits for a free slot that never comes until the loop ends) */
            int sms = prop.multiProcessorCount, per_sm = prop.maxThreadsPerMultiProcessor / 256;
            /* the loop kernel's CTA takes one slot; fill=1 leaves no slot free and no CTA pending,
             * fill=2 adds one CTA that cannot be scheduled while the loop runs */
            const int ctas = sms * per_sm - 1 + (fill == 2 ? 1 : 0);
            CK(cudaMalloc((void **)&fill_stop, sizeof(int)));
            CK(cudaMemset(fill_stop, 0, sizeof(int)));
            CK(cudaStreamCreateWithFlags(&fst, cudaStreamNonBlocking));
            usleep(20000); /* the loop kernel is launched first */
            fill_sms<<<ctas, 256, 0, fst>>>(fill_stop);
            printf("T1FILL rank 0 sms=%d ctas=%d threads=256 pending=%d\n", sms, ctas, fill == 2 ? 1 : 0);
        }
        rc = waitStream(st, ktimeout_s);
        if (fill) {
            int one = 1;
            cudaStream_t cst;
            CK(cudaStreamCreateWithFlags(&cst, cudaStreamNonBlocking));
            CK(cudaMemcpyAsync(fill_stop, &one, sizeof(int), cudaMemcpyHostToDevice, cst)); /* a copy, no kernel */
            CK(cudaStreamSynchronize(cst));
            cudaStreamSynchronize(fst);
        }
        double tr = monoMs();
        if (rc) {
            printf("T1RESULT rank 0 KERNEL_TIMEOUT_OR_ERROR rc=%d after_ms=%.1f\n", rc, tr - tl);
            fflush(stdout);
            _exit(rc); /* a kernel still running: no finalize (it would wait for the kernel) */
        }
        size_t nbad = 0, first_bad = (size_t)-1, slow = 0;
        double maxd = 0, sumd = 0;
        size_t imax = 0;
        std::vector<double> d(nrec);
        for (size_t i = 0; i < nrec; i++) {
            d[i] = (rec[i].t1 - rec[i].t0) / 1e3;
            sumd += d[i];
            if (d[i] > maxd) {
                maxd = d[i];
                imax = i;
            }
            if (d[i] > 1000.0) slow++;
            if (rec[i].status) {
                nbad++;
                if (first_bad == (size_t)-1) first_bad = i;
            }
        }
        std::vector<double> ds = d;
        std::sort(ds.begin(), ds.end());
        char ev[32];
        int he = hostErrorView(ev, sizeof(ev));
        printf("T1RESULT rank 0 records=%zu status_bad=%zu first_bad=%lld status_first=0x%08x median_op_us=%.2f "
               "max_op_us=%.1f max_at=%zu max_t1_gt=%llu slow_ops_gt1ms=%zu kernel_ms=%.1f host_err=%d(%s)\n",
               nrec, nbad, first_bad == (size_t)-1 ? -1LL : (long long)first_bad,
               first_bad == (size_t)-1 ? 0u : rec[first_bad].status, ds[nrec / 2], maxd, imax,
               (unsigned long long)rec[imax].t1, slow, tr - tl, he, ev);
        if (do_fetch && !mt) {
            /* fetch values: before the first failed status every fetch must have returned its
             * iteration number (exactly once); from the first failed status on, the poison value
             * (all bits 1). Anything else is a stale or duplicated result. */
            size_t exact = 0, poison = 0, stale = 0, poison_before_bad = 0, nfetch = 0;
            long long first_poison = -1, first_stale = -1;
            for (size_t i = 0; i < nrec; i++) {
                const long long v = rec[i].fetch;
                if (v == LLONG_MIN) continue; /* no fetch in this iteration */
                const long long expect = (long long)nfetch++;
                if (v == expect) {
                    exact++;
                } else if (v == -1LL) {
                    poison++;
                    if (first_poison < 0) first_poison = (long long)i;
                    if (first_bad == (size_t)-1 || i < first_bad) poison_before_bad++;
                } else {
                    stale++;
                    if (first_stale < 0) first_stale = (long long)i;
                }
            }
            printf("T1FETCH rank 0 fetches=%zu exact=%zu poison=%zu stale=%zu first_poison=%lld first_stale=%lld "
                   "poison_before_bad=%zu first_bad=%lld\n",
                   nfetch, exact, poison, stale, first_poison, first_stale, poison_before_bad,
                   first_bad == (size_t)-1 ? -1LL : (long long)first_bad);
            if (stale || poison_before_bad) rc = 5;
        }
        if (nbad) rc = 3;
    } else {
        unsigned int *bad;
        unsigned long long *tarr;
        CK(cudaHostAlloc(&bad, sizeof(unsigned) * nslots, cudaHostAllocMapped));
        CK(cudaHostAlloc(&tarr, sizeof(unsigned long long) * (mt ? 1 : nslots), cudaHostAllocMapped));
        memset(bad, 0, sizeof(unsigned) * nslots);
        double tl = monoMs();
        if (mt)
            recv_mt<<<1, 32, 0, st>>>(dst, bytes, nslots, sig, bad, tarr);
        else
            recv_loop<<<1, 256, 0, st>>>(dst, bytes, sig, iters, bad, tarr);
        rc = waitStream(st, ktimeout_s);
        double tr = monoMs();
        uint64_t fsig = 0;
        CK(cudaMemcpy(&fsig, sig, 8, cudaMemcpyDeviceToHost)); /* a copy runs next to a live kernel */
        if (do_fetch) {
            long long c = 0;
            CK(cudaMemcpy(&c, ctr, 8, cudaMemcpyDeviceToHost));
            printf("T1FETCH rank 1 counter=%lld expect=%d\n", c, (iters + fetch_every - 1) / fetch_every);
        }
        if (rc) {
            printf("T1RESULT rank 1 KERNEL_TIMEOUT_OR_ERROR rc=%d after_ms=%.1f final_sig=%llu expect=%zu\n", rc,
                   tr - tl, (unsigned long long)fsig, nslots);
            fflush(stdout);
            _exit(rc == 7 ? 4 : rc);
        }
        if (mt) {
            check_mt<<<64, 256, 0, st>>>(dst, bytes, nslots, bad);
            CK(cudaStreamSynchronize(st));
        }
        size_t gpu_bad = 0, host_bad = 0;
        for (size_t i = 0; i < nslots; i++) gpu_bad += bad[i] ? 1 : 0;
        std::vector<unsigned char> h(bytes * nslots);
        CK(cudaMemcpy(h.data(), dst, h.size(), cudaMemcpyDeviceToHost));
        long long first_host_bad = -1;
        for (size_t i = 0; i < nslots; i++) {
            bool ok = true;
            for (size_t b = 0; b < bytes && ok; b++) ok = h[i * bytes + b] == patByte((uint32_t)i, b);
            if (!ok) {
                host_bad++;
                if (first_host_bad < 0) first_host_bad = (long long)i;
            }
        }
        if (!mt) { /* signals that arrived more than 1 ms after the previous one (%globaltimer, ns) */
            for (size_t i = 1; i < nslots; i++)
                if (tarr[i] - tarr[i - 1] > 1000000ULL)
                    printf("T1ARRIVE rank 1 it=%zu gt=%llu gap_us=%.1f\n", i, (unsigned long long)tarr[i],
                           (tarr[i] - tarr[i - 1]) / 1e3);
        }
        char ev[32];
        int he = hostErrorView(ev, sizeof(ev));
        printf("T1RESULT rank 1 slots=%zu gpu_bad=%zu host_bad=%zu first_host_bad=%lld final_sig=%llu expect=%zu "
               "sig_exact=%d kernel_ms=%.1f host_err=%d(%s)\n",
               nslots, gpu_bad, host_bad, first_host_bad, (unsigned long long)fsig, nslots, fsig == nslots ? 1 : 0,
               tr - tl, he, ev);
        if (gpu_bad || host_bad) rc = 5;
        else if (fsig != nslots) rc = 4;
    }
    // device status after the run (observation)
    {
        unsigned int *s;
        CK(cudaHostAlloc(&s, sizeof(unsigned), cudaHostAllocMapped));
        *s = 0;
        status_kernel<<<1, 1, 0, st>>>(peer, s);
        if (waitStream(st, 10) == 0) printf("T1STATUS rank %d end_status=0x%08x\n", me, *s);
    }
    if (no_finalize) {
        /* t1_close: leave main without nvshmem_finalize; the library's atexit hook stops its helper */
        printf("T1EXIT rank %d mono_ms=%.3f\n", me, monoMs());
        fflush(stdout);
        return rc;
    }
    double tf = monoMs();
    nvshmem_finalize();
    printf("T1END rank %d rc=%d finalize_ms=%.1f end_mono_ms=%.3f\n", me, rc, monoMs() - tf, monoMs());
    return rc;
}
