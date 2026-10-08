#!/usr/bin/env bash
# Deploy this study's bundles to NEW directories on rain (local) and sunny, never overwriting a file:
#   $HOME/gi-bundle/gin_ts2/hd/    the research libnccl (agent_ts2hd/out/hd) + this study's driver (agent_ts2hd/out/drv)
#   $HOME/gi-bundle/gin_ts2/hdp/   the production libnccl (agent_ts2hd/out/hdp, same source) + the same driver
#   $HOME/gi-bundle/gin_ts2/ow2/   gin-oneway's libnccl (b4af65c5, agent_ts2ow/out/ow) + the same driver (contrast cells
#                                   that need the new driver: shrink hand-off)
#   $HOME/gi-bundle/gin_ts2/stk/   pristine NCCL v2.32.3-1 (agent_ts2hd/out/stk) + the driver built against it with
#                                   -DGIN_TS_STOCK_API (agent_ts2hd/out/drv-stk)
# Refuses if any of the four directories already holds any file. Checks: the md5 of every deployed file on both nodes
# equals the source; ldd of each driver resolves libnccl inside its bundle; the md5 of every file of the existing bundle
# $HOME/gi-bundle/gin_ts2 (outside the four new directories) is the same before and after, on both nodes.
# usage: deploy_hd.sh <check file>   (the check is written to that file only; never pipe it)
set -euo pipefail
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
SUNNY_SSH=${SUNNY_SSH:-unionxic@192.0.2.194}
B=gi-bundle/gin_ts2
OUT=${1:?output file (the check is written to a file only; never pipe it)}
H=$SCR/agent_ts2hd/out
declare -A LIB DRV
LIB[hd]=$H/hd/libnccl.so.2.32.3;   DRV[hd]=$H/drv/gin_ts2
LIB[hdp]=$H/hdp/libnccl.so.2.32.3; DRV[hdp]=$H/drv/gin_ts2
LIB[ow2]=$SCR/agent_ts2ow/out/ow/libnccl.so.2.32.3; DRV[ow2]=$H/drv/gin_ts2
LIB[stk]=$H/stk/libnccl.so.2.32.3; DRV[stk]=$H/drv-stk/gin_ts2
DIRS="hd hdp ow2 stk"
[ "$(md5sum < "${LIB[ow2]}" | cut -c1-8)" = b4af65c5 ] || { echo "the ow libnccl is not b4af65c5" >&2; exit 1; }
for d in $DIRS; do
  [ -f "${LIB[$d]}" ] && [ -f "${DRV[$d]}" ] || { echo "missing source for $d" >&2; exit 1; }
done
existing() { echo "cd ~/$B && find . \( -path ./hd -o -path ./hdp -o -path ./ow2 -o -path ./stk \) -prune -o -type f -print | sort | xargs md5sum"; }
BEFORE_L=$(bash -c "$(existing)"); BEFORE_S=$(ssh -n "$SUNNY_SSH" "$(existing)")
for d in $DIRS; do
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
F=""
SRCSUM=""
for d in $DIRS; do
  mkdir -p ~/$B/$d; ssh -n "$SUNNY_SSH" "mkdir -p ~/$B/$d"
  put "${LIB[$d]}" $d/libnccl.so.2.32.3
  (cd ~/$B/$d && ln -s libnccl.so.2.32.3 libnccl.so.2 && ln -s libnccl.so.2 libnccl.so)
  ssh -n "$SUNNY_SSH" "cd ~/$B/$d && ln -s libnccl.so.2.32.3 libnccl.so.2 && ln -s libnccl.so.2 libnccl.so"
  put "${DRV[$d]}" $d/gin_ts2
  F="$F $d/libnccl.so.2.32.3 $d/gin_ts2"
  SRCSUM="$SRCSUM$(md5sum < "${LIB[$d]}" | cut -d' ' -f1)  $d/libnccl.so.2.32.3
$(md5sum < "${DRV[$d]}" | cut -d' ' -f1)  $d/gin_ts2
"
done
SRCSUM=$(printf '%s' "$SRCSUM")
# shellcheck disable=SC2086
L=$(cd ~/$B && md5sum $F); S=$(ssh -n "$SUNNY_SSH" "cd ~/$B && md5sum $F")
AFTER_L=$(bash -c "$(existing)"); AFTER_S=$(ssh -n "$SUNNY_SSH" "$(existing)")
{
  echo "== source"; echo "$SRCSUM"; echo "== rain"; echo "$L"; echo "== sunny"; echo "$S"
  for d in $DIRS; do
    echo "rain $d: $(cd ~/$B/$d && LD_LIBRARY_PATH=$HOME/$B/$d ldd ./gin_ts2 | grep nccl)"
    ssh -n "$SUNNY_SSH" "cd ~/$B/$d && echo \"sunny $d: \$(LD_LIBRARY_PATH=\$HOME/$B/$d ldd ./gin_ts2 | grep nccl)\""
  done
  [ "$L" = "$SRCSUM" ] && [ "$S" = "$SRCSUM" ] && echo "deployed md5 == source on both nodes" || echo "DEPLOYED MD5 MISMATCH"
  [ "$BEFORE_L" = "$AFTER_L" ] && [ "$BEFORE_S" = "$AFTER_S" ] && echo "existing bundle unchanged on both nodes ($(echo "$BEFORE_L" | wc -l) files each)" \
    || echo "EXISTING BUNDLE CHANGED"
  echo "== existing bundle md5 (rain)"; echo "$AFTER_L"
  echo "== existing bundle md5 (sunny)"; echo "$AFTER_S"
} > "$OUT"
