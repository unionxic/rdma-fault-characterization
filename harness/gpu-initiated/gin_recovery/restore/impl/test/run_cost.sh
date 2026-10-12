#!/usr/bin/env bash
# run_cost.sh - gin-restore work package 10: one normal-path cost run of EXPERIMENT.md 7's cost cells, with the 9.15.6 driver
# (gin-remaining's gin_ts2 + ../../feas/gin_ts2_winflags.diff; both windows NCCL_WIN_STRICT_ORDERING in every arm, so the arms
# differ only in what is measured: the hold processes force strict anyway, 9.10.8). Rank 0 sends, rank 1 receives on the
# named node. The 6-vs-6 interleave of arms is hold_rs.sh's (9.15.6's method); each run is one arm.
#
# Cells cost_<metric>_<arm>_<node>; metric lat4k | lat256k (3 000 iterations of one put + signal + flush) | bw256k (burst,
# one thread, 12 iterations of 8 x 256 KiB + signal + flush; bandwidth = burst_K x bytes / p50). Arms:
#   the send-side log (lat_4k, lat_256k and the bandwidth cell of section 7; 9.5): hold policy, the macro driver, Resume never
#   called (unarmed), the log turned on only by the "measure only" variable NCCL_GIN_RESTORE_LOG_MEASURE:
#     off       no LOG_MEASURE (the hold path without the log)
#     on        LOG_MEASURE, checksum off
#     sampled   LOG_MEASURE, NCCL_GIN_RESTORE_CHECKSUM=sampled
#     full      LOG_MEASURE, NCCL_GIN_RESTORE_CHECKSUM=full
#   hold before arming vs fail-fast (lat_hold_unarmed; 9.10.6 (다)): the macro driver in both arms, so only the policy differs
#     ua-ff     NCCL_GIN_FAULT_POLICY=failfast
#     ua-hold   NCCL_GIN_FAULT_POLICY=hold (unarmed)
#   the fail-fast branch (lat_ff_branch; 9.11.5 decision (나) (4)): fail-fast programs, this layer vs hk
#     ffb-rs    the restore production libnccl (rsp) + gin_ts2_ff (this layer's headers, no macro)
#     ffb-hk    gpu-detect's production libnccl (hkp, read only) + the deployed ord driver (hw = hk headers)
#   Not covered: section 7's 4 KiB get arm of lat_ff_branch (gin_ts2 has no get latency mode: GIN_TS_GET refuses lat mode).
# Common: NCCL_RMA_DISABLE=1, NCCL_NUM_RMA_CTX=0, NCCL_GIN_TYPE=3, NCCL_SYM_GIN_KERNELS_ENABLE=0, one GIN connection, QP watch
# off (9.15.6's w0), wait blocking, gap 0, NCCL_DEBUG=WARN.
#
# Safety: as ../../feas/run_ord.sh (this is its sibling): both processes under timeout -s KILL and gin_ts2's own watchdog;
# nothing killed by name; ports 29000-30999 with a nonce; rain's management address at run time; IPv4 masked in the copied
# logs, the node originals deleted; every NCCL_/GIN_ variable of the caller dropped first; leftovers counted by the run's
# own file paths only (gin_ts2 is also other studies' driver name).
#
# usage: run_cost.sh <cell> <run-tag> <logdir>
# env: SUNNY_SSH (required), HCA_RAIN (mlx5_1), HCA_SUNNY (mlx5_0), LOG_MEASURE_MS (50)
# files in <logdir>: <cell>_<tag>_r0.kv/_r1.kv/_r0.log/_r1.log, <cell>_<tag>_lat_raw.csv.gz (lat), <cell>_<tag>_meta.txt
set -u
CELL=${1:?cell}; TAG=${2:?run tag}; LOGDIR=${3:?logdir}
for v in $(env | sed -n 's/^\(\(NCCL\|GIN\)_[A-Za-z0-9_]*\)=.*/\1/p'); do unset "$v"; done
SUNNY_SSH=${SUNNY_SSH:?set SUNNY_SSH}
SUNNY_HOST=${SUNNY_SSH#*@}
HCA_RAIN=${HCA_RAIN:-mlx5_1}; HCA_SUNNY=${HCA_SUNNY:-mlx5_0}
LOG_MEASURE_MS=${LOG_MEASURE_MS:-50}
IFS=_ read -r _ METRIC ARM RX <<< "$CELL"
case "$METRIC" in
  lat4k)   MODE=lat;   ITERS=3000; BYTES=4096;   XENV="" ;;
  lat256k) MODE=lat;   ITERS=3000; BYTES=262144; XENV="" ;;
  bw256k)  MODE=burst; ITERS=12;   BYTES=262144; XENV="GIN_TS_TX_BLOCKS=1 GIN_TS_TX_THREADS=1 GIN_TS_BURST_K=8 GIN_TS_AGG=1" ;;
  *) echo "bad metric in $CELL" >&2; exit 2 ;;
