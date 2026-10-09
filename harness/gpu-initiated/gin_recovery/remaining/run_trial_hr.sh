#!/usr/bin/env bash
# run_trial_hr.sh - one gin-remaining two-rank trial (rank 0 = rain, rank 1 = sunny), inside ../../common/cluster_run.sh
# (through hold.sh). A copy of ../peer/run_trial_hq.sh (that script is not changed) with one difference: the driver binary
# may come from another bundle than the library, DRVKEY (default: BUILD): the hq controls of this study run the hq libnccl
# with this study's gin_ts2 (DRVKEY=hr; GIN_TS_HOG_CALLS is new in it). The meta line adds drvkey and drvbin. gin-peer's
# description follows (its own copy of ../harden/run_trial_hd.sh: same arguments, same per-trial files, same meta line
# plus a few keys) with these differences:
#   - the port fix (portpick.sh): the rendezvous port is drawn below the ephemeral range and checked unused on both
#     nodes; every trial gets a random rendezvous nonce (GIN_RDV_NONCE: this study's drivers verify the rendezvous before
#     sending anything; the older drivers of the hf and hfp bundles ignore it);
#   - RDV_DECOY=1 (test): a decoy listener on rain at a second free port; rank 1 (GIN_RDV_TEST_DECOY_PORT) connects there
#     first and must reject it without sending a byte (decoy.out); PORT_OCCUPY=1 (test): a listener holds the first
#     candidate port before the pick, which must skip it;
#   - no iptables (this study changes no firewall rule) and no MGMT_MUTE.
# Processes are only ever killed by a PID this script recorded: rank 0 runs under a `timeout` whose PID is kept; rank 1's
# remote shell writes its own PID (the `timeout` it execs into) to a per-trial file; the occupier and the decoy run under
# `timeout` wrappers whose PIDs are kept. Nothing is killed or counted by process name alone.
#
# usage: run_trial_hq.sh <none|F1|F2|F3|F4|F1both|lat> <timeout|blocking> <trial-tag> <logdir> [iters] [bytes]
# env knobs (as run_trial_hd.sh): APP=default|burst|bidir, BUILD (libnccl bundle directory under $HOME/gi-bundle/gin_ts2),
#   DRVKEY (gin-remaining: the bundle directory of the gin_ts2 binary; default BUILD), TS, REC,
#   CLASSIFY, INJECT, INJECT1, R0_ENV, R1_ENV, EXTRA_ENV, KILL_DELAY_MS (F4: rank 1; default 1200), KILL_R0=1 (rank 0,
#   KILL_DELAY_MS after its launch), GAP_US, DEV_TIMEOUT_S (8), WATCHDOG_S (45), IB_TIMEOUT (14), DIAG, ABORT_WD_S (15),
#   NCCL_DEBUG, NCCL_DEBUG_SUBSYS; gin-peer: PORT_LO, PORT_HI, RDV_DECOY, PORT_OCCUPY
set -u
FAULT=$1; WAIT=$2; TRIAL=$3; LOGDIR=$4
ITERS=${5:-120}
BYTES=${6:-262144}
APP=${APP:-default}; BUILD=${BUILD:?BUILD (bundle directory) is required}
TS=${TS:-1}; REC=${REC:-1}; CLASSIFY=${CLASSIFY:-1}
INJECT=${INJECT:-700}
DEV_TIMEOUT_S=${DEV_TIMEOUT_S:-8}
WATCHDOG_S=${WATCHDOG_S:-45}
IB_TIMEOUT=${IB_TIMEOUT:-14}
if [ "$FAULT" = lat ]; then GAP_US=${GAP_US:-0}; else GAP_US=${GAP_US:-15000}; fi
SUNNY_SSH=${SUNNY_SSH:-unionxic@192.0.2.194}
SUNNY_HOST=${SUNNY_SSH#*@}
# rank 0's management address (the rendezvous rank 1 connects to): the address of rain's interface on the route to
# sunny's management address, looked up at run time (no address is written here)
RAIN_MGMT=$(ip -4 route get "$SUNNY_HOST" 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p' | head -1)
[ -n "$RAIN_MGMT" ] || { echo "cannot find rain's management address" >&2; exit 1; }
BUNDLE=$HOME/gi-bundle/gin_ts2/$BUILD
DRVKEY=${DRVKEY:-$BUILD}   # gin-remaining: the driver's bundle
DRVDIR=$HOME/gi-bundle/gin_ts2/$DRVKEY
BIN=gin_ts2
[ -x "$DRVDIR/$BIN" ] && [ -f "$BUNDLE/libnccl.so.2" ] || { echo "missing $DRVDIR/$BIN or $BUNDLE/libnccl.so.2 on rain" >&2; exit 1; }
WORK=$(mktemp -d /tmp/gin_hr_trial.XXXXXX)
D=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=portpick.sh
. "$D/portpick.sh"
OCC_PORT=""; OCC_PID=""; DECOY_PID=""; DECOY_PORT=""
if [ "${PORT_OCCUPY:-0}" = 1 ]; then  # test: hold the first candidate, then pick from it (it must be skipped)
  first=$(( PORT_LO + ($$ + RANDOM) % (PORT_HI - PORT_LO + 1) ))
  pick_port "$first"; OCC_PORT=$PORT
  start_occupier "$OCC_PORT" || echo "occupier on $OCC_PORT did not listen" >&2
  pick_port "$OCC_PORT"
else
  pick_port
fi
RDV_NONCE=$(new_nonce)
R1_DECOY=""
if [ "${RDV_DECOY:-0}" = 1 ]; then  # test: a decoy listener at another free port; rank 1 tries it first
  save=$PORT; savet=$PORT_TRIES; saves=$PORT_SKIPPED
  pick_port $(( PORT + 1 > PORT_HI ? PORT_LO : PORT + 1 )); DECOY_PORT=$PORT
  PORT=$save; PORT_TRIES=$savet; PORT_SKIPPED=$saves
  start_decoy "$DECOY_PORT" "$WORK/decoy.out" || echo "decoy on $DECOY_PORT did not listen" >&2
  R1_DECOY="GIN_RDV_TEST_DECOY_PORT=$DECOY_PORT"
fi
cleanup_aux() { stop_pid "$OCC_PID" TERM; OCC_PID=""; stop_pid "$DECOY_PID" TERM; DECOY_PID=""; }
trap 'cleanup_aux' EXIT
RTAG=gin_hr_$(hostname -s)_$$_$RANDOM
R1KV=/tmp/$RTAG.kv; R1LOG=/tmp/$RTAG.log; R1PIDF=/tmp/$RTAG.pid
GID_PROBE='d=/sys/class/infiniband/$1/ports/1
for g in $(ls "$d/gids" | sort -n); do
  [ "$(cat "$d/gid_attrs/types/$g" 2>/dev/null)" = "RoCE v2" ] || continue
  case "$(cat "$d/gids/$g")" in 0000:0000:0000:0000:0000:ffff:1e00:00*) echo "$g"; exit 0;; esac
done; exit 1'
GID0=$(bash -c "$GID_PROBE" _ mlx5_1) || { echo "no GID on rain" >&2; exit 1; }
GID1=$(ssh -n "$SUNNY_SSH" bash -c "'$GID_PROBE'" _ mlx5_0) || { echo "no GID on sunny" >&2; exit 1; }
MODE=none; INJ0=""; INJ1=""; KILL_R1=0
case "$APP" in default) ;; burst) MODE=burst ;; bidir) MODE=bidir ;; *) echo "unknown APP $APP" >&2; exit 1 ;; esac
case "$FAULT" in
  none) ;;
  lat) MODE=lat ;;
  F1) INJ0="local_err:$INJECT" ;;
  F1both) INJ0="local_err:$INJECT"; INJ1="local_err:${INJECT1:-$INJECT}" ;;
  F2) if [ "$MODE" = burst ]; then R0_ENV="${R0_ENV:-} GIN_TS_BURST_BADIT=${F2_IT:-10}"; else MODE=F2; fi ;;
  F3) INJ1="peer_err:$INJECT" ;;
  F4) KILL_R1=1 ;;
  *) echo "unknown fault $FAULT" >&2; exit 1 ;;
