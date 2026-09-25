#!/usr/bin/env bash
# Follow-up validation pass: each new cell once, plus a regression of the main cells.
set -u
L=${1:?logdir}
cd "$(dirname "$0")"
for c in split_b stallq_b stallc_b die_b tmo_t none_b f1_b f3_b f1g0_b f2_b; do bash batch.sh "$L" $c 1; done
