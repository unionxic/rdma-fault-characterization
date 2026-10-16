#!/usr/bin/env bash
# hold_gc.sh - one hold of gin-control's test side (../../EXPERIMENT.md 7, 8; n and caps are DRAFT, fixed at the
# pre-registration). gin-mirror's hold_mi.sh (copied and then changed): the main session runs it inside
# ../../../../common/cluster_run.sh (tag gc-<hold>, -w 10800) under timeout -s KILL 880, through chain_gc.sh. Before and after
# the hold: hold_mi.sh's snapshots (GPU users and compute mode, BAR1, rain's NVRM mapping-failure lines, mlx5 kernel lines,
# rain's firmware-command counters) and its stops (STOP_mlx5, STOP_cuda, STOP_left, STOP_nic, STOP_mem), rain's BAR1 start
# gate, the per-trial QUERY_QP cap.
#
# What is new against hold_mi.sh (section 8's additions):
#   - the launchers: a hold that runs an rdma build (gc, gcp) starts one launcher per node before its first trial
#     (launcher_gc.sh start, with the hold's one launcher_env from cells_gc.json; EXPERIMENT 5: one per node per hold, the
#     coordinator's decision of 2026-10-17) and stops them after its last trial (the ranks of every trial ended before: the
#     launcher last). run_gc.sh reads their records (LAUNCHER_REC_RAIN, LAUNCHER_REC_SUNNY), checks at every trial's start
#     that the registration table is empty (exit 7 otherwise) and writes trial_start / trial_end markers into both launcher
#     logs. Either launcher not ready: both are stopped and the hold does not start (STOP_launcher);
#   - per trial: STOP_launcher for a launcher line "(STOP_launcher)" or "(STOP_launcher: ...)" in the trial's launcher slices
#     (a refused signal, a FENCE_NAK, the RNIC transport failing; the pid-check failure; both forms through
#     rows_gc.py --stops, the scorer's rule), a launcher QP loss outside the test-switch cells (the same rule as rows_gc.py's
#     la_qp_err_n: after the trial's start marker, before the first "is leaving", of a rank other than the subject), a
#     launcher gone or changed (pid or start time) between the trial's start and end, or the trial's start check failing
#     (run_gc.sh exit 6: not ready, exit 7: the table not empty; cells_gc.sh); STOP_rnr for a growth of the RNR port counter
#     outside gc4_credit_stall; STOP_left for a stopped (state T) process or a gin_fdhold child left after the trial
#     (run_gc.sh's meta left_stopped, left_fdhold); STOP_async for an asynchronous event of a record or liveness-READ QP (the
#     library's control summary, TODO(phase2)) outside the test-switch cells; STOP_mtu when a port's active_mtu after the
#     trial differs from before; after the last trial, a STOP line in a launcher log after its last trial_end marker;
#   - the start check of section 8: both GIN ports' active_mtu must be at least 2048 and equal, else the hold does not start
#     (STOP_mtu);
#   - leftovers: this study's driver names (gin_mi, gin_mi_nomacro), this uid's gin_fdhold and gin_launcher, this study's
#     /tmp paths (gc_rt, gc_cost) and gin-remaining's runner's (gin_mrr_), read only. Processes are never killed here by name;
#   - pilot and smoke holds (P*, COSTPILOT-*) run only in a results folder whose name starts with pilot or smoke, and the
#     main-run holds (C*, RG-*, COST-*) never in such a folder (REVIEW_TEST fix 16: no shared file names);
#   - the hold runs only under chain_gc.sh (GC_CHAIN=1, which chain_gc.sh sets inside cluster_run.sh).
#
# usage: hold_gc.sh <resultsdir> <hold>
#   C1-C11                 the main-run holds of cells_gc.json (section 7 rows 1-22)
#   P0-P4                  the pilot holds (never scored; a results folder pilot* or smoke* of their own): P0 the smoke, P1
#                          one trial of every rdma cell, P2 of every tcp cell, P3 the noreport cell (its launcher with
#                          NO_EXIT_REPORT), P4 9.9's unscored 12 000 ms stop (its own cell gc4_stop12000_pilot)
#   RG-<gct|gc>-<G1|G3|T1|T2|G2|R1|R2|R3>   gin-mirror's hold of that name (../../../mirror/impl/test/cells_mi.json), every
#                          cell with its name, env and n, at the named build (section 7 rows 23, 24)
#   COST-probe-<rain|sunny>[-<metric>]       the probe cost family on the receiving node (3 arms x 3 metrics x 6 rounds)
#   COSTPILOT-<rain|sunny> one round of the probe cost family
# env: SUNNY_SSH (required), RS_SET (required), RS_QUERY_CAP (50000), RS_QUERY_CAP_REG (150000), RS_TRIAL_BOUND_S (60: the
#   4 KiB trials; a cell's bound_s overrides), RS_TRAIN_BOUND_S (150), GC_CHAIN (1, set by chain_gc.sh).
# Resumable as hold_mi.sh: a cell trial whose <stem>_meta.txt exists is skipped.
set -u
R=${1:?resultsdir}; H=${2:?hold}
D=$(cd "$(dirname "$0")" && pwd)
[ "${GC_CHAIN:-0}" = 1 ] || { echo "hold_gc.sh runs only under chain_gc.sh (inside cluster_run.sh)" >&2; exit 2; }
# shellcheck source=remote_gc.sh
. "$D/remote_gc.sh"
SUNNY_SSH=${SUNNY_SSH:?set SUNNY_SSH}
export SUNNY_SSH
RS_SET=${RS_SET:-}
# shellcheck source=../../../mirror/impl/test/rs_set_mi.sh
. "$D/../../../mirror/impl/test/rs_set_mi.sh"
rs_set_check || exit 2
export RS_SET
CELLS=$D/cells_gc.json
MCELLS=$D/../../../mirror/impl/test/cells_mi.json
FW=$D/../../../scripts/ts1/fwcmd_snapshot.sh
[ -f "$FW" ] || { echo "missing $FW" >&2; exit 2; }
QCAP=${RS_QUERY_CAP:-50000}
QCAP_REG=${RS_QUERY_CAP_REG:-150000}
TRIAL_BOUND=${RS_TRIAL_BOUND_S:-60}
TRAIN_BOUND=${RS_TRAIN_BOUND_S:-150}
case "$H" in P*|COSTPILOT-*) PILOT=1 ;; *) PILOT=0 ;; esac
case "$(basename "$R")" in
  pilot*|smoke*) [ "$PILOT" = 1 ] || { echo "hold $H is a main-run hold: not in the pilot/smoke folder $(basename "$R")" >&2; exit 2; } ;;
  *) [ "$PILOT" = 0 ] || { echo "hold $H is a pilot or smoke hold: its results folder's name starts with pilot or smoke" >&2; exit 2; } ;;
