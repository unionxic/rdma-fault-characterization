#!/usr/bin/env bash
# run_trial.sh - run ONE 2-PE IBGDA trial and emit one CSV row on stdout.
# PE0 (initiator) runs locally on rain; PE1 (target) runs on sunny over ssh.
# Every process is bounded by `timeout`; leftover processes are reaped by exact
# binary name afterwards. This script is meant to be called from inside
# cluster_run.sh (which holds the cluster lock and waits for an idle link).
#
#   run_trial.sh <fault> <wait_mode> <trial> <outdir>
#     fault     : none | F1 | F2 | F3 | F4
#     wait_mode : timeout | blocking | deepep_poll
# Env knobs: NVSHMEM_IB_TIMEOUT (default 14), FAULT_MS (default 1500),
#            ITERS (8), MSG (262144), CADENCE_MS (250), DEV_TIMEOUT_MS (5000).
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
. "$HERE/env_common.sh"

FAULT="$1"; WAIT="$2"; TRIAL="$3"; OUTDIR="$4"
mkdir -p "$OUTDIR"

RAIN_MGMT=192.0.2.193
SUNNY_SSH=unionxic@192.0.2.194
BIN=nvshmem_fault
RBIN=$HOME/gi-bundle/nvshmem/bin/$BIN
PORT=${PORT:-18215}
ITERS=${ITERS:-8}; MSG=${MSG:-262144}; CADENCE_MS=${CADENCE_MS:-250}
DEV_TIMEOUT_MS=${DEV_TIMEOUT_MS:-5000}; FAULT_MS=${FAULT_MS:-1500}
PROC_TIMEOUT=${PROC_TIMEOUT:-60}; BURST=${BURST:-1}
BURSTARG=""; [ "$BURST" != 1 ] && BURSTARG="--burst $BURST"
PREFAULTARG=""; [ -n "${PREFAULT_MS:-}" ] && PREFAULTARG="--prefault-ms $PREFAULT_MS"

tag="${FAULT}_${WAIT}_t${TRIAL}"
L0="$OUTDIR/${tag}.pe0.log"; L1="$OUTDIR/${tag}.pe1.log"
rm -f "$L0" "$L1"

# --- per-fault environment / extra args ---
OOB=""; INJ0=""; INJ1=""; KILL1=0; EXTRA0=""
CORRUPT_AT=${CORRUPT_AT:-4}
case "$FAULT" in
  none) ;;
  F1) INJ0="NVSHMEM_IBGDA_FAULT_INJECT=local_err:$FAULT_MS" ;;
  F2|F2a) OOB="--oob" ;;                                   # oob within MR: silent corruption
  F2b) EXTRA0="--corrupt-rkey $CORRUPT_AT" ;;              # invalid rkey -> responder NAK
  F3) INJ1="NVSHMEM_IBGDA_FAULT_INJECT=peer_err:$FAULT_MS" ;;
  F4) KILL1=1 ;;
  *) echo "unknown fault $FAULT" >&2; exit 2 ;;
esac
# NVSHMEM_IBGDA_FAULT_WATCH diagnostic (default off) runs on the initiator (PE0).
[ -n "${WATCH_MS:-}" ] && INJ0="${INJ0:+$INJ0 }NVSHMEM_IBGDA_FAULT_WATCH=$WATCH_MS"
[ -n "${WATCH_DELAY_MS:-}" ] && INJ0="${INJ0:+$INJ0 }NVSHMEM_IBGDA_FAULT_WATCH_DELAY_MS=$WATCH_DELAY_MS"
[ -n "${WATCH_QPONLY:-}" ] && INJ0="${INJ0:+$INJ0 }NVSHMEM_IBGDA_FAULT_WATCH_QPONLY=$WATCH_QPONLY"

# reap any stragglers of OURS (exact name) before starting
pkill -x "$BIN" 2>/dev/null
ssh -n -o ConnectTimeout=5 "$SUNNY_SSH" "pkill -x $BIN 2>/dev/null; true"

# --- launch PE1 (sunny) in background over ssh ---
REMOTE_ENV="$(node_env sunny)"
ssh -n -o ConnectTimeout=8 "$SUNNY_SSH" \
  "$REMOTE_ENV; ${INJ1:+export $INJ1;} exec timeout -s KILL $PROC_TIMEOUT $RBIN 1 $RAIN_MGMT $PORT $WAIT $ITERS $MSG $CADENCE_MS $DEV_TIMEOUT_MS $OOB $BURSTARG" \
  >"$L1" 2>&1 &
SSH_PID=$!

# --- launch PE0 (rain) in background locally ---
(
  eval "$(node_env rain)"
  ${INJ0:+export $INJ0}
  exec timeout -s KILL "$PROC_TIMEOUT" "$HERE/$BIN" 0 "$RAIN_MGMT" "$PORT" "$WAIT" "$ITERS" "$MSG" "$CADENCE_MS" "$DEV_TIMEOUT_MS" $OOB $BURSTARG $EXTRA0 $PREFAULTARG
) >"$L0" 2>&1 &
PE0_PID=$!

# --- F4: SIGKILL PE1 mid-run (by exact binary name on sunny = ours only) ---
if [ "$KILL1" = 1 ]; then
  ( sleep $(awk "BEGIN{print $FAULT_MS/1000.0}")
    ssh -n -o ConnectTimeout=5 "$SUNNY_SSH" "pkill -9 -x $BIN" 2>/dev/null ) &
