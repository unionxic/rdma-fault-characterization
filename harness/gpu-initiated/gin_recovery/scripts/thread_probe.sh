#!/usr/bin/env bash
# thread_probe.sh <binary-name> <max_s> - doorbell-mode indicator that needs no NCCL/DOCA change.
# NCCL starts its GIN progress thread ("NCCL GIN P<dev>-<t>") only when some GDAKI QP needs the
# CPU proxy to ring its doorbell (devHandle->needsProxyProgress). Samples the thread names of the
# running <binary-name> every 0.25 s until it exits (or max_s) and prints one line:
#   probe samples=<n> gin_proxy_thread=<0|1> max_threads=<n>
bin=$1; max=${2:-60}
end=$(( $(date +%s) + max )); pid=""
while [ -z "$pid" ] && [ "$(date +%s)" -lt "$end" ]; do pid=$(pgrep -x "$bin" | head -1); sleep 0.1; done
[ -z "$pid" ] && { echo "probe samples=0 gin_proxy_thread=na max_threads=0"; exit 0; }
n=0; seen=0; maxt=0
while [ -d /proc/$pid ] && [ "$(date +%s)" -lt "$end" ]; do
  names=$(cat /proc/$pid/task/*/comm 2>/dev/null)
  t=$(printf '%s\n' "$names" | grep -c .)
  [ "$t" -gt "$maxt" ] && maxt=$t
  printf '%s\n' "$names" | grep -q '^NCCL GIN P' && seen=1
  n=$((n + 1)); sleep 0.25
done
echo "probe samples=$n gin_proxy_thread=$seen max_threads=$maxt"
