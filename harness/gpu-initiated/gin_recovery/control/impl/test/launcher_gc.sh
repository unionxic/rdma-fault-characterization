#!/usr/bin/env bash
# launcher_gc.sh - gin-control, test side: one node's launcher (../launcher/gin_launcher, ../../EXPERIMENT.md 5 and 9.5) for
# hold_gc.sh (one launcher per node per hold, EXPERIMENT 5) and run_gc.sh (LAUNCHER_SCOPE=trial: one per node per trial).
# Run only by the main session, inside ../../../../common/cluster_run.sh through chain_gc.sh / hold_gc.sh.
#
#   launcher_gc.sh start <rain|sunny> <dir> <tag> [K=V ...]   start it, wait for its "listening" line, write <dir>/la_<tag>_<node>.rec
#   launcher_gc.sh info  <rain|sunny> <dir> <tag>             one line: pid= start= alive= ready= log_bytes= (read only)
#   launcher_gc.sh stop  <rain|sunny> <dir> <tag>             SIGTERM to the recorded PID (its own shutdown: unused spares
#                                                             SIGKILLed through their pidfds, the socket unlinked), SIGKILL to
#                                                             the same PID after 3 s if it is still there
# The K=V arguments go into the launcher's environment (the test switch NCCL_GIN_CTRL_TEST_NO_EXIT_REPORT=1 of
# gc4_fdhold_sock_kill3_noreport, cells_gc.json launcher_env). Every NCCL_ and GIN_ variable of the caller is dropped first.
#
# What it does: the socket goes to a new directory of this uid with mode 0700 (/tmp/gc_la.XXXXXX/launcher.sock, made by
# mktemp -d; the launcher refuses any other directory); the launcher runs as
#   timeout -s KILL <LA_BOUND_S> gin_launcher --node <0 rain | 1 sunny> --dev <mlx5_1 | mlx5_0> --port 1 --gid-index <the
#   RoCE v2 GID of run_mi.sh's probe> --tc <LA_TC> --sock <path>
# and its stderr is stamped with rain's CLOCK_MONOTONIC at receipt (run_mi.sh's receipt clock) into <dir>/la_<tag>_<node>.log.
# The launcher's own PID (the child of that timeout whose comm is gin_launcher) and its start time (/proc/<pid>/stat field
# 22) are recorded; info and stop act only on a process whose comm and start time are the recorded ones. Nothing is killed
# by name. sunny's management address comes from SUNNY_SSH only and is never written to a file.
# env: SUNNY_SSH (required), RS_SET (required), LA_BOUND_S (900), LA_TC (the launcher's --tc; default $NCCL_IB_TC of the
#   ranks, which run_gc.sh does not set: 0), LA_READY_S (15), LA_BIN (~/rs-bundle/<RS_SET>/gctest/gin_launcher)
set -u
OP=${1:?start|info|stop}; NODE=${2:?rain|sunny}; DIR=${3:?dir}; TAG=${4:?tag}
shift 4
case "$NODE" in rain) NODEN=0; DEV=mlx5_1 ;; sunny) NODEN=1; DEV=mlx5_0 ;; *) echo "node is rain or sunny" >&2; exit 2 ;; esac
case "$TAG" in "" | *[!A-Za-z0-9_.-]*) echo "tag is one plain word" >&2; exit 2 ;; esac
D=$(cd "$(dirname "$0")" && pwd)
RS_SET=${RS_SET:-}
# shellcheck source=../../../mirror/impl/test/rs_set_mi.sh
. "$D/../../../mirror/impl/test/rs_set_mi.sh"
rs_set_check || exit 2
SUNNY_SSH=${SUNNY_SSH:?set SUNNY_SSH}
LA_BIN=${LA_BIN:-\$HOME/rs-bundle/$RS_SET/gctest/gin_launcher}
LA_BOUND_S=${LA_BOUND_S:-900}; LA_TC=${LA_TC:-0}; LA_READY_S=${LA_READY_S:-15}
mkdir -p "$DIR"
REC=$DIR/la_${TAG}_$NODE.rec; LOG=$DIR/la_${TAG}_$NODE.log; CTL=$DIR/la_${TAG}_$NODE.ctl
STAMP='import sys,time
for l in sys.stdin.buffer:
    sys.stdout.write("%.6f %s\n" % (time.clock_gettime(time.CLOCK_MONOTONIC), l.decode("utf-8","replace").rstrip("\n")))
    sys.stdout.flush()'
