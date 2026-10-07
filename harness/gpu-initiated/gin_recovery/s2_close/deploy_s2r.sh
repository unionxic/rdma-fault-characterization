#!/usr/bin/env bash
# Deploy this study's two bundles to NEW directories on rain (local) and sunny, never overwriting a file:
#   $HOME/gi-bundle/gin_ts2/s2r/     this study's libnccl (agent_ts2r) + a copy of the final step-2 driver (d4b1f082)
#   $HOME/gi-bundle/gin_ts2/s2rget/  this study's libnccl + the get-mode driver (agent_ts2r/s2rget/gin_ts2)
# Refuses if a target directory already holds any file. Checks: the md5 of every deployed file on both nodes equals the
# source; ldd of each driver resolves libnccl inside its own bundle; the md5 of every file of the existing bundle
# $HOME/gi-bundle/gin_ts2 (outside s2r/ and s2rget/) is the same before and after, on both nodes.
set -euo pipefail
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
SUNNY_SSH=${SUNNY_SSH:-unionxic@192.0.2.194}
B=gi-bundle/gin_ts2
LIB=$SCR/agent_ts2r/build/lib/libnccl.so.2.32.3
DRV_S2R=$HOME/gi-bundle/gin_ts2/gin_ts2          # the final step-2 driver, copied as is
DRV_GET=$SCR/agent_ts2r/s2rget/gin_ts2
[ "$(md5sum < "$DRV_S2R" | cut -c1-8)" = d4b1f082 ] || { echo "the final driver is not d4b1f082" >&2; exit 1; }
OUT=${1:-/dev/stdout}
existing() {  # md5 of every existing bundle file outside the new directories (one node)
  echo "cd ~/$B && find . -path ./s2r -prune -o -path ./s2rget -prune -o -type f -print | sort | xargs md5sum"
}
BEFORE_L=$(bash -c "$(existing)"); BEFORE_S=$(ssh -n "$SUNNY_SSH" "$(existing)")
for d in s2r s2rget; do
  if [ -n "$(ls -A ~/$B/$d 2>/dev/null)" ] || [ -n "$(ssh -n "$SUNNY_SSH" "ls -A ~/$B/$d 2>/dev/null")" ]; then
    echo "$B/$d is not empty on one node: refusing to overwrite" >&2; exit 1
  fi
done
put() {  # put <src> <dst relative to ~/$B>; the destination must not exist
  [ ! -e ~/$B/"$2" ] || { echo "exists: $2" >&2; exit 1; }
  cp "$1" ~/$B/"$2.tmp" && mv -n ~/$B/"$2.tmp" ~/$B/"$2"
  ssh -n "$SUNNY_SSH" "[ ! -e $B/$2 ]" || { echo "exists on sunny: $2" >&2; exit 1; }
  scp -q "$1" "$SUNNY_SSH:$B/$2.tmp" && ssh -n "$SUNNY_SSH" "mv -n $B/$2.tmp $B/$2"
}
for d in s2r s2rget; do
  mkdir -p ~/$B/$d; ssh -n "$SUNNY_SSH" "mkdir -p ~/$B/$d"
  put "$LIB" "$d/libnccl.so.2.32.3"
  (cd ~/$B/$d && ln -s libnccl.so.2.32.3 libnccl.so.2 && ln -s libnccl.so.2 libnccl.so)
  ssh -n "$SUNNY_SSH" "cd ~/$B/$d && ln -s libnccl.so.2.32.3 libnccl.so.2 && ln -s libnccl.so.2 libnccl.so"
done
put "$DRV_S2R" s2r/gin_ts2
put "$DRV_GET" s2rget/gin_ts2
F="s2r/libnccl.so.2.32.3 s2r/gin_ts2 s2rget/libnccl.so.2.32.3 s2rget/gin_ts2"
SRCSUM=$(printf '%s  s2r/libnccl.so.2.32.3\n%s  s2r/gin_ts2\n%s  s2rget/libnccl.so.2.32.3\n%s  s2rget/gin_ts2\n'   "$(md5sum < "$LIB" | cut -d' ' -f1)" "$(md5sum < "$DRV_S2R" | cut -d' ' -f1)" "$(md5sum < "$LIB" | cut -d' ' -f1)"   "$(md5sum < "$DRV_GET" | cut -d' ' -f1)")
L=$(cd ~/$B && md5sum $F); S=$(ssh -n "$SUNNY_SSH" "cd ~/$B && md5sum $F")
AFTER_L=$(bash -c "$(existing)"); AFTER_S=$(ssh -n "$SUNNY_SSH" "$(existing)")
{
  echo "== source"; echo "$SRCSUM"; echo "== rain"; echo "$L"; echo "== sunny"; echo "$S"
  for d in s2r s2rget; do
    echo "rain $d: $(cd ~/$B/$d && LD_LIBRARY_PATH=$HOME/$B/$d ldd ./gin_ts2 | grep nccl)"
    ssh -n "$SUNNY_SSH" "cd ~/$B/$d && echo \"sunny $d: \$(LD_LIBRARY_PATH=\$HOME/$B/$d ldd ./gin_ts2 | grep nccl)\""
  done
  [ "$L" = "$SRCSUM" ] && [ "$S" = "$SRCSUM" ] && echo "deployed md5 == source on both nodes" || echo "DEPLOYED MD5 MISMATCH"
  [ "$BEFORE_L" = "$AFTER_L" ] && [ "$BEFORE_S" = "$AFTER_S" ] && echo "existing bundle unchanged on both nodes ($(echo "$BEFORE_L" | wc -l) files each)"     || echo "EXISTING BUNDLE CHANGED"
  echo "== existing bundle md5 (rain)"; echo "$AFTER_L"
  echo "== existing bundle md5 (sunny)"; echo "$AFTER_S"
} | tee "$OUT"
