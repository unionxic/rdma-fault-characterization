#!/usr/bin/env bash
# launcher_gc.sh - gin-control, test side: one node's launcher (../launcher/gin_launcher, ../../EXPERIMENT.md 5 and 9.5) for
# hold_gc.sh (one launcher per node per hold, EXPERIMENT 5) and run_cost_gc.sh (one per node per cost run). Run only by the main
# session, inside ../../../../common/cluster_run.sh through chain_gc.sh / hold_gc.sh.
#
#   launcher_gc.sh start <rain|sunny> <dir> <tag> [K=V ...]   start it, wait for its "listening" line, write <dir>/la_<tag>_<node>.rec;
#                                                             not ready: it stops what it started (the stop below) and exits 1
#   launcher_gc.sh info  <rain|sunny> <dir> <tag>             one line: pid= start= alive= ready= log_bytes= (read only)
#   launcher_gc.sh mark  <rain|sunny> <dir> <tag> <word ...>  append "<receipt time> GINLA mark <words>" to the launcher log
#                                                             (run_gc.sh's trial_start / trial_end markers; the log is O_APPEND)
#   launcher_gc.sh table <rain|sunny> <dir> <tag>             one line "table open=N [entries]": the registration table read from
#                                                             the launcher's own lines (read only; see TABLEPY)
#   launcher_gc.sh stop  <rain|sunny> <dir> <tag>             SIGTERM to the recorded PID (its own shutdown: unused spares
#                                                             SIGKILLed through their pidfds, the socket unlinked), SIGKILL to
#                                                             the same PID after 3 s if it is still there; with no launcher PID
#                                                             recorded, SIGTERM to the recorded timeout PID (it passes it on)
# The K=V arguments go into the launcher's environment (the test switch NCCL_GIN_CTRL_TEST_NO_EXIT_REPORT=1 of
# gc4_fdhold_sock_kill3_noreport, cells_gc.json launcher_env). Every NCCL_ and GIN_ variable of the caller is dropped first.
#
# What it does: the socket goes to a new directory of this uid with mode 0700 (/tmp/gc_la.XXXXXX/launcher.sock, made by
# mktemp -d; the launcher refuses any other directory); the launcher runs as
#   timeout -s KILL <LA_BOUND_S> gin_launcher --node <0 rain | 1 sunny> --dev <mlx5_1 | mlx5_0> --port 1 --gid-index <the
#   RoCE v2 GID of run_mi.sh's probe> --tc <LA_TC> --sock <path>
# and its stderr is stamped with rain's CLOCK_MONOTONIC at receipt (run_mi.sh's receipt clock) into <dir>/la_<tag>_<node>.log
# (opened O_APPEND, so the markers of `mark` land between whole lines). The launcher's own PID (the child of that timeout whose
# comm is gin_launcher) and its start time (/proc/<pid>/stat field 22), and the timeout's PID and start, are recorded; info and
# stop act only on a process whose comm and start time are the recorded ones. Nothing is killed by name. sunny's management
# address comes from SUNNY_SSH only and is never written to a file; the log is IPv4-masked after the stop.
# env: SUNNY_SSH (required), RS_SET (required), LA_BOUND_S (860: below hold_gc.sh's timeout -s KILL 880), LA_TC (the launcher's
#   --tc; default $NCCL_IB_TC of the ranks, which run_gc.sh does not set: 0), LA_READY_S (15), LA_BIN (relative to $HOME:
#   rs-bundle/<RS_SET>/gctest/gin_launcher)
set -u
OP=${1:?start|info|mark|table|stop}; NODE=${2:?rain|sunny}; DIR=${3:?dir}; TAG=${4:?tag}
shift 4
case "$NODE" in rain) NODEN=0; DEV=mlx5_1 ;; sunny) NODEN=1; DEV=mlx5_0 ;; *) echo "node is rain or sunny" >&2; exit 2 ;; esac
case "$TAG" in "" | *[!A-Za-z0-9_.-]*) echo "tag is one plain word" >&2; exit 2 ;; esac
D=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=remote_gc.sh
. "$D/remote_gc.sh"
RS_SET=${RS_SET:-}
# shellcheck source=../../../mirror/impl/test/rs_set_mi.sh
. "$D/../../../mirror/impl/test/rs_set_mi.sh"
rs_set_check || exit 2
SUNNY_SSH=${SUNNY_SSH:?set SUNNY_SSH}
LA_BIN=${LA_BIN:-rs-bundle/$RS_SET/gctest/gin_launcher}
LA_BOUND_S=${LA_BOUND_S:-860}; LA_TC=${LA_TC:-0}; LA_READY_S=${LA_READY_S:-15}
mkdir -p "$DIR"
REC=$DIR/la_${TAG}_$NODE.rec; LOG=$DIR/la_${TAG}_$NODE.log; CTL=$DIR/la_${TAG}_$NODE.ctl
STAMP='import sys,time
for l in sys.stdin.buffer:
    sys.stdout.write("%.6f %s\n" % (time.clock_gettime(time.CLOCK_MONOTONIC), l.decode("utf-8","replace").rstrip("\n")))
    sys.stdout.flush()'
