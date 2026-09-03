#!/usr/bin/env bash
#
# run_experiment.sh - 3.7s Retry Decomposition
#
# Sweeps retry_cnt 0..7 × timeout {14, 8} under process kill.
# Reuses experiment4/client binary. Captures per-iteration raw
# detection latencies from client stderr for delta analysis.
#
# Usage:
#   ./run_experiment.sh              # full sweep
#   DRY_RUN=1 ./run_experiment.sh    # print configs without running

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -f "$SCRIPT_DIR/config.sh" ] && source "$SCRIPT_DIR/config.sh"

SERVER_IP="${SERVER_IP:?Set SERVER_IP in config.sh}"
DEV_NAME="${DEV_NAME:-mlx5_0}"
IB_PORT="${IB_PORT:-1}"
GID_INDEX="${GID_INDEX:-3}"
CTRL_PORT="${CTRL_PORT:-18515}"
RETRY_VALUES="${RETRY_VALUES:-0 1 2 3 4 5 6 7}"
TIMEOUT_VALUES="${TIMEOUT_VALUES:-14 8}"
KILL_ITERS="${KILL_ITERS:-30}"
CLIENT="${CLIENT:-${SCRIPT_DIR}/client}"
SERVER_SSH="${SERVER_SSH:-}"
SERVER_BIN_DIR="${SERVER_BIN_DIR:-}"
RESULTS_DIR="${RESULTS_DIR:-${SCRIPT_DIR}/results}"
DRY_RUN="${DRY_RUN:-0}"

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
RAW_CSV="${RESULTS_DIR}/raw_${TIMESTAMP}.csv"
AGG_CSV="${RESULTS_DIR}/agg_${TIMESTAMP}.csv"
ENV_FILE="${RESULTS_DIR}/environment_${TIMESTAMP}.txt"

mkdir -p "$RESULTS_DIR"

log_info()  { echo "[INFO ] $(date '+%H:%M:%S') $*" >&2; }
log_warn()  { echo "[WARN ] $(date '+%H:%M:%S') $*" >&2; }
log_error() { echo "[ERROR] $(date '+%H:%M:%S') $*" >&2; }

timeout_ms() {
    awk -v x="$1" 'BEGIN{ printf "%.3f", 4.096 * (2 ** x) / 1000 }'
}

# -----------------------------------------------------------------
# Validate client binary
if [ ! -x "$CLIENT" ]; then
    log_error "Client binary not found: $CLIENT"
    log_info "Build it: make -C $(dirname "$CLIENT")"
    exit 1
fi

# Total configs
n_retry=$(echo $RETRY_VALUES | wc -w)
n_timeout=$(echo $TIMEOUT_VALUES | wc -w)
n_total=$((n_retry * n_timeout))
log_info "=== 3.7s Retry Decomposition ==="
log_info "Configs: ${n_retry} retry × ${n_timeout} timeout = ${n_total} configs × N=${KILL_ITERS}"
log_info "Client: $CLIENT"

if [ "$DRY_RUN" = "1" ]; then
    log_info "DRY_RUN: listing configs"
    for R in $RETRY_VALUES; do
        for T in $TIMEOUT_VALUES; do
            echo "  R=$R T=$T (~$(timeout_ms $T)ms) × N=$KILL_ITERS"
        done
    done
    exit 0
fi

# -----------------------------------------------------------------
# Save environment
{
    echo "=== Retry Decomposition Experiment ==="
    echo "Date: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
    echo "Hostname: $(hostname)"
    echo "Kernel: $(uname -r)"
    echo ""
    echo "SERVER_IP=$SERVER_IP"
    echo "RETRY_VALUES=$RETRY_VALUES"
    echo "TIMEOUT_VALUES=$TIMEOUT_VALUES"
    echo "KILL_ITERS=$KILL_ITERS"
    echo "CLIENT=$CLIENT"
    echo ""
    echo "=== ibv_devinfo ==="
    ibv_devinfo 2>/dev/null || echo "(unavailable)"
} > "$ENV_FILE"

# -----------------------------------------------------------------
# Raw CSV header
echo "retry_cnt,qp_timeout,timeout_ms,iteration,detection_ms,status" > "$RAW_CSV"

