#!/usr/bin/env bash
# run_ring_test_neg.sh <outfile> - sensitivity check of ring_walk_test. The waiters start 50 ms late,
# so the emulated NIC runs ahead up to its flow-control limit (nwqes WQEs, one CQE each). With
# nwqes <= ncqes (the ring's precondition) nothing is overwritten and the test must PASS; with
# nwqes > ncqes the NIC overwrites unconsumed CQEs and the test must fail (missed completions ->
# waiters and NIC stall -> killed by the bound). The first run (2026-09-25 07:18) had no delay; its
# waiters kept up with the NIC, no overrun happened and the "negative" runs passed.
set -u
BIN=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad/agent_ftv2/ring_walk_test2
export LD_LIBRARY_PATH=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad/agent_ftv2/install/lib:/usr/local/cuda-12.8/lib64
OUT=$1
{
echo "# md5 $(md5sum < $BIN | cut -c1-12) $(date '+%F %T')"
for cfg in "16 16 1048576 4 1 20 50" "64 64 1048576 4 1 21 50" "16 64 1048576 4 1 22 50" "64 256 1048576 4 1 23 50"; do
  timeout -s KILL 15 $BIN $cfg; rc=$?
  echo "RINGTEST_NEG cfg=\"$cfg\" rc=$rc (0 PASS; 1 FAIL reported; 137 stalled and killed)"
done
} > "$OUT" 2>&1
cat "$OUT"
