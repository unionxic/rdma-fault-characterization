#!/usr/bin/env bash
# run_mr_hq.sh - one gin-peer N-rank trial: N processes of gin_mr (the unmodified application), rank r on rain when r is
# even and on sunny when r is odd (interleaved; ../multirank/EXPERIMENT.md 1). A copy of ../multirank/run_mr.sh (same
# arguments, same per-trial files, same meta line plus a few keys; that script is not changed) with these differences:
#   - the port fix (portpick.sh): the rendezvous port is drawn below the ephemeral range and checked unused on both
#     nodes; every trial gets a random rendezvous nonce (GIN_RDV_NONCE; this study's gin_mr verifies the rendezvous
#     before sending anything); RDV_DECOY=1 and PORT_OCCUPY=1 as in run_trial_hq.sh (the decoy is tried by every rank
#     r > 0);
#   - rank 0's management address is looked up at run time (the route to sunny's management address), not written here.
# Every cluster action runs inside ../../common/cluster_run.sh (hold.sh via chain.sh); each process is bounded by
# timeout -s KILL (WATCHDOG_S + 20), whose kill reaches only its own child. Nothing is killed by name: the only kill is
# KILL_RANK's, by the PID recorded right after that rank started (below); the occupier and the decoy are stopped by the
# PIDs of their `timeout` wrappers.
#
# usage: run_mr_hq.sh <trial-tag> <logdir>
# env: N (4), LIB (hq: libnccl from $HOME/gi-bundle/gin_ts2/$LIB), MRKEY (hq: driver $HOME/gi-bundle/gin_ts2/mr/$MRKEY/gin_mr),
#   MODE (none|lat), ITERS (1000), BYTES (4096), GAP_US (15000; lat: 0), WATCHDOG_S (60), ABORT_WD_S (15), EDGES (all),
#   FLUSH (ctx|peer), TS, REC, CLASSIFY (1), MRGE (1 if N > 2), R<r>_ENV, EXTRA_ENV, KILL_RANK, KILL_DELAY_MS, CELL,
#   PORT_LO, PORT_HI, RDV_DECOY, PORT_OCCUPY
# files in <logdir>: <stem>_r<r>.log, <stem>_r<r>.kv (every rank), <stem>_kill.out, <stem>_decoy.out, <stem>_meta.txt
set -u
TRIAL=${1:?trial tag}; LOGDIR=${2:?logdir}
N=${N:-4}; LIB=${LIB:-hq}; MRKEY=${MRKEY:-hq}
MODE=${MODE:-none}; ITERS=${ITERS:-1000}; BYTES=${BYTES:-4096}
if [ "$MODE" = lat ]; then GAP_US=${GAP_US:-0}; else GAP_US=${GAP_US:-15000}; fi
WATCHDOG_S=${WATCHDOG_S:-60}; EDGES=${EDGES:-all}; FLUSH=${FLUSH:-ctx}
TS=${TS:-1}; REC=${REC:-1}; CLASSIFY=${CLASSIFY:-1}; IB_TIMEOUT=${IB_TIMEOUT:-14}
if [ "$N" -gt 2 ]; then MRGE=${MRGE:-1}; else MRGE=${MRGE:-0}; fi
[ "$N" -ge 2 ] && [ "$N" -le 6 ] || { echo "N must be 2..6" >&2; exit 1; }
SUNNY_SSH=${SUNNY_SSH:-unionxic@192.0.2.194}
SUNNY_HOST=${SUNNY_SSH#*@}
RAIN_MGMT=$(ip -4 route get "$SUNNY_HOST" 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p' | head -1)
[ -n "$RAIN_MGMT" ] || { echo "cannot find rain's management address" >&2; exit 1; }
LIBDIR=$HOME/gi-bundle/gin_ts2/$LIB
MRBIN=$HOME/gi-bundle/gin_ts2/mr/$MRKEY/gin_mr
BIN=gin_mr
[ -x "$MRBIN" ] && [ -f "$LIBDIR/libnccl.so.2" ] || { echo "missing $MRBIN or $LIBDIR/libnccl.so.2 on rain" >&2; exit 1; }
WORK=$(mktemp -d /tmp/gin_mrq_trial.XXXXXX)
RT=/tmp/gin_mrq_$$_$RANDOM   # sunny-side file prefix of this trial
D=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=portpick.sh
. "$D/portpick.sh"
OCC_PORT=""; OCC_PID=""; DECOY_PID=""; DECOY_PORT=""
if [ "${PORT_OCCUPY:-0}" = 1 ]; then
  first=$(( PORT_LO + ($$ + RANDOM) % (PORT_HI - PORT_LO + 1) ))
  pick_port "$first"; OCC_PORT=$PORT
  start_occupier "$OCC_PORT" || echo "occupier on $OCC_PORT did not listen" >&2
  pick_port "$OCC_PORT"
else
  pick_port
fi
RDV_NONCE=$(new_nonce)
DECOY_ENV=""
if [ "${RDV_DECOY:-0}" = 1 ]; then
  save=$PORT; savet=$PORT_TRIES; saves=$PORT_SKIPPED
  pick_port $(( PORT + 1 > PORT_HI ? PORT_LO : PORT + 1 )); DECOY_PORT=$PORT
  PORT=$save; PORT_TRIES=$savet; PORT_SKIPPED=$saves
  start_decoy "$DECOY_PORT" "$WORK/decoy.out" || echo "decoy on $DECOY_PORT did not listen" >&2
  DECOY_ENV="GIN_RDV_TEST_DECOY_PORT=$DECOY_PORT"
fi
cleanup_aux() { stop_pid "$OCC_PID" TERM; OCC_PID=""; stop_pid "$DECOY_PID" TERM; DECOY_PID=""; }
trap 'cleanup_aux' EXIT
GID_PROBE='d=/sys/class/infiniband/$1/ports/1
for g in $(ls "$d/gids" | sort -n); do
  [ "$(cat "$d/gid_attrs/types/$g" 2>/dev/null)" = "RoCE v2" ] || continue
  case "$(cat "$d/gids/$g")" in 0000:0000:0000:0000:0000:ffff:1e00:00*) echo "$g"; exit 0;; esac
done; exit 1'
GID0=$(bash -c "$GID_PROBE" _ mlx5_1) || { echo "no GID on rain" >&2; exit 1; }
GID1=$(ssh -n "$SUNNY_SSH" bash -c "'$GID_PROBE'" _ mlx5_0) || { echo "no GID on sunny" >&2; exit 1; }
NENV="NCCL_DEBUG=${NCCL_DEBUG:-WARN} NCCL_DEBUG_SUBSYS=${NCCL_DEBUG_SUBSYS:-INIT,NET} NCCL_SOCKET_IFNAME=eno1 \
NCCL_GIN_TYPE=3 NCCL_GIN_ENABLE=1 NCCL_IB_TIMEOUT=$IB_TIMEOUT NCCL_GIN_FAULT_CLASSIFY=$CLASSIFY \
NCCL_GIN_FAULT_RECOVERY=$REC NCCL_GIN_FAULT_TRANSPARENT=$TS NCCL_MULTI_RANK_GPU_ENABLE=$MRGE \
GIN_MR_EDGES=$EDGES GIN_MR_FLUSH=$FLUSH GIN_ABORT_WATCHDOG_S=${ABORT_WD_S:-15} GIN_RDV_NONCE=$RDV_NONCE \
LD_LIBRARY_PATH=$LIBDIR ${EXTRA_ENV:-}"
ARGS="$N $RAIN_MGMT $PORT $ITERS $BYTES $MODE $WATCHDOG_S"
tag="$LIB/$MRKEY/n$N/$MODE/${CELL:-mr}#$TRIAL"
echo "[$tag] gid rain=$GID0 sunny=$GID1 port=$PORT tries=$PORT_TRIES skipped=${PORT_SKIPPED:--} decoy=${DECOY_PORT:--} edges=$EDGES flush=$FLUSH kill=${KILL_RANK:--}" >&2
renv() { local v="R${1}_ENV"; echo "${!v:-}"; }
declare -A PID LT
T0=$(date +%s.%N)
launch() {  # launch <r>
  local r=$1 e; e=$(renv "$r")
  [ "$r" -gt 0 ] && e="$DECOY_ENV $e"
  LT[$r]=$(date +%s.%N)
  if [ $((r % 2)) -eq 1 ]; then
    ssh -n "$SUNNY_SSH" "cd $LIBDIR && echo \$\$ > $RT.r$r.pid && $NENV NCCL_IB_HCA=mlx5_0 NCCL_IB_GID_INDEX=$GID1 $e \
exec stdbuf -oL -eL timeout -s KILL $((WATCHDOG_S + 20)) $MRBIN $r $ARGS $RT.r$r.kv $GAP_US > $RT.r$r.log 2>&1" &
  else
    env $NENV NCCL_IB_HCA=mlx5_1 NCCL_IB_GID_INDEX=$GID0 $e \
      stdbuf -oL -eL timeout -s KILL $((WATCHDOG_S + 20)) "$MRBIN" "$r" $ARGS "$WORK/r$r.kv" "$GAP_US" > "$WORK/r$r.log" 2>&1 &
  fi
  PID[$r]=$!
}
for ((r = N - 1; r >= 1; r--)); do launch $r; done
launch 0
if [ -n "$OCC_PID" ]; then stop_pid "$OCC_PID" TERM; OCC_PID=""; fi  # the pick is done: the occupier has served
KILLER=""
if [ -n "${KILL_RANK:-}" ]; then
  KR=$KILL_RANK
  # record the PID of KR's gin_mr and of its parent: a descendant (child or grandchild) of the PID we recorded at its
  # start, found through the parent links (pgrep -P) and recognised by /proc/<pid>/comm; up to 20 s
  PIDREC='for i in $(seq 1 200); do for a in "$1" $(pgrep -P "$1"); do for c in $(pgrep -P "$a"); do
[ "$(cat /proc/$c/comm 2>/dev/null)" = gin_mr ] && { echo "$c $a" > "$2"; exit 0; }; done; done; sleep 0.1; done; exit 1'
  if [ $((KR % 2)) -eq 1 ]; then
    ssh -n "$SUNNY_SSH" "for i in \$(seq 1 50); do [ -s $RT.r$KR.pid ] && break; sleep 0.1; done; \
bash -c '$PIDREC' _ \$(cat $RT.r$KR.pid) $RT.r$KR.cpid" &
  else
    bash -c "$PIDREC" _ "${PID[$KR]}" "$WORK/kill_target.pid" &
  fi
  RECORDER=$!
  ( sleep "$(awk -v a="${LT[$KR]}" -v d="${KILL_DELAY_MS:-6500}" -v n="$(date +%s.%N)" \
              'BEGIN{s = a + d / 1000 - n; if (s < 0) s = 0; print s}')"
    # kill the recorded PID only while it is still the child of the recorded timeout (no PID reuse)
    PYK='import os,sys,time; c,p=int(sys.argv[1]),sys.argv[2]; s=open("/proc/%d/stat"%c).read(); assert s[s.index("(")+1:s.rindex(")")]=="gin_mr" and s.rsplit(")",1)[1].split()[1]==p, "not the recorded process"; t=time.clock_gettime(time.CLOCK_MONOTONIC)*1e3; os.kill(c,9); print("kill_mono_ms=%.3f pid=%d rank=%s node=%s" % (t, c, sys.argv[3], sys.argv[4]))'
    if [ $((KR % 2)) -eq 1 ]; then
      ssh -n "$SUNNY_SSH" "for i in \$(seq 1 50); do [ -s $RT.r$KR.cpid ] && break; sleep 0.1; done; \
read c p < $RT.r$KR.cpid 2>/dev/null; \
if [ -n \"\$c\" ] && [ -n \"\$p\" ]; then python3 -c '$PYK' \"\$c\" \"\$p\" $KR sunny; else echo no_process=1 rank=$KR; fi"
    else
      for i in $(seq 1 50); do [ -s "$WORK/kill_target.pid" ] && break; sleep 0.1; done
      read -r c p < "$WORK/kill_target.pid" 2>/dev/null
      if [ -n "${c:-}" ] && [ -n "${p:-}" ]; then python3 -c "$PYK" "$c" "$p" "$KR" rain; else echo "no_process=1 rank=$KR"; fi
    fi > "$WORK/kill.out" 2>&1
    echo "[$tag] SIGKILL rank $KR after ${KILL_DELAY_MS:-6500} ms: $(cat "$WORK/kill.out")" >&2 ) &
  KILLER=$!
fi
declare -A RC
for ((r = 0; r < N; r++)); do wait "${PID[$r]}" 2>/dev/null; RC[$r]=$?; done
T1=$(date +%s.%N)
[ -n "$KILLER" ] && wait "$KILLER" "$RECORDER" 2>/dev/null
cleanup_aux
for ((r = 1; r < N; r += 2)); do
  scp -q "$SUNNY_SSH:$RT.r$r.kv" "$WORK/r$r.kv" 2>/dev/null || true
  scp -q "$SUNNY_SSH:$RT.r$r.log" "$WORK/r$r.log" 2>/dev/null || true
done
# nothing is killed here: every rank's timeout has exited (wait above), so its gin_mr has ended too. Our sunny-side files
# go; LEFT is a read-only count of gin_mr processes still present on either node (expected 0; two in a row stop the run)
ssh -n "$SUNNY_SSH" "rm -f $RT.r*.kv $RT.r*.log $RT.r*.pid $RT.r*.cpid" || true
LEFT=$( { pgrep -x $BIN; ssh -n "$SUNNY_SSH" "pgrep -x $BIN"; } 2>/dev/null | wc -l)
OCC_SKIPPED=0
[ -n "$OCC_PORT" ] && [ "$PORT" != "$OCC_PORT" ] && case ",$PORT_SKIPPED," in *",$OCC_PORT,"*) OCC_SKIPPED=1 ;; esac
mkdir -p "$LOGDIR"
stem="${CELL:-mr_n${N}_${MODE}}_${TRIAL}"
for ((r = 0; r < N; r++)); do
  for f in log kv; do [ -f "$WORK/r$r.$f" ] && cp "$WORK/r$r.$f" "$LOGDIR/${stem}_r$r.$f"; done
