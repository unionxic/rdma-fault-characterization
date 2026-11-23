# Early detection (counter 기반 조기 감지)

> [실험 인덱스와 canonical 수치 기준](README.md)

### 2.1 왜 이 실험이 필요한가

RETRY_EXC_ERR(송신 측이 서버 무응답으로 retry 한도를 소진했을 때 나는 에러)는 default 설정에서 약 3.7s가 지나야 CQE로 통보된다. 이 3.7s는 firmware가 재전송을 모두 소진하기까지 걸리는 시간으로, 그 동안 application은 fault 발생을 전혀 알 수 없다(passive detection). fault는 이미 link/peer 레벨에서 진행 중인데도 software는 약 3.7s 동안 정상으로 착각한 채 동작한다. 이 3.7s 자체는 firmware의 retry timeout 누적([1. Detection latency와 firmware retry 분해](01_detection_firmware_retry.md)에서 min_ack_timeout_limit feature로 분해됨)에서 비롯되며, 본 섹션은 그 timeout을 줄이는 대신 fault 진행을 보여주는 다른 신호를 감시하는 접근을 다룬다.

목표는 passive 통보를 기다리지 않고, fault 진행을 노출하는 HW counter를 polling으로 감시해 같은 fault를 훨씬 일찍 감지(active/early detection)하는 것이다. 전제가 되는 두 통찰은 다음과 같다.

| 통찰 | 내용 |
|---|---|
| Retry는 중단 가능 | firmware가 retry를 다 소진하기 전에 `ibv_modify_qp(IBV_QPS_ERR)`로 QP를 강제 ERR 전이시키면 진행 중인 firmware retry가 즉시 끊긴다. 일찍 "감지"만 하면 일찍 "복구"를 시작할 수 있다. |
| Counter가 fault 진행을 노출 | firmware는 재전송을 시도할 때마다 특정 HW counter를 증가시킨다. 이 counter 증가 시점이 CQE 통보(약 3.7s)보다 훨씬 빠르므로, counter를 감시하면 조기 감지 신호가 된다. |

### 2.2 메커니즘 1: ibv_modify_qp(ERR)로 firmware retry 즉시 중단

먼저 "일찍 감지하면 일찍 멈출 수 있는가"를 검증했다. RETRY_EXC_ERR을 유발한 뒤(서버 무응답 상태), passive 통보(약 3.7s)를 기다리지 않고 송신 측에서 임의 시점에 QP를 ERR로 강제 전이시켰다.

결과: `ibv_modify_qp(IBV_QPS_ERR)` 호출 후 약 500us 이내에 진행 중이던 WR이 WR_FLUSH_ERR(status=5, vendor_err=0xf5)로 CQE에 올라온다. 이때의 CQE는 RETRY_EXC_ERR이 아니라 WR_FLUSH_ERR이다 — QP가 ERR 상태로 들어가면서 미완료 WR들이 flush되었기 때문이다. fault의 분류(RETRY_EXC_ERR 여부)는 별도 신호로 알아야 하고, 여기서의 WR_FLUSH_ERR은 "retry를 우리가 끊었다"는 결과일 뿐이다.

| 항목 | 값 |
|---|---|
| 강제 ERR 전이 시점(주입 후) | 100ms / 200ms / 500ms 세 시점 모두 시도 |
| WR_FLUSH_ERR CQE 생성 지연 | ERR 전이 후 약 500us 이내 |
| 성공률 | 15/15 trial |
| 결론 | 약 3.7s를 기다리지 않고도 임의 시점에 firmware retry를 절단 가능 — early detection의 전제 성립 |

### 2.3 메커니즘 2: firmware retry의 2단계 구조

다음으로 "어떤 counter가, 언제 증가하는가"를 보기 위해 fault 주입 후 counter timeline을 측정했다. firmware retry는 단일 루프가 아니라 두 단계로 동작한다.

| 단계 | Counter | 동작 | Counter 첫 증가 시점(주입 후) | 간격 |
|---|---|---|---|---|
| 1단계 Adaptive retransmission | roce_adp_retrans | exponential backoff 재전송 | 약 4-18ms | 약 4ms에서 시작해 배증(doubling) |
| 2단계 ACK timeout retry | local_ack_timeout_err | ACK timeout 기반 고정 간격 재전송 | 약 1,050ms | 약 536ms 고정 |

fault 직후에는 적응적 재전송(roce_adp_retrans)이 먼저 빠르게 일어나고, 이것이 실패하면 보수적인 ACK-timeout 재전송(local_ack_timeout_err)으로 넘어간다. 두 단계의 첫 증가 시점이 세 자릿수 차이(약 4-18ms vs 약 1,050ms)이므로, 어느 counter를 early detection 신호로 쓰느냐에 따라 감지 속도와 false-positive 특성이 크게 달라진다. 여기서 "counter 첫 증가 시점"은 firmware가 counter를 처음 올리는 시점이고, 아래 실측의 "detection latency"는 거기에 polling 주기와 polling 횟수가 더해진 실제 software 감지 시점이다.

### 2.4 실측 1: roce_adp_retrans 기반 조기 감지 (가장 빠름)

