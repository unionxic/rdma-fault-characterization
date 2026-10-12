#!/usr/bin/env bash
# run_rs.sh - gin-restore work package 10: one restore trial of EXPERIMENT.md 7 / 9.8. Four live ranks of gin_rs (rank r on
# rain when r is even, on sunny when r is odd: the interleaved placement, NCCL_MULTI_RANK_GPU_ENABLE=1, two ranks per GPU)
# and, in a kill cell with a spare, one spare process on the SAME node and GPU as the rank to be killed
# (NCCL_GIN_RESTORE_SPARE=<rank>). The spare does not join the rendezvous; it waits inside ncclCommInitRank for the library.
#
# Receipt clock (the house style of gpu-detect's apprun.py): every line a process prints (gin_rs's GINRS lines and NCCL's
# WARN lines) is streamed to rain and written as "<rain CLOCK_MONOTONIC at receipt, s> <line>", for rain's ranks through a
# local pipe and for sunny's through the ssh stdout. One clock for both nodes; rows_rs.py reads the death, release, restore
# and fallback times from it. The recorded-PID kill writes its own stamped line too.
#
# Safety (EXPERIMENT.md 8, 9.15; the patterns of ../../feas/run_spike.sh and ../../../remaining/run_mr_hr.sh): every process
# is bounded by `timeout -s KILL`; NOTHING is killed by name; the only kill is of KILL_RANK, by the PID recorded right after
# it started (its `timeout`'s child named gin_rs, found by parent links and /proc/<pid>/comm), and only while that PID is
# still the child of the recorded timeout (no PID reuse). The rendezvous port is drawn 29000-30999 and checked unused on
# both nodes (portpick.sh), with a per-trial nonce. rain's management address is looked up at run time and sunny's comes
# from SUNNY_SSH: neither is written to any file here (the copied logs are IPv4-masked too). Every NCCL_ and GIN_ variable of
# the caller is dropped first. No link, address, driver or firewall is touched.
#
# Run only by the main session, inside ../../../../common/cluster_run.sh through hold_rs.sh. The restore library layer may
# not be integrated yet: then every cell runs as a clean exchange (a kill falls back, no revival) and score.py reads
# "자료 부족" where the restore reaction is needed. Until work package 8 the spare starts with a zero unique id and ends at
# its own watchdog (or an init error): bounded, harmless.
#
# usage: run_rs.sh <trial-tag> <logdir>
# env: SUNNY_SSH (required), N (4), CELL, RS_SET (empty: today's deployment, $HOME/rs-bundle/{lib/rs,lib/rsp,rstest};
#   a name: the deployment set $HOME/rs-bundle/<RS_SET>/{lib/rs,lib/rsp,rstest}, deploy_rs.sh with the same RS_SET),
#   LIB (rs: <set>/lib/rs and <set>/rstest/gin_rs; hk: gpu-detect's deployed $HOME/gi-bundle/gin_ts2/hk, read only, and
#   <set>/rstest/gin_rs_hk), STEPS (600), BYTES (4096),
#   STEP_GAP_US (5000: pacing between steps, so a kill lands inside the traffic), WATCHDOG_S (90; 200 in kill cells with
#   a spare),
#   KILL_RANK (the rank to kill; empty = none). The traffic kill: by its recorded PID, KILL_DELAY_US (500) after KR's first
#   stamped line of a step >= KILL_AT_STEP (100) that arrived after the spare was ready (fallback: KILL_DELAY_MS 30000).
#   KILL_IN_HOOK=1 instead: the checkpoint-pause kill (2026-10-13, after the pilot P1): the library's research-build test
#   switch NCCL_GIN_RESTORE_TEST_DIE_IN_CKPT=<node-local arm file>:<KILL_HOOK_US (300)>, given to KR only: once the arm file
#   exists and KR has a checkpoint it sent as armable and stable, KR SIGKILLs itself KILL_HOOK_US after the pause request
#   (CKPT_PAUSE to every peer) of its next checkpoint, with one WARN line ("test switch NCCL_GIN_RESTORE_TEST_DIE_IN_CKPT:
#   dying ..."), whose receipt time is the kill time (no _kill.out). The arm file is created once the spare is ready (or
#   its wait ran out) AND every survivor printed "GIN/RS: rank <s>: rank <KR> armed at its stable checkpoint <k>" (the
#   library's line when KR's CKPT_STABLE marked KR armed there; bounded by ARM_WAIT_S, 60; none: no arm file, no kill,
#   meta arm_wait=timeout). The driver's own GIN_RS_DIE_IN_STEP (still in gin_rs.cu) is not used any more: it assumed a
#   checkpoint at every step divisible by CKPT_STEPS, while the library takes checkpoint 0 at step 0 and the next ones
#   CKPT_STEPS steps after the previous one became stable (the pilot P1, EXPERIMENT.md 12).
#   SPARE_WAIT_MS (60000): the spare's NCCL_GIN_RESTORE_SPARE_WAIT_MS (the library's default is one hour). A spare never
#   activated ends on its own that long after its ready line (its Resume returns an error; the driver aborts and exits)
#   instead of at its 200 s watchdog. Safe: the start gate holds the live ranks until the spare is ready, so the kill
#   comes about 1-3 s after the ready line (the traffic kill at step >= 100 of 5 ms steps; the checkpoint kill after the
#   first stable checkpoint, about 1 s after the steps begin, and 20 steps more), and a held rank falls back at its hold
#   deadline (NCCL_GIN_RESTORE_MS 20 000 ms; LATER answers are retried until then): an activation comes at most about
#   23 s after the ready line, well inside 60 s.
#   SPARE (1 = a spare for KILL_RANK, started after KR's Resume line, replaying KR's init transcript; its address is
#   registered with KR: NCCL_GIN_RESTORE_SPARE_ADDR), SPARE_KILL_FIRST (1 with SPARE=1: the spare-absent cell, the spare is
#   SIGKILLed by its recorded PID once ready, before KR dies), SPARE_ADDR (1 with SPARE=0: an address registered with no
#   process ever started; unused by the cells), FAULT_POLICY (hold|failfast; hold ranks record their init transcript),
#   RESTORE (1|0), SYM_GIN (0), GIN_TYPE (3), RMA_DISABLE (1), NUM_RMA_CTX (0), NCONN (1), RESTORE_MS (20000),
#   RESUME_MS (30000), CKPT_STEPS (empty = library default), LOG_MEASURE (0), CHECKSUM (off), QPWATCH (10, EXPERIMENT.md 6),
#   DRIVER (gin_rs | gin_rs_nomacro | gin_rs_hk: the build the cell names; default gin_rs for rs, gin_rs_hk for hk),
#   CONTINUE_AFTER_REFUSAL (1: after a refused Resume the ranks run the workload fail-fast: the no-macro refusal cell),
#   R<r>_ENV, EXTRA_ENV, PORT_LO, PORT_HI, END_GRACE_MS (kill cells with a spare: 3000; the live ranks' pause before their
#   final abort). Kill cells with a spare also hold the live ranks before step 0 (rank 0's start gate, RS_START_GATE) until
#   the spare is ready, so a slow init replay cannot let the run end before the kill. Pilot only: SPARE_STRACE=1 (strace the spare: peer connects before/after its ready point, own and other
#   ranks' proxy UDS apart; counts only leave the node), NEG_REPLAY=1 with NEG_RANK (3) and NEG_FIELD_OFF (184): after the
#   trial, two spares replay a cut and a field-changed copy of NEG_RANK's transcript (both must fail). NCCL_GIN_Q4_QPWATCH_MS
#   is 0 for every process (the spare branch's requirement).
# Restore variable names (fixed by the dev, host and spare branches: impl/rs_spare_api.h, rs_hold_api.h, rs_ckpt_api.h;
#   the spare branch's rs_layer_spare.diff): NCCL_GIN_RESTORE_RECORD (each hold rank's init transcript, node-local),
#   NCCL_GIN_RESTORE_REPLAY (the spare replays its rank's transcript), NCCL_GIN_RESTORE_SPARE, NCCL_GIN_RESTORE_SPARE_PORT
#   (the spare's activation port), NCCL_GIN_RESTORE_SPARE_ADDR (given to the original rank only), NCCL_GIN_RESTORE_CKPT_STEPS,
#   NCCL_GIN_RESTORE_SPARE_WAIT_MS (the spare's activation wait), NCCL_GIN_RESTORE_TEST_DIE_IN_CKPT (the test switch above).
# files in <logdir>: <stem>_r<r>.kv/.log, <stem>_spare.kv/.log, <stem>_kill.out, <stem>_meta.txt (stem = <cell>_<lib>_<tag>);
# the meta line also names the deployment (rs_set, or -) and the md5 of the library and the driver this trial used on rain
# (lib_md5, driver_md5; read after the trial).
set -u
TRIAL=${1:?trial tag}; LOGDIR=${2:?logdir}
# the caller's NCCL_ and GIN_ variables are dropped: the processes get exactly NENV below (R<r>_ENV/EXTRA_ENV are kept)
for v in $(env | sed -n 's/^\(\(NCCL\|GIN\)_[A-Za-z0-9_]*\)=.*/\1/p'); do unset "$v"; done
SUNNY_SSH=${SUNNY_SSH:?set SUNNY_SSH}
SUNNY_HOST=${SUNNY_SSH#*@}
N=${N:-4}
[ "$N" = 4 ] || { echo "run_rs.sh is the 4-rank workload (N=4)" >&2; exit 1; }
LIB=${LIB:-rs}
RS_SET=${RS_SET:-}
case "$RS_SET" in ""|[A-Za-z0-9]*) ;; *) echo "RS_SET must be a plain name" >&2; exit 1 ;; esac
case "$RS_SET" in */*|*..*) echo "RS_SET must be a plain name" >&2; exit 1 ;; esac
RSB=$HOME/rs-bundle${RS_SET:+/$RS_SET}   # the deployment set (deploy_rs.sh with the same RS_SET)
# the driver build each cell names (cells_rs.json "driver"): gin_rs (macro), gin_rs_nomacro (this layer's headers, no
# macro), gin_rs_hk (hk headers); the default follows the library
case "$LIB" in
  rs|rsp) LIBDIR=$RSB/lib/$LIB; DRIVER=${DRIVER:-gin_rs} ;;
  hk) LIBDIR=$HOME/gi-bundle/gin_ts2/hk; DRIVER=${DRIVER:-gin_rs_hk} ;;   # read only
  *) echo "unknown LIB $LIB" >&2; exit 1 ;;
esac
case "$LIB:$DRIVER" in rs:gin_rs|rs:gin_rs_nomacro|rsp:gin_rs|rsp:gin_rs_nomacro|hk:gin_rs_hk) ;;
  *) echo "driver $DRIVER does not belong with library $LIB" >&2; exit 1 ;; esac
RSBIN=$RSB/rstest/$DRIVER
BINNAME=$(basename "$RSBIN")
STEPS=${STEPS:-600}; BYTES=${BYTES:-4096}; STEP_GAP_US=${STEP_GAP_US:-5000}
KILL_AT_STEP=${KILL_AT_STEP:-100}; KILL_DELAY_US=${KILL_DELAY_US:-500}
FAULT_POLICY=${FAULT_POLICY:-hold}; RESTORE=${RESTORE:-1}; SYM_GIN=${SYM_GIN:-0}; GIN_TYPE=${GIN_TYPE:-3}
RMA_DISABLE=${RMA_DISABLE:-1}; NUM_RMA_CTX=${NUM_RMA_CTX:-0}; NCONN=${NCONN:-1}; QPWATCH=${QPWATCH:-10}
RESTORE_MS=${RESTORE_MS:-20000}; RESUME_MS=${RESUME_MS:-30000}; LOG_MEASURE=${LOG_MEASURE:-0}; CHECKSUM=${CHECKSUM:-off}
KILL_RANK=${KILL_RANK:-}; KILL_DELAY_MS=${KILL_DELAY_MS:-30000}; KILL_IN_HOOK=${KILL_IN_HOOK:-0}; KILL_HOOK_US=${KILL_HOOK_US:-300}
ARM_WAIT_S=${ARM_WAIT_S:-60}
SPARE=${SPARE:-0}; SPARE_WAIT_MS=${SPARE_WAIT_MS:-60000}
# the processes' own bound: kill cells with a spare also wait at the start gate (up to 2 x 60 s for the spare)
WATCHDOG_S=${WATCHDOG_S:-$( [ -n "$KILL_RANK" ] && [ "$SPARE" = 1 ] && echo 200 || echo 90 )}
[ -x "$RSBIN" ] && [ -f "$LIBDIR/libnccl.so.2" ] || { echo "missing $RSBIN or $LIBDIR/libnccl.so.2 on rain" >&2; exit 1; }
RAIN_MGMT=$(ip -4 route get "$SUNNY_HOST" 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p' | head -1)
[ -n "$RAIN_MGMT" ] || { echo "cannot find rain's management address" >&2; exit 1; }
umask 077
WORK=$(mktemp -d /tmp/rs_rt.XXXXXX)
RT=/tmp/rs_rt_$$_$RANDOM      # sunny-side file prefix of this trial
D=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=../../../remaining/portpick.sh
. "$D/../../../remaining/portpick.sh"
cleanup() { ssh -n "$SUNNY_SSH" "rm -f $RT.*" 2>/dev/null || true; rm -rf "$WORK"; }
trap cleanup EXIT
GID_PROBE='d=/sys/class/infiniband/$1/ports/1
for g in $(ls "$d/gids" | sort -n); do
  [ "$(cat "$d/gid_attrs/types/$g" 2>/dev/null)" = "RoCE v2" ] || continue
  case "$(cat "$d/gids/$g")" in 0000:0000:0000:0000:0000:ffff:1e00:00*) echo "$g"; exit 0;; esac
done; exit 1'
GID0=$(bash -c "$GID_PROBE" _ mlx5_1) || { echo "no GID on rain" >&2; exit 1; }
GID1=$(ssh -n "$SUNNY_SSH" bash -c "'$GID_PROBE'" _ mlx5_0) || { echo "no GID on sunny" >&2; exit 1; }
# the receipt-clock stamper: every input line prefixed with rain's CLOCK_MONOTONIC (s) at receipt
STAMP='import sys,time
for l in sys.stdin.buffer:
    sys.stdout.write("%.6f %s\n" % (time.clock_gettime(time.CLOCK_MONOTONIC), l.decode("utf-8","replace").rstrip("\n")))
    sys.stdout.flush()'
node_of() { [ $(( $1 % 2 )) -eq 0 ] && echo rain || echo sunny; }
# the hold-process configuration of 9.10.8 plus the restore variables (QP watch: EXPERIMENT.md 6)
NENV="NCCL_DEBUG=WARN NCCL_DEBUG_SUBSYS=INIT,NET NCCL_SOCKET_IFNAME=eno1 NCCL_GIN_TYPE=$GIN_TYPE NCCL_GIN_ENABLE=1 \
NCCL_IB_TIMEOUT=14 NCCL_GIN_FAULT_CLASSIFY=1 NCCL_GIN_FAULT_RECOVERY=1 NCCL_GIN_FAULT_TRANSPARENT=1 \
NCCL_MULTI_RANK_GPU_ENABLE=1 NCCL_GIN_TS_QPWATCH_MS=$QPWATCH NCCL_GIN_FAULT_POLICY=$FAULT_POLICY NCCL_GIN_RESTORE=$RESTORE \
NCCL_SYM_GIN_KERNELS_ENABLE=$SYM_GIN NCCL_RMA_DISABLE=$RMA_DISABLE NCCL_NUM_RMA_CTX=$NUM_RMA_CTX NCCL_GIN_NCONNECTIONS=$NCONN \
NCCL_GIN_RESTORE_MS=$RESTORE_MS NCCL_GIN_RESTORE_RESUME_MS=$RESUME_MS NCCL_GIN_RESTORE_CHECKSUM=$CHECKSUM \
NCCL_GIN_RESTORE_LOG_MEASURE=$LOG_MEASURE ${CKPT_STEPS:+NCCL_GIN_RESTORE_CKPT_STEPS=$CKPT_STEPS} \
NCCL_GIN_Q4_QPWATCH_MS=0 NCCL_RAS_ENABLE=0 LD_LIBRARY_PATH=$LIBDIR ${EXTRA_ENV:-}"
END_GRACE_MS=${END_GRACE_MS:-$( [ -n "$KILL_RANK" ] && [ "$SPARE" = 1 ] && echo 3000 || echo 0 )}
RS_ENV="RS_STEPS=$STEPS RS_BYTES=$BYTES RS_WATCHDOG_S=$WATCHDOG_S RS_STEP_GAP_US=$STEP_GAP_US RS_END_GRACE_MS=$END_GRACE_MS \
RS_CONTINUE_AFTER_REFUSAL=${CONTINUE_AFTER_REFUSAL:-0}"
NONCE=$(new_nonce)
pick_port
# the spare's address (9.3): a port on the spare's node, picked before any launch so the original rank gets it at its start.
# SPARE=1: a spare listens there. SPARE_ADDR=1 with SPARE=0 (the no-spare cell): the address is registered but no process
# listens, so the rank is armed and the activation must fail (the fallback of 9.2). Neither address is written to a file.
SPORT=""; SADDR_ENV=""
if [ -n "$KILL_RANK" ] && { [ "$SPARE" = 1 ] || [ "${SPARE_ADDR:-0}" = 1 ]; }; then
  save=$PORT; savet=$PORT_TRIES; pick_port $(( PORT + 1 > PORT_HI ? PORT_LO : PORT + 1 )); SPORT=$PORT
  PORT=$save; PORT_TRIES=$savet
  if [ "$(node_of "$KILL_RANK")" = sunny ]; then sa=$SUNNY_HOST; else sa=$RAIN_MGMT; fi
  SADDR_ENV="NCCL_GIN_RESTORE_SPARE_ADDR=$sa:$SPORT"
fi
ARGS="$N $RAIN_MGMT $PORT"
tag="$LIB/${CELL:-rs}#$TRIAL"
echo "[$tag] gid rain=$GID0 sunny=$GID1 port=$PORT kill=${KILL_RANK:--} spare=$SPARE policy=$FAULT_POLICY restore=$RESTORE" >&2
hca() { [ "$1" = rain ] && echo "NCCL_IB_HCA=mlx5_1 NCCL_IB_GID_INDEX=$GID0" || echo "NCCL_IB_HCA=mlx5_0 NCCL_IB_GID_INDEX=$GID1"; }
renv() { local v="R${1}_ENV"; echo "${!v:-}"; }
# per-node, per-trial private paths (the init transcript holds management addresses: it stays on its node, mode 0600 by
# the library's O_EXCL create, inside this trial's private prefix, and is deleted with the trial)
npath() { [ "$1" = sunny ] && echo "$RT.$2" || echo "$WORK/$2"; }
rec_env() { [ "$FAULT_POLICY" = hold ] && echo "NCCL_GIN_RESTORE_RECORD=$(npath "$(node_of "$1")" "r$1.rec")"; }
sa_env() { [ -n "$SADDR_ENV" ] && [ "$1" = "$KILL_RANK" ] && echo "$SADDR_ENV"; }  # only the rank that may be revived
die_env() {  # the checkpoint-pause kill: the library's test switch, armed by a node-local file (see the header)
  [ -n "$KILL_RANK" ] && [ "$1" = "$KILL_RANK" ] && [ "$KILL_IN_HOOK" = 1 ] &&
    echo "NCCL_GIN_RESTORE_TEST_DIE_IN_CKPT=$(npath "$(node_of "$1")" arm):$KILL_HOOK_US"
}
# wait_line <file> <regex with one group or none> <min receipt time> <min group value> <timeout s>: prints the receipt time
# of the first stamped line that matches with time >= min and group >= min value; nothing on timeout
WAITPY='import re,sys,time
f,rx,tmin,gmin,tmo=sys.argv[1],re.compile(sys.argv[2]),float(sys.argv[3]),int(sys.argv[4]),float(sys.argv[5])
end=time.time()+tmo
while time.time()<end:
    try:
        for l in open(f,errors="replace"):
            t,_,rest=l.partition(" ")
            m=rx.search(rest)
            if m and float(t)>=tmin and (not m.groups() or int(m.group(1))>=gmin):
                print(t); sys.exit(0)
    except (OSError,ValueError):
        pass
    time.sleep(0.002)'
wait_line() { python3 -c "$WAITPY" "$@"; }
# compute apps on either GPU before this trial launches anything (none of ours yet): any is another user's (section 8)
GPU_APPS="$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | grep -c .)/$(ssh -n "$SUNNY_SSH" "nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | grep -c ." 2>/dev/null)"
declare -A PID LT
T0=$(date +%s.%N)
# launch <name> <rank> <node> <extra env>: the process runs under `timeout`, its parent shell writes its own PID (the
# recorder looks for the gin_rs grandchild below it) and the exit code; stdout+stderr are stamped on rain
launch() {
  local name=$1 r=$2 node=$3 e=$4 pre=${5:-}
  LT[$name]=$(date +%s.%N)
  if [ "$node" = sunny ]; then
    ssh -n "$SUNNY_SSH" "cd \$HOME && umask 077 && echo \$\$ > $RT.$name.pid && $NENV $(hca sunny) $RS_ENV RS_RDV_NONCE=$NONCE $e \
stdbuf -oL -eL $pre timeout -s KILL $((WATCHDOG_S + 20)) $RSBIN $r $ARGS $RT.$name.kv 2>&1; echo \$? > $RT.$name.rc" \
      | python3 -u -c "$STAMP" > "$WORK/$name.log" 2>&1 &
  else
    ( echo $BASHPID > "$WORK/$name.pid"
      env $NENV $(hca rain) $RS_ENV RS_RDV_NONCE=$NONCE $e \
        stdbuf -oL -eL $pre timeout -s KILL $((WATCHDOG_S + 20)) "$RSBIN" "$r" $ARGS "$WORK/$name.kv" 2>&1
      echo $? > "$WORK/$name.rc" ) | python3 -u -c "$STAMP" > "$WORK/$name.log" 2>&1 &
  fi
  PID[$name]=$!
}
# strace of a spare (pilot, SPARE_STRACE=1; EXPERIMENT.md 9.15.4's method): only socket, connect and accept are traced
# (--seccomp-bpf where it works, so untraced calls do not stop the process). The raw trace holds addresses: it stays on its
# node and only the counts below leave it; the raw file is deleted right after counting.
SPROBE='if strace --seccomp-bpf -f -qq -e trace=connect -o /dev/null true 2>/dev/null; then echo 2; elif command -v strace >/dev/null; then echo 1; else echo 0; fi'
strace_mode() { if [ "$1" = sunny ]; then ssh -n "$SUNNY_SSH" "$SPROBE" 2>/dev/null; else bash -c "$SPROBE"; fi; }
strace_pre() {  # strace_pre <node> <name>: the prefix for launch (empty when strace is missing)
  local m; m=$(strace_mode "$1")
  case "$m" in
    2) echo "strace --seccomp-bpf -f -qq -ttt -e trace=socket,connect,accept,accept4 -o $(npath "$1" "$2.strace")" ;;
    1) echo "strace -f -qq -ttt -e trace=socket,connect,accept,accept4 -o $(npath "$1" "$2.strace")" ;;
  esac
}
# the counts (argv: trace, rt of spare_ready (0: unknown), own rank, own addresses...): connects to a peer (not loopback,
# not this node) before and after the spare was ready (an init replay makes none; after it, REJOIN and the data sockets),
# AF_UNIX connects to NCCL's proxy sockets (/tmp/nccl-socket-<rank>-<hash>) of its own rank and of other ranks apart.
STRACECNT_PY='import re,sys,collections
f,rt,own=sys.argv[1],float(sys.argv[2]),int(sys.argv[3]); ips=set(sys.argv[4:]); c=collections.Counter()
pat=re.compile(r"^\s*(?:\[pid\s+\d+\]\s*|\d+\s+)?(\d+\.\d+)\s+(socket|connect|accept4?)\((.*)")
for ln in open(f,errors="replace"):
    m=pat.match(ln)
    if not m: continue
    c["lines_matched"]+=1
    t,call,rest=float(m.group(1)),m.group(2),m.group(3)
    if call=="socket": c["socket"]+=1; continue
    if call.startswith("accept"): c["accept"]+=1; continue
    if "AF_UNIX" in rest or "AF_LOCAL" in rest:
        u=re.search(r"nccl-socket-(\d+)-",rest)
        if u: c["uds_own_rank" if int(u.group(1))==own else "uds_other_rank"]+=1
        else: c["uds_other"]+=1
        continue
    if "AF_INET" in rest:
        ips_=re.findall(r"inet_addr\(\"([^\"]+)\"\)|inet_pton\(AF_INET6, \"([^\"]+)\"",rest)
        ip=[a or b for a,b in ips_][0] if ips_ else ""
        if ip.startswith("127.") or ip=="::1": c["loop_connect"]+=1
        elif ip in ips: c["self_connect"]+=1
        elif rt and t < rt: c["peer_connect_before_ready"]+=1
        else: c["peer_connect_after_ready"]+=1
        continue
    c["other_connect"]+=1
keys=["lines_matched","socket","peer_connect_before_ready","peer_connect_after_ready","self_connect","loop_connect",
      "uds_own_rank","uds_other_rank","uds_other","other_connect","accept"]
print(" ".join("%s=%d"%(k,c[k]) for k in keys)+" rt_known=%d"%(1 if rt else 0))'
OWNIPS='ip -o addr show | awk "{print \$4}" | cut -d/ -f1 | tr "\n" " "'
strace_count() {  # strace_count <node> <name> <own rank>: counts into $WORK/<name>.stracecount, raw trace deleted
  local node=$1 name=$2 own=$3 rt
  rt=$(sed -n 's/.*GINRS spare_ready .* rt_s=\([0-9.]*\).*/\1/p' "$WORK/$name.log" 2>/dev/null | head -1); rt=${rt:-0}
  if [ "$node" = sunny ]; then
    local b64; b64=$(printf '%s' "$STRACECNT_PY" | base64 -w0)
    ssh -n "$SUNNY_SSH" "umask 077; if [ -f $RT.$name.strace ]; then echo $b64 | base64 -d > $RT.cnt.py && \
python3 $RT.cnt.py $RT.$name.strace $rt $own \$($OWNIPS); rm -f $RT.$name.strace $RT.cnt.py; else echo strace_missing=1; fi" \
      > "$WORK/$name.stracecount" 2>/dev/null
  else
    if [ -f "$WORK/$name.strace" ]; then python3 -c "$STRACECNT_PY" "$WORK/$name.strace" "$rt" "$own" $(bash -c "$OWNIPS") \
      > "$WORK/$name.stracecount"; rm -f "$WORK/$name.strace"; else echo strace_missing=1 > "$WORK/$name.stracecount"; fi
  fi
}
# the start gate (kill cells with a spare): rank 0 (rain) holds every live rank before step 0 until the spare is ready
GATE=""; [ -n "$KILL_RANK" ] && [ "$SPARE" = 1 ] && GATE=$WORK/start_gate
gate_env() { [ -n "$GATE" ] && [ "$1" = 0 ] && echo "RS_START_GATE=$GATE"; }
for ((r = N - 1; r >= 0; r--)); do
  launch "r$r" "$r" "$(node_of "$r")" "$(renv "$r") $(rec_env "$r") $(sa_env "$r") $(die_env "$r") $(gate_env "$r")"
