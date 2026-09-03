/*
 * rdma_fault.h — libibverbs 위에 얹는 얇은 RDMA 에러 분류·진단 라이브러리.
 *
 * 목적: ibv_poll_cq로 받은 에러 CQE를 (ibv_wc_status + vendor_err) 조합으로
 * 분류하고, 어떤 종류의 에러이며 어떤 recovery action이 맞는지, peer가 살아있다고
 * 볼 수 있는지를 즉시 알려준다. 이것만으로 "watchdog까지 hang하고 원인 불명"이라는
 * 기존 RDMA 런타임의 문제를 푼다(fast-fail + 진단).
 *
 * 범위: 이 라이브러리는 "분류·진단"만 한다. recovery 실행(QP reset, PSN 재협상,
 * MR refresh)은 양쪽 QP 협조와 control channel이 필요하므로 별도 미들웨어 영역이다.
 * 여기서는 각 에러에 대해 "권장 action"을 hint로 돌려줄 뿐, 직접 실행하지 않는다.
 *
 * libibverbs는 수정하지 않는다. 이 라이브러리가 그 위에서 ibv_* 를 호출할 뿐이다.
 *
 * 주의(일반화): vendor_err hex 값은 mlx5(ConnectX) firmware syndrome이다. status
 * 분류는 driver-stable이라 벤더 무관하지만, vendor_err 세부(0x53 등)는 mlx5 계열
 * 전용이다(ConnectX-5↔6 세대 무관성은 swap 실측으로 확인). 타 벤더(EFA/irdma/
 * bnxt_re/cxgb4)는 vendor_err 테이블을 교체해야 한다.
 */
#ifndef RDMA_FAULT_H
#define RDMA_FAULT_H

#include <infiniband/verbs.h>

/* 우리 분류 체계의 에러 클래스 */
enum rdma_error_class {
	RDMA_CLASS_OK = 0,
	RDMA_CLASS_LOCAL_PROT,   /* LOC_PROT_ERR: 로컬 메모리 보호 위반 (application bug) */
	RDMA_CLASS_WR_FLUSH,     /* WR_FLUSH_ERR: 선행 에러로 ERR 전이한 QP의 후속 flush */
	RDMA_CLASS_REM_INV_REQ,  /* REM_INV_REQ_ERR: 원격 invalid request */
	RDMA_CLASS_REM_ACCESS,   /* REM_ACCESS_ERR: invalid rkey 또는 주소 범위 초과 */
	RDMA_CLASS_RNR,          /* RNR_RETRY_EXC_ERR: recv buffer 부족 */
	RDMA_CLASS_TIMEOUT,      /* RETRY_EXC_ERR: ack timeout, peer 무응답 */
	RDMA_CLASS_OTHER,        /* 그 외 / 미분류 */
};

/* 권장 recovery action (이 라이브러리는 hint만, 실행 안 함) */
enum rdma_recovery_action {
	RDMA_ACT_NONE = 0,        /* 정상 */
	RDMA_ACT_NOTIFY_BUG,      /* 자동 복구 불가 — application 수정 필요 (로컬 보호) */
	RDMA_ACT_QP_RECOVERY,     /* QP-only recovery (ERR->RESET->RTS + PSN 재협상) */
	RDMA_ACT_QP_RECOVERY_MR,  /* QP recovery + MR/rkey refresh (또는 주소 교정) */
	RDMA_ACT_PROBE_PEER,      /* peer 생사 불명: control channel probe 후 recover, 죽었으면 escalate */
};

/* peer가 살아있다고 볼 수 있는가. NAK 수신은 peer가 응답했다는 증거다. */
enum rdma_peer_liveness {
	RDMA_PEER_NA = 0,    /* 해당 없음 (로컬 에러 등 wire에 안 나감) */
	RDMA_PEER_ALIVE,     /* NAK 수신 = peer 응답함 */
	RDMA_PEER_UNKNOWN,   /* ack 무응답 = peer 생사 불명 (timeout) */
};

struct rdma_fault_info {
	enum rdma_error_class     error_class;
	enum rdma_recovery_action action;
	enum rdma_peer_liveness   peer;
	int                       wc_status;   /* ibv_wc_status 원본 */
	unsigned int              vendor_err;  /* CQE vendor_err 원본 (mlx5 syndrome) */
	const char               *cause;       /* 사람이 읽는 원인 (vendor_err 세분류 포함) */
	const char               *action_hint; /* 권장 조치 한 문장 */
};

/* 하나의 completion(ibv_wc)을 분류한다. */
struct rdma_fault_info rdma_classify(const struct ibv_wc *wc);

/*
 * ibv_poll_cq의 thin wrapper. poll 후 각 wc를 분류해 info[]에 채운다.
 * wc[]와 info[]는 호출자가 num 크기로 준비한다. 반환값은 poll된 개수(<0이면 에러).
 */
int rdma_poll(struct ibv_cq *cq, int num, struct ibv_wc *wc,
	      struct rdma_fault_info *info);

const char *rdma_error_class_str(enum rdma_error_class c);
const char *rdma_recovery_action_str(enum rdma_recovery_action a);
const char *rdma_peer_liveness_str(enum rdma_peer_liveness p);

#endif /* RDMA_FAULT_H */
