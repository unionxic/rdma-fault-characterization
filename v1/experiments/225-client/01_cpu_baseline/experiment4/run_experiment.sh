#!/usr/bin/env bash
#
# run_experiment.sh - Sweep (retry_cnt × qp_timeout × {netem | kill}) for
# Experiment 4. Applies tc netem on the local NIC for transient tests
# (requires sudo). Persistent (kill) tests assume server_loop.sh is
# running on the remote node, restarting the server after each kill.
#
# Usage:
#   ./run_experiment.sh                # full sweep
#   PHASE=netem ./run_experiment.sh    # only transient
#   PHASE=kill  ./run_experiment.sh    # only persistent
#   PHASE=baseline ./run_experiment.sh # only baseline (no fault, no netem)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -f "$SCRIPT_DIR/config.sh" ] && source "$SCRIPT_DIR/config.sh"

SERVER_IP="${SERVER_IP:?Set SERVER_IP in config.sh}"
DEV_NAME="${DEV_NAME:-mlx5_0}"
IB_PORT="${IB_PORT:-1}"
GID_INDEX="${GID_INDEX:-3}"
CTRL_PORT="${CTRL_PORT:-18515}"
NIC_IFACE="${NIC_IFACE:-enp1s0f0np0}"
RETRY_VALUES="${RETRY_VALUES:-0 1 3 7}"
TIMEOUT_VALUES="${TIMEOUT_VALUES:-8 12 14 17 20}"
LOSS_VALUES="${LOSS_VALUES:-1 5 10 50}"
NETEM_WRITES="${NETEM_WRITES:-200}"
KILL_ITERS="${KILL_ITERS:-10}"
SERVER_SSH="${SERVER_SSH:-}"
SERVER_BIN_DIR="${SERVER_BIN_DIR:-}"
RESULTS_DIR="${RESULTS_DIR:-${SCRIPT_DIR}/results}"
PHASE="${PHASE:-all}"

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
CSV="${RESULTS_DIR}/exp4_${TIMESTAMP}.csv"
ENV_FILE="${RESULTS_DIR}/environment_${TIMESTAMP}.txt"

mkdir -p "$RESULTS_DIR"

log_info()  { echo "[INFO ] $(date '+%H:%M:%S') $*" >&2; }
log_warn()  { echo "[WARN ] $(date '+%H:%M:%S') $*" >&2; }
log_error() { echo "[ERROR] $(date '+%H:%M:%S') $*" >&2; }

# -----------------------------------------------------------------
if [ ! -x "$SCRIPT_DIR/client" ]; then
    log_info "Building experiment4 client..."
    make -C "$SCRIPT_DIR" all
fi

{
    echo "=== Experiment 4: NIC Retry Boundary ==="
    echo "Date: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
    echo "Hostname: $(hostname)"
    echo "Kernel: $(uname -r)"
    echo ""
    echo "SERVER_IP=$SERVER_IP"
    echo "NIC_IFACE=$NIC_IFACE"
    echo "RETRY_VALUES=$RETRY_VALUES"
    echo "TIMEOUT_VALUES=$TIMEOUT_VALUES"
    echo "LOSS_VALUES=$LOSS_VALUES"
    echo "NETEM_WRITES=$NETEM_WRITES"
    echo "KILL_ITERS=$KILL_ITERS"
    echo "PHASE=$PHASE"
    echo ""
    echo "=== ibv_devinfo ==="
    ibv_devinfo 2>/dev/null || echo "(unavailable)"
} > "$ENV_FILE"

# -----------------------------------------------------------------
clear_netem() {
    sudo tc qdisc del dev "$NIC_IFACE" root 2>/dev/null || true
}
trap clear_netem EXIT

apply_netem() {
    local loss="$1"
    sudo tc qdisc del dev "$NIC_IFACE" root 2>/dev/null || true
    sudo tc qdisc add dev "$NIC_IFACE" root netem loss "${loss}%"
}

# Decode timeout to ms for log readability: 4.096us * 2^x
timeout_label() {
    awk -v x="$1" 'BEGIN{ printf "%.3fms", 4.096 * (2 ** x) / 1000 }'
}

# -----------------------------------------------------------------
# Server start (kill phase only — netem uses regular server)
start_server_kill() {
    [ -z "$SERVER_SSH" ] && { log_warn "SERVER_SSH unset; start server_loop.sh manually"; read -r -p "press Enter when server_loop is up: "; return; }
    [ -z "$SERVER_BIN_DIR" ] && { log_error "SERVER_BIN_DIR required"; exit 1; }

    ssh "$SERVER_SSH" "pkill -f '${SERVER_BIN_DIR}/server' 2>/dev/null; \
                       pkill -f 'server_loop' 2>/dev/null; sleep 0.5; true" || true
    # Use ssh -f and full stdio detachment so the SSH channel closes cleanly
    # even though the remote process keeps running.
    # shellcheck disable=SC2029
    ssh -f "$SERVER_SSH" "cd '$SERVER_BIN_DIR' && \
        nohup ./server_loop.sh \
            -d '$DEV_NAME' -i '$IB_PORT' -g '$GID_INDEX' -p '$CTRL_PORT' \
            </dev/null >/tmp/rdma_exp4_server.log 2>&1 & disown"

    for _ in $(seq 1 15); do
        if ssh "$SERVER_SSH" "ss -tln | grep -q ':${CTRL_PORT} '" 2>/dev/null; then
            log_info "server_loop listening"
            return
        fi
        sleep 1
    done
    log_error "server_loop did not start"
    ssh "$SERVER_SSH" "tail -20 /tmp/rdma_exp4_server.log 2>/dev/null" >&2 || true
    exit 1
}

