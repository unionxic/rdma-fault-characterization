#!/usr/bin/env bash
# Build the recovery driver (gin_rec.cu) against the recovery NCCL build tree (v2.32.3-1 +
# ../gin/gin_fault_inject.diff + ../gin_q4/gin_q4_classify.diff + gin_recovery.diff). The GIN
# device API is header-only and the recovery API is declared in the patched nccl.h, so the driver
# must be compiled against this build's headers. NCCL headers are -isystem (their own warnings are
# not ours); -Werror applies to gin_rec.cu.
set -euo pipefail
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad/gi/gin_recovery
NCCL_BUILD=${NCCL_BUILD:-$SCR/build}
OUT=${OUT:-$SCR/gin_rec}
SRC=$(cd "$(dirname "$0")/.." && pwd)/gin_rec.cu
/usr/local/cuda-12.8/bin/nvcc -std=c++17 -O2 --expt-relaxed-constexpr \
  -gencode=arch=compute_75,code=sm_75 -gencode=arch=compute_86,code=sm_86 \
  -isystem "$NCCL_BUILD/include" \
  -Xcompiler "-Wall,-Wextra,-Werror,-Wno-missing-field-initializers" \
  "$SRC" -o "$OUT" \
  -L "$NCCL_BUILD/lib" -lnccl -lcudart -Xlinker -rpath,"$NCCL_BUILD/lib"
echo "built $OUT"
