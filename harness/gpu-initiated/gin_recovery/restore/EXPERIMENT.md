# GIN 투명 복구: 죽은 rank를 예비 프로세스에 되살려 상대를 모르는 대기를 지킨다 (gin-restore)

**목적:** rank 하나가 죽으면 그 논리 rank만 예비 프로세스에 체크포인트와 송신 쪽 로그로 되살려, 살아남은 rank의 상대를 모르는 대기
(`waitSignal` 등)가 풀리지도 멈추지도 않고 원래 값으로 끝나게 하는 설계를 세우고, 라이브러리 계층이 필요 없는 부분을 먼저 시제품으로 만든다.

| 항목 | 값 |
|---|---|
| 상태 | `DRAFT` |
| 담당자 | @unionxic |
| 작성일 | 2026-10-09 |
| 기준 브랜치와 커밋 | `exp/gin-restore` @ `02a640aa` (master) |
| 사전 등록 태그 | 없음. 라이브러리 계층(9.9절)과 pilot 뒤 `prereg/gin-restore-v1` 예정 |
| 마지막 갱신 | 2026-10-09, 초안: 설계(9.1–9.8절), 필요한 hook(9.9절). 사용자 결정으로 감지와 반응을 나눈 정책 설계와 통합 상호작용 표, 막는 문제를 [DESIGN_POLICY.md](DESIGN_POLICY.md)로 옮김. 충돌이 남은 동안 구현 없음(시제품 멈춤, 9.13절) |

**설계의 기준 문서.** 장애 반응 정책(fail-fast와 hold-for-restore), 기존 장치와의 통합 상호작용 표, gpu-detect 계층에 넣을 변경, 막는 문제는
[DESIGN_POLICY.md](DESIGN_POLICY.md)에 있다. 이 문서의 9.9–9.11절은 그것을 가리키기만 한다. 사용자 결정(2026-10-09): 충돌이 남아 있는 동안 아무것도
구현하거나 빌드하지 않는다.

표시: `[측정]` 원자료나 시행별 표, 시험 출력에서 확인, `[소스]` 코드에서 읽음, `[문서]` 외부 문서나 논문의 설명, `[추론]` 해석,
`[미확인]` 확인 안 함.

이 문서의 코드는 함수 이름과 줄 번호로 가리킨다. 따로 적지 않으면 파일은 `src/transport/net_ib/gdaki/gin_host_gdaki.cc`이고, 줄 번호는
gin-remaining `hr` 빌드 트리(세션 스크래치 `agent_ts2hr/nccl-src`, 2026-10-09 읽음)의 것이다. gpu-detect `hw` 트리(`agent_gd/gin/nccl-src`, diff md5
`be0ea9ed`)에서는 이 파일의 줄이 밀린다. 둘을 함께 적은 표는 [DESIGN_POLICY.md](DESIGN_POLICY.md) 4절이다. 장치 쪽은
`src/include/nccl_device/gin/gdaki/gin_gdaki.h`(`gin_gdaki.h`)와 `gin_gdaki_device_host_common.h`(`common.h`)이고 hr과 hw가 같다.

용어(helper, 사용자 devComm, abort 단어, 상대별 단어, 거절, 죽음, 라운드, 커밋, degraded, NIC 복사 경로, 게이트, 에폭)는
[../remaining/EXPERIMENT.md](../remaining/EXPERIMENT.md)와 [../peer/EXPERIMENT.md](../peer/EXPERIMENT.md) 머리말과 같다. 이 실험에서 더 쓰는 말:
- 논리 rank: application과 communicator가 아는 rank 번호. 복원 뒤에도 바뀌지 않는다. 그 rank를 맡은 프로세스를 그 rank의 화신(incarnation)이라 하고,
  처음 화신은 0, 복원마다 1씩 는다.
- 예비 프로세스(spare): 미리 띄워 둔, 논리 rank 하나를 맡을 수 있는 프로세스. 같은 실행 파일을 `NCCL_GIN_RESTORE_SPARE=<rank>`로 띄운다.
- 짝(buddy): 논리 rank r의 체크포인트와 초기화 기록을 호스트 메모리에 맡아 두는 다른 rank. 이 테스트베드에서는 다른 노드의 rank다.
- 체크포인트: application이 커널 사이에서 부르는 단계 hook(9.4절)에서 찍는 r의 장치 상태(GIN window, 등록한 버퍼, 신호 값)와 호스트 덩어리.
- 입력 멈춤: 체크포인트를 찍는 동안 다른 rank가 r에게 보내는 QP의 게이트를 홀수 에폭으로 두어 r로 가는 보내기를 잠깐 멈추는 것. 라운드가 아니다.
- 절단점(cut): 체크포인트에 든 입력과 들지 않은 입력의 경계. 보내는 쪽 로그의 위치와 메시지 수로 적는다.
- 송신 쪽 로그: 각 rank가 상대마다(QP마다) 자기가 보낸 put과 신호를 내용과 함께 적어 두는 장치 메모리 고리. 상대의 다음 체크포인트가 확정되면 지운다.
- 재실행(replay): 예비 프로세스가 체크포인트의 단계부터 application 커널을 다시 도는 것.
- 중복 억제(suppression): 재실행이 다시 내는 보내기 가운데 생존 rank가 이미 받은 것을 내지 않는 것. 단위는 RC 요청 메시지다.
- 붙잡음(hold): 생존 rank의 helper가 죽은 상대 하나를 거절하지 않고 복원을 기다리는 것. 상태는 HELD, COMMITTING, PUBLISHED(DESIGN_POLICY.md 3절).
  복원 시한(`NCCL_GIN_RESTORE_MS`)이 끝나거나 실패하면 앞 빌드의 거절로 돌아간다(fallback).
- 초기화 기록(init transcript): 논리 rank r이 처음 초기화 때 받은 모든 집합 교환(bootstrap, GIN collComm)의 결과. 예비 프로세스가 초기화를 다시 할 때
  이것을 받아 쓴다(초기화 재생).

예측 id, 셀 이름, 빌드 키는 원자료를 찾는 키로만 괄호나 표의 열에 둔다.

| 빌드 키 | 내용 | 쓰는 곳 |
|---|---|---|
| `rs` | 이 실험의 연구 빌드: gpu-detect `hw` 위에 9.9절의 계층(아직 없음) | 새 셀 |
| `rsp` | 같은 소스의 운영 빌드(`-DNCCL_GIN_TS_PRODUCTION`) | 지연, 운영 kill |
| `hw` | gpu-detect의 연구 빌드(대조: 복원 없이 degraded) | 대조 |
| `hr` | gin-remaining의 연구 빌드(읽기만, 대조) | 대조 |

## 1. 배경과 연구 질문

**남은 문제: 상대를 모르는 대기.** `waitSignal`, `waitCounter`, 배리어는 어느 rank의 신호를 기다리는지 모른다. 신호는 어느 rank든 더할 수 있다
(`gin__funcs.h`의 `waitSignal`이 devComm의 abort 단어만 넘긴다) `[소스]`. 그래서 상대 하나가 죽으면 라이브러리는 둘 중 하나밖에 못 한다.
- 모두 푼다(gin-remaining `hr`의 degraded 규칙). 랭크 4개에서 rank 3을 SIGKILL하고 모든 받기에 시간 제한을 두지 않았을 때, 생존 rank의 rank 3
  받기 30개가 죽음 판정 2 006.7–2 013.0 ms 뒤 오류로 풀렸고, 생존 rank 사이 받기도 시행마다 6개씩 60개 모두 오류로 풀렸다(10회)
  `[측정: ../remaining/results/20261009/trials_scored.csv에서 다시 셈, rm4_kill3_untimed@hr n=10]`. gin-remaining 15절은 그 60개 가운데 40개가 끝에
  신호를 다 받을 대기였다고 적었다 `[문서: 다시 세지 않음]`.
- 아무것도 풀지 않는다(gin-peer `hq`). 같은 셀에서 생존 rank 3개의 커널이 5회 모두 application이 포기할 때까지 돌았고 풀린 받기는 0이었다
  `[측정: 같은 표에서 다시 셈, rm4_kill3_untimed@hq n=5]`.

**사용자가 고른 해법.** 어느 대기를 풀지 고르지 않고 죽음을 되돌릴 수 있게 만든다. 논리 rank마다 체크포인트를 짝의 메모리에 두고, 보내는 쪽이
보낸 것을 로그로 남기고, 죽은 논리 rank 하나만 예비 프로세스에 되살려 체크포인트 뒤의 입력을 다시 넣고 같은 논리 rank로 다시 잇는다. 생존 rank는
되돌아가지 않는다. 그 `waitSignal`은 그냥 계속 기다리고, 되살린 rank가 빚진 신호를 보내면 끝난다.

**비어 있는 것.** 이 저장소의 GIN 계층들은 QP 하나나 쌍 하나를 고치는 라운드(hr)와 죽은 상대를 거절하는 규칙만 있다. 프로세스가 사라진 뒤 같은 논리
rank를 새 프로세스로 잇는 길, 보낸 메시지를 다시 넣는 길, 다시 보낸 메시지를 거르는 길이 없다 `[소스]`.

**질문.**
1. 생존 rank가 죽음 판정 뒤 거절 대신 복원을 기다릴 때, 기존 장치(degraded, 장치 대기의 hold 한도, 감시, 라운드, gpu-detect의 QP 상태 감시)와 충돌
   없이 대기를 붙잡아 둘 수 있는가. 복원이 실패하면 지금의 degraded로 돌아가는가.
