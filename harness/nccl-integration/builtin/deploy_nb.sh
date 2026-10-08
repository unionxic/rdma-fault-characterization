#!/usr/bin/env bash
# Deploy this study's bundles to a NEW directory $HOME/nb-bundle on rain (local) and sunny, never overwriting a file:
#   nb-bundle/n232/  libnccl.so.2.32.3 (build_nb.sh n232: v2.32.3-1 + inject_232.diff) + nb_ct
#   nb-bundle/s2/    libnccl.so.2.23.4 (the Stage 2 build 9ed03e1d) + nb_ct
#   nb-bundle/run/   rank 1's PID file (nbrun.py)
# Refuses if $HOME/nb-bundle already exists on either node. Checks, written to the output file only (never piped):
# the md5 of every deployed file on both nodes equals the source (out/MD5SUMS of build_nb.sh); ldd of nb_ct with each
# bundle's library path resolves libnccl inside that bundle; the md5 of every file of the existing bundles
# ($HOME/gi-bundle on both nodes, $HOME/nccl-ct on sunny) is the same before and after.
# No RDMA traffic and no GPU use: ssh/scp over the management network only.
set -euo pipefail
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
SUNNY_SSH=${SUNNY_SSH:-unionxic@192.0.2.194}
O=$SCR/agent_nb/out
B=nb-bundle
OUT=${1:?output file (the check is written to a file only; never pipe it)}
declare -A SRC=([n232/libnccl.so.2.32.3]=$O/n232/libnccl.so.2.32.3 [n232/nb_ct]=$O/nb_ct
                [s2/libnccl.so.2.23.4]=$O/s2/libnccl.so.2.23.4 [s2/nb_ct]=$O/nb_ct)
# the sources must be the bytes build_nb.sh recorded
(cd "$O" && md5sum -c --quiet MD5SUMS) || { echo "out/ differs from out/MD5SUMS" >&2; exit 1; }
[ "$(md5sum < "$O/s2/libnccl.so.2.23.4" | cut -c1-8)" = 9ed03e1d ] || { echo "s2 library is not 9ed03e1d" >&2; exit 1; }
existing() { echo 'for d in $HOME/gi-bundle $HOME/nccl-ct; do [ -d "$d" ] && find "$d" -type f -print0 | sort -z | xargs -0 md5sum; done; true'; }
BEFORE_L=$(bash -c "$(existing)"); BEFORE_S=$(ssh -n "$SUNNY_SSH" "$(existing)")
if [ -e "$HOME/$B" ] || ssh -n "$SUNNY_SSH" "[ -e \$HOME/$B ]"; then
  echo "\$HOME/$B already exists on one node: refusing to overwrite" >&2; exit 1
fi
put() {  # put <src> <dst relative to $HOME/$B>; the destination must not exist on either node
  [ ! -e "$HOME/$B/$2" ] || { echo "exists: $2" >&2; exit 1; }
  cp "$1" "$HOME/$B/$2.tmp" && mv -n "$HOME/$B/$2.tmp" "$HOME/$B/$2"
  ssh -n "$SUNNY_SSH" "[ ! -e $B/$2 ]" || { echo "exists on sunny: $2" >&2; exit 1; }
  scp -q "$1" "$SUNNY_SSH:$B/$2.tmp" && ssh -n "$SUNNY_SSH" "mv -n $B/$2.tmp $B/$2"
}
mkdir "$HOME/$B" "$HOME/$B/n232" "$HOME/$B/s2" "$HOME/$B/run"
ssh -n "$SUNNY_SSH" "mkdir \$HOME/$B \$HOME/$B/n232 \$HOME/$B/s2 \$HOME/$B/run"
for f in n232/libnccl.so.2.32.3 n232/nb_ct s2/libnccl.so.2.23.4 s2/nb_ct; do put "${SRC[$f]}" "$f"; done
for b in n232 s2; do
  lib=$(cd "$HOME/$B/$b" && ls libnccl.so.2.*)
  (cd "$HOME/$B/$b" && ln -s "$lib" libnccl.so.2 && ln -s libnccl.so.2 libnccl.so)
  ssh -n "$SUNNY_SSH" "cd \$HOME/$B/$b && ln -s $lib libnccl.so.2 && ln -s libnccl.so.2 libnccl.so"
done
F="n232/libnccl.so.2.32.3 n232/nb_ct s2/libnccl.so.2.23.4 s2/nb_ct"
SRCSUM=$(for f in $F; do echo "$(md5sum < "${SRC[$f]}" | cut -d' ' -f1)  $f"; done)
L=$(cd "$HOME/$B" && md5sum $F); S=$(ssh -n "$SUNNY_SSH" "cd \$HOME/$B && md5sum $F")
AFTER_L=$(bash -c "$(existing)"); AFTER_S=$(ssh -n "$SUNNY_SSH" "$(existing)")
{
  echo "== $(date '+%F %T') source"; echo "$SRCSUM"; echo "== rain"; echo "$L"; echo "== sunny"; echo "$S"
  for b in n232 s2; do
    echo "rain $b: $(cd "$HOME/$B/$b" && LD_LIBRARY_PATH=$HOME/$B/$b ldd ./nb_ct | grep nccl)"
    ssh -n "$SUNNY_SSH" "cd \$HOME/$B/$b && echo \"sunny $b: \$(LD_LIBRARY_PATH=\$HOME/$B/$b ldd ./nb_ct | grep nccl)\""
  done
  [ "$L" = "$SRCSUM" ] && [ "$S" = "$SRCSUM" ] && echo "deployed md5 == source on both nodes" || echo "DEPLOYED MD5 MISMATCH"
  [ "$BEFORE_L" = "$AFTER_L" ] && [ "$BEFORE_S" = "$AFTER_S" ] && \
    echo "existing bundles unchanged (rain $(echo "$BEFORE_L" | grep -c .) files, sunny $(echo "$BEFORE_S" | grep -c .) files)" \
    || echo "EXISTING BUNDLE CHANGED"
  echo "== existing bundle md5 (rain)"; echo "$AFTER_L"
  echo "== existing bundle md5 (sunny)"; echo "$AFTER_S"
} > "$OUT"
