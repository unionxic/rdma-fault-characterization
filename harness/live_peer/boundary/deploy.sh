#!/usr/bin/env bash
# deploy.sh - prepare the live_boundary run (EXPERIMENT.md section 9). Run it inside
# harness/gpu-initiated/common/cluster_run.sh -w 10800 -t lb-deploy -- ...
#   - builds the CPU harness in this worktree (rain) and copies its source to sunny
#     ~/rdma-error-lb/harness (a new directory of this study), then builds it there;
#     run.sh syncs and rebuilds the same copy before every trial;
#   - checks, without changing anything, the md5 of the reused GIN stall bundle
#     (~/gi-bundle/gin_recovery_gpudb_stall: gin_rec fac97c8c..., libnccl 1ed8e0a1...) and of
#     ~/gi-bundle/evrec2/evrec (3f93b3a9...) on both nodes; exits 1 if any differs.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
H=$(cd "$HERE/../.." && pwd)
WANT="fac97c8c5c558e47ef697c45daeefcfc  gi-bundle/gin_recovery_gpudb_stall/gin_rec
1ed8e0a15dc76fb7cbe672fe463923c3  gi-bundle/gin_recovery_gpudb_stall/libnccl.so.2.32.3
3f93b3a9fa66e9da638bef92d03159de  gi-bundle/evrec2/evrec"
FILES="gi-bundle/gin_recovery_gpudb_stall/gin_rec gi-bundle/gin_recovery_gpudb_stall/libnccl.so.2.32.3 gi-bundle/evrec2/evrec"

make -s -C "$H"
ssh -n sunny "mkdir -p ~/rdma-error-lb/harness"
rsync -a --exclude='results/*' --exclude='/probe_client' --exclude='/probe_server' --exclude='/nccl-integration/' \
  "$H"/ "sunny:rdma-error-lb/harness/"
ssh -n sunny "cd ~/rdma-error-lb/harness && make -s"

R=$(cd "$HOME" && md5sum $FILES)
S=$(ssh -n sunny "cd ~ && md5sum $FILES")
echo "== rain";  echo "$R"; (cd "$H" && md5sum probe_client probe_server)
echo "== sunny"; echo "$S"; ssh -n sunny "cd ~/rdma-error-lb/harness && md5sum probe_client probe_server"
[ "$R" = "$WANT" ] || { echo "rain bundle md5 differs from the pre-registered values" >&2; exit 1; }
[ "$S" = "$WANT" ] || { echo "sunny bundle md5 differs from the pre-registered values" >&2; exit 1; }
echo "bundle md5 ok on both nodes"
