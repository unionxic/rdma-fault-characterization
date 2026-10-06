#!/usr/bin/env bash
# run_trial.sh - one NCCL GIN fault trial (rank0=rain initiator, rank1=sunny target).
#
# Must be invoked *inside* common/cluster_run.sh (which holds the cluster lock
# and waits for an idle RoCE link). This script launches rank1 on sunny over SSH
# and rank0 locally on rain, injects the fault, collects each rank's KEY=VALUE
# result file, and appends one CSV row (DESIGN.md columns) to $OUT_CSV.
#
# usage: run_trial.sh <proxy|gdaki> <none|F1|F2|F3|F4> <timeout|blocking> <trial#> <out_csv> [iters] [ib_timeout]
set -u

BACKEND=$1; FAULT=$2; WAIT=$3; TRIAL=$4; OUT_CSV=$5
ITERS=${6:-120}
IB_TIMEOUT=${7:-14}          # DESIGN: 14 for short trials; 20 (default) for the F3 reference
INJECT_MS=${INJECT_MS:-600}  # when the fault fires, relative to GIN context creation
GAP_MS=${GAP_MS:-15}         # inter-iteration pacing so the fault lands mid-run
DEV_TIMEOUT_S=${DEV_TIMEOUT_S:-5}   # bounded device wait (timeout mode)
WATCHDOG_S=${WATCHDOG_S:-90}        # per-rank host watchdog (hard bound)
BYTES=${BYTES:-262144}       # 256 KiB

RAIN_MGMT=192.0.2.193
SUNNY_SSH=${SUNNY_SSH:-unionxic@192.0.2.194}
BUNDLE=/home/unionxic/gi-bundle/gin
PORT=$(( 41000 + ($$ + RANDOM) % 4000 ))   # PID-salted to avoid reusing a lingering socket
GINTYPE=2; [ "$BACKEND" = gdaki ] && GINTYPE=3

STAMP=$(date +%Y%m%d_%H%M%S)
WORK=$(mktemp -d /tmp/gin_trial.XXXXXX)
R0KV=$WORK/r0.kv;  R1KV=$WORK/r1.kv
R0LOG=$WORK/r0.log; R1LOG=$WORK/r1.log
tag="${BACKEND}/${FAULT}/${WAIT}#${TRIAL}"

# --- per-node GID probe (RoCE v2 IPv4), mirrors harness/run.sh -------------
GID_PROBE='d=/sys/class/infiniband/$1/ports/1
for g in $(ls "$d/gids" | sort -n); do
  [ "$(cat "$d/gid_attrs/types/$g" 2>/dev/null)" = "RoCE v2" ] || continue
  case "$(cat "$d/gids/$g")" in 0000:0000:0000:0000:0000:ffff:*) echo "$g"; exit 0;; esac
done; exit 1'
GID0=$(bash -c "$GID_PROBE" _ mlx5_1) || { echo "[$tag] no GID on rain mlx5_1" >&2; exit 1; }
GID1=$(ssh -n "$SUNNY_SSH" bash -c "'$GID_PROBE'" _ mlx5_0) || { echo "[$tag] no GID on sunny mlx5_0" >&2; exit 1; }

# --- fault -> per-rank injection env --------------------------------------
INJ0=""; INJ1=""            # NCCL_GIN_FAULT_INJECT for rank0/rank1
KILL_R1=0
case "$FAULT" in
  none) ;;
  F1)   INJ0="local_err:$INJECT_MS" ;;                 # initiator moves its own QP to ERR
  F2)   ;;                                             # driver puts past end of remote window (no hook)
  F3)   INJ1="peer_err:$INJECT_MS" ;;                  # target moves its own QP to ERR, stays alive
  F4)   KILL_R1=1 ;;                                   # SIGKILL rank1 mid-run
  *) echo "unknown fault $FAULT" >&2; exit 1 ;;
esac