esac
CMDERR='grep -i mlx5 | grep -iE "cmd|command" | grep -icE "failed|timeout|leak"'
mkdir -p "$R"
HT=$H
if [ -e "$R/snap_before-$HT.txt" ]; then k=2; while [ -e "$R/snap_before-$H-r$k.txt" ]; do k=$((k + 1)); done; HT=$H-r$k; fi
export HOLD_TAG=$HT
case "$H" in RG-*-T1|RG-*-T2) export BAR1_AT_GATE=1 ;; esac  # gin-mirror's training holds: rain's BAR1 at each gate (run_gc.sh)
echo "hold $H (files tagged $HT) rs_set=$RS_SET"
LEFTQ='pgrep -x gin_mi; pgrep -x gin_mi_nomacro; pgrep -x -u "$(id -u)" gin_fdhold; pgrep -x -u "$(id -u)" gin_launcher
pgrep -f "[/]tmp/gc_rt"; pgrep -f "[/]tmp/gc_cost"; pgrep -f "[/]tmp/gin_mrr_"; true'
left() { { bash -c "$LEFTQ"; sunny_sh "$LEFTQ"; } 2>/dev/null | wc -l; }
OWNCLEAN='find /tmp -maxdepth 1 -user "$(id -un)" \( -name "gc_rt_*" -o -name "gc_rt.*" -o -name "gc_cost_*" -o -name "gc_cost.*" -o -name "gc_la.*" -o -name "gc_lp.*" \) -exec rm -rf {} + 2>/dev/null; true'
for f in STOP_mlx5 STOP_cuda STOP_left STOP_nic STOP_mem STOP_launcher STOP_rnr STOP_mtu STOP_async; do
  if [ -e "$R/$f" ]; then
    echo "$R/$f present: no hold runs" >&2
    [ "$(left)" -eq 0 ] && { bash -c "$OWNCLEAN"; sunny_sh "$OWNCLEAN"; }
    exit 3
  fi
