/*
 * RNR_RETRY_EXC recovery benchmark — client (225)
 *
 * Measures two recovery paths after RNR_RETRY_EXC_ERR:
 *   Path C: QP-only recovery (reset QP, re-exchange, reconnect)
 *   Path B: Full RDMA resource rebuild (destroy all, recreate)
 *
 * Usage: ./client [num_trials]
 *
 * Fault trigger: SEND to a QP with no posted recv buffer, rnr_retry=0.
 * The HCA sends RNR NAK, sender exhausts retries immediately -> CQE error.
 *
 * Output: CSV to stdout, progress to stderr.
 */

#include "../recovery_common.h"

#define DEFAULT_TRIALS  10
#define CQ_TIMEOUT_MS   10000   /* 10s, generous for RNR timeout */
#define MR_ACCESS       (IBV_ACCESS_LOCAL_WRITE | IBV_ACCESS_REMOTE_WRITE | \
			 IBV_ACCESS_REMOTE_READ)

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
/*  Wait for "READY" or "DONE" from server                            */
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
/*  Setup: trigger RNR_RETRY_EXC fault condition                      */
/* ------------------------------------------------------------------ */

static int setup_rnr_fault(int sock, struct rdma_res *res)
{
	/* Tell server to create resources without posting recv */
	if (tcp_send_msg(sock, CMD_SETUP_RNR) < 0)
		return -1;
	if (wait_server_ack(sock, CMD_READY) < 0)
		return -1;

	/* Client: create resources, exchange QP info, connect */
	if (setup_rdma(res, 1, MR_ACCESS, 0, 0, 14) < 0) {
		fprintf(stderr, "ERROR: setup_rdma failed\n");
		return -1;
	}

	/* Exchange QP info: client sends first */
	if (tcp_exchange_qp_info(sock, &res->local_info,
				 &res->remote_info, 0) < 0) {
		fprintf(stderr, "ERROR: QP info exchange failed\n");
		return -1;
	}

	/* Connect QP with rnr_retry=0 (immediate failure on RNR NAK) */
	if (connect_qp(res, 0, 0, 0, 14) < 0) {
		fprintf(stderr, "ERROR: connect_qp failed\n");
		return -1;
	}

	return 0;
}

/* ------------------------------------------------------------------ */
/*  Inject fault and measure detection time                           */
/* ------------------------------------------------------------------ */

static int inject_and_detect(struct rdma_res *res, struct ibv_wc *wc,
			     struct timespec *t_start, struct timespec *t_detect)
{
	/* Post SEND -> will RNR because server has no recv buffer */
	ts_now(t_start);
	if (post_send(res) != 0) {
		fprintf(stderr, "ERROR: post_send failed: %s\n",
			strerror(errno));
		return -1;
	}

	/* Poll CQ -> expect error CQE */
	int n = poll_cq_block(res->cq, wc, CQ_TIMEOUT_MS);
	ts_now(t_detect);

