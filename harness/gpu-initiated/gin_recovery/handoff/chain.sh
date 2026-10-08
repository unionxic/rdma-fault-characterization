#!/usr/bin/env bash
# Run gin-handoff holds one after another, each as its own ../../common/cluster_run.sh hold (-w 10800: other experiments
# share the lock; tag ghf-<hold>; each hold bounded by timeout -s KILL 880). No further hold runs once a hold has written
# <resultsdir>/STOP_mlx5, STOP_iptables or STOP_cuda. This study adds no iptables rule (no cell sets MGMT_MUTE), so there
# is nothing to clean up here; hold.sh only checks that the number of gin-harden-tagged rules did not grow.
# usage: chain.sh <resultsdir> <hold> [<hold> ...]
set -u
R=${1:?resultsdir}; shift
D=$(cd "$(dirname "$0")" && pwd)
CR=$D/../../common/cluster_run.sh
mkdir -p "$R"
for H in "$@"; do
  if [ -e "$R/STOP_mlx5" ] || [ -e "$R/STOP_iptables" ] || [ -e "$R/STOP_cuda" ]; then
    echo "$(date '+%F %T') hold $H skipped: STOP file present" | tee -a "$R/chain.out"
    continue
  fi
  tag=ghf-${H%%:*}
  echo "$(date '+%F %T') hold $H start" >> "$R/chain.out"
  bash "$CR" -w 10800 -t "$tag" -- timeout -s KILL 880 bash "$D/hold.sh" "$R" "$H" > "$R/hold_${H%%:*}.out" 2>&1
  echo "$(date '+%F %T') hold $H rc=$?" >> "$R/chain.out"
done
