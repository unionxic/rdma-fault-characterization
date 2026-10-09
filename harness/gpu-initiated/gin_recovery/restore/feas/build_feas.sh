#!/usr/bin/env bash
# build_feas.sh - build gin-restore's feasibility tests (EXPERIMENT.md 9.15) on rain, in NEW scratch trees only. No GPU or
# RDMA program runs here; nothing outside agent_restore/ is written (the gpu-detect hw tree agent_gd/gin is read only).
# usage: build_feas.sh <b1-setup|b1-lib|app|b3|info|all>
#   b1-setup  check that agent_restore/b1/{nccl-src,build} is the copy of the hw tree (head commit "gpu-detect hw", its diff
#             against "gin-remaining hr" = hw_layer.diff md5 be0ea9ed, built libnccl md5 efc48ca1); the copy, the path
#             rewrite of the .d files and that commit were made once by hand (EXPERIMENT.md 12).
#   b1-lib    apply rs_spike.diff to that working tree unless it already carries it (the changed files must be exactly
#             RS_FILES), incremental make into agent_restore/b1/build -> agent_restore/out/$RSX/libnccl.so.2.32.3 (build key
#             $RSX, default rsx2: the second build after the pass-3 review; out/rsx holds the first, deployed build).
#             rs_spike.diff changes no device header: the include tree must stay equal to the hw one.
#   app       rs_spike.cu (B1 and B2 application) against the hw headers -> agent_restore/out/app/rs_spike (B2 runs on rsx
#             with only the report lines on: NCCL_GIN_RESTORE_REPORT=1)
#   b3        rs_drain_test.cu (no NCCL; libibverbs, libmlx5, libcuda) -> agent_restore/out/$B3OUT/rs_drain_test (B3OUT
#             default b3v2, the second build; out/b3 holds the first, deployed build)
#   info      agent_restore/out/build_info.txt: md5 of every output and input
# All compiles run at nice 19 and idle I/O priority. nvcc output is not byte-reproducible: a rerun changes the md5 of the
# executables; the deployed values are those recorded in EXPERIMENT.md 12.
set -euo pipefail
STAGE=${1:?stage}
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
D=$(cd "$(dirname "$0")" && pwd)
CUDA=/usr/local/cuda-12.8
GENCODE="-gencode=arch=compute_75,code=sm_75 -gencode=arch=compute_86,code=sm_86"
JOBS=${JOBS:-8}
RSX=${RSX:-rsx2}
W=$SCR/agent_restore
B1=$W/b1
OUT=$W/out
PRM=$SCR/agent_gd/gin/nccl-src/src/transport/net_ib/gdaki/doca-gpunetio/include/host
RS_FILES="src/bootstrap.cc src/dev_runtime.cc src/gin/gin_host.cc src/include/rs_spike.h src/init.cc src/misc/rs_spike.cc src/transport/net_ib/gdaki/gin_host_gdaki.cc src/transport/net_ib/gin.cc"
mkdir -p "$OUT"
GG() { git -C "$B1/nccl-src" -c user.name=build -c user.email=build@localhost "$@"; }
md5() { md5sum < "$1" | cut -c1-32; }
MK() {  # MK <builddir> [make args]
  local b=$1; shift
  nice -n 19 ionice -c3 make -j"$JOBS" -C "$B1/nccl-src" src.build BUILDDIR="$b" CUDA_HOME=$CUDA NVCC_GENCODE="$GENCODE" "$@"
}
b1_setup() {
  [ -d "$B1/nccl-src" ] && [ -d "$B1/build" ] || { echo "agent_restore/b1 is not set up (copy of agent_gd/gin)" >&2; exit 1; }
  case "$(GG log -1 --format=%s)" in "gpu-detect hw"*) ;; *) echo "agent_restore/b1 head is not the hw commit" >&2; exit 1 ;; esac
  [ "$(GG diff HEAD~1 HEAD -- src | md5sum | cut -c1-8)" = be0ea9ed ] || { echo "the hw commit is not hw_layer.diff be0ea9ed" >&2; exit 1; }
  echo "b1-setup: agent_restore/b1 at $(GG rev-parse --short HEAD) ($(GG log -1 --format=%s))"
}
b1_tree() {
  b1_setup
  if GG diff --quiet HEAD -- src; then GG apply --index "$D/rs_spike.diff"; fi
  local got want
  got=$(GG diff --name-only HEAD -- src | sort | tr '\n' ' ')
  want=$(echo $RS_FILES | tr ' ' '\n' | sort | tr '\n' ' ')
  [ "$got" = "$want" ] || { echo "the working tree changes other files than RS_FILES: $got" >&2; exit 1; }
  [ "$(GG diff HEAD -- src | md5sum | cut -c1-32)" = "$(md5sum < "$D/rs_spike.diff" | cut -c1-32)" ] ||
    { echo "the working tree is not rs_spike.diff" >&2; exit 1; }
}
b1_lib() {
  b1_tree
  MK "$B1/build"
  mkdir -p "$OUT/$RSX"; cp "$B1/build/lib/libnccl.so.2.32.3" "$OUT/$RSX/"
  diff -r -q "$B1/build/include/nccl_device" "$SCR/agent_gd/gin/build/include/nccl_device" > /dev/null ||
    { echo "the rsx device headers differ from hw" >&2; exit 1; }
  echo "$RSX libnccl $(md5 "$OUT/$RSX/libnccl.so.2.32.3")"
}
app() {
  local o=$OUT/app inc=$SCR/agent_gd/gin/build/include
  mkdir -p "$o"
  nice -n 19 "$CUDA/bin/nvcc" -std=c++17 -O2 --expt-relaxed-constexpr --expt-extended-lambda $GENCODE -isystem "$inc" \
    -Xcompiler "-Wall,-Wextra" "$D/rs_spike.cu" -o "$o/rs_spike" -L"$SCR/agent_gd/gin/build/lib" -lnccl -lcudart -lpthread
  echo "rs_spike $(md5 "$o/rs_spike")"
}
b3() {  # B3OUT (b3v2): the output folder; out/b3 holds the first, deployed build
  local o=$OUT/${B3OUT:-b3v2}
  mkdir -p "$o"
  # the mlx5 PRM layouts: the DOCA GPUNetIO copy inside the hw tree (read only)
  nice -n 19 "$CUDA/bin/nvcc" -std=c++17 -O2 $GENCODE -Xcompiler "-Wall,-Wextra,-Werror" -I"$PRM" "$D/rs_drain_test.cu" \
    -o "$o/rs_drain_test" -libverbs -lmlx5 -lcuda
  echo "rs_drain_test.cu $(md5 "$D/rs_drain_test.cu") built $(date '+%F %T')" > "$o/build_src.txt"  # the source at compile time
  echo "rs_drain_test $(md5 "$o/rs_drain_test")"
}
info() {
  {
    echo "built=$(date '+%F %T') host=$(hostname -s) nvcc=$("$CUDA/bin/nvcc" --version | tail -1)"
    [ -f "$OUT/rsx/libnccl.so.2.32.3" ] && echo "rsx (first build, deployed 2026-10-09) libnccl $(md5 "$OUT/rsx/libnccl.so.2.32.3")"
    [ -f "$OUT/$RSX/libnccl.so.2.32.3" ] && echo "$RSX libnccl $(md5 "$OUT/$RSX/libnccl.so.2.32.3") rs_spike.diff $(md5 "$D/rs_spike.diff") base $(GG rev-parse --short HEAD) include_digest $(cd "$B1/build/include" && find . -type f | LC_ALL=C sort | xargs md5sum | md5sum | cut -c1-32)"
    echo "hw include_digest $(cd "$SCR/agent_gd/gin/build/include" && find . -type f | LC_ALL=C sort | xargs md5sum | md5sum | cut -c1-32) (the app is built against these headers)"
    [ -f "$OUT/app/rs_spike" ] && echo "rs_spike $(md5 "$OUT/app/rs_spike") rs_spike.cu $(md5 "$D/rs_spike.cu") sass $("$CUDA/bin/cuobjdump" --list-elf "$OUT/app/rs_spike" 2>/dev/null | grep -o 'sm_[0-9]*' | sort -u | tr '\n' ' ')"
    [ -f "$OUT/b3/rs_drain_test" ] && echo "rs_drain_test (first build, deployed 2026-10-09) $(md5 "$OUT/b3/rs_drain_test")"
    for k in b3v2 b3v3 ${B3OUT:-}; do
      [ -f "$OUT/$k/rs_drain_test" ] && echo "rs_drain_test $k $(md5 "$OUT/$k/rs_drain_test") source at compile: $(cat "$OUT/$k/build_src.txt" 2>/dev/null || echo "not recorded (built before build_src.txt); source now $(md5 "$D/rs_drain_test.cu")")"
    done | sort -u
  } > "$OUT/build_info.txt"
  cat "$OUT/build_info.txt"
}
case "$STAGE" in
  b1-setup) b1_setup ;;
  b1-lib) b1_lib ;;
  app) app ;;
  b3) b3 ;;
  info) info ;;
  all) b1_lib; app; b3; info ;;
  *) echo "unknown stage $STAGE" >&2; exit 2 ;;
esac
