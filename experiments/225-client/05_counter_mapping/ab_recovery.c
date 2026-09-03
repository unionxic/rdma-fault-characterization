/*
 * ab_recovery.c — Compare two recovery strategies for an address-violation
 * (REM_ACCESS_ERR / NAK) partial RDMA WRITE.
 *
 * Scenario (identical for both strategies): the client posts an RDMA WRITE
 * whose [remote_addr, remote_addr+len) overruns the server's registered MR
 * boundary. Multi-packet WRITEs DMA the whole PMTU(1024) packets that fit
 * before the boundary, then the boundary packet NAKs with REM_ACCESS_ERR. The
 * partial bytes that landed are a corruption hazard until correct data is
 * written. (Established by verify_partial_write.c: partials are whole-PMTU-
 * packet granular, and bytes_written == sq_psn_delta * PMTU.)
 *
 * Strategy A (reactive, post-hoc whole resend):
 *   - Normal WRITE, NO local bound check.
 *   - If it violates -> REM_ACCESS_ERR CQE.
 *   - Measure sq_psn_delta (ibv_query_qp IBV_QP_SQ_PSN) -> reconstruct landed
 *     bytes = sq_psn_delta * PMTU (the corruption footprint past the boundary).
 *   - QP-only recovery (reset -> new PSN -> re-exchange -> reconnect).
 *   - Resend the WHOLE message to a correct in-MR target.
 *   - Normal path cost = 0 (no check). Error path = detect + psn + recover +
 *     resend. Corruption window = from "partial landed" to "correct data done".
 *
 * Strategy B (proactive, pre-flight range check):
 *   - Server sends MR base+size at connect; client caches it.
 *   - Before every WRITE, check (remote_addr + len <= mr_base + mr_size).
 *   - Pass -> write as-is. Violation -> never put on the wire; correct the
 *     target address to a valid in-MR location, then write.
 *   - Normal path cost = one integer comparison per WRITE. Partial never
 *     occurs, so corruption window = 0 by construction.
 *
 * Usage: ./ab_recovery A|B [num_iters] [msg_size] [err_pct] [mr_size] [warmup]
 *   A|B        : strategy (required)
 *   num_iters  : measured WRITE iterations           (default 10000)
 *   msg_size   : WRITE payload bytes                 (default 4096, multi-pkt)
 *   err_pct    : %% of iters injected as violations   (default 0)
 *   mr_size    : server registered MR bytes          (default 65536)
 *   warmup     : warmup iters (not recorded)         (default 200)
 *
 * Output CSV: results/raw/ab_recovery.csv (appended). Schema documented in
 * README.md. Human-readable progress on stderr.
 *
 * Build: see Makefile target ab_recovery. Run via run_ab_recovery.sh.
 * Reuses counter_mapping/common.h (RDMA setup, qp_info exchange, SQ_PSN query,
 * device auto-resolve). Server side: counter_mapping/server.c handle_*_ab.
 */

#include "common.h"

/* ------------------------------------------------------------------ */
/*  Config / state                                                    */
/* ------------------------------------------------------------------ */

static struct rdma_res res;
static int ctrl_sock = -1;

/* Cached server MR bounds (received at SETUP_AB / RECOVER_AB). */
static uint64_t g_mr_base = 0;
static uint64_t g_mr_size = 0;

/* Correct in-MR target offset for resend / B-correction. We always land the
 * full message at offset 0 of the MR (valid as long as msg_size <= mr_size). */
#define CORRECT_OFFSET 0

/* ------------------------------------------------------------------ */
/*  TCP helpers (thin wrappers over common.h)                          */
/* ------------------------------------------------------------------ */

static int send_cmd_wait(int sock, const char *cmd, const char *expect)
{
	tcp_send_msg(sock, cmd);
	char resp[256];
	if (tcp_recv_msg(sock, resp, sizeof(resp)) <= 0)
		return -1;
	if (expect && strcmp(resp, expect) != 0) {
		fprintf(stderr, "Expected '%s', got '%s'\n", expect, resp);
		return -1;
	}
	return 0;
}

