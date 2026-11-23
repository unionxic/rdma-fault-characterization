#!/usr/bin/env bash
# make_diff.sh - write nvshmem_ibgda_t1_380.diff (the port as one full diff against official v3.8.0-0 +
# ../../nvshmem/nvshmem_ibgda_fault_inject.diff + ../../nvshmem_rootcause/nvshmem_nrc_proxy_sq_dbr.diff)
# from <scratch>/agent_t1_380/src, then check that it re-applies on pristine v3.8.0-0 + the two layers
# and reproduces the tree.
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
G=$HERE/../..
SCRATCH=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
SRC=$SCRATCH/agent_t1_380/src
OUT=$HERE/nvshmem_ibgda_t1_380.diff
BASE=$(cd "$SRC" && git log --format=%H --grep='^base: v3.8.0-0 + inject + nrc' | tail -1)
{
cat <<'HDR'
# NVSHMEM IBGDA transparent recovery on official NVSHMEM v3.8.0-0 (research): the t1_close build b2
# (../t1_close/nvshmem_ibgda_t1close.diff) ported to v3.8.0-0. The only hand edit is the barrier.cpp
# hunk, whose include context differs in 3.8.0; the code it adds is the same.
#
# Base:     NVSHMEM v3.8.0-0 (tag commit 270759e5, github.com/NVIDIA/nvshmem)
# Layering: apply ../../nvshmem/nvshmem_ibgda_fault_inject.diff, then
#           ../../nvshmem_rootcause/nvshmem_nrc_proxy_sq_dbr.diff (default-off record knob), then this file.
#           The two-line CPU-proxy doorbell-record fix is NOT applied (transparent recovery needs the GPU
#           NIC handler; see EXPERIMENT.md section 4).
HDR
cd "$SRC" && git diff "$BASE" -- src nvshmem_transport.sym
} > "$OUT"
echo "wrote $OUT ($(wc -l < "$OUT") lines, md5 $(md5sum < "$OUT" | cut -c1-8))"
T=$(mktemp -d "$SCRATCH/agent_t1_380/verify.XXXX")
(cd $SCRATCH/ibgda/nvshmem && git archive v3.8.0-0) | tar -x -C "$T"
cd "$T"
git apply "$G/nvshmem/nvshmem_ibgda_fault_inject.diff"
git apply "$G/nvshmem_rootcause/nvshmem_nrc_proxy_sq_dbr.diff"
git apply "$OUT"
if diff -r -q "$T/src" "$SRC/src" | grep -v -E "Only in $SRC/src.*(nvshmem_version.h|transfer_device.cuh|nvshmem_build_options.h|nvshmemi_build_metadata.h|: comm)$" ; then
  echo "VERIFY: trees differ"; exit 1
fi
diff -q "$T/nvshmem_transport.sym" "$SRC/nvshmem_transport.sym" && echo "VERIFY: diff re-applies on pristine v3.8.0-0 + the two layers and reproduces the tree"
rm -rf "$T"