# on the node: "<launcher pid> <its start ticks> <timeout pid> <its start ticks>" of the gin_launcher child of the recorded
# timeout pid ("- -" for the launcher when it is not found in 10 s; exit 1 then)
FINDPY='import os,sys,time
tp=int(open(sys.argv[1]).read().split()[0])
def st(p):
    s=open("/proc/%s/stat"%p).read(); return s[s.index("(")+1:s.rindex(")")], s.rsplit(")",1)[1].split()
try: ts=st(tp)[1][19]
except OSError: ts="-"
end=time.time()+10
while time.time()<end:
    for d in os.listdir("/proc"):
        if not d.isdigit(): continue
        try: name,f=st(d)
        except (OSError,ValueError): continue
        if name=="gin_launcher" and int(f[1])==tp: print(d, f[19], tp, ts); sys.exit(0)
    time.sleep(0.05)
print("-", "-", tp, ts); sys.exit(1)'
# on the node: alive check / signal of the recorded (pid, start, comm); prints alive=0|1 or the signal line
SIGPY='import os,sys,signal
pid,start,sig,comm=int(sys.argv[1]),sys.argv[2],sys.argv[3],sys.argv[4]
try:
    s=open("/proc/%d/stat"%pid).read()
except OSError:
    print("alive=0"); sys.exit(0)
name=s[s.index("(")+1:s.rindex(")")]; f=s.rsplit(")",1)[1].split()
ok=(name==comm and f[19]==start and f[0] not in ("Z","X"))
if sig=="none":
    print("alive=%d state=%s" % (int(ok), f[0] if ok else "-")); sys.exit(0)
if not ok:
    print("GINLA no_process pid=%d" % pid); sys.exit(0)
os.kill(pid, getattr(signal, sig)); print("GINLA signal %s pid=%d comm=%s" % (sig, pid, comm))'
# the registration table from the launcher's own lines (TODO(p3): a "table:" line of the launcher would replace this reading;
# notes_test.md, line formats). Open: a rank entry (registered / re-registered) without its end (EXITED, "exited; EXITED not
# sent", FENCED, left), a spare entry (said HELLO) without its end (ended, re-registered as the rank, shutdown SIGKILL).
TABLEPY='import re,sys
op={}
R=re.compile
pats=[(R(r"GIN/LA: node \d+: rank (\d+) incarnation (\d+) registered \(pid"),"rank","open"),
      (R(r"GIN/LA: node \d+: rank (\d+) incarnation (\d+) re-registered"),"spare","close"),
      (R(r"GIN/LA: node \d+: rank (\d+) incarnation (\d+) re-registered"),"rank","open"),
      (R(r"GIN/LA: node \d+: rank (\d+) incarnation (\d+) (?:EXITED\b|exited; EXITED not sent|FENCED:|left \(LEAVING)"),"rank","close"),
      (R(r"GIN/LA: node \d+: spare of rank (\d+) incarnation (\d+) said HELLO"),"spare","open"),
      (R(r"GIN/LA: node \d+: (?:spare of rank (\d+) incarnation (\d+) ended|shutdown: the unused spare of rank (\d+) incarnation (\d+))"),"spare","close")]
