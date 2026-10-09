#!/usr/bin/env bash
# gpu-detect: the regression and latency cells of EXPERIMENT.md 7 (one bounded batch; run inside a hold of hold.sh, itself
# inside ../gpu-initiated/common/cluster_run.sh through chain.sh). The runners are gin-remaining's, called unchanged from
# their folder (../gpu-initiated/gin_recovery/remaining/run_trial_hr.sh, run_mr_hr.sh; they pick a checked rendezvous
# port in 29000-30999 with portpick.sh and kill only PIDs they recorded). Library: the bundle of <build> under
# $HOME/gi-bundle/gin_ts2/ (this study: hk from pilot 2 on; hw for the responder-side gap's control). Drivers:
# gin-remaining's deployed gin_ts2 (bundle hr, DRVKEY=hr) and gin_mr (mr/hr, MRKEY=hr), built with the hr headers, which
# equal hw's and hk's (neither layer changes a header; build_info.txt).
# Cell definitions repeated from ../gpu-initiated/gin_recovery/remaining/cells.sh (two-rank regression, four-rank
# regression, the cycle) and new ones (latency per watch period, two lower REQs in one ACK wait, a late pair fault after
# a death; hk: the responder-side gap, hold asked for, a policy mismatch) below.
# usage: cells_reg.sh <logdir> <cell> <build> <n> [start]
set -u
L=${1:?logdir}; CELL=${2:?cell}; B=${3:?build}; NRUN=${4:?n}; START=${5:-1}
D=$(cd "$(dirname "$0")" && pwd)
RM=$D/../gpu-initiated/gin_recovery/remaining
RES=${RES:-$(dirname "$(dirname "$L")")}   # the results directory (hold.sh passes <resultsdir>/reg/<subdir> and RES)
run() { CELL=$CELL BUILD=$B DRVKEY=hr bash "$RM/run_trial_hr.sh" "$@"; }
mr() { CELL=$CELL LIB=$B MRKEY=hr ABORT_WD_S=20 bash "$RM/run_mr_hr.sh" "$@"; }
BIDIR="GIN_TS_BIDIR_FUSED=1"
F_MS=${F_MS:-6000}; KILL_MS=${KILL_MS:-9000}; STALL=${STALL:-300}
LATE_MS=${LATE_MS:-13000}   # the late pair fault: rank 0's QP to rank 1, after the kill (9 s) and the degraded raise (+2 s)
# the responder-side gap (EXPERIMENT.md 9.1 (g)): rank 3's fault GAP_F_MS after its context; its stall after its own Commit
# (GAP_STALL ms) and the runner's kill GAP_KILL_MS after its launch (pilot 1: 9000 ms after launch = 8.0 s after devComm),
# so the kill lands inside the stall (about 4.1-12 s after devComm)
GAP_F_MS=${GAP_F_MS:-4000}; GAP_STALL=${GAP_STALL:-8000}; GAP_KILL_MS=${GAP_KILL_MS:-9000}
ctx() { local a=$1 b=$2 n=$3; echo $(( a * (n - 1) + (b < a ? b : b - 1) )); }
hook() { echo "NCCL_GIN_FAULT_INJECT=local_err:$F_MS NCCL_GIN_FAULT_INJECT_CTX=$(ctx "$1" "$2" "$3")"; }
ST="NCCL_GIN_TS_TEST_STALL=${STALL}@quiesce"
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
  inj=$(( 500 + (k * 137) % 700 ))   # as ../gpu-initiated/scripts/ts2/batch.sh: ms after the GDAKI context's creation
  t=n$k
  case "$CELL" in
    # ================= two ranks (run_trial_hr.sh), ../harden/cells.sh definitions as gin-remaining =================
    f1_b)    TS=1 INJECT=$inj run F1 blocking $t "$L" 120 ;;
    f3_b)    TS=1 INJECT=$inj run F3 blocking $t "$L" 120 ;;
    bidirf_sym_b) i0=$(( 60 + (k * 7) % 50 )); TS=1 APP=bidir GAP_US=0 INJECT=$i0 INJECT1=$(( i0 - 1 - k % 2 )) \
             EXTRA_ENV="$BIDIR" run F1both blocking $t "$L" 8000 4096 ;;
    f4_b)    TS=1 GAP_US=30000 KILL_DELAY_MS=$(( 3500 + (k * 211) % 900 )) WATCHDOG_S=40 run F4 blocking $t "$L" 200 ;;
    f2rel_b) TS=1 ABORT_WD_S=40 EXTRA_ENV="GIN_TS_RX_WAIT_S=20 GIN_TS_POST_ABORT_WAIT_S=3 NCCL_GIN_TS_USER_ABORT=1" \
             run F2 blocking $t "$L" 120 ;;
    hd_rxdeath_b) TS=1 KILL_R0=1 KILL_DELAY_MS=3000 ABORT_WD_S=20 WATCHDOG_S=60 EXTRA_ENV="GIN_TS_RX_WAIT_S=15" \
             run none blocking $t "$L" 1000 16384 ;;
    # ---- fault-free latency, 3000 round trips, per QP-watch period (gpu-detect: the watch's cost) ----
    lat_4k_w*)   TS=1 EXTRA_ENV="NCCL_GIN_TS_QPWATCH_MS=${CELL#lat_4k_w}" run lat blocking $t "$L" 3000 4096 ;;
    lat_256k_w*) TS=1 EXTRA_ENV="NCCL_GIN_TS_QPWATCH_MS=${CELL#lat_256k_w}" run lat blocking $t "$L" 3000 262144 ;;
    # ================= four ranks (run_mr_hr.sh), gin-remaining's definitions =================
    mr4_none)        N=4 EXTRA_ENV="$BASE" mr $t "$L" ;;
    mr4_f1_01)       N=4 EXTRA_ENV="$BASE" R0_ENV="$(hook 0 1 4)" mr $t "$L" ;;
    rm4_kill3_untimed) N=4 KILL_RANK=3 KILL_DELAY_MS=$KILL_MS FLUSH=peer \
                     EXTRA_ENV="GIN_MR_RX_UNTIMED=1 GIN_MR_GRACE_S=15" mr $t "$L" ;;
    mr4_cyc_stall)   N=4 EXTRA_ENV="$BASE GIN_MR_GRACE_S=40" R0_ENV="$(hook 0 1 4) $ST" R1_ENV="$(hook 1 2 4) $ST" \
                     R2_ENV="$(hook 2 0 4) $ST" mr $t "$L" ;;
    # ---- gpu-detect (review M-A): two lower REQs wait while rank 3 waits for an ACK. Faults on rank 0 (QP to 3), rank 1
    # (QP to 3), rank 2 (QP to 1) and rank 3 (QP to 2), each initiator's helper stalled 300 ms after its quiesce so the
    # rounds overlap: rank 3 waits for rank 2, which waits for rank 1 (it keeps rank 3's REQ, a higher rank), which waits
    # for rank 3 (it keeps rank 2's REQ); ranks 0 and 1 both send their REQ to rank 3, the lower ranks it answers inside
    # its wait, one nested round per pass (the cycle 3>2>1>3 ends when rank 3 answers rank 1) ----
    mr4_twolow_stall) N=4 EXTRA_ENV="$BASE GIN_MR_GRACE_S=40" R0_ENV="$(hook 0 3 4) $ST" R1_ENV="$(hook 1 3 4) $ST" \
                     R2_ENV="$(hook 2 1 4) $ST" R3_ENV="$(hook 3 2 4) $ST" mr $t "$L" ;;
    # ---- gpu-detect (review M-C): rank 3 killed (gin-peer's timed form), then rank 0's QP to rank 1 faulted LATE_MS after
    # the context, after the degraded raise. Default rule (NCCL_GIN_TS_DEGRADED_ROUNDS=0): the pair 0-1 declines at its
    # publish check; =1 (gin-remaining's rule): it recovers ----
    rm4_late01)      N=4 KILL_RANK=3 KILL_DELAY_MS=$KILL_MS FLUSH=peer EXTRA_ENV="$BASE GIN_MR_GRACE_S=40" \
                     R0_ENV="NCCL_GIN_FAULT_INJECT=local_err:$LATE_MS NCCL_GIN_FAULT_INJECT_CTX=$(ctx 0 1 4)" mr $t "$L" ;;
    rm4_late01_rounds) N=4 KILL_RANK=3 KILL_DELAY_MS=$KILL_MS FLUSH=peer \
                     EXTRA_ENV="$BASE GIN_MR_GRACE_S=40 NCCL_GIN_TS_DEGRADED_ROUNDS=1" \
                     R0_ENV="NCCL_GIN_FAULT_INJECT=local_err:$LATE_MS NCCL_GIN_FAULT_INJECT_CTX=$(ctx 0 1 4)" mr $t "$L" ;;
    # ---- gpu-detect (hk, the responder-side gap, EXPERIMENT.md 9.1 (g)): rank 3 starts a round with rank 0 (local QP error
    # on rank 3's context ctx(3,0)) and dies inside rank 0's window: after rank 0's Commit, before DONE. rm4_gap: rank 3
    # stalls after its own Commit (NCCL_GIN_TS_TEST_STALL=<ms>@commit, a switch hw has too) and the runner kills it during
    # the stall: the same condition on hw (the control) and hk. rm4_gapx (hk only): rank 3 ends itself right after the ACK
    # (NCCL_GIN_TS_TEST_EXIT_AFTER_ACK=1, _exit 73). Untimed receives, the application's grace 15 s, as rm4_kill3_untimed.
    rm4_gap)  N=4 KILL_RANK=3 KILL_DELAY_MS=$GAP_KILL_MS FLUSH=peer EXTRA_ENV="GIN_MR_RX_UNTIMED=1 GIN_MR_GRACE_S=15" \
              R3_ENV="NCCL_GIN_FAULT_INJECT=local_err:$GAP_F_MS NCCL_GIN_FAULT_INJECT_CTX=$(ctx 3 0 4) NCCL_GIN_TS_TEST_STALL=${GAP_STALL}@commit" \
              mr $t "$L" ;;
    rm4_gapx) N=4 FLUSH=peer EXTRA_ENV="GIN_MR_RX_UNTIMED=1 GIN_MR_GRACE_S=15" \
              R3_ENV="NCCL_GIN_FAULT_INJECT=local_err:$GAP_F_MS NCCL_GIN_FAULT_INJECT_CTX=$(ctx 3 0 4) NCCL_GIN_TS_TEST_EXIT_AFTER_ACK=1" \
              mr $t "$L" ;;
    # ---- gpu-detect (hk, the policy field G1): hold asked for on every rank (no restore layer: one WARN each, fail-fast; the
    # kill cell of RG9 otherwise unchanged), and a mismatch (rank 0 hold, rank 1 fail-fast: a WARN on both; f4_b otherwise)
    rm4_kill3_hold) N=4 KILL_RANK=3 KILL_DELAY_MS=$KILL_MS FLUSH=peer \
                     EXTRA_ENV="GIN_MR_RX_UNTIMED=1 GIN_MR_GRACE_S=15 NCCL_GIN_FAULT_POLICY=hold" mr $t "$L" ;;
    f4_mix_b) TS=1 GAP_US=30000 KILL_DELAY_MS=$(( 3500 + (k * 211) % 900 )) WATCHDOG_S=40 R0_ENV="NCCL_GIN_FAULT_POLICY=hold" \
             run F4 blocking $t "$L" 200 ;;
    *) echo "unknown cell $CELL" >&2; exit 1 ;;
  esac
  streak $t
done
