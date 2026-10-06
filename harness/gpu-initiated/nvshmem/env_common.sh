#!/usr/bin/env bash
# env_common.sh - NVSHMEM IBGDA environment shared by all runs, sourced by the
# runner. Emits the env for one node. Usage: node_env <rain|sunny>
#
# rain  = PE0 = initiator, RoCE dev mlx5_1, RoCE v2 IPv4 GID index 4.
# sunny = PE1 = target,    RoCE dev mlx5_0, RoCE v2 IPv4 GID index 3.
# Both use the management NIC eno1 for NVSHMEM's own unique-id bootstrap so that
# control traffic stays off the shared RoCE link.

BUNDLE=${BUNDLE:-$HOME/gi-bundle/nvshmem}
CUDA_HOME=${CUDA_HOME:-/usr/local/cuda-12.8}

# Common IBGDA knobs. IB_TIMEOUT is overridden per batch (14 for trials).
common_env() {
  cat <<EOF
export LD_LIBRARY_PATH=$BUNDLE/lib:$CUDA_HOME/lib64:\${LD_LIBRARY_PATH:-}
export NVSHMEM_IB_ENABLE_IBGDA=1
export NVSHMEM_IBGDA_NIC_HANDLER=${NIC_HANDLER:-auto}
# NIC control buffers (CQ/WQ/dbr) location: gpumem (default) or hostmem. Used by
# the diagnostic to test whether an error CQE appears in a host-memory CQ.
export NVSHMEM_IBGDA_FORCE_NIC_BUF_MEMTYPE=${NVSHMEM_IBGDA_FORCE_NIC_BUF_MEMTYPE:-gpumem}
# QA A/B: 1 (default, stock) collapsed CQ; 0 = normal ring CQ. Set on BOTH nodes.
export NVSHMEM_IBGDA_FAULT_CQ_COLLAPSED=${NVSHMEM_IBGDA_FAULT_CQ_COLLAPSED:-1}
# IBGDA is the ONLY IB transport here. REMOTE_TRANSPORT=none skips the default
# host proxy transport (ibrc), whose plain-ibv_reg_mr heap registration fails on
# this box; IBGDA (gated separately by IB_ENABLE_IBGDA) carries the puts.
export NVSHMEM_REMOTE_TRANSPORT=none
# The whole symmetric heap is registered with the NIC in one shot, and rain's
# BAR1 is only 256 MiB. Two problems in the stock config make the heap too big
# and unregisterable:
#   1. "heapextra" defaults to ~1.28 GiB (256 teams' psync + a 64 MiB coalescing
#      buffer). Shrink it with few teams and small G buffers (G_COALESCING must
#      equal G_BUF*16).
#   2. A CUDA-VMM heap's VA is reported as non-device by cudaPointerGetAttributes
#      on this driver, so NVSHMEM registers it with plain ibv_reg_mr (which fails
#      on VMM memory) instead of dmabuf. Use DISABLE_CUDA_VMM=1 so the heap is a
#      cudaMalloc region (reported as device -> registered with ibv_reg_dmabuf_mr,
#      which works here), and set CUMEM_GRANULARITY to 2 MiB (the static heap
#      otherwise rounds up to a 512 MiB granularity).
# Net: heap = SYMMETRIC_SIZE(16M) + ~heapextra, well under 64 MiB.
export NVSHMEM_DISABLE_CUDA_VMM=1
export NVSHMEM_CUMEM_GRANULARITY=2097152
export NVSHMEM_MAX_TEAMS=4
export NVSHMEM_G_BUF_SIZE=262144
export NVSHMEM_G_COALESCING_BUF_SIZE=4194304
export NVSHMEM_IBGDA_NUM_RC_PER_PE=1
export NVSHMEM_IBGDA_RC_MAP_BY=none
export NVSHMEM_IBGDA_NUM_DCI=1
export NVSHMEM_SYMMETRIC_SIZE=16M
export NVSHMEM_BOOTSTRAP_UID_SOCK_IFNAME=eno1
export NVSHMEM_IB_ADDR_FAMILY=AF_INET
export NVSHMEM_DEBUG=${NVSHMEM_DEBUG:-INFO}
export NVSHMEM_IB_TIMEOUT=${NVSHMEM_IB_TIMEOUT:-14}
export NVSHMEM_IB_RETRY_CNT=${NVSHMEM_IB_RETRY_CNT:-7}
EOF
}

node_env() {
  common_env
  case "$1" in
    rain)  echo 'export NVSHMEM_HCA_LIST=mlx5_1:1'; echo 'export NVSHMEM_ENABLE_NIC_PE_MAPPING=1'; echo 'export NVSHMEM_IB_GID_INDEX=4' ;;
    sunny) echo 'export NVSHMEM_HCA_LIST=mlx5_0:1'; echo 'export NVSHMEM_ENABLE_NIC_PE_MAPPING=1'; echo 'export NVSHMEM_IB_GID_INDEX=3' ;;
  esac
}