# -----------------------------------------------------------------
# Server management
start_server_kill() {
    if [ -z "$SERVER_SSH" ]; then
        log_warn "SERVER_SSH unset; start server_loop.sh on 224 manually:"
        log_warn "  cd $SERVER_BIN_DIR && ./server_loop.sh -d $DEV_NAME -i $IB_PORT -g $GID_INDEX -p $CTRL_PORT"
        read -r -p "Press Enter when server_loop is running: "
        return
    fi
    [ -z "$SERVER_BIN_DIR" ] && { log_error "SERVER_BIN_DIR required"; exit 1; }

    ssh "$SERVER_SSH" "pkill -f '${SERVER_BIN_DIR}/server' 2>/dev/null; \
                       pkill -f 'server_loop' 2>/dev/null; sleep 0.5; true" || true
    ssh -f "$SERVER_SSH" "cd '$SERVER_BIN_DIR' && \
        nohup ./server_loop.sh \
            -d '$DEV_NAME' -i '$IB_PORT' -g '$GID_INDEX' -p '$CTRL_PORT' \
            </dev/null >/tmp/rdma_retry_decomp_server.log 2>&1 & disown"

    for _ in $(seq 1 15); do
        if ssh "$SERVER_SSH" "ss -tln | grep -q ':${CTRL_PORT} '" 2>/dev/null; then
            log_info "server_loop listening on $SERVER_SSH:$CTRL_PORT"
            return
        fi
        sleep 1
    done
    log_error "server_loop did not start"
    ssh "$SERVER_SSH" "tail -20 /tmp/rdma_retry_decomp_server.log 2>/dev/null" >&2 || true
    exit 1
}

stop_server() {
    [ -z "$SERVER_SSH" ] && return
    ssh "$SERVER_SSH" "pkill -f '${SERVER_BIN_DIR}/server' 2>/dev/null; \
                       pkill -f 'server_loop' 2>/dev/null; true" || true
}

# -----------------------------------------------------------------
# Main sweep
start_server_kill

config_idx=0
for T in $TIMEOUT_VALUES; do
    T_MS=$(timeout_ms "$T")
    for R in $RETRY_VALUES; do
        config_idx=$((config_idx + 1))
        log_info "[$config_idx/$n_total] R=$R T=$T (~${T_MS}ms) × N=$KILL_ITERS"

        STDERR_TMP=$(mktemp /tmp/retry_decomp_XXXXXX.log)

        "$CLIENT" -s "$SERVER_IP" -d "$DEV_NAME" \
            -i "$IB_PORT" -g "$GID_INDEX" -p "$CTRL_PORT" \
            -R "$R" -O "$T" -n "$KILL_ITERS" \
            -o "$AGG_CSV" 2>"$STDERR_TMP" || log_warn "client returned non-zero for R=$R T=$T"

        # Parse per-iteration detection times from stderr
        # Format: [INFO ] client.c:417: kill[N]: detect=X.Xms status=Y
        grep -oP 'kill\[\K\d+\]: detect=[\d.]+ms status=\d+' "$STDERR_TMP" | \
        while IFS= read -r match; do
            iter=$(echo "$match" | grep -oP '^\d+')
            detect=$(echo "$match" | grep -oP 'detect=\K[\d.]+')
            status=$(echo "$match" | grep -oP 'status=\K\d+')
            echo "$R,$T,$T_MS,$iter,$detect,$status" >> "$RAW_CSV"
        done

        n_parsed=$(grep -c 'detect=' "$STDERR_TMP" 2>/dev/null || echo 0)
        log_info "  → parsed $n_parsed iterations"

        rm -f "$STDERR_TMP"
    done
done

stop_server

# -----------------------------------------------------------------
log_info "============================================="
log_info "Raw per-iteration: $RAW_CSV"
log_info "Aggregate:         $AGG_CSV"
log_info "============================================="

if command -v python3 >/dev/null 2>&1 && [ -f "$SCRIPT_DIR/analyze.py" ]; then
    log_info "Running analysis..."
    python3 "$SCRIPT_DIR/analyze.py" "$RAW_CSV" || true
fi
