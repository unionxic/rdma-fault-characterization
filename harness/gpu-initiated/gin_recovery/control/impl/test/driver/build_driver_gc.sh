#!/usr/bin/env bash
# build_driver_gc.sh - gin-control: compile this folder's gin_mi.cu (gin-mirror's test driver with the GC_GPUHANG_IT switch,
# see its head comment and ../notes_test.md) LOCALLY on rain (nice 19, idle I/O). COMPILE ONLY: no library build, no GPU or
# RDMA program runs. gin-mirror's ../../../../mirror/impl/test/build_mi_test.sh stage "mi" (copied, then cut to that stage).
# The headers and the library are a gin-control build tree's installed ones (RSINC, RSLIB; default the session scratch's
# agent_gc_p2a2/build, the tree the smokes build gc in), the headers copied first; nothing under that tree is written.
#
#   mi    gin_mi.cu with -DNCCL_GIN_RESTORE_DEVICE against the headers, linked to RSLIB's libnccl -> $OUTROOT/<MIOUT>/gin_mi
#   info  the header digest and the library md5
# usage: [MIOUT=<word>] [OUTROOT=<dir>] [RSINC=<dir>] [RSLIB=<dir>] build_driver_gc.sh <mi|info>
#        (MIOUT default mi; OUTROOT default $SCR/agent_gc_smoke4/test/out; nvcc output is not byte-reproducible, so an
#        output that exists is refused)
set -euo pipefail
STAGE=${1:?stage: mi|info}
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
D="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CUDA=/usr/local/cuda-12.8
GENCODE="-gencode=arch=compute_75,code=sm_75 -gencode=arch=compute_86,code=sm_86"
RSINC=${RSINC:-$SCR/agent_gc_p2a2/build/include}; RSLIB=${RSLIB:-$SCR/agent_gc_p2a2/build/lib}
OUTROOT=${OUTROOT:-$SCR/agent_gc_smoke4/test/out}
MIOUT=${MIOUT:-mi}
case "$MIOUT" in "" | *[!A-Za-z0-9_.-]* | .*) echo "MIOUT is one plain word: '$MIOUT'" >&2; exit 2 ;; esac
OUT=$OUTROOT/$MIOUT; INC=$OUTROOT/include_$MIOUT
md5() { md5sum < "$1" | cut -c1-32; }
ndigest() { (cd "$1" && find . -type f | LC_ALL=C sort | xargs md5sum | md5sum | cut -c1-32); }
NV() { nice -n 19 ionice -c3 "$CUDA/bin/nvcc" "$@"; }
case "$STAGE" in
  mi)
    grep -q 'ncclGinRestoreResume' "$RSINC/nccl.h" || { echo "no restore API in $RSINC/nccl.h" >&2; exit 1; }
    [ ! -e "$OUT/gin_mi" ] || { echo "$OUT/gin_mi already holds a build; set MIOUT" >&2; exit 1; }
    rm -rf "$INC"; mkdir -p "$INC" "$OUT"; cp -a "$RSINC/." "$INC/"
    NV -std=c++17 -O2 --expt-relaxed-constexpr --expt-extended-lambda $GENCODE -DNCCL_GIN_RESTORE_DEVICE \
      -isystem "$INC" -Xcompiler "-Wall,-Wextra" "$D/gin_mi.cu" -o "$OUT/gin_mi" \
      -L"$RSLIB" -lnccl -lcudart -lpthread
    echo "gin_mi $(md5 "$OUT/gin_mi") src $(md5 "$D/gin_mi.cu") include $(ndigest "$INC") macro=1 lib $(md5 "$RSLIB/libnccl.so.2.32.3")" \
      | tee "$OUT/gin_mi.build.txt" ;;
  info)
    echo "headers $RSINC digest $(ndigest "$RSINC") lib $(md5 "$RSLIB/libnccl.so.2.32.3" 2>/dev/null || echo missing)" ;;
  *) echo "unknown stage $STAGE" >&2; exit 2 ;;
esac
