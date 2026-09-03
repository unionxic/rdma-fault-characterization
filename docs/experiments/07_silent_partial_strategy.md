# Silent partial 대응 전략 비교 (commit 가시성)

> [실험 인덱스와 canonical 수치 기준](README.md)

### 7.1 왜 이 실험인가 — 복원이 아니라 판별로 재프레이밍

[partial write 실험 5.4절](05_partial_write_ab_recovery.md)의 결론은 silent failure(timeout / peer death) 경로의 partial write가 requester-invisible이라는 것이었다(sq_psn도 counter도 경계를 못 준다). 문헌 조사(2026-07-15) 결과 이 결론은 기존 연구와 일치하며, 대응은 전부 receiver-side 검증 계열이다: Tailwind(ATC'18)는 RDMA 로그 복제의 partial write를 entry별 checksum으로 감지하고, FaRM은 per-cacheline version으로 torn read를 감지하며, IBTA spec 1.5(2021)의 Memory Placement Extensions(RDMA FLUSH + ATOMIC WRITE verb)는 write-then-commit 패턴을 하드웨어로 표준화한 것이다.

여기서 문제를 재프레이밍한다. WRITE requester는 원본 데이터를 항상 보유하므로, silent partial의 실제 위험은 데이터 손실이 아니라 소비자가 torn prefix를 완전한 데이터로 읽는 것이다. 필요한 것은 바이트 경계 복원이 아니라 valid/invalid 판별, 즉 commit 가시성이다.

### 7.2 세 전략과 셋업

| 전략 | 원리 | 정상경로 비용 구조 |
|---|---|---|
| C1 commit-flag | payload WR 뒤 별도 flag WR (RC는 같은 QP 내 WR 순서 보장) | O(1) — WR 1개 추가 |
| C2 per-message CRC32C | 메시지에 checksum을 실어 self-describing하게 만듦 | O(len) — 길이 비례 계산 |
| C3 read-back | 재연결 후 requester가 READ-back diff로 경계 파악 | 0 — 에러 시에만 비용 |

셋업(2026-07-15): 4MB WRITE 도중 responder QP를 ERR로 전이(mid-transfer silent fault). 정상경로 N=1000 × 메시지 크기 {4KB, 64KB, 1MB, 4MB}, 에러경로 N=100/전략. 코드: `05_counter_mapping/silent_strategy.c` + `run_silent.sh` + 224 `server.c`의 C핸들러. CSV: `results/raw/silent_strategy.csv`(320행).

### 7.3 결과 — C3 전 구간 우위, 서열은 에러율이 아니라 소비자 능력

| 지표 | C1 commit-flag | C2 CRC32C | C3 read-back |
|---|---|---|---|
| 정상경로 오버헤드 | +약 1us 상수 | +89% @4MB (+331us/op) | 0 (C0 대비 동률) |
| 에러당 total (4MB PARTIAL) | 4,164us | 5,130us | 4,003us (최저) |
| 판별 비용 | 1 TCP RTT (약 503us) | CRC 재계산 | READ-back, resend 2.23MB = 통째 대비 -46.9% |

C3(read-back)가 정상경로 0 + 에러당 최저로 전 구간 Pareto 우위다. break-even은 없다. 서열을 가르는 것은 에러율이 아니라 소비자 능력이다: 소비자가 read-back 가능하면 C3, 제어채널만 있으면 C1, inline 소비자라 self-describing이 필수면 C2만 정당화된다.

total의 구성: detect(433us, 강제 flush 약 10%) + recover(약 2,850us, 68% 지배) + judge + resend. recover가 지배하므로 전략 간 차별화는 정상경로 오버헤드 + judge + resend에서만 남는다.

검증된 것:

- recover 2,833–2,889us — [5.6절](05_partial_write_ab_recovery.md) TCP_NODELAY 아티팩트 수정의 유효성 확정(42ms 재현 0/300, max total 6.4ms). [recovery 실험](03_recovery.md)의 QP-only 2,773us와 정합.
- partial이 PMTU 정수배임을 재확인: C1/C3 100/100 정수배, C2는 (payload+16B 헤더)가 정수배(위반 아님).
- 판별 정확도 300/300 — 단 300 트라이얼 전부 PARTIAL이었다는 한계가 있다(아래).
- C2 CRC 처리율 3.0→12.7GB/s(고정비 + 선형) — O(len) 비용 구조 확인.

### 7.4 남은 이슈 (논문 인용 전 처리)

| 이슈 | 내용 |
|---|---|
| C2 judge 수치 오염 | judge_us 1,408us는 bimodal(461us 33건 / 2,019us 56건)이고 payload 크기와 음의 상관(-0.208) — CRC 비용이 아니라 VERIFY_CRC 제어교환의 코디네이션 stall(delayed-ACK/Nagle류 잔존 의심). CRC 실비용은 정상경로의 약 330us가 참값. 인용 시 disclaim 필수, 서버측 판별 경로 재점검 후 재실행 권장 |
| FULL/NO_WRITE 미검증 | 300 트라이얼 전부 PARTIAL — 판별기 specificity와 C1 고유 false-negative(FULL인데 flag WR만 유실된 경우)가 미검증. settle_ms 스윕(짧게 → NO_WRITE, 길게 → FULL 유도)으로 보강 필요. "정확도 100%"는 PARTIAL 한정 서술 |
| C2 정상경로 tail | 64KB p99 39us vs p50 14us — canonical 인용은 p50 권장 |

### 7.5 recovery 전략 지도에서의 위치

[A/B 실험 5.6절](05_partial_write_ab_recovery.md)과 합치면 에러 분류 → recovery 전략 매핑이 완성된다. NAK 에러(예측 가능, MR 경계는 협상으로 앎)는 proactive 사전 차단(B)이 일방 우위이고, silent 에러(예측 불가)는 사전 차단이 원리적으로 불가능하므로 commit 가시성 프로토콜(C 계열)로 대응한다. 복원 가능 여부(5.4절)와 예측 가능 여부(5.6절, 모두 [05 문서](05_partial_write_ab_recovery.md))에 이어 소비자 능력(7.3)이 세 번째 전략 결정 축이다.

일반화 경고: sq_psn retreat(NAK 복원의 전제)은 현행 RoCE NIC의 go-back-N 구현 산물이다. IRN(SIGCOMM'18)/SRNIC 계열 selective-repeat NIC에서는 성립하지 않을 수 있다 — vendor_err 한계와 같은 카테고리의 구현 의존성으로 문서화한다.
