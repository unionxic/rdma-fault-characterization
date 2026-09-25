#!/usr/bin/env bash
# chunk.sh <queue> <start_budget_s> - run the not-yet-done lines of a queue file, one trial per line:
#   <id> <wrapper> <args...>          (wrapper = q4_one.sh | rec_one.sh | nv_one.sh in ../bin)
# A line is marked done (state/<queue>.done) after its trial returned, whatever the outcome.
# No new trial is started once <start_budget_s> seconds have passed (each trial bounds itself;
# the caller adds a hard `timeout` and runs this inside common/cluster_run.sh).
set -u
A=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad/agent_n30
Q=$1; BUDGET=${2:-600}
DONE=$A/state/$(basename "$Q").done
touch "$DONE"
T0=$(date +%s); n=0
while read -r id wrapper args; do
  [ -z "${id:-}" ] && continue
  case "$id" in \#*) continue ;; esac
  grep -qxF "$id" "$DONE" && continue
  if [ $(( $(date +%s) - T0 )) -ge "$BUDGET" ]; then echo "[chunk] budget reached before $id" >&2; break; fi
  echo ">>> [$id] $(date '+%F %T')" >&2
  s=$(date +%s.%N)
  # shellcheck disable=SC2086
  bash "$A/bin/$wrapper" $args < /dev/null
  rc=$?
  echo "$id" >> "$DONE"
  echo "$(date '+%F %T') id=$id rc=$rc dur_s=$(python3 -c "import sys;print('%.1f'%(float(sys.argv[2])-float(sys.argv[1])))" "$s" "$(date +%s.%N)")" >> "$A/state/trials.log"
  n=$((n + 1))
done < "$Q"
left=$(grep -v '^#' "$Q" | awk 'NF' | cut -d' ' -f1 | grep -vxFf "$DONE" | wc -l)
echo "[chunk] ran $n trials in $(( $(date +%s) - T0 )) s; $left left in $(basename "$Q")" >&2
