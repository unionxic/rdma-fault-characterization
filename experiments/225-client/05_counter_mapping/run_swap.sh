#!/bin/bash
# run_swap.sh — CX-generation swap for vendor_err measurement.
#
# RUN THIS ON NODE 225 (the responder/server side). ssh only works 225->224,
# so 225 orchestrates: server runs locally on 225 (responder=CX-6), client runs
# on 224 over ssh (requester=CX-5). Same fault scenarios, opposite requester NIC.
# Diffing vendor_err vs the CX-6-requester baseline tells whether codes depend
# on requester NIC generation.
#
#   CLEAN  : 1 2 3 (local SGE-len / lkey / MR-perm) — requester NIC only.
#   AUX    : 5 6  (remote NAK) — requester+responder both flip, interpret w/ care.
#
# Usage:  ./run_swap.sh [num_trials]            # scenarios 1 2 3 5 6
#         ./run_swap.sh [num_trials] <sc>...    # only listed ids
set -u

CLIENT_SSH="gustlr@SERVER_224_ADDR"     # node 224 = requester (CX-5)
CLIENT_DIR="/home/gustlr/Desktop/gpu_fault_recovery/05_counter_mapping"
SERVER_RDMA="10.0.0.2"                   # node 225 RDMA IP (this node) = responder
REQUESTER_NIC="CX5"                      # 224 acting as requester
RESPONDER_NIC="CX6"                      # 225 acting as responder

LOCAL_DIR="$(cd "$(dirname "$0")" && pwd)"
N="${1:-10}"; shift || true
SC=("$@"); [ ${#SC[@]} -eq 0 ] && SC=(1 2 3 5 6)

declare -A NAMES=(
  [1]="LOC_PROT_LEN   (local: SGE length > MR)"
  [2]="LOC_PROT_LKEY  (local: invalid lkey)"
  [3]="LOC_PROT_PERM  (local: MR missing LOCAL_WRITE)"
  [5]="REM_INV_REQ    (remote NAK: no REMOTE_WRITE)"
  [6]="REM_ACCESS_RKEY(remote NAK: invalid rkey)"
)

start_server() { pkill -f './server' 2>/dev/null; sleep 1
  RDMA_BIND="$SERVER_RDMA" nohup "$LOCAL_DIR/server" > /tmp/server_swap.log 2>&1 & sleep 1; }
stop_server()  { pkill -f './server' 2>/dev/null; sleep 1; }
trap 'set +e; stop_server' EXIT

echo "[swap] build both nodes..."
make -C "$LOCAL_DIR" client server || { echo "local build failed"; exit 1; }
ssh "$CLIENT_SSH" "cd $CLIENT_DIR && make client server" || { echo "224 build failed"; exit 1; }

# fresh client-side summary
ssh "$CLIENT_SSH" "rm -f $CLIENT_DIR/results/raw/vendor_err_summary.csv; mkdir -p $CLIENT_DIR/results/raw"

echo "[swap] N=$N scenarios=[${SC[*]}]  requester=224($REQUESTER_NIC) responder=225($RESPONDER_NIC)"
for sc in "${SC[@]}"; do
  echo ""
  echo "=================================================================="
  echo "  SWAP scenario $sc: ${NAMES[$sc]:-unknown}"
  echo "=================================================================="
  start_server
  ssh "$CLIENT_SSH" "cd $CLIENT_DIR && RDMA_SERVER=$SERVER_RDMA REQUESTER_NIC=$REQUESTER_NIC ./client $sc $N $SERVER_RDMA"
  stop_server
done

echo ""
echo "[swap] done. vendor_err (requester=$REQUESTER_NIC) vs CX-6 baseline:"
ssh "$CLIENT_SSH" "cat $CLIENT_DIR/results/raw/vendor_err_summary.csv"
