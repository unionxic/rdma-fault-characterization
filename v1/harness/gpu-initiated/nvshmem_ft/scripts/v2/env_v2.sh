#!/usr/bin/env bash
# env_v2.sh - NVSHMEM IBGDA environment for the v2 runs. Same settings as ../env_ft.sh, but the
# bundle defaults to ~/gi-bundle/nvshmem_ft2 (v2 build) and the v2 knobs are passed through.
# Usage: node_env <rain|sunny>
#   FT (1)            NVSHMEM_IBGDA_FT
#   RING ("")         NVSHMEM_IBGDA_FT_RING_CQ      (v2 A: non-collapsed send CQs + ring walk)
#   BOUNDS ("")       NVSHMEM_IBGDA_FT_BOUNDS       (v2 B: device bounds check of remote ranges)
#   GUARD ("")        NVSHMEM_IBGDA_FT_BOUNDS_GUARD (v2 B: red zone bytes after every allocation)
#   SKIP ("")         NVSHMEM_IBGDA_FT_TEST_SKIP    (v2 C: test-only, skip resync steps)
#   TRIP ("")         NVSHMEM_IBGDA_FT_TEST_TRIP    (v2.1: test-only, ring_d:<n> | ring_d_silent:<n>)
#   CQ_COLLAPSED ("") NVSHMEM_IBGDA_FAULT_CQ_COLLAPSED (hook: 0 = cc=0/oi=0 ring CQ, stock device code)
#   FT_CAPTURE, FT_QUIET, FT_POLL_US, HANDLER, PROXY_SQ_DBR as in ../env_ft.sh
BUNDLE=${BUNDLE:-$HOME/gi-bundle/nvshmem_ft2}
CUDA_HOME=${CUDA_HOME:-/usr/local/cuda-12.8}
common_env() {
  cat <<EOT
export LD_LIBRARY_PATH=$BUNDLE/lib:$CUDA_HOME/lib64:\${LD_LIBRARY_PATH:-}
export NVSHMEM_IB_ENABLE_IBGDA=1
export NVSHMEM_IBGDA_NIC_HANDLER=${HANDLER:-auto}
export NVSHMEM_REMOTE_TRANSPORT=none
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
export NVSHMEM_IBGDA_FT_POLL_US=${FT_POLL_US:-50}
EOT
  # FT=0 means "unset" (flag off exactly as in stock: the variable is not in the environment)
  [ "${FT:-1}" != 0 ] && echo "export NVSHMEM_IBGDA_FT=${FT:-1}"
  [ -n "${RING:-}" ] && echo "export NVSHMEM_IBGDA_FT_RING_CQ=$RING"
  [ -n "${BOUNDS:-}" ] && echo "export NVSHMEM_IBGDA_FT_BOUNDS=$BOUNDS"
  [ -n "${GUARD:-}" ] && echo "export NVSHMEM_IBGDA_FT_BOUNDS_GUARD=$GUARD"
  [ -n "${SKIP:-}" ] && echo "export NVSHMEM_IBGDA_FT_TEST_SKIP=$SKIP"
  [ -n "${TRIP:-}" ] && echo "export NVSHMEM_IBGDA_FT_TEST_TRIP=$TRIP"
  [ -n "${CQ_COLLAPSED:-}" ] && echo "export NVSHMEM_IBGDA_FAULT_CQ_COLLAPSED=$CQ_COLLAPSED"
  [ -n "${FT_CAPTURE:-}" ] && echo "export NVSHMEM_IBGDA_FT_CAPTURE=$FT_CAPTURE"
  [ -n "${FT_QUIET:-}" ] && echo "export NVSHMEM_IBGDA_FT_QUIET=$FT_QUIET"
  [ -n "${PROXY_SQ_DBR:-}" ] && echo "export NVSHMEM_IBGDA_PROXY_SQ_DBR=$PROXY_SQ_DBR"
  true
}
node_env() {
  common_env
  case "$1" in
    rain)  echo 'export NVSHMEM_HCA_LIST=mlx5_1:1'; echo 'export NVSHMEM_ENABLE_NIC_PE_MAPPING=1'; echo 'export NVSHMEM_IB_GID_INDEX=4' ;;
    sunny) echo 'export NVSHMEM_HCA_LIST=mlx5_0:1'; echo 'export NVSHMEM_ENABLE_NIC_PE_MAPPING=1'; echo 'export NVSHMEM_IB_GID_INDEX=3' ;;
  esac
}
