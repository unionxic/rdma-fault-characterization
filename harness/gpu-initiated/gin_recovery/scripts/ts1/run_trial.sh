#!/usr/bin/env bash
# run_trial.sh - one S1 trial (rank0 = rain put initiator, rank1 = sunny target), inside
# ../../../common/cluster_run.sh. The application (gin_ts1) is the same unmodified loop in every
# cell; only the NCCL environment and the injected fault differ.
#
# usage: run_trial.sh <none|F1|F2|F3|F4|lat> <timeout|blocking> <trial-tag> <logdir> [iters] [bytes]
# env knobs:
#   TS=0|1        NCCL_GIN_FAULT_TRANSPARENT (default 1). REC/CLASSIFY default 1 (the gpudb v2 stack).
#   BASE=1        run the gpudb (v2) libnccl + the driver compiled against it (bundle base/), TS ignored
#   INJECT=<ms>   hook delay list (F1 on rank 0 local_err, F3 on rank 1 peer_err), default 700
#   R0_ENV=<VAR=val ...>  extra environment for rank 0 only (test knobs of the initiator)
#   KILL_DELAY_MS (F4, default 1200), GAP_US (default 15000; lat: 0), DEV_TIMEOUT_S (flush timeout in
#   timeout mode, default 8), WATCHDOG_S (default 45), DIAG (NCCL_GIN_TS_DIAG), EXTRA_ENV
set -u
FAULT=$1; WAIT=$2; TRIAL=$3; LOGDIR=$4
ITERS=${5:-120}
BYTES=${6:-262144}
TS=${TS:-1}; REC=${REC:-1}; CLASSIFY=${CLASSIFY:-1}; BASE=${BASE:-0}
INJECT=${INJECT:-700}
DEV_TIMEOUT_S=${DEV_TIMEOUT_S:-8}
WATCHDOG_S=${WATCHDOG_S:-45}
IB_TIMEOUT=${IB_TIMEOUT:-14}
if [ "$FAULT" = lat ]; then GAP_US=${GAP_US:-0}; else GAP_US=${GAP_US:-15000}; fi
RAIN_MGMT=192.0.2.193
SUNNY_SSH=${SUNNY_SSH:-unionxic@192.0.2.194}
BUNDLE=/home/unionxic/gi-bundle/gin_ts1
[ "$BASE" = 1 ] && BUNDLE=$BUNDLE/base
# VAR=<name>: a cost-attribution variant of the S1 driver (var_<name>/, same libnccl; measurement only)
[ -n "${VAR:-}" ] && BUNDLE=$BUNDLE/var_$VAR
BIN=gin_ts1
PORT=$(( 46000 + ($$ + RANDOM) % 3000 ))
WORK=$(mktemp -d /tmp/gin_ts1_trial.XXXXXX)
GID_PROBE='d=/sys/class/infiniband/$1/ports/1
for g in $(ls "$d/gids" | sort -n); do
  [ "$(cat "$d/gid_attrs/types/$g" 2>/dev/null)" = "RoCE v2" ] || continue
  case "$(cat "$d/gids/$g")" in 0000:0000:0000:0000:0000:ffff:*) echo "$g"; exit 0;; esac
done; exit 1'
GID0=$(bash -c "$GID_PROBE" _ mlx5_1) || { echo "no GID on rain" >&2; exit 1; }
GID1=$(ssh -n "$SUNNY_SSH" bash -c "'$GID_PROBE'" _ mlx5_0) || { echo "no GID on sunny" >&2; exit 1; }
MODE=none; INJ0=""; INJ1=""; KILL_R1=0
case "$FAULT" in
  none) ;;
  lat) MODE=lat ;;
  F1) INJ0="local_err:$INJECT" ;;
  F2) MODE=F2 ;;
  F3) INJ1="peer_err:$INJECT" ;;
  F4) KILL_R1=1 ;;
  *) echo "unknown fault $FAULT" >&2; exit 1 ;;
