#!/usr/bin/env bash
# Build this study's NCCL library (bundles pr and prd) on top of the gin-reconnect library tree (agent_ts2rc, libnccl
# 8354411f), leaving that tree untouched, and the dual-context driver (bundle prd) against it.
#   1. once: copy agent_ts2rc's source tree and build directory -> agent_ts2pr; rewrite the absolute paths in the
#      dependency files (*.d) and device manifests and give them back their original mtimes, so that make rebuilds only
#      what changed; commit the rc state in the scratch git repo; apply pr_layer.diff (skipped when the working tree
#      already carries it, as while it is being written).
#   2. incremental make: transport/net_ib/gdaki/gin_host_gdaki.cc and the version stamp only (no header, no device code).
#   3. the driver ../gin_ts2.cu (GIN_TS_DUAL mode added) against agent_ts2pr -> agent_ts2pr/gin_ts2 (bundle prd).
# The pr bundle's driver is the unchanged final step-2 driver (d4b1f082), copied by deploy_pr.sh.
set -euo pipefail
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
SRC=$SCR/agent_ts2rc
DST=$SCR/agent_ts2pr
D=$(cd "$(dirname "$0")" && pwd)
GENCODE="-gencode=arch=compute_75,code=sm_75 -gencode=arch=compute_86,code=sm_86"
if [ ! -d "$DST/nccl-src" ]; then
  mkdir -p "$DST"
  cp -a "$SRC/nccl-src" "$SRC/build" "$DST/"
  (cd "$DST/build" && find . \( -name '*.d' -o -name manifest \) -print0 |
     while IFS= read -r -d '' f; do sed -i "s#$SRC/#$DST/#g" "$f"; touch -h -r "$SRC/build/$f" "$f"; done)
  git -C "$DST/nccl-src" -c user.name=build -c user.email=build@localhost commit -qam "gin-reconnect rc (libnccl 8354411f)"
  [ -f "$D/pr_layer.diff" ] && git -C "$DST/nccl-src" apply "$D/pr_layer.diff"
fi
[ "${SETUP_ONLY:-0}" = 1 ] && exit 0
echo "to compile: $(make -n -C "$DST/nccl-src" src.build BUILDDIR="$DST/build" CUDA_HOME=/usr/local/cuda-12.8 \
  NVCC_GENCODE="$GENCODE" 2>/dev/null | grep -o -- '-c [^ ]*' | tr '\n' ' ')"
make -j32 -C "$DST/nccl-src" src.build BUILDDIR="$DST/build" CUDA_HOME=/usr/local/cuda-12.8 NVCC_GENCODE="$GENCODE"
md5sum "$DST/build/lib/libnccl.so.2.32.3"
# the dual-context driver (same command as ../scripts/ts2/build_driver.sh)
/usr/local/cuda-12.8/bin/nvcc -std=c++17 -O2 --expt-relaxed-constexpr \
  -gencode=arch=compute_75,code=sm_75 -gencode=arch=compute_86,code=sm_86 \
  -isystem "$DST/build/include" \
  -Xcompiler "-Wall,-Wextra,-Werror,-Wno-missing-field-initializers" \
  "$D/../gin_ts2.cu" -o "$DST/gin_ts2" -L "$DST/build/lib" -lnccl -lcudart -Xlinker -rpath,"$DST/build/lib"
md5sum "$DST/gin_ts2"
