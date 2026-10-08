#!/usr/bin/env bash
# Build this study's two libraries and its driver into $SCR/agent_nb/out (session scratch only; nothing here touches
# the cluster, an existing bundle, or another scratch tree; the 2.23.4 tree is only read with git show).
#   n232   NCCL v2.32.3-1 + inject_232.diff (test-only fault-injection hook, no recovery). Full build for sm_75, sm_86.
#          The script refuses a tree that is not exactly the upstream tag + that diff.
#   s2     the Stage 2 library 9ed03e1d (../stage2/net_ib_stage2.diff on v2.23.4-1: build a037de42 + the inert F2
#          hook), copied. The script checks that the patch in this repository reproduces the patched net_ib.cc named in
#          the patch header (git hash-object 18d998a8).
#   drv    the Stage 2 driver ../perf/nccl_ct.cu, unchanged, compiled against the 2.23.4 header as nb_ct (a binary
#          built against an older nccl.h runs on a newer libnccl.so.2; one binary serves both libraries).
# usage: build_nb.sh [n232|s2|drv|all]      (default all; JOBS=<make -j> for n232, default 24, run under nice)
set -euo pipefail
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
A=$SCR/agent_nb
D=$(cd "$(dirname "$0")" && pwd)
CUDA=/usr/local/cuda-12.8
GENCODE="-gencode=arch=compute_75,code=sm_75 -gencode=arch=compute_86,code=sm_86"
S2LIB=$SCR/nccl_rkey_build/lib/libnccl.so.2.23.4   # build 9ed03e1d (stage2 NOTES.md)
S2INC=$SCR/nccl_rkey_build/include
N223=$SCR/nccl                                      # NCCL git tree that holds tag v2.23.4-1 (read with git show only)
T=$A/nccl-232
strip() { sed '/^# /d;/^#$/d' "$1"; }
mkdir -p "$A/out/n232" "$A/out/s2"

build_n232() {
  if [ ! -d "$T" ]; then
    git clone -q --depth 1 --branch v2.32.3-1 https://github.com/NVIDIA/nccl "$T"
    (cd "$T" && strip "$D/inject_232.diff" | git apply)
  fi
  git -C "$T" rev-parse -q --verify 'v2.32.3-1^{commit}' >/dev/null || { echo "no tag v2.32.3-1 in $T" >&2; exit 1; }
  if ! cmp -s <(git -C "$T" diff v2.32.3-1 -- src) <(strip "$D/inject_232.diff"); then
    echo "$T/src is not v2.32.3-1 + inject_232.diff: refusing to build" >&2; exit 1
  fi
  echo "tree check: $T/src == v2.32.3-1 ($(git -C "$T" rev-parse --short=12 'v2.32.3-1^{commit}')) + inject_232.diff"
  nice -n 10 make -j"${JOBS:-24}" -C "$T" src.build BUILDDIR="$A/build-n232" CUDA_HOME=$CUDA NVCC_GENCODE="$GENCODE" \
    > "$A/build_n232.log" 2>&1 || { tail -30 "$A/build_n232.log" >&2; exit 1; }
  cp "$A/build-n232/lib/libnccl.so.2.32.3" "$A/out/n232/libnccl.so.2.32.3"
}

build_s2() {
  [ "$(md5sum < "$S2LIB" | cut -c1-8)" = 9ed03e1d ] || { echo "$S2LIB is not build 9ed03e1d" >&2; exit 1; }
  local C=$A/s2check
  rm -rf "$C"; mkdir -p "$C/src/transport"
  git -C "$N223" show v2.23.4-1:src/transport/net_ib.cc > "$C/src/transport/net_ib.cc"
  (cd "$C" && strip "$D/../stage2/net_ib_stage2.diff" | git apply)
  local h; h=$(git hash-object "$C/src/transport/net_ib.cc")
  [ "${h:0:8}" = 18d998a8 ] || { echo "net_ib_stage2.diff gives net_ib.cc $h, not 18d998a8" >&2; exit 1; }
  echo "patch check: v2.23.4-1 net_ib.cc + ../stage2/net_ib_stage2.diff -> git hash-object $h (the header's 18d998a8)"
  cp "$S2LIB" "$A/out/s2/libnccl.so.2.23.4"
}

build_drv() {
  $CUDA/bin/nvcc -O2 $GENCODE -I"$S2INC" -L"$(dirname "$S2LIB")" -o "$A/out/nb_ct" "$D/../perf/nccl_ct.cu" -lnccl
}

case "${1:-all}" in
  n232) build_n232 ;;
  s2) build_s2 ;;
  drv) build_drv ;;
  all) build_s2; build_drv; build_n232 ;;
  *) echo "usage: $0 [n232|s2|drv|all]" >&2; exit 2 ;;
esac
(cd "$A/out" && md5sum $(ls n232/libnccl.so.2.32.3 s2/libnccl.so.2.23.4 nb_ct 2>/dev/null)) | tee "$A/out/MD5SUMS"
