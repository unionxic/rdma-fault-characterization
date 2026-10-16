#!/usr/bin/env bash
# run_gc.sh - gin-control, test side: one trial of ../../EXPERIMENT.md 7 / 9.8 / 9.9. gin-mirror's runner
# (../../../mirror/impl/test/run_mi.sh) with its layout, receipt clock, recorded-PID kill, spares, start gate, IPv4 masking
# and memory check, and these additions:
#   - builds gc | gct | gctc | gcp | gctp (~/rs-bundle/<RS_SET>/lib/<build>), driver ~/rs-bundle/<RS_SET>/gctest/<DRIVER>
#     (gin_mi built against the gc tree's headers; deploy_gc.sh);
#   - launchers (rdma builds gc, gcp only): LAUNCHER_SCOPE=hold reads hold_gc.sh's records (LAUNCHER_REC_RAIN,
#     LAUNCHER_REC_SUNNY; EXPERIMENT 5: one launcher per node per hold), LAUNCHER_SCOPE=trial starts one per node for this
#     trial (launcher_gc.sh, per-trial socket path) and stops it last. Either way every rank and spare gets
#     NCCL_GIN_CTRL_LAUNCHER_SOCK and NCCL_GIN_CTRL_LAUNCHER_NODE of its node, the runner checks before the ranks start that
#     both launchers are alive and printed their "listening" line (section 8's start check), records each launcher's pid and
#     start time before and after the trial, and copies the launcher log lines of the trial window into the trial folder;
#   - the injections of section 9.9 (every one by a PID this runner recorded, on the process's own node, by one python
#     process that verifies comm, parent and start before it signals, and prints its own CLOCK_MONOTONIC as mono_ms):
#       KILL_KIND traffic        SIGKILL of KILL_RANK at its step line >= KILL_AT_STEP (+ KILL_DELAY_US)  (run_mi.sh's)
#       KILL_KIND self           no runner kill: the library's test switch (NCCL_GIN_TS_TEST_DIE_RST) kills the rank
#       KILL_KIND spare_then_rank once every survivor logged "rank KILL_RANK armed at its stable checkpoint K" after the spare
#                                was ready, SIGKILL of the spare, SPARE_GAP_MS (5) later SIGKILL of KILL_RANK
#       FDHOLD=1                 before the traffic kill, wait for KILL_RANK's fork line of NCCL_GIN_TS_TEST_FD_HOLDER (the
#                                child gin_fdhold's pid); at the end SIGKILL of that child by that pid (comm gin_fdhold,
#                                this uid, started after the trial's start)
#       STOP_RANK, STOP_MS       SIGSTOP of STOP_RANK at its step line >= KILL_AT_STEP, SIGCONT STOP_MS later (the line
#                                says whether the PID was still there and the stopped time on the node's clock)
#       DUTY_RANK, DUTY_ON_MS, DUTY_OFF_MS, DUTY_S   SIGSTOP/SIGCONT cycles from the same trigger for DUTY_S seconds
#       KILL2_RANK + KILL2_KIND=pid_after_armed     the second kill by recorded PID, only after every survivor of the
#                                second death logged "rank KILL2_RANK armed at its stable checkpoint K" after the first
#                                restore (KILL2_RANK may equal KILL_RANK: then the target is the revived spare's PID)
#     and, at the end, any recorded rank or spare PID still in state T gets SIGCONT then SIGKILL (left_stopped in meta);
#   - per trial: active_mtu of both GIN ports (ibv_devinfo, read only), the RNR port counter rnr_nak_retry_err before and
#     after (sysfs, read only), the launchers' --tc, and the trial's control variables (WITNESS, FENCE, RST_GAP_MS,
#     CONFIRM_MS, PROBE_MS) in meta;
#   - shutdown order: the ranks and spares end by themselves (the library's BYE at the communicator's destroy, then exit),
#     the runner waits for every one of them, and only then (LAUNCHER_SCOPE=trial) stops the launchers.
# Nothing is killed by name. sunny's management address comes from SUNNY_SSH only and rain's is looked up at run time; neither
# is written to a file (copied logs are IPv4-masked). Every NCCL_ and GIN_ variable of the caller is dropped first. No link,
# address, driver or firewall is touched. Run only by the main session, inside ../../../../common/cluster_run.sh through
# hold_gc.sh.
#
# usage: run_gc.sh <trial-tag> <logdir>
# env (beyond run_mi.sh's, which keep their meaning and defaults): LIB (gc), DRIVER (gin_mi), WITNESS (empty: library
#   default 1), FENCE (empty: library default lineage), RST_GAP_MS (gctc only), CONFIRM_MS, PROBE_MS, SPARE_RANK (default
#   KILL_RANK: the rank whose spare runs), SPARE_ENV (the spare's test switches), KILL_KIND, SPARE_GAP_MS (5), FDHOLD,
#   STOP_RANK, STOP_MS, DUTY_RANK, DUTY_ON_MS (50), DUTY_OFF_MS (50), DUTY_S (20), KILL2_KIND, LAUNCHER_SCOPE (hold when
#   LAUNCHER_REC_RAIN is set, else trial), LA_TC (0), HOLD_TAG (hold_gc.sh). RS_DRY_CONFIG=1 prints the configuration line
#   and exits before any file, address, ssh or process is touched (CPU self-test).
# files in <logdir>: run_mi.sh's, plus <stem>_inject.out, <stem>_launcher_<node>.log, <stem>_fdhold.out (stem =
#   <cell>_<lib>_<tag>).
set -u
TRIAL=${1:?trial tag}; LOGDIR=${2:?logdir}
for v in $(env | sed -n 's/^\(\(NCCL\|GIN\)_[A-Za-z0-9_]*\)=.*/\1/p'); do unset "$v"; done
N=${N:-4}
[ "$N" = 4 ] || { echo "run_gc.sh is the 4-rank workload (N=4)" >&2; exit 1; }
LIB=${LIB:-gc}
RS_SET=${RS_SET:-}
D=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=../../../mirror/impl/test/rs_set_mi.sh
. "$D/../../../mirror/impl/test/rs_set_mi.sh"
rs_set_check || exit 1
RSB=$HOME/rs-bundle/$RS_SET
case "$LIB" in gc|gcp) CTRL=rdma ;; gct|gctc|gctp) CTRL=tcp ;; *) echo "unknown LIB $LIB (gc | gct | gctc | gcp | gctp)" >&2; exit 1 ;; esac
LIBDIR=$RSB/lib/$LIB
DRIVER=${DRIVER:-gin_mi}
case "$DRIVER" in gin_mi|gin_mi_nomacro) ;; *) echo "driver $DRIVER is not a gin-control driver" >&2; exit 1 ;; esac
RSBIN=$RSB/gctest/$DRIVER
BINNAME=$(basename "$RSBIN")
TRAIN=${TRAIN:-0}; OVERWRITE=${OVERWRITE:-0}; RING=${RING:-4}
if [ "$TRAIN" = 1 ]; then STEPS=${STEPS:-2000}; BYTES=${BYTES:-2097152}; else STEPS=${STEPS:-600}; BYTES=${BYTES:-4096}; fi
STEP_GAP_US=${STEP_GAP_US:-5000}
KILL_AT_STEP=${KILL_AT_STEP:-100}; KILL_DELAY_US=${KILL_DELAY_US:-500}
FAULT_POLICY=${FAULT_POLICY:-hold}; RESTORE=${RESTORE:-1}; SYM_GIN=${SYM_GIN:-0}; GIN_TYPE=${CELL_GIN_TYPE:-3}
RMA_DISABLE=${RMA_DISABLE:-1}; NUM_RMA_CTX=${NUM_RMA_CTX:-0}; NCONN=${NCONN:-1}; QPWATCH=${QPWATCH:-10}
RESTORE_MS=${RESTORE_MS:-20000}; RESUME_MS=${RESUME_MS:-30000}; LOG_MEASURE=${LOG_MEASURE:-0}; CHECKSUM=${CHECKSUM:-off}
MIRROR=${MIRROR:-1}
KILL_RANK=${KILL_RANK:-}; KILL_DELAY_MS=${KILL_DELAY_MS:-30000}
ARM_WAIT_S=${ARM_WAIT_S:-60}
SPARE=${SPARE:-0}; SPARE_WAIT_MS=${SPARE_WAIT_MS:-60000}; SPARE_RANK=${SPARE_RANK:-$KILL_RANK}
KILL2_RANK=${KILL2_RANK:-}; SPARE2=${SPARE2:-0}; KILL2_KIND=${KILL2_KIND:-}
DIE_SEED=${DIE_SEED:-}; DIE_US_MAX=${DIE_US_MAX:-4000}
STOP_RANK=${STOP_RANK:-}; STOP_MS=${STOP_MS:-}
DUTY_RANK=${DUTY_RANK:-}; DUTY_ON_MS=${DUTY_ON_MS:-50}; DUTY_OFF_MS=${DUTY_OFF_MS:-50}; DUTY_S=${DUTY_S:-20}
FDHOLD=${FDHOLD:-0}; SPARE_GAP_MS=${SPARE_GAP_MS:-5}
WITNESS=${WITNESS:-}; FENCE=${FENCE:-}; RST_GAP_MS=${RST_GAP_MS:-}; CONFIRM_MS=${CONFIRM_MS:-}; PROBE_MS=${PROBE_MS:-}
[ -n "$RST_GAP_MS" ] && [ "$LIB" != gctc ] && { echo "RST_GAP_MS is the tcp control build's parameter (LIB gctc)" >&2; exit 1; }
if [ "$CTRL" = rdma ]; then LAUNCHER_SCOPE=${LAUNCHER_SCOPE:-$([ -n "${LAUNCHER_REC_RAIN:-}" ] && echo hold || echo trial)}; else LAUNCHER_SCOPE=none; fi
case "$LAUNCHER_SCOPE" in hold|trial|none) ;; *) echo "LAUNCHER_SCOPE is hold or trial" >&2; exit 1 ;; esac
# the second death: run_mi.sh's driver step kill (DIE2_LO..DIE2_HI from DIE_SEED), or the recorded-PID kill after armed
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
if [ -n "$KILL2_RANK" ] && [ "$KILL2_KIND" != pid_after_armed ]; then
  [ -n "$DIE_SEED" ] && [ -n "${DIE2_LO:-}" ] || { echo "KILL2_RANK needs DIE_SEED and DIE2_LO (or KILL2_KIND=pid_after_armed)" >&2; exit 1; }
  [ "$KILL2_RANK" != "$KILL_RANK" ] || { echo "a driver step kill of the same rank twice is not run here (KILL2_KIND=pid_after_armed)" >&2; exit 1; }
  read -r ds du <<< "$(draw "$DIE2_LO" "${DIE2_HI:-$DIE2_LO}" second)"; DIE2_AT="$ds:$du"
