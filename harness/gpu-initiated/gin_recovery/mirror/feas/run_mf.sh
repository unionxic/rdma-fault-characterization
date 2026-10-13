#!/usr/bin/env bash
# run_mf.sh - one run of gin-mirror's feasibility checks (EXPERIMENT.md 9.8; DRAFT stage, never scored). Called by
# hold_mf.sh inside ../../../common/cluster_run.sh.
# usage: run_mf.sh <cell> <repeat> <logdir> [run tag]
#   vis_<4k|256k|2m|rand>_<rain|sunny>  check 1: the named node holds the host MR (mirror_feas vis host; it listens), the
#                                       other node writes from its GPU (vis writer); <repeat> iterations
#   store_<rain|sunny>                  check 3: the named node holds the store MR, the READ source and the background target
#                                       (store host; it listens), the other node is src; <repeat> repetitions (x 10)
#   bar1_rain                           check 4: three bar1 processes on rain's GPU (p0 also in a second PD, p2, sp; the
#                                       slots of rank 0, rank 2 and rank 2's spare); <repeat> is not used
#   cm_<lat4k|lat256k|lat2m|bw256k|bw2m>_<one|man-self|man-peer>_<rain|sunny>
#                                       check 2: gin_ts2 with the manual-mirror arm of cost_man.md (built and deployed by the
#                                       test work package); the named node receives (rank 1), the other sends (rank 0,
#                                       which listens for gin_ts2's rendezvous); <repeat> is not used
# Safety (as ../../restore/feas/run_b3.sh and run_ord.sh): every process runs under timeout -s KILL and its own watchdog;
# nothing is killed here, by name or otherwise; the rendezvous port is drawn from 29000-30999 and checked unused on both
# nodes (../../remaining/portpick.sh), with a per-run nonce; rain's management address is looked up at run time from the
# route to SUNNY_SSH's host and is never written to a file; every NCCL_, GIN_ and MF_ variable of the caller is dropped
# first (the knobs below are read before); IPv4 addresses are masked in every copied kv and log; the node-side files are
# deleted; leftovers are counted by this run's own paths (gin_ts2 is also other studies' driver name: never by name).
# Receipt clock (the house style of ../../restore/impl/test/run_rs.sh): every line a process prints is streamed to rain and
# written as "<rain CLOCK_MONOTONIC at receipt, s> <line>" (sunny's through the ssh stdout).
# files in <logdir> (stem = <cell>, or <cell>_<tag>): <stem>_<name>.kv and .log (vis: host, writer; store: host, src; bar1:
#   p0, p2, sp; cm: r0, r1), <stem>_timing.tsv (store: src's every timed operation), <stem>_bar1.txt (bar1: rain's BAR1 at
#   each stage), <stem>_lat_raw.csv.gz (cm lat cells: rank 0's per-iteration ns; raw data, not tracked),
#   <stem>_gpu_<node>_<before|after>.txt, <stem>_meta.txt (left: this run's processes still there after it ended)
# env: SUNNY_SSH (required), HCA_RAIN (mlx5_1), HCA_SUNNY (mlx5_0), MFBIN ($HOME/rs-bundle/mf/mirror_feas), MF_SIGNAL (msn |
#   flag, vis), MF_QUERY_BUDGET (30000, vis host), MF_BAR1_MIN_FREE_MIB (64: bar1 skips the second-PD stage when rain's BAR1
#   Free after the first stage is below it), CMBIN ($HOME/rs-bundle/mfcm/gin_ts2), CMLIB ($HOME/rs-bundle/i5/lib/rsp: the
#   gin-restore production library of the deployment set i5, read only), CM_LOG_MEASURE_MS (50)
set -u
CELL=${1:?cell}; REP=${2:?repeat}; LOGDIR=${3:?logdir}; RTAG=${4:-}
SIG=${MF_SIGNAL:-msn}; QB=${MF_QUERY_BUDGET:-30000}; MINFREE=${MF_BAR1_MIN_FREE_MIB:-64}; LMS=${CM_LOG_MEASURE_MS:-50}
for v in $(env | sed -n 's/^\(\(NCCL\|GIN\|MF\)_[A-Za-z0-9_]*\)=.*/\1/p'); do unset "$v"; done
SUNNY_SSH=${SUNNY_SSH:?set SUNNY_SSH}
SUNNY_HOST=${SUNNY_SSH#*@}
HCA_RAIN=${HCA_RAIN:-mlx5_1}; HCA_SUNNY=${HCA_SUNNY:-mlx5_0}
BIN=${MFBIN:-$HOME/rs-bundle/mf/mirror_feas}
CMBIN=${CMBIN:-$HOME/rs-bundle/mfcm/gin_ts2}; CMLIB=${CMLIB:-$HOME/rs-bundle/i5/lib/rsp}
STEM=$CELL${RTAG:+_$RTAG}
bad() { echo "bad cell $CELL" >&2; exit 2; }
case "$SIG" in msn|flag) ;; *) echo "MF_SIGNAL must be msn or flag" >&2; exit 2 ;; esac
case "$QB$MINFREE$LMS$REP" in *[!0-9]*) echo "MF_QUERY_BUDGET, MF_BAR1_MIN_FREE_MIB, CM_LOG_MEASURE_MS, repeat: numbers" >&2; exit 2 ;; esac
[ "$QB" -ge 1000 ] || { echo "MF_QUERY_BUDGET must be >= 1000 (mirror_feas stops hard at the budget + 400)" >&2; exit 2; }
IFS=_ read -r KIND A1 A2 A3 <<< "$CELL"
case "$KIND" in
  vis) case "$A1:${A2:-}:${A3:-}" in 4k:rain:|4k:sunny:|256k:rain:|256k:sunny:|2m:rain:|2m:sunny:|rand:rain:|rand:sunny:) ;; *) bad ;; esac
       SIZE=$A1; HOSTN=$A2 ;;
  store) case "${A1:-}:${A2:-}" in rain:|sunny:) ;; *) bad ;; esac; HOSTN=$A1 ;;
  bar1) [ "${A1:-}:${A2:-}" = rain: ] || bad ;;
  cm) case "${A1:-}" in lat4k|lat256k|lat2m|bw256k|bw2m) ;; *) bad ;; esac
      case "${A2:-}" in one|man-self|man-peer) ;; *) bad ;; esac
      case "${A3:-}" in rain|sunny) ;; *) bad ;; esac
      METRIC=$A1; ARM=$A2; HOSTN=$A3 ;;
  *) bad ;;