done
# the recorded-PID kill (EXPERIMENT.md 8): PIDREC finds the gin_rs grandchild of the shell whose PID was written at its
# start (shell -> timeout -> gin_rs) and records "<pid> <its parent>"; PYK SIGKILLs that PID only while it is still the
# child of the recorded timeout and has the recorded name (no PID reuse). Nothing is ever killed by name.
PIDREC='for i in $(seq 1 200); do p=$(cat "$1" 2>/dev/null); [ -n "$p" ] || { sleep 0.1; continue; }
for a in $(pgrep -P "$p"); do for c in $(pgrep -P "$a"); do
[ "$(cat /proc/$c/comm 2>/dev/null)" = "$3" ] && { echo "$c $a" > "$2"; exit 0; }; done; done; sleep 0.1; done; exit 1'
PYK='import os,sys; c,p,n=int(sys.argv[1]),sys.argv[2],sys.argv[5]; s=open("/proc/%d/stat"%c).read(); assert s[s.index("(")+1:s.rindex(")")]==n[:15] and s.rsplit(")",1)[1].split()[1]==p, "not the recorded process"; os.kill(c,9); print("GINRS killed rank=%s node=%s pid=%d" % (sys.argv[3],sys.argv[4],c))'
# kill_spare_now <node> <rank>: the spare-absent cell (SPARE_KILL_FIRST=1): the spare registered and got ready, and is
# SIGKILLed by its recorded PID before its rank dies, so the buddy's activation finds no spare (not with SPARE_STRACE)
kill_spare_now() {
  local node=$1 rk=$2 c p
  if [ "$node" = sunny ]; then
    ssh -n "$SUNNY_SSH" "bash -c '$PIDREC' _ $RT.spare.pid $RT.spare.cpid $BINNAME; read c p < $RT.spare.cpid 2>/dev/null; \
if [ -n \"\$c\" ] && [ -n \"\$p\" ]; then python3 -c '$PYK' \"\$c\" \"\$p\" $rk sunny $BINNAME; else echo GINRS no_process rank=$rk; fi"
  else
    bash -c "$PIDREC" _ "$WORK/spare.pid" "$WORK/spare_target.pid" "$BINNAME"
    read -r c p < "$WORK/spare_target.pid" 2>/dev/null
    if [ -n "${c:-}" ] && [ -n "${p:-}" ]; then python3 -c "$PYK" "$c" "$p" "$rk" rain "$BINNAME"; else echo "GINRS no_process rank=$rk"; fi
  fi 2>&1 | python3 -u -c "$STAMP" > "$WORK/spare_kill.out"
}
SPARE_ON=0; T_READY=0
if [ -n "$SPORT" ] && [ "$SPARE" = 1 ]; then
  # the spare (same node and GPU as KILL_RANK) replays KILL_RANK's init transcript: start it once that transcript is
  # complete, i.e. after KILL_RANK's Resume (whose exchange is the transcript's last entry; EXPERIMENT.md 9.14 item 8)
  KR=$KILL_RANK; knode=$(node_of "$KR")
  if [ -n "$(wait_line "$WORK/r$KR.log" "GINRS resume rank=$KR " 0 0 60)" ]; then
    SPRE=""; [ "${SPARE_STRACE:-0}" = 1 ] && SPRE=$(strace_pre "$knode" spare)
    launch spare "$KR" "$knode" "NCCL_GIN_RESTORE_SPARE=$KR NCCL_GIN_RESTORE_SPARE_PORT=$SPORT NCCL_GIN_RESTORE_SPARE_WAIT_MS=$SPARE_WAIT_MS NCCL_GIN_RESTORE_REPLAY=$(npath "$knode" "r$KR.rec")" "$SPRE"
    SPARE_ON=1
    # ready: its init replay is done and its Resume waits for the activation (bounded; a slow spare is a pilot finding)
    T_READY=$(wait_line "$WORK/spare.log" "GINRS spare_ready rank=$KR " 0 0 60); T_READY=${T_READY:-0}
    [ "${SPARE_KILL_FIRST:-0}" = 1 ] && [ "$T_READY" != 0 ] && kill_spare_now "$knode" "$KR"
  fi
