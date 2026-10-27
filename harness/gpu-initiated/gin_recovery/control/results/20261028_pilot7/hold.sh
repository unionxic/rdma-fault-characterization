#!/usr/bin/env bash
# hold.sh <resultsdir name> <hold>...: pilot 7's holds through chain_gc.sh (each inside cluster_run.sh) into the scratch folder <name>/
P=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad/agent_gc_pilot7
export SUNNY_SSH="unionxic@$(grep '^MGMT_B=' ~/.config/rdma-error/mgmt.env | cut -d= -f2)" RS_SET=gc_pilot7
N=$1; shift
echo "$(date '+%F %T') attempt $N $* start" >> $P/attempts.txt
bash /home/unionxic/rdma-error-wt/gin-control/harness/gpu-initiated/gin_recovery/control/impl/test/chain_gc.sh $P/$N "$@"
echo "$(date '+%F %T') attempt $N $* end rc=$?" >> $P/attempts.txt
