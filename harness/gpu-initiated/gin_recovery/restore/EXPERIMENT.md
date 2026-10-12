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
| 마지막 갱신 | 2026-10-09, 초안: 설계(9.1–9.8절), 필요한 hook(9.9절). 사용자 결정으로 감지와 반응을 나눈 정책 설계와 통합 상호작용 표, 막는 문제를 따로 문서(`DESIGN_POLICY.md`)로 옮겼다가 2026-10-11 사용자 결정으로 9.10–9.11절에 다시 합침. 충돌이 남은 동안 구현 없음(시제품 멈춤, 9.13절). 사용자 결정(2026-10-09): B4는 (나)(검토 3과 재확인: 풀리지 않은 충돌 없음), B1–B3은 실행 가능성 시험(9.15절, 채점 안 함; 설계와 코드의 독립 검토 반영). 시험 결과(2026-10-09): B2 해결 A, B1 초기화 재생이 이 범위에서 됨, B3 열림(rain의 GPU 경합 셀이 두 번 다 미결, 사용자 결정 대기). 2026-10-11: 사용자 결정으로 경합 셀 넷을 같은 프로세스 안의 hog로 다시 해 B3의 drain 확인이 두 노드, 두 순서 모두 통과. 같은 날 사용자 결정으로 B3을 닫음: 복원 대상 window는 런타임이 strict를 강제(9.10.8절), 정상 경로 비용은 9.15.6에서 잼: 두 노드 모두 잴 만한 차이 없음. 같은 날 사용자 결정: 복원을 켤 수 없으면 `ncclGinRestoreResume`이 이유와 함께 오류(모든 rank 같음). 질문, 가설, 예측, 셀, 기준의 초안(DRAFT)과 구현 계획(9.14절). 같은 날 작업 묶음 1(strict 강제와 설정 합의) 구현, 빌드됨, CPU 시험함, 독립 검토(막는 문제 없음); 작업 묶음 2는 충돌 확인에서 설계가 풀지 않은 물음 둘로 멈춤(12절). 2026-10-12 사용자 결정(Resume은 모든 rank가 부르고 bootstrap으로 모아 같은 결과, 9.10.8절)으로 작업 묶음 2 구현, 빌드됨, CPU 시험함, 독립 검토(막는 문제 없음). 작업 묶음 3은 충돌 확인에서 멈춘 뒤 사용자 결정(측 표 포인터를 GPU 문맥 끝에, 판 그대로)으로 구현, 빌드됨, CPU 시험함, 기계어 비교, 독립 검토(막는 문제 없음). 작업 묶음 4는 메인 세션의 보고 뒤 |

**정책 설계의 자리.** 장애 반응 정책(fail-fast와 hold-for-restore), 기존 장치와의 통합 상호작용 표, gpu-detect 계층에 넣을 변경, 막는 문제와
그 독립 검토는 9.10–9.11절에 있다(2026-10-09에 따로 쓴 `DESIGN_POLICY.md`를 2026-10-11 사용자 결정으로 합침, 12절). 사용자 결정(2026-10-09): 충돌이 남아 있는 동안 아무것도
구현하거나 빌드하지 않는다.

표시: `[측정]` 원자료나 시행별 표, 시험 출력에서 확인, `[소스]` 코드에서 읽음, `[문서]` 외부 문서나 논문의 설명, `[추론]` 해석,
`[미확인]` 확인 안 함.

이 문서의 코드는 함수 이름과 줄 번호로 가리킨다. 따로 적지 않으면 파일은 `src/transport/net_ib/gdaki/gin_host_gdaki.cc`이고, 줄 번호는
gin-remaining `hr` 빌드 트리(세션 스크래치 `agent_ts2hr/nccl-src`, 2026-10-09 읽음)의 것이다. gpu-detect `hw` 트리(`agent_gd/gin/nccl-src`, diff md5
`be0ea9ed`)에서는 이 파일의 줄이 밀린다. 둘을 함께 적은 표는 9.11절이다. 장치 쪽은
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
- 붙잡음(hold): 생존 rank의 helper가 죽은 상대 하나를 거절하지 않고 복원을 기다리는 것. 상태는 HELD, COMMITTING, PUBLISHED(9.10.7절).
  복원 시한(`NCCL_GIN_RESTORE_MS`)이 끝나거나 실패하면 앞 빌드의 거절로 돌아간다(fallback).
- 초기화 기록(init transcript): 논리 rank r이 처음 초기화 때 받은 모든 집합 교환(bootstrap, GIN collComm)의 결과. 예비 프로세스가 초기화를 다시 할 때
  이것을 받아 쓴다(초기화 재생).

예측 id, 셀 이름, 빌드 키는 원자료를 찾는 키로만 괄호나 표의 열에 둔다.

| 빌드 키 | 내용 | 쓰는 곳 |
|---|---|---|
| `rs` | 이 실험의 연구 빌드: gpu-detect `hk` 위에 9.9절의 계층(지금은 작업 묶음 3까지, 12절) | 새 셀 |
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
5. 복원을 켤 수 없는 설정에서 모든 rank의 `ncclGinRestoreResume`이 같은 이유의 오류를 돌려주고, 켤 수 있는 설정에서 복원 대상 window가 strict로 등록되는가
   (2026-10-11 사용자 결정, 9.10.8절). strict의 정상 경로 비용은 실행 가능성 단계에서 두 노드 모두 잴 만한 차이가 없었다(9.15.6).

## 2. 가설

초안이다(DRAFT). pilot 뒤에 고치고 사전 등록에서 고정한다(실험 작업 절차의 2절). 짧은 부호를 새로 만들지 않고 내용으로 부른다. 3절 표의 "찾는 키"는
나중에 예측 표 파일과 채점기가 원자료를 찾는 이름일 뿐이다.

| 가설 | 다음이 관측되면 틀린 것이다 |
|---|---|
| 대기 붙잡기: 무장된 상대가 강한 죽음 증거로 죽으면 생존 rank는 거절하지 않고 그 상대를 붙잡으며, 상대를 모르는 대기를 포함한 생존 rank의 대기가 복원 시한 안에 오류 없이 붙잡혀 있다 | 복원 셀에서 생존 rank의 대기가 오류로 끝나거나, application에 비동기 오류나 거절이 닿는 시행이 있다 |
| 정확한 복원: 체크포인트(입력 멈춤으로 정한 절단점), 보낸 쪽 로그, 응답 쪽 누적 실행 수로 다시 보내기를 거르면 결정적인 workload의 최종 데이터가 장애 없는 실행과 비트 단위로 같다 | 복원 셀에서 어느 rank의 최종 데이터나 받은 칸이 호스트 기준과 다른 시행이 있다 |
| 생존 rank는 되돌아가지 않는다 | 생존 rank의 단계 실행 수가 1이 아닌 단계가 있다 |
| 복원이 시한 안에 안 되면 지금의 거절과 degraded로 돌아간다 | 예비 프로세스가 없는 셀에서 대기가 복원 시한 + 2 s 근처에 오류로 풀리지 않거나, 붙잡힌 채 남는다 |
| 켤 수 없으면 알린다(2026-10-11 사용자 결정, 9.10.8절): 복원을 켤 수 없는 설정에서는 모든 rank의 `ncclGinRestoreResume`이 같은 이유의 오류를 돌려주고, 켤 수 있는 설정에서는 hold 프로세스의 모든 GDAKI window MR이 strict로 등록된다 | 켤 수 없는 설정에서 오류 없이 fail-fast로 넘어가거나 rank마다 다른 결과가 나오는 시행, 켤 수 있는 설정에서 strict가 아닌 window 등록이 있는 시행이 있다 |
| 정상 경로 비용이 작다: 로그, 체크포인트, 게이트 뒤 키 다시 읽기, fail-fast의 분기 하나가 지연과 단계 시간에 작게 남는다 | 3절에서 pilot 뒤에 수로 고정할 문턱을 넘는다 |

## 3. 사전 예측 (측정 전에 작성)

초안이다(DRAFT). 문턱과 n은 pilot 뒤에 정하고, 고정은 예측 표 파일, `PREREG.txt`, 태그로 한다. 판정은 유효한 시행만으로 센다(8절). 판정식의 "≥ k/n"은
유효 시행 n개 가운데 그 조건이 참인 시행이 k개 이상이라는 뜻이다.

| 무엇을 예측했나 | 셀 | 시행마다의 조건 | 판정식(초안) | 근거 | 찾는 키 |
|---|---|---|---|---|---|
| 생존 rank의 상대를 모르는 대기가 풀리지 않음 | `rs4_kill3@rs` | 모든 생존 rank에서 `waitSignal`이 문턱 이상의 값으로 돌아옴, 비동기 오류 0, 거절 WARN 줄 0 | ≥ 9/10 | 9.2, 9.10.7절 `[소스, 추론]` | `wait_held` |
| 최종 데이터가 기준과 같음 | `rs4_kill3@rs` | 모든 rank의 최종 상태와 받은 칸이 호스트 기준과 비트 단위로 같음 | ≥ 9/10 | 9.6, 9.7절 | `data_equal` |
| 생존 rank는 다시 실행하지 않음 | `rs4_kill3@rs` | 생존 rank의 모든 단계 실행 수 = 1 | 10/10 | 생존 rank는 붙잡기만 함 | `no_reexec` |
| 되살린 rank가 끝까지 감 | `rs4_kill3@rs` | 되살린 rank가 마지막 단계를 끝내고 exit 0 | ≥ 9/10 | 9.3절 | `revived_done` |
| 다시 보내기 억제가 정확함 | `rs4_kill3@rs` | 통로마다 억제한 메시지 수 = 생존 rank의 누적 실행 수 − 체크포인트 때의 실행 수 | ≥ 9/10 | 9.6절 | `suppress_exact` |
| 복원 시간이 시한 안 | `rs4_kill3@rs` | 첫 죽음 판정 줄부터 마지막 생존 rank의 게이트 재개까지 ≤ T(초안 T = 10 000 ms, pilot 뒤 고정) | ≥ 9/10 | 9.3절 어림 `[추론]` | `restore_time` |
| 체크포인트 멈춤 중 kill도 앞 체크포인트에서 복원 | `rs4_kill3_ckpt@rs` | 위 넷(대기, 데이터, 재실행 없음, 끝까지)이 모두 참이고 쓰인 체크포인트가 kill 앞에 확정된 것 | ≥ 4/5 | 9.4절 | `ckpt_kill` |
| 같은 GPU의 다른 rank가 죽어도 같음 | `rs4_kill1@rs` | 위 넷이 모두 참 | ≥ 4/5 | 배치의 대칭 `[추론]` | `kill_other` |
| 예비 프로세스가 없으면 fallback | `rs4_kill3_nospare@rs` | 상대를 모르는 대기가 복원 시한 + 2 000–2 500 ms 안에 오류로 풀리고 fallback 줄이 있음 | ≥ 4/5 | 9.10.5절 fallback | `fallback_nospare` |
| 대조: 복원이 없는 빌드는 degraded로 모두 풀림 | `rs4_kill3@hk` | 죽음 판정 + 2 000–2 500 ms 안에 생존 rank의 대기가 오류로 풀림 | ≥ 4/5 | gin-remaining의 degraded 결과 `[측정: 그 실험]` | `control_degraded` |
| 장애 없음: 데이터 같음, 복원 0, 멈춤이 짧음 | `rs4_none@rs` | 최종 데이터 같음, 복원 0, 체크포인트마다 생존 rank의 입력 멈춤 ≤ 5 ms | 5/5 | 9.4절 `[추론]` | `none_clean` |
| hold 프로세스의 window는 모두 strict | `rs4_none@rs`, `rs4_none_off@rs` | hold 셀: 라이브러리의 등록 보고에서 모든 GDAKI window MR이 강제됨; 복원 끈 셀: 강제 0 | 각 5/5 | 9.10.8절 | `strict_forced` |
| 켤 수 없으면 모든 rank가 같은 이유의 오류 | `rs4_refuse_symgin@rs`, `rs4_refuse_gintype@rs`, `rs4_refuse_restoreoff1@rs` | 모든 rank의 `ncclGinRestoreResume`이 오류를 돌려주고 이유 문자열이 rank 사이에서 같으며, 오류 없이 fail-fast로 넘어간 rank가 없음 | 셀마다 3/3 | 2026-10-11 사용자 결정 | `refuse_reason` |
| 기존 셀의 회귀 없음 | gin-remaining과 gpu-detect의 회귀 셀`@rs` | 그 실험들의 원래 판정식(복원 계층이 켜져 있어도 fail-fast 결과가 같음) | 원래 기준 | 9.10.6절 (다) | `regression` |
| 로그의 비용 | `lat_4k`, `lat_256k`(로그 켬 대 끔)`@rsp` | 9.15.6과 같은 틀(6 대 6 섞기, 완전 갈림, 같은 값은 갈리지 않음) | 문턱은 pilot 뒤 | 9.5절 어림 | `cost_log` |
| 무장 전 hold의 비용 | `lat_hold_unarmed@rsp` | 같은 틀 | 문턱은 pilot 뒤 | 9.10.6절 (다) | `cost_unarmed` |
| fail-fast의 분기 비용 없음 | `lat_ff_branch`(이 계층 대 `hk` 운영 빌드) | 같은 틀, 갈리지 않음을 예측 | 갈리지 않음 | 9.11.5절 결정 (나)의 (4) | `cost_ff` |

## 4. 범위

**포함.**
- 9절의 설계: 복원 중 대기 유지, 예비 프로세스와 끝점 간접화, 체크포인트, 송신 쪽 로그, 재실행과 중복 억제, 결정성 요구, 시험 workload와 판정 기준.
- 9.9절 hook 목록(gpu-detect `hw` 위의 계층)과 9.10–9.11절의 정책 설계와 상호작용 표.
- 시제품(9.13절): 체크포인트와 로그의 자료 구조, 복원 계획과 적용, 중복 억제를 독립 라이브러리로 만들고 CPU 모의로 단위 시험한다. 시험 프로그램
  [gin_rs.cu](gin_rs.cu)는 `hr` 헤더로 빌드만 한다.

**제외.**
- 실제 GPU 고장, 노드 고장, 하드웨어 예비 장비: 주입할 수 없다. 장애는 프로세스 kill(SIGKILL)만이다.
- NVSHMEM: 이 실험은 GIN만 다룬다.
- 동시에 둘 이상 죽는 것, 복원 중 다른 rank가 죽는 것, 예비 프로세스가 복원 중 죽는 것: fallback(9.2절)으로만 다룬다.
- GIN 밖의 NCCL 통신(collective, NCCL P2P, LSA load/store)으로 되살린 rank와 주고받는 것: 로그되지 않는다. 복원한 communicator에서는 쓸 수 없다(9.11.8절 X2).
- 복원 뒤 새 GIN 자원(window 등록, devComm 생성)을 만드는 것: GIN collComm 고리가 끊겨 있다(9.11.5절 A3).
- 실제 link down, flap, 재부팅, 드라이버 재적재: 하지 않는다.

## 5. 테스트베드와 버전

| 항목 | 값 | 확인 방법과 날짜 |
|---|---|---|
| 노드, NIC, GPU, CUDA | gin-remaining과 같다: rain(Quadro RTX 5000), sunny(RTX A4000), ConnectX-6, CUDA 12.8 | `../remaining/EXPERIMENT.md` 5절 `[문서]` |
| 랭크 배치 | 랭크 4개, GPU마다 프로세스 둘(`NCCL_MULTI_RANK_GPU_ENABLE=1`, gin-multirank처럼): rain에 0과 2, sunny에 1과 3. rank 3의 예비 프로세스는 sunny GPU의 셋째 프로세스, 짝은 rank 2(rain) | 계획 |
| 라이브러리 | gpu-detect `hk` + 이 계층(`rs`). 지금은 작업 묶음 3까지(빌드됨, 실행 안 함; 12절). 이 라이브러리와 쓰는 프로그램은 이 계층의 헤더로 빌드(9.11.5절) | 9.9절, 9.14절 |
| 시제품 빌드 | rain, g++ (CPU 시험), nvcc 12.8(빌드만) | 9.13절 |

## 6. 변수

- **독립변수.** 빌드(이 계층의 연구 빌드 `rs`, 운영 빌드 `rsp`, 대조 `hk`), 장애(rank 3 kill, rank 1 kill, 체크포인트 멈춤 중 kill, 예비 프로세스 없음),
  kill 시점(단계 번호와 단계 안의 지연), 켤 수 없는 설정(symmetric 커널의 GIN 켬, GIN 종류가 3이 아님, rank 사이에서 `NCCL_GIN_RESTORE`만 다름), 체크포인트
  간격(단계 수), 메시지 크기, 로그 켬과 끔.
- **종속변수.** 생존 rank의 대기 결과와 끝난 시각, 비동기 오류와 거절 줄, 최종 데이터 비교, 단계 실행 수, 억제한 메시지 수, 다시 넣은 로그 크기, 복원
  단계별 시각(죽음 판정, 활성화, 초기화 재생, 상태 적용, 재연결, 게이트 재개), 체크포인트마다 입력 멈춤 시간과 단계 시간, `ncclGinRestoreResume`의 반환과
  이유 문자열, 강제된 window 등록 수, put 지연.
- **통제변수.** hold 프로세스의 고정 설정(9.10.8절의 결정): `NCCL_GIN_FAULT_POLICY=hold`, `NCCL_GIN_RESTORE=1`, `NCCL_SYM_GIN_KERNELS_ENABLE=0`,
  `NCCL_RMA_DISABLE=1`, `NCCL_GIN_TYPE=3`, GIN 연결 FULL, runtime connect 켬, NVLS 끔; 투명 복구 켬, QP 감시 10 ms(무장 조건);
  2026-10-12 더함(작업 묶음 2 검토): `NCCL_NUM_RMA_CTX=0`(host RMA 문맥은 기본 1이고 `NCCL_RMA_DISABLE`은 proxy만 끄므로, 없으면 Resume이 "host RMA is on"으로
  거절 `[소스: init.cc 2798, rma/rma.cc 19–21]`), GIN 연결 하나(`NCCL_GIN_NCONNECTIONS=1`; 기본은 이 노드의 GIN 장치 수이고 rain과 sunny의 수는 `[미확인]`); 복원 시한(초안
  `NCCL_GIN_RESTORE_MS` 20 000); 체크포인트 간격(초안 20 단계); window는 rain의 BAR1 때문에 하나에 24 MiB 이하(9.15.6); 시행마다 프로세스를 새로 띄움.

## 7. 실험 셀, 반복 수, 대조군

초안이다(DRAFT). 반복 수는 pilot 뒤에 고정한다. 배치: 랭크 4개, GPU마다 프로세스 둘(rain에 0과 2, sunny에 1과 3; B2에서 lsaSize 1 확인), rank 3의 예비
프로세스는 sunny GPU의 셋째 프로세스, 짝은 rank 2(rain).

| 셀 | 조건 | 빌드와 반복 수 | 종류 |
|---|---|---|---|
| `rs4_none` | 장애 없음, 체크포인트 켬 | `@rs` 5 | 대조, 비용, strict 강제 |
| `rs4_none_off` | 같고 복원 계층 끔(`NCCL_GIN_RESTORE=0`, hold이지만 무장 안 함) | `@rs` 5 | 비용 기준, strict 강제 없음 |
| `rs4_kill3` | rank 3 SIGKILL(단계 중간), 예비 프로세스 있음 | `@rs` 10 | 새 셀 |
| `rs4_kill3_ckpt` | 체크포인트 입력 멈춤 중 kill | `@rs` 5 | 새 셀 |
| `rs4_kill1` | rank 1 kill(rank 3과 같은 GPU) | `@rs` 5 | 일반성 |
| `rs4_kill3_nospare` | 예비 프로세스 없음 | `@rs` 5 | fallback |
| `rs4_kill3` | 복원이 없는 빌드 | `@hk` 5 | 대조 |
| `rs4_refuse_symgin`, `rs4_refuse_gintype`, `rs4_refuse_restoreoff1` | 켤 수 없는 설정 셋(symmetric 커널의 GIN 켬, GIN 종류 proxy, rank 하나만 `NCCL_GIN_RESTORE=0`), 장애 없음 | `@rs` 각 3 | 명시적 오류 |
| gin-remaining과 gpu-detect의 회귀 셀 | 복원 계층이 있는 빌드의 fail-fast | `@rs` 각 5 | 회귀 |
| `lat_4k`, `lat_256k` | 로그 켬 대 끔, 9.15.6의 섞기 | `@rsp` 각 팔 6 | 비용 |
| `lat_hold_unarmed` | 4 KiB, 256 KiB: hold이지만 무장 전 대 fail-fast | `@rsp` 각 팔 6 | 비용 |
| `lat_ff_branch` | 4 KiB, 256 KiB put과 4 KiB get: fail-fast에서 이 계층 대 `hk` 운영 빌드 | `@rsp`, `@hkp` 각 팔 6 | 비용 |

## 8. 제외 기준과 중단 기준

초안이다(DRAFT). 틀은 gin-remaining 8절과 이 실험의 실행 가능성 시험(9.15.5)의 STOP 규칙을 따른다.
- **제외(채점에서 빼고 채움).** GIN 사용자 문맥 전에 끝난 시행(장애가 들어가지 않음); kill이 첫 확정 체크포인트 전(복원할 체크포인트 없음); 예비 프로세스가
  활성화 전에 시작에 실패함(따로 셈); hold를 시작할 때 링크가 한가하지 않았거나 응답 쪽 GPU에 다른 사용자의 compute app이 있었음(시간 나눔); smoke와 pilot은
  늘 제외. 제외한 시행은 이유와 함께 12절과 결과표에 따로 센다.
- **중단(그 hold의 남은 시행을 멈추고 올림).** CUDA 메모리 오류(STOP_cuda), 새 mlx5 명령 오류나 rain 펌웨어 명령 실패의 증가(STOP_mlx5), 시행 뒤 남은 프로세스
  (STOP_left), kv의 설정 오류나 NIC 오류(STOP_nic). 시행마다 QUERY_QP 상한(초안 20 000, rain의 새는 명령 slot). rain의 BAR1 Free가 128 MiB보다 작으면 시작하지
  않음. 이름으로 끄지 않고 실행기가 기록한 PID만 끔(예비 프로세스 포함). 실제 link down, 재부팅, 드라이버 재적재는 하지 않음.

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
  키 읽기 자리는 이 원칙과 충돌했다(9.11.12절 B4). 사용자 결정(2026-10-09, (나)): 키를 게이트 진입 뒤에 다시 읽는 것은 hold 정책의
  communicator에서만 하고, fail-fast의 빠른 경로는 키 읽기 자리를 그대로 두고 측 표 포인터의 분기 하나만 더한다(9.6절, 9.9절 DV3).
- 기존 라운드 기계를 다시 쓴다. 생존 rank 쪽 복원 라운드는 `ncclGinRecoverPrepare`(2143), `ncclGinRecoverCommit`(2334),
  `gdakiTsRepostApply`(4692)를 상대 하나에 대해 그대로 부르고, 다른 것은 끝점을 바꾸는 것과 "모든 옛 WQE가 실행됨"으로 계획을 만드는 것뿐이다.

### 9.2 복원 중 대기 유지와 시한 (생존 rank)

**상태.** 생존 rank의 helper는 상대 r마다 상태 하나를 둔다: `OFF`(복원 꺼짐), `ARMED`(r의 확정된 체크포인트가 있고 r로 가는 로그가 그 절단점부터
빠짐없음), `HELD`, `COMMITTING`, `PUBLISHED`(붙잡음: 복원 라운드의 커밋 지점 전, 게시 중, 게시 뒤 예비 프로세스의 RESTORED 전), `FALLBACK`(복원 포기, 앞 빌드의
거절로), `CANCELLED`(abort, shrink, revoke, 정리). 전이와 무장의 원문은 9.10.4절과 9.10.7절이다.

**죽음 판정에서.** 지금은 FIN이 보이면 `gdakiTsSocketLost`(3746–3777)가 `deadJudged`를 세우고, helper 루프(6095–6101)가 바로
`gdakiTsDecline(..., GDAKI_UA_PEER_DEAD)`를 부른다. 거절은 QP를 ERR로 보내고(4933), 그 상대의 단어와 비동기 오류를 올리고(4936–4943),
degraded를 예약하고(2828–2840), 게이트를 실패로 쓴다(4960–4964) `[소스]`. 계층은 `gdakiTsDecline` 맨 앞의 정책 hook(G2, 9.11.10절)에 hold 분기(RL1)를 둔다. 그 상대가 `ARMED`이고
죽음의 증거가 있으면(아래) 거절하지 않고 붙잡는다(상태 HELD → COMMITTING → PUBLISHED, 9.10.7절).
- 죽음의 증거: 강한 증거(BYE 없는 FIN, 또는 1–5 s 간격의 거절 둘)만 쓴다. 라운드 안의 FIN은 지금 거절이 아니라 취소(`gdakiTsCancelRound` 5127–5146)로
  가서 상대를 "모름"으로 두므로, 그 경우는 다시 걸기와 탐침의 거절 둘로 죽음이 판정된 뒤 다시 줄에 선 기록의 라운드(죽음 길)나 helper 루프의 거절로 온다. 두 길 모두 G2를 거친다. 다른 거절(분류 불가, 확대 상한, 상대의
  FAIL, 펌웨어 초과, BADMAGIC 같은 약한 죽음)은 가로채지 않는다. 판단의 원문은 9.10.5절과 9.11.2절 R1이다.
- 붙잡을 때 하는 일: 상태를 맨 먼저 HELD로 두고, 범위를 모든 문맥으로 두고, 준비된 라운드를 풀고, `gdakiTsQuiesce`(4416)를 그대로 부른다(게이트 홀수, QP를 ERR로,
  개수 0, 모아 둔 WQE의 doorbell, `abandoned` 확인). `deadJudged`와 `failedPending`을 지운다. 이 모두를 `gdakiTsBusy` 안에서 한다.
  차례의 원문은 9.10.7절이다. 보내기는 게이트에서 쉬고, r의 QP를 기다리는 요청 대기와 flush는 다음 짝수 에폭까지 쉰다
  (`tsParkStable`, `gin_gdaki.h` 252–297). 상대별 단어, 칸 0, 비동기 오류, degraded 예약, 거절의 WARN 줄은 만들지 않는다(죽음 판정의 WARN 줄은 감지라서 남는다). 상대를 모르는 대기(`waitSignal`)는
  칸 0만 읽으므로 그냥 계속 돈다.
- 장치 대기의 한도: 쉬는 장치 스레드는 게이트의 `waitMs`(= `NCCL_GIN_TS_HOLD_MS`, 기본 30 000 ms, 6820) 뒤 포기한다(`tsGiveUp` → poison)
  `[소스]`. 그래서 복원 시한 `NCCL_GIN_RESTORE_MS`(초안 기본 20 000)는 `holdMs`보다 짧아야 하고, 계층은 `gdakiTsStart`(`roundMs`를 정하는 곳)에서
  관계를 확인해 어기면 복원을 끈다(시작 줄로 보임). 쉬는 스레드의 시계는 게이트가 처음 홀수가 된 때부터 가므로 실제 시한은 그것으로 줄인다
  (9.11.4절 T4).
- 시한이 지나면(`FALLBACK`): Q4 감시 스레드가 시한을 지킨다(G8). CAS(HELD 또는 PUBLISHED → TIMED_OUT)에 이기면 그 상대의 단어(PEER_DEAD), 비동기 오류,
  책임(PeerDead), degraded 예약을 CPU 쓰기로 하고, helper가 풀리면 앞 빌드의 거절(`gdakiTsDecline(..., PeerDead, GDAKI_UA_PEER_DEAD)`)로 게이트와 FAIL을
  마저 한다. degraded 시계는 시한에서 시작하므로 상대를 모르는 대기는 시한 + 2 000 ms에 풀린다. 모든 rank와 예비 프로세스에 FALLBACK(p)를 보내고, 예비
  프로세스는 BYE 없이 끝난다(9.10.7절).
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
  QP들)에 잇는다(`gdakiConnectQp` 517; 양쪽 토큰 교환은 9.11.3절 M4). GIN collComm 고리 연결(`ncclGinIbConnect`, gin.cc 231–259)과 helper 설정의
  잇기와 받기(6255–6308)도 건너뛴다(9.11.5절 A3). host RMA proxy는 상대마다 따로 IB 연결을 맺으므로 꺼 둔다(무장 조건, B1 설계 검토 T1-1). 원래 rank의 listen 주소와 다른 포트에 묶고, 설치되기 전에는 REJOIN 말고 아무것에도 답하지
  않는다(9.11.1절 D4). 활성화 전에 원래 프로세스의 PID가 없어졌는지 확인한다(같은 노드, 9.10.5절).
  생존 rank 쪽은 복원 라운드에서 자기 QP를 새 QPN에 다시 잇는다(아래).
- 범위: 생존 rank의 NCCL 핵심(collective 전송, proxy, RAS)은 예비 프로세스를 모른다. 복원한 communicator에서는 GIN 장치 통신만 된다(9.11.8절 X2).
  초기화 재생이 NCCL 핵심의 결정성에 기대는 것은 이 설계에서 가장 큰 위험이다(9.11.12절 B1).

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
   9.11.5절 A1 (3), 검토 3 W5).
8. 게시 전 확인(4708) 뒤, 커밋 지점(4713) 전에 상태 CAS(HELD → COMMITTING). 지면(감시 스레드의 시한이 이김) fallback.
   `gdakiTsRepostApply`(4692–4897)를 QP마다 `U = S, n = 0`인 계획으로 부른다(응답 쪽이 Commit 뒤 게시 전에 상대가 죽은 경우는 강한 죽음 증거가 아니라
   fail-fast다. gpu-detect가 그 길을 고친 뒤에도 그 거절에는 `pe.lostAfterCommit`가 서 있어 붙잡지 않는다, 9.10.5절과 9.10.7절): 커밋 지점(포기한
   장치 대기가 있으면 FALLBACK), PUBLISHING, `lbase += U`, 짝수 에폭 게시. 쉬던 요청 대기는 자기
   표가 `lbase`보다 작으므로 성공으로 끝난다(`tsPoll` 1086–1092) `[소스]`. 그 WQE들의 효과는 로그 적용으로 예비 프로세스의 메모리에 이미 들어 있으므로
   맞는 의미다 `[추론]`.

**시간 어림** `[추론]`: 죽음 판정은 kill 뒤 수 ms(gin-remaining의 kill 셀). 예비 프로세스 활성화와 초기화 재생(CUDA 문맥은 미리 있음: NCCL 초기화,
window 등록, devComm과 GIN 문맥, NIC 루프백 설정 3.0–10.9 ms `[문서: gin-remaining 15절]`) 0.5–3 s, 체크포인트와 로그 받기(MB 단위, TCP) 0.1 s 안팎,
복원 라운드 QP마다 수 ms. 합 1–5 s. 예비 프로세스는 rank 1이 돌고 있는 GPU를 나눠 쓰므로 시분할로 더 늦을 수 있다.

### 9.4 체크포인트

**무엇을.** 단계 hook 때의 r의 상태: (a) r이 등록한 모든 GIN window의 내용(사용자 devComm의 자원 window 포함, 9.10.8절, 2026-10-11 검토 K17), (b) application이 `ncclGinRestoreRegister`로 더 등록한 장치 버퍼,
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
   (gin-remaining의 flush 규칙과 같은 근거, 9.11.12절 B3), window와 신호 표를 GPU 안의 사본으로 복사한다(장치 안 복사).
   B3 설계 검토(2026-10-09, T3-2, T3-6, T3-8)로 정한 것: READ는 window가 아니라 측 표 안의 8바이트 fence 낱말(문맥을 만들 때 NIC 복사 경로의 strict 루프백
   MR에 등록된 다른 할당, 9.10.4절)을 읽는다. window 내용은 루프백 MR에 없다. 복사는 copy engine(r의 단계 hook에서 r의 스트림에
   `cudaMemcpyAsync` D2D)이다. QUERY_QP는 예상 drain 시각에 처음 내고 그 뒤 50 µs 이상 띄우며, 체크포인트마다 상한을 둔다(수는 B3 시험이 정함).
   멈춤 전 마지막 메시지는 신호 없는 put일 수 있으므로, 마지막의 신호 원자 연산이 앞의 쓰기를 밀어 주리라고(그 원자 연산의 PCIe 읽기가 앞의 posted 쓰기를
   앞지르지 못함) 기대지 않는다(T3-1). READ로 모자라면 대안은 `cuFlushGPUDirectRDMAWrites`(r은 단계 hook에 있어 CUDA를 부를 수 있음)다(T3-5).
4. `CKPT_RESUME(k)`: q는 짝수 에폭을 새로 게시한다(빈 라운드: `lbase` 그대로). 단 q가 그동안 r을 거절하지 않았고, 멈춤 뒤 진짜 라운드가 없었고, 게이트가
   아직 멈춤 때의 에폭일 때만이다. 아니면 그 체크포인트는 버린다(9.11.9절 C1). 생존 rank의 멈춤은 1–4의 시간이다.
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
개수 0)에서 NIC 루프백으로 세우므로 로그의 시작이 절단점과 같다(9.11.9절 C2, 검토 3 W2). 측 표 포인터만으로는 로그를 켜지 않는다(그 포인터는 hold 정책이면
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
  검사(`tsPollEnter` 365)와 `tsParkStable`(264)은 이 비트를 보지 않는다(공용 `tsWordOpen`에 넣으면 flush와 wait가 끝없이 돎, 9.11.9절 C6).
  느린 길(`tsGateEnterSlow`, 303–328)이 나가기와 쉬기 전에 예산을 보고 내지 않거나 일부만 낸다. 빠른 경로의 명령 수는 그대로다 `[추론]`. 비트는 helper만
  쓰고, 예산이 남은 동안 에폭 반쪽을 쓸 때마다 OR한다. 예산이 0이 되면 helper가 지운다.
- READ는 응답 쪽 MSN이 세는 요청 메시지라 X − P에 섞인다. 되살릴 rank의 get은 9.7절 8번의 application 요구이고, 억제 느린 길은 예산이 남은 QP에 들어온
  get을 실패로 표시해 복원을 실패시킨다(9.11.3절 M2 (c)). 0바이트 put의 NOP와 flush의 DUMP는 메시지가 아니라
  예산을 쓰지 않는다.
- 누적 실행 수는 화신마다 mod 2^24라서, 감시의 QUERY_QP(G7)와 기준 바꿈마다 증분을 더하고 복원 라운드가 2ERR 뒤 Commit 전에 한 번 더 읽는다.
- 억제한 연산은 WQE를 쓰지 않으므로 그 요청의 대기와 flush는 바로 끝난다(요청 표는 실제로 낸 WQE만 셈) `[소스: waitImplCore 1175]`.

**키 읽기 자리.** 생존 rank의 장치 코드는 rkey를 게이트에 들어가기 전에 읽는다(`raddr.key` 476, `signalKey` 1461과 1464, 게이트 501) `[소스]`. 게이트에서
쉬던 스레드는 복원 전에 읽은 옛 rkey로 보낸다. 느린 길 뒤에만 다시 읽으면 모자란다: 게이트가 홀수일 때 옛 키를 읽고 게시 뒤 빠른 경로로 들어가는 보내기가
있을 수 있다. 키 읽기를 게이트 진입 뒤로 옮겨야 하고 이는 빠른 경로의 차례를 바꾼다(9.11.12절 B4). (이 문단은 결정 전의
것이다. 결정 (나)는 키 읽기를 옮기지 않고 hold에서만 게이트 뒤에 다시 읽는다, 아래.)

사용자 결정(2026-10-09, (나)): 게이트 진입 뒤의 키 다시 읽기는 hold 정책의 communicator에서만 한다. 갈림은 측 표 포인터(DV1)가 0인지로 한다. 그 포인터는
문맥을 만드는 중(`gdakiTsStart`, `ncclGinGdakiCreateContext`가 돌아오기 전) 한 번 쓰고 그 뒤 바뀌지 않는다(9.10.4절, 검토 3 W1).
fail-fast는 키를 지금 자리에서 지금 방식(`loadConst`, L1 적중)으로 읽고, 더해지는 것은 DV2와 같은 포인터 읽기에 기대는 분기 하나와 내부 인자 하나다.
hold는 `tsGateEnter`가 참을 돌려준 뒤(빠른 길이든 느린 길이든) window rkey와 신호 rkey를, get은 원격 window rkey를 L1을 거치지 않는 시스템 범위
relaxed 읽기로 다시 읽어 보낸다(put, putValue, get 모두; 검토 3 W3, W4). 자세한 것은 9.9절 DV3와 9.11.5절 A1이다.

### 9.7 결정성 요구 (piecewise determinism)

되살린 rank의 체크포인트 뒤 실행은 (체크포인트, 호스트 덩어리, 받은 메시지)의 결정적 함수여야 한다. 이 설계가 application에 요구하는 것:
1. 신호에 대해 data-race-free: 상대가 쓴 window 자리는 그것을 덮는 `waitSignal`이 돌아온 뒤에만 읽는다.
2. 제어 흐름은 `waitSignal`의 문턱에만 기댄다. `readSignal` 값이나 도착 시각에 따라 갈리지 않는다.
3. 단일 대입: 체크포인트에서 재실행 끝까지, 다른 rank가 쓰는 window 자리는 한 번만 쓰인다. 입력을 재실행 전에 한꺼번에 넣기(9.6절) 때문이다. 같은
   자리를 다시 쓰는 workload(고리 버퍼)는 재실행의 진행에 맞춰 입력을 넣어야 하고, 그러려면 보내는 쪽이 받은 쪽의 진행을 알아야 한다(벡터 시계류).
   v1의 범위 밖이다.
4. 원격 읽기(`get`)는 체크포인트에서 재실행 끝까지 바뀌지 않는 메모리에서만. 생존 rank의 메모리가 그 사이 바뀌면 다른 값을 읽기 때문이다.
5. 되살린 rank에서 한 QP로 가는 보내기는 프로그램 차례 하나(스레드 하나 또는 coop 하나)로 낸다. 억제가 "앞의 B개"를 프로그램 차례로 세기 때문이다.
6. GIN 밖의 통신(collective, NCCL P2P, LSA, host RMA)을 되살릴 rank와 주고받지 않고, hold 정책의 프로세스는 NVSHMEM을 쓰지 않는다(9.11.8절 X6).
   host에서 띄운 NCCL 호출은 runtime connect로 상대 버퍼를 가져오는 전송을 만든다(B2 설계 검토 T2-3). host RMA는 꺼야 한다(`NCCL_NUM_RMA_CTX=0`, 9.10.4절).
7. 단계 hook은 그 rank의 커널이 끝나고 마지막 flush가 끝난 뒤에만 부른다(체크포인트 때 r의 보내기가 모두 실행됨: `P_q`가 r이 낸 수와 같음).
8. 되살릴 수 있는 rank와는 어느 방향으로도 `get`을 하지 않는다(4번보다 강함: 생존 rank의 get이 죽음 때 날아가던 중이면 자료 없이 끝나고, 재실행 중인
   rank의 메모리를 읽으면 옛 값을 읽음. 9.11.3절 M2).
9. 체크포인트에서 재실행 끝까지, 다른 rank가 더하는 신호와 카운터를 초기화하지 않는다(재실행 전에 적용한 로그의 더하기를 지움. 9.11.6절 P5).
10. 복원한 communicator는 `ncclCommAbort`로 끝낸다(정상 정리의 노드 안 bootstrap 배리어에 되살린 rank가 들어감. 9.11.6절 P3).
11. communicator마다 투명 복구 GDAKI 문맥이 하나다(devComm 하나, GIN 연결 하나). 둘 이상이면 무장하지 않는다(9.10.4절).

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
9.11.10절이다: G1 정책 칸과 `NCCL_GIN_FAULT_POLICY`, G2 `gdakiTsDecline` 맨 앞의 거절 hook(hr 4916 / hw 4941),
G3 QP 감시의 상대 거르기 hook(hw 6094), G4 기록 처리 루프의 hook(hr 6114–6124 / hw 6399–6409), G5 훑기 유실 검사의 hook(hr 5894–5896 / hw 5923–5925),
G6 에폭 비교의 `coveredEpoch`(hw 6066, 6139, 5460, 3361), G7 감시의 QUERY_QP가 rmsn을 넘김(hw 6111), G8 감시 스레드의 복원 시한(`gdakiTsWatchdog` hw 3488),
G9 펌웨어 초과 책임의 원인(hw 3530).

**복원 계층(hold 분기의 내용).**

| id | 어디에 | 무엇을 |
|---|---|---|
| RL1 | G2의 hold 분기 | (가) 붙잡은 상대에 대한 모든 거절 → fallback(PeerDead, PEER_DEAD), (나) 강한 죽음 증거, ARMED, TOLD 아님 → hold 시작(9.10.7절) |
| RL2 | G4의 hold 분기 | 붙잡은 상대의 기록 흡수, `qs[].handled` 올림 |
| RL3 | G5, G3, G6, G7, G8, G9의 hold 분기 | 붙잡은 상대는 감시와 유실 검사에서 뺌, `coveredEpoch`, rmsn 표본, 감시 스레드의 복원 시한, 펌웨어 초과 책임의 원인 |
| RL4 | helper 루프(hr 6013–6129 / hw 6298–6415) | 복원 상태 기계 한 걸음(TIMED_OUT 확인, 활성화, REJOIN, 로그 보내기, 복원 라운드, FALLBACK(p)와 RESTORED(p) 처리). `gdakiTsBusy`는 hold 시작과 복원 라운드에서. 상태는 상대마다 원자 칸(9.10.7절) |
| RL5 | `gdakiTsStart`(hr 6735– / hw 7040–; `roundMs`를 정하는 곳 hr 6741 / hw 7046) | 복원 시한, `holdMs`, `roundMs`의 관계 검사, communicator 무장 조건(9.10.4절). 어기면 fail-fast |
| RL6 | 받기 루프(hr 4164–4243 / hw 4189–4268) | REJOIN: 붙잡은 상대(HELD)에게서만, nonce와 화신 번호, 죽음 표시 지우고 `gdakiTsInstall`(hr 3859 / hw 3884) |
| RL7 | 새 함수, `opMu` 안 | QP마다 `rq.exch`를 새 끝점으로(Commit의 검사 hr 2360 / hw 2361, 연결 hr 2450 / hw 2451 전) |
| RL8 | 새 함수 | 계획 `U = S, n = 0`으로 `gdakiTsRepostApply`(hr 4692 / hw 4717) |
| RL9 | `ncclGinGdakiRegMrSym`(hr 7879–7931 / hw 8198–8250), 문맥 생성(hr 7311–7315 / hw 7630–7634), `gdakiLbSetup`(hr 6474– / hw 6761–) | window 등록은 rkey 표의 자리만 등록부에 적고, 루프백 MR 등록(`gdakiLbAddRange`)은 GDAKI 문맥을 만들 때(devComm 생성, `gin_host.cc` 374) 그때까지의 표에만 한다. 그 뒤 등록한 window가 있으면 무장 안 함. 복원 때 칸 r을 NIC 루프백으로 쓰고, 다 쓴 뒤 READ 하나로 확인하고 나서 게시(9.11.4절 T5, 9.11.5절 A1 (3)) 2026-10-11(충돌 검토 K2, K3): "문맥"은 사용자 투명 복구 문맥이다(NCCL 안의 symmetric 커널 문맥이 아님). 사용자 devComm의 자원 window(문맥 뒤에 등록, `dev_runtime.cc` 1715–1723)는 devComm 생성 끝에서 그 rkey 표를 루프백 MR에 더해 복원 대상으로 넣음 |
| RL10 | 문맥 생성, `gdakiLbSetup`(hr 6474–6735 / hw 6761–7040), `gdakiTsStart`(hw 7040–) | 로그 고리와 측 표 할당, 루프백 MR, `ncclGinGdakiGPUContext`의 새 칸. GPU 문맥은 `gdakiTsSetup`보다 먼저 장치로 복사되므로(hw 7966) 측 표 포인터 칸은 `gdakiTsStart` 안에서 H2D 한 번으로 따로 쓰고, `ncclGinGdakiCreateContext`가 돌아온 뒤에는 쓰지 않음(9.10.4절, 검토 3 W1) |
| RL11 | `gdakiTsMsg`(hr 2953 / hw 2966), helper 루프의 메시지 처리(hr 6074–6083 / hw 6359–6368) | 새 메시지 종류 |
| RL12 | 새 함수 + 낡은 기록 검사(hr 5431 / hw 5460) | 입력 멈춤의 빈 라운드. 검사는 `coveredEpoch`로 |
| RL13 | `gdakiTsExecuted`(hr 4330 / hw 4355), `gdakiTsBaseline`(hr 4351 / hw 4376) | 누적 실행 수 |
| RL14 | `ncclGinTsUserAbortRaise`(hr 2760 / hw 2767), 정리(hr 6962, 7086 / hw 7274, 7405) | CANCELLED, 예비 프로세스에 BYE |
| RL15 | 확대 상한(hr 5081 / hw 5106) | 복원 라운드와 빈 라운드는 세지 않음 |
| RL17 | `gdakiTsServeLower`(hr 5372–5373 / hw 5401–5402) | 새 메시지 미루기. 같은 상대의 미룬 메시지는 그 상대의 REQ보다 먼저, 도착 차례대로 처리(9.10.7절 R1) |
| RL18 | 자료 서버(새 스레드, 새 포트) | 체크포인트 블록, 로그 내보내기 |
| RL19 | 통계 API(hr 7135 / hw 7454) | 복원 수 |
| RL20 | `gdakiTsRespond` 맨 앞(hr 5739 / hw 5768) | 그 상대의 미룬 RESTORED를 먼저 적용한 뒤, 붙잡은 상대의 REQ에 NACK 17, PUBLISHED면 fallback(9.10.7절 Q5, R1) |
| RL21 | `ncclGinGdakiRegMrSym`(hw 8198–8250 / hk 8376–8428), 정책 도우미(G1과 같이 씀), G1 기록의 `policyPad`, 예비 프로세스 모드 | 2026-10-11 사용자 결정(9.10.8절): hold 프로세스(`NCCL_GIN_FAULT_POLICY=hold`, `NCCL_GIN_RESTORE` ≠ 0)와 예비 프로세스의 모든 GDAKI window MR을 `force_strict_ordering`으로 등록(application의 `winFlags`는 그대로, 등록 호출에는 오류 길 없음, 지킴은 단위 시험 E1). rank마다 strict 비트와 복원 켬을 G1 기록에 싣고, 모든 rank가 복원을 요청했는데 어느 rank의 비트가 0이면 모든 rank에서 명시적 오류와 WARN(2026-10-11 사용자 결정: `ncclGinRestoreResume`이 이유와 함께 오류를 돌려주고 devComm 생성은 `ncclInternalError`와 WARN; 그 communicator는 끝, 다시 하지 않음). hold가 RO=1을 이기면 WARN 한 줄 2026-10-11 다시 확인(K13–K18): 오류는 모든 rank가 복원을 요청했는데 어느 rank의 비트가 0일 때만, 결정은 `all[]` 전체로 all-gather 바로 뒤, 오류는 2026-10-11 사용자 결정대로 Resume이 이유와 함께 돌려줌(devComm 생성은 `ncclInternalError`와 WARN), 자원 window는 `ncclGinRestoreResume`에서 찾아 잠금 안에서 루프백 MR에 더함 |

장치 쪽(DV1–DV4)과 예비 프로세스 쪽(SP1–SP6)은 아래 그대로다.

| id | 무엇을 |
|---|---|
| DV1 | `ncclGinGdakiGPUContext`(common.h 222–236)에 측 표 포인터 `restore` 칸: QP마다 로그 고리 설명, "로그 켬" 낱말(검토 3 W2), 보낸 메시지 수, 억제 예산. 포인터는 hold 정책이면 문맥을 만들 때부터 0이 아님(RL10) 2026-10-12 사용자 결정: 판은 그대로 두고 구조체 끝에 더함(9.11.5절의 GPU 문맥 판 행) |
| DV2 | `putImplMode`(gin_gdaki.h 458–547), `putValueImplMode`(577–), 신호 길에서 게이트 안 로그 쓰기(9.5절). hold가 아니면 측 표 포인터가 0. 포인터가 0이 아니어도 그 QP의 "로그 켬" 낱말(게이트 안 strong 읽기)이 서 있을 때만 씀 |
| DV3 | 결정 (나)(2026-10-09, 9.11.12절 B4, 검토 3 반영): hold 정책의 communicator(측 표 포인터 ≠ 0)에서만 `tsGateEnter`가 참을 돌려준 뒤 키를 다시 읽음. `putImplMode`는 게이트(501) 뒤 보내기 갈림(509) 앞에서 `raddr.key`(`hasWins`일 때만)와 `sig_raddr.key`(키 주소가 null이 아닐 때만), `putValueImplMode`는 604 뒤, `getImplMode`는 704 뒤에 `raddr.key`. 읽기는 L1을 거치지 않는 시스템 범위 relaxed 32비트 읽기. `signalKey`는 지금처럼 호출자가 계산해 값으로 넘기고(1458–1468, 1483–1494), 호출자는 그 키를 읽은 주소(`signals_table.rkeys + peer` 또는 `signalMh->rkeys + peer`, 신호가 없으면 null)를 내부 인자 하나로 더 넘김. fail-fast는 키 읽기 자리와 종류가 지금과 같고 put에는 DV2와 같은 포인터의 분기 하나와 내부 인자 하나, get에는 포인터 읽기 하나와 분기 하나만 더해짐(검토 3 재확인 X3). 비용은 LT1, LT2와 7절의 비용 셀 |
| DV4 | 게이트 에폭 반쪽의 SUPPRESS 비트(`EPOCH_MASK`를 `0x1fffffff`로). 보내기의 열림 검사(`tsGateEnter` 333)에만 넣고 공용 `tsWordOpen`(146–148)과 대기 쪽(`tsPollEnter` 365, `tsParkStable` 264)에는 넣지 않음. 장치가 에폭 반쪽을 값으로 쓰는 자리(364–366, 1106–1108, 1037, 206–207)에서 지움. 느린 길의 억제와 put+신호 나누기(9.11.9절 C6) |

| id | 무엇을 |
|---|---|
| SP1 | 초기화 기록: bootstrap API와 GIN collComm의 결과를 원래 rank가 적고 짝에게 맡김 |
| SP2 | 예비 모드 `ncclCommInitRank`: 활성화를 기다리고, bootstrap 호출을 기록으로 대답(종류, 태그, 크기 검사), 자기 몫은 새 값 |
| SP3 | 예비 모드 GIN 문맥: 새 QP를 기록의 생존 rank QPN에 연결, helper 설정은 기록의 salt로 nonce, REJOIN으로 모든 생존 rank에 걺 |
| SP4 | window 등록: rkey 표에 기록의 생존 rank rkey, 자기 칸은 새 rkey. 새 rkey와 신호 표 rkey를 REJOIN에 실음 |
| SP5 | 상태 적용: 짝에게서 이미지, 생존 rank에게서 로그와 `X_q` |
| SP6 | `ncclGinRestoreResume`이 단계와 덩어리를 돌려줌. 억제 예산을 측 표에 쓰고 SUPPRESS 비트를 켬 |

### 9.10 장애 반응 정책: 감지와 반응을 나눈 통합 설계 (gin-restore, gpu-detect)

이 절과 9.11절은 2026-10-09에 따로 쓴 정책 설계 문서(`DESIGN_POLICY.md`)를 2026-10-11 사용자 결정(실험 하나에 `EXPERIMENT.md` 하나)으로 옮긴 것이다(12절). 그 문서의 절은 1 → 9.10.1, 2.1–2.5 → 9.10.2–9.10.6, 3 → 9.10.7, 4와 4.1–4.11 → 9.11과 9.11.1–9.11.11, 5 → 9.11.12, 6 → 9.11.13, 7 → 20절로 옮겼고, 안의 절 참조도 새 번호로 고쳤다. 내용은 그대로다.

**목적.** gpu-detect 계층(GIN `hw`, NVSHMEM `t1w`)이 섞어 둔 "장애 감지"와 "fail-fast 반응"을 나누고, gin-restore가 요구하는 반대
반응(대기를 붙잡고, degraded 해제를 막고, 새 프로세스를 같은 논리 rank로 받아 재실행)을 communicator마다 고르는 정책으로 넣었을 때, 기존
장치와 충돌이 남지 않는지 한 표로 정리한다.

**상태.** 검토용 설계. 사용자 결정(2026-10-09)으로 충돌이 남아 있는 동안 구현하지 않는다. 이 설계의 검토가 끝날 때까지 아무것도 빌드하지 않는다. 사용자 결정(2026-10-09, 뒤): B4는 (나)(9.11.12절), B1–B3은 실행 가능성 시험만 빌드한다(9.15절). 복원 계층은 여전히 구현하지 않는다.

**근거 트리.** hr: 세션 스크래치 `agent_ts2hr/nccl-src`(gin-remaining). hw: `agent_gd/gin/nccl-src`(기준 커밋 `382bbb4` = hr, `harness/gpu-detect/hw_layer.diff`(그때 gpu-detect worktree, 지금 master) md5 `be0ea9ed`, libnccl md5 `efc48ca1`). nvs: `agent_gd/nvs/src`(t1_380 위의 t1w, t1w_layer.diff md5 `ac24448b`). 모두 2026-10-09에 읽기만 함.

**독립 검토.** 검토 1(이 문서의 초안 표 대상), 검토 2(이 정책 설계 대상, 재확인 다섯 번) 반영. 검토 2의 마지막 판정(커밋 `0af9190e`): "막는 문제 B1–B4 밖에 풀리지 않은 충돌 없음"(9.11.13절)

**줄 번호 규칙.** `gin_host_gdaki.cc`의 줄은 "hr N / hw M" 꼴로 둘 다 적는다. hw는 이 파일만 바꿨고, 장치 헤더(`gin_gdaki.h`,
`gin_gdaki_device_host_common.h`), `init.cc`, `transport/net_ib/gin.cc`, `gin/gin_host.cc`는 hr과 hw가 같은 파일이다(앞의 넷은 md5 확인 `[측정]`).
그 파일들은 줄 번호 하나만 적는다. NVSHMEM은 `ibgda.cpp`(= `src/modules/transport/ibgda/ibgda.cpp`)와 `wait_until.cuh`(=
`src/include/non_abi/device/wait/nvshmemi_wait_until_apis.cuh`)다. gpu-detect 문서는 master의 `harness/gpu-detect/EXPERIMENT.md`다
(2026-10-11, PR #63; 이 설계를 쓸 때는 gpu-detect worktree에 있었음). "F번호"는 검토 1, "V번호"는 검토 2의 지적이다(9.11.13절).

#### 9.10.1 문제

gpu-detect는 감지를 고치면서 반응도 fail-fast로 굳혔다 `[소스]`.
- GIN `hw`: QP 상태 감시(`gdakiDetWatchStep` hw 6085–6187)가 ERR QP를 장애 기록으로 바꾸고, 보통 라운드가 살아 있으면 복구, 죽었으면 거절한다.
  `NCCL_GIN_TS_DEGRADED_ROUNDS=0`(hw 2676)이 기본이라 칸 0이 오른 뒤에는 어느 상대와도 라운드를 게시하지 않는다(`gdakiUaPeerRaised` hw 2918–2925).
  그런 거절은 원인이 Local이라 shrink 넘기기를 막는다(gpu-detect 문서 9.1절 (d)).
- NVSHMEM `t1w`: FIN이 BYE 없이 오면 바로 죽음으로 거절하고(`t1_helper_main`의 판정, ibgda.cpp 7930–7951), 거절마다
  `NVSHMEM_IBGDA_FT_T1_FAILSTOP_MS=0`(기본, ibgda.cpp 8048)이면 `_exit(70)`이다(`t1w_after_decline` 6841–6858, `t1w_failstop_exit` 6813–6839).

gin-restore는 죽음에 반대로 반응해야 한다: 대기를 붙잡고, degraded 해제를 막고, 새 프로세스를 같은 논리 rank로 받아들이고, 재실행한다
(9.1–9.8절). 두 반응이 같은 코드 자리(거절)에 섞여 있으면 어느 하나를 넣을 때 다른 하나가 깨진다.

#### 9.10.2 감지(두 정책에 공통)

감지는 "무슨 일이 있었는가"의 증거만 만든다. 증거를 만드는 코드, 그 변수(감시 주기와 유예 등), 그 로그 줄은 두 정책에서 같다.

| id | 감지원 | 만드는 증거 | 코드 |
|---|---|---|---|
| S1 | 장치 분류: 요청 대기, flush, 보내기의 slot 대기가 본 오류 CQE를 분류해 기록 | QP 장애(분류: RETRY_EXC, LOCAL_QP_ERR, REM_ACCESS 등) | `q4Report` gin_gdaki.h 859–, `tsPoll` 1103–1108, `tsSwErrReport` 1031–1045; 호스트 `gdakiQ4Handle` 1008–1030(hr = hw, Q4 감시 스레드) → `gdakiTsRoutes` hr 3260–3264 / hw 3285–3289 → `gdakiTsPushFault` hr 3266–3271 / hw 3291–3296 |
| S2 | hw QP 상태 감시: 라운드 밖에서 10 ms마다 QUERY_QP, ERR/SQER이면 합성 기록 | QP 장애 | hw `gdakiDetWatchStep` 6085–6187(상대 거르기 6094), `gdakiDetRecord` 5986–6058, `gdakiDetQueued` 6060–6069, helper 루프에서 부름 6410, 변수 2673–2675 |
| S3 | helper 소켓 liveness | 죽음: BYE 없는 FIN, BADMAGIC, "모름" 목록 밖의 errno(`gdakiTsCauseLiveness` hr 3712–3718 / hw 3737–3743, `gdakiTsSocketLost` hr 3746–3777 / hw 3771–3802; 판정 WARN 줄 hr 3766, 3774 / hw 3791, 3799), 1–5 s 간격 거절 둘(`gdakiTsRefused` hr 3783–3810 / hw 3808–3835). 떠남: BYE(hr 6078–6080 / hw 6363–6365). 모름: reset, 시간 초과(`gdakiTsMakeUnknown` hr 3724–3741 / hw 3749–3766). 상대의 거절: FAIL(hr 3896–3906 / hw 3921–3931). 남의 연결: nonce 불일치(hr 4198–4203 / hw 4223–4228) | |
| S4 | 감시(watchdog, Q4 감시 스레드): 펌웨어 명령 단계 초과, 라운드 초과, 기록이 쌓였는데 helper가 1 s 넘게 돌지 않음 | 로컬 정체 | `gdakiTsWatchdog` hr 3463–3526 / hw 3488–3551, `gdakiRecFwGuard` hr 1742–1770 / hw 1743–1771 |
| S5 | 장치의 포기와 훑기: 쉬던 장치 스레드가 hold 한도 뒤 포기(DEV_FAILED, abandoned), 기록 유실 | "application이 이미 실패를 들음" | `tsGiveUp` gin_gdaki.h 188–192, `tsLateFail` 200–214, `tsParkStable` 252–297; `gdakiTsScan` hr 5862–5900 / hw 5891–5929 |
| S6 | NVSHMEM t1w: BYE 없는 FIN 판정 | 죽음 | ibgda.cpp 7930–7951, `t1_peer_fin` 6442–(BYE 먼저 읽기), `t1_fini`의 BYE 8243–, `NVSHMEM_IBGDA_FT_T1_FIN_DEATH` 8047 |

증거의 종류: 죽음(DEAD), 떠남(LEFT), 모름(UNKNOWN: 재연결 기계가 맡음, 반응 아님), 상대의 거절(PEER_DECLINED), QP 장애(PAIR_FAULT, 상대가 살아
있으면 라운드), 로컬 정체(LOCAL), application이 이미 들음(TOLD, 9.10.5절).

#### 9.10.3 반응(정책)

정책은 communicator마다 하나이고 두 값이 있다.
- **fail-fast**(기본): 지금의 hr, hw 동작 그대로. 죽음 → 그 상대 거절(상대별 단어, 비동기 오류, QP를 ERR로, 게이트 실패) → 2 s 뒤 degraded로 칸 0
  (랭크 2개면 "모든 상대 거절" 규칙으로 바로) → (hw) `DEGRADED_ROUNDS=0`이면 그 뒤 어느 상대와도 라운드 게시 없음.
- **hold-for-restore**: 강한 죽음 증거(9.10.5절)가 있고, 그 상대가 무장(ARMED)이고, TOLD가 아니면 거절하지 않고 붙잡는다(상태 HELD, COMMITTING, PUBLISHED, 이하 "붙잡은 상대"; 9.10.7절).
  복원 시한까지 복원이 안 되거나 복원 중 무엇이든 실패하면 그때 fail-fast 반응을 그대로 한다(fallback). fallback은 그 상대를 원인 PeerDead,
  `GDAKI_UA_PEER_DEAD`로 거절하는 것이고, 붙잡은 상대에 대한 다른 거절도 모두 이것으로 바뀐다(V1). 그래서 fallback 뒤의 상태(단어, degraded, 책임 기록)는
  fail-fast에서 그 상대가 죽었을 때와 같다.

정책이 바꾸는 것은 **죽음에 대한 반응**, 붙잡은 상대에게서 온 QP 장애 기록의 처리(라운드 대신 흡수), 붙잡은 상대에 대한 거절의 원인(PeerDead로)뿐이다.
살아 있는 상대의 QP 장애, 분류 불가, 확대 상한, 상대의 FAIL, BYE, 감시, 장치의 포기는 두 정책에서 같게 처리한다.

NVSHMEM은 정책이 fail-fast 하나다(복원은 범위 밖). t1w의 `FIN_DEATH`, `FAILSTOP_MS`, `FAILSTOP_CODE`는 fail-fast 반응의 변수다. hold 정책의 프로세스는
NVSHMEM을 쓰지 않는다(X6).

#### 9.10.4 정책 고르기, 기본값, 무장 조건

- 환경 변수 `NCCL_GIN_FAULT_POLICY=failfast|hold`. 기본 `failfast`. GIN 문맥을 만들 때(`gdakiTsSetup` hr 6152– / hw 6438–) 읽고, 설정 all-gather
  (`gdakiTsAddr`, hr 6232 / hw 6518)에 실어 모든 rank가 같은지 본다. 다르면 그 communicator는 fail-fast다(WARN 한 줄). 레코드가 커지므로 한 job의 모든
  rank가 같은 라이브러리여야 한다(지금도 이 all-gather는 같은 판을 전제함).
- communicator마다의 선택은 API로: `hold`는 application이 그 communicator에 `ncclGinRestoreResume`을 부른 뒤에만 무장한다(9.4절).
  부르지 않는 application의 communicator는 변수와 상관없이 fail-fast다. 이 호출은 새 `nccl.h`에만 있으므로 그 application이 새 헤더로 빌드됐다는
  증거로 쓰고(`[추론]`: 한 프로그램이 헤더 둘을 섞는 경우는 막지 못함), 장치 쪽의 확인은 GPU 문맥 판 번호(A5)가 한다.
- **communicator의 무장 조건**(`gdakiTsStart`에서 확인, 하나라도 아니면 그 communicator는 fail-fast):
  - (2026-10-12 사용자 결정, 9.10.8절) 아래 조건은 모두 `ncclGinRestoreResume`에서 rank마다 보고, 모든 rank가 bootstrap으로 모은 같은 자료로 정한다. Resume
    때 하나라도 어긋나면 그 호출이 모든 rank에서 같은 이유의 오류를 돌려준다(전에는 대부분 WARN과 fail-fast였음). LSA 팀 조건은 devComm의 `lsaSize`가 1이
    아니면 오류로 보고, 복원 시한과 hold 한도의 관계는 우선 "`NCCL_GIN_RESTORE_MS`가 `NCCL_GIN_TS_HOLD_MS`보다 작음"으로 본다(붙잡기 상태 기계에서 다듬을 수
    있음). Resume 뒤에 잃는 조건(확대 상한, NIC 경로가 꺼짐, 문맥 뒤의 window 등록, 사용자 문맥이 아닌 `createContext`)은 그대로 DISARM이나 fallback이다.
    측 표와 복원 버퍼의 루프백 MR, 문맥 뒤 window는 작업 묶음 3에서 Resume의 검사에 더한다(9.14절).
  - 투명 복구 GDAKI 문맥이 정확히 하나(F6: helper는 문맥마다, 단어는 communicator마다라 둘 이상이면 한 helper의 fallback이 다른 helper의 복원을 깸). 문맥은
    devComm을 만들 때 생기고(`gin_host.cc` 374) GIN 연결마다 하나다(`ginCommCount`, `gin_host.cc` 277).
  - `NCCL_GIN_TS_RECONNECT=1`(F27).
  - 그 문맥이 확대 상한으로 복구를 멈추지 않았음(`ts->escalated`, F26).
  - 복원 시한과 hold 한도의 관계(T4).
  - NIC 복사 경로가 켜져 있고(`gdakiLbOn`), 복원이 쓰는 GPU 버퍼(window rkey 표, 신호와 카운터 표, 로그 고리, 측 표)가 문맥을 만들 때 루프백 MR에
    등록됨(V8, V12). devComm을 만든 뒤 등록한 window가 있으면 무장하지 않는다(그 rkey 표는 루프백 MR에 없음). 도중에 NIC 경로가 꺼지면 fallback.
  - QP 감시가 켜져 있음(`NCCL_GIN_TS_QPWATCH_MS` > 0, hw 6087): 누적 실행 수의 표본(G7, V14).
  - (2026-10-11 바꿈) window의 strict ordering은 더는 무장 조건이 아니다. 전에는 "window가 strict ordering으로 등록됨(`NCCL_WIN_STRICT_ORDERING`,
    9.11.12절 B3의 해결 후보. B3이 풀리기 전에는 조건으로 둔다)"이었고 어기면 WARN과 fail-fast였다. 사용자 결정(2026-10-11)으로 런타임이 등록 때 strict를
    강제하고, 강제할 수 없을 때만 명시적 오류를 돌려준다(9.10.8절). 다른 무장 조건은 그대로 WARN과 fail-fast다(2026-10-12 바뀜: Resume의 오류, 이 목록의 첫 항목).
  - (2026-10-11, 충돌 검토 K2, K4, K18) 그 communicator에 NCCL 안의 GIN devComm이 없음(symmetric 커널의 GIN devComm: `NCCL_SYM_GIN_KERNELS_ENABLE=0`이거나
    COLL_SYMMETRIC window가 없음; 9.10.8절 표; `ncclGinRestoreResume`에서 검사하고 그 뒤 사용자 문맥이 아닌 `createContext`가 오면 DISARM), 모든 rank의 G1 기록에 strict 비트가 1(9.10.8절). 앞의 것은 어기면 WARN과 fail-fast(2026-10-12 바뀜: Resume의 오류), 뒤의 것은 모든 rank가
    복원을 요청했을 때(9.10.8절의 K13 정의) 명시적 오류다. 오류는 2026-10-11 사용자 결정대로 `ncclGinRestoreResume`(과 devComm 생성)에서 이유와 함께 나온다(9.10.8절).
  - 이 rank의 GPU 문맥(판 3, A5; 2026-10-12 사용자 결정으로 판은 그대로 두고 구조체 끝에 더함, 9.11.5절)에 0이 아닌 측 표 포인터가 있음(검토 3 W1, 2026-10-09). hw는 GPU 문맥을 `gdakiTsSetup`(hw 7986)보다 먼저 장치로 복사하므로
    (`copy_h_to_d`, hw 7966) 포인터는 그 복사에 실리지 않는다. 복원 계층(RL10)은 측 표를 할당한 `gdakiTsStart` 안에서, `ncclGinGdakiCreateContext`가
    돌아오기 전에 그 칸 하나를 동기 H2D 한 번으로 쓰고(hw 7106처럼 돌아오기 전에 동기화; 호스트 사본 `host_buf`에도 같은 값) 그 뒤에는 쓰지 않는다(그 뒤에
    쓰면 이미 도는 커널이 L1에 남은 0을 계속 읽을 수 있음). 정책 `failfast`나
    `NCCL_GIN_RESTORE=0`이면 포인터는 0이고 그 communicator는 무장하지 않는다.
  - host RMA가 꺼져 있음(`comm->config.numRmaCtx == 0`, B1 설계 검토 T1-1, 2026-10-09): 켜져 있으면 첫 window 등록에서 RMA proxy가 모든 상대에게 hook 밖의
    IB 연결을 맺어(`ncclRmaProxyConnectOnce`, `transport/net_ib/gin.cc` 545–556) 예비 프로세스가 재생할 수 없다(A3).
  - `runtimeConn = 1`, `nvlsSupport = 0`(B2 설계 검토 T2-3): runtime connect를 끄면 초기화가 상대와 전송을 잇고(`init.cc` 1837–1906), NVLS는 multicast handle을
    상대에게서 가져온다. 둘 다 재생할 수 없다. host에서 띄운 NCCL collective나 P2P는 runtime connect로 P2P/SHM 전송을 만들어 상대 버퍼를 가져오므로
    application 요구로 막는다(9.7절 6번).
  - 무장할 상대는 이 rank와 LSA 팀이 다름(lsaSize 2 이상이면 메모리 handle의 파일 기술자를 상대 proxy에서 받아 기록할 수 없음, `dev_runtime.cc` 322–328; 9.11.12절 B2,
    T1-4).
- **상대의 무장(ARMED)은 communicator 전체의 합의다**(V6). 상대 p는 다음이 모두 참일 때만 ARMED다.
  - p의 확정된 체크포인트가 짝에 있고, 그 체크포인트의 입력 멈춤에서 **모든** 생존 rank가 "p에 대해 무장 가능"으로 답했음(PAUSED에 실음. 그 rank의
    communicator 무장 조건, 위의 측 표 포인터 포함).
  - 그 뒤 어느 rank도 p에 대한 DISARM을 보내지 않았음. rank q는 p로 가는 로그가 넘치거나, p로 `get`을 냈거나(M2), 자기 문맥이 무장 조건을 잃으면
    DISARM(p)를 모든 rank에 보낸다. 받은 rank는 p를 OFF로 둔다(p의 다음 확정 체크포인트까지).
  - p의 예비 프로세스가 짝에 등록돼 있음.
  하나라도 아니면 p의 죽음에는 모든 rank가 fail-fast다.

#### 9.10.5 우선순위, 증거, fallback 순서

위가 이긴다.
1. application이 고른 동작: `ncclCommAbort`, `ncclCommRevoke`, 중단 shrink(이 셋은 모든 단어를 올림), `ncclCommDestroy`(정리: helper를 멈춤, 단어는
   올리지 않음). 복원 중이면 취소(CANCELLED).
2. 이미 application에 닿은 것(TOLD). 이 상태에서는 hold를 시작하지 않고, 복원 중이었으면 fallback.
3. hold-for-restore(무장된 상대의 강한 죽음 증거).
4. 복원 시한 또는 복원 중 실패 → fallback.
5. fail-fast.

fallback 순서는 hold-for-restore → 복원 시한 → fail-fast다. fallback은 지금의 거절을 그때 부르는 것이고, degraded 시계도 그때 시작한다(칸 0은
fallback + `NCCL_GIN_TS_DEGRADED_MS`, 랭크 2개면 바로).

- **TOLD의 판단**: (a) communicator 등록부(`gdakiUa`, hr 2705–2718 / hw 2712–2725)에서 그 상대의 단어, 칸 0, `allWhy`, (b) 그 문맥의 비동기 오류가
  서 있음(`q4->setAsync`; 다른 상대의 거절이 세운 것도 communicator에 대한 것이므로 TOLD), (c) 그 상대로 가는 게이트의 `abandoned`나 DEV_FAILED(게이트
  읽기, NIC 복사 경로). (c)의 읽기가 실패하면 TOLD로 본다(보수적).
- **강한 죽음 증거**(F9, V11): 거절의 `uaWhy`가 `GDAKI_UA_PEER_DEAD`이고, 그 죽음을 판정한 `gdakiTsSocketLost`가 남긴 `pe.lostCause`가 "FIN"(BYE 없음)
  이거나 "ECONNREFUSED"(1–5 s 간격 거절 둘)이고, `pe.lostAfterCommit`가 서 있지 않은 경우만. BADMAGIC과 그 밖의 errno로 판정된 죽음은 hold를 시작하지 않고 fail-fast다(흐름이 어긋난 산
  프로세스일 수 있음). REJOIN은 `lostCause`와 `closeCause`, `lostAfterCommit`를 지운다(낡은 원인이 남지 않게).
- **`pe.lostAfterCommit`**(2026-10-09, gpu-detect와의 계약, 메인 세션이 정함): gpu-detect는 응답 쪽이 Commit한 뒤 게시 전에 소켓을 잃은 길(9.10.7절,
  hw 5285–5292, 5298–5303)을 고친다. 그 길에서 소켓을 잃은 자리에서, `gdakiTsSocketLost`를 부르기 전과 어느 돌아가기보다도 먼저 상대별 표시
  `pe.lostAfterCommit = true`를 세우고(검토 3 W10, X5; 규칙은 이것 하나), 그 잃음이 죽음 판정이면 거절을 원인
  PeerDead, `GDAKI_UA_PEER_DEAD`로 한다(degraded 예약). 죽음 판정이 아니면 지금 동작(원인 Unknown, `uaWhy` DECLINED) 그대로다. 그래서 고친 뒤에는 그 거절이
  위의 앞 두 조건을 채울 수 있다. 복원 설계는 이 창을 계속 붙잡지 않는다: G2의 강한 증거 검사가 이 표시가 선 거절을 빼고, 그 상대가 ARMED였으면 NOHOLD(p)를
  보낸 뒤 fail-fast로 거절한다(9.10.7절 N4). 표시는 G2가 그 거절 안에서 읽으므로 거절 전에 서 있어야 하고, 지우는 곳은 REJOIN뿐이다(D4).
  검토 3의 다듬음(W10, 메인 세션과 gpu-detect에 넘길 것): 그 고침이 `gdakiTsSocketLost`만 부르고 거절을 helper 루프(hw 6380–6386)나 라운드의 죽음 길
  (hw 5507–5518)에 맡기면 "거절 바로 전"은 그 창을 모르는 코드가 된다. 그래서 표시는 잃은 자리에서, `gdakiTsSocketLost`를 부르기 전과 어느 돌아가기보다도
  먼저 세운다. Commit 뒤 응답 쪽의 다른 출구(DONE 시간 초과 hw 5304, BYE 5305–5307, FAIL이나 모르는 레코드 5309–5311, `RepostApply` 실패 5313)에서도
  세우면 앞으로 원인이 바뀌어도 이 지킴이 따로 선다(선택). 같은 화신에 대해 표시 없는 PEER_DEAD 거절이 뒤따를 수는 없다: 첫 거절이 `pe.declined`를 세우면
  `gdakiTsSocketLost`가 더는 `deadJudged`를 세우지 않고(hw 3796), 다시 걸기와 탐침이 멈추고(hw 3997, 4094), 그 상대 단어가 TOLD로 G2의 hold 갈래를 막는다
  `[소스: 검토 3]`. 2026-10-09 확인: gpu-detect의 `hk` 빌드(`hk_layer.diff`, `prereg/gpu-detect-v1`)의 `gdakiTsDeclineAfterCommit`가 이 규칙대로 두 자리에서
  표시를 맨 먼저 세우고, 표시는 `gdakiTsInstall`에서 지운다 `[소스: hk_layer.diff, 읽기만]`. 검토 3 W11(gpu-detect 쪽 메모): ACK 보내기 실패 길에서는 `gdakiTsSend`가 `pe.closeCause`를 세우지 않고 `gdakiTsInstall`이 지우므로
  (hw 3892), errno를 먼저 `closeCause`에 옮기지 않고 `gdakiTsSocketLost`를 부르면 원인이 "모름"으로 남아 `gdakiTsCauseLiveness`(hw 3737–3743)가 죽음으로
  분류한다(EPIPE가 거짓 죽음과 degraded가 됨). hw 5606, 5749처럼 errno를 먼저 옮겨야 한다. 복원 설계에는 영향이 없다("모름"은 강한 증거가 아니고 표시가 뺌).
  2026-10-09 확인: `hk`는 ACK 보내기 실패 길에서 죽음 판정을 하지 않고 errno 이름을 `closeCause`에 넣는다(hk 검토 지적 1로 받기 쪽 peek을 뺌) `[소스: hk_layer.diff]`.
  복원 계층을 만들 때의 기준은 그때의 gpu-detect 빌드(지금은 `hk`)이고, 이 정책 설계의 hw 줄 번호는 그때 다시 맞춘다.
- **잘못된 죽음 판정의 막**: (1) 예비 프로세스는 같은 노드에 있으므로 활성화 전에 원래 프로세스(등록 때 받은 PID)가 끝났는지 스스로 확인한다:
  `/proc/<pid>`가 없거나, `/proc/<pid>/stat`의 상태가 Z(거두기 전 zombie)나 X이거나, 시작 시각(22번째 칸)이 등록 때의 값과 다르다(거둔 뒤 PID가 다시
  쓰인 경우; V9). 아니면 활성화를 거절하고 모두 fallback한다. (2) 복원 라운드가 생존
  rank의 QP를 예비 프로세스의 새 QPN에만 다시 이으므로, 옛 프로세스가 살아 있어도 RC 연결이 없어 생존 rank의 메모리에 쓰지 못한다(펜싱 `[추론]`).
  (3) 그 논리 rank의 HELLO, HELLO-ACK, PROBE-ACK는 화신 번호가 지금과 같아야 받는다(D4).
- **communicator마다 붙잡은 상대는 하나**. 복원 중 다른 상대의 죽음 증거가 오면 붙잡은 상대도 fallback하고 새 죽음은 fail-fast다(단일 실패 범위).
- **모두 함께**(V6): 예비 프로세스의 활성화는 모든 생존 rank가 p를 붙잡았다고 짝에게 알린 뒤에만 한다(HOLDING(p)). p를 붙잡은 생존 rank가 fallback하면
  FALLBACK(p, 화신)을 모든 rank와 예비 프로세스에 보내고, 그 화신을 붙잡았거나 되살린 rank도 fallback한다(붙잡지 않은 rank는 OFF로만, 9.10.7절 Q1).

#### 9.10.6 불변식

- (가) hold 동안 그 상대에 대해 application에 닿는 것은 없다: 상대별 단어, 칸 0, 비동기 오류, degraded 예약, 거절의 WARN 줄이 없다. 대기는 붙잡혀 있다.
  죽음 판정의 WARN 줄(hr 3766, 3774 / hw 3791, 3799)은 감지라서 두 정책에서 남고 `ncclGetLastError`에도 보인다.
- (나) 그 상대나 communicator에 대해 무언가가 application에 닿았으면 hold는 시작되지 않거나 끝난다(fallback). 실패를 들은 연산은 다시 내지 않는다는
  기존 규칙(게시 전 확인 `gdakiUaPeerRaised`, 커밋 지점 Dekker)이 그대로 지켜진다.
- (다) 정책 `failfast`에서 호스트 동작은 hw와 같다(검토 2 확인). 정책 `hold`이지만 무장하지 않은 communicator는 반응은 fail-fast와 같아도 설정이
  다르다: 문맥을 만들 때 루프백 MR이 더 많고(복원 버퍼), 그 등록에서 CUDA driver 함수를 부르고, 자체 시험 범위가 넓다(N5). 정책 hook(9.11.10절 G1–G9)과 같은 파일에 넣는 복원 계층의 코드(9.11.11절)는 fail-fast에서 늘 같은 값을 돌려주거나
  닿지 않는다. 장치 헤더의 변경(9.9절 DV1–DV4)은 fail-fast에서 같은 결과를 내지만 시간을 바꿀 수 있다: 보내기마다 측 표 포인터를 한 번
  보는 것(DV2), 키 읽기 자리(B4). B4의 결정 (나)(2026-10-09) 뒤 fail-fast에서 키 읽기의 자리와 종류는 지금과 같고, 더해지는 것은 DV2와 같은 포인터 읽기에
  기대는 분기 하나와 내부 인자 하나(신호 키의 주소)다(검토 3 W8: 그 인자가 게이트의 `__noinline__` 느린 길 호출을 건너 살아 있어 레지스터 배치가 바뀔 수
  있음, 결과는 같음). 게이트 뒤의 키 다시 읽기는 측 표 포인터가 0이 아닌 hold 정책의 communicator에서만 한다(A1). 그래서 hold 정책이지만 무장하지 않은
  communicator도 장치에서 fail-fast와 다르다: 문맥을 만든 때부터 보내기마다 키를 게이트 뒤에 다시 읽고(L1 적중을 잃음), coop의 추가 동기화를 치른다(로그 켬
  낱말은 게이트를 잡은 0번 스레드만 보므로 건너뜀 깃발을 적어도 한 번의 동기화로 나눔, C2). 로그는 QP마다의 켬 낱말이 선 뒤에만 쓰고(C2; 검토 3 W2), 그 낱말은
  그 QP의 첫 체크포인트 멈춤에서 서므로 무장하지 않은 communicator도 첫 멈춤 뒤에는 로그를 쓸 수 있다(검토 3 재확인 X1).

#### 9.10.7 상태 기계 (상대 하나, hold-for-restore)

```
 OFF ──(Resume 호출, communicator 무장 조건, 모든 생존 rank가 무장 가능으로 답한 확정 체크포인트, 예비 등록)──▶ ARMED ──(DISARM)──▶ OFF
 ARMED ──(강한 죽음 증거, TOLD 아님)──▶ HELD ──(hold 시작, 모두 HOLDING, PID 확인, REJOIN, 상태 적용, 복원 라운드)
 HELD ──(helper CAS, 커밋 지점 직전)──▶ COMMITTING ──(게시)──▶ PUBLISHED ──(예비 프로세스의 RESTORED(p))──▶ ARMED(화신 + 1) 또는 OFF
 HELD ──(시한: G8 CAS와 CPU 쓰기, 실패, TOLD, 다른 죽음, FALLBACK(p, 화신))──▶ FALLBACK = 그 화신을 PeerDead 거절
 COMMITTING ──(커밋 지점 뒤 복사나 doorbell 실패: 게시가 일어나지 않음)──▶ 그 자리에서 PeerDead 거절
 COMMITTING ──(그 사이 온 FALLBACK(p, 화신))──▶ 게시를 마친 뒤 PUBLISHED에서 FALLBACK
 PUBLISHED ──(시한: G8은 상태만, 실패, 그 상대 QP의 장애 기록, FALLBACK(p, 화신))──▶ helper가 PeerDead 거절(2ERR 먼저)
 그 화신을 붙잡았거나 되살린 상태 ──(FALLBACK(p, 화신) 받음)──▶ 그 화신을 PeerDead 거절, 그 화신은 다시 붙잡지 않음
 ARMED 또는 OFF(그 화신을 붙잡지 않음) ──(FALLBACK(p, 화신)이나 NOHOLD(p) 받음)──▶ OFF(거절하지 않음: 아직 죽음 증거가 없음)
 HELD, COMMITTING, PUBLISHED ──(abort, revoke, shrink, destroy)──▶ CANCELLED
 OFF 또는 ARMED가 아닌 상대의 죽음 ──▶ fail-fast 거절(ARMED였으면 NOHOLD(p)도 보냄)
```

"붙잡은 상대"는 HELD, COMMITTING, PUBLISHED의 상대다. 다만 감시와 기록과 훑기에서 빼는 규칙(G3, G4의 흡수, G5)은 QP가 ERR인 HELD와 COMMITTING에만
걸린다. PUBLISHED의 QP는 예비 프로세스와 RTS로 살아 있으므로 감시하고, 그 QP의 장애 기록은 복원 실패로 보아 fallback한다(라운드를 열지 않음; P3). 이 상태는 상대마다 원자 칸 하나이고, helper와 Q4 감시 스레드(G8, G9)는 잠금 없이 읽고 CAS로만
바꾼다(N3: G9는 outMu 안 hw 3530에서 불리고 helper의 거절은 정책 칸을 본 뒤 outMu로 가므로, 정책 잠금을 두면 차례가 뒤집혀 교착될 수 있음).

- **시한과 게시의 다툼**(N1). helper는 복원 라운드의 게시 전 확인(hr 4708 / hw 4733) 뒤, 커밋 지점(hr 4713 / hw 4738) 전에 CAS(HELD → COMMITTING)를 한다.
  G8은 HELD에서 CAS(HELD → TIMED_OUT)에 이겼을 때만 CPU 쓰기(단어, 비동기 오류, 책임, degraded)를 한다. HELD의 QP는 hold 시작에서 ERR이고, 복원 라운드의 Commit(5단계)부터
  CAS(8단계)까지는 RTS이지만 생존 rank의 게이트가 홀수라 보내지 못하고 예비 프로세스는 모든 DONE_RS 전에는 보내지 않으므로 그 QP로 NIC이 하는 일이 없다(Q4).
  그래서 "QP를 ERR로 먼저, 그 다음 단어"라는 거절의 차례(hr 4931–4943 / hw 4956–4968)가 뜻하는 것이 지켜진다. PUBLISHED에서는 QP가 RTS라 CPU로 단어부터 올리면 그 차례가 깨지므로
  (P1) G8은 CAS(PUBLISHED → TIMED_OUT)로 상태만 바꾸고, 거절 전체(2ERR 먼저)는 helper가 한다. PUBLISHED에서는 게이트가 이미 짝수라 장치 대기가 붙잡혀
  있지 않으므로 급할 일이 없다. PUBLISHED의 시한은 hold 한도 항이 없는 따로 된 값(게시 시각 + `NCCL_GIN_RESTORE_MS`)이다. COMMITTING은 G8이 건드리지 않는다: 남은 일은 정해진
  복사와 게시뿐이고 그 시간은 T4의 "복원 라운드 몫"에 든다(라운드 감시도 덮음). CAS에서 진 helper는 커밋 지점 전에 fallback한다. hold 시작의 걸음마다,
  특히 HOLDING을 보내기 전에 TIMED_OUT을 본다. 이렇게 하면 게시 전 확인 뒤에 라이브러리가 스스로 상대 단어를 올리는 일이 없다(불변식 (나)).
- **게시 뒤의 실패**(N2). 생존 rank가 게시한 뒤(PUBLISHED)에도 예비 프로세스가 모든 DONE_RS를 받아 재실행을 시작하고 RESTORED(p)를 모두에게 보내기 전까지는
  붙잡은 상대다. 그 사이 FALLBACK(p)를 받거나 PUBLISHED의 시한이 오면 helper가 새 화신을 PeerDead/PEER_DEAD로 거절한다(G2 갈래 (가)는 "RESTORED 전의
  화신"을 덮음). 그 거절은 게시 뒤 그 상대 QP에 낸 연산의 실패를 application에 알리는 보통의 거절이다. FALLBACK은 화신 번호를 싣는다. 받은 rank가 그 화신을
  붙잡았거나(HELD, COMMITTING, PUBLISHED) 되살렸으면(RESTORED를 받음) 그 화신을 PeerDead로 거절하고 다시 붙잡지 않는다(RESTORED와 FALLBACK이 엇갈려 와도
  복원에 참여한 모든 rank가 거절로 모임, P2). 그 화신을 붙잡지 않은 rank(ARMED, OFF)는 거절하지 않고 OFF로만 둔다(Q1: 그 rank에는 아직 죽음 증거가 없음). 예비 프로세스는 RESTORED
  뒤에도 FALLBACK을 받으면 BYE 없이 끝난다(BYE를 보내면 생존 rank가 LEFT로 보고 degraded 없이 거절할 수 있음, hr 5487–5488 / hw 5516–5517). 재실행은 모든 DONE_RS 뒤에만 한다.
- **RESTORED 뒤**(P5). ARMED(화신 + 1)는 무장 조건(9.10.4절)이 맞을 때만이고 아니면 OFF다: 새 예비 프로세스가 짝에 등록됐고, 짝은 그 논리 rank를 지금 맡은 프로세스
  (첫 예비 프로세스)의 PID와 시작 시각을 받았고(다음 PID 확인용), 붙잡은 동안 받은 DISARM(p)가 없어야 한다(그 동안 받은 DISARM은 RESTORED 때 적용). 같은
  rank의 두 번째 복원은 체크포인트 k와 그 뒤의 로그로 다시 할 수 있다(예산 X − P_k가 첫 예비 프로세스의 실행까지 덮음, 검토 2 확인).
- **억제 중인 rank와 남의 체크포인트**(P4). 억제 예산이 남은 rank는 다른 rank의 CKPT_PAUSE에 BUSY로 답한다. 그 rank의 보내기 위치가 상대가 실행한 수보다
  예산만큼 뒤라 절단점을 맞출 수 없기 때문이다. 그래서 생존 rank의 다음 체크포인트는 예비 프로세스의 억제가 끝난 뒤에 확정된다.
- **붙잡지 않고 거절하는 rank**(N4, Q1). ARMED인 p를 hold 없이 거절하는 rank(약한 죽음 판정, 9.10.7절의 응답 쪽 Commit 뒤 거절, hold 시작 때의 TOLD, 시작 실패)는
  NOHOLD(p)를 모두에게 보낸다. 받은 rank가 p를 붙잡고 있으면 fallback하고, 아니면 p를 OFF로만 둔다(DISARM과 같은 뜻). 거절의 이유가 산 상대일 수도 있는
  것(BADMAGIC, ACK 보내기의 EPIPE나 ECONNRESET)이라도 다른 rank가 p를 거절하지는 않으므로, 한 쌍의 문제가 communicator 전체의 "p 죽음"으로 번지지
  않는다(fail-fast에서 그 한 쌍만 실패하는 것과 같음).
- **PUBLISHED에서 RESTORED가 시한을 이김**(Q2). helper는 PUBLISHED의 TIMED_OUT을 처리하기 전에 예비 프로세스의 소켓과 미룬 칸에서 RESTORED(p)를 먼저 읽고,
  있으면 RESTORED를 따른다(PUBLISHED의 시한은 진행이 멈추지 않게 하는 장치일 뿐임). PUBLISHED의 시한은 `roundMs` + handshake 한도보다 길게 둔다(helper가
  다른 라운드에 묶여 있어도 RESTORED를 읽을 수 있게).
- **PUBLISHED의 낡은 기록**(Q3). PUBLISHED 상대의 장애 기록은 fallback 전에 `ts_epoch < coveredEpoch`인지 보고 그러면 낡은 기록으로 버린다(복원 라운드의
  게시가 `coveredEpoch`를 올리므로, hold 시작의 2ERR이 낸 flush 기록이 늦게 와도 성공한 복원을 무너뜨리지 않음).
- **예비 프로세스가 여는 라운드**(Q5). `gdakiTsRespond`(hr 5739–5820 / hw 5768–5849)는 상대가 거절됐는지만 보고 REQ에 답한다. 복원 계층은 그 맨 앞에서
  붙잡은 상대(HELD, COMMITTING, PUBLISHED)의 REQ에 NACK(새 이유 17, "복원 중")로 답하고, PUBLISHED이면 fallback한다(P3과 같이 PUBLISHED에서는 라운드를 열지
  않음). HELD에서 보통 라운드가 게시하면 계획이 `U = S − 날아가던 것`이 되어 로그로 이미 넣은 연산을 다시 보내기 때문이다. 예비 프로세스는 RESTORED 전에는
  라운드를 시작하지 않는다.
- **같은 상대의 메시지 차례**(R1). 같은 상대에게서 미룬 제어 메시지(M1)는 그 상대의 REQ보다 먼저, 소켓에 도착한 차례대로 처리한다(기다림 안 응답
  `gdakiTsServeLower` hr 5315–5378 / hw 5341–5407에서 바로 답하는 REQ와 미룬 REQ hr 6023–6056 / hw 6308–6341 모두). NACK 17을 보내기 전에도 그 상대의 미룬
  RESTORED를 먼저 적용한다. 그래야 RESTORED 뒤에 같은 소켓으로 온 REQ가 성공한 복원을 무너뜨리지 않는다.

**hold의 시작**(F8, V10). 거절 hook(G2) 안에서 `gdakiTsBusy` 안으로(라운드처럼 25 s 감시를 받고, 쌓임 감시는 Busy 동안 보지 않음 hr
3522 / hw 3547) 차례로, 걸음마다 heartbeat를 갱신하고 TIMED_OUT을 보며:
0. 상태를 HELD로(맨 먼저: 다음 걸음의 펌웨어 단계 2ERR이 넘쳐도 G9가 책임을 PeerDead로 적게, N3).
1. 범위를 모든 문맥으로(`gdakiTsScope = ALL`, 거절이 하는 것과 같음 hr 4919 / hw 4944): 쌍 범위 라운드나 중첩 응답 라운드 안에서 온 죽음도 모든 문맥을 덮음.
2. 그 상대에 준비된 라운드가 있으면 `ncclGinRecoverAbort`(거절이 하는 것과 같음 hr 4930 / hw 4955).
3. `gdakiTsQuiesce`(hr 4416– / hw 4441–)를 그대로: 게이트 홀수, `opMu` 안에서 QP를 ERR로(죽은 상대로 간 WQE가 flush 오류로 끝나 slot을 기다리던
   보내기가 게이트를 나감), 개수 0, 모아 둔 WQE의 doorbell(hr 4471–4499 / hw 4496–4524; 안 하면 복원 라운드의 Prepare가 "GPU producer not quiescent"로
   거절 hr 2213–2236 / hw 2214–2237), `abandoned` 확인. 실패하면 fallback.
4. `pe.deadJudged`, `pe.failedPending`을 지움(거절이 hr 4923–4924 / hw 4948–4949에서 하는 것. 안 지우면 helper 루프 hr 6095–6101 / hw 6380–6386이 루프마다
   다시 들어옴).
5. 게이트가 처음 홀수가 된 시각(라운드의 정지가 먼저였으면 그 시각)을 적음: 복원 시한 계산(T4).
6. 짝에게 HOLDING(p).

상대별 단어, 칸 0, 비동기 오류는 건드리지 않는다. 장치 대기가 본 flush 오류는 기록(D1)이 되고 흡수된다.

**Commit 뒤 게시 전의 응답 쪽 죽음**(F4, V3). 응답 쪽이 Commit(hr 5228 / hw 5253)한 뒤 ACK를 못 보내거나(hr 5260–5267 / hw 5285–5292) DONE을 기다리다
소켓을 잃으면(hr 5273–5278 / hw 5298–5303) 지금 코드는 죽음 판정(`gdakiTsSocketLost`) 없이 `pe.gone = true`를 세우고 원인 Unknown, `uaWhy` DECLINED로
바로 거절한다. 강한 죽음 증거가 아니므로 이 경우는 **두 정책 모두 fail-fast**다. 그래서 "Commit했으나 게시 전인 에폭"을 복원이 다룰 일은 없다(앞 판의
`S_pending`은 지웠다). 이 길은 hw에도 틈이 있다: PEER_DEAD가 아니라 degraded가 예약되지 않아, 랭크 3개 이상에서 상대를 모르는 대기가 풀리지 않는다
`[소스, 추론]`. 정책과 별개의 hw 고칠 거리로 9.11.10절 끝에 적었다.

2026-10-09: gpu-detect가 이 틈을 고친다(계약은 9.10.5절 `pe.lostAfterCommit`). 고친 뒤 이 창에서 죽음이 판정되면 거절은 PeerDead, `GDAKI_UA_PEER_DEAD`가 되고
degraded가 예약된다(fail-fast의 상대를 모르는 대기는 2 s 뒤 풀림). 그래도 hold-for-restore는 이 창을 여전히 붙잡지 않는다: 그 거절에는
`pe.lostAfterCommit`가 서 있어 G2가 강한 증거로 보지 않고, 상대가 ARMED였으면 NOHOLD(p)를 보낸 뒤 fail-fast로 거절한다. 그래서 "Commit했으나 게시 전인
에폭"을 복원이 다룰 일은 고친 뒤에도 없다.

**복원 뒤 생존 rank 자신의 무장.** 죽은 rank가 보낸 메시지의 로그는 그 rank와 함께 사라졌다. 모든 rank가 그 복원에 참여했으므로, 각 생존 rank q는 자기
확정 체크포인트의 절단점(되살린 rank에서 q로 오는 통로)이 복원 뒤 로그의 시작보다 앞임을 알고, 자기 다음 확정 체크포인트까지 DISARM(q)를 보낸다(그
사이 q가 죽으면 fail-fast). 단일 실패 범위의 약한 창이다 `[추론]`.

#### 9.10.8 복원 대상 window의 strict ordering 강제 (2026-10-11 사용자 결정)

**결정(사용자, 2026-10-11, 원문 그대로).** "복원 정책이 활성화된 communicator에서 복원 대상으로 등록되는 window는 런타임이 NCCL_WIN_STRICT_ORDERING을
강제한다. 강제가 불가능하면 조용히 복원을 끄지 않고 명시적인 등록 오류를 반환한다."

**근거(메인 세션이 2.32.3 트리에서 확인, 이 에이전트가 hw 트리에서 다시 읽음) `[소스]`.** VA 신호는 window가 `NCCL_WIN_STRICT_ORDERING`으로 등록돼야
한다(`docs/userguide/source/api/device_gin.rst` 156). `ncclGinRegister`가 그 flag를 `NCCL_NET_MR_FLAG_FORCE_SO`로 바꾸고(`gin/gin_host.cc` 556),
GDAKI의 `ncclGinGdakiRegMrSym`(hw 8198–8250)이 그것을 `gdakiRegMr`(hw 188–199)에 넘기면 `IBV_ACCESS_RELAXED_ORDERING`을 더하지 않는다(192). NCCL은 자기
신호 표와 RMA 버퍼를 늘 `FORCE_SO`로 등록한다(`gin_host_proxy.cc` 527, `rma/rma_proxy.cc` 127, 190, 200; GDAKI 신호와 카운터 표 hr 7311–7312 / hw
7630–7631). B3은 relaxed와 strict 모두에서 drain 확인을 통과했지만(9.15.3) relaxed를 쓰지 않는다. relaxed는 나중의 최적화 후보로만 남고, 능력 확인과
겹침(overlap) 실험을 통과한 뒤에만 다시 본다. application은 지금처럼 hook 둘(체크포인트 지점, `ncclGinRestoreResume`)을 부른다. 강제는 application이
flag를 넘길 필요만 없앤다. 순서(사용자): (1) 강제의 범위와 기존 등록 flag와의 충돌 검토(이 절), (2) 정상 경로에서 strict와 relaxed의 지연과 대역 비교
(9.15.6), (3) 복원 실험의 예측과 셀(DRAFT), (4) 체크포인트와 복원 경로 구현, pilot, 사전 등록(태그), 본 실행. 지금은 (1)과 (2)의 준비만 하고 복원 계층
코드는 쓰지 않는다.

**말의 정의(2026-10-11 충돌 검토 K1–K12 반영).**
- "복원 정책이 활성화된 communicator": window를 등록하는 때에 알 수 있는 것은 프로세스의 변수뿐이다. 정책 합의(G1)는 사용자 투명 복구 GDAKI 문맥을 만들 때
  (사용자 devComm 생성, `gdakiTsSetup`; 사용자 문맥은 `ncclGinFaultUserCtx`로 가림, `gin_host.cc` 370)의 all-gather에서 일어나고, window의 GIN 등록은 그보다
  먼저일 수 있다: devComm 전에 등록한 window는 devComm 생성 안에서 합의보다 먼저 등록되고(`dev_runtime.cc` 1486–1492, 그 뒤 `ncclGinDevCommSetup` 1644),
  `NCCL_WIN_COLL_SYMMETRIC` window가 하나라도 있으면 symmetric 커널의 내부 GIN devComm이 첫 `ncclCommWindowRegister` 안에서 GIN을 켜 그 뒤의 window는 바로
  등록된다(K2, 아래 표) `[소스]`. 그래서 등록 때의 판단은 "이 프로세스의 `NCCL_GIN_FAULT_POLICY`가 `hold`이고 `NCCL_GIN_RESTORE`가 0이 아님"이다.
  `NCCL_GIN_RESTORE`는 정수 변수(`ncclGetEnv`, NCCL_PARAM 꼴)이고 기본 1, 0이면 복원 끔(K11 (i)). 두 값은 G1과 같은 도우미 하나가 프로세스마다 한 번 읽어
  캐시하고(hk의 G1은 `gdakiTsSetup`에서 `getenv`로 읽음; 복원 계층의 빌드에서 G1도 이 도우미를 씀, `hk_layer.diff`는 고치지 않음), `hold`도 `failfast`도
  아닌 값은 G1처럼 fail-fast로 본다(강제 없음). 예비 프로세스 모드에서는 변수와 상관없이 강제한다(예비 프로세스는 복원에만 쓰임, K4).
- "복원 대상 window": 사용자 투명 복구 GDAKI 문맥이 만들어질 때 이미 등록돼 있는 사용자 window와, 그 사용자 devComm의 자원 window(아래 K3 행)다. NCCL 안의
  다른 window(symmetric 커널의 내부 devComm 자원 window 등)는 복원 대상이 아니다. 9.10.4절과 RL9의 "devComm을 만든 뒤 등록한 window가 있으면 무장 안 함"은
  "사용자 투명 복구 문맥을 만든 뒤 등록한 사용자 window"로 읽는다(K2: 어느 `createContext`든이 아니라 사용자 문맥; 그렇지 않으면 symmetric 커널의 내부
  문맥 때문에 모든 사용자 window가 "문맥 뒤"가 됨).
- "강제": hold 프로세스(와 예비 프로세스)에서 GDAKI backend에 GIN 등록되는 모든 window MR을 `FORCE_SO`로 등록하는 것(`ncclGinGdakiRegMrSym`에서
  `force_strict_ordering`을 참으로; hw 8198–8250 / hk 8376–8428). 복원 대상보다 넓게 건다: devComm 전과 뒤, `ncclGinRestoreResume` 전과 뒤, NCCL 안의
  window, 나중에 무장하지 않는 communicator의 window도 포함한다. application이 넘긴 `winFlags`는 바꾸지 않는다: 메모리 재사용의 동일성(`symMemoryObtain`,
  `dev_runtime.cc` 736), 등록 능력 all-gather(752–772, GIN_ONLY 마스크만 비교), 장치 쪽 `winFlags`(`core__types.h` 38), proxy backend의 MR이 지금과 같다.
  GDAKI에는 `regMrSymDmaBuf`가 없어(`net_ib/gin.cc` 387–388) `RegMrSym`(358–361)이 GDAKI window MR의 유일한 입구다(K11 (d), 유지보수 메모). 이 강제는 9.4절
  3단계의 READ를 대신하지 않는다: B3에서 두 GPU의 `GPU_DIRECT_RDMA_WRITES_ORDERING`이 0이었다(K11 (g)).
- "강제 불가능 → 명시적 오류"(K1, K4 반영): GDAKI에서는 `gdakiRegMr`가 `force_strict_ordering`이면 RO 비트를 넣지 않으므로(hw 192; data-direct dmabuf,
  dmabuf, `ibv_reg_mr_iova2` 길 모두 같은 access) 등록 때 강제가 안 되는 길이 없다 `[소스]`. 그래서 등록 호출에는 실행 중 오류 길을 두지 않는다(한 rank만
  돌아가면 rkey all-gather의 시간 제한 없는 고리 `net_ib/gin.cc` 138–202에서 다른 rank가 멈추고, 실패 길이 `devr->ginEnabled`(1470)와 symmetric 커널의
  `initialized`(`sym_kernels.cc` 191)를 되돌리지 않아 다시 하기도 깨짐, K1). 등록 길의 지킴은 단위 시험과 자체 시험으로 둔다(E1: hold 프로세스에서
  window MR이 RO 비트 없이 등록됨을 시험). 강제가 안 될 수 있는 경우는 rank 사이에서 생긴다: 변수가 hold가 아니거나 `NCCL_GIN_RESTORE=0`인 rank, 강제가
  없는 라이브러리(예: `hk`)를 쓰는 rank(이 경우는 아래 K16 고침: 섞인 라이브러리는 지원하지 않음). 그래서 rank마다 "내 GDAKI window MR이 모두 strict"인지를 한 비트로 G1 기록에 싣고(`policyPad` 칸; 복원 계층의
  빌드에서만 채움, `hk`는 0을 실으므로 strict 아님으로 읽힘), 사용자 문맥의 all-gather 뒤 모든 rank가 같은 자료로 정한다: 모든 rank가 복원을
  요청했는데(아래 K13 정의) 어느 rank의 비트가 0이면 모든 rank에서 명시적 오류와 WARN 한 줄(그 rank 번호)이다. 오류가 나오는 자리와 값은 아래 2026-10-11 사용자
  결정을 따른다(Resume이 이유와 함께 오류를 돌려줌, devComm 생성은 `ncclInternalError`와 WARN; 처음 쓴 `ncclInvalidUsage`는 그대로 나오지 않음). 이 오류는 그 communicator에 대해 끝이다: 모든 rank가 `ncclCommAbort`나 `ncclCommDestroy`로 끝내고 다시 하지 않는다(K1). rank 사이에서
  정책 자체가 다르면 지금처럼 G1의 WARN과 fail-fast다(정책 불일치는 강제의 문제가 아님). ARMED에는 모든 rank의 비트가 1이어야 한다(9.10.4절). (E2) HCA가
  MR flag와 상관없이 relaxed 쓰기를 강제하는 설정(펌웨어 설정 `PCI_WR_ORDERING`의 force relax)은 사용자 공간에서 알아낼 길을 찾지 못했다 `[미확인]`. 한계로
  18절에 적는다(K11 (h)). 2026-10-11 메인 세션의 읽기 전용 sudo 읽기로 이 두 NIC는 확인됐다: rain과 sunny의 ConnectX6 모두 `PCI_WR_ORDERING`이 `per_mkey(0)`
  (펌웨어가 relaxed 쓰기를 강제하지 않고 MR마다의 access flag를 따름) `[측정]`. 그래서 이 두 노드에서 강제(MR에 RO access flag 없음)는 NIC가 strict 쓰기를 낸다는
  뜻이다 `[측정: 설정]`. 다른 기계에서는 한계로 남고, sudo 읽기 한 번(`mlxconfig -d <bdf> q PCI_WR_ORDERING`)이면 풀린다.

**다시 확인(검토 K13–K18, 2026-10-11) 뒤의 고침과 사용자 선택.**
- 복원 요청(K13): rank마다 "복원 요청" = (`NCCL_GIN_FAULT_POLICY=hold`이고 `NCCL_GIN_RESTORE` ≠ 0) 또는 예비 프로세스 모드. 위 정의의 "strict 비트"는 실제로는
  "이 rank의 라이브러리가 강제하고 이 rank가 복원을 요청함"이라는 프로세스의 성질이다(그 뒤에 등록되는 자원 window도 강제되므로 지금까지의 등록이 아니라
  프로세스를 말함, 검토의 정보 메모). 명시적 오류는 "모든 rank가 복원을 요청했는데 어느 rank의 이 비트가 0"일 때만이다. 모든 rank가 hold이고
  `NCCL_GIN_RESTORE=0`이면 오류 없이 hold이지만 무장하지 않은 communicator다(9.10.4절, 7절의 `rs4_none_off`). rank 사이에서 `NCCL_GIN_RESTORE`만 다르면 어떻게
  할지는 아래 2026-10-11 사용자 결정대로 모든 rank의 `ncclGinRestoreResume`이 이유와 함께 오류를 돌려준다.
- 정하는 자료(K15): 결정은 all-gather로 모은 기록 `all[]`만으로, 모든 p ∈ [0, nranks)에 대해, all-gather 바로 뒤 helper 소켓 잇기 전에 한다(hk의 비교 고리는
  rankStride 걸음이고 `why == nullptr`일 때만 돎, hk 6684–6689). 그래서 모든 rank가 같은 자리에서 같은 결과로 나간다. hold는 GIN 연결 FULL을 요구한다(RAIL이면
  collComm이 호스트마다 rank 하나라 기록 모음이 rank마다 다름, `gin_host.cc` 156–162). 투명 복구가 꺼진 rank는 all-gather 전에 돌아가므로(hw 6439) 그 변수도 모든
  rank가 같아야 한다(지금의 전제).
- 섞인 라이브러리(K16): `hk` rank는 이 규칙을 모르고 helper 잇기로 들어가 막힌다. 그래서 섞인 라이브러리는 지원하지 않는다고 적고, strict 비트는 복원 계층
  rank들이 무장하지 않게만 한다(hk rank가 섞이면 같은 오류가 모든 rank에서 돌아온다는 앞 문장은 틀림, 고침).
- 오류가 나오는 자리와 값(K14): 결정은 `createContext` 안(`gdakiTsSetup`)이므로 그 실패는 `ncclGinDevCommSetup`이 backend의 오류 값을 버리고 다음 후보 backend로
  넘어가게 하거나(`gin_host.cc` 454–468, INFO 한 줄), 남은 후보가 없으면 `ncclInternalError`("DevComm setup failed on all available backends", 471–472)로 돌려준다.
  `NCCL_GIN_TYPE=3`(이 저장소의 실행기)이면 `ncclInternalError`이고, 다른 backend가 active이면 NCCL이 그 backend로 devComm을 만들어 성공한다: 결정이 막으려는
  "조용히 복원을 끔"이다. 그리고 오류의 자리가 결정 문장의 "등록 오류"(window 등록 호출)에서 devComm 생성으로 옮겨졌다. 셋 가운데 사용자 선택이었다(아래 2026-10-11 사용자 결정으로 (b) + Resume 검사): (a)
  `gin_host.cc`를 조금 고쳐 복원의 오류를 그대로 넘기고 다음 backend로 넘어가지 않음(복원 계층 코드를 GDAKI 파일에만 둔다는 규칙을 깸), (b) 값은 `ncclInternalError`와
  복원 계층의 WARN 한 줄로 적고 hold 프로세스에 `NCCL_GIN_TYPE=3`(GDAKI만)을 요구함, (c) 오류를 `ncclGinRestoreResume`에서 돌려줌(communicator는 fail-fast로 쓸 수
  있음, "등록 오류"에서 더 멀어짐). 어느 것이든 오류의 자리에 대한 사용자 확인을 12절에 적는다. (b)만으로는 "조용히 끄지 않음"이 보장되지 않는다: NCCL의 안쪽
  plugin 목록은 GDAKI 옆에 GIN proxy를 늘 넣고(`plugin/gin.cc` 248–257) RMA backend가 있으면 그것이 active가 된다(`gin_host_proxy.cc` 702–709). hold의
  `numRmaCtx == 0`이 그 RMA backend를 없애는지는 `[미확인]`이고, GDAKI의 `createContext` 안에서는 `NCCL_GIN_TYPE=3`을 강제할 수 없다(거기서 오류를 내면 그것이
  proxy로 넘어감, K26). 그래서 (b)는 "(b) + `ncclGinRestoreResume`의 검사"로 적는다: Resume이 그 communicator의 복원이 거절됐거나 그 devComm이 GDAKI 투명 복구
  문맥이 아니면 오류를 돌려주고, hold 프로세스에 `NCCL_RMA_DISABLE=1`과 `NCCL_GIN_TYPE=3`을 요구해 Resume에서 확인한다. 이 에이전트의 생각: "(b) + Resume
  검사"가 규칙을 덜 깨고 결정 문장의 "조용히 끄지 않음"을 지킨다(K26으로 고친 권함).
- 자원 window의 자리(K17, K27): GDAKI 층은 `RegMrSym`에서 그 window를 알아볼 수 없다(`winFlags`도 부른 쪽도 넘어오지 않음, 등록은 `createContext`가 돌아오고
  `ncclGinFaultUserCtx`가 지워진 뒤, `gin_host.cc` 390, 419). 그래서 `ncclGinRestoreResume`에서 그 window를 찾고, 그 rkey 표를
  거기서 루프백 MR에 더한다. Resume은 devComm을 받아야 한다(9.4절의 `ncclGinRestoreResume(comm, &step, blob, &bytes)`에 `const ncclDevComm*`를 더하거나, 사용자
  devComm을 만들 때 기록해 둠). `devComm.resourceWindow`는 장치 handle이고, GDAKI 등록부가 `RegMrSym`에서 본 주소는
  `resourceWindow_inlined.lsaFlatBase + lsaRank·(stride4G << 32)`(= 그 메모리의 `primaryAddr`, `dev_runtime.cc` 1725–1727)이므로 그 주소로 찾는다(K27). `lb->mrs`는 잠금 없는 `std::vector`이고 helper 스레드가 읽으므로(hw 1452–1460, 1476) 더하기는 새 lb 잠금 안이나 `gdakiTsBusy`
  안에서 한다. 복원 등록부에 window 번호를 주어 로그와 rkey 바꾸기가 덮게 한다. 9.4절 (a)에 이름을 적었다. 크기 0인 자원 window(신호, 배리어, 자원이 없음)는
  없으므로 넘어간다.
- 안의 GIN devComm 검사 시점(K18): `ncclSymkInitOnce`는 사용자 devComm 뒤에도(뒤의 COLL_SYMMETRIC 등록, NCCL collective: `symmetric_sched.cc` 246,
  `task_posttuning.cc` 276) 돌 수 있다. 그래서 검사는 `ncclGinRestoreResume`에서 하고, 그 뒤 같은 comm 키로 사용자 문맥이 아닌 `createContext`가 오면
  DISARM한다(`gin_host.cc` 370–372). 7절의 복원 셀, 9.8절, `gin_rs.cu`에 `NCCL_SYM_GIN_KERNELS_ENABLE=0`(또는 COLL_SYMMETRIC window 없음)을 넣는다.
- 남았던 설계 선택 넷: hold 프로세스의 GDAKI 밖 backend, hold 프로세스에 `NCCL_SYM_GIN_KERNELS_ENABLE=0`을 요구할지, 명시적 오류의 자리와 값(위 (a)–(c)),
  rank 사이에서 `NCCL_GIN_RESTORE`만 다를 때. 아래 2026-10-11 사용자 결정으로 모두 정해졌다.

**2026-10-11 사용자 결정(설계 선택 넷, 원문 그대로).** "application이 복원을 요청했는데(ncclGinRestoreResume 호출) 켤 수 없으면, 이유가 무엇이든 그 함수가
이유와 함께 오류를 돌려준다. 모든 rank가 같은 오류를 받는다."

적용(메인 세션이 전함):
- hold 프로세스가 GDAKI 밖 backend에 있으면 `ncclGinRestoreResume`이 이유와 함께 오류를 돌려준다(전의 설계는 무장 조건의 WARN과 fail-fast였음).
- hold에는 `NCCL_SYM_GIN_KERNELS_ENABLE=0`이 조건으로 남고, 어기면 같은 Resume 호출이 오류를 돌려준다.
- 명시적 오류가 나오는 자리는 위 (b): devComm 생성에서는 `ncclInternalError`와 복원 계층의 WARN 한 줄, 그리고 Resume 호출이 "이 communicator는 복원할 수 없음"을
  이유와 함께 돌려준다. hold 프로세스는 `NCCL_RMA_DISABLE=1`과 `NCCL_GIN_TYPE=3`을 두어야 하고 Resume에서 확인한다.
- rank 사이에서 `NCCL_GIN_RESTORE`만 다르면 모든 rank의 Resume이 오류를 돌려준다.
- 결정 문장의 "등록 오류"(2026-10-11 첫 결정)는 이렇게 다듬어진다: 명시적 오류는 window 등록 호출이 아니라 Resume(과 devComm 생성)에서 나온다. 까닭: 한
  rank만 window 등록에서 오류를 내면 다른 rank가 rkey all-gather의 시간 제한 없는 고리에서 멈춘다(`net_ib/gin.cc` 138–202, 위 정의의 K1).
- Resume의 오류는 모든 rank가 같은 자료로 정한다(위 정하는 자료). 그래서 "모든 rank가 같은 오류를 받는다"는 all-gather 뒤의 결정과 같은 기록에서 나온다.

이로써 강제의 범위에 열린 충돌도, 남은 설계 선택도 없다. 강제와 Resume의 검사는 사용자 순서 (4)(체크포인트와 복원 경로 구현)에서 만든다. 비교 측정(9.15.6)은
이 결정과 무관하다.

**2026-10-12 사용자 결정(원문 그대로: "가로가야지").** 작업 묶음 2의 충돌 확인이 멈춘 물음 둘(12절 2026-10-11 마지막 행: 설정 합의 뒤의 지역 실패, 나머지 무장
조건)에 대해 메인 세션이 사용자에게 올린 선택지 (가)를 골랐다. 메인 세션이 전한 내용:
- `ncclGinRestoreResume`은 communicator의 모든 rank가 부르는 호출이다(다른 NCCL 집합 호출처럼). 그 안에서 rank마다 한 번, 자기 지역 판정("켤 수 있음" 또는
  "켤 수 없음과 이유")을 내놓고 communicator의 bootstrap으로 모은다. 지역 판정은 설정 때의 지역 결과(helper 소켓의 connect, accept, HELLO, 게이트 설정, NIC 복사
  경로의 설정과 자체 시험, 뒤의 측 표 할당)와 Resume 때 보는 모든 조건을 덮는다. 모든 rank는 모은 같은 자료로 정해 같은 결과와 같은 이유 문자열을 돌려준다(정한
  차례에서 처음 걸리는 이유).
- 앞의 사용자 규칙("이유가 무엇이든")에 따라 9.10.4절이 WARN과 fail-fast로 남겨 둔 무장 조건(문맥 하나, 재연결 변수, QP 감시, 복원 시한과 hold 한도, NIC 복사
  경로, 측 표, runtime connect와 NVLS, LSA 팀 등)은 모두 이유와 함께 Resume의 오류가 된다.
- fail-fast 프로세스는 Resume을 부르지 않으므로 `hk`와 같다.
- 이 결정이 대신하는 것: 12절 2026-10-11 행에서 이 에이전트가 낸 고를 길 (가) 설정 끝의 두 번째 GIN all-gather와 (나) 한계로 둠은 쓰지 않는다. (다)의 앞 반쪽
  (변수로 정해지는 무장 조건을 Resume 오류로)은 이 결정에 들어가되 기록 비트가 아니라 Resume의 모음으로 한다. 위 "Resume의 오류는 ... all-gather 뒤의 결정과 같은
  기록에서 나온다"는 "설정 기록의 결정과 Resume에서 모은 지역 판정에서 나온다"로 넓어진다(설정 기록의 결정은 그 모음의 한 항목으로 남음).
- 이 결정 아래 작업 묶음 2의 충돌 확인과 풀이는 12절(2026-10-12)과 9.14절 2번에 있다. 정한 것: 모음을 기다리는 한도 `NCCL_GIN_RESTORE_RESUME_MS`(기본 30 000 ms),
  넘으면 Resume이 그 communicator의 abort 깃발을 세워(`ncclCommAbort`의 첫 걸음과 같음) 모음을 풀고 오류를 돌려주며 그 communicator는 `ncclCommAbort`로만 끝낸다,
  두 번째 호출은 첫 호출의 결과를 모음 없이 돌려준다, 이미 장애가 application에 닿았으면 Resume의 오류다. 남는 한계 `[추론]`: 한도가 끝나는 바로 그때
  도착한 rank가 있으면 일부 rank는 모음을 끝내고 일부는 한도로 끝날 수 있다(모음을 끝낸 rank는 다른 rank의 abort를 실행 중 장애로 본다). abort 깃발은 자원을
  나누는 split의 communicator와 함께 쓰여 그것도 함께 끝난다. 마지막 오류 글은 프로세스에 하나라 그 사이 다른 스레드의 WARN이 이유를 덮을 수 있다.

**충돌 표(강제가 닿는 모든 자리; 2026-10-11 검토 K1–K12 반영).**

| 자리 | 지금 | 강제 뒤 | 처리 |
|---|---|---|---|
| `NCCL_IB_PCI_RELAXED_ORDERING` | 0: RO 끔, 1과 2(기본): ibverbs의 `ibv_reg_mr_iova2`가 있으면 RO 켬, 없으면 조용히 끔. 2.32.3에서는 1과 2가 같게 동작하고 1도 RO를 못 켤 때 실패하지 않는다(`net_ib/init.cc` 153–161, `gdakiRelaxedOrderingEnabled` hw 112–131, 기호 검사 `ibvwrap.cc` 211–216). 문서(`env.rst` 1240–1242)는 1이 실패한다고 쓰지만 코드는 아님 `[소스]` | 변수는 그대로 전역 기본값. hold 프로세스의 GDAKI window MR만 `FORCE_SO`가 이김(신호 표가 이미 그렇듯). 0, 1, 2 어느 것이든 오류 없음 | 1이면 첫 강제 등록에 WARN 한 줄("window MR strict despite NCCL_IB_PCI_RELAXED_ORDERING=1: hold policy", K11 (f)) |
| 사용자 flag `NCCL_WIN_STRICT_ORDERING` | 넘기면 `FORCE_SO` | 같음 | 충돌 없음 |
| `NCCL_WIN_COLL_SYMMETRIC` | symmetric 커널 초기화(`dev_runtime.cc` 1178–1181 → `ncclSymkInitOnce`). `NCCL_SYM_GIN_KERNELS_ENABLE=1`(기본, `sym_kernels.cc` 131)이고 LSA 팀이 communicator보다 작으면(이 배치의 lsaSize 1) 첫 `ncclCommWindowRegister` 안에서 내부 GIN devComm(RAIL, VA 신호; `sym_kernels.cc` 212–255)을 만들어 GIN을 켜고, 투명 복구가 아닌 GDAKI 문맥과 내부 자원 window를 만든다. 그 뒤의 window는 바로 GIN 등록(873–879). 이 저장소의 드라이버는 모두 이 flag를 씀(`gin_ts2.cu` 1005–1006, `gin_mr.cu`, `rs_spike.cu` 327–328) | 강제는 그 내부 window에도 걸림(비용만). 사용자 window의 등록이 사용자 문맥보다 먼저냐는 사용자 문맥을 기준으로 봄(위 정의) | 무장 조건을 더함(9.10.4절): 그 communicator에 NCCL 안의 GIN devComm이 없음(`NCCL_SYM_GIN_KERNELS_ENABLE=0`이거나 COLL_SYMMETRIC window가 없음). 그 내부 문맥도 죽은 rank로 가는 QP를 가지며 투명 복구가 아니라, 상대가 죽을 때 무엇이 application에 닿는지 `[미확인]`. hold는 이미 NCCL collective를 금함(9.7절 6번). 사용자 확인 권함 |
| 사용자 devComm의 자원 window(K3) | 사용자 GDAKI 문맥(1644) 뒤에 등록(`dev_runtime.cc` 1715–1723, `winFlags` 0). GIN 신호가 있으면 늘 있음(신호 그림자가 크기에 듦, 1637). 신호 그림자(`gin__funcs.h` 1113–1129)와 application이 요구한 자원 버퍼(원격에서 쓸 수 있음)가 든다 | 강제됨 | 복원 대상으로 넣음: 복원 계층이 devComm 생성 끝에서 그 window의 rkey 표를 루프백 MR에 더하고(RL9 넓힘, `gdakiLbAddRange`를 문맥 생성 뒤에 한 번 더 부름 `[추론]`) 체크포인트의 (a)에 넣음. "문맥 뒤 등록 window → 무장 안 함"에서 뺌 |
| `NCCL_WIN_GIN_ONLY` | GIN 등록만(`dev_runtime.cc` 47–58) | GIN MR이 strict | 충돌 없음(등록 능력 마스크 그대로) |
| `NCCL_WIN_CFT_COUNTED` | CFT 논리 끝점 묶기(IB MR 아님) | 그대로 | 충돌 없음 |
| 메모리 재사용과 동일성 | `winFlags`가 같은 같은 메모리만 재사용(736) | `winFlags`를 바꾸지 않으므로 그대로 | 충돌 없음. `winFlags`에 flag를 더하는 길은 쓰지 않음 |
| `ncclCommRegister`의 로컬 등록(`dev_runtime.cc` 1176) | net 경로의 로컬 MR | 강제가 닿지 않음 | 복원 대상이 아님(K11 (b)) |
| devComm 전 window, devComm 뒤 window, `ncclGinRestoreResume` 뒤 window | 미뤄진 등록(1486–1492) 또는 바로 등록(873–879) | 모두 강제. 사용자 문맥 뒤 사용자 window는 복원 대상이 아니고 무장 안 함(그대로) | 오류 길은 등록 호출에 없음(위 정의). 명시적 오류는 사용자 `ncclDevCommCreate`에서 모든 rank가 같이 |
| 정책을 아는 길과 rank 사이 불일치 | G1이 `gdakiTsSetup`에서 읽고 all-gather로 비교, 다르면 fail-fast(WARN, hk). G1 기록은 정책만 비교 | strict 비트와 `NCCL_GIN_RESTORE`를 G1 기록에 더함 | 정책이 다르면 WARN과 fail-fast(그대로), 모든 rank가 복원을 요청했는데 strict 비트가 0인 rank가 있으면 모든 rank의 명시적 오류(정의는 "다시 확인" 블록의 복원 요청, 자리와 값은 2026-10-11 사용자 결정: Resume이 이유와 함께 돌려줌) |
| 예비 프로세스 | 기록을 재생해 같은 rank로 초기화(9.15.4) | 예비 프로세스 모드에서는 늘 강제, strict 비트 1 | 예비 프로세스의 변수가 hold가 아니어도 강제(K4) |
| `ncclGinRestoreResume`을 부르지 않는 communicator | hold 프로세스여도 무장 안 함 | window는 강제됨(비용만) | 기록: hold 프로세스의 모든 GDAKI window는 strict |
| GDAKI가 아닌 GIN backend(proxy와 in-tree `net_ib`는 `FORCE_SO`를 따름 `net_ib/reg.cc` 30; 바깥 net plugin, GPI, EFA-GDA는 `[미확인]`) | hold여도 무장 조건 "투명 복구 GDAKI 문맥이 정확히 하나"를 못 채워 WARN과 fail-fast. devComm 생성에서 backend는 조용히 다음 후보로 넘어감(`gin_host.cc` 454–471) | 강제 hook은 GDAKI 안이라 닿지 않음. 그 window는 복원 대상이 될 수 없음 | 기존 WARN과 fail-fast를 둠(결정 문장은 복원 대상 window에 대한 것). 사용자 확인 권함: `ncclGinRestoreResume`이 "무장할 수 없음"(GDAKI 아님, 투명 복구 꺼짐, host RMA 켬 등 정적인 까닭)을 반환값으로 명시적으로 알리게 할지(검토 K Q3의 제안) |
| active backend가 둘 이상 | 모든 active backend에 등록(gin_host.cc 557–578). 뒤 backend가 실패하면 앞 slot이 새는 기존 동작(675–680은 다 된 조각만 지움, K11 (c)) | GDAKI backend의 MR만 강제 | 충돌 없음(강제는 실패를 만들지 않음) |
| LSA, NVLS | NVLink load/store, multicast(IB MR 없음) | 그대로 | 충돌 없음 |
| host RMA 등록(`symMemoryRegisterRma`, 684–691) | flag 없이 등록 | 그대로 | hold의 무장 조건이 host RMA 끔 |
| 여러 조각 window, host 메모리 조각 | 조각마다 `ncclGinRegister`(658–664) | 조각마다 강제 | 충돌 없음 |
| 루프백 MR과 복원 버퍼 | `gdakiLbAddRange`는 RO 없이 등록(hw 1504), 신호와 카운터 표는 strict(hr 7311–7312 / hw 7630–7631 / hk 7808–7809) | 복원 버퍼(rkey 표, 신호와 카운터 표, 로그 고리, 측 표)는 루프백 MR이라 strict. get의 sink 버퍼(hw 7883 / hk 8061)는 RO일 수 있으나 복원 버퍼가 아님 | 충돌 없음. 측 표는 drain 확인의 READ 대상이라 strict여야 함(9.4절 3단계) |
| gpu-detect `hk`의 hook(G1) | `gdakiTsSetup`에서 `getenv`, 사용자 투명 복구 문맥에서만(hw 6439) | 도우미 하나로 한 번 읽음(등록과 G1이 같이 씀) | `hk_layer.diff`(사전 등록 파일)는 고치지 않고 복원 계층이 G1을 도우미로 바꿈 |
| 9.10.4절의 옛 무장 조건 "window는 strict" | 어기면 WARN과 fail-fast | 무장 조건에서 뺌, 강제와 위의 명시적 오류로 바뀜 | 다른 무장 조건은 그대로 WARN과 fail-fast |
| B3 실행 가능성 기록(9.15.3, 9.11.12절 B3) | relaxed와 strict 모두 통과 | 사용자 결정으로 닫음 | 기록만 바꿈 |
| VA 신호 문서(device_gin.rst 155–156) | VA 신호는 사용자가 flag를 넘긴 window에서만 | `winFlags`를 바꾸지 않으므로 사용자 약속은 그대로 | 충돌 없음 |
| 장치 코드 | `winFlags`는 CFT counted만 읽음(`core__funcs.h` 212) | 바뀌는 장치 코드 없음 | 충돌 없음 |
| 성능 | window MR은 기본 RO 요청 | strict | 9.15.6에서 잰다(복원 계층 없이) |

### 9.11 통합 상호작용 표, 막는 문제, 정책 설계의 독립 검토

열: 장치와 코드 위치 / fail-fast에서 / hold-for-restore에서 / 우선 / 바꿀 것. "바꿀 것"의 G는 gpu-detect 계층에 넣을 정책 hook(9.11.10절), L은 복원 계층의
일(9.11.11절, 9.9절 RL), DV는 장치 헤더의 일(9.9절)이다.

#### 9.11.1 감지

| # | 장치와 코드 | fail-fast | hold-for-restore | 우선 | 바꿀 것 |
|---|---|---|---|---|---|
| D1 | 장치 분류와 기록 경로(S1). 붙잡은 상대의 처리는 HELD, COMMITTING에서 흡수, PUBLISHED에서 fallback(9.10.7절, P3). 경로 판단은 Q4 감시 스레드(hr 1021, false면 1026–1035에서 비동기 오류), 처리는 helper의 기록 루프 hr 6114–6124 / hw 6399–6409 → `gdakiTsInitiate` hr 5419– / hw 5448– | 기록 → 라운드: liveness 확인 → 살아 있으면 복구, 죽었으면 거절(hr 5478–5489 / hw 5507–5518) | 경로 판단은 그대로 참(helper로; F28). 살아 있는 상대: 같음. 붙잡은 상대의 기록: 라운드를 열지 않고 흡수(`qs[].handled` 올림). 루프의 뒷정리(`ts->batch`, heartbeat, `nQueued` 줄이기)는 그대로 둠(V16) | 감지(반응은 정책) | G4. L: 흡수 |
| D2 | hw QP 상태 감시(S2) | 거절 안 된 모든 상대의 QP를 10 ms마다 QUERY_QP. ERR/SQER + 유예 5 ms(뿌리 CQE 없으면 50 ms) → 합성 기록 → D1 | HELD와 COMMITTING의 상대는 감시하지 않음(QUERY_QP도, QP와 CQ의 NIC 읽기도 없음). PUBLISHED는 감시함(P3). 이미 줄에 선 기록은 D1처럼 흡수. 복원 뒤(QP가 예비 프로세스와 RTS) 다시 감시. 감시의 에폭 비교(`gdakiDetQueued` hw 6066, `handled >= epoch + 2` hw 6139)는 빈 라운드(M3)에 맞춰 `coveredEpoch`로 | 감지 | G3, G6 |
| D3 | 감시의 펌웨어 명령 부하(S2) | rank마다 (상대 수 × 문맥 수)번/10 ms, `opMu` 안 | 이 rank에서는 hold 시작과 복원 라운드와 겹치지 않음(같은 helper 스레드, 감시는 기록 줄이 빌 때만 hw 6410). 같은 NIC의 다른 rank의 감시와 예비 프로세스의 초기화(QP 생성, MR 등록)는 겹침. 복원 라운드의 펌웨어 단계가 3 000 ms를 넘으면 감시가 그 상대의 단어를 올림 → TOLD → fallback. 감시의 QUERY_QP가 응답 쪽 rmsn도 받아 누적 실행 수에 쓰므로(G7) 누적을 위해서는 복원 계층이 따로 펌웨어 명령을 내지 않음. 체크포인트의 drain 확인(9.4절 3단계)은 예외로, r이 응답 QP마다 체크포인트당 몇 번 QUERY_QP를 낸다(예상 drain 시각에 처음, 그 뒤 50 µs 이상 간격, 상한; B3 설계 검토 T3-8, 2026-10-09) | 펌웨어 감시 | G7. L: 복원 셀에서 `detQueryUsMax`와 복원 단계 시간을 잼 |
| D4 | helper 소켓 liveness(S3). 다시 걸지 않음: `gone`/`declined` 상대(hr 3972, 4069 / hw 3997, 4094). HELLO는 낮은 rank에서만, 더 새 세대만(hr 4209–4215 / hw 4234–4240). 거절한 상대에는 FAIL(hr 3910–3923, 4176–4180, 4204–4207 / hw 3935–3948, 4201–4205, 4229–4232). nonce(hr 6237–6239 / hw 6523–6525). 다시 걸기(hr 4046–4064 / hw 4071–4089), 받기 한 번에 500 ms까지 읽음(hr 4175 / hw 4200) | 죽음 → `deadJudged` → 거절(R1) | 판정과 그 줄은 같음. 반응만 다름(R1). 새 프로세스 받기: 새 메시지 REJOIN을 받기 루프(hr 4164–4243 / hw 4189–4268)에서, 붙잡은 상대에게서만, nonce가 맞고(초기화 재생으로 같은 nonce) 화신 번호 = 지금 + 1일 때. 아직 붙잡지 않은 rank는 REJOIN을 닫고, 예비 프로세스는 시한까지 다시 건다(V6). 받으면 `gone`, `deadJudged`, `refusals`, `left`, `peerFailed`, `failedPending`, `lostCause`, `closeCause`, `lostAfterCommit`(9.10.5절, 2026-10-09)를 지우고, 옛 주소로 진행 중이던 `dialFd`/`pendFd`/`probeFd`를 닫고(늦은 ECONNREFUSED가 새 화신의 죽음으로 세어지지 않게, hr 4032–4036 / hw 4057–4061), 공통 연결 세대를 정해 `gdakiTsInstall`(hr 3859–3872 / hw 3884–3897; F22). 펜싱(F11): HELLO, HELLO-ACK, PROBE-ACK에 화신 번호를 싣고 생존 rank는 지금 화신이 아니면 받지 않음. 예비 프로세스는 설치되기 전에는 REJOIN 말고 아무것에도 답하지 않고, 원래 rank의 listen 주소(기록에 있음)와 다른 포트에 묶음. REJOIN은 고정 크기 제어 메시지이고, rkey 목록 같은 큰 것은 자료 소켓으로(F23) | 감지 | L. hw 변경 없음 |
| D5 | 감시(S4) | 펌웨어 단계 초과 → 그 상대의 단어 + 비동기 오류 + 책임(그 상대, Local)(hr 3476–3516 / hw 3501–3541, 책임 hr 3505 / hw 3530). 라운드 25 s 초과, 기록이 쌓였는데 helper가 1 s 넘게 정지 → 드러냄, 이후 모든 라운드 거절(hr 3517–3525 / hw 3542–3550) | 같음. 다만 붙잡은 상대에 대한 펌웨어 초과의 책임 원인은 PeerDead로 적음(G9: 안 그러면 Local 책임이 남아 fallback 뒤 shrink 넘기기가 −3을 돌려줌, V1). 복원 기다림은 라운드가 아님(heartbeat 계속). 복원 상태 기계의 한 걸음은 1 s보다 짧게: 소켓 읽기, 로그와 이미지의 NIC 읽기는 조각으로(고정 사본 크기 = max(CQ 크기 × 64 B, 장치 QP 구조) + 4 KiB, hr 1899–1901 / hw 1900–1902), 기록은 흡수되어 쌓이지 않음(F14). hold 시작과 복원 라운드는 `gdakiTsBusy` 안. 복원 시한은 이 감시 스레드가 지킴(G8, V5): helper가 다른 라운드에 묶여 있어도 시한에 HELD에서 CAS(HELD → TIMED_OUT)에 이기면 그 상대의 단어(PEER_DEAD), 비동기 오류, 책임(PeerDead), degraded 예약을 CPU 쓰기로(hw 감시처럼 `gdakiTsToComm` 안에서) 하고(PUBLISHED에서는 CAS로 상태만, P1), 게이트 실패 쓰기와 FAIL은 helper가 풀리면 fallback 거절로 마저 함(이중 거절은 무해: 단어의 first, degraded의 `deadMs`, 책임의 중복 막기, `!pe.declined`; 검토 2 확인). COMMITTING은 건드리지 않음(9.10.7절, N1) | 감시 | G8, G9, L |
| D6 | 장치의 포기와 훑기(S5) | 포기 → 거절(원인 Local, hr 5892–5893, 5898 / hw 5921–5922, 5927). 기록 유실 두 번 → 거절(hr 5894–5896 / hw 5923–5925) | 포기는 TOLD. 붙잡은 상대에 대한 훑기의 거절은 G2가 fallback(PeerDead)으로 바꿈(V1). 유실 검사: 흡수가 `handled`를 올리므로 보통은 조용함. 장치 기록 우편함이 넘친 경우 HELD, COMMITTING의 상대는 건너뜀 | 장치 실패(TOLD) | G2, G5 |
| D7 | NVSHMEM t1w FIN 판정(S6) | BYE 없는 FIN → 바로 `t1_decline` | NVSHMEM에는 hold가 없음. hold 정책의 프로세스는 NVSHMEM을 쓰지 않음(X6) | NVSHMEM fail-fast | 없음(제약) |

#### 9.11.2 반응

| # | 장치와 코드 | fail-fast | hold-for-restore | 우선 | 바꿀 것 |
|---|---|---|---|---|---|
| R1 | 거절 `gdakiTsDecline` hr 4916–4966 / hw 4941–4991: 범위 ALL(hr 4919 / hw 4944), 준비 풀기(hr 4930 / hw 4955), QP를 ERR로(hr 4931–4934 / hw 4956–4959), 책임 기록, 상대 단어, 비동기 오류(hr 4936–4943 / hw 4961–4968), FAIL, 게이트 실패(hr 4959–4965 / hw 4984–4990). 죽음이 이 함수에 오는 길: helper 루프(hr 6095–6101 / hw 6380–6386), 라운드의 죽음 길(hr 5478–5489 / hw 5507–5518). 라운드 안의 소켓 끊김(hr 5566–5572, 5594–5600 / hw 5595–5601, 5623–5629)은 보통 거절이 아니라 취소(`gdakiTsCancelRound` hr 5127–5146 / hw 5152–5171, 응답 쪽 `gdakiTsCancelResponder` hr 5152–5173 / hw 5177–5198)로 가서 상대를 "모름"으로 두고 기록을 다시 줄에 세움. 죽은 상대는 다시 걸기와 탐침의 거절 둘로 죽음이 되고, 다시 줄에 선 기록의 라운드(죽음 길)나 helper 루프에서 거절로 옴 | 위 모두 | 거절 맨 앞의 정책 hook(G2), 두 갈래: (가) 그 상대가 이미 붙잡은 상대면 어떤 거절이든(원인, `uaWhy` 무관) fallback 함수 하나로: PeerDead, `GDAKI_UA_PEER_DEAD`로 한 번 거절하고 다시 붙잡지 않음(V1). (나) 붙잡지 않은 상대: 정책 hold, 상대 ARMED, 강한 죽음 증거(9.10.5절), TOLD 아님 → 9.10.7절의 hold 시작, 돌아감. 그 밖은 거절 그대로 | 9.10.5절 | G2 |
| R2 | 상대별 abort 단어(hq, `gdakiUaRaisePeer` hr 2793–2862 / hw 2800–2869; 배열 hr 2705–2755 / hw 2712–2762). 장치: `tsWaitWord` gin_gdaki.h 241–245, `tsParkStable` 271–277, `tsPoll` 1123–1139, 보내기 `tsPosterAbortWord` 223–228, `tsQpWordError` 230–233 | 거절이 그 상대의 단어를 바로 올림: 그 상대 QP의 대기, flush, 쉬는 보내기가 바로 실패 | 복원 중에는 올리지 않음. 쉬는 스레드는 64번마다 단어를 읽지만 0이라 계속 쉼(hold 한도까지, T4). fallback(또는 G8의 시한)에서 올림. 단어는 communicator마다라서 문맥이 둘 이상이면 무장하지 않음(9.10.4절, F6) | 9.10.5절 | 없음 |
| R3 | degraded(hr 2826–2840, 2867–2894 / hw 2833–2847, 2874–2901; `NCCL_GIN_TS_DEGRADED_MS` hr 2690 / hw 2697), "모든 상대 거절" 규칙(hr 2813–2824 / hw 2820–2831) | 첫 죽음 거절(PEER_DEAD) 2 s 뒤 칸 0: `waitSignal`, `waitCounter`, 배리어가 오류. 랭크 2개는 바로. 원인 Unknown의 거절(9.10.7절의 응답 쪽 Commit 뒤 길)은 degraded를 예약하지 않음(hw의 틈). gpu-detect가 고친 뒤(9.10.5절 `pe.lostAfterCommit`, 2026-10-09)에는 그 길의 죽음 판정이 PEER_DEAD 거절이 되어 degraded를 예약함 | 복원 중에는 예약 없음. fallback 거절(PEER_DEAD) 또는 G8이 예약 → 칸 0은 fallback + 2 s(랭크 2개는 fallback 때 바로) | 9.10.5절 | 없음 |
| R4 | `NCCL_GIN_TS_DEGRADED_ROUNDS`(hw M-C, `gdakiUaPeerRaised` hw 2918–2925, 변수 2676) | 0(기본): 칸 0이 오르면 어느 상대와도 라운드 게시 없음, 그 거절은 원인 Local | hold 자체는 칸 0을 올리지 않으므로 이 규칙은 복원 중 잠자고 있음. 복원 중 칸 0이 다른 이유로 오르면(abort, revoke, shrink, 모든 상대 거절, 다른 rank의 죽음의 degraded) 복원 라운드의 게시 전 확인(`gdakiTsRepostPlanAll` hr 4566 / hw 4591, `gdakiTsRepostApply` hr 4708 / hw 4733)이 막음 → fallback | 칸 0(TOLD) | 없음. fail-fast의 변수로 문서화 |
| R5 | 비동기 오류와 문맥의 sticky 오류(거절이 세움 hr 4939–4942 / hw 4964–4967; `tsFail` gin_gdaki.h 1047–1053; Commit은 helper 안에서 지우지 않음 hr 2492–2512 / hw 2493–2513) | 거절 때 비동기 오류. sticky는 실패한 장치 스레드가 그 문맥에 세움 | 복원 중에는 비동기 오류 없음. 비동기 오류가 서 있거나 그 상대의 QP에서 장치 스레드가 실패했으면 TOLD → hold 안 함 | TOLD | 없음 |
| R6 | t1w fail-stop과 장치 대기 단어(ibgda.cpp `t1w_after_decline` 6841–6858, `t1w_failstop_exit` 6813–6839, `t1_decline`의 호출 6925, 변수 8047–8049; 장치 `nvshmemi_t1w_aborted` wait_until.cuh 41–56) | 0(기본): 거절 직후 `_exit(70)`. −1: 장치 대기 단어를 올려 PE의 모든 대기를 "풀린 채" 돌려줌. 양수: 단어를 올리고 그만큼 뒤 종료 | NVSHMEM에는 hold가 없음. 이 변수들은 NVSHMEM fail-fast 반응의 변수다. NVSHMEM에 hold를 넣는다면 `t1_decline`의 맨 앞에 G2와 같은 hook을 두는 것이 같은 구조다(범위 밖) | NVSHMEM fail-fast | 없음(문서화). X6 |

#### 9.11.3 복구 기계

| # | 장치와 코드 | fail-fast | hold-for-restore | 우선 | 바꿀 것 |
|---|---|---|---|---|---|
| M1 | 라운드: 쌍 범위와 전체 재설정(`gdakiTsDecideScope` hr 3315–3375 / hw 3340–3400), NACK 12(hr 5611–5619 / hw 5640–5648), 범위 충돌(hr 5639–5653 / hw 5668–5682), 커밋 전 계획과 NACK 15/16(hr 4542–4570, 5621–5627 / hw 4567–4595, 5650–5656), 중첩 응답 라운드(`gdakiTsServeLower` hr 5315–5378 / hw 5341–5407, hw M-A: 한 번에 하나), 미룬 REQ(hr 6023–6056 / hw 6308–6341). 모르는 메시지 종류: 시작 쪽 ACK 기다림이 무시(hr 5685 / hw 5714), 미룬 REQ 뒤 무시(hr 6048 / hw 6333), 기다림 안 응답이 무시(hr 5373 / hw 5402), 응답 쪽 DONE 기다림은 살아 있는 상대를 거절(hr 5284–5286 / hw 5309–5311) | 그대로 | 살아 있는 상대와는 그대로(복원 중에도). 라운드 도중의 죽음은 R1. 새 제어 메시지(CKPT_*, HOLDING, DISARM, NOHOLD, FALLBACK, RESTORED)는 설치된 소켓으로 오므로 위의 모든 기다림에서 버리지도, 거절의 이유로 삼지도 않고 그 상대 칸에 미룸(F7 (a)). REJOIN은 listen 소켓으로 와서 받기 루프까지 backlog에 남음. 제어 메시지는 고정 크기이고 helper 스레드만 씀(`gdakiTsPumpRaw`가 정확히 한 레코드를 읽고 magic을 봄 hr 3657–3679 / hw 3682–3704: 섞이면 BADMAGIC → 죽음, F7 (c)) | 라운드(살아 있는 상대) | L |
| M2 | 정확히 한 번: 응답 쪽 실행 수(`gdakiTsExecuted` hr 4330–4348 / hw 4355–4373, 화신마다 mod 2^24 hr 4342 / hw 4367; `gdakiTsBaseline` hr 4351–4367 / hw 4376–4392, 2RST가 rmsn을 0으로 안 할 수 있음 hr 4361–4363 / hw 4386–4388), 다시 보내기 계획과 적용(hr 4552–4897 / hw 4577–4922), 장치의 `lbase` 다시 매핑(`tsPoll` gin_gdaki.h 1086–1095), 비메시지 표시(`gdakiTsNonMsg`, 라운드가 거절에 씀 hr 5548, 5810 / hw 5577, 5839; 게시 때 지움 hr 4875 / hw 4900; get은 READ 표시 gin_gdaki.h 709) | 상대가 REQ/ACK로 알려 준 rmsn으로 실행 안 된 WQE를 다시 보냄 | 죽은 쪽 QP는 없어 QUERY_QP를 못 함. (a) 생존 rank → 죽은 rank: SQ에서 다시 보내지 않고 모든 옛 WQE를 실행된 것으로(계획 `U = S, n = 0`: `lbase += S`), 효과는 생존 rank의 로그를 예비 프로세스에 적용해 넣음. 순서와 번호는 로그 항목 번호와 통로의 누적 메시지 수. 복원 라운드는 게시 전에 `gdakiTsNonMsg`를 읽어 READ(또는 get이 남았다는 DUMP)가 있으면 fallback(F2). 생존 rank가 p로 get을 내면 그때 DISARM(p)(9.10.4절). (b) 죽은 rank → 생존 rank: 생존 rank의 응답 쪽 QP는 남아 있어 누적 실행 수 X를 읽음. 누적은 화신마다의 증분(mod 2^24)을 감시의 QUERY_QP(G7)와 기준 바꿈(Baseline) 때마다 더해 만들고, 복원 라운드는 2ERR 뒤, Commit 전에 한 번 더 읽음(F19). 표본 사이에 한 QP로 2^23개보다 많은 메시지가 오면 wrap을 놓치므로 이 율을 무장 조건의 한계로 적음(V14 `[추론]`). 억제 예산 X − P. 단위는 RC 요청 메시지. (c) 되살린 rank의 get(V7): READ도 응답 쪽 MSN에 들어 X − P에 섞이고 생존 rank는 WRITE와 가르지 못함 → 결정성 요구(9.7절 8번, 검사하지 않는 application 요구). 억제 느린 길이 예산이 남은 QP에 들어온 get을 직접 실패로 표시하고(예산이 남은 동안의 get은 게시 전에 억제 길로 오므로 READ 표시 gin_gdaki.h 709는 서지 않음), 예비 프로세스의 helper가 그 표시를 보면 복원 실패(FALLBACK(p)). NOP, DUMP는 메시지가 아니라 예산을 쓰지 않음 | 복원 | L, G7 |
| M3 | 낡은 기록 검사(hr 5431–5435 / hw 5460–5464), 범위 판단의 산 기록 검사(hr 3336 / hw 3361), hw 감시의 에폭 비교(D2)와 장치의 에폭 회계(`tsPoll` 1106–1116: 에폭이 바뀌면 `notEpoch`로 쉼) | 빈 라운드 없음 | 체크포인트의 입력 멈춤은 에폭을 홀수로 했다가 +2로 게시(빈 라운드: 같은 짝수로 돌려놓으면 `notEpoch`로 쉬던 대기가 hold 한도까지 쉬다 포기함). 그러면 에폭을 쓰는 모든 비교가 빈 라운드를 진짜 라운드로 봄 → 모두 `coveredEpoch`(진짜 라운드와 거절만 올림; 복원 라운드의 게시도 진짜 라운드라 올림)로(F12). 빈 라운드는 `nonmsg`와 `swErr`를 지우지 않음(멈춤 전에 낸 get이 날아가는 중이면 잊지 않게, V17). fail-fast에서는 빈 라운드가 없어 `coveredEpoch == epoch` | 정확성 | G6, L |
| M4 | Prepare/Commit(`ncclGinRecoverPrepare` hr 2143–2330 / hw 2144–2331, Commit hr 2334–2529 / hw 2335–2530; 토큰 검사 hr 2350–2369 / hw 2351–2370, 다시 연결 hr 2450 / hw 2451, drain hr 2257–2303 / hw 2258–2304, 새 PSN hr 2308 / hw 2309) | 살아 있는 상대와의 라운드 | 복원 라운드: Prepare(p)(2ERR은 hold 시작에서 이미, drain: 죽은 상대로 간 WQE는 flush 오류 CQE로 끝남 `[추론, 미확인]`), `rq.exch`를 예비 프로세스의 끝점으로(`opMu` 안; 토큰 검사가 `rq.exch.qpn`을 보므로 먼저), Commit. 양쪽 토큰 교환(F10)의 차례: REJOIN(예비 프로세스의 QPN, 보내기 PSN) → 생존 rank Prepare → 생존 rank 토큰(QPN, 새 보내기 PSN)을 예비 프로세스에 → 예비 프로세스가 그 PSN으로 자기 QP를 RTR/RTS로 잇고 READY → 생존 rank Commit(예비 프로세스의 PSN을 받는 PSN으로), Baseline, rkey 바꿈, 게시 → DONE_RS. 예비 프로세스는 초기화 재생 때 QP를 만들기만 하고 잇지 않는다. 새 QPN이 기록의 죽은 QPN과 같은지 보고 남김(같은 NIC의 QPN 재사용 `[미확인]`; 생존 rank의 QP는 hold 시작에서 ERR이라 옛 패킷을 다시 보내지 않음) | 복원 | L |

#### 9.11.4 한도와 감시

| # | 장치와 코드 | fail-fast | hold-for-restore | 우선 | 바꿀 것 |
|---|---|---|---|---|---|
| T1 | 확대 상한 8회/60 s(`gdakiTsEscalated` hr 5081–5102 / hw 5106–5127; 쓰는 곳: 시작 쪽 hr 5444, 5503–5508 / hw 5473, 5532–5537, 응답 쪽 hr 5786 / hw 5815; 멈춘 표시 hr 5083–5086 / hw 5108–5111) | 그대로 | 살아 있는 상대의 라운드는 그대로 셈. 복원 라운드와 빈 라운드는 복구 라운드가 아니므로 세지 않음(`count = false`). 상한으로 멈춘 문맥은 무장하지 않음(9.10.4절, F26) | 상한 | L |
| T2 | 펌웨어 단계 감시(D5) | 그대로 | 복원 라운드의 펌웨어 단계(2ERR, 2RST, INIT/RTR/RTS, Commit 전 QUERY_QP)는 가드 안 → 초과는 TOLD → fallback. 체크포인트와 누적용 QUERY_QP는 가드 밖(hw 감시와 같은 이유: 가드 안에서 SIGSTOP이 오면 감시가 산 쌍의 단어를 올림, gpu-detect 리뷰 M1; F21) | 감시 | L |
| T3 | 라운드 감시 25 s, 쌓임 감시 1 s(D5) | 그대로 | 복원 기다림은 라운드가 아님. hold 시작과 복원 라운드는 Busy 안. 상태 기계의 한 걸음은 1 s 안(D5) | 감시 | L |
| T4 | 장치 대기의 hold 한도(게이트 `waitMs` = `NCCL_GIN_TS_HOLD_MS` 30 000, hr 6820 / hw 7128; `tsParkStable` gin_gdaki.h 255, 278–294), `roundMs`는 `gdakiTsStart`에서 정함(hr 6741 / hw 7046), 재연결 기다림의 한도(hr 6773–6778 / hw 7081–7086), helper가 다른 일에 묶이는 시간(라운드 `roundMs`, 재연결 기다림 hr 5461–5472 / hw 5490–5501, 정지 `quiesceMs`) | 라운드를 기다리는 장치 스레드의 한도 | 쉬는 스레드의 시계는 게이트가 처음 홀수가 된 때부터 감(F13). HELD의 실제 시한 = min(hold 시작 + `NCCL_GIN_RESTORE_MS`, 게이트가 홀수가 된 시각 + `holdMs` − 복원 라운드 몫 − 여유). PUBLISHED의 시한은 게시 시각 + `NCCL_GIN_RESTORE_MS`(장치 대기가 붙잡혀 있지 않아 hold 한도 항이 없음, P1). 시한은 Q4 감시 스레드가 지키므로(G8) helper가 묶여 있어도 늦지 않음(V5). 관계 검사는 `gdakiTsStart`에서. 어기면 그 communicator는 fail-fast(WARN). 포기는 TOLD → fallback | hold 한도 | G8, L |
| T5 | 복사 한도 2 000 ms와 NIC 루프백(hr 1232, `gdakiRecCopyWait` 1388–1440, `gdakiLbXfer` 1586–1668 / hw 1232, 1388–1440, 1587–1669), 루프백 설정과 자체 시험(hr 6474–6735 / hw 6761–7040, hw L-C: NIC만으로 시험), MR 목록(`gdakiLbAddRange`는 설정 때만, CUDA driver 함수를 부름 hr 1498, 1508, 1522 / hw 1499, 1509, 1523; 잠금 없는 찾기 hr 1475–1479 / hw 1476–1480), MR이 없으면 스트림 복사(CUDA 호출, hr 1721–1729 / hw 1722–1730; 묶임 hr 1377–1386 / hw 1377–1386), NIC 경로 끄기(`gdakiLbOff` hr 1483–1496 / hw 1484–1497) | 그대로 | 복원이 쓰는 GPU 메모리는 문맥을 만들 때만 루프백 MR에 넣음(실행 중 등록 없음, V12). 복원 라운드는 rkey 표와 신호 표의 칸 p를 모두 쓴 뒤 READ 하나로 GPU 메모리에 닿았음을 확인하고 나서 게시함(검토 3 W5, A1 (3)). 그 뒤 등록한 window가 있으면 무장 안 함(9.10.4절). 무장된 communicator에서 window 등록 해제(hr 7945 / hw 8264에서 rkey 표를 풂)가 오면 잠금 안에서 DISARM을 먼저 세우고, helper는 같은 잠금 안에서 그 표시와 `ts->stop`을 본 뒤에만 rkey 표에 씀(orphan helper 포함, F15). 풀린 rkey 표를 덮는 루프백 MR은 helper가 DISARM 때 해제(그 전까지 dmabuf 참조가 남는지는 `[미확인]`). `gdakiLbXfer`는 helper 스레드 하나만 씀(스테이징, 루프백 CQ). 자료 스레드는 호스트 버퍼의 소켓 입출력만(F14). NIC 경로가 꺼지면 fallback(V8) | 복사 한도 | L |

#### 9.11.5 끝점과 메모리

| # | 장치와 코드 | fail-fast | hold-for-restore | 우선 | 바꿀 것 |
|---|---|---|---|---|---|
| A1 | rkey와 주소: window rkey는 등록 때 all-gather(`ncclGinGdakiRegMrSym` hr 7879–7931, all-gather 7902–7905 / hw 8198–8250, 8221–8224), 신호와 카운터 표의 교환(hr 7311–7315 / hw 7630–7634). 장치: 원격 주소는 window 안의 오프셋(gin_gdaki.h 475), rkey는 게이트 전에 읽음(476, 게이트 501; `signalKey`는 호출자가 계산해 값으로 넘김 1458–1468), `loadConst`는 보통 읽기(`utility.h` 449–457) | rkey는 communicator가 사는 동안 고정 | 예비 프로세스의 MR은 새 rkey. 생존 rank는 그 상대로 가는 게이트가 홀수인 동안 모든 window rkey 표와 신호, 카운터 표의 칸 p를 NIC 루프백으로 바꾸고 짝수 에폭을 게시. 그러나 키는 게이트 전에 읽히므로, 게이트가 홀수일 때 옛 키를 읽고 게시 뒤 빠른 경로로 들어간 보내기는 옛 키로 보냄(F5): 남의 MR이 그 키 값을 다시 받으면 조용한 손상 `[미확인]`. 해결은 키 읽기를 게이트에 들어간 뒤로 옮기는 것(DV3)이고, `signalKey`의 계산 자리를 옮기는 구조 변경과 읽기 종류의 변경(L1 적중을 잃을 수 있음)이 따름 → 9.11.12절 B4(이 문장은 결정 전의 것: 결정 (나)는 옮기지 않고 hold에서만 다시 읽음, 검토 3 W9). **결정 (나)(2026-10-09, 검토 3 반영)**: (1) 갈림과 자리: 측 표 포인터(DV1, `loadConst`로 게이트 전에 한 번; 문맥을 만드는 중 `gdakiTsStart`에서 한 번 쓰고 그 뒤 바뀌지 않음, 9.10.4절)가 0이 아니면, `tsGateEnter`가 참을 돌려준 뒤(빠른 길이든 느린 길 `tsGateEnterSlow`든) 키를 다시 읽어 덮어씀. `putImplMode`는 게이트(501) 뒤, 보내기 갈림(509) 앞에서 읽어 `tsTestSplitPut`(516)도 새 키를 씀. `raddr.key`(`dstMh->rkeys[peer]`)는 `hasWins`일 때만(신호만 보내는 길 526–533에서는 `dstMh`가 없을 수 있음), `sig_raddr.key`는 키 주소가 null이 아닐 때만 다시 읽음. `putValueImplMode`는 게이트(604) 뒤에 같은 것(window는 늘 있음). `getImplMode`도 게이트(704) 뒤에 `raddr.key`(`remoteMh->rkeys[peer]`, 697)를 다시 읽음(검토 3 W3: 복원을 건너는 커널의 get이 L1에 남은 옛 키를 쓰지 않게; 같은 포인터의 분기 하나). 다시 읽기는 L1을 거치지 않는 시스템 범위 relaxed 32비트 읽기(`ld.relaxed.sys`, 게이트 안의 다른 호스트 쓰기 칸을 읽는 `tsLoadRelaxedSys64` 390, 404, 769와 같은 종류; 쓰는 쪽이 NIC이므로; 검토 3 W4). (2) `signalKey`는 지금처럼 호출자가 계산해 값으로 넘기고(gin_gdaki.h 1458–1468, 1483–1494) fail-fast는 그 값을 씀. 호출자는 그 키를 읽은 주소(`signals_table.rkeys + peer`나 `signalMh->rkeys + peer`, 신호가 없으면 null)를 장치 헤더 안의 내부 인자 하나로 더 넘김(공개 API는 같음). (3) 차례의 근거: 생존 rank의 helper는 p로 가는 게이트가 홀수이고 개수가 0일 때 모든 window rkey 표와 신호 표의 칸 p를 NIC 루프백으로 쓰고, 다 쓴 뒤 READ 하나로 GPU 메모리에 닿았음을 확인한 다음(검토 3 W5; 9.3절 7단계, RL9, T5) `gdakiTsRepostApply`의 게시(hw 4906)로 짝수 에폭을 냄. 게이트에 든 스레드는 개수 0 전에 나갔거나 게시 뒤에 들어왔고, 진입은 acquire 원자 더하기(`tsWordEnter` 126–130)라 그 뒤의 strong 읽기가 앞당겨지지 않고 L1의 옛 줄을 보지 않으므로 새 키를 읽음 `[추론]`. (4) fail-fast(포인터 0): 키 읽기의 자리, 종류(`loadConst`, L1 적중), 명령 차례가 지금과 같음. 더해지는 것은 put과 putValue에서 분기 하나(DV2와 같은 포인터 읽기)와 내부 인자 하나(검토 3 W8), get에서 포인터 읽기 하나와 분기 하나다(DV2는 get에 포인터 읽기를 더하지 않음, 검토 3 재확인 X3). 결과는 같다. (5) hold: 키를 두 번 읽고(호출자의 게이트 전 읽기는 버려짐) 게이트 뒤 읽기는 L1 적중을 잃음. 무장 전에도(문맥을 만든 때부터) 그렇다. 비용은 계층을 만들 때 4 KiB, 256 KiB에서 잼(LT1, LT2와 다시 읽기만 따로 재는 셀, 7절). (6) 억제(C6): 느린 길이 SUPPRESS로 내지 않으면 다시 읽기도 없음. 일부만 내거나(신호만) 그대로 내면 참을 돌려준 뒤 같은 자리의 다시 읽기를 지남. 억제는 예비 프로세스에서만 서고 그 프로세스의 생존 rank 키는 바뀌지 않으므로 다시 읽기는 같은 값을 읽음. C2의 coop에서는 게이트를 잡은 0번 스레드가 보내기 전에 읽음. (7) 다시 읽지 않는 것: 카운터 키(자기 rank 칸 493, 바뀌지 않음), flush의 mcst(로컬 lkey, 755). 상대 rkey를 읽는 장치 자리는 476, 592, 697, 1461, 1464, 1487, 1492뿐이고 DOCA의 한쪽 연산 도우미는 키를 값으로 받음(검토 3 W7). 투명 복구는 companion(카운터) QP가 있으면 켜지지 않으므로(hw 2180, 6446) hold에서 카운터 길은 쓰이지 않고, 카운터 표의 칸 p 바꿈은 해가 없는 헛일이다 | 복원 | DV3, 9.11.12절 B4 |
| A2 | get 표(Commit이 지움 hr 2436–2446 / hw 2437–2447) | 그대로 | 복원 라운드의 Commit이 그 상대의 get 표를 지움. get은 M2대로 없음 | 복원 | 없음 |
| A3 | GIN collComm 고리(gin.cc 138–229, 연결 231–259: 고리 이웃과 실제로 잇고 받음), helper 설정의 잇기와 받기(hr 6255–6308 / hw 6541–6594: 여기서만 `gated`, `addr`가 섬 hr 6281–6284, 6303–6306 / hw 6567–6570, 6589–6592; 게이트는 `gated` 상대에만 씀 hr 6813–6831 / hw 7121–7139) | rank 하나가 죽으면 고리가 끊겨 그 communicator에서 GIN 집합 교환(새 window 등록, devComm 생성)을 더 못 함 | 같음. 예비 프로세스의 GIN 초기화는 all-gather 대답뿐 아니라 고리 연결과 helper 설정의 잇기/받기도 건너뛰어야 하고, 그러면서 `gated`와 `addr`는 기록으로 세워야 함(안 그러면 게이트가 없어 투명 복구도 억제도 없음, V13). B1. host RMA proxy도 첫 window 등록에서 상대마다 hook 밖의 IB 연결을 맺으므로 꺼야 함(9.10.4절, B1 설계 검토 T1-1). 복원 뒤 새 GIN 자원은 범위 밖 | 범위 | B1 |
| A4 | LSA(devComm `lsaRank`, `lsaSize`, `comm__types.h` 35; `dev_runtime.cc` 392) | 해당 없음(GIN만) | 같은 노드의 rank가 LSA 팀이면 생존 rank의 devComm이 죽은 rank의 메모리를 load/store로 가리킴 `[추론]` | 막는 문제 | 9.11.12절 B2 |
| A5 | GPU 문맥 판(`NCCL_GIN_GDAKI_GPU_CONTEXT_VERSION` = 2, gpucontext.h 19; 장치는 컴파일된 크기로 문맥을 셈 gin_gdaki.h 466) | 그대로 | 측 표 포인터 칸(DV1)이 `ncclGinGdakiGPUContext`의 크기를 바꿈 → 옛 헤더 바이너리가 contextId ≥ 1을 잘못 읽음(F17). 판을 3으로 올리고 판 2 formatter를 남김(판 1처럼, gpucontext.cc 37–45). 판 2 바이너리는 fail-fast | 호환 | DV1 2026-10-12 사용자 결정(원문 그대로: "가로 해야지"): 판 3 계획은 쓰지 않는다. 라이브러리가 고르는 판은 프로그램의 컴파일 때 NCCL 판으로 정하고 `hk` 헤더와 이 계층의 헤더는 둘 다 2.32.3이라 가를 수 없다(12절 2026-10-12). 측 표 포인터는 판을 바꾸지 않고 구조체 끝에 더한다(앞선 연구 계층이 분류 블록 포인터를 더한 방식). 뒤따르는 것: 이 라이브러리와 쓰는 모든 프로그램은 이 계층의 헤더로 빌드한다(gin-remaining과 gpu-detect 회귀 셀의 드라이버 포함, 이 계층의 장치 코드를 재려면 어차피 다시 빌드함). 옛 헤더로 빌드한 문맥 둘 이상의 프로그램은 1번 문맥부터 잘못 읽는다(지원하지 않음). 고를 길 (나) 분류 블록에 둠과 (다) 헤더 표시를 더함은 쓰지 않음 |

#### 9.11.6 application과 정리

| # | 장치와 코드 | fail-fast | hold-for-restore | 우선 | 바꿀 것 |
|---|---|---|---|---|---|
| P1 | `ncclCommRevoke`(init.cc 3463), `ncclCommAbort`(3521), 중단 shrink(3796) → `ncclGinTsUserAbortRaise` hr 2760–2788 / hw 2767–2795; 정리 `ncclGinGdakiTsCommTeardown` hr 6962–7084 / hw 7274–7403, `gdakiTsStop` hr 7086–7105 / hw 7405–7424, `gdakiTsFree` hr 7106–7134 / hw 7425–7453, orphan helper(hr 6936–6956, 6984–6992 / hw 7248–7268, 7296–7304) | revoke, abort, shrink는 모든 단어를 올림. 정리는 helper를 멈춤 | 같음. 복원 중이면 CANCELLED, 예비 프로세스에 BYE. 복원 라운드 중이면 그 라운드는 정지(`ts->stop`)로 거절. orphan helper는 rkey 표 쓰기 전에 `ts->stop`을 봄(T5) | application | L |
| P2 | 원인 기반 shrink 넘기기(`gdakiBlameNote` hr 841–898 = hw: Local 같은 이 rank 쪽 원인이 하나라도 있으면 질의가 −3, 상대 쪽 원인은 상대 목록; 거절의 기록 hr 4937 / hw 4962; 질의 init.cc 3572–3640) | 죽은 상대의 거절이 원인 PeerDead로 기록 → 그 상대를 빼는 중단 shrink는 GIN 오류를 넘어감. hw: degraded 뒤 건강한 쌍의 거절은 원인 Local → 넘기기 실패 | 복원 중에는 거절이 없어 기록도 없음. 붙잡은 상대에 대한 거절과 펌웨어 초과의 책임은 G2, G9로 PeerDead → fallback 뒤의 책임 기록은 fail-fast와 같음(V1). application이 복원 중 (자기 시한으로) shrink하면 P1로 취소되고, 부모에 GIN 오류가 없으므로 넘기기 검사가 필요 없음 `[추론]` | application | G2, G9 |
| P3 | 정상 정리의 bootstrap 배리어(`ncclCommDestroy`/`Finalize`가 abort 단어 0일 때 노드 안 배리어, init.cc 3171–3194) | 그대로 | 배리어에 든 되살린 rank의 bootstrap 끝점은 옛 프로세스의 것이거나 재생으로 만든 것 → 멈추거나 오류 `[미확인]`(F16). 복원한 communicator는 `ncclCommAbort`로 끝내야 함(application 요구, 9.7절) | application 요구 | 문서 |
| P4 | 통계 API(`ncclGinGetRecoveryStats` hr 7135– / hw 7454–) | 그대로 | 복원, fallback, 취소, 체크포인트, 억제 수를 더함 | 없음 | L |
| P5 | 신호와 카운터의 초기화(`ncclGinApi_ResetCounter`, `ResetSignal` gin_gdaki.h 1507–1527) | 그대로 | 재실행하는 rank가 다른 rank가 더하는 신호를 지우면 재실행 전에 적용한 로그의 더하기를 지움(F24) → 결정성 요구 | application 요구 | 문서 |

#### 9.11.7 빌드와 규약

| # | 장치와 코드 | fail-fast | hold-for-restore | 우선 | 바꿀 것 |
|---|---|---|---|---|---|
| B1x | 운영과 연구 빌드(`GIN_TS_NOTE` hr 82–85 = hw; 시험 스위치는 `#ifndef NCCL_GIN_TS_PRODUCTION` 블록, hr과 hw에 20개) | 그대로 | 정책과 복원은 두 빌드에 같음. 시험 스위치만 연구 빌드 | 규칙 | L |
| H1x | helper 메시지 규약(종류 hr 2932–2934 / hw 2945–2947, 형식 hr 2953–2967 / hw 2966–2980; 모르는 종류는 idle 루프가 무시 hr 6081–6082 / hw 6366–6367) | 그대로(새 종류는 오지 않음) | 새 종류(CKPT_PAUSE, PAUSED, BUSY, CKPT_RESUME, CKPT_STABLE, DISARM, NOHOLD, HOLDING, FALLBACK, ACTIVATE, REJOIN, READY, DONE_RS, RESTORED, LOG_REQ)와 NACK 이유 17. 모두 고정 크기, helper만 씀. 모든 rank가 같은 빌드, 같은 정책이어야 함(설정 all-gather에서 확인). 모든 기다림에서 미룸(M1) | 규약 | L |

#### 9.11.8 외부

| # | 장치 | fail-fast | hold-for-restore | 우선 | 바꿀 것 |
|---|---|---|---|---|---|
| X1 | PyTorch ProcessGroupNCCL 감시와 시간 제한, NCCL 자체 시간 제한, 장치 대기의 호출자 시간 제한(gin_gdaki.h 265, 1078, 1112: 쉬는 동안에도 감) | application이 2 s 안에 오류를 봄(degraded) | 복원 동안 생존 rank의 스트림이 GIN 커널에 묶임. 복원 시한(20 s)이 감시 한도보다 짧아야 함. 기본 한도는 이 환경에서 확인하지 않음 `[미확인]`. 시간 제한을 준 장치 대기는 복원 중 `ncclTimeout`으로 돌아올 수 있음(실패가 아니라 그 연산이 나중에 끝날 수 있다는 뜻, F25) → application의 장치 시간 제한도 복원 시간보다 길어야 함 | application의 감시 | 문서 |
| X2 | GIN 밖의 NCCL collective, NCCL P2P, LSA | 그대로 | 로그되지 않음. 복원한 communicator에서 되살린 rank와는 GIN 장치 통신만 됨(collective 전송, proxy 연결은 새 프로세스로 다시 잇지 않음). 쓰면 멈추거나 오류 | 범위 | 문서 |
| X3 | NCCL RAS | 죽은 rank를 보고 | 되살린 rank를 모름: RAS 보고가 어긋날 것 `[추론, 미확인]` | 범위 | 문서 |
| X4 | `NCCL_MULTI_RANK_GPU_ENABLE`(init.cc 73, 1307–1309) | 그대로 | 예비 프로세스도 같은 GPU의 셋째 프로세스로 이 변수가 필요. GPU 시분할로 예비 프로세스의 일이 느려짐(복원 시간에 잼) | 규칙 | 실행기 |
| X5 | NCCL의 shrink, grow, revoke, abort(`nccl.h.in` 321–363) | application의 회복 수단 | 복원 중 이 호출이 오면 P1로 취소. grow는 새 communicator와 새 devComm을 만들어 도는 커널을 지키지 못하므로 복원을 대신하지 못함 | application | 없음 |
| X6 | 같은 프로세스의 NVSHMEM t1w(R6, D7) | NVSHMEM은 FIN 판정 뒤 `_exit(70)`(기본) | `FAILSTOP_MS=-1`과 `FIN_DEATH=0`으로도 죽은 PE에 대한 거절은 다른 길(RETRY_EXC와 FIN의 `t1_fault`, 포기)로 일어나고, −1이면 거절마다 PE 전체의 대기 단어가 올라 붙잡힌 커널 안의 NVSHMEM 대기가 자료 없이 풀림(V15) → 제약: hold 정책의 프로세스는 NVSHMEM을 쓰지 않음(9.7절 6번). 실행기가 확인 | 프로세스 종료가 이김 | 실행기 검사 |

#### 9.11.9 복원 구성 요소

| # | 구성 요소 | fail-fast | hold-for-restore에서 닿는 기존 장치와 규칙 |
|---|---|---|---|
| C1 | 체크포인트의 입력 멈춤(빈 라운드, 9.4절) | 없음(체크포인트 없음) | 생존 rank q는 `gdakiTsQuiesce`에서 2ERR만 뺀 차례로 멈춤: 게이트 홀수, 개수 0, 모아 둔 WQE의 doorbell(안 울리면 r의 drain이 끝나지 않음, F20). 에폭 회계(M3: `coveredEpoch`, `nonmsg` 유지), 확대 상한(T1, 세지 않음), 기다림의 메시지 미룸(M1), hold 한도(멈춤은 ms 단위), drain의 QUERY_QP(T2, 가드 밖). RESUME은 q가 그 상대를 거절하지 않았고, 멈춤 뒤 진짜 라운드가 없었고, 게이트가 아직 멈춤 때의 에폭일 때만 게시(`gdakiTsWordHiWrite`는 에폭 반쪽을 통째로 씀 hr 4270–4273 / hw 4295–4298: 거절의 HOST_FAILED를 지우면 안 됨, F7 (b)). 멈춤 중 그 쌍에 라운드가 돌면 라운드가 이기고 그 체크포인트는 버림. 멈춤 요청을 받은 rank가 라운드 중이거나 억제 예산이 남았으면 BUSY(P4). PAUSED는 "p에 대해 무장 가능"을 실음(9.10.4절). 억제 예산이 남은 rank는 체크포인트를 찍지 않음(V18) |
| C2 | 송신 쪽 로그(장치) | 꺼짐: 측 표 포인터가 0 | 측 표의 QP마다 "로그 켬" 낱말이 선 QP에서만 쓴다(검토 3 W2, 2026-10-09: 측 표 포인터 ≠ 0은 B4의 키 다시 읽기를 뜻하고, 로그는 따로 켬). 그 낱말은 helper가 그 QP의 게이트가 홀수이고 개수가 0일 때(체크포인트의 입력 멈춤, C1) NIC 루프백으로 쓰고 READ로 확인한 뒤에야 CKPT_RESUME의 짝수 에폭을 게시하므로(검토 3 재확인 X2) 로그의 시작과 절단점이 같은 자리다. q는 멈춤마다(PAUSED가 "무장 가능"이든 아니든) 아직 서지 않았으면 낱말을 세운다(로그가 더 쓰여도 해가 없음). 장치는 게이트 안에서 strong 읽기로 본다. DISARM은 낱말을 그대로 두거나 다음 멈춤에서 지운다(로그가 더 쓰여도 해가 없음). 게이트 안 기록(put 경로 gin_gdaki.h 458–547). 게이트 계수는 coop의 0번 스레드만 잡으므로(465, 501, 537) 0번 스레드가 계수를 잡은 채 자리를 잡고, coop 동기화 뒤 모든 스레드가 내용을 복사하고, 다시 동기화한 뒤 0번이 적고 보내고 나감(V19: 개수 0이 "항목이 다 적힘"을 뜻하게). 0번 스레드의 게이트 진입이 실패하거나 억제되면 coop 전체가 보는 "건너뜀" 깃발로 복사를 건너뜀. 추가 동기화는 측 표 포인터가 0이 아닐 때만. 넘침은 DISARM. 측 표 포인터 칸은 GPU 문맥 판 3(A5; 2026-10-12 사용자 결정으로 판은 그대로 두고 구조체 끝에 더함, 9.11.5절) |
| C3 | 예비 프로세스와 초기화 재생 | 없음 | NCCL bootstrap, GIN collComm 고리와 helper 설정(A3), `NCCL_MULTI_RANK_GPU_ENABLE`(X4). 막는 문제 B1 |
| C4 | REJOIN | REJOIN은 닫음 | 재연결 기계와 펜싱(D4) |
| C5 | 복원 라운드 | 없음 | hold 시작(9.10.7절), Prepare/Commit과 양쪽 토큰(M4), rkey(A1), `RepostApply`의 커밋 지점과 PUBLISHING(M2), 비메시지 확인(M2), 펌웨어 감시(T2), hold 한도(T4), 게시 전 확인(R4) |
| C6 | 예비 프로세스의 억제 | 없음 | 게이트 에폭 반쪽의 새 비트 SUPPRESS(`EPOCH_MASK` 30비트 → 29비트). 보내기만 이 비트로 느린 길에 감: 보내기의 열림 검사(`tsGateEnter` gin_gdaki.h 333)에만 넣고, 대기의 열림 검사(`tsPollEnter` 365)와 `tsParkStable`(264)은 그대로(공용 `tsWordOpen`에 넣으면 flush와 wait가 `tsTicketSlow` 382–386에서 끝없이 돎, F1). 장치가 에폭 반쪽을 값으로 쓰는 모든 자리에서 SUPPRESS를 지움: `tsPollEnter`가 저장하는 값(364–366), `tsPoll`의 비교(1106)와 기록(1107–1108), `tsSwErrReport`(1037), `tsLateFail`(206–207)(V4: 안 그러면 `reported`와 `handled`에 2^29가 붙어 그 QP의 다음 장애 보고가 막힘). 느린 길(`tsGateEnterSlow` 303–328)은 나가기와 쉬기 전에 억제를 먼저 처리. SUPPRESS는 예산을 쓰는 동안 에폭 반쪽의 모든 호스트 쓰기(정지 hr 4425, PUBLISHING 4731, 게시 4881, 거절 4963, 훑기 5871, 정리 7039 / hw 4450, 4756, 4906, 4988, 5900, 7351)에서 유지돼야 하므로 helper가 유일한 쓰는 쪽이고 쓸 때마다 OR함(F18; 거절과 훑기, 정리의 HOST_FAILED 쓰기에서 지워지는 것은 그 QP가 끝났으므로 무해). 보통 rank와 fail-fast에서는 이 비트가 서지 않음. B4 결정 (나)(2026-10-09)의 키 다시 읽기는 느린 길이 참을 돌려준 뒤(내기로 한 뒤)에 오므로 억제한 연산은 키를 읽지 않음(A1) |

#### 9.11.10 gpu-detect 계층에 넣을 변경 (최소)

정책을 나누는 데 필요한 것만이다. fail-fast에서 모든 hook은 지금의 동작을 그대로 낸다(9.10.6절 (다)). 그래서 gpu-detect의 pilot과 예측은 이 변경으로
바뀌지 않는다 `[추론]`. 검토 2는 G1–G7이 fail-fast에서 hw와 같게 돈다고 확인했다(G1은 all-gather 레코드가 커지는 것만 다름, G4는 뒷정리를 지킬 때).
G8, G9는 검토 2 뒤에 더했다.

**hw (`gin_host_gdaki.cc`).**
- G1. 정책 칸과 변수: `NCCL_GIN_FAULT_POLICY`(기본 `failfast`)를 `gdakiTsSetup`(hw 6438–)에서 읽고 설정 all-gather(`gdakiTsAddr`, hw 6458–6518)에
  싣는다. rank마다 다르면 fail-fast(WARN). 문맥(`gdakiTs`)과 communicator 등록부(`gdakiUa`)에 둔다.
- G2. 거절 hook: `gdakiTsDecline`(hw 4941) 맨 앞에서 `gdakiPolicyOnDecline(r, peer, why, cause, uaWhy)`를 부르고, 참이면 돌아간다. 두 갈래는 R1. fail-fast에서는
  늘 거짓이다. 죽음과 붙잡은 상대에 대한 모든 거절이 이 함수로 모이므로 호출 자리는 고치지 않는다. 강한 증거 검사는 `pe.lostAfterCommit`도 본다(9.10.5절,
  2026-10-09): gpu-detect가 응답 쪽 Commit 뒤 길을 PEER_DEAD 거절로 고친 뒤에도 그 거절은 붙잡지 않는다.
- G3. 감시 hook: `gdakiDetWatchStep`의 상대 거르기(hw 6094)에 `|| !gdakiPolicyWatch(r, p)`. HELD, COMMITTING이면 거짓. fail-fast에서는 늘 참(감시함).
- G4. 기록 처리 hook: helper의 기록 처리 루프(hw 6399–6409)에서 `gdakiTsInitiate(r, f)`를 `if (gdakiPolicyRoute(r, f)) gdakiTsInitiate(r, f);`로 바꾼다
  (HELD, COMMITTING의 상대는 흡수, PUBLISHED의 상대는 낡은 기록이면 버리고 아니면 fallback을 표시하고 거짓, Q3; `ts->batch`, heartbeat, `nQueued`의 뒷정리는 그대로 돎, V16). fail-fast에서는 늘 참. Q4 감시 스레드의 경로 판단(`gdakiTsRoutes`)은 그대로.
- G5. 훑기 hook: `gdakiTsScan`의 유실 검사(hw 5923–5925)를 `gdakiPolicyWatch(r, p)`가 거짓인 상대에서 건너뜀. fail-fast에서는 늘 검사.
- G6. 에폭 비교의 기준: `gdakiDetQueued`(hw 6066)와 `gdakiDetWatchStep`(hw 6139)의 `qs[].epoch`를 `gdakiTsCoveredEpoch(s)`로. fail-fast에서는 빈 라운드가
  없어 `epoch`와 같다. 같은 바꿈을 hr에서 물려받은 비교(hw 5460, 3361)에도 한다.
- G7. 감시의 QUERY_QP가 받는 값: `doca_verbs_qp_query_seq`(hw 6111)에 rmsn 자리를 넘겨 `gdakiPolicyObserveRmsn(r, qp, rmsn)`에 전한다. fail-fast에서는
  아무것도 하지 않는 함수다(펌웨어 명령 수는 그대로).
- G8. 감시 스레드의 정책 걸음: `gdakiTsWatchdog`(hw 3488) 맨 앞, `gdakiUaDegradedStep` 옆에 `gdakiPolicyWatchdogStep(r)`. 복원 시한이 지난 붙잡은 상대에
  대해, HELD면 CAS(HELD → TIMED_OUT)에 이겼을 때 `gdakiTsToComm` 안에서 CPU 쓰기로 그 상대의 단어(PEER_DEAD), 비동기 오류, 책임(PeerDead), degraded
  예약을 하고(PUBLISHED면 CAS로 상태만 바꾸고 거절은 helper가, P1), helper가 나중에 fallback 거절로 마저 하게 표시한다(V5, N1). 정책 칸은 원자 칸이라 잠금을 잡지 않는다(N3).
  fail-fast에서는 붙잡은 상대가 없어 아무것도 하지 않는다.
- G9. 펌웨어 초과의 책임 원인: `gdakiTsWatchdog`의 책임 기록(hw 3530)에서 원인을 `gdakiPolicyBlameCause(r, peer, gdakiCause::Local)`로. 붙잡은 상대면
  PeerDead, 아니면 그대로(fail-fast에서는 늘 그대로, V1).
- 코드 변경 없음, 문서만: `NCCL_GIN_TS_DEGRADED_MS`, `NCCL_GIN_TS_DEGRADED_ROUNDS`는 fail-fast 반응의 변수다. hold에서는 거절(fallback)이 일어난 뒤에만
  효과가 있다. QP 감시의 변수(`QPWATCH_MS`, `GRACE_MS`, `NOCQE_MS`)는 감지의 변수라 두 정책에 같다(V14).

**정책과 별개로 찾은 hw의 틈(권고).** 응답 쪽이 Commit한 뒤 ACK 보내기 실패나 DONE 기다림 중 소켓을 잃으면(hw 5285–5292, 5298–5303) 죽음 판정 없이 원인
Unknown, `uaWhy` DECLINED로 거절하므로 degraded가 예약되지 않는다. 랭크 3개 이상에서는 그 상대를 기다리는 상대를 모르는 대기가 풀리지 않는다 `[소스,
추론]`. 그 두 자리에서 먼저 `gdakiTsSocketLost`로 판정하게 하면 FIN이 죽음으로 판정되어 helper 루프의 PEER_DEAD 거절로 간다. fail-fast의 동작을 바꾸는
고침이므로 gpu-detect가 정할 일이다. 고치기 전에는 이 창의 죽음은 hold에서도 fail-fast다(9.10.7절).

2026-10-09: gpu-detect가 이 틈을 고친다(병렬 작업, 메인 세션이 정한 계약). 그 두 자리에서 소켓을 잃은 자리에서(`gdakiTsSocketLost`를 부르기 전과 어느
돌아가기보다도 먼저, 검토 3 W10, X5) `pe.lostAfterCommit = true`를 세우고, 잃음이 죽음
판정이면 거절은 PeerDead, `GDAKI_UA_PEER_DEAD`(degraded 예약), 아니면 지금 그대로다. 복원 계층이 이 계약에 기대는 것은 둘이다: G2의 강한 증거 검사가 이
표시를 본다(9.10.5절, 붙잡지 않고 NOHOLD), REJOIN이 이 표시를 지운다(D4). 표시를 세우는 자리와 ACK 길의 errno에 대한 검토 3의 메모(W10, W11)는 9.10.5절에 적었다. 이 정책 설계의 hw 줄 번호는 고치기 전 트리(diff md5 `be0ea9ed`)의 것이다. 고친 뒤 줄이 밀리면
계층을 만들 때 다시 맞춘다.

**t1w (NVSHMEM).** 코드 변경 없음. `NVSHMEM_IBGDA_FT_T1_FIN_DEATH`, `FAILSTOP_MS`, `FAILSTOP_CODE`는 NVSHMEM fail-fast 반응의 변수로 문서화한다.
NVSHMEM 정책은 fail-fast 하나다. hold 정책의 프로세스는 NVSHMEM을 쓰지 않는다(X6).

#### 9.11.11 복원 계층의 변경과 fail-fast

- 복원 계층은 G2–G9의 hold 분기를 채운다. 그 밖에 같은 파일의 hw 코드에도 손을 댄다(9.9절): 받기 루프의 REJOIN(RL6), 메시지 처리와 모든
  기다림의 미룸(RL11, RL17, M1), 낡은 기록 검사의 `coveredEpoch`(RL12), 확대 상한의 세지 않기(RL15), 누적 실행 수(RL13), hold 시작과 복원 라운드(RL1,
  RL4, RL7–RL9), 응답의 NACK 17(RL20). 이들도 fail-fast에서 같다: 새 메시지는 오지 않고, `coveredEpoch == epoch`이고, 세지 않기와 누적은 hold 경로에서만 부르고, 붙잡은 상대가 없어 NACK 17이
  나가지 않는다.
- 로그, 체크포인트, 예비 프로세스는 정책이 hold이고 그 communicator가 무장 조건(9.10.4절)을 갖추고 `ncclGinRestoreResume`을 부른 뒤에만 켠다. 로그를 켜는 것은 QP마다의
  "로그 켬" 낱말이다(C2, 검토 3 W2). 측 표 포인터는 hold 정책이면 문맥을 만들 때부터 0이 아니고 그때부터 키 다시 읽기(A1)가 돈다.
  fail-fast에서는 비용이 보내기마다 측 표 포인터를 한 번 보는 분기와 내부 인자 하나뿐이다(DV2, A1 (4)).
- 시제품은 멈췄다: 이 정책 설계의 검토 전에 쓴 초안(로그 고리, 체크포인트 저장소, 복원 계획, CPU 모의)은 빌드도 실행도 하지 않았고, 저장소에 넣지 않고 세션
  스크래치 `agent_restore/proto_draft_unbuilt/`에 두었다. 시험 프로그램 `gin_rs.cu`는 쓰지 않았다. 초안의 억제 판정은 READ를 다루지 않으므로 다시 쓸 때
  M2에 맞춘다.

#### 9.11.12 열린 충돌 (막는 문제)

해결이 없거나 결정이 필요한 행이다. 하나라도 남아 있는 동안 복원 계층은 구현하지 않는다.

| id | 무엇 | 왜 막는가 | 풀 조건 |
|---|---|---|---|
| B1 | 예비 프로세스의 초기화 재생(C3, A3) | NCCL bootstrap, GIN collComm 고리 연결과 all-gather, helper 설정의 잇기/받기는 모든 rank가 함께 해야 한다. 기록된 결과로 대답하는 길이 NCCL 핵심의 초기화 전체(proxy, 런타임 연결, 대칭 메모리 등록)를 덮는지, 같은 devComm 모양을 만드는지, `gated`와 `addr`를 기록으로 세울 수 있는지 모른다 `[미확인]` | 초기화 재생 시험(빌드가 필요하므로 이 정책 설계의 승인 뒤): 장애 없이 한 rank의 기록을 만들고, 예비 프로세스가 그 기록으로 초기화를 끝내 같은 rank, nRanks, 컨텍스트 수, 신호 수, window 크기, 모든 상대의 게이트를 얻는지. 2026-10-09: 시험 설계, 판정 기준, 코드가 검토를 거쳐 빌드됨, 실행 전(9.15.4). 설계 검토로 host RMA proxy와 runtime connect, NVLS를 무장 조건에 더함(9.10.4절). **2026-10-09 시험 결과**: 2회 모두 예비 프로세스가 rank 0과 rank 1의 기록만으로 상대 없이 초기화, window 등록 둘, devComm 생성을 끝내고 다섯 항목(기록 정확 소비, 상대로의 connect 0, 같은 devComm과 window와 rkey, 모든 상대의 gated, addr, 게이트)을 통과했고 음성 대조 둘은 실패했다(9.15.4, 12절). 그래서 B1의 "초기화 재생" 부분은 이 범위(2 rank, 노드 사이, lsaSize 1, host RMA와 RAS 꺼짐)에서 풀렸다. 남은 부분(REJOIN, 복원 라운드의 토큰 연결, rkey 바꿈, 4 rank와 노드 안 상대의 재생)은 계층을 만들 때 확인한다 |
| B2 | LSA 팀(A4) | GPU 하나를 두 프로세스가 나눌 때 devComm의 `lsaSize`가 1인지 모른다. 2 이상이면 생존 rank의 load/store가 죽은 rank의 메모리를 계속 가리키고, 이것을 고치려면 생존 rank에서 CUDA 가상 메모리 호출이 필요하다(생존 rank는 CUDA 호출을 하지 않는다는 원칙과 충돌) `[추론]` | `lsaSize`를 읽어 확인. 2 이상이면 LSA 팀에 든 상대는 무장하지 않음(그 상대의 죽음은 fail-fast)으로 해결한 것으로 본다. 2026-10-09: 기존 원자료에는 값이 없음, 확인 시험이 빌드됨, 실행 전(9.15.2). **2026-10-09 풀림(해결 A)**: 복원 셀 배치(4 rank 번갈아, GPU마다 둘)에서 2회 모두 네 rank `lsaSize=1`, `nLsaTeams=4`(9.15.2, 12절). 다른 배치를 지키는 장치로 "LSA 팀에 든 상대는 무장하지 않음" 규칙과 runtime connect, NVLS 조건(9.10.4절)은 그대로 둔다 |
| B3 | 체크포인트의 drain 확인(C1) | 응답 쪽 rmsn이 멈춤 때의 메시지 수에 이른 뒤 그 쓰기가 GPU 메모리에 보인다는 것은 NIC 루프백 READ 하나의 차례 보장에 기댄다. 그런데 window MR은 기본으로 relaxed ordering이다(`gdakiRegMr` hr 192 = hw, `NCCL_IB_PCI_RELAXED_ORDERING` 기본 2 net_ib/init.cc 11; strict는 `NCCL_WIN_STRICT_ORDERING`일 때만 gin_host.cc 556; 신호와 카운터 표는 strict hr 7311–7312 / hw 7630–7631). gin-remaining의 flush 근거는 그 계층 자신의 strict 루프백 MR이었다 `[미확인: 이 하드웨어]` | (가) 무장 조건으로 strict window를 요구하고(성능 비용을 잼), (나) NIC 게이트 시험과 같은 꼴로 relaxed와 strict에서 drain 뒤 사본이 맞는지 따로 잼. (나)가 끝나야 풂. 2026-10-09: (나)의 시험(READ 대상은 다른 할당의 fence 낱말, copy engine 복사, 꼬리 셋, 대조 둘)이 검토를 거쳐 빌드됨, 실행 전(9.4절 3단계, 9.15.3). **2026-10-09 시험 결과: 열림(사용자 결정 대기)**. 셀 열둘 가운데 열이 통과했다(rain의 노드 사이와 같은 노드 셀 `ro`, `so`; sunny 여섯, sunny 경합 `so`는 다시 해서). 모든 실행에서 채점 fence 실패 0이다. rain의 GPU 경합 셀 둘은 두 번씩 대조(`early`, `boundary`)에서 늦은 낱말이 한 번도 없어 미결이고, 그래서 rain은 열림, sunny는 `ro`, `so` 모두 통과다. 대조가 힘을 잃는 것은 hog 프로세스와 GPU를 시간 나눔으로 쓰느라 복사가 늦게 시작하기 때문으로 본다 `[추론]`. 모든 셀에서 READ 없는 대조 길(`nofence`)도 실패 0이라 이 시험은 READ가 필요한지를 가르지 못한다. 결정 전까지 무장 조건 "window는 strict"(9.10.4절)는 그대로 둔다(9.15.3 결과, 12절). **2026-10-11: drain 확인이 두 순서 모두에서 통과, strict window 무장 조건은 사용자 결정(대기)**. 경합 셀 넷을 같은 프로세스 안의 hog로 다시 했고(사용자 결정, 9.15.3) 넷 모두 유효하고 통과했다. 노드와 순서마다 `x`, `s`, 새 경합 셀의 묶음이 모두 통과다(rain `ro` 4 663, `so` 4 645, sunny `ro`, `so` 4 800 채점 fence 반복, 실패 0). sunny의 새 경합 셀은 쓰기 도착을 늦추는 경합을 보이지 않는다(사용자 결정). READ 없는 대조 길도 모든 셀에서 실패 0이라, 이 시험은 쓰기가 보이는 것을 READ 덕분으로 돌리지 못한다(9.15.3 결과, 12절) **2026-10-11 사용자 결정으로 닫음**: 복원 대상 window는 런타임이 strict를 강제하고, 강제할 수 없으면 명시적 등록 오류(9.10.8절, RL21). relaxed는 쓰지 않고, 능력 확인과 겹침 실험을 통과한 뒤의 최적화 후보로만 남는다. strict의 정상 경로 비용은 9.15.6에서 잰다 |
| B4 | 빠른 경로의 키 읽기 자리(A1, F5) | 생존 rank의 보내기가 게이트가 홀수일 때 옛 rkey를 읽고, 게시 뒤 빠른 경로로 들어가면 죽은 rank의 rkey로 보낸다. 고치려면 키 읽기를 게이트 진입 뒤로 옮겨야 한다. `signalKey`는 호출자가 계산해 값으로 넘기므로 그 계산 자리를 `putImplMode` 안으로 옮기는 구조 변경이 들고, 보통 읽기(`loadConst`)를 게이트 뒤의 시스템 범위 읽기로 바꾸면 L1 적중을 잃을 수 있다(V2b). 이것은 "빠른 경로는 바꾸지 않는다"는 설계 원칙(9.1절)과 충돌한다 | 사용자의 결정: (가) 모든 보내기에서 키 읽기를 게이트 뒤로(지연을 4 KiB, 256 KiB에서 잼), (나) hold 정책의 communicator에서만(측 표 포인터로 가르는 분기가 fail-fast에도 더해짐), (다) 복원을 포기. 결정 전에는 막음. **2026-10-09 사용자 결정: (나).** 설계는 A1과 9.9절 DV3. 4 KiB, 256 KiB 지연은 복원 계층을 만들 때 잰다(LT1, LT2). 결정 뒤의 독립 검토는 9.11.13절 검토 3 |

#### 9.11.13 정책 설계의 독립 검토

**검토 1**(읽기 전용 에이전트, 2026-10-09, 대상: 이 정책 설계의 초안 9.1–9.11절과 hr 트리, hw diff). 새 막는 문제 0, 높음 6(F1–F6), 중간 9(F7–F15),
낮음과 중간-낮음 13(F16–F28), B3 정정 하나, 인용 오류 여섯.

| 지적 | 요지 | 자리 | 지적 | 요지 | 자리 |
|---|---|---|---|---|---|
| F1 | SUPPRESS를 공용 열림 검사에 넣으면 flush와 wait가 끝없이 돎 | C6 | F15 | rkey 표의 MR 등록 | T5 |
| F2 | 생존 rank의 get이 자료 없이 끝남 | M2, 9.10.4절 | F16 | 정상 정리의 배리어 | P3 |
| F3 | 되살린 rank의 READ, NOP, DUMP의 예산 | M2 | F17 | GPU 문맥 크기 | A5 |
| F4 | 응답 쪽 Commit 뒤 게시 전 죽음 | 9.10.7절(검토 2로 fail-fast로 바꿈) | F18 | SUPPRESS가 호스트 쓰기에서 지워짐 | C6 |
| F5 | 빠른 경로의 옛 rkey | A1, B4 | F19 | 실행 수 mod 2^24, Commit 전 읽기 | M2, G7 |
| F6 | 문맥마다 helper, communicator마다 단어 | 9.10.4절, R2 | F20 | 멈춤 중 울리지 않은 WQE | C1 |
| F7 | 체크포인트 메시지와 라운드의 기다림, RESUME, 고정 크기 | M1, C1, H1x | F21 | 체크포인트 QUERY_QP의 가드 | T2 |
| F8 | hold 시작이 모자람 | 9.10.7절 | F22 | REJOIN의 세대와 진행 중인 연결 | D4 |
| F9 | 죽음 증거가 약함 | 9.10.5절 | F23 | REJOIN의 크기 | D4 |
| F10 | PSN과 QPN | M4 | F24 | 신호 초기화 | P5 |
| F11 | 같은 nonce로 옛 HELLO/PROBE를 통과 | D4 | F25 | 장치 대기의 호출자 시간 제한 | X1 |
| F12 | 빈 라운드와 다른 에폭 비교 | M3, G6 | F26 | 상한으로 멈춘 문맥 | 9.10.4절, T1 |
| F13 | hold 시계의 시작 | T4 | F27 | 재연결 꺼짐 | 9.10.4절 |
| F14 | 쌓임 감시와 NIC 복사의 스레드 | D1, D5, T5 | F28 | 경로 판단은 Q4 감시 스레드 | D1, G4 |

그 밖: 예비 프로세스의 helper 설정과 collComm 고리 연결(A3, B1), window MR의 relaxed ordering(B3), 인용 고침(R1의 취소 길, M1의 REJOIN, B1x의 20개,
9.3절의 `pe.addr`, T4의 `gdakiTsStart`).

**검토 2**(읽기 전용 에이전트, 2026-10-09, 대상: 검토 1을 반영한 이 정책 설계와 9.1–9.9절, hr, hw, nvs 트리). 지적 21개(V1–V20, V2b), 모두 해결안이
있고 B1–B4 밖의 새 막는 문제는 없다고 했다. 인용 확인: "hr N / hw M" 쌍 142개 불일치 0, 틀린 인용 하나(D5의 사본 크기). 반영:

| 지적 | 요지 | 자리 |
|---|---|---|
| V1 | 붙잡은 상대를 죽음 아닌 원인으로 거절하면 fail-fast와 결과가 다름(degraded 없음, Local 책임) | 9.10.3절, R1(G2 갈래 가), D5, D6, P2, G9 |
| V2 | DV4가 F1을 되살림 | 9.9절 DV4, C6 |
| V2b | DV3가 B4에서 막힌 방안, `signalKey`는 값으로 넘김, 읽기 종류 | DV3, A1, B4 |
| V3 | 응답 쪽 Commit 뒤 죽음은 강한 증거가 아님 → `S_pending`은 죽은 코드. hw의 degraded 틈 | 9.10.7절, R3, 9.11.10절 끝 |
| V4 | SUPPRESS가 장치의 에폭 값에 섞임 | C6, DV4 |
| V5 | 복원 시한을 helper 하나로 못 지킴 | D5, T4, G8 |
| V6 | 무장은 rank마다, 복원은 모두 | 9.10.4절, 9.10.5절, 9.10.7절, D4 |
| V7 | 되살린 rank의 get | M2 (c), 9.7절 8번 |
| V8 | NIC 복사 경로가 무장 조건에 없음 | 9.10.4절, T5 |
| V9 | zombie PID | 9.10.5절 |
| V10 | hold 시작이 Busy 밖 | 9.10.7절, T3 |
| V11 | 낡은 `lostCause` | 9.10.5절, D4, R1 |
| V12 | 실행 중 MR 등록, 등록 해제, orphan | 9.10.4절, T5, P1 |
| V13 | 예비 프로세스에 게이트가 없음 | A3, B1 |
| V14 | QP 감시 변수의 성격, 표본 조건 | 9.10.2절, 9.10.4절, M2, 9.11.10절 |
| V15 | NVSHMEM 둘째 선택지가 불완전 | X6, 9.10.3절 |
| V16 | G4의 `continue`가 뒷정리를 건너뜀 | D1, G4 |
| V17 | 빈 라운드가 `nonmsg`를 지움 | M3 |
| V18 | 억제 예산이 남은 동안 체크포인트 | C1 |
| V19 | 로그 내용 복사가 게이트 계수 밖 | C2 |
| V20 | 사실 불일치 12개(G 개수, `U = S`, 9.1절 그림 차례, 9.11.11절, destroy, 취소 뒤 길, 판정 WARN 줄, DV2의 시간, D5의 사본 크기, C6의 쓰기 목록, T1의 응답 쪽, X6과 9.10.4절) | 각 자리, 9.1, 9.3, 9.9절 |

**검토 2 재확인 1**(커밋 `6e3c1618` 대상). V1–V20 대부분 풀림. G1–G9는 정책 failfast에서 hw와 같음(조건 N5). 인용 쌍 164개 불일치 0. 새 충돌:
N1(높음, G8과 게시의 다툼 → 9.10.7절 CAS), N2(높음, 게시 뒤의 FALLBACK → 9.10.7절 PUBLISHED), N3(G9의 범위와 잠금 차례 → 9.10.7절 0단계, 원자 칸), N4(붙잡지 않고 거절한
rank의 알림 → 9.10.7절), N5(정책 hold 무장 전의 설정 차이 → 9.10.6절 (다)), V7의 남은 부분(→ M2 (c)), V9, V12, V19의 낮은 메모(→ 9.10.5절, T5, C2), 이 정책 설계에 남은
문장 일곱(→ 고침).

**검토 2 재확인 2**(커밋 `568af8c1` 대상). N1–N5, V7, 이 정책 설계의 7문장 풀림, 인용 쌍 167개 불일치 0, fail-fast 동치 그대로(조건 N5). 새 충돌:
P1(높음, PUBLISHED에서 G8이 단어부터 올리면 거절의 차례가 깨짐 → G8은 PUBLISHED에서 상태만, 따로 된 시한), P2(RESTORED와 FALLBACK의 경쟁 → 화신 번호, 어느
상태든 거절), P3(PUBLISHED의 산 QP를 감시에서 뺌 → HELD, COMMITTING에만, PUBLISHED의 장애는 fallback), P4(억제 중 남의 체크포인트 → BUSY), P5(RESTORED 뒤
무장 조건 → ARMED 또는 OFF, PID 등록, DISARM 적용), P6(COMMITTING의 실패 → 바로 거절), P7(이 정책 설계의 그림, 9.3절 8단계, RL9). 모두 9.10.7절과 해당 행,
이 정책 설계에 반영.

**검토 2 재확인 3**(커밋 `452e7cf4` 대상). P1–P7 풀림, 인용 쌍 169개 불일치 0, fail-fast 동치 그대로(조건 N5; 정책 failfast에서는 FALLBACK도 NOHOLD도
보내지 않음). 새 충돌: Q1(중간-높음, N4 방송과 "어느 상태든 FALLBACK이면 거절"이 겹쳐 산 상대를 모두가 거절 → NOHOLD로 나누고, FALLBACK의 거절은 그 화신을
붙잡았거나 되살린 rank만), Q2(PUBLISHED에서 RESTORED가 시한을 이김, 시한 ≥ roundMs + handshake), Q3(PUBLISHED의 낡은 기록 버림), Q4(Commit부터 CAS까지의
문장), Q5(예비 프로세스의 REQ에 NACK 17). 모두 9.10.7절에 반영.

**검토 2 재확인 4**(커밋 `70b23f28` 대상). Q1–Q5 풀림, 인용 쌍 171개 불일치 0(`gdakiTsRespond`의 끝 줄 하나 고침), fail-fast 동치 그대로(조건 N5).
남은 것 R1(낮음: 미룬 RESTORED보다 같은 상대의 REQ가 먼저 처리될 수 있음 → 같은 상대의 메시지는 도착 차례대로, NACK 17 전에 RESTORED 적용). 9.10.7절에 반영.

**검토 2 재확인 5**(커밋 `0af9190e` 대상). R1 풀림(두 길 모두 덮음; 미룬 FALLBACK을 기다림 안에서 처리하는 것은 hw가 FAIL을 그 자리에서 처리하는
방식 hw 5391–5397과 같은 꼴), `gdakiTsRespond` 끝 줄 확인, fail-fast 동치 그대로(조건 N5). **판정: 막는 문제 B1–B4 밖에 풀리지 않은 충돌 없음.**

남은 것은 9.11.12절의 B1–B4다. B4는 사용자의 결정이 필요하고, B1과 B3은 빌드가 필요한 시험이므로 이 정책 설계의 승인 뒤에 한다.

2026-10-09 사용자 결정(검토 2 뒤): B4는 (나). B1, B2, B3은 실행 가능성 시험을 한다(시험 프로그램만 빌드, 복원 계층은 구현하지 않음;
9.15절). 같은 날 gpu-detect와의 계약 `pe.lostAfterCommit`(9.10.5절)를 넣었다. 이 두 변경의 검토는 아래 검토 3이다.

**검토 3**(읽기 전용 에이전트, 2026-10-09, 대상: 커밋 `60399e85`의 결정 (나)와 `lostAfterCommit` 계약, hw 트리). 막는 문제 0, 중간 3(W1–W3), 낮음 5, 메모 3.
계약 쪽: 같은 화신에 표시 없는 PEER_DEAD 거절이 올 수 없음, 붙잡은 상대는 이 창에 닿지 못함(모든 REQ가 `gdakiTsRespond`의 NACK 17을 지남), N4, Q1, V11,
R3, D4, P2와 맞음, REJOIN에서만 지워도 충분함. (나) 쪽: 차례의 논거는 맞음(W4, W5 제외), SUPPRESS와 coop와 충돌 없음. 반영(커밋 `daa63c69`):

| 지적 | 요지 | 자리 |
|---|---|---|
| W1 | 측 표 포인터를 쓰는 때가 없고 무장 조건에 없음(GPU 문맥은 hw 7966에서 `gdakiTsSetup` 전에 복사됨) | 9.10.4절(무장 조건, PAUSED), RL10, 9.6절 |
| W2 | 포인터 ≠ 0이 "키 다시 읽기"와 "로그 씀" 둘을 뜻함 | C2와 9.11.11절(QP마다 "로그 켬" 낱말), 9.10.6절 (다), DV1, DV2, 9.5절, 7절 비용 셀 둘 |
| W3 | get 키를 다시 읽지 않는 이유가 틀림(복원을 건너는 커널의 L1) | A1 (1), (7), DV3, 9.6절: get도 다시 읽음 |
| W4 | 읽기 범위가 두 가지로 적힘 | A1 (1): 시스템 범위 relaxed 32비트 |
| W5 | 쓰고 READ로 확인하는 걸음이 9.3절과 RL9, T5에 없음 | 9.3절 7단계, RL9, T5 |
| W6 | 신호만 보내는 길의 null, 자리(509 앞) | A1 (1), DV3 |
| W7 | 보내기 길 목록은 완전함, 카운터 길은 hold에서 쓰이지 않음 | A1 (7) |
| W8 | fail-fast의 변화는 분기 하나와 내부 인자 하나 | 9.10.6절 (다), A1 (4), 9.11.11절, DV3 |
| W9 | 결정 전 문장, 없던 절 참조 | A1, 9.6절(표시), 9.15절(만듦), 이 검토 |
| W10 | 표시를 세우는 자리: 잃은 자리에서, `gdakiTsSocketLost` 전 | 9.10.5절(메인 세션과 gpu-detect에 넘김) |
| W11 | ACK 길에서 errno를 `closeCause`로 먼저 옮겨야 거짓 죽음이 없음(gpu-detect 쪽) | 9.10.5절(메모) |

첫 판정: "W1, W2, W3(모두 중간, 문서로 고칠 수 있음) 밖에 풀리지 않은 것 없음. 계약에는 풀리지 않은 충돌 없음(W10의 문구와 W11 메모를 조건으로)."

**검토 3 재확인**(같은 에이전트, 대상: 커밋 `6b33627e`). W1–W11 모두 풀림. 새로 낮음 다섯: X1(무장 전 hold도 coop 추가 동기화를 치르고 첫 멈춤 뒤 로그를 쓸 수 있음 → 9.10.6절 (다), `lat_hold_unarmed`는 멈춤 없이), X2(로그 켬 낱말을 쓰고 READ로 확인한 뒤 RESUME → C2), X3(fail-fast의 get은 포인터 읽기 하나와 분기 하나 → A1 (4), `lat_ff_branch`에 get), X4(줄 번호 hw 7966, 포인터 쓰기는 동기, `host_buf`에도 → 9.10.4절), X5(표시 자리 규칙을 "잃은 자리" 하나로 → 9.10.5절, 9.11.10절 끝). 모두 반영했다. **판정: "결정 (나)와 `lostAfterCommit` 계약에 낮음 X1–X5 밖에 풀리지 않은 충돌 없음"**(X1–X5는 이 반영으로 닫음).

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
위치(`ovfSeq`)로 무장을 판단하는 규칙(9.5절), 복원 뒤 생존 rank가 자기 다음 체크포인트까지 무장하지 않는 창(9.10.7절).

### 9.14 구현 계획과 실행 방법 (사용자 순서 (4), 2026-10-11, 아직 구현하지 않음)

**바탕.** gpu-detect의 `hk` 빌드(hw + 정책 hook 아홉, `pe.lostAfterCommit`; `harness/gpu-detect/hk_layer.diff`, 사전 등록 파일이라 고치지 않음; 빌드 트리
`agent_gd/gin_hk`). 그 트리를 세션 스크래치의 새 트리로 복사하고 이 계층을 그 위의 diff 하나(`rs_layer.diff`)로 쌓는다. 실행 가능성 시험의 초기화 재생
hook(`feas/rs_spike.diff`)은 hw 위에 있었으므로 hk 위로 옮긴다. 빌드는 둘: 연구 빌드 `rs`와 운영 빌드 `rsp`(gin-remaining의 `hrp`처럼). 새 빌드는 늘 새 폴더에
두고, 배포는 `~/rs-bundle/` 안의 새 디렉터리와 앞뒤 md5 확인(`deploy_feas.sh` 틀). rain의 BAR1 때문에 시험의 window는 하나에 24 MiB 이하.

**작업 묶음(차례대로; 묶음마다 빌드와 독립 검토를 마친 뒤 다음으로).** "장치 헤더"는 `gin_gdaki.h`와 `gin_gdaki_device_host_common.h`, "호스트 파일"은
`gin_host_gdaki.cc`다. 코드의 자리는 9.9절의 hook 목록(괄호 안은 그 목록에서 찾는 키).

1. **정책 도우미, strict 강제, G1 기록 넓히기, 정하는 자료.** 호스트 파일만. 정책 값(`NCCL_GIN_FAULT_POLICY`, `NCCL_GIN_RESTORE`)을 프로세스마다 한 번 읽는
   도우미를 G1과 같이 쓰고, `ncclGinGdakiRegMrSym`에서 hold 프로세스와 예비 프로세스의 window MR을 strict로 등록하며, G1 기록의 `policyPad`에 "복원 요청"과
   strict 비트를 싣고, all-gather 바로 뒤 모든 rank가 같은 자료로 거절 여부와 이유를 정한다(9.10.8절; RL21). 충돌 확인: 9.10.8절 표 전체. 빌드와 단위 확인:
   새 트리 빌드, 정하는 함수를 CPU에서 가짜 기록 묶음(모두 hold, 한 rank 복원 끔, 정책 섞임, FULL이 아님)으로 시험, 등록 길에서 hold일 때 RO 비트가 빠지는지
   디버그 빌드의 계수로 시험. pilot이 보여야 할 것: hold 셀의 모든 window 등록이 강제됨, 복원 끈 셀은 강제 0(`strict_forced`).
2. **공개 API와 `ncclGinRestoreResume`의 검사와 오류.** 공개 호스트 헤더(`nccl.h.in`의 새 함수 `ncclGinRestoreResume`, `ncclGinRestoreStep`,
   `ncclGinRestoreRegister`)와 그 함수를 communicator에서 GIN 문맥으로 잇는 GIN 핵심 파일(`gin/gin_host.cc`나 새 파일) + 호스트 파일. 장치 헤더는 아님.
   Resume은 devComm을 받고(9.10.8절), 켤 수 없는 까닭(GDAKI 아님, 투명 복구 꺼짐, host RMA 켬, `NCCL_GIN_TYPE`이 3이 아님, symmetric 커널의 GIN devComm 있음,
   rank 사이 `NCCL_GIN_RESTORE` 다름, strict 비트 0, FULL이 아님)을 이유 문자열과 함께 모든 rank에서 같게 돌려준다. 충돌 확인: 9.10.4절 무장 조건, 9.10.8절의
   사용자 결정, 복원 계층 코드를 GDAKI 파일에만 둔다는 규칙의 예외(공개 API의 입구) 기록. 빌드와 단위 확인: 이유 함수의 CPU 시험. pilot: 켤 수 없는 셀 셋
   (`refuse_reason`).
   2026-10-12 사용자 결정(9.10.8절)으로 바뀐 것: Resume은 모든 rank가 부르는 집합 호출이다. rank마다 지역 판정(설정 기록의 결정, 설정 때의 지역 결과, Resume 때
   보는 9.10.4절의 모든 무장 조건과 위 까닭, 이미 application에 닿은 장애)을 만들어 communicator의 bootstrap all-gather로 모으고, 모든 rank가 같은 자료로
   정한 결과와 이유를 돌려준다. 모음은 `NCCL_GIN_RESTORE_RESUME_MS`(기본 30 000 ms)까지 기다리고, 넘으면 communicator의 abort 깃발을 세워 모음을 풀고 오류를
   돌려준다(그 communicator는 `ncclCommAbort`로만 끝냄). 두 번째 호출은 첫 결과를 모음 없이 돌려준다. 이유는 그 호출 바로 전의 WARN이라 `ncclGetLastError`로
   읽는다. 입구는 `nccl.h.in`과 `gin/gin_host.cc`(communicator의 사실, bootstrap 모음, abort 깃발)이고 판정과 정하기는 호스트 파일에 둔다. `ncclGinRestoreStep`과
   `ncclGinRestoreRegister`는 이 묶음에서 "이 빌드에 아직 없음"으로 오류를 돌려주는 자리만 둔다. 빌드와 단위 확인에 더함: 여러 rank를 흉내 낸 모음에서 모든 rank가
   같은 결과, 부르지 않는 rank가 있을 때의 시한, 이유마다.
3. **측 표, GPU 문맥 판, 복원 버퍼의 루프백 MR, 자원 window.** 장치 헤더(`ncclGinGdakiGPUContext`의 측 표 포인터 칸과 판 번호; DV1, A5)와 호스트 파일
   (`gdakiTsStart`에서 측 표와 로그 고리 할당, 동기 H2D 한 번; 루프백 MR에 rkey 표, 신호와 카운터 표, 로그 고리, 측 표; Resume에서 사용자 devComm의 자원
   window를 새 lb 잠금 안에서 더함; RL9, RL10). 충돌 확인: 9.11.5절(A1, A5), 9.10.4절의 측 표 포인터 조건, 9.10.8절의 자원 window 행. 빌드와 단위 확인: sm_75와
   sm_86 빌드, fail-fast에서 포인터 0이고 장치 동작이 hk와 같음을 gpu-detect 회귀 셀의 판정으로 확인할 준비. pilot: `regression`(fail-fast 같음).
   2026-10-12 더함: 측 표 할당의 실패, 복원 버퍼가 루프백 MR에 없음, 사용자 문맥 뒤에 등록한 사용자 window를 Resume의 지역 판정에 더한다(9.10.8절).
   2026-10-12 사용자 결정(원문 그대로: "가로 해야지"): GPU 문맥 판은 올리지 않고 측 표 포인터를 `ncclGinGdakiGPUContext` 끝에 더한다(9.11.5절의 GPU 문맥 판
   행). 그래서 이 묶음의 장치 헤더 변경은 구조체 끝의 포인터 하나이고, 이 라이브러리와 쓰는 모든 프로그램은 이 계층의 헤더로 빌드해야 한다.
4. **장치 보내기 길.** 장치 헤더(`gin_gdaki.h`): 게이트 뒤 키 다시 읽기(결정 (나), DV3), SUPPRESS 비트와 느린 길(DV4), 게이트 안의 로그 쓰기와 "로그 켬"
   낱말(DV2). 충돌 확인: 9.11.9절(C2, C6), 9.11.5절(A1), 9.10.6절 (다)의 fail-fast 같음. 빌드와 단위 확인: 두 아키텍처 빌드, fail-fast의 명령 차례가 hk와
   같음을 SASS 비교 또는 코드 검토로, 비용 셀의 준비. pilot: `cost_ff`(갈리지 않음), `cost_unarmed`, `cost_log`의 첫 값.
5. **체크포인트.** 호스트 파일 + 공개 API(`ncclGinRestoreStep`): 단계 hook, 입력 멈춤의 빈 라운드(RL12), drain 확인(응답 쪽 QUERY_QP와 측 표의 루프백
   READ; strict, 9.4절 3단계), 장치 안 복사(copy engine), 짝의 메모리로 보내기(자료 서버 RL18), PAUSED와 RESUME 메시지(RL11). 충돌 확인: 9.11.9절(C1),
   9.11.4절(T2, T5), QUERY_QP 상한. 빌드와 단위 확인: 라운드 회계의 CPU 시험. pilot: `rs4_none`의 체크포인트마다 멈춤 ≤ 5 ms, `none_clean`.
6. **보낸 쪽 로그 관리.** 호스트 파일(장치 쪽 쓰기는 4에서): 로그 고리의 자리 관리, 넘침이면 그 상대 DISARM(9.5절), 로그 내보내기. 충돌 확인: 9.10.4절의
   상대 무장 합의. 빌드와 단위 확인: 멈춘 시제품 초안(9.13절)의 고리와 넘침 논리를 CPU 시험으로. pilot: 로그 크기와 넘침 0.
7. **붙잡기 상태 기계.** 호스트 파일만: G2의 hold 분기(RL1), 기록 흡수(RL2), 감시와 유실 검사의 hold 분기(RL3), helper 루프의 한 걸음(RL4), 무장 조건
   검사(RL5), 메시지 미루기(RL17, RL20), TOLD 판단, HOLDING과 FALLBACK 메시지, fallback. 충돌 확인: 9.10.5절, 9.10.7절의 상태 기계, 9.11.1–9.11.4절의 행. 빌드와
   단위 확인: 표로 쓴 전이의 CPU 모형 시험. pilot: `fallback_nospare`, 생존 rank의 대기 붙잡기 일부.
8. **예비 프로세스.** GIN 밖의 NCCL 핵심 파일(초기화 재생 hook: `bootstrap.cc`, `init.cc`, `transport/net_ib/gin.cc`, `dev_runtime.cc`, `gin/gin_host.cc`;
   실행 가능성 시험의 hook을 다듬음) + 호스트 파일(REJOIN RL6, 끝점 바꾸기 RL7, 원래 프로세스의 PID 확인, 예비 프로세스 모드의 strict 강제). 장치 헤더는 아님.
   충돌 확인: 9.15.4절의 범위(그때는 2 rank; 이제 4 rank, GPU마다 둘), 9.10.4절 무장 조건, 9.11.5절(A3). 빌드와 단위 확인: 실행 가능성 시험 B1과 같은 재생 시험
   (상대로의 connect 0, 음성 대조 둘)을 4 rank 배치로. pilot: 활성화와 초기화 재생 시간.
   2026-10-12 더함(9.10.8절): Resume이 bootstrap all-gather를 하는 집합 호출이 되었으므로, 원래 rank는 첫 Resume의 모음 결과를 초기화 기록에 넣고, 예비
   프로세스의 Resume은 그 모음을 기록으로 대답한다(생존 rank는 그때 Resume을 부르지 않음). 예비 프로세스 자신의 지역 판정이 "켤 수 없음"이면 복원을
   포기한다(fallback). 설정 기록에서 살아 있는 설정의 예비 프로세스를 거절하는 규칙(작업 묶음 1)과 예비 프로세스 자신의 결정도 이때 정한다.
9. **다시 넣기와 억제.** 호스트 파일(로그 적용, 계획 `U = S, n = 0` RL8, 누적 실행 수 RL13, 억제 예산을 측 표에) + 장치 쪽은 4의 SUPPRESS를 씀. 충돌 확인:
   9.11.3절(M2), 9.6절. 빌드와 단위 확인: 억제 예산 계산의 CPU 시험. pilot: `suppress_exact`, `data_equal`, `no_reexec`, `revived_done`, `restore_time`.
10. **시험 프로그램, 실행기, 채점기, pilot.** `gin_rs.cu`(9.8절의 workload; COLL_SYMMETRIC window 없이 또는 `NCCL_SYM_GIN_KERNELS_ENABLE=0`), 예비 프로세스를
   함께 띄우는 실행기, 셀 파일, 채점기. pilot은 모든 셀을 작은 n으로 돌려 2, 3, 7, 8절의 문턱과 n을 정하고, 그 뒤 사전 등록(예측 표 파일, `PREREG.txt`, 태그
   `prereg/gin-restore-v1`), 본 실행, QA.

장치 헤더를 바꾸는 묶음은 3과 4뿐이고, GIN 밖의 NCCL 핵심 파일을 바꾸는 것은 2(공개 API의 입구)와 8(초기화 재생)이다. 나머지는 호스트 파일만 바꾼다. 묶음마다
빌드됨과 시험함을 따로 적고(실행하지 않은 것을 성공이라 쓰지 않음), 독립 검토의 판정을 12절에 남긴다.

### 9.15 실행 가능성 시험 B1, B2, B3 (DRAFT 단계, 채점하지 않음)

사용자 결정(2026-10-09)으로 막는 문제 B1–B3(9.11.12절)이 풀릴 수 있는지 먼저 시험한다. 사전 등록하지 않고 채점하지 않는다.
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
  `runtimeConn = 1`, `nvlsSupport = 0`, host RMA 꺼짐(B1 T1-1), 그리고 application 요구로 host에서 띄우는 NCCL 통신 없음(9.7절 6번). 9.10.4절.
- 해결 B: 어느 rank든 `lsaSize ≥ 2` → 9.11.12절 B2의 풀 조건대로 LSA 팀에 든 상대는 무장하지 않는다(그 상대의 죽음은 fail-fast). 복원 셀 배치를 다시 본다.
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
  - 두 노드에서 `ro`와 `so` 모두 통과 → 이 플랫폼, 이 설정에서 READ 하나로 drain 확인이 맞다. strict 조건(9.10.4절)을 뺄지는 사용자 결정으로 둔다(RO가 실제로
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
확인하고 그 뒤 사용자가 B3을 다시 정한다. 그때까지 B3은 "열림, 사용자 결정 대기"이고 무장 조건 "window는 strict"(9.10.4절)는
그대로다. 노드 사이 셀과 같은 노드 셀(`x`, `s`)은 다시 하지 않는다. 셀의 판정 기준(채점 fence 실패 0; `early` 10반복 이상, `boundary` 10반복 이상, 경계 덮기
50% 이상; 질의 예산 19 000, 상한 20 000)은 그대로다. 묶음 규칙은 바뀐다: 노드와 순서 하나는 `x`, `s`, `h` 대신 `x`, `s`, 새 경합 셀 `m`의 마지막 실행으로
묶는다(사용자 결정, 12절). 아래는 그 확인의 설계다. 빌드 전에 충돌 표와 설계의 독립 검토(D1–D15, 12절)를 거쳤다.
- 옛 경합 셀(`b3_h_*`, 다른 프로세스의 hog): 실행과 원자료, 2026-10-09 결과 문단은 그대로 둔다. 사실만 적는다: rain은 `ro`, `so` 각 두 실행 모두 미결
  (`early` 0/191, `boundary` 0/190–191), sunny `ro`는 통과(22, 13), sunny `so`는 미결 뒤 다시 해서 통과(19, 10). 묶음에서 빠지고, 그 결과는 새 판정을 살리지도
  깎지도 않는다(summ_feas가 따로 보임).
- 복사 시각(새 바이너리 `b3v4`, 모든 셀): 응답 쪽이 사본 복사의 바로 앞과 뒤에 CUDA event(기본 flag)를 넣고, 뒤 event를 넣은 바로 다음(다른 CUDA 호출 없이)
  호스트가 그 event를 돌며 묻는다. 복사의 끝은 [아직이라고 답한 마지막 질문의 시작, 끝났다고 답한 첫 질문의 끝] 안에 있고(호스트 시계), 두 event 사이의
  GPU 시간을 빼면 시작의 구간이 된다. 기준 시각은 `early`는 PAUSED를 받은 때, `boundary`는 rmsn = M − 1을 돌려준 QUERY_QP가 돌아온 때, 그 밖의 길은 rmsn = M을
  돌려준 QUERY_QP가 돌아온 때다. 도달(reach)은 지금처럼 M을 돌려준 QUERY_QP의 시작이다. 사본마다 길, 꼬리, 이 시각들, 낱말 셈을 메모리에 두었다가 고리 뒤에
  `<cell>_resp_timing.tsv`로 쓴다(원자료, git이 따르지 않음, release에 올림). 복사 앞에 시각을 찍는 커널은 넣지 않는다(커널은 그 자체가 시간 나눔을 기다려
  재려는 것을 바꿈). 채점 고리의 차례는 그대로이고, 뒤 event를 기다리는 동안 그 반복의 신호 읽기와 검사가 복사 시간만큼(µs) 늦어진다(AW의 원자 연산이
  4 MiB 쓰기 앞이라 신호 검사의 힘은 그대로 `[추론]`). 응답 쪽의 stream은 모두 non-blocking이고 사본과 탐침의 stream은 가장 높은 우선순위다(kv에 적음).
- 엔진 확인(`b3v4`, 셀마다 한 번, 자체 시험 뒤, hog 스레드 전): 모든 SM을 채우는 5 ms 회전 커널을 다른 stream에 낸 뒤 window 크기의 D2D 복사를 event와 함께
  낸다. 복사가 회전이 끝나기 전에 끝나면 copy engine(`d2d_engine=ce`), 아니면 SM(`sm`)이다. 시간 나눔 설명은 복사가 GPU 시간 조각을 기다릴 때만 맞으므로
  읽기에 함께 적는다.
- 진단(판정 없음, `b3_diag/`; 노드마다 hold 하나): 셀은 노드마다 셋, `ro`만, 각 640반복(`early`, `boundary` 각 40, 채점 fence 320, 뒤에 탐침 40),
  `RS_LAST_KB=4096`, 예산 19 000(셀마다 QUERY_QP 약 4 200 예상): `b3_dn_<node>_ro` hog 없음, `b3_dp_<node>_ro` 옛 경합 셀과 같은 다른 프로세스의 hog,
  `b3_dm_<node>_ro` 새 경합 셀과 같은 프로세스 안의 hog.
- 진단의 읽기(실행 전 고정, 노드마다; 아무것도 정하지 않는다): `early` 반복에서 시작 구간의 아래 끝이 그 실행의 reach p50보다 뒤면 "늦음", 끝의 위 끝이 reach
  p50보다 앞이면 "제때"다. 읽기 1(시간 나눔 추론): `dp`의 `early` 반복 90% 이상이 늦음이고 `dn`의 90% 이상이 제때면 "맞음", `dp`의 50% 이상이 제때면 "틀림"
  (복사는 쓰기가 끝나기 전에 끝났는데 대조가 0이니 다른 까닭), 그 밖은 "불분명"이다. 읽기 2(프로세스 안 복사가 제때인가): `dm`의 `early` 시작 위 끝 p90이 `dm`
  reach p50의 1/4보다 짧으면 "예". 함께 적는 것: 늦은 낱말이 잡힌 `early` 반복과 아닌 반복의 시작 p50(sunny의 약 10%가 일찍 시작한 반복인지), 엔진, hog 대역.
- 정하는 실행(2026-10-11 코드 검토 V2, 진단 전에 고정): 진단을 다시 하면 한 노드의 읽기와 관문은 그 노드의 진단 폴더 가운데 `dn`, `dp`, `dm`이 모두 오류
  출구 없이 끝나고 시각 파일이 있는 가장 나중의 것 하나로 정한다. 엔진은 `dn`의 값으로 정하고 `dm`이 같아야 한다(다르면 올림). `dp`의 엔진 확인은 hog 프로세스나
  남의 GPU 작업과의 시간 나눔이 회전 커널을 흐트러뜨릴 수 있어 정보다. 엔진 값이 그 확인의 복사 시간과 어긋나면(`ce`인데 1 000 µs 이상, `sm`인데 1 000 µs
  미만) 올린다(V3). 읽기 2 옆에 `dm`의 `early` 끝 위 끝 p90과 GPU 시간 p90을 정보로 적는다: 시작 어림은 앞 event가 끝난 때라 복사가 그 뒤에 기다리면 시작이
  아니라 GPU 시간이 길어진다(V7).
- 관문(실행 전 고정; 진단에서 정하는 것은 이것뿐): 노드마다 `dm`에서 (1) `early` 늦은 낱말이 10반복 이상이면서 `early` 반복의 50% 이상, (2) `boundary`의 마지막
  메시지 늦은 낱말이 10반복 이상이면서 사본을 뜬 `boundary` 반복의 50% 이상, (3) reach p50의 오름(`dm` − `dn`)이 `dp`의 오름(`dp` − `dn`)의 절반 이상(NIC 쪽이
  비슷한 경합을 봄; 옛 rain은 795 → 1 076 µs)이면 그 노드의 새 셀 둘을 한다. 넘지 못하면 하지 않고 사용자에게 올린다. hog 대역은 정보다(`dp`와 `dm`은 프로세스
  경계와 커널 모양이 둘 다 달라 대역 차이를 프로세스 경계 탓으로만 돌릴 수 없다).
- 2026-10-11 사용자 결정(진단 뒤, sunny 새 셀의 결과 전, 선택지 (가)): sunny에서는 관문 (3)을 적용하지 않는다. 까닭: 진단에서 sunny의 reach p50은 `dn`
  644.9 µs, `dp` 619.6 µs(오름 −25.3), `dm` 628.0 µs(오름 −16.9)라 두 hog 모두 NIC 쪽 도착을 늦추지 않았다 `[측정]`. (3)은 hog 프로세스가 도착을 늦춘다(오름이
  양수)는 전제였으므로 음수 오름의 절반은 뜻이 없다. sunny의 관문 (1), (2)는 넘었다(`dm` `early` 40/40, `boundary` 40/40). 그래서 sunny의 새 셀 둘은 정의대로
  한다(`b3v4`, 같은 셀 규칙, 예산, 상한, 판정). 기록에는 sunny의 새 셀이 쓰기 도착을 늦추는 경합을 보이지 않고 "프로세스 안 메모리 부하 아래에서 제때 낸 복사"만
  시험한다고 적는다. 범위: sunny의 관문 (3)만. rain은 그대로다(관문 셋 모두 넘음). summ_feas는 sunny에 "gate item 3 not applicable (user decision
  2026-10-11)"을 적고, 다시 한 진단에서 sunny의 오름이 양수로 나오면 올리라는 메모를 붙인다.
- 새 경합 셀 `b3_m_<rain|sunny>_<ro|so>`(옛 `b3_h_*`를 대신함): 노드 사이(이름의 노드가 응답 쪽)이고, 응답 프로세스 안의 hog 스레드가 엔진 확인 뒤부터 마지막
  반복 뒤까지 가장 낮은 우선순위의 non-blocking stream에 round마다 복사 커널 8개를 내고 그 stream만 기다린다. 커널은 SM 수의 3/4만큼의 256-thread block이
  256 MiB 두 버퍼 사이를 grid-stride로 옮긴다(스레드마다 float4 8개를 한꺼번에 읽고 씀). 나머지 SM은 비어 사본 복사(SM 커널일 경우), 검사, 1 024-thread
  탐침 block(Turing은 SM마다 1 024 thread)이 hog block이 빠지기를 기다리지 않는다. 같은 CUDA 문맥이라 시간 나눔이 없다. 3 200반복, `RS_LAST_KB=4096`, 예산
  19 000, 상한 20 000, 셀마다 hold 하나, 결과는 `b3m_run<k>/`. 새 셀과 `dm`의 탐침은 시작이 늦을 수 있어 정보로만 적는다. 판정 기준은 위와 같다(노드와 순서
  하나는 `x`, `s`, `m`이 모두 유효하고 통과일 때 통과; 실패율 95% 상한 3/(3 200 + `m`의 채점 수)).
- 새 셀이 대표하는 경합 `[추론]`: 응답 쪽 GPU의 메모리 대역을 같은 프로세스의 다른 커널이 채우는 동안 NIC 쓰기가 들어오고, 체크포인트의 복사가 제때 시작하는
  경우다. 메모리가 바쁠 때 rmsn = M 뒤에도 쓰기가 늦게 보이는 틈이 있다면 드러날 수 있는 경우이고, 대조가 힘을 가지면 B3의 물음(rmsn = M과 READ 하나 뒤 복사에
  모든 쓰기가 보이는가)에 경합 아래에서 답한다. 사본 복사를 가장 높은 우선순위로 내는 것은 실제 설계(application의 stream에서 커널 사이에 복사, 9.4절 3단계)보다
  엄한 쪽이다. 배치에서 실제로 생기는 경우는 다른 프로세스와의 시간 나눔이다(GPU를 나눠 쓰는 rank와 예비 프로세스, B2). 시간 나눔은 rmsn = M과 READ 뒤에
  넣은 복사를 늦출 수만 있고 NIC 쓰기가 보이는 것은 어느 문맥이 GPU를 잡고 있는지와 무관하므로, 그 경우는 rmsn = M과 복사 사이가 넓어지는 쪽이다. 그 경우의
  자료는 옛 셀(실패 0, 대조가 rain에서 잡히지 않음)뿐이다.
- 새 셀이 다시 미결이면 그 셀만 한 번 다시 하고(`b3m_run2/` 등, hold 이름에 꼬리표를 붙여 hold마다 다른 이름), 그래도 미결이면 사용자에게 올린다. 그 뒤의
  재설계나 실행은 사용자 결정 뒤에만 한다. `FENCE_FAIL`은 다시 하지 않고 결과로 올린다. 오류 멈춤은 9.15.5의 STOP 규칙을 따른다. 응답 쪽 GPU에 다른 사용자의
  compute app이 `dm`이나 새 셀 동안 있었으면(실행기가 셀 앞뒤로 적음) 시간 나눔이 돌아오므로 12절에 적는다.
- 결과 폴더는 `x`, `s` 셀과 같은 `results/20261009_feasibility/`다(9.15.5의 날짜 규칙에서 벗어남: summ_feas가 한 폴더에서 묶음). `b3v4`는 `~/rs-bundle/b3v4/`에
  새로 둔다. 실행기의 기본 바이너리는 `b3v3` 그대로이고 hold가 새 셀과 진단 셀에만 `b3v4`를 넘긴다(`x`, `s` 셀을 다시 해도 바이너리가 몰래 바뀌지 않음).

**결과(2026-10-11, 경합 셀 다시 확인 뒤).** `[측정: results/20261009_feasibility/b3m_run1/, b3_diag/; 이 에이전트가 원자료에서 다시 셈, summ_feas.py, 12절]`
- 새 경합 셀 넷(`b3v4`, 프로세스 안 hog) 모두 유효하고 통과: rain `ro` 채점 fence 실패 0/1 463(예산으로 2 926반복에서 끝남), rain `so` 0/1 445(2 891반복),
  sunny `ro` 0/1 600, sunny `so` 0/1 600(3 400반복, 예산에 닿지 않음). 대조는 모든 셀에서 해당 반복마다 잡혔다(`early` rain 183/183, 180/180, sunny
  200/200 둘; `boundary` rain 182/182, 181/181, sunny 200/200 둘), 경계 덮기 1.000, 사본 복사는 `early` 반복 모두 제때(늦음 0, 시작 위 끝 p50 rain 7.9 µs,
  sunny 10.4–10.6 µs). hog 대역 rain 326.4–326.5 GB/s, sunny 366.5–366.7 GB/s, 엔진 `sm`.
- 노드와 순서마다의 묶음(`x`, `s`, `m`의 마지막 실행, 셋 다 유효하고 통과): rain `ro` 채점 4 663(실패율 95% 상한 약 0.0643%), rain `so` 4 645(약 0.0646%),
  sunny `ro` 4 800(0.0625%), sunny `so` 4 800(0.0625%). 각 상한은 그 노드와 순서 하나의 묶음에 대한 값이다. summ_feas의 B3 결론 줄: "READ-fence drain
  check holds on this platform as configured for ro and so (strict condition: user decision)". 본 셀 폴더의 모든 실행을 합치면(smoke와 진단 제외, 유효 여부와
  무관, 판정 규칙의 묶음이 아님) 채점 fence 29 815반복에서 실패 0이다.
- 경합의 뜻: rain의 새 셀은 reach p50이 1 074.0–1 074.3 µs로 노드 사이 셀(795 µs 안팎)보다 약 279 µs 길어 쓰기 도착이 늦어지는 경합 아래였다. sunny의 새 셀은
  reach p50이 617.2–619.6 µs로 노드 사이 셀(647 µs 안팎)보다 길지 않아, 사용자 결정(관문 (3) 적용 안 함)대로 쓰기 도착을 늦추는 경합을 보이지 않는다. sunny의
  새 셀은 "프로세스 안 메모리 부하 아래에서 제때 낸 복사"만 시험한 것이다.
- READ의 몫: 모든 셀에서 READ 없이 rmsn = M 뒤 바로 복사한 대조 길(`nofence`)도 실패 0이다(새 셀마다 `W`, `AW` 각 181–200반복; `fence_same`, `cuflush`,
  `WA` 꼬리도 0). 그래서 이 시험은 "rmsn = M을 본 뒤 낸 복사에는 쓰기가 보인다"를 보이고, 그것을 READ 덕분으로 돌리지 못한다. 시험의 힘은 QUERY_QP 지연(셀마다의 p50
  53.9–69.8 µs)만큼의 창에 한정된다.
- 보이지 않는 것: 다른 프로세스가 GPU를 시간 나눔으로 쓰는 경우(옛 경합 셀, 대조의 힘 없음), 다른 하드웨어와 설정 `[미확인]`. strict window 무장 조건을
  뺄지는 사용자 결정으로 남는다(이 에이전트는 정하지 않음).
- relaxed(`ro`) 셀의 RO가 NIC 쪽에서 허용됐는가(2026-10-11 메인 세션의 읽기 전용 sudo 읽기, 12절): 두 노드의 NIC와 GPU DevCtl이 `RlxdOrd+`, 두 NIC의
  `PCI_WR_ORDERING`이 `per_mkey(0)`이므로, `ro` 셀은 window MR의 RO flag가 실제로 허용된 채 돌았다 `[측정]`. root complex가 그 쓰기를 실제로 바꿔 놓았는지는
  볼 수 없다 `[미확인]`. 위 결과와 그 해석은 바꾸지 않는다.

충돌 표(2026-10-11 바꿈, 9.15.1에 더함):

| 자원 | 이 바꿈 | 겹치는 것 | 처리 |
|---|---|---|---|
| GPU 메모리와 SM | 진단 `dm`과 새 셀: 응답 프로세스 안의 hog 버퍼 512 MiB와 복사 커널(SM의 3/4), 셀마다 엔진 확인의 5 ms 회전 커널 한 번. 진단 `dp`: 옛 hog 프로세스(같은 크기) | 다른 사용자의 GPU 작업 | 옛 경합 셀과 같은 크기. 셀 앞뒤로 두 노드의 compute app을 적음. hog 스레드는 고리 뒤에 멈추고 결과 줄 전에 합류, 프로세스는 `timeout`과 watchdog으로 묶임 |
| NIC 펌웨어 명령 | 진단 셀마다 QUERY_QP 약 4 200, 새 셀마다 19 400 이하(예산 19 000, 상한 20 000 그대로). rain이 응답 쪽인 것은 진단 셋과 새 셀 둘, 합 약 51 400(다시 하면 셀마다 19 400까지 더함), hold 셋 이상에 나뉨 | rain의 새는 명령 slot | 셀마다 상한, hold 앞뒤로 rain debugfs 셈을 적음, 9.15.5의 STOP 규칙. 앞선 예: B3r은 hold 하나에 69 993, 실패 셈 31 → 31 |
| 링크 | 진단 셀마다 약 3.5 GB, 새 셀마다 약 17 GB(옛 경합 셀과 같음) | 다른 사용자의 RDMA 작업 | `cluster_run.sh`가 링크가 한가할 때 시작 |
| 노드의 파일 | 새 `~/rs-bundle/b3v4/`. 응답 쪽 시각 파일은 rain에서 실행기의 작업 디렉터리, sunny에서 `/tmp/rs_b3_*`(실행기와 hold의 자기 파일 지우기 대상) | `~/rs-bundle`의 다른 파일, 다른 묶음 | 배포는 새 디렉터리만, 앞뒤 md5 |
| 결과 폴더와 git | 새 `b3_diag/`, `b3_diag_run<k>/`, `b3m_run<k>/`(모두 `20261009_feasibility/` 안). 시각 파일은 `.tsv`(git이 따르지 않음) | 옛 `b3/`, `b3_rerun<k>/`; `.gitignore`가 `*.csv`를 따름 | 옛 것을 덮지 않음. 원자료는 release에 올림. summ_feas는 진단을 판정과 모든 실행의 합에서 뺌 |
| 판정 규칙 | 셀의 유효와 통과 기준은 그대로, 묶음은 `x`, `s`, `h` → `x`, `s`, `m` | 9.15.3의 판정 | 사용자 결정으로 12절에 날짜, 까닭, 범위를 적음 |
| hold와 셀 | 진단은 노드마다 hold 하나(`B3diag-<node>`), 새 셀은 셀마다 hold 하나(`B3m-<cell>`), 다시 하는 hold는 꼬리표로 이름을 다르게 | 9.15.1의 "rain과 sunny가 응답 쪽인 셀은 다른 hold" | 그대로 지킴. `mlx5_new_<hold>.txt`가 덮이지 않음 |
| 프로세스와 CPU | 프로세스 안 hog는 스레드라 끄는 일이 없음(고리 끝의 멈춤 표시). hog 스레드의 기다림이 CPU 코어 하나를 씀(`nproc`을 kv에 적음) | 다른 사용자의 프로세스 | 이름으로 끄지 않음. 남은 프로세스 검사는 그대로(`rs_drain_test`) |
| 라이브러리와 다른 실험 | NCCL을 쓰지 않음 | gpu-detect, 다른 에이전트의 트리 | 겹침 없음 |

#### 9.15.4 B1: 예비 프로세스의 초기화 재생 spike

**질문.** 장애 없는 2-rank 실행에서 한 rank의 초기화 기록을 남기면, 같은 노드의 예비 프로세스가 다른 rank의 참여 없이 그 기록만으로 초기화를 끝내고
같은 rank, nRanks, GIN 문맥 수, 신호 수, window 크기, 모든 상대에 대한 게이트 상태(`gated`, `addr`, 장치 게이트 구조)를 얻는가(9.11.5절 A3, 9.11.9절 C3, 9.11.13절 V13).
장애 주입과 복원 라운드는 없다. 답은 lsaSize 1인 배치에만 해당한다(lsaSize 2 이상이면 메모리 handle의 파일 기술자를 상대 proxy에서 받아야 해 기록할 수 없음,
`dev_runtime.cc` 322–328; T1-4).

**전제(검토 T1-1, T1-4).** host RMA proxy는 기본으로 켜져(`numRmaCtx` 기본 1, `init.cc` 2798; `ncclRmaProxyEnabled` `rma/rma.cc` 19–21) 첫 window 등록에서
모든 상대에게 hook 밖의 IB 연결을 맺는다(`ncclRmaProxyConnectOnce` → `ncclRmaIbProxyCreateContext`, `transport/net_ib/gin.cc` 545–556) `[소스]`. 그래서 B1의
모든 실행은 `NCCL_NUM_RMA_CTX=0`, `NCCL_RMA_DISABLE=1`이고, 재생 hook은 `numRmaCtx ≠ 0`, `NCCL_OOB_NET_ENABLE=1`, RAS 켜짐 가운데 하나라도 있으면 재생을
거절한다. 이것은 복원의 무장 조건이기도 하다(9.10.4절, 9.11.5절 A3).

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
  `gdakiTsStart`는 게이트 설정까지 하고 helper 스레드를 띄우지 않는다(설치 전에는 아무에게도 말하지 않는 예비 프로세스, 9.11.1절 D4). 상대에 이어진
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
progress_iterations_done`)을 쓴다(2026-10-09 다시 검토 U2). (2) `RS_QUERY_BUDGET`(기본 꺼짐)이 있으면 반복을 시작할 때 QUERY_QP가 그 수 이상인지 보고 그러면 고리를 마친다
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

**2026-10-11 경합 셀 넷의 다시 확인: `b3v4`, 진단, 새 경합 셀(9.15.3).** `rs_drain_test` `b3v4`(빌드됨, 실행 안 함; md5 `c7cad09beb0092b3840899964bfee746`,
컴파일 때 소스 `a3534807`). 결과 폴더는 `x`, `s` 셀과 같은 `results/20261009_feasibility/`다. hold는 노드마다 진단 하나, 새 셀마다 하나다. 아래 차례대로 하고, 앞
단계에 STOP 파일이 생기면 9.15.5의 STOP 규칙대로 멈춘다.

```
R=~/rdma-error-wt/gin-restore/harness/gpu-initiated/gin_recovery/restore/results/20261009_feasibility
# b3v4 배포: 새 디렉터리 ~/rs-bundle/b3v4/ 하나만(있으면 거절), 그 밖의 ~/rs-bundle과 다른 묶음은 앞뒤 md5가 같아야 함. 약 30 s
ls -d ~/rs-bundle/b3v4; ssh -n "$SUNNY_SSH" 'ls -d ~/rs-bundle/b3v4'      # 둘 다 "No such file"이어야 함
WANT_B3V4=c7cad09beb0092b3840899964bfee746 bash $F/deploy_feas.sh $SCR/agent_restore/deploy_check_b3v4.txt b3v4
test -s $SCR/agent_restore/deploy_check_b3v4.txt && echo written
grep -E "MISMATCH|CHANGED|not found" $SCR/agent_restore/deploy_check_b3v4.txt   # 아무 줄도 없어야 함
# 진단(판정 없음): rain이 응답 쪽인 hold, 그다음 sunny. hold마다 셀 셋(dn, dp, dm) x 640반복, 약 1–2분
bash $CR -w 10800 -t rs-B3diag-rain -- timeout -s KILL 880 bash $F/hold_feas.sh $R B3diag-rain > $R/hold_B3diag-rain.out 2>&1
bash $CR -w 10800 -t rs-B3diag-sunny -- timeout -s KILL 880 bash $F/hold_feas.sh $R B3diag-sunny > $R/hold_B3diag-sunny.out 2>&1
python3 $F/summ_feas.py $R      # "reading 1", "reading 2", "gate for b3_m_<node>_ro and ..._so" 줄을 봄
# 관문을 넘은 노드의 새 경합 셀만(셀마다 hold 하나, 3 200반복, 예산 19 000; 결과는 b3m_run1/). 셀마다 약 30–60 s
bash $CR -w 10800 -t rs-B3m-rain-ro -- timeout -s KILL 880 bash $F/hold_feas.sh $R B3m-b3_m_rain_ro > $R/hold_B3m-b3_m_rain_ro.out 2>&1
bash $CR -w 10800 -t rs-B3m-rain-so -- timeout -s KILL 880 bash $F/hold_feas.sh $R B3m-b3_m_rain_so > $R/hold_B3m-b3_m_rain_so.out 2>&1
bash $CR -w 10800 -t rs-B3m-sunny-ro -- timeout -s KILL 880 bash $F/hold_feas.sh $R B3m-b3_m_sunny_ro > $R/hold_B3m-b3_m_sunny_ro.out 2>&1
bash $CR -w 10800 -t rs-B3m-sunny-so -- timeout -s KILL 880 bash $F/hold_feas.sh $R B3m-b3_m_sunny_so > $R/hold_B3m-b3_m_sunny_so.out 2>&1
python3 $F/summ_feas.py $R
# 미결인 새 셀만 한 번 다시(꼬리표 -r2로 hold 이름을 다르게; 결과는 b3m_run2/). 예:
bash $CR -w 10800 -t rs-B3m-rain-ro-r2 -- timeout -s KILL 880 bash $F/hold_feas.sh $R B3m-b3_m_rain_ro-r2 > $R/hold_B3m-b3_m_rain_ro-r2.out 2>&1
```

`summ_feas.py`는 돌 때마다 결과 폴더의 `SUMMARY.txt`를 새로 쓴다(2026-10-09의 내용은 `SUMMARY_20261009.txt`).
진단 뒤 볼 것: 셀마다 응답 쪽 kv에 `d2d_engine`, `hog=`(응답 프로세스 안 hog만 뜻함: `dp`는 `hog=none`이고 hog 프로세스는 meta의 `hog=proc`와
`<cell>_hog.kv`에 있음; `dm`은 `hog_rounds`, `hog_gbps`도), `early_copy_n`, `early_copy_late`, `early_copy_prompt`,
`timing_file_rows`가 있고 `nic_error`, `setup_error`, `cuda_error`, `watchdog=1`이 없음(셀의 `result`는 쓰지 않음); 결과 폴더의 `b3_diag/<cell>_resp_timing.tsv`;
hold마다 새 mlx5 줄 0, 펌웨어 명령 실패 31 → 31, rain debugfs QUERY_QP 증가가 rain 응답 쪽 셀마다 약 4 200; summ_feas의 읽기 1, 2와 노드마다의 관문 줄.
새 셀 뒤 볼 것: `result`, `valid`, 채점 fence 실패 0, `early`와 `boundary` 대조 수, 경계 덮기, `query_qp_total` ≤ 19 400, `budget_stop`, `d2d_engine`,
`early_copy_late`/`early_copy_prompt`, `hog_gbps`, reach p50(노드 사이 셀보다 오른 정도), 셀 앞뒤의 compute app에 남의 프로세스가 없음(있으면 12절에 적음);
마지막에 summ_feas의 노드와 순서마다의 줄과 B3 결론 줄. 관문을 넘지 못한 노드의 새 셀, 두 번 미결인 새 셀, `FENCE_FAIL`은 사용자에게 올린다.

#### 9.15.6 정상 경로 비용: window strict와 relaxed (2026-10-11, DRAFT 단계 측정, 채점하지 않음)

**질문.** 복원 대상 window를 strict로 강제하면(9.10.8절) 장애 없는 GIN put의 지연과 대역이 얼마나 바뀌는가. 복원 계층 없이, 배포된 gpu-detect `hk` 빌드로
잰다. 강제는 이미 결정됐고(사용자), 이 측정은 그 비용을 적고 relaxed가 나중의 최적화 후보로 볼 만한지를 미리 정한 규칙으로 읽는다.

**무엇으로.**
- 라이브러리: gpu-detect가 배포한 `~/gi-bundle/gin_ts2/hk/libnccl.so.2`(md5 `2913c777aa0b05d4d566c9f7638c6a0e`; hw + 정책 hook, 복원 계층 없음; 읽기만). 그 묶음은
  바꾸지 않는다.
- 드라이버: gin-remaining의 `gin_ts2`(gpu-detect 지연 셀 `lat_*`이 쓴 것, 소스 `../gin_ts2.cu` md5 `1779db9d`)에 [feas/gin_ts2_winflags.diff](feas/gin_ts2_winflags.diff)를
  더한 빌드. 바뀐 것은 둘뿐이다(2026-10-11 검토 K5, K7): `GIN_TS_WIN_STRICT=1`이면 두 window를 `NCCL_WIN_COLL_SYMMETRIC | NCCL_WIN_STRICT_ORDERING`으로
  등록(아니면 지금처럼 `NCCL_WIN_COLL_SYMMETRIC`), 그리고 kv에 `win_flags`, `ro_env`, `ro_api`, `ro_requested`를 적음(`ro_requested`는 NCCL이 window MR에
  RO를 요청하는 조건을 그대로 셈: 변수 1이나 2(없으면 2)이고 NCCL이 여는 libibverbs에 `ibv_reg_mr_iova2@IBVERBS_1.8`이 있음, `net_ib/init.cc` 153–161,
  `ibvsymbols.cc` 125). burst 모드의 0번 스레드 반복 시간 통계는 원래 있다(`gin_ts2.cu` 1500–1504). hw 헤더(hk와 같음)로 빌드, 새 디렉터리
  `~/rs-bundle/ord/`에 배포.
- 실행기: [feas/run_ord.sh](feas/run_ord.sh). 두 rank 모두 `stdbuf -oL -eL`로 돈다(2026-10-11 바꿈: gin_ts2는 `_exit`로 끝나므로 블록 버퍼의 stdout에서 NCCL의 WARN
  줄이 사라졌다; NCCL은 `NCCL_DEBUG_FILE`만 줄 버퍼로 둠, `debug.cc` 35, 268–270). `ORD_DIAG=1`(진단 smoke)이면 NCCL INFO(`INIT,NET,REG`)를 노드의
  `~/rs-ordlogs/`(mode 700) 파일에 남기고 옮기지 않는다(관리망 주소가 들어감; 노드에서 읽음). 보내는 rank 0과 받는 rank 1을 노드 둘에 나눠, 받는 쪽 노드를 셀 이름으로 고른다(rain과 sunny 둘 다 받는 쪽으로
  잼). 포트는 `portpick.sh`, 랑데부 nonce, 프로세스마다 `timeout -s KILL`, 개인 작업 디렉터리와 `ulimit -c 0`(gpu-detect 묶음에 아무것도 남기지 않음, K12), 끄는
  일 없음(run_b3.sh와 같은 꼴). 고정한 값(K6): wait `blocking`, gap 0, `NCCL_DEBUG=WARN`(본 실행에서 INFO 줄은 관리망 주소를 담으므로 쓰지 않음, K9; RO는 위의 kv로 앎; 진단 smoke만 INFO를 노드의 파일에),
  `NCCL_IB_TIMEOUT=14`, 투명 복구 켬, QP 감시 끔(`NCCL_GIN_TS_QPWATCH_MS=0`: rain의 펌웨어 명령을 줄임, 두 팔에 같음; gpu-detect의 `lat_4k_w0`,
  `lat_256k_w0`과 같은 조건), `NCCL_IB_PCI_RELAXED_ORDERING`은 두지 않음, 큐 깊이는 NCCL 기본, burst는 block 하나 스레드 하나, K = 8(2026-10-11 바꿈, 처음 16), `GIN_TS_AGG=1`(8개를
  신호와 함께 울림). 실행기는 부른 쪽의 `NCCL_*`, `GIN_*` 변수를 모두 지우고 위 값만 넘기며 sunny 쪽에도 `umask 077`(K21). 지연 셀의 rank 0은 반복마다의
  시간을 `GIN_LAT_RAW`로 남겨 `<cell>_<tag>_lat_raw.csv.gz`(원자료, git이 따르지 않음)로 옮긴다(다시 셀 수 있게, K22). 옮기는 로그의 IPv4 주소는 그래도
  가리고 노드의 원본은 지운다. 이 실행의 프로세스가 남았는지는 실행마다의 고유 파일 이름으로만 세고(hold 앞뒤의 남은 프로세스 검사와 자기 파일 지우기도
  `/tmp/rs_ord*`를 덮음, K20), 이름 `gin_ts2`인 프로세스 수는 정보로만 적는다(gin-remaining과 gpu-detect의 드라이버도 같은 이름, K12). hold는 시작 때 두
  노드에서 실제로 쓰는 `libnccl.so.2`의 md5를 `lib_md5.txt`에 적는다(K24).

**셀(받는 쪽 노드마다).**
- `ord_lat4k_<strict|relaxed>_<rain|sunny>`: `lat` 모드, 3 000반복, 4 KiB(gpu-detect `lat_4k`와 같음). 값: rank 0의 `lat_p50_us`(스레드 하나의 put, 신호
  원자 연산, flush의 시간: flush는 신호 원자 연산의 ACK로 끝나고 PCIe에서 읽기가 앞선 쓰기를 앞지르지 못하므로 받는 쪽이 데이터 쓰기를 비우는 시간이 든다
  `[추론]`; 받는 쪽에서 보이는 때는 재지 않음, K7).
- `ord_lat256k_<...>`: `lat` 모드, 3 000반복, 256 KiB. 값: `lat_p50_us`.
- `ord_bw256k_<...>`: burst 모드, 스레드 하나, 반복마다 256 KiB put 8개(2 MiB) 뒤 신호와 flush, 12반복(window 24 MiB). 값: 대역 = K × 256 KiB / 0번 스레드 반복
  시간 p50(GB/s; K는 kv의 `burst_K`). (2026-10-11 바꿈, 첫 `ORD-sunny` hold 뒤: 처음 정한 256 KiB × 16 × 200반복은 window가 rank마다 800 MiB 둘이라 rain의
  BAR1(256 MiB; rain에서 50 MiB를 넘는 GIN window 등록은 "Bad address"로 실패한 기록이 있음, `../TRANSPARENT_S2.md`, 저장소 규칙은 64 MiB 이하
  `../../DESIGN.md`)을 넘어 등록에 실패했다. 판정 규칙은 그대로이고 이 셀의 크기와 값의 식만 바뀜. 12절)
- 정하는 폴더(실행 전 고정, K23): 한 노드의 결과는 그 노드의 `ord_<노드>[_run<k>]` 폴더 가운데 36실행이 모두 있는(meta 파일 36개) 가장 나중의 것 하나로
  읽는다. 앞의 폴더와 모자란 폴더는 정보로만 보인다. meta가 없는 kv는 세지 않고 이름을 적는다.
- 반복과 섞기(실행 전 고정): 받는 쪽 노드마다 hold 하나, 그 안에서 k = 1–6마다 세 셀을 (k−1)만큼 돌린 차례로 하고, 셀마다 strict와 relaxed를 붙여서(k가
  홀수면 strict 먼저, 짝수면 relaxed 먼저) 한다. 그래서 셀과 팔(arm)마다 6실행, 받는 쪽 노드마다 36실행, 모두 72실행이다. 시간의 흐름은 두 팔에 같이 걸린다.

**판정(실행 전 고정; 강제의 결정은 바꾸지 않는다).**
- 실행이 유효: 두 rank의 kv에 `exit=0`, rank 0의 `tx_done`이 반복 수, `nccl_error`, `cuda_error`가 없음, strict 팔의 kv에 `win_flags=0x3`, relaxed 팔에
  `0x1`. 두 rank의 `ro_requested`가 1이 아니면 relaxed 팔에서 NCCL이 RO를 요청하지 않은 것이므로 그 노드의 비교는 "비교 불가"다. `ro_requested=1`은 "RO를
  요청함"이지 NIC가 실제로 relaxed 쓰기를 냈다는 뜻이 아니다(HCA 능력 `relaxed_ordering_write`는 B3에서 1, NIC의 PCIe 장치 제어 RO 비트는 `[미확인]`; 관리자의
  읽기 전용 `lspci -vvv` 한 번이면 풀림, K5). 2026-10-11 메인 세션의 읽기 전용 sudo 읽기: 두 노드의 NIC(rain `0000:17:00.1`, sunny `0000:17:00.0`)와 GPU(두 노드
  `65:00.0`)의 DevCtl이 `RlxdOrd+`, 두 NIC의 `PCI_WR_ORDERING`이 `per_mkey(0)` `[측정]`. 그래서 이 두 노드에서는 relaxed 팔의 "RO 요청"이 "RO 허용"이기도 하다(MR의
  RO flag + NIC DevCtl RO 허용 + MR마다를 따르는 펌웨어). root complex가 그 쓰기를 실제로 바꿔 놓았는지는 여전히 볼 수 없다 `[미확인]`. (두 NIC 링크 모두
  "8GT/s (downgraded), x16", 정보.) 무효 실행은 셈에서 빼고 바꿔 하지 않는다. 한
  팔의 유효 실행이 5보다 적으면 그 셀은 "미완"이다.
- 셀마다 두 팔의 실행 값 중앙값, 차(strict − relaxed; 대역은 relaxed − strict로 써서 양수가 strict의 손해), 그 차를 relaxed 중앙값에 대한 %로, 팔마다의
  범위(최소–최대)를 적는다. "갈림": 한 팔의 모든 유효 실행이 다른 팔의 모든 유효 실행보다 크다(같은 값은 갈리지 않음: 지연 p50은 32 ns 단위로 끊김; 6 대
  6에서 차이가 없을 때 한 셀이 우연히 갈릴 확률 2/924, 약 0.2%, 여섯 셀 가운데 하나라도 그럴 확률 약 1.3%, K8). 읽기: 갈리지 않으면 "차이를 잴 수 없음", 갈리고
  strict 손해가 2% 이상이면 "strict가 X만큼 느림", 2% 미만이면 "relaxed 이득 2% 미만(X)", strict가 나으면 그렇게 적는다. 정상 확인(정보): sunny가 받는 쪽인
  relaxed 팔의 지연은 gpu-detect의 `lat_4k_w0`, `lat_256k_w0`(10.50 µs, 38.88 µs `[문서]`)와 비슷해야 한다. 결과가 갈리지 않으면 "이 두 노드에서 RO를 요청해도
  잴 만한 차이가 없음"이지 "RO가 효과 없음"을 가르지 못한다(NIC의 실제 relaxed 쓰기는 보지 않음, K5).
- relaxed의 나중 최적화(이 측정이 정하지 않음, 사용자 결정): 어느 셀이든 갈리고 strict의 손해가 relaxed 중앙값의 2% 이상이면 "능력 확인과 겹침 실험을 해 볼
  만함", 아니면 "이 두 노드에서 relaxed의 2% 이상 이득을 재지 못함"으로 적는다.
- 한계: 노드 둘(Turing, Ampere), 두 rank, 보내는 쪽 하나, 큐 깊이 기본값. 셀마다 두 rank의 MR(보내는 쪽 읽기, 받는 쪽 쓰기)을 함께 바꾸므로 노드마다의 결과는
  그 쌍의 효과다. 복원 배치의 같은 노드 GIN 쌍(NIC 루프백, lsaSize 1)은 재지 않는다(K10). 강제는 hold 프로세스의 모든 GDAKI window에 걸리므로 이 비용은 무장하지 않는
  communicator에도 든다(9.10.8절).

**충돌 표(이 측정).**

| 자원 | 이 측정 | 겹치는 것 | 처리 |
|---|---|---|---|
| 라이브러리 | gpu-detect의 `~/gi-bundle/gin_ts2/hk`를 읽기만(`LD_LIBRARY_PATH`) | gpu-detect(COMPLETE, master), 그 묶음의 다른 사용 | 쓰지 않음. 배포 확인이 그 묶음의 앞뒤 md5를 봄 |
| 노드의 파일 | 새 `~/rs-bundle/ord/gin_ts2` 하나 | `~/rs-bundle`의 다른 파일, 다른 묶음 | 배포는 새 디렉터리만, 앞뒤 md5 |
| 결과 | 새 폴더 `results/20261011_ordering/`(hold마다 `ord_<노드>/`, 다시 하면 `ord_<노드>_run<k>/`; 진단 smoke는 `ord_smoke_<노드>/`, 판정에 쓰지 않음) | B3의 `results/20261009_feasibility/` | 섞지 않음. 요약은 따로(`feas/summ_ord.py`, `SUMMARY_ORD.txt`) |
| 클러스터 | hold 둘(`ORD-rain`, `ORD-sunny`; 첫 hold가 멈춘 뒤 smoke `ORDSMOKE-rain`, `ORDSMOKE-sunny` 각 2실행과 다시 하는 `ORD-sunny-2`), `cluster_run.sh` 안, 본 hold마다 36실행 약 5–8분 | 다른 사용자의 작업 | 잠금과 링크 한가 확인. hold 시간 840 s 보호(`fits`) |
| NIC 펌웨어 명령 | 감시를 끄므로 QUERY_QP 고리 없음. 실행마다 QP, MR 만들기와 지우기 | rain의 새는 명령 slot | hold 앞뒤 rain debugfs 셈. 실행에 오류가 나면 STOP 파일(B3과 같은 규칙)로 남은 실행을 멈춤 |
| GPU 메모리 | 대역 셀은 rank마다 window 24 MiB 둘(2026-10-11 바꿈, 처음 계획은 800 MiB 둘이라 rain의 BAR1을 넘음) | 다른 사용자의 GPU 작업 | 실행 앞뒤 compute app 기록 |
| GPU BAR1 | GPUDirect 등록이 BAR1을 씀(rain 256 MiB, sunny `[미확인]`). 한 rank의 window 48 MiB와 NCCL 안의 등록 | 다른 사용자의 GPUDirect 작업 | hold 앞뒤 snap에 두 노드의 BAR1 Used/Free와 rain의 NVRM 매핑 실패 줄 수(읽기 전용). 본 hold 전 rain BAR1 Free가 128 MiB 이상일 때만 함 |
| 링크 | 실행마다 약 0.01–0.79 GB, 본 hold 둘 모두 약 20 GB(2026-10-11 대역 셀을 줄인 뒤 다시 셈) | 다른 사용자의 RDMA | `cluster_run.sh` |
| 포트와 랑데부 | 29000–30999에서 고름, nonce | 같은 범위의 다른 실험 | `portpick.sh` |
| 프로세스 | `gin_ts2`를 `timeout -s KILL`로 묶음. 남은 프로세스는 실행마다의 고유 파일 이름과 `/tmp/rs_ord`로 셈(남으면 STOP_left, 그 뒤 실행은 건너뜀), 이름 `gin_ts2`의 수는 정보로만 | 다른 사용자와 다른 실험의 `gin_ts2` | 이름으로 끄지도 세지도 않음(K12, K20) |
| 관리망 주소 | 본 실행은 `NCCL_DEBUG=WARN`이라 INFO의 주소 줄이 없음. 진단 smoke의 INFO 파일은 노드의 `~/rs-ordlogs/`(700, 파일 600)에만 남고 옮기지 않음(만들 수 없으면 실행 안 함). 랑데부 주소는 meta와 stderr에 적지 않음 | 공개 저장소와 release | 옮길 때 IPv4를 그래도 가림, 노드의 원본은 실행기가 지움(umask 077), smoke 판단 뒤 `~/rs-ordlogs/`를 두 노드에서 지움, release는 `tools/pack_release.py`의 검사를 거침 |
| 복원 계층과 정책 | 쓰지 않음(`NCCL_GIN_FAULT_POLICY` 없음, 강제 없음) | 9.10.8절의 강제 | strict는 드라이버의 flag로만 |

**2026-10-11 첫 hold 뒤: 진단, 고침, STOP_nic 풀기.** 첫 `ORD-sunny` hold(17:23:14 잠금, hold 79 s, rc 0, 새 mlx5 줄 0, 펌웨어 명령 실패 31 → 31, `cmd_err` 2 → 2,
`lib_md5.txt` 두 노드 `2913c777`)는 k1의 지연 셀 넷을 마쳤고(4 KiB strict, relaxed 둘 다 `lat_p50_us` 10.50, 256 KiB 둘 다 38.88: gpu-detect의 `w0` 값과 같음) `[측정]`,
`ord_bw256k_strict_sunny_k1`에서 rank 0(rain, 보냄)이 첫 `ncclCommWindowRegister`(dSend, `gin_ts2.cu` 패치 뒤 1022행)에서 "unhandled system error"(exit 2),
rank 1이 watchdog(exit 7)으로 끝나 실행기가 STOP_nic를 쓰고 남은 31실행을 건너뛰었다 `[측정]`. 진단 `[소스, 추론]`: (1) 그 셀의 window는 `bytes × iters × P × K` =
256 KiB × 200 × 1 × 16 = 800 MiB씩 둘(지연 셀은 슬롯을 다시 써서 4 KiB와 256 KiB); (2) "unhandled system error"는 `ncclSystemError`이고, 이 길에서 그것을 내는
것은 ibverbs 등록 실패(`wrap_ibv_reg_mr_iova2`의 `IBV_PTR_CHECK_ERRNO`, `ibvwrap.cc` 38–45, 211–219, WARN "Call to ibv_reg_mr_iova2 failed with error ...")나
GIN 등록부의 NULL(`gin_host.cc` 573–576)이다; (3) GDAKI의 strict 길은 relaxed와 access의 RO 비트 하나만 다르고 같은 dmabuf와 `ibv_reg_mr_iova2` 길을 탄다(hw 188–199)
`[소스]`; (4) rain의 BAR1은 256 MiB이고(blind 2026-10-09 `nvidia-smi -q -d MEMORY` `[측정: 그 실험]`) GIN window가 50 MiB를 넘으면 "Bad address"로 등록에 실패한
기록이 있다(`../TRANSPARENT_S2.md`). 그래서 실패는 strict가 아니라 window 크기 때문으로 본다 `[추론]`(relaxed의 같은 크기는 돌지 않아 직접 견주지 못함). 뒷받침(코드 검토 O10): rank 0은 시작
1.83 s 뒤에 실패했고(bootstrap 시한보다 훨씬 이름), sunny의 rank 1은 같은 0x3, 800 MiB에서 `nccl_error` 없이 watchdog으로 끝났다(sunny에서는 등록이 되었음
`[추론]`) `[측정]`; gin-remaining의 `../scripts/ts2/batch.sh`(82, 109–110)는 rain에서 window 4 × 16 MiB는 되고 4 × 30 MiB는 NVRM "can't alloc VA space"로
실패했다고 적는다; `ncclCommRegister`는 regCache에 적기만 하고 MR을 만들지 않는다(`register.cc` 26–75, 150–158). 반증 조건: 두 노드의 BAR1을 읽어 sunny도
256 MiB이면 sunny에서 같은 등록이 된 것을 설명하지 못하므로 smoke 전에 올린다. 2026-10-11 메인 세션의 읽기 전용 읽기: rain BAR1 Total 256 MiB(Used 5, Free 251),
sunny 16 384 MiB(Used 21, Free 16 363); rain `dmesg`에 첫 hold 시각(17:23–17:25, `dmesg -T` 시계는 어긋날 수 있음; 처음 보인 것 17:25:30)의
`NVRM: dmaAllocMapping_GM107: can't alloc VA space for mapping.` 19줄(버퍼 전체 913줄) `[측정]`. 그래서 진단은 `[측정]`이다: rain의 BAR1 VA가 모자랐고, sunny의
16 GiB BAR1은 sunny에서 같은 window가 등록된 것을 설명한다. 풀기 조건 1–4가 맞아 메인 세션이 STOP_nic와 `skipped.txt`를 같은 시각 꼬리표로 옮김. 또 첫 hold의 정상 지연 실행 넷의 로그도 모두 4 KiB 블록에서 잘려 있었다
(같은 버퍼 까닭). WARN
줄이 로그에 없던 것은 stdout이 블록 버퍼였고 gin_ts2가 `_exit`로 끝났기 때문이다 `[소스]`. 고침(판정 규칙은 그대로): 대역 셀을 256 KiB × 8 × 12반복(window
24 MiB)으로, 두 rank를 `stdbuf -oL -eL`로, 진단 smoke hold `ORDSMOKE-<노드>`(대역 셀 strict와 relaxed 한 번씩, NCCL INFO는 노드에 남김)를 더함. `ord_sunny/`(5실행)는
정하는 폴더 규칙대로 정보로만 남고, 다시 하는 hold는 `ord_sunny_run2/`에 36실행을 쓴다.

이 STOP_nic를 푸는 단계: 다음이 모두 참일 때 `STOP_nic.cleared-<날짜시각>`으로, 같은 꼬리표로 `skipped.txt`도 `skipped.txt.cleared-<날짜시각>`으로 옮기고
12절에 적는다(그래야 다음 hold의 "skipped.txt 없음" 확인이 쓰임, O1). (1) 그 hold의 오류는 `ord_bw256k_strict_sunny_k1` 하나이고 rank 0의
`nccl_error=unhandled system error`(첫 window 등록)와 그 결과인 rank 1의 watchdog뿐, 다른 실행의 kv에 오류 키가 없음; (2) 원인 진단과 고침이 12절에 있고 바뀐 스크립트가
독립 검토를 받음; (3) 새 mlx5 줄 0, rain 펌웨어 명령 실패와 `cmd_err` 그대로, 남은 프로세스 0(`left=0`, STOP_left 없음); (4) 두 노드의 BAR1 크기와 Free를 읽기 전용으로
읽어 12절에 적고 rain의 Free가 128 MiB 이상, rain의 `dmesg`에서 첫 hold 시각(17:23–17:25)의 NVRM 매핑 실패 줄(`dmaAllocMapping`, `alloc VA`)의 수를 읽기 전용으로
세어 12절에 적음(있으면 진단이 `[측정]`이 됨, O3, O4). sunny의 BAR1이 256 MiB이면 위의 반증 조건대로 smoke 전에 올림. 그 뒤 smoke hold가 오류 없이 끝나야(두 노드, strict와 relaxed 모두 `exit=0`, 대역 값이 있음) 본 hold를 한다. smoke는 relaxed를 먼저 한다(strict가 다시 실패해도 같은
크기의 relaxed 결과가 남음). smoke에서 다시 등록 오류가 나면 노드의 `~/rs-ordlogs/` 파일에서 WARN 줄만(주소를 가려) 읽어 올린다. smoke를 판단한 뒤에는
두 노드의 `~/rs-ordlogs/`를 지운다(관리망 주소가 든 파일, O7). 한계(O11): 대역 셀은 반복 12개의 p50이고 flush 하나당 2 MiB라 신호와 flush의 고정 비용 몫이
커져, 그 셀에서 "갈리지 않음"의 무게가 처음 계획보다 작다.

**명령(메인 세션).** 드라이버 `gin_ts2` ord(빌드됨, 실행 안 함; md5 `64418f216c68bf1f518b25737a7e5c9d`, 컴파일 때 소스 `gin_ts2.cu` `1779db9d` +
`gin_ts2_winflags.diff` `fb9d2d8d` → `fa30bb70`). 변수 `F`, `CR`, `SCR`는 9.15.5와 같다. sunny가 받는 hold를 먼저 한다(정상 확인을 gpu-detect의 값과 견줌).

```
R2=~/rdma-error-wt/gin-restore/harness/gpu-initiated/gin_recovery/restore/results/20261011_ordering
ls -d ~/rs-bundle/ord; ssh -n "$SUNNY_SSH" 'ls -d ~/rs-bundle/ord'      # 둘 다 "No such file"이어야 함
WANT_ORD=64418f216c68bf1f518b25737a7e5c9d bash $F/deploy_feas.sh $SCR/agent_restore/deploy_check_ord.txt ord   # 약 30 s
test -s $SCR/agent_restore/deploy_check_ord.txt && echo written
grep -E "MISMATCH|CHANGED|not found" $SCR/agent_restore/deploy_check_ord.txt   # 아무 줄도 없어야 함
mkdir -p $R2
# (2026-10-11 17:22–17:25에 이미 함: 배포와 첫 ORD-sunny. 아래 두 hold 줄은 다시 돌리지 않는다: 같은 hold 이름은 첫 hold의 snap, mlx5, fwcmd, hold 출력을 덮음)
# bash $CR -w 10800 -t rs-ORD-sunny -- timeout -s KILL 880 bash $F/hold_feas.sh $R2 ORD-sunny > $R2/hold_ORD-sunny.out 2>&1
# bash $CR -w 10800 -t rs-ORD-rain -- timeout -s KILL 880 bash $F/hold_feas.sh $R2 ORD-rain > $R2/hold_ORD-rain.out 2>&1
# 2026-10-11 첫 hold가 멈춘 뒤(위 진단): 스크립트만 바뀜, 드라이버와 배포는 그대로(다시 배포하지 않음)
nvidia-smi -q -d MEMORY | sed -n '/BAR1/,/Free/p'; ssh -n "$SUNNY_SSH" "nvidia-smi -q -d MEMORY | sed -n '/BAR1/,/Free/p'"   # 읽기만, 12절에 적음
sudo -n dmesg -T | grep -iE 'NVRM.*(dmaAllocMapping|alloc VA)' | grep -c '17:2[345]'     # 읽기만: 첫 hold 때의 NVRM 매핑 실패 줄 수
TS=$(date +%Y%m%d-%H%M%S); mv $R2/STOP_nic $R2/STOP_nic.cleared-$TS; mv $R2/skipped.txt $R2/skipped.txt.cleared-$TS   # 위 풀기 단계 1–4를 확인한 뒤
bash $CR -w 10800 -t rs-ORDSMOKE-rain -- timeout -s KILL 880 bash $F/hold_feas.sh $R2 ORDSMOKE-rain > $R2/hold_ORDSMOKE-rain.out 2>&1      # 2실행, 약 1분
bash $CR -w 10800 -t rs-ORDSMOKE-sunny -- timeout -s KILL 880 bash $F/hold_feas.sh $R2 ORDSMOKE-sunny > $R2/hold_ORDSMOKE-sunny.out 2>&1    # 2실행, 약 1분
# 두 smoke 모두 오류 없이(rc_r0=0 rc_r1=0 left=0, kv exit=0, lat_p50_us 있음) 끝났을 때만 본 hold(sunny는 ord_sunny_run2/에 새로 36실행)
bash $CR -w 10800 -t rs-ORD-sunny2 -- timeout -s KILL 880 bash $F/hold_feas.sh $R2 ORD-sunny-2 > $R2/hold_ORD-sunny-2.out 2>&1
bash $CR -w 10800 -t rs-ORD-rain -- timeout -s KILL 880 bash $F/hold_feas.sh $R2 ORD-rain > $R2/hold_ORD-rain.out 2>&1
python3 $F/summ_ord.py $R2
# smoke를 판단한 뒤(필요하면 WARN 줄만 주소를 가려 옮긴 뒤) 두 노드의 진단 파일을 지움
rm -rf ~/rs-ordlogs; ssh -n "$SUNNY_SSH" 'rm -rf $HOME/rs-ordlogs'
```

볼 것: 배포 확인에 rain == sunny, source == deployed, `ord: libnccl.so.2 => .../gi-bundle/gin_ts2/hk/...`, 그 밖의 파일 그대로(`~/gi-bundle` 포함); hold마다
`lib_md5.txt`의 두 노드 md5가 `2913c777aa0b05d4d566c9f7638c6a0e`, 새 mlx5 줄 0, 펌웨어 명령 실패 31 → 31, STOP 파일 없음, `skipped.txt` 없음; 실행마다 meta의 `rc_r0=0 rc_r1=0 left=0`, kv의 `win_flags`(strict `0x3`, relaxed
`0x1`)와 `ro_requested=1`; `SUMMARY_ORD.txt`의 셀마다 n(6, 6), 갈림, 읽기, 노드마다의 마지막 줄. sunny가 받는 relaxed 지연이 10.50, 38.88 µs 안팎에서 크게
벗어나면 결과를 해석하기 전에 올린다. 실행이 오류로 멈추면(STOP 파일) 9.15.5의 STOP 규칙대로 올린다.

**결과(2026-10-11).** `[측정: results/20261011_ordering/ord_rain/, ord_sunny_run2/(정하는 폴더, 각 36실행), ord_smoke_*/; 이 에이전트가 원자료에서 다시 셈: 지연
셀 48실행의 p50을 반복마다의 원자료 `lat_raw.csv.gz`에서 다시 구해 kv와 모두 같음, summ_ord.py로 표 다시 만듦]`

| 받는 쪽 노드 | 셀 | strict 중앙값(범위) | relaxed 중앙값(범위) | 차(strict 손해 +) | 갈림 | 읽기 |
|---|---|---|---|---|---|---|
| rain | 4 KiB 지연 | 11.260 µs(11.260–11.260) | 11.260 µs(11.260–11.260) | 0 | 아니오 | 차이를 잴 수 없음 |
| rain | 256 KiB 지연 | 39.940 µs(38.910–40.960) | 39.940 µs(38.910–39.940) | 0 | 아니오 | 차이를 잴 수 없음 |
| rain | 대역(256 KiB × 8) | 5.491 GB/s(5.476–5.491) | 5.491 GB/s(5.476–5.491) | 0 | 아니오 | 차이를 잴 수 없음 |
| sunny | 4 KiB 지연 | 10.500 µs(10.460–10.500) | 10.500 µs(10.500–10.530) | 0 | 아니오 | 차이를 잴 수 없음 |
| sunny | 256 KiB 지연 | 38.880 µs(38.880–38.880) | 38.880 µs(38.880–38.880) | 0 | 아니오 | 차이를 잴 수 없음 |
| sunny | 대역(256 KiB × 8) | 6.492 GB/s(6.482–6.507) | 6.490 GB/s(6.480–6.507) | −0.002(−0.03%) | 아니오 | 차이를 잴 수 없음 |

- n: 셀과 팔마다 6실행, 모두 유효(무효 0). 노드 줄은 두 노드 모두 "relaxed의 2% 이상 이득을 재지 못함"이다(relaxed 최적화는 사용자 결정으로 남고 이 측정은
  아무것도 정하지 않음). sunny가 받는 relaxed 지연은 gpu-detect의 `w0` 값(10.50, 38.88 µs `[문서]`)과 같다.
- 첫 `ord_sunny/`(5실행, 대역 셀 등록 실패)는 정보로만 남는다. 진단 smoke 넷(두 노드 × 두 팔, 반복 12의 p50: rain 381.95 µs 둘 다, sunny relaxed 322.82,
  strict 323.36 µs)은 판정에 쓰지 않았고, 노드의 진단 파일은 smoke 뒤 지웠다(메인 세션; 이 에이전트가 rain에서 없음을 확인).
- 한계: 대역 셀은 반복 12개의 p50이고 flush 하나당 2 MiB라 "갈리지 않음"의 무게가 처음 계획보다 작다. relaxed 팔은 NCCL이 RO를 요청했고(`ro_requested=1`) 두 노드의
  NIC 쪽에서 허용도 됐다(DevCtl `RlxdOrd+`, `PCI_WR_ORDERING` `per_mkey`, 12절) `[측정]`. 그러나 root complex가 그 쓰기를 실제로 바꿔 놓았는지는 보지 못한다
  `[미확인]`. 그래서 결과는 "이 두 노드, 이 크기에서 RO를 요청하고 허용해도 지연과 대역에 잴 만한 차이가 없음"이고, "RO가 효과 없음"을 뜻하지 않는다. 같은
  노드 GIN 쌍, 보내는 쪽 여럿, 큰 대역(BAR1이 막음)은 재지 않았다.
- 9.10.8절의 strict 강제가 이 두 노드의 정상 경로에 잴 만한 비용을 더하지 않는다는 근거가 된다 `[측정, 위 한계 안에서]`.

## 10. 완료 조건과 QA 기준

- [ ] 9.11.12절의 막는 문제가 풀렸고, 정책 설계의 독립 검토(9.11.13절)가 남은 충돌이 없다고 했다.
- [ ] 9.9절 계층을 구현하고 독립 리뷰를 받았다.
- [ ] 모든 셀이 계획한 n만큼 실행됐다(제외와 실패를 따로 센 표 포함).
- [ ] 예측마다 판정과 놓친 시행 목록이 있다.
- [ ] 핵심 수치를 원자료에서 다시 계산했다(다른 에이전트).
- [ ] smoke, pilot, 제외 시행이 결과에 섞이지 않았다.
- [ ] 원자료를 Release에 올리고 DATA.md에 적었다.

## 11. 작업 체크리스트

- [x] 앞 실험의 측정 다시 셈(1절), `hr` 소스와 gpu-detect 초안 읽기
- [x] 설계 초안(9.1–9.8절), hook 목록(9.9절)
- [x] 감지와 반응을 나눈 정책 설계와 통합 상호작용 표(9.10–9.11절)
- [x] 독립 충돌 검토 둘(EXPERIMENT.md 초안 표, 9.10–9.11절)과 반영. 검토 2의 마지막 판정: B1–B4 밖에 풀리지 않은 충돌 없음
- [x] B4 결정: (나)(2026-10-09, 사용자)
- [x] (나)와 `pe.lostAfterCommit` 계약의 독립 충돌 검토(9.11.13절 검토 3과 재확인: 풀리지 않은 충돌 없음)
- [ ] 사용자의 설계 승인(그 전에는 복원 계층의 구현과 빌드 없음. B1–B3 실행 가능성 시험은 2026-10-09 허용)
- [ ] gpu-detect 계층에 정책 hook G1–G9(9.11.10절)
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
- [x] 그 설계의 독립 검토(D1–D15)와 반영
- [x] `b3v4` 빌드됨
- [x] `b3v4`와 스크립트의 독립 검토(V1–V7)와 반영
- [x] 진단(`b3_diag/`)과 새 경합 셀 넷(`b3_m_*`) 실행(2026-10-11: 넷 모두 통과, B3 drain 확인 통과)
- [x] B3의 사용자 결정(다시): 2026-10-11, 복원 대상 window는 런타임이 strict를 강제, 못 하면 명시적 등록 오류(9.10.8절)
- [x] strict 강제의 범위와 등록 flag 충돌 표(9.10.8절)
- [x] 그 충돌 표의 독립 검토(K1–K12)와 반영
- [x] 반영의 독립 재확인(열린 충돌 없음까지; 2026-10-11 마지막 판정: 열린 충돌 없음, 남은 설계 선택 넷 대기)
- [x] 남은 설계 선택 넷의 사용자 결정(2026-10-11: 복원을 켤 수 없으면 `ncclGinRestoreResume`이 이유와 함께 오류, 모든 rank가 같은 오류)
- [x] 정상 경로의 strict와 relaxed 비교(9.15.6): 설계와 빌드
- [x] 그 비교의 실행과 기록(2026-10-11: 두 노드, 셀 셋 모두 차이를 잴 수 없음, 9.15.6 결과)
- [x] 복원 실험의 질문, 가설, 예측(판정식), 셀, 반복 수, 제외와 중단 기준의 초안(DRAFT, 2026-10-11; pilot 뒤 고정)
- [x] 구현 계획(작업 묶음 열, 9.14절)
- [ ] 체크포인트와 복원 경로 구현, pilot, 사전 등록(태그), 본 실행
- [x] 작업 묶음 1(9.14절): 새 빌드 트리와 [impl/build_rs.sh](impl/build_rs.sh), 정책 도우미, strict 강제, 설정 기록 넓히기, 정하는 자료. 충돌 확인, 빌드됨(`rs_p1`, `rsp_p1`), CPU 단위 시험함, 독립 검토와 재확인(막는 문제 없음), [impl/rs_layer.diff](impl/rs_layer.diff)와 다시 적용 확인(2026-10-11)
- [x] 작업 묶음 2(9.14절): 공개 API와 `ncclGinRestoreResume`의 검사. 충돌 확인에서 멈춤(2026-10-11), 사용자 결정(2026-10-12, Resume은 모든 rank가 부르는 모음), 새 설계 아래 충돌 확인, 빌드됨(`rs_p2d`, `rsp_p2d`), CPU 단위 시험함, 독립 검토와 재확인(막는 문제 없음), diff와 다시 적용 확인(2026-10-12)
- [x] 작업 묶음 3(9.14절): 측 표, GPU 문맥 판, 복원 버퍼의 루프백 MR, 자원 window. 충돌 확인에서 멈춤, 사용자 결정(2026-10-12, 판은 그대로 두고 구조체 끝에 포인터), 새 결정 아래 충돌 확인, 빌드됨(`rs_p3b`, `rsp_p3b`, 장치 객체 모두), CPU 단위 시험함, fail-fast 장치 동작의 기계어 비교(sm_75, sm_86), 독립 검토와 재확인(막는 문제 없음), diff와 다시 적용 확인(2026-10-12)
- [ ] 작업 묶음 4(장치 보내기 길): 메인 세션이 보고한 뒤 시작
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
| 2026-10-09 | 독립 충돌 검토 1(읽기 전용 에이전트)에 이 문서의 초안 표를 맡김 | 9.11.13절 |
| 2026-10-09 | gpu-detect `hw` 계층이 빌드됨(실행, 병합 전; diff md5 `be0ea9ed`, libnccl `efc48ca1`) → 줄 번호를 hr/hw 둘로, 표에 hw 행(QP 감시, `DEGRADED_ROUNDS`, 감시의 펌웨어 부하) 더함 | 9.11절 |
| 2026-10-09 | 사용자 결정: 충돌이 남은 동안 구현 없음, 감지와 반응을 나눈 통합 설계 문서를 먼저. 시제품 초안(빌드, 실행 안 함)을 스크래치로 옮기고 멈춤. 정책 설계 문서 `DESIGN_POLICY.md` 작성(2026-10-11에 9.10–9.11절로 합침) | 9.13절 |
| 2026-10-09 | 검토 1 결과(F1–F28) 반영. 검토 2(이 문서 대상, 읽기 전용 에이전트): 첫 검토 V1–V20, 재확인 N1–N5, P1–P7, Q1–Q5, R1을 차례로 반영. 마지막 판정(커밋 `0af9190e`): 막는 문제 B1–B4 밖에 풀리지 않은 충돌 없음 | 9.11.13절, 커밋 `fb27b091`–`0af9190e` |
| 2026-10-09 | 사용자 결정 둘. (1) B4는 (나): 게이트 뒤의 키 다시 읽기는 hold 정책의 communicator에서만, fail-fast는 측 표 포인터의 분기 하나만 더함(4 KiB, 256 KiB 지연은 계층을 만들 때 잼). (2) B1(예비 프로세스의 초기화 재생), B2(GPU를 나눠 쓰는 rank의 LSA 팀 크기), B3(relaxed ordering window MR에서 체크포인트 drain이 보이는가)의 실행 가능성 시험을 한다. 복원 계층은 여전히 구현하지 않고, 스크래치의 시제품 초안도 빌드하지 않는다 | 9.1, 9.6절, 9.9절 DV3, 9.11.12절 B4 |
| 2026-10-09 | 병렬로 도는 gpu-detect 고침과의 계약을 설계에 넣음(메인 세션이 정함): 응답 쪽 Commit 뒤 게시 전에 소켓을 잃은 길(hw 5285–5292, 5298–5303)에서 거절 바로 전에 `pe.lostAfterCommit = true`, 죽음 판정이면 그 거절은 PeerDead/`GDAKI_UA_PEER_DEAD`(degraded 예약), 아니면 지금과 같음. 복원 설계는 이 창을 계속 붙잡지 않는다: G2의 강한 증거 검사가 그 표시가 선 거절을 뺀다(NOHOLD), REJOIN이 표시를 지운다 | 9.3절 8단계, 9.10.5절, 9.10.7절, 9.11.1절 D4, 9.11.2절 R3, 9.11.10절 끝 |
| 2026-10-09 | 검토 3(읽기 전용 에이전트): 결정 (나)와 `lostAfterCommit` 계약 대상. 중간 W1–W3(측 표 포인터를 쓰는 때와 무장 조건, 포인터의 두 뜻 → QP마다 "로그 켬" 낱말, get 키도 다시 읽음), 낮음과 메모 W4–W11 반영. 재확인: W1–W11 풀림, 낮음 X1–X5 반영(표시를 세우는 자리는 "잃은 자리에서, `gdakiTsSocketLost` 전" 하나로; gpu-detect에 넘길 것). 판정: 풀리지 않은 충돌 없음 | 9.11.13절 검토 3, 커밋 `daa63c69`, `6b33627e`와 이 커밋 |
| 2026-10-09 | B2의 기존 원자료 확인: gin-multirank 본 실행 보관본(Release `data-20261009`의 `harness__gpu-initiated__gin_recovery__multirank__results__20261009.tar.xz`, sha256 앞 12자 `3c22ffd4d260`, 세션 스크래치에 풂)의 4-rank 로그와 kv에 LSA 값이 없음. NCCL도 이 경우 값을 찍지 않음(`dev_runtime.cc` 140, 1742) | 9.15.2절 `[측정, 소스]` |
| 2026-10-09 | B1–B3 실행 가능성 시험의 설계와 충돌 표, 판정 기준을 실행 전에 적음. B1 빌드 트리를 hw 트리에서 복사(`agent_restore/b1/`, 복사본의 hw 커밋 `c7d7f7f`, diff md5 `be0ea9ed` 확인; hw 트리는 고치지 않음) | 9.15절 |
| 2026-10-09 | B1–B3 시험 설계의 독립 검토(읽기 전용 에이전트 둘). B3 "고치면 답함": 꼬리의 신호 원자 연산이 그 자체로 drain을 보장해 시험을 무력하게 함(T3-1, 높음), READ 대상이 설계와 다름(T3-2, 높음), RO가 실제로 켜졌는지의 증거, 경계 대조와 경계 덮기, `cuFlushGPUDirectRDMAWrites` 길, cuMem과 GPU 원본, 경합, QUERY_QP 간격과 상한, 노드별 통계(T3-3–T3-12). B1 "고치면 답함": host RMA proxy가 hook 밖에서 상대마다 IB 연결을 맺음(T1-1, 높음), hook의 셈으로는 hook 밖 연결을 못 봄 → strace(T1-2), 자리별 가면 비교, 판정 항목 추가, 음성 대조, 주소 처리(T1-3–T1-11). B2 "답함", lsaSize 1이어도 남는 매핑 길을 무장 조건으로(T2-3). 모두 9.15절, 9.4절 3단계, 9.7절 6번, 9.10.4절, 9.11.5절 A3, 9.11.1절 D3에 반영하고 판정 기준을 실행 전에 다시 고정함. B3 프로그램은 검토가 도는 동안 초안을 쓰기 시작했고, 반영 뒤에만 빌드함 | 9.15절 |
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
| 2026-10-09 | gpu-detect의 `hk` 빌드(`~/rdma-error-wt/gpu-detect/harness/gpu-detect/hk_layer.diff`, 사전 등록 태그 `prereg/gpu-detect-v1`)를 읽어 계약 확인(읽기만): `gdakiTsDeclineAfterCommit`가 맨 처음에 `pe.lostAfterCommit = true`를 세우고(어느 돌아가기, `gdakiTsSocketLost`보다 먼저), 두 자리(ACK 보내기 실패, DONE 기다림 중 잃음)가 모두 이 함수를 부른다. ACK 실패 길은 죽음 판정을 하지 않고 errno 이름을 `closeCause`에 넣는다(hk 검토 지적 1로 받기 쪽 peek을 뺌). DONE 길은 `gdakiTsCauseLiveness`가 죽음이면 `gdakiTsSocketLost` 뒤 PeerDead, `GDAKI_UA_PEER_DEAD`로 거절. 표시는 `gdakiTsInstall`에서 지운다(REJOIN이 설치하는 자리). 그래서 검토 3의 W10/X5와 W11을 hk가 채운다 `[소스: hk_layer.diff]` | 9.10.5절 |
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
| 2026-10-09 | B3 상태(이 에이전트가 원자료에서 다시 셈, `summ_feas.py`): rain `ro`, `so` 열림(경합 셀이 두 번 다 미결), sunny `ro`, `so` 통과(채점 4 800씩, 상한 0.0625%), B3 결론 "열림". 본 셀 폴더의 모든 실행에서 채점 fence 실패 0/23 707(유효 여부와 무관한 합), 모든 셀의 `nofence`도 실패 0. 메인 세션의 판단(rain 경합에서는 대조가 힘을 잃어 이 방법으로 유효해질 수 없음, sunny 경합은 약 10%)과 함께 사용자에게 올림: B3은 사용자 결정 대기. 대조가 0인 까닭의 추론과 미확인은 9.15.3 결과. `summ_feas.py` 고침: 앞 실행 목록에서 오류 출구를 "error ... (no verdict)"로 적음(전의 "FAIL"은 `nicFail`이 쓰는 `result=FAIL`이지 fence 실패가 아님), 모든 실행의 합 줄을 더함, 실패율 상한은 통과한 묶음에만 적음. 이 고침으로 `SUMMARY.txt`를 다시 만듦(23:39, 원자료는 그대로) | 9.15.3, 9.11.12절 B3, `feas/summ_feas.py` |
| 2026-10-11 | 사용자 결정(메인 세션이 전함): "4셀만 제대로 확인 후 다시 결정해보자". 경합 셀 넷만 다시 확인하고 그 뒤 B3을 다시 정함; 그때까지 B3은 열림, 무장 조건 "window는 strict" 유지, `x`, `s` 셀은 다시 하지 않음, 판정 기준 그대로. 옛 경합 셀(`b3_h_*`)과 그 실행은 그대로 두고 "다른 프로세스 hog, rain에서 대조의 힘 없음"으로 적고 묶음에서 뺌. 설계(빌드 전): 진단(판정 없음, `b3_diag/`, 노드마다 hog 없음, 다른 프로세스 hog, 프로세스 안 hog 각 320반복, 복사 시작 시각을 event로 잼)과 새 경합 셀 `b3_m_*`(응답 프로세스 안 낮은 우선순위 stream의 hog, 사본 stream은 높은 우선순위), 미리 정한 진단의 읽기, 노드마다의 관문, 다시 하기 규칙, 충돌 표 | 9.15.3 |
| 2026-10-11 | 묶음 규칙의 바꿈(사용자 결정, 위 행): B3의 노드와 순서 하나는 `x`, `s`, `h` 대신 `x`, `s`, `m`(프로세스 안 hog의 새 경합 셀)의 마지막 실행으로 묶는다. 까닭: 옛 `h`(다른 프로세스의 hog)는 rain에서 대조가 한 번도 잡히지 않아 그 노드에서 유효해질 수 없었고, 사용자가 경합 셀만 제대로 다시 확인하기로 함. 범위: B3의 묶음과 결론 줄(`summ_feas.py`)만. 셀의 유효와 통과 기준, 예산과 상한, `x`, `s`의 결과는 그대로. 옛 `h`의 실행과 2026-10-09 결과 문단은 그대로 두고(그때의 `SUMMARY.txt`는 2026-10-11 13:56에 덮였고 같은 내용을 `SUMMARY_20261009.txt`로 다시 만듦, 아래 행), 옛 sunny `h`의 통과는 새 판정을 살리지도 깎지도 않는다 | 9.15.3 |
| 2026-10-11 | 설계의 독립 검토(읽기 전용 에이전트, 커밋 `09f28e1b` 대상, 빌드 전): 판정 "design: not ready: D1". 막는 것 D1(재는 자리와 적는 값이 정해지지 않음: 복사 뒤 다음 CUDA 호출인 페이지 가능한 8바이트 D2H가 호스트를 붙잡아 시작 어림이 늦어질 수 있음). 중간: D2(D2D 복사의 엔진을 모름), D3(관문이 NIC 쪽 경합을 보지 않음), D4(묶음 바꿈을 규칙 바꿈으로 적기, 옛 셀은 사실로), D5(결과 폴더), D6(`.gitignore`가 `*.csv`를 따름), D7(`run_b3.sh`), D8(hold, 배포, 기본 바이너리, 노드마다 hold, hold 이름), D9(hog의 kv 키와 합류), D10(읽기를 조이기: 구간, 90%, 반복마다의 연결, `dm` 읽기, 기준 시각, 관문만 정함, boundary 분모), D11(Turing에서 1 024-thread 탐침이 굶을 수 있음). 낮음: D12, D13, D14. 정보: D15(펌웨어 명령, 링크, 프로세스 충돌 없음). 반영(이 커밋): 뒤 event를 넣은 바로 다음 다른 CUDA 호출 없이 돌며 묻고 끝의 구간과 시작의 구간을 적음(D1), 셀마다 엔진 확인(D2), 관문 (3) reach 오름(D3), 위 행(D4), 결과 폴더 `20261009_feasibility/`(D5), 시각 파일 `.tsv`(D6), 실행기의 셀 문법, 응답 쪽에만 `RS_HOG`, 다른 역할은 거절, `hog=` meta(D7), hold `B3diag-<node>`, `B3m-<cell>`, 꼬리표, `B3BIN`을 hold가 넘김, 배포 `b3v4`(D8), `hog_*` 키만, 결과 줄 전에 합류, 오류 출구의 hog round(D9), 읽기 1, 2와 관문을 위처럼 고정하고 진단 셀을 640반복으로(D10), hog를 SM의 3/4 grid-stride로 바꿔 나머지 SM이 비게 함, 탐침은 정보(D11), 문구(D12, D13), `nproc`과 남의 compute app(D14) | 9.15.3 |
| 2026-10-11 | `rs_drain_test` `b3v4` 빌드됨(실행 안 함; md5 `c7cad09beb0092b3840899964bfee746`, 컴파일 때 소스 `a3534807` 기록, `out/b3v4/`): 복사 시각과 `.tsv`, 엔진 확인, 프로세스 안 hog(`RS_HOG=stream`, 응답 쪽만), 높은 우선순위의 non-blocking stream. 스크립트: `run_b3.sh`(셀 `m`, `dn`, `dp`, `dm`; `RS_HOG`와 시각 파일은 응답 쪽만; `m`, `d` 셀은 `b3v4`가 아니면 거절; meta `hog=`), `hold_feas.sh`(`B3diag-<node>[-<꼬리표>]`, `B3m-<cell>[-<꼬리표>]`, 640반복, `B3BIN`을 넘김, 예산), `summ_feas.py`(`b3m_run<k>/`를 읽고 `x`, `s`, `m`으로 묶음, 옛 `h`는 따로, 진단의 읽기와 관문), `deploy_feas.sh`(`b3v4`), `build_feas.sh`(info). summ_feas는 스크래치의 결과 폴더 복사본에 만든 가짜 진단과 새 셀 파일로 돌려 봄(진짜 결과 없음). 다만 고친 summ_feas를 진짜 폴더에도 한 번 돌려 `SUMMARY.txt`를 덮음(아래 행). 명령은 9.15.5 | 9.15.3, 9.15.5, `feas/` |
| 2026-10-11 13:56 | 고친 `summ_feas.py`(커밋 `1ec61a9b`)를 진짜 결과 폴더에 한 번 돌려 `results/20261009_feasibility/SUMMARY.txt`를 덮음(이 에이전트, 원자료는 그대로). 그 파일의 노드와 순서마다의 줄은 이제 `m` 셀이 없어 네 줄 모두 "missing"이다. 2026-10-09의 내용(rain `ro` 열림 4 727, `so` 열림 4 729, sunny `ro`, `so` 통과 4 800, 상한 0.0625%, 모든 실행 0/23 707)은 커밋 `fa43d230`의 `summ_feas.py`를 스크래치의 폴더 복사본에 돌려 같은 값으로 다시 만들어 `SUMMARY_20261009.txt`에 둠(14:13) `[측정: 다시 셈]`. 앞의 두 행에서 "그대로"와 "복사본으로만"이라고 쓴 것은 이 덮음과 어긋나 그 자리에 이 행을 가리키게 고침(코드 검토 V1) | `results/20261009_feasibility/SUMMARY_20261009.txt` |
| 2026-10-11 | `b3v4`와 스크립트의 독립 코드 검토(읽기 전용 에이전트, 커밋 `ad9672ee` 대상, 실행과 ssh 없음): 판정 "b3v4, the diagnostic and the new cells: ready to run", 막는 것 없음. 확인: md5(`c7cad09b`, 컴파일 때 소스 `a3534807` = 작업 트리), v3 → v4 차이는 계측뿐이라 판정, 셈, 예산과 상한이 그대로, 뒤 event와 돌기 사이에 CUDA 호출 없음, 기준 시각이 모든 길에서 맞고 반복을 넘어 남지 않음, 엔진 확인이 끝나고 걸리지 않음, hog 스레드가 non-blocking stream만 쓰고 결과 줄 전에 합류, Turing에서 1 024-thread 탐침이 굶지 않음(hog block 36개라 SM 12개 이상이 빔), 스크립트와 9.15.5 명령이 맞음, summ_feas의 읽기와 관문이 9.15.3과 같음(가짜 파일로 경계값까지 시험). 중간: V1(진짜 `SUMMARY.txt` 덮음 → 위 행), V2(진단을 다시 하면 어느 실행이 정하는지 없음, 셀 없는 노드도 관문 줄). 낮음: V3(`dp`의 엔진 확인은 시간 나눔에 흔들림), V4(summ 진단 표의 오류 표시, kv와의 교차 확인, 잘린 tsv 줄, reach 오름 늘 적기), V5(관문을 못 넘은 노드의 결론 줄), V6(`dp`의 kv `hog=none` 뜻). 정보: V7(시작 어림의 뜻, 지연 적재, tsv는 정상 끝에만). 반영(바이너리는 그대로): 9.15.3에 정하는 실행과 엔진 읽기(V2, V3, V7), summ_feas: 셀 없는 노드는 건너뛰고 노드마다 정하는 실행 하나로 읽기와 관문을 한 번만 적음, 오류 출구 표시, kv 교차 확인, 잘린 줄 세기, reach 오름, 엔진의 `dn`/`dm` 일치와 복사 시간 어긋남, 관문을 못 넘은 노드는 결론 줄이 "사용자에게"(V2, V4, V5, V7), 9.15.5 문구(V6)와 `SUMMARY.txt`를 늘 새로 쓴다는 메모. 고친 summ_feas는 스크래치의 가짜 파일로만 돌림 | 9.15.3, 9.15.5, `feas/summ_feas.py` |
| 2026-10-11 14:49:27–14:51:20 | hold `B3diag-rain`(26 s), `B3diag-sunny`(26 s), 둘 다 rc 0, 새 mlx5 줄 0, 펌웨어 명령 실패 31 → 31, 셀 앞 compute app 없음, 결과는 `b3_diag/`. 이 에이전트가 스크래치의 폴더 복사본에서 summ_feas로 다시 셈(메인 세션의 값과 같음) `[측정]`. 셀(`ro`, 680반복씩): `dn` rain reach p50 795.3 µs, sunny 644.9; `early` 늦은 낱말 40/40, 복사는 40/40 제때(시작 아래 끝 p50 rain 5.0 µs, sunny 7.8). `dp`(hog 프로세스) reach p50 rain 1 075.9, sunny 619.6; `early` 늦은 낱말 0/40, 복사는 40/40 늦음(시작 아래 끝 p50 rain 2 157.5 µs, sunny 2 147.9), `boundary` 0/40. `dm`(프로세스 안 hog) reach p50 rain 1 075.9, sunny 628.0; `early` 40/40, `boundary` 40/40, 시작 위 끝 p90 rain 9.7 µs, sunny 15.0; hog 대역 rain 329.8 GB/s, sunny 370.3(`dp`의 hog 프로세스 322.1, 360.4). 엔진은 여섯 셀 모두 `sm`(회전 커널이 SM을 채운 동안 확인 복사가 4 455–6 438 µs 기다림). QUERY_QP: rain 응답 쪽 셋 3 504, 4 244, 4 544(rain debugfs 증가 12 292와 같음), sunny 응답 쪽 2 405, 2 564, 2 651. 읽기 1(시간 나눔): 두 노드 모두 "맞음". 읽기 2: 두 노드 모두 "예". 관문: rain 넘음(reach 오름 `dm` 280.6 µs, `dp` 280.6), sunny는 (1), (2)를 넘고 (3)에서 걸림(오름 `dm` −16.9, `dp` −25.3 µs: 두 hog 모두 도착을 늦추지 않음) | `results/20261009_feasibility/b3_diag/`, `hold_B3diag-rain.out`, `hold_B3diag-sunny.out` |
| 2026-10-11 | 사용자 결정(메인 세션이 전함, sunny 새 셀의 결과 전, 선택지 (가)): sunny의 관문 (3)은 적용하지 않음. 까닭: sunny에서는 두 hog 모두 NIC 쪽 도착을 늦추지 않아(오름 음수) (3)의 전제(hog 프로세스의 오름이 양수)가 없고 음수 오름의 절반은 뜻이 없음. (1), (2)는 넘음. 범위: sunny의 관문 (3)만, rain은 그대로, 셀 규칙, 예산, 상한, 판정, 묶음은 그대로. sunny 새 셀은 정의대로 하고, 그 결과는 쓰기 도착을 늦추는 경합을 보이지 않으며 "프로세스 안 메모리 부하 아래에서 제때 낸 복사"만 시험한 것으로 적음. `summ_feas.py`가 sunny에 "gate item 3 not applicable (user decision 2026-10-11)"을 적도록 고침(스크래치 복사본에서 확인: sunny 관문 줄이 "passed"와 그 메모가 됨) | 9.15.3, `feas/summ_feas.py` |
| 2026-10-11 14:52:06–16:20 | 새 경합 셀 넷(셀마다 hold 하나, `b3v4`, 3 200반복, `RS_LAST_KB=4096`, 예산 19 000, 결과는 `b3m_run1/`), 모두 `cluster_run.sh` 안, rc 0, 새 mlx5 줄 0, 펌웨어 명령 실패 31 → 31, `cmd_err` 2 → 2, STOP 파일 없음, 셀 앞뒤 compute app 없음. 이 에이전트가 원자료에서 다시 셈(메인 세션의 값과 같음) `[측정]`: `b3_m_rain_ro`(14:52:06, hold 13 s) PASS, valid 1, fence 0/1 463, `early` 183/183, `boundary` 182/182, 경계 덮기 1.000, 예산 멈춤 2 926반복, QUERY_QP 19 004(rain debugfs 증가 같음), reach p50 1 074.0 µs, 사본 늦음 0/183, hog 326.4 GB/s; `b3_m_sunny_ro`(16:18:15, 12 s) PASS, 0/1 600, 200/200, 200/200, 3 400반복, QUERY_QP 13 634, reach p50 617.2, 늦음 0/200, hog 366.7; `b3_m_rain_so`(16:18:58, 13 s) PASS, 0/1 445, 180/180, 181/181, 예산 멈춤 2 891, QUERY_QP 19 003(debugfs 같음), reach p50 1 074.3, 늦음 0/180, hog 326.5; `b3_m_sunny_so`(16:19:43, 12 s) PASS, 0/1 600, 200/200, 200/200, 3 400, QUERY_QP 13 646, reach p50 619.6, 늦음 0/200, hog 366.5. 모든 셀 엔진 `sm`, 자체 시험 1/1, `nofence`, `fence_same`, `cuflush`, `WA`, SM 직접 검사 모두 실패 0, 신호 틀림 0 | `results/20261009_feasibility/b3m_run1/`, `hold_B3m-*.out` |
| 2026-10-11 | B3 결과(summ_feas, 이 에이전트가 스크래치의 폴더 복사본과 진짜 폴더에서 다시 셈): rain `ro` 통과 4 663(상한 약 0.0643%), rain `so` 통과 4 645(약 0.0646%), sunny `ro`, `so` 통과 4 800(0.0625%), 모든 실행 0/29 815, B3 결론 "drain 확인이 두 순서 모두에서 통과(strict 조건은 사용자 결정)". sunny의 새 셀은 쓰기 도착을 늦추는 경합을 보이지 않음(사용자 결정), READ 없는 대조 길도 실패 0이라 쓰기가 보이는 것을 READ 덕분으로 돌리지 못함. 9.15.3에 결과 문단, 9.11.12 B3 행, 머리말, 11절을 고침. strict window 무장 조건은 정하지 않음(사용자 결정 대기). 현재 `summ_feas.py`로 진짜 폴더의 `SUMMARY.txt`를 다시 만듦(2026-10-09의 내용은 `SUMMARY_20261009.txt`에 그대로) | 9.15.3, 9.11.12절, `results/20261009_feasibility/SUMMARY.txt` |
| 2026-10-11 | 사용자 결정(메인 세션이 전함, B3을 결정으로 닫음): "복원 정책이 활성화된 communicator에서 복원 대상으로 등록되는 window는 런타임이 NCCL_WIN_STRICT_ORDERING을 강제한다. 강제가 불가능하면 조용히 복원을 끄지 않고 명시적인 등록 오류를 반환한다." 근거(메인 세션이 2.32.3에서 확인, 이 에이전트가 hw 트리에서 다시 읽음): `device_gin.rst` 156, `gin_host.cc` 556, `gdakiRegMr`(hw 188–199), NCCL이 자기 신호 표와 RMA 버퍼를 늘 `FORCE_SO`로 등록. relaxed는 능력 확인과 겹침 실험을 통과한 뒤의 최적화 후보로만 남음. 사용자의 순서: (1) 강제의 범위와 등록 flag 충돌 검토, (2) 정상 경로의 strict와 relaxed 비교, (3) 복원 실험의 예측과 셀(DRAFT), (4) 구현, pilot, 사전 등록, 본 실행. 지금은 (1)과 (2)의 준비만, 복원 계층 코드 없음 | 9.10.8절, 9.11.12절 B3 |
| 2026-10-11 | (1) 강제의 범위와 충돌 표(빌드 전): 9.10.8절에 정의("활성화" = 프로세스의 `NCCL_GIN_FAULT_POLICY=hold`와 `NCCL_GIN_RESTORE` ≠ 0, 등록이 정책 합의보다 먼저이므로; "복원 대상" = devComm을 만들 때 이미 등록된 window, 강제는 hold 프로세스의 모든 GDAKI window MR; "강제" = GDAKI MR을 `FORCE_SO`로, application의 `winFlags`는 그대로; "강제 불가능" = GDAKI에서는 늘 되므로 지킴이 오류 E1, HCA의 relaxed 강제 설정 E2 `[미확인]`; devComm 전 window의 오류는 `ncclDevCommCreate`에서)와 자리마다의 충돌 표(RO 변수: 2.32.3에서 1과 2가 같게 동작하고 실패하지 않음 `[소스]`; 사용자 flag 넷; 메모리 재사용; devComm과 Resume 전후; rank 사이 정책 불일치; GDAKI 밖 backend; LSA와 NVLS; host RMA; 루프백 MR과 복원 버퍼; hk의 G1; 옛 무장 조건; B3 기록; VA 신호; 장치 코드; 성능). 9.10.4절의 무장 조건 "window는 strict"를 강제로 바꿈(옛 문장은 그 자리에 남김), hook RL21 더함. 사용자 확인 권함: hold 프로세스에서 GDAKI 밖 backend를 명시적 오류로 막을지(지금 설계는 기존 WARN과 fail-fast) | 9.10.4, 9.10.8절, 9.9절 RL21 |
| 2026-10-11 | (2) 정상 경로 비교의 설계(빌드 전, DRAFT 단계 측정): 배포된 `hk`, gin_ts2에 window flag 환경 변수와 burst 반복 시간 통계만 더한 드라이버, 새 실행기 `run_ord.sh`(받는 쪽 노드 둘), 셀 셋(4 KiB와 256 KiB 지연, 256 KiB × 16 대역) × strict와 relaxed × 6실행, 노드마다 hold 하나(36실행)에서 붙여 섞음, 판정(유효 조건, 6 대 6 갈림, 2% 문턱의 읽기)과 충돌 표를 실행 전에 고정 | 9.15.6 |
| 2026-10-11 | 강제 범위와 비교 설계의 독립 검토(읽기 전용 에이전트, 커밋 `c318b5e4` 대상): 강제 결정 자체와 표의 대부분 행은 소스와 맞음(RO 1과 2가 같고 실패 안 함, 사용자 flag, 재사용 동일성, 등록 능력 all-gather, 미뤄진 등록, backend, 루프백 MR, VA 신호, 장치 코드; hook 자리는 `RegMrSym`이 맞음). 열린 것: K1(등록 오류는 한 rank만의 것이라 다른 rank가 rkey all-gather나 bootstrap barrier에서 멈추고, 실패 길이 `ginEnabled`와 symmetric 커널 초기화를 되돌리지 않음), K2(빠진 행: COLL_SYMMETRIC이 첫 등록에서 내부 GIN devComm으로 GIN을 켬, RL9의 "문맥"은 사용자 문맥이어야 함), K3(빠진 행: 사용자 devComm의 자원 window가 문맥 뒤에 등록돼 늘 무장을 막음), K4(모든 rank의 복원 대상이 strict임을 보이는 것이 없음: 예비 프로세스, 섞인 빌드), K5("[RO]" 줄은 RO 요청이지 실제가 아님). 낮음 K6–K12, 사용자 선택 하나(GDAKI 밖 backend의 hold: WARN과 fail-fast냐 명시적 오류냐; 검토는 env만으로는 WARN, `ncclGinRestoreResume`이 "무장할 수 없음"을 명시적으로 알리게 하자고 제안). 판정 "open: K1, K2, K3, K4, K5" | 9.10.8, 9.15.6 |
| 2026-10-11 | 검토 반영(빌드 전 설계): K1 등록 호출에는 실행 중 오류 길을 두지 않음(GDAKI는 늘 강제됨, 지킴은 단위 시험 E1), 명시적 오류는 G1 기록의 strict 비트로 사용자 `ncclDevCommCreate`에서 모든 rank가 같이 돌려주고 그 communicator는 끝(다시 하지 않음); K2 표에 COLL_SYMMETRIC 행, 복원 대상은 사용자 투명 복구 문맥을 기준, 무장 조건에 "NCCL 안의 GIN devComm 없음"(`NCCL_SYM_GIN_KERNELS_ENABLE=0`) 더함(사용자 확인 권함); K3 사용자 devComm의 자원 window를 복원 대상으로 넣고 RL9를 넓힘; K4 rank마다 strict 비트와 복원 켬을 G1 기록(`policyPad`)에 싣고 ARMED에 요구, 예비 프로세스는 늘 강제; K5 relaxed 팔은 "RO 요청"으로, 드라이버가 NCCL의 RO 조건을 kv(`ro_requested`)로 적음, 결과 없음의 읽기를 고침; K6 실행 변수 고정; K7 바뀐 것은 flag와 kv뿐, 지연의 뜻; K8 같은 값은 갈리지 않음, 2% 미만 읽기, 거짓 갈림 약 1.3%, 정상 확인; K9 WARN 수준; K10 같은 노드 쌍은 한계; K11 표 고침(링크 양, `ncclCommRegister`, 부분 slot 누수, 유지보수 메모, hk 줄 번호, RO=1이면 WARN, READ를 대신하지 않음, E2를 18절에, `NCCL_GIN_RESTORE`의 정의); K12 개인 작업 디렉터리와 `ulimit -c 0`, 남은 프로세스는 실행 고유 이름으로 | 9.10.4, 9.10.8, 9.9절 RL9, RL21, 9.15.6, 18절 |
| 2026-10-11 | (2)의 빌드(실행 안 함): `gin_ts2` ord md5 `64418f216c68bf1f518b25737a7e5c9d`(`out/ord/`; 소스 `1779db9d` + `gin_ts2_winflags.diff` `fb9d2d8d` → `fa30bb70`, hw 헤더, gin-remaining `build_hr.sh` drivers()의 flag). 새 파일 `feas/run_ord.sh`, `feas/summ_ord.py`(가짜 실행 파일로만 시험), `hold_feas.sh`에 hold `ORD-<노드>[-꼬리표]`, `build_feas.sh`의 `ord`, `deploy_feas.sh`의 `ord`. 명령은 9.15.6 | 9.15.6, `feas/` |
| 2026-10-11 | 반영의 독립 재확인(같은 에이전트, 커밋 `df0c2352` 대상): K1–K12 닫힘(K3은 자리만). `policyPad` 칸은 hk 기록 모양과 G1 비교를 깨지 않음, 안의 GIN devComm 길은 `sym_kernels.cc` 254 하나, ord 빌드는 diff와 맞음(`fa30bb70`, 64418f21), `ro_requested`는 NCCL의 계산과 같음 `[소스]`. 비교 코드와 9.15.6은 대체로 맞고 지속 시간은 hold마다 약 6분으로 맞음(gpu-detect 지연 실행 1.8–2.4 s를 다시 셈). 열린 것: K13(hold이고 `NCCL_GIN_RESTORE=0`이 오류가 됨), K14(오류가 `ncclDevCommCreate`에서 `ncclInternalError`로 나오거나 다른 backend로 조용히 넘어감, 자리의 옮김은 사용자 확인 필요), K17(자원 window를 GDAKI 층이 알아볼 수 없고 루프백 MR 더하기는 잠금 없는 벡터라 다툼), K19(`summ_ord.py`에서 무효 실행 하나가 노드 전체를 "비교 불가"로). 낮음 K15, K16, K18, K20–K23, 정보 K24 | 9.10.8, 9.15.6 |
| 2026-10-11 | 재확인 반영: K13 "복원 요청"으로 정의를 바꿔 모두 `NCCL_GIN_RESTORE=0`이면 오류 없음; K14 오류의 자리와 값을 사용자 선택으로((a) `gin_host.cc` 고침, (b) `ncclInternalError`와 WARN, `NCCL_GIN_TYPE=3` 요구, (c) `ncclGinRestoreResume`; 이 에이전트는 (b)를 권함); K15 결정은 `all[]` 전체로 all-gather 바로 뒤, FULL 연결 요구; K16 섞인 라이브러리는 지원하지 않음; K17 자원 window는 `ncclGinRestoreResume`에서 `devComm.resourceWindow`로 찾고 잠금 안에서 루프백 MR에 더함, 9.4절 (a)에 적음; K18 안의 GIN devComm 검사는 `ncclGinRestoreResume`에서, 그 뒤 사용자 문맥이 아닌 문맥이면 DISARM; 남은 설계 선택 넷의 목록을 9.10.8절에 둠(강제 구현 전에 받음). 비교 코드: K19 `summ_ord.py`(RO는 유효 실행에서만, 노드 줄이 비교 불가와 미완을 말함, 정하는 폴더 규칙과 meta 없는 kv), K20 hold(STOP_left도 건너뜀, `/tmp/rs_ord` 남은 프로세스와 자기 파일 지우기), K21 `NCCL_*`, `GIN_*`를 모두 지우고 sunny에 umask, K22 지연 원자료 `lat_raw.csv.gz`, K23 정하는 폴더, K24 hold 시작의 `lib_md5.txt`. 바이너리는 그대로(`64418f21`) | 9.4, 9.10.4, 9.10.8, 9.9절 RL21, 9.15.6, `feas/` |
| 2026-10-11 | 반영의 마지막 재확인(같은 에이전트, 커밋 `adc5b8c0` 대상): K13–K24 닫힘. 판정: 강제의 범위에 열린 충돌 없음(사용자 설계 선택 넷 대기), 비교는 실행 준비됨. 낮음 셋(K25 옛 오류 규칙의 문장이 몇 자리에 남음, K26 오류 자리의 선택 (b)만으로는 proxy로 조용히 넘어감을 막지 못함, K27 Resume에 devComm이 없음)과 정보(정하는 폴더가 없으면 한 줄) → 반영: 옛 문장들을 "복원 요청"과 오류 자리의 선택으로 고침, 그 선택의 (b)를 "(b) + Resume 검사"로(`NCCL_RMA_DISABLE=1`, `NCCL_GIN_TYPE=3` 요구), Resume에 devComm(또는 기록)과 주소 규칙, `summ_ord.py`가 정하는 폴더가 없는 노드를 한 줄로 알림. 남은 설계 선택 넷은 강제 구현 전에 받음 | 9.10.4, 9.10.8, 9.9절 RL21, `feas/summ_ord.py` |
| 2026-10-11 ≈17:22–17:25 | 메인 세션: ord 배포(확인 파일: rain == sunny, source == deployed, ldd가 두 노드에서 `~/gi-bundle/gin_ts2/hk`, 그 밖의 파일 그대로 rain 334, sunny 386; 이 에이전트가 다시 읽음). hold `ORD-sunny`(17:23:14 잠금, hold 79 s, rc 0, 새 mlx5 줄 0, 펌웨어 명령 실패 31 → 31, `cmd_err` 2 → 2, `lib_md5.txt` 두 노드 `2913c777`): k1의 지연 셀 넷 완료(4 KiB strict와 relaxed 모두 p50 10.50 µs, 256 KiB 모두 38.88 µs, `win_flags` 0x3/0x1, `ro_requested=1`), `ord_bw256k_strict_sunny_k1`에서 rank 0(rain)이 첫 window 등록에서 "unhandled system error"(exit 2), rank 1 watchdog(exit 7), wall 46.5 s, left 0. 실행기가 STOP_nic를 쓰고 31실행을 건너뜀, `ORD-rain`은 시작 안 함 `[측정: 이 에이전트가 원자료에서 다시 셈]` | `results/20261011_ordering/ord_sunny/`, `hold_ORD-sunny.out`, `STOP_nic`, `skipped.txt` |
| 2026-10-11 | 진단과 고침(9.15.6의 "첫 hold 뒤" 문단): 대역 셀의 window가 800 MiB씩 둘(256 KiB × 200 × 16)이라 rain의 BAR1(256 MiB, GIN window 50 MiB 넘으면 등록 실패의 기록)을 넘음 `[추론]`; "unhandled system error" = `ncclSystemError`, 이 길에서는 ibverbs 등록 실패나 GIN 등록부 NULL `[소스]`; strict와 relaxed는 RO 비트만 다름 `[소스]`; WARN 줄이 없던 것은 블록 버퍼 stdout과 `_exit` `[소스: debug.cc 35, 268–270]`. 고침: 대역 셀 256 KiB × 8 × 12(window 24 MiB, 값 = K × 256 KiB / p50, `summ_ord.py`는 K를 kv에서 읽음), `stdbuf -oL -eL`, 진단 smoke hold `ORDSMOKE-<노드>`(NCCL INFO는 노드의 `~/rs-ordlogs/`에만). 판정 규칙(유효 조건, 6 대 6 갈림, 2% 문턱, 정하는 폴더)은 그대로이고 대역 셀의 크기와 값의 식만 바뀜(측정 전 바꿈, 그 셀의 결과는 아직 없음). STOP_nic 푸는 단계와 명령은 9.15.6 | 9.15.6, `feas/run_ord.sh`, `feas/summ_ord.py`, `feas/hold_feas.sh` |
| 2026-10-11 | 고침의 독립 검토(읽기 전용 에이전트, 커밋 `5e50aa76` 대상): 판정 "ord fix: ready to clear STOP_nic and run the smoke", 막는 것 없음. 진단이 소스와 맞음(오류 문자열, strict와 relaxed는 RO 비트만, WARN이 사라진 까닭; 정상 지연 실행 넷의 로그도 4 KiB에서 잘림 `[측정]`), `ncclCommRegister`는 MR을 만들지 않고 내부 devComm은 크기와 무관, 24 MiB는 이미 된 4 × 16 MiB보다 작음, eval과 stdbuf, summ의 값과 정하는 폴더(`ORD-sunny-2` → `ord_sunny_run2`), smoke 폴더가 맞음, STOP_nic 풀기 조건 (1), (3)이 원자료와 맞음. 중간: O1(`skipped.txt`도 옮겨야 함). 낮음: O2(`~/rs-ordlogs`를 만든 결과 확인), O3(BAR1 문턱과 snap), O4(NVRM dmesg 줄), O5(낡은 문장), O6(본 hold는 ORD_DIAG=0, summ이 구성과 diag를 확인), O7(진단 파일 지우기), O8(이미 돈 명령 표시). 정보: O9, O10(뒷받침 사실과 반증 조건), O11(대역 셀의 민감도, smoke는 relaxed 먼저). 모두 반영(스크립트만, 바이너리와 배포 그대로) | 9.15.6, `feas/run_ord.sh`, `feas/hold_feas.sh`, `feas/summ_ord.py` |
| 2026-10-11 | 메인 세션의 읽기 전용 확인(passwordless sudo): `lspci -vvv` DevCtl은 rain NIC mlx5_1 `0000:17:00.1` RlxdOrd+ NoSnoop+, rain GPU `65:00.0` RlxdOrd+, sunny NIC mlx5_0 `0000:17:00.0` RlxdOrd+, sunny GPU `65:00.0` RlxdOrd+(두 NIC 링크 "8GT/s (downgraded), x16", 정보); `mlxconfig q PCI_WR_ORDERING`은 두 ConnectX6 모두 `per_mkey(0)`; BAR1은 rain Total 256 MiB(Used 5, Free 251), sunny 16 384 MiB(Used 21, Free 16 363); rain `dmesg`에 17:23–17:25의 `NVRM: dmaAllocMapping_GM107: can't alloc VA space for mapping.` 19줄(버퍼 전체 913줄; `dmesg -T` 시계는 어긋날 수 있음) `[측정]`. 뜻: (가) 첫 `ORD-sunny`의 대역 셀 실패는 rain의 BAR1 VA 부족으로 `[측정]`이 됨, sunny의 16 GiB BAR1이 같은 등록이 된 까닭; (나) B3의 relaxed(`ro`) 셀은 NIC 쪽에서 relaxed ordering이 실제로 허용된 채 돌았다(RO access flag + NIC DevCtl RlxdOrd+ + per_mkey 펌웨어) `[측정]`, root complex가 그 쓰기를 실제로 바꿔 놓았는지는 볼 수 없다 `[미확인]`(9.15.3의 결과 해석은 바꾸지 않음); (다) 펌웨어가 relaxed 쓰기를 강제하는지는 이 두 NIC에서 확인됨(per_mkey, 강제 안 함), 다른 기계에는 한계로 남고 sudo 읽기 한 번이면 풀림; (라) per_mkey이므로 strict 강제(MR에 RO flag 없음)는 이 두 노드에서 NIC의 strict 쓰기다. 풀기 조건 1–4가 맞아 메인 세션이 STOP_nic와 `skipped.txt`를 같은 시각 꼬리표로 옮김. ORDSMOKE hold는 도는 중(결과는 따로) | 9.10.8, 9.15.6, 18절 |
| 2026-10-11 | 사용자 결정(메인 세션이 전함, 설계 선택 넷): "application이 복원을 요청했는데(ncclGinRestoreResume 호출) 켤 수 없으면, 이유가 무엇이든 그 함수가 이유와 함께 오류를 돌려준다. 모든 rank가 같은 오류를 받는다." 적용: GDAKI 밖 backend의 hold → Resume이 이유와 함께 오류; hold에는 `NCCL_SYM_GIN_KERNELS_ENABLE=0`이 조건으로 남고 어기면 Resume이 오류; 오류의 자리는 (b)(devComm 생성은 `ncclInternalError`와 WARN, Resume이 "이 communicator는 복원할 수 없음"을 이유와 함께; hold 프로세스는 `NCCL_RMA_DISABLE=1`, `NCCL_GIN_TYPE=3`, Resume에서 확인); rank 사이에서 `NCCL_GIN_RESTORE`만 다르면 모든 rank의 Resume이 오류. 첫 결정의 "등록 오류"는 이렇게 다듬어짐: 명시적 오류는 window 등록이 아니라 Resume(과 devComm 생성)에서 나옴(한 rank만 등록에서 오류를 내면 다른 rank가 rkey all-gather에서 멈추므로). 같은 날 사용자 지적("U1-U4 처럼 또 은어 만들어서 쓰지말고")으로 이 문서의 설계 선택 표지 U1–U4를 내용을 말하는 이름으로 바꾸고 새 짧은 부호를 만들지 않기로 함(12절의 지난 행도 그 표지를 풀어 씀; 2026-10-09 b3v3 검토의 지적 번호 U1–U8은 다른 것으로 괄호 안의 찾는 키로 남음) | 9.10.8, 9.10.4, 9.9절 RL21, 11절 |
| 2026-10-11 19:58–20:00 | 진단 smoke hold 둘(`cluster_run.sh` 안, rc 0, 각 18 s, 새 mlx5 줄 0, 펌웨어 명령 실패 31 → 31, `cmd_err` 2 → 2, NVRM 매핑 실패 줄 913 → 913): `ORDSMOKE-rain`(잠금 19:58:42; 메인 세션의 글은 17:46:06이나 그것은 STOP 파일을 옮긴 시각이고 hold 출력의 잠금 시각은 19:58:42 — 원자료를 따름), `ORDSMOKE-sunny`(19:59:32). 네 실행 모두 `rc_r0=0 rc_r1=0 left=0`, kv `exit=0`, `iters=12`, `burst_K=8`, `diag_files=1/1`; 반복 12의 p50 rain 381.95 µs(두 팔), sunny 322.82(relaxed)와 323.36(strict) µs; BAR1 rain 256/5/251 MiB, sunny 16 384/2/16 382 MiB. 노드의 진단 파일은 smoke 뒤 메인 세션이 지움(WARN 줄은 필요 없었음) `[측정]` | `results/20261011_ordering/ord_smoke_rain/`, `ord_smoke_sunny/`, `hold_ORDSMOKE-*.out` |
| 2026-10-11 20:00–21:16 | 본 hold 둘: `ORD-sunny-2`(잠금 20:00:40, 232 s) → `ord_sunny_run2/` 36실행, `ORD-rain`(21:12:34, 229 s) → `ord_rain/` 36실행; 둘 다 rc 0, 새 mlx5 줄 0, 펌웨어 31 → 31, `cmd_err` 2 → 2, STOP 파일 없음. 이 에이전트가 다시 셈: 지연 셀 48실행의 p50을 원자료 `lat_raw.csv.gz`에서 다시 구해 kv와 모두 같음, summ_ord.py의 표가 메인 세션의 값과 같음: 모든 셀 6 대 6, 갈림 없음, 읽기 "차이를 잴 수 없음"(9.15.6 결과의 표). 노드 줄은 둘 다 "relaxed의 2% 이상 이득을 재지 못함". 한계(작은 대역 셀, RO는 요청되고 NIC 쪽에서 허용됐으나 root complex의 실제 순서 바꿈은 보지 못함)는 9.15.6 결과에 | `results/20261011_ordering/ord_sunny_run2/`, `ord_rain/`, `SUMMARY_ORD.txt` |
| 2026-10-11 | 사용자 순서 (3)과 (4)의 준비(구현하지 않음): 1절에 질문 5(켤 수 없을 때의 명시적 오류와 strict 강제), 2절 가설 여섯, 3절 예측 열일곱(시행마다의 조건과 "유효 시행 n개 가운데 k개 이상" 꼴의 판정식, 문턱과 n은 pilot 뒤 고정), 6절 변수(hold 프로세스의 고정 설정 포함), 7절 셀과 반복 수(켤 수 없는 설정의 셀 셋 더함), 8절 제외와 중단 기준, 모두 DRAFT. 9.14절에 구현 계획: hk 위의 작업 묶음 열(차례, 바탕, 바꾸는 것, 충돌 확인, 빌드와 단위 확인, pilot이 보여야 할 것; 장치 헤더는 묶음 둘, NCCL 핵심 파일은 묶음 둘). 짧은 부호를 새로 만들지 않음(예측의 "찾는 키"는 원자료를 찾는 이름) | 1–3, 6–8절, 9.14절 |
| 2026-10-11 | 정책 설계 문서를 이 문서로 합침(사용자 결정, 메인 세션이 전함: 실험 하나에 `EXPERIMENT.md` 하나, 단계별 문서를 따로 두지 않는다는 저장소 규칙과 `DESIGN_POLICY.md`가 어긋나 9절로 합침, 선택지 (가)). 옮긴 곳: 그 문서의 1절 → 9.10.1, 2.1–2.5절 → 9.10.2–9.10.6, 3절 → 9.10.7, 4절과 4.1–4.11절 → 9.11과 9.11.1–9.11.11, 5절 → 9.11.12, 6절 → 9.11.13, 7절 → 20절(이미 있던 항목과 합침), 머리말의 목적, 상태, 근거 트리, 독립 검토, 줄 번호 규칙 → 9.10의 첫 문단들. 내용은 그대로이고 안의 절 참조만 새 번호로 고침("EXPERIMENT.md N절"은 "N절"로, "이 문서"는 "이 정책 설계"로). 9.10, 9.11의 옛 가리킴 문단과 머리말의 "설계의 기준 문서" 문단은 바꿈. 이 문서 안의 모든 가리킴(본문, 9.15 판정 글의 절 번호 둘, 11절, 12절의 지난 행, 19절)을 경로와 절 번호만 새 자리로 고침. gpu-detect 문서의 자리는 그 사이 master로 옮겨져(PR #63) 경로 글만 고침. `DESIGN_POLICY.md`는 이 커밋에서 지움(git 역사에 남음). 해석이나 결과는 바꾸지 않음 | 9.10–9.11절 |
| 2026-10-11 | 작업 묶음 1(정책 도우미, strict 강제, 설정 기록 넓히기, 정하는 자료)의 충돌 확인(코딩 전, 9.14절이 정한 범위). 9.10.8절 표의 행마다 이 묶음의 변경과 맞춤: `NCCL_IB_PCI_RELAXED_ORDERING`(강제가 이기고 1이면 WARN 한 줄), 사용자 flag, COLL_SYMMETRIC(내부 window도 강제됨, 조건은 기록의 변수 사실), GIN_ONLY와 CFT, 메모리 재사용(`winFlags`를 바꾸지 않음), `ncclCommRegister`(닿지 않음), devComm 전후와 Resume 뒤 window(모두 강제, 등록 호출에 오류 길 없음), 정책을 아는 길과 불일치(hk의 WARN과 fail-fast 그대로), 예비 프로세스(늘 강제), Resume을 부르지 않는 communicator(강제, 비용만), GDAKI 밖 backend(닿지 않음, Resume은 묶음 2), active backend 둘, LSA와 NVLS, host RMA 등록, 여러 조각, 루프백 MR, hk의 정책 칸(G1; 도우미로 바꿈, `hk_layer.diff`는 고치지 않음), 옛 무장 조건, VA 신호, 장치 코드. 9.10.4절: 합의는 all-gather 바로 뒤 helper 소켓 잇기 전, 모든 p에 대해. 9.11절: 정책 칸(G1; 기록 크기 그대로 56 B, `policyPad`만 채움), 운영과 연구 빌드(시험 스위치 없음), helper 메시지 규약(새 메시지 없음), rkey all-gather(등록 길에 새 실패 없음). 결과: 설계가 풀지 못한 충돌 없음 `[소스]`. 이 에이전트의 해석 넷(독립 검토가 타당하다고 봄): (1) rank마다 다를 수 있는 변수 사실(`NCCL_GIN_TYPE`, `NCCL_RMA_DISABLE`, `NCCL_SYM_GIN_KERNELS_ENABLE`, devComm의 GIN rank stride)을 기록 비트로 실어 Resume의 이유가 모든 rank에서 같은 자료에서 나오게 함, (2) 그 GDAKI 문맥의 생성을 끝내는 것은 "복원을 요청한 rank의 strict 비트 0"뿐이고 다른 거절은 fail-fast 문맥을 남겨 Resume이 알림(그래야 거절 셀에서 Resume에 닿음), (3) 살아 있는 설정의 all-gather에 든 예비 프로세스는 거절(예비 프로세스는 초기화를 재생하므로; 묶음 8에서 예비 프로세스 자신의 결정을 정해야 함), (4) symmetric 커널의 GIN은 변수 `NCCL_SYM_GIN_KERNELS_ENABLE=0`으로만 판단(9.10.8절 사용자 결정의 적용 문장대로; 9.10.4절의 "또는 COLL_SYMMETRIC window 없음"보다 엄격). 시험 방법의 차이 하나: 9.14절의 "디버그 빌드의 계수로 RO 비트" 대신 연구 빌드의 window MR 보고 줄(`gdakiRegMr`가 실제로 등록한 access flag의 RO 비트)과 강제 판단 함수의 CPU 시험. RO 비트가 실제로 빠지는지는 pilot이 그 줄을 읽어야 보인다 `[미확인]` | 9.10.8, 9.14절 |
| 2026-10-11 | 새 빌드 트리(세션 스크래치 `agent_rs`): gpu-detect `hk` 트리(`agent_gd/gin_hk`, 읽기만)의 복사. 복사 전 확인: 작업 트리 = `hk_layer.diff` md5 `c5222c553801af455da0784fd1ac9022`, 빌드 hk libnccl `2913c777aa0b05d4d566c9f7638c6a0e`, hkp `84209c03a497bd28206210205bfc6cf5`, 복사 뒤 두 빌드의 md5가 같음 `[측정]`. 복사본에 커밋 "gpu-detect hk (libnccl 2913c777)"(그 아래 hw `be0ea9ed`, hr). 새 파일 [impl/build_rs.sh](impl/build_rs.sh)(트리 준비, 연구 빌드, 운영 빌드 `-DNCCL_GIN_TS_PRODUCTION`, CPU 단위 시험, md5 기록; 출력은 늘 새 폴더, 있으면 거절), [impl/make_diff_rs.sh](impl/make_diff_rs.sh)(diff와 다시 적용 확인, hr에서 hw, hk, 이 계층을 차례로 적용한 확인), [impl/rs_unit.cc](impl/rs_unit.cc)(호스트 파일의 "gin-restore: pure functions" 표시 사이 구간을 잘라 g++로 컴파일하는 CPU 시험) | `impl/` |
| 2026-10-11 | 작업 묶음 1 구현(호스트 파일 `gin_host_gdaki.cc`만). (가) 정책 도우미: 프로세스마다 한 번 읽음. `NCCL_GIN_FAULT_POLICY`와 `NCCL_GIN_RESTORE_SPARE`는 hk의 정책 칸(G1)처럼 `getenv`, `NCCL_GIN_RESTORE`는 NCCL 변수(기본 1)이고 hold일 때만 읽음. 복원 요청 = hold이고 `NCCL_GIN_RESTORE` ≠ 0, 또는 예비 프로세스(9.10.8절의 정의). hk의 정책 칸(G1)이 이 도우미를 씀. (나) `ncclGinGdakiRegMrSym`: 복원을 요청한 프로세스의 모든 GDAKI window MR을 strict로 등록(window flag와 상관없이, 새 실패 길 없음). hold나 예비 프로세스에서는 window MR마다 보고 줄 하나(strict, 강제 여부, flag의 strict, 실제 access flag의 RO 비트, 복원 요청), `NCCL_IB_PCI_RELAXED_ORDERING=1`이면 첫 강제 등록에 WARN 한 줄. `gdakiRegMr`에 등록한 access flag를 돌려주는 출력 인자 하나(기본 null, 다른 호출은 그대로). (다) 설정 기록의 `policyPad`: 복원을 요청한 rank만 all-gather 바로 전에 채움(요청, strict, 예비 프로세스, all-gather 전 지역 검사로 투명 복구가 꺼짐, `NCCL_GIN_TYPE` ≠ 3, `NCCL_RMA_DISABLE` = 0, `NCCL_SYM_GIN_KERNELS_ENABLE` ≠ 0, rank stride > 1). 요청하지 않은 rank는 0(hk의 기록과 같음). (라) 정하는 자료: all-gather 바로 뒤, helper 소켓을 잇기 전에 모든 rank가 기록만으로 정함(정하는 함수는 정하는 rank를 인자로 받지 않음). 차례: 아무도 요청하지 않음(오류 없음, 모두 hold이고 `NCCL_GIN_RESTORE=0`인 셀 포함) → 요청이 rank 사이에서 다름 → 요청한 rank의 strict 비트 0(그 GDAKI 문맥을 만들지 않음: `ncclInternalError`와 WARN) → 투명 복구가 꺼진 rank → 살아 있는 설정의 예비 프로세스 → 변수 사실 → 켤 수 있음. 이유 문자열에는 결정하는 rank의 번호가 없고 문제가 된 rank 번호만 있음. (마) 로그: 복원을 요청한 rank는 모든 길에서 결정 한 줄. hold의 hk WARN은 앞말("NCCL_GIN_FAULT_POLICY=hold requested, not available in this build")을 지키고 괄호에 결정을 씀(gpu-detect 채점기의 정규식이 그대로 맞음 `[소스: rows_gd.py 80]`). 이유 문자열에는 gpu-detect 채점기의 문구가 들어가지 않음. 유효 정책은 여전히 fail-fast(붙잡기 반응은 작업 묶음 7). fail-fast(정책 변수 없음이나 failfast, 예비 변수 없음)에서 hk와 다른 것: 동작은 없음(MR access flag, 기록 바이트, 흐름, 반환값 같음), 로그는 정책 변수 값이 127자를 넘을 때 WARN에서 잘리는 것뿐 `[소스]`. hold이고 `NCCL_GIN_RESTORE=0`이면 동작은 hk와 같고 로그(window MR 줄, hold WARN의 괄호)만 다름 | `impl/rs_layer.diff` |
| 2026-10-11 | 작업 묶음 1 빌드됨(rain, nice 19, ionice idle; 실행 안 함): 연구 빌드 `out/rs_p1` libnccl `92e8d9d6d87e7f54b755b2eda5fd0373`, 운영 빌드 `out/rsp_p1` `ecaecc0e5d1a6ff9e165732527b34252`, 두 빌드 모두 경고 0, 컴파일된 소스는 호스트 파일과 `git_version.cc`뿐, 헤더는 hk와 같음 `[측정]`. 이때의 diff(호스트 파일 하나, 318줄) md5 `a2f84a36f8f217dc358cdddf603e40ae`, 다시 적용 확인과 hr에서의 차례 적용 확인 통과 `[측정]` | 세션 스크래치 `agent_rs/out/` |
| 2026-10-11 | 작업 묶음 1 시험함(CPU 단위 시험, rain, g++ 8.4 ASan과 UBSan; `rs_unit.cc` md5 `068095683531dcace29a0f0331029cb1`): `rs_unit: 600422 checks, 0 failed` `[측정]`. 가짜 기록 묶음(4 rank가 각자 변수로 기록을 만들고, 같은 배열로 rank마다 결정): 모두 failfast, 모두 hold이고 복원 끔(오류 없음), 모두 hold(켤 수 있음), 한 rank 복원 끔(가장 낮은 rank인 경우 포함), 정책 섞임(정책 변수 없음과 모르는 값 포함), failfast 사이의 hold 하나, devComm rank stride 2, symmetric 커널 GIN 켬, strict 비트 0(문맥을 만들지 않는 결정), 투명 복구 꺼짐(magic 0, 기준 질의 실패), `NCCL_GIN_TYPE`, `NCCL_RMA_DISABLE`, 예비 프로세스, 우선순위, 1과 2 rank, 짧은 이유 버퍼, 무작위 기록 묶음 200 000개(규칙과 같은 결정). 모든 경우에 rank마다의 결정과 이유가 바이트 단위로 같고, 무작위 묶음을 포함한 모든 이유에 gpu-detect 채점기 문구(정책 불일치 WARN, hold WARN, 정책 시작 줄, 투명 복구 꺼짐 줄)가 없음. 변수 읽기(`gdakiRsCfgOf`)와 강제 판단(`gdakiRsWinStrict`)도 시험함. 표시 밖의 감싸는 함수(한 번 읽기, 보고 줄)와 실제 등록 길은 시험하지 않음 `[미확인]` | `impl/rs_unit.cc` |
| 2026-10-11 | 작업 묶음 1의 독립 검토(읽기 전용 에이전트, 고정한 사본 대상). 첫 판정: 막는 문제 없음. 기준 넷 모두 통과(fail-fast에서 hk와 같음, 같은 기록이면 모든 rank가 같은 결정, window 등록에 rank 하나만의 오류 없음, 운영 빌드에 시험 스위치로 켤 것 없음). 막지 않는 지적을 반영함: stride 이유 문구(연결이 FULL인지는 communicator의 사실이라 작업 묶음 2에서 넘김), all-gather 전 기준 질의 실패를 기록 비트로(hk는 그때도 magic을 유지), 이유 문구에서 gpu-detect 채점기 문구 빼기, 보고 줄의 RO 비트를 `gdakiRegMr`가 실제로 쓴 access flag에서, 그 GDAKI 문맥을 만들지 않을 때의 WARN 문구(NCCL이 다른 backend로 넘어갈 수 있음), 복원을 요청한 rank는 모든 길에서 결정 한 줄, 예비 프로세스의 WARN 문구. 기록만 하는 것: 정책 변수 값이 127자를 넘으면 WARN에서 잘림, hold 프로세스의 새 로그 줄, 프로세스마다 한 번 읽기(설계대로), 문맥을 만들지 않는 결정은 지금의 어느 빌드로도 생기지 않아 pilot으로는 볼 수 없고 단위 시험만 다룸 `[소스]`, 예비 프로세스 자신의 결정은 작업 묶음 8에서 정함. 재확인(같은 에이전트, diff md5 `a2f84a36`): 반영이 모두 맞고 fail-fast는 hk와 같음(`gdakiRegMr`의 새 출력 인자, fail-fast rank의 `policyPad`는 0). 판정: 막는 문제 없음. 남은 메모 셋: 주석 한 줄이 WARN과 어긋남(동작 없음, 기록한 빌드와 diff를 맞추려고 다음 묶음에서 고침), 빌드 md5 기록(위 행), 무작위 묶음의 채점기 문구 확인(반영함, 위 행의 시험 수) | 세션 스크래치 `agent_rs/review_p1/`, `review_p1b/` |
| 2026-10-11 | 작업 묶음 2(공개 API와 `ncclGinRestoreResume`의 검사)의 충돌 확인(코딩 전): **설계가 풀지 않은 물음 둘이 있어 멈춤, 코드 없음**. (1) 합의 뒤의 지역 실패: 9.10.8절은 "Resume의 오류는 all-gather 뒤의 결정과 같은 기록에서 나온다"로 모든 rank가 같은 오류를 받게 한다. 그러나 같은 GDAKI 문맥 생성 안에서 합의 뒤에 rank마다 따로 일어나는 일이 있다: helper 소켓의 connect, accept, HELLO(`gdakiTsSetup`), 게이트 설정과 NIC 복사 경로의 설정과 자체 시험(`gdakiTsStart`) `[소스]`. 이것이 한 rank에서 실패하면 그 rank만 투명 복구가 꺼지고, 기록에는 없으므로 다른 rank의 Resume은 성공하고 그 communicator는 조용히 무장하지 않는다(사용자 결정의 "모든 rank가 같은 오류"와 어긋남) `[추론]`. 9.14절 작업 묶음 2의 이유 목록에 "투명 복구 꺼짐"이 있어 이 묶음의 범위다. (2) 나머지 무장 조건: 9.10.4절은 "다른 무장 조건은 그대로 WARN과 fail-fast"(문맥 하나, `NCCL_GIN_TS_RECONNECT=1`, 복원 시한과 hold 한도의 관계, NIC 복사 경로, QP 감시, 측 표 포인터, runtime connect와 NVLS, LSA 팀)라 하고, 뒤의 사용자 결정은 "이유가 무엇이든 Resume이 오류"라 하며, 9.14절의 이유 목록은 그 가운데 일부만 든다. 어느 쪽을 따를지 정해지지 않았다. 고를 길(이 에이전트의 제안, 사용자 결정 대기): (가) 두 번째 합의: 첫 결정이 "아무도 요청하지 않음"이 아닐 때만(fail-fast의 선 위 동작은 hk 그대로) 그 GDAKI 문맥 생성의 끝(`gdakiTsStart` 뒤, 아직 문맥 생성 안)에서 GIN collComm all-gather를 한 번 더 해 rank마다 "투명 복구가 아직 켜짐"과 무장 조건의 지역 결과를 싣고, Resume은 두 기록으로 정함. 새 집합 교환이므로 예비 프로세스의 초기화 재생(작업 묶음 8)도 이것을 기록하고 재생해야 함. (나) 한계로 둠: 그 rank의 Resume만 이유와 함께 오류, 다른 rank는 성공하고 무장 합의에서 빠짐(조용히 꺼짐을 받아들임). (다) 무장 조건 가운데 변수로 정해지는 것(`NCCL_GIN_TS_RECONNECT`, `NCCL_GIN_TS_QPWATCH_MS`, 복원 시한과 hold 한도, 문맥 수)은 지금의 기록 비트에 더해 Resume 오류로 하고, 지역 결과(소켓, 게이트, NIC 경로)는 (가)나 (나). 작업 묶음 3(측 표, 루프백 MR)은 이 물음에 기대지 않으나, 측 표 할당 실패도 같은 종류의 지역 결과다 | 9.10.4, 9.10.8, 9.14절 |
| 2026-10-12 | 사용자 결정(메인 세션이 전함, 원문 그대로: "가로가야지"): 작업 묶음 2가 멈춘 물음 둘에 메인 세션의 선택지 (가). `ncclGinRestoreResume`은 모든 rank가 부르는 호출이고, rank마다 지역 판정(설정 때의 지역 결과와 Resume 때의 모든 조건)을 bootstrap으로 모아 모든 rank가 같은 결과와 이유를 돌려준다. 9.10.4절이 WARN과 fail-fast로 남긴 무장 조건은 모두 Resume의 오류가 된다. fail-fast 프로세스는 Resume을 부르지 않아 `hk`와 같다. 이 에이전트가 2026-10-11 행에 낸 (가) 설정 끝의 두 번째 all-gather와 (나) 한계로 둠은 쓰지 않음. 9.10.8절에 결정과 대신하는 것, 9.10.4절 머리에 바뀐 규칙, 9.14절 2번(바뀐 내용), 3번(측 표와 복원 버퍼, 문맥 뒤 window를 Resume 판정에 더함), 8번(예비 프로세스의 Resume 모음을 초기화 기록으로 대답)에 적음 | 9.10.4, 9.10.8, 9.14절 |
| 2026-10-12 | 작업 묶음 2의 충돌 확인(새 설계 아래, 코딩 전). 결과: 설계가 풀지 못한 충돌 없음. 정한 것과 근거: (1) Resume을 부르지 않는 rank: 모음은 `bootstrapAllGather`(고리, 시간 제한 없음)이고 그 소켓 고리는 communicator의 abort 깃발을 보면 끝난다 `[소스: misc/socket.cc 459–463, 511–514, bootstrap.cc의 net 길 checkAbort]`. 그래서 한도 `NCCL_GIN_RESTORE_RESUME_MS`(기본 30 000 ms)를 넘으면 Resume이 abort 깃발(호스트와 장치, 자식 communicator의 것; `ncclCommAbort`의 첫 걸음과 같음)을 세워 모음을 풀고 `ncclSystemError`와 고정 문구를 돌려준다. 고리가 어긋났으므로 그 communicator는 `ncclCommAbort`로만 끝낸다(9.10.8절이 strict 비트의 오류에 쓴 "그 communicator는 끝"과 같은 뜻). 부른 rank는 모두 한도 안에 오류를 받는다. 한도 끝에 늦게 온 rank는 모음이 끝나지 못해 자기 한도에서 오류다. 남는 경합: 한도의 마지막 순간에 도착하면 일부 rank는 모음을 끝내고 일부는 한도로 끝날 수 있다 `[추론]`(끝낸 rank는 상대의 abort를 실행 중 장애로 본다). 자원을 나누는 split의 자식은 abort 깃발을 나눠 함께 끝난다(이 실험은 split을 쓰지 않음). (2) 장애가 이미 application에 닿은 뒤의 Resume: 지역 판정 "이미 닿음"(communicator의 대기 단어, degraded 예약, GIN 비동기 오류)으로 모든 rank의 오류. (3) 두 번 부름: 첫 결과를 모음 없이 돌려줌(멈춤 없음). (4) 예비 프로세스의 초기화 재생: 그때 생존 rank는 Resume을 부르지 않으므로 작업 묶음 8에서 원래 rank의 첫 Resume 모음 결과를 기록에 넣고 예비 프로세스가 그것으로 대답(9.14절 8번에 적음). (5) bootstrap을 쓰는 때: Resume은 application 스레드의 차례 있는 집합 호출이다(다른 NCCL 호출과 같은 규칙: 모든 rank가 같은 차례로, 같은 communicator에 동시에 부르지 않음). NCCL 안의 다른 bootstrap 사용도 application 스레드의 집합 호출이고, GDAKI helper는 bootstrap을 쓰지 않는다(GIN collComm과 자기 소켓) `[소스: bootstrap 호출 자리 grep]`. (6) helper 스레드와의 안전: Resume은 GDAKI 문맥을 `gdakiRecRegMu` 안에서 읽고(`ncclGinGetRecoveryStats`와 같음), helper가 쓰는 값은 원자 칸(active, dead, escalated)이나 helper 시작 전에 정해진 값(QP 감시 주기, hold 한도)만 읽고, NIC 복사 경로의 깃발은 원자 읽기로 읽음. 대기 단어는 `gdakiUaMu` 안에서. 두 잠금을 한꺼번에 잡지 않음(`ncclGinTsUserAbortWord`가 거꾸로 잡으므로). Resume이 쓰는 등록부는 helper가 읽지 않음. (7) `ncclGetLastError`: 이유는 돌아가기 바로 전 호출한 스레드의 WARN 글이다. 마지막 오류 글은 프로세스에 하나라 그 사이 다른 스레드의 WARN이 덮을 수 있음(한계). (8) 규칙의 예외: 공개 API의 입구는 `nccl.h.in`, `gin/gin_host.cc`(communicator와 devComm의 사실, bootstrap 모음, abort 깃발), `include/gin/gin_host.h`(그 둘을 잇는 구조체 하나와 함수 선언 하나). 판정과 정하기, `ncclGinRestoreStep`과 `ncclGinRestoreRegister`의 자리는 호스트 파일. (9) 9.10.4절 조건 가운데 측 표, 복원 버퍼의 루프백 MR, 사용자 문맥 뒤의 사용자 window는 작업 묶음 3에서 더함. 복원 시한과 hold 한도는 우선 "`NCCL_GIN_RESTORE_MS`(기본 20 000)가 0보다 크고 `NCCL_GIN_TS_HOLD_MS`보다 작음" | 9.10.4, 9.10.8, 9.14절 |
| 2026-10-12 | 작업 묶음 2 구현. (가) `nccl.h.in`: `ncclGinRestoreResume(comm, devComm, &step, blob, &bytes)`, `ncclGinRestoreStep`, `ncclGinRestoreRegister`와 `pnccl` 짝, 쓰는 법의 주석(모든 rank가 부름, 결과 셋, 이유는 `ncclGetLastError`). (나) `gin/gin_host.cc`: 입구. communicator와 devComm의 사실(devComm의 GIN backend 종류, GIN 연결 수와 handle, communicator의 GIN 연결이 FULL인지, devComm의 GIN context stride, host RMA 문맥 수, runtime connect, NVLS, devComm의 LSA 팀 크기, symmetric 커널의 GIN devComm)과 bootstrap all-gather, abort 깃발 세우기를 호스트 파일에 넘김. `include/gin/gin_host.h`: 그 사실의 구조체와 함수 선언. (다) 호스트 파일: 지역 판정(정한 차례의 조건 스물둘: 인자, devComm이 다른 판의 장치 헤더로 쓰임, 이미 닿은 장애, 예비 프로세스, GIN 연결 없음, GDAKI 아님, FULL 아님, stride, GIN 연결 둘 이상, host RMA, runtime connect, NVLS, LSA 팀, symmetric 커널의 GIN devComm, 투명 복구 꺼짐, 문맥 둘 이상, 합의 뒤 꺼짐(까닭과 함께), 재연결 변수, QP 감시, 복원 시한과 hold 한도, NIC 복사 경로, 확대 상한), 고정 크기 기록 하나(요청, 정책, 설정 결정과 이유, 지역 판정과 이유), 한도 있는 모음, 정하기(아무도 요청 안 함 → 성공; 요청이 다름; 설정 결정의 거절; 가장 낮은 rank의 지역 거절; 켤 수 있음). 지역 문구에는 rank 번호가 없고 정하기가 "rank p: "를 붙임. 설정 결정과 합의 뒤 꺼진 까닭(설정의 connect, accept, HELLO 실패와 게이트 설정 실패)은 등록부에 두고(아무도 요청하지 않으면 두지 않음), 그 GDAKI 문맥을 없앨 때와 communicator를 정리할 때 지움. 두 번째 호출은 첫 결과. 켤 수 있으면 첫 화신(단계 0, 덩어리 0바이트)이고 붙잡기 반응이 아직 없어 fail-fast로 남는다는 줄 하나. (라) `ncclGinRestoreStep`, `ncclGinRestoreRegister`: 이 빌드에 아직 없다는 WARN과 `ncclInvalidUsage`. (마) 작업 묶음 1 검토의 남은 메모(주석 한 줄)를 고침. 검토를 반영해 더한 것(아래 검토 행): 입구가 `ncclCommEnsureReady`처럼 돌아가지 않고 communicator의 비동기 오류(와 그 질의의 실패)를 지역 판정 "이미 닿은 장애"로 모음에 실음(먼저 돌아가는 것은 잘못된 comm, 초기화가 실패한 communicator(그 오류), 아직 끝나지 않은 nonblocking 작업뿐), devComm의 magic과 판이 이 라이브러리의 것이 아니면 다른 칸을 읽지 않고 지역 거절, 저장한 Resume 결과는 communicator마다 하나(주소, commHash, bootstrap 상태로 알아봄), 자식 abort 깃발 포인터는 한 번 원자 읽기, 한도는 하루로 자름, 설정 등록 실패 길도 꺼진 까닭을 남김, `nccl.h`의 설명(나누는 abort 깃발, 한도 ≤ 0은 없음, 끝의 경합, 먼저 돌아가는 경우, group 안에서 부르지 않음, 마지막 오류 글). fail-fast(Resume을 부르지 않는 프로세스)에서 바뀌는 것: 정리 때 빈 등록부를 훑는 것(잠금 하나)뿐 `[소스]` | `impl/rs_layer.diff` |
| 2026-10-12 | 작업 묶음 2 빌드됨(rain, nice 19, ionice idle; 실행 안 함). 마지막 빌드: 연구 `out/rs_p2d` libnccl `105a68a5f9d6332925b65936a9378f0f`, 운영 `out/rsp_p2d` `1902c01fd2b1827d5415448f58cdcf01`, 이 계층의 파일에서 경고 0 `[측정]`. `nccl.h.in`을 바꿔 처음 다시 빌드할 때 호스트 파일 185개가 다시 컴파일되었고 그때 경고는 손대지 않은 `scheduler/symmetric_sched.cc:327` 하나뿐이다(v2.32.3-1 원본 그대로의 줄, 다른 실험의 예전 전체 빌드 기록에도 같은 경고) `[측정]`. 장치 코드는 다시 컴파일되지 않음(장치 객체가 `nccl.h`에 기대지 않음) `[측정: 의존 파일]`. 검토 전 빌드(`rs_p2` `dfa61319`, `rsp_p2` `a0a2fdcb`)와 반영 중의 빌드(`rs_p2b` `1db0fe59`, `rsp_p2b` `c1201716`; `rs_p2c` `b31d85a0`, `rsp_p2c` `116ac40d`)는 폴더에 그대로 둠(배포하지 않음). 이때의 diff(파일 넷, 978줄) md5 `13563bf6b271a1d1bbd7d6da6b317a6e`, 다시 적용 확인과 hr에서의 차례 적용 확인 통과 `[측정]`. 장치 헤더는 그대로(include 차이는 `nccl.h`와 그 생성본뿐) | 세션 스크래치 `agent_rs/out/` |
| 2026-10-12 | 작업 묶음 2 시험함(CPU 단위 시험, rain, g++ 8.4 ASan과 UBSan, 스레드): `rs_unit: 967454 checks, 0 failed`, 네 번 되풀이해 같음 `[측정]`. 더한 시험: 지역 판정의 조건 스물둘을 하나씩(제 번호와 문구, rank 번호 없음, 채점기 문구 없음)과 한꺼번에(첫 조건이 이김), 모음 정하기(아무도 요청 안 함, 요청이 다름, 설정 결정의 거절과 문맥을 만들지 않은 결정, 가장 낮은 rank의 지역 거절, 다른 라이브러리의 기록, 꽉 찬 문구 칸), 무작위 기록 묶음 50 000개(규칙의 차례와 같은 결정, 모든 rank의 문구가 같음), 스레드 넷이 흉내 낸 bootstrap 모음(같은 결과와 문구, abort 없음), 한 rank가 부르지 않을 때(나머지 셋이 한도 300 ms 안팎에 끝나고 저마다 abort를 한 번), 늦게 온 rank(이미 깨진 고리라 자기 한도에서 끝), 한도 없음, 한도 끝에서 끝나는 모음(끝났으면 abort 없음, 한도면 abort 한 번) 200번. 시험하지 않은 것 `[미확인]`: 입구와 등록부를 잇는 코드(두 번째 호출, 저장한 결과, 비동기 오류와 초기화 실패 길), 실제 bootstrap(흉내 낸 모음은 모두 끝나거나 아무도 못 끝냄; 실제 고리에서 일부만 끝나는 경합은 위 한계) | `impl/rs_unit.cc` |
| 2026-10-12 | 작업 묶음 2의 독립 검토(읽기 전용 에이전트, 고정한 사본 `review_p2`, diff md5 `c62f649c`). 첫 판정: 막는 문제 하나. 비동기 오류가 이미 선 rank는 입구의 `ncclCommEnsureReady`에서 모음 없이 돌아가 다른 rank가 한도까지 기다리고 다른 이유로 끝남(설계의 "이미 닿은 장애는 모든 rank에 같은 Resume 오류"와 어긋남). 막지 않는 것: 두 번째 호출이 devComm마다였음, 같은 주소의 다음 communicator가 옛 결과를 받을 수 있음, 6절 설정에 `NCCL_NUM_RMA_CTX=0`이 없어 Resume이 늘 "host RMA is on"으로 거절할 것(host RMA 문맥 기본 1, `NCCL_RMA_DISABLE`은 proxy만 끔) `[소스]`, 다른 판의 devComm 배치, `nccl.h` 설명, 자식 abort 깃발 포인터. 모두 반영(위 구현 행, 6절에 `NCCL_NUM_RMA_CTX=0`과 GIN 연결 하나). 재확인(`review_p2b`, `69bb2547`): 판정 막는 문제 없음, 막지 않는 둘(초기화가 실패한 communicator에서 Resume이 NULL을 읽을 수 있음, 비동기 오류 질의 자체의 실패) 반영. 그 확인(`review_p2c`, `49f31845`): 막는 문제 없음, 메모 하나(abort 깃발이 선 뒤에는 nonblocking 초기화를 기다린 다음 초기화 상태를 읽음)를 반영하고 같은 에이전트가 다시 확인(`13563bf6`): 막는 문제 없음. 기준별: fail-fast는 `hk`와 같음, 같은 기록이면 모든 rank가 같은 결과와 문구, 한도 있는 기다림이 맞음(abort 깃발이 bootstrap 소켓 고리를 끝냄 `[소스: os/linux.cc 375–378, bootstrap.cc 206]`), 교착 없음(잠금 셋을 하나씩), 운영 빌드에 시험 스위치 없음, 9.10.4절에서 Resume 때 볼 수 있는 조건을 모두 덮음 | 세션 스크래치 `agent_rs/review_p2/`, `review_p2b/`, `review_p2c/` |
| 2026-10-12 | 작업 묶음 3(측 표, GPU 문맥 판, 복원 버퍼의 루프백 MR, 자원 window)의 충돌 확인(코딩 전): **설계가 풀지 못한 충돌 하나로 멈춤, 코드 없음**. 9.11.5절의 GPU 문맥 판 행과 9.9절 장치 쪽 첫 행(측 표 포인터 칸)은 측 표 포인터를 `ncclGinGdakiGPUContext`에 더하고 "판을 3으로 올리고 판 2 formatter를 남김, 판 2 바이너리는 fail-fast"로 옛 헤더로 빌드한 프로그램이 문맥 배열을 잘못 세는 것을 막는다고 적었다. 그러나 라이브러리가 고르는 판은 프로그램의 장치 코드 판(`reqs->version` = 컴파일 때의 `NCCL_VERSION_CODE`)을 판마다의 최소 NCCL 판 표와 견주어 정하고(`gin/gin_host.cc` 41–43, 318–323; `dev_runtime.cc` 2016–2019), `hk` 헤더로 빌드한 프로그램과 이 계층의 헤더로 빌드한 프로그램은 둘 다 2.32.3이다(`makefiles/version.mk`) `[소스]`. 그래서 라이브러리는 두 헤더를 가를 수 없고 판 3은 2.32.3 프로그램에 닿지 않는다. 앞선 연구 계층도 이 구조체에 분류 블록 포인터(`fault`)를 판을 바꾸지 않고 끝에 더했다(커밋 "stack: inject + q4 + rec v1 + gpudb v2") `[소스]`. 고를 길(사용자 결정 대기): (가) 판을 바꾸지 않고 구조체 끝에 측 표 포인터를 더함(앞선 계층과 같은 방식): 이 라이브러리와 쓰는 모든 프로그램과 드라이버(gin-remaining, gpu-detect 회귀 셀의 드라이버 포함)를 이 계층의 헤더로 다시 빌드해야 하고, 옛 헤더로 빌드한 문맥 둘 이상의 프로그램은 1번 문맥부터 잘못 읽음(지원하지 않음, 문서화). 회귀 셀이 이 계층의 장치 코드를 재려면 어차피 다시 빌드해야 함. (나) 문맥 배열의 배치는 그대로 두고 측 표 포인터를 분류 블록(`struct ncclGinGdakiQ4`, GDAKI 문맥마다 하나, 라이브러리가 장치 메모리에 할당) 끝에 둠: 보내기 길은 게이트 진입에 이미 `gdaki->fault`를 읽으므로(`gin_gdaki.h` 501, 604, 704) 더해지는 것은 그 블록에서 포인터 하나를 더 읽는 것(게이트가 켜졌을 때만; 투명 복구는 분류를 요구하므로 그때 블록은 늘 있음)이고, 옛 헤더 프로그램은 새 칸을 읽지 않아 그대로 돈다. 9.11.12절의 키 읽기 자리 결정 (나)가 받아들인 fail-fast 비용(포인터 읽기 하나와 분기 하나)과 같은 수이나, 그 읽기가 블록 포인터 읽기에 기대는 점이 다르다(재야 함). (다) 라이브러리가 볼 수 있는 헤더 표시를 더함(예: devComm 요구 구조체에 칸 하나): NCCL 공개 장치 API 헤더와 그 호환 논리를 건드림. 이 에이전트의 생각: (나)가 배치와 호환 문제를 없애고 비용 모양도 결정과 가깝다. 같은 확인에서 걸리지 않은 것: 측 표 할당과 포인터의 동기 H2D는 `gdakiTsStart`(문맥 생성 안, 돌아가기 전)에서 가능, fail-fast에서 포인터 0; 루프백 MR에 넣을 버퍼(사용자 문맥 전에 등록한 window의 rkey 표는 복원을 요청한 프로세스에서 `ncclGinGdakiRegMrSym`이 적어 둠, 신호와 카운터 표, 로그 고리, 측 표); 자원 window는 Resume에서 그 주소로 찾아 더함(NIC 경로의 MR 목록은 helper가 잠금 없이 읽으므로, 9.10.8절이 정한 새 잠금은 복원을 요청한 프로세스에서만 잡거나 미리 자리를 잡아 원자 개수로 내놓는 식으로 fail-fast의 읽기 길을 그대로 둠); Resume의 지역 판정에 더할 셋(측 표 할당 실패, 복원 버퍼가 루프백 MR에 없음, 사용자 문맥 뒤에 등록한 사용자 window) | 9.9, 9.11.5, 9.14절 |
| 2026-10-12 | 사용자 결정(메인 세션이 전함, 원문 그대로: "가로 해야지"): 작업 묶음 3이 멈춘 물음에 이 에이전트의 고를 길 (가). 측 표 포인터를 `ncclGinGdakiGPUContext` 끝에 GPU 문맥 판을 바꾸지 않고 더한다(앞선 연구 계층이 분류 블록 포인터를 더한 방식). 뒤따르는 것: 이 라이브러리와 쓰는 모든 프로그램은 이 계층의 헤더로 빌드한다(gin-remaining과 gpu-detect 회귀 셀의 드라이버 포함, 이 계층의 장치 코드를 재려면 어차피 다시 빌드함). 옛 헤더로 빌드한 문맥 둘 이상의 프로그램은 1번 문맥부터 잘못 읽는다(지원하지 않음, 문서화). 판 3 계획을 대신하고, 고를 길 (나) 분류 블록에 둠과 (다) 헤더 표시를 더함은 쓰지 않음. 9.11.5절 GPU 문맥 판 행, 9.9절 측 표 포인터 행, 9.14절 3번에 적음 | 9.9, 9.11.5, 9.14절 |
| 2026-10-12 | 작업 묶음 3의 충돌 확인(새 결정 아래, 코딩 전). 결과: 설계가 풀지 못한 충돌 없음. (1) fail-fast 장치 동작: 측 표 포인터는 0이다. GPU 문맥 배열의 호스트 사본은 `calloc`이고 문맥 생성에서 장치로 복사되며 `[소스]`, 이 계층은 복원을 요청한 프로세스에서만, 게이트가 선 뒤 helper가 시작하기 전에 그 칸을 쓴다. 이 묶음에서 그 칸을 읽는 장치 코드는 없다. 장치에 보이는 차이는 구조체 크기 하나라 이 헤더로 빌드한 프로그램의 문맥 간격이 바뀌고, 라이브러리 안의 장치 객체는 이 헤더에 기대지 않는다 `[측정: 의존 파일]`. 기계어 비교로 확인한다(아래 시험 행). (2) 옛 헤더 프로그램을 Resume에서 알아보는 것: 프로그램의 구조체 크기나 헤더 요약을 알려 주는 칸이 없어 값싸지 않음, 넣지 않고 문서화(`nccl.h`와 장치 헤더의 주석). (3) NIC 복사 경로의 MR 목록: helper가 잠금 없이 읽는다. 복원을 요청한 프로세스에서만 설정 끝에 목록의 자리를 미리 잡고(항목이 옮겨지지 않음; helper는 찾은 항목의 포인터를 들고 전송함) 그 뒤의 찾기와 Resume의 더하기가 새 잠금을 잡는다. fail-fast는 잠금도 예약도 없음. (4) 측 표 할당과 동기 H2D: 문맥 생성 안(`gdakiTsStart`, 돌아가기 전)이라 어느 커널도 아직 이 문맥을 쓰지 못한다. 포인터를 마지막에 써서 실패하면 0으로 남는다. 할당은 복구 host가 갖고 NIC 경로의 MR을 푼 뒤에 놓으므로 문맥의 포인터가 해제된 메모리를 가리키지 않는다. GPU 문맥 판 1 프로그램에는 쓰지 않음. (5) Resume의 검사 셋과 자원 window: 위 판정에 더함(측 표, 복원 버퍼가 NIC 경로에 있음과 측 표의 fence 낱말을 NIC으로 다시 읽음, 문맥 뒤에 등록한 window와 그 사이 해제된 window). 자원 window는 devComm이 만드는 주소(`add4G(lsaFlatBase, lsaRank × stride4G)`, `dev_runtime.cc`)로 찾아 잠금 안에서 더함. (6) BAR1: 로그 고리는 변수(`NCCL_GIN_RESTORE_LOG_ENTRIES` 기본 4 096, `NCCL_GIN_RESTORE_LOG_BYTES` 기본 1 MiB, QP마다)로 정하고 rain에서의 여유는 pilot이 본다 `[미확인]` | 9.9, 9.10.4, 9.10.8, 9.11.4, 9.11.5, 9.14절 |
| 2026-10-12 | 작업 묶음 3 구현. (가) 장치와 호스트가 함께 쓰는 헤더: `ncclGinGdakiGPUContext` 끝에 `restore`(측 표 포인터, 판 그대로), 측 표의 머리(64바이트: magic, QP 수, drain 확인의 fence 낱말)와 QP마다의 항목(128바이트: 연구의 시제품 로그 고리 형식을 따른 자리, 로그 켬 낱말, 억제 예산). 크기는 정적 확인. (나) 호스트 파일: 복원을 요청한 프로세스에서 게이트 뒤 helper 전에 (1) 장치 할당 하나(4 KiB 정렬, 쪽 단위 크기)에 측 표와, 게이트가 선 상대의 QP마다 항목 고리와 내용 고리를 두고 0으로, (2) 그 할당, 신호와 카운터 표와 그 rkey 표, 이 문맥 전에 같은 collComm에 등록한 window의 rkey 표를 NIC 복사 경로의 MR에 넣고 측 표의 fence 낱말을 NIC으로 다시 읽음, 목록 자리 예약과 잠금 켬, (3) 측 표 주소를 장치 배열의 모든 문맥에 동기 복사로 쓰고 호스트 사본에도(마지막 걸음). window 등록과 해제를 적는 등록부(복원을 요청한 프로세스만, collComm 정리 때 지움). Resume의 지역 판정에 다섯을 더함(측 표, 복원 버퍼, 문맥 뒤 window, 해제된 window, 자원 window를 더하지 못함)과 자원 window 더하기(window의 분류는 순수 함수로 떼어 시험함). 할당은 문맥을 남기는 검사 뒤에 놓음. (다) `gin/gin_host.cc`: devComm의 자원 window 주소를 사실에 더함. (라) 빌드 스크립트: 파일 목록에 장치와 호스트가 함께 쓰는 헤더, 그리고 장치 헤더 나무(`src/include/nccl_device`)가 그 빌드 폴더의 지난 빌드 때와 다르면 장치 객체를 지우고 모두 다시 빌드(아래 검토 행의 막는 문제). fail-fast에서 바뀌는 것: 장치에는 구조체 크기(문맥 간격), 호스트에는 MR 찾기의 거짓 분기 하나와 정리 때 빈 목록 훑기 `[소스]` | `impl/rs_layer.diff` |
| 2026-10-12 | 작업 묶음 3 빌드됨(rain, nice 19, ionice idle; sm_75와 sm_86; 실행 안 함). 마지막 빌드: 연구 `out/rs_p3b` libnccl `c3ebd12fd840281b3a3757466d411ffe`, 운영 `out/rsp_p3b` `d0cfc1c2081445f57f93e2f2d1fe5f5b`, 각각 206개 컴파일(장치 객체 모두), 경고 0, 걸린 시간 약 7분 `[측정]`. 검토 전 빌드(`rs_p3` `cad3e508`, `rsp_p3` `02a30ffc`)는 장치 객체를 다시 컴파일하지 않은 것이라 쓰지 않음(아래 검토 행; 폴더에 그대로 둠, 배포하지 않음). 이때의 diff(파일 다섯, 1 470줄) md5 `93da2cf9a28b15ce3e64b195f2df8b25`, 다시 적용 확인과 hr에서의 차례 적용 확인 통과 `[측정]` | 세션 스크래치 `agent_rs/out/` |
| 2026-10-12 | 작업 묶음 3 시험함. (1) CPU 단위 시험: `rs_unit: 967952 checks, 0 failed`(측 표 배치: 2의 거듭제곱으로 내림, 한계, 고리 256바이트 정렬, 할당 크기는 쪽 단위; window 분류: 문맥 뒤, 그 사이 해제, 자원 window를 주소로 찾음; 지역 판정의 새 조건 다섯과 그 차례) `[측정]`. (2) fail-fast 장치 동작의 기계어 비교(GPU에서 돌리지 않음; 스크래치 `agent_rs/sass/`): (가) gin-remaining의 드라이버 `gin_ts2.cu`, `remaining/gin_mr.cu`, NCCL 예제 `09_gin_optimizations/01_ring_exchange`를 `hk` 헤더와 이 계층의 헤더로 sm_75와 sm_86에 컴파일해 SASS를 줄마다 견줌(`sass_cmp.py`): 줄 수가 같고, 다른 명령은 모두 문맥 간격의 즉시값뿐(0x60 → 0x68, 컴파일러가 0x50 + 0x10으로 나눈 곳은 0x10 → 0x18; gin_ts2 16, gin_mr 18, ring 8), 새 읽기나 명령 없음 `[측정]`. (나) 라이브러리 안의 장치 객체 207개를 `hk` 빌드와 견줌(`obj_cmp.sh`): 183개는 SASS가 같고, `device_glue.o`와 `onerank.cu.o`는 컴파일마다 달라지는 내부 이름의 해시만 다름(정규화하면 같음), 나머지 22개는 NCCL의 symmetric GIN 커널(AllGather, ReduceScatter의 Rail 커널)로 다시 컴파일되어 레지스터 배치가 달라짐. 그 22개의 생성 소스 31개(두 트리에서 같음)를 두 헤더로 compute_75와 compute_86 PTX로 만들어 견줌(`ptx/ptx_cmp.py`, 내부 이름 해시와 단언 문구 속 빌드 경로를 정규화): 62쌍 모두 다른 줄은 문맥 간격 96 → 104뿐(28개 파일에 292줄), 그 밖은 0 `[측정]`. 이 주장은 sm_75와 sm_86(이 실험의 두 GPU)에 한한다: FP8의 RailA2A LsaLDMC 커널 8개는 sm_100a로만 컴파일되고 그 SASS는 간격 밖으로도 달라졌다(문맥 배열의 32바이트 정렬이 깨진 탓으로 봄 `[추론]`; 이 노드에서는 돌지 않음). (다) 라이브러리 전체 SASS에서 Rail symmetric 커널의 문맥 간격 곱: `hk` 0x60 556곳, 검토 전 `rs_p3` 0x60 556곳(낡은 장치 코드), `rs_p3b`와 `rsp_p3b` 0x68 556곳, 0x60 0곳 `[측정]` | `impl/rs_unit.cc`, 비교 도구 [impl/sass_cmp.py](impl/sass_cmp.py), [impl/obj_cmp.sh](impl/obj_cmp.sh), [impl/ptx_mk.sh](impl/ptx_mk.sh), [impl/ptx_cmp.py](impl/ptx_cmp.py), 출력은 세션 스크래치 `agent_rs/sass/` |
| 2026-10-12 | 작업 묶음 3의 독립 검토(읽기 전용 에이전트, 고정한 사본 `review_p3`, diff md5 `92d58b3e`). 첫 판정: 막는 문제 하나. NCCL의 장치 의존 규칙(`src/device/Makefile`의 `nvcc -MM -dc`)은 장치 컴파일에서만 포함되는 헤더(`__CUDACC__`, `__CUDA_ARCH__` 아래의 GIN 장치 헤더)를 보지 못해, 첫 빌드(`rs_p3`, `rsp_p3`)에서 symmetric GIN 커널 22개가 다시 컴파일되지 않았고 옛 문맥 간격(0x60)으로 새 배치(0x68)를 읽었다 `[소스, 측정]`(fail-fast에서도, symmetric 커널의 GIN이 켜졌을 때 1번 이후 문맥). 반영: 빌드 스크립트가 장치 헤더 나무의 요약을 빌드 폴더마다 적고 다르면 장치 객체를 지운 뒤 빌드, 새 빌드 `rs_p3b`, `rsp_p3b`와 위 기계어 비교 셋. 막지 않는 지적 반영: 측 표 할당을 쪽 정렬(NIC 경로가 쪽 단위로 등록), window 분류를 순수 함수로 떼어 시험, 할당을 문맥을 남기는 검사 뒤에 놓음, 9.10.4절과 9.11.9절의 "판 3" 글에 날짜 붙인 메모. 기록만 하는 것: BAR1(복원을 요청한 프로세스는 측 표와 로그 고리 QP마다 기본 1.25 MiB와 신호, 카운터 표와 rkey 표, window rkey 표를 NIC 경로의 MR로 더 등록함; 이미 GIN에 등록한 쪽을 다시 등록할 때 BAR1을 더 쓰는지 `[미확인]`; pilot이 BAR1 Used를 앞뒤로 적음), window를 해제해도 그 rkey 표의 루프백 MR과 등록부 항목은 문맥이 끝날 때까지 남음(Resume은 해제된 window가 있으면 거절하므로 이 묶음에서는 무해; 체크포인트 묶음에서 9.11.4절 T5대로 DISARM 뒤 해제), 포인터는 설정 합의가 거절해도 복원을 요청한 프로세스면 씀(설계의 "hold 정책이면 0이 아님"과 같음; 장치 보내기 길 묶음 전에 다시 볼 수 있음). 재확인(`review_p3b`, `93da2cf9`): 막는 문제 없음. 장치 코드가 든 객체는 `obj/device`와 `obj/diagnostics/device`뿐이라 다시 빌드 범위가 빠짐없음, symmetric GIN 객체 30개의 문맥 간격 곱 512곳이 모두 0x68, 나머지 객체는 함수마다 같음(내부 이름 해시를 정규화하면), PTX 비교 재현. 메모 둘 반영: 빌드 스크립트의 요약에 DOCA 장치 헤더 나무를 더함(요약 공식이 바뀌어 다음 빌드에서 장치 객체를 한 번 더 다시 빌드함), 기계어 주장을 sm_75와 sm_86으로 한정 | 세션 스크래치 `agent_rs/review_p3/`, `review_p3b/`, `agent_rs/sass/` |

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
- strict 강제(9.10.8절)는 MR의 RO 비트만 뺀다. HCA의 펌웨어 설정이 MR과 상관없이 relaxed 쓰기를 강제하는 경우(`PCI_WR_ORDERING`의 force relax)는 사용자
  공간에서 알아낼 길을 찾지 못해 막지 못한다 `[미확인]`(2026-10-11 충돌 검토 K11 (h)). 이 실험의 두 NIC는 2026-10-11 sudo 읽기로 `per_mkey(0)`(강제 안 함)임을
  확인했다 `[측정]`. 다른 기계에는 한계로 남고, sudo 읽기 한 번(`mlxconfig -d <bdf> q PCI_WR_ORDERING`)이면 풀린다.

## 19. 다음 작업

- 막는 문제를 먼저 푼다(9.11.12절).
- gpu-detect 계층이 확정되면 그 위에 9.9절 계층을 만든다.

## 20. 참고자료

- `../remaining/EXPERIMENT.md` 9절 1번 (c)(degraded), (f)(재리뷰 M-A, L-C, M-C), 15, 17–19절
- `../peer/EXPERIMENT.md`(상대별 단어), `../multirank/EXPERIMENT.md`(랭크 4개, GPU 나눠 쓰기), `../handoff/EXPERIMENT.md`(shrink 넘기기, CUDA 호출)
- gpu-detect `harness/gpu-detect/EXPERIMENT.md` 9.1절(hw), 9.2절(t1w), 18, 19절(이 설계를 쓸 때는 gpu-detect worktree의 초안, 2026-10-11 master, PR #63)
- 9.12절의 논문들 `[미확인]`
