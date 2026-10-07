#!/usr/bin/env bash
# run_cells.sh <A|B> <outroot> - run the cells of one part of the live_peer study
# (EXPERIMENT.md section 7; tag prereg/live-peer-v1). Run it inside
# harness/gpu-initiated/common/cluster_run.sh -w 10800 -t lp-<part> -- ...
#
#   A: CPU verbs harness (harness/run.sh, one probe_client/probe_server pair per trial)
#   B: GIN GDAKI recovery v2 with the stall switch (gin_recovery/scripts/run_trial.sh)
#
# Every trial is wrapped by propagation/campaign/evrec_pair.sh on both nodes (evrec2 build) and
# appends "<tag> rc=<rc> <start> <end>" to <outroot>/<part>/trials.log. After every trial, and
# before the next one (section 8):
#   - our processes (exact names) in state T on either node get SIGCONT; leftovers after 5 s stop
#     the campaign (after SIGCONT + kill of those PIDs only);
#   - new mlx5 command errors in dmesg (rain; sunny if readable without sudo) stop the campaign;
#   - an RDMA port that is not ACTIVE stops the campaign.
# Extra trials (section 8): a trial whose fault was not applied, or whose runner failed (no CSV row /
# no kv), is replaced by another trial of the same cell, at most ceil(0.3 n) per cell. The check
# reads only those two conditions, never an outcome field. Smoke runs (N_OVERRIDE=1) add none.
# Exit status: 0 done, 3 stopped by a safety check, 2 bad arguments.
set -u
PART=${1:?A|B}; ROOT=${2:?outroot}
HERE=$(cd "$(dirname "$0")" && pwd)
H=$(cd "$HERE/.." && pwd)                       # harness
G=$H/gpu-initiated
EP=$G/propagation/campaign/evrec_pair.sh
OUT=$ROOT/$PART
mkdir -p "$OUT/logs" "$OUT/evrec"
ROOT=$(cd "$ROOT" && pwd); OUT=$ROOT/$PART
export EVREC_BIN=$HOME/gi-bundle/evrec2/evrec
SMP_ARGS="-s 50 -c rp_cnp_handled,roce_slow_restart_cnps,roce_adp_retrans,local_ack_timeout_err"
SUNNY=sunny
NAMES="probe_server probe_client gin_rec lp_stall"
DMESG_RX='mlx5.*(mlx5_cmd_out_err|mlx5_cmd_check|wait_func|cmd_work_handler|failed, status|Will cause a leak)'

note() { echo "$(date '+%F %T') $*" | tee -a "$OUT/runner.log" >&2; }
nn() { echo "${N_OVERRIDE:-$1}"; }

dmesg_local()  { dmesg 2>/dev/null | grep -cE "$DMESG_RX"; }
dmesg_remote() { ssh -n "$SUNNY" "dmesg >/dev/null 2>&1 || { echo unreadable; exit 0; }; dmesg | grep -cE '$DMESG_RX'; exit 0" 2>/dev/null || echo ssh_failed; }
DM_L0=$(dmesg_local); DM_R0=$(dmesg_remote)
note "start part $PART: dmesg mlx5 command-error lines rain=$DM_L0 sunny=$DM_R0"

stop_campaign() { note "STOP: $*"; echo "STOP $(date '+%F %T') $*" >> "$OUT/trials.log"; exit 3; }