esac
case "$BUILD" in stk) TSENV="" ;; *) TSENV="NCCL_GIN_FAULT_TRANSPARENT=$TS" ;; esac
NENV="NCCL_DEBUG=${NCCL_DEBUG:-WARN} NCCL_DEBUG_SUBSYS=${NCCL_DEBUG_SUBSYS:-INIT,NET} NCCL_SOCKET_IFNAME=eno1 \
NCCL_GIN_TYPE=3 NCCL_GIN_ENABLE=1 NCCL_IB_TIMEOUT=$IB_TIMEOUT NCCL_GIN_FAULT_CLASSIFY=$CLASSIFY \
NCCL_GIN_FAULT_RECOVERY=$REC $TSENV ${DIAG:+NCCL_GIN_TS_DIAG=$DIAG} GIN_ABORT_WATCHDOG_S=${ABORT_WD_S:-15} \
GIN_RDV_NONCE=$RDV_NONCE LD_LIBRARY_PATH=$BUNDLE ${EXTRA_ENV:-}"
ARGS="$ITERS $BYTES $WAIT $MODE $DEV_TIMEOUT_S $WATCHDOG_S"
tag="$BUILD/ts${TS}/$APP/${FAULT}/${WAIT}#${TRIAL}"
echo "[$tag] rain=$GID0 sunny=$GID1 port=$PORT tries=$PORT_TRIES skipped=${PORT_SKIPPED:--} decoy=${DECOY_PORT:--} inject=$INJECT bytes=$BYTES iters=$ITERS rtag=$RTAG" >&2
# rank 1: the remote shell records its own PID, then execs into `timeout`, whose child is gin_ts2
ssh -n "$SUNNY_SSH" "cd $BUNDLE && echo \$\$ > $R1PIDF && $NENV NCCL_IB_HCA=mlx5_0 NCCL_IB_GID_INDEX=$GID1 \
${INJ1:+NCCL_GIN_FAULT_INJECT=$INJ1} $R1_DECOY ${R1_ENV:-} exec stdbuf -oL -eL timeout -s KILL $((WATCHDOG_S+20)) $DRVDIR/$BIN 1 $RAIN_MGMT \
$PORT $ARGS $R1KV $GAP_US > $R1LOG 2>&1" &
SSH_PID=$!
# kill rank 1 (F4): the gin_ts2 child of the recorded remote PID, by its PID
if [ "$KILL_R1" = 1 ]; then
  KILL_DELAY_MS=${KILL_DELAY_MS:-1200}
  ( sleep "$(awk "BEGIN{print $KILL_DELAY_MS/1000}")"
    ssh -n "$SUNNY_SSH" "tp=\$(cat $R1PIDF 2>/dev/null); pid=; [ -n \"\$tp\" ] && grep -q $RTAG /proc/\$tp/cmdline 2>/dev/null && \
pid=\$(pgrep -P \"\$tp\" -x $BIN | head -1); [ -n \"\$pid\" ] && python3 -c \"import os,sys,time; t=time.clock_gettime(time.CLOCK_MONOTONIC)*1e3; os.kill(int(sys.argv[1]),9); \
print('kill_mono_ms=%.3f pid=%s' % (t, sys.argv[1]))\" \$pid || echo no_rank1_process=1" > "$WORK/kill.out" 2>&1
    echo "[$tag] SIGKILL rank1 after ${KILL_DELAY_MS} ms: $(cat "$WORK/kill.out")" >&2 ) &
  KILLER=$!
