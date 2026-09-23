#!/usr/bin/env bash
# run_trial.sh - one GIN GDAKI Q4 trial (rank0=rain initiator, rank1=sunny target).
#
# Adapted from ../../gin/scripts/run_trial.sh (Q2). Must be invoked *inside*
# ../../common/cluster_run.sh (cluster lock + idle RoCE link). Launches rank1 on
# sunny over SSH and rank0 on rain, injects the fault, keeps both ranks' logs and
# KEY=VALUE files, and appends one CSV row (scripts/q4_row.py) to $OUT_CSV.
#
# usage: run_trial.sh <none|F1|F2|F3|F4|lat> <timeout|blocking> <trial#> <out_csv> [iters] [ib_timeout]
# knobs (env):
#   CQ_TYPE=ring|collapsed|collapsed_host  -> NCCL_GIN_GDAKI_CQ_TYPE (unset/ring = stock)
#   CLASSIFY=0|1                           -> NCCL_GIN_FAULT_CLASSIFY (default 0 = stock)
#   QPWATCH_MS=<ms>                        -> NCCL_GIN_Q4_QPWATCH_MS (diagnostic, default 0)
#   POLL_US=<us>                           -> NCCL_GIN_FAULT_CLASSIFY_POLL_US (default 20)
#   ASYNC_POLL_US=<us>                     -> driver ncclCommGetAsyncError period (default 200)
#   LATE_US=<us>                           -> NCCL_GIN_Q4_LATE_READ_US (collapsed slot re-read, default 0)
#   INJECT_MS, GAP_MS, DEV_TIMEOUT_S, WATCHDOG_S, BYTES, KILL_DELAY_MS, GIN_BLOCK_CAP_S,
#   GIN_POST_POLL_S, LAT_ITERS, LAT_REPS as in the Q2 runner / driver.
#   EXTRA_ENV="VAR=val ..."                -> extra environment for both ranks (diagnostics)
set -u

FAULT=$1; WAIT=$2; TRIAL=$3; OUT_CSV=$4
ITERS=${5:-120}
IB_TIMEOUT=${6:-14}
INJECT_MS=${INJECT_MS:-600}
GAP_MS=${GAP_MS:-15}
DEV_TIMEOUT_S=${DEV_TIMEOUT_S:-5}
WATCHDOG_S=${WATCHDOG_S:-60}
BYTES=${BYTES:-262144}
CQ_TYPE=${CQ_TYPE:-ring}
CLASSIFY=${CLASSIFY:-0}
QPWATCH_MS=${QPWATCH_MS:-0}
POLL_US=${POLL_US:-20}
ASYNC_POLL_US=${ASYNC_POLL_US:-200}
LATE_US=${LATE_US:-0}

HERE=$(cd "$(dirname "$0")" && pwd)
RAIN_MGMT=192.0.2.193
SUNNY_SSH=${SUNNY_SSH:-unionxic@192.0.2.194}
BUNDLE=/home/unionxic/gi-bundle/gin_q4
BIN=gin_q4
PORT=$(( 45000 + ($$ + RANDOM) % 4000 ))

WORK=$(mktemp -d "${Q4_WORKDIR:-/tmp}/gin_q4_trial.XXXXXX")
R0KV=$WORK/r0.kv;  R1KV=$WORK/r1.kv
R0LOG=$WORK/r0.log; R1LOG=$WORK/r1.log
tag="gdaki/${CQ_TYPE}/c${CLASSIFY}/${FAULT}/${WAIT}#${TRIAL}"

GID_PROBE='d=/sys/class/infiniband/$1/ports/1
for g in $(ls "$d/gids" | sort -n); do
  [ "$(cat "$d/gid_attrs/types/$g" 2>/dev/null)" = "RoCE v2" ] || continue
  case "$(cat "$d/gids/$g")" in 0000:0000:0000:0000:0000:ffff:*) echo "$g"; exit 0;; esac
done; exit 1'
GID0=$(bash -c "$GID_PROBE" _ mlx5_1) || { echo "[$tag] no GID on rain mlx5_1" >&2; exit 1; }
GID1=$(ssh -n "$SUNNY_SSH" bash -c "'$GID_PROBE'" _ mlx5_0) || { echo "[$tag] no GID on sunny mlx5_0" >&2; exit 1; }

INJ0=""; INJ1=""; KILL_R1=0
case "$FAULT" in
  none|lat) ;;
  F1) INJ0="local_err:$INJECT_MS" ;;
  F2) ;;
  F3) INJ1="peer_err:$INJECT_MS" ;;
  F4) KILL_R1=1 ;;
  *) echo "unknown fault $FAULT" >&2; exit 1 ;;
esac

Q4ENV="NCCL_GIN_FAULT_CLASSIFY=$CLASSIFY NCCL_GIN_FAULT_CLASSIFY_POLL_US=$POLL_US NCCL_GIN_Q4_QPWATCH_MS=$QPWATCH_MS NCCL_GIN_Q4_LATE_READ_US=$LATE_US"
[ "$CQ_TYPE" != ring ] && Q4ENV="$Q4ENV NCCL_GIN_GDAKI_CQ_TYPE=$CQ_TYPE"
COMMON_ENV="NCCL_DEBUG=${NCCL_DEBUG:-WARN} NCCL_DEBUG_SUBSYS=${NCCL_DEBUG_SUBSYS:-INIT,NET} \
NCCL_SOCKET_IFNAME=eno1 NCCL_GIN_TYPE=3 NCCL_IB_TIMEOUT=$IB_TIMEOUT \
NCCL_GIN_ENABLE=1 GIN_ABORT_WATCHDOG_S=15 LD_LIBRARY_PATH=$BUNDLE \
GIN_BLOCK_CAP_S=${GIN_BLOCK_CAP_S:-25} GIN_POST_POLL_S=${GIN_POST_POLL_S:-15} GIN_ASYNC_POLL_US=$ASYNC_POLL_US \
GIN_LAT_ITERS=${LAT_ITERS:-2000} GIN_LAT_REPS=${LAT_REPS:-5} $Q4ENV ${EXTRA_ENV:-}"

