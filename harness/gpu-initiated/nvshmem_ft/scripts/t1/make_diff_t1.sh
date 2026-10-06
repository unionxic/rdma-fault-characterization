#!/usr/bin/env bash
# make_diff_t1.sh - regenerate ../../nvshmem_ibgda_transparent.diff from the scratch tree
# <scratch>/agent_nvt1/src (a copy of the v2.2 tree; git: ... -> "v2.2 (third review; diff 3aa1f0de)" ->
# working tree = T1), as a full diff against the same base as nvshmem_ibgda_ft_v2.diff (NVSHMEM 7bb2e99c +
# ../nvshmem/nvshmem_ibgda_fault_inject.diff + ../nvshmem_rootcause/nvshmem_nrc_proxy_sq_dbr.diff), and
# verify that it re-applies on that base and reproduces the tree.
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
G=$HERE/../../..
SCRATCH=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
SRC=$SCRATCH/agent_nvt1/src
OUT=$HERE/../../nvshmem_ibgda_transparent.diff
BASE=$(cd "$SRC" && git log --format=%H --grep='^base: 7bb2e99c + inject + nrc' | tail -1)
{
cat <<'HDR'
# NVSHMEM IBGDA fault tolerance T1 (research): transparent recovery inside the library, on top of
# FT v2.2 (nvshmem_ibgda_ft_v2.diff, contained here unchanged except where T1 hooks into it).
#
# Base:     NVSHMEM commit 7bb2e99c (github.com/NVIDIA/nvshmem)
# Layering: apply ../nvshmem/nvshmem_ibgda_fault_inject.diff, then
#           ../nvshmem_rootcause/nvshmem_nrc_proxy_sq_dbr.diff, then this file (git apply).
#           Full diff against that base: it contains v1, v2, v2.1 and v2.2; apply it instead of
#           nvshmem_ibgda_ft_v2.diff, not on top of it.
# Gate:     NVSHMEM_IBGDA_FT_TRANSPARENT=1 with NVSHMEM_IBGDA_FT=1 and NVSHMEM_IBGDA_FT_RING_CQ=1 (GPU NIC
#           handler, park on). Unset: as v2.2 (device: a few __constant__ flag tests per post/wait).
# T1:       per-RC-QP gate in GPU memory (epoch + counted posters in one 64-bit word; held posters;
#           index offset; WQEBB surplus); posters counted from reserve to submit, held across a
#           recovery in the slot wait and the ready CAS; waiters keep a logical ticket and hold across
#           a recovery; a helper thread in the transport runs the whole recovery (policy, library TCP
#           socket per peer, quiesce, drain, executed prefix from the responder's rmsn, rebase to the
#           next multiple of 65536, send-ring rotation, re-post with a host doorbell, GID re-lookup by
#           value, commit-point give-up handshake, watchdog, teardown); declines surface through
#           nvshmemx_ibgda_ft_status / nvshmemt_ibgda_ft_query and the failed-transport teardown path.
# Env (T1): NVSHMEM_IBGDA_FT_T1_HOLD_MS ROUND_MS QUIESCE_MS HANDSHAKE_MS GID_WAIT_MS IFNAME,
#           NVSHMEM_IBGDA_FT_T1_TEST_SKIP=remap,ring,rotate,prefix,gid (test-only negative controls);
#           fault hook: NVSHMEM_IBGDA_FAULT_INJECT=rem_access:<ms> (responder revokes remote access).
# Design:   harness/gpu-initiated/nvshmem_ft/TRANSPARENT_T1.md (v2.2: V2.md)
HDR
cd "$SRC" && git diff "$BASE" -- src nvshmem_transport.sym
} > "$OUT"
echo "wrote $OUT ($(wc -l < "$OUT") lines, md5 $(md5sum < "$OUT" | cut -c1-8))"
T=$(mktemp -d "$SCRATCH/agent_nvt1/verify.XXXX")
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
