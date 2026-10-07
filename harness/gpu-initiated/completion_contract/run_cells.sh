#!/usr/bin/env bash
# run_cells.sh <nvs|gin> <outroot> [n_override] - the pre-registered cells of completion_contract.
# Run it inside ../common/cluster_run.sh, one call per group. Each cell writes to its own folder
# (<outroot>/P1 ...), because the runners name files by fault, wait mode and trial only.
#   nvs: P1 (3.4.5 CPU proxy, peer killed, 10), P2 (3.4.5 GPU handler, killed, 5),
#        P3 (3.4.5 CPU proxy, no kill, 5)                   -> ../nvshmem_rootcause/official380/run.sh
#   gin: P4 (GDAKI handler 6, no fault, 10), P5 (default handler, no fault, 5),
#        P6 (handler 1, F1 F2 F3, 5 each), P7 (handler 1, no fault, 5) -> ../gin/scripts/run_trial.sh
# n_override replaces every count (smoke runs only).
set -u
GROUP=$1; ROOT=$2; NO=${3:-}
mkdir -p "$ROOT"; ROOT=$(cd "$ROOT" && pwd)
G=$(cd "$(dirname "$0")/.." && pwd)            # harness/gpu-initiated
n() { echo "${NO:-$1}"; }
log() { echo "$* $(date +%T)"; }

case "$GROUP" in
nvs)
  export NVS_BUNDLE=$HOME/gi-bundle/nvshmem_345
  for c in "P1 cpu_host_memory 1 10" "P2 gpu 1 5" "P3 cpu_host_memory 0 5"; do
    set -- $c
    mkdir -p "$ROOT/$1"
    for t in $(seq "$(n $4)"); do
      bash "$G/nvshmem_rootcause/official380/run.sh" stock "$2" "$3" "$t" "$ROOT/$1" >> "$ROOT/$1/trials.csv"
      log "$1 t$t"
    done
  done ;;
gin)
  export GIN_ABORT_WATCHDOG_S=30 WATCHDOG_S=120 NCCL_DEBUG=INFO NCCL_DEBUG_SUBSYS=INIT,NET
  run() {  # cell handler(or -) fault count
    local cell=$1 h=$2 f=$3 cnt=$4 extra=""
    [ "$h" != - ] && extra="NCCL_GIN_GDAKI_NIC_HANDLER=$h"
    mkdir -p "$ROOT/$cell"
    for t in $(seq "$(n $cnt)"); do
      GIN_EXTRA_ENV="$extra" bash "$G/gin/scripts/run_trial.sh" gdaki "$f" timeout "$t" "$ROOT/$cell/gin.csv" \
        > "$ROOT/$cell/gdaki_${f}_timeout_t${t}.out" 2>&1
      log "$cell $f t$t"
    done
  }
  run P4 6 none 10
  run P5 - none 5
  for f in F1 F2 F3; do run P6 1 "$f" 5; done
  run P7 1 none 5 ;;
*) echo "unknown group $GROUP" >&2; exit 2 ;;
esac
