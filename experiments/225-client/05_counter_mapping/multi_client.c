/*
 * multi_client.c -- Fault injection under realistic traffic conditions.
 *
 * Tests whether error fingerprints (vendor_err + counter delta) observed
 * in single-WR experiments remain stable under three conditions:
 *
 *   Condition A (MULTI_WR):  N normal WRs in-flight, then 1 faulty WR.
 *   Condition B (LARGE_MSG): Single large RDMA WRITE (multi-packet).
 *   Condition C (MULTI_QP):  4 QPs; inject fault on QP #0 only.
 *
 * Fault scenarios tested: LOC_PROT_LEN, LOC_PROT_LKEY, REM_INV_REQ, REM_ACCESS_RKEY, RNR_RETRY_EXC, RETRY_EXC_QP_ERR, REM_ACCESS_ADDR.
 *
 * Usage: ./multi_client <condition> <scenario> [num_trials]
 *   condition: A, B, or C
 *   scenario:  scenario ID (1,2,5,6,7,8,9)
 *   num_trials: default 10
 *
 * Requires: multi_server running on 10.0.0.3:18515
 *           counter_daemon running on SERVER_224_ADDR:18516
 *
 * CSV output to: results/multi/<condition>_<scenario>.csv
 */

#include "multi_common.h"
#include <getopt.h>
#include <sys/stat.h>

/* ------------------------------------------------------------------ */
/*  Globals                                                           */
/* ------------------------------------------------------------------ */

static int ctrl_sock = -1;
static int num_trials = 10;

/* ------------------------------------------------------------------ */
/*  Server communication helpers                                      */
/* ------------------------------------------------------------------ */

static int send_cmd_wait(int sock, const char *cmd, const char *expect)
{
	tcp_send_msg(sock, cmd);
	char resp[256];
	tcp_recv_msg(sock, resp, sizeof(resp));
	if (expect && strcmp(resp, expect) != 0) {
		fprintf(stderr, "Expected '%s', got '%s'\n", expect, resp);
		return -1;
	}
	return 0;
}

/* ------------------------------------------------------------------ */
/*  Supported scenario list                                           */
/* ------------------------------------------------------------------ */

static const enum scenario supported_scenarios[] = {
	LOC_PROT_LEN,
	LOC_PROT_LKEY,
	REM_INV_REQ,
	REM_ACCESS_RKEY,
	RNR_RETRY_EXC,
	RETRY_EXC_QP_ERR,
	REM_ACCESS_ADDR,
};
#define NUM_SUPPORTED (sizeof(supported_scenarios) / sizeof(supported_scenarios[0]))

static int is_supported(enum scenario sc)
{
	for (size_t i = 0; i < NUM_SUPPORTED; i++)
		if (supported_scenarios[i] == sc)
			return 1;
	return 0;
}

/* ------------------------------------------------------------------ */
/*  QP parameter selection per scenario                               */
/* ------------------------------------------------------------------ */

struct qp_params {
	int access_flags;
	int retry_cnt;
	int rnr_retry;
	int timeout;
	int remote_write;   /* 1 = connect QP with REMOTE_WRITE access */
	int use_send;       /* 1 = SEND/RECV mode (for RNR_RETRY_EXC) */
};

static void get_qp_params(enum scenario sc, struct qp_params *p)
{
	p->access_flags = IBV_ACCESS_LOCAL_WRITE | IBV_ACCESS_REMOTE_WRITE |
			  IBV_ACCESS_REMOTE_READ;
	p->retry_cnt = 7;
	p->rnr_retry = 7;
	p->timeout = 14;
	p->remote_write = 1;
	p->use_send = 0;

	switch (sc) {
	case REM_INV_REQ:
		/* Server has no REMOTE_WRITE, but client still has normal access */
		p->remote_write = 0;
		break;
	case RNR_RETRY_EXC:
		p->use_send = 1;
		p->rnr_retry = 0;
		p->remote_write = 0;
		break;
	case RETRY_EXC_QP_ERR:
		p->retry_cnt = 7;
		p->timeout = 8;
		break;
	default:
		break;
	}
}

/* ================================================================== */
/*  CONDITION A: Multi-WR in-flight                                   */
/* ================================================================== */

/*
 * Post N normal unsignaled WRITEs, then 1 faulty signaled WR.
 * After the faulty WR completes (error CQE), drain the CQ to see
 * how many WR_FLUSH_ERR CQEs appear for the earlier WRs.
 *
 * The key question: does vendor_err on the faulty WR's CQE match
 * the single-WR baseline?
 */

static int setup_cond_a(struct rdma_res *res, enum scenario sc)
{
	struct qp_params p;
	get_qp_params(sc, &p);

	/*
	 * Use a CQ deep enough for MULTI_WR_COUNT + 1 (faulty) + flush.
	 * Override the default CQ creation in setup_rdma by destroying
	 * and recreating with larger depth.
	 */
	if (setup_rdma(res, p.use_send, p.access_flags,
		       p.retry_cnt, p.rnr_retry, p.timeout) < 0)
		return -1;

	/* Replace default CQ with a larger one */
	struct ibv_cq *old_cq = res->cq;
	struct ibv_cq *new_cq = ibv_create_cq(res->ctx, MULTI_CQ_DEPTH,
					       NULL, NULL, 0);
	if (!new_cq) {
		fprintf(stderr, "ibv_create_cq(MULTI_CQ_DEPTH) failed\n");
		return -1;
	}

	/* Must destroy old QP first, then old CQ, then recreate QP */
	ibv_destroy_qp(res->qp);
	ibv_destroy_cq(old_cq);
	res->cq = new_cq;

	struct ibv_qp_init_attr qp_attr = {
		.send_cq = res->cq,
		.recv_cq = res->cq,
		.cap = {
			.max_send_wr = MULTI_MAX_WR,
			.max_recv_wr = MAX_WR,
			.max_send_sge = MAX_SGE,
			.max_recv_sge = MAX_SGE,
		},
		.qp_type = IBV_QPT_RC,
	};
	res->qp = ibv_create_qp(res->pd, &qp_attr);
	if (!res->qp) {
		fprintf(stderr, "ibv_create_qp failed (cond A)\n");
		return -1;
	}

	/* Update local_info with new QPN */
	res->local_info.qpn = res->qp->qp_num;
	res->local_info.psn = rand() & 0xFFFFFF;

	/* TCP setup with server */
	const char *setup_cmd;
	if (sc == REM_INV_REQ)
		setup_cmd = CMD_SETUP_NOREMOTE;
	else if (sc == RNR_RETRY_EXC)
		setup_cmd = CMD_SETUP_SEND;
	else
		setup_cmd = CMD_SETUP;

	tcp_send_msg(ctrl_sock, setup_cmd);
	tcp_exchange_qp_info(ctrl_sock, &res->local_info,
			     &res->remote_info, 0);

	if (connect_qp(res, p.remote_write,
			p.retry_cnt, p.rnr_retry, p.timeout) < 0) {
		fprintf(stderr, "connect_qp failed (cond A)\n");
		return -1;
	}

	char resp[256];
	if (tcp_recv_msg(ctrl_sock, resp, sizeof(resp)) <= 0 ||
	    strcmp(resp, CMD_READY) != 0) {
		fprintf(stderr, "Expected READY, got '%s'\n", resp);
		return -1;
	}
	return 0;
}

