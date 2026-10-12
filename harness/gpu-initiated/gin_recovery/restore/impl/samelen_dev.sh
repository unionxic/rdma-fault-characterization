#!/usr/bin/env bash
# samelen_dev.sh <list> - the library device objects that differ from hk's build (exact_cmp_dev.sh), each compiled again
# with NCCL's own command (make -n -B in this branch's tree), once from hk's tree (read only) and once from this tree
# through the symlink agent_rs_dev/ab, whose path has hk's length (agent_gd/gin_hk); their whole SASS dumps (cuobjdump
# -sass, every line) must be identical. Nothing runs; no cluster action. <list>: object paths relative to the build folder,
# one per line. Output: agent_rs_dev/samelen2/ (the objects, dumps and logs) and one line per object on stdout.
# Sequential on purpose: make -n -B remakes the generated sources (gensrc) of this tree's build folder each time, so two at
# once can compile a file that is being rewritten (the cause of the one failed compile in the parallel run of 2026-10-12).
# Side effect: the next build_rs_dev.sh rs rebuilds every generated device object (gensrc is newer).
set -uo pipefail
LIST=${1:?list}
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
W=${RS_TREE:-$SCR/agent_rs_dev}  # integration: RS_TREE=<another scratch tree>
HK=$SCR/agent_gd/gin_hk
E=$W/samelen2
CU=/usr/local/cuda-12.8/bin
mkdir -p "$E"
[ -e "$W/ab" ] || ln -s "$W" "$W/ab"
[ $((${#W} + 3)) -eq "${#HK}" ] || { echo "the symlink's path ($W/ab) is not as long as hk's" >&2; exit 1; }
same=0
diff=0
while IFS= read -r rel; do
  o=$W/build/$rel
  cmd=$(cd "$W/nccl-src/src/device" && make -n -B BUILDDIR="$W/build" CUDA_HOME=/usr/local/cuda-12.8 CXXSTD=-std=c++17 \
        NVCC_GENCODE="-gencode=arch=compute_75,code=sm_75 -gencode=arch=compute_86,code=sm_86" "$o" 2>/dev/null |
        grep -o '/usr/local/cuda-12.8/bin/nvcc [^;]* -dw [^;]*' | head -1)
  [ -n "$cmd" ] || { echo "no command: $rel"; diff=$((diff + 1)); continue; }
  b=$(basename "$rel" .o)
  for t in hk ab; do
    if [ $t = hk ]; then R=$HK; else R=$W/ab; fi
    c=${cmd//$W\//$R\/}
    c=$(echo "$c" | sed -E "s# -o [^ ]+# -o $E/${b}_$t.o#")
    (cd "$R/nccl-src/src/device" && eval nice -n 19 ionice -c 3 $c) > "$E/${b}_$t.log" 2>&1 || echo "FAIL $b $t"
    "$CU/cuobjdump" -sass "$E/${b}_$t.o" > "$E/${b}_$t.sass"
  done
  if cmp -s "$E/${b}_hk.sass" "$E/${b}_ab.sass"; then
    same=$((same + 1))
    echo "same: $rel ($(grep -cE '^\s+/\*[0-9a-f]{4,}\*/' "$E/${b}_hk.sass") instructions, $(wc -l < "$E/${b}_hk.sass") lines)"
  else
    diff=$((diff + 1))
    echo "DIFFERENT: $rel"
  fi
done < "$LIST"
echo "same-length build paths: identical $same, different $diff"