# on the node: <pid> <start ticks> of the gin_launcher child of the recorded timeout pid
FINDPY='import os,sys,time
tp=int(open(sys.argv[1]).read().split()[0]); end=time.time()+10
while time.time()<end:
    for d in os.listdir("/proc"):
        if not d.isdigit(): continue
        try: s=open("/proc/%s/stat"%d).read()
        except OSError: continue
        name=s[s.index("(")+1:s.rindex(")")]; f=s.rsplit(")",1)[1].split()
        if name=="gin_launcher" and int(f[1])==tp: print(d, f[19]); sys.exit(0)
    time.sleep(0.05)
sys.exit(1)'
# on the node: alive check / signal of the recorded (pid, start); prints alive=0|1 or the signal line
SIGPY='import os,sys,signal
pid,start,sig=int(sys.argv[1]),sys.argv[2],sys.argv[3]
try:
    s=open("/proc/%d/stat"%pid).read()
except OSError:
    print("alive=0"); sys.exit(0)
name=s[s.index("(")+1:s.rindex(")")]; f=s.rsplit(")",1)[1].split()
ok=(name=="gin_launcher" and f[19]==start)
if sig=="none":
    print("alive=%d state=%s" % (int(ok), f[0] if ok else "-")); sys.exit(0)
if not ok:
    print("GINLA no_process pid=%d" % pid); sys.exit(0)
os.kill(pid, getattr(signal, sig)); print("GINLA signal %s pid=%d" % (sig, pid))'
GID_PROBE='d=/sys/class/infiniband/$1/ports/1
for g in $(ls "$d/gids" | sort -n); do
  [ "$(cat "$d/gid_attrs/types/$g" 2>/dev/null)" = "RoCE v2" ] || continue
  case "$(cat "$d/gids/$g")" in 0000:0000:0000:0000:0000:ffff:1e00:00*) echo "$g"; exit 0;; esac
