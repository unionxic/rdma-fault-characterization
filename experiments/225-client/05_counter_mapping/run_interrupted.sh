#!/bin/bash
# run_interrupted.sh - Interrupted (mid-transfer) RDMA WRITE test
#
# Verifies that a partial WRITE caused by a mid-transfer responder QP->ERR
# (timeout / peer-death path) breaks on PMTU(1024)-packet boundaries, and that
# the requester can reconstruct the bytes that landed via sq_psn_delta * PMTU.
#
# Run from client (225). Server (224) reached over SSH.
#
# Usage: ./run_interrupted.sh [num_trials] [settle_ms]
#   num_trials : number of trials          (default 100)
#   settle_ms  : delay between post_send and local QP->ERR, ms (default 80)

set -e

REMOTE="gustlr@SERVER_224_ADDR"
REMOTE_DIR="/home/gustlr/Desktop/gpu_fault_recovery/05_counter_mapping"
NUM_TRIALS=${1:-100}
SETTLE_MS=${2:-80}

echo "=== Interrupted WRITE (timeout/peer-death) test ==="
echo "Trials      : $NUM_TRIALS"
echo "Settle (ms) : $SETTLE_MS"
echo "WRITE       : 4MB single WRITE = 4096 PMTU(1024) packets, in-bounds"
echo ""

# Kill any stale server, then rebuild both sides.
ssh "$REMOTE" "pkill -f './server'" 2>/dev/null || true
sleep 1

echo "[build] Compiling on 224 (server)..."
ssh "$REMOTE" "cd $REMOTE_DIR && make clean && make"
echo "[build] Compiling locally (client)..."
make clean && make

echo "[orchestrator] Starting server on 224..."
ssh -f "$REMOTE" "cd $REMOTE_DIR && nohup ./server > /tmp/server_interrupted.log 2>&1 < /dev/null & exit"
sleep 1

mkdir -p results/raw

echo "[run] Launching client..."
./verify_interrupted_write "$NUM_TRIALS" "$SETTLE_MS"

echo ""
echo "CSV       : results/raw/interrupted_write_verify.csv"
echo "Server log: ssh $REMOTE 'cat /tmp/server_interrupted.log'"
