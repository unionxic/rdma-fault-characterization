# Partial write와 data-plane 복원, A/B recovery 실험

> [실험 인덱스와 canonical 수치 기준](README.md)

### 5.1 왜 이 문제인가 — control-plane은 보이는데 data-plane은 안 보인다

지금까지의 에러 분석은 전부 control-plane 신호였다. CQE의 `ibv_wc_status`, `vendor_err`, hw_counter는 "에러가 났다, 어떤 종류다"를 알려주지만, 정작 서버 메모리에 무엇이 써졌는가 — data-plane 상태 — 는 한 글자도 알려주지 않는다.

이 사각지대가 가장 위험해지는 지점이 partial write다. RDMA WRITE 하나가 절반만 서버에 commit되고 에러로 끝났을 때, 서버에는 "새 데이터 일부 + 옛 데이터 일부"가 섞인 corrupt 상태가 남는다. 이 섹션은 셋을 다룬다.

1. partial write가 정확히 어떤 메커니즘으로 발생하며 어디까지 써지는가
2. requester가 서버 협조 없이 써진 바이트를 복원할 수 있는가
3. 이 복원 능력을 recovery 전략(reactive vs proactive)에 어떻게 쓰는가

관련 배경(REM_ACCESS_ERR, NAK, 서버 responder pipeline)은 theory 문서의 에러 분류 체계와 responder pipeline에 있으므로 여기서는 partial write 자체와 data-plane 복원에만 집중한다.

### 5.2 RDMA WRITE의 패킷 분할 메커니즘

RDMA WRITE는 단일 atomic operation처럼 보이지만 wire 위에서는 PMTU(Path MTU, 본 실험에서는 1024B = `IBV_MTU_1024`) 단위로 쪼개진다. 메시지 크기에 따라 packet opcode가 달라진다.

| 메시지 크기 | 패킷 구성 | RETH(주소 헤더) 위치 |
|---|---|---|
| ≤ PMTU | WRITE_ONLY 1개 | 그 패킷에 |
| > PMTU | FIRST → MIDDLE … → LAST | FIRST에만 |

핵심은 RETH(RDMA Extended Transport Header, 목적지 주소 + rkey + length)가 FIRST 패킷에만 들어간다는 점이다. 이후 MIDDLE/LAST 패킷에는 주소 헤더가 없고, responder가 PSN(Packet Sequence Number) 순서로부터 암묵적 주소를 이어서 계산한다. 즉 responder는 각 패킷을 받을 때마다 주소를 PSN으로부터 산출해 순차적으로 검증하고 commit한다.

responder의 동작 원칙 두 가지가 partial write의 모든 것을 결정한다.

1. 패킷 단위 순차 commit + rollback 없음. responder는 패킷 하나를 검증 통과시키면 즉시 DMA로 서버 메모리에 쓴다. 뒤 패킷이 실패해도 이미 쓴 앞 패킷을 되돌리지 않는다(no rollback).
2. 부분 패킷은 존재하지 않는다. 검증도 패킷 통째로, commit도 패킷 통째로 한다.

이 두 원칙에서 두 시나리오가 갈린다(서버 MR 4096B, N=10, deterministic 측정 — theory 문서의 partial write 표와 동일 데이터).

| 시나리오 | 조건 | 결과 |
|---|---|---|
| single-packet straddle | MR 경계가 한 패킷 안을 가로지름 | 그 패킷 통째 거부 → NO_WRITE (0B 기록) |
| multi-packet straddle | MR 경계가 패킷 경계 사이에 떨어짐 | 경계 앞 온전한 패킷들만 commit → partial write |

핵심 귀결: partial write로 서버에 써진 바이트 수는 항상 PMTU의 정수배다. 부분 패킷이 원리적으로 없으므로 "1024B의 절반"처럼 어중간한 길이는 나올 수 없다. 이는 theory 문서의 multi_pkt_cross 관찰(offset=2048, len=4096인 4패킷 중 MR 안 2패킷 = 2048B만 기록, MR 밖 0B)과 정확히 일치한다.

### 5.3 실험: sq_psn으로 data-plane 복원 (NAK 한정)

#### 측정 원리

`ibv_query_qp(IBV_QP_SQ_PSN)`를 WRITE 직전과 직후에 호출해 sq_psn의 증가분(delta)을 본다.

서버 실제 기록 바이트 = sq_psn_delta × PMTU

