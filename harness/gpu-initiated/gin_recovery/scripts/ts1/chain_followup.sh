#!/usr/bin/env bash
# Runs the follow-up holds one after another, each as its own cluster_run hold (the lock is released in
# between), after the smoke gate passed. fwcmd snapshots are taken inside each hold, before and after.
set -u
G=$(cd "$(dirname "$0")/../.." && pwd); R=$G/results/20260925_ts1; S=$G/scripts/ts1
python3 $S/smoke_check.py $R/v2_smoke2 > $R/v2_smoke2/_check.txt 2>&1 || { cat $R/v2_smoke2/_check.txt; exit 1; }
for H in ${HOLDS:-H1 H2 H3 H4}; do
  $G/../common/cluster_run.sh -w 14400 -t ts1b-$H -- timeout -s KILL 880 bash -c \
    "bash $S/fwcmd_snapshot.sh before-ts1b-$H > $R/v2_fwcmd/ts1b-${H}_before.txt 2>&1; \
     bash $S/followup_hold.sh $R $H > $R/v2_hold_$H.out 2>&1; \
     bash $S/fwcmd_snapshot.sh after-ts1b-$H > $R/v2_fwcmd/ts1b-${H}_after.txt 2>&1"
  echo "$H rc=$?"
done
