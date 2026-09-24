#!/usr/bin/env bash
# experiments.sh - the runs done with GPU-rung doorbells (PeerMappingOverride=1).
# Called by window.sh inside the driver-reload window, which already holds the cluster
# lock, so the per-trial runners are called directly (not through cluster_run.sh).
# Same runners, binaries and knobs as the CPU-doorbell results in ../nvshmem and ../gin_q4;
# only the doorbell path differs.
set -u
G=/home/unionxic/rdma-error/harness/gpu-initiated
OUT=$G/gpu_doorbell/results/$(date +%Y%m%d)
mkdir -p "$OUT/nvshmem" "$OUT/gin_q4"
say() { echo "$(date '+%T') [exp] $*"; }

# ---- 1. NVSHMEM IBGDA: does an error CQE reach the CQ when the GPU rings the doorbell?
cd "$G/nvshmem"
export DEV_TIMEOUT_MS=6000 PROC_TIMEOUT=60
NV="$OUT/nvshmem/matrix.csv"
for t in 1 2; do say "nvshmem none t$t"; ./run_trial.sh none timeout $t "$OUT/nvshmem" >> "$NV"; done
say "nvshmem NIC handler: $(grep -h -o 'NIC handler will be[^.]*' "$OUT/nvshmem/none_timeout_t1.pe0.log" | head -1)"
for f in F2b F1 F3; do
  for t in 1 2 3; do say "nvshmem $f t$t"; ./run_trial.sh $f timeout $t "$OUT/nvshmem" >> "$NV"; done
done
say "nvshmem F2b blocking"; ./run_trial.sh F2b blocking 1 "$OUT/nvshmem" >> "$NV"

# ---- 2. NCCL GIN GDAKI with the Q4 classifier, GPU doorbell ----------------------------
cd "$G/gin_q4"
for t in 1 2; do say "gin none t$t"; CLASSIFY=1 ./scripts/run_trial.sh none timeout $t "$OUT/gin_q4/q4.csv"; done
for f in F1 F2 F3; do
  for t in 1 2; do say "gin $f t$t"; CLASSIFY=1 ./scripts/run_trial.sh $f timeout $t "$OUT/gin_q4/q4.csv"; done
done
for t in 1 2; do say "gin stock F1 blocking t$t"; CLASSIFY=0 ./scripts/run_trial.sh F1 blocking $t "$OUT/gin_q4/stock.csv"; done
for f in none F2; do say "gin collapsed $f"; CQ_TYPE=collapsed CLASSIFY=1 ./scripts/run_trial.sh $f timeout 1 "$OUT/gin_q4/q4_collapsed.csv"; done
say "gin latency (no fault), classifier off and on"
CLASSIFY=0 ./scripts/run_trial.sh lat timeout 1 "$OUT/gin_q4/lat.csv"
CLASSIFY=1 ./scripts/run_trial.sh lat timeout 2 "$OUT/gin_q4/lat.csv"
say "done"
