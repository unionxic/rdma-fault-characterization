#!/usr/bin/env bash
# ptx_mk_dev.sh <file> <arch>: PTX of one generated symmetric source of this branch's build (agent_rs_dev, NCCL's device
# flags as makefiles/common.mk; ptx_mk.sh's command with this branch's tree) -> agent_rs_dev/ptx/<name>_<arch>_dev.ptx
set -e
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
R=$SCR/agent_rs_dev; f=$1; a=$2
mkdir -p "$R/ptx"
cd "$R/nccl-src/src/device"
nice -n 19 /usr/local/cuda-12.8/bin/nvcc -ccbin g++ -arch=compute_$a -std=c++17 --expt-extended-lambda -O3 -DNCCL_OS_LINUX \
  -I. -I.. -I"$R/build/include" -I../include -I../include/plugin --compiler-options "-fPIC -fvisibility=hidden" \
  -ptx "$R/build/obj/device/gensrc/symmetric/$f" -o "$R/ptx/${f%.cu}_${a}_dev.ptx"
