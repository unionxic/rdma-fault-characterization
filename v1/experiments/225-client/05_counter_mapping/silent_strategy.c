/*
 * silent_strategy.c — 무음(silent) partial RDMA WRITE 대응 전략 비교 harness
 *                     (client / requester, 225에서 실행)
 *
 * 배경: 응답자(responder) QP가 전송 도중 ERR로 떨어지는 timeout/peer-death 경로의
 * partial WRITE는 NAK가 없다("silent"). requester는 flush된 WQE만 본다. NAK 경로
 * (ab_recovery.c)와 달리 sq_psn으로는 커밋 경계를 복원할 수 없다(sq_psn = 전송된
 * PSN이지 커밋된 바이트가 아님, verify_interrupted_write.c에서 확립). 하지만 WRITE
 * requester는 원본을 항상 보유하므로 진짜 위험은 데이터 손실이 아니라 "소비자가
 * torn prefix를 완전한 것으로 읽는 것"이다. 즉 필요한 것은 바이트 경계 복원이 아니라
 * valid/invalid 판별(커밋 의미론)이다.
 *
 * 이 harness는 torn prefix를 안전하게 만드는 세 전략의 (1) 정상경로 오버헤드와
 * (2) 에러 후 판별/복구 비용을 비교한다. C0는 순수 baseline(비교 기준)이다.
 *
 *   C0 baseline    : 순수 WRITE 1개(signaled). 판별 장치 없음.
 *   C1 commit-flag : payload WRITE(unsignaled) + 8B flag WRITE(signaled)를 같은
 *                    QP에 연속 post. RC in-order 실행 => payload가 mid-transfer
 *                    실패하면 flag WR은 절대 실행 안 됨. 판별 O(1) (flag 유무).
 *   C2 crc32c      : payload 앞 16B 헤더 [seq|len|crc|reserved]를 포함해 단일
 *                    WRITE. crc32c는 payload만 커버. 판별 = 서버가 crc 재계산 O(len).
 *   C3 read-back   : 정상경로는 C0과 동일(오버헤드 0). 에러 후 QP-only recovery →
 *                    대상 영역을 RDMA READ로 회수 → 로컬 원본과 비교해 written
 *                    boundary 탐색 → 경계부터 나머지만 재전송(partial resend).
 *
 * fault 주입은 verify_interrupted_write.c 방식 재사용: 4MB WRITE post 후 settle_ms
 * 지나서 CMD_INTERRUPT로 responder QP→ERR (race). 감지 시간은 측정 대상이 아니므로
 * 로컬 QP→ERR 강제 flush로 즉시 CQE를 얻어 3.7s retry 대기를 피한다(detect_us는
 * 참고용). 트라이얼 결과는 PARTIAL/FULL/NO_WRITE 혼재 — outcome에 기록하고 분석은
 * PARTIAL 부분집합 중심. ground truth는 서버 CHECK_C 스캔.
 *
 * Usage:
 *   ./silent_strategy <C0|C1|C2|C3> normal [msg_size] [num_iters]
 *   ./silent_strategy <C1|C2|C3>    error  [msg_size(무시,4MB고정)] [num_iters] [settle_ms]
 *
 * 정상경로 기본: num_iters=1000, warmup=100.  에러경로 기본: num_iters=100, settle=80ms.
 *
 * 출력 CSV: results/raw/silent_strategy.csv (append; 헤더는 run_silent.sh가 기록).
 * Build: Makefile 타깃 silent_strategy (-msse4.2). Run via run_silent.sh.
 * 서버(224) 짝: server.c handle_setup_c/init_c/interrupt/check_flag/verify_crc/
 * recover_c/check_c. 공유 헤더 common.h(setup_rdma / qp_info 교환 / connect_qp).
 */

#include "common.h"

/* ------------------------------------------------------------------ */
/*  Config / state                                                    */
/* ------------------------------------------------------------------ */

static struct rdma_res res;
static int ctrl_sock = -1;

/* Strategy ids. C0=baseline, C1=commit-flag, C2=crc32c, C3=read-back. */
enum { C0 = 0, C1 = 1, C2 = 2, C3 = 3 };
static const char *strat_name[] = { "C0", "C1", "C2", "C3" };

#define NORMAL_WARMUP  100

/* ------------------------------------------------------------------ */
/*  crc32c (Castagnoli) — MUST match server.c byte-for-byte            */
/* ------------------------------------------------------------------ */

