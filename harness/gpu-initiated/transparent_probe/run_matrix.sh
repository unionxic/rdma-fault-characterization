#!/usr/bin/env bash
# run_matrix.sh <outdir> - one bounded hold running the tr_probe feasibility matrix.
# MUST run inside ../common/cluster_run.sh. Each trial self-bounds; the whole hold stays < 10 min.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
OUT=${1:-run1}
case "$OUT" in /*) ;; *) OUT="$HERE/results/$(basename "$OUT")" ;; esac   # always under transparent_probe/results
mkdir -p "$OUT"
run() { bash "$HERE/run_probe.sh" "$@"; }

# Q1 (responder next_rcv_psn vs memory) + Q2 Mode B (both reset) exactly-once, 5 seeds.
# small delay so the responder 2ERR lands mid-burst (partial execution) rather than after it.
for s in 1 2 3 4 5; do SEED=$s K=256 RECOVER=1 DELAY_MAX_US=120 run rb_s$s "$OUT" resp_err; done
# Q1 (responder RTS) + Q2 Mode A (responder untouched) exactly-once, 5 seeds
for s in 1 2 3 4 5; do SEED=$s K=256 RECOVER=1 DELAY_MAX_US=150 run ra_s$s "$OUT" req_err; done
# Q3 atomic-duplicate window: rewind depths
for d in 4 16 64 200; do SEED=1 K=256 DUP_DEPTH=$d run dup_d$d "$OUT" dup; done
# Q4 WQE index field vs NIC counter after reset (no fault, index override)
SEED=1 K=64 run wqeidx "$OUT" wqeidx
echo "MATRIX_DONE $OUT"
