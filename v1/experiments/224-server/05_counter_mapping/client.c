/*
 * client.c — fault fingerprint requester (기본: 225에서 실행)
 *
 * 11개 fault 시나리오(common.h의 enum scenario)를 하나씩 재현한다.
 * 시나리오마다 QP를 새로 만들고(setup_for_scenario: 시나리오별 access flag /
 * retry / timeout 조정), 정상 WRITE로 연결을 확인한 뒤 fault를 주입한다
 * (inject_and_post: 잘못된 SGE/lkey/rkey, QP→ERR, 프로세스 kill, link down 등).
 *
 * trial 1회의 흐름:
 *   로컬 sysfs 카운터 + 상대 노드 counter_daemon 스냅샷(before)
 *   → fault 주입 → 에러 CQE 관측 (wc_status + vendor_err = fingerprint 재료)
 *   → 스냅샷(after) → 델타를 results/raw/<시나리오>.csv 로 기록.
 * vendor_err는 NIC 세대 swap 비교용으로 results/raw/vendor_err_summary.csv 에도
 * append한다 (REQUESTER_NIC 환경변수로 라벨링).
 *
 * RETRY_EXC_PROC_KILL(kill)/RETRY_EXC_LINK_DOWN(link down)는 이 프로세스가 못 하므로 /tmp/ready_to_inject 파일로
 * orchestration 스크립트(run_experiment.sh)에 신호를 보내 대신 수행하게 한다.
 *
 * swap 실험(run_swap.sh)에서는 같은 소스가 224에서 requester로 돌며,
 * argv[3] 또는 env RDMA_SERVER로 responder IP를 바꾼다.
 *
 * 사용법: ./client <scenario_id|all> [num_trials] [server_ip]
 */
/* (224 사본 주의: run_swap.sh 전용 requester. 225 사본과 달리 resolve_ib_dev_name()
 * 호출이 없다 — 224는 장치명이 mlx5_0로 고정이라 필요 없기 때문.) */
#include "common.h"

/* ------------------------------------------------------------------ */
/*  Globals                                                           */
/* ------------------------------------------------------------------ */

static struct rdma_res res;
static int ctrl_sock = -1;
static int num_trials = 10;

/* Server (responder) RDMA IP this requester connects to.
 * Default keeps the normal experiment (225->224) intact. Override for the
 * swap experiment (224->225) via argv[3] or env RDMA_SERVER. Resolved in
 * main() before any TCP connect. */
static const char *server_ip = RDMA_SERVER_IP;

/* Human label for the requester NIC generation (e.g. "CX5" / "CX6").
 * Printed verbatim into the vendor_err summary CSV so a swap run can be
 * diffed against the baseline. We do NOT infer it from the device name —
 * the operator passes it via env REQUESTER_NIC. Default "unknown". */
static const char *requester_nic = "unknown";

/* ------------------------------------------------------------------ */
/*  Server communication helpers                                      */
/* ------------------------------------------------------------------ */

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

/* ------------------------------------------------------------------ */
/*  vendor_err summary CSV (swap-comparison friendly)                 */
/* ------------------------------------------------------------------ */

/* Append one row to results/raw/vendor_err_summary.csv with vendor_err as a
 * first-class column (the per-scenario counter CSV only carries it inside a
 * '#' comment). This file accumulates across scenarios/runs so a swap run and
 * a baseline run can be diffed side-by-side. Header is written once, plus a
 * trailing comment block of the current (pre-swap) requester fingerprints so
 * the contrast is visible at a glance.
 *
 * The append is best-effort: a failure here must not abort the trial or
 * corrupt the primary counter CSV, so all errors are swallowed after a stderr
 * note. */
static void append_vendor_summary(enum scenario sc, int trial,
				  int wc_status, unsigned int vendor_err,
				  double latency_us)
{
	const char *path = "results/raw/vendor_err_summary.csv";
	int write_header = (access(path, F_OK) != 0);

	FILE *f = fopen(path, "a");
	if (!f) {
		fprintf(stderr, "[client] WARN: cannot open %s: %s\n",
			path, strerror(errno));
		return;
	}

	if (write_header) {
		fprintf(f, "scenario,requester_nic,trial,wc_status,wc_status_str,vendor_err,latency_us\n");
	}

	fprintf(f, "%s,%s,%d,%d,%s,0x%x,%.0f\n",
		scenario_names[sc], requester_nic, trial,
		wc_status, ibv_wc_status_str(wc_status),
		vendor_err, latency_us);

	fclose(f);
}