fi
[ "$KILL2_KIND" = pid_after_armed ] && [ -z "$KILL2_RANK" ] && { echo "KILL2_KIND without KILL2_RANK" >&2; exit 1; }
KILL_IN_HOOK=${KILL_IN_HOOK:-0}; KILL_HOOK_US=${KILL_HOOK_US:-300}; KILL_AFTER_STABLE=${KILL_AFTER_STABLE:-}
if [ -n "${KILL_KIND:-}" ]; then :
elif [ -n "$DIE_AT" ]; then KILL_KIND=driver
elif [ "$KILL_IN_HOOK" = 1 ]; then KILL_KIND=hook
elif [ -n "$KILL_AFTER_STABLE" ]; then KILL_KIND=after_stable
elif [ -n "$KILL_RANK" ]; then KILL_KIND=traffic
else KILL_KIND=-; fi
case "$KILL_KIND" in driver|traffic|hook|after_stable|self|spare_then_rank|-) ;; *) echo "unknown KILL_KIND $KILL_KIND" >&2; exit 1 ;; esac
[ "$KILL_KIND" = spare_then_rank ] && [ "$SPARE" != 1 ] && { echo "spare_then_rank needs SPARE=1" >&2; exit 1; }
[ "$FDHOLD" = 1 ] && [ "$KILL_KIND" != traffic ] && { echo "FDHOLD=1 goes with the traffic kill" >&2; exit 1; }
SUBJECT=${KILL_RANK:-${STOP_RANK:-${DUTY_RANK:-}}}
INJECT=none
[ -n "$KILL_RANK" ] && INJECT=kill_$KILL_KIND
[ "$FDHOLD" = 1 ] && INJECT=fd_holder_kill
[ -n "$STOP_RANK" ] && INJECT=sigstop
[ -n "$DUTY_RANK" ] && INJECT=duty
# the pinned host memory per node (run_mi.sh's estimate)
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
need_mb() {
  local nd=$1 n=2 sp=0
  [ "$SPARE" = 1 ] && [ -n "$SPARE_RANK" ] && [ "$(node_of "$SPARE_RANK")" = "$nd" ] && sp=$((sp + 1))
  [ "$SPARE2" = 1 ] && [ -n "$KILL2_RANK" ] && [ "$(node_of "$KILL2_RANK")" = "$nd" ] && sp=$((sp + 1))
  echo $(( (n + sp) * PIN_PER + sp * FETCH_PIN + 1024 ))
}
NEED_RAIN=$(need_mb rain); NEED_SUNNY=$(need_mb sunny)
CFGLINE="cell=${CELL:-} lib=$LIB ctrl=$CTRL driver=$DRIVER policy=$FAULT_POLICY restore=$RESTORE witness=${WITNESS:-default} \
fence=${FENCE:-default} rst_gap_ms=${RST_GAP_MS:-} confirm_ms=${CONFIRM_MS:-} probe_ms=${PROBE_MS:-} launcher_scope=$LAUNCHER_SCOPE \
kill_rank=$KILL_RANK kill_kind=$KILL_KIND spare_wanted=$SPARE spare_rank=$SPARE_RANK spare_gap_ms=$SPARE_GAP_MS fdhold=$FDHOLD \
stop_rank=$STOP_RANK stop_ms=$STOP_MS duty_rank=$DUTY_RANK duty_on_ms=$DUTY_ON_MS duty_off_ms=$DUTY_OFF_MS duty_s=$DUTY_S \
kill2_rank=$KILL2_RANK kill2_kind=${KILL2_KIND:--} die_at=${DIE_AT:--} die2_at=${DIE2_AT:--} subject_rank=$SUBJECT inject=$INJECT \
r0_env=$(echo ${R0_ENV:-} | tr ' ' '+') r1_env=$(echo ${R1_ENV:-} | tr ' ' '+') r2_env=$(echo ${R2_ENV:-} | tr ' ' '+') \
r3_env=$(echo ${R3_ENV:-} | tr ' ' '+') spare_env=$(echo ${SPARE_ENV:-} | tr ' ' '+') overwrite=$OVERWRITE train=$TRAIN \
steps=$STEPS bytes=$BYTES mirror=$MIRROR need_mb_rain=$NEED_RAIN need_mb_sunny=$NEED_SUNNY rs_set=$RS_SET"
if [ "${RS_DRY_CONFIG:-0}" = 1 ]; then echo "$CFGLINE"; exit 0; fi
SUNNY_SSH=${SUNNY_SSH:?set SUNNY_SSH}
SUNNY_HOST=${SUNNY_SSH#*@}
[ -x "$RSBIN" ] && [ -f "$LIBDIR/libnccl.so.2" ] || { echo "missing $RSBIN or $LIBDIR/libnccl.so.2 on rain" >&2; exit 1; }
AVAIL_RAIN=$(awk '/^MemAvailable:/{print int($2/1024)}' /proc/meminfo)
AVAIL_SUNNY=$(ssh -n "$SUNNY_SSH" "awk '/^MemAvailable:/{print int(\$2/1024)}' /proc/meminfo" 2>/dev/null)
if [ -z "$AVAIL_RAIN" ] || [ -z "$AVAIL_SUNNY" ] || [ "$AVAIL_RAIN" -lt "$NEED_RAIN" ] || [ "$AVAIL_SUNNY" -lt "$NEED_SUNNY" ]; then
  echo "host memory short for ${CELL:-}#$TRIAL: rain ${AVAIL_RAIN:-?}/$NEED_RAIN MiB, sunny ${AVAIL_SUNNY:-?}/$NEED_SUNNY MiB (available/needed)" >&2
  exit 5
fi
RAIN_MGMT=$(ip -4 route get "$SUNNY_HOST" 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p' | head -1)
[ -n "$RAIN_MGMT" ] || { echo "cannot find rain's management address" >&2; exit 1; }
umask 077
WORK=$(mktemp -d /tmp/gc_rt.XXXXXX)
RT=/tmp/gc_rt_$$_$RANDOM      # sunny-side file prefix of this trial
# shellcheck source=../../../remaining/portpick.sh
. "$D/../../../remaining/portpick.sh"
LA_TAG=t$$_$RANDOM
cleanup() {
  if [ "$LAUNCHER_SCOPE" = trial ]; then
    for nd in rain sunny; do bash "$D/launcher_gc.sh" stop "$nd" "$WORK/la" "$LA_TAG" > /dev/null 2>&1; done
  fi
  ssh -n "$SUNNY_SSH" "rm -f $RT.*" 2>/dev/null || true; rm -rf "$WORK"
}
trap cleanup EXIT
GID_PROBE='d=/sys/class/infiniband/$1/ports/1
for g in $(ls "$d/gids" | sort -n); do
  [ "$(cat "$d/gid_attrs/types/$g" 2>/dev/null)" = "RoCE v2" ] || continue
  case "$(cat "$d/gids/$g")" in 0000:0000:0000:0000:0000:ffff:1e00:00*) echo "$g"; exit 0;; esac
done; exit 1'
GID0=$(bash -c "$GID_PROBE" _ mlx5_1) || { echo "no GID on rain" >&2; exit 1; }
GID1=$(ssh -n "$SUNNY_SSH" bash -c "'$GID_PROBE'" _ mlx5_0) || { echo "no GID on sunny" >&2; exit 1; }
# read only: the GIN ports' active MTU (ibv_devinfo queries the port; no QP, no traffic) and the RNR port counter
MTU_Q='ibv_devinfo -d $1 -i 1 2>/dev/null | awk '"'"'/active_mtu/{print $2; exit}'"'"''
RNR_Q='cat /sys/class/infiniband/$1/ports/1/hw_counters/rnr_nak_retry_err 2>/dev/null || echo -'
MTU_RAIN=$(bash -c "$MTU_Q" _ mlx5_1); MTU_SUNNY=$(ssh -n "$SUNNY_SSH" bash -c "'$MTU_Q'" _ mlx5_0)
RNR0_RAIN=$(bash -c "$RNR_Q" _ mlx5_1); RNR0_SUNNY=$(ssh -n "$SUNNY_SSH" bash -c "'$RNR_Q'" _ mlx5_0)
STAMP='import sys,time
for l in sys.stdin.buffer:
    sys.stdout.write("%.6f %s\n" % (time.clock_gettime(time.CLOCK_MONOTONIC), l.decode("utf-8","replace").rstrip("\n")))
    sys.stdout.flush()'
# ---- the launchers (rdma builds): hold scope reads hold_gc.sh's records, trial scope starts its own
LA_OK=1; LA_TC=${LA_TC:-0}
declare -A LAREC LASOCK LANODE LAOFF
LANODE[rain]=0; LANODE[sunny]=1
if [ "$LAUNCHER_SCOPE" = trial ]; then
  for nd in rain sunny; do
    LA_TC=$LA_TC bash "$D/launcher_gc.sh" start "$nd" "$WORK/la" "$LA_TAG" ${LAUNCHER_ENV:-} >&2 || LA_OK=0
    LAREC[$nd]=$WORK/la/la_${LA_TAG}_$nd.rec
  done
elif [ "$LAUNCHER_SCOPE" = hold ]; then
  LAREC[rain]=${LAUNCHER_REC_RAIN:-}; LAREC[sunny]=${LAUNCHER_REC_SUNNY:-}
fi
la_val() { sed -n "s/.*\b$2=\([^ ]*\).*/\1/p" "${LAREC[$1]}" 2>/dev/null | head -1; }
la_info() { local rec=${LAREC[$1]} dir tag; dir=$(dirname "$rec"); tag=$(basename "$rec" .rec); tag=${tag#la_}; tag=${tag%_$1}
  bash "$D/launcher_gc.sh" info "$1" "$dir" "$tag"; }
LAB_RAIN=-; LAB_SUNNY=-; LAA_RAIN=-; LAA_SUNNY=-
if [ "$LAUNCHER_SCOPE" != none ]; then
  for nd in rain sunny; do
    [ -f "${LAREC[$nd]:-}" ] || { LA_OK=0; continue; }
    LASOCK[$nd]=$(la_val "$nd" sock)
    info=$(la_info "$nd")
    [ "$nd" = rain ] && LAB_RAIN=$info || LAB_SUNNY=$info
    case "$info" in *"alive=1 ready=1"*) ;; *) LA_OK=0 ;; esac
    LAOFF[$nd]=$(echo "$info" | sed -n 's/.*log_bytes=\([0-9]*\).*/\1/p')
  done
  if [ "$LA_OK" != 1 ]; then  # section 8: the launcher not ready on both nodes at the trial's start -> nothing runs
    mkdir -p "$LOGDIR"
    echo "cell=${CELL:-} lib=$LIB trial=$TRIAL launcher_ready=0 launcher_before_rain=$(echo "$LAB_RAIN" | tr ' ' ',') launcher_before_sunny=$(echo "$LAB_SUNNY" | tr ' ' ',') runner=gcr" \
      > "$LOGDIR/${CELL:-gc}_${LIB}_${TRIAL}_meta.txt"
    echo "[${CELL:-gc}#$TRIAL] the launchers are not ready on both nodes: no rank started" >&2
    exit 6
  fi
