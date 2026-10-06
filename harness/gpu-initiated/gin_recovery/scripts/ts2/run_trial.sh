#!/usr/bin/env bash
# run_trial.sh - one S2 trial (rank0 = rain, rank1 = sunny), inside ../../../common/cluster_run.sh. The
# application (gin_ts2) is the same unmodified program in every cell; only the NCCL environment, the
# application's traffic mode and the injected fault differ.
#
# usage: run_trial.sh <none|F1|F2|F3|F4|F1both|lat> <timeout|blocking> <trial-tag> <logdir> [iters] [bytes]
# env knobs:
#   APP=default|burst|bidir   traffic mode of gin_ts2 (default: the S1 put+signal+flush loop)
#   BUILD=s2|s1|base|var_sys  which bundle directory (default s2 = the S2 build)
#   TS=0|1        NCCL_GIN_FAULT_TRANSPARENT (default 1). REC/CLASSIFY default 1.
#   INJECT=<ms>[,<ms>...]  hook delay list (F1: rank 0 local_err, F3: rank 1 peer_err, F1both: both ranks
#                 local_err, rank 1 with INJECT1 if set), default 700
#   GIDSEL=primary|secondary  GID of the test QPs: the first IPv4 RoCE v2 GID (primary, as S1) or the
#                 secondary address's GID (30.0.1.x, set up by ../../../../nccl-integration/stage2/gid_blackhole.sh)
#   CUT_S=<s> CUT_DELAY_MS=<ms>  address flap: remove sunny's secondary address for CUT_S seconds, CUT_DELAY_MS
#                 after rank 0 launched its kernel (gid_blackhole.sh cut); needs GIDSEL=secondary and a prior setup
#   R0_ENV / R1_ENV / EXTRA_ENV   extra environment (rank 0 / rank 1 / both)
#   KILL_DELAY_MS (F4, default 1200), GAP_US (default 15000; lat: 0), DEV_TIMEOUT_S (8), WATCHDOG_S (45), DIAG
set -u
FAULT=$1; WAIT=$2; TRIAL=$3; LOGDIR=$4
ITERS=${5:-120}
BYTES=${6:-262144}
APP=${APP:-default}; BUILD=${BUILD:-s2}
TS=${TS:-1}; REC=${REC:-1}; CLASSIFY=${CLASSIFY:-1}
INJECT=${INJECT:-700}
DEV_TIMEOUT_S=${DEV_TIMEOUT_S:-8}
WATCHDOG_S=${WATCHDOG_S:-45}
IB_TIMEOUT=${IB_TIMEOUT:-14}
GIDSEL=${GIDSEL:-primary}
if [ "$FAULT" = lat ]; then GAP_US=${GAP_US:-0}; else GAP_US=${GAP_US:-15000}; fi
RAIN_MGMT=192.0.2.193
SUNNY_SSH=${SUNNY_SSH:-unionxic@192.0.2.194}
GBH=/home/unionxic/rdma-error/harness/nccl-integration/stage2/gid_blackhole.sh
BUNDLE=/home/unionxic/gi-bundle/gin_ts2
[ "$BUILD" != s2 ] && BUNDLE=$BUNDLE/$BUILD
BIN=gin_ts2
PORT=$(( 46000 + ($$ + RANDOM) % 3000 ))
WORK=$(mktemp -d /tmp/gin_ts2_trial.XXXXXX)
if [ "$GIDSEL" = secondary ]; then
  read -r GID0 GID1 < <(bash "$GBH" gids 2>/dev/null)
  [ -n "${GID0:-}" ] && [ -n "${GID1:-}" ] || { echo "no secondary GID (run gid_blackhole.sh setup first)" >&2; exit 1; }
else
  GID_PROBE='d=/sys/class/infiniband/$1/ports/1