/* Read the "mr_base,mr_size" bounds line the server sends after qp_info. */
static int recv_ab_bounds(int sock)
{
	char line[128];
	if (tcp_recv_msg(sock, line, sizeof(line)) <= 0)
		return -1;
	unsigned long base = 0, size = 0;
	if (sscanf(line, "%lu,%lu", &base, &size) != 2) {
		fprintf(stderr, "Bad AB bounds line: '%s'\n", line);
		return -1;
	}
	g_mr_base = base;
	g_mr_size = size;
	return 0;
}

/* ------------------------------------------------------------------ */
/*  Client RDMA setup with an AB-sized buffer/MR                        */
/* ------------------------------------------------------------------ */

/* setup_rdma() registers only MR_SIZE (4096). For whole-message resend and for
 * messages up to AB_BUF_SIZE we need a bigger client MR. Reuse all of
 * setup_rdma()'s PD/CQ/QP/GID work, then swap the MR/buffer to AB_BUF_SIZE,
 * exactly like the server's handle_setup_ab does. */
static int setup_client_ab(void)
{
	int access = IBV_ACCESS_LOCAL_WRITE | IBV_ACCESS_REMOTE_WRITE |
		     IBV_ACCESS_REMOTE_READ;

	if (setup_rdma(&res, 0, access, 7, 7, 14) < 0)
		return -1;

	ibv_dereg_mr(res.mr);
	free(res.buf);

	res.buf = calloc(1, AB_BUF_SIZE);
	if (!res.buf) {
		fprintf(stderr, "calloc AB buffer failed\n");
		return -1;
	}
	res.buf_size = AB_BUF_SIZE;

	res.mr = ibv_reg_mr(res.pd, res.buf, AB_BUF_SIZE, access);
	if (!res.mr) {
		fprintf(stderr, "ibv_reg_mr(AB) failed: %s\n", strerror(errno));
		return -1;
	}

	res.local_info.rkey = res.mr->rkey;
	res.local_info.raddr = (uint64_t)res.buf;
	return 0;
}

/* ------------------------------------------------------------------ */
/*  WRITE posting                                                      */
/* ------------------------------------------------------------------ */

/* Post one RDMA WRITE to remote offset `roff`, length `len`. Caller polls. */
static int post_write_at(uint64_t roff, size_t len)
{
	struct ibv_sge sge = {
		.addr = (uint64_t)res.buf,
		.length = (uint32_t)len,
		.lkey = res.mr->lkey,
	};
	struct ibv_send_wr wr = {
		.wr_id = 1,
		.sg_list = &sge,
		.num_sge = 1,
		.opcode = IBV_WR_RDMA_WRITE,
		.send_flags = IBV_SEND_SIGNALED,
		.wr.rdma = {
			.remote_addr = res.remote_info.raddr + roff,
			.rkey = res.remote_info.rkey,
		},
	};
	struct ibv_send_wr *bad = NULL;
	return ibv_post_send(res.qp, &wr, &bad);
}

/* ------------------------------------------------------------------ */
/*  Strategy A: QP-only recovery over the live control socket          */
/* ------------------------------------------------------------------ */

/* Mirror of server handle_recover_ab. Returns recovery_us via *out. */
static int recover_qp_only(double *out_us)
{
	struct timespec r0, r1;
	clock_gettime(CLOCK_MONOTONIC, &r0);

	/* Drain CQ (the error CQE + any flushed WRs). */
	struct ibv_wc wc;
	while (ibv_poll_cq(res.cq, 1, &wc) > 0)
		;

	struct ibv_qp_attr attr = { .qp_state = IBV_QPS_RESET };
	if (ibv_modify_qp(res.qp, &attr, IBV_QP_STATE) < 0) {
		fprintf(stderr, "recover: reset failed: %s\n", strerror(errno));
		return -1;
	}

	res.local_info.psn = rand() & 0xFFFFFF;

	/* Tell server to recover in lockstep, then re-exchange + reconnect. */
	tcp_send_msg(ctrl_sock, CMD_RECOVER_AB);
	tcp_exchange_qp_info(ctrl_sock, &res.local_info, &res.remote_info, 0);

	if (connect_qp(&res, 1, 7, 7, 14) < 0) {
		fprintf(stderr, "recover: reconnect failed\n");
		return -1;
	}

	/* Server resends bounds, then READY. */
	if (recv_ab_bounds(ctrl_sock) < 0)
		return -1;
	char resp[64];
	if (tcp_recv_msg(ctrl_sock, resp, sizeof(resp)) <= 0 ||
	    strcmp(resp, CMD_READY) != 0) {
		fprintf(stderr, "recover: no READY (got '%s')\n", resp);
		return -1;
	}

	clock_gettime(CLOCK_MONOTONIC, &r1);
	*out_us = elapsed_us(&r0, &r1);
	return 0;
}

