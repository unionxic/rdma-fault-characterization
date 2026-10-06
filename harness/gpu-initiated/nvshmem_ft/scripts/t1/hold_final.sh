#!/usr/bin/env bash
# hold_final.sh <reg|lat|flap> - the last validation holds of the final build (hooks at their reviewed
# positions): the regression (specs/reglat.txt -> reg_final2), the latency spec (-> lat_final2) and
# the flap (-> flap_final2).
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
CR=$HERE/../../../common/cluster_run.sh
R=${R:-$HERE/../../results/20260930_t1}
cd "$HERE/../.."
case "$1" in
  reg) $CR -t t1-reg2 -- timeout -s KILL 880 env INTERLEAVE=1 STOP_AFTER_S=780 bash scripts/t1/hold_generic.sh scripts/t1/specs/reglat.txt $R/reg_final2 gate_test ;;
  lat) $CR -t t1-lat2 -- timeout -s KILL 880 env INTERLEAVE=1 STOP_AFTER_S=600 bash scripts/t1/hold_generic.sh scripts/t1/specs/lat.txt $R/lat_final2 ;;
  flap) $CR -t t1-flap2 -- timeout -s KILL 880 env STOP_AFTER_S=760 bash scripts/t1/flap_hold.sh $R/flap_final2 t1 5 0.5 6 15 ;;
  *) echo "unknown $1" >&2; exit 2 ;;
esac
