#!/usr/bin/env bash
# gin-pair-reset: the new, control and pr-only cells of EXPERIMENT.md section 7 (one bounded batch; run inside a hold of
# hold.sh, itself inside ../../common/cluster_run.sh). Replication cells run through ../scripts/ts2/batch.sh with BUILD=pr,
# and the rc latency reference through ../reconnect/cells.sh.
# usage: cells.sh <logdir> <cell> <n> [start]
# Bundles: BUILD=pr  -> $HOME/gi-bundle/gin_ts2/pr  (this study's libnccl + the final step-2 driver d4b1f082)
#          BUILD=prd -> $HOME/gi-bundle/gin_ts2/prd (the same libnccl + the dual-context driver, GIN_TS_DUAL=1)
# NCCL_GIN_FAULT_INJECT_CTX=<c> (the fault hook moves only context c's QPs) goes to the faulting rank (R0_ENV / R1_ENV).
# CONFLICT_OFF (default 5): rank 1's hook delay minus rank 0's in pr_bidirf_conflict_b (EXPERIMENT.md 8: changed at most
# once, after smoke, recorded in DEVIATIONS.md).
set -u
L=${1:?logdir}; CELL=${2:?cell}; N=${3:?n}; START=${4:-1}
T=$(cd "$(dirname "$0")/../scripts/ts2" && pwd)
run() { CELL=$CELL bash "$T/run_trial.sh" "$@"; }
for ((k = START; k < START + N; k++)); do
  inj=$(( 400 + (k * 137) % 700 ))   # ms after the GDAKI context's creation
  case "$CELL" in
    lat_pr_on_4k)   BUILD=pr TS=1 run lat blocking n$k "$L" 3000 4096 ;;
    lat_pr_on_256k) BUILD=pr TS=1 run lat blocking n$k "$L" 3000 262144 ;;
    # the receiving rank's own wait released at ncclCommAbort (as ../reconnect/cells.sh f2rel_b, build pr)
    f2rel_b)        BUILD=pr TS=1 ABORT_WD_S=40 EXTRA_ENV="GIN_TS_RX_WAIT_S=20 GIN_TS_POST_ABORT_WAIT_S=3 NCCL_GIN_TS_USER_ABORT=1" \
                    run F2 blocking n$k "$L" 120 ;;
    # two contexts at once, 4 KiB x 3000 per context; a local QP error on rank 0's context-0 QP only
    pr_dual_f1c0_b)      BUILD=prd TS=1 GAP_US=500 INJECT=$inj R0_ENV="NCCL_GIN_FAULT_INJECT_CTX=0" EXTRA_ENV="GIN_TS_DUAL=1" \
                         run F1 blocking n$k "$L" 3000 4096 ;;
    # the same with the pair reset off: the full-reset reference (same hold, interleaved)
    pr_dual_f1c0_full_b) BUILD=prd TS=1 GAP_US=500 INJECT=$inj R0_ENV="NCCL_GIN_FAULT_INJECT_CTX=0" \
                         EXTRA_ENV="GIN_TS_DUAL=1 NCCL_GIN_TS_PAIR_RESET=0" run F1 blocking n$k "$L" 3000 4096 ;;
    # a peer QP error on rank 1's context-0 QP only (retry exceeded at rank 0 after ~3.5 s); 2 ms gap: a ~6 s loop
    pr_dual_f3c0_b)      BUILD=prd TS=1 GAP_US=2000 INJECT=$inj R1_ENV="NCCL_GIN_FAULT_INJECT_CTX=0" WATCHDOG_S=60 \
                         EXTRA_ENV="GIN_TS_DUAL=1" run F3 blocking n$k "$L" 3000 4096 ;;
    # the stock hook: every context's QP of rank 0 to ERR (the fallback)
    pr_dual_f1all_b)     BUILD=prd TS=1 GAP_US=500 INJECT=$inj EXTRA_ENV="GIN_TS_DUAL=1" run F1 blocking n$k "$L" 3000 4096 ;;
    # no fault (control)
    pr_dual_none_b)      BUILD=prd TS=1 GAP_US=500 EXTRA_ENV="GIN_TS_DUAL=1" run none blocking n$k "$L" 3000 4096 ;;
    # simultaneous rounds with different scopes: bidir in one kernel (rank 0 sends on context 0, rank 1 on context 1);
    # rank 0's context-0 QP fails first and its helper stalls 20 ms after its quiesce; rank 1's context-1 QP fails
    # CONFLICT_OFF ms later
    pr_bidirf_conflict_b) i0=$(( 60 + (k * 7) % 50 )); BUILD=pr TS=1 APP=bidir GAP_US=0 INJECT=$i0 INJECT1=$(( i0 + ${CONFLICT_OFF:-5} )) \
                         R0_ENV="NCCL_GIN_FAULT_INJECT_CTX=0 NCCL_GIN_TS_TEST_STALL=20@quiesce" R1_ENV="NCCL_GIN_FAULT_INJECT_CTX=1" \
                         EXTRA_ENV="GIN_TS_BIDIR_FUSED=1" run F1both blocking n$k "$L" 8000 4096 ;;
    *) echo "unknown cell $CELL" >&2; exit 1 ;;
  esac
done
