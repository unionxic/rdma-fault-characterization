#!/usr/bin/env bash
# mk.sh <tree: hk|rs> <file> <arch>: PTX of one generated symmetric source, NCCL's device flags (makefiles/common.mk)
set -e
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
t=$1; f=$2; a=$3
if [ "$t" = hk ]; then R=$SCR/agent_gd/gin_hk; else R=$SCR/agent_rs; fi
cd "$R/nccl-src/src/device"
nice -n 19 /usr/local/cuda-12.8/bin/nvcc -ccbin g++ -arch=compute_$a -std=c++17 --expt-extended-lambda -O3 -DNCCL_OS_LINUX \
  -I. -I.. -I"$R/build/include" -I../include -I../include/plugin --compiler-options "-fPIC -fvisibility=hidden" \
  -ptx "$R/build/obj/device/gensrc/symmetric/$f" -o "$SCR/agent_rs/sass/ptx/${f%.cu}_${a}_$t.ptx"
