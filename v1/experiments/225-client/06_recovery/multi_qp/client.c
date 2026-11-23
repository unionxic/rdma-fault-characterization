/*
 * Multi-QP isolation & concurrent fault experiment -- client (225)
 *
 * Mode 1 (isolation): Fault on QP_B while QP_A runs continuous RDMA WRITE.
 *   Measures whether QP_B fault+recovery impacts QP_A throughput.
 *   Compares QP-only recovery (QP_B only) vs full rebuild (all resources).
 *
 * Mode 2 (concurrent): Inject different errors on QP_A (REM_ACCESS_ERR)
 *   and QP_B (RETRY_EXC_ERR) simultaneously. Verifies per-QP CQE
 *   error identification and counter-level ambiguity.
 *
 * Usage: ./client isolation [trials]
 *        ./client concurrent [trials]
 */

#include "../recovery_common.h"
#include <pthread.h>

#define DEFAULT_TRIALS    10
#define CQ_TIMEOUT_MS     10000
#define MR_ACCESS         (IBV_ACCESS_LOCAL_WRITE | IBV_ACCESS_REMOTE_WRITE | \
                           IBV_ACCESS_REMOTE_READ)

#define WARMUP_OPS        100
#define WINDOW_MS         10
#define BASELINE_MS       100
#define POST_RECOVERY_MS  100
#define SIGNAL_INTERVAL   8
#define EARLY_DETECT_MS   100
#define MAX_WINDOWS       256

/* Multi-QP CQ depth: enough for signaled ops in flight */
#define MULTI_CQ_DEPTH    64
#define MULTI_MAX_WR      64

/* TCP commands */
#define CMD_SETUP_MULTI       "SETUP_MULTI"
#define CMD_INJECT_FAULT_B    "INJECT_FAULT_B"
#define CMD_RECOVER_QP_B      "RECOVER_QP_B"
#define CMD_SETUP_CONCURRENT  "SETUP_CONCURRENT"
#define CMD_INJECT_CONCURRENT "INJECT_CONCURRENT"
#define CMD_RECOVER_CONCURRENT "RECOVER_CONCURRENT"

/* ------------------------------------------------------------------ */
/*  Timing helpers                                                    */
/* ------------------------------------------------------------------ */

static void ts_now(struct timespec *ts)
{
	clock_gettime(CLOCK_MONOTONIC, ts);
}

static long ts_diff_us(struct timespec *a, struct timespec *b)
{
	return (long)((b->tv_sec - a->tv_sec) * 1000000L +
		      (b->tv_nsec - a->tv_nsec) / 1000L);
}

static long ts_diff_ms(struct timespec *a, struct timespec *b)
{
	return ts_diff_us(a, b) / 1000L;
}

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
/*  Multi-QP resource bundle                                          */
/* ------------------------------------------------------------------ */

struct multi_qp_res {
	struct ibv_context *ctx;
	struct ibv_pd      *pd;
	struct ibv_mr      *mr;
	void               *buf;
	int                 gid_index;
	union ibv_gid       gid;

	struct ibv_cq      *cq[2];
	struct ibv_qp      *qp[2];
	struct qp_info      local_info[2];
	struct qp_info      remote_info[2];
};

