#!/usr/bin/env bash
# Run blind-apps holds one after another, each as its own ../gpu-initiated/common/cluster_run.sh hold (-w 10800: other
# experiments share the lock; prio- runs go first; tag blind-<hold>; each hold bounded by timeout -s KILL 880).
# After every hold (also one killed by its bound, whose trial could not remove its mute rules) any iptables rule on rain
# whose comment starts with "blind-" (only blindrun.py adds such rules) is deleted and the deletion is checked; a rule
# that cannot be deleted writes STOP_iptables. A blind hold (D*, G*, N*) that still has trials without a result after
# its pass (the runner stops a pass before its 800 s budget) is queued again, at most twice. No further hold runs once
# <resultsdir> holds a STOP_* file.
# usage: chain.sh <resultsdir> <hold> [<hold> ...]
set -u
R=${1:?resultsdir}; shift
D=$(cd "$(dirname "$0")" && pwd)
CR=$D/../gpu-initiated/common/cluster_run.sh
SUNNY_SSH=${SUNNY_SSH:-unionxic@192.0.2.194}
export SUNNY_SSH
mkdir -p "$R"
ipt_cleanup() {
  local rules n=0 line left
  rules=$(sudo -n iptables -w 5 -S 2>/dev/null | grep -- "--comment \"\?blind-[0-9]*-[0-9a-z-]*\"\? ")
  if [ -n "$rules" ]; then
    while IFS= read -r line; do
      # shellcheck disable=SC2086
      sudo -n iptables -w 5 $(echo "$line" | sed 's/^-A /-D /' | tr -d '"') && n=$((n + 1))
    done <<< "$rules"
  fi
  left=$(sudo -n iptables -w 5 -S 2>/dev/null | grep -c -- "blind-")
  echo "$(date '+%F %T') iptables cleanup: deleted=$n left=$left" >> "$R/chain.out"
  [ "$left" = 0 ] || echo "$(date '+%F %T') $left blind- iptables rule(s) could not be deleted" | tee -a "$R/STOP_iptables"
}
run_hold() {  # run_hold <hold> <pass>
  local H=$1 tag="blind-$1"
  echo "$(date '+%F %T') hold $H pass $2 start" >> "$R/chain.out"
  bash "$CR" -w 10800 -t "$tag" -- timeout -s KILL 880 bash "$D/hold.sh" "$R" "$H" > "$R/hold_${H}_p$2.out" 2>&1
  echo "$(date '+%F %T') hold $H pass $2 rc=$?" >> "$R/chain.out"
  ipt_cleanup
}
stopped() { ls "$R"/STOP_* > /dev/null 2>&1; }
for H in "$@"; do
  if stopped; then echo "$(date '+%F %T') hold $H skipped: STOP file present" | tee -a "$R/chain.out"; continue; fi
  run_hold "$H" 1
  case "$H" in
    D[0-9]*|G[0-9]*|N[0-9]*)
      for p in 2 3; do
        stopped && break
        left=$(python3 "$D/blindrun.py" pending --results "$R" --hold "$H" 2>/dev/null || echo 0)
        [ "${left:-0}" -gt 0 ] || break
        echo "$(date '+%F %T') hold $H: $left trial(s) without a result; pass $p" >> "$R/chain.out"
        run_hold "$H" "$p"
      done ;;
  esac
done
