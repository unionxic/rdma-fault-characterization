#!/usr/bin/env bash
# build_driver_gc.sh - gin-control: compile this folder's gin_mi.cu (gin-mirror's test driver with the GC_GPUHANG_IT switch
# and, since 2026-10-24, its context filter GC_GPUHANG_CTX; since 2026-10-27 GC_QUIET_IT and GC_WAITPEND, and the async-error
# check's back-off after the first error (100 ms, at most 1 000 error results); see its head comment and
# ../notes_test.md) LOCALLY on rain (nice 19, idle I/O). COMPILE ONLY: no library build, no GPU or
# RDMA program runs. gin-mirror's ../../../../mirror/impl/test/build_mi_test.sh stage "mi" (copied, then cut to that stage).
# The headers and the library are a gin-control build tree's installed ones (RSINC, RSLIB; default the session scratch's
# agent_gc_p2a2/build, the tree the smokes build gc in), the headers copied first; nothing under that tree is written.
#
#   mi      gin_mi.cu with -DNCCL_GIN_RESTORE_DEVICE against the headers, linked to RSLIB's libnccl -> $OUTROOT/<MIOUT>/gin_mi
#   nomacro the same gin_mi.cu without the macro (gin-mirror build_mi_test.sh "nomacro"), RSLIB -> <MIOUT>/gin_mi_nomacro
#   mr      gin-remaining's gin_mr.cu, ff (no macro) and hold (the macro; build_mi_test.sh "mr"), RSLIB -> <MIOUT>/mr/<ff|hold>/gin_mr
#   cost    gin_ts2.cu + gin-restore's winflags diff + gin-mirror's gin_ts2_mi.diff with the macro (build_mi_test.sh "cost"),
#           linked to PLIB's libnccl (the cost arms' gcp) -> <MIOUT>/gin_ts2_mi
#           (2026-10-27: these three are the commands of pilot 1's scratch build_cost_pl1.sh and pilot 2's build_extra_pl2.sh,
#           moved here unchanged so that the main run's drivers are built from a tracked script; one <MIOUT> folder then holds
#           every driver, the DRV_DIR of deploy_gc.sh)
#   info    the header digest and the library md5s
# usage: [MIOUT=<word>] [OUTROOT=<dir>] [RSINC=<dir>] [RSLIB=<dir>] [PLIB=<dir>] build_driver_gc.sh <mi|nomacro|mr|cost|info>
#        (MIOUT default mi; OUTROOT default $SCR/agent_gc_smoke4/test/out; nvcc output is not byte-reproducible, so an
#        output that exists is refused)
set -euo pipefail
STAGE=${1:?stage: mi|nomacro|mr|cost|info}
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
D="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CUDA=/usr/local/cuda-12.8
GENCODE="-gencode=arch=compute_75,code=sm_75 -gencode=arch=compute_86,code=sm_86"
RSINC=${RSINC:-$SCR/agent_gc_p2a2/build/include}; RSLIB=${RSLIB:-$SCR/agent_gc_p2a2/build/lib}
PLIB=${PLIB:-$SCR/agent_gc_p2a2/build-gcp/lib}
G="$(cd "$D/../../../.." && pwd)"   # gin_recovery: gin_ts2.cu, remaining/, restore/feas/, mirror/impl/test/
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
  nomacro)
    [ ! -e "$OUT/gin_mi_nomacro" ] || { echo "$OUT/gin_mi_nomacro already holds a build; set MIOUT" >&2; exit 1; }
    I=${INC}_nomacro; rm -rf "$I"; mkdir -p "$I" "$OUT"; cp -a "$RSINC/." "$I/"
    NV -std=c++17 -O2 --expt-relaxed-constexpr --expt-extended-lambda $GENCODE -isystem "$I" -Xcompiler "-Wall,-Wextra" \
      "$D/gin_mi.cu" -o "$OUT/gin_mi_nomacro" -L"$RSLIB" -lnccl -lcudart -lpthread
    echo "gin_mi_nomacro $(md5 "$OUT/gin_mi_nomacro") src $(md5 "$D/gin_mi.cu") include $(ndigest "$I") macro=0 lib $(md5 "$RSLIB/libnccl.so.2.32.3")" \
      | tee "$OUT/gin_mi_nomacro.build.txt" ;;
  mr)
    for v in ff hold; do [ ! -e "$OUT/mr/$v/gin_mr" ] || { echo "$OUT/mr/$v/gin_mr already holds a build; set MIOUT" >&2; exit 1; }; done
    I=${INC}_mr; rm -rf "$I"; mkdir -p "$I" "$OUT/mr/ff" "$OUT/mr/hold"; cp -a "$RSINC/." "$I/"
    for v in ff hold; do
      def=""; [ "$v" = hold ] && def=-DNCCL_GIN_RESTORE_DEVICE
      NV -std=c++17 -O2 --expt-relaxed-constexpr $GENCODE $def -isystem "$I" \
        -Xcompiler "-Wall,-Wextra,-Werror,-Wno-missing-field-initializers" "$G/remaining/gin_mr.cu" -o "$OUT/mr/$v/gin_mr" -L "$RSLIB" -lnccl -lcudart
    done
    echo "mr/ff/gin_mr $(md5 "$OUT/mr/ff/gin_mr") mr/hold/gin_mr $(md5 "$OUT/mr/hold/gin_mr") gin_mr.cu $(md5 "$G/remaining/gin_mr.cu") include $(ndigest "$I") lib $(md5 "$RSLIB/libnccl.so.2.32.3")" \
      | tee "$OUT/gin_mr.build.txt" ;;
  cost)
    src=$G/gin_ts2.cu
    [ "$(md5 "$src")" = 1779db9d62eaa5dba5758b14a5ba6e17 ] || { echo "gin_ts2.cu is not the 9.15.6 driver's source" >&2; exit 1; }
    [ ! -e "$OUT/gin_ts2_mi" ] || { echo "$OUT/gin_ts2_mi already holds a build; set MIOUT" >&2; exit 1; }
    I=${INC}_cost; w=$OUTROOT/cost_src_$MIOUT; rm -rf "$I" "$w"; mkdir -p "$I" "$OUT" "$w"; cp -a "$RSINC/." "$I/"
    cp "$src" "$w/gin_ts2.cu"
    (cd "$w" && patch -p1 --forward --quiet < "$G/restore/feas/gin_ts2_winflags.diff")
    (cd "$w" && patch -p1 --forward --quiet < "$G/mirror/impl/test/gin_ts2_mi.diff")
    NV -std=c++17 -O2 --expt-relaxed-constexpr $GENCODE -DNCCL_GIN_RESTORE_DEVICE -isystem "$I" \
      -Xcompiler "-Wall,-Wextra,-Werror,-Wno-missing-field-initializers" "$w/gin_ts2.cu" -o "$OUT/gin_ts2_mi" -L "$PLIB" -lnccl -lcudart -ldl
    echo "gin_ts2_mi $(md5 "$OUT/gin_ts2_mi") gin_ts2.cu $(md5 "$src") + winflags $(md5 "$G/restore/feas/gin_ts2_winflags.diff") + mi $(md5 "$G/mirror/impl/test/gin_ts2_mi.diff") patched $(md5 "$w/gin_ts2.cu") include $(ndigest "$I") macro=1 lib $(md5 "$PLIB/libnccl.so.2.32.3")" \
      | tee "$OUT/gin_ts2_mi.build.txt" ;;
  info)
    echo "headers $RSINC digest $(ndigest "$RSINC") lib $(md5 "$RSLIB/libnccl.so.2.32.3" 2>/dev/null || echo missing) plib $(md5 "$PLIB/libnccl.so.2.32.3" 2>/dev/null || echo missing)" ;;
  *) echo "unknown stage $STAGE" >&2; exit 2 ;;
esac