	if (n <= 0) {
		fprintf(stderr, "ERROR: poll_cq timed out or failed (n=%d)\n", n);
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
/*  Path C: QP-only recovery                                          */
/* ------------------------------------------------------------------ */

static int recover_qp_only(int sock, struct rdma_res *res,
			   struct timespec *t_start, struct timespec *t_done)
{
	ts_now(t_start);

	/* 1. Reset QP to RESET state */
	if (reset_qp_to_reset(res->qp) < 0)
		return -1;

	/* 2. Generate new PSN */
	res->local_info.psn = rand() & 0xFFFFFF;

	/* 3. Tell server to do QP recovery (server will post recv) */
	if (tcp_send_msg(sock, CMD_RECOVER_QP) < 0)
		return -1;

	/* 4. Exchange new QP info */
	if (tcp_exchange_qp_info(sock, &res->local_info,
				 &res->remote_info, 0) < 0)
		return -1;

	/* 5. Reconnect QP with normal retry params */
	if (connect_qp(res, 0, 7, 7, 14) < 0) {
		fprintf(stderr, "ERROR: connect_qp in QP recovery failed\n");
		return -1;
	}

	/* 6. Wait for server ready */
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

	/* 1. Destroy everything */
	cleanup_rdma(res);

	/* 2. Tell server to do full rebuild (server will post recv) */
	if (tcp_send_msg(sock, CMD_RECOVER_FULL) < 0)
		return -1;

	/* 3. Recreate all resources */
	if (setup_rdma(res, 1, MR_ACCESS, 7, 7, 14) < 0) {
		fprintf(stderr, "ERROR: setup_rdma in full rebuild failed\n");
		return -1;
	}

	/* 4. Exchange new QP info */
	if (tcp_exchange_qp_info(sock, &res->local_info,
				 &res->remote_info, 0) < 0)
		return -1;

	/* 5. Connect QP with normal retry params */
	if (connect_qp(res, 0, 7, 7, 14) < 0) {
		fprintf(stderr, "ERROR: connect_qp in full rebuild failed\n");
		return -1;
	}

	/* 6. Wait for server ready */
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
	struct timespec t_start, t_detect, t_counter_start, t_counter_done;
	struct timespec t_recover_start, t_recover_done;
	struct timespec t_retry_start, t_retry_done;
	struct counter_snapshot snap_before, snap_after;

	memset(&res, 0, sizeof(res));
	memset(timing, 0, sizeof(*timing));

	fprintf(stderr, "\n--- Trial %d, method=%s ---\n", trial, method);

	/* 1. Setup: create RNR fault condition */
	if (setup_rnr_fault(sock, &res) < 0)
		return -1;

	/* 2. Snapshot counters before fault */
	snapshot_local_counters(&snap_before);

	/* 3. Inject fault and detect */
	if (inject_and_detect(&res, &wc, &t_start, &t_detect) < 0) {
		cleanup_rdma(&res);
		return -1;
	}
	timing->detect_us = ts_diff_us(&t_start, &t_detect);

	/* 4. Snapshot counters after fault (measures read overhead) */
	ts_now(&t_counter_start);
	snapshot_local_counters(&snap_after);
	ts_now(&t_counter_done);
	timing->counter_us = ts_diff_us(&t_counter_start, &t_counter_done);

	/* Verify expected counter delta (stderr only) */
	for (int i = 0; i < snap_before.count && i < snap_after.count; i++) {
		long long delta = snap_after.values[i] - snap_before.values[i];
		if (delta != 0)
			fprintf(stderr, "  [counter] %s: +%lld\n",
				snap_before.names[i], delta);
	}

	/* 4. Recovery */
	if (strcmp(method, "C") == 0) {
		if (recover_qp_only(sock, &res,
				    &t_recover_start, &t_recover_done) < 0) {
			cleanup_rdma(&res);
			return -1;
		}
	} else { /* method == "B" */
		if (recover_full_rebuild(sock, &res,
					&t_recover_start, &t_recover_done) < 0) {
			cleanup_rdma(&res);
			return -1;
		}
	}
	timing->recovery_us = ts_diff_us(&t_recover_start, &t_recover_done);

	/* 5. Retry: SEND should succeed now */
	if (retry_and_verify(&res, &t_retry_start, &t_retry_done) < 0) {
		cleanup_rdma(&res);
		return -1;
	}
	timing->retry_us = ts_diff_us(&t_retry_start, &t_retry_done);
	timing->total_us = ts_diff_us(&t_start, &t_retry_done);

	fprintf(stderr, "  detect=%ld us, counter=%ld us, recovery=%ld us, "
		"retry=%ld us, total=%ld us\n",
		timing->detect_us, timing->counter_us,
		timing->recovery_us, timing->retry_us, timing->total_us);

	/* 6. Cleanup this trial */
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

	fprintf(stderr, "RNR_RETRY_EXC recovery benchmark: %d trials per method\n",
		num_trials);

	/* Connect TCP control channel (kept alive across all trials) */
	int sock = tcp_connect(RDMA_SERVER_IP, TCP_CTRL_PORT);
	if (sock < 0) {
		fprintf(stderr, "ERROR: cannot connect to server %s:%d\n",
			RDMA_SERVER_IP, TCP_CTRL_PORT);
		return 1;
	}
	fprintf(stderr, "Connected to server\n");

	/* CSV header */
	printf("# RNR_RETRY_EXC recovery benchmark\n");
	printf("# trial,method,detect_us,counter_us,recovery_us,retry_us,total_us\n");

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
		printf("%d,C,%ld,%ld,%ld,%ld,%ld\n",
		       i, timing.detect_us, timing.counter_us,
		       timing.recovery_us, timing.retry_us, timing.total_us);
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
		printf("%d,B,%ld,%ld,%ld,%ld,%ld\n",
		       i, timing.detect_us, timing.counter_us,
		       timing.recovery_us, timing.retry_us, timing.total_us);
		fflush(stdout);
	}

	/* Shutdown server */
	tcp_send_msg(sock, CMD_SHUTDOWN);
	close(sock);

	fprintf(stderr, "\nDone. %d trials failed out of %d total.\n",
		failed, num_trials * 2);
	return (failed > 0) ? 1 : 0;
}
