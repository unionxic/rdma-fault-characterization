#!/usr/bin/env bash
#
# run.sh - orchestrate the unified RDMA fault harness from the requester node.
#
# Builds both sides, launches probe_server on the responder over ssh, runs
# probe_client for each fault, and drops one CSV per fault into results/.
# Then invokes analyze.py for a combined summary.
#
# Usage:  ./run.sh [fault ...]      (defaults to $FAULTS from config.sh)
# Config comes from config.sh (override any var via the environment).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
# shellcheck source=config.sh
source config.sh

FAULTS_TO_RUN=("$@")
[ ${#FAULTS_TO_RUN[@]} -eq 0 ] && read -ra FAULTS_TO_RUN <<< "$FAULTS"

log() { echo "[run] $(date '+%H:%M:%S') $*" >&2; }

mkdir -p "$RESULTS_DIR"
STAMP="$(date +%Y%m%d_%H%M%S)"

# --- build both sides ---
log "building client (this node)"
make -s
log "syncing source + building server ($SERVER_SSH)"
# sync source (never the binaries) so the responder rebuilds from the same code
rsync -a --exclude='results/*' --exclude='/probe_client' --exclude='/probe_server' \
      "$SCRIPT_DIR"/ "$SERVER_SSH:$SERVER_DIR"/ >/dev/null
ssh "$SERVER_SSH" "cd $SERVER_DIR && make -s"

start_server() {
    ssh "$SERVER_SSH" "pkill -f probe_server 2>/dev/null; sleep 0.3" || true
    # ssh -f detaches after auth; the remote process survives this shell.
    ssh -f "$SERVER_SSH" "cd $SERVER_DIR && timeout 300 ./probe_server \
        -d $SERVER_DEV -i $IB_PORT -g $GID_INDEX -p $CTRL_PORT -C $SERVER_CPU \
        -I $SERVER_IFACE > /tmp/probe_srv.log 2>&1"
    for _ in $(seq 1 10); do
        if ssh -n "$SERVER_SSH" "ss -tln | grep -q ':$CTRL_PORT '"; then return 0; fi
        sleep 0.5
    done
    log "ERROR: server did not start; log:"; ssh -n "$SERVER_SSH" "cat /tmp/probe_srv.log" >&2
    return 1
}
stop_server() { ssh "$SERVER_SSH" "pkill -f probe_server 2>/dev/null; true" || true; }

run_one() {
    local fault="$1"
    local out="$RESULTS_DIR/${fault}_${STAMP}.csv"
    log "=== fault: $fault (recovery=$RECOVERY, n=$ITERS) ==="
    if [ "$fault" = "retry_proc_kill" ]; then
        # server dies each trial -> restart per iteration, append rows
        local combined="$out" i first=1
        for i in $(seq 1 "$ITERS"); do
            start_server
            local tmp="$RESULTS_DIR/.pk_${i}.csv"
            ./probe_client -s "$SERVER_IP" -d "$CLIENT_DEV" -i "$IB_PORT" -g "$GID_INDEX" \
                -p "$CTRL_PORT" -f "$fault" -r "$RECOVERY" -n 1 -o "$tmp" \
                -C "$CLIENT_CPU" -S "$MSG_SIZE" -k "$COUNTER" -t "$DETECT_TIMEOUT_MS" || true
            if [ -f "$tmp" ]; then
                if [ $first -eq 1 ]; then cp "$tmp" "$combined"; first=0
                else tail -n +2 "$tmp" >> "$combined"; fi
                rm -f "$tmp"
            fi
        done
    else
        start_server
        ./probe_client -s "$SERVER_IP" -d "$CLIENT_DEV" -i "$IB_PORT" -g "$GID_INDEX" \
            -p "$CTRL_PORT" -f "$fault" -r "$RECOVERY" -n "$ITERS" -o "$out" \
            -C "$CLIENT_CPU" -S "$MSG_SIZE" -k "$COUNTER" -t "$DETECT_TIMEOUT_MS"
    fi
    log "wrote $out"
}

trap stop_server EXIT
for f in "${FAULTS_TO_RUN[@]}"; do run_one "$f"; done
stop_server

log "analysis:"
if command -v python3 >/dev/null; then
    python3 analyze.py "$RESULTS_DIR"/*_"${STAMP}".csv
fi
log "done. results in $RESULTS_DIR (stamp $STAMP)"
