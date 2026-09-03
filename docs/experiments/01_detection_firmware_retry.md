# Detection latency와 firmware retry 분해

> [실험 인덱스와 canonical 수치 기준](README.md)

### 1.1 왜 이 분해가 필요한가

RDMA fault recovery의 전체 latency는 fault 발생 시점부터 software가 인지하는 시점까지의 detection latency, 그리고 인지 후 QP를 다시 사용 가능 상태로 되돌리는 recovery latency로 나뉜다. cpu_baseline 실험에서 recovery floor는 약 2.7ms(QP recovery의 local stage 합), detection은 약 3.7s로, detection이 recovery의 약 1000배를 차지한다. 즉 전체 latency는 사실상 detection이 지배한다. 따라서 "RDMA fault를 얼마나 빨리 복구할 수 있는가"는 실질적으로 "3.7s라는 detection latency가 어디서 오는가, 그리고 줄일 수 있는가"로 환원된다.

3.7s가 ConnectX HCA의 변경 불가능한 하드웨어 한계라면 recovery 논의는 무의미해진다. 반대로 configurable firmware feature라면 detection을 ms 단위로 끌어내릴 수 있고 fault characterization과 fast recovery가 의미를 갖는다. 이 절은 3.7s가 후자임을 실험으로 증명한 과정이다.

### 1.2 3.7s baseline: 무엇이 측정되었나

cpu_baseline Exp1은 CQ를 tight-loop로 polling하면서 fault 주입 후 첫 failure CQE가 관측될 때까지의 시간을 측정했다. 세 시나리오 모두 약 3.7s로 수렴한다.

| 시나리오 | detection latency (ms) | N |
|---|---|---|
| 서버 QP를 ERR로 전이 | 3748 ± 11.9 | 데이터 손실(csv에 N=1만 저장, 재실험 필요) |
| 서버 프로세스 kill | 3701 ± 8.5 | 100 |
| link down | 3701 ± 10.3 | 100 |

세 가지 서로 다른 fault 원인이 같은 값으로 수렴한다는 사실 자체가, detection latency를 결정하는 것이 fault의 종류가 아니라 HCA의 transport retry 동작이라는 점을 시사한다. 응답이 오지 않는 모든 fault는 동일한 retry timeout 사이클을 거친 뒤에야 failure CQE를 발생시킨다.

측정 정밀도 한계: 이 detection 측정에는 fault 주입을 위한 control 경로의 TCP RTT가 혼입되어 있어 sub-ms 정밀도를 주장할 수 없다. 다만 3.7s가 지배적이라 혼입의 영향은 1% 미만이다. 서버 QP를 ERR로 전이시키는 시나리오는 detection_latency.csv에 N=1만 저장(데이터 손실)되어 단독으로는 통계적 주장에 쓸 수 없다. 프로세스 kill과 link down 시나리오만 N=100으로 완전하다.

### 1.3 Recovery floor와의 대비: 왜 detection이 지배하는가

비교 기준이 되는 recovery latency는 cpu_baseline Exp3(per-stage QP recovery, N=100)에서 측정했다. QP를 ERR → RESET → INIT → RTR → RTS 5단계로 되돌리며 각 transition 시간을 분해했다.

| stage | 시간 | 비중 |
|---|---|---|
| ERR → RESET (T1) | 1695 µs | 62.2% (지배) |
| local stage 합 (ERR→RESET→INIT→RTR→RTS, coordination 제외) | 약 2.7ms | — |
| with coordination (양쪽 PSN 재협상 포함) | 약 3.6ms | — |

local 기준 recovery floor 약 2.7ms는 detection 3.7s의 약 1/1000이다. QP를 RTS로 되돌리는 작업 자체는 빠르고, 전체 latency를 결정하는 것은 fault를 software가 인지하기까지 걸리는 detection 구간이다. 이 대비가 "detection 단축이 곧 전체 latency 단축"이라는 본 절의 전제를 정당화한다.

### 1.4 3.7s의 산술적 구성: retry timeout 사이클

RDMA reliable connection은 ack이 오지 않으면 ack timeout만큼 기다린 뒤 재전송하고, 이를 retry_cnt만큼 반복한 후 최종적으로 실패 CQE를 올린다. 따라서 detection latency는 다음 구조를 가진다.

detection ≈ t_first + retry_cnt × t_retry

ConnectX-5에서 관측된 분해는 다음과 같다.

429 ms + 6 × 537 ms ≈ 3651 ms

첫 timeout은 약 429ms, 이후 각 retry는 약 537ms floor에 고정된다. retry_cnt를 7로 설정해도 7번이 아니라 6번이 누적되는데, 이는 roce_adp_retrans_en(adaptive retransmission)이 1회 retry를 흡수하기 때문이다(1.7절). effective retry count는 R-1이 된다.

