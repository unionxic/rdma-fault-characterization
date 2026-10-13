#!/usr/bin/env bash
# run_mi.sh - gin-mirror, test branch: one restore trial of ../../EXPERIMENT.md 7 / 9.8. gin-restore's runner
# (../../../restore/impl/test/run_rs.sh, copied and then extended) for the mirror layer: four live ranks of gin_mi (rank r on
# rain when r is even, on sunny when r is odd, NCCL_MULTI_RANK_GPU_ENABLE=1, two ranks per GPU) and up to two spare
# processes, each on the SAME node and GPU as the rank it may revive (NCCL_GIN_RESTORE_SPARE=<rank>).
#
# What is new against run_rs.sh (the rest is its text and behaviour):
#   - the library is the mirror layer's (LIB mi | mip, ~/rs-bundle/<RS_SET>/lib/<LIB>) and the driver gin_mi |
#     gin_mi_nomacro (~/rs-bundle/<RS_SET>/mitest/); RS_SET must be named (rs_set_mi.sh);
#   - the mirror's variables (cell names: MIRROR, MIRROR_SLOTS, MIRROR_LANE, MIRROR_PULL, POOL_MAX_MB, FETCH_MB,
#     STORE_WRITE_MS -> NCCL_GIN_RESTORE_MIRROR, _MIRROR_SLOTS, _MIRROR_LANE, _MIRROR_PULL, _MIRROR_POOL_MAX_MB,
#     _MIRROR_FETCH_MB, NCCL_GIN_RESTORE_STORE_WRITE_MS; impl/rs_mirror_api.h, rs_store_api.h) and the workload's (OVERWRITE,
#     TRAIN, RING -> gin_mi's RS_OVERWRITE, RS_TRAIN, RS_RING);
#   - kills drawn from a seed (DIE_SEED with DIE_LO..DIE_HI and DIE_US_MAX): the driver's own step kill GIN_RS_DIE_AT=<step>:<us>
#     given to KILL_RANK (EXPERIMENT.md 7: the training kill cells; the second-death cells), step and in-step delay drawn
#     by draw() below from (seed, cell, trial, rank, which) with sha256, so a trial's kill is fixed once the seed is;
#   - the second death: KILL2_RANK with DIE2_LO..DIE2_HI (always the driver's step kill, 7절: not the library test switch)
#     and SPARE2=1 (a second spare, for KILL2_RANK, files <stem>_spare_2nd.*). Both ranks get their spare's address. The
#     start gate opens once every wanted spare is ready;
#   - KILL_AFTER_STABLE=<n> (the segment cells, "확정 체크포인트 뒤 15단계째 kill"): the recorded-PID kill of KILL_RANK at its
#     first step line >= K + n, K the first checkpoint of KILL_RANK whose "checkpoint K stable at buddy" line arrived after
#     the spare was ready (KILL_DELAY_US after that step line, as the traffic kill);
#   - the host-memory start check of section 8: each node's MemAvailable must hold the pinned memory this trial's
#     processes register (pool, store slots, D2H buffer, a spare's FETCH buffer; the estimate below) + 1 GiB, else the
#     runner writes nothing and exits 5 (cells_mi.sh then writes STOP_mem);
#   - pilot-only features of run_rs.sh not carried over: SPARE_STRACE, NEG_REPLAY, SPARE_ADDR without a spare.
#
# Receipt clock, safety, rendezvous, IPv4 masking and the recorded-PID kill are run_rs.sh's (its head comment): every
# process is bounded by `timeout -s KILL`; nothing is killed by name; the only kills are the recorded-PID kills of
# KILL_RANK (traffic, after-stable) and of a spare (SPARE_KILL_FIRST); a driver kill is the process's own SIGKILL. sunny's
# management address comes from SUNNY_SSH only and rain's is looked up at run time; neither is written to a file (copied
# logs are IPv4-masked). Every NCCL_ and GIN_ variable of the caller is dropped first. No link, address, driver or firewall
# is touched. Run only by the main session, inside ../../../../common/cluster_run.sh through hold_mi.sh.
#
# usage: run_mi.sh <trial-tag> <logdir>
# env: SUNNY_SSH (required), RS_SET (required), CELL, LIB (mi | mip), DRIVER (gin_mi | gin_mi_nomacro; default gin_mi),
#   N (4), STEPS (600; TRAIN=1: 2000), BYTES (4096; TRAIN=1: 2097152), STEP_GAP_US (5000), OVERWRITE (0), TRAIN (0),
#   RING (4), MIRROR (1), MIRROR_SLOTS, MIRROR_LANE, MIRROR_PULL, POOL_MAX_MB, FETCH_MB, STORE_WRITE_MS (empty: the
#   library's default), FAULT_POLICY (hold), RESTORE (1), CHECKSUM (off), CKPT_STEPS, QPWATCH (10; the training cells 50,
#   EXPERIMENT.md 6), RESTORE_MS (20000), RESUME_MS (30000), SYM_GIN (0), CELL_GIN_TYPE (3), RMA_DISABLE (1),
#   NUM_RMA_CTX (0), NCONN (1), LOG_MEASURE (0), WATCHDOG_S (90; 200 with a spare), SPARE_WAIT_MS (60000; the training cells
#   120000), END_GRACE_MS (3000 with a spare), KILL_RANK, SPARE, SPARE_KILL_FIRST, KILL_AT_STEP (100), KILL_DELAY_US (500),
#   KILL_DELAY_MS (30000), KILL_IN_HOOK, KILL_HOOK_US (300), ARM_WAIT_S (60), KILL_AFTER_STABLE, DIE_SEED, DIE_LO, DIE_HI,
#   DIE_US_MAX (4000), KILL2_RANK, DIE2_LO, DIE2_HI, SPARE2, CONTINUE_AFTER_REFUSAL, R<r>_ENV, EXTRA_ENV, PORT_LO, PORT_HI.
#   RS_DRY_CONFIG=1 (CPU self-test): print the configuration line (with the drawn kills and the memory estimate) and exit
#   before any file, address, ssh or process is touched.
# files in <logdir>: <stem>_r<r>.kv/.log, <stem>_spare.kv/.log, <stem>_spare_2nd.kv/.log, <stem>_kill.out,
#   <stem>_spare_kill.out, <stem>_meta.txt (stem = <cell>_<lib>_<tag>); meta names the set, the md5 of the library and the
#   driver this trial used on rain, the drawn kills and the memory check.
set -u
TRIAL=${1:?trial tag}; LOGDIR=${2:?logdir}
for v in $(env | sed -n 's/^\(\(NCCL\|GIN\)_[A-Za-z0-9_]*\)=.*/\1/p'); do unset "$v"; done
N=${N:-4}
[ "$N" = 4 ] || { echo "run_mi.sh is the 4-rank workload (N=4)" >&2; exit 1; }
LIB=${LIB:-mi}
RS_SET=${RS_SET:-}
D=$(cd "$(dirname "$0")" && pwd)
. "$D/rs_set_mi.sh"
rs_set_check || exit 1
RSB=$HOME/rs-bundle/$RS_SET
case "$LIB" in mi|mip) LIBDIR=$RSB/lib/$LIB ;; *) echo "unknown LIB $LIB (mi | mip)" >&2; exit 1 ;; esac
DRIVER=${DRIVER:-gin_mi}
case "$DRIVER" in gin_mi|gin_mi_nomacro) ;; *) echo "driver $DRIVER is not a gin-mirror driver" >&2; exit 1 ;; esac
RSBIN=$RSB/mitest/$DRIVER
BINNAME=$(basename "$RSBIN")
TRAIN=${TRAIN:-0}; OVERWRITE=${OVERWRITE:-0}; RING=${RING:-4}
if [ "$TRAIN" = 1 ]; then STEPS=${STEPS:-2000}; BYTES=${BYTES:-2097152}; else STEPS=${STEPS:-600}; BYTES=${BYTES:-4096}; fi
STEP_GAP_US=${STEP_GAP_US:-5000}
KILL_AT_STEP=${KILL_AT_STEP:-100}; KILL_DELAY_US=${KILL_DELAY_US:-500}
FAULT_POLICY=${FAULT_POLICY:-hold}; RESTORE=${RESTORE:-1}; SYM_GIN=${SYM_GIN:-0}; GIN_TYPE=${CELL_GIN_TYPE:-3}
RMA_DISABLE=${RMA_DISABLE:-1}; NUM_RMA_CTX=${NUM_RMA_CTX:-0}; NCONN=${NCONN:-1}; QPWATCH=${QPWATCH:-10}
RESTORE_MS=${RESTORE_MS:-20000}; RESUME_MS=${RESUME_MS:-30000}; LOG_MEASURE=${LOG_MEASURE:-0}; CHECKSUM=${CHECKSUM:-off}
MIRROR=${MIRROR:-1}
KILL_RANK=${KILL_RANK:-}; KILL_DELAY_MS=${KILL_DELAY_MS:-30000}; KILL_IN_HOOK=${KILL_IN_HOOK:-0}; KILL_HOOK_US=${KILL_HOOK_US:-300}
ARM_WAIT_S=${ARM_WAIT_S:-60}; KILL_AFTER_STABLE=${KILL_AFTER_STABLE:-}
SPARE=${SPARE:-0}; SPARE_WAIT_MS=${SPARE_WAIT_MS:-60000}
KILL2_RANK=${KILL2_RANK:-}; SPARE2=${SPARE2:-0}
DIE_SEED=${DIE_SEED:-}; DIE_US_MAX=${DIE_US_MAX:-4000}
WATCHDOG_S=${WATCHDOG_S:-$( { [ -n "$KILL_RANK" ] && [ "$SPARE" = 1 ]; } || [ "$SPARE2" = 1 ] && echo 200 || echo 90 )}
# draw <lo> <hi> <which>: "<step> <us>", step in [lo, hi] and us in [0, DIE_US_MAX], from sha256 of (seed, cell, trial,
# which); the same seed gives the same kills for the same cell and trial (EXPERIMENT.md 7: the seed is fixed at the
# pre-registration)
DRAWPY='import hashlib,sys
seed,cell,trial,which,lo,hi,umax=sys.argv[1:8]; lo,hi,umax=int(lo),int(hi),int(umax)
h=hashlib.sha256(("gin-mirror|%s|%s|%s|%s"%(seed,cell,trial,which)).encode()).digest()
a=int.from_bytes(h[:8],"big"); b=int.from_bytes(h[8:16],"big")
print(lo+a%(hi-lo+1), b%(umax+1))'
draw() { python3 -c "$DRAWPY" "$DIE_SEED" "${CELL:-}" "$TRIAL" "$3" "$1" "$2" "$DIE_US_MAX"; }
DIE_AT=""; DIE2_AT=""
if [ -n "${DIE_LO:-}" ] && [ -n "$KILL_RANK" ]; then
  [ -n "$DIE_SEED" ] || { echo "DIE_LO without DIE_SEED" >&2; exit 1; }
  read -r ds du <<< "$(draw "$DIE_LO" "${DIE_HI:-$DIE_LO}" first)"; DIE_AT="$ds:$du"
