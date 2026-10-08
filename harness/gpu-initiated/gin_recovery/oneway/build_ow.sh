#!/usr/bin/env bash
# Build this study's two NCCL libraries on top of the gin-pair-check library tree (agent_ts2pc, libnccl 93d9ffee), leaving
# that tree untouched. usage: build_ow.sh <pcm|ow>
#   once: copy agent_ts2pc's source tree and build directory -> agent_ts2ow; rewrite the absolute paths in the dependency
#         files (*.d) and device manifests and give them back their original mtimes, so that make rebuilds only what
#         changed; commit the pc state in the scratch git repo.
#   pcm:  the reference build = pc + the two test switches (pcm_layer.diff, applied unless the working tree already
#         carries it); incremental make; the library is copied to agent_ts2ow/out/pcm/.
#   ow:   commit the pcm state (once), apply ow_layer.diff (unless the working tree already carries it); incremental make;
#         the library is copied to agent_ts2ow/out/ow/.
# Only transport/net_ib/gdaki/gin_host_gdaki.cc and the version stamp are recompiled (checked with make -n and printed).
# No driver is built: deploy_ow.sh copies the final step-2 driver (d4b1f082) into both bundles.
set -euo pipefail
STAGE=${1:?pcm or ow}
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
SRC=$SCR/agent_ts2pc
DST=$SCR/agent_ts2ow
D=$(cd "$(dirname "$0")" && pwd)
GENCODE="-gencode=arch=compute_75,code=sm_75 -gencode=arch=compute_86,code=sm_86"
G() { git -C "$DST/nccl-src" -c user.name=build -c user.email=build@localhost "$@"; }
if [ ! -d "$DST/nccl-src" ]; then
  mkdir -p "$DST"
  cp -a "$SRC/nccl-src" "$SRC/build" "$DST/"
  (cd "$DST/build" && find . \( -name '*.d' -o -name manifest \) -print0 |
     while IFS= read -r -d '' f; do sed -i "s#$SRC/#$DST/#g" "$f"; touch -h -r "$SRC/build/$f" "$f"; done)
  G commit -qam "gin-pair-check pc (libnccl 93d9ffee)"
fi
[ "${SETUP_ONLY:-0}" = 1 ] && exit 0
head=$(G log -1 --format=%s)
case "$STAGE" in
  pcm)
    case "$head" in "gin-pair-check pc"*) ;; *) echo "the tree is past the pc commit ($head)" >&2; exit 1 ;; esac
    if G diff --quiet HEAD -- src; then G apply "$D/pcm_layer.diff"; fi ;;
  ow)
    case "$head" in
      "gin-pair-check pc"*) G commit -qam "gin-oneway pcm (test switches)" ;;
      "gin-oneway pcm"*) ;;
      *) echo "unexpected head commit ($head)" >&2; exit 1 ;;
    esac
    if G diff --quiet HEAD -- src; then G apply "$D/ow_layer.diff"; fi ;;
  *) echo "unknown stage $STAGE" >&2; exit 2 ;;
esac
echo "to compile: $(make -n -C "$DST/nccl-src" src.build BUILDDIR="$DST/build" CUDA_HOME=/usr/local/cuda-12.8 \
  NVCC_GENCODE="$GENCODE" 2>/dev/null | grep -o -- '-c [^ ]*' | tr '\n' ' ')"
make -j32 -C "$DST/nccl-src" src.build BUILDDIR="$DST/build" CUDA_HOME=/usr/local/cuda-12.8 NVCC_GENCODE="$GENCODE"
mkdir -p "$DST/out/$STAGE"
cp "$DST/build/lib/libnccl.so.2.32.3" "$DST/out/$STAGE/libnccl.so.2.32.3"
md5sum "$DST/out/$STAGE/libnccl.so.2.32.3"
