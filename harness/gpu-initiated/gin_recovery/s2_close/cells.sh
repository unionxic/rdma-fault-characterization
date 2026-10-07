#!/usr/bin/env bash
# gin-s2-close: the new and control cells of EXPERIMENT.md section 7 (one bounded batch; run inside a hold of hold.sh,
# itself inside ../../common/cluster_run.sh). Existing cells (16/64/256 threads, bidirectional, F1, F3, F4, flag off,
# latency) run through ../scripts/ts2/batch.sh unchanged, with BUILD=s2r for the new-library re-runs.
# usage: cells.sh <logdir> <cell> <n> [start]
# Bundles: BUILD=s2r  -> $HOME/gi-bundle/gin_ts2/s2r     (this study's libnccl + the final step-2 driver d4b1f082)
#          BUILD=s2rget -> $HOME/gi-bundle/gin_ts2/s2rget (this study's libnccl + the get-mode driver)
set -u
L=${1:?logdir}; CELL=${2:?cell}; N=${3:?n}; START=${4:-1}
T=$(cd "$(dirname "$0")/../scripts/ts2" && pwd)
run() { CELL=$CELL bash "$T/run_trial.sh" "$@"; }
for ((k = START; k < START + N; k++)); do
  inj=$(( 500 + (k * 137) % 700 ))   # the fault-time formula of batch.sh (ms after devComm creation)
  case "$CELL" in
    # --- latency of the new library, interleaved with batch.sh's lat_* cells in the same hold ---
    lat_s2r_on_4k)   BUILD=s2r TS=1 run lat blocking n$k "$L" 3000 4096 ;;
    lat_s2r_on_256k) BUILD=s2r TS=1 run lat blocking n$k "$L" 3000 262144 ;;
    # --- the receiving rank's own wait released at ncclCommAbort (remote access error at iteration 10) ---
    f2rel_b)     BUILD=s2r TS=1 ABORT_WD_S=40 EXTRA_ENV="GIN_TS_RX_WAIT_S=20 GIN_TS_POST_ABORT_WAIT_S=3 NCCL_GIN_TS_USER_ABORT=1" \
                 run F2 blocking n$k "$L" 120 ;;
    f2rel_off_b) BUILD=s2r TS=1 ABORT_WD_S=40 EXTRA_ENV="GIN_TS_RX_WAIT_S=20 GIN_TS_POST_ABORT_WAIT_S=3 NCCL_GIN_TS_USER_ABORT=0" \
                 run F2 blocking n$k "$L" 120 ;;
    ringf2rel_b) BUILD=s2r TS=1 APP=burst GAP_US=15000 ABORT_WD_S=40 \
                 EXTRA_ENV="GIN_TS_BURST_K=128 GIN_TS_AGG=1 GIN_TS_RX_WAIT_S=20 GIN_TS_POST_ABORT_WAIT_S=3 NCCL_GIN_TS_USER_ABORT=1" \
                 run F2 blocking n$k "$L" 200 1024 ;;
    # --- a round with a get (RDMA READ) in its epoch; the rescue area switched off ---
    get_f1_b)    BUILD=s2rget TS=1 INJECT=$inj ABORT_WD_S=40 EXTRA_ENV="GIN_TS_GET=1 GIN_TS_RX_WAIT_S=20" \
                 run F1 blocking n$k "$L" 120 ;;
    get_none_b)  BUILD=s2rget TS=1 EXTRA_ENV="GIN_TS_GET=1" run none blocking n$k "$L" 120 ;;
    mt1024_norescue_b)   # batch.sh's mt1024_f1_b (p = 1024: 4 CTAs x 256 threads, 100 iterations, trigger multiplier < 70)
                 p=1024; m=70
                 BUILD=s2r TS=1 APP=burst GAP_US=0 INJECT=20000 ABORT_WD_S=40 WATCHDOG_S=60 \
                 R0_ENV="NCCL_GIN_FAULT_INJECT_AT=wqe:$(( 2 * p * (20 + (k * 13) % m) + (k * 3) % 64 ))" \
                 EXTRA_ENV="GIN_TS_TX_BLOCKS=4 GIN_TS_TX_THREADS=256 GIN_TS_BURST_K=1 GIN_TS_AGG=0 NCCL_GIN_TS_RESCUE_LAPS=0 GIN_TS_RX_WAIT_S=20" \
                 run F1 blocking n$k "$L" 100 256 ;;
    # --- the management socket muted on both ranks (drop filter; no FIN, no RST) ---
    mute8_f1_b)  BUILD=s2r TS=1 INJECT=12000 ABORT_WD_S=20 WATCHDOG_S=60 \
                 EXTRA_ENV="NCCL_GIN_TS_TEST_SOCK_MUTE=500:8000 GIN_TS_RX_WAIT_S=10" run F1 blocking n$k "$L" 1000 16384 ;;
    mute_f3_b)   BUILD=s2r TS=1 INJECT=6000 ABORT_WD_S=20 WATCHDOG_S=60 \
                 EXTRA_ENV="NCCL_GIN_TS_TEST_SOCK_MUTE=300:30000 GIN_TS_RX_WAIT_S=10" run F3 blocking n$k "$L" 1000 16384 ;;
    mute1_f1_b)  BUILD=s2r TS=1 INJECT=3000 EXTRA_ENV="NCCL_GIN_TS_TEST_SOCK_MUTE=500:1000" run F1 blocking n$k "$L" 300 16384 ;;
    *) echo "unknown cell $CELL" >&2; exit 1 ;;
  esac
done
