# Recovery 방법론

> [실험 인덱스와 canonical 수치 기준](README.md)

이 섹션은 RDMA QP가 에러로 진입한 뒤 다시 정상 통신 상태(RTS)로 복귀시키는 세 방법을 비교하고, 어떤 에러에 어떤 방법을 선택해야 하는지를 실측 데이터로 정리한다. 배경부터 짚으면, RC(Reliable Connected) QP는 transport 에러를 만나면 자동으로 ERR 상태로 전이하고, 이후 게시된 모든 WR은 WR_FLUSH_ERR로 flush된다. ERR 상태의 QP는 더 이상 통신할 수 없으므로 application이 명시적으로 복구 절차를 밟아야 한다. 핵심 주장은 셋이다. 첫째, recovery 방법 선택만으로 복구 시간이 2,847× 차이 난다(driver reload 대 QP-only). 둘째, 어떤 방법을 쓸지는 CQE(`ibv_wc_status` + `vendor_err`)만으로 추가 비용 없이 결정된다. 셋째, recovery 자체는 이미 ms 단위로 빠르고 end-to-end 시간의 진짜 bottleneck은 recovery가 아니라 detection이다.

실험 환경은 client 225(ConnectX-6 MT28908, fw 20.40.1000, RDMA IP 10.0.0.2), server 224(ConnectX-5 MT27800, fw 16.35.8002, RDMA IP 10.0.0.3), 100Gbps RoCE v2다. recovery 협상에 쓰는 TCP control channel에 `TCP_NODELAY`를 적용해 Nagle buffering을 제거했다. 각 trial은 setup → fault inject → detect → recover → retry verify → cleanup을 독립적으로 수행하며 method별 N=10이다. NAK 기반 에러는 첫 5 trial(trial 0-4)이 NIC cache warmup(수 ms → 수백 us, 예: REM_ACCESS_ERR 5.3ms→480us, REM_INV_REQ_ERR 3.1ms→489us)을 거치므로 안정값(trial 5-9)을 기준으로 분석한다.

### 3.1 세 가지 recovery method

복구 깊이가 다른 세 방법을 정의한다. 깊을수록 더 많은 자원을 재생성하고 더 느리다.

| Method | 재생성 범위 | 절차 | Latency | 비고 |
|---|---|---|---|---|
| QP-only (+MR) | QP만 | QP를 RESET으로 전이 후 INIT→RTR→RTS 재구동 + 양쪽 PSN 재협상 + (필요 시 MR 재교환) | 1.3–2.8 ms | PD, CQ 재활용 |
| Full rebuild | PD/CQ/QP/MR 전부 | 모든 자원 파괴 후 재생성 | 6.9–9.6 ms | 새 자원 할당 비용 포함 |
| Driver reload | 커널 모듈 전체 | `modprobe -r mlx5_ib` → `modprobe mlx5_ib` → device init → GID table 재생성 → 전체 자원 재생성 | 7,889 ms (7.9 s) | QP-only 대비 2,847× |

QP-only는 QP를 RESET 상태로 내렸다가 다시 RTR을 거쳐 RTS까지 올리는 state machine 재구동이다. PD/CQ/MR은 그대로 두므로 가장 빠르다. PSN(Packet Sequence Number)은 RESET을 거치면서 초기화되므로 양쪽이 RTR 전이 시점에 새 PSN을 교환해야 하며, 이 재협상은 양쪽 모두 수행해야 한다(3.4절).

Full rebuild는 PD/CQ/QP/MR을 전부 파괴하고 새로 만든다. MR 재등록, CQ 재할당 등 추가 자원 할당이 들어가 QP-only보다 느리다. 에러 유형별 QP-only 대비 full rebuild 비율은 3.5×–5.5×다(RETRY_EXC_ERR 9,633/2,773 = 3.47×가 최소, RNR_RETRY_EXC_ERR 7,793/1,416 = 5.50×가 최대). QP-only로 충분한 상황에서 full rebuild를 쓰는 것은 불필요한 over-recovery다.

Driver reload는 커널 모듈을 내렸다 올리는 것으로, device init과 GID table 재생성까지 포함해 7.9초가 걸린다. 이는 전체 NIC를 리셋하므로 같은 NIC를 쓰는 다른 모든 QP/연결도 함께 중단된다. 단일 QP 에러를 driver reload로 복구하는 것은 QP-only 대비 약 2,847× 더 비싼 선택이다(RETRY_EXC_ERR 기준 driver reload recovery 7,889,068us / QP-only recovery 2,773us ≈ 2,845, 요약 문서 표기 2,847).

### 3.2 에러 유형별 detect + recover + retry

