#!/usr/bin/env bash
# Run gin-multirank holds one after another, each as its own ../../common/cluster_run.sh hold (-w 10800: other
# experiments share the lock; tag gmr-<hold>; each hold bounded by timeout -s KILL 880). No further hold runs once a hold
# has written <resultsdir>/STOP_mlx5 or <resultsdir>/STOP_left (two trials in a row left gin_mr behind), nor (after P0)
# once the pilot wrote <resultsdir>/PILOT_STOP.
# usage: LIB=<recovery build> [MRKEY=<driver key>] chain.sh <resultsdir> <hold> [<hold> ...]
set -u
R=${1:?resultsdir}; shift
: "${LIB:?LIB (the recovery build key)}"
D=$(cd "$(dirname "$0")" && pwd)
CR=$D/../../common/cluster_run.sh
mkdir -p "$R"
for H in "$@"; do
  if [ -e "$R/STOP_mlx5" ]; then echo "$(date '+%F %T') hold $H skipped: STOP_mlx5" | tee -a "$R/chain.out"; continue; fi
  if [ -e "$R/STOP_left" ]; then echo "$(date '+%F %T') hold $H skipped: STOP_left" | tee -a "$R/chain.out"; continue; fi
  if [ -e "$R/PILOT_STOP" ]; then echo "$(date '+%F %T') hold $H skipped: PILOT_STOP" | tee -a "$R/chain.out"; continue; fi
  tag=gmr-${H%%:*}
  echo "$(date '+%F %T') hold $H start lib=$LIB mrkey=${MRKEY:-$LIB}" >> "$R/chain.out"
  LIB=$LIB bash "$CR" -w 10800 -t "$tag" -- timeout -s KILL 880 bash "$D/hold.sh" "$R" "$H" > "$R/hold_${H%%:*}.out" 2>&1
  echo "$(date '+%F %T') hold $H rc=$?" >> "$R/chain.out"
done
