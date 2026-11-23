#!/usr/bin/env bash
# nvshmem_batch.sh - NVSHMEM IBGDA trials from a spec file, inside ../../common/cluster_run.sh.
# Appends one KV line per trial to <outdir>/nvshmem.txt.
#   nvshmem_batch.sh <spec> <outdir>
# spec lines (v2): <fault> <wait> <handler> <fix 0|1> <hold 0|1> <watch_ms (0 = off)> <trial> [<watch_delay_ms>]
# (the v1 specs nv1/nv2 used "<fault> <fix> <hold> <watch_ms> <trial> [delay]" with wait=timeout
#  and handler=auto, which was the CPU proxy before PeerMappingOverride was made permanent)
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
SPEC=$1; OUT=$2
mkdir -p "$OUT"
cp "$SPEC" "$OUT/$(basename "$SPEC").$(date +%H%M%S)"
while read -r fault wait handler fix hold wms trial wdelay; do
  case "$fault" in ''|\#*) continue ;; esac
  HANDLER=$handler FIX=$fix HOLD=$hold WATCH_MS=$wms WATCH_DELAY_MS=${wdelay:-0} \
    DEV_TIMEOUT_MS=${DEV_TIMEOUT_MS:-10000} NVSHMEM_FAULT_WATCHDOG_S=${NVSHMEM_FAULT_WATCHDOG_S:-25} \
    bash "$HERE/run_nvshmem_trial.sh" "$fault" "$wait" "$trial" "$OUT" </dev/null | tee -a "$OUT/nvshmem.txt"
done < "$SPEC"
echo "nvshmem batch done"
