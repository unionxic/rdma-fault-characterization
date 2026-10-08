#!/usr/bin/env bash
# Write this study's NCCL patches from the scratch tree agent_ts2rc (git: pristine v2.32.3-1 -> the four earlier
# layers -> step 2 final -> gin-s2-close s2r, all committed; the working tree adds this study's reconnect layer):
#   gin_transparent_rc.diff  the FULL diff against pristine NCCL v2.32.3-1
#   rc_layer.diff            this study's change alone, against the gin-s2-close tree (../s2_close/gin_transparent_s2r.diff)
# and check that pristine + the full diff, and the s2r tree + the layer diff, both reproduce the working tree.
set -euo pipefail
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
SRC=$SCR/agent_ts2rc/nccl-src
D=$(cd "$(dirname "$0")" && pwd)
BASE=$(git -C "$SRC" rev-list --max-parents=0 HEAD)
{
cat <<'HDR'
# GIN GDAKI transparent recovery, step 2 + gin-s2-close + gin-reconnect (research build). FULL diff against pristine
# NCCL v2.32.3-1 (12df1a11): the four earlier layers, step 1, step 2, gin-s2-close (../s2_close/s2r_layer.diff) and this
# study's change (rc_layer.diff, EXPERIMENT.md section 9), all in src/transport/net_ib/gdaki/gin_host_gdaki.cc:
#   the helper socket's liveness three ways (dead: FIN, ECONNRESET, EPIPE, refused re-dial, BADMAGIC, other errno;
#   unknown: ETIMEDOUT, EHOSTUNREACH, ENETUNREACH; no evidence: EAGAIN); an unknown socket is closed, the lower rank
#   re-dials every 500 ms (HELLO: context number, generation) and the higher rank re-accepts on the kept listen socket;
#   a fault on an unknown peer waits up to NCCL_GIN_TS_RECONNECT_MS (10000) for the reconnect, then declines as "peer
#   liveness unknown"; decline texts name the cause; NCCL_GIN_TS_RECONNECT=0 turns the re-dial off; the socket-mute
#   test knob also filters the listen socket and new sockets while it is on
# Apply to a pristine tree:  git apply gin_transparent_rc.diff
#
HDR
git -C "$SRC" diff "$BASE" -- src
} > "$D/gin_transparent_rc.diff"
git -C "$SRC" diff HEAD -- src > "$D/rc_layer.diff"
echo "wrote gin_transparent_rc.diff ($(wc -c < "$D/gin_transparent_rc.diff") bytes), rc_layer.diff ($(wc -c < "$D/rc_layer.diff") bytes)"
T=$(mktemp -d)
git -C "$SRC" archive "$BASE" | tar -x -C "$T"
(cd "$T" && git apply "$D/gin_transparent_rc.diff")
diff -r -q "$T/src" "$SRC/src" && echo "VERIFIED: pristine v2.32.3-1 + gin_transparent_rc.diff == the rc source tree"
rm -rf "$T"; T=$(mktemp -d)
git -C "$SRC" archive "$BASE" | tar -x -C "$T"
(cd "$T" && git apply "$D/../s2_close/gin_transparent_s2r.diff" && git apply "$D/rc_layer.diff")
diff -r -q "$T/src" "$SRC/src" && echo "VERIFIED: pristine + ../s2_close/gin_transparent_s2r.diff + rc_layer.diff == the rc source tree"
rm -rf "$T"
