#!/usr/bin/env bash
# Write this study's NCCL patches from the scratch tree agent_ts2hd (git: pristine v2.32.3-1 -> the earlier layers ->
# gin-oneway ow, all committed; the working tree adds this study's layer hd; the production build hdp is the same source
# compiled with -DNCCL_GIN_TS_PRODUCTION):
#   gin_transparent_hd.diff  the FULL diff against pristine NCCL v2.32.3-1 of the hd/hdp source
#   hd_layer.diff            this study's layer alone, against the ow tree (../oneway/gin_transparent_ow.diff)
# and check that pristine + the full diff, and pristine + ../oneway/gin_transparent_ow.diff + hd_layer.diff, reproduce the
# working tree.
set -euo pipefail
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
SRC=$SCR/agent_ts2hd/nccl-src
D=$(cd "$(dirname "$0")" && pwd)
BASE=$(git -C "$SRC" rev-list --max-parents=0 HEAD)
case "$(git -C "$SRC" log -1 --format=%s)" in "gin-oneway ow"*) ;; *) echo "HEAD is not the ow commit" >&2; exit 1 ;; esac
{
cat <<'HDR'
# GIN GDAKI transparent recovery, step 2 + gin-s2-close + gin-reconnect + gin-pair-reset + gin-pair-check + gin-oneway
# + gin-harden (hd: research build; hdp: the same source compiled with -DNCCL_GIN_TS_PRODUCTION). FULL diff against
# pristine NCCL v2.32.3-1 (12df1a11): the earlier layers (../oneway/gin_transparent_ow.diff), then this study's layer
# (hd_layer.diff, EXPERIMENT.md section 9): a user devComm's own abort word whose release returns an error; death only on
# two refused connects >= 1 s apart; a per-context nonce in HELLO/HELLO-ACK/PROBE/PROBE-ACK; BYE before an orderly close;
# a socket loss inside a round before the commit cancels and retries the round; a peer judged dead is declined at once;
# bounded device-state copies, firmware-phase watchdog, bounded helper join at ncclCommAbort; re-post plan validated for
# every QP before any post; escalation cap; ncclGinGetRecoveryStats; NCCL_GIN_TS_PORT; the production switch
# Apply to a pristine tree:  git apply gin_transparent_hd.diff
#
HDR
git -C "$SRC" diff "$BASE" -- src
} > "$D/gin_transparent_hd.diff"
git -C "$SRC" diff HEAD -- src > "$D/hd_layer.diff"
for f in gin_transparent_hd.diff hd_layer.diff; do
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
check "pristine v2.32.3-1 + gin_transparent_hd.diff == the hd source tree" "$D/gin_transparent_hd.diff"
check "pristine + ../oneway/gin_transparent_ow.diff + hd_layer.diff == the hd source tree" \
  "$D/../oneway/gin_transparent_ow.diff" "$D/hd_layer.diff"
echo "layer files (+/-):"
git -C "$SRC" diff --numstat HEAD -- src
