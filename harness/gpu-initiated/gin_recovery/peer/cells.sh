#!/usr/bin/env bash
# gin-peer: every cell of EXPERIMENT.md section 7 (one bounded batch; run inside a hold of hold.sh, itself inside
# ../../common/cluster_run.sh through chain.sh). Two-rank cells run this folder's run_trial_hq.sh (gin_ts2 of the bundle
# <build>); N-rank cells run this folder's run_mr_hq.sh (gin_mr of the bundle mr/hq with the libnccl of <build>). Both
# runners kill only PIDs they recorded and pick a checked rendezvous port below the ephemeral range (portpick.sh).
# usage: cells.sh <logdir> <cell> <build> <n> [start]
# Builds: hq (this study, research), hqp (production, same source), hf and hfp (gin-handoff bundles, deployed: controls and
# the latency baseline). For an N-rank cell <build> is the libnccl (LIB); the driver is always mr/hq (MRKEY=hq: compiled
# against the hq headers; with the hf library its device code behaves as hf's, EXPERIMENT.md 9.3).
# Regression cells repeat the definitions of ../harden/cells.sh and ../multirank/cells.sh with the runner changed.
set -u
L=${1:?logdir}; CELL=${2:?cell}; B=${3:?build}; NRUN=${4:?n}; START=${5:-1}
D=$(cd "$(dirname "$0")" && pwd)
RES=$(dirname "$L")   # the results directory (hold.sh passes <resultsdir>/<subdir>)
run() { CELL=$CELL BUILD=$B bash "$D/run_trial_hq.sh" "$@"; }
mr() { CELL=$CELL LIB=$B MRKEY=hq ABORT_WD_S=20 bash "$D/run_mr_hq.sh" "$@"; }
BIDIR="GIN_TS_BIDIR_FUSED=1"
# N-rank timing (as ../multirank/cells.sh, kept): hook F_MS after the GDAKI context is created, kill KILL_MS after the
# runner starts the killed rank; F2_MS: the second hook of pq4_fwslow (rank 2, edge 2>0), after rank 0's overrun round
F_MS=${F_MS:-6000}; KILL_MS=${KILL_MS:-9000}; F2_MS=${F2_MS:-11500}
ctx() { local a=$1 b=$2 n=$3; echo $(( a * (n - 1) + (b < a ? b : b - 1) )); }
hook() { echo "NCCL_GIN_FAULT_INJECT=local_err:$F_MS NCCL_GIN_FAULT_INJECT_CTX=$(ctx "$1" "$2" "$3")"; }
BASE="GIN_TS_RX_WAIT_S=10"
streak() {  # after trial $1: two trials in a row that left a process behind write $RES/STOP_left (EXPERIMENT.md 8)
  local left; left=$(sed -n 's/.* left=\([0-9]*\) .*/\1/p' "$L/${CELL}_$1_meta.txt" 2>/dev/null)
  if [ -n "$left" ] && [ "$left" -gt 0 ]; then
    echo $(( $(cat "$RES/LEFT_STREAK" 2>/dev/null || echo 0) + 1 )) > "$RES/LEFT_STREAK"
  else
    echo 0 > "$RES/LEFT_STREAK"
  fi
  if [ "$(cat "$RES/LEFT_STREAK")" -ge 2 ]; then
    echo "$(date '+%F %T') ${CELL}_$1: a process left behind in two trials in a row" | tee -a "$RES/STOP_left"
  fi
}
for ((k = START; k < START + NRUN; k++)); do
  if [ -e "$RES/STOP_left" ] || [ -e "$RES/STOP_mlx5" ] || [ -e "$RES/STOP_cuda" ]; then
    echo "skipped ${CELL}_n$k: STOP file" >&2; break
  fi
  inj=$(( 500 + (k * 137) % 700 ))   # as ../scripts/ts2/batch.sh: ms after the GDAKI context's creation
  t=n$k
  case "$CELL" in
    # ================= two ranks (run_trial_hq.sh) =================
    # ---- regression (../harden/cells.sh definitions) ----
    f1_b)    TS=1 INJECT=$inj run F1 blocking $t "$L" 120 ;;
    f3_b)    TS=1 INJECT=$inj run F3 blocking $t "$L" 120 ;;
    bidirf_sym_b) i0=$(( 60 + (k * 7) % 50 )); TS=1 APP=bidir GAP_US=0 INJECT=$i0 INJECT1=$(( i0 - 1 - k % 2 )) \
             EXTRA_ENV="$BIDIR" run F1both blocking $t "$L" 8000 4096 ;;
    f4_b)    TS=1 GAP_US=30000 KILL_DELAY_MS=$(( 3500 + (k * 211) % 900 )) WATCHDOG_S=40 run F4 blocking $t "$L" 200 ;;
    f2rel_b) TS=1 ABORT_WD_S=40 EXTRA_ENV="GIN_TS_RX_WAIT_S=20 GIN_TS_POST_ABORT_WAIT_S=3 NCCL_GIN_TS_USER_ABORT=1" \
             run F2 blocking $t "$L" 120 ;;
    hd_rxdeath_b) TS=1 KILL_R0=1 KILL_DELAY_MS=3000 ABORT_WD_S=20 WATCHDOG_S=60 EXTRA_ENV="GIN_TS_RX_WAIT_S=15" \
             run none blocking $t "$L" 1000 16384 ;;
    hdp_kill_b) TS=1 GAP_US=30000 KILL_DELAY_MS=$(( 3500 + (k * 211) % 900 )) WATCHDOG_S=40 run F4 blocking $t "$L" 200 ;;
    lat_4k)   TS=1 run lat blocking $t "$L" 3000 4096 ;;
    lat_256k) TS=1 run lat blocking $t "$L" 3000 262144 ;;
    # ---- 3a: the re-post plan, validated on both ranks before either commits ----
    # the responder (rank 1) rejects its plan's second QP (both directions on two contexts, full-scope rounds)
    pq_repost_r1_b) TS=1 APP=bidir INJECT=$inj ABORT_WD_S=30 WATCHDOG_S=60 \
             EXTRA_ENV="$BIDIR NCCL_GIN_TS_PAIR_RESET=0 GIN_TS_RX_WAIT_S=10" R1_ENV="NCCL_GIN_TS_TEST_BAD_REPOST=1" \
             run F1 blocking $t "$L" 400 16384 ;;
    # regression: the initiator (rank 0) rejects (../harden/cells.sh hd_repost_f1_b)
    hd_repost_f1_b) TS=1 APP=bidir INJECT=$inj ABORT_WD_S=30 WATCHDOG_S=60 \
             EXTRA_ENV="$BIDIR NCCL_GIN_TS_PAIR_RESET=0 GIN_TS_RX_WAIT_S=10" R0_ENV="NCCL_GIN_TS_TEST_BAD_REPOST=1" \
             run F1 blocking $t "$L" 400 16384 ;;
    # ---- 3b at two ranks: an 8 s commit phase (../harden/cells.sh hd_fwslow_f1_b, hq form) ----
    hd_fwslow_f1_b) TS=1 INJECT=$inj ABORT_WD_S=30 WATCHDOG_S=60 R0_ENV="NCCL_GIN_TS_TEST_FW_DELAY=8000@commit" \
             run F1 blocking $t "$L" 120 ;;
    # ---- 3c: a round cancelled while waiting for the ACK, its responder already committed ----
    # The initiating rank's helper sockets drop everything they receive from 500 ms to 8500 ms after its helper started
    # (test switch); its local QP error at 1500 ms starts a round whose REQ goes out and is executed by the peer, while
    # the ACK and the TCP acknowledgements come back to a muted socket: both sockets end with ETIMEDOUT about 5 s later,
    # the initiator cancels (retry) and the committed responder declines. After the mute the initiator reconnects: the
    # lower rank re-dials (HELLO, _f1_b), the higher rank probes (PROBE, _f1r1_b).
    pq_ackrace_f1_b) TS=1 INJECT=1500 ABORT_WD_S=20 WATCHDOG_S=60 EXTRA_ENV="GIN_TS_RX_WAIT_S=10" \
             R0_ENV="NCCL_GIN_TS_TEST_SOCK_MUTE=500:8000" run F1 blocking $t "$L" 1000 16384 ;;
    pq_ackrace_f1r1_b) TS=1 APP=bidir GAP_US=15000 ABORT_WD_S=20 WATCHDOG_S=60 EXTRA_ENV="$BIDIR GIN_TS_RX_WAIT_S=30" \
             R1_ENV="NCCL_GIN_FAULT_INJECT=local_err:1500 NCCL_GIN_FAULT_INJECT_CTX=1 NCCL_GIN_TS_TEST_SOCK_MUTE=500:8000" \
             run none blocking $t "$L" 1000 16384 ;;
    # ---- 4: cause-based shrink hand-off at two ranks ----
    # a cause on rank 0 (its round's first device-state copy is held 4 s: copy timeout, decline of rank 1); rank 0 then
    # shrinks to itself, excluding the live rank 1
    pq_copystall_shrink_b) TS=1 INJECT=$inj ABORT_WD_S=30 WATCHDOG_S=60 \
             R0_ENV="NCCL_GIN_TS_TEST_COPY_STALL=4000 GIN_TS_SHRINK=1 GIN_TS_HO_WAIT_S=3" run F1 blocking $t "$L" 120 ;;
    # a cause on rank 1 (the responder's copy is held: it NACKs and declines; rank 0 declines on the NACK); rank 0 shrinks
    pq_copystall1_shrink_b) TS=1 INJECT=$inj ABORT_WD_S=30 WATCHDOG_S=60 R1_ENV="NCCL_GIN_TS_TEST_COPY_STALL=4000" \
             R0_ENV="GIN_TS_SHRINK=1 GIN_TS_HO_WAIT_S=3" run F1 blocking $t "$L" 120 ;;
    # regression: the peer died (../harden/cells.sh hd_shrink_b)
    hd_shrink_b) TS=1 APP=bidir KILL_DELAY_MS=3500 ABORT_WD_S=30 WATCHDOG_S=90 \
             EXTRA_ENV="$BIDIR GIN_TS_RX_WAIT_S=60" R0_ENV="GIN_TS_SHRINK=1 GIN_TS_HO_WAIT_S=3 GIN_TS_POST_ABORT_WAIT_S=10" \
             run F4 blocking $t "$L" 400 16384 ;;
    # ---- port fix: a held first candidate and a decoy listener, then f1_b ----
    pq_rdv_b) TS=1 INJECT=$inj RDV_DECOY=1 PORT_OCCUPY=1 run F1 blocking $t "$L" 120 ;;
    # ================= four ranks (run_mr_hq.sh) =================
    # ---- 2: per-peer abort words. SIGKILL of rank 3 (../multirank/cells.sh definitions) ----
    mr4_kill3_peer) N=4 KILL_RANK=3 KILL_DELAY_MS=$KILL_MS FLUSH=peer EXTRA_ENV="$BASE GIN_MR_GRACE_S=40" mr $t "$L" ;;
    mr4_kill3)      N=4 KILL_RANK=3 KILL_DELAY_MS=$KILL_MS EXTRA_ENV="$BASE GIN_MR_GRACE_S=40" mr $t "$L" ;;
    # ---- 3b: a firmware overrun declines its round only. Rank 0's round with rank 1 (edge 0>1) spends 4 s in its commit
    # phase (the watchdog trips at 3 s); later rank 2's local QP error on edge 2>0 needs a round with rank 0 ----
    pq4_fwslow) N=4 FLUSH=peer EXTRA_ENV="$BASE GIN_MR_GRACE_S=40" \
             R0_ENV="$(hook 0 1 4) NCCL_GIN_TS_TEST_FW_DELAY=4000@commit" \
             R2_ENV="NCCL_GIN_FAULT_INJECT=local_err:$F2_MS NCCL_GIN_FAULT_INJECT_CTX=$(ctx 2 0 4)" mr $t "$L" ;;
    # ---- 4 at four ranks: the survivors shrink rank 3 away after its death and run traffic on a devComm of the child ----
    pq4_kill3_shrink) N=4 KILL_RANK=3 KILL_DELAY_MS=$KILL_MS FLUSH=peer WATCHDOG_S=100 \
             EXTRA_ENV="$BASE GIN_MR_GRACE_S=40 GIN_MR_SHRINK=3 GIN_MR_CHILD=1 GIN_MR_PHASE_S=40" mr $t "$L" ;;
    # ---- 4 at four ranks: a cause on rank 0 (its round with rank 1 hits a held copy); ranks 0, 2, 3 shrink rank 1 away ----
    pq4_local_shrink) N=4 FLUSH=peer WATCHDOG_S=80 EXTRA_ENV="$BASE GIN_MR_GRACE_S=40 GIN_MR_SHRINK=1 GIN_MR_PHASE_S=12" \
             R0_ENV="$(hook 0 1 4) NCCL_GIN_TS_TEST_COPY_STALL=4000" mr $t "$L" ;;
    # ---- port fix at four ranks ----
    pq4_rdv) N=4 RDV_DECOY=1 PORT_OCCUPY=1 EXTRA_ENV="$BASE" mr $t "$L" ;;
    # ---- regression (../multirank/cells.sh definitions) ----
    mr4_none)   N=4 EXTRA_ENV="$BASE" mr $t "$L" ;;
    mr4_f1_01)  N=4 EXTRA_ENV="$BASE" R0_ENV="$(hook 0 1 4)" mr $t "$L" ;;
    *) echo "unknown cell $CELL" >&2; exit 1 ;;
  esac
  streak $t
done
