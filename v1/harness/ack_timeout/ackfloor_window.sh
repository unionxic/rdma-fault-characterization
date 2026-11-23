#!/usr/bin/env bash
# ackfloor_window.sh - run ONE command with the ConnectX firmware ACK-timeout floor disabled
# (ROCE_ACCL.min_ack_timeout_limit_disabled = 1) on rain's 17:00.1 (mlx5_1) ONLY, and restore
# the register on every exit path.
#
#   ackfloor_window.sh [-t tag] -- <command> [args...]
#
# Contract:
#   * must itself run under ../gpu-initiated/common/cluster_run.sh, and refuses (fail closed,
#     before any register access) unless the cluster lock is verifiably held by that process:
#       1. the nearest ancestor process runs cluster_run.sh;
#       2. that process has fd 9 open on an existing, not deleted, regular file;
#       3. /proc/<it>/fdinfo/9 shows a FLOCK WRITE lock on that file's inode, and a
#          non-blocking flock(1) on the file fails with the conflict code (any other outcome,
#          including a flock(1) error, refuses);
#       4. the script it runs is this repository's ../gpu-initiated/common/cluster_run.sh;
#       5. the locked file is the shared cluster lock as that script defines it (its SCRATCH/LOCK
#          lines evaluated with CLUSTER_LOCK unset), so a cluster_run.sh pointed at a private
#          lock file (CLUSTER_LOCK=...) is refused too.
#     ACKFLOOR_CHECK_ONLY=1: run these checks, print the result and exit (0 = would proceed)
#     without reading or writing the register (used by scripts/test_lockcheck.sh);
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
CR_REPO=$HERE/../gpu-initiated/common/cluster_run.sh
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

# ---- 0. preconditions: the cluster lock must be verifiably held by our cluster_run.sh ----
# prints one line; returns 0 only if every check passes (sets LOCK and CR_PID)
LOCK=""; CR_PID=""
verify_lock() {
  local pid=$$ ppid cmd arg script="" cwd lk ino fdino rc canon crreal
  # 1. nearest ancestor running cluster_run.sh
  while :; do
    ppid=$(awk '{print $4}' "/proc/$pid/stat" 2>/dev/null)
    [ -n "$ppid" ] && [ "$ppid" -gt 1 ] 2>/dev/null || break
    while IFS= read -r -d '' arg; do
      case "$arg" in */cluster_run.sh|cluster_run.sh) script=$arg; break ;; esac
    done < "/proc/$ppid/cmdline" 2>/dev/null
    [ -n "$script" ] && { CR_PID=$ppid; break; }
    pid=$ppid
  done
  [ -n "$CR_PID" ] || { echo "check 1: no cluster_run.sh among the ancestors of pid $$"; return 1; }
  # 2. its fd 9: an existing, not deleted, regular file
  lk=$(readlink "/proc/$CR_PID/fd/9" 2>/dev/null) || { echo "check 2: cluster_run.sh (pid $CR_PID) has no fd 9"; return 1; }
  case "$lk" in *" (deleted)") echo "check 2: fd 9 of pid $CR_PID points to a deleted file: $lk"; return 1 ;; esac
  [ -f "$lk" ] || { echo "check 2: fd 9 of pid $CR_PID is not an existing regular file: $lk"; return 1; }
  fdino=$(stat -L -c '%d:%i' "/proc/$CR_PID/fd/9" 2>/dev/null)
  [ -n "$fdino" ] && [ "$fdino" = "$(stat -c '%d:%i' "$lk" 2>/dev/null)" ] || { echo "check 2: fd 9 of pid $CR_PID is not the file at $lk"; return 1; }
  # 3. the lock is held on that open file (fdinfo) and a non-blocking attempt conflicts
  ino=${fdino#*:}
  grep -Eq "^lock:.*FLOCK +ADVISORY +WRITE +[0-9]+ +[0-9a-f]+:[0-9a-f]+:$ino " "/proc/$CR_PID/fdinfo/9" 2>/dev/null \
    || { echo "check 3: no FLOCK WRITE lock on fd 9 of pid $CR_PID ($lk): not held"; return 1; }
  flock -n -E 75 "$lk" true 2>/dev/null; rc=$?
  [ "$rc" = 75 ] || { echo "check 3: non-blocking flock on $lk returned $rc (want 75 = held)"; return 1; }
  # 4. the script is this repository's cluster_run.sh
  cwd=$(readlink "/proc/$CR_PID/cwd" 2>/dev/null)
  case "$script" in /*) ;; *) script=$cwd/$script ;; esac
  crreal=$(realpath -e "$CR_REPO" 2>/dev/null)
  [ -n "$crreal" ] && [ "$(realpath -e "$script" 2>/dev/null)" = "$crreal" ] \
    || { echo "check 4: ancestor runs $script, not $CR_REPO"; return 1; }
  # 5. the locked file is the shared cluster lock as cluster_run.sh itself defines it
  canon=$(env -u CLUSTER_LOCK bash -c "$(grep -E '^(SCRATCH|LOCK)=' "$crreal")"'; printf %s "$LOCK"' 2>/dev/null)
  [ -n "$canon" ] && [ "$(realpath -e "$lk")" = "$(realpath -e "$canon" 2>/dev/null)" ] \
    || { echo "check 5: held lock $lk is not the shared cluster lock ${canon:-<undefined>}"; return 1; }
  LOCK=$lk
  echo "lock verified: $lk held by cluster_run.sh pid $CR_PID (fdinfo FLOCK WRITE, flock -n -> 75)"
  return 0
}
verify_lock > "${PFX}_lockcheck.txt" 2>&1; VRC=$?     # in this shell: sets LOCK and CR_PID
VMSG=$(cat "${PFX}_lockcheck.txt" 2>/dev/null)
if [ "$VRC" != 0 ] || [ -z "$LOCK" ]; then
  log "REFUSE: ${VMSG:-lock check failed}"; exit 64
fi
log "$VMSG"
if [ "${ACKFLOOR_CHECK_ONLY:-0}" = 1 ]; then
  log "CHECK_ONLY: checks passed; exiting without touching the register"; exit 0
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