이 분해에서 핵심은 429ms와 537ms가 사용자가 설정한 ack timeout(QP attribute)과 무관하게 강제된다는 점이다.

### 1.5 Root cause: min_ack_timeout_limit firmware feature

원인은 ConnectX-5의 min_ack_timeout_limit firmware feature다. 이 feature는 사용자가 QP attribute로 지정한 ack timeout이 아무리 작아도 firmware가 정한 하한(floor) 아래로 내려가지 못하게 막는다. 그 결과 작은 timeout을 설정해도 floor인 약 429ms / 537ms로 clamp되고, 위의 산술이 3.7s를 만든다.

여기서 ack timeout은 QP attribute의 timeout exponent T로 인코딩되며, IBA 정의상 실제 시간은 4.096 µs × 2^T다. 본 실험에서 사용한 T=8은 약 1.05ms에 해당한다(추론이 아니라 IBA 인코딩 정의에서 계산).

증명 방법은 두 firmware 토글을 ROCE_ACCL register로 직접 켜고 끄면서 같은 retry sweep을 반복한 것이다. R은 retry_cnt를 의미한다.

| 설정 | R=0 detection | R=3 detection | 해석 |
|---|---|---|---|
| min_ack_timeout_limit ON (default) | 약 428ms | 약 2038ms | floor가 T를 override, T=8(1.05ms) 무시됨 |
| min_ack_timeout_limit_disabled=1 | 1.2ms | 5.9ms | T=8이 respected, 설정한 timeout이 그대로 반영 |

default 상태(ON)에서는 T=8을 줘도 R=0이 428ms, R=3이 2038ms로, 설정한 timeout이 전혀 반영되지 않는다. disabled=1로 바꾸면 R=0이 1.2ms, R=3이 5.9ms로 떨어져 설정한 T가 그대로 반영된다. 이 대조가 3.7s의 직접적 원인이 min_ack_timeout_limit floor임을 결정적으로 보여준다.

참고: 산술 분해의 첫 timeout 429ms와 측정 표의 R=0=428ms는 같은 양을 가리킨다(전자는 floor 모델의 첫 항, 후자는 R=0에서의 실측). 1ms 차이는 측정 분산 범위 내다.

### 1.6 297배 단축: R=7에서 12.26ms

min_ack_timeout_limit_disabled=1 상태에서 retry_cnt를 0..7로 sweep한 full 결과가 핵심 수치다.

| 항목 | min_limit ON (default) | min_limit OFF (disabled=1) | 비율 |
|---|---|---|---|
| R=0 | 약 428ms | 1.2ms | — |
| R=7 | 약 3.65s | 12.26ms | 약 297배 |
| 측정 | — | N=30, 실측 (추정 아님) | — |

R=7에서 detection이 약 3.65s에서 12.26ms로 약 297배 단축된다. 이 12.26ms는 modifyqp_20260507_125550.csv에 R=0..7 각 N=30으로 기록된 실측값이며 추정이 아니다. 즉 3.7s는 하드웨어 물리 한계가 아니라 firmware의 configurable floor였고, 그 floor를 해제하면 ms 단위 detection이 가능하다는 것이 실험으로 확정되었다.

### 1.7 roce_adp_retrans_en (adaptive retransmission)의 역할

roce_adp_retrans_en은 adaptive retransmission feature로, retry 중 1회를 흡수해 effective retry count를 R-1로 만든다. 위의 429 + 6 × 537에서 6이 나온 이유다(retry_cnt를 7로 설정했지만 6회만 누적).

중요한 구분: 이 feature를 끄는 것만으로는 3.7s가 해소되지 않는다. adp만 OFF로 두고 min_limit은 ON으로 둔 상태에서 측정하면 R=0=428ms, R=3=2038ms로 여전히 floor가 적용된다. 두 feature는 독립적이며, 3.7s의 근본 원인은 어디까지나 min_ack_timeout_limit이고 roce_adp_retrans_en은 retry 횟수를 한 번 줄이는 보조적 역할만 한다.

| feature | 역할 | 끄면 단독 효과 |
|---|---|---|
| min_ack_timeout_limit | timeout floor 강제 (429/537ms) | 해제 시 T respected → ms 단위 (root cause) |
| roce_adp_retrans_en | retry 1회 흡수 (effective R-1) | OFF만으로는 floor 유지, R=0=428ms/R=3=2038ms |

### 1.8 retry_cnt × qp_timeout sweep: floor의 경계

