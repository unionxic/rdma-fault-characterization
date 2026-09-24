#!/usr/bin/env bash
# run_trial_v2.sh - one 2-PE NVSHMEM IBGDA trial with the v2 bundle (PE0 rain = initiator, PE1 sunny
# = target). Derived from ../run_trial.sh; differences: bundle / binary / port are parameters (the
# v1 bundle and its binary name nvft_drv are never touched), the v2 knobs of env_v2.sh are passed
# through, and the faults F2a (--oob <kind>) and F1F2b (F1 hook + corrupted rkeys later) exist.
# Run inside ../../../common/cluster_run.sh. Every process is bounded by `timeout -s KILL`;
# leftovers are reaped by exact binary name of OUR binary only (nvft2_drv / nvft2v1_drv).
#
#   run_trial_v2.sh <fault> <mode> <trial> <outdir>
#     fault: none | F1 | F2b | F3 | F4 | F2a | F1F2b      mode: timeout | blocking
# env: as ../run_trial.sh (FT RECOVER ITERS BYTES GAP_MS DEV_TIMEOUT_MS BURST FAULT_MS SHOTS
#      CORRUPT_AT KILL_AT QDELAY_US SENTINEL LAT LAT_REPS FORCE_AT PROC_TIMEOUT TAG), plus
#      BUNDLE (~/gi-bundle/nvshmem_ft2)  BIN (nvft2_drv)  PORT (18327)
#      RING BOUNDS SKIP CQ_COLLAPSED     (see env_v2.sh)
#      OOB (exact)  F2a kind: exact | gap | straddle | tail | heap (driver --oob)
#      XARGS ("")   extra driver arguments for both ranks
#      MT MT_REPS   --mt T --mt-reps R (fault-free concurrent waiters, see nvshmem_ft_v2.cu)
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
. "$HERE/env_v2.sh"

FAULT=$1; MODE=$2; TRIAL=$3; OUTDIR=$4
mkdir -p "$OUTDIR"
RAIN_MGMT=192.0.2.193
SUNNY_SSH=unionxic@192.0.2.194
BIN=${BIN:-nvft2_drv}
case "$BIN" in nvft2_drv|nvft2v1_drv) ;; *) echo "refusing binary name $BIN" >&2; exit 2 ;; esac
LBIN=$BUNDLE/bin/$BIN
RBIN=$(echo "$BUNDLE" | sed "s#^$HOME#\$HOME#")/bin/$BIN   # same path on sunny
PORT=${PORT:-18327}
ITERS=${ITERS:-200}; BYTES=${BYTES:-262144}; GAP_MS=${GAP_MS:-15}; DEV_TIMEOUT_MS=${DEV_TIMEOUT_MS:-10000}
BURST=${BURST:-1}; FAULT_MS=${FAULT_MS:-800}; SHOTS=${SHOTS:-}; CORRUPT_AT=${CORRUPT_AT:-4}
KILL_AT=${KILL_AT:-3}; PROC_TIMEOUT=${PROC_TIMEOUT:-120}
RECOVER=${RECOVER:-0}; export FT=${FT:-1}

tag="${FAULT}_${MODE}_ft${FT}_rec${RECOVER}${TAG:+_$TAG}_t${TRIAL}"
L0="$OUTDIR/${tag}.pe0.log"; L1="$OUTDIR/${tag}.pe1.log"; META="$OUTDIR/${tag}.meta"
rm -f "$L0" "$L1" "$META"

ARGS="--iters $ITERS --bytes $BYTES --gap-ms $GAP_MS --dev-timeout-ms $DEV_TIMEOUT_MS --burst $BURST"
[ "$RECOVER" = 1 ] && ARGS="$ARGS --recover"
[ -n "${QDELAY_US:-}" ] && ARGS="$ARGS --quiet-delay-us $QDELAY_US"
[ -n "${SENTINEL:-}" ] && ARGS="$ARGS --sentinel $SENTINEL"
[ -n "${LAT:-}" ] && ARGS="$ARGS --lat $LAT --lat-reps ${LAT_REPS:-1}"
[ -n "${FORCE_AT:-}" ] && ARGS="$ARGS --force-rec-at $FORCE_AT"
[ -n "${XARGS:-}" ] && ARGS="$ARGS $XARGS"
[ -n "${MT:-}" ] && ARGS="$ARGS --mt $MT --mt-reps ${MT_REPS:-4}"
ARGS0="$ARGS"; ARGS1="$ARGS"
INJ0=""; INJ1=""; KILL1=0
case "$FAULT" in
  none) ;;
  F1) INJ0="NVSHMEM_IBGDA_FAULT_INJECT=local_err:${FAULT_MS}${SHOTS}" ;;
  F2b) ARGS0="$ARGS0 --corrupt-rkey $CORRUPT_AT" ;;
  F2a) ARGS0="$ARGS0 --oob ${OOB:-exact} --oob-at $CORRUPT_AT"; ARGS1="$ARGS1 --oob ${OOB:-exact} --oob-at $CORRUPT_AT" ;;
  F1F2b) INJ0="NVSHMEM_IBGDA_FAULT_INJECT=local_err:${FAULT_MS}${SHOTS}"; ARGS0="$ARGS0 --corrupt-rkey $CORRUPT_AT" ;;
  F3) INJ1="NVSHMEM_IBGDA_FAULT_INJECT=peer_err:${FAULT_MS}${SHOTS}" ;;
  F4) KILL1=1 ;;
  *) echo "unknown fault $FAULT" >&2; exit 2 ;;
