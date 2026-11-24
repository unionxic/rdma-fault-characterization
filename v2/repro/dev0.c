// dev0.c: LD_PRELOAD shim that makes every cudaSetDevice() select device 0, so that NCCL's examples (which
// take the node-local rank as the device) run several ranks on a node with one GPU.
// build: gcc -O2 -shared -fPIC -o libdev0.so dev0.c -ldl      use with NCCL_MULTI_RANK_GPU_ENABLE=1
#define _GNU_SOURCE
#include <dlfcn.h>
int cudaSetDevice(int device) {
  static int (*real)(int);
  if (!real) real = (int (*)(int))dlsym(RTLD_NEXT, "cudaSetDevice");
  (void)device;
  return real(0);
}
