# rdma_fault — RDMA 에러 분류·진단 라이브러리

libibverbs 위에 얹는 얇은 라이브러리다. libibverbs는 수정하지 않고, 그 위에서 `ibv_*`를 호출하는 함수 모음을 제공한다. 에러 CQE 하나를 받으면 (ibv_wc_status + vendor_err) 조합으로 분류해서 어떤 종류의 에러인지, 어떤 recovery action이 맞는지, peer가 살아있다고 볼 수 있는지를 즉시 돌려준다.

이것만으로 "RDMA 에러가 나면 watchdog timeout까지 hang하고 원인도 모른다"는 기존 런타임(NCCL/UCX/SPDK는 vendor_err를 로그에만 찍는다)의 문제를 fast-fail + 진단으로 푼다.

## 범위

이 라이브러리는 분류·진단만 한다. recovery 실행(QP reset, PSN 재협상, MR refresh)은 양쪽 QP 협조와 control channel이 필요해서 별도 미들웨어 영역이다. 여기서는 각 에러에 대해 권장 action을 hint로 돌려줄 뿐 직접 실행하지 않는다.

## 파일

| 파일 | 내용 |
|------|------|
| rdma_fault.h | 에러 클래스·action·peer liveness enum, `rdma_classify` / `rdma_poll` 선언 |
| rdma_fault.c | 분류표 구현 (우리 실험으로 확정한 매핑) |
| test_classify.c | 분류 단위 테스트 (실제 RDMA 불필요) |
| Makefile | librdma_fault.a 빌드 + 테스트 |

## 빌드와 테스트 (225에서)

```bash
cd ~/Desktop/gpu_fault_recovery/07_fault_classify   # 225 기준 경로
make            # librdma_fault.a + test_classify
make test       # 분류 단위 테스트 실행 (하드웨어 불필요, 9개 시나리오 검증)
```

테스트는 가짜 `ibv_wc`로 분류 로직만 확인하므로 RDMA 연결 없이 돌아간다. libibverbs 헤더/링크만 있으면 된다.

## API

```c
struct rdma_fault_info rdma_classify(const struct ibv_wc *wc);
int rdma_poll(struct ibv_cq *cq, int num, struct ibv_wc *wc,
              struct rdma_fault_info *info);
```

`rdma_poll`은 `ibv_poll_cq`의 thin wrapper다 — 내부에서 `ibv_poll_cq`를 그대로 부르고, 받은 각 completion을 분류해 `info[]`에 채운다.

## 사용 예

app은 `ibv_poll_cq`를 직접 부르는 대신 `rdma_poll`을 부른다.

```c
#include "rdma_fault.h"

struct ibv_wc wc[16];
struct rdma_fault_info info[16];

int n = rdma_poll(cq, 16, wc, info);
for (int i = 0; i < n; i++) {
    if (info[i].error_class == RDMA_CLASS_OK)
        continue;
    fprintf(stderr, "RDMA fault: %s (%s)\n  → %s [peer=%s]\n",
            rdma_error_class_str(info[i].error_class),
            info[i].cause,
            info[i].action_hint,
            rdma_peer_liveness_str(info[i].peer));

    switch (info[i].action) {        /* 분류 결과로 분기 */
    case RDMA_ACT_NOTIFY_BUG:     /* 자동 복구 불가 → 상위에 보고 */      break;
    case RDMA_ACT_QP_RECOVERY:    /* QP-only recovery 트리거 */          break;
    case RDMA_ACT_QP_RECOVERY_MR: /* QP recovery + MR/rkey refresh */    break;
    case RDMA_ACT_PROBE_PEER:     /* control channel로 peer probe 후 결정 */ break;
    default: break;
    }
}
```

## 분류표

| ibv_wc_status | vendor_err (mlx5) | error_class | 권장 action | peer |
|---|---|---|---|---|
| SUCCESS | — | OK | none | n/a |
| LOC_PROT_ERR | 0x53 | LOC_PROT_ERR (SGE length 초과) | notify-bug (자동복구 불가) | n/a |
| LOC_PROT_ERR | 0x52 | LOC_PROT_ERR (invalid lkey) | notify-bug | n/a |
| LOC_PROT_ERR | 0x33 | LOC_PROT_ERR (MR 권한 위반) | notify-bug | n/a |
| WR_FLUSH_ERR | 0xf5 | WR_FLUSH_ERR | qp-recovery (선행 에러 후속) | n/a |
| REM_INV_REQ_ERR | 0x8a | REM_INV_REQ_ERR | qp-recovery + config 수정 | alive |
| REM_ACCESS_ERR | 0x88 | REM_ACCESS_ERR (invalid rkey 또는 주소 범위 초과) | qp-recovery + MR refresh | alive |
| RNR_RETRY_EXC_ERR | 0x87 | RNR_RETRY_EXC_ERR | qp-recovery + recv WQE 보충 | alive |
| RETRY_EXC_ERR | 0x81 | RETRY_EXC_ERR (timeout) | probe-peer 후 recover/escalate | unknown |

NAK 계열(REM_INV_REQ / REM_ACCESS / RNR)은 서버가 응답한 것이므로 peer alive로 본다. timeout(RETRY_EXC)만 peer 생사가 불명이라 control channel probe가 필요하다.

## 한계

- 분류만 한다. recovery 실행은 별도(양쪽 QP 협조 + control channel 필요).
- vendor_err hex는 mlx5(ConnectX) firmware syndrome이다. status 분류는 driver-stable이라 벤더 무관하지만, vendor_err 세부(0x53 등)는 mlx5 계열 전용이다. 타 벤더(EFA / irdma / bnxt_re / cxgb4)는 rdma_fault.c의 vendor_err 분기를 교체해야 한다. ConnectX-5↔6 세대 무관성은 swap 실측으로 확인됨.
- REM_ACCESS_ERR의 invalid rkey와 주소 범위 초과는 CQE/counter로 구분되지 않는다(우리 결과: 유일한 미구분 쌍). 단 recovery 절차가 같아 분기에는 지장 없다.
