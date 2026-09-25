#!/usr/bin/env bash
# rec_one.sh <bundle: v2|v1> <fault> <wait> <trial-tag> <iters> <logdir> [VAR=value ...]
# One GIN GDAKI recovery trial with the UNCHANGED runner ../gin_recovery/scripts/run_trial.sh
# (which already runs the GIN proxy-thread probe on both ranks), DOCA_GPUNETIO_LOG=4, and the
# given bundle (v2 = ~/gi-bundle/gin_recovery_gpudb, v1 = ~/gi-bundle/gin_recovery), plus the
# nvidia driver configuration of both nodes. Settings per cell as in gin_recovery/scripts/run_gpudb.sh.
set -u
B=$1; F=$2; W=$3; T=$4; IT=$5; L=$6; shift 6
A=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad/agent_n30
G=/home/unionxic/rdma-error/harness/gpu-initiated
case "$B" in
  v2) BUNDLE=/home/unionxic/gi-bundle/gin_recovery_gpudb ;;
  v1) BUNDLE=/home/unionxic/gi-bundle/gin_recovery ;;
  *) echo "bundle?" >&2; exit 2 ;;
esac
mkdir -p "$L"
REC=1
for kvp in "$@"; do case "$kvp" in REC=*) REC=${kvp#REC=} ;; esac; done
stem="rec${REC}_${F}_${W}_${T}"
bash "$A/bin/drvcfg.sh" "$L/${stem}_drv.txt"
env BUNDLE=$BUNDLE DOCA_LOG=4 REC_WORKDIR=$A/work "$@" bash "$G/gin_recovery/scripts/run_trial.sh" "$F" "$W" "$T" "$L" "$IT" 14
echo "[rec $B $stem] $(grep -o 'r0_gin_proxy_thread=[^ ]* .*r1_gin_proxy_thread=[^ ]*' "$L/${stem}_meta.txt" 2>/dev/null) dbmode_r0=$(grep -o 'doorbell mode=[A-Z_]*' "$L/${stem}_r0.log" 2>/dev/null | sort | uniq -c | tr '\n' ' ') cpu_proxy_lines r0=$(grep -c 'Enabling CPU proxy mode' "$L/${stem}_r0.log" 2>/dev/null)" >&2
