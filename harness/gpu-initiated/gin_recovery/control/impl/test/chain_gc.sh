#!/usr/bin/env bash
# chain_gc.sh - run gin-control test-side holds one after another, each as its own ../../../../common/cluster_run.sh hold
# (-w 10800: other experiments share the lock; tag gc-<hold>; each bounded by timeout -s KILL 880), like gin-mirror's
# chain_mi.sh. No further hold runs once <resultsdir> holds a STOP_* file. No cluster action happens on this branch's side:
# the MAIN SESSION runs this. It touches no link, address, driver or firewall.
# usage: RS_SET=<set> chain_gc.sh <resultsdir> <hold> [<hold> ...]
# The same hold may be named again (holds are resumable: hold_gc.sh skips a cell trial whose meta file exists); a repeated
# hold's output goes to hold_<hold>-r<k>.out. The hold's output (stdout and stderr, ssh's error lines included) goes through
# the IPv4 mask before it reaches that file (REVIEW_TEST fix 15). GC_CHAIN=1 marks the hold as started here (hold_gc.sh
# refuses to run without it).
set -u
R=${1:?resultsdir}; shift
D=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=remote_gc.sh
. "$D/remote_gc.sh"
CR=$D/../../../../common/cluster_run.sh
SUNNY_SSH=${SUNNY_SSH:?set SUNNY_SSH}
export SUNNY_SSH
RS_SET=${RS_SET:-}
# shellcheck source=../../../mirror/impl/test/rs_set_mi.sh
. "$D/../../../mirror/impl/test/rs_set_mi.sh"
rs_set_check || exit 1
export RS_SET
mkdir -p "$R"
stopped() { ls "$R"/STOP_* > /dev/null 2>&1; }
for H in "$@"; do
  if stopped; then echo "$(date '+%F %T') hold $H skipped: STOP file present" | tee -a "$R/chain.out"; continue; fi
  out=$R/hold_${H}.out
  if [ -e "$out" ]; then k=2; while [ -e "$R/hold_${H}-r$k.out" ]; do k=$((k + 1)); done; out=$R/hold_${H}-r$k.out; fi
  echo "$(date '+%F %T') hold $H start rs_set=$RS_SET out=$(basename "$out")" >> "$R/chain.out"
  bash "$CR" -w 10800 -t "gc-$H" -- env GC_CHAIN=1 timeout -s KILL 880 bash "$D/hold_gc.sh" "$R" "$H" 2>&1 | sed -u "$MASK" > "$out"
  echo "$(date '+%F %T') hold $H rc=${PIPESTATUS[0]}" >> "$R/chain.out"
done
