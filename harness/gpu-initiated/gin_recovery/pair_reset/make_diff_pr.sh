#!/usr/bin/env bash
# Write this study's NCCL patches from the scratch tree agent_ts2pr (git: pristine v2.32.3-1 -> the four earlier
# layers -> step 2 final -> gin-s2-close s2r -> gin-reconnect rc, all committed; the working tree adds this study's
# pair-reset layer):
#   gin_transparent_pr.diff  the FULL diff against pristine NCCL v2.32.3-1
#   pr_layer.diff            this study's change alone, against the gin-reconnect tree (../reconnect/gin_transparent_rc.diff)
# and check that pristine + the full diff, and the rc tree + the layer diff, both reproduce the working tree.
set -euo pipefail
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
SRC=$SCR/agent_ts2pr/nccl-src
D=$(cd "$(dirname "$0")" && pwd)
BASE=$(git -C "$SRC" rev-list --max-parents=0 HEAD)
{
cat <<'HDR'
# GIN GDAKI transparent recovery, step 2 + gin-s2-close + gin-reconnect + gin-pair-reset (research build). FULL diff
# against pristine NCCL v2.32.3-1 (12df1a11): the four earlier layers, step 1, step 2, gin-s2-close, gin-reconnect
# (../reconnect/rc_layer.diff) and this study's change (pr_layer.diff, EXPERIMENT.md section 9), all in
# src/transport/net_ib/gdaki/gin_host_gdaki.cc:
#   a recovery round covers only the faulted GIN context's QP pair (scope mask of the helper's QP walks) when
#   NCCL_GIN_TS_PAIR_RESET=1 (default), this rank's other QPs to the peer are RTS and no other context's fault for the
#   peer is queued; otherwise every context as before; the scope travels in REQ/ACK (pad, 0 = every context); a
#   simultaneous round with a different scope makes the higher rank answer the lower rank's round and requeue its own
#   fault as a full reset; declines stay full; test knob NCCL_GIN_FAULT_INJECT_CTX=<c> (the fault hook moves only
#   context c's QPs); log lines: pair reset, scope decision, scope in the recovered lines, scope conflict, gate epochs
# Apply to a pristine tree:  git apply gin_transparent_pr.diff
#
HDR
git -C "$SRC" diff "$BASE" -- src
} > "$D/gin_transparent_pr.diff"
git -C "$SRC" diff HEAD -- src > "$D/pr_layer.diff"
echo "wrote gin_transparent_pr.diff ($(wc -c < "$D/gin_transparent_pr.diff") bytes), pr_layer.diff ($(wc -c < "$D/pr_layer.diff") bytes)"
T=$(mktemp -d)
git -C "$SRC" archive "$BASE" | tar -x -C "$T"
(cd "$T" && git apply "$D/gin_transparent_pr.diff")
diff -r -q "$T/src" "$SRC/src" && echo "VERIFIED: pristine v2.32.3-1 + gin_transparent_pr.diff == the pr source tree"
rm -rf "$T"; T=$(mktemp -d)
git -C "$SRC" archive "$BASE" | tar -x -C "$T"
(cd "$T" && git apply "$D/../reconnect/gin_transparent_rc.diff" && git apply "$D/pr_layer.diff")
diff -r -q "$T/src" "$SRC/src" && echo "VERIFIED: pristine + ../reconnect/gin_transparent_rc.diff + pr_layer.diff == the pr source tree"
rm -rf "$T"
