#!/usr/bin/env bash
#
# run_cqe_seq.sh - Q1 runner (CPU verbs, no GPU): the ordered CQE sequence after a fault.
#
#   ./run_cqe_seq.sh build              build cqe_seq_client here (rain) and the UNCHANGED
#                                       harness probe_server on the responder (sunny).
#                                       No RDMA traffic: no cluster lock needed.
#   ./run_cqe_seq.sh run <fault> [...]  run the matrix for these faults. Uses the shared
#                                       RoCE link, so ALWAYS call it through cluster_run.sh:
#       ../common/cluster_run.sh -t cqe_seq_rnr -- ./run_cqe_seq.sh run rnr
#   ./run_cqe_seq.sh analyze            python3 analyze_cqe_seq.py over results/
#
# Faults: local_qp_err rem_access rem_inv_req rnr retry_server_qp_err retry_proc_kill
# (never link_down). retry_proc_kill restarts the server for every trial.
#
# Environment (default):
#   TRIALS (5)  NS ("1 4 16 64")  SIGS ("all last")  POSS ("first middle"; "last" = k = N-1)
#   QUIET_MS (500)  FIRST_ERR_MS (10000)
#   WQE_BYTES (4096; local_qp_err: LOCAL_WQE_BYTES = 4194304, so WQEs are still
#              outstanding when the QP is forced to ERR - the harness's MSG_SIZE)
#   CLIENT_CPU (2)  SERVER_CPU (2)  CTRL_PORT (18591)  STAMP (now)  CQE_TAG (run tag in file names; default STAMP)
# Output (results/): raw_<fault>_<tag>.csv (one row per CQE), trials_<fault>_<tag>.csv
# (one row per trial), log_<fault>_<tag>.txt (client trace + responder log tail).
#
# Exit status: 0 only if every client exited 0; 1 otherwise.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
HARNESS_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

# --- cluster (see ../../config.sh) ---
SERVER_IP="${SERVER_IP:-192.0.2.194}"            # sunny mgmt IP: TCP control channel
SERVER_SSH="${SERVER_SSH:-unionxic@192.0.2.194}"
SERVER_DEV="${SERVER_DEV:-mlx5_0}"
CLIENT_DEV="${CLIENT_DEV:-mlx5_1}"
IB_PORT="${IB_PORT:-1}"
SERVER_HARNESS="${SERVER_HARNESS:-rdma-error/harness}"   # relative to the remote home
SERVER_DIR="$SERVER_HARNESS/gpu-initiated/cqe_seq"
SERVER_LOG="${SERVER_LOG:-/tmp/cqe_seq_srv.log}"
CTRL_PORT="${CTRL_PORT:-18591}"

# --- matrix ---
TRIALS="${TRIALS:-5}"
NS="${NS:-1 4 16 64}"
SIGS="${SIGS:-all last}"
POSS="${POSS:-first middle}"
QUIET_MS="${QUIET_MS:-500}"
FIRST_ERR_MS="${FIRST_ERR_MS:-10000}"
WQE_BYTES="${WQE_BYTES:-4096}"
LOCAL_WQE_BYTES="${LOCAL_WQE_BYTES:-4194304}"
CLIENT_CPU="${CLIENT_CPU:-2}"
SERVER_CPU="${SERVER_CPU:-2}"
STAMP="${STAMP:-$(date +%Y%m%d_%H%M%S)}"
CQE_TAG="${CQE_TAG:-$STAMP}"
RESULTS_DIR="${RESULTS_DIR:-$SCRIPT_DIR/results}"

log() { echo "[cqe_seq] $(date '+%H:%M:%S') $*" >&2; }
csv() { echo "$*" | tr ' ' ','; }