핵심 통찰: sq_psn은 post한 패킷 수가 아니라 ACK된 패킷 수만 센다. NAK 에러가 나면 responder가 NAK과 함께 마지막으로 정상 처리한 PSN 경계를 알려주고, requester의 sq_psn이 그 경계로 retreat한다(go-back-N, 추론 — 외부 관측 기반, firmware 소스 미확인). 따라서 `sq_psn_after`는 서버가 실제로 commit한 마지막 패킷 경계와 일치한다. 서버 메모리를 읽거나 peer의 협조를 받을 필요 없이 requester가 `ibv_query_qp` 한 번으로 partial write 바이트를 안다.

#### 1차 측정 (N=10, deterministic)

환경: 클라이언트 225(ConnectX-6, 디바이스 rocep1s0f0 자동 선택), 서버 224(mlx5_0, ConnectX-5), PMTU=1024, 서버 MR=4096B, 주소 범위 초과(REM_ACCESS_ERR) 유발. 코드: `05_counter_mapping/verify_partial_write.c`, 224 `server.c`의 CHECK_BUFFER(last_mod offset). 결과: `results/raw/partial_write_verify.csv`. 아래 표의 ground truth는 서버가 자기 버퍼를 직접 검사해 얻은 실제 기록 바이트다.

| Test case | WRITE 크기 | sq_psn_delta | delta × PMTU | ground truth(서버 기록) | 일치 |
|---|---|---|---|---|---|
| multi_pkt_cross | 4KB (offset 2048, MR안 2048B) | 2 | 2048 | 2048 | O |
| single_pkt_cross | straddle 1패킷 (offset 4064, len 64) | 0 | 0 | 0 (NO_WRITE) | O |
| barely_1B_inside | straddle 1패킷 (offset 4095, len 64) | 0 | 0 | 0 (NO_WRITE) | O |

#### MTU 비정렬 검증 (2026-06-02)

partial write가 PMTU 정수배라는 주장이 비정렬 주소/길이에서도 robust한지 확인했다. within_mod는 서버 검사로 얻은 실제 기록 바이트(ground truth)다.

| Test case | 상황 | sq_psn_delta | delta × PMTU vs within_mod |
|---|---|---|---|
| unaligned_boundary | MR안 가용 2560B → 2048B만 기록 | 2 | 오차 0 |
| unaligned_offset | offset 2560 비정렬 → 첫 패킷도 full 1024B | 1 | 오차 0 |
| three_pkt_partial | 3072B 기록 | 3 | 오차 0 |

결론: straddle 패킷은 통째 거부되고 첫 패킷도 full PMTU(1024B)이므로, partial write는 비정렬 주소/길이에서도 항상 PMTU 정수배다. 부분 패킷은 원리적으로 없고, sq_psn_delta × PMTU 복원이 비정렬에도 robust하다.

#### 폐기된 신호: byte_len

에러 CQE의 `byte_len`은 run마다 garbage 값이었다(1차 0, 2차 32767). RDMA WRITE 에러 CQE에서 byte_len은 정의되지 않은 필드다. data-plane 복원에 무용 — 폐기.

#### 전제 검증: ERR 상태 QP에서 sq_psn 유효

에러가 난 뒤 query하는 이 방법의 전제는 "ERR 상태로 전이한 QP에서도 `ibv_query_qp(SQ_PSN)`가 유효값을 반환한다"이다. mlx5 ConnectX-6에서 이를 확인했다.

### 5.4 silent failure는 복원 불가 — 복원 가능 여부가 에러를 가른다

sq_psn 복원이 모든 에러에 통하는 것은 아니다. 결정적 경계는 NAK이 돌아오느냐다.

silent failure(timeout / peer death = 서버 QP ERR, 프로세스 kill, link down) 경로를 검증했다(2026-06-02, N=100, 4MB WRITE race, 서버 MR=8MB). 코드: `verify_interrupted_write.c`(225) + `server.c` SETUP_LARGE/INTERRUPT/CHECK_LARGE(224). "race"는 클라이언트가 4MB WRITE를 진행하는 도중 서버가 QP를 끊어, 끊긴 시점에 따라 써진 양이 매 run 달라지는 비결정적 상황을 가리킨다.

| 항목 | NAK 경로 (주소 위반) | silent 경로 (timeout / peer death) |
|---|---|---|
| partial 발생 | 발생 | 발생 (PARTIAL 52 / FULL 48 / NO_WRITE 0) |
| partial이 PMTU 정수배 | 항상 | 항상 (52/52, 두 경로 공통) |
| sq_psn 의미 | ACK 경계로 retreat | transmitted(post한 전체) 그대로 |
| sq_psn 복원 정확도 | 100% (N=10) | 0/52 (delta=4096=전체 4MB이나 실제 기록은 1.4–4.1MB로 무관) |

