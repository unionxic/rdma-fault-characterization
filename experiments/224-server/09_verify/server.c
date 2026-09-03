/*
 * verify/server.c — rdma_fault 분류 라이브러리 통합 검증용 server (224)
 *
 * 목적: 실제 RDMA 연결에서 여러 fault를 의도적으로 만들어, client의
 * rdma_poll/rdma_classify가 "하드웨어가 실제로 낸" 에러 CQE를 분류표대로
 * 분류하는지 확인한다. 단위테스트(test_classify)는 가짜 ibv_wc로 분류 로직만
 * 보지만, 이 harness는 진짜 NIC가 만든 (status, vendor_err)로 통합 검증한다.
 *
 * 이 server는 fault 조건만 만든다(분류는 client 쪽 라이브러리가 한다). 각
 * 시나리오의 trap은 MR 권한 / recv 게시 여부 / QP 상태로만 갈린다:
 *
 *   SETUP_NORMAL   MR full access(LOCAL|REMOTE_WRITE|REMOTE_READ), recv 게시
 *                  → LOC_PROT(client 로컬) / REM_ACCESS(client bad rkey) /
 *                    RETRY_EXC(이후 INJECT_QP_ERR)의 베이스
 *   SETUP_NORECV   MR full access, recv 미게시 → client SEND이 RNR NAK
 *   SETUP_NOPERM   MR을 LOCAL_WRITE only로 등록(QP access는 remote 허용)
 *                  → valid rkey지만 MR 권한 부족 → REM_INV_REQ NAK
 *   INJECT_QP_ERR  server QP를 ERR로 전이 → client SEND ack 없음 → RETRY_EXC
 *   CLEANUP/SHUTDOWN
 *
 * 주의: REM_ACCESS(invalid rkey)와 REM_INV_REQ(valid rkey + MR 권한 부족)는
 * vendor_err가 각각 0x88 / 0x8a로 갈린다. 그래서 trap도 rkey 위조(client) vs
 * MR 권한 제거(server)로 다르게 만든다.
 */
#include "../05_counter_mapping/common.h"

#define MR_FULL    (IBV_ACCESS_LOCAL_WRITE | IBV_ACCESS_REMOTE_WRITE | \
		    IBV_ACCESS_REMOTE_READ)
#define MR_NOPERM  (IBV_ACCESS_LOCAL_WRITE)   /* remote 권한 없음 → REM_INV_REQ */

/* verify 전용 control 명령 (client.c와 동일 정의) */
#define CMD_SETUP_NORMAL   "SETUP_NORMAL"
#define CMD_SETUP_NORECV   "SETUP_NORECV"
#define CMD_SETUP_NOPERM   "SETUP_NOPERM"
#define CMD_INJECT_QP_ERR  "INJECT_QP_ERR"

static struct rdma_res res;
static int res_active = 0;

/*
 * 공통 setup. mr_access(MR 권한)와 post_recv_buf(recv 게시 여부)만 시나리오마다
 * 다르다. QP access는 항상 remote 허용 — REM_INV_REQ는 MR 권한으로만 유발한다.
 */
static int do_setup(int sock, int mr_access, int post_recv_buf,
		    int qp_remote_write)
{
	if (res_active) {
		cleanup_rdma(&res);
		res_active = 0;
	}
	memset(&res, 0, sizeof(res));

	if (setup_rdma(&res, 1, mr_access, 7, 7, 14) < 0) {
		fprintf(stderr, "ERROR: setup_rdma failed\n");
		return -1;
	}
	res_active = 1;

	/* client에게 QP info 교환 시작을 알린다 (#1) */
	tcp_send_msg(sock, CMD_READY);

	/* QP info 교환: server는 먼저 받고 나중에 보낸다 */
	if (tcp_exchange_qp_info(sock, &res.local_info, &res.remote_info, 1) < 0) {
		fprintf(stderr, "ERROR: QP info exchange failed\n");
		return -1;
	}

	/* QP access의 remote_write는 호출자가 지정한다 (REM_INV_REQ trap은 0) */
	if (connect_qp(&res, qp_remote_write, 7, 7, 14) < 0) {
		fprintf(stderr, "ERROR: connect_qp failed\n");
		return -1;
	}

	if (post_recv_buf) {
		if (post_recv(&res) < 0) {
			fprintf(stderr, "ERROR: post_recv failed\n");
			return -1;
		}
	}

	/* 연결 완료 (#2) */
	tcp_send_msg(sock, CMD_READY);
	fprintf(stderr, "  setup done (mr_access=0x%x, recv=%d)\n",
		mr_access, post_recv_buf);
	return 0;
}

