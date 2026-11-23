/*
 * Early detection experiment suite — client (225)
 *
 * Three test modes for RETRY_EXC_ERR early detection:
 *
 *   Mode 1: force_err — Verify ibv_modify_qp(ERR) aborts firmware retry
 *           and generates WR_FLUSH_ERR CQE.
 *
 *   Mode 2: timeline — Record when each HW counter first increments
 *           during natural retry exhaustion (3.7s).
 *
 *   Mode 3: recover — Counter-based early detection + QP-only recovery.
 *           Background thread polls a configurable counter, forces ERR
 *           on first increment, main thread recovers.
 *
 * All modes reuse RETRY_EXC_ERR server on 224.
 *
 * Usage:
 *   ./client force_err [delay_ms ...] — default: 100 200 500
 *   ./client timeline  [num_trials]   — default: 5
 *   ./client recover   [counter_name] [poll_interval_ms] [num_trials]
 *                                     — default: roce_adp_retrans 10 10
 */

#include "../../recovery_common.h"
#include <pthread.h>

#define CQ_TIMEOUT_MS      5000
#define MR_ACCESS          (IBV_ACCESS_LOCAL_WRITE | IBV_ACCESS_REMOTE_WRITE | \
			    IBV_ACCESS_REMOTE_READ)

#define CMD_SETUP_RETRY    "SETUP_RETRY"
#define CMD_INJECT_FAULT   "INJECT_FAULT"

#define FORCE_ERR_TRIALS   5
#define MAX_MONITOR        8
#define MAX_EVENTS         256

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

static int wait_server_ack(int sock, const char *expected)
{
	char buf[64];
	if (tcp_recv_msg(sock, buf, sizeof(buf)) < 0)
		return -1;
	if (strcmp(buf, expected) != 0) {
		fprintf(stderr, "ERROR: expected '%s', got '%s'\n",
			expected, buf);
		return -1;
	}
	return 0;
}

/* ------------------------------------------------------------------ */
/*  Common: setup RETRY_EXC_ERR fault                                 */
/* ------------------------------------------------------------------ */

static int setup_retry_fault(int sock, struct rdma_res *res)
{
	if (tcp_send_msg(sock, CMD_SETUP_RETRY) < 0)
		return -1;
	if (wait_server_ack(sock, CMD_READY) < 0)
		return -1;

	if (setup_rdma(res, 1, MR_ACCESS, 7, 7, 14) < 0)
		return -1;

	if (tcp_exchange_qp_info(sock, &res->local_info,
				 &res->remote_info, 0) < 0)
		return -1;

	if (connect_qp(res, 0, 7, 0, 14) < 0)
		return -1;

	if (tcp_send_msg(sock, CMD_INJECT_FAULT) < 0)
		return -1;
	if (wait_server_ack(sock, CMD_READY) < 0)
		return -1;

	return 0;
}

static void cleanup_trial(int sock, struct rdma_res *res)
{
	tcp_send_msg(sock, CMD_CLEANUP);
	wait_server_ack(sock, CMD_DONE);
	cleanup_rdma(res);
}

/* ================================================================== */
/*  Mode 1: force_err                                                 */
/* ================================================================== */

static int run_force_err(int sock, int delay_ms, int trial)
{
	struct rdma_res res;
	struct timespec t_post, t_force, t_cqe;

	memset(&res, 0, sizeof(res));
	fprintf(stderr, "\n--- force_err: delay=%dms, trial=%d ---\n",
		delay_ms, trial);

	if (setup_retry_fault(sock, &res) < 0)
		return -1;

	ts_now(&t_post);
	if (post_send(&res) != 0) {
		cleanup_rdma(&res);
		return -1;
	}

	usleep(delay_ms * 1000);

	ts_now(&t_force);
	struct ibv_qp_attr attr = { .qp_state = IBV_QPS_ERR };
	int rc = ibv_modify_qp(res.qp, &attr, IBV_QP_STATE);
	if (rc != 0) {
		fprintf(stderr, "ERROR: ibv_modify_qp(ERR) failed\n");
		cleanup_rdma(&res);
		return -1;
	}

	struct ibv_wc wc;
	int n = poll_cq_block(res.cq, &wc, CQ_TIMEOUT_MS);
	ts_now(&t_cqe);

	long post_to_force_us = ts_diff_us(&t_post, &t_force);
	long force_to_cqe_us = (n > 0) ? ts_diff_us(&t_force, &t_cqe) : -1;

	if (n > 0) {
		printf("%d,%d,%d,%s,0x%x,%ld,%ld\n",
		       delay_ms, trial, wc.status,
		       ibv_wc_status_str(wc.status), wc.vendor_err,
		       post_to_force_us, force_to_cqe_us);
	} else {
		printf("%d,%d,-1,NO_CQE,-,%ld,-1\n",
		       delay_ms, trial, post_to_force_us);
	}
	fflush(stdout);

	cleanup_trial(sock, &res);
	return 0;
}

