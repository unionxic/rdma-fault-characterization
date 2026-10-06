#!/usr/bin/env bash
# rerun_f4.sh <outroot> - re-run only the GP and GG F4 cells (10 + 10 trials) with the F4 settings
# that cells.sh lacked in the 2026-10-06 campaign (DEVIATIONS.md item 10). One cluster_run.sh call
# per stack, as in the campaign.
set -u
R=${1:?outroot}; mkdir -p "$R"; R=$(cd "$R" && pwd)
cd "$HOME/rdma-error"
C=harness/gpu-initiated/common/cluster_run.sh
CELLS=harness/gpu-initiated/propagation/campaign/cells.sh
echo "f4 rerun start $(date '+%F %T') commit $(git rev-parse --short HEAD)"
for s in gp gg; do
  $C -w 3600 -t prop-f4-$s -- timeout -s KILL 1800 env ONLY_FAULT=F4 bash "$CELLS" "$s" "$R"
  echo "stack $s exit $? at $(date '+%F %T')"
done
echo "f4 rerun end $(date '+%F %T')"
