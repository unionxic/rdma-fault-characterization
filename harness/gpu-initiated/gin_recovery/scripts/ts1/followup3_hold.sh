#!/usr/bin/env bash
# Third-review holds (non-prio ts1b-*, each <= 15 min), new result dirs results/20260925_ts1/v3_*.
#   H5  post-commit-point stalls: late_ok_b, late_fail_b x10
#   H6  monitor through ncclCommAbort mid-round: abortmon_b, abortmonfull_b x10; regression on the final
#       build (every cell 2-3x, in-flight x10, fault-free latency on/off x3)
set -u
R=${1:?resultsdir}; H=${2:?hold}
cd "$(dirname "$0")"
case "$H" in
  H5) for c in late_ok_b late_fail_b; do bash batch.sh "$R/v3_late" $c 10; done ;;
  H6) for c in abortmon_b abortmonfull_b; do bash batch.sh "$R/v3_abortmon" $c 10; done
      for c in none_b f1_b f1_t f3_b f1x5_b f2_b f4_b split_b slow_b stallq_b die_b tmo_t abortmid_b; do bash batch.sh "$R/v3_confirm" $c 2; done
      for c in off_f1_b base_f1_b neg_norebase_t neg_noring_t; do bash batch.sh "$R/v3_confirm" $c 1; done
      bash batch.sh "$R/v3_confirm" f1g0_b 10
      for k in 1 2 3; do for c in lat_on_4k lat_off_4k lat_on_256k lat_off_256k; do bash batch.sh "$R/v3_lat" $c 1 $k; done; done ;;
  *) echo "unknown hold $H" >&2; exit 2 ;;
esac
