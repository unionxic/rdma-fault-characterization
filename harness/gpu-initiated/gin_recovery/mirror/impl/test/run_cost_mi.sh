#!/usr/bin/env bash
# run_cost_mi.sh - gin-mirror, test branch: one normal-path cost run of ../../EXPERIMENT.md 7's mirror cost family, with
# gin-restore's cost frame (../../../restore/impl/test/run_cost.sh, copied and then changed). Rank 0 sends, rank 1 receives
# on the named node. The 6-vs-6 interleave of arms is hold_mi.sh's (gin-restore 9.15.6's method); each run is one arm.
#
# The mirror cost family (EXPERIMENT.md 7, 3's cost_mirror_*): the driver is gin_mi's cost build gin_ts2_mi (gin_ts2 +
# ../../../restore/feas/gin_ts2_winflags.diff + gin_ts2_mi.diff, built with NCCL_GIN_RESTORE_DEVICE against the mirror layer's
# headers; GIN_TS_MAN_MIRROR unset here, so the mirror WRITEs come from the LIBRARY's measurement mode, not from the
# driver). The library's measurement mode (NCCL_GIN_RESTORE_LOG_MEASURE=<ms> publishes the side table without Resume) picks
# the arm; the mirror arm uses NCCL_GIN_RESTORE_LOG_MEASURE_MIRROR (0|self|peer, rs_mirror_api.h). Arms:
#   off          NCCL_GIN_FAULT_POLICY=failfast (the macro build's fail-fast path; reported)
#   on           hold, LOG_MEASURE, LOG_MEASURE_LOG=1, MIRROR off, checksum off (the log-on base of the comparison)
#   mirror-self  on + NCCL_GIN_RESTORE_MIRROR=1, NCCL_GIN_RESTORE_LOG_MEASURE_MIRROR=self (the NIC loopback bound)
#   mirror-peer  on + NCCL_GIN_RESTORE_MIRROR=1, NCCL_GIN_RESTORE_LOG_MEASURE_MIRROR=peer (two bytes to the receiving node)
# Metrics: lat4k | lat256k | lat2m (3 000 iterations of one put + signal + flush) | bw256k (burst, one thread, 12
# iterations of 8 x 256 KiB + signal + flush) | bw2m (burst, one thread, 24 iterations of 8 x 2 MiB with GIN_TS_BURST_REUSE
# so the window stays 16 MiB; bandwidth = burst_K x bytes / p50). The base arm of every comparison is `on` (section 3:
# mirror-self, mirror-peer against on). mirror-self and mirror-peer are the judged arms; off is reported only.
#
# Safety, ports, management address, IPv4 masking and the leftover count are run_cost.sh's. Every NCCL_/GIN_ variable of
# the caller is dropped first.
#
# usage: run_cost_mi.sh <cell> <run-tag> <logdir>     (cell = cost_<metric>_<arm>_<node>)
# env: SUNNY_SSH (required), RS_SET (required), HCA_RAIN (mlx5_1), HCA_SUNNY (mlx5_0), LOG_MEASURE_MS (50), MIRROR_LANE
#   (268435456), MIRROR_SLOTS (2), POOL_MAX_MB (empty: the library's default) of the mirror arms. The integration
#   (2026-10-15) set the lane's default: the library breaks a put larger than L and puts the cursor back to 0 once it is
#   past L/2 at each helper step (about 1 ms), so L must hold the largest put (2 MiB) and the mirror bytes of a few helper
#   steps at line rate (256 MiB: L/2 holds about 10 ms of line rate); an arm counts only with "mirror summary" broken=0
#   (the device's breaks counted in it) and max_live_bytes > 0. Pool per process: 1 ward x S x (n - 1) lanes x L =
#   512 MiB with the defaults on two ranks. The library is ~/rs-bundle/<RS_SET>/lib/mip, the driver
#   ~/rs-bundle/<RS_SET>/mitest/gin_ts2_mi.
# files in <logdir>: <cell>_<tag>_r0.kv/_r1.kv/_r0.log/_r1.log, <cell>_<tag>_lat_raw.csv.gz (lat), <cell>_<tag>_meta.txt.
set -u
CELL=${1:?cell}; TAG=${2:?run tag}; LOGDIR=${3:?logdir}
for v in $(env | sed -n 's/^\(\(NCCL\|GIN\)_[A-Za-z0-9_]*\)=.*/\1/p'); do unset "$v"; done
SUNNY_SSH=${SUNNY_SSH:?set SUNNY_SSH}
SUNNY_HOST=${SUNNY_SSH#*@}
HCA_RAIN=${HCA_RAIN:-mlx5_1}; HCA_SUNNY=${HCA_SUNNY:-mlx5_0}
LOG_MEASURE_MS=${LOG_MEASURE_MS:-50}
IFS=_ read -r _ METRIC ARM RX <<< "$CELL"
case "$METRIC" in
  lat4k)   MODE=lat;   ITERS=3000; BYTES=4096;    XENV="" ;;
  lat256k) MODE=lat;   ITERS=3000; BYTES=262144;  XENV="" ;;
  lat2m)   MODE=lat;   ITERS=3000; BYTES=2097152; XENV="" ;;
  bw256k)  MODE=burst; ITERS=12;   BYTES=262144;  XENV="GIN_TS_TX_BLOCKS=1 GIN_TS_TX_THREADS=1 GIN_TS_BURST_K=8 GIN_TS_AGG=1" ;;
  bw2m)    MODE=burst; ITERS=24;   BYTES=2097152; XENV="GIN_TS_TX_BLOCKS=1 GIN_TS_TX_THREADS=1 GIN_TS_BURST_K=8 GIN_TS_AGG=1 GIN_TS_BURST_REUSE=1" ;;
  *) echo "bad metric in $CELL" >&2; exit 2 ;;
