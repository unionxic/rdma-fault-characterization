#!/usr/bin/env bash
# One bounded batch of S1 trials (run inside ../../../common/cluster_run.sh; each call < 15 min).
# usage: batch.sh <logdir> <cell> <n> [start]
# cells (all with the same unmodified application gin_ts1):
#   none_b      fault-free, TS=1, blocking flush, 256 KiB x 120
#   f1_b|f1_t   local QP ERR (rank 0 hook) mid-loop, TS=1, blocking|timeout flush
#   f3_b|f3_t   peer QP ERR (rank 1 hook) -> RETRY_EXC mid-loop, TS=1
#   f1x5_b      five local faults in one run, the third inside the previous recovery's commit
#   f2_b        the application's own bad offset (REM_ACCESS) at iteration 10 -> must be declined
#   f4_b        SIGKILL of rank 1 mid-loop -> RETRY_EXC with the peer dead -> must be declined
#   neg_norebase_t  negative control (timeout flush): device waiters keep their stale ticket (F1)
#   neg_noring_t    negative control (timeout flush): the host does not ring the doorbell for the re-posted WQEs (F1)
#   off_f1_b    TS=0 (flag off, gpudb v2 behaviour), F1        base_f1_b  gpudb build (base/), F1
#   lat_<on|off|base>_<4k|256k>   fault-free latency, 3000 iterations, one reused slot
set -u
L=${1:?logdir}; CELL=${2:?cell}; N=${3:?n}; START=${4:-1}
cd "$(dirname "$0")"
run() { CELL=$CELL bash run_trial.sh "$@"; }
for ((k = START; k < START + N; k++)); do
  inj=$(( 500 + (k * 137) % 700 ))   # spread the fault instant over the loop (ms after devComm creation)
  case "$CELL" in
    none_b)   TS=1 run none blocking n$k "$L" 120 ;;
    f1_b)     TS=1 INJECT=$inj run F1 blocking n$k "$L" 120 ;;
    f1_t)     TS=1 INJECT=$inj run F1 timeout n$k "$L" 120 ;;
    f3_b)     TS=1 INJECT=$inj run F3 blocking n$k "$L" 120 ;;
    f3_t)     TS=1 INJECT=$inj run F3 timeout n$k "$L" 120 ;;
    f1x5_b)   TS=1 INJECT="$inj,150,-1,200,100" run F1 blocking n$k "$L" 160 ;;
    # back-to-back 4 KiB ops (no gap): the local ERR lands inside an in-flight op, so the responder may
    # already have executed the WRITE (n=1) or the WRITE and the ADD (n=0) when the requester errs
    f1g0_b)   TS=1 GAP_US=0 INJECT=$(( 60 + (k * 7) % 50 )) run F1 blocking n$k "$L" 8000 4096 ;;
    f2_b)     TS=1 ABORT_WD_S=5 run F2 blocking n$k "$L" 120 ;;
    f4_b)     TS=1 GAP_US=30000 KILL_DELAY_MS=$(( 3500 + (k * 211) % 900 )) WATCHDOG_S=40 run F4 blocking n$k "$L" 200 ;;
    neg_norebase_t) TS=1 DIAG=norebase INJECT=$inj WATCHDOG_S=40 EXTRA_ENV="GIN_TS_RX_WAIT_S=10" run F1 timeout n$k "$L" 120 ;;
    neg_noring_t)   TS=1 DIAG=noring INJECT=$inj WATCHDOG_S=40 EXTRA_ENV="GIN_TS_RX_WAIT_S=10" run F1 timeout n$k "$L" 120 ;;
    off_f1_b) TS=0 INJECT=$inj run F1 blocking n$k "$L" 120 ;;
    base_f1_b) BASE=1 INJECT=$inj run F1 blocking n$k "$L" 120 ;;
    # --- follow-up (external review) ---
    # exactly-once boundary: the k-th put+signal is split; the fault fires after its WRITE completed and
    # before its ADD is posted (test hook inside NCCL, rank 0 only): the round must re-post only the ADD
    split_b)  TS=1 R0_ENV="NCCL_GIN_TS_TEST_SPLIT=$(( 20 + (k * 13) % 80 ))" run none blocking n$k "$L" 120 ;;
    # bounded behaviour when the helper stalls / dies mid-round (rank 0 test knobs)
    # (GIN_TS_ASYNC_GRACE_S: how long the application lets the kernel finish after the async error;
    #  GIN_TS_POST_ABORT_WAIT_S: observe a kernel still running at ncclCommAbort; both driver-side only)
    stallq_b) TS=1 ABORT_WD_S=15 R0_ENV="NCCL_GIN_TS_TEST_STALL=8000@quiesce" \
              EXTRA_ENV="NCCL_GIN_TS_ROUND_MS=2000 NCCL_GIN_TS_HOLD_MS=4000 GIN_TS_RX_WAIT_S=12 GIN_TS_ASYNC_GRACE_S=10 GIN_TS_POST_ABORT_WAIT_S=3" \
              INJECT=$inj run F1 blocking n$k "$L" 120 ;;
    stallc_b) TS=1 ABORT_WD_S=15 R0_ENV="NCCL_GIN_TS_TEST_STALL=8000@commit" \
              EXTRA_ENV="NCCL_GIN_TS_ROUND_MS=2000 NCCL_GIN_TS_HOLD_MS=4000 GIN_TS_RX_WAIT_S=12 GIN_TS_ASYNC_GRACE_S=10 GIN_TS_POST_ABORT_WAIT_S=3" \
              INJECT=$inj run F1 blocking n$k "$L" 120 ;;
    die_b)    TS=1 ABORT_WD_S=15 R0_ENV="NCCL_GIN_TS_TEST_DIE=quiesce GIN_TS_CONTINUE=1" \
              EXTRA_ENV="NCCL_GIN_TS_ROUND_MS=2000 NCCL_GIN_TS_HOLD_MS=4000 GIN_TS_RX_WAIT_S=12 GIN_TS_ASYNC_GRACE_S=10 GIN_TS_POST_ABORT_WAIT_S=3" \
              INJECT=$inj run F1 blocking n$k "$L" 120 ;;
    # a slow but successful round (helper stalled 3 s < NCCL_GIN_TS_ROUND_MS 25 s): must stay transparent,
    # no watchdog (the review found a false "helper not running" at the end of rounds longer than 1 s)
    #   (odd trials stall after quiesce, even trials after both commits, i.e. inside the responder's DONE wait)
    slow_b)   st=quiesce; [ $((k % 2)) = 0 ] && st=commit
              TS=1 R0_ENV="NCCL_GIN_TS_TEST_STALL=3000@$st" EXTRA_ENV="GIN_TS_POST_ABORT_WAIT_S=3" INJECT=$inj \
              run F1 blocking n$k "$L" 120 ;;
    # the application's own flush timeout (0.5 s) is shorter than the (stalled, 3 s) recovery
    tmo_t)    TS=1 ABORT_WD_S=15 DEV_TIMEOUT_S=0.5 R0_ENV="NCCL_GIN_TS_TEST_STALL=3000@quiesce" \
              EXTRA_ENV="NCCL_GIN_TS_ROUND_MS=2000 GIN_TS_RX_WAIT_S=12 GIN_TS_ASYNC_GRACE_S=10 GIN_TS_POST_ABORT_WAIT_S=3" \
              INJECT=$inj run F1 timeout n$k "$L" 120 ;;
    # production form of the helper-vs-teardown race: the application calls ncclCommAbort (without
    # ncclDevCommDestroy) while rank 0's helper is inside a round (stalled 8 s after quiesce) and the
    # kernel is parked (hold 30 s): the teardown must join the helper, poison the gates, and the kernel exit
    abortmid_b) TS=1 ABORT_WD_S=15 R0_ENV="NCCL_GIN_TS_TEST_STALL=8000@quiesce GIN_TS_ASYNC_GRACE_S=0.3" \
              EXTRA_ENV="NCCL_GIN_TS_ROUND_MS=2000 NCCL_GIN_TS_HOLD_MS=30000 GIN_TS_RX_WAIT_S=12 GIN_TS_POST_ABORT_WAIT_S=5" \
              INJECT=$inj run F1 blocking n$k "$L" 120 ;;
    # cumulative cost attribution (unsafe device variants compiled into the driver only)
    lat_c1gpufence_4k|lat_c2nogate_4k|lat_c3nopoll_4k) v=${CELL#lat_}; TS=1 VAR=${v%_4k} run lat blocking n$k "$L" 3000 4096 ;;
    lat_c1gpufence_256k|lat_c2nogate_256k|lat_c3nopoll_256k) v=${CELL#lat_}; TS=1 VAR=${v%_256k} run lat blocking n$k "$L" 3000 262144 ;;
    lat_on_4k)    TS=1 run lat blocking n$k "$L" 3000 4096 ;;
    lat_off_4k)   TS=0 run lat blocking n$k "$L" 3000 4096 ;;
    lat_base_4k)  BASE=1 run lat blocking n$k "$L" 3000 4096 ;;
    lat_on_256k)  TS=1 run lat blocking n$k "$L" 3000 262144 ;;
    lat_off_256k) TS=0 run lat blocking n$k "$L" 3000 262144 ;;
    lat_base_256k) BASE=1 run lat blocking n$k "$L" 3000 262144 ;;
    # cost attribution (unsafe device variants compiled into the driver only; not part of the patch)
    lat_nogate_4k|lat_nopoll_4k|lat_gpufence_4k) v=${CELL#lat_}; TS=1 VAR=${v%_4k} run lat blocking n$k "$L" 3000 4096 ;;
    lat_nogate_256k|lat_nopoll_256k|lat_gpufence_256k) v=${CELL#lat_}; TS=1 VAR=${v%_256k} run lat blocking n$k "$L" 3000 262144 ;;
    *) echo "unknown cell $CELL" >&2; exit 1 ;;
  esac
done