done
bar1free=$(nvidia-smi -q -d MEMORY 2>/dev/null | sed -n '/BAR1/,/Free/p' | sed -n 's/.*Free *: *\([0-9]*\) *MiB.*/\1/p' | head -1)
if [ -z "$bar1free" ] || [ "$bar1free" -lt 128 ]; then
  echo "$(date '+%F %T') hold $H: rain BAR1 Free ${bar1free:-unread} MiB < 128 MiB: not started" | tee -a "$R/refused.txt"
  exit 3
fi
# section 8: the UD path MTU (both GIN ports' active_mtu, read only) at least 2048 and the same, else no hold
m0=$(bash -c "$MTU_Q" _ mlx5_1); m1=$(sunny_sh "$MTU_Q" mlx5_0 2>/dev/null)
case "$m0$m1" in *[!0-9]*) m0=""; m1="" ;; esac
if [ -z "$m0" ] || [ -z "$m1" ] || [ "$m0" -lt 2048 ] || [ "$m0" != "$m1" ]; then
  echo "$(date '+%F %T') hold $H: active_mtu rain=${m0:-unread} sunny=${m1:-unread}: below 2048 or different, not started" | tee -a "$R/STOP_mtu"
  exit 3
fi
snap() {
  echo "== $1 $(date '+%F %T')"
  nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader 2>/dev/null | sed 's/^/rain gpu: /'
  ssh -n "$SUNNY_SSH" "nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader" 2>/dev/null | sed 's/^/sunny gpu: /'
  nvidia-smi --query-gpu=index,name,compute_mode --format=csv,noheader 2>/dev/null | sed 's/^/rain gpu mode: /'
  ssh -n "$SUNNY_SSH" "nvidia-smi --query-gpu=index,name,compute_mode --format=csv,noheader" 2>/dev/null | sed 's/^/sunny gpu mode: /'
  nvidia-smi -q -d MEMORY 2>/dev/null | sed -n '/BAR1/,/Free/p' | tr -s ' ' | tr '\n' ' ' | sed 's/^/rain bar1: /'; echo
  ssh -n "$SUNNY_SSH" "nvidia-smi -q -d MEMORY | sed -n '/BAR1/,/Free/p'" 2>/dev/null | tr -s ' ' | tr '\n' ' ' | sed 's/^/sunny bar1: /'; echo
  echo "rain MemAvailable MiB: $(awk '/^MemAvailable:/{print int($2/1024)}' /proc/meminfo)"
  echo "sunny MemAvailable MiB: $(ssh -n "$SUNNY_SSH" "awk '/^MemAvailable:/{print int(\$2/1024)}' /proc/meminfo" 2>/dev/null)"
  echo "rain active_mtu: $(bash -c "$MTU_Q" _ mlx5_1), sunny active_mtu: $(sunny_sh "$MTU_Q" mlx5_0 2>/dev/null)"
  echo "rain nvrm mapping-failure lines: $(sudo -n dmesg 2>/dev/null | grep -ciE 'NVRM.*(dmaAllocMapping|alloc VA)')"
  sudo -n dmesg 2>/dev/null | grep -i mlx5 > "$R/mlx5_$1_rain.txt"
  ssh -n "$SUNNY_SSH" "sudo -n dmesg 2>/dev/null | grep -i mlx5" > "$R/mlx5_$1_sunny.txt" 2>/dev/null
  echo "rain mlx5 dmesg lines: $(wc -l < "$R/mlx5_$1_rain.txt")"
  echo "sunny mlx5 dmesg lines: $(wc -l < "$R/mlx5_$1_sunny.txt")"
  echo "rain mlx5 cmd_err lines: $(eval "cat $R/mlx5_$1_rain.txt | $CMDERR")"
  echo "sunny mlx5 cmd_err lines: $(eval "cat $R/mlx5_$1_sunny.txt | $CMDERR")"
  bash "$FW" "$1" > "$R/fwcmd_$1.txt" 2>&1
  echo "rain fwcmd failed sum: $(awk '{for(i=1;i<=NF;i++) if($i ~ /^failed=|^failed_mbox_status=/){split($i,a,"="); s+=a[2]}} END{print s+0}' "$R/fwcmd_$1.txt")"
  echo "rain fwcmd QUERY_QP n: $(awk '$1=="QUERY_QP"{for(i=1;i<=NF;i++) if($i ~ /^n=/){split($i,a,"="); print a[2]}}' "$R/fwcmd_$1.txt")"
}
fwread() {
  bash "$FW" "$1" 2>/dev/null | awk '{for(i=1;i<=NF;i++){ if($i ~ /^failed=|^failed_mbox_status=/){split($i,a,"="); s+=a[2]}
    if($1=="QUERY_QP" && $i ~ /^n=/){split($i,b,"="); q=b[2]} }} END{print s+0, q+0}'
}
n0=$(left)
[ "$n0" -eq 0 ] || { echo "$(date '+%F %T') hold $H: $n0 test process(es) present before the hold" | tee -a "$R/STOP_left"; exit 3; }
bash -c "$OWNCLEAN"; sunny_sh "$OWNCLEAN"
SECONDS=0
snap "before-$HT" | tee "$R/snap_before-$HT.txt"
read -r FW0 QQ < <(fwread "start-$HT")
fits() {
  if [ $((SECONDS + $1)) -gt 840 ]; then echo "$(date '+%F %T') hold $H: skipped $2 (elapsed ${SECONDS}s + bound $1s > 840s)" | tee -a "$R/skipped.txt"; return 1; fi
  return 0
}
stopped() { ls "$R"/STOP_* > /dev/null 2>&1; }
mval() { sed -n "s/.*\b$2=\([^ ]*\).*/\1/p" "$1" 2>/dev/null | head -1; }
gc_after_trial() {  # gc_after_trial <what> <meta> <cell>: section 8's gin-control stops for one restore trial
  local what=$1 m=$2 cell=$3 stem b a nd st f envs sw=0 chk lstop lqp
  [ -f "$m" ] || return 0
  stem=${m%_meta.txt}
  envs="$(mval "$m" r0_env)$(mval "$m" r1_env)$(mval "$m" r2_env)$(mval "$m" r3_env)$(mval "$m" spare_env)"
  case "$envs" in *TEST_QP_ERR*|*TEST_DROP_UD*|*TEST_CREDIT_STALL*) sw=1 ;; esac
  if [ "$(mval "$m" ctrl)" = rdma ] && [ "$(mval "$m" launcher_ready)" = 1 ]; then
    for nd in rain sunny; do
      b=$(mval "$m" "launcher_before_$nd"); a=$(mval "$m" "launcher_after_$nd")
      if [ "${b%%,alive*}" != "${a%%,alive*}" ] || ! echo "$a" | grep -q 'alive=1'; then
        echo "$(date '+%F %T') hold $H: $what: the $nd launcher ended or changed during the trial (before ${b%%,ready*}, after ${a%%,ready*})" | tee -a "$R/STOP_launcher"
      fi
    done
    # both STOP_launcher forms and the launcher QP loss: the scorer's own rule (rows_gc.py --stops; REVIEW_TEST B4)
    chk=$(python3 "$D/rows_gc.py" --stops "$stem" 2>/dev/null)
    lstop=$(echo "$chk" | sed -n 's/.*\bla_stop_n=\([0-9]*\).*/\1/p'); lqp=$(echo "$chk" | sed -n 's/.*\bla_qp_err_n=\([0-9]*\).*/\1/p')
    if [ -z "$chk" ]; then
      echo "$(date '+%F %T') hold $H: $what: the launcher slices could not be read (rows_gc.py --stops)" | tee -a "$R/STOP_launcher"
    fi
    if [ "${lstop:-0}" -gt 0 ]; then
      echo "$(date '+%F %T') hold $H: $what: $lstop launcher line(s) (STOP_launcher) or (STOP_launcher: ...)" | tee -a "$R/STOP_launcher"
    fi
    if [ "$sw" = 0 ] && [ "${lqp:-0}" -gt 0 ]; then
      echo "$(date '+%F %T') hold $H: $what: $lqp launcher QP loss line(s) outside the test-switch cells (section 8)" | tee -a "$R/STOP_launcher"
    fi
  fi
  st=$(mval "$m" left_stopped); f=$(mval "$m" left_fdhold)
  if [ "${st:-0}" != 0 ] || [ "${f:-0}" != 0 ]; then
    echo "$(date '+%F %T') hold $H: $what: a stopped process (${st:-0}) or a gin_fdhold child (${f:-0}) left after the trial" | tee -a "$R/STOP_left"
  fi
  if [ "$cell" != gc4_credit_stall ]; then
    for nd in rain sunny; do
      b=$(mval "$m" "rnr_before_$nd"); a=$(mval "$m" "rnr_after_$nd")
      case "$b$a" in *[!0-9]*|"") continue ;; esac
      [ "$a" -gt "$b" ] && echo "$(date '+%F %T') hold $H: $what: $nd rnr_nak_retry_err grew by $((a - b)) ($b -> $a; a port counter, other users of the port count too) outside the credit cell, trial wall $(mval "$m" wall_s) s" | tee -a "$R/STOP_rnr"
    done
  fi
  for nd in rain sunny; do  # REVIEW_TEST nit 20: the port's active_mtu after the trial must be the one before
    b=$(mval "$m" "active_mtu_$nd"); a=$(mval "$m" "active_mtu_after_$nd")
    [ "$b" != "$a" ] && echo "$(date '+%F %T') hold $H: $what: $nd active_mtu ${b:-unread} before, ${a:-unread} after the trial" | tee -a "$R/STOP_mtu"
  done
  # TODO(phase2): the library's control summary carries async=<n> (record and liveness-READ QPs); the test-switch cells apart
  if [ "$sw" = 0 ] && cat "${stem}"_*.log 2>/dev/null | grep -qE 'GIN/RC: rank [0-9]+: control summary .*\basync=[1-9]'; then
    echo "$(date '+%F %T') hold $H: $what: an asynchronous event of a control QP outside the test-switch cells" | tee -a "$R/STOP_async"
  fi
  return 0
}
after_trial() {  # hold_mi.sh's per-trial stops: kv error keys, a refused Resume where the restore is expected, firmware, QUERY_QP
  local what=$1 f fw qq refuse_ok=${3:-1} cap=${4:-$QCAP}
  for f in $2; do
    [ -f "$f" ] || continue
    case "$f" in
      *_spare.kv|*_spare_2nd.kv) grep -q 'watchdog=1' "$f" && echo "$(date '+%F %T') $what: $(basename "$f") ended at its watchdog" >> "$R/spare_wait.txt"; continue ;;
    esac
    if grep -qE 'cuda_error=|watchdog=1|nccl_error=' "$f"; then
      echo "$(date '+%F %T') hold $H: $what: an error key in $(basename "$f"); no further trial" | tee -a "$R/STOP_nic"; break
    fi
    if [ "$refuse_ok" = 0 ] && grep -q 'xchg=refused' "$f"; then
      echo "$(date '+%F %T') hold $H: $what: Resume refused in a cell that expects the restore ($(basename "$f")); no further trial" | tee -a "$R/STOP_nic"; break
    fi
  done
  read -r fw qq < <(fwread "after-$what")
  [ "$fw" -gt "$FW0" ] && echo "$(date '+%F %T') hold $H: firmware-command failures grew after $what ($FW0 -> $fw)" | tee -a "$R/STOP_mlx5"
  if [ $((qq - QQ)) -gt "$cap" ]; then
    if [ "$PILOT" = 1 ]; then echo "$(date '+%F %T') $what: rain QUERY_QP +$((qq - QQ)) > $cap" >> "$R/qp_over.txt"
    else echo "$(date '+%F %T') hold $H: $what: rain QUERY_QP +$((qq - QQ)) > cap $cap" | tee -a "$R/STOP_mlx5"; fi
  fi
  QQ=$qq
}
newdir() { if ! ls "$R/$1"/*_meta.txt >/dev/null 2>&1; then echo "$R/$1"; return; fi; local k=2; while [ -e "$R/$1_run$k" ]; do k=$((k+1)); done; echo "$R/$1_run$k"; }
# json_hold <hold>: one line per cell entry: cell build kind n driver bound launcher_env(+-joined) env...
json_hold() {
  python3 - "$CELLS" "$MCELLS" "$1" <<'PY'
import json, sys
c = json.load(open(sys.argv[1])); m = json.load(open(sys.argv[2])); h = sys.argv[3]
out = []
if h.startswith("RG-"):
    _, b, mh = h.split("-", 2)
    if b not in c["regression"]["builds"] or mh not in c["regression"]["holds"]:
        sys.exit("unknown regression hold %s" % h)
    for e in m["holds"][mh]:
        bound = 150 if e["cell"].startswith("mi4_train_") else 60
        out.append((e["cell"], b, e["kind"], e["n"], e.get("driver", ""), bound, {}, e.get("env", {})))
elif h in c["holds"]:
    for x in c["holds"][h]:
        e = c["cells"].get(x["key"]) or c["pilot_cells"][x["key"]]
        env = dict(e.get("env", {})); env.update(x.get("env", {}))
        out.append((e["cell"], e["build"], e["kind"], x.get("n", e["n"]), e.get("driver", ""), e.get("bound_s", 60),
                    e.get("launcher_env", {}), env))
else:
    sys.exit("unknown hold %s" % h)
les = {json.dumps(o[6], sort_keys=True) for o in out}
if len(les) > 1:
    sys.exit("hold %s mixes launcher_env values" % h)
for cell, b, kind, n, drv, bound, le, env in out:
    f = [cell, b, kind, str(n), str(bound), "+".join("%s=%s" % kv for kv in sorted(le.items())) or "-"]
    f += ["DRIVER=%s" % drv] + ["%s=%s" % kv for kv in env.items()]
    print("\t".join(f))
PY
}
LA_STARTED=0
la_start() {  # la_start <launcher_env, +-joined or ->: one launcher per node for this hold (EXPERIMENT 5)
  local le=$1 nd args=()
  [ "$le" != - ] && IFS=+ read -r -a args <<< "$le"
  for nd in rain sunny; do
    if ! bash "$D/launcher_gc.sh" start "$nd" "$R/launcher" "$HT" "${args[@]}"; then
      echo "$(date '+%F %T') hold $H: the $nd launcher did not get ready; both are stopped and the hold does not start" | tee -a "$R/STOP_launcher"
      for nd in rain sunny; do bash "$D/launcher_gc.sh" stop "$nd" "$R/launcher" "$HT"; done  # REVIEW_TEST fix 5
      return 1
    fi
  done
  export LAUNCHER_REC_RAIN=$R/launcher/la_${HT}_rain.rec LAUNCHER_REC_SUNNY=$R/launcher/la_${HT}_sunny.rec
  LA_STARTED=1
}
la_stop() {
  [ "$LA_STARTED" = 1 ] || return 0
  local nd lg n
  for nd in rain sunny; do bash "$D/launcher_gc.sh" stop "$nd" "$R/launcher" "$HT"; done
  LA_STARTED=0
  for nd in rain sunny; do  # the lines after the last trial's end marker belong to no trial slice: their STOP lines here
    lg=$R/launcher/la_${HT}_$nd.log
    [ -f "$lg" ] || continue
    n=$(tac "$lg" | sed '/GINLA mark trial_end /q' | grep -c '(STOP_launcher')
    [ "$n" -gt 0 ] && echo "$(date '+%F %T') hold $H: $nd launcher: $n line(s) (STOP_launcher) after the last trial" | tee -a "$R/STOP_launcher"
  done
  return 0
}
do_json_hold() {
  local line cell build kind n bound le ldir rok first=1 lines
  local -a f envs
  lines=$(json_hold "$1") || { echo "hold $1: no cell list" >&2; return 1; }
  while IFS= read -r line <&3; do
    IFS=$'\t' read -r -a f <<< "$line"
    cell=${f[0]}; build=${f[1]}; kind=${f[2]}; n=${f[3]}; bound=${f[4]}; le=${f[5]}; envs=("${f[@]:6}")
    if [ "$first" = 1 ]; then
      first=0
      if printf '%s\n' "$lines" | cut -f2 | grep -qxE 'gc|gcp'; then la_start "$le" || return 1; fi
    fi
    case "$kind" in reg) ldir=$R/reg ;; *) ldir=$R/raw ;; esac
    mkdir -p "$ldir"
    for ((k = 1; k <= n; k++)); do
      if [ "$kind" = rs ]; then stem="${cell}_${build}_n$k"; else stem="${cell}_n$k"; fi
      if [ -f "$ldir/${stem}_meta.txt" ]; then
        echo "$(date '+%F %T') hold $H: ${cell}@${build}_n$k already done ($(basename "$ldir")/${stem}_meta.txt exists)"
        continue
      fi
      stopped && { echo "skipped ${cell}@${build}_n$k: STOP" >> "$R/skipped.txt"; break; }
      if [ "$kind" = rs ]; then
        case "$cell" in mi4_train_*) [ "$bound" -lt "$TRAIN_BOUND" ] && bound=$TRAIN_BOUND ;; *) [ "$bound" -lt "$TRIAL_BOUND" ] && bound=$TRIAL_BOUND ;; esac
        fits "$bound" "${cell}@${build}_n$k" || break
      else fits 150 "${cell}_n$k" || break; fi
      bash "$D/cells_gc.sh" "$ldir" "$cell" "$build" "$kind" 1 "$k" "${envs[@]}" < /dev/null
      case "$cell" in mi4_refuse_*|rs4_refuse_*|*rstgap*) rok=1 ;; *) rok=$([ "$kind" = rs ] && echo 0 || echo 1) ;; esac
      if [ "$kind" = rs ]; then
        after_trial "${cell}_${build}_n$k" "$ldir/${cell}_${build}_n${k}_*.kv" "$rok"
        gc_after_trial "${cell}_${build}_n$k" "$ldir/${cell}_${build}_n${k}_meta.txt" "$cell"
      else after_trial "${cell}_n$k" "$ldir/${cell}_n${k}_r*.kv" 1 "$QCAP_REG"; fi
    done
  done 3< <(printf '%s\n' "$lines")
  la_stop
}
cost_run() {  # cost_run <cell> <tag> <logdir>
  local cell=$1 tag=$2 dir=$3 f bad=""
  stopped && { echo "skipped ${cell}_$tag: STOP" >> "$R/skipped.txt"; return 0; }
  fits 90 "${cell}_$tag" || return 0
  bash "$D/run_cost_gc.sh" "$cell" "$tag" "$dir"
  if [ "$?" = 6 ]; then  # REVIEW_TEST nit 13: the cost run's launchers not ready is a launcher stop, not a NIC one
    echo "$(date '+%F %T') hold $H: ${cell}_$tag: the launchers were not ready; no further run" | tee -a "$R/STOP_launcher"
    after_trial "${cell}_$tag" ""; return 0
  fi
  for f in "$dir/${cell}_${tag}_r0.kv" "$dir/${cell}_${tag}_r1.kv"; do
    [ -f "$f" ] || { bad="missing $(basename "$f")"; break; }
    if grep -qE 'nccl_error=|cuda_error=|watchdog|man_error=' "$f" || ! grep -q '^exit=0$' "$f"; then
      bad="$(basename "$f"): $(grep -hoE 'nccl_error=[^ ]*|cuda_error=[^ ]*|man_error=[^ ]*|exit=[0-9]+' "$f" | tr '\n' ' ')"; break
    fi
  done
  [ -n "$bad" ] && echo "$(date '+%F %T') hold $H: ${cell}_$tag error ($bad); no further run" | tee -a "$R/STOP_nic"
  local lft; lft=$(sed -n 's/.* left=\([0-9]*\) .*/\1/p' "$dir/${cell}_${tag}_meta.txt" 2>/dev/null)
  [ -n "$lft" ] && [ "$lft" -gt 0 ] && echo "$(date '+%F %T') hold $H: ${cell}_$tag left $lft" | tee -a "$R/STOP_left"
  after_trial "${cell}_$tag" ""
}
cost_family() {  # cost_family <family> <node> <dir> <rounds> [metric]
  local fam=$1 node=$2 dir=$3 rounds=$4 only=${5:-} k m a arms
  local -a metrics armlist
  read -r -a metrics <<< "$(python3 -c 'import json,sys; print(" ".join(json.load(open(sys.argv[1]))["cost"]["families"][sys.argv[2]]["metrics"]))' "$CELLS" "$fam")"
  if [ -n "$only" ]; then
    case " ${metrics[*]} " in *" $only "*) metrics=("$only") ;; *) echo "metric $only is not in family $fam" >&2; return 1 ;; esac
  fi
  read -r -a armlist <<< "$(python3 -c 'import json,sys; print(" ".join(json.load(open(sys.argv[1]))["cost"]["families"][sys.argv[2]]["arms"]))' "$CELLS" "$fam")"
  for ((k = 1; k <= rounds; k++)); do
    for m in "${metrics[@]}"; do
      if [ $((k % 2)) = 1 ]; then arms="${armlist[*]}"; else arms=$(printf '%s\n' "${armlist[@]}" | tac | tr '\n' ' '); fi
      for a in $arms; do cost_run "cost_${m}_${a}_${node}" "k$k" "$dir"; done
    done
  done
}
case "$H" in
  C[0-9]*|P[0-9]*|RG-*) do_json_hold "$H" ;;
  COSTPILOT-*)
    node=${H#COSTPILOT-}; node=${node%%-*}
    case "$node" in rain|sunny) ;; *) echo "COSTPILOT-<rain|sunny>" >&2; exit 2 ;; esac
    d=$(newdir "costpilot_$node"); mkdir -p "$d"
    cost_family probe "$node" "$d" 1 ;;
  COST-*)
    rest=${H#COST-}; fam=${rest%%-*}; rest=${rest#*-}; node=${rest%%-*}; met=""
    case "$rest" in *-*) met=${rest#*-}; met=${met%%-*} ;; esac
    case "$met" in lat4k|lat256k|bw256k|"") ;; *) met="" ;; esac
    case "$fam" in probe) ;; *) echo "COST-probe-<rain|sunny>[-<metric>]" >&2; exit 2 ;; esac
    case "$node" in rain|sunny) ;; *) echo "COST-probe-<rain|sunny>[-<metric>]" >&2; exit 2 ;; esac
    d=$(newdir "cost_${fam}_$node${met:+_$met}"); mkdir -p "$d"
    cost_family "$fam" "$node" "$d" 6 "$met" ;;
  *) echo "unknown hold $H" >&2; exit 2 ;;
