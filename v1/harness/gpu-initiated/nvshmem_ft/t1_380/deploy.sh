#!/usr/bin/env bash
# deploy.sh - put the t1_380 build in a NEW bundle ~/gi-bundle/nvshmem_t1_380 on rain and sunny:
#   lib/, bin/nvt1_drv           the port (official v3.8.0-0 + inject + record knob + transparent recovery)
#   stock380/lib, stock380/bin   unmodified v3.8.0-0 (copied from ~/gi-bundle/nvshmem_off380/lib_stock) and
#                                nvt1st_drv (the driver built against it with -DT1_STOCK)
# Refuses to run if the bundle exists on either node. Every existing bundle file (~/gi-bundle on both
# nodes) is checksummed before and after; any change, missing file or md5 mismatch between the nodes
# is an error. Output: <scratch>/agent_t1_380/deploy/ (manifests) and stdout.
set -eu
SCRATCH=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
W=$SCRATCH/agent_t1_380
OUTD=$W/deploy
NAME=nvshmem_t1_380
B=$HOME/gi-bundle/$NAME
STOCKLIB=$HOME/gi-bundle/nvshmem_off380/lib_stock
mkdir -p "$OUTD"
if [ -e "$B" ]; then echo "REFUSED: $B exists on rain"; exit 1; fi
if ssh -n -o ConnectTimeout=8 sunny "test -e gi-bundle/$NAME"; then echo "REFUSED: gi-bundle/$NAME exists on sunny"; exit 1; fi
manifest_rain() { find "$HOME/gi-bundle" -path "$B" -prune -o -type f -print0 | sort -z | xargs -0 md5sum | sed "s#$HOME/##"; }
manifest_sunny() { ssh -n -o ConnectTimeout=8 sunny "cd \$HOME && find gi-bundle -path gi-bundle/$NAME -prune -o -type f -print0 | sort -z | xargs -0 md5sum"; }
manifest_rain > "$OUTD/before_rain.txt"; manifest_sunny > "$OUTD/before_sunny.txt"
echo "existing bundle files: rain $(wc -l < "$OUTD/before_rain.txt"), sunny $(wc -l < "$OUTD/before_sunny.txt")"
mkdir -p "$B/lib" "$B/bin" "$B/stock380/lib" "$B/stock380/bin"
cp -a "$W"/install/lib/*.so* "$B/lib/"
cp "$W/nvt1_drv" "$B/bin/nvt1_drv"
cp -a "$STOCKLIB"/*.so* "$B/stock380/lib/"
cp "$W/nvt1st_drv" "$B/stock380/bin/nvt1st_drv"
rsync -a "$B/" "sunny:gi-bundle/$NAME/"
L=$(cd "$B" && find . -type f -print0 | sort -z | xargs -0 md5sum)
R=$(ssh -n -o ConnectTimeout=8 sunny "cd gi-bundle/$NAME && find . -type f -print0 | sort -z | xargs -0 md5sum")
echo "$L" > "$OUTD/new_bundle_rain.txt"; echo "$R" > "$OUTD/new_bundle_sunny.txt"
echo "$L"
[ "$L" = "$R" ] && echo "new bundle: md5 match on sunny ($(echo "$L" | wc -l) files)" || { echo "MD5 MISMATCH on sunny"; exit 1; }
manifest_rain > "$OUTD/after_rain.txt"; manifest_sunny > "$OUTD/after_sunny.txt"
for n in rain sunny; do
  bad=$(python3 - "$OUTD/before_$n.txt" "$OUTD/after_$n.txt" <<'PY'
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
  echo "existing bundle files changed or missing on $n: $bad"
  [ "$(echo "$bad" | head -1)" = 0 ] || exit 1
done
echo "DEPLOY OK"
