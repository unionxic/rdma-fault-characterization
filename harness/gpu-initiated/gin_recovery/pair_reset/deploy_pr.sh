#!/usr/bin/env bash
# Deploy this study's bundles to NEW directories on rain (local) and sunny, never overwriting a file:
#   $HOME/gi-bundle/gin_ts2/pr/    this study's libnccl (agent_ts2pr) + a copy of the final step-2 driver (d4b1f082)
#   $HOME/gi-bundle/gin_ts2/prd/   the same libnccl + the dual-context driver (agent_ts2pr/gin_ts2, ../gin_ts2.cu)
# Refuses if either directory already holds any file. Checks: the md5 of every deployed file on both nodes equals the
# source; ldd of each driver resolves libnccl inside its bundle; the md5 of every file of the existing bundle
# $HOME/gi-bundle/gin_ts2 (outside pr/ and prd/) is the same before and after, on both nodes.
set -euo pipefail
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
SUNNY_SSH=${SUNNY_SSH:-unionxic@192.0.2.194}
B=gi-bundle/gin_ts2
LIB=$SCR/agent_ts2pr/build/lib/libnccl.so.2.32.3
DRV=$HOME/gi-bundle/gin_ts2/gin_ts2          # the final step-2 driver, copied as is
DUAL=$SCR/agent_ts2pr/gin_ts2                # the dual-context driver
[ "$(md5sum < "$DRV" | cut -c1-8)" = d4b1f082 ] || { echo "the final driver is not d4b1f082" >&2; exit 1; }
OUT=${1:-/dev/stdout}
existing() { echo "cd ~/$B && find . \( -path ./pr -o -path ./prd \) -prune -o -type f -print | sort | xargs md5sum"; }
BEFORE_L=$(bash -c "$(existing)"); BEFORE_S=$(ssh -n "$SUNNY_SSH" "$(existing)")
if [ "${CHECK_ONLY:-0}" = 1 ]; then
  # re-check an earlier deployment without copying: "before" is the existing bundle as gin-reconnect's deploy check
  # recorded it after its own deployment (2026-10-08 10:50; rc/ excluded there, so rc/'s two files are added here)
  R=$(cd "$(dirname "$0")" && pwd)/../reconnect/deploy_check.txt
  ref() { awk -v s="$1" '$0 == s {f = 1; next} /^== / {f = 0} f' "$R"
          awk '/^== source/ {f = 1; next} /^== / {f = 0} f' "$R" | sed 's#  rc/#  ./rc/#'; }
  BEFORE_L=$(ref "== existing bundle md5 (rain)" | sort -k2); BEFORE_S=$(ref "== existing bundle md5 (sunny)" | sort -k2)
else
for d in pr prd; do
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
for d in pr prd; do
  mkdir -p ~/$B/$d; ssh -n "$SUNNY_SSH" "mkdir -p ~/$B/$d"
  put "$LIB" $d/libnccl.so.2.32.3
  (cd ~/$B/$d && ln -s libnccl.so.2.32.3 libnccl.so.2 && ln -s libnccl.so.2 libnccl.so)
  ssh -n "$SUNNY_SSH" "cd ~/$B/$d && ln -s libnccl.so.2.32.3 libnccl.so.2 && ln -s libnccl.so.2 libnccl.so"
done
put "$DRV" pr/gin_ts2
put "$DUAL" prd/gin_ts2
fi
F="pr/libnccl.so.2.32.3 pr/gin_ts2 prd/libnccl.so.2.32.3 prd/gin_ts2"
SRCSUM=$(printf '%s  pr/libnccl.so.2.32.3\n%s  pr/gin_ts2\n%s  prd/libnccl.so.2.32.3\n%s  prd/gin_ts2\n' \
  "$(md5sum < "$LIB" | cut -d' ' -f1)" "$(md5sum < "$DRV" | cut -d' ' -f1)" "$(md5sum < "$LIB" | cut -d' ' -f1)" \
  "$(md5sum < "$DUAL" | cut -d' ' -f1)")
L=$(cd ~/$B && md5sum $F); S=$(ssh -n "$SUNNY_SSH" "cd ~/$B && md5sum $F")
AFTER_L=$(bash -c "$(existing)"); AFTER_S=$(ssh -n "$SUNNY_SSH" "$(existing)")
if [ "${CHECK_ONLY:-0}" = 1 ]; then AFTER_L=$(echo "$AFTER_L" | sort -k2); AFTER_S=$(echo "$AFTER_S" | sort -k2); fi
{
  echo "== source"; echo "$SRCSUM"; echo "== rain"; echo "$L"; echo "== sunny"; echo "$S"
  for d in pr prd; do
    echo "rain $d: $(cd ~/$B/$d && LD_LIBRARY_PATH=$HOME/$B/$d ldd ./gin_ts2 | grep nccl)"
    ssh -n "$SUNNY_SSH" "cd ~/$B/$d && echo \"sunny $d: \$(LD_LIBRARY_PATH=\$HOME/$B/$d ldd ./gin_ts2 | grep nccl)\""
  done
  [ "$L" = "$SRCSUM" ] && [ "$S" = "$SRCSUM" ] && echo "deployed md5 == source on both nodes" || echo "DEPLOYED MD5 MISMATCH"
  [ "$BEFORE_L" = "$AFTER_L" ] && [ "$BEFORE_S" = "$AFTER_S" ] && echo "existing bundle unchanged on both nodes ($(echo "$BEFORE_L" | wc -l) files each)" \
    || echo "EXISTING BUNDLE CHANGED"
  echo "== existing bundle md5 (rain)"; echo "$AFTER_L"
  echo "== existing bundle md5 (sunny)"; echo "$AFTER_S"
} | tee "$OUT"