esac
RS_SET=${RS_SET:-}
. "$(cd "$(dirname "$0")" && pwd)/rs_set_mi.sh"
rs_set_check || exit 2
RSB=$HOME/rs-bundle/$RS_SET
LIB=$RSB/lib/mip; BIN=$RSB/mitest/gin_ts2_mi
MEAS="NCCL_GIN_FAULT_POLICY=hold NCCL_GIN_RESTORE=1 NCCL_GIN_RESTORE_LOG_MEASURE=$LOG_MEASURE_MS NCCL_GIN_RESTORE_LOG_MEASURE_LOG=1 NCCL_GIN_RESTORE_CHECKSUM=off"
MIRROR_LANE=${MIRROR_LANE:-268435456}; MIRROR_SLOTS=${MIRROR_SLOTS:-2}
MIR="${MIRROR_LANE:+NCCL_GIN_RESTORE_MIRROR_LANE=$MIRROR_LANE} ${MIRROR_SLOTS:+NCCL_GIN_RESTORE_MIRROR_SLOTS=$MIRROR_SLOTS} ${POOL_MAX_MB:+NCCL_GIN_RESTORE_MIRROR_POOL_MAX_MB=$POOL_MAX_MB}"
case "$ARM" in
  off)         RSENV="NCCL_GIN_FAULT_POLICY=failfast" ;;
  on)          RSENV="$MEAS NCCL_GIN_RESTORE_MIRROR=0" ;;
  mirror-self) RSENV="$MEAS NCCL_GIN_RESTORE_MIRROR=1 NCCL_GIN_RESTORE_LOG_MEASURE_MIRROR=self $MIR" ;;
  mirror-peer) RSENV="$MEAS NCCL_GIN_RESTORE_MIRROR=1 NCCL_GIN_RESTORE_LOG_MEASURE_MIRROR=peer $MIR" ;;
  *) echo "bad arm in $CELL" >&2; exit 2 ;;
esac
case "$RX" in rain) TX=sunny ;; sunny) TX=rain ;; *) echo "bad node in $CELL" >&2; exit 2 ;; esac
[ -x "$BIN" ] || { echo "missing $BIN on rain" >&2; exit 1; }
[ -f "$LIB/libnccl.so.2" ] || { echo "missing $LIB/libnccl.so.2 on rain" >&2; exit 1; }
umask 077
WORK=$(mktemp -d /tmp/mi_cost.XXXXXX)
RT=/tmp/mi_cost_$$_$RANDOM
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
rm -f "$LOGDIR/${stem}"_*
for r in 0 1; do
  [ -f "$WORK/r$r.kv" ] && sed "$MASK" "$WORK/r$r.kv" > "$LOGDIR/${stem}_r$r.kv"
  [ -f "$WORK/r$r.log" ] && sed "$MASK" "$WORK/r$r.log" > "$LOGDIR/${stem}_r$r.log"
done
[ -f "$WORK/lat_raw.csv" ] && gzip -c "$WORK/lat_raw.csv" > "$LOGDIR/${stem}_lat_raw.csv.gz"
rc() { tr -d '\n' < "$WORK/r$1.rc" 2>/dev/null || echo none; }
LIB_MD5=$(md5sum < "$LIB/libnccl.so.2" 2>/dev/null | cut -c1-32); DRIVER_MD5=$(md5sum < "$BIN" 2>/dev/null | cut -c1-32)
echo "cell=$CELL tag=$TAG metric=$METRIC arm=$ARM rx=$RX tx=$TX mode=$MODE iters=$ITERS bytes=$BYTES lib=mip \
bin=$(basename "$BIN") log_measure_ms=$LOG_MEASURE_MS rc_r0=$(rc 0) rc_r1=$(rc 1) left=$LEFT hca_rain=$HCA_RAIN \
hca_sunny=$HCA_SUNNY gid_rain=$GID_R gid_sunny=$GID_S port=$PORT port_tries=$PORT_TRIES rdv_nonce_set=1 qpwatch_ms=0 \
mirror_lane=${MIRROR_LANE:-} mirror_slots=${MIRROR_SLOTS:-} runner=costmi \
wall_s=$(awk -v a="$T0" -v b="$T1" 'BEGIN{printf "%.1f", b - a}') rs_set=$RS_SET lib_md5=${LIB_MD5:-none} \
driver_md5=${DRIVER_MD5:-none}" > "$LOGDIR/${stem}_meta.txt"
echo "[$stem] rc r0=$(rc 0) r1=$(rc 1) left=$LEFT :: $(grep -ho 'lat_p50_us=[0-9.]*\|exit=[0-9]*\|man_error=[^ ]*' "$WORK/r0.kv" 2>/dev/null | tr '\n' ' ')" >&2
exit 0
