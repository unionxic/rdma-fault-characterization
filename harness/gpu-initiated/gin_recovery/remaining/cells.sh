#!/usr/bin/env bash
# gin-remaining: every cell of EXPERIMENT.md section 7 (one bounded batch; run inside a hold of hold.sh, itself inside
# ../../common/cluster_run.sh through chain.sh). Two-rank cells run this folder's run_trial_hr.sh, N-rank cells this
# folder's run_mr_hr.sh, the host-memory benchmark run_bench_hr.sh, the NIC gate test run_ngt_hr.sh. The runners kill only
# PIDs they recorded and pick a checked rendezvous port below the ephemeral range (portpick.sh).
# usage: cells.sh <logdir> <cell> <build> <n> [start]
# Builds (<build> = the libnccl bundle): hr (this study, research), hrp (production, same source), hq and hqp (gin-peer's
# bundles, deployed, read only: the controls and the latency baseline). Drivers: two ranks use this study's gin_ts2 (bundle
# hr) for hr and for the hq controls (DRV=hr: GIN_TS_HOG_CALLS is new in it), and each production bundle's own gin_ts2 for
# hrp and hqp (the latency comparison includes the drivers' device code, as in gin-peer); N ranks always use this study's
# gin_mr (mr/hr) with the libnccl of <build>.
# Definitions repeated from earlier studies: ../harden/cells.sh (two-rank regression), ../handoff/cells.sh (the GPU-full
# order), ../multirank/cells.sh (cycle, chain, four-rank regression), ../peer/cells.sh (rank 3 kill, per-peer flush).
set -u
L=${1:?logdir}; CELL=${2:?cell}; B=${3:?build}; NRUN=${4:?n}; START=${5:-1}
D=$(cd "$(dirname "$0")" && pwd)
RES=$(dirname "$L")   # the results directory (hold.sh passes <resultsdir>/<subdir>)
case "$B" in hr|hq) DRV=hr ;; *) DRV=$B ;; esac
run() { CELL=$CELL BUILD=$B DRVKEY=$DRV bash "$D/run_trial_hr.sh" "$@"; }
mr() { CELL=$CELL LIB=$B MRKEY=hr ABORT_WD_S=20 bash "$D/run_mr_hr.sh" "$@"; }
bench() { CELL=$CELL BENCHKEY=hr bash "$D/run_bench_hr.sh" "$@"; }
ngt() { CELL=$CELL NGTKEY=ngt bash "$D/run_ngt_hr.sh" "$@"; }
BIDIR="GIN_TS_BIDIR_FUSED=1"
# N-rank timing (../multirank/cells.sh, kept): hook F_MS after the GDAKI context is created, kill KILL_MS after the runner
# starts the killed rank, the helper stall of the cycle and chain cells after its quiesce
F_MS=${F_MS:-6000}; KILL_MS=${KILL_MS:-9000}; STALL=${STALL:-300}
ctx() { local a=$1 b=$2 n=$3; echo $(( a * (n - 1) + (b < a ? b : b - 1) )); }
hook() { echo "NCCL_GIN_FAULT_INJECT=local_err:$F_MS NCCL_GIN_FAULT_INJECT_CTX=$(ctx "$1" "$2" "$3")"; }
ST="NCCL_GIN_TS_TEST_STALL=${STALL}@quiesce"
BASE="GIN_TS_RX_WAIT_S=10"
HOG="GIN_TS_HOG_MS=3000 GIN_TS_HOG_PROBE=1"   # ../handoff/cells.sh hf_hog_f1_b, without rank 0's shrink
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
    # ================= two ranks (run_trial_hr.sh) =================
    # ---- problem 3: the GPU-full order of gin-handoff (calls after the GIN launch), the copies over the NIC ----
    rh_hog_f1_b) TS=1 INJECT=$inj EXTRA_ENV="$HOG" run F1 blocking $t "$L" 120 ;;
    # the same with this build's stream copies (NCCL_GIN_TS_COPY_PATH=stream): the control inside the hr build
    rh_hog_copystream_f1_b) TS=1 INJECT=$inj EXTRA_ENV="$HOG NCCL_GIN_TS_COPY_PATH=stream" run F1 blocking $t "$L" 120 ;;
    # one of gin-harden's three calls after the GIN launch, the other two before it (gin_ts2.cu GIN_TS_HOG_CALLS)
    rh_hogcall_load_f1_b)   TS=1 INJECT=$inj EXTRA_ENV="$HOG GIN_TS_HOG_CALLS=load" run F1 blocking $t "$L" 120 ;;
    rh_hogcall_malloc_f1_b) TS=1 INJECT=$inj EXTRA_ENV="$HOG GIN_TS_HOG_CALLS=malloc" run F1 blocking $t "$L" 120 ;;
    rh_hogcall_stream_f1_b) TS=1 INJECT=$inj EXTRA_ENV="$HOG GIN_TS_HOG_CALLS=stream" run F1 blocking $t "$L" 120 ;;
    # ---- regression (../harden/cells.sh definitions, as ../peer/cells.sh) ----
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
    # ================= four ranks (run_mr_hr.sh) =================
    # ---- problem 1: three initiators in a cycle 0->1, 1->2, 2->0 (each helper stalled after its quiesce so the rounds
    # overlap), and the chain 0->1, 1->2 ----
    mr4_cyc_stall)   N=4 EXTRA_ENV="$BASE GIN_MR_GRACE_S=40" R0_ENV="$(hook 0 1 4) $ST" R1_ENV="$(hook 1 2 4) $ST" \
                     R2_ENV="$(hook 2 0 4) $ST" mr $t "$L" ;;
    mr4_chain_stall) N=4 EXTRA_ENV="$BASE GIN_MR_GRACE_S=40" R0_ENV="$(hook 0 1 4) $ST" R1_ENV="$(hook 1 2 4) $ST" \
                     mr $t "$L" ;;
    # ---- problem 2: rank 3 SIGKILLed, per-peer flush, every receive wait untimed (GIN_MR_RX_UNTIMED=1); the application
    # gives up 15 s after the async error (GIN_MR_GRACE_S), so a wait that is never released ends the trial there ----
    rm4_kill3_untimed) N=4 KILL_RANK=3 KILL_DELAY_MS=$KILL_MS FLUSH=peer \
                     EXTRA_ENV="GIN_MR_RX_UNTIMED=1 GIN_MR_GRACE_S=15" mr $t "$L" ;;
    # gin-peer's definition (timed receive waits, 10 s): the degraded rule changes its survivors' receives
    mr4_kill3_peer)  N=4 KILL_RANK=3 KILL_DELAY_MS=$KILL_MS FLUSH=peer EXTRA_ENV="$BASE GIN_MR_GRACE_S=40" mr $t "$L" ;;
    # ---- regression (../multirank/cells.sh definitions) ----
    mr4_none)        N=4 EXTRA_ENV="$BASE" mr $t "$L" ;;
    mr4_f1_01)       N=4 EXTRA_ENV="$BASE" R0_ENV="$(hook 0 1 4)" mr $t "$L" ;;
    # ================= the host-memory benchmark (run_bench_hr.sh; both nodes, one GPU each) =================
    hm_bench) bench $t "$L" ;;
    # ================= the NIC gate test (run_ngt_hr.sh; both nodes, one GPU and the node's HCA each) =================
    nic_gate) ngt $t "$L" ;;
    *) echo "unknown cell $CELL" >&2; exit 1 ;;
  esac
  streak $t
done