DRV_ARGS="$ITERS $BYTES $WAIT $FAULT $DEV_TIMEOUT_S $WATCHDOG_S"
echo "[$tag] GID rain=$GID0 sunny=$GID1 port=$PORT ib_timeout=$IB_TIMEOUT inject=${INJECT_MS}ms q4env='$Q4ENV'" >&2

REMOTE_CMD="cd $BUNDLE && $COMMON_ENV NCCL_IB_HCA=mlx5_0 NCCL_IB_GID_INDEX=$GID1 \
${INJ1:+NCCL_GIN_FAULT_INJECT=$INJ1} \
exec stdbuf -oL -eL timeout -s KILL $((WATCHDOG_S+30)) ./$BIN 1 $RAIN_MGMT $PORT $DRV_ARGS /tmp/gin_q4_r1.kv $GAP_MS \
> /tmp/gin_q4_r1.log 2>&1"
ssh -n "$SUNNY_SSH" "$REMOTE_CMD" &
SSH_PID=$!

if [ "$KILL_R1" = 1 ]; then
  KILL_DELAY_MS=${KILL_DELAY_MS:-2500}
  ( sleep "$(awk "BEGIN{print $KILL_DELAY_MS/1000}")"
    ssh -n "$SUNNY_SSH" "pid=\$(pgrep -x $BIN | head -1); [ -n \"\$pid\" ] && python3 -c \"import os,sys,time; t=time.clock_gettime(time.CLOCK_MONOTONIC)*1e3; os.kill(int(sys.argv[1]),9); print('kill_mono_ms=%.3f' % t)\" \$pid" > "$WORK/kill.out" 2>&1
    echo "[$tag] SIGKILLed rank1 after ${KILL_DELAY_MS}ms: $(cat "$WORK/kill.out")" >&2 ) &
  KILLER=$!
fi

LATRAW=""
[ "$FAULT" = lat ] && LATRAW="GIN_LAT_RAW=$WORK/lat_raw.csv"
env $COMMON_ENV NCCL_IB_HCA=mlx5_1 NCCL_IB_GID_INDEX=$GID0 \
  ${INJ0:+NCCL_GIN_FAULT_INJECT=$INJ0} $LATRAW \
  stdbuf -oL -eL timeout -s KILL $((WATCHDOG_S+30)) \
  "$BUNDLE/$BIN" 0 $RAIN_MGMT $PORT $DRV_ARGS "$R0KV" "$GAP_MS" > "$R0LOG" 2>&1
R0RC=$?

wait "$SSH_PID" 2>/dev/null; R1RC=$?
[ "${KILLER:-}" ] && wait "$KILLER" 2>/dev/null
scp -q "$SUNNY_SSH:/tmp/gin_q4_r1.kv" "$R1KV" 2>/dev/null || true
scp -q "$SUNNY_SSH:/tmp/gin_q4_r1.log" "$R1LOG" 2>/dev/null || true
ssh -n "$SUNNY_SSH" "pgrep -x $BIN | xargs -r kill -9 2>/dev/null; rm -f /tmp/gin_q4_r1.kv /tmp/gin_q4_r1.log" || true
pkill -x $BIN 2>/dev/null || true
LEFT=$( { pgrep -x $BIN; ssh -n "$SUNNY_SSH" "pgrep -x $BIN"; } 2>/dev/null | wc -l)

LOGDIR=$(dirname "$OUT_CSV")/logs
mkdir -p "$LOGDIR"
stem="${CQ_TYPE}_c${CLASSIFY}_${FAULT}_${WAIT}_t${TRIAL}"
cp "$R0LOG" "$LOGDIR/${stem}_r0.log" 2>/dev/null || true
cp "$R1LOG" "$LOGDIR/${stem}_r1.log" 2>/dev/null || true
cp "$R0KV"  "$LOGDIR/${stem}_r0.kv"  2>/dev/null || true
cp "$R1KV"  "$LOGDIR/${stem}_r1.kv"  2>/dev/null || true
[ -f "$WORK/lat_raw.csv" ] && gzip -c "$WORK/lat_raw.csv" > "$LOGDIR/${stem}_lat_raw.csv.gz"
[ -f "$WORK/kill.out" ] && cp "$WORK/kill.out" "$LOGDIR/${stem}_kill.out"
echo "fault=$FAULT wait=$WAIT trial=$TRIAL cq=$CQ_TYPE classify=$CLASSIFY r0rc=$R0RC r1rc=$R1RC left=$LEFT \
qpwatch_ms=$QPWATCH_MS poll_us=$POLL_US late_us=$LATE_US bytes=$BYTES ib_timeout=$IB_TIMEOUT" > "$LOGDIR/${stem}_meta.txt"

python3 "$HERE/q4_row.py" --csv "$OUT_CSV" --fault "$FAULT" --wait "$WAIT" --trial "$TRIAL" \
  --cq "$CQ_TYPE" --classify "$CLASSIFY" --r0kv "$R0KV" --r1kv "$R1KV" --r0log "$R0LOG" --r1log "$R1LOG" \
  --kill "$WORK/kill.out" --r0rc "$R0RC" --r1rc "$R1RC" --left "$LEFT" --stem "$stem" >&2

rm -rf "$WORK"
exit 0
