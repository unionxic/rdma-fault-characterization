/*
 * verify_qp_state.c — NAK 이후 responder QP 상태 검증 (client 프로그램, 225에서 실행)
 *
 * IBA spec은 "Error NAK을 보낸 responder QP는 ERR로 전이한다"고 하지만, 실제
 * ConnectX-5가 그렇게 동작하는지 확인한다. NAK 4종(REM_INV_REQ, REM_ACCESS_RKEY, RNR_RETRY_EXC, REM_ACCESS_ADDR) + RETRY_EXC_QP_ERR에
 * 대해 fault 전/후 서버 QP 상태를 QUERY_STATE 명령으로 조회해서
 * RTS 유지 / ERR 전이 / 기타를 시나리오별로 집계한다.
 *
 * 실행: run_verify.sh (225에서). 결과: results/raw/qp_state_verify.csv
 * 주의: 현재 저장된 데이터는 N=1 (재측정 필요 — 3_다음_계획.md 참고).
 */
#include "common.h"

static struct rdma_res res;
static int ctrl_sock = -1;
static int num_trials = 10;

static const enum scenario test_scenarios[] = {
	REM_INV_REQ,
	REM_ACCESS_RKEY,
	RNR_RETRY_EXC,
	REM_ACCESS_ADDR,
	RETRY_EXC_QP_ERR,
};
#define NUM_SCENARIOS 5

struct scenario_summary {
	enum scenario sc;
	int success;
	int before_rts;
	int after_rts;
	int after_err;
	int after_other;
};

static const char *qp_state_str(int state)
{
	switch (state) {
	case IBV_QPS_RESET: return "RESET";
	case IBV_QPS_INIT:  return "INIT";
	case IBV_QPS_RTR:   return "RTR";
	case IBV_QPS_RTS:   return "RTS";
	case IBV_QPS_SQD:   return "SQD";
	case IBV_QPS_SQE:   return "SQE";
	case IBV_QPS_ERR:   return "ERR";
	default:            return "???";
	}
}

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

static int query_server_qp_state(void)
{
	tcp_send_msg(ctrl_sock, CMD_QUERY_STATE);
	char resp[256];
	if (tcp_recv_msg(ctrl_sock, resp, sizeof(resp)) <= 0)
		return -1;
	int state = -1;
	sscanf(resp, "QP_STATE=%d", &state);
	return state;
}

static int setup_for_scenario(enum scenario sc)
{
	int access = IBV_ACCESS_LOCAL_WRITE | IBV_ACCESS_REMOTE_WRITE |
		     IBV_ACCESS_REMOTE_READ;
	int retry = 7, rnr_retry = 7, timeout = 14;
	int use_send = 0;
	const char *setup_cmd = CMD_SETUP;

	switch (sc) {
	case REM_INV_REQ:
		setup_cmd = CMD_SETUP_NOREMOTE;
		break;
	case RNR_RETRY_EXC:
		use_send = 1;
		rnr_retry = 0;
		setup_cmd = CMD_SETUP_SEND;
		break;
	case RETRY_EXC_QP_ERR:
		timeout = 8;
		break;
	default:
		break;
	}

	if (setup_rdma(&res, use_send, access, retry, rnr_retry, timeout) < 0)
		return -1;

	tcp_send_msg(ctrl_sock, setup_cmd);
	tcp_exchange_qp_info(ctrl_sock, &res.local_info, &res.remote_info, 0);

	int remote_write = (sc != REM_INV_REQ && sc != RNR_RETRY_EXC);
	if (connect_qp(&res, remote_write, retry, rnr_retry, timeout) < 0)
		return -1;

	char resp[256];
	if (tcp_recv_msg(ctrl_sock, resp, sizeof(resp)) <= 0 ||
	    strcmp(resp, CMD_READY) != 0)
		return -1;

	return 0;
}

static int verify_connection(void)
{
	if (post_rdma_write(&res, NULL) < 0)
		return -1;
	struct ibv_wc wc;
	if (poll_cq_block(res.cq, &wc, 5000) <= 0)
		return -1;
	if (wc.status != IBV_WC_SUCCESS)
		return -1;
	printf("  Connection verified\n");
	return 0;
}

static int inject_and_post(enum scenario sc)
{
	switch (sc) {
	case REM_INV_REQ:
		return post_rdma_write(&res, NULL);

	case REM_ACCESS_RKEY: {
		struct ibv_sge s = {
			.addr = (uint64_t)res.buf,
			.length = 64,
			.lkey = res.mr->lkey,
		};
		struct ibv_send_wr wr = {
			.wr_id = 1,
			.sg_list = &s,
			.num_sge = 1,
			.opcode = IBV_WR_RDMA_WRITE,
			.send_flags = IBV_SEND_SIGNALED,
			.wr.rdma = {
				.remote_addr = res.remote_info.raddr,
				.rkey = res.remote_info.rkey + 0x100,
			},
		};
		struct ibv_send_wr *bad;
		return ibv_post_send(res.qp, &wr, &bad);
	}

	case RNR_RETRY_EXC:
		return post_send(&res);

	case REM_ACCESS_ADDR: {
		struct ibv_sge s = {
			.addr = (uint64_t)res.buf,
			.length = 64,
			.lkey = res.mr->lkey,
		};
		struct ibv_send_wr wr = {
			.wr_id = 1,
			.sg_list = &s,
			.num_sge = 1,
			.opcode = IBV_WR_RDMA_WRITE,
			.send_flags = IBV_SEND_SIGNALED,
			.wr.rdma = {
				.remote_addr = res.remote_info.raddr +
					       MR_SIZE + 4096,
				.rkey = res.remote_info.rkey,
			},
		};
		struct ibv_send_wr *bad;
		return ibv_post_send(res.qp, &wr, &bad);
	}

	case RETRY_EXC_QP_ERR: {
		char cmd[64];
		snprintf(cmd, sizeof(cmd), "%s %d",
			 CMD_INJECT, RETRY_EXC_QP_ERR);
		send_cmd_wait(ctrl_sock, cmd, CMD_DONE);
		return post_rdma_write(&res, NULL);
	}

	default:
		return -1;
	}
}

