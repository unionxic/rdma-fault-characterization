#!/usr/bin/env bash
# Run gin-s2-close holds one after another, each as its own ../../common/cluster_run.sh hold (-w 10800: two other
# experiments share the lock; tag gs2-<hold>; each hold bounded by timeout -s KILL 880). No further hold runs once a
# hold has written <resultsdir>/STOP_mlx5. usage: chain.sh <resultsdir> <hold> [<hold> ...]
set -u
R=${1:?resultsdir}; shift
D=$(cd "$(dirname "$0")" && pwd)
CR=$D/../../common/cluster_run.sh
mkdir -p "$R"
for H in "$@"; do
  if [ -e "$R/STOP_mlx5" ]; then echo "$(date '+%F %T') hold $H skipped: STOP_mlx5" | tee -a "$R/chain.out"; continue; fi
  tag=gs2-${H%%:*}
  echo "$(date '+%F %T') hold $H start" >> "$R/chain.out"
  bash "$CR" -w 10800 -t "$tag" -- timeout -s KILL 880 bash "$D/hold.sh" "$R" "$H" > "$R/hold_${H%%:*}.out" 2>&1
  echo "$(date '+%F %T') hold $H rc=$?" >> "$R/chain.out"
done
