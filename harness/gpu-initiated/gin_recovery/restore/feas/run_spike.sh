#!/usr/bin/env bash
# run_spike.sh - one trial of gin-restore's feasibility tests B1 and B2 (EXPERIMENT.md 9.15.2, 9.15.4) with rs_spike and the
# rsx libnccl (hw + rs_spike.diff). Called by hold_feas.sh inside ../../../common/cluster_run.sh. Every process is bounded
# by timeout -s KILL (and its own watchdog); nothing is killed here. Every run has host RMA and RAS off and NCCL_DEBUG=WARN.
# usage: run_spike.sh <cell> <trial> <logdir>
#   b1         rec: rank 0 on rain, rank 1 on sunny, both record their init transcript (NCCL_GIN_RESTORE_RECORD) and end;
#              rep1: a spare on sunny replays rank 1's transcript alone (NCCL_GIN_RESTORE_REPLAY, RS_SPARE=1) under strace;
#              rep0: the same on rain for rank 0; neg: two replays on sunny of a cut copy and of a copy with one size field
#              changed (both must fail). The transcripts hold management addresses: they stay in the nodes' /tmp (mode
#              0600) and are deleted at the end of the trial (also on an error); only counts leave the node.
#   b1_live    rec with RS_HOLD_S=30: while both ranks hold, a spare on sunny replays rank 1's transcript under strace
#   b2_inter   four ranks, rain 0, 2 and sunny 1, 3 (NCCL_MULTI_RANK_GPU_ENABLE=1), report lines only (NCCL_GIN_RESTORE_REPORT)
#   b2_consec  four ranks, rain 0, 1 and sunny 2, 3 (control), report lines only
# files in <logdir>: <stem>_<part>_r<rank>.kv/.log (part rec, rep1, rep0, neg_cut, neg_field, live, rank), <stem>_<part>_strace.txt
#   (counts only), <stem>_meta.txt
# env: SUNNY_SSH (required), APP ($HOME/rs-bundle/app/rs_spike), LIBDIR ($HOME/rs-bundle/rsx)
set -u
CELL=${1:?cell}; TRIAL=${2:?trial}; LOGDIR=${3:?logdir}
SUNNY_SSH=${SUNNY_SSH:?set SUNNY_SSH}
SUNNY_HOST=${SUNNY_SSH#*@}
APP=${APP:-$HOME/rs-bundle/app/rs_spike}
LIBDIR=${LIBDIR:-$HOME/rs-bundle/rsx}
[ -x "$APP" ] && [ -f "$LIBDIR/libnccl.so.2" ] || { echo "missing $APP or $LIBDIR on rain" >&2; exit 1; }
case "$CELL" in b1|b1_live|b2_inter|b2_consec) ;; *) echo "bad cell $CELL" >&2; exit 2 ;; esac
WORK=$(mktemp -d /tmp/rs_sp.XXXXXX)
RT=/tmp/rs_sp_$$_$RANDOM            # this trial's file prefix on both nodes (transcripts, kv, logs)
D=$(cd "$(dirname "$0")" && pwd)
stem="${CELL}_t${TRIAL}"
# shellcheck source=../../remaining/portpick.sh
. "$D/../../remaining/portpick.sh"
cleanup() { rm -f "$RT".*; ssh -n "$SUNNY_SSH" "rm -f $RT.*" 2>/dev/null || true; rm -rf "$WORK"; }
trap cleanup EXIT
RAIN_MGMT=$(ip -4 route get "$SUNNY_HOST" 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p' | head -1)
[ -n "$RAIN_MGMT" ] || { echo "cannot find rain's management address" >&2; exit 1; }
GID_PROBE='d=/sys/class/infiniband/$1/ports/1
for g in $(ls "$d/gids" | sort -n); do
  [ "$(cat "$d/gid_attrs/types/$g" 2>/dev/null)" = "RoCE v2" ] || continue
  case "$(cat "$d/gids/$g")" in 0000:0000:0000:0000:0000:ffff:1e00:00*) echo "$g"; exit 0;; esac