/* Emit, once at the end of a run, the baseline (current-requester) vendor_err
 * fingerprints as CSV comment lines so the file is self-describing when a swap
 * run lands beside it. These constants are the measured values from the
 * existing requester; they are reference-only, never used in any branch. */
static void append_baseline_reference(void)
{
	const char *path = "results/raw/vendor_err_summary.csv";
	FILE *f = fopen(path, "a");
	if (!f)
		return;

	fprintf(f, "# --- baseline reference (current requester, pre-swap) ---\n");
	fprintf(f, "# LOC_PROT_LEN    : vendor_err=0x53 (SGE length > MR size)\n");
	fprintf(f, "# LOC_PROT_LKEY   : vendor_err=0x52 (invalid lkey)\n");
	fprintf(f, "# LOC_PROT_PERM   : vendor_err=0x33 (MR missing LOCAL_WRITE)\n");
	fprintf(f, "# REM_INV_REQ     : vendor_err=0x8a (REMOTE_WRITE not allowed)\n");
	fprintf(f, "# REM_ACCESS_RKEY : vendor_err=0x88 (invalid rkey)\n");
	fprintf(f, "# RNR_RETRY_EXC       : vendor_err=0x87 (RNR retries exhausted)\n");
	fprintf(f, "# REM_ACCESS_ADDR : vendor_err=0x88 (remote addr out of MR bounds)\n");
	fprintf(f, "# RETRY_EXC_*        : vendor_err=0x81 (transport retries exceeded)\n");
	fprintf(f, "# Local errors (LOC_PROT_LEN/LOC_PROT_LKEY/LOC_PROT_PERM) isolate requester NIC generation = clean compare.\n");
	fprintf(f, "# Remote NAK errors (REM_INV_REQ/REM_ACCESS_RKEY/REM_ACCESS_ADDR) flip requester AND responder = confounded.\n");

	fclose(f);
}

/* ------------------------------------------------------------------ */
/*  Per-scenario RDMA setup                                           */
/* ------------------------------------------------------------------ */

static int setup_for_scenario(enum scenario sc)
{
	int access = IBV_ACCESS_LOCAL_WRITE | IBV_ACCESS_REMOTE_WRITE |
		     IBV_ACCESS_REMOTE_READ;
	int retry = 7, rnr_retry = 7, timeout = 14;
	int use_send = 0;
	const char *setup_cmd = CMD_SETUP;

	switch (sc) {
	case LOC_PROT_PERM:
		/* MR without LOCAL_WRITE — RDMA READ response can't write here */
		access = 0;
		break;
	case REM_INV_REQ:
		setup_cmd = CMD_SETUP_NOREMOTE;
		break;
	case RNR_RETRY_EXC:
		use_send = 1;
		rnr_retry = 0;
		setup_cmd = CMD_SETUP_SEND;
		break;
	case RETRY_EXC_QP_ERR:
	case RETRY_EXC_PROC_KILL:
	case RETRY_EXC_LINK_DOWN:
		retry = 7;
		timeout = 8;
		break;
	default:
		break;
	}

	if (setup_rdma(&res, use_send, access, retry, rnr_retry, timeout) < 0) {
		fprintf(stderr, "[client] setup_rdma failed\n");
		return -1;
	}

	tcp_send_msg(ctrl_sock, setup_cmd);
	tcp_exchange_qp_info(ctrl_sock, &res.local_info, &res.remote_info, 0);
	fprintf(stderr, "[client] remote: qpn=%u psn=%u rkey=%u raddr=%lu\n",
		res.remote_info.qpn, res.remote_info.psn,
		res.remote_info.rkey, (unsigned long)res.remote_info.raddr);

	int remote_write = (sc != REM_INV_REQ && sc != RNR_RETRY_EXC);
	if (connect_qp(&res, remote_write, retry, rnr_retry, timeout) < 0) {
		fprintf(stderr, "[client] connect_qp failed\n");
		return -1;
	}

	char resp[256];
	if (tcp_recv_msg(ctrl_sock, resp, sizeof(resp)) <= 0 ||
	    strcmp(resp, CMD_READY) != 0) {
		fprintf(stderr, "[client] expected READY, got '%s'\n", resp);
		return -1;
	}
	return 0;
}

/* ------------------------------------------------------------------ */
/*  Verify connection with a normal WRITE                             */
/* ------------------------------------------------------------------ */