2. 예비 프로세스가 같은 논리 rank로 다시 이어지고(초기화 재생, QP 재연결, rkey 바꾸기), 체크포인트와 송신 쪽 로그로 죽기 직전 상태를 만들고,
   재실행이 다시 내는 보내기를 정확히 걸러, 최종 데이터가 장애 없는 실행과 비트 단위로 같은가.
3. 생존 rank는 한 단계도 다시 실행하지 않는가. 생존 rank의 상대를 모르는 대기가 오류 없이 끝나는가.
4. 복원 시간, 로그 크기, 체크포인트 비용(생존 rank의 입력 멈춤 시간, 단계 시간 증가)은 얼마인가.

## 2. 가설

초안이다. 사전 등록 전에 9.9절 계층과 pilot을 보고 고친다.

| id | 가설 | 다음이 관측되면 틀린 것이다 |
|---|---|---|
| H1 | 죽음 판정을 거절 대신 복원 중 상태로 바꾸고 게이트를 홀수 에폭으로 두면, 생존 rank의 상대별 대기와 상대를 모르는 대기가 복원 시한 안에 오류 없이 붙잡혀 있다 | 복원 셀에서 생존 rank의 대기가 오류로 끝나거나 비동기 오류가 보이는 시행이 있다 |
| H2 | 체크포인트(입력 멈춤으로 정확한 절단점) + 송신 쪽 로그 + RC 응답 쪽 실행 수로 중복을 거르면, 결정적인 workload의 최종 데이터가 장애 없는 실행과 같다 | 복원 셀에서 어느 rank의 최종 데이터나 받은 칸이 기준과 다른 시행이 있다 |
| H3 | 생존 rank는 되돌아가지 않는다 | 생존 rank의 단계 실행 수가 1이 아닌 단계가 있다 |
| H4 | 복원이 시한 안에 끝나지 않으면 앞 빌드의 거절과 degraded로 돌아간다 | 예비 프로세스가 없는 셀에서 대기가 시한 + 2 s 근처에 풀리지 않는다 |
| H5 | 로그와 체크포인트의 비용은 빠른 경로 지연에 작게 남는다 | 9.4, 9.5절의 비용 어림을 크게 넘는다(3절에서 수로 고정) |

## 3. 사전 예측 (측정 전에 작성)

아직 고정하지 않았다. 아래는 초안이고, 판정 기준의 수는 계층과 pilot 뒤에 정한다. 고정은 `predictions.csv`와 태그로 한다.

| 무엇을 예측했나 | id(초안) | 셀 | 판정 기준(초안) | 근거 |
|---|---|---|---|---|
| 생존 rank의 상대를 모르는 대기가 오류 없이 끝나고 비동기 오류가 없음 | RS1 | `rs4_kill3@rs` | ≥9/10 | 9.2절 `[소스, 추론]` |
| 모든 rank의 최종 상태와 받은 칸이 기준(호스트 계산)과 비트 단위로 같음 | RS2 | `rs4_kill3@rs` | ≥9/10 | 9.6, 9.7절. 시제품 모의에서 맞음 `[측정: 9.13절]` |
| 생존 rank의 단계 실행 수가 모두 1 | RS3 | `rs4_kill3@rs` | 10/10 | 생존 rank는 hold만 한다 |
| 되살린 rank가 마지막 단계까지 감 | RS4 | `rs4_kill3@rs` | ≥9/10 | |
| 억제한 메시지 수 = 생존 rank의 실행 수 − 체크포인트 때 실행 수(통로마다) | RS5 | `rs4_kill3@rs` | ≥9/10 | 9.6절 |
| 복원 시간(첫 죽음 판정 줄에서 마지막 생존 rank의 게이트 재개까지) 10 000 ms 이하 | RS6 | `rs4_kill3@rs` | ≥9/10 | 9.3절 어림 `[추론]` |
| 체크포인트 중 kill: 앞 체크포인트에서 복원, RS1–RS4 | RS7 | `rs4_kill3_ckpt@rs` | ≥4/5 | 9.4절 |
| 예비 프로세스 없음: 복원 시한 뒤 거절, 상대를 모르는 대기가 시한 + 2 000–2 500 ms에 오류로 풀림 | RS8 | `rs4_kill3_nospare@rs` | ≥4/5 | 9.2절 fallback |
| 대조: 복원 없는 빌드는 2 s 뒤 degraded로 모두 풀림 | RS9 | `rs4_kill3@hw` | ≥4/5 | gin-remaining DG1 `[측정]` |
| 장애 없음: 최종 데이터 같음, 복원 0, 체크포인트마다 생존 rank의 입력 멈춤 5 ms 이하 | RS10 | `rs4_none@rs` | 5/5 | 9.4절 `[추론]` |
| 4 KiB, 256 KiB put 지연 증가(로그 켬 대 끔) | LT1, LT2 | `lat_*@rsp` | 수는 pilot 뒤 | 9.5절 비용 어림 |

## 4. 범위

**포함.**
- 9절의 설계: 복원 중 대기 유지, 예비 프로세스와 끝점 간접화, 체크포인트, 송신 쪽 로그, 재실행과 중복 억제, 결정성 요구, 시험 workload와 판정 기준.
- 9.9절 hook 목록(gpu-detect `hw` 위의 계층)과 [DESIGN_POLICY.md](DESIGN_POLICY.md)의 정책 설계와 상호작용 표.
- 시제품(9.13절): 체크포인트와 로그의 자료 구조, 복원 계획과 적용, 중복 억제를 독립 라이브러리로 만들고 CPU 모의로 단위 시험한다. 시험 프로그램
  [gin_rs.cu](gin_rs.cu)는 `hr` 헤더로 빌드만 한다.

**제외.**
- 실제 GPU 고장, 노드 고장, 하드웨어 예비 장비: 주입할 수 없다. 장애는 프로세스 kill(SIGKILL)만이다.
- NVSHMEM: 이 실험은 GIN만 다룬다.
- 동시에 둘 이상 죽는 것, 복원 중 다른 rank가 죽는 것, 예비 프로세스가 복원 중 죽는 것: fallback(9.2절)으로만 다룬다.
- GIN 밖의 NCCL 통신(collective, NCCL P2P, LSA load/store)으로 되살린 rank와 주고받는 것: 로그되지 않는다. 복원한 communicator에서는 쓸 수 없다(DESIGN_POLICY.md X2).
- 복원 뒤 새 GIN 자원(window 등록, devComm 생성)을 만드는 것: GIN collComm 고리가 끊겨 있다(DESIGN_POLICY.md A3).
- 실제 link down, flap, 재부팅, 드라이버 재적재: 하지 않는다.

## 5. 테스트베드와 버전

| 항목 | 값 | 확인 방법과 날짜 |
|---|---|---|
| 노드, NIC, GPU, CUDA | gin-remaining과 같다: rain(Quadro RTX 5000), sunny(RTX A4000), ConnectX-6, CUDA 12.8 | `../remaining/EXPERIMENT.md` 5절 `[문서]` |
| 랭크 배치 | 랭크 4개, GPU마다 프로세스 둘(`NCCL_MULTI_RANK_GPU_ENABLE=1`, gin-multirank처럼): rain에 0과 2, sunny에 1과 3. rank 3의 예비 프로세스는 sunny GPU의 셋째 프로세스, 짝은 rank 2(rain) | 계획 |
| 라이브러리 | gpu-detect `hw` + 이 계층(`rs`). 아직 없음 | 9.9절 |
| 시제품 빌드 | rain, g++ (CPU 시험), nvcc 12.8(빌드만) | 9.13절 |

## 6. 변수

- **독립변수.** 빌드(`rs`, `rsp`, `hw`), 장애(rank 3 kill, 체크포인트 중 kill, 예비 프로세스 없음), kill 시점(단계 번호와 단계 안의 지연),
  체크포인트 간격(단계 수), 메시지 크기.
- **종속변수.** 생존 rank의 대기 결과와 끝난 시각, 비동기 오류, 최종 데이터 비교, 단계 실행 수, 억제한 메시지 수, 다시 넣은 로그 크기, 복원 단계별
  시각(죽음 판정, 활성화, 초기화 재생, 상태 적용, 재연결, 게이트 재개), 체크포인트마다 입력 멈춤 시간과 단계 시간.
- **통제변수.** gpu-detect와 같은 투명 복구 스위치 기본값, `NCCL_GIN_RESTORE_MS`(초안 20 000), 체크포인트 간격(초안 20 단계), 시행마다 프로세스를
  새로 띄움.

## 7. 실험 셀, 반복 수, 대조군

초안이다.

| 셀 | 조건 | 빌드와 반복 수 | 종류 |
|---|---|---|---|
| `rs4_none` | 랭크 4개 ring/stencil(9.8절), 장애 없음, 체크포인트 켬 | `@rs` 5 | 대조, 비용 |
| `rs4_none_off` | 같고 복원 계층 끔(`NCCL_GIN_RESTORE=0`) | `@rs` 5 | 비용 기준 |
| `rs4_kill3` | rank 3 SIGKILL(단계 중간), 예비 프로세스 있음 | `@rs` 10 | 새 셀 |
| `rs4_kill3_ckpt` | 체크포인트 입력 멈춤 중 kill | `@rs` 5 | 새 셀 |
| `rs4_kill3_nospare` | 예비 프로세스 없음 | `@rs` 5 | fallback |
| `rs4_kill3` | 복원 없는 빌드 | `@hw` 5 | 대조 |
| `rs4_kill1` | rank 1 kill(rank 3과 같은 GPU) | `@rs` 5 | 일반성 |
| gin-remaining, gpu-detect 회귀 셀 | 복원 계층을 켠 채 기존 셀 | `@rs` 각 5 | 회귀 |
| `lat_4k`, `lat_256k` | 로그 켬 대 끔 | `@rsp` 각 5 | 비용 |

