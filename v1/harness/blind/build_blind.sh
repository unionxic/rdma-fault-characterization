#!/usr/bin/env bash
# build_blind.sh [gin|nvs|all] - build the two native workloads of blind-apps on rain (no GPU or RDMA program runs).
#
#   gin  NCCL 2.32.3 official example docs/examples/09_gin_optimizations/01_ring_exchange (main.cu, kernels.cuh
#        unchanged) against the gin-peer research build `hq` (headers $SCR/agent_ts2hq/build/include, libnccl md5
#        c1311625), linked with boot/gin_boot.cc in place of the examples' common/src/utils.cc (whose multi-node path
#        needs MPI). Output: $OUT/gin/blind_gin_ring.
#   nvs  NVSHMEM 3.8.0 official example examples/ring-reduce.cu (unchanged) against the t1_380 install
#        ($SCR/agent_t1_380/install), and boot/nvs_boot.cc as an NVSHMEM bootstrap plugin (NVSHMEM_BOOTSTRAP=plugin).
#        Output: $OUT/nvs/blind_nvs_rr, $OUT/nvs/blind_nvs_boot.so.
#   Both: sm_75 (rain, Quadro RTX 5000) and sm_86 (sunny, RTX A4000), CUDA 12.8, nice 19. $OUT/build_info.txt has the
#   md5 of every output and input.
set -euo pipefail
D=$(cd "$(dirname "$0")" && pwd)
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
CUDA=/usr/local/cuda-12.8
GENCODE="-gencode=arch=compute_75,code=sm_75 -gencode=arch=compute_86,code=sm_86"
OUT=${BLIND_BUILD_OUT:-$SCR/agent_blind/out}
EX=$SCR/agent_nb/nccl-232/docs/examples
HQ=$SCR/agent_ts2hq/build
NVS_SRC=$SCR/agent_t1_380/src
NVS_INST=$SCR/agent_t1_380/install
what=${1:-all}
mkdir -p "$OUT/gin" "$OUT/nvs"

gin() {
  local src=$EX/09_gin_optimizations/01_ring_exchange/c o=$OUT/gin
  [ "$(md5sum < "$HQ/lib/libnccl.so.2.32.3" | cut -c1-32)" = c1311625c7a06c785bc313558504f982 ] ||
    { echo "the hq libnccl is not c1311625" >&2; exit 1; }
  nice -n 19 "$CUDA/bin/nvcc" -std=c++17 -O2 --expt-relaxed-constexpr --expt-extended-lambda $GENCODE \
    -isystem "$HQ/include" -I"$EX/common/include" -c "$src/main.cu" -o "$o/main.o"
  nice -n 19 g++ -std=c++17 -O2 -Wall -Wextra -I"$CUDA/include" -isystem "$HQ/include" -I"$EX/common/include" -I"$D/boot" \
    -c "$D/boot/gin_boot.cc" -o "$o/gin_boot.o"
  nice -n 19 "$CUDA/bin/nvcc" $GENCODE "$o/main.o" "$o/gin_boot.o" -o "$o/blind_gin_ring" \
    -L"$HQ/lib" -lnccl -lcudart -lpthread
}

nvs() {
  local o=$OUT/nvs
  nice -n 19 g++ -std=c++17 -O2 -fPIC -shared -Wall -Wextra -I"$NVS_SRC/src/include" -I"$D/boot" \
    "$D/boot/nvs_boot.cc" -o "$o/blind_nvs_boot.so" -ldl
  nice -n 19 "$CUDA/bin/nvcc" -std=c++17 -O2 -rdc=true -ccbin g++ $GENCODE -I"$NVS_INST/include" \
    "$NVS_SRC/examples/ring-reduce.cu" -o "$o/blind_nvs_rr" \
    -L"$NVS_INST/lib" -lnvshmem_host -lnvshmem_device -L"$CUDA/lib64" -lcudart -lcuda -ldl -lpthread
}

info() {
  {
    echo "built=$(date '+%F %T') host=$(hostname -s) nvcc=$("$CUDA/bin/nvcc" --version | tail -1)"
    [ -f "$OUT/gin/blind_gin_ring" ] && {
      echo "gin: blind_gin_ring $(md5sum < "$OUT/gin/blind_gin_ring" | cut -c1-32)"
      echo "gin: main.cu $(md5sum < "$EX/09_gin_optimizations/01_ring_exchange/c/main.cu" | cut -c1-32) kernels.cuh $(md5sum < "$EX/09_gin_optimizations/01_ring_exchange/c/kernels.cuh" | cut -c1-32) utils.h $(md5sum < "$EX/common/include/utils.h" | cut -c1-32)"
      echo "gin: gin_boot.cc $(md5sum < "$D/boot/gin_boot.cc" | cut -c1-32) rdv.h $(md5sum < "$D/boot/rdv.h" | cut -c1-32)"
      echo "gin: hq libnccl $(md5sum < "$HQ/lib/libnccl.so.2.32.3" | cut -c1-32) include_digest $(cd "$HQ/include" && find . -type f | LC_ALL=C sort | xargs md5sum | md5sum | cut -c1-32)"
      echo "gin: sass $("$CUDA/bin/cuobjdump" --list-elf "$OUT/gin/blind_gin_ring" 2>/dev/null | grep -o 'sm_[0-9]*' | sort -u | tr '\n' ' ')"
    }
    [ -f "$OUT/nvs/blind_nvs_rr" ] && {
      echo "nvs: blind_nvs_rr $(md5sum < "$OUT/nvs/blind_nvs_rr" | cut -c1-32) blind_nvs_boot.so $(md5sum < "$OUT/nvs/blind_nvs_boot.so" | cut -c1-32)"
      echo "nvs: ring-reduce.cu $(md5sum < "$NVS_SRC/examples/ring-reduce.cu" | cut -c1-32) nvs_boot.cc $(md5sum < "$D/boot/nvs_boot.cc" | cut -c1-32)"
      echo "nvs: install transport $(md5sum < "$NVS_INST/lib/nvshmem_transport_ibgda.so.7.0.0" | cut -c1-32) host $(md5sum < "$NVS_INST/lib/libnvshmem_host.so.3.8.0" | cut -c1-32) uid $(md5sum < "$NVS_INST/lib/nvshmem_bootstrap_uid.so.3.0.0" | cut -c1-32)"
      echo "nvs: sass $("$CUDA/bin/cuobjdump" --list-elf "$OUT/nvs/blind_nvs_rr" 2>/dev/null | grep -o 'sm_[0-9]*' | sort -u | tr '\n' ' ')"
      echo "nvs: plugin exports $(nm -D --defined-only "$OUT/nvs/blind_nvs_boot.so" | awk '{print $3}' | grep nvshmemi_bootstrap | tr '\n' ' ')"
    }
  } > "$OUT/build_info.txt"
  cat "$OUT/build_info.txt"
}

case "$what" in
  gin) gin; info ;;
  nvs) nvs; info ;;
  all) gin; nvs; info ;;
  info) info ;;
  *) echo "usage: $0 [gin|nvs|all|info]" >&2; exit 2 ;;
esac
