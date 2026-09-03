# Recovery Latency 실험 결과 종합

## 1. 실험 환경

| 항목 | Client (225) | Server (224) |
|---|---|---|
| NIC | ConnectX-6 (MT28908) | ConnectX-5 (MT27800) |
| Firmware | 20.40.1000 | 16.35.8002 |
| RDMA IP | 10.0.0.2 | 10.0.0.3 |
| Link | 100 Gbps RoCE v2 | 100 Gbps RoCE v2 |

TCP control channel: TCP_NODELAY 적용 (Nagle buffering 제거).
각 trial 독립 (setup → fault inject → detect → recover → retry verify → cleanup).

---

## 2. 에러 유형별 실험 요약

### 2-1. RNR_RETRY_EXC (Error 13, vendor_err 0x87)

Fault scenario: Server가 recv buffer 미게시 → client SEND → RNR NAK → rnr_retry=0 즉시 소진

Recovery method: 양쪽 QP reset + PSN 재협상 + reconnect (server는 RTS→RESET)

| Method | detect (us) | recovery (us) | retry (us) | N |
|---|---|---|---|---|
| QP-only | 245 | 1,416 | 10 | 10 |
| Full rebuild | 245 | 7,793 | 7 | 10 |

파일: `RNR_RETRY_EXC/results/recovery_20260517_013222.csv`

특이사항:
- Server QP는 RTS 상태 (건강)이지만 PSN 재협상을 위해 RESET 필요
- Detection 245us = RNR NAK 즉시 리턴 + rnr_retry=0

---

### 2-2. RETRY_EXC_ERR (Error 12, vendor_err 0x81)

Fault scenario: Server QP를 ibv_modify_qp(ERR)로 강제 전이 → client SEND → ACK 없음 → retry_cnt=7 소진

Recovery method: 양쪽 QP reset + PSN 재협상 + reconnect (양쪽 모두 ERR→RESET)

| Method | detect (us) | recovery (us) | retry (us) | N |
|---|---|---|---|---|
| QP-only | 3,738,010 | 2,773 | 4 | 10 |
| Full rebuild | 3,738,810 | 9,633 | 4 | 10 |
| Driver reload | 3,622,813 | 7,889,068 | 9 | 10 |

파일: `RETRY_EXC_ERR/results/recovery_20260517_021213.csv`

특이사항:
- Detection 3.7s = firmware retry exhaustion (retry_cnt=7, adaptive retransmission 포함)
- Driver reload = modprobe -r mlx5_ib + modprobe mlx5_ib + device init + GID table 재생성
- QP-only vs Driver reload = 2,847x 차이
- retry_cnt=7은 NCCL 기본값 (NCCL_IB_RETRY_CNT)

---

### 2-3. REM_ACCESS_ERR (Error 10, vendor_err 0x88)

Fault scenario: Server가 ibv_dereg_mr() → client가 stale rkey로 RDMA WRITE → Error NAK → 즉시 감지

Recovery method: 양쪽 QP reset + server 새 MR 등록 + (PSN + rkey + addr) 교환 + reconnect

| Method | detect (us) | recovery (us) | retry (us) | N |
|---|---|---|---|---|
| QP-only + MR refresh | 480 (stable) | 1,342 | 8 | 10 |
| Full rebuild | 427 | 6,878 | 6 | 10 |

파일: `REM_ACCESS_ERR/results/recovery_20260517_160121.csv`

특이사항:
- Detection ~450us = Error NAK 즉시 리턴 (retry 없음, IBA spec 상 Error NAK은 재전송 불가)
- Error NAK 자체가 peer liveness 증거 → TCP probe 불필요
- 첫 5 trials warmup (5.3ms→480us), NIC cache 효과. 안정값 기준 분석
- MR 재등록이 recovery에 추가되지만 latency 차이 무시 가능 (~100us)

---

### 2-4. REM_INV_REQ_ERR (Error 9, vendor_err 0x8a)

Fault scenario: Server MR을 IBV_ACCESS_LOCAL_WRITE만으로 등록 → client RDMA WRITE → Error NAK (code 1) → 즉시 감지

