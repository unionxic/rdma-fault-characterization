#!/usr/bin/env bash
# Write this study's NCCL patches from the scratch tree agent_ts2pc (git: pristine v2.32.3-1 -> the four earlier
# layers -> step 2 final -> gin-s2-close s2r -> gin-reconnect rc -> gin-pair-reset pr, all committed; the working tree adds this study's
# pair-check layer):
#   gin_transparent_pc.diff  the FULL diff against pristine NCCL v2.32.3-1
#   pc_layer.diff            this study's change alone, against the gin-pair-reset tree (../pair_reset/gin_transparent_pr.diff)
# and check that pristine + the full diff, and the pr tree + the layer diff, both reproduce the working tree.
set -euo pipefail
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
SRC=$SCR/agent_ts2pc/nccl-src
D=$(cd "$(dirname "$0")" && pwd)
BASE=$(git -C "$SRC" rev-list --max-parents=0 HEAD)
{
cat <<'HDR'
# GIN GDAKI transparent recovery, step 2 + gin-s2-close + gin-reconnect + gin-pair-reset + gin-pair-check (research build).
# FULL diff against pristine NCCL v2.32.3-1 (12df1a11): the four earlier layers, step 1, step 2, gin-s2-close,
# gin-reconnect, gin-pair-reset (../pair_reset/pr_layer.diff) and this study's change (pc_layer.diff, EXPERIMENT.md
# section 9), all in src/transport/net_ib/gdaki/gin_host_gdaki.cc:
#   before answering a narrowed REQ the answering rank queries its own QPs to the initiator outside the scope and refuses
#   (NACK 12, nothing paused) if any is not RTS, or if its own NCCL_GIN_TS_PAIR_RESET is 0; the initiator then reruns the
#   round as a full reset (reason peer); after a scope conflict the higher rank's fault decides its scope again (a second
#   conflict: full); a mask equal to every context is sent as 0; NCCL_GIN_TS_PAIR_CHECK=0|1; log lines: pair check,
#   check accepted/refused, rerun, QP states at teardown
# Apply to a pristine tree:  git apply gin_transparent_pc.diff
#
HDR
git -C "$SRC" diff "$BASE" -- src
} > "$D/gin_transparent_pc.diff"
git -C "$SRC" diff HEAD -- src > "$D/pc_layer.diff"
echo "wrote gin_transparent_pc.diff ($(wc -c < "$D/gin_transparent_pc.diff") bytes), pc_layer.diff ($(wc -c < "$D/pc_layer.diff") bytes)"
T=$(mktemp -d)
git -C "$SRC" archive "$BASE" | tar -x -C "$T"
(cd "$T" && git apply "$D/gin_transparent_pc.diff")
diff -r -q "$T/src" "$SRC/src" && echo "VERIFIED: pristine v2.32.3-1 + gin_transparent_pc.diff == the pc source tree"
rm -rf "$T"; T=$(mktemp -d)
git -C "$SRC" archive "$BASE" | tar -x -C "$T"
(cd "$T" && git apply "$D/../pair_reset/gin_transparent_pr.diff" && git apply "$D/pc_layer.diff")
diff -r -q "$T/src" "$SRC/src" && echo "VERIFIED: pristine + ../pair_reset/gin_transparent_pr.diff + pc_layer.diff == the pc source tree"
rm -rf "$T"