NAK 기반 에러 4종(RNR_RETRY_EXC_ERR / REM_ACCESS_ERR / REM_INV_REQ_ERR / RETRY_EXC_ERR)에 대해 detection, recovery, retry verify를 분리 측정했다. 각 fault scenario는 다음과 같다.

| 에러 유형 | Fault scenario | 감지 경로 |
|---|---|---|
| RNR_RETRY_EXC_ERR | server가 recv buffer를 게시하지 않은 상태(recv buffer 부족)에서 client SEND → RNR NAK 즉시 반환 | rnr_retry=0이라 재전송 없이 즉시 소진 |
| REM_ACCESS_ERR | server가 MR을 `ibv_dereg_mr`로 해제 → client가 stale rkey(invalid rkey)로 RDMA WRITE | Error NAK 즉시 반환 |
| REM_INV_REQ_ERR | server MR을 `IBV_ACCESS_LOCAL_WRITE`만으로 등록(REMOTE_WRITE 권한 없음) → client RDMA WRITE | Error NAK 즉시 반환 |
| RETRY_EXC_ERR | server QP를 `ibv_modify_qp(ERR)`로 강제 전이(서버 QP ERR) → ACK 끊김 → client의 timeout retry 소진 | retry_cnt=7 + adaptive retransmission 소진 |

QP-only recovery 기준 측정값:

| 에러 유형 (status / vendor_err) | Detect | Recover | Retry | Total | N |
|---|---|---|---|---|---|
| RNR_RETRY_EXC_ERR (13 / 0x87) | 245 us | 1,416 us | 10 us | 1,671 us | 10 |
| REM_ACCESS_ERR (10 / 0x88) | 480 us | 1,342 us | 8 us | 1,830 us | 10 |
| REM_INV_REQ_ERR (9 / 0x8a) | 489 us | 1,310 us | 8 us | 1,818 us | 10 |
| RETRY_EXC_ERR (12 / 0x81) | 3,738,010 us | 2,773 us | 4 us | 3,740,787 us | 10 |

> Detect/Recover/Retry 세 컬럼은 각각 독립적으로 평균낸 값이고 Total은 trial별 end-to-end 측정값의 평균이므로, 반올림된 컬럼 합과 Total이 정확히 일치하지 않을 수 있다. REM_INV_REQ_ERR이 그 예다: 컬럼 합은 489 + 1,310 + 8 = 1,807us지만 측정 total은 1,818us(약 11us 차이). 다른 행은 컬럼 합과 total이 일치한다.

Full rebuild는 recovery만 6.9–9.6ms로 늘고 detection은 동일하다(detection은 recovery method와 무관 — NIC이 에러를 감지하는 시점은 어떤 복구를 쓸지와 상관없이 같음):

| 에러 유형 | QP-only recover | Full rebuild recover |
|---|---|---|
| RNR_RETRY_EXC_ERR | 1,416 us | 7,793 us |
| REM_ACCESS_ERR | 1,342 us | 6,878 us |
| REM_INV_REQ_ERR | 1,310 us | 6,960 us |
| RETRY_EXC_ERR | 2,773 us | 9,633 us |

두 가지를 읽어낼 수 있다. 첫째, recovery latency는 에러 유형에 거의 무관하다. QP-only는 모든 에러에서 1.3–2.8ms 범위다. 절차가 같으면 시간도 같다. RETRY_EXC_ERR만 약 1.4ms 더 느린데(2,773us vs NAK 기반 1.3–1.4ms), 이는 3.7초 동안 firmware가 쌓은 retry state를 정리하는 비용이다. 같은 맥락으로 QP를 ERR→RESET으로 전이시키는 것이 RTS→RESET보다 약 1.3ms 더 걸린다(firmware error context cleanup, order of magnitude는 동일). 둘째, end-to-end total을 지배하는 것은 recovery가 아니라 detection이다. NAK 기반 에러는 total이 1.7–1.8ms인 반면, RETRY_EXC_ERR는 recovery가 2.8ms임에도 detection 3.7s 때문에 total이 3.74s다.

REM_ACCESS_ERR과 REM_INV_REQ_ERR은 수치가 사실상 동일하다(detect 480 vs 489us, recover 1,342 vs 1,310us, total 1,830 vs 1,818us). 둘 다 같은 Error NAK 분류이고, 같은 recovery 절차(QP reset + server MR 재등록 + PSN/rkey/addr 교환)를 따르므로 같은 latency가 나온다. MR 재등록이 절차에 추가되지만 latency 차이는 무시 가능한 수준(약 100us, 요약 문서 서술 기반 추정)이다.

