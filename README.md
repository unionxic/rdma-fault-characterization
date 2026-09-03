### RDMA subsystem fault characterization 실험

## 핵심 결론

- 3.7s detection의 정체는 하드웨어 한계가 아니라 firmware 설정(min_ack_timeout_limit)이다. 해제하면 12.26 ms, 약 297배 단축.
- recovery 결정은 CQE(ibv_wc_status + vendor_err)만으로 끝난다. counter는 critical path 밖 — 사후 진단과 조기 감지용.
- counter 감시(roce_adp_retrans)로 같은 fault를 18.4 ms에 감지·복구했다. passive 대비 203배.
- 11개 fault 시나리오 중 9/10을 신호 조합으로 유일 식별했고, N=100 반복에서 전부 deterministic. latency는 host jitter 탓에 분류 신호로 부적합.
- recovery 방법 선택만으로 2,845배 차이가 난다(QP-only 2.8 ms vs driver reload 7.9 s). QP-only는 정상 QP 영향 0%.
- partial write는 NAK 경로만 sq_psn으로 100% 복원된다. silent failure는 requester-invisible — 대응은 read-back 전략.
- SSD 경계에서는 관측성이 역전된다. 명시적 storage 에러는 RDMA 무결, silent 장애만 RDMA counter가 발화(앱 에러보다 54배 조기).

한 줄 목적: RDMA RC QP의 failure/error behavior를 CQE·vendor_err·HW counter 세 신호로 전수 실측해 분류 체계와 최소 비용 recovery를 세우고, 같은 관측 틀을 외부 리소스 경계(SSD, 이후 memory/GPU)로 확장한다.

#### 대표 측정표

에러 유형별 detect + recover(QP-only) + retry, N=10. detection이 전체를 지배한다.

| 에러 (status / vendor_err) | Detect | Recover | Total |
| --- | ---: | ---: | ---: |
| RNR_RETRY_EXC_ERR (13 / 0x87) | 245 us | 1,416 us | 1,671 us |
| REM_ACCESS_ERR (10 / 0x88) | 480 us | 1,342 us | 1,830 us |
| REM_INV_REQ_ERR (9 / 0x8a) | 489 us | 1,310 us | 1,818 us |
| RETRY_EXC_ERR (12 / 0x81) | 3,738,010 us | 2,773 us | 3,740,787 us |

RETRY_EXC_ERR detection 단축 경로 비교.

| 방식 | Detection | Passive 대비 | 오탐 |
| --- | ---: | ---: | --- |
| Passive (CQE 대기, default firmware) | 약 3.7 s | 기준 | 없음 |
| local_ack_timeout_err 감시 | 1,053 ms | 3.5배 | 거의 없음 |
| roce_adp_retrans 감시 | 16.6 ms | 203배 | threshold 필요 |
| firmware floor 해제 (R=7) | 12.26 ms | 약 297배 | 없음 |

#### 해석과 한계

- vendor_err hex는 mlx5 전용. ConnectX-5↔6 swap 실측은 동일, CX-7·타 벤더는 미검증. status는 driver-stable이라 방법론은 vendor-agnostic.
- counter는 recovery 결정을 바꾸지 않지만 분류 해상도의 마지막 한 단계는 올린다. RETRY_EXC_ERR의 두 원인(서버 QP ERR vs 프로세스 종료)을 ethtool traffic으로 구분해 8/10 → 9/10.
- tc netem은 RDMA에 무효(kernel bypass). fault 주입은 QP 상태 조작·프로세스 kill·link down·device-mapper로 수행.
- A/B 실험의 A recover 42.7 ms는 TCP_NODELAY 아티팩트로 판명(수정 완료, 재실행 대기). B 우위 결론은 불변.
- latency 절대값은 CPU pinning 없이 측정한 값이라 host 환경 의존.
- firmware 토글은 mlxreg 수동 조작이며, 스크립트의 관리망 주소는 placeholder로 치환되어 있다.

환경: 225(ConnectX-6, fw 20.40.1000) ↔ 224(ConnectX-5, fw 16.35.8002), 100 Gbps RoCE v2 직결, Ubuntu 24.04, GPU 없음.

#### Directory

| 경로 | 내용 |
| --- | --- |
| `docs/theory/` | 이론 문서 8편 — RDMA 기초, 에러 식별, 분류 체계, counter 관측성, vendor_err 일반화 |
| `docs/experiments/` | 실험 문서 8편 — detection 분해부터 Storage×RDMA까지 |
| `experiments/225-client/` | client(requester) 측 실험 코드와 원시 결과 CSV |
| `experiments/224-server/` | server(responder) 측 대응 코드 |

수치의 근거와 전체 기록: [docs/experiments/README.md](docs/experiments/README.md) (canonical 수치 표)
