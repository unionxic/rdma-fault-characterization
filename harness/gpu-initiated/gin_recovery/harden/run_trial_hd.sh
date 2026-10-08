#!/usr/bin/env bash
# run_trial_hd.sh - one gin-harden trial (rank 0 = rain, rank 1 = sunny), inside ../../common/cluster_run.sh (through
# hold.sh). Derived from ../scripts/ts2/run_trial.sh (same arguments, same per-trial files, same meta line plus a few
# keys) with these differences:
#   - processes are only ever killed by a PID this script recorded: rank 0 runs under a `timeout` whose PID is kept
#     ($R0PID); rank 1's remote shell writes its own PID (the `timeout` it execs into) to a per-trial file. A kill or a
#     cleanup signals that PID's children and the PID itself. Nothing is killed or counted by process name.
#   - rank 1's files on sunny are per trial (/tmp/gin_hd_<tag>.*), not shared fixed names.
#   - no address flap (no RoCE address change) and no secondary GIDs.
#   - MGMT_MUTE=<start ms>:<len ms> with MGMT_PORT=<p> (gin-harden production cells): from <start> ms after rank 0's
#     kernel launch, for <len> ms, rain drops incoming TCP from sunny's management address to or from ports p..p+15 (the
#     helper sockets of NCCL_GIN_TS_PORT=p) with two iptables INPUT rules tagged "gin-harden-<pid>"; they are removed at
#     the end of the window, again on exit (trap), and checked to be gone (mute.out). The mute is skipped (mute.out
#     mute_skipped=...) if `sudo -n iptables` fails or any socket on rain in that port range belongs to a process other
#     than this trial's rank 0.
#
# usage: run_trial_hd.sh <none|F1|F2|F3|F4|F1both|lat> <timeout|blocking> <trial-tag> <logdir> [iters] [bytes]
# env knobs (as run_trial.sh): APP=default|burst|bidir, BUILD (bundle directory under $HOME/gi-bundle/gin_ts2), TS, REC,
#   CLASSIFY, INJECT, INJECT1, R0_ENV, R1_ENV, EXTRA_ENV, KILL_DELAY_MS (F4: rank 1; default 1200), KILL_R0=1 (rank 0,
#   KILL_DELAY_MS after its launch), GAP_US, DEV_TIMEOUT_S (8), WATCHDOG_S (45), IB_TIMEOUT (14), DIAG, ABORT_WD_S (15),
#   NCCL_DEBUG, NCCL_DEBUG_SUBSYS
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
BIN=gin_ts2
PORT=$(( 46000 + ($$ + RANDOM) % 3000 ))
WORK=$(mktemp -d /tmp/gin_hd_trial.XXXXXX)
RTAG=gin_hd_$(hostname -s)_$$_$RANDOM
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
LD_LIBRARY_PATH=$BUNDLE ${EXTRA_ENV:-}"
ARGS="$ITERS $BYTES $WAIT $MODE $DEV_TIMEOUT_S $WATCHDOG_S"
tag="$BUILD/ts${TS}/$APP/${FAULT}/${WAIT}#${TRIAL}"
echo "[$tag] rain=$GID0 sunny=$GID1 port=$PORT inject=$INJECT bytes=$BYTES iters=$ITERS rtag=$RTAG" >&2
# rank 1: the remote shell records its own PID, then execs into `timeout`, whose child is gin_ts2
ssh -n "$SUNNY_SSH" "cd $BUNDLE && echo \$\$ > $R1PIDF && $NENV NCCL_IB_HCA=mlx5_0 NCCL_IB_GID_INDEX=$GID1 \
${INJ1:+NCCL_GIN_FAULT_INJECT=$INJ1} ${R1_ENV:-} exec stdbuf -oL -eL timeout -s KILL $((WATCHDOG_S+20)) ./$BIN 1 $RAIN_MGMT \
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
  stdbuf -oL -eL timeout -s KILL $((WATCHDOG_S+20)) "$BUNDLE/$BIN" 0 "$RAIN_MGMT" $PORT $ARGS "$WORK/r0.kv" $GAP_US \
  > "$WORK/r0.log" 2>&1 &
