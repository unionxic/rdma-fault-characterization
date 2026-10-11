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
| 마지막 갱신 | 2026-10-09, 초안: 설계(9.1–9.8절), 필요한 hook(9.9절). 사용자 결정으로 감지와 반응을 나눈 정책 설계와 통합 상호작용 표, 막는 문제를 [DESIGN_POLICY.md](DESIGN_POLICY.md)로 옮김. 충돌이 남은 동안 구현 없음(시제품 멈춤, 9.13절). 사용자 결정(2026-10-09): B4는 (나)(검토 3과 재확인: 풀리지 않은 충돌 없음), B1–B3은 실행 가능성 시험(9.15절, 채점 안 함; 설계와 코드의 독립 검토 반영). 시험 결과(2026-10-09): B2 해결 A, B1 초기화 재생이 이 범위에서 됨, B3 열림(rain의 GPU 경합 셀이 두 번 다 미결, 사용자 결정 대기). 복원 계층은 여전히 구현하지 않음 |

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
| `lat_hold_unarmed` | 4 KiB, 256 KiB: hold 정책이지만 무장 전 대 fail-fast. `ncclGinRestoreStep`을 부르지 않아 멈춤이 없고 로그도 없음. 잼 = 키 다시 읽기 + coop 추가 동기화 | `@rsp` 각 5 | 비용(B4 (나), 검토 3 W2, 재확인 X1) |
| `lat_ff_branch` | 4 KiB, 256 KiB put과 4 KiB get: fail-fast에서 이 계층의 빌드 대 `hw` 운영 빌드(put은 분기 하나와 내부 인자 하나, get은 포인터 읽기 하나와 분기 하나) | `@rsp`, `@hwp` 각 5 | 비용(검토 3 W2, W8, 재확인 X3) |

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
  │                                                                            모든 DONE_RS 뒤 RESTORED(r)를 모두에게
  ├─ (게시 전 CAS: HELD → COMMITTING; 게시 뒤 PUBLISHED; RESTORED 받으면 무장 조건에 따라 ARMED 또는 OFF)
  └─ 시한(감시 스레드), 실패, 누구든 FALLBACK(r, 화신) → 그 화신을 PeerDead 거절 → 2 s 뒤 degraded. 예비 프로세스는 BYE 없이 끝남
