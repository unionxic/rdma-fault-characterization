#!/usr/bin/env bash
# Build this study's libraries and drivers in the session scratch, leaving every earlier tree untouched.
# usage: build_hq.sh <setup|hq|hqp|drivers|all>
#   setup:   once: copy agent_ts2hf's source tree, its research build directory build/ and its production build directory
#            build-hfp/ -> agent_ts2hq (build-hfp/ becomes build-hqp/); rewrite the absolute paths in the dependency files
#            (*.d) and device manifests and give them back their original mtimes, so make rebuilds only what changed;
#            drop a copied git worktree registration, if any; commit the hf state (agent_ts2hf's working tree =
#            ../handoff/hf_layer.diff on the hd commit) in the scratch git repo as "gin-handoff hf (libnccl b6372d86)".
#   hq:      apply hq_layer.diff unless the working tree already carries it; the changed files must be exactly LAYER_FILES;
#            incremental make into build/ (the layer changes a device header, so device objects are rebuilt too);
#            libnccl -> out/hq/.
#   hqp:     the production build from the SAME source: incremental make into build-hqp/ (whose host objects were all
#            compiled with -DNCCL_GIN_TS_PRODUCTION by the earlier production builds) with CXXFLAGS=-DNCCL_GIN_TS_PRODUCTION;
#            libnccl -> out/hqp/.
#   drivers: ../gin_ts2.cu against build/ headers -> out/drv/gin_ts2 (used by the hq and hqp bundles), and this folder's
#            gin_mr.cu against the same headers -> out/mr/gin_mr (+ build_info.txt). Warnings are errors.
# All compiles run at nice 19 and idle I/O priority with JOBS (default 8) jobs: other studies run on this node.
set -euo pipefail
STAGE=${1:?setup, hq, hqp, drivers or all}
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
SRC=$SCR/agent_ts2hf
DST=$SCR/agent_ts2hq
D=$(cd "$(dirname "$0")" && pwd)
CUDA=/usr/local/cuda-12.8
GENCODE="-gencode=arch=compute_75,code=sm_75 -gencode=arch=compute_86,code=sm_86"
JOBS=${JOBS:-8}
# the files hq_layer.diff changes
LAYER_FILES="src/dev_runtime.cc src/include/nccl_device/gin/gdaki/gin_gdaki.h src/include/nccl_device/gin/gdaki/gin_gdaki_device_host_common.h src/init.cc src/transport/net_ib/gdaki/gin_host_gdaki.cc"
G() { git -C "$DST/nccl-src" -c user.name=build -c user.email=build@localhost "$@"; }
MK() {  # MK <builddir> [make args]
  local b=$1; shift
  nice -n 19 ionice -c3 make -j"$JOBS" -C "$DST/nccl-src" src.build BUILDDIR="$b" CUDA_HOME=$CUDA NVCC_GENCODE="$GENCODE" "$@"
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
  case "$(git -C "$SRC/nccl-src" log -1 --format=%s)" in "gin-harden hd"*) ;; *) echo "agent_ts2hf head is not hd" >&2; exit 1 ;; esac
  [ "$(git -C "$SRC/nccl-src" diff HEAD -- src | md5sum | cut -c1-8)" = a2bcaf69 ] || { echo "agent_ts2hf working tree is not hf_layer.diff" >&2; exit 1; }
  [ "$(md5sum < "$SRC/build/lib/libnccl.so.2.32.3" | cut -c1-8)" = b6372d86 ] || { echo "agent_ts2hf build is not hf" >&2; exit 1; }
  [ "$(md5sum < "$SRC/build-hfp/lib/libnccl.so.2.32.3" | cut -c1-8)" = 1ae4ce9a ] || { echo "agent_ts2hf build-hfp is not hfp" >&2; exit 1; }
  mkdir -p "$DST"
  cp -a "$SRC/nccl-src" "$SRC/build" "$DST/"
  cp -a "$SRC/build-hfp" "$DST/build-hqp"
  rm -rf "$DST/nccl-src/.git/worktrees"  # a copied registration would not be ours
  rewrite "$SRC/build-hfp/" "$DST/build-hqp/" "$DST/build-hqp"
  rewrite "$SRC/" "$DST/" "$DST/build-hqp"
  rewrite "$SRC/" "$DST/" "$DST/build"
  G commit -qam "gin-handoff hf (libnccl b6372d86)"
  [ "$(G diff HEAD~1 HEAD -- src | md5sum | cut -c1-8)" = a2bcaf69 ] || { echo "the hf commit is not hf_layer.diff" >&2; exit 1; }
  echo "setup: agent_ts2hq at $(G rev-parse --short HEAD) ($(G log -1 --format=%s))"
  echo "setup: make -n in build/ after the copy: $(MK "$DST/build" -n 2>/dev/null | grep -c -- ' -c ' || true) compile commands"
}
copylib() {  # copylib <builddir> <out name>
  mkdir -p "$DST/out/$2"
  cp "$1/lib/libnccl.so.2.32.3" "$DST/out/$2/libnccl.so.2.32.3"
  md5sum "$DST/out/$2/libnccl.so.2.32.3"
}
# the compile commands make would run in <builddir> (one line each: the object it writes)
plan() { MK "$1" -n 2>/dev/null | grep -oE -- '-o [^ ]+\.o\b' | sed 's/^-o //' | sort -u; }
hq() {
  setup
  case "$(G log -1 --format=%s)" in "gin-handoff hf"*) ;; *) echo "unexpected head commit" >&2; exit 1 ;; esac
  if G diff --quiet HEAD -- src; then G apply "$D/hq_layer.diff"; fi
  [ "$(G diff --name-only HEAD -- src | sort | tr '\n' ' ')" = "$(echo $LAYER_FILES | tr ' ' '\n' | sort | tr '\n' ' ')" ] ||
    { echo "the working tree changes other files than $LAYER_FILES" >&2; exit 1; }
  local p; p=$(plan "$DST/build")
  echo "hq: objects to compile: $(echo "$p" | grep -c . || true) (device: $(echo "$p" | grep -c 'obj/device/' || true))"
  MK "$DST/build"
  copylib "$DST/build" hq
}
hqp() {
  [ -f "$DST/out/hq/libnccl.so.2.32.3" ] || { echo "build hq first" >&2; exit 1; }
  local p; p=$(CXXFLAGS=-DNCCL_GIN_TS_PRODUCTION plan "$DST/build-hqp")
  echo "hqp: objects to compile: $(echo "$p" | grep -c . || true) (device: $(echo "$p" | grep -c 'obj/device/' || true))"
  CXXFLAGS=-DNCCL_GIN_TS_PRODUCTION MK "$DST/build-hqp"
  copylib "$DST/build-hqp" hqp
  # the two builds must carry the same device headers (the drivers are compiled once, against build/)
  diff -r -q "$DST/build/include/nccl_device" "$DST/build-hqp/include/nccl_device" > /dev/null ||
    { echo "the hqp device headers differ from hq" >&2; exit 1; }
}
drivers() {
  local inc=$DST/build/include lib=$DST/build/lib
  mkdir -p "$DST/out/drv" "$DST/out/mr"
  nice -n 19 $CUDA/bin/nvcc -std=c++17 -O2 --expt-relaxed-constexpr $GENCODE -isystem "$inc" \
    -Xcompiler "-Wall,-Wextra,-Werror,-Wno-missing-field-initializers" "$D/../gin_ts2.cu" -o "$DST/out/drv/gin_ts2" \
    -L "$lib" -lnccl -lcudart -ldl
  nice -n 19 $CUDA/bin/nvcc -std=c++17 -O2 --expt-relaxed-constexpr $GENCODE -isystem "$inc" \
    -Xcompiler "-Wall,-Wextra,-Werror,-Wno-missing-field-initializers" "$D/gin_mr.cu" -o "$DST/out/mr/gin_mr" \
    -L "$lib" -lnccl -lcudart
  {
    echo "built=$(date '+%F %T') nccl_build=$DST/build"
    echo "gin_ts2_md5=$(md5sum < "$DST/out/drv/gin_ts2" | cut -d' ' -f1) gin_ts2_cu_md5=$(md5sum < "$D/../gin_ts2.cu" | cut -d' ' -f1)"
    echo "gin_mr_md5=$(md5sum < "$DST/out/mr/gin_mr" | cut -d' ' -f1) gin_mr_cu_md5=$(md5sum < "$D/gin_mr.cu" | cut -d' ' -f1)"
    echo "libnccl_hq_md5=$(md5sum < "$DST/build/lib/libnccl.so.2.32.3" | cut -d' ' -f1)"
    echo "include_digest=$(cd "$inc" && find . -type f | LC_ALL=C sort | xargs md5sum | md5sum | cut -d' ' -f1)"
    echo "nvcc=$($CUDA/bin/nvcc --version | tail -1)"
  } > "$DST/out/build_info.txt"
  cat "$DST/out/build_info.txt"
}
case "$STAGE" in
  setup) setup ;;
  hq) hq ;;
  hqp) hqp ;;
  drivers) drivers ;;
  all) hq; hqp; drivers ;;
  *) echo "unknown stage $STAGE" >&2; exit 2 ;;
esac
