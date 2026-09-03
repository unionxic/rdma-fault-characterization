/*
 * REM_INV_REQ_ERR recovery benchmark — client (225)
 *
 * Measures recovery after REM_INV_REQ_ERR caused by RDMA WRITE
 * to a server MR that lacks REMOTE_WRITE permission.
 * Server registers MR with LOCAL_WRITE only → Error NAK (code 1).
 *
 * Recovery methods:
 *   QP-only + MR refresh: reset QP, server re-registers MR with correct flags
 *   Full rebuild: destroy all, recreate
 *
 * Usage: ./client [num_trials]
 */

#include "../recovery_common.h"

#define DEFAULT_TRIALS  10
#define CQ_TIMEOUT_MS   5000
#define MR_ACCESS       (IBV_ACCESS_LOCAL_WRITE | IBV_ACCESS_REMOTE_WRITE | \
			 IBV_ACCESS_REMOTE_READ)

#define CMD_SETUP_INV      "SETUP_INV"
#define CMD_RECOVER_QP_MR  "RECOVER_QP_MR"

/* ------------------------------------------------------------------ */
/*  Timing helpers                                                    */
/* ------------------------------------------------------------------ */

static void ts_now(struct timespec *ts)
{
	clock_gettime(CLOCK_MONOTONIC, ts);
}

static long ts_diff_us(struct timespec *start, struct timespec *end)
{
	return (long)((end->tv_sec - start->tv_sec) * 1000000L +
		      (end->tv_nsec - start->tv_nsec) / 1000L);
}

/* ------------------------------------------------------------------ */
/*  Wait for server ack                                               */
/* ------------------------------------------------------------------ */

static int wait_server_ack(int sock, const char *expected)
{
	char buf[64];
	if (tcp_recv_msg(sock, buf, sizeof(buf)) < 0) {
		fprintf(stderr, "ERROR: tcp_recv_msg failed waiting for %s\n",
			expected);
		return -1;
	}
	if (strcmp(buf, expected) != 0) {
		fprintf(stderr, "ERROR: expected '%s', got '%s'\n",
			expected, buf);
		return -1;
	}
	return 0;
}

/* ------------------------------------------------------------------ */
/*  Setup: server creates MR WITHOUT remote write permission          */
/* ------------------------------------------------------------------ */

static int setup_inv_fault(int sock, struct rdma_res *res)
{
	if (tcp_send_msg(sock, CMD_SETUP_INV) < 0)
		return -1;
	if (wait_server_ack(sock, CMD_READY) < 0)
		return -1;

	/* Client creates resources with full RDMA WRITE capability */
	if (setup_rdma(res, 1, MR_ACCESS, 7, 7, 14) < 0) {
		fprintf(stderr, "ERROR: setup_rdma failed\n");
		return -1;
	}

	if (tcp_exchange_qp_info(sock, &res->local_info,
				 &res->remote_info, 0) < 0) {
		fprintf(stderr, "ERROR: QP info exchange failed\n");
		return -1;
	}

	/* QP connect with RDMA access on client side */
	if (connect_qp(res, 7, 7, 7, 14) < 0) {
		fprintf(stderr, "ERROR: connect_qp failed\n");
		return -1;
	}

	/*
	 * No verify WRITE here — server MR has no REMOTE_WRITE permission,
	 * so any RDMA WRITE would immediately trigger REM_INV_REQ_ERR.
	 */
	fprintf(stderr, "  [setup] QP connected (server MR has no REMOTE_WRITE)\n");
	return 0;
}

/* ------------------------------------------------------------------ */
/*  Inject: RDMA WRITE → REM_INV_REQ_ERR (Error NAK code 1)          */
/* ------------------------------------------------------------------ */

static int inject_and_detect(struct rdma_res *res, struct ibv_wc *wc,
			     struct timespec *t_start, struct timespec *t_detect)
{
	ts_now(t_start);
	if (post_rdma_write(res, NULL) != 0) {
		fprintf(stderr, "ERROR: post_rdma_write failed: %s\n",
			strerror(errno));
		return -1;
	}

	int n = poll_cq_block(res->cq, wc, CQ_TIMEOUT_MS);
	ts_now(t_detect);