esac
[ "$BASE" = 1 ] && TSENV="" || TSENV="NCCL_GIN_FAULT_TRANSPARENT=$TS"
NENV="NCCL_DEBUG=${NCCL_DEBUG:-WARN} NCCL_DEBUG_SUBSYS=${NCCL_DEBUG_SUBSYS:-INIT,NET} NCCL_SOCKET_IFNAME=eno1 \
NCCL_GIN_TYPE=3 NCCL_GIN_ENABLE=1 NCCL_IB_TIMEOUT=$IB_TIMEOUT NCCL_GIN_FAULT_CLASSIFY=$CLASSIFY \
NCCL_GIN_FAULT_RECOVERY=$REC $TSENV ${DIAG:+NCCL_GIN_TS_DIAG=$DIAG} GIN_ABORT_WATCHDOG_S=${ABORT_WD_S:-15} \
LD_LIBRARY_PATH=$BUNDLE ${EXTRA_ENV:-}"
ARGS="$ITERS $BYTES $WAIT $MODE $DEV_TIMEOUT_S $WATCHDOG_S"
tag="ts${TS}/b${BASE}/${FAULT}/${WAIT}#${TRIAL}"
echo "[$tag] GID rain=$GID0 sunny=$GID1 port=$PORT inject=$INJECT bytes=$BYTES iters=$ITERS" >&2
ssh -n "$SUNNY_SSH" "cd $BUNDLE && $NENV NCCL_IB_HCA=mlx5_0 NCCL_IB_GID_INDEX=$GID1 ${INJ1:+NCCL_GIN_FAULT_INJECT=$INJ1} \
exec stdbuf -oL -eL timeout -s KILL $((WATCHDOG_S+20)) ./$BIN 1 $RAIN_MGMT $PORT $ARGS /tmp/gin_ts1_r1.kv $GAP_US \
> /tmp/gin_ts1_r1.log 2>&1" &
SSH_PID=$!
if [ "$KILL_R1" = 1 ]; then
  KILL_DELAY_MS=${KILL_DELAY_MS:-1200}
  ( sleep "$(awk "BEGIN{print $KILL_DELAY_MS/1000}")"
    ssh -n "$SUNNY_SSH" "pid=\$(pgrep -x $BIN | head -1); [ -n \"\$pid\" ] && python3 -c \"import os,sys,time; t=time.clock_gettime(time.CLOCK_MONOTONIC)*1e3; os.kill(int(sys.argv[1]),9); print('kill_mono_ms=%.3f pid=%s' % (t, sys.argv[1]))\" \$pid" > "$WORK/kill.out" 2>&1
    echo "[$tag] SIGKILL rank1 after ${KILL_DELAY_MS} ms: $(cat "$WORK/kill.out")" >&2 ) &
  KILLER=$!
fi
LATRAW=""; [ "$FAULT" = lat ] && LATRAW="GIN_LAT_RAW=$WORK/lat_raw.csv"
T0=$(date +%s.%N)
env $NENV NCCL_IB_HCA=mlx5_1 NCCL_IB_GID_INDEX=$GID0 ${INJ0:+NCCL_GIN_FAULT_INJECT=$INJ0} $LATRAW ${R0_ENV:-} \
  stdbuf -oL -eL timeout -s KILL $((WATCHDOG_S+20)) "$BUNDLE/$BIN" 0 $RAIN_MGMT $PORT $ARGS "$WORK/r0.kv" $GAP_US \
  > "$WORK/r0.log" 2>&1
R0RC=$?
T1=$(date +%s.%N)
wait "$SSH_PID" 2>/dev/null; R1RC=$?
[ "${KILLER:-}" ] && wait "$KILLER" 2>/dev/null
scp -q "$SUNNY_SSH:/tmp/gin_ts1_r1.kv" "$WORK/r1.kv" 2>/dev/null || true
scp -q "$SUNNY_SSH:/tmp/gin_ts1_r1.log" "$WORK/r1.log" 2>/dev/null || true
# only our own binary name, exact match (other agents run other binaries)
ssh -n "$SUNNY_SSH" "pgrep -x $BIN | xargs -r kill -9 2>/dev/null; rm -f /tmp/gin_ts1_r1.kv /tmp/gin_ts1_r1.log" || true
pkill -x $BIN 2>/dev/null || true
LEFT=$( { pgrep -x $BIN; ssh -n "$SUNNY_SSH" "pgrep -x $BIN"; } 2>/dev/null | wc -l)
mkdir -p "$LOGDIR"
stem="${CELL:-ts${TS}b${BASE}_${FAULT}_${WAIT}}_${TRIAL}"
for f in r0.log r1.log r0.kv r1.kv kill.out; do [ -f "$WORK/$f" ] && cp "$WORK/$f" "$LOGDIR/${stem}_$f"; done
[ -f "$WORK/lat_raw.csv" ] && gzip -c "$WORK/lat_raw.csv" > "$LOGDIR/${stem}_lat_raw.csv.gz"
echo "cell=${CELL:-} var=${VAR:-} r0env=$(echo ${R0_ENV:-} | tr ' ' '+') fault=$FAULT wait=$WAIT trial=$TRIAL ts=$TS base=$BASE rec=$REC classify=$CLASSIFY diag=${DIAG:-} inject=$INJECT \
iters=$ITERS bytes=$BYTES gap_us=$GAP_US r0rc=$R0RC r1rc=$R1RC left=$LEFT ib_timeout=$IB_TIMEOUT \
wall_s=$(awk "BEGIN{printf \"%.1f\", $T1-$T0}") bundle=$BUNDLE" > "$LOGDIR/${stem}_meta.txt"
echo "[$tag] r0rc=$R0RC r1rc=$R1RC left=$LEFT wall=$(awk "BEGIN{printf \"%.1f\", $T1-$T0}")s :: $(grep -h 'DONE outcome' "$WORK/r0.log" "$WORK/r1.log" 2>/dev/null | sed 's/^.*\] //' | tr '\n' '|')" >&2
rm -rf "$WORK"
exit 0
