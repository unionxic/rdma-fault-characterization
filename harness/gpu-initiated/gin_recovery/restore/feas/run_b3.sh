#!/usr/bin/env bash
# run_b3.sh - one B3 cell of gin-restore's feasibility tests (EXPERIMENT.md 9.15.3): rs_drain_test on rain and sunny.
# Called by hold_feas.sh inside ../../../common/cluster_run.sh. No NCCL. Each process is bounded by timeout -s KILL and by
# its own watchdog; the hog process ends by itself when this runner creates its stop file; nothing is killed here.
# usage: run_b3.sh <cell> <iters> <logdir>
#   cells: b3_x_<rain|sunny>_<ro|so>  cross-node: the named node is the responder (GPU window), the other node writes
#          b3_s_<rain|sunny>_<ro|so>  same node: the writer is another process on the same node, GPU and HCA
#          b3_h_<rain|sunny>_<ro|so>  cross-node, plus a memory-bound hog process on the responder's GPU
#   The responder always listens for the control connection (TCP, nonce-verified, port 29000-30999 picked free on both
#   nodes by ../../remaining/portpick.sh); the writer connects to the responder's management address, or to 127.0.0.1.
# files in <logdir>: <cell>_resp.kv/.log, <cell>_writer.kv/.log, <cell>_hog.kv/.log (h cells), <cell>_topo_<node>.txt
#   (nvidia-smi topo -m), <cell>_gpu_<node>_<before|after>.txt (compute apps), <cell>_meta.txt
# env: SUNNY_SSH (required), HCA_RAIN (mlx5_1), HCA_SUNNY (mlx5_0), B3BIN ($HOME/rs-bundle/b3/rs_drain_test),
#      RS_LAST_KB (passed to both sides if set; see rs_drain_test.cu)
set -u
CELL=${1:?cell}; ITERS=${2:?iters}; LOGDIR=${3:?logdir}
SUNNY_SSH=${SUNNY_SSH:?set SUNNY_SSH}
SUNNY_HOST=${SUNNY_SSH#*@}
HCA_RAIN=${HCA_RAIN:-mlx5_1}; HCA_SUNNY=${HCA_SUNNY:-mlx5_0}
BIN=${B3BIN:-$HOME/rs-bundle/b3/rs_drain_test}
[ -x "$BIN" ] || { echo "missing $BIN on rain" >&2; exit 1; }
IFS=_ read -r _ MODE NODE ORDER <<< "$CELL"
case "$MODE:$NODE:$ORDER" in [xsh]:rain:ro|[xsh]:rain:so|[xsh]:sunny:ro|[xsh]:sunny:so) ;; *) echo "bad cell $CELL" >&2; exit 2 ;; esac
umask 077
WORK=$(mktemp -d /tmp/rs_b3.XXXXXX)
RT=/tmp/rs_b3_$$_$RANDOM            # sunny-side file prefix of this cell
cleanup() { ssh -n "$SUNNY_SSH" "rm -f $RT.*" 2>/dev/null || true; rm -rf "$WORK"; }
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
CELL_S=$(( ITERS / 100 + 60 ))       # the responder's soft bound (result INCOMPLETE)
WD=$(( CELL_S + 30 ))                # the programs' hard watchdog
TMO=$(( WD + 15 ))                   # the outer timeout
pick_port
NONCE=$(new_nonce)
# where each role runs
RESP=$NODE
if [ "$MODE" = s ]; then WRITER=$NODE; else [ "$NODE" = rain ] && WRITER=sunny || WRITER=rain; fi
if [ "$RESP" = rain ]; then RESP_ADDR=$RAIN_MGMT; else RESP_ADDR=$SUNNY_HOST; fi
[ "$MODE" = s ] && RESP_ADDR=127.0.0.1
hca() { [ "$1" = rain ] && echo "$HCA_RAIN" || echo "$HCA_SUNNY"; }
gidx() { [ "$1" = rain ] && echo "$GID_R" || echo "$GID_S"; }
# start <node> <name> <args...>: background process on <node>; PIDS[name]; sunny: the exit code goes to $WORK/<name>.rc
declare -A PIDS
start() {
  local node=$1 name=$2; shift 2
  local envs="RS_RDV_NONCE=$NONCE RS_WATCHDOG_S=$WD RS_CELL_S=$CELL_S${RS_LAST_KB:+ RS_LAST_KB=$RS_LAST_KB}"
  if [ "$node" = rain ]; then
    ( env $envs timeout -s KILL "$TMO" "$BIN" "$WORK/$name.kv" "$@" > "$WORK/$name.log" 2>&1; echo $? > "$WORK/$name.rc" ) &
  else
    ssh -n "$SUNNY_SSH" "$envs timeout -s KILL $TMO $BIN $RT.$name.kv $* > $RT.$name.log 2>&1; echo \$?" > "$WORK/$name.rc" 2>/dev/null &
  fi
  PIDS[$name]=$!
}
snapgpu() {  # snapgpu <tag>
  nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader > "$WORK/gpu_rain_$1.txt" 2>&1
  ssh -n "$SUNNY_SSH" "nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader" > "$WORK/gpu_sunny_$1.txt" 2>&1
}
nvidia-smi topo -m > "$WORK/topo_rain.txt" 2>&1
ssh -n "$SUNNY_SSH" "nvidia-smi topo -m" > "$WORK/topo_sunny.txt" 2>&1
snapgpu before
T0=$(date +%s.%N)
STOPF=/tmp/rs_b3_hogstop_$$_$RANDOM
if [ "$MODE" = h ]; then
  if [ "$RESP" = rain ]; then rm -f "$STOPF"; else ssh -n "$SUNNY_SSH" "rm -f $STOPF"; fi
  start "$RESP" hog hog "$CELL_S" "$STOPF"
  sleep 2
