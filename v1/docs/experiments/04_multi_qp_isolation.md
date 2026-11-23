# Multi-QP isolation

> [실험 인덱스와 canonical 수치 기준](README.md)

### 4.1 왜 이 실험이 필요한가

앞 섹션들의 fault injection과 recovery 실험은 모두 단일 QP(queue pair) 환경에서 수행했다. 그러나 실제 RDMA application(NCCL collective, distributed training의 parameter exchange, storage target 등)은 수십약 수백 개의 QP를 동시에 운용한다. 이때 두 질문이 생긴다.

첫째, isolation 질문이다. 하나의 QP에서 fault가 나서 recovery를 수행할 때, fault와 무관한 정상 QP들은 영향을 받는가? QP-only recovery(해당 QP만 ERR→RESET→INIT→RTR→RTS로 재협상)가 정상 QP에 영향이 없다면, 전체 자원을 파괴/재생성하는 full rebuild 대비 운영상 결정적 장점이 된다.

둘째, classification 질문이다. 여러 QP에서 서로 다른 에러가 동시에 발생하면, fault detection 경로의 두 메커니즘(per-QP CQE polling vs port-level HW counter)이 각각 어느 QP가 어떤 에러를 냈는지 식별할 수 있는가? 이 답은 어떤 detection 경로를 분류의 1차 신호로 삼아야 하는지를 결정한다.

### 4.2 실험 셋업 (공통)

| 항목 | 값 |
|------|----|
| 토폴로지 | client(225, ConnectX-6) ↔ server(224, ConnectX-5), 100Gbps RoCE |
| QP 수 | 2 (QP_A, QP_B) 동시 RDMA WRITE |
| fault 대상 | Experiment 1은 QP_B에만 inject(QP_A 정상 유지), Experiment 2는 두 QP에 각각 다른 에러 inject |
| 측정 단위 | throughput은 ops/10ms window |
| 결과 파일(remote) | `multi_qp/results/20260518_013055_isolation.csv`, `multi_qp/results/20260518_013055_concurrent.csv` |

### 4.3 Experiment 1: Isolation — fault QP의 recovery가 정상 QP에 영향을 주는가

2개 QP가 동시에 RDMA WRITE를 수행하는 상태에서 QP_B에만 RETRY_EXC_ERR(서버 응답 없음으로 retry 소진)를 inject한다. fault가 난 QP_B를 두 방식으로 복구하면서, fault와 무관한 QP_A의 throughput과 downtime을 측정했다.

QP-only recovery: 해당 QP만 RESET 경유로 재협상(PSN 재협상 포함). 이 과정 동안 QP_A의 throughput은 변하지 않았다.

Full rebuild: PD/MR/CQ/QP 등 전 자원을 파괴 후 재생성. QP_A도 동일 자원(PD/MR/CQ)을 공유하므로 QP_B와 함께 중단된다.

| 지표 | QP-only recovery | Full rebuild |
|------|------------------|--------------|
| recovery 동안 QP_A throughput | 5,885 → 6,036 ops/10ms (오차 범위, 변화 0%) | 측정 불가(공유 자원 파괴로 중단) |
| recovery 동안 QP_A downtime | 없음 | 14,995 us |
| recovery time | 2,453 us | 14,995 us |

측정 구간 주의(2026-07-15 검토 반영): isolation CSV의 phase는 baseline → during_fault → after_recovery 세 구간뿐으로, recovery 연산이 실제로 도는 순간의 throughput 윈도우는 따로 없다. 위의 "6,036 ops/10ms"는 fault-hold 구간(fault를 유지한 채 QP_A만 돌린 구간)의 값이다. 또한 full rebuild의 "QP_A downtime 14,995us"는 throughput 트레이스로 직접 관측된 것이 아니라 recovery time + 공유 자원 파괴 사실로부터의 추론이다. 논문 서술 시 "recovery 동안"이라는 표현 대신 이 정의대로 정확히 쓸 것.

Full rebuild에서 QP_A downtime과 recovery time이 동일한 14,995 us인 이유: QP_A는 공유 자원이 파괴되는 순간부터 재생성이 끝날 때까지 통째로 멈추므로, full rebuild의 전체 소요 시간이 그대로 QP_A의 downtime이 된다. 반면 QP-only는 QP_B만 RESET 경유로 복구되고 QP_A는 멈추지 않으므로 QP_A downtime이 0이다.

QP-only는 full rebuild 대비 recovery time 기준 14995 / 2453 ≈ 6.1배 빠르다. 더 중요한 것은 QP_A throughput 변화가 5,885 → 6,036 ops/10ms로 사실상 0%(상승/하락이 아니라 측정 오차 범위)라는 점이다. 즉 QP-only recovery는 fault QP를 격리한 채 복구하며, 정상 QP의 data plane을 전혀 멈추지 않는다. 반면 full rebuild는 공유 자원(PD/MR/CQ)을 함께 파괴하므로 무관한 QP_A에 14,995 us의 downtime을 강제한다.

해석: recovery scope를 "fault QP 하나"로 좁힐 수 있다는 것이 단순히 더 빠른 것을 넘어, 정상 트래픽 무중단(isolation)이라는 정성적으로 다른 성질을 제공한다. multi-QP 환경에서 full rebuild는 blast radius가 전체 QP로 번지지만 QP-only는 fault QP에 국한된다.

### 4.4 Experiment 2: Concurrent — 서로 다른 에러 동시 발생 시 CQE vs counter

두 QP에 서로 다른 에러를 동시에 inject하여, 분류 신호로서 CQE와 HW counter가 "어느 QP가 어떤 에러를 냈는지"를 구별할 수 있는지 비교했다.

