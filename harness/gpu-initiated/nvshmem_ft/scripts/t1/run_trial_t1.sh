#!/usr/bin/env bash
# run_trial_t1.sh - one 2-PE trial of the unmodified application nvshmem_t1.cu (PE0 rain puts, PE1
# sunny receives). Run inside ../../../common/cluster_run.sh. Every process is bounded by
# `timeout -s KILL`; leftovers are reaped by exact binary name (nvt1_drv / nvt1v22_drv) only.
#
#   run_trial_t1.sh <fault> <mode> <trial> <outdir>
#     fault: none | F1 | F1x5 | F3 | F2 | F2A | F4 | FLAP    mode: loop | mt | lat
#     (F2: the responder revokes remote access, hook; F2A: the application's own bug, one put past the
#     symmetric heap at iteration BAD_AT)
# env: ITERS BYTES GAP_US CTAS THREADS BURST REPS (driver), FAULT_MS (hook delay after connect; "rand"
#      = uniform in [FAULT_LO, FAULT_HI]), SHOTS (",d2,d3,..." extra F1 shots), KILL_MS (F4: SIGKILL of
#      PE1 this long after PE0 starts its kernel), CUT_S (FLAP: outage seconds), CUT_AT_MS (FLAP: cut
#      this long after PE0 starts its kernel), FETCH=1 (--fetch), PROC_TIMEOUT KTIMEOUT, TAG, BUNDLE
#      BUNDLE_V22 BIN, XENV (one extra VAR=value exported in both processes, e.g.
#      CUDA_DEVICE_MAX_CONNECTIONS=32), SOCK_DIR (both|in), and the knobs
#      of env_t1.sh (FT RING T1 T1SKIP SKIP HOLD_MS ... GID_R GID_S RC_PER_PE RC_MAP); NOFIN=1 (--no-finalize).
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
. "$HERE/env_t1.sh"
FAULT=$1; MODE=$2; TRIAL=$3; OUTDIR=$4
mkdir -p "$OUTDIR"
RAIN_MGMT=192.0.2.193
SUNNY_SSH=unionxic@192.0.2.194
BIN=${BIN:-nvt1_drv}
case "$BIN" in nvt1_drv|nvt1v22_drv) ;; *) echo "refusing binary name $BIN" >&2; exit 2 ;; esac
[ "$BIN" = nvt1v22_drv ] && BUNDLE=${BUNDLE_V22:-$HOME/gi-bundle/nvshmem_t1/v22ref}
LBIN=$BUNDLE/bin/$BIN
RBIN=$(echo "$BUNDLE" | sed "s#^$HOME#\$HOME#")/bin/$BIN
PORT=${PORT:-18411}
GBH=${GBH:-$HERE/../../../../nccl-integration/stage2/gid_blackhole.sh}
ITERS=${ITERS:-160}; BYTES=${BYTES:-262144}; GAP_US=${GAP_US:-15000}
PROC_TIMEOUT=${PROC_TIMEOUT:-150}; KTIMEOUT=${KTIMEOUT:-120}
FAULT_LO=${FAULT_LO:-900}; FAULT_HI=${FAULT_HI:-1900}
FMS=${FAULT_MS:-rand}
[ "$FMS" = rand ] && FMS=$(python3 -c "import random; print(random.randint($FAULT_LO, $FAULT_HI))")
tag="${FAULT}_${MODE}_ft${FT:-1}_t1${T1:-1}${TAG:+_$TAG}_t${TRIAL}"
L0="$OUTDIR/${tag}.pe0.log"; L1="$OUTDIR/${tag}.pe1.log"; META="$OUTDIR/${tag}.meta"
rm -f "$L0" "$L1" "$META"
ARGS="--iters $ITERS --bytes $BYTES --gap-us $GAP_US --kernel-timeout-s $KTIMEOUT"
[ -n "${CTAS:-}" ] && ARGS="$ARGS --ctas $CTAS"
[ -n "${THREADS:-}" ] && ARGS="$ARGS --threads $THREADS"
[ -n "${BURST:-}" ] && ARGS="$ARGS --burst $BURST"
[ -n "${REPS:-}" ] && ARGS="$ARGS --reps $REPS"
[ "${FETCH:-0}" = 1 ] && ARGS="$ARGS --fetch${FETCH_EVERY:+ --fetch-every $FETCH_EVERY}"
[ "${FILL:-0}" != 0 ] && ARGS="$ARGS --fill-sms $FILL"
[ "${NOFIN:-0}" = 1 ] && ARGS="$ARGS --no-finalize"   # t1_close: exit without nvshmem_finalize
INJ0=""; INJ1=""
case "$FAULT" in
  none|F4|FLAP|SOCK) ;;
  SOCK1) INJ0="NVSHMEM_IBGDA_FAULT_INJECT=local_err:$FMS" ;;  # F1 after a library-socket outage
  F1) INJ0="NVSHMEM_IBGDA_FAULT_INJECT=local_err:$FMS" ;;
  F1x5) INJ0="NVSHMEM_IBGDA_FAULT_INJECT=local_err:$FMS${SHOTS:-,150,-1,150,150}" ;;
  F3) INJ1="NVSHMEM_IBGDA_FAULT_INJECT=peer_err:$FMS" ;;
  F2) INJ1="NVSHMEM_IBGDA_FAULT_INJECT=rem_access:$FMS" ;;
  F2A) ARGS="$ARGS --bad-at ${BAD_AT:-60}" ;;
  *) echo "unknown fault $FAULT" >&2; exit 2 ;;
