#!/usr/bin/env bash
# run_trial.sh - one 2-PE NVSHMEM IBGDA FT trial (PE0 rain = initiator, PE1 sunny = target).
# Run inside ../../common/cluster_run.sh (lock + idle link). Every process is bounded by
# `timeout -s KILL`; leftovers are reaped by exact binary name (nvft_drv, ours only).
#
#   run_trial.sh <fault> <mode> <trial> <outdir>
#     fault: none | F1 | F2b | F3 | F4        mode: timeout | blocking
# env: FT (1)          NVSHMEM_IBGDA_FT on both PEs
#      RECOVER (0)     1 = run the recovery protocol (--recover)
#      ITERS (200) BYTES (262144) GAP_MS (15) DEV_TIMEOUT_MS (10000) BURST (1)
#      FAULT_MS (800) SHOTS ("")  extra shots for F1/F3, e.g. ",20,20,-1,20" (see the hook)
#      CORRUPT_AT (4)  F2b iteration       KILL_AT (3) F4: SIGKILL PE1 after PE0 logged this ITER
#      QDELAY_US (0)   --quiet-delay-us    SENTINEL ("") --sentinel <poll_ns>
#      LAT ("") LAT_REPS (1)  latency mode (no fault)
#      FORCE_AT ("")   --force-rec-at: forced recovery after a completed operation (d = 0 branch)
#      FT_CAPTURE (""), FT_POLL_US (50), NVSHMEM_IB_TIMEOUT (14), PROC_TIMEOUT (120), PORT (18317)
#      TAG (extra tag suffix)
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
. "$HERE/env_ft.sh"

FAULT=$1; MODE=$2; TRIAL=$3; OUTDIR=$4
mkdir -p "$OUTDIR"
RAIN_MGMT=192.0.2.193
SUNNY_SSH=unionxic@192.0.2.194
BIN=nvft_drv
LBIN=$HOME/gi-bundle/nvshmem_ft/bin/$BIN
RBIN=$HOME/gi-bundle/nvshmem_ft/bin/$BIN   # same path on sunny
PORT=${PORT:-18317}
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
ARGS0="$ARGS"; ARGS1="$ARGS"
INJ0=""; INJ1=""; KILL1=0
case "$FAULT" in
  none) ;;
  F1) INJ0="NVSHMEM_IBGDA_FAULT_INJECT=local_err:${FAULT_MS}${SHOTS}" ;;
  F2b) ARGS0="$ARGS0 --corrupt-rkey $CORRUPT_AT" ;;
  F3) INJ1="NVSHMEM_IBGDA_FAULT_INJECT=peer_err:${FAULT_MS}${SHOTS}" ;;
  F4) KILL1=1 ;;
  *) echo "unknown fault $FAULT" >&2; exit 2 ;;
esac

{
  echo "tag=$tag fault=$FAULT mode=$MODE trial=$TRIAL ft=$FT recover=$RECOVER iters=$ITERS bytes=$BYTES"
  echo "burst=$BURST fault_ms=$FAULT_MS shots=$SHOTS corrupt_at=$CORRUPT_AT kill_at=$KILL_AT qdelay_us=${QDELAY_US:-} sentinel=${SENTINEL:-} lat=${LAT:-}"
  echo "ft_capture=${FT_CAPTURE:-} ib_timeout=${NVSHMEM_IB_TIMEOUT:-14} start=$(date '+%F %T')"
  echo "md5_rain=$(md5sum < $LBIN | cut -c1-12) lib_rain=$(md5sum < $HOME/gi-bundle/nvshmem_ft/lib/nvshmem_transport_ibgda.so.7.0.0 | cut -c1-12)"
} > "$META"

pkill -x "$BIN" 2>/dev/null
ssh -n -o ConnectTimeout=5 "$SUNNY_SSH" "pkill -x $BIN 2>/dev/null; true"

LIMITS="NVFT_ACK_LIMIT_S=${NVFT_ACK_LIMIT_S:-60} NVFT_RX_LIMIT_S=${NVFT_RX_LIMIT_S:-120} NVFT_TEARDOWN_S=${NVFT_TEARDOWN_S:-60}"
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
  # the kill time is taken on sunny (CLOCK_MONOTONIC, s) right before the SIGKILL; rows.py converts
  # it with the drivers' OOB clock offset
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
