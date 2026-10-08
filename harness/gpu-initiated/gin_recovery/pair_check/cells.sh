#!/usr/bin/env bash
# gin-pair-check: the new, control and pc-only cells of EXPERIMENT.md section 7 (one bounded batch; run inside a hold of
# hold.sh, itself inside ../../common/cluster_run.sh). Replication cells on pc run through ../scripts/ts2/batch.sh with
# BUILD=pc; the pr and prd references through ../pair_reset/cells.sh.
# usage: cells.sh <logdir> <cell> <n> [start]
# Bundles: BUILD=pc  -> $HOME/gi-bundle/gin_ts2/pc  (this study's libnccl + the final step-2 driver d4b1f082)
#          BUILD=pcd -> $HOME/gi-bundle/gin_ts2/pcd (the same libnccl + gin-pair-reset's dual-context driver 4926edee)
# R1C2_LEAD (default 100) and CONFLICT_OFF (default 5): rank 1's hook lead/lag in pc_dual_f1c0_r1c2_b and pc_bidirf_conflict_b
# (EXPERIMENT.md 8: each may change once, after smoke, recorded in DEVIATIONS.md).
set -u
L=${1:?logdir}; CELL=${2:?cell}; N=${3:?n}; START=${4:-1}
T=$(cd "$(dirname "$0")/../scripts/ts2" && pwd)
run() { CELL=$CELL bash "$T/run_trial.sh" "$@"; }
for ((k = START; k < START + N; k++)); do
  inj=$(( 400 + (k * 137) % 700 ))   # two-context cells: ms after the GDAKI context's creation
  injb=$(( 500 + (k * 137) % 700 ))  # as ../scripts/ts2/batch.sh
  case "$CELL" in
    lat_pc_on_4k)   BUILD=pc TS=1 run lat blocking n$k "$L" 3000 4096 ;;
    lat_pc_on_256k) BUILD=pc TS=1 run lat blocking n$k "$L" 3000 262144 ;;
    # the receiving rank's own wait released at ncclCommAbort (as ../pair_reset/cells.sh f2rel_b, build pc)
    f2rel_b)        BUILD=pc TS=1 ABORT_WD_S=40 EXTRA_ENV="GIN_TS_RX_WAIT_S=20 GIN_TS_POST_ABORT_WAIT_S=3 NCCL_GIN_TS_USER_ABORT=1" \
                    run F2 blocking n$k "$L" 120 ;;
    # batch.sh's f3_b with the responder check off on both ranks (control)
    f3_b_nocheck)   BUILD=pc TS=1 INJECT=$injb EXTRA_ENV="NCCL_GIN_TS_PAIR_CHECK=0" run F3 blocking n$k "$L" 120 ;;
    # two contexts at once, 4 KiB x 3000 per context; a local QP error on rank 0's context-0 QP only (clean responder)
    pc_dual_f1c0_b)       BUILD=pcd TS=1 GAP_US=500 INJECT=$inj R0_ENV="NCCL_GIN_FAULT_INJECT_CTX=0" EXTRA_ENV="GIN_TS_DUAL=1" \
                          run F1 blocking n$k "$L" 3000 4096 ;;
    # the same, and rank 1's idle context-2 QP broken R1C2_LEAD ms earlier (a responder QP outside the scope)
    pc_dual_f1c0_r1c2_b)  BUILD=pcd TS=1 GAP_US=500 INJECT=$inj INJECT1=$(( inj - ${R1C2_LEAD:-100} )) \
                          R0_ENV="NCCL_GIN_FAULT_INJECT_CTX=0" R1_ENV="NCCL_GIN_FAULT_INJECT_CTX=2" EXTRA_ENV="GIN_TS_DUAL=1" \
                          run F1both blocking n$k "$L" 3000 4096 ;;
    # the clean-responder cell with rank 1's own pair reset off (control)
    pc_dual_f1c0_r1off_b) BUILD=pcd TS=1 GAP_US=500 INJECT=$inj R0_ENV="NCCL_GIN_FAULT_INJECT_CTX=0" \
                          R1_ENV="NCCL_GIN_TS_PAIR_RESET=0" EXTRA_ENV="GIN_TS_DUAL=1" run F1 blocking n$k "$L" 3000 4096 ;;
    # replications of gin-pair-reset's dual cells on pcd
    pc_dual_f3c0_b)       BUILD=pcd TS=1 GAP_US=2000 INJECT=$inj R1_ENV="NCCL_GIN_FAULT_INJECT_CTX=0" WATCHDOG_S=60 \
                          EXTRA_ENV="GIN_TS_DUAL=1" run F3 blocking n$k "$L" 3000 4096 ;;
    pc_dual_f1all_b)      BUILD=pcd TS=1 GAP_US=500 INJECT=$inj EXTRA_ENV="GIN_TS_DUAL=1" run F1 blocking n$k "$L" 3000 4096 ;;
    # simultaneous rounds with different scopes (as ../pair_reset/cells.sh pr_bidirf_conflict_b, build pc)
    pc_bidirf_conflict_b) i0=$(( 60 + (k * 7) % 50 )); BUILD=pc TS=1 APP=bidir GAP_US=0 INJECT=$i0 INJECT1=$(( i0 + ${CONFLICT_OFF:-5} )) \
                          R0_ENV="NCCL_GIN_FAULT_INJECT_CTX=0 NCCL_GIN_TS_TEST_STALL=20@quiesce" R1_ENV="NCCL_GIN_FAULT_INJECT_CTX=1" \
                          EXTRA_ENV="GIN_TS_BIDIR_FUSED=1" run F1both blocking n$k "$L" 8000 4096 ;;
    *) echo "unknown cell $CELL" >&2; exit 1 ;;
  esac
done
