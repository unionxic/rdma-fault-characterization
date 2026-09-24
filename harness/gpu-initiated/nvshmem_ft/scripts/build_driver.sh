#!/usr/bin/env bash
# build_driver.sh - compile nvshmem_ft.cu against the FT build of NVSHMEM (device API is header-only,
# so the driver must be built against the patched headers). sm_75 (rain) + sm_86 (sunny).
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
SCRATCH=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
NVSHMEM_HOME=${NVSHMEM_HOME:-$SCRATCH/gi/nvshmem_ft/install}
CUDA_HOME=${CUDA_HOME:-/usr/local/cuda-12.8}
OUT=${OUT:-$SCRATCH/gi/nvshmem_ft/nvft_drv}
"$CUDA_HOME/bin/nvcc" -std=c++17 -O2 -rdc=true -ccbin g++ \
  -gencode=arch=compute_75,code=sm_75 -gencode=arch=compute_86,code=sm_86 \
  -Xcompiler '-Wall,-Wextra' -Xptxas -v \
  -I"$NVSHMEM_HOME/include" "$HERE/../nvshmem_ft.cu" -o "$OUT" \
  -L"$NVSHMEM_HOME/lib" -lnvshmem_host -lnvshmem_device \
  -L"$CUDA_HOME/lib64" -lcudart -lcuda -ldl 2> "$OUT.ptxas.log" || { cat "$OUT.ptxas.log"; exit 1; }
grep -E "warning|error" "$OUT.ptxas.log" | grep -v "ptxas info" || true
echo "built: $OUT"