/* Hardware SSE4.2 path when available, portable bitwise fallback otherwise. The
 * software path uses the same reflected poly (0x82F63B78) the CRC32 instruction
 * implements, so the two paths agree. Build with -msse4.2 (see Makefile). */
#ifdef __SSE4_2__
#include <nmmintrin.h>
#endif
static uint32_t crc32c(const void *data, size_t len)
{
	const uint8_t *p = (const uint8_t *)data;
	uint32_t crc = 0xFFFFFFFFu;
#ifdef __SSE4_2__
	while (len >= 8) {
		crc = (uint32_t)_mm_crc32_u64(crc, *(const uint64_t *)p);
		p += 8;
		len -= 8;
	}
	while (len--)
		crc = _mm_crc32_u8(crc, *p++);
#else
	for (size_t i = 0; i < len; i++) {
		crc ^= p[i];
		for (int k = 0; k < 8; k++)
			crc = (crc >> 1) ^
			      (0x82F63B78u & (uint32_t)(-(int32_t)(crc & 1)));
	}
#endif
	return crc ^ 0xFFFFFFFFu;
}

/* ------------------------------------------------------------------ */
/*  TCP + timing helpers                                              */
/* ------------------------------------------------------------------ */

static int send_cmd_wait(int sock, const char *cmd, const char *expect)
{
	tcp_send_msg(sock, cmd);
	char resp[256];
	if (tcp_recv_msg(sock, resp, sizeof(resp)) <= 0)
		return -1;
	if (expect && strcmp(resp, expect) != 0) {
		fprintf(stderr, "  expected '%s', got '%s'\n", expect, resp);
		return -1;
	}
	return 0;
}

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

static void force_qp_err(struct ibv_qp *qp)
{
	struct ibv_qp_attr attr = { .qp_state = IBV_QPS_ERR };
	if (ibv_modify_qp(qp, &attr, IBV_QP_STATE))
		fprintf(stderr, "  local ibv_modify_qp(ERR) failed: %s\n",
			strerror(errno));
}

/* ------------------------------------------------------------------ */
/*  Client RDMA setup with an 8MB (LARGE) buffer/MR                    */
/* ------------------------------------------------------------------ */

/* Reuse setup_rdma()'s PD/CQ/QP/GID work, then swap the MR/buffer to
 * LARGE_BUF_SIZE with REMOTE_READ (needed to issue C3's RDMA READ target and to
 * mirror the server layout). Identical shape to ab_recovery's setup_client_ab. */
static int setup_client_c(void)
{
	int access = IBV_ACCESS_LOCAL_WRITE | IBV_ACCESS_REMOTE_WRITE |
		     IBV_ACCESS_REMOTE_READ;

	if (setup_rdma(&res, 0, access, 7, 7, 14) < 0)
		return -1;

	ibv_dereg_mr(res.mr);
	free(res.buf);

	res.buf = calloc(1, LARGE_BUF_SIZE);
	if (!res.buf) {
		fprintf(stderr, "calloc C buffer failed\n");
		return -1;
	}
	res.buf_size = LARGE_BUF_SIZE;

	res.mr = ibv_reg_mr(res.pd, res.buf, LARGE_BUF_SIZE, access);
	if (!res.mr) {
		fprintf(stderr, "ibv_reg_mr(C) failed: %s\n", strerror(errno));
		return -1;
	}

	res.local_info.rkey = res.mr->rkey;
	res.local_info.raddr = (uint64_t)res.buf;
	return 0;
}

/* ------------------------------------------------------------------ */
/*  WRITE / READ posting                                              */
/* ------------------------------------------------------------------ */

/* One RDMA WRITE: local buf+local_off -> remote raddr+remote_off, len bytes. */
static int post_write(uint64_t local_off, uint64_t remote_off, size_t len,
		      int signaled)
{
	struct ibv_sge sge = {
		.addr = (uint64_t)res.buf + local_off,
		.length = (uint32_t)len,
		.lkey = res.mr->lkey,
	};
	struct ibv_send_wr wr = {
		.wr_id = 1,
		.sg_list = &sge,
		.num_sge = 1,
		.opcode = IBV_WR_RDMA_WRITE,
		.send_flags = signaled ? IBV_SEND_SIGNALED : 0,
		.wr.rdma = {
			.remote_addr = res.remote_info.raddr + remote_off,
			.rkey = res.remote_info.rkey,
		},
	};
	struct ibv_send_wr *bad = NULL;
	return ibv_post_send(res.qp, &wr, &bad);
}

