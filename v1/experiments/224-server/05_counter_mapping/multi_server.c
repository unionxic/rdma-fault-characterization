/*
 * multi_server.c -- Extended RDMA fault injection server
 *
 * Superset of server.c.  Adds:
 *   - SETUP_LARGE <buf_size>            Large-MR single QP (Condition B)
 *   - SETUP_LARGE_NOREMOTE <buf_size>   Large-MR without REMOTE_WRITE (B/REM_INV_REQ)
 *   - SETUP_MULTI_QP <count>            Multiple QPs (Condition C)
 *   - SETUP_MULTI_QP_SEND <count>       Multiple QPs, SEND/RECV mode (C/RNR_RETRY_EXC)
 *   - INJECT_QP <qp_idx> <scenario>     Fault on specific QP
 *   - CLEANUP_ALL                       Tear down all QPs
 *   - QUERY_STATE [qp_idx]              Query specific QP state
 *
 * All original single-QP commands work unchanged via slot 0.
 *
 * Build:  gcc -Wall -O2 -o multi_server multi_server.c -libverbs -lpthread
 */

#include "common.h"

/* ------------------------------------------------------------------ */
/*  Multi-QP data structures                                          */
/* ------------------------------------------------------------------ */

#define MAX_MULTI_QP  8
#define MAX_LARGE_BUF (16 * 1024 * 1024)

struct qp_slot {
	struct ibv_cq  *cq;
	struct ibv_qp  *qp;
	struct ibv_mr  *mr;
	void           *buf;
	size_t          buf_size;
	struct qp_info  local_info;
	struct qp_info  remote_info;
	int             active;
	int             remote_write_enabled;
};

struct multi_rdma_res {
	struct ibv_context *ctx;
	struct ibv_pd      *pd;
	struct qp_slot      qps[MAX_MULTI_QP];
	int                 num_qps;
	int                 gid_index;
	union ibv_gid       gid;
};

static struct multi_rdma_res mres;

static struct rdma_res legacy_res;
static int legacy_active = 0;

/* ------------------------------------------------------------------ */
/*  Device / PD lifecycle                                             */
/* ------------------------------------------------------------------ */

static int open_device(void)
{
	if (mres.ctx)
		return 0;

	mres.ctx = open_ib_device(IB_DEV_NAME);
	if (!mres.ctx) {
		fprintf(stderr, "Failed to open device %s\n", IB_DEV_NAME);
		return -1;
	}

	mres.pd = ibv_alloc_pd(mres.ctx);
	if (!mres.pd) {
		fprintf(stderr, "ibv_alloc_pd failed\n");
		ibv_close_device(mres.ctx);
		mres.ctx = NULL;
		return -1;
	}

	mres.gid_index = -1;
	for (int i = 0; i < 16; i++) {
		union ibv_gid g;
		if (ibv_query_gid(mres.ctx, IB_PORT, i, &g))
			break;
		if (g.raw[0] == 0 && g.raw[10] == 0xff && g.raw[11] == 0xff &&
		    (g.raw[12] != 0 || g.raw[13] != 0)) {
			mres.gid_index = i;
			mres.gid = g;
			break;
		}
	}
	if (mres.gid_index < 0) {
		fprintf(stderr, "No valid RoCEv2 GID found\n");
		ibv_dealloc_pd(mres.pd);
		mres.pd = NULL;
		ibv_close_device(mres.ctx);
		mres.ctx = NULL;
		return -1;
	}

	fprintf(stderr, "[multi_server] Device %s opened, GID index %d\n",
		IB_DEV_NAME, mres.gid_index);
	return 0;
}

static void close_device(void)
{
	if (mres.pd) {
		ibv_dealloc_pd(mres.pd);
		mres.pd = NULL;
	}
	if (mres.ctx) {
		ibv_close_device(mres.ctx);
		mres.ctx = NULL;
	}
	mres.gid_index = -1;
}

/* ------------------------------------------------------------------ */
/*  Per-slot setup / teardown                                         */
/* ------------------------------------------------------------------ */

