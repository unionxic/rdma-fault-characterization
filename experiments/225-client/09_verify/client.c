/*
 * verify/client.c — rdma_fault 분류 라이브러리 통합 검증용 client (225)
 *
 * 실제 RDMA 연결에서 5개 fault를 차례로 일으키고, 각 에러 CQE를 라이브러리의
 * rdma_poll로 받아 (error_class, action, peer) + vendor_err가 분류표의 기대값과
 * 일치하는지 대조한다.
 *
 * test_classify(가짜 ibv_wc 단위테스트)와의 차이: 여기서는 하드웨어가 실제로
 * 만든 CQE를 검증한다. 즉 "분류표가 옳다"가 아니라 "라이브러리가 실 CQ에 끼워져
 * 돌 때 실제 NIC의 (status, vendor_err)를 분류표대로 분류한다"는 통합 동작을
 * 확인한다. vendor_err(0x53/0x87/0x88/0x8a/0x81)가 기대대로 나오는지도 함께 본다.
 *
 * 사용: ./client          (server는 224에서 먼저 실행)
 * 출력: 시나리오별 PASS/FAIL 표 + 요약. 모두 PASS면 exit 0.
 */
#include "../05_counter_mapping/common.h"
#include "../07_fault_classify/rdma_fault.h"

#define MR_FULL    (IBV_ACCESS_LOCAL_WRITE | IBV_ACCESS_REMOTE_WRITE | \
		    IBV_ACCESS_REMOTE_READ)
#define CQ_TIMEOUT_MS  12000   /* RETRY_EXC detection(~3.7s) 여유 */

/* server.c와 동일 정의 */
#define CMD_SETUP_NORMAL   "SETUP_NORMAL"
#define CMD_SETUP_NORECV   "SETUP_NORECV"
#define CMD_SETUP_NOPERM   "SETUP_NOPERM"
#define CMD_INJECT_QP_ERR  "INJECT_QP_ERR"

/* fault 주입 방법 */
enum inject_kind {
	INJ_SEND,            /* SEND (RNR: recv 없음 / RETRY: server QP ERR) */
	INJ_WRITE,           /* 정상 rkey RDMA WRITE (REM_INV_REQ: MR 권한 부족) */
	INJ_WRITE_BADRKEY,   /* invalid rkey RDMA WRITE (REM_ACCESS) */
	INJ_WRITE_OVERSGE,   /* local SGE length > MR (LOC_PROT) */
};

struct vscenario {
	const char *name;
	const char *setup_cmd;
	int inject_qp_err;       /* 연결 후 server QP를 ERR로 (RETRY) */
	int rnr_retry;           /* connect 시 rnr_retry (RNR=0, 그 외 7) */
	int cli_remote_write;    /* client QP access의 REMOTE 권한 — REM_INV_REQ(0x8a) 유발에 필요 */
	enum inject_kind kind;
	/* 분류표 기대값 */
	enum rdma_error_class     want_class;
	enum rdma_recovery_action want_act;
	enum rdma_peer_liveness   want_peer;
	unsigned                  want_vendor;  /* 기대 vendor_err */
};

static struct vscenario scen[] = {
	{ "LOC_PROT (oversize SGE)",  CMD_SETUP_NORMAL, 0, 7, 0, INJ_WRITE_OVERSGE,
	  RDMA_CLASS_LOCAL_PROT,  RDMA_ACT_NOTIFY_BUG,     RDMA_PEER_NA,      0x53 },
	{ "RNR_RETRY_EXC",            CMD_SETUP_NORECV, 0, 0, 0, INJ_SEND,
	  RDMA_CLASS_RNR,         RDMA_ACT_QP_RECOVERY,    RDMA_PEER_ALIVE,   0x87 },
	{ "REM_ACCESS (bad rkey)",    CMD_SETUP_NORMAL, 0, 7, 0, INJ_WRITE_BADRKEY,
	  RDMA_CLASS_REM_ACCESS,  RDMA_ACT_QP_RECOVERY_MR, RDMA_PEER_ALIVE,   0x88 },
	{ "REM_INV_REQ (MR noperm)",  CMD_SETUP_NOPERM, 0, 7, 1, INJ_WRITE,
	  RDMA_CLASS_REM_INV_REQ, RDMA_ACT_QP_RECOVERY_MR, RDMA_PEER_ALIVE,   0x8a },
	{ "RETRY_EXC (server QP ERR)",CMD_SETUP_NORMAL, 1, 7, 0, INJ_SEND,
	  RDMA_CLASS_TIMEOUT,     RDMA_ACT_PROBE_PEER,     RDMA_PEER_UNKNOWN, 0x81 },
};

