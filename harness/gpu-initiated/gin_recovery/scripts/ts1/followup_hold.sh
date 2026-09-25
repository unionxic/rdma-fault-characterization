#!/usr/bin/env bash
# Follow-up (external review) holds on the final follow-up build, each inside ../../../common/cluster_run.sh
# with a non-prio tag and `timeout` <= 15 min. New result dirs under results/20260925_ts1/v2_*.
# usage: followup_hold.sh <resultsdir> <H1|H2|H3|H4>
#   H1  exactly-once boundary (split_b x30) + in-flight F1 cell f1g0_b n1..50
#   H2  bounds: stallq_b, stallc_b, die_b, tmo_t, abortmid_b, slow_b x10 each
#   H3  in-flight f1g0_b n51..100 + cumulative latency attribution (interleaved, 5 reps)
#   H4  in-flight f1g0_b n101..150 + regression confirmation of every phase-1 cell
set -u
R=${1:?resultsdir}; H=${2:?hold}
cd "$(dirname "$0")"
case "$H" in
  H1) bash batch.sh "$R/v2_split" split_b 30
      bash batch.sh "$R/v2_f1g0" f1g0_b 50 1 ;;
  H2) for c in stallq_b stallc_b die_b tmo_t abortmid_b slow_b; do bash batch.sh "$R/v2_bounds" $c 10; done ;;
  H3) bash batch.sh "$R/v2_f1g0" f1g0_b 50 51
      for k in 1 2 3 4 5; do
        for c in lat_on_4k lat_c1gpufence_4k lat_c2nogate_4k lat_c3nopoll_4k lat_off_4k lat_base_4k \
                 lat_on_256k lat_c1gpufence_256k lat_c2nogate_256k lat_c3nopoll_256k lat_off_256k lat_base_256k; do
          bash batch.sh "$R/v2_lat" $c 1 $k
        done
      done ;;
  H4) bash batch.sh "$R/v2_f1g0" f1g0_b 50 101
      for c in none_b f1_b f1_t f3_b f3_t f1x5_b f2_b f4_b; do bash batch.sh "$R/v2_confirm" $c 3; done
      for c in neg_norebase_t neg_noring_t off_f1_b base_f1_b; do bash batch.sh "$R/v2_confirm" $c 2; done ;;
  *) echo "unknown hold $H" >&2; exit 2 ;;
esac