Recovery method: 양쪽 QP reset + server MR 재등록(REMOTE_WRITE 포함) + (PSN + rkey + addr) 교환 + reconnect

| Method | detect (us) | recovery (us) | retry (us) | N |
|---|---|---|---|---|
| QP-only + MR refresh | 489 (stable) | 1,310 | 8 | 10 |
| Full rebuild | 437 | 6,960 | 6 | 10 |

파일: `REM_INV_REQ/results/recovery_20260517_223911.csv`

특이사항:
- REM_ACCESS_ERR과 동일 메커니즘 (Error NAK 기반), 수치도 사실상 동일
- 첫 5 trials warmup (3.1ms→489us), NIC cache 효과. 안정값 기준 분석
- 같은 Error NAK 분류 → 같은 recovery → 같은 latency 실증

---

## 3. 전체 비교표

### 3-1. Detection Latency

| 에러 유형 | Detection | 원인 | Retry 여부 |
|---|---|---|---|
| RNR_RETRY_EXC | 245 us | RNR NAK 즉시 리턴 | rnr_retry=0, 재전송 없음 |
| REM_ACCESS_ERR | 480 us | Error NAK 즉시 리턴 | IBA: Error NAK은 재전송 불가 |
| REM_INV_REQ | 489 us | Error NAK 즉시 리턴 | IBA: Error NAK은 재전송 불가 |
| RETRY_EXC_ERR | 3,738 ms | Timeout retry exhaustion | retry_cnt=7 + adaptive retrans |

Detection 차이: NAK 기반 에러는 수백 us, Timeout 기반 에러는 수 초. 1,000x~10,000x 차이.

### 3-2. Recovery Latency

| 에러 유형 | QP-only | Full rebuild | Driver reload |
|---|---|---|---|
| RNR_RETRY_EXC | 1,416 us | 7,793 us | — |
| REM_ACCESS_ERR | 1,342 us | 6,878 us | — |
| REM_INV_REQ | 1,310 us | 6,960 us | — |
| RETRY_EXC_ERR | 2,773 us | 9,633 us | 7,889,068 us |

Recovery는 에러 유형에 거의 무관 (QP-only: 1.3~2.8ms). 절차가 동일하면 시간도 동일.
RETRY_EXC가 ~1.4ms 느린 이유: 3.7s 동안 firmware가 쌓은 retry state 정리 비용.

### 3-3. End-to-End Total (detect + recovery + retry)

| 에러 유형 | QP-only total | Full rebuild total | Driver reload total |
|---|---|---|---|
| RNR_RETRY_EXC | 1,671 us | 8,045 us | — |
| REM_ACCESS_ERR | 1,830 us | 7,311 us | — |
| REM_INV_REQ | 1,818 us | 7,411 us | — |
| RETRY_EXC_ERR | 3,740,787 us | 3,748,447 us | 11,511,890 us |

NAK 기반 에러: end-to-end ~2ms (detect + recover 합산).
Timeout 기반 에러: end-to-end ~3.7s — detection이 지배, recovery 최적화로 줄일 수 없음.

---

## 4. Early Detection: Counter 기반 조기 감지 (RETRY_EXC_ERR)

RETRY_EXC_ERR의 3.7s detection을 단축하기 위한 능동적 counter 감시 방식.

### 4-1. 검증: ibv_modify_qp(ERR)로 firmware retry 중단 가능

Firmware retry 진행 중에 ibv_modify_qp(ERR) 호출 → WR_FLUSH_ERR CQE 생성 확인.

| delay (ms) | CQE status | vendor_err | force→CQE (us) | N |
|---|---|---|---|---|
| 100 | 5 (WR_FLUSH_ERR) | 0xf5 | 564 | 5 |
| 200 | 5 (WR_FLUSH_ERR) | 0xf5 | 452 | 5 |
| 500 | 5 (WR_FLUSH_ERR) | 0xf5 | 508 | 5 |

