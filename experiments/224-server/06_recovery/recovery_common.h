/*
 * recovery_common.h — 06_recovery 공용 헤더 (client/server 양쪽에서 include)
 *
 * 05_counter_mapping/common.h 위에 recovery 실험 전용 정의를 얹는다:
 *   - TCP 명령: SETUP_RNR(RQ에 WQE 안 걸기 = RNR 유발), RECOVER_QP(QP-only),
 *     RECOVER_FULL(자원 전체 rebuild), PREP_NEXT(다음 trial 준비)
 *   - struct recovery_timing: detect / counter / recovery / retry 단계별 분해
 *   - reset_qp_to_reset(): 어느 상태에서든 RESET으로 (IBA spec상 항상 허용)
 *   - drain_cq(): 남은 CQE 비우기 (재연결 전 flush 완료 정리용)
 *
 * 주의: QP-only recovery는 RESET→INIT→RTR→RTS 전이만으로 끝나지 않는다 —
 * 반드시 새 PSN을 뽑아 상대와 재교환해야 한다. stale PSN으로 재연결하면
 * 첫 WR부터 out-of-sequence로 실패한다.
 */
#ifndef RECOVERY_COMMON_H
#define RECOVERY_COMMON_H

#include "../05_counter_mapping/common.h"

/* ------------------------------------------------------------------ */
/*  Recovery-specific TCP commands                                     */
/* ------------------------------------------------------------------ */

#define CMD_SETUP_RNR    "SETUP_RNR"
#define CMD_RECOVER_QP   "RECOVER_QP"
#define CMD_RECOVER_FULL "RECOVER_FULL"
#define CMD_PREP_NEXT    "PREP_NEXT"
/* CMD_CLEANUP and CMD_SHUTDOWN are already in common.h */

/* ------------------------------------------------------------------ */
/*  Recovery timing breakdown                                         */
/* ------------------------------------------------------------------ */

struct recovery_timing {
	long detect_us;     /* post WR -> error CQE */
	long counter_us;    /* counter snapshot read time */
	long recovery_us;   /* start recovery -> QP back in RTS */
	long retry_us;      /* post retry WR -> success CQE */
	long total_us;      /* post original WR -> retry success */
};

/* ------------------------------------------------------------------ */
/*  QP state transition helpers                                       */
/* ------------------------------------------------------------------ */

/*
 * Move QP from any state to RESET.
 * The IBA spec allows RESET transition from any state.
 * Returns 0 on success, -1 on failure.
 */
static int reset_qp_to_reset(struct ibv_qp *qp) __attribute__((unused));
static int reset_qp_to_reset(struct ibv_qp *qp)
{
	struct ibv_qp_attr attr = {
		.qp_state = IBV_QPS_RESET,
	};
	int ret = ibv_modify_qp(qp, &attr, IBV_QP_STATE);
	if (ret) {
		fprintf(stderr, "reset_qp_to_reset failed: %s\n",
			strerror(errno));
		return -1;
	}
	return 0;
}

/*
 * Drain any pending completions from CQ (both send and recv).
 * Returns number of completions drained.
 */
static int drain_cq(struct ibv_cq *cq) __attribute__((unused));
static int drain_cq(struct ibv_cq *cq)
{
	struct ibv_wc wc;
	int total = 0;
	while (ibv_poll_cq(cq, 1, &wc) > 0)
		total++;
	return total;
}

#endif /* RECOVERY_COMMON_H */