static int setup_multi_resources(struct multi_qp_res *m)
{
	memset(m, 0, sizeof(*m));

	m->ctx = open_ib_device(IB_DEV_NAME);
	if (!m->ctx) {
		fprintf(stderr, "ERROR: open_ib_device failed\n");
		return -1;
	}

	m->pd = ibv_alloc_pd(m->ctx);
	if (!m->pd) {
		fprintf(stderr, "ERROR: ibv_alloc_pd failed\n");
		return -1;
	}

	m->buf = calloc(1, BUF_SIZE);
	if (!m->buf)
		return -1;

	m->mr = ibv_reg_mr(m->pd, m->buf, MR_SIZE, MR_ACCESS);
	if (!m->mr) {
		fprintf(stderr, "ERROR: ibv_reg_mr failed: %s\n", strerror(errno));
		return -1;
	}

	/* Find RoCEv2 GID */
	m->gid_index = -1;
	for (int i = 0; i < 16; i++) {
		union ibv_gid g;
		if (ibv_query_gid(m->ctx, IB_PORT, i, &g))
			break;
		if (g.raw[0] == 0 && g.raw[10] == 0xff && g.raw[11] == 0xff &&
		    (g.raw[12] != 0 || g.raw[13] != 0)) {
			m->gid_index = i;
			m->gid = g;
			break;
		}
	}
	if (m->gid_index < 0) {
		fprintf(stderr, "ERROR: no valid RoCEv2 GID\n");
		return -1;
	}

	/* Create 2 CQs and 2 QPs */
	for (int i = 0; i < 2; i++) {
		m->cq[i] = ibv_create_cq(m->ctx, MULTI_CQ_DEPTH, NULL, NULL, 0);
		if (!m->cq[i]) {
			fprintf(stderr, "ERROR: ibv_create_cq[%d] failed\n", i);
			return -1;
		}

		struct ibv_qp_init_attr qp_attr = {
			.send_cq = m->cq[i],
			.recv_cq = m->cq[i],
			.cap = {
				.max_send_wr  = MULTI_MAX_WR,
				.max_recv_wr  = MAX_WR,
				.max_send_sge = MAX_SGE,
				.max_recv_sge = MAX_SGE,
			},
			.qp_type = IBV_QPT_RC,
		};
		m->qp[i] = ibv_create_qp(m->pd, &qp_attr);
		if (!m->qp[i]) {
			fprintf(stderr, "ERROR: ibv_create_qp[%d] failed\n", i);
			return -1;
		}

		m->local_info[i].qpn  = m->qp[i]->qp_num;
		m->local_info[i].psn  = rand() & 0xFFFFFF;
		m->local_info[i].rkey = m->mr->rkey;
		m->local_info[i].raddr = (uint64_t)m->buf;
		m->local_info[i].gid  = m->gid;
	}

	fprintf(stderr, "[setup] QP_A qpn=%u, QP_B qpn=%u, gid_index=%d\n",
		m->qp[0]->qp_num, m->qp[1]->qp_num, m->gid_index);
	return 0;
}

static int connect_multi_qp(struct multi_qp_res *m, int idx,
			     int retry_cnt, int rnr_retry, int timeout)
{
	if (modify_qp_to_init(m->qp[idx], 1)) {
		fprintf(stderr, "ERROR: init QP[%d] failed: %s\n",
			idx, strerror(errno));
		return -1;
	}
	if (modify_qp_to_rtr(m->qp[idx], &m->remote_info[idx], m->gid_index)) {
		fprintf(stderr, "ERROR: rtr QP[%d] failed: %s\n",
			idx, strerror(errno));
		return -1;
	}
	if (modify_qp_to_rts(m->qp[idx], m->local_info[idx].psn,
			      retry_cnt, rnr_retry, timeout)) {
		fprintf(stderr, "ERROR: rts QP[%d] failed: %s\n",
			idx, strerror(errno));
		return -1;
	}
	return 0;
}

static void cleanup_multi(struct multi_qp_res *m)
{
	for (int i = 0; i < 2; i++) {
		if (m->qp[i]) ibv_destroy_qp(m->qp[i]);
		if (m->cq[i]) ibv_destroy_cq(m->cq[i]);
	}
	if (m->mr)  ibv_dereg_mr(m->mr);
	if (m->pd)  ibv_dealloc_pd(m->pd);
	if (m->ctx) ibv_close_device(m->ctx);
	free(m->buf);
	memset(m, 0, sizeof(*m));
}

/* Post RDMA WRITE on a specific QP */
static int post_write_on(struct multi_qp_res *m, int idx, int signaled, uint64_t wr_id)
{
	struct ibv_sge sge = {
		.addr   = (uint64_t)m->buf,
		.length = 64,
		.lkey   = m->mr->lkey,
	};
	struct ibv_send_wr wr = {
		.wr_id      = wr_id,
		.sg_list    = &sge,
		.num_sge    = 1,
		.opcode     = IBV_WR_RDMA_WRITE,
		.send_flags = signaled ? IBV_SEND_SIGNALED : 0,
		.wr.rdma = {
			.remote_addr = m->remote_info[idx].raddr,
			.rkey        = m->remote_info[idx].rkey,
		},
	};
	struct ibv_send_wr *bad;
	return ibv_post_send(m->qp[idx], &wr, &bad);
}

