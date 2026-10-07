#!/usr/bin/env bash
# deploy.sh - put the t1_close build in a NEW bundle ~/gi-bundle/nvshmem_t1close on rain and sunny:
#   lib/        the t1_close install (*.so*)            bin/        nvt1_drv
#   v22ref/lib  copied from ~/gi-bundle/nvshmem_t1/v22ref/lib (v2.2 libraries, latency baseline)
#   v22ref/bin  nvt1v22_drv copied from the same place
# Refuses to run if the bundle exists on either node. Every existing bundle file (~/gi-bundle on both
# nodes) is checksummed before and after; any change, missing file or md5 mismatch between the
# nodes is an error. Output: <scratch>/agent_t1close/deploy/ (manifests) and stdout.
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
SCRATCH=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
NV=$SCRATCH/agent_nvt1
OUTD=$SCRATCH/agent_t1close/deploy
NAME=${T1C_BUNDLE_NAME:-nvshmem_t1close}
B=$HOME/gi-bundle/$NAME
REF=$HOME/gi-bundle/nvshmem_t1/v22ref
mkdir -p "$OUTD"
if [ -e "$B" ]; then echo "REFUSED: $B exists on rain"; exit 1; fi
if ssh -n -o ConnectTimeout=8 sunny "test -e gi-bundle/$NAME"; then echo "REFUSED: gi-bundle/$NAME exists on sunny"; exit 1; fi
manifest() {  # md5 of every file under ~/gi-bundle except the new bundle, sorted by path
  find "$HOME/gi-bundle" -path "$B" -prune -o -type f -print0 | sort -z | xargs -0 md5sum | sed "s#$HOME/##"
}
manifest > "$OUTD/before_rain.txt"
ssh -n -o ConnectTimeout=8 sunny "cd \$HOME && find gi-bundle -path gi-bundle/$NAME -prune -o -type f -print0 | sort -z | xargs -0 md5sum" > "$OUTD/before_sunny.txt"
echo "existing bundle files: rain $(wc -l < "$OUTD/before_rain.txt"), sunny $(wc -l < "$OUTD/before_sunny.txt")"
mkdir -p "$B/lib" "$B/bin" "$B/v22ref/lib" "$B/v22ref/bin"
cp -a "$NV"/install/lib/*.so* "$B/lib/"
cp "$SCRATCH/agent_t1close/nvt1_drv" "$B/bin/nvt1_drv"
cp -a "$REF"/lib/*.so* "$B/v22ref/lib/"
cp "$REF/bin/nvt1v22_drv" "$B/v22ref/bin/nvt1v22_drv"
rsync -a "$B/" "sunny:gi-bundle/$NAME/"
L=$(cd "$B" && find . -type f -print0 | sort -z | xargs -0 md5sum)
R=$(ssh -n -o ConnectTimeout=8 sunny "cd gi-bundle/$NAME && find . -type f -print0 | sort -z | xargs -0 md5sum")
echo "$L" > "$OUTD/new_bundle_rain.txt"; echo "$R" > "$OUTD/new_bundle_sunny.txt"
echo "$L"
[ "$L" = "$R" ] && echo "new bundle: md5 match on sunny ($(echo "$L" | wc -l) files)" || { echo "MD5 MISMATCH on sunny"; exit 1; }
manifest > "$OUTD/after_rain.txt"
ssh -n -o ConnectTimeout=8 sunny "cd \$HOME && find gi-bundle -path gi-bundle/$NAME -prune -o -type f -print0 | sort -z | xargs -0 md5sum" > "$OUTD/after_sunny.txt"
# every file that existed before must be unchanged (files the other experiment adds meanwhile are ignored)
for n in rain sunny; do
  missing=$(python3 - "$OUTD/before_$n.txt" "$OUTD/after_$n.txt" <<'PY'
import sys
def rd(p):
    d = {}
    for l in open(p):
        h, f = l.rstrip('\n').split('  ', 1)
        d[f] = h
    return d
b, a = rd(sys.argv[1]), rd(sys.argv[2])
bad = [f for f in b if a.get(f) != b[f]]
print(len(bad)); [print(' ', f) for f in bad[:20]]
PY
)
  echo "existing bundle files changed or missing on $n: $missing"
  [ "$(echo "$missing" | head -1)" = 0 ] || exit 1
done
echo "DEPLOY OK"
