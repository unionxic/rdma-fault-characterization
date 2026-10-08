#!/usr/bin/env bash
# gin-harden: every cell of EXPERIMENT.md section 7 (one bounded batch; run inside a hold of hold.sh, itself inside
# ../../common/cluster_run.sh through chain.sh). All trials go through this folder's run_trial_hd.sh (kills only PIDs it
# recorded; see its header). The regression cells repeat the definitions of ../scripts/ts2/batch.sh,
# ../reconnect/cells.sh, ../oneway/cells.sh and ../pair_check/cells.sh with the build changed.
# usage: cells.sh <logdir> <cell> <build> <n> [start]
# Builds (bundle directories under $HOME/gi-bundle/gin_ts2): hd (this study, research build), hdp (production build),
# ow (gin-oneway, deployed), ow2 (gin-oneway's libnccl with this study's driver), stk (pristine NCCL v2.32.3-1).
set -u
L=${1:?logdir}; CELL=${2:?cell}; B=${3:?build}; N=${4:?n}; START=${5:-1}
D=$(cd "$(dirname "$0")" && pwd)
run() { CELL=$CELL BUILD=$B bash "$D/run_trial_hd.sh" "$@"; }
BIDIR="GIN_TS_BIDIR_FUSED=1"
MUTE8="NCCL_GIN_TS_TEST_SOCK_MUTE=500:8000"
for ((k = START; k < START + N; k++)); do
  inj=$(( 500 + (k * 137) % 700 ))   # as ../scripts/ts2/batch.sh: ms after the GDAKI context's creation
  inj2=$(( 400 + (k * 137) % 700 ))  # as ../pair_check/cells.sh (two-context cells)
  case "$CELL" in
    # ---------------- regression (EXPERIMENT.md 7, "재현") ----------------
    f1_b)    TS=1 INJECT=$inj run F1 blocking n$k "$L" 120 ;;
    f3_b)    TS=1 INJECT=$inj run F3 blocking n$k "$L" 120 ;;
    bidirf_sym_b) i0=$(( 60 + (k * 7) % 50 )); TS=1 APP=bidir GAP_US=0 INJECT=$i0 INJECT1=$(( i0 - 1 - k % 2 )) \
             EXTRA_ENV="$BIDIR" run F1both blocking n$k "$L" 8000 4096 ;;
    f4_b)    TS=1 GAP_US=30000 KILL_DELAY_MS=$(( 3500 + (k * 211) % 900 )) WATCHDOG_S=40 run F4 blocking n$k "$L" 200 ;;
    f2rel_b) TS=1 ABORT_WD_S=40 EXTRA_ENV="GIN_TS_RX_WAIT_S=20 GIN_TS_POST_ABORT_WAIT_S=3 NCCL_GIN_TS_USER_ABORT=1" \
             run F2 blocking n$k "$L" 120 ;;
    pc_dual_f1c0_r1c2_b) TS=1 GAP_US=500 INJECT=$inj2 INJECT1=$(( inj2 - 100 )) R0_ENV="NCCL_GIN_FAULT_INJECT_CTX=0" \
             R1_ENV="NCCL_GIN_FAULT_INJECT_CTX=2" EXTRA_ENV="GIN_TS_DUAL=1" run F1both blocking n$k "$L" 3000 4096 ;;
    rc_mute8_f1_b) TS=1 INJECT=12000 ABORT_WD_S=20 WATCHDOG_S=60 EXTRA_ENV="$MUTE8 GIN_TS_RX_WAIT_S=10" \
             run F1 blocking n$k "$L" 1000 16384 ;;
    rc_mutekill_b) TS=1 KILL_DELAY_MS=6550 ABORT_WD_S=20 WATCHDOG_S=60 \
             EXTRA_ENV="NCCL_GIN_TS_TEST_SOCK_MUTE=300:8000 GIN_TS_RX_WAIT_S=10" run F4 blocking n$k "$L" 1000 16384 ;;
    ow_r1in_f1_b) TS=1 INJECT=12000 ABORT_WD_S=20 WATCHDOG_S=60 EXTRA_ENV="GIN_TS_RX_WAIT_S=10" \
             R0_ENV="NCCL_GIN_TS_TEST_SOCK_UTO_MS=20000" R1_ENV="$MUTE8" run F1 blocking n$k "$L" 1000 16384 ;;
    ow_r0in_f1r1_b) TS=1 APP=bidir GAP_US=15000 ABORT_WD_S=20 WATCHDOG_S=60 EXTRA_ENV="$BIDIR GIN_TS_RX_WAIT_S=30" \
             R0_ENV="$MUTE8" \
             R1_ENV="NCCL_GIN_FAULT_INJECT=local_err:6500 NCCL_GIN_FAULT_INJECT_CTX=1 NCCL_GIN_TS_TEST_SOCK_UTO_MS=20000" \
             run none blocking n$k "$L" 1000 16384 ;;
    ow_kill0_b) TS=1 APP=bidir GAP_US=15000 KILL_R0=1 KILL_DELAY_MS=6500 ABORT_WD_S=20 WATCHDOG_S=60 \
             EXTRA_ENV="$BIDIR NCCL_GIN_TS_TEST_SOCK_MUTE=300:8000 GIN_TS_RX_WAIT_S=30" run none blocking n$k "$L" 1000 16384 ;;
    ow_hello_f1_b) TS=1 INJECT=12000 ABORT_WD_S=20 WATCHDOG_S=60 EXTRA_ENV="$MUTE8 GIN_TS_RX_WAIT_S=10" \
             R1_ENV="NCCL_GIN_TS_TEST_REFUSE_HELLO=1" run F1 blocking n$k "$L" 1000 16384 ;;
    # ---------------- new cells (EXPERIMENT.md 7, "새 셀") ----------------
    # 1b: refusal once / twice. Both ranks muted 500:8000 (both sockets time out: unknown); rank 1 closes its listen
    # socket from 8000 ms for 1200 ms (one refused re-dial of rank 0) or 3000 ms (two, >= 1000 ms apart); local QP error
    # on rank 0 at 12 s
    hd_ref1_f1_b) TS=1 INJECT=12000 ABORT_WD_S=20 WATCHDOG_S=60 EXTRA_ENV="$MUTE8 GIN_TS_RX_WAIT_S=10" \
             R1_ENV="NCCL_GIN_TS_TEST_LISTEN_GAP=8000:1200" run F1 blocking n$k "$L" 1000 16384 ;;
    hd_ref2_f1_b) TS=1 INJECT=12000 ABORT_WD_S=20 WATCHDOG_S=60 EXTRA_ENV="$MUTE8 GIN_TS_RX_WAIT_S=10" \
             R1_ENV="NCCL_GIN_TS_TEST_LISTEN_GAP=8000:3000" run F1 blocking n$k "$L" 1000 16384 ;;
    # 1b: wrong nonce. Both ranks muted 500:8000; rank 0's first reconnect HELLO carries a wrong nonce
    hd_nonce_f1_b) TS=1 INJECT=12000 ABORT_WD_S=20 WATCHDOG_S=60 EXTRA_ENV="$MUTE8 GIN_TS_RX_WAIT_S=10" \
             R0_ENV="NCCL_GIN_TS_TEST_BAD_NONCE=1" run F1 blocking n$k "$L" 1000 16384 ;;
    # 1b: a reset inside a round. Rank 1 muted 500:8000 (inbound), rank 0's sockets time out after 20 s, so rank 1's
    # kernel resets the connection at about 5.1 s; rank 0's local QP error at 3 s starts a round that stalls 4 s after its
    # quiesce (existing test switch), so the reset arrives inside it. Both builds (the switches exist in ow).
    hd_rround_f1_b) TS=1 INJECT=3000 ABORT_WD_S=20 WATCHDOG_S=60 EXTRA_ENV="GIN_TS_RX_WAIT_S=30" \
             R0_ENV="NCCL_GIN_TS_TEST_SOCK_UTO_MS=20000 NCCL_GIN_TS_TEST_STALL=4000@quiesce" R1_ENV="$MUTE8" \
             run F1 blocking n$k "$L" 1000 16384 ;;
    # 1b: a receive-only rank whose peer dies: rank 0 (the sender) killed 3 s after its launch, no mute; rank 1 only
    # receives (its waits are bounded by GIN_TS_RX_WAIT_S=15)
    hd_rxdeath_b) TS=1 KILL_R0=1 KILL_DELAY_MS=3000 ABORT_WD_S=20 WATCHDOG_S=60 EXTRA_ENV="GIN_TS_RX_WAIT_S=15" \
             run none blocking n$k "$L" 1000 16384 ;;
    # 1c: the GPU full of an application kernel during the recovery (both ranks: GIN_TS_HOG_MS=3000)
    hd_hog_f1_b) TS=1 INJECT=$inj EXTRA_ENV="GIN_TS_HOG_MS=3000" run F1 blocking n$k "$L" 120 ;;
    # 1c: a slow firmware phase. hd: rank 0's commit phase sleeps 8 s (test switch, inside the watched phase);
    # ow: the existing stall of 8 s after the commit (no firmware-phase bound there)
    hd_fwslow_f1_b)
      if [ "$B" = ow ]; then sw="NCCL_GIN_TS_TEST_STALL=8000@commit"; else sw="NCCL_GIN_TS_TEST_FW_DELAY=8000@commit"; fi
      TS=1 INJECT=$inj ABORT_WD_S=30 WATCHDOG_S=60 R0_ENV="$sw" run F1 blocking n$k "$L" 120 ;;
    # 1c: a stalled device-state copy (hd only): the first round's stream is held 4 s
    hd_copystall_f1_b) TS=1 INJECT=$inj ABORT_WD_S=30 WATCHDOG_S=60 R0_ENV="NCCL_GIN_TS_TEST_COPY_STALL=4000" \
             run F1 blocking n$k "$L" 120 ;;
    # 1d: re-post plan rejected on the second QP (hd only): both directions on two contexts, full-scope rounds
    hd_repost_f1_b) TS=1 APP=bidir INJECT=$inj ABORT_WD_S=30 WATCHDOG_S=60 \
             EXTRA_ENV="$BIDIR NCCL_GIN_TS_PAIR_RESET=0 GIN_TS_RX_WAIT_S=10" R0_ENV="NCCL_GIN_TS_TEST_BAD_REPOST=1" \
             run F1 blocking n$k "$L" 400 16384 ;;
    # 2c: escalation. Five local QP errors on rank 0 (the k-th 300 ms after the commit of the (k-1)-th); cap 3 rounds in
    # 10 s on both ranks (the variables do nothing in ow)
    hd_esc_f1_b) TS=1 INJECT="800,300,300,300,300" ABORT_WD_S=20 WATCHDOG_S=60 \
             EXTRA_ENV="NCCL_GIN_TS_ESCALATE_ROUNDS=3 NCCL_GIN_TS_ESCALATE_WINDOW_MS=10000" run F1 blocking n$k "$L" 200 ;;
    # 3: shrink hand-off. Both directions; rank 1 killed 3.5 s after the runner starts it; rank 0 shrinks to itself
    hd_shrink_b) TS=1 APP=bidir KILL_DELAY_MS=3500 ABORT_WD_S=30 WATCHDOG_S=90 \
             EXTRA_ENV="$BIDIR GIN_TS_RX_WAIT_S=60" R0_ENV="GIN_TS_SHRINK=1 GIN_TS_HO_WAIT_S=3 GIN_TS_POST_ABORT_WAIT_S=10" \
             run F4 blocking n$k "$L" 400 16384 ;;
    # ---------------- production build (hdp) and latency ----------------
    lat_4k)   TS=1 run lat blocking n$k "$L" 3000 4096 ;;
    lat_256k) TS=1 run lat blocking n$k "$L" 3000 262144 ;;
    # a kill without any hook (as f4_b)
    hdp_kill_b) TS=1 GAP_US=30000 KILL_DELAY_MS=$(( 3500 + (k * 211) % 900 )) WATCHDOG_S=40 run F4 blocking n$k "$L" 200 ;;
    # a management-network outage without any test switch: fixed helper port 51700 on both ranks; rain drops sunny's
    # packets to/from ports 51700..51715 from 2 s after rank 0's kernel launch, for 8 s (run_trial_hd.sh MGMT_MUTE)
    hdp_mute_b) TS=1 MGMT_PORT=51700 MGMT_MUTE=2000:8000 ABORT_WD_S=20 WATCHDOG_S=60 \
             EXTRA_ENV="NCCL_GIN_TS_PORT=51700 GIN_TS_RX_WAIT_S=20" run none blocking n$k "$L" 1000 16384 ;;
    # ---------------- IB timeout 20 (item 4) ----------------
    # the peer's QP error with the default ack timeout: blocking (no device-side timeout) and timeout mode (8 s)
    to20_f3_b) TS=1 IB_TIMEOUT=20 INJECT=700 ABORT_WD_S=20 WATCHDOG_S=110 EXTRA_ENV="GIN_TS_RX_WAIT_S=120" \
             run F3 blocking n$k "$L" 120 ;;
    to20_f3_t) TS=1 IB_TIMEOUT=20 INJECT=700 DEV_TIMEOUT_S=8 ABORT_WD_S=20 WATCHDOG_S=60 EXTRA_ENV="GIN_TS_RX_WAIT_S=20" \
             run F3 timeout n$k "$L" 120 ;;
    *) echo "unknown cell $CELL" >&2; exit 1 ;;
  esac
done
