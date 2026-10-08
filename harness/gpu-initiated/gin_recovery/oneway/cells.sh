#!/usr/bin/env bash
# gin-oneway: the new, control and ow-only cells of EXPERIMENT.md section 7 (one bounded batch; run inside a hold of
# hold.sh, itself inside ../../common/cluster_run.sh). Replication cells f1_b, f3_b, bidirf_sym_b and f4_b run through
# ../scripts/ts2/batch.sh with BUILD=ow; the pc latency reference through ../pair_check/cells.sh.
# usage: cells.sh <logdir> <cell> <build: ow|pcm|pc> <n> [start]
# Bundles: BUILD=ow -> $HOME/gi-bundle/gin_ts2/ow, BUILD=pcm -> .../pcm, BUILD=pc -> .../pc (all with the driver d4b1f082).
# Switches (EXPERIMENT.md 7):
#   NCCL_GIN_TS_TEST_SOCK_MUTE=<start ms>:<length ms>  on ONE rank (R0_ENV or R1_ENV) cuts only the direction INTO that
#                                                     rank; on both ranks (EXTRA_ENV) both directions
#   NCCL_GIN_TS_TEST_SOCK_UTO_MS=20000                 the unmuted rank's helper-socket TCP_USER_TIMEOUT (pcm, ow)
#   NCCL_GIN_TS_TEST_REFUSE_HELLO=1                    rank 1 refuses the first reconnect HELLO (pcm, ow)
# KILL0_MS (default 6500): KILL_DELAY_MS of ow_kill0_b, from rank 0's launch (EXPERIMENT.md 8: may change once after smoke).
set -u
L=${1:?logdir}; CELL=${2:?cell}; B=${3:?build}; N=${4:?n}; START=${5:-1}
T=$(cd "$(dirname "$0")/../scripts/ts2" && pwd)
run() { CELL=$CELL bash "$T/run_trial.sh" "$@"; }
BIDIR="GIN_TS_BIDIR_FUSED=1"
for ((k = START; k < START + N; k++)); do
  case "$CELL" in
    # rank 1 drops its inbound helper traffic (rank 0 -> rank 1 cut); rank 0's sockets time out after 20 s; local QP
    # error on rank 0 at 12 s
    ow_r1in_f1_b)   BUILD=$B TS=1 INJECT=12000 ABORT_WD_S=20 WATCHDOG_S=60 EXTRA_ENV="GIN_TS_RX_WAIT_S=10" \
                    R0_ENV="NCCL_GIN_TS_TEST_SOCK_UTO_MS=20000" R1_ENV="NCCL_GIN_TS_TEST_SOCK_MUTE=500:8000" \
                    run F1 blocking n$k "$L" 1000 16384 ;;
    # rank 0 drops its inbound helper traffic (rank 1 -> rank 0 cut); rank 1's sockets time out after 20 s; both
    # directions of traffic; local QP error on rank 1's context 1 (its sending context) at 6.5 s
    ow_r0in_f1r1_b) BUILD=$B TS=1 APP=bidir GAP_US=15000 ABORT_WD_S=20 WATCHDOG_S=60 EXTRA_ENV="$BIDIR GIN_TS_RX_WAIT_S=30" \
                    R0_ENV="NCCL_GIN_TS_TEST_SOCK_MUTE=500:8000" \
                    R1_ENV="NCCL_GIN_FAULT_INJECT=local_err:6500 NCCL_GIN_FAULT_INJECT_CTX=1 NCCL_GIN_TS_TEST_SOCK_UTO_MS=20000" \
                    run none blocking n$k "$L" 1000 16384 ;;
    # the same without the timeout switch (who times out first is a race)
    ow_r0in_nat_f1r1_b) BUILD=$B TS=1 APP=bidir GAP_US=15000 ABORT_WD_S=20 WATCHDOG_S=60 EXTRA_ENV="$BIDIR GIN_TS_RX_WAIT_S=30" \
                    R0_ENV="NCCL_GIN_TS_TEST_SOCK_MUTE=500:8000" \
                    R1_ENV="NCCL_GIN_FAULT_INJECT=local_err:6500 NCCL_GIN_FAULT_INJECT_CTX=1" \
                    run none blocking n$k "$L" 1000 16384 ;;
    # both ranks muted 300:8000; rank 0 (the lower rank) killed during the mute; rank 1 keeps sending to it
    ow_kill0_b)     BUILD=$B TS=1 APP=bidir GAP_US=15000 KILL_R0=1 KILL_DELAY_MS=${KILL0_MS:-6500} ABORT_WD_S=20 WATCHDOG_S=60 \
                    EXTRA_ENV="$BIDIR NCCL_GIN_TS_TEST_SOCK_MUTE=300:8000 GIN_TS_RX_WAIT_S=30" \
                    run none blocking n$k "$L" 1000 16384 ;;
    # both ranks muted 500:8000; rank 1 refuses the first reconnect HELLO; local QP error on rank 0 at 12 s
    ow_hello_f1_b)  BUILD=$B TS=1 INJECT=12000 ABORT_WD_S=20 WATCHDOG_S=60 \
                    EXTRA_ENV="NCCL_GIN_TS_TEST_SOCK_MUTE=500:8000 GIN_TS_RX_WAIT_S=10" R1_ENV="NCCL_GIN_TS_TEST_REFUSE_HELLO=1" \
                    run F1 blocking n$k "$L" 1000 16384 ;;
    lat_ow_on_4k)   BUILD=ow TS=1 run lat blocking n$k "$L" 3000 4096 ;;
    lat_ow_on_256k) BUILD=ow TS=1 run lat blocking n$k "$L" 3000 262144 ;;
    # replications with build ow (as ../pair_check/cells.sh f2rel_b, ../reconnect/cells.sh rc_mute8_f1_b, rc_mutekill_b)
    f2rel_b)        BUILD=$B TS=1 ABORT_WD_S=40 EXTRA_ENV="GIN_TS_RX_WAIT_S=20 GIN_TS_POST_ABORT_WAIT_S=3 NCCL_GIN_TS_USER_ABORT=1" \
                    run F2 blocking n$k "$L" 120 ;;
    rc_mute8_f1_b)  BUILD=$B TS=1 INJECT=12000 ABORT_WD_S=20 WATCHDOG_S=60 \
                    EXTRA_ENV="NCCL_GIN_TS_TEST_SOCK_MUTE=500:8000 GIN_TS_RX_WAIT_S=10" run F1 blocking n$k "$L" 1000 16384 ;;
    rc_mutekill_b)  BUILD=$B TS=1 KILL_DELAY_MS=6550 ABORT_WD_S=20 WATCHDOG_S=60 \
                    EXTRA_ENV="NCCL_GIN_TS_TEST_SOCK_MUTE=300:8000 GIN_TS_RX_WAIT_S=10" run F4 blocking n$k "$L" 1000 16384 ;;
    *) echo "unknown cell $CELL" >&2; exit 1 ;;
  esac
done
