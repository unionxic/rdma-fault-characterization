#!/usr/bin/env bash
# nvshmem_batch.sh - NVSHMEM IBGDA trials from a spec file, inside ../../common/cluster_run.sh.
# Appends one KV line per trial to <outdir>/nvshmem.txt.
#   nvshmem_batch.sh <spec> <outdir>
# spec lines: <fault> <fix 0|1> <hold 0|1> <watch_ms (0 = off)> <trial> [<watch_delay_ms>]
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
SPEC=$1; OUT=$2
mkdir -p "$OUT"
cp "$SPEC" "$OUT/$(basename "$SPEC").$(date +%H%M%S)"
while read -r fault fix hold wms trial wdelay; do
  case "$fault" in ''|\#*) continue ;; esac
  FIX=$fix HOLD=$hold WATCH_MS=$wms WATCH_DELAY_MS=${wdelay:-0} DEV_TIMEOUT_MS=${DEV_TIMEOUT_MS:-10000} \
    bash "$HERE/run_nvshmem_trial.sh" "$fault" timeout "$trial" "$OUT" </dev/null | tee -a "$OUT/nvshmem.txt"
done < "$SPEC"
echo "nvshmem batch done"
