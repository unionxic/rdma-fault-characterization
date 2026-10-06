#!/usr/bin/env bash
# Build the S2 driver (../../gin_ts2.cu, an unmodified GIN application) against an NCCL build tree. The GIN
# device API is header-only, so the driver must be compiled against the tree it runs with.
#   default: the S2 tree                -> $SCR/agent_ts2/gin_ts2
#   S1=1:    the S1 tree (read only)    -> $SCR/agent_ts2/gin_ts2_s1   (S1 flag off/on latency cells)
#   BASE=1:  the gpudb v2 tree (read only) -> $SCR/agent_ts2/gin_ts2_base (flag-off baseline)
#   VAR=sys: the S2 tree with the gate atomics at system scope (-DNCCL_GIN_TS_GATE_SYS; measurement only)
# Also builds the gate micro-test (../../gate_ce_test.cu) -> $SCR/agent_ts2/gate_ce_test.
set -euo pipefail
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
DEFS=""
if [ "${BASE:-0}" = 1 ]; then
  NCCL_BUILD=$SCR/gi/gin_recovery/build_gpudb; OUT=$SCR/agent_ts2/gin_ts2_base
elif [ "${S1:-0}" = 1 ]; then
  NCCL_BUILD=$SCR/agent_ts1/build; OUT=$SCR/agent_ts2/gin_ts2_s1
else
  NCCL_BUILD=${NCCL_BUILD:-$SCR/agent_ts2/build}; OUT=${OUT:-$SCR/agent_ts2/gin_ts2}
  case "${VAR:-}" in
    "") ;;
    sys) DEFS="-DNCCL_GIN_TS_GATE_SYS"; OUT=$SCR/agent_ts2/var/sys/gin_ts2 ;;
    *) echo "unknown VAR ${VAR}" >&2; exit 2 ;;
  esac
fi
mkdir -p "$(dirname "$OUT")"
D=$(cd "$(dirname "$0")/../.." && pwd)
/usr/local/cuda-12.8/bin/nvcc -std=c++17 -O2 --expt-relaxed-constexpr $DEFS \
  -gencode=arch=compute_75,code=sm_75 -gencode=arch=compute_86,code=sm_86 \
  -isystem "$NCCL_BUILD/include" \
  -Xcompiler "-Wall,-Wextra,-Werror,-Wno-missing-field-initializers" \
  "$D/gin_ts2.cu" -o "$OUT" -L "$NCCL_BUILD/lib" -lnccl -lcudart -Xlinker -rpath,"$NCCL_BUILD/lib"
echo "built $OUT against $NCCL_BUILD $DEFS"
# the minimal bidirectional program (../../gin_bidir_min.cu): S2 tree -> gin_bidir_min, gpudb tree -> gin_bidir_min_base
if [ -z "${VAR:-}" ] && [ "${S1:-0}" != 1 ]; then
  MOUT=$SCR/agent_ts2/gin_bidir_min; [ "${BASE:-0}" = 1 ] && MOUT=$SCR/agent_ts2/gin_bidir_min_base
  /usr/local/cuda-12.8/bin/nvcc -std=c++17 -O2 --expt-relaxed-constexpr \
    -gencode=arch=compute_75,code=sm_75 -gencode=arch=compute_86,code=sm_86 \
    -isystem "$NCCL_BUILD/include" -Xcompiler "-Wall,-Wextra,-Werror,-Wno-missing-field-initializers" \
    "$D/gin_bidir_min.cu" -o "$MOUT" -L "$NCCL_BUILD/lib" -lnccl -lcudart -Xlinker -rpath,"$NCCL_BUILD/lib"
  echo "built $MOUT against $NCCL_BUILD"
fi
if [ "${BASE:-0}" != 1 ] && [ "${S1:-0}" != 1 ] && [ -z "${VAR:-}" ]; then
  /usr/local/cuda-12.8/bin/nvcc -std=c++17 -O2 -gencode=arch=compute_75,code=sm_75 -gencode=arch=compute_86,code=sm_86 \
    -Xcompiler "-Wall,-Wextra,-Werror" "$D/gate_ce_test.cu" -o "$SCR/agent_ts2/gate_ce_test"
  echo "built $SCR/agent_ts2/gate_ce_test"
fi
