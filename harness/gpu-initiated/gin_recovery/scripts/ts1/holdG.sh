#!/usr/bin/env bash
# Hold G, on the final build (helper QP modifications serialized with the fault hook through opMu):
# the in-flight cell (N=30) and a confirmation pass over every other cell.
set -u
R=${1:?resultsdir}
cd "$(dirname "$0")"
bash batch.sh "$R/runs" f1g0_b 30
for c in none_b f1_b f1_t f3_b f1x5_b f2_b f4_b; do bash batch.sh "$R/confirm" $c 3; done
bash batch.sh "$R/confirm" neg_norebase_t 1
bash batch.sh "$R/confirm" neg_noring_t 1
bash batch.sh "$R/confirm" off_f1_b 2
for k in 1 2 3; do for c in lat_on_4k lat_off_4k lat_on_256k lat_off_256k; do bash batch.sh "$R/confirm_lat" $c 1 $k; done; done
