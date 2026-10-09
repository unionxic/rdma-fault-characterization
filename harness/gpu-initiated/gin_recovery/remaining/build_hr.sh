#!/usr/bin/env bash
# Build this study's libraries and drivers in the session scratch, leaving every earlier tree untouched.
# usage: build_hr.sh <setup|hr|hrp|drivers|ngt|all>
#   setup:   once: copy agent_ts2hq's source tree, its research build directory build/ and its production build directory
#            build-hqp/ -> agent_ts2hr (build-hqp/ becomes build-hrp/); rewrite the absolute paths in the dependency files
#            (*.d) and device manifests and give them back their original mtimes, so make rebuilds only what changed;
#            drop a copied git worktree registration, if any; commit the hq state (agent_ts2hq's working tree =
#            ../peer/hq_layer.diff on the hf commit) in the scratch git repo as "gin-peer hq (libnccl c1311625)".
#   hr:      apply hr_layer.diff unless the working tree already carries it; the changed files must be exactly LAYER_FILES;
#            incremental make into build/ (the layer changes a device header that NCCL's own device objects do not
#            include, so no device object is rebuilt); libnccl -> out/hr/.
#   hrp:     the production build from the SAME source: incremental make into build-hrp/ (whose host objects were all
#            compiled with -DNCCL_GIN_TS_PRODUCTION by the earlier production builds) with CXXFLAGS=-DNCCL_GIN_TS_PRODUCTION;
#            libnccl -> out/hrp/.
#   drivers: ../gin_ts2.cu against build/ headers -> out/drv/gin_ts2 (used by the hr and hrp bundles and, with the hq
#            libnccl, by the hq controls), this folder's gin_mr.cu -> out/mr/gin_mr, and this folder's hm_bench.cu ->
#            out/drv/hm_bench (+ build_info.txt). Warnings are errors. (nvcc output is not byte-reproducible: a rerun
#            changes these md5 values; the deployed ones are recorded in EXPERIMENT.md 12.)
#   ngt:     this folder's nic_gate_test.cu (no NCCL; libibverbs, libcuda) -> out/ngt/nic_gate_test (+ out/ngt/build_info.txt).
#            Built on its own after the pilot (EXPERIMENT.md 12) so the deployed drivers stay as they are.
# All compiles run at nice 19 and idle I/O priority with JOBS (default 8) jobs: other studies run on this node.
set -euo pipefail
STAGE=${1:?setup, hr, hrp, drivers, ngt or all}
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
SRC=$SCR/agent_ts2hq
DST=$SCR/agent_ts2hr
D=$(cd "$(dirname "$0")" && pwd)
CUDA=/usr/local/cuda-12.8
GENCODE="-gencode=arch=compute_75,code=sm_75 -gencode=arch=compute_86,code=sm_86"
JOBS=${JOBS:-8}
# the files hr_layer.diff changes
LAYER_FILES="src/include/nccl_device/gin/gdaki/gin_gdaki.h src/include/nccl_device/gin/gdaki/gin_gdaki_device_host_common.h src/transport/net_ib/gdaki/gin_host_gdaki.cc"
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
  case "$(git -C "$SRC/nccl-src" log -1 --format=%s)" in "gin-handoff hf"*) ;; *) echo "agent_ts2hq head is not hf" >&2; exit 1 ;; esac
  [ "$(git -C "$SRC/nccl-src" diff HEAD -- src | md5sum | cut -c1-8)" = 34ab6201 ] || { echo "agent_ts2hq working tree is not hq_layer.diff" >&2; exit 1; }
  [ "$(md5sum < "$SRC/build/lib/libnccl.so.2.32.3" | cut -c1-8)" = c1311625 ] || { echo "agent_ts2hq build is not hq" >&2; exit 1; }
  [ "$(md5sum < "$SRC/build-hqp/lib/libnccl.so.2.32.3" | cut -c1-8)" = 4fa076e1 ] || { echo "agent_ts2hq build-hqp is not hqp" >&2; exit 1; }
  mkdir -p "$DST"
  cp -a "$SRC/nccl-src" "$SRC/build" "$DST/"
  cp -a "$SRC/build-hqp" "$DST/build-hrp"
  rm -rf "$DST/nccl-src/.git/worktrees"  # a copied registration would not be ours
  rewrite "$SRC/build-hqp/" "$DST/build-hrp/" "$DST/build-hrp"
  rewrite "$SRC/" "$DST/" "$DST/build-hrp"
  rewrite "$SRC/" "$DST/" "$DST/build"
  G commit -qam "gin-peer hq (libnccl c1311625)"
  [ "$(G diff HEAD~1 HEAD -- src | md5sum | cut -c1-8)" = 34ab6201 ] || { echo "the hq commit is not hq_layer.diff" >&2; exit 1; }
  echo "setup: agent_ts2hr at $(G rev-parse --short HEAD) ($(G log -1 --format=%s))"
  echo "setup: make -n in build/ after the copy: $(MK "$DST/build" -n 2>/dev/null | grep -c -- ' -c ' || true) compile commands"
}
copylib() {  # copylib <builddir> <out name>
  mkdir -p "$DST/out/$2"
  cp "$1/lib/libnccl.so.2.32.3" "$DST/out/$2/libnccl.so.2.32.3"
  md5sum "$DST/out/$2/libnccl.so.2.32.3"
}
# the compile commands make would run in <builddir> (one line each: the object it writes)
plan() { MK "$1" -n 2>/dev/null | grep -oE -- '-o [^ ]+\.o\b' | sed 's/^-o //' | sort -u; }
hr() {
  setup
  case "$(G log -1 --format=%s)" in "gin-peer hq"*) ;; *) echo "unexpected head commit" >&2; exit 1 ;; esac
  if G diff --quiet HEAD -- src; then G apply "$D/hr_layer.diff"; fi
  [ "$(G diff --name-only HEAD -- src | sort | tr '\n' ' ')" = "$(echo $LAYER_FILES | tr ' ' '\n' | sort | tr '\n' ' ')" ] ||
    { echo "the working tree changes other files than $LAYER_FILES" >&2; exit 1; }
  local p; p=$(plan "$DST/build")
  echo "hr: objects to compile: $(echo "$p" | grep -c . || true) (device: $(echo "$p" | grep -c 'obj/device/' || true))"
  MK "$DST/build"
  copylib "$DST/build" hr
}
hrp() {
  [ -f "$DST/out/hr/libnccl.so.2.32.3" ] || { echo "build hr first" >&2; exit 1; }
  local p; p=$(CXXFLAGS=-DNCCL_GIN_TS_PRODUCTION plan "$DST/build-hrp")
  echo "hrp: objects to compile: $(echo "$p" | grep -c . || true) (device: $(echo "$p" | grep -c 'obj/device/' || true))"
  CXXFLAGS=-DNCCL_GIN_TS_PRODUCTION MK "$DST/build-hrp"
  copylib "$DST/build-hrp" hrp
  # the two builds must carry the same device headers (the drivers are compiled once, against build/)
  diff -r -q "$DST/build/include/nccl_device" "$DST/build-hrp/include/nccl_device" > /dev/null ||
    { echo "the hrp device headers differ from hr" >&2; exit 1; }
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
  nice -n 19 $CUDA/bin/nvcc -std=c++17 -O2 $GENCODE \
    -Xcompiler "-Wall,-Wextra,-Werror" "$D/hm_bench.cu" -o "$DST/out/drv/hm_bench" -lcudart
  {
    echo "built=$(date '+%F %T') nccl_build=$DST/build"
    echo "gin_ts2_md5=$(md5sum < "$DST/out/drv/gin_ts2" | cut -d' ' -f1) gin_ts2_cu_md5=$(md5sum < "$D/../gin_ts2.cu" | cut -d' ' -f1)"
    echo "gin_mr_md5=$(md5sum < "$DST/out/mr/gin_mr" | cut -d' ' -f1) gin_mr_cu_md5=$(md5sum < "$D/gin_mr.cu" | cut -d' ' -f1)"
    echo "hm_bench_md5=$(md5sum < "$DST/out/drv/hm_bench" | cut -d' ' -f1) hm_bench_cu_md5=$(md5sum < "$D/hm_bench.cu" | cut -d' ' -f1)"
    echo "libnccl_hr_md5=$(md5sum < "$DST/build/lib/libnccl.so.2.32.3" | cut -d' ' -f1)"
    echo "include_digest=$(cd "$inc" && find . -type f | LC_ALL=C sort | xargs md5sum | md5sum | cut -d' ' -f1)"
    echo "nvcc=$($CUDA/bin/nvcc --version | tail -1)"
  } > "$DST/out/build_info.txt"
  cat "$DST/out/build_info.txt"
}
ngt() {
  mkdir -p "$DST/out/ngt"
  nice -n 19 $CUDA/bin/nvcc -std=c++17 -O2 $GENCODE -Xcompiler "-Wall,-Wextra,-Werror" "$D/nic_gate_test.cu" \
    -o "$DST/out/ngt/nic_gate_test" -libverbs -lcuda
  {
    echo "built=$(date '+%F %T')"
    echo "nic_gate_test_md5=$(md5sum < "$DST/out/ngt/nic_gate_test" | cut -d' ' -f1) nic_gate_test_cu_md5=$(md5sum < "$D/nic_gate_test.cu" | cut -d' ' -f1)"
    echo "nvcc=$($CUDA/bin/nvcc --version | tail -1)"
  } > "$DST/out/ngt/build_info.txt"
  cat "$DST/out/ngt/build_info.txt"
}
case "$STAGE" in
  setup) setup ;;
  ngt) ngt ;;
  hr) hr ;;
  hrp) hrp ;;
  drivers) drivers ;;
  all) hr; hrp; drivers ;;
  *) echo "unknown stage $STAGE" >&2; exit 2 ;;
esac