# ---------------- build ----------------
do_build() {
    log "building cqe_seq_client (this node)"
    make -s cqe_seq_client
    # The responder runs the harness probe_server UNCHANGED. Build it from the
    # responder's own harness checkout, after checking that it is byte-identical to
    # ours (this script never writes outside gpu-initiated/cqe_seq on either node).
    local files="common/probe.c common/probe.h server/probe_server.c"
    local here there
    here=$(cd "$HARNESS_DIR" && md5sum $files)
    there=$(ssh -n "$SERVER_SSH" "cd $SERVER_HARNESS && md5sum $files")
    if [ "$here" != "$there" ]; then
        log "ERROR: the responder's harness sources differ from this node's:"
        diff <(echo "$here") <(echo "$there") >&2 || true
        log "sync them first (harness/run.sh rsyncs the harness), then rebuild"
        return 1
    fi
    ssh -n "$SERVER_SSH" "mkdir -p $SERVER_DIR"
    rsync -a --exclude='results/' --exclude='/cqe_seq_client' --exclude='/probe_server' \
          "$SCRIPT_DIR"/ "$SERVER_SSH:$SERVER_DIR"/
    ssh -n "$SERVER_SSH" "cd $SERVER_DIR && make -s probe_server && ls -l probe_server" >&2
    log "build ok (probe_server sources identical on both nodes: $(echo "$here" | awk '{print $1}' | tr '\n' ' '))"
}

# ---------------- responder process control ----------------
# `pkill -x` matches the exact process name; nobody else on sunny runs probe_server.
# Never `pkill -f`: it matches the remote shell's own command line.
kill_server() {
    ssh -n "$SERVER_SSH" 'pkill -x probe_server 2>/dev/null
        for _ in $(seq 1 30); do pgrep -x probe_server >/dev/null || exit 0; sleep 0.1; done
        pkill -KILL -x probe_server 2>/dev/null; sleep 0.3
        ! pgrep -x probe_server >/dev/null'
}
start_server() {    # start_server <lifetime_s>
    kill_server || { log "ERROR: could not stop a running probe_server"; return 1; }
    # PROBE_LINK_DRYRUN=1: belt and braces, the server could never touch the link
    # even if it were asked for retry_link_down (this client never asks).
    ssh -f "$SERVER_SSH" "cd $SERVER_DIR && PROBE_LINK_DRYRUN=1 timeout $1 ./probe_server \
        -d $SERVER_DEV -i $IB_PORT -g $SERVER_GID -p $CTRL_PORT -C $SERVER_CPU > $SERVER_LOG 2>&1"
    for _ in $(seq 1 20); do
        if ssh -n "$SERVER_SSH" "ss -tln | grep -q ':$CTRL_PORT '"; then return 0; fi
        sleep 0.5
    done
    log "ERROR: server did not start; log:"; ssh -n "$SERVER_SSH" "cat $SERVER_LOG" >&2 || true
    return 1
}
stop_server() { kill_server >/dev/null 2>&1 || log "WARNING: could not confirm probe_server stopped"; }

# prints the index of the RoCE v2, IPv4-mapped GID of device $1 port $2 (from ../../run.sh)
GID_PROBE='d=/sys/class/infiniband/$1/ports/$2
for g in $(ls "$d/gids" | sort -n); do
  [ "$(cat "$d/gid_attrs/types/$g" 2>/dev/null)" = "RoCE v2" ] || continue
  case "$(cat "$d/gids/$g")" in 0000:0000:0000:0000:0000:ffff:*) echo "$g"; exit 0;; esac
done
exit 1'

client() {  # client <timeout_s> <fault> <raw> <trials> <log> [extra args...]
    local to=$1 fault=$2 raw=$3 tr=$4 lg=$5; shift 5
    local rc=0
    timeout "$to" ./cqe_seq_client -s "$SERVER_IP" -d "$CLIENT_DEV" -i "$IB_PORT" -g "$CLIENT_GID" \
        -p "$CTRL_PORT" -f "$fault" -o "$raw" -O "$tr" -q "$QUIET_MS" -t "$FIRST_ERR_MS" \
        -R "$CQE_TAG" -C "$CLIENT_CPU" "$@" 2>&1 | tee -a "$lg" >&2 || rc=${PIPESTATUS[0]}
    return "$rc"
}