done; exit 1'
GID_R=$(bash -c "$GID_PROBE" _ mlx5_1) || { echo "no GID on rain" >&2; exit 1; }
GID_S=$(ssh -n "$SUNNY_SSH" bash -c "'$GID_PROBE'" _ mlx5_0) || { echo "no GID on sunny" >&2; exit 1; }
HKEY=$(od -An -N8 -tx8 /dev/urandom | tr -d ' \n')   # the report hashes' key: in the processes' environment only
STRACE_S=$(ssh -n "$SUNNY_SSH" "command -v strace >/dev/null && echo 1 || echo 0" 2>/dev/null)
STRACE_R=$(command -v strace >/dev/null && echo 1 || echo 0)
BASE="NCCL_DEBUG=WARN NCCL_DEBUG_SUBSYS=INIT,NET NCCL_SOCKET_IFNAME=eno1 NCCL_GIN_TYPE=3 NCCL_GIN_ENABLE=1 NCCL_IB_TIMEOUT=14 \
NCCL_GIN_FAULT_CLASSIFY=1 NCCL_GIN_FAULT_RECOVERY=1 NCCL_GIN_FAULT_TRANSPARENT=1 NCCL_NUM_RMA_CTX=0 NCCL_RMA_DISABLE=1 \
NCCL_RAS_ENABLE=0 NCCL_GIN_RESTORE_HKEY=$HKEY RS_WATCHDOG_S=60 LD_LIBRARY_PATH=$LIBDIR"
node_env() { [ "$1" = rain ] && echo "NCCL_IB_HCA=mlx5_1 NCCL_IB_GID_INDEX=$GID_R" || echo "NCCL_IB_HCA=mlx5_0 NCCL_IB_GID_INDEX=$GID_S"; }
# strace counts, computed on the node from the raw trace, which is then deleted (it holds addresses)
STRACE_PY='import re,sys,collections
fdt={}; c=collections.Counter()
for ln in open(sys.argv[1], errors="replace"):
  m=re.match(r"\s*\d+\s+(socket|connect|accept4?)\((.*)", ln)
  if not m: continue
  call,rest=m.group(1),m.group(2)
  if call=="socket":
    r=re.search(r"=\s*(\d+)\s*$", ln)
    if r: fdt[r.group(1)]=("dgram" if "SOCK_DGRAM" in rest else "stream" if "SOCK_STREAM" in rest else "other")
    continue
  if call.startswith("accept"): c["accept"]+=1; continue
  fd=rest.split(",")[0].strip()
  if "AF_UNIX" in rest or "AF_LOCAL" in rest: c["unix_connect"]+=1; continue
  if "AF_INET" in rest:
    loop=("127." in rest) or ("\"::1\"" in rest)
    c["inet_connect_loop" if loop else "inet_connect_nonloop_"+fdt.get(fd,"unknown")]+=1
    continue
  c["other_connect"]+=1
