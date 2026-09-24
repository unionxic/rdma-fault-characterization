#!/usr/bin/env bash
# Build the S1 driver (../../gin_ts1.cu, an unmodified GIN application) against an NCCL build tree.
#   default: the transparent-S1 tree   -> $SCR/agent_ts1/gin_ts1
#   BASE=1:  the gpudb (v2) tree, read only -> $SCR/agent_ts1/gin_ts1_base  (flag-off equivalence baseline)
# The GIN device API is header-only, so the driver must be compiled against the tree it runs with.
set -euo pipefail
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
if [ "${BASE:-0}" = 1 ]; then
  NCCL_BUILD=$SCR/gi/gin_recovery/build_gpudb; OUT=$SCR/agent_ts1/gin_ts1_base
else
  NCCL_BUILD=${NCCL_BUILD:-$SCR/agent_ts1/build}; OUT=${OUT:-$SCR/agent_ts1/gin_ts1}
fi
SRC=$(cd "$(dirname "$0")/../.." && pwd)/gin_ts1.cu
/usr/local/cuda-12.8/bin/nvcc -std=c++17 -O2 --expt-relaxed-constexpr \
  -gencode=arch=compute_75,code=sm_75 -gencode=arch=compute_86,code=sm_86 \
  -isystem "$NCCL_BUILD/include" \
  -Xcompiler "-Wall,-Wextra,-Werror,-Wno-missing-field-initializers" \
  "$SRC" -o "$OUT" -L "$NCCL_BUILD/lib" -lnccl -lcudart -Xlinker -rpath,"$NCCL_BUILD/lib"
echo "built $OUT against $NCCL_BUILD"
