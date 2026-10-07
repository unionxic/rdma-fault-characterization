#!/usr/bin/env bash
# Write this study's NCCL patches from the scratch tree agent_ts2r (git: pristine v2.32.3-1 -> the four earlier
# layers -> step 2 final committed; the working tree adds this study's change):
#   gin_transparent_s2r.diff  the FULL diff against pristine NCCL v2.32.3-1 (four earlier layers + step 1 + step 2 + s2r)
#   s2r_layer.diff            this study's change alone, against the step-2 final tree (../gin_transparent_s2.diff)
# and check that pristine + the full diff, and step-2 tree + the layer diff, both reproduce the working tree.
set -euo pipefail
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
SRC=$SCR/agent_ts2r/nccl-src
D=$(cd "$(dirname "$0")" && pwd)
BASE=$(git -C "$SRC" rev-list --max-parents=0 HEAD)
{
cat <<'HDR'
# GIN GDAKI transparent recovery, step 2 + gin-s2-close (research build). FULL diff against pristine NCCL v2.32.3-1
# (12df1a11): the four earlier layers, step 1, step 2 (../gin_transparent_s2.diff) and this study's change
# (s2r_layer.diff, EXPERIMENT.md section 9):
#   src/dev_runtime.cc  a user devComm gets the communicator's device abort flag (comm->abortFlagDev) after the GIN
#       setup when NCCL_GIN_FAULT_RECOVERY, NCCL_GIN_FAULT_TRANSPARENT and NCCL_GIN_TS_USER_ABORT (default 1) are set,
#       so ncclCommAbort releases the GIN waits of its kernels (waitSignal included); WARN "user devComm abort flag set"
#   src/transport/net_ib/gdaki/gin_host_gdaki.cc  NCCL_GIN_TS_USER_ABORT and ncclGinTsUserAbortEnabled(); test knob
#       NCCL_GIN_TS_TEST_SOCK_MUTE=<start ms>:<length ms> (a drop-everything SO_ATTACH_FILTER on the helper sockets);
#       the helper's idle socket loss is logged as a WARN with its cause (FIN, BADMAGIC or the errno name), behaviour
#       unchanged
# Apply to a pristine tree:  git apply gin_transparent_s2r.diff
#
HDR
git -C "$SRC" diff "$BASE" -- src
} > "$D/gin_transparent_s2r.diff"
git -C "$SRC" diff HEAD -- src > "$D/s2r_layer.diff"
echo "wrote gin_transparent_s2r.diff ($(wc -c < "$D/gin_transparent_s2r.diff") bytes), s2r_layer.diff ($(wc -c < "$D/s2r_layer.diff") bytes)"
T=$(mktemp -d)
git -C "$SRC" archive "$BASE" | tar -x -C "$T"
(cd "$T" && git apply "$D/gin_transparent_s2r.diff")
diff -r -q "$T/src" "$SRC/src" && echo "VERIFIED: pristine v2.32.3-1 + gin_transparent_s2r.diff == the s2r source tree"
rm -rf "$T"; T=$(mktemp -d)
git -C "$SRC" archive "$BASE" | tar -x -C "$T"
(cd "$T" && git apply "$D/../gin_transparent_s2.diff" && git apply "$D/s2r_layer.diff")
diff -r -q "$T/src" "$SRC/src" && echo "VERIFIED: pristine + ../gin_transparent_s2.diff + s2r_layer.diff == the s2r source tree"
rm -rf "$T"
