#!/usr/bin/env bash
# make_diff_v2.sh - regenerate ../../nvshmem_ibgda_ft_v2.diff from the scratch source tree
# <scratch>/agent_ftv2/src (a git repo: commit "base: 7bb2e99c + inject + nrc" = the same base as
# the v1 diff) and verify that it re-applies on a pristine 7bb2e99c + the two base diffs and
# reproduces the tree. The v2 diff is a full diff against that base (it contains v1).
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
G=$HERE/../../..
SCRATCH=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
SRC=$SCRATCH/agent_ftv2/src
OUT=$HERE/../../nvshmem_ibgda_ft_v2.diff
BASE=$(cd "$SRC" && git log --format=%H --grep='^base: 7bb2e99c + inject + nrc' | tail -1)
{
cat <<'HDR'
# NVSHMEM IBGDA fault tolerance v2 (research): v1 (device classification + host mailbox + recovery)
# plus (A) ring send CQs walked by the device, (B) device bounds check of remote ranges, (C) test-only
# negative-control knobs for the recovery resync.
#
# Base:     NVSHMEM commit 7bb2e99c (github.com/NVIDIA/nvshmem)
# Layering: apply ../nvshmem/nvshmem_ibgda_fault_inject.diff, then
#           ../nvshmem_rootcause/nvshmem_nrc_proxy_sq_dbr.diff, then this file (git apply).
#           This is a full diff against that base: it contains nvshmem_ibgda_ft.diff (v1); do not
#           apply both.
# Gate:     NVSHMEM_IBGDA_FT=1 (default off). Flag off: as v1 flag off, plus one __constant__ flag
#           read per RMA/AMO call (bounds gate); no host thread, no buffer, same DEVX commands.
# Env (v1): NVSHMEM_IBGDA_FT_POLL_US, NVSHMEM_IBGDA_FT_CAPTURE=exit, NVSHMEM_IBGDA_FT_DRAIN_MS,
#           NVSHMEM_IBGDA_FT_QUIET, NVSHMEM_IBGDA_FAULT_INJECT=<act>:<ms>[,<d2>...]
# Env (v2): NVSHMEM_IBGDA_FT_RING_CQ=1  send CQs created with cc=0 (oi=1); device waits walk them by
#             consumer counter and never consume an error CQE, so the root cause stays until a
#             wait records it (GPU NIC handler only)
#           NVSHMEM_IBGDA_FT_BOUNDS=1   remote range checked against the heap allocator's in-use
#             chunks (host library publishes them) before an RMA/AMO is posted; violation -> not
#             posted, sticky record class OOB_WRITE/OOB_READ, status/bounded quiet report it
#           NVSHMEM_IBGDA_FT_BOUNDS_GUARD=<bytes>  (with BOUNDS) red zone after every symmetric
#             allocation, published as free (an overrun starting at an object's end is caught)
#           NVSHMEM_IBGDA_FT_TEST_SKIP=<idx,lock,ibuf,sticky,cqfill,dbr,nerr,dci,psn,finbar,ringci,park>
#             test-only: skip one step of the recovery resync / teardown handling (park: v2 posting)
# v2.1:     park (on with FT): a QP with a recorded CQE error or ring invariant gets prod_idx raised
#             to a mark (2^63), so later posts never write the doorbell record or ring; the drain
#             waits for the doorbell record's send word; recovery removes the mark. No post-path
#             instruction added.
#           ring-walk invariant: a consumed CQE whose advance d is outside 1..ncqes is recorded
#             (class RING_INVARIANT, sticky opcode 0xf) and fails the wait; policy: decline
#           NVSHMEM_IBGDA_FT_TEST_TRIP=ring_d:<n> | ring_d_silent:<n>  test-only: force d = 0 at the
#             n-th consumed ring CQE (record + error, or v2's silent consumption)
# Design:   harness/gpu-initiated/nvshmem_ft/V2.md (v1: DESIGN.md)
HDR
cd "$SRC" && git diff "$BASE" -- src nvshmem_transport.sym
} > "$OUT"
echo "wrote $OUT ($(wc -l < "$OUT") lines)"
T=$(mktemp -d "$SCRATCH/agent_ftv2/verify.XXXX")
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