fi
[ -n "$GATE" ] && touch "$GATE"   # open the start gate: the spare is ready, or its waits ran out (meta spare_ready says which)
ARM_WAIT=-; T_ARMED=0
if [ -n "$KILL_RANK" ] && [ "$KILL_IN_HOOK" = 1 ]; then
  # arm the checkpoint-pause kill once every survivor printed the library's line that KR is armed at a stable checkpoint
  # (after the start gate: the spare is ready, or its waits ran out); KR then dies in its next checkpoint's pause
  ARM_WAIT=ok; aend=$(awk -v s="$ARM_WAIT_S" 'BEGIN{printf "%.3f", s}')
  for ((s = 0; s < N; s++)); do
    [ "$s" = "$KILL_RANK" ] && continue
    t=$(wait_line "$WORK/r$s.log" "GIN/RS: rank $s: rank $KILL_RANK armed at its stable checkpoint [0-9]+" 0 0 "$aend")
    if [ -z "$t" ]; then ARM_WAIT=timeout; break; fi
    T_ARMED=$(awk -v a="$T_ARMED" -v b="$t" 'BEGIN{print (b > a ? b : a)}')
  done
  if [ "$ARM_WAIT" = ok ]; then
    if [ "$(node_of "$KILL_RANK")" = sunny ]; then ssh -n "$SUNNY_SSH" "touch $RT.arm"; else touch "$WORK/arm"; fi
  fi