이유: 서버 QP ERR / death는 NAK 없이 패킷을 silent drop한다. requester는 전 패킷을 transmit하고 sq_psn이 transmitted 값(4MB / 1024B = 4096 패킷)에 머문다. 반면 주소 위반은 NAK이 sq_psn을 ACK 경계로 retreat시켜 일치했던 것이다. 한편 클라이언트 측 local ERR 전이 자체는 sq_psn을 망치지 않았다(query로 읽은 delta가 CQE가 보고한 패킷 수와 52/52 일치).

핵심 함의:

| 에러 카테고리 | partial 발생 | 복원 가능 | 위험도 |
|---|---|---|---|
| NAK (주소 위반 / invalid rkey) | 조건부(multi-packet straddle) | 가능 (sq_psn) | 중 — 복원으로 대응 가능 |
| silent (timeout / peer death) | 가능 | 불가능 (requester-invisible) | 최대 — sq_psn / counter 모두 경계 못 줌 |

silent failure는 production RETRY_EXC_ERR의 주원인(production 보고에서 압도적 1위)인데, 바로 그 경로에서 partial write가 requester에게 완전히 보이지 않는다. application checksum / sentinel이 불가피하다. 또한 silent partial은 MR 에러가 아니라 peer liveness 카테고리(서버가 MR 검증 단계에 도달하기 전 응답 자체가 없음)이므로, recovery 분류상 MR 에러와 별개 축이다.

### 5.5 에러 가시성의 비대칭 — 서버는 partial을 모른다

partial write가 위험한 두 번째 이유는 서버 측 가시성이다. RDMA WRITE는 one-sided이므로 서버 NIC이 자체 처리하고 서버 소프트웨어에 CQE를 생성하지 않는다(theory 문서의 responder pipeline 참조). 따라서 서버에는 partial corruption을 알리는 CQE도 error counter도 없다. 서버 애플리케이션이 corrupt된 버퍼를 정상인 줄 알고 읽을 수 있다.

이 비대칭은 application-level 방어를 요구한다.

| 방어 수단 | 원리 | partial 탐지 범위 |
|---|---|---|
| sentinel value | 버퍼 끝에 magic 값을 두고 write 후 확인 | 마지막 패킷 미도착 탐지 |
| WRITE_WITH_IMM | write 완료 시 서버에 immediate로 completion 통지 | 전체 완료 여부만 (부분 여부 아님) |
| application checksum | 데이터 무결성 검증 | partial corruption 탐지 |

### 5.6 A/B recovery 실험: reactive vs proactive

#### 설계

복원 능력(sq_psn)을 실제 recovery에 쓰는 두 전략을 비교한다. scope는 NAK(REM_ACCESS_ERR, 주소 위반) 한정 — silent는 5.4에서 본 대로 복원 불가라 reactive만 가능하다.

| 전략 | 동작 | 정상 경로 비용 | 에러 경로 |
|---|---|---|---|
| A (reactive) | 경계 체크 없이 write → REM_ACCESS_ERR → sq_psn으로 partial 경계 복원 → QP-only recovery → 올바른 단일 MR로 통째 재전송 | 체크 없음 | 복구 + corruption window |
| B (proactive) | 협상받은 MR 경계로 write 전 로컬 검증(addr + len ≤ 경계) → 위반이면 안 보내고 교정 | per-WRITE 범위 체크 | partial 미발생 |

가정: "올바른 목적지 주소를 안다"고 전제(실제 앱의 주소 결정은 별개 문제). MR 경계는 협상으로 정적으로 안다고 전제(동적 등록/해제 환경이면 stale 위험).

#### 셋업 (2026-06-04)

조합(combo)당 N=10000. 에러율 err ∈ {0%, 1%, 10%} × 메시지 크기 msg ∈ {1024B(single-packet), 4096B(multi-packet)}, 서버 MR=65536B. 코드: `05_counter_mapping/ab_recovery.c`, `run_ab_recovery.sh`, `server.c`의 `handle_*_ab`, `common.h`의 `CMD_*_AB`.

#### 결과 — B 전 영역 압승

