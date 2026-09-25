#!/usr/bin/env bash
# drvcfg.sh <out_file> - record the nvidia driver configuration of both nodes (one line per node).
# Reads /proc/driver/nvidia/params and /proc/driver/nvidia/version only (no privileges, no changes).
out=$1
SUNNY_SSH=${SUNNY_SSH:-unionxic@192.0.2.194}
q='v=$(grep -o "Kernel Module for [^ ]*  *[0-9.]*" /proc/driver/nvidia/version | awk "{print \$NF}");
rd=$(sed -n "s/^RegistryDwords: //p" /proc/driver/nvidia/params | tr -d " ");
sm=$(sed -n "s/^EnableStreamMemOPs: //p" /proc/driver/nvidia/params);
echo "node=$(hostname) nvidia=$v RegistryDwords=$rd EnableStreamMemOPs=$sm"'
{
  bash -c "$q"
  ssh -n -o ConnectTimeout=5 "$SUNNY_SSH" "$q" 2>/dev/null || echo "node=sunny query_failed=1"
  echo "time=$(date '+%F %T')"
} > "$out"