/* Warmup: post N signaled WRITEs and poll completions */
static int warmup_qp(struct multi_qp_res *m, int idx, int count)
{
	struct ibv_wc wc;
	for (int i = 0; i < count; i++) {
		if (post_write_on(m, idx, 1, 100 + i) != 0) {
			fprintf(stderr, "ERROR: warmup post QP[%d] iter %d: %s\n",
				idx, i, strerror(errno));
			return -1;
		}
		int n = poll_cq_block(m->cq[idx], &wc, 5000);
		if (n <= 0 || wc.status != IBV_WC_SUCCESS) {
			fprintf(stderr, "ERROR: warmup poll QP[%d] iter %d: n=%d status=%d\n",
				idx, i, n, n > 0 ? wc.status : -1);
			return -1;
		}
	}
	return 0;
}

/* ------------------------------------------------------------------ */
/*  Throughput measurement thread for QP_A                            */
/* ------------------------------------------------------------------ */

struct window_record {
	long   start_ms;
	long   end_ms;
	long   ops;
	char   qp_b_state[16]; /* healthy, fault, recovering, recovered */
	char   phase[24];
};

struct throughput_ctx {
	struct multi_qp_res *m;
	volatile int         stop;
	volatile int         error;

	struct window_record windows[MAX_WINDOWS];
	int                  num_windows;
	struct timespec      t_origin;

	/* Caller sets these to mark QP_B phases */
	volatile int         qp_b_phase; /* 0=healthy, 1=fault, 2=recovering, 3=recovered */
};

static const char *phase_label(int phase, long win_start_ms)
{
	(void)win_start_ms;
	switch (phase) {
	case 0: return "baseline";
	case 1: return "during_fault";
	case 2: return "during_recovery";
	case 3: return "after_recovery";
	default: return "unknown";
	}
}

static const char *state_label(int phase)
{
	switch (phase) {
	case 0: return "healthy";
	case 1: return "fault";
	case 2: return "recovering";
	case 3: return "recovered";
	default: return "unknown";
	}
}

static void *throughput_thread(void *arg)
{
	struct throughput_ctx *tc = (struct throughput_ctx *)arg;
	struct multi_qp_res *m = tc->m;
	struct ibv_wc wc;
	long ops = 0;
	long total_ops = 0;
	int win_idx = 0;
	struct timespec win_start;

	ts_now(&tc->t_origin);
	ts_now(&win_start);

	while (!tc->stop && win_idx < MAX_WINDOWS) {
		if (post_write_on(m, 0, 1, total_ops) != 0) {
			fprintf(stderr, "[throughput] post_send failed: %s\n",
				strerror(errno));
			tc->error = 1;
			return NULL;
		}

		while (!tc->stop) {
			int n = ibv_poll_cq(m->cq[0], 1, &wc);
			if (n > 0)
				break;
			if (n < 0) {
				tc->error = 1;
				return NULL;
			}
		}
		if (tc->stop)
			break;

		if (wc.status != IBV_WC_SUCCESS) {
			fprintf(stderr, "[throughput] QP_A error: status=%d (%s)\n",
				wc.status, ibv_wc_status_str(wc.status));
			tc->error = 1;
			return NULL;
		}
		ops++;
		total_ops++;

		struct timespec now;
		ts_now(&now);
		if (ts_diff_ms(&win_start, &now) >= WINDOW_MS) {
			int ph = tc->qp_b_phase;
			struct window_record *w = &tc->windows[win_idx];
			w->start_ms = ts_diff_ms(&tc->t_origin, &win_start);
			w->end_ms   = ts_diff_ms(&tc->t_origin, &now);
			w->ops      = ops;
			strncpy(w->qp_b_state, state_label(ph), sizeof(w->qp_b_state) - 1);
			strncpy(w->phase, phase_label(ph, w->start_ms), sizeof(w->phase) - 1);
			win_idx++;
			ops = 0;
			win_start = now;
		}
	}

	tc->num_windows = win_idx;
	return NULL;
}