fi
LATRAW=""; [ "$FAULT" = lat ] && LATRAW="GIN_LAT_RAW=$WORK/lat_raw.csv"
T0=$(date +%s.%N)
# rank 0, always under a recorded `timeout` PID
env $NENV NCCL_IB_HCA=mlx5_1 NCCL_IB_GID_INDEX=$GID0 ${INJ0:+NCCL_GIN_FAULT_INJECT=$INJ0} $LATRAW ${R0_ENV:-} \
  stdbuf -oL -eL timeout -s KILL $((WATCHDOG_S+20)) "$DRVDIR/$BIN" 0 "$RAIN_MGMT" $PORT $ARGS "$WORK/r0.kv" $GAP_US \
  > "$WORK/r0.log" 2>&1 &
R0PID=$!
if [ -n "$OCC_PID" ]; then stop_pid "$OCC_PID" TERM; OCC_PID=""; fi  # the pick is done: the occupier has served
if [ "${KILL_R0:-0}" = 1 ]; then
  # kill OUR rank 0 (the gin_ts2 child of R0PID) KILL_DELAY_MS after its launch; kill.out: kill_mono_ms, pid, rank=0
  ( sleep "$(awk "BEGIN{print ${KILL_DELAY_MS:-1200}/1000}")"
    pid=$(pgrep -P "$R0PID" -x $BIN | head -1)
    if [ -n "$pid" ]; then
      python3 -c "import os,sys,time; t=time.clock_gettime(time.CLOCK_MONOTONIC)*1e3; os.kill(int(sys.argv[1]),9); print('kill_mono_ms=%.3f pid=%s rank=0' % (t, sys.argv[1]))" "$pid"
    else
      echo "no_rank0_process=1"
    fi > "$WORK/kill.out" 2>&1
    echo "[$tag] SIGKILL rank0 after ${KILL_DELAY_MS:-1200} ms: $(cat "$WORK/kill.out")" >&2 ) &
  KILLER0=$!
