#!/usr/bin/env bash
#
# run_experiment.sh - Orchestration script for Experiment 1
#
# RDMA Fault Detection Latency Baseline Measurement
# Part of: GPU-Initiated RDMA Fault Recovery Research
#
# This script runs on the CLIENT machine (Server A).
# It handles:
#   1. Building the binaries
#   2. Capturing the hardware/software environment
#   3. Running each scenario with proper server lifecycle management
#   4. Collecting results and generating summary
#
# For scenario (b) kill: this script SSHes to Server B to restart
# the server process between iterations.
#
# Prerequisites:
#   - SSH key-based auth to Server B (no password prompts)
#   - rdma-core, libibverbs-dev installed on both machines
#   - For scenario (c): root access on Server B
#
# Usage:
#   ./run_experiment.sh [options]
#
# Options are loaded from config.sh (create from config.sh.example)
# or can be overridden via environment variables.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ================================================================
# Configuration (override via config.sh or environment)
# ================================================================

if [ -f config.sh ]; then
    # shellcheck source=config.sh
    source config.sh
fi

# Required
SERVER_IP="${SERVER_IP:?ERROR: Set SERVER_IP in config.sh or environment}"

# Optional with defaults
DEV_NAME="${DEV_NAME:-mlx5_0}"
IB_PORT="${IB_PORT:-1}"
GID_INDEX="${GID_INDEX:-3}"
CTRL_PORT="${CTRL_PORT:-18515}"
ITERATIONS="${ITERATIONS:-100}"
SCENARIOS="${SCENARIOS:-a}"           # Comma-separated: a,b,c
NIC_IFACE="${NIC_IFACE:-enp1s0f0np0}"
SERVER_SSH="${SERVER_SSH:-}"          # SSH target for Server B (e.g., user@10.0.0.4)
SERVER_BIN_DIR="${SERVER_BIN_DIR:-}"  # Path to experiment1/ on Server B
RESULTS_DIR="${RESULTS_DIR:-${SCRIPT_DIR}/results}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
OUTPUT_FILE="${RESULTS_DIR}/detection_latency_${TIMESTAMP}.csv"

# ================================================================
# Utility functions
# ================================================================

log_info()  { echo "[INFO ] $(date '+%H:%M:%S') $*" >&2; }
log_warn()  { echo "[WARN ] $(date '+%H:%M:%S') $*" >&2; }
log_error() { echo "[ERROR] $(date '+%H:%M:%S') $*" >&2; }

check_prereqs() {
    log_info "Checking prerequisites..."

    # Check that binaries exist
    if [ ! -f "$SCRIPT_DIR/client" ] || [ ! -f "$SCRIPT_DIR/server" ]; then
        log_info "Building binaries..."
        make -C "$SCRIPT_DIR" all
    fi

    # Check that the IB device exists
    if ! ibv_devinfo -d "$DEV_NAME" >/dev/null 2>&1; then
        log_error "IB device '$DEV_NAME' not found. Run 'ibv_devinfo' to list devices."
        exit 1
    fi

    # Check SSH access to server (if scenarios b or c are requested)
    if [[ "$SCENARIOS" == *"b"* ]] || [[ "$SCENARIOS" == *"c"* ]]; then
        if [ -z "$SERVER_SSH" ]; then
            log_error "SERVER_SSH is required for scenarios b and c"
            log_error "Set SERVER_SSH=user@server_ip in config.sh"
            exit 1
        fi
        if ! ssh -o BatchMode=yes -o ConnectTimeout=5 "$SERVER_SSH" true 2>/dev/null; then
            log_error "Cannot SSH to $SERVER_SSH (key-based auth required)"
            exit 1
        fi
        if [ -z "$SERVER_BIN_DIR" ]; then
            log_error "SERVER_BIN_DIR is required for scenarios b and c"
            exit 1
        fi
    fi

    log_info "Prerequisites OK"
}

