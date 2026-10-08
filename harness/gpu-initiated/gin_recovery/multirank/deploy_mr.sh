#!/usr/bin/env bash
# Deploy the gin-multirank driver built by build_mr.sh to a NEW directory on rain (local) and sunny, never overwriting:
#   $HOME/gi-bundle/gin_ts2/mr/<key>/gin_mr     ($SCR/agent_mr/out/<key>/gin_mr; the driver only)
# libnccl is not copied: the runner takes it from the recovery bundle $HOME/gi-bundle/gin_ts2/<lib>/ (deployed by that
# build's own study). usage: deploy_mr.sh <key> [<lib>] <output file>   (lib defaults to key)
# Refuses if mr/<key>/ already holds a file on either node, or if the recovery bundle <lib> lacks libnccl.so.2 on either
# node. Checks, written to the output file only (never piped): the md5 of the deployed driver on both nodes equals the
# source; ldd of the driver with LD_LIBRARY_PATH=<lib bundle> resolves libnccl inside that bundle, on both nodes; the md5
# of every file of the existing bundle $HOME/gi-bundle/gin_ts2 outside mr/ is the same before and after, on both nodes.
set -euo pipefail
KEY=${1:?key}
if [ $# -ge 3 ]; then LIBK=$2; OUT=$3; else LIBK=$KEY; OUT=${2:?output file}; fi
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
SUNNY_SSH=${SUNNY_SSH:-unionxic@192.0.2.194}
B=gi-bundle/gin_ts2
SRC=$SCR/agent_mr/out/$KEY/gin_mr
[ -x "$SRC" ] || { echo "no driver at $SRC (run build_mr.sh $KEY <tree>)" >&2; exit 1; }
[ -f ~/$B/$LIBK/libnccl.so.2 ] && ssh -n "$SUNNY_SSH" "[ -f $B/$LIBK/libnccl.so.2 ]" || {
  echo "the recovery bundle $B/$LIBK has no libnccl.so.2 on one node" >&2; exit 1; }
existing() { echo "cd ~/$B && find . -path ./mr -prune -o -type f -print | sort | xargs md5sum"; }
BEFORE_L=$(bash -c "$(existing)"); BEFORE_S=$(ssh -n "$SUNNY_SSH" "$(existing)")
if [ -n "$(ls -A ~/$B/mr/$KEY 2>/dev/null)" ] || [ -n "$(ssh -n "$SUNNY_SSH" "ls -A ~/$B/mr/$KEY 2>/dev/null")" ]; then
  echo "$B/mr/$KEY is not empty on one node: refusing to overwrite" >&2; exit 1
fi
mkdir -p ~/$B/mr/$KEY; ssh -n "$SUNNY_SSH" "mkdir -p ~/$B/mr/$KEY"
DST=mr/$KEY/gin_mr
[ ! -e ~/$B/$DST ] || { echo "exists: $DST" >&2; exit 1; }
cp "$SRC" ~/$B/"$DST.tmp" && mv -n ~/$B/"$DST.tmp" ~/$B/"$DST"
ssh -n "$SUNNY_SSH" "[ ! -e $B/$DST ]" || { echo "exists on sunny: $DST" >&2; exit 1; }
scp -q "$SRC" "$SUNNY_SSH:$B/$DST.tmp" && ssh -n "$SUNNY_SSH" "mv -n $B/$DST.tmp $B/$DST && chmod +x $B/$DST"
SRCSUM="$(md5sum < "$SRC" | cut -d' ' -f1)  $DST"
L=$(cd ~/$B && md5sum "$DST"); S=$(ssh -n "$SUNNY_SSH" "cd ~/$B && md5sum $DST")
AFTER_L=$(bash -c "$(existing)"); AFTER_S=$(ssh -n "$SUNNY_SSH" "$(existing)")
{
  echo "== source"; echo "$SRCSUM"; cat "$SCR/agent_mr/out/$KEY/build_info.txt" 2>/dev/null
  echo "== rain"; echo "$L"; echo "== sunny"; echo "$S"
  echo "rain $KEY with $LIBK: $(LD_LIBRARY_PATH=$HOME/$B/$LIBK ldd ~/$B/$DST | grep nccl)"
  ssh -n "$SUNNY_SSH" "echo \"sunny $KEY with $LIBK: \$(LD_LIBRARY_PATH=\$HOME/$B/$LIBK ldd ~/$B/$DST | grep nccl)\""
  echo "rain $LIBK libnccl md5: $(md5sum < ~/$B/$LIBK/libnccl.so.2 | cut -d' ' -f1)"
  ssh -n "$SUNNY_SSH" "echo \"sunny $LIBK libnccl md5: \$(md5sum < $B/$LIBK/libnccl.so.2 | cut -d' ' -f1)\""
  [ "$L" = "$SRCSUM" ] && [ "$S" = "$SRCSUM" ] && echo "deployed md5 == source on both nodes" || echo "DEPLOYED MD5 MISMATCH"
  [ "$BEFORE_L" = "$AFTER_L" ] && [ "$BEFORE_S" = "$AFTER_S" ] && echo "existing bundle unchanged on both nodes ($(echo "$BEFORE_L" | wc -l) files each)" \
    || echo "EXISTING BUNDLE CHANGED"
} > "$OUT"
