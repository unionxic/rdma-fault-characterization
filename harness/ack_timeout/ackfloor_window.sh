#!/usr/bin/env bash
# ackfloor_window.sh - run ONE command with the ConnectX firmware ACK-timeout floor disabled
# (ROCE_ACCL.min_ack_timeout_limit_disabled = 1) on rain's 17:00.1 (mlx5_1) ONLY, and restore
# the register on every exit path.
#
#   ackfloor_window.sh [-t tag] -- <command> [args...]
#
# Contract:
#   * must itself run under ../gpu-initiated/common/cluster_run.sh (refuses if the cluster lock
#     is not held by someone);
#   * (a) records the full ROCE_ACCL state before (all 19 fields) -> window/<stamp>_before.txt;
#     refuses unless min_ack_timeout_limit_disabled is 0 before;
#   * (b) sets ONLY min_ack_timeout_limit_disabled = 1 (its field_select = 1, every other
#     field_select = 0) and verifies by re-reading that it is 1 and every other field is unchanged;
#   * (c) runs the command in its own process group (so it can be stopped as a whole);
#   * (d) EXIT/INT/TERM/HUP trap: stops the command if still running, writes back the recorded
#     value, re-reads and verifies that every field equals the before state (retries 3x), logs
#     the dumps; exit status = the command's, or 70 if the restore could not be verified;
#   * a detached guardian (ackfloor_guardian.sh) restores the register if this script dies
#     without restoring (SIGKILL), identified by /proc/<pid>/stat start time + a done marker.
# Also reads (never writes) ROCE_ACCL of the other function 17:00.0 before/after, to show the
# setting's scope.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
DEV=17:00.1
OTHER=17:00.0
REG=ROCE_ACCL
FIELD=min_ack_timeout_limit_disabled
RESDIR=${ACKFLOOR_DIR:-$HERE/results/20260925/window}
LOG=${ACKFLOOR_LOG:-$HERE/results/20260925/window.log}
LOCK=${CLUSTER_LOCK:-/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad/cluster.lock.v2}
TAG=win
while [ $# -gt 0 ]; do
  case "$1" in
    -t) TAG=$2; shift 2 ;;
    --) shift; break ;;
    *) break ;;
  esac