| 지표 | A (reactive) | B (proactive) |
|---|---|---|
| 정상 latency (err 0%) | 2.34 us | 2.32 us (오차 범위, 동률) |
| 에러당 recover 비용 | 42.7 ms | 2 us |
| corruption window | 44.9–45.1 ms | 0 (사전 차단) |
| total_wall (err 1%) | 4.6M us (228배) | 25k us |
| total_wall (err 10%) | 46M us (1851배) | 25k us |
| 에러 후 정상 latency 안정성 | 상승 (err 10% p99 43us, QP reset 여파) | 안정 (QP 안 깨짐) |

해석:

- 예상이 빗나간 지점: "에러율이 낮으면 B의 per-WRITE 체크 오버헤드 때문에 A가 유리, break-even point가 있을 것"으로 예상했으나, B의 체크 비용이 측정 불가 수준(err 0%에서 A 2.34us vs B 2.32us)이라 break-even이 없었다. err 0%만 동률이고 에러가 1건이라도 섞이면 B 우위.
- A의 2차 손해: A는 에러마다 QP를 ERR → reset해야 하므로 에러 이후의 정상 WRITE latency까지 상승한다(err 10% p99 43us). B는 QP를 깨지 않아 안정적이다.

아티팩트 정정(2026-07-15 검토): 위 표의 A recover 42.7ms는 224 `05_counter_mapping/server.c`의 accept 소켓에 TCP_NODELAY가 빠져 있어 A 전략의 lockstep TCP 재협상 왕복마다 40ms delayed-ACK floor가 낀 값이다(ab_recovery.csv A recover 42,603 ± 436us, min 41,088 — 고정 40ms + 실작업 약 2.6ms 시그니처). 같은 시퀀스인 06_recovery의 QP-only 2,773us는 서버 accept 소켓에 NODELAY가 있어 정상이었다. 수정은 양쪽 server.c에 반영 완료했고, 수정 후 [silent 전략 실험](07_silent_partial_strategy.md)에서 동일 recover가 2,833–2,889us로 실측되어 아티팩트 해소를 검증했다(42ms 재현 0/300). 따라서 total_wall의 228배/1851배는 과대이며 재실행 시 약 1/15로 줄어들 것으로 추정한다 — 단 B recover가 2us이므로 B 압승 결론은 불변이다. corruption window 44.9–45.1ms도 측정 전용 CHECK_AB 왕복 + 42.6ms recover가 포함된 이중 오염 값이라 대표성이 없다. ab_recovery 재실행 시 corruption window 정의에서 검증 왕복을 분리할 것.

#### 검증

| 검증 항목 | 결과 |
|---|---|
| recon_match (sq_psn_delta × PMTU = 서버 truth) | 4400/4400 정확 |
| single-packet(1024B) 위반 NO_WRITE (delta=0) | 1100건 일치 |
| multi-packet(4096B) delta | 2 → 2 × 1024 = 2048B = truth |

#### 함의

예측 가능한 에러(MR 경계는 협상으로 미리 안다)에서는 proactive 차단이 reactive 복구를 일방적으로 압도한다. 흔히 가정하는 "성능 vs 안전 trade-off"가 아니라 일방 우위다 — B가 더 빠르고(에러 시 1851배) 동시에 더 안전하다(corruption window 0).

반대로 timeout 등 예측 불가능한 에러는 B(사전 체크) 자체가 불가능하고 reactive만 남는다. 즉 에러 분류의 실용적 가치는 "proactive로 막을 수 있는가"로 가름된다 — 복원 가능 여부(5.4)와 예측 가능 여부가 recovery 전략을 결정하는 두 축이다.

### 5.7 미해결 / 재확인 대상

| 항목 | 내용 |
|---|---|
| ab_recovery 재실행 | TCP_NODELAY 아티팩트(5.6절 정정 참조) 수정 후 재실행해 42.7ms 포함 데이터를 대체할 것. corruption window 정의에서 CHECK_AB 검증 왕복 분리 포함. |
| 타 NIC 재현 | 전 실험이 ConnectX-6 requester 단일 NIC. sq_psn retreat / PMTU 정수배 동작의 일반화는 [TODO: 타 NIC 재현 필요]. |
| go-back-N retreat 메커니즘 | sq_psn이 ACK 경계로 retreat한다는 메커니즘은 외부 관측 기반 추론. firmware 소스 미확인. |
| MR 경계 동적 변경 | B는 MR 경계 정적 전제. 동적 등록 / 해제 환경에서 stale 가능성 미검증. |
| silent partial 대응 | silent failure의 partial은 sq_psn으로 복원 불가 → checkpoint / application checksum 등 recovery 2–3단계 영역. 본 실험 scope 밖. |