## 8. 제외 기준과 중단 기준

초안: gin-remaining 8절과 같은 틀(초기화 전 실패, 장애 미적용 제외, 설정 확인 실패면 블록 멈춤, `cluster_run.sh` 잠금, 이름으로 끄지 않음, CUDA 메모리
오류와 mlx5 오류에서 멈춤)을 쓴다. 더하는 것:
- kill이 첫 체크포인트 확정 전이면(복원할 체크포인트 없음) 제외하고 채운다.
- 예비 프로세스가 활성화 전에 끝났으면(시작 실패) 제외하고 따로 센다.
- 예비 프로세스는 실행기가 기록한 PID로만 끈다.

## 9. 설계와 실행 방법

### 9.1 설계 개요

```
[생존 rank q의 helper]                         [짝 b(r)]                       [예비 프로세스 s(r)]
 r의 helper 소켓 FIN → 죽음 판정                 r의 체크포인트 k, 초기화 기록     같은 실행 파일. CUDA 문맥까지 만들고
  ├─ ARMED(r)이고 TOLD 아니면 거절 대신 hold      을 호스트 메모리에 둠            ncclCommInitRank 안에서 대기
  │   게이트(q→r) 홀수, QP ERR, 개수 0
  │   칸 0, 상대 단어, 비동기 오류 없음
  ├─ HOLDING(r) ─────────────────────────────▶ 모든 생존 rank가 HOLDING이면
  │                                             ACTIVATE(r, k) ──────────────▶ PID 확인(원래 프로세스가 끝났는지)
  │                                                                            초기화 재생(기록으로 집합 교환 대답), QP는 만들기만
  │◀──────────── REJOIN(r, 화신+1, nonce, 새 QPN, 보내기 PSN) ──────────────────
  ├─ X_q(r→q)와 로그(절단점 이후) 보냄 ─────────────────────────────────────────▶ 체크포인트 k 받아 window와 신호 복원
  │                                                                            로그 적용(쓰기, 신호 더하기), 억제 예산 = X_q − P_q
  ├─ 복원 라운드 시작: Prepare(drain, 새 PSN) → 토큰(QPN, 새 PSN) ────────────────▶ 그 PSN으로 자기 QP를 RTR/RTS로 이음
  │◀──────────── READY ──────────────────────────────────────────────────────
  ├─ 끝점 바꿈 → Commit(2RST, 새 QPN에 연결) → Baseline → rkey 표 [r] 바꿈
  │   → 모든 옛 WQE를 실행된 것으로(lbase += S) → 짝수 에폭 게시 → DONE_RS ──────▶ (모든 생존 rank의 DONE_RS) 단계 k부터 재실행,
  │                                                                            억제 예산만큼 보내기를 내지 않음
  └─ 시한(감시 스레드가 지킴)이나 실패, 누구든 FALLBACK(r) → PeerDead 거절 → 2 s 뒤 degraded
```

원칙 셋 `[추론]`:
- 생존 rank는 CUDA 호출을 하지 않는다(gin-handoff, gin-remaining: application의 CUDA 호출이 helper의 스트림을 묶을 수 있음). 생존 rank 쪽 일은
  helper 소켓, 펌웨어 명령, NIC 루프백 복사(이미 있는 길)뿐이다. 무거운 CUDA 일(초기화, 메모리 복원)은 할 일이 없는 예비 프로세스가 한다.
- 빠른 경로는 바꾸지 않는다. 로그 쓰기(9.5절)만 빠른 경로에 더한다(hold가 아니면 측 표 포인터를 한 번 보는 것). 억제는 게이트의 느린 길에서만 한다.
  키 읽기 자리는 이 원칙과 충돌해 결정이 필요하다(DESIGN_POLICY.md 5절 B4).
- 기존 라운드 기계를 다시 쓴다. 생존 rank 쪽 복원 라운드는 `ncclGinRecoverPrepare`(2143), `ncclGinRecoverCommit`(2334),
  `gdakiTsRepostApply`(4692)를 상대 하나에 대해 그대로 부르고, 다른 것은 끝점을 바꾸는 것과 "모든 옛 WQE가 실행됨"으로 계획을 만드는 것뿐이다.

### 9.2 복원 중 대기 유지와 시한 (생존 rank)

**상태.** 생존 rank의 helper는 상대 r마다 상태 하나를 둔다: `OFF`(복원 꺼짐), `ARMED`(r의 확정된 체크포인트가 있고 r로 가는 로그가 그 절단점부터
빠짐없음), `HELD`, `COMMITTING`, `PUBLISHED`(붙잡음: 복원 라운드의 커밋 지점 전, 게시 중, 게시 뒤 예비 프로세스의 RESTORED 전), `FALLBACK`(복원 포기, 앞 빌드의
거절로), `CANCELLED`(abort, shrink, revoke, 정리). 전이와 무장의 원문은 [DESIGN_POLICY.md](DESIGN_POLICY.md) 2.3절과 3절이다.

**죽음 판정에서.** 지금은 FIN이 보이면 `gdakiTsSocketLost`(3746–3777)가 `deadJudged`를 세우고, helper 루프(6095–6101)가 바로
`gdakiTsDecline(..., GDAKI_UA_PEER_DEAD)`를 부른다. 거절은 QP를 ERR로 보내고(4933), 그 상대의 단어와 비동기 오류를 올리고(4936–4943),
degraded를 예약하고(2828–2840), 게이트를 실패로 쓴다(4960–4964) `[소스]`. 계층은 `gdakiTsDecline` 맨 앞의 정책 hook(G2, [DESIGN_POLICY.md](DESIGN_POLICY.md) 4.10절)에 hold 분기(RL1)를 둔다. 그 상대가 `ARMED`이고
죽음의 증거가 있으면(아래) 거절하지 않고 붙잡는다(상태 HELD → COMMITTING → PUBLISHED, DESIGN_POLICY.md 3절).
- 죽음의 증거: 강한 증거(BYE 없는 FIN, 또는 1–5 s 간격의 거절 둘)만 쓴다. 라운드 안의 FIN은 지금 거절이 아니라 취소(`gdakiTsCancelRound` 5127–5146)로
  가서 상대를 "모름"으로 두므로, 그 경우는 다시 걸기와 탐침의 거절 둘로 죽음이 판정된 뒤 다시 줄에 선 기록의 라운드(죽음 길)나 helper 루프의 거절로 온다. 두 길 모두 G2를 거친다. 다른 거절(분류 불가, 확대 상한, 상대의
  FAIL, 펌웨어 초과, BADMAGIC 같은 약한 죽음)은 가로채지 않는다. 판단의 원문은 [DESIGN_POLICY.md](DESIGN_POLICY.md) 2.4절과 R1이다.
- 붙잡을 때 하는 일: 상태를 맨 먼저 HELD로 두고, 범위를 모든 문맥으로 두고, 준비된 라운드를 풀고, `gdakiTsQuiesce`(4416)를 그대로 부른다(게이트 홀수, QP를 ERR로,
  개수 0, 모아 둔 WQE의 doorbell, `abandoned` 확인). `deadJudged`와 `failedPending`을 지운다. 이 모두를 `gdakiTsBusy` 안에서 한다.
  차례의 원문은 [DESIGN_POLICY.md](DESIGN_POLICY.md) 3절이다. 보내기는 게이트에서 쉬고, r의 QP를 기다리는 요청 대기와 flush는 다음 짝수 에폭까지 쉰다
  (`tsParkStable`, `gin_gdaki.h` 252–297). 상대별 단어, 칸 0, 비동기 오류, degraded 예약, 거절의 WARN 줄은 만들지 않는다(죽음 판정의 WARN 줄은 감지라서 남는다). 상대를 모르는 대기(`waitSignal`)는
  칸 0만 읽으므로 그냥 계속 돈다.
- 장치 대기의 한도: 쉬는 장치 스레드는 게이트의 `waitMs`(= `NCCL_GIN_TS_HOLD_MS`, 기본 30 000 ms, 6820) 뒤 포기한다(`tsGiveUp` → poison)
  `[소스]`. 그래서 복원 시한 `NCCL_GIN_RESTORE_MS`(초안 기본 20 000)는 `holdMs`보다 짧아야 하고, 계층은 `gdakiTsStart`(`roundMs`를 정하는 곳)에서
  관계를 확인해 어기면 복원을 끈다(시작 줄로 보임). 쉬는 스레드의 시계는 게이트가 처음 홀수가 된 때부터 가므로 실제 시한은 그것으로 줄인다
  ([DESIGN_POLICY.md](DESIGN_POLICY.md) T4).