어느 시점에서든 즉시 중단 가능. 15/15 성공.

파일: `RETRY_EXC_ERR/early_detect/results/force_err_20260517_225228.csv`

### 4-2. Counter 증가 타임라인

자연 retry 소진(3.7s) 동안 counter 증가 시점 전수 기록.

Firmware retry 2단계 구조 발견:

1단계 — Adaptive retransmission (exponential backoff):

| 시점 (ms) | Counter | 간격 |
|---|---|---|
| 3.8 | roce_adp_retrans +1 | — |
| 8.3 | roce_adp_retrans +1 | 4.5ms |
| 14.3 | roce_adp_retrans +1 | 6.0ms |
| 26.3 | roce_adp_retrans +1 | 12.0ms |
| 51.8 | roce_adp_retrans +1 | 25.5ms |
| 118.6 | roce_adp_retrans +1 | 66.8ms |
| 253.2 | roce_adp_retrans +1 | 134.6ms |
| 522.0 | roce_adp_retrans +1 | 268.8ms |

2단계 — ACK timeout retry (~536ms 고정 간격):

| 시점 (ms) | Counter | 간격 |
|---|---|---|
| 1,059 | local_ack_timeout_err +1 | — |
| 1,595 | local_ack_timeout_err +1 | 536ms |
| 2,132 | local_ack_timeout_err +1 | 537ms |
| 2,669 | local_ack_timeout_err +1 | 537ms |
| 3,205 | local_ack_timeout_err +1 | 536ms |
| 3,742 | req_transport_retries_exceeded + CQE | 537ms |

Counter별 첫 증가 시점:

| Counter | 첫 증가 (avg) | CQE 대비 |
|---|---|---|
| roce_adp_retrans | ~10 ms | 3.7s 전 |
| local_ack_timeout_err | ~1,050 ms | 2.7s 전 |
| req_transport_retries_exceeded | ~3,742 ms | CQE와 동시 |
| roce_adp_retrans_to | 미증가 | — |
| out_of_sequence | 미증가 | — |

파일: `RETRY_EXC_ERR/early_detect/results/timeline_20260517_230941.csv`

### 4-3. Early Detection Recovery 실측

Counter를 10ms 간격으로 polling → 증가 감지 시 force ERR → recovery.

| Method | Detection (us) | Recovery (us) | Total (us) | Speedup |
|---|---|---|---|---|
| Passive (기존) | 3,738,010 | 2,773 | 3,740,787 | 1x |
| Active — local_ack_timeout_err 10ms | 1,053,000 | 2,770 | 1,058,000 | 3.5x |
| Active — local_ack_timeout_err 20ms | 1,057,000 | 2,808 | 1,060,000 | 3.5x |
| Active — local_ack_timeout_err 50ms | 1,057,000 | 2,695 | 1,060,000 | 3.5x |
| Active — roce_adp_retrans 10ms | 16,559 | 1,575 | 18,431 | 203x |

local_ack_timeout_err: polling interval(10/20/50ms)은 결과에 거의 무관 — counter 증가 시점(~1,050ms)이 지배.
roce_adp_retrans: detection 10~31ms 범위. polls_before_detect 1~3회, counter 첫 증가(~4ms)와 polling 주기(10ms) 정렬에 따라 결정.

파일:
- `RETRY_EXC_ERR/early_detect/results/early_detect_20260517_230111_combined.csv` (local_ack_timeout_err)
- `RETRY_EXC_ERR/early_detect/results/20260518_003532_recover_roce_adp_retrans_10ms.csv` (roce_adp_retrans)

### 4-4. Counter 선택: detection speed vs false positive trade-off

| Counter | 첫 증가 | Detection | False positive 위험 | 적합 정책 |
|---|---|---|---|---|
| roce_adp_retrans | ~4-18 ms | 16.6 ms (실측) | 높음 — 일시적 congestion에서도 증가 가능 | threshold N 설정 ("N번 연속 증가 시 개입") |
| local_ack_timeout_err | ~1,050 ms | ~1,053 ms | 거의 없음 — ACK timeout 자체가 보수적 판정 | 첫 증가 즉시 개입 가능 |

