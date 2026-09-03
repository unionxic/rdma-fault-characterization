#!/bin/bash
# run.sh — RETRY_EXC_ERR recovery benchmark (Path A/B/C)
# Run from 225. Manages server on 224 via SSH.
# Path A (driver reload) requires root — run with sudo or as root.
#
# Usage: ./run.sh [num_trials]

set -e

REMOTE="gustlr@SERVER_224_ADDR"
REMOTE_DIR="/home/gustlr/Desktop/gpu_fault_recovery/06_recovery/RETRY_EXC_ERR"
LOCAL_DIR="$(cd "$(dirname "$0")" && pwd)"
TRIALS=${1:-10}

# --- Check root for Path A ---

# Path A uses "sudo modprobe" inside client binary.
# Cache sudo credentials upfront so it doesn't prompt mid-benchmark.
echo "[setup] Caching sudo credentials for Path A (driver reload)..."
sudo -v

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
    ssh -f "$REMOTE" "cd $REMOTE_DIR && nohup ./server > /tmp/retry_exc_server.log 2>&1 < /dev/null & exit"
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
    echo "Check: ssh $REMOTE 'cat /tmp/retry_exc_server.log'"
    exit 1
fi

echo "[client] Running benchmark (trials=$TRIALS, ~$(( TRIALS * 3 * 4 ))s estimated)..."
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
    grep ',C,' "$OUTFILE" | awk -F, '{sum+=$4; n++} END {printf "  recovery: avg %.0f us (%d trials)\n", sum/n, n}'
    echo ""
    echo "--- Path B (full rebuild) ---"
    grep ',B,' "$OUTFILE" | awk -F, '{sum+=$4; n++} END {printf "  recovery: avg %.0f us (%d trials)\n", sum/n, n}'
    echo ""
    echo "--- Path A (driver reload) ---"
    grep ',A,' "$OUTFILE" | awk -F, '{sum+=$4; n++} END {printf "  recovery: avg %.0f us (%d trials)\n", sum/n, n}'
    echo ""
    echo "--- Detection latency ---"
    grep ',C,' "$OUTFILE" | awk -F, '{sum+=$3; n++} END {printf "  avg detect: %.0f us (%.2f s)\n", sum/n, sum/n/1000000}'
else
    echo "ERROR: benchmark failed (exit code $RC)"
    echo "Server log: ssh $REMOTE 'cat /tmp/retry_exc_server.log'"
fi

exit $RC
