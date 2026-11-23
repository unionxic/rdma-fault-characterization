#include "common.h"

/*
 * verify_interrupted_write.c  (client / requester, runs on 225)
 *
 * Goal: show that a mid-transfer partial RDMA WRITE (timeout / peer-death
 * path) is broken on PMTU-packet boundaries, and that the requester can
 * reconstruct how many bytes actually landed purely from its own SQ PSN:
 *
 *     bytes_written_on_responder  ==  sq_psn_delta * PMTU
 *
 * This extends verify_partial_write.c, which proved the same identity for an
 * ADDRESS-violation (REM_ACCESS_ERR) partial write with zero error. Here the
 * WRITE target is fully INSIDE the responder MR (8MB buf + 8MB MR), so the
 * partial is caused not by a bounds check but by the responder QP being
 * driven to ERR while 4096 PMTU(1024) packets are on the wire.
 *
 * This is NOT deterministic: the RDMA WRITE is fast (4MB ~= 320us of wire
 * time at 100Gbps) and the interrupt arrives over TCP, so the fault lands at
 * a random point in (or after) the transfer. We use a large WRITE to widen
 * the race window and run many trials to collect the partial ones.
 *
 * Measurement subtlety (sq_psn):
 *   We query sq_psn at THREE points:
 *     - sq_psn_before     : before post_send, QP in RTS
 *     - sq_psn_after_wait : after the settle delay, QP STILL in RTS. This is
 *                           the clean observable: it reflects ACK progress
 *                           only, with no local-ERR transition artifact. The
 *                           required CSV columns (sq_psn_after / delta / match)
 *                           use THIS value.
 *     - sq_psn_after_cqe  : after we force the LOCAL QP to ERR (to get a fast
 *                           flush CQE instead of waiting ~3.7s for
 *                           RETRY_EXC_ERR). Recorded separately so we can see
 *                           whether the ERR transition perturbs sq_psn.
 *
 * Reuses: 0xAA fill + responder-side non-zero byte count (within_mod) and
 * last non-zero offset (last_mod), exactly as in verify_partial_write.c.
 */

static struct rdma_res res;
static int ctrl_sock = -1;
static int num_trials = 100;
static int settle_ms = 80;   /* delay post_send -> query -> local ERR */

struct run_summary {
	int trials;          /* completed trials (CQE seen)            */
	int full;            /* within_mod == write_len (no partial)   */
	int partial;         /* 0 < within_mod < write_len             */
	int nowrite;         /* within_mod == 0                        */
	int pmtu_aligned;    /* within_mod % PMTU == 0 (among partials)*/
	int psn_match;       /* psn_delta*PMTU == within_mod (partials)*/
};

static int send_cmd_wait(int sock, const char *cmd, const char *expect)
{
	tcp_send_msg(sock, cmd);
	char resp[256];
	if (tcp_recv_msg(sock, resp, sizeof(resp)) <= 0) {
		fprintf(stderr, "  no response to '%s'\n", cmd);
		return -1;
	}
	if (expect && strcmp(resp, expect) != 0) {
		fprintf(stderr, "  expected '%s', got '%s'\n", expect, resp);
		return -1;
	}
	return 0;
}

static uint32_t query_sq_psn(struct ibv_qp *qp)
{
	struct ibv_qp_attr qattr;
	struct ibv_qp_init_attr qinit;
	if (ibv_query_qp(qp, &qattr, IBV_QP_SQ_PSN, &qinit) == 0)
		return qattr.sq_psn;
	return 0;
}

static void force_qp_err(struct ibv_qp *qp)
{
	struct ibv_qp_attr attr = { .qp_state = IBV_QPS_ERR };
	if (ibv_modify_qp(qp, &attr, IBV_QP_STATE))
		fprintf(stderr, "  local ibv_modify_qp(ERR) failed: %s\n",
			strerror(errno));
}

