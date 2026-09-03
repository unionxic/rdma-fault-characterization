#!/bin/bash
# run.sh — rdma_conn 미들웨어 자동복구 데모
# 225(client)에서 실행. server는 224에서 SSH로 관리한다.
#
# 4개 시나리오를 차례로 돌리며 분류→자동복구→재전송 전체 경로를 보인다.
# 사용: bash run.sh

set -e

REMOTE="gustlr@SERVER_224_ADDR"
REMOTE_DIR="/home/gustlr/Desktop/gpu_fault_recovery/08_middleware"
LOCAL_DIR="$(cd "$(dirname "$0")" && pwd)"

# --- Build ---
echo "[build] librdma_fault.a + demo_client on 225..."
make -C "$LOCAL_DIR/../07_fault_classify" librdma_fault.a
make -C "$LOCAL_DIR" demo_client

echo "[build] librdma_fault.a + demo_server on 224..."
ssh "$REMOTE" "make -C $REMOTE_DIR/../07_fault_classify librdma_fault.a && make -C $REMOTE_DIR demo_server"

# --- Server lifecycle (시나리오마다 새 server 프로세스) ---
stop_server() {
	ssh "$REMOTE" "pkill -f '$REMOTE_DIR/demo_server'" 2>/dev/null || true
	sleep 1
}
trap 'set +e; stop_server' EXIT

RC=0
for scen in rnr rem_access retry loc_prot; do
	echo ""
	echo "=================================================="
	echo " 시나리오: $scen"
	echo "=================================================="
	stop_server
	ssh -f "$REMOTE" "cd $REMOTE_DIR && nohup $REMOTE_DIR/demo_server $scen > /tmp/demo_server_$scen.log 2>&1 < /dev/null & exit"
	sleep 2
	if ! "$LOCAL_DIR/demo_client" "$scen"; then
		echo "  (scenario $scen: demo_client exit non-zero)"
		RC=1
	fi
	sleep 1
done

echo ""
if [ $RC -eq 0 ]; then
	echo "=== 모든 시나리오 자동복구 성공 ==="
else
	echo "=== 일부 시나리오 실패 — 위 출력 / ssh $REMOTE 'cat /tmp/demo_server_<scen>.log' 확인 ==="
fi
exit $RC
