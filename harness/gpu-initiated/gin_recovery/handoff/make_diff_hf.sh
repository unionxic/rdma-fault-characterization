#!/usr/bin/env bash
# Write this study's NCCL patches from the scratch tree agent_ts2hf (git: pristine v2.32.3-1 -> the earlier layers ->
# gin-oneway ow -> gin-harden hd, all committed; the working tree adds this study's layer hf; the production build hfp is
# the same source compiled with -DNCCL_GIN_TS_PRODUCTION):
#   gin_transparent_hf.diff  the FULL diff against pristine NCCL v2.32.3-1 of the hf/hfp source
#   hf_layer.diff            this study's layer alone, against the hd tree (../harden/gin_transparent_hd.diff)
# and check that pristine + the full diff, and pristine + ../oneway/gin_transparent_ow.diff + ../harden/hd_layer.diff +
# hf_layer.diff, reproduce the working tree.
set -euo pipefail
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
SRC=$SCR/agent_ts2hf/nccl-src
D=$(cd "$(dirname "$0")" && pwd)
BASE=$(git -C "$SRC" rev-list --max-parents=0 HEAD)
case "$(git -C "$SRC" log -1 --format=%s)" in "gin-harden hd"*) ;; *) echo "HEAD is not the hd commit" >&2; exit 1 ;; esac
{
cat <<'HDR'
# GIN GDAKI transparent recovery, step 2 + gin-s2-close + gin-reconnect + gin-pair-reset + gin-pair-check + gin-oneway
# + gin-harden + gin-handoff (hf: research build; hfp: the same source compiled with -DNCCL_GIN_TS_PRODUCTION). FULL diff
# against pristine NCCL v2.32.3-1 (12df1a11): the earlier layers (../harden/gin_transparent_hd.diff), then this study's
# layer (hf_layer.diff, EXPERIMENT.md section 9): an aborting ncclCommShrink (NCCL_SHRINK_ABORT) goes on past the
# parent's GIN async error when the GDAKI layer raised that error only for GIN peers that are all excluded (every raise
# notes its peer, keyed by the communicator's GIN state); NCCL_GIN_SHRINK_HANDOFF=0 restores the stock check.
# Apply to a pristine tree:  git apply gin_transparent_hf.diff
#
HDR
git -C "$SRC" diff "$BASE" -- src
} > "$D/gin_transparent_hf.diff"
git -C "$SRC" diff HEAD -- src > "$D/hf_layer.diff"
for f in gin_transparent_hf.diff hf_layer.diff; do
  echo "wrote $f ($(wc -c < "$D/$f") bytes, md5 $(md5sum < "$D/$f" | cut -c1-8))"
done
check() {  # check <label> <diff> [<diff>...]: pristine + the diffs == the working tree
  local label=$1; shift
  local T R
  T=$(mktemp -d); R=$(mktemp -d)
  git -C "$SRC" archive "$BASE" | tar -x -C "$T"
  for x in "$@"; do (cd "$T" && git apply "$x"); done
  cp -a "$SRC/src" "$R/"
  diff -r -q "$T/src" "$R/src" && echo "VERIFIED: $label"
  rm -rf "$T" "$R"
}
check "pristine v2.32.3-1 + gin_transparent_hf.diff == the hf source tree" "$D/gin_transparent_hf.diff"
check "pristine + ../oneway/gin_transparent_ow.diff + ../harden/hd_layer.diff + hf_layer.diff == the hf source tree" \
  "$D/../oneway/gin_transparent_ow.diff" "$D/../harden/hd_layer.diff" "$D/hf_layer.diff"
echo "layer files (+/-):"
git -C "$SRC" diff --numstat HEAD -- src