static int run_trial(int trial, FILE *csv, struct run_summary *sum)
{
	fprintf(stderr, "\n--- interrupted_write trial %d ---\n", trial);

	/* Server: register 8MB buf + 8MB MR, exchange QP, connect. */
	tcp_send_msg(ctrl_sock, CMD_SETUP_LARGE);

	/* Client: standard setup, then swap in a large local buffer + MR so
	 * the 4MB source SGE is covered by LOCAL_WRITE. */
	int access = IBV_ACCESS_LOCAL_WRITE | IBV_ACCESS_REMOTE_WRITE |
		     IBV_ACCESS_REMOTE_READ;
	if (setup_rdma(&res, 0, access, 7, 7, 14) < 0)
		return -1;

	ibv_dereg_mr(res.mr);
	free(res.buf);
	res.buf = calloc(1, LARGE_BUF_SIZE);
	if (!res.buf) {
		fprintf(stderr, "  client calloc(%d) failed\n", LARGE_BUF_SIZE);
		cleanup_rdma(&res);
		return -1;
	}
	res.buf_size = LARGE_BUF_SIZE;
	res.mr = ibv_reg_mr(res.pd, res.buf, LARGE_BUF_SIZE, access);
	if (!res.mr) {
		fprintf(stderr, "  client ibv_reg_mr(%d) failed: %s\n",
			LARGE_BUF_SIZE, strerror(errno));
		cleanup_rdma(&res);
		return -1;
	}
	res.local_info.rkey = res.mr->rkey;
	res.local_info.raddr = (uint64_t)res.buf;

	tcp_exchange_qp_info(ctrl_sock, &res.local_info, &res.remote_info, 0);

	if (connect_qp(&res, 1, 7, 7, 14) < 0) {
		cleanup_rdma(&res);
		return -1;
	}

	char resp[256];
	if (tcp_recv_msg(ctrl_sock, resp, sizeof(resp)) <= 0 ||
	    strcmp(resp, CMD_READY) != 0) {
		fprintf(stderr, "  server not READY (got '%s')\n", resp);
		cleanup_rdma(&res);
		return -1;
	}

	/* Verify the path with a tiny normal WRITE (into server buf[0..63]). */
	{
		struct ibv_sge sge = {
			.addr = (uint64_t)res.buf,
			.length = 64,
			.lkey = res.mr->lkey,
		};
		struct ibv_send_wr wr = {
			.wr_id = 1,
			.sg_list = &sge,
			.num_sge = 1,
			.opcode = IBV_WR_RDMA_WRITE,
			.send_flags = IBV_SEND_SIGNALED,
			.wr.rdma = {
				.remote_addr = res.remote_info.raddr,
				.rkey = res.remote_info.rkey,
			},
		};
		struct ibv_send_wr *bad;
		struct ibv_wc wc;
		if (ibv_post_send(res.qp, &wr, &bad) ||
		    poll_cq_block(res.cq, &wc, 5000) <= 0 ||
		    wc.status != IBV_WC_SUCCESS) {
			fprintf(stderr, "  connection verify WRITE failed\n");
			cleanup_rdma(&res);
			return -1;
		}
	}
	fprintf(stderr, "  connection verified\n");

	/* Zero the server buffer (clears the 64B verify write). */
	if (send_cmd_wait(ctrl_sock, CMD_INIT_LARGE, CMD_DONE) < 0) {
		cleanup_rdma(&res);
		return -1;
	}

	/* Fill the whole 4MB source region with 0xAA. */
	memset(res.buf, 0xAA, LARGE_WRITE_LEN);

	/* The large in-bounds WRITE: 4MB = 4096 PMTU(1024) packets. */
	struct ibv_sge sge = {
		.addr = (uint64_t)res.buf,
		.length = LARGE_WRITE_LEN,
		.lkey = res.mr->lkey,
	};
	struct ibv_send_wr wr = {
		.wr_id = 1,
		.sg_list = &sge,
		.num_sge = 1,
		.opcode = IBV_WR_RDMA_WRITE,
		.send_flags = IBV_SEND_SIGNALED,
		.wr.rdma = {
			.remote_addr = res.remote_info.raddr,  /* offset 0, in-MR */
			.rkey = res.remote_info.rkey,
		},
	};
	struct ibv_send_wr *bad;

	uint32_t psn_before = query_sq_psn(res.qp);

	struct timespec t0, t1;
	clock_gettime(CLOCK_MONOTONIC, &t0);

	/* RACE: post the multi-packet WRITE, then immediately tell the server
	 * to drive its QP to ERR. The two back-to-back lines below ARE the
	 * fault-timing logic: how soon the responder ERR lands relative to the
	 * in-flight packets determines how much of the WRITE is partial. */
	int post_ret = ibv_post_send(res.qp, &wr, &bad);
	tcp_send_msg(ctrl_sock, CMD_INTERRUPT);

	if (post_ret) {
		fprintf(stderr, "  ibv_post_send(4MB) failed: %s\n",
			strerror(post_ret));
		/* still drain the INTERRUPT ack so the channel stays in sync */
		tcp_recv_msg(ctrl_sock, resp, sizeof(resp));
		cleanup_rdma(&res);
		return -1;
	}

	/* Drain the server's INTERRUPT ack (DONE / ERROR). */
	if (tcp_recv_msg(ctrl_sock, resp, sizeof(resp)) <= 0) {
		fprintf(stderr, "  no INTERRUPT ack\n");
		cleanup_rdma(&res);
		return -1;
	}

	/* Let ACKs for pre-ERR packets settle, then read sq_psn while the QP
	 * is STILL in RTS. This is the clean PSN observable. */
	usleep(settle_ms * 1000);
	uint32_t psn_after_wait = query_sq_psn(res.qp);

	/* Force LOCAL QP to ERR to flush the outstanding WQE -> fast CQE,
	 * instead of waiting ~3.7s for RETRY_EXC_ERR. */
	force_qp_err(res.qp);

	struct ibv_wc wc;
	memset(&wc, 0, sizeof(wc));
	int n = poll_cq_block(res.cq, &wc, 2000);
	clock_gettime(CLOCK_MONOTONIC, &t1);

	uint32_t psn_after_cqe = query_sq_psn(res.qp);

	double latency = elapsed_us(&t0, &t1);

	if (n <= 0) {
		fprintf(stderr, "  poll timeout (no flush CQE in 2000ms)\n");
		/* QP is in ERR; clean up and skip this trial. */
		send_cmd_wait(ctrl_sock, CMD_CLEANUP, CMD_DONE);
		cleanup_rdma(&res);
		return -1;
	}

	/* sq_psn columns use the RTS-time value (clean observable). */
	uint32_t psn_after  = psn_after_wait;
	uint32_t psn_delta  = (psn_after - psn_before) & 0xFFFFFF;
	uint32_t psn_delta_cqe = (psn_after_cqe - psn_before) & 0xFFFFFF;

	/* Ask the responder how many bytes actually landed. */
	char check_cmd[64];
	snprintf(check_cmd, sizeof(check_cmd), "%s %d",
		 CMD_CHECK_LARGE, LARGE_WRITE_LEN);
	tcp_send_msg(ctrl_sock, check_cmd);

	char buf_resp[256];
	if (tcp_recv_msg(ctrl_sock, buf_resp, sizeof(buf_resp)) <= 0) {
		fprintf(stderr, "  no CHECK_LARGE response\n");
		send_cmd_wait(ctrl_sock, CMD_CLEANUP, CMD_DONE);
		cleanup_rdma(&res);
		return -1;
	}

	long within_mod = -1, last_mod = -1, srv_len = 0;
	sscanf(buf_resp, "LARGE:%ld:last=%ld:len=%ld",
	       &within_mod, &last_mod, &srv_len);

	long write_len = LARGE_WRITE_LEN;
	int is_pmtu_multiple = (within_mod >= 0 &&
				(within_mod % PMTU_BYTES) == 0) ? 1 : 0;
	long psn_x_pmtu = (long)psn_delta * PMTU_BYTES;
	int match = (psn_x_pmtu == within_mod) ? 1 : 0;
	long psn_x_pmtu_cqe = (long)psn_delta_cqe * PMTU_BYTES;

	const char *klass;
	if (within_mod <= 0)
		klass = "NO_WRITE";
	else if (within_mod >= write_len)
		klass = "FULL";
	else
		klass = "PARTIAL";

	fprintf(stderr,
		"  CQE: status=%d (%s) vendor_err=0x%x lat=%.0fus | %s\n",
		wc.status, ibv_wc_status_str(wc.status), wc.vendor_err,
		latency, klass);
	fprintf(stderr,
		"  within_mod=%ld last_mod=%ld | sq_psn %u->%u (delta %u) "
		"psn*PMTU=%ld %s | psn_after_cqe=%u (delta %u, *PMTU=%ld)\n",
		within_mod, last_mod, psn_before, psn_after, psn_delta,
		psn_x_pmtu, match ? "MATCH" : "MISS",
		psn_after_cqe, psn_delta_cqe, psn_x_pmtu_cqe);

	/* CSV row. Required columns first, then the diagnostic extras. */
	fprintf(csv,
		"%d,%d,0x%x,%u,%u,%u,%ld,%ld,%ld,%d,%ld,%d,"
		"%.0f,%u,%u,%ld,%u,%s\n",
		trial, wc.status, wc.vendor_err,
		psn_before, psn_after, psn_delta,
		within_mod, last_mod, write_len,
		is_pmtu_multiple, psn_x_pmtu, match,
		latency, wc.byte_len, psn_after_cqe, psn_x_pmtu_cqe,
		psn_delta_cqe, klass);
	fflush(csv);

	/* Aggregate. */
	sum->trials++;
	if (within_mod <= 0) {
		sum->nowrite++;
	} else if (within_mod >= write_len) {
		sum->full++;
	} else {
		sum->partial++;
		if (is_pmtu_multiple)
			sum->pmtu_aligned++;
		if (match)
			sum->psn_match++;
	}

	/* Tear down this trial's RDMA state (server + client). */
	if (send_cmd_wait(ctrl_sock, CMD_CLEANUP, CMD_DONE) < 0) {
		cleanup_rdma(&res);
		return -1;
	}
	cleanup_rdma(&res);
	return 0;
}