static int wait_ack(int sock, const char *expected)
{
	char buf[64];
	if (tcp_recv_msg(sock, buf, sizeof(buf)) < 0) {
		fprintf(stderr, "ERROR: tcp_recv_msg failed waiting for %s\n",
			expected);
		return -1;
	}
	if (strcmp(buf, expected) != 0) {
		fprintf(stderr, "ERROR: expected '%s', got '%s'\n", expected, buf);
		return -1;
	}
	return 0;
}

/* fault를 실제로 주입한다. 반환: ibv_post_* 반환값(0=성공 post) */
static int do_inject(struct rdma_res *res, enum inject_kind kind)
{
	switch (kind) {
	case INJ_SEND:
		return post_send(res);
	case INJ_WRITE:
		return post_rdma_write(res, NULL);
	case INJ_WRITE_BADRKEY:
		/* 원격 rkey를 임의값으로 위조 → responder가 MR 못 찾음 → REM_ACCESS */
		res->remote_info.rkey = 0xdeadbeef;
		return post_rdma_write(res, NULL);
	case INJ_WRITE_OVERSGE: {
		/* local SGE length(8192) > MR_SIZE(4096) → local protection error */
		struct ibv_sge sge = {
			.addr   = (uint64_t)res->buf,
			.length = MR_SIZE * 2,
			.lkey   = res->mr->lkey,
		};
		return post_rdma_write(res, &sge);
	}
	}
	return -1;
}

/*
 * 라이브러리 rdma_poll을 blocking으로 감싸 에러 CQE 하나를 받아 분류한다.
 * 반환: 1=분류 1건, 0=timeout, <0=poll 에러.
 */
static int rdma_poll_block(struct rdma_res *res, struct ibv_wc *wc,
			   struct rdma_fault_info *fi, int timeout_ms)
{
	struct timespec start, now;
	clock_gettime(CLOCK_MONOTONIC, &start);
	while (1) {
		int n = rdma_poll(res->cq, 1, wc, fi);
		if (n != 0)
			return n;   /* >0: 분류됨, <0: 에러 */
		clock_gettime(CLOCK_MONOTONIC, &now);
		long ms = (now.tv_sec - start.tv_sec) * 1000 +
			  (now.tv_nsec - start.tv_nsec) / 1000000;
		if (timeout_ms > 0 && ms > timeout_ms)
			return 0;
	}
}

