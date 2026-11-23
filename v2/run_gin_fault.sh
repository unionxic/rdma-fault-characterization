#!/bin/bash
# Runs the #2483 reproduction (rank 0 on rain, rank 1 on sunny, GDAKI forced).
# env: HOSTS=sunny,rain makes sunny the sender; EXTRA="-x NAME=value" adds settings.
# usage: run_gin_fault.sh <label> <reps> <arm>...   arm = control | untimed | timed | host (slower kernel, so the 1 s host query runs)
#        | inject (no bad put; repro/qperr.c moves the QPs of rank QPERR_RANK to ERR, pass -x QPERR_RANK=.. in EXTRA)
#        | stream (as inject, but 30000 small puts with one flush at the end: puts are in flight when the QPs fail)
R=$HOME/rdma-recovery; L=$1; N=$2; shift 2; OUT=$R/runs/ginfault-$L-$(date +%Y%m%d-%H%M%S); mkdir -p $OUT
MPI="$HOME/opt/openmpi-4.1.8/bin/mpirun --prefix $HOME/opt/openmpi-4.1.8 --timeout 90 --mca pml ob1 --mca btl tcp,self --mca btl_tcp_if_exclude lo,docker0,virbr0 -H ${HOSTS:-rain,sunny} -np 2 -x NCCL_GIN_TYPE=3 -x NCCL_DEBUG=WARN $EXTRA"
for i in $(seq $N); do for a in "$@"; do
  case $a in control) E="-x BAD=-1";; untimed) E="-x BAD=10";; timed) E="-x BAD=10 -x TIMED=1 -x TMO_CYCLES=200000000";; host) E="-x BAD=10 -x TIMED=1 -x TMO_CYCLES=200000000 -x DELAY_CYCLES=60000000";;
    inject) E="-x BAD=-1 -x TIMED=1 -x TMO_CYCLES=200000000 -x DELAY_CYCLES=60000000 -x LD_PRELOAD=$R/repro/libqperr.so";;
    stream) E="-x BAD=-1 -x TIMED=1 -x TMO_CYCLES=20000000000 -x DELAY_CYCLES=${GAP:-20000} -x N=30000 -x CHUNK=1024 -x FLUSH_EVERY=0 -x LINGER_MS=2500 -x LD_PRELOAD=$R/repro/libqperr.so";; esac
  $MPI $E $R/env.sh $R/repro/gin_fault > $OUT/$a-$i.log 2>&1; echo "$a-$i rc=$?"
done; done
grep -hoE "(SUMMARY|RECV|STALL|QPERR).*" $OUT/*.log | sed -E "s/ elapsed=.*//; s/async_error_samples=[1-9][0-9]*/async_error_samples=N/" | sort | uniq -c
grep -ho "syndrome=[^ ]* vendor_err=[^ ]* .*wqe_counter=[0-9]*" $OUT/*.log | sed "s/hw_err.*hw_type=[^ ]* //" | sort | uniq -c
echo $OUT