/* ------------------------------------------------------------------ */
/*  Reset and reconnect a single QP                                   */
/* ------------------------------------------------------------------ */

static int reset_and_reconnect_qp(int sock, struct multi_qp_res *m, int idx)
{
	if (reset_qp_to_reset(m->qp[idx]) < 0)
		return -1;
	drain_cq(m->cq[idx]);

	m->local_info[idx].psn = rand() & 0xFFFFFF;

	if (tcp_exchange_qp_info(sock, &m->local_info[idx],
				  &m->remote_info[idx], 0) < 0)
		return -1;

	if (connect_multi_qp(m, idx, 7, 7, 14) < 0)
		return -1;

	return 0;
}

/* ------------------------------------------------------------------ */
/*  Mode 1: Isolation test                                            */
/* ------------------------------------------------------------------ */

static int run_isolation(int sock, int num_trials)
{
	printf("# mode=isolation\n");
	printf("# trial,method,window_idx,window_start_ms,window_end_ms,"
	       "qp_a_ops,qp_b_state,phase\n");

	int failed = 0;

	for (int method = 0; method < 2; method++) {
		const char *method_name = (method == 0) ? "qp_only" : "full_rebuild";
		fprintf(stderr, "\n========== Isolation: %s ==========\n", method_name);

		for (int trial = 0; trial < num_trials; trial++) {
			struct multi_qp_res m;
			struct timespec t0, t1, t2, t3;
			long detect_us = 0, recovery_us = 0;
			int win_offset = 0;
			/* first-run window aggregates carried past the tc memset()
			 * on the full_rebuild path (otherwise the summary loop only
			 * sees the second run and reports baseline=0, fault=0). */
			long carry_baseline_ops = 0, carry_fault_ops = 0;
			int  carry_baseline_n = 0,   carry_fault_n = 0;

			/* zero so an early goto trial_fail (before setup) can safely
			 * run cleanup_multi() on NULL handles. */
			memset(&m, 0, sizeof(m));

			fprintf(stderr, "\n--- Trial %d, method=%s ---\n",
				trial, method_name);

			/* 1. Setup */
			if (tcp_send_msg(sock, CMD_SETUP_MULTI) < 0)
				goto trial_fail;
			if (wait_server_ack(sock, CMD_READY) < 0)
				goto trial_fail;

			if (setup_multi_resources(&m) < 0)
				goto trial_fail;

			/* Exchange QP info: QP_A first, QP_B second */
			for (int i = 0; i < 2; i++) {
				if (tcp_exchange_qp_info(sock, &m.local_info[i],
							  &m.remote_info[i], 0) < 0)
					goto trial_cleanup;
			}

			/* Connect both QPs */
			for (int i = 0; i < 2; i++) {
				if (connect_multi_qp(&m, i, 7, 7, 14) < 0)
					goto trial_cleanup;
			}

			/* Warmup */
			for (int i = 0; i < 2; i++) {
				if (warmup_qp(&m, i, WARMUP_OPS) < 0)
					goto trial_cleanup;
			}
			fprintf(stderr, "  warmup done\n");

			/* 2. Start QP_A throughput thread */
			struct throughput_ctx tc;
			memset(&tc, 0, sizeof(tc));
			tc.m = &m;
			tc.qp_b_phase = 0;

			pthread_t tid;
			if (pthread_create(&tid, NULL, throughput_thread, &tc) != 0) {
				fprintf(stderr, "ERROR: pthread_create failed\n");
				goto trial_cleanup;
			}

			/* 3. Baseline phase: let QP_A run for BASELINE_MS */
			usleep(BASELINE_MS * 1000);
			if (tc.error)
				goto trial_join;

			/* 4. Inject fault on QP_B */
			if (tcp_send_msg(sock, CMD_INJECT_FAULT_B) < 0)
				goto trial_join;
			if (wait_server_ack(sock, CMD_READY) < 0)
				goto trial_join;

			tc.qp_b_phase = 1;
			ts_now(&t0);

			/* Post a WRITE on QP_B (will eventually fail) */
			post_write_on(&m, 1, 1, 999);

			/* Early detection: wait EARLY_DETECT_MS then force QP_B to ERR */
			usleep(EARLY_DETECT_MS * 1000);

			struct ibv_qp_attr err_attr = { .qp_state = IBV_QPS_ERR };
			ibv_modify_qp(m.qp[1], &err_attr, IBV_QP_STATE);

			/* Poll QP_B CQE */
			struct ibv_wc wc_b;
			int n = poll_cq_block(m.cq[1], &wc_b, 5000);
			ts_now(&t1);
			detect_us = ts_diff_us(&t0, &t1);

			if (n <= 0) {
				fprintf(stderr, "ERROR: QP_B poll timed out\n");
				goto trial_join;
			}
			fprintf(stderr, "  [QP_B detect] status=%d (%s) vendor_err=0x%x "
				"detect=%ld us\n",
				wc_b.status, ibv_wc_status_str(wc_b.status),
				wc_b.vendor_err, detect_us);

			/* 5. Recovery */
			tc.qp_b_phase = 2;
			ts_now(&t2);

			if (method == 0) {
				/* QP-only: recover QP_B only, QP_A keeps running */
				if (tcp_send_msg(sock, CMD_RECOVER_QP_B) < 0)
					goto trial_join;
				if (reset_and_reconnect_qp(sock, &m, 1) < 0)
					goto trial_join;
				if (wait_server_ack(sock, CMD_READY) < 0)
					goto trial_join;
			} else {
				/* Full rebuild: must stop QP_A thread first —
				   this downtime IS the point of the comparison */
				tc.stop = 1;
				pthread_join(tid, NULL);

				/* Output first-run windows before they're cleared */
				for (int w = 0; w < tc.num_windows; w++) {
					printf("%d,%s,%d,%ld,%ld,%ld,%s,%s\n",
					       trial, method_name, w,
					       tc.windows[w].start_ms,
					       tc.windows[w].end_ms,
					       tc.windows[w].ops,
					       tc.windows[w].qp_b_state,
					       tc.windows[w].phase);
					if (strcmp(tc.windows[w].phase, "baseline") == 0) {
						carry_baseline_ops += tc.windows[w].ops;
						carry_baseline_n++;
					} else if (strcmp(tc.windows[w].phase, "during_fault") == 0 ||
						   strcmp(tc.windows[w].phase, "during_recovery") == 0) {
						carry_fault_ops += tc.windows[w].ops;
						carry_fault_n++;
					}
				}
				win_offset = tc.num_windows;

				/* Full cleanup + fresh setup (CLEANUP then SETUP_MULTI) */
				if (tcp_send_msg(sock, CMD_CLEANUP) < 0)
					goto trial_fail;
				if (wait_server_ack(sock, CMD_DONE) < 0)
					goto trial_fail;
				cleanup_multi(&m);

				if (tcp_send_msg(sock, CMD_SETUP_MULTI) < 0)
					goto trial_fail;
				if (wait_server_ack(sock, CMD_READY) < 0)
					goto trial_fail;

				if (setup_multi_resources(&m) < 0)
					goto trial_fail;
				for (int i = 0; i < 2; i++) {
					if (tcp_exchange_qp_info(sock, &m.local_info[i],
								  &m.remote_info[i], 0) < 0)
						goto trial_cleanup;
				}
				for (int i = 0; i < 2; i++) {
					if (connect_multi_qp(&m, i, 7, 7, 14) < 0)
						goto trial_cleanup;
				}

				/* Restart throughput thread for post-rebuild measurement */
				memset(&tc, 0, sizeof(tc));
				tc.m = &m;
				tc.qp_b_phase = 3;
				if (pthread_create(&tid, NULL, throughput_thread, &tc) != 0)
					goto trial_cleanup;
			}

			ts_now(&t3);
			recovery_us = ts_diff_us(&t2, &t3);

			/* Verify QP_B works again */
			if (post_write_on(&m, 1, 1, 1000) != 0) {
				fprintf(stderr, "ERROR: QP_B retry post failed\n");
				goto trial_join;
			}
			struct ibv_wc wc_verify;
			n = poll_cq_block(m.cq[1], &wc_verify, 5000);
			if (n <= 0 || wc_verify.status != IBV_WC_SUCCESS) {
				fprintf(stderr, "ERROR: QP_B retry failed: n=%d status=%d\n",
					n, n > 0 ? wc_verify.status : -1);
				goto trial_join;
			}
			fprintf(stderr, "  [QP_B recovery] %ld us, retry OK\n", recovery_us);

			tc.qp_b_phase = 3;

			/* 6. Post-recovery phase */
			usleep(POST_RECOVERY_MS * 1000);

			/* 7. Stop throughput thread */
			tc.stop = 1;
			pthread_join(tid, NULL);

			/* Output per-window data (second run, or only run for qp_only) */
			for (int w = 0; w < tc.num_windows; w++) {
				printf("%d,%s,%d,%ld,%ld,%ld,%s,%s\n",
				       trial, method_name, win_offset + w,
				       tc.windows[w].start_ms,
				       tc.windows[w].end_ms,
				       tc.windows[w].ops,
				       tc.windows[w].qp_b_state,
				       tc.windows[w].phase);
			}

			/* Summary line — combine with first-run windows if full_rebuild */
			long baseline_ops = carry_baseline_ops, fault_ops = carry_fault_ops;
			long recovered_ops = 0;
			int  baseline_n = carry_baseline_n, fault_n = carry_fault_n;
			int  recovered_n = 0;
			for (int w = 0; w < tc.num_windows; w++) {
				if (strcmp(tc.windows[w].phase, "baseline") == 0) {
					baseline_ops += tc.windows[w].ops;
					baseline_n++;
				} else if (strcmp(tc.windows[w].phase, "during_fault") == 0 ||
					   strcmp(tc.windows[w].phase, "during_recovery") == 0) {
					fault_ops += tc.windows[w].ops;
					fault_n++;
				} else if (strcmp(tc.windows[w].phase, "after_recovery") == 0) {
					recovered_ops += tc.windows[w].ops;
					recovered_n++;
				}
			}
			printf("# summary: %d,%s,%.0f,%.0f,%.0f,%ld,%ld\n",
			       trial, method_name,
			       baseline_n  ? (double)baseline_ops / baseline_n : 0,
			       fault_n     ? (double)fault_ops / fault_n : 0,
			       recovered_n ? (double)recovered_ops / recovered_n : 0,
			       detect_us, recovery_us);
			fflush(stdout);

			/* Cleanup */
			tcp_send_msg(sock, CMD_CLEANUP);
			wait_server_ack(sock, CMD_DONE);
			cleanup_multi(&m);
			continue;

		trial_join:
			tc.stop = 1;
			pthread_join(tid, NULL);
		trial_cleanup:
			tcp_send_msg(sock, CMD_CLEANUP);
			wait_server_ack(sock, CMD_DONE);
			cleanup_multi(&m);
		trial_fail:
			/* free m on the direct-to-fail paths (e.g. full_rebuild
			 * CLEANUP/SETUP handshake) that skip trial_cleanup.
			 * cleanup_multi is idempotent (memsets m), so the
			 * trial_cleanup fall-through calling it twice is safe. */
			cleanup_multi(&m);
			fprintf(stderr, "ERROR: trial %d method=%s failed\n",
				trial, method_name);
			failed++;
		}
	}

	return failed;
}

