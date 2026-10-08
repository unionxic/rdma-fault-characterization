#!/usr/bin/env bash
# Write this study's NCCL patches from the scratch tree agent_ts2hq (git: pristine v2.32.3-1 -> the earlier layers ->
# gin-oneway ow -> gin-harden hd -> gin-handoff hf, all committed; the working tree adds this study's layer hq; the
# production build hqp is the same source compiled with -DNCCL_GIN_TS_PRODUCTION):
#   gin_transparent_hq.diff  the FULL diff against pristine NCCL v2.32.3-1 of the hq/hqp source
#   hq_layer.diff            this study's layer alone, against the hf tree (../handoff/gin_transparent_hf.diff)
# and check that pristine + the full diff, and pristine + ../oneway/gin_transparent_ow.diff + ../harden/hd_layer.diff +
# ../handoff/hf_layer.diff + hq_layer.diff, reproduce the working tree.
set -euo pipefail
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
SRC=$SCR/agent_ts2hq/nccl-src
D=$(cd "$(dirname "$0")" && pwd)
BASE=$(git -C "$SRC" rev-list --max-parents=0 HEAD)
case "$(git -C "$SRC" log -1 --format=%s)" in "gin-handoff hf"*) ;; *) echo "HEAD is not the hf commit" >&2; exit 1 ;; esac
{
cat <<'HDR'
# GIN GDAKI transparent recovery, step 2 + gin-s2-close + gin-reconnect + gin-pair-reset + gin-pair-check + gin-oneway
# + gin-harden + gin-handoff + gin-peer (hq: research build; hqp: the same source compiled with -DNCCL_GIN_TS_PRODUCTION).
# FULL diff against pristine NCCL v2.32.3-1 (12df1a11): the earlier layers (../handoff/gin_transparent_hf.diff), then
# this study's layer (hq_layer.diff, EXPERIMENT.md section 9): per-peer user abort words (a decline toward one peer
# releases only the device waits on that peer's QPs), a per-round firmware watchdog, the re-post plan validated on both
# ranks before either commits, FAIL to a declined peer's reconnect, a cause-based shrink hand-off, refusals forgotten
# after 5 s, escalation without reruns, symmetric cancel counts.
# Apply to a pristine tree:  git apply gin_transparent_hq.diff
#
HDR
git -C "$SRC" diff "$BASE" -- src
} > "$D/gin_transparent_hq.diff"
git -C "$SRC" diff HEAD -- src > "$D/hq_layer.diff"
for f in gin_transparent_hq.diff hq_layer.diff; do
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
check "pristine v2.32.3-1 + gin_transparent_hq.diff == the hq source tree" "$D/gin_transparent_hq.diff"
check "pristine + ../oneway/gin_transparent_ow.diff + ../harden/hd_layer.diff + ../handoff/hf_layer.diff + hq_layer.diff == the hq source tree" \
  "$D/../oneway/gin_transparent_ow.diff" "$D/../harden/hd_layer.diff" "$D/../handoff/hf_layer.diff" "$D/hq_layer.diff"
echo "layer files (+/-):"
git -C "$SRC" diff --numstat HEAD -- src
