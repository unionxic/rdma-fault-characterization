#!/usr/bin/env bash
# run_mr.sh - one gin-multirank trial: N processes of gin_mr (the unmodified application), rank r on rain when r is even
# and on sunny when r is odd (interleaved, so NCCL's LSA team has one rank and no rank maps another process's memory;
# EXPERIMENT.md 1). Every cluster action runs inside ../../common/cluster_run.sh (hold.sh via chain.sh); this script
# bounds each process with timeout -s KILL (WATCHDOG_S + 20), whose kill reaches only its own child. It never kills by
# name: the only kill is KILL_RANK's, by the PID recorded right after that rank started (below).
#
# usage: run_mr.sh <trial-tag> <logdir>
# env:
#   N (4)              ranks, 2..6
#   LIB (ow)           recovery build: libnccl from $HOME/gi-bundle/gin_ts2/$LIB (never written here)
#   MRKEY (= LIB)      driver: $HOME/gi-bundle/gin_ts2/mr/$MRKEY/gin_mr (deploy_mr.sh)
#   MODE (none|lat), ITERS (1000), BYTES (4096), GAP_US (15000; lat: 0), WATCHDOG_S (60), ABORT_WD_S (15)
#   EDGES (all)        GIN_MR_EDGES ("a-b,c-d,..."; never ">", a redirection in the remote shell)
#   FLUSH (ctx|peer)   GIN_MR_FLUSH
#   TS (1)             NCCL_GIN_FAULT_TRANSPARENT; REC, CLASSIFY (1)
#   MRGE (1 if N > 2)  NCCL_MULTI_RANK_GPU_ENABLE (0 with N > 2 is the pilot's negative control)
#   R<r>_ENV           extra environment of rank r (fault hooks, test switches); EXTRA_ENV: every rank
#   KILL_RANK, KILL_DELAY_MS   SIGKILL rank KILL_RANK KILL_DELAY_MS after the runner started it. Its timeout's PID is
#                      recorded at the start (rain: our background PID; sunny: the PID our remote shell wrote before
#                      exec); the PID of its gin_mr and of that process's parent are recorded from it (parent links,
#                      pgrep -P) as soon as they exist; the kill goes to that recorded PID only while it is still gin_mr
#                      with the recorded parent (so the PID cannot have been reused); kill.out holds kill_mono_ms (that
#                      node's CLOCK_MONOTONIC), pid, rank, node
#   CELL               stem prefix of the trial files
# files in <logdir>: <stem>_r<r>.log, <stem>_r<r>.kv (every rank), <stem>_kill.out, <stem>_meta.txt
set -u
TRIAL=${1:?trial tag}; LOGDIR=${2:?logdir}
N=${N:-4}; LIB=${LIB:-ow}; MRKEY=${MRKEY:-$LIB}
MODE=${MODE:-none}; ITERS=${ITERS:-1000}; BYTES=${BYTES:-4096}
if [ "$MODE" = lat ]; then GAP_US=${GAP_US:-0}; else GAP_US=${GAP_US:-15000}; fi
WATCHDOG_S=${WATCHDOG_S:-60}; EDGES=${EDGES:-all}; FLUSH=${FLUSH:-ctx}
TS=${TS:-1}; REC=${REC:-1}; CLASSIFY=${CLASSIFY:-1}; IB_TIMEOUT=${IB_TIMEOUT:-14}
if [ "$N" -gt 2 ]; then MRGE=${MRGE:-1}; else MRGE=${MRGE:-0}; fi
[ "$N" -ge 2 ] && [ "$N" -le 6 ] || { echo "N must be 2..6" >&2; exit 1; }
RAIN_MGMT=192.0.2.193
SUNNY_SSH=${SUNNY_SSH:-unionxic@192.0.2.194}
LIBDIR=/home/unionxic/gi-bundle/gin_ts2/$LIB
MRBIN=/home/unionxic/gi-bundle/gin_ts2/mr/$MRKEY/gin_mr
BIN=gin_mr
[ -x "$MRBIN" ] && [ -f "$LIBDIR/libnccl.so.2" ] || { echo "missing $MRBIN or $LIBDIR/libnccl.so.2 on rain" >&2; exit 1; }
PORT=$(( 46000 + ($$ + RANDOM) % 3000 ))
WORK=$(mktemp -d /tmp/gin_mr_trial.XXXXXX)
RT=/tmp/gin_mr_$$_$RANDOM   # sunny-side file prefix of this trial
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
GIN_MR_EDGES=$EDGES GIN_MR_FLUSH=$FLUSH GIN_ABORT_WATCHDOG_S=${ABORT_WD_S:-15} LD_LIBRARY_PATH=$LIBDIR ${EXTRA_ENV:-}"
ARGS="$N $RAIN_MGMT $PORT $ITERS $BYTES $MODE $WATCHDOG_S"
tag="$LIB/n$N/$MODE/${CELL:-mr}#$TRIAL"
echo "[$tag] gid rain=$GID0 sunny=$GID1 port=$PORT edges=$EDGES flush=$FLUSH kill=${KILL_RANK:--}" >&2
renv() { local v="R${1}_ENV"; echo "${!v:-}"; }
declare -A PID LT
T0=$(date +%s.%N)
launch() {  # launch <r>
  local r=$1 e; e=$(renv "$r")
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
for ((r = 1; r < N; r += 2)); do
  scp -q "$SUNNY_SSH:$RT.r$r.kv" "$WORK/r$r.kv" 2>/dev/null || true
  scp -q "$SUNNY_SSH:$RT.r$r.log" "$WORK/r$r.log" 2>/dev/null || true
done
# nothing is killed here: every rank's timeout has exited (wait above), so its gin_mr has ended too. Our sunny-side files
# go; LEFT is a read-only count of gin_mr processes still present on either node (expected 0; two in a row stop the run)
ssh -n "$SUNNY_SSH" "rm -f $RT.r*.kv $RT.r*.log $RT.r*.pid $RT.r*.cpid" || true
LEFT=$( { pgrep -x $BIN; ssh -n "$SUNNY_SSH" "pgrep -x $BIN"; } 2>/dev/null | wc -l)
mkdir -p "$LOGDIR"
stem="${CELL:-mr_n${N}_${MODE}}_${TRIAL}"
for ((r = 0; r < N; r++)); do
  for f in log kv; do [ -f "$WORK/r$r.$f" ] && cp "$WORK/r$r.$f" "$LOGDIR/${stem}_r$r.$f"; done
done
[ -f "$WORK/kill.out" ] && cp "$WORK/kill.out" "$LOGDIR/${stem}_kill.out"
rcs=""; envs=""
for ((r = 0; r < N; r++)); do rcs="$rcs r${r}rc=${RC[$r]}"; envs="$envs r${r}env=$(renv "$r" | tr ' ' '+')"; done
echo "cell=${CELL:-} lib=$LIB mrkey=$MRKEY n=$N mode=$MODE flush=$FLUSH edges=$EDGES iters=$ITERS bytes=$BYTES gap_us=$GAP_US \
trial=$TRIAL ts=$TS rec=$REC classify=$CLASSIFY mrge=$MRGE ib_timeout=$IB_TIMEOUT kill_rank=${KILL_RANK:-} \
kill_delay_ms=${KILL_DELAY_MS:-} extra=$(echo ${EXTRA_ENV:-} | tr ' ' '+')$envs$rcs left=$LEFT gid0=$GID0 gid1=$GID1 \
port=$PORT wall_s=$(awk -v a="$T0" -v b="$T1" 'BEGIN{printf "%.1f", b - a}') libdir=$LIBDIR mrbin=$MRBIN" > "$LOGDIR/${stem}_meta.txt"
echo "[$tag]$rcs left=$LEFT wall=$(awk -v a="$T0" -v b="$T1" 'BEGIN{printf "%.1f", b - a}')s :: $(grep -h 'DONE outcome' "$WORK"/r*.log 2>/dev/null | sed 's/^.*\] //' | tr '\n' '|')" >&2
rm -rf "$WORK"
exit 0
