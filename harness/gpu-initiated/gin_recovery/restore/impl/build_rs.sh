#!/usr/bin/env bash
# build_rs.sh - build gin-restore's restore layer (EXPERIMENT.md 9.14) on rain, in a NEW scratch tree only. No GPU or RDMA
# program runs here; nothing outside agent_rs_int/ is written (the gpu-detect hk tree agent_gd/gin_hk is read only).
# Integration of the four branches (2026-10-12, impl/PARALLEL.md): the tree is agent_rs_int/ (agent_rs/ and the branch
# trees agent_rs_{dev,host,spare,test}/ are not touched), and rs_layer.diff is the whole integrated layer over hk.
# usage: build_rs.sh <setup|rs|rsp|unitd|unith|units|api|units-all|info>
#   setup  once: check that agent_gd/gin_hk is gpu-detect's hk (head commit "gpu-detect hw", working tree = hk_layer.diff
#          md5 c5222c55, builds hk 2913c777 and hkp 84209c03), copy its nccl-src and build to agent_rs_int/{nccl-src,build}
#          and build-hkp to agent_rs_int/build-rsp, rewrite the absolute paths in the dependency files and device manifests
#          (mtimes kept), and commit hk's working tree in the copy as "gpu-detect hk (libnccl 2913c777)". History: hr, hw, hk.
#   rs     apply rs_layer.diff unless the working tree already carries changes (the changed files must be exactly
#          RS_FILES); incremental make into agent_rs_int/build -> agent_rs_int/out/$RSOUT/libnccl.so.2.32.3 (research
#          build; RSOUT default rs, a folder that already holds a build is refused: give a new name).
#   rsp    the production build of the same source (-DNCCL_GIN_TS_PRODUCTION) into agent_rs_int/build-rsp ->
#          agent_rs_int/out/$RSPOUT/ (default rsp; same refusal).
#   unitd  the CPU unit test of work packages 1-4 (4 redone), 6 and 9: rs_unit_dev.cc (the dev branch's copy of rs_unit.cc,
#          every test function of it with package 4's tests redone for one ring per rank, and packages 6 and 9's) with the
#          regions "gin-restore: pure functions", "gin-restore (dev): log, suppress and replay, pure" and the log API block of
#          the working tree's gin_host_gdaki.cc, the device-host common header and rs_log_api.h (g++, ASan, UBSan; no NCCL,
#          no CUDA, no network).
#          rs_unit.cc itself (packages 1-4 with the withdrawn per-QP rings) does not compile against this tree and is kept
#          only as the record of those packages.
#   unith  the host branch's rs_unit_host.cc (packages 7, 5): the regions "gin-restore hold: pure functions" and
#          "gin-restore ckpt: pure functions"; first, rs_hold_api.h's and rs_ckpt_api.h's shared text are the host file's.
#   units  the spare branch's rs_spare_unit.cc (package 8): the region "gin-restore (rs, work package 8, spare branch): pure
#          functions" and packages 1-4's region (the Resume local check).
#   api    the host file's log API block is rs_log_api.h's, byte for byte.
#   units-all  api, unitd, unith, units.
#   info   agent_rs_int/out/build_info.txt: md5 of every output and input.
# The device objects are rebuilt whenever the device header trees differ from the last build of that directory (devsync;
# NCCL's dependency pass does not see them), so the first build after setup rebuilds every device object (hk's copied
# build carries 22 stale symmetric GIN objects, EXPERIMENT.md 12).
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
W=$SCR/agent_rs_int
OUT=$W/out
HOSTF=src/transport/net_ib/gdaki/gin_host_gdaki.cc
COMMON=src/include/nccl_device/gin/gdaki/gin_gdaki_device_host_common.h
NEW_FILES="src/include/rs_spike.h src/misc/rs_spike.cc"  # work package 8: the init transcript's record and replay
RS_FILES="src/bootstrap.cc src/dev_runtime.cc src/gin/gin_host.cc src/include/gin/gin_host.h \
src/include/nccl_device/gin/gdaki/gin_gdaki.h $COMMON src/init.cc src/nccl.h.in $HOSTF src/transport/net_ib/gin.cc $NEW_FILES"
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
  [ -d "$W/nccl-src" ] && { echo "agent_rs_int already set up" >&2; return 0; }
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
  echo "setup: agent_rs_int at $(RG rev-parse --short HEAD) ($(RG log -1 --format=%s)); base libnccl hk 2913c777 hkp 84209c03"
}
tree() {  # the restore layer on the working tree of the copy (the new files of package 8 as intent-to-add)
  case "$(RG log -1 --format=%s)" in "gpu-detect hk"*) ;; *) echo "unexpected head commit in agent_rs_int" >&2; exit 1 ;; esac
  if RG diff --quiet HEAD -- src && [ ! -e "$W/nccl-src/src/misc/rs_spike.cc" ]; then RG apply "$D/rs_layer.diff"; fi
  RG add -N -- $NEW_FILES
  [ "$(RG diff --name-only HEAD -- src | sort | tr '\n' ' ')" = "$(echo $RS_FILES | tr ' ' '\n' | sort | tr '\n' ' ')" ] ||
    { echo "the working tree changes other files than RS_FILES: $(RG diff --name-only HEAD -- src | tr '\n' ' ')" >&2; exit 1; }
}
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
region() {  # region <begin regex> <end regex> <file>
  awk -v b="$1" -v e="$2" '$0 ~ b {on=1} on {print} $0 ~ e {on=0}' "$3"
}
cut1() {  # cut1 <out> <begin regex> <end regex>: a region of the host file, which must exist
  region "$2" "$3" "$W/nccl-src/$HOSTF" > "$1"
  [ -s "$1" ] || { echo "no region '$2' in $HOSTF" >&2; exit 1; }
}
PURE_B='^// ---- gin-restore: pure functions [(]begin'
PURE_E='^// ---- gin-restore: pure functions [(]end'
policyEnum() {
  grep -qxF 'enum { GDAKI_POLICY_FAILFAST = 0, GDAKI_POLICY_HOLD = 1 };' "$W/nccl-src/$HOSTF" || { echo "hk's policy enum changed" >&2; exit 1; }
}
GXX() { nice -n 19 g++ -std=c++17 -O1 -g -Wall -Wextra -Werror -pthread -fsanitize=address,undefined "$@"; }
unitd() {
  local o=$OUT/unitd; mkdir -p "$o"; policyEnum
  cut1 "$o/rs_pure.inc" "$PURE_B" "$PURE_E"
  cut1 "$o/rs_dev_pure.inc" '^// ---- gin-restore [(]dev[)]: log, suppress and replay, pure [(]begin' \
       '^// ---- gin-restore [(]dev[)]: log, suppress and replay, pure [(]end'
  # work package 9: the log API block (its records and constants) for the dev pure region
  cut1 "$o/rs_dev_api.inc" '^// ---- gin-restore [(]dev[)]: log API [(]begin' '^// ---- gin-restore [(]dev[)]: log API [(]end'
  GXX -I"$o" -I"$D" -I"$W/nccl-src/src/include" "$D/rs_unit_dev.cc" -o "$o/rs_unit_dev"
  "$o/rs_unit_dev"
}
unith() {
  local o=$OUT/unith src=$W/nccl-src/$HOSTF; mkdir -p "$o"; policyEnum
  cut1 "$o/rs_pure.inc" "$PURE_B" "$PURE_E"
  cut1 "$o/rs_hold_pure.inc" '^// ---- gin-restore hold: pure functions [(]begin' '^// ---- gin-restore hold: pure functions [(]end'
  cut1 "$o/rs_ckpt_pure.inc" '^// ---- gin-restore ckpt: pure functions [(]begin' '^// ---- gin-restore ckpt: pure functions [(]end'
  # rs_hold_api.h's and rs_ckpt_api.h's shared text are in the host file verbatim (its first and second fenced block)
  local fence='/^\/\/ ---- shared text \(begin\) ----$/{on=1; k++} on && k==N{print} /^\/\/ ---- shared text \(end\) ----$/{on=0}'
  awk -v N=1 "$fence" "$D/rs_hold_api.h" > "$o/shared_api.txt"
  awk -v N=1 "$fence" "$src" > "$o/shared_src.txt"
  awk -v N=1 "$fence" "$D/rs_ckpt_api.h" > "$o/shared_ckpt_api.txt"
  awk -v N=2 "$fence" "$src" > "$o/shared_ckpt_src.txt"
  [ -s "$o/shared_api.txt" ] && cmp -s "$o/shared_api.txt" "$o/shared_src.txt" ||
    { echo "rs_hold_api.h's shared text differs from the host file's" >&2; exit 1; }
  [ -s "$o/shared_ckpt_api.txt" ] && cmp -s "$o/shared_ckpt_api.txt" "$o/shared_ckpt_src.txt" ||
    { echo "rs_ckpt_api.h's shared text differs from the host file's" >&2; exit 1; }
  [ "$(grep -c '^// ---- shared text (begin) ----$' "$src")" = 2 ] || { echo "the host file has not two shared-text blocks" >&2; exit 1; }
  echo "unith: rs_hold_api.h shared text = host file ($(wc -l < "$o/shared_api.txt") lines)"
  echo "unith: rs_ckpt_api.h shared text = host file ($(wc -l < "$o/shared_ckpt_api.txt") lines)"
  GXX -I"$o" -I"$D" -I"$W/nccl-src/src/include" "$D/rs_unit_host.cc" -o "$o/rs_unit_host"
  "$o/rs_unit_host"
}
units() {
  local o=$OUT/units; mkdir -p "$o"
  cut1 "$o/rs_pure.inc" "$PURE_B" "$PURE_E"
  cut1 "$o/rs_spare_pure.inc" '^// ==== gin-restore [(]rs, work package 8, spare branch[)]: pure functions [(]begin' \
       '^// ==== gin-restore [(]rs, work package 8, spare branch[)]: pure functions [(]end'
  GXX -Wno-unused-function -I"$o" -I"$W/nccl-src/src/include" "$D/rs_spare_unit.cc" -o "$o/rs_spare_unit"
  "$o/rs_spare_unit"
}
api() {
  local a b B='^// ---- gin-restore [(]dev[)]: log API [(]begin' E='^// ---- gin-restore [(]dev[)]: log API [(]end'
  [ -n "$(region "$B" "$E" "$D/rs_log_api.h")" ] || { echo "no log API block in rs_log_api.h" >&2; exit 1; }
  a=$(region "$B" "$E" "$W/nccl-src/$HOSTF" | md5sum | cut -c1-32)
  b=$(region "$B" "$E" "$D/rs_log_api.h" | md5sum | cut -c1-32)
  [ "$a" = "$b" ] || { echo "the host file's log API block differs from rs_log_api.h ($a vs $b)" >&2; exit 1; }
  echo "api: the host file's log API block is rs_log_api.h's ($a)"
}
info() {
  {
    echo "built=$(date '+%F %T') host=$(hostname -s) nvcc=$("$CUDA/bin/nvcc" --version | tail -1) g++=$(g++ -dumpfullversion)"
    echo "base: agent_rs_int head $(RG rev-parse --short HEAD) ($(RG log -1 --format=%s)); hk_layer.diff md5 $(RG diff HEAD~1 HEAD -- src | md5sum | cut -c1-32)"
    echo "working tree: $(RG diff --name-only HEAD -- src | tr '\n' ' ')"
    echo "working tree diff md5 $(RG diff --diff-algorithm=histogram HEAD -- src | md5sum | cut -c1-32) (histogram, as make_diff_rs.sh)"
    [ -f "$D/rs_layer.diff" ] && echo "rs_layer.diff $(md5 "$D/rs_layer.diff")"
    for b in "$OUT"/*/libnccl.so.2.32.3; do [ -f "$b" ] && echo "$(basename "$(dirname "$b")") libnccl $(md5 "$b")"; done
    echo "include_digest build $(cd "$W/build/include" && find . -type f | LC_ALL=C sort | xargs md5sum | md5sum | cut -c1-32)"
    echo "include_digest hk $(cd "$HK/build/include" && find . -type f | LC_ALL=C sort | xargs md5sum | md5sum | cut -c1-32)"
    for f in rs_unit.cc rs_unit_dev.cc rs_unit_host.cc rs_spare_unit.cc rs_log_api.h rs_hold_api.h rs_ckpt_api.h rs_spare_api.h; do
      echo "$f $(md5 "$D/$f")"; done
  } > "$OUT/build_info.txt"
  cat "$OUT/build_info.txt"
}
case "$STAGE" in
  setup) setup ;;
  rs) rs ;;
  rsp) rsp ;;
  unitd) unitd ;;
  unith) unith ;;
  units) units ;;
  api) api ;;
  units-all) api; unitd; unith; units ;;
  info) info ;;
  *) echo "unknown stage $STAGE" >&2; exit 2 ;;
esac