esac
la_stop
snap "after-$HT" | tee "$R/snap_after-$HT.txt"
for node in rain sunny; do
  diff <(sort "$R/mlx5_before-${HT}_$node.txt") <(sort "$R/mlx5_after-${HT}_$node.txt") | grep '^>' | sed "s/^> /$node: /"
done > "$R/mlx5_new_$HT.txt"
echo "new mlx5 kernel lines in hold $H: $(wc -l < "$R/mlx5_new_$HT.txt")"; cat "$R/mlx5_new_$HT.txt"
b=$(grep -h "cmd_err lines\|fwcmd failed sum" "$R/snap_before-$HT.txt" | awk -F': ' '{s+=$2} END{print s+0}')
a=$(grep -h "cmd_err lines\|fwcmd failed sum" "$R/snap_after-$HT.txt" | awk -F': ' '{s+=$2} END{print s+0}')
[ "$a" -gt "$b" ] && echo "$(date '+%F %T') hold $H: mlx5 command errors or firmware-command failures grew ($b -> $a)" | tee -a "$R/STOP_mlx5"
cudafail=$(find "$R" \( -name '*.kv' -o -name '*.log' \) -newer "$R/snap_before-$HT.txt" \
  -exec grep -liE 'illegal address|illegal memory access|unspecified launch failure|cuda_error=' {} + 2>/dev/null | sort -u)
[ -n "$cudafail" ] && echo "$(date '+%F %T') hold $H: CUDA fault in: $(echo "$cudafail" | tr '\n' ' ')" | tee -a "$R/STOP_cuda"
n1=$(left)
[ "$n1" -eq 0 ] || echo "$(date '+%F %T') hold $H: $n1 test process(es) left after the hold" | tee -a "$R/STOP_left"
[ "$n1" -eq 0 ] && { bash -c "$OWNCLEAN"; sunny_sh "$OWNCLEAN"; }
echo "hold $H elapsed ${SECONDS}s"
exit 0
