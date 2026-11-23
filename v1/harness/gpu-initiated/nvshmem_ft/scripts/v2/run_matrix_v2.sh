#!/usr/bin/env bash
# run_matrix_v2.sh <spec> <outdir> - run every line of a spec with run_trial_v2.sh (inside
# ../../../common/cluster_run.sh):
#   <fault> <mode> <ntrials> [VAR=value ...]      ('#' comments; TFIRST=k starts trial numbering at k)
# Stops when STOP_AFTER_S seconds (default 840) have passed, so one hold stays under 15 min.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
SPEC=$1; OUT=$2
mkdir -p "$OUT"
T0=$(date +%s)
while read -r fault mode n rest; do
  [ -z "${fault:-}" ] && continue
  case "$fault" in \#*) continue ;; esac
  first=1
  for kvp in $rest; do case "$kvp" in TFIRST=*) first=${kvp#TFIRST=} ;; esac; done
  for t in $(seq "$first" $((first + n - 1))); do
    if [ $(( $(date +%s) - T0 )) -gt "${STOP_AFTER_S:-840}" ]; then
      echo "[matrix] time budget reached before $fault $mode t$t ($rest)" | tee -a "$OUT/matrix.out"; exit 0
    fi
    # shellcheck disable=SC2086
    env $rest bash "$HERE/run_trial_v2.sh" "$fault" "$mode" "$t" "$OUT" | tee -a "$OUT/matrix.out"
  done
done < "$SPEC"
