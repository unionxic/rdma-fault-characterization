/*
 * test_classify.c — rdma_classify 단위 테스트.
 *
 * 가짜 ibv_wc(status + vendor_err만 채움)로 분류 결과를 검증한다. 실제 RDMA
 * 하드웨어/연결이 필요 없으므로 libibverbs 헤더만 있으면 어디서나 돌릴 수 있다.
 * 9개 시나리오(우리 실험 분류)가 기대한 class/action/peer로 나오는지 확인한다.
 */
#include "rdma_fault.h"
#include <stdio.h>
#include <string.h>

static int fails = 0;

static void check(const char *name, int status, unsigned int vendor,
		  enum rdma_error_class want_class,
		  enum rdma_recovery_action want_act,
		  enum rdma_peer_liveness want_peer)
{
	struct ibv_wc wc;
	memset(&wc, 0, sizeof(wc));
	wc.status     = status;
	wc.vendor_err = vendor;

	struct rdma_fault_info fi = rdma_classify(&wc);
	int ok = (fi.error_class == want_class &&
		  fi.action == want_act &&
		  fi.peer == want_peer);
	if (!ok)
		fails++;

	printf("[%s] %-16s status=%2d vendor=0x%02x -> %-17s / %-24s / peer=%s\n",
	       ok ? "PASS" : "FAIL", name, status, vendor,
	       rdma_error_class_str(fi.error_class),
	       rdma_recovery_action_str(fi.action),
	       rdma_peer_liveness_str(fi.peer));
	printf("        cause: %s\n", fi.cause);
}

int main(void)
{
	printf("rdma_fault 분류 단위 테스트 (실제 RDMA 불필요)\n");
	printf("================================================\n");

	check("success",      IBV_WC_SUCCESS,           0x00, RDMA_CLASS_OK,          RDMA_ACT_NONE,           RDMA_PEER_NA);
	check("SGE length",   IBV_WC_LOC_PROT_ERR,      0x53, RDMA_CLASS_LOCAL_PROT,  RDMA_ACT_NOTIFY_BUG,     RDMA_PEER_NA);
	check("invalid lkey", IBV_WC_LOC_PROT_ERR,      0x52, RDMA_CLASS_LOCAL_PROT,  RDMA_ACT_NOTIFY_BUG,     RDMA_PEER_NA);
	check("MR perm",      IBV_WC_LOC_PROT_ERR,      0x33, RDMA_CLASS_LOCAL_PROT,  RDMA_ACT_NOTIFY_BUG,     RDMA_PEER_NA);
	check("WR_FLUSH",     IBV_WC_WR_FLUSH_ERR,      0xf5, RDMA_CLASS_WR_FLUSH,    RDMA_ACT_QP_RECOVERY,    RDMA_PEER_NA);
	check("REM_INV_REQ",  IBV_WC_REM_INV_REQ_ERR,   0x8a, RDMA_CLASS_REM_INV_REQ, RDMA_ACT_QP_RECOVERY_MR, RDMA_PEER_ALIVE);
	check("REM_ACCESS",   IBV_WC_REM_ACCESS_ERR,    0x88, RDMA_CLASS_REM_ACCESS,  RDMA_ACT_QP_RECOVERY_MR, RDMA_PEER_ALIVE);
	check("RNR",          IBV_WC_RNR_RETRY_EXC_ERR, 0x87, RDMA_CLASS_RNR,         RDMA_ACT_QP_RECOVERY,    RDMA_PEER_ALIVE);
	check("RETRY_EXC",    IBV_WC_RETRY_EXC_ERR,     0x81, RDMA_CLASS_TIMEOUT,     RDMA_ACT_PROBE_PEER,     RDMA_PEER_UNKNOWN);

	printf("================================================\n");
	printf("%s — %d개 실패\n", fails ? "FAILED" : "ALL PASS", fails);
	return fails ? 1 : 0;
}
