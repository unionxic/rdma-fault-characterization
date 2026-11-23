#!/usr/bin/env bash
# make_diff.sh - write nvshmem_ibgda_t1close.diff (the t1_close library as one full diff against the
# same base as ../nvshmem_ibgda_transparent.diff) from <scratch>/agent_nvt1/src, then check that it
# re-applies on NVSHMEM 7bb2e99c + the fault-inject diff + the CPU-proxy record diff and reproduces the
# tree. ../nvshmem_ibgda_transparent.diff (final3) is left as it is.
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
G=$HERE/../..
SCRATCH=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
SRC=$SCRATCH/agent_nvt1/src
OUT=$HERE/nvshmem_ibgda_t1close.diff
BASE=$(cd "$SRC" && git log --format=%H --grep='^base: 7bb2e99c + inject + nrc' | tail -1)
{
cat <<'HDR'
# NVSHMEM IBGDA transparent recovery, t1_close build (research): final3 (../nvshmem_ibgda_transparent.diff)
# plus the changes of the t1_close study (EXPERIMENT.md section 9):
#   - bounded device-state copies poll without sleeping for the first 200 us (t1_sync)
#   - a fetching AMO in [C, R) is re-posted when the responder did not execute it; one it executed
#     declines ("executed by the responder"); DUMP counts as a local WQE (t1_prepare, t1_prefix)
#   - RECOVERED/DECLINE lines carry nqps, fetch_cr, fetch_exec, fetch_reposted, ops_cr; the RECOVERED
#     per-QP text is a std::string (the 512-byte buffer could overflow with 4-5 QPs)
#   - the atexit hook logs "ATEXIT helper=joined|detached join_ms=..."
#   - NVSHMEM_IBGDA_FT_T1_TEST_SKIP takes comma-separated tokens compared exactly; new tokens spin,
#     fetchrepost, fetchexec (test-only)
#
# Base:     NVSHMEM commit 7bb2e99c (github.com/NVIDIA/nvshmem)
# Layering: apply ../../nvshmem/nvshmem_ibgda_fault_inject.diff, then
#           ../../nvshmem_rootcause/nvshmem_nrc_proxy_sq_dbr.diff, then this file (git apply). Full diff:
#           apply it instead of nvshmem_ibgda_transparent.diff or nvshmem_ibgda_ft_v2.diff.
HDR
cd "$SRC" && git diff "$BASE" -- src nvshmem_transport.sym
} > "$OUT"
echo "wrote $OUT ($(wc -l < "$OUT") lines, md5 $(md5sum < "$OUT" | cut -c1-8))"
T=$(mktemp -d "$SCRATCH/agent_t1close/verify.XXXX")
(cd $SCRATCH/ibgda/nvshmem && git archive 7bb2e99c) | tar -x -C "$T"
cd "$T"
git apply "$G/nvshmem/nvshmem_ibgda_fault_inject.diff"
git apply "$G/nvshmem_rootcause/nvshmem_nrc_proxy_sq_dbr.diff"
git apply "$OUT"
if diff -r -q "$T/src" "$SRC/src" | grep -v -E "Only in $SRC/src.*(nvshmem_version.h|transfer_device.cuh|nvshmem_build_options.h|nvshmemi_build_metadata.h|: comm)$" ; then
  echo "VERIFY: trees differ"; exit 1
fi
diff -q "$T/nvshmem_transport.sym" "$SRC/nvshmem_transport.sym" && echo "VERIFY: diff re-applies on the base and reproduces the tree"
rm -rf "$T"
