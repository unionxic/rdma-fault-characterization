#!/usr/bin/env bash
# verify_0x81_counter.sh - does an RDMA counter ALONE separate the two 0x81 causes?
#
# The repo docs claim the RETRY_EXC (0x81) pair (server_qp_err vs proc_kill) has
# IDENTICAL RDMA traffic (15 pkts both) and is split only by the TCP sideband
# (FIN vs RST = process liveness). This measures the responder's RDMA port
# counters (rcv/xmit packets) EXTERNALLY over the fault window for both causes.
# If the deltas overlap, the RDMA counter alone cannot distinguish them -> the
# discriminator must be liveness, exactly as the docs say.
set -uo pipefail
SRV_SSH=unionxic@192.0.2.194
SRV_DATA=unionxic@30.0.0.4
DEV=mlx5_0; PORT=1; IFACE=enp23s0f0np0
CDIR=/sys/class/infiniband/$DEV/ports/$PORT/counters
CLIENT_IP=192.0.2.194
N=${N:-5}

rd() { ssh -n "$SRV_DATA" "cat $CDIR/port_rcv_packets $CDIR/port_xmit_packets" 2>/dev/null | tr '\n' ' '; }

echo "fault,trial,rcv_delta,xmit_delta"
for f in retry_server_qp_err retry_proc_kill; do
  for i in $(seq 1 "$N"); do
    ssh -n "$SRV_DATA" 'pkill -f probe_server 2>/dev/null; sleep 0.3'
    ssh -f "$SRV_DATA" "cd ~/rdma-error/harness && timeout 60 ./probe_server -d $DEV -i $PORT -g 3 -p 18580 -I $IFACE >/tmp/probe_srv.log 2>&1"
    sleep 1
    read -r b_r b_x <<< "$(rd)"
    ./probe_client -s "$CLIENT_IP" -d mlx5_1 -i 1 -g 3 -p 18580 -f "$f" -r none -n 1 \
        -o /dev/null >/dev/null 2>&1
    read -r a_r a_x <<< "$(rd)"
    echo "$f,$i,$((a_r-b_r)),$((a_x-b_x))"
  done
done
ssh -n "$SRV_DATA" 'pkill -f probe_server 2>/dev/null; true'