- 시한이 지나면(`FALLBACK`): Q4 감시 스레드가 시한을 지킨다(G8). CAS(HELD 또는 PUBLISHED → TIMED_OUT)에 이기면 그 상대의 단어(PEER_DEAD), 비동기 오류,
  책임(PeerDead), degraded 예약을 CPU 쓰기로 하고, helper가 풀리면 앞 빌드의 거절(`gdakiTsDecline(..., PeerDead, GDAKI_UA_PEER_DEAD)`)로 게이트와 FAIL을
  마저 한다. degraded 시계는 시한에서 시작하므로 상대를 모르는 대기는 시한 + 2 000 ms에 풀린다. 모든 rank와 예비 프로세스에 FALLBACK(p)를 보내고, 예비
  프로세스는 BYE 없이 끝난다(DESIGN_POLICY.md 3절).
- 시한 안의 실패도 같은 길이다: 예비 프로세스 없음(짝이 ACTIVATE를 못 보냄), 예비 프로세스의 소켓 끊김, 상태 적용 실패, 복원 라운드의 거절(아래),
  장치 대기의 포기(`abandoned`, 4303–4313; 복원 라운드의 커밋 지점이 본다).
- 복원 라운드 안에서 펌웨어 단계가 `NCCL_GIN_TS_FW_MS`를 넘으면 감시(3476–3516)가 그 상대의 단어를 올린다. application이 이미 실패를 들었으므로 복원은
  그 자리에서 `FALLBACK`이다(기존 장치가 이긴다).

**칸 0과 상대를 모르는 대기.** 복원 중에는 칸 0을 올리지 않는다. 그래서 rank 3개 이상에서 생존 rank의 `waitSignal`은 복원이 끝나 r이 신호를 보낼
때까지, 또는 `FALLBACK` + 2 s까지 기다린다. 이것이 이 설계의 목표 동작이다.

### 9.3 예비 프로세스와 끝점 간접화

**예비 프로세스.** 실행기가 rank r을 띄울 때 같은 노드, 같은 GPU에 예비 프로세스를 하나 더 띄운다(`NCCL_MULTI_RANK_GPU_ENABLE=1`, gin-multirank처럼
GPU 하나를 프로세스 여럿이 나눠 씀). 같은 실행 파일과 인자에 `NCCL_GIN_RESTORE_SPARE=r`, `NCCL_GIN_RESTORE_SPARE_PORT=<p>`를 준다. 예비 프로세스는
CUDA 문맥과 모듈 적재까지 미리 하고(시간이 드는 일), `ncclCommInitRank` 안에서 활성화를 기다린다. 원래 rank r은
`NCCL_GIN_RESTORE_SPARE_ADDR=<노드 관리 주소>:<p>`로 예비 프로세스의 주소를 알고, 체크포인트 0과 함께 짝에게 맡긴다.

**초기화 재생.** 예비 프로세스는 application의 초기화 길(`ncclCommInitRank`, `ncclMemAlloc`, `ncclCommWindowRegister`, `ncclDevCommCreate`)을
그대로 다시 돈다. 그 안의 모든 집합 교환은 네트워크 대신 초기화 기록으로 대답한다.
- 기록: 원래 rank r의 라이브러리가 초기화 동안 받은 집합 교환의 결과를 차례로 적는다. NCCL 핵심은 bootstrap(`bootstrapAllGather`,
  `bootstrapIntraNodeAllGather`, `bootstrapBarrier`, `bootstrapSend/Recv`; 예: `dev_runtime.cc` 392, 756, 1225, 1739), GIN 쪽은 GIN collComm
  (`ncclGinIbAllGather`, `ncclGinIbAllToAll`, `transport/net_ib/gin.cc` 138, 258–259)이다 `[소스]`. 기록은 KB 단위로 작다 `[추론]`. 체크포인트 0과 함께
  짝에게 둔다.
- 재생: 예비 프로세스의 같은 호출이 기록의 다음 항목을 받는다. 호출 종류, 태그, 크기가 기록과 다르면 복원을 포기한다(검사). 결과 가운데 자기 몫(자기
  rank 칸)은 새 값으로 바꾼다(자기 QPN, rkey, 주소). 단 GIN helper 설정의 salt(6183, 6237–6239)는 기록의 옛 값을 써서 nonce가 처음과 같게 한다.
- GIN 문맥: 예비 프로세스는 QP를 새로 만들기만 하고 잇지 않는다. 생존 rank의 새 PSN이 든 토큰을 받은 뒤 기록의 생존 rank QPN(옛 rank r과 이어졌던 그
  QP들)에 잇는다(`gdakiConnectQp` 517; 양쪽 토큰 교환은 DESIGN_POLICY.md M4). GIN collComm 고리 연결(`ncclGinIbConnect`, gin.cc 231–259)과 helper 설정의
  잇기와 받기(6255–6308)도 건너뛴다(DESIGN_POLICY.md A3). 원래 rank의 listen 주소와 다른 포트에 묶고, 설치되기 전에는 REJOIN 말고 아무것에도 답하지
  않는다(DESIGN_POLICY.md D4). 활성화 전에 원래 프로세스의 PID가 없어졌는지 확인한다(같은 노드, DESIGN_POLICY.md 2.4절).
  생존 rank 쪽은 복원 라운드에서 자기 QP를 새 QPN에 다시 잇는다(아래).
- 범위: 생존 rank의 NCCL 핵심(collective 전송, proxy, RAS)은 예비 프로세스를 모른다. 복원한 communicator에서는 GIN 장치 통신만 된다(DESIGN_POLICY.md X2).
  초기화 재생이 NCCL 핵심의 결정성에 기대는 것은 이 설계에서 가장 큰 위험이다(DESIGN_POLICY.md 5절 B1).

**끝점 표.** 논리 rank → 끝점의 간접화는 생존 rank가 이미 가진 칸들을 새 화신의 값으로 바꾸는 것이다.
- helper 소켓 주소 `pe.addr`(hr 2987 / hw 3000), 화신 번호(새 칸), 자료 서버 주소(새 칸).
- QP마다 상대의 연결 정보 `rq.exch`(qpn, gid, lid; `gdaki_exch_info` 347–360). `ncclGinRecoverCommit`의 검사(2360)와 `gdakiConnectQp`(2450)가 이것을
  쓴다. 바꾸기는 `opMu` 안에서 한다(RL7).
- window마다 rkey 표의 칸 r(`ncclGinGdakiRegMrSym`이 all-gather로 채운 `rkeys_hd_mhandle`, 7902–7910)과 신호, 카운터 표의 칸 r
  (`signals_table`, `counters_table`, 7311–7315). 장치 메모리이므로 NIC 루프백 쓰기로 바꾸고(CUDA 호출 없음), 호스트 사본도 바꾼다(RL9).
- 원격 주소: GDAKI의 put은 `raddr.addr = dstOff`(window 안의 오프셋, `gin_gdaki.h` 475), 신호는 표 안의 오프셋(1460)이다 `[소스]`. 그래서 예비 프로세스의
  가상 주소가 달라도 원격 주소는 그대로이고 rkey만 바뀐다.

**다시 잇기(REJOIN).** 지금의 재연결 기계는 낮은 rank만 높은 rank에 다시 걸고(3970), 높은 rank는 낮은 rank의 HELLO만 받으며(4209–4215), `gone`인
상대에게는 다시 걸지 않는다(3972) `[소스]`. 예비 프로세스는 새 메시지 REJOIN으로 모든 생존 rank의 남겨 둔 listen 소켓(`ts->listenFd`)에 건다. 생존 rank는
그 상대가 `HELD`이고, nonce가 맞고, 화신 번호가 지금 + 1일 때만 받는다(RL6). 받으면 `pe`의 죽음 표시(`gone`, `deadJudged`, `refusals`, `left`,
`peerFailed`, `failedPending`)를 지우고, 옛 주소로 진행 중이던 다시 걸기와 탐침을 닫고, 공통 연결 세대를 정해 `gdakiTsInstall`(3859)로 설치하고, 새 listen
주소를 `pe.addr`에 둔다. 그 뒤의 소켓 끊김은 앞과 같은 규칙(낮은 rank가 다시 건다)을 따르고, HELLO와 탐침 답은 화신 번호가 맞아야 받는다(펜싱).
REJOIN은 고정 크기 제어 메시지이고 rkey 목록은 자료 소켓으로 온다.

**생존 rank 쪽 복원 라운드**(상대 r 하나, `gdakiTsBusy` 안, 한도 `roundMs`):
1. `ncclGinRecoverPrepare(comm, r)`(2143–2330): 생산자 정지 확인, QP를 ERR로(2243–2255; hold 시작에서 이미 ERR), drain(2257–2303: 죽은 상대로 간 WQE는
   flush 오류 CQE로 끝난다), 각 QP의 이 에폭 WQE 수 S와 새 보내기 PSN을 얻는다. 응답 쪽 rmsn을 이때 한 번 더 읽어 누적 실행 수 X를 확인한다(RL13). QP는 hold 시작의 2ERR 뒤로
   아무것도 실행하지 않으므로, 예비 프로세스에 X를 먼저 보낸 값(그림)과 같다.
