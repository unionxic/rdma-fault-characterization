#!/usr/bin/env bash
# Fault-free latency, interleaved per repetition (on, off, base) x (4 KiB, 256 KiB), inside cluster_run.
set -u
L=${1:?logdir}; N=${2:?reps}; START=${3:-1}
cd "$(dirname "$0")"
for ((k = START; k < START + N; k++)); do
  for c in lat_on_4k lat_off_4k lat_base_4k lat_on_256k lat_off_256k lat_base_256k; do
    bash batch.sh "$L" $c 1 $k
  done
done
