#!/bin/bash
# run.sh — Multi-QP isolation experiment
# Run from 225. Manages server on 224 via SSH.
#
# Usage:
#   ./run.sh                      — run all modes (isolation + concurrent)
#   ./run.sh isolation  [trials]  — isolation test only
#   ./run.sh concurrent [trials]  — concurrent error test only

set -e

REMOTE="gustlr@SERVER_224_ADDR"
REMOTE_DIR="/home/gustlr/Desktop/gpu_fault_recovery/06_recovery/multi_qp"
LOCAL_DIR="$(cd "$(dirname "$0")" && pwd)"

MODE="${1:-all}"
TRIALS="${2:-10}"

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
    echo "[server] Starting multi_qp server on 224..."
    ssh -f "$REMOTE" "cd $REMOTE_DIR && nohup ./server > /tmp/multi_qp_server.log 2>&1 < /dev/null & exit"
    sleep 2
}

check_server() {
    ssh "$REMOTE" "pgrep -f './server'" > /dev/null 2>&1
}

# --- Cleanup on exit ---
trap 'set +e; stop_server' EXIT

mkdir -p "$LOCAL_DIR/results"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# --- Run a single mode ---

run_mode() {
    local mode="$1"
    local trials="$2"

    stop_server
    start_server

    if ! check_server; then
        echo "ERROR: server failed to start on 224"
        echo "Check: ssh $REMOTE 'cat /tmp/multi_qp_server.log'"
        exit 1
    fi

    case "$mode" in
        isolation)
            echo ""
            echo "========== Mode: isolation (trials=$trials) =========="
            OUTFILE="$LOCAL_DIR/results/${TIMESTAMP}_isolation.csv"

            "$LOCAL_DIR/client" isolation "$trials" > "$OUTFILE"
            RC=$?

            if [ $RC -ne 0 ]; then
                echo "ERROR: client exited with code $RC"
                echo "Server log: ssh $REMOTE 'cat /tmp/multi_qp_server.log'"
                return $RC
            fi

            echo "Results: $OUTFILE"
            echo ""

            # Print comment/summary lines
            grep '^#' "$OUTFILE" || true
            echo ""

            # Throughput impact summary
            echo "=== QP_A Throughput Impact ==="
            grep -v '^#' "$OUTFILE" | awk -F, '
                NF < 8 { next }
                $8 == "baseline"        { sum += $6; n++ }
                $8 == "during_fault"    { sum_f += $6; nf++ }
                $8 == "during_recovery" { sum_r += $6; nr++ }
                $8 == "after_recovery"  { sum_a += $6; na++ }
                END {
                    if (n  > 0) printf "  Baseline:         avg %.0f ops/window (%d samples)\n", sum/n, n
                    if (nf > 0) printf "  During fault:     avg %.0f ops/window (%d samples)\n", sum_f/nf, nf
                    if (nr > 0) printf "  During recovery:  avg %.0f ops/window (%d samples)\n", sum_r/nr, nr
                    if (na > 0) printf "  After recovery:   avg %.0f ops/window (%d samples)\n", sum_a/na, na
                    if (n > 0 && nf > 0)
                        printf "  Fault impact:     %.1f%%\n", (1 - (sum_f/nf) / (sum/n)) * 100
                    if (n > 0 && na > 0)
                        printf "  Recovery delta:   %.1f%%\n", (1 - (sum_a/na) / (sum/n)) * 100
                }'
            ;;

        concurrent)
            echo ""
            echo "========== Mode: concurrent (trials=$trials) =========="
            OUTFILE="$LOCAL_DIR/results/${TIMESTAMP}_concurrent.csv"

            "$LOCAL_DIR/client" concurrent "$trials" > "$OUTFILE"
            RC=$?

            if [ $RC -ne 0 ]; then
                echo "ERROR: client exited with code $RC"
                echo "Server log: ssh $REMOTE 'cat /tmp/multi_qp_server.log'"
                return $RC
            fi

            echo "Results: $OUTFILE"
            echo ""
            cat "$OUTFILE"
            ;;

        *)
            echo "ERROR: unknown mode '$mode' (expected: isolation, concurrent, all)"
            exit 1
            ;;
    esac
}

# --- Main ---

if [ "$MODE" = "all" ]; then
    run_mode isolation "$TRIALS"
    run_mode concurrent "$TRIALS"
    echo ""
    echo "========================================"
    echo " ALL DONE — results in $LOCAL_DIR/results/"
    echo "========================================"
else
    run_mode "$MODE" "$TRIALS"
fi

exit 0
