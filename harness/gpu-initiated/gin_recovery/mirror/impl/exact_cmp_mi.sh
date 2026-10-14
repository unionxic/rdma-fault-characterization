#!/usr/bin/env bash
# exact_cmp_mi.sh <tag> - gin-mirror's fail-fast identity (EXPERIMENT.md 9.5, impl/PARALLEL.md "fail-fast 동일성"), ported
# from gin-restore's exact_cmp_dev.sh: the device code compiled WITHOUT NCCL_GIN_RESTORE_DEVICE must be byte-identical
# (whole SASS dumps and cuobjdump -res-usage) to gpu-detect's hk and to gin-restore's i5, for the research and the
# production build. Runs after ff_cmp_mi.sh <tag> (its variant n objects). Nothing runs on a GPU; no cluster action.
# Read only: $HK (agent_gd/gin_hk: build, build-hkp) and $I5 (agent_rs_int: build, build-rsp).
#   programs  ff_ops.cu and prog_sass.sh's three programs: this tree's variant n (ff_cmp_mi.sh) against the same sources
#             compiled here with the same flags against hk's installed headers (h) and i5's (i); per program and
#             architecture the whole `cuobjdump -sass` (every line: every instruction at any offset with both words of its
#             encoding) and the resource lines must be equal. The installed headers of the two builds are the same
#             (build_mi.sh mip checks it), so the programs stand for both builds.
#   library   every device object (obj/device, obj/diagnostics/device) of $W/build against i5's build and hk's build, and of
#             $W/build-mip against i5's build-rsp and hk's build-hkp: equal whole SASS dumps, or equal once the compiler's
#             per-compilation hash in internal names is masked; then the whole libnccl's -res-usage (hash masked) of
#             out/$LIB and out/$LIBP against i5's and hk's libraries. Known before this layer (gin-restore EXPERIMENT.md 12,
#             2026-10-12): hk's build trees hold 22 stale symmetric GIN objects (compiled before hk's last device header
#             change), so 22 objects differ from hk's in every build since; the comparison with i5 has no such exception.
# Output: $W/sass_<tag>/exact/ and a summary on stdout.
set -uo pipefail
TAG=${1:?tag}
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
D=$(cd "$(dirname "$0")" && pwd)
RSD=$(cd "$D/../../restore/impl" && pwd)
CU=/usr/local/cuda-12.8/bin
W=${W:-$SCR/agent_mi_dev}
I5=${I5:-$SCR/agent_rs_int}
HK=${HK:-$SCR/agent_gd/gin_hk}
LIB=${LIB:-$TAG}
LIBP=${LIBP:-mip${LIB#mi}}
O=$W/sass_$TAG
X=$O/exact
[ -f "$O/ff_n75.o" ] || { echo "run ff_cmp_mi.sh $TAG first" >&2; exit 1; }
mkdir -p "$X"
RING=$W/nccl-src/docs/examples/09_gin_optimizations/01_ring_exchange/c
DRV="-Xcompiler -Wall,-Wextra,-Werror,-Wno-missing-field-initializers"
for v in h i; do
  base=$HK; [ "$v" = i ] && base=$I5
  rm -rf "$X/inc_$v"; mkdir -p "$X/inc_$v"
  cp -a "$base/build/include/nccl.h" "$base/build/include/nccl_device.h" "$base/build/include/nccl_device" "$X/inc_$v/"
done
cc() {  # cc <variant h|i> <name> <source> [flags]: the other tree's headers, ff_cmp_mi.sh's flags
  local v=$1 n=$2 src=$3; shift 3
  for a in 75 86; do
    nice -n 19 "$CU/nvcc" -std=c++17 -O2 --expt-relaxed-constexpr -gencode=arch=compute_$a,code=sm_$a -isystem "$X/inc_$v" \
      "$@" -c "$src" -o "$X/${n}_$v$a.o" > "$X/${n}_$v$a.log" 2>&1 || { cat "$X/${n}_$v$a.log" >&2; exit 1; }
  done
}
for v in h i; do
  cc "$v" ff "$RSD/ff_ops.cu"
  cc "$v" gin_ts2 "$RSD/../../gin_ts2.cu" $DRV
  cc "$v" gin_mr "$RSD/../../remaining/gin_mr.cu" $DRV
  cc "$v" ring "$RING/main.cu" -I"$RING/../../../common/include"
done
sassText() { "$CU/cuobjdump" -sass "$1"; }
resText() { "$CU/cuobjdump" -res-usage "$1" | grep -E 'Function|REG'; }
for v in h i; do
  pe=0; pd=0
  for p in ff gin_ts2 gin_mr ring; do
    for a in 75 86; do
      sassText "$O/${p}_n$a.o" > "$X/${p}_n$a.sass"
      resText "$O/${p}_n$a.o" > "$X/${p}_n$a.res"
      sassText "$X/${p}_$v$a.o" > "$X/${p}_$v$a.sass"
      resText "$X/${p}_$v$a.o" > "$X/${p}_$v$a.res"
      if cmp -s "$X/${p}_n$a.sass" "$X/${p}_$v$a.sass" && cmp -s "$X/${p}_n$a.res" "$X/${p}_$v$a.res"; then
        pe=$((pe + 1))
        echo "program $p sm_$a vs $v: SASS and resources identical ($(grep -cE '^\s+/\*[0-9a-f]{4,}\*/' "$X/${p}_$v$a.sass") instructions, $(grep -c Function "$X/${p}_$v$a.sass") functions, $(wc -l < "$X/${p}_$v$a.sass") lines)"
      else
        pd=$((pd + 1))
        echo "program $p sm_$a vs $v: DIFFERENT: $(diff "$X/${p}_$v$a.sass" "$X/${p}_n$a.sass" | grep -c '^[<>]') SASS lines, res $(cmp -s "$X/${p}_n$a.res" "$X/${p}_$v$a.res" && echo same || echo different)"
      fi
    done
  done
  echo "programs vs $([ "$v" = h ] && echo hk || echo i5): identical $pe, different $pd (program x architecture)"
done
mask() { sed -E 's/(_INTERNAL_|__nv_static_[0-9]+__|__N__)[0-9a-f]{8}_/\1H_/g; s/_cu_[0-9a-f]{8}_[0-9]+/_cu_H/g'; }
export CU X
sum1() {  # sum1 <build dir> <rel>: "<rel> <md5 of the whole SASS dump> <md5 with the compile hash masked>"
  local d=$1 rel=$2 t
  t=$(mktemp -p "$X")
  "$CU/cuobjdump" -sass "$d/$rel" > "$t" 2>/dev/null
  echo "$rel $(md5sum < "$t" | cut -c1-32) $(sed -E 's/(_INTERNAL_|__nv_static_[0-9]+__|__N__)[0-9a-f]{8}_/\1H_/g; s/_cu_[0-9a-f]{8}_[0-9]+/_cu_H/g' "$t" | md5sum | cut -c1-32)"
  rm -f "$t"
}
export -f sum1
sums() {  # sums <build dir> <out file>: every device object's dump digests, 8 at a time (each dump is read once)
  (cd "$1" && find obj/device obj/diagnostics/device -name '*.o' | LC_ALL=C sort) |
    nice -n 19 xargs -P 8 -I{} bash -c 'sum1 "$0" "$1"' "$1" {} | LC_ALL=C sort > "$2"
}
objs() {  # objs <label> <our digests> <their digests>
  local lab=$1 ours=$2 theirs=$3 le=0 lh=0 ld=0 lm=0 rel a am b bm
  while read -r rel a am; do
    b=$(awk -v r="$rel" '$1 == r {print $2; exit}' "$theirs"); bm=$(awk -v r="$rel" '$1 == r {print $3; exit}' "$theirs")
    if [ -z "$b" ]; then lm=$((lm + 1)); echo "library $lab: missing there: $rel"; continue; fi
    if [ "$a" = "$b" ]; then le=$((le + 1)); continue; fi
    if [ "$am" = "$bm" ]; then lh=$((lh + 1)); echo "library $lab: equal once the compile hash is masked: $rel"; continue; fi
    ld=$((ld + 1)); echo "library $lab: DIFFERENT: $rel"
  done < "$ours"
  echo "library $lab device objects: identical $le, identical with the hash masked $lh, different $ld, missing there $lm"
}
sums "$W/build" "$X/obj_mi.txt"
sums "$W/build-mip" "$X/obj_mip.txt"
sums "$I5/build" "$X/obj_i5.txt"
sums "$I5/build-rsp" "$X/obj_i5p.txt"
sums "$HK/build" "$X/obj_hk.txt"
sums "$HK/build-hkp" "$X/obj_hkp.txt"
objs "research vs i5" "$X/obj_mi.txt" "$X/obj_i5.txt"
objs "production vs i5" "$X/obj_mip.txt" "$X/obj_i5p.txt"
objs "research vs hk" "$X/obj_mi.txt" "$X/obj_hk.txt"
objs "production vs hk" "$X/obj_mip.txt" "$X/obj_hkp.txt"
libres() {  # libres <label> <ours> <theirs>
  local lab=$1 a=$2 b=$3
  [ -f "$a" ] || { echo "library $lab: $a missing"; return 0; }
  local x y
  x=$("$CU/cuobjdump" -res-usage "$b" | grep -E 'Function|REG' | mask | md5sum)
  y=$("$CU/cuobjdump" -res-usage "$a" | grep -E 'Function|REG' | mask | md5sum)
  echo "library $lab resource usage (names with the hash masked): $([ "$x" = "$y" ] && echo identical || echo DIFFERENT)"
}
libres "$LIB vs i5" "$W/out/$LIB/libnccl.so.2.32.3" "$I5/build/lib/libnccl.so.2.32.3"
libres "$LIBP vs i5" "$W/out/$LIBP/libnccl.so.2.32.3" "$I5/build-rsp/lib/libnccl.so.2.32.3"
libres "$LIB vs hk" "$W/out/$LIB/libnccl.so.2.32.3" "$HK/build/lib/libnccl.so.2.32.3"
libres "$LIBP vs hk" "$W/out/$LIBP/libnccl.so.2.32.3" "$HK/build-hkp/lib/libnccl.so.2.32.3"