fi
la_env() {  # the rank's or spare's launcher variables (its node's socket and node number)
  [ "$LAUNCHER_SCOPE" = none ] && return
  echo "NCCL_GIN_CTRL_LAUNCHER_SOCK=${LASOCK[$1]} NCCL_GIN_CTRL_LAUNCHER_NODE=${LANODE[$1]}"
}
MIENV="NCCL_GIN_RESTORE_MIRROR=$MIRROR ${MIRROR_SLOTS:+NCCL_GIN_RESTORE_MIRROR_SLOTS=$MIRROR_SLOTS} \
${MIRROR_LANE:+NCCL_GIN_RESTORE_MIRROR_LANE=$MIRROR_LANE} ${MIRROR_PULL:+NCCL_GIN_RESTORE_MIRROR_PULL=$MIRROR_PULL} \
${POOL_MAX_MB:+NCCL_GIN_RESTORE_MIRROR_POOL_MAX_MB=$POOL_MAX_MB} ${FETCH_MB:+NCCL_GIN_RESTORE_MIRROR_FETCH_MB=$FETCH_MB} \
${STORE_WRITE_MS:+NCCL_GIN_RESTORE_STORE_WRITE_MS=$STORE_WRITE_MS}"
GCENV="${WITNESS:+NCCL_GIN_CTRL_WITNESS=$WITNESS} ${FENCE:+NCCL_GIN_RESTORE_FENCE=$FENCE} \
${RST_GAP_MS:+NCCL_GIN_TS_RST_REFUSAL_GAP_MS=$RST_GAP_MS} ${CONFIRM_MS:+NCCL_GIN_CTRL_CONFIRM_MS=$CONFIRM_MS} \
${PROBE_MS:+NCCL_GIN_TS_PROBE_MS=$PROBE_MS}"
NENV="NCCL_DEBUG=WARN NCCL_DEBUG_SUBSYS=INIT,NET NCCL_SOCKET_IFNAME=eno1 NCCL_GIN_TYPE=$GIN_TYPE NCCL_GIN_ENABLE=1 \
NCCL_IB_TIMEOUT=14 NCCL_GIN_FAULT_CLASSIFY=1 NCCL_GIN_FAULT_RECOVERY=1 NCCL_GIN_FAULT_TRANSPARENT=1 \
NCCL_MULTI_RANK_GPU_ENABLE=1 NCCL_GIN_TS_QPWATCH_MS=$QPWATCH NCCL_GIN_FAULT_POLICY=$FAULT_POLICY NCCL_GIN_RESTORE=$RESTORE \
NCCL_SYM_GIN_KERNELS_ENABLE=$SYM_GIN NCCL_RMA_DISABLE=$RMA_DISABLE NCCL_NUM_RMA_CTX=$NUM_RMA_CTX NCCL_GIN_NCONNECTIONS=$NCONN \
NCCL_GIN_RESTORE_MS=$RESTORE_MS NCCL_GIN_RESTORE_RESUME_MS=$RESUME_MS NCCL_GIN_RESTORE_CHECKSUM=$CHECKSUM \
NCCL_GIN_RESTORE_LOG_MEASURE=$LOG_MEASURE ${CKPT_STEPS:+NCCL_GIN_RESTORE_CKPT_STEPS=$CKPT_STEPS} $MIENV $GCENV \
NCCL_GIN_Q4_QPWATCH_MS=0 NCCL_RAS_ENABLE=0 LD_LIBRARY_PATH=$LIBDIR ${EXTRA_ENV:-}"
ANYSPARE=0; { [ -n "$SPARE_RANK" ] && [ "$SPARE" = 1 ]; } && ANYSPARE=1; { [ -n "$KILL2_RANK" ] && [ "$SPARE2" = 1 ]; } && ANYSPARE=1
WATCHDOG_S=${WATCHDOG_S:-$([ "$ANYSPARE" = 1 ] && echo 200 || echo 90)}
END_GRACE_MS=${END_GRACE_MS:-$( [ "$ANYSPARE" = 1 ] && echo 3000 || echo 0 )}
RS_ENV="RS_STEPS=$STEPS RS_BYTES=$BYTES RS_WATCHDOG_S=$WATCHDOG_S RS_STEP_GAP_US=$STEP_GAP_US RS_END_GRACE_MS=$END_GRACE_MS \
RS_CONTINUE_AFTER_REFUSAL=${CONTINUE_AFTER_REFUSAL:-0} RS_OVERWRITE=$OVERWRITE RS_TRAIN=$TRAIN RS_RING=$RING"
NONCE=$(new_nonce)
pick_port
nextport() { pick_port $(( $1 + 1 > PORT_HI ? PORT_LO : $1 + 1 )); }
SPORT=""; SADDR_ENV=""; SPORT2=""; SADDR2_ENV=""
save=$PORT; savet=$PORT_TRIES; last=$PORT
addr_of() { if [ "$(node_of "$1")" = sunny ]; then echo "$SUNNY_HOST"; else echo "$RAIN_MGMT"; fi; }
if [ -n "$SPARE_RANK" ] && [ "$SPARE" = 1 ]; then
  nextport "$last"; SPORT=$PORT; last=$PORT; SADDR_ENV="NCCL_GIN_RESTORE_SPARE_ADDR=$(addr_of "$SPARE_RANK"):$SPORT"
