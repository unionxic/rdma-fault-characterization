#!/usr/bin/env bash
# make_diff_rs_spare.sh - write rs_layer_spare.diff (the restore layer plus work package 8, the spare process, on top of
# gpu-detect's hk) from the spare branch's scratch tree and check it re-applies and reproduces the tree. This is
# rs_layer.diff (work packages 1-4) plus work package 8's changes (bootstrap.cc, init.cc, transport/net_ib/gin.cc,
# dev_runtime.cc, gin/gin_host.cc, the GDAKI host file's REJOIN/endpoint regions and replay branches) and the two new
# files src/include/rs_spike.h, src/misc/rs_spike.cc. No cluster action.
set -eu
D=$(cd "$(dirname "$0")" && pwd)
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
W=$SCR/agent_rs_spare
REPO=$W/nccl-src
OUTF=$D/rs_layer_spare.diff
case "$(git -C "$REPO" log -1 --format=%s)" in "gpu-detect hk"*) ;; *) echo "agent_rs_spare head is not the hk commit" >&2; exit 1 ;; esac
# intent-to-add the new files so git diff carries them as additions (they are not committed in the scratch tree)
git -C "$REPO" add -N -- src/include/rs_spike.h src/misc/rs_spike.cc
git -C "$REPO" diff HEAD -- src > "$OUTF"
t=$(mktemp -d "$W/verify.XXXX")
trap 'rm -rf "$t"' EXIT
bad=0
git clone -q "$REPO" "$t/r"
git -C "$t/r" apply "$OUTF"
# the new files are intent-to-add (not in HEAD), so compare the whole src working tree
for f in $(git -C "$REPO" diff --name-only HEAD -- src; echo src/include/rs_spike.h src/misc/rs_spike.cc); do
  cmp -s "$REPO/$f" "$t/r/$f" || { echo "differs after re-apply: $f"; bad=1; }
done
[ "$bad" = 0 ] && echo "VERIFIED: rs_layer_spare.diff ($(wc -l < "$OUTF") lines, md5 $(md5sum < "$OUTF" | cut -c1-32)) re-applies on 'gpu-detect hk' and reproduces the tree"
exit "$bad"
