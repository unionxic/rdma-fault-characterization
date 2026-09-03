/*
 * server.c — swap 실험용 responder (225에서 실행)
 *
 * run_swap.sh 전용. NIC 세대 swap 실험은 역할을 뒤집어 225(ConnectX-6)가
 * responder, 224(ConnectX-5)가 requester가 된다. 이 파일은 224 server.c의
 * 부분집합으로 fingerprint + partial write 검증 명령만 처리한다 (A/B 명령 없음).
 * env RDMA_BIND로 제어 소켓을 특정 IP(RDMA 서브넷)에 고정할 수 있다.
 * 평상시 실험의 서버는 이 파일이 아니라 224쪽 server.c다.
 */
#include "common.h"

static struct rdma_res res;
static int ctrl_sock = -1;

static int handle_setup(int conn, int use_send_recv, int enable_remote_write)
{
	int access = IBV_ACCESS_LOCAL_WRITE;
	if (enable_remote_write)
		access |= IBV_ACCESS_REMOTE_WRITE | IBV_ACCESS_REMOTE_READ;

	if (setup_rdma(&res, use_send_recv, access, 7, 7, 14) < 0)
		return -1;

	tcp_exchange_qp_info(conn, &res.local_info, &res.remote_info, 1);

	if (connect_qp(&res, enable_remote_write, 7, 7, 14) < 0)
		return -1;

	if (use_send_recv) {
		/* For RNR_RETRY_EXC scenario, we intentionally do NOT post recv */
		printf("  [server] SEND/RECV QP ready (no recv WQE posted for RNR_RETRY_EXC)\n");
	} else {
		printf("  [server] WRITE QP ready (remote_write=%d)\n",
		       enable_remote_write);
	}

	tcp_send_msg(conn, CMD_READY);
	return 0;
}

static int handle_setup_normal(int conn)
{
	return handle_setup(conn, 0, 1);
}

static int handle_setup_no_remote_write(int conn)
{
	return handle_setup(conn, 0, 0);
}

static int handle_setup_send_recv(int conn)
{
	return handle_setup(conn, 1, 0);
}

static int handle_inject(int conn, const char *scenario_str)
{
	int scenario = atoi(scenario_str);

	switch (scenario) {
	case REM_INV_REQ:
		/* QP already setup without REMOTE_WRITE flag.
		 * The client's RDMA WRITE will trigger NAK code 1. */
		printf("  [server] REM_INV_REQ: QP has no REMOTE_WRITE (already set)\n");
		break;

	case RNR_RETRY_EXC:
		/* No recv WQE posted — client's SEND will get RNR NAK */
		printf("  [server] RNR_RETRY_EXC: no recv WQE posted\n");
		break;

	case RETRY_EXC_QP_ERR: {
		struct ibv_qp_attr attr = { .qp_state = IBV_QPS_ERR };
		if (ibv_modify_qp(res.qp, &attr, IBV_QP_STATE) < 0) {
			perror("ibv_modify_qp(ERR)");
			return -1;
		}
		printf("  [server] RETRY_EXC_QP_ERR: QP moved to ERR state\n");
		break;
	}

	default:
		printf("  [server] scenario %d: no server-side action needed\n",
		       scenario);
		break;
	}

	tcp_send_msg(conn, CMD_DONE);
	return 0;
}

static int handle_setup_boundary(int conn)
{
	int access = IBV_ACCESS_LOCAL_WRITE | IBV_ACCESS_REMOTE_WRITE |
		     IBV_ACCESS_REMOTE_READ;

	if (setup_rdma(&res, 0, access, 7, 7, 14) < 0)
		return -1;

	ibv_dereg_mr(res.mr);
	free(res.buf);

	res.buf = calloc(1, BOUNDARY_BUF_SIZE);
	if (!res.buf)
		return -1;
	res.buf_size = BOUNDARY_BUF_SIZE;

	res.mr = ibv_reg_mr(res.pd, res.buf, MR_SIZE, access);
	if (!res.mr)
		return -1;

	res.local_info.rkey = res.mr->rkey;
	res.local_info.raddr = (uint64_t)res.buf;

	tcp_exchange_qp_info(conn, &res.local_info, &res.remote_info, 1);

	if (connect_qp(&res, 1, 7, 7, 14) < 0)
		return -1;

	printf("  [server] Boundary QP ready (buf=%d, mr=%d)\n",
	       BOUNDARY_BUF_SIZE, MR_SIZE);
	tcp_send_msg(conn, CMD_READY);
	return 0;
}

static void handle_init_buffer(int conn)
{
	memset(res.buf, 0, res.buf_size);
	printf("  [server] Buffer zeroed (%zu bytes)\n", res.buf_size);
	tcp_send_msg(conn, CMD_DONE);
}

