/*
 * verify_partial_write.c — MR 경계 침범(REM_ACCESS_ERR) partial write 검증
 * (client 프로그램, 225에서 실행)
 *
 * 서버 MR(4096B) 경계를 넘도록 offset/write_len을 조합한 6개 케이스로 WRITE를
 * 쏘고, 두 값이 일치하는지 확인한다:
 *   (1) 요청자가 자기 정보만으로 복원한 값: sq_psn_delta × PMTU(1024)
 *   (2) 서버가 CHECK_BUFFER로 자기 버퍼를 스캔한 실제 기록 바이트 (ground truth)
 *
 * 핵심 결론(측정 완료): partial write는 항상 whole-PMTU-packet 단위로 끊기며,
 * 요청자는 CQE + sq_psn만으로 "몇 바이트가 상대에 기록됐는지"를 복원할 수 있다.
 * 이 성질이 ab_recovery.c(전략 A)와 verify_interrupted_write.c의 전제가 된다.
 *
 * 실행: run_partial.sh (225에서). 결과: results/raw/partial_write_verify.csv
 */
#include "common.h"

static struct rdma_res res;
static int ctrl_sock = -1;
static int num_trials = 10;

struct test_case {
	const char *name;
	size_t offset;
	size_t write_len;
};

static const struct test_case cases[] = {
	{"single_pkt_cross",   MR_SIZE - 32,    64},
	{"multi_pkt_cross",    MR_SIZE - 2048,  4096},
	{"barely_1B_inside",   MR_SIZE - 1,     64},
	/* MTU(1024)-misaligned: MR-inside region is not a multiple of MTU.
	 * Tests whether sq_psn_delta*MTU still equals actual bytes written,
	 * i.e. whether partial write is always whole-MTU-packet granular. */
	{"unaligned_boundary", MR_SIZE - 2560,  3072},  /* in-MR avail 2560 */
	{"unaligned_offset",   MR_SIZE - 1536,  2048},  /* in-MR avail 1536 */
	{"three_pkt_partial",  MR_SIZE - 3072,  4096},  /* in-MR avail 3072 */
};
#define NUM_CASES 6

struct case_summary {
	int success;
	int no_write;
	int partial;
};

static int send_cmd_wait(int sock, const char *cmd, const char *expect)
{
	tcp_send_msg(sock, cmd);
	char resp[256];
	tcp_recv_msg(sock, resp, sizeof(resp));
	if (expect && strcmp(resp, expect) != 0) {
		fprintf(stderr, "Expected '%s', got '%s'\n", expect, resp);
		return -1;
	}
	return 0;
}

static int run_test(const struct test_case *tc, int trial, FILE *csv,
		    struct case_summary *summary)
{
	printf("\n--- %s trial %d ---\n", tc->name, trial);

	/* Server: boundary setup (8KB buf, 4KB MR) */
	tcp_send_msg(ctrl_sock, CMD_SETUP_BOUNDARY);

	/* Client: standard setup */
	int access = IBV_ACCESS_LOCAL_WRITE | IBV_ACCESS_REMOTE_WRITE |
		     IBV_ACCESS_REMOTE_READ;
	if (setup_rdma(&res, 0, access, 7, 7, 14) < 0)
		return -1;

	tcp_exchange_qp_info(ctrl_sock, &res.local_info,
			     &res.remote_info, 0);

	if (connect_qp(&res, 1, 7, 7, 14) < 0) {
		cleanup_rdma(&res);
		return -1;
	}

	char resp[256];
	if (tcp_recv_msg(ctrl_sock, resp, sizeof(resp)) <= 0 ||
	    strcmp(resp, CMD_READY) != 0) {
		cleanup_rdma(&res);
		return -1;
	}

	/* Verify connection with normal WRITE */
	if (post_rdma_write(&res, NULL) < 0) {
		cleanup_rdma(&res);
		return -1;
	}
	struct ibv_wc wc;
	if (poll_cq_block(res.cq, &wc, 5000) <= 0 ||
	    wc.status != IBV_WC_SUCCESS) {
		fprintf(stderr, "  Verify failed\n");
		cleanup_rdma(&res);
		return -1;
	}
	printf("  Connection verified\n");

	/* Zero server buffer */
	send_cmd_wait(ctrl_sock, CMD_INIT_BUFFER, CMD_DONE);

	/* Fill client buffer with 0xAA pattern */
	memset(res.buf, 0xAA, BUF_SIZE);

	/* Post boundary-crossing RDMA WRITE */
	struct ibv_sge sge = {
		.addr = (uint64_t)res.buf,
		.length = tc->write_len,
		.lkey = res.mr->lkey,
	};
	struct ibv_send_wr wr = {
		.wr_id = 1,
		.sg_list = &sge,
		.num_sge = 1,
		.opcode = IBV_WR_RDMA_WRITE,
		.send_flags = IBV_SEND_SIGNALED,
		.wr.rdma = {
			.remote_addr = res.remote_info.raddr + tc->offset,
			.rkey = res.remote_info.rkey,
		},
	};
	struct ibv_send_wr *bad;

	/* Requester-side SQ PSN before/after: reconstruct how far the
	 * multi-packet WRITE actually got, purely from the requester. */
	struct ibv_qp_attr qattr;
	struct ibv_qp_init_attr qinit;
	uint32_t psn_before = 0, psn_after = 0;
	if (ibv_query_qp(res.qp, &qattr, IBV_QP_SQ_PSN, &qinit) == 0)
		psn_before = qattr.sq_psn;

	struct timespec t0, t1;
	clock_gettime(CLOCK_MONOTONIC, &t0);
	ibv_post_send(res.qp, &wr, &bad);