static int mode_force_err(int sock, int argc, char *argv[])
{
	int delays[10] = {100, 200, 500};  /* sized to the num_delays clamp below */
	int num_delays = 3;

	if (argc > 2) {
		num_delays = argc - 2;
		if (num_delays > 10) num_delays = 10;
		for (int i = 0; i < num_delays; i++)
			delays[i] = atoi(argv[i + 2]);
	}

	printf("# force_err verification test\n");
	printf("# delay_ms,trial,cqe_status,cqe_status_str,vendor_err,"
	       "post_to_force_us,force_to_cqe_us\n");

	int failed = 0;
	for (int d = 0; d < num_delays; d++)
		for (int t = 0; t < FORCE_ERR_TRIALS; t++)
			if (run_force_err(sock, delays[d], t) < 0)
				failed++;
	return failed;
}

/* ================================================================== */
/*  Mode 2: timeline                                                  */
/* ================================================================== */

static const char *timeline_counters[] = {
	"roce_adp_retrans",
	"roce_adp_retrans_to",
	"local_ack_timeout_err",
	"out_of_sequence",
	"req_transport_retries_exceeded",
	"req_cqe_error",
	NULL
};

struct counter_event {
	struct timespec ts;
	int counter_idx;
	long long old_val;
	long long new_val;
};

static int run_timeline(int sock, int trial)
{
	struct rdma_res res;
	struct ibv_wc wc;
	struct timespec t_post, t_cqe;

	memset(&res, 0, sizeof(res));
	fprintf(stderr, "\n--- timeline: trial=%d ---\n", trial);

	if (setup_retry_fault(sock, &res) < 0)
		return -1;

	int num_counters = 0;
	long long baseline[MAX_MONITOR], current[MAX_MONITOR];

	for (int i = 0; timeline_counters[i]; i++) {
		if (read_hw_counter(
				       timeline_counters[i], &baseline[i]) < 0)
			baseline[i] = -1;
		current[i] = baseline[i];
		num_counters++;
	}

	ts_now(&t_post);
	if (post_send(&res) != 0) {
		cleanup_rdma(&res);
		return -1;
	}

	struct counter_event events[MAX_EVENTS];
	int num_events = 0;

	while (1) {
		int n = ibv_poll_cq(res.cq, 1, &wc);
		if (n > 0) {
			ts_now(&t_cqe);
			break;
		}

		for (int i = 0; i < num_counters; i++) {
			if (baseline[i] < 0)
				continue;
			long long val;
			if (read_hw_counter(
					       timeline_counters[i], &val) < 0)
				continue;
			if (val != current[i] && num_events < MAX_EVENTS) {
				struct counter_event *ev = &events[num_events++];
				ts_now(&ev->ts);
				ev->counter_idx = i;
				ev->old_val = current[i];
				ev->new_val = val;
				current[i] = val;
			}
		}
	}

	for (int i = 0; i < num_events; i++) {
		long offset_us = ts_diff_us(&t_post, &events[i].ts);
		printf("%d,%s,%ld,%lld,%lld,%lld\n",
		       trial, timeline_counters[events[i].counter_idx],
		       offset_us, events[i].old_val, events[i].new_val,
		       events[i].new_val - events[i].old_val);
	}
	printf("%d,CQE_RECEIVED,%ld,%d,0x%x,0\n",
	       trial, ts_diff_us(&t_post, &t_cqe), wc.status, wc.vendor_err);
	fflush(stdout);

	cleanup_trial(sock, &res);
	return 0;
}

