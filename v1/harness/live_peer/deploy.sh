#!/usr/bin/env bash
# deploy.sh - build and deploy the live_peer binaries (EXPERIMENT.md section 9). Run it inside
# harness/gpu-initiated/common/cluster_run.sh -w 10800 -t lp-deploy -- ...
# Nothing existing is overwritten: every target directory is new for this study.
#   evrec (with -s/-c samples)        -> ~/gi-bundle/evrec2/evrec            (rain, sunny)
#   gin_rec with the stall switch     -> ~/gi-bundle/gin_recovery_gpudb_stall (rain, sunny), with the
#                                        unchanged libnccl of the v2 bundle (md5 1ed8e0a1...)
#   CPU harness source + build        -> sunny ~/rdma-error-lp/harness (run.sh syncs and rebuilds it per
#                                        trial; rain builds in this worktree)
# Prints md5 of every deployed binary on both nodes.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
H=$(cd "$HERE/.." && pwd)
G=$H/gpu-initiated
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
LIB=$SCR/gi/gin_recovery/build_gpudb/lib/libnccl.so.2.32.3
BIN=$SCR/gi/gin_recovery/gin_rec_stall
NEW_GIN=gi-bundle/gin_recovery_gpudb_stall
NEW_EV=gi-bundle/evrec2

[ "$(md5sum < "$LIB" | cut -c1-8)" = 1ed8e0a1 ] || { echo "libnccl md5 is not 1ed8e0a1" >&2; exit 1; }
for d in "$NEW_GIN" "$NEW_EV"; do
  [ -e "$HOME/$d" ] && { echo "$HOME/$d exists on rain: not overwriting" >&2; exit 1; }
  ssh -n sunny "[ ! -e ~/$d ]" || { echo "~/$d exists on sunny: not overwriting" >&2; exit 1; }
done

make -s -C "$G/propagation/evrec"
make -s -C "$H"
mkdir -p "$HOME/$NEW_EV"
cp "$G/propagation/evrec/evrec" "$HOME/$NEW_EV/evrec"
ssh -n sunny "mkdir -p ~/$NEW_EV"
scp -q "$HOME/$NEW_EV/evrec" "sunny:$NEW_EV/evrec"

B=$NEW_GIN LIB=$LIB BIN=$BIN bash "$G/gin_recovery/scripts/deploy.sh"

ssh -n sunny "mkdir -p ~/rdma-error-lp/harness"
rsync -a --exclude='results/*' --exclude='/probe_client' --exclude='/probe_server' --exclude='/nccl-integration/' \
  "$H"/ "sunny:rdma-error-lp/harness/"
ssh -n sunny "cd ~/rdma-error-lp/harness && make -s"

echo "== rain"
(cd "$HOME" && md5sum "$NEW_EV/evrec" "$NEW_GIN/gin_rec" "$NEW_GIN/libnccl.so.2.32.3")
md5sum "$H/probe_client" "$H/probe_server" | sed "s#$H/##"
echo "== sunny"
ssh -n sunny "cd ~ && md5sum $NEW_EV/evrec $NEW_GIN/gin_rec $NEW_GIN/libnccl.so.2.32.3 && cd rdma-error-lp/harness && md5sum probe_client probe_server"