capture_environment() {
    local env_file="${RESULTS_DIR}/environment_${TIMESTAMP}.txt"
    log_info "Capturing environment to $env_file"

    {
        echo "=== Experiment Environment ==="
        echo "Date: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
        echo "Hostname: $(hostname)"
        echo "Kernel: $(uname -r)"
        echo ""

        echo "=== RDMA Devices ==="
        ibv_devinfo 2>/dev/null || echo "(ibv_devinfo not available)"
        echo ""

        echo "=== IB Status ==="
        ibstat 2>/dev/null || echo "(ibstat not available)"
        echo ""

        echo "=== PCI Devices (Mellanox/NVIDIA NICs) ==="
        lspci | grep -i -E '(mellanox|nvidia.*network|connectx)' 2>/dev/null || echo "(none found)"
        echo ""

        echo "=== OFED Version ==="
        ofed_info -s 2>/dev/null || echo "(not OFED installation)"
        echo ""

        echo "=== rdma-core Version ==="
        dpkg -l rdma-core 2>/dev/null | tail -1 || rpm -q rdma-core 2>/dev/null || echo "(unknown)"
        echo ""

        echo "=== CPU ==="
        lscpu | head -20
        echo ""

        echo "=== Network Interface ==="
        ip addr show "$NIC_IFACE" 2>/dev/null || echo "(interface $NIC_IFACE not found)"
        echo ""

        echo "=== GID Table ==="
        for gid_file in /sys/class/infiniband/"$DEV_NAME"/ports/"$IB_PORT"/gids/*; do
            if [ -f "$gid_file" ]; then
                idx=$(basename "$gid_file")
                gid=$(cat "$gid_file")
                if [ "$gid" != "0000:0000:0000:0000:0000:0000:0000:0000" ]; then
                    echo "  GID[$idx]: $gid"
                fi
            fi
        done
        echo ""

        echo "=== Experiment Configuration ==="
        echo "SERVER_IP=$SERVER_IP"
        echo "DEV_NAME=$DEV_NAME"
        echo "IB_PORT=$IB_PORT"
        echo "GID_INDEX=$GID_INDEX"
        echo "CTRL_PORT=$CTRL_PORT"
        echo "ITERATIONS=$ITERATIONS"
        echo "SCENARIOS=$SCENARIOS"
        echo "NIC_IFACE=$NIC_IFACE"

    } > "$env_file" 2>&1

    log_info "Environment captured"
}

# ================================================================
# Server management (on Server B via SSH)
# ================================================================

start_remote_server() {
    if [ -z "$SERVER_SSH" ] || [ -z "$SERVER_BIN_DIR" ]; then
        log_warn "No SSH config for remote server management"
        return 0
    fi

    log_info "Starting server on $SERVER_SSH ..."

    # Kill any existing server process
    ssh "$SERVER_SSH" "pkill -f '${SERVER_BIN_DIR}/server' 2>/dev/null; sleep 0.5; true"

    # Start server in background
    # shellcheck disable=SC2029
    ssh "$SERVER_SSH" "cd '$SERVER_BIN_DIR' && \
        nohup ./server \
            -d '$DEV_NAME' \
            -i '$IB_PORT' \
            -g '$GID_INDEX' \
            -p '$CTRL_PORT' \
            -I '$NIC_IFACE' \
            > /tmp/rdma_fault_server.log 2>&1 &"

    # Wait for server to be ready (listening on port)
    local retries=10
    while [ $retries -gt 0 ]; do
        if ssh "$SERVER_SSH" "ss -tln | grep -q ':${CTRL_PORT} '" 2>/dev/null; then
            log_info "Remote server is listening on port $CTRL_PORT"
            return 0
        fi
        sleep 1
        retries=$((retries - 1))
    done

    log_error "Remote server did not start within 10 seconds"
    ssh "$SERVER_SSH" "cat /tmp/rdma_fault_server.log 2>/dev/null" >&2
    return 1
}

stop_remote_server() {
    if [ -z "$SERVER_SSH" ]; then
        return 0
    fi

    log_info "Stopping remote server..."
    ssh "$SERVER_SSH" "pkill -f '${SERVER_BIN_DIR}/server' 2>/dev/null; true"
}

# ================================================================
# Run scenarios
# ================================================================

run_scenario_a() {
    log_info "=============================================="
    log_info "  Scenario A: QP -> ERR state transition"
    log_info "=============================================="

    ./client \
        -s "$SERVER_IP" \
        -d "$DEV_NAME" \
        -i "$IB_PORT" \
        -g "$GID_INDEX" \
        -p "$CTRL_PORT" \
        -n "$ITERATIONS" \
        -o "$OUTPUT_FILE" \
        -S a
}

run_scenario_b() {
    log_info "=============================================="
    log_info "  Scenario B: Remote process kill"
    log_info "  Running $ITERATIONS iterations (1 per server lifecycle)"
    log_info "=============================================="

    local b_output="${RESULTS_DIR}/detection_latency_b_${TIMESTAMP}.csv"
    echo "scenario,iteration,t_inject_request_ns,t_ack_ns,tcp_rtt_ns,t_error_cqe_ns,detection_latency_ns,error_status,error_vendor_err" > "$b_output"

    for i in $(seq 1 "$ITERATIONS"); do
        log_info "--- Scenario B: iteration $i/$ITERATIONS ---"

        # Start a fresh server (the previous one was killed)
        start_remote_server

        # Run one iteration
        local iter_output="${RESULTS_DIR}/.b_iter_${i}.csv"
        ./client \
            -s "$SERVER_IP" \
            -d "$DEV_NAME" \
            -i "$IB_PORT" \
            -g "$GID_INDEX" \
            -p "$CTRL_PORT" \
            -n 1 \
            -o "$iter_output" \
            -S b || log_warn "Iteration $i failed"

        # Append result (skip header)
        if [ -f "$iter_output" ]; then
            tail -n +2 "$iter_output" >> "$b_output"
            rm -f "$iter_output"
        fi

        # Brief pause for cleanup
        sleep 1
    done

    # Merge into main output
    if [ -f "$b_output" ]; then
        tail -n +2 "$b_output" >> "$OUTPUT_FILE"
    fi
}

run_scenario_c() {
    log_info "=============================================="
    log_info "  Scenario C: Link down"
    log_info "  NOTE: Requires root on Server B"
    log_info "=============================================="

    local c_output="${RESULTS_DIR}/detection_latency_c_${TIMESTAMP}.csv"

    ./client \
        -s "$SERVER_IP" \
        -d "$DEV_NAME" \
        -i "$IB_PORT" \
        -g "$GID_INDEX" \
        -p "$CTRL_PORT" \
        -n "$ITERATIONS" \
        -o "$c_output" \
        -S c

    # Merge into main output
    if [ -f "$c_output" ]; then
        tail -n +2 "$c_output" >> "$OUTPUT_FILE"
        rm -f "$c_output"
    fi
}

# ================================================================
# Main
# ================================================================

main() {
    log_info "RDMA Fault Detection Latency Experiment"
    log_info "========================================"

    # Create results directory
    mkdir -p "$RESULTS_DIR"

    # Check prerequisites
    check_prereqs

    # Capture environment
    capture_environment

    # Write CSV header
    echo "scenario,iteration,t_inject_request_ns,t_ack_ns,tcp_rtt_ns,t_error_cqe_ns,detection_latency_ns,error_status,error_vendor_err" > "$OUTPUT_FILE"

    # Parse scenario list and run each
    IFS=',' read -ra SCENARIO_LIST <<< "$SCENARIOS"
    for scenario in "${SCENARIO_LIST[@]}"; do
        scenario=$(echo "$scenario" | tr -d ' ' | tr '[:upper:]' '[:lower:]')
        case "$scenario" in
            a)
                # For scenario A, make sure server is running
                if [ -n "$SERVER_SSH" ]; then
                    start_remote_server
                else
                    log_warn "No SERVER_SSH set. Start the server manually on Server B:"
                    log_warn "  ./server -d $DEV_NAME -i $IB_PORT -g $GID_INDEX -p $CTRL_PORT"
                    log_warn "Press Enter when server is ready..."
                    read -r
                fi
                run_scenario_a
                ;;
            b)
                # Scenario B needs server restart between iterations
                # First start, client handles reconnection
                start_remote_server
                run_scenario_b
                ;;
            c)
                start_remote_server
                run_scenario_c
                # Ensure link is back up after scenario C
                if [ -n "$SERVER_SSH" ]; then
                    ssh "$SERVER_SSH" "ip link set $NIC_IFACE up 2>/dev/null; true"
                fi
                ;;
            *)
                log_error "Unknown scenario: '$scenario' (valid: a, b, c)"
                ;;
        esac
    done

    # Stop remote server
    if [ -n "$SERVER_SSH" ]; then
        stop_remote_server
    fi

    # Run analysis
    if [ -f "$SCRIPT_DIR/analyze.py" ] && command -v python3 >/dev/null 2>&1; then
        log_info "Running analysis..."
        python3 "$SCRIPT_DIR/analyze.py" "$OUTPUT_FILE"
    else
        log_warn "Skipping analysis (python3 or analyze.py not available)"
    fi

    log_info "========================================"
    log_info "Experiment complete!"
    log_info "Results: $OUTPUT_FILE"
    log_info "Environment: ${RESULTS_DIR}/environment_${TIMESTAMP}.txt"
    log_info "========================================"
}

main "$@"