# SIGCONT our stopped processes, wait for leftovers, check dmesg and ports
check_after() {   # check_after <tag>
  local tag=$1 n names
  names=$(echo $NAMES | tr ' ' '|')
  # stopped processes of ours: SIGCONT by PID
  local tl tr
  tl=$(ps -eo pid=,stat=,comm= | awk -v r="^($names)\$" '$2 ~ /^T/ && $3 ~ r {print $1}')
  [ -n "$tl" ] && { note "$tag: SIGCONT to stopped rain PIDs $tl"; kill -CONT $tl 2>/dev/null; }
  tr=$(ssh -n "$SUNNY" "ps -eo pid=,stat=,comm= | awk -v r='^($names)\$' '\$2 ~ /^T/ && \$3 ~ r {print \$1}'")
  [ -n "$tr" ] && { note "$tag: SIGCONT to stopped sunny PIDs $tr"; ssh -n "$SUNNY" "kill -CONT $tr" 2>/dev/null; }
  # leftovers after 5 s
  local ll lr
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
  # dmesg
  local dl dr
  dl=$(dmesg_local); dr=$(dmesg_remote)
  [ "$dl" -gt "$DM_L0" ] 2>/dev/null && stop_campaign "$tag: new mlx5 command-error lines in rain dmesg ($DM_L0 -> $dl)"
  case "$dr" in ''|*[!0-9]*) ;; *) [ "$DM_R0" -eq "$DM_R0" ] 2>/dev/null && [ "$dr" -gt "$DM_R0" ] && stop_campaign "$tag: new mlx5 command-error lines in sunny dmesg ($DM_R0 -> $dr)";; esac
  # ports
  local pl pr
  pl=$(cat /sys/class/infiniband/mlx5_1/ports/1/state)
  pr=$(ssh -n "$SUNNY" "cat /sys/class/infiniband/mlx5_0/ports/1/state")
  case "$pl" in *ACTIVE*) ;; *) stop_campaign "$tag: rain mlx5_1 port state '$pl'";; esac
  case "$pr" in *ACTIVE*) ;; *) stop_campaign "$tag: sunny mlx5_0 port state '$pr'";; esac
  return 0
}

trial() {   # trial <tag> <evrec_args> <timeout_s> <command...>
  local tag=$1 xa=$2 to=$3; shift 3
  local t0; t0=$(date +%FT%T)
  EVREC_ARGS="$xa" bash "$EP" start "$OUT/evrec" "$tag"
  timeout -k 10 "$to" "$@" > "$OUT/logs/$tag.out" 2>&1
  local rc=$?
  EVREC_ARGS="$xa" bash "$EP" stop "$OUT/evrec" "$tag"
  echo "$tag rc=$rc $t0 $(date +%FT%T)" | tee -a "$OUT/trials.log"
  check_after "$tag"
}

# ---- validity used only for extra trials (section 8): fault applied, runner produced its record ----
SERVER_SIDE="retry_server_qp_err live_qp_reset live_qp_init live_qp_rtr live_transient live_stop_err live_stop_ok live_ctl_close live_qp_recreate"
valid_A() {   # valid_A <tag> <fault>
  local d=$OUT/runs/$1 f=$2 csv srv
  csv=$(ls "$d"/"$f"_*.csv 2>/dev/null | head -1); srv=$(ls "$d"/"$f"_*.srv.log 2>/dev/null | head -1)
  [ -n "$csv" ] && [ "$(wc -l < "$csv")" -ge 2 ] || return 1
  case " $SERVER_SIDE " in *" $f "*) grep -q "fault_applied fault=$f" "$srv" 2>/dev/null || return 1;; esac
  [ "$f" = retry_proc_sigkill ] && { grep -q "proc_sigkill: raising SIGKILL" "$srv" 2>/dev/null || return 1; }
  case "$f" in live_stop_*) grep -q "stall_end" "$srv" 2>/dev/null || return 1;; esac
  return 0
}
valid_B() {   # valid_B <tag> <fault> <stall_ms>
  local s="$OUT/logs/rec1_$2_timeout_$1"
  [ -s "${s}_r0.kv" ] && [ -s "${s}_r1.kv" ] || return 1
  [ "$2" = F3 ] && { grep -q "^fault ev=" "${s}_r0.kv" || return 1; }
  [ "$3" -gt 0 ] && { grep -q "^stall on=" "${s}_r1.kv" || return 1; }
  return 0
}

