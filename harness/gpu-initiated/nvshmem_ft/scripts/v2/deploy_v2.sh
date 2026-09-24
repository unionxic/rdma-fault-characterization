#!/usr/bin/env bash
# deploy_v2.sh - copy the v2 build (libs + driver) to ~/gi-bundle/nvshmem_ft2/{lib,bin} on rain and
# sunny and check md5s. Touches nothing else (~/gi-bundle/nvshmem_ft is the v1 bundle of another run).
set -eu
SCRATCH=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
INST=$SCRATCH/agent_ftv2/install
DRV=$SCRATCH/agent_ftv2/nvft2_drv
B=$HOME/gi-bundle/nvshmem_ft2
mkdir -p $B/lib $B/bin
cp -a $INST/lib/*.so* $B/lib/
cp $DRV $B/bin/nvft2_drv
ssh -o ConnectTimeout=8 sunny "mkdir -p ~/gi-bundle/nvshmem_ft2/lib ~/gi-bundle/nvshmem_ft2/bin"
rsync -a $B/lib/ sunny:gi-bundle/nvshmem_ft2/lib/
rsync -a $B/bin/nvft2_drv sunny:gi-bundle/nvshmem_ft2/bin/
L=$(cd $B && md5sum lib/libnvshmem_host.so.3.9.0 lib/nvshmem_transport_ibgda.so.7.0.0 bin/nvft2_drv)
R=$(ssh sunny "cd ~/gi-bundle/nvshmem_ft2 && md5sum lib/libnvshmem_host.so.3.9.0 lib/nvshmem_transport_ibgda.so.7.0.0 bin/nvft2_drv")
echo "$L"
[ "$L" = "$R" ] && echo "md5 match on sunny" || { echo "MD5 MISMATCH"; echo "$R"; exit 1; }
