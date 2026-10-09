#!/usr/bin/env bash
# run_ngt_hr.sh - one gin-remaining NIC gate trial (EXPERIMENT.md 9, 5): nic_gate_test once on rain (GPU 0, mlx5_1) and
# once on sunny (GPU 0, mlx5_0), one after the other, inside ../../common/cluster_run.sh (through hold.sh). No NCCL; a
# loopback RC QP pair on the node's own HCA (no traffic leaves the NIC). Each run is bounded by `timeout -s KILL 90`
# (nic_gate_test has its own 75 s watchdog); nothing is killed by name or PID here. A copy of run_bench_hr.sh with the
# binary and its arguments changed.
# usage: run_ngt_hr.sh <trial-tag> <logdir>
# env: CELL (nic_gate), NGTKEY (ngt: $HOME/gi-bundle/gin_ts2/$NGTKEY/nic_gate_test), NGT_SECS (5: seconds per phase),
#      HCA0 (mlx5_1), HCA1 (mlx5_0)
# files in <logdir>: <stem>_rain.kv, <stem>_sunny.kv, <stem>_rain.log, <stem>_sunny.log, <stem>_meta.txt
set -u
TRIAL=${1:?trial tag}; LOGDIR=${2:?logdir}
NGTKEY=${NGTKEY:-ngt}; NGT_SECS=${NGT_SECS:-5}; HCA0=${HCA0:-mlx5_1}; HCA1=${HCA1:-mlx5_0}
SUNNY_SSH=${SUNNY_SSH:-unionxic@192.0.2.194}
BIN=$HOME/gi-bundle/gin_ts2/$NGTKEY/nic_gate_test
[ -x "$BIN" ] || { echo "missing $BIN on rain" >&2; exit 1; }
WORK=$(mktemp -d /tmp/gin_hrg_trial.XXXXXX)
RT=/tmp/gin_hrg_$$_$RANDOM.kv   # sunny-side file of this trial
T0=$(date +%s.%N)
timeout -s KILL 90 "$BIN" "$WORK/rain.kv" "$HCA0" "$NGT_SECS" -1 0 > "$WORK/rain.log" 2>&1
RC0=$?
ssh -n "$SUNNY_SSH" "timeout -s KILL 90 $BIN $RT $HCA1 $NGT_SECS -1 0 > $RT.log 2>&1; echo \$?" > "$WORK/sunny.rc" 2>/dev/null
RC1=$(tr -d '\n' < "$WORK/sunny.rc")
scp -q "$SUNNY_SSH:$RT" "$WORK/sunny.kv" 2>/dev/null || true
scp -q "$SUNNY_SSH:$RT.log" "$WORK/sunny.log" 2>/dev/null || true
ssh -n "$SUNNY_SSH" "rm -f $RT $RT.log" || true
T1=$(date +%s.%N)
mkdir -p "$LOGDIR"
stem="${CELL:-nic_gate}_${TRIAL}"
for f in rain.kv sunny.kv rain.log sunny.log; do [ -f "$WORK/$f" ] && cp "$WORK/$f" "$LOGDIR/${stem}_$f"; done
echo "cell=${CELL:-nic_gate} build=hr trial=$TRIAL secs=$NGT_SECS hca_rain=$HCA0 hca_sunny=$HCA1 rc_rain=$RC0 \
rc_sunny=${RC1:-none} runner=hrg wall_s=$(awk -v a="$T0" -v b="$T1" 'BEGIN{printf "%.1f", b - a}') bin=$BIN" \
  > "$LOGDIR/${stem}_meta.txt"
echo "[nic_gate#$TRIAL] rc rain=$RC0 sunny=${RC1:-none} :: $(grep -ho 'result=[A-Z]*\|setup_error=[^ ]*\|nic_error=[^ ]*' \
  "$WORK/rain.kv" "$WORK/sunny.kv" 2>/dev/null | tr '\n' ' ')" >&2
rm -rf "$WORK"
exit 0