try: lines=open(sys.argv[1],errors="replace").read().splitlines()
except OSError: lines=[]
for l in lines:
    for rx,kind,act in pats:
        m=rx.search(l)
        if not m: continue
        g=[x for x in m.groups() if x is not None]
        k="%s%s.%s"%(kind,g[0],g[1])
        if act=="open": op[k]=1
        else: op.pop(k,None)
print("table open=%d%s" % (len(op), "".join(" "+k for k in sorted(op))))'
recval() { sed -n "s/.*\b$1=\([^ ]*\).*/\1/p" "$REC" 2>/dev/null | head -1; }
do_stop() {  # the recorded launcher (or, with none recorded, the recorded timeout), then the node-side directories
  local p s tp ts sd pd pipe gone
  p=$(recval pid); s=$(recval start); tp=$(recval tpid); ts=$(recval tstart); sd=$(recval sockdir); pd=$(recval piddir)
  pipe=$(recval pipe)
  if [ -n "$p" ] && [ "$p" != - ]; then
    node_py "$NODE" "$SIGPY" "$p" "$s" SIGTERM gin_launcher >> "$CTL" 2>&1
    gone=0
    for _ in $(seq 1 30); do
      node_py "$NODE" "$SIGPY" "$p" "$s" none gin_launcher | grep -q 'alive=0' && { gone=1; break; }
      sleep 0.1
    done
    if [ "$gone" = 0 ]; then
      node_py "$NODE" "$SIGPY" "$p" "$s" SIGKILL gin_launcher >> "$CTL" 2>&1
      echo "$(date '+%F %T') stop $NODE tag=$TAG pid=$p: still there 3 s after SIGTERM, SIGKILL sent" >> "$CTL"
    fi
  elif [ -n "$tp" ] && [ "$tp" != - ] && [ -n "$ts" ] && [ "$ts" != - ]; then
    node_py "$NODE" "$SIGPY" "$tp" "$ts" SIGTERM timeout >> "$CTL" 2>&1
    echo "$(date '+%F %T') stop $NODE tag=$TAG: no launcher pid recorded; SIGTERM to the recorded timeout $tp" >> "$CTL"
  fi
  # the node-side directories this script made (this uid's mktemp names only)
  case "$sd" in /tmp/gc_la.??????) node_sh "$NODE" 'rm -rf "$1"' "$sd" ;; esac
  case "$pd" in /tmp/gc_lp.??????) node_sh "$NODE" 'rm -rf "$1"' "$pd" ;; esac
  # the stamping pipe ends with the launcher; then the log is IPv4-masked in place (REVIEW_TEST nit 16)
  if [ -n "$pipe" ]; then for _ in $(seq 1 30); do kill -0 "$pipe" 2>/dev/null || break; sleep 0.1; done; fi
  [ -f "$LOG" ] && sed -i "$MASK" "$LOG"
  echo "$(date '+%F %T') stop $NODE tag=$TAG pid=$p done" >> "$CTL"
}
case "$OP" in
  start)
    [ -e "$REC" ] && { echo "$REC exists: one launcher per tag and node" >&2; exit 2; }
    envs=()
    for kv in "$@"; do
      case "$kv" in NCCL_GIN_CTRL_TEST_NO_EXIT_REPORT=[01]) envs+=("$kv") ;; *) echo "launcher env $kv is not one this runner passes" >&2; exit 2 ;; esac
    done
    GID=$(node_sh "$NODE" "$GID_PROBE" "$DEV")
    [ -n "$GID" ] || { echo "no RoCE v2 GID on $NODE" >&2; exit 1; }
    # the node-side files: a 0700 directory for the socket and one for the pid files (both this uid's, removed at stop)
    PRE=$(node_sh "$NODE" 'umask 077; a=$(mktemp -d /tmp/gc_la.XXXXXX) && b=$(mktemp -d /tmp/gc_lp.XXXXXX) && echo "$a $b"')
    read -r SDIR PDIR <<< "$PRE"
    [ -n "${SDIR:-}" ] && [ -n "${PDIR:-}" ] || { echo "could not make the launcher's directories on $NODE" >&2; exit 1; }
    SOCK=$SDIR/launcher.sock
    # shellcheck disable=SC2016
    RUN='cd "$HOME" || exit 1; umask 077