keys=["inet_connect_nonloop_stream","inet_connect_nonloop_dgram","inet_connect_nonloop_other","inet_connect_nonloop_unknown","inet_connect_loop","unix_connect","other_connect","accept"]
print(" ".join("%s=%d"%(k,c[k]) for k in keys)+" inet_connect_nonloop_total=%d"%sum(c[k] for k in keys[:4]))'
# launch <node> <name> <rank> <nranks> <extra env> [strace]: background; PIDS[name]; rc in $WORK/<name>.rc
declare -A PIDS
launch() {
  local node=$1 name=$2 r=$3 n=$4 extra=$5 tr=${6:-0} env
  env="$BASE $(node_env "$node") $extra"
  local cmd="timeout -s KILL 75 $APP $r $n $RAIN_MGMT $PORT $RT.$name.kv"
  local st=""
  if [ "$tr" = 1 ]; then st="strace -f -qq -e trace=socket,connect,accept,accept4 -o $RT.$name.strace"; fi
  if [ "$node" = rain ]; then
    ( if [ "$tr" = 1 ] && [ "$STRACE_R" = 1 ]; then env $env $st $cmd; else env $env $cmd; fi > "$RT.$name.log" 2>&1
      echo $? > "$WORK/$name.rc"
      if [ -f "$RT.$name.strace" ]; then python3 -c "$STRACE_PY" "$RT.$name.strace" > "$WORK/$name.stracecount"; rm -f "$RT.$name.strace"; fi ) &
  else
    local use=0; [ "$tr" = 1 ] && [ "$STRACE_S" = 1 ] && use=1
    ssh -n "$SUNNY_SSH" "if [ $use = 1 ]; then env $env $st $cmd; else env $env $cmd; fi > $RT.$name.log 2>&1; echo \$? > $RT.$name.rc; \
if [ -f $RT.$name.strace ]; then python3 -c '$STRACE_PY' $RT.$name.strace > $RT.$name.stracecount; rm -f $RT.$name.strace; fi" &
  fi
  PIDS[$name]=$!
}
fetch() {  # fetch <node> <name>: kv, log, rc and strace counts into $WORK
  local node=$1 name=$2
  if [ "$node" = rain ]; then cp "$RT.$name.kv" "$WORK/$name.kv" 2>/dev/null; cp "$RT.$name.log" "$WORK/$name.log" 2>/dev/null
  else
    for f in kv log rc stracecount; do scp -q "$SUNNY_SSH:$RT.$name.$f" "$WORK/$name.$f" 2>/dev/null || true; done
  fi
}
rcof() { tr -d '\n' < "$WORK/$1.rc" 2>/dev/null || echo none; }
pick_port
T0=$(date +%s.%N)
PARTS=""
run_rec() {  # run_rec <part> <hold_s>: rank 0 rain, rank 1 sunny, both record
  local part=$1 hold=$2 nonce
  nonce=$(new_nonce)
  launch sunny "${part}_r1" 1 2 "RS_RDV_NONCE=$nonce RS_HOLD_S=$hold NCCL_GIN_RESTORE_RECORD=$RT.tr1"
  launch rain "${part}_r0" 0 2 "RS_RDV_NONCE=$nonce RS_HOLD_S=$hold NCCL_GIN_RESTORE_RECORD=$RT.tr0"
  PARTS="$PARTS ${part}_r0:rain ${part}_r1:sunny"
}
case "$CELL" in
  b1)
    run_rec rec 0
    wait "${PIDS[rec_r0]}"; wait "${PIDS[rec_r1]}"
    TR0=$(stat -c %s "$RT.tr0" 2>/dev/null || echo 0); TR1=$(ssh -n "$SUNNY_SSH" "stat -c %s $RT.tr1 2>/dev/null || echo 0")
    launch sunny rep1 1 2 "RS_SPARE=1 NCCL_GIN_RESTORE_REPLAY=$RT.tr1" 1; wait "${PIDS[rep1]}"
    launch rain rep0 0 2 "RS_SPARE=1 NCCL_GIN_RESTORE_REPLAY=$RT.tr0" 1; wait "${PIDS[rep0]}"
    # negative controls: a cut copy, and a copy whose first entry's element-size field (bytes 32..39 of the first entry
    # header, which starts after the 24-byte file header and the 128-byte commId) is changed
    ssh -n "$SUNNY_SSH" "head -c \$(( \$(stat -c %s $RT.tr1) / 2 )) $RT.tr1 > $RT.trcut && chmod 600 $RT.trcut && \
python3 -c 'import sys; b=bytearray(open(sys.argv[1],\"rb\").read()); b[152+32]^=0x10; open(sys.argv[2],\"wb\").write(bytes(b))' $RT.tr1 $RT.trfld && chmod 600 $RT.trfld"
    launch sunny neg_cut 1 2 "RS_SPARE=1 NCCL_GIN_RESTORE_REPLAY=$RT.trcut"; wait "${PIDS[neg_cut]}"
    launch sunny neg_field 1 2 "RS_SPARE=1 NCCL_GIN_RESTORE_REPLAY=$RT.trfld"; wait "${PIDS[neg_field]}"
    PARTS="$PARTS rep1:sunny rep0:rain neg_cut:sunny neg_field:sunny"
    EXTRA="transcript_bytes_r0=$TR0 transcript_bytes_r1=$TR1" ;;
  b1_live)
    run_rec live 30
    # wait (at most 60 s) until rank 1 holds (its kv has hold_start), then replay rank 1 while both ranks hold
    for i in $(seq 1 120); do ssh -n "$SUNNY_SSH" "grep -q hold_start_mono_ms $RT.live_r1.kv 2>/dev/null" && break; sleep 0.5; done
    launch sunny live_rep1 1 2 "RS_SPARE=1 NCCL_GIN_RESTORE_REPLAY=$RT.tr1" 1; wait "${PIDS[live_rep1]}"
    wait "${PIDS[live_r0]}"; wait "${PIDS[live_r1]}"
    PARTS="$PARTS live_rep1:sunny"
    EXTRA="" ;;
  b2_inter|b2_consec)
    nonce=$(new_nonce)
    for r in 3 2 1 0; do
      if [ "$CELL" = b2_inter ]; then [ $((r % 2)) -eq 0 ] && node=rain || node=sunny; else [ "$r" -lt 2 ] && node=rain || node=sunny; fi
      launch "$node" "rank_r$r" "$r" 4 "RS_RDV_NONCE=$nonce NCCL_MULTI_RANK_GPU_ENABLE=1 NCCL_GIN_RESTORE_REPORT=1"
      PARTS="$PARTS rank_r$r:$node"
    done
    for r in 0 1 2 3; do wait "${PIDS[rank_r$r]}"; done
    EXTRA="placement=${CELL#b2_}" ;;
esac
T1=$(date +%s.%N)
mkdir -p "$LOGDIR"
RCS=""
for p in $PARTS; do
  name=${p%%:*}; node=${p#*:}
  fetch "$node" "$name"
  for f in kv log; do [ -f "$WORK/$name.$f" ] && cp "$WORK/$name.$f" "$LOGDIR/${stem}_$name.$f"; done
  [ -f "$WORK/$name.stracecount" ] && cp "$WORK/$name.stracecount" "$LOGDIR/${stem}_${name}_strace.txt"
  RCS="$RCS rc_$name=$(rcof "$name")"
done
echo "cell=$CELL trial=$TRIAL gid_rain=$GID_R gid_sunny=$GID_S port=$PORT port_tries=$PORT_TRIES strace_rain=$STRACE_R \
strace_sunny=$STRACE_S ${EXTRA:-}$RCS wall_s=$(awk -v a="$T0" -v b="$T1" 'BEGIN{printf "%.1f", b - a}') app=$APP libdir=$LIBDIR" \
  > "$LOGDIR/${stem}_meta.txt"
echo "[$stem]$RCS :: $(grep -ho 'exit=[0-9]*\|xchg=[a-z]*\|abort_rc=[A-Za-z ]*' "$WORK"/*.kv 2>/dev/null | tr '\n' ' ')" >&2
exit 0
