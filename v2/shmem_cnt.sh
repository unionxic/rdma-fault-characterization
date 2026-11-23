#!/bin/bash
# shmem_cnt.sh <reps>: NVSHMEM fault runs on sunny with the port hw_counters that moved during each run (is the cause visible there when the CQE shows only the flush?).
snap() { ssh -o BatchMode=yes sunny 'cd /sys/class/infiniband/mlx5_0/ports/1/hw_counters && grep -H . req_* resp_* local_ack_timeout_err rnr_nak_retry_err out_of_sequence packet_seq_err 2>/dev/null'; }
for cfg in "control:-x BAD=-1 -x THREADS=8" "t1-addr:-x THREADS=1" "t8-addr:-x THREADS=8" "t64-addr:-x THREADS=64" "t1-align:-x THREADS=1 -x KIND=1" "t8-align:-x THREADS=8 -x KIND=1"; do
  for i in $(seq ${1:-3}); do snap > /tmp/shmem_cnt.$$; o=$(./shmem_fault.sh cnt-${cfg%%:*} 1 -x CHECK=1 ${cfg#*:} | grep -oE "QUERY.*|STALL.*" | sed -E 's/ elapsed=.*//' | sort -u | tr '\n' ' ')
    echo "${cfg%%:*} | $o| counters: $(snap | diff /tmp/shmem_cnt.$$ - | awk -F: '/^</{a[$1]=$2} /^>/{sub(/^> /,"",$1); k="< "$1; printf "%s+%d ", $1, $2-a[k]}')"; done
done | sort | uniq -c; rm -f /tmp/shmem_cnt.$$