int main(int argc, char **argv)
{
	if (argc >= 2)
		num_trials = atoi(argv[1]);
	if (argc >= 3)
		settle_ms = atoi(argv[2]);

	srand(time(NULL));

	ctrl_sock = tcp_connect(RDMA_SERVER_IP, TCP_CTRL_PORT);
	if (ctrl_sock < 0) {
		fprintf(stderr, "Cannot connect to server at %s:%d\n",
			RDMA_SERVER_IP, TCP_CTRL_PORT);
		return 1;
	}

	FILE *csv = fopen("results/raw/interrupted_write_verify.csv", "w");
	if (!csv) {
		perror("fopen csv");
		close(ctrl_sock);
		return 1;
	}
	fprintf(csv,
		"trial,wc_status,vendor_err,"
		"sq_psn_before,sq_psn_after,sq_psn_delta,"
		"within_mod,last_mod,write_len,"
		"is_pmtu_multiple,psn_x_pmtu,match,"
		"latency_us,byte_len,sq_psn_after_cqe,psn_x_pmtu_cqe,"
		"sq_psn_delta_cqe,class\n");

	fprintf(stderr, "=== Interrupted WRITE (timeout/peer-death) test ===\n");
	fprintf(stderr, "trials=%d settle=%dms write=%dMB (%d PMTU pkts) PMTU=%dB\n",
		num_trials, settle_ms, LARGE_WRITE_LEN >> 20,
		LARGE_WRITE_LEN / PMTU_BYTES, PMTU_BYTES);

	struct run_summary sum = {0};
	for (int t = 0; t < num_trials; t++) {
		if (run_trial(t, csv, &sum) < 0)
			fprintf(stderr, "  trial %d failed (skipped)\n", t);
	}

	send_cmd_wait(ctrl_sock, CMD_SHUTDOWN, CMD_DONE);
	close(ctrl_sock);
	fclose(csv);

	/* Summary on stderr (human) + a final line for quick eyeballing. */
	fprintf(stderr, "\n");
	fprintf(stderr, "============================================================\n");
	fprintf(stderr, "  Interrupted WRITE results (n=%d completed)\n", sum.trials);
	fprintf(stderr, "============================================================\n");
	fprintf(stderr, "  FULL (no partial)      : %d\n", sum.full);
	fprintf(stderr, "  NO_WRITE (ERR too soon): %d\n", sum.nowrite);
	fprintf(stderr, "  PARTIAL                : %d\n", sum.partial);
	if (sum.partial > 0) {
		fprintf(stderr, "    of which within_mod %% %d == 0 : %d/%d (%.0f%%)\n",
			PMTU_BYTES, sum.pmtu_aligned, sum.partial,
			100.0 * sum.pmtu_aligned / sum.partial);
		fprintf(stderr, "    of which psn_delta*PMTU == within_mod : %d/%d (%.0f%%)\n",
			sum.psn_match, sum.partial,
			100.0 * sum.psn_match / sum.partial);
	} else {
		fprintf(stderr, "    no PARTIAL trials captured -- widen the race:\n");
		fprintf(stderr, "    try a larger WRITE or smaller settle_ms.\n");
	}
	fprintf(stderr, "  CSV: results/raw/interrupted_write_verify.csv\n");

	return 0;
}