COMMON_ENV="NCCL_DEBUG=${NCCL_DEBUG:-WARN} NCCL_DEBUG_SUBSYS=${NCCL_DEBUG_SUBSYS:-INIT,NET} \
NCCL_SOCKET_IFNAME=eno1 NCCL_GIN_TYPE=$GINTYPE NCCL_IB_TIMEOUT=$IB_TIMEOUT \
NCCL_GIN_ENABLE=1 GIN_ABORT_WATCHDOG_S=${GIN_ABORT_WATCHDOG_S:-15} LD_LIBRARY_PATH=$BUNDLE \
GIN_BLOCK_CAP_S=${GIN_BLOCK_CAP_S:-25} GIN_POST_POLL_S=${GIN_POST_POLL_S:-15}"

DRV_ARGS="$ITERS $BYTES $WAIT $FAULT $DEV_TIMEOUT_S $WATCHDOG_S"

echo "[$tag] GID rain=$GID0 sunny=$GID1 port=$PORT ib_timeout=$IB_TIMEOUT inject=${INJECT_MS}ms" >&2

# --- launch rank1 (sunny) over SSH ------------------------------------------
# gin_fault runs in the FOREGROUND of the remote shell (writing its own log);
# the ssh is backgrounded *locally* so rank0 can start immediately. (Capturing
# a remotely-backgrounded PID via $(ssh ...) would block until the job exits.)
REMOTE_CMD="cd $BUNDLE && $COMMON_ENV NCCL_IB_HCA=mlx5_0 NCCL_IB_GID_INDEX=$GID1 \
${INJ1:+NCCL_GIN_FAULT_INJECT=$INJ1} \
exec stdbuf -oL -eL timeout -s KILL $((WATCHDOG_S+30)) ./gin_fault 1 $RAIN_MGMT $PORT $DRV_ARGS /tmp/gin_r1.kv $GAP_MS \
> /tmp/gin_r1.log 2>&1"
ssh -n "$SUNNY_SSH" "$REMOTE_CMD" &
SSH_PID=$!
echo "[$tag] rank1 launched on sunny (ssh pid=$SSH_PID)" >&2

# --- optional proc_kill: SIGKILL rank1 by its PID mid-run --------------------
# F4 fires from trial start (not GIN-context creation like the hook faults), so
# it needs a larger delay to let both ranks finish setup and run some iterations
# before rank 1 dies (KILL_DELAY_MS, default 3000).
if [ "$KILL_R1" = 1 ]; then
  KILL_DELAY_MS=${KILL_DELAY_MS:-3000}
  ( sleep "$(awk "BEGIN{print $KILL_DELAY_MS/1000}")"
    # kill by PID (pgrep, never pkill -f; our binary name is unique). The
    # CLOCK_MONOTONIC timestamp is taken on SUNNY in the same process that sends
    # SIGKILL (microseconds apart), then converted to rain's clock with the
    # driver-measured offset -> F4 fault time.
    ssh -n "$SUNNY_SSH" 'pid=$(pgrep -x gin_fault | head -1); [ -n "$pid" ] && python3 -c "import os,sys,time; t=time.clock_gettime(time.CLOCK_MONOTONIC)*1e3; os.kill(int(sys.argv[1]),9); print(\"kill_mono_ms=%.3f\" % t)" $pid' > "$WORK/kill.out" 2>&1
    echo "[$tag] SIGKILLed rank1 (by PID) after ${KILL_DELAY_MS}ms: $(cat "$WORK/kill.out")" >&2 ) &
  KILLER=$!
fi

# --- launch rank0 (rain) in foreground --------------------------------------
env $COMMON_ENV NCCL_IB_HCA=mlx5_1 NCCL_IB_GID_INDEX=$GID0 \
  ${INJ0:+NCCL_GIN_FAULT_INJECT=$INJ0} \
  stdbuf -oL -eL timeout -s KILL $((WATCHDOG_S+30)) \
  "$BUNDLE/gin_fault" 0 $RAIN_MGMT $PORT $DRV_ARGS "$R0KV" "$GAP_MS" > "$R0LOG" 2>&1
