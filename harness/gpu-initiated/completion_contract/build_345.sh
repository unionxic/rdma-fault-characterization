#!/usr/bin/env bash
# build_345.sh - unmodified NVSHMEM v3.4.5-0 and the official380 reproducer linked against it,
# bundled in ~/gi-bundle/nvshmem_345 on rain and sunny (completion_contract P1-P3).
#
#   W=<work dir> bash build_345.sh
#
# Source: https://github.com/NVIDIA/nvshmem/archive/refs/tags/v3.4.5-0.tar.gz (tag 131da55f,
# tarball sha256 74047b0b572d677a6c072c9e5486514d19fe7dff1252a2548ee08ce8d68b6bc5).
# Same cmake options as ../nvshmem_rootcause/official380/build.sh except GDRCopy: 3.4.5 needs
# gdrapi.h, which is not installed here, and the cells use the cpu_host_memory and gpu handlers,
# which do not use GDRCopy. The reproducer is linked per version because the device library is
# static.
set -eu
W=${W:?work dir}
CUDA=/usr/local/cuda-12.8
REPRO=$(cd "$(dirname "$0")/../nvshmem_rootcause/official380" && pwd)/kill_repro.cu
SRC=$W/nvshmem-3.4.5-0
B=$HOME/gi-bundle/nvshmem_345

if [ ! -d "$SRC" ]; then
  (cd "$W" && curl -sSL -o v3.4.5-0.tar.gz https://github.com/NVIDIA/nvshmem/archive/refs/tags/v3.4.5-0.tar.gz &&
   sha256sum v3.4.5-0.tar.gz && tar xzf v3.4.5-0.tar.gz)
fi
rm -rf "$W/build"
cmake -S "$SRC" -B "$W/build" -DCMAKE_BUILD_TYPE=release -DCMAKE_CUDA_ARCHITECTURES="75;86" \
  -DCUDA_HOME=$CUDA -DCMAKE_CUDA_COMPILER=$CUDA/bin/nvcc \
  -DNVSHMEM_IBGDA_SUPPORT=ON -DNVSHMEM_IBRC_SUPPORT=ON -DNVSHMEM_USE_GDRCOPY=OFF \
  -DNVSHMEM_MPI_SUPPORT=OFF -DNVSHMEM_SHMEM_SUPPORT=OFF -DNVSHMEM_UCX_SUPPORT=OFF \
  -DNVSHMEM_PMIX_SUPPORT=OFF -DNVSHMEM_LIBFABRIC_SUPPORT=OFF -DNVSHMEM_USE_NCCL=OFF \
  -DNVSHMEM_BUILD_TESTS=OFF -DNVSHMEM_BUILD_EXAMPLES=OFF -DNVSHMEM_BUILD_PYTHON_LIB=OFF \
  -DNVSHMEM_BUILD_BITCODE_LIBRARY=OFF -DNVSHMEM_BUILD_LTOIR_LIBRARY=OFF \
  -DNVSHMEM_BUILD_HYDRA_LAUNCHER=OFF -DNVSHMEM_BUILD_TXZ_PACKAGE=OFF \
  -DCMAKE_INSTALL_PREFIX="$W/install"
make -C "$W/build" -j16
make -C "$W/build" install

rm -rf "$B" && mkdir -p "$B/bin"
cp -a "$W/install/lib" "$B/lib_stock"
$CUDA/bin/nvcc -std=c++17 -rdc=true -gencode=arch=compute_75,code=sm_75 -gencode=arch=compute_86,code=sm_86 \
  -Xcompiler -Wall,-Wextra -I"$W/install/include" "$REPRO" -o "$B/bin/nvs_kill_repro" \
  -L"$W/install/lib" -lnvshmem_host -lnvshmem_device -L$CUDA/lib64 -lcudart -lcuda

md5sum "$B"/lib_stock/nvshmem_transport_ibgda.so.* "$B/bin/nvs_kill_repro"
ssh -n sunny "rm -rf gi-bundle/nvshmem_345"
scp -rq "$B" sunny:gi-bundle/
ssh -n sunny "md5sum gi-bundle/nvshmem_345/lib_stock/nvshmem_transport_ibgda.so.* gi-bundle/nvshmem_345/bin/nvs_kill_repro"
