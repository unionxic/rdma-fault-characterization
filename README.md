# RDMA Fault Characterization and Recovery

RDMA subsystem의 failure/error behavior를 실측으로 characterize하고, 에러 분류에 기반한 최소 비용 recovery를 설계하는 연구. 현재는 RDMA를 cross-resource(SSD/DRAM/GPU) 에러 관측점으로 확장하는 리소스 경계 신호 지도(resource-boundary signal map) 단계로 진행 중이다.

## 연구 질문

1. RDMA 에러는 requester가 관측하는 신호(ibv_wc_status, vendor_err, HW counter)만으로 얼마나 세분류되는가?
2. 분류 결과로 recovery 방법(QP-only / Full rebuild / Driver reload)을 추가 비용 없이 결정할 수 있는가?
3. 외부 리소스(SSD/DRAM/GPU)에서 시작된 오류는 RDMA 경계를 지나며 어떤 신호로 변환되거나 소실되는가?

## 핵심 결과

| 발견 | 수치 |
|------|------|
| RETRY_EXC_ERR 3.7s detection의 정체 | min_ack_timeout_limit firmware floor(429 + 6 × 537 ms). 비활성화 시 R=7에서 12.26 ms — 약 297배 단축 (N=30 실측) |
| Counter 기반 early detection | roce_adp_retrans 감시 18.4 ms(203배, 오탐 위험) vs local_ack_timeout_err 1,058 ms(3.5배, 저오탐) |
| 에러 fingerprint 해상도 | 11개 fault 시나리오 → 9/10 구분 (status + vendor_err + counter), N=100 전부 deterministic |
| Recovery 비용 스펙트럼 | QP-only 2.8 ms / Full rebuild 9.6 ms / Driver reload 7.9 s (2,845배 차이). recovery 결정은 CQE만으로 충분(0-cost), counter는 사후 진단 |
| Multi-QP isolation | QP-only recovery 시 정상 QP 영향 0%. per-QP 식별은 CQE만 가능(counter는 port-level 합산) |
| Partial write 복원 | sq_psn_delta × PMTU로 NAK 에러는 100% 복원. silent failure(timeout/peer death)는 requester-invisible |
| Silent partial 대응 | read-back(C3)이 전 구간 우위 — 정상경로 0 + 에러당 4,003 µs. 서열은 에러율이 아니라 소비자 능력이 결정 |
| Storage×RDMA 관측성 역전 | 명시적 SSD 에러는 RDMA 무결(캡슐화 전달), silent 장애만 RDMA counter 발화 — crash에서 counter가 앱 대비 54배 조기(0.6 s vs 33.4 s) |

## 저장소 구조

| 경로 | 내용 |
|------|------|
| `docs/theory/` | 이론 문서군 8편 — RDMA 기초, CQE·에러 식별, 에러 분류 체계, counter 관측성, vendor_err 일반화, 구현 레이어 제약. 인덱스는 `docs/theory/README.md` |
| `docs/experiments/` | 실험 실측 문서군 8편 — detection·retry 분해부터 Storage×RDMA까지. `docs/experiments/README.md`의 canonical 표가 수치 충돌 시 단일 기준 |
| `experiments/225-client/` | client(requester) 측 실험 코드 — 01_cpu_baseline – 10_storage_rdma, 원시 결과 CSV 포함 |
| `experiments/224-server/` | server(responder) 측 대응 코드 |

experiments/는 두 노드에서 실제 구동한 코드의 스냅샷이다. 각 실험 디렉토리의 `results/`에 원시 CSV가 있고, 실험별 상세 인덱스는 `experiments/225-client/README.md`에 있다.

## 실험 환경

| 노드 | 역할 | NIC | Firmware | Kernel |
|------|------|-----|----------|--------|
| 225 | client (requester) | ConnectX-6 (MT4123) | 20.40.1000 | 6.14.0-custom |
| 224 | server (responder) | ConnectX-5 (MT27800) | 16.35.8002 | 6.16.2 |

100 Gbps RoCE v2 직결, Ubuntu 24.04, 양쪽 GPU 없음(GPU 경계 실험은 노드 확보 후). 스크립트의 서버 주소는 placeholder로 치환되어 있다 — 재현 시 자기 환경의 값으로 교체할 것.

## 재현 시 주의

- firmware 토글(min_ack_timeout_limit, roce_adp_retrans_en)은 mlxreg로 ROCE_ACCL register를 수동 조작한다 — 실험 코드 밖 절차(`docs/experiments/01_detection_firmware_retry.md` 1.11절).
- tc netem은 RDMA에 무효(kernel bypass). fault 주입은 QP 상태 조작, 프로세스 kill, link down, 그리고 storage 실험은 target 블록 계층(device-mapper)으로 수행한다.
- vendor_err hex는 mlx5(ConnectX) 전용이다. status는 driver-stable, vendor_err는 firmware raw — 타 벤더 이식 시 분류표 재매핑이 필요하다.
- storage 실험은 부팅 디스크 보호를 위해 file-backed nvmet namespace만 export한다(스크립트에 3중 방어 내장).

## 상태

Baseline(RDMA-native, 01–09)과 Case 1(SSD×RDMA, 10_storage_rdma, 72 trials) 완료. Case 2(Memory×RDMA)는 설계 완료 후 feasibility 확인 대기, Case 3(GPU×RDMA)은 GPU 노드 확보 후. 미해결 항목은 각 실험 문서의 미해결/TODO 절에 있다.
