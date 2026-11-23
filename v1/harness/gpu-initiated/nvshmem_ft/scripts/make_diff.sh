#!/usr/bin/env bash
# make_diff.sh - regenerate ../nvshmem_ibgda_ft.diff from the scratch source tree (a git repo whose
# commit "fault_inject + nrc" = 7bb2e99c + the two earlier diffs) and verify that it re-applies on a
# pristine 7bb2e99c + the base diffs and reproduces the tree.
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
G=$HERE/../..
SCRATCH=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
SRC=$SCRATCH/gi/nvshmem_ft/src
OUT=$HERE/../nvshmem_ibgda_ft.diff
{
cat <<'HDR'
# NVSHMEM IBGDA fault tolerance: device classification + host mailbox + recovery (research)
#
# Base:     NVSHMEM commit 7bb2e99c (github.com/NVIDIA/nvshmem)
# Layering: apply ../nvshmem/nvshmem_ibgda_fault_inject.diff, then
#           ../nvshmem_rootcause/nvshmem_nrc_proxy_sq_dbr.diff, then this file (git apply).
# Gate:     NVSHMEM_IBGDA_FT=1 (default off). Off: one extra __constant__ pointer read per CQ poll,
#           no host thread, no buffer; connect issues the same DEVX commands with the same values.
# Env:      NVSHMEM_IBGDA_FT_POLL_US (watcher period, 50), NVSHMEM_IBGDA_FT_CAPTURE=exit (diagnostic:
#           classify only the CQE that ends the wait), NVSHMEM_IBGDA_FT_DRAIN_MS (1000),
#           NVSHMEM_IBGDA_FT_QUIET=1 (no log lines), NVSHMEM_IBGDA_FAULT_INJECT=<act>:<ms>[,<d2>...]
#           (multi-shot hook: shot k fires d_k ms after the recovery commit of shot k-1; -1 = inside it)
# Files:    include/device_host_transport/nvshmem_common_ibgda.h  per-QP sticky record in the mvars
#             padding, FT pointer in the device-state padding (sizes unchanged), record/API types
#           include/non_abi/device/pt-to-pt/ibgda_device.cuh  in-loop capture in ibgda_poll_cq,
#             fail-fast waits, nvshmemx_ibgda_ft_status/_quiet_bounded/_sentinel
#           modules/transport/ibgda/ibgda.cpp  mailbox + watcher, exported nvshmemt_ibgda_ft_*
#             (query/prepare/commit/abort/mark_failed/sentinel_stop/commits), PSN parameters on
#             INIT2RTR/RTR2RTS (default 0 = stock), peer handle kept at connect, multi-shot hook
#           host/coll/barrier/barrier.cpp, host/init/init.cu, internal headers: skip device barriers
#             once the transport is marked failed (NVSHMEM_TRANSPORT_ATTR_FT_FAILED)
#           nvshmem_transport.sym  export nvshmemt_ibgda_ft_*
# Design:   harness/gpu-initiated/nvshmem_ft/DESIGN.md
HDR
cd "$SRC" && git diff HEAD -- src nvshmem_transport.sym
} > "$OUT"
echo "wrote $OUT ($(wc -l < "$OUT") lines)"
# verify
T=$(mktemp -d "$SCRATCH/gi/nvshmem_ft/verify.XXXX")
(cd $SCRATCH/ibgda/nvshmem && git archive 7bb2e99c) | tar -x -C "$T"
cd "$T"
git apply "$G/nvshmem/nvshmem_ibgda_fault_inject.diff"
git apply "$G/nvshmem_rootcause/nvshmem_nrc_proxy_sq_dbr.diff"
git apply "$OUT"
if diff -r -q "$T/src" "$SRC/src" | grep -v -E "Only in $SRC/src.*(nvshmem_version.h|transfer_device.cuh|nvshmem_build_options.h|nvshmemi_build_metadata.h|: comm)$" ; then
  echo "VERIFY: trees differ"; exit 1
fi
diff -q "$T/nvshmem_transport.sym" "$SRC/nvshmem_transport.sym" && echo "VERIFY: diff re-applies and reproduces the tree"
rm -rf "$T"
