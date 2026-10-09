#!/usr/bin/env bash
# Run gpu-detect holds one after another, each as its own ../gpu-initiated/common/cluster_run.sh hold (-w 10800: other
# experiments share the lock; prio- runs go first; tag gd-<hold>; each hold bounded by timeout -s KILL 880). A copy of
# ../blind/chain.sh without the iptables cleanup (this study adds no rule): chain.sh only counts, read-only, the rules
# tagged gin- or blind- on rain before and after every hold and writes STOP_iptables if the count grew. An app hold (G*, N*)
# that still has trials without a result after its pass (apprun.py stops a pass before its 800 s budget) is queued again,
# at most twice. No further hold runs once <resultsdir> holds a STOP_* file.
# usage: chain.sh <resultsdir> <hold> [<hold> ...]
set -u
R=${1:?resultsdir}; shift
D=$(cd "$(dirname "$0")" && pwd)
CR=$D/../gpu-initiated/common/cluster_run.sh
SUNNY_SSH=${SUNNY_SSH:-unionxic@192.0.2.194}
export SUNNY_SSH
mkdir -p "$R"
ipt_count() { sudo -n iptables -w 5 -S 2>/dev/null | grep -cE -- "gin-|blind-"; }
run_hold() {  # run_hold <hold> <pass>
  local H=$1 i0 i1
  i0=$(ipt_count)
  echo "$(date '+%F %T') hold $H pass $2 start" >> "$R/chain.out"
  bash "$CR" -w 10800 -t "gd-$H" -- timeout -s KILL 880 bash "$D/hold.sh" "$R" "$H" > "$R/hold_${H}_p$2.out" 2>&1
  echo "$(date '+%F %T') hold $H pass $2 rc=$?" >> "$R/chain.out"
  i1=$(ipt_count)
  echo "$(date '+%F %T') iptables rules tagged gin- or blind-: before=$i0 after=$i1 (this study adds none)" >> "$R/chain.out"
  [ "$i1" -le "$i0" ] || echo "$(date '+%F %T') hold $H: iptables rules grew ($i0 -> $i1)" | tee -a "$R/STOP_iptables"
}
stopped() { ls "$R"/STOP_* > /dev/null 2>&1; }
for H in "$@"; do
  if stopped; then echo "$(date '+%F %T') hold $H skipped: STOP file present" | tee -a "$R/chain.out"; continue; fi
  run_hold "$H" 1
  case "$H" in
    G[0-9]*|N[0-9]*|P1)
      for p in 2 3; do
        stopped && break
        left=$(python3 "$D/apprun.py" pending --results "$R" --hold "$H" 2>/dev/null || echo 0)
        [ "${left:-0}" -gt 0 ] || break
        echo "$(date '+%F %T') hold $H: $left trial(s) without a result; pass $p" >> "$R/chain.out"
        run_hold "$H" "$p"
      done ;;
  esac
done
