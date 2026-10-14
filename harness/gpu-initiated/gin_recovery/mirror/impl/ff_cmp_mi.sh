#!/usr/bin/env bash
# ff_cmp_mi.sh <tag> - gin-mirror's machine-code comparison of the device programs (EXPERIMENT.md 9.5, impl/PARALLEL.md
# "fail-fast 동일성"), ported from gin-restore's ff_cmp_dev.sh. build_mi.sh ident runs it (W, HK, I5, LIB in the
# environment; dev and int). Nothing runs on a GPU; no cluster action.
#   compile  gin-restore's ff_ops.cu (one kernel per GIN device operation) and the three programs of prog_sass.sh (gin_ts2,
#            gin_mr, NCCL's ring example) against this tree's installed headers ($W/build/include; build_mi.sh mip checks
#            that build-mip installs the same headers, so one compile stands for both builds), twice: without
#            NCCL_GIN_RESTORE_DEVICE (variant n) and with it (variant m), for sm_75 and sm_86, objects only, warnings
#            counted (gin_ts2 and gin_mr with -Werror). Variant m is the compile check of the mirror's device code.
#   res      cuobjdump -res-usage per kernel (gin-restore's res_cmp.py): n against i5's n ($I5/sass_i5, the same flags):
#            must be the same; m against i5's m: the mirror's cost in a macro build (registers may grow, reported); n
#            against m
#   library  cuobjdump -res-usage of out/$LIB (research) and out/$LIBP (production, default mip<tag without mi>) against
#            i5's (build, build-rsp) and hk's (build, build-hkp) libraries (NCCL's own kernels: no macro)
# Output: $W/sass_<tag>/; a summary on stdout. exact_cmp_mi.sh then compares the whole SASS.
set -euo pipefail
TAG=${1:?tag}
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
D=$(cd "$(dirname "$0")" && pwd)
RSD=$(cd "$D/../../restore/impl" && pwd)  # gin-restore's tools and programs (read only)
CU=/usr/local/cuda-12.8/bin
W=${W:-$SCR/agent_mi_dev}
I5=${I5:-$SCR/agent_rs_int}
HK=${HK:-$SCR/agent_gd/gin_hk}
LIB=${LIB:-$TAG}
LIBP=${LIBP:-mip${LIB#mi}}
O=$W/sass_$TAG
REF=$I5/sass_i5  # i5's programs, compiled by gin-restore's ff_cmp_dev.sh with the same flags (read only)
[ -e "$O" ] && { echo "$O exists; give a new tag" >&2; exit 1; }
mkdir -p "$O"
INC=$O/inc
mkdir -p "$INC"
cp -a "$W/build/include/nccl.h" "$W/build/include/nccl_device.h" "$W/build/include/nccl_device" "$INC/"
RING=$W/nccl-src/docs/examples/09_gin_optimizations/01_ring_exchange/c
dump() {  # dump <name> <variant>: resource usage and SASS of both architectures (cuobjdump takes one file at a time)
  local n=$1 v=$2
  { "$CU/cuobjdump" -res-usage "$O/${n}_${v}75.o"; "$CU/cuobjdump" -res-usage "$O/${n}_${v}86.o"; } > "$O/${n}_$v.res"
  { "$CU/cuobjdump" -sass "$O/${n}_${v}75.o"; "$CU/cuobjdump" -sass "$O/${n}_${v}86.o"; } > "$O/${n}_$v.sass"
}
cc() {  # cc <name> <variant n|m> <source> [extra flags]
  local n=$1 v=$2 src=$3; shift 3
  local mac=""; [ "$v" = m ] && mac="-DNCCL_GIN_RESTORE_DEVICE"
  for a in 75 86; do
    nice -n 19 "$CU/nvcc" -std=c++17 -O2 --expt-relaxed-constexpr -gencode=arch=compute_$a,code=sm_$a $mac -isystem "$INC" \
      "$@" -c "$src" -o "$O/${n}_$v$a.o" > "$O/${n}_$v$a.log" 2>&1 || { cat "$O/${n}_$v$a.log" >&2; exit 1; }
  done
  dump "$n" "$v"
  echo "$n ($v): warnings $(cat "$O/${n}_${v}75.log" "$O/${n}_${v}86.log" | grep -ci warning || true)"
}
DRV="-Xcompiler -Wall,-Wextra,-Werror,-Wno-missing-field-initializers"
for v in n m; do
  cc ff "$v" "$RSD/ff_ops.cu"
  cc gin_ts2 "$v" "$RSD/../../gin_ts2.cu" $DRV
  cc gin_mr "$v" "$RSD/../../remaining/gin_mr.cu" $DRV
  cc ring "$v" "$RING/main.cu" -I"$RING/../../../common/include"
done
for p in ff gin_ts2 gin_mr ring; do
  python3 "$RSD/res_cmp.py" "$REF/${p}_n.res" "$O/${p}_n.res" > "$O/${p}_res_i5_n.txt" || true
  python3 "$RSD/res_cmp.py" "$REF/${p}_m.res" "$O/${p}_m.res" > "$O/${p}_res_i5_m.txt" || true
  python3 "$RSD/res_cmp.py" "$O/${p}_n.res" "$O/${p}_m.res" > "$O/${p}_res_n_m.txt" || true
  echo "== $p: res vs i5 (no macro): $(tail -1 "$O/${p}_res_i5_n.txt")"
  echo "== $p: res vs i5 (macro): $(tail -1 "$O/${p}_res_i5_m.txt")"
  echo "== $p: res no macro vs macro: $(tail -1 "$O/${p}_res_n_m.txt")"
done
lib() {  # lib <name> <ours> <i5's> <hk's>
  local n=$1 a=$2 b=$3 c=$4
  [ -f "$a" ] || { echo "== library $n: $a missing (build it first)"; return 0; }
  "$CU/cuobjdump" -res-usage "$a" > "$O/lib_$n.res"
  "$CU/cuobjdump" -res-usage "$b" > "$O/lib_${n}_i5.res"
  "$CU/cuobjdump" -res-usage "$c" > "$O/lib_${n}_hk.res"
  python3 "$RSD/res_cmp.py" "$O/lib_${n}_i5.res" "$O/lib_$n.res" > "$O/lib_${n}_res_i5.txt" || true
  python3 "$RSD/res_cmp.py" "$O/lib_${n}_hk.res" "$O/lib_$n.res" > "$O/lib_${n}_res_hk.txt" || true
  echo "== library $n: res vs i5: $(tail -1 "$O/lib_${n}_res_i5.txt")"
  echo "== library $n: res vs hk: $(tail -1 "$O/lib_${n}_res_hk.txt")"
}
lib "$LIB" "$W/out/$LIB/libnccl.so.2.32.3" "$I5/build/lib/libnccl.so.2.32.3" "$HK/build/lib/libnccl.so.2.32.3"
lib "$LIBP" "$W/out/$LIBP/libnccl.so.2.32.3" "$I5/build-rsp/lib/libnccl.so.2.32.3" "$HK/build-hkp/lib/libnccl.so.2.32.3"
