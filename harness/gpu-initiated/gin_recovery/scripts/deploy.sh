#!/usr/bin/env bash
# Deploy the recovery build (libnccl.so.2.32.3 + gin_rec) to ~/gi-bundle/gin_recovery/ on rain
# (local) and sunny, and check md5s. No cluster lock needed (file copy on the management net).
set -euo pipefail
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad/gi/gin_recovery
SUNNY_SSH=${SUNNY_SSH:-unionxic@192.0.2.194}
B=gi-bundle/gin_recovery
LIB=$SCR/build/lib/libnccl.so.2.32.3
BIN=$SCR/gin_rec
mkdir -p ~/$B
cp -f "$LIB" "$BIN" ~/$B/
ln -sf libnccl.so.2.32.3 ~/$B/libnccl.so.2; ln -sf libnccl.so.2 ~/$B/libnccl.so
ssh -n "$SUNNY_SSH" "mkdir -p ~/$B"
scp -q "$LIB" "$BIN" "$SUNNY_SSH:$B/"
ssh -n "$SUNNY_SSH" "cd ~/$B && ln -sf libnccl.so.2.32.3 libnccl.so.2 && ln -sf libnccl.so.2 libnccl.so"
L=$(cd ~/$B && md5sum libnccl.so.2.32.3 gin_rec)
S=$(ssh -n "$SUNNY_SSH" "cd ~/$B && md5sum libnccl.so.2.32.3 gin_rec")
echo "rain:  $L"; echo "sunny: $S"
[ "$L" = "$S" ] || { echo "md5 mismatch" >&2; exit 1; }
# the driver must load our libnccl (not the user's pip cu13 NCCL)
(cd ~/$B && LD_LIBRARY_PATH=$HOME/$B ldd ./gin_rec | grep nccl)
ssh -n "$SUNNY_SSH" "cd ~/$B && LD_LIBRARY_PATH=\$HOME/$B ldd ./gin_rec | grep nccl"
