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
#
# Exit status: 0 only if every fault's client exited 0 AND its CSV has exactly
# ITERS data rows; 1 otherwise (the failing faults are listed at the end).
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

# A real (non-dry-run) retry_link_down toggles the responder's RoCE netdev.
LINK_REAL=0
for f in "${FAULTS_TO_RUN[@]}"; do
    if [ "$f" = retry_link_down ] && [ "$PROBE_LINK_DRYRUN" != 1 ]; then LINK_REAL=1; fi
done
[ "$LINK_REAL" = 1 ] && log "NOTE: retry_link_down will really toggle $SERVER_IFACE on $SERVER_SSH"

# --- process control on the responder ---
# `pkill -x` matches the process NAME exactly. Never `pkill -f probe_server`: the
# remote shell running that very command has "probe_server" in its command line
# and would kill itself (ssh exit 255, and nothing after it runs).
kill_server() {
    ssh -n "$SERVER_SSH" 'pkill -x probe_server 2>/dev/null
        for _ in $(seq 1 30); do pgrep -x probe_server >/dev/null || exit 0; sleep 0.1; done
        pkill -KILL -x probe_server 2>/dev/null; sleep 0.3
        ! pgrep -x probe_server >/dev/null'
}
start_server() {
    kill_server || { log "ERROR: could not stop a running probe_server"; return 1; }
    # ssh -f detaches after auth; the remote process survives this shell.
    ssh -f "$SERVER_SSH" "cd $SERVER_DIR && PROBE_LINK_DRYRUN=$PROBE_LINK_DRYRUN PROBE_TEST_NO_PROBE_REPLY=${PROBE_TEST_NO_PROBE_REPLY:-0} \
        timeout $SERVER_TIMEOUT ./probe_server \
        -d $SERVER_DEV -i $IB_PORT -g $SERVER_GID_INDEX -p $CTRL_PORT -C $SERVER_CPU \
        -I $SERVER_IFACE > $SERVER_LOG 2>&1"
    for _ in $(seq 1 20); do
        if ssh -n "$SERVER_SSH" "ss -tln | grep -q ':$CTRL_PORT '"; then return 0; fi
        sleep 0.5
    done
    log "ERROR: server did not start; log:"; ssh -n "$SERVER_SSH" "cat $SERVER_LOG" >&2 || true
    return 1
}
stop_server() { kill_server >/dev/null 2>&1 || log "WARNING: could not confirm probe_server stopped"; }

# best effort: if the responder's RoCE netdev is admin-down, bring it back up
restore_link() {
    ssh -n "$SERVER_SSH" "PATH=\$PATH:/usr/sbin:/sbin
        st=\$(ip -o link show dev $SERVER_IFACE 2>/dev/null) || exit 0
        echo \"\$st\" | grep -Eq '<([^>]*,)?UP[,>]' && exit 0
        echo 'run.sh: $SERVER_IFACE is down, restoring' >&2
        sudo -n ip link set dev $SERVER_IFACE up" \
    || log "WARNING: could not verify/restore $SERVER_IFACE on $SERVER_SSH - check it manually"
}

on_exit() {
    local rc=$?
    stop_server
    if [ "$LINK_REAL" = 1 ]; then restore_link; fi
    rm -f "$RESULTS_DIR"/.pk_*.csv
    exit "$rc"
}
trap on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP

# --- build both sides ---
log "building client (this node)"
make -s
log "syncing source + building server ($SERVER_SSH)"
# sync source (never the binaries or results) so the responder rebuilds from the
# same code; nccl-integration/ is not part of this build and is left alone.
rsync -a --exclude='results/*' --exclude='/probe_client' --exclude='/probe_server' \
      --exclude='/nccl-integration/' \
      "$SCRIPT_DIR"/ "$SERVER_SSH:$SERVER_DIR"/ >/dev/null
ssh -n "$SERVER_SSH" "cd $SERVER_DIR && make -s"

# --- resolve GID indices (per node: they can differ and can move) ---
# prints the index of the RoCE v2, IPv4-mapped GID of device $1 port $2
GID_PROBE='d=/sys/class/infiniband/$1/ports/$2
for g in $(ls "$d/gids" | sort -n); do
  [ "$(cat "$d/gid_attrs/types/$g" 2>/dev/null)" = "RoCE v2" ] || continue
  case "$(cat "$d/gids/$g")" in 0000:0000:0000:0000:0000:ffff:*) echo "$g"; exit 0;; esac
