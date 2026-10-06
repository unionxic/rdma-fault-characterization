#!/usr/bin/env bash
# build.sh - unmodified NVSHMEM v3.8.0-0 (+ a second ibgda plugin with only the fix), the
# reproducer, and the bundle in ~/gi-bundle/nvshmem_off380 on rain and sunny.
#
#   W=<work dir> bash build.sh
#
# Source: https://github.com/NVIDIA/nvshmem/archive/refs/tags/v3.8.0-0.tar.gz
# (sha256 38d3abb2969739816b2dcd5e0ae337ba036911f922f7caca0780caa517d37b1d, tag 270759e5).
set -eu
W=${W:?work dir}
CUDA=/usr/local/cuda-12.8
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=$W/nvshmem-3.8.0-0
B=$HOME/gi-bundle/nvshmem_off380

[ -d "$SRC" ] || (cd "$W" && curl -sSL https://github.com/NVIDIA/nvshmem/archive/refs/tags/v3.8.0-0.tar.gz | tar xz)
cmake -S "$SRC" -B "$W/build" -DCMAKE_BUILD_TYPE=release -DCMAKE_CUDA_ARCHITECTURES="75;86" \
  -DCUDA_HOME=$CUDA -DCMAKE_CUDA_COMPILER=$CUDA/bin/nvcc \
  -DNVSHMEM_IBGDA_SUPPORT=ON -DNVSHMEM_IBRC_SUPPORT=ON -DNVSHMEM_USE_GDRCOPY=ON \
  -DNVSHMEM_MPI_SUPPORT=OFF -DNVSHMEM_SHMEM_SUPPORT=OFF -DNVSHMEM_UCX_SUPPORT=OFF \
  -DNVSHMEM_PMIX_SUPPORT=OFF -DNVSHMEM_LIBFABRIC_SUPPORT=OFF -DNVSHMEM_USE_NCCL=OFF \
  -DNVSHMEM_BUILD_TESTS=OFF -DNVSHMEM_BUILD_EXAMPLES=OFF -DNVSHMEM_BUILD_PYTHON_LIB=OFF \
  -DNVSHMEM_BUILD_BITCODE_LIBRARY=OFF -DNVSHMEM_BUILD_LTOIR_LIBRARY=OFF \
  -DNVSHMEM_BUILD_HYDRA_LAUNCHER=OFF -DNVSHMEM_BUILD_TXZ_PACKAGE=OFF \
  -DCMAKE_INSTALL_PREFIX="$W/install"
make -C "$W/build" -j16
make -C "$W/build" install

# Bundle: lib_stock = the install; lib_fix = the same files with the ibgda plugin rebuilt from
# the source with only fix.diff applied. The source is restored afterwards.
rm -rf "$B" && mkdir -p "$B/bin"
cp -a "$W/install/lib" "$B/lib_stock"
cp -a "$W/install/lib" "$B/lib_fix"
patch -d "$SRC" -p1 <"$HERE/fix.diff"
make -C "$W/build" nvshmem_transport_ibgda
plugin=$(readlink -f "$W/build/src/lib/nvshmem_transport_ibgda.so")
cp "$plugin" "$B/lib_fix/$(basename "$(readlink -f "$B/lib_fix/nvshmem_transport_ibgda.so")")"
patch -d "$SRC" -p1 -R <"$HERE/fix.diff"
make -C "$W/build" nvshmem_transport_ibgda

$CUDA/bin/nvcc -std=c++17 -rdc=true -gencode=arch=compute_75,code=sm_75 -gencode=arch=compute_86,code=sm_86 \
  -Xcompiler -Wall,-Wextra -I"$W/install/include" "$HERE/kill_repro.cu" -o "$B/bin/nvs_kill_repro" \
  -L"$W/install/lib" -lnvshmem_host -lnvshmem_device -L$CUDA/lib64 -lcudart -lcuda

md5sum "$B"/lib_*/nvshmem_transport_ibgda.so.* "$B/bin/nvs_kill_repro"
ssh -n sunny "rm -rf gi-bundle/nvshmem_off380"
scp -rq "$B" sunny:gi-bundle/
ssh -n sunny "md5sum gi-bundle/nvshmem_off380/lib_*/nvshmem_transport_ibgda.so.* gi-bundle/nvshmem_off380/bin/nvs_kill_repro"
