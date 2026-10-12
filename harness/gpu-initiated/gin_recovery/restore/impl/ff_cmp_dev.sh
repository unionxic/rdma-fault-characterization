#!/usr/bin/env bash
# ff_cmp_dev.sh <tag> - the dev branch's machine-code comparison of work package 4 redone (build-time opt-in, user decision
# 2026-10-12): the GIN device operations (ff_ops.cu) and the three programs of prog_sass.sh (gin_ts2, gin_mr, NCCL's ring
# example) compiled against this branch's installed headers (agent_rs_dev/build/include) twice, without and with
# -DNCCL_GIN_RESTORE_DEVICE, for sm_75 and sm_86, objects only (nothing runs). Compared with work package 4's references
# (read only, agent_rs/sass4/: hk's headers and package 3's headers, which equal hk's but for the context stride):
#   res   cuobjdump -res-usage per kernel (res_cmp.py): without the macro the registers, stack and local memory must equal
#         package 3's (and hk's); with it they may grow (only programs that use the restore pay)
#   sass  without the macro, per kernel, sass_seg.py against package 3's: what is added (expected: the side-table pointer's
#         load, its compare, a branch and the trap) and no function of the hold path
# Output: agent_rs_dev/sass_<tag>/. Also the library: cuobjdump -res-usage of out/<lib>/libnccl.so (LIB, default
# rs_<tag>) against hk's and package 4's dumps (NCCL's own kernels are built without the macro).
set -euo pipefail
TAG=${1:?tag}
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
D=$(cd "$(dirname "$0")" && pwd)
CU=/usr/local/cuda-12.8/bin
REF=$SCR/agent_rs/sass4          # work package 4's references (read only)
W=$SCR/agent_rs_dev
O=$W/sass_$TAG
LIB=${LIB:-rs_$TAG}
mkdir -p "$O"
INC=$O/inc
if [ "${DUMPONLY:-0}" != 1 ]; then
  rm -rf "$INC"; mkdir -p "$INC"
  cp -a "$W/build/include/nccl.h" "$W/build/include/nccl_device.h" "$W/build/include/nccl_device" "$INC/"
fi
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
if [ "${DUMPONLY:-0}" = 1 ]; then  # the objects exist: dump and compare again only
  for p in ff gin_ts2 gin_mr ring; do for v in n m; do dump "$p" "$v"; done; done
else
for v in n m; do
  cc ff "$v" "$D/ff_ops.cu"
  cc gin_ts2 "$v" "$D/../../gin_ts2.cu" $DRV
  cc gin_mr "$v" "$D/../../remaining/gin_mr.cu" $DRV
  cc ring "$v" "$RING/main.cu" -I"$RING/../../../common/include"
done
fi
for p in ff gin_ts2 gin_mr ring; do
  for v in n m; do
    python3 "$D/res_cmp.py" "$REF/${p}_p3b.res" "$O/${p}_$v.res" > "$O/${p}_res_p3b_$v.txt" || true
    python3 "$D/res_cmp.py" "$REF/${p}_hk.res" "$O/${p}_$v.res" > "$O/${p}_res_hk_$v.txt" || true
  done
  python3 "$D/res_cmp.py" "$O/${p}_n.res" "$O/${p}_m.res" > "$O/${p}_res_n_m.txt" || true
  python3 "$D/sass_seg.py" "$REF/${p}_p3b.sass" "$O/${p}_n.sass" > "$O/${p}_seg_p3b_n.txt" 2>&1 || true
  python3 "$D/sass_seg.py" "$REF/${p}_p4d.sass" "$O/${p}_m.sass" > "$O/${p}_seg_p4d_m.txt" 2>&1 || true
  echo "== $p: res vs package 3 (no macro): $(tail -1 "$O/${p}_res_p3b_n.txt")"
  echo "== $p: res vs hk (no macro): $(tail -1 "$O/${p}_res_hk_n.txt")"
  echo "== $p: res no macro vs macro: $(tail -1 "$O/${p}_res_n_m.txt")"
done
if [ -f "$W/out/$LIB/libnccl.so.2.32.3" ]; then
  "$CU/cuobjdump" -res-usage "$W/out/$LIB/libnccl.so.2.32.3" > "$O/lib_$LIB.res"
  python3 "$D/res_cmp.py" "$REF/lib/hk.res" "$O/lib_$LIB.res" > "$O/lib_res_hk.txt" || true
  python3 "$D/res_cmp.py" "$REF/lib/rs_p3b.res" "$O/lib_$LIB.res" > "$O/lib_res_p3b.txt" || true
  python3 "$D/res_cmp.py" "$REF/lib/rs_p4d.res" "$O/lib_$LIB.res" > "$O/lib_res_p4d.txt" || true
  echo "== library $LIB: res vs hk: $(tail -1 "$O/lib_res_hk.txt")"
  echo "== library $LIB: res vs package 3: $(tail -1 "$O/lib_res_p3b.txt")"
  echo "== library $LIB: res vs package 4: $(tail -1 "$O/lib_res_p4d.txt")"
fi
