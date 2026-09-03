# 전략 C: Silent Partial Write 대응 전략 비교 (commit 의미론)

Timeout/peer-death 경로의 **무음(silent) partial RDMA WRITE**에 대해, torn prefix를 소비자에게 안전하게 만드는 세 가지 방법의 비용을 동일 시나리오에서 비교하는 harness.

## 왜 "복원"이 아니라 "판별"인가

NAK 경로(`ab_recovery.c`, REM_ACCESS_ERR)와 달리, 응답자 QP가 전송 도중 ERR로 떨어지는 silent 경로는 NAK가 없다. requester는 flush된 WQE만 본다. 그리고 `verify_interrupted_write.c`에서 확립했듯 **sq_psn으로는 커밋 경계를 복원할 수 없다** (sq_psn = 전송된 PSN이지 커밋된 바이트가 아님). partial은 PMTU(1024) 정수배 prefix로 끊긴다는 사실만 남는다.

핵심 재프레이밍: **WRITE requester는 원본을 항상 보유**하므로 silent partial의 위험은 데이터 손실이 아니라 **소비자가 torn prefix를 완전한 것으로 읽는 것**이다. 따라서 필요한 것은 바이트 경계 복원이 아니라 valid/invalid 판별 = 커밋 의미론이다. 이 실험은 커밋 의미론을 구현하는 세 전략의 (1) 정상경로 오버헤드와 (2) 에러 후 판별/복구 비용을 잰다.

## 전략 정의

| | 정상경로 | 에러 후 판별 | 복구 / 재전송 |
|---|---|---|---|
| **C0** baseline | 순수 WRITE 1개(signaled) | 없음 (비교 기준) | — |
| **C1** commit-flag | payload WRITE(unsignaled) + 8B flag WRITE(signaled), 같은 QP 연속 post | flag 유무 = 판별, **O(1)** | QP-only recovery + 전체 재전송 + flag 재기록 |
| **C2** crc32c | 16B 헤더[seq\|len\|crc\|reserved] + payload를 **단일 WRITE**; crc 계산 비용 | 서버가 헤더 읽고 payload CRC 재계산, **O(len)** | QP-only recovery + 전체 재전송 |
| **C3** read-back | C0과 동일, **오버헤드 0** | recovery 후 RDMA READ 회수 + 로컬 원본 diff로 경계 탐색 | **경계부터 나머지만** 재전송 (partial resend) |

핵심 대비:
- **C1**은 정상경로에 WR 하나(flag)를 더하지만 판별이 O(1). RC의 WR 간 in-order 실행이 보장의 근거 — payload가 mid-transfer 실패하면 뒤이은 flag WR은 절대 실행되지 않는다(단일 WR 내 "마지막 바이트 폴링"이 아니라 반드시 **별도 WR**이어야 IBA 스펙 보장).
- **C2**는 정상경로에 CRC 계산(O(len))을 얹지만 self-describing. 헤더가 안 떨어졌거나(seq mismatch/len=0) CRC 불일치면 torn.
- **C3**는 정상경로 공짜지만 에러 후 READ 왕복(O(len))이 필요. 대신 유일하게 **partial resend**로 재전송 바이트를 줄인다.

## 시나리오 (fault 주입)

`verify_interrupted_write.c` 방식 재사용:
1. 서버가 `SETUP_C`로 8MB backing buffer + 8MB MR(REMOTE_READ 포함)를 등록하고 QP 연결.
2. 클라이언트가 4MB payload를 offset 0으로 WRITE post (C1은 payload+flag 2 WR, C2는 헤더+payload 단일 WR).
3. post 직후 `CMD_INTERRUPT`로 서버 responder QP를 ERR로 전환 (**race**) → mid-transfer partial 발생.
4. `settle_ms`(기본 80ms) 대기 후 **로컬 QP→ERR 강제**로 즉시 flush CQE 획득 (3.7s RETRY_EXC 대기 회피). settle 대기는 인위적이라 어떤 비용에도 포함 안 됨; `detect_us`는 flush 자체 시간(참고용).

fault는 비결정적이라 트라이얼 결과가 **PARTIAL / FULL / NO_WRITE 혼재**다. `outcome` 컬럼에 기록하고 분석은 **PARTIAL 부분집합** 중심. ground truth는 서버 `CHECK_C` 스캔(payload 영역의 연속 non-zero prefix = 실제 land한 바이트).

## 설계상 결정과 근거

**flag 슬롯 위치.** 8MB MR의 맨 끝 8B(`C_FLAG_OFFSET = LARGE_BUF_SIZE - 8`). `LARGE_BUF_SIZE`(8MB)가 8B 정렬이라 슬롯도 정렬됨. payload 영역 `[0, 4MB)`와 멀리 떨어져 절대 겹치지 않는다. flag 값 = `magic(hi32) | seq(lo32)`; 소비자는 `(flag>>32)==C_FLAG_MAGIC && (uint32_t)flag==기대seq`일 때만 payload 유효로 본다. INIT_C가 슬롯을 0으로 두므로, flag WR이 실행 안 되면 슬롯은 0으로 남아 자동으로 invalid.

