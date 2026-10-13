#!/usr/bin/env bash
# hold_mi.sh - one hold of gin-mirror's test branch (../../EXPERIMENT.md 7, 8; n and caps are DRAFT, frozen at the
# pre-registration). gin-restore's hold_rs.sh (copied and then changed): the main session runs it inside
# ../../../../common/cluster_run.sh (tag mi-<hold>, -w 10800) under timeout -s KILL 880, through chain_mi.sh. Before and
# after the hold: the GPU users and compute mode of both nodes, both GPUs' BAR1, rain's NVRM mapping-failure lines, the
# mlx5 kernel lines, rain's firmware-command counters. Stops (section 8): a new mlx5 command-error line or a growth of the
# firmware-command failures writes STOP_mlx5; a CUDA fault STOP_cuda; a test process left behind STOP_left; an error key
# in a trial's kv STOP_nic; a trial whose rain QUERY_QP grew by more than the cap STOP_mlx5 (a pilot hold: a line in
# qp_over.txt only); run_mi.sh's exit 5 (host memory short) STOP_mem. No further hold runs while a STOP file exists. Start
# gate: rain's BAR1 Free below 128 MiB -> the hold does not start (refused.txt). Processes are never killed here: each is
# bounded by its own timeout; the leftover check is a read-only count of this study's driver names (gin_mi, gin_mi_nomacro)
# and of the cost runs' and trials' own /tmp paths (gin_ts2_mi and gin_mr are counted by those paths, not by name).
#
# What is new against hold_rs.sh: RS_SET is required (rs_set_mi.sh); the holds are cells_mi.json's (P1-P3, G1, G3, T1, T2,
# G2, R1-R3 and COST-mirror-<node>); the per-trial stop checks add STOP_mem (run_mi.sh exit 5); the start-check also reads each
# node's MemAvailable (run_mi.sh does the per-trial check; here only the hold's own leftover and BAR1 gates).
#
# usage: hold_mi.sh <resultsdir> <hold>
#   P1, P2, P3             the pilot holds (never scored; a results folder of their own): the 4 KiB cells and refusals,
#                          the training cells, the regression
#   G1                     the 4 KiB overwrite restore cells and their mirror-off controls
#   G3                     the segment, interval, pull and overflow cells
#   T1                     mi4_train_none + mi4_train_kill3 (the training split, section 8: 465-510 s)
#   T2                     mi4_train_kill2_kill3 (the second-death training cell, 160-175 s)
#   G2                     the refusal cells (mirror+checksum, one rank's mirror off, S/L mismatch)
#   R1                     the regression cells of gin-remaining's run_mr_hr.sh (mirror off)
#   R2                     gin-restore's restore cells at @mi with the mirror off (their names and env)
#   R3                     gin-restore's refusal cells (mirror off) and the mirror-on regression (rs4_none_mion, rs4_kill3_mion)
#   COST-mirror-<rain|sunny>[-<metric>][-<tag>]   the mirror cost family on the named receiving node, all its metrics or
#                          the one named (4 arms x 5 metrics x 6 rounds = 120 runs; usually run one metric per hold)
#   COSTPILOT-<rain|sunny> pilot: one round (k=1) of the mirror cost family
# env: SUNNY_SSH (required), RS_SET (required), RS_QUERY_CAP (50000: rain's QUERY_QP growth per trial of the restore cells
#   and the cost runs; the mirror context adds a QP n + 1 bundle, EXPERIMENT.md 8), RS_QUERY_CAP_REG (150000: the regression
#   cells), RS_TRIAL_BOUND_S (60: the 4 KiB restore trials), RS_TRAIN_BOUND_S (150: the training trials; section 8's draft
#   120 s plus a training trial that falls back, whose spare waits its 120 s, about 125-130 s).
# Resumable: a cell trial whose <stem>_meta.txt exists in its logdir is skipped ("already done"); a cost hold's repeat goes
# to a new _run<k> folder.
set -u
R=${1:?resultsdir}; H=${2:?hold}
D=$(cd "$(dirname "$0")" && pwd)
SUNNY_SSH=${SUNNY_SSH:?set SUNNY_SSH}
export SUNNY_SSH
RS_SET=${RS_SET:-}
. "$D/rs_set_mi.sh"
rs_set_check || exit 2
export RS_SET
CELLS=$D/cells_mi.json
FW=$D/../../../scripts/ts1/fwcmd_snapshot.sh
[ -f "$FW" ] || { echo "missing $FW" >&2; exit 2; }
QCAP=${RS_QUERY_CAP:-50000}
QCAP_REG=${RS_QUERY_CAP_REG:-150000}
TRIAL_BOUND=${RS_TRIAL_BOUND_S:-60}
TRAIN_BOUND=${RS_TRAIN_BOUND_S:-150}
case "$H" in P*|COSTPILOT-*) PILOT=1 ;; *) PILOT=0 ;; esac
CMDERR='grep -i mlx5 | grep -iE "cmd|command" | grep -icE "failed|timeout|leak"'
mkdir -p "$R"
HT=$H
if [ -e "$R/snap_before-$HT.txt" ]; then k=2; while [ -e "$R/snap_before-$H-r$k.txt" ]; do k=$((k + 1)); done; HT=$H-r$k; fi
echo "hold $H (files tagged $HT) rs_set=$RS_SET"
left() { { pgrep -x gin_mi; pgrep -x gin_mi_nomacro; pgrep -f '[/]tmp/mi_cost'; pgrep -f '[/]tmp/mi_rt'
           ssh -n "$SUNNY_SSH" "pgrep -x gin_mi; pgrep -x gin_mi_nomacro; pgrep -f '[/]tmp/mi_cost'; pgrep -f '[/]tmp/mi_rt'"; } 2>/dev/null | wc -l; }
