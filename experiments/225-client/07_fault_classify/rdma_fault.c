/*
 * rdma_fault.c — rdma_fault.h의 구현.
 *
 * 분류표는 우리 실험으로 확정한 (ibv_wc_status, vendor_err) → (원인, 권장 action,
 * peer liveness) 매핑이다. 출처는 연구 정리본의 recovery decision tree와
 * counter_mapping 결과다. vendor_err hex는 mlx5(ConnectX) firmware syndrome 기준.
 */
#include "rdma_fault.h"

struct rdma_fault_info rdma_classify(const struct ibv_wc *wc)
{
	struct rdma_fault_info fi;
	fi.error_class = RDMA_CLASS_OTHER;
	fi.action      = RDMA_ACT_QP_RECOVERY;
	fi.peer        = RDMA_PEER_NA;
	fi.wc_status   = wc->status;
	fi.vendor_err  = wc->vendor_err;
	fi.cause       = "기타 에러";
	fi.action_hint = "QP recovery 시도, 반복되면 escalate";

	if (wc->status == IBV_WC_SUCCESS) {
		fi.error_class = RDMA_CLASS_OK;
		fi.action      = RDMA_ACT_NONE;
		fi.cause       = "success";
		fi.action_hint = "정상";
		return fi;
	}

	switch (wc->status) {
	case IBV_WC_LOC_PROT_ERR:
		/* 로컬 메모리 보호 위반. wire에 안 나가거나 로컬 단계 실패 → application bug.
		 * vendor_err로 세 원인을 구분(우리 실험으로 확정). 자동 복구 불가. */
		fi.error_class = RDMA_CLASS_LOCAL_PROT;
		fi.action      = RDMA_ACT_NOTIFY_BUG;
		fi.peer        = RDMA_PEER_NA;
		switch (wc->vendor_err) {
		case 0x53: fi.cause = "SGE length > MR size (로컬 길이 초과)"; break;
		case 0x52: fi.cause = "invalid lkey"; break;
		case 0x33: fi.cause = "MR 권한 위반 (LOCAL_WRITE 없음)"; break;
		default:   fi.cause = "로컬 메모리 보호 위반 (vendor_err 미상)"; break;
		}
		fi.action_hint = "자동 복구 불가 — application의 SGE/lkey/MR 권한 수정 후 재시도";
		break;

	case IBV_WC_WR_FLUSH_ERR:
		/* QP가 이미 ERR로 전이한 뒤 남은 WR이 flush된 것. 그 자체가 root cause가
		 * 아니라 선행 에러의 후속이다. */
		fi.error_class = RDMA_CLASS_WR_FLUSH;
		fi.action      = RDMA_ACT_QP_RECOVERY;
		fi.peer        = RDMA_PEER_NA;
		fi.cause       = "선행 에러로 QP가 ERR 전이한 뒤 flush된 WR";
		fi.action_hint = "선행 에러를 먼저 처리 → QP recovery 후 이 WR 재post";
		break;

	case IBV_WC_REM_INV_REQ_ERR:
		/* 원격 invalid request NAK. 서버가 응답했으므로 peer는 살아있다. */
		fi.error_class = RDMA_CLASS_REM_INV_REQ;
		fi.action      = RDMA_ACT_QP_RECOVERY_MR;
		fi.peer        = RDMA_PEER_ALIVE;
		fi.cause       = "원격 invalid request (예: 서버 QP에 REMOTE_WRITE 권한 없음)";
		fi.action_hint = "peer alive — 양쪽 QP recovery + 서버 측 권한/config 수정";
		break;

	case IBV_WC_REM_ACCESS_ERR:
		/* 원격 접근 에러 NAK. invalid rkey와 주소 범위 초과 두 원인이 CQE/counter
		 * 어디서도 구분되지 않는다(우리 결과: 9/10 중 유일한 미구분 쌍). recovery
		 * 절차는 둘 다 동일하므로 분기에는 지장 없다. */
		fi.error_class = RDMA_CLASS_REM_ACCESS;
		fi.action      = RDMA_ACT_QP_RECOVERY_MR;
		fi.peer        = RDMA_PEER_ALIVE;
		fi.cause       = "원격 접근 에러 (invalid rkey 또는 주소 범위 초과 — CQE로 구분 불가)";
		fi.action_hint = "peer alive — 양쪽 QP recovery + MR 재등록/rkey 재교환(또는 주소 교정)";
		break;

	case IBV_WC_RNR_RETRY_EXC_ERR:
		/* RNR NAK. 서버 recv buffer 부족. RNR NAK도 peer 응답이므로 살아있다. */
		fi.error_class = RDMA_CLASS_RNR;
		fi.action      = RDMA_ACT_QP_RECOVERY;
		fi.peer        = RDMA_PEER_ALIVE;
		fi.cause       = "recv buffer 부족 (RNR retry 소진)";
		fi.action_hint = "peer alive — 양쪽 QP recovery, 서버 recv WQE 보충";
		break;

	case IBV_WC_RETRY_EXC_ERR:
		/* ack 무응답으로 transport retry 소진. 서버 QP ERR / 프로세스 종료 /
		 * link down이 모두 같은 신호를 내며, peer 생사를 CQE만으로는 알 수 없다. */
		fi.error_class = RDMA_CLASS_TIMEOUT;
		fi.action      = RDMA_ACT_PROBE_PEER;
		fi.peer        = RDMA_PEER_UNKNOWN;
		fi.cause       = "transport retry 소진 (서버 QP ERR / 프로세스 종료 / link down — 무응답)";
		fi.action_hint = "peer 생사 불명 — control channel로 probe: 살아있으면 QP recovery, 죽었으면 escalate(사람 개입)";
		break;

	default:
		/* 위 초기값(OTHER, QP_RECOVERY) 유지 */
		break;
	}
	return fi;
}

