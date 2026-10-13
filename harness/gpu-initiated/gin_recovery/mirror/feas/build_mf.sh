#!/usr/bin/env bash
# build_mf.sh <out name> - build gin-mirror's feasibility tool mirror_feas.cu (EXPERIMENT.md 9.8) on rain into a NEW scratch
# folder $SCR/mirror_feas/<out name>/ (mirror_feas, build.log, build_src.txt). No GPU or RDMA program runs here; nothing
# outside that folder is written; the mlx5 PRM header (QUERY_QP layouts) is read from the DOCA GPUNetIO copy inside the
# gpu-detect hw tree (read only). sm_75 (rain, Quadro RTX 5000) and sm_86 (sunny, RTX A4000), -Werror. A folder that already
# holds a build is refused: nvcc output is not byte-reproducible, the deployed md5 is the one recorded in EXPERIMENT.md 12.
set -euo pipefail
NAME=${1:?out name: a new folder, e.g. mf1}
case "$NAME" in */*|*..*) echo "bad out name" >&2; exit 2 ;; esac
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
D=$(cd "$(dirname "$0")" && pwd)
CUDA=/usr/local/cuda-12.8
PRM=$SCR/agent_gd/gin/nccl-src/src/transport/net_ib/gdaki/doca-gpunetio/include/host
O=$SCR/mirror_feas/$NAME
[ -e "$O/mirror_feas" ] && { echo "refusing: $O already holds a build" >&2; exit 1; }
[ -f "$PRM/mlx5_ifc.h" ] || { echo "missing $PRM/mlx5_ifc.h" >&2; exit 1; }
mkdir -p "$O"
md5() { md5sum < "$1" | cut -c1-32; }
nice -n 19 ionice -c3 "$CUDA/bin/nvcc" -std=c++17 -O2 -gencode=arch=compute_75,code=sm_75 -gencode=arch=compute_86,code=sm_86 \
  -Xcompiler "-Wall,-Wextra,-Werror" -I"$PRM" "$D/mirror_feas.cu" -o "$O/mirror_feas" -libverbs -lmlx5 -lcuda > "$O/build.log" 2>&1
echo "mirror_feas.cu $(md5 "$D/mirror_feas.cu") mlx5_ifc.h $(md5 "$PRM/mlx5_ifc.h") $("$CUDA/bin/nvcc" --version | tail -1 | tr ' ' '_') \
warning_lines $(grep -ci warning "$O/build.log" || true) sass $("$CUDA/bin/cuobjdump" --list-elf "$O/mirror_feas" | grep -o 'sm_[0-9]*' | sort -u | tr '\n' ' ')\
built $(date '+%F %T')" > "$O/build_src.txt"
echo "mirror_feas $(md5 "$O/mirror_feas") ($(cat "$O/build_src.txt"))"