1단계 counter(roce_adp_retrans)를 polling으로 감시하다가 증가가 관측되면 즉시 `ibv_modify_qp(IBV_QPS_ERR)`로 복구를 트리거하는 모드.

| 항목 | 실측값 |
|---|---|
| Detection latency | avg 16,559us (range 10-31ms, poll 1-3회) |
| Recovery latency | avg 1,575us |
| Total (detection + recovery) | avg 18,431us (≈ 18.4ms) |
| Passive(약 3.7s) 대비 단축 | 203x |
| local_ack_timeout_err 방식 대비 | 57x 빠름 |

### 2.5 실측 2: local_ack_timeout_err 기반 조기 감지 (가장 안전)

2단계 counter(local_ack_timeout_err)를 감시하는 모드. 첫 증가 시점 자체가 약 1,050ms이므로 감지가 늦지만, ACK timeout은 그 자체로 "충분히 기다렸는데 응답이 없다"는 보수적 판정이라 오탐이 거의 없다.

| 항목 | 실측값 |
|---|---|
| Detection latency | 1,053ms |
| Recovery latency | 2,770us |
| Total | 1,058ms |
| Passive(약 3.7s) 대비 단축 | 3.5x |

특이점: polling 간격을 10/20/50ms로 바꿔도 detection이 1,053ms로 동일했다. 감지 지연을 polling 주기가 아니라 counter가 처음 증가하는 시점(약 1,050ms)이 지배함을 뜻한다. polling을 더 촘촘히 해도 counter가 안 올라가면 못 잡는다.

### 2.6 speed vs false-positive trade-off

두 counter는 같은 fault를 다른 시점에 노출하므로, 어느 것을 쓸지는 속도와 오탐 사이의 trade-off다.

| Counter | Detection (실측) | Total (실측) | Speedup | False positive |
|---|---|---|---|---|
| roce_adp_retrans | 16.6ms | 18.4ms | 203x | 높음 — 일시적 congestion에서도 증가하므로 단발 증가로 판단하면 오탐. threshold N(연속/누적 증가 임계) 필요 |
| local_ack_timeout_err | 1,053ms | 1,058ms | 3.5x | 거의 없음 — ACK timeout 자체가 보수적 판정 |

roce_adp_retrans는 적응적 재전송 단계라서 정상 운영 중의 일시적 혼잡(congestion)에서도 증가할 수 있다. 단일 증가를 fault로 단정하면 오탐 위험이 있고, threshold(예: 연속 N회 또는 단위 시간당 증가량)를 둬야 한다. 반대로 local_ack_timeout_err는 ACK가 충분히 오래 안 온 뒤에야 올라가므로 거의 오탐이 없는 대신 느리다. 논문에서는 둘 중 하나를 고르는 대신 두 counter를 trade-off 축으로 함께 제시한다.

### 2.7 counter의 이중 역할: 분류는 CQE, 시점은 counter

이 실험 framing의 핵심 결론은 counter와 CQE의 역할 분리다.

| 신호 | 역할 | 비고 |
|---|---|---|
| CQE (ibv_wc_status, vendor_err) | 분류(classification) — 무슨 fault인지 | RETRY_EXC_ERR vs 다른 status 구분은 CQE로만 확정 |
| HW counter (roce_adp_retrans, local_ack_timeout_err) | 시점(timing) — 언제 fault가 시작됐는지 | recovery "결정"에는 불필요하나 recovery "시점"을 앞당기는 능동 신호 |

counter는 recovery 여부를 결정하는 데는 필요 없다(결정은 CQE가 한다). 그러나 CQE가 약 3.7s 뒤에야 오는 동안 counter는 이미 ms 단위로 fault 진행을 노출하므로, counter를 능동 감지 신호로 쓰면 recovery 개시 시점을 최대 203x 앞당길 수 있다. 분류와 시점을 서로 다른 신호 소스로 분리하는 것이 이 early detection 설계의 본질이다.

### 2.8 정리

| 방식 | Detection | Total | Passive 대비 | 안전성 |
|---|---|---|---|---|
| Passive (CQE 대기) | 약 3.7s | 약 3.7s | 기준 | 확정적(오탐 없음) |
| local_ack_timeout_err 감시 | 1,053ms | 1,058ms | 3.5x | 매우 높음 |
| roce_adp_retrans 감시 | 16.6ms | 18.4ms | 203x | threshold 필요 |

약 3.7s passive detection을 counter 감시로 대체하면 같은 RETRY_EXC_ERR fault를 최대 18.4ms(203x 단축)에 감지 후 복구까지 끝낼 수 있고, 오탐을 최소화하려면 1,058ms(3.5x) 경로를 택한다. 두 경로 사이의 57x 차이는 1단계(roce_adp_retrans)와 2단계(local_ack_timeout_err) counter의 첫 증가 시점 차이(약 4-18ms vs 약 1,050ms)에서 그대로 나온다. 실험 산출물 위치: `RETRY_EXC_ERR/early_detect/`(force_err / timeline / recover 3모드 통합), 결과: `RETRY_EXC_ERR/early_detect/results/`.