static void handle_check_buffer(int conn, const char *args)
{
	int offset = 0, length = 0;
	sscanf(args, "%d %d", &offset, &length);

	unsigned char *buf = (unsigned char *)res.buf;
	int mr_end = MR_SIZE;

	int within_end = (offset + length < mr_end) ?
			 offset + length : mr_end;
	int within_mod = 0;
	for (int i = offset; i < within_end; i++)
		if (buf[i] != 0) within_mod++;

	int beyond_start = mr_end;
	int beyond_end = offset + length;
	if (beyond_end > (int)res.buf_size)
		beyond_end = (int)res.buf_size;
	int beyond_mod = 0;
	for (int i = beyond_start; i < beyond_end; i++)
		if (buf[i] != 0) beyond_mod++;

	char resp[128];
	snprintf(resp, sizeof(resp), "PARTIAL:%d/%d:%d/%d",
		 within_mod, within_end - offset,
		 beyond_mod, beyond_end - beyond_start);
	printf("  [server] %s\n", resp);
	tcp_send_msg(conn, resp);
}

static void run_server(void)
{
	/* Optional bind IP via env RDMA_BIND (default INADDR_ANY). Lets the
	 * swap experiment pin the control socket to this node's RDMA subnet IP;
	 * unset preserves the original wide-open listen. */
	const char *bind_ip = getenv("RDMA_BIND");
	int listen_sock = tcp_listen_bind(TCP_CTRL_PORT, bind_ip);
	if (listen_sock < 0) {
		fprintf(stderr, "Failed to listen on port %d (bind=%s)\n",
			TCP_CTRL_PORT, (bind_ip && bind_ip[0]) ? bind_ip : "ANY");
		exit(1);
	}
	printf("Server listening on port %d (bind=%s)\n",
	       TCP_CTRL_PORT, (bind_ip && bind_ip[0]) ? bind_ip : "ANY");

	while (1) {
		struct sockaddr_in client_addr;
		socklen_t len = sizeof(client_addr);
		int conn = accept(listen_sock, (struct sockaddr *)&client_addr, &len);
		if (conn < 0) {
			perror("accept");
			continue;
		}
		/* Nagle+delayed-ACK가 lockstep 왕복에 40ms floor를 만든다 —
		 * 224 server.c / 06_recovery 서버들과 동일하게 비활성화 (2026-07-15). */
		int flag = 1;
		setsockopt(conn, IPPROTO_TCP, TCP_NODELAY, &flag, sizeof(flag));
		printf("Client connected\n");
		ctrl_sock = conn;

		char cmd[256];
		while (tcp_recv_msg(conn, cmd, sizeof(cmd)) > 0) {
			printf("[server] cmd: %s\n", cmd);

			if (strncmp(cmd, CMD_SETUP_SEND, strlen(CMD_SETUP_SEND)) == 0) {
				if (handle_setup_send_recv(conn) < 0)
					fprintf(stderr, "setup_send_recv failed\n");

			} else if (strncmp(cmd, CMD_SETUP_NOREMOTE, strlen(CMD_SETUP_NOREMOTE)) == 0) {
				if (handle_setup_no_remote_write(conn) < 0)
					fprintf(stderr, "setup_no_remote failed\n");

			} else if (strncmp(cmd, CMD_SETUP_BOUNDARY, strlen(CMD_SETUP_BOUNDARY)) == 0) {
				if (handle_setup_boundary(conn) < 0)
					fprintf(stderr, "setup_boundary failed\n");

			} else if (strncmp(cmd, CMD_SETUP, strlen(CMD_SETUP)) == 0) {
				if (handle_setup_normal(conn) < 0)
					fprintf(stderr, "setup failed\n");

			} else if (strncmp(cmd, CMD_INJECT, strlen(CMD_INJECT)) == 0) {
				char *arg = cmd + strlen(CMD_INJECT) + 1;
				if (handle_inject(conn, arg) < 0)
					fprintf(stderr, "inject failed\n");

			} else if (strcmp(cmd, CMD_INIT_BUFFER) == 0) {
				handle_init_buffer(conn);

			} else if (strncmp(cmd, CMD_CHECK_BUFFER, strlen(CMD_CHECK_BUFFER)) == 0) {
				handle_check_buffer(conn, cmd + strlen(CMD_CHECK_BUFFER) + 1);

			} else if (strcmp(cmd, CMD_CLEANUP) == 0) {
				cleanup_rdma(&res);
				printf("  [server] RDMA resources cleaned up\n");
				tcp_send_msg(conn, CMD_DONE);

			} else if (strcmp(cmd, CMD_QUERY_STATE) == 0) {
				if (!res.qp) {
					tcp_send_msg(conn, "QP_STATE=-1");
				} else {
					struct ibv_qp_attr qattr;
					struct ibv_qp_init_attr qinit;
					if (ibv_query_qp(res.qp, &qattr,
							 IBV_QP_STATE, &qinit))
						tcp_send_msg(conn, "QP_STATE=-2");
					else {
						char resp[32];
						snprintf(resp, sizeof(resp),
							 "QP_STATE=%d",
							 qattr.qp_state);
						tcp_send_msg(conn, resp);
					}
				}

			} else if (strcmp(cmd, CMD_SHUTDOWN) == 0) {
				cleanup_rdma(&res);
				tcp_send_msg(conn, CMD_DONE);
				close(conn);
				close(listen_sock);
				printf("Server shutting down\n");
				return;

			} else {
				fprintf(stderr, "Unknown command: %s\n", cmd);
				tcp_send_msg(conn, "ERROR");
			}
		}

		printf("Client disconnected\n");
		cleanup_rdma(&res);
		close(conn);
		ctrl_sock = -1;
	}
}

int main(void)
{
	srand(time(NULL));
	run_server();
	return 0;
}
