#!/bin/bash
# Runs the #120 reproduction on sunny (2 PEs, one GPU, through the NIC). usage: shmem_fault.sh <label> <reps> [-x NAME=value ...]
# The test asks nvshmemx_get_op_error() itself, so the library default (abort on the first failure) is turned off; ABORT=1 keeps it.
L=$1; N=$2; shift 2; R='$HOME/rdma-recovery'
ssh -o BatchMode=yes sunny "OUT=$R/runs/shmemfault-$L-\$(date +%Y%m%d-%H%M%S); mkdir -p \$OUT; for i in \$(seq $N); do
  $R/env.sh mpirun --timeout 60 --mca pml ob1 --mca btl self,vader -np 2 -x NVSHMEM_IB_ENABLE_IBGDA=1 -x NVSHMEM_DISABLE_P2P=1 \
    -x NVSHMEM_BOOTSTRAP=MPI -x NVSHMEM_SYMMETRIC_SIZE=1G -x NVSHMEM_IBGDA_ABORT_ON_OP_ERROR=${ABORT:-0} $* $R/env.sh $R/repro/shmem_fault > \$OUT/\$i.log 2>&1; echo run-\$i rc=\$?; done
  grep -hoE '(SUMMARY|QUERY|RECV|STALL|WARN).*' \$OUT/*.log | sort | uniq -c; echo \$OUT"
