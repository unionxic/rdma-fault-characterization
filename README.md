### RDMA subsystem fault characterization 실험

## 핵심 결론

- RETRY_EXC_ERR의 3.7s detection은 하드웨어 한계가 아니라 firmware 설정이다. ConnectX-5의 min_ack_timeout_limit floor(429 + 6 × 537 ms)가 원인이며, 비활성화하면 R=7 기준 12.26 ms로 약 297배 단축됐다(N=30 실측).
- recovery 결정에 counter는 필요 없다. CQE(ibv_wc_status + vendor_err)만으로 모든 recovery action이 결정됐고(0-cost), 전수 조사한 counter가 추가 정보를 준 경우는 0건. counter의 역할은 분류가 아니라 시점이다 — roce_adp_retrans 감시로 같은 fault의 감지·복구를 18.4 ms(203배)에 끝냈다.
- 11개 fault 시나리오 중 9/10이 (status, vendor_err, counter signature) 조합으로 유일하게 식별되고, N=100 반복에서 전부 deterministic. 반면 latency는 host jitter로 bimodal이라 분류 신호로 부적합.
- recovery 방법 선택만으로 2,845배 차이가 난다(QP-only 2.8 ms vs driver reload 7.9 s). QP-only는 동일 NIC의 정상 QP에 영향 0%.
- 최대 위험은 silent failure다. NAK 에러의 partial write는 sq_psn_delta × PMTU로 서버 협조 없이 100% 복원되지만, timeout/peer death 경로는 requester-invisible — 대응은 복원이 아니라 commit 가시성이며, read-back 전략이 전 구간 우위(정상경로 0 + 에러당 최저).
- SSD 경계에서는 관측성이 역전된다. 명시적 storage 에러는 RDMA 계층에 무결(캡슐화 전달)이고, silent 장애(crash, timeout 초과 fail-slow)만 RDMA counter가 발화한다 — crash에서 counter가 앱 에러보다 54배 조기(0.6 s vs 33.4 s).

한 줄 목적: RDMA RC QP의 failure/error behavior를 CQE·vendor_err·HW counter 세 신호로 전수 실측해 분류 체계와 최소 비용 recovery를 세우고, 같은 관측 틀을 외부 리소스 경계(SSD, 이후 memory/GPU)로 확장한다.

#### 대표 측정표

에러 유형별 detect + recover(QP-only) + retry, N=10. detection이 전체를 지배한다(NAK 수백 us vs timeout 3.7 s).

| 에러 (status / vendor_err) | Detect | Recover | Total |
| --- | ---: | ---: | ---: |
| RNR_RETRY_EXC_ERR (13 / 0x87) | 245 us | 1,416 us | 1,671 us |
| REM_ACCESS_ERR (10 / 0x88) | 480 us | 1,342 us | 1,830 us |
| REM_INV_REQ_ERR (9 / 0x8a) | 489 us | 1,310 us | 1,818 us |
| RETRY_EXC_ERR (12 / 0x81) | 3,738,010 us | 2,773 us | 3,740,787 us |

RETRY_EXC_ERR detection 단축 경로 비교.

| 방식 | Detection | Total | Passive 대비 | 오탐 |
| --- | ---: | ---: | ---: | --- |
| Passive (CQE 대기, default firmware) | 약 3.7 s | 약 3.7 s | 기준 | 없음 |
| local_ack_timeout_err 감시 | 1,053 ms | 1,058 ms | 3.5배 | 거의 없음 |
| roce_adp_retrans 감시 | 16.6 ms | 18.4 ms | 203배 | threshold 필요 |
| firmware floor 해제 (min_ack_timeout_limit_disabled=1, R=7) | 12.26 ms | — | 약 297배 | 없음 |

#### 해석과 한계

- vendor_err hex는 mlx5 전용이다. ConnectX-5↔6 swap 실측에서 세대 무관을 확인했지만 ConnectX-7·타 벤더(EFA/irdma/bnxt_re/cxgb4)는 미검증. status는 driver-stable이므로 방법론 자체는 vendor-agnostic.
- tc netem은 RDMA에 무효(kernel bypass). fault 주입은 QP 상태 조작·프로세스 kill·link down, storage는 target 블록 계층(device-mapper)으로 수행했다.
- A/B recovery 실험의 A recover 42.7 ms는 TCP_NODELAY 누락 아티팩트로 판명(40 ms delayed-ACK floor). 수정 후 동일 시퀀스 2.83 ms 실측으로 검증했고 ab_recovery 재실행은 대기 중 — B(proactive) 우위 결론은 불변.
- latency 절대값은 CPU pinning 없이 측정한 값이라 host 환경 의존(NAK 계열 bimodal). 분류는 latency가 아니라 deterministic한 vendor_err·counter로 한다.
- firmware 토글(min_ack_timeout_limit, roce_adp_retrans_en)은 mlxreg ROCE_ACCL register 수동 조작으로, 실험 코드 밖 절차다.
- 스크립트의 관리망 주소는 placeholder로 치환되어 있어 그대로는 실행되지 않는다. 환경: 225(ConnectX-6, fw 20.40.1000) ↔ 224(ConnectX-5, fw 16.35.8002), 100 Gbps RoCE v2 직결, Ubuntu 24.04, GPU 없음.

#### Directory

| 경로 | 내용 |
| --- | --- |
| `docs/theory/` | 이론 문서 8편: RDMA 기초, CQE·에러 식별, 분류 체계, counter 관측성, vendor_err 일반화, 구현 레이어 제약 |
| `docs/experiments/` | 실험 문서 8편: detection·retry 분해, early detection, recovery, multi-QP, partial write, latency 분포, silent 전략, Storage×RDMA |
| `experiments/225-client/` | client(requester) 측 실험 코드와 원시 결과 CSV — 01_cpu_baseline ~ 10_storage_rdma |
| `experiments/224-server/` | server(responder) 측 대응 코드 |

수치의 근거와 전체 기록: [docs/experiments/README.md](docs/experiments/README.md) (canonical 수치 표)
