#!/usr/bin/env bash
# run_ring_test.sh <outfile> - ring-walker stress test configurations (rain GPU only; run inside
# ../../common/cluster_run.sh like every GPU run). Args of ring_walk_test: ncqes nwqes total
# waiter_blocks(8 waiters each) max_group seed.
set -u
BIN=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad/agent_ftv2/ring_walk_test
export LD_LIBRARY_PATH=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad/agent_ftv2/install/lib:/usr/local/cuda-12.8/lib64
OUT=$1
{
echo "# md5 $(md5sum < $BIN | cut -c1-12) $(date '+%F %T')"
for cfg in "64 64 2097152 4 4 1" "64 64 2097152 4 4 2" "64 32 2097152 4 4 3" "1024 1024 4194304 4 1 4" \
           "1024 1024 4194304 4 8 5" "16 16 1048576 8 8 6" "128 128 2097152 1 4 7" "128 128 2097152 16 2 8"; do
  timeout -s KILL 60 $BIN $cfg || echo "RINGTEST cfg=\"$cfg\" rc=$?"
done
echo "# precondition violated on purpose (nwqes > ncqes: the emulated NIC may overrun the ring)"
timeout -s KILL 20 $BIN 16 64 1048576 4 8 9 || echo "RINGTEST cfg=\"16 64 1048576 4 8 9\" rc=$? (expected: FAIL or killed)"
} > "$OUT" 2>&1
cat "$OUT"
