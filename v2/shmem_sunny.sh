#!/bin/bash
# NVSHMEM runs on sunny only (rain's GPU BAR1 is 256 MiB): 2 PEs on one GPU, P2P off so they talk through the NIC.
# usage: shmem_sunny.sh <perftest name> [extra mpirun -x args...]
T=$1; shift; R='$HOME/rdma-recovery'; OUT=$HOME/rdma-recovery/runs/shmem-$(date +%Y%m%d-%H%M%S); mkdir -p $OUT
ssh -o BatchMode=yes sunny "$R/env.sh mpirun --timeout \${TMO:-90} --mca pml ob1 --mca btl self,vader -np 2 \
  -x NVSHMEM_IB_ENABLE_IBGDA=1 -x NVSHMEM_DISABLE_P2P=1 -x NVSHMEM_BOOTSTRAP=MPI -x NVSHMEM_DEBUG=1 $* \
  $R/env.sh $R/nvshmem/build/perftest/device/pt-to-pt/$T" > $OUT/$T.log 2>&1
echo "$T rc=$? log=$OUT/$T.log"