```

원칙 셋 `[추론]`:
- 생존 rank는 CUDA 호출을 하지 않는다(gin-handoff, gin-remaining: application의 CUDA 호출이 helper의 스트림을 묶을 수 있음). 생존 rank 쪽 일은
  helper 소켓, 펌웨어 명령, NIC 루프백 복사(이미 있는 길)뿐이다. 무거운 CUDA 일(초기화, 메모리 복원)은 할 일이 없는 예비 프로세스가 한다.
- 빠른 경로는 바꾸지 않는다. 로그 쓰기(9.5절)만 빠른 경로에 더한다(hold가 아니면 측 표 포인터를 한 번 보는 것). 억제는 게이트의 느린 길에서만 한다.
  키 읽기 자리는 이 원칙과 충돌했다(DESIGN_POLICY.md 5절 B4). 사용자 결정(2026-10-09, (나)): 키를 게이트 진입 뒤에 다시 읽는 것은 hold 정책의
  communicator에서만 하고, fail-fast의 빠른 경로는 키 읽기 자리를 그대로 두고 측 표 포인터의 분기 하나만 더한다(9.6절, 9.9절 DV3).
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
  잇기와 받기(6255–6308)도 건너뛴다(DESIGN_POLICY.md A3). host RMA proxy는 상대마다 따로 IB 연결을 맺으므로 꺼 둔다(무장 조건, B1 설계 검토 T1-1). 원래 rank의 listen 주소와 다른 포트에 묶고, 설치되기 전에는 REJOIN 말고 아무것에도 답하지
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
7. rkey 표 칸 r 바꿈(RL9): 모든 window rkey 표와 신호 표의 칸 r을 NIC 루프백으로 쓰고, 다 쓴 뒤 READ 하나로 GPU 메모리에 닿았음을 확인한다(게시 전,
   DESIGN_POLICY.md A1 (3), 검토 3 W5).
8. 게시 전 확인(4708) 뒤, 커밋 지점(4713) 전에 상태 CAS(HELD → COMMITTING). 지면(감시 스레드의 시한이 이김) fallback.
   `gdakiTsRepostApply`(4692–4897)를 QP마다 `U = S, n = 0`인 계획으로 부른다(응답 쪽이 Commit 뒤 게시 전에 상대가 죽은 경우는 강한 죽음 증거가 아니라
   fail-fast다. gpu-detect가 그 길을 고친 뒤에도 그 거절에는 `pe.lostAfterCommit`가 서 있어 붙잡지 않는다, DESIGN_POLICY.md 2.4절과 3절): 커밋 지점(포기한
   장치 대기가 있으면 FALLBACK), PUBLISHING, `lbase += U`, 짝수 에폭 게시. 쉬던 요청 대기는 자기
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
   B3 설계 검토(2026-10-09, T3-2, T3-6, T3-8)로 정한 것: READ는 window가 아니라 측 표 안의 8바이트 fence 낱말(문맥을 만들 때 NIC 복사 경로의 strict 루프백
   MR에 등록된 다른 할당, DESIGN_POLICY.md 2.3절)을 읽는다. window 내용은 루프백 MR에 없다. 복사는 copy engine(r의 단계 hook에서 r의 스트림에
   `cudaMemcpyAsync` D2D)이다. QUERY_QP는 예상 drain 시각에 처음 내고 그 뒤 50 µs 이상 띄우며, 체크포인트마다 상한을 둔다(수는 B3 시험이 정함).
   멈춤 전 마지막 메시지는 신호 없는 put일 수 있으므로, 마지막의 신호 원자 연산이 앞의 쓰기를 밀어 주리라고(그 원자 연산의 PCIe 읽기가 앞의 posted 쓰기를
   앞지르지 못함) 기대지 않는다(T3-1). READ로 모자라면 대안은 `cuFlushGPUDirectRDMAWrites`(r은 단계 hook에 있어 CUDA를 부를 수 있음)다(T3-5).
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
"그때까지의 항목이 모두 다 적힘"을 뜻한다. 로그는 측 표의 QP마다 "로그 켬" 낱말이 선 QP에서만 쓴다. helper는 그 낱말을 그 QP의 첫 입력 멈춤 안(게이트 홀수,
개수 0)에서 NIC 루프백으로 세우므로 로그의 시작이 절단점과 같다(DESIGN_POLICY.md C2, 검토 3 W2). 측 표 포인터만으로는 로그를 켜지 않는다(그 포인터는 hold 정책이면
문맥을 만들 때부터 0이 아니고 키 다시 읽기를 뜻함, 9.6절).

**지우기.** 상대 r의 `CKPT_STABLE(k)`를 받으면 그 QP의 꼬리를 `L_q(k)`로 옮긴다(호스트가 NIC 루프백으로 꼬리 단어를 씀). 쓰는 쪽은 꼬리를 보고 남은
자리를 안다.

**넘침.** 고리가 차면 그 연산은 로그 없이 보내고 그 통로에 넘침 표시를 한다. 넘친 통로의 상대는 다음 확정 체크포인트까지 `ARMED`가 아니다(그 사이
죽으면 앞 빌드의 거절). 보내기를 막지 않는다(생존 rank를 멈추게 하지 않음). 고리 크기는 체크포인트 간격 × 단계당 바이트 × 2 이상으로 잡는다.

**비용 어림** `[추론]`: put마다 원자 더하기 둘, 항목 쓰기 64 B, 내용 복사(읽기와 쓰기 각 `bytes`), coop 동기화 둘. 4 KiB put(앞 빌드 p50 10.5 µs
`[문서: gin-remaining 15절]`)에는 1–2 µs, 256 KiB put(38.9 µs)에는 CTA 하나의 복사 대역폭에 따라 5–15 µs를 더할 것이다. 로그를 끄면(`NCCL_GIN_RESTORE=0`)
장치 코드는 측 표 포인터가 0인지 한 번 보고 지나간다. hold 정책의 communicator는 여기에 게이트 뒤의 키 다시 읽기(9.6절, L1을 거치지 않는 읽기 한둘)가
더해진다. 이 비용도 LT1, LT2에서 함께 잰다.

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
있을 수 있다. 키 읽기를 게이트 진입 뒤로 옮겨야 하고 이는 빠른 경로의 차례를 바꾼다([DESIGN_POLICY.md](DESIGN_POLICY.md) 5절 B4). (이 문단은 결정 전의
것이다. 결정 (나)는 키 읽기를 옮기지 않고 hold에서만 게이트 뒤에 다시 읽는다, 아래.)

사용자 결정(2026-10-09, (나)): 게이트 진입 뒤의 키 다시 읽기는 hold 정책의 communicator에서만 한다. 갈림은 측 표 포인터(DV1)가 0인지로 한다. 그 포인터는
문맥을 만드는 중(`gdakiTsStart`, `ncclGinGdakiCreateContext`가 돌아오기 전) 한 번 쓰고 그 뒤 바뀌지 않는다(DESIGN_POLICY.md 2.3절, 검토 3 W1).
fail-fast는 키를 지금 자리에서 지금 방식(`loadConst`, L1 적중)으로 읽고, 더해지는 것은 DV2와 같은 포인터 읽기에 기대는 분기 하나와 내부 인자 하나다.
hold는 `tsGateEnter`가 참을 돌려준 뒤(빠른 길이든 느린 길이든) window rkey와 신호 rkey를, get은 원격 window rkey를 L1을 거치지 않는 시스템 범위
relaxed 읽기로 다시 읽어 보낸다(put, putValue, get 모두; 검토 3 W3, W4). 자세한 것은 9.9절 DV3와 [DESIGN_POLICY.md](DESIGN_POLICY.md) A1이다.

### 9.7 결정성 요구 (piecewise determinism)

되살린 rank의 체크포인트 뒤 실행은 (체크포인트, 호스트 덩어리, 받은 메시지)의 결정적 함수여야 한다. 이 설계가 application에 요구하는 것:
1. 신호에 대해 data-race-free: 상대가 쓴 window 자리는 그것을 덮는 `waitSignal`이 돌아온 뒤에만 읽는다.
2. 제어 흐름은 `waitSignal`의 문턱에만 기댄다. `readSignal` 값이나 도착 시각에 따라 갈리지 않는다.
3. 단일 대입: 체크포인트에서 재실행 끝까지, 다른 rank가 쓰는 window 자리는 한 번만 쓰인다. 입력을 재실행 전에 한꺼번에 넣기(9.6절) 때문이다. 같은
   자리를 다시 쓰는 workload(고리 버퍼)는 재실행의 진행에 맞춰 입력을 넣어야 하고, 그러려면 보내는 쪽이 받은 쪽의 진행을 알아야 한다(벡터 시계류).
   v1의 범위 밖이다.
4. 원격 읽기(`get`)는 체크포인트에서 재실행 끝까지 바뀌지 않는 메모리에서만. 생존 rank의 메모리가 그 사이 바뀌면 다른 값을 읽기 때문이다.
5. 되살린 rank에서 한 QP로 가는 보내기는 프로그램 차례 하나(스레드 하나 또는 coop 하나)로 낸다. 억제가 "앞의 B개"를 프로그램 차례로 세기 때문이다.
6. GIN 밖의 통신(collective, NCCL P2P, LSA, host RMA)을 되살릴 rank와 주고받지 않고, hold 정책의 프로세스는 NVSHMEM을 쓰지 않는다(DESIGN_POLICY.md X6).
   host에서 띄운 NCCL 호출은 runtime connect로 상대 버퍼를 가져오는 전송을 만든다(B2 설계 검토 T2-3). host RMA는 꺼야 한다(`NCCL_NUM_RMA_CTX=0`, DESIGN_POLICY.md 2.3절).
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
| RL9 | `ncclGinGdakiRegMrSym`(hr 7879–7931 / hw 8198–8250), 문맥 생성(hr 7311–7315 / hw 7630–7634), `gdakiLbSetup`(hr 6474– / hw 6761–) | window 등록은 rkey 표의 자리만 등록부에 적고, 루프백 MR 등록(`gdakiLbAddRange`)은 GDAKI 문맥을 만들 때(devComm 생성, `gin_host.cc` 374) 그때까지의 표에만 한다. 그 뒤 등록한 window가 있으면 무장 안 함. 복원 때 칸 r을 NIC 루프백으로 쓰고, 다 쓴 뒤 READ 하나로 확인하고 나서 게시(DESIGN_POLICY.md T5, A1 (3)) |
| RL10 | 문맥 생성, `gdakiLbSetup`(hr 6474–6735 / hw 6761–7040), `gdakiTsStart`(hw 7040–) | 로그 고리와 측 표 할당, 루프백 MR, `ncclGinGdakiGPUContext`의 새 칸. GPU 문맥은 `gdakiTsSetup`보다 먼저 장치로 복사되므로(hw 7966) 측 표 포인터 칸은 `gdakiTsStart` 안에서 H2D 한 번으로 따로 쓰고, `ncclGinGdakiCreateContext`가 돌아온 뒤에는 쓰지 않음(DESIGN_POLICY.md 2.3절, 검토 3 W1) |
| RL11 | `gdakiTsMsg`(hr 2953 / hw 2966), helper 루프의 메시지 처리(hr 6074–6083 / hw 6359–6368) | 새 메시지 종류 |
| RL12 | 새 함수 + 낡은 기록 검사(hr 5431 / hw 5460) | 입력 멈춤의 빈 라운드. 검사는 `coveredEpoch`로 |
| RL13 | `gdakiTsExecuted`(hr 4330 / hw 4355), `gdakiTsBaseline`(hr 4351 / hw 4376) | 누적 실행 수 |
| RL14 | `ncclGinTsUserAbortRaise`(hr 2760 / hw 2767), 정리(hr 6962, 7086 / hw 7274, 7405) | CANCELLED, 예비 프로세스에 BYE |
| RL15 | 확대 상한(hr 5081 / hw 5106) | 복원 라운드와 빈 라운드는 세지 않음 |
| RL17 | `gdakiTsServeLower`(hr 5372–5373 / hw 5401–5402) | 새 메시지 미루기. 같은 상대의 미룬 메시지는 그 상대의 REQ보다 먼저, 도착 차례대로 처리(DESIGN_POLICY.md 3절 R1) |
| RL18 | 자료 서버(새 스레드, 새 포트) | 체크포인트 블록, 로그 내보내기 |
| RL19 | 통계 API(hr 7135 / hw 7454) | 복원 수 |
| RL20 | `gdakiTsRespond` 맨 앞(hr 5739 / hw 5768) | 그 상대의 미룬 RESTORED를 먼저 적용한 뒤, 붙잡은 상대의 REQ에 NACK 17, PUBLISHED면 fallback(DESIGN_POLICY.md 3절 Q5, R1) |

장치 쪽(DV1–DV4)과 예비 프로세스 쪽(SP1–SP6)은 아래 그대로다.

| id | 무엇을 |
|---|---|
| DV1 | `ncclGinGdakiGPUContext`(common.h 222–236)에 측 표 포인터 `restore` 칸: QP마다 로그 고리 설명, "로그 켬" 낱말(검토 3 W2), 보낸 메시지 수, 억제 예산. 포인터는 hold 정책이면 문맥을 만들 때부터 0이 아님(RL10) |
| DV2 | `putImplMode`(gin_gdaki.h 458–547), `putValueImplMode`(577–), 신호 길에서 게이트 안 로그 쓰기(9.5절). hold가 아니면 측 표 포인터가 0. 포인터가 0이 아니어도 그 QP의 "로그 켬" 낱말(게이트 안 strong 읽기)이 서 있을 때만 씀 |
| DV3 | 결정 (나)(2026-10-09, DESIGN_POLICY.md 5절 B4, 검토 3 반영): hold 정책의 communicator(측 표 포인터 ≠ 0)에서만 `tsGateEnter`가 참을 돌려준 뒤 키를 다시 읽음. `putImplMode`는 게이트(501) 뒤 보내기 갈림(509) 앞에서 `raddr.key`(`hasWins`일 때만)와 `sig_raddr.key`(키 주소가 null이 아닐 때만), `putValueImplMode`는 604 뒤, `getImplMode`는 704 뒤에 `raddr.key`. 읽기는 L1을 거치지 않는 시스템 범위 relaxed 32비트 읽기. `signalKey`는 지금처럼 호출자가 계산해 값으로 넘기고(1458–1468, 1483–1494), 호출자는 그 키를 읽은 주소(`signals_table.rkeys + peer` 또는 `signalMh->rkeys + peer`, 신호가 없으면 null)를 내부 인자 하나로 더 넘김. fail-fast는 키 읽기 자리와 종류가 지금과 같고 put에는 DV2와 같은 포인터의 분기 하나와 내부 인자 하나, get에는 포인터 읽기 하나와 분기 하나만 더해짐(검토 3 재확인 X3). 비용은 LT1, LT2와 7절의 비용 셀 |
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

### 9.15 실행 가능성 시험 B1, B2, B3 (DRAFT 단계, 채점하지 않음)

사용자 결정(2026-10-09)으로 막는 문제 B1–B3([DESIGN_POLICY.md](DESIGN_POLICY.md) 5절)이 풀릴 수 있는지 먼저 시험한다. 사전 등록하지 않고 채점하지 않는다.
판정 기준은 아래에 실행 전에 적었다. 시험 코드는 [feas/](feas/)에 두고(시험 프로그램, B1의 기록과 재생 hook, 실행기), 결과는
`results/<날짜>_feasibility/`에 두며 12절에 적는다. 복원 계층(9.9절)은 구현하지 않는다. 클러스터 실행은 모두 메인 세션이 `cluster_run.sh` 안에서 한다.
첫 설계(커밋 `daa63c69`)는 읽기 전용 에이전트 둘의 설계 검토를 받아 아래처럼 고쳤다(B3: T3-1–T3-12, B1: T1-1–T1-11, B2: T2-1–T2-4; 12절). 판정 기준은
그 반영으로 바뀌었고, 바뀐 기준도 실행 전에 고정한다.

#### 9.15.1 기존 장치와 병렬 작업과의 충돌 (세 시험 공통)

| 자원 | 이 시험 | 겹치는 것 | 처리 |
|---|---|---|---|
| 빌드 트리 | 세션 스크래치 `agent_restore/b1/`(hw 트리의 복사), `agent_restore/out/` | gpu-detect가 쓰고 다른 에이전트도 복사하는 `agent_gd/gin`(hw, libnccl `efc48ca1`, diff md5 `be0ea9ed`) | 그 트리는 읽기만 한다(장치 헤더와 PRM 헤더를 include로 읽음). 복사본에서만 고치고 빌드한다(nice 19, ionice idle, rain에서 컴파일만) |
| 노드의 파일 | 새 디렉터리 `~/rs-bundle/`(rain, sunny 둘 다) | `~/gi-bundle`, `~/gd-bundle`, `~/blind-bundle` | 건드리지 않는다. 배포는 대상 디렉터리가 두 노드에 없을 때만 하고, 배포 뒤 두 노드의 md5를 원본과 맞춘다. 기존 묶음의 md5가 배포 앞뒤로 같은지도 본다 |
| 라이브러리 | B1, B2: hw에 기록, 재생, 보고 hook만 더한 `rsx` libnccl(첫 빌드 `~/rs-bundle/rsx/`; 2026-10-09 검토 3차 뒤의 둘째 빌드 `rsx2`는 `~/rs-bundle/rsx2/`) | gpu-detect가 배포한 `~/gi-bundle/gin_ts2/hw` | 그 파일을 쓰지 않는다. `rsx`의 hook은 환경 변수가 없으면 닿지 않는다(보고만 켜는 `NCCL_GIN_RESTORE_REPORT=1`은 읽기만 함) |
| 클러스터 잠금 | hold마다 `cluster_run.sh`, 태그 `rs-<hold>` | gpu-detect의 실행, 다른 사용자의 작업 | 잠금이 줄 세운다. 메인 세션만 실행한다. B3에서 rain이 응답 쪽인 셀과 sunny가 응답 쪽인 셀은 다른 hold다 |
| TCP 포트 | 시험 프로그램의 랑데부만 29000–30999에서, 실행마다 두 노드에서 비어 있음을 보고 고른다(`../remaining/portpick.sh`). nonce가 맞지 않는 상대에게는 아무것도 보내지 않는다 | 같은 범위를 쓰는 다른 실험 | 고르기와 nonce. NCCL bootstrap과 helper는 지금처럼 임시 포트(`NCCL_GIN_TS_PORT`는 두지 않음: p–p+15가 이 범위와 겹칠 수 있음, T1-11) |
| NIC 펌웨어 명령 | QP, MR, CQ는 프로세스마다 시작 때 한 번 만든다. B3의 QUERY_QP는 PAUSED 뒤 지난 반복의 도달 시간 × 0.7에 처음, 그 뒤 시작 간격 50 µs 이상, 한 번에 하나, 반복당 200개, 셀당 20 000개 상한(넘으면 그 셀을 멈춤), QUERY_QP 하나가 50 ms를 넘으면 그 셀을 멈춤. rain의 QUERY_QP 평균은 약 71 µs다 `[측정: multirank 보관본 fwcmd_before-H1.txt]`. B1, B2의 NCCL 프로세스는 hw QP 감시를 돌린다: 기본 10 ms면 gated QP마다 초당 100번이라 4 rank, 문맥 12개(rank마다 QP 36개)에서 rank마다 초당 약 3 600번이다. 2026-10-09 B2 hold는 이 기본값으로 돌았고(rank의 helper가 사는 몇 초 동안, 새 mlx5 줄 0), 그 뒤의 B1, B2는 `NCCL_GIN_TS_QPWATCH_MS=100`(기록과 재생이 같게; 검토 3차 P3)이다 | rain의 새는 명령 slot, 같은 HCA를 쓰는 다른 사용자 | 만들고 지우기를 되풀이하지 않는다. hold마다 앞뒤로 rain mlx5_1의 명령 셈(debugfs, 읽기만)과 mlx5 커널 줄을 남기고, 명령 오류가 늘면 `STOP_mlx5` |
| GID와 traffic class | GIN과 같은 RoCE v2 IPv4 대응 GID(gin-remaining 실행기의 고르기), TC 0(`NCCL_IB_TC` 기본) | 남의 우선순위 class | GIN과 같게 둔다 |
| GPU | B3: 응답 쪽 GPU에 같은 노드의 다른 프로세스(같은 노드 셀의 보내는 쪽, 경합 셀의 hog). B1: 예비 프로세스는 기본 셀에서 원래 rank가 끝난 뒤에 돈다 | 다른 사용자의 GPU 작업 | hold 앞뒤로 두 노드의 `nvidia-smi` compute app을 적는다. 모든 프로세스는 자기 시간 상한이 있다 |
| iptables | 쓰지 않는다 | | |
| 프로세스 | 모두 `timeout -s KILL`로 묶는다. 끄는 일은 실행기가 기록한 자기 PID만. hog는 실행기가 만드는 stop 파일을 보고 스스로 끝난다 | 다른 사용자의 GPU, RDMA 작업(gds-kv, NVMe-oF, gdsio, mooncake, `prio-` 작업) | 이름으로 끄지 않는다(남은 프로세스는 정확한 이름으로 세기만) |
| 링크 | B3 셀마다 약 8 GB(window 약 2 MiB × 4 000반복, 셀당 1분 안). 2026-10-09 바꿈: 본 셀은 마지막 쓰기 4 MiB(window 약 5 MiB) × 3 400반복(본 3 200 + 탐침 200)이라 셀당 약 17 GB, 셀당 1분 안(9.15.3, 12절). `cluster_run.sh`는 시작 때만 링크가 한가한지 본다 | NVMe-oF, gdsio | 셀을 짧게 둔다 |
| gpu-detect의 고침(G1–G9, `lostAfterCommit`) | 기대지 않는다. B1은 hw `be0ea9ed` 위에서 한다 | 그 고침이 같은 파일(`gin_host_gdaki.cc`)을 바꿈 | B1의 hook은 시험용 복사본에만 있고 그 고침과 합치지 않는다. 계층을 만들 때 다시 맞춘다 |
| 관리망 주소 | B1의 기록 파일에는 commId(root 주소), bootstrap ring 정보(P2P, proxy listen 주소), GIN listen handle, helper 주소, QP 교환 정보의 GID가 든다(T1-10). 파일은 노드의 `/tmp`에 mode 0600으로 만들고 실행기가 trial 뒤 지운다(프로세스가 kill돼도). 보고 줄은 주소나 그 해시를 찍지 않고, trial마다 메모리에만 있는 열쇠(`NCCL_GIN_RESTORE_HKEY`, 파일에 적지 않음)로 만든 열쇠 해시만 찍는다. 모든 B1, B2 실행은 RAS를 끄고(`NCCL_RAS_ENABLE=0`) `NCCL_DEBUG=WARN`이다(INFO는 eno1 주소를 찍음). strace 출력은 노드에서 셈으로만 바꾸고 지운다 | 저장소와 Release에 주소가 들어가면 안 됨 | 결과 폴더에는 셈과 요약만 둔다 |

#### 9.15.2 B2: GPU를 나눠 쓰는 rank의 LSA 팀 크기

**기존 자료.** gin-multirank 본 실행 보관본(`multirank/results/20261009`, sha256 `3c22ffd4d260`)을 풀어 보았다: 4-rank 로그는 WARN 수준이고 시행별
kv에 LSA 값이 없다 `[측정: 보관본의 h1/mr4_none_n10_r1.log, .kv]`. NCCL은 `lsaSize`를 cross-clique 갈래에서만 찍고(`dev_runtime.cc` 140),
`ncclDevCommDump`(1373)는 부르는 곳이 주석이다(1742) `[소스]`. gin-remaining은 같은 driver(`gin_mr.cu`)와 같은 로그 수준이다. 그래서 기존 원자료로는 확인할
수 없다.

**소스 판단.** `computeLsaSize`(`dev_runtime.cc` 129–156)는 `NCCL_LSA_TEAM_SIZE`(기본 0)와, 같은 노드에 연달아 있는 rank 묶음 길이들의 최대공약수다
(노드는 `rankToNode`, `init.cc` 1558–1568). 예외(cross-clique, `init.cc` 1695)는 MNNVL일 때만이다. 번갈아 둔 배치(rain 0, 2, sunny 1, 3)는 1, 연달아 둔 배치
(rain 0, 1, sunny 2, 3)는 2다 `[소스, 추론]`. 예비 프로세스는 rank를 늘리지 않고 죽은 rank의 칸을 기록된 `rankToNode`로 재생하므로 생존 rank의 lsaSize는
바뀌지 않는다(T2-1). 이 판단을 실제 값으로 확인한다.

**확인.** B1의 시험 application [feas/rs_spike.cu](feas/rs_spike.cu)를 `rsx` libnccl로, 보고만 켜고(`NCCL_GIN_RESTORE_REPORT=1`, 기록과 재생 없음) 복원 셀과
같은 배치와 환경(4 rank, 번갈아, `NCCL_MULTI_RANK_GPU_ENABLE=1`, GIN 문맥 12개, FULL, `NCCL_NUM_RMA_CTX=0`, `NCCL_RAS_ENABLE=0`, `NCCL_LSA_TEAM_SIZE` 두지 않음,
노드마다의 `NCCL_IB_HCA`와 GID는 gin-remaining 실행기처럼)으로 띄운다. rank마다 kv에 devComm의 `lsaSize`, `lsaRank`(`dev_runtime.cc` 1510–1511), 보고 줄에
`nLsaTeams`, `nvlsSupport`, `runtimeConn`을 적고, 짧은 장애 없는 GIN 교환이 맞게 끝나는지 본다.
- `b2_inter`: 번갈아 둔 배치, 2회.
- `b2_consec`(대조, 선택): 연달아 둔 배치 1회. 환경 변수로는 lsaSize를 낮출 수만 있으므로 2 이상을 보는 유일한 길이고, 같은 GPU의 두 프로세스가 상대
  proxy를 거쳐 메모리를 가져오는 길도 지난다(T2-2). 실패하면 그 사실만 적고 판정에 쓰지 않는다.

**판정(실행 전 고정).**
- 해결 A: `b2_inter` 2회에서 네 rank 모두 `lsaSize = 1`, `nLsaTeams = 4`(T2-4), `nvlsSupport = 0`, `runtimeConn = 1`이고 GIN 교환이 맞음 → 복원 셀 배치에는
  LSA로 묶인 상대가 없다. 무장 규칙은 지킴 장치로 둔다(LSA 팀에 든 상대는 무장하지 않음). lsaSize 1이어도 다른 프로세스의 GPU 메모리를 매핑하는 길이 남으므로
  (T2-3: host에서 띄운 NCCL collective나 P2P는 runtime connect로 P2P/SHM 전송을 만들어 상대 버퍼를 proxy로 가져옴, `init.cc` 1827) 무장 조건에 더한다:
  `runtimeConn = 1`, `nvlsSupport = 0`, host RMA 꺼짐(B1 T1-1), 그리고 application 요구로 host에서 띄우는 NCCL 통신 없음(9.7절 6번). DESIGN_POLICY.md 2.3절.
- 해결 B: 어느 rank든 `lsaSize ≥ 2` → 5절 B2의 풀 조건대로 LSA 팀에 든 상대는 무장하지 않는다(그 상대의 죽음은 fail-fast). 복원 셀 배치를 다시 본다.
- 미결: 초기화나 devComm 생성이 실패해 값을 읽지 못함 → B2는 열린 채 둔다.

**결과(2026-10-09).** 해결 A: `b2_inter` 2회 모두 네 rank `lsaSize=1`, `nLsaTeams=4`, `nvlsSupport=0`, `runtimeConn=1`, GIN 교환 맞음 `[측정: `results/20261009_feasibility/b2/`, summ_feas.py로 다시 셈]`. 대조 `b2_consec`는 하지 않았다.

#### 9.15.3 B3: 체크포인트 drain 뒤 GPU 메모리에 쓰기가 보이는가

**질문.** 응답 쪽 QP의 rmsn(QUERY_QP)이 멈춤 때 상대가 보낸 메시지 수 M에 이른 뒤, 설계(9.4절 3단계, 검토로 정함)대로 NIC 루프백 READ 하나(다른 할당의 fence
낱말, strict 루프백 MR)를 끝내고 GPU 안에서 window를 copy engine으로 복사하면, 그 M개의 RDMA 쓰기가 모두 복사본에 들어 있는가. window MR이 relaxed
ordering(기본, `gdakiRegMr` 192)일 때와 strict일 때 따로.

**검토가 바꾼 것.** (1) 마지막 메시지가 신호 원자 연산이면 그 연산의 PCIe 읽기가 앞의 posted 쓰기를 앞지르지 못해 rmsn = M이 이미 drain을 뜻한다(T3-1) →
반복의 꼬리를 셋으로 나눔: `W`(쓰기만), `AW`(원자 연산 뒤 큰 쓰기가 마지막), `WA`(원자 연산이 마지막, 따로 셈). 채점하는 fence 반복은 `W`와 `AW`뿐.
(2) READ 대상은 window가 아니라 다른 할당(측 표를 흉내 낸 fence 낱말)이고(T3-2), 같은 할당 READ는 변형으로 따로 셈. (3) RO가 실제로 켜져 있는지의 증거를
적고(T3-3), 늦은 쓰기를 메시지 경계에서 보는 대조와 경계 덮기 규칙을 더하고(T3-4), `cuFlushGPUDirectRDMAWrites` 길을 함께 잼(T3-5). (4) 할당은 cuMem
(`gpuDirectRDMACapable`, GIN window와 같음), 보내는 쪽 원본은 GPU 메모리, 같은 노드 셀은 다른 프로세스가 같은 GPU에서 보냄(T3-6), GPU 경합 셀(T3-7).
(5) QUERY_QP 간격과 상한(T3-8), rmsn 24비트 비교의 단위 시험(T3-9), 노드마다 묶는 통계와 빠진 갈래(T3-10), 사본을 반복마다 독으로 채움, 첫 반복의 값,
신호 기대값, 무작위 차례, 시간 상한(T3-11), window 약 2 MiB(T3-12).

**시험 프로그램.** [feas/rs_drain_test.cu](feas/rs_drain_test.cu)(NCCL 없음, libibverbs, mlx5dv의 DEVX, CUDA driver).
- 응답 쪽(`resp`): window(약 2 MiB + 경계 4 KiB, cuMem, `gpuDirectRDMACapable`)를 dmabuf MR로 iova 0에 등록(`ro`: `IBV_ACCESS_RELAXED_ORDERING`을 더함,
  `so`: 더하지 않음; 둘 다 `REMOTE_ATOMIC` 포함, `gdakiRegMr`와 같음). 신호 낱말은 다른 cuMem 할당의 strict MR. 따로 된 protection domain의 루프백 RC QP 쌍과
  그 PD의 strict MR 둘: fence 낱말이 든 또 다른 cuMem 할당(측 표 흉내, 설계의 READ 대상)과 window 할당(같은 할당 READ 변형). QP 순서는 IBTA 기본
  (`NCCL_GIN_IB_OOO_ALL` 두지 않음).
- 보내는 쪽(`writer`): 원본은 자기 GPU의 cuMem 버퍼(dmabuf MR). 반복 i마다 응답 쪽의 GO(i)를 받은 뒤 커널로 원본에 무늬(8바이트 낱말 = (i+1) << 32 | 낱말
  번호)를 쓰고, 꼬리에 따라 31–33개의 RDMA WRITE(64 B–128 KiB 섞음, 큰 쓰기 1 MiB)와 원자 더하기 1을 차례로 doorbell 한 번에 내고, 완료를 기다리지 않고
  `PAUSED(i, M)`(M = 기준 rmsn부터 센 누적 요청 메시지 수, 원자 연산 포함)를 보낸다(9.4절 2단계의 차례). 자기 마지막 완료와 `DONE(i)`를 본 뒤에만 다음
  반복으로 간다.
- 길(16반복마다 고정 시드의 무작위 차례): `fence`(설계: rmsn = M → 다른 할당 READ → copy engine 복사 → 검사) `W` 4, `AW` 4, `WA` 1; `fence_same`(같은 할당
  READ) `W` 1, `AW` 1; `nofence`(READ 없음, 진단) `W` 1, `AW` 1; `cuflush`(rmsn = M → `cuFlushGPUDirectRDMAWrites(CURRENT_CTX, TO_OWNER)` → 복사) `W` 1;
  `early`(PAUSED 직후 rmsn 없이 복사, 대조) `W` 1; `boundary`(rmsn = M − 1을 본 순간 복사: 마지막 큰 쓰기가 실행 중, 대조) `W` 1.
  모든 길은 끝에 rmsn = M과 READ를 마친 뒤 `DONE(i)`를 보낸다.
- 검사: 사본은 반복마다 먼저 독(모든 비트 1)으로 채운다. 복사 뒤 GPU 커널이 사본에서 이번 반복에 쓴 모든 낱말을 보고, 앞 반복의 값("늦음")과 그 밖("깨짐")을
  나눠 센다. 첫 반복 전 window는 "반복 0"의 무늬로 채운다. 신호 기대값은 기준값 + 이번 반복까지의 원자 연산 수(늦음 = 하나 모자람). 실패는 반복 단위로 센다.
  `fence`에서는 window를 SM으로 직접 읽는 검사도 함께 한다(정보).
- 순서 탐침(정보, 반복 루프 뒤 반복 수의 1/16): 응답 쪽 커널이 window의 마지막 낱말이 이번 값이 될 때까지 돌다가 바로 나머지 낱말을 본다. 앞 낱말이
  늦으면 GPU가 NIC 쓰기를 차례 밖으로 볼 수 있다는 뜻이다(RO가 실제로 효과가 있는지의 진단).
- 함께 적는 것: `CU_DEVICE_ATTRIBUTE_GPU_DIRECT_RDMA_WRITES_ORDERING`, `..._FLUSH_WRITES_OPTIONS`, `..._GPU_DIRECT_RDMA_SUPPORTED`, HCA 능력
  `relaxed_ordering_write`(QUERY_HCA_CAP), 두 노드의 `nvidia-smi topo -m`(실행기), MTU, GID 번호, TC, QUERY_QP 지연 분포(p50, p99, 최대), 반복마다 PAUSED에서
  rmsn = M까지의 시간과 QUERY_QP 수, M에 이르기 전에 rmsn < M을 한 번 이상 본 반복의 비율. PCIe 장치 제어의 RO 허용 비트는 root가 아니면 못 읽어 `[미확인]`이고,
  관리자가 읽기 전용 `lspci -vvv` 한 번을 해 주면 풀린다.
- 코드 검토(실행 전)로 고친 것: `early`의 반복 수를 반복 단위로 셈(C1), 경로 MTU는 두 쪽의 작은 값(C2), 도달 시간은 M을 본 QUERY_QP의 시작 시각으로 재어
  첫 질의가 경계로 다가가게 함(C3), 반복당 QUERY_QP 상한 200(9.15.1과 맞춤, C4), FENCE_FAIL이 INCOMPLETE에 가려지지 않음(C5), 셀마다 멈춤 검사와 hold 시간
  보호(C6, C7). 마지막 쓰기 크기는 `RS_LAST_KB`(기본 1 024)로 바꿀 수 있고, smoke에서 경계 덮기가 50% 아래면 그 값을 키워 12절에 적은 뒤에만 본 셀을 한다.
- smoke 뒤의 바꿈(2026-10-09, 본 셀 전, 판정 기준은 그대로): 기본값(마지막 쓰기 1 MiB)의 rain smoke는 `boundary` 12반복에서 마지막 메시지의 늦은 낱말이
  한 번도 보이지 않아(경계 덮기 0.692와 `early` 13/13은 채움) 미결이었다. 마지막 쓰기가 짧으면 rmsn = M − 1을 보는 순간에 그 쓰기가 이미 끝나 있기
  때문이다 `[추론]`. 그래서 `RS_LAST_KB=4096`으로 smoke 둘을 다시 했고 둘 다 유효했다(12절). 본 셀(B3r, B3s, 다시 하는 셀)은 `RS_LAST_KB=4096`을 실행기가
  명시해 셀마다 meta에 남긴다. 4 MiB에서 rain은 반복당 QUERY_QP 약 4.9번이라(smoke 221반복에 1 091번) 4 000반복이면 셀당 상한 20 000에 닿는다. 상한은
  그대로 두고 반복 수를 셀당 3 200으로 줄인다(QUERY_QP 예상 rain 약 16 800, sunny 약 12 000). 그래서 채점하는 `fence` 반복은 셀마다 1 600, 노드와 순서마다
  4 800이고 실패율 95% 상한은 약 0.0625%(3/4 800)다(아래 판정의 2 000, 6 000, 약 0.05%를 이 수로 바꿔 읽는다. 통과의 조건, 실패 0은 같다).
- 경합 셀의 바꿈(2026-10-09, `b3_h_rain_ro`를 다시 한 뒤, 판정 기준은 그대로): GPU 경합 셀은 3 200반복을 다 하기 전에 셀당 QUERY_QP 상한 20 000에 닿았다(12절).
  상한은 rain의 새는 명령 slot 때문에 그대로 둔다. 경합 셀(`b3_h_*`)만 `RS_QUERY_BUDGET=19000`으로 돌린다: 반복을 시작할 때마다 QUERY_QP 수를 보고 19 000 이상이면
  그 자리(반복 경계)에서 고리를 마치고 한 반복까지의 결과로 판정한다(멈추는 때는 질의 수로만 정해지고 결과와 무관하다). 이 끝(`budget_stop=1`)은
  정상 끝이라 STOP 파일을 쓰지 않는다(결과가 `INCONCLUSIVE`여도 실행기는 다음 셀로 간다). 상한까지 남는 1 000은 한 반복이 낼 수 있는 최대 400(질의 고리
  둘 × 200)보다 크다. 그래서 경합 셀의 채점 fence 반복 수는 미리 정해지지 않는다(최대 1 600). 노드와 순서마다의 묶음은 `x`, `s`의 3 200과 `h`가 실제로 한 수의
  합이고, 실패율 95% 상한은 3/(3 200 + `h`의 수)로 0.0625%(`h`가 1 600)에서 약 0.094%(`h`가 0에 가까움) 사이다. `h` 셀의 유효 조건(early와 boundary가 각 10반복
  이상, 경계 덮기 50% 이상)은 그대로라 반복이 너무 적으면 그 셀은 미결이다. `x`, `s` 셀은 3 200반복 그대로다(예산은 빈 값으로 넘겨 꺼짐). 순서 탐침은
  본 반복 3 200 뒤에 하므로 예산으로 끝난 경합 셀에는 탐침 자료가 거의 없거나 없다: 경합에서 GPU가 NIC 쓰기를 차례 밖으로 보는지의 진단이 빠진다(탐침은
  정보 항목이라 판정과 무관, 다시 검토 U8).
- 셀(각 4 000반복, 위의 바꿈으로 본 셀은 3 200반복; 응답 쪽 노드마다 hold 하나):
  - `b3_x_<rain|sunny>_<ro|so>`: 노드 사이(이름의 노드가 응답 쪽).
  - `b3_s_<rain|sunny>_<ro|so>`: 같은 노드(보내는 프로세스가 같은 GPU, 같은 HCA; GIN의 노드 안 쌍).
  - `b3_h_<rain|sunny>_<ro|so>`: 노드 사이 + 응답 쪽 GPU에서 다른 프로세스가 메모리 대역 커널을 계속 돌림(경합).
  - 먼저 smoke 둘(`b3_x_rain_ro`, `b3_x_sunny_ro` 각 208반복, 판정에 쓰지 않음; sunny가 응답 쪽일 때 제어 포트를 여는 것도 봄, C17). 본 셀은 smoke에서
    설정 오류가 없고 경계 덮기, `early`, `boundary`, QUERY_QP 수가 판정 기준을 채울 만할 때만 한다.

**판정(실행 전 고정).**
- 셀이 유효: 설정 오류, CQE 오류, QUERY_QP 상한 초과가 없고, 모든 반복에서 rmsn이 2 s 안에 M에 이르렀고, 다음이 모두 참이다. `early` 반복 가운데 10반복
  이상에서 늦은 낱말이 있고 깨진 낱말은 0; `boundary` 반복 가운데 10반복 이상에서 마지막 메시지에 늦은 낱말이 있음; 채점하는 `fence` 반복의 50% 이상이
  M에 이르기 전에 rmsn < M을 한 번 이상 봄(경계 덮기). 하나라도 아니면 그 셀은 미결이다.
- 셀이 통과: 채점하는 `fence` 반복(`W`, `AW`; 셀마다 2 000)에서 늦은 낱말, 깨진 낱말, 신호 틀림이 있는 반복이 0.
- 순서 하나(`ro` 또는 `so`)가 노드 하나에서 통과: 그 노드가 응답 쪽인 그 순서의 셀 셋(`x`, `s`, `h`)이 모두 유효하고 통과. 이때 노드마다 6 000반복이고 실패율
  95% 상한은 약 0.05%(3/6 000)다. 노드끼리는 묶지 않는다(Turing과 Ampere, 다른 PCIe 길).
- B3의 결론(노드마다, 그리고 두 노드를 함께):
  - 두 노드에서 `ro`와 `so` 모두 통과 → 이 플랫폼, 이 설정에서 READ 하나로 drain 확인이 맞다. strict 조건(2.3절)을 뺄지는 사용자 결정으로 둔다(RO가 실제로
    켜졌는지는 위의 증거와 순서 탐침으로 적고, 다른 하드웨어는 `[미확인]`).
  - `ro` 실패, `so` 통과 → 무장 조건 "window는 strict"를 확정하고 그 조건으로 B3을 푼다.
  - `ro` 통과, `so` 실패, 또는 노드마다 결과가 다름 → 흔들리는 결과로 보고 B3은 열린 채 둔다.
  - `so`도 실패 → B3은 열린 채 둔다. `cuflush` 결과가 깨끗하면 대안으로 사용자에게 올린다.
  - 미결 셀은 그 셀만 다시 하고, 다시 해도 미결이면 사용자에게 올린다.
- 진단(판정에 쓰지 않음): `fence_same`, `nofence`, `WA` 꼬리, `cuflush`, SM 직접 검사, 순서 탐침. 이 시험의 힘은 QUERY_QP 지연(수십 µs)만큼의 창에 한정된다는
  것도 결과와 함께 적는다. 나중에 rmsn을 더 빨리 보는 설계(멈춤 없는 v2 체크포인트 등)로 바꾸면 B3을 다시 해야 한다(T3-4).

**결과(2026-10-09, 열림: 사용자 결정 대기).** `[측정: results/20261009_feasibility/b3/, b3_rerun1/–b3_rerun3/; summ_feas.py로 다시 셈, 12절]`
- 통과(채점 fence 실패 0/1 600, `early`와 `boundary` 대조 200/200): rain의 노드 사이와 같은 노드 셀 넷(`ro`, `so`, 첫 빌드), sunny의 노드 사이와 같은 노드
  셀 넷(`b3v3`).
- sunny의 GPU 경합 셀: `ro`는 통과(0/1 600, `early` 22/200, `boundary` 13/200). `so`는 첫 실행이 `boundary` 7/200으로 미결이었고 다시 한 실행이 통과했다
  (0/1 600, `early` 19, `boundary` 10). 그래서 sunny는 `ro`, `so` 모두 통과다(노드와 순서마다 채점 4 800, 실패율 95% 상한 0.0625%).
- rain의 GPU 경합 셀: `ro`, `so`를 각각 두 번 했다(`b3v3`, 질의 예산 19 000으로 3 046–3 058반복에서 끝남). 네 실행 모두 채점 fence 실패 0이다(실행마다
  1 524–1 529, 합 `ro` 3 051, `so` 3 056). 그러나 `early`(실행마다 191반복)와 `boundary`(190–191반복)에서 늦은 낱말이 한 번도 없어 네 실행 모두 미결이다.
  규칙(미결 셀은 한 번 다시 하고, 다시 해도 미결이면 사용자에게 올림)에 따라 rain의 `ro`, `so`는 열림이고 B3의 결론은 "열림"이다. 다음 단계는 사용자 결정을
  기다린다.
- 본 셀 폴더의 모든 실행을 합치면(smoke 제외, 유효 여부와 무관, 실행과 셀이 섞인 합이라 판정 규칙의 묶음이 아님) 채점 fence 23 707반복에서 실패 0이다.
  오류로 끝나 셈이 없는 실행 둘(첫 빌드의 설정 자체 시험, `b3v2`의 상한 멈춤)은 따로 센다.
- 진단: 모든 셀에서 `nofence`(READ 없이 rmsn = M 뒤 바로 복사)도 실패 0이다(셀마다 190–200반복). 그래서 이 시험은 "rmsn = M을 본 뒤 복사에는 쓰기가
  보인다"까지 보이고, 그것이 READ 덕분인지는 가르지 못한다(QUERY_QP 지연 수십 µs의 창 안에서). 두 노드 모두 `GPU_DIRECT_RDMA_WRITES_ORDERING` 0,
  `FLUSH_WRITES_OPTIONS` 1, HCA `relaxed_ordering_write` 1이다.
- rain 경합 셀의 대조가 0인 까닭 `[추론]`: 경합에서 반복 하나가 rain 1.17 → 8.1 ms, sunny 1.04 → 7.5 ms로 늘었는데, NIC 쪽(PAUSED에서 rmsn = M까지) p50은
  rain 795 → 1 076 µs, sunny 647 → 918 µs로만 늘었다 `[측정]`. 응답 쪽과 hog는 다른 프로세스라(MPS 없음) GPU를 시간 나눔으로 쓰고, hog는 약 1.7 ms(rain),
  1.5 ms(sunny)짜리 복사 커널을 잇달아 낸다(hog kv의 round 수와 시간에서 셈). 그래서 응답 쪽의 복사가 PAUSED나 rmsn = M − 1을 본 뒤 한참 늦게 시작하고,
  rain에서는 그 늦음이 남은 쓰기 시간(1 ms 안팎)보다 늘 길어 복사가 모든 쓰기 뒤에 읽는 것으로 본다. 경합 셀에서는 sunny도 앞 메시지의 늦은 낱말이
  0반복이라(경합 없는 셀은 200/200) 복사가 쓰기를 앞지르지 못한다는 것과 맞다. 같은 늦음이 `fence` 반복의 틈도 가리므로 rain 경합 셀의 fence 실패 0은
  힘이 거의 없고, sunny 경합 셀도 대조가 약 10%만 잡혀 힘이 그만큼 작다. 복사가 실제로 얼마나 늦는지(복사 시작 시각을 잰 적 없음), D2D 복사가 copy
  engine과 SM 가운데 어디서 도는지, 두 GPU(Turing Quadro RTX 5000, Ampere RTX A4000)가 왜 다른지는 `[미확인]`이다.

**2026-10-11 사용자 결정: 경합 셀 넷만 제대로 다시 확인.** 사용자: "4셀만 제대로 확인 후 다시 결정해보자". 경합 셀 넷(rain과 sunny, `ro`와 `so`)만 다시
확인하고 그 뒤 사용자가 B3을 다시 정한다. 그때까지 B3은 "열림, 사용자 결정 대기"이고 무장 조건 "window는 strict"([DESIGN_POLICY.md](DESIGN_POLICY.md) 2.3절)는
그대로다. 노드 사이 셀과 같은 노드 셀(`x`, `s`)은 다시 하지 않는다. 판정 기준(채점 fence 실패 0; `early` 10반복 이상, `boundary` 10반복 이상, 경계 덮기 50%
이상; 질의 예산 19 000, 상한 20 000)은 그대로다. 아래는 그 확인의 설계다(빌드 전에 적고 충돌 표와 독립 검토를 먼저 함).
- 옛 경합 셀(`b3_h_*`, 다른 프로세스의 hog): 실행과 원자료는 그대로 두고 "다른 프로세스 hog, rain에서 대조의 힘 없음"으로 적는다. 노드와 순서마다의 묶음에서는
  뺀다(summ_feas가 따로 보임).
- 진단(판정 없음, 폴더 `b3_diag/`): 응답 쪽이 사본 복사의 바로 앞과 뒤에 CUDA event를 넣고, 호스트가 뒤 event의 끝을 본 시각에서 두 event 사이의 GPU 시간을
  빼서 복사가 GPU에서 시작한 때를 어림한다. 복사 앞에 시각을 찍는 커널을 넣지 않는다(커널은 그 자체가 시간 나눔을 기다려 재려는 것을 바꿈). 이 값을 PAUSED를
  받은 때, rmsn = M − 1을 본 때(`boundary`), rmsn = M을 본 때(그 밖의 길)와 견주어 반복마다 CSV(`<cell>_resp_timing.csv`)에 적는다. 셀은 노드마다 셋, `ro`만,
  각 320반복(`early`, `boundary` 각 20, 채점 fence 160, 뒤에 탐침 20), `RS_LAST_KB=4096`, 예산 19 000(셀마다 QUERY_QP 약 2 400 예상): `b3_dn_<node>_ro` hog
  없음, `b3_dp_<node>_ro` 옛 경합 셀과 같은 다른 프로세스의 hog, `b3_dm_<node>_ro` 아래 새 경합 셀과 같은 프로세스 안의 hog.
- 진단의 읽기(실행 전 고정, 노드마다, B3 판정에는 쓰지 않음): `dp`에서 `early` 복사 시작(PAUSED 뒤) p50이 같은 실행의 rmsn = M까지 p50보다 길고, `dn`에서
  그 p90이 `dn`의 rmsn = M까지 p50의 1/4보다 짧으면 시간 나눔 추론은 "맞음"이다. `dp`에서 그 p50이 `dp`의 rmsn = M까지 p50의 1/4보다 짧으면 "틀림"(복사는
  제때인데 대조가 0이니 다른 까닭)이고, 그 밖은 "불분명"이다.
- 새 경합 셀 `b3_m_<rain|sunny>_<ro|so>`(옛 `b3_h_*`를 대신함): 노드 사이(이름의 노드가 응답 쪽)이고, 응답 프로세스 안에서 가장 낮은 우선순위의 stream 하나가
  첫 반복 전부터 마지막 반복 뒤까지 메모리 대역 복사 커널을 쉬지 않고 낸다(block마다 64 KiB를 복사하고 끝나는 짧은 block, 256 MiB 두 버퍼 사이를 오감, round마다
  커널 8개). 사본 복사와 검사, 탐침의 stream은 가장 높은 우선순위다. 같은 CUDA 문맥이라 시간 나눔이 없고, block이 짧아 높은 우선순위 커널이 수십 µs 안에
  SM을 얻는다 `[추론: 진단의 dm으로 확인]`. 3 200반복, `RS_LAST_KB=4096`, 예산 19 000, 상한 20 000. 판정 기준은 위와 같고 묶음에서 `h` 자리에 `m`이 들어간다
  (노드와 순서 하나는 `x`, `s`, `m`이 모두 유효하고 통과일 때 통과; 실패율 95% 상한 3/(3 200 + `m`의 채점 수)).
- 새 셀이 대표하는 경합: 응답 쪽 GPU의 메모리 대역을 같은 프로세스의 다른 커널(같은 application의 다른 stream 작업 등)이 채우는 동안 NIC 쓰기가 들어오고,
  체크포인트의 복사는 제때 시작하는 경우다. 메모리가 바쁠 때 rmsn = M 뒤에도 쓰기가 늦게 보이는 틈이 있다면 드러날 수 있는 경우이고, 대조가 힘을 가지므로
  B3의 물음(rmsn = M과 READ 하나 뒤 복사에 모든 쓰기가 보이는가)에 경합 아래에서 답한다. 다른 프로세스가 GPU를 시간 나눔으로 쓰는 경우(GPU를 나눠 쓰는
  rank 등)는 대표하지 않는다. 그 경우는 복사가 늦어져 rmsn = M과 복사 사이가 넓어지는 쪽이고, 옛 셀의 자료(실패 0, 대조의 힘 없음)만 있다.
- 실행 차례와 관문(실행 전 고정): 배포 → 진단 hold 하나 → 노드마다 관문 → 새 경합 셀(셀마다 hold 하나, `b3m_run<k>/`). 관문: 그 노드의 `dm`에서 `early`의
  늦은 낱말이 10반복 이상이면서 `early` 반복의 50% 이상, `boundary`의 마지막 메시지 늦은 낱말도 같은 조건, `dm`의 hog 대역이 `dp`의 hog 대역의 50% 이상.
  관문을 넘지 못한 노드의 새 셀은 하지 않고 사용자에게 올린다.
- 새 셀이 다시 미결이면 그 셀만 한 번 다시 하고(`b3m_run2/` 등), 그래도 미결이면 사용자에게 올린다. 그 뒤의 재설계나 실행은 사용자 결정 뒤에만 한다.
  `FENCE_FAIL`은 다시 하지 않고 결과로 올린다. 오류 멈춤은 9.15.5의 STOP 규칙을 따른다.
- 바이너리 `b3v4`(새 디렉터리 `~/rs-bundle/b3v4/`): 위의 event 시각과 CSV를 모든 셀에서 적고(채점 고리의 차례와 판정은 그대로, 사본 복사 앞뒤의 event 둘과
  호스트의 완료 확인만 더함), `RS_HOG=stream`이면 프로세스 안 hog를 돌리고, 사본과 탐침의 stream을 가장 높은 우선순위로 만든다. `x`, `s` 셀은 `b3v4`로 다시 하지
  않는다(그 결과는 첫 빌드와 `b3v3`의 것).

충돌 표(2026-10-11 바꿈, 9.15.1에 더함):

| 자원 | 이 바꿈 | 겹치는 것 | 처리 |
|---|---|---|---|
| GPU 메모리와 SM | 진단 `dm`과 새 셀: 응답 프로세스 안의 hog 버퍼 512 MiB와 복사 커널. 진단 `dp`: 옛 hog 프로세스(같은 크기) | 다른 사용자의 GPU 작업 | 옛 경합 셀과 같은 크기. hold 앞뒤로 두 노드의 compute app을 적음. hog 스레드는 고리가 끝나면 멈추고, 프로세스는 `timeout`과 watchdog으로 묶임 |
| NIC 펌웨어 명령 | 진단 셀마다 QUERY_QP 약 2 400, 새 셀마다 19 400 이하(예산 19 000, 상한 20 000 그대로). rain이 응답 쪽인 것은 진단 셋과 새 셀 둘, 합 약 46 000(다시 하면 셀마다 19 400까지 더함) | rain의 새는 명령 slot | 셀마다 상한, hold 앞뒤로 rain debugfs 셈을 적음, 9.15.5의 STOP 규칙 |
| 링크 | 진단 셀마다 약 1.7 GB, 새 셀마다 약 17 GB(옛 경합 셀과 같음) | 다른 사용자의 RDMA 작업 | `cluster_run.sh`가 링크가 한가할 때 시작 |
| 노드의 파일 | 새 `~/rs-bundle/b3v4/`. 응답 쪽 CSV는 rain에서 실행기의 작업 디렉터리, sunny에서 `/tmp/rs_b3_*`(실행기와 hold의 자기 파일 지우기 대상) | `~/rs-bundle`의 다른 파일, 다른 묶음 | 배포는 새 디렉터리만, 앞뒤 md5 |
| 결과 폴더 | 새 `b3_diag/`, `b3m_run<k>/` | 옛 `b3/`, `b3_rerun<k>/` | 옛 것을 덮지 않음. summ_feas는 진단을 판정에서 빼고, 묶음은 `x`, `s`, `m`의 마지막 실행 |
| 판정 규칙 | 그대로(셀 이름만 `h` → `m`) | 9.15.3의 판정 | 사용자 결정으로 12절에 적음 |
| 프로세스 | 프로세스 안 hog는 스레드라 끄는 일이 없음(고리 끝의 멈춤 표시) | 다른 사용자의 프로세스 | 이름으로 끄지 않음. 남은 프로세스 검사는 그대로(`rs_drain_test`) |
| 라이브러리와 다른 실험 | NCCL을 쓰지 않음 | gpu-detect, 다른 에이전트의 트리 | 겹침 없음 |

#### 9.15.4 B1: 예비 프로세스의 초기화 재생 spike

**질문.** 장애 없는 2-rank 실행에서 한 rank의 초기화 기록을 남기면, 같은 노드의 예비 프로세스가 다른 rank의 참여 없이 그 기록만으로 초기화를 끝내고
같은 rank, nRanks, GIN 문맥 수, 신호 수, window 크기, 모든 상대에 대한 게이트 상태(`gated`, `addr`, 장치 게이트 구조)를 얻는가(DESIGN_POLICY.md A3, C3, V13).
장애 주입과 복원 라운드는 없다. 답은 lsaSize 1인 배치에만 해당한다(lsaSize 2 이상이면 메모리 handle의 파일 기술자를 상대 proxy에서 받아야 해 기록할 수 없음,
`dev_runtime.cc` 322–328; T1-4).

**전제(검토 T1-1, T1-4).** host RMA proxy는 기본으로 켜져(`numRmaCtx` 기본 1, `init.cc` 2798; `ncclRmaProxyEnabled` `rma/rma.cc` 19–21) 첫 window 등록에서
모든 상대에게 hook 밖의 IB 연결을 맺는다(`ncclRmaProxyConnectOnce` → `ncclRmaIbProxyCreateContext`, `transport/net_ib/gin.cc` 545–556) `[소스]`. 그래서 B1의
모든 실행은 `NCCL_NUM_RMA_CTX=0`, `NCCL_RMA_DISABLE=1`이고, 재생 hook은 `numRmaCtx ≠ 0`, `NCCL_OOB_NET_ENABLE=1`, RAS 켜짐 가운데 하나라도 있으면 재생을
거절한다. 이것은 복원의 무장 조건이기도 하다(DESIGN_POLICY.md 2.3절, A3).

**hook**(`rsx` 빌드 = hw 트리의 복사 + [feas/rs_spike.diff](feas/rs_spike.diff), 모두 환경 변수가 있을 때만 닿음).
- `NCCL_GIN_RESTORE_RECORD=<파일>`(기록): 이 프로세스의 첫 communicator가 초기화, window 등록, devComm 생성 동안 받은 모든 집합 교환의 결과를 차례로 적는다.
  대상: commId(`ncclCommInitRankFunc`), bootstrap의 공개 함수 전부(`bootstrapAllGather`, `bootstrapIntraNodeAllGather`, `bootstrapBarrier`,
  `bootstrapIntraNodeBarrier`, `bootstrapSend`, `bootstrapRecv`, `bootstrapBroadcast`, `bootstrapIntraNodeBroadcast`; 안에서 부르는 것은 다시 적지 않음.
  참여 rank가 하나인 노드 안 호출은 네트워크가 없어 적지 않음), GIN collComm의 all-gather(`ncclGinIbAllGather` 맨 앞에서; all-to-all과 P2P barrier도 이것을
  거침). 항목마다 부른 자리 표시(peerInfo `init.cc` 1254, allGather3 1549, GIN 연결 수 `gin_host.cc` 195, window 조각 정보 `dev_runtime.cc` 756, 그 밖)를 단다.
  window 등록 끝과 devComm 생성 끝에 표시 항목을 넣는다.
- `NCCL_GIN_RESTORE_REPLAY=<파일>`(재생, 예비 프로세스): commId를 `getHash`와 magic 전에 기록의 것으로 바꾸고 rank, nRanks가 맞는지 보고, bootstrap의 root
  연락과 ring 연결을 건너뛰고(ring 소켓은 초기화만), 위의 모든 호출을 기록의 다음 항목으로 대답한다(종류, 자리 표시, 태그, 상대, 크기, 참여 rank 수가 다르면
  그 자리에서 실패). 기록이 끝난 뒤의 bootstrap 호출은 소켓을 건드리지 않고 오류를 돌려준다. 자기 칸은 새 값으로 두되, 자리별 가면으로 비교한다: peerInfo는
  `pidHash`와 `comm` 말고는 같아야 하고, allGather3, GIN 연결 수, window 조각 정보는 바이트까지 같아야 한다(T1-6). 그 밖의 항목은 다른 바이트 수만 적는다.
  GIN collComm의 ring 연결은 `ncclGinIbConnect`의 connect와 accept 고리(246–255)만 건너뛰고 필드 설정(257–264)은 그대로 둔다(T1-3). helper 설정
  (`gdakiTsSetup`)은 salt를 기록의 자기 값으로 써서 nonce를 처음과 같게 하고, 잇거나 받지 않고 `gated`, `addr`를 기록의 all-gather 결과로 세운다.
  `gdakiTsStart`는 게이트 설정까지 하고 helper 스레드를 띄우지 않는다(설치 전에는 아무에게도 말하지 않는 예비 프로세스, DESIGN_POLICY.md D4). 상대에 이어진
  QP는 만들기만 하고 잇지 않고(9.3절과 같음), 게이트 보고 줄 바로 뒤에 기록의 상대 QPN과 GID(`rq.exch`)로 새 무작위 PSN을 써서 한 번 잇고, 그때 응답 쪽
  MSN 기준(rmsn0)을 잡는다(`gdakiTsSetup`에서는 RESET인 QP에 QUERY_QP를 내지 않음; 검토 3차 P2, P7). 로컬 상태만 바뀌고 패킷은 없다(RTR이 이웃 탐색 ARP만
  부를 수 있음, T1-5). 재생은 ring 연결을 하지 않으므로 그 연결이 하던 장치 protection domain의 참조를 직접 잡고(처음이면 할당, `ncclIbInitCommDevBase`와
  같음) collComm을 닫을 때 놓는다. 없으면 WARN과 함께 실패한다(검토 3차 P1: 첫 빌드는 이것이 빠져 GDAKI의 첫 MR 등록에서 멈췄을 것).
- `NCCL_GIN_RESTORE_REPORT=1`(또는 위 둘): `GIN/RS:` 보고 줄. communicator의 `runtimeConn`, `nvlsSupport`, `numRmaCtx`, lsaSize, `nLsaTeams`; window마다
  (내부 window 포함) 크기, `winFlags`, 그 밖의 등록 정보; GPU에서 다시 읽은 window rkey 표와 신호, 카운터 표의 상대 칸(열쇠 해시); GIN 문맥마다 상대별
  `gated`, `addr`(열쇠 해시), QP마다 `rq.exch`(열쇠 해시), 장치 게이트 구조 전체(flags, waitMs, rescue 유무)와 게이트 낱말; helper nonce(열쇠 해시);
  `ncclDevCommDump`(주석을 풀어 이 env에서만 부름) 출력. 주소는 찍지 않는다.

**시험 application.** [feas/rs_spike.cu](feas/rs_spike.cu): 보통 모드는 `gin_mr.cu`와 같은 nonce 랑데부와 초기화(`ncclCommInitRankConfig`, `ncclMemAlloc`과
`ncclCommWindowRegister` 둘, GIN 문맥 N(N−1)개, 신호 1, FULL), 짧은 장애 없는 교환(모든 간선 put + 신호 20회, 자료 검사), 보고, `ncclCommAbort`. 예비 모드
(`RS_SPARE=1`)는 랑데부도 `ncclGetUniqueId`도 하지 않고(T1-6) 같은 초기화, 보고, `ncclCommAbort`만 한다(커널 없음). kv: rank, nranks, devComm의 rank, nRanks,
lsaRank, lsaSize, ginContextCount, ginSignalCount, ginCounterCount, ginConnectionCount, window 크기, `ncclGinGetRecoveryStats`의 문맥 수, 각 API의 결과와 시간,
`ncclCommAbort`의 결과와 시간.

**밖에서 보는 네트워크 확인(T1-2).** 예비 프로세스는 `strace --seccomp-bpf -f -e trace=socket,connect,accept,accept4`로 띄우고(그 노드의 strace가
`--seccomp-bpf`를 못 하면 그것 없이; 추적하는 호출만 멈추게 해 초기화가 느려지지 않게, 코드 검토 C8), 실행기가 노드에서 그 출력을 셈으로만 바꾼다: 상대로의
connect 수(루프백도 그 노드 자신의 주소도 아닌 AF_INET, AF_INET6; 스트림과 데이터그램 따로), 자기 주소, 루프백, AF_UNIX connect 수, accept 수, socket 수와
해석한 줄 수(해석기의 양성 대조, C9). 원문은 지운다. sunny에 strace가 없으면 `b1_rep1`의 이 항목은 `[미확인]`이다(실행기가 적음).

**셀.**
- `b1_rec`: rain rank 0, sunny rank 1. 두 rank 모두 기록을 남기고 끝난다(장애 없음, 교환 맞음).
- `b1_rep1`: 이어서 sunny에서 rank 1의 기록으로 예비 프로세스 하나(상대는 이미 끝나 있음).
- `b1_rep0`: rain에서 rank 0의 기록으로 같은 것(bootstrap root였던 rank).
- `b1_neg`(음성 대조, T1-8): rank 1의 기록을 반으로 자른 사본과, 항목 하나의 크기 칸을 바꾼 사본으로 재생 두 번. 둘 다 재생이 실패해야 한다.
- 위 넷을 2회. 그다음 선택으로 `b1_live`(위가 통과했을 때만, 같은 hold 안): 2-rank 실행이 교환 뒤 30 s 쉬는 동안 sunny에서 rank 1의 기록을 재생. 살아 있는
  rank의 로그와 복구 통계에 변화(라운드, 거절, 재연결, 모르는 연결)가 없어야 한다. 여기서는 예비 프로세스와 살아 있는 rank 1이 같은 노드라 상대로의 connect가
  "자기 주소"로 셀 수 있으므로, 자기 주소 connect 수가 순차 재생(`b1_rep1`)의 수를 넘으면 3번 실패로 본다(코드 재검토 N5, 실행 전).

**판정(실행 전 고정).** 재생 실행 하나가 통과하려면 다음이 모두 참이다.
1. 예비 프로세스가 `ncclCommInitRankConfig`, window 등록 둘, `ncclDevCommCreate`를 ncclSuccess로 끝내고, `ncclCommAbort`가 ncclSuccess를 10 s 안에 돌려주고,
   프로세스가 `timeout`이 아니라 스스로 끝난다(재생 전체 60 s 상한).
2. 기록을 정확히 소비한다: devComm 생성 끝 표시까지의 모든 항목을 차례로 썼고 어긋남 0, 자리별 가면 비교의 다름 0.
3. 상대와 말하지 않았다: strace 셈에서 루프백도 이 노드 자신의 주소도 아닌 AF_INET, AF_INET6 connect 0(자기 주소로의 connect는 따로 셈), strace 해석이
   socket 호출을 하나 이상 셌음(해석기의 양성 대조), 그리고 hook의 셈에서 기록 밖 bootstrap 호출 0.
4. 같은 rank의 기록 실행과 같다: rank, nRanks, devComm의 rank, nRanks, lsaRank, lsaSize, ginContextCount, ginSignalCount, ginCounterCount, ginConnectionCount,
   window 크기와 등록 정보(내부 window 포함), `runtimeConn = 1`, `nvlsSupport = 0`, `numRmaCtx = 0`, 투명 복구 문맥 수, helper nonce, GPU에서 다시 읽은 상대
   rkey 칸, `ncclDevCommDump` 출력(포인터 값은 가림).
5. 모든 상대 p에 대해 `gated = 1`, `addr`와 p로 가는 모든 QP의 `rq.exch`가 기록 실행과 같고, 장치 게이트 구조(flags, waitMs, rescue 유무)와 게이트 낱말(에폭 0,
   개수 0)이 기록 실행의 같은 자리와 같다. 게이트 보고 뒤의 한 번 잇기(QP를 RTS로)가 성공한다.
비교에서 원래 다를 수밖에 없는 것은 뺀다(코드 검토 C15, 실행 전): 상대별 `fd`(기록 1, 재생 0), helper의 `listen` 표시, 재생에만 있는 한 번 잇기 줄,
`ncclDevCommDump`의 포인터 값과 이 프로세스 자신의 lkey. 비교하는 칸은 gated, haveAddr, addr 해시, exch 해시, flags, waitMs, rescue, rescueLaps, lbase, 에폭,
개수와 4번의 줄들이다. 비교는 [feas/summ_feas.py](feas/summ_feas.py)가 한다.
`b1_neg`는 두 재생 모두 1번이 실패하고 어긋남이 보고될 때 통과다(그렇지 않으면 검사가 눈먼 것이라 B1 전체가 미결).

결론: `b1_rep1`, `b1_rep0`가 2회 모두 통과하고 `b1_neg`가 통과하면 B1의 "초기화 재생" 부분은 이 범위(2 rank, 노드 사이, 문맥 2개, lsaSize 1, host RMA와
RAS 꺼짐)에서 된다고 본다. 남는 부분(REJOIN, 복원 라운드의 토큰 연결, rkey 바꿈, 4 rank와 노드 안 상대의 재생)은 계층을 만들 때의 일로 적는다. 어느 항목이든
실패하면 그 항목과 원인을 증거로 B1을 막힌 채 둔다. 기록으로 대답할 수 없는 NCCL 핵심 상태가 나오면 spike를 거기서 멈추고 근거와 함께 올린다.

#### 9.15.5 빌드, 배포, 실행 명령 (메인 세션)

빌드(rain, 컴파일만; 이 에이전트가 함): `bash feas/build_feas.sh b1-lib`, `app`, `b3`, `info`. 결과물과 md5는 `agent_restore/out/build_info.txt`와 12절에 있다:
`rsx` libnccl `cc8ed9dd6ba3418c72aa0102cc3c251e`(hw 트리 `c7d7f7f` + [feas/rs_spike.diff](feas/rs_spike.diff) md5 `0ee31358`), `rs_spike`
`40d43ed2c8ca4d19202084b7457da4c7`, `rs_drain_test` `7e2e4fde5941ad54e673b77f91ee190e`. 장치 헤더는 hw와 같다(include digest `a27dac89`). 모두 빌드만 됐고
어느 것도 실행하지 않았다.
배포와 실행은 메인 세션이 한다. 아래에서 `F`는 `feas/`의 절대 경로, `R`은 결과 폴더(`results/<실행 날짜>_feasibility`), `SUNNY_SSH`는 관리망 설정
파일에서 읽은 `user@sunny 관리 주소`다(저장소에 적지 않음).

```
F=~/rdma-error-wt/gin-restore/harness/gpu-initiated/gin_recovery/restore/feas
CR=~/rdma-error-wt/gin-restore/harness/gpu-initiated/common/cluster_run.sh
R=~/rdma-error-wt/gin-restore/harness/gpu-initiated/gin_recovery/restore/results/<날짜>_feasibility
SCR=/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad
export SUNNY_SSH=...        # 관리망 설정 파일에서
# 배포(새 디렉터리만; 대상이 있으면 스크립트가 거절): 약 1분
ls -d ~/rs-bundle; ssh -n "$SUNNY_SSH" 'ls -d ~/rs-bundle'          # 둘 다 "No such file"이어야 함
WANT_RSX=cc8ed9dd6ba3418c72aa0102cc3c251e WANT_APP=40d43ed2c8ca4d19202084b7457da4c7 WANT_B3=7e2e4fde5941ad54e673b77f91ee190e \
  bash $F/deploy_feas.sh $SCR/agent_restore/deploy_check.txt
