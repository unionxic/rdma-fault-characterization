#!/usr/bin/env bash
# run_min.sh - one trial of the minimal bidirectional program ../../gin_bidir_min.cu (rank 0 = rain, rank 1 = sunny),
# inside ../../../common/cluster_run.sh. Default BUILD=base (the unpatched gpudb build, recovery off).
# usage: run_min.sh <both|d01|d10|seq> <bytes> <iters> <trial-tag> <logdir>
# env: BUILD=base|s2, SAME_CTX=1 (both directions on context 0), TIMEOUT_S (10), WATCHDOG_S (60), EXTRA_ENV, R0_ENV/R1_ENV
set -u
MODE=$1; BYTES=$2; ITERS=$3; TRIAL=$4; LOGDIR=$5
BUILD=${BUILD:-base}; TIMEOUT_S=${TIMEOUT_S:-10}; WATCHDOG_S=${WATCHDOG_S:-60}
RAIN_MGMT=192.0.2.193
SUNNY_SSH=${SUNNY_SSH:-unionxic@192.0.2.194}
BUNDLE=/home/unionxic/gi-bundle/gin_ts2; [ "$BUILD" = base ] && BUNDLE=$BUNDLE/base
BIN=gin_bidir_min
PORT=$(( 46000 + ($$ + RANDOM) % 3000 ))
WORK=$(mktemp -d /tmp/gin_min_trial.XXXXXX)
GID_PROBE='d=/sys/class/infiniband/$1/ports/1
for g in $(ls "$d/gids" | sort -n); do
  [ "$(cat "$d/gid_attrs/types/$g" 2>/dev/null)" = "RoCE v2" ] || continue
  case "$(cat "$d/gids/$g")" in 0000:0000:0000:0000:0000:ffff:1e00:00*) echo "$g"; exit 0;; esac
done; exit 1'
GID0=$(bash -c "$GID_PROBE" _ mlx5_1) || { echo "no GID on rain" >&2; exit 1; }
GID1=$(ssh -n "$SUNNY_SSH" bash -c "'$GID_PROBE'" _ mlx5_0) || { echo "no GID on sunny" >&2; exit 1; }
REC=0; TSENV=""; [ "$BUILD" = s2 ] && { REC=1; TSENV="NCCL_GIN_FAULT_TRANSPARENT=${TS:-1}"; }
NENV="NCCL_DEBUG=WARN NCCL_DEBUG_SUBSYS=INIT,NET NCCL_SOCKET_IFNAME=eno1 NCCL_GIN_TYPE=3 NCCL_GIN_ENABLE=1 NCCL_IB_TIMEOUT=14 \
NCCL_GIN_FAULT_CLASSIFY=1 NCCL_GIN_FAULT_RECOVERY=$REC $TSENV ${SAME_CTX:+MIN_SAME_CTX=$SAME_CTX} LD_LIBRARY_PATH=$BUNDLE ${EXTRA_ENV:-}"
tag="min/$BUILD/$MODE/${BYTES}B#$TRIAL"
echo "[$tag] GID rain=$GID0 sunny=$GID1 port=$PORT iters=$ITERS bar1_rain=$(nvidia-smi -q | grep -A2 'BAR1 Memory' | grep Used | awk '{print $3}')MiB" >&2
ssh -n "$SUNNY_SSH" "cd $BUNDLE && $NENV NCCL_IB_HCA=mlx5_0 NCCL_IB_GID_INDEX=$GID1 ${R1_ENV:-} exec stdbuf -oL -eL timeout -s KILL $((WATCHDOG_S+20)) \
./$BIN 1 $RAIN_MGMT $PORT $ITERS $BYTES $MODE /tmp/gin_min_r1.kv $TIMEOUT_S > /tmp/gin_min_r1.log 2>&1" &
SSH_PID=$!
T0=$(date +%s.%N)
env $NENV NCCL_IB_HCA=mlx5_1 NCCL_IB_GID_INDEX=$GID0 ${R0_ENV:-} stdbuf -oL -eL timeout -s KILL $((WATCHDOG_S+20)) \
  "$BUNDLE/$BIN" 0 $RAIN_MGMT $PORT $ITERS $BYTES $MODE "$WORK/r0.kv" $TIMEOUT_S > "$WORK/r0.log" 2>&1
R0RC=$?
T1=$(date +%s.%N)
wait "$SSH_PID" 2>/dev/null; R1RC=$?
scp -q "$SUNNY_SSH:/tmp/gin_min_r1.kv" "$WORK/r1.kv" 2>/dev/null || true
scp -q "$SUNNY_SSH:/tmp/gin_min_r1.log" "$WORK/r1.log" 2>/dev/null || true
ssh -n "$SUNNY_SSH" "pgrep -x $BIN | xargs -r kill -9 2>/dev/null; rm -f /tmp/gin_min_r1.kv /tmp/gin_min_r1.log" || true
pkill -x $BIN 2>/dev/null || true
LEFT=$( { pgrep -x $BIN; ssh -n "$SUNNY_SSH" "pgrep -x $BIN"; } 2>/dev/null | wc -l)
mkdir -p "$LOGDIR"
stem="${CELL:-min_${BUILD}_${MODE}_${BYTES}}_${TRIAL}"
for f in r0.log r1.log r0.kv r1.kv; do [ -f "$WORK/$f" ] && cp "$WORK/$f" "$LOGDIR/${stem}_$f"; done
echo "cell=${CELL:-} build=$BUILD mode=$MODE bytes=$BYTES iters=$ITERS same_ctx=${SAME_CTX:-0} r0env=$(echo ${R0_ENV:-} | tr ' ' '+') r1env=$(echo ${R1_ENV:-} | tr ' ' '+') trial=$TRIAL r0rc=$R0RC r1rc=$R1RC left=$LEFT \
wall_s=$(awk "BEGIN{printf \"%.1f\", $T1-$T0}") gid0=$GID0 gid1=$GID1" > "$LOGDIR/${stem}_meta.txt"
echo "[$tag] r0rc=$R0RC r1rc=$R1RC left=$LEFT wall=$(awk "BEGIN{printf \"%.1f\", $T1-$T0}")s :: $(grep -h 'rx_dir\|tx_dir' "$WORK/r0.kv" "$WORK/r1.kv" 2>/dev/null | sed 's/ tx_max_lat.*//;s/ host_first_bad.*signal_exact=/ exact=/' | tr '\n' '|')" >&2
rm -rf "$WORK"
exit 0
