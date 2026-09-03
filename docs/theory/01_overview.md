# 연구 개요와 방향

> [이론 문서 인덱스](README.md)

### 1.1 연구 목적

이 연구의 목적은 RDMA subsystem의 error/failure behavior를 체계적으로 characterize하는 것이다. RDMA는 kernel을 bypass하는 data path 위에서 동작하므로, 에러가 발생했을 때 application이 관측할 수 있는 신호가 제한적이고 그 의미가 모호하다. 예를 들어 RETRY_EXC_ERR 하나가 서버 QP의 ERR 전이, 프로세스 kill, link down 같은 서로 원인이 다른 상황을 동시에 가리킬 수 있다. 이렇게 "같은 status인데 원인이 다른" 경우들을 구분 가능한 단위까지 분해하고, 각 원인에 맞는 recovery 전략을 명확히 정의하는 것이 연구의 출발점이다.

초기 framing은 "GPU-initiated RDMA fault recovery"였으나, 에러 복구라는 좁은 목표에서 RDMA subsystem 전반의 error characterization으로 범위를 넓혔다. 즉 특정 시스템 설계를 전제하지 않고, RDMA가 노출하는 신호들을 measurement 기반으로 분류·진단·복구하는 방법론 자체를 contribution으로 삼는다.

### 1.2 핵심 기여

핵심 기여는 세 개의 신호를 조합해 에러를 세분류하는 것이다. 이 조합 자체가 기존에 수행되지 않던 접근이다 (2026-05-16 교수 미팅 확인).

| 신호 | 출처 | 성격 | 역할 |
|------|------|------|------|
| ibv_wc_status | CQE (data path, user-space) | driver-stable, 표준 enum | 1차 분류 |
| vendor_err | CQE (data path, user-space) | firmware raw, ConnectX-specific | 2차 세분류 |
| hw_counter delta | sysfs / ethtool (control path) | port-level, async | 진단 보강 + 조기감지 |

이 세 신호를 단계적으로 합치면 분류 해상도(distinguishable error 종류)가 올라간다. counter mapping 전수조사 결과 ibv_wc_status만으로는 10종 중 6종, vendor_err를 더하면 8종, ethtool counter까지 더하면 9종이 구분되었다 (5절). 남은 1종은 REM_ACCESS_ERR 계열에서 invalid rkey와 주소 범위 초과가 모든 counter source에서 동일 fingerprint를 보여 구분 불가다.

6/10 →(+vendor_err)→ 8/10 →(+ethtool counter)→ 9/10

여기서 중요한 재framing이 있었다 (2026-05-17). 처음에는 counter가 분류·복구 결정에 필요하다고 보았으나, 전수조사 결과 CQE 안의 status와 vendor_err만으로 recovery 결정이 충분하다는 것이 드러났다. CQE는 어차피 application이 ibv_poll_cq로 받는 신호이므로 추가 비용이 없다 (0-cost). counter는 sysfs/ethtool 읽기라는 별도 cost가 있고 port-level이라 per-QP 분해도 떨어진다. 따라서 counter의 위치를 recovery critical path에서 async 진단 + 조기감지로 옮겼다. counter 전수조사는 역설적으로 "counter 없이 CQE만으로 충분하다"는 CQE sufficiency claim의 근거가 되었다.

| 신호 위치 | 이전 가정 | 재framing 후 (2026-05-17) | 근거 |
|-----------|-----------|---------------------------|------|
| CQE (status+vendor_err) | 분류용 | recovery 결정에 충분, 0-cost critical path | poll_cq로 어차피 받음 |
| hw_counter | 분류·복구에 필요 | async 진단 + 조기감지로 이동 | port-level, 별도 read cost |

### 1.3 2단계 전략

교수 제안에 따라 연구를 2단계로 분리한다. 이유는 counter + vendor_err 기반 진단이 RDMA subsystem 레벨 동작이라 CPU든 GPU든 무관하기 때문이다.

| 단계 | 범위 | 내용 |
|------|------|------|
| 1단계 | 범용 CPU RDMA | 분류법 + recovery 방법론이 일반 CPU 환경에서 범용적으로 동작함을 보임 |
| 2단계 | GPU-initiated 특화 | GPU 환경에 특화된 감지·분류·복구 방법론을 별도 제시 |

1단계 논문은 GPU로 국한하지 않고 분류법의 범용성을 입증하는 데 집중한다. GPU 특화 contribution은 2단계로 미룬다.

### 1.4 Recovery 3단계 분류

복구 가능성에 따라 에러를 세 범주로 나눈다 (교수 분류, 2026-05-16). 목표는 "모든 사람이 동의할 수 있게 명확히 정의"하는 것이다.

| 범주 | 상황 | 복구 방식 | 처리 |
|------|------|-----------|------|
| 소프트웨어 자동복구 | 재전송 등 프로토콜 수정으로 해결 가능 | QP recovery (ERR→RESET→RTS) + root cause 수정 | 구현으로 직접 시연 |
| checkpoint | context가 깨진 경우 | checkpoint 기반 복구 | Minder 등 기존 연구 인용 |
| 사람 개입 | 서버 완전 다운 (프로세스 kill 등) | 자동 복구 불가 | 운영자 직접 개입 필요 |