OWNCLEAN='find /tmp -maxdepth 1 -user "$(id -un)" \( -name "mi_rt_*" -o -name "mi_rt.*" -o -name "mi_cost_*" -o -name "mi_cost.*" \) -exec rm -rf {} + 2>/dev/null; true'
for f in STOP_mlx5 STOP_cuda STOP_left STOP_nic STOP_mem; do
  if [ -e "$R/$f" ]; then
    echo "$R/$f present: no hold runs" >&2
    [ "$(left)" -eq 0 ] && { bash -c "$OWNCLEAN"; ssh -n "$SUNNY_SSH" "$OWNCLEAN"; }
    exit 3
  fi
done
bar1free=$(nvidia-smi -q -d MEMORY 2>/dev/null | sed -n '/BAR1/,/Free/p' | sed -n 's/.*Free *: *\([0-9]*\) *MiB.*/\1/p' | head -1)
if [ -z "$bar1free" ] || [ "$bar1free" -lt 128 ]; then
  echo "$(date '+%F %T') hold $H: rain BAR1 Free ${bar1free:-unread} MiB < 128 MiB: not started" | tee -a "$R/refused.txt"
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
  echo "rain nvrm mapping-failure lines: $(sudo -n dmesg 2>/dev/null | grep -ciE 'NVRM.*(dmaAllocMapping|alloc VA)')"
  sudo -n dmesg 2>/dev/null | grep -i mlx5 > "$R/mlx5_$1_rain.txt"
  ssh -n "$SUNNY_SSH" "sudo -n dmesg 2>/dev/null | grep -i mlx5" > "$R/mlx5_$1_sunny.txt"
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
bash -c "$OWNCLEAN"; ssh -n "$SUNNY_SSH" "$OWNCLEAN"
SECONDS=0
snap "before-$HT" | tee "$R/snap_before-$HT.txt"
read -r FW0 QQ < <(fwread "start-$HT")
fits() {
  if [ $((SECONDS + $1)) -gt 840 ]; then echo "$(date '+%F %T') hold $H: skipped $2 (elapsed ${SECONDS}s + bound $1s > 840s)" | tee -a "$R/skipped.txt"; return 1; fi
  return 0
}
stopped() { ls "$R"/STOP_* > /dev/null 2>&1; }
after_trial() {  # after_trial <what> <kv glob> [refusal-expected 0|1] [QUERY_QP cap]: the per-trial stop checks. A spare's
                # kv (spare, spare_2nd, neg) is not checked for errors (a spare never activated waits to its bound)
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
json_hold() {
  python3 - "$CELLS" "$1" <<'PY'
import json, sys
for e in json.load(open(sys.argv[1]))["holds"].get(sys.argv[2], []):
    env = ["DRIVER=%s" % e["driver"]] + ["%s=%s" % kv for kv in e.get("env", {}).items()]
    print("\t".join([e["cell"], e["build"], e["kind"], str(e["n"])] + env))
PY
}
do_json_hold() {
  local line cell build kind n ldir rok bound
  local -a f envs
  while IFS= read -r line <&3; do
    IFS=$'\t' read -r -a f <<< "$line"
    cell=${f[0]}; build=${f[1]}; kind=${f[2]}; n=${f[3]}; envs=("${f[@]:4}")
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
        case "$cell" in mi4_train_*) bound=$TRAIN_BOUND ;; *) bound=$TRIAL_BOUND ;; esac
        fits "$bound" "${cell}@${build}_n$k" || break
      else fits 150 "${cell}_n$k" || break; fi
      bash "$D/cells_mi.sh" "$ldir" "$cell" "$build" "$kind" 1 "$k" "${envs[@]}" < /dev/null
      case "$cell" in mi4_refuse_*|rs4_refuse_*) rok=1 ;; *) rok=$([ "$kind" = rs ] && echo 0 || echo 1) ;; esac
      if [ "$kind" = rs ]; then after_trial "${cell}_${build}_n$k" "$ldir/${cell}_${build}_n${k}_*.kv" "$rok"
      else after_trial "${cell}_n$k" "$ldir/${cell}_n${k}_r*.kv" 1 "$QCAP_REG"; fi
    done
  done 3< <(json_hold "$1")
}
cost_run() {  # cost_run <cell> <tag> <logdir>
  local cell=$1 tag=$2 dir=$3 f bad=""
  stopped && { echo "skipped ${cell}_$tag: STOP" >> "$R/skipped.txt"; return 0; }
  fits 90 "${cell}_$tag" || return 0
  bash "$D/run_cost_mi.sh" "$cell" "$tag" "$dir"
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
  P1|P2|P3|G1|G3|T1|T2|G2|R1|R2|R3) do_json_hold "$H" ;;
  COSTPILOT-*)
    node=${H#COSTPILOT-}; node=${node%%-*}
    case "$node" in rain|sunny) ;; *) echo "COSTPILOT-<rain|sunny>" >&2; exit 2 ;; esac
    d=$(newdir "costpilot_$node"); mkdir -p "$d"
    cost_family mirror "$node" "$d" 1 ;;
  COST-*)
    rest=${H#COST-}; fam=${rest%%-*}; rest=${rest#*-}; node=${rest%%-*}; met=""
    case "$rest" in *-*) met=${rest#*-}; met=${met%%-*} ;; esac
    case "$met" in lat4k|lat256k|bw256k|lat2m|bw2m|"") ;; *) met="" ;; esac
    case "$fam" in mirror) ;; *) echo "COST-mirror-<rain|sunny>[-<metric>][-<tag>]" >&2; exit 2 ;; esac
    case "$node" in rain|sunny) ;; *) echo "COST-mirror-<rain|sunny>[-<metric>][-<tag>]" >&2; exit 2 ;; esac
    d=$(newdir "cost_${fam}_$node${met:+_$met}"); mkdir -p "$d"
    cost_family "$fam" "$node" "$d" 6 "$met" ;;
  *) echo "unknown hold $H" >&2; exit 2 ;;
esac
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
[ "$n1" -eq 0 ] && { bash -c "$OWNCLEAN"; ssh -n "$SUNNY_SSH" "$OWNCLEAN"; }
echo "hold $H elapsed ${SECONDS}s"
exit 0