start_server_passive() {
    [ -z "$SERVER_SSH" ] && { log_warn "SERVER_SSH unset; start passive server manually"; read -r -p "press Enter when server is up: "; return; }
    [ -z "$SERVER_BIN_DIR" ] && { log_error "SERVER_BIN_DIR required"; exit 1; }

    ssh "$SERVER_SSH" "pkill -f '${SERVER_BIN_DIR}/server' 2>/dev/null; \
                       pkill -f 'server_loop' 2>/dev/null; sleep 0.5; true" || true
    # shellcheck disable=SC2029
    ssh -f "$SERVER_SSH" "cd '$SERVER_BIN_DIR' && \
        nohup ./server \
            -d '$DEV_NAME' -i '$IB_PORT' -g '$GID_INDEX' -p '$CTRL_PORT' \
            </dev/null >/tmp/rdma_exp4_server.log 2>&1 & disown"

    for _ in $(seq 1 15); do
        if ssh "$SERVER_SSH" "ss -tln | grep -q ':${CTRL_PORT} '" 2>/dev/null; then
            log_info "passive server listening"
            return
        fi
        sleep 1
    done
    log_error "passive server did not start"
    ssh "$SERVER_SSH" "tail -20 /tmp/rdma_exp4_server.log 2>/dev/null" >&2 || true
    exit 1
}

stop_server() {
    [ -z "$SERVER_SSH" ] && return
    ssh "$SERVER_SSH" "pkill -f '${SERVER_BIN_DIR}/server' 2>/dev/null; \
                       pkill -f 'server_loop' 2>/dev/null; true" || true
}

# -----------------------------------------------------------------
phase_baseline() {
    log_info "=== PHASE: baseline (no fault, no netem) ==="
    start_server_passive
    for R in $RETRY_VALUES; do
        for T in $TIMEOUT_VALUES; do
            log_info "  baseline R=$R T=$T (~$(timeout_label $T))"
            "$SCRIPT_DIR/client" -s "$SERVER_IP" -d "$DEV_NAME" \
                -i "$IB_PORT" -g "$GID_INDEX" -p "$CTRL_PORT" \
                -M netem -R "$R" -O "$T" -L 0 -n "$NETEM_WRITES" \
                -o "$CSV" || log_warn "client returned non-zero"
        done
    done
    stop_server
}

phase_netem() {
    log_info "=== PHASE: netem transient faults ==="
    start_server_passive
    for L in $LOSS_VALUES; do
        log_info "  applying tc netem loss=${L}% on $NIC_IFACE"
        apply_netem "$L"
        for R in $RETRY_VALUES; do
            for T in $TIMEOUT_VALUES; do
                log_info "    netem L=${L}% R=$R T=$T (~$(timeout_label $T))"
                "$SCRIPT_DIR/client" -s "$SERVER_IP" -d "$DEV_NAME" \
                    -i "$IB_PORT" -g "$GID_INDEX" -p "$CTRL_PORT" \
                    -M netem -R "$R" -O "$T" -L "$L" -n "$NETEM_WRITES" \
                    -o "$CSV" || log_warn "client returned non-zero"
            done
        done
        clear_netem
    done
    stop_server
}

phase_kill() {
    log_info "=== PHASE: persistent fault (process kill) ==="
    start_server_kill
    for R in $RETRY_VALUES; do
        for T in $TIMEOUT_VALUES; do
            log_info "  kill R=$R T=$T (~$(timeout_label $T))"
            "$SCRIPT_DIR/client" -s "$SERVER_IP" -d "$DEV_NAME" \
                -i "$IB_PORT" -g "$GID_INDEX" -p "$CTRL_PORT" \
                -M kill -R "$R" -O "$T" -n "$KILL_ITERS" \
                -o "$CSV" || log_warn "client returned non-zero"
        done
    done
    stop_server
}

# -----------------------------------------------------------------
case "$PHASE" in
    baseline) phase_baseline ;;
    netem)    phase_netem ;;
    kill)     phase_kill ;;
    all)      phase_baseline; phase_netem; phase_kill ;;
    *)        log_error "Unknown PHASE=$PHASE (use baseline|netem|kill|all)"; exit 1 ;;
esac

if [ -f "$SCRIPT_DIR/analyze.py" ] && command -v python3 >/dev/null 2>&1; then
    log_info "Running analysis..."
    python3 "$SCRIPT_DIR/analyze.py" "$CSV" || true
fi

log_info "============================================="
log_info "Experiment 4 done: $CSV"
log_info "============================================="