/*
 * Post N normal unsignaled WRs.  Returns 0 on success.
 * For WRITE scenarios: post RDMA WRITEs.
 * For RNR_RETRY_EXC (SEND): post SENDs.
 */
static int post_normal_wrs(struct rdma_res *res, enum scenario sc, int count)
{
	for (int i = 0; i < count; i++) {
		struct ibv_sge sge = {
			.addr   = (uint64_t)res->buf,
			.length = 64,
			.lkey   = res->mr->lkey,
		};

		struct ibv_send_wr wr = {
			.wr_id    = 100 + i,
			.sg_list  = &sge,
			.num_sge  = 1,
			.send_flags = 0,  /* unsignaled */
		};

		if (sc == RNR_RETRY_EXC) {
			wr.opcode = IBV_WR_SEND;
		} else {
			wr.opcode = IBV_WR_RDMA_WRITE;
			wr.wr.rdma.remote_addr = res->remote_info.raddr;
			wr.wr.rdma.rkey = res->remote_info.rkey;
		}

		struct ibv_send_wr *bad;
		int ret = ibv_post_send(res->qp, &wr, &bad);
		if (ret) {
			fprintf(stderr, "post_normal_wrs[%d]: %s\n",
				i, strerror(ret));
			return -1;
		}
	}
	return 0;
}

/*
 * Post the faulty WR (signaled).  Same logic as client.c inject_and_post
 * but returns the WR ID used (200).
 */
static int post_faulty_wr(struct rdma_res *res, enum scenario sc)
{
	struct ibv_sge sge;
	struct ibv_send_wr wr;
	struct ibv_send_wr *bad;
	char inject_cmd[64];

	memset(&wr, 0, sizeof(wr));
	wr.wr_id = 200;
	wr.num_sge = 1;
	wr.sg_list = &sge;
	wr.send_flags = IBV_SEND_SIGNALED;

	switch (sc) {
	case LOC_PROT_LEN:
		sge.addr = (uint64_t)res->buf;
		sge.length = MR_SIZE + 4096;
		sge.lkey = res->mr->lkey;
		wr.opcode = IBV_WR_RDMA_WRITE;
		wr.wr.rdma.remote_addr = res->remote_info.raddr;
		wr.wr.rdma.rkey = res->remote_info.rkey;
		return ibv_post_send(res->qp, &wr, &bad);

	case LOC_PROT_LKEY:
		sge.addr = (uint64_t)res->buf;
		sge.length = 64;
		sge.lkey = res->mr->lkey + 0x100;
		wr.opcode = IBV_WR_RDMA_WRITE;
		wr.wr.rdma.remote_addr = res->remote_info.raddr;
		wr.wr.rdma.rkey = res->remote_info.rkey;
		return ibv_post_send(res->qp, &wr, &bad);

	case REM_INV_REQ:
		sge.addr = (uint64_t)res->buf;
		sge.length = 64;
		sge.lkey = res->mr->lkey;
		wr.opcode = IBV_WR_RDMA_WRITE;
		wr.wr.rdma.remote_addr = res->remote_info.raddr;
		wr.wr.rdma.rkey = res->remote_info.rkey;
		return ibv_post_send(res->qp, &wr, &bad);

	case REM_ACCESS_RKEY:
		sge.addr = (uint64_t)res->buf;
		sge.length = 64;
		sge.lkey = res->mr->lkey;
		wr.opcode = IBV_WR_RDMA_WRITE;
		wr.wr.rdma.remote_addr = res->remote_info.raddr;
		wr.wr.rdma.rkey = res->remote_info.rkey + 0x100;
		return ibv_post_send(res->qp, &wr, &bad);

	case RNR_RETRY_EXC:
		sge.addr = (uint64_t)res->buf;
		sge.length = 64;
		sge.lkey = res->mr->lkey;
		wr.opcode = IBV_WR_SEND;
		return ibv_post_send(res->qp, &wr, &bad);

	case RETRY_EXC_QP_ERR:
		snprintf(inject_cmd, sizeof(inject_cmd), "%s %d",
			 CMD_INJECT, RETRY_EXC_QP_ERR);
		send_cmd_wait(ctrl_sock, inject_cmd, CMD_DONE);
		sge.addr = (uint64_t)res->buf;
		sge.length = 64;
		sge.lkey = res->mr->lkey;
		wr.opcode = IBV_WR_RDMA_WRITE;
		wr.wr.rdma.remote_addr = res->remote_info.raddr;
		wr.wr.rdma.rkey = res->remote_info.rkey;
		return ibv_post_send(res->qp, &wr, &bad);

	case REM_ACCESS_ADDR:
		sge.addr = (uint64_t)res->buf;
		sge.length = 64;
		sge.lkey = res->mr->lkey;
		wr.opcode = IBV_WR_RDMA_WRITE;
		wr.wr.rdma.remote_addr = res->remote_info.raddr + MR_SIZE + 4096;
		wr.wr.rdma.rkey = res->remote_info.rkey;
		return ibv_post_send(res->qp, &wr, &bad);

	default:
		fprintf(stderr, "Unsupported scenario %d for faulty WR\n", sc);
		return -1;
	}
}

