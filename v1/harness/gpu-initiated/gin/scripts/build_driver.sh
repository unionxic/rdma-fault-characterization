#!/usr/bin/env bash
# Build the GIN fault driver against our own patched NCCL 2.32.3 build tree.
# -Wno-missing-field-initializers: the NCCL_*_INITIALIZER macros set only some
# fields on purpose (append-only versioned structs); every other host warning
# is treated as an error.
set -euo pipefail
NCCL_BUILD=${NCCL_BUILD:-/tmp/scratch/gi/gin/build}
OUT=${OUT:-/tmp/scratch/gi/gin/gin_fault}
SRC=$(cd "$(dirname "$0")/.." && pwd)/gin_fault.cu
/usr/local/cuda-12.8/bin/nvcc -std=c++17 -O2 --expt-relaxed-constexpr \
  -gencode=arch=compute_75,code=sm_75 -gencode=arch=compute_86,code=sm_86 \
  -I "$NCCL_BUILD/include" \
  -Xcompiler "-Wall,-Wextra,-Wno-missing-field-initializers" \
  "$SRC" -o "$OUT" \
  -L "$NCCL_BUILD/lib" -lnccl -lcudart -Xlinker -rpath,"$NCCL_BUILD/lib"
echo "built $OUT"