for g in $(ls "$d/gids" | sort -n); do
  [ "$(cat "$d/gid_attrs/types/$g" 2>/dev/null)" = "RoCE v2" ] || continue
  case "$(cat "$d/gids/$g")" in 0000:0000:0000:0000:0000:ffff:1e00:00*) echo "$g"; exit 0;; esac
done; exit 1'
  GID0=$(bash -c "$GID_PROBE" _ mlx5_1) || { echo "no GID on rain" >&2; exit 1; }
  GID1=$(ssh -n "$SUNNY_SSH" bash -c "'$GID_PROBE'" _ mlx5_0) || { echo "no GID on sunny" >&2; exit 1; }
fi
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
[ "$BUILD" = base ] && TSENV="" || TSENV="NCCL_GIN_FAULT_TRANSPARENT=$TS"
NENV="NCCL_DEBUG=${NCCL_DEBUG:-WARN} NCCL_DEBUG_SUBSYS=${NCCL_DEBUG_SUBSYS:-INIT,NET} NCCL_SOCKET_IFNAME=eno1 \
NCCL_GIN_TYPE=3 NCCL_GIN_ENABLE=1 NCCL_IB_TIMEOUT=$IB_TIMEOUT NCCL_GIN_FAULT_CLASSIFY=$CLASSIFY \
NCCL_GIN_FAULT_RECOVERY=$REC $TSENV ${DIAG:+NCCL_GIN_TS_DIAG=$DIAG} GIN_ABORT_WATCHDOG_S=${ABORT_WD_S:-15} \
LD_LIBRARY_PATH=$BUNDLE ${EXTRA_ENV:-}"
ARGS="$ITERS $BYTES $WAIT $MODE $DEV_TIMEOUT_S $WATCHDOG_S"
tag="$BUILD/ts${TS}/$APP/${FAULT}/${WAIT}#${TRIAL}"
echo "[$tag] GID($GIDSEL) rain=$GID0 sunny=$GID1 port=$PORT inject=$INJECT bytes=$BYTES iters=$ITERS cut=${CUT_S:-0}" >&2
ssh -n "$SUNNY_SSH" "cd $BUNDLE && $NENV NCCL_IB_HCA=mlx5_0 NCCL_IB_GID_INDEX=$GID1 ${INJ1:+NCCL_GIN_FAULT_INJECT=$INJ1} ${R1_ENV:-} \
exec stdbuf -oL -eL timeout -s KILL $((WATCHDOG_S+20)) ./$BIN 1 $RAIN_MGMT $PORT $ARGS /tmp/gin_ts2_r1.kv $GAP_US \
> /tmp/gin_ts2_r1.log 2>&1" &
SSH_PID=$!
if [ "$KILL_R1" = 1 ]; then
  KILL_DELAY_MS=${KILL_DELAY_MS:-1200}
  ( sleep "$(awk "BEGIN{print $KILL_DELAY_MS/1000}")"
    ssh -n "$SUNNY_SSH" "pid=\$(pgrep -x $BIN | head -1); [ -n \"\$pid\" ] && python3 -c \"import os,sys,time; t=time.clock_gettime(time.CLOCK_MONOTONIC)*1e3; os.kill(int(sys.argv[1]),9); print('kill_mono_ms=%.3f pid=%s' % (t, sys.argv[1]))\" \$pid" > "$WORK/kill.out" 2>&1
    echo "[$tag] SIGKILL rank1 after ${KILL_DELAY_MS} ms: $(cat "$WORK/kill.out")" >&2 ) &
  KILLER=$!
