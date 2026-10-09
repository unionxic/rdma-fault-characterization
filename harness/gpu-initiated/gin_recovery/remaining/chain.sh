#!/usr/bin/env bash
# Run gin-remaining holds one after another, each as its own ../../common/cluster_run.sh hold (-w 10800: other experiments
# share the lock; tag grm-<hold>; each hold bounded by timeout -s KILL 880). A copy of ../peer/chain.sh with the tag
# changed. No further hold runs once a hold has written
# <resultsdir>/STOP_mlx5, STOP_cuda or STOP_left. This study adds no iptables rule; chain.sh still counts the rules of
# the earlier studies' tags on rain before and after every hold (read-only) and stops if the count grew (STOP_iptables).
# usage: chain.sh <resultsdir> <hold> [<hold> ...]
set -u
R=${1:?resultsdir}; shift
D=$(cd "$(dirname "$0")" && pwd)
CR=$D/../../common/cluster_run.sh
mkdir -p "$R"
ipt_count() { sudo -n iptables -w 5 -S INPUT 2>/dev/null | grep -c -- "gin-" ; }
for H in "$@"; do
  if [ -e "$R/STOP_mlx5" ] || [ -e "$R/STOP_cuda" ] || [ -e "$R/STOP_left" ] || [ -e "$R/STOP_iptables" ]; then
    echo "$(date '+%F %T') hold $H skipped: STOP file present" | tee -a "$R/chain.out"
    continue
  fi
  tag=grm-${H%%:*}
  i0=$(ipt_count)
  echo "$(date '+%F %T') hold $H start" >> "$R/chain.out"
  bash "$CR" -w 10800 -t "$tag" -- timeout -s KILL 880 bash "$D/hold.sh" "$R" "$H" > "$R/hold_${H%%:*}.out" 2>&1
  echo "$(date '+%F %T') hold $H rc=$?" >> "$R/chain.out"
  i1=$(ipt_count)
  echo "$(date '+%F %T') iptables rules tagged gin-: before=$i0 after=$i1 (this study adds none)" >> "$R/chain.out"
  [ "$i1" -le "$i0" ] || echo "$(date '+%F %T') hold $H: gin- iptables rules grew ($i0 -> $i1)" | tee -a "$R/STOP_iptables"
done