fi
if [ -n "$KILL2_RANK" ] && [ "$SPARE2" = 1 ]; then
  nextport "$last"; SPORT2=$PORT; last=$PORT; SADDR2_ENV="NCCL_GIN_RESTORE_SPARE_ADDR=$(addr_of "$KILL2_RANK"):$SPORT2"
fi
PORT=$save; PORT_TRIES=$savet
ARGS="$N $RAIN_MGMT $PORT"
tag="$LIB/${CELL:-gc}#$TRIAL"
echo "[$tag] gid rain=$GID0 sunny=$GID1 port=$PORT inject=$INJECT subject=${SUBJECT:--} spare=$SPARE launchers=$LAUNCHER_SCOPE mtu=$MTU_RAIN/$MTU_SUNNY" >&2
hca() { [ "$1" = rain ] && echo "NCCL_IB_HCA=mlx5_1 NCCL_IB_GID_INDEX=$GID0" || echo "NCCL_IB_HCA=mlx5_0 NCCL_IB_GID_INDEX=$GID1"; }
renv() { local v="R${1}_ENV"; echo "${!v:-}"; }
npath() { [ "$1" = sunny ] && echo "$RT.$2" || echo "$WORK/$2"; }
rec_env() { [ "$FAULT_POLICY" = hold ] && echo "NCCL_GIN_RESTORE_RECORD=$(npath "$(node_of "$1")" "r$1.rec")"; }
sa_env() {
  [ -n "$SADDR_ENV" ] && [ "$1" = "$SPARE_RANK" ] && echo "$SADDR_ENV"
  [ -n "$SADDR2_ENV" ] && [ "$1" = "$KILL2_RANK" ] && [ "$KILL2_RANK" != "$SPARE_RANK" ] && echo "$SADDR2_ENV"
}
die_env() {  # run_mi.sh's: the library's checkpoint-pause switch (hook) or the driver's step kill
  [ -n "$KILL_RANK" ] && [ "$1" = "$KILL_RANK" ] && [ "$KILL_KIND" = hook ] &&
    echo "NCCL_GIN_RESTORE_TEST_DIE_IN_CKPT=$(npath "$(node_of "$1")" arm):$KILL_HOOK_US"
  [ -n "$KILL_RANK" ] && [ "$1" = "$KILL_RANK" ] && [ -n "$DIE_AT" ] && echo "GIN_RS_DIE_AT=$DIE_AT"
  [ -n "$KILL2_RANK" ] && [ "$1" = "$KILL2_RANK" ] && [ -n "$DIE2_AT" ] && echo "GIN_RS_DIE_AT=$DIE2_AT"
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
wait_line() { python3 -c "$WAITPY" "$@"; }
GPU_APPS="$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | grep -c .)/$(ssh -n "$SUNNY_SSH" "nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | grep -c ." 2>/dev/null)"
declare -A PID
T0=$(date +%s.%N)
launch() {
  local name=$1 r=$2 node=$3 e=$4
  if [ "$node" = sunny ]; then
    ssh -n "$SUNNY_SSH" "cd \$HOME && umask 077 && echo \$\$ > $RT.$name.pid && $NENV $(hca sunny) $(la_env sunny) $RS_ENV RS_RDV_NONCE=$NONCE $e \
stdbuf -oL -eL timeout -s KILL $((WATCHDOG_S + 20)) $RSBIN $r $ARGS $RT.$name.kv 2>&1; echo \$? > $RT.$name.rc" \
      | python3 -u -c "$STAMP" > "$WORK/$name.log" 2>&1 &
  else
    ( echo $BASHPID > "$WORK/$name.pid"
      env $NENV $(hca rain) $(la_env rain) $RS_ENV RS_RDV_NONCE=$NONCE $e \
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
# PIDREC <subshell pid file> <out file> <comm>: "<process pid> <its parent (timeout) pid>" of the launched program
PIDREC='for i in $(seq 1 200); do p=$(cat "$1" 2>/dev/null); [ -n "$p" ] || { sleep 0.1; continue; }
for a in $(pgrep -P "$p"); do for c in $(pgrep -P "$a"); do
[ "$(cat /proc/$c/comm 2>/dev/null)" = "$3" ] && { echo "$c $a" > "$2"; exit 0; }; done; done; sleep 0.1; done; exit 1'
# INJPY <op> ...: the one place the runner signals; every target is a (pid, parent) it recorded, checked by comm and parent
INJPY='import os,sys,time,signal
def mono(): return time.clock_gettime(time.CLOCK_MONOTONIC)*1000.0
def stat(p):
    try: s=open("/proc/%d/stat"%p).read()
    except OSError: return None
    return s[s.index("(")+1:s.rindex(")")], s.rsplit(")",1)[1].split()
def mine(p,pp,n):
    st=stat(p); return st is not None and st[0]==n[:15] and (pp=="-" or st[1][1]==pp)
op=sys.argv[1]; a=sys.argv[2:]
if op=="kill":
    p,pp,n,rk,nd,which=int(a[0]),a[1],a[2],a[3],a[4],a[5]
    if not mine(p,pp,n): print("GINRS no_process rank=%s which=%s mono_ms=%.3f"%(rk,which,mono())); sys.exit(0)
    os.kill(p,signal.SIGKILL); print("GINRS killed rank=%s node=%s pid=%d which=%s mono_ms=%.3f"%(rk,nd,p,which,mono()))
elif op=="pair":
    sp,spp,rp,rpp,n,rk,nd,gap=int(a[0]),a[1],int(a[2]),a[3],a[4],a[5],a[6],float(a[7])
    if not mine(sp,spp,n) or not mine(rp,rpp,n): print("GINRS no_process rank=%s which=pair mono_ms=%.3f"%(rk,mono())); sys.exit(0)
    os.kill(sp,signal.SIGKILL); t1=mono(); print("GINRS spare_killed rank=%s node=%s pid=%d mono_ms=%.3f"%(rk,nd,sp,t1)); sys.stdout.flush()
    time.sleep(gap/1000.0)
    os.kill(rp,signal.SIGKILL); t2=mono(); print("GINRS killed rank=%s node=%s pid=%d which=after_spare gap_ms=%.3f mono_ms=%.3f"%(rk,nd,rp,t2-t1,t2))
elif op=="stop":
    p,pp,n,rk,ms=int(a[0]),a[1],a[2],a[3],float(a[4])
    if not mine(p,pp,n): print("GINRS no_process rank=%s which=stop mono_ms=%.3f"%(rk,mono())); sys.exit(0)
    os.kill(p,signal.SIGSTOP); t1=mono(); print("GINRS stop rank=%s pid=%d stop_ms=%g mono_ms=%.3f"%(rk,p,ms,t1)); sys.stdout.flush()
    time.sleep(ms/1000.0)
    here=mine(p,pp,n)
    if here: os.kill(p,signal.SIGCONT)
    t2=mono(); print("GINRS cont rank=%s pid=%d present=%d stopped_ms=%.3f mono_ms=%.3f"%(rk,p,int(here),t2-t1,t2))
elif op=="duty":
    p,pp,n,rk,on,off,tot=int(a[0]),a[1],a[2],a[3],float(a[4]),float(a[5]),float(a[6])
    if not mine(p,pp,n): print("GINRS no_process rank=%s which=duty mono_ms=%.3f"%(rk,mono())); sys.exit(0)
    t0=mono(); k=0; stopped=0.0; print("GINRS duty start rank=%s pid=%d on_ms=%g off_ms=%g s=%g mono_ms=%.3f"%(rk,p,on,off,tot,t0)); sys.stdout.flush()
    while mono()-t0<tot*1000.0 and mine(p,pp,n):
        os.kill(p,signal.SIGSTOP); a1=mono(); time.sleep(on/1000.0)
        if mine(p,pp,n): os.kill(p,signal.SIGCONT)
        stopped+=mono()-a1; k+=1; time.sleep(off/1000.0)
    if mine(p,pp,n): os.kill(p,signal.SIGCONT)
    print("GINRS duty end rank=%s pid=%d cycles=%d stopped_ms=%.1f mono_ms=%.3f"%(rk,p,k,stopped,mono()))
elif op=="cleanup":
    p,pp,n=int(a[0]),a[1],a[2]
    st=stat(p)
    if st is not None and st[0]==n[:15] and (pp=="-" or st[1][1]==pp) and st[1][0] in ("T","t"):
        os.kill(p,signal.SIGCONT); os.kill(p,signal.SIGKILL); print("GINRS cleanup_stopped pid=%d mono_ms=%.3f"%(p,mono()))
elif op=="fdkill":
    p,t0=int(a[0]),float(a[1])
    st=stat(p)
    if st is None: print("GINRS fdhold_gone pid=%d mono_ms=%.3f"%(p,mono())); sys.exit(0)
    bt=[float(l.split()[1]) for l in open("/proc/stat") if l.startswith("btime ")][0]
    started=bt+float(st[1][19])/os.sysconf("SC_CLK_TCK")
    if st[0]!="gin_fdhold" or os.stat("/proc/%d"%p).st_uid!=os.getuid() or started<t0:
        print("GINRS fdhold_not_ours pid=%d mono_ms=%.3f"%(p,mono())); sys.exit(0)
    os.kill(p,signal.SIGKILL); print("GINRS fdhold_killed pid=%d mono_ms=%.3f"%(p,mono()))'
# on_node <node> <python op args...>: run INJPY on that node, output stamped at receipt into <out file> (appended)
inj() {
  local node=$1 out=$2; shift 2
  if [ "$node" = sunny ]; then ssh -n "$SUNNY_SSH" "python3 -u -c '$INJPY' $*"
  else python3 -u -c "$INJPY" "$@"; fi 2>&1 | python3 -u -c "$STAMP" >> "$out"
}
# rec_pid <name> <node>: start PIDREC for a launched process (in the background); its "<pid> <parent>" lands in $WORK/<name>.cpid
rec_pid() {
  if [ "$2" = sunny ]; then
    ( ssh -n "$SUNNY_SSH" "bash -c '$PIDREC' _ $RT.$1.pid $RT.$1.cpid $BINNAME; cat $RT.$1.cpid 2>/dev/null" > "$WORK/$1.cpid" ) &
  else
    bash -c "$PIDREC" _ "$WORK/$1.pid" "$WORK/$1.cpid" "$BINNAME" &
  fi
}
cpid_of() { for _ in $(seq 1 100); do [ -s "$WORK/$1.cpid" ] && break; sleep 0.1; done; cat "$WORK/$1.cpid" 2>/dev/null; }
for ((r = 0; r < N; r++)); do rec_pid "r$r" "$(node_of "$r")"; done
start_spare() {  # start_spare <name> <rank> <port> [extra env]
  local name=$1 kr=$2 sport=$3 extra=${4:-} knode
  knode=$(node_of "$kr")
  if [ -n "$(wait_line "$WORK/r$kr.log" "GINRS resume rank=$kr " 0 0 60)" ]; then
    launch "$name" "$kr" "$knode" "NCCL_GIN_RESTORE_SPARE=$kr NCCL_GIN_RESTORE_SPARE_PORT=$sport NCCL_GIN_RESTORE_SPARE_WAIT_MS=$SPARE_WAIT_MS NCCL_GIN_RESTORE_REPLAY=$(npath "$knode" "r$kr.rec") ${SPARE_ENV:-} $extra"
    echo "$name" >> "$WORK/spares_started"
    rec_pid "$name" "$knode"
  fi
}
SPARE_ON=0; SPARE2_ON=0; T_READY=0; T_READY2=0
[ -n "$SPORT" ] && start_spare spare "$SPARE_RANK" "$SPORT"
# the second spare: for another rank as run_mi.sh; for the same rank its incarnation is 2 (TODO(phase3): the variable)
if [ -n "$SPORT2" ]; then start_spare spare_2nd "$KILL2_RANK" "$SPORT2"
elif [ "$SPARE2" = 1 ] && [ "$KILL2_RANK" = "$SPARE_RANK" ]; then
  save=$PORT; nextport "$SPORT"; SPORT2=$PORT; PORT=$save
  start_spare spare_2nd "$KILL2_RANK" "$SPORT2" "NCCL_GIN_RESTORE_SPARE_INC=2"
fi
grep -qx spare "$WORK/spares_started" 2>/dev/null && SPARE_ON=1
grep -qx spare_2nd "$WORK/spares_started" 2>/dev/null && SPARE2_ON=1
if [ "$SPARE_ON" = 1 ]; then
  read -r T_READY _ <<< "$(wait_line "$WORK/spare.log" "GINRS spare_ready rank=$SPARE_RANK " 0 0 60)"; T_READY=${T_READY:-0}
fi
if [ "$SPARE2_ON" = 1 ]; then
  read -r T_READY2 _ <<< "$(wait_line "$WORK/spare_2nd.log" "GINRS spare_ready rank=$KILL2_RANK " 0 0 60)"; T_READY2=${T_READY2:-0}
fi
# SPARE_KILL_FIRST=1 (gin-restore's spare-absent regression cell): the spare SIGKILLed by its recorded PID once ready
if [ "$SPARE_ON" = 1 ] && [ "${SPARE_KILL_FIRST:-0}" = 1 ] && [ "$T_READY" != 0 ]; then
  read -r c p < <(cpid_of spare)
  inj "$(node_of "$SPARE_RANK")" "$WORK/spare_kill.out" kill "${c:-0}" "${p:--}" "$BINNAME" "$SPARE_RANK" "$(node_of "$SPARE_RANK")" spare
fi
[ -n "$GATE" ] && touch "$GATE"
T_GATE=$(awk -v a="$T_READY" -v b="$T_READY2" 'BEGIN{printf "%.6f", (a > b ? a : b)}')
secs() { awk -v d="$1" 'BEGIN{printf "%.3f", d / 1000}'; }
# wait_armed <subject> <after receipt time> <excluded rank> [extra log]: the latest receipt time of the survivors' "rank S armed
# at its stable checkpoint K" lines (one per survivor: every rank but the subject and the excluded one, plus the extra log);
# "timeout" when one is missing within ARM_WAIT_S
wait_armed() {
  local s=$1 after=$2 ex=$3 extra=${4:-} t tmax=0 aend left q logs=()
  for ((q = 0; q < N; q++)); do [ "$q" = "$s" ] || [ "$q" = "$ex" ] || logs+=("$WORK/r$q.log"); done
  [ -n "$extra" ] && logs+=("$extra")
  aend=$(awk -v n="$(date +%s.%N)" -v w="$ARM_WAIT_S" 'BEGIN{printf "%.3f", n + w}')
  for lg in "${logs[@]}"; do
    left=$(awk -v n="$(date +%s.%N)" -v e="$aend" 'BEGIN{x = e - n; printf "%.3f", (x > 0 ? x : 0)}')
    read -r t _ <<< "$(wait_line "$lg" "GIN/RS: rank [0-9]+: rank $s armed at its stable checkpoint [0-9]+" "$after" 0 "$left")"
    [ -n "${t:-}" ] || { echo timeout; return; }
    tmax=$(awk -v a="$tmax" -v b="$t" 'BEGIN{printf "%.6f", (b > a ? b : a)}')
  done
  echo "$tmax"
}
INJ_PLAN_RT=-; ARMED_RT=-; ARMED2_RT=-; FDHOLD_PID=-; FDHOLD_LINE=0; ARM_WAIT=-; KILL_STABLE_K=-
if [ "$KILL_KIND" = hook ]; then  # run_mi.sh's checkpoint-pause kill: arm once every survivor saw KILL_RANK armed
  a=$(wait_armed "$KILL_RANK" 0 -1)
  if [ "$a" = timeout ]; then ARM_WAIT=timeout; else
    ARM_WAIT=ok; ARMED_RT=$a
    if [ "$(node_of "$KILL_RANK")" = sunny ]; then ssh -n "$SUNNY_SSH" "touch $RT.arm"; else touch "$WORK/arm"; fi
  fi
fi
INJECTOR=""
TRIG_RANK=${KILL_RANK:-${STOP_RANK:-${DUTY_RANK:-}}}
if [ "$KILL_KIND" = traffic ] || [ "$KILL_KIND" = after_stable ] || [ "$KILL_KIND" = spare_then_rank ] || [ -n "$STOP_RANK" ] || [ -n "$DUTY_RANK" ]; then
  TR=$TRIG_RANK; tnode=$(node_of "$TR")
  ( if [ "$KILL_KIND" = spare_then_rank ]; then
      a=$(wait_armed "$TR" 0 -1)
      echo "$a" > "$WORK/armed_rt"
      [ "$a" = timeout ] && { echo "GINRS no_process rank=$TR which=armed_timeout" | python3 -u -c "$STAMP" >> "$WORK/kill.out"; exit 0; }
      read -r sc sp < <(cpid_of spare); read -r rc rp < <(cpid_of "r$TR")
      inj "$tnode" "$WORK/kill_pair.out" pair "${sc:-0}" "${sp:--}" "${rc:-0}" "${rp:--}" "$BINNAME" "$TR" "$tnode" "$SPARE_GAP_MS"
      exit 0
    fi
    if [ "$FDHOLD" = 1 ]; then
      read -r _ fp <<< "$(wait_line "$WORK/r$TR.log" "test switch FD_HOLDER=[a-z]+: child gin_fdhold pid=([0-9]+)" 0 0 "$(secs "$KILL_DELAY_MS")")"
      [ -n "${fp:-}" ] && echo "$fp" > "$WORK/fdhold.pid"
    fi
    at=$KILL_AT_STEP
    if [ "$KILL_KIND" = after_stable ]; then  # run_mi.sh's: K + KILL_AFTER_STABLE, K the first stable at buddy after the spare was ready
      read -r _ k <<< "$(wait_line "$WORK/r$TR.log" "GIN/RS: rank $TR: checkpoint ([0-9]+) stable at buddy" "$T_READY" 0 "$(secs "$KILL_DELAY_MS")")"
      if [ -n "${k:-}" ]; then at=$((k + KILL_AFTER_STABLE)); echo "$k" > "$WORK/kill_stable_k"; fi
    fi
    read -r tl _ <<< "$(wait_line "$WORK/r$TR.log" "GINRS step rank=$TR step=([0-9]+) released=0" "$T_READY" "$at" "$(secs "$KILL_DELAY_MS")")"
    sleep "$(awk -v u="$KILL_DELAY_US" 'BEGIN{printf "%.6f", u / 1e6}')"
    awk -v t="${tl:-0}" -v u="$KILL_DELAY_US" 'BEGIN{printf "%.6f\n", t + u / 1e6}' > "$WORK/inj_plan_rt"
    read -r c p < <(cpid_of "r$TR")
    if [ -n "$STOP_RANK" ]; then inj "$tnode" "$WORK/inject.out" stop "${c:-0}" "${p:--}" "$BINNAME" "$TR" "$STOP_MS"
    elif [ -n "$DUTY_RANK" ]; then inj "$tnode" "$WORK/inject.out" duty "${c:-0}" "${p:--}" "$BINNAME" "$TR" "$DUTY_ON_MS" "$DUTY_OFF_MS" "$DUTY_S"
    else inj "$tnode" "$WORK/kill.out" kill "${c:-0}" "${p:--}" "$BINNAME" "$TR" "$tnode" first; fi ) &
  INJECTOR=$!
fi
# the second kill by recorded PID after armed (KILL2_KIND=pid_after_armed)
KILLER2=""
if [ "$KILL2_KIND" = pid_after_armed ]; then
  ( K2=$KILL2_RANK; k2node=$(node_of "$K2")
    read -r trs _ <<< "$(wait_line "$WORK/r$(( (KILL_RANK + 1) % N )).log" "GIN/RS: rank [0-9]+: rank $KILL_RANK restored as incarnation" 0 0 "$(secs "$KILL_DELAY_MS")")"
    [ -n "${trs:-}" ] || { echo "GINRS no_process rank=$K2 which=second_no_restore" | python3 -u -c "$STAMP" >> "$WORK/kill.out"; exit 0; }
    if [ "$K2" = "$KILL_RANK" ]; then a=$(wait_armed "$K2" "$trs" -1); target=spare
    else a=$(wait_armed "$K2" "$trs" "$KILL_RANK" "$WORK/spare.log"); target=r$K2; fi
    echo "$a" > "$WORK/armed2_rt"
    [ "$a" = timeout ] && { echo "GINRS no_process rank=$K2 which=second_armed_timeout" | python3 -u -c "$STAMP" >> "$WORK/kill.out"; exit 0; }
    read -r c p < <(cpid_of "$target")
    inj "$k2node" "$WORK/kill.out" kill "${c:-0}" "${p:--}" "$BINNAME" "$K2" "$k2node" second ) &
  KILLER2=$!
fi
for ((r = 0; r < N; r++)); do wait "${PID[r$r]}" 2>/dev/null; done
[ "$SPARE_ON" = 1 ] && wait "${PID[spare]}" 2>/dev/null
[ "$SPARE2_ON" = 1 ] && wait "${PID[spare_2nd]}" 2>/dev/null
T1=$(date +%s.%N)
[ -n "$INJECTOR" ] && wait "$INJECTOR" 2>/dev/null
[ -n "$KILLER2" ] && wait "$KILLER2" 2>/dev/null
wait 2>/dev/null
# the end: a recorded rank or spare PID still stopped gets SIGCONT then SIGKILL; the fd holder by the pid of its fork line
names="r0 r1 r2 r3"; [ "$SPARE_ON" = 1 ] && names="$names spare"; [ "$SPARE2_ON" = 1 ] && names="$names spare_2nd"
node_of_name() { case "$1" in spare) node_of "$SPARE_RANK" ;; spare_2nd) node_of "$KILL2_RANK" ;; *) node_of "${1#r}" ;; esac; }
for name in $names; do
  read -r c p < <(cat "$WORK/$name.cpid" 2>/dev/null)
  [ -n "${c:-}" ] && inj "$(node_of_name "$name")" "$WORK/cleanup.out" cleanup "$c" "${p:--}" "$BINNAME"
