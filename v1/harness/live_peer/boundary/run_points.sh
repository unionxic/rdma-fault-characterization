#!/usr/bin/env bash
# run_points.sh <CPU|GIN> <outroot> - run the sweep points of the live_boundary study
# (EXPERIMENT.md section 7; tag prereg/live-boundary-v1). Run it inside
# harness/gpu-initiated/common/cluster_run.sh -w 10800 -t lb-<part> -- ...
#
#   CPU: CPU verbs harness (harness/run.sh, one probe_client/probe_server pair per trial)
#        CP<ms>: live_stop_probe, the responder stops <ms> when it receives the PROBE (0 = no stop)
#        CG<ms>: live_stop_err, the responder stops <ms> right after GOACK
#   GIN: GIN GDAKI recovery v2 with the stall switch (bundle gin_recovery_gpudb_stall)
#        G<ms>:  rank 1 stops <ms> when it receives the recovery request
#
# Points are run round-robin (one trial of every unfinished point per round), so time drift does not
# line up with the stop length. Every trial is wrapped by propagation/campaign/evrec_pair.sh (evrec2,
# no samples) and appends "<tag> rc=<rc> <start> <end>" to <outroot>/<series>/trials.log. The safety
# checks after every trial are those of ../run_cells.sh (section 8): SIGCONT to our stopped
# processes, leftovers after 5 s stop the campaign, new mlx5 command errors in dmesg stop it, a port
# that is not ACTIVE stops it. Extra trials: only for a fault not applied or a runner failure, decided
# without reading any outcome field, at most ceil(0.3 n) per point; none in smoke (N_OVERRIDE=1).
# Exit status: 0 done, 3 stopped by a safety check, 2 bad arguments.
set -u
PART=${1:?CPU|GIN}; ROOT=${2:?outroot}
HERE=$(cd "$(dirname "$0")" && pwd)
H=$(cd "$HERE/../.." && pwd)                    # harness
G=$H/gpu-initiated
EP=$G/propagation/campaign/evrec_pair.sh
mkdir -p "$ROOT"; ROOT=$(cd "$ROOT" && pwd)
export EVREC_BIN=$HOME/gi-bundle/evrec2/evrec
SUNNY=sunny
NAMES="probe_server probe_client gin_rec lp_stall"
DMESG_RX='mlx5.*(mlx5_cmd_out_err|mlx5_cmd_check|wait_func|cmd_work_handler|failed, status|Will cause a leak)'
SERVER_DIR_LB='~/rdma-error-lb/harness'         # this study's copy on sunny
LOGF=$ROOT/runner_$PART.log

note() { echo "$(date '+%F %T') $*" | tee -a "$LOGF" >&2; }
nn() { echo "${N_OVERRIDE:-$1}"; }
dmesg_local()  { dmesg 2>/dev/null | grep -cE "$DMESG_RX"; }
dmesg_remote() { ssh -n "$SUNNY" "dmesg >/dev/null 2>&1 || { echo unreadable; exit 0; }; dmesg | grep -cE '$DMESG_RX'; exit 0" 2>/dev/null || echo ssh_failed; }
DM_L0=$(dmesg_local); DM_R0=$(dmesg_remote)
note "start $PART: dmesg mlx5 command-error lines rain=$DM_L0 sunny=$DM_R0"

stop_campaign() { note "STOP: $*"; echo "STOP $(date '+%F %T') $*" >> "$ROOT/STOP"; exit 3; }

