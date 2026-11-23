/*
 * REM_ACCESS_ERR recovery benchmark — server (224)
 *
 * SETUP_REM: create resources, exchange, connect (with valid MR)
 * INVALIDATE_MR: deregister MR → client's next WRITE gets REM_ACCESS_ERR
 * RECOVER_QP_MR: reset QP, register new MR, exchange new info, reconnect
 * RECOVER_FULL: destroy all, recreate
 *
 * Usage: ./server
 */

#include "../recovery_common.h"

#define MR_ACCESS  (IBV_ACCESS_LOCAL_WRITE | IBV_ACCESS_REMOTE_WRITE | \
		    IBV_ACCESS_REMOTE_READ)

#define CMD_SETUP_REM      "SETUP_REM"
#define CMD_INVALIDATE_MR  "INVALIDATE_MR"
#define CMD_RECOVER_QP_MR  "RECOVER_QP_MR"

static struct rdma_res res;
static int res_active = 0;

/* ------------------------------------------------------------------ */
/*  Command: SETUP_REM                                                */
/*  Create resources, exchange, connect — MR fully valid              */
/* ------------------------------------------------------------------ */

static int handle_setup_rem(int sock)
{
	fprintf(stderr, "[cmd] SETUP_REM\n");

	if (res_active) {
		cleanup_rdma(&res);
		res_active = 0;
	}

	memset(&res, 0, sizeof(res));

	if (setup_rdma(&res, 1, MR_ACCESS, 7, 7, 14) < 0) {
		fprintf(stderr, "ERROR: setup_rdma failed\n");
		return -1;
	}
	res_active = 1;

	tcp_send_msg(sock, CMD_READY);

	if (tcp_exchange_qp_info(sock, &res.local_info,
				 &res.remote_info, 1) < 0) {
		fprintf(stderr, "ERROR: QP info exchange failed\n");
		return -1;
	}

	if (connect_qp(&res, 7, 7, 7, 14) < 0) {
		fprintf(stderr, "ERROR: connect_qp failed\n");
		return -1;
	}

	fprintf(stderr, "  QP connected, MR valid (rkey=0x%x, addr=0x%lx)\n",
		res.mr->rkey, (unsigned long)res.buf);
	return 0;
}

/* ------------------------------------------------------------------ */
/*  Command: INVALIDATE_MR                                            */
/*  Deregister MR — makes client's cached rkey stale                  */
/* ------------------------------------------------------------------ */

static int handle_invalidate_mr(int sock)
{
	fprintf(stderr, "[cmd] INVALIDATE_MR\n");

	if (!res_active || !res.mr) {
		fprintf(stderr, "ERROR: no active MR\n");
		return -1;
	}

	uint32_t old_rkey = res.mr->rkey;
	if (ibv_dereg_mr(res.mr) != 0) {
		fprintf(stderr, "ERROR: ibv_dereg_mr failed: %s\n",
			strerror(errno));
		return -1;
	}
	res.mr = NULL;

	fprintf(stderr, "  MR deregistered (old rkey=0x%x now invalid)\n",
		old_rkey);

	tcp_send_msg(sock, CMD_READY);
	return 0;
}

/* ------------------------------------------------------------------ */
/*  Command: RECOVER_QP_MR                                            */
/*  Reset QP, register new MR, exchange new PSN+rkey+addr, reconnect  */
/* ------------------------------------------------------------------ */