done
[ -f "$WORK/kill.out" ] && cp "$WORK/kill.out" "$LOGDIR/${stem}_kill.out"
[ -f "$WORK/decoy.out" ] && cp "$WORK/decoy.out" "$LOGDIR/${stem}_decoy.out"
rcs=""; envs=""
for ((r = 0; r < N; r++)); do rcs="$rcs r${r}rc=${RC[$r]}"; envs="$envs r${r}env=$(renv "$r" | tr ' ' '+')"; done
echo "cell=${CELL:-} lib=$LIB mrkey=$MRKEY n=$N mode=$MODE flush=$FLUSH edges=$EDGES iters=$ITERS bytes=$BYTES gap_us=$GAP_US \
trial=$TRIAL ts=$TS rec=$REC classify=$CLASSIFY mrge=$MRGE ib_timeout=$IB_TIMEOUT kill_rank=${KILL_RANK:-} \
kill_delay_ms=${KILL_DELAY_MS:-} extra=$(echo ${EXTRA_ENV:-} | tr ' ' '+')$envs$rcs left=$LEFT gid0=$GID0 gid1=$GID1 \
port=$PORT port_lo=$PORT_LO port_hi=$PORT_HI port_tries=$PORT_TRIES port_skipped=${PORT_SKIPPED:-none} \
occupy_port=${OCC_PORT:-none} occupy_skipped=$OCC_SKIPPED decoy_port=${DECOY_PORT:-none} rdv_nonce_set=1 runner=mrq \
wall_s=$(awk -v a="$T0" -v b="$T1" 'BEGIN{printf "%.1f", b - a}') libdir=$LIBDIR mrbin=$MRBIN" > "$LOGDIR/${stem}_meta.txt"
echo "[$tag]$rcs left=$LEFT wall=$(awk -v a="$T0" -v b="$T1" 'BEGIN{printf "%.1f", b - a}')s :: $(grep -h 'DONE outcome' "$WORK"/r*.log 2>/dev/null | sed 's/^.*\] //' | tr '\n' '|')" >&2
rm -rf "$WORK"
exit 0