esac
if [ "$KIND" = cm ]; then
  [ -x "$CMBIN" ] && [ -f "$CMLIB/libnccl.so.2" ] || { echo "missing $CMBIN or $CMLIB/libnccl.so.2 on rain (cost_man.md)" >&2; exit 1; }
else
  [ -x "$BIN" ] || { echo "missing $BIN on rain" >&2; exit 1; }
fi
umask 077
WORK=$(mktemp -d /tmp/mf_run.XXXXXX)
RT=/tmp/mf_rt_$$_$RANDOM            # sunny-side file prefix of this run
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
STAMP='import sys,time
for l in sys.stdin.buffer:
    sys.stdout.write("%.6f %s\n" % (time.clock_gettime(time.CLOCK_MONOTONIC), l.decode("utf-8","replace").rstrip("\n")))
    sys.stdout.flush()'
other() { [ "$1" = rain ] && echo sunny || echo rain; }
hca() { [ "$1" = rain ] && echo "$HCA_RAIN" || echo "$HCA_SUNNY"; }
gidx() { [ "$1" = rain ] && echo "$GID_R" || echo "$GID_S"; }
addr() { [ "$1" = rain ] && echo "$RAIN_MGMT" || echo "$SUNNY_HOST"; }
npath() { [ "$1" = sunny ] && echo "$RT.$2" || echo "$WORK/$2"; }   # a per-run file on <node>
declare -A PIDS NODE
# start <node> <name> <env> <command...>: one process under timeout -s KILL $TMO on <node>, in a private working directory,
# no core files; stdout and stderr stamped on rain at receipt into $WORK/<name>.log; the exit code into <name>.rc on the node
start() {
  local node=$1 name=$2 envs=$3; shift 3
  NODE[$name]=$node
  if [ "$node" = rain ]; then
    ( mkdir -p "$WORK/cwd" && cd "$WORK/cwd" && ulimit -c 0 && env $envs stdbuf -oL -eL timeout -s KILL "$TMO" "$@" 2>&1
      echo $? > "$WORK/$name.rc" ) | python3 -u -c "$STAMP" > "$WORK/$name.log" 2>&1 &
  else
    ssh -n "$SUNNY_SSH" "umask 077 && mkdir -p $RT.cwd && cd $RT.cwd && ulimit -c 0 && $envs stdbuf -oL -eL timeout -s KILL $TMO $* 2>&1; \
echo \$? > $RT.$name.rc" | python3 -u -c "$STAMP" > "$WORK/$name.log" 2>&1 &
  fi
  PIDS[$name]=$!
}
snapgpu() {  # snapgpu <tag>
  nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader > "$WORK/gpu_rain_$1.txt" 2>&1
  ssh -n "$SUNNY_SSH" "nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader" > "$WORK/gpu_sunny_$1.txt" 2>&1
}
bar1read() {  # bar1read <stage>: rain's BAR1 Total, Used, Free (MiB; nvidia-smi, read only; the first GPU listed)
  local tm; tm=$(python3 -c 'import time; print("%.3f" % time.clock_gettime(time.CLOCK_MONOTONIC))')
  nvidia-smi -q -d MEMORY 2>/dev/null | sed -n '/BAR1/,/Free/p' | awk -v s="$1" -v tm="$tm" '
    /Total/ && t == "" {t = $3} /Used/ && u == "" {u = $3} /Free/ && f == "" {f = $3}
    END {printf "stage=%s total_mib=%s used_mib=%s free_mib=%s t_mono=%s\n", s, t, u, f, tm}'
}
WAITPY='import re,sys,time
st,n,tmo,files=sys.argv[1],int(sys.argv[2]),float(sys.argv[3]),sys.argv[4:]
rx=re.compile(r"MFSTAGE \S+ %s ok=" % re.escape(st))
end=time.time()+tmo
while time.time()<end:
    k=0
    for f in files:
        try:
            k+=any(rx.search(l) for l in open(f,errors="replace"))
        except OSError:
            pass
    if k>=n: sys.exit(0)
    time.sleep(0.05)
