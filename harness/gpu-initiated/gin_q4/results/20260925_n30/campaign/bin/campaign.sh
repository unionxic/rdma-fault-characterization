#!/usr/bin/env bash
# campaign.sh <queue> [<queue> ...] - run the queues chunk by chunk, each chunk one cluster hold:
#   common/cluster_run.sh -- timeout -s TERM 780 chunk.sh <queue> 600
# (no new trial after 600 s, hard stop at 780 s; the hold adds >= 30 s of idle-link wait, so each hold
# stays < 14 min). Pauses 60 s between holds so other agents queued on the lock get it.
# Stops when state/STOP exists. Log: state/campaign.out; one line per hold in state/holds.log.
set -u
A=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad/agent_n30
CR=/home/unionxic/rdma-error/harness/gpu-initiated/common/cluster_run.sh
left() { grep -v '^#' "$1" | awk 'NF' | cut -d' ' -f1 | grep -vxFf "$A/state/$(basename "$1").done" 2>/dev/null | wc -l; }
for qn in "$@"; do
  Q=$A/specs/$qn.q
  touch "$A/state/$qn.q.done"
  k=0
  while [ "$(left "$Q")" -gt 0 ]; do
    [ -e "$A/state/STOP" ] && { echo "$(date '+%F %T') STOP file present; stopping" >> "$A/state/holds.log"; exit 0; }
    k=$((k + 1))
    tag=n30-$qn$k
    s=$(date +%s)
    bash "$CR" -w 7200 -t "$tag" -- timeout -s TERM 780 bash "$A/bin/chunk.sh" "$Q" 600 >> "$A/state/campaign.out" 2>&1
    rc=$?
    echo "$(date '+%F %T') hold=$tag rc=$rc wall_s=$(( $(date +%s) - s )) left=$(left "$Q")" >> "$A/state/holds.log"
    sleep 60
  done
done
echo "$(date '+%F %T') campaign done: $*" >> "$A/state/holds.log"
