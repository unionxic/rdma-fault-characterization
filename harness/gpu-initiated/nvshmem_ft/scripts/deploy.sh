#!/usr/bin/env bash
# deploy.sh - copy the FT build (libs + driver) to ~/gi-bundle/nvshmem_ft on rain and sunny and
# check md5s. Does not touch ~/gi-bundle/nvshmem or ~/gi-bundle/nvshmem_nrc.
set -eu
SCRATCH=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
INST=$SCRATCH/gi/nvshmem_ft/install
DRV=$SCRATCH/gi/nvshmem_ft/nvft_drv
B=$HOME/gi-bundle/nvshmem_ft
mkdir -p $B/lib $B/bin
cp -a $INST/lib/*.so* $B/lib/
cp $DRV $B/bin/nvft_drv
ssh -o ConnectTimeout=8 sunny "mkdir -p ~/gi-bundle/nvshmem_ft/lib ~/gi-bundle/nvshmem_ft/bin"
rsync -a $B/lib/ sunny:gi-bundle/nvshmem_ft/lib/
rsync -a $B/bin/ sunny:gi-bundle/nvshmem_ft/bin/
L=$(cd $B && md5sum lib/libnvshmem_host.so.3.9.0 lib/nvshmem_transport_ibgda.so.7.0.0 bin/nvft_drv)
R=$(ssh sunny "cd ~/gi-bundle/nvshmem_ft && md5sum lib/libnvshmem_host.so.3.9.0 lib/nvshmem_transport_ibgda.so.7.0.0 bin/nvft_drv")
echo "$L"
[ "$L" = "$R" ] && echo "md5 match on sunny" || { echo "MD5 MISMATCH"; echo "$R"; exit 1; }
