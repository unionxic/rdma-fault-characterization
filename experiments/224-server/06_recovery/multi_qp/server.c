/*
 * Multi-QP isolation experiment — server (224)
 *
 * Manages two QPs (A and B) sharing one PD/ctx but with separate CQs.
 * Tests: (1) fault on QP_B doesn't affect QP_A, (2) concurrent different
 * faults on both QPs with independent recovery.
 *
 * Usage: ./server
 */

#include "../recovery_common.h"

#define MR_ACCESS  (IBV_ACCESS_LOCAL_WRITE | IBV_ACCESS_REMOTE_WRITE | \
		    IBV_ACCESS_REMOTE_READ)

#define CMD_SETUP_MULTI      "SETUP_MULTI"
#define CMD_INJECT_FAULT_B   "INJECT_FAULT_B"
#define CMD_RECOVER_QP_B     "RECOVER_QP_B"
#define CMD_SETUP_CONCURRENT "SETUP_CONCURRENT"
#define CMD_INJECT_CONCURRENT "INJECT_CONCURRENT"
#define CMD_RECOVER_CONCURRENT "RECOVER_CONCURRENT"

struct multi_res {
	struct ibv_context *ctx;
	struct ibv_pd *pd;
	struct ibv_cq *cq_a, *cq_b;
	struct ibv_qp *qp_a, *qp_b;
	struct ibv_mr *mr_a, *mr_b;
	void *buf_a, *buf_b;
	int gid_index;
	union ibv_gid gid;
	struct qp_info local_a, remote_a;
	struct qp_info local_b, remote_b;
};

static struct multi_res mres;
static int mres_active = 0;

/* ------------------------------------------------------------------ */
/*  Resource management                                                */
/* ------------------------------------------------------------------ */

static int find_rocev2_gid(struct ibv_context *ctx, int *gid_idx,
			   union ibv_gid *gid)
{
	for (int i = 0; i < 16; i++) {
		union ibv_gid g;
		if (ibv_query_gid(ctx, IB_PORT, i, &g))
			break;
		if (g.raw[0] == 0 && g.raw[10] == 0xff && g.raw[11] == 0xff &&
		    (g.raw[12] != 0 || g.raw[13] != 0)) {
			*gid_idx = i;
			*gid = g;
			return 0;
		}
	}
	return -1;
}

static int alloc_multi_resources(void)
{
	memset(&mres, 0, sizeof(mres));

	mres.ctx = open_ib_device(IB_DEV_NAME);
	if (!mres.ctx) {
		fprintf(stderr, "ERROR: open_ib_device failed\n");
		return -1;
	}

	mres.pd = ibv_alloc_pd(mres.ctx);
	if (!mres.pd) {
		fprintf(stderr, "ERROR: ibv_alloc_pd failed\n");
		return -1;
	}

	mres.cq_a = ibv_create_cq(mres.ctx, CQ_DEPTH, NULL, NULL, 0);
	mres.cq_b = ibv_create_cq(mres.ctx, CQ_DEPTH, NULL, NULL, 0);
	if (!mres.cq_a || !mres.cq_b) {
		fprintf(stderr, "ERROR: ibv_create_cq failed\n");
		return -1;
	}

	struct ibv_qp_init_attr qp_attr = {
		.send_cq = mres.cq_a,
		.recv_cq = mres.cq_a,
		.cap = {
			.max_send_wr = MAX_WR,
			.max_recv_wr = MAX_WR,
			.max_send_sge = MAX_SGE,
			.max_recv_sge = MAX_SGE,
		},
		.qp_type = IBV_QPT_RC,
	};
	mres.qp_a = ibv_create_qp(mres.pd, &qp_attr);
	if (!mres.qp_a) {
		fprintf(stderr, "ERROR: ibv_create_qp(A) failed\n");
		return -1;
	}

	qp_attr.send_cq = mres.cq_b;
	qp_attr.recv_cq = mres.cq_b;
	mres.qp_b = ibv_create_qp(mres.pd, &qp_attr);
	if (!mres.qp_b) {
		fprintf(stderr, "ERROR: ibv_create_qp(B) failed\n");
		return -1;
	}

	mres.buf_a = calloc(1, BUF_SIZE);
	mres.buf_b = calloc(1, BUF_SIZE);
	if (!mres.buf_a || !mres.buf_b) {
		fprintf(stderr, "ERROR: buffer allocation failed\n");
		return -1;
	}

	mres.mr_a = ibv_reg_mr(mres.pd, mres.buf_a, BUF_SIZE, MR_ACCESS);
	mres.mr_b = ibv_reg_mr(mres.pd, mres.buf_b, BUF_SIZE, MR_ACCESS);
	if (!mres.mr_a || !mres.mr_b) {
		fprintf(stderr, "ERROR: ibv_reg_mr failed: %s\n", strerror(errno));
		return -1;
	}

	if (find_rocev2_gid(mres.ctx, &mres.gid_index, &mres.gid) < 0) {
		fprintf(stderr, "ERROR: no valid RoCEv2 GID found\n");
		return -1;
	}
	fprintf(stderr, "[setup] Using GID index %d\n", mres.gid_index);

	mres.local_a.qpn = mres.qp_a->qp_num;
	mres.local_a.psn = rand() & 0xFFFFFF;
	mres.local_a.rkey = mres.mr_a->rkey;
	mres.local_a.raddr = (uint64_t)mres.buf_a;
	mres.local_a.gid = mres.gid;

	mres.local_b.qpn = mres.qp_b->qp_num;
	mres.local_b.psn = rand() & 0xFFFFFF;
	mres.local_b.rkey = mres.mr_b->rkey;
	mres.local_b.raddr = (uint64_t)mres.buf_b;
	mres.local_b.gid = mres.gid;

	return 0;
}