for v in $(env | sed -n "s/^\(\(NCCL\|GIN\)_[A-Za-z0-9_]*\)=.*/\1/p"); do unset "$v"; done
pd=$1; bin=$HOME/$2; bound=$3; node=$4; dev=$5; gid=$6; tc=$7; sock=$8; shift 8
echo $$ > "$pd/timeout.pid"
exec env "$@" timeout -s KILL "$bound" "$bin" --node "$node" --dev "$dev" --port 1 --gid-index "$gid" --tc "$tc" --sock "$sock" 2>&1'
    : > "$LOG"
    if [ "$NODE" = sunny ]; then
      ssh -n -o LogLevel=ERROR "$SUNNY_SSH" "$(rcmd "$RUN" "$PDIR" "$LA_BIN" "$LA_BOUND_S" "$NODEN" "$DEV" "$GID" "$LA_TC" "$SOCK" "${envs[@]}")" \
        2>&1 | python3 -u -c "$STAMP" >> "$LOG" 2>&1 &
    else
      bash -c "$RUN" _ "$PDIR" "$LA_BIN" "$LA_BOUND_S" "$NODEN" "$DEV" "$GID" "$LA_TC" "$SOCK" "${envs[@]}" \
        2>&1 | python3 -u -c "$STAMP" >> "$LOG" 2>&1 &
    fi
    PIPE=$!
    # shellcheck disable=SC2016
    read -r LPID LSTART TPID TSTART <<< "$(node_sh "$NODE" 'for i in $(seq 1 50); do [ -s "$1" ] && break; sleep 0.1; done; python3 -c "$2" "$1"' "$PDIR/timeout.pid" "$FINDPY")"
    # shellcheck disable=SC2016
    BINMD5=$(node_sh "$NODE" 'md5sum < "$HOME/$1" | cut -c1-32' "$LA_BIN")
    ready=0
    end=$(( $(date +%s) + LA_READY_S ))
    while [ "$(date +%s)" -le "$end" ]; do
      grep -q "GIN/LA: node $NODEN: listening on its Unix socket" "$LOG" 2>/dev/null && { ready=1; break; }
      kill -0 "$PIPE" 2>/dev/null || break
      sleep 0.1
    done
    [ -n "${LPID:-}" ] && [ "$LPID" != - ] || ready=0
    echo "node=$NODE noden=$NODEN dev=$DEV gid=$GID tc=$LA_TC pid=${LPID:--} start=${LSTART:--} tpid=${TPID:--} tstart=${TSTART:--} sock=$SOCK sockdir=$SDIR piddir=$PDIR ready=$ready bound_s=$LA_BOUND_S bin_md5=${BINMD5:-none} env=$(IFS=+; echo "${envs[*]:-}") pipe=$PIPE" > "$REC"
    echo "$(date '+%F %T') start $NODE tag=$TAG pid=${LPID:--} ready=$ready" >> "$CTL"
    if [ "$ready" != 1 ]; then
      echo "launcher on $NODE not ready (see $(basename "$LOG")); stopping what was started" >&2
      do_stop
      exit 1
    fi ;;
  info)
    [ -f "$REC" ] || { echo "pid= start= alive=0 ready=0 log_bytes=0"; exit 0; }
    p=$(recval pid); s=$(recval start)
    a=$( [ -n "$p" ] && [ "$p" != - ] && node_py "$NODE" "$SIGPY" "$p" "$s" none gin_launcher | sed -n 's/.*alive=\([01]\).*/\1/p' )
    echo "pid=$p start=$s alive=${a:-0} ready=$(recval ready) log_bytes=$(stat -c %s "$LOG" 2>/dev/null || echo 0)" ;;
  mark)
    [ "$#" -ge 1 ] || { echo "mark needs a word" >&2; exit 2; }
    python3 -c 'import sys,time
open(sys.argv[1],"a").write("%.6f GINLA mark %s\n" % (time.clock_gettime(time.CLOCK_MONOTONIC), " ".join(sys.argv[2:])))' "$LOG" "$@" ;;
  table)
    python3 -c "$TABLEPY" "$LOG" ;;
  stop)
    [ -f "$REC" ] || { echo "no launcher record for $NODE tag $TAG" >&2; exit 0; }
    do_stop ;;
  *) echo "start|info|mark|table|stop" >&2; exit 2 ;;
esac
exit 0