static int setup_slot(int idx, size_t buf_size, int access_flags,
		      int remote_write)
{
	if (idx < 0 || idx >= MAX_MULTI_QP)
		return -1;

	struct qp_slot *s = &mres.qps[idx];
	if (s->active)
		return -1;

	if (open_device() < 0)
		return -1;

	s->cq = ibv_create_cq(mres.ctx, CQ_DEPTH, NULL, NULL, 0);
	if (!s->cq) {
		fprintf(stderr, "ibv_create_cq failed for slot %d\n", idx);
		return -1;
	}

	struct ibv_qp_init_attr qp_attr = {
		.send_cq = s->cq,
		.recv_cq = s->cq,
		.cap = {
			.max_send_wr  = MAX_WR,
			.max_recv_wr  = MAX_WR,
			.max_send_sge = MAX_SGE,
			.max_recv_sge = MAX_SGE,
		},
		.qp_type = IBV_QPT_RC,
	};
	s->qp = ibv_create_qp(mres.pd, &qp_attr);
	if (!s->qp) {
		fprintf(stderr, "ibv_create_qp failed for slot %d\n", idx);
		ibv_destroy_cq(s->cq);
		s->cq = NULL;
		return -1;
	}

	s->buf_size = buf_size;
	s->buf = calloc(1, buf_size);
	if (!s->buf) {
		ibv_destroy_qp(s->qp);
		s->qp = NULL;
		ibv_destroy_cq(s->cq);
		s->cq = NULL;
		return -1;
	}

	s->mr = ibv_reg_mr(mres.pd, s->buf, buf_size, access_flags);
	if (!s->mr) {
		fprintf(stderr, "ibv_reg_mr failed for slot %d: %s\n",
			idx, strerror(errno));
		free(s->buf);
		s->buf = NULL;
		ibv_destroy_qp(s->qp);
		s->qp = NULL;
		ibv_destroy_cq(s->cq);
		s->cq = NULL;
		return -1;
	}

	s->local_info.qpn  = s->qp->qp_num;
	s->local_info.psn  = rand() & 0xFFFFFF;
	s->local_info.rkey = s->mr->rkey;
	s->local_info.raddr = (uint64_t)s->buf;
	s->local_info.gid  = mres.gid;

	s->remote_write_enabled = remote_write;
	s->active = 1;
	return 0;
}

static int connect_slot(int idx, int retry_cnt, int rnr_retry, int timeout)
{
	struct qp_slot *s = &mres.qps[idx];
	if (!s->active || !s->qp)
		return -1;

	if (modify_qp_to_init(s->qp, s->remote_write_enabled) != 0) {
		fprintf(stderr, "modify_qp_to_init failed slot %d\n", idx);
		return -1;
	}
	if (modify_qp_to_rtr(s->qp, &s->remote_info, mres.gid_index) != 0) {
		fprintf(stderr, "modify_qp_to_rtr failed slot %d\n", idx);
		return -1;
	}
	if (modify_qp_to_rts(s->qp, s->local_info.psn,
			      retry_cnt, rnr_retry, timeout) != 0) {
		fprintf(stderr, "modify_qp_to_rts failed slot %d\n", idx);
		return -1;
	}
	return 0;
}

static void cleanup_slot(int idx)
{
	if (idx < 0 || idx >= MAX_MULTI_QP)
		return;

	struct qp_slot *s = &mres.qps[idx];
	if (!s->active)
		return;

	if (s->qp) { ibv_destroy_qp(s->qp); s->qp = NULL; }
	if (s->mr)  { ibv_dereg_mr(s->mr);   s->mr = NULL; }
	if (s->cq)  { ibv_destroy_cq(s->cq); s->cq = NULL; }
	free(s->buf);
	s->buf = NULL;
	s->buf_size = 0;
	s->active = 0;
	s->remote_write_enabled = 0;
	memset(&s->local_info, 0, sizeof(s->local_info));
	memset(&s->remote_info, 0, sizeof(s->remote_info));
}

static void cleanup_all_slots(void)
{
	for (int i = 0; i < MAX_MULTI_QP; i++)
		cleanup_slot(i);
	mres.num_qps = 0;
}

static void cleanup_everything(void)
{
	cleanup_all_slots();
	if (legacy_active) {
		cleanup_rdma(&legacy_res);
		legacy_active = 0;
	}
	close_device();
}

