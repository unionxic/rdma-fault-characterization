#!/usr/bin/env bash
# Write this study's NCCL patches from the scratch tree agent_ts2hr (git: pristine v2.32.3-1 -> the earlier layers ->
# gin-oneway ow -> gin-harden hd -> gin-handoff hf -> gin-peer hq, all committed; the working tree adds this study's layer
# hr; the production build hrp is the same source compiled with -DNCCL_GIN_TS_PRODUCTION):
#   gin_transparent_hr.diff  the FULL diff against pristine NCCL v2.32.3-1 of the hr/hrp source
#   hr_layer.diff            this study's layer alone, against the hq tree (../peer/gin_transparent_hq.diff)
# and check that pristine + the full diff, and pristine + ../oneway/gin_transparent_ow.diff + ../harden/hd_layer.diff +
# ../handoff/hf_layer.diff + ../peer/hq_layer.diff + hr_layer.diff, reproduce the working tree.
set -euo pipefail
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
SRC=$SCR/agent_ts2hr/nccl-src
D=$(cd "$(dirname "$0")" && pwd)
BASE=$(git -C "$SRC" rev-list --max-parents=0 HEAD)
case "$(git -C "$SRC" log -1 --format=%s)" in "gin-peer hq"*) ;; *) echo "HEAD is not the hq commit" >&2; exit 1 ;; esac
{
cat <<'HDR'
# GIN GDAKI transparent recovery, step 2 + gin-s2-close + gin-reconnect + gin-pair-reset + gin-pair-check + gin-oneway
# + gin-harden + gin-handoff + gin-peer + gin-remaining (hr: research build; hrp: the same source compiled with
# -DNCCL_GIN_TS_PRODUCTION). FULL diff against pristine NCCL v2.32.3-1 (12df1a11): the earlier layers
# (../peer/gin_transparent_hq.diff), then this study's layer (hr_layer.diff, EXPERIMENT.md section 9): the device-state
# copies of a round over a loopback RDMA QP pair (no CUDA call in a round), a lower rank's REQ answered inside an ACK wait
# (no circular wait), the degraded rule for waits that name no peer (word [0] some time after a peer is judged dead; waits
# on one QP read their peer's word), per-peer prepared state, nesting-aware round guards.
# Apply to a pristine tree:  git apply gin_transparent_hr.diff
#
HDR
git -C "$SRC" diff "$BASE" -- src
} > "$D/gin_transparent_hr.diff"
git -C "$SRC" diff HEAD -- src > "$D/hr_layer.diff"
for f in gin_transparent_hr.diff hr_layer.diff; do
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
check "pristine v2.32.3-1 + gin_transparent_hr.diff == the hr source tree" "$D/gin_transparent_hr.diff"
check "pristine + ../oneway/gin_transparent_ow.diff + ../harden/hd_layer.diff + ../handoff/hf_layer.diff + ../peer/hq_layer.diff + hr_layer.diff == the hr source tree" \
  "$D/../oneway/gin_transparent_ow.diff" "$D/../harden/hd_layer.diff" "$D/../handoff/hf_layer.diff" \
  "$D/../peer/hq_layer.diff" "$D/hr_layer.diff"
echo "layer files (+/-):"
git -C "$SRC" diff --numstat HEAD -- src