sys.exit(1)'
waitstage() { python3 -c "$WAITPY" "$1" 3 "$2" "$WORK/p0.log" "$WORK/p2.log" "$WORK/sp.log"; }
pick_port
NONCE=$(new_nonce)
snapgpu before
GPU_APPS="$(grep -c . "$WORK/gpu_rain_before.txt")/$(grep -c . "$WORK/gpu_sunny_before.txt")"
MEMLOCK="$(bash -c 'ulimit -l')/$(ssh -n "$SUNNY_SSH" 'ulimit -l' 2>/dev/null)"
NOTE=""
T0=$(date +%s.%N)
case "$KIND" in
  vis)
    WRN=$(other "$HOSTN"); WD=$(( REP / 200 + 120 )); TMO=$(( WD + 30 ))
    E="MF_RDV_NONCE=$NONCE MF_WATCHDOG_S=$WD MF_SIGNAL=$SIG"
    start "$HOSTN" host "$E MF_QUERY_BUDGET=$QB MF_RUN_S=$(( REP / 200 + 60 ))" "$BIN" "$(npath "$HOSTN" host.kv)" vis host \
      "$(hca "$HOSTN")" "$(gidx "$HOSTN")" "$SIZE" "$REP" "listen:$PORT"
    sleep 1
    start "$WRN" writer "$E" "$BIN" "$(npath "$WRN" writer.kv)" vis writer "$(hca "$WRN")" "$(gidx "$WRN")" "$SIZE" "$REP" \
      "connect:$(addr "$HOSTN"):$PORT" ;;
  store)
    SRCN=$(other "$HOSTN"); WD=$(( REP / 2 + 240 )); TMO=$(( WD + 30 ))
    E="MF_RDV_NONCE=$NONCE MF_WATCHDOG_S=$WD"
    start "$HOSTN" host "$E" "$BIN" "$(npath "$HOSTN" host.kv)" store host "$(hca "$HOSTN")" "$(gidx "$HOSTN")" "$REP" "listen:$PORT"
    sleep 1
    start "$SRCN" src "$E MF_TIMING_FILE=$(npath "$SRCN" timing.tsv)" "$BIN" "$(npath "$SRCN" src.kv)" store src "$(hca "$SRCN")" \
      "$(gidx "$SRCN")" "$REP" "connect:$(addr "$HOSTN"):$PORT" ;;
  bar1)
    WD=300; TMO=330; CD=$WORK/ctl; mkdir -p "$CD"
    bar1read before > "$WORK/bar1.txt"
    E="MF_WATCHDOG_S=$WD MF_STAGE_WAIT_S=60"
    start rain p0 "$E" "$BIN" "$WORK/p0.kv" bar1 p0 "$HCA_RAIN" "$CD" 1
    start rain p2 "$E" "$BIN" "$WORK/p2.kv" bar1 p2 "$HCA_RAIN" "$CD" 0
    start rain sp "$E" "$BIN" "$WORK/sp.kv" bar1 sp "$HCA_RAIN" "$CD" 0
    if waitstage ctx 90; then bar1read ctx >> "$WORK/bar1.txt"; else NOTE="$NOTE ctx_timeout"; fi
    touch "$CD/go_pd1"
    if waitstage pd1 60; then bar1read pd1 >> "$WORK/bar1.txt"; else NOTE="$NOTE pd1_timeout"; fi
    FREE=$(tail -1 "$WORK/bar1.txt" | sed -n 's/.* free_mib=\([0-9]*\) .*/\1/p')
    if [ -n "$FREE" ] && [ "$FREE" -ge "$MINFREE" ]; then
      touch "$CD/go_pd2"
      if waitstage pd2 60; then bar1read pd2 >> "$WORK/bar1.txt"; else NOTE="$NOTE pd2_timeout"; fi
    else
      NOTE="$NOTE pd2_skipped_free=${FREE:-unread}"   # the processes see stop before go_pd2 and skip the second PD
    fi
    touch "$CD/stop" ;;
  cm)
    TXN=$(other "$HOSTN"); WD=45; TMO=$(( WD + 20 ))
    case "$METRIC" in
      lat4k)   MODE=lat;   ITERS=3000; BYTES=4096;    XENV="" ;;
      lat256k) MODE=lat;   ITERS=3000; BYTES=262144;  XENV="" ;;
      lat2m)   MODE=lat;   ITERS=3000; BYTES=2097152; XENV="" ;;
      bw256k)  MODE=burst; ITERS=12;   BYTES=262144;  XENV="GIN_TS_TX_BLOCKS=1 GIN_TS_TX_THREADS=1 GIN_TS_BURST_K=8 GIN_TS_AGG=1" ;;
      bw2m)    MODE=burst; ITERS=24;   BYTES=2097152; XENV="GIN_TS_TX_BLOCKS=1 GIN_TS_TX_THREADS=1 GIN_TS_BURST_K=8 GIN_TS_AGG=1 GIN_TS_BURST_REUSE=1" ;;
    esac
    case "$ARM" in one) MAN="" ;; man-self) MAN="GIN_TS_MAN_MIRROR=self" ;; man-peer) MAN="GIN_TS_MAN_MIRROR=peer" ;; esac
    # gin-restore's cost frame (../../restore/impl/test/run_cost.sh, arm "on": the macro-built driver, the library's
    # measurement mode with the log on, checksum off), both windows strict, QP watch off; the arms differ only in MAN
    NENV="NCCL_DEBUG=WARN NCCL_SOCKET_IFNAME=eno1 NCCL_GIN_TYPE=3 NCCL_GIN_ENABLE=1 NCCL_IB_TIMEOUT=14 \
NCCL_GIN_FAULT_CLASSIFY=1 NCCL_GIN_FAULT_RECOVERY=1 NCCL_GIN_FAULT_TRANSPARENT=1 NCCL_GIN_TS_QPWATCH_MS=0 NCCL_GIN_Q4_QPWATCH_MS=0 \
NCCL_RMA_DISABLE=1 NCCL_NUM_RMA_CTX=0 NCCL_SYM_GIN_KERNELS_ENABLE=0 NCCL_GIN_NCONNECTIONS=1 GIN_TS_WIN_STRICT=1 \
NCCL_GIN_FAULT_POLICY=hold NCCL_GIN_RESTORE=1 NCCL_GIN_RESTORE_LOG_MEASURE=$LMS NCCL_GIN_RESTORE_LOG_MEASURE_LOG=1 \
NCCL_GIN_RESTORE_CHECKSUM=off GIN_ABORT_WATCHDOG_S=15 GIN_RDV_NONCE=$NONCE LD_LIBRARY_PATH=$CMLIB $XENV $MAN"
    for r in 0 1; do
      node=$TXN; [ "$r" = 1 ] && node=$HOSTN
      e="$NENV NCCL_IB_HCA=$(hca "$node") NCCL_IB_GID_INDEX=$(gidx "$node")"
      [ "$r" = 0 ] && [ "$MODE" = lat ] && e="$e GIN_LAT_RAW=$(npath "$node" lat_raw.csv)"
      start "$node" "r$r" "$e" "$CMBIN" "$r" "$(addr "$TXN")" "$PORT" "$ITERS" "$BYTES" blocking "$MODE" 8 "$WD" \
        "$(npath "$node" "r$r.kv")" 0
      [ "$r" = 0 ] && sleep 1
    done ;;
