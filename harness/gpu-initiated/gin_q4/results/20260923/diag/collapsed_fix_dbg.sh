#!/usr/bin/env bash
cd ~/rdma-error/harness/gpu-initiated/gin_q4
export Q4_WORKDIR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad/gi/gin_q4/work
O=results/20260923/diag/collapsed_fix.csv
CQ_TYPE=collapsed CLASSIFY=0 WATCHDOG_S=40 bash scripts/run_trial.sh none timeout f1 $O 120 14
CQ_TYPE=collapsed CLASSIFY=1 WATCHDOG_S=40 bash scripts/run_trial.sh none timeout f2 $O 300 14
CQ_TYPE=collapsed CLASSIFY=1 WATCHDOG_S=60 bash scripts/run_trial.sh none blocking f3 $O 300 14
CQ_TYPE=collapsed_host CLASSIFY=1 WATCHDOG_S=30 bash scripts/run_trial.sh none timeout f4 $O 20 14
