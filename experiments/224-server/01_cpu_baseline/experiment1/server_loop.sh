#!/usr/bin/env bash
# server_loop.sh - Auto-restart wrapper for scenario B (kill -9)
# Restarts the server whenever it exits (e.g., after _exit(137))
#
# Usage: ./server_loop.sh [server args...]
# Example: ./server_loop.sh -d mlx5_0 -g 3

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER="$SCRIPT_DIR/server"

echo "[LOOP] Server auto-restart wrapper started"
echo "[LOOP] Press Ctrl+C to stop"

trap 'echo "[LOOP] Stopping..."; exit 0' INT TERM

while true; do
    echo "[LOOP] Starting server..."
    "$SERVER" "$@"
    EXIT_CODE=$?
    echo "[LOOP] Server exited with code $EXIT_CODE, restarting in 1 second..."
    sleep 1
done
