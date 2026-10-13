#!/usr/bin/env bash
# hold_mf.sh - one hold of gin-mirror's feasibility checks (EXPERIMENT.md 9.8; DRAFT stage, never scored). The main session
# runs it inside ../../../common/cluster_run.sh (tag mf-<hold>, -w 10800) under timeout -s KILL 880.
# usage: hold_mf.sh <resultsdir> <hold>
#   VIS      check 1: vis_<4k|256k|2m>_<sunny|rain> (both directions; the named node holds the host MR), VIS_ITERS
#            (MF_VIS_ITERS, 10 000) iterations each, into vis/ (a repeat: vis_run<k>/)
#   VISone-<cell>[-<tag>]  one vis cell (vis_<size>_<node>, size 4k|256k|2m|rand), into vis_one<k>/
#   STORE    check 3: store_rain (sunny's GPU writes to and reads from rain's host MRs: the layout of a rank 3 kill, whose
#            buddy rank 2 is on rain) and store_sunny (the other direction), STORE_REPS (MF_STORE_REPS, 100) each, into
#            store/ (a repeat: store_run<k>/)
#   BAR1     check 4: bar1_rain into bar1/ (a repeat: bar1_run<k>/); not started unless rain's BAR1 Free >= MF_BAR1_START_MIB
#            (192 = three processes x 30 MiB + one second-PD registration of 30 MiB + the 64 MiB of the pass rule)
#   COSTMAN-<rain|sunny>-<metric>[-<tag>]  check 2: the manual mirror cost (cost_man.md; needs the test work package's
#            gin_ts2 in ~/rs-bundle/mfcm), metric lat4k|lat256k|lat2m|bw256k|bw2m, the named node receiving: for k = 1-6 the
#            arms one, man-self, man-peer back to back, the order reversed when k is even (gin-restore 9.15.6's interleave),
#            into costman_<node>_<metric>/ (a repeat: ..._run<k>/)
# Before and after the hold (as ../../restore/feas/hold_feas.sh and ../../restore/impl/test/hold_rs.sh): GPU users, compute
# mode and BAR1 of both nodes, MemAvailable of both nodes, the mlx5 kernel lines of both nodes, rain's mlx5_1
# firmware-command counters (debugfs, read only, ../../scripts/ts1/fwcmd_snapshot.sh). Start gates (refused.txt): rain's BAR1
# Free >= 128 MiB (EXPERIMENT.md 8), MemAvailable >= MF_MIN_MEM_MIB (2048) on both nodes. STOP rules: after every run, an
# error key (setup_error, nic_error, cuda_error, watchdog=1; gin_ts2: nccl_error, cuda_error, watchdog, no exit=0) or a
# missing kv writes STOP_nic, a process of the run left behind writes STOP_left, a growth of rain's firmware-command
# failures or of rain's QUERY_QP count by more than MF_QCAP (40 000) in one run writes STOP_mlx5, and the remaining runs are
# skipped; after the hold, a new mlx5 command-error line writes STOP_mlx5, a CUDA memory fault STOP_cuda, a test process
# left STOP_left. A vis FAIL (a wrong word in a2 or a3) and a bar1 REG_FAIL are readings, not stops. A run whose bound would
# end past 840 s of the hold is skipped (skipped.txt). No hold runs while a STOP file exists (this script refuses). Nothing
# is killed here: every process has its own timeout; the leftover check is a read-only count, by exact name for mirror_feas
# and by this study's /tmp paths for everything else. Before the hold, with no test process left, this user's own leftover
# files of an earlier cut hold (/tmp/mf_run.*, /tmp/mf_rt_*) are deleted on both nodes. No iptables rule.
# env: SUNNY_SSH (required; passed to run_mf.sh), and the knobs above
set -u
R=${1:?resultsdir}; H=${2:?hold}
D=$(cd "$(dirname "$0")" && pwd)
SUNNY_SSH=${SUNNY_SSH:?set SUNNY_SSH}
export SUNNY_SSH
FW=$D/../../scripts/ts1/fwcmd_snapshot.sh
[ -f "$FW" ] || { echo "missing $FW" >&2; exit 2; }
VIS_ITERS=${MF_VIS_ITERS:-10000}; STORE_REPS=${MF_STORE_REPS:-100}; QCAP=${MF_QCAP:-40000}
BAR1_START=${MF_BAR1_START_MIB:-192}; MINMEM=${MF_MIN_MEM_MIB:-2048}
CMDERR='grep -i mlx5 | grep -iE "cmd|command" | grep -icE "failed|timeout|leak"'
mkdir -p "$R"
HT=$H   # this run's tag for its snapshot files: the hold's name, or <hold>-r<k> when an earlier run left its files here
if [ -e "$R/snap_before-$HT.txt" ]; then k=2; while [ -e "$R/snap_before-$H-r$k.txt" ]; do k=$((k + 1)); done; HT=$H-r$k; fi
left() { { pgrep -x mirror_feas; pgrep -f '[/]tmp/mf_r'
           ssh -n "$SUNNY_SSH" "pgrep -x mirror_feas; pgrep -f '[/]tmp/mf_r'"; } 2>/dev/null | wc -l; }
