#!/usr/bin/env bash
# chain_rs.sh - run gin-restore work package 10 holds one after another, each as its own
# ../../../../common/cluster_run.sh hold (-w 10800: other experiments share the lock; tag rs-<hold>; each bounded by
# timeout -s KILL 880), like ../../feas and gpu-detect's chain.sh. No further hold runs once <resultsdir> holds a STOP_*
# file. No cluster action happens here on this branch: the MAIN SESSION runs this. It touches no link, address, driver or
# firewall and adds no iptables rule.
# usage: chain_rs.sh <resultsdir> <hold> [<hold> ...]
set -u
R=${1:?resultsdir}; shift
D=$(cd "$(dirname "$0")" && pwd)
CR=$D/../../../../common/cluster_run.sh
SUNNY_SSH=${SUNNY_SSH:?set SUNNY_SSH}
export SUNNY_SSH
mkdir -p "$R"
stopped() { ls "$R"/STOP_* > /dev/null 2>&1; }
for H in "$@"; do
  if stopped; then echo "$(date '+%F %T') hold $H skipped: STOP file present" | tee -a "$R/chain.out"; continue; fi
  echo "$(date '+%F %T') hold $H start" >> "$R/chain.out"
  bash "$CR" -w 10800 -t "rs-$H" -- timeout -s KILL 880 bash "$D/hold_rs.sh" "$R" "$H" > "$R/hold_${H}.out" 2>&1
  echo "$(date '+%F %T') hold $H rc=$?" >> "$R/chain.out"
done
