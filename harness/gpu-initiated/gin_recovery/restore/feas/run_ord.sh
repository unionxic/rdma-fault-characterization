#!/usr/bin/env bash
# run_ord.sh - one run of gin-restore's normal-path comparison of strict and relaxed windows (EXPERIMENT.md 9.15.6; DRAFT
# stage, never scored): gin_ts2 (gin-remaining's driver + feas/gin_ts2_winflags.diff) on the deployed hk libnccl, rank 0
# sends, rank 1 receives. Called by hold_feas.sh inside ../../../common/cluster_run.sh. Each process is bounded by
# timeout -s KILL and by gin_ts2's own watchdog; nothing is killed here (the runner waits for its two processes).
# usage: run_ord.sh <cell> <run-tag> <logdir>
#   cells: ord_<lat4k|lat256k|bw256k>_<strict|relaxed>_<rain|sunny>: the named node receives (rank 1), the other node sends
#          (rank 0, which also listens for the driver's rendezvous)
#     lat4k    lat mode, 3 000 iterations of one 4 KiB put + flush (gpu-detect's lat_4k)
#     lat256k  lat mode, 3 000 iterations of one 256 KiB put + flush
#     bw256k   burst mode, one thread, 200 iterations of 16 puts of 256 KiB + signal + flush (bandwidth = 4 MiB / p50)
#     strict   GIN_TS_WIN_STRICT=1 on both ranks: both windows NCCL_WIN_COLL_SYMMETRIC | NCCL_WIN_STRICT_ORDERING
#     relaxed  no GIN_TS_WIN_STRICT: NCCL_WIN_COLL_SYMMETRIC only (NCCL asks RO for the window MRs when ro_requested=1 in
#              the driver's kv: NCCL_IB_PCI_RELAXED_ORDERING unset = 2 and ibv_reg_mr_iova2@IBVERBS_1.8 present)
#   pinned (EXPERIMENT.md 9.15.6, review K6): wait blocking, gap 0, NCCL_DEBUG=WARN, NCCL_IB_TIMEOUT=14, transparent recovery
#   on, QP watch off, NCCL_IB_PCI_RELAXED_ORDERING unset, queue depth NCCL's default, burst: one block of one thread,
#   K=16, GIN_TS_AGG=1 (the 16 puts are rung with the signal)
# files in <logdir>: <cell>_<tag>_r0.kv, _r1.kv, _r0.log, _r1.log (IPv4 addresses masked anyway; the originals on the
#   nodes are deleted), <cell>_<tag>_meta.txt (left: processes of this run still there after both ended, by the run's
#   unique tag; gin_ts2_before/after: every process named gin_ts2 on both nodes, information only)
# env: SUNNY_SSH (required), HCA_RAIN (mlx5_1), HCA_SUNNY (mlx5_0), ORDBIN ($HOME/rs-bundle/ord/gin_ts2),
#      ORDLIB ($HOME/gi-bundle/gin_ts2/hk: gpu-detect's deployed hk bundle, read only)
set -u
CELL=${1:?cell}; TAG=${2:?run tag}; LOGDIR=${3:?logdir}
unset GIN_TS_WIN_STRICT NCCL_IB_PCI_RELAXED_ORDERING GIN_TS_AGG GIN_TS_QDEPTH   # pinned below, never inherited
SUNNY_SSH=${SUNNY_SSH:?set SUNNY_SSH}
SUNNY_HOST=${SUNNY_SSH#*@}
HCA_RAIN=${HCA_RAIN:-mlx5_1}; HCA_SUNNY=${HCA_SUNNY:-mlx5_0}
BIN=${ORDBIN:-$HOME/rs-bundle/ord/gin_ts2}
LIB=${ORDLIB:-$HOME/gi-bundle/gin_ts2/hk}
[ -x "$BIN" ] && [ -f "$LIB/libnccl.so.2" ] || { echo "missing $BIN or $LIB/libnccl.so.2 on rain" >&2; exit 1; }
IFS=_ read -r _ METRIC ARM RX <<< "$CELL"
case "$METRIC:$ARM:$RX" in lat4k:*|lat256k:*|bw256k:*) ;; *) echo "bad cell $CELL" >&2; exit 2 ;; esac
case "$ARM" in strict) STRICT=1 ;; relaxed) STRICT=0 ;; *) echo "bad cell $CELL" >&2; exit 2 ;; esac
case "$RX" in rain) TX=sunny ;; sunny) TX=rain ;; *) echo "bad cell $CELL" >&2; exit 2 ;; esac
case "$METRIC" in
  lat4k)   MODE=lat;   ITERS=3000; BYTES=4096;   XENV="" ;;
  lat256k) MODE=lat;   ITERS=3000; BYTES=262144; XENV="" ;;
  bw256k)  MODE=burst; ITERS=200;  BYTES=262144; XENV="GIN_TS_TX_BLOCKS=1 GIN_TS_TX_THREADS=1 GIN_TS_BURST_K=16 GIN_TS_AGG=1" ;;