**CRC 커버 범위.** crc32c는 **payload만** 커버(헤더 자신 제외). 헤더는 `[0,16)`에 있어 partial이 1024B 이상이면 항상 온전하다 → seq가 맞고 CRC만 틀리면 "헤더는 왔는데 payload가 torn". NO_WRITE(경계 0)면 헤더도 0이라 seq mismatch로 torn 판정. 서버는 `len==0 || len>4MB || seq!=기대`를 먼저 걸러 빈 payload의 CRC(0x0)가 우연히 통과하는 것을 막는다. 하드웨어 CRC32C(SSE4.2 `_mm_crc32_u64`)를 requester/responder 양쪽이 동일 함수로 사용(소프트웨어 폴백은 동일 reflected poly `0x82F63B78`이라 값이 일치).

**C3 스캔 방식.** payload는 non-zero 패턴(0xAB), 서버 버퍼는 트라이얼마다 INIT_C로 0. partial은 PMTU 정수배 prefix이므로 **첫 0 위치 = 경계**. READ-back을 로컬 버퍼 뒤쪽 절반(`buf+4MB`)에 회수한 뒤 **1024B 단위 점프 스캔**으로 첫 0 블록을 찾고, 미세 walk로 정확한 마지막 non-zero 바이트를 확정(비정렬/비연속 방어). 경계부터 `[boundary, 4MB)`만 재전송.

**REMOTE_READ 접근 플래그.** C3의 READ-back을 위해 `SETUP_C`의 MR access에 `IBV_ACCESS_REMOTE_READ`를 포함(기존 SETUP_LARGE/AB와 무관한 additive 신설 핸들러라 다른 실험 영향 없음).

**QP-only recovery.** `RECOVER_C`가 라이브 제어 소켓 위에서 reset→새 PSN→qp_info 재교환→INIT/RTR/RTS를 클라이언트와 lockstep 수행(`handle_recover_ab` 패턴, bounds 라인만 제거). 같은 MR/buffer 유지. C3는 READ 전에 recovery가 선행돼야 하므로 recover→readback→resend 순, C1/C2는 judge→recover→full resend 순.

**per-trial 재설정.** 에러경로는 트라이얼마다 `SETUP_C`→fault→`RECOVER_C`→resend→`CLEANUP`로 상태를 새로 잡는다(`verify_interrupted_write` 패턴). 정상경로는 fault가 없어 한 연결로 전체 sweep.

## 측정 매트릭스

1. **정상경로**: C0/C1/C2/C3 × msg {4KB, 64KB, 1MB, 4MB} × N=1000(warmup 100). mean/p50/p99. C1은 flag CQE까지, C2는 CRC 계산 포함, C3=C0.
2. **에러경로**: C1/C2/C3 × 4MB × N=100/전략. 컬럼: outcome, ground_truth_bytes, judged_valid, judge_correct, detect_us, recover_us, judge_us, resend_bytes, resend_us, total_us.
3. **C3 partial resend 이득**: 에러 summary 행의 평균 resend_bytes ÷ 4MB로 전체 재전송 대비 절감 비율.

## CSV 스키마

출력: `results/raw/silent_strategy.csv`. 18 컬럼. `phase`로 행 종류 구분.

| 컬럼 | phase=normal | phase=error | phase=summary |
|---|---|---|---|
| strategy | C0..C3 | C1..C3 | C1..C3 |
| phase | `normal` | `error` | `summary` |
| msg_size | payload 바이트 | 4194304(4MB) | 4194304 |
| iter | -1 | 트라이얼 index | -1 |
| outcome | `NA` | FULL/PARTIAL/NO_WRITE | `P<partial>_F<full>_N<nowrite>` |
| ground_truth_bytes | 0 | 서버 스캔 land 바이트 | 평균 land 바이트 |
| judged_valid | 0 | 전략의 판정(1=valid) | judged_valid==1 **개수** |
| judge_correct | 0 | ground truth 일치 여부(1/0) | judge_correct==1 **개수** |
| detect_us | 0 | flush CQE 시간(참고용) | 평균 |
| recover_us | 0 | QP-only recovery(µs) | 평균 |
| judge_us | 0 | 판별 비용(C1≈0, C2=CRC, C3=READ+scan) | 평균 |
| resend_bytes | 0 | 재전송 바이트(C1/C2=4MB, C3=tail) | 평균 |
| resend_us | 0 | 재전송 시간(µs) | 평균 |
| total_us | 0 | detect+recover+judge+resend | 평균 |
| norm_mean_us | 정상 WRITE 평균(µs) | 0 | 0 |
| norm_p50_us | 정상 WRITE p50 | 0 | 0 |
| norm_p99_us | 정상 WRITE p99 | 0 | 0 |
| norm_count | 측정한 정상 WRITE 수 | 0 | 완료 트라이얼 수 |