	if (n <= 0) {
		fprintf(stderr, "ERROR: poll_cq timed out (n=%d)\n", n);
		return -1;
	}

	if (wc->status == IBV_WC_SUCCESS) {
		fprintf(stderr, "ERROR: expected error CQE, got success\n");
		return -1;
	}

	fprintf(stderr, "  [detect] status=%d (%s) vendor_err=0x%x\n",
		wc->status, ibv_wc_status_str(wc->status), wc->vendor_err);

	return 0;
}

/* ------------------------------------------------------------------ */
/*  QP-only + MR refresh recovery                                     */
/* ------------------------------------------------------------------ */

static int recover_qp_mr(int sock, struct rdma_res *res,
			 struct timespec *t_start, struct timespec *t_done)
{
	ts_now(t_start);

	if (reset_qp_to_reset(res->qp) < 0)
		return -1;

	res->local_info.psn = rand() & 0xFFFFFF;

	/* Server will: reset QP, re-register MR WITH remote write, send new info */
	if (tcp_send_msg(sock, CMD_RECOVER_QP_MR) < 0)
		return -1;

	if (tcp_exchange_qp_info(sock, &res->local_info,
				 &res->remote_info, 0) < 0)
		return -1;

	if (connect_qp(res, 7, 7, 7, 14) < 0) {
		fprintf(stderr, "ERROR: connect_qp in recovery failed\n");
		return -1;
	}

	if (wait_server_ack(sock, CMD_READY) < 0)
		return -1;

	ts_now(t_done);
	return 0;
}

/* ------------------------------------------------------------------ */
/*  Full rebuild recovery                                             */
/* ------------------------------------------------------------------ */

static int recover_full_rebuild(int sock, struct rdma_res *res,
				struct timespec *t_start,
				struct timespec *t_done)
{
	ts_now(t_start);

	cleanup_rdma(res);

	if (tcp_send_msg(sock, CMD_RECOVER_FULL) < 0)
		return -1;

	if (setup_rdma(res, 1, MR_ACCESS, 7, 7, 14) < 0) {
		fprintf(stderr, "ERROR: setup_rdma in full rebuild failed\n");
		return -1;
	}

	if (tcp_exchange_qp_info(sock, &res->local_info,
				 &res->remote_info, 0) < 0)
		return -1;

	if (connect_qp(res, 7, 7, 7, 14) < 0) {
		fprintf(stderr, "ERROR: connect_qp in full rebuild failed\n");
		return -1;
	}

	if (wait_server_ack(sock, CMD_READY) < 0)
		return -1;

	ts_now(t_done);
	return 0;
}

/* ------------------------------------------------------------------ */
/*  Retry: RDMA WRITE with new rkey should succeed                    */
/* ------------------------------------------------------------------ */

static int retry_and_verify(struct rdma_res *res,
			    struct timespec *t_start,
			    struct timespec *t_done)
{
	struct ibv_wc wc;

	ts_now(t_start);
	if (post_rdma_write(res, NULL) != 0) {
		fprintf(stderr, "ERROR: retry post_rdma_write failed: %s\n",
			strerror(errno));
		return -1;
	}

	int n = poll_cq_block(res->cq, &wc, CQ_TIMEOUT_MS);
	ts_now(t_done);

	if (n <= 0) {
		fprintf(stderr, "ERROR: retry poll_cq timed out (n=%d)\n", n);
		return -1;
	}
	if (wc.status != IBV_WC_SUCCESS) {
		fprintf(stderr, "ERROR: retry failed: status=%d (%s)\n",
			wc.status, ibv_wc_status_str(wc.status));
		return -1;
	}

	fprintf(stderr, "  [retry] RDMA WRITE success with correct permissions\n");
	return 0;
}

/* ------------------------------------------------------------------ */
/*  Run one trial                                                     */
/* ------------------------------------------------------------------ */

static int run_trial(int sock, int trial, const char *method,
		     struct recovery_timing *timing)
{
	struct rdma_res res;
	struct ibv_wc wc;
	struct timespec t_start, t_detect;
	struct timespec t_recover_start, t_recover_done;
	struct timespec t_retry_start, t_retry_done;

	memset(&res, 0, sizeof(res));
	memset(timing, 0, sizeof(*timing));

	fprintf(stderr, "\n--- Trial %d, method=%s ---\n", trial, method);

