#!/usr/bin/env bash
# build_mi_test.sh - gin-mirror, test branch: compile the test programs LOCALLY on rain (nice 19, idle I/O). COMPILE ONLY:
# no library build here, no GPU or RDMA program runs. gin-restore's build_rs_test.sh (copied and then changed). The mirror
# layer's headers are read through a COPY of the integrated tree (set at integration; here, before integration, the i5
# headers $SCR/agent_rs_int/build/include, which have the restore API: the mirror drivers compile the same against both,
# since gin_mi and gin_ts2_mi use only the public restore API and GIN device API, 0 warnings). Nothing under agent_rs_int,
# agent_gd or another branch's tree is written. The outputs go to $SCR/agent_mi_test/out/<MIOUT>/.
#
#   mi      gin_mi.cu against the headers with -DNCCL_GIN_RESTORE_DEVICE (the build-time opt-in), linked to the mirror
#           research libnccl (at integration; here the i5 research libnccl, read only) -> out/<MIOUT>/gin_mi
#   nomacro gin_mi.cu against the headers WITHOUT the macro -> out/<MIOUT>/gin_mi_nomacro (the no-macro refusal: its Resume
#           is refused on every rank, as gin-restore's gin_rs_nomacro)
#   cost    gin_ts2.cu + ../../../restore/feas/gin_ts2_winflags.diff + gin_ts2_mi.diff (the mirror cost driver; cost_man.md and
#           run_cost_mi.sh) with the macro -> out/cost/gin_ts2_mi
#   mr      gin-remaining's gin_mr.cu against the headers: out/mr/ff/gin_mr (no macro) and out/mr/hold/gin_mr (macro): the
#           regression cells, mirror off (gin-restore's regression against the mirror layer)
#   info    the header digest and link libraries
# usage: build_mi_test.sh <mi|nomacro|cost|mr|info>   (MIOUT: the output subfolder of mi and nomacro, default mi; nvcc
#        output is not byte-reproducible, so a file that already exists is refused; RSINC and RSLIB override the header and
#        library trees, default the i5 build in the session scratch)
set -euo pipefail
STAGE=${1:?stage: mi|nomacro|cost|mr|info}
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
D=$(cd "$(dirname "$0")" && pwd)
CUDA=/usr/local/cuda-12.8
GENCODE="-gencode=arch=compute_75,code=sm_75 -gencode=arch=compute_86,code=sm_86"
RSINC=${RSINC:-$SCR/agent_rs_int/build/include}; RSLIB=${RSLIB:-$SCR/agent_rs_int/build/lib}
W=$SCR/agent_mi_test
OUT=$W/out/${MIOUT:-mi}
md5() { md5sum < "$1" | cut -c1-32; }
ndigest() { (cd "$1" && find . -type f | LC_ALL=C sort | xargs md5sum | md5sum | cut -c1-32); }
copyinc() { rm -rf "$2"; mkdir -p "$2"; cp -a "$1/." "$2/"; }
NV() { nice -n 19 ionice -c3 "$CUDA/bin/nvcc" "$@"; }
fresh() { [ ! -e "$1" ] || { echo "$1 already holds a build; set MIOUT (or use a new cost/mr folder)" >&2; exit 1; }; }
case "$STAGE" in
  mi)
    grep -q 'ncclGinRestoreResume' "$RSINC/nccl.h" || { echo "no restore API in $RSINC/nccl.h" >&2; exit 1; }
    copyinc "$RSINC" "$W/include_mi"; mkdir -p "$OUT"; fresh "$OUT/gin_mi"
    NV -std=c++17 -O2 --expt-relaxed-constexpr --expt-extended-lambda $GENCODE -DNCCL_GIN_RESTORE_DEVICE \
      -isystem "$W/include_mi" -Xcompiler "-Wall,-Wextra" "$D/gin_mi.cu" -o "$OUT/gin_mi" \
      -L"$RSLIB" -lnccl -lcudart -lpthread
    echo "gin_mi $(md5 "$OUT/gin_mi") src $(md5 "$D/gin_mi.cu") include $(ndigest "$W/include_mi") macro=1 lib $(md5 "$RSLIB/libnccl.so.2.32.3")" \
      | tee "$OUT/gin_mi.build.txt" ;;
  nomacro)
    grep -q 'ncclGinRestoreResume' "$RSINC/nccl.h" || { echo "no restore API in $RSINC/nccl.h" >&2; exit 1; }
    copyinc "$RSINC" "$W/include_mi"; mkdir -p "$OUT"; fresh "$OUT/gin_mi_nomacro"
    NV -std=c++17 -O2 --expt-relaxed-constexpr --expt-extended-lambda $GENCODE \
      -isystem "$W/include_mi" -Xcompiler "-Wall,-Wextra" "$D/gin_mi.cu" -o "$OUT/gin_mi_nomacro" \
      -L"$RSLIB" -lnccl -lcudart -lpthread
    echo "gin_mi_nomacro $(md5 "$OUT/gin_mi_nomacro") src $(md5 "$D/gin_mi.cu") include $(ndigest "$W/include_mi") macro=0 lib $(md5 "$RSLIB/libnccl.so.2.32.3")" \
      | tee "$OUT/gin_mi_nomacro.build.txt" ;;
  cost)
    src=$D/../../../gin_ts2.cu; o=$W/out/cost; w=$W/cost_src
    [ "$(md5 "$src")" = 1779db9d62eaa5dba5758b14a5ba6e17 ] || { echo "gin_ts2.cu is not the 9.15.6 driver's source" >&2; exit 1; }
    fresh "$o/gin_ts2_mi"
    copyinc "$RSINC" "$W/include_mi"; mkdir -p "$o"; rm -rf "$w"; mkdir -p "$w"
    cp "$src" "$w/gin_ts2.cu"
    (cd "$w" && patch -p1 --forward --quiet < "$D/../../../restore/feas/gin_ts2_winflags.diff") || { echo "winflags does not apply" >&2; exit 1; }
    (cd "$w" && patch -p1 --forward --quiet < "$D/gin_ts2_mi.diff") || { echo "gin_ts2_mi.diff does not apply" >&2; exit 1; }
    NV -std=c++17 -O2 --expt-relaxed-constexpr $GENCODE -DNCCL_GIN_RESTORE_DEVICE -isystem "$W/include_mi" \
      -Xcompiler "-Wall,-Wextra,-Werror,-Wno-missing-field-initializers" "$w/gin_ts2.cu" -o "$o/gin_ts2_mi" \
      -L "$RSLIB" -lnccl -lcudart -ldl
    echo "gin_ts2_mi $(md5 "$o/gin_ts2_mi") gin_ts2.cu $(md5 "$src") + winflags $(md5 "$D/../../../restore/feas/gin_ts2_winflags.diff") + mi $(md5 "$D/gin_ts2_mi.diff") macro=1" \
      | tee "$o/build.txt" ;;
  mr)
    src=$D/../../../remaining/gin_mr.cu; o=$W/out/mr
    fresh "$o/ff/gin_mr"; fresh "$o/hold/gin_mr"
    copyinc "$RSINC" "$W/include_mi"; mkdir -p "$o/ff" "$o/hold"
    for v in ff hold; do
      def=""; [ "$v" = hold ] && def=-DNCCL_GIN_RESTORE_DEVICE
      NV -std=c++17 -O2 --expt-relaxed-constexpr $GENCODE $def -isystem "$W/include_mi" \
        -Xcompiler "-Wall,-Wextra,-Werror,-Wno-missing-field-initializers" "$src" -o "$o/$v/gin_mr" -L "$RSLIB" -lnccl -lcudart
      echo "mr/$v/gin_mr $(md5 "$o/$v/gin_mr") gin_mr.cu $(md5 "$src") macro=$([ "$v" = hold ] && echo 1 || echo 0)"
    done | tee "$o/build.txt" ;;
  info)
    echo "mi headers $RSINC digest $(ndigest "$RSINC") lib $(md5 "$RSLIB/libnccl.so.2.32.3" 2>/dev/null || echo missing)" ;;
  *) echo "unknown stage $STAGE" >&2; exit 2 ;;
esac
