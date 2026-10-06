#!/usr/bin/env bash
# Deploy the S2 bundle to ~/gi-bundle/gin_ts2/ on rain (local) and sunny, and check md5s and ldd:
#   libnccl.so.2.32.3 + gin_ts2 + gate_ce_test   the S2 build, its driver, the gate micro-test
#   s1/    the S1 (third-review) libnccl, copied read-only, + gin_ts2 compiled against the S1 tree
#   base/  the gpudb v2 libnccl, copied read-only, + gin_ts2 compiled against the gpudb tree
#   var_sys/  the S2 libnccl + gin_ts2 with the gate atomics at system scope (measurement only)
# The S1 bundle (~/gi-bundle/gin_ts1/) is not touched. File copies over the management network only.
set -euo pipefail
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
SUNNY_SSH=${SUNNY_SSH:-unionxic@192.0.2.194}
B=gi-bundle/gin_ts2
declare -A LIB=( [.]=$SCR/agent_ts2/build/lib/libnccl.so.2.32.3 [s1]=$SCR/agent_ts1/build/lib/libnccl.so.2.32.3
                 [base]=$SCR/gi/gin_recovery/build_gpudb/lib/libnccl.so.2.32.3 [var_sys]=$SCR/agent_ts2/build/lib/libnccl.so.2.32.3 )
declare -A BIN=( [.]=$SCR/agent_ts2/gin_ts2 [s1]=$SCR/agent_ts2/gin_ts2_s1 [base]=$SCR/agent_ts2/gin_ts2_base
                 [var_sys]=$SCR/agent_ts2/var/sys/gin_ts2 )
ssh -n "$SUNNY_SSH" "mkdir -p ~/$B/s1 ~/$B/base ~/$B/var_sys"
# Every file is replaced atomically (copy to a temporary name, then rename): a trial of another bundle directory
# may be running, and a truncating copy over a mapped library or an executing binary would break it.
put() {  # put <src> <dst relative to ~/$B>
  cp -f "$1" ~/$B/"$2.tmp" && mv -f ~/$B/"$2.tmp" ~/$B/"$2"
  scp -q "$1" "$SUNNY_SSH:$B/$2.tmp" && ssh -n "$SUNNY_SSH" "mv -f $B/$2.tmp $B/$2"
}
for d in . s1 base var_sys; do
  mkdir -p ~/$B/$d
  put "${LIB[$d]}" "$d/libnccl.so.2.32.3"; put "${BIN[$d]}" "$d/gin_ts2"
  (cd ~/$B/$d && ln -sf libnccl.so.2.32.3 libnccl.so.2 && ln -sf libnccl.so.2 libnccl.so)
  ssh -n "$SUNNY_SSH" "cd ~/$B/$d && ln -sf libnccl.so.2.32.3 libnccl.so.2 && ln -sf libnccl.so.2 libnccl.so"
done
put $SCR/agent_ts2/gate_ce_test gate_ce_test
put $SCR/agent_ts2/two_streams_test two_streams_test
# the minimal bidirectional program: against the S2 tree (.) and the gpudb tree (base/)
put $SCR/agent_ts2/gin_bidir_min gin_bidir_min
put $SCR/agent_ts2/gin_bidir_min_base base/gin_bidir_min
F="libnccl.so.2.32.3 gin_ts2 gate_ce_test gin_bidir_min s1/libnccl.so.2.32.3 s1/gin_ts2 base/libnccl.so.2.32.3 base/gin_ts2 base/gin_bidir_min var_sys/libnccl.so.2.32.3 var_sys/gin_ts2"
L=$(cd ~/$B && md5sum $F)
S=$(ssh -n "$SUNNY_SSH" "cd ~/$B && md5sum $F")
echo "rain:"; echo "$L"; echo "sunny:"; echo "$S"
[ "$L" = "$S" ] || { echo "md5 mismatch" >&2; exit 1; }
for d in . s1 base var_sys; do
  (cd ~/$B/$d && echo "rain $d: $(LD_LIBRARY_PATH=$HOME/$B/$d ldd ./gin_ts2 | grep nccl)")
  ssh -n "$SUNNY_SSH" "cd ~/$B/$d && echo \"sunny $d: \$(LD_LIBRARY_PATH=\$HOME/$B/$d ldd ./gin_ts2 | grep nccl)\""
done
