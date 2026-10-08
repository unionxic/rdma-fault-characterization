#!/usr/bin/env bash
# Build this study's NCCL library (bundle rc) on top of the gin-s2-close library tree (agent_ts2r, libnccl ba4984bd),
# leaving that tree untouched.
#   1. once: copy agent_ts2r's source tree and build directory -> agent_ts2rc; rewrite the absolute paths in the
#      dependency files (*.d) and device manifests and give them back their original mtimes, so that make rebuilds only
#      what changed; commit the s2r state in the scratch git repo; apply rc_layer.diff.
#   2. incremental make: transport/net_ib/gdaki/gin_host_gdaki.cc and the version stamp only (no header, no device code).
# The rc bundle's driver is the unchanged final step-2 driver (d4b1f082), copied by deploy_rc.sh.
set -euo pipefail
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
SRC=$SCR/agent_ts2r
DST=$SCR/agent_ts2rc
D=$(cd "$(dirname "$0")" && pwd)
GENCODE="-gencode=arch=compute_75,code=sm_75 -gencode=arch=compute_86,code=sm_86"
if [ ! -d "$DST/nccl-src" ]; then
  mkdir -p "$DST"
  cp -a "$SRC/nccl-src" "$SRC/build" "$DST/"
  (cd "$DST/build" && find . \( -name '*.d' -o -name manifest \) -print0 |
     while IFS= read -r -d '' f; do sed -i "s#$SRC/#$DST/#g" "$f"; touch -h -r "$SRC/build/$f" "$f"; done)
  git -C "$DST/nccl-src" -c user.name=build -c user.email=build@localhost commit -qam "gin-s2-close s2r (libnccl ba4984bd)"
  git -C "$DST/nccl-src" apply "$D/rc_layer.diff"
fi
echo "to compile: $(make -n -C "$DST/nccl-src" src.build BUILDDIR="$DST/build" CUDA_HOME=/usr/local/cuda-12.8 \
  NVCC_GENCODE="$GENCODE" 2>/dev/null | grep -o -- '-c [^ ]*' | tr '\n' ' ')"
make -j32 -C "$DST/nccl-src" src.build BUILDDIR="$DST/build" CUDA_HOME=/usr/local/cuda-12.8 NVCC_GENCODE="$GENCODE"
md5sum "$DST/build/lib/libnccl.so.2.32.3"