done
LEFT_STOPPED=$(grep -c 'GINRS cleanup_stopped' "$WORK/cleanup.out" 2>/dev/null); LEFT_STOPPED=${LEFT_STOPPED:-0}
if [ -s "$WORK/fdhold.pid" ]; then
  FDHOLD_PID=$(cat "$WORK/fdhold.pid"); FDHOLD_LINE=1
  inj "$(node_of "$KILL_RANK")" "$WORK/fdhold.out" fdkill "$FDHOLD_PID" "$(awk -v t="$T0" 'BEGIN{printf "%.3f", t - 5}')"
fi
[ -s "$WORK/inj_plan_rt" ] && INJ_PLAN_RT=$(cat "$WORK/inj_plan_rt")
[ -s "$WORK/armed_rt" ] && ARMED_RT=$(cat "$WORK/armed_rt")
[ -s "$WORK/armed2_rt" ] && ARMED2_RT=$(cat "$WORK/armed2_rt")
[ -s "$WORK/kill_stable_k" ] && KILL_STABLE_K=$(cat "$WORK/kill_stable_k")
if [ -s "$WORK/kill_pair.out" ]; then  # the pair kill: the spare's line apart (run_mi.sh's spare_kill.out), the rank's to kill.out
  grep 'GINRS spare_killed' "$WORK/kill_pair.out" | sed 's/GINRS spare_killed/GINRS killed/' >> "$WORK/spare_kill.out"
  grep -v 'GINRS spare_killed' "$WORK/kill_pair.out" >> "$WORK/kill.out"
