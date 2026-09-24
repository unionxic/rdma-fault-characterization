#!/usr/bin/env bash
# Validation pass over every cell once (inside cluster_run), after the review fixes.
set -u
L=${1:?logdir}
cd "$(dirname "$0")"
for c in none_b f1_b f1_t f3_b f1x5_b f2_b f4_b neg_norebase_t neg_noring_t off_f1_b base_f1_b; do
  bash batch.sh "$L" $c 1
done