static int run_cond_a(enum scenario sc, int trial, FILE *csv)
{
	struct rdma_res res;
	memset(&res, 0, sizeof(res));

	fprintf(stderr, "\n--- Cond A [%s] trial %d ---\n",
		scenario_names[sc], trial);

	if (setup_cond_a(&res, sc) < 0)
		return -1;

	/* Verify connection first (except REM_INV_REQ, RNR_RETRY_EXC which cannot do normal WRITE) */
	if (sc != REM_INV_REQ && sc != RNR_RETRY_EXC) {
		if (post_rdma_write(&res, NULL) < 0) {
			fprintf(stderr, "verify write failed\n");
			cleanup_rdma(&res);
			return -1;
		}
		struct ibv_wc vwc;
		if (poll_cq_block(res.cq, &vwc, 5000) <= 0 ||
		    vwc.status != IBV_WC_SUCCESS) {
			fprintf(stderr, "verify: CQ poll failed or error\n");
			cleanup_rdma(&res);
			return -1;
		}
		fprintf(stderr, "  Connection verified.\n");
	}

	/* Snapshots before fault */
	struct counter_snapshot cli_before, cli_after;
	struct counter_snapshot srv_before, srv_after;
	snapshot_local_counters(&cli_before);
	int daemon_ok = (request_daemon_snapshot(MGMT_SERVER_IP, DAEMON_PORT,
						 &srv_before) == 0);

	/*
	 * For RETRY_EXC_QP_ERR, we need to inject BEFORE posting normal WRs, because
	 * once server QP goes to ERR the normal WRs will also fail.
	 * Actually, for RETRY_EXC_QP_ERR we want normal WRs to complete first, then
	 * inject and post the faulty WR.
	 *
	 * For REM_INV_REQ/RNR_RETRY_EXC: normal WRs will also fail because server has no
	 * remote-write / no recv buffer.  Post them anyway to see how
	 * the HCA handles the batch.
	 */

	struct timespec t_inject, t_detect;

	if (sc == RETRY_EXC_QP_ERR) {
		/*
		 * RETRY_EXC_QP_ERR special case: post normal WRs first (they should succeed),
		 * wait for them, THEN inject server QP to ERR, then post faulty WR.
		 * Since normal WRs are unsignaled, we post a signaled fence WR to
		 * confirm completion.
		 */
		if (post_normal_wrs(&res, sc, MULTI_WR_COUNT) < 0) {
			cleanup_rdma(&res);
			return -1;
		}

		/* Post a signaled "fence" WRITE to confirm normal WRs completed */
		struct ibv_sge fence_sge = {
			.addr = (uint64_t)res.buf,
			.length = 64,
			.lkey = res.mr->lkey,
		};
		struct ibv_send_wr fence_wr = {
			.wr_id = 999,
			.sg_list = &fence_sge,
			.num_sge = 1,
			.opcode = IBV_WR_RDMA_WRITE,
			.send_flags = IBV_SEND_SIGNALED | IBV_SEND_FENCE,
			.wr.rdma = {
				.remote_addr = res.remote_info.raddr,
				.rkey = res.remote_info.rkey,
			},
		};
		struct ibv_send_wr *bad;
		if (ibv_post_send(res.qp, &fence_wr, &bad) != 0) {
			fprintf(stderr, "fence post failed\n");
			cleanup_rdma(&res);
			return -1;
		}

		struct ibv_wc fwc;
		if (poll_cq_block(res.cq, &fwc, 10000) <= 0 ||
		    fwc.status != IBV_WC_SUCCESS) {
			fprintf(stderr, "fence WR failed: status=%d\n",
				fwc.status);
			cleanup_rdma(&res);
			return -1;
		}
		fprintf(stderr, "  Normal WRs completed (fence ok).\n");

		/* Now inject fault and post faulty WR */
		clock_gettime(CLOCK_MONOTONIC, &t_inject);
		if (post_faulty_wr(&res, sc) < 0) {
			fprintf(stderr, "post_faulty_wr failed\n");
			cleanup_rdma(&res);
			return -1;
		}
	} else {
		/*
		 * Non-RETRY_EXC_QP_ERR scenarios: post normal WRs followed immediately
		 * by the faulty WR.
		 *
		 * For local faults (LOC_PROT_LEN, LOC_PROT_LKEY): normal unsignaled WRs use valid
		 * params and should be processed first; the faulty signaled
		 * WR fails at the HCA.
		 *
		 * For remote faults (REM_ACCESS_RKEY, REM_ACCESS_ADDR): normal WRs use valid params and
		 * succeed; only the faulty WR triggers a NAK from the server.
		 *
		 * For REM_INV_REQ/RNR_RETRY_EXC: ALL operations fail because the server config
		 * rejects them (no REMOTE_WRITE / no recv buffer).  We post
		 * normal WRs first, then the signaled faulty WR, to observe
		 * how many flush CQEs appear.
		 */
		if (post_normal_wrs(&res, sc, MULTI_WR_COUNT) < 0) {
			fprintf(stderr, "post_normal_wrs failed "
				"(may be expected for some scenarios)\n");
		}

		clock_gettime(CLOCK_MONOTONIC, &t_inject);
		if (post_faulty_wr(&res, sc) < 0) {
			fprintf(stderr, "post_faulty_wr returned error "
				"(may be expected)\n");
		}
	}

	/* Wait for CQE(s) */
	int timeout_ms = 30000;
	if (sc == RETRY_EXC_QP_ERR)
		timeout_ms = 60000;

	/*
	 * We want to drain ALL CQEs: the error CQE plus any flush CQEs.
	 * First, wait for at least one CQE (the error), then drain the rest.
	 */
	struct ibv_wc wc_all[MULTI_MAX_CQE];
	int first_n = poll_cq_block(res.cq, &wc_all[0], timeout_ms);
	clock_gettime(CLOCK_MONOTONIC, &t_detect);

	if (first_n <= 0) {
		fprintf(stderr, "  Poll timeout -- no CQE.\n");
		cleanup_rdma(&res);
		return -1;
	}

	/* Give HCA time to generate flush CQEs, then drain */
	usleep(100000);  /* 100ms */
	int rest = drain_cq(res.cq, wc_all + first_n,
			    MULTI_MAX_CQE - first_n, 500);
	int total_cqe = first_n + rest;

	/* Classify CQEs */
	int n_success, n_flush, n_error;
	uint32_t first_vendor_err;
	int first_error_status;
	classify_wc_array(wc_all, total_cqe, &n_success, &n_flush,
			  &n_error, &first_vendor_err, &first_error_status);

	double latency = elapsed_us(&t_inject, &t_detect);
	fprintf(stderr, "  CQEs: total=%d, success=%d, flush=%d, error=%d\n",
		total_cqe, n_success, n_flush, n_error);
	fprintf(stderr, "  First error: status=%d (%s), vendor_err=0x%x, "
		"latency=%.0f us\n",
		first_error_status,
		first_error_status >= 0 ?
			ibv_wc_status_str(first_error_status) : "N/A",
		first_vendor_err, latency);

	/* Log each CQE for detailed analysis */
	for (int i = 0; i < total_cqe; i++) {
		fprintf(stderr, "    CQE[%d]: wr_id=%lu status=%d (%s) "
			"vendor_err=0x%x\n",
			i, (unsigned long)wc_all[i].wr_id,
			wc_all[i].status,
			ibv_wc_status_str(wc_all[i].status),
			wc_all[i].vendor_err);
	}

	/* Counter snapshots after */
	sleep(1);
	snapshot_local_counters(&cli_after);
	if (daemon_ok)
		request_daemon_snapshot(MGMT_SERVER_IP, DAEMON_PORT, &srv_after);

	/* CSV output */
	fprintf(csv, "# MULTI_WR,%s,trial=%d,status=%d,vendor_err=0x%x,"
		"latency_us=%.0f,total_cqe=%d,success=%d,flush=%d,error=%d\n",
		scenario_names[sc], trial, first_error_status,
		first_vendor_err, latency, total_cqe, n_success,
		n_flush, n_error);

	/* Per-CQE detail rows */
	for (int i = 0; i < total_cqe; i++) {
		fprintf(csv, "MULTI_WR,%s,%d,0,cqe,%d,wr_id=%lu,status=%d,"
			"vendor_err=0x%x\n",
			scenario_names[sc], trial, i,
			(unsigned long)wc_all[i].wr_id,
			wc_all[i].status, wc_all[i].vendor_err);
	}

	/* Counter deltas */
	print_counter_delta("client", &cli_before, &cli_after, csv);
	if (daemon_ok)
		print_counter_delta("server", &srv_before, &srv_after, csv);

	/* Cleanup */
	send_cmd_wait(ctrl_sock, CMD_CLEANUP, CMD_DONE);
	cleanup_rdma(&res);
	return 0;
}

/* ================================================================== */
/*  CONDITION B: Large message (multi-packet WRITE)                   */
/* ================================================================== */

/*
 * With MTU=1024, a 256KB WRITE = 256 packets on the wire.
 * The HCA segments the single WQE into multiple packets.
 *
 * We allocate a large buffer, register it, and post a single large
 * RDMA WRITE with the fault injected in the WR parameters.
 *
 * For server-side faults (RETRY_EXC_QP_ERR), we inject mid-operation by having
 * the server QP crash before we post.
 */