static int connect_single_qp(struct ibv_qp *qp, uint32_t local_psn,
			      struct qp_info *remote)
{
	if (modify_qp_to_init(qp, 1)) {
		fprintf(stderr, "ERROR: modify_qp_to_init failed: %s\n",
			strerror(errno));
		return -1;
	}
	if (modify_qp_to_rtr(qp, remote, mres.gid_index)) {
		fprintf(stderr, "ERROR: modify_qp_to_rtr failed: %s\n",
			strerror(errno));
		return -1;
	}
	if (modify_qp_to_rts(qp, local_psn, 7, 7, 14)) {
		fprintf(stderr, "ERROR: modify_qp_to_rts failed: %s\n",
			strerror(errno));
		return -1;
	}
	return 0;
}

static void cleanup_multi(void)
{
	if (mres.qp_a) ibv_destroy_qp(mres.qp_a);
	if (mres.qp_b) ibv_destroy_qp(mres.qp_b);
	if (mres.mr_a) ibv_dereg_mr(mres.mr_a);
	if (mres.mr_b) ibv_dereg_mr(mres.mr_b);
	if (mres.cq_a) ibv_destroy_cq(mres.cq_a);
	if (mres.cq_b) ibv_destroy_cq(mres.cq_b);
	if (mres.pd) ibv_dealloc_pd(mres.pd);
	if (mres.ctx) ibv_close_device(mres.ctx);
	free(mres.buf_a);
	free(mres.buf_b);
	memset(&mres, 0, sizeof(mres));
	mres_active = 0;
}

/* ------------------------------------------------------------------ */
/*  Command: SETUP_MULTI                                               */
/*  Create 2 QPs, exchange info, connect both                          */
/* ------------------------------------------------------------------ */

static int handle_setup_multi(int sock)
{
	fprintf(stderr, "[cmd] SETUP_MULTI\n");

	if (mres_active)
		cleanup_multi();

	if (alloc_multi_resources() < 0)
		return -1;
	mres_active = 1;

	tcp_send_msg(sock, CMD_READY);

	if (tcp_exchange_qp_info(sock, &mres.local_a, &mres.remote_a, 1) < 0) {
		fprintf(stderr, "ERROR: QP_A info exchange failed\n");
		return -1;
	}
	if (tcp_exchange_qp_info(sock, &mres.local_b, &mres.remote_b, 1) < 0) {
		fprintf(stderr, "ERROR: QP_B info exchange failed\n");
		return -1;
	}

	if (connect_single_qp(mres.qp_a, mres.local_a.psn, &mres.remote_a) < 0) {
		fprintf(stderr, "ERROR: connect QP_A failed\n");
		return -1;
	}
	if (connect_single_qp(mres.qp_b, mres.local_b.psn, &mres.remote_b) < 0) {
		fprintf(stderr, "ERROR: connect QP_B failed\n");
		return -1;
	}

	fprintf(stderr, "  QP_A (qpn=%u) and QP_B (qpn=%u) connected\n",
		mres.qp_a->qp_num, mres.qp_b->qp_num);
	return 0;
}

/* ------------------------------------------------------------------ */
/*  Command: INJECT_FAULT_B                                            */
/*  Move QP_B to ERR, QP_A untouched                                   */
/* ------------------------------------------------------------------ */

static int handle_inject_fault_b(int sock)
{
	fprintf(stderr, "[cmd] INJECT_FAULT_B\n");

	if (!mres_active) {
		fprintf(stderr, "ERROR: no active resources\n");
		return -1;
	}

	struct ibv_qp_attr attr = { .qp_state = IBV_QPS_ERR };
	if (ibv_modify_qp(mres.qp_b, &attr, IBV_QP_STATE) != 0) {
		fprintf(stderr, "ERROR: ibv_modify_qp(B, ERR) failed: %s\n",
			strerror(errno));
		return -1;
	}

	fprintf(stderr, "  QP_B moved to ERR, QP_A untouched\n");
	tcp_send_msg(sock, CMD_READY);
	return 0;
}

