#!/usr/bin/env bash
#
# run_experiment.sh - Orchestration for Experiment 3: QP Recovery Overhead
#
# Server lifecycle: the server binary stays alive for the entire run.
# No QP destroy/create between iterations — only in-place state transitions.
#
# Usage:
#   ./run_experiment.sh             # runs with config.sh defaults
#   ITERATIONS=200 ./run_experiment.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -f "$SCRIPT_DIR/config.sh" ]; then
    # shellcheck source=config.sh
    source "$SCRIPT_DIR/config.sh"
fi

SERVER_IP="${SERVER_IP:?ERROR: Set SERVER_IP in config.sh}"
DEV_NAME="${DEV_NAME:-mlx5_0}"
IB_PORT="${IB_PORT:-1}"
GID_INDEX="${GID_INDEX:-3}"
CTRL_PORT="${CTRL_PORT:-18515}"
ITERATIONS="${ITERATIONS:-100}"
SERVER_SSH="${SERVER_SSH:-}"
SERVER_BIN_DIR="${SERVER_BIN_DIR:-}"
RESULTS_DIR="${RESULTS_DIR:-${SCRIPT_DIR}/results}"

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
CLIENT_CSV="${RESULTS_DIR}/recovery_${TIMESTAMP}.csv"
SERVER_CSV_NAME="server_recovery_${TIMESTAMP}.csv"
ENV_FILE="${RESULTS_DIR}/environment_${TIMESTAMP}.txt"

log_info()  { echo "[INFO ] $(date '+%H:%M:%S') $*" >&2; }
log_warn()  { echo "[WARN ] $(date '+%H:%M:%S') $*" >&2; }
log_error() { echo "[ERROR] $(date '+%H:%M:%S') $*" >&2; }

mkdir -p "$RESULTS_DIR"

# -----------------------------------------------------------------
# Prerequisites
# -----------------------------------------------------------------
if [ ! -x "$SCRIPT_DIR/client" ]; then
    log_info "Building experiment3..."
    make -C "$SCRIPT_DIR" all
fi

# -----------------------------------------------------------------
# Environment capture
# -----------------------------------------------------------------
{
    echo "=== Experiment 3: QP Recovery Overhead ==="
    echo "Date: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
    echo "Hostname: $(hostname)"
    echo "Kernel: $(uname -r)"
    echo ""
    echo "=== Configuration ==="
    echo "SERVER_IP=$SERVER_IP"
    echo "DEV_NAME=$DEV_NAME"
    echo "IB_PORT=$IB_PORT"
    echo "GID_INDEX=$GID_INDEX"
    echo "CTRL_PORT=$CTRL_PORT"
    echo "ITERATIONS=$ITERATIONS"
    echo ""
    echo "=== RDMA Devices (local) ==="
    ibv_devinfo 2>/dev/null || echo "(ibv_devinfo not available)"
} > "$ENV_FILE" 2>&1

# -----------------------------------------------------------------
# Server start
# -----------------------------------------------------------------
if [ -n "$SERVER_SSH" ] && [ -n "$SERVER_BIN_DIR" ]; then
    log_info "Starting server via SSH: $SERVER_SSH"
    ssh "$SERVER_SSH" "pkill -f '${SERVER_BIN_DIR}/server' 2>/dev/null; sleep 0.5; true" || true

    SERVER_CMD="cd '$SERVER_BIN_DIR' && nohup ./server \
        -d '$DEV_NAME' -i '$IB_PORT' -g '$GID_INDEX' -p '$CTRL_PORT' \
        -o '${SERVER_BIN_DIR}/results/${SERVER_CSV_NAME}' \
        > /tmp/rdma_exp3_server.log 2>&1 &"

    # shellcheck disable=SC2029
    ssh "$SERVER_SSH" "$SERVER_CMD"

    retries=15
    while [ $retries -gt 0 ]; do
        if ssh "$SERVER_SSH" "ss -tln | grep -q ':${CTRL_PORT} '" 2>/dev/null; then
            log_info "Server listening on port $CTRL_PORT"
            break
        fi
        sleep 1
        retries=$((retries - 1))
    done
    if [ $retries -eq 0 ]; then
        log_error "Server did not start within 15s"
        ssh "$SERVER_SSH" "tail -20 /tmp/rdma_exp3_server.log" >&2 || true
        exit 1
    fi
else
    log_warn "SERVER_SSH/SERVER_BIN_DIR not set."
    log_warn "Start the server manually on Server B:"
    log_warn "  ./server -d $DEV_NAME -i $IB_PORT -g $GID_INDEX -p $CTRL_PORT \\"
    log_warn "           -o results/${SERVER_CSV_NAME}"
    log_warn "Press Enter when the server is listening..."
    read -r
fi

# -----------------------------------------------------------------
# Client run
# -----------------------------------------------------------------
log_info "============================================="
log_info "  Running Experiment 3 client: $ITERATIONS iterations"
log_info "============================================="

"$SCRIPT_DIR/client" \
    -s "$SERVER_IP" \
    -d "$DEV_NAME" \
    -i "$IB_PORT" \
    -g "$GID_INDEX" \
    -p "$CTRL_PORT" \
    -n "$ITERATIONS" \
    -o "$CLIENT_CSV" || log_warn "Client returned non-zero"

# -----------------------------------------------------------------
# Fetch server CSV (if remote)
# -----------------------------------------------------------------
if [ -n "$SERVER_SSH" ] && [ -n "$SERVER_BIN_DIR" ]; then
    log_info "Fetching server CSV..."
    scp "$SERVER_SSH:${SERVER_BIN_DIR}/results/${SERVER_CSV_NAME}" \
        "${RESULTS_DIR}/${SERVER_CSV_NAME}" 2>/dev/null \
        || log_warn "Failed to fetch server CSV"

    ssh "$SERVER_SSH" "pkill -f '${SERVER_BIN_DIR}/server' 2>/dev/null; true" || true
fi

# -----------------------------------------------------------------
# Analyze
# -----------------------------------------------------------------
if [ -f "$SCRIPT_DIR/analyze.py" ] && command -v python3 >/dev/null 2>&1; then
    log_info "Running analysis..."
    python3 "$SCRIPT_DIR/analyze.py" "$CLIENT_CSV"
fi

log_info "============================================="
log_info "Experiment 3 complete!"
log_info "Client CSV:  $CLIENT_CSV"
log_info "Server CSV:  ${RESULTS_DIR}/${SERVER_CSV_NAME}"
log_info "Environment: $ENV_FILE"
log_info "============================================="