esac

{
  echo "tag=$tag fault=$FAULT mode=$MODE trial=$TRIAL ft=$FT recover=$RECOVER iters=$ITERS bytes=$BYTES"
  echo "burst=$BURST fault_ms=$FAULT_MS shots=$SHOTS corrupt_at=$CORRUPT_AT kill_at=$KILL_AT qdelay_us=${QDELAY_US:-} sentinel=${SENTINEL:-} lat=${LAT:-}"
  echo "ring=${RING:-} bounds=${BOUNDS:-} guard=${GUARD:-} skip=${SKIP:-} cq_collapsed=${CQ_COLLAPSED:-} oob=${OOB:-} xargs=\"${XARGS:-}\" mt=${MT:-} mt_reps=${MT_REPS:-}"
  echo "ft_capture=${FT_CAPTURE:-} ib_timeout=${NVSHMEM_IB_TIMEOUT:-14} bundle=$BUNDLE bin=$BIN start=$(date '+%F %T')"
  echo "md5_rain=$(md5sum < $LBIN | cut -c1-12) lib_rain=$(md5sum < $BUNDLE/lib/nvshmem_transport_ibgda.so.7.0.0 | cut -c1-12) host_rain=$(md5sum < $BUNDLE/lib/libnvshmem_host.so.3.9.0 | cut -c1-12)"
} > "$META"

pkill -x "$BIN" 2>/dev/null
ssh -n -o ConnectTimeout=5 "$SUNNY_SSH" "pkill -x $BIN 2>/dev/null; true"

LIMITS="NVFT_ACK_LIMIT_S=${NVFT_ACK_LIMIT_S:-60} NVFT_RX_LIMIT_S=${NVFT_RX_LIMIT_S:-120} NVFT_TEARDOWN_S=${NVFT_TEARDOWN_S:-60} NVFT_INIT_DIAG_S=${NVFT_INIT_DIAG_S:-0}"
REMOTE_ENV="$(node_env sunny); export $LIMITS"
ssh -n -o ConnectTimeout=8 "$SUNNY_SSH" \
  "$REMOTE_ENV; ${INJ1:+export $INJ1;} exec timeout -s KILL $PROC_TIMEOUT $RBIN 1 $RAIN_MGMT $PORT $MODE $ARGS1" \
  >"$L1" 2>&1 &
SSH_PID=$!

(
  eval "$(node_env rain)"
  ${INJ0:+export $INJ0}
  # shellcheck disable=SC2086
  export $LIMITS
  # shellcheck disable=SC2086
  exec timeout -s KILL "$PROC_TIMEOUT" "$LBIN" 0 "$RAIN_MGMT" "$PORT" "$MODE" $ARGS0
) >"$L0" 2>&1 &
PE0_PID=$!

if [ "$KILL1" = 1 ]; then
  for i in $(seq 1 600); do
    grep -q "^ITER $KILL_AT rank 0" "$L0" 2>/dev/null && break
    kill -0 "$PE0_PID" 2>/dev/null || break
    sleep 0.05
  done
  KT=$(ssh -n -o ConnectTimeout=5 "$SUNNY_SSH" "python3 -c 'import time,subprocess; t=time.clock_gettime(time.CLOCK_MONOTONIC); subprocess.run([\"pkill\",\"-9\",\"-x\",\"$BIN\"]); print(\"%.6f\" % t)'" 2>/dev/null)
  echo "kill_mono1_s=$KT" >> "$META"
  echo "[runner] F4: SIGKILL PE1 at sunny mono_s=$KT" >> "$L0"
fi
wait "$PE0_PID"; PE0_RC=$?
wait "$SSH_PID"; PE1_RC=$?
pkill -x "$BIN" 2>/dev/null
LEFT0=$(pgrep -x "$BIN" | wc -l)
LEFT1=$(ssh -n -o ConnectTimeout=5 "$SUNNY_SSH" "pkill -x $BIN 2>/dev/null; sleep 0.2; pgrep -x $BIN | wc -l")
echo "pe0_rc=$PE0_RC pe1_rc=$PE1_RC leftover_rain=$LEFT0 leftover_sunny=$LEFT1 end=$(date '+%F %T')" >> "$META"
echo "$tag pe0_rc=$PE0_RC pe1_rc=$PE1_RC $(grep -h '^SUMMARY' "$L0" "$L1" | tr '\n' ' ')"