static int mode_timeline(int sock, int argc, char *argv[])
{
	int num_trials = 5;
	if (argc > 2) num_trials = atoi(argv[2]);
	if (num_trials <= 0) num_trials = 5;

	printf("# Counter timeline during RETRY_EXC_ERR\n");
	printf("# trial,counter_name,offset_us,old_val,new_val,delta\n");

	int failed = 0;
	for (int i = 0; i < num_trials; i++)
		if (run_timeline(sock, i) < 0)
			failed++;
	return failed;
}

/* ================================================================== */
/*  Mode 3: recover — counter-based early detection + recovery        */
/* ================================================================== */

struct monitor_ctx {
	struct ibv_qp *qp;
	const char *counter_name;
	int poll_interval_ms;

	volatile int started;
	volatile int detected;
	volatile int cancel;

	struct timespec t_detect;
	struct timespec t_force;
	struct timespec t_force_done;

	long long counter_baseline;
	long long counter_detected;
	int polls_before_detect;

	struct timespec t_last_no_change;
};

static void *monitor_thread_fn(void *arg)
{
	struct monitor_ctx *ctx = arg;
	long long val;
	int polls = 0;

	if (read_hw_counter( ctx->counter_name,
			       &ctx->counter_baseline) < 0) {
		fprintf(stderr, "ERROR: monitor: cannot read %s\n",
			ctx->counter_name);
		/* Signal started so main's spin-wait terminates; detected stays
		 * 0 so the trial fails gracefully instead of hanging forever. */
		ctx->started = 1;
		return NULL;
	}

	ctx->started = 1;

	while (!ctx->cancel) {
		usleep(ctx->poll_interval_ms * 1000);
		polls++;

		if (read_hw_counter( ctx->counter_name,
				       &val) < 0)
			continue;

		if (val > ctx->counter_baseline) {
			ts_now(&ctx->t_detect);
			ctx->counter_detected = val;
			ctx->polls_before_detect = polls;

			ts_now(&ctx->t_force);
			struct ibv_qp_attr attr = {
				.qp_state = IBV_QPS_ERR
			};
			ibv_modify_qp(ctx->qp, &attr, IBV_QP_STATE);
			ts_now(&ctx->t_force_done);

			ctx->detected = 1;
			return NULL;
		}

		ts_now(&ctx->t_last_no_change);
	}
	return NULL;
}

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
	if (connect_qp(res, 0, 7, 7, 14) < 0)
		return -1;
	if (wait_server_ack(sock, CMD_READY) < 0)
		return -1;

	ts_now(t_done);
	return 0;
}

static int run_recover(int sock, const char *counter_name,
		       int poll_ms, int trial)
{
	struct rdma_res res;
	struct ibv_wc wc;
	struct timespec t_post, t_cqe;
	struct timespec t_recover_start, t_recover_done;
	struct timespec t_retry_start, t_retry_done;

	memset(&res, 0, sizeof(res));
	fprintf(stderr, "\n--- recover: counter=%s, poll=%dms, trial=%d ---\n",
		counter_name, poll_ms, trial);

	if (setup_retry_fault(sock, &res) < 0)
		return -1;

	struct monitor_ctx mon;
	memset(&mon, 0, sizeof(mon));
	mon.qp = res.qp;
	mon.counter_name = counter_name;
	mon.poll_interval_ms = poll_ms;

	pthread_t tid;
	if (pthread_create(&tid, NULL, monitor_thread_fn, &mon) != 0) {
		cleanup_rdma(&res);
		return -1;
	}

	while (!mon.started)
		usleep(100);

	ts_now(&t_post);
	if (post_send(&res) != 0) {
		mon.cancel = 1;
		pthread_join(tid, NULL);
		cleanup_rdma(&res);
		return -1;
	}

	int n = poll_cq_block(res.cq, &wc, 10000);
	ts_now(&t_cqe);

	mon.cancel = 1;
	pthread_join(tid, NULL);

	if (n <= 0 || !mon.detected) {
		fprintf(stderr, "ERROR: detection failed (n=%d, detected=%d)\n",
			n, mon.detected);
		cleanup_rdma(&res);
		return -1;
	}

	fprintf(stderr, "  [detect] status=%d (%s) vendor_err=0x%x\n",
		wc.status, ibv_wc_status_str(wc.status), wc.vendor_err);

	if (recover_qp_only(sock, &res,
			    &t_recover_start, &t_recover_done) < 0) {
		cleanup_rdma(&res);
		return -1;
	}

	/* Retry */
	ts_now(&t_retry_start);
	if (post_send(&res) != 0) {
		cleanup_rdma(&res);
		return -1;
	}
	n = poll_cq_block(res.cq, &wc, CQ_TIMEOUT_MS);
	ts_now(&t_retry_done);

	if (n <= 0 || wc.status != IBV_WC_SUCCESS) {
		fprintf(stderr, "ERROR: retry failed\n");
		cleanup_rdma(&res);
		return -1;
	}
	fprintf(stderr, "  [retry] success\n");

	long detect_us       = ts_diff_us(&t_post, &mon.t_detect);
	long force_us        = ts_diff_us(&mon.t_force, &mon.t_force_done);
	long force_to_cqe_us = ts_diff_us(&mon.t_force, &t_cqe);
	long recovery_us     = ts_diff_us(&t_recover_start, &t_recover_done);
	long retry_us        = ts_diff_us(&t_retry_start, &t_retry_done);
	long total_us        = ts_diff_us(&t_post, &t_retry_done);
	long polling_lag_us  = 0;
	if (mon.t_last_no_change.tv_sec > 0)
		polling_lag_us = ts_diff_us(&mon.t_last_no_change, &mon.t_detect);
	long long counter_delta = mon.counter_detected - mon.counter_baseline;

	printf("%s,%d,%d,%ld,%ld,%d,%lld,%ld,%ld,%ld,%ld,%ld,%d,0x%x\n",
	       counter_name, poll_ms, trial,
	       detect_us, polling_lag_us,
	       mon.polls_before_detect, counter_delta,
	       force_us, force_to_cqe_us,
	       recovery_us, retry_us, total_us,
	       wc.status, wc.vendor_err);
	fflush(stdout);

	cleanup_trial(sock, &res);
	return 0;
}