done; exit 1'
on_node() { if [ "$NODE" = sunny ]; then ssh -n "$SUNNY_SSH" "$1"; else bash -c "$1"; fi; }
recval() { sed -n "s/.*\b$1=\([^ ]*\).*/\1/p" "$REC" 2>/dev/null | head -1; }
case "$OP" in
  start)
    [ -e "$REC" ] && { echo "$REC exists: one launcher per tag and node" >&2; exit 2; }
    envs=""
    for kv in "$@"; do
      case "$kv" in NCCL_GIN_CTRL_TEST_NO_EXIT_REPORT=[01]) envs="$envs $kv" ;; *) echo "launcher env $kv is not one this runner passes" >&2; exit 2 ;; esac
    done
    if [ "$NODE" = sunny ]; then GID=$(ssh -n "$SUNNY_SSH" bash -c "'$GID_PROBE'" _ "$DEV"); else GID=$(bash -c "$GID_PROBE" _ "$DEV"); fi
    [ -n "$GID" ] || { echo "no RoCE v2 GID on $NODE" >&2; exit 1; }
    # the node-side files: a 0700 directory for the socket and one for the pid files (both this uid's, removed at stop)
    PRE=$(on_node 'umask 077; a=$(mktemp -d /tmp/gc_la.XXXXXX) && b=$(mktemp -d /tmp/gc_lp.XXXXXX) && echo "$a $b"')
    read -r SDIR PDIR <<< "$PRE"
    [ -n "${SDIR:-}" ] && [ -n "${PDIR:-}" ] || { echo "could not make the launcher's directories on $NODE" >&2; exit 1; }
    SOCK=$SDIR/launcher.sock
    CMD="cd \$HOME && umask 077 && for v in \$(env | sed -n 's/^\\(\\(NCCL\\|GIN\\)_[A-Za-z0-9_]*\\)=.*/\\1/p'); do unset \$v; done; \
echo \$\$ > $PDIR/timeout.pid && exec env $envs timeout -s KILL $LA_BOUND_S $LA_BIN --node $NODEN --dev $DEV --port 1 \
--gid-index $GID --tc $LA_TC --sock $SOCK 2>&1"
    if [ "$NODE" = sunny ]; then
      ssh -n "$SUNNY_SSH" "$CMD" | python3 -u -c "$STAMP" > "$LOG" 2>&1 &
    else
      bash -c "$CMD" | python3 -u -c "$STAMP" > "$LOG" 2>&1 &
    fi
    PIPE=$!
    read -r LPID LSTART <<< "$(on_node "for i in \$(seq 1 50); do [ -s $PDIR/timeout.pid ] && break; sleep 0.1; done; python3 -c '$FINDPY' $PDIR/timeout.pid")"
    BINMD5=$(on_node "md5sum < $LA_BIN | cut -c1-32")
    ready=0
    end=$(( $(date +%s) + LA_READY_S ))
    while [ "$(date +%s)" -le "$end" ]; do
      grep -q "GIN/LA: node $NODEN: listening on its Unix socket" "$LOG" 2>/dev/null && { ready=1; break; }
      kill -0 "$PIPE" 2>/dev/null || break
      sleep 0.1
    done
    echo "node=$NODE noden=$NODEN dev=$DEV gid=$GID tc=$LA_TC pid=${LPID:-} start=${LSTART:-} sock=$SOCK sockdir=$SDIR piddir=$PDIR ready=$ready bound_s=$LA_BOUND_S bin_md5=${BINMD5:-none} env=$(echo $envs | tr ' ' '+') pipe=$PIPE" > "$REC"
    echo "$(date '+%F %T') start $NODE tag=$TAG pid=${LPID:-} ready=$ready" >> "$CTL"
    [ "$ready" = 1 ] && [ -n "${LPID:-}" ] || { echo "launcher on $NODE not ready (see $(basename "$LOG"))" >&2; exit 1; } ;;
  info)
    [ -f "$REC" ] || { echo "pid= start= alive=0 ready=0 log_bytes=0"; exit 0; }
    p=$(recval pid); s=$(recval start)
    a=$( [ -n "$p" ] && on_node "python3 -c '$SIGPY' $p $s none" | sed -n 's/.*alive=\([01]\).*/\1/p' )
    echo "pid=$p start=$s alive=${a:-0} ready=$(recval ready) log_bytes=$(stat -c %s "$LOG" 2>/dev/null || echo 0)" ;;
  stop)
    [ -f "$REC" ] || { echo "no launcher record for $NODE tag $TAG" >&2; exit 0; }
    p=$(recval pid); s=$(recval start); sd=$(recval sockdir); pd=$(recval piddir)
    if [ -n "$p" ]; then
      on_node "python3 -c '$SIGPY' $p $s SIGTERM" >> "$CTL" 2>&1
      gone=0
      for _ in $(seq 1 30); do
        on_node "python3 -c '$SIGPY' $p $s none" | grep -q 'alive=0' && { gone=1; break; }
        sleep 0.1
      done
      if [ "$gone" = 0 ]; then
        on_node "python3 -c '$SIGPY' $p $s SIGKILL" >> "$CTL" 2>&1
        echo "$(date '+%F %T') stop $NODE tag=$TAG pid=$p: still there 3 s after SIGTERM, SIGKILL sent" >> "$CTL"
      fi
    fi
    # the node-side directories this script made (this uid's mktemp names only)
    case "$sd" in /tmp/gc_la.??????) on_node "rm -rf $sd" ;; esac
    case "$pd" in /tmp/gc_lp.??????) on_node "rm -rf $pd" ;; esac
    echo "$(date '+%F %T') stop $NODE tag=$TAG pid=$p done" >> "$CTL" ;;
  *) echo "start|info|stop" >&2; exit 2 ;;
esac
exit 0
