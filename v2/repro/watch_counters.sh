#!/bin/bash
# Samples every RDMA port counter and NIC statistic of the active mlx5 port twice a second and prints the ones that
# changed, with the time and the number of gin_fault processes on this host (a drop marks a death).
# usage: watch_counters.sh <seconds>
for d in /sys/class/infiniband/*; do grep -q ACTIVE $d/ports/1/state && dev=$(basename $d) && break; done
net=$(ls /sys/class/infiniband/$dev/device/net | head -1); declare -A last; end=$((SECONDS + $1))
while [ $SECONDS -lt $end ]; do
  now=$(date +%s.%N | cut -c1-14)
  while read -r k v; do
    [ "${last[$k]}" = "$v" ] && continue
    [ -n "${last[$k]}" ] && echo "$now $k ${last[$k]} -> $v"
    last[$k]=$v
  done < <(echo "procs $(pgrep -c gin_fault)"
           for f in /sys/class/infiniband/$dev/ports/1/hw_counters/* /sys/class/infiniband/$dev/ports/1/counters/*; do echo "$(basename $f) $(cat $f 2>/dev/null)"; done
           ethtool -S $net 2>/dev/null | sed 's/^ *//; s/: / /' | grep -v '^NIC')
  sleep 0.5
done