fi
start "$RESP" resp resp "$(hca "$RESP")" "$(gidx "$RESP")" "$ORDER" "$ITERS" "listen:$PORT"
sleep 1
start "$WRITER" writer writer "$(hca "$WRITER")" "$(gidx "$WRITER")" "$ORDER" "$ITERS" "connect:$RESP_ADDR:$PORT"
wait "${PIDS[resp]}"; wait "${PIDS[writer]}"
if [ "$MODE" = h ]; then
  if [ "$RESP" = rain ]; then touch "$STOPF"; else ssh -n "$SUNNY_SSH" "touch $STOPF"; fi
  wait "${PIDS[hog]}"
  if [ "$RESP" = rain ]; then rm -f "$STOPF"; else ssh -n "$SUNNY_SSH" "rm -f $STOPF"; fi
fi
T1=$(date +%s.%N)
snapgpu after
for name in resp writer hog; do
  node=$RESP; [ "$name" = writer ] && node=$WRITER
  [ -n "${PIDS[$name]:-}" ] || continue
  if [ "$node" = sunny ]; then
    scp -q "$SUNNY_SSH:$RT.$name.kv" "$WORK/$name.kv" 2>/dev/null || true
    scp -q "$SUNNY_SSH:$RT.$name.log" "$WORK/$name.log" 2>/dev/null || true
  fi
done
mkdir -p "$LOGDIR"
for f in resp.kv resp.log writer.kv writer.log hog.kv hog.log; do [ -f "$WORK/$f" ] && cp "$WORK/$f" "$LOGDIR/${CELL}_$f"; done
for n in rain sunny; do cp "$WORK/topo_$n.txt" "$LOGDIR/${CELL}_topo_$n.txt"
  for t in before after; do cp "$WORK/gpu_${n}_$t.txt" "$LOGDIR/${CELL}_gpu_${n}_$t.txt"; done; done
rc() { tr -d '\n' < "$WORK/$1.rc" 2>/dev/null || echo none; }
echo "cell=$CELL mode=$MODE responder=$RESP writer=$WRITER order=$ORDER iters=$ITERS hca_rain=$HCA_RAIN hca_sunny=$HCA_SUNNY \
gid_rain=$GID_R gid_sunny=$GID_S rc_resp=$(rc resp) rc_writer=$(rc writer) rc_hog=$( [ "$MODE" = h ] && rc hog || echo none) \
port=$PORT port_tries=$PORT_TRIES rdv_nonce_set=1 cell_s=$CELL_S timeout_s=$TMO last_kb=${RS_LAST_KB:-1024} \
wall_s=$(awk -v a="$T0" -v b="$T1" 'BEGIN{printf "%.1f", b - a}') bin=$BIN" > "$LOGDIR/${CELL}_meta.txt"
echo "[$CELL] rc resp=$(rc resp) writer=$(rc writer) :: $(grep -ho 'result=[A-Z_]*\|setup_error=[^ ]*\|nic_error=[^ ]*' \
  "$WORK"/*.kv 2>/dev/null | tr '\n' ' ')" >&2
exit 0
