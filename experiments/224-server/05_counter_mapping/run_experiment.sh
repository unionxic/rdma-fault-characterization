#!/bin/bash
# run_experiment.sh — Orchestrate all 11 fault scenarios
# Run from client (225). Server (224) must be accessible via SSH.
#
# Usage: ./run_experiment.sh [scenario_id] [num_trials]
#   No args: run all scenarios
#   With scenario_id: run only that scenario

set -e

REMOTE="gustlr@SERVER_224_ADDR"
REMOTE_DIR="/home/gustlr/Desktop/gpu_fault_recovery/05_counter_mapping"
LOCAL_DIR="$(cd "$(dirname "$0")" && pwd)"
RDMA_IFACE="enp1s0f0np0"
NUM_TRIALS=${2:-10}

# Scenario names for display
declare -A NAMES=(
    [1]="LOC_PROT_LEN"
    [2]="LOC_PROT_LKEY"
    [3]="LOC_PROT_PERM"
    [4]="WR_FLUSH"
    [5]="REM_INV_REQ"
    [6]="REM_ACCESS_RKEY"
    [7]="RNR_RETRY_EXC"
    [8]="RETRY_EXC_QP_ERR"
    [9]="RETRY_EXC_PROC_KILL"
    [10]="RETRY_EXC_LINK_DOWN"
    [11]="REM_ACCESS_ADDR"
)

start_daemon() {
    echo "[orchestrator] Starting counter_daemon on 224..."
    ssh -f "$REMOTE" "cd $REMOTE_DIR && nohup bash counter_daemon.sh > /tmp/counter_daemon.log 2>&1 < /dev/null & exit"
    sleep 1
}

stop_daemon() {
    echo "[orchestrator] Stopping counter_daemon on 224..."
    ssh "$REMOTE" "pkill -f counter_daemon.sh" 2>/dev/null || true
}

start_server() {
    echo "[orchestrator] Starting server on 224..."
    ssh -f "$REMOTE" "cd $REMOTE_DIR && nohup ./server > /tmp/server.log 2>&1 < /dev/null & exit"
    sleep 1
}

stop_server() {
    ssh "$REMOTE" "pkill -f './server'" 2>/dev/null || true
    sleep 1
}

kill_server() {
    echo "[orchestrator] Killing server process on 224..."
    ssh "$REMOTE" "pkill -9 -f './server'" 2>/dev/null || true
}

link_down() {
    echo "[orchestrator] Bringing down $RDMA_IFACE on 224..."
    ssh "$REMOTE" "sudo ip link set $RDMA_IFACE down"
    # Wait until link is actually down
    for i in $(seq 1 20); do
        state=$(ssh "$REMOTE" "cat /sys/class/net/$RDMA_IFACE/operstate 2>/dev/null")
        [ "$state" = "down" ] && break
        sleep 0.5
    done
    sleep 2
}

link_up() {
    echo "[orchestrator] Bringing up $RDMA_IFACE on 224..."
    ssh "$REMOTE" "sudo ip link set $RDMA_IFACE up"
    echo "[orchestrator] Waiting for link recovery..."
    sleep 15
}

run_standard_scenario() {
    local sc=$1
    echo ""
    echo "=========================================="
    echo "  Running scenario $sc: ${NAMES[$sc]}"
    echo "=========================================="

    stop_server
    start_server
    ./client "$sc" "$NUM_TRIALS"
    stop_server
}

wait_for_signal() {
    local timeout=${1:-300}
    local elapsed=0
    while [ ! -f /tmp/ready_to_inject ] && [ $elapsed -lt $timeout ]; do
        sleep 0.1
        elapsed=$((elapsed + 1))
    done
    rm -f /tmp/ready_to_inject
    [ $elapsed -lt $timeout ]
}

run_f8b() {
    echo ""
    echo "=========================================="
    echo "  Running scenario 9: RETRY_EXC_PROC_KILL"
    echo "=========================================="

    mkdir -p results/raw
    rm -f results/raw/RETRY_EXC_PROC_KILL.csv

    for ((t=0; t<NUM_TRIALS; t++)); do
        echo "--- RETRY_EXC_PROC_KILL trial $t ---"
        rm -f /tmp/ready_to_inject

        stop_server
        start_server

        ./client 9 1 &
        CLIENT_PID=$!

        # Wait until client has posted WR and signals readiness
        if ! wait_for_signal 300; then
            echo "ERROR: client did not signal readiness"
            kill $CLIENT_PID 2>/dev/null || true
            continue
        fi

        kill_server
        touch /tmp/inject_done
        wait $CLIENT_PID 2>/dev/null || true
        rm -f /tmp/inject_done
    done
}

run_f8c() {
    echo ""
    echo "=========================================="
    echo "  Running scenario 10: RETRY_EXC_LINK_DOWN"
    echo "=========================================="

    mkdir -p results/raw
    rm -f results/raw/RETRY_EXC_LINK_DOWN.csv

    for ((t=0; t<NUM_TRIALS; t++)); do
        echo "--- RETRY_EXC_LINK_DOWN trial $t ---"
        rm -f /tmp/ready_to_inject

        link_up 2>/dev/null || true
        sleep 2

        stop_server
        start_server

        ./client 10 1 &
        CLIENT_PID=$!

        if ! wait_for_signal 300; then
            echo "ERROR: client did not signal readiness"
            kill $CLIENT_PID 2>/dev/null || true
            continue
        fi

        link_down
        touch /tmp/inject_done
        wait $CLIENT_PID 2>/dev/null || true
        rm -f /tmp/inject_done

        link_up
        stop_server
    done
}

run_all() {
    # Standard scenarios: IDs 1-8 + 11 (PROC_KILL/LINK_DOWN handled separately below)
    for sc in 1 2 3 4 5 6 7 8 11; do
        run_standard_scenario $sc
    done

    # Special scenarios
    run_f8b
    run_f8c
}

# Start daemon (stays alive across all scenarios)
start_daemon

# Trap to clean up on exit
trap 'set +e; stop_daemon; stop_server; link_up 2>/dev/null' EXIT

if [ -n "$1" ]; then
    sc=$1
    case $sc in
        9)  run_f8b ;;
        10) run_f8c ;;
        *)  run_standard_scenario "$sc" ;;
    esac
else
    run_all
fi

echo ""
echo "All experiments complete. Results in results/raw/"