`judge_correct`의 전략별 의미: C1/C2는 `judged_valid == (outcome==FULL)`(판정이 실제와 일치했나). C3는 `scan_boundary == ground_truth_bytes`(read-back diff가 경계를 정확히 찾았나) + `judged_valid=(boundary==4MB)`.

## 예상 결과 해석 가이드

- **정상경로**: C0 ≈ C3(오버헤드 0) < C1(flag WR 1개, 작은 msg에서 상대적으로 큼) < C2(CRC O(len), 큰 msg에서 지배적)일 것으로 예상. 교차 지점을 msg 크기 축에서 관찰.
- **판별 정확도**: C1은 PARTIAL/NO_WRITE에서 항상 invalid 판정(정답). 단 payload FULL인데 interrupt가 flag WR을 물면 false-negative(judge_correct=0) 가능 — C1 고유 성질로 기록됨. C2/C3는 PARTIAL을 결정적으로 torn 판정.
- **비용 축**: C1의 judge_us는 flag 읽기(≈0)라 판별이 사실상 공짜, C2/C3는 O(len). recover_us는 세 전략 공통(QP-only). C3의 resend_bytes만 4MB보다 작아(경계 이후만) partial-resend 이득이 드러난다.
- **스토리**: A/B(NAK=예측 가능→proactive 범위검사)와 C(silent=예측 불가→커밋 프로토콜)로 "fault 분류 → recovery 전략 매핑"이 완성된다.

## 빌드

서버(224)와 클라이언트(225) 별도 빌드. `server.c`는 additive 확장(`SETUP_C/INIT_C/INTERRUPT/CHECK_FLAG/VERIFY_CRC/RECOVER_C/CHECK_C` 핸들러)만, 기존 동작 유지. 양쪽 모두 `-msse4.2`(하드웨어 CRC32C)로 빌드하며, 소프트웨어 폴백이 있어 플래그 없이도 컴파일은 되지만 CRC 값 일치를 위해 양쪽 동일 경로를 써야 한다.

```
# 서버 (224)
cd ~/Desktop/gpu_fault_recovery/05_counter_mapping
make server          # server 타깃에 -msse4.2 포함

# 클라이언트 (225)
cd ~/Desktop/gpu_fault_recovery/05_counter_mapping
make silent_strategy # -msse4.2 포함
```

공유 헤더 `common.h`에 양쪽 동일 변경(`CMD_SETUP_C/INIT_C/CHECK_FLAG/VERIFY_CRC/RECOVER_C/CHECK_C`, `C_FLAG_OFFSET/MAGIC`, `struct c2_header`, `C2_HEADER_SIZE`)이 들어갔다. mutagen sync로 전파됨. `LARGE_BUF_SIZE`(8MB)/`LARGE_WRITE_LEN`(4MB)/`PMTU_BYTES`(1024)는 기존 정의 재사용.

## 실행

`run_silent.sh`가 225에서 orchestration(ssh로 224 server 빌드/기동, 정상경로 sweep + 에러경로 3전략, CSV header 생성).

```
cd ~/Desktop/gpu_fault_recovery/05_counter_mapping
./run_silent.sh [normal_iters=1000] [err_trials=100] [settle_ms=80]
```

수동 실행(단일 combo, 디버깅용):
```
# 224: ./server
# 225:
./silent_strategy C2 normal 65536 1000     # C2 정상경로, 64KB, 1000회
./silent_strategy C3 error  4194304 100 80 # C3 에러경로, 4MB, 100 트라이얼, settle 80ms
```

CSV는 append되므로 수동 실행 전 header가 없으면 직접 만들거나 run script를 쓸 것.

## 환경 (재현용)

| 항목 | Client (225) | Server (224) |
|---|---|---|
| NIC | ConnectX-6 (MT28908) | ConnectX-5 (MT27800) |
| CPU | x86 (SSE4.2 CRC32C) | x86 Xeon (SSE4.2 CRC32C) |
| RDMA IP | 10.0.0.2 | 10.0.0.3 |
| Link | 100 Gbps RoCE v2 | 100 Gbps RoCE v2 |
| PMTU | IBV_MTU_1024 (RTR `path_mtu`) | 동일 |

[TODO: 실험 필요] 실제 측정값(정상 latency, judge/recover/resend_us, judge 정확도, C3 partial-resend 절감률)은 하드웨어에서 실행 후 채울 것.
