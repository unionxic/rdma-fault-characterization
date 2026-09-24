#!/usr/bin/env bash
# linkflap_window.sh - REAL link down/up on sunny's RoCE port, for the Stage 2 transient-fault test.
#
# NOT RUN YET. The rain<->sunny link also carries the user's NVMe-oF (sunny mounts rain's namespaces
# at /mnt/rain-nvmeof over RDMA) and gds-kv experiments. A link flap disrupts that storage traffic, so
# this script refuses to run unless the user has approved it explicitly for this window:
#
#   linkflap_window.sh --i-have-user-approval <outage_s> -- <command...>
#
# It checks that no gdsio / mix_threads.sh runs on sunny, records the NVMe-oF state and the kernel log
# position, takes the link down for <outage_s> seconds while <command> runs (the link goes down
# <delay> s after the command starts), brings it back in every exit path (EXIT/INT/TERM trap, and a
# watchdog `sleep; ip link set up` started on sunny before the link goes down), then reports what the
# NVMe-oF host logged. Run under ../../gpu-initiated/common/cluster_run.sh.
set -u
[ "${1:-}" = "--i-have-user-approval" ] || { echo "refusing: needs --i-have-user-approval (the link carries the user's NVMe-oF)"; exit 2; }
OUTAGE=${2:?outage seconds}; shift 2
[ "${1:-}" = "--" ] && shift
DELAY=${LINKFLAP_DELAY:-6}
SUNNY=unionxic@192.0.2.194
S_IF=enp23s0f0np0
LOG=${LINKFLAP_LOG:-/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad/linkflap.log}
log() { echo "$(date '+%F %T.%N' | cut -c1-23) $*" | tee -a "$LOG" >&2; }
on_sunny() { ssh -n -o ConnectTimeout=5 -o BatchMode=yes "$SUNNY" "$@"; }

on_sunny 'pgrep -x gdsio >/dev/null || pgrep -f "[m]ix_threads.sh" >/dev/null' && { log "storage benchmark running on sunny; not flapping"; exit 75; }
log "before: $(on_sunny "ip -br link show $S_IF; mount | grep -c rain-nvmeof; sudo -n dmesg | wc -l")"
restore() {
  on_sunny "sudo -n ip link set $S_IF up" 2>/dev/null
  log "restore: $(on_sunny "ip -br link show $S_IF")"
}
trap restore EXIT INT TERM
"$@" &
CMD=$!
sleep "$DELAY"
# watchdog on sunny itself: the link comes back even if this host loses the management network
on_sunny "nohup bash -c 'sleep $((OUTAGE + 5)); sudo -n ip link set $S_IF up' >/dev/null 2>&1 &"
log "link down for ${OUTAGE}s"
on_sunny "sudo -n ip link set $S_IF down; sleep $OUTAGE; sudo -n ip link set $S_IF up"
log "link up again"
wait $CMD; rc=$?
sleep 10
log "after: $(on_sunny "ip -br link show $S_IF; mount | grep -c rain-nvmeof"); nvme lines since: $(on_sunny "sudo -n dmesg | tail -200 | grep -i -c nvme")"
exit $rc