fi

KILLER=""; RECORDER=""
if [ -n "$KILL_RANK" ] && [ "$KILL_IN_HOOK" != 1 ]; then
  KR=$KILL_RANK; knode=$(node_of "$KR")
  # record KR's gin_rs PID and its parent (the recorded `timeout`), a grandchild of the shell PID written at its start
  if [ "$knode" = sunny ]; then
    ssh -n "$SUNNY_SSH" "bash -c '$PIDREC' _ $RT.r$KR.pid $RT.r$KR.cpid $BINNAME" &
  else
    bash -c "$PIDREC" _ "$WORK/r$KR.pid" "$WORK/kill_target.pid" "$BINNAME" &
  fi
  RECORDER=$!
  # fire inside the traffic: the first stamped line of KR for a step >= KILL_AT_STEP that arrived after the spare was ready
  # (or after start without a spare), then KILL_DELAY_US; if no such line comes within KILL_DELAY_MS, kill anyway
  ( wait_line "$WORK/r$KR.log" "GINRS step rank=$KR step=([0-9]+) released=0" "$T_READY" "$KILL_AT_STEP" \
      "$(awk -v d="$KILL_DELAY_MS" 'BEGIN{printf "%.3f", d / 1000}')" > /dev/null
    sleep "$(awk -v u="$KILL_DELAY_US" 'BEGIN{printf "%.6f", u / 1e6}')"
    # SIGKILL the recorded PID only while it is still the child of the recorded timeout and named as recorded
    if [ "$knode" = sunny ]; then
      ssh -n "$SUNNY_SSH" "for i in \$(seq 1 50); do [ -s $RT.r$KR.cpid ] && break; sleep 0.1; done; \
read c p < $RT.r$KR.cpid 2>/dev/null; \
if [ -n \"\$c\" ] && [ -n \"\$p\" ]; then python3 -c '$PYK' \"\$c\" \"\$p\" $KR sunny $BINNAME; else echo GINRS no_process rank=$KR; fi"
    else
      for i in $(seq 1 50); do [ -s "$WORK/kill_target.pid" ] && break; sleep 0.1; done
      read -r c p < "$WORK/kill_target.pid" 2>/dev/null
      if [ -n "${c:-}" ] && [ -n "${p:-}" ]; then python3 -c "$PYK" "$c" "$p" "$KR" rain "$BINNAME"; else echo "GINRS no_process rank=$KR"; fi
    fi 2>&1 | python3 -u -c "$STAMP" > "$WORK/kill.out" ) &
  KILLER=$!
