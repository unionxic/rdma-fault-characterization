#!/usr/bin/env bash
# env_t1.sh - NVSHMEM environment for the T1 runs (same base settings as ../v2/env_v2.sh).
# Usage: node_env <rain|sunny>
#   BUNDLE (~/gi-bundle/nvshmem_t1)   FT (1)   RING (1)   T1 (1): NVSHMEM_IBGDA_FT_TRANSPARENT
#   T1SKIP (""): NVSHMEM_IBGDA_FT_T1_TEST_SKIP      SKIP (""): NVSHMEM_IBGDA_FT_TEST_SKIP
#   HOLD_MS ROUND_MS QUIESCE_MS HANDSHAKE_MS GID_WAIT_MS (library defaults if unset)
#   GID_R / GID_S: NVSHMEM_IB_GID_INDEX on rain / sunny (default 4 / 3: the primary RoCE v2 GIDs)
#   SYM (96M): NVSHMEM_SYMMETRIC_SIZE
BUNDLE=${BUNDLE:-$HOME/gi-bundle/nvshmem_t1}
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
export NVSHMEM_SYMMETRIC_SIZE=${SYM:-96M}
export NVSHMEM_BOOTSTRAP_UID_SOCK_IFNAME=eno1
export NVSHMEM_IB_ADDR_FAMILY=AF_INET
export NVSHMEM_DEBUG=${NVSHMEM_DEBUG:-WARN}
export NVSHMEM_IB_TIMEOUT=${NVSHMEM_IB_TIMEOUT:-14}
export NVSHMEM_IB_RETRY_CNT=${NVSHMEM_IB_RETRY_CNT:-7}
export NVSHMEM_IBGDA_FT_POLL_US=${FT_POLL_US:-50}
EOT
  [ "${FT:-1}" != 0 ] && echo "export NVSHMEM_IBGDA_FT=${FT:-1}"
  [ "${FT:-1}" != 0 ] && [ "${RING:-1}" != 0 ] && echo "export NVSHMEM_IBGDA_FT_RING_CQ=1"
  [ "${FT:-1}" != 0 ] && [ "${T1:-1}" != 0 ] && echo "export NVSHMEM_IBGDA_FT_TRANSPARENT=1"
  [ -n "${T1SKIP:-}" ] && echo "export NVSHMEM_IBGDA_FT_T1_TEST_SKIP=$T1SKIP"
  [ -n "${SKIP:-}" ] && echo "export NVSHMEM_IBGDA_FT_TEST_SKIP=$SKIP"
  [ -n "${HOLD_MS:-}" ] && echo "export NVSHMEM_IBGDA_FT_T1_HOLD_MS=$HOLD_MS"
  [ -n "${ROUND_MS:-}" ] && echo "export NVSHMEM_IBGDA_FT_T1_ROUND_MS=$ROUND_MS"
  [ -n "${QUIESCE_MS:-}" ] && echo "export NVSHMEM_IBGDA_FT_T1_QUIESCE_MS=$QUIESCE_MS"
  [ -n "${HANDSHAKE_MS:-}" ] && echo "export NVSHMEM_IBGDA_FT_T1_HANDSHAKE_MS=$HANDSHAKE_MS"
  [ -n "${GID_WAIT_MS:-}" ] && echo "export NVSHMEM_IBGDA_FT_T1_GID_WAIT_MS=$GID_WAIT_MS"
  true
}
node_env() {
  common_env
  case "$1" in
    rain)  echo 'export NVSHMEM_HCA_LIST=mlx5_1:1'; echo 'export NVSHMEM_ENABLE_NIC_PE_MAPPING=1'; echo "export NVSHMEM_IB_GID_INDEX=${GID_R:-4}" ;;
    sunny) echo 'export NVSHMEM_HCA_LIST=mlx5_0:1'; echo 'export NVSHMEM_ENABLE_NIC_PE_MAPPING=1'; echo "export NVSHMEM_IB_GID_INDEX=${GID_S:-3}" ;;
  esac
}