2. `gdakiTsNonMsg`를 읽어 READ나 DUMP가 있으면 FALLBACK(get은 실행된 것으로 칠 수 없음).
3. 생존 rank의 토큰(QPN, 새 PSN)을 예비 프로세스에 보내고, 예비 프로세스가 자기 QP를 그 PSN으로 이은 READY를 기다린다.
4. 끝점 바꿈(RL7): `rq.exch`를 예비 프로세스의 QPN, GID, LID로.
5. `ncclGinRecoverCommit(comm, r, &spareToken)`(2334–2529): 2RST, 장치 색인 0, 새 QPN에 연결(예비 프로세스의 보내기 PSN을 받는 PSN으로).
6. `gdakiTsBaseline`(4351): 새 화신의 rmsn 기준.
7. rkey 표 칸 r 바꿈(RL9).
8. `gdakiTsRepostApply`(4692–4897)를 QP마다 `U = S, n = 0`인 계획으로 부른다(응답 쪽이 Commit 뒤 게시 전에 상대가 죽은 경우는 강한 죽음 증거가 아니라
   fail-fast다, DESIGN_POLICY.md 3절): 커밋 지점(포기한 장치 대기가 있으면 FALLBACK), PUBLISHING, `lbase += U`, 짝수 에폭 게시. 쉬던 요청 대기는 자기
   표가 `lbase`보다 작으므로 성공으로 끝난다(`tsPoll` 1086–1092) `[소스]`. 그 WQE들의 효과는 로그 적용으로 예비 프로세스의 메모리에 이미 들어 있으므로
   맞는 의미다 `[추론]`.

**시간 어림** `[추론]`: 죽음 판정은 kill 뒤 수 ms(gin-remaining의 kill 셀). 예비 프로세스 활성화와 초기화 재생(CUDA 문맥은 미리 있음: NCCL 초기화,
window 등록, devComm과 GIN 문맥, NIC 루프백 설정 3.0–10.9 ms `[문서: gin-remaining 15절]`) 0.5–3 s, 체크포인트와 로그 받기(MB 단위, TCP) 0.1 s 안팎,
복원 라운드 QP마다 수 ms. 합 1–5 s. 예비 프로세스는 rank 1이 돌고 있는 GPU를 나눠 쓰므로 시분할로 더 늦을 수 있다.

### 9.4 체크포인트

**무엇을.** 단계 hook 때의 r의 상태: (a) r이 등록한 모든 GIN window의 내용, (b) application이 `ncclGinRestoreRegister`로 더 등록한 장치 버퍼,
(c) 신호 표와 카운터 표의 r 몫, (d) 호스트 덩어리(application이 hook에 넘김: 단계 번호, 신호 기준값 등), (e) 라이브러리 상태: 상대마다 절단점(로그
위치와 누적 메시지 수), 상대마다 그때의 실행 수 `P_q`(r→q, 생존 rank q의 응답 쪽 누적 실행 수), 화신 번호.

**application의 협조(피할 수 없음, 최소로).** 라이브러리는 application의 장치 상태가 언제 일관된지, 호스트의 어느 값이 다음 단계를 정하는지 모른다.
그래서 두 호출을 요구한다.
- `ncclGinRestoreStep(comm, step, blob, bytes)`: 커널 사이(그 커널이 마지막 flush까지 끝낸 뒤)에 부른다. 간격(`NCCL_GIN_RESTORE_CKPT_STEPS`)마다
  체크포인트를 찍고, 아니면 바로 돌아온다.
- `ncclGinRestoreResume(comm, &step, blob, &bytes)`: devComm을 만든 뒤 부른다. 처음 화신은 단계 0을, 예비 프로세스는 복원한 단계와 덩어리를 돌려준다.
  상태(window, 등록 버퍼, 신호)는 돌아오기 전에 복원된다.
- 다음 단계를 정하는 장치 상태는 모두 window나 등록 버퍼에 있어야 한다. 9.7절의 결정성 요구도 application의 몫이다.

**언제, 어떻게(입력 멈춤).** 단계 hook에서 r의 helper가:
1. 모든 상대 q에게 `CKPT_PAUSE(k)`를 보낸다.
2. q의 helper는 r로 가는 QP의 게이트를 홀수 에폭으로 쓰고 개수 0을 기다리고 모아 둔 WQE의 doorbell을 울린 뒤(보내기가 모두 게이트를 나오고 낸 것은
   모두 NIC로 감; `gdakiTsQuiesce`에서 2ERR만 뺀 차례), 로그의 쓰기 위치 `L_q`와 r로 보낸 누적
   메시지 수 `M_q`, 자기 응답 쪽 누적 실행 수 `P_q`(r→q)를 `PAUSED`로 답한다. q가 라운드 중이면 `BUSY`로 답하고 r은 이번 체크포인트를 건너뛴다.
3. r은 응답 쪽 QP의 rmsn이 `M_q`에 이를 때까지(QUERY_QP, 펌웨어 가드 밖, 한도 있음) 기다린 뒤, NIC 루프백 READ 하나로 그 쓰기들이 GPU 메모리에 닿았음을 확인하고
   (gin-remaining의 flush 규칙과 같은 근거, DESIGN_POLICY.md 5절 B3), window와 신호 표를 GPU 안의 사본으로 복사한다(장치 안 복사).
4. `CKPT_RESUME(k)`: q는 짝수 에폭을 새로 게시한다(빈 라운드: `lbase` 그대로). 단 q가 그동안 r을 거절하지 않았고, 멈춤 뒤 진짜 라운드가 없었고, 게이트가
   아직 멈춤 때의 에폭일 때만이다. 아니면 그 체크포인트는 버린다(DESIGN_POLICY.md C1). 생존 rank의 멈춤은 1–4의 시간이다.
5. r은 사본을 블록(초안 64 KiB)으로 나눠 해시하고, 지난 확정 체크포인트와 다른 블록만 짝에게 보낸다(증분). 짝이 다 받으면 `CKPT_STABLE(k)`를 모든
   상대에게 보내고, 상대는 그때 로그를 `L_q`까지 지운다.

**어디에.** 짝의 호스트 메모리(이 테스트베드에서 rank 3의 짝은 rain의 rank 2). 짝은 마지막 확정 이미지 하나와 받는 중인 것 하나를 둔다. 큰 전송은
helper 소켓이 아니라 별도 자료 소켓과 스레드로 한다(helper 루프가 막히지 않게).

**비용 어림** `[추론]`: 생존 rank의 멈춤 = 소켓 왕복 둘(수백 µs) + drain + 장치 안 복사(window 수 MB면 수십 µs) ≈ 1–5 ms. r의 단계 hook 시간 = 그것 +
D2H와 해시, 전송(비동기로 다음 단계와 겹칠 수 있음). 메모리: r의 GPU에 window 크기의 사본 하나, 짝의 호스트에 이미지 둘.

**왜 멈춤인가.** 멈춤 없이 찍으려면 신호 표를 읽는 순간과 응답 쪽 실행 수를 읽는 순간을 맞춰야 한다. 신호 더하기는 멱등이 아니라서 절단점이 한 메시지만
어긋나도 신호 값이 틀린다. 쓰기는 같은 값을 다시 써도 되지만(단일 대입, 9.7절) 신호는 그렇지 않다 `[추론]`. 멈춤 없는 절단(앞뒤 rmsn이 같을 때까지
다시 찍기)은 v2 후보로 남긴다.

### 9.5 송신 쪽 로그

**무엇을.** 모든 rank가 모든 상대에게 보내는 put, putValue, 신호를 (컨텍스트, 상대) QP마다 장치 메모리 고리에 적는다. 항목(64 B): 그 연산이 낸 요청
메시지 수, 종류, 대상 window 번호, 오프셋, 바이트 수, 신호 번호와 더하는 값, 내용의 고리 안 위치. 내용은 따로 고리(바이트)에 복사한다. 형식과 규칙의
원문은 [proto/rs_core.h](proto/rs_core.h)다.

**언제, 누가.** put 경로(`putImplMode`, `gin_gdaki.h` 458–547)의 게이트 안(`tsGateEnter` 501 뒤, `tsPostLeave` 537 전)에서. 항목과 내용 자리는 원자
더하기로 잡고(여러 스레드가 한 QP에 보내도 됨), 내용은 그 coop의 스레드가 함께 복사한다. 게이트 안에서 쓰므로 입력 멈춤(게이트 홀수)과 개수 0 확인이
"그때까지의 항목이 모두 다 적힘"을 뜻한다.

**지우기.** 상대 r의 `CKPT_STABLE(k)`를 받으면 그 QP의 꼬리를 `L_q(k)`로 옮긴다(호스트가 NIC 루프백으로 꼬리 단어를 씀). 쓰는 쪽은 꼬리를 보고 남은
자리를 안다.

**넘침.** 고리가 차면 그 연산은 로그 없이 보내고 그 통로에 넘침 표시를 한다. 넘친 통로의 상대는 다음 확정 체크포인트까지 `ARMED`가 아니다(그 사이
죽으면 앞 빌드의 거절). 보내기를 막지 않는다(생존 rank를 멈추게 하지 않음). 고리 크기는 체크포인트 간격 × 단계당 바이트 × 2 이상으로 잡는다.

**비용 어림** `[추론]`: put마다 원자 더하기 둘, 항목 쓰기 64 B, 내용 복사(읽기와 쓰기 각 `bytes`), coop 동기화 둘. 4 KiB put(앞 빌드 p50 10.5 µs
`[문서: gin-remaining 15절]`)에는 1–2 µs, 256 KiB put(38.9 µs)에는 CTA 하나의 복사 대역폭에 따라 5–15 µs를 더할 것이다. 로그를 끄면(`NCCL_GIN_RESTORE=0`)
장치 코드는 측 표 포인터가 0인지 한 번 보고 지나간다.

### 9.6 재실행과 중복 억제

