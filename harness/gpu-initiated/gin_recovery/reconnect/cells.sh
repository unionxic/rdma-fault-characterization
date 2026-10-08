#!/usr/bin/env bash
# gin-reconnect: the new, control and rc-only cells of EXPERIMENT.md section 7 (one bounded batch; run inside a hold of
# hold.sh, itself inside ../../common/cluster_run.sh). Existing cells run through ../scripts/ts2/batch.sh with BUILD=rc,
# and the s2r latency reference through ../s2_close/cells.sh.
# usage: cells.sh <logdir> <cell> <n> [start]
# Bundle BUILD=rc -> $HOME/gi-bundle/gin_ts2/rc (this study's libnccl + the final step-2 driver d4b1f082).
# NCCL_GIN_TS_TEST_SOCK_MUTE=<start ms>:<length ms> goes to both ranks (EXTRA_ENV); times from each rank's helper start.
set -u
L=${1:?logdir}; CELL=${2:?cell}; N=${3:?n}; START=${4:-1}
T=$(cd "$(dirname "$0")/../scripts/ts2" && pwd)
run() { CELL=$CELL bash "$T/run_trial.sh" "$@"; }
for ((k = START; k < START + N; k++)); do
  case "$CELL" in
    lat_rc_on_4k)   BUILD=rc TS=1 run lat blocking n$k "$L" 3000 4096 ;;
    lat_rc_on_256k) BUILD=rc TS=1 run lat blocking n$k "$L" 3000 262144 ;;
    # the receiving rank's own wait released at ncclCommAbort (as ../s2_close/cells.sh f2rel_b, build rc)
    f2rel_b)        BUILD=rc TS=1 ABORT_WD_S=40 EXTRA_ENV="GIN_TS_RX_WAIT_S=20 GIN_TS_POST_ABORT_WAIT_S=3 NCCL_GIN_TS_USER_ABORT=1" \
                    run F2 blocking n$k "$L" 120 ;;
    # 8 s mute, then a local QP error at 12 s (the gin-s2-close mute8_f1_b condition)
    rc_mute8_f1_b)  BUILD=rc TS=1 INJECT=12000 ABORT_WD_S=20 WATCHDOG_S=60 \
                    EXTRA_ENV="NCCL_GIN_TS_TEST_SOCK_MUTE=500:8000 GIN_TS_RX_WAIT_S=10" run F1 blocking n$k "$L" 1000 16384 ;;
    rc_mute8off_b)  BUILD=rc TS=1 INJECT=12000 ABORT_WD_S=20 WATCHDOG_S=60 \
                    EXTRA_ENV="NCCL_GIN_TS_TEST_SOCK_MUTE=500:8000 GIN_TS_RX_WAIT_S=10 NCCL_GIN_TS_RECONNECT=0" \
                    run F1 blocking n$k "$L" 1000 16384 ;;
    # a peer QP error at 6 s during a mute that ends inside the 10 s bound (12.3 s) / outlasts it (30.3 s)
    rc_mutef3s_b)   BUILD=rc TS=1 INJECT=6000 ABORT_WD_S=20 WATCHDOG_S=60 \
                    EXTRA_ENV="NCCL_GIN_TS_TEST_SOCK_MUTE=300:12000 GIN_TS_RX_WAIT_S=30" run F3 blocking n$k "$L" 1000 16384 ;;
    rc_mutef3l_b)   BUILD=rc TS=1 INJECT=6000 ABORT_WD_S=40 WATCHDOG_S=60 \
                    EXTRA_ENV="NCCL_GIN_TS_TEST_SOCK_MUTE=300:30000 GIN_TS_RX_WAIT_S=30" run F3 blocking n$k "$L" 1000 16384 ;;
    # the peer killed during an 8 s mute (KILL_DELAY_MS from rank 1's launch; about 6.0 s after devComm creation)
    rc_mutekill_b)  BUILD=rc TS=1 KILL_DELAY_MS=6550 ABORT_WD_S=20 WATCHDOG_S=60 \
                    EXTRA_ENV="NCCL_GIN_TS_TEST_SOCK_MUTE=300:8000 GIN_TS_RX_WAIT_S=10" run F4 blocking n$k "$L" 1000 16384 ;;
    # 1 s mute (control)
    rc_mute1_f1_b)  BUILD=rc TS=1 INJECT=3000 EXTRA_ENV="NCCL_GIN_TS_TEST_SOCK_MUTE=500:1000" run F1 blocking n$k "$L" 300 16384 ;;
    *) echo "unknown cell $CELL" >&2; exit 1 ;;
  esac
done