fi

for ((r = 0; r < N; r++)); do wait "${PID[r$r]}" 2>/dev/null; done
[ "$SPARE_ON" = 1 ] && wait "${PID[spare]}" 2>/dev/null
T1=$(date +%s.%N)
[ -n "$KILLER" ] && wait "$KILLER" "$RECORDER" 2>/dev/null
[ "$SPARE_ON" = 1 ] && [ "${SPARE_STRACE:-0}" = 1 ] && strace_count "$(node_of "$KILL_RANK")" spare "$KILL_RANK"
# the negative controls of the init replay (pilot, NEG_REPLAY=1; EXPERIMENT.md 9.15.4 b1_neg): after the live ranks ended,
# two spares on NEG_RANK's node replay a cut copy and a copy with one field changed (the first entry's element size, bytes
# 32..39 of the first entry header after the 24-byte file header and the 128-byte commId; offset NEG_FIELD_OFF); both must
# fail in the replay, with no peer connect (strace). The copies are mode 0600 next to the record and deleted after.
NEGS=""
if [ "${NEG_REPLAY:-0}" = 1 ] && [ "$FAULT_POLICY" = hold ]; then
  NR=${NEG_RANK:-3}; nnode=$(node_of "$NR"); rec=$(npath "$nnode" "r$NR.rec")
  cut=$(npath "$nnode" neg_cut.rec); fld=$(npath "$nnode" neg_field.rec); off=${NEG_FIELD_OFF:-184}
  MK="umask 077; [ -s $rec ] && head -c \$(( \$(stat -c %s $rec) / 2 )) $rec > $cut && \
python3 -c 'import sys; b=bytearray(open(sys.argv[1],\"rb\").read()); b[int(sys.argv[3])]^=0x10; open(sys.argv[2],\"wb\").write(bytes(b))' $rec $fld $off && echo made"
  if [ "$nnode" = sunny ]; then made=$(ssh -n "$SUNNY_SSH" "$MK"); else made=$(bash -c "$MK"); fi
  if [ "$made" = made ]; then
    save=$PORT; pick_port $(( PORT + 2 > PORT_HI ? PORT_LO : PORT + 2 )); NPORT=$PORT; PORT=$save
    for neg in neg_cut neg_field; do
      NPRE=$(strace_pre "$nnode" "$neg")
      launch "$neg" "$NR" "$nnode" "NCCL_GIN_RESTORE_SPARE=$NR NCCL_GIN_RESTORE_SPARE_PORT=$NPORT NCCL_GIN_RESTORE_REPLAY=$(npath "$nnode" "$neg.rec") RS_WATCHDOG_S=40" "$NPRE"
      wait "${PID[$neg]}" 2>/dev/null
      strace_count "$nnode" "$neg" "$NR"
      NEGS="$NEGS $neg"
    done
  fi
  if [ "$nnode" = sunny ]; then ssh -n "$SUNNY_SSH" "rm -f $cut $fld"; else rm -f "$cut" "$fld"; fi