/* ------------------------------------------------------------------ */
/*  Command: RECOVER_QP_B                                              */
/*  Reset QP_B, new PSN, re-exchange, reconnect. QP_A untouched.       */
/* ------------------------------------------------------------------ */

static int handle_recover_qp_b(int sock)
{
	fprintf(stderr, "[cmd] RECOVER_QP_B\n");

	if (!mres_active) {
		fprintf(stderr, "ERROR: no active resources\n");
		return -1;
	}

	int drained = drain_cq(mres.cq_b);
	if (drained > 0)
		fprintf(stderr, "  drained %d CQ_B entries\n", drained);

	if (reset_qp_to_reset(mres.qp_b) < 0)
		return -1;

	mres.local_b.psn = rand() & 0xFFFFFF;

	if (tcp_exchange_qp_info(sock, &mres.local_b, &mres.remote_b, 1) < 0)
		return -1;

	if (connect_single_qp(mres.qp_b, mres.local_b.psn, &mres.remote_b) < 0) {
		fprintf(stderr, "ERROR: reconnect QP_B failed\n");
		return -1;
	}

	tcp_send_msg(sock, CMD_READY);
	fprintf(stderr, "  QP_B recovered (new psn=0x%x)\n", mres.local_b.psn);
	return 0;
}

/* ------------------------------------------------------------------ */
/*  Command: SETUP_CONCURRENT                                          */
/*  Create 2 QPs for concurrent fault test                             */
/* ------------------------------------------------------------------ */

static int handle_setup_concurrent(int sock)
{
	fprintf(stderr, "[cmd] SETUP_CONCURRENT\n");

	if (mres_active)
		cleanup_multi();

	if (alloc_multi_resources() < 0)
		return -1;
	mres_active = 1;

	tcp_send_msg(sock, CMD_READY);

	if (tcp_exchange_qp_info(sock, &mres.local_a, &mres.remote_a, 1) < 0) {
		fprintf(stderr, "ERROR: QP_A info exchange failed\n");
		return -1;
	}
	if (tcp_exchange_qp_info(sock, &mres.local_b, &mres.remote_b, 1) < 0) {
		fprintf(stderr, "ERROR: QP_B info exchange failed\n");
		return -1;
	}

	if (connect_single_qp(mres.qp_a, mres.local_a.psn, &mres.remote_a) < 0) {
		fprintf(stderr, "ERROR: connect QP_A failed\n");
		return -1;
	}
	if (connect_single_qp(mres.qp_b, mres.local_b.psn, &mres.remote_b) < 0) {
		fprintf(stderr, "ERROR: connect QP_B failed\n");
		return -1;
	}

	fprintf(stderr, "  QP_A (qpn=%u) and QP_B (qpn=%u) connected (concurrent mode)\n",
		mres.qp_a->qp_num, mres.qp_b->qp_num);
	return 0;
}

/* ------------------------------------------------------------------ */
/*  Command: INJECT_CONCURRENT                                         */
/*  QP_A: deregister MR (→ REM_ACCESS_ERR)                            */
/*  QP_B: move to ERR (→ RETRY_EXC_ERR)                               */
/* ------------------------------------------------------------------ */

static int handle_inject_concurrent(int sock)
{
	fprintf(stderr, "[cmd] INJECT_CONCURRENT\n");

	if (!mres_active) {
		fprintf(stderr, "ERROR: no active resources\n");
		return -1;
	}

	uint32_t old_rkey = mres.mr_a->rkey;
	if (ibv_dereg_mr(mres.mr_a) != 0) {
		fprintf(stderr, "ERROR: ibv_dereg_mr(A) failed: %s\n",
			strerror(errno));
		return -1;
	}
	mres.mr_a = NULL;
	fprintf(stderr, "  QP_A: MR deregistered (rkey=0x%x now invalid)\n",
		old_rkey);

	struct ibv_qp_attr attr = { .qp_state = IBV_QPS_ERR };
	if (ibv_modify_qp(mres.qp_b, &attr, IBV_QP_STATE) != 0) {
		fprintf(stderr, "ERROR: ibv_modify_qp(B, ERR) failed: %s\n",
			strerror(errno));
		return -1;
	}
	fprintf(stderr, "  QP_B: moved to ERR\n");

	tcp_send_msg(sock, CMD_READY);
	return 0;
}

/* ------------------------------------------------------------------ */
/*  Command: RECOVER_CONCURRENT                                        */
/*  QP_A: re-register MR, reset QP, new PSN                           */
/*  QP_B: reset QP, new PSN                                           */
/* ------------------------------------------------------------------ */

