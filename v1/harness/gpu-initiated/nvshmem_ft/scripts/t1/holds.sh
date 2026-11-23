#!/usr/bin/env bash
# holds.sh <name> - the cluster holds of the T1 campaign (each <= 15 min, through cluster_run.sh).
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
CR=$HERE/../../../common/cluster_run.sh
R=${R:-$HERE/../../results/20260930_t1}
cd "$HERE/../.."
case "$1" in
  smoke1) $CR -t t1-smoke1 -- timeout -s KILL 880 bash scripts/t1/hold_generic.sh scripts/t1/specs/smoke1.txt $R/smoke1 gate_test ;;
  A) $CR -t t1-holdA -- timeout -s KILL 880 env INTERLEAVE=1 STOP_AFTER_S=800 bash scripts/t1/hold_generic.sh scripts/t1/specs/mainA.txt $R/mainA ;;
  B) $CR -t t1-holdB -- timeout -s KILL 880 env INTERLEAVE=1 STOP_AFTER_S=780 bash scripts/t1/hold_generic.sh scripts/t1/specs/mainB.txt $R/mainB ;;
  C) $CR -t t1-holdC -- timeout -s KILL 880 env INTERLEAVE=1 STOP_AFTER_S=780 bash scripts/t1/hold_generic.sh scripts/t1/specs/neg.txt $R/neg gate_test_sunny ;;
  D) $CR -t t1-holdD -- timeout -s KILL 880 bash -c "INTERLEAVE=1 STOP_AFTER_S=300 bash scripts/t1/hold_generic.sh scripts/t1/specs/f2a.txt $R/f2a; INTERLEAVE=1 STOP_AFTER_S=150 bash scripts/t1/hold_generic.sh scripts/t1/specs/neg2.txt $R/neg2; INTERLEAVE=1 STOP_AFTER_S=250 bash scripts/t1/hold_generic.sh scripts/t1/specs/lat.txt $R/lat" ;;
  # reg/lat_final/flap_t1 first ran on an intermediate build with the T1 device paths out of line
  # (sets *_outlined); the final build (inlined, as in neg2/f2a/lat) is re-validated by reg,
  # flap_t1_final and nogid_lat.
  reg) $CR -t t1-reg -- timeout -s KILL 880 env INTERLEAVE=1 STOP_AFTER_S=780 bash scripts/t1/hold_generic.sh scripts/t1/specs/reg.txt $R/reg_final gate_test ;;
  lat_final) $CR -t t1-latf -- timeout -s KILL 880 env INTERLEAVE=1 STOP_AFTER_S=700 bash scripts/t1/hold_generic.sh scripts/t1/specs/lat.txt $R/lat_final ;;
  flap_t1_final) $CR -t t1-flapt1f -- timeout -s KILL 880 env STOP_AFTER_S=760 bash scripts/t1/flap_hold.sh $R/flap_t1_final t1 5 0.5 6 15 ;;
  nogid_lat) $CR -t t1-nogidlat -- timeout -s KILL 880 bash -c "STOP_AFTER_S=250 KTIMEOUT=60 PROC_TIMEOUT=80 bash scripts/t1/flap_hold.sh $R/flap_nogid t1nogid 3 6; INTERLEAVE=1 STOP_AFTER_S=420 bash scripts/t1/hold_generic.sh scripts/t1/specs/lat.txt $R/lat_final" ;;
  lat) $CR -t t1-lat -- timeout -s KILL 880 env INTERLEAVE=1 STOP_AFTER_S=700 bash scripts/t1/hold_generic.sh scripts/t1/specs/lat.txt $R/lat ;;
  flap_v22) $CR -t t1-flapv22 -- timeout -s KILL 880 env STOP_AFTER_S=700 KTIMEOUT=45 PROC_TIMEOUT=65 bash scripts/t1/flap_hold.sh $R/flap_v22 v22 2 0.5 6 15 ;;
  flap_t1) $CR -t t1-flapt1 -- timeout -s KILL 880 env STOP_AFTER_S=760 bash scripts/t1/flap_hold.sh $R/flap_t1 t1 5 0.5 6 15 ;;
  flap_nogid) $CR -t t1-flapnogid -- timeout -s KILL 880 env STOP_AFTER_S=600 KTIMEOUT=60 PROC_TIMEOUT=80 bash scripts/t1/flap_hold.sh $R/flap_nogid t1nogid 3 6 ;;
  bisect) $CR -t t1-bisect -- timeout -s KILL 880 env INTERLEAVE=1 STOP_AFTER_S=780 bash scripts/t1/hold_generic.sh scripts/t1/specs/bisect.txt $R/bisect ;;
  fetch) $CR -t t1-fetch -- timeout -s KILL 880 env INTERLEAVE=1 STOP_AFTER_S=780 bash scripts/t1/hold_generic.sh scripts/t1/specs/fetch.txt $R/fetch ;;
  # final build after the code review: regression, flap, fetch, latency and the review cells
  reg_fixed) $CR -t t1-regf -- timeout -s KILL 880 env INTERLEAVE=1 STOP_AFTER_S=780 bash scripts/t1/hold_generic.sh scripts/t1/specs/reg.txt $R/reg_fixed gate_test ;;
  flap_fixed) $CR -t t1-flapf -- timeout -s KILL 880 env STOP_AFTER_S=760 bash scripts/t1/flap_hold.sh $R/flap_fixed t1 5 0.5 6 15 ;;
  fetch_fixed) $CR -t t1-fetchf -- timeout -s KILL 880 env INTERLEAVE=1 STOP_AFTER_S=780 bash scripts/t1/hold_generic.sh scripts/t1/specs/fetch.txt $R/fetch_fixed ;;
  review) $CR -t t1-review -- timeout -s KILL 880 bash -c "INTERLEAVE=0 STOP_AFTER_S=780 bash scripts/t1/hold_generic.sh scripts/t1/specs/review.txt $R/review; sudo -n iptables -S | grep t1sock | sed 's/^-A/-D/' | while read -r r; do sudo -n iptables \$r; done; echo iptables_t1sock_left=\$(sudo -n iptables -S | grep -c t1sock)" ;;
  cut25_lat) $CR -t t1-cut25 -- timeout -s KILL 880 bash -c "STOP_AFTER_S=300 KTIMEOUT=100 PROC_TIMEOUT=120 bash scripts/t1/flap_hold.sh $R/flap_cut25 t1 3 25; INTERLEAVE=1 STOP_AFTER_S=400 bash scripts/t1/hold_generic.sh scripts/t1/specs/lat.txt $R/lat_fixed" ;;
  dci2) $CR -t t1-dci2 -- timeout -s KILL 880 env INTERLEAVE=0 STOP_AFTER_S=700 bash scripts/t1/hold_generic.sh scripts/t1/specs/dci2.txt $R/dci_fill2 ;;
  *) echo "unknown hold $1" >&2; exit 2 ;;
esac
