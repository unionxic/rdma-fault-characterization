#!/usr/bin/env bash
# make_diff_rs.sh - write rs_layer.diff (the restore layer on top of gpu-detect's hk) from the scratch tree and check that it
# re-applies on its base and reproduces the tree (no cluster action).
#   rs_layer.diff  agent_rs_int/nccl-src working tree against its commit "gpu-detect hk (libnccl 2913c777)" (= hr +
#                  hw_layer.diff + hk_layer.diff), with work package 8's two new files (src/include/rs_spike.h,
#                  src/misc/rs_spike.cc) as additions (intent-to-add). Integration of the four branches (2026-10-12): the
#                  whole layer, work packages 1-10. The full GIN diff against pristine NCCL v2.32.3-1 is
#                  ../remaining/gin_transparent_hr.diff, gpu-detect's hw_layer.diff and hk_layer.diff, then this file.
#   chain check    a clone at the hr commit, then gpu-detect's hw_layer.diff and hk_layer.diff (read from the repository at
#                  master commit 5a56da93, md5 checked) and this file, compared with the working tree.
set -eu
D=$(cd "$(dirname "$0")" && pwd)
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
W=$SCR/agent_rs_int
REPO=$W/nccl-src
GD_COMMIT=5a56da93
NEW_FILES="src/include/rs_spike.h src/misc/rs_spike.cc"
OUTF=$D/rs_layer.diff
case "$(git -C "$REPO" log -1 --format=%s)" in "gpu-detect hk"*) ;; *) echo "agent_rs_int head is not the hk commit" >&2; exit 1 ;; esac
git -C "$REPO" add -N -- $NEW_FILES
# histogram: git's default (Myers) aligns the merged host file badly (about 4 100 hk lines shown deleted and added again);
# histogram shows the same change as 51 deletions. Either applies to the same tree.
git -C "$REPO" diff --diff-algorithm=histogram HEAD -- src > "$OUTF"
t=$(mktemp -d "$W/verify.XXXX")
trap 'rm -rf "$t"' EXIT
bad=0
git clone -q "$REPO" "$t/r"
git -C "$t/r" apply "$OUTF"
for f in $( (git -C "$REPO" diff --name-only HEAD -- src; echo $NEW_FILES | tr ' ' '\n') | sort -u); do
  cmp -s "$REPO/$f" "$t/r/$f" || { echo "differs after re-apply: $f"; bad=1; }
done
[ "$bad" = 0 ] && echo "VERIFIED: rs_layer.diff ($(wc -l < "$OUTF") lines, md5 $(md5sum < "$OUTF" | cut -c1-32)) re-applies on 'gpu-detect hk' and reproduces the tree"
git -C "$D" show "$GD_COMMIT:harness/gpu-detect/hw_layer.diff" > "$t/hw_layer.diff"
git -C "$D" show "$GD_COMMIT:harness/gpu-detect/hk_layer.diff" > "$t/hk_layer.diff"
[ "$(md5sum < "$t/hw_layer.diff" | cut -c1-8)" = be0ea9ed ] || { echo "hw_layer.diff at $GD_COMMIT is not be0ea9ed" >&2; exit 1; }
[ "$(md5sum < "$t/hk_layer.diff" | cut -c1-8)" = c5222c55 ] || { echo "hk_layer.diff at $GD_COMMIT is not c5222c55" >&2; exit 1; }
git clone -q "$REPO" "$t/c"
git -C "$t/c" checkout -q HEAD~2
case "$(git -C "$t/c" log -1 --format=%s)" in "gin-remaining hr"*) ;; *) echo "HEAD~2 of agent_rs_int is not the hr commit" >&2; exit 1 ;; esac
git -C "$t/c" apply "$t/hw_layer.diff"
git -C "$t/c" apply "$t/hk_layer.diff"
git -C "$t/c" apply "$OUTF"
for f in $( (git -C "$REPO" diff --name-only HEAD~2 -- src; echo $NEW_FILES | tr ' ' '\n') | sort -u); do
  cmp -s "$REPO/$f" "$t/c/$f" || { echo "differs after the chain: $f"; bad=1; }
done
[ "$bad" = 0 ] && echo "VERIFIED: hw_layer.diff, hk_layer.diff, then rs_layer.diff on 'gin-remaining hr' reproduce the tree"
exit "$bad"
