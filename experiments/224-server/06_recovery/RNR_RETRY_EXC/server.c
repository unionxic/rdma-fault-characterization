/*
 * RNR_RETRY_EXC recovery benchmark — server (224)
 *
 * Listens for TCP commands from the client and manages RDMA resources.
 * Key behavior: SETUP_RNR creates a QP but does NOT post a recv buffer,
 * causing the client's SEND to trigger RNR_RETRY_EXC_ERR.
 * Recovery commands (RECOVER_QP, RECOVER_FULL) rebuild the QP and
 * post a recv buffer so the client's retry SEND succeeds.
 *
 * Usage: ./server
 */

#include "../recovery_common.h"

#define MR_ACCESS  (IBV_ACCESS_LOCAL_WRITE | IBV_ACCESS_REMOTE_WRITE | \
		    IBV_ACCESS_REMOTE_READ)

static struct rdma_res res;
static int res_active = 0;  /* track whether resources are allocated */

/* ------------------------------------------------------------------ */
/*  Command: SETUP_RNR                                                */
/*  Create resources, exchange QP info, connect — but NO recv buffer  */
/* ------------------------------------------------------------------ */

static int handle_setup_rnr(int sock)
{
	fprintf(stderr, "[cmd] SETUP_RNR\n");

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

	/* Tell client we're ready for QP info exchange */
	tcp_send_msg(sock, CMD_READY);

	/* Exchange QP info: server receives first, then sends */
	if (tcp_exchange_qp_info(sock, &res.local_info,
				 &res.remote_info, 1) < 0) {
		fprintf(stderr, "ERROR: QP info exchange failed\n");
		return -1;
	}

	/* Connect QP — server side also uses rnr_retry=0 for symmetry,
	 * but it doesn't matter since server won't be sending */
	if (connect_qp(&res, 0, 0, 0, 14) < 0) {
		fprintf(stderr, "ERROR: connect_qp failed\n");
		return -1;
	}

	/* Deliberately do NOT post recv buffer -> triggers RNR on client SEND */
	fprintf(stderr, "  QP connected, NO recv posted (RNR trap set)\n");
	return 0;
}

/* ------------------------------------------------------------------ */
/*  Command: RECOVER_QP                                               */
/*  Reset QP, new PSN, post recv, re-exchange, reconnect              */
/* ------------------------------------------------------------------ */

static int handle_recover_qp(int sock)
{
	fprintf(stderr, "[cmd] RECOVER_QP\n");

	if (!res_active) {
		fprintf(stderr, "ERROR: no active resources\n");
		return -1;
	}

	/* 1. Drain any CQ completions */
	int drained = drain_cq(res.cq);
	if (drained > 0)
		fprintf(stderr, "  drained %d CQ entries\n", drained);

	/* 2. Reset QP */
	if (reset_qp_to_reset(res.qp) < 0)
		return -1;

	/* 3. New PSN */
	res.local_info.psn = rand() & 0xFFFFFF;

	/* 4. Exchange new QP info */
	if (tcp_exchange_qp_info(sock, &res.local_info,
				 &res.remote_info, 1) < 0)
		return -1;

	/* 5. Reconnect QP with normal retry params */
	if (connect_qp(&res, 0, 7, 7, 14) < 0) {
		fprintf(stderr, "ERROR: connect_qp after QP recovery failed\n");
		return -1;
	}

	/* 6. Post recv buffer (must be after INIT; connect_qp puts QP in RTS) */
	if (post_recv(&res) < 0) {
		fprintf(stderr, "ERROR: post_recv failed\n");
		return -1;
	}

	tcp_send_msg(sock, CMD_READY);
	fprintf(stderr, "  QP recovered, recv posted\n");
	return 0;
}

/* ------------------------------------------------------------------ */
/*  Command: RECOVER_FULL                                             */
/*  Destroy all, recreate, post recv, re-exchange, reconnect          */
/* ------------------------------------------------------------------ */

static int handle_recover_full(int sock)
{
	fprintf(stderr, "[cmd] RECOVER_FULL\n");

	/* 1. Destroy everything */
	if (res_active) {
		cleanup_rdma(&res);
		res_active = 0;
	}

	memset(&res, 0, sizeof(res));

	/* 2. Recreate all resources */
	if (setup_rdma(&res, 1, MR_ACCESS, 7, 7, 14) < 0) {
		fprintf(stderr, "ERROR: setup_rdma in full rebuild failed\n");
		return -1;
	}
	res_active = 1;

	/* 3. Exchange new QP info */
	if (tcp_exchange_qp_info(sock, &res.local_info,
				 &res.remote_info, 1) < 0)
		return -1;

	/* 4. Connect QP */
	if (connect_qp(&res, 0, 7, 7, 14) < 0) {
		fprintf(stderr, "ERROR: connect_qp in full rebuild failed\n");
		return -1;
	}

	/* 5. Post recv buffer (must be after INIT; connect_qp puts QP in RTS) */
	if (post_recv(&res) < 0) {
		fprintf(stderr, "ERROR: post_recv failed\n");
		return -1;
	}

	tcp_send_msg(sock, CMD_READY);
	fprintf(stderr, "  full rebuild done, recv posted\n");
	return 0;
}

/* ------------------------------------------------------------------ */
/*  Command: PREP_NEXT                                                */
/*  Drain recv completions but don't post new recv (re-arm RNR trap)  */
/* ------------------------------------------------------------------ */

static int handle_prep_next(int sock)
{
	fprintf(stderr, "[cmd] PREP_NEXT\n");

	if (res_active) {
		int drained = drain_cq(res.cq);
		fprintf(stderr, "  drained %d completions\n", drained);
	}

	tcp_send_msg(sock, CMD_READY);
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
/*  main: listen and dispatch commands                                */
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

			if (strcmp(cmd, CMD_SETUP_RNR) == 0) {
				if (handle_setup_rnr(sock) < 0)
					fprintf(stderr, "WARN: SETUP_RNR failed\n");

			} else if (strcmp(cmd, CMD_RECOVER_QP) == 0) {
				if (handle_recover_qp(sock) < 0)
					fprintf(stderr, "WARN: RECOVER_QP failed\n");

			} else if (strcmp(cmd, CMD_RECOVER_FULL) == 0) {
				if (handle_recover_full(sock) < 0)
					fprintf(stderr, "WARN: RECOVER_FULL failed\n");

			} else if (strcmp(cmd, CMD_PREP_NEXT) == 0) {
				handle_prep_next(sock);

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