int rdma_poll(struct ibv_cq *cq, int num, struct ibv_wc *wc,
	      struct rdma_fault_info *info)
{
	int n = ibv_poll_cq(cq, num, wc);
	if (n < 0)
		return n;
	for (int i = 0; i < n; i++)
		info[i] = rdma_classify(&wc[i]);
	return n;
}

const char *rdma_error_class_str(enum rdma_error_class c)
{
	switch (c) {
	case RDMA_CLASS_OK:          return "OK";
	case RDMA_CLASS_LOCAL_PROT:  return "LOC_PROT_ERR";
	case RDMA_CLASS_WR_FLUSH:    return "WR_FLUSH_ERR";
	case RDMA_CLASS_REM_INV_REQ: return "REM_INV_REQ_ERR";
	case RDMA_CLASS_REM_ACCESS:  return "REM_ACCESS_ERR";
	case RDMA_CLASS_RNR:         return "RNR_RETRY_EXC_ERR";
	case RDMA_CLASS_TIMEOUT:     return "RETRY_EXC_ERR";
	default:                     return "OTHER";
	}
}

const char *rdma_recovery_action_str(enum rdma_recovery_action a)
{
	switch (a) {
	case RDMA_ACT_NONE:           return "none";
	case RDMA_ACT_NOTIFY_BUG:     return "notify-bug(자동복구 불가)";
	case RDMA_ACT_QP_RECOVERY:    return "qp-recovery";
	case RDMA_ACT_QP_RECOVERY_MR: return "qp-recovery+mr-refresh";
	case RDMA_ACT_PROBE_PEER:     return "probe-peer-then-recover";
	default:                      return "?";
	}
}

const char *rdma_peer_liveness_str(enum rdma_peer_liveness p)
{
	switch (p) {
	case RDMA_PEER_NA:      return "n/a";
	case RDMA_PEER_ALIVE:   return "alive";
	case RDMA_PEER_UNKNOWN: return "unknown";
	default:                return "?";
	}
}