done
[ $# -gt 0 ] || { echo "usage: $0 [-t tag] -- <command> [args...]" >&2; exit 2; }
mkdir -p "$RESDIR"
STAMP=$(date +%Y%m%d_%H%M%S)_$$
PFX=$RESDIR/${STAMP}_${TAG}

log() { local m; m="$(date '+%F %T.%3N') [$TAG pid=$$ stamp=$STAMP] $*"; echo "$m" >> "$LOG"; echo "$m" >&2; }
getreg() { sudo -n mlxreg -d "$1" --reg_name "$REG" --get 2>&1; }
# "name=value" per register field, in register order
fields() { awk -F'|' 'NF==2 && $1 !~ /Field Name/ { n=$1; v=$2; gsub(/[ \t]/,"",n); gsub(/[ \t]/,"",v); if (n!="") print n"="v }'; }
fieldval() { awk -F= -v f="$1" '$1==f {print $2}'; }
SEL="roce_adp_retrans_field_select=0,roce_tx_window_field_select=0,roce_slow_restart_field_select=0,roce_slow_restart_idle_field_select=0,${FIELD}_field_select=1,adaptive_routing_forced_en_field_select=0,selective_repeat_forced_en_field_select=0,dc_half_handshake_en_field_select=0,ack_dscp_force_field_select=0"
setval() { sudo -n mlxreg -d "$DEV" --reg_name "$REG" --yes --set "$SEL,$FIELD=$1" 2>&1; }

# ---- 0. preconditions ----
if flock -n "$LOCK" true 2>/dev/null; then
  log "REFUSE: cluster lock $LOCK is not held; run me under cluster_run.sh"; exit 64
fi
B_RAW=$(getreg "$DEV") || { log "REFUSE: GET failed: $B_RAW"; exit 65; }
printf '%s\n' "$B_RAW" > "${PFX}_before.txt"
BEFORE=$(printf '%s\n' "$B_RAW" | fields)
NF_BEFORE=$(printf '%s\n' "$BEFORE" | grep -c '=')
BVAL=$(printf '%s\n' "$BEFORE" | fieldval "$FIELD")
if [ "$NF_BEFORE" -ne 19 ] || [ -z "$BVAL" ]; then
  log "REFUSE: could not parse the before state ($NF_BEFORE fields)"; exit 65
fi
if [ "$BVAL" != 0x00000000 ]; then
  log "REFUSE: $FIELD is $BVAL before the window (expected 0x00000000: another window active or register left changed)"; exit 66
fi
getreg "$OTHER" > "${PFX}_before_${OTHER}.txt"
log "BEFORE $DEV: $(printf '%s\n' "$BEFORE" | grep -v field_select | tr '\n' ' ')"

# compare the current state with BEFORE; prints differing fields; 0 if identical
compare() {
  local now diff
  now=$(printf '%s\n' "$1" | fields)
  diff=$(diff <(printf '%s\n' "$BEFORE") <(printf '%s\n' "$now") | grep '^[<>]' | tr '\n' ' ')
  [ "$(printf '%s\n' "$now" | grep -c '=')" -eq 19 ] || { echo "parse: $(printf '%s\n' "$now" | grep -c '=') fields"; return 1; }
  [ -z "$diff" ] || { echo "$diff"; return 1; }
  return 0
}

CHILD=""
DONE_MARK="${PFX}.restored"
restore() {
  local rc=$? ok=0 out a_raw d
  trap - EXIT
  trap '' INT TERM HUP     # the restore itself must not be interrupted
  if [ -n "$CHILD" ] && kill -0 "$CHILD" 2>/dev/null; then
    log "stopping command process group $CHILD (TERM)"
    kill -TERM -- "-$CHILD" 2>/dev/null
  fi
  for attempt in 1 2 3; do
    out=$(setval "$BVAL")
    a_raw=$(getreg "$DEV")
    printf '%s\n' "$a_raw" > "${PFX}_after_restore.txt"
    if d=$(compare "$a_raw"); then
      ok=1; log "RESTORED ($FIELD=$BVAL written, attempt $attempt): all 19 fields equal the before state"
      break
    fi
    log "restore attempt $attempt NOT verified: diff: $d; mlxreg: $(printf '%s' "$out" | tr '\n' ' ' | tail -c 300)"
    sleep 1
  done
  getreg "$OTHER" > "${PFX}_after_${OTHER}.txt"
  if cmp -s <(fields < "${PFX}_before_${OTHER}.txt") <(fields < "${PFX}_after_${OTHER}.txt"); then
    log "$OTHER ROCE_ACCL unchanged (read-only check)"
  else
    log "WARNING: $OTHER ROCE_ACCL differs from its before state"
  fi
  if [ -n "$CHILD" ] && kill -0 "$CHILD" 2>/dev/null; then
    sleep 2; kill -KILL -- "-$CHILD" 2>/dev/null; log "command process group $CHILD killed (KILL)"
  fi
  if [ "$ok" = 1 ]; then
    touch "$DONE_MARK"
    log "window end rc=$rc"
    exit "$rc"
  fi
  log "RESTORE FAILED: register may be left changed; guardian will retry"
  exit 70
}
trap restore EXIT
trap 'log "caught SIGINT"; exit 130' INT
trap 'log "caught SIGTERM"; exit 143' TERM
trap 'log "caught SIGHUP"; exit 129' HUP

# ---- guardian: covers SIGKILL of this script ----
WSTART=$(awk '{print $22}' /proc/$$/stat)
setsid bash "$HERE/ackfloor_guardian.sh" "$$" "$WSTART" "$BVAL" "$DONE_MARK" "$LOG" "$TAG" "$STAMP" \
  </dev/null >/dev/null 2>&1 &
log "guardian started (pid $!) for window pid $$ start $WSTART"

# ---- (b) set only the one field ----
out=$(setval 1)
S_RAW=$(getreg "$DEV")
printf '%s\n' "$S_RAW" > "${PFX}_after_set.txt"
SVAL=$(printf '%s\n' "$S_RAW" | fields | fieldval "$FIELD")
# every other field must be unchanged
OTHERS_DIFF=$(diff <(printf '%s\n' "$BEFORE" | grep -v "^$FIELD=") <(printf '%s\n' "$S_RAW" | fields | grep -v "^$FIELD=") | grep '^[<>]' | tr '\n' ' ')
if [ "$SVAL" != 0x00000001 ] || [ -n "$OTHERS_DIFF" ]; then
  log "SET NOT VERIFIED: $FIELD=$SVAL other diffs: '$OTHERS_DIFF'; mlxreg: $(printf '%s' "$out" | tr '\n' ' ' | tail -c 300)"
  exit 67
fi
log "SET $FIELD=1 verified (other 18 fields unchanged); running: $*"

# ---- (c) the command, in its own process group ----
setsid "$@" &
CHILD=$!
wait "$CHILD"
rc=$?
log "command exited rc=$rc"
exit "$rc"
