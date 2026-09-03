#!/bin/bash
# run.sh — Early detection experiment suite for RETRY_EXC_ERR
# Runs all 3 modes sequentially, or a single mode.
#
# Usage:
#   ./run.sh              — run all modes
#   ./run.sh force_err    — force-ERR verification only
#   ./run.sh timeline     — counter timeline only
#   ./run.sh recover      — early detection recovery only
#   ./run.sh recover roce_adp_retrans 10 10

set -e

REMOTE="gustlr@SERVER_224_ADDR"
SERVER_DIR="/home/gustlr/Desktop/gpu_fault_recovery/06_recovery/RETRY_EXC_ERR"
LOCAL_DIR="$(cd "$(dirname "$0")" && pwd)"

# --- Build ---

echo "[build] Building client on 225..."
make -C "$LOCAL_DIR" clean && make -C "$LOCAL_DIR"

echo "[build] Building server on 224..."
ssh "$REMOTE" "cd $SERVER_DIR && make clean && make"

# --- Server management ---

stop_server() {
    ssh "$REMOTE" "pkill -f './server'" 2>/dev/null || true
    sleep 1
}

start_server() {
    echo "[server] Starting RETRY_EXC_ERR server on 224..."
    ssh -f "$REMOTE" "cd $SERVER_DIR && nohup ./server > /tmp/early_detect_server.log 2>&1 < /dev/null & exit"
    sleep 2
}

check_server() {
    ssh "$REMOTE" "pgrep -f './server'" > /dev/null 2>&1
}

trap 'set +e; stop_server' EXIT

mkdir -p "$LOCAL_DIR/results"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
MODE="${1:-all}"

run_mode() {
    local mode="$1"
    shift

    stop_server
    start_server
    if ! check_server; then
        echo "ERROR: server failed to start"
        exit 1
    fi

    case "$mode" in
        force_err)
            echo ""
            echo "========== Mode: force_err =========="
            OUTFILE="$LOCAL_DIR/results/${TIMESTAMP}_force_err.csv"
            "$LOCAL_DIR/client" force_err "$@" > "$OUTFILE"
            echo "Results: $OUTFILE"
            cat "$OUTFILE"
            ;;
        timeline)
            echo ""
            echo "========== Mode: timeline =========="
            OUTFILE="$LOCAL_DIR/results/${TIMESTAMP}_timeline.csv"
            "$LOCAL_DIR/client" timeline "$@" > "$OUTFILE"
            echo "Results: $OUTFILE"
            echo ""
            echo "=== First increment per counter ==="
            for C in roce_adp_retrans roce_adp_retrans_to local_ack_timeout_err req_transport_retries_exceeded req_cqe_error; do
                grep ",$C," "$OUTFILE" 2>/dev/null | awk -F, -v c="$C" '
                !seen[$1]++ { n++; sum+=$3 }
                END { if(n>0) printf "  %-35s first at avg %10.0f us (%d trials)\n", c, sum/n, n }' || true
            done
            ;;
        recover)
            local COUNTER="${1:-roce_adp_retrans}"
            local POLL_MS="${2:-10}"
            local TRIALS="${3:-10}"
            echo ""
            echo "========== Mode: recover (counter=$COUNTER, poll=${POLL_MS}ms) =========="
            OUTFILE="$LOCAL_DIR/results/${TIMESTAMP}_recover_${COUNTER}_${POLL_MS}ms.csv"
            "$LOCAL_DIR/client" recover "$COUNTER" "$POLL_MS" "$TRIALS" > "$OUTFILE"
            echo "Results: $OUTFILE"
            grep -v '^#' "$OUTFILE" | awk -F, '{
                detect+=$4; ftc+=$9; rec+=$10; total+=$12; n++
            } END {
                printf "  detect:     avg %.0f us\n", detect/n
                printf "  force→CQE:  avg %.0f us\n", ftc/n
                printf "  recovery:   avg %.0f us\n", rec/n
                printf "  total:      avg %.0f us\n", total/n
                printf "  speedup:    %.1fx (vs passive 3,740,787 us)\n", 3740787/(total/n)
            }'
            ;;
    esac
}

if [ "$MODE" = "all" ]; then
    run_mode force_err
    run_mode timeline
    run_mode recover roce_adp_retrans 10 10
    run_mode recover local_ack_timeout_err 10 10

    echo ""
    echo "========================================"
    echo " ALL DONE"
    echo "========================================"
else
    shift
    run_mode "$MODE" "$@"
fi

exit 0
