#!/usr/bin/env bash
# build_rs_host.sh - the host branch's wrapper of build_rs.sh and make_diff_rs.sh (impl/PARALLEL.md: work packages 7 and 5).
# Same stages, on the host branch's own scratch tree agent_rs_host/ and its layer diff rs_layer_host.diff; build_rs.sh and
# make_diff_rs.sh themselves are not changed (they are run with W and the diff name substituted). No GPU or RDMA program
# runs; nothing outside agent_rs_host/ is written (agent_rs/ is read once, by setup).
# usage: build_rs_host.sh <setup|rs|rsp|unit|unith|diff|info>
#   setup  once: check that agent_rs/nccl-src is exp/gin-restore's base (head "gpu-detect hk", working tree = rs_layer.diff
#          of this branch's base commit, md5 922b2859), copy agent_rs/{nccl-src,build,build-rsp} to agent_rs_host/ (mtimes
#          kept) and rewrite the absolute paths in the dependency files and device manifests.
#   rs, rsp, unit, info   build_rs.sh's stages on agent_rs_host (RSOUT, RSPOUT as there; a used folder is refused).
#   unith  the host branch's CPU unit test: the two marked regions of the working tree's gin_host_gdaki.cc ("gin-restore:
#          pure functions" and "gin-restore hold: pure functions") are cut out and compiled with rs_unit_host.cc (g++, ASan,
#          UBSan; no NCCL, no CUDA, no network) -> agent_rs_host/out/unith/rs_unit_host, then run.
#   diff   make_diff_rs.sh on agent_rs_host: rs_layer_host.diff (the whole layer over hk) and its re-apply checks.
# All compiles run at nice 19 and idle I/O priority (other studies use this node).
set -euo pipefail
STAGE=${1:?stage}
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
D=$(cd "$(dirname "$0")" && pwd)
SRC=$SCR/agent_rs
W=$SCR/agent_rs_host
HOSTF=src/transport/net_ib/gdaki/gin_host_gdaki.cc
md5() { md5sum < "$1" | cut -c1-32; }
# build_rs.sh / make_diff_rs.sh with this branch's tree and diff (the substitutions are checked before running)
sub() {  # sub <script>: the script's text with W and the diff file of this branch
  sed -e 's#^W=\$SCR/agent_rs$#W=$SCR/agent_rs_host#' \
      -e 's#\$D/rs_layer\.diff#$D/rs_layer_host.diff#g' \
      -e 's#^OUTF=\$D/rs_layer\.diff$#OUTF=$D/rs_layer_host.diff#' "$D/$1"
}
run_sub() {  # run_sub <script> <args...>
  local s=$1; shift
  local t; t=$(sub "$s")
  printf '%s\n' "$t" | grep -q '^W=\$SCR/agent_rs_host$' || { echo "$s: W substitution failed" >&2; exit 1; }
  ! printf '%s\n' "$t" | grep -q '\$D/rs_layer\.diff' || { echo "$s: a path still names rs_layer.diff" >&2; exit 1; }
  bash -c "$t" "$D/$s" "$@"
}
rewrite() {  # rewrite <from prefix> <to prefix> <dir>: absolute paths in *.d and manifests, mtimes kept
  local from=$1 to=$2 dir=$3
  (cd "$dir" && find . \( -name '*.d' -o -name manifest \) -print0 |
     while IFS= read -r -d '' f; do
       local t; t=$(mktemp); touch -r "$f" "$t"
       sed -i "s#$from#$to#g" "$f"; touch -h -r "$t" "$f"; rm -f "$t"
     done)
}
setup() {
  [ -d "$W/nccl-src" ] && { echo "agent_rs_host already set up" >&2; return 0; }
  case "$(git -C "$SRC/nccl-src" log -1 --format=%s)" in "gpu-detect hk"*) ;; *) echo "agent_rs head is not hk" >&2; exit 1 ;; esac
  [ "$(git -C "$SRC/nccl-src" diff HEAD -- src | md5sum | cut -c1-8)" = 922b2859 ] ||
    { echo "agent_rs working tree is not rs_layer.diff 922b2859 (exp/gin-restore 655093ad)" >&2; exit 1; }
  mkdir -p "$W"
  cp -a "$SRC/nccl-src" "$SRC/build" "$SRC/build-rsp" "$W/"
  rewrite "$SRC/" "$W/" "$W/build"
  rewrite "$SRC/" "$W/" "$W/build-rsp"
  [ "$(git -C "$W/nccl-src" diff HEAD -- src | md5sum | cut -c1-8)" = 922b2859 ] || { echo "the copy differs" >&2; exit 1; }
  [ -f "$W/build/.rs_nccl_device_digest" ] && echo "setup: device digest $(cat "$W/build/.rs_nccl_device_digest")"
  echo "setup: agent_rs_host at $(git -C "$W/nccl-src" rev-parse --short HEAD), working tree rs_layer.diff 922b2859"
  echo "setup: base build libnccl $(md5 "$W/build/lib/libnccl.so.2.32.3"), build-rsp $(md5 "$W/build-rsp/lib/libnccl.so.2.32.3")"
}
unith() {
  local o=$W/out/unith src=$W/nccl-src/$HOSTF
  mkdir -p "$o"
  awk '/^\/\/ ---- gin-restore: pure functions \(begin/{on=1} on{print} /^\/\/ ---- gin-restore: pure functions \(end/{on=0}' \
    "$src" > "$o/rs_pure.inc"
  awk '/^\/\/ ---- gin-restore hold: pure functions \(begin/{on=1} on{print} /^\/\/ ---- gin-restore hold: pure functions \(end/{on=0}' \
    "$src" > "$o/rs_hold_pure.inc"
  [ -s "$o/rs_pure.inc" ] || { echo "no pure-function region in $HOSTF" >&2; exit 1; }
  [ -s "$o/rs_hold_pure.inc" ] || { echo "no hold pure-function region in $HOSTF" >&2; exit 1; }
  grep -qxF 'enum { GDAKI_POLICY_FAILFAST = 0, GDAKI_POLICY_HOLD = 1 };' "$src" || { echo "hk's policy enum changed" >&2; exit 1; }
  # rs_hold_api.h's shared text is in the host file verbatim
  local fence='/^\/\/ ---- shared text \(begin\) ----$/{on=1} on{print} /^\/\/ ---- shared text \(end\) ----$/{on=0}'
  awk "$fence" "$D/rs_hold_api.h" > "$o/shared_api.txt"
  awk "$fence" "$src" > "$o/shared_src.txt"
  [ -s "$o/shared_api.txt" ] && cmp -s "$o/shared_api.txt" "$o/shared_src.txt" ||
    { echo "rs_hold_api.h's shared text differs from the host file's" >&2; exit 1; }
  echo "unith: rs_hold_api.h shared text = host file ($(wc -l < "$o/shared_api.txt") lines)"
  nice -n 19 g++ -std=c++17 -O1 -g -Wall -Wextra -Werror -pthread -fsanitize=address,undefined -I"$o" -I"$D" \
    -I"$W/nccl-src/src/include" "$D/rs_unit_host.cc" -o "$o/rs_unit_host"
  "$o/rs_unit_host"
}
case "$STAGE" in
  setup) setup ;;
  rs|rsp|unit|info) run_sub build_rs.sh "$STAGE" ;;
  unith) unith ;;
  diff) run_sub make_diff_rs.sh ;;
  *) echo "unknown stage $STAGE" >&2; exit 2 ;;
esac
