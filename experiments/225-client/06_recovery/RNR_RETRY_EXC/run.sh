#!/bin/bash
# run.sh — RNR_RETRY_EXC recovery benchmark
# Run from 225. Manages server on 224 via SSH.
#
# Usage: ./run.sh [num_trials]

set -e

REMOTE="gustlr@SERVER_224_ADDR"
REMOTE_DIR="/home/gustlr/Desktop/gpu_fault_recovery/06_recovery/RNR_RETRY_EXC"
LOCAL_DIR="$(cd "$(dirname "$0")" && pwd)"
TRIALS=${1:-10}

# --- Build ---

echo "[build] Building client on 225..."
make -C "$LOCAL_DIR" clean && make -C "$LOCAL_DIR"

echo "[build] Building server on 224..."
ssh "$REMOTE" "cd $REMOTE_DIR && make clean && make"

# --- Server management ---

stop_server() {
    ssh "$REMOTE" "pkill -f './server'" 2>/dev/null || true
    sleep 1
}

start_server() {
    echo "[server] Starting on 224..."
    ssh -f "$REMOTE" "cd $REMOTE_DIR && nohup ./server > /tmp/rnr_recovery_server.log 2>&1 < /dev/null & exit"
    sleep 2
}

check_server() {
    ssh "$REMOTE" "pgrep -f './server'" > /dev/null 2>&1
}

# --- Cleanup on exit ---
trap 'set +e; stop_server' EXIT

# --- Run ---

stop_server
start_server

if ! check_server; then
    echo "ERROR: server failed to start on 224"
    echo "Check: ssh $REMOTE 'cat /tmp/rnr_recovery_server.log'"
    exit 1
fi

echo "[client] Running benchmark (trials=$TRIALS)..."
echo ""

mkdir -p "$LOCAL_DIR/results"
OUTFILE="$LOCAL_DIR/results/recovery_$(date +%Y%m%d_%H%M%S).csv"

"$LOCAL_DIR/client" "$TRIALS" > "$OUTFILE"
RC=$?

echo ""
if [ $RC -eq 0 ]; then
    echo "========================================"
    echo " DONE — results saved to:"
    echo " $OUTFILE"
    echo "========================================"
    echo ""
    echo "Summary:"
    echo "--- Path C (QP-only recovery) ---"
    grep ',C,' "$OUTFILE" | awk -F, '{sum+=$5; n++} END {printf "  recovery: avg %.0f us (%d trials)\n", sum/n, n}'
    grep ',C,' "$OUTFILE" | awk -F, '{sum+=$7; n++} END {printf "  total:    avg %.0f us\n", sum/n}'
    echo ""
    echo "--- Path B (full rebuild) ---"
    grep ',B,' "$OUTFILE" | awk -F, '{sum+=$5; n++} END {printf "  recovery: avg %.0f us (%d trials)\n", sum/n, n}'
    grep ',B,' "$OUTFILE" | awk -F, '{sum+=$7; n++} END {printf "  total:    avg %.0f us\n", sum/n}'
else
    echo "ERROR: benchmark failed (exit code $RC)"
    echo "Server log: ssh $REMOTE 'cat /tmp/rnr_recovery_server.log'"
fi

exit $RC