esac
RSPLIB=$HOME/rs-bundle/lib/rsp; HKPLIB=$HOME/gi-bundle/gin_ts2/hkp
MACRO=$HOME/rs-bundle/rscost/gin_ts2; FFBIN=$HOME/rs-bundle/rscost/gin_ts2_ff; HKBIN=$HOME/rs-bundle/ord/gin_ts2
HOLDLOG="NCCL_GIN_FAULT_POLICY=hold NCCL_GIN_RESTORE=1"
case "$ARM" in
  off)      BIN=$MACRO; LIB=$RSPLIB; RSENV="$HOLDLOG" ;;
  on)       BIN=$MACRO; LIB=$RSPLIB; RSENV="$HOLDLOG NCCL_GIN_RESTORE_LOG_MEASURE=$LOG_MEASURE_MS NCCL_GIN_RESTORE_CHECKSUM=off" ;;
  sampled)  BIN=$MACRO; LIB=$RSPLIB; RSENV="$HOLDLOG NCCL_GIN_RESTORE_LOG_MEASURE=$LOG_MEASURE_MS NCCL_GIN_RESTORE_CHECKSUM=sampled" ;;
  full)     BIN=$MACRO; LIB=$RSPLIB; RSENV="$HOLDLOG NCCL_GIN_RESTORE_LOG_MEASURE=$LOG_MEASURE_MS NCCL_GIN_RESTORE_CHECKSUM=full" ;;
  ua-ff)    BIN=$MACRO; LIB=$RSPLIB; RSENV="NCCL_GIN_FAULT_POLICY=failfast" ;;
  ua-hold)  BIN=$MACRO; LIB=$RSPLIB; RSENV="$HOLDLOG" ;;
  ffb-rs)   BIN=$FFBIN; LIB=$RSPLIB; RSENV="NCCL_GIN_FAULT_POLICY=failfast" ;;
  ffb-hk)   BIN=$HKBIN; LIB=$HKPLIB; RSENV="" ;;
  *) echo "bad arm in $CELL" >&2; exit 2 ;;
esac
case "$RX" in rain) TX=sunny ;; sunny) TX=rain ;; *) echo "bad node in $CELL" >&2; exit 2 ;; esac
[ -x "$BIN" ] && [ -f "$LIB/libnccl.so.2" ] || { echo "missing $BIN or $LIB/libnccl.so.2 on rain" >&2; exit 1; }
umask 077
WORK=$(mktemp -d /tmp/rs_cost.XXXXXX)
RT=/tmp/rs_cost_$$_$RANDOM
cleanup() { ssh -n "$SUNNY_SSH" "rm -rf $RT.*" 2>/dev/null || true; rm -rf "$WORK"; }
trap cleanup EXIT
D=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=../../../remaining/portpick.sh
. "$D/../../../remaining/portpick.sh"
GID_PROBE='d=/sys/class/infiniband/$1/ports/1
for g in $(ls "$d/gids" | sort -n); do
  [ "$(cat "$d/gid_attrs/types/$g" 2>/dev/null)" = "RoCE v2" ] || continue
  case "$(cat "$d/gids/$g")" in 0000:0000:0000:0000:0000:ffff:1e00:00*) echo "$g"; exit 0;; esac
