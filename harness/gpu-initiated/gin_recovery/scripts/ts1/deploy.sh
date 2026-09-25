#!/usr/bin/env bash
# Deploy the S1 bundle to ~/gi-bundle/gin_ts1/ on rain (local) and sunny, and check md5s:
#   libnccl.so.2.32.3 + gin_ts1            the transparent-S1 build and its driver
#   base/libnccl.so.2.32.3 + base/gin_ts1  the gpudb (v2) build, copied read-only, with the same driver
#                                          source compiled against it (flag-off equivalence baseline)
# File copies over the management network only; no cluster lock needed.
set -euo pipefail
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
SUNNY_SSH=${SUNNY_SSH:-unionxic@192.0.2.194}
B=gi-bundle/gin_ts1
LIB=$SCR/agent_ts1/build/lib/libnccl.so.2.32.3
BIN=$SCR/agent_ts1/gin_ts1
BLIB=$SCR/gi/gin_recovery/build_gpudb/lib/libnccl.so.2.32.3
BBIN=$SCR/agent_ts1/gin_ts1_base
mkdir -p ~/$B/base
cp -f "$LIB" ~/$B/; cp -f "$BIN" ~/$B/gin_ts1
cp -f "$BLIB" ~/$B/base/; cp -f "$BBIN" ~/$B/base/gin_ts1
for d in ~/$B ~/$B/base; do (cd $d && ln -sf libnccl.so.2.32.3 libnccl.so.2 && ln -sf libnccl.so.2 libnccl.so); done
ssh -n "$SUNNY_SSH" "mkdir -p ~/$B/base"
scp -q "$LIB" "$SUNNY_SSH:$B/"; scp -q "$BIN" "$SUNNY_SSH:$B/gin_ts1"
scp -q "$BLIB" "$SUNNY_SSH:$B/base/"; scp -q "$BBIN" "$SUNNY_SSH:$B/base/gin_ts1"
ssh -n "$SUNNY_SSH" "for d in ~/$B ~/$B/base; do (cd \$d && ln -sf libnccl.so.2.32.3 libnccl.so.2 && ln -sf libnccl.so.2 libnccl.so); done"
L=$(cd ~/$B && md5sum libnccl.so.2.32.3 gin_ts1 base/libnccl.so.2.32.3 base/gin_ts1)
S=$(ssh -n "$SUNNY_SSH" "cd ~/$B && md5sum libnccl.so.2.32.3 gin_ts1 base/libnccl.so.2.32.3 base/gin_ts1")
echo "rain:"; echo "$L"; echo "sunny:"; echo "$S"
[ "$L" = "$S" ] || { echo "md5 mismatch" >&2; exit 1; }
(cd ~/$B && LD_LIBRARY_PATH=$HOME/$B ldd ./gin_ts1 | grep nccl)
(cd ~/$B/base && LD_LIBRARY_PATH=$HOME/$B/base ldd ./gin_ts1 | grep nccl)
ssh -n "$SUNNY_SSH" "cd ~/$B && LD_LIBRARY_PATH=\$HOME/$B ldd ./gin_ts1 | grep nccl"
# cost-attribution variants (driver only; the same libnccl as the S1 bundle)
for v in ${VARS:-c1gpufence c2nogate c3nopoll}; do
  VB=$SCR/agent_ts1/var/$v/gin_ts1
  [ -f "$VB" ] || continue
  mkdir -p ~/$B/var_$v; cp -f "$LIB" ~/$B/var_$v/; cp -f "$VB" ~/$B/var_$v/gin_ts1
  (cd ~/$B/var_$v && ln -sf libnccl.so.2.32.3 libnccl.so.2 && ln -sf libnccl.so.2 libnccl.so)
  ssh -n "$SUNNY_SSH" "mkdir -p ~/$B/var_$v"
  scp -q "$LIB" "$SUNNY_SSH:$B/var_$v/"; scp -q "$VB" "$SUNNY_SSH:$B/var_$v/gin_ts1"
  ssh -n "$SUNNY_SSH" "cd ~/$B/var_$v && ln -sf libnccl.so.2.32.3 libnccl.so.2 && ln -sf libnccl.so.2 libnccl.so"
  echo "var_$v: rain $(md5sum < ~/$B/var_$v/gin_ts1 | cut -c1-12) sunny $(ssh -n "$SUNNY_SSH" "md5sum < ~/$B/var_$v/gin_ts1" | cut -c1-12)"
done