run_fault() {
    local fault=$1
    local raw="$RESULTS_DIR/raw_${fault}_${CQE_TAG}.csv" tr="$RESULTS_DIR/trials_${fault}_${CQE_TAG}.csv"
    local lg="$RESULTS_DIR/log_${fault}_${CQE_TAG}.txt"
    local bytes=$WQE_BYTES
    [ "$fault" = local_qp_err ] && bytes=$LOCAL_WQE_BYTES
    local nposs=1
    case "$fault" in rem_access|rem_inv_req|rnr) nposs=$(echo $POSS | wc -w) ;; esac
    local cells=$(( $(echo $NS | wc -w) * $(echo $SIGS | wc -w) * nposs ))
    local per_trial=$(( FIRST_ERR_MS / 1000 + QUIET_MS / 1000 + 6 ))
    log "=== $fault: N={$NS} sig={$SIGS} pos={$([ $nposs -gt 1 ] && echo $POSS || echo none)} x $TRIALS trials, wqe $bytes B ==="
    local rc=0
    if [ "$fault" = retry_proc_kill ]; then
        # the server exits on GO: one server + one client per trial
        local uid=0 n s t
        for n in $NS; do for s in $SIGS; do for t in $(seq 0 $((TRIALS - 1))); do
            if ! start_server 60; then rc=1; break 3; fi
            client 40 "$fault" "$raw" "$tr" "$lg" -S "$bytes" -N "$n" -m "$s" -n 1 -T "$uid" -b "$t" \
                || { rc=1; log "ERROR: $fault N=$n $s trial $t: client failed"; }
            uid=$((uid + 1))
            stop_server
        done; done; done
    else
        local life=$(( 120 + cells * TRIALS * per_trial ))
        if start_server $((life + 60)); then
            client "$life" "$fault" "$raw" "$tr" "$lg" -S "$bytes" -N "$(csv $NS)" -m "$(csv $SIGS)" \
                -k "$(csv $POSS)" -n "$TRIALS" || { rc=1; log "ERROR: $fault: client failed"; }
        else
            rc=1
        fi
        { echo "--- responder log tail ($SERVER_LOG) ---"; ssh -n "$SERVER_SSH" "tail -n 20 $SERVER_LOG"; } \
            >> "$lg" 2>&1 || true
        stop_server
    fi
    log "$fault: $(( $(wc -l < "$tr" 2>/dev/null || echo 1) - 1 )) trial rows in $tr"
    return "$rc"
}

do_run() {
    [ $# -gt 0 ] || { log "usage: $0 run <fault> [...]"; return 2; }
    local f
    for f in "$@"; do
        case "$f" in
            local_qp_err|rem_access|rem_inv_req|rnr|retry_server_qp_err|retry_proc_kill) ;;
            *) log "ERROR: unsupported fault '$f'"; return 2 ;;
        esac
    done
    [ -x ./cqe_seq_client ] || { log "ERROR: run '$0 build' first"; return 1; }
    ssh -n "$SERVER_SSH" "test -x $SERVER_DIR/probe_server" || { log "ERROR: run '$0 build' first"; return 1; }
    CLIENT_GID=$(bash -s -- "$CLIENT_DEV" "$IB_PORT" <<< "$GID_PROBE") \
        || { log "ERROR: no RoCE v2 IPv4 GID on $CLIENT_DEV"; return 1; }
    SERVER_GID=$(ssh "$SERVER_SSH" bash -s -- "$SERVER_DEV" "$IB_PORT" <<< "$GID_PROBE") \
        || { log "ERROR: no RoCE v2 IPv4 GID on $SERVER_SSH $SERVER_DEV"; return 1; }
    log "GID index: client $CLIENT_DEV=$CLIENT_GID, server $SERVER_DEV=$SERVER_GID; tag $CQE_TAG"
    mkdir -p "$RESULTS_DIR"
    trap 'stop_server; pkill -x cqe_seq_client 2>/dev/null || true' EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    local failed=()
    for f in "$@"; do run_fault "$f" || failed+=("$f"); done
    stop_server
    if pgrep -x cqe_seq_client >/dev/null; then log "WARNING: a cqe_seq_client is still running"; fi
    if [ ${#failed[@]} -gt 0 ]; then log "FAILED: ${failed[*]} (tag $CQE_TAG)"; return 1; fi
    log "done (tag $CQE_TAG)"
}

cmd="${1:-}"; shift || true
case "$cmd" in
    build)   do_build ;;
    run)     do_run "$@" ;;
    analyze) python3 "$SCRIPT_DIR/analyze_cqe_seq.py" "$RESULTS_DIR" ;;
    *) sed -n '3,30p' "$0" >&2; exit 2 ;;
esac
