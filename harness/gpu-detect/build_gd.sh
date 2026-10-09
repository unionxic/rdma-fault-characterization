#!/usr/bin/env bash
# build_gd.sh - build gpu-detect's two library layers and the two unmodified examples on rain, in NEW scratch trees
# (every earlier tree, bundle and worktree stays untouched). No GPU or RDMA program runs here.
# usage: build_gd.sh <gin-setup|gin-hw|gin-hwp|gin-app|nvs-setup|nvs-lib|nvs-app|info|all>
#
# GIN (layer hw on gin-remaining's hr):
#   gin-setup  once: copy agent_ts2hr/{nccl-src,build,build-hrp} -> agent_gd/gin/{nccl-src,build,build-hwp}; rewrite the
#              absolute paths in the dependency files and device manifests, keeping their mtimes, so that make rebuilds
#              only what changed; commit agent_ts2hr's working tree (= ../gpu-initiated/gin_recovery/remaining/
#              hr_layer.diff, md5 66f61272, on the "gin-peer hq" commit) in the copied scratch repository as
#              "gin-remaining hr (libnccl 2dee2b5b)".
#   gin-hw     apply hw_layer.diff unless the working tree already carries it (the changed files must be exactly
#              GIN_FILES); incremental make into build/; libnccl -> agent_gd/out/hw/.
#   gin-hwp    the production build of the same source: incremental make into build-hwp/ with
#              CXXFLAGS=-DNCCL_GIN_TS_PRODUCTION; libnccl -> agent_gd/out/hwp/ (built only; not deployed).
#   gin-app    NCCL 2.32.3 example 09_gin_optimizations/01_ring_exchange (main.cu, kernels.cuh unchanged) against the hw
#              headers, linked with ../blind/boot/gin_boot.cc (as ../blind/build_blind.sh gin) -> agent_gd/out/gin/gd_gin_ring.
#              The hw layer changes no device header, so this binary also serves the hr control.
# NVSHMEM (layer t1w on the t1_380 port):
#   nvs-setup  once: copy agent_t1_380/src -> agent_gd/nvs/src; commit its working tree (= the t1_380 port,
#              ../gpu-initiated/nvshmem_ft/t1_380/nvshmem_ibgda_t1_380.diff on "base: v3.8.0-0 + inject + nrc") as
#              "t1_380 (transport d6ae3699)"; cmake with the options of ../gpu-initiated/nvshmem_ft/t1_380/build.sh into
#              agent_gd/nvs/build, install prefix agent_gd/nvs/install.
#   nvs-lib    apply t1w_layer.diff unless the working tree already carries it (exactly NVS_FILES); make, install.
#   nvs-app    NVSHMEM 3.8.0 example examples/ring-reduce.cu (unchanged) against the t1w install -> agent_gd/out/nvs/gd_nvs_rr,
#              and ../blind/boot/nvs_boot.cc as a bootstrap plugin -> agent_gd/out/nvs/gd_nvs_boot.so (as build_blind.sh nvs).
#              The device code of the waits is compiled into the application, so the example must be rebuilt (not changed).
#   info       agent_gd/out/build_info.txt: md5 of every output and of the inputs.
# All compiles run at nice 19 and idle I/O priority (other studies use this node). nvcc output is not byte-reproducible:
# a rerun changes the md5 of the executables; the deployed values are those in EXPERIMENT.md 12.
set -euo pipefail
STAGE=${1:?stage}
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
D=$(cd "$(dirname "$0")" && pwd)
G=$D/../gpu-initiated
CUDA=/usr/local/cuda-12.8
GENCODE="-gencode=arch=compute_75,code=sm_75 -gencode=arch=compute_86,code=sm_86"
JOBS=${JOBS:-8}
W=$SCR/agent_gd
OUT=$W/out
HR=$SCR/agent_ts2hr
T1=$SCR/agent_t1_380
EX=$SCR/agent_nb/nccl-232/docs/examples
GIN_FILES="src/transport/net_ib/gdaki/gin_host_gdaki.cc"
NVS_FILES="src/include/device_host_transport/nvshmem_common_ibgda.h src/include/non_abi/device/wait/nvshmemi_wait_until_apis.cuh src/modules/transport/ibgda/ibgda.cpp"
mkdir -p "$OUT"
GG() { git -C "$W/gin/nccl-src" -c user.name=build -c user.email=build@localhost "$@"; }
NG() { git -C "$W/nvs/src" -c user.name=build -c user.email=build@localhost "$@"; }
MK() {  # MK <builddir> [make args]
  local b=$1; shift
  nice -n 19 ionice -c3 make -j"$JOBS" -C "$W/gin/nccl-src" src.build BUILDDIR="$b" CUDA_HOME=$CUDA NVCC_GENCODE="$GENCODE" "$@"
}
rewrite() {  # rewrite <from prefix> <to prefix> <dir>: absolute paths in *.d and manifests, mtimes kept
  local from=$1 to=$2 dir=$3
  (cd "$dir" && find . \( -name '*.d' -o -name manifest \) -print0 |
     while IFS= read -r -d '' f; do
       local t; t=$(mktemp); touch -r "$f" "$t"
       sed -i "s#$from#$to#g" "$f"; touch -h -r "$t" "$f"; rm -f "$t"
     done)
}
md5() { md5sum < "$1" | cut -c1-32; }

