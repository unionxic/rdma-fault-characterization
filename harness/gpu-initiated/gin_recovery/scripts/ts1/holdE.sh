#!/usr/bin/env bash
# Hold E: cost attribution of the flag-on fast path (interleaved per repetition), and re-runs of the
# three trials that failed with a TCP port collision in the driver's own rendezvous socket.
set -u
R=${1:?resultsdir}
cd "$(dirname "$0")"
for k in 1 2 3 4 5; do
  for c in lat_on_4k lat_nogate_4k lat_nopoll_4k lat_gpufence_4k lat_off_4k \
           lat_on_256k lat_nogate_256k lat_nopoll_256k lat_gpufence_256k lat_off_256k; do
    bash batch.sh "$R/lat_attr" $c 1 $k
  done
done
bash batch.sh "$R/runs" off_f1_b 1 6
bash batch.sh "$R/lat" lat_base_4k 1 16
bash batch.sh "$R/lat" lat_on_4k 1 16