R0RC=$?

# --- collect rank1 artifacts and make sure nothing is left on sunny ---------
wait "$SSH_PID" 2>/dev/null; R1RC=$?          # remote gin_fault exit status via ssh
[ "${KILLER:-}" ] && wait "$KILLER" 2>/dev/null
scp -q "$SUNNY_SSH:/tmp/gin_r1.kv" "$R1KV" 2>/dev/null || true
scp -q "$SUNNY_SSH:/tmp/gin_r1.log" "$R1LOG" 2>/dev/null || true
# hard cleanup: kill any stray driver of ours on sunny (unique binary name)
ssh -n "$SUNNY_SSH" "pgrep -x gin_fault | xargs -r kill -9 2>/dev/null; rm -f /tmp/gin_r1.kv /tmp/gin_r1.log" || true
pkill -x gin_fault 2>/dev/null || true

# persist raw logs
LOGDIR=$(dirname "$OUT_CSV")/logs
mkdir -p "$LOGDIR"
cp "$R0LOG" "$LOGDIR/${BACKEND}_${FAULT}_${WAIT}_t${TRIAL}_r0.log" 2>/dev/null || true
cp "$R1LOG" "$LOGDIR/${BACKEND}_${FAULT}_${WAIT}_t${TRIAL}_r1.log" 2>/dev/null || true
cp "$R0KV"  "$LOGDIR/${BACKEND}_${FAULT}_${WAIT}_t${TRIAL}_r0.kv"  2>/dev/null || true
cp "$R1KV"  "$LOGDIR/${BACKEND}_${FAULT}_${WAIT}_t${TRIAL}_r1.kv"  2>/dev/null || true

# --- parse KV files ---------------------------------------------------------
kvget() { grep -oE "$2=[^ ]+" "$1" 2>/dev/null | tail -1 | cut -d= -f2- ; }

GINTYPE_SEEN=$(kvget "$R0KV" gin_type); [ -z "$GINTYPE_SEEN" ] && GINTYPE_SEEN=$(kvget "$R1KV" gin_type)
R0_OUT=$(kvget "$R0KV" init_outcome)
R1_DATA=$(kvget "$R1KV" data_check)
R0_ITERS=$(kvget "$R0KV" iters_ok)
R1_ITERS=$(kvget "$R1KV" iters_ok)
R0_HOSTERR=$(kvget "$R0KV" host_error)
R0_HOSTERRMS=$(kvget "$R0KV" host_error_ms)
R1_HOSTERR=$(kvget "$R1KV" host_error)
R1_HOSTERRMS=$(kvget "$R1KV" host_error_ms)
R0_SILENT=$(kvget "$R0KV" silent_success)
R1_SILENT=$(kvget "$R1KV" silent_success)
R0_TEARDOWN=$(kvget "$R0KV" teardown)

# --- derive combined outcome ------------------------------------------------
iters_ok_before=${R0_ITERS:-0}
init_outcome=${R0_OUT:-unknown}
# blocking-mode global-watchdog kill leaves no KV outcome
if [ "$R0RC" = 137 ] || { [ "$R0RC" = 7 ] && [ -z "$R0_OUT" ]; }; then init_outcome=hang_killed; fi
[ "$R0RC" = 7 ] && [ "$init_outcome" = unknown ] && init_outcome=hang_killed

case "$FAULT" in
  F4) target_outcome=killed ;;
  *)  if [ "$R1RC" = 137 ] || [ "$R1RC" = 7 ]; then target_outcome=hang_killed
      elif [ -n "$(kvget "$R1KV" timeout_ms)" ] || [ "$(kvget "$R1KV" device_rc)" = ncclTimeout ]; then target_outcome=timeout
      elif [ "${R1_DATA:-n/a}" = ok ] && [ "${R1RC:-NA}" = 0 ]; then target_outcome=ok
      else target_outcome=${R1_DATA:+error}; target_outcome=${target_outcome:-unknown}; fi ;;
