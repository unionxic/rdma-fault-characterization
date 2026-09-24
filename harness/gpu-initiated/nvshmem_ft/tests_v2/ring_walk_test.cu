// ring_walk_test.cu - single-GPU stress test of the v2 ring-CQ walker (ibgda_ft_ring_poll in the
// patched ibgda_device.cuh), success path only, no NIC.
//
// One "NIC" thread (block 0) writes CQEs into a ring of NCQES 64-byte entries the way mlx5 does
// (slot = pi & (NCQES-1), owner bit = !!(pi & NCQES), word 15 written last after a fence), each CQE
// completing a random group of 1..MAXG WQEs (wqe_counter = the group's last WQE index, 16 bits), and
// it respects the device's flow control: it completes WQE w only if w < cons_idx + NWQES (the device
// posts WQE w only after cons_idx > w - NWQES). WAITERS threads (one per warp, blocks 1..) each loop
// "pick a target index, call ibgda_ft_ring_poll(target), check cons_idx >= target", concurrently on
// the same CQ. Checked: every poll returns 0; cons_idx never exceeds the number of WQEs the NIC has
// completed (an over-advance would be a silent early completion); at the end cons_idx == TOTAL and
// the consumer counter == the number of CQEs written. TOTAL spans many ring laps and several 16-bit
// wqe_counter wraps.
#include <nvshmem.h>
#include <nvshmemx.h>
#include "device_host_transport/nvshmem_common_ibgda.h"
#include "non_abi/device/pt-to-pt/ibgda_device.cuh"
#include <cstdio>
#include <cstdlib>
#include <cstring>

#ifndef __CUDA_ARCH__
// host pass: declaration only (the header defines it in the device pass)
#endif

struct Shared {
    nvshmemi_ibgda_device_qp_management_t mv;  // cons_idx, ft_ring_ci live here
    unsigned long long completed;               // WQEs the NIC has completed (published)
    unsigned long long cqes;                    // CQEs written
    unsigned long long violations;              // cons_idx > completed seen
    unsigned long long bad_rc;                  // polls that did not return 0
    unsigned long long short_ret;               // polls that returned with cons_idx < target
    unsigned long long polls;
    unsigned int done;
};

__device__ unsigned int xs(unsigned int &s) {
    s ^= s << 13;
    s ^= s >> 17;
    s ^= s << 5;
    return s;
}

__global__ void nic_and_waiters(Shared *S, unsigned char *ring, unsigned ncqes, unsigned nwqes,
                                unsigned long long total, unsigned maxg, unsigned seed,
                                long long waiter_delay_cycles) {
#ifdef __CUDA_ARCH__
    uint64_t *cons_p = &S->mv.tx_wq.cons_idx;
    if (blockIdx.x == 0) {
        if (threadIdx.x != 0) return;
        unsigned int s = seed | 1;
        unsigned long long w_next = 0, pi = 0;
        while (w_next < total) {
            unsigned long long cons = *(volatile unsigned long long *)cons_p;
            if (cons > w_next) atomicAdd(&S->violations, 1ull);  // over-advance
            unsigned long long allowed = cons + nwqes;          // WQEs < allowed may exist
            unsigned g = 1 + xs(s) % maxg;
            unsigned long long last = w_next + g - 1;
            if (last >= total) last = total - 1;
            if (last >= allowed) {
                if (w_next >= allowed) continue;  // wait for the waiters to consume
                last = allowed - 1;
            }
            unsigned char *e = ring + (size_t)(pi & (ncqes - 1)) * 64;
            unsigned int *w = (unsigned int *)e;
            for (int k = 0; k < 15; k++) w[k] = xs(s);  // payload (timestamps etc. on a real CQE)
            __threadfence();
            uint16_t wc = (uint16_t)(last & 0xffff);
            unsigned owner = (pi & ncqes) ? 1u : 0u;
            unsigned w15 = (unsigned)(wc >> 8) | ((unsigned)(wc & 0xff) << 8) | (0xd2u << 16) |
                           ((0x0u << 4 | owner) << 24);  // BE wqe_counter, signature, op_own (opcode 0)
            atomicExch(&w[15], w15);
            __threadfence();
            atomicExch(&S->completed, last + 1);
            pi++;
            w_next = last + 1;
        }
        atomicExch(&S->cqes, pi);
        atomicExch(&S->done, 1u);
        return;
    }
    if (threadIdx.x % 32) return;  // one waiter per warp
    if (waiter_delay_cycles > 0) {  // let the NIC run ahead first (sensitivity check)
        long long t0 = clock64();
        while (clock64() - t0 < waiter_delay_cycles) {
        }
    }
    nvshmemi_ibgda_device_cq_t cq;
    memset(&cq, 0, sizeof(cq));
    cq.cqe = ring;
    cq.ncqes = ncqes;
    cq.cons_idx = cons_p;
    cq.prod_idx = &S->mv.tx_wq.prod_idx;
    cq.resv_head = &S->mv.tx_wq.resv_head;
    cq.ready_head = &S->mv.tx_wq.ready_head;
    cq.qp_type = NVSHMEMI_IBGDA_DEVICE_QP_TYPE_RC;
    unsigned int s = seed ^ (blockIdx.x * 7919u + threadIdx.x * 104729u);
    for (;;) {
        unsigned long long cons = *(volatile unsigned long long *)cons_p;
        if (cons >= total) break;
        unsigned long long tgt = cons + 1 + xs(s) % nwqes;  // anything up to what may be posted
        if (tgt > total) tgt = total;
        int err = 0;
        int rc = ibgda_ft_ring_poll(&cq, tgt, &err, NVSHMEMI_IBGDA_FT_PATH_POLL, 0, 0);
        atomicAdd(&S->polls, 1ull);
        if (rc != 0) atomicAdd(&S->bad_rc, 1ull);
        unsigned long long after = *(volatile unsigned long long *)cons_p;
        if (after < tgt) atomicAdd(&S->short_ret, 1ull);
        if (after > *(volatile unsigned long long *)&S->completed) atomicAdd(&S->violations, 1ull);
    }
#endif
}

