#!/bin/bash
# First two-host check: does each path initialise and move data. One run per case, 120 s cap each.
R=$HOME/rdma-recovery; OUT=$R/runs/verify-$(date +%Y%m%d-%H%M%S); mkdir -p $OUT
MPI="$HOME/opt/openmpi-4.1.8/bin/mpirun --prefix $HOME/opt/openmpi-4.1.8 --timeout ${TMO:-120} --mca pml ob1 --mca btl tcp,self --mca btl_tcp_if_exclude lo,docker0,virbr0 -H rain,sunny -np 2"
GIN=$R/nccl/docs/examples/06_device_api/02_alltoall_gin/c/alltoall_gin
run() { n=$1; shift; echo "== $n"; "$@" > $OUT/$n.log 2>&1; echo "$n rc=$?" | tee -a $OUT/summary.txt; }
[ -n "$ONLY_SHMEM" ] || run gin_auto    $MPI -x NCCL_DEBUG=INFO $R/env.sh $GIN
[ -n "$ONLY_SHMEM" ] || run gin_gdaki   $MPI -x NCCL_DEBUG=INFO -x NCCL_GIN_TYPE=3 $R/env.sh $GIN
[ -n "$ONLY_SHMEM" ] || run gin_proxy   $MPI -x NCCL_DEBUG=INFO -x NCCL_GIN_TYPE=2 $R/env.sh $GIN
[ -n "$ONLY_SHMEM" ] || run gin_bf6     $MPI -x NCCL_DEBUG=INFO -x NCCL_GIN_GDAKI_NIC_HANDLER=6 $R/env.sh $GIN
[ -n "$ONLY_SHMEM" ] || run gin_bf6_t3  $MPI -x NCCL_DEBUG=INFO -x NCCL_GIN_TYPE=3 -x NCCL_GIN_GDAKI_NIC_HANDLER=6 $R/env.sh $GIN
run shmem_put_bw $MPI -x NVSHMEM_IB_ENABLE_IBGDA=1 ${XENV} -x NVSHMEM_SYMMETRIC_SIZE=${HEAP:-64M} -x NVSHMEM_BOOTSTRAP=MPI -x NVSHMEM_DEBUG=1 $R/env.sh $R/nvshmem/build/perftest/device/pt-to-pt/shmem_put_bw
echo $OUT
