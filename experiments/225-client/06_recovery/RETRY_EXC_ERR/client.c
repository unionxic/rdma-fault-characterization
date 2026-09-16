/*
 * RETRY_EXC_ERR recovery benchmark — client (225)
 *
 * Measures recovery paths after RETRY_EXC_ERR (transport retry exhaustion):
 *   Path C: QP-only recovery (bilateral reset + PSN re-exchange)
 *   Path B: Full RDMA resource rebuild
 *
 *   Path A: Driver reload (modprobe -r mlx5_ib + modprobe mlx5_ib)
 *
 * Fault trigger: Server QP forced to ERR via ibv_modify_qp.
 * Client's SEND gets no ACK → retries exhaust → CQE error.
 * Uses retry_cnt=7 (NCCL default) for production-realistic detection.
 *
 * Usage: ./client [num_trials]
 *        Path A requires root (sudo) for modprobe.
 */

#include "../recovery_common.h"

#define DEFAULT_TRIALS  10
#define CQ_TIMEOUT_MS   10000
#define MR_ACCESS       (IBV_ACCESS_LOCAL_WRITE | IBV_ACCESS_REMOTE_WRITE | \
			 IBV_ACCESS_REMOTE_READ)

#define CMD_SETUP_RETRY   "SETUP_RETRY"
#define CMD_INJECT_FAULT  "INJECT_FAULT"

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
/*  Setup: establish connection, then inject fault                    */
/* ------------------------------------------------------------------ */

static int setup_retry_fault(int sock, struct rdma_res *res)
{
	/* Tell server to setup normally */
	if (tcp_send_msg(sock, CMD_SETUP_RETRY) < 0)
		return -1;
	if (wait_server_ack(sock, CMD_READY) < 0)
		return -1;

	/* Client: create resources with retry_cnt=7 (NCCL default) */
	if (setup_rdma(res, 1, MR_ACCESS, 7, 7, 14) < 0) {
		fprintf(stderr, "ERROR: setup_rdma failed\n");
		return -1;
	}

	/* Exchange QP info */
	if (tcp_exchange_qp_info(sock, &res->local_info,
				 &res->remote_info, 0) < 0) {
		fprintf(stderr, "ERROR: QP info exchange failed\n");
		return -1;
	}

	/* Connect QP: retry_cnt=7, timeout=14 (production-realistic) */
	if (connect_qp(res, 0, 7, 0, 14) < 0) {
		fprintf(stderr, "ERROR: connect_qp failed\n");
		return -1;
	}

	/* Tell server to move its QP to ERR */
	if (tcp_send_msg(sock, CMD_INJECT_FAULT) < 0)
		return -1;
	if (wait_server_ack(sock, CMD_READY) < 0)
		return -1;

	return 0;
}

/* ------------------------------------------------------------------ */
/*  Inject fault and measure detection time                           */
/* ------------------------------------------------------------------ */

