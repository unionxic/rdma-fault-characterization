// ff_ops.cu - work package 4's machine-code comparison of the GDAKI device operations one by one (EXPERIMENT.md 12).
// Compiled only (never run) against two header sets (work package 3's, or hk's, and this package's): one small kernel per
// operation calls the GDAKI backend the way NCCL's front end does (gin__funcs.h: a one-thread coop for put and putValue,
// the caller's coop for get), so each kernel's SASS holds that operation and nothing else. Whole programs are compared
// too (prog_sass.sh), but there the compiler reschedules the whole kernel around the new branch; here the differences
// stay readable. The arguments come from kernel parameters so nothing is folded away.
#include <nccl.h>
#include "nccl_device.h"

#define GD NCCL_NET_DEVICE_GIN_GDAKI

static __device__ ncclGinSignalDescriptor sigNone() {
  ncclGinSignalDescriptor s;
  s.type = NCCL_GIN_SIGNAL_TYPE_NONE;
  s.isStrong = false;
  return s;
}
static __device__ ncclGinSignalDescriptor sigIndexed(ncclGinSignal_t id) {
  ncclGinSignalDescriptor s;
  s.type = NCCL_GIN_SIGNAL_TYPE_INDEXED;
  s.indexedSignal.signalId = id;
  s.isStrong = false;
  return s;
}
static __device__ ncclGinSignalDescriptor sigVa(ncclGinWindow_t w, size_t off) {
  ncclGinSignalDescriptor s;
  s.type = NCCL_GIN_SIGNAL_TYPE_VA;
  s.vaSignal.signalWindow = w;
  s.vaSignal.signalOffset = off;
  s.vaSignal.ncclWindow = nullptr;
  s.isStrong = false;
  return s;
}

// put without a signal
extern "C" __global__ void k_put(ncclGinCtx ctx, int peer, ncclGinWindow_t d, size_t dOff, ncclGinWindow_t s, size_t sOff,
                                 size_t bytes) {
  ncclGinApi_Put<GD>::call(ctx, ncclCoopThread(), peer, true, d, dOff, s, sOff, bytes, sigNone(), ncclGinSignalInc, 0,
                           false, 0, false, nullptr, cuda::thread_scope_system, cuda::thread_scope_device);
}
// put with an indexed signal (the context's signal table)
extern "C" __global__ void k_put_sig(ncclGinCtx ctx, int peer, ncclGinWindow_t d, size_t dOff, ncclGinWindow_t s,
                                     size_t sOff, size_t bytes, ncclGinSignal_t sig, uint64_t val) {
  ncclGinApi_Put<GD>::call(ctx, ncclCoopThread(), peer, true, d, dOff, s, sOff, bytes, sigIndexed(sig), ncclGinSignalAdd,
                           val, false, 0, false, nullptr, cuda::thread_scope_system, cuda::thread_scope_device);
}
// put with a VA signal (a window)
extern "C" __global__ void k_put_vasig(ncclGinCtx ctx, int peer, ncclGinWindow_t d, size_t dOff, ncclGinWindow_t s,
                                       size_t sOff, size_t bytes, ncclGinWindow_t sw, size_t swOff) {
  ncclGinApi_Put<GD>::call(ctx, ncclCoopThread(), peer, true, d, dOff, s, sOff, bytes, sigVa(sw, swOff), ncclGinSignalInc,
                           0, false, 0, false, nullptr, cuda::thread_scope_system, cuda::thread_scope_device);
}
// a signal alone (the front end's signal(): put without windows)
extern "C" __global__ void k_signal(ncclGinCtx ctx, int peer, ncclGinSignal_t sig, uint64_t val) {
  ncclGinApi_Put<GD>::call(ctx, ncclCoopThread(), peer, false, nullptr, 0, nullptr, 0, 0, sigIndexed(sig),
                           ncclGinSignalAdd, val, false, 0, false, nullptr, cuda::thread_scope_system,
                           cuda::thread_scope_device);
}
// putValue without and with a signal
extern "C" __global__ void k_putvalue(ncclGinCtx ctx, int peer, ncclGinWindow_t d, size_t dOff, uint64_t v) {
  ncclGinApi_PutValue<GD>::call(ctx, ncclCoopThread(), peer, d, dOff, v, sigNone(), ncclGinSignalInc, 0, false, nullptr,
                                cuda::thread_scope_system, cuda::thread_scope_device);
}
extern "C" __global__ void k_putvalue_sig(ncclGinCtx ctx, int peer, ncclGinWindow_t d, size_t dOff, uint32_t v,
                                          ncclGinSignal_t sig) {
  ncclGinApi_PutValue<GD>::call(ctx, ncclCoopThread(), peer, d, dOff, v, sigIndexed(sig), ncclGinSignalInc, 0, false,
                                nullptr, cuda::thread_scope_system, cuda::thread_scope_device);
}
// get with a one-thread coop and with a CTA coop (the front end passes the caller's coop)
extern "C" __global__ void k_get(ncclGinCtx ctx, int peer, ncclGinWindow_t r, size_t rOff, ncclGinWindow_t l, size_t lOff,
                                 size_t bytes) {
  ncclGinApi_Get<GD>::call(ctx, ncclCoopThread(), peer, r, rOff, l, lOff, bytes, false, nullptr);
}
extern "C" __global__ void k_get_cta(ncclGinCtx ctx, int peer, ncclGinWindow_t r, size_t rOff, ncclGinWindow_t l,
                                     size_t lOff, size_t bytes) {
  ncclGinApi_Get<GD>::call(ctx, ncclCoopCta(), peer, r, rOff, l, lOff, bytes, false, nullptr);
}
// the wait paths: flush (blocking, with an abort word, with a timeout), flushAsync + wait
extern "C" __global__ void k_flush(ncclGinCtx ctx, uint32_t* abortFlag) {
  ncclGinApi_Flush<GD>::call(ctx, ncclCoopThread(), false, nullptr, cuda::memory_order_acquire, abortFlag);
}
extern "C" __global__ void k_flush_timeout(ncclGinCtx ctx, uint32_t* abortFlag, uint64_t cycles, int* rc) {
  *rc = (int)ncclGinApi_Flush<GD>::call(ctx, ncclCoopThread(), false, nullptr, cuda::memory_order_acquire, abortFlag,
                                        cycles);
}
extern "C" __global__ void k_flushasync_wait(ncclGinCtx ctx, int peer, uint32_t* abortFlag) {
  ncclGinRequest_t req;
  ncclGinApi_FlushAsync<GD>::call(ctx, peer, &req, false, nullptr, 0);
  ncclGinApi_Wait<GD>::call(ctx, req, false, nullptr, cuda::memory_order_acquire, abortFlag);
}
