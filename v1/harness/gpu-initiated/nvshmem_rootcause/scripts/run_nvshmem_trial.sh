#!/usr/bin/env bash
# run_nvshmem_trial.sh - one 2-PE NVSHMEM IBGDA trial with the nrc knob, run inside
# ../../common/cluster_run.sh. Adapted from ../../nvshmem/run_trial.sh (same driver binary,
# same env_common.sh, same fault hooks); differences:
#   * LD_LIBRARY_PATH points at the bundle with the nrc transport plugin
#     (BUNDLE, default ~/gi-bundle/nvshmem_nrc, built from nvshmem_nrc_proxy_sq_dbr.diff);
#   * FIX=0|1 sets NVSHMEM_IBGDA_PROXY_SQ_DBR on BOTH PEs (default 0 = stock proxy);
#   * the QP watch always runs on PE0 in query-only mode (QUERY_QP + doorbell-record words);
#   * HOLD=1 reproduces the base diff's watch (lock held across its sleep, starving the proxy);
#     WATCH_MS=0 turns the watch off;
#   * samples rain's port counters every 0.5 s into <tag>.cnt;
#   * emits one KV line instead of the Q2 CSV row.
#
#   run_nvshmem_trial.sh <fault> <wait_mode> <trial> <outdir>
#     fault: none | F1 | F2b | F3 | F4     wait_mode: timeout | blocking
# HANDLER=auto|gpu|cpu_host_memory sets NVSHMEM_IBGDA_NIC_HANDLER on both PEs (after
# env_common.sh, which hard-codes auto). F4 SIGKILLs PE1 (exact binary name on sunny) once PE0
# has logged iteration 2.
# env: FIX (0), NVSHMEM_IB_TIMEOUT (14), FAULT_MS (1500), ITERS (8), DEV_TIMEOUT_MS (10000),
#      WATCH_MS (100), PROC_TIMEOUT (60), NVSHMEM_FAULT_WATCHDOG_S (40), CORRUPT_AT (4)
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
NV="$HERE/../../nvshmem"
export BUNDLE=${BUNDLE:-$HOME/gi-bundle/nvshmem_nrc}
. "$NV/env_common.sh"

FAULT=$1; WAIT=$2; TRIAL=$3; OUTDIR=$4
mkdir -p "$OUTDIR"
FIX=${FIX:-0}
RAIN_MGMT=192.0.2.193
SUNNY_SSH=unionxic@192.0.2.194
BIN=nvshmem_fault
LBIN="$NV/$BIN"
RBIN=$HOME/gi-bundle/nvshmem/bin/$BIN
PORT=${PORT:-18215}
ITERS=${ITERS:-8}; MSG=${MSG:-262144}; CADENCE_MS=${CADENCE_MS:-250}
DEV_TIMEOUT_MS=${DEV_TIMEOUT_MS:-10000}; FAULT_MS=${FAULT_MS:-1500}
PROC_TIMEOUT=${PROC_TIMEOUT:-60}; WATCH_MS=${WATCH_MS:-100}
export NVSHMEM_FAULT_WATCHDOG_S=${NVSHMEM_FAULT_WATCHDOG_S:-40}
CORRUPT_AT=${CORRUPT_AT:-4}

HOLDTAG=""; [ "${HOLD:-0}" = 1 ] && HOLDTAG="_hold"
[ "${WATCH_MS:-100}" = 0 ] && HOLDTAG="${HOLDTAG}_nowatch"
tag="${FAULT}_${WAIT}_${HANDLER}_fix${FIX}${HOLDTAG}_t${TRIAL}"
L0="$OUTDIR/${tag}.pe0.log"; L1="$OUTDIR/${tag}.pe1.log"
rm -f "$L0" "$L1"

INJ0=""; INJ1=""; EXTRA0=""; KILL1=0
HANDLER=${HANDLER:-auto}
case "$FAULT" in
  none) ;;
  F1) INJ0="NVSHMEM_IBGDA_FAULT_INJECT=local_err:$FAULT_MS" ;;
  F2b) EXTRA0="--corrupt-rkey $CORRUPT_AT" ;;
  F3) INJ1="NVSHMEM_IBGDA_FAULT_INJECT=peer_err:$FAULT_MS" ;;
  F4) KILL1=1 ;;
  *) echo "unknown fault $FAULT" >&2; exit 2 ;;
