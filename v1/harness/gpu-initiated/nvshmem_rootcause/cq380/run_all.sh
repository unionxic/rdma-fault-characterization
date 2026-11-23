#!/usr/bin/env bash
# run_all.sh <outdir> - the 25 pre-registered cq380 trials, trial-major, inside one cluster_run.sh call.
set -u
OUT=${1:?outdir}; mkdir -p "$OUT"; OUT=$(cd "$OUT" && pwd)
HERE=$(cd "$(dirname "$0")" && pwd)
echo "start $(date '+%F %T')"
for t in 1 2 3 4 5; do
  for c in "stock cpu_host_memory 1" "stock gpu 1" "fix cpu_host_memory 1" "stock cpu_host_memory 0" "stock gpu 0"; do
    set -- $c
    bash "$HERE/trace_trial.sh" "$1" "$2" "$3" "$t" "$OUT" >> "$OUT/trials.csv"
    echo "$1 $2 kill$3 t$t done $(date +%T)"
  done
done
echo "end $(date '+%F %T')"