cpu_baseline Exp4는 firmware 토글 없이 QP attribute의 retry_cnt와 qp_timeout exponent만 sweep해서 floor의 경계를 확인했다. firmware feature를 건드리지 않는 한, QP attribute만으로는 3.7s 근처를 벗어날 수 없음을 보여준다.

| 설정 영역 | 관측 | 해석 |
|---|---|---|
| retry=7, qp_timeout ≤ 14 | 약 3.55s 포화 | HCA backoff cap에 도달 |
| qp_timeout=20 | 30s 초과, 사실상 미감지 | timeout exponent가 너무 커서 retry 사이클이 비현실적으로 길어짐 |
| retry=0 | 수백 ms floor | retry 없어도 kernel cleanup 비용이 남음 |

이 sweep은 "QP attribute 튜닝만으로 detection을 줄이려는 시도는 floor에 막힌다"는 결론을 주고, 그 floor를 넘으려면 firmware feature(min_ack_timeout_limit) 자체를 꺼야 한다는 후속 실험의 동기가 되었다.

### 1.9 Blind window: polling 주기로는 못 줄인다

cpu_baseline Exp2는 CQ polling 사이에 의도적으로 sleep을 넣어 polling 주기가 detection에 미치는 영향을 측정했다(각 N=30).

| 시나리오 | sleep과의 관계 | 해석 |
|---|---|---|
| 서버 프로세스 kill | sleep + 3.7s 선형 누적 | retry 사이클 후 sleep만큼 추가 지연 |
| 서버 QP를 ERR로 전이 | max(sleep, 3.7s) | retry가 지배, sleep이 그 안에 묻힘 |

어느 경우든 detection을 줄이는 것은 polling을 더 자주 하는 것이 아니다. retry timeout이 지배하기 때문에, software polling 주기를 아무리 촘촘히 해도 3.7s 아래로 내려가지 않는다. detection 단축의 lever는 polling이 아니라 firmware floor 해제임을 보강하는 결과다.

### 1.10 Negative finding: tc netem은 RDMA에 무효

network emulation 도구 tc netem으로 packet loss/delay를 주입해 fault를 만들려는 시도는 RDMA에 무효였다. RoCE 데이터 경로가 kernel network stack을 bypass하기 때문에, tc qdisc 계층에 건 netem rule이 RDMA 트래픽에 적용되지 않는다. fault injection은 netem이 아니라 서버 측 QP 상태 조작, 프로세스 kill, link down 같은 직접적 방법으로 해야 한다. 이는 fault injection 방법론 설계 시 반드시 고려할 제약이다.

### 1.11 도구와 재현 절차

firmware feature 토글은 mlxreg로 ROCE_ACCL register를 직접 조작한다.

```
mlxreg -d 01:00.0 --reg_name ROCE_ACCL
```

MFT(Mellanox Firmware Tools) 설치가 필요하고, 빌드 시 `--without-kernel` 옵션을 쓴다. 이 토글은 실험 코드(03_modifyqp/) 밖의 수동 조작이므로, 논문/아카이브용으로는 별도 재현 절차 문서화가 필요하다.

실험 구성: client는 225 노드에서 03_modifyqp/를 실행하고, server는 224 노드의 기존 01_cpu_baseline/experiment1/server를 사용한다.

결과 파일:

| 파일 | 내용 |
|---|---|
| modifyqp_20260507_125550.csv | min_limit OFF, R=0..7, N=30 (R=7 12.26ms 실측의 출처) |
| modifyqp_20260507_111714.csv | min_limit ON, 동일 sweep (default floor) |
| raw_20260504_182249.csv | process-kill 기준 retry_cnt × qp_timeout sweep |
| test_no_adp.csv | adp OFF 단독 효과 측정 |
| test_no_min_limit.csv | min_limit OFF 검증 |

### 1.12 이 절의 결론

3.7s detection latency는 ConnectX-5의 변경 불가능한 하드웨어 한계가 아니라, min_ack_timeout_limit이라는 configurable firmware feature가 강제하는 timeout floor(약 429ms 첫 timeout + 537ms/회)의 누적이다. roce_adp_retrans_en이 retry 1회를 흡수해 429 + 6 × 537 ≈ 3651ms를 만든다. min_ack_timeout_limit_disabled=1로 floor를 해제하면 사용자가 지정한 timeout이 respected되어 R=7에서 12.26ms(N=30 실측), 약 297배 단축된다. QP attribute sweep과 polling 주기 조정은 모두 floor에 막혀 detection을 줄이지 못하며, tc netem은 kernel bypass로 RDMA에 무효다. recovery floor 약 2.7ms가 detection의 약 1/1000임을 감안하면, 전체 fault recovery latency를 단축하는 유일하게 유효한 lever는 firmware feature(min_ack_timeout_limit) 해제다.
