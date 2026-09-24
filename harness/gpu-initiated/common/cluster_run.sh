#!/usr/bin/env bash
# cluster_run.sh - run one cluster experiment under the shared lock, on an idle link.
#
# usage: cluster_run.sh [-w max_wait_s] [-t tag] -- <command> [args...]
#
# The rain<->sunny RoCE link is shared with the user's NVMe-oF storage (sunny mounts
# rain's namespaces over RDMA) and with gdsio benchmarks run from sunny. This wrapper
#   1. takes an exclusive lock, so only one experiment uses the cluster at a time;
#   2. waits until sunny runs no gdsio / mix_threads.sh and rain's RoCE port has carried
#      less than 500 Mb/s for 3 consecutive 10 s samples;
#   3. runs the command and logs the link state before and after it.
# The command must bound its own run time; the lock is held until it returns.
# Exit status: the command's, or 75 if the lock or an idle link was not obtained in time.
set -u

SCRATCH=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
# v2: the first lock file stays held forever by a process that inherited its fd (a
# mooncake_client restarted from inside a locked run, 2026-09-24). The command below now
# runs with fd 9 closed, so nothing it starts can inherit the lock.
LOCK=${CLUSTER_LOCK:-$SCRATCH/cluster.lock.v2}
LOG=${CLUSTER_LOG:-$SCRATCH/cluster_run.log}
PORT=/sys/class/infiniband/mlx5_1/ports/1/counters
SUNNY_MGMT=${SUNNY_MGMT:-unionxic@192.0.2.194}
MAXWAIT=7200
TAG=run

while [ $# -gt 0 ]; do
  case "$1" in
    -w) MAXWAIT=$2; shift 2 ;;
    -t) TAG=$2; shift 2 ;;
    --) shift; break ;;
    *) break ;;
  esac
done
[ $# -gt 0 ] || { echo "usage: $0 [-w max_wait_s] [-t tag] -- <command> [args...]" >&2; exit 2; }

log() { echo "$(date '+%F %T') [$TAG] $*" | tee -a "$LOG" >&2; }

# 1 if sunny runs a storage benchmark (or cannot be asked), else 0.
sunny_busy() {
  ssh -n -o ConnectTimeout=5 -o BatchMode=yes "$SUNNY_MGMT" \
    'if pgrep -x gdsio >/dev/null || pgrep -f "[m]ix_threads.sh" >/dev/null; then echo 1; else echo 0; fi' \
    2>/dev/null || echo 1
}

# RoCE rate on rain's port over a 10 s window, in Mb/s (counters count 4-byte words).
port_mbps() {
  local a b
  a=$(( $(cat $PORT/port_xmit_data) + $(cat $PORT/port_rcv_data) ))
  sleep 10
  b=$(( $(cat $PORT/port_xmit_data) + $(cat $PORT/port_rcv_data) ))
  echo $(( (b - a) * 4 * 8 / 10 / 1000000 ))
}

exec 9>"$LOCK"
start=$(date +%s)
# Priority: while a live process named in $PRIO waits for the lock, runs whose tag does not start
# with "prio-" give the lock back right after getting it, so the priority run gets it next.
PRIO=${CLUSTER_PRIO:-$SCRATCH/cluster.prio}
case "$TAG" in prio-*) echo $$ > "$PRIO" ;; esac
while :; do
  left=$(( MAXWAIT - ($(date +%s) - start) ))
  if [ "$left" -le 0 ] || ! flock -w "$left" 9; then
    log "gave up waiting for the cluster lock after ${MAXWAIT}s"
    case "$TAG" in prio-*) rm -f "$PRIO" ;; esac
    exit 75
  fi
  case "$TAG" in prio-*) break ;; esac
  p=$(cat "$PRIO" 2>/dev/null)
  if [ -n "$p" ] && kill -0 "$p" 2>/dev/null; then
    flock -u 9; sleep 3; continue      # yield to the waiting priority run
  fi
  break
done
case "$TAG" in prio-*) rm -f "$PRIO" ;; esac
log "lock acquired; waiting for an idle link"

quiet=0
while :; do
  busy=$(sunny_busy)
  mbps=$(port_mbps)
  if [ "$busy" = 0 ] && [ "$mbps" -lt 500 ]; then quiet=$((quiet + 1)); else quiet=0; fi
  [ "$quiet" -ge 3 ] && break
  if [ $(( $(date +%s) - start )) -gt "$MAXWAIT" ]; then
    log "link still busy after ${MAXWAIT}s (sunny_busy=$busy rate=${mbps}Mb/s); not running"
    exit 75
  fi
done

log "idle (rate=${mbps}Mb/s); running: $*"
"$@" 9>&-      # the lock fd stays with this shell only; children must not inherit it
rc=$?
log "command exited rc=$rc; sunny_busy_after=$(sunny_busy)"
exit $rc
