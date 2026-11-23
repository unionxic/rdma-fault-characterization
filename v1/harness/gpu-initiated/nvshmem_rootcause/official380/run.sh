#!/usr/bin/env bash
# run.sh - one kill_repro trial: PE 0 on rain (local), PE 1 on sunny (ssh). Run it inside
# cluster_run.sh. Every process is bounded by timeout and reaped by exact name afterwards.
#
#   run.sh <stock|fix> <cpu_host_memory|gpu> <kill 0|1> <trial> <outdir>
#
# stock = unmodified NVSHMEM v3.8.0-0; fix = the same build with only the doorbell-record line
# changed in nvshmem_transport_ibgda.so (see README.md). kill=1 SIGKILLs PE 1 once PE 0 has
# finished iteration KILL_AFTER (default 3). FINALIZE=1 is passed to both PEs (nvshmem_finalize
# at the end under a 30 s watchdog; see kill_repro.cu); the default 0 keeps the old behaviour.
set -u
VAR=$1; HANDLER=$2; KILL=$3; TRIAL=$4; OUT=$5
mkdir -p "$OUT"
B=${NVS_BUNDLE:-$HOME/gi-bundle/nvshmem_off380}   # same path on both nodes; completion_contract uses nvshmem_345
BIN=${NVS_BIN:-nvs_kill_repro}   # cq380 uses nvs_cq_repro
RAIN_MGMT=192.0.2.193
PORT=${PORT:-18317}
ITERS=${ITERS:-40}; BYTES=${BYTES:-262144}; PERIOD_MS=${PERIOD_MS:-250}; HANG_S=${HANG_S:-30}
KILL_AFTER=${KILL_AFTER:-3}; PROC_TIMEOUT=${PROC_TIMEOUT:-150}
CTRS="local_ack_timeout_err req_cqe_error req_cqe_flush_error req_remote_access_errors"
tag=${VAR}_${HANDLER}_kill${KILL}_t${TRIAL}
L0=$OUT/$tag.pe0.log; L1=$OUT/$tag.pe1.log

# RoCE v2 IPv4-mapped GID index of <dev> (it moves after an address re-add).
gid_cmd='d=/sys/class/infiniband/$DEV/ports/1; for i in $(seq 0 15); do
  [ "$(cat $d/gid_attrs/types/$i 2>/dev/null)" = "RoCE v2" ] &&
  grep -q "^0000:0000:0000:0000:0000:ffff:" $d/gids/$i && { echo $i; break; }; done'
GID0=$(DEV=mlx5_1 bash -c "$gid_cmd"); GID1=$(ssh -n sunny "DEV=mlx5_0 bash -c '$gid_cmd'")
[ -n "$GID0" ] && [ -n "$GID1" ] || { echo "no RoCE v2 IPv4 GID (rain=$GID0 sunny=$GID1)" >&2; exit 2; }

node_env() {  # <hca> <gid index>
  cat <<EOF
export LD_LIBRARY_PATH=$B/lib_$VAR:/usr/local/cuda-12.8/lib64
export NVSHMEM_IB_ENABLE_IBGDA=1 NVSHMEM_IBGDA_NIC_HANDLER=$HANDLER NVSHMEM_REMOTE_TRANSPORT=none
export NVSHMEM_HCA_LIST=$1:1 NVSHMEM_ENABLE_NIC_PE_MAPPING=1 NVSHMEM_IB_GID_INDEX=$2 NVSHMEM_IB_ADDR_FAMILY=AF_INET
export NVSHMEM_IB_TIMEOUT=14 NVSHMEM_IB_RETRY_CNT=7
export NVSHMEM_IBGDA_NUM_RC_PER_PE=1 NVSHMEM_IBGDA_RC_MAP_BY=${RC_MAP_BY:-none} NVSHMEM_IBGDA_NUM_DCI=1
export NVSHMEM_DISABLE_CUDA_VMM=1 NVSHMEM_CUMEM_GRANULARITY=2097152 NVSHMEM_SYMMETRIC_SIZE=16M
export NVSHMEM_MAX_TEAMS=4 NVSHMEM_G_BUF_SIZE=262144 NVSHMEM_G_COALESCING_BUF_SIZE=4194304
export NVSHMEM_BOOTSTRAP_UID_SOCK_IFNAME=eno1
export NVSHMEM_DEBUG=INFO NVSHMEM_DEBUG_SUBSYS=ALL
export FINALIZE=${FINALIZE:-0} CQSCAN=${CQSCAN:-0} CQSCAN_HOLD_S=${CQSCAN_HOLD_S:-0}
EOF
}
ctrs() { local d=/sys/class/infiniband/mlx5_1/ports/1/hw_counters c; for c in $CTRS; do printf '%s ' "$(cat $d/$c)"; done; }

pkill -x $BIN 2>/dev/null; ssh -n sunny "pkill -x $BIN; true"
C0=$(ctrs)
ssh -n sunny "$(node_env mlx5_0 "$GID1"); exec timeout -s KILL $PROC_TIMEOUT $B/bin/$BIN 1 $RAIN_MGMT $PORT $ITERS $BYTES $PERIOD_MS $HANG_S" >"$L1" 2>&1 &
SSH_PID=$!
( eval "$(node_env mlx5_1 "$GID0")"
  exec timeout -s KILL "$PROC_TIMEOUT" "$B/bin/$BIN" 0 "$RAIN_MGMT" "$PORT" "$ITERS" "$BYTES" "$PERIOD_MS" "$HANG_S" ) >"$L0" 2>&1 &
PE0_PID=$!

KILL_AT=-
if [ "$KILL" = 1 ]; then
  for _ in $(seq 1200); do
    grep -q "^PE 0 iter $KILL_AFTER:" "$L0" 2>/dev/null && break
    kill -0 $PE0_PID 2>/dev/null || break
    sleep 0.1
  done
  if grep -q "^PE 0 iter $KILL_AFTER:" "$L0"; then
    ssh -n sunny "pkill -9 -x $BIN"; KILL_AT=$(date +%T.%N | cut -c1-12)
    echo "=== runner: SIGKILL PE 1 at $KILL_AT ===" >>"$L0"
  fi
fi
wait $PE0_PID; RC0=$?
wait $SSH_PID; RC1=$?
pkill -x $BIN 2>/dev/null; ssh -n sunny "pkill -x $BIN; true"
C1=$(ctrs)

d=""; set -- $C1; for c0 in $C0; do d="$d$(( $1 - c0 ));"; shift; done
handler=$(grep -m1 -o 'NIC handler will be [^.]*' "$L0" | sed 's/NIC handler will be //')
last=$(grep '^PE 0 ' "$L0" | tail -1)
# variant,handler_env,kill,trial,handler_log,kill_at,pe0_rc,pe1_rc,d_ack_timeout;d_cqe_err;d_flush;d_rem_access,pe0_last
echo "$VAR,$HANDLER,$KILL,$TRIAL,$handler,$KILL_AT,$RC0,$RC1,$d,\"$last\""
