#!/usr/bin/env bash
# deploy_t1.sh - copy the T1 build (libs + nvt1_drv) to ~/gi-bundle/nvshmem_t1/{lib,bin}, and the v2.2
# libraries (read from ~/gi-bundle/nvshmem_ft2/lib, not modified) with nvt1v22_drv to
# ~/gi-bundle/nvshmem_t1/v22ref/{lib,bin}, on rain and sunny; md5 checked on both nodes.
set -eu
SCRATCH=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
B=$HOME/gi-bundle/nvshmem_t1
mkdir -p $B/lib $B/bin $B/v22ref/lib $B/v22ref/bin
cp -a $SCRATCH/agent_nvt1/install/lib/*.so* $B/lib/
cp $SCRATCH/agent_nvt1/nvt1_drv $B/bin/nvt1_drv
if [ -f $SCRATCH/agent_nvt1/nvt1v22_drv ]; then
  cp -a $HOME/gi-bundle/nvshmem_ft2/lib/*.so* $B/v22ref/lib/
  cp $SCRATCH/agent_nvt1/nvt1v22_drv $B/v22ref/bin/nvt1v22_drv
fi
ssh -o ConnectTimeout=8 sunny "mkdir -p ~/gi-bundle/nvshmem_t1/lib ~/gi-bundle/nvshmem_t1/bin ~/gi-bundle/nvshmem_t1/v22ref/lib ~/gi-bundle/nvshmem_t1/v22ref/bin"
rsync -a $B/ sunny:gi-bundle/nvshmem_t1/
F="lib/libnvshmem_host.so.3.9.0 lib/nvshmem_transport_ibgda.so.7.0.0 bin/nvt1_drv"
[ -f $B/v22ref/bin/nvt1v22_drv ] && F="$F v22ref/lib/libnvshmem_host.so.3.9.0 v22ref/lib/nvshmem_transport_ibgda.so.7.0.0 v22ref/bin/nvt1v22_drv"
L=$(cd $B && md5sum $F)
R=$(ssh sunny "cd ~/gi-bundle/nvshmem_t1 && md5sum $F")
echo "$L"
[ "$L" = "$R" ] && echo "md5 match on sunny" || { echo "MD5 MISMATCH"; echo "$R"; exit 1; }
