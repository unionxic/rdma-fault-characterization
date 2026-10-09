#!/usr/bin/env bash
# make_diff_gd.sh - write this study's two layer diffs from the scratch trees and check that each re-applies on its base
# and reproduces the tree (no cluster action).
#   hw_layer.diff   agent_gd/gin/nccl-src working tree against its commit "gin-remaining hr (libnccl 2dee2b5b)". The full
#                   diff against pristine NCCL v2.32.3-1 is ../gpu-initiated/gin_recovery/remaining/gin_transparent_hr.diff
#                   followed by this file.
#   t1w_layer.diff  agent_gd/nvs/src working tree against its commit "t1_380 (transport d6ae3699)". The full diff against
#                   official NVSHMEM v3.8.0-0 is ../gpu-initiated/nvshmem/nvshmem_ibgda_fault_inject.diff,
#                   ../gpu-initiated/nvshmem_rootcause/nvshmem_nrc_proxy_sq_dbr.diff and
#                   ../gpu-initiated/nvshmem_ft/t1_380/nvshmem_ibgda_t1_380.diff, then this file.
#   hk_layer.diff   agent_gd/gin_hk/nccl-src working tree against its commit "gpu-detect hw (libnccl efc48ca1)" (= hr +
#                   hw_layer.diff). The full GIN diff is gin_transparent_hr.diff, hw_layer.diff, then this file; the chain
#                   check applies hw_layer.diff and this file on the hr commit and compares with the hk tree.
# usage: make_diff_gd.sh [all|hk]   (all: the three diffs; hk: hk_layer.diff only)
set -eu
WHAT=${1:-all}
D=$(cd "$(dirname "$0")" && pwd)
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
W=$SCR/agent_gd
mk() {  # mk <repo> <out> <base subject prefix> <paths...>
  local repo=$1 out=$2 subj=$3; shift 3
  case "$(git -C "$repo" log -1 --format=%s)" in "$subj"*) ;; *) echo "$repo: head is not '$subj'" >&2; exit 1 ;; esac
  git -C "$repo" diff HEAD -- "$@" > "$out"
  local t; t=$(mktemp -d "$W/verify.XXXX")
  git clone -q "$repo" "$t/r"
  git -C "$t/r" apply "$out"
  local bad=0 f
  for f in $(git -C "$repo" diff --name-only HEAD -- "$@"); do
    cmp -s "$repo/$f" "$t/r/$f" || { echo "differs after re-apply: $f"; bad=1; }
  done
  rm -rf "$t"
  [ "$bad" = 0 ] && echo "VERIFIED: $(basename "$out") ($(wc -l < "$out") lines, md5 $(md5sum < "$out" | cut -c1-8)) re-applies on '$subj' and reproduces the tree"
}
chain() {  # the hk tree from the hr commit: hw_layer.diff, then hk_layer.diff
  local repo=$W/gin_hk/nccl-src t bad=0 f
  t=$(mktemp -d "$W/verify.XXXX")
  git clone -q "$repo" "$t/r"
  git -C "$t/r" checkout -q HEAD~1
  case "$(git -C "$t/r" log -1 --format=%s)" in "gin-remaining hr"*) ;; *) echo "HEAD~1 of gin_hk is not the hr commit" >&2; exit 1 ;; esac
  git -C "$t/r" apply "$D/hw_layer.diff"
  git -C "$t/r" apply "$D/hk_layer.diff"
  for f in $(git -C "$repo" diff --name-only HEAD~1 -- src); do
    cmp -s "$repo/$f" "$t/r/$f" || { echo "differs after the chain: $f"; bad=1; }
  done
  rm -rf "$t"
  [ "$bad" = 0 ] && echo "VERIFIED: hw_layer.diff then hk_layer.diff on 'gin-remaining hr' reproduce the hk tree"
}
if [ "$WHAT" = all ]; then
  mk "$W/gin/nccl-src" "$D/hw_layer.diff" "gin-remaining hr" src
  mk "$W/nvs/src" "$D/t1w_layer.diff" "t1_380 " src
fi
mk "$W/gin_hk/nccl-src" "$D/hk_layer.diff" "gpu-detect hw" src
chain
