#!/usr/bin/env bash
# build_345_ahinit.sh - NVSHMEM v3.4.5-0 with one initialization line added (patches/
# v3.4.5-0_dct_ah_attr_init.diff: zero the address-handle attributes of the shared DCT, as 3.8.0
# does). Unmodified 3.4.5 could not start with the cpu_host_memory handler on sunny ("Unable to
# create ah", DEVIATIONS 4). Only nvshmem_transport_ibgda.so changes; the bundle gets lib_ahinit =
# lib_stock with that plugin replaced, on rain and sunny. Run build_345.sh first.
#
#   W=<work dir with v3.4.5-0.tar.gz> bash build_345_ahinit.sh
set -eu
W=${W:?work dir}
CUDA=/usr/local/cuda-12.8
HERE=$(cd "$(dirname "$0")" && pwd)
B=$HOME/gi-bundle/nvshmem_345
SRC=$W/ahinit/nvshmem-3.4.5-0

rm -rf "$W/ahinit" && mkdir -p "$W/ahinit"
tar xzf "$W/v3.4.5-0.tar.gz" -C "$W/ahinit"
patch -d "$SRC" -p1 < "$HERE/patches/v3.4.5-0_dct_ah_attr_init.diff"
cmake -S "$SRC" -B "$W/build_ahinit" -DCMAKE_BUILD_TYPE=release -DCMAKE_CUDA_ARCHITECTURES="75;86" \
  -DCUDA_HOME=$CUDA -DCMAKE_CUDA_COMPILER=$CUDA/bin/nvcc \
  -DNVSHMEM_IBGDA_SUPPORT=ON -DNVSHMEM_IBRC_SUPPORT=ON -DNVSHMEM_USE_GDRCOPY=OFF \
  -DNVSHMEM_MPI_SUPPORT=OFF -DNVSHMEM_SHMEM_SUPPORT=OFF -DNVSHMEM_UCX_SUPPORT=OFF \
  -DNVSHMEM_PMIX_SUPPORT=OFF -DNVSHMEM_LIBFABRIC_SUPPORT=OFF -DNVSHMEM_USE_NCCL=OFF \
  -DNVSHMEM_BUILD_TESTS=OFF -DNVSHMEM_BUILD_EXAMPLES=OFF -DNVSHMEM_BUILD_PYTHON_LIB=OFF \
  -DNVSHMEM_BUILD_BITCODE_LIBRARY=OFF -DNVSHMEM_BUILD_LTOIR_LIBRARY=OFF \
  -DNVSHMEM_BUILD_HYDRA_LAUNCHER=OFF -DNVSHMEM_BUILD_TXZ_PACKAGE=OFF > "$W/build_ahinit.cmake.log"
make -C "$W/build_ahinit" -j16 nvshmem_transport_ibgda > "$W/build_ahinit.make.log"

so=$(find "$W/build_ahinit" -name 'nvshmem_transport_ibgda.so.3.*' -type f | head -1)
rm -rf "$B/lib_ahinit" && cp -a "$B/lib_stock" "$B/lib_ahinit"
cp "$so" "$B/lib_ahinit/$(basename "$so")"
md5sum "$B"/lib_stock/nvshmem_transport_ibgda.so.3.* "$B"/lib_ahinit/nvshmem_transport_ibgda.so.3.*
ssh -n sunny "rm -rf gi-bundle/nvshmem_345/lib_ahinit"
scp -rq "$B/lib_ahinit" sunny:gi-bundle/nvshmem_345/
ssh -n sunny "md5sum gi-bundle/nvshmem_345/lib_ahinit/nvshmem_transport_ibgda.so.3.*"
