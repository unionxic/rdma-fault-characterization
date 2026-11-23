#!/usr/bin/env bash
# Build the Q4 driver (gin_q4.cu) against the Q4 NCCL build tree (v2.32.3-1 +
# gin/gin_fault_inject.diff + gin_q4/gin_q4_classify.diff). The device code of GIN
# is header-only, so the driver must be compiled against the Q4 headers.
# NCCL headers are included with -isystem (their own -Wextra warnings, e.g. unused
# parameters in stock gin__funcs.h, are not ours); -Werror applies to gin_q4.cu.
# -Wno-missing-field-initializers: the NCCL_*_INITIALIZER macros set only some
# fields on purpose; every other host warning is an error.
set -euo pipefail
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad/gi/gin_q4
NCCL_BUILD=${NCCL_BUILD:-$SCR/build}
OUT=${OUT:-$SCR/gin_q4}
SRC=$(cd "$(dirname "$0")/.." && pwd)/gin_q4.cu
/usr/local/cuda-12.8/bin/nvcc -std=c++17 -O2 --expt-relaxed-constexpr \
  -gencode=arch=compute_75,code=sm_75 -gencode=arch=compute_86,code=sm_86 \
  -isystem "$NCCL_BUILD/include" \
  -Xcompiler "-Wall,-Wextra,-Werror,-Wno-missing-field-initializers" \
  "$SRC" -o "$OUT" \
  -L "$NCCL_BUILD/lib" -lnccl -lcudart -Xlinker -rpath,"$NCCL_BUILD/lib"
echo "built $OUT"
