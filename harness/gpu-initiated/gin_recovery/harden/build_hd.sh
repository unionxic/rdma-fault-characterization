#!/usr/bin/env bash
# Build this study's libraries and drivers in the session scratch, leaving every earlier tree untouched.
# usage: build_hd.sh <setup|hd|hdp|stock|drivers|all>
#   setup:   once: copy agent_ts2ow's source tree and build directory -> agent_ts2hd; rewrite the absolute paths in
#            the dependency files (*.d) and device manifests and give them back their original mtimes, so make rebuilds
#            only what changed; commit the ow state (agent_ts2ow's working tree, = ../oneway/ow_layer.diff on the pcm
#            commit) in the scratch git repo as "gin-oneway ow (libnccl b4af65c5)".
#   hd:      apply hd_layer.diff unless the working tree already carries it; incremental make into build/ (the device
#            headers change, so the device objects are rebuilt too); libnccl -> out/hd/.
#   hdp:     the production build from the SAME source: build/ is copied to build-hdp/ (paths rewritten, mtimes kept),
#            every host object is removed, and make runs with CXXFLAGS=-DNCCL_GIN_TS_PRODUCTION (the switch is read by
#            host files only; make -n must list no device object); libnccl -> out/hdp/.
#   stock:   pristine NCCL v2.32.3-1 (the scratch repo's root commit, checked against the upstream tag 12df1a11 of the
#            session's NCCL clone) as a git worktree stock-src/, full build into build-stock/; libnccl -> out/stk/.
#   drivers: ../gin_ts2.cu against build/ (hd headers) -> out/drv/gin_ts2 (used by the hd, hdp and ow2 bundles) and
#            against build-stock/ with -DGIN_TS_STOCK_API -> out/drv-stk/gin_ts2 (the stk bundle).
# The ow bundle's driver (d4b1f082) and libnccl (b4af65c5) are not rebuilt. All compiles run at nice 19.
set -euo pipefail
STAGE=${1:?setup, hd, hdp, stock, drivers or all}
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
SRC=$SCR/agent_ts2ow
DST=$SCR/agent_ts2hd
D=$(cd "$(dirname "$0")" && pwd)
CUDA=/usr/local/cuda-12.8
GENCODE="-gencode=arch=compute_75,code=sm_75 -gencode=arch=compute_86,code=sm_86"
JOBS=${JOBS:-24}
G() { git -C "$DST/nccl-src" -c user.name=build -c user.email=build@localhost "$@"; }
MK() {  # MK <builddir> [make args]
  local b=$1; shift
  nice -n 19 make -j"$JOBS" -C "$DST/nccl-src" src.build BUILDDIR="$b" CUDA_HOME=$CUDA NVCC_GENCODE="$GENCODE" "$@"
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
  [ -d "$DST/nccl-src" ] && return 0
  [ "$(git -C "$SRC/nccl-src" log -1 --format=%s)" = "gin-oneway pcm (test switches)" ] || { echo "agent_ts2ow head is not pcm" >&2; exit 1; }
  [ "$(git -C "$SRC/nccl-src" diff HEAD -- src | md5sum | cut -c1-8)" = 06f450ec ] || { echo "agent_ts2ow working tree is not ow_layer.diff" >&2; exit 1; }
  [ "$(md5sum < "$SRC/build/lib/libnccl.so.2.32.3" | cut -c1-8)" = b4af65c5 ] || { echo "agent_ts2ow build is not ow" >&2; exit 1; }
  mkdir -p "$DST"
  cp -a "$SRC/nccl-src" "$SRC/build" "$DST/"
  rewrite "$SRC/" "$DST/" "$DST/build"
  G commit -qam "gin-oneway ow (libnccl b4af65c5)"
  echo "setup: agent_ts2hd at $(G rev-parse --short HEAD) ($(G log -1 --format=%s))"
}
copylib() {  # copylib <builddir> <out name>
  mkdir -p "$DST/out/$2"
  cp "$1/lib/libnccl.so.2.32.3" "$DST/out/$2/libnccl.so.2.32.3"
  md5sum "$DST/out/$2/libnccl.so.2.32.3"
}
hd() {
  setup
  case "$(G log -1 --format=%s)" in "gin-oneway ow"*) ;; *) echo "unexpected head commit" >&2; exit 1 ;; esac
  if G diff --quiet HEAD -- src; then G apply "$D/hd_layer.diff"; fi
  echo "hd: to compile (host): $(MK "$DST/build" -n 2>/dev/null | grep -o -- '-c [^ ]*\.cc' | wc -l) files"
  MK "$DST/build"
  copylib "$DST/build" hd
}
hdp() {
  [ -f "$DST/out/hd/libnccl.so.2.32.3" ] || { echo "build hd first" >&2; exit 1; }
  rm -rf "$DST/build-hdp"
  cp -a "$DST/build" "$DST/build-hdp"
  rewrite "$DST/build/" "$DST/build-hdp/" "$DST/build-hdp"
  find "$DST/build-hdp/obj" -name '*.o' -not -path '*/device/*' -delete
  rm -f "$DST/build-hdp/lib/libnccl"*
  local dev
  dev=$(CXXFLAGS=-DNCCL_GIN_TS_PRODUCTION MK "$DST/build-hdp" -n 2>/dev/null | grep -c -- 'obj/device/.*\.o\b' || true)
  echo "hdp: device-object compile commands in make -n: $dev (must be 0)"
  [ "$dev" = 0 ] || { echo "hdp would rebuild device objects" >&2; exit 1; }
  CXXFLAGS=-DNCCL_GIN_TS_PRODUCTION MK "$DST/build-hdp"
  copylib "$DST/build-hdp" hdp
}
stock() {
  setup
  local root up
  root=$(G rev-list --max-parents=0 HEAD)
  up=$SCR/gin/nccl  # the session's NCCL clone (read only)
  [ "$(git -C "$up" rev-parse 'v2.32.3-1^{commit}')" = 12df1a11afad322be5a204a2db890161cbf8131d ] || { echo "no upstream tag" >&2; exit 1; }
  local a b
  a=$(mktemp -d); b=$(mktemp -d)
  git -C "$up" archive v2.32.3-1 | tar -x -C "$a"
  G archive "$root" | tar -x -C "$b"
  if diff -r -q "$a" "$b" > /dev/null; then echo "VERIFIED: scratch root commit $root == upstream v2.32.3-1 (12df1a11)"
  else echo "the scratch root commit differs from upstream v2.32.3-1" >&2; rm -rf "$a" "$b"; exit 1; fi
  rm -rf "$a" "$b"
  [ -d "$DST/stock-src" ] || G worktree add --detach "$DST/stock-src" "$root"
  nice -n 19 make -j"$JOBS" -C "$DST/stock-src" src.build BUILDDIR="$DST/build-stock" CUDA_HOME=$CUDA NVCC_GENCODE="$GENCODE"
  copylib "$DST/build-stock" stk
}
drivers() {
  local cu=$D/../gin_ts2.cu
  mkdir -p "$DST/out/drv" "$DST/out/drv-stk"
  nice -n 19 $CUDA/bin/nvcc -std=c++17 -O2 --expt-relaxed-constexpr $GENCODE -isystem "$DST/build/include" \
    -Xcompiler "-Wall,-Wextra,-Werror,-Wno-missing-field-initializers" "$cu" -o "$DST/out/drv/gin_ts2" \
    -L "$DST/build/lib" -lnccl -lcudart -ldl
  nice -n 19 $CUDA/bin/nvcc -std=c++17 -O2 --expt-relaxed-constexpr -DGIN_TS_STOCK_API $GENCODE \
    -isystem "$DST/build-stock/include" -Xcompiler "-Wall,-Wextra,-Werror,-Wno-missing-field-initializers" "$cu" \
    -o "$DST/out/drv-stk/gin_ts2" -L "$DST/build-stock/lib" -lnccl -lcudart -ldl
  md5sum "$DST/out/drv/gin_ts2" "$DST/out/drv-stk/gin_ts2" "$cu"
}
case "$STAGE" in
  setup) setup ;;
  hd) hd ;;
  hdp) hdp ;;
  stock) stock ;;
  drivers) drivers ;;
  all) hd; hdp; stock; drivers ;;
  *) echo "unknown stage $STAGE" >&2; exit 2 ;;
esac