/* One RDMA READ: remote raddr+remote_off -> local buf+local_off, len bytes. */
static int post_read(uint64_t local_off, uint64_t remote_off, size_t len)
{
	struct ibv_sge sge = {
		.addr = (uint64_t)res.buf + local_off,
		.length = (uint32_t)len,
		.lkey = res.mr->lkey,
	};
	struct ibv_send_wr wr = {
		.wr_id = 3,
		.sg_list = &sge,
		.num_sge = 1,
		.opcode = IBV_WR_RDMA_READ,
		.send_flags = IBV_SEND_SIGNALED,
		.wr.rdma = {
			.remote_addr = res.remote_info.raddr + remote_off,
			.rkey = res.remote_info.rkey,
		},
	};
	struct ibv_send_wr *bad = NULL;
	return ibv_post_send(res.qp, &wr, &bad);
}

/* C1: payload WRITE(unsignaled) linked to 8B flag WRITE(signaled), posted in one
 * ibv_post_send so both are enqueued before the fault. RC executes them in order,
 * so the flag slot is written ONLY if the whole payload landed. flag value =
 * magic(hi32) | seq(lo32). payload_len lets the same helper serve both the
 * normal-path sweep (variable msg) and the 4MB error path. */
static int post_c1_pair(uint32_t seq, size_t payload_len)
{
	uint64_t flagval = ((uint64_t)C_FLAG_MAGIC << 32) | (uint32_t)seq;
	memcpy((unsigned char *)res.buf + C_FLAG_OFFSET, &flagval, 8);

	struct ibv_sge sge_p = {
		.addr = (uint64_t)res.buf,
		.length = (uint32_t)payload_len,
		.lkey = res.mr->lkey,
	};
	struct ibv_sge sge_f = {
		.addr = (uint64_t)res.buf + C_FLAG_OFFSET,
		.length = 8,
		.lkey = res.mr->lkey,
	};
	struct ibv_send_wr wr_f = {
		.wr_id = 2,
		.sg_list = &sge_f,
		.num_sge = 1,
		.opcode = IBV_WR_RDMA_WRITE,
		.send_flags = IBV_SEND_SIGNALED,
		.wr.rdma = {
			.remote_addr = res.remote_info.raddr + C_FLAG_OFFSET,
			.rkey = res.remote_info.rkey,
		},
	};
	struct ibv_send_wr wr_p = {
		.wr_id = 1,
		.sg_list = &sge_p,
		.num_sge = 1,
		.opcode = IBV_WR_RDMA_WRITE,
		.send_flags = 0,            /* unsignaled: flag CQE covers both  */
		.next = &wr_f,
		.wr.rdma = {
			.remote_addr = res.remote_info.raddr,
			.rkey = res.remote_info.rkey,
		},
	};
	struct ibv_send_wr *bad = NULL;
	return ibv_post_send(res.qp, &wr_p, &bad);
}

/* Fill the C2 header at local offset 0 (seq, payload len, crc32c over payload). */
static void fill_c2_header(uint32_t seq, size_t payload_len)
{
	struct c2_header hdr;
	hdr.seq = seq;
	hdr.len = (uint32_t)payload_len;
	hdr.crc = crc32c((unsigned char *)res.buf + C2_HEADER_SIZE, payload_len);
	hdr.reserved = 0;
	memcpy(res.buf, &hdr, C2_HEADER_SIZE);
}

/* ------------------------------------------------------------------ */
/*  QP-only recovery over the live control socket (mirror server)      */
/* ------------------------------------------------------------------ */