이 3단계는 1.2의 세분류 결과와 연결된다. 예를 들어 timeout 계열은 자동복구 후보가 될 수 있지만, RETRY_EXC_ERR이 가리키는 프로세스 kill·link down은 사람 개입 범주로 넘어간다. 즉 신호 세분류가 곧 recovery 범주 판정의 입력이 된다.

여기서 RETRY_EXC_ERR의 timeout 자체가 가지는 비용에 주의해야 한다. CQ tight-loop baseline 측정에서 RETRY_EXC_ERR 검출까지 약 3.7s가 걸렸다. 세 시나리오 모두 약 3.7s로 수렴한다: 서버 QP ERR 전이 3,748 ± 11.9 ms, 프로세스 kill 3,701 ± 8.5 ms, link down 3,701 ± 10.3 ms (kill·link down은 N=100 완전 측정, 서버 QP ERR 시나리오는 N=1 데이터 손실 caveat 있어 재실험 필요). 이 3.7s의 root cause는 ConnectX-5의 `min_ack_timeout_limit` firmware feature다. 이 feature를 비활성화하면 R=7에서 12.26ms로 줄어들어 약 297배 단축된다 (N=30 실측, 추정 아님). 즉 같은 RETRY_EXC_ERR이라도 검출 latency 자체가 firmware 설정에 종속된다는 점이 자동복구 가능 여부 판정의 전제다. (baseline·root cause·단축비의 상세 분해는 experiments 문서의 "1. Detection latency와 firmware retry 분해" 참조.)

### 1.5 GPU-CPU cooperative 결정

GPU-only recovery는 포기하고 GPU-CPU cooperative로 결정했다 (2026-05-14). GPU 단독이 불가능한 구조적 이유는 다음과 같다.

| 제약 | 내용 | 결과 |
|------|------|------|
| QP recovery 경로 | ibv_modify_qp 상태 전이는 kernel 경유 필수 | GPU가 직접 QP 복구 불가 |
| counter 접근 | hw_counter는 sysfs 노출 | GPU가 sysfs 접근 불가 |
| firmware timeout | RETRY_EXC_ERR의 3.7s는 min_ack_timeout_limit (firmware-controlled) | GPU/CPU 무관하게 고정 |

따라서 역할을 분담한다.

| 주체 | 역할 |
|------|------|
| GPU | CQ polling 즉시 감지, vendor_err 분류, 해당 QP의 WR posting 중단 (cascading 방지), 다른 QP 통신 유지 |
| CPU | counter snapshot, recovery safety 판단, QP recovery (kernel calls) 실행, root cause 수정 (rkey refresh / recv buffer post) |

이 분담은 NCCL 통합 framing과도 조율된다 (상세는 7절). NCCL은 GPU가 아니라 CPU proxy thread가 ibv_poll_cq로 CQ를 polling하므로, "GPU-initiated 감지"는 proxy 현실에 맞춰 감지=proxy, 분류=vendor_err 분기 추가, recovery=QP ops로 매핑된다. GPU가 CQE를 직접 보는 것은 GPUDirect Async라는 특수 경로다. 또한 구현 레이어 분석 결과 (2026-06-04), CQE/vendor_err는 QP를 소유한 user-space 런타임만 볼 수 있어 (CQ가 해당 프로세스 user-space mmap), 분류+복구가 가능한 유일한 자리는 통신 런타임이다. 드라이버는 control path만 (QP state ops + async event/devlink coarse 감지), 데몬은 cross-process coarse monitoring까지만 가능하다 (sysfs counter + `rdma resource show qp`로 타 프로세스 QP state·pid는 보지만, 타 프로세스 CQE는 못 보고 QP recovery 핸들도 없음).

### 1.6 평가 방법

평가는 마이크로벤치마크와 end-to-end 두 축으로 구성한다 (교수 제안).

| 축 | 측정 | 비교 대상 |
|----|------|-----------|
| 마이크로벤치마크 | 복구 시간 | 드라이버 내렸다 올리는 시간 vs 소프트웨어 recovery 시간 |
| end-to-end | 분산 ML completion time | fault 발생 시 자동복구 유무에 따른 차이 |

end-to-end ML 측정에는 제약이 있다. 현 클러스터(225 client / 224 server)는 GPU가 없어 NCCL(CUDA 필수) 실행이 불가능하므로 진짜 분산 ML을 측정할 수 없다. CPU 통신 프록시로 all-reduce를 모사하는 방안은 compute 단계가 가짜라 채택하지 않았다 (2026-06-02 결정). 따라서 end-to-end ML + NCCL 통합 + GPU-initiated 감지 경로는 GPU 노드 확보 후로 미루고, 그 전까지 CPU 환경에서는 기존 마이크로벤치마크의 신뢰성 보강에 집중한다 (예: SGE length 초과 측정이 N=1, latency 분산/CI 미보고 — [TODO: 측정 보강 필요]). GPU 노드의 NIC이 ConnectX-7이면 vendor_err 세대 일반화 검증의 빈칸도 동시에 해소된다 (6절).

### 1.7 논문 구조 주의사항

교수 경고에 따라 에러 시나리오를 단순 나열하는 구조는 피한다. "에러가 발생하는 요인을 다 list-up하거나 모든 시나리오를 적는 형태"가 아니라, 분류 체계 + recovery 3단계 + 평가로 논문을 구성한다. 즉 이 연구의 서술 단위는 개별 에러가 아니라 "신호 조합으로 만든 분류축"과 "복구 가능성 범주"다.
