#!/usr/bin/env bash
# Run S2 holds one after another, each as its own cluster_run.sh hold (<= 15 min; other users' runs can take the
# lock in between). The flap holds get a TERM before the KILL and a final teardown of the secondary addresses in
# the same hold. usage: chain.sh <resultsdir> <hold> [<hold> ...]
set -u
R=${1:?resultsdir}; shift
D=$(cd "$(dirname "$0")" && pwd)
CR=$D/../../../common/cluster_run.sh
GBH=$D/../../../../nccl-integration/stage2/gid_blackhole.sh
for H in "$@"; do
  case "$H" in
    d1|d2|d3|d4) $CR -w 14400 -t ts2-$H -- bash -c "timeout -k 20 850 bash $D/hold.sh $R $H; bash $GBH teardown >> $R/gbh_final_teardown_$H.txt 2>&1" \
                > "$R/hold_$H.out" 2>&1 ;;
    *) $CR -w 14400 -t ts2-$H -- timeout -s KILL 880 bash "$D/hold.sh" "$R" "$H" > "$R/hold_$H.out" 2>&1 ;;
  esac
  echo "$(date '+%F %T') hold $H rc=$?" >> "$R/chain.out"
done
