#!/usr/bin/env bash
# build_rs_spare.sh - build gin-restore's restore layer with work package 8 (the spare process) on rain, in the spare
# branch's own scratch tree agent_rs_spare/ only, and run the spare CPU unit test. A thin wrapper around the NCCL make:
# build_rs.sh (unmodified) checks the working tree changes exactly its RS_FILES, which work package 8 extends with
# bootstrap.cc, init.cc, transport/net_ib/gin.cc, dev_runtime.cc and the new src/misc/rs_spike.cc, src/include/rs_spike.h;
# this wrapper builds that tree instead. No GPU or RDMA program runs here; nothing outside agent_rs_spare/ is written.
# usage: build_rs_spare.sh <rs|rsp|unit|unit1|info>
#   rs/rsp  research / production (-DNCCL_GIN_TS_PRODUCTION) build into agent_rs_spare/{build,build-rsp} ->
#           agent_rs_spare/out/{rs_spare,rsp_spare}/libnccl.so.2.32.3 (sm_75 and sm_86; a folder that already holds a build
#           is refused: give a new name with RSOUT=/RSPOUT=).
#   unit    the spare CPU unit test: the region between the two "gin-restore (rs, work package 8, spare branch): pure
#           functions" markers of gin_host_gdaki.cc is cut into rs_spare_pure.inc and compiled with impl/rs_spare_unit.cc
#           (g++, no NCCL, no CUDA, no network), then run.
#   unit1   work packages 1-4's test impl/rs_unit.cc against this tree's "gin-restore: pure functions" region (the Resume
#           local check gains a condition here; the earlier conditions and their order must still pass).
#   info    agent_rs_spare/out/build_info_spare.txt: md5 of every output and input.
# All compiles run at nice 19 and idle I/O priority (other studies use this node).
set -euo pipefail
STAGE=${1:?stage}
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
D=$(cd "$(dirname "$0")" && pwd)
CUDA=/usr/local/cuda-12.8
GENCODE="-gencode=arch=compute_75,code=sm_75 -gencode=arch=compute_86,code=sm_86"
JOBS=${JOBS:-8}
RSOUT=${RSOUT:-rs_spare}
RSPOUT=${RSPOUT:-rsp_spare}
W=$SCR/agent_rs_spare
OUT=$W/out
HOSTF=src/transport/net_ib/gdaki/gin_host_gdaki.cc
md5() { md5sum < "$1" | cut -c1-32; }
MKS() { local b=$1; shift; nice -n 19 ionice -c3 make -j"$JOBS" -C "$W/nccl-src" src.build BUILDDIR="$b" \
          CUDA_HOME=$CUDA NVCC_GENCODE="$GENCODE" "$@"; }
fresh() { [ ! -e "$1/libnccl.so.2.32.3" ] || { echo "$1 already holds a build; give a new folder name" >&2; exit 1; }; mkdir -p "$1"; }
rs() {
  fresh "$OUT/$RSOUT"
  MKS "$W/build"
  cp "$W/build/lib/libnccl.so.2.32.3" "$OUT/$RSOUT/"
  echo "$RSOUT libnccl $(md5 "$OUT/$RSOUT/libnccl.so.2.32.3")"
}
rsp() {
  fresh "$OUT/$RSPOUT"
  CXXFLAGS=-DNCCL_GIN_TS_PRODUCTION MKS "$W/build-rsp"
  cp "$W/build-rsp/lib/libnccl.so.2.32.3" "$OUT/$RSPOUT/"
  diff -r -q "$W/build/include" "$W/build-rsp/include" > /dev/null ||
    { echo "the production build's headers differ from the research build's" >&2; exit 1; }
  echo "$RSPOUT libnccl $(md5 "$OUT/$RSPOUT/libnccl.so.2.32.3")"
}
unit() {
  local o=$OUT/unit_spare src=$W/nccl-src/$HOSTF
  mkdir -p "$o"
  awk '/^\/\/ ==== gin-restore \(rs, work package 8, spare branch\): pure functions \(begin/{on=1} on{print} /^\/\/ ==== gin-restore \(rs, work package 8, spare branch\): pure functions \(end/{on=0}' \
    "$src" > "$o/rs_spare_pure.inc"
  [ -s "$o/rs_spare_pure.inc" ] || { echo "no spare pure-function region in $HOSTF" >&2; exit 1; }
  # also packages 1-4's region, for the Resume local check this package changes (its other functions are unused here)
  awk '/^\/\/ ---- gin-restore: pure functions \(begin/{on=1} on{print} /^\/\/ ---- gin-restore: pure functions \(end/{on=0}' \
    "$src" > "$o/rs_pure.inc"
  nice -n 19 g++ -std=c++17 -O1 -g -Wall -Wextra -Werror -Wno-unused-function -pthread -fsanitize=address,undefined \
    -I"$o" -I"$W/nccl-src/src/include" "$D/rs_spare_unit.cc" -o "$o/rs_spare_unit"
  "$o/rs_spare_unit"
}
unit1() {  # packages 1-4's unit test (impl/rs_unit.cc) against this tree's region, as build_rs.sh unit does for agent_rs
  local o=$OUT/unit1 src=$W/nccl-src/$HOSTF
  mkdir -p "$o"
  awk '/^\/\/ ---- gin-restore: pure functions \(begin/{on=1} on{print} /^\/\/ ---- gin-restore: pure functions \(end/{on=0}' \
    "$src" > "$o/rs_pure.inc"
  [ -s "$o/rs_pure.inc" ] || { echo "no pure-function region in $HOSTF" >&2; exit 1; }
  grep -qxF 'enum { GDAKI_POLICY_FAILFAST = 0, GDAKI_POLICY_HOLD = 1 };' "$src" || { echo "hk's policy enum changed" >&2; exit 1; }
  nice -n 19 g++ -std=c++17 -O1 -g -Wall -Wextra -Werror -pthread -fsanitize=address,undefined -I"$o" \
    -I"$W/nccl-src/src/include" "$D/rs_unit.cc" -o "$o/rs_unit"
  "$o/rs_unit"
}
info() {
  { echo "built=$(date '+%F %T') host=$(hostname -s) g++=$(g++ -dumpfullversion)"
    for b in "$OUT"/*/libnccl.so.2.32.3; do
      [ -f "$b" ] && echo "$(basename "$(dirname "$b")") libnccl $(md5 "$b")"; done
    [ -f "$D/rs_layer_spare.diff" ] && echo "rs_layer_spare.diff $(md5 "$D/rs_layer_spare.diff")"
    echo "host file $HOSTF md5 $(md5 "$W/nccl-src/$HOSTF")"
    [ -f "$OUT/unit_spare/rs_spare_unit" ] && echo "unit: rs_spare_unit.cc $(md5 "$D/rs_spare_unit.cc") rs_spare_pure.inc $(md5 "$OUT/unit_spare/rs_spare_pure.inc")"
  } > "$OUT/build_info_spare.txt"
  cat "$OUT/build_info_spare.txt"
}
case "$STAGE" in
  rs) rs ;; rsp) rsp ;; unit) unit ;; unit1) unit1 ;; info) info ;;
  *) echo "unknown stage $STAGE" >&2; exit 2 ;;
esac