fi
# the launchers after the trial (pid and start again; their log lines of the trial window)
if [ "$LAUNCHER_SCOPE" != none ]; then
  LAA_RAIN=$(la_info rain); LAA_SUNNY=$(la_info sunny)
fi
MTU1_RAIN=$(bash -c "$MTU_Q" _ mlx5_1); MTU1_SUNNY=$(ssh -n "$SUNNY_SSH" bash -c "'$MTU_Q'" _ mlx5_0)
RNR1_RAIN=$(bash -c "$RNR_Q" _ mlx5_1); RNR1_SUNNY=$(ssh -n "$SUNNY_SSH" bash -c "'$RNR_Q'" _ mlx5_0)
LIB_MD5=$(md5sum < "$LIBDIR/libnccl.so.2" 2>/dev/null | cut -c1-32); LIB_MD5=${LIB_MD5:-none}
DRIVER_MD5=$(md5sum < "$RSBIN" 2>/dev/null | cut -c1-32); DRIVER_MD5=${DRIVER_MD5:-none}
for name in $names; do
  if [ -f "$WORK/$name.kv" ]; then continue; fi
  scp -q "$SUNNY_SSH:$RT.$name.kv" "$WORK/$name.kv" 2>/dev/null || true
  scp -q "$SUNNY_SSH:$RT.$name.rc" "$WORK/$name.rc" 2>/dev/null || true