int main(int argc, char **argv) {
    unsigned ncqes = argc > 1 ? atoi(argv[1]) : 64;
    unsigned nwqes = argc > 2 ? atoi(argv[2]) : 64;
    unsigned long long total = argc > 3 ? strtoull(argv[3], 0, 10) : (1ull << 21);
    unsigned blocks = argc > 4 ? atoi(argv[4]) : 4;
    unsigned maxg = argc > 5 ? atoi(argv[5]) : 4;
    unsigned seed = argc > 6 ? atoi(argv[6]) : 12345;
    double delay_ms = argc > 7 ? atof(argv[7]) : 0;  // waiters start this late (NIC runs ahead)
    cudaDeviceProp prop;
    cudaGetDeviceProperties(&prop, 0);
    long long delay_cycles = (long long)(delay_ms * prop.clockRate);
    Shared *S;
    unsigned char *ring;
    cudaMalloc(&S, sizeof(Shared));
    cudaMemset(S, 0, sizeof(Shared));
    cudaMalloc(&ring, (size_t)ncqes * 64);
    cudaMemset(ring, 0xff, (size_t)ncqes * 64);  // creation fill
    cudaEvent_t a, b;
    cudaEventCreate(&a);
    cudaEventCreate(&b);
    cudaEventRecord(a);
    nic_and_waiters<<<1 + blocks, 256>>>(S, ring, ncqes, nwqes, total, maxg, seed, delay_cycles);
    cudaError_t e = cudaDeviceSynchronize();
    cudaEventRecord(b);
    cudaEventSynchronize(b);
    float ms = 0;
    cudaEventElapsedTime(&ms, a, b);
    Shared h;
    cudaMemcpy(&h, S, sizeof(h), cudaMemcpyDeviceToHost);
    bool ok = e == cudaSuccess && h.done && h.mv.tx_wq.cons_idx == total && h.mv.ft_ring_ci == h.cqes &&
              h.violations == 0 && h.bad_rc == 0 && h.short_ret == 0;
    printf("RINGTEST ncqes=%u nwqes=%u total=%llu waiters=%u maxg=%u seed=%u delay_ms=%.0f cuda=%s cqes=%llu "
           "ring_ci=%llu cons_idx=%llu polls=%llu violations=%llu bad_rc=%llu short_ret=%llu "
           "wqe_counter_wraps=%llu laps=%llu ms=%.1f result=%s\n",
           ncqes, nwqes, total, blocks * 8, maxg, seed, delay_ms, cudaGetErrorString(e), h.cqes,
           (unsigned long long)h.mv.ft_ring_ci, (unsigned long long)h.mv.tx_wq.cons_idx, h.polls,
           h.violations, h.bad_rc, h.short_ret, total >> 16, h.cqes / ncqes, ms, ok ? "PASS" : "FAIL");
    return ok ? 0 : 1;
}