static int run_trial(enum scenario sc, int trial, FILE *csv,
		     struct scenario_summary *summary)
{
	printf("\n--- %s trial %d ---\n", scenario_names[sc], trial);

	if (setup_for_scenario(sc) < 0) {
		fprintf(stderr, "  Setup failed\n");
		return -1;
	}

	if (sc != REM_INV_REQ && sc != RNR_RETRY_EXC) {
		if (verify_connection() < 0) {
			cleanup_rdma(&res);
			return -1;
		}
	}

	int state_before = query_server_qp_state();
	printf("  Server QP before: %s (%d)\n",
	       qp_state_str(state_before), state_before);

	struct timespec t0, t1;
	clock_gettime(CLOCK_MONOTONIC, &t0);

	if (inject_and_post(sc) < 0) {
		fprintf(stderr, "  inject_and_post failed\n");
		cleanup_rdma(&res);
		return -1;
	}

	int timeout_ms = (sc == RETRY_EXC_QP_ERR) ? 60000 : 30000;
	struct ibv_wc wc;
	int n = poll_cq_block(res.cq, &wc, timeout_ms);
	clock_gettime(CLOCK_MONOTONIC, &t1);

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

	int state_after = query_server_qp_state();
	printf("  Server QP after:  %s (%d)\n",
	       qp_state_str(state_after), state_after);

	fprintf(csv, "%s,%d,%d,0x%x,%.0f,%s,%s\n",
		scenario_names[sc], trial, wc.status, wc.vendor_err,
		latency, qp_state_str(state_before),
		qp_state_str(state_after));

	summary->success++;
	if (state_before == IBV_QPS_RTS)
		summary->before_rts++;
	if (state_after == IBV_QPS_RTS)
		summary->after_rts++;
	else if (state_after == IBV_QPS_ERR)
		summary->after_err++;
	else
		summary->after_other++;

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

	FILE *csv = fopen("results/raw/qp_state_verify.csv", "w");
	if (!csv) {
		perror("fopen csv");
		close(ctrl_sock);
		return 1;
	}
	fprintf(csv, "scenario,trial,wc_status,vendor_err,latency_us,"
		     "qp_before,qp_after\n");

	struct scenario_summary sums[NUM_SCENARIOS] = {};

	for (int s = 0; s < NUM_SCENARIOS; s++) {
		enum scenario sc = test_scenarios[s];
		sums[s].sc = sc;

		printf("\n========================================\n");
		printf("  %s\n", scenario_names[sc]);
		printf("========================================\n");

		for (int t = 0; t < num_trials; t++) {
			if (run_trial(sc, t, csv, &sums[s]) < 0)
				fprintf(stderr, "  Trial %d failed\n", t);
		}
	}

	send_cmd_wait(ctrl_sock, CMD_SHUTDOWN, CMD_DONE);
	close(ctrl_sock);
	fclose(csv);

	printf("\n");
	printf("============================================================\n");
	printf("  Server QP State After Error — Verification Results\n");
	printf("============================================================\n");
	printf("%-24s %-12s %-12s %s\n",
	       "Scenario", "Before", "After", "N");
	printf("------------------------------------------------------------\n");

	for (int s = 0; s < NUM_SCENARIOS; s++) {
		struct scenario_summary *m = &sums[s];
		int n = m->success;

		char after_str[32];
		if (m->after_rts == n)
			snprintf(after_str, sizeof(after_str),
				 "RTS(%d/%d)", m->after_rts, n);
		else if (m->after_err == n)
			snprintf(after_str, sizeof(after_str),
				 "ERR(%d/%d)", m->after_err, n);
		else
			snprintf(after_str, sizeof(after_str),
				 "RTS=%d ERR=%d", m->after_rts, m->after_err);

		const char *note = "";
		if (m->sc == RNR_RETRY_EXC)
			note = "  (RNR=flow ctrl)";
		else if (m->sc == RETRY_EXC_QP_ERR)
			note = "  (control)";

		printf("%-24s RTS(%d/%d)    %-12s %d%s\n",
		       scenario_names[m->sc],
		       m->before_rts, n, after_str, n, note);
	}

	printf("------------------------------------------------------------\n");
	printf("IBA spec predicts: REM_INV_REQ/REM_ACCESS_RKEY/REM_ACCESS_ADDR → ERR, RNR_RETRY_EXC → RTS, RETRY_EXC_QP_ERR → ERR\n");
	printf("Results: results/raw/qp_state_verify.csv\n");

	return 0;
}
