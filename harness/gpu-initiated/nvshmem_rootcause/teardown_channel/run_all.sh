#!/usr/bin/env bash
# run_all.sh <outdir> - the 30 pre-registered trials, interleaved (trial-major), one cluster_run.sh
# call for the whole set. Per trial: GPU handler (stock), CPU proxy + record fix, CPU proxy (stock),
# each with the peer killed and with no kill.
set -u
OUT=${1:?outdir}; mkdir -p "$OUT"; OUT=$(cd "$OUT" && pwd)
HERE=$(cd "$(dirname "$0")" && pwd)
echo "variant,handler_env,kill,trial,handler_log,kill_at,pe0_rc,pe1_rc,counters,pe0_last,capture" > "$OUT/trials.csv"
echo "start $(date '+%F %T')"
for t in 1 2 3 4 5; do
  for v in "stock gpu" "fix cpu_host_memory" "stock cpu_host_memory"; do
    for k in 1 0; do
      set -- $v
      bash "$HERE/trace_trial.sh" "$1" "$2" "$k" "$t" "$OUT" >> "$OUT/trials.csv"
      echo "$1 $2 kill$k t$t done $(date +%T)"
    done
  done
done
echo "end $(date '+%F %T')"
