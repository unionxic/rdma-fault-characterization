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
# NB: always `pkill -x probe_server` (exact process name). `pkill -f probe_server`
# matches the remote shell running the command itself and kills it.
SRV_SSH=unionxic@192.0.2.194
SRV_DATA=unionxic@30.0.0.4
DEV=mlx5_0; PORT=1; IFACE=enp23s0f0np0
CDIR=/sys/class/infiniband/$DEV/ports/$PORT/counters
CLIENT_IP=192.0.2.194
N=${N:-5}

# RoCE v2 IPv4-mapped GID index per node (same probe as run.sh; indices differ per
# node and can move: rain's went 3 -> 4 by 2026-09-23).
GID_PROBE='d=/sys/class/infiniband/$1/ports/$2
for g in $(ls "$d/gids" | sort -n); do
  [ "$(cat "$d/gid_attrs/types/$g" 2>/dev/null)" = "RoCE v2" ] || continue
  case "$(cat "$d/gids/$g")" in 0000:0000:0000:0000:0000:ffff:*) echo "$g"; exit 0;; esac
done
exit 1'
CGID=$(bash -s -- mlx5_1 1 <<< "$GID_PROBE") || { echo "no RoCE v2 IPv4 GID on mlx5_1" >&2; exit 1; }
SGID=$(ssh "$SRV_DATA" bash -s -- "$DEV" "$PORT" <<< "$GID_PROBE") || { echo "no RoCE v2 IPv4 GID on sunny $DEV" >&2; exit 1; }
echo "# GID index: client mlx5_1=$CGID, server $DEV=$SGID" >&2
FAIL=0

rd() { ssh -n "$SRV_DATA" "cat $CDIR/port_rcv_packets $CDIR/port_xmit_packets" 2>/dev/null | tr '\n' ' '; }

echo "fault,trial,rcv_delta,xmit_delta"
for f in retry_server_qp_err retry_proc_kill; do
  for i in $(seq 1 "$N"); do
    ssh -n "$SRV_DATA" 'pkill -x probe_server 2>/dev/null; sleep 0.3'
    ssh -f "$SRV_DATA" "cd ~/rdma-error/harness && timeout 60 ./probe_server -d $DEV -i $PORT -g $SGID -p 18580 -I $IFACE >/tmp/probe_srv.log 2>&1"
    sleep 1
    read -r b_r b_x <<< "$(rd)"
    crc=0
    ./probe_client -s "$CLIENT_IP" -d mlx5_1 -i 1 -g "$CGID" -p 18580 -f "$f" -r none -n 1 \
        -o /dev/null >/dev/null 2>&1 || crc=$?
    [ "$crc" -eq 0 ] || { echo "# $f trial $i: probe_client exit $crc" >&2; FAIL=1; }
    read -r a_r a_x <<< "$(rd)"
    echo "$f,$i,$((a_r-b_r)),$((a_x-b_x))"
  done
done
ssh -n "$SRV_DATA" 'pkill -x probe_server 2>/dev/null; true'
exit $FAIL
