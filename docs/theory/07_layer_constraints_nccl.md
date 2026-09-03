# 구현 레이어 제약과 NCCL

> [이론 문서 인덱스](README.md)

이 절은 우리가 만든 에러 분류 + 복구 방법론을 실제 소프트웨어 스택의 어느 레이어에 넣을 수 있는가를 따진다. 결론을 먼저 말하면, 배치 가능한 레이어는 설계자가 자유롭게 고를 수 있는 것이 아니라 RDMA의 kernel-bypass 구조가 강제한다. 분류의 핵심 입력인 CQE의 `vendor_err`가 QP를 소유한 user-space 프로세스 밖으로 나가지 않기 때문이다. GPU 학습 환경에서 그 user-space 런타임이 NCCL이며, NCCL의 어디에 어떤 난이도로 통합할 수 있는지까지 정리한다. 통합 실험 자체는 GPU 확보 후로 미뤄져 있고(현재 클러스터 225/224는 GPU 없음 → CUDA·NCCL 동작 불가), 본 절은 통합 지점과 난이도를 미리 확정해 둔 분석이다(2026-06-04 분석).

### 7.1 왜 레이어가 문제가 되는가

RDMA는 data path(WR posting, CQE polling)를 kernel을 거치지 않고 user-space가 NIC과 직접 주고받게 만든 것이 성능의 핵심이다. 그 결과 어떤 진단/복구 정보가 어느 레이어에서 보이는가가 레이어마다 다르다. 우리 분류 체계의 입력 중 CQE의 `vendor_err` 필드가 이 구조에 가장 강하게 제약을 받는다.

우리 분류·복구 방법론은 세 가지 입력을 쓴다. 분류 결정에 충분한 0-cost 신호는 CQE의 `status` + `vendor_err`이고, hw_counter는 recovery critical path가 아니라 async 진단/검증용으로 위치한다는 점은 5절에서 정리했다. 여기서는 그 세 입력이 "어느 레이어에서 보이는가"만 다룬다.

| 입력 | 경로 | 어느 레이어에서 보이나 |
|------|------|------------------------|
| `ibv_wc_status` | CQE 필드 (data path) | QP를 소유한 user-space 프로세스만 |
| `vendor_err` | CQE 필드 (data path, firmware raw) | QP를 소유한 user-space 프로세스만 |
| hw_counter delta | sysfs / ethtool (control path, port-level) | 누구나 (kernel·데몬·user-space) |

여기서 결정적인 비대칭이 생긴다. counter는 control path라 전역에서 보이지만 port-level로 집계되어 coarse하다. counter-mapping 실험에서 분류 해상도는 CQE의 `status`만으로 10개 시나리오 중 6개 구분, `vendor_err`를 더하면 8개, ethtool counter까지 더해야 9개까지 올라갔고, 마지막 한 쌍(REM_ACCESS_ERR의 invalid rkey와 주소 범위 초과)은 어떤 counter source로도 구분되지 않았다(5절). 즉 counter만으로는 다수 시나리오의 signature가 동일하게 묶인다. 반면 CQE의 `status`와 `vendor_err`는 fine-grained 분류의 핵심이지만 data path라서 그 QP를 소유한 user-space 프로세스 안에서만 보인다. 정리하면, 분류 해상도를 결정하는 정보가 스택에서 가장 좁은 레이어에 갇혀 있다.

### 7.2 레이어별로 무엇이 가능한가

각 후보 레이어가 (1) 감지, (2) 분류(status + vendor_err), (3) 복구 실행(`ibv_modify_qp`) 세 능력을 갖는지 정리한다.

| 레이어 | 감지 | 분류(status + vendor_err) | 복구 실행 | 핵심 제약 |
|--------|------|---------------------------|-----------|-----------|
| 드라이버 (kernel) | coarse만 (async event / devlink reporter) | 불가 | 가능 (QP state ops 소유) | data path가 user-space bypass라 CQE를 못 봄 |
| 데몬 (별도 프로세스) | coarse (sysfs counter + rdma netlink) | 불가 | 불가 (QP 핸들 없음) | 타 프로세스 CQ가 그 프로세스 user-space에 mmap |
| user-space 런타임 (NCCL 등) | 즉시 (자기 CQ polling) | 가능 (CQE 소유) | 가능 (자기 QP 핸들) | 자기가 소유한 QP에 한정 |