grep -E "MISMATCH|CHANGED|not found|missing" $SCR/agent_restore/deploy_check.txt   # 아무 줄도 없어야 함(strace missing이면 B1 3번은 [미확인])
# hold마다(앞의 hold에 STOP 파일이 없을 때만)
mkdir -p $R
bash $CR -w 10800 -t rs-<HOLD> -- timeout -s KILL 880 bash $F/hold_feas.sh $R <HOLD> > $R/hold_<HOLD>.out 2>&1
# 끝나면(노드 밖, 클러스터 없이)
python3 $F/summ_feas.py $R
```

hold의 차례와 예상 시간(잠금과 한가한 링크를 기다리는 30 s 이상은 빼고), 끝난 뒤 볼 것:

| 차례 | hold | 무엇 | 예상 | 끝난 뒤 볼 것 |
|---|---|---|---|---|
| 1 | `S3` | B3 smoke(노드 사이, rain 응답, ro, 208반복) | 1–2분 | `$R/b3_smoke/b3_x_rain_ro_resp.kv`에 `setup_error`, `nic_error`가 없고 `result=` 줄이 있음(smoke라 PASS가 아니어도 됨), writer `result=WRITER_DONE`, `path_mtu`, `query_p50_us`/`query_max_us`, `query_qp_total`(208반복에 1 000 아래가 좋음), `edge_fraction` ≥ 0.5, `early_iters_stale` ≥ 1, `boundary_iters_stale_last` ≥ 1, 새 mlx5 줄 0, STOP 파일 없음. `edge_fraction` < 0.5면 `RS_LAST_KB=4096`으로 S3을 다시 하고, 그 값과 바뀐 셀당 전송량(window 약 5 MiB; 본 셀 3 200반복이면 셀당 약 17 GB)을 12절에 적은 뒤 B3r, B3s에도 같은 env를 준다(9.15.1의 2 MiB, 8 GB에서 바뀜) |
| 1b | `S3s` | 같은 smoke(sunny 응답) | 1–2분 | 같은 것(`b3_x_sunny_ro`) |
| 2 | `B2` | 4 rank 번갈아 2회 | 1–2분 | `summ_feas.py`의 B2 줄: 네 rank `lsaSize=1`, `nLsaTeams=4`, `nvls=0`, `runtimeConn=1`, `xchg=ok` |
| 3 | `B1` | 기록 + 재생 둘 + 음성 대조 둘, 2회 | 2–4분 | B1 줄: `rep1`, `rep0` PASS, `neg_cut`, `neg_field` "replay failed as required", `meta`의 `strace_sunny`가 2(`--seccomp-bpf`) 또는 1(0이면 3번 항목 `[미확인]`), 재생의 `init_ms`가 기록과 크게 다르지 않음 |
| 4 | `B3r` | B3 셀 여섯(rain 응답; S3, S3s가 위 조건을 채웠을 때만) | 3–6분 | B3 표의 rain 셀: `result`, `valid`, fence 실패 0, `query_max_us` < 50 000, rain QUERY_QP 수의 증가(`snap_*-B3r.txt`), `skipped.txt`, `STOP_nic` 없음 |
| 5 | `B3s` | B3 셀 여섯(sunny 응답) | 3–6분 | 같은 것(sunny 셀) |
| 6(선택) | `B2c` | 4 rank 연달아 1회(대조) | 1분 | `lsaSize=2`가 보이면 읽기가 2 이상도 보여 줌. 실패하면 사실만 적음 |
| 7(선택) | `B1live` | 2 rank가 30 s 쉬는 동안 재생 | 2분 | live 재생 PASS, 살아 있는 rank의 `after_hold_*` 모두 0 |

어느 hold든 `STOP_mlx5`, `STOP_cuda`, `STOP_left`, `STOP_nic`를 남기면 hold_feas.sh가 다음 hold를 거절한다. 그때는 이 에이전트나 사용자에게 올린다.
`skipped.txt`에 줄이 생기면(hold 시간 보호로 건너뛴 셀) 그 셀만 hold `B3one-<셀>`로 다시 한다(B3 셀 하나, 1–2분). 미결 셀을 다시 할 때도 같다.

**2차 배포와 남은 hold(2026-10-09, 검토 3차 뒤).** 위의 첫 배포, `S3`, `B2`는 돌았다(12절). 그 뒤 B1의 라이브러리를 다시 빌드했고(`rsx2`
`c72cdad0bfe4307a117784e821f26b35`, diff md5 `10271487`), B3 본 셀은 3 200반복과 `RS_LAST_KB=4096`으로 바꿨다(9.15.3). `rs_spike` `40d43ed2`와
`rs_drain_test` `7e2e4fde`는 이미 배포한 것을 그대로 쓴다. B1은 독립 재검토가 "B1 ready to run"이라고 한 뒤에만 돈다.

```
# 2차 배포: 새 디렉터리 ~/rs-bundle/rsx2/ 하나만(있으면 거절), 그 밖의 ~/rs-bundle과 다른 묶음은 앞뒤 md5가 같아야 함. 약 30 s
ls -d ~/rs-bundle/rsx2; ssh -n "$SUNNY_SSH" 'ls -d ~/rs-bundle/rsx2'      # 둘 다 "No such file"이어야 함
WANT_RSX2=c72cdad0bfe4307a117784e821f26b35 bash $F/deploy_feas.sh $SCR/agent_restore/deploy_check_rsx2.txt rsx2
test -s $SCR/agent_restore/deploy_check_rsx2.txt && echo written                  # 확인 파일이 있어야 함(ssh가 중간에 끊기면 없음:
#   그때는 두 노드의 ~/rs-bundle/rsx2를 손으로 보고 올린다)
grep -E "MISMATCH|CHANGED|not found" $SCR/agent_restore/deploy_check_rsx2.txt   # 아무 줄도 없어야 함
# B1(기본 LIBDIR = ~/rs-bundle/rsx2, NCCL_GIN_TS_QPWATCH_MS=100; 결과는 $R/b1/, 다시 하면 $R/b1_run<k>/)
bash $CR -w 10800 -t rs-B1 -- timeout -s KILL 880 bash $F/hold_feas.sh $R B1 > $R/hold_B1.out 2>&1
# B3 본 셀(셀마다 3 200반복, RS_LAST_KB=4096을 실행기가 넘김; 결과는 $R/b3/)
bash $CR -w 10800 -t rs-B3r -- timeout -s KILL 880 bash $F/hold_feas.sh $R B3r > $R/hold_B3r.out 2>&1
bash $CR -w 10800 -t rs-B3s -- timeout -s KILL 880 bash $F/hold_feas.sh $R B3s > $R/hold_B3s.out 2>&1
python3 $F/summ_feas.py $R
```

| hold | 예상(잠금과 링크 기다림 빼고) | 끝난 뒤 볼 것 |
|---|---|---|
| `B1` | 2–3분(시행마다 기록 약 10 s, 재생 둘, 음성 대조 둘) | B1 줄: `rep1`, `rep0` PASS, `neg_cut`, `neg_field` "replay failed as required", `strace_mode` 2, 재생 `init_ms`가 기록과 비슷함, 재생 로그에 "no protection domain"이 없음, `hold_B1.out`의 새 mlx5 줄 0 |
| `B3r` | 3–5분(셀 여섯, 셀마다 약 3 400반복, 1–2 ms씩) | B3 표의 rain 셀: `result`, `valid`, fence 실패 0, `query_qp_total` < 20 000, `query_max_us` < 50 000, meta의 `last_kb=4096`, `skipped.txt`와 `STOP_nic` 없음 |
| `B3s` | 3–5분 | 같은 것(sunny 셀). 끝나면 B3 결론 줄 |

B3 본 셀의 QUERY_QP 예상(rain 셀당 약 16 800)은 노드 사이 smoke에서만 나왔다. 같은 노드 셀과 경합 셀은 4 MiB에서 잰 적이 없다. 어느 셀이 "QUERY_QP cap of the
cell reached"로 멈추면(`STOP_nic`) 그것은 상한 멈춤이지 시험 결과가 아니다: 남은 셀을 하지 않고(실행기가 막음) 올리며, 그 셀만 반복을 줄여(예: 2 400, 채점
fence 1 200) 새 hold로 다시 하는 것을 사용자나 이 에이전트와 정한다(다시 검토 Q2, 실행 전; 경합 셀은 아래 `b3v3` 블록의 질의 예산으로 정함). B1의 `abort_rc=0`은 깔끔한 정리를 증명하지 않는다: application이
`ncclDevCommDestroy`를 부르지 않아 collComm을 닫을 때 PD 해제가 EBUSY로 실패할 수 있고, 기록 실행도 같으며 NCCL이 그 오류를 숨긴다(Q1, 판정에 영향 없음).

**`STOP_nic`를 푸는 규칙(2026-10-09, B3r 뒤에 정함).** `STOP_nic`는 지우지 않는다. 메인 세션은 다음이 모두 참일 때만 그 파일을
`STOP_nic.cleared-<날짜시각>`으로 옮기고, 진단을 12절에 적는다.
1. 멈춘 셀의 응답 쪽 kv가 `setup_error`로 끝났고(설정 단계: 본 반복 전), `nic_error`, `watchdog=1`, `cuda_error`가 없다. 보내는 쪽의 `nic_error="control receive
   (peer gone or bound)"`는 응답 쪽이 끝나서 생긴 것이라 이 조건에 든다.
