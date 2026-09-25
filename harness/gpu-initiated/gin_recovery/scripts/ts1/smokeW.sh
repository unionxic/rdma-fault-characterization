#!/usr/bin/env bash
# Follow-up validation pass 2 (teardown fix): the abort-mid-round cell, the bound cells with the longer
# application grace, and a short regression (recovery on, flag off).
set -u
L=${1:?logdir}
cd "$(dirname "$0")"
for c in abortmid_b abortmid_b slow_b die_b stallq_b tmo_t f1_b off_f1_b none_b f2_b; do bash batch.sh "$L" $c 1; done
