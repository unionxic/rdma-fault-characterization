#!/usr/bin/env bash
#
# config.sh - Environment for Experiment 4: NIC Retry Boundary

# Server B RDMA IP (passive write target)
SERVER_IP="10.0.0.3"

# RDMA device
DEV_NAME="mlx5_0"
IB_PORT=1
GID_INDEX=3
CTRL_PORT=18515

# tc netem applies to this interface (the local RDMA NIC, here = client side)
NIC_IFACE="enp1s0f0np0"

# Sweep parameters
RETRY_VALUES="0 1 3 7"
TIMEOUT_VALUES="8 12 14 17 20"
LOSS_VALUES="1 5 10 50"

# How many writes per netem run, how many kill cycles per kill run
NETEM_WRITES=50
KILL_ITERS=10

# SSH to Server B for kill mode (server_loop.sh wrapper)
# e.g., SERVER_SSH="user@10.0.0.3" or "user@SERVER_224_ADDR"
SERVER_SSH="gustlr@SERVER_224_ADDR"
SERVER_BIN_DIR="/home/gustlr/Desktop/gpu_fault_recovery/01_cpu_baseline/experiment1"   # e.g., "/home/user/gpu_fault_recovery/01_cpu_baseline/experiment1"

RESULTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/results"
