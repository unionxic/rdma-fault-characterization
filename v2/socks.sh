#!/bin/bash
# lists the sockets of the two PEs while they hold; $1 = btl list
R=$HOME/rdma-recovery
$R/env.sh mpirun --timeout 60 --mca pml ob1 --mca btl $1 -np 2 -x NVSHMEM_IB_ENABLE_IBGDA=1 -x NVSHMEM_DISABLE_P2P=1 -x NVSHMEM_BOOTSTRAP=MPI -x NVSHMEM_SYMMETRIC_SIZE=1G -x BAD=-1 -x HOLD_S=10 $R/env.sh $R/repro/shmem_fault > /dev/null 2>&1 &
sleep 7
echo "== btl $1"
for pid in $(pgrep -x shmem_fault); do
  echo "pid $pid sockets_total=$(ls -l /proc/$pid/fd | grep -c socket) tcp=$(ss -tnpH | grep -c "pid=$pid,") unix=$(ss -xnpH | grep -c "pid=$pid,")"
  ss -tnpH | grep "pid=$pid," | awk '{print "  tcp", $1, $4, "->", $5}'
done
wait