/* ------------------------------------------------------------------ */
/*  Mode 2: Concurrent different-error test                           */
/* ------------------------------------------------------------------ */

static int run_concurrent(int sock, int num_trials)
{
	printf("# mode=concurrent\n");
	printf("# trial,qp,cqe_status,cqe_status_str,vendor_err,detect_us,"
	       "recovery_us,counter_deltas\n");

	int failed = 0;

	for (int trial = 0; trial < num_trials; trial++) {
		struct multi_qp_res m;
		struct counter_snapshot snap_before, snap_after;
		struct timespec t0, t_detect_a, t_detect_b, t_recover_start, t_recover_done;
		long detect_a_us = 0, detect_b_us = 0, recovery_us = 0;

		fprintf(stderr, "\n--- Concurrent trial %d ---\n", trial);

		/* 1. Setup */
		if (tcp_send_msg(sock, CMD_SETUP_CONCURRENT) < 0)
			goto conc_fail;
		if (wait_server_ack(sock, CMD_READY) < 0)
			goto conc_fail;

		if (setup_multi_resources(&m) < 0)
			goto conc_fail;

		for (int i = 0; i < 2; i++) {
			if (tcp_exchange_qp_info(sock, &m.local_info[i],
						  &m.remote_info[i], 0) < 0)
				goto conc_cleanup;
		}
		for (int i = 0; i < 2; i++) {
			if (connect_multi_qp(&m, i, 7, 7, 14) < 0)
				goto conc_cleanup;
		}

		/* Warmup both QPs */
		for (int i = 0; i < 2; i++) {
			if (warmup_qp(&m, i, WARMUP_OPS) < 0)
				goto conc_cleanup;
		}

		/* 2. Counter snapshot before */
		snapshot_local_counters(&snap_before);

		/* 3. Inject: server deregisters QP_A's MR + moves QP_B to ERR */
		if (tcp_send_msg(sock, CMD_INJECT_CONCURRENT) < 0)
			goto conc_cleanup;
		if (wait_server_ack(sock, CMD_READY) < 0)
			goto conc_cleanup;

		ts_now(&t0);

		/* Post WRITE on QP_A -> REM_ACCESS_ERR (instant, ~480us) */
		if (post_write_on(&m, 0, 1, 500) != 0) {
			fprintf(stderr, "ERROR: post QP_A failed\n");
			goto conc_cleanup;
		}

		/* Post WRITE on QP_B -> will eventually get RETRY_EXC_ERR */
		if (post_write_on(&m, 1, 1, 501) != 0) {
			fprintf(stderr, "ERROR: post QP_B failed\n");
			goto conc_cleanup;
		}

		/* Poll QP_A CQE (should arrive quickly: REM_ACCESS_ERR) */
		struct ibv_wc wc_a;
		int n_a = poll_cq_block(m.cq[0], &wc_a, 5000);
		ts_now(&t_detect_a);
		detect_a_us = ts_diff_us(&t0, &t_detect_a);

		if (n_a <= 0) {
			fprintf(stderr, "ERROR: QP_A poll timed out\n");
			goto conc_cleanup;
		}

		/* Early detection on QP_B: force ERR after EARLY_DETECT_MS */
		long elapsed_since_post = ts_diff_us(&t0, &t_detect_a);
		long remaining_ms = EARLY_DETECT_MS - elapsed_since_post / 1000;
		if (remaining_ms > 0)
			usleep(remaining_ms * 1000);

		struct ibv_qp_attr err_attr = { .qp_state = IBV_QPS_ERR };
		ibv_modify_qp(m.qp[1], &err_attr, IBV_QP_STATE);

		struct ibv_wc wc_b;
		int n_b = poll_cq_block(m.cq[1], &wc_b, 5000);
		ts_now(&t_detect_b);
		detect_b_us = ts_diff_us(&t0, &t_detect_b);

		if (n_b <= 0) {
			fprintf(stderr, "ERROR: QP_B poll timed out\n");
			goto conc_cleanup;
		}

		fprintf(stderr, "  [QP_A] status=%d (%s) vendor_err=0x%x detect=%ld us\n",
			wc_a.status, ibv_wc_status_str(wc_a.status),
			wc_a.vendor_err, detect_a_us);
		fprintf(stderr, "  [QP_B] status=%d (%s) vendor_err=0x%x detect=%ld us\n",
			wc_b.status, ibv_wc_status_str(wc_b.status),
			wc_b.vendor_err, detect_b_us);

		/* 4. Counter snapshot after */
		snapshot_local_counters(&snap_after);

		/* Build counter delta string */
		char delta_str[1024] = "";
		int dlen = 0;
		for (int i = 0; i < snap_before.count && i < snap_after.count; i++) {
			long long delta = snap_after.values[i] - snap_before.values[i];
			if (delta != 0) {
				int wrote = snprintf(delta_str + dlen, sizeof(delta_str) - dlen,
						     "%s%s=+%lld",
						     dlen > 0 ? ";" : "",
						     snap_before.names[i], delta);
				if (wrote > 0) dlen += wrote;
				fprintf(stderr, "  [counter] %s: +%lld\n",
					snap_before.names[i], delta);
			}
		}
		if (dlen == 0)
			strncpy(delta_str, "none", sizeof(delta_str));

		/* 5. Recover both QPs */
		ts_now(&t_recover_start);

		if (tcp_send_msg(sock, CMD_RECOVER_CONCURRENT) < 0)
			goto conc_cleanup;

		for (int i = 0; i < 2; i++) {
			if (reset_and_reconnect_qp(sock, &m, i) < 0)
				goto conc_cleanup;
		}

		if (wait_server_ack(sock, CMD_READY) < 0)
			goto conc_cleanup;

		ts_now(&t_recover_done);
		recovery_us = ts_diff_us(&t_recover_start, &t_recover_done);

		/* Verify both QPs work */
		for (int i = 0; i < 2; i++) {
			if (post_write_on(&m, i, 1, 600 + i) != 0) {
				fprintf(stderr, "ERROR: QP[%d] retry post failed\n", i);
				goto conc_cleanup;
			}
			struct ibv_wc wc_v;
			int nv = poll_cq_block(m.cq[i], &wc_v, 5000);
			if (nv <= 0 || wc_v.status != IBV_WC_SUCCESS) {
				fprintf(stderr, "ERROR: QP[%d] retry failed\n", i);
				goto conc_cleanup;
			}
		}
		fprintf(stderr, "  [recovery] %ld us, both QPs verified\n", recovery_us);

		/* Output */
		printf("%d,A,%d,%s,0x%x,%ld,%ld,\"%s\"\n",
		       trial, wc_a.status, ibv_wc_status_str(wc_a.status),
		       wc_a.vendor_err, detect_a_us, recovery_us, delta_str);
		printf("%d,B,%d,%s,0x%x,%ld,%ld,\"%s\"\n",
		       trial, wc_b.status, ibv_wc_status_str(wc_b.status),
		       wc_b.vendor_err, detect_b_us, recovery_us, delta_str);
		fflush(stdout);

		/* Cleanup */
		tcp_send_msg(sock, CMD_CLEANUP);
		wait_server_ack(sock, CMD_DONE);
		cleanup_multi(&m);
		continue;

	conc_cleanup:
		tcp_send_msg(sock, CMD_CLEANUP);
		wait_server_ack(sock, CMD_DONE);
		cleanup_multi(&m);
	conc_fail:
		fprintf(stderr, "ERROR: concurrent trial %d failed\n", trial);
		failed++;
	}

	return failed;
}

