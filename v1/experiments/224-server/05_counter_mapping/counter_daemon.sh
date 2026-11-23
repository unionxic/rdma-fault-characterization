#!/bin/bash
# counter_daemon.sh — Independent counter snapshot daemon
# Runs on server (224), listens on management IP, survives server.c kill
# Uses socat for reliable TCP listening (install: apt install socat)
#
# Usage: ./counter_daemon.sh [port] [bind_ip]

PORT=${1:-18516}
BIND_IP=${2:-SERVER_224_ADDR}
HW_DIR="/sys/class/infiniband/mlx5_0/ports/1/hw_counters"
PORT_DIR="/sys/class/infiniband/mlx5_0/ports/1/counters"

read_counters() {
    for f in "$HW_DIR"/*; do
        [ -f "$f" ] || continue
        echo "$(basename "$f"),$(cat "$f" 2>/dev/null)"
    done
    for f in "$PORT_DIR"/*; do
        [ -f "$f" ] || continue
        echo "$(basename "$f"),$(cat "$f" 2>/dev/null)"
    done
}

handle_connection() {
    read line
    if [ "$line" = "SNAPSHOT" ] || [ "$line" = "SNAPSHOT\r" ]; then
        read_counters
    fi
}
export -f read_counters handle_connection
export HW_DIR PORT_DIR

echo "Counter daemon listening on ${BIND_IP}:${PORT}"
echo "Using socat (install with: sudo apt install socat)"

exec socat TCP-LISTEN:${PORT},bind=${BIND_IP},reuseaddr,fork EXEC:"bash -c handle_connection"
