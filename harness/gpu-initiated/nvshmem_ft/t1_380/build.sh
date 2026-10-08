#!/usr/bin/env bash
# build.sh [lib|drivers|all] - build the t1_380 port of NVSHMEM transparent recovery on official v3.8.0-0.
#   lib:     <scratch>/agent_t1_380/src (git: "pristine v3.8.0-0 (270759e5)" -> "base: v3.8.0-0 + inject + nrc"
#            -> working tree = ../t1_close/nvshmem_ibgda_t1close.diff with the barrier.cpp hunk re-anchored),
#            configured with the cmake options of ../../nvshmem_rootcause/official380/build.sh, built in
#            <scratch>/agent_t1_380/build and installed to <scratch>/agent_t1_380/install
#   drivers: ../nvshmem_t1.cu -> <scratch>/agent_t1_380/nvt1_drv (port install) and, with -DT1_STOCK,
#            -> <scratch>/agent_t1_380/nvt1st_drv (unmodified v3.8.0-0 install <scratch>/off380/install)
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
SCRATCH=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
CUDA=/usr/local/cuda-12.8
export PATH=$CUDA/bin:$PATH
W=$SCRATCH/agent_t1_380
STOCK=$SCRATCH/off380/install
what=${1:-all}
if [ "$what" = lib ] || [ "$what" = all ]; then
  [ -f "$W/build/CMakeCache.txt" ] || cmake -S "$W/src" -B "$W/build" -DCMAKE_BUILD_TYPE=release -DCMAKE_CUDA_ARCHITECTURES="75;86" \
    -DCUDA_HOME=$CUDA -DCMAKE_CUDA_COMPILER=$CUDA/bin/nvcc \
    -DNVSHMEM_IBGDA_SUPPORT=ON -DNVSHMEM_IBRC_SUPPORT=ON -DNVSHMEM_USE_GDRCOPY=ON \
    -DNVSHMEM_MPI_SUPPORT=OFF -DNVSHMEM_SHMEM_SUPPORT=OFF -DNVSHMEM_UCX_SUPPORT=OFF \
    -DNVSHMEM_PMIX_SUPPORT=OFF -DNVSHMEM_LIBFABRIC_SUPPORT=OFF -DNVSHMEM_USE_NCCL=OFF \
    -DNVSHMEM_BUILD_TESTS=OFF -DNVSHMEM_BUILD_EXAMPLES=OFF -DNVSHMEM_BUILD_PYTHON_LIB=OFF \
    -DNVSHMEM_BUILD_BITCODE_LIBRARY=OFF -DNVSHMEM_BUILD_LTOIR_LIBRARY=OFF \
    -DNVSHMEM_BUILD_HYDRA_LAUNCHER=OFF -DNVSHMEM_BUILD_TXZ_PACKAGE=OFF \
    -DCMAKE_INSTALL_PREFIX="$W/install" > "$W/cmake.log" 2>&1
  ( time nice -n 10 make -C "$W/build" -j16 > "$W/build_lib.log" 2>&1 ) 2> "$W/build_lib.time"
  nice -n 10 make -C "$W/build" install > "$W/install.log" 2>&1
fi
if [ "$what" = drivers ] || [ "$what" = all ]; then
  drv() {  # drv <install> <out> [extra nvcc flags]
    "$CUDA/bin/nvcc" -std=c++17 -O2 -rdc=true -ccbin g++ ${3:-} \
      -gencode=arch=compute_75,code=sm_75 -gencode=arch=compute_86,code=sm_86 \
      -Xcompiler '-Wall,-Wextra' -Xptxas -v \
      -I"$1/include" "$HERE/../nvshmem_t1.cu" -o "$2" \
      -L"$1/lib" -lnvshmem_host -lnvshmem_device \
      -L"$CUDA/lib64" -lcudart -lcuda -ldl -lpthread 2> "$2.ptxas.log" || { cat "$2.ptxas.log"; exit 1; }
    grep -E "warning|error" "$2.ptxas.log" | grep -v "ptxas info" || true
  }
  drv "$W/install" "$W/nvt1_drv"
  drv "$STOCK" "$W/nvt1st_drv" -DT1_STOCK
fi
md5sum "$W"/install/lib/nvshmem_transport_ibgda.so.7.0.0 "$W"/install/lib/libnvshmem_host.so.3.8.0 "$W"/nvt1_drv "$W"/nvt1st_drv 2>/dev/null || true
