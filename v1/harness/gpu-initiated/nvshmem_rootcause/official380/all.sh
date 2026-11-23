#!/usr/bin/env bash
# all.sh - the official-3.8.0 matrix. Run it inside cluster_run.sh:
#   cluster_run.sh -t off380 -- timeout -s KILL 1500 bash all.sh <outdir>
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=$1; mkdir -p "$OUT"
{
  date '+%F %T %Z'
  for h in rain sunny; do
    echo "== $h"
    cmd='hostname -s; uname -r; ofed_info -s; nvidia-smi --query-gpu=name,driver_version --format=csv,noheader;
         grep -h . /etc/modprobe.d/nvidia-peermapping.conf 2>/dev/null; grep -h RegistryDwords /proc/driver/nvidia/params;
         for d in /sys/class/infiniband/mlx5_*; do echo "$(basename $d) fw $(cat $d/fw_ver)"; done'
    if [ $h = rain ]; then bash -c "$cmd"; else ssh -n sunny "$cmd"; fi
  done
  md5sum "$HOME"/gi-bundle/nvshmem_off380/lib_*/nvshmem_transport_ibgda.so.* "$HOME"/gi-bundle/nvshmem_off380/bin/*
} >"$OUT/env.txt" 2>&1

CSV=$OUT/trials.csv
echo "variant,handler_env,kill,trial,handler_log,kill_at,pe0_rc,pe1_rc,d_ack_timeout;d_cqe_err;d_flush;d_rem_access,pe0_last" >"$CSV"
run() { bash "$HERE/run.sh" "$@" "$OUT" | tee -a "$CSV"; sleep 3; }
run stock cpu_host_memory 0 1
for t in 1 2 3; do
  run stock cpu_host_memory 1 $t
  run stock gpu 1 $t
  run fix cpu_host_memory 1 $t
done
run fix cpu_host_memory 0 1