static int inject_and_detect(struct rdma_res *res, struct ibv_wc *wc,
			     struct timespec *t_start, struct timespec *t_detect)
{
	ts_now(t_start);
	if (post_send(res) != 0) {
		fprintf(stderr, "ERROR: post_send failed: %s\n",
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
	if (wc->status != IBV_WC_RETRY_EXC_ERR)
		fprintf(stderr, "WARN: expected RETRY_EXC_ERR, got status=%d (%s) "
			"— passive baseline may be measuring a different fault\n",
			wc->status, ibv_wc_status_str(wc->status));

	fprintf(stderr, "  [detect] status=%d (%s) vendor_err=0x%x\n",
		wc->status, ibv_wc_status_str(wc->status), wc->vendor_err);

	return 0;
}

/* ------------------------------------------------------------------ */
/*  Path C: QP-only recovery (bilateral)                              */
/* ------------------------------------------------------------------ */

static int recover_qp_only(int sock, struct rdma_res *res,
			   struct timespec *t_start, struct timespec *t_done)
{
	ts_now(t_start);

	if (reset_qp_to_reset(res->qp) < 0)
		return -1;

	res->local_info.psn = rand() & 0xFFFFFF;

	if (tcp_send_msg(sock, CMD_RECOVER_QP) < 0)
		return -1;

	if (tcp_exchange_qp_info(sock, &res->local_info,
				 &res->remote_info, 0) < 0)
		return -1;

	if (connect_qp(res, 0, 7, 7, 14) < 0) {
		fprintf(stderr, "ERROR: connect_qp in QP recovery failed\n");
		return -1;
	}

	if (wait_server_ack(sock, CMD_READY) < 0)
		return -1;

	ts_now(t_done);
	return 0;
}

/* ------------------------------------------------------------------ */
/*  Path B: Full RDMA resource rebuild                                */
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

	if (connect_qp(res, 0, 7, 7, 14) < 0) {
		fprintf(stderr, "ERROR: connect_qp in full rebuild failed\n");
		return -1;
	}

	if (wait_server_ack(sock, CMD_READY) < 0)
		return -1;

	ts_now(t_done);
	return 0;
}

/* ------------------------------------------------------------------ */
/*  Path A: Driver reload recovery                                    */
/* ------------------------------------------------------------------ */

static int setup_rdma_retry(struct rdma_res *res, int buf_count,
			    int mr_access, int timeout_ms)
{
	struct timespec start, now;
	clock_gettime(CLOCK_MONOTONIC, &start);

	while (1) {
		memset(res, 0, sizeof(*res));
		if (setup_rdma(res, buf_count, mr_access, 7, 7, 14) == 0)
			return 0;

		/* setup_rdma may have partially allocated ctx/pd/cq/qp/mr/buf
		 * before failing (e.g. at the RoCEv2-GID check while the GID
		 * table repopulates after modprobe). Free it before retrying so
		 * the next memset doesn't leak the handles. cleanup_rdma is
		 * NULL-tolerant on partial allocation. */
		cleanup_rdma(res);

		clock_gettime(CLOCK_MONOTONIC, &now);
		long elapsed_ms = (now.tv_sec - start.tv_sec) * 1000 +
				  (now.tv_nsec - start.tv_nsec) / 1000000;
		if (elapsed_ms > timeout_ms) {
			fprintf(stderr, "ERROR: setup_rdma timed out after %dms\n",
				timeout_ms);
			return -1;
		}

		fprintf(stderr, "  waiting for GID table (%ldms)...\n", elapsed_ms);
		usleep(100000);
	}
}

static int recover_driver_reload(int sock, struct rdma_res *res,
				 struct timespec *t_start,
				 struct timespec *t_done)
{
	ts_now(t_start);

	cleanup_rdma(res);

	if (tcp_send_msg(sock, CMD_RECOVER_FULL) < 0)
		return -1;

	int rc = system("sudo modprobe -r mlx5_ib && sudo modprobe mlx5_ib");
	if (rc != 0) {
		fprintf(stderr, "ERROR: driver reload failed (rc=%d)\n", rc);
		return -1;
	}
	usleep(500000);
	/* Best-effort device rename after reload; consume return to satisfy
	 * -Wunused-result. The trailing "; true" makes the shell rc 0 anyway. */
	if (system("dev=$(ls /sys/class/infiniband/ 2>/dev/null | head -1); "
	       "[ -n \"$dev\" ] && [ \"$dev\" != \"mlx5_0\" ] && "
	       "sudo rdma dev set \"$dev\" name mlx5_0 2>/dev/null; true") != 0)
		fprintf(stderr, "WARN: device rename best-effort step failed\n");

	if (setup_rdma_retry(res, 1, MR_ACCESS, 5000) < 0) {
		fprintf(stderr, "ERROR: setup_rdma after driver reload failed\n");
		return -1;
	}

	if (tcp_exchange_qp_info(sock, &res->local_info,
				 &res->remote_info, 0) < 0)
		return -1;

	if (connect_qp(res, 0, 7, 7, 14) < 0) {
		fprintf(stderr, "ERROR: connect_qp after driver reload failed\n");
		return -1;
	}

	if (wait_server_ack(sock, CMD_READY) < 0)
		return -1;

	ts_now(t_done);
	return 0;
}

/* ------------------------------------------------------------------ */
/*  Retry: post SEND and verify success                               */
/* ------------------------------------------------------------------ */

static int retry_and_verify(struct rdma_res *res,
			    struct timespec *t_start,
			    struct timespec *t_done)
{
	struct ibv_wc wc;