gin_setup() {
  [ -d "$W/gin/nccl-src" ] && return 0
  case "$(git -C "$HR/nccl-src" log -1 --format=%s)" in "gin-peer hq"*) ;; *) echo "agent_ts2hr head is not the hq commit" >&2; exit 1 ;; esac
  [ "$(git -C "$HR/nccl-src" diff HEAD -- src | md5sum | cut -c1-8)" = 66f61272 ] || { echo "agent_ts2hr working tree is not hr_layer.diff" >&2; exit 1; }
  [ "$(md5 "$HR/build/lib/libnccl.so.2.32.3")" = 2dee2b5bf36b3477dd85f0197987f028 ] || { echo "agent_ts2hr build is not hr" >&2; exit 1; }
  [ "$(md5 "$HR/build-hrp/lib/libnccl.so.2.32.3")" = 786f70bcb82ea21cb678dcb056256ed5 ] || { echo "agent_ts2hr build-hrp is not hrp" >&2; exit 1; }
  mkdir -p "$W/gin"
  cp -a "$HR/nccl-src" "$HR/build" "$W/gin/"
  cp -a "$HR/build-hrp" "$W/gin/build-hwp"
  rm -rf "$W/gin/nccl-src/.git/worktrees"
  rewrite "$HR/build-hrp/" "$W/gin/build-hwp/" "$W/gin/build-hwp"
  rewrite "$HR/" "$W/gin/" "$W/gin/build-hwp"
  rewrite "$HR/" "$W/gin/" "$W/gin/build"
  GG add -A src
  GG commit -qm "gin-remaining hr (libnccl 2dee2b5b)"
  [ "$(GG diff HEAD~1 HEAD -- src | md5sum | cut -c1-8)" = 66f61272 ] || { echo "the hr commit is not hr_layer.diff" >&2; exit 1; }
  echo "gin-setup: agent_gd/gin at $(GG rev-parse --short HEAD) ($(GG log -1 --format=%s))"
  echo "gin-setup: make -n in build/ after the copy: $(MK "$W/gin/build" -n 2>/dev/null | grep -c -- ' -c ' || true) compile commands"
}
gin_tree() {  # the hw layer on the working tree
  case "$(GG log -1 --format=%s)" in "gin-remaining hr"*) ;; *) echo "unexpected head commit in agent_gd/gin" >&2; exit 1 ;; esac
  if GG diff --quiet HEAD -- src; then GG apply "$D/hw_layer.diff"; fi
  [ "$(GG diff --name-only HEAD -- src | sort | tr '\n' ' ')" = "$(echo $GIN_FILES | tr ' ' '\n' | sort | tr '\n' ' ')" ] ||
    { echo "the working tree changes other files than $GIN_FILES" >&2; exit 1; }
}
gin_hw() {
  gin_setup; gin_tree
  MK "$W/gin/build"
  mkdir -p "$OUT/hw"; cp "$W/gin/build/lib/libnccl.so.2.32.3" "$OUT/hw/"
  echo "hw libnccl $(md5 "$OUT/hw/libnccl.so.2.32.3")"
}
gin_hwp() {
  gin_setup; gin_tree
  CXXFLAGS=-DNCCL_GIN_TS_PRODUCTION MK "$W/gin/build-hwp"
  mkdir -p "$OUT/hwp"; cp "$W/gin/build-hwp/lib/libnccl.so.2.32.3" "$OUT/hwp/"
  diff -r -q "$W/gin/build/include/nccl_device" "$W/gin/build-hwp/include/nccl_device" > /dev/null ||
    { echo "the hwp device headers differ from hw" >&2; exit 1; }
  echo "hwp libnccl $(md5 "$OUT/hwp/libnccl.so.2.32.3")"
}
gin_app() {
  local src=$EX/09_gin_optimizations/01_ring_exchange/c o=$OUT/gin inc=$W/gin/build/include
  mkdir -p "$o"
  nice -n 19 "$CUDA/bin/nvcc" -std=c++17 -O2 --expt-relaxed-constexpr --expt-extended-lambda $GENCODE \
    -isystem "$inc" -I"$EX/common/include" -c "$src/main.cu" -o "$o/main.o"
  nice -n 19 g++ -std=c++17 -O2 -Wall -Wextra -I"$CUDA/include" -isystem "$inc" -I"$EX/common/include" -I"$D/../blind/boot" \
    -c "$D/../blind/boot/gin_boot.cc" -o "$o/gin_boot.o"
  nice -n 19 "$CUDA/bin/nvcc" $GENCODE "$o/main.o" "$o/gin_boot.o" -o "$o/gd_gin_ring" -L"$W/gin/build/lib" -lnccl -lcudart -lpthread
  echo "gd_gin_ring $(md5 "$o/gd_gin_ring")"
}
nvs_setup() {
  [ -d "$W/nvs/src" ] && return 0
  case "$(git -C "$T1/src" log -1 --format=%s)" in "base: v3.8.0-0 + inject + nrc"*) ;; *) echo "agent_t1_380 head is not the base commit" >&2; exit 1 ;; esac
  [ "$(md5 "$T1/install/lib/nvshmem_transport_ibgda.so.7.0.0")" = d6ae3699f95bfeaf0f36af6ebba95b7e ] || { echo "agent_t1_380 install is not t1_380" >&2; exit 1; }
  mkdir -p "$W/nvs"
  cp -a "$T1/src" "$W/nvs/src"
  rm -rf "$W/nvs/src/.git/worktrees"
  NG add -A src nvshmem_transport.sym
  NG commit -qm "t1_380 (transport d6ae3699)"
  echo "nvs-setup: agent_gd/nvs/src at $(NG rev-parse --short HEAD) ($(NG log -1 --format=%s)); files in the commit: $(NG diff --name-only HEAD~1 HEAD | wc -l)"
  cmake -S "$W/nvs/src" -B "$W/nvs/build" -DCMAKE_BUILD_TYPE=release -DCMAKE_CUDA_ARCHITECTURES="75;86" \
    -DCUDA_HOME=$CUDA -DCMAKE_CUDA_COMPILER=$CUDA/bin/nvcc \
    -DNVSHMEM_IBGDA_SUPPORT=ON -DNVSHMEM_IBRC_SUPPORT=ON -DNVSHMEM_USE_GDRCOPY=ON \
    -DNVSHMEM_MPI_SUPPORT=OFF -DNVSHMEM_SHMEM_SUPPORT=OFF -DNVSHMEM_UCX_SUPPORT=OFF \
    -DNVSHMEM_PMIX_SUPPORT=OFF -DNVSHMEM_LIBFABRIC_SUPPORT=OFF -DNVSHMEM_USE_NCCL=OFF \
    -DNVSHMEM_BUILD_TESTS=OFF -DNVSHMEM_BUILD_EXAMPLES=OFF -DNVSHMEM_BUILD_PYTHON_LIB=OFF \
    -DNVSHMEM_BUILD_BITCODE_LIBRARY=OFF -DNVSHMEM_BUILD_LTOIR_LIBRARY=OFF \
    -DNVSHMEM_BUILD_HYDRA_LAUNCHER=OFF -DNVSHMEM_BUILD_TXZ_PACKAGE=OFF \
    -DCMAKE_INSTALL_PREFIX="$W/nvs/install" > "$W/nvs/cmake.log" 2>&1
}
nvs_lib() {
  nvs_setup
  case "$(NG log -1 --format=%s)" in "t1_380 "*) ;; *) echo "unexpected head commit in agent_gd/nvs/src" >&2; exit 1 ;; esac
  if NG diff --quiet HEAD -- src; then NG apply "$D/t1w_layer.diff"; fi
  [ "$(NG diff --name-only HEAD -- src | sort | tr '\n' ' ')" = "$(echo $NVS_FILES | tr ' ' '\n' | sort | tr '\n' ' ')" ] ||
    { echo "the working tree changes other files than $NVS_FILES" >&2; exit 1; }
  ( time nice -n 19 ionice -c3 make -C "$W/nvs/build" -j"${NVS_JOBS:-16}" > "$W/nvs/build_lib.log" 2>&1 ) 2> "$W/nvs/build_lib.time"
  nice -n 19 make -C "$W/nvs/build" install > "$W/nvs/install.log" 2>&1
  echo "t1w transport $(md5 "$W/nvs/install/lib/nvshmem_transport_ibgda.so.7.0.0") host $(md5 "$W/nvs/install/lib/libnvshmem_host.so.3.8.0")"
}
nvs_app() {
  local o=$OUT/nvs inst=$W/nvs/install
  mkdir -p "$o"
  nice -n 19 g++ -std=c++17 -O2 -fPIC -shared -Wall -Wextra -I"$W/nvs/src/src/include" -I"$D/../blind/boot" \
    "$D/../blind/boot/nvs_boot.cc" -o "$o/gd_nvs_boot.so" -ldl
  nice -n 19 "$CUDA/bin/nvcc" -std=c++17 -O2 -rdc=true -ccbin g++ $GENCODE -I"$inst/include" \
    "$W/nvs/src/examples/ring-reduce.cu" -o "$o/gd_nvs_rr" \
    -L"$inst/lib" -lnvshmem_host -lnvshmem_device -L"$CUDA/lib64" -lcudart -lcuda -ldl -lpthread
  echo "gd_nvs_rr $(md5 "$o/gd_nvs_rr") gd_nvs_boot.so $(md5 "$o/gd_nvs_boot.so")"
}
info() {
  {
    echo "built=$(date '+%F %T') host=$(hostname -s) nvcc=$("$CUDA/bin/nvcc" --version | tail -1)"
    [ -f "$OUT/hw/libnccl.so.2.32.3" ] && echo "gin: hw libnccl $(md5 "$OUT/hw/libnccl.so.2.32.3") include_digest $(cd "$W/gin/build/include" && find . -type f | LC_ALL=C sort | xargs md5sum | md5sum | cut -c1-32)"
    [ -f "$OUT/hwp/libnccl.so.2.32.3" ] && echo "gin: hwp libnccl $(md5 "$OUT/hwp/libnccl.so.2.32.3")"
    echo "gin: hr include_digest $(cd "$HR/build/include" && find . -type f | LC_ALL=C sort | xargs md5sum | md5sum | cut -c1-32) (hw changes no header: equal is expected)"
    [ -f "$OUT/gin/gd_gin_ring" ] && {
      echo "gin: gd_gin_ring $(md5 "$OUT/gin/gd_gin_ring") main.cu $(md5 "$EX/09_gin_optimizations/01_ring_exchange/c/main.cu") kernels.cuh $(md5 "$EX/09_gin_optimizations/01_ring_exchange/c/kernels.cuh") gin_boot.cc $(md5 "$D/../blind/boot/gin_boot.cc") rdv.h $(md5 "$D/../blind/boot/rdv.h")"
      echo "gin: gd_gin_ring sass $("$CUDA/bin/cuobjdump" --list-elf "$OUT/gin/gd_gin_ring" 2>/dev/null | grep -o 'sm_[0-9]*' | sort -u | tr '\n' ' ')"
    }
    [ -f "$W/nvs/install/lib/nvshmem_transport_ibgda.so.7.0.0" ] && {
      echo "nvs: t1w transport $(md5 "$W/nvs/install/lib/nvshmem_transport_ibgda.so.7.0.0") host $(md5 "$W/nvs/install/lib/libnvshmem_host.so.3.8.0") uid $(md5 "$W/nvs/install/lib/nvshmem_bootstrap_uid.so.3.0.0") device_a $(md5 "$W/nvs/install/lib/libnvshmem_device.a")"
    }
    [ -f "$OUT/nvs/gd_nvs_rr" ] && {
      echo "nvs: gd_nvs_rr $(md5 "$OUT/nvs/gd_nvs_rr") gd_nvs_boot.so $(md5 "$OUT/nvs/gd_nvs_boot.so") ring-reduce.cu $(md5 "$W/nvs/src/examples/ring-reduce.cu") nvs_boot.cc $(md5 "$D/../blind/boot/nvs_boot.cc")"
      echo "nvs: gd_nvs_rr sass $("$CUDA/bin/cuobjdump" --list-elf "$OUT/nvs/gd_nvs_rr" 2>/dev/null | grep -o 'sm_[0-9]*' | sort -u | tr '\n' ' ')"
    }
    [ -f "$D/hw_layer.diff" ] && echo "hw_layer.diff $(md5 "$D/hw_layer.diff")"
    [ -f "$D/t1w_layer.diff" ] && echo "t1w_layer.diff $(md5 "$D/t1w_layer.diff")"
  } > "$OUT/build_info.txt"
  cat "$OUT/build_info.txt"
}
case "$STAGE" in
  gin-setup) gin_setup ;;
  gin-hw) gin_hw ;;
  gin-hwp) gin_hwp ;;
  gin-app) gin_app ;;
  nvs-setup) nvs_setup ;;
  nvs-lib) nvs_lib ;;
  nvs-app) nvs_app ;;
  info) info ;;
  all) gin_hw; gin_hwp; gin_app; nvs_lib; nvs_app; info ;;
  *) echo "unknown stage $STAGE" >&2; exit 2 ;;
esac
