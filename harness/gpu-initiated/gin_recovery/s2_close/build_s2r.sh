#!/usr/bin/env bash
# Build this study's NCCL library (bundle s2r) and the get-mode driver (bundle s2rget), leaving the step-2 final build
# (agent_ts2, libnccl 0a32b875) untouched.
#   1. once: copy the step-2 source tree and build directory agent_ts2 -> agent_ts2r; rewrite the absolute paths in the
#      dependency files (*.d) and the device manifests and give them back their original mtimes, so that make rebuilds
#      only what changed; commit the step-2 state in the scratch git repo; apply s2r_layer.diff (this study's change).
#   2. incremental make: dev_runtime.cc, transport/net_ib/gdaki/gin_host_gdaki.cc and the version stamp only (no header
#      and no device code changes).
#   3. the get-mode driver: ../gin_ts2.cu against the s2r tree -> agent_ts2r/s2rget/gin_ts2 (-Wall -Wextra -Werror).
# The s2r bundle's driver is the unchanged final step-2 driver (d4b1f082), copied by deploy_s2r.sh, not rebuilt.
set -euo pipefail
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
SRC=$SCR/agent_ts2
DST=$SCR/agent_ts2r
D=$(cd "$(dirname "$0")" && pwd)
GENCODE="-gencode=arch=compute_75,code=sm_75 -gencode=arch=compute_86,code=sm_86"
if [ ! -d "$DST/nccl-src" ]; then
  mkdir -p "$DST"
  cp -a "$SRC/nccl-src" "$SRC/build" "$DST/"
  (cd "$DST/build" && find . \( -name '*.d' -o -name manifest \) -print0 |
     while IFS= read -r -d '' f; do sed -i "s#$SRC/#$DST/#g" "$f"; touch -h -r "$SRC/build/$f" "$f"; done)
  git -C "$DST/nccl-src" -c user.name=build -c user.email=build@localhost commit -qam "step 2 final (libnccl 0a32b875)"
  git -C "$DST/nccl-src" apply "$D/s2r_layer.diff"
fi
echo "to compile: $(make -n -C "$DST/nccl-src" src.build BUILDDIR="$DST/build" CUDA_HOME=/usr/local/cuda-12.8 \
  NVCC_GENCODE="$GENCODE" 2>/dev/null | grep -o -- '-c [^ ]*' | tr '\n' ' ')"
make -j32 -C "$DST/nccl-src" src.build BUILDDIR="$DST/build" CUDA_HOME=/usr/local/cuda-12.8 NVCC_GENCODE="$GENCODE"
mkdir -p "$DST/s2rget"
/usr/local/cuda-12.8/bin/nvcc -std=c++17 -O2 --expt-relaxed-constexpr $GENCODE -isystem "$DST/build/include" \
  -Xcompiler "-Wall,-Wextra,-Werror,-Wno-missing-field-initializers" "$D/../gin_ts2.cu" -o "$DST/s2rget/gin_ts2" \
  -L "$DST/build/lib" -lnccl -lcudart -Xlinker -rpath,"$DST/build/lib"
md5sum "$DST/build/lib/libnccl.so.2.32.3" "$DST/s2rget/gin_ts2"