OWNCLEAN='find /tmp -maxdepth 1 -user "$(id -un)" \( -name "mf_run.*" -o -name "mf_rt_*" \) -exec rm -rf {} + 2>/dev/null; true'
for f in STOP_mlx5 STOP_cuda STOP_left STOP_nic; do
  if [ -e "$R/$f" ]; then
    echo "$R/$f present: no hold runs" >&2
    [ "$(left)" -eq 0 ] && { bash -c "$OWNCLEAN"; ssh -n "$SUNNY_SSH" "$OWNCLEAN"; }
    exit 3
  fi
done
bar1free() { nvidia-smi -q -d MEMORY 2>/dev/null | sed -n '/BAR1/,/Free/p' | sed -n 's/.*Free *: *\([0-9]*\) *MiB.*/\1/p' | head -1; }
memavail() { awk '$1 == "MemAvailable:" {print int($2 / 1024)}' /proc/meminfo; }
refuse() { echo "$(date '+%F %T') hold $H: $1: not started" | tee -a "$R/refused.txt"; exit 3; }
b1=$(bar1free); need=128; [ "$H" = BAR1 ] && need=$BAR1_START
{ [ -n "$b1" ] && [ "$b1" -ge "$need" ]; } || refuse "rain BAR1 Free ${b1:-unread} MiB < $need MiB"
mr=$(memavail); ms=$(ssh -n "$SUNNY_SSH" "awk '\$1 == \"MemAvailable:\" {print int(\$2 / 1024)}' /proc/meminfo" 2>/dev/null)
{ [ -n "$mr" ] && [ -n "$ms" ] && [ "$mr" -ge "$MINMEM" ] && [ "$ms" -ge "$MINMEM" ]; } ||
  refuse "MemAvailable rain ${mr:-unread} / sunny ${ms:-unread} MiB < $MINMEM MiB"