/* ------------------------------------------------------------------ */
/*  Percentile helpers (sort + index)                                  */
/* ------------------------------------------------------------------ */

static int cmp_double(const void *a, const void *b)
{
	double x = *(const double *)a, y = *(const double *)b;
	return (x > y) - (x < y);
}

static double percentile(double *sorted, int n, double p)
{
	if (n <= 0)
		return 0;
	int idx = (int)(p * (n - 1) + 0.5);
	if (idx < 0) idx = 0;
	if (idx >= n) idx = n - 1;
	return sorted[idx];
}

/* ------------------------------------------------------------------ */
/*  main                                                               */
/* ------------------------------------------------------------------ */

int main(int argc, char **argv)
{
	if (argc < 2 || (strcmp(argv[1], "A") != 0 && strcmp(argv[1], "B") != 0)) {
		fprintf(stderr,
			"Usage: %s A|B [num_iters] [msg_size] [err_pct] "
			"[mr_size] [warmup]\n", argv[0]);
		return 1;
	}
	const char strategy = argv[1][0];
	int num_iters  = (argc > 2) ? atoi(argv[2]) : 10000;
	size_t msg_size = (argc > 3) ? (size_t)atoll(argv[3]) : 4096;
	double err_pct  = (argc > 4) ? atof(argv[4]) : 0.0;
	size_t mr_size  = (argc > 5) ? (size_t)atoll(argv[5]) : 65536;
	int warmup      = (argc > 6) ? atoi(argv[6]) : 200;

	/* Declared up front so the cleanup labels (reached by goto from before
	 * the allocation sites) can release them safely without jumping over an
	 * in-scope initializer. */
	FILE *csv = NULL;
	double *norm_lat = NULL;

	if (msg_size == 0 || msg_size > AB_BUF_SIZE) {
		fprintf(stderr, "msg_size must be in (0, %d]\n", AB_BUF_SIZE);
		return 1;
	}
	if (mr_size == 0 || mr_size > AB_BUF_SIZE) {
		fprintf(stderr, "mr_size must be in (0, %d]\n", AB_BUF_SIZE);
		return 1;
	}
	if (msg_size > mr_size) {
		fprintf(stderr,
			"msg_size (%zu) > mr_size (%zu): correct WRITE can't fit "
			"in MR; pick mr_size >= msg_size\n", msg_size, mr_size);
		return 1;
	}

	srand(time(NULL) ^ getpid());

	/* The violation target: place the message so it straddles the MR end.
	 * Half the message lands in-MR, half overruns -> guaranteed partial for
	 * multi-packet messages. For single-packet (<=PMTU) messages the NIC
	 * checks the whole range first -> NO_WRITE (no partial); the code still
	 * exercises detect+recover, corruption window is then ~0 (nothing
	 * landed) which the server CHECK_AB confirms. */
	uint64_t violate_off = (mr_size > msg_size / 2)
				 ? (mr_size - msg_size / 2) : 0;

	ctrl_sock = tcp_connect(RDMA_SERVER_IP, TCP_CTRL_PORT);
	if (ctrl_sock < 0) {
		fprintf(stderr, "Cannot connect to server control port\n");
		return 1;
	}

	/* Server: register MR of mr_size, send bounds. */
	char setup_cmd[64];
	snprintf(setup_cmd, sizeof(setup_cmd), "%s %zu", CMD_SETUP_AB, mr_size);
	tcp_send_msg(ctrl_sock, setup_cmd);

	if (setup_client_ab() < 0) {
		fprintf(stderr, "client setup failed\n");
		goto out_sock;
	}
	tcp_exchange_qp_info(ctrl_sock, &res.local_info, &res.remote_info, 0);
	if (connect_qp(&res, 1, 7, 7, 14) < 0) {
		fprintf(stderr, "connect_qp failed\n");
		goto out_rdma;
	}
	if (recv_ab_bounds(ctrl_sock) < 0)
		goto out_rdma;
	char rdy[64];
	if (tcp_recv_msg(ctrl_sock, rdy, sizeof(rdy)) <= 0 ||
	    strcmp(rdy, CMD_READY) != 0) {
		fprintf(stderr, "no READY after SETUP_AB (got '%s')\n", rdy);
		goto out_rdma;
	}

	fprintf(stderr, "[ab] strategy=%c iters=%d msg=%zu err_pct=%.2f "
		"mr_size=%zu warmup=%d\n", strategy, num_iters, msg_size,
		err_pct, mr_size, warmup);
	fprintf(stderr, "[ab] server MR base=0x%lx size=%lu; violate_off=%lu "
		"(in-MR avail at violation = %lu)\n",
		(unsigned long)g_mr_base, (unsigned long)g_mr_size,
		(unsigned long)violate_off,
		(unsigned long)(g_mr_size - violate_off));

	/* Fill client buffer with a non-zero pattern so the server can detect
	 * landed bytes (0 == untouched). */
	memset(res.buf, 0xAA, AB_BUF_SIZE);

	/* Zero the server backing buffer once before measurement. */
	if (send_cmd_wait(ctrl_sock, CMD_INIT_AB, CMD_DONE) < 0)
		goto out_rdma;

	/* Output CSV (append; header written by run script if new). */
	csv = fopen("results/raw/ab_recovery.csv", "a");
	if (!csv) {
		perror("fopen csv");
		goto out_rdma;
	}

	/* Per-iteration latency record (normal writes only, for distribution). */
	norm_lat = calloc(num_iters > 0 ? num_iters : 1, sizeof(double));
	if (!norm_lat) {
		goto out_rdma;
	}
	int norm_n = 0;

	long n_normal = 0, n_error = 0;
	double sum_recover_us = 0;       /* A: per-error recovery cost */
	double sum_corrupt_us = 0;       /* A: per-error corruption window */
	long sum_landed_bytes = 0;       /* A: reconstructed in-MR partial bytes */
	long sum_partial_truth = 0;      /* server ground-truth in-MR partial bytes */
	int corrupt_match = 0, corrupt_total = 0;

	struct timespec wall0, wall1;

	/* The error schedule: deterministic spacing for reproducibility.
	 * inject every `interval`-th iteration when err_pct>0. */
	double frac = err_pct / 100.0;
	int interval = (frac > 0.0) ? (int)(1.0 / frac + 0.5) : 0;
	if (interval < 1 && frac > 0.0)
		interval = 1;

	/* -------------------- warmup (not recorded) -------------------- */
	for (int i = 0; i < warmup; i++) {
		if (post_write_at(CORRECT_OFFSET, msg_size) < 0)
			break;
		struct ibv_wc wc;
		if (poll_cq_block(res.cq, &wc, 5000) <= 0 ||
		    wc.status != IBV_WC_SUCCESS) {
			fprintf(stderr, "[ab] warmup WRITE failed (status=%d)\n",
				wc.status);
			break;
		}
	}

	clock_gettime(CLOCK_MONOTONIC, &wall0);

	/* -------------------- measured loop --------------------------- */
	for (int i = 0; i < num_iters; i++) {
		int inject = (interval > 0) && ((i % interval) == 0);

		if (!inject) {
			/* ---- NORMAL WRITE ---- */
			struct timespec t0, t1;
			if (strategy == 'B') {
				/* Pre-flight range check (the B overhead). The
				 * check is on the hot path and timed with the
				 * write. Always passes for the normal target. */
				clock_gettime(CLOCK_MONOTONIC, &t0);
				uint64_t raddr = g_mr_base + CORRECT_OFFSET;
				int ok = (raddr + msg_size <= g_mr_base + g_mr_size);
				if (!ok) {
					/* would never happen for CORRECT_OFFSET */
					fprintf(stderr, "[ab] B: normal check "
						"unexpectedly failed\n");
					break;
				}
				if (post_write_at(CORRECT_OFFSET, msg_size) < 0)
					break;
			} else {
				clock_gettime(CLOCK_MONOTONIC, &t0);
				if (post_write_at(CORRECT_OFFSET, msg_size) < 0)
					break;
			}
			struct ibv_wc wc;
			if (poll_cq_block(res.cq, &wc, 5000) <= 0 ||
			    wc.status != IBV_WC_SUCCESS) {
				fprintf(stderr, "[ab] normal WRITE failed "
					"(status=%d %s)\n", wc.status,
					ibv_wc_status_str(wc.status));
				break;
			}
			clock_gettime(CLOCK_MONOTONIC, &t1);
			if (norm_n < num_iters)
				norm_lat[norm_n++] = elapsed_us(&t0, &t1);
			n_normal++;
			continue;
		}

		/* ---- INJECTED VIOLATION ---- */
		n_error++;

		if (strategy == 'B') {
			/* Proactive: detect the would-be violation locally,
			 * correct the address, write. Nothing hits the wire
			 * wrong; no partial; corruption window = 0. */
			struct timespec b0, b1;
			clock_gettime(CLOCK_MONOTONIC, &b0);

			uint64_t want = g_mr_base + violate_off;
			int ok = (want + msg_size <= g_mr_base + g_mr_size);
			uint64_t use_off = ok ? violate_off : CORRECT_OFFSET;
			/* (ok is false by construction -> corrected) */
			if (post_write_at(use_off, msg_size) < 0)
				break;
			struct ibv_wc wc;
			if (poll_cq_block(res.cq, &wc, 5000) <= 0 ||
			    wc.status != IBV_WC_SUCCESS) {
				fprintf(stderr, "[ab] B corrected WRITE failed "
					"(status=%d)\n", wc.status);
				break;
			}
			clock_gettime(CLOCK_MONOTONIC, &b1);
			double cost = elapsed_us(&b0, &b1);
			sum_recover_us += cost;     /* "recovery" cost for B */
			sum_corrupt_us += 0.0;      /* no corruption window */

			/* B: detect_us=0 (range check folded into cost),
			 * recover_us=cost (check+correct+write), corrupt=0,
			 * landed=0, truth=0, recon_match=1 (no corruption),
			 * trailing norm/wall columns = 0. */
			fprintf(csv, "%c,%d,%zu,%.2f,%zu,error,0,0.000,%.3f,0.000,"
				"0,0,1,0.000,0.000,0.000,0,0.000\n",
				strategy, i, msg_size, err_pct, mr_size, cost);
			corrupt_total++;
			corrupt_match++;   /* trivially correct: no corruption */
			continue;
		}

		/* ---- strategy A: reactive ---- */
		/* SQ PSN before, to reconstruct the in-MR partial that lands. */
		struct ibv_qp_attr qattr;
		struct ibv_qp_init_attr qinit;
		uint32_t psn_before = 0, psn_after = 0;
		if (ibv_query_qp(res.qp, &qattr, IBV_QP_SQ_PSN, &qinit) == 0)
			psn_before = qattr.sq_psn;

		/* t_partial marks when the (bad) WRITE goes out: the corrupt
		 * partial begins landing as soon as the in-MR-prefix packets
		 * DMA-commit (a hair after this post). This is the start of the
		 * corruption window. */
		struct timespec t_partial, t_detect, t_corr_end;
		clock_gettime(CLOCK_MONOTONIC, &t_partial);
		if (post_write_at(violate_off, msg_size) < 0)
			break;

		struct ibv_wc wc;
		int n = poll_cq_block(res.cq, &wc, 30000);
		clock_gettime(CLOCK_MONOTONIC, &t_detect);
		if (n <= 0) {
			fprintf(stderr, "[ab] A: poll timeout on violation\n");
			break;
		}

		if (ibv_query_qp(res.qp, &qattr, IBV_QP_SQ_PSN, &qinit) == 0)
			psn_after = qattr.sq_psn;
		uint32_t psn_delta = (psn_after - psn_before) & 0xFFFFFF;
		long landed_bytes = (long)psn_delta * PMTU_BYTES;

		double detect_us = elapsed_us(&t_partial, &t_detect);

		/* Ground-truth the partial NOW, before recovery/resend, so the
		 * straddle region [violate_off, mr_size) reflects exactly what
		 * the failed WRITE left behind (the resend lands at offset 0 and
		 * could otherwise overlap for small mr_size). */
		char check_cmd[96];
		snprintf(check_cmd, sizeof(check_cmd), "%s %lu %zu %zu",
			 CMD_CHECK_AB, (unsigned long)violate_off, msg_size,
			 mr_size);
		tcp_send_msg(ctrl_sock, check_cmd);
		char buf_resp[160];
		long partial_truth = 0, resend_pre = 0, past_mr = 0;
		if (tcp_recv_msg(ctrl_sock, buf_resp, sizeof(buf_resp)) > 0)
			sscanf(buf_resp,
			       "AB:partial_bytes=%ld:resend_bytes=%ld:past_mr=%ld",
			       &partial_truth, &resend_pre, &past_mr);
		(void)resend_pre; (void)past_mr;  /* diagnostics */

		int match = (landed_bytes == partial_truth) ? 1 : 0;

		/* QP-only recovery (reset -> new PSN -> re-exchange -> reconnect). */
		double recover_us = 0;
		if (recover_qp_only(&recover_us) < 0) {
			fprintf(stderr, "[ab] A: recovery failed\n");
			break;
		}

		/* Whole-message resend to the correct in-MR target (offset 0). */
		if (post_write_at(CORRECT_OFFSET, msg_size) < 0)
			break;
		struct ibv_wc wc2;
		if (poll_cq_block(res.cq, &wc2, 5000) <= 0 ||
		    wc2.status != IBV_WC_SUCCESS) {
			fprintf(stderr, "[ab] A: resend failed (status=%d %s)\n",
				wc2.status, ibv_wc_status_str(wc2.status));
			break;
		}
		clock_gettime(CLOCK_MONOTONIC, &t_corr_end);

		/* Corruption window per task definition: from when the partial
		 * landed (t_partial) to when the correct data resend completes
		 * (t_corr_end). During this window a server-side reader could
		 * observe the stale partial in [violate_off, mr_size). */
		double corrupt_us = elapsed_us(&t_partial, &t_corr_end);

		corrupt_total++;
		if (match)
			corrupt_match++;

		sum_recover_us += recover_us;
		sum_corrupt_us += corrupt_us;
		sum_landed_bytes += landed_bytes;
		sum_partial_truth += partial_truth;

		/* Re-zero server buffer so the stale partial doesn't contaminate
		 * the next trial's CHECK_AB. (In a real system, recovery would
		 * also overwrite/zero the corrupt straddle region; here the
		 * resend lands at offset 0, so we clear separately.) */
		if (send_cmd_wait(ctrl_sock, CMD_INIT_AB, CMD_DONE) < 0)
			break;

		/* error rows carry 0 in the trailing norm/wall columns. */
		fprintf(csv, "%c,%d,%zu,%.2f,%zu,error,%u,%.3f,%.3f,%.3f,"
			"%ld,%ld,%d,0.000,0.000,0.000,0,0.000\n",
			strategy, i, msg_size, err_pct, mr_size,
			psn_delta, detect_us, recover_us, corrupt_us,
			landed_bytes, partial_truth, match);

		fprintf(stderr, "  [A] iter %d: detect=%.0fus recover=%.0fus "
			"corrupt_win=%.0fus landed=%ld truth=%ld %s\n",
			i, detect_us, recover_us, corrupt_us,
			landed_bytes, partial_truth,
			match ? "OK" : "MISMATCH");
	}

	clock_gettime(CLOCK_MONOTONIC, &wall1);
	double total_wall_us = elapsed_us(&wall0, &wall1);

	/* Normal-write latency distribution (sorted in place for percentiles). */
	double p50 = 0, p99 = 0, mean = 0;
	if (norm_n > 0) {
		double s = 0;
		for (int i = 0; i < norm_n; i++) s += norm_lat[i];
		mean = s / norm_n;
		qsort(norm_lat, norm_n, sizeof(double), cmp_double);
		p50 = percentile(norm_lat, norm_n, 0.50);
		p99 = percentile(norm_lat, norm_n, 0.99);
	}

	/* Summary row (phase=summary). Column meanings on this row:
	 *   sq_psn_delta        slot -> total iters (n_normal + n_error)
	 *   detect_us           slot -> 0 (per-error detect is on error rows)
	 *   recover_us          slot -> mean per-error recover cost
	 *   corrupt_us          slot -> mean per-error corruption window
	 *   landed_bytes        slot -> mean reconstructed landed bytes
	 *   overrun_truth_bytes slot -> mean server-truth overrun bytes
	 *   recon_match         slot -> count of trials whose reconstruction matched
	 *   norm_mean/p50/p99   -> normal-WRITE latency distribution (us)
	 *   norm_count          -> number of normal WRITEs measured
	 *   total_wall_us       -> wall-clock for the whole measured loop (us) */
	fprintf(csv,
		"%c,-1,%zu,%.2f,%zu,summary,%ld,0.000,%.3f,%.3f,%ld,%ld,%d,"
		"%.3f,%.3f,%.3f,%d,%.3f\n",
		strategy, msg_size, err_pct, mr_size,
		n_normal + n_error,
		(n_error > 0) ? sum_recover_us / n_error : 0.0,
		(n_error > 0) ? sum_corrupt_us / n_error : 0.0,
		(long)(n_error > 0 ? sum_landed_bytes / n_error : 0),
		(long)(n_error > 0 ? sum_partial_truth / n_error : 0),
		corrupt_match,
		mean, p50, p99, norm_n, total_wall_us);

	fprintf(stderr, "\n========== summary (strategy %c) ==========\n",
		strategy);
	fprintf(stderr, "normal writes : %ld\n", n_normal);
	fprintf(stderr, "error writes  : %ld\n", n_error);
	fprintf(stderr, "normal latency: mean=%.2fus p50=%.2fus p99=%.2fus "
		"(n=%d)\n", mean, p50, p99, norm_n);
	fprintf(stderr, "total wall    : %.0fus (%.3f ms)\n",
		total_wall_us, total_wall_us / 1000.0);
	if (n_error > 0) {
		fprintf(stderr, "per-error recover : %.1fus\n",
			sum_recover_us / n_error);
		fprintf(stderr, "per-error corrupt : %.1fus%s\n",
			sum_corrupt_us / n_error,
			strategy == 'B' ? " (0 by construction)" : "");
		fprintf(stderr, "reconstruction    : %d/%d trials matched "
			"server ground truth\n", corrupt_match, corrupt_total);
	}
	fprintf(stderr, "CSV: results/raw/ab_recovery.csv\n");

	free(norm_lat);
	fclose(csv);

	send_cmd_wait(ctrl_sock, CMD_SHUTDOWN, CMD_DONE);
	cleanup_rdma(&res);
	close(ctrl_sock);
	return 0;

out_rdma:
	if (norm_lat)
		free(norm_lat);
	if (csv)
		fclose(csv);
	cleanup_rdma(&res);
out_sock:
	if (ctrl_sock >= 0) {
		send_cmd_wait(ctrl_sock, CMD_SHUTDOWN, CMD_DONE);
		close(ctrl_sock);
	}
	return 1;
}