### 3.3 CQE sufficiency: recovery 결정은 0-cost

recovery 방법을 고를 때 HW counter(sysfs/ethtool/register)를 읽을 필요가 없다. `ibv_wc_status`와 `vendor_err`만으로 모든 recovery action이 결정된다. 이는 counter를 전수 조사했기에 "충분하다"고 단정할 수 있다(counter mapping 실험에서 ethtool 2,394개 counter 중 recovery 결정을 바꾸는 것이 없음을 확인. 단 분류 관점에서는 ethtool 트래픽 counter의 변화 패턴이 RETRY_EXC_ERR 두 원인을 구분해 해상도를 8/10에서 9/10으로 올린다 — theory 문서의 counter 관측성 참조).

| 에러 (status / vendor_err) | CQE만으로 구분되는가 | Counter가 추가 정보를 주는가 |
|---|---|---|
| LOC_PROT_ERR (4 / 0x53·0x52·0x33) | YES — SGE length 초과·invalid lkey·MR 권한 위반 3종 완전 구분 | NO |
| WR_FLUSH_ERR (5 / 0xf5) | YES | NO |
| REM_INV_REQ_ERR (9 / 0x8a) | YES | NO |
| REM_ACCESS_ERR (10 / 0x88) | invalid rkey와 주소 범위 초과를 미구분, 단 recovery 동일이라 무방 | NO — counter도 못 구분 |
| RNR_RETRY_EXC_ERR (13 / 0x87) | YES | NO |
| RETRY_EXC_ERR (12 / 0x81) | 서버 QP ERR vs 프로세스 종료(kill) 미구분 | 제한적 — sysfs retry counter는 두 원인 동일(N=30), ethtool non-RDMA traffic(tx_vport_unicast 12-13 vs 8)으로만 사후 구분. critical path 판정은 TCP probe |

CQE는 WR 완료 시 이미 메모리(completion queue)에 들어와 있으므로 읽는 비용이 0이다. 반면 counter read는 약 7.5ms로 측정되어 recovery(2.8ms)보다 느리다. 따라서 counter는 critical path에서 제외하고 사후 진단(firmware retry 분해, monitoring blind spot 증거 수집)으로만 위치시킨다. 단, RETRY_EXC_ERR에서 "서버 QP가 ERR로 빠졌는지(peer alive)" vs "프로세스가 죽었는지(peer dead)"는 CQE로도 sysfs counter로도 구분 불가하며(ethtool non-RDMA traffic 사후 구분은 가능 — counter mapping 실험), 이때만 TCP probe(약 수백 us)가 critical path에 들어간다.

| Layer | 역할 | Cost | Critical path? |
|---|---|---|---|
| CQE (status + vendor_err) | recovery 방법 결정 | 0 | YES |
| TCP probe | RETRY_EXC_ERR의 peer alive/dead 구분 | 약 수백 us | YES (이 에러만) |
| sysfs/ethtool counter | 사후 진단, firmware 분해 | 7.5 ms | NO |

### 3.4 흔한 오해 세 가지 바로잡기

#### Detection이 진짜 bottleneck이다

recovery 절차를 아무리 최적화해도 NAK가 오느냐 timeout을 기다리느냐가 전체 시간을 결정한다.

| 에러 유형 | Detection | 메커니즘 |
|---|---|---|
| RNR_RETRY_EXC_ERR | 245 us | RNR NAK 즉시 리턴, rnr_retry=0이라 재전송 없음 |
| REM_ACCESS_ERR | 480 us | Error NAK 즉시 리턴, IBA상 Error NAK은 재전송 불가 |
| REM_INV_REQ_ERR | 489 us | Error NAK 즉시 리턴 |
| RETRY_EXC_ERR | 3,738,010 us | Timeout retry exhaustion (retry_cnt=7 + adaptive retransmission) |

NAK 기반 에러는 수백 us, timeout 기반 에러는 3.7초로, 3,738,010 / 489 ≈ 7,600×(REM_INV_REQ_ERR 대비)에서 3,738,010 / 245 ≈ 15,300×(RNR_RETRY_EXC_ERR 대비)까지 차이다(요약 문서는 1,000x약 10,000x로 어림). RETRY_EXC_ERR에서 recovery를 2.8ms로 줄여도 total이 3.74s인 이유가 여기 있다. RETRY_EXC_ERR 계열의 개선 여지는 recovery가 아니라 detection 단축([2. Early detection](02_early_detection.md))에 있다.

#### Error NAK = peer liveness 증거 (TCP probe 불필요)