done
ssh -n "$SUNNY_SSH" "rm -f $RT.*" 2>/dev/null || true
LEFT=$( { pgrep -x "$BINNAME"; ssh -n "$SUNNY_SSH" "pgrep -x $BINNAME"; } 2>/dev/null | wc -l)
LEFT_FD=$( { pgrep -x -u "$(id -u)" gin_fdhold; ssh -n "$SUNNY_SSH" 'pgrep -x -u "$(id -u)" gin_fdhold'; } 2>/dev/null | wc -l)
mkdir -p "$LOGDIR"
stem="${CELL:-gc}_${LIB}_${TRIAL}"
MASK='s/[0-9]\{1,3\}\.[0-9]\{1,3\}\.[0-9]\{1,3\}\.[0-9]\{1,3\}/<ip>/g'
rm -f "$LOGDIR/${stem}"_*
for name in $names; do
  [ -f "$WORK/$name.kv" ] && sed "$MASK" "$WORK/$name.kv" > "$LOGDIR/${stem}_$name.kv"
  [ -f "$WORK/$name.log" ] && sed "$MASK" "$WORK/$name.log" > "$LOGDIR/${stem}_$name.log"
done
for f in kill spare_kill inject fdhold cleanup; do
  [ -f "$WORK/$f.out" ] && sed "$MASK" "$WORK/$f.out" > "$LOGDIR/${stem}_$f.out"