check_after() {   # check_after <tag>
  local tag=$1 names tl tr ll lr dl dr pl pr
  names=$(echo $NAMES | tr ' ' '|')
  tl=$(ps -eo pid=,stat=,comm= | awk -v r="^($names)\$" '$2 ~ /^T/ && $3 ~ r {print $1}')
  [ -n "$tl" ] && { note "$tag: SIGCONT to stopped rain PIDs $tl"; kill -CONT $tl 2>/dev/null; }
  tr=$(ssh -n "$SUNNY" "ps -eo pid=,stat=,comm= | awk -v r='^($names)\$' '\$2 ~ /^T/ && \$3 ~ r {print \$1}'")
  [ -n "$tr" ] && { note "$tag: SIGCONT to stopped sunny PIDs $tr"; ssh -n "$SUNNY" "kill -CONT $tr" 2>/dev/null; }
  for _ in $(seq 10); do
    ll=$(for x in $NAMES; do pgrep -x "$x"; done)
    lr=$(ssh -n "$SUNNY" "for x in $NAMES; do pgrep -x \$x; done")
    [ -z "$ll$lr" ] && break
    sleep 0.5
  done
  if [ -n "$ll$lr" ]; then
    [ -n "$ll" ] && { kill -CONT $ll 2>/dev/null; kill $ll 2>/dev/null; }
    [ -n "$lr" ] && ssh -n "$SUNNY" "kill -CONT $lr 2>/dev/null; kill $lr 2>/dev/null"
    stop_campaign "$tag: our processes left after the trial (rain: $(echo $ll) sunny: $(echo $lr)); SIGCONT+SIGTERM sent to those PIDs"
  fi
  dl=$(dmesg_local); dr=$(dmesg_remote)
  [ "$dl" -gt "$DM_L0" ] 2>/dev/null && stop_campaign "$tag: new mlx5 command-error lines in rain dmesg ($DM_L0 -> $dl)"
  case "$dr" in ''|*[!0-9]*) ;; *) [ "$DM_R0" -eq "$DM_R0" ] 2>/dev/null && [ "$dr" -gt "$DM_R0" ] && stop_campaign "$tag: new mlx5 command-error lines in sunny dmesg ($DM_R0 -> $dr)";; esac
  pl=$(cat /sys/class/infiniband/mlx5_1/ports/1/state)
  pr=$(ssh -n "$SUNNY" "cat /sys/class/infiniband/mlx5_0/ports/1/state")
  case "$pl" in *ACTIVE*) ;; *) stop_campaign "$tag: rain mlx5_1 port state '$pl'";; esac
  case "$pr" in *ACTIVE*) ;; *) stop_campaign "$tag: sunny mlx5_0 port state '$pr'";; esac
  return 0
}

trial() {   # trial <series_dir> <tag> <timeout_s> <command...>
  local out=$1 tag=$2 to=$3; shift 3
  local t0; t0=$(date +%FT%T)
  mkdir -p "$out/logs" "$out/evrec"
  EVREC_ARGS="" bash "$EP" start "$out/evrec" "$tag"
  timeout -k 10 "$to" "$@" > "$out/logs/$tag.out" 2>&1
  local rc=$?
  EVREC_ARGS="" bash "$EP" stop "$out/evrec" "$tag"
  echo "$tag rc=$rc $t0 $(date +%FT%T)" | tee -a "$out/trials.log"
  check_after "$tag"
}

# ---- CPU harness ----
run_cpu() {   # run_cpu <series CP|CG> <ms> <tN>
  local s=$1 ms=$2 tn=$3 f tag out
  if [ "$s" = CP ]; then f=live_stop_probe; else f=live_stop_err; fi
  tag="lb_$(echo "$s" | tr 'A-Z' 'a-z')${ms}_$tn"; out=$ROOT/$s
  mkdir -p "$out/runs/$tag" "$out/logs"
  if [ "$ms" -gt 0 ]; then
    # evidence of the stop (not scored): poll the responder's process state until it shows T
    ( ssh -n "$SUNNY" 'for i in $(seq 150); do s=$(ps -o stat= -C probe_server | head -1); case "$s" in T*) echo "state T seen at poll $i"; ps -o pid=,stat=,comm= -C probe_server; exit 0;; esac; sleep 0.2; done; echo "state T not seen"' > "$out/logs/$tag.pstate" 2>&1 ) &
  fi
  trial "$out" "$tag" 90 env RESULTS_DIR="$out/runs/$tag" ITERS=1 LIVE_STOP_MS="$ms" \
    SERVER_DIR="$SERVER_DIR_LB" SERVER_LOG=/tmp/lb_probe_srv.log bash "$H/run.sh" "$f"
  wait
}
valid_cpu() {   # valid_cpu <series> <ms> <tN>: CSV row, fault_applied, stall_end when the stop is > 0
  local s=$1 ms=$2 tn=$3 f tag d csv srv
  if [ "$s" = CP ]; then f=live_stop_probe; else f=live_stop_err; fi
  tag="lb_$(echo "$s" | tr 'A-Z' 'a-z')${ms}_$tn"; d=$ROOT/$s/runs/$tag
  csv=$(ls "$d"/"$f"_*.csv 2>/dev/null | head -1); srv=$(ls "$d"/"$f"_*.srv.log 2>/dev/null | head -1)
  [ -n "$csv" ] && [ "$(wc -l < "$csv")" -ge 2 ] || return 1
  grep -q "fault_applied fault=$f" "$srv" 2>/dev/null || return 1
  [ "$ms" -gt 0 ] && { grep -q "stall_end" "$srv" 2>/dev/null || return 1; }
  return 0
}

