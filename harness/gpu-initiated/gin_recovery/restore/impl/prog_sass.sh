#!/usr/bin/env bash
# prog_sass.sh <include dir> <tag> <out dir>: compile the GIN programs the fail-fast machine-code comparison uses (work
# packages 3 and 4: gin-remaining's gin_ts2.cu and gin_mr.cu, NCCL's example 09_gin_optimizations/01_ring_exchange) against
# one header set, for sm_75 and sm_86 (the study's two GPUs), to objects only (no link, nothing runs), and dump their SASS:
# <out>/<prog>_<tag>.o and .sass. Flags as gin-remaining's build_hr.sh (drivers) and NCCL's examples.mk.
set -euo pipefail
INC=${1:?include dir}; TAG=${2:?tag}; O=${3:?out dir}
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
D=$(cd "$(dirname "$0")" && pwd)
CU=/usr/local/cuda-12.8/bin
GENCODE="-gencode=arch=compute_75,code=sm_75 -gencode=arch=compute_86,code=sm_86"
RING=$SCR/agent_rs/nccl-src/docs/examples/09_gin_optimizations/01_ring_exchange/c
mkdir -p "$O"
cc() {  # cc <name> <source> [extra flags]
  local n=$1 src=$2; shift 2
  nice -n 19 "$CU/nvcc" -std=c++17 -O2 --expt-relaxed-constexpr $GENCODE -isystem "$INC" "$@" -c "$src" \
    -o "$O/${n}_$TAG.o" > "$O/${n}_$TAG.log" 2>&1 || { cat "$O/${n}_$TAG.log" >&2; exit 1; }
  "$CU/cuobjdump" -sass "$O/${n}_$TAG.o" > "$O/${n}_$TAG.sass"
  echo "$n $TAG: $(grep -c '' "$O/${n}_$TAG.sass") SASS lines, warnings $(grep -ci warning "$O/${n}_$TAG.log" || true)"
}
cc gin_ts2 "$D/../../gin_ts2.cu" -Xcompiler "-Wall,-Wextra,-Werror,-Wno-missing-field-initializers"
cc gin_mr "$D/../../remaining/gin_mr.cu" -Xcompiler "-Wall,-Wextra,-Werror,-Wno-missing-field-initializers"
cc ring "$RING/main.cu" -I"$RING/../../../common/include"
