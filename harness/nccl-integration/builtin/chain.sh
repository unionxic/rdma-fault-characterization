#!/usr/bin/env bash
# Run nccl-builtin holds one after another, each as its own ../../gpu-initiated/common/cluster_run.sh hold (-w 10800:
# other experiments share the lock; tag nb-<hold>; each hold bounded by timeout -s KILL 880). No further hold runs once
# a hold has written <resultsdir>/STOP_mlx5, STOP_config or STOP_left (EXPERIMENT.md 8).
# usage: chain.sh <resultsdir> <hold> [<hold> ...]
set -u
R=${1:?resultsdir}; shift
D=$(cd "$(dirname "$0")" && pwd)
CR=$D/../../gpu-initiated/common/cluster_run.sh
mkdir -p "$R"
for H in "$@"; do
  stop=$(ls "$R"/STOP_mlx5 "$R"/STOP_config "$R"/STOP_left 2>/dev/null | head -1)
  if [ -n "$stop" ]; then echo "$(date '+%F %T') hold $H skipped: $(basename "$stop")" | tee -a "$R/chain.out"; continue; fi
  name=${H%%:*}; [ "$name" = fill ] && name=fill-$(date +%H%M%S)
  echo "$(date '+%F %T') hold $H start" >> "$R/chain.out"
  bash "$CR" -w 10800 -t "nb-${H%%:*}" -- timeout -s KILL 880 bash "$D/hold.sh" "$R" "$H" > "$R/hold_$name.out" 2>&1
  echo "$(date '+%F %T') hold $H rc=$?" >> "$R/chain.out"
done