static int setup_cond_b(struct large_rdma_res *lr, enum scenario sc)
{
	struct qp_params p;
	get_qp_params(sc, &p);

	/* Open device */
	lr->ctx = open_ib_device(IB_DEV_NAME);
	if (!lr->ctx) {
		fprintf(stderr, "Failed to open device\n");
		return -1;
	}

	lr->pd = ibv_alloc_pd(lr->ctx);
	if (!lr->pd) {
		fprintf(stderr, "ibv_alloc_pd failed\n");
		return -1;
	}

	lr->cq = ibv_create_cq(lr->ctx, MULTI_CQ_DEPTH, NULL, NULL, 0);
	if (!lr->cq) {
		fprintf(stderr, "ibv_create_cq failed\n");
		return -1;
	}

	struct ibv_qp_init_attr qp_attr = {
		.send_cq = lr->cq,
		.recv_cq = lr->cq,
		.cap = {
			.max_send_wr  = MAX_WR,
			.max_recv_wr  = MAX_WR,
			.max_send_sge = MAX_SGE,
			.max_recv_sge = MAX_SGE,
		},
		.qp_type = IBV_QPT_RC,
	};

	lr->qp = ibv_create_qp(lr->pd, &qp_attr);
	if (!lr->qp) {
		fprintf(stderr, "ibv_create_qp failed\n");
		return -1;
	}

	/* Allocate large buffer */
	lr->buf_size = LARGE_BUF_SIZE;
	lr->buf = calloc(1, lr->buf_size);
	if (!lr->buf) {
		fprintf(stderr, "calloc(%zu) failed\n", lr->buf_size);
		return -1;
	}

	/* Fill buffer with pattern for verifiability */
	memset(lr->buf, 0xAB, lr->buf_size);

	/*
	 * MR size depends on scenario:
	 * - LOC_PROT_LEN: register only 4KB MR, then try to WRITE 256KB (SGE > MR)
	 * - Others: register full 256KB
	 */
	size_t mr_size = (sc == LOC_PROT_LEN) ? MR_SIZE : lr->buf_size;
	lr->mr = ibv_reg_mr(lr->pd, lr->buf, mr_size, p.access_flags);
	if (!lr->mr) {
		fprintf(stderr, "ibv_reg_mr(%zu) failed: %s\n",
			mr_size, strerror(errno));
		return -1;
	}

	/* Find GID */
	union ibv_gid gid;
	int gid_index = -1;
	for (int i = 0; i < 16; i++) {
		union ibv_gid g;
		if (ibv_query_gid(lr->ctx, IB_PORT, i, &g))
			break;
		if (g.raw[0] == 0 && g.raw[10] == 0xff && g.raw[11] == 0xff &&
		    (g.raw[12] != 0 || g.raw[13] != 0)) {
			gid_index = i;
			gid = g;
			break;
		}
	}
	if (gid_index < 0) {
		fprintf(stderr, "No valid RoCEv2 GID found\n");
		return -1;
	}
	lr->gid_index = gid_index;

	lr->local_info.qpn  = lr->qp->qp_num;
	lr->local_info.psn  = rand() & 0xFFFFFF;
	lr->local_info.rkey = lr->mr->rkey;
	lr->local_info.raddr = (uint64_t)lr->buf;
	lr->local_info.gid  = gid;

	/* TCP: ask server to setup large buffer */
	char cmd[64];
	if (sc == REM_INV_REQ)
		snprintf(cmd, sizeof(cmd), "%s %zu",
			 CMD_SETUP_LARGE_NOREMOTE, lr->buf_size);
	else
		snprintf(cmd, sizeof(cmd), "%s %zu",
			 CMD_SETUP_LARGE, lr->buf_size);

	tcp_send_msg(ctrl_sock, cmd);
	tcp_exchange_qp_info(ctrl_sock, &lr->local_info,
			     &lr->remote_info, 0);

	/* Connect QP */
	if (modify_qp_to_init(lr->qp, p.remote_write)) {
		fprintf(stderr, "modify_qp_to_init failed\n");
		return -1;
	}
	if (modify_qp_to_rtr(lr->qp, &lr->remote_info, lr->gid_index)) {
		fprintf(stderr, "modify_qp_to_rtr failed\n");
		return -1;
	}
	if (modify_qp_to_rts(lr->qp, lr->local_info.psn,
			      p.retry_cnt, p.rnr_retry, p.timeout)) {
		fprintf(stderr, "modify_qp_to_rts failed\n");
		return -1;
	}

	char resp[256];
	if (tcp_recv_msg(ctrl_sock, resp, sizeof(resp)) <= 0 ||
	    strcmp(resp, CMD_READY) != 0) {
		fprintf(stderr, "Expected READY, got '%s'\n", resp);
		return -1;
	}

	return 0;
}

static void cleanup_large(struct large_rdma_res *lr)
{
	if (lr->qp) ibv_destroy_qp(lr->qp);
	if (lr->mr) ibv_dereg_mr(lr->mr);
	if (lr->cq) ibv_destroy_cq(lr->cq);
	if (lr->pd) ibv_dealloc_pd(lr->pd);
	if (lr->ctx) ibv_close_device(lr->ctx);
	free(lr->buf);
	memset(lr, 0, sizeof(*lr));
}

static int post_large_faulty_wr(struct large_rdma_res *lr, enum scenario sc)
{
	struct ibv_sge sge;
	struct ibv_send_wr wr;
	struct ibv_send_wr *bad;
	char inject_cmd[64];

	memset(&wr, 0, sizeof(wr));
	wr.wr_id = 300;
	wr.num_sge = 1;
	wr.sg_list = &sge;
	wr.send_flags = IBV_SEND_SIGNALED;
	wr.opcode = IBV_WR_RDMA_WRITE;

	switch (sc) {
	case LOC_PROT_LEN:
		/* MR is only 4KB but SGE covers 256KB */
		sge.addr = (uint64_t)lr->buf;
		sge.length = LARGE_BUF_SIZE;
		sge.lkey = lr->mr->lkey;
		wr.wr.rdma.remote_addr = lr->remote_info.raddr;
		wr.wr.rdma.rkey = lr->remote_info.rkey;
		return ibv_post_send(lr->qp, &wr, &bad);

	case LOC_PROT_LKEY:
		sge.addr = (uint64_t)lr->buf;
		sge.length = LARGE_BUF_SIZE;
		sge.lkey = lr->mr->lkey + 0x100;
		wr.wr.rdma.remote_addr = lr->remote_info.raddr;
		wr.wr.rdma.rkey = lr->remote_info.rkey;
		return ibv_post_send(lr->qp, &wr, &bad);

	case REM_INV_REQ:
		sge.addr = (uint64_t)lr->buf;
		sge.length = LARGE_BUF_SIZE;
		sge.lkey = lr->mr->lkey;
		wr.wr.rdma.remote_addr = lr->remote_info.raddr;
		wr.wr.rdma.rkey = lr->remote_info.rkey;
		return ibv_post_send(lr->qp, &wr, &bad);

	case REM_ACCESS_RKEY:
		sge.addr = (uint64_t)lr->buf;
		sge.length = LARGE_BUF_SIZE;
		sge.lkey = lr->mr->lkey;
		wr.wr.rdma.remote_addr = lr->remote_info.raddr;
		wr.wr.rdma.rkey = lr->remote_info.rkey + 0x100;
		return ibv_post_send(lr->qp, &wr, &bad);

	case RETRY_EXC_QP_ERR:
		snprintf(inject_cmd, sizeof(inject_cmd), "%s %d",
			 CMD_INJECT, RETRY_EXC_QP_ERR);
		send_cmd_wait(ctrl_sock, inject_cmd, CMD_DONE);
		sge.addr = (uint64_t)lr->buf;
		sge.length = LARGE_BUF_SIZE;
		sge.lkey = lr->mr->lkey;
		wr.wr.rdma.remote_addr = lr->remote_info.raddr;
		wr.wr.rdma.rkey = lr->remote_info.rkey;
		return ibv_post_send(lr->qp, &wr, &bad);

	case REM_ACCESS_ADDR:
		sge.addr = (uint64_t)lr->buf;
		sge.length = LARGE_BUF_SIZE;
		sge.lkey = lr->mr->lkey;
		/* Offset past remote MR end so the write overflows */
		wr.wr.rdma.remote_addr = lr->remote_info.raddr +
					 LARGE_BUF_SIZE + 4096;
		wr.wr.rdma.rkey = lr->remote_info.rkey;
		return ibv_post_send(lr->qp, &wr, &bad);

	case RNR_RETRY_EXC:
		/* RNR_RETRY_EXC uses SEND, not WRITE -- skip for large msg */
		fprintf(stderr, "RNR_RETRY_EXC not applicable for large WRITE test\n");
		return -1;

	default:
		fprintf(stderr, "Unsupported scenario %d for large msg\n", sc);
		return -1;
	}
}

