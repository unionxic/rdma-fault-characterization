#!/bin/bash
# run_partial.sh — Verify partial write behavior at MR boundary
# Run from client (225). Server (224) must be accessible via SSH.
#
# Usage: ./run_partial.sh [num_trials]

set -e

REMOTE="gustlr@SERVER_224_ADDR"
REMOTE_DIR="/home/gustlr/Desktop/gpu_fault_recovery/05_counter_mapping"
NUM_TRIALS=${1:-10}

echo "=== Partial Write Boundary Test ==="
echo "Tests: single_pkt_cross, multi_pkt_cross, barely_1B_inside"
echo "Trials per test: $NUM_TRIALS"
echo ""

ssh "$REMOTE" "pkill -f './server'" 2>/dev/null || true
sleep 1

echo "[build] Compiling on 224..."
ssh "$REMOTE" "cd $REMOTE_DIR && make clean && make"
echo "[build] Compiling locally..."
make clean && make

echo "[orchestrator] Starting server on 224..."
ssh -f "$REMOTE" "cd $REMOTE_DIR && nohup ./server > /tmp/server_partial.log 2>&1 < /dev/null & exit"
sleep 1

mkdir -p results/raw

./verify_partial_write "$NUM_TRIALS"

echo ""
echo "Server log: ssh $REMOTE 'cat /tmp/server_partial.log'"