esac
FIXENV="NVSHMEM_IBGDA_PROXY_SQ_DBR=$FIX NVSHMEM_IBGDA_NIC_HANDLER=$HANDLER"
HOLD=${HOLD:-0}   # 1 = watch holds rc_endpoint_lock across its sleep (the base diff's behaviour)
WATCHENV="NVSHMEM_IBGDA_FAULT_WATCH_HOLD_LOCK=$HOLD"
[ "$WATCH_MS" != 0 ] && WATCHENV="$WATCHENV NVSHMEM_IBGDA_FAULT_WATCH=$WATCH_MS NVSHMEM_IBGDA_FAULT_WATCH_QPONLY=1 NVSHMEM_IBGDA_FAULT_WATCH_DELAY_MS=${WATCH_DELAY_MS:-0}"

pkill -x "$BIN" 2>/dev/null
ssh -n -o ConnectTimeout=5 "$SUNNY_SSH" "pkill -x $BIN 2>/dev/null; true"

# rain port counters every 0.5 s for the whole trial (as ../../../scratch gi/diag_f3.sh)
PC=/sys/class/infiniband/mlx5_1/ports/1/counters
CNT="$OUTDIR/${tag}.cnt"; rm -f "$CNT" "$CNT.stop"
( echo "t_ms xmit_pkts rcv_pkts"; t0=$(date +%s%N)
  while [ ! -f "$CNT.stop" ] && [ $(( ($(date +%s%N) - t0) / 1000000000 )) -lt $((PROC_TIMEOUT + 5)) ]; do
    echo "$(( ($(date +%s%N) - t0) / 1000000 )) $(cat $PC/port_xmit_packets) $(cat $PC/port_rcv_packets)"; sleep 0.5; done ) > "$CNT" &
SAMPLER=$!

REMOTE_ENV="$(node_env sunny)"
ssh -n -o ConnectTimeout=8 "$SUNNY_SSH" \
  "$REMOTE_ENV; export NVSHMEM_FAULT_WATCHDOG_S=$NVSHMEM_FAULT_WATCHDOG_S $FIXENV ${INJ1}; exec timeout -s KILL $PROC_TIMEOUT $RBIN 1 $RAIN_MGMT $PORT $WAIT $ITERS $MSG $CADENCE_MS $DEV_TIMEOUT_MS" \
  >"$L1" 2>&1 &
SSH_PID=$!

(
  eval "$(node_env rain)"
  # shellcheck disable=SC2086
  export $FIXENV $WATCHENV ${INJ0}
  # shellcheck disable=SC2086
  exec timeout -s KILL "$PROC_TIMEOUT" "$LBIN" 0 "$RAIN_MGMT" "$PORT" "$WAIT" "$ITERS" "$MSG" "$CADENCE_MS" "$DEV_TIMEOUT_MS" $EXTRA0
) >"$L0" 2>&1 &
PE0_PID=$!

KILL_AT=""
if [ "$KILL1" = 1 ]; then
  for i in $(seq 1 300); do   # up to 30 s for PE0 to finish iteration 2
    grep -q "^ITER 2 rank 0" "$L0" 2>/dev/null && break
    kill -0 "$PE0_PID" 2>/dev/null || break
    sleep 0.1
  done
  KILL_AT=$(date +%s.%N)
  ssh -n -o ConnectTimeout=5 "$SUNNY_SSH" "pkill -9 -x $BIN" 2>/dev/null
  echo "[runner] F4: SIGKILL PE1 at $KILL_AT" >> "$L0"
fi
wait "$PE0_PID"; PE0_RC=$?
wait "$SSH_PID"; PE1_RC=$?
touch "$CNT.stop"; wait "$SAMPLER"; rm -f "$CNT.stop"
pkill -x "$BIN" 2>/dev/null
ssh -n -o ConnectTimeout=5 "$SUNNY_SSH" "pkill -x $BIN 2>/dev/null; true"

