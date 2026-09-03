#!/bin/bash
# run_verify.sh — Verify server QP state after NAK errors
# Run from client (225). Server (224) must be accessible via SSH.
#
# Tests IBA spec claim: Error NAK → responder QP transitions to ERR
# vs actual ConnectX-5 behavior
#
# Usage: ./run_verify.sh [num_trials]

set -e

REMOTE="gustlr@SERVER_224_ADDR"
REMOTE_DIR="/home/gustlr/Desktop/gpu_fault_recovery/05_counter_mapping"
NUM_TRIALS=${1:-10}

echo "=== Server QP State Verification ==="
echo "Scenarios: REM_INV_REQ(inv_req) REM_ACCESS_RKEY(rkey) RNR_RETRY_EXC(RNR) REM_ACCESS_ADDR(addr) RETRY_EXC_QP_ERR(control)"
echo "Trials per scenario: $NUM_TRIALS"
echo ""

# Stop any existing server
ssh "$REMOTE" "pkill -f './server'" 2>/dev/null || true
sleep 1

# Build on both sides
echo "[build] Compiling on 224..."
ssh "$REMOTE" "cd $REMOTE_DIR && make clean && make"
echo "[build] Compiling locally..."
make clean && make

# Start server
echo "[orchestrator] Starting server on 224..."
ssh -f "$REMOTE" "cd $REMOTE_DIR && nohup ./server > /tmp/server_verify.log 2>&1 < /dev/null & exit"
sleep 1

# Ensure results directory exists
mkdir -p results/raw

# Run verification
./verify_qp_state "$NUM_TRIALS"

echo ""
echo "Server log: ssh $REMOTE 'cat /tmp/server_verify.log'"
