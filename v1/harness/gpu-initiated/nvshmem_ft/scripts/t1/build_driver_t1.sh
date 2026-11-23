#!/usr/bin/env bash
# build_driver_t1.sh - build the unmodified-application driver nvshmem_t1.cu against the T1 install
# (<scratch>/agent_nvt1/install -> nvt1_drv) and, with BASE=v22, against the v2.2 install
# (<scratch>/agent_ftv2/install -> nvt1v22_drv, the latency baseline). -Wall -Wextra.
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
SCRATCH=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
CUDA_HOME=${CUDA_HOME:-/usr/local/cuda-12.8}
# VARIANT=<name> T1DEV=<n>: build against <scratch>/agent_nvt1/<name>_install (the device bisect builds of
# build_variant.sh; the same -DNVSHMEMI_IBGDA_T1_DEVICE=<n>) -> nvt1_drv_<name>
XDEF=""
if [ "${BASE:-}" = v22 ]; then
  NVSHMEM_HOME=$SCRATCH/agent_ftv2/install; OUT=$SCRATCH/agent_nvt1/nvt1v22_drv
elif [ -n "${VARIANT:-}" ]; then
  NVSHMEM_HOME=$SCRATCH/agent_nvt1/${VARIANT}_install; OUT=$SCRATCH/agent_nvt1/nvt1_drv_$VARIANT
  XDEF="-DNVSHMEMI_IBGDA_T1_DEVICE=${T1DEV:-7}"
else
  NVSHMEM_HOME=$SCRATCH/agent_nvt1/install; OUT=$SCRATCH/agent_nvt1/nvt1_drv
fi
"$CUDA_HOME/bin/nvcc" -std=c++17 -O2 -rdc=true -ccbin g++ $XDEF \
  -gencode=arch=compute_75,code=sm_75 -gencode=arch=compute_86,code=sm_86 \
  -Xcompiler '-Wall,-Wextra' -Xptxas -v \
  -I"$NVSHMEM_HOME/include" "$HERE/../../nvshmem_t1.cu" -o "$OUT" \
  -L"$NVSHMEM_HOME/lib" -lnvshmem_host -lnvshmem_device \
  -L"$CUDA_HOME/lib64" -lcudart -lcuda -ldl -lpthread 2> "$OUT.ptxas.log" || { cat "$OUT.ptxas.log"; exit 1; }
grep -E "warning|error" "$OUT.ptxas.log" | grep -v "ptxas info" || true
echo "built: $OUT ($(md5sum < "$OUT" | cut -c1-8))"