esac

data_check=${R1_DATA:-n/a}
[ "$FAULT" = F4 ] && data_check=missing
# a hung receiver never completed the compare: the delivered data is unmeasured
[ "$target_outcome" = hang_killed ] && data_check=n/a

# silent_success (DESIGN): the initiator's wait reported success for an op whose
# data did not arrive intact. => rank0 flush never failed (init_outcome=ok) AND
# rank1's bytes are missing/mismatch. (Also honour a per-rank driver flag.)
silent_success=0
if { [ "$init_outcome" = ok ] && { [ "${R1_DATA:-}" = missing ] || [ "${R1_DATA:-}" = mismatch ]; }; }; then silent_success=1; fi
{ [ "${R0_SILENT:-0}" = 1 ] || [ "${R1_SILENT:-0}" = 1 ]; } && silent_success=1

# --- host error + time to surface, all on RANK0's CLOCK_MONOTONIC ------------
# Each rank logs t0_mono_ms (its program start) and host_error_ms (relative to
# its own start); rank0 logs clock_offset_ms = rank1_clock - rank0_clock (min-RTT
# ping-pong). Fault fire time: F1 hook line on rank0 (fire_mono_ms), F3 hook line
# on rank1 (sunny clock), F2 first OOB put launch on rank0 (fault_mono_ms), F4 the
# SIGKILL timestamp taken on sunny in the killing process (kill_mono_ms).
# host_error_ms and fault_ms are relative to rank0's start; surface_ms is their
# difference; surface_by says which rank's ncclCommGetAsyncError saw it first.
FIRE0=$(grep -ohE 'fire_mono_ms=[0-9.]+' "$R0LOG" 2>/dev/null | head -1 | cut -d= -f2)
FIRE1=$(grep -ohE 'fire_mono_ms=[0-9.]+' "$R1LOG" 2>/dev/null | head -1 | cut -d= -f2)
MOVED=$(grep -ohE 'moved [0-9]+/[0-9]+' "$R0LOG" "$R1LOG" 2>/dev/null | head -1 | awk '{print $2}')
KILLT=$(grep -ohE 'kill_mono_ms=[0-9.]+' "$WORK/kill.out" 2>/dev/null | head -1 | cut -d= -f2)
read host_error host_error_ms fault_ms surface_ms surface_by init_silent_iters clock_offset_ms < <(
FAULT=$FAULT T0R0=$(kvget "$R0KV" t0_mono_ms) T0R1=$(kvget "$R1KV" t0_mono_ms) OFF=$(kvget "$R0KV" clock_offset_ms) \
E0="${R0_HOSTERR:-none}" E0MS="${R0_HOSTERRMS:--1}" E1="${R1_HOSTERR:-none}" E1MS="${R1_HOSTERRMS:--1}" \
FIRE0="$FIRE0" FIRE1="$FIRE1" F2T=$(kvget "$R0KV" fault_mono_ms) KILLT="$KILLT" \
OK0=$(kvget "$R0KV" okit) OK1=$(kvget "$R1KV" okit) python3 - <<'PY'
import os
g=lambda k: os.environ.get(k,'')
def f(k):
    try: return float(g(k))
    except ValueError: return None
t0r0, t0r1, off = f('T0R0'), f('T0R1'), f('OFF')
cands=[]
if g('E0') not in ('','none') and f('E0MS') is not None and f('E0MS')>=0 and t0r0 is not None:
    cands.append((t0r0+f('E0MS'), g('E0'), 'r0'))
if g('E1') not in ('','none') and f('E1MS') is not None and f('E1MS')>=0 and None not in (t0r1, off):
    cands.append((t0r1+f('E1MS')-off, g('E1'), 'r1'))
fa=None
F=g('FAULT')
if F=='F1': fa=f('FIRE0')
elif F=='F3' and f('FIRE1') is not None and off is not None: fa=f('FIRE1')-off
elif F=='F2': fa=f('F2T')
elif F=='F4' and f('KILLT') is not None and off is not None: fa=f('KILLT')-off
he,hems,sb='none','-','-'
if cands:
    a,he,sb=min(cands); hems='%.1f'%(a-t0r0)
fms='%.1f'%(fa-t0r0) if (fa is not None and t0r0 is not None) else '-'
sms='%.1f'%(min(cands)[0]-fa) if (cands and fa is not None) else '-'
ok0=int(g('OK0') or 0); ok1=int(g('OK1') or 0)
print(he,hems,fms,sms,sb,ok0-ok1,('%.3f'%off) if off is not None else '-')
PY
)
[ "$host_error_ms" = - ] && host_error_ms=
[ "$fault_ms" = - ] && fault_ms=
[ "$surface_ms" = - ] && surface_ms=