fi
# what this trial ran on rain (read after the trial, so the reads do not touch its timing)
LIB_MD5=$(md5sum < "$LIBDIR/libnccl.so.2" 2>/dev/null | cut -c1-32); LIB_MD5=${LIB_MD5:-none}
DRIVER_MD5=$(md5sum < "$RSBIN" 2>/dev/null | cut -c1-32); DRIVER_MD5=${DRIVER_MD5:-none}
# the sunny-side kv and exit codes
names="r0 r1 r2 r3"; [ "$SPARE_ON" = 1 ] && names="$names spare"; names="$names$NEGS"
for name in $names; do
  if [ -f "$WORK/$name.kv" ]; then continue; fi
  scp -q "$SUNNY_SSH:$RT.$name.kv" "$WORK/$name.kv" 2>/dev/null || true
  scp -q "$SUNNY_SSH:$RT.$name.rc" "$WORK/$name.rc" 2>/dev/null || true
done
ssh -n "$SUNNY_SSH" "rm -f $RT.*" 2>/dev/null || true
# nothing is killed here: every timeout has exited (wait above). LEFT is a read-only count of this study's own program name.
LEFT=$( { pgrep -x "$BINNAME"; ssh -n "$SUNNY_SSH" "pgrep -x $BINNAME"; } 2>/dev/null | wc -l)
mkdir -p "$LOGDIR"
stem="${CELL:-rs}_${LIB}_${TRIAL}"   # the build is in the stem: rs4_kill3@rs and rs4_kill3@hk never collide in one folder
MASK='s/[0-9]\{1,3\}\.[0-9]\{1,3\}\.[0-9]\{1,3\}\.[0-9]\{1,3\}/<ip>/g'
for name in $names; do
  [ -f "$WORK/$name.kv" ] && sed "$MASK" "$WORK/$name.kv" > "$LOGDIR/${stem}_$name.kv"
  [ -f "$WORK/$name.log" ] && sed "$MASK" "$WORK/$name.log" > "$LOGDIR/${stem}_$name.log"
