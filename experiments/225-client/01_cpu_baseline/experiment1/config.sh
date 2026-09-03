#!/usr/bin/env bash
#
# config.sh - Environment configuration for Experiment 1
#
# Copy this file and fill in your values.
# This file is sourced by run_experiment.sh.
#
# IMPORTANT: Never hardcode IPs or device names in source code.
#            All environment-specific values go here.

# ================================================================
# Required: Server B IP address (RDMA-reachable)
# ================================================================
SERVER_IP="10.0.0.4"   # <-- Change to Server B's IP

# ================================================================
# RDMA device configuration
# ================================================================
DEV_NAME="mlx5_0"       # IB device name (ibv_devinfo to list)
IB_PORT=1               # IB port number
GID_INDEX=3             # GID index for RoCEv2 (verify with show_gids)

# ================================================================
# Control channel
# ================================================================
CTRL_PORT=18515          # TCP port for out-of-band control

# ================================================================
# NIC interface (for scenario C: link down)
# ================================================================
NIC_IFACE="enp1s0f0np0" # Network interface name on Server B

# ================================================================
# Experiment parameters
# ================================================================
ITERATIONS=100           # Iterations per scenario
SCENARIOS="a"            # Comma-separated: a,b,c
                         #   a = QP->ERR transition
                         #   b = Remote process kill
                         #   c = Link down (needs root)

# ================================================================
# Remote server management (for scenarios b and c)
# ================================================================
# SSH target for Server B (must have key-based auth)
SERVER_SSH=""             # e.g., "user@10.0.0.4" or "user@mgmt-server-b"

# Path to experiment1/ directory on Server B
SERVER_BIN_DIR=""         # e.g., "/home/user/gpu_fault_recovery/01_cpu_baseline/experiment1"

# ================================================================
# Output
# ================================================================
RESULTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/results"