roce_adp_retrans는 패킷이 살짝 늦게 도착하면 firmware가 adaptive retransmission을 시도하면서 +1됨.
이걸로 바로 QP를 ERR로 전이시키면 정상 연결을 죽이는 위험.

local_ack_timeout_err는 ACK timeout이 발생해야 증가하므로, 증가 자체가 "실제 문제"의 강한 신호.
첫 증가 즉시 개입해도 false positive 위험이 낮음.

| Method | Detection | Total | 안전성 |
|---|---|---|---|
| Passive (기존) | 3,738 ms | 3,741 ms | 1x | — |
| Active — local_ack_timeout_err | 1,053 ms | 1,058 ms | 3.5x | 안전 |
| Active — roce_adp_retrans (threshold=1) | 16.6 ms | 18.4 ms | 203x | 위험 (congestion false positive) |
| Active — roce_adp_retrans (threshold=N) | 16.6ms × N | 가변 | 가변 | 조정 가능 |

---

## 5. Recovery Method 비교


| Method | 내용 | Latency | 비고 |
|---|---|---|---|
| QP-only (+MR) | QP RESET→RTS + PSN 재협상 + (필요시 MR 재교환) | 1.3~2.8 ms | PD, CQ 재활용 |
| Full rebuild | PD/CQ/QP/MR 전부 파괴 + 재생성 | 6.9~9.6 ms | 모든 자원 새로 할당 |
| Driver reload | modprobe -r + modprobe + device init + 전체 재생성 | 7,889 ms | QP-only 대비 2,847x 느림 |

---

## 6. 핵심 결론

### 5-1. CQE만으로 recovery 결정 가능 (0-cost)

ibv_wc_status + vendor_err 조합으로 모든 recovery action이 결정됨.
Counter(sysfs/ethtool)는 recovery 결정에 추가 정보를 주지 않음 (전수 조사로 증명).
Counter는 사후 진단용 (firmware retry 분해, monitoring blind spot 증거).

### 5-2. Recovery latency는 에러 유형 무관, method 선택이 지배적

QP-only: ~1.5ms (에러 유형 불문)
Driver reload: ~7.9s
차이: 2,847x — CQE 분류로 QP-only 선택하면 즉시 이 이득을 얻음.

### 6-3. Detection bottleneck은 counter 감시로 해결 가능

| Detection 방법 | 시간 | Total | False positive |
|---|---|---|---|
| NAK 기반 (RNR, REM_ACCESS, REM_INV_REQ) | 수백 us | ~2ms | 없음 |
| Timeout — passive (기존) | 3,738 ms | ~3.7s | 없음 |
| Timeout — active (local_ack_timeout_err) | 1,053 ms | ~1.06s (3.5x) | 거의 없음 |
| Timeout — active (roce_adp_retrans) | 16.6 ms | 18.4ms (203x) | 높음 (threshold 필요) |

Counter의 역할 재정의:
- 분류(WHAT): CQE vendor_err → 변함없음
- 시점(WHEN): counter가 조기 감지 신호 → 수동 대기에서 능동 개입으로
- Counter 선택은 speed vs safety trade-off

### 6-4. Firmware retry 2단계 구조 발견

1단계 Adaptive retransmission: roce_adp_retrans, exponential backoff (~4ms에서 시작, 배증)
2단계 ACK timeout retry: local_ack_timeout_err, ~536ms 고정 간격

roce_adp_retrans가 local_ack_timeout_err보다 ~60x 먼저 증가.
단, roce_adp_retrans는 일시적 congestion에서도 증가 가능 → threshold 정책 필요.

### 6-5. Error NAK = peer liveness 증거

REM_ACCESS_ERR, RNR_RETRY_EXC 등 NAK 기반 에러는 "상대방이 살아있고 응답했다"는 증거.
별도 TCP probe 없이 즉시 recovery 시작 가능.
RETRY_EXC_ERR만 peer liveness 불확실 → TCP control channel로 확인 (이미 recovery 프로토콜에 포함).