fi
wait "$R0PID"
R0RC=$?
[ "${KILLER0:-}" ] && wait "$KILLER0" 2>/dev/null
T1=$(date +%s.%N)
wait "$SSH_PID" 2>/dev/null; R1RC=$?
[ "${KILLER:-}" ] && wait "$KILLER" 2>/dev/null
cleanup_aux
scp -q "$SUNNY_SSH:$R1KV" "$WORK/r1.kv" 2>/dev/null || true
scp -q "$SUNNY_SSH:$R1LOG" "$WORK/r1.log" 2>/dev/null || true
# cleanup: only the recorded remote PID and its children, and only while that PID is still this trial's `timeout` (its
# command line carries the trial's unique file tag), so a reused PID is never signalled. Rank 0's `timeout` was waited
# for above (its gin_ts2 child ends with it or before it): nothing local to kill. Leftovers are counted by the trial's
# unique tag in the command line (counting only), with a pattern that does not match the shell that counts
# (see ../harden/run_trial_hd.sh).
ssh -n "$SUNNY_SSH" "tp=\$(cat $R1PIDF 2>/dev/null); if [ -n \"\$tp\" ] && grep -q $RTAG /proc/\$tp/cmdline 2>/dev/null; then \
for c in \$(pgrep -P \"\$tp\"); do kill -9 \$c 2>/dev/null; done; kill -9 \$tp 2>/dev/null; fi; rm -f $R1KV $R1LOG $R1PIDF" || true
RPAT="[${RTAG:0:1}]${RTAG:1}"
LPAT="[${WORK:0:1}]${WORK:1}/r0.kv"
LEFT=$( { pgrep -f "$LPAT" 2>/dev/null; ssh -n "$SUNNY_SSH" "pgrep -f '$RPAT'"; } 2>/dev/null | wc -l)
OCC_SKIPPED=0
[ -n "$OCC_PORT" ] && [ "$PORT" != "$OCC_PORT" ] && case ",$PORT_SKIPPED," in *",$OCC_PORT,"*) OCC_SKIPPED=1 ;; esac
mkdir -p "$LOGDIR"
stem="${CELL:-${BUILD}_ts${TS}_${APP}_${FAULT}_${WAIT}}_${TRIAL}"
for f in r0.log r1.log r0.kv r1.kv kill.out decoy.out; do [ -f "$WORK/$f" ] && cp "$WORK/$f" "$LOGDIR/${stem}_$f"; done
[ -f "$WORK/lat_raw.csv" ] && gzip -c "$WORK/lat_raw.csv" > "$LOGDIR/${stem}_lat_raw.csv.gz"
echo "cell=${CELL:-} build=$BUILD app=$APP r0env=$(echo ${R0_ENV:-} | tr ' ' '+') r1env=$(echo ${R1_ENV:-} | tr ' ' '+') \
extra=$(echo ${EXTRA_ENV:-} | tr ' ' '+') fault=$FAULT wait=$WAIT trial=$TRIAL ts=$TS rec=$REC classify=$CLASSIFY diag=${DIAG:-} \
inject=$INJECT inject1=${INJECT1:-} iters=$ITERS bytes=$BYTES gap_us=$GAP_US gidsel=primary gid0=$GID0 gid1=$GID1 cut_s=0 \
cut_delay_ms=0 r0rc=$R0RC r1rc=$R1RC left=$LEFT ib_timeout=$IB_TIMEOUT kill_r0=${KILL_R0:-0} kill_delay_ms=${KILL_DELAY_MS:-} \
port=$PORT port_lo=$PORT_LO port_hi=$PORT_HI port_tries=$PORT_TRIES port_skipped=${PORT_SKIPPED:-none} \
occupy_port=${OCC_PORT:-none} occupy_skipped=$OCC_SKIPPED decoy_port=${DECOY_PORT:-none} rdv_nonce_set=1 runner=hr \
wall_s=$(awk "BEGIN{printf \"%.1f\", $T1-$T0}") bundle=$BUNDLE drvkey=$DRVKEY drvbin=$DRVDIR/$BIN" > "$LOGDIR/${stem}_meta.txt"
echo "[$tag] r0rc=$R0RC r1rc=$R1RC left=$LEFT wall=$(awk "BEGIN{printf \"%.1f\", $T1-$T0}")s :: $(grep -h 'DONE outcome' "$WORK/r0.log" "$WORK/r1.log" 2>/dev/null | sed 's/^.*\] //' | tr '\n' '|')" >&2
rm -rf "$WORK"
exit 0
