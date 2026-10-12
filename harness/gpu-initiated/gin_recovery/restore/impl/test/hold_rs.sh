#!/usr/bin/env bash
# hold_rs.sh - one hold of gin-restore work package 10 (EXPERIMENT.md 7, 8; DRAFT until the pilot freezes n). The main session
# runs it inside ../../../../common/cluster_run.sh (tag rs-<hold>, -w 10800) under timeout -s KILL 880, through chain_rs.sh.
# Modeled on ../../feas/hold_feas.sh and ../../../remaining/hold.sh. Before and after the hold: the GPU users and compute
# mode of both nodes, both GPUs' BAR1, rain's NVRM mapping-failure lines, the mlx5 kernel lines, rain's firmware-command
# counters (debugfs, read only). Stops (EXPERIMENT.md 8): a new mlx5 command-error line or a growth of the firmware-command
# failures writes STOP_mlx5; a CUDA fault STOP_cuda; a test process left behind STOP_left; an error key in a trial's kv
# STOP_nic; a trial whose rain QUERY_QP count grew by more than RS_QUERY_CAP (draft 20 000, rain's leaking command slots)
# STOP_mlx5 in a main hold (in a pilot hold: a line in qp_over.txt only, the pilot measures it). No further hold runs while
# a STOP file exists (this script refuses). Start gate (section 8): rain's BAR1 Free below 128 MiB -> the hold does not start
# (refused.txt, no STOP file; retry later). Processes are never killed here: each is bounded by its own timeout; the
# leftover check is a read-only count of this study's own program names (gin_rs, gin_rs_hk) and of the cost runs' per-run
# files (gin_ts2 and gin_mr are also other studies' names). This user's own leftover files of a cut hold are deleted.
#
# usage: hold_rs.sh <resultsdir> <hold>
#   P1, P2, P3, G1, G2, R1     the cells_rs.json holds (P*: pilot, never scored; run them into a results folder of their own;
#                              P3: the spare's strace and the two negative replays)
#   COST-<family>-<rain|sunny>[-<metric>][-<tag>]   one cost family (log | ffbranch, cells_rs.json "cost") on the named
#                              receiving node, all its metrics or the one named (the log family runs one metric per hold:
#                              5 arms x 6 rounds = 30 runs): for k = 1-6 the arms back to back with the first arm alternating
#                              by k (9.15.6's interleave), into cost_<family>_<node>[_<metric>]/ (a repeat: ..._run<k>/)
#   COSTPILOT-<rain|sunny>     pilot: one round (k=1) of every family, into costpilot_<node>/
# env: SUNNY_SSH (required), RS_SET (empty: today's deployment under ~/rs-bundle; a name: the set ~/rs-bundle/<RS_SET>/,
#   passed to the runners), RS_QUERY_CAP (20000: rain's QUERY_QP growth per trial of the restore cells and the cost runs),
#   RS_QUERY_CAP_REG (150000: the same for the regression cells, kind reg: gin-remaining's run_mr_hr.sh trials of about
#   17 s grew it by 90 000-108 000 in the pilot P2, results/20261013_pilot/qp_over.txt, while the restore cells stayed
#   under 20 000), RS_TRIAL_BOUND_S (300: the bound `fits` assumes for one restore trial, kind rs; the pilot fixes it from
#   the measured wall times)
# Resumable (2026-10-13): a cell trial whose <stem>_meta.txt already exists in its logdir is skipped with an "already done"
# line, so the same hold run again into the same results folder runs only the trials still missing (the cost holds are not
# resumed: a repeat goes to a new _run<k> folder as before). A hold run again keeps the earlier run's files: its snapshot,
# mlx5 and firmware-command files get the tag <hold>-r<k> (k = 2, 3, ...).
set -u
R=${1:?resultsdir}; H=${2:?hold}
D=$(cd "$(dirname "$0")" && pwd)
SUNNY_SSH=${SUNNY_SSH:?set SUNNY_SSH}
export SUNNY_SSH
RS_SET=${RS_SET:-}
export RS_SET
CELLS=$D/cells_rs.json
FW=$D/../../../scripts/ts1/fwcmd_snapshot.sh
[ -f "$FW" ] || { echo "missing $FW" >&2; exit 2; }
QCAP=${RS_QUERY_CAP:-20000}
QCAP_REG=${RS_QUERY_CAP_REG:-150000}
TRIAL_BOUND=${RS_TRIAL_BOUND_S:-300}
case "$H" in P*|COSTPILOT-*) PILOT=1 ;; *) PILOT=0 ;; esac
CMDERR='grep -i mlx5 | grep -iE "cmd|command" | grep -icE "failed|timeout|leak"'
mkdir -p "$R"
# this run's tag for its snapshot, mlx5 and firmware-command files: the hold's name, or <hold>-r<k> when an earlier run of
# the same hold left its files in this folder
HT=$H
if [ -e "$R/snap_before-$HT.txt" ]; then k=2; while [ -e "$R/snap_before-$H-r$k.txt" ]; do k=$((k + 1)); done; HT=$H-r$k; fi
echo "hold $H (files tagged $HT) rs_set=${RS_SET:--}"
left() { { pgrep -x gin_rs; pgrep -x gin_rs_hk; pgrep -f '[/]tmp/rs_cost'
           ssh -n "$SUNNY_SSH" "pgrep -x gin_rs; pgrep -x gin_rs_hk; pgrep -f '[/]tmp/rs_cost'"; } 2>/dev/null | wc -l; }
