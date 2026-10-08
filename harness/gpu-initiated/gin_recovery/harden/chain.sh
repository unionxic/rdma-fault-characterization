#!/usr/bin/env bash
# Run gin-harden holds one after another, each as its own ../../common/cluster_run.sh hold (-w 10800: other experiments
# share the lock; tag ghd-<hold>; each hold bounded by timeout -s KILL 880). No further hold runs once a hold has written
# <resultsdir>/STOP_mlx5 or STOP_iptables. After every hold (also one killed by its bound, whose trial could not remove
# its mute rules), any iptables INPUT rule on rain whose comment starts with "gin-harden-" (only run_trial_hd.sh adds
# such rules) is deleted and the deletion is checked; a rule that cannot be deleted writes STOP_iptables.
# usage: chain.sh <resultsdir> <hold> [<hold> ...]
set -u
R=${1:?resultsdir}; shift
D=$(cd "$(dirname "$0")" && pwd)
CR=$D/../../common/cluster_run.sh
mkdir -p "$R"
ipt_cleanup() {  # delete this study's leftover INPUT rules on rain (tagged gin-harden-<pid>), report what was done
  local rules n=0 line
  rules=$(sudo -n iptables -w 5 -S INPUT 2>/dev/null | grep -- "--comment \"\?gin-harden-[0-9]*\"\? ")
  if [ -n "$rules" ]; then
    while IFS= read -r line; do
      # shellcheck disable=SC2086
      sudo -n iptables -w 5 $(echo "$line" | sed 's/^-A /-D /' | tr -d '"') && n=$((n + 1))
    done <<< "$rules"
  fi
  local left
  left=$(sudo -n iptables -w 5 -S INPUT 2>/dev/null | grep -c -- "gin-harden-")
  echo "$(date '+%F %T') iptables cleanup: deleted=$n left=$left" >> "$R/chain.out"
  [ "$left" = 0 ] || echo "$(date '+%F %T') $left gin-harden iptables rule(s) could not be deleted" | tee -a "$R/STOP_iptables"
}
for H in "$@"; do
  if [ -e "$R/STOP_mlx5" ] || [ -e "$R/STOP_iptables" ]; then
    echo "$(date '+%F %T') hold $H skipped: STOP file present" | tee -a "$R/chain.out"
    continue
  fi
  tag=ghd-${H%%:*}
  echo "$(date '+%F %T') hold $H start" >> "$R/chain.out"
  bash "$CR" -w 10800 -t "$tag" -- timeout -s KILL 880 bash "$D/hold.sh" "$R" "$H" > "$R/hold_${H%%:*}.out" 2>&1
  echo "$(date '+%F %T') hold $H rc=$?" >> "$R/chain.out"
  ipt_cleanup
done