static int run_cond_b(enum scenario sc, int trial, FILE *csv)
{
	struct large_rdma_res lr;
	memset(&lr, 0, sizeof(lr));

	fprintf(stderr, "\n--- Cond B [%s] trial %d ---\n",
		scenario_names[sc], trial);

	if (sc == RNR_RETRY_EXC) {
		fprintf(stderr, "  SKIP: RNR_RETRY_EXC not applicable to large WRITE.\n");
		fprintf(csv, "# LARGE_MSG,%s,trial=%d,SKIPPED\n",
			scenario_names[sc], trial);
		return 0;
	}

	if (setup_cond_b(&lr, sc) < 0) {
		cleanup_large(&lr);
		return -1;
	}

	/* Verify with a small WRITE first (except REM_INV_REQ) */
	if (sc != REM_INV_REQ) {
		struct ibv_sge vsge = {
			.addr = (uint64_t)lr.buf,
			.length = 64,
			.lkey = lr.mr->lkey,
		};
		struct ibv_send_wr vwr = {
			.wr_id = 999,
			.sg_list = &vsge,
			.num_sge = 1,
			.opcode = IBV_WR_RDMA_WRITE,
			.send_flags = IBV_SEND_SIGNALED,
			.wr.rdma = {
				.remote_addr = lr.remote_info.raddr,
				.rkey = lr.remote_info.rkey,
			},
		};

		/* LOC_PROT_LEN has small MR -- use a length within MR for verify */
		if (sc == LOC_PROT_LEN)
			vsge.length = 64;  /* within 4KB MR */

		struct ibv_send_wr *bad;
		if (ibv_post_send(lr.qp, &vwr, &bad) != 0) {
			fprintf(stderr, "verify post failed\n");
			cleanup_large(&lr);
			return -1;
		}
		struct ibv_wc vwc;
		if (poll_cq_block(lr.cq, &vwc, 5000) <= 0 ||
		    vwc.status != IBV_WC_SUCCESS) {
			fprintf(stderr, "verify failed: status=%d\n",
				vwc.status);
			cleanup_large(&lr);
			return -1;
		}
		fprintf(stderr, "  Connection verified.\n");
	}

	/* Snapshots */
	struct counter_snapshot cli_before, cli_after;
	struct counter_snapshot srv_before, srv_after;
	snapshot_local_counters(&cli_before);
	int daemon_ok = (request_daemon_snapshot(MGMT_SERVER_IP, DAEMON_PORT,
						 &srv_before) == 0);

	/* Post faulty large WR */
	struct timespec t_inject, t_detect;
	clock_gettime(CLOCK_MONOTONIC, &t_inject);

	int post_ret = post_large_faulty_wr(&lr, sc);
	if (post_ret != 0) {
		fprintf(stderr, "post_large_faulty_wr failed: %s\n",
			strerror(post_ret));
		/* Some scenarios may fail at post time, that's data too */
	}

	/* Wait for CQE */
	int timeout_ms = (sc == RETRY_EXC_QP_ERR) ? 60000 : 30000;
	struct ibv_wc wc;
	int n = poll_cq_block(lr.cq, &wc, timeout_ms);
	clock_gettime(CLOCK_MONOTONIC, &t_detect);

	if (n <= 0) {
		fprintf(stderr, "  Poll timeout.\n");
		cleanup_large(&lr);
		return -1;
	}

	double latency = elapsed_us(&t_inject, &t_detect);
	fprintf(stderr, "  CQE: status=%d (%s), vendor_err=0x%x, "
		"latency=%.0f us\n",
		wc.status, ibv_wc_status_str(wc.status),
		wc.vendor_err, latency);

	/* Counter snapshots after */
	sleep(1);
	snapshot_local_counters(&cli_after);
	if (daemon_ok)
		request_daemon_snapshot(MGMT_SERVER_IP, DAEMON_PORT, &srv_after);

	/* CSV output */
	fprintf(csv, "# LARGE_MSG,%s,trial=%d,status=%d,vendor_err=0x%x,"
		"latency_us=%.0f,buf_size=%zu\n",
		scenario_names[sc], trial, wc.status,
		wc.vendor_err, latency, lr.buf_size);

	print_counter_delta("client", &cli_before, &cli_after, csv);
	if (daemon_ok)
		print_counter_delta("server", &srv_before, &srv_after, csv);

	/* Cleanup */
	send_cmd_wait(ctrl_sock, CMD_CLEANUP, CMD_DONE);
	cleanup_large(&lr);
	return 0;
}

/* ================================================================== */
/*  CONDITION C: Multi-QP                                             */
/* ================================================================== */

/*
 * Create 4 QPs to the same server.  Run normal traffic on all 4,
 * then inject fault on QP #0.  Observe:
 *   - Does QP #0 get the expected error CQE and fingerprint?
 *   - Do QPs #1-#3 get any errors? Any counter deltas?
 *
 * This tests fault isolation: per-QP errors should NOT propagate
 * to sibling QPs on the same port.
 */