**입력 다시 넣기(예비 프로세스, 커널 시작 전).** 체크포인트 이미지를 window와 등록 버퍼, 신호 표에 쓴 뒤, 생존 rank마다 절단점 뒤의 로그 항목을
차례로 적용한다: 쓰기는 그 오프셋에 내용을, 신호는 그 값을 더한다. 생존 rank의 SQ에 남은(죽음 때 실행되지 않은) WQE는 다시 보내지 않는다. 그것들도
로그에 있으므로 이미 적용됐고, 복원 라운드가 그것들을 실행된 것으로 친다(9.3절 6).

**다시 내는 보내기 거르기.** 통로(r→q, 컨텍스트 c)마다 억제 예산 `B = X_q − P_q`(메시지)를 둔다. `X_q`는 죽음 뒤 q의 응답 쪽 누적 실행 수, `P_q`는
체크포인트 때의 값이다. 둘 다 q의 같은 계수에서 오므로 단위가 같다. RC는 차례대로 실행하므로 실행된 것은 앞에서부터 `X_q − P_q`개다. 재실행은 프로그램
차례로 같은 보내기를 다시 내고, 앞의 `B`개 메시지는 내지 않고 센다. put+신호(메시지 둘)의 가운데에서 예산이 끝나면 신호만 낸다. 그 뒤는 그대로 보낸다
(죽음 때 날아가던 것과 그 뒤의 것).
- 누적 실행 수: 지금의 실행 수는 화신마다다(`gdakiTsExecuted` 4330–4348이 `rmsn − rmsn0`). 계층은 라운드가 기준을 바꿀 때(`gdakiTsBaseline` 4351) 옛
  화신의 실행 수를 누적에 더한다(RL13). 죽은 프로세스의 QP는 없어도 생존 rank 쪽 QP는 남아 있어 QUERY_QP가 된다(ERR에서도, 라운드가 이미 그렇게 함).
- 장치 쪽: 예산이 0이 아닌 QP는 게이트 에폭 반쪽에 새 비트(SUPPRESS)를 두어 **보내기의** 열림 검사(`tsGateEnter` 333)만 실패하게 한다. 대기의 열림
  검사(`tsPollEnter` 365)와 `tsParkStable`(264)은 이 비트를 보지 않는다(공용 `tsWordOpen`에 넣으면 flush와 wait가 끝없이 돎, DESIGN_POLICY.md C6).
  느린 길(`tsGateEnterSlow`, 303–328)이 나가기와 쉬기 전에 예산을 보고 내지 않거나 일부만 낸다. 빠른 경로의 명령 수는 그대로다 `[추론]`. 비트는 helper만
  쓰고, 예산이 남은 동안 에폭 반쪽을 쓸 때마다 OR한다. 예산이 0이 되면 helper가 지운다.
- READ는 응답 쪽 MSN이 세는 요청 메시지라 X − P에 섞인다. 되살릴 rank의 get은 9.7절 8번의 application 요구이고, 억제 느린 길은 예산이 남은 QP에 들어온
  get을 실패로 표시해 복원을 실패시킨다(DESIGN_POLICY.md M2 (c)). 0바이트 put의 NOP와 flush의 DUMP는 메시지가 아니라
  예산을 쓰지 않는다.
- 누적 실행 수는 화신마다 mod 2^24라서, 감시의 QUERY_QP(G7)와 기준 바꿈마다 증분을 더하고 복원 라운드가 2ERR 뒤 Commit 전에 한 번 더 읽는다.
- 억제한 연산은 WQE를 쓰지 않으므로 그 요청의 대기와 flush는 바로 끝난다(요청 표는 실제로 낸 WQE만 셈) `[소스: waitImplCore 1175]`.

**키 읽기 자리.** 생존 rank의 장치 코드는 rkey를 게이트에 들어가기 전에 읽는다(`raddr.key` 476, `signalKey` 1461과 1464, 게이트 501) `[소스]`. 게이트에서
쉬던 스레드는 복원 전에 읽은 옛 rkey로 보낸다. 느린 길 뒤에만 다시 읽으면 모자란다: 게이트가 홀수일 때 옛 키를 읽고 게시 뒤 빠른 경로로 들어가는 보내기가
있을 수 있다. 키 읽기를 게이트 진입 뒤로 옮겨야 하고 이는 빠른 경로의 차례를 바꾼다. 결정이 필요한 막는 문제다([DESIGN_POLICY.md](DESIGN_POLICY.md) 5절 B4).

### 9.7 결정성 요구 (piecewise determinism)

되살린 rank의 체크포인트 뒤 실행은 (체크포인트, 호스트 덩어리, 받은 메시지)의 결정적 함수여야 한다. 이 설계가 application에 요구하는 것:
1. 신호에 대해 data-race-free: 상대가 쓴 window 자리는 그것을 덮는 `waitSignal`이 돌아온 뒤에만 읽는다.
2. 제어 흐름은 `waitSignal`의 문턱에만 기댄다. `readSignal` 값이나 도착 시각에 따라 갈리지 않는다.
3. 단일 대입: 체크포인트에서 재실행 끝까지, 다른 rank가 쓰는 window 자리는 한 번만 쓰인다. 입력을 재실행 전에 한꺼번에 넣기(9.6절) 때문이다. 같은
   자리를 다시 쓰는 workload(고리 버퍼)는 재실행의 진행에 맞춰 입력을 넣어야 하고, 그러려면 보내는 쪽이 받은 쪽의 진행을 알아야 한다(벡터 시계류).
   v1의 범위 밖이다.
4. 원격 읽기(`get`)는 체크포인트에서 재실행 끝까지 바뀌지 않는 메모리에서만. 생존 rank의 메모리가 그 사이 바뀌면 다른 값을 읽기 때문이다.
5. 되살린 rank에서 한 QP로 가는 보내기는 프로그램 차례 하나(스레드 하나 또는 coop 하나)로 낸다. 억제가 "앞의 B개"를 프로그램 차례로 세기 때문이다.
6. GIN 밖의 통신(collective, NCCL P2P, LSA)을 되살릴 rank와 주고받지 않고, hold 정책의 프로세스는 NVSHMEM을 쓰지 않는다(DESIGN_POLICY.md X6).
7. 단계 hook은 그 rank의 커널이 끝나고 마지막 flush가 끝난 뒤에만 부른다(체크포인트 때 r의 보내기가 모두 실행됨: `P_q`가 r이 낸 수와 같음).
8. 되살릴 수 있는 rank와는 어느 방향으로도 `get`을 하지 않는다(4번보다 강함: 생존 rank의 get이 죽음 때 날아가던 중이면 자료 없이 끝나고, 재실행 중인
   rank의 메모리를 읽으면 옛 값을 읽음. DESIGN_POLICY.md M2).
9. 체크포인트에서 재실행 끝까지, 다른 rank가 더하는 신호와 카운터를 초기화하지 않는다(재실행 전에 적용한 로그의 더하기를 지움. DESIGN_POLICY.md P5).
10. 복원한 communicator는 `ncclCommAbort`로 끝낸다(정상 정리의 노드 안 bootstrap 배리어에 되살린 rank가 들어감. DESIGN_POLICY.md P3).
11. communicator마다 투명 복구 GDAKI 문맥이 하나다(devComm 하나, GIN 연결 하나). 둘 이상이면 무장하지 않는다(DESIGN_POLICY.md 2.3절).

**시험 workload가 이를 지키는 방법**(9.8절): 단계마다 칸이 따로 있어 단일 대입(3), 받은 칸은 신호 문턱 뒤에만 읽음(1), 분기는 단계 번호뿐(2), get 없음(4),
보내는 QP마다 스레드 하나(5), GIN만 씀(6), 커널 하나가 단계 하나이고 끝에 flush(7), 신호 초기화 없음(9), 끝은 `ncclCommAbort`(10), devComm 하나(11).
GIN 연결 수가 하나인지는 확인하지 않았다 `[미확인]`.

### 9.8 시험 workload와 판정 기준

[gin_rs.cu](gin_rs.cu)(빌드만 함). 랭크 4개, GPU마다 둘. 컨텍스트는 받는 rank마다 하나(`ctx = dst`)라서 rank b가 받는 모든 put은 b의 컨텍스트 b 신호 0에
더한다. 그래서 b의 `waitSignal(ctx b, 0)`은 어느 rank를 기다리는지 모르는 대기다(목표 상황).
- 상태: rank마다 `B` 바이트 상태 `x`(window 안). 단계 s의 커널: (1) 받는 rank마다 `x`와 (r, dst, s)로 정한 `B` 바이트를 보내기 칸에 만들고 그 rank의
  받기 window의 칸(src, s)에 put + 신호 1, (2) 상대별 flush, (3) `waitSignal(ctx r, 0) ≥ 기준 + (N−1)(s+1)`(시간 제한 없음; 돌아온 뒤 값이 모자라면
  풀린 것으로 셈), (4) 받은 칸 N−1개와 `x`로 새 `x`를 만듦, (5) 단계 실행 수 칸을 1 더함.
- kill: 실행기가 시각으로, 또는 `GIN_RS_DIE_AT=<단계>:<µs>`로 그 단계 커널을 띄운 뒤 µs 지나 자기에게 SIGKILL.
- 기준: 호스트가 같은 함수로 모든 rank의 상태를 차례로 계산한다(`__host__ __device__` 함수 하나).
- 판정: (a) 생존 rank의 `waitSignal`이 풀리지 않음(값이 문턱 이상으로 돌아옴), 비동기 오류 없음; (b) 각 rank의 최종 `x`와 모든 받은 칸이 기준과 같음;
  (c) 생존 rank의 단계 실행 수가 모두 1; (d) 되살린 rank의 마지막 단계가 끝까지; (e) 억제 수가 통로마다 `X − P`.
