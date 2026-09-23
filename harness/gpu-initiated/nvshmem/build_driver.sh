#!/usr/bin/env bash
# build_driver.sh - compile nvshmem_fault.cu against our from-source NVSHMEM.
# Builds a fatbin for sm_75 (rain) and sm_86 (sunny). Host code is -Wall -Wextra clean.
set -eu

NVSHMEM_HOME=${NVSHMEM_HOME:-/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad/gi/nvshmem/install}
CUDA_HOME=${CUDA_HOME:-/usr/local/cuda-12.8}
OUT=${OUT:-$(dirname "$0")/nvshmem_fault}

"$CUDA_HOME/bin/nvcc" -std=c++17 -rdc=true -ccbin g++ \
  -gencode=arch=compute_75,code=sm_75 \
  -gencode=arch=compute_86,code=sm_86 \
  -Xcompiler '-Wall,-Wextra' \
  -I"$NVSHMEM_HOME/include" \
  "$(dirname "$0")/nvshmem_fault.cu" -o "$OUT" \
  -L"$NVSHMEM_HOME/lib" -lnvshmem_host -lnvshmem_device \
  -L"$CUDA_HOME/lib64" -lcudart -lcuda

echo "built: $OUT"
