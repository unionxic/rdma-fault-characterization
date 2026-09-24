#!/usr/bin/env bash
# The S1 matrix in four cluster holds (each well under 15 min; the lock is released in between).
set -u
R=${1:?resultsdir}
cd "$(dirname "$0")"
CR=../../../common/cluster_run.sh
mkdir -p "$R/runs" "$R/lat"
$CR -w 7200 -t prio-ts1-A -- timeout 840 bash -c "bash batch.sh $R/runs none_b 30; bash batch.sh $R/runs f1_b 30; bash batch.sh $R/runs f1_t 10; bash batch.sh $R/runs off_f1_b 5; bash batch.sh $R/runs base_f1_b 5"
$CR -w 7200 -t prio-ts1-B -- timeout 840 bash -c "bash batch.sh $R/runs f3_b 10; bash batch.sh $R/runs f3_t 5; bash batch.sh $R/runs f1x5_b 10"
$CR -w 7200 -t prio-ts1-C -- timeout 840 bash -c "bash batch.sh $R/runs f2_b 30; bash batch.sh $R/runs f4_b 10; bash batch.sh $R/runs neg_norebase_t 5; bash batch.sh $R/runs neg_noring_t 5"
$CR -w 7200 -t prio-ts1-D -- timeout 840 bash lat_batch.sh $R/lat 15