/* server QP를 ERR로 전이 → client SEND이 ack를 못 받아 RETRY_EXC가 난다 */
static int inject_qp_err(int sock)
{
	if (!res_active) {
		fprintf(stderr, "ERROR: no active resources\n");
		return -1;
	}
	struct ibv_qp_attr attr = { .qp_state = IBV_QPS_ERR };
	if (ibv_modify_qp(res.qp, &attr, IBV_QP_STATE)) {
		fprintf(stderr, "ERROR: modify to ERR failed: %s\n",
			strerror(errno));
		return -1;
	}
	fprintf(stderr, "  server QP -> ERR (RETRY trap set)\n");
	tcp_send_msg(sock, CMD_READY);
	return 0;
}

static int handle_cleanup(int sock)
{
	if (res_active) {
		cleanup_rdma(&res);
		res_active = 0;
	}
	memset(&res, 0, sizeof(res));
	tcp_send_msg(sock, CMD_DONE);
	return 0;
}

int main(void)
{
	srand(time(NULL));

	int listen_sock = tcp_listen(TCP_CTRL_PORT);
	if (listen_sock < 0) {
		fprintf(stderr, "ERROR: tcp_listen failed\n");
		return 1;
	}
	fprintf(stderr, "verify server listening on port %d\n", TCP_CTRL_PORT);

	while (1) {
		fprintf(stderr, "Waiting for client connection...\n");
		struct sockaddr_in caddr;
		socklen_t alen = sizeof(caddr);
		int sock = accept(listen_sock, (struct sockaddr *)&caddr, &alen);
		if (sock < 0) {
			perror("accept");
			continue;
		}
		int flag = 1;
		setsockopt(sock, IPPROTO_TCP, TCP_NODELAY, &flag, sizeof(flag));
		fprintf(stderr, "Client connected\n");

		char cmd[64];
		int running = 1;
		while (running && tcp_recv_msg(sock, cmd, sizeof(cmd)) > 0) {
			fprintf(stderr, "\nReceived command: '%s'\n", cmd);

			if (strcmp(cmd, CMD_SETUP_NORMAL) == 0) {
				do_setup(sock, MR_FULL, 1, 1);
			} else if (strcmp(cmd, CMD_SETUP_NORECV) == 0) {
				do_setup(sock, MR_FULL, 0, 1);
			} else if (strcmp(cmd, CMD_SETUP_NOPERM) == 0) {
				/* MR 권한 위반은 REM_ACCESS(0x88)로 떨어진다(실측 일관).
				 * REM_INV_REQ(0x8a)는 QP access 레벨 위반 — server QP에서
				 * REMOTE_WRITE를 빼고 MR은 정상으로 둔다. */
				do_setup(sock, MR_FULL, 1, 0);
			} else if (strcmp(cmd, CMD_INJECT_QP_ERR) == 0) {
				inject_qp_err(sock);
			} else if (strcmp(cmd, CMD_CLEANUP) == 0) {
				handle_cleanup(sock);
			} else if (strcmp(cmd, CMD_SHUTDOWN) == 0) {
				fprintf(stderr, "[cmd] SHUTDOWN\n");
				if (res_active) {
					cleanup_rdma(&res);
					res_active = 0;
				}
				running = 0;
			} else {
				fprintf(stderr, "WARN: unknown command '%s'\n", cmd);
			}
		}

		close(sock);
		fprintf(stderr, "Client disconnected\n");
		if (!running)
			break;
	}

	close(listen_sock);
	fprintf(stderr, "verify server exiting\n");
	return 0;
}