2. 그 원인이 시험 프로그램이나 실행기의 결함으로 진단되어 12절에 적혔고, 그것을 고친 새 바이너리(새 디렉터리)가 독립 검토를 받았다.
3. 그 hold의 새 mlx5 커널 줄이 0이고, rain의 펌웨어 명령 실패 셈(`fwcmd failed sum`)과 `cmd_err` 줄 수가 hold 앞과 같고, 남은 시험 프로세스가 0이다.
4. 같은 hold의 다른 셀에는 `setup_error`, `nic_error`가 없다.
`nic_error`로 멈춘 경우는 위 규칙으로 풀지 않는다: "QUERY_QP cap of the cell reached"는 상한 멈춤(위)이라 반복 수를 정한 뒤에, CQE 오류, rmsn 2 s 초과, QUERY_QP
50 ms 초과, 반복당 200회 초과는 이 에이전트나 사용자에게 올리고 원인을 본 뒤에만 푼다. `STOP_mlx5`, `STOP_cuda`, `STOP_left`도 같다(올림).

**2026-10-09 B3r 뒤: `b3v2`와 남은 B3 hold.** B3r의 `b3_h_rain_ro`는 설정의 loopback READ 자체 시험에서 멈췄다(12절의 진단: 첫 빌드는 그 시험의 무늬를 페이지
가능한 호스트 메모리에서 `cudaMemcpy`로 써서, 복사의 DMA가 끝나기 전에 READ가 옛 낱말을 읽을 수 있었고 GPU가 바쁘면 그 틈이 커짐). 고친 `rs_drain_test`
(`b3v2`, md5 `db5541eb7195619410b2113b137ad0df`)는 무늬를 pinned 메모리에서 쓰고 장치를 동기화한 뒤 READ가 옛 낱말이면 1 ms 간격으로 50번까지 다시 읽고 그
횟수와 읽은 값을 kv에 적는다. 본 반복의 코드는 첫 빌드와 같다(바뀐 것은 이 자체 시험과 머리 주석뿐). 그래서 첫 빌드로 통과한 rain 셀 넷은 그대로 쓰고,
남은 셀(`b3_h_rain_ro`, `b3_h_rain_so`, B3s 여섯)은 `b3v2`로 한다(실행기 기본값; meta의 `bin=`에 남음).

