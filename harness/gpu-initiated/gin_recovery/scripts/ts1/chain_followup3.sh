#!/usr/bin/env bash
# Third-review holds H5, H6 one after another, each as its own cluster_run hold (non-prio), with
# read-only firmware-command snapshots inside each hold.
set -u
G=$(cd "$(dirname "$0")/../.." && pwd); R=$G/results/20260925_ts1; S=$G/scripts/ts1
mkdir -p $R/v3_fwcmd
for H in ${HOLDS:-H5 H6}; do
  $G/../common/cluster_run.sh -w 14400 -t ts1b-$H -- timeout -s KILL 880 bash -c \
    "bash $S/fwcmd_snapshot.sh before-ts1b-$H > $R/v3_fwcmd/ts1b-${H}_before.txt 2>&1; \
     bash $S/followup3_hold.sh $R $H > $R/v3_hold_$H.out 2>&1; \
     bash $S/fwcmd_snapshot.sh after-ts1b-$H > $R/v3_fwcmd/ts1b-${H}_after.txt 2>&1"
  echo "$H rc=$?"
done