	/* 1. Setup with permission-less server MR */
	if (setup_inv_fault(sock, &res) < 0)
		return -1;

	/* 2. RDMA WRITE to MR without REMOTE_WRITE → REM_INV_REQ_ERR */
	if (inject_and_detect(&res, &wc, &t_start, &t_detect) < 0) {
		cleanup_rdma(&res);
		return -1;
	}
	timing->detect_us = ts_diff_us(&t_start, &t_detect);

	/* 3. Recovery */
	if (strcmp(method, "QP_MR") == 0) {
		if (recover_qp_mr(sock, &res,
				  &t_recover_start, &t_recover_done) < 0) {
			cleanup_rdma(&res);
			return -1;
		}
	} else {
		if (recover_full_rebuild(sock, &res,
					&t_recover_start, &t_recover_done) < 0) {
			cleanup_rdma(&res);
			return -1;
		}
	}
	timing->recovery_us = ts_diff_us(&t_recover_start, &t_recover_done);

	/* 4. Retry WRITE with correct permissions */
	if (retry_and_verify(&res, &t_retry_start, &t_retry_done) < 0) {
		cleanup_rdma(&res);
		return -1;
	}
	timing->retry_us = ts_diff_us(&t_retry_start, &t_retry_done);
	timing->total_us = ts_diff_us(&t_start, &t_retry_done);

	fprintf(stderr, "  detect=%ld us, recovery=%ld us, "
		"retry=%ld us, total=%ld us\n",
		timing->detect_us, timing->recovery_us,
		timing->retry_us, timing->total_us);

	/* 5. Cleanup */
	tcp_send_msg(sock, CMD_CLEANUP);
	wait_server_ack(sock, CMD_DONE);
	cleanup_rdma(&res);

	return 0;
}

/* ------------------------------------------------------------------ */
/*  main                                                              */
/* ------------------------------------------------------------------ */

int main(int argc, char *argv[])
{
	int num_trials = DEFAULT_TRIALS;
	if (argc > 1)
		num_trials = atoi(argv[1]);
	if (num_trials <= 0)
		num_trials = DEFAULT_TRIALS;

	srand(time(NULL));

	fprintf(stderr, "REM_INV_REQ_ERR recovery benchmark: %d trials per method\n",
		num_trials);

	int sock = tcp_connect(RDMA_SERVER_IP, TCP_CTRL_PORT);
	if (sock < 0) {
		fprintf(stderr, "ERROR: cannot connect to server %s:%d\n",
			RDMA_SERVER_IP, TCP_CTRL_PORT);
		return 1;
	}
	fprintf(stderr, "Connected to server\n");

	printf("# REM_INV_REQ_ERR recovery benchmark\n");
	printf("# trial,method,detect_us,recovery_us,retry_us,total_us\n");

	struct recovery_timing timing;
	int failed = 0;

	/* --- QP-only + MR refresh --- */
	fprintf(stderr, "\n========== QP-only + MR refresh ==========\n");
	for (int i = 0; i < num_trials; i++) {
		if (run_trial(sock, i, "QP_MR", &timing) < 0) {
			fprintf(stderr, "ERROR: trial %d QP_MR failed\n", i);
			failed++;
			continue;
		}
		printf("%d,QP_MR,%ld,%ld,%ld,%ld\n",
		       i, timing.detect_us, timing.recovery_us,
		       timing.retry_us, timing.total_us);
		fflush(stdout);
	}

	/* --- Full rebuild --- */
	fprintf(stderr, "\n========== Full rebuild ==========\n");
	for (int i = 0; i < num_trials; i++) {
		if (run_trial(sock, i, "FULL", &timing) < 0) {
			fprintf(stderr, "ERROR: trial %d FULL failed\n", i);
			failed++;
			continue;
		}
		printf("%d,FULL,%ld,%ld,%ld,%ld\n",
		       i, timing.detect_us, timing.recovery_us,
		       timing.retry_us, timing.total_us);
		fflush(stdout);
	}

	tcp_send_msg(sock, CMD_SHUTDOWN);
	close(sock);

	fprintf(stderr, "\nDone. %d trials failed out of %d total.\n",
		failed, num_trials * 2);
	return (failed > 0) ? 1 : 0;
}