```
# b3v2 배포: 새 디렉터리 ~/rs-bundle/b3v2/ 하나만(있으면 거절), 그 밖의 ~/rs-bundle과 다른 묶음은 앞뒤 md5가 같아야 함. 약 30 s
ls -d ~/rs-bundle/b3v2; ssh -n "$SUNNY_SSH" 'ls -d ~/rs-bundle/b3v2'      # 둘 다 "No such file"이어야 함
WANT_B3V2=db5541eb7195619410b2113b137ad0df bash $F/deploy_feas.sh $SCR/agent_restore/deploy_check_b3v2.txt b3v2
test -s $SCR/agent_restore/deploy_check_b3v2.txt && echo written               # 확인 파일이 있어야 함(ssh가 중간에 끊기면 없음:
#   그때는 두 노드의 ~/rs-bundle/b3v2를 손으로 보고 올린다)
grep -E "MISMATCH|CHANGED|not found" $SCR/agent_restore/deploy_check_b3v2.txt   # 아무 줄도 없어야 함
# STOP_nic 풀기(위 규칙의 1–4를 확인한 뒤, 12절에 진단이 있을 때)
mv $R/STOP_nic $R/STOP_nic.cleared-$(date +%Y%m%d-%H%M%S)
# 경합 셀 둘을 다시(셀마다 hold 하나, b3v2, 3 200반복, RS_LAST_KB=4096; 결과는 $R/b3_rerun1/): 셀마다 약 1분
bash $CR -w 10800 -t rs-B3one-hro -- timeout -s KILL 880 bash $F/hold_feas.sh $R B3one-b3_h_rain_ro > $R/hold_B3one-hro.out 2>&1
bash $CR -w 10800 -t rs-B3one-hso -- timeout -s KILL 880 bash $F/hold_feas.sh $R B3one-b3_h_rain_so > $R/hold_B3one-hso.out 2>&1
# 둘 다 STOP 없이 끝났을 때만
bash $CR -w 10800 -t rs-B3s -- timeout -s KILL 880 bash $F/hold_feas.sh $R B3s > $R/hold_B3s.out 2>&1
python3 $F/summ_feas.py $R
```

