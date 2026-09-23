#!/usr/bin/env bash
# collapsed-CQ stall diagnosis (no fault)
cd ~/rdma-error/harness/gpu-initiated/gin_q4
export Q4_WORKDIR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad/gi/gin_q4/work
O=results/20260923/diag/collapsed_stall.csv
mkdir -p $(dirname $O)
CQ_TYPE=collapsed CLASSIFY=0 WATCHDOG_S=40 bash scripts/run_trial.sh none timeout d1 $O 70 14
CQ_TYPE=collapsed CLASSIFY=1 WATCHDOG_S=40 EXTRA_ENV="NCCL_GIN_GDAKI_QP_DEPTH=256" bash scripts/run_trial.sh none timeout d2q256 $O 140 14
CQ_TYPE=ring CLASSIFY=1 WATCHDOG_S=40 EXTRA_ENV="NCCL_GIN_GDAKI_QP_DEPTH=256" bash scripts/run_trial.sh none timeout d3q256 $O 140 14