R0PID=$!
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
# management mute on rain (production cells): two INPUT DROP rules, from sunny's management address only, ports
# MGMT_PORT..MGMT_PORT+15, removed at the end of the window and on exit
MUTE_TAG=gin-harden-$$
MUTE_ON=0
mute_off() {  # delete this trial's two rules (each independently, up to 3 times; absent rules are fine)
  [ "$MUTE_ON" = 1 ] || return 0
  local lo=${MGMT_PORT:?MGMT_PORT}; local hi=$(( lo + 15 )) k d
  for k in 1 2 3; do
    for d in --sport --dport; do
      sudo -n iptables -w 5 -D INPUT -s "$SUNNY_HOST" -p tcp "$d" "$lo:$hi" -m comment --comment "$MUTE_TAG" -j DROP 2>/dev/null
    done
  done
  MUTE_ON=0
}
trap 'mute_off' EXIT
if [ -n "${MGMT_MUTE:-}" ]; then
  ( ms=${MGMT_MUTE%%:*}; len=${MGMT_MUTE#*:}
    launched=0
    for _ in $(seq 1 1200); do grep -q launch_mono_ms "$WORK/r0.kv" 2>/dev/null && { launched=1; break; }
      kill -0 "$R0PID" 2>/dev/null || break; sleep 0.05; done
    [ "$launched" = 1 ] || { echo "mute_skipped=no_launch" > "$WORK/mute.out"; exit 0; }
    if ! sudo -n iptables -w 5 -S INPUT > /dev/null 2>&1; then echo "mute_skipped=no_iptables" > "$WORK/mute.out"; exit 0; fi
    sleep "$(awk "BEGIN{print $ms/1000}")"
    # every socket on rain in the port range must belong to this trial's rank 0
    r0=$(pgrep -P "$R0PID" -x $BIN | head -1)
    lo=${MGMT_PORT:?}; hi=$(( lo + 15 ))
    # (closing remnants without an owner, e.g. TIME-WAIT of an earlier trial, carry no traffic and are not counted)
    foreign=$(ss -tanpH 2>/dev/null | awk -v lo="$lo" -v hi="$hi" -v me="pid=$r0," '
      $1 ~ /^(LISTEN|ESTAB|SYN-SENT|SYN-RECV|CLOSE-WAIT)$/ {
        split($4, a, ":"); split($5, b, ":"); lp = a[length(a)] + 0; rp = b[length(b)] + 0;
        if (((lp >= lo && lp <= hi) || (rp >= lo && rp <= hi)) && index($0, me) == 0) n++ } END { print n + 0 }')
    if [ -z "$r0" ] || [ "$foreign" != 0 ]; then echo "mute_skipped=port_busy foreign=$foreign r0=$r0" > "$WORK/mute.out"; exit 0; fi
    t0=$(python3 -c 'import time; print("%.3f" % (time.clock_gettime(time.CLOCK_MONOTONIC)*1e3))')
    lo2=$lo; tagc=$MUTE_TAG
    sudo -n iptables -w 5 -I INPUT -s "$SUNNY_HOST" -p tcp --sport "$lo:$hi" -m comment --comment "$tagc" -j DROP
    sudo -n iptables -w 5 -I INPUT -s "$SUNNY_HOST" -p tcp --dport "$lo:$hi" -m comment --comment "$tagc" -j DROP
    n_on=$(sudo -n iptables -w 5 -S INPUT | grep -c -- "$tagc")
    sleep "$(awk "BEGIN{print $len/1000}")"
    for k in 1 2 3; do
      sudo -n iptables -w 5 -D INPUT -s "$SUNNY_HOST" -p tcp --sport "$lo:$hi" -m comment --comment "$tagc" -j DROP 2>/dev/null
      sudo -n iptables -w 5 -D INPUT -s "$SUNNY_HOST" -p tcp --dport "$lo:$hi" -m comment --comment "$tagc" -j DROP 2>/dev/null
    done
    t1=$(python3 -c 'import time; print("%.3f" % (time.clock_gettime(time.CLOCK_MONOTONIC)*1e3))')
    n_off=$(sudo -n iptables -w 5 -S INPUT | grep -c -- "$tagc")
    echo "mute_on_mono_ms=$t0 mute_off_mono_ms=$t1 mute_rules_on=$n_on mute_rules_left=$n_off ports=$lo2-$hi" > "$WORK/mute.out"
  ) &
  MUTER=$!
  MUTE_ON=1  # the trap removes the rules if this script exits before the subshell does
fi
wait "$R0PID"
R0RC=$?
[ "${KILLER0:-}" ] && wait "$KILLER0" 2>/dev/null
T1=$(date +%s.%N)
wait "$SSH_PID" 2>/dev/null; R1RC=$?
[ "${KILLER:-}" ] && wait "$KILLER" 2>/dev/null
[ "${MUTER:-}" ] && wait "$MUTER" 2>/dev/null
mute_off
scp -q "$SUNNY_SSH:$R1KV" "$WORK/r1.kv" 2>/dev/null || true
scp -q "$SUNNY_SSH:$R1LOG" "$WORK/r1.log" 2>/dev/null || true
# cleanup: only the recorded remote PID and its children, and only while that PID is still this trial's `timeout` (its
# command line carries the trial's unique file tag), so a reused PID is never signalled. Rank 0's `timeout` was waited
# for above (its gin_ts2 child ends with it or before it): nothing local to kill. Leftovers are counted by the trial's
# unique tag in the command line (counting only).
ssh -n "$SUNNY_SSH" "tp=\$(cat $R1PIDF 2>/dev/null); if [ -n \"\$tp\" ] && grep -q $RTAG /proc/\$tp/cmdline 2>/dev/null; then \
for c in \$(pgrep -P \"\$tp\"); do kill -9 \$c 2>/dev/null; done; kill -9 \$tp 2>/dev/null; fi; rm -f $R1KV $R1LOG" || true
LEFT=$( { pgrep -f "$WORK/r0.kv" 2>/dev/null; ssh -n "$SUNNY_SSH" "pgrep -f $RTAG; rm -f $R1PIDF"; } 2>/dev/null | wc -l)
LEFT_RULES=$(sudo -n iptables -w 5 -S INPUT 2>/dev/null | grep -c -- "$MUTE_TAG")
mkdir -p "$LOGDIR"
stem="${CELL:-${BUILD}_ts${TS}_${APP}_${FAULT}_${WAIT}}_${TRIAL}"
for f in r0.log r1.log r0.kv r1.kv kill.out mute.out; do [ -f "$WORK/$f" ] && cp "$WORK/$f" "$LOGDIR/${stem}_$f"; done
[ -f "$WORK/lat_raw.csv" ] && gzip -c "$WORK/lat_raw.csv" > "$LOGDIR/${stem}_lat_raw.csv.gz"
echo "cell=${CELL:-} build=$BUILD app=$APP r0env=$(echo ${R0_ENV:-} | tr ' ' '+') r1env=$(echo ${R1_ENV:-} | tr ' ' '+') \
extra=$(echo ${EXTRA_ENV:-} | tr ' ' '+') fault=$FAULT wait=$WAIT trial=$TRIAL ts=$TS rec=$REC classify=$CLASSIFY diag=${DIAG:-} \
inject=$INJECT inject1=${INJECT1:-} iters=$ITERS bytes=$BYTES gap_us=$GAP_US gidsel=primary gid0=$GID0 gid1=$GID1 cut_s=0 \
cut_delay_ms=0 r0rc=$R0RC r1rc=$R1RC left=$LEFT ib_timeout=$IB_TIMEOUT kill_r0=${KILL_R0:-0} kill_delay_ms=${KILL_DELAY_MS:-} \
mgmt_mute=${MGMT_MUTE:-} mgmt_port=${MGMT_PORT:-} left_rules=$LEFT_RULES runner=hd \
wall_s=$(awk "BEGIN{printf \"%.1f\", $T1-$T0}") bundle=$BUNDLE" > "$LOGDIR/${stem}_meta.txt"
echo "[$tag] r0rc=$R0RC r1rc=$R1RC left=$LEFT left_rules=$LEFT_RULES wall=$(awk "BEGIN{printf \"%.1f\", $T1-$T0}")s :: $(grep -h 'DONE outcome' "$WORK/r0.log" "$WORK/r1.log" 2>/dev/null | sed 's/^.*\] //' | tr '\n' '|')" >&2
rm -rf "$WORK"
exit 0
