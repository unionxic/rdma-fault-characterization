#!/usr/bin/env bash
# cells.sh <stack> <outroot> - run every trial of one stack of the pre-registered campaign
# (../PREDICTIONS.md, ../predictions.csv). Each trial is a fresh process pair, wrapped by
# evrec_pair.sh on both nodes. Run it inside ../../common/cluster_run.sh, one stack per call.
#
# stacks (variant ids of PREDICTIONS.md):
#   cpu  CPU verbs harness         gp  GIN proxy        gg  GIN GDAKI       gq  GDAKI + Q4
#   nvo  NVSHMEM v3.8.0-0 (NC NG NX)                    nvd NVSHMEM devel + fault hooks (ND)
#   nvf  NVSHMEM FT v2.2 (NF)                           net NCCL 2.23.4 net_ib (stock path, Stage 2)
# N per cell follows PREDICTIONS.md: 10 for new cells, 5 for replications and F0 controls.
# Every trial appends "<tag> rc=<rc> <start> <end>" to <outroot>/<stack>/trials.log.
set -u
STACK=$1; ROOT=$2
HERE=$(cd "$(dirname "$0")" && pwd)
G=$(cd "$HERE/../.." && pwd)                 # harness/gpu-initiated
H=$(cd "$G/.." && pwd)                       # harness
OUT=$ROOT/$STACK; mkdir -p "$OUT"
EP=$HERE/evrec_pair.sh

trial() {  # trial <tag> <command...>
  local tag=$1; shift
  local t0; t0=$(date +%FT%T)
  bash "$EP" start "$OUT/evrec" "$tag"
  "$@" > "$OUT/logs/$tag.out" 2>&1
  local rc=$?
  bash "$EP" stop "$OUT/evrec" "$tag"
  echo "$tag rc=$rc $t0 $(date +%FT%T)" | tee -a "$OUT/trials.log"
}
mkdir -p "$OUT/logs" "$OUT/evrec"
# smoke runs: N_OVERRIDE=<n> replaces every count
nn() { echo "${N_OVERRIDE:-$1}"; }

case "$STACK" in
cpu)
  # one probe_client/probe_server pair per trial (ITERS=1)
  for f in none local_qp_err rem_access rem_inv_req rnr retry_server_qp_err retry_proc_sigkill partial_write; do
    n=10; [ "$f" = none ] && n=5
    for t in $(seq "$(nn "$n")"); do
      trial "cpu_${f}_t$t" env RESULTS_DIR="$OUT/csv" ITERS=1 bash "$H/run.sh" "$f"
    done
  done ;;
gp|gg)
  B=proxy; [ "$STACK" = gg ] && B=gdaki
  export GIN_ABORT_WATCHDOG_S=30 WATCHDOG_S=120
  cells="none:timeout:5"
  if [ "$STACK" = gp ]; then cells="$cells F1:timeout:10 F2:timeout:10 F3:timeout:10 F4:timeout:10"
  else cells="$cells F1:blocking:5 F2:blocking:10 F3:blocking:10 F4:blocking:10"; fi
  for c in $cells; do
    IFS=: read -r f m n <<< "$c"
    for t in $(seq "$(nn "$n")"); do
      trial "${STACK}_${f}_${m}_t$t" bash "$G/gin/scripts/run_trial.sh" "$B" "$f" "$m" "$t" "$OUT/${STACK}.csv"
    done
  done ;;
gq)
  export GIN_ABORT_WATCHDOG_S=30 WATCHDOG_S=120 CLASSIFY=1
  for c in none:timeout:5 F1:blocking:5 F2:blocking:5 F3:blocking:5 F4:timeout:5; do
    IFS=: read -r f m n <<< "$c"
    for t in $(seq "$(nn "$n")"); do
      trial "gq_${f}_${m}_t$t" bash "$G/gin_q4/scripts/run_trial.sh" "$f" "$m" "$t" "$OUT/gq.csv"
    done
  done ;;
nvo)
  export FINALIZE=1
  for k in 0 1; do
    for v in "stock cpu_host_memory NC" "stock gpu NG" "fix cpu_host_memory NX"; do
      read -r lib handler id <<< "$v"
      for t in $(seq "$(nn 5)"); do
        trial "nvo_${id}_kill${k}_t$t" bash "$G/nvshmem_rootcause/official380/run.sh" "$lib" "$handler" "$k" "$t" "$OUT/runs"
      done
    done
  done ;;
nvd)
  for h in auto cpu_host_memory; do
    for f in F1 F2b F3; do
      for t in $(seq "$(nn 5)"); do
        trial "nvd_${h}_${f}_t$t" env NIC_HANDLER="$h" bash "$G/nvshmem/run_trial.sh" "$f" timeout "$t" "$OUT/runs_$h"
      done
    done
  done ;;
nvf)
  for f in none F1 F2b F3 F4; do
    for t in $(seq "$(nn 5)"); do
      trial "nvf_${f}_t$t" env RING=1 RECOVER=1 BOUNDS=1 TAG=prop bash "$G/nvshmem_ft/scripts/v2/run_trial_v2.sh" "$f" timeout "$t" "$OUT/runs"
    done
  done ;;
net)
  # NCCL 2.23.4 net_ib (../../../nccl-integration/stage2/run_tests.py): T0s = no fault (flag on),
  # F2 = corrupted rkey with recovery on, F2stock = the same with recovery off (stock error path)
  for c in T0s:5 F2:10 F2stock:10; do
    IFS=: read -r id n <<< "$c"
    for t in $(seq "$(nn "$n")"); do
      trial "net_${id}_t$t" python3 "$H/nccl-integration/stage2/run_tests.py" --out "$OUT/runs/${id}_t$t" --tests "$id" --n 1
    done
  done ;;
*) echo "unknown stack $STACK" >&2; exit 2 ;;
esac
