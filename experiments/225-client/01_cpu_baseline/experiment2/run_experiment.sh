#!/usr/bin/env bash
#
# run_experiment.sh - Orchestration for Experiment 2: Blind Window
#
# Iterates over all (sleep_time, fault_type) combinations.
# For each combination, runs the client binary N times,
# appending results to a single CSV file.
#
# Server lifecycle:
#   Scenario A (QP->ERR): server stays alive, client handles reset
#   Scenario B (kill):    server_loop.sh on Server B auto-restarts
#   Scenario C (link-down): server_link_loop.sh on Server B
#
# Prerequisites:
#   - experiment1/server binary built
#   - SSH key-based auth to Server B (for scenarios b/c)
#   - Root on Server B (for scenario c)
#
# Usage:
#   ./run_experiment.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXP1_DIR="$(cd "$SCRIPT_DIR/../experiment1" && pwd)"

# ================================================================
# Load configuration
# ================================================================

if [ -f "$SCRIPT_DIR/config.sh" ]; then
    # shellcheck source=config.sh
    source "$SCRIPT_DIR/config.sh"
fi

SERVER_IP="${SERVER_IP:?ERROR: Set SERVER_IP in config.sh}"
DEV_NAME="${DEV_NAME:-mlx5_0}"
IB_PORT="${IB_PORT:-1}"
GID_INDEX="${GID_INDEX:-3}"
CTRL_PORT="${CTRL_PORT:-18515}"
NIC_IFACE="${NIC_IFACE:-enp1s0f0np0}"
SLEEP_VALUES="${SLEEP_VALUES:-0 1000 10000 100000 1000000 5000000 10000000}"
FAULT_TYPES="${FAULT_TYPES:-a b c}"
ITERATIONS="${ITERATIONS:-30}"
SERVER_SSH="${SERVER_SSH:-}"
SERVER_BIN_DIR="${SERVER_BIN_DIR:-}"
SERVER_NIC_IP="${SERVER_NIC_IP:-}"
RESULTS_DIR="${RESULTS_DIR:-${SCRIPT_DIR}/results}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
COMBINED_CSV="${RESULTS_DIR}/blind_window_${TIMESTAMP}.csv"

# ================================================================
# Utility
# ================================================================

log_info()  { echo "[INFO ] $(date '+%H:%M:%S') $*" >&2; }
log_warn()  { echo "[WARN ] $(date '+%H:%M:%S') $*" >&2; }
log_error() { echo "[ERROR] $(date '+%H:%M:%S') $*" >&2; }

# ================================================================
# Prerequisite checks
# ================================================================

check_prereqs() {
    log_info "Checking prerequisites..."

    if [ ! -f "$SCRIPT_DIR/client" ]; then
        log_info "Building experiment2 client..."
        make -C "$SCRIPT_DIR" all
    fi

    if [ ! -x "$EXP1_DIR/server" ]; then
        log_error "experiment1/server not found. Build it first: make -C $EXP1_DIR"
        exit 1
    fi

    for fault in $FAULT_TYPES; do
        if [[ "$fault" == "b" || "$fault" == "c" ]]; then
            if [ -z "$SERVER_SSH" ]; then
                log_error "SERVER_SSH required for scenario $fault"
                exit 1
            fi
            if [ -z "$SERVER_BIN_DIR" ]; then
                log_error "SERVER_BIN_DIR required for scenario $fault"
                exit 1
            fi
            if ! ssh -o BatchMode=yes -o ConnectTimeout=5 "$SERVER_SSH" true 2>/dev/null; then
                log_error "Cannot SSH to $SERVER_SSH"
                exit 1
            fi
        fi
    done

    if [[ "$FAULT_TYPES" == *"c"* ]] && [ -z "$SERVER_NIC_IP" ]; then
        log_error "SERVER_NIC_IP required for scenario c (e.g., 10.0.0.4/24)"
        exit 1
    fi

    log_info "Prerequisites OK"
}

# ================================================================
# Environment capture
# ================================================================

capture_environment() {
    local env_file="${RESULTS_DIR}/environment_${TIMESTAMP}.txt"
    log_info "Capturing environment to $env_file"

    {
        echo "=== Experiment 2: CPU Polling Interval Blind Window ==="
        echo "Date: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
        echo "Hostname: $(hostname)"
        echo "Kernel: $(uname -r)"
        echo ""
        echo "=== RDMA Devices ==="
        ibv_devinfo 2>/dev/null || echo "(ibv_devinfo not available)"
        echo ""
        echo "=== Configuration ==="
        echo "SERVER_IP=$SERVER_IP"
        echo "DEV_NAME=$DEV_NAME"
        echo "IB_PORT=$IB_PORT"
        echo "GID_INDEX=$GID_INDEX"
        echo "CTRL_PORT=$CTRL_PORT"
        echo "SLEEP_VALUES=$SLEEP_VALUES"
        echo "FAULT_TYPES=$FAULT_TYPES"
        echo "ITERATIONS=$ITERATIONS"
        echo ""
        echo "=== CPU ==="
        lscpu | head -20
    } > "$env_file" 2>&1

    log_info "Environment captured"
}

# ================================================================
# Server management
# ================================================================