NAK 기반 에러(RNR_RETRY_EXC_ERR, REM_ACCESS_ERR, REM_INV_REQ_ERR)에서 NAK이 도착했다는 사실 자체가 "상대가 살아 있고 응답했다"는 증거다. 별도 TCP probe로 peer liveness를 확인할 필요 없이 즉시 recovery를 시작할 수 있다. 오직 RETRY_EXC_ERR(timeout)만 peer가 ACK를 끊은 이유가 "QP가 ERR로 빠짐"인지 "프로세스가 죽음(kill)"인지 불확실하므로 TCP control channel로 확인한다.

#### "원격측 조치 불필요"는 틀린 표현이다

QP-only recovery는 양쪽 PSN 재협상이 필수다. RESET을 거치면 PSN이 초기화되므로 한쪽만 reset해서는 sequence가 어긋나 재연결이 불가능하다. 즉 어떤 NAK 기반 에러든 "원격측은 가만히 있어도 된다"는 서술은 부정확하다. 차이는 원격측이 조치를 하느냐 마느냐가 아니라 coordination 수준에 있다.

| 에러 | 원격(server) QP 상태 | 원격이 해야 할 일 |
|---|---|---|
| RNR_RETRY_EXC_ERR | RTS (건강) | RTS→RESET 후 PSN 재협상 |
| REM_ACCESS_ERR | RTS (MR만 dereg됨) | RTS→RESET + 새 MR 등록 + PSN/rkey/addr 재교환 |
| REM_INV_REQ_ERR | RTS (MR 권한 부족) | RTS→RESET + REMOTE_WRITE 포함 MR 재등록 + 재교환 |
| RETRY_EXC_ERR | ERR | ERR→RESET 후 PSN 재협상 |

RNR_RETRY_EXC_ERR처럼 server QP가 RTS로 건강한 경우조차 PSN 재협상을 위해 RESET을 거쳐야 한다. coordination 비용이 가장 낮은 경우(RNR_RETRY_EXC_ERR, 단순 PSN 교환)부터 가장 높은 경우(REM_ACCESS_ERR/REM_INV_REQ_ERR, MR 재등록 + rkey/addr 재교환)까지 스펙트럼이 있을 뿐, 원격 무개입은 어디에도 없다.

### 3.5 Recovery decision tree

CQE 수신 시 method를 고르는 결정 트리다. 모든 분기 판단은 CQE(0-cost)로 하고, RETRY_EXC_ERR에서만 TCP probe를 추가한다.

```
CQE error 수신
  │
  ├── status=13 (RNR_RETRY_EXC_ERR), vendor_err=0x87
  │     → QP-only recovery (peer alive 보장, server QP는 RTS)
  │     → Expected total: ~1.7ms
  │
  ├── status=10 (REM_ACCESS_ERR), vendor_err=0x88
  │     → QP-only + MR refresh (peer alive 보장, Error NAK 수신)
  │     → Expected total: ~1.8ms
  │
  ├── status=9 (REM_INV_REQ_ERR), vendor_err=0x8a
  │     → QP-only + MR refresh (REM_ACCESS_ERR와 동일 메커니즘)
  │     → Expected total: ~1.8ms
  │
  ├── status=4 (LOC_PROT_ERR), vendor_err=0x53/0x52/0x33
  │     → 자동 복구 불가 (application bug)
  │     → Notify + log (vendor_err로 원인 세분류: SGE length 초과 / invalid lkey / MR 권한 위반)
  │
  └── status=12 (RETRY_EXC_ERR), vendor_err=0x81
        → TCP control channel로 peer 접촉 시도
        ├── 응답 있음: QP-only recovery (~2.8ms, but total ~3.7s — detection 지배)
        └── 응답 없음: peer dead → escalate (외부 개입)
```

요약하면 NAK 기반 에러는 전부 QP-only로 ms 단위에 복구 가능하고(REM_ACCESS_ERR/REM_INV_REQ_ERR는 MR refresh 추가), LOC_PROT_ERR은 application bug라 자동 복구 대상이 아니며, RETRY_EXC_ERR만 TCP probe로 peer 생사를 가른 뒤 분기한다. RETRY_EXC_ERR의 3.7s detection 자체를 줄이는 능동적 counter 감시(roce_adp_retrans 기반 18.4ms, 203× 단축) 경로는 [2. Early detection](02_early_detection.md)에서 다룬다. Full rebuild나 driver reload는 이 트리의 어떤 정상 경로에도 등장하지 않는다 — 둘은 각각 약 5×(범위 3.5×–5.5×), 약 2,847× 더 비싼 over-recovery이며, QP-only로 충분하지 않은 예외 상황(자원 자체 손상, NIC 전체 hang 등)에서만 fallback으로 고려한다.
