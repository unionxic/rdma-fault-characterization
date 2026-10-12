#!/usr/bin/env bash
# build_rs.sh - build gin-restore's restore layer (EXPERIMENT.md 9.14) on rain, in a NEW scratch tree only. No GPU or RDMA
# program runs here; nothing outside agent_rs/ is written (the gpu-detect hk tree agent_gd/gin_hk is read only).
# usage: build_rs.sh <setup|rs|rsp|unit|info>
#   setup  once: check that agent_gd/gin_hk is gpu-detect's hk (head commit "gpu-detect hw", working tree = hk_layer.diff
#          md5 c5222c55, builds hk 2913c777 and hkp 84209c03), copy its nccl-src and build to agent_rs/{nccl-src,build}
#          and build-hkp to agent_rs/build-rsp, rewrite the absolute paths in the dependency files and device manifests
#          (mtimes kept, so make rebuilds only what changed), and commit hk's working tree in the copy as
#          "gpu-detect hk (libnccl 2913c777)". The copy's history: hr, hw, hk.
#   rs     apply rs_layer.diff unless the working tree already carries changes (the changed files must be exactly
#          RS_FILES); incremental make into agent_rs/build -> agent_rs/out/$RSOUT/libnccl.so.2.32.3 (research build;
#          RSOUT default rs, a folder that already holds a build is refused: give a new name).
#   rsp    the production build of the same source (-DNCCL_GIN_TS_PRODUCTION) into agent_rs/build-rsp ->
#          agent_rs/out/$RSPOUT/ (default rsp; same refusal).
#   unit   the CPU unit test of the decision and reason functions: the region between the two "gin-restore: pure
#          functions" markers of the working tree's gin_host_gdaki.cc is cut out and compiled with rs_unit.cc (g++, no
#          NCCL, no CUDA, no network) -> agent_rs/out/unit/rs_unit, then run. Work package 4: rs_unit.cc also includes the
#          working tree's device-host common header (the checksum, the log entry, the suppression plan the device uses).
#   info   agent_rs/out/build_info.txt: md5 of every output and input.
# All compiles run at nice 19 and idle I/O priority (other studies use this node).
set -euo pipefail
STAGE=${1:?stage}
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
D=$(cd "$(dirname "$0")" && pwd)
CUDA=/usr/local/cuda-12.8
GENCODE="-gencode=arch=compute_75,code=sm_75 -gencode=arch=compute_86,code=sm_86"
JOBS=${JOBS:-8}
RSOUT=${RSOUT:-rs}
RSPOUT=${RSPOUT:-rsp}
HK=$SCR/agent_gd/gin_hk
W=$SCR/agent_rs
OUT=$W/out
HOSTF=src/transport/net_ib/gdaki/gin_host_gdaki.cc
RS_FILES="src/gin/gin_host.cc src/include/gin/gin_host.h src/include/nccl_device/gin/gdaki/gin_gdaki.h src/include/nccl_device/gin/gdaki/gin_gdaki_device_host_common.h src/nccl.h.in $HOSTF"
# work package 2: + the public entry; work package 3: + the device-host common header (the side-table pointer);
# work package 4: + the device header (the hold path)
KG() { git -C "$HK/nccl-src" -c user.name=build -c user.email=build@localhost "$@"; }
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
  [ -d "$W/nccl-src" ] && { echo "agent_rs already set up" >&2; return 0; }
  case "$(KG log -1 --format=%s)" in "gpu-detect hw"*) ;; *) echo "agent_gd/gin_hk head is not the hw commit" >&2; exit 1 ;; esac
  [ "$(KG diff HEAD -- src | md5sum | cut -c1-8)" = c5222c55 ] || { echo "agent_gd/gin_hk working tree is not hk_layer.diff" >&2; exit 1; }
  [ "$(md5 "$HK/build/lib/libnccl.so.2.32.3")" = 2913c777aa0b05d4d566c9f7638c6a0e ] || { echo "agent_gd/gin_hk build is not hk" >&2; exit 1; }
  [ "$(md5 "$HK/build-hkp/lib/libnccl.so.2.32.3")" = 84209c03a497bd28206210205bfc6cf5 ] || { echo "agent_gd/gin_hk build-hkp is not hkp" >&2; exit 1; }
  mkdir -p "$W"
  cp -a "$HK/nccl-src" "$HK/build" "$W/"
  cp -a "$HK/build-hkp" "$W/build-rsp"
  rm -rf "$W/nccl-src/.git/worktrees"
  rewrite "$HK/build-hkp/" "$W/build-rsp/" "$W/build-rsp"
  rewrite "$HK/" "$W/" "$W/build-rsp"
  rewrite "$HK/" "$W/" "$W/build"
  RG add -A src
  RG commit -qm "gpu-detect hk (libnccl 2913c777)"
  [ "$(RG diff HEAD~1 HEAD -- src | md5sum | cut -c1-8)" = c5222c55 ] || { echo "the hk commit is not hk_layer.diff" >&2; exit 1; }
  [ "$(RG diff HEAD~2 HEAD~1 -- src | md5sum | cut -c1-8)" = be0ea9ed ] || { echo "the commit below hk is not hw_layer.diff" >&2; exit 1; }
  [ "$(md5 "$W/build/lib/libnccl.so.2.32.3")" = 2913c777aa0b05d4d566c9f7638c6a0e ] || { echo "the copied build is not hk" >&2; exit 1; }
  [ "$(md5 "$W/build-rsp/lib/libnccl.so.2.32.3")" = 84209c03a497bd28206210205bfc6cf5 ] || { echo "the copied build-rsp is not hkp" >&2; exit 1; }
  echo "setup: agent_rs at $(RG rev-parse --short HEAD) ($(RG log -1 --format=%s)); base libnccl hk 2913c777 hkp 84209c03"
  echo "setup: make -n in build/ after the copy: $(MKS "$W/build" -n 2>/dev/null | grep -c -- ' -c ' || true) compile commands"
}
tree() {  # the restore layer on the working tree of the copy
  case "$(RG log -1 --format=%s)" in "gpu-detect hk"*) ;; *) echo "unexpected head commit in agent_rs" >&2; exit 1 ;; esac
  if RG diff --quiet HEAD -- src; then RG apply "$D/rs_layer.diff"; fi
  [ "$(RG diff --name-only HEAD -- src | sort | tr '\n' ' ')" = "$(echo $RS_FILES | tr ' ' '\n' | sort | tr '\n' ' ')" ] ||
    { echo "the working tree changes other files than RS_FILES: $(RG diff --name-only HEAD -- src | tr '\n' ' ')" >&2; exit 1; }
}
# NCCL's device dependency pass (src/device/Makefile: nvcc -MM -dc) does not see headers that are included only in device
# compilation (gin__funcs.h -> gin_device_api.h under __CUDACC__, gin_gdaki.h under __CUDA_ARCH__), so a change of
# src/include/nccl_device/** does not rebuild the device objects that use them (work package 3's review: the symmetric GIN
# kernels kept the old GPU context stride). devsync <builddir>: when that tree differs from the one recorded at the build
# directory's last build, remove its device objects so that make rebuilds every one; the digest is recorded after a
# successful make (devdone).
# The vendored DOCA device headers are installed under nccl_device too (src/Makefile) and reached the same way: both trees.
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
fresh() {  # fresh <dir>: refuse a folder that already holds a build
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
unit() {
  local o=$OUT/unit src=$W/nccl-src/$HOSTF
  mkdir -p "$o"
  awk '/^\/\/ ---- gin-restore: pure functions \(begin/{on=1} on{print} /^\/\/ ---- gin-restore: pure functions \(end/{on=0}' \
    "$src" > "$o/rs_pure.inc"
  [ -s "$o/rs_pure.inc" ] || { echo "no pure-function region in $HOSTF" >&2; exit 1; }
  # the region uses hk's policy enum: the test defines it, and it must be the line the host file has
  grep -qxF 'enum { GDAKI_POLICY_FAILFAST = 0, GDAKI_POLICY_HOLD = 1 };' "$src" || { echo "hk's policy enum changed" >&2; exit 1; }
  nice -n 19 g++ -std=c++17 -O1 -g -Wall -Wextra -Werror -pthread -fsanitize=address,undefined -I"$o" \
    -I"$W/nccl-src/src/include" "$D/rs_unit.cc" -o "$o/rs_unit"
  "$o/rs_unit"
}
info() {
  {
    echo "built=$(date '+%F %T') host=$(hostname -s) nvcc=$("$CUDA/bin/nvcc" --version | tail -1) g++=$(g++ -dumpfullversion)"
    echo "base: agent_rs head $(RG rev-parse --short HEAD) ($(RG log -1 --format=%s)); hk_layer.diff md5 $(RG diff HEAD~1 HEAD -- src | md5sum | cut -c1-32)"
    echo "working tree: $(RG diff --name-only HEAD -- src | tr '\n' ' ')"
    echo "working tree diff md5 $(RG diff HEAD -- src | md5sum | cut -c1-32)"
    [ -f "$D/rs_layer.diff" ] && echo "rs_layer.diff $(md5 "$D/rs_layer.diff")"
    for b in "$OUT"/*/libnccl.so.2.32.3; do [ -f "$b" ] && echo "$(basename "$(dirname "$b")") libnccl $(md5 "$b")"; done
    echo "include_digest build $(cd "$W/build/include" && find . -type f | LC_ALL=C sort | xargs md5sum | md5sum | cut -c1-32)"
    echo "include_digest hk $(cd "$HK/build/include" && find . -type f | LC_ALL=C sort | xargs md5sum | md5sum | cut -c1-32)"
    [ -f "$OUT/unit/rs_unit" ] && echo "unit: rs_unit.cc $(md5 "$D/rs_unit.cc") rs_pure.inc $(md5 "$OUT/unit/rs_pure.inc")"
  } > "$OUT/build_info.txt"
  cat "$OUT/build_info.txt"
}
case "$STAGE" in
  setup) setup ;;
  rs) rs ;;
  rsp) rsp ;;
  unit) unit ;;
  info) info ;;
  *) echo "unknown stage $STAGE" >&2; exit 2 ;;
esac
