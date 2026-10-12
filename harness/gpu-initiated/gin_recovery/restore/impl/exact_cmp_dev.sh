#!/usr/bin/env bash
# exact_cmp_dev.sh <tag> - exact equality of the device code compiled WITHOUT NCCL_GIN_RESTORE_DEVICE against gpu-detect's
# hk (user direction 2026-10-12: byte-identical registers, stack, local and SASS for every kernel, programs and library),
# and the cost of the variant WITH it. Nothing runs; no cluster action. Read only: hk's build tree agent_gd/gin_hk.
#   programs  ff_ops.cu and prog_sass.sh's three programs, compiled by ff_cmp_dev.sh <tag> (variants n and m) and here a
#             third time against hk's installed headers with the same flags (variant h); per program and architecture:
#             the whole SASS dump (cuobjdump -sass: every line, so every instruction at any offset with both 64-bit
#             words of its encoding, the second one holding the scheduling bits) of n must equal h's, and
#             cuobjdump -res-usage of n must equal h's
#   library   every device object of agent_rs_dev/build (obj/device, obj/diagnostics/device) against hk's build: equal
#             whole SASS dumps, or equal once the compiler's per-compilation hash in internal names is masked; and the
#             whole libnccl's -res-usage against hk's (out/<LIB>, default rs_<tag>)
# Output: agent_rs_dev/sass_<tag>/exact/ (OUT=<dir> to change) and a summary on stdout.
# (The first version kept only the lines '^\s+/\*[0-9a-f]{4}\*/': it dropped every instruction at an offset of 0x10000
# or more and every encoding's second word; its verdicts are void.)
set -uo pipefail
TAG=${1:?tag}
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
D=$(cd "$(dirname "$0")" && pwd)
CU=/usr/local/cuda-12.8/bin
W=$SCR/agent_rs_dev
HK=$SCR/agent_gd/gin_hk
O=$W/sass_$TAG
X=${OUT:-$O/exact}
LIB=${LIB:-rs_$TAG}
mkdir -p "$X"
RING=$W/nccl-src/docs/examples/09_gin_optimizations/01_ring_exchange/c
DRV="-Xcompiler -Wall,-Wextra,-Werror,-Wno-missing-field-initializers"
INCH=$X/inc_hk
rm -rf "$INCH"; mkdir -p "$INCH"
cp -a "$HK/build/include/nccl.h" "$HK/build/include/nccl_device.h" "$HK/build/include/nccl_device" "$INCH/"
ch() {  # ch <name> <source> [flags]: hk headers, same flags as ff_cmp_dev.sh's cc
  local n=$1 src=$2; shift 2
  for a in 75 86; do
    nice -n 19 "$CU/nvcc" -std=c++17 -O2 --expt-relaxed-constexpr -gencode=arch=compute_$a,code=sm_$a -isystem "$INCH" \
      "$@" -c "$src" -o "$X/${n}_h$a.o" > "$X/${n}_h$a.log" 2>&1 || { cat "$X/${n}_h$a.log" >&2; exit 1; }
  done
}
sassText() { "$CU/cuobjdump" -sass "$1"; }
ch ff "$D/ff_ops.cu"
ch gin_ts2 "$D/../../gin_ts2.cu" $DRV
ch gin_mr "$D/../../remaining/gin_mr.cu" $DRV
ch ring "$RING/main.cu" -I"$RING/../../../common/include"
pe=0; pd=0
for p in ff gin_ts2 gin_mr ring; do
  for a in 75 86; do
    sassText "$O/${p}_n$a.o" > "$X/${p}_n$a.sass"
    sassText "$X/${p}_h$a.o" > "$X/${p}_h$a.sass"
    "$CU/cuobjdump" -res-usage "$O/${p}_n$a.o" | grep -E 'Function|REG' > "$X/${p}_n$a.res"
    "$CU/cuobjdump" -res-usage "$X/${p}_h$a.o" | grep -E 'Function|REG' > "$X/${p}_h$a.res"
    if cmp -s "$X/${p}_n$a.sass" "$X/${p}_h$a.sass" && cmp -s "$X/${p}_n$a.res" "$X/${p}_h$a.res"; then
      pe=$((pe + 1))
      echo "program $p sm_$a: SASS and resources identical to hk ($(grep -cE '^\s+/\*[0-9a-f]{4,}\*/' "$X/${p}_h$a.sass") instructions, $(grep -c Function "$X/${p}_h$a.sass") functions, $(wc -l < "$X/${p}_h$a.sass") lines)"
    else
      pd=$((pd + 1))
      echo "program $p sm_$a: DIFFERENT from hk: $(diff "$X/${p}_h$a.sass" "$X/${p}_n$a.sass" | grep -c '^[<>]') SASS lines, res $(cmp -s "$X/${p}_n$a.res" "$X/${p}_h$a.res" && echo same || echo different)"
    fi
  done
done
echo "programs: identical $pe, different $pd (program x architecture)"
# the library's device objects
le=0; lh=0; ld=0; lm=0
mask() { sed -E 's/(_INTERNAL_|__nv_static_[0-9]+__|__N__)[0-9a-f]{8}_/\1H_/g; s/_cu_[0-9a-f]{8}_[0-9]+/_cu_H/g'; }
while IFS= read -r rel; do
  h="$HK/build/$rel"; r="$W/build/$rel"
  [ -f "$h" ] || { lm=$((lm + 1)); echo "library: missing in hk: $rel"; continue; }
  a=$(sassText "$h" | md5sum); b=$(sassText "$r" | md5sum)
  if [ "$a" = "$b" ]; then le=$((le + 1)); continue; fi
  a=$(sassText "$h" | mask | md5sum); b=$(sassText "$r" | mask | md5sum)
  if [ "$a" = "$b" ]; then lh=$((lh + 1)); echo "library: equal once the compile hash is masked: $rel"; continue; fi
  ld=$((ld + 1)); echo "library: DIFFERENT: $rel"
done < <(cd "$W/build" && find obj/device obj/diagnostics/device -name '*.o' | LC_ALL=C sort)
echo "library device objects: identical $le, identical with the hash masked $lh, different $ld, missing in hk $lm"
if [ -f "$W/out/$LIB/libnccl.so.2.32.3" ]; then
  "$CU/cuobjdump" -res-usage "$W/out/$LIB/libnccl.so.2.32.3" > "$X/lib_$LIB.res"
  "$CU/cuobjdump" -res-usage "$HK/build/lib/libnccl.so.2.32.3" > "$X/lib_hk.res"
  a=$(grep -E 'Function|REG' "$X/lib_hk.res" | mask | md5sum); b=$(grep -E 'Function|REG' "$X/lib_$LIB.res" | mask | md5sum)
  echo "library $LIB resource usage vs hk (names with the hash masked): $([ "$a" = "$b" ] && echo identical || echo DIFFERENT)"
fi