/* ------------------------------------------------------------------ */
/*  main                                                              */
/* ------------------------------------------------------------------ */

int main(int argc, char *argv[])
{
	if (argc < 2) {
		fprintf(stderr, "Usage: %s <isolation|concurrent> [trials]\n", argv[0]);
		return 1;
	}

	const char *mode = argv[1];
	int num_trials = DEFAULT_TRIALS;
	if (argc > 2) {
		num_trials = atoi(argv[2]);
		if (num_trials <= 0)
			num_trials = DEFAULT_TRIALS;
	}

	srand(time(NULL));

	int sock = tcp_connect(RDMA_SERVER_IP, TCP_CTRL_PORT);
	if (sock < 0) {
		fprintf(stderr, "ERROR: cannot connect to server %s:%d\n",
			RDMA_SERVER_IP, TCP_CTRL_PORT);
		return 1;
	}
	fprintf(stderr, "Connected to server, mode=%s, trials=%d\n",
		mode, num_trials);

	int failed;

	if (strcmp(mode, "isolation") == 0) {
		failed = run_isolation(sock, num_trials);
	} else if (strcmp(mode, "concurrent") == 0) {
		failed = run_concurrent(sock, num_trials);
	} else {
		fprintf(stderr, "ERROR: unknown mode '%s'\n", mode);
		close(sock);
		return 1;
	}

	tcp_send_msg(sock, CMD_SHUTDOWN);
	close(sock);

	fprintf(stderr, "\nDone. %d trials failed.\n", failed);
	return (failed > 0) ? 1 : 0;
}
