#!/usr/bin/env bash
# hold_final3.sh <reg|flap|cut25> - third-round validation holds of the final build
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
CR=$HERE/../../../common/cluster_run.sh
R=${R:-$HERE/../../results/20260930_t1}
cd "$HERE/../.."
case "$1" in
  reg) $CR -t t1-reg3 -- timeout -s KILL 880 env INTERLEAVE=1 STOP_AFTER_S=780 bash scripts/t1/hold_generic.sh scripts/t1/specs/reglat.txt $R/reg_final3 gate_test ;;
  flap) $CR -t t1-flap3 -- timeout -s KILL 880 env STOP_AFTER_S=760 bash scripts/t1/flap_hold.sh $R/flap_final3 t1 5 0.5 6 15 ;;
  cut25) $CR -t t1-cut25_3 -- timeout -s KILL 880 env STOP_AFTER_S=400 KTIMEOUT=100 PROC_TIMEOUT=120 bash scripts/t1/flap_hold.sh $R/flap_cut25_3 t1 3 25 ;;
  *) echo "unknown $1" >&2; exit 2 ;;
esac