**2026-10-09 경합 셀의 상한 멈춤 뒤: `b3v3`.** `b3v2`로 다시 한 `b3_h_rain_ro`는 자체 시험을 한 번에 통과했지만(진단 확인) 고리 도중 셀당 QUERY_QP 상한
20 000에 닿아 `nic_error`로 멈췄고, 그 출구는 진행 정도를 적지 않았다(12절). `rs_drain_test` `b3v3`(빌드됨, 실행 안 함; md5 `62fed1fd2104cdfe92b3c50defcc0093`,
소스 `bcf58d50`)은 (1) 오류 출구(NIC 오류, CUDA 오류, watchdog)에서 `progress_*`(한 반복, 채점 fence 수, QUERY_QP 수, 주 대기의 반복당 질의 수)를 적고,
정상 끝에서는 같은 값을 `iterations_done`, `scored_n`, `query_qp_total`, `polls_per_iter_mean`으로 적는다(소스 주석 89–90행은 정상 끝에서도 `progress_*`를
쓴다고 하지만 틀린 말이다. 빌드 소스의 md5를 지키려고 주석은 고치지 않는다, 다시 검토 U1). `progress_polls_per_iter`와 `polls_per_iter_mean`은 `early`,
`boundary`를 뺀 길의 주 대기만 센다. 반복당 질의 수를 정할 때는 `query_qp_total / iterations_done`(오류 출구면 `progress_query_qp /
progress_iterations_done`)을 쓴다(U2). (2) `RS_QUERY_BUDGET`(기본 꺼짐)이 있으면 반복을 시작할 때 QUERY_QP가 그 수 이상인지 보고 그러면 고리를 마친다
(`budget_stop=1`, 위 9.15.3; 정상 끝이라 STOP 파일 없음). 예산이 꺼져 있으면 고리는 `b3v2`와 같다.
실행기는 `b3v3`을 기본으로 쓰고 경합 셀에만 `RS_QUERY_BUDGET=19000`을 넘긴다(meta의 `query_budget=`).

상한 멈춤의 `STOP_nic`("QUERY_QP cap of the cell reached")를 푸는 단계: 다음이 모두 참일 때 `STOP_nic.cleared-<날짜시각>`으로 옮기고 12절에 적는다. (1) 응답 쪽 kv의
오류가 정확히 그 문구이고 `watchdog=1`, `cuda_error`, 다른 `nic_error`가 없음(보내는 쪽의 "the peer reported an error"는 그 결과), (2) 그 셀들의 새 계획(여기서는
예산 19 000)이 12절에 정해졌고 그것을 담은 새 바이너리가 독립 검토를 받음, (3) 새 mlx5 줄 0, rain 펌웨어 명령 실패 셈과 `cmd_err` 그대로, 남은 시험 프로세스 0,
(4) 그 hold의 rain debugfs QUERY_QP 증가가 20 000을 넘지 않음(상한이 지켜짐).

```
# b3v3 배포: 새 디렉터리 ~/rs-bundle/b3v3/ 하나만(있으면 거절), 그 밖의 ~/rs-bundle과 다른 묶음은 앞뒤 md5가 같아야 함. 약 30 s
ls -d ~/rs-bundle/b3v3; ssh -n "$SUNNY_SSH" 'ls -d ~/rs-bundle/b3v3'      # 둘 다 "No such file"이어야 함
WANT_B3V3=62fed1fd2104cdfe92b3c50defcc0093 bash $F/deploy_feas.sh $SCR/agent_restore/deploy_check_b3v3.txt b3v3
test -s $SCR/agent_restore/deploy_check_b3v3.txt && echo written
grep -E "MISMATCH|CHANGED|not found" $SCR/agent_restore/deploy_check_b3v3.txt   # 아무 줄도 없어야 함
# 상한 멈춤의 STOP_nic 풀기(위 1–4를 확인한 뒤)
mv $R/STOP_nic $R/STOP_nic.cleared-$(date +%Y%m%d-%H%M%S)
# 경합 셀 둘(b3v3, 3 200반복 상한, RS_LAST_KB=4096, RS_QUERY_BUDGET=19000; b3_h_rain_ro는 b3_rerun2/, b3_h_rain_so는 b3_rerun1/): 셀마다 약 30–40 s
bash $CR -w 10800 -t rs-B3one-hro2 -- timeout -s KILL 880 bash $F/hold_feas.sh $R B3one-b3_h_rain_ro > $R/hold_B3one-hro2.out 2>&1
bash $CR -w 10800 -t rs-B3one-hso -- timeout -s KILL 880 bash $F/hold_feas.sh $R B3one-b3_h_rain_so > $R/hold_B3one-hso.out 2>&1
# 둘 다 STOP 없이 끝났을 때만(B3s의 경합 셀 둘도 같은 예산; x, s는 3 200반복)
bash $CR -w 10800 -t rs-B3s -- timeout -s KILL 880 bash $F/hold_feas.sh $R B3s > $R/hold_B3s.out 2>&1
python3 $F/summ_feas.py $R
```

끝난 뒤 볼 것(경합 셀): `budget_stop`(1이면 예산으로 끝남), `iterations_done`, 채점 fence 수(`fence_W_n` + `fence_AW_n`), `query_qp_total` ≤ 19 400, 반복당 질의 수
(`query_qp_total / iterations_done`), 자체 시험 시도 1/1, `result`, `valid`, hog의 `HOG_DONE`. B3s의 `x`, `s` 셀은 앞과 같다. 마지막의 B3 결론 줄은 노드마다 실제 채점 수로 상한을 다시 적는다.

(이 문단은 `b3v2` 때의 것이다. 경합 셀은 이제 `b3v3`과 질의 예산으로 하고, 확인은 위 `b3v3` 블록의 것(`query_qp_total` ≤ 19 400,
`budget_stop`, 실제 채점 수)을 따른다. 아래의 `query_qp_total` < 20 000은 예산이 꺼진 셀에만 맞다, 다시 검토 U4.) 다시 한 셀은 `b3_rerun<k>/`에 있고 `summ_feas.py`가 그 셀의 마지막 실행으로 읽는다(앞의 실행은 표 아래 "earlier runs"에 남음). 노드와 순서마다의 묶음은 셀
`x`, `s`, `h`의 마지막 실행으로 한다(rain의 `x`, `s`는 첫 빌드, `h`는 `b3v2`; summ_feas가 셀마다 빌드와 `last_kb`, 자체 시험의 시도 수, hog 결과를 표로
보임). 끝난 뒤 볼 것: 다시 한 경합 셀의 kv에 `selfcheck_fence_attempts`, `selfcheck_same_attempts`, `result=PASS`, `valid=1`, fence 실패 0, `query_qp_total`
< 20 000, hog의 `HOG_DONE`; B3s 셀 여섯은 B3r과 같은 것; 마지막에 B3 결론 줄. 진단대로라면 시도 수는 늘 1이다. 1보다 크면 셀이 통과해도 그 수를 측정으로
12절에 적고 B3s 전에 올린다(진단과 맞지 않음; 본 반복의 판정에는 영향 없음; 다시 검토 S3). 한계: `b3v2`는 READ 전에 staging을 0으로 지우므로, 읽은 값 0은
"옛 낱말"과 "READ가 아무것도 쓰지 않음"을 가르지 못한다(S2, 바이너리를 다시 만들지 않고 둠).

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
- [x] 독립 충돌 검토 둘(EXPERIMENT.md 초안 표, DESIGN_POLICY.md)과 반영. 검토 2의 마지막 판정: B1–B4 밖에 풀리지 않은 충돌 없음
- [x] B4 결정: (나)(2026-10-09, 사용자)
- [x] (나)와 `pe.lostAfterCommit` 계약의 독립 충돌 검토(DESIGN_POLICY.md 6절 검토 3과 재확인: 풀리지 않은 충돌 없음)
- [ ] 사용자의 설계 승인(그 전에는 복원 계층의 구현과 빌드 없음. B1–B3 실행 가능성 시험은 2026-10-09 허용)
- [ ] gpu-detect 계층에 정책 hook G1–G9(DESIGN_POLICY.md 4.10절)
- [ ] 시제품: 로그, 체크포인트, 복원 계획, 억제, 모의, 단위 시험(9.13절, 멈춤)
- [ ] 시험 프로그램 `gin_rs.cu`
- [x] B1–B3 실행 가능성 시험의 설계, 충돌 표, 판정 기준(9.15절, 실행 전)
- [x] B1–B3 시험 설계의 독립 검토와 반영
- [x] 시험 코드의 독립 검토와 반영(실행 전)
- [x] B2: 기존 원자료 확인(값 없음, 9.15.2절)
- [x] B2: 시험 application으로 확인(2회, 해결 A; 2026-10-09)
- [x] B3: `rs_drain_test` 빌드됨
- [x] B3: smoke(1 024에서 rain 미결, 4 096에서 rain, sunny 유효)
- [x] B3: 본 셀 열둘(3 200반복, `RS_LAST_KB=4096`; 경합 셀은 예산 19 000) 실행: rain 넷과 sunny 여섯 통과(sunny 경합 `so`는 다시 해서), rain 경합 둘은
  두 번씩 미결(9.15.3 결과)
