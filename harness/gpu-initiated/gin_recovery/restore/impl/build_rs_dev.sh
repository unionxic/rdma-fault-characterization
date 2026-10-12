#!/usr/bin/env bash
# build_rs_dev.sh - the dev branch's build of gin-restore's restore layer (impl/PARALLEL.md: work packages 4 again, 6, 9),
# in its OWN scratch tree agent_rs_dev/ only (a copy of agent_rs/, which is read only here). No GPU or RDMA program runs;
# no cluster action. Same stages as build_rs.sh (which this branch does not change), with this branch's tree and files.
# usage: build_rs_dev.sh <setup|rs|rsp|unit|api|diff|info>
#   setup  once: check that agent_rs is work package 4's final state (working tree = rs_layer.diff md5 922b2859, builds
#          rs_p4d 1e19d678 and rsp_p4d c03c2ee5), copy its nccl-src, build and build-rsp to agent_rs_dev/ and rewrite the
#          absolute paths in the dependency files and device manifests (mtimes kept, so make rebuilds only what changes).
#   rs     incremental make of the working tree (the changed files must be exactly RS_FILES) into agent_rs_dev/build ->
#          agent_rs_dev/out/$RSOUT/ (a folder that already holds a build is refused). The device objects are rebuilt when
#          the device header trees differ from the last build of that directory (build_rs.sh's rule, work package 3).
#   rsp    the production build (-DNCCL_GIN_TS_PRODUCTION) into agent_rs_dev/build-rsp -> agent_rs_dev/out/$RSPOUT/.
#   unit   the CPU unit test rs_unit_dev.cc: the host file's pure regions are cut out ("gin-restore: pure functions" and
#          this branch's "gin-restore (dev): log, suppress and replay, pure" region) and compiled with the working tree's
#          device-host common header and rs_log_api.h (g++, ASan, UBSan; no NCCL, no CUDA, no network), then run.
#   api    check that the host file's log API block (between the "gin-restore (dev): log API" markers) is rs_log_api.h's
#          block byte for byte (one source for the interface the host branch codes against).
#   diff   write rs_layer_dev.diff (working tree against its commit "gpu-detect hk") and check that it re-applies on hk and
#          that hr + hw_layer.diff + hk_layer.diff + it reproduce the tree (make_diff_rs.sh's checks, this branch's file).
#   info   agent_rs_dev/out/build_info.txt: md5 of every output and input.
# All compiles run at nice 19 and idle I/O priority (other studies use this node).
set -euo pipefail
STAGE=${1:?stage}
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
D=$(cd "$(dirname "$0")" && pwd)
CUDA=/usr/local/cuda-12.8
GENCODE="-gencode=arch=compute_75,code=sm_75 -gencode=arch=compute_86,code=sm_86"
JOBS=${JOBS:-8}
RSOUT=${RSOUT:-rs_dev}
RSPOUT=${RSPOUT:-rsp_dev}
SRC=$SCR/agent_rs       # work package 4's tree (read only)
W=$SCR/agent_rs_dev     # this branch's tree
OUT=$W/out
HOSTF=src/transport/net_ib/gdaki/gin_host_gdaki.cc
COMMON=src/include/nccl_device/gin/gdaki/gin_gdaki_device_host_common.h
RS_FILES="src/gin/gin_host.cc src/include/gin/gin_host.h src/include/nccl_device/gin/gdaki/gin_gdaki.h $COMMON src/nccl.h.in $HOSTF"
DIFF=$D/rs_layer_dev.diff
GD_COMMIT=5a56da93      # master commit that holds gpu-detect's hw_layer.diff and hk_layer.diff
SG() { git -C "$SRC/nccl-src" "$@"; }
RG() { git -C "$W/nccl-src" -c user.name=build -c user.email=build@localhost "$@"; }
md5() { md5sum < "$1" | cut -c1-32; }
MKS() {  # MKS <builddir> [make args]
  local b=$1; shift
  nice -n 19 ionice -c3 make -j"$JOBS" -C "$W/nccl-src" src.build BUILDDIR="$b" CUDA_HOME=$CUDA NVCC_GENCODE="$GENCODE" "$@"
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
  [ -d "$W/nccl-src" ] && { echo "agent_rs_dev already set up" >&2; return 0; }
  case "$(SG log -1 --format=%s)" in "gpu-detect hk"*) ;; *) echo "agent_rs head is not the hk commit" >&2; exit 1 ;; esac
  [ "$(SG diff HEAD -- src | md5sum | cut -c1-32)" = 922b2859ddd1d28a3496329c236147fe ] ||
    { echo "agent_rs working tree is not work package 4's rs_layer.diff (922b2859)" >&2; exit 1; }
  [ "$(md5 "$SRC/build/lib/libnccl.so.2.32.3")" = 1e19d678d843ee0c71c453e0645ecb77 ] || { echo "agent_rs build is not rs_p4d" >&2; exit 1; }
  [ "$(md5 "$SRC/build-rsp/lib/libnccl.so.2.32.3")" = c03c2ee5b10a4aafff04b1cef57d84c7 ] || { echo "agent_rs build-rsp is not rsp_p4d" >&2; exit 1; }
  mkdir -p "$W"
  cp -a "$SRC/nccl-src" "$SRC/build" "$SRC/build-rsp" "$W/"
  rm -rf "$W/nccl-src/.git/worktrees"
  rewrite "$SRC/" "$W/" "$W/build"
  rewrite "$SRC/" "$W/" "$W/build-rsp"
  [ "$(RG diff HEAD -- src | md5sum | cut -c1-32)" = 922b2859ddd1d28a3496329c236147fe ] || { echo "the copy's working tree differs" >&2; exit 1; }
  echo "setup: agent_rs_dev at $(RG rev-parse --short HEAD) ($(RG log -1 --format=%s)), working tree = rs_layer.diff 922b2859"
  echo "setup: make -n in build/ after the copy: $(MKS "$W/build" -n 2>/dev/null | grep -c -- ' -c ' || true) compile commands"
}
tree() {
  case "$(RG log -1 --format=%s)" in "gpu-detect hk"*) ;; *) echo "unexpected head commit in agent_rs_dev" >&2; exit 1 ;; esac
  [ "$(RG diff --name-only HEAD -- src | sort | tr '\n' ' ')" = "$(echo $RS_FILES | tr ' ' '\n' | sort | tr '\n' ' ')" ] ||
    { echo "the working tree changes other files than RS_FILES: $(RG diff --name-only HEAD -- src | tr '\n' ' ')" >&2; exit 1; }
}
# build_rs.sh's device-object rule (work package 3's review): NCCL's dependency pass does not see the GIN device headers.
NDEV=src/include/nccl_device
NDOCA=src/transport/net_ib/gdaki/doca-gpunetio/include
ndevDigest() { (cd "$W/nccl-src" && find "$NDEV" "$NDOCA" -type f | LC_ALL=C sort | xargs md5sum | md5sum | cut -c1-32); }
devsync() {
  local b=$1
  if [ "$(cat "$b/.rs_nccl_device_digest" 2>/dev/null)" != "$(ndevDigest)" ]; then
    echo "devsync: $NDEV or $NDOCA differs from the last build of $(basename "$b"): its device objects are rebuilt"
    rm -rf "$b/obj/device" "$b/obj/diagnostics/device"
  fi
}
devdone() { ndevDigest > "$1/.rs_nccl_device_digest"; }
fresh() {
  [ ! -e "$1/libnccl.so.2.32.3" ] || { echo "$1 already holds a build; give a new folder name" >&2; exit 1; }
  mkdir -p "$1"
}
rs() {
  tree; fresh "$OUT/$RSOUT"
  devsync "$W/build"
  MKS "$W/build"
  devdone "$W/build"
  cp "$W/build/lib/libnccl.so.2.32.3" "$OUT/$RSOUT/"
  echo "$RSOUT libnccl $(md5 "$OUT/$RSOUT/libnccl.so.2.32.3")"
}
rsp() {
  tree; fresh "$OUT/$RSPOUT"
  devsync "$W/build-rsp"
  CXXFLAGS=-DNCCL_GIN_TS_PRODUCTION MKS "$W/build-rsp"
  devdone "$W/build-rsp"
  cp "$W/build-rsp/lib/libnccl.so.2.32.3" "$OUT/$RSPOUT/"
  diff -r -q "$W/build/include" "$W/build-rsp/include" > /dev/null ||
    { echo "the production build's headers differ from the research build's" >&2; exit 1; }
  echo "$RSPOUT libnccl $(md5 "$OUT/$RSPOUT/libnccl.so.2.32.3")"
}
region() {  # region <begin regex> <end regex> <file>
  awk -v b="$1" -v e="$2" '$0 ~ b {on=1} on {print} $0 ~ e {on=0}' "$3"
}
unit() {
  local o=$OUT/unit src=$W/nccl-src/$HOSTF
  mkdir -p "$o"
  region '^// ---- gin-restore: pure functions [(]begin' '^// ---- gin-restore: pure functions [(]end' "$src" > "$o/rs_pure.inc"
  region '^// ---- gin-restore [(]dev[)]: log, suppress and replay, pure [(]begin' \
         '^// ---- gin-restore [(]dev[)]: log, suppress and replay, pure [(]end' "$src" > "$o/rs_dev_pure.inc"
  [ -s "$o/rs_pure.inc" ] || { echo "no pure-function region in $HOSTF" >&2; exit 1; }
  [ -s "$o/rs_dev_pure.inc" ] || echo "// (no dev pure region in the host file yet)" > "$o/rs_dev_pure.inc"
  region '^// ---- gin-restore [(]dev[)]: log API [(]begin' '^// ---- gin-restore [(]dev[)]: log API [(]end' "$src" > "$o/rs_dev_api.inc"
  [ -s "$o/rs_dev_api.inc" ] || { echo "no log API block in $HOSTF" >&2; exit 1; }
  grep -qxF 'enum { GDAKI_POLICY_FAILFAST = 0, GDAKI_POLICY_HOLD = 1 };' "$src" || { echo "hk's policy enum changed" >&2; exit 1; }
  nice -n 19 g++ -std=c++17 -O1 -g -Wall -Wextra -Werror -pthread -fsanitize=address,undefined -I"$o" -I"$D" \
    -I"$W/nccl-src/src/include" "$D/rs_unit_dev.cc" -o "$o/rs_unit_dev"
  "$o/rs_unit_dev"
}
api() {
  local a b
  a=$(region '^// ---- gin-restore [(]dev[)]: log API [(]begin' '^// ---- gin-restore [(]dev[)]: log API [(]end' "$W/nccl-src/$HOSTF" | md5sum | cut -c1-32)
  b=$(region '^// ---- gin-restore [(]dev[)]: log API [(]begin' '^// ---- gin-restore [(]dev[)]: log API [(]end' "$D/rs_log_api.h" | md5sum | cut -c1-32)
  [ -n "$(region '^// ---- gin-restore [(]dev[)]: log API [(]begin' '^// ---- gin-restore [(]dev[)]: log API [(]end' "$D/rs_log_api.h")" ] ||
    { echo "no log API block in rs_log_api.h" >&2; exit 1; }
  [ "$a" = "$b" ] || { echo "the host file's log API block differs from rs_log_api.h ($a vs $b)" >&2; exit 1; }
  echo "api: the host file's log API block is rs_log_api.h's ($a)"
}
diffcheck() {
  case "$(RG log -1 --format=%s)" in "gpu-detect hk"*) ;; *) echo "agent_rs_dev head is not the hk commit" >&2; exit 1 ;; esac
  RG diff HEAD -- src > "$DIFF"
  local t; t=$(mktemp -d "$W/verify.XXXX")
  local bad=0
  git clone -q "$W/nccl-src" "$t/r"
  git -C "$t/r" apply "$DIFF"
  for f in $(RG diff --name-only HEAD -- src); do cmp -s "$W/nccl-src/$f" "$t/r/$f" || { echo "differs after re-apply: $f"; bad=1; }; done
  [ "$bad" = 0 ] && echo "VERIFIED: rs_layer_dev.diff ($(wc -l < "$DIFF") lines, md5 $(md5 "$DIFF")) re-applies on 'gpu-detect hk' and reproduces the tree"
  git -C "$D" show "$GD_COMMIT:harness/gpu-detect/hw_layer.diff" > "$t/hw_layer.diff"
  git -C "$D" show "$GD_COMMIT:harness/gpu-detect/hk_layer.diff" > "$t/hk_layer.diff"
  [ "$(md5sum < "$t/hw_layer.diff" | cut -c1-8)" = be0ea9ed ] || { echo "hw_layer.diff at $GD_COMMIT is not be0ea9ed" >&2; exit 1; }
  [ "$(md5sum < "$t/hk_layer.diff" | cut -c1-8)" = c5222c55 ] || { echo "hk_layer.diff at $GD_COMMIT is not c5222c55" >&2; exit 1; }
  git clone -q "$W/nccl-src" "$t/c"
  git -C "$t/c" checkout -q HEAD~2
  case "$(git -C "$t/c" log -1 --format=%s)" in "gin-remaining hr"*) ;; *) echo "HEAD~2 is not the hr commit" >&2; exit 1 ;; esac
  git -C "$t/c" apply "$t/hw_layer.diff"
  git -C "$t/c" apply "$t/hk_layer.diff"
  git -C "$t/c" apply "$DIFF"
  for f in $(RG diff --name-only HEAD~2 -- src); do cmp -s "$W/nccl-src/$f" "$t/c/$f" || { echo "differs after the chain: $f"; bad=1; }; done
  [ "$bad" = 0 ] && echo "VERIFIED: hw_layer.diff, hk_layer.diff, then rs_layer_dev.diff on 'gin-remaining hr' reproduce the tree"
  rm -rf "$t"
  return "$bad"
}
info() {
  {
    echo "built=$(date '+%F %T') host=$(hostname -s) nvcc=$("$CUDA/bin/nvcc" --version | tail -1) g++=$(g++ -dumpfullversion)"
    echo "base: agent_rs_dev head $(RG rev-parse --short HEAD) ($(RG log -1 --format=%s)); hk_layer.diff md5 $(RG diff HEAD~1 HEAD -- src | md5sum | cut -c1-32)"
    echo "working tree: $(RG diff --name-only HEAD -- src | tr '\n' ' ')"
    echo "working tree diff md5 $(RG diff HEAD -- src | md5sum | cut -c1-32)"
    [ -f "$DIFF" ] && echo "rs_layer_dev.diff $(md5 "$DIFF")"
    for b in "$OUT"/*/libnccl.so.2.32.3; do [ -f "$b" ] && echo "$(basename "$(dirname "$b")") libnccl $(md5 "$b")"; done
    echo "include_digest build $(cd "$W/build/include" && find . -type f | LC_ALL=C sort | xargs md5sum | md5sum | cut -c1-32)"
    [ -f "$OUT/unit/rs_unit_dev" ] && echo "unit: rs_unit_dev.cc $(md5 "$D/rs_unit_dev.cc") rs_pure.inc $(md5 "$OUT/unit/rs_pure.inc") rs_dev_pure.inc $(md5 "$OUT/unit/rs_dev_pure.inc")"
    echo "rs_log_api.h $(md5 "$D/rs_log_api.h" 2>/dev/null || echo none)"
  } > "$OUT/build_info.txt"
  cat "$OUT/build_info.txt"
}
case "$STAGE" in
  setup) setup ;;
  rs) rs ;;
  rsp) rsp ;;
  unit) unit ;;
  api) api ;;
  diff) diffcheck ;;
  info) info ;;
  *) echo "unknown stage $STAGE" >&2; exit 2 ;;
esac