static int handle_recover_qp_mr(int sock)
{
	fprintf(stderr, "[cmd] RECOVER_QP_MR\n");

	if (!res_active) {
		fprintf(stderr, "ERROR: no active resources\n");
		return -1;
	}

	int drained = drain_cq(res.cq);
	if (drained > 0)
		fprintf(stderr, "  drained %d CQ entries\n", drained);

	if (reset_qp_to_reset(res.qp) < 0)
		return -1;

	/* Register new MR (reuse existing buffer) */
	res.mr = ibv_reg_mr(res.pd, res.buf, 4096, MR_ACCESS);
	if (!res.mr) {
		fprintf(stderr, "ERROR: ibv_reg_mr failed: %s\n",
			strerror(errno));
		return -1;
	}

	/* Update local info with new PSN + new MR info */
	res.local_info.psn = rand() & 0xFFFFFF;
	res.local_info.rkey = res.mr->rkey;
	res.local_info.raddr = (uint64_t)res.buf;

	if (tcp_exchange_qp_info(sock, &res.local_info,
				 &res.remote_info, 1) < 0)
		return -1;

	if (connect_qp(&res, 7, 7, 7, 14) < 0) {
		fprintf(stderr, "ERROR: connect_qp after recovery failed\n");
		return -1;
	}

	tcp_send_msg(sock, CMD_READY);
	fprintf(stderr, "  recovered: new rkey=0x%x\n", res.mr->rkey);
	return 0;
}

/* ------------------------------------------------------------------ */
/*  Command: RECOVER_FULL                                             */
/*  Destroy all, recreate, exchange, reconnect                        */
/* ------------------------------------------------------------------ */

static int handle_recover_full(int sock)
{
	fprintf(stderr, "[cmd] RECOVER_FULL\n");

	if (res_active) {
		cleanup_rdma(&res);
		res_active = 0;
	}

	memset(&res, 0, sizeof(res));

	if (setup_rdma(&res, 1, MR_ACCESS, 7, 7, 14) < 0) {
		fprintf(stderr, "ERROR: setup_rdma in full rebuild failed\n");
		return -1;
	}
	res_active = 1;

	if (tcp_exchange_qp_info(sock, &res.local_info,
				 &res.remote_info, 1) < 0)
		return -1;

	if (connect_qp(&res, 7, 7, 7, 14) < 0) {
		fprintf(stderr, "ERROR: connect_qp in full rebuild failed\n");
		return -1;
	}

	tcp_send_msg(sock, CMD_READY);
	fprintf(stderr, "  full rebuild done\n");
	return 0;
}

/* ------------------------------------------------------------------ */
/*  Command: CLEANUP                                                  */
/* ------------------------------------------------------------------ */

static int handle_cleanup(int sock)
{
	fprintf(stderr, "[cmd] CLEANUP\n");

	if (res_active) {
		cleanup_rdma(&res);
		res_active = 0;
	}
	memset(&res, 0, sizeof(res));

	tcp_send_msg(sock, CMD_DONE);
	return 0;
}

/* ------------------------------------------------------------------ */
/*  main                                                              */
/* ------------------------------------------------------------------ */

int main(void)
{
	srand(time(NULL));

	int listen_sock = tcp_listen(TCP_CTRL_PORT);
	if (listen_sock < 0) {
		fprintf(stderr, "ERROR: tcp_listen failed\n");
		return 1;
	}
	fprintf(stderr, "Server listening on port %d\n", TCP_CTRL_PORT);

	while (1) {
		fprintf(stderr, "Waiting for client connection...\n");
		struct sockaddr_in client_addr;
		socklen_t alen = sizeof(client_addr);
		int sock = accept(listen_sock, (struct sockaddr *)&client_addr,
				  &alen);
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

			if (strcmp(cmd, CMD_SETUP_REM) == 0) {
				if (handle_setup_rem(sock) < 0)
					fprintf(stderr, "WARN: SETUP_REM failed\n");

			} else if (strcmp(cmd, CMD_INVALIDATE_MR) == 0) {
				if (handle_invalidate_mr(sock) < 0)
					fprintf(stderr, "WARN: INVALIDATE_MR failed\n");

			} else if (strcmp(cmd, CMD_RECOVER_QP_MR) == 0) {
				if (handle_recover_qp_mr(sock) < 0)
					fprintf(stderr, "WARN: RECOVER_QP_MR failed\n");

			} else if (strcmp(cmd, CMD_RECOVER_FULL) == 0) {
				if (handle_recover_full(sock) < 0)
					fprintf(stderr, "WARN: RECOVER_FULL failed\n");

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
	fprintf(stderr, "Server exiting\n");
	return 0;
}
