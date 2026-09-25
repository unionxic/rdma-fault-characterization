#!/usr/bin/env bash
# run_ring_test_v21.sh <outfile> - the 8 stress configurations and the sensitivity check on the v2.1
# header (ring_walk_test3; the walker now records and fails on an invariant violation instead of
# consuming silently, so any violation shows up as bad_rc).
set -u
BIN=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad/agent_ftv2/ring_walk_test3
export LD_LIBRARY_PATH=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad/agent_ftv2/install/lib:/usr/local/cuda-12.8/lib64
OUT=$1
{
echo "# md5 $(md5sum < $BIN | cut -c1-12) $(date '+%F %T')"
for cfg in "64 64 2097152 4 4 1" "64 64 2097152 4 4 2" "64 32 2097152 4 4 3" "1024 1024 4194304 4 1 4" \
           "1024 1024 4194304 4 8 5" "16 16 1048576 8 8 6" "128 128 2097152 1 4 7" "128 128 2097152 16 2 8"; do
  timeout -s KILL 60 $BIN $cfg || echo "RINGTEST cfg=\"$cfg\" rc=$?"
done
for cfg in "16 16 1048576 4 1 20 50" "64 64 1048576 4 1 21 50" "16 64 1048576 4 1 22 50" "64 256 1048576 4 1 23 50"; do
  timeout -s KILL 15 $BIN $cfg; rc=$?
  echo "RINGTEST_NEG cfg=\"$cfg\" rc=$rc (0 PASS; 1 FAIL reported; 137 stalled and killed)"
done
} > "$OUT" 2>&1
cat "$OUT"