### 6-6. QP-only recovery는 다른 QP에 영향을 주지 않는다 (multi-QP isolation)

2 QPs 동시 RDMA WRITE 통신, QP_B에만 fault inject, QP_A throughput 측정.

| Phase | QP_A ops/10ms | vs Baseline |
|---|---|---|
| Baseline (QP_B healthy) | 5,885 | — |
| During fault (QP_B in ERR, 100ms) | 6,036 | +2.6% (오차 범위) |
| After QP_B recovery | 6,046 | +2.7% (오차 범위) |

QP-only recovery 중 QP_A throughput 영향 0%. fault가 다른 QP로 전파되지 않음.

Recovery time 비교 (multi-QP 환경):

| Method | Recovery time | QP_A downtime |
|---|---|---|
| QP-only | 2,453 us | 0 (영향 없음) |
| Full rebuild | 14,995 us | 14,995 us (전체 중단) |

Full rebuild는 모든 QP/PD/CQ/MR을 파괴하므로 정상 QP_A도 중단. QP-only는 6.1x 빠르면서 isolation 보장.

파일: `multi_qp/results/20260518_013055_isolation.csv`

### 6-7. CQE는 per-QP 에러 식별, counter는 port-level 혼합

2 QPs에 서로 다른 에러를 동시 주입:

| QP | Injected fault | CQE status | vendor_err | Detection |
|---|---|---|---|---|
| QP_A | MR deregistered | 10 (REM_ACCESS_ERR) | 0x88 | ~2.1ms |
| QP_B | QP forced ERR | 5 (WR_FLUSH_ERR) | 0xf5 | ~101ms |

CQE: per-QP로 정확한 에러 식별. 10/10 trials deterministic.

Counter delta (port-level, 혼합):

| Counter | Delta | 해석 |
|---|---|---|
| req_cqe_error | +2 | QP_A + QP_B 합산, 어느 QP인지 구분 불가 |
| req_remote_access_errors | +1 | QP_A의 REM_ACCESS, counter만으로는 확인 불가 |
| roce_adp_retrans | +2~4 | QP_B의 retry, 양도 변동 |

결론: counter는 port-level aggregate → multi-QP 환경에서 에러 원인 귀속 불가. CQE가 유일한 per-QP 분류 수단.

파일: `multi_qp/results/20260518_013055_concurrent.csv`

---

## 7. Production 적용 시 recovery decision tree

```
CQE error 수신
  │
  ├── status=13 (RNR_RETRY_EXC), vendor_err=0x87
  │     → QP-only recovery (peer alive 보장, server QP RTS)
  │     → Expected total: ~1.7ms
  │
  ├── status=10 (REM_ACCESS_ERR), vendor_err=0x88
  │     → QP-only + MR refresh (peer alive 보장, Error NAK 수신)
  │     → Expected total: ~1.8ms
  │
  ├── status=9 (REM_INV_REQ), vendor_err=0x8a
  │     → QP-only + MR refresh (peer alive 보장, Error NAK 수신)
  │     → Expected total: ~1.8ms (REM_ACCESS와 동일 메커니즘)
  │
  ├── status=4 (LOC_PROT_ERR), vendor_err=0x53/0x52/0x33
  │     → 자동 복구 불가 (application bug)
  │     → Notify + log (vendor_err로 원인 세분류 가능)
  │
  └── status=12 (RETRY_EXC_ERR), vendor_err=0x81
        → TCP control channel로 peer 접촉 시도
        ├── 응답 있음: QP-only recovery (~2.8ms, total ~3.7s)
        └── 응답 없음: peer dead → escalate (외부 개입)

  [조기 감지 경로] roce_adp_retrans counter 증가 감지 (실측 16.6ms)
        → ibv_modify_qp(ERR) → WR_FLUSH_ERR CQE (~250us)
        → TCP probe → peer 상태 확인
        → QP-only recovery (~1.6ms)
        → 실측 total: 18.4ms (passive 대비 203x)
```
