#!/usr/bin/env bash
# S2 holds (each <= 15 min, run inside ../../../common/cluster_run.sh). Results: <resultsdir>/<subdir>/.
# usage: hold.sh <resultsdir> <hold>
set -u
R=${1:?resultsdir}; H=${2:?hold}
cd "$(dirname "$0")"
SUNNY_SSH=${SUNNY_SSH:-unionxic@192.0.2.194}
snap() {  # read-only state of both nodes: GPU users, kernel messages of mlx5, firmware command failures
  echo "== $1 $(date '+%F %T')"
  nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader 2>/dev/null | sed 's/^/rain gpu: /'
  ssh -n "$SUNNY_SSH" "nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader" 2>/dev/null | sed 's/^/sunny gpu: /'
  echo "rain gpu clocks: $(nvidia-smi --query-gpu=clocks.sm,clocks.max.sm,pstate,utilization.gpu --format=csv,noheader)"
  echo "sunny gpu clocks: $(ssh -n "$SUNNY_SSH" "nvidia-smi --query-gpu=clocks.sm,clocks.max.sm,pstate,utilization.gpu --format=csv,noheader")"
  echo "rain mlx5 dmesg lines: $(sudo -n dmesg 2>/dev/null | grep -c mlx5)"
  echo "sunny mlx5 dmesg lines: $(ssh -n "$SUNNY_SSH" "sudo -n dmesg 2>/dev/null | grep -c mlx5")"
  bash ../ts1/fwcmd_snapshot.sh "$1" > "$R/fwcmd_$1.txt" 2>&1
}
mkdir -p "$R"
snap "before-$H"
case "$H" in
  smoke1)
    bash gate_test.sh "$R/gate_smoke.txt" 5
    for c in none_b f1_b f3_b f1g0_b lat_s2on_4k lat_s2off_4k burst_none_b burst_f1_b mtb_none_b mt16_none_b mt1024_none_b \
             bidir_none_b bidir_f1both_b f2_b; do bash batch.sh "$R/smoke1" $c 1; done ;;
  smoke2)   # after E, the traffic trigger and the driver fixes: one of each new cell, plus comparisons
    for c in bidir_none_b bidir_none_off_b bidir_none_base_b f1_b s1_f1_b f1_b s1_f1_b burst_f1_b burst_f3_b burst_f1rp_b \
             mtb_f1_b mt64_none_b mt256_none_b mt1024_none_b mt64_f1_b mt256_f1_b mt1024_f1_b bidir_f1both_b pub_ok_b; do
      bash batch.sh "$R/smoke2" $c 1; done ;;
  smoke3)   # after the trigger fix and split-context bidir
    for c in bidir_none_b bidir_f1both_b bidir_f1both_b bidir_f1_b burst_f1_b burst_f3_b burst_f1rp_b mtb_f1_b mtb_f3_b \
             mt64_f1_b mt256_f1_b mt1024_none_b mt1024_f1_b; do bash batch.sh "$R/smoke3" $c 1; done ;;
  smoke4)   # bidir traffic sizes (the 256 KiB both-ways case loses data on every build), burst without aggregation
    for c in bidir4k_none_b bidir64r_none_b bidir64_none_b burst_f1na_b burst_f1na_b; do bash batch.sh "$R/smoke4" $c 1; done ;;
  smoke5)   # symmetric initiation with the self-report knob; one flap-free sanity cell
    bash batch.sh "$R/smoke5" sym_b 4; bash batch.sh "$R/smoke5" sym_notie_b 2; bash batch.sh "$R/smoke5" f1_b 1 ;;
  smoke6)   bash batch.sh "$R/smoke6" sym_b 13 ;;
  fill1)    # replacements for trials that failed before NCCL started (driver rendezvous port in use)
    bash batch.sh "$R/reg" f1_b 1 11; bash batch.sh "$R/b" burst_f3_b 1 11 ;;
  bmin)     # bidirectional root cause on the unpatched gpudb build: each direction alone, both at once, sequential
    for c in min_d01_262144 min_d10_262144 min_d01_64 min_d10_64 min_both_262144 min_both_64; do bash batch.sh "$R/bmin" $c 5; done
    for c in min_seq_262144 min_samectx_both_262144 min_hostrx_262144 min_txonly_262144; do bash batch.sh "$R/bmin" $c 3; done ;;
  b4)       for p in 16 64 256 1024; do bash batch.sh "$R/b" mt${p}_f1_b 5 6; done ;;
  bmin2)    # bidirectional diagnostics on the gpudb build (see batch.sh minx_*)
    for c in minx_both_64 minx_both_262144; do bash batch.sh "$R/bmin" $c 2; done
    for c in minx_both_txdelay_64 minx_both_paced_64 minx_both_rx1_64; do bash batch.sh "$R/bmin" $c 3; done ;;
  bmin3)    # do two kernels on two streams run concurrently on these GPUs? then the fused and txfirst modes
    for o in spinfirst quickfirst; do
      echo "rain: $(~/gi-bundle/gin_ts2/two_streams_test 2000 $o)"
      echo "sunny: $(ssh -n "$SUNNY_SSH" "~/gi-bundle/gin_ts2/two_streams_test 2000 $o")"
    done | tee "$R/two_streams.txt"
    for c in minx_fused_64 minx_fused_262144 minx_txfirst_64 minx_fused_s2_64; do bash batch.sh "$R/bmin" $c 3; done ;;
  bmin4)    # lazy module loading off: the minimal program's `both`, then the driver's bidir cells (fault-free, F1 on both)
    for c in minx_both_eager_64 minx_both_eager_262144; do bash batch.sh "$R/bmin" $c 3; done
    for c in bidir_eager_none_base_b bidir_eager_none_b bidir_eager_f1both_b; do bash batch.sh "$R/c" $c 3; done ;;
  bmin5)    # the local-memory reservation raised up front: the minimal program's `both`, then the driver's bidir cells
    for c in minx_both_stack_64 minx_both_stack_262144; do bash batch.sh "$R/bmin" $c 3; done
    for c in bidir_stack_none_base_b bidir_stack_none_b bidir_stack_f1both_b; do bash batch.sh "$R/c" $c 3; done ;;
  bmin6)    # more hardware queues (CUDA_DEVICE_MAX_CONNECTIONS=32): the minimal program's `both`, then the driver's bidir cells
    for c in minx_both_conn_64 minx_both_conn_262144; do bash batch.sh "$R/bmin" $c 3; done
    for c in bidir_conn_none_base_b bidir_conn_none_b bidir_conn_f1both_b; do bash batch.sh "$R/c" $c 3; done ;;
  bmin7)    bash batch.sh "$R/bmin" minx_txfirst_paced_64 3 ;;
  fill2)    # replacements for final-build trials lost to the driver's rendezvous port (bind: Address already in use)
    bash batch.sh "$R/reg" f1g0_b 1 31; bash batch.sh "$R/reg" f2_b 1 11; bash batch.sh "$R/b" mt1024_none_b 1 4 ;;
  fix1)     # after the stale-root classifier fix: the 256- and 1024-thread F1 cells again (n=10; the earlier runs go to
            # b/superseded), the full-ring cells and the host-ring cell (the poster-side report path), one F1 sanity
    mkdir -p "$R/b/superseded"; mv "$R"/b/mt256_f1_b_* "$R"/b/mt1024_f1_b_* "$R/b/superseded/" 2>/dev/null
    for p in 256 1024; do bash batch.sh "$R/b" mt${p}_f1_b 10; done
    for c in ring_f4_b ring_f2_b; do bash batch.sh "$R/new" $c 5 6; done
    bash batch.sh "$R/new" burst_hring2_b 3 6; bash batch.sh "$R/reg" f1_b 3 11 ;;
  c5)       # simultaneous initiation with real bidirectional traffic (fused kernel), tie-break on (n=20) and off (n=5)
    bash batch.sh "$R/c" bidirf_sym_b 20; bash batch.sh "$R/c" bidirf_sym_notie_b 5 ;;
  c4)       # C with real bidirectional traffic (one kernel, two CTAs per rank) and faults on both sides, no self-report knob
    for c in bidirf_none_base_b bidirf_none_off_b; do bash batch.sh "$R/c" $c 3; done
    bash batch.sh "$R/c" bidirf_none_b 5; bash batch.sh "$R/c" bidirf_f1both_b 20
    for c in bidirf_f1_b bidirf_f3_b bidirf_f1both_notie_b; do bash batch.sh "$R/c" $c 5; done ;;
  stacks)   # two plain kernels on two streams, with stack frames like the GIN kernels' (spinner small, quick kernel larger),
            # with and without a raised stack limit, on both GPUs
    for args in "0 0 0" "256 1024 0" "256 1024 4096" "1024 256 0" "1024 1024 0" "256 4096 0" "4096 256 0"; do
      echo "rain: $(~/gi-bundle/gin_ts2/two_streams_test 2000 spinfirst $args)"
      echo "sunny: $(ssh -n "$SUNNY_SSH" "~/gi-bundle/gin_ts2/two_streams_test 2000 spinfirst $args")"
    done | tee "$R/two_streams_stacks.txt" ;;
  c3)       # C with real bidirectional traffic and faults on both sides (no self-report knob), 32 hardware queues
    bash batch.sh "$R/c" bidir_conn_none_b 5; bash batch.sh "$R/c" bidir_conn_f1both_b 20
    bash batch.sh "$R/c" bidir_conn_f1_b 5; bash batch.sh "$R/c" bidir_conn_f1both_notie_b 5 ;;
  c2)       # C with real bidirectional traffic and faults on both sides (no self-report knob)
    bash batch.sh "$R/c" bidir_stack_none_b 5; bash batch.sh "$R/c" bidir_stack_f1both_b 20
    bash batch.sh "$R/c" bidir_stack_f1_b 5; bash batch.sh "$R/c" bidir_stack_f1both_notie_b 5 ;;
  # --- the reviewed build (results/20261001_ts2): the review cells, then the same regression, flap and B cells ---
  smoke7)   for c in f1_b ring_none_b ring_f4_b ring_f2_b burst_hring_b mt1024_f1_b; do bash batch.sh "$R/smoke7" $c 1; done ;;
  new1)     for c in ring_none_b ring_f4_b ring_f2_b burst_hring_b; do bash batch.sh "$R/new" $c 5; done ;;
  new2)     bash batch.sh "$R/new" burst_hring2_b 5 ;;
  b4a)      for p in 16 64; do bash batch.sh "$R/b" mt${p}_none_b 3; bash batch.sh "$R/b" mt${p}_f1_b 10; done ;;
  b4b)      for p in 256 1024; do bash batch.sh "$R/b" mt${p}_none_b 3; bash batch.sh "$R/b" mt${p}_f1_b 10; done ;;
  d4)       # D.3 (review): the S2 build at the path-wait bound: a 20 s cut (inside it) and a 30 s cut (beyond), n=3
    GBH=../../../../nccl-integration/stage2/gid_blackhole.sh
    bash $GBH setup > "$R/gbh_setup_$H.txt" 2>&1; cat "$R/gbh_setup_$H.txt"
    trap 'bash $GBH teardown > "$R/gbh_teardown_$H.txt" 2>&1; cat "$R/gbh_teardown_$H.txt"' EXIT
    for c in flap_s2_20 flap_s2_30; do bash batch.sh "$R/d" $c 3; done ;;
  lat)      # A: the gate micro-test on both GPUs, then fault-free latency, 5 interleaved repetitions
    bash gate_test.sh "$R/gate_test.txt" 10
    for k in 1 2 3 4 5; do
      for c in lat_base_4k lat_s1off_4k lat_s1on_4k lat_s2off_4k lat_s2on_4k lat_s2sys_4k \
               lat_base_256k lat_s1off_256k lat_s1on_256k lat_s2off_256k lat_s2on_256k lat_s2sys_256k; do
        bash batch.sh "$R/lat" $c 1 $k; done; done ;;
  reg1)     for c in none_b f1_b f3_b f1x5_b; do bash batch.sh "$R/reg" $c 10; done ;;
  reg2)     bash batch.sh "$R/reg" f1g0_b 30; for c in f2_b f4_b; do bash batch.sh "$R/reg" $c 10; done ;;
  reg3)     for c in neg_norebase_t neg_noring_t; do bash batch.sh "$R/reg" $c 10; done
            for c in off_f1_b base_f1_b; do bash batch.sh "$R/reg" $c 5; done ;;
  e1)       for c in pub_ok_b pub_fail_b; do bash batch.sh "$R/e" $c 5; done; bash batch.sh "$R/e" late_fail_b 3 ;;
  b1)       bash batch.sh "$R/b" burst_none_b 3
            for c in burst_f1_b burst_f1na_b burst_f3_b burst_f1rp_b; do bash batch.sh "$R/b" $c 10; done ;;
  b2)       bash batch.sh "$R/b" mtb_none_b 3
            for c in mtb_f1_b mtb_f3_b; do bash batch.sh "$R/b" $c 10; done ;;
  b3)       for p in 16 64 256 1024; do bash batch.sh "$R/b" mt${p}_none_b 3; bash batch.sh "$R/b" mt${p}_f1_b 5; done ;;
  c1)       bash batch.sh "$R/c" sym_b 30; bash batch.sh "$R/c" sym_notie_b 10
            for c in bidir_none_b bidir_none_base_b bidir_same_base_b; do bash batch.sh "$R/c" $c 2; done ;;
  d1)       # D.1: the S1 build under address flaps (secondary GIDs), n=2 per cut length
    GBH=../../../../nccl-integration/stage2/gid_blackhole.sh
    bash $GBH setup > "$R/gbh_setup_d1.txt" 2>&1; cat "$R/gbh_setup_d1.txt"
    trap 'bash $GBH teardown > "$R/gbh_teardown_d1.txt" 2>&1; cat "$R/gbh_teardown_d1.txt"' EXIT
    for c in flap_s1_05 flap_s1_6 flap_s1_15; do bash batch.sh "$R/d" $c 2; done ;;
  d2|d3)    # D.2: the S2 build under address flaps; d2 = 0.5 s and 6 s, d3 = 15 s (n=5 each)
    GBH=../../../../nccl-integration/stage2/gid_blackhole.sh
    bash $GBH setup > "$R/gbh_setup_$H.txt" 2>&1; cat "$R/gbh_setup_$H.txt"
    trap 'bash $GBH teardown > "$R/gbh_teardown_$H.txt" 2>&1; cat "$R/gbh_teardown_$H.txt"' EXIT
    if [ "$H" = d2 ]; then for c in flap_s2_05 flap_s2_6; do bash batch.sh "$R/d" $c 5; done
    else bash batch.sh "$R/d" flap_s2_15 5; fi ;;
  *) echo "unknown hold $H" >&2; exit 2 ;;
esac
snap "after-$H"
