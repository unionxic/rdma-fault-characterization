#!/usr/bin/env bash
# server_link_loop.sh - Auto-restart wrapper for scenario C (link down)
#
# After each iteration:
#   1. Restores the link (ip link set up)
#   2. Re-adds the IP address
#   3. Waits for RoCE GID to repopulate
#   4. Restarts the server
#
# Usage: ./server_link_loop.sh -a 10.0.0.3/24 [server args...]
# Example: sudo ./server_link_loop.sh -a 10.0.0.3/24 -d mlx5_0 -g 3 -I enp1s0f0np0

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER="$SCRIPT_DIR/server"

# Parse our own -a flag, pass the rest to the server
NIC_IP=""
NIC_IFACE="enp1s0f0np0"
DEV_NAME="mlx5_0"
IB_PORT=1
GID_INDEX=3
SERVER_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        -a|--ip)      NIC_IP="$2"; SERVER_ARGS+=("$1" "$2"); shift 2 ;;
        -I|--nic)     NIC_IFACE="$2"; SERVER_ARGS+=("$1" "$2"); shift 2 ;;
        -d|--device)  DEV_NAME="$2"; SERVER_ARGS+=("$1" "$2"); shift 2 ;;
        -i|--ib-port) IB_PORT="$2"; SERVER_ARGS+=("$1" "$2"); shift 2 ;;
        -g|--gid-index) GID_INDEX="$2"; SERVER_ARGS+=("$1" "$2"); shift 2 ;;
        *)            SERVER_ARGS+=("$1"); shift ;;
    esac
done

if [ -z "$NIC_IP" ]; then
    echo "ERROR: -a <ip/mask> is required (e.g. -a 10.0.0.3/24)"
    exit 1
fi

GID_PATH="/sys/class/infiniband/${DEV_NAME}/ports/${IB_PORT}/gids/${GID_INDEX}"

restore_network() {
    echo "[LOOP] Restoring network..."

    # Bring link up
    ip link set "$NIC_IFACE" up 2>/dev/null

    # Wait for link UP
    for i in $(seq 1 15); do
        if ip link show "$NIC_IFACE" | grep -q "state UP"; then
            echo "[LOOP] Link UP after ${i}s"
            break
        fi
        sleep 1
    done

    # Remove and re-add IP to force GID regeneration
    ip addr del "$NIC_IP" dev "$NIC_IFACE" 2>/dev/null
    sleep 1
    ip addr add "$NIC_IP" dev "$NIC_IFACE" 2>/dev/null

    # Wait for GID to repopulate
    echo "[LOOP] Waiting for GID[$GID_INDEX] to repopulate..."
    for i in $(seq 1 20); do
        GID=$(cat "$GID_PATH" 2>/dev/null)
        if [ -n "$GID" ] && [ "$GID" != "0000:0000:0000:0000:0000:0000:0000:0000" ]; then
            echo "[LOOP] GID[$GID_INDEX] = $GID (restored after ${i}s)"
            return 0
        fi
        sleep 1
    done

    echo "[LOOP] WARNING: GID still empty after 20s"
    return 1
}

trap 'echo "[LOOP] Stopping..."; exit 0' INT TERM

echo "[LOOP] Server link-down loop wrapper started"
echo "[LOOP] NIC=$NIC_IFACE IP=$NIC_IP DEV=$DEV_NAME GID_INDEX=$GID_INDEX"

while true; do
    # Ensure network is good before starting server
    restore_network
    if [ $? -ne 0 ]; then
        echo "[LOOP] Network restore failed, retrying in 5s..."
        sleep 5
        continue
    fi

    sleep 1
    echo "[LOOP] Starting server..."
    "$SERVER" "${SERVER_ARGS[@]}"
    EXIT_CODE=$?
    echo "[LOOP] Server exited with code $EXIT_CODE"

    sleep 1
done