esac
{
  echo "tag=$tag fault=$FAULT mode=$MODE trial=$TRIAL ft=${FT:-1} ring=${RING:-1} t1=${T1:-1} t1skip=${T1SKIP:-} skip=${SKIP:-} fetch=${FETCH:-0} fetch_every=${FETCH_EVERY:-1} fill=${FILL:-0} sock_s=${SOCK_S:-} sock_at_ms=${SOCK_AT_MS:-} sock_dir=${SOCK_DIR:-both} xenv=${XENV:-} nofin=${NOFIN:-0} rc_per_pe=${RC_PER_PE:-1} rc_map=${RC_MAP:-none}"
  echo "iters=$ITERS bytes=$BYTES gap_us=$GAP_US ctas=${CTAS:-} threads=${THREADS:-} burst=${BURST:-} reps=${REPS:-} fault_ms=$FMS shots=${SHOTS:-} kill_ms=${KILL_MS:-} cut_s=${CUT_S:-} cut_at_ms=${CUT_AT_MS:-}"
  echo "hold_ms=${HOLD_MS:-} gid_r=${GID_R:-4} gid_s=${GID_S:-3} ib_timeout=${NVSHMEM_IB_TIMEOUT:-14} bundle=$BUNDLE bin=$BIN start=$(date '+%F %T')"
  echo "md5_bin=$(md5sum < $LBIN | cut -c1-12) md5_transport=$(md5sum < $BUNDLE/lib/nvshmem_transport_ibgda.so.7.0.0 | cut -c1-12) md5_host=$(md5sum < $BUNDLE/lib/libnvshmem_host.so.3.9.0 | cut -c1-12)"
} > "$META"
pkill -x "$BIN" 2>/dev/null
ssh -n -o ConnectTimeout=5 "$SUNNY_SSH" "pkill -x $BIN 2>/dev/null; true"
REMOTE_ENV="$(node_env sunny)"
ssh -n -o ConnectTimeout=8 "$SUNNY_SSH" \
  "$REMOTE_ENV; ${INJ1:+export $INJ1;} ${XENV:+export $XENV;} exec timeout -s KILL $PROC_TIMEOUT $RBIN 1 $RAIN_MGMT $PORT $MODE $ARGS" \
  >"$L1" 2>&1 &
SSH_PID=$!
(
  eval "$(node_env rain)"
  ${INJ0:+export $INJ0}
  ${XENV:+export $XENV}
  # shellcheck disable=SC2086
  exec timeout -s KILL "$PROC_TIMEOUT" "$LBIN" 0 "$RAIN_MGMT" "$PORT" "$MODE" $ARGS
) >"$L0" 2>&1 &
PE0_PID=$!
wait_start() {  # wait until PE0 printed its start line
  for i in $(seq 1 1200); do
    grep -q "^T1APP rank 0" "$L0" 2>/dev/null && return 0
    kill -0 "$PE0_PID" 2>/dev/null || return 1
    sleep 0.01
  done
  return 1
}
if [ "$FAULT" = F4 ]; then
  if wait_start; then
    sleep "$(python3 -c "print(${KILL_MS:-600}/1000)")"
    KT=$(ssh -n -o ConnectTimeout=5 "$SUNNY_SSH" "python3 -c 'import time,subprocess; t=time.clock_gettime(time.CLOCK_MONOTONIC); subprocess.run([\"pkill\",\"-9\",\"-x\",\"$BIN\"]); print(\"%.6f\" % t)'" 2>/dev/null)
    echo "kill_mono1_s=$KT" >> "$META"
    echo "[runner] F4: SIGKILL PE1 at sunny mono_s=$KT" >> "$L0"
  fi