# ---- GIN ----
run_gin() {   # run_gin G <ms> <tN>
  local ms=$2 tn=$3 tag="g${2}_$3" out=$ROOT/G
  mkdir -p "$out/logs"
  trial "$out" "$tag" 180 env BUNDLE="$HOME/gi-bundle/gin_recovery_gpudb_stall" REC=1 CLASSIFY=1 INJECT=600 WATCHDOG_S=60 \
    EXTRA_ENV="GIN_REC_TEST_STALL_MS=$ms GIN_REC_TEST_STALL_ON=req" \
    bash "$G/gin_recovery/scripts/run_trial.sh" F3 timeout "$tag" "$out/logs" 120 14
}
valid_gin() {   # valid_gin G <ms> <tN>: both kv files, a fault record, a stall record with its end
  local s="$ROOT/G/logs/rec1_F3_timeout_g${2}_$3"
  [ -s "${s}_r0.kv" ] && [ -s "${s}_r1.kv" ] || return 1
  grep -q "^fault ev=" "${s}_r0.kv" || return 1
  grep -q "^stall on=.*end_mono_ms=" "${s}_r1.kv" || return 1
  return 0
}

# ---- round-robin over points, then extra trials ----
sweep() {   # sweep <runfn> <validfn> "<series> <ms> <n>" ...
  local rf=$1 vf=$2; shift 2
  local -a S M N V
  local i k=0 maxn=0
  local p s m n
  for p in "$@"; do
    read -r s m n <<< "$p"
    S[k]=$s; M[k]=$m; N[k]=$(nn "$n"); V[k]=0
    [ "${N[k]}" -gt "$maxn" ] && maxn=${N[k]}
    k=$((k + 1))
  done
  for r in $(seq "$maxn"); do
    for i in $(seq 0 $((k - 1))); do
      [ "$r" -le "${N[i]}" ] || continue
      "$rf" "${S[i]}" "${M[i]}" "t$r"
      "$vf" "${S[i]}" "${M[i]}" "t$r" && V[i]=$((V[i] + 1))
    done
  done
  for i in $(seq 0 $((k - 1))); do
    local emax=0 e=0 t
    [ -z "${N_OVERRIDE:-}" ] && emax=$(( (3 * N[i] + 9) / 10 ))
    while [ "${V[i]}" -lt "${N[i]}" ] && [ "$e" -lt "$emax" ]; do
      e=$((e + 1)); t=$((N[i] + e))
      note "point ${S[i]}${M[i]}: ${V[i]}/${N[i]} valid, extra trial t$t ($e/$emax)"
      "$rf" "${S[i]}" "${M[i]}" "t$t"
      "$vf" "${S[i]}" "${M[i]}" "t$t" && V[i]=$((V[i] + 1))
    done
    note "point ${S[i]}${M[i]} done: planned ${N[i]}, extra $e, valid ${V[i]}"
  done
}

case "$PART" in
CPU)
  sweep run_cpu valid_cpu "CP 0 5" "CP 900 5" "CP 990 5" "CP 1008 10" "CP 1024 10" "CP 1040 5" "CP 1100 5"
  sweep run_cpu valid_cpu "CG 4300 5" "CG 4600 10" "CG 5000 5" ;;
GIN)
  sweep run_gin valid_gin "G 2900 5" "G 2985 5" "G 2992 5" "G 2995 10" "G 2998 10" "G 3010 5" "G 3100 5" ;;
*) echo "usage: $0 CPU|GIN <outroot>" >&2; exit 2 ;;
esac
note "part $PART finished"