static int setup_cond_c(struct multi_qp_res *mq, enum scenario sc)
{
	struct qp_params p;
	get_qp_params(sc, &p);

	mq->ctx = open_ib_device(IB_DEV_NAME);
	if (!mq->ctx) {
		fprintf(stderr, "Failed to open device\n");
		return -1;
	}

	mq->pd = ibv_alloc_pd(mq->ctx);
	if (!mq->pd) {
		fprintf(stderr, "ibv_alloc_pd failed\n");
		return -1;
	}

	/* Allocate shared buffer and MR */
	mq->buf_size = BUF_SIZE;
	mq->buf = calloc(1, mq->buf_size);
	if (!mq->buf)
		return -1;

	mq->mr = ibv_reg_mr(mq->pd, mq->buf, MR_SIZE, p.access_flags);
	if (!mq->mr) {
		fprintf(stderr, "ibv_reg_mr failed: %s\n", strerror(errno));
		return -1;
	}

	/* Find GID */
	union ibv_gid gid;
	int gid_index = -1;
	for (int i = 0; i < 16; i++) {
		union ibv_gid g;
		if (ibv_query_gid(mq->ctx, IB_PORT, i, &g))
			break;
		if (g.raw[0] == 0 && g.raw[10] == 0xff && g.raw[11] == 0xff &&
		    (g.raw[12] != 0 || g.raw[13] != 0)) {
			gid_index = i;
			gid = g;
			break;
		}
	}
	if (gid_index < 0) {
		fprintf(stderr, "No valid RoCEv2 GID found\n");
		return -1;
	}
	mq->gid_index = gid_index;

	/* Create QPs */
	int count = MULTI_QP_COUNT;
	mq->qp_count = count;

	for (int i = 0; i < count; i++) {
		mq->cq[i] = ibv_create_cq(mq->ctx, MULTI_CQ_DEPTH,
					   NULL, NULL, 0);
		if (!mq->cq[i]) {
			fprintf(stderr, "ibv_create_cq[%d] failed\n", i);
			return -1;
		}

		struct ibv_qp_init_attr qp_attr = {
			.send_cq = mq->cq[i],
			.recv_cq = mq->cq[i],
			.cap = {
				.max_send_wr  = MAX_WR,
				.max_recv_wr  = MAX_WR,
				.max_send_sge = MAX_SGE,
				.max_recv_sge = MAX_SGE,
			},
			.qp_type = IBV_QPT_RC,
		};

		mq->qp[i] = ibv_create_qp(mq->pd, &qp_attr);
		if (!mq->qp[i]) {
			fprintf(stderr, "ibv_create_qp[%d] failed\n", i);
			return -1;
		}

		mq->local_info[i].qpn  = mq->qp[i]->qp_num;
		mq->local_info[i].psn  = rand() & 0xFFFFFF;
		mq->local_info[i].rkey = mq->mr->rkey;
		mq->local_info[i].raddr = (uint64_t)mq->buf;
		mq->local_info[i].gid  = gid;
	}

	/* Ask server to create matching QPs */
	char cmd[64];
	if (sc == RNR_RETRY_EXC)
		snprintf(cmd, sizeof(cmd), "%s %d",
			 CMD_SETUP_MULTI_QP_SEND, count);
	else if (sc == REM_INV_REQ)
		/*
		 * For REM_INV_REQ in multi-QP we need server QPs with no remote
		 * write but only on QP #0.  Simplify: use normal setup
		 * for all QPs (SETUP_MULTI_QP), but the faulty WR on
		 * QP #0 uses an invalid rkey/addr to trigger the error.
		 * Actually, REM_INV_REQ requires the server QP to lack REMOTE_WRITE.
		 * We cannot do per-QP access flags easily.
		 *
		 * Solution: For REM_INV_REQ multi-QP, set up ALL server QPs without
		 * remote write.  Then the normal WRs on QPs #1-#3 will
		 * also fail if they try RDMA WRITE.  So for the "normal
		 * traffic" on QPs #1-#3, we just verify they exist and
		 * are connected, but don't send any WRITEs.
		 *
		 * Hmm, that defeats the purpose.  Better approach:
		 * Use SETUP_MULTI_QP (with remote write) for all QPs,
		 * and for the fault on QP #0, re-use REM_ACCESS_RKEY (invalid rkey).
		 * This gives us the same "remote access error" class.
		 *
		 * Actually let's just skip REM_INV_REQ for multi-QP and note it.
		 */
		snprintf(cmd, sizeof(cmd), "%s %d",
			 CMD_SETUP_MULTI_QP, count);
	else
		snprintf(cmd, sizeof(cmd), "%s %d",
			 CMD_SETUP_MULTI_QP, count);

	tcp_send_msg(ctrl_sock, cmd);

	/* Exchange QP info for each QP, in order */
	for (int i = 0; i < count; i++) {
		tcp_exchange_qp_info(ctrl_sock, &mq->local_info[i],
				     &mq->remote_info[i], 0);
		fprintf(stderr, "  QP[%d]: local qpn=%u, remote qpn=%u\n",
			i, mq->local_info[i].qpn,
			mq->remote_info[i].qpn);
	}

	/* Connect all QPs */
	for (int i = 0; i < count; i++) {
		if (modify_qp_to_init(mq->qp[i], p.remote_write)) {
			fprintf(stderr, "init QP[%d] failed\n", i);
			return -1;
		}
		if (modify_qp_to_rtr(mq->qp[i], &mq->remote_info[i],
				     mq->gid_index)) {
			fprintf(stderr, "rtr QP[%d] failed\n", i);
			return -1;
		}
		if (modify_qp_to_rts(mq->qp[i], mq->local_info[i].psn,
				     p.retry_cnt, p.rnr_retry, p.timeout)) {
			fprintf(stderr, "rts QP[%d] failed\n", i);
			return -1;
		}
	}

	char resp[256];
	if (tcp_recv_msg(ctrl_sock, resp, sizeof(resp)) <= 0 ||
	    strcmp(resp, CMD_READY) != 0) {
		fprintf(stderr, "Expected READY, got '%s'\n", resp);
		return -1;
	}

	return 0;
}

static void cleanup_multi_qp(struct multi_qp_res *mq)
{
	for (int i = 0; i < mq->qp_count; i++) {
		if (mq->qp[i]) ibv_destroy_qp(mq->qp[i]);
		if (mq->cq[i]) ibv_destroy_cq(mq->cq[i]);
	}
	if (mq->mr)  ibv_dereg_mr(mq->mr);
	if (mq->pd)  ibv_dealloc_pd(mq->pd);
	if (mq->ctx) ibv_close_device(mq->ctx);
	free(mq->buf);
	memset(mq, 0, sizeof(*mq));
}

/*
 * Post a normal signaled WRITE on a specific QP.
 */
static int post_write_on_qp(struct multi_qp_res *mq, int qp_idx)
{
	struct ibv_sge sge = {
		.addr = (uint64_t)mq->buf,
		.length = 64,
		.lkey = mq->mr->lkey,
	};
	struct ibv_send_wr wr = {
		.wr_id = 400 + qp_idx,
		.sg_list = &sge,
		.num_sge = 1,
		.opcode = IBV_WR_RDMA_WRITE,
		.send_flags = IBV_SEND_SIGNALED,
		.wr.rdma = {
			.remote_addr = mq->remote_info[qp_idx].raddr,
			.rkey = mq->remote_info[qp_idx].rkey,
		},
	};
	struct ibv_send_wr *bad;
	return ibv_post_send(mq->qp[qp_idx], &wr, &bad);
}

/*
 * Post a faulty signaled WR on QP #0.
 */