fi
if [ "$FAULT" = SOCK ] || [ "$FAULT" = SOCK1 ]; then
  # library-socket outage on rain only: drop the packets of PE0's T1 socket (its local port, read
  # from the library's log line) in both directions for SOCK_S seconds, no RDMA fault; the rules
  # carry a comment and are removed here and by the hold's trap
  if wait_start; then
    for i in $(seq 1 600); do grep -q 'library socket on .*peer1:local_port=' "$L0" && break; sleep 0.01; done
    LP=$(grep -o 'peer1:local_port=[0-9]*' "$L0" | head -1 | cut -d= -f2)
    sleep "$(python3 -c "print(${SOCK_AT_MS:-1500}/1000)")"
    if [ -n "$LP" ]; then
      echo "sock_port=$LP sock_start_rain_mono_ms=$(python3 -c 'import time; print("%.3f" % (time.clock_gettime(time.CLOCK_MONOTONIC)*1e3))')" >> "$META"
      # SOCK_DIR=both (default): drop both directions; SOCK_DIR=in: only packets arriving at PE0's
      # socket, so that PE0's keepalive times out first and it re-dials while sunny still believes
      # the old connection is alive
      sudo -n iptables -I INPUT -p tcp --dport "$LP" -m comment --comment t1sock -j DROP
      [ "${SOCK_DIR:-both}" = both ] && sudo -n iptables -I OUTPUT -p tcp --sport "$LP" -m comment --comment t1sock -j DROP
      sleep "${SOCK_S:-8}"
      sudo -n iptables -D INPUT -p tcp --dport "$LP" -m comment --comment t1sock -j DROP
      [ "${SOCK_DIR:-both}" = both ] && sudo -n iptables -D OUTPUT -p tcp --sport "$LP" -m comment --comment t1sock -j DROP
      echo "sock_end_rain_mono_ms=$(python3 -c 'import time; print("%.3f" % (time.clock_gettime(time.CLOCK_MONOTONIC)*1e3))') iptables_left=$(sudo -n iptables -S | grep -c t1sock)" >> "$META"
    else
      echo "sock_port=none" >> "$META"
    fi
  fi
fi
if [ "$FAULT" = FLAP ]; then
  if wait_start; then
    sleep "$(python3 -c "print(${CUT_AT_MS:-600}/1000)")"
    echo "cut_start_rain_mono_ms=$(python3 -c 'import time; print("%.3f" % (time.clock_gettime(time.CLOCK_MONOTONIC)*1e3))')" >> "$META"
    GBH_LOG="$OUTDIR/${tag}.gbh.log" bash "$GBH" cut "${CUT_S:-0.5}" >> "$META" 2>&1
    echo "cut_end_rain_mono_ms=$(python3 -c 'import time; print("%.3f" % (time.clock_gettime(time.CLOCK_MONOTONIC)*1e3))')" >> "$META"
  fi
fi
wait "$PE0_PID"; PE0_RC=$?
wait "$SSH_PID"; PE1_RC=$?
pkill -x "$BIN" 2>/dev/null
LEFT0=$(pgrep -x "$BIN" | wc -l)
LEFT1=$(ssh -n -o ConnectTimeout=5 "$SUNNY_SSH" "pkill -x $BIN 2>/dev/null; sleep 0.2; pgrep -x $BIN | wc -l")
echo "pe0_rc=$PE0_RC pe1_rc=$PE1_RC leftover_rain=$LEFT0 leftover_sunny=$LEFT1 end=$(date '+%F %T')" >> "$META"
echo "$tag pe0_rc=$PE0_RC pe1_rc=$PE1_RC $(grep -h '^T1RESULT' "$L0" "$L1" | tr '\n' ' ')"