static int recover_qp_only_c(double *out_us)
{
	struct timespec r0, r1;
	clock_gettime(CLOCK_MONOTONIC, &r0);

	struct ibv_wc wc;
	while (ibv_poll_cq(res.cq, 1, &wc) > 0)
		; /* drain the error + flushed CQEs */

	struct ibv_qp_attr attr = { .qp_state = IBV_QPS_RESET };
	if (ibv_modify_qp(res.qp, &attr, IBV_QP_STATE) < 0) {
		fprintf(stderr, "recover: reset failed: %s\n", strerror(errno));
		return -1;
	}

	res.local_info.psn = rand() & 0xFFFFFF;

	tcp_send_msg(ctrl_sock, CMD_RECOVER_C);
	tcp_exchange_qp_info(ctrl_sock, &res.local_info, &res.remote_info, 0);

	if (connect_qp(&res, 1, 7, 7, 14) < 0) {
		fprintf(stderr, "recover: reconnect failed\n");
		return -1;
	}

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

/* Find the written boundary in a read-back buffer (C3): the partial is a
 * PMTU-granular non-zero prefix followed by INIT zeros. Coarse-scan by PMTU to
 * the first zero block, then a fine walk pins the exact last-non-zero byte
 * (defensive: also handles a non-PMTU-aligned or non-contiguous edge case). */
static long scan_boundary(const unsigned char *rb, long len)
{
	long b = len;                    /* default: FULL (no zero found) */
	for (long i = 0; i < len; i += PMTU_BYTES) {
		if (rb[i] == 0) {
			b = i;
			break;
		}
	}
	while (b > 0 && rb[b - 1] == 0)          /* walk back to last non-zero */
		b--;
	while (b < len && rb[b] != 0)            /* extend over any short tail */
		b++;
	return b;
}

/* ------------------------------------------------------------------ */
/*  Normal path: latency of one strategy at one msg size               */
/* ------------------------------------------------------------------ */

static int run_normal(int strat, size_t msg, int num_iters, FILE *csv)
{
	/* One healthy connection for the whole sweep (no fault). */
	tcp_send_msg(ctrl_sock, CMD_SETUP_C);
	if (setup_client_c() < 0)
		return -1;
	tcp_exchange_qp_info(ctrl_sock, &res.local_info, &res.remote_info, 0);
	if (connect_qp(&res, 1, 7, 7, 14) < 0) {
		cleanup_rdma(&res);
		return -1;
	}
	char resp[256];
	if (tcp_recv_msg(ctrl_sock, resp, sizeof(resp)) <= 0 ||
	    strcmp(resp, CMD_READY) != 0) {
		fprintf(stderr, "  normal: no READY (got '%s')\n", resp);
		cleanup_rdma(&res);
		return -1;
	}
	if (send_cmd_wait(ctrl_sock, CMD_INIT_C, CMD_DONE) < 0) {
		cleanup_rdma(&res);
		return -1;
	}

	/* Local source pattern (0xAB = non-zero). C2 keeps the header at [0,16) and
	 * the payload at [16, 16+msg); everyone else uses payload at [0, msg). */
	size_t payload_off = (strat == C2) ? C2_HEADER_SIZE : 0;
	memset((unsigned char *)res.buf + payload_off, 0xAB, msg);

	double *lat = calloc(num_iters > 0 ? num_iters : 1, sizeof(double));
	if (!lat) {
		cleanup_rdma(&res);
		return -1;
	}
	int n = 0;

	for (int i = -NORMAL_WARMUP; i < num_iters; i++) {
		uint32_t seq = (uint32_t)(i + NORMAL_WARMUP + 1);
		struct timespec t0, t1;
		int rc;

		clock_gettime(CLOCK_MONOTONIC, &t0);
		switch (strat) {
		case C1:
			rc = post_c1_pair(seq, msg);
			break;
		case C2:
			fill_c2_header(seq, msg);         /* CRC compute = the overhead */
			rc = post_write(0, 0, C2_HEADER_SIZE + msg, 1);
			break;
		case C0:
		case C3:                                  /* C3 normal == C0 */
		default:
			rc = post_write(0, 0, msg, 1);
			break;
		}
		if (rc) {
			fprintf(stderr, "  normal post failed (strat=%s)\n",
				strat_name[strat]);
			break;
		}
		struct ibv_wc wc;
		if (poll_cq_block(res.cq, &wc, 5000) <= 0 ||
		    wc.status != IBV_WC_SUCCESS) {
			fprintf(stderr, "  normal WRITE failed (status=%d %s)\n",
				wc.status, ibv_wc_status_str(wc.status));
			break;
		}
		clock_gettime(CLOCK_MONOTONIC, &t1);

		if (i >= 0 && n < num_iters)              /* skip warmup */
			lat[n++] = elapsed_us(&t0, &t1);
	}

	double mean = 0, p50 = 0, p99 = 0;
	if (n > 0) {
		double s = 0;
		for (int i = 0; i < n; i++)
			s += lat[i];
		mean = s / n;
		qsort(lat, n, sizeof(double), cmp_double);
		p50 = percentile(lat, n, 0.50);
		p99 = percentile(lat, n, 0.99);
	}
	free(lat);

	/* phase=normal summary row (error columns zeroed). */
	fprintf(csv,
		"%s,normal,%zu,-1,NA,0,0,0,0.000,0.000,0.000,0,0.000,0.000,"
		"%.3f,%.3f,%.3f,%d\n",
		strat_name[strat], msg, mean, p50, p99, n);
	fflush(csv);

	fprintf(stderr, "[%s normal] msg=%zu n=%d  mean=%.2fus p50=%.2fus p99=%.2fus\n",
		strat_name[strat], msg, n, mean, p50, p99);

	send_cmd_wait(ctrl_sock, CMD_SHUTDOWN, CMD_DONE);
	cleanup_rdma(&res);
	return 0;
}

/* ------------------------------------------------------------------ */
/*  Error path: one fault-injection trial for a strategy               */
/* ------------------------------------------------------------------ */

struct err_agg {
	int trials, full, partial, nowrite;
	int judged_valid, judge_correct;
	double sum_detect, sum_recover, sum_judge, sum_resend, sum_total;
	double sum_gt, sum_resend_bytes;
};

static int run_error_trial(int strat, int trial, int settle_ms, FILE *csv,
			   struct err_agg *agg)
{
	uint32_t seq = (uint32_t)(trial + 1);           /* non-zero */
	size_t payload_len = LARGE_WRITE_LEN;           /* 4MB fixed */
	long region_off = (strat == C2) ? C2_HEADER_SIZE : 0;

	/* Fresh server + client RDMA state per trial (like verify_interrupted_write). */
	tcp_send_msg(ctrl_sock, CMD_SETUP_C);
	if (setup_client_c() < 0)
		return -1;
	tcp_exchange_qp_info(ctrl_sock, &res.local_info, &res.remote_info, 0);
	if (connect_qp(&res, 1, 7, 7, 14) < 0) {
		cleanup_rdma(&res);
		return -1;
	}
	char resp[256];
	if (tcp_recv_msg(ctrl_sock, resp, sizeof(resp)) <= 0 ||
	    strcmp(resp, CMD_READY) != 0) {
		fprintf(stderr, "  trial %d: no READY (got '%s')\n", trial, resp);
		cleanup_rdma(&res);
		return -1;
	}
	if (send_cmd_wait(ctrl_sock, CMD_INIT_C, CMD_DONE) < 0) {
		cleanup_rdma(&res);
		return -1;
	}

	/* Build the local source. Zero everything first (clears the flag slot),
	 * then lay the non-zero payload so the server's scan sees a clean prefix. */
	memset(res.buf, 0, res.buf_size);
	memset((unsigned char *)res.buf + region_off, 0xAB, payload_len);
	if (strat == C2)
		fill_c2_header(seq, payload_len);

	/* ---- RACE: post the WRITE(s), then drive the responder QP to ERR ---- */
	int post_ret;
	if (strat == C1) {
		post_ret = post_c1_pair(seq, payload_len);
	} else {
		size_t wlen = (strat == C2) ? (C2_HEADER_SIZE + payload_len)
					    : payload_len;
		post_ret = post_write(0, 0, wlen, 1);
	}
	tcp_send_msg(ctrl_sock, CMD_INTERRUPT);

	if (post_ret) {
		fprintf(stderr, "  trial %d: post failed: %s\n", trial,
			strerror(post_ret));
		tcp_recv_msg(ctrl_sock, resp, sizeof(resp));  /* drain ack */
		send_cmd_wait(ctrl_sock, CMD_CLEANUP, CMD_DONE);
		cleanup_rdma(&res);
		return -1;
	}
	/* Drain the INTERRUPT ack (DONE / ERROR). */
	if (tcp_recv_msg(ctrl_sock, resp, sizeof(resp)) <= 0) {
		fprintf(stderr, "  trial %d: no INTERRUPT ack\n", trial);
		cleanup_rdma(&res);
		return -1;
	}

	/* Let ACKs settle, then force LOCAL QP->ERR for a fast flush CQE instead of
	 * waiting ~3.7s for RETRY_EXC_ERR. The settle wait is artificial and is NOT
	 * counted in any reported cost; detect_us times only the flush itself. */
	usleep(settle_ms * 1000);

	struct timespec d0, d1;
	clock_gettime(CLOCK_MONOTONIC, &d0);
	force_qp_err(res.qp);
	struct ibv_wc wc;
	int nc = poll_cq_block(res.cq, &wc, 2000);
	clock_gettime(CLOCK_MONOTONIC, &d1);
	double detect_us = elapsed_us(&d0, &d1);
	if (nc <= 0) {
		fprintf(stderr, "  trial %d: no flush CQE in 2000ms\n", trial);
		send_cmd_wait(ctrl_sock, CMD_CLEANUP, CMD_DONE);
		cleanup_rdma(&res);
		return -1;
	}
	struct ibv_wc wc2;                               /* drain extras (C1 pair) */
	while (ibv_poll_cq(res.cq, 1, &wc2) > 0)
		;

	/* ---- Ground truth (BEFORE recovery/resend): how many payload bytes landed ---- */
	char cc[64];
	snprintf(cc, sizeof(cc), "%s %ld %zu", CMD_CHECK_C, region_off, payload_len);
	tcp_send_msg(ctrl_sock, cc);
	if (tcp_recv_msg(ctrl_sock, resp, sizeof(resp)) <= 0) {
		fprintf(stderr, "  trial %d: no CHECK_C\n", trial);
		send_cmd_wait(ctrl_sock, CMD_CLEANUP, CMD_DONE);
		cleanup_rdma(&res);
		return -1;
	}
	long gt = 0, nonzero = 0, last = -1;
	sscanf(resp, "CHECK_C:landed=%ld:nonzero=%ld:last=%ld", &gt, &nonzero, &last);
	const char *outcome = (gt <= 0) ? "NO_WRITE"
			    : (gt >= (long)payload_len) ? "FULL" : "PARTIAL";
	int is_full = (gt >= (long)payload_len);

	/* ---- Strategy-specific judge / recover / resend ---- */
	double recover_us = 0, judge_us = 0, resend_us = 0;
	long resend_bytes = 0;
	int judged_valid = 0, judge_correct = 0;

	if (strat == C1) {
		/* Judge = read the commit-flag slot (O(1); flag absence IS the verdict). */
		struct timespec j0, j1;
		clock_gettime(CLOCK_MONOTONIC, &j0);
		tcp_send_msg(ctrl_sock, CMD_CHECK_FLAG);
		tcp_recv_msg(ctrl_sock, resp, sizeof(resp));
		clock_gettime(CLOCK_MONOTONIC, &j1);
		judge_us = elapsed_us(&j0, &j1);

		unsigned long long seen = 0;
		sscanf(resp, "FLAG:%llu", &seen);
		uint64_t expect = ((uint64_t)C_FLAG_MAGIC << 32) | (uint32_t)seq;
		judged_valid = (seen == expect);
		judge_correct = (judged_valid == is_full);

		if (recover_qp_only_c(&recover_us) < 0)
			goto trial_fail;

		/* Recover -> full payload+flag resend. */
		struct timespec s0, s1;
		clock_gettime(CLOCK_MONOTONIC, &s0);
		if (post_c1_pair(seq, payload_len) ||
		    poll_cq_block(res.cq, &wc, 5000) <= 0 ||
		    wc.status != IBV_WC_SUCCESS) {
			fprintf(stderr, "  trial %d: C1 resend failed\n", trial);
			goto trial_fail;
		}
		clock_gettime(CLOCK_MONOTONIC, &s1);
		resend_us = elapsed_us(&s0, &s1);
		resend_bytes = (long)payload_len;

	} else if (strat == C2) {
		/* Judge = server recomputes crc over the landed payload (O(len)). */
		char vc[64];
		snprintf(vc, sizeof(vc), "%s %u", CMD_VERIFY_CRC, seq);
		tcp_send_msg(ctrl_sock, vc);
		tcp_recv_msg(ctrl_sock, resp, sizeof(resp));
		int cv = 0;
		double srv_judge = 0;
		sscanf(resp, "CRC:valid=%d:judge_us=%lf", &cv, &srv_judge);
		judge_us = srv_judge;                    /* the actual O(len) cost */
		judged_valid = cv;
		judge_correct = (judged_valid == is_full);

		if (recover_qp_only_c(&recover_us) < 0)
			goto trial_fail;

		/* Recover -> full header+payload resend. */
		struct timespec s0, s1;
		clock_gettime(CLOCK_MONOTONIC, &s0);
		if (post_write(0, 0, C2_HEADER_SIZE + payload_len, 1) ||
		    poll_cq_block(res.cq, &wc, 5000) <= 0 ||
		    wc.status != IBV_WC_SUCCESS) {
			fprintf(stderr, "  trial %d: C2 resend failed\n", trial);
			goto trial_fail;
		}
		clock_gettime(CLOCK_MONOTONIC, &s1);
		resend_us = elapsed_us(&s0, &s1);
		resend_bytes = (long)payload_len;

	} else { /* C3 */
		/* Recover first (READ needs a live QP), then read-back + diff. */
		if (recover_qp_only_c(&recover_us) < 0)
			goto trial_fail;

		struct timespec j0, j1;
		clock_gettime(CLOCK_MONOTONIC, &j0);
		/* READ remote [0, payload_len) into the second half of the local
		 * buffer so we don't clobber the source at [0, payload_len). */
		if (post_read(payload_len, 0, payload_len) ||
		    poll_cq_block(res.cq, &wc, 5000) <= 0 ||
		    wc.status != IBV_WC_SUCCESS) {
			fprintf(stderr, "  trial %d: C3 read-back failed (status=%d)\n",
				trial, wc.status);
			goto trial_fail;
		}
		long boundary = scan_boundary(
			(unsigned char *)res.buf + payload_len, (long)payload_len);
		clock_gettime(CLOCK_MONOTONIC, &j1);
		judge_us = elapsed_us(&j0, &j1);

		judged_valid = (boundary >= (long)payload_len);
		judge_correct = (boundary == gt);        /* boundary detected exactly? */
		resend_bytes = (long)payload_len - boundary;

		/* Partial resend: only the missing tail [boundary, payload_len). */
		struct timespec s0, s1;
		clock_gettime(CLOCK_MONOTONIC, &s0);
		if (resend_bytes > 0) {
			if (post_write((uint64_t)boundary, (uint64_t)boundary,
				       (size_t)resend_bytes, 1) ||
			    poll_cq_block(res.cq, &wc, 5000) <= 0 ||
			    wc.status != IBV_WC_SUCCESS) {
				fprintf(stderr, "  trial %d: C3 resend failed\n", trial);
				goto trial_fail;
			}
		}
		clock_gettime(CLOCK_MONOTONIC, &s1);
		resend_us = elapsed_us(&s0, &s1);
	}

	double total_us = detect_us + recover_us + judge_us + resend_us;

	/* phase=error row (norm columns zeroed). */
	fprintf(csv,
		"%s,error,%zu,%d,%s,%ld,%d,%d,%.3f,%.3f,%.3f,%ld,%.3f,%.3f,"
		"0.000,0.000,0.000,0\n",
		strat_name[strat], payload_len, trial, outcome, gt,
		judged_valid, judge_correct, detect_us, recover_us, judge_us,
		resend_bytes, resend_us, total_us);
	fflush(csv);

	fprintf(stderr,
		"  [%s] trial %d: %-8s gt=%ld judged=%s %s | recover=%.0f judge=%.1f "
		"resend=%ld(%.0fus) total=%.0fus\n",
		strat_name[strat], trial, outcome, gt,
		judged_valid ? "valid" : "torn",
		judge_correct ? "OK" : "MISJUDGE",
		recover_us, judge_us, resend_bytes, resend_us, total_us);

	/* Aggregate. */
	agg->trials++;
	if (gt <= 0) agg->nowrite++;
	else if (is_full) agg->full++;
	else agg->partial++;
	agg->judged_valid += judged_valid;
	agg->judge_correct += judge_correct;
	agg->sum_detect += detect_us;
	agg->sum_recover += recover_us;
	agg->sum_judge += judge_us;
	agg->sum_resend += resend_us;
	agg->sum_total += total_us;
	agg->sum_gt += gt;
	agg->sum_resend_bytes += resend_bytes;

	send_cmd_wait(ctrl_sock, CMD_CLEANUP, CMD_DONE);
	cleanup_rdma(&res);
	return 0;

trial_fail:
	send_cmd_wait(ctrl_sock, CMD_CLEANUP, CMD_DONE);
	cleanup_rdma(&res);
	return -1;
}

/* ------------------------------------------------------------------ */
/*  main                                                               */
/* ------------------------------------------------------------------ */

int main(int argc, char **argv)
{
	if (argc < 3) {
		fprintf(stderr,
			"Usage: %s <C0|C1|C2|C3> <normal|error> "
			"[msg_size] [num_iters] [settle_ms]\n", argv[0]);
		return 1;
	}

	int strat = -1;
	for (int i = 0; i < 4; i++)
		if (strcmp(argv[1], strat_name[i]) == 0)
			strat = i;
	if (strat < 0) {
		fprintf(stderr, "bad strategy '%s' (C0|C1|C2|C3)\n", argv[1]);
		return 1;
	}

	int is_error = (strcmp(argv[2], "error") == 0);
	if (!is_error && strcmp(argv[2], "normal") != 0) {
		fprintf(stderr, "bad mode '%s' (normal|error)\n", argv[2]);
		return 1;
	}
	if (is_error && strat == C0) {
		fprintf(stderr, "C0 has no judging device; error mode is C1|C2|C3\n");
		return 1;
	}

	size_t msg = (argc > 3) ? (size_t)atoll(argv[3]) : 4096;
	int num_iters = (argc > 4) ? atoi(argv[4]) : (is_error ? 100 : 1000);
	int settle_ms = (argc > 5) ? atoi(argv[5]) : 80;

	if (is_error)
		msg = LARGE_WRITE_LEN;                    /* error path fixed at 4MB */
	if (msg == 0 || msg > LARGE_WRITE_LEN) {
		fprintf(stderr, "msg_size must be in (0, %d]\n", LARGE_WRITE_LEN);
		return 1;
	}

	srand(time(NULL) ^ getpid());

	ctrl_sock = tcp_connect(RDMA_SERVER_IP, TCP_CTRL_PORT);
	if (ctrl_sock < 0) {
		fprintf(stderr, "Cannot connect to server at %s:%d\n",
			RDMA_SERVER_IP, TCP_CTRL_PORT);
		return 1;
	}

	FILE *csv = fopen("results/raw/silent_strategy.csv", "a");
	if (!csv) {
		perror("fopen csv");
		close(ctrl_sock);
		return 1;
	}

	if (!is_error) {
		fprintf(stderr, "=== silent_strategy NORMAL: %s msg=%zu iters=%d ===\n",
			strat_name[strat], msg, num_iters);
		run_normal(strat, msg, num_iters, csv);
		fclose(csv);
		close(ctrl_sock);
		return 0;
	}

	/* ---- error path ---- */
	fprintf(stderr,
		"=== silent_strategy ERROR: %s msg=%d(4MB) trials=%d settle=%dms ===\n",
		strat_name[strat], LARGE_WRITE_LEN, num_iters, settle_ms);

	struct err_agg agg = {0};
	for (int t = 0; t < num_iters; t++) {
		if (run_error_trial(strat, t, settle_ms, csv, &agg) < 0)
			fprintf(stderr, "  trial %d failed (skipped)\n", t);
	}

	/* phase=summary row. Means over completed trials; counts in the
	 * judged_valid / judge_correct columns; trials count in norm_count. */
	int tr = agg.trials > 0 ? agg.trials : 1;
	char tok[32];
	snprintf(tok, sizeof(tok), "P%d_F%d_N%d",
		 agg.partial, agg.full, agg.nowrite);
	fprintf(csv,
		"%s,summary,%d,-1,%s,%ld,%d,%d,%.3f,%.3f,%.3f,%ld,%.3f,%.3f,"
		"0.000,0.000,0.000,%d\n",
		strat_name[strat], LARGE_WRITE_LEN, tok,
		(long)(agg.sum_gt / tr), agg.judged_valid, agg.judge_correct,
		agg.sum_detect / tr, agg.sum_recover / tr, agg.sum_judge / tr,
		(long)(agg.sum_resend_bytes / tr), agg.sum_resend / tr,
		agg.sum_total / tr, agg.trials);
	fflush(csv);

	fprintf(stderr, "\n===== summary (%s) =====\n", strat_name[strat]);
	fprintf(stderr, "trials=%d  PARTIAL=%d FULL=%d NO_WRITE=%d\n",
		agg.trials, agg.partial, agg.full, agg.nowrite);
	fprintf(stderr, "judge_correct=%d/%d  judged_valid=%d\n",
		agg.judge_correct, agg.trials, agg.judged_valid);
	fprintf(stderr, "mean: recover=%.1fus judge=%.1fus resend=%.1fus "
		"total=%.1fus  resend_bytes=%ld (of %d)\n",
		agg.sum_recover / tr, agg.sum_judge / tr, agg.sum_resend / tr,
		agg.sum_total / tr, (long)(agg.sum_resend_bytes / tr),
		LARGE_WRITE_LEN);

	send_cmd_wait(ctrl_sock, CMD_SHUTDOWN, CMD_DONE);
	fclose(csv);
	close(ctrl_sock);
	return 0;
}
