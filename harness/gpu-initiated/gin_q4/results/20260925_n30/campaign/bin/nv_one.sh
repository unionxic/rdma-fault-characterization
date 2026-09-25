#!/usr/bin/env bash
# nv_one.sh <fault> <mode> <trial> <outdir> [VAR=value ...]
# One NVSHMEM IBGDA FT trial with the UNCHANGED runner ../nvshmem_ft/scripts/run_trial.sh and bundle
# ~/gi-bundle/nvshmem_ft (GPU NIC handler by default, "auto"), plus the nvidia driver configuration
# of both nodes (<tag>.drv next to the trial's .meta).
set -u
F=$1; M=$2; T=$3; O=$4; shift 4
A=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad/agent_n30
G=/home/unionxic/rdma-error/harness/gpu-initiated
mkdir -p "$O"
FT=1; RECOVER=0; TAG=""
for kvp in "$@"; do case "$kvp" in FT=*) FT=${kvp#FT=} ;; RECOVER=*) RECOVER=${kvp#RECOVER=} ;; TAG=*) TAG=${kvp#TAG=} ;; esac; done
tag="${F}_${M}_ft${FT}_rec${RECOVER}${TAG:+_$TAG}_t${T}"
bash "$A/bin/drvcfg.sh" "$O/${tag}.drv"
env "$@" bash "$G/nvshmem_ft/scripts/run_trial.sh" "$F" "$M" "$T" "$O"
echo "[nv $tag] handler: $(grep -h -o 'NIC handler will be [A-Za-z]*' "$O/${tag}.pe0.log" "$O/${tag}.pe1.log" 2>/dev/null | sort | uniq -c | tr '\n' ' ') $(grep -h -o 'handler=[A-Za-z_]*' "$O/${tag}.pe0.log" 2>/dev/null | head -1)" >&2
