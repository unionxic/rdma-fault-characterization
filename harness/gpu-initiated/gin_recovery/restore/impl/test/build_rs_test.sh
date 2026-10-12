#!/usr/bin/env bash
# build_rs_test.sh - gin-restore work package 10: compile the test programs LOCALLY on rain (nice 19, idle I/O). COMPILE ONLY:
# no library build here, no GPU or RDMA program runs. Header trees are read through COPIES under $SCR/agent_rs_int/test/
# (nothing in agent_rs_int's build, agent_rs_test or agent_gd is written). Integration (2026-10-12): the layer's headers and
# research libnccl are the integrated tree's (agent_rs_int/build, impl/build_rs.sh); the outputs go to agent_rs_int/test/.
#
#   rs     gin_rs.cu against this layer's headers ($SCR/agent_rs_int/build/include) with -DNCCL_GIN_RESTORE_DEVICE (the
#          build-time opt-in, EXPERIMENT.md 12 choice (b)), linked to the layer's research libnccl -> out/<RSTOUT>/gin_rs
#   nomacro  the same source against this layer's headers without the macro -> out/<RSTOUT>/gin_rs_nomacro (the no-macro
#          refusal cell)
#   hk     the same source against gpu-detect's hk headers ($SCR/agent_gd/gin_hk/build/include), no macro, linked to hk's
#          libnccl -> out/<RSTOUT>/gin_rs_hk (the no-restore control rs4_kill3@hk; the restore hooks compiled out)
#   cost   gin-remaining's gin_ts2.cu + ../../feas/gin_ts2_winflags.diff (the 9.15.6 driver) against this layer's headers:
#          with the macro -> out/cost/gin_ts2 (the hold arms), without -> out/cost/gin_ts2_ff (the fail-fast arm of the
#          fail-fast-branch cell); the hk arm uses the deployed ord driver (~/rs-bundle/ord/gin_ts2, hw = hk headers)
#   mr     gin-remaining's gin_mr.cu against this layer's headers: out/mr/ff/gin_mr (no macro) and out/mr/hold/gin_mr (macro)
#   info   the header digests and link libraries
# usage: build_rs_test.sh <rs|nomacro|hk|cost|mr|info>   (RSTOUT: the output subfolder of rs and hk, default rs; nvcc output is not
#        byte-reproducible, so a file that already exists is refused)
set -euo pipefail
STAGE=${1:?stage: rs|nomacro|hk|cost|mr|info}
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
D=$(cd "$(dirname "$0")" && pwd)
CUDA=/usr/local/cuda-12.8
GENCODE="-gencode=arch=compute_75,code=sm_75 -gencode=arch=compute_86,code=sm_86"
RSINC=$SCR/agent_rs_int/build/include; RSLIB=$SCR/agent_rs_int/build/lib
HKINC=$SCR/agent_gd/gin_hk/build/include; HKLIB=$SCR/agent_gd/gin_hk/build/lib
W=$SCR/agent_rs_int/test
OUT=$W/out/${RSTOUT:-rs}
md5() { md5sum < "$1" | cut -c1-32; }
ndigest() { (cd "$1" && find . -type f | LC_ALL=C sort | xargs md5sum | md5sum | cut -c1-32); }
copyinc() { rm -rf "$2"; mkdir -p "$2"; cp -a "$1/." "$2/"; }  # a read-only copy of a header tree
NV() { nice -n 19 ionice -c3 "$CUDA/bin/nvcc" "$@"; }
fresh() { [ ! -e "$1" ] || { echo "$1 already holds a build; set RSTOUT (or use a new cost folder)" >&2; exit 1; }; }
case "$STAGE" in
  rs)
    grep -q 'ncclGinRestoreResume' "$RSINC/nccl.h" || { echo "no restore API in $RSINC/nccl.h" >&2; exit 1; }
    copyinc "$RSINC" "$W/include_rs"; mkdir -p "$OUT"; fresh "$OUT/gin_rs"
    NV -std=c++17 -O2 --expt-relaxed-constexpr --expt-extended-lambda $GENCODE -DNCCL_GIN_RESTORE_DEVICE \
      -isystem "$W/include_rs" -Xcompiler "-Wall,-Wextra" "$D/gin_rs.cu" -o "$OUT/gin_rs" \
      -L"$RSLIB" -lnccl -lcudart -lpthread
    echo "gin_rs $(md5 "$OUT/gin_rs") src $(md5 "$D/gin_rs.cu") include $(ndigest "$W/include_rs") macro=1 lib $(md5 "$RSLIB/libnccl.so.2.32.3")" \
      | tee "$OUT/gin_rs.build.txt" ;;
  nomacro)  # the same source against this layer's headers WITHOUT the macro: the program a fail-fast user builds; its
            # Resume is refused on every rank under the 2026-10-12 design (the no-macro refusal cell)
    grep -q 'ncclGinRestoreResume' "$RSINC/nccl.h" || { echo "no restore API in $RSINC/nccl.h" >&2; exit 1; }
    copyinc "$RSINC" "$W/include_rs"; mkdir -p "$OUT"; fresh "$OUT/gin_rs_nomacro"
    NV -std=c++17 -O2 --expt-relaxed-constexpr --expt-extended-lambda $GENCODE \
      -isystem "$W/include_rs" -Xcompiler "-Wall,-Wextra" "$D/gin_rs.cu" -o "$OUT/gin_rs_nomacro" \
      -L"$RSLIB" -lnccl -lcudart -lpthread
    echo "gin_rs_nomacro $(md5 "$OUT/gin_rs_nomacro") src $(md5 "$D/gin_rs.cu") include $(ndigest "$W/include_rs") macro=0 lib $(md5 "$RSLIB/libnccl.so.2.32.3")" \
      | tee "$OUT/gin_rs_nomacro.build.txt" ;;
  hk)
    [ -f "$HKINC/nccl.h" ] || { echo "hk headers missing at $HKINC" >&2; exit 1; }
    copyinc "$HKINC" "$W/include_hk"; mkdir -p "$OUT"; fresh "$OUT/gin_rs_hk"
    NV -std=c++17 -O2 --expt-relaxed-constexpr --expt-extended-lambda $GENCODE \
      -isystem "$W/include_hk" -Xcompiler "-Wall,-Wextra" "$D/gin_rs.cu" -o "$OUT/gin_rs_hk" \
      -L"$HKLIB" -lnccl -lcudart -lpthread
    echo "gin_rs_hk $(md5 "$OUT/gin_rs_hk") src $(md5 "$D/gin_rs.cu") include $(ndigest "$W/include_hk") macro=0 lib $(md5 "$HKLIB/libnccl.so.2.32.3")" \
      | tee "$OUT/gin_rs_hk.build.txt" ;;
  cost)
    src=$D/../../../gin_ts2.cu; o=$W/out/cost; w=$W/cost_src
    [ "$(md5 "$src")" = 1779db9d62eaa5dba5758b14a5ba6e17 ] || { echo "gin_ts2.cu is not the 9.15.6 driver's source" >&2; exit 1; }
    fresh "$o/gin_ts2"; fresh "$o/gin_ts2_ff"
    copyinc "$RSINC" "$W/include_rs"; mkdir -p "$o"; rm -rf "$w"; mkdir -p "$w"
    cp "$src" "$w/gin_ts2.cu"
    (cd "$w" && patch -p1 --forward --quiet < "$D/../../feas/gin_ts2_winflags.diff") || { echo "the patch does not apply" >&2; exit 1; }
    for v in macro ff; do
      if [ "$v" = macro ]; then def=-DNCCL_GIN_RESTORE_DEVICE; out=$o/gin_ts2; else def=""; out=$o/gin_ts2_ff; fi
      NV -std=c++17 -O2 --expt-relaxed-constexpr $GENCODE $def -isystem "$W/include_rs" \
        -Xcompiler "-Wall,-Wextra,-Werror,-Wno-missing-field-initializers" "$w/gin_ts2.cu" -o "$out" \
        -L "$RSLIB" -lnccl -lcudart -ldl
      echo "$(basename "$out") $(md5 "$out") gin_ts2.cu $(md5 "$src") + winflags $(md5 "$D/../../feas/gin_ts2_winflags.diff") macro=$([ "$v" = macro ] && echo 1 || echo 0)"
    done | tee "$o/build.txt" ;;
  mr)  # gin-remaining's unmodified 4-rank driver gin_mr.cu against this layer's headers (the regression cells): without the
       # macro -> out/mr/ff/gin_mr (the fail-fast program), with it -> out/mr/hold/gin_mr (the hold variants: the device
       # takes the hold send path, EXPERIMENT.md 7). An hr-header build would silently keep the old device path.
    src=$D/../../../remaining/gin_mr.cu; o=$W/out/mr
    fresh "$o/ff/gin_mr"; fresh "$o/hold/gin_mr"
    copyinc "$RSINC" "$W/include_rs"; mkdir -p "$o/ff" "$o/hold"
    for v in ff hold; do
      def=""; [ "$v" = hold ] && def=-DNCCL_GIN_RESTORE_DEVICE
      NV -std=c++17 -O2 --expt-relaxed-constexpr $GENCODE $def -isystem "$W/include_rs" \
        -Xcompiler "-Wall,-Wextra,-Werror,-Wno-missing-field-initializers" "$src" -o "$o/$v/gin_mr" -L "$RSLIB" -lnccl -lcudart
      echo "mr/$v/gin_mr $(md5 "$o/$v/gin_mr") gin_mr.cu $(md5 "$src") macro=$([ "$v" = hold ] && echo 1 || echo 0)"
    done | tee "$o/build.txt" ;;
  info)
    echo "rs headers $RSINC digest $(ndigest "$RSINC") lib $(md5 "$RSLIB/libnccl.so.2.32.3" 2>/dev/null || echo missing)"
    echo "hk headers $HKINC digest $(ndigest "$HKINC" 2>/dev/null || echo missing) lib $(md5 "$HKLIB/libnccl.so.2.32.3" 2>/dev/null || echo missing)" ;;
  *) echo "unknown stage $STAGE" >&2; exit 2 ;;
esac
