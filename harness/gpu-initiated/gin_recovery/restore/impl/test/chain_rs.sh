#!/usr/bin/env bash
# chain_rs.sh - run gin-restore work package 10 holds one after another, each as its own
# ../../../../common/cluster_run.sh hold (-w 10800: other experiments share the lock; tag rs-<hold>; each bounded by
# timeout -s KILL 880), like ../../feas and gpu-detect's chain.sh. No further hold runs once <resultsdir> holds a STOP_*
# file. No cluster action happens here on this branch: the MAIN SESSION runs this. It touches no link, address, driver or
# firewall and adds no iptables rule.
# usage: [RS_SET=<set>] chain_rs.sh <resultsdir> <hold> [<hold> ...]
# RS_SET (2026-10-13): the deployment set the runners use (~/rs-bundle/<RS_SET>/, deploy_rs.sh; empty: today's paths); it is
# exported to every hold and written in chain.out. The same hold may be named again (in this call or a later one): the holds
# are resumable (hold_rs.sh skips a cell trial whose meta file exists), and a repeated hold's output goes to
# hold_<hold>-r<k>.out (k = 2, 3, ...), so no earlier output is overwritten.
set -u
R=${1:?resultsdir}; shift
D=$(cd "$(dirname "$0")" && pwd)
CR=$D/../../../../common/cluster_run.sh
SUNNY_SSH=${SUNNY_SSH:?set SUNNY_SSH}
export SUNNY_SSH
RS_SET=${RS_SET:-}
case "$RS_SET" in */*|*..*|-*) echo "RS_SET must be a plain name" >&2; exit 1 ;; esac
export RS_SET
mkdir -p "$R"
stopped() { ls "$R"/STOP_* > /dev/null 2>&1; }
for H in "$@"; do
  if stopped; then echo "$(date '+%F %T') hold $H skipped: STOP file present" | tee -a "$R/chain.out"; continue; fi
  out=$R/hold_${H}.out
  if [ -e "$out" ]; then k=2; while [ -e "$R/hold_${H}-r$k.out" ]; do k=$((k + 1)); done; out=$R/hold_${H}-r$k.out; fi
  echo "$(date '+%F %T') hold $H start rs_set=${RS_SET:--} out=$(basename "$out")" >> "$R/chain.out"
  bash "$CR" -w 10800 -t "rs-$H" -- timeout -s KILL 880 bash "$D/hold_rs.sh" "$R" "$H" > "$out" 2>&1
  echo "$(date '+%F %T') hold $H rc=$?" >> "$R/chain.out"
done