static int post_faulty_on_qp0(struct multi_qp_res *mq, enum scenario sc)
{
	struct ibv_sge sge;
	struct ibv_send_wr wr;
	struct ibv_send_wr *bad;
	char inject_cmd[64];

	memset(&wr, 0, sizeof(wr));
	wr.wr_id = 500;
	wr.num_sge = 1;
	wr.sg_list = &sge;
	wr.send_flags = IBV_SEND_SIGNALED;
	wr.opcode = IBV_WR_RDMA_WRITE;

	switch (sc) {
	case LOC_PROT_LEN:
		sge.addr = (uint64_t)mq->buf;
		sge.length = MR_SIZE + 4096;
		sge.lkey = mq->mr->lkey;
		wr.wr.rdma.remote_addr = mq->remote_info[0].raddr;
		wr.wr.rdma.rkey = mq->remote_info[0].rkey;
		return ibv_post_send(mq->qp[0], &wr, &bad);

	case LOC_PROT_LKEY:
		sge.addr = (uint64_t)mq->buf;
		sge.length = 64;
		sge.lkey = mq->mr->lkey + 0x100;
		wr.wr.rdma.remote_addr = mq->remote_info[0].raddr;
		wr.wr.rdma.rkey = mq->remote_info[0].rkey;
		return ibv_post_send(mq->qp[0], &wr, &bad);

	case REM_INV_REQ:
		/*
		 * For multi-QP REM_INV_REQ we use the same approach as single-WR:
		 * Server QP #0 has no REMOTE_WRITE.  But with SETUP_MULTI_QP
		 * all server QPs have REMOTE_WRITE.  So we effectively
		 * re-test REM_INV_REQ behavior as if it were REM_INV_REQ in single-QP by
		 * posting to a server QP that has remote write -- but the
		 * WRITE is normal, so it would succeed.
		 *
		 * NOTE: REM_INV_REQ multi-QP is not fully testable with the current
		 * server protocol.  We document this and fall through to
		 * use an invalid rkey (same error class) instead.
		 */
		fprintf(stderr, "  NOTE: REM_INV_REQ multi-QP uses invalid rkey "
			"(same error class as REM_ACCESS_RKEY)\n");
		sge.addr = (uint64_t)mq->buf;
		sge.length = 64;
		sge.lkey = mq->mr->lkey;
		wr.wr.rdma.remote_addr = mq->remote_info[0].raddr;
		wr.wr.rdma.rkey = mq->remote_info[0].rkey + 0x100;
		return ibv_post_send(mq->qp[0], &wr, &bad);

	case REM_ACCESS_RKEY:
		sge.addr = (uint64_t)mq->buf;
		sge.length = 64;
		sge.lkey = mq->mr->lkey;
		wr.wr.rdma.remote_addr = mq->remote_info[0].raddr;
		wr.wr.rdma.rkey = mq->remote_info[0].rkey + 0x100;
		return ibv_post_send(mq->qp[0], &wr, &bad);

	case RNR_RETRY_EXC:
		sge.addr = (uint64_t)mq->buf;
		sge.length = 64;
		sge.lkey = mq->mr->lkey;
		wr.opcode = IBV_WR_SEND;
		return ibv_post_send(mq->qp[0], &wr, &bad);

	case RETRY_EXC_QP_ERR:
		/* Tell server to crash QP #0 only */
		snprintf(inject_cmd, sizeof(inject_cmd), "%s 0 %d",
			 CMD_INJECT_QP, RETRY_EXC_QP_ERR);
		send_cmd_wait(ctrl_sock, inject_cmd, CMD_DONE);
		sge.addr = (uint64_t)mq->buf;
		sge.length = 64;
		sge.lkey = mq->mr->lkey;
		wr.wr.rdma.remote_addr = mq->remote_info[0].raddr;
		wr.wr.rdma.rkey = mq->remote_info[0].rkey;
		return ibv_post_send(mq->qp[0], &wr, &bad);

	case REM_ACCESS_ADDR:
		sge.addr = (uint64_t)mq->buf;
		sge.length = 64;
		sge.lkey = mq->mr->lkey;
		wr.wr.rdma.remote_addr = mq->remote_info[0].raddr +
					 MR_SIZE + 4096;
		wr.wr.rdma.rkey = mq->remote_info[0].rkey;
		return ibv_post_send(mq->qp[0], &wr, &bad);

	default:
		fprintf(stderr, "Unsupported scenario %d for multi-QP\n", sc);
		return -1;
	}
}

static int run_cond_c(enum scenario sc, int trial, FILE *csv)
{
	struct multi_qp_res mq;
	memset(&mq, 0, sizeof(mq));

	fprintf(stderr, "\n--- Cond C [%s] trial %d ---\n",
		scenario_names[sc], trial);

	if (setup_cond_c(&mq, sc) < 0) {
		cleanup_multi_qp(&mq);
		return -1;
	}

	/*
	 * Verify all QPs work (except REM_INV_REQ/RNR_RETRY_EXC where the operation itself
	 * would fail).
	 */
	if (sc != REM_INV_REQ && sc != RNR_RETRY_EXC) {
		for (int i = 0; i < mq.qp_count; i++) {
			if (post_write_on_qp(&mq, i) != 0) {
				fprintf(stderr, "verify QP[%d] post failed\n", i);
				cleanup_multi_qp(&mq);
				return -1;
			}
			struct ibv_wc vwc;
			if (poll_cq_block(mq.cq[i], &vwc, 5000) <= 0 ||
			    vwc.status != IBV_WC_SUCCESS) {
				fprintf(stderr, "verify QP[%d] failed: "
					"status=%d\n", i,
					vwc.status);
				cleanup_multi_qp(&mq);
				return -1;
			}
		}
		fprintf(stderr, "  All %d QPs verified.\n", mq.qp_count);
	}

	/* Snapshots */
	struct counter_snapshot cli_before, cli_after;
	struct counter_snapshot srv_before, srv_after;
	snapshot_local_counters(&cli_before);
	int daemon_ok = (request_daemon_snapshot(MGMT_SERVER_IP, DAEMON_PORT,
						 &srv_before) == 0);

	/*
	 * Step 1: Post normal WRITEs on QPs #1-#3 (keep them busy)
	 * Step 2: Inject fault on QP #0
	 */

	/* Post on QPs #1-#3 */
	if (sc != REM_INV_REQ && sc != RNR_RETRY_EXC) {
		for (int i = 1; i < mq.qp_count; i++) {
			if (post_write_on_qp(&mq, i) != 0) {
				fprintf(stderr, "traffic QP[%d] post failed\n", i);
			}
		}
	}

	/* Inject and post faulty WR on QP #0 */
	struct timespec t_inject, t_detect;
	clock_gettime(CLOCK_MONOTONIC, &t_inject);

	if (post_faulty_on_qp0(&mq, sc) != 0) {
		fprintf(stderr, "post_faulty_on_qp0 failed (may be expected)\n");
	}

	/* Wait for error CQE on QP #0's CQ */
	int timeout_ms = (sc == RETRY_EXC_QP_ERR) ? 60000 : 30000;
	struct ibv_wc wc0;
	int n0 = poll_cq_block(mq.cq[0], &wc0, timeout_ms);
	clock_gettime(CLOCK_MONOTONIC, &t_detect);

	double latency = 0;
	uint32_t vendor_err0 = 0;
	int status0 = -1;

	if (n0 > 0) {
		latency = elapsed_us(&t_inject, &t_detect);
		vendor_err0 = wc0.vendor_err;
		status0 = wc0.status;
		fprintf(stderr, "  QP[0] CQE: status=%d (%s), "
			"vendor_err=0x%x, latency=%.0f us\n",
			status0, ibv_wc_status_str(status0),
			vendor_err0, latency);
	} else {
		fprintf(stderr, "  QP[0]: no CQE (timeout)\n");
	}

	/* Drain CQ[0] for flush entries */
	struct ibv_wc flush_wc[16];
	usleep(100000);
	int n_flush0 = drain_cq(mq.cq[0], flush_wc, 16, 500);
	fprintf(stderr, "  QP[0] additional CQEs: %d\n", n_flush0);

	/* Check QPs #1-#3: did they get errors? */
	int sibling_errors = 0;
	for (int i = 1; i < mq.qp_count; i++) {
		struct ibv_wc swc[4];
		int sn = drain_cq(mq.cq[i], swc, 4, 2000);
		int got_error = 0;
		for (int j = 0; j < sn; j++) {
			fprintf(stderr, "  QP[%d] CQE[%d]: status=%d (%s) "
				"vendor_err=0x%x\n",
				i, j, swc[j].status,
				ibv_wc_status_str(swc[j].status),
				swc[j].vendor_err);
			if (swc[j].status != IBV_WC_SUCCESS)
				got_error = 1;
		}
		if (got_error)
			sibling_errors++;

		/* Also check QP state */
		struct ibv_qp_attr qattr;
		struct ibv_qp_init_attr qinit;
		if (ibv_query_qp(mq.qp[i], &qattr, IBV_QP_STATE, &qinit) == 0) {
			fprintf(stderr, "  QP[%d] state = %d\n",
				i, qattr.qp_state);
			fprintf(csv, "MULTI_QP,%s,%d,%d,qp_state,%d\n",
				scenario_names[sc], trial, i,
				qattr.qp_state);
		}
	}

	/* Check QP #0 state too */
	{
		struct ibv_qp_attr qattr;
		struct ibv_qp_init_attr qinit;
		if (ibv_query_qp(mq.qp[0], &qattr, IBV_QP_STATE, &qinit) == 0) {
			fprintf(stderr, "  QP[0] state = %d\n", qattr.qp_state);
			fprintf(csv, "MULTI_QP,%s,%d,0,qp_state,%d\n",
				scenario_names[sc], trial,
				qattr.qp_state);
		}
	}

	fprintf(stderr, "  Sibling QPs with errors: %d / %d\n",
		sibling_errors, mq.qp_count - 1);

	/* Post-fault: verify sibling QPs still work */
	int siblings_still_working = 0;
	if (sc != REM_INV_REQ && sc != RNR_RETRY_EXC) {
		for (int i = 1; i < mq.qp_count; i++) {
			/* First drain any pending CQEs */
			struct ibv_wc dwc[4];
			drain_cq(mq.cq[i], dwc, 4, 100);

			if (post_write_on_qp(&mq, i) != 0)
				continue;
			struct ibv_wc pwc;
			if (poll_cq_block(mq.cq[i], &pwc, 5000) > 0 &&
			    pwc.status == IBV_WC_SUCCESS)
				siblings_still_working++;
		}
		fprintf(stderr, "  Sibling QPs still working after fault: "
			"%d / %d\n", siblings_still_working,
			mq.qp_count - 1);
	}

	/* Counter snapshots */
	sleep(1);
	snapshot_local_counters(&cli_after);
	if (daemon_ok)
		request_daemon_snapshot(MGMT_SERVER_IP, DAEMON_PORT, &srv_after);

	/* CSV output */
	fprintf(csv, "# MULTI_QP,%s,trial=%d,qp0_status=%d,"
		"qp0_vendor_err=0x%x,latency_us=%.0f,"
		"sibling_errors=%d,siblings_working=%d\n",
		scenario_names[sc], trial, status0,
		vendor_err0, latency, sibling_errors,
		siblings_still_working);

	print_counter_delta("client", &cli_before, &cli_after, csv);
	if (daemon_ok)
		print_counter_delta("server", &srv_before, &srv_after, csv);

	/* Cleanup */
	send_cmd_wait(ctrl_sock, CMD_CLEANUP, CMD_DONE);
	cleanup_multi_qp(&mq);
	return 0;
}