# teardown: clean if abort returned (KV present), hang if exit 7 with no teardown line
teardown=${R0_TEARDOWN:-n/a}
[ "$R0RC" = 7 ] && [ -z "$R0_TEARDOWN" ] && teardown=hang

# fingerprint location + status/vendor_err from WARN lines (proxy path only)
fp_where=none; status=; vendor_err=
if grep -q 'NET/IB/GIN: Got completion' "$R0LOG" "$R1LOG" 2>/dev/null; then
  fp_where=log
  wl=$(grep -h 'NET/IB/GIN: Got completion' "$R0LOG" "$R1LOG" 2>/dev/null | tail -1)
  status=$(echo "$wl" | grep -oE 'status=[0-9]+' | cut -d= -f2)
  vendor_err=$(echo "$wl" | grep -oE 'vendor err [0-9]+' | awk '{print $3}')
elif grep -q 'GIN Error detected' "$R0LOG" "$R1LOG" 2>/dev/null; then
  fp_where=api    # GDAKI: only "QP in ERR" is surfaced, no status/vendor_err
fi

notes="r0rc=$R0RC;r1rc=$R1RC;gintype=${GINTYPE_SEEN:-?};qps_moved=${MOVED:--};drain_rc=$(kvget "$R0KV" drain_device_rc);post_poll_ms=$(kvget "$R0KV" post_poll_ms)/$(kvget "$R1KV" post_poll_ms)"

# --- append CSV row ---------------------------------------------------------
if [ ! -f "$OUT_CSV" ]; then
  echo "stack,backend,fault,wait_mode,trial,iters_ok_before,init_outcome,target_outcome,data_check,silent_success,host_error,host_error_ms,fp_where,status,vendor_err,teardown,notes,fault_ms,surface_ms,surface_by,init_silent_iters,clock_offset_ms" > "$OUT_CSV"
fi
echo "nccl-gin,$BACKEND,$FAULT,$WAIT,$TRIAL,$iters_ok_before,$init_outcome,$target_outcome,$data_check,$silent_success,$host_error,${host_error_ms:-},$fp_where,${status:-},${vendor_err:-},$teardown,$notes,${fault_ms:-},${surface_ms:-},$surface_by,$init_silent_iters,$clock_offset_ms" >> "$OUT_CSV"
echo "[$tag] -> init=$init_outcome target=$target_outcome data=$data_check silent=$silent_success host_error=$host_error@${host_error_ms:-}ms fault@${fault_ms:-}ms surface=${surface_ms:-}ms(${surface_by}) init_silent=$init_silent_iters fp=$fp_where st=${status:-} ve=${vendor_err:-} teardown=$teardown (r0rc=$R0RC r1rc=$R1RC)" >&2

rm -rf "$WORK"
exit 0
