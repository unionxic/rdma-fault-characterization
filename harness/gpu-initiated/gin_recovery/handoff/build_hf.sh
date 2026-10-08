#!/usr/bin/env bash
# Build this study's libraries and driver in the session scratch, leaving every earlier tree untouched.
# usage: build_hf.sh <setup|hf|hfp|driver|all>
#   setup:  once: copy agent_ts2hd's source tree, its research build directory build/ and its production build directory
#           build-hdp/ -> agent_ts2hf (build-hdp/ becomes build-hfp/); rewrite the absolute paths in the dependency files
#           (*.d) and device manifests and give them back their original mtimes, so make rebuilds only what changed;
#           drop the copied git worktree registration (agent_ts2hd's stock-src belongs to agent_ts2hd); commit the hd
#           state (agent_ts2hd's working tree = ../harden/hd_layer.diff on the ow commit) in the scratch git repo as
#           "gin-harden hd (libnccl e2090323)".
#   hf:     apply hf_layer.diff unless the working tree already carries it; incremental make into build/ (the layer
#           changes host files only, so make -n must list no device object); libnccl -> out/hf/.
#   hfp:    the production build from the SAME source: incremental make into build-hfp/ (whose host objects were all
#           compiled with -DNCCL_GIN_TS_PRODUCTION by ../harden/build_hd.sh hdp) with CXXFLAGS=-DNCCL_GIN_TS_PRODUCTION;
#           make -n must list exactly the host objects of the files the layer changes and no device object;
#           libnccl -> out/hfp/.
#   driver: ../gin_ts2.cu against build/ (hf headers; the device headers are the hd ones, checked) -> out/drv/gin_ts2
#           (used by the hf and hfp bundles). The hd bundle's driver (c0b73e09) is not rebuilt.
# All compiles run at nice 19 and idle I/O priority with JOBS (default 8) jobs: other studies run on this node.
set -euo pipefail
STAGE=${1:?setup, hf, hfp, driver or all}
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
SRC=$SCR/agent_ts2hd
DST=$SCR/agent_ts2hf
D=$(cd "$(dirname "$0")" && pwd)
CUDA=/usr/local/cuda-12.8
GENCODE="-gencode=arch=compute_75,code=sm_75 -gencode=arch=compute_86,code=sm_86"
JOBS=${JOBS:-8}
LAYER_FILES="src/init.cc src/transport/net_ib/gdaki/gin_host_gdaki.cc"  # the files hf_layer.diff changes
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
  case "$(git -C "$SRC/nccl-src" log -1 --format=%s)" in "gin-oneway ow"*) ;; *) echo "agent_ts2hd head is not ow" >&2; exit 1 ;; esac
  [ "$(git -C "$SRC/nccl-src" diff HEAD -- src | md5sum | cut -c1-8)" = 2226872e ] || { echo "agent_ts2hd working tree is not hd_layer.diff" >&2; exit 1; }
  [ "$(md5sum < "$SRC/build/lib/libnccl.so.2.32.3" | cut -c1-8)" = e2090323 ] || { echo "agent_ts2hd build is not hd" >&2; exit 1; }
  [ "$(md5sum < "$SRC/build-hdp/lib/libnccl.so.2.32.3" | cut -c1-8)" = 4818e30b ] || { echo "agent_ts2hd build-hdp is not hdp" >&2; exit 1; }
  mkdir -p "$DST"
  cp -a "$SRC/nccl-src" "$SRC/build" "$DST/"
  cp -a "$SRC/build-hdp" "$DST/build-hfp"
  rm -rf "$DST/nccl-src/.git/worktrees"  # the copied registration of agent_ts2hd/stock-src (not ours)
  rewrite "$SRC/build-hdp/" "$DST/build-hfp/" "$DST/build-hfp"
  rewrite "$SRC/" "$DST/" "$DST/build-hfp"
  rewrite "$SRC/" "$DST/" "$DST/build"
  G commit -qam "gin-harden hd (libnccl e2090323)"
  [ "$(G diff HEAD~1 HEAD -- src | md5sum | cut -c1-8)" = 2226872e ] || { echo "the hd commit is not hd_layer.diff" >&2; exit 1; }
  echo "setup: agent_ts2hf at $(G rev-parse --short HEAD) ($(G log -1 --format=%s))"
  echo "setup: make -n in build/ after the copy: $(MK "$DST/build" -n 2>/dev/null | grep -c -- ' -c ' || true) compile commands"
}
copylib() {  # copylib <builddir> <out name>
  mkdir -p "$DST/out/$2"
  cp "$1/lib/libnccl.so.2.32.3" "$DST/out/$2/libnccl.so.2.32.3"
  md5sum "$DST/out/$2/libnccl.so.2.32.3"
}
# the compile commands make would run in <builddir> (one line each: the object it writes)
plan() { MK "$1" -n 2>/dev/null | grep -oE -- '-o [^ ]+\.o\b' | sed 's/^-o //' | sort -u; }
hf() {
  setup
  case "$(G log -1 --format=%s)" in "gin-harden hd"*) ;; *) echo "unexpected head commit" >&2; exit 1 ;; esac
  if G diff --quiet HEAD -- src; then G apply "$D/hf_layer.diff"; fi
  [ "$(G diff --name-only HEAD -- src | sort | tr '\n' ' ')" = "$(echo $LAYER_FILES | tr ' ' '\n' | sort | tr '\n' ' ')" ] ||
    { echo "the working tree changes other files than $LAYER_FILES" >&2; exit 1; }
  local p; p=$(plan "$DST/build")
  echo "hf: objects to compile: $(echo "$p" | grep -c . || true)"; echo "$p" | sed 's/^/  /'
  if echo "$p" | grep -q 'obj/device/'; then echo "hf would rebuild device objects" >&2; exit 1; fi
  MK "$DST/build"
  copylib "$DST/build" hf
}
hfp() {
  [ -f "$DST/out/hf/libnccl.so.2.32.3" ] || { echo "build hf first" >&2; exit 1; }
  local p; p=$(CXXFLAGS=-DNCCL_GIN_TS_PRODUCTION plan "$DST/build-hfp")
  echo "hfp: objects to compile: $(echo "$p" | grep -c . || true)"; echo "$p" | sed 's/^/  /'
  if echo "$p" | grep -q 'obj/device/'; then echo "hfp would rebuild device objects" >&2; exit 1; fi
  CXXFLAGS=-DNCCL_GIN_TS_PRODUCTION MK "$DST/build-hfp"
  copylib "$DST/build-hfp" hfp
}
driver() {
  local cu=$D/../gin_ts2.cu
  # the driver's device code comes from the installed device headers: they must be the hd ones
  diff -r -q "$SRC/build/include/nccl_device" "$DST/build/include/nccl_device" > /dev/null ||
    { echo "the hf device headers differ from hd" >&2; exit 1; }
  mkdir -p "$DST/out/drv"
  nice -n 19 $CUDA/bin/nvcc -std=c++17 -O2 --expt-relaxed-constexpr $GENCODE -isystem "$DST/build/include" \
    -Xcompiler "-Wall,-Wextra,-Werror,-Wno-missing-field-initializers" "$cu" -o "$DST/out/drv/gin_ts2" \
    -L "$DST/build/lib" -lnccl -lcudart -ldl
  md5sum "$DST/out/drv/gin_ts2" "$cu"
}
case "$STAGE" in
  setup) setup ;;
  hf) hf ;;
  hfp) hfp ;;
  driver) driver ;;
  all) hf; hfp; driver ;;
  *) echo "unknown stage $STAGE" >&2; exit 2 ;;
esac