/* 한 시나리오 실행. *pass에 PASS(1)/FAIL(0) 기록. 반환: 0=정상 진행, -1=프로토콜 실패 */
static int run_scenario(int sock, struct vscenario *s, int *pass)
{
	struct rdma_res res;
	memset(&res, 0, sizeof(res));
	*pass = 0;

	/* 1. server에 setup 요청 → 자원 생성됨(#1) */
	if (tcp_send_msg(sock, s->setup_cmd) < 0)
		return -1;
	if (wait_ack(sock, CMD_READY) < 0)
		return -1;

	/* 2. client 자원 생성 (MR은 full access) */
	if (setup_rdma(&res, 1, MR_FULL, 7, 7, 14) < 0) {
		fprintf(stderr, "ERROR: client setup_rdma failed\n");
		return -1;
	}

	/* 3. QP info 교환 (client 먼저 보냄) */
	if (tcp_exchange_qp_info(sock, &res.local_info, &res.remote_info, 0) < 0) {
		cleanup_rdma(&res);
		return -1;
	}

	/* 4. connect (RNR이면 rnr_retry=0으로 즉시 실패) */
	if (connect_qp(&res, s->cli_remote_write, 7, s->rnr_retry, 14) < 0) {
		cleanup_rdma(&res);
		return -1;
	}

	/* 5. server 연결 완료 대기(#2) */
	if (wait_ack(sock, CMD_READY) < 0) {
		cleanup_rdma(&res);
		return -1;
	}

	/* 6. RETRY: server QP를 ERR로 만든다 */
	if (s->inject_qp_err) {
		if (tcp_send_msg(sock, CMD_INJECT_QP_ERR) < 0 ||
		    wait_ack(sock, CMD_READY) < 0) {
			cleanup_rdma(&res);
			return -1;
		}
	}

	/* 7. fault 주입 */
	int prc = do_inject(&res, s->kind);

	/* 8. 라이브러리로 poll + classify */
	struct ibv_wc wc;
	struct rdma_fault_info fi;
	memset(&fi, 0, sizeof(fi));
	int n = 0;
	if (prc == 0)
		n = rdma_poll_block(&res, &wc, &fi, CQ_TIMEOUT_MS);

	/* 9. 기대값 대조 */
	int got = (n > 0);
	int cmatch = got && fi.error_class == s->want_class &&
		     fi.action == s->want_act && fi.peer == s->want_peer;
	int vmatch = got && (s->want_vendor == 0 ||
			     fi.vendor_err == s->want_vendor);
	*pass = cmatch && vmatch;

	printf("[%s] %-28s\n", *pass ? "PASS" : "FAIL", s->name);
	if (prc != 0) {
		printf("       ibv_post 즉시 실패(rc=%d) — CQE 미발생\n", prc);
	} else if (!got) {
		printf("       에러 CQE 미수신 (n=%d, timeout?)\n", n);
	} else {
		printf("       got : status=%-2d vendor=0x%02x  %s / %s / peer=%s\n",
		       fi.wc_status, fi.vendor_err,
		       rdma_error_class_str(fi.error_class),
		       rdma_recovery_action_str(fi.action),
		       rdma_peer_liveness_str(fi.peer));
		printf("       want: %-21s vendor=0x%02x  %s / %s / peer=%s\n",
		       "", s->want_vendor,
		       rdma_error_class_str(s->want_class),
		       rdma_recovery_action_str(s->want_act),
		       rdma_peer_liveness_str(s->want_peer));
		printf("       cause: %s\n", fi.cause);
		if (!vmatch)
			printf("       NOTE: vendor_err 불일치 (got 0x%02x, want 0x%02x)\n",
			       fi.vendor_err, s->want_vendor);
	}
	fflush(stdout);

	/* 10. cleanup */
	tcp_send_msg(sock, CMD_CLEANUP);
	wait_ack(sock, CMD_DONE);
	cleanup_rdma(&res);
	return 0;
}

int main(void)
{
	srand(time(NULL));

	int sock = tcp_connect(RDMA_SERVER_IP, TCP_CTRL_PORT);
	if (sock < 0) {
		fprintf(stderr, "ERROR: cannot connect to server %s:%d\n",
			RDMA_SERVER_IP, TCP_CTRL_PORT);
		return 1;
	}
	fprintf(stderr, "Connected to verify server\n\n");

	printf("rdma_fault 분류 라이브러리 — 실제 연결 통합 검증\n");
	printf("(하드웨어가 만든 진짜 CQE를 rdma_poll로 받아 분류표와 대조)\n");
	printf("================================================================\n");

	int ntot = sizeof(scen) / sizeof(scen[0]);
	int npass = 0;
	for (int i = 0; i < ntot; i++) {
		int pass = 0;
		if (run_scenario(sock, &scen[i], &pass) < 0) {
			fprintf(stderr, "ERROR: scenario '%s' protocol failure\n",
				scen[i].name);
			/* 프로토콜 실패는 FAIL로 집계하고 계속 */
		}
		npass += pass;
	}

	printf("================================================================\n");
	printf("%s — %d/%d PASS\n", (npass == ntot) ? "ALL PASS" : "FAILED",
	       npass, ntot);

	tcp_send_msg(sock, CMD_SHUTDOWN);
	close(sock);
	return (npass == ntot) ? 0 : 1;
}