start_server_for_scenario() {
    local scenario="$1"

    if [ -z "$SERVER_SSH" ]; then
        log_warn "No SERVER_SSH. Start server manually on Server B."
        log_warn "Press Enter when ready..."
        read -r
        return 0
    fi

    # Kill any existing server process
    ssh "$SERVER_SSH" "pkill -f '${SERVER_BIN_DIR}/server' 2>/dev/null; sleep 0.5; true"

    local server_cmd=""
    case "$scenario" in
        a)
            server_cmd="cd '$SERVER_BIN_DIR' && nohup ./server \
                -d '$DEV_NAME' -i '$IB_PORT' -g '$GID_INDEX' -p '$CTRL_PORT' \
                -I '$NIC_IFACE' > /tmp/rdma_exp2_server.log 2>&1 &"
            ;;
        b)
            server_cmd="cd '$SERVER_BIN_DIR' && nohup ./server_loop.sh \
                -d '$DEV_NAME' -i '$IB_PORT' -g '$GID_INDEX' -p '$CTRL_PORT' \
                > /tmp/rdma_exp2_server.log 2>&1 &"
            ;;
        c)
            server_cmd="cd '$SERVER_BIN_DIR' && nohup sudo ./server_link_loop.sh \
                -a '$SERVER_NIC_IP' \
                -d '$DEV_NAME' -i '$IB_PORT' -g '$GID_INDEX' -p '$CTRL_PORT' \
                -I '$NIC_IFACE' > /tmp/rdma_exp2_server.log 2>&1 &"
            ;;
    esac

    log_info "Starting server for scenario $scenario..."
    # shellcheck disable=SC2029
    ssh "$SERVER_SSH" "$server_cmd"

    local retries=15
    while [ $retries -gt 0 ]; do
        if ssh "$SERVER_SSH" "ss -tln | grep -q ':${CTRL_PORT} '" 2>/dev/null; then
            log_info "Server is listening on port $CTRL_PORT"
            return 0
        fi
        sleep 1
        retries=$((retries - 1))
    done

    log_error "Server did not start within 15 seconds"
    ssh "$SERVER_SSH" "tail -20 /tmp/rdma_exp2_server.log 2>/dev/null" >&2
    return 1
}

stop_server() {
    if [ -z "$SERVER_SSH" ]; then
        return 0
    fi

    log_info "Stopping remote server..."
    ssh "$SERVER_SSH" "pkill -f '${SERVER_BIN_DIR}/server' 2>/dev/null; \
                       pkill -f 'server_loop' 2>/dev/null; \
                       pkill -f 'server_link_loop' 2>/dev/null; true"
}

# ================================================================
# Run one (sleep, fault) combination
# ================================================================

run_combination() {
    local sleep_us="$1"
    local fault="$2"
    local iter_csv="${RESULTS_DIR}/.tmp_s${sleep_us}_f${fault}.csv"

    log_info "======================================================="
    log_info "  sleep=${sleep_us} us, scenario=${fault}, iterations=${ITERATIONS}"
    log_info "======================================================="

    "$SCRIPT_DIR/client" \
        -s "$SERVER_IP" \
        -d "$DEV_NAME" \
        -i "$IB_PORT" \
        -g "$GID_INDEX" \
        -p "$CTRL_PORT" \
        -T "$sleep_us" \
        -S "$fault" \
        -n "$ITERATIONS" \
        -o "$iter_csv" || {
            log_warn "Client returned non-zero for sleep=${sleep_us} scenario=${fault}"
        }

    if [ -f "$iter_csv" ]; then
        tail -n +2 "$iter_csv" >> "$COMBINED_CSV"
        rm -f "$iter_csv"
    fi
}

# ================================================================
# Main
# ================================================================

main() {
    log_info "============================================="
    log_info "  Experiment 2: CPU Polling Interval Blind Window"
    log_info "============================================="
    log_info "Sleep values: $SLEEP_VALUES"
    log_info "Fault types:  $FAULT_TYPES"
    log_info "Iterations:   $ITERATIONS per combination"

    # Count total combinations
    local n_sleep=0 n_fault=0
    for _ in $SLEEP_VALUES; do n_sleep=$((n_sleep + 1)); done
    for _ in $FAULT_TYPES; do n_fault=$((n_fault + 1)); done
    local total=$((n_sleep * n_fault * ITERATIONS))
    log_info "Total measurements: $total ($n_sleep sleeps x $n_fault faults x $ITERATIONS iters)"

    mkdir -p "$RESULTS_DIR"
    check_prereqs
    capture_environment

    # Write combined CSV header
    echo "sleep_us,scenario,iteration,t_inject_request_ns,t_ack_ns,tcp_rtt_ns,t_wakeup_ns,t_detected_ns,detection_delay_ns,wakeup_to_detection_ns,error_status,vendor_err" \
        > "$COMBINED_CSV"

    local combo=0
    local total_combos=$((n_sleep * n_fault))

    for fault in $FAULT_TYPES; do
        # Start (or restart) the appropriate server wrapper for this fault type
        start_server_for_scenario "$fault"

        for sleep_us in $SLEEP_VALUES; do
            combo=$((combo + 1))
            log_info "--- Combination $combo/$total_combos ---"

            run_combination "$sleep_us" "$fault"

            # For scenarios b/c, the server wrapper auto-restarts.
            # For scenario a, the client handles QP reset internally.
            # Between sleep values for the same fault type, no server restart needed
            # (except b/c where the wrapper handles it).
        done

        stop_server
        sleep 2
    done

    # Run analysis
    if [ -f "$SCRIPT_DIR/analyze.py" ] && command -v python3 >/dev/null 2>&1; then
        log_info "Running analysis..."
        python3 "$SCRIPT_DIR/analyze.py" "$COMBINED_CSV"
    else
        log_warn "Skipping analysis (python3 or analyze.py not available)"
    fi

    log_info "============================================="
    log_info "Experiment 2 complete!"
    log_info "Results: $COMBINED_CSV"
    log_info "============================================="
}

main "$@"
