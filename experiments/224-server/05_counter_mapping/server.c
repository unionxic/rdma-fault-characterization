/*
 * server.c — fingerprint / partial-write / A-B recovery responder (224에서 실행)
 *
 * TCP 제어 소켓(18515)으로 client(225)의 명령을 받아 시나리오별 RDMA 자원을
 * 구성해 주는 상시 서버. 225의 run*.sh 스크립트들이 SSH로 빌드/기동/종료한다.
 *
 * 처리하는 명령 (common.h의 CMD_*):
 *   SETUP / SETUP_SEND / SETUP_NOREMOTE : 11개 fault 시나리오 fingerprint용 QP 구성
 *     (REMOTE_WRITE 금지 = REM_INV_REQ 유발, SEND-RECV 모드 = RNR_RETRY_EXC 유발)
 *   INJECT <sc>                         : 서버 쪽 fault 주입 (RETRY_EXC_QP_ERR: QP→ERR)
 *   SETUP_BOUNDARY / INIT_BUFFER / CHECK_BUFFER :
 *     MR 경계 partial write 검증 — 서버가 자기 버퍼를 직접 스캔해서
 *     실제 기록된 바이트 수(ground truth)를 돌려준다 (verify_partial_write.c 짝)
 *   SETUP_AB / RECOVER_AB / INIT_AB / CHECK_AB :
 *     A/B recovery 전략 비교 (ab_recovery.c 짝). RECOVER_AB는 제어 소켓을
 *     유지한 채 QP-only recovery(RESET→INIT→RTR→RTS, PSN 재교환)를 수행한다.
 */
#include "common.h"

static struct rdma_res res;
static int ctrl_sock = -1;

