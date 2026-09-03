#!/bin/bash
# run_ab_recovery.sh — Compare reactive (A) vs proactive (B) recovery for an
# address-violation (REM_ACCESS_ERR / NAK) partial RDMA WRITE.
#
# Strategy A: normal WRITE, no bound check; on NAK -> sq_psn reconstruction +
#             QP-only recovery + whole-message resend. Corruption window > 0.
# Strategy B: pre-flight local range check every WRITE; violation corrected
#             before hitting the wire. No partial; corruption window = 0.
#
# Run from client (225). Server (224) reached over SSH and started here.
# The control TCP socket stays alive across all iterations within one run; each
# (strategy, err_pct, msg_size) combination is a fresh client process so the
# server resets resources between combos (SHUTDOWN -> new SETUP_AB).
#
# Usage: ./run_ab_recovery.sh [num_iters] [warmup] [mr_size]
#   num_iters : measured iters per combo     (default 10000)
#   warmup    : warmup iters per combo        (default 200)
#   mr_size   : server registered MR bytes    (default 65536)
#
# Sweep (edit the arrays below to change):
#   strategies : A B
#   err_pcts   : 0 1 10
#   msg_sizes  : 1024 4096   (single-packet and multi-packet)

set -e

REMOTE="gustlr@SERVER_224_ADDR"
REMOTE_DIR="/home/gustlr/Desktop/gpu_fault_recovery/05_counter_mapping"

NUM_ITERS=${1:-10000}
WARMUP=${2:-200}
MR_SIZE=${3:-65536}

STRATEGIES=(A B)
ERR_PCTS=(0 1 10)
MSG_SIZES=(1024 4096)

CSV="results/raw/ab_recovery.csv"
HEADER="strategy,iter,msg_size,err_pct,mr_size,phase,sq_psn_delta,detect_us,recover_us,corrupt_us,landed_bytes,partial_truth_bytes,recon_match,norm_mean_us,norm_p50_us,norm_p99_us,norm_count,total_wall_us"

echo "=== A/B recovery-strategy comparison (REM_ACCESS_ERR partial WRITE) ==="
echo "iters/combo : $NUM_ITERS   warmup: $WARMUP   mr_size: $MR_SIZE"
echo "strategies  : ${STRATEGIES[*]}"
echo "err_pcts    : ${ERR_PCTS[*]} (%)"
echo "msg_sizes   : ${MSG_SIZES[*]} (bytes; PMTU=1024)"
echo ""

# Clean any stale server, rebuild both sides.
ssh "$REMOTE" "pkill -f './server'" 2>/dev/null || true
sleep 1

echo "[build] Compiling on 224 (server)..."
ssh "$REMOTE" "cd $REMOTE_DIR && make server"
echo "[build] Compiling locally (client)..."
make ab_recovery

mkdir -p results/raw

# Fresh CSV with header.
echo "$HEADER" > "$CSV"

run_combo() {
	local strat=$1 err=$2 msg=$3

	echo "[orchestrator] (re)starting server on 224..."
	ssh "$REMOTE" "pkill -f './server'" 2>/dev/null || true
	sleep 1
	ssh -f "$REMOTE" "cd $REMOTE_DIR && nohup ./server > /tmp/server_ab.log 2>&1 < /dev/null & exit"
	sleep 1

	echo "[run] strategy=$strat err_pct=$err msg_size=$msg"
	# ab_recovery appends to $CSV (header already present).
	./ab_recovery "$strat" "$NUM_ITERS" "$msg" "$err" "$MR_SIZE" "$WARMUP"
	echo ""
}

for msg in "${MSG_SIZES[@]}"; do
	for err in "${ERR_PCTS[@]}"; do
		for strat in "${STRATEGIES[@]}"; do
			run_combo "$strat" "$err" "$msg"
		done
	done
done

# Final server shutdown.
ssh "$REMOTE" "pkill -f './server'" 2>/dev/null || true

echo "==================================================================="
echo "Done. CSV : $CSV"
echo "  phase=summary : one row per (strategy,err_pct,msg_size) combo. Holds"
echo "                  normal-WRITE latency (norm_mean/p50/p99_us, norm_count),"
echo "                  total_wall_us, and mean per-error recover/corrupt costs."
echo "  phase=error   : one row per injected violation. Holds detect_us,"
echo "                  recover_us, corrupt_us, sq_psn_delta, landed_bytes,"
echo "                  overrun_truth_bytes, recon_match."
echo "  (No per-normal-WRITE rows; the distribution is in the summary row.)"
echo "Server log: ssh $REMOTE 'cat /tmp/server_ab.log'"
