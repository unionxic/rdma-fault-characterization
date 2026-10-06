#!/usr/bin/env bash
# run_all.sh - the full pre-registered campaign, one cluster_run.sh call per stack.
R=$(cd "$(dirname "$0")" && pwd)
cd "$HOME/rdma-error"
C=harness/gpu-initiated/common/cluster_run.sh
CELLS=harness/gpu-initiated/propagation/campaign/cells.sh
echo "campaign start $(date '+%F %T') commit $(git rev-parse --short HEAD)"
for sb in cpu:1800 gp:2400 gg:3600 gq:2400 nvo:2400 nvd:2400 nvf:1200 net:1800; do
  s=${sb%%:*}; b=${sb##*:}
  $C -w 3600 -t prop-$s -- timeout -s KILL "$b" bash "$CELLS" "$s" "$R"
  echo "stack $s exit $? at $(date '+%F %T')"
done
echo "campaign end $(date '+%F %T')"