static int handle_recover_concurrent(int sock)
{
	fprintf(stderr, "[cmd] RECOVER_CONCURRENT\n");

	if (!mres_active) {
		fprintf(stderr, "ERROR: no active resources\n");
		return -1;
	}

	/* QP_A: re-register MR, drain, reset */
	mres.mr_a = ibv_reg_mr(mres.pd, mres.buf_a, BUF_SIZE, MR_ACCESS);
	if (!mres.mr_a) {
		fprintf(stderr, "ERROR: ibv_reg_mr(A) failed: %s\n",
			strerror(errno));
		return -1;
	}

	int drained_a = drain_cq(mres.cq_a);
	if (drained_a > 0)
		fprintf(stderr, "  drained %d CQ_A entries\n", drained_a);

	if (reset_qp_to_reset(mres.qp_a) < 0)
		return -1;

	mres.local_a.psn = rand() & 0xFFFFFF;
	mres.local_a.rkey = mres.mr_a->rkey;
	mres.local_a.raddr = (uint64_t)mres.buf_a;

	/* QP_B: drain, reset */
	int drained_b = drain_cq(mres.cq_b);
	if (drained_b > 0)
		fprintf(stderr, "  drained %d CQ_B entries\n", drained_b);

	if (reset_qp_to_reset(mres.qp_b) < 0)
		return -1;

	mres.local_b.psn = rand() & 0xFFFFFF;

	/* Exchange new info for both QPs */
	if (tcp_exchange_qp_info(sock, &mres.local_a, &mres.remote_a, 1) < 0)
		return -1;
	if (tcp_exchange_qp_info(sock, &mres.local_b, &mres.remote_b, 1) < 0)
		return -1;

	/* Reconnect both */
	if (connect_single_qp(mres.qp_a, mres.local_a.psn, &mres.remote_a) < 0) {
		fprintf(stderr, "ERROR: reconnect QP_A failed\n");
		return -1;
	}
	if (connect_single_qp(mres.qp_b, mres.local_b.psn, &mres.remote_b) < 0) {
		fprintf(stderr, "ERROR: reconnect QP_B failed\n");
		return -1;
	}

	tcp_send_msg(sock, CMD_READY);
	fprintf(stderr, "  both QPs recovered (A: rkey=0x%x, B: psn=0x%x)\n",
		mres.mr_a->rkey, mres.local_b.psn);
	return 0;
}

/* ------------------------------------------------------------------ */
/*  Command: CLEANUP                                                   */
/* ------------------------------------------------------------------ */

static int handle_cleanup(int sock)
{
	fprintf(stderr, "[cmd] CLEANUP\n");

	if (mres_active)
		cleanup_multi();

	tcp_send_msg(sock, CMD_DONE);
	return 0;
}

/* ------------------------------------------------------------------ */
/*  main                                                               */
/* ------------------------------------------------------------------ */

int main(void)
{
	srand(time(NULL));

	int listen_sock = tcp_listen(TCP_CTRL_PORT);
	if (listen_sock < 0) {
		fprintf(stderr, "ERROR: tcp_listen failed\n");
		return 1;
	}
	fprintf(stderr, "Multi-QP server listening on port %d\n", TCP_CTRL_PORT);

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

			if (strcmp(cmd, CMD_SETUP_MULTI) == 0) {
				if (handle_setup_multi(sock) < 0)
					fprintf(stderr, "WARN: SETUP_MULTI failed\n");

			} else if (strcmp(cmd, CMD_INJECT_FAULT_B) == 0) {
				if (handle_inject_fault_b(sock) < 0)
					fprintf(stderr, "WARN: INJECT_FAULT_B failed\n");

			} else if (strcmp(cmd, CMD_RECOVER_QP_B) == 0) {
				if (handle_recover_qp_b(sock) < 0)
					fprintf(stderr, "WARN: RECOVER_QP_B failed\n");

			} else if (strcmp(cmd, CMD_SETUP_CONCURRENT) == 0) {
				if (handle_setup_concurrent(sock) < 0)
					fprintf(stderr, "WARN: SETUP_CONCURRENT failed\n");

			} else if (strcmp(cmd, CMD_INJECT_CONCURRENT) == 0) {
				if (handle_inject_concurrent(sock) < 0)
					fprintf(stderr, "WARN: INJECT_CONCURRENT failed\n");

			} else if (strcmp(cmd, CMD_RECOVER_CONCURRENT) == 0) {
				if (handle_recover_concurrent(sock) < 0)
					fprintf(stderr, "WARN: RECOVER_CONCURRENT failed\n");

			} else if (strcmp(cmd, CMD_CLEANUP) == 0) {
				handle_cleanup(sock);

			} else if (strcmp(cmd, CMD_SHUTDOWN) == 0) {
				fprintf(stderr, "[cmd] SHUTDOWN\n");
				if (mres_active)
					cleanup_multi();
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