done
[ -f "$WORK/kill.out" ] && sed "$MASK" "$WORK/kill.out" > "$LOGDIR/${stem}_kill.out"
[ -f "$WORK/spare_kill.out" ] && sed "$MASK" "$WORK/spare_kill.out" > "$LOGDIR/${stem}_spare_kill.out"
for name in $names; do  # strace counts only (the raw traces never left their node)
  [ -f "$WORK/$name.stracecount" ] && sed "$MASK" "$WORK/$name.stracecount" > "$LOGDIR/${stem}_${name}_strace.txt"
done
rcs=""; for name in $names; do rcs="$rcs ${name}rc=$(tr -d '\n' < "$WORK/$name.rc" 2>/dev/null || echo none)"; done
echo "cell=${CELL:-} lib=$LIB n=$N steps=$STEPS bytes=$BYTES policy=$FAULT_POLICY restore=$RESTORE sym_gin=$SYM_GIN \
gin_type=$GIN_TYPE num_rma_ctx=$NUM_RMA_CTX nconn=$NCONN qpwatch_ms=$QPWATCH restore_ms=$RESTORE_MS checksum=$CHECKSUM \
log_measure=$LOG_MEASURE step_gap_us=$STEP_GAP_US kill_rank=${KILL_RANK:-} kill_at_step=$KILL_AT_STEP kill_delay_us=$KILL_DELAY_US kill_fallback_ms=$KILL_DELAY_MS kill_in_hook=$KILL_IN_HOOK kill_hook_us=$KILL_HOOK_US \
die_switch=$([ "$KILL_IN_HOOK" = 1 ] && echo NCCL_GIN_RESTORE_TEST_DIE_IN_CKPT || echo -) arm_wait=$ARM_WAIT arm_wait_s=$ARM_WAIT_S armed_rt=$T_ARMED spare_wait_ms=$SPARE_WAIT_MS \
spare=$SPARE_ON spare_wanted=$SPARE spare_kill_first=${SPARE_KILL_FIRST:-0} spare_ready=$([ "$T_READY" != 0 ] && echo 1 || echo 0) gpu_apps_before=$GPU_APPS \
spare_strace=${SPARE_STRACE:-0} neg_replay=${NEG_REPLAY:-0} negs=$(echo $NEGS | tr " " ",") end_grace_ms=$END_GRACE_MS spare_addr_set=$([ -n "$SADDR_ENV" ] && echo 1 || echo 0) trial=$TRIAL extra=$(echo ${EXTRA_ENV:-} | tr ' ' '+')$rcs left=$LEFT gid0=$GID0 gid1=$GID1 port=$PORT \
port_tries=$PORT_TRIES rdv_nonce_set=1 runner=rsr driver=$DRIVER continue_after_refusal=${CONTINUE_AFTER_REFUSAL:-0} wall_s=$(awk -v a="$T0" -v b="$T1" 'BEGIN{printf "%.1f", b - a}') \
bin=$BINNAME rs_set=${RS_SET:--} lib_md5=$LIB_MD5 driver_md5=$DRIVER_MD5" > "$LOGDIR/${stem}_meta.txt"
echo "[$tag]$rcs left=$LEFT wall=$(awk -v a="$T0" -v b="$T1" 'BEGIN{printf "%.1f", b - a}')s :: $(grep -ho 'xchg=[a-z]*' "$WORK"/*.kv 2>/dev/null | tr '\n' ' ')" >&2
exit 0