OWNCLEAN='find /tmp -maxdepth 1 -user "$(id -un)" \( -name "rs_rt_*" -o -name "rs_rt.*" -o -name "rs_cost_*" -o -name "rs_cost.*" \) -exec rm -rf {} + 2>/dev/null; true'
for f in STOP_mlx5 STOP_cuda STOP_left STOP_nic; do
  if [ -e "$R/$f" ]; then
    echo "$R/$f present: no hold runs" >&2
    [ "$(left)" -eq 0 ] && { bash -c "$OWNCLEAN"; ssh -n "$SUNNY_SSH" "$OWNCLEAN"; }
    exit 3
  fi
done
# the section-8 start gate: rain's BAR1 Free >= 128 MiB
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
fwread() {  # fwread <tag>: "<failed sum> <QUERY_QP n>" from one firmware-command snapshot
  bash "$FW" "$1" 2>/dev/null | awk '{for(i=1;i<=NF;i++){ if($i ~ /^failed=|^failed_mbox_status=/){split($i,a,"="); s+=a[2]}
    if($1=="QUERY_QP" && $i ~ /^n=/){split($i,b,"="); q=b[2]} }} END{print s+0, q+0}'
}
n0=$(left)
[ "$n0" -eq 0 ] || { echo "$(date '+%F %T') hold $H: $n0 test process(es) present before the hold" | tee -a "$R/STOP_left"; exit 3; }
bash -c "$OWNCLEAN"; ssh -n "$SUNNY_SSH" "$OWNCLEAN"
SECONDS=0
snap "before-$HT" | tee "$R/snap_before-$HT.txt"
read -r FW0 QQ < <(fwread "start-$HT")
fits() {  # fits <bound_s> <what>: false (and a line in skipped.txt) if the bound would end past 840 s of the hold
  if [ $((SECONDS + $1)) -gt 840 ]; then echo "$(date '+%F %T') hold $H: skipped $2 (elapsed ${SECONDS}s + bound $1s > 840s)" | tee -a "$R/skipped.txt"; return 1; fi
  return 0
}
stopped() { [ -e "$R/STOP_left" ] || [ -e "$R/STOP_mlx5" ] || [ -e "$R/STOP_cuda" ] || [ -e "$R/STOP_nic" ]; }
after_trial() {  # after_trial <what> <kv glob> [refusal-expected 0|1] [QUERY_QP cap]: the per-trial stop checks (error
                # keys in the live ranks' kv, a refusal where none is expected, firmware failures, QUERY_QP cap: RS_QUERY_CAP,
                # or the caller's, RS_QUERY_CAP_REG for the regression cells). A spare's kv is not checked for errors: a spare
                # never activated (no kill, a fallback) waits in Resume to its bound by design (SPARE_WAIT_MS, run_rs.sh; its
                # watchdog before); a watchdog end goes to spare_wait.txt and does not stop the hold
  local what=$1 f fw qq refuse_ok=${3:-1} cap=${4:-$QCAP}
  for f in $2; do
    [ -f "$f" ] || continue
    case "$f" in
      *_spare.kv|*_neg_cut.kv|*_neg_field.kv)
        grep -q 'watchdog=1' "$f" && echo "$(date '+%F %T') $what: $(basename "$f") ended at its watchdog" >> "$R/spare_wait.txt"
        continue ;;
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
# one cell line per record from cells_rs.json: cell, build, kind, n, then each env pair as its own field (tab-separated,
# values may hold spaces)
json_hold() {
  python3 - "$CELLS" "$1" <<'PY'
import json, sys
for e in json.load(open(sys.argv[1]))["holds"].get(sys.argv[2], []):
    env = ["DRIVER=%s" % e["driver"]] + ["%s=%s" % kv for kv in e.get("env", {}).items()]  # every cell names its driver
    print("\t".join([e["cell"], e["build"], e["kind"], str(e["n"])] + env))
PY
}
do_json_hold() {
  local line cell build kind n ldir rok
  local -a f envs
  while IFS= read -r line <&3; do
    IFS=$'\t' read -r -a f <<< "$line"
    cell=${f[0]}; build=${f[1]}; kind=${f[2]}; n=${f[3]}; envs=("${f[@]:4}")
    case "$kind" in reg) ldir=$R/reg ;; *) ldir=$R/raw ;; esac
    mkdir -p "$ldir"
    for ((k = 1; k <= n; k++)); do
      if [ "$kind" = rs ]; then stem="${cell}_${build}_n$k"; else stem="${cell}_n$k"; fi
      if [ -f "$ldir/${stem}_meta.txt" ]; then  # an earlier run of this hold did it (resumable holds)
        echo "$(date '+%F %T') hold $H: ${cell}@${build}_n$k already done ($(basename "$ldir")/${stem}_meta.txt exists)"
        continue
      fi
      stopped && { echo "skipped ${cell}@${build}_n$k: STOP" >> "$R/skipped.txt"; break; }
      # bound: an rs trial with a spare: the spare's own wait (60 s, run_rs.sh) or its watchdog, plus the runner's waits
      if [ "$kind" = rs ]; then fits "$TRIAL_BOUND" "${cell}@${build}_n$k" || break; else fits 150 "${cell}_n$k" || break; fi
      bash "$D/cells_rs.sh" "$ldir" "$cell" "$build" "$kind" 1 "$k" "${envs[@]}" < /dev/null
      case "$cell" in rs4_refuse_*) rok=1 ;; *) rok=$([ "$build" = rs ] && echo 0 || echo 1) ;; esac
      if [ "$kind" = rs ]; then after_trial "${cell}_${build}_n$k" "$ldir/${cell}_${build}_n${k}_*.kv" "$rok"
      else after_trial "${cell}_n$k" "$ldir/${cell}_n${k}_r*.kv" 1 "$QCAP_REG"; fi
    done
  done 3< <(json_hold "$1")
}
cost_run() {  # cost_run <cell> <tag> <logdir>
  local cell=$1 tag=$2 dir=$3 f bad=""
  stopped && { echo "skipped ${cell}_$tag: STOP" >> "$R/skipped.txt"; return 0; }
  fits 90 "${cell}_$tag" || return 0
  bash "$D/run_cost.sh" "$cell" "$tag" "$dir"
  for f in "$dir/${cell}_${tag}_r0.kv" "$dir/${cell}_${tag}_r1.kv"; do
    [ -f "$f" ] || { bad="missing $(basename "$f")"; break; }
    if grep -qE 'nccl_error=|cuda_error=|watchdog' "$f" || ! grep -q '^exit=0$' "$f"; then
      bad="$(basename "$f"): $(grep -hoE 'nccl_error=[^ ]*|cuda_error=[^ ]*|exit=[0-9]+' "$f" | tr '\n' ' ')"; break
    fi
  done
  [ -n "$bad" ] && echo "$(date '+%F %T') hold $H: ${cell}_$tag error ($bad); no further run" | tee -a "$R/STOP_nic"
  local lft; lft=$(sed -n 's/.* left=\([0-9]*\) .*/\1/p' "$dir/${cell}_${tag}_meta.txt" 2>/dev/null)
  [ -n "$lft" ] && [ "$lft" -gt 0 ] && echo "$(date '+%F %T') hold $H: ${cell}_$tag left $lft" | tee -a "$R/STOP_left"
  after_trial "${cell}_$tag" ""
}
cost_family() {  # cost_family <family> <node> <dir> <rounds> [metric]: every metric of the family, or only the one named
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
  P1|P2|P3|G1|G2|R1) do_json_hold "$H" ;;
  COSTPILOT-*)
    node=${H#COSTPILOT-}; node=${node%%-*}
    case "$node" in rain|sunny) ;; *) echo "COSTPILOT-<rain|sunny>" >&2; exit 2 ;; esac
    d=$(newdir "costpilot_$node"); mkdir -p "$d"
    for fam in log ffbranch; do cost_family "$fam" "$node" "$d" 1; done ;;
  COST-*)
    rest=${H#COST-}; fam=${rest%%-*}; rest=${rest#*-}; node=${rest%%-*}; met=""
    case "$rest" in *-*) met=${rest#*-}; met=${met%%-*} ;; esac
    case "$met" in lat4k|lat256k|bw256k|"") ;; *) met="" ;; esac   # anything else after the node is only a tag
    case "$fam" in log|ffbranch) ;; *) echo "COST-<log|ffbranch>-<rain|sunny>[-<metric>][-<tag>]" >&2; exit 2 ;; esac
    case "$node" in rain|sunny) ;; *) echo "COST-<family>-<rain|sunny>[-<metric>][-<tag>]" >&2; exit 2 ;; esac
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