static int handle_setup(int conn, int use_send_recv, int enable_remote_write)
{
	int access = IBV_ACCESS_LOCAL_WRITE;
	if (enable_remote_write)
		access |= IBV_ACCESS_REMOTE_WRITE | IBV_ACCESS_REMOTE_READ;

	if (setup_rdma(&res, use_send_recv, access, 7, 7, 14) < 0)
		return -1;

	tcp_exchange_qp_info(conn, &res.local_info, &res.remote_info, 1);

	if (connect_qp(&res, enable_remote_write, 7, 7, 14) < 0)
		return -1;

	if (use_send_recv) {
		/* For RNR_RETRY_EXC scenario, we intentionally do NOT post recv */
		printf("  [server] SEND/RECV QP ready (no recv WQE posted for RNR_RETRY_EXC)\n");
	} else {
		printf("  [server] WRITE QP ready (remote_write=%d)\n",
		       enable_remote_write);
	}

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

static int handle_inject(int conn, const char *scenario_str)
{
	int scenario = atoi(scenario_str);

	switch (scenario) {
	case REM_INV_REQ:
		/* QP already setup without REMOTE_WRITE flag.
		 * The client's RDMA WRITE will trigger NAK code 1. */
		printf("  [server] REM_INV_REQ: QP has no REMOTE_WRITE (already set)\n");
		break;

	case RNR_RETRY_EXC:
		/* No recv WQE posted — client's SEND will get RNR NAK */
		printf("  [server] RNR_RETRY_EXC: no recv WQE posted\n");
		break;

	case RETRY_EXC_QP_ERR: {
		struct ibv_qp_attr attr = { .qp_state = IBV_QPS_ERR };
		if (ibv_modify_qp(res.qp, &attr, IBV_QP_STATE) < 0) {
			perror("ibv_modify_qp(ERR)");
			return -1;
		}
		printf("  [server] RETRY_EXC_QP_ERR: QP moved to ERR state\n");
		break;
	}

	default:
		printf("  [server] scenario %d: no server-side action needed\n",
		       scenario);
		break;
	}

	tcp_send_msg(conn, CMD_DONE);
	return 0;
}

static int handle_setup_boundary(int conn)
{
	int access = IBV_ACCESS_LOCAL_WRITE | IBV_ACCESS_REMOTE_WRITE |
		     IBV_ACCESS_REMOTE_READ;

	if (setup_rdma(&res, 0, access, 7, 7, 14) < 0)
		return -1;

	ibv_dereg_mr(res.mr);
	free(res.buf);

	res.buf = calloc(1, BOUNDARY_BUF_SIZE);
	if (!res.buf)
		return -1;
	res.buf_size = BOUNDARY_BUF_SIZE;

	res.mr = ibv_reg_mr(res.pd, res.buf, MR_SIZE, access);
	if (!res.mr)
		return -1;

	res.local_info.rkey = res.mr->rkey;
	res.local_info.raddr = (uint64_t)res.buf;

	tcp_exchange_qp_info(conn, &res.local_info, &res.remote_info, 1);

	if (connect_qp(&res, 1, 7, 7, 14) < 0)
		return -1;

	printf("  [server] Boundary QP ready (buf=%d, mr=%d)\n",
	       BOUNDARY_BUF_SIZE, MR_SIZE);
	tcp_send_msg(conn, CMD_READY);
	return 0;
}

static void handle_init_buffer(int conn)
{
	memset(res.buf, 0, res.buf_size);
	printf("  [server] Buffer zeroed (%zu bytes)\n", res.buf_size);
	tcp_send_msg(conn, CMD_DONE);
}

static void handle_check_buffer(int conn, const char *args)
{
	int offset = 0, length = 0;
	sscanf(args, "%d %d", &offset, &length);

	unsigned char *buf = (unsigned char *)res.buf;
	int mr_end = MR_SIZE;

	int within_end = (offset + length < mr_end) ?
			 offset + length : mr_end;
	int within_mod = 0;
	for (int i = offset; i < within_end; i++)
		if (buf[i] != 0) within_mod++;

	int beyond_start = mr_end;
	int beyond_end = offset + length;
	if (beyond_end > (int)res.buf_size)
		beyond_end = (int)res.buf_size;
	int beyond_mod = 0;
	for (int i = beyond_start; i < beyond_end; i++)
		if (buf[i] != 0) beyond_mod++;

	char resp[128];
	snprintf(resp, sizeof(resp), "PARTIAL:%d/%d:%d/%d",
		 within_mod, within_end - offset,
		 beyond_mod, beyond_end - beyond_start);
	printf("  [server] %s\n", resp);
	tcp_send_msg(conn, resp);
}

/* ------------------------------------------------------------------ */
/*  A/B recovery-strategy comparison (REM_ACCESS_ERR address overrun)  */
/* ------------------------------------------------------------------ */

/* Send the registered MR bounds as an extra control line so strategy B can
 * range-check WRITEs locally. raddr/rkey are already in the qp_info exchange;
 * this line adds mr_size (the registered length), which qp_info doesn't carry. */
static void send_ab_bounds(int conn, size_t mr_size)
{
	char line[128];
	snprintf(line, sizeof(line), "%lu,%lu",
		 (unsigned long)res.local_info.raddr, (unsigned long)mr_size);
	tcp_send_msg(conn, line);
}

/* SETUP_AB <mr_size>: back AB_BUF_SIZE bytes, register an MR of only mr_size
 * bytes. The prefix [0,mr_size) is the valid WRITE target; [mr_size,AB_BUF_SIZE)
 * is backing memory a boundary-overrun WRITE can DMA into before NAK. */
static int handle_setup_ab(int conn, const char *args)
{
	size_t mr_size = 0;
	sscanf(args, "%zu", &mr_size);
	if (mr_size == 0 || mr_size > AB_BUF_SIZE) {
		fprintf(stderr, "  [server] SETUP_AB bad mr_size=%zu\n", mr_size);
		return -1;
	}

	int access = IBV_ACCESS_LOCAL_WRITE | IBV_ACCESS_REMOTE_WRITE |
		     IBV_ACCESS_REMOTE_READ;

	if (setup_rdma(&res, 0, access, 7, 7, 14) < 0)
		return -1;

	/* Replace the default MR_SIZE buffer/MR with our AB layout. */
	ibv_dereg_mr(res.mr);
	free(res.buf);

	res.buf = calloc(1, AB_BUF_SIZE);
	if (!res.buf)
		return -1;
	res.buf_size = AB_BUF_SIZE;

	res.mr = ibv_reg_mr(res.pd, res.buf, mr_size, access);
	if (!res.mr) {
		fprintf(stderr, "  [server] ibv_reg_mr(%zu) failed: %s\n",
			mr_size, strerror(errno));
		return -1;
	}

	res.local_info.rkey = res.mr->rkey;
	res.local_info.raddr = (uint64_t)res.buf;

	tcp_exchange_qp_info(conn, &res.local_info, &res.remote_info, 1);

	if (connect_qp(&res, 1, 7, 7, 14) < 0)
		return -1;

	send_ab_bounds(conn, mr_size);

	printf("  [server] AB QP ready (backing=%d, mr=%zu)\n",
	       AB_BUF_SIZE, mr_size);
	tcp_send_msg(conn, CMD_READY);
	return 0;
}

/* RECOVER_AB: QP-only recovery over the live socket (strategy A).
 * Same MR/buffer is kept; only the QP is reset + re-handshaked. Mirrors the
 * client: reset -> new PSN -> re-exchange -> reconnect, then resend bounds. */
static int handle_recover_ab(int conn)
{
	if (!res.qp) {
		fprintf(stderr, "  [server] RECOVER_AB: no QP\n");
		return -1;
	}

	struct ibv_wc wc;
	while (ibv_poll_cq(res.cq, 1, &wc) > 0)
		; /* drain */

	struct ibv_qp_attr attr = { .qp_state = IBV_QPS_RESET };
	if (ibv_modify_qp(res.qp, &attr, IBV_QP_STATE) < 0) {
		fprintf(stderr, "  [server] RECOVER_AB reset failed: %s\n",
			strerror(errno));
		return -1;
	}

	res.local_info.psn = rand() & 0xFFFFFF;

	tcp_exchange_qp_info(conn, &res.local_info, &res.remote_info, 1);

	if (connect_qp(&res, 1, 7, 7, 14) < 0) {
		fprintf(stderr, "  [server] RECOVER_AB reconnect failed\n");
		return -1;
	}

	/* MR is unchanged; resend bounds so the client can re-read them. */
	send_ab_bounds(conn, res.mr->length);

	printf("  [server] AB QP recovered (QP-only)\n");
	tcp_send_msg(conn, CMD_READY);
	return 0;
}

static void handle_init_ab(int conn)
{
	memset(res.buf, 0, res.buf_size);
	printf("  [server] AB buffer zeroed (%zu bytes)\n", res.buf_size);
	tcp_send_msg(conn, CMD_DONE);
}

/* CHECK_AB <off> <len> <mr_size>: ground-truth scan of the backing buffer for
 * a straddling WRITE that started at `off` and would span `len` bytes, against
 * a registered MR of `mr_size` bytes.
 *
 * The proven partial-write model (verify_partial_write.c): a multi-packet WRITE
 * that overruns the MR boundary DMA-commits the whole PMTU packets that fit
 * inside the MR, i.e. into the straddle region [off, mr_size); the boundary
 * packet (and everything past it) NAKs with REM_ACCESS_ERR and never lands.
 * So the corruption footprint is the modified bytes in [off, mr_size), and the
 * requester's reconstruction sq_psn_delta*PMTU must equal that count.
 *
 * Reports:
 *   partial_bytes : modified (non-zero) bytes in [off, mr_size)  -> the partial
 *                   that landed in the MR (corruption footprint, match target).
 *   resend_bytes  : modified bytes in [0, len)                   -> confirms the
 *                   correct whole-message resend landed at offset 0.
 *   past_mr       : modified bytes in [mr_size, AB_BUF_SIZE)      -> must be 0
 *                   (no bytes should ever land past the boundary). */
static void handle_check_ab(int conn, const char *args)
{
	long off = 0, len = 0, mr_size = 0;
	sscanf(args, "%ld %ld %ld", &off, &len, &mr_size);

	unsigned char *buf = (unsigned char *)res.buf;
	long n = (long)res.buf_size;
	if (mr_size < 0) mr_size = 0;
	if (mr_size > n) mr_size = n;
	if (off < 0) off = 0;
	if (off > mr_size) off = mr_size;

	/* partial that landed in the MR straddle region [off, mr_size) */
	long partial_bytes = 0;
	for (long i = off; i < mr_size; i++)
		if (buf[i] != 0) partial_bytes++;

	/* correct resend region [0, len) */
	long resend_end = (len < n) ? len : n;
	long resend_bytes = 0;
	for (long i = 0; i < resend_end; i++)
		if (buf[i] != 0) resend_bytes++;

	/* anything past the MR boundary should be untouched */
	long past_mr = 0;
	for (long i = mr_size; i < n; i++)
		if (buf[i] != 0) past_mr++;

	char resp[160];
	snprintf(resp, sizeof(resp),
		 "AB:partial_bytes=%ld:resend_bytes=%ld:past_mr=%ld",
		 partial_bytes, resend_bytes, past_mr);
	printf("  [server] %s\n", resp);
	tcp_send_msg(conn, resp);
}

/* ------------------------------------------------------------------ */
/*  Strategy-C: silent partial-write commit-protocol comparison        */
/*  (SETUP_C / INIT_C / INTERRUPT / CHECK_FLAG / VERIFY_CRC /           */
/*   RECOVER_C / CHECK_C — all additive, existing handlers untouched)   */
/* ------------------------------------------------------------------ */

/* crc32c (Castagnoli) — hardware SSE4.2 path when available, portable bitwise
 * fallback otherwise. Requester (silent_strategy.c) and responder MUST agree
 * byte-for-byte, so the software path uses the same reflected polynomial
 * (0x82F63B78) that the CRC32 instruction implements. Build the server with
 * -msse4.2 (see Makefile) for the hardware path on the x86 Xeon. */
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

/* SETUP_C: back LARGE_BUF_SIZE (8MB) and register an 8MB MR that INCLUDES
 * REMOTE_READ (C3 reads the region back). The payload target is offset 0; the
 * commit-flag slot is the 8B aligned tail (C_FLAG_OFFSET). */
static int handle_setup_c(int conn)
{
	int access = IBV_ACCESS_LOCAL_WRITE | IBV_ACCESS_REMOTE_WRITE |
		     IBV_ACCESS_REMOTE_READ;

	if (setup_rdma(&res, 0, access, 7, 7, 14) < 0)
		return -1;

	/* Swap the default MR_SIZE buffer for the 8MB strategy-C layout. */
	ibv_dereg_mr(res.mr);
	free(res.buf);

	res.buf = calloc(1, LARGE_BUF_SIZE);
	if (!res.buf)
		return -1;
	res.buf_size = LARGE_BUF_SIZE;

	res.mr = ibv_reg_mr(res.pd, res.buf, LARGE_BUF_SIZE, access);
	if (!res.mr) {
		fprintf(stderr, "  [server] SETUP_C ibv_reg_mr(%d) failed: %s\n",
			LARGE_BUF_SIZE, strerror(errno));
		return -1;
	}

	res.local_info.rkey = res.mr->rkey;
	res.local_info.raddr = (uint64_t)res.buf;

	tcp_exchange_qp_info(conn, &res.local_info, &res.remote_info, 1);

	if (connect_qp(&res, 1, 7, 7, 14) < 0)
		return -1;

	printf("  [server] C QP ready (buf+mr=%d, REMOTE_READ enabled)\n",
	       LARGE_BUF_SIZE);
	tcp_send_msg(conn, CMD_READY);
	return 0;
}

static void handle_init_c(int conn)
{
	memset(res.buf, 0, res.buf_size);
	printf("  [server] C buffer zeroed (%zu bytes)\n", res.buf_size);
	tcp_send_msg(conn, CMD_DONE);
}

/* INTERRUPT: the mid-transfer fault. Drive the responder QP to ERR while the
 * requester's multi-packet WRITE is in flight -> silent partial write. */
static int handle_interrupt(int conn)
{
	if (!res.qp) {
		fprintf(stderr, "  [server] INTERRUPT: no QP\n");
		tcp_send_msg(conn, "ERROR");
		return -1;
	}
	struct ibv_qp_attr attr = { .qp_state = IBV_QPS_ERR };
	if (ibv_modify_qp(res.qp, &attr, IBV_QP_STATE) < 0) {
		fprintf(stderr, "  [server] INTERRUPT modify(ERR) failed: %s\n",
			strerror(errno));
		tcp_send_msg(conn, "ERROR");
		return -1;
	}
	printf("  [server] INTERRUPT: responder QP -> ERR (mid-transfer fault)\n");
	tcp_send_msg(conn, CMD_DONE);
	return 0;
}

/* CHECK_FLAG (C1): return the raw 8B commit-flag slot value. The client compares
 * it against the expected magic|seq; a torn payload leaves the slot at its
 * INIT_C zero because the flag WR (posted after the payload WR) never executed. */
static void handle_check_flag(int conn)
{
	uint64_t flag = 0;
	if (res.buf && res.buf_size >= C_FLAG_OFFSET + 8)
		memcpy(&flag, (unsigned char *)res.buf + C_FLAG_OFFSET, 8);
	char resp[64];
	snprintf(resp, sizeof(resp), "FLAG:%llu", (unsigned long long)flag);
	printf("  [server] %s\n", resp);
	tcp_send_msg(conn, resp);
}

/* VERIFY_CRC <seq> (C2): parse the 16B header at offset 0, recompute crc32c over
 * the declared payload, and report valid/torn plus the recompute time (the O(len)
 * judging cost). Torn if the header did not fully land (seq mismatch / zero len /
 * impossible len) or the recomputed crc differs (payload tail is INIT_C zeros). */
static void handle_verify_crc(int conn, const char *args)
{
	unsigned long expected_seq = 0;
	sscanf(args, "%lu", &expected_seq);

	struct c2_header hdr;
	memset(&hdr, 0, sizeof(hdr));
	if (res.buf && res.buf_size >= (size_t)C2_HEADER_SIZE)
		memcpy(&hdr, res.buf, C2_HEADER_SIZE);

	int valid = 0;
	double judge_us = 0.0;
	if (hdr.seq == (uint32_t)expected_seq && hdr.len > 0 &&
	    hdr.len <= LARGE_WRITE_LEN &&
	    res.buf_size >= (size_t)C2_HEADER_SIZE + hdr.len) {
		struct timespec c0, c1;
		clock_gettime(CLOCK_MONOTONIC, &c0);
		uint32_t got = crc32c((unsigned char *)res.buf + C2_HEADER_SIZE,
				      hdr.len);
		clock_gettime(CLOCK_MONOTONIC, &c1);
		judge_us = elapsed_us(&c0, &c1);
		valid = (got == hdr.crc);
	}
	char resp[96];
	snprintf(resp, sizeof(resp), "CRC:valid=%d:judge_us=%.3f", valid, judge_us);
	printf("  [server] %s (seq=%u len=%u)\n", resp, hdr.seq, hdr.len);
	tcp_send_msg(conn, resp);
}

/* RECOVER_C: QP-only recovery over the live socket (same MR/buffer kept). Mirror
 * of handle_recover_ab minus the AB bounds line; lockstep with the client. */
static int handle_recover_c(int conn)
{
	if (!res.qp) {
		fprintf(stderr, "  [server] RECOVER_C: no QP\n");
		return -1;
	}

	struct ibv_wc wc;
	while (ibv_poll_cq(res.cq, 1, &wc) > 0)
		; /* drain */

	struct ibv_qp_attr attr = { .qp_state = IBV_QPS_RESET };
	if (ibv_modify_qp(res.qp, &attr, IBV_QP_STATE) < 0) {
		fprintf(stderr, "  [server] RECOVER_C reset failed: %s\n",
			strerror(errno));
		return -1;
	}

	res.local_info.psn = rand() & 0xFFFFFF;

	tcp_exchange_qp_info(conn, &res.local_info, &res.remote_info, 1);

	if (connect_qp(&res, 1, 7, 7, 14) < 0) {
		fprintf(stderr, "  [server] RECOVER_C reconnect failed\n");
		return -1;
	}

	printf("  [server] C QP recovered (QP-only)\n");
	tcp_send_msg(conn, CMD_READY);
	return 0;
}

/* CHECK_C <off> <len>: ground-truth scan of the payload region [off, off+len).
 * The payload is a non-zero pattern and INIT_C zeroed the rest, and the silent
 * partial is a PMTU-granular prefix, so the contiguous non-zero run from `off`
 * equals the number of payload bytes that actually landed (the boundary). Also
 * report total non-zero and last non-zero offset as diagnostics. */
static void handle_check_c(int conn, const char *args)
{
	long off = 0, len = 0;
	sscanf(args, "%ld %ld", &off, &len);

	unsigned char *buf = (unsigned char *)res.buf;
	long n = (long)res.buf_size;
	if (off < 0) off = 0;
	if (off > n) off = n;
	long end = off + len;
	if (end > n) end = n;

	long landed = 0;
	while (off + landed < end && buf[off + landed] != 0)
		landed++;

	long nonzero = 0, last = -1;
	for (long i = off; i < end; i++) {
		if (buf[i] != 0) {
			nonzero++;
			last = i - off;
		}
	}

	char resp[128];
	snprintf(resp, sizeof(resp), "CHECK_C:landed=%ld:nonzero=%ld:last=%ld",
		 landed, nonzero, last);
	printf("  [server] %s\n", resp);
	tcp_send_msg(conn, resp);
}

static void run_server(void)
{
	/* Optional bind IP via env RDMA_BIND (default INADDR_ANY). Lets the
	 * swap experiment pin the control socket to this node's RDMA subnet IP;
	 * unset preserves the original wide-open listen. */
	const char *bind_ip = getenv("RDMA_BIND");
	int listen_sock = tcp_listen_bind(TCP_CTRL_PORT, bind_ip);
	if (listen_sock < 0) {
		fprintf(stderr, "Failed to listen on port %d (bind=%s)\n",
			TCP_CTRL_PORT, (bind_ip && bind_ip[0]) ? bind_ip : "ANY");
		exit(1);
	}
	printf("Server listening on port %d (bind=%s)\n",
	       TCP_CTRL_PORT, (bind_ip && bind_ip[0]) ? bind_ip : "ANY");

	while (1) {
		struct sockaddr_in client_addr;
		socklen_t len = sizeof(client_addr);
		int conn = accept(listen_sock, (struct sockaddr *)&client_addr, &len);
		if (conn < 0) {
			perror("accept");
			continue;
		}
		/* Nagle+delayed-ACK가 lockstep 왕복(RECOVER_AB의 qp_info 재교환 등)에
		 * 40ms floor를 만든다 — 06_recovery 서버들과 동일하게 비활성화.
		 * (기존 ab_recovery.csv의 A recover 42.6ms가 이 아티팩트였음, 2026-07-15) */
		int flag = 1;
		setsockopt(conn, IPPROTO_TCP, TCP_NODELAY, &flag, sizeof(flag));
		printf("Client connected\n");
		ctrl_sock = conn;

		char cmd[256];
		while (tcp_recv_msg(conn, cmd, sizeof(cmd)) > 0) {
			printf("[server] cmd: %s\n", cmd);

			if (strncmp(cmd, CMD_SETUP_SEND, strlen(CMD_SETUP_SEND)) == 0) {
				if (handle_setup_send_recv(conn) < 0)
					fprintf(stderr, "setup_send_recv failed\n");

			} else if (strncmp(cmd, CMD_SETUP_NOREMOTE, strlen(CMD_SETUP_NOREMOTE)) == 0) {
				if (handle_setup_no_remote_write(conn) < 0)
					fprintf(stderr, "setup_no_remote failed\n");

			} else if (strncmp(cmd, CMD_SETUP_BOUNDARY, strlen(CMD_SETUP_BOUNDARY)) == 0) {
				if (handle_setup_boundary(conn) < 0)
					fprintf(stderr, "setup_boundary failed\n");

			} else if (strncmp(cmd, CMD_SETUP_AB, strlen(CMD_SETUP_AB)) == 0) {
				if (handle_setup_ab(conn, cmd + strlen(CMD_SETUP_AB) + 1) < 0)
					fprintf(stderr, "setup_ab failed\n");

			} else if (strcmp(cmd, CMD_RECOVER_AB) == 0) {
				if (handle_recover_ab(conn) < 0)
					fprintf(stderr, "recover_ab failed\n");

			} else if (strcmp(cmd, CMD_INIT_AB) == 0) {
				handle_init_ab(conn);

			} else if (strncmp(cmd, CMD_CHECK_AB, strlen(CMD_CHECK_AB)) == 0) {
				handle_check_ab(conn, cmd + strlen(CMD_CHECK_AB) + 1);

			} else if (strcmp(cmd, CMD_SETUP_C) == 0) {
				if (handle_setup_c(conn) < 0)
					fprintf(stderr, "setup_c failed\n");

			} else if (strcmp(cmd, CMD_INIT_C) == 0) {
				handle_init_c(conn);

			} else if (strcmp(cmd, CMD_INTERRUPT) == 0) {
				if (handle_interrupt(conn) < 0)
					fprintf(stderr, "interrupt failed\n");

			} else if (strcmp(cmd, CMD_CHECK_FLAG) == 0) {
				handle_check_flag(conn);

			} else if (strncmp(cmd, CMD_VERIFY_CRC, strlen(CMD_VERIFY_CRC)) == 0) {
				handle_verify_crc(conn, cmd + strlen(CMD_VERIFY_CRC) + 1);

			} else if (strcmp(cmd, CMD_RECOVER_C) == 0) {
				if (handle_recover_c(conn) < 0)
					fprintf(stderr, "recover_c failed\n");

			} else if (strncmp(cmd, CMD_CHECK_C, strlen(CMD_CHECK_C)) == 0) {
				handle_check_c(conn, cmd + strlen(CMD_CHECK_C) + 1);

			} else if (strncmp(cmd, CMD_SETUP, strlen(CMD_SETUP)) == 0) {
				if (handle_setup_normal(conn) < 0)
					fprintf(stderr, "setup failed\n");

			} else if (strncmp(cmd, CMD_INJECT, strlen(CMD_INJECT)) == 0) {
				char *arg = cmd + strlen(CMD_INJECT) + 1;
				if (handle_inject(conn, arg) < 0)
					fprintf(stderr, "inject failed\n");

			} else if (strcmp(cmd, CMD_INIT_BUFFER) == 0) {
				handle_init_buffer(conn);

			} else if (strncmp(cmd, CMD_CHECK_BUFFER, strlen(CMD_CHECK_BUFFER)) == 0) {
				handle_check_buffer(conn, cmd + strlen(CMD_CHECK_BUFFER) + 1);

			} else if (strcmp(cmd, CMD_CLEANUP) == 0) {
				cleanup_rdma(&res);
				printf("  [server] RDMA resources cleaned up\n");
				tcp_send_msg(conn, CMD_DONE);

			} else if (strcmp(cmd, CMD_QUERY_STATE) == 0) {
				if (!res.qp) {
					tcp_send_msg(conn, "QP_STATE=-1");
				} else {
					struct ibv_qp_attr qattr;
					struct ibv_qp_init_attr qinit;
					if (ibv_query_qp(res.qp, &qattr,
							 IBV_QP_STATE, &qinit))
						tcp_send_msg(conn, "QP_STATE=-2");
					else {
						char resp[32];
						snprintf(resp, sizeof(resp),
							 "QP_STATE=%d",
							 qattr.qp_state);
						tcp_send_msg(conn, resp);
					}
				}

			} else if (strcmp(cmd, CMD_SHUTDOWN) == 0) {
				cleanup_rdma(&res);
				tcp_send_msg(conn, CMD_DONE);
				close(conn);
				close(listen_sock);
				printf("Server shutting down\n");
				return;

			} else {
				fprintf(stderr, "Unknown command: %s\n", cmd);
				tcp_send_msg(conn, "ERROR");
			}
		}

		printf("Client disconnected\n");
		cleanup_rdma(&res);
		close(conn);
		ctrl_sock = -1;
	}
}

int main(void)
{
	srand(time(NULL));
	run_server();
	return 0;
}
