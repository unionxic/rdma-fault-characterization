#!/usr/bin/env bash
# Deploy this study's bundles to NEW directories on rain (local) and sunny, never overwriting a file:
#   $HOME/gi-bundle/gin_ts2/pcm/   the reference libnccl (agent_ts2ow/out/pcm: pc + test switches) + the final step-2 driver (d4b1f082)
#   $HOME/gi-bundle/gin_ts2/ow/    this study's libnccl (agent_ts2ow/out/ow) + the same driver
# Refuses if either directory already holds any file. Checks: the md5 of every deployed file on both nodes equals the
# source; ldd of each driver resolves libnccl inside its bundle; the md5 of every file of the existing bundle
# $HOME/gi-bundle/gin_ts2 (outside pcm/ and ow/) is the same before and after, on both nodes.
set -euo pipefail
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
SUNNY_SSH=${SUNNY_SSH:-unionxic@192.0.2.194}
B=gi-bundle/gin_ts2
LIBM=$SCR/agent_ts2ow/out/pcm/libnccl.so.2.32.3
LIBO=$SCR/agent_ts2ow/out/ow/libnccl.so.2.32.3
DRV=$HOME/gi-bundle/gin_ts2/gin_ts2          # the final step-2 driver, copied as is
[ "$(md5sum < "$DRV" | cut -c1-8)" = d4b1f082 ] || { echo "the final driver is not d4b1f082" >&2; exit 1; }
OUT=${1:?output file (the check is written to a file only; never pipe it)}
existing() { echo "cd ~/$B && find . \( -path ./pcm -o -path ./ow \) -prune -o -type f -print | sort | xargs md5sum"; }
BEFORE_L=$(bash -c "$(existing)"); BEFORE_S=$(ssh -n "$SUNNY_SSH" "$(existing)")
for d in pcm ow; do
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
for d in pcm ow; do
  mkdir -p ~/$B/$d; ssh -n "$SUNNY_SSH" "mkdir -p ~/$B/$d"
  [ $d = pcm ] && LIB=$LIBM || LIB=$LIBO
  put "$LIB" $d/libnccl.so.2.32.3
  (cd ~/$B/$d && ln -s libnccl.so.2.32.3 libnccl.so.2 && ln -s libnccl.so.2 libnccl.so)
  ssh -n "$SUNNY_SSH" "cd ~/$B/$d && ln -s libnccl.so.2.32.3 libnccl.so.2 && ln -s libnccl.so.2 libnccl.so"
done
put "$DRV" pcm/gin_ts2
put "$DRV" ow/gin_ts2
F="pcm/libnccl.so.2.32.3 pcm/gin_ts2 ow/libnccl.so.2.32.3 ow/gin_ts2"
SRCSUM=$(printf '%s  pcm/libnccl.so.2.32.3\n%s  pcm/gin_ts2\n%s  ow/libnccl.so.2.32.3\n%s  ow/gin_ts2\n' \
  "$(md5sum < "$LIBM" | cut -d' ' -f1)" "$(md5sum < "$DRV" | cut -d' ' -f1)" "$(md5sum < "$LIBO" | cut -d' ' -f1)" \
  "$(md5sum < "$DRV" | cut -d' ' -f1)")
L=$(cd ~/$B && md5sum $F); S=$(ssh -n "$SUNNY_SSH" "cd ~/$B && md5sum $F")
AFTER_L=$(bash -c "$(existing)"); AFTER_S=$(ssh -n "$SUNNY_SSH" "$(existing)")
{
  echo "== source"; echo "$SRCSUM"; echo "== rain"; echo "$L"; echo "== sunny"; echo "$S"
  for d in pcm ow; do
    echo "rain $d: $(cd ~/$B/$d && LD_LIBRARY_PATH=$HOME/$B/$d ldd ./gin_ts2 | grep nccl)"
    ssh -n "$SUNNY_SSH" "cd ~/$B/$d && echo \"sunny $d: \$(LD_LIBRARY_PATH=\$HOME/$B/$d ldd ./gin_ts2 | grep nccl)\""
  done
  [ "$L" = "$SRCSUM" ] && [ "$S" = "$SRCSUM" ] && echo "deployed md5 == source on both nodes" || echo "DEPLOYED MD5 MISMATCH"
  [ "$BEFORE_L" = "$AFTER_L" ] && [ "$BEFORE_S" = "$AFTER_S" ] && echo "existing bundle unchanged on both nodes ($(echo "$BEFORE_L" | wc -l) files each)" \
    || echo "EXISTING BUNDLE CHANGED"
  echo "== existing bundle md5 (rain)"; echo "$AFTER_L"
  echo "== existing bundle md5 (sunny)"; echo "$AFTER_S"
} > "$OUT"