done
if [ "$LAUNCHER_SCOPE" != none ]; then  # the launcher lines of this trial: from the byte offset read before the ranks started
  for nd in rain sunny; do
    lg=$(dirname "${LAREC[$nd]}")/$(basename "${LAREC[$nd]}" .rec).log
    [ -f "$lg" ] && tail -c +"$(( ${LAOFF[$nd]:-0} + 1 ))" "$lg" | sed "$MASK" > "$LOGDIR/${stem}_launcher_$nd.log"
  done
fi
rcs=""; for name in $names; do rcs="$rcs ${name}rc=$(tr -d '\n' < "$WORK/$name.rc" 2>/dev/null || echo none)"; done
sp() { echo "$1" | tr ' ' ','; }
echo "cell=${CELL:-} lib=$LIB ctrl=$CTRL n=$N steps=$STEPS bytes=$BYTES policy=$FAULT_POLICY restore=$RESTORE sym_gin=$SYM_GIN \
gin_type=$GIN_TYPE num_rma_ctx=$NUM_RMA_CTX nconn=$NCONN qpwatch_ms=$QPWATCH restore_ms=$RESTORE_MS checksum=$CHECKSUM \
log_measure=$LOG_MEASURE step_gap_us=$STEP_GAP_US mirror=$MIRROR mirror_slots=${MIRROR_SLOTS:-} mirror_lane=${MIRROR_LANE:-} \
overwrite=$OVERWRITE train=$TRAIN ring=$RING ckpt_steps=${CKPT_STEPS:-} witness=${WITNESS:-1} fence=${FENCE:-lineage} \
rst_gap_ms=${RST_GAP_MS:-} confirm_ms=${CONFIRM_MS:-} probe_ms=${PROBE_MS:-} kill_rank=$KILL_RANK kill_kind=$KILL_KIND \
kill_at_step=$KILL_AT_STEP kill_delay_us=$KILL_DELAY_US kill_fallback_ms=$KILL_DELAY_MS subject_rank=$SUBJECT inject=$INJECT \
kill_in_hook=$KILL_IN_HOOK kill_hook_us=$KILL_HOOK_US kill_after_stable=$KILL_AFTER_STABLE kill_stable_k=$KILL_STABLE_K \
die_switch=$([ "$KILL_KIND" = hook ] && echo NCCL_GIN_RESTORE_TEST_DIE_IN_CKPT || echo -) arm_wait=$ARM_WAIT \
spare_kill_first=${SPARE_KILL_FIRST:-0} \
inj_plan_rt=$INJ_PLAN_RT stop_rank=$STOP_RANK stop_ms=$STOP_MS duty_rank=$DUTY_RANK duty_on_ms=$DUTY_ON_MS duty_off_ms=$DUTY_OFF_MS \
duty_s=$DUTY_S fdhold=$FDHOLD fdhold_pid=$FDHOLD_PID fdhold_line=$FDHOLD_LINE spare_gap_ms=$SPARE_GAP_MS armed_rt=$ARMED_RT \
die_seed=${DIE_SEED:-} die_at=${DIE_AT:--} kill2_rank=$KILL2_RANK kill2_kind=${KILL2_KIND:--} die2_at=${DIE2_AT:--} armed2_rt=$ARMED2_RT \
die_us_max=$DIE_US_MAX spare_wait_ms=$SPARE_WAIT_MS spare=$SPARE_ON spare_wanted=$SPARE spare_rank=$SPARE_RANK \
spare_ready=$([ "$T_READY" != 0 ] && echo 1 || echo 0) spare2=$SPARE2_ON spare2_wanted=$SPARE2 \
spare2_ready=$([ "$T_READY2" != 0 ] && echo 1 || echo 0) gate_rt=$T_GATE gpu_apps_before=$GPU_APPS end_grace_ms=$END_GRACE_MS \
launcher_scope=$LAUNCHER_SCOPE launcher_ready=$LA_OK launcher_tc=$LA_TC launcher_env=$(echo ${LAUNCHER_ENV:-} | tr ' ' '+') \
launcher_before_rain=$(sp "$LAB_RAIN") launcher_before_sunny=$(sp "$LAB_SUNNY") launcher_after_rain=$(sp "$LAA_RAIN") \
launcher_after_sunny=$(sp "$LAA_SUNNY") active_mtu_rain=${MTU_RAIN:--} active_mtu_sunny=${MTU_SUNNY:--} \
active_mtu_after_rain=${MTU1_RAIN:--} active_mtu_after_sunny=${MTU1_SUNNY:--} rnr_before_rain=$RNR0_RAIN rnr_before_sunny=$RNR0_SUNNY \
rnr_after_rain=$RNR1_RAIN rnr_after_sunny=$RNR1_SUNNY mem_avail_rain=$AVAIL_RAIN mem_avail_sunny=$AVAIL_SUNNY \
mem_need_rain=$NEED_RAIN mem_need_sunny=$NEED_SUNNY pin_mb_per_proc=$PIN_PER trial=$TRIAL hold=${HOLD_TAG:-} \
extra=$(echo ${EXTRA_ENV:-} | tr ' ' '+') r0_env=$(echo ${R0_ENV:-} | tr ' ' '+') r1_env=$(echo ${R1_ENV:-} | tr ' ' '+') \
r2_env=$(echo ${R2_ENV:-} | tr ' ' '+') r3_env=$(echo ${R3_ENV:-} | tr ' ' '+') spare_env=$(echo ${SPARE_ENV:-} | tr ' ' '+')$rcs \
left=$LEFT left_stopped=$LEFT_STOPPED left_fdhold=$LEFT_FD gid0=$GID0 gid1=$GID1 port=$PORT port_tries=$PORT_TRIES \
rdv_nonce_set=1 runner=gcr driver=$DRIVER wall_s=$(awk -v a="$T0" -v b="$T1" 'BEGIN{printf "%.1f", b - a}') watchdog_s=$WATCHDOG_S \
bin=$BINNAME rs_set=$RS_SET lib_md5=$LIB_MD5 driver_md5=$DRIVER_MD5" > "$LOGDIR/${stem}_meta.txt"
echo "[$tag]$rcs left=$LEFT stopped=$LEFT_STOPPED fdhold=$LEFT_FD wall=$(awk -v a="$T0" -v b="$T1" 'BEGIN{printf "%.1f", b - a}')s" >&2
exit 0
