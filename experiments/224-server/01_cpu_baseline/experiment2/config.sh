#!/usr/bin/env bash
#
# config.sh - Environment configuration for Experiment 2
#
# Sourced by run_experiment.sh. All environment-specific values go here.
# Override any variable via the shell environment before running.

# ================================================================
# Required: Server B IP address (RDMA-reachable)
# ================================================================
SERVER_IP="10.0.0.4"

# ================================================================
# RDMA device configuration
# ================================================================
DEV_NAME="mlx5_0"
IB_PORT=1
GID_INDEX=3

# ================================================================
# Control channel
# ================================================================
CTRL_PORT=18515

# ================================================================
# NIC interface on Server B (for scenario C: link down)
# ================================================================
NIC_IFACE="enp1s0f0np0"

# ================================================================
# Experiment 2 parameters
# ================================================================
# Sleep intervals in microseconds (space-separated)
SLEEP_VALUES="0 1000 10000 100000 1000000 5000000 10000000"

# Fault scenarios to run (space-separated: a b c)
FAULT_TYPES="a b c"

# Iterations per (sleep, fault) combination
ITERATIONS=30

# ================================================================
# Remote server management (required for scenarios b and c)
# ================================================================
SERVER_SSH=""             # e.g., "user@10.0.0.4"
SERVER_BIN_DIR=""         # e.g., "/home/user/gpu_fault_recovery/01_cpu_baseline/experiment1"
SERVER_NIC_IP=""          # e.g., "10.0.0.4/24" (for link-down recovery)

# ================================================================
# Output
# ================================================================
RESULTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/results"