	ts_now(t_start);
	if (post_send(res) != 0) {
		fprintf(stderr, "ERROR: retry post_send failed: %s\n",
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

	fprintf(stderr, "  [retry] success\n");
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

	/* 1. Setup: establish connection then inject fault */
	if (setup_retry_fault(sock, &res) < 0)
		return -1;

	/* 2. Inject: SEND to dead server QP → timeout → RETRY_EXC_ERR */
	if (inject_and_detect(&res, &wc, &t_start, &t_detect) < 0) {
		cleanup_rdma(&res);
		return -1;
	}
	timing->detect_us = ts_diff_us(&t_start, &t_detect);

	/* 3. Recovery */
	if (strcmp(method, "C") == 0) {
		if (recover_qp_only(sock, &res,
				    &t_recover_start, &t_recover_done) < 0) {
			cleanup_rdma(&res);
			return -1;
		}
	} else if (strcmp(method, "B") == 0) {
		if (recover_full_rebuild(sock, &res,
					&t_recover_start, &t_recover_done) < 0) {
			cleanup_rdma(&res);
			return -1;
		}
	} else { /* method == "A" */
		if (recover_driver_reload(sock, &res,
					 &t_recover_start, &t_recover_done) < 0) {
			cleanup_rdma(&res);
			return -1;
		}
	}
	timing->recovery_us = ts_diff_us(&t_recover_start, &t_recover_done);

	/* 4. Retry: SEND should succeed now */
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

	fprintf(stderr, "RETRY_EXC_ERR recovery benchmark: %d trials per method\n",
		num_trials);

	int sock = tcp_connect(RDMA_SERVER_IP, TCP_CTRL_PORT);
	if (sock < 0) {
		fprintf(stderr, "ERROR: cannot connect to server %s:%d\n",
			RDMA_SERVER_IP, TCP_CTRL_PORT);
		return 1;
	}
	fprintf(stderr, "Connected to server\n");

	printf("# RETRY_EXC_ERR recovery benchmark\n");
	printf("# trial,method,detect_us,recovery_us,retry_us,total_us\n");

	struct recovery_timing timing;
	int failed = 0;

	/* --- Path C: QP-only recovery --- */
	fprintf(stderr, "\n========== Path C: QP-only recovery ==========\n");
	for (int i = 0; i < num_trials; i++) {
		if (run_trial(sock, i, "C", &timing) < 0) {
			fprintf(stderr, "ERROR: trial %d method C failed\n", i);
			failed++;
			continue;
		}
		printf("%d,C,%ld,%ld,%ld,%ld\n",
		       i, timing.detect_us, timing.recovery_us,
		       timing.retry_us, timing.total_us);
		fflush(stdout);
	}

	/* --- Path B: Full rebuild --- */
	fprintf(stderr, "\n========== Path B: Full RDMA rebuild ==========\n");
	for (int i = 0; i < num_trials; i++) {
		if (run_trial(sock, i, "B", &timing) < 0) {
			fprintf(stderr, "ERROR: trial %d method B failed\n", i);
			failed++;
			continue;
		}
		printf("%d,B,%ld,%ld,%ld,%ld\n",
		       i, timing.detect_us, timing.recovery_us,
		       timing.retry_us, timing.total_us);
		fflush(stdout);
	}

	/* --- Path A: Driver reload --- */
	fprintf(stderr, "\n========== Path A: Driver reload ==========\n");
	for (int i = 0; i < num_trials; i++) {
		if (run_trial(sock, i, "A", &timing) < 0) {
			fprintf(stderr, "ERROR: trial %d method A failed\n", i);
			failed++;
			continue;
		}
		printf("%d,A,%ld,%ld,%ld,%ld\n",
		       i, timing.detect_us, timing.recovery_us,
		       timing.retry_us, timing.total_us);
		fflush(stdout);
	}

	tcp_send_msg(sock, CMD_SHUTDOWN);
	close(sock);

	fprintf(stderr, "\nDone. %d trials failed out of %d total.\n",
		failed, num_trials * 3);
	return (failed > 0) ? 1 : 0;
}