fi

wait "$PE0_PID"; PE0_RC=$?
wait "$SSH_PID"; PE1_RC=$?

# final reap
pkill -x "$BIN" 2>/dev/null
ssh -n -o ConnectTimeout=5 "$SUNNY_SSH" "pkill -x $BIN 2>/dev/null; true"

# --- parse logs into one CSV row ---
BACKEND=$(grep -m1 "NIC handler will be" "$L0" 2>/dev/null | sed -E 's/.*will be //; s/\.$//; s/ /_/g')
[ -z "$BACKEND" ] && BACKEND="unknown"

# PE0: first failing ITER line (wait_rc 1 or 2), else last ITER line.
# Anchor on "^ITER " so the "SUMMARY rank 0" line is never matched.
FAILLINE=$(grep "^ITER .* rank 0 " "$L0" | awk '/wait_rc=1|wait_rc=2/{print; exit}')
[ -z "$FAILLINE" ] && FAILLINE=$(grep "^ITER .* rank 0 " "$L0" | tail -1)
IT_OK=$(grep -c "^ITER .* rank 0 .*wait_rc=0" "$L0")

getf(){ echo "$1" | grep -oE "$2=[^ ]+" | head -1 | cut -d= -f2; }
WRC=$(getf "$FAILLINE" wait_rc); [ -z "$WRC" ] && WRC="na"
OPC=$(getf "$FAILLINE" cqe_opcode); SYN=$(getf "$FAILLINE" cqe_syndrome)
VEN=$(getf "$FAILLINE" cqe_vendor_err); WQC=$(getf "$FAILLINE" cqe_wqe_counter)
HMS=$(getf "$FAILLINE" dt_ms)
[ -z "$OPC" ] && OPC="na"; [ -z "$SYN" ] && SYN="na"; [ -z "$VEN" ] && VEN="na"
[ -z "$WQC" ] && WQC="na"; [ -z "$HMS" ] && HMS="na"

# PE1: failing data_check line, else last
P1LINE=$(grep "^ITER .* rank 1 " "$L1" | awk '/data_check=missing|data_check=mismatch/{print; exit}')
[ -z "$P1LINE" ] && P1LINE=$(grep "^ITER .* rank 1 " "$L1" | tail -1)
DATACHK=$(getf "$P1LINE" data_check); [ -z "$DATACHK" ] && DATACHK="n/a"

# outcomes
case "$WRC" in
  0) INIT_OUT="ok" ;;
  1) INIT_OUT="timeout" ;;
  2) INIT_OUT="error" ;;
  *) INIT_OUT="unknown" ;;
esac
[ "$PE0_RC" = 137 ] && INIT_OUT="hang_killed"        # SIGKILL by timeout
[ "$PE0_RC" = 7 ] && INIT_OUT="hang_killed"          # our watchdog

if [ "$FAULT" = F4 ]; then TARGET_OUT="killed"
elif grep -q "data_check=missing" "$L1"; then TARGET_OUT="timeout"
elif [ "$PE1_RC" = 137 ]; then TARGET_OUT="hang_killed"
else TARGET_OUT="ok"; fi

# silent success: initiator said ok (wait_rc=0) but data did not arrive intact
SILENT=0
if [ "$WRC" = 0 ] && { [ "$DATACHK" = missing ] || [ "$DATACHK" = mismatch ]; }; then SILENT=1; fi

# map syndrome -> ibv_wc_status (rdma-core providers/mlx5/cq.c) when opcode==REQ_ERR(0xd)
STATUS="n/a"
if [ "$OPC" = "0xd" ] || [ "$OPC" = "0xD" ]; then
  case "$SYN" in
    0x01) STATUS=LOC_LEN ;; 0x02) STATUS=LOC_QP_OP ;; 0x04) STATUS=LOC_PROT ;;
    0x05) STATUS=WR_FLUSH ;; 0x06) STATUS=MW_BIND ;; 0x10) STATUS=BAD_RESP ;;
    0x11) STATUS=LOC_ACCESS ;; 0x12) STATUS=REM_INV_REQ ;; 0x13) STATUS=REM_ACCESS ;;
    0x14) STATUS=REM_OP ;; 0x15) STATUS=RETRY_EXC ;; 0x16) STATUS=RNR_RETRY_EXC ;;
    0x22) STATUS=REM_ABORT ;; *) STATUS="GENERAL(${SYN})" ;;
  esac
fi

FP_WHERE="cqe"; [ "$OPC" = na ] && FP_WHERE="none"
HOST_ERR="exit${PE0_RC}"
# teardown: exit 7 means finalize/kernel watchdog fired
TEARDOWN="clean"; { [ "$PE0_RC" = 7 ] || [ "$PE1_RC" = 7 ]; } && TEARDOWN="hang"
NOTES="pe0_rc=${PE0_RC};pe1_rc=${PE1_RC}"

echo "nvshmem-ibgda,$BACKEND,$FAULT,$WAIT,$TRIAL,$IT_OK,$INIT_OUT,$TARGET_OUT,$DATACHK,$SILENT,$HOST_ERR,$HMS,$FP_WHERE,$STATUS,$VEN,$TEARDOWN,$NOTES,$OPC,$SYN,$VEN,$WQC"