	int n = poll_cq_block(res.cq, &wc, 30000);
	clock_gettime(CLOCK_MONOTONIC, &t1);

	if (ibv_query_qp(res.qp, &qattr, IBV_QP_SQ_PSN, &qinit) == 0)
		psn_after = qattr.sq_psn;
	uint32_t psn_delta = (psn_after - psn_before) & 0xFFFFFF;

	if (n <= 0) {
		fprintf(stderr, "  Poll timeout\n");
		cleanup_rdma(&res);
		return -1;
	}

	double latency = elapsed_us(&t0, &t1);
	printf("  CQE: status=%d (%s) vendor_err=0x%x latency=%.0fus\n",
	       wc.status, ibv_wc_status_str(wc.status),
	       wc.vendor_err, latency);

	usleep(100000);

	/* Check server buffer for modifications */
	char check_cmd[64];
	snprintf(check_cmd, sizeof(check_cmd), "%s %zu %zu",
		 CMD_CHECK_BUFFER, tc->offset, tc->write_len);
	tcp_send_msg(ctrl_sock, check_cmd);

	char buf_resp[256];
	tcp_recv_msg(ctrl_sock, buf_resp, sizeof(buf_resp));

	int within_mod = 0, within_total = 0;
	int beyond_mod = 0, beyond_total = 0;
	int last_mod = -1;
	sscanf(buf_resp, "PARTIAL:%d/%d:%d/%d:last=%d",
	       &within_mod, &within_total, &beyond_mod, &beyond_total,
	       &last_mod);

	const char *result = (within_mod == 0) ? "NO_WRITE" : "PARTIAL_WRITE";

	printf("  Buffer: within_mr=%d/%d modified, beyond_mr=%d/%d → %s\n",
	       within_mod, within_total, beyond_mod, beyond_total, result);
	printf("  Requester: byte_len=%u sq_psn %u->%u (delta %u pkts) "
	       "last_mod_off=%d\n",
	       wc.byte_len, psn_before, psn_after, psn_delta, last_mod);

	fprintf(csv, "%s,%d,%d,0x%x,%.0f,%zu,%zu,%d,%d,%d,%d,%s,"
		"%u,%u,%u,%u,%d\n",
		tc->name, trial, wc.status, wc.vendor_err, latency,
		tc->offset, tc->write_len,
		within_mod, within_total, beyond_mod, beyond_total, result,
		wc.byte_len, psn_before, psn_after, psn_delta, last_mod);

	summary->success++;
	if (within_mod == 0)
		summary->no_write++;
	else
		summary->partial++;

	send_cmd_wait(ctrl_sock, CMD_CLEANUP, CMD_DONE);
	cleanup_rdma(&res);
	return 0;
}

int main(int argc, char **argv)
{
	if (argc >= 2)
		num_trials = atoi(argv[1]);

	srand(time(NULL));

	ctrl_sock = tcp_connect(RDMA_SERVER_IP, TCP_CTRL_PORT);
	if (ctrl_sock < 0) {
		fprintf(stderr, "Cannot connect to server\n");
		return 1;
	}

	FILE *csv = fopen("results/raw/partial_write_verify.csv", "w");
	if (!csv) {
		perror("fopen csv");
		close(ctrl_sock);
		return 1;
	}
	fprintf(csv, "test,trial,wc_status,vendor_err,latency_us,"
		     "offset,write_len,"
		     "within_mod,within_total,beyond_mod,beyond_total,"
		     "result,byte_len,sq_psn_before,sq_psn_after,"
		     "sq_psn_delta,last_mod\n");

	struct case_summary sums[NUM_CASES] = {};

	for (int c = 0; c < NUM_CASES; c++) {
		const struct test_case *tc = &cases[c];

		printf("\n========================================\n");
		printf("  %s (offset=%zu, len=%zu)\n",
		       tc->name, tc->offset, tc->write_len);
		printf("  Within MR: %zu bytes, Beyond MR: %zu bytes\n",
		       MR_SIZE - tc->offset,
		       tc->offset + tc->write_len - MR_SIZE);
		printf("========================================\n");

		for (int t = 0; t < num_trials; t++) {
			if (run_test(tc, t, csv, &sums[c]) < 0)
				fprintf(stderr, "  Trial %d failed\n", t);
		}
	}

	send_cmd_wait(ctrl_sock, CMD_SHUTDOWN, CMD_DONE);
	close(ctrl_sock);
	fclose(csv);

	printf("\n");
	printf("============================================================\n");
	printf("  Partial Write Boundary Test Results\n");
	printf("============================================================\n");
	printf("%-20s %6s %6s  %-10s %-10s %s\n",
	       "Test", "Offset", "Len", "In-MR", "Beyond", "Result");
	printf("------------------------------------------------------------\n");

	for (int c = 0; c < NUM_CASES; c++) {
		const struct test_case *tc = &cases[c];
		struct case_summary *s = &sums[c];
		int n = s->success;

		printf("%-20s %6zu %6zu  %zu/%zuB    %zu/%zuB   %s(%d/%d)\n",
		       tc->name,
		       tc->offset, tc->write_len,
		       MR_SIZE - tc->offset, tc->write_len,
		       tc->offset + tc->write_len - MR_SIZE, tc->write_len,
		       s->no_write == n ? "NO_WRITE" : "PARTIAL",
		       s->no_write == n ? s->no_write : s->partial, n);
	}

	printf("------------------------------------------------------------\n");
	printf("NO_WRITE = NIC checks full range before writing (safe)\n");
	printf("PARTIAL  = NIC writes per-packet, partial data in MR\n");
	printf("Results: results/raw/partial_write_verify.csv\n");

	return 0;
}