esac
for n in "${!PIDS[@]}"; do wait "${PIDS[$n]}"; done
T1=$(date +%s.%N)
[ "$KIND" = bar1 ] && bar1read after >> "$WORK/bar1.txt"
snapgpu after
# this run's processes still there (counting only, by the run's unique paths; a pattern that does not match the shell)
LEFT=$( { pgrep -f "[${WORK:0:1}]${WORK:1}/" 2>/dev/null; ssh -n "$SUNNY_SSH" "pgrep -f '[${RT:0:1}]${RT:1}\.'"; } 2>/dev/null | wc -l)
for n in "${!NODE[@]}"; do
  [ "${NODE[$n]}" = sunny ] || continue
  for f in "$n.kv" "$n.rc" timing.tsv lat_raw.csv; do scp -q "$SUNNY_SSH:$RT.$f" "$WORK/$f" 2>/dev/null || true; done
done
mkdir -p "$LOGDIR"
# a rerun of this stem: no file of the earlier run stays (only this runner's own suffixes)
rm -f "$LOGDIR/${STEM}"_{host,writer,src,p0,p2,sp,r0,r1}.{kv,log} "$LOGDIR/${STEM}"_{timing.tsv,bar1.txt,lat_raw.csv.gz,meta.txt} \
  "$LOGDIR/${STEM}"_gpu_{rain,sunny}_{before,after}.txt
