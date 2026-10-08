#!/usr/bin/env bash
# Build the gin-multirank driver (gin_mr.cu, an unmodified GIN application) against one NCCL build tree, on rain, with
# no cluster action. The GIN device API (and the transparent-recovery gate) is header-only, so the driver must be
# compiled against the headers of the libnccl it runs with: one binary per recovery build.
# usage: build_mr.sh <key> <nccl build dir>     e.g. build_mr.sh ow $SCR/agent_ts2ow/build
# Output: $SCR/agent_mr/out/<key>/gin_mr and $SCR/agent_mr/out/<key>/build_info.txt (md5 of the driver, md5 of the tree's
# libnccl, a digest of the tree's installed headers: md5 of the sorted "md5sum" list of every file under include/).
# Two trees with the same header digest give the same device code; the driver of one then serves both.
# No rpath: the runner sets LD_LIBRARY_PATH to the recovery bundle (deploy_mr.sh checks with ldd).
set -euo pipefail
KEY=${1:?key (ow, hd, ...)}; NB=${2:?nccl build dir}
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
D=$(cd "$(dirname "$0")" && pwd)
OUT=$SCR/agent_mr/out/$KEY
[ -f "$NB/include/nccl_device.h" ] && [ -f "$NB/lib/libnccl.so.2.32.3" ] || { echo "not an NCCL build dir: $NB" >&2; exit 1; }
mkdir -p "$OUT"
/usr/local/cuda-12.8/bin/nvcc -std=c++17 -O2 --expt-relaxed-constexpr \
  -gencode=arch=compute_75,code=sm_75 -gencode=arch=compute_86,code=sm_86 \
  -isystem "$NB/include" -Xcompiler "-Wall,-Wextra,-Werror,-Wno-missing-field-initializers" \
  "$D/gin_mr.cu" -o "$OUT/gin_mr.tmp" -L "$NB/lib" -lnccl -lcudart
mv "$OUT/gin_mr.tmp" "$OUT/gin_mr"
{
  echo "key=$KEY built=$(date '+%F %T') nccl_build=$NB"
  echo "gin_mr_md5=$(md5sum < "$OUT/gin_mr" | cut -d' ' -f1)"
  echo "gin_mr_cu_md5=$(md5sum < "$D/gin_mr.cu" | cut -d' ' -f1)"
  echo "libnccl_md5=$(md5sum < "$NB/lib/libnccl.so.2.32.3" | cut -d' ' -f1)"
  echo "include_digest=$(cd "$NB/include" && find . -type f | LC_ALL=C sort | xargs md5sum | md5sum | cut -d' ' -f1)"
  echo "nvcc=$(/usr/local/cuda-12.8/bin/nvcc --version | tail -1)"
} > "$OUT/build_info.txt"
cat "$OUT/build_info.txt"