/* ================================================================== */
/*  Main                                                              */
/* ================================================================== */

static void usage(const char *prog)
{
	fprintf(stderr,
		"Usage: %s <condition> <scenario_id> [num_trials]\n\n"
		"Conditions:\n"
		"  A  Multi-WR in-flight (8 normal + 1 faulty)\n"
		"  B  Large message (256KB, multi-packet)\n"
		"  C  Multi-QP (4 QPs, fault on #0)\n\n"
		"Supported scenarios:\n", prog);
	for (size_t i = 0; i < NUM_SUPPORTED; i++)
		fprintf(stderr, "  %2d = %s\n",
			supported_scenarios[i],
			scenario_names[supported_scenarios[i]]);
}

int main(int argc, char **argv)
{
	if (argc < 3) {
		usage(argv[0]);
		return 1;
	}

	/* Parse condition */
	enum multi_condition cond;
	switch (argv[1][0]) {
	case 'A': case 'a': cond = COND_A_MULTI_WR;  break;
	case 'B': case 'b': cond = COND_B_LARGE_MSG;  break;
	case 'C': case 'c': cond = COND_C_MULTI_QP;   break;
	default:
		fprintf(stderr, "Invalid condition '%s'\n", argv[1]);
		usage(argv[0]);
		return 1;
	}

	/* Parse scenario */
	int sc = atoi(argv[2]);
	if (sc <= 0 || sc >= SCENARIO_MAX || !is_supported(sc)) {
		fprintf(stderr, "Unsupported scenario %d\n", sc);
		usage(argv[0]);
		return 1;
	}

	if (argc >= 4)
		num_trials = atoi(argv[3]);

	srand(time(NULL));

	/* Idle check */
	fprintf(stderr, "Checking for background noise...\n");
	if (verify_idle() < 0) {
		fprintf(stderr, "Aborting: background RDMA traffic detected\n");
		return 1;
	}

	/* Create output directory */
	mkdir("results", 0755);
	mkdir("results/multi", 0755);

	/* Open CSV */
	char csv_path[256];
	snprintf(csv_path, sizeof(csv_path), "results/multi/%s_%s.csv",
		 condition_names[cond], scenario_names[sc]);
	FILE *csv = fopen(csv_path, "w");
	if (!csv) {
		perror("fopen csv");
		return 1;
	}
	fprintf(csv, "# multi_client: condition=%s, scenario=%s, "
		"trials=%d\n", condition_names[cond],
		scenario_names[sc], num_trials);

	/* Connect to server */
	ctrl_sock = tcp_connect(RDMA_SERVER_IP, TCP_CTRL_PORT);
	if (ctrl_sock < 0) {
		fprintf(stderr, "Cannot connect to server at %s:%d\n",
			RDMA_SERVER_IP, TCP_CTRL_PORT);
		fclose(csv);
		return 1;
	}
	fprintf(stderr, "Connected to server.\n");

	/* Run trials */
	int ok = 0, fail = 0;
	for (int t = 0; t < num_trials; t++) {
		int ret = -1;

		switch (cond) {
		case COND_A_MULTI_WR:
			ret = run_cond_a(sc, t, csv);
			break;
		case COND_B_LARGE_MSG:
			ret = run_cond_b(sc, t, csv);
			break;
		case COND_C_MULTI_QP:
			ret = run_cond_c(sc, t, csv);
			break;
		default:
			break;
		}

		if (ret == 0)
			ok++;
		else
			fail++;
	}

	/* Summary */
	fprintf(stderr, "\n=== Summary: %d/%d trials succeeded, "
		"%d failed ===\n", ok, num_trials, fail);
	fprintf(csv, "# SUMMARY: ok=%d, fail=%d, total=%d\n",
		ok, fail, num_trials);

	/* Shutdown */
	send_cmd_wait(ctrl_sock, CMD_SHUTDOWN, CMD_DONE);
	close(ctrl_sock);
	fclose(csv);

	fprintf(stderr, "Results written to %s\n", csv_path);
	return (fail > 0) ? 1 : 0;
}
