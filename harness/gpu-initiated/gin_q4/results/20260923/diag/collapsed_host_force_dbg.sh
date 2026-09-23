#!/usr/bin/env bash
# one-off: backtrace of the forced collapsed_host failure on rank 0 (rank 1 = stock ring)
S=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad/gi/gin_q4
B=/home/unionxic/gi-bundle/gin_q4
PORT=$(( 45000 + ($$ + RANDOM) % 4000 ))
ENVS="NCCL_DEBUG=WARN NCCL_SOCKET_IFNAME=eno1 NCCL_GIN_TYPE=3 NCCL_IB_TIMEOUT=14 NCCL_GIN_ENABLE=1 GIN_ABORT_WATCHDOG_S=10 LD_LIBRARY_PATH=$B"
ssh -n unionxic@192.0.2.194 "cd $B && $ENVS NCCL_IB_HCA=mlx5_0 NCCL_IB_GID_INDEX=3 exec timeout -s KILL 60 ./gin_q4 1 192.0.2.193 $PORT 5 262144 timeout none 5 30 /tmp/gin_q4_r1.kv 15 > /tmp/gin_q4_r1.log 2>&1" &
SP=$!
env $ENVS NCCL_IB_HCA=mlx5_1 NCCL_IB_GID_INDEX=4 NCCL_GIN_GDAKI_CQ_TYPE=collapsed_host_force DOCA_GPUNETIO_LOG=6 \
  timeout -s KILL 90 gdb -batch -ex run -ex bt -ex quit --args $B/gin_q4 0 192.0.2.193 $PORT 5 262144 timeout none 5 30 $S/work/host_r0.kv 15 > $S/dbg_host_r0_log.txt 2>&1
wait $SP
ssh -n unionxic@192.0.2.194 "pgrep -x gin_q4 | xargs -r kill -9; cat /tmp/gin_q4_r1.log | tail -3; rm -f /tmp/gin_q4_r1.kv /tmp/gin_q4_r1.log"
pgrep -x gin_q4 | xargs -r kill -9
pgrep -x gdb -u unionxic >/dev/null && echo "gdb still running?"
