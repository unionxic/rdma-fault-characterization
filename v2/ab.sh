#!/bin/bash
# Normal-path cost of the changes: runs each benchmark REPS times, alternating the unmodified build (base/) and this folder's build.
# usage: ab.sh shmem <reps> <NVSHMEM perftest name>...   (run on sunny: 2 PEs, one GPU, through the NIC)
#        ab.sh gin <reps>                                (run on rain: NCCL ring_exchange, rank 0 rain, rank 1 sunny, GDAKI forced)
# Compare with ab_report.py <printed folder>.
K=$1; N=$2; shift 2; H=$HOME/rdma-recovery; M=$HOME/opt/openmpi-4.1.8; OUT=$H/runs/ab-$K-$(date +%Y%m%d-%H%M%S); mkdir -p $OUT
[ $K = gin ] && set -- ring_exchange
for i in $(seq $N); do for t in "$@"; do for v in base fix; do
  R=$H; [ $v = base ] && R=$H/base
  if [ $K = gin ]; then A="--mca btl tcp,self --mca btl_tcp_if_exclude lo,docker0,virbr0 -H rain,sunny -x NCCL_GIN_TYPE=3"; B=$R/nccl/docs/examples/09_gin_optimizations/01_ring_exchange/c/$t
  else A="--mca btl self,vader -x NVSHMEM_IB_ENABLE_IBGDA=1 -x NVSHMEM_DISABLE_P2P=1 -x NVSHMEM_BOOTSTRAP=MPI"; B=$R/nvshmem/build/perftest/device/pt-to-pt/$t; fi
  $M/bin/mpirun --prefix $M --timeout 120 --mca pml ob1 $A -np 2 -x RR_ROOT=$R $H/env.sh $B > $OUT/$t-$v-$i.log 2>&1 || echo "$t-$v-$i rc=$?"
done; done; done
echo $OUT
