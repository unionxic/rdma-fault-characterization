#!/usr/bin/env bash
#
# config.sh - 3.7s Retry Decomposition Experiment
#
# retry_cnt 0~7 full sweep × timeout {14, 8} under process kill.
# Reveals per-retry interval and firmware backoff pattern.

# Server B RDMA IP (passive write target / fault target)
SERVER_IP="10.0.0.3"

# RDMA device
DEV_NAME="mlx5_0"
IB_PORT=1
GID_INDEX=3
CTRL_PORT=18515

# Sweep parameters — full retry_cnt range, two timeout values
RETRY_VALUES="0 1 2 3 4 5 6 7"
TIMEOUT_VALUES="14 8"

# N=30 per (retry_cnt, timeout) config
KILL_ITERS=30

# Instrumented retry-decomposition client (built locally via make)
CLIENT="${CLIENT:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/client}"

# Experiment 1 server_loop.sh (reused for kill mode)
SERVER_LOOP="${SERVER_LOOP:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../cpu_baseline/experiment1/server_loop.sh}"

# SSH to Server B for remote server management
# Set these before running, e.g.:
#   SERVER_SSH="gustlr@SERVER_224_ADDR"
#   SERVER_BIN_DIR="/home/gustlr/Desktop/gpu_fault_recovery/01_cpu_baseline/experiment1"
SERVER_SSH=""
SERVER_BIN_DIR=""

RESULTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/results"