static int verify_connection(void)
{
	if (post_rdma_write(&res, NULL) < 0) {
		fprintf(stderr, "post_rdma_write failed\n");
		return -1;
	}
	struct ibv_wc wc;
	if (poll_cq_block(res.cq, &wc, 5000) <= 0) {
		fprintf(stderr, "verify: poll timeout\n");
		return -1;
	}
	if (wc.status != IBV_WC_SUCCESS) {
		fprintf(stderr, "verify: wc.status=%d\n", wc.status);
		return -1;
	}
	printf("  Connection verified (WRITE success)\n");
	return 0;
}

/* ------------------------------------------------------------------ */
/*  Fault injection per scenario                                      */
/* ------------------------------------------------------------------ */

static int inject_and_post(enum scenario sc)
{
	struct ibv_sge sge;
	char inject_cmd[64];

	switch (sc) {
	case LOC_PROT_LEN:
		/* SGE.length > MR size */
		sge.addr = (uint64_t)res.buf;
		sge.length = MR_SIZE + 4096;
		sge.lkey = res.mr->lkey;
		return post_rdma_write(&res, &sge);

	case LOC_PROT_LKEY:
		/* Invalid lkey */
		sge.addr = (uint64_t)res.buf;
		sge.length = 64;
		sge.lkey = res.mr->lkey + 0x100;
		return post_rdma_write(&res, &sge);

	case LOC_PROT_PERM: {
		/* MR without LOCAL_WRITE — RDMA READ writes response into local
		 * buf, which requires LOCAL_WRITE. This triggers LOC_PROT_ERR. */
		struct ibv_sge s3 = {
			.addr = (uint64_t)res.buf,
			.length = 64,
			.lkey = res.mr->lkey,
		};
		struct ibv_send_wr wr3 = {
			.wr_id = 1,
			.sg_list = &s3,
			.num_sge = 1,
			.opcode = IBV_WR_RDMA_READ,
			.send_flags = IBV_SEND_SIGNALED,
			.wr.rdma = {
				.remote_addr = res.remote_info.raddr,
				.rkey = res.remote_info.rkey,
			},
		};
		struct ibv_send_wr *bad3;
		return ibv_post_send(res.qp, &wr3, &bad3);
	}

	case WR_FLUSH: {
		/* Move QP to ERR, then post */
		struct ibv_qp_attr attr = { .qp_state = IBV_QPS_ERR };
		ibv_modify_qp(res.qp, &attr, IBV_QP_STATE);
		return post_rdma_write(&res, NULL);
	}

	case REM_INV_REQ:
		/* Server QP has no REMOTE_WRITE flag — normal WRITE triggers NAK */
		return post_rdma_write(&res, NULL);

	case REM_ACCESS_RKEY: {
		/* Invalid rkey */
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
		/* SEND with no recv WQE on server */
		return post_send(&res);

	case RETRY_EXC_QP_ERR:
		/* Tell server to move QP to ERR, then post WRITE.
		 * TCP round-trip happens here; caller timestamps after return. */
		snprintf(inject_cmd, sizeof(inject_cmd), "%s %d",
			 CMD_INJECT, RETRY_EXC_QP_ERR);
		send_cmd_wait(ctrl_sock, inject_cmd, CMD_DONE);
		return post_rdma_write(&res, NULL);

	case RETRY_EXC_PROC_KILL: {
		/* Signal orchestrator to kill server, wait for done, then post */
		FILE *sig = fopen("/tmp/ready_to_inject", "w");
		if (sig) { fprintf(sig, "kill\n"); fclose(sig); }
		/* Wait for orchestrator to confirm kill */
		for (int i = 0; i < 300; i++) {
			if (access("/tmp/inject_done", F_OK) == 0) {
				unlink("/tmp/inject_done");
				break;
			}
			usleep(100000);
		}
		sleep(1);
		return post_rdma_write(&res, NULL);
	}

	case RETRY_EXC_LINK_DOWN: {
		/* Signal orchestrator to bring link down, wait, then post */
		FILE *sig = fopen("/tmp/ready_to_inject", "w");
		if (sig) { fprintf(sig, "linkdown\n"); fclose(sig); }
		for (int i = 0; i < 300; i++) {
			if (access("/tmp/inject_done", F_OK) == 0) {
				unlink("/tmp/inject_done");
				break;
			}
			usleep(100000);
		}
		sleep(3);
		return post_rdma_write(&res, NULL);
	}

	case REM_ACCESS_ADDR: {
		/* Remote address out of MR bounds */
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
				.remote_addr = res.remote_info.raddr + MR_SIZE + 4096,
				.rkey = res.remote_info.rkey,
			},
		};
		struct ibv_send_wr *bad;
		return ibv_post_send(res.qp, &wr, &bad);
	}

	default:
		fprintf(stderr, "Unknown scenario %d\n", sc);
		return -1;
	}
}

