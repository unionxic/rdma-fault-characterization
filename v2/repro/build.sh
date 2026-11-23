#!/bin/bash
# Builds repro/gin_*.cu against this folder's NCCL and repro/shmem_*.cu against this folder's NVSHMEM. Run on each host (GPU generations differ).
R=$HOME/rdma-recovery; M=$HOME/opt/openmpi-4.1.8; cd $R/repro
gcc -O2 -shared -fPIC -o libqperr.so qperr.c -ldl -lpthread || exit 1  # fault injector, see qperr.c
for f in gin_*.cu; do /usr/local/cuda/bin/nvcc -std=c++17 -O2 -gencode arch=compute_70,code=sm_70 -gencode arch=compute_80,code=sm_80 \
  -Wno-deprecated-gpu-targets -I$R/nccl/build/include -I$M/include $f -o ${f%.cu} -L$R/nccl/build/lib -lnccl -L$M/lib -lmpi -Xlinker -rpath -Xlinker $R/nccl/build/lib -Xlinker -rpath -Xlinker $M/lib || exit 1; done
S=$R/nvshmem # same flags as NVSHMEM's own perftests (release: NDEBUG); sm_86 because NVSHMEM runs on sunny only
for f in shmem_*.cu; do [ -e $S/build/src/lib/libnvshmem_device.a ] || break; /usr/local/cuda/bin/nvcc -std=c++17 -O3 -DNDEBUG -arch=sm_86 -rdc=true -D__STDC_CONSTANT_MACROS -D__STDC_LIMIT_MACROS \
  -I$S/build/src/include -I$M/include $f -o ${f%.cu} -L$S/build/src/lib -lnvshmem_host -lnvshmem_device -L$M/lib -lmpi \
  -Xlinker -rpath -Xlinker $S/build/src/lib -Xlinker -rpath -Xlinker $M/lib || exit 1; done
