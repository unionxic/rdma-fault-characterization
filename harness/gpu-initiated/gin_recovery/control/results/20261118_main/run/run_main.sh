#!/usr/bin/env bash
# run_main.sh <pass-name> <hold>...: gin-control main run, one chain of holds inside cluster_run.sh (via chain_gc.sh), results in main/
P=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad/agent_gc_main1
export SUNNY_SSH="unionxic@$(grep '^MGMT_B=' ~/.config/rdma-error/mgmt.env | cut -d= -f2)" RS_SET=gc_main1
N=$1; shift
echo "$(date '+%F %T') pass $N $* start" >> $P/attempts.txt
bash /home/unionxic/rdma-error-wt/gin-control/harness/gpu-initiated/gin_recovery/control/impl/test/chain_gc.sh $P/main "$@"
echo "$(date '+%F %T') pass $N $* end rc=$?" >> $P/attempts.txt