snap() {  # snap <tag>
  echo "== $1 $(date '+%F %T')"
  nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader 2>/dev/null | sed 's/^/rain gpu: /'
  ssh -n "$SUNNY_SSH" "nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader" 2>/dev/null | sed 's/^/sunny gpu: /'
  nvidia-smi --query-gpu=index,name,compute_mode --format=csv,noheader 2>/dev/null | sed 's/^/rain gpu mode: /'
  ssh -n "$SUNNY_SSH" "nvidia-smi --query-gpu=index,name,compute_mode --format=csv,noheader" 2>/dev/null | sed 's/^/sunny gpu mode: /'
  nvidia-smi -q -d MEMORY 2>/dev/null | sed -n '/BAR1/,/Free/p' | tr -s ' ' | tr '\n' ' ' | sed 's/^/rain bar1: /'; echo
  ssh -n "$SUNNY_SSH" "nvidia-smi -q -d MEMORY | sed -n '/BAR1/,/Free/p'" 2>/dev/null | tr -s ' ' | tr '\n' ' ' | sed 's/^/sunny bar1: /'; echo
  echo "rain memavailable_mib: $(memavail)"
  echo "sunny memavailable_mib: $(ssh -n "$SUNNY_SSH" "awk '\$1 == \"MemAvailable:\" {print int(\$2 / 1024)}' /proc/meminfo" 2>/dev/null)"
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
newdir() {  # newdir <base>: $R/<base> if it holds no run yet, else the first free $R/<base>_run<k> (k >= 2)
  if ! ls "$R/$1"/*_meta.txt >/dev/null 2>&1; then echo "$R/$1"; return; fi
  local k=2; while [ -e "$R/$1_run$k" ]; do k=$((k + 1)); done; echo "$R/$1_run$k"
}
mfrun() {  # mfrun <cell> <repeat> <dir> <bound_s> [tag]: one run if it fits, then the per-run stop checks
  local cell=$1 rep=$2 dir=$3 bound=$4 tag=${5:-} stem f bad="" fw qq lft n=0
  stem=$cell${tag:+_$tag}
  stopped && { echo "skipped $stem: STOP file" >> "$R/skipped.txt"; return 0; }
  fits "$bound" "$stem" || return 0
  bash "$D/run_mf.sh" "$cell" "$rep" "$dir" "$tag"
  for f in "$dir/${stem}"_{host,writer,src,p0,p2,sp,r0,r1}.kv; do
    [ -f "$f" ] || continue
    n=$((n + 1))
    if grep -qE 'setup_error=|nic_error=|cuda_error=|nccl_error=|watchdog' "$f"; then
      bad="$(basename "$f"): $(grep -hoE '(setup|nic)_error="[^"]*"|(cuda|nccl)_error=[^ ]*|watchdog[^ ]*' "$f" | head -1)"; break
    fi
    case "$cell" in cm_*) grep -q '^exit=0$' "$f" || { bad="$(basename "$f"): no exit=0"; break; } ;; esac
  done
  case "$cell" in vis_*|store_*|cm_*) want=2 ;; bar1_*) want=3 ;; esac
  [ -z "$bad" ] && [ "$n" -lt "$want" ] && bad="$n of $want kv files"
  [ -n "$bad" ] && echo "$(date '+%F %T') hold $H: $stem ended with an error ($bad); no further run" | tee -a "$R/STOP_nic"
  lft=$(sed -n 's/.* left=\([0-9]*\) .*/\1/p' "$dir/${stem}_meta.txt" 2>/dev/null)
  [ -n "$lft" ] && [ "$lft" -gt 0 ] && echo "$(date '+%F %T') hold $H: $stem left $lft process(es)" | tee -a "$R/STOP_left"
  read -r fw qq < <(fwread "after-$stem")
  [ "$fw" -gt "$FW0" ] && echo "$(date '+%F %T') hold $H: firmware-command failures grew after $stem ($FW0 -> $fw)" | tee -a "$R/STOP_mlx5"
  [ $((qq - QQ)) -gt "$QCAP" ] && echo "$(date '+%F %T') hold $H: $stem: rain QUERY_QP +$((qq - QQ)) > $QCAP" | tee -a "$R/STOP_mlx5"
  echo "$stem rain_query_qp_delta=$((qq - QQ))" >> "$R/qp_delta.txt"
  QQ=$qq
  return 0
}
VISB=$(( VIS_ITERS / 200 + 150 + 30 ))   # bounds: the runner's timeout (watchdog + 30) and its own waits
STOREB=$(( STORE_REPS / 2 + 270 + 30 ))
case "$H" in
  VIS) d=$(newdir vis); for s in 4k 256k 2m; do for n in sunny rain; do mfrun "vis_${s}_$n" "$VIS_ITERS" "$d" "$VISB"; done; done ;;
  VISone-*)
    cell=${H#VISone-}; cell=${cell%%-*}
    case "$cell" in vis_4k_*|vis_256k_*|vis_2m_*|vis_rand_*) ;; *) echo "VISone-vis_<size>_<node>[-<tag>]" >&2; exit 2 ;; esac
    k=1; while [ -e "$R/vis_one$k/${cell}_meta.txt" ]; do k=$((k + 1)); done
    mfrun "$cell" "$VIS_ITERS" "$R/vis_one$k" "$VISB" ;;
  STORE) d=$(newdir store); for n in rain sunny; do mfrun "store_$n" "$STORE_REPS" "$d" "$STOREB"; done ;;
  BAR1) d=$(newdir bar1); mfrun bar1_rain 0 "$d" 400 ;;
  COSTMAN-*)
    rest=${H#COSTMAN-}; node=${rest%%-*}; rest=${rest#*-}; met=${rest%%-*}
    case "$node" in rain|sunny) ;; *) echo "COSTMAN-<rain|sunny>-<metric>[-<tag>]" >&2; exit 2 ;; esac
    case "$met" in lat4k|lat256k|lat2m|bw256k|bw2m) ;; *) echo "COSTMAN-<node>-<lat4k|lat256k|lat2m|bw256k|bw2m>[-<tag>]" >&2; exit 2 ;; esac
    d=$(newdir "costman_${node}_$met"); mkdir -p "$d"
    for k in 1 2 3 4 5 6; do
      if [ $((k % 2)) = 1 ]; then arms="one man-self man-peer"; else arms="man-peer man-self one"; fi
      for a in $arms; do mfrun "cm_${met}_${a}_$node" 0 "$d" 90 "k$k"; done
    done ;;
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
echo "hold $H elapsed ${SECONDS} s"
exit 0