/* ------------------------------------------------------------------ */
/*  Backward-compatible single-QP commands                            */
/* ------------------------------------------------------------------ */

static int handle_setup(int conn, int use_send_recv, int enable_remote_write)
{
	cleanup_all_slots();
	if (legacy_active) {
		cleanup_rdma(&legacy_res);
		legacy_active = 0;
	}

	int access = IBV_ACCESS_LOCAL_WRITE;
	if (enable_remote_write)
		access |= IBV_ACCESS_REMOTE_WRITE | IBV_ACCESS_REMOTE_READ;

	if (setup_slot(0, BUF_SIZE, access, enable_remote_write) < 0)
		return -1;

	tcp_exchange_qp_info(conn, &mres.qps[0].local_info,
			     &mres.qps[0].remote_info, 1);

	if (connect_slot(0, 7, 7, 14) < 0)
		return -1;

	mres.num_qps = 1;

	if (use_send_recv)
		printf("  [server] SEND/RECV QP ready (no recv WQE posted)\n");
	else
		printf("  [server] WRITE QP ready (remote_write=%d)\n",
		       enable_remote_write);

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

static int handle_setup_boundary(int conn)
{
	cleanup_all_slots();
	if (legacy_active) {
		cleanup_rdma(&legacy_res);
		legacy_active = 0;
	}

	int access = IBV_ACCESS_LOCAL_WRITE | IBV_ACCESS_REMOTE_WRITE |
		     IBV_ACCESS_REMOTE_READ;

	if (setup_rdma(&legacy_res, 0, access, 7, 7, 14) < 0)
		return -1;

	ibv_dereg_mr(legacy_res.mr);
	free(legacy_res.buf);

	legacy_res.buf = calloc(1, BOUNDARY_BUF_SIZE);
	if (!legacy_res.buf)
		return -1;
	legacy_res.buf_size = BOUNDARY_BUF_SIZE;

	legacy_res.mr = ibv_reg_mr(legacy_res.pd, legacy_res.buf, MR_SIZE, access);
	if (!legacy_res.mr)
		return -1;

	legacy_res.local_info.rkey = legacy_res.mr->rkey;
	legacy_res.local_info.raddr = (uint64_t)legacy_res.buf;

	tcp_exchange_qp_info(conn, &legacy_res.local_info,
			     &legacy_res.remote_info, 1);

	if (connect_qp(&legacy_res, 1, 7, 7, 14) < 0)
		return -1;

	legacy_active = 1;
	printf("  [server] Boundary QP ready (buf=%d, mr=%d)\n",
	       BOUNDARY_BUF_SIZE, MR_SIZE);
	tcp_send_msg(conn, CMD_READY);
	return 0;
}

/* ------------------------------------------------------------------ */
/*  New: SETUP_LARGE / SETUP_LARGE_NOREMOTE                           */
/* ------------------------------------------------------------------ */

static int handle_setup_large_impl(int conn, const char *args,
				    int enable_remote_write)
{
	cleanup_all_slots();
	if (legacy_active) {
		cleanup_rdma(&legacy_res);
		legacy_active = 0;
	}

	unsigned long buf_size = 0;
	if (sscanf(args, "%lu", &buf_size) != 1 || buf_size == 0) {
		fprintf(stderr, "SETUP_LARGE: invalid buf_size '%s'\n", args);
		tcp_send_msg(conn, "ERROR invalid buf_size");
		return -1;
	}
	if (buf_size > MAX_LARGE_BUF) {
		fprintf(stderr, "SETUP_LARGE: buf_size %lu exceeds max %d\n",
			buf_size, MAX_LARGE_BUF);
		tcp_send_msg(conn, "ERROR buf_size too large");
		return -1;
	}

	int access = IBV_ACCESS_LOCAL_WRITE;
	if (enable_remote_write)
		access |= IBV_ACCESS_REMOTE_WRITE | IBV_ACCESS_REMOTE_READ;

	if (setup_slot(0, (size_t)buf_size, access, enable_remote_write) < 0) {
		tcp_send_msg(conn, "ERROR setup_slot failed");
		return -1;
	}

	tcp_exchange_qp_info(conn, &mres.qps[0].local_info,
			     &mres.qps[0].remote_info, 1);

	if (connect_slot(0, 7, 7, 14) < 0) {
		cleanup_slot(0);
		tcp_send_msg(conn, "ERROR connect failed");
		return -1;
	}

	mres.num_qps = 1;
	printf("  [server] LARGE QP ready (buf_size=%lu, remote_write=%d)\n",
	       buf_size, enable_remote_write);
	tcp_send_msg(conn, CMD_READY);
	return 0;
}

/* ------------------------------------------------------------------ */
/*  New: SETUP_MULTI_QP / SETUP_MULTI_QP_SEND                        */
/* ------------------------------------------------------------------ */

static int handle_setup_multi_qp_impl(int conn, const char *args,
				       int use_send_recv)
{
	cleanup_all_slots();
	if (legacy_active) {
		cleanup_rdma(&legacy_res);
		legacy_active = 0;
	}

	int count = 0;
	if (sscanf(args, "%d", &count) != 1 || count <= 0) {
		fprintf(stderr, "SETUP_MULTI_QP: invalid count '%s'\n", args);
		tcp_send_msg(conn, "ERROR invalid count");
		return -1;
	}
	if (count > MAX_MULTI_QP) {
		fprintf(stderr, "SETUP_MULTI_QP: count %d exceeds max %d\n",
			count, MAX_MULTI_QP);
		tcp_send_msg(conn, "ERROR count too large");
		return -1;
	}

	int access, remote_write;
	if (use_send_recv) {
		access = IBV_ACCESS_LOCAL_WRITE;
		remote_write = 0;
	} else {
		access = IBV_ACCESS_LOCAL_WRITE | IBV_ACCESS_REMOTE_WRITE |
			 IBV_ACCESS_REMOTE_READ;
		remote_write = 1;
	}

	for (int i = 0; i < count; i++) {
		if (setup_slot(i, BUF_SIZE, access, remote_write) < 0) {
			fprintf(stderr, "Failed to create slot %d\n", i);
			for (int j = 0; j < i; j++)
				cleanup_slot(j);
			tcp_send_msg(conn, "ERROR slot creation failed");
			return -1;
		}
	}

	for (int i = 0; i < count; i++) {
		tcp_exchange_qp_info(conn, &mres.qps[i].local_info,
				     &mres.qps[i].remote_info, 1);
		fprintf(stderr, "  [server] Slot %d: local qpn=%u <-> remote qpn=%u\n",
			i, mres.qps[i].local_info.qpn,
			mres.qps[i].remote_info.qpn);
	}

	for (int i = 0; i < count; i++) {
		if (connect_slot(i, 7, 7, 14) < 0) {
			fprintf(stderr, "Failed to connect slot %d\n", i);
			cleanup_all_slots();
			tcp_send_msg(conn, "ERROR connect failed");
			return -1;
		}
	}

	mres.num_qps = count;
	printf("  [server] Multi-QP ready: %d QPs (send_recv=%d)\n",
	       count, use_send_recv);
	tcp_send_msg(conn, CMD_READY);
	return 0;
}

/* ------------------------------------------------------------------ */
/*  INJECT -- original (backward compat) and INJECT_QP (new)          */
/* ------------------------------------------------------------------ */

static int do_inject(int conn, int scenario, int qp_idx)
{
	struct ibv_qp *target_qp = NULL;

	if (legacy_active) {
		target_qp = legacy_res.qp;
	} else if (qp_idx >= 0 && qp_idx < MAX_MULTI_QP &&
		   mres.qps[qp_idx].active) {
		target_qp = mres.qps[qp_idx].qp;
	}

	switch (scenario) {
	case REM_INV_REQ:
		printf("  [server] REM_INV_REQ: QP has no REMOTE_WRITE [slot %d]\n",
		       qp_idx);
		break;

	case RNR_RETRY_EXC:
		printf("  [server] RNR_RETRY_EXC: no recv WQE posted [slot %d]\n",
		       qp_idx);
		break;

	case RETRY_EXC_QP_ERR: {
		if (!target_qp) {
			fprintf(stderr, "INJECT RETRY_EXC_QP_ERR: no QP for slot %d\n",
				qp_idx);
			tcp_send_msg(conn, "ERROR no qp");
			return -1;
		}
		struct ibv_qp_attr attr = { .qp_state = IBV_QPS_ERR };
		if (ibv_modify_qp(target_qp, &attr, IBV_QP_STATE) < 0) {
			perror("ibv_modify_qp(ERR)");
			tcp_send_msg(conn, "ERROR modify_qp failed");
			return -1;
		}
		printf("  [server] RETRY_EXC_QP_ERR: QP moved to ERR [slot %d]\n", qp_idx);
		break;
	}

	default:
		printf("  [server] scenario %d: no action [slot %d]\n",
		       scenario, qp_idx);
		break;
	}

	tcp_send_msg(conn, CMD_DONE);
	return 0;
}

/* "INJECT <scenario> [qp_idx]" — backward compatible, scenario first */
static int handle_inject(int conn, const char *args)
{
	int scenario = 0, qp_idx = 0;
	sscanf(args, "%d %d", &scenario, &qp_idx);
	return do_inject(conn, scenario, qp_idx);
}

/* "INJECT_QP <qp_idx> <scenario>" — new command, qp_idx first */
static int handle_inject_qp(int conn, const char *args)
{
	int qp_idx = 0, scenario = 0;
	if (sscanf(args, "%d %d", &qp_idx, &scenario) < 2) {
		fprintf(stderr, "INJECT_QP: bad args '%s'\n", args);
		tcp_send_msg(conn, "ERROR bad inject_qp args");
		return -1;
	}
	return do_inject(conn, scenario, qp_idx);
}

/* ------------------------------------------------------------------ */
/*  QUERY_STATE [qp_idx]                                              */
/* ------------------------------------------------------------------ */

static void handle_query_state(int conn, const char *args)
{
	int qp_idx = 0;
	if (args && *args)
		sscanf(args, "%d", &qp_idx);

	struct ibv_qp *target_qp = NULL;

	if (legacy_active)
		target_qp = legacy_res.qp;
	else if (qp_idx >= 0 && qp_idx < MAX_MULTI_QP &&
		 mres.qps[qp_idx].active)
		target_qp = mres.qps[qp_idx].qp;

	if (!target_qp) {
		tcp_send_msg(conn, "QP_STATE=-1");
		return;
	}

	struct ibv_qp_attr qattr;
	struct ibv_qp_init_attr qinit;
	if (ibv_query_qp(target_qp, &qattr, IBV_QP_STATE, &qinit) != 0) {
		tcp_send_msg(conn, "QP_STATE=-2");
		return;
	}

	char resp[32];
	snprintf(resp, sizeof(resp), "QP_STATE=%d", qattr.qp_state);
	tcp_send_msg(conn, resp);
}

/* ------------------------------------------------------------------ */
/*  INIT_BUFFER / CHECK_BUFFER                                        */
/* ------------------------------------------------------------------ */

static void handle_init_buffer(int conn)
{
	if (legacy_active) {
		memset(legacy_res.buf, 0, legacy_res.buf_size);
		printf("  [server] Buffer zeroed (%zu bytes, legacy)\n",
		       legacy_res.buf_size);
	} else if (mres.qps[0].active) {
		memset(mres.qps[0].buf, 0, mres.qps[0].buf_size);
		printf("  [server] Buffer zeroed (%zu bytes, slot 0)\n",
		       mres.qps[0].buf_size);
	}
	tcp_send_msg(conn, CMD_DONE);
}

static void handle_check_buffer(int conn, const char *args)
{
	int offset = 0, length = 0;
	sscanf(args, "%d %d", &offset, &length);

	void *buf;
	size_t total_buf_size;
	int mr_end;

	if (legacy_active) {
		buf = legacy_res.buf;
		total_buf_size = legacy_res.buf_size;
		mr_end = MR_SIZE;
	} else if (mres.qps[0].active) {
		buf = mres.qps[0].buf;
		total_buf_size = mres.qps[0].buf_size;
		mr_end = (int)mres.qps[0].buf_size;
	} else {
		tcp_send_msg(conn, "ERROR no buffer");
		return;
	}

	unsigned char *p = (unsigned char *)buf;
	int within_end = (offset + length < mr_end) ?
			 offset + length : mr_end;
	int within_mod = 0;
	for (int i = offset; i < within_end; i++)
		if (p[i] != 0) within_mod++;

	int beyond_start = mr_end;
	int beyond_end = offset + length;
	if (beyond_end > (int)total_buf_size)
		beyond_end = (int)total_buf_size;
	int beyond_mod = 0;
	for (int i = beyond_start; i < beyond_end; i++)
		if (p[i] != 0) beyond_mod++;

	char resp[128];
	snprintf(resp, sizeof(resp), "PARTIAL:%d/%d:%d/%d",
		 within_mod, within_end - offset,
		 beyond_mod, beyond_end - beyond_start);
	printf("  [server] %s\n", resp);
	tcp_send_msg(conn, resp);
}

/* ------------------------------------------------------------------ */
/*  CLEANUP                                                           */
/* ------------------------------------------------------------------ */

static void handle_cleanup(int conn)
{
	if (legacy_active) {
		cleanup_rdma(&legacy_res);
		legacy_active = 0;
	} else {
		cleanup_all_slots();
	}
	close_device();
	printf("  [server] RDMA resources cleaned up\n");
	tcp_send_msg(conn, CMD_DONE);
}

static void handle_cleanup_all(int conn)
{
	cleanup_everything();
	printf("  [server] All RDMA resources cleaned up\n");
	tcp_send_msg(conn, CMD_DONE);
}

/* ------------------------------------------------------------------ */
/*  Command dispatch                                                  */
/* ------------------------------------------------------------------ */

#define CMD_SETUP_LARGE          "SETUP_LARGE"
#define CMD_SETUP_LARGE_NOREMOTE "SETUP_LARGE_NOREMOTE"
#define CMD_SETUP_MULTI_QP       "SETUP_MULTI_QP"
#define CMD_SETUP_MULTI_QP_SEND  "SETUP_MULTI_QP_SEND"
#define CMD_INJECT_QP            "INJECT_QP"
#define CMD_CLEANUP_ALL          "CLEANUP_ALL"

static void run_server(void)
{
	int listen_sock = tcp_listen(TCP_CTRL_PORT);
	if (listen_sock < 0) {
		fprintf(stderr, "Failed to listen on port %d\n", TCP_CTRL_PORT);
		exit(1);
	}
	printf("Multi-server listening on port %d\n", TCP_CTRL_PORT);

	while (1) {
		struct sockaddr_in client_addr;
		socklen_t addr_len = sizeof(client_addr);
		int conn = accept(listen_sock, (struct sockaddr *)&client_addr,
				  &addr_len);
		if (conn < 0) {
			perror("accept");
			continue;
		}
		/* Nagle+delayed-ACK가 lockstep 왕복(RETRY_EXC_QP_ERR의 CMD_INJECT
		 * 왕복 등, 측정 구간 t_inject..t_detect 안에 포함됨)에 ~40ms floor를
		 * 만든다 — server.c와 동일하게 비활성화. (2026-09-15) */
		int flag = 1;
		setsockopt(conn, IPPROTO_TCP, TCP_NODELAY, &flag, sizeof(flag));
		printf("Client connected\n");

		char cmd[256];
		while (tcp_recv_msg(conn, cmd, sizeof(cmd)) > 0) {
			printf("[server] cmd: %s\n", cmd);

			/*
			 * Longer prefixes first to avoid false matches.
			 * SETUP_MULTI_QP_SEND before SETUP_MULTI_QP
			 * SETUP_LARGE_NOREMOTE before SETUP_LARGE
			 * INJECT_QP before INJECT
			 * CLEANUP_ALL before CLEANUP
			 */

			if (strncmp(cmd, CMD_SETUP_MULTI_QP_SEND,
				    strlen(CMD_SETUP_MULTI_QP_SEND)) == 0) {
				const char *a = cmd + strlen(CMD_SETUP_MULTI_QP_SEND);
				if (*a == ' ') a++;
				if (handle_setup_multi_qp_impl(conn, a, 1) < 0)
					fprintf(stderr, "setup_multi_qp_send failed\n");

			} else if (strncmp(cmd, CMD_SETUP_MULTI_QP,
					   strlen(CMD_SETUP_MULTI_QP)) == 0) {
				const char *a = cmd + strlen(CMD_SETUP_MULTI_QP);
				if (*a == ' ') a++;
				if (handle_setup_multi_qp_impl(conn, a, 0) < 0)
					fprintf(stderr, "setup_multi_qp failed\n");

			} else if (strncmp(cmd, CMD_SETUP_LARGE_NOREMOTE,
					   strlen(CMD_SETUP_LARGE_NOREMOTE)) == 0) {
				const char *a = cmd + strlen(CMD_SETUP_LARGE_NOREMOTE);
				if (*a == ' ') a++;
				if (handle_setup_large_impl(conn, a, 0) < 0)
					fprintf(stderr, "setup_large_noremote failed\n");

			} else if (strncmp(cmd, CMD_SETUP_LARGE,
					   strlen(CMD_SETUP_LARGE)) == 0) {
				const char *a = cmd + strlen(CMD_SETUP_LARGE);
				if (*a == ' ') a++;
				if (handle_setup_large_impl(conn, a, 1) < 0)
					fprintf(stderr, "setup_large failed\n");

			} else if (strncmp(cmd, CMD_SETUP_SEND,
					   strlen(CMD_SETUP_SEND)) == 0) {
				if (handle_setup_send_recv(conn) < 0)
					fprintf(stderr, "setup_send_recv failed\n");

			} else if (strncmp(cmd, CMD_SETUP_NOREMOTE,
					   strlen(CMD_SETUP_NOREMOTE)) == 0) {
				if (handle_setup_no_remote_write(conn) < 0)
					fprintf(stderr, "setup_no_remote failed\n");

			} else if (strncmp(cmd, CMD_SETUP_BOUNDARY,
					   strlen(CMD_SETUP_BOUNDARY)) == 0) {
				if (handle_setup_boundary(conn) < 0)
					fprintf(stderr, "setup_boundary failed\n");

			} else if (strncmp(cmd, CMD_SETUP,
					   strlen(CMD_SETUP)) == 0) {
				if (handle_setup_normal(conn) < 0)
					fprintf(stderr, "setup failed\n");

			} else if (strncmp(cmd, CMD_INJECT_QP,
					   strlen(CMD_INJECT_QP)) == 0) {
				const char *a = cmd + strlen(CMD_INJECT_QP);
				if (*a == ' ') a++;
				if (handle_inject_qp(conn, a) < 0)
					fprintf(stderr, "inject_qp failed\n");

			} else if (strncmp(cmd, CMD_INJECT,
					   strlen(CMD_INJECT)) == 0) {
				const char *a = cmd + strlen(CMD_INJECT);
				if (*a == ' ') a++;
				if (handle_inject(conn, a) < 0)
					fprintf(stderr, "inject failed\n");

			} else if (strcmp(cmd, CMD_INIT_BUFFER) == 0) {
				handle_init_buffer(conn);

			} else if (strncmp(cmd, CMD_CHECK_BUFFER,
					   strlen(CMD_CHECK_BUFFER)) == 0) {
				handle_check_buffer(conn,
					cmd + strlen(CMD_CHECK_BUFFER) + 1);

			} else if (strcmp(cmd, CMD_CLEANUP_ALL) == 0) {
				handle_cleanup_all(conn);

			} else if (strcmp(cmd, CMD_CLEANUP) == 0) {
				handle_cleanup(conn);

			} else if (strncmp(cmd, CMD_QUERY_STATE,
					   strlen(CMD_QUERY_STATE)) == 0) {
				const char *a = cmd + strlen(CMD_QUERY_STATE);
				if (*a == ' ') a++;
				handle_query_state(conn, a);

			} else if (strcmp(cmd, CMD_SHUTDOWN) == 0) {
				cleanup_everything();
				tcp_send_msg(conn, CMD_DONE);
				close(conn);
				close(listen_sock);
				printf("Server shutting down\n");
				return;

			} else {
				fprintf(stderr, "Unknown command: %s\n", cmd);
				tcp_send_msg(conn, "ERROR unknown command");
			}
		}

		printf("Client disconnected\n");
		cleanup_everything();
		close(conn);
	}
}

int main(void)
{
	srand(time(NULL));
	memset(&mres, 0, sizeof(mres));
	memset(&legacy_res, 0, sizeof(legacy_res));
	run_server();
	return 0;
}
