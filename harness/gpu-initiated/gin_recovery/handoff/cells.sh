#!/usr/bin/env bash
# gin-handoff: every cell of EXPERIMENT.md section 7 (one bounded batch; run inside a hold of hold.sh, itself inside
# ../../common/cluster_run.sh through chain.sh). All trials go through ../harden/run_trial_hd.sh (kills only PIDs it
# recorded; no address change; iptables only with MGMT_MUTE, which no cell of this study sets).
# usage: cells.sh <logdir> <cell> <build> <n> [start]
# Builds (bundle directories under $HOME/gi-bundle/gin_ts2): hf (this study, research build), hfp (production build),
# hd and hdp (gin-harden, deployed, unchanged).
# Cells taken over from gin-harden run ../harden/cells.sh with the same definition (only the build differs):
#   f1_b f3_b bidirf_sym_b f4_b f2rel_b hd_rxdeath_b hd_shrink_b hdp_kill_b lat_4k lat_256k
set -u
L=${1:?logdir}; CELL=${2:?cell}; B=${3:?build}; N=${4:?n}; START=${5:-1}
D=$(cd "$(dirname "$0")" && pwd)
H=$D/../harden
case "$CELL" in
  f1_b|f3_b|bidirf_sym_b|f4_b|f2rel_b|hd_rxdeath_b|hd_shrink_b|hdp_kill_b|lat_4k|lat_256k)
    exec bash "$H/cells.sh" "$L" "$CELL" "$B" "$N" "$START" ;;
esac
run() { CELL=$CELL BUILD=$B bash "$H/run_trial_hd.sh" "$@"; }
for ((k = START; k < START + N; k++)); do
  inj=$(( 500 + (k * 137) % 700 ))   # as ../scripts/ts2/batch.sh: ms after the GDAKI context's creation
  case "$CELL" in
    # shrink hand-off with the switch off (hf): hd_shrink_b of ../harden/cells.sh plus NCCL_GIN_SHRINK_HANDOFF=0 on
    # rank 0 (the stock check: the shrink must fail with the parent's GIN error)
    hf_shrinkoff_b) TS=1 APP=bidir KILL_DELAY_MS=3500 ABORT_WD_S=30 WATCHDOG_S=90 \
             EXTRA_ENV="GIN_TS_BIDIR_FUSED=1 GIN_TS_RX_WAIT_S=60" \
             R0_ENV="GIN_TS_SHRINK=1 GIN_TS_HO_WAIT_S=3 GIN_TS_POST_ABORT_WAIT_S=10 NCCL_GIN_SHRINK_HANDOFF=0" \
             run F4 blocking n$k "$L" 400 16384 ;;
    # the application's "devComm first" way around the stock check (switch off): hd_shrink_b plus, on rank 0,
    # NCCL_GIN_SHRINK_HANDOFF=0 and ncclDevCommDestroy before the shrink (GIN_TS_SHRINK_DEVCOMM_DESTROY=1)
    hf_shrinkdc_b) TS=1 APP=bidir KILL_DELAY_MS=3500 ABORT_WD_S=30 WATCHDOG_S=90 \
             EXTRA_ENV="GIN_TS_BIDIR_FUSED=1 GIN_TS_RX_WAIT_S=60" \
             R0_ENV="GIN_TS_SHRINK=1 GIN_TS_HO_WAIT_S=3 GIN_TS_POST_ABORT_WAIT_S=10 NCCL_GIN_SHRINK_HANDOFF=0 GIN_TS_SHRINK_DEVCOMM_DESTROY=1" \
             run F4 blocking n$k "$L" 400 16384 ;;
    # The GPU full of an application kernel (hd_hog_f1_b of ../harden/cells.sh: f1_b, both ranks GIN_TS_HOG_MS=3000) with
    # the copy probe on both ranks, in a 2 x 2: the calls between the GIN launch and the GPU-filling launch as in
    # gin-harden (occupancy query that loads the kernel, cudaMalloc, stream) or none of them (GIN_TS_HOG_PREALLOC=1), and
    # the GPU-filling grid at its full size or one block smaller (GIN_TS_HOG_SLACK=1).
    # hf_hog_f1_b: as gin-harden's pilot; rank 0 then shrinks to itself (rank 1 alive): a watchdog surface of the stalled
    # helper names no peer, so the hand-off must keep the stock answer
    hf_hog_f1_b) TS=1 INJECT=$inj EXTRA_ENV="GIN_TS_HOG_MS=3000 GIN_TS_HOG_PROBE=1" \
             R0_ENV="GIN_TS_SHRINK=1 GIN_TS_HO_WAIT_S=3" run F1 blocking n$k "$L" 120 ;;
    hf_hogslack_f1_b) TS=1 INJECT=$inj EXTRA_ENV="GIN_TS_HOG_MS=3000 GIN_TS_HOG_SLACK=1 GIN_TS_HOG_PROBE=1" \
             run F1 blocking n$k "$L" 120 ;;
    hf_hogpre_f1_b) TS=1 INJECT=$inj EXTRA_ENV="GIN_TS_HOG_MS=3000 GIN_TS_HOG_PREALLOC=1 GIN_TS_HOG_PROBE=1" \
             run F1 blocking n$k "$L" 120 ;;
    hf_hogpreslack_f1_b) TS=1 INJECT=$inj \
             EXTRA_ENV="GIN_TS_HOG_MS=3000 GIN_TS_HOG_PREALLOC=1 GIN_TS_HOG_SLACK=1 GIN_TS_HOG_PROBE=1" \
             run F1 blocking n$k "$L" 120 ;;
    *) echo "unknown cell $CELL" >&2; exit 1 ;;
  esac
done
