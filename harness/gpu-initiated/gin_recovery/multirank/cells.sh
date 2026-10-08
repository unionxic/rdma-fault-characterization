#!/usr/bin/env bash
# gin-multirank: the cells of EXPERIMENT.md section 7 (one bounded batch; run inside a hold of hold.sh, itself inside
# ../../common/cluster_run.sh through chain.sh). Every trial is run_mr.sh: N processes of the unmodified gin_mr, rank r on
# rain (r even) or sunny (r odd), libnccl of the recovery build <lib>, driver mr/<MRKEY>/gin_mr (MRKEY defaults to <lib>).
# usage: cells.sh <logdir> <cell> <lib> <n> [start]
# Timing values that the pilot may change once before the pre-registration tag (EXPERIMENT.md 3.4):
#   F_MS (6000)      fault hook delay after the GDAKI context is created (NCCL_GIN_FAULT_INJECT=local_err:<F_MS>)
#   KILL_MS (9000)   SIGKILL delay after the runner started the killed rank
#   STALL (300)      NCCL_GIN_TS_TEST_STALL=<STALL>@quiesce in the cycle and chain cells
# Fault hooks name one GIN context: edge a->b uses context ctx(a,b) = a*(N-1) + (b < a ? b : b-1) (gin_mr.cu).
set -u
L=${1:?logdir}; CELL=${2:?cell}; LIBK=${3:?lib}; NRUN=${4:?n}; START=${5:-1}
D=$(cd "$(dirname "$0")" && pwd)
F_MS=${F_MS:-6000}; KILL_MS=${KILL_MS:-9000}; STALL=${STALL:-300}
ctx() { local a=$1 b=$2 n=$3; echo $(( a * (n - 1) + (b < a ? b : b - 1) )); }
hook() { echo "NCCL_GIN_FAULT_INJECT=local_err:$F_MS NCCL_GIN_FAULT_INJECT_CTX=$(ctx "$1" "$2" "$3")"; }
peerhook() { echo "NCCL_GIN_FAULT_INJECT=peer_err:$F_MS NCCL_GIN_FAULT_INJECT_CTX=$(ctx "$1" "$2" "$3")"; }
ST="NCCL_GIN_TS_TEST_STALL=${STALL}@quiesce"
BASE="GIN_TS_RX_WAIT_S=10"
run() { CELL=$CELL LIB=$LIBK MRKEY=${MRKEY:-$LIBK} ABORT_WD_S=20 bash "$D/run_mr.sh" "$@"; }
RES=$(dirname "$L")   # the results directory (hold.sh passes <resultsdir>/<hold folder>)
streak() {  # after trial $1: two trials in a row that left a gin_mr process behind write $RES/STOP_left (EXPERIMENT.md 8)
  local left; left=$(sed -n 's/.* left=\([0-9]*\) .*/\1/p' "$L/${CELL}_$1_meta.txt" 2>/dev/null)
  if [ -n "$left" ] && [ "$left" -gt 0 ]; then
    echo $(( $(cat "$RES/LEFT_STREAK" 2>/dev/null || echo 0) + 1 )) > "$RES/LEFT_STREAK"
  else
    echo 0 > "$RES/LEFT_STREAK"
  fi
  if [ "$(cat "$RES/LEFT_STREAK")" -ge 2 ]; then
    echo "$(date '+%F %T') ${CELL}_$1: gin_mr left behind in two trials in a row" | tee -a "$RES/STOP_left"
  fi
}
for ((k = START; k < START + NRUN; k++)); do
  [ -e "$RES/STOP_left" ] || [ -e "$RES/STOP_mlx5" ] && { echo "skipped ${CELL}_n$k: STOP file" >&2; break; }
  t=n$k
  case "$CELL" in
    # fault-free
    mr4_none)        N=4 EXTRA_ENV="$BASE" run $t "$L" ;;
    mr4_none_peer)   N=4 FLUSH=peer EXTRA_ENV="$BASE" run $t "$L" ;;
    mr3_none)        N=3 EXTRA_ENV="$BASE" run $t "$L" ;;
    mr2_none)        N=2 EXTRA_ENV="$BASE" run $t "$L" ;;
    # pilot only: the multi-rank-per-GPU switch off (NCCL must refuse two ranks on one GPU)
    mr4_nomrge)      N=4 MRGE=0 WATCHDOG_S=40 EXTRA_ENV="$BASE" run $t "$L" ;;
    # one pair: local QP error on an edge between nodes / within rain (NIC loopback), remote QP error
    mr4_f1_01)       N=4 EXTRA_ENV="$BASE" R0_ENV="$(hook 0 1 4)" run $t "$L" ;;
    mr4_f1_02)       N=4 EXTRA_ENV="$BASE" R0_ENV="$(hook 0 2 4)" run $t "$L" ;;
    mr4_f3_01)       N=4 EXTRA_ENV="$BASE" R1_ENV="$(peerhook 0 1 4)" run $t "$L" ;;
    # two pairs at once: disjoint; two initiators toward one responder; every edge of rank 0 (three serial rounds)
    mr4_f1_01_23)    N=4 EXTRA_ENV="$BASE" R0_ENV="$(hook 0 1 4)" R2_ENV="$(hook 2 3 4)" run $t "$L" ;;
    mr4_f1_10_30)    N=4 EXTRA_ENV="$BASE" R1_ENV="$(hook 1 0 4)" R3_ENV="$(hook 3 0 4)" run $t "$L" ;;
    mr4_f1all0)      N=4 EXTRA_ENV="$BASE" R0_ENV="NCCL_GIN_FAULT_INJECT=local_err:$F_MS" run $t "$L" ;;
    # SIGKILL of rank 3 (sunny, sharing the GPU with rank 1): context-wide flush, per-peer flush
    mr4_kill3)       N=4 KILL_RANK=3 KILL_DELAY_MS=$KILL_MS EXTRA_ENV="$BASE GIN_MR_GRACE_S=40" run $t "$L" ;;
    mr4_kill3_peer)  N=4 KILL_RANK=3 KILL_DELAY_MS=$KILL_MS FLUSH=peer EXTRA_ENV="$BASE GIN_MR_GRACE_S=40" run $t "$L" ;;
    # three initiators in a cycle 0->1, 1->2, 2->0, each helper stalled after its quiesce so the rounds overlap; and the
    # chain 0->1, 1->2 (no edge back to rank 0) as its control
    mr4_cyc_stall)   N=4 EXTRA_ENV="$BASE GIN_MR_GRACE_S=40" R0_ENV="$(hook 0 1 4) $ST" R1_ENV="$(hook 1 2 4) $ST" \
                     R2_ENV="$(hook 2 0 4) $ST" run $t "$L" ;;
    mr4_chain_stall) N=4 EXTRA_ENV="$BASE GIN_MR_GRACE_S=40" R0_ENV="$(hook 0 1 4) $ST" R1_ENV="$(hook 1 2 4) $ST" \
                     run $t "$L" ;;
    # three ranks (two on rain, one on sunny)
    mr3_f1_01)       N=3 EXTRA_ENV="$BASE" R0_ENV="$(hook 0 1 3)" run $t "$L" ;;
    # fault-free latency, 4 KiB put + signal + flush back to back, 3000 iterations, one reused slot per edge
    mr2_lat)         N=2 MODE=lat ITERS=3000 BYTES=4096 EXTRA_ENV="$BASE" run $t "$L" ;;
    mr4_lat_solo)    N=4 MODE=lat ITERS=3000 BYTES=4096 EDGES="0-1,1-0" EXTRA_ENV="$BASE" run $t "$L" ;;
    mr4_lat)         N=4 MODE=lat ITERS=3000 BYTES=4096 EXTRA_ENV="$BASE" run $t "$L" ;;
    *) echo "unknown cell $CELL" >&2; exit 1 ;;
  esac
  streak $t
done
