#!/usr/bin/env bash
# sweep_cpu.sh - several ackt cells in one cluster hold.
#   sweep_cpu.sh <outdir> <label:T:R:N[:extra args, space separated]> ...
# e.g. sweep_cpu.sh results/20260925/A floorON:14:7:10 floorON:16:7:5 nosamp:14:7:5:-N
# Stops starting new cells after STOP_AFTER_S (default 780 s) so a hold stays < 15 min.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=$1; shift
T0=$(date +%s)
rc_all=0
for cell in "$@"; do
  IFS=: read -r label T R N extra <<< "$cell"
  if [ $(( $(date +%s) - T0 )) -gt "${STOP_AFTER_S:-780}" ]; then
    echo "[sweep] time budget reached before $cell" >&2; rc_all=3; break
  fi
  # shellcheck disable=SC2086
  bash "$HERE/run_cpu.sh" "$OUT" "$label" "$T" "$R" "$N" ${extra:-} || rc_all=1
done
exit $rc_all
