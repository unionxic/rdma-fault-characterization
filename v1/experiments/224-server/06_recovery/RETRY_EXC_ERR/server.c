/*
 * RETRY_EXC_ERR recovery benchmark — server (224)
 *
 * Listens for TCP commands from the client.
 * SETUP_RETRY: create QP, exchange, connect normally (both QPs healthy).
 * INJECT_FAULT: move server QP to ERR state → client's SEND will timeout.
 * RECOVER_QP/RECOVER_FULL: rebuild QP, post recv so client retry succeeds.
 *
 * Usage: ./server
 */

#include "../recovery_common.h"

#define MR_ACCESS  (IBV_ACCESS_LOCAL_WRITE | IBV_ACCESS_REMOTE_WRITE | \
		    IBV_ACCESS_REMOTE_READ)

#define CMD_SETUP_RETRY   "SETUP_RETRY"
#define CMD_INJECT_FAULT  "INJECT_FAULT"

static struct rdma_res res;
static int res_active = 0;

/* ------------------------------------------------------------------ */
/*  Command: SETUP_RETRY                                              */
/*  Create resources, exchange, connect normally                      */
/* ------------------------------------------------------------------ */

static int handle_setup_retry(int sock)
{
	fprintf(stderr, "[cmd] SETUP_RETRY\n");

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

	/* Exchange QP info: server receives first, then sends */
	if (tcp_exchange_qp_info(sock, &res.local_info,
				 &res.remote_info, 1) < 0) {
		fprintf(stderr, "ERROR: QP info exchange failed\n");
		return -1;
	}

	/* Connect QP normally */
	if (connect_qp(&res, 0, 7, 7, 14) < 0) {
		fprintf(stderr, "ERROR: connect_qp failed\n");
		return -1;
	}

	fprintf(stderr, "  QP connected normally (healthy)\n");
	return 0;
}

/* ------------------------------------------------------------------ */
/*  Command: INJECT_FAULT                                             */
/*  Move server QP to ERR → client SEND will get no response          */
/* ------------------------------------------------------------------ */

static int handle_inject_fault(int sock)
{
	fprintf(stderr, "[cmd] INJECT_FAULT\n");

	if (!res_active) {
		fprintf(stderr, "ERROR: no active resources\n");
		return -1;
	}

	struct ibv_qp_attr attr = { .qp_state = IBV_QPS_ERR };
	if (ibv_modify_qp(res.qp, &attr, IBV_QP_STATE) != 0) {
		fprintf(stderr, "ERROR: ibv_modify_qp(ERR) failed: %s\n",
			strerror(errno));
		return -1;
	}

	fprintf(stderr, "  Server QP moved to ERR (fault injected)\n");
	tcp_send_msg(sock, CMD_READY);
	return 0;
}

/* ------------------------------------------------------------------ */
/*  Command: RECOVER_QP                                               */
/*  Reset QP (from ERR), new PSN, re-exchange, reconnect, post recv   */
/* ------------------------------------------------------------------ */

static int handle_recover_qp(int sock)
{
	fprintf(stderr, "[cmd] RECOVER_QP\n");

	if (!res_active) {
		fprintf(stderr, "ERROR: no active resources\n");
		return -1;
	}

	int drained = drain_cq(res.cq);
	if (drained > 0)
		fprintf(stderr, "  drained %d CQ entries\n", drained);

	if (reset_qp_to_reset(res.qp) < 0)
		return -1;

	res.local_info.psn = rand() & 0xFFFFFF;

	if (tcp_exchange_qp_info(sock, &res.local_info,
				 &res.remote_info, 1) < 0)
		return -1;

	if (connect_qp(&res, 0, 7, 7, 14) < 0) {
		fprintf(stderr, "ERROR: connect_qp after recovery failed\n");
		return -1;
	}

	if (post_recv(&res) < 0) {
		fprintf(stderr, "ERROR: post_recv failed\n");
		return -1;
	}

	tcp_send_msg(sock, CMD_READY);
	fprintf(stderr, "  QP recovered (ERR→RESET→RTS), recv posted\n");
	return 0;
}

/* ------------------------------------------------------------------ */
/*  Command: RECOVER_FULL                                             */
/*  Destroy all, recreate, re-exchange, reconnect, post recv          */
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

	if (connect_qp(&res, 0, 7, 7, 14) < 0) {
		fprintf(stderr, "ERROR: connect_qp in full rebuild failed\n");
		return -1;
	}

	if (post_recv(&res) < 0) {
		fprintf(stderr, "ERROR: post_recv failed\n");
		return -1;
	}

	tcp_send_msg(sock, CMD_READY);
	fprintf(stderr, "  full rebuild done, recv posted\n");
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

			if (strcmp(cmd, CMD_SETUP_RETRY) == 0) {
				if (handle_setup_retry(sock) < 0)
					fprintf(stderr, "WARN: SETUP_RETRY failed\n");

			} else if (strcmp(cmd, CMD_INJECT_FAULT) == 0) {
				if (handle_inject_fault(sock) < 0)
					fprintf(stderr, "WARN: INJECT_FAULT failed\n");

			} else if (strcmp(cmd, CMD_RECOVER_QP) == 0) {
				if (handle_recover_qp(sock) < 0)
					fprintf(stderr, "WARN: RECOVER_QP failed\n");

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