드라이버 (kernel): 드라이버는 QP state machine을 소유한다. ERR→RESET→INIT→RTR→RTS 전이(`ibv_modify_qp`의 kernel 측 구현)는 모두 드라이버가 수행하므로 control path 상의 복구 실행 능력은 있다. 감지 쪽에서는 async event(예: QP fatal, port event)와 devlink health reporter로 coarse한 신호를 받는다. 그러나 드라이버는 CQE를 보지 못한다. completion이 적히는 CQ buffer는 user-space에 mmap되어 NIC이 user-space와 직접 DMA로 주고받기 때문에, 정상 경로에서 kernel은 개입하지 않는다. 따라서 어떤 WR이 어떤 `status` / `vendor_err`로 실패했는지를 드라이버는 알 수 없다. 결론: 드라이버 단독으로는 "무슨 에러인지" 분류가 불가능하므로 단독 recovery도 불가능하다. 드라이버는 복구의 실행기는 될 수 있어도 의사결정기는 될 수 없다.

데몬 (별도 프로세스): 시스템 전역을 감시하는 별도 데몬을 두는 설계는 자연스럽지만 두 가지 벽에 막힌다. 데몬이 볼 수 있는 것은 control path 정보뿐이다. sysfs hw_counter는 전역이고 port-level이라 누구나 읽을 수 있다. rdma netlink(`rdma resource show qp`)로는 타 프로세스의 QP state와 소유 pid까지 coarse하게 열거할 수 있어, "어느 QP가 ERR로 죽었는가" 수준의 cross-process 모니터링은 가능하다. 데몬이 볼 수 없는 것이 두 가지다. 첫째, 타 프로세스의 CQE(`vendor_err` 포함)를 못 본다. 그 CQ는 해당 프로세스의 user-space 주소공간에 mmap되어 있어 외부 프로세스가 들여다볼 핸들이 없다. 둘째, 타 프로세스 QP에 대한 복구 실행도 못 한다. `ibv_modify_qp`를 호출하려면 그 QP의 ibv 핸들이 필요한데 데몬은 그 핸들을 갖지 못한다. 결론: 데몬은 coarse monitoring(어느 QP가 죽었나)은 되지만 분류도 복구도 불가능하다.

user-space 런타임 (NCCL 등): QP를 생성·소유한 user-space 런타임은 자기 CQ를 직접 polling하므로 CQE의 `status`와 `vendor_err`를 모두 본다. 자기 QP 핸들도 가지고 있어 `ibv_modify_qp` 기반 복구도 직접 실행할 수 있다. 즉 감지·분류·복구 세 능력을 한 레이어에 동시에 갖는 유일한 위치다. 우리가 실험에 쓴 client/server harness(225/224에서 fault를 주입하고 CQE·counter·latency를 수집하는 libibverbs 프로그램)가 바로 이 레이어의 prototype이다.

### 7.3 공통의 벽: vendor_err의 소유권

위 표를 한 문장으로 요약하면, CQE 필드인 `vendor_err`가 QP를 소유한 user-space 전용이라는 점이 데몬과 드라이버 양쪽 공통의 벽이다. counter는 전역이라 어디서든 보이지만 coarse하고(7.1의 9/10 해상도, 마지막 동률 쌍 잔존), fine-grained 분류를 가능하게 하는 `vendor_err`는 data path에 있어 QP 소유 프로세스 밖으로 나가지 않는다. 그래서 우리 분류 + 복구 방법론이 들어갈 수 있는 통합 대상은 본질적으로 통신 런타임 자체일 수밖에 없다. 이것은 구현상의 편의 문제가 아니라 RDMA kernel-bypass 아키텍처가 강제하는 구조적 결론이다.

### 7.4 NCCL 통합

통합 대상이 통신 런타임이라는 결론에서, GPU 분산 학습의 사실상 표준인 NCCL이 자연스러운 타깃이 된다. NCCL의 IB transport(`net_ib`)에서 completion 처리는 GPU가 직접 하는 것이 아니라 CPU proxy thread가 `ibv_poll_cq`로 수행한다. 통합 지점은 이 proxy thread의 completion 처리 경로에 `vendor_err` 분기를 추가하는 것이다.

현재 NCCL의 동작(production survey 확인): completion 처리에서 `wc.status`만 보고 분기하며, `vendor_err`는 로깅 용도로만 출력하고 런타임 분기에는 쓰지 않는다.

쉬운 통합 vs 어려운 통합:

