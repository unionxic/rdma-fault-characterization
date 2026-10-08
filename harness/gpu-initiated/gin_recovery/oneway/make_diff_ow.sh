#!/usr/bin/env bash
# Write this study's NCCL patches from the scratch tree agent_ts2ow (git: pristine v2.32.3-1 -> the earlier layers ->
# gin-pair-check pc -> this study's test switches pcm, all committed; the working tree adds this study's fix ow):
#   gin_transparent_pcm.diff  the FULL diff against pristine NCCL v2.32.3-1 of the reference build pcm
#   gin_transparent_ow.diff   the FULL diff against pristine NCCL v2.32.3-1 of the new build ow
#   pcm_layer.diff            the test switches alone, against the gin-pair-check tree (../pair_check/gin_transparent_pc.diff)
#   ow_layer.diff             the fix alone, against the pcm tree
# and check that pristine + each full diff, and the pc tree + the layer diffs, reproduce the two trees.
set -euo pipefail
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
SRC=$SCR/agent_ts2ow/nccl-src
D=$(cd "$(dirname "$0")" && pwd)
BASE=$(git -C "$SRC" rev-list --max-parents=0 HEAD)
[ "$(git -C "$SRC" log -1 --format=%s)" = "gin-oneway pcm (test switches)" ] || { echo "HEAD is not the pcm commit" >&2; exit 1; }
PC=$(git -C "$SRC" rev-parse HEAD~1)
hdr() {
cat <<HDR
# GIN GDAKI transparent recovery, step 2 + gin-s2-close + gin-reconnect + gin-pair-reset + gin-pair-check + gin-oneway
# ($1, research build). FULL diff against pristine NCCL v2.32.3-1 (12df1a11), all in
# src/transport/net_ib/gdaki/gin_host_gdaki.cc: the earlier layers (../pair_check/gin_transparent_pc.diff), then
#   test switches (pcm_layer.diff): NCCL_GIN_TS_TEST_SOCK_UTO_MS (TCP_USER_TIMEOUT of the helper sockets) and
#   NCCL_GIN_TS_TEST_REFUSE_HELLO=<n> (refuse the first n reconnect HELLOs that pass the checks)
HDR
[ "$1" = ow ] && cat <<'HDR'
#   the fix (ow_layer.diff, EXPERIMENT.md section 9): a reset (ECONNRESET, EPIPE, ECONNABORTED, ECONNREFUSED, EHOSTDOWN,
#   ENONET) on an established helper socket is unknown, not dead; a refused re-dial or probe is dead; the lower rank
#   installs a re-dial only after the higher rank's HELLO-ACK (an unconfirmed attempt ends with a reset); the higher rank
#   probes an unknown lower rank's listen port; log lines: helper liveness, re-dial not accepted, probe answered/refused
HDR
echo "# Apply to a pristine tree:  git apply gin_transparent_$1.diff"
echo "#"
}
{ hdr pcm; git -C "$SRC" diff "$BASE" HEAD -- src; } > "$D/gin_transparent_pcm.diff"
{ hdr ow; git -C "$SRC" diff "$BASE" -- src; } > "$D/gin_transparent_ow.diff"
git -C "$SRC" diff "$PC" HEAD -- src > "$D/pcm_layer.diff"
git -C "$SRC" diff HEAD -- src > "$D/ow_layer.diff"
for f in gin_transparent_pcm.diff gin_transparent_ow.diff pcm_layer.diff ow_layer.diff; do
  echo "wrote $f ($(wc -c < "$D/$f") bytes, md5 $(md5sum < "$D/$f" | cut -c1-8))"
done
check() {  # check <label> <tree to compare: HEAD or WORK> <diff> [<diff>...]
  local label=$1 what=$2; shift 2
  local T R
  T=$(mktemp -d); R=$(mktemp -d)
  git -C "$SRC" archive "$BASE" | tar -x -C "$T"
  for x in "$@"; do (cd "$T" && git apply "$x"); done
  if [ "$what" = HEAD ]; then git -C "$SRC" archive HEAD src | tar -x -C "$R"; else cp -a "$SRC/src" "$R/"; fi
  diff -r -q "$T/src" "$R/src" && echo "VERIFIED: $label"
  rm -rf "$T" "$R"
}
check "pristine v2.32.3-1 + gin_transparent_pcm.diff == the pcm source tree" HEAD "$D/gin_transparent_pcm.diff"
check "pristine v2.32.3-1 + gin_transparent_ow.diff == the ow source tree" WORK "$D/gin_transparent_ow.diff"
check "pristine + ../pair_check/gin_transparent_pc.diff + pcm_layer.diff == the pcm source tree" HEAD \
  "$D/../pair_check/gin_transparent_pc.diff" "$D/pcm_layer.diff"
check "pristine + ../pair_check/gin_transparent_pc.diff + pcm_layer.diff + ow_layer.diff == the ow source tree" WORK \
  "$D/../pair_check/gin_transparent_pc.diff" "$D/pcm_layer.diff" "$D/ow_layer.diff"
