/*
 * demo_server.c — rdma_conn 미들웨어 자동복구 시연 server (224)
 *
 * client와 같은 시나리오 인자로 실행한다. 정상 연결을 맺은 뒤(rdma_conn_server),
 * 시나리오별 trap을 깔고, rdma_conn_serve()로 client의 복구 요청에 응답한다.
 * 복구 절차(QP reset / MR 재등록 / probe 응답)는 전부 미들웨어가 처리한다.
 *
 * 사용: ./demo_server <scenario>
 *   rnr         lifecycle에서 recv 미게시 (client SEND → RNR)
 *   rem_access  연결 후 MR 재등록(새 rkey)하되 client엔 안 알림 → client stale rkey
 *   retry       연결 후 server QP를 ERR로 (client SEND ack 없음 → RETRY_EXC)
 *   loc_prot    trap 없음 (client 로컬 보호 위반)
 */
#include "rdma_conn.h"

#define MR_FULL  (IBV_ACCESS_LOCAL_WRITE | IBV_ACCESS_REMOTE_WRITE | \
		  IBV_ACCESS_REMOTE_READ)
#define CMD_TRAP_READY "TRAP_READY"   /* demo 전용: trap 완료를 client에 알림 */

int main(int argc, char **argv)
{
	if (argc < 2) {
		fprintf(stderr, "usage: %s <rnr|rem_access|retry|loc_prot>\n",
			argv[0]);
		return 2;
	}
	const char *scen = argv[1];
	srand(time(NULL));

	int listen_sock = tcp_listen(TCP_CTRL_PORT);
	if (listen_sock < 0) {
		fprintf(stderr, "ERROR: tcp_listen failed\n");
		return 1;
	}
	fprintf(stderr, "demo server listening (scenario=%s)\n", scen);

	/* RNR이면 recv를 안 올린 채 연결한다 — client SEND이 RNR NAK를 받게. */
	int post_recv_initial = strcmp(scen, "rnr") ? 1 : 0;

	struct rdma_conn c;
	if (rdma_conn_server(&c, listen_sock, MR_FULL, 1, 7, 7, 14,
			     post_recv_initial) < 0) {
		fprintf(stderr, "ERROR: rdma_conn_server failed\n");
		close(listen_sock);
		return 1;
	}
	fprintf(stderr, "connected\n");

	/* --- 연결 후 trap --- */
	if (!strcmp(scen, "retry")) {
		struct ibv_qp_attr attr = { .qp_state = IBV_QPS_ERR };
		if (ibv_modify_qp(c.res.qp, &attr, IBV_QP_STATE))
			fprintf(stderr, "WARN: QP->ERR failed: %s\n", strerror(errno));
		else
			fprintf(stderr, "trap: server QP -> ERR\n");
	}
	/* rem_access: client가 rkey를 위조하므로 server trap 불필요(정상 연결).
	 * rnr: post_recv_initial=0이 trap. loc_prot: trap 불필요. */

	/* trap 완료를 client에 알린다 — client는 이 신호 후에 inject한다.
	 * RoCE RTT가 매우 낮아(~수 us), 신호 없이는 client의 첫 전송이 trap
	 * 적용(특히 QP->ERR, firmware 왕복 ~수십 us) 전에 responder에 도착해
	 * 정상 처리될 수 있다. */
	tcp_send_msg(c.ctrl_sock, CMD_TRAP_READY);

	/* client의 복구 요청에 응답 (MW_SHUTDOWN까지) */
	rdma_conn_serve(&c);

	rdma_conn_close(&c);
	close(listen_sock);
	fprintf(stderr, "demo server done\n");
	return 0;
}