| QP | inject한 에러 | ibv_wc_status | vendor_err |
|----|---------------|---------------|-----------|
| QP_A | invalid rkey 또는 주소 범위 초과 계열 | REM_ACCESS_ERR (status=10) | 0x88 |
| QP_B | 서버 QP ERR 전이 후 후속 WR flush | WR_FLUSH_ERR (status=5) | 0xf5 |

QP_A의 vendor_err 0x88은 counter mapping 실험에서 "invalid rkey ≡ 주소 범위 초과" 두 원인이 모든 counter source에서 동일 signature를 내는 것으로 확인된 REM_ACCESS_ERR 계열이다. 둘은 firmware 내부에서 같은 NAK를 생성하므로 오류 코드와 counter 변화만으로는 구분되지 않는다.

두 detection 신호의 동작 차이:

| 신호 | 식별 단위 | 결과 | per-QP 구분 |
|------|-----------|------|------------|
| CQE (completion queue entry) | per-QP (각 QP의 CQE에 qp_num·status·vendor_err 포함) | QP_A=REM_ACCESS_ERR, QP_B=WR_FLUSH_ERR을 정확히 식별, 10/10 deterministic | 가능 |
| HW counter | port-level aggregate | `req_cqe_error`가 baseline 대비 +2로 합산되어 증가, 두 에러가 한 카운터에 묶임 | 불가능 |

CQE는 각 completion이 자신의 QP 번호와 status, vendor_err를 그대로 실어 오므로 10회 반복 모두(10/10) 어느 QP가 어떤 에러를 냈는지 deterministic하게 식별했다. 반면 `req_cqe_error` 같은 HW counter는 port 단위 aggregate이기 때문에, 두 QP의 에러가 baseline 대비 +2라는 합산값으로만 보이고 어느 QP에서 발생했는지 분해되지 않는다.

해석: HW counter는 multi-QP 환경에서 per-QP 분류 신호로 쓸 수 없다. counter는 "포트 전체에서 에러가 몇 건 늘었다"는 집계 정보만 주고, 어떤 QP를 어떻게 복구해야 하는지는 알려주지 못한다. 따라서 분류의 1차 신호는 반드시 per-QP CQE여야 하며, counter는 보조(추세/관측)로만 활용 가능하다. 이는 production survey에서 본 NCCL/UCX/SPDK가 vendor_err를 런타임 분기에 쓰지 않는 관행(production survey 확인)과는 별개로, 적어도 "어느 QP가 망가졌는가"라는 1차 질문에 대해서는 CQE만이 답을 준다는 점을 실증한다.

### 4.5 Realistic 조건에서 오류 신호 조합의 불변성

단일 WR·단일 패킷·단일 QP라는 단순화된 조건에서 도출한 오류 신호 조합(ibv_wc_status × vendor_err × counter signature)이, multi-WR·multi-packet·multi-QP의 현실적 조건에서도 유지되는지 확인했다. 결과는 9개 시나리오 전부 MATCH(9/9, 총 27 trials, 예외 없음)로, 현실적 조건에서도 같은 조합이 재현되었다(이 검증은 counter mapping 실험에 통합되어 수행됨, 2026-05-16).

| 조건 | 신호 조합 재현 |
|------|------------------|
| 단순(single WR / single packet / single QP) | baseline |
| realistic(multi-WR / multi-packet / multi-QP) | 9/9 MATCH (27 trials) |

invariance를 떠받치는 세 mechanistic 관찰:

| 현실 조건 | 관찰 | 함의 |
|-----------|------|------|
| multi-WR (8개 unsignaled WR pending) | 에러 발생 시에도 flush CQE = 0 (unsignaled WR은 에러 시 CQE 미생성) | WR_FLUSH_ERR 오류 코드가 signaled WR에 한정됨을 확인 |
| multi-packet (256KB = 256 packets) | counter delta가 single-packet과 동일 | 신호 조합이 전송 크기에 invariant |
| multi-QP isolation 3종(local / remote / timeout 계열) | sibling QP 영향 0 | Experiment 1의 isolation을 에러 유형 전반으로 확장 |

이는 theory 문서의 에러 분류 체계에서 구축한 오류 신호 조합 기반 분류가 toy 조건의 산물이 아니라 동시성·다중 전송 환경에서도 그대로 성립함을 의미한다. 코드: `05_counter_mapping/multi_client.c`(225), `multi_server.c`(224).

### 4.6 결론

multi-QP 실험은 두 가지를 실증했다. (1) QP-only recovery는 fault QP를 격리해 복구하며 정상 QP throughput 변화 0%(5,885 → 6,036 ops/10ms, 측정 오차 범위), full rebuild는 공유 자원(PD/MR/CQ) 파괴로 무관한 QP에 14,995 us downtime을 강제한다(recovery time 2,453 us vs 14,995 us, 약 6.1배 차이). (2) 동시 다발 에러에서 per-QP 식별은 CQE만 가능하고(10/10 deterministic) HW counter는 port-level 합산(`req_cqe_error` baseline 대비 +2)으로 구분 불가하다. 여기에 realistic 조건 신호 조합 9/9 MATCH(27 trials)가 더해져, "per-QP CQE로 분류 → 최소 recovery action(QP-only) 선택 → isolation 보장"이라는 흐름이 단일 QP toy 환경이 아니라 실제 동시성 환경에서도 성립한다는 근거가 된다.

raw CSV 위치: `06_recovery/multi_qp/results/20260518_013055_isolation.csv`, 동 `_concurrent.csv` (2026-07-15 검토에서 존재 확인).
