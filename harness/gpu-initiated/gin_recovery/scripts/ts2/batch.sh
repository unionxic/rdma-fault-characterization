#!/usr/bin/env bash
# One bounded batch of S2 trials (run inside ../../../common/cluster_run.sh; each call < 15 min).
# usage: batch.sh <logdir> <cell> <n> [start]
# The application is always gin_ts2 (unmodified: no recovery code); BUILD picks the library bundle.
# S1 regression cells on the S2 build (as scripts/ts1/batch.sh):
#   none_b f1_b f1_t f3_b f3_t f1x5_b f1g0_b f2_b f4_b split_b neg_norebase_t neg_noring_t off_f1_b base_f1_b
# latency (fault-free put+signal+flush, 3000 iterations, one reused slot):
#   lat_<base|s1off|s1on|s2off|s2on|s2sys>_<4k|256k>
# B, many operations in flight (APP=burst):
#   burst_{none,f1,f3,f1rp}_b   one thread, K=16 aggregated 4 KiB puts + 1 signal + flush per iteration
#                               (f1rp: a second local fault fires inside the first recovery's commit, so it
#                               hits the re-posted WQEs)
#   mtb_{none,f1,f3}_b          4 CTAs x 1 thread + 1 CTA x 4 threads... (see below): several CTAs and threads
#                               posting bursts to one QP, P x (K+1) <= the 128-slot ring
#   mt<P>_{none,f1}_b           P threads (16..1024) posting put + signal (not aggregated) + flush to one QP
# C, symmetric initiation (APP=bidir, both directions at once):
#   bidir_none_b, bidir_f1_b (rank 0 only), bidir_f1both_b (both ranks at once), bidir_f1both_notie_b (tie-break
#   off: S1 behaviour, both decline)
# D, address flap (secondary GIDs; the hold must run gid_blackhole.sh setup before and teardown after):
#   flap_<s1|s2>_<05|6|15>      sunny's secondary address removed for 0.5/6/15 s, 2 s after launch
#   flap_s2_<20|30>             (review) cuts near and beyond the path-wait bound
# review cells: ring_{none,f4,f2}_b (a full ring of aggregated puts), burst_hring_b (the host rings unrung WQEs)
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
    f1g0_b)   TS=1 GAP_US=0 INJECT=$(( 60 + (k * 7) % 50 )) run F1 blocking n$k "$L" 8000 4096 ;;
    f2_b)     TS=1 ABORT_WD_S=5 run F2 blocking n$k "$L" 120 ;;
    f4_b)     TS=1 GAP_US=30000 KILL_DELAY_MS=$(( 3500 + (k * 211) % 900 )) WATCHDOG_S=40 run F4 blocking n$k "$L" 200 ;;
    split_b)  TS=1 R0_ENV="NCCL_GIN_TS_TEST_SPLIT=$(( 20 + (k * 13) % 80 ))" run none blocking n$k "$L" 120 ;;
    neg_norebase_t) TS=1 DIAG=norebase INJECT=$inj WATCHDOG_S=40 EXTRA_ENV="GIN_TS_RX_WAIT_S=10" run F1 timeout n$k "$L" 120 ;;
    neg_noring_t)   TS=1 DIAG=noring INJECT=$inj WATCHDOG_S=40 EXTRA_ENV="GIN_TS_RX_WAIT_S=10" run F1 timeout n$k "$L" 120 ;;
    off_f1_b) TS=0 INJECT=$inj run F1 blocking n$k "$L" 120 ;;
    base_f1_b) BUILD=base INJECT=$inj run F1 blocking n$k "$L" 120 ;;
    # --- latency: the same application source compiled against each build ---
    lat_base_4k)  BUILD=base run lat blocking n$k "$L" 3000 4096 ;;
    lat_s1off_4k) BUILD=s1 TS=0 run lat blocking n$k "$L" 3000 4096 ;;
    lat_s1on_4k)  BUILD=s1 TS=1 run lat blocking n$k "$L" 3000 4096 ;;
    lat_s2off_4k) TS=0 run lat blocking n$k "$L" 3000 4096 ;;
    lat_s2on_4k)  TS=1 run lat blocking n$k "$L" 3000 4096 ;;
    lat_s2sys_4k) BUILD=var_sys TS=1 run lat blocking n$k "$L" 3000 4096 ;;
    lat_base_256k)  BUILD=base run lat blocking n$k "$L" 3000 262144 ;;
    lat_s1off_256k) BUILD=s1 TS=0 run lat blocking n$k "$L" 3000 262144 ;;
    lat_s1on_256k)  BUILD=s1 TS=1 run lat blocking n$k "$L" 3000 262144 ;;
    lat_s2off_256k) TS=0 run lat blocking n$k "$L" 3000 262144 ;;
    lat_s2on_256k)  TS=1 run lat blocking n$k "$L" 3000 262144 ;;
    lat_s2sys_256k) BUILD=var_sys TS=1 run lat blocking n$k "$L" 3000 262144 ;;
    # --- B: many operations in flight (no gap: the QP is always busy; the fault is placed in the traffic by the
    #     library's test trigger NCCL_GIN_FAULT_INJECT_AT: rank 0 fires when its QP has posted >= n WQEs, rank 1
    #     when its signal 0 reached n; the INJECT delay is then only the bound on that wait) ---
    burst_none_b) TS=1 APP=burst GAP_US=0 EXTRA_ENV="GIN_TS_BURST_K=16 GIN_TS_AGG=1" run none blocking n$k "$L" 600 4096 ;;
    burst_f1_b)   TS=1 APP=burst GAP_US=0 INJECT=20000 R0_ENV="NCCL_GIN_FAULT_INJECT_AT=wqe:$(( 17 * (40 + (k * 37) % 500) + (k * 5) % 17 ))" \
                  EXTRA_ENV="GIN_TS_BURST_K=16 GIN_TS_AGG=1" run F1 blocking n$k "$L" 600 4096 ;;
    burst_f1na_b) TS=1 APP=burst GAP_US=0 INJECT=20000 R0_ENV="NCCL_GIN_FAULT_INJECT_AT=wqe:$(( 17 * (40 + (k * 37) % 500) + (k * 5) % 17 ))" \
                  EXTRA_ENV="GIN_TS_BURST_K=16 GIN_TS_AGG=0" run F1 blocking n$k "$L" 600 4096 ;;
    burst_f3_b)   TS=1 APP=burst GAP_US=0 INJECT=20000 R1_ENV="NCCL_GIN_FAULT_INJECT_AT=sig:$(( 40 + (k * 37) % 500 ))" \
                  EXTRA_ENV="GIN_TS_BURST_K=16 GIN_TS_AGG=1" run F3 blocking n$k "$L" 600 4096 ;;
    burst_f1rp_b) TS=1 APP=burst GAP_US=0 INJECT="20000,-1" R0_ENV="NCCL_GIN_FAULT_INJECT_AT=wqe:$(( 17 * (40 + (k * 37) % 500) + (k * 5) % 17 ))" \
                  EXTRA_ENV="GIN_TS_BURST_K=16 GIN_TS_AGG=1" run F1 blocking n$k "$L" 600 4096 ;;
    # several CTAs and threads posting bursts to one QP: 2 CTAs x 2 threads, K=8 aggregated + 1 signal each
    # (P x (K+1) = 36 <= the 128-slot ring)
    mtb_none_b) TS=1 APP=burst GAP_US=0 EXTRA_ENV="GIN_TS_TX_BLOCKS=2 GIN_TS_TX_THREADS=2 GIN_TS_BURST_K=8 GIN_TS_AGG=1" \
                run none blocking n$k "$L" 800 2048 ;;
    mtb_f1_b)   TS=1 APP=burst GAP_US=0 INJECT=20000 R0_ENV="NCCL_GIN_FAULT_INJECT_AT=wqe:$(( 36 * (40 + (k * 37) % 600) + (k * 7) % 36 ))" \
                EXTRA_ENV="GIN_TS_TX_BLOCKS=2 GIN_TS_TX_THREADS=2 GIN_TS_BURST_K=8 GIN_TS_AGG=1" run F1 blocking n$k "$L" 800 2048 ;;
    mtb_f3_b)   TS=1 APP=burst GAP_US=0 INJECT=20000 R1_ENV="NCCL_GIN_FAULT_INJECT_AT=sig:$(( 40 + (k * 37) % 600 ))" \
                EXTRA_ENV="GIN_TS_TX_BLOCKS=2 GIN_TS_TX_THREADS=2 GIN_TS_BURST_K=8 GIN_TS_AGG=1" run F3 blocking n$k "$L" 800 2048 ;;
    # P posting threads (put + signal, one doorbell per post) on one QP: the gates under contention; P x 2 WQEs
    # per iteration, so from P = 64 on the 128-slot ring is full and posters wait for slots
    mt*_none_b|mt*_f1_b)
                p=${CELL#mt}; p=${p%%_*}; f=none; [ "${CELL%_b}" != "mt${p}_none" ] && f=F1
                blk=1; thr=$p; [ "$p" -gt 256 ] && { blk=$(( p / 256 )); thr=256; }
                it=300; [ "$p" -gt 256 ] && it=100   # window <= 25 MiB each (rain's BAR1 is 256 MiB)
                # the trigger must lie inside the run (2 x p x it WQEs): with 100 iterations the multiplier stays < 90
                # (the first b3/b4b runs of mt1024 used % 200, and 4 of 10 triggers were past the end: no fault)
                m=200; [ "$p" -gt 256 ] && m=70
                TS=1 APP=burst GAP_US=0 INJECT=20000 R0_ENV="NCCL_GIN_FAULT_INJECT_AT=wqe:$(( 2 * p * (20 + (k * 13) % m) + (k * 3) % 64 ))" \
                WATCHDOG_S=60 EXTRA_ENV="GIN_TS_TX_BLOCKS=$blk GIN_TS_TX_THREADS=$thr GIN_TS_BURST_K=1 GIN_TS_AGG=0" \
                run $f blocking n$k "$L" $it 256 ;;
    # --- E: the post-commit residual (hold 4 s; the helper stalls after marking the round PUBLISHING) ---
    #   pub_ok_b: stall 10 s: device threads' second bound expires at 8 s, they see PUBLISHING and wait; the
    #             publication at 10 s -> transparent (S1 would have failed them at 8 s and re-posted anyway)
    #   pub_fail_b: stall 14 s: the third bound expires at 12 s -> the flush fails (the documented residual)
    pub_ok_b)   TS=1 R0_ENV="NCCL_GIN_TS_TEST_STALL=10000@publishing" \
                EXTRA_ENV="NCCL_GIN_TS_HOLD_MS=4000 NCCL_GIN_TS_HANDSHAKE_MS=10000 GIN_TS_POST_ABORT_WAIT_S=3" \
                INJECT=$inj run F1 blocking n$k "$L" 120 ;;
    pub_fail_b) TS=1 R0_ENV="NCCL_GIN_TS_TEST_STALL=14000@publishing GIN_TS_END_WAIT_S=6" \
                EXTRA_ENV="NCCL_GIN_TS_HOLD_MS=4000 NCCL_GIN_TS_HANDSHAKE_MS=10000 GIN_TS_RX_WAIT_S=20 GIN_TS_POST_ABORT_WAIT_S=3" \
                INJECT=$inj run F1 blocking n$k "$L" 120 ;;
    late_fail_b) TS=1 R0_ENV="NCCL_GIN_TS_TEST_STALL=12000@replay GIN_TS_END_WAIT_S=6" \
                 EXTRA_ENV="NCCL_GIN_TS_HOLD_MS=4000 NCCL_GIN_TS_HANDSHAKE_MS=10000 GIN_TS_RX_WAIT_S=12 GIN_TS_POST_ABORT_WAIT_S=3" \
                 INJECT=$inj run F1 blocking n$k "$L" 120 ;;
    s1_f1_b)  BUILD=s1 TS=1 INJECT=$inj run F1 blocking n$k "$L" 120 ;;
    bidir_none_base_b) BUILD=base APP=bidir run none blocking n$k "$L" 120 ;;
    # both directions on ONE context (the driver's GIN_TS_BIDIR_CTX=same), gpudb build: the pre-existing failure
    bidir_same_base_b) BUILD=base APP=bidir EXTRA_ENV="GIN_TS_BIDIR_CTX=same" run none blocking n$k "$L" 120 ;;
    bidir_none_off_b)  TS=0 APP=bidir run none blocking n$k "$L" 120 ;;
    # --- bidirectional root cause: the minimal program (../../gin_bidir_min.cu), unpatched gpudb build ---
    #   min_<mode>_<bytes>: mode both|d01|d10|seq; min_samectx_both_<bytes>: both directions on context 0
    #   (four windows of bytes x iters each: 64 iterations at 256 KiB = 4 x 16 MiB; 4 x 30 MiB failed to register
    #    on rain, NVRM "dmaAllocMapping_GM107: can't alloc VA space", BAR1)
    min_*)   m=${CELL#min_}; sc=""; [ "${m#samectx_}" != "$m" ] && { sc=1; m=${m#samectx_}; }
             md=${m%%_*}; by=${m##*_}; it=120; [ "$by" -ge 65536 ] && it=64
             CELL=$CELL BUILD=${MINBUILD:-base} SAME_CTX=$sc bash run_min.sh $md $by $it n$k "$L" ;;
    #   minx_* (bmin2, diagnostics on the gpudb build, 64 B x 120): both directions with sunny's sender delayed 2 s
    #   (txdelay), rain's sender paced 50 ms per put + sunny delayed 2 s (paced), the receiver kernels with 1 thread
    #   (rx1), and plain both at 64 B / 256 KiB with the kernel-end timing
    minx_both_txdelay_64) CELL=$CELL BUILD=base R1_ENV="MIN_TX_DELAY_MS=2000" bash run_min.sh both 64 120 n$k "$L" ;;
    minx_both_paced_64)   CELL=$CELL BUILD=base R0_ENV="MIN_TX_GAP_US=50000" R1_ENV="MIN_TX_DELAY_MS=2000" WATCHDOG_S=90 \
                          bash run_min.sh both 64 120 n$k "$L" ;;
    minx_both_rx1_64)     CELL=$CELL BUILD=base EXTRA_ENV="MIN_RX_THREADS=1" bash run_min.sh both 64 120 n$k "$L" ;;
    minx_both_64)         CELL=$CELL BUILD=base bash run_min.sh both 64 120 n$k "$L" ;;
    minx_both_262144)     CELL=$CELL BUILD=base bash run_min.sh both 262144 64 n$k "$L" ;;
    #   bmin3: the two roles as two CTAs of one kernel (fused), the sender launched before the receiver (txfirst)
    minx_fused_64)        CELL=$CELL BUILD=base bash run_min.sh fused 64 120 n$k "$L" ;;
    minx_fused_262144)    CELL=$CELL BUILD=base bash run_min.sh fused 262144 64 n$k "$L" ;;
    minx_txfirst_64)      CELL=$CELL BUILD=base bash run_min.sh txfirst 64 120 n$k "$L" ;;
    minx_fused_s2_64)     CELL=$CELL BUILD=s2 bash run_min.sh fused 64 120 n$k "$L" ;;
    #   bmin7: both senders paced (50 ms per put, 6 s), launched before the receivers: does a GIN receiver kernel run
    #   while a GIN sender kernel runs? (rx_sig_first/last_ms spread over 6 s: yes; both near 0: it started afterwards)
    minx_txfirst_paced_64) CELL=$CELL BUILD=base EXTRA_ENV="MIN_TX_GAP_US=50000" TIMEOUT_S=20 WATCHDOG_S=90 \
                           bash run_min.sh txfirst 64 120 n$k "$L" ;;
    #   bmin4: `both` with CUDA lazy module loading off (the sender kernel's launch otherwise waits for the running
    #   receiver kernel, see TRANSPARENT_S2.md C)
    minx_both_eager_64)     CELL=$CELL BUILD=base EXTRA_ENV="CUDA_MODULE_LOADING=EAGER" bash run_min.sh both 64 120 n$k "$L" ;;
    minx_both_eager_262144) CELL=$CELL BUILD=base EXTRA_ENV="CUDA_MODULE_LOADING=EAGER" bash run_min.sh both 262144 64 n$k "$L" ;;
    #   bmin6: `both` with more hardware queues for the streams (CUDA_DEVICE_MAX_CONNECTIONS=32; NCCL creates streams of
    #   its own, so with the default 8 the application's two streams can share one queue and serialize)
    minx_both_conn_64)     CELL=$CELL BUILD=base EXTRA_ENV="CUDA_DEVICE_MAX_CONNECTIONS=32" bash run_min.sh both 64 120 n$k "$L" ;;
    minx_both_conn_262144) CELL=$CELL BUILD=base EXTRA_ENV="CUDA_DEVICE_MAX_CONNECTIONS=32" bash run_min.sh both 262144 64 n$k "$L" ;;
    #   bmin5: `both` with the local-memory reservation raised up front (MIN_STACK_LIMIT)
    minx_both_stack_64)     CELL=$CELL BUILD=base EXTRA_ENV="MIN_STACK_LIMIT=2048" bash run_min.sh both 64 120 n$k "$L" ;;
    minx_both_stack_262144) CELL=$CELL BUILD=base EXTRA_ENV="MIN_STACK_LIMIT=2048" bash run_min.sh both 262144 64 n$k "$L" ;;
    # --- C: symmetric initiation ---
    bidir_none_b)   TS=1 APP=bidir run none blocking n$k "$L" 120 ;;
    # bidir variants (traffic sizes): both 4 KiB; rank 0 256 KiB + rank 1 64 B; both 64 B
    bidir4k_none_b)  TS=1 APP=bidir run none blocking n$k "$L" 120 4096 ;;
    bidir64r_none_b) TS=1 APP=bidir EXTRA_ENV="GIN_TS_R1_BYTES=64" run none blocking n$k "$L" 120 ;;
    bidir64_none_b)  TS=1 APP=bidir run none blocking n$k "$L" 120 64 ;;
    bidir_f1_b)     TS=1 APP=bidir INJECT=$inj run F1 blocking n$k "$L" 120 ;;
    # symmetric initiation with one-way traffic (bidirectional traffic loses data on this testbed on every build):
    # rank 0 posts 4 KiB back to back; the hook fires on BOTH ranks at the same delay after context creation; rank
    # 1's helper gets a LOCAL_QP_ERR record when its hook fires (test knob), rank 0's device reports the flushed
    # op; both helpers start a round within milliseconds. sym_notie_b: tie-break off (S1 behaviour).
    #   (rank 1's hook delay is rank 0's minus 1 or 2 ms: the offset at which both helpers started within ~1 ms of
    #   each other in the calibration run smoke6, where offsets of -6..+6 ms crossed only at -2 and -1)
    sym_b)       i0=$(( 60 + (k * 7) % 50 )); TS=1 GAP_US=0 INJECT=$i0 INJECT1=$(( i0 - 1 - k % 2 )) \
                 R1_ENV="NCCL_GIN_TS_TEST_SELF_REPORT=1" run F1both blocking n$k "$L" 8000 4096 ;;
    sym_notie_b) i0=$(( 60 + (k * 7) % 50 )); TS=1 GAP_US=0 INJECT=$i0 INJECT1=$(( i0 - 1 - k % 2 )) \
                 R1_ENV="NCCL_GIN_TS_TEST_SELF_REPORT=1" ABORT_WD_S=5 \
                 EXTRA_ENV="NCCL_GIN_TS_TIE_BREAK=0 GIN_TS_RX_WAIT_S=10" WATCHDOG_S=40 run F1both blocking n$k "$L" 8000 4096 ;;
    bidir_f1both_b) TS=1 APP=bidir INJECT=$inj run F1both blocking n$k "$L" 120 ;;
    # the same with CUDA lazy module loading off (CUDA_MODULE_LOADING=EAGER): both kernels of a rank then run at once
    bidir_eager_none_b)   TS=1 APP=bidir EXTRA_ENV="CUDA_MODULE_LOADING=EAGER" run none blocking n$k "$L" 120 ;;
    bidir_eager_f1both_b) TS=1 APP=bidir INJECT=$inj EXTRA_ENV="CUDA_MODULE_LOADING=EAGER" run F1both blocking n$k "$L" 120 ;;
    bidir_eager_f1both_notie_b) TS=1 APP=bidir INJECT=$inj ABORT_WD_S=5 WATCHDOG_S=40 \
                    EXTRA_ENV="CUDA_MODULE_LOADING=EAGER NCCL_GIN_TS_TIE_BREAK=0 GIN_TS_RX_WAIT_S=10" run F1both blocking n$k "$L" 120 ;;
    bidir_eager_none_base_b) BUILD=base APP=bidir EXTRA_ENV="CUDA_MODULE_LOADING=EAGER" run none blocking n$k "$L" 120 ;;
    # the same with the per-thread local-memory reservation raised before the launches (GIN_TS_STACK_LIMIT): the sender
    # kernel's larger stack frame no longer makes its launch wait for the running receiver kernel (TRANSPARENT_S2.md C)
    bidir_conn_none_b)    TS=1 APP=bidir EXTRA_ENV="CUDA_DEVICE_MAX_CONNECTIONS=32" run none blocking n$k "$L" 120 ;;
    bidir_conn_none_base_b) BUILD=base APP=bidir EXTRA_ENV="CUDA_DEVICE_MAX_CONNECTIONS=32" run none blocking n$k "$L" 120 ;;
    bidir_conn_f1both_b)  TS=1 APP=bidir INJECT=$inj EXTRA_ENV="CUDA_DEVICE_MAX_CONNECTIONS=32" run F1both blocking n$k "$L" 120 ;;
    bidir_conn_f1_b)      TS=1 APP=bidir INJECT=$inj EXTRA_ENV="CUDA_DEVICE_MAX_CONNECTIONS=32" run F1 blocking n$k "$L" 120 ;;
    bidir_conn_f1both_notie_b) TS=1 APP=bidir INJECT=$inj ABORT_WD_S=5 WATCHDOG_S=40 \
                    EXTRA_ENV="CUDA_DEVICE_MAX_CONNECTIONS=32 NCCL_GIN_TS_TIE_BREAK=0 GIN_TS_RX_WAIT_S=10" run F1both blocking n$k "$L" 120 ;;
    # bidir with the sender and receiver as two CTAs of ONE kernel (GIN_TS_BIDIR_FUSED=1): the working pattern (C)
    bidirf_none_b)        TS=1 APP=bidir EXTRA_ENV="GIN_TS_BIDIR_FUSED=1" run none blocking n$k "$L" 120 ;;
    bidirf_none_off_b)    TS=0 APP=bidir EXTRA_ENV="GIN_TS_BIDIR_FUSED=1" run none blocking n$k "$L" 120 ;;
    bidirf_none_base_b)   BUILD=base APP=bidir EXTRA_ENV="GIN_TS_BIDIR_FUSED=1" run none blocking n$k "$L" 120 ;;
    bidirf_f1_b)          TS=1 APP=bidir INJECT=$inj EXTRA_ENV="GIN_TS_BIDIR_FUSED=1" run F1 blocking n$k "$L" 120 ;;
    bidirf_f3_b)          TS=1 APP=bidir INJECT=$inj EXTRA_ENV="GIN_TS_BIDIR_FUSED=1" run F3 blocking n$k "$L" 120 ;;
    bidirf_f1both_b)      TS=1 APP=bidir INJECT=$inj EXTRA_ENV="GIN_TS_BIDIR_FUSED=1" run F1both blocking n$k "$L" 120 ;;
    # simultaneous initiation with real bidirectional traffic: 4 KiB back to back both ways, rank 1's hook 1-2 ms before
    # rank 0's (the calibrated offset of sym_b; with equal delays rank 1's fault fired 0.6-1.0 ms after rank 0's and its
    # helper always answered rank 0's REQ instead of initiating, c4)
    bidirf_sym_b)   i0=$(( 60 + (k * 7) % 50 )); TS=1 APP=bidir GAP_US=0 INJECT=$i0 INJECT1=$(( i0 - 1 - k % 2 )) \
                    EXTRA_ENV="GIN_TS_BIDIR_FUSED=1" run F1both blocking n$k "$L" 8000 4096 ;;
    bidirf_sym_notie_b) i0=$(( 60 + (k * 7) % 50 )); TS=1 APP=bidir GAP_US=0 INJECT=$i0 INJECT1=$(( i0 - 1 - k % 2 )) ABORT_WD_S=5 \
                    WATCHDOG_S=40 EXTRA_ENV="GIN_TS_BIDIR_FUSED=1 NCCL_GIN_TS_TIE_BREAK=0 GIN_TS_RX_WAIT_S=10" run F1both blocking n$k "$L" 8000 4096 ;;
    bidirf_f1both_notie_b) TS=1 APP=bidir INJECT=$inj ABORT_WD_S=5 WATCHDOG_S=40 \
                    EXTRA_ENV="GIN_TS_BIDIR_FUSED=1 NCCL_GIN_TS_TIE_BREAK=0 GIN_TS_RX_WAIT_S=10" run F1both blocking n$k "$L" 120 ;;
    bidir_stack_none_b)   TS=1 APP=bidir EXTRA_ENV="GIN_TS_STACK_LIMIT=2048" run none blocking n$k "$L" 120 ;;
    bidir_stack_none_base_b) BUILD=base APP=bidir EXTRA_ENV="GIN_TS_STACK_LIMIT=2048" run none blocking n$k "$L" 120 ;;
    bidir_stack_f1both_b) TS=1 APP=bidir INJECT=$inj EXTRA_ENV="GIN_TS_STACK_LIMIT=2048" run F1both blocking n$k "$L" 120 ;;
    bidir_stack_f1_b)     TS=1 APP=bidir INJECT=$inj EXTRA_ENV="GIN_TS_STACK_LIMIT=2048" run F1 blocking n$k "$L" 120 ;;
    bidir_stack_f1both_notie_b) TS=1 APP=bidir INJECT=$inj ABORT_WD_S=5 WATCHDOG_S=40 \
                    EXTRA_ENV="GIN_TS_STACK_LIMIT=2048 NCCL_GIN_TS_TIE_BREAK=0 GIN_TS_RX_WAIT_S=10" run F1both blocking n$k "$L" 120 ;;
    bidir_f1both_notie_b) TS=1 APP=bidir INJECT=$inj ABORT_WD_S=5 EXTRA_ENV="NCCL_GIN_TS_TIE_BREAK=0 GIN_TS_RX_WAIT_S=10" \
                    WATCHDOG_S=40 run F1both blocking n$k "$L" 120 ;;
    # --- D: address flap on the secondary GIDs (16 KiB x 1800, 15 ms gap: a ~27 s loop; windows <= 28 MiB:
    #     larger GIN windows fail to register on rain, whose BAR1 is 256 MiB) ---
    #     flap_s2_20 / flap_s2_30 (review): cuts near and beyond the path-wait bound (the local GID must be back
    #     within NCCL_GIN_TS_PATH_WAIT_MS, 21 s after the clamp, of the round's start): 20 s transparent, 30 s a
    #     clean decline (longer bounds so the receiver's own wait and the abort can run out normally)
    flap_s1_05|flap_s1_6|flap_s1_15|flap_s2_05|flap_s2_6|flap_s2_15|flap_s2_20|flap_s2_30)
                b=${CELL#flap_}; b=${b%%_*}; c=${CELL##*_}; [ "$c" = 05 ] && c=0.5
                wd=100; awd=10; [ "$c" -ge 20 ] 2>/dev/null && { wd=140; awd=30; }
                BUILD=$b TS=1 GIDSEL=secondary CUT_S=$c CUT_DELAY_MS=2000 WATCHDOG_S=$wd ABORT_WD_S=$awd \
                EXTRA_ENV="GIN_TS_RX_WAIT_S=40" run none blocking n$k "$L" 1800 16384 ;;
    # --- review: the slot wait's ring (vendored doca_gpunetio_dev_verbs_qp.cuh). K = 128 aggregated puts fill the
    #     whole 128-slot SQ before the signal; the signal's poster then waits for slot 0, whose WQE was never rung
    #     (stock DOCA spins there forever). ring_none_b: fault-free; ring_f4_b: rank 1 killed mid-run (decline:
    #     HOST_FAILED with an even epoch); ring_f2_b: an invalid remote offset at iteration 10 (REM_ACCESS, decline).
    #     The kernel must exit and ncclCommAbort return in every case. ---
    ring_none_b) TS=1 APP=burst GAP_US=15000 EXTRA_ENV="GIN_TS_BURST_K=128 GIN_TS_AGG=1" run none blocking n$k "$L" 200 1024 ;;
    ring_f4_b)   TS=1 APP=burst GAP_US=30000 KILL_DELAY_MS=$(( 3500 + (k * 211) % 900 )) WATCHDOG_S=40 \
                 EXTRA_ENV="GIN_TS_BURST_K=128 GIN_TS_AGG=1" run F4 blocking n$k "$L" 200 1024 ;;
    ring_f2_b)   TS=1 APP=burst GAP_US=15000 ABORT_WD_S=5 EXTRA_ENV="GIN_TS_BURST_K=128 GIN_TS_AGG=1" run F2 blocking n$k "$L" 200 1024 ;;
    # --- review: the host's ring of unrung aggregated WQEs (gdakiTsQuiesce -> gdakiTsRing): 16 aggregated puts, then
    #     a 20 ms pause before the signal that would ring for them; the local fault (hook delay) lands in that pause
    #     with high probability, so the quiesce finds sq_wqe_pi < sq_ready_index and rings from the host ---
    #     (burst_hring_b: the helper learns of the fault only when the poster's next post fails, i.e. after the signal
    #      rang: host_rung = 0 in 5/5. burst_hring2_b adds the self-report knob, so the helper starts its round while the
    #      poster is still in the pause and the 16 puts are still unrung)
    burst_hring_b) TS=1 APP=burst GAP_US=0 INJECT=$inj EXTRA_ENV="GIN_TS_BURST_K=16 GIN_TS_AGG=1 GIN_TS_AGG_GAP_US=20000" \
                   run F1 blocking n$k "$L" 300 4096 ;;
    burst_hring2_b) TS=1 APP=burst GAP_US=0 INJECT=$inj R0_ENV="NCCL_GIN_TS_TEST_SELF_REPORT=1" \
                   EXTRA_ENV="GIN_TS_BURST_K=16 GIN_TS_AGG=1 GIN_TS_AGG_GAP_US=20000" run F1 blocking n$k "$L" 300 4096 ;;
    *) echo "unknown cell $CELL" >&2; exit 1 ;;
  esac
done