/* ------------------------------------------------------------------ */
/*  Run one trial                                                     */
/* ------------------------------------------------------------------ */

static int run_trial(enum scenario sc, int trial, FILE *csv)
{
	printf("\n--- %s trial %d ---\n", scenario_names[sc], trial);

	/* 1. Setup RDMA */
	if (setup_for_scenario(sc) < 0) {
		fprintf(stderr, "Setup failed\n");
		return -1;
	}

	/* 2. Verify connection (skip for WR_FLUSH — we'll break it ourselves,
	 *    and REM_INV_REQ — server has no remote write) */
	if (sc != WR_FLUSH && sc != REM_INV_REQ &&
	    sc != RNR_RETRY_EXC) {
		if (verify_connection() < 0)
			return -1;
	}

	/* 3. Before snapshots */
	struct counter_snapshot cli_before, cli_after;
	struct counter_snapshot srv_before, srv_after;

	snapshot_local_counters(&cli_before);

	int daemon_ok = 1;
	if (request_daemon_snapshot(MGMT_SERVER_IP, DAEMON_PORT,
				   &srv_before) < 0) {
		fprintf(stderr, "Warning: daemon snapshot failed\n");
		daemon_ok = 0;
	}

	/* 4. Inject fault and post WR */
	struct timespec t_inject, t_detect;
	clock_gettime(CLOCK_MONOTONIC, &t_inject);

	if (inject_and_post(sc) < 0) {
		/* post_send can fail for WR_FLUSH (QP in ERR) — that's expected,
		 * the error appears as flush on CQ */
		if (sc != WR_FLUSH) {
			fprintf(stderr, "inject_and_post failed\n");
			cleanup_rdma(&res);
			return -1;
		}
	}

	/* 5. Wait for CQE error */
	int timeout_ms = 30000;
	if (sc >= RETRY_EXC_QP_ERR && sc <= RETRY_EXC_LINK_DOWN)
		timeout_ms = 60000;

	struct ibv_wc wc;
	int n = poll_cq_block(res.cq, &wc, timeout_ms);
	clock_gettime(CLOCK_MONOTONIC, &t_detect);

	if (n <= 0) {
		fprintf(stderr, "  Poll timeout — no CQE received\n");
		cleanup_rdma(&res);
		return -1;
	}

	double latency = elapsed_us(&t_inject, &t_detect);
	printf("  CQE: status=%d (%s), vendor_err=0x%x, latency=%.0f us\n",
	       wc.status, ibv_wc_status_str(wc.status),
	       wc.vendor_err, latency);

	/* Record vendor_err in the swap-comparison summary (first-class column,
	 * tagged with the requester NIC label). Best-effort; never aborts. */
	append_vendor_summary(sc, trial, wc.status, wc.vendor_err, latency);

	/* 6. Wait for counters to settle */
	sleep(1);

	/* 7. After snapshots */
	snapshot_local_counters(&cli_after);

	if (daemon_ok) {
		request_daemon_snapshot(MGMT_SERVER_IP, DAEMON_PORT, &srv_after);
	}

	/* 8. Output results */
	fprintf(csv, "# %s,trial=%d,status=%d,vendor_err=0x%x,latency_us=%.0f\n",
		scenario_names[sc], trial, wc.status, wc.vendor_err, latency);

	print_counter_delta("client", &cli_before, &cli_after, csv);
	if (daemon_ok)
		print_counter_delta("server", &srv_before, &srv_after, csv);

	/* 9. Cleanup — skip for RETRY_EXC_PROC_KILL (server dead) and RETRY_EXC_LINK_DOWN (link down) */
	if (sc != RETRY_EXC_PROC_KILL && sc != RETRY_EXC_LINK_DOWN) {
		send_cmd_wait(ctrl_sock, CMD_CLEANUP, CMD_DONE);
	}
	cleanup_rdma(&res);

	return 0;
}

/* ------------------------------------------------------------------ */
/*  Main                                                              */
/* ------------------------------------------------------------------ */

