#!/usr/bin/env bash
# Regenerate ../../gin_transparent_s2.diff: the FULL diff of the S2 source tree against pristine NCCL v2.32.3-1
# (12df1a11): the four earlier layers, S1 and S2 in one patch. The scratch tree is a git repo with commit 1 =
# pristine v2.32.3-1 (git archive) and commit 2 = the four earlier diffs applied; the working tree = + S1 + S2.
# Then check that the patch applied to a pristine tree reproduces the working tree exactly.
set -euo pipefail
SRC=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad/agent_ts2/nccl-src
S1SRC=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad/agent_ts1/nccl-src
OUT=$(cd "$(dirname "$0")/../.." && pwd)/gin_transparent_s2.diff
BASE=$(git -C "$SRC" rev-list --max-parents=0 HEAD)
{
cat <<'HDR'
# GIN GDAKI transparent recovery, step S2 (research build): many operations in flight, many posting threads,
# a single-word device gate, symmetric initiation, GID re-lookup on reconnect, and the post-commit residual
# closed. The application is unmodified: no error returned to its kernel or host, no relaunch.
# Env-gated: nothing changes unless NCCL_GIN_FAULT_TRANSPARENT=1 (default 0).
#
# base tag: v2.32.3-1  commit: 12df1a11afad322be5a204a2db890161cbf8131d
# This is a FULL diff against the pristine base: the four layers gin_recovery_gpudb.diff sits on, S1
# (gin_transparent_s1.diff) and S2:
#   1. ../gin/gin_fault_inject.diff        fault-injection hook (NCCL_GIN_FAULT_INJECT)
#   2. ../gin_q4/gin_q4_classify.diff      device error-CQE classifier + host mailbox (NCCL_GIN_FAULT_CLASSIFY)
#   3. gin_recovery.diff                   Prepare/Commit recovery API (NCCL_GIN_FAULT_RECOVERY)
#   4. gin_recovery_gpudb.diff             GPU-rung doorbells in Prepare/Commit
#   5. S1                                  device pause gate + hold-and-rebase waits + in-library helper
#   6. S2 (this step)                      see below
# Apply to a pristine tree:  git apply gin_transparent_s2.diff
#
# S2 changes (TRANSPARENT_S2.md):
#   include/nccl_device/gin/gdaki/gin_gdaki_device_host_common.h, gin_gdaki.h  one 64-bit gate word per QP
#       (reserved1 padding): epoch half written by the host (4-byte copy), count half by the device; posters and
#       pollers enter with one atomic add whose return carries the epoch and leave with a release add (no SC
#       fence); device failure bit in the count half; PUBLISHING bit and tsLateFail (second Dekker: a device
#       thread whose second hold expires either fails before the host re-posts, or waits for the publication)
#   transport/net_ib/gdaki/doca-gpunetio/include/device/doca_gpunetio_dev_verbs_qp.cuh  (NCCL's vendored DOCA)
#       the SQ-slot wait of a gated QP keeps a copy of a slot's WQE that completed in error before reusing the slot
#       (rescue area), polls the slot's CQE without DOCA's cqe_ci window, and rings ready-but-unrung WQEs it waits
#       for while a recovery quiesces the QP; ungated QPs unchanged
#   transport/net_ib/gdaki/gin_host_gdaki.cc  quiesce/publish/decline on the gate word; the host rings WQEs that
#       aggregated posts left unrung before Prepare; re-post from the slot or the rescue area, with one copy each
#       way, in chunks when it is larger than the SQ ring (the host reads the re-posted WQEs' CQEs, then sets the
#       CQ consumer index); tie-break for simultaneous initiation (the lower rank keeps the round, the higher rank
#       answers it as responder, reusing its own quiesce/Prepare); local GID looked up by value before every
#       reconnect, waiting (NCCL_GIN_TS_PATH_WAIT_MS) for an address that is not back yet; handshake bounds grow by
#       that wait; PUBLISHING mark before the re-post; test knobs NCCL_GIN_FAULT_INJECT_AT=wqe:<n>|sig:<n>,
#       NCCL_GIN_TS_TEST_STALL=<ms>@publishing, NCCL_GIN_TS_TEST_SELF_REPORT=1, NCCL_GIN_TS_TIE_BREAK=0 (S1)
#   review fixes (2026-10-01, TRANSPARENT_S2.md "Review fixes"): NCCL_GIN_TS_PATH_WAIT_MS clamped to
#       min(ROUND_MS, HOLD_MS) - HANDSHAKE_MS - 1 s (21 s by default) and every in-round wait cut to what is left of
#       the round; the slot wait rings on an odd epoch, on HOST_FAILED and after 16 K spins; the slot wait records the
#       first error CQE it sees (gate word swErr) and the poster reports it after its post (Q4 path post-slot-wait,
#       ticket = the CQ consumer index), the classifier uses the record when the CQ window holds no current root;
#       gdakiTsRing masks the 16-bit WQE index
# env (S2, in addition to S1's): NCCL_GIN_TS_PATH_WAIT_MS (30000, clamped), NCCL_GIN_TS_TIE_BREAK (1),
#   NCCL_GIN_TS_RESCUE_LAPS (32)
#
HDR
cd "$SRC" && git diff "$BASE" -- src
} > "$OUT"
echo "wrote $OUT ($(wc -c < "$OUT") bytes)"
echo "S2 alone vs S1 tree:"; diff -ru "$S1SRC/src" "$SRC/src" | diffstat 2>/dev/null | tail -3 || true
# verify: pristine + patch == working tree
T=$(mktemp -d)
git -C "$SRC" archive "$BASE" | tar -x -C "$T"
(cd "$T" && git apply "$OUT")
if diff -r -q "$T/src" "$SRC/src" > "$T.diff" 2>&1; then echo "VERIFIED: pristine v2.32.3-1 + gin_transparent_s2.diff == the S2 source tree"
else echo "MISMATCH:"; head "$T.diff"; rm -rf "$T" "$T.diff"; exit 1; fi
rm -rf "$T" "$T.diff"
