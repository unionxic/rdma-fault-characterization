#!/usr/bin/env bash
# Deploy this study's bundles to NEW directories on rain (local) and sunny, never overwriting a file:
#   $HOME/gi-bundle/gin_ts2/hf/    the research libnccl (agent_ts2hf/out/hf) + this study's driver (agent_ts2hf/out/drv)
#   $HOME/gi-bundle/gin_ts2/hfp/   the production libnccl (agent_ts2hf/out/hfp, same source) + the same driver
# The hd and hdp bundles of gin-harden are used as they are (control and latency cells) and are not touched.
# Refuses if either directory already holds any file, or if a source file is not the expected build (md5 prefixes
# below, recorded in EXPERIMENT.md 5). Checks: the md5 of every deployed file on both nodes equals the source; ldd of each
# driver resolves libnccl inside its bundle; the md5 of every file of the existing bundle $HOME/gi-bundle/gin_ts2 (outside
# the two new directories) is the same before and after, on both nodes (another study deploying at the same moment would
# show up there as a change: then compare by hand).
# usage: deploy_hf.sh <check file>   (the check is written to that file only; never pipe it)
set -euo pipefail
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
SUNNY_SSH=${SUNNY_SSH:-unionxic@192.0.2.194}
B=gi-bundle/gin_ts2
OUT=${1:?output file (the check is written to a file only; never pipe it)}
H=$SCR/agent_ts2hf/out
declare -A LIB DRV WANT_LIB
LIB[hf]=$H/hf/libnccl.so.2.32.3;   DRV[hf]=$H/drv/gin_ts2
LIB[hfp]=$H/hfp/libnccl.so.2.32.3; DRV[hfp]=$H/drv/gin_ts2
WANT_LIB[hf]=${WANT_HF:?WANT_HF=<md5 prefix of out/hf, EXPERIMENT.md 5>}
WANT_LIB[hfp]=${WANT_HFP:?WANT_HFP=<md5 prefix of out/hfp, EXPERIMENT.md 5>}
WANT_DRV=${WANT_DRV:?WANT_DRV=<md5 prefix of out/drv/gin_ts2, EXPERIMENT.md 5>}
DIRS="hf hfp"
for d in $DIRS; do
  [ -f "${LIB[$d]}" ] && [ -f "${DRV[$d]}" ] || { echo "missing source for $d" >&2; exit 1; }
  [ "$(md5sum < "${LIB[$d]}" | cut -c1-8)" = "${WANT_LIB[$d]:0:8}" ] || { echo "out/$d is not the expected build" >&2; exit 1; }
  [ "$(md5sum < "${DRV[$d]}" | cut -c1-8)" = "${WANT_DRV:0:8}" ] || { echo "out/drv is not the expected driver" >&2; exit 1; }
done
existing() { echo "cd ~/$B && find . \( -path ./hf -o -path ./hfp \) -prune -o -type f -print | sort | xargs md5sum"; }
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
