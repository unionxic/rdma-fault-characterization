#!/bin/bash
# run_multi_experiment.sh — Run essential multi-condition experiments
# Covers 3 conditions × 4 error classes (6 experiments, 3 trials each)
#
# Run from 225 (client). Manages multi_server on 224 via SSH.
#
# Usage: ./run_multi_experiment.sh

set -e

REMOTE="gustlr@SERVER_224_ADDR"
REMOTE_DIR="/home/gustlr/Desktop/gpu_fault_recovery/05_counter_mapping"
LOCAL_DIR="$(cd "$(dirname "$0")" && pwd)"
CLIENT="$LOCAL_DIR/multi_client"
TRIALS=3

if [ ! -x "$CLIENT" ]; then
    echo "ERROR: multi_client not found. Run 'make multi_client' first."
    exit 1
fi

# --- Server management (224) ---

start_server() {
    echo "[orchestrator] Starting multi_server on 224..."
    ssh -f "$REMOTE" "cd $REMOTE_DIR && nohup ./multi_server > /tmp/multi_server.log 2>&1 < /dev/null & exit"
    sleep 2
}

stop_server() {
    ssh "$REMOTE" "pkill -f './multi_server'" 2>/dev/null || true
    sleep 1
}

check_server() {
    ssh "$REMOTE" "pgrep -f './multi_server'" > /dev/null 2>&1
}

# --- Cleanup on exit ---
trap 'set +e; stop_server' EXIT

# --- Experiment list ---
# Format: "CONDITION SCENARIO_ID"
declare -a EXPERIMENTS=(
    "A 1"    # A×LOC_PROT_LEN: local error + multi-WR (flush CQE?)
    "A 8"    # A×RETRY_EXC_QP_ERR: timeout + multi-WR
    "B 1"    # B×LOC_PROT_LEN: local error + 256KB multi-packet
    "B 6"    # B×REM_ACCESS_RKEY: remote access + multi-packet
    "C 6"    # C×REM_ACCESS_RKEY: remote access + multi-QP isolation
    "C 8"    # C×RETRY_EXC_QP_ERR: timeout + multi-QP isolation
)

TOTAL=${#EXPERIMENTS[@]}
PASS=0
FAIL=0

echo "============================================"
echo " Multi-condition experiment batch"
echo " ${TOTAL} experiments x ${TRIALS} trials each"
echo " Server: 224 ($REMOTE)"
echo " Client: 225 (local)"
echo "============================================"
echo ""

for i in "${!EXPERIMENTS[@]}"; do
    read -r COND SC <<< "${EXPERIMENTS[$i]}"
    IDX=$((i + 1))

    echo "[$IDX/$TOTAL] Condition $COND, Scenario $SC"

    # Restart server fresh for each experiment
    stop_server
    start_server

    if ! check_server; then
        echo "  ERROR: multi_server failed to start on 224"
        echo "  Check: ssh $REMOTE 'cat /tmp/multi_server.log'"
        FAIL=$((FAIL + 1))
        continue
    fi

    if $CLIENT "$COND" "$SC" "$TRIALS"; then
        echo "  -> OK"
        PASS=$((PASS + 1))
    else
        echo "  -> FAILED (exit code $?)"
        FAIL=$((FAIL + 1))
    fi

    echo ""
done

stop_server

echo "============================================"
echo " DONE: $PASS passed, $FAIL failed (out of $TOTAL)"
echo "============================================"
echo ""
echo "Results:"
ls -lt "$LOCAL_DIR/results/multi/"*.csv 2>/dev/null | head -20
