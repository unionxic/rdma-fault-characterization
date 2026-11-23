#!/usr/bin/env bash
# hold_generic.sh <spec> <outdir> [gate_test] - one cluster hold: optional gate micro-test on rain's GPU,
# then the spec (run_matrix_t1.sh). Wrap in ../../../common/cluster_run.sh.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
SPEC=$1; OUT=$2
mkdir -p "$OUT"
if [ "${3:-}" = gate_test ]; then
  timeout -s KILL 60 $HOME/gi-bundle/nvshmem_t1/bin/gate_race_test 64 128 20000 20000 > "$OUT/gate_race_test.out" 2>&1
  timeout -s KILL 60 $HOME/gi-bundle/nvshmem_t1/bin/gate_race_test 8 32 200000 50000 >> "$OUT/gate_race_test.out" 2>&1
  cat "$OUT/gate_race_test.out"
fi
if [ "${3:-}" = gate_test_sunny ]; then  # the same test on sunny's GPU (sm_86)
  ssh -n -o ConnectTimeout=8 unionxic@192.0.2.194 "timeout -s KILL 60 \$HOME/gi-bundle/nvshmem_t1/bin/gate_race_test 64 128 20000 20000; timeout -s KILL 60 \$HOME/gi-bundle/nvshmem_t1/bin/gate_race_test 8 32 200000 50000" > "$OUT/gate_race_test_sunny.out" 2>&1
  cat "$OUT/gate_race_test_sunny.out"
fi
{ date '+%F %T'; dmesg 2>/dev/null | tail -3; } > "$OUT/dmesg_before_rain.txt" 2>&1
bash "$HERE/run_matrix_t1.sh" "$SPEC" "$OUT"
{ date '+%F %T'; dmesg 2>/dev/null | tail -5; } > "$OUT/dmesg_after_rain.txt" 2>&1
ssh -n -o ConnectTimeout=5 unionxic@192.0.2.194 "pgrep -x nvt1_drv | wc -l; pgrep -x nvt1v22_drv | wc -l" > "$OUT/leftover_sunny.txt" 2>&1
pgrep -x nvt1_drv | wc -l > "$OUT/leftover_rain.txt"
