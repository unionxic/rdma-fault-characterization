/*
 * rdma_conn.h — rdma_fault 분류 위에 자동 recovery를 얹는 connection 미들웨어.
 *
 * 분류 라이브러리(librdma_fault)는 에러 CQE를 (class, action, peer)로 분류만
 * 한다. 그 위에서 실제 복구를 실행하려면 (1) connection lifecycle 관리,
 * (2) in-flight WR 추적(복구 후 재전송), (3) 양쪽 QP를 함께 reset하는 협조
 * 프로토콜이 필요하다 — 이 셋을 rdma_conn이 담당한다.
 *
 * 핵심 흐름(client):
 *   rdma_conn_client() 로 연결 → rdma_conn_send/write() 로 전송(자동 in-flight
 *   기록) → rdma_conn_poll() 로 완료/에러 수신 → 에러면 rdma_conn_recover() 가
 *   분류 action에 따라 자동 분기(QP reset / MR refresh / peer probe)하고 in-flight
 *   WR을 재전송. server는 rdma_conn_serve() 로 그 협조 요청에 응답.
 *
 * recovery 메커니즘(bilateral QP reset + PSN 재협상, MR 재등록) 자체는 recovery
 * 실험 harness에서 측정·검증된 절차(QP-only 2.8ms 등)를 그대로 옮긴 것이다.
 */
#ifndef RDMA_CONN_H
#define RDMA_CONN_H

#include "../05_counter_mapping/common.h"
#include "../07_fault_classify/rdma_fault.h"

#define RDMA_CONN_MAX_INFLIGHT  MAX_WR   /* common.h: 16 */

/* 미들웨어 control 명령 (bilateral 협조 채널 위) */
#define CMD_MW_SETUP    "MW_SETUP"
#define CMD_MW_RECOVER  "MW_RECOVER"    /* QP-only bilateral recovery */
#define CMD_MW_REFRESH  "MW_REFRESH"    /* QP recovery + server MR 재등록(새 rkey) */
#define CMD_MW_PROBE    "MW_PROBE"      /* peer liveness probe */
#define CMD_MW_SHUTDOWN "MW_SHUTDOWN"

/* rdma_conn_recover의 결과 */
enum rdma_recover_result {
	RDMA_RECOVER_OK = 0,     /* 복구 + in-flight 재전송까지 완료 */
	RDMA_RECOVER_NOTREQ,     /* 정상 CQE — 복구 불필요 */
	RDMA_RECOVER_BUG,        /* 자동복구 불가(application bug) — 상위 보고 */
	RDMA_RECOVER_PEER_DEAD,  /* peer 사망 확인 — escalate(사람 개입) */
	RDMA_RECOVER_FAILED,     /* 복구 절차 자체 실패 */
};

/* 복구 후 재전송하기 위해 기록해 두는 미완료 WR */
struct inflight_wr {
	uint64_t wr_id;
	int      opcode;    /* IBV_WR_SEND / IBV_WR_RDMA_WRITE */
	uint32_t length;
};

struct rdma_conn {
	struct rdma_res res;
	int  ctrl_sock;
	int  is_server;

	/* 연결 파라미터 — recovery 시 동일하게 재적용한다 */
	int  mr_access;
	int  remote_write;
	int  retry_cnt, rnr_retry, timeout;
	int  post_recv_initial;   /* server: lifecycle에서 recv 게시 여부 */

	/* in-flight WR 추적 (post_send/write wrapping으로 채워짐) */
	struct inflight_wr inflight[RDMA_CONN_MAX_INFLIGHT];
	int  n_inflight;

	int  recover_count;       /* 누적 복구 횟수 */
};

/* ---- lifecycle ---- */
int  rdma_conn_client(struct rdma_conn *c, const char *server_ip,
		      int mr_access, int remote_write,
		      int retry_cnt, int rnr_retry, int timeout);
int  rdma_conn_server(struct rdma_conn *c, int listen_sock,
		      int mr_access, int remote_write,
		      int retry_cnt, int rnr_retry, int timeout,
		      int post_recv_initial);
void rdma_conn_close(struct rdma_conn *c);

/* ---- data path (client): post 후 in-flight에 기록 ---- */
int  rdma_conn_send(struct rdma_conn *c, uint64_t wr_id, uint32_t len);
int  rdma_conn_write(struct rdma_conn *c, uint64_t wr_id, uint32_t len);

/* blocking poll + 분류. 성공 CQE는 in-flight에서 제거한다.
 * 반환: 1=CQE 1건 분류(fi 채워짐), 0=timeout, <0=poll 에러. */
int  rdma_conn_poll(struct rdma_conn *c, struct ibv_wc *wc,
		    struct rdma_fault_info *fi, int timeout_ms);

/* 분류 action 기반 자동 recovery + in-flight 재전송 (client 주도) */
enum rdma_recover_result rdma_conn_recover(struct rdma_conn *c,
					   const struct rdma_fault_info *fi);

/* ---- server 협조 ---- */
/* client recovery 명령 1건 처리. 1=처리됨, 0=모르는/종료 명령, -1=에러 */
int  rdma_conn_handle(struct rdma_conn *c, const char *cmd);
/* MW_SHUTDOWN까지 rdma_conn_handle 반복 */
int  rdma_conn_serve(struct rdma_conn *c);

const char *rdma_recover_result_str(enum rdma_recover_result r);

#endif /* RDMA_CONN_H */