static int mode_recover(int sock, int argc, char *argv[])
{
	const char *counter_name = "roce_adp_retrans";
	int poll_ms = 10;
	int num_trials = 10;

	if (argc > 2) counter_name = argv[2];
	if (argc > 3) poll_ms = atoi(argv[3]);
	if (argc > 4) num_trials = atoi(argv[4]);
	if (poll_ms <= 0) poll_ms = 10;
	if (num_trials <= 0) num_trials = 10;

	printf("# Early detection recovery (counter=%s, poll=%dms)\n",
	       counter_name, poll_ms);
	printf("# counter,poll_ms,trial,detect_us,polling_lag_us,"
	       "polls_before_detect,counter_delta,"
	       "force_us,force_to_cqe_us,"
	       "recovery_us,retry_us,total_us,cqe_status,vendor_err\n");

	int failed = 0;
	for (int i = 0; i < num_trials; i++)
		if (run_recover(sock, counter_name, poll_ms, i) < 0)
			failed++;
	return failed;
}

/* ================================================================== */
/*  main                                                              */
/* ================================================================== */

int main(int argc, char *argv[])
{
	if (argc < 2) {
		fprintf(stderr,
			"Usage:\n"
			"  %s force_err [delay_ms ...]\n"
			"  %s timeline  [num_trials]\n"
			"  %s recover   [counter_name] [poll_ms] [num_trials]\n",
			argv[0], argv[0], argv[0]);
		return 1;
	}

	srand(time(NULL));

	/* Resolve active IB device name so counter sysfs paths are correct after
	 * a NIC rename (225: mlx5_0 -> rocep1s0f0). */
	resolve_ib_dev_name();
	fprintf(stderr, "[early_detect] counter device: %s\n", g_ib_dev_name);

	int sock = tcp_connect(RDMA_SERVER_IP, TCP_CTRL_PORT);
	if (sock < 0) {
		fprintf(stderr, "ERROR: cannot connect to server\n");
		return 1;
	}

	int failed = 0;
	if (strcmp(argv[1], "force_err") == 0)
		failed = mode_force_err(sock, argc, argv);
	else if (strcmp(argv[1], "timeline") == 0)
		failed = mode_timeline(sock, argc, argv);
	else if (strcmp(argv[1], "recover") == 0)
		failed = mode_recover(sock, argc, argv);
	else {
		fprintf(stderr, "ERROR: unknown mode '%s'\n", argv[1]);
		failed = 1;
	}

	tcp_send_msg(sock, CMD_SHUTDOWN);
	close(sock);

	fprintf(stderr, "\nDone. %d failures.\n", failed);
	return (failed > 0) ? 1 : 0;
}