- 잴 것: 복원 단계별 시각, 다시 넣은 로그 바이트, 체크포인트마다 생존 rank의 멈춤 시간, 단계 시간(로그 켬과 끔).

### 9.9 필요한 라이브러리 hook (gpu-detect `hw` 위)

두 겹이다. 줄 번호는 "hr / hw"다(장치 헤더는 하나).

**gpu-detect 계층에 넣을 정책 hook(G1–G9).** 감지와 반응을 나누는 최소 변경이다. fail-fast(기본)에서 지금의 hw 동작을 그대로 낸다. 원문은
[DESIGN_POLICY.md](DESIGN_POLICY.md) 4.10절이다: G1 정책 칸과 `NCCL_GIN_FAULT_POLICY`, G2 `gdakiTsDecline` 맨 앞의 거절 hook(hr 4916 / hw 4941),
G3 QP 감시의 상대 거르기 hook(hw 6094), G4 기록 처리 루프의 hook(hr 6114–6124 / hw 6399–6409), G5 훑기 유실 검사의 hook(hr 5894–5896 / hw 5923–5925),
G6 에폭 비교의 `coveredEpoch`(hw 6066, 6139, 5460, 3361), G7 감시의 QUERY_QP가 rmsn을 넘김(hw 6111), G8 감시 스레드의 복원 시한(`gdakiTsWatchdog` hw 3488),
G9 펌웨어 초과 책임의 원인(hw 3530).

**복원 계층(hold 분기의 내용).**

| id | 어디에 | 무엇을 |
|---|---|---|
| RL1 | G2의 hold 분기 | (가) 붙잡은 상대에 대한 모든 거절 → fallback(PeerDead, PEER_DEAD), (나) 강한 죽음 증거, ARMED, TOLD 아님 → hold 시작(DESIGN_POLICY.md 3절) |
| RL2 | G4의 hold 분기 | 붙잡은 상대의 기록 흡수, `qs[].handled` 올림 |
| RL3 | G5, G3, G6, G7, G8, G9의 hold 분기 | 붙잡은 상대는 감시와 유실 검사에서 뺌, `coveredEpoch`, rmsn 표본, 감시 스레드의 복원 시한, 펌웨어 초과 책임의 원인 |
| RL4 | helper 루프(hr 6013–6129 / hw 6298–6415) | 복원 상태 기계 한 걸음(TIMED_OUT 확인, 활성화, REJOIN, 로그 보내기, 복원 라운드, FALLBACK(p)와 RESTORED(p) 처리). `gdakiTsBusy`는 hold 시작과 복원 라운드에서. 상태는 상대마다 원자 칸(DESIGN_POLICY.md 3절) |
| RL5 | `gdakiTsStart`(hr 6735– / hw 7040–; `roundMs`를 정하는 곳 hr 6741 / hw 7046) | 복원 시한, `holdMs`, `roundMs`의 관계 검사, communicator 무장 조건(DESIGN_POLICY.md 2.3절). 어기면 fail-fast |
| RL6 | 받기 루프(hr 4164–4243 / hw 4189–4268) | REJOIN: 붙잡은 상대(HELD)에게서만, nonce와 화신 번호, 죽음 표시 지우고 `gdakiTsInstall`(hr 3859 / hw 3884) |
| RL7 | 새 함수, `opMu` 안 | QP마다 `rq.exch`를 새 끝점으로(Commit의 검사 hr 2360 / hw 2361, 연결 hr 2450 / hw 2451 전) |
| RL8 | 새 함수 | 계획 `U = S, n = 0`으로 `gdakiTsRepostApply`(hr 4692 / hw 4717) |
| RL9 | `ncclGinGdakiRegMrSym`(hr 7879–7931 / hw 8198–8250), 문맥 생성(hr 7311–7315 / hw 7630–7634) | rkey 표와 신호, 카운터 표의 등록부. 복원 때 칸 r을 NIC 루프백으로. 이 버퍼들을 `gdakiLbAddRange`에 |
| RL10 | 문맥 생성, `gdakiLbSetup`(hr 6474–6735 / hw 6761–7040) | 로그 고리와 측 표 할당, 루프백 MR, `ncclGinGdakiGPUContext`의 새 칸 |
| RL11 | `gdakiTsMsg`(hr 2953 / hw 2966), helper 루프의 메시지 처리(hr 6074–6083 / hw 6359–6368) | 새 메시지 종류 |
| RL12 | 새 함수 + 낡은 기록 검사(hr 5431 / hw 5460) | 입력 멈춤의 빈 라운드. 검사는 `coveredEpoch`로 |
| RL13 | `gdakiTsExecuted`(hr 4330 / hw 4355), `gdakiTsBaseline`(hr 4351 / hw 4376) | 누적 실행 수 |
| RL14 | `ncclGinTsUserAbortRaise`(hr 2760 / hw 2767), 정리(hr 6962, 7086 / hw 7274, 7405) | CANCELLED, 예비 프로세스에 BYE |
| RL15 | 확대 상한(hr 5081 / hw 5106) | 복원 라운드와 빈 라운드는 세지 않음 |
| RL17 | `gdakiTsServeLower`(hr 5372–5373 / hw 5401–5402) | 새 메시지 미루기 |
| RL18 | 자료 서버(새 스레드, 새 포트) | 체크포인트 블록, 로그 내보내기 |
| RL19 | 통계 API(hr 7135 / hw 7454) | 복원 수 |

장치 쪽(DV1–DV4)과 예비 프로세스 쪽(SP1–SP6)은 아래 그대로다.

| id | 무엇을 |
|---|---|
| DV1 | `ncclGinGdakiGPUContext`(common.h 222–236)에 측 표 포인터 `restore` 칸: QP마다 로그 고리 설명, 보낸 메시지 수, 억제 예산 |
| DV2 | `putImplMode`(gin_gdaki.h 458–547), `putValueImplMode`(577–), 신호 길에서 게이트 안 로그 쓰기(9.5절). hold가 아니면 측 표 포인터가 0 |
| DV3 | `raddr.key`와 `signalKey`를 게이트 진입(501) 뒤에 읽음. `signalKey`는 지금 호출자가 계산해 값으로 넘기므로(1458–1468) 그 계산을 `putImplMode` 안으로 옮김. 빠른 경로의 차례가 바뀌므로 결정 대기(DESIGN_POLICY.md 5절 B4) |
| DV4 | 게이트 에폭 반쪽의 SUPPRESS 비트(`EPOCH_MASK`를 `0x1fffffff`로). 보내기의 열림 검사(`tsGateEnter` 333)에만 넣고 공용 `tsWordOpen`(146–148)과 대기 쪽(`tsPollEnter` 365, `tsParkStable` 264)에는 넣지 않음. 장치가 에폭 반쪽을 값으로 쓰는 자리(364–366, 1106–1108, 1037, 206–207)에서 지움. 느린 길의 억제와 put+신호 나누기(DESIGN_POLICY.md C6) |

| id | 무엇을 |
|---|---|
| SP1 | 초기화 기록: bootstrap API와 GIN collComm의 결과를 원래 rank가 적고 짝에게 맡김 |
| SP2 | 예비 모드 `ncclCommInitRank`: 활성화를 기다리고, bootstrap 호출을 기록으로 대답(종류, 태그, 크기 검사), 자기 몫은 새 값 |
| SP3 | 예비 모드 GIN 문맥: 새 QP를 기록의 생존 rank QPN에 연결, helper 설정은 기록의 salt로 nonce, REJOIN으로 모든 생존 rank에 걺 |
| SP4 | window 등록: rkey 표에 기록의 생존 rank rkey, 자기 칸은 새 rkey. 새 rkey와 신호 표 rkey를 REJOIN에 실음 |
| SP5 | 상태 적용: 짝에게서 이미지, 생존 rank에게서 로그와 `X_q` |
| SP6 | `ncclGinRestoreResume`이 단계와 덩어리를 돌려줌. 억제 예산을 측 표에 쓰고 SUPPRESS 비트를 켬 |

### 9.10 기존 장치와의 상호작용 표

[DESIGN_POLICY.md](DESIGN_POLICY.md) 4절로 옮겼다(fail-fast와 hold-for-restore의 동작, 우선, hr/hw/nvs 코드 위치, 바꿀 것).

### 9.11 막는 문제

[DESIGN_POLICY.md](DESIGN_POLICY.md) 5절로 옮겼다.

### 9.12 선행 연구

이 세션에서 논문을 다시 읽지 않았다. 아래 설명은 기억에 기댄 것이라 모두 `[미확인]`이다.
- **송신 쪽 메시지 로그(Johnson과 Zwaenepoel, 1987).** 보내는 쪽이 메시지를 자기 메모리에 두고, 받는 쪽이 받은 차례(RSN)를 돌려주며, 실패한 프로세스는
  체크포인트에서 다시 시작해 그 차례대로 메시지를 다시 받는다. 단편 결정성을 가정하고, 한 번에 하나의 실패를 견딘다. 같은 것: 송신 쪽 로그, 단편 결정성,
  생존자는 되돌아가지 않음. 다른 것: 한쪽 RDMA라 받는 CPU가 차례를 매기지 못함. 그래서 이 설계는 RSN 대신 입력 멈춤으로 정확한 절단점을 만들고,
  단일 대입과 교환 가능한 신호 더하기로 차례의 필요를 없애고, NIC의 응답 쪽 실행 수로 중복을 거른다.
