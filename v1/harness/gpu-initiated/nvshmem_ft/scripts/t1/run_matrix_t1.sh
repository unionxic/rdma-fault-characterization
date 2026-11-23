#!/usr/bin/env bash
# run_matrix_t1.sh <spec> <outdir> - run the trials of a spec file in order, inside one cluster hold
# (the caller wraps it in ../../../common/cluster_run.sh). Spec lines: "<n> <fault> <mode> VAR=val ...";
# '#' comments. Trials of the listed cells are interleaved (round-robin) when INTERLEAVE=1. Stops
# starting new trials after STOP_AFTER_S seconds (default 780, so a hold stays under 15 min).
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
SPEC=$1; OUT=$2
mkdir -p "$OUT"
STOP_AFTER_S=${STOP_AFTER_S:-780}
T0=$(date +%s)
mapfile -t LINES < <(grep -v '^\s*#' "$SPEC" | grep -v '^\s*$')
declare -a Q=()
if [ "${INTERLEAVE:-0}" = 1 ]; then
  max=0
  for l in "${LINES[@]}"; do n=${l%% *}; [ "$n" -gt "$max" ] && max=$n; done
  for ((k = 1; k <= max; k++)); do
    for l in "${LINES[@]}"; do n=${l%% *}; [ "$k" -le "$n" ] && Q+=("$k ${l#* }"); done
  done
else
  for l in "${LINES[@]}"; do
    n=${l%% *}; for ((k = 1; k <= n; k++)); do Q+=("$k ${l#* }"); done
  done
fi
echo "matrix $SPEC: ${#Q[@]} trials -> $OUT (start $(date '+%F %T'))"
for e in "${Q[@]}"; do
  if [ $(( $(date +%s) - T0 )) -gt "$STOP_AFTER_S" ]; then echo "STOP_AFTER_S reached; remaining trials not run"; break; fi
  read -r k fault mode rest <<< "$e"
  # shellcheck disable=SC2086
  ( export $rest; bash "$HERE/run_trial_t1.sh" "$fault" "$mode" "$k" "$OUT" )
done
echo "matrix done $(date '+%F %T')"