MASK='s/[0-9]\{1,3\}\.[0-9]\{1,3\}\.[0-9]\{1,3\}\.[0-9]\{1,3\}/<ip>/g'
for n in "${!NODE[@]}"; do
  for x in kv log; do [ -f "$WORK/$n.$x" ] && sed "$MASK" "$WORK/$n.$x" > "$LOGDIR/${STEM}_$n.$x"; done
done
[ -f "$WORK/timing.tsv" ] && cp "$WORK/timing.tsv" "$LOGDIR/${STEM}_timing.tsv"
[ -f "$WORK/bar1.txt" ] && cp "$WORK/bar1.txt" "$LOGDIR/${STEM}_bar1.txt"
[ -f "$WORK/lat_raw.csv" ] && gzip -c "$WORK/lat_raw.csv" > "$LOGDIR/${STEM}_lat_raw.csv.gz"
for n in rain sunny; do for t in before after; do cp "$WORK/gpu_${n}_$t.txt" "$LOGDIR/${STEM}_gpu_${n}_$t.txt"; done; done
rc() { tr -d '\n' < "$WORK/$1.rc" 2>/dev/null || echo none; }
RCS=$(for n in $(printf '%s\n' "${!NODE[@]}" | sort); do printf 'rc_%s=%s ' "$n" "$(rc "$n")"; done)
B1=$(md5sum < "$( [ "$KIND" = cm ] && echo "$CMBIN" || echo "$BIN" )" | cut -c1-32)
B2=$(ssh -n "$SUNNY_SSH" "md5sum < $( [ "$KIND" = cm ] && echo "$CMBIN" || echo "$BIN" ) | cut -c1-32" 2>/dev/null)
echo "cell=$STEM kind=$KIND host_node=${HOSTN:-rain} repeat=$REP signal=$SIG query_budget=$QB hca_rain=$HCA_RAIN \
hca_sunny=$HCA_SUNNY gid_rain=$GID_R gid_sunny=$GID_S ${RCS}left=$LEFT port=$PORT port_tries=$PORT_TRIES rdv_nonce_set=1 \
timeout_s=$TMO gpu_apps_before=$GPU_APPS memlock_kib=$MEMLOCK wall_s=$(awk -v a="$T0" -v b="$T1" 'BEGIN{printf "%.1f", b - a}') \
bin_md5_rain=$B1 bin_md5_sunny=${B2:-unread}${NOTE:+ note=$(echo $NOTE | tr ' ' ',')}" > "$LOGDIR/${STEM}_meta.txt"
echo "[$STEM] $RCS:: $(grep -ho 'result=[A-Z_]*\|setup_error=[^ ]*\|nic_error=[^ ]*\|exit=[0-9]*' "$WORK"/*.kv 2>/dev/null | tr '\n' ' ')" >&2
exit 0
