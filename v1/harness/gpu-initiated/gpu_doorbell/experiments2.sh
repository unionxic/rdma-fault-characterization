#!/usr/bin/env bash
# experiments2.sh - second GPU-doorbell window: the NVSHMEM runs that window 1 lost to
# sunny's CUDA device-node mismatch, plus one INFO-level GIN run per CQ type to record
# which doorbell path GDAKI actually used.
set -u
G=/home/unionxic/rdma-error/harness/gpu-initiated
OUT=$G/gpu_doorbell/results/$(date +%Y%m%d)_w2
mkdir -p "$OUT/nvshmem" "$OUT/gin_q4"
say() { echo "$(date '+%T') [exp2] $*"; }

cd "$G/nvshmem"
export DEV_TIMEOUT_MS=6000 PROC_TIMEOUT=60
NV="$OUT/nvshmem/matrix.csv"
for t in 1 2; do say "nvshmem none t$t"; ./run_trial.sh none timeout $t "$OUT/nvshmem" >> "$NV"; done
say "nvshmem NIC handler: $(grep -h -o 'NIC handler will be[^.]*' "$OUT/nvshmem/none_timeout_t1.pe0.log" | head -1)"
for f in F2b F1 F3; do
  for t in 1 2 3; do say "nvshmem $f t$t"; ./run_trial.sh $f timeout $t "$OUT/nvshmem" >> "$NV"; done
done
say "nvshmem F2b blocking"; ./run_trial.sh F2b blocking 1 "$OUT/nvshmem" >> "$NV"

cd "$G/gin_q4"
INFOENV="NCCL_DEBUG=INFO NCCL_DEBUG_SUBSYS=INIT,NET"
for t in 1 2; do say "gin none t$t (INFO)"; EXTRA_ENV="$INFOENV" CLASSIFY=1 ./scripts/run_trial.sh none timeout $t "$OUT/gin_q4/q4.csv"; done
for t in 1 2; do say "gin F1 t$t"; CLASSIFY=1 ./scripts/run_trial.sh F1 timeout $t "$OUT/gin_q4/q4.csv"; done
say "gin collapsed F1"; CQ_TYPE=collapsed CLASSIFY=1 ./scripts/run_trial.sh F1 timeout 1 "$OUT/gin_q4/q4_collapsed.csv"
say "gin collapsed F3"; CQ_TYPE=collapsed CLASSIFY=1 ./scripts/run_trial.sh F3 timeout 1 "$OUT/gin_q4/q4_collapsed.csv"
say "done"