static void usage(const char *prog)
{
	fprintf(stderr, "Usage: %s <scenario_id> [num_trials] [server_ip]\n", prog);
	fprintf(stderr, "  server_ip: responder RDMA IP to connect to.\n");
	fprintf(stderr, "             default=%s (env RDMA_SERVER also honored;\n",
		RDMA_SERVER_IP);
	fprintf(stderr, "             argv overrides env). For the CX-swap run\n");
	fprintf(stderr, "             pass the OTHER node's RDMA IP.\n");
	fprintf(stderr, "  env REQUESTER_NIC: label (e.g. CX5/CX6) tagged into\n");
	fprintf(stderr, "             results/raw/vendor_err_summary.csv.\n");
	fprintf(stderr, "Scenarios:\n");
	for (int i = 1; i < SCENARIO_MAX; i++)
		fprintf(stderr, "  %2d = %s\n", i, scenario_names[i]);
}

int main(int argc, char **argv)
{
	if (argc < 2) {
		usage(argv[0]);
		return 1;
	}

	int sc = atoi(argv[1]);
	if (sc <= 0 || sc >= SCENARIO_MAX) {
		usage(argv[0]);
		return 1;
	}

	if (argc >= 3)
		num_trials = atoi(argv[2]);

	/* Resolve responder IP: argv[3] wins, else env RDMA_SERVER, else the
	 * compiled-in default. This keeps the normal experiment (no extra arg,
	 * no env) connecting to RDMA_SERVER_IP exactly as before. */
	if (argc >= 4 && argv[3][0] != '\0') {
		server_ip = argv[3];
	} else {
		const char *env = getenv("RDMA_SERVER");
		if (env && env[0] != '\0')
			server_ip = env;
	}

	/* Requester NIC label is informational only (CSV tag). */
	{
		const char *nic = getenv("REQUESTER_NIC");
		if (nic && nic[0] != '\0')
			requester_nic = nic;
	}

	fprintf(stderr, "[client] responder=%s requester_nic=%s trials=%d\n",
		server_ip, requester_nic, num_trials);

	srand(time(NULL));

	/* Idle check */
	printf("Checking for background noise...\n");
	if (verify_idle() < 0) {
		fprintf(stderr, "Aborting: background RDMA traffic detected\n");
		return 1;
	}

	/* Open CSV output */
	char csv_path[256];
	snprintf(csv_path, sizeof(csv_path), "results/raw/%s.csv",
		 scenario_names[sc]);
	int append = (sc == RETRY_EXC_PROC_KILL || sc == RETRY_EXC_LINK_DOWN);
	FILE *csv = fopen(csv_path, append ? "a" : "w");
	if (!csv) {
		perror("fopen csv");
		return 1;
	}
	if (!append || ftell(csv) == 0)
		fprintf(csv, "side,counter,before,after,delta\n");

	/* Connect to server (skip for RETRY_EXC_PROC_KILL — handled by run_experiment.sh) */
	if (sc == RETRY_EXC_PROC_KILL || sc == RETRY_EXC_LINK_DOWN) {
		/* RETRY_EXC_PROC_KILL/RETRY_EXC_LINK_DOWN: each trial needs fresh TCP connection
		 * since server restarts between trials. Handled in trial loop. */
		for (int t = 0; t < num_trials; t++) {
			/* Connect to server for this trial */
			ctrl_sock = tcp_connect(server_ip, TCP_CTRL_PORT);
			if (ctrl_sock < 0) {
				fprintf(stderr, "Trial %d: cannot connect to server\n", t);
				continue;
			}

			/* For RETRY_EXC_PROC_KILL: setup, then run_experiment.sh kills server */
			/* For RETRY_EXC_LINK_DOWN: setup, then run_experiment.sh brings link down */
			if (run_trial(sc, t, csv) < 0)
				fprintf(stderr, "Trial %d failed\n", t);

			close(ctrl_sock);
			ctrl_sock = -1;

			/* Wait for server restart (handled by run_experiment.sh) */
			if (sc == RETRY_EXC_LINK_DOWN)
				sleep(5);
		}
	} else {
		ctrl_sock = tcp_connect(server_ip, TCP_CTRL_PORT);
		if (ctrl_sock < 0) {
			fprintf(stderr, "Cannot connect to server\n");
			fclose(csv);
			return 1;
		}

		for (int t = 0; t < num_trials; t++) {
			if (run_trial(sc, t, csv) < 0)
				fprintf(stderr, "Trial %d failed\n", t);
		}

		send_cmd_wait(ctrl_sock, CMD_SHUTDOWN, CMD_DONE);
		close(ctrl_sock);
	}

	fclose(csv);

	/* Drop the baseline fingerprint comment block at the tail of the
	 * vendor_err summary so a swap CSV is self-describing for eyeballing. */
	append_baseline_reference();

	printf("\nResults written to %s\n", csv_path);
	printf("vendor_err summary appended to results/raw/vendor_err_summary.csv\n");
	return 0;
}
