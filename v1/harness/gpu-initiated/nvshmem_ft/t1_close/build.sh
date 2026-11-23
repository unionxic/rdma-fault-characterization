#!/usr/bin/env bash
# build.sh - build the t1_close library (incremental, in the T1 scratch tree) and the driver.
#   library: <scratch>/agent_nvt1/src (git: ... "T1 final3" + the t1_close working tree), build dir
#            <scratch>/agent_nvt1/build, installed to <scratch>/agent_nvt1/install
#   driver:  ../nvshmem_t1.cu -> <scratch>/agent_t1close/nvt1_drv (-Wall -Wextra)
# The final3 install and driver were copied to <scratch>/agent_t1close/*_final3_backup first; the
# deployed final3 bundle ~/gi-bundle/nvshmem_t1 is never touched.
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
SCRATCH=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
CUDA_HOME=${CUDA_HOME:-/usr/local/cuda-12.8}
export PATH=$CUDA_HOME/bin:$PATH
NV=$SCRATCH/agent_nvt1
OUTD=$SCRATCH/agent_t1close
mkdir -p "$OUTD"
nice -n 10 make -C "$NV/build" -j12 install > "$OUTD/build_lib.log" 2>&1
NVSHMEM_HOME=$NV/install
"$CUDA_HOME/bin/nvcc" -std=c++17 -O2 -rdc=true -ccbin g++ \
  -gencode=arch=compute_75,code=sm_75 -gencode=arch=compute_86,code=sm_86 \
  -Xcompiler '-Wall,-Wextra' -Xptxas -v \
  -I"$NVSHMEM_HOME/include" "$HERE/../nvshmem_t1.cu" -o "$OUTD/nvt1_drv" \
  -L"$NVSHMEM_HOME/lib" -lnvshmem_host -lnvshmem_device \
  -L"$CUDA_HOME/lib64" -lcudart -lcuda -ldl -lpthread 2> "$OUTD/nvt1_drv.ptxas.log" || { cat "$OUTD/nvt1_drv.ptxas.log"; exit 1; }
grep -E "warning|error" "$OUTD/nvt1_drv.ptxas.log" | grep -v "ptxas info" || true
md5sum "$NV/install/lib/nvshmem_transport_ibgda.so.7.0.0" "$NV/install/lib/libnvshmem_host.so.3.9.0" "$OUTD/nvt1_drv"