done
exit 1'
if [ "$CLIENT_GID_INDEX" = auto ]; then
    CLIENT_GID_INDEX=$(bash -s -- "$CLIENT_DEV" "$IB_PORT" <<< "$GID_PROBE") \
        || { log "ERROR: no RoCE v2 IPv4 GID on $CLIENT_DEV port $IB_PORT"; exit 1; }
fi
if [ "$SERVER_GID_INDEX" = auto ]; then
    SERVER_GID_INDEX=$(ssh "$SERVER_SSH" bash -s -- "$SERVER_DEV" "$IB_PORT" <<< "$GID_PROBE") \
        || { log "ERROR: no RoCE v2 IPv4 GID on $SERVER_SSH $SERVER_DEV port $IB_PORT"; exit 1; }
fi
log "GID index: client $CLIENT_DEV=$CLIENT_GID_INDEX, server $SERVER_DEV=$SERVER_GID_INDEX"

data_rows() {   # data rows in a CSV (header excluded); 0 if missing
    local n=0
    [ -f "$1" ] && n=$(( $(wc -l < "$1") - 1 ))
    [ "$n" -lt 0 ] && n=0
    echo "$n"
}

client() {      # client <fault> <iters> <out.csv>
    ./probe_client -s "$SERVER_IP" -d "$CLIENT_DEV" -i "$IB_PORT" -g "$CLIENT_GID_INDEX" \
        -p "$CTRL_PORT" -f "$1" -r "$RECOVERY" -n "$2" -o "$3" \
        -C "$CLIENT_CPU" -S "$MSG_SIZE" -k "$COUNTER" -t "$DETECT_TIMEOUT_MS"
}

# NB: called from an `if`, so errexit is off inside: every step is checked explicitly.
run_one() {
    local fault="$1"
    local out="$RESULTS_DIR/${fault}_${STAMP}.csv"
    local rc=0 crc
    log "=== fault: $fault (recovery=$RECOVERY, n=$ITERS) ==="
    if [ "$fault" = "retry_proc_kill" ] || [ "$fault" = "retry_proc_sigkill" ]; then
        # server dies each trial -> restart per iteration, append rows
        local i first=1 fails=0 tmp
        rm -f "$out"
        for i in $(seq 1 "$ITERS"); do
            tmp="$RESULTS_DIR/.pk_${i}.csv"
            rm -f "$tmp"
            if ! start_server; then
                fails=$((fails + 1)); log "ERROR: $fault trial $i: server did not start"; continue
            fi
            crc=0
            client "$fault" 1 "$tmp" || crc=$?
            [ "$crc" -eq 0 ] || { fails=$((fails + 1)); log "ERROR: $fault trial $i: client exit $crc"; }
            if [ -f "$tmp" ]; then
                if [ $first -eq 1 ]; then cp "$tmp" "$out"; first=0
                else tail -n +2 "$tmp" >> "$out"; fi
                rm -f "$tmp"
            fi
        done
        [ "$fails" -eq 0 ] || { log "ERROR: $fault: $fails/$ITERS trials failed"; rc=1; }
    else
        if start_server; then
            crc=0
            client "$fault" "$ITERS" "$out" || crc=$?
            if [ "$crc" -ne 0 ]; then
                rc=1
                log "ERROR: $fault: client exit $crc; responder log tail:"
                ssh -n "$SERVER_SSH" "tail -n 8 $SERVER_LOG" >&2 || true
            fi
        else
            rc=1
        fi
    fi
    local rows
    rows=$(data_rows "$out")
    if [ "$rows" -ne "$ITERS" ]; then
        log "ERROR: $fault: $rows data rows in $out, expected $ITERS"
        rc=1
    fi
    log "wrote $out ($rows rows)"
    return "$rc"
}

FAILED=()
for f in "${FAULTS_TO_RUN[@]}"; do
    if ! run_one "$f"; then FAILED+=("$f"); fi
done
stop_server

log "analysis:"
shopt -s nullglob
CSVS=("$RESULTS_DIR"/*_"${STAMP}".csv)
shopt -u nullglob
if command -v python3 >/dev/null && [ ${#CSVS[@]} -gt 0 ]; then
    python3 analyze.py "${CSVS[@]}" || { log "ERROR: analyze.py failed"; FAILED+=("analyze"); }
fi

if [ ${#FAILED[@]} -gt 0 ]; then
    log "FAILED: ${FAILED[*]} (stamp $STAMP)"
    exit 1
fi
log "done. results in $RESULTS_DIR (stamp $STAMP)"