esac
umask 077
WORK=$(mktemp -d /tmp/rs_ord.XXXXXX)
RT=/tmp/rs_ord_$$_$RANDOM            # sunny-side file prefix of this run
cleanup() { ssh -n "$SUNNY_SSH" "rm -rf $RT.*" 2>/dev/null || true; rm -rf "$WORK"; }
trap cleanup EXIT
D=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=../../remaining/portpick.sh
. "$D/../../remaining/portpick.sh"
GID_PROBE='d=/sys/class/infiniband/$1/ports/1
for g in $(ls "$d/gids" | sort -n); do
  [ "$(cat "$d/gid_attrs/types/$g" 2>/dev/null)" = "RoCE v2" ] || continue
  case "$(cat "$d/gids/$g")" in 0000:0000:0000:0000:0000:ffff:1e00:00*) echo "$g"; exit 0;; esac
done; exit 1'
GID_R=$(bash -c "$GID_PROBE" _ "$HCA_RAIN") || { echo "no GID on rain" >&2; exit 1; }
GID_S=$(ssh -n "$SUNNY_SSH" bash -c "'$GID_PROBE'" _ "$HCA_SUNNY") || { echo "no GID on sunny" >&2; exit 1; }
RAIN_MGMT=$(ip -4 route get "$SUNNY_HOST" 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p' | head -1)
[ -n "$RAIN_MGMT" ] || { echo "cannot find rain's management address" >&2; exit 1; }
if [ "$TX" = rain ]; then R0_ADDR=$RAIN_MGMT; else R0_ADDR=$SUNNY_HOST; fi   # rank 0 listens: the sender's node
WD=45                                  # gin_ts2's host watchdog (s)
TMO=$(( WD + 20 ))                     # the outer timeout
pick_port
NONCE=$(new_nonce)
hca() { [ "$1" = rain ] && echo "$HCA_RAIN" || echo "$HCA_SUNNY"; }
gidx() { [ "$1" = rain ] && echo "$GID_R" || echo "$GID_S"; }
NENV="NCCL_DEBUG=WARN NCCL_SOCKET_IFNAME=eno1 NCCL_GIN_TYPE=3 NCCL_GIN_ENABLE=1 \
NCCL_IB_TIMEOUT=14 NCCL_GIN_FAULT_CLASSIFY=1 NCCL_GIN_FAULT_RECOVERY=1 NCCL_GIN_FAULT_TRANSPARENT=1 \
NCCL_GIN_TS_QPWATCH_MS=0 GIN_ABORT_WATCHDOG_S=15 GIN_RDV_NONCE=$NONCE LD_LIBRARY_PATH=$LIB \
$( [ "$STRICT" = 1 ] && echo GIN_TS_WIN_STRICT=1 ) $XENV"
# start <node> <rank>: background process; PIDS[rank]; the exit code goes to $WORK/r<rank>.rc
declare -A PIDS
start() {
  local node=$1 r=$2 envs
  envs="$NENV NCCL_IB_HCA=$(hca "$node") NCCL_IB_GID_INDEX=$(gidx "$node")"
  local args="$r $R0_ADDR $PORT $ITERS $BYTES blocking $MODE 8 $WD"
  # a private working directory per process and no core files (not in gpu-detect's bundle; review K12)
  if [ "$node" = rain ]; then
    ( mkdir -p "$WORK/cwd$r" && cd "$WORK/cwd$r" && ulimit -c 0 && env $envs timeout -s KILL "$TMO" "$BIN" $args "$WORK/r$r.kv" 0 \
        > "$WORK/r$r.log" 2>&1; echo $? > "$WORK/r$r.rc" ) &
  else
    ssh -n "$SUNNY_SSH" "mkdir -p $RT.cwd$r && cd $RT.cwd$r && ulimit -c 0 && $envs timeout -s KILL $TMO $BIN $args $RT.r$r.kv 0 \
> $RT.r$r.log 2>&1; echo \$?" > "$WORK/r$r.rc" 2>/dev/null &
  fi
  PIDS[$r]=$!
}
snapgpu() {  # snapgpu <tag>
  nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader > "$WORK/gpu_rain_$1.txt" 2>&1
  ssh -n "$SUNNY_SSH" "nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader" > "$WORK/gpu_sunny_$1.txt" 2>&1
}
nts() { echo "$(pgrep -x gin_ts2 2>/dev/null | wc -l)/$(ssh -n "$SUNNY_SSH" 'pgrep -x gin_ts2 | wc -l' 2>/dev/null)"; }
TS_BEFORE=$(nts)
snapgpu before
T0=$(date +%s.%N)
start "$TX" 0
sleep 1
start "$RX" 1
wait "${PIDS[0]}"; wait "${PIDS[1]}"
T1=$(date +%s.%N)
snapgpu after
# this run's processes still there (counting only, by the run's unique kv paths; a pattern that does not match the shell)
LEFT=$( { pgrep -f "[${WORK:0:1}]${WORK:1}/r[01].kv" 2>/dev/null; ssh -n "$SUNNY_SSH" "pgrep -f '[${RT:0:1}]${RT:1}.r[01].kv'"; } 2>/dev/null | wc -l)
TS_AFTER=$(nts)
for r in 0 1; do
  node=$TX; [ "$r" = 1 ] && node=$RX
  if [ "$node" = sunny ]; then
    scp -q "$SUNNY_SSH:$RT.r$r.kv" "$WORK/r$r.kv" 2>/dev/null || true
    scp -q "$SUNNY_SSH:$RT.r$r.log" "$WORK/r$r.log" 2>/dev/null || true
  fi
done
mkdir -p "$LOGDIR"
stem="${CELL}_${TAG}"
MASK='s/[0-9]\{1,3\}\.[0-9]\{1,3\}\.[0-9]\{1,3\}\.[0-9]\{1,3\}/<ip>/g'
for r in 0 1; do
  [ -f "$WORK/r$r.kv" ] && sed "$MASK" "$WORK/r$r.kv" > "$LOGDIR/${stem}_r$r.kv"
  [ -f "$WORK/r$r.log" ] && sed "$MASK" "$WORK/r$r.log" > "$LOGDIR/${stem}_r$r.log"
done
for n in rain sunny; do for t in before after; do cp "$WORK/gpu_${n}_$t.txt" "$LOGDIR/${stem}_gpu_${n}_$t.txt"; done; done
rc() { tr -d '\n' < "$WORK/r$1.rc" 2>/dev/null || echo none; }
echo "cell=$CELL tag=$TAG metric=$METRIC arm=$ARM win_strict=$STRICT rx=$RX tx=$TX mode=$MODE iters=$ITERS bytes=$BYTES \
burst=$(echo "$XENV" | tr ' ' '+') hca_rain=$HCA_RAIN hca_sunny=$HCA_SUNNY gid_rain=$GID_R gid_sunny=$GID_S \
rc_r0=$(rc 0) rc_r1=$(rc 1) left=$LEFT gin_ts2_before=$TS_BEFORE gin_ts2_after=$TS_AFTER port=$PORT port_tries=$PORT_TRIES rdv_nonce_set=1 \
qpwatch_ms=0 wall_s=$(awk -v a="$T0" -v b="$T1" 'BEGIN{printf "%.1f", b - a}') bin=$BIN lib=$LIB" > "$LOGDIR/${stem}_meta.txt"
echo "[$stem] rc r0=$(rc 0) r1=$(rc 1) left=$LEFT :: $(grep -ho 'win_flags=[0-9a-fx]*\|ro_requested=[01]\|lat_p50_us=[0-9.]*\|exit=[0-9]*' \
  "$WORK/r0.kv" 2>/dev/null | tr '\n' ' ')" >&2
exit 0