fi
if [ -n "$KILL2_RANK" ]; then
  [ -n "$DIE_SEED" ] && [ -n "${DIE2_LO:-}" ] || { echo "KILL2_RANK needs DIE_SEED and DIE2_LO" >&2; exit 1; }
  [ "$KILL2_RANK" != "$KILL_RANK" ] || { echo "KILL2_RANK equals KILL_RANK" >&2; exit 1; }
  read -r ds du <<< "$(draw "$DIE2_LO" "${DIE2_HI:-$DIE2_LO}" second)"; DIE2_AT="$ds:$du"
fi
# the kill of KILL_RANK: driver (DIE_AT), library switch (KILL_IN_HOOK), after-stable (KILL_AFTER_STABLE), or traffic
if [ -n "$DIE_AT" ]; then KILL_KIND=driver; elif [ "$KILL_IN_HOOK" = 1 ]; then KILL_KIND=hook
elif [ -n "$KILL_AFTER_STABLE" ]; then KILL_KIND=after_stable; elif [ -n "$KILL_RANK" ]; then KILL_KIND=traffic; else KILL_KIND=-; fi
# the pinned host memory of this trial per node (MiB; section 8's start check), the mirror layer's sizes (impl/rs_mirror_api.h
# pool = S x (n - 1) x L for one ward; impl/rs_store_api.h store = 2 slots of 64 KiB + image + 1 MiB; the D2H buffer = image;
# a spare's FETCH buffer FETCH_MB, default 512). image = the two windows and the registered state, as gin_mi sizes them.
MEMPY='import sys,math
n,steps,b,train,ring,ow,mirror,slots,lane,fetch=[int(x) for x in sys.argv[1:11]]
M=1<<20; r2=lambda v:((v+2*M-1)//(2*M))*2*M
if train: send=r2((n-1)*b); recv=r2((n-1)*ring*b); state=4*steps+8*(steps+1)
else:
    reg=b*steps; slotsb=reg*(n-1); sendslots=(n-1)*b if ow else slotsb; x=(sendslots+255)//256*256
    send=r2(x+8*(steps+1)); recv=r2(slotsb); state=4*steps
img=math.ceil((send+recv+state)/M)
per=0
if mirror: per=math.ceil(slots*(n-1)*lane/M)+2*(img+2)+1+img
print(per, img, fetch if mirror else 0)'
read -r PIN_PER IMG_MB FETCH_PIN <<< "$(python3 -c "$MEMPY" "$N" "$STEPS" "$BYTES" "$TRAIN" "$RING" "$OVERWRITE" \
  "$MIRROR" "${MIRROR_SLOTS:-3}" "${MIRROR_LANE:-1048576}" "${FETCH_MB:-512}")"
node_of() { [ $(( $1 % 2 )) -eq 0 ] && echo rain || echo sunny; }
need_mb() {  # need_mb <node>: two live ranks + the spares on that node, + 1 GiB
  local nd=$1 n=2 sp=0
  [ "$SPARE" = 1 ] && [ -n "$KILL_RANK" ] && [ "$(node_of "$KILL_RANK")" = "$nd" ] && sp=$((sp + 1))
  [ "$SPARE2" = 1 ] && [ -n "$KILL2_RANK" ] && [ "$(node_of "$KILL2_RANK")" = "$nd" ] && sp=$((sp + 1))
  echo $(( (n + sp) * PIN_PER + sp * FETCH_PIN + 1024 ))
}
NEED_RAIN=$(need_mb rain); NEED_SUNNY=$(need_mb sunny)
if [ "${RS_DRY_CONFIG:-0}" = 1 ]; then
  echo "cell=${CELL:-} lib=$LIB driver=$DRIVER policy=$FAULT_POLICY restore=$RESTORE sym_gin=$SYM_GIN gin_type=$GIN_TYPE \
rma_disable=$RMA_DISABLE num_rma_ctx=$NUM_RMA_CTX nconn=$NCONN qpwatch_ms=$QPWATCH restore_ms=$RESTORE_MS checksum=$CHECKSUM \
log_measure=$LOG_MEASURE ckpt_steps=${CKPT_STEPS:-} kill_rank=${KILL_RANK:-} kill_in_hook=$KILL_IN_HOOK spare_wanted=$SPARE \
spare_kill_first=${SPARE_KILL_FIRST:-0} continue_after_refusal=${CONTINUE_AFTER_REFUSAL:-0} \
r0_env=$(echo ${R0_ENV:-} | tr ' ' '+') r1_env=$(echo ${R1_ENV:-} | tr ' ' '+') r2_env=$(echo ${R2_ENV:-} | tr ' ' '+') \
r3_env=$(echo ${R3_ENV:-} | tr ' ' '+') rs_set=$RS_SET spare_wait_ms=$SPARE_WAIT_MS mirror=$MIRROR \
mirror_slots=${MIRROR_SLOTS:-} mirror_lane=${MIRROR_LANE:-} mirror_pull=${MIRROR_PULL:-} pool_max_mb=${POOL_MAX_MB:-} \
fetch_mb=${FETCH_MB:-} store_write_ms=${STORE_WRITE_MS:-} overwrite=$OVERWRITE train=$TRAIN ring=$RING steps=$STEPS \
bytes=$BYTES kill_kind=$KILL_KIND kill_after_stable=${KILL_AFTER_STABLE:-} die_seed=${DIE_SEED:-} die_at=${DIE_AT:--} \
kill2_rank=${KILL2_RANK:-} die2_at=${DIE2_AT:--} spare2_wanted=$SPARE2 die_us_max=$DIE_US_MAX watchdog_s=$WATCHDOG_S pin_mb_per_proc=$PIN_PER \
image_mb=$IMG_MB need_mb_rain=$NEED_RAIN need_mb_sunny=$NEED_SUNNY"
  exit 0
fi
SUNNY_SSH=${SUNNY_SSH:?set SUNNY_SSH}
SUNNY_HOST=${SUNNY_SSH#*@}
[ -x "$RSBIN" ] && [ -f "$LIBDIR/libnccl.so.2" ] || { echo "missing $RSBIN or $LIBDIR/libnccl.so.2 on rain" >&2; exit 1; }
# section 8's start check: MemAvailable on both nodes (read only)
AVAIL_RAIN=$(awk '/^MemAvailable:/{print int($2/1024)}' /proc/meminfo)
AVAIL_SUNNY=$(ssh -n "$SUNNY_SSH" "awk '/^MemAvailable:/{print int(\$2/1024)}' /proc/meminfo" 2>/dev/null)
if [ -z "$AVAIL_RAIN" ] || [ -z "$AVAIL_SUNNY" ] || [ "$AVAIL_RAIN" -lt "$NEED_RAIN" ] || [ "$AVAIL_SUNNY" -lt "$NEED_SUNNY" ]; then
  echo "host memory short for ${CELL:-}#$TRIAL: rain ${AVAIL_RAIN:-?}/$NEED_RAIN MiB, sunny ${AVAIL_SUNNY:-?}/$NEED_SUNNY MiB (available/needed)" >&2
  exit 5
fi
RAIN_MGMT=$(ip -4 route get "$SUNNY_HOST" 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p' | head -1)
[ -n "$RAIN_MGMT" ] || { echo "cannot find rain's management address" >&2; exit 1; }
umask 077
WORK=$(mktemp -d /tmp/mi_rt.XXXXXX)
RT=/tmp/mi_rt_$$_$RANDOM      # sunny-side file prefix of this trial
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
STAMP='import sys,time
for l in sys.stdin.buffer:
    sys.stdout.write("%.6f %s\n" % (time.clock_gettime(time.CLOCK_MONOTONIC), l.decode("utf-8","replace").rstrip("\n")))
    sys.stdout.flush()'
# the hold-process configuration of gin-restore (run_rs.sh) plus the mirror's variables
MIENV="NCCL_GIN_RESTORE_MIRROR=$MIRROR ${MIRROR_SLOTS:+NCCL_GIN_RESTORE_MIRROR_SLOTS=$MIRROR_SLOTS} \
${MIRROR_LANE:+NCCL_GIN_RESTORE_MIRROR_LANE=$MIRROR_LANE} ${MIRROR_PULL:+NCCL_GIN_RESTORE_MIRROR_PULL=$MIRROR_PULL} \
${POOL_MAX_MB:+NCCL_GIN_RESTORE_MIRROR_POOL_MAX_MB=$POOL_MAX_MB} ${FETCH_MB:+NCCL_GIN_RESTORE_MIRROR_FETCH_MB=$FETCH_MB} \
${STORE_WRITE_MS:+NCCL_GIN_RESTORE_STORE_WRITE_MS=$STORE_WRITE_MS}"
NENV="NCCL_DEBUG=WARN NCCL_DEBUG_SUBSYS=INIT,NET NCCL_SOCKET_IFNAME=eno1 NCCL_GIN_TYPE=$GIN_TYPE NCCL_GIN_ENABLE=1 \
NCCL_IB_TIMEOUT=14 NCCL_GIN_FAULT_CLASSIFY=1 NCCL_GIN_FAULT_RECOVERY=1 NCCL_GIN_FAULT_TRANSPARENT=1 \
NCCL_MULTI_RANK_GPU_ENABLE=1 NCCL_GIN_TS_QPWATCH_MS=$QPWATCH NCCL_GIN_FAULT_POLICY=$FAULT_POLICY NCCL_GIN_RESTORE=$RESTORE \
NCCL_SYM_GIN_KERNELS_ENABLE=$SYM_GIN NCCL_RMA_DISABLE=$RMA_DISABLE NCCL_NUM_RMA_CTX=$NUM_RMA_CTX NCCL_GIN_NCONNECTIONS=$NCONN \
NCCL_GIN_RESTORE_MS=$RESTORE_MS NCCL_GIN_RESTORE_RESUME_MS=$RESUME_MS NCCL_GIN_RESTORE_CHECKSUM=$CHECKSUM \
NCCL_GIN_RESTORE_LOG_MEASURE=$LOG_MEASURE ${CKPT_STEPS:+NCCL_GIN_RESTORE_CKPT_STEPS=$CKPT_STEPS} $MIENV \
NCCL_GIN_Q4_QPWATCH_MS=0 NCCL_RAS_ENABLE=0 LD_LIBRARY_PATH=$LIBDIR ${EXTRA_ENV:-}"
ANYSPARE=0; { [ -n "$KILL_RANK" ] && [ "$SPARE" = 1 ]; } && ANYSPARE=1; { [ -n "$KILL2_RANK" ] && [ "$SPARE2" = 1 ]; } && ANYSPARE=1
END_GRACE_MS=${END_GRACE_MS:-$( [ "$ANYSPARE" = 1 ] && echo 3000 || echo 0 )}
RS_ENV="RS_STEPS=$STEPS RS_BYTES=$BYTES RS_WATCHDOG_S=$WATCHDOG_S RS_STEP_GAP_US=$STEP_GAP_US RS_END_GRACE_MS=$END_GRACE_MS \
RS_CONTINUE_AFTER_REFUSAL=${CONTINUE_AFTER_REFUSAL:-0} RS_OVERWRITE=$OVERWRITE RS_TRAIN=$TRAIN RS_RING=$RING"
NONCE=$(new_nonce)
pick_port
# the spares' addresses (gin-restore 9.3): a port on each spare's node, picked before any launch so the rank gets it at its
# start. Neither address is written to a file.
nextport() { pick_port $(( $1 + 1 > PORT_HI ? PORT_LO : $1 + 1 )); }
SPORT=""; SADDR_ENV=""; SPORT2=""; SADDR2_ENV=""
save=$PORT; savet=$PORT_TRIES; last=$PORT
addr_of() { if [ "$(node_of "$1")" = sunny ]; then echo "$SUNNY_HOST"; else echo "$RAIN_MGMT"; fi; }
if [ -n "$KILL_RANK" ] && [ "$SPARE" = 1 ]; then
  nextport "$last"; SPORT=$PORT; last=$PORT; SADDR_ENV="NCCL_GIN_RESTORE_SPARE_ADDR=$(addr_of "$KILL_RANK"):$SPORT"
fi
if [ -n "$KILL2_RANK" ] && [ "$SPARE2" = 1 ]; then
  nextport "$last"; SPORT2=$PORT; last=$PORT; SADDR2_ENV="NCCL_GIN_RESTORE_SPARE_ADDR=$(addr_of "$KILL2_RANK"):$SPORT2"
fi
PORT=$save; PORT_TRIES=$savet
ARGS="$N $RAIN_MGMT $PORT"
tag="$LIB/${CELL:-mi}#$TRIAL"
echo "[$tag] gid rain=$GID0 sunny=$GID1 port=$PORT kill=${KILL_RANK:--}($KILL_KIND ${DIE_AT:--}) kill2=${KILL2_RANK:--}(${DIE2_AT:--}) spare=$SPARE spare2=$SPARE2 mirror=$MIRROR" >&2
hca() { [ "$1" = rain ] && echo "NCCL_IB_HCA=mlx5_1 NCCL_IB_GID_INDEX=$GID0" || echo "NCCL_IB_HCA=mlx5_0 NCCL_IB_GID_INDEX=$GID1"; }
renv() { local v="R${1}_ENV"; echo "${!v:-}"; }
npath() { [ "$1" = sunny ] && echo "$RT.$2" || echo "$WORK/$2"; }
rec_env() { [ "$FAULT_POLICY" = hold ] && echo "NCCL_GIN_RESTORE_RECORD=$(npath "$(node_of "$1")" "r$1.rec")"; }
sa_env() {  # only the ranks that may be revived get their spare's address
  [ -n "$SADDR_ENV" ] && [ "$1" = "$KILL_RANK" ] && echo "$SADDR_ENV"
  [ -n "$SADDR2_ENV" ] && [ "$1" = "$KILL2_RANK" ] && echo "$SADDR2_ENV"
}
die_env() {  # the library's checkpoint-pause switch (KILL_IN_HOOK) or the driver's step kill (DIE_AT, DIE2_AT)
  [ -n "$KILL_RANK" ] && [ "$1" = "$KILL_RANK" ] && [ "$KILL_KIND" = hook ] &&
    echo "NCCL_GIN_RESTORE_TEST_DIE_IN_CKPT=$(npath "$(node_of "$1")" arm):$KILL_HOOK_US"
  [ -n "$KILL_RANK" ] && [ "$1" = "$KILL_RANK" ] && [ -n "$DIE_AT" ] && echo "GIN_RS_DIE_AT=$DIE_AT"
  [ -n "$KILL2_RANK" ] && [ "$1" = "$KILL2_RANK" ] && echo "GIN_RS_DIE_AT=$DIE2_AT"
}
WAITPY='import re,sys,time
f,rx,tmin,gmin,tmo=sys.argv[1],re.compile(sys.argv[2]),float(sys.argv[3]),int(sys.argv[4]),float(sys.argv[5])
end=time.time()+tmo
while time.time()<end:
    try:
        for l in open(f,errors="replace"):
            t,_,rest=l.partition(" ")
            m=rx.search(rest)
            if m and float(t)>=tmin and (not m.groups() or int(m.group(1))>=gmin):
                print(t, m.group(1) if m.groups() else ""); sys.exit(0)
    except (OSError,ValueError):
        pass
    time.sleep(0.002)'
# wait_line <file> <regex with one group or none> <min receipt time> <min group value> <timeout s>: "<receipt time> <group>"
# of the first stamped line that matches with time >= min and group >= min value; nothing on timeout
wait_line() { python3 -c "$WAITPY" "$@"; }
GPU_APPS="$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | grep -c .)/$(ssh -n "$SUNNY_SSH" "nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | grep -c ." 2>/dev/null)"
declare -A PID LT
T0=$(date +%s.%N)
launch() {
  local name=$1 r=$2 node=$3 e=$4
  LT[$name]=$(date +%s.%N)
  if [ "$node" = sunny ]; then
    ssh -n "$SUNNY_SSH" "cd \$HOME && umask 077 && echo \$\$ > $RT.$name.pid && $NENV $(hca sunny) $RS_ENV RS_RDV_NONCE=$NONCE $e \
stdbuf -oL -eL timeout -s KILL $((WATCHDOG_S + 20)) $RSBIN $r $ARGS $RT.$name.kv 2>&1; echo \$? > $RT.$name.rc" \
      | python3 -u -c "$STAMP" > "$WORK/$name.log" 2>&1 &
  else
    ( echo $BASHPID > "$WORK/$name.pid"
      env $NENV $(hca rain) $RS_ENV RS_RDV_NONCE=$NONCE $e \
        stdbuf -oL -eL timeout -s KILL $((WATCHDOG_S + 20)) "$RSBIN" "$r" $ARGS "$WORK/$name.kv" 2>&1
      echo $? > "$WORK/$name.rc" ) | python3 -u -c "$STAMP" > "$WORK/$name.log" 2>&1 &
  fi
  PID[$name]=$!
}
GATE=""; [ "$ANYSPARE" = 1 ] && GATE=$WORK/start_gate
gate_env() { [ -n "$GATE" ] && [ "$1" = 0 ] && echo "RS_START_GATE=$GATE"; }
for ((r = N - 1; r >= 0; r--)); do
  launch "r$r" "$r" "$(node_of "$r")" "$(renv "$r") $(rec_env "$r") $(sa_env "$r") $(die_env "$r") $(gate_env "$r")"
done
PIDREC='for i in $(seq 1 200); do p=$(cat "$1" 2>/dev/null); [ -n "$p" ] || { sleep 0.1; continue; }
for a in $(pgrep -P "$p"); do for c in $(pgrep -P "$a"); do
[ "$(cat /proc/$c/comm 2>/dev/null)" = "$3" ] && { echo "$c $a" > "$2"; exit 0; }; done; done; sleep 0.1; done; exit 1'
PYK='import os,sys; c,p,n=int(sys.argv[1]),sys.argv[2],sys.argv[5]; s=open("/proc/%d/stat"%c).read(); assert s[s.index("(")+1:s.rindex(")")]==n[:15] and s.rsplit(")",1)[1].split()[1]==p, "not the recorded process"; os.kill(c,9); print("GINRS killed rank=%s node=%s pid=%d" % (sys.argv[3],sys.argv[4],c))'
kill_spare_now() {  # SPARE_KILL_FIRST=1: the spare is SIGKILLed by its recorded PID once ready, before its rank dies
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
# start_spare <name> <rank> <port>: the spare replays <rank>'s init transcript once it is complete (after <rank>'s Resume
# line); prints the receipt time of its ready line, or 0
start_spare() {
  local name=$1 kr=$2 sport=$3 knode t
  knode=$(node_of "$kr")
  if [ -n "$(wait_line "$WORK/r$kr.log" "GINRS resume rank=$kr " 0 0 60)" ]; then
    launch "$name" "$kr" "$knode" "NCCL_GIN_RESTORE_SPARE=$kr NCCL_GIN_RESTORE_SPARE_PORT=$sport NCCL_GIN_RESTORE_SPARE_WAIT_MS=$SPARE_WAIT_MS NCCL_GIN_RESTORE_REPLAY=$(npath "$knode" "r$kr.rec")"
    echo "$name" >> "$WORK/spares_started"
  fi
}
SPARE_ON=0; SPARE2_ON=0; T_READY=0; T_READY2=0
if [ -n "$SPORT" ]; then start_spare spare "$KILL_RANK" "$SPORT"; fi
if [ -n "$SPORT2" ]; then start_spare spare_2nd "$KILL2_RANK" "$SPORT2"; fi
grep -qx spare "$WORK/spares_started" 2>/dev/null && SPARE_ON=1
grep -qx spare_2nd "$WORK/spares_started" 2>/dev/null && SPARE2_ON=1
if [ "$SPARE_ON" = 1 ]; then
  read -r T_READY _ <<< "$(wait_line "$WORK/spare.log" "GINRS spare_ready rank=$KILL_RANK " 0 0 60)"; T_READY=${T_READY:-0}
  [ "${SPARE_KILL_FIRST:-0}" = 1 ] && [ "$T_READY" != 0 ] && kill_spare_now "$(node_of "$KILL_RANK")" "$KILL_RANK"
fi
if [ "$SPARE2_ON" = 1 ]; then
  read -r T_READY2 _ <<< "$(wait_line "$WORK/spare_2nd.log" "GINRS spare_ready rank=$KILL2_RANK " 0 0 60)"; T_READY2=${T_READY2:-0}
fi
[ -n "$GATE" ] && touch "$GATE"   # open the start gate: every wanted spare is ready, or its waits ran out
T_GATE=$(awk -v a="$T_READY" -v b="$T_READY2" 'BEGIN{printf "%.6f", (a > b ? a : b)}')
ARM_WAIT=-; T_ARMED=0
if [ "$KILL_KIND" = hook ]; then  # gin-restore's checkpoint-pause kill (run_rs.sh): arm once every survivor saw KR armed
  ARM_WAIT=ok; aend=$(awk -v n="$(date +%s.%N)" -v s="$ARM_WAIT_S" 'BEGIN{printf "%.3f", n + s}')
  for ((s = 0; s < N; s++)); do
    [ "$s" = "$KILL_RANK" ] && continue
    left=$(awk -v n="$(date +%s.%N)" -v e="$aend" 'BEGIN{x = e - n; printf "%.3f", (x > 0 ? x : 0)}')
    read -r t _ <<< "$(wait_line "$WORK/r$s.log" "GIN/RS: rank $s: rank $KILL_RANK armed at its stable checkpoint [0-9]+" 0 0 "$left")"
    if [ -z "${t:-}" ]; then ARM_WAIT=timeout; break; fi
    T_ARMED=$(awk -v a="$T_ARMED" -v b="$t" 'BEGIN{printf "%.6f", (b > a ? b : a)}')
  done
  if [ "$ARM_WAIT" = ok ]; then
    if [ "$(node_of "$KILL_RANK")" = sunny ]; then ssh -n "$SUNNY_SSH" "touch $RT.arm"; else touch "$WORK/arm"; fi
  fi
fi
KILLER=""; RECORDER=""; KILL_STABLE_K=-
if [ "$KILL_KIND" = traffic ] || [ "$KILL_KIND" = after_stable ]; then
  KR=$KILL_RANK; knode=$(node_of "$KR")
  if [ "$knode" = sunny ]; then
    ssh -n "$SUNNY_SSH" "bash -c '$PIDREC' _ $RT.r$KR.pid $RT.r$KR.cpid $BINNAME" &
  else
    bash -c "$PIDREC" _ "$WORK/r$KR.pid" "$WORK/kill_target.pid" "$BINNAME" &
  fi
  RECORDER=$!
  # the step to wait for: KILL_AT_STEP (traffic), or K + KILL_AFTER_STABLE with K the first checkpoint of KR stable at its
  # buddy after the spare was ready (after_stable; the step is written to $WORK/kill_stable_k for the meta)
  ( at=$KILL_AT_STEP
    if [ "$KILL_KIND" = after_stable ]; then
      read -r _ k <<< "$(wait_line "$WORK/r$KR.log" "GIN/RS: rank $KR: checkpoint ([0-9]+) stable at buddy" "$T_READY" 0 \
        "$(awk -v d="$KILL_DELAY_MS" 'BEGIN{printf "%.3f", d / 1000}')")"
      if [ -n "${k:-}" ]; then at=$((k + KILL_AFTER_STABLE)); echo "$k" > "$WORK/kill_stable_k"; fi
    fi
    wait_line "$WORK/r$KR.log" "GINRS step rank=$KR step=([0-9]+) released=0" "$T_READY" "$at" \
      "$(awk -v d="$KILL_DELAY_MS" 'BEGIN{printf "%.3f", d / 1000}')" > /dev/null
    sleep "$(awk -v u="$KILL_DELAY_US" 'BEGIN{printf "%.6f", u / 1e6}')"
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
[ "$SPARE2_ON" = 1 ] && wait "${PID[spare_2nd]}" 2>/dev/null
T1=$(date +%s.%N)
[ -n "$KILLER" ] && wait "$KILLER" "$RECORDER" 2>/dev/null
[ -s "$WORK/kill_stable_k" ] && KILL_STABLE_K=$(cat "$WORK/kill_stable_k")
LIB_MD5=$(md5sum < "$LIBDIR/libnccl.so.2" 2>/dev/null | cut -c1-32); LIB_MD5=${LIB_MD5:-none}
DRIVER_MD5=$(md5sum < "$RSBIN" 2>/dev/null | cut -c1-32); DRIVER_MD5=${DRIVER_MD5:-none}
names="r0 r1 r2 r3"; [ "$SPARE_ON" = 1 ] && names="$names spare"; [ "$SPARE2_ON" = 1 ] && names="$names spare_2nd"
for name in $names; do
  if [ -f "$WORK/$name.kv" ]; then continue; fi
  scp -q "$SUNNY_SSH:$RT.$name.kv" "$WORK/$name.kv" 2>/dev/null || true
  scp -q "$SUNNY_SSH:$RT.$name.rc" "$WORK/$name.rc" 2>/dev/null || true
done
ssh -n "$SUNNY_SSH" "rm -f $RT.*" 2>/dev/null || true
LEFT=$( { pgrep -x "$BINNAME"; ssh -n "$SUNNY_SSH" "pgrep -x $BINNAME"; } 2>/dev/null | wc -l)
mkdir -p "$LOGDIR"
stem="${CELL:-mi}_${LIB}_${TRIAL}"
MASK='s/[0-9]\{1,3\}\.[0-9]\{1,3\}\.[0-9]\{1,3\}\.[0-9]\{1,3\}/<ip>/g'
rm -f "$LOGDIR/${stem}"_*
for name in $names; do
  [ -f "$WORK/$name.kv" ] && sed "$MASK" "$WORK/$name.kv" > "$LOGDIR/${stem}_$name.kv"
  [ -f "$WORK/$name.log" ] && sed "$MASK" "$WORK/$name.log" > "$LOGDIR/${stem}_$name.log"
done
[ -f "$WORK/kill.out" ] && sed "$MASK" "$WORK/kill.out" > "$LOGDIR/${stem}_kill.out"
[ -f "$WORK/spare_kill.out" ] && sed "$MASK" "$WORK/spare_kill.out" > "$LOGDIR/${stem}_spare_kill.out"
rcs=""; for name in $names; do rcs="$rcs ${name}rc=$(tr -d '\n' < "$WORK/$name.rc" 2>/dev/null || echo none)"; done
echo "cell=${CELL:-} lib=$LIB n=$N steps=$STEPS bytes=$BYTES policy=$FAULT_POLICY restore=$RESTORE sym_gin=$SYM_GIN \
gin_type=$GIN_TYPE num_rma_ctx=$NUM_RMA_CTX nconn=$NCONN qpwatch_ms=$QPWATCH restore_ms=$RESTORE_MS checksum=$CHECKSUM \
log_measure=$LOG_MEASURE step_gap_us=$STEP_GAP_US mirror=$MIRROR mirror_slots=${MIRROR_SLOTS:-} mirror_lane=${MIRROR_LANE:-} \
mirror_pull=${MIRROR_PULL:-} pool_max_mb=${POOL_MAX_MB:-} fetch_mb=${FETCH_MB:-} store_write_ms=${STORE_WRITE_MS:-} \
overwrite=$OVERWRITE train=$TRAIN ring=$RING ckpt_steps=${CKPT_STEPS:-} kill_rank=${KILL_RANK:-} kill_kind=$KILL_KIND \
kill_at_step=$KILL_AT_STEP kill_delay_us=$KILL_DELAY_US kill_fallback_ms=$KILL_DELAY_MS kill_in_hook=$KILL_IN_HOOK \
kill_hook_us=$KILL_HOOK_US kill_after_stable=${KILL_AFTER_STABLE:-} kill_stable_k=$KILL_STABLE_K die_seed=${DIE_SEED:-} \
die_at=${DIE_AT:--} kill2_rank=${KILL2_RANK:-} die2_at=${DIE2_AT:--} die_us_max=$DIE_US_MAX \
die_switch=$([ "$KILL_KIND" = hook ] && echo NCCL_GIN_RESTORE_TEST_DIE_IN_CKPT || echo -) arm_wait=$ARM_WAIT arm_wait_s=$ARM_WAIT_S armed_rt=$T_ARMED \
spare_wait_ms=$SPARE_WAIT_MS spare=$SPARE_ON spare_wanted=$SPARE spare_kill_first=${SPARE_KILL_FIRST:-0} \
spare_ready=$([ "$T_READY" != 0 ] && echo 1 || echo 0) spare2=$SPARE2_ON spare2_wanted=$SPARE2 \
spare2_ready=$([ "$T_READY2" != 0 ] && echo 1 || echo 0) gate_rt=$T_GATE gpu_apps_before=$GPU_APPS end_grace_ms=$END_GRACE_MS \
spare_addr_set=$([ -n "$SADDR_ENV" ] && echo 1 || echo 0) spare2_addr_set=$([ -n "$SADDR2_ENV" ] && echo 1 || echo 0) \
mem_avail_rain=$AVAIL_RAIN mem_avail_sunny=$AVAIL_SUNNY mem_need_rain=$NEED_RAIN mem_need_sunny=$NEED_SUNNY \
pin_mb_per_proc=$PIN_PER trial=$TRIAL extra=$(echo ${EXTRA_ENV:-} | tr ' ' '+') \
r0_env=$(echo ${R0_ENV:-} | tr ' ' '+') r1_env=$(echo ${R1_ENV:-} | tr ' ' '+') r2_env=$(echo ${R2_ENV:-} | tr ' ' '+') \
r3_env=$(echo ${R3_ENV:-} | tr ' ' '+')$rcs left=$LEFT gid0=$GID0 gid1=$GID1 port=$PORT \
port_tries=$PORT_TRIES rdv_nonce_set=1 runner=mir driver=$DRIVER continue_after_refusal=${CONTINUE_AFTER_REFUSAL:-0} \
wall_s=$(awk -v a="$T0" -v b="$T1" 'BEGIN{printf "%.1f", b - a}') watchdog_s=$WATCHDOG_S \
bin=$BINNAME rs_set=$RS_SET lib_md5=$LIB_MD5 driver_md5=$DRIVER_MD5" > "$LOGDIR/${stem}_meta.txt"
echo "[$tag]$rcs left=$LEFT wall=$(awk -v a="$T0" -v b="$T1" 'BEGIN{printf "%.1f", b - a}')s :: $(grep -ho 'xchg=[a-z]*' "$WORK"/*.kv 2>/dev/null | tr '\n' ' ')" >&2
exit 0
