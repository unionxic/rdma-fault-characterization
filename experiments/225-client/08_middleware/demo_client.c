/*
 * demo_client.c — rdma_conn 미들웨어 자동복구 시연 client (225)
 *
 * 한 시나리오마다 fault를 하나 일으키고, 미들웨어가 분류→자동복구→재전송까지
 * 처리하는 전체 경로를 보인다. application이 직접 보는 코드는 send/poll/recover
 * 세 줄뿐이다.
 *
 * 사용: ./demo_client <scenario>
 *   rnr         RNR_RETRY_EXC  → QP_RECOVERY    (server가 recv 보충)
 *   rem_access  REM_ACCESS_ERR → QP_RECOVERY_MR (server MR 재등록 + rkey 재교환)
 *   retry       RETRY_EXC_ERR  → PROBE_PEER     (probe로 alive 확인 후 QP recovery)
 *   loc_prot    LOC_PROT_ERR   → NOTIFY_BUG     (자동복구 불가, 상위 보고)
 */
#include "rdma_conn.h"

#define MR_FULL        (IBV_ACCESS_LOCAL_WRITE | IBV_ACCESS_REMOTE_WRITE | \
			IBV_ACCESS_REMOTE_READ)
#define CQ_TIMEOUT_MS  12000   /* RETRY_EXC detection(~3.7s) 여유 */
#define CMD_TRAP_READY "TRAP_READY"   /* demo 전용: server trap 완료 신호 */

int main(int argc, char **argv)
{
	if (argc < 2) {
		fprintf(stderr, "usage: %s <rnr|rem_access|retry|loc_prot>\n",
			argv[0]);
		return 2;
	}
	const char *scen = argv[1];
	srand(time(NULL));

	int want_send = (!strcmp(scen, "rnr") || !strcmp(scen, "retry"));
	int is_locprot = !strcmp(scen, "loc_prot");
	/* RNR은 rnr_retry=0으로 즉시 실패시킨다. 그 외는 NCCL 기본 7. */
	int rnr_retry = !strcmp(scen, "rnr") ? 0 : 7;

	struct rdma_conn c;
	if (rdma_conn_client(&c, RDMA_SERVER_IP, MR_FULL, 0, 7, rnr_retry, 14) < 0) {
		fprintf(stderr, "ERROR: rdma_conn_client failed\n");
		return 1;
	}
	printf("[demo] connected (scenario=%s)\n", scen);

	/* server가 trap을 깐 뒤 보내는 신호를 기다린다(race 방지). */
	char sig[64];
	if (tcp_recv_msg(c.ctrl_sock, sig, sizeof(sig)) < 0 ||
	    strcmp(sig, CMD_TRAP_READY) != 0) {
		fprintf(stderr, "ERROR: TRAP_READY 대기 실패\n");
		rdma_conn_close(&c);
		return 1;
	}

	/* --- fault 주입 (application의 평범한 송신 한 줄) --- */
	int prc;
	if (want_send)
		prc = rdma_conn_send(&c, 1, 64);
	else if (is_locprot)
		prc = rdma_conn_write(&c, 1, MR_SIZE * 2);  /* oversize SGE → LOC_PROT */
	else {
		/* rem_access: 원격 rkey를 invalid 값으로 위조 → REM_ACCESS.
		 * server MR 재등록 trap은 dereg/reg가 같은 rkey를 재사용할 수 있어
		 * 비결정적이라, client 측 위조로 결정적으로 만든다. 복구(MW_REFRESH)가
		 * server 새 rkey를 exchange로 돌려줘 remote_info를 갱신하면 재전송이
		 * 유효 rkey를 타고 성공한다. */
		c.res.remote_info.rkey = 0xdeadbeef;
		prc = rdma_conn_write(&c, 1, 64);
	}
	if (prc != 0)
		fprintf(stderr, "  (ibv_post 즉시 rc=%d)\n", prc);
	printf("[demo] posted, polling...\n");

	/* --- poll + 분류 --- */
	struct ibv_wc wc;
	struct rdma_fault_info fi;
	memset(&fi, 0, sizeof(fi));
	int n = (prc == 0) ? rdma_conn_poll(&c, &wc, &fi, CQ_TIMEOUT_MS) : 0;
	if (n <= 0) {
		fprintf(stderr, "ERROR: 에러 CQE 미수신 (n=%d)\n", n);
		rdma_conn_close(&c);
		return 1;
	}
	if (fi.error_class == RDMA_CLASS_OK) {
		fprintf(stderr, "ERROR: fault 미발생(예상과 다름)\n");
		rdma_conn_close(&c);
		return 1;
	}
	printf("[fault] %s — %s\n",
	       rdma_error_class_str(fi.error_class), fi.cause);
	printf("        action=%s peer=%s vendor=0x%02x\n",
	       rdma_recovery_action_str(fi.action),
	       rdma_peer_liveness_str(fi.peer), fi.vendor_err);

	/* --- 자동복구 (분류 action에 따라 미들웨어가 알아서 분기) --- */
	enum rdma_recover_result r = rdma_conn_recover(&c, &fi);
	printf("[recover] %s\n", rdma_recover_result_str(r));

	int rc = 1;
	if (r == RDMA_RECOVER_OK) {
		/* 재전송 결과 확인 — 복구가 진짜 됐다면 성공 CQE가 와야 한다 */
		n = rdma_conn_poll(&c, &wc, &fi, CQ_TIMEOUT_MS);
		if (n > 0 && fi.error_class == RDMA_CLASS_OK) {
			printf("[verify] 재전송 성공 — connection 복구됨 (복구 %d회)\n",
			       c.recover_count);
			rc = 0;
		} else {
			printf("[verify] 재전송 실패 (n=%d, class=%s)\n", n,
			       n > 0 ? rdma_error_class_str(fi.error_class) : "none");
		}
	} else if (r == RDMA_RECOVER_BUG) {
		/* LOC_PROT: 자동복구 대상이 아닌 게 정상 동작 */
		printf("[verify] application bug로 분류 — 자동복구 시도 안 함, 상위 보고 (정상)\n");
		rc = 0;
	} else if (r == RDMA_RECOVER_PEER_DEAD) {
		printf("[verify] peer 사망으로 판정 — escalate\n");
	}

	tcp_send_msg(c.ctrl_sock, CMD_MW_SHUTDOWN);
	rdma_conn_close(&c);
	return rc;
}