fi
if [ -n "${CUT_S:-}" ]; then
  # the cut starts CUT_DELAY_MS after rank 0 launched its kernel (bounded wait for the launch line)
  ( launched=0
    for _ in $(seq 1 600); do grep -q launch_mono_ms "$WORK/r0.kv" 2>/dev/null && { launched=1; break; }
      grep -q '^exit=' "$WORK/r0.kv" 2>/dev/null && break; sleep 0.05; done
    [ "$launched" = 1 ] || { echo "cut_s=0 no_launch=1" > "$WORK/cut.out"; echo "[$tag] no kernel launch: no cut" >&2; exit 0; }
    sleep "$(awk "BEGIN{print ${CUT_DELAY_MS:-3000}/1000}")"
    t0=$(python3 -c 'import time; print("%.3f" % (time.clock_gettime(time.CLOCK_MONOTONIC)*1e3))')
    GBH_LOG=$WORK/gbh.log bash "$GBH" cut "$CUT_S" > "$WORK/cut.out" 2>&1
    t1=$(python3 -c 'import time; print("%.3f" % (time.clock_gettime(time.CLOCK_MONOTONIC)*1e3))')
    echo "cut_s=$CUT_S cut_start_mono_ms=$t0 cut_end_mono_ms=$t1 gids_after=$(bash "$GBH" gids 2>/dev/null | tr ' ' '/')" >> "$WORK/cut.out"
    echo "[$tag] cut ${CUT_S}s done: $(tail -1 "$WORK/cut.out")" >&2 ) &
  CUTTER=$!
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
[ "${CUTTER:-}" ] && wait "$CUTTER" 2>/dev/null
scp -q "$SUNNY_SSH:/tmp/gin_ts2_r1.kv" "$WORK/r1.kv" 2>/dev/null || true
scp -q "$SUNNY_SSH:/tmp/gin_ts2_r1.log" "$WORK/r1.log" 2>/dev/null || true
# only our own binary name, exact match (other agents run other binaries)
ssh -n "$SUNNY_SSH" "pgrep -x $BIN | xargs -r kill -9 2>/dev/null; rm -f /tmp/gin_ts2_r1.kv /tmp/gin_ts2_r1.log" || true
pkill -x $BIN 2>/dev/null || true
LEFT=$( { pgrep -x $BIN; ssh -n "$SUNNY_SSH" "pgrep -x $BIN"; } 2>/dev/null | wc -l)
mkdir -p "$LOGDIR"
stem="${CELL:-${BUILD}_ts${TS}_${APP}_${FAULT}_${WAIT}}_${TRIAL}"
for f in r0.log r1.log r0.kv r1.kv kill.out cut.out gbh.log; do [ -f "$WORK/$f" ] && cp "$WORK/$f" "$LOGDIR/${stem}_$f"; done
[ -f "$WORK/lat_raw.csv" ] && gzip -c "$WORK/lat_raw.csv" > "$LOGDIR/${stem}_lat_raw.csv.gz"
echo "cell=${CELL:-} build=$BUILD app=$APP r0env=$(echo ${R0_ENV:-} | tr ' ' '+') r1env=$(echo ${R1_ENV:-} | tr ' ' '+') \
extra=$(echo ${EXTRA_ENV:-} | tr ' ' '+') fault=$FAULT wait=$WAIT trial=$TRIAL ts=$TS rec=$REC classify=$CLASSIFY diag=${DIAG:-} \
inject=$INJECT inject1=${INJECT1:-} iters=$ITERS bytes=$BYTES gap_us=$GAP_US gidsel=$GIDSEL gid0=$GID0 gid1=$GID1 cut_s=${CUT_S:-0} \
cut_delay_ms=${CUT_DELAY_MS:-0} r0rc=$R0RC r1rc=$R1RC left=$LEFT ib_timeout=$IB_TIMEOUT \
wall_s=$(awk "BEGIN{printf \"%.1f\", $T1-$T0}") bundle=$BUNDLE" > "$LOGDIR/${stem}_meta.txt"
echo "[$tag] r0rc=$R0RC r1rc=$R1RC left=$LEFT wall=$(awk "BEGIN{printf \"%.1f\", $T1-$T0}")s :: $(grep -h 'DONE outcome' "$WORK/r0.log" "$WORK/r1.log" 2>/dev/null | sed 's/^.*\] //' | tr '\n' '|')" >&2
rm -rf "$WORK"
exit 0