- **MPICH-V(2002–2004).** V1은 채널 메모리, V2는 송신 쪽 로그와 받은 차례를 믿을 만한 노드의 event logger에 두는 방식, Vcl은 협조 체크포인트다.
  같은 것: 송신 쪽 내용 로그. 다른 것: 받은 차례(결정 요소) 로그가 없음(한쪽 연산에는 받는 쪽 사건이 없다), 장치 communicator를 제자리에서 되살림.
- **Charm++의 메모리 안 체크포인트와 메시지 로그(FTC-Charm++, 2004; Chakravorty와 Kalé의 빠른 복구 규약, 2007).** 짝 프로세서 메모리에 두 겹
  체크포인트, 메시지 로그와 함께 쓰면 실패한 프로세서의 객체만 되살린다. 같은 것: 짝 메모리 체크포인트, 실패한 것만 되살림. 다른 것: Charm++는 객체를
  다른 프로세서로 옮겨 복구를 나눌 수 있는 런타임이고, 여기서는 논리 rank 하나를 예비 프로세스 하나에 그대로 옮긴다.
- **LLM 학습의 메모리 안 체크포인트(Gemini, SOSP 2023; CheckFreq, FAST 2021; Just-In-Time checkpointing, EuroSys 2024; Oobleck, SOSP 2023 등).**
  체크포인트를 다른 노드의 CPU 메모리에 두어 빨리 되살리거나, 실패 순간 다른 복제본의 상태로 바로 찍는다. 같은 것: 짝의 호스트 메모리, 예비 장비.
  다른 것: 이들은 반복 경계에서 모든 rank가 함께 되돌아가거나(전역 일관 상태), 데이터 병렬 복제본에 기대고, 메시지 로그가 없다. 이 설계는 생존 rank를
  되돌리지 않는 대신 결정성과 로그를 요구한다.
- **NCCL grow로 바꾸기.** 생존 rank가 shrink 뒤 grow로 새 rank를 들이면 새 communicator와 새 devComm이 생겨, 도는 커널의 `waitSignal`은 지킬 수 없다
  `[소스: nccl.h.in 349–363, 추론]`. 이 설계는 도는 커널을 지키려고 같은 communicator를 제자리에서 고친다.

### 9.13 시제품 (멈춤)

처음 계획은 라이브러리 계층이 없어도 되는 부분(로그 고리, 체크포인트 저장소, 복원 계획과 억제, CPU 모의, 시험 프로그램)을 먼저 만들어 rain의 CPU에서
단위 시험하는 것이었다. 사용자 결정(2026-10-09)으로 멈췄다: 죽음에 대한 반응 정책이 정해지고 충돌이 없다는 검토가 끝나기 전에는 아무것도 구현하거나
빌드하지 않는다. 그 전에 쓴 초안(`rs_core.h`, `rs_host.h`, `rs_host.cc`, `rs_test.cc`, `rs_sim.cc`)은 컴파일도 실행도 하지 않았고, 저장소에 넣지
않고 세션 스크래치 `agent_restore/proto_draft_unbuilt/`에 두었다. 시험 프로그램 `gin_rs.cu`는 쓰지 않았다. 그 초안에서 설계로 옮긴 것: 로그 넘침의
위치(`ovfSeq`)로 무장을 판단하는 규칙(9.5절), 복원 뒤 생존 rank가 자기 다음 체크포인트까지 무장하지 않는 창([DESIGN_POLICY.md](DESIGN_POLICY.md) 3절).

### 9.14 실행 방법 (계획)

계층이 생긴 뒤: 빌드는 gpu-detect의 `build_gd.sh`를 본뜬 `build_rs.sh`의 `layer` 단계, 배포는 새 디렉터리 `rs/`, `rsp/`, 실행은 gin-remaining의
`run_mr_hr.sh`를 본떠 예비 프로세스를 함께 띄우는 실행기, 모두 `cluster_run.sh` 안. 실행기와 셀 파일은 아직 쓰지 않았다.

## 10. 완료 조건과 QA 기준

- [ ] [DESIGN_POLICY.md](DESIGN_POLICY.md) 5절의 막는 문제가 풀렸고, 그 문서의 독립 검토가 남은 충돌이 없다고 했다.
- [ ] 9.9절 계층을 구현하고 독립 리뷰를 받았다.
- [ ] 모든 셀이 계획한 n만큼 실행됐다(제외와 실패를 따로 센 표 포함).
- [ ] 예측마다 판정과 놓친 시행 목록이 있다.
- [ ] 핵심 수치를 원자료에서 다시 계산했다(다른 에이전트).
- [ ] smoke, pilot, 제외 시행이 결과에 섞이지 않았다.
- [ ] 원자료를 Release에 올리고 DATA.md에 적었다.

## 11. 작업 체크리스트

- [x] 앞 실험의 측정 다시 셈(1절), `hr` 소스와 gpu-detect 초안 읽기
- [x] 설계 초안(9.1–9.8절), hook 목록(9.9절)
- [x] 감지와 반응을 나눈 정책 설계와 통합 상호작용 표([DESIGN_POLICY.md](DESIGN_POLICY.md))
- [ ] 독립 충돌 검토 둘(EXPERIMENT.md 초안 표, DESIGN_POLICY.md)과 반영
- [ ] 사용자의 설계 승인(그 전에는 구현과 빌드 없음)
- [ ] gpu-detect 계층에 정책 hook G1–G9(DESIGN_POLICY.md 4.10절)
- [ ] 시제품: 로그, 체크포인트, 복원 계획, 억제, 모의, 단위 시험(9.13절, 멈춤)
- [ ] 시험 프로그램 `gin_rs.cu`
- [ ] B1 시험(초기화 재생), B2 확인(LSA), B3 시험(drain)
- [ ] gpu-detect 계층 확정 뒤 이 계층 구현, 리뷰
- [ ] 실행기, 셀, 채점기, 예측 고정, pilot, 사전 등록
- [ ] 본 실행, 채점, QA, 결론

## 12. 실행 기록 (시간순)

| 시각 | 무엇을 했나 | 결과와 근거(경로, 커밋, 실행 ID) |
|---|---|---|
| 2026-10-09 | gin-remaining 시행별 표에서 degraded 셀을 다시 셈 | 1절 `[측정]` |
| 2026-10-09 | `hr` 트리(`agent_ts2hr/nccl-src`)와 gpu-detect 초안(`agent_gd/gin/nccl-src`, `hw_layer.diff`)을 읽고 설계 초안과 상호작용 표 작성. 두 트리는 고치지 않음 | 9절 |
| 2026-10-09 | 독립 충돌 검토 1(읽기 전용 에이전트)에 이 문서의 초안 표를 맡김 | [DESIGN_POLICY.md](DESIGN_POLICY.md) 6절 |
| 2026-10-09 | gpu-detect `hw` 계층이 빌드됨(실행, 병합 전; diff md5 `be0ea9ed`, libnccl `efc48ca1`) → 줄 번호를 hr/hw 둘로, 표에 hw 행(QP 감시, `DEGRADED_ROUNDS`, 감시의 펌웨어 부하) 더함 | DESIGN_POLICY.md 4절 |
| 2026-10-09 | 사용자 결정: 충돌이 남은 동안 구현 없음, 감지와 반응을 나눈 통합 설계 문서를 먼저. 시제품 초안(빌드, 실행 안 함)을 스크래치로 옮기고 멈춤. [DESIGN_POLICY.md](DESIGN_POLICY.md) 작성 | 9.13절 |

## 13. 사전 등록 이후 변경

없음(사전 등록 전).

| 날짜 | 무엇을 | 이유 | 영향 범위 | 커밋 |
|---|---|---|---|---|

## 14. 원자료와 결과표

| 무엇 | 경로 또는 Release 자산 | n |
|---|---|--:|

## 15. 결과 요약

`[미확인]` 본 실험 전이다.

## 16. QA와 재현성

아직 없다.

## 17. 결론

아직 없다.

## 18. 한계

- 설계 단계다. 라이브러리 계층, 예비 모드 초기화, 실행기가 없다.
- 결정성 요구(9.7절)가 application을 크게 제한한다: 단일 대입, 신호 문턱에만 기대는 분기, 변하는 메모리의 get 없음, GIN만 씀.
- 동시 다중 실패, 복원 중 실패, 노드 고장은 다루지 않는다.

## 19. 다음 작업

- 막는 문제를 먼저 푼다([DESIGN_POLICY.md](DESIGN_POLICY.md) 5절).
- gpu-detect 계층이 확정되면 그 위에 9.9절 계층을 만든다.

## 20. 참고자료

- `../remaining/EXPERIMENT.md` 9절 1번 (c)(degraded), (f)(재리뷰 M-A, L-C, M-C), 15, 17–19절
- `../peer/EXPERIMENT.md`(상대별 단어), `../multirank/EXPERIMENT.md`(랭크 4개, GPU 나눠 쓰기), `../handoff/EXPERIMENT.md`(shrink 넘기기, CUDA 호출)
- gpu-detect 초안 `harness/gpu-detect/EXPERIMENT.md` 9.1절(gpu-detect worktree, 아직 master에 없음)
- 9.12절의 논문들 `[미확인]`