- [x] B3: 열린 rain 경합 셀의 사용자 결정(2026-10-11: 경합 셀 넷만 다시 확인한 뒤 다시 정함)
- [x] B3 경합 셀 다시 확인의 설계와 충돌 표(9.15.3, 빌드 전)
- [ ] 그 설계의 독립 검토
- [ ] `b3v4` 빌드와 코드의 독립 검토
- [ ] 진단(`b3_diag/`)과 새 경합 셀 넷(`b3_m_*`) 실행
- [ ] B3의 사용자 결정(다시)
- [x] B1: `rsx` hook과 `rs_spike` 빌드됨
- [x] B1: 검토 3차의 막는 결함 P1 고침, 둘째 빌드 `rsx2`
- [x] B1: 기록과 재생, 음성 대조(2회 통과, 2026-10-09)
- [ ] 배포(`~/rs-bundle/`)와 실행 명령(메인 세션), 결과 정리(`results/<날짜>_feasibility/`)
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
| 2026-10-09 | 검토 1 결과(F1–F28) 반영. 검토 2(이 문서 대상, 읽기 전용 에이전트): 첫 검토 V1–V20, 재확인 N1–N5, P1–P7, Q1–Q5, R1을 차례로 반영. 마지막 판정(커밋 `0af9190e`): 막는 문제 B1–B4 밖에 풀리지 않은 충돌 없음 | DESIGN_POLICY.md 6절, 커밋 `fb27b091`–`0af9190e` |
| 2026-10-09 | 사용자 결정 둘. (1) B4는 (나): 게이트 뒤의 키 다시 읽기는 hold 정책의 communicator에서만, fail-fast는 측 표 포인터의 분기 하나만 더함(4 KiB, 256 KiB 지연은 계층을 만들 때 잼). (2) B1(예비 프로세스의 초기화 재생), B2(GPU를 나눠 쓰는 rank의 LSA 팀 크기), B3(relaxed ordering window MR에서 체크포인트 drain이 보이는가)의 실행 가능성 시험을 한다. 복원 계층은 여전히 구현하지 않고, 스크래치의 시제품 초안도 빌드하지 않는다 | 9.1, 9.6절, 9.9절 DV3, DESIGN_POLICY.md 5절 B4 |
| 2026-10-09 | 병렬로 도는 gpu-detect 고침과의 계약을 설계에 넣음(메인 세션이 정함): 응답 쪽 Commit 뒤 게시 전에 소켓을 잃은 길(hw 5285–5292, 5298–5303)에서 거절 바로 전에 `pe.lostAfterCommit = true`, 죽음 판정이면 그 거절은 PeerDead/`GDAKI_UA_PEER_DEAD`(degraded 예약), 아니면 지금과 같음. 복원 설계는 이 창을 계속 붙잡지 않는다: G2의 강한 증거 검사가 그 표시가 선 거절을 뺀다(NOHOLD), REJOIN이 표시를 지운다 | 9.3절 8단계, DESIGN_POLICY.md 2.4, 3절, D4, R3, 4.10절 끝 |
| 2026-10-09 | 검토 3(읽기 전용 에이전트): 결정 (나)와 `lostAfterCommit` 계약 대상. 중간 W1–W3(측 표 포인터를 쓰는 때와 무장 조건, 포인터의 두 뜻 → QP마다 "로그 켬" 낱말, get 키도 다시 읽음), 낮음과 메모 W4–W11 반영. 재확인: W1–W11 풀림, 낮음 X1–X5 반영(표시를 세우는 자리는 "잃은 자리에서, `gdakiTsSocketLost` 전" 하나로; gpu-detect에 넘길 것). 판정: 풀리지 않은 충돌 없음 | DESIGN_POLICY.md 6절 검토 3, 커밋 `daa63c69`, `6b33627e`와 이 커밋 |
| 2026-10-09 | B2의 기존 원자료 확인: gin-multirank 본 실행 보관본(Release `data-20261009`의 `harness__gpu-initiated__gin_recovery__multirank__results__20261009.tar.xz`, sha256 앞 12자 `3c22ffd4d260`, 세션 스크래치에 풂)의 4-rank 로그와 kv에 LSA 값이 없음. NCCL도 이 경우 값을 찍지 않음(`dev_runtime.cc` 140, 1742) | 9.15.2절 `[측정, 소스]` |
| 2026-10-09 | B1–B3 실행 가능성 시험의 설계와 충돌 표, 판정 기준을 실행 전에 적음. B1 빌드 트리를 hw 트리에서 복사(`agent_restore/b1/`, 복사본의 hw 커밋 `c7d7f7f`, diff md5 `be0ea9ed` 확인; hw 트리는 고치지 않음) | 9.15절 |
| 2026-10-09 | B1–B3 시험 설계의 독립 검토(읽기 전용 에이전트 둘). B3 "고치면 답함": 꼬리의 신호 원자 연산이 그 자체로 drain을 보장해 시험을 무력하게 함(T3-1, 높음), READ 대상이 설계와 다름(T3-2, 높음), RO가 실제로 켜졌는지의 증거, 경계 대조와 경계 덮기, `cuFlushGPUDirectRDMAWrites` 길, cuMem과 GPU 원본, 경합, QUERY_QP 간격과 상한, 노드별 통계(T3-3–T3-12). B1 "고치면 답함": host RMA proxy가 hook 밖에서 상대마다 IB 연결을 맺음(T1-1, 높음), hook의 셈으로는 hook 밖 연결을 못 봄 → strace(T1-2), 자리별 가면 비교, 판정 항목 추가, 음성 대조, 주소 처리(T1-3–T1-11). B2 "답함", lsaSize 1이어도 남는 매핑 길을 무장 조건으로(T2-3). 모두 9.15절, 9.4절 3단계, 9.7절 6번, DESIGN_POLICY.md 2.3절, A3, D3에 반영하고 판정 기준을 실행 전에 다시 고정함. B3 프로그램은 검토가 도는 동안 초안을 쓰기 시작했고, 반영 뒤에만 빌드함 | 9.15절 |
| 2026-10-09 | 시험 코드를 씀([feas/](feas/)): B3 `rs_drain_test.cu`, B1 hook `rs_spike.diff`(hw 트리의 복사 `agent_restore/b1/`, 파일 8개), B1과 B2 application `rs_spike.cu`, 실행기(`hold_feas.sh`, `run_b3.sh`, `run_spike.sh`), 빌드와 배포(`build_feas.sh`, `deploy_feas.sh`), 판정 스크립트(`summ_feas.py`). B2는 hw 복사본 대신 `rsx`에 보고 줄만 켜서 하기로 바꿈(같은 코드에 hook이 닿지 않음; 배포할 라이브러리를 하나로) | 커밋 `bc6e47d5`와 이 커밋 |
| 2026-10-09 | 실행 전 독립 코드 검토(읽기 전용 에이전트): B2 "실행 가능", B1 "먼저 고칠 것 C8, C9", B3 "먼저 고칠 것 C1, C2, C3, C6". 고친 것: early 반복 셈(C1), 경로 MTU 교환(C2), 도달 시간을 M을 본 질의의 시작으로(C3), 반복당 QUERY_QP 200(C4), 결과 차례(C5), 셀마다 STOP 검사와 hold 시간 보호(C6, C7), strace `--seccomp-bpf`(C8), strace 해석의 PID 접두와 양성 대조와 루프백 판별(C9), 자기 주소 connect 따로(C10), umask 077(C11), 끊긴 hold의 자기 파일 지움(C12), devComm 내부 window 보고(C13), 비교 칸의 명세(C15), sunny 응답 smoke(C17). 스스로 찾은 것: GDAKI dump의 자기 lkey를 비교에서 가림, 보내는 쪽 SGE 주소를 iova 0 MR에 맞춤. 남긴 것: C14(무해), C16(재생에서 RESET QP의 QUERY_QP가 거절되면 투명 복구가 꺼진다는 WARN으로 드러남, `[미확인]`) | 9.15절 |
| 2026-10-09 | 빌드됨(rain, nice 19, ionice idle; 실행 안 함): `rsx` libnccl `cc8ed9dd6ba3418c72aa0102cc3c251e`(diff md5 `0ee313583f7e5d2d0e305d3ec1e4d28d`, 장치 헤더는 hw와 같음), `rs_spike` `40d43ed2c8ca4d19202084b7457da4c7`, `rs_drain_test` `7e2e4fde5941ad54e673b77f91ee190e`. 배포와 실행은 9.15.5절의 명령으로 메인 세션이 함 | `agent_restore/out/build_info.txt` |
| 2026-10-09 | 코드 재검토(같은 에이전트, 커밋 `269c2d78` 대상): C1–C13, C15, C17 풀림. 새로 고친 것: 자기 rank의 peer 줄(gated=0)을 5번 검사에서 뺌(N1, 높음), B3 셀 다시 하기를 `b3_rerun<k>/`에 두고 판정은 마지막 것(N2), application의 stdout 줄 버퍼(N3: `_exit` 때 NCCL WARN 줄을 잃지 않게), 음성 대조는 init, reg, devcomm 가운데 하나라도 실패하면 실패로 봄(N4), live 셀의 자기 주소 connect 상한(N5), strace가 없는 노드는 3번 `[미확인]`(N6), B3 결론의 갈래 차례(N7), 기록 끝 표시는 위치만 비교(N8), B2 시행 둘을 묶은 판정(N9). dump 비교는 끼어든 로그 줄을 건너뜀. 판정 스크립트를 합성 파일로 시험함(B1 통과와 음성 대조, B2 해결 A, B3의 네 갈래). `rs_spike` 다시 빌드됨 `40d43ed2c8ca4d19202084b7457da4c7`(나머지 md5는 같음) | 이 커밋 |
| 2026-10-09 22:22 | 메인 세션이 배포(첫 빌드: `rsx` `cc8ed9dd`, `rs_spike` `40d43ed2`, `rs_drain_test` `7e2e4fde`를 두 노드의 새 `~/rs-bundle/`에). 확인 파일: 새 파일 rain과 sunny 같음(3개), 원본과 같음, ldd 맞음, 두 노드에 strace 있음, 기존 묶음 그대로(rain 323, sunny 375개) | `agent_restore/deploy_check.txt` |
| 2026-10-09 22:23 | hold `S3`(smoke, 기본 `RS_LAST_KB=1024`, rain 응답, ro, 221반복 = 208 + 탐침 13): 미결. `boundary` 12반복에서 마지막 메시지의 늦은 낱말 0(`boundary_missed` 1), `early` 13/13, 경계 덮기 0.692, fence W와 AW 104반복 실패 0, QUERY_QP 383(p50 59.9 µs, 최대 90.9 µs), 경로 MTU 5(4096 B). 채점 아님 `[측정: 원자료에서 다시 셈]` | `results/20261009_feasibility/b3_smoke/b3_x_rain_ro_resp.kv` |
| 2026-10-09 22:24–22:26 | smoke를 `RS_LAST_KB=4096`으로 다시(hold `S3`, `S3s`, 태그 `rs-S3k`, `rs-S3s`). 문서의 스위치를 문서에 적은 이유(경계 덮기 < 0.5)가 아닌 이유로 썼다: 경계 덮기는 채웠고 모자란 것은 `boundary` 대조였다. rain 응답: 유효, PASS, `boundary` 13/13, `early` 13/13, 경계 덮기 1.000, QUERY_QP 1 091(p50 55.3 µs, 최대 81.1 µs), 도달 p50 770 µs. sunny 응답: 유효, PASS, 13/13, 13/13, 1.000, QUERY_QP 777(p50 71.5 µs, 최대 113.5 µs), 도달 p50 648 µs. 두 smoke 모두 fence, fsame, nofence, cuflush, 탐침의 실패 0, `gdr_writes_ordering=0`, `gdr_flush_options=1`, HCA `relaxed_ordering_write` 능력 1. rain의 S3 hold 앞뒤 debugfs QUERY_QP 셈의 차이가 1 091로 프로그램의 셈과 같음. 채점 아님 `[측정: 원자료에서 다시 셈]` | `results/20261009_feasibility/s3_last4096/b3_smoke/` |
| 2026-10-09 22:26 | hold `B2`(태그 `rs-B2`, 첫 빌드 `rsx`, 보고 줄만, hw QP 감시 기본 10 ms): 2회 모두 네 rank `lsaSize=1`, `nLsaTeams=4`, `nvlsSupport=0`, `runtimeConn=1`, `numRmaCtx=0`, GIN 교환 맞음, 종료 0(시행마다 2.0 s, hold 14 s). 판정: 해결 A(9.15.2) `[측정: summ_feas.py로 다시 셈]`. 이 배치에서 생존 rank는 다른 프로세스의 GPU 메모리를 LSA로 매핑하지 않는다 | `results/20261009_feasibility/b2/`, `results/20261009_feasibility/SUMMARY.txt` |
| 2026-10-09 | 모든 hold에서 STOP 파일 없음, 새 mlx5 커널 줄 0 `[측정: mlx5_new_*.txt]`. B1은 돌지 않았다 | `results/20261009_feasibility/` |
| 2026-10-09 | 독립 검토 3차(B1 중심, 메인 세션이 맡김, 보고는 세션 스크래치의 `rs_review_b1_pass3.md`): 막는 결함 P1 — 재생은 GIN ring 연결을 건너뛰는데 그 연결만 장치 protection domain을 할당하므로 `cComm->ib.pd`가 NULL로 남아 `ncclDevCommCreate`의 첫 GDAKI MR 등록에서 멈췄을 것(첫 빌드 `cc8ed9dd`로 B1을 돌렸다면 B1이 막힌 것처럼 읽혔을 것). 그 밖에 P2(재생에서 RESET QP에 QUERY_QP), P3(hw QP 감시의 펌웨어 명령, 9.15.1에 없음), P4–P7, P9, P10 낮음 | 9.15.1, 9.15.4 |
| 2026-10-09 | 3차 반영: P1 재생 collComm이 장치 PD 참조를 직접 잡고(0에서 1이면 할당) 닫을 때 놓음, 없으면 WARN과 실패; P2 재생에서는 `gdakiTsSetup`의 rmsn 기준 질의를 하지 않고 한 번 잇기 뒤에 잡음; P3 B1, B2의 NCCL 프로세스는 `NCCL_GIN_TS_QPWATCH_MS=100`(기록과 재생이 같게; 이미 돈 B2의 부하는 9.15.1에 적음); P4 음성 대조의 문구 맞춤을 좁힘(`diverged=0`이 맞지 않게); P5 비교할 보고 줄이 있어야 함(window 줄 셋 이상 등); P6 `nokey` 해시 거부; P7 한 번 잇기는 게이트 보고 뒤(문서); P9 STOP으로 거절하는 hold도 남은 프로세스가 없으면 자기 파일을 지움; P10 B1, B2를 다시 하면 새 폴더(`b1_run<k>`, `b2_run<k>`), 판정은 폴더마다 | 이 커밋 |
| 2026-10-09 | 둘째 빌드(rain, nice 19, ionice idle; 실행 안 함): `rsx2` libnccl `c72cdad0bfe4307a117784e821f26b35`(diff md5 `102714874d19c61e0659aecae0995fca`, 장치 헤더는 hw와 같음). `rs_spike`와 `rs_drain_test`는 바뀌지 않음. 배포는 새 디렉터리 `~/rs-bundle/rsx2/`에만(`deploy_feas.sh <확인 파일> rsx2`, 이미 배포한 파일은 덮어쓰지 않고 앞뒤 md5를 봄), B1 실행기의 기본 라이브러리는 `rsx2` | `agent_restore/out/build_info.txt` |
| 2026-10-09 | B3 본 셀의 결정(실행 전, 판정 기준은 그대로): `RS_LAST_KB=4096`을 B3r, B3s, 다시 하는 셀에 실행기가 명시해 meta에 남김(이유: 1 024 smoke의 `boundary` 대조가 한 번도 늦은 낱말을 보지 못함). 4 096에서 rain은 반복당 QUERY_QP 약 4.9번이라 4 000반복이면 셀당 상한 20 000에 닿으므로 상한은 두고 반복을 셀당 3 200으로 줄임(예상 rain 약 16 800, sunny 약 12 000). 채점 fence는 셀당 1 600, 노드와 순서마다 4 800, 실패율 95% 상한 약 0.0625%. 셀당 전송량 약 17 GB | 9.15.1, 9.15.3 |
| 2026-10-09 | gpu-detect의 `hk` 빌드(`~/rdma-error-wt/gpu-detect/harness/gpu-detect/hk_layer.diff`, 사전 등록 태그 `prereg/gpu-detect-v1`)를 읽어 계약 확인(읽기만): `gdakiTsDeclineAfterCommit`가 맨 처음에 `pe.lostAfterCommit = true`를 세우고(어느 돌아가기, `gdakiTsSocketLost`보다 먼저), 두 자리(ACK 보내기 실패, DONE 기다림 중 잃음)가 모두 이 함수를 부른다. ACK 실패 길은 죽음 판정을 하지 않고 errno 이름을 `closeCause`에 넣는다(hk 검토 지적 1로 받기 쪽 peek을 뺌). DONE 길은 `gdakiTsCauseLiveness`가 죽음이면 `gdakiTsSocketLost` 뒤 PeerDead, `GDAKI_UA_PEER_DEAD`로 거절. 표시는 `gdakiTsInstall`에서 지운다(REJOIN이 설치하는 자리). 그래서 검토 3의 W10/X5와 W11을 hk가 채운다 `[소스: hk_layer.diff]` | DESIGN_POLICY.md 2.4절 |
| 2026-10-09 | 3차 반영의 독립 재검토(읽기 전용 에이전트, 커밋 `4bd76410` 대상): md5 확인(`rsx2` `c72cdad0`, diff `10271487`가 트리와 같음, `rs_spike` `40d43ed2`), P1 고침(PD 참조 셈, 장치 번호, 잠금, 실패 길, 해제), P2 고침이 맞음, 스크립트와 문서가 맞음. 재생이 시험 결함으로 실패할 남은 길은 찾지 못함. 낮음: Q2(B3 QUERY_QP 예산은 노드 사이 smoke에서만 잼 → 9.15.5에 예산 멈춤의 처리), Q3(dump 비교에서 빈 줄을 뺌), Q4, Q5(문서), Q1(정보: 정리의 PD 해제 EBUSY는 기록과 같고 숨겨짐). 판정: "B1: ready to run", "B3 main cells (B3r/B3s): ready to run" | 이 커밋 |
| 2026-10-09 22:50 | 메인 세션이 `rsx2`를 배포(새 `~/rs-bundle/rsx2/`): rain과 sunny 같음, 원본과 같음, ldd 맞음, 기존 파일 그대로(rain 328, sunny 380개) | `agent_restore/deploy_check_rsx2.txt` |
| 2026-10-09 22:50–22:51 | hold `B1`(태그 `rs-B1`, `rsx2`, QP 감시 100 ms, hold 28 s): 2회 모두 `rep1`, `rep0` 통과, 음성 대조 둘 다 init에서 실패(init_rc 2), 기록 12 117 B, 기록 29항목을 재생 29항목으로 정확히 소비(어긋남 0, 기록 밖 0, 자리별 가면 비교의 다름 0, 자기 칸의 다른 바이트 46과 49), 한 번 잇기 2/2, strace `--seccomp-bpf`에서 socket 13, 상대로의 connect 0, 자기 주소 0, AF_UNIX 1(자기 proxy), init_ms 기록/재생 211.8/174.3, 187.2/170.4, 223.0/185.5, 186.3/189.3, 재생의 abort 약 0.9 s, "no protection domain" 줄 없음. 판정(9.15.4): 이 범위(2 rank, 노드 사이, 문맥 2개, lsaSize 1, host RMA와 RAS 꺼짐)에서 초기화 재생은 된다 `[측정: summ_feas.py와 원자료로 다시 셈]` | `results/20261009_feasibility/b1/` |
| 2026-10-09 22:51–22:53 | hold `B3r`(태그 `rs-B3r`, 첫 빌드 `rs_drain_test`, 3 200반복, `RS_LAST_KB=4096`, hold 43 s): `b3_x_rain_ro`, `b3_x_rain_so`, `b3_s_rain_ro`, `b3_s_rain_so` 모두 유효, PASS(채점 fence W와 AW 1 600반복 실패 0, `early` 200/200, `boundary` 200/200, 경계 덮기 1.000, fsame, nofence, cuflush, WA, 탐침의 실패 0, QUERY_QP 17 447–17 583, p50 54.1–60.6 µs, 최대 122.0 µs). 넷의 QUERY_QP 합은 rain debugfs 셈의 차이(69 993)와 맞음. `b3_h_rain_ro`(경합 셀)는 설정에서 멈춤: 응답 쪽 `setup_error="loopback READ self-check"`(본 반복 전), 보내는 쪽은 그 때문에 `nic_error="control receive"`, hog는 `HOG_DONE`(3.42 s). 실행기가 `STOP_nic`를 쓰고 `b3_h_rain_so`를 건너뜀(`skipped.txt`). 새 mlx5 줄 0, rain 펌웨어 명령 실패 셈 31 → 31, `cmd_err` 2 → 2 `[측정]` | `results/20261009_feasibility/b3/`, `STOP_nic` |
| 2026-10-09 | 경합 셀 멈춤의 진단: 자체 시험은 무늬를 스택 변수(페이지 가능 메모리)에서 `cudaMemcpy` H2D로 fence 낱말과 window 경계 낱말에 쓴 뒤 곧바로 NIC 루프백 READ로 읽는다(첫 빌드의 925–934줄). 페이지 가능 메모리에서 장치로의 `cudaMemcpy`는 무늬를 staging 버퍼에 옮기면 돌아올 수 있고 장치로의 DMA는 아직 끝나지 않았을 수 있다(CUDA 런타임의 동기 동작 설명) `[문서]`. hog가 GPU 메모리 대역을 채운 셀에서만 멈췄으므로 그 틈에 READ가 옛 낱말을 읽은 것으로 본다 `[추론]`(읽은 값은 첫 빌드가 적지 않아 `[미확인]`). 둘째 `cudaMemcpy`(window 경계 낱말)는 시작 전에 스트림을 동기화하므로 첫째(fence 낱말)는 이미 닿았고,
늦은 것은 같은 할당의 경계 낱말(same=1)이었을 가능성이 크다 `[추론, 다시 검토 S1]`. kv의 errno 28은 앞선 다른 호출이 남긴 값이다(이 실패는 값 비교라 errno가
없음; 보내는 쪽 kv도 시스템 호출 실패가 없는 수신 끝에서 같은 errno 28을 적음) `[소스, 측정]`. 통과한 셀 넷은 영향을 받지 않는다: 자체 시험은 본 반복 전에 한 번이고 넷 모두 통과했으며, 본 반복의 판정은 그 낱말을 읽지 않는다(fence READ는 값을 보지 않음) `[소스]`. 고침: `b3v2`(빌드됨, 실행 안 함; md5 `db5541eb7195619410b2113b137ad0df`, 소스 md5 `c0e8db87` = 커밋 `78473506`의 파일; pinned 무늬, 장치 동기화, 1 ms 간격 50번까지 다시 읽기, 시도 수와 읽은 값을 kv에, errno 0). 본 반복 코드는 같음. 배포는 새 `~/rs-bundle/b3v2/`(`deploy_feas.sh <확인 파일> b3v2`), 실행기의 기본 바이너리를 `b3v2`로. `STOP_nic`를 푸는 규칙을 9.15.5에 적음 | 9.15.5, 커밋 `78473506` |
| 2026-10-09 | `b3v2`와 다시 하기 계획의 독립 검토(읽기 전용 에이전트, 커밋 `78473506` 대상): 진단은 그럴듯함(추론), 통과한 rain 셀 넷은 영향 없음(본 반복은 그 낱말을 읽지 않고 검사 커널은 [0, L.total)만 봄), 고침은 맞고 본 반복의 동작은 같음, b3v2 배포 방식 맞음, `STOP_nic` 푸는 조건 1–4가 파일에서 모두 참(이 검토가 조건 2), 다시 하기와 summ_feas의 묶음 맞음, md5 확인. 막는 것 없음; 낮음 S1–S8을 문서와 스크립트에 반영(S2는 한계로 적고 바이너리는 그대로). 판정: "b3v2 and the rerun plan: ready to run" | 커밋 `8bc6d6af` |
| 2026-10-09 23:07 | 메인 세션이 `b3v2`를 배포(새 `~/rs-bundle/b3v2/`): rain과 sunny 같음, 원본과 같음, 기존 파일 그대로(rain 331, sunny 383개). 확인 파일 끝 줄이 "source at compile: not recorded"다: `b3v2`의 소스 md5는 컴파일 때 적지 않았다(출처의 빈칸). 그 소스는 `c0e8db87` = 커밋 `78473506`의 파일임을 b3v2 검토가 빌드, 파일, 커밋의 시각으로 확인했고, 그 사실을 나중에 `out/b3v2/build_src.txt`에 "나중에 적음"으로 남겼다. `b3v3`부터는 빌드 단계가 컴파일 때 소스 md5를 적는다 | `agent_restore/deploy_check_b3v2.txt` |
| 2026-10-09 23:07 | 메인 세션이 9.15.5의 조건 1–4를 스스로 확인하고(응답 쪽 kv는 `setup_error`뿐, 두 노드에 남은 시험 프로세스 0, B3r의 새 mlx5 줄 0, 다른 넷에 오류 없음) `STOP_nic`를 `STOP_nic.cleared-20261009-230739`로 옮김 | `results/20261009_feasibility/STOP_nic.cleared-20261009-230739` |
| 2026-10-09 23:07–23:08 | hold `B3one-b3_h_rain_ro`(`b3v2`, 3 200반복, `RS_LAST_KB=4096`, hold 36 s): 자체 시험 fence와 same 시도 1/1, 읽은 값 둘 다 무늬 `0x7273647261696e32`(첫 빌드의 멈춤 진단과 맞음). 그러나 고리 도중 응답 쪽이 `nic_error="QUERY_QP cap of the cell reached"`(exit 3)로 멈춤; 보내는 쪽은 "the peer reported an error"(exit 3), hog `HOG_DONE`(2 135회 × 4 GiB, 29.45 s), 셀 29.8 s. rain debugfs QUERY_QP 증가 정확히 20 000(5 701 339 → 5 721 339; 상한이 지켜짐). 그 출구는 한 반복 수와 채점 수를 적지 않아 몇 반복까지 갔는지 모른다 `[미확인]`. 같은 상한 안에서 노드 사이 셀은 3 400반복을 3.97 s에 했으므로(질의 17 472) 경합은 반복을 크게 늦추고 반복당 질의를 늘린 것으로 본다 `[추론]`. 새 mlx5 줄 0, 펌웨어 명령 실패 31 → 31. 실행기가 새 `STOP_nic`를 씀(예산 멈춤), `b3_h_rain_so`와 B3s는 돌지 않음 `[측정]` | `results/20261009_feasibility/b3_rerun1/`, `STOP_nic` |
| 2026-10-09 | 예산 멈춤의 결정(판정 기준은 그대로): 상한 20 000은 그대로(rain의 새는 명령 slot), 경합 셀만 `RS_QUERY_BUDGET=19000`(반복 경계에서 고리를 마치고 한 반복까지로 판정; 상한까지 1 000이 남아 한 반복의 최대 400보다 큼), `x`, `s` 셀은 3 200반복 그대로. 노드와 순서마다의 실패율 95% 상한은 3/(3 200 + 경합 셀의 채점 수)로 다시 적음(0.0625%–약 0.094%). 미리 반복 수를 줄이는 대신 예산을 쓴 이유: 경합에서의 반복당 질의 수를 잴 자료가 없음(그 출구가 진행을 적지 않음). 그래서 `rs_drain_test` `b3v3`을 만듦(빌드됨, 실행 안 함; md5 `62fed1fd2104cdfe92b3c50defcc0093`, 소스 `bcf58d50` 컴파일 때 기록): 모든 출구에서 `progress_*`, `RS_QUERY_BUDGET`, 끝에 `budget_stop`과 반복당 질의 평균. 예산이 꺼지면 고리는 `b3v2`와 같음. 배포는 새 `~/rs-bundle/b3v3/`, 실행기 기본 `b3v3`, hold가 경합 셀에만 예산을 넘김. 예산 멈춤의 `STOP_nic` 푸는 단계는 9.15.5 | 9.15.3, 9.15.5, 이 커밋 |
| 2026-10-09 | `b3v3`과 경합 셀 계획의 독립 검토(읽기 전용 에이전트, 커밋 `31092b76` 대상, 실행과 빌드와 ssh 없음): 판정 "b3v3 and the h-cell plan: ready to run", 막는 문제 없음. 확인한 것: 예산이 꺼지면 고리가 `b3v2`(와 첫 빌드의 채점 고리)와 같음; 예산 검사는 반복 시작(탐침 커널 전)에 있고 질의 수에 처음 질의가 들어가 debugfs 셈과 맞음; 한 반복은 최대 400(`boundary`의 대기 둘 × 200)이라 최대 18 999 + 400 = 19 399 < 20 000; 멈추는 때는 질의 수로만 정해짐; 오류 출구의 진행 기록; 실행기의 환경 전달과 `b3_rerun` 번호(`b3_h_rain_ro`는 `b3_rerun2/`, `b3_h_rain_so`는 `b3_rerun1/`); 상한 3/3 200 = 0.09375%, 3/4 800 = 0.0625%; 상한 멈춤의 풀기 조건 1–4가 파일과 맞음(조건 2의 독립 검토가 이 검토); md5(`b3v3` `62fed1fd`, 컴파일 때 소스 `bcf58d50` = 커밋 `31092b76`의 파일, `b3v2` `db5541eb` 그대로). 낮음, 반영(바이너리는 그대로, 다시 빌드하지 않음): U1(정상 끝은 `progress_*`가 아니라 `iterations_done` 등을 씀 → 9.15.5 문구; 소스 주석은 md5를 지키려고 둠), U2(반복당 질의 평균은 `early`, `boundary`를 뺀 주 대기만 → 계획에는 `query_qp_total / iterations_done`), U3(상한 20 000에 닿은 `nic_error` 멈춤은 이제 "상한 멈춤"으로 부르고 `budget_stop=1`("예산으로 끝남", 정상 끝, STOP 없음)과 가름; 앞 행의 "예산 멈춤"은 상한 멈춤을 뜻하며 고치지 않음; 9.15.3의 "넘으면"은 "19 000 이상이면"), U4(9.15.5의 `b3v2` 문단에 `b3v3` 안내), U5(`hold_feas.sh`가 `x`, `s` 셀과 smoke에 빈 `RS_QUERY_BUDGET`을 넘겨 호출 쪽 환경을 막음), U6(`build_feas.sh b3`는 `B3OUT`이 있어야 하고 이미 빌드가 있는 폴더는 거절: 기록된 `b3`, `b3v2`, `b3v3`을 덮지 않음), U8(예산으로 끝난 경합 셀은 순서 탐침 자료가 거의 없음 → 9.15.3). 정보: U7(watchdog 스레드가 진행 값을 읽는 경합과 kv 동시 쓰기는 x86-64와 glibc에서 무해; `fclose` 뒤 watchdog의 옛 틈은 무시할 만함). 스크립트 고침 뒤 `bash -n` 통과(실행 안 함) | 9.15.3, 9.15.5, `feas/hold_feas.sh`, `feas/build_feas.sh`, 이 커밋 |
| 2026-10-09 23:25 | `b3v3` 배포(메인 세션, 새 `~/rs-bundle/b3v3/`). 확인 파일(23:25:29)에 rain == sunny, source == deployed, 그 밖의 파일 그대로(rain 332, sunny 384), md5 `62fed1fd`, 컴파일 때 소스 `bcf58d50` `[측정: 이 에이전트가 확인 파일을 다시 읽음]`. 메인 세션이 상한 멈춤의 풀기 조건 1–4를 확인하고(`b3_rerun1`의 kv에 `watchdog`, `cuda_error` 없음, 남은 시험 프로세스 0, 새 mlx5 줄 0, 펌웨어 명령 실패 31 → 31) `STOP_nic`를 옮김 | `$SCR/agent_restore/deploy_check_b3v3.txt`, `results/20261009_feasibility/STOP_nic.cleared-20261009-232537` |
| 2026-10-09 23:25:37–23:26:43 | hold `B3one-b3_h_rain_ro`(`b3v3`, 3 200반복 상한, `RS_LAST_KB=4096`, 질의 예산 19 000; hold 35 s): 예산으로 끝남(`budget_stop=1`), 3 046반복, QUERY_QP 19 004(rain debugfs 증가도 19 004), 채점 fence 0/1 524, `early` 늦은 낱말 0/191, `boundary` 0/190, 경계 덮기 1.000, rmsn = M까지 p50 1 075.6 µs, 자체 시험 1/1, hog `HOG_DONE`(2 045 round, 28.18 s) → 미결(`valid=0`, exit 4). 새 mlx5 줄 0, 펌웨어 명령 실패 31 → 31, `cmd_err` 2 → 2 `[측정]` | `results/20261009_feasibility/b3_rerun2/`, `hold_B3one-hro2.out` |
| 2026-10-09 23:26:43–23:27:49 | hold `B3one-b3_h_rain_so`(같은 설정, hold 34 s): 예산으로 끝남, 3 055반복, QUERY_QP 19 000(debugfs 19 000), 채점 fence 0/1 527, `early` 0/191, `boundary` 0/191 → 미결. 새 mlx5 줄 0, 펌웨어 31 → 31 `[측정]` | `results/20261009_feasibility/b3_rerun1/`, `hold_B3one-hso.out` |
| 2026-10-09 23:27:49–23:30:06 | hold `B3s`(`b3v3`, sunny가 응답 쪽, hold 104 s): `x`, `s`의 `ro`, `so` 넷 통과(각 0/1 600, 대조 200/200, QUERY_QP 12 025–17 433), `b3_h_sunny_ro` 통과(0/1 600, `early` 22/200, `boundary` 13/200, QUERY_QP 16 969, 예산에 닿지 않음), `b3_h_sunny_so` 미결(0/1 600, `early` 23, `boundary` 7 < 10, QUERY_QP 16 910). 여섯 셀 모두 자체 시험 1/1. rain debugfs QUERY_QP 증가 0(응답 쪽이 sunny), 새 mlx5 줄 0, 펌웨어 31 → 31 `[측정]` | `results/20261009_feasibility/b3/`, `hold_B3s.out` |
| 2026-10-09 23:30:44–23:34:05 | 미결 셀을 한 번씩 다시(9.15.3의 규칙, hold 셋, 각 34–36 s): `b3_h_rain_ro` → `b3_rerun3/` 예산으로 끝남 3 054반복(QUERY_QP 19 005), 0/1 527, 대조 0/191, 0/190 → 미결; `b3_h_rain_so` → `b3_rerun2/` 3 058반복(19 006), 0/1 529, 대조 0/191, 0/191 → 미결; `b3_h_sunny_so` → `b3_rerun1/` 통과(0/1 600, `early` 19, `boundary` 10). 세 hold 모두 새 mlx5 줄 0, 펌웨어 31 → 31, `cmd_err` 2 → 2, rain debugfs 증가는 kv의 `query_qp_total`과 같음 `[측정]`. `mlx5_new_<hold>.txt`는 hold 이름마다 하나라 다시 한 hold가 첫 hold의 파일을 덮었다. hold마다의 줄 수는 각 `hold_*.out`의 "new mlx5 kernel lines" 줄에 남아 있다 | `results/20261009_feasibility/b3_rerun1/`–`b3_rerun3/`, `hold_B3one-rep-*.out` |
| 2026-10-09 | B3 상태(이 에이전트가 원자료에서 다시 셈, `summ_feas.py`): rain `ro`, `so` 열림(경합 셀이 두 번 다 미결), sunny `ro`, `so` 통과(채점 4 800씩, 상한 0.0625%), B3 결론 "열림". 본 셀 폴더의 모든 실행에서 채점 fence 실패 0/23 707(유효 여부와 무관한 합), 모든 셀의 `nofence`도 실패 0. 메인 세션의 판단(rain 경합에서는 대조가 힘을 잃어 이 방법으로 유효해질 수 없음, sunny 경합은 약 10%)과 함께 사용자에게 올림: B3은 사용자 결정 대기. 대조가 0인 까닭의 추론과 미확인은 9.15.3 결과. `summ_feas.py` 고침: 앞 실행 목록에서 오류 출구를 "error ... (no verdict)"로 적음(전의 "FAIL"은 `nicFail`이 쓰는 `result=FAIL`이지 fence 실패가 아님), 모든 실행의 합 줄을 더함, 실패율 상한은 통과한 묶음에만 적음. 이 고침으로 `SUMMARY.txt`를 다시 만듦(23:39, 원자료는 그대로) | 9.15.3, [DESIGN_POLICY.md](DESIGN_POLICY.md) 5절 B3, `feas/summ_feas.py` |
| 2026-10-11 | 사용자 결정(메인 세션이 전함): "4셀만 제대로 확인 후 다시 결정해보자". 경합 셀 넷만 다시 확인하고 그 뒤 B3을 다시 정함; 그때까지 B3은 열림, 무장 조건 "window는 strict" 유지, `x`, `s` 셀은 다시 하지 않음, 판정 기준 그대로. 옛 경합 셀(`b3_h_*`)과 그 실행은 그대로 두고 "다른 프로세스 hog, rain에서 대조의 힘 없음"으로 적고 묶음에서 뺌. 설계(빌드 전): 진단(판정 없음, `b3_diag/`, 노드마다 hog 없음, 다른 프로세스 hog, 프로세스 안 hog 각 320반복, 복사 시작 시각을 event로 잼)과 새 경합 셀 `b3_m_*`(응답 프로세스 안 낮은 우선순위 stream의 hog, 사본 stream은 높은 우선순위), 미리 정한 진단의 읽기, 노드마다의 관문, 다시 하기 규칙, 충돌 표 | 9.15.3 |

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
