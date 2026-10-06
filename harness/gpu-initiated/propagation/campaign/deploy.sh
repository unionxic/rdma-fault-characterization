#!/usr/bin/env bash
# deploy.sh - build the campaign binaries on rain and copy them to ~/gi-bundle on both nodes.
#   evrec           -> ~/gi-bundle/evrec/evrec
#   nvs_kill_repro  -> ~/gi-bundle/nvshmem_off380/bin/   (official v3.8.0-0 install, see official380/)
#   gin_fault       -> ~/gi-bundle/gin/                  (stock NCCL 2.32.3 bundle)
#   gin_q4          -> ~/gi-bundle/gin_q4/               (Q4 NCCL bundle)
# The libraries in those bundles are not touched. Prints md5 of every deployed binary on both nodes.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
P=$(cd "$HERE/.." && pwd)            # propagation/
G=$(cd "$P/.." && pwd)               # gpu-initiated/
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
CUDA=/usr/local/cuda-12.8
B=$HOME/gi-bundle

make -C "$P/evrec"
mkdir -p "$B/evrec" && cp "$P/evrec/evrec" "$B/evrec/evrec"

I=$SCR/off380/install
[ -d "$I" ] || { echo "no NVSHMEM v3.8.0-0 install at $I (rebuild with official380/build.sh)"; exit 1; }
$CUDA/bin/nvcc -std=c++17 -rdc=true -gencode=arch=compute_75,code=sm_75 -gencode=arch=compute_86,code=sm_86 \
  -Xcompiler -Wall,-Wextra -I"$I/include" "$G/nvshmem_rootcause/official380/kill_repro.cu" \
  -o "$B/nvshmem_off380/bin/nvs_kill_repro" -L"$I/lib" -lnvshmem_host -lnvshmem_device -L$CUDA/lib64 -lcudart -lcuda

OUT=$B/gin/gin_fault bash "$G/gin/scripts/build_driver.sh"
OUT=$B/gin_q4/gin_q4 bash "$G/gin_q4/scripts/build_driver.sh"

FILES="evrec/evrec nvshmem_off380/bin/nvs_kill_repro gin/gin_fault gin_q4/gin_q4"
ssh -n sunny "mkdir -p gi-bundle/evrec"
for f in $FILES; do scp -q "$B/$f" "sunny:gi-bundle/$f"; done
echo "== rain";  (cd "$B" && md5sum $FILES)
echo "== sunny"; ssh -n sunny "cd gi-bundle && md5sum $FILES"
