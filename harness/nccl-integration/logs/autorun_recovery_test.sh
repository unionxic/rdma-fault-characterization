#!/bin/bash
# Waits for rain GPU to free, then runs: (1) flag-off baseline, (2) inject=recoverable,
# (3) proc-kill control. Saves logs under $SCR. Fires when free mem >= 3000 MiB.
SCR="$1"; RL=$HOME/experiments/nccl-fault/nccl/build/lib
CUDA=/usr/local/cuda-12.8/lib64; DRV=$HOME/experiments/nccl-fault/test/nccl_ar2
log(){ echo "[$(date +%H:%M:%S)] $*" >> $SCR/autorun.log; }
: > $SCR/autorun.log
# wait up to 45 min for >=3000MiB free on rain
for i in $(seq 1 135); do
  FREE=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | head -1)
  if [ "$FREE" -ge 3000 ] 2>/dev/null; then log "GPU free=${FREE}MiB -> running tests"; break; fi
  sleep 20
done
FREE=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | head -1)
if [ "$FREE" -lt 3000 ] 2>/dev/null; then log "TIMEOUT waiting for GPU (free=${FREE}MiB); aborting"; exit 3; fi
run2() { # $1=tag $2=extra_env_rank0 $3=port $4=killpeer(0/1)
  local tag=$1 extra=$2 port=$3 killp=$4
  pkill -9 -x nccl_ar2 2>/dev/null; ssh unionxic@30.0.0.4 'pkill -9 -x nccl_ar2 2>/dev/null'; sleep 2
  LD_LIBRARY_PATH=$RL:$CUDA env NCCL_DEBUG=INFO NCCL_DEBUG_SUBSYS=NET NCCL_DEBUG_FILE=$SCR/${tag}_ncdbg_r0.%h.%p \
    NCCL_MAX_NCHANNELS=2 NCCL_IB_HCA=mlx5_1 NCCL_IB_GID_INDEX=3 NCCL_SOCKET_IFNAME=ens4f1np1 $extra \
    timeout 80 $DRV 0 30.0.0.3 $port 60 1048576 150 > $SCR/${tag}_r0.log 2>&1 &
  local R0=$!
  sleep 3
  if [ "$killp" = "1" ]; then
    ssh unionxic@30.0.0.4 "cd ~/experiments/nccl-fault/bundle && LD_LIBRARY_PATH=\$PWD env NCCL_DEBUG=WARN \
      NCCL_MAX_NCHANNELS=2 NCCL_IB_HCA=mlx5_0 NCCL_IB_GID_INDEX=3 NCCL_SOCKET_IFNAME=enp23s0f0np0 NCCL_RDMA_FAULT_RECOVERY=1 \
      timeout 80 ./nccl_ar2 1 30.0.0.3 $port 60 1048576 150 > /tmp/${tag}_r1.log 2>&1 & P=\$!; sleep 8; kill -9 \$(pgrep -x nccl_ar2); echo killed" &
  else
    ssh unionxic@30.0.0.4 "cd ~/experiments/nccl-fault/bundle && LD_LIBRARY_PATH=\$PWD env NCCL_DEBUG=INFO NCCL_DEBUG_SUBSYS=NET \
      NCCL_DEBUG_FILE=/tmp/${tag}_ncdbg_r1.%h.%p NCCL_MAX_NCHANNELS=2 NCCL_IB_HCA=mlx5_0 NCCL_IB_GID_INDEX=3 \
      NCCL_SOCKET_IFNAME=enp23s0f0np0 NCCL_RDMA_FAULT_RECOVERY=1 \
      timeout 80 ./nccl_ar2 1 30.0.0.3 $port 60 1048576 150 > /tmp/${tag}_r1.log 2>&1" &
  fi
  wait $R0; log "$tag rank0 exit=$? iters_ok=$(grep -c 'iter .* ok' $SCR/${tag}_r0.log) done=$(grep -c '\[rank0\] done' $SCR/${tag}_r0.log)"
  sleep 2; pkill -9 -x nccl_ar2 2>/dev/null; ssh unionxic@30.0.0.4 'pkill -9 -x nccl_ar2 2>/dev/null'; sleep 2
  scp -q unionxic@30.0.0.4:/tmp/${tag}_r1.log $SCR/${tag}_r1.log 2>/dev/null
  scp -q "unionxic@30.0.0.4:/tmp/${tag}_ncdbg_r1.*" $SCR/ 2>/dev/null
}
run2 base   "" 43100 0            # flag-off baseline
run2 inject "NCCL_RDMA_FAULT_RECOVERY=1 NCCL_RDMA_FAULT_INJECT=50" 43110 0   # recoverable
run2 kill   "NCCL_RDMA_FAULT_RECOVERY=1" 43120 1                             # proc-kill control
log "ALL DONE"