done; exit 1'
GID_R=$(bash -c "$GID_PROBE" _ "$HCA_RAIN") || { echo "no GID on rain" >&2; exit 1; }
GID_S=$(ssh -n "$SUNNY_SSH" bash -c "'$GID_PROBE'" _ "$HCA_SUNNY") || { echo "no GID on sunny" >&2; exit 1; }
RAIN_MGMT=$(ip -4 route get "$SUNNY_HOST" 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p' | head -1)
[ -n "$RAIN_MGMT" ] || { echo "cannot find rain's management address" >&2; exit 1; }
if [ "$TX" = rain ]; then R0_ADDR=$RAIN_MGMT; else R0_ADDR=$SUNNY_HOST; fi
WD=45; TMO=$((WD + 20))
pick_port
NONCE=$(new_nonce)
hca() { [ "$1" = rain ] && echo "$HCA_RAIN" || echo "$HCA_SUNNY"; }
gidx() { [ "$1" = rain ] && echo "$GID_R" || echo "$GID_S"; }
NENV="NCCL_DEBUG=WARN NCCL_SOCKET_IFNAME=eno1 NCCL_GIN_TYPE=3 NCCL_GIN_ENABLE=1 NCCL_IB_TIMEOUT=14 \
NCCL_GIN_FAULT_CLASSIFY=1 NCCL_GIN_FAULT_RECOVERY=1 NCCL_GIN_FAULT_TRANSPARENT=1 NCCL_GIN_TS_QPWATCH_MS=0 NCCL_GIN_Q4_QPWATCH_MS=0 \
NCCL_RMA_DISABLE=1 NCCL_NUM_RMA_CTX=0 NCCL_SYM_GIN_KERNELS_ENABLE=0 NCCL_GIN_NCONNECTIONS=1 GIN_TS_WIN_STRICT=1 \
GIN_ABORT_WATCHDOG_S=15 GIN_RDV_NONCE=$NONCE LD_LIBRARY_PATH=$LIB $RSENV $XENV"
declare -A PIDS
start() {
  local node=$1 r=$2 envs; envs="$NENV NCCL_IB_HCA=$(hca "$node") NCCL_IB_GID_INDEX=$(gidx "$node")"
  local args="$r $R0_ADDR $PORT $ITERS $BYTES blocking $MODE 8 $WD"
  if [ "$r" = 0 ] && [ "$MODE" = lat ]; then
    if [ "$node" = rain ]; then envs="$envs GIN_LAT_RAW=$WORK/lat_raw.csv"; else envs="$envs GIN_LAT_RAW=$RT.lat_raw.csv"; fi
  fi
  if [ "$node" = rain ]; then
    ( mkdir -p "$WORK/cwd$r" && cd "$WORK/cwd$r" && ulimit -c 0 && eval "env $envs stdbuf -oL -eL timeout -s KILL $TMO $BIN $args $WORK/r$r.kv 0" \
        > "$WORK/r$r.log" 2>&1; echo $? > "$WORK/r$r.rc" ) &
  else
    ssh -n "$SUNNY_SSH" "umask 077 && mkdir -p $RT.cwd$r && cd $RT.cwd$r && ulimit -c 0 && $envs stdbuf -oL -eL timeout -s KILL $TMO $BIN $args $RT.r$r.kv 0 \
> $RT.r$r.log 2>&1; echo \$?" > "$WORK/r$r.rc" 2>/dev/null &
  fi
  PIDS[$r]=$!
}
T0=$(date +%s.%N)
start "$TX" 0
sleep 1
start "$RX" 1
wait "${PIDS[0]}"; wait "${PIDS[1]}"
T1=$(date +%s.%N)
LEFT=$( { pgrep -f "[${WORK:0:1}]${WORK:1}/r[01].kv" 2>/dev/null; ssh -n "$SUNNY_SSH" "pgrep -f '[${RT:0:1}]${RT:1}.r[01].kv'"; } 2>/dev/null | wc -l)
for r in 0 1; do
  node=$TX; [ "$r" = 1 ] && node=$RX
  if [ "$node" = sunny ]; then
    scp -q "$SUNNY_SSH:$RT.r$r.kv" "$WORK/r$r.kv" 2>/dev/null || true
    scp -q "$SUNNY_SSH:$RT.r$r.log" "$WORK/r$r.log" 2>/dev/null || true
    [ "$r" = 0 ] && [ "$MODE" = lat ] && { scp -q "$SUNNY_SSH:$RT.lat_raw.csv" "$WORK/lat_raw.csv" 2>/dev/null || true; }
  fi
done
mkdir -p "$LOGDIR"
stem="${CELL}_${TAG}"
MASK='s/[0-9]\{1,3\}\.[0-9]\{1,3\}\.[0-9]\{1,3\}\.[0-9]\{1,3\}/<ip>/g'
for r in 0 1; do
  [ -f "$WORK/r$r.kv" ] && sed "$MASK" "$WORK/r$r.kv" > "$LOGDIR/${stem}_r$r.kv"
  [ -f "$WORK/r$r.log" ] && sed "$MASK" "$WORK/r$r.log" > "$LOGDIR/${stem}_r$r.log"
done
[ -f "$WORK/lat_raw.csv" ] && gzip -c "$WORK/lat_raw.csv" > "$LOGDIR/${stem}_lat_raw.csv.gz"
rc() { tr -d '\n' < "$WORK/r$1.rc" 2>/dev/null || echo none; }
case "$LIB" in "$HKPLIB") LIBKEY=hkp ;; *) LIBKEY=rsp ;; esac
echo "cell=$CELL tag=$TAG metric=$METRIC arm=$ARM rx=$RX tx=$TX mode=$MODE iters=$ITERS bytes=$BYTES lib=$LIBKEY \
bin=$(basename "$BIN") log_measure_ms=$LOG_MEASURE_MS rc_r0=$(rc 0) rc_r1=$(rc 1) left=$LEFT hca_rain=$HCA_RAIN \
hca_sunny=$HCA_SUNNY gid_rain=$GID_R gid_sunny=$GID_S port=$PORT port_tries=$PORT_TRIES rdv_nonce_set=1 qpwatch_ms=0 \
runner=cost wall_s=$(awk -v a="$T0" -v b="$T1" 'BEGIN{printf "%.1f", b - a}')" > "$LOGDIR/${stem}_meta.txt"
echo "[$stem] rc r0=$(rc 0) r1=$(rc 1) left=$LEFT :: $(grep -ho 'lat_p50_us=[0-9.]*\|exit=[0-9]*' "$WORK/r0.kv" 2>/dev/null | tr '\n' ' ')" >&2
exit 0
