#!/usr/bin/env bash
# Build this study's NCCL library (bundles pc and pcd) on top of the gin-pair-reset library tree (agent_ts2pr, libnccl
# 51c2426c), leaving that tree untouched.
#   1. once: copy agent_ts2pr's source tree and build directory -> agent_ts2pc; rewrite the absolute paths in the
#      dependency files (*.d) and device manifests and give them back their original mtimes, so that make rebuilds only
#      what changed; commit the pr state in the scratch git repo; apply pc_layer.diff (skipped when the working tree
#      already carries it, as while it is being written).
#   2. incremental make: transport/net_ib/gdaki/gin_host_gdaki.cc and the version stamp only (no header, no device code).
# No driver is built: deploy_pc.sh copies the final step-2 driver (d4b1f082, bundle pc) and gin-pair-reset's
# two-context driver (4926edee, bundle pcd).
set -euo pipefail
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
SRC=$SCR/agent_ts2pr
DST=$SCR/agent_ts2pc
D=$(cd "$(dirname "$0")" && pwd)
GENCODE="-gencode=arch=compute_75,code=sm_75 -gencode=arch=compute_86,code=sm_86"
if [ ! -d "$DST/nccl-src" ]; then
  mkdir -p "$DST"
  cp -a "$SRC/nccl-src" "$SRC/build" "$DST/"
  (cd "$DST/build" && find . \( -name '*.d' -o -name manifest \) -print0 |
     while IFS= read -r -d '' f; do sed -i "s#$SRC/#$DST/#g" "$f"; touch -h -r "$SRC/build/$f" "$f"; done)
  git -C "$DST/nccl-src" -c user.name=build -c user.email=build@localhost commit -qam "gin-pair-reset pr (libnccl 51c2426c)"
  [ -f "$D/pc_layer.diff" ] && git -C "$DST/nccl-src" apply "$D/pc_layer.diff"
fi
[ "${SETUP_ONLY:-0}" = 1 ] && exit 0
echo "to compile: $(make -n -C "$DST/nccl-src" src.build BUILDDIR="$DST/build" CUDA_HOME=/usr/local/cuda-12.8 \
  NVCC_GENCODE="$GENCODE" 2>/dev/null | grep -o -- '-c [^ ]*' | tr '\n' ' ')"
make -j32 -C "$DST/nccl-src" src.build BUILDDIR="$DST/build" CUDA_HOME=/usr/local/cuda-12.8 NVCC_GENCODE="$GENCODE"
md5sum "$DST/build/lib/libnccl.so.2.32.3"
