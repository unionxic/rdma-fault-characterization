#!/usr/bin/env bash
# The gate micro-test (../../gate_ce_test.cu) on both GPUs, inside a cluster hold. One line per run.
# usage: gate_test.sh <outfile> [secs]
set -u
OUT=${1:?out}; SECS=${2:-10}
SUNNY_SSH=${SUNNY_SSH:-unionxic@192.0.2.194}
B=/home/unionxic/gi-bundle/gin_ts2
for cfg in "1 32 gpu 0" "8 256 gpu 0" "64 256 gpu 0" "64 256 sys 0" "64 256 cas 0" "64 256 gpu 2000" "160 1024 gpu 0"; do
  set -- $cfg
  echo "rain $(timeout 120 $B/gate_ce_test $1 $2 $SECS $3 $4 2>&1 | tail -1) rc=$?" | tee -a "$OUT"
  echo "sunny $(ssh -n "$SUNNY_SSH" "timeout 120 $B/gate_ce_test $1 $2 $SECS $3 $4 2>&1 | tail -1; echo rc=\$?" | tr '\n' ' ')" | tee -a "$OUT"
done
