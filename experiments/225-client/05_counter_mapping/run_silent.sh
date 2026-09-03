#!/bin/bash
# run_silent.sh — Compare three ways to make a SILENT (timeout/peer-death)
# partial RDMA WRITE safe for a consumer, and their costs.
#
#   C0 baseline    : plain WRITE (comparison baseline; normal path only)
#   C1 commit-flag : payload WRITE(unsignaled) + 8B flag WRITE(signaled), same QP
#   C2 crc32c      : 16B header + payload in one WRITE; server recomputes crc
#   C3 read-back   : plain WRITE; after the fault, RDMA READ back + diff + resend
#                    ONLY the missing tail (partial resend)
#
# Two measurement matrices:
#   (1) normal path : C0/C1/C2/C3 x msg {4KB,64KB,1MB,4MB} x N=NORMAL_ITERS
#                     -> mean/p50/p99 latency (phase=normal rows).
#   (2) error path  : C1/C2/C3 x 4MB x N=ERR_TRIALS, responder QP->ERR mid-write
#                     -> per-trial outcome/judging/recovery (phase=error rows)
#                        + one phase=summary row per strategy.
#
# Run from client (225). Server (224) reached over SSH and (re)started here. The
# control TCP socket lives for one client process = one combo; each combo gets a
# fresh server (client sends SHUTDOWN at the end).
#
# Usage: ./run_silent.sh [normal_iters] [err_trials] [settle_ms]
#   normal_iters : measured normal-path iters per combo (default 1000, warmup 100)
#   err_trials   : fault-injection trials per strategy   (default 100)
#   settle_ms    : post_send -> local QP->ERR delay, ms  (default 80)

set -e

REMOTE="gustlr@SERVER_224_ADDR"
REMOTE_DIR="/home/gustlr/Desktop/gpu_fault_recovery/05_counter_mapping"

NORMAL_ITERS=${1:-1000}
ERR_TRIALS=${2:-100}
SETTLE_MS=${3:-80}

NORMAL_STRATS=(C0 C1 C2 C3)
ERROR_STRATS=(C1 C2 C3)
MSG_SIZES=(4096 65536 1048576 4194304)   # 4KB 64KB 1MB 4MB

CSV="results/raw/silent_strategy.csv"
HEADER="strategy,phase,msg_size,iter,outcome,ground_truth_bytes,judged_valid,judge_correct,detect_us,recover_us,judge_us,resend_bytes,resend_us,total_us,norm_mean_us,norm_p50_us,norm_p99_us,norm_count"

echo "=== silent partial-write strategy comparison (C0/C1/C2/C3) ==="
echo "normal iters/combo : $NORMAL_ITERS (warmup 100)"
echo "error trials/strat : $ERR_TRIALS   settle: ${SETTLE_MS}ms"
echo "normal msg sizes   : ${MSG_SIZES[*]} (PMTU=1024)"
echo ""

# Clean any stale server, rebuild both sides.
ssh "$REMOTE" "pkill -f './server'" 2>/dev/null || true
sleep 1

echo "[build] Compiling on 224 (server, -msse4.2 for hardware CRC32C)..."
ssh "$REMOTE" "cd $REMOTE_DIR && make server"
echo "[build] Compiling locally (client)..."
make silent_strategy

mkdir -p results/raw

# Fresh CSV with header (client appends).
echo "$HEADER" > "$CSV"

# Restart the server, then run one client invocation (one combo).
run_combo() {
	echo "[orchestrator] (re)starting server on 224..."
	ssh "$REMOTE" "pkill -f './server'" 2>/dev/null || true
	sleep 1
	ssh -f "$REMOTE" "cd $REMOTE_DIR && nohup ./server > /tmp/server_silent.log 2>&1 < /dev/null & exit"
	sleep 1
	echo "[run] ./silent_strategy $*"
	./silent_strategy "$@"
	echo ""
}

echo "----- matrix 1: normal path (overhead) -----"
for strat in "${NORMAL_STRATS[@]}"; do
	for msg in "${MSG_SIZES[@]}"; do
		run_combo "$strat" normal "$msg" "$NORMAL_ITERS"
	done
done

echo "----- matrix 2: error path (silent partial, judging + recovery) -----"
for strat in "${ERROR_STRATS[@]}"; do
	run_combo "$strat" error 4194304 "$ERR_TRIALS" "$SETTLE_MS"
done

# Final server shutdown.
ssh "$REMOTE" "pkill -f './server'" 2>/dev/null || true

echo "==================================================================="
echo "Done. CSV : $CSV"
echo "  phase=normal  : one row per (strategy,msg_size). norm_mean/p50/p99_us,"
echo "                  norm_count = normal-path WRITE latency distribution."
echo "  phase=error   : one row per fault trial. outcome (FULL/PARTIAL/NO_WRITE),"
echo "                  ground_truth_bytes, judged_valid, judge_correct, detect_us,"
echo "                  recover_us, judge_us, resend_bytes, resend_us, total_us."
echo "  phase=summary : one row per error strategy. means in the cost columns;"
echo "                  judged_valid/judge_correct = counts; norm_count = #trials;"
echo "                  outcome = P<partial>_F<full>_N<nowrite>."
echo "Analysis: focus on the PARTIAL subset. C3's mean resend_bytes vs 4MB gives"
echo "          the partial-resend saving."
echo "Server log: ssh $REMOTE 'cat /tmp/server_silent.log'"