getf() { echo "$1" | grep -oE "$2=[^ ]+" | head -1 | cut -d= -f2; }
BACKEND=$(grep -m1 "NIC handler will be" "$L0" | sed -E 's/.*will be //; s/\.$//; s/ /_/g')
FAILLINE=$(grep "^ITER .* rank 0 " "$L0" | awk '/wait_rc=[12]|CUDAERR/{print; exit}')
[ -z "$FAILLINE" ] && FAILLINE=$(grep "^ITER .* rank 0 " "$L0" | tail -1)
IT=$(echo "$FAILLINE" | awk '{print $2}')
SCAN=$(grep "^SCAN iter ${IT:-x} rank 0 rc_ncqes" "$L0" | head -1)
ERRCQE=$(grep -m1 "^SCAN iter .* ERRCQE" "$L0" | cut -d' ' -f5-)
OKITERS=$(grep -c "^ITER .* rank 0 .*wait_rc=0" "$L0")
# first RC QUERY_QP with state 6, and the last DBR words the watch printed
QPERR=$(grep -m1 "fault-watch.* RC .*state=6" "$L0" | awk '{print $2}')
QPLAST=$(grep "fault-watch.* RC .*QUERY_QP" "$L0" | tail -1 | grep -oE "state=[0-9]+ hw_sq_wqebb=[0-9]+ sw_sq_wqebb=[0-9]+ cur_retry=[0-9]+" | tr ' ' ';')
DBRLAST=$(grep "nvshmem-nrc.*DBR" "$L0" | tail -1 | grep -oE "word0\(rq\)=[0-9]+ word1\(sq\)=[0-9]+" | tr ' ' ';')
FIXMSG=$(grep -c "CPU proxy writes the SQ doorbell record" "$L0")
FINALDBR=$(grep -m1 "nvshmem-nrc\] final RC" "$L0" | grep -oE "DBR\([a-z]+\) ok=[0-9] word0\(rq\)=[0-9]+ word1\(sq\)=[0-9]+" | tr ' ' ';')
BLK_LAST=$(grep "^ITER .* rank 0 wait=blocking" "$L0" | tail -1 | awk '{print $2}')
QPSEQ=$(grep "fault-watch.* RC .*QUERY_QP" "$L0" | awk '{print $2"ms:"$8","$9","$10}' | awk -F: '{k=$2; if (k!=prev) {printf "%s ", $0; prev=k}}' | sed 's/state=//g; s/hw_sq_wqebb=//g; s/sw_sq_wqebb=//g' | tr ' ' '|')
XMIT=$(awk 'NR==2{x0=$2} NR>2 && $2!=px {last=$1} {px=$2} END{print "xmit_total="$2-x0";t_last_xmit_change_ms="last}' "$CNT" 2>/dev/null)
FIRE=$(grep -m1 "moved .* QP(s) to ERR" "$L0" "$L1" | head -1 | sed 's/.*moved/moved/')
echo "trial=$tag backend=$BACKEND fix=$FIX fix_msg=$FIXMSG ok_iters=$OKITERS fail_iter=${IT:-na} wait_rc=$(getf "$FAILLINE" wait_rc) dt_ms=$(getf "$FAILLINE" dt_ms) cqe_opcode=$(getf "$FAILLINE" cqe_opcode) cqe_syndrome=$(getf "$FAILLINE" cqe_syndrome) cqe_vendor_err=$(getf "$FAILLINE" cqe_vendor_err) cqe_wqe=$(getf "$FAILLINE" cqe_wqe_counter) ready_head=$(getf "$FAILLINE" ready_head) scan_errs=$(getf "$SCAN" errs) scan_rc_hist=$(echo "$SCAN" | grep -oE 'rc_hist\{[^}]*\}' | tr ' ' '_') errcqe=\"${ERRCQE}\" watch_first_rc_err_ms=${QPERR:-none} watch_rc_last=${QPLAST:-na} dbr_last=${DBRLAST:-na} dbr_final=${FINALDBR:-na} blocking_last_iter=${BLK_LAST:-na} handler_req=$HANDLER qp_seq=${QPSEQ:-na} $XMIT hold=$HOLD fault_fire=\"${FIRE}\" pe0_rc=$PE0_RC pe1_rc=$PE1_RC"
