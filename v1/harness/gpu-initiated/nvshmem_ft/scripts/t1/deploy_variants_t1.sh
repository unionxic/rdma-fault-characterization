#!/usr/bin/env bash
# deploy_variants_t1.sh - bundles for the flag-off latency bisect, under ~/gi-bundle/nvshmem_t1/<name>/
# on both nodes (the final build in lib/ and bin/ is left as it is):
#   varA varP varW  device bisect builds (build_variant.sh; libs + their own nvt1_drv)
#   mixA            T1 driver (T1 device code) with the v2.2 host libraries
#   mixB            v2.2 driver (v2.2 device code) with the T1 host libraries
set -eu
SCRATCH=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
B=$HOME/gi-bundle/nvshmem_t1
for v in varA varP varW; do
  mkdir -p $B/$v/lib $B/$v/bin
  cp -a $SCRATCH/agent_nvt1/${v}_install/lib/*.so* $B/$v/lib/
  cp $SCRATCH/agent_nvt1/nvt1_drv_$v $B/$v/bin/nvt1_drv
done
mkdir -p $B/mixA/lib $B/mixA/bin $B/mixB/lib $B/mixB/bin
cp -a $B/v22ref/lib/*.so* $B/mixA/lib/; cp $B/bin/nvt1_drv $B/mixA/bin/nvt1_drv
cp -a $B/lib/*.so* $B/mixB/lib/; cp $B/v22ref/bin/nvt1v22_drv $B/mixB/bin/nvt1v22_drv
rsync -a $B/ sunny:gi-bundle/nvshmem_t1/
F=""
for v in varA varP varW mixA; do F="$F $v/lib/libnvshmem_host.so.3.9.0 $v/lib/nvshmem_transport_ibgda.so.7.0.0 $v/bin/nvt1_drv"; done
F="$F mixB/lib/libnvshmem_host.so.3.9.0 mixB/lib/nvshmem_transport_ibgda.so.7.0.0 mixB/bin/nvt1v22_drv"
L=$(cd $B && md5sum $F); R=$(ssh sunny "cd ~/gi-bundle/nvshmem_t1 && md5sum $F")
echo "$L" | cut -c1-8,33-
[ "$L" = "$R" ] && echo "md5 match on sunny" || { echo "MD5 MISMATCH"; exit 1; }