# run one cell: planned n, then extra trials while some are invalid (at most ceil(0.3 n)).
# runfn and validfn get <key> <tN> [args...]. Tags follow EXPERIMENT.md 3.0: part A lp_<fault>_t<n>,
# part B b<k>_t<n>.
cell() {   # cell <key> <n> <validfn> <runfn> [args...]
  local key=$1 n=$2 vf=$3 rf=$4; shift 4
  local extra_max=0 good=0 t=0
  [ -z "${N_OVERRIDE:-}" ] && extra_max=$(( (3 * n + 9) / 10 ))
  for t in $(seq "$n"); do "$rf" "$key" "t$t" "$@"; "$vf" "$key" "t$t" "$@" 2>/dev/null && good=$((good + 1)); done
  local e=0
  while [ "$good" -lt "$n" ] && [ "$e" -lt "$extra_max" ]; do
    e=$((e + 1)); t=$((n + e))
    note "cell $key: $good/$n valid, extra trial t$t ($e/$extra_max)"
    "$rf" "$key" "t$t" "$@"; "$vf" "$key" "t$t" "$@" 2>/dev/null && good=$((good + 1))
  done
  note "cell $key done: planned $n, extra $e, valid $good"
}

# ---- part A ----
SERVER_DIR_LP='~/rdma-error-lp/harness'      # this study's copy on sunny (the shared ~/rdma-error stays untouched)
runA() {   # runA <key> <tN> <fault>
  local key=$1 tn=$2 f=$3 tag="lp_${3}_$2" xa=""
  case "$key" in A1|A3|A6) xa=$SMP_ARGS;; esac
  mkdir -p "$OUT/runs/$tag"
  if [ "$f" = live_stop_err ] || [ "$f" = live_stop_ok ]; then
    # evidence of the stop: poll the responder's process state (0.2 s steps, 30 s) until it shows T
    ( ssh -n "$SUNNY" 'for i in $(seq 150); do s=$(ps -o stat= -C probe_server | head -1); case "$s" in T*) echo "state T seen at poll $i"; ps -o pid=,stat=,comm= -C probe_server; exit 0;; esac; sleep 0.2; done; echo "state T not seen"' > "$OUT/logs/$tag.pstate" 2>&1 ) &
  fi
  trial "$tag" "$xa" 90 env RESULTS_DIR="$OUT/runs/$tag" ITERS=1 COUNTER=rp_cnp_handled \
    SERVER_DIR="$SERVER_DIR_LP" SERVER_LOG=/tmp/lp_probe_srv.log bash "$H/run.sh" "$f"
  wait
}
vA() { valid_A "lp_${3}_$2" "$3"; }

# ---- part B ----
runB() {   # runB <key> <tN> <fault> <stall_ms> <stall_on>
  local key=$1 tn=$2 f=$3 ms=$4 on=$5 tag="b${1#B}_$2" ex=""
  [ "$ms" -gt 0 ] && ex="GIN_REC_TEST_STALL_MS=$ms GIN_REC_TEST_STALL_ON=$on"
  trial "$tag" "" 180 env BUNDLE="$HOME/gi-bundle/gin_recovery_gpudb_stall" REC=1 CLASSIFY=1 INJECT=600 WATCHDOG_S=60 \
    EXTRA_ENV="$ex" bash "$G/gin_recovery/scripts/run_trial.sh" "$f" timeout "$tag" "$OUT/logs" 120 14
}
vB() { valid_B "b${1#B}_$2" "$3" "$4"; }

case "$PART" in
A)
  for c in "A0 5 none" "A1 5 retry_server_qp_err" "A2 5 retry_proc_sigkill" "A3 10 live_qp_reset" \
           "A4 10 live_qp_init" "A5 10 live_qp_rtr" "A6 10 live_transient" "A7 10 live_stop_err" \
           "A8 10 live_stop_ok" "A9 10 live_ctl_close" "A10 5 rnr" "A11 5 live_qp_recreate"; do
    read -r key n f <<< "$c"
    [ -n "${ONLY_CELLS:-}" ] && case " $ONLY_CELLS " in *" $key "*) ;; *) continue;; esac
    cell "$key" "$(nn "$n")" vA runA "$f"
  done ;;
B)
  for c in "B0 5 F3 0 req" "B1 10 F3 1000 req" "B2 10 F3 6000 req" "B3 5 none 6000 iter:60"; do
    read -r key n f ms on <<< "$c"
    [ -n "${ONLY_CELLS:-}" ] && case " $ONLY_CELLS " in *" $key "*) ;; *) continue;; esac
    cell "$key" "$(nn "$n")" vB runB "$f" "$ms" "$on"
  done ;;
*) echo "usage: $0 A|B <outroot>" >&2; exit 2 ;;
esac
note "part $PART finished"