| 구분 | 내용 | 난이도 / 위험 | motivation |
|------|------|----------------|------------|
| 쉬움 (PoC 현실적) | `vendor_err` 분류 + fast-fail. 에러 원인을 식별하고 즉시 실패 보고 | 낮음. proxy thread completion 경로에 분기 추가 | NCCL의 watchdog timeout까지 hang + 범인(원인 QP/에러) 불명 문제 해결. NCCL Issue #1434에서 fast-fail 요청 → NVIDIA "not planned" 응답 |
| 어려움 | 자동 recovery (QP 복구 + collective 재개) | 높음. NCCL connection/collective state machine 깊이 통합 필요 | QP만 reset하면 NCCL 상위 계층(collective state)이 모르는 채로 진행되어 정합성 깨짐 |

쉬운 쪽이 강한 motivation을 갖는다. 현재 RDMA 에러가 나면 NCCL은 watchdog timeout까지 hang하고, 그 과정에서 어느 QP가 어떤 원인으로 죽었는지 식별 정보를 상위로 올리지 못한다(PyTorch Flight Recorder 블로그 "The rank that first raises the NCCL watchdog timeout is rarely the culprit", UCX Issue #6673 "no indication of who is the other side"). `vendor_err` 분류 + fast-fail은 이 두 문제를 동시에 푼다. NCCL Issue #1434에서 커뮤니티가 fast-fail을 요청했으나 NVIDIA가 "not planned"로 답한 사실은, 이 통합이 공백을 메운다는 외부 근거가 된다.

어려운 쪽(자동 recovery)은 QP state machine만 복구해서는 부족하다. NCCL이 connection과 collective state를 별도로 관리하므로, QP를 reset 후 PSN을 재협상해 재연결하면 그 상태 변화를 NCCL collective state machine에 일관되게 반영해야 한다. 이 통합 없이 QP만 복구하면 상위가 복구 사실을 모른 채 진행해 hang 또는 silent corruption이 된다.

### 7.5 framing 조율: "GPU-initiated"의 현실

NCCL에서 CQ polling은 GPU가 아니라 CPU proxy thread가 수행한다. 따라서 우리 연구의 "GPU-initiated 감지" framing은 proxy 현실에 맞춰 다음과 같이 분해해 기술해야 한다.

| 단계 | 실제 수행 주체 | 비고 |
|------|----------------|------|
| 감지 | CPU proxy thread (`ibv_poll_cq`) | GPU 직접 polling 아님 |
| 분류 | 위 proxy 경로에 `vendor_err` 분기 추가 | 우리 기여 |
| 복구 | QP ops (`ibv_modify_qp`, kernel 경유) | control path |

GPU가 CQE를 직접 읽는 경로는 GPUDirect Async 같은 특수 경로(GPU kernel이 NIC doorbell·CQ에 직접 접근하도록 설계된 경로)로 한정되며, 일반 NCCL 경로의 현실은 CPU proxy thread다. 이 framing 분해는 1.5절에서 정리한 GPU-CPU cooperative 역할분담과도 일관된다. 그 역할분담은 GPU 측이 CQ polling 즉시 감지 + `vendor_err` 분류 + 해당 QP WR posting 중단(cascading 방지) + 다른 QP 통신 유지를 맡고, CPU 측이 counter snapshot + recovery safety 판단 + QP recovery(kernel calls) 실행 + root cause 수정(invalid rkey refresh, recv buffer 재 post)을 맡는 구조다. 통합 실험은 GPU(따라서 NCCL/CUDA) 확보 후로 미뤄져 있다.

### 7.6 요약

| 질문 | 결론 |
|------|------|
| recovery 로직을 어디 두는가 | 선택이 아니라 RDMA kernel-bypass가 강제. fine-grained 분류 입력 `vendor_err`(CQE data path)는 QP 소유 user-space 전용 |
| 드라이버 (kernel) | 복구 실행은 가능하나 CQE를 못 봐 분류 불가 → 의사결정기 불가 |
| 데몬 | coarse monitoring(어느 QP 죽었나)만 가능, 분류·복구 모두 불가 |
| user-space 런타임 | 감지·분류·복구를 한 레이어에 갖는 유일한 자리 |
| 통합 대상 | 통신 런타임, GPU 학습에선 NCCL. 지점은 `net_ib` CPU proxy thread의 `ibv_poll_cq` completion 경로 |
| 쉬운 통합 | 분류 + fast-fail → NCCL hang + 범인 불명 해결, NVIDIA not-planned 공백 메움 |
| 어려운 통합 | 자동 recovery → NCCL connection/collective state machine과 깊은 정합 필요 |
