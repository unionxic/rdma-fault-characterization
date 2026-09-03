#!/usr/bin/env bash
#
# config.sh - Environment configuration for Experiment 3
#
# Sourced by run_experiment.sh. All environment-specific values go here.
# Override any variable via the shell environment before running.

# Server B RDMA IP (fault target, runs the server binary)
SERVER_IP="10.0.0.3"

# RDMA device configuration
DEV_NAME="mlx5_0"
IB_PORT=1
GID_INDEX=3

# TCP control port
CTRL_PORT=18515

# Iterations
ITERATIONS=100

# SSH to Server B (optional: if set, run_experiment.sh auto-starts the
# server binary there; otherwise user starts it manually).
# e.g., SERVER_SSH="user@10.0.0.3" or "user@SERVER_224_ADDR"
SERVER_SSH=""
SERVER_BIN_DIR=""   # e.g., "/home/user/gpu_fault_recovery/01_cpu_baseline/experiment3"

# Output directory
RESULTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/results"
