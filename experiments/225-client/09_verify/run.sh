#!/bin/bash
# run.sh — rdma_fault 분류 라이브러리 실제 연결 통합 검증
# 225(client)에서 실행. server는 224에서 SSH로 관리한다.
#
# 5개 fault를 실제로 일으켜 rdma_poll의 분류가 분류표 기대값과 맞는지 본다.
# 사용: bash run.sh

set -e

REMOTE="gustlr@SERVER_224_ADDR"
REMOTE_DIR="/home/gustlr/Desktop/gpu_fault_recovery/09_verify"
LOCAL_DIR="$(cd "$(dirname "$0")" && pwd)"

# --- Build ---
echo "[build] librdma_fault.a (분류 라이브러리)..."
make -C "$LOCAL_DIR/../07_fault_classify"

echo "[build] verify client on 225..."
make -C "$LOCAL_DIR" client

echo "[build] verify server on 224..."
ssh "$REMOTE" "cd $REMOTE_DIR && make server"

# --- Server management ---
stop_server() {
	ssh "$REMOTE" "pkill -f '$REMOTE_DIR/server'" 2>/dev/null || true
	sleep 1
}
start_server() {
	echo "[server] starting on 224..."
	ssh -f "$REMOTE" "cd $REMOTE_DIR && nohup $REMOTE_DIR/server > /tmp/verify_server.log 2>&1 < /dev/null & exit"
	sleep 2
}
check_server() {
	ssh "$REMOTE" "pgrep -f '$REMOTE_DIR/server'" > /dev/null 2>&1
}

trap 'set +e; stop_server' EXIT
stop_server
start_server

if ! check_server; then
	echo "ERROR: server failed to start on 224"
	echo "Check: ssh $REMOTE 'cat /tmp/verify_server.log'"
	exit 1
fi

# --- Run ---
echo ""
echo "[client] running integration verification..."
echo ""
"$LOCAL_DIR/client"
RC=$?

echo ""
if [ $RC -eq 0 ]; then
	echo "=== 검증 통과: 라이브러리가 실제 CQE를 분류표대로 분류함 ==="
else
	echo "=== 검증 실패 (exit $RC) — 위 FAIL 행 확인 ==="
	echo "Server log: ssh $REMOTE 'cat /tmp/verify_server.log'"
fi
exit $RC
