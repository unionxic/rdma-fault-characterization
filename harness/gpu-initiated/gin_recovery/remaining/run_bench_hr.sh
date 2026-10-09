#!/usr/bin/env bash
# run_bench_hr.sh - one gin-remaining host-memory benchmark trial (EXPERIMENT.md 9, 4): hm_bench once on rain's GPU and
# once on sunny's GPU, one after the other, inside ../../common/cluster_run.sh (through hold.sh). No NCCL, no network.
# Each run is bounded by `timeout -s KILL 90` (hm_bench has its own 60 s watchdog); nothing is killed by name or PID here.
# usage: run_bench_hr.sh <trial-tag> <logdir>
# env: CELL (hm_bench), BENCHKEY (hr: $HOME/gi-bundle/gin_ts2/$BENCHKEY/hm_bench), N_LAT (20000), RACE_MS (2000)
# files in <logdir>: <stem>_rain.kv, <stem>_sunny.kv, <stem>_meta.txt
set -u
TRIAL=${1:?trial tag}; LOGDIR=${2:?logdir}
BENCHKEY=${BENCHKEY:-hr}; N_LAT=${N_LAT:-20000}; RACE_MS=${RACE_MS:-2000}
SUNNY_SSH=${SUNNY_SSH:-unionxic@192.0.2.194}
BIN=$HOME/gi-bundle/gin_ts2/$BENCHKEY/hm_bench
[ -x "$BIN" ] || { echo "missing $BIN on rain" >&2; exit 1; }
WORK=$(mktemp -d /tmp/gin_hrb_trial.XXXXXX)
RT=/tmp/gin_hrb_$$_$RANDOM.kv   # sunny-side file of this trial
T0=$(date +%s.%N)
timeout -s KILL 90 "$BIN" "$WORK/rain.kv" 0 "$N_LAT" "$RACE_MS" > "$WORK/rain.log" 2>&1
RC0=$?
ssh -n "$SUNNY_SSH" "timeout -s KILL 90 $BIN $RT 0 $N_LAT $RACE_MS > $RT.log 2>&1; echo \$?" > "$WORK/sunny.rc" 2>/dev/null
RC1=$(tr -d '\n' < "$WORK/sunny.rc")
scp -q "$SUNNY_SSH:$RT" "$WORK/sunny.kv" 2>/dev/null || true
scp -q "$SUNNY_SSH:$RT.log" "$WORK/sunny.log" 2>/dev/null || true
ssh -n "$SUNNY_SSH" "rm -f $RT $RT.log" || true
T1=$(date +%s.%N)
mkdir -p "$LOGDIR"
stem="${CELL:-hm_bench}_${TRIAL}"
for f in rain.kv sunny.kv rain.log sunny.log; do [ -f "$WORK/$f" ] && cp "$WORK/$f" "$LOGDIR/${stem}_$f"; done
echo "cell=${CELL:-hm_bench} build=$BENCHKEY trial=$TRIAL n_lat=$N_LAT race_ms=$RACE_MS rc_rain=$RC0 rc_sunny=${RC1:-none} \
runner=hrb wall_s=$(awk -v a="$T0" -v b="$T1" 'BEGIN{printf "%.1f", b - a}') bin=$BIN" > "$LOGDIR/${stem}_meta.txt"
echo "[hm_bench#$TRIAL] rc rain=$RC0 sunny=${RC1:-none} :: $(tr '\n' ' ' < "$WORK/rain.kv" 2>/dev/null | cut -c1-200)" >&2
rm -rf "$WORK"
exit 0
