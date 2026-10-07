# GIN 투명 복구 2단계 마감 (gin-s2-close)

**목적:** GIN 투명 복구 2단계의 남은 항목 가운데 하루에 끝낼 수 있는 네 가지를 사전 등록한 예측으로 잰다. 네 가지는
다음과 같다.

1. 중간 빌드에서만 잰 결과를 최종 빌드에서 다시 잰다.
2. 거절 뒤 받는 쪽 자기 signal 대기를 abort로 푼다.
3. 다시 보낼 수 없는 라운드를 거절하는지 확인한다.
4. 관리망 소켓이 끊길 때의 현재 정책을 잰다.

| 항목 | 값 |
|---|---|
| 상태 | `QA` |
| 담당자 | @unionxic |
| 작성일 | 2026-10-07 |
| 기준 브랜치와 커밋 | `exp/gin-s2-close` @ `3dbf995e` (master) |
| 사전 등록 태그 | `prereg/gin-s2-close-v1` (상태를 `PREREGISTERED`로 바꾼 바로 그 커밋) |
| 마지막 갱신 | 2026-10-07 20:50, 본 실행 끝, 채점, 상태 `QA` |

표시: `[측정]` 원자료에서 확인, `[소스]` 코드에서 읽음, `[추론]` 해석, `[미확인]` 확인 안 함.

이 문서의 소스 줄 번호는 2단계 소스 트리 기준이다. 그 트리는 pristine NCCL v2.32.3-1에 `../gin_transparent_s2.diff`를
적용한 것과 같다. 세션 스크래치의 트리(`agent_ts2/nccl-src`)와 이 diff의 본문 md5가 같다(`5c8a53f7`) `[측정]`.

장애 기호와 셀 이름은 원자료를 찾는 키로만 괄호나 표의 id 열에 둔다. 장애 기호는 다음과 같다.

| 장애 | 기호 |
|---|---|
| 로컬 QP 오류 | F1 |
| 원격 접근 오류 | F2 |
| 상대 QP 오류 | F3 |
| 상대 프로세스 kill | F4 |

빌드 키는 세 가지다.

| 빌드 | 키 | 내용 |
|---|---|---|
| 최종 빌드 | `s2` | 2단계 최종 libnccl `0a32b875`와 드라이버 `d4b1f082` |
| 새 라이브러리 빌드 | `s2r` | 3절 변경을 넣은 libnccl과 최종 드라이버 사본 |
| get 드라이버 빌드 | `s2rget` | 새 libnccl과 get 모드를 넣은 드라이버 |

## 1. 배경과 연구 질문

**2단계가 멈춘 지점.**
- 폴더 README는 "남은 항목은 PR #7"이라고 적는다(`../README.md` 91행).
- PR #7은 2026-10-06 05:27 UTC에 합쳐졌다. 본문의 확인 목록 다섯 줄은 모두 체크되지 않았다 `[측정: gh pr view 7]`.
- 이번 실험은 그 목록과 `../TRANSPARENT_S2.md`의 한계 절(381–422행)에서 하루에 끝낼 수 있는 것만 다룬다.
- 문서 정리는 별도 커밋으로 한다(4절).

**중간 빌드에서만 잰 결과.** Release `data-20261006`의 2단계 원자료를 받아 다시 세었다 `[측정]`. sha256 앞 12자는
`f628df6c6b48`로 `DATA.md`와 같다.
- 16, 64 스레드 로컬 QP 오류 10회씩은 중간 빌드 폴더(`prev_6ff74bb6/b/`)에만 있다. 이를 잰 hold는 10-01
  11:52–11:54에 돌았고, 최종 빌드는 12:16에 나왔다.
- 실제 양방향 트래픽의 동시 시작 칸도 중간 빌드 폴더(`prev_6ff74bb6/c/`, 12:14–12:15)에만 있다.
- 지연 표는 09:45–09:52(중간 빌드)에 쟀다.
- 그런데 `../TRANSPARENT_S2.md`는 앞의 두 결과를 "final build"로 적는다.

**받는 쪽이 풀리지 않는다.**
- 최종 빌드에서 원격 접근 오류(F2)를 거절한 뒤 받는 쪽(rank 1)의 `ncclCommAbort`가 돌아온 것은 0/10이었다. 링을 가득
  채운 같은 장애에서도 0/10이었다. 모두 앱 감시가 끝냈다(종료 코드 7) `[측정: 위 원자료를 다시 셈]`.
- 원인 `[소스]`:
  - 사용자 devComm은 abort 플래그가 null이다(`dev_runtime.cc` 1510행 `if (isInternal)`).
  - 모든 GIN 대기는 그 플래그를 1만 번 회전마다 읽는다. `waitRollingLessEq`(`gin__funcs.h` 85–103행)와
    `testAbort`(`utility.h` 79–87행)가 그렇다.
  - `ncclCommAbort`는 `abortFlagDev`를 세우지만(`init.cc` 3507행) 그 신호가 사용자 커널에 닿지 않는다. 정리 단계는
    커널이 끝나기를 기다린다.
- `MODEL.md` 규칙 4(완료를 받지 않는 쪽은 장애를 모른다)에서 따로 알려 주는 통로가 장치 대기까지 닿는지의 문제다.

**다시 보낼 수 없는 라운드.**
- 2단계는 get(RDMA READ), 0바이트 put(NOP), get 뒤 flush의 DUMP가 낀 라운드를 거절한다 `[소스]`. 표식은
  `gin_gdaki.h` 485, 658, 719행에서 달고, 거절은 `gin_host_gdaki.cc` 3037–3040행에서 한다.
- 이 경로를 잰 적은 없다. 저장소의 어떤 드라이버도 `gin.get`을 부르지 않는다 `[측정: grep]`.
- 다시 보낼 WQE의 슬롯이 덮였고 사본 영역도 없으면 거절한다(2576–2603행) `[소스]`. 이것도 잰 적이 없다.
  - 최종 빌드 1024 스레드 칸은 모든 라운드가 사본 영역에서 WQE를 꺼냈다. 10라운드에 5282개, 라운드마다 435–597개다
    `[측정]`. 사전 등록 때는 `../TRANSPARENT_S2.md` 한계 절의 476–593을 옮겨 적었다. 원자료와 달라 2026-10-07에
    원자료 값으로 고쳤다([DEVIATIONS.md](DEVIATIONS.md) 4절).
- `MODEL.md` 규칙 5(실행 여부를 모르면 다시 보내지 말고 오류로 표시)의 확인이다.

**관리망 소켓.** PR #7은 "관리망의 TCP 오류는 상대 사망의 증거가 아니다. 관리망 끊김 시험을 더하라"고 적었다.
- 현재 코드 `[소스]`:
  - 소켓의 모든 TCP 오류를 사망으로 본다(`gdakiTsAlive`, 2246–2254행).
  - 쉬는 중 소켓이 닫히면 INFO 한 줄만 남기고 그 상대와의 복구를 끈다(3243–3249행).
  - 수신 소켓은 준비가 끝나면 닫으므로 다시 연결할 수 없다(3399행).
- `MODEL.md` 규칙 3의 한계("오판은 아직 재지 않았다", 182행)를 처음 재는 자리다.

**질문.**
1. 중간 빌드에서만 잰 2단계 결과가 최종 빌드에서도 같은가. 대상은 16, 64 스레드 로컬 QP 오류, 실제 양방향 동시 시작,
   장애 없는 지연이다.
2. 사용자 devComm에 통신기의 abort 플래그를 이으면, 거절 뒤 받는 쪽의 `ncclCommAbort`가 돌아오는가. abort 전에는 아무것도
   풀리지 않고, 복구 결과와 빠른 경로가 그대로인가.
3. 라이브러리는 다음 두 라운드를 성공으로 내보내지 않고 거절하는가.
   - 응답 쪽 실행 수로 완료를 알 수 없는 작업(get)이 낀 라운드.
   - 다시 보낼 WQE의 사본이 없는 라운드.
4. RoCE 경로는 멀쩡하고 관리망 소켓만 소리 없이 끊기면, 지금의 정책은 무엇이라고 결론 내리는가.

## 2. 가설

| id | 가설 | 다음이 관측되면 틀린 것이다 |
|---|---|---|
| H1 | 중간 빌드에서 최종 빌드로 바뀐 것(낡은 원인 CQE를 분류에 쓰지 않게 한 수정)은 질문 1의 결과를 바꾸지 않는다 | 16, 64 스레드나 동시 시작 셀에서 투명하지 않은 시행이 나온다. 또는 지연 차이가 예측 범위 밖이다 |
| H2 | 받는 쪽 장치 대기는 abort 플래그가 닿을 때만 풀린다. 사용자 devComm에 플래그를 이으면 abort가 몇 초 안에 돌아오고, abort 전에는 풀리지 않는다. 복구 결과와 빠른 경로는 그대로다 | 새 셀에서 abort가 2회 이상 늦거나 돌아오지 않는다. 또는 플래그를 끈 대조에서 abort가 빨리 돌아온다. 또는 abort 전에 받는 쪽 커널이 끝난다. 또는 복구 재현 셀이 회귀하거나 지연 차이가 범위 밖이다 |
| H3 | 실행 여부나 사본을 확인할 수 없는 라운드는 거절되고 오류가 앱에 드러난다 | 어떤 시행이든 송신 쪽 flush가 모두 성공하고 비동기 오류도 없는데 슬롯, signal, get 데이터가 틀린다. 또는 get 셀에서 투명한 복구가 2회 이상 나온다. 또는 사본 영역을 끈 셀에서 거절되지 않은 시행이 있다 |
| H4 | 지금의 정책은 관리망 소켓의 시간 초과를 상대 사망과 같게 취급한다. 쉬는 중 끊김은 앱에 알려지지 않고, 뒤의 복구 가능한 장애는 거절되며, 끊김 중 재전송 소진은 상대가 살아 있어도 FIN/RST 사유로 거절된다. 짧은 끊김은 아무것도 바꾸지 않는다 | 8 s 끊김 뒤 로컬 QP 오류가 2회 이상 복구된다. 또는 끊김 중 상대 QP 오류의 거절 사유가 다르다. 또는 1 s 끊김에서 소켓이 닫힌다 |

## 3. 사전 예측 (측정 전에 작성)

예측 원문은 [predictions.csv](predictions.csv)이고, 해시는 [PREREG.txt](PREREG.txt)에 있다. 28줄이다.
`kind`는 N(새 셀), R(재현), C(대조)다. 아래 판정 열, 셀 키, 판정식 문법은 지금 고정한다.

### 3.1 판정에 쓰는 열

시행마다 한 줄이다. `../scripts/ts2/rows.py`의 열을 그대로 쓰고, 이 폴더의 `rows_extra.py`가 새 열을 붙인다.

**`rows.py`의 열** `[소스]`. 의미는 `rows.py`에 정의된 그대로다.

| 열 | 내용 |
|---|---|
| `cell`, `build` | 셀 이름과 빌드 |
| `transparent_ok` | 1 또는 0 |
| `r0rc`, `r1rc` | rank별 종료 코드 |
| `r0_outcome`, `r1_outcome` | 드라이버가 남긴 결과 |
| `tx_rc`, `tx_done` | 송신 쪽 첫 flush 결과와 끝낸 반복 수 |
| `dev_bad_slots`, `host_bad_slots`, `signal_exact` | 받는 쪽 데이터와 signal 검사 |
| `r0_async`, `r1_async` | 첫 비동기 오류. 없으면 `none` |
| `decl_r0`, `decl_r1` | 거절 사유. 여럿이면 `;`로 잇는다 |
| `tie_kept`, `yielded` | 동시 시작에서 라운드를 지킨 수와 양보한 수 |
| `teardown_r0`, `teardown_r1` | `ncclCommAbort` 반환 문자열. 성공은 `no error`, 돌아오지 않으면 빈칸 |
| `teardown_ms_r0`, `teardown_ms_r1` | abort가 돌아오기까지 걸린 시간 |
| `lat_p50_us` | 지연 p50 |
| `n_fires_r0`, `n_fires_r1`, `trigger_miss` | 장애 훅이 발화한 수와 트리거를 못 만난 수 |
| `bind_fail` | 드라이버 랑데부 포트 충돌 |
| `ts_on_r0`, `ts_on_r1` | "transparent recovery ON" 줄 수 |
| `fault_mono_r0`, `fault_after_launch_ms` | 장애 시각(rank 0 시계)과 커널 시작에서 장애까지 |
| `left` | 시행 뒤 남은 프로세스 수 |
| `iters` | 반복 수 |

**`rows_extra.py`가 붙이는 열.** 새 로그 줄의 형식도 여기서 고정한다.

| 열 | 출처와 정의 |
|---|---|
| `get_n`, `get_bad` | rank 0 kv `get_n=<검사한 get 수> get_bad=<틀린 get 수>`. flush가 `ncclSuccess`를 돌려준 반복만 검사한다 |
| `ua_r0`, `ua_r1` | rank별 로그의 WARN `GIN/TS: user devComm abort flag set rank=<r>` 줄 수 |
| `n_mute_on_r0`, `mute_on_ms_r0` | rank 0 WARN `GIN/TS: TEST socket mute on rank=<r> peers=<n> mono_ms=<t>`의 줄 수와 첫 줄의 `mono_ms` |
| `n_sock_close_r0`, `sock_close_ms_r0`, `sock_close_cause_r0` | rank 0 WARN `GIN/TS: rank <r>: socket to rank <p> closed cause=<NAME> mono_ms=<t>`의 줄 수, 첫 줄의 `mono_ms`, 첫 줄의 `cause` |
| `sock_close_cause_r1` | rank 1의 같은 줄. `cause`는 `FIN`, `BADMAGIC`, 또는 errno 이름(`ETIMEDOUT`, `ECONNRESET` 등) |
| `decl_mono_r0` | rank 0 첫 `GIN/TS: declined` 줄의 `mono_ms` |
| `async_before_fault` | 어느 rank든 첫 비동기 오류 시각이 `fault_mono_r0`보다 앞서면 1, 아니면 0. 첫 비동기 오류 시각은 그 rank의 kv `launch_mono_ms + async_first_ms_after_launch`다. rank 1 값은 rank 0 kv의 `clock_offset_ms`(rank 1 − rank 0)를 빼서 rank 0 시계로 옮긴다 |
| `r1_alive_at_decline` | 1의 조건은 두 가지다. rank 1의 `launch_mono_ms + kernel_ms`를 rank 0 시계로 옮긴 값이 `decl_mono_r0`보다 크다. 그리고 `r1rc`가 137, 139, 255가 아니다. 아니면 0 |
| `silent_bad` | 1의 조건은 세 가지다. `tx_rc == "no error"`이다. `r0_async == "none"`이다. 그리고 `dev_bad_slots > 0`, `host_bad_slots > 0`, `signal_exact == 0`, `get_bad > 0` 중 하나다. 아니면 0 |
| `gate_pass` | 지연 hold의 `gate_test.txt`에서 `result=PASS`인 줄 수. 스칼라 하나다 |

### 3.2 셀 키와 판정식 문법

**셀 키.**
- 셀 키는 `cell@build`다. 예: `f1_b@s2r`. 같은 셀 이름을 두 빌드에서 돌리므로 `cell`과 `build` 두 열로 고른다.
- 판정 대상은 8절 제외를 거친 시행이다.
- 계획한 반복 수(7절)보다 판정할 시행이 적으면 그 예측은 "자료 부족"이다.

**판정식.** `score.py`가 이 문법을 그대로 구현한다.

| 형태 | 뜻 |
|---|---|
| `count(E)` | 셀의 시행 중 식 `E`가 참인 수. `E`는 Python 식이고 열 이름이 변수다 |
| 값 변환 | 숫자로 읽히는 값은 실수, 빈칸은 None, 나머지는 문자열로 다룬다. None이 들어간 비교나 산술은 거짓이다 |
| `has(F, "s")` | 열 `F`에 문자열 `s`가 들어 있다. 빈칸이면 거짓이다 |
| `nonempty(F)` | 열 `F`가 빈칸이 아니다 |
| `maskbit(F, b)` | `F`에서 처음 나오는 `mask 0x<16진수>`의 값과 `b`의 비트 AND가 0이 아니다 |
| `median(F, "셀 키")` | 그 셀 시행들의 `F` 중앙값 |
| `abs` | 절댓값 |
| `per cell:` | 나열한 셀마다 따로 적용한다. 모두 맞아야 맞음이다 |

판정은 맞음, 틀림, 자료 부족 중 하나다.

### 3.3 예측 요약

전체 판정식은 [predictions.csv](predictions.csv)에 있다. 아래는 요약이다.

| id | 셀 | 예측 | 판정 기준(요약) | 근거 |
|---|---|---|---|---|
| RA1 | `mt16_f1_b@s2`, `mt64_f1_b@s2` | 16, 64 스레드 로컬 QP 오류가 최종 빌드에서도 투명하다 | 셀마다 5/5 | 중간 빌드 10/10씩 `[측정]` |
| RA2a | `bidirf_sym_b@s2` | 실제 양방향 동시 시작이 최종 빌드에서도 투명하다 | 5/5 | 중간 빌드 20/20 `[측정]` |
| RA2b | `bidirf_sym_b@s2` | 대부분 두 helper가 함께 시작해 낮은 rank가 라운드를 지킨다 | 지킴과 양보가 함께 있는 시행 ≥3/5 | 중간 빌드 19/20 |
| RA3 | `bidirf_sym_notie_b@s2` | 동시 시작 처리를 끄면 대부분 두 쪽이 거절한다 | 투명 ≤2/5, 동시 복구 사유 ≥3/5 | 중간 빌드 투명 1/5 |
| RA4a | `lat_s2on_4k@s2` 대 `lat_s2off_4k@s2` | 4 KiB에서 2단계 켬이 0.30–1.20 µs 느리다 | 실행 중앙값 차이 | 첫 빌드 +0.61, 중간 빌드 +0.67 `[측정]` |
| RA4b | `lat_s2on_256k@s2` 대 `lat_s2off_256k@s2` | 256 KiB에서 0.10–1.00 µs 느리다 | 같음 | +0.48, +0.40 `[측정]` |
| RA4c | 게이트 미세 시험 | 두 GPU, 일곱 설정 모두 통과 | `gate_pass == 14` | 앞서 14/14 두 번 |
| RB1a | `f2rel_b@s2r` | 거절 뒤 받는 쪽 abort가 5 s 안에 돌아온다 | ≥9/10 | 2절 H2, 1절의 `[소스]` |
| RB1b | `f2rel_b@s2r` | abort 전에는 풀리지 않는다(비동기 오류 2 s 뒤에도 커널이 멈춰 있다) | 10/10 | 거절 경로는 플래그를 쓰지 않는다 `[소스: init.cc 3378–3388행]` |
| RB1c | `f2rel_b@s2r` | 보내는 쪽 결정은 그대로다(원격 접근 오류로 거절) | 10/10 | 최종 빌드 10/10 |
| RB2 | `ringf2rel_b@s2r` | burst 수신 쪽도 풀린다. abort가 8 s 안에 돌아온다 | ≥9/10 | 남은 반복마다 1만 번 회전 뒤에야 플래그를 본다 `[추론]` |
| RB3 | `f2rel_off_b@s2r` | 플래그를 끄면 abort가 자기 수신 대기(20 s)를 기다린다 | 5/5 | 대조 |
| RB4a | `f1_b`, `f3_b`, `f1g0_b`, `mt256_f1_b`, `bidirf_f1both_b`(모두 `@s2r`) | 복구 결과가 그대로다 | 셀마다 5/5 투명 | 최종 빌드 13/13, 10/10, 30/30, 10/10, 20/20 `[측정]` |
| RB4b | `f4_b@s2r` | 죽은 상대는 그대로 거절되고 살아남은 쪽 abort가 돌아온다 | 5/5 | 최종 빌드 10/10 |
| RB5 | `off_f1_b@s2r` | 투명 복구를 끄면 분류기만 동작하고 플래그를 잇지 않는다 | 5/5 | 대조 |
| RB6a | `lat_s2r_on_4k@s2r` 대 `lat_s2on_4k@s2` | 4 KiB 지연 차이가 0.40 µs 이하 | 실행 중앙값 | 회전 1만 번에 한 번 읽기 `[추론]` |
| RB6b | `lat_s2r_on_256k@s2r` 대 `lat_s2on_256k@s2` | 256 KiB 지연 차이가 0.30 µs 이하 | 같음 | 같음 |
| RC1a | `get_f1_b@s2rget` | get이 낀 라운드는 READ 표식(0x4)으로 거절된다 | ≥9/10 | `[소스]` 1절 |
| RC1b | `get_f1_b@s2rget` | 조용한 실패 0, 투명한 복구 ≤1 | 10회 전체 | 규칙 5 |
| RC2 | `get_none_b@s2rget` | 장애가 없으면 get 모드는 투명하고 get 데이터가 모두 맞다 | 5/5 | 대조 |
| RC3a | `mt1024_norescue_b@s2r` | 사본 영역이 없으면 거절되고 조용한 실패가 없다 | 5/5 | 음성 대조 |
| RC3b | `mt1024_norescue_b@s2r` | 거절 사유가 덮인 WQE다 | ≥4/5 | `[소스]` 2576–2603행 |
| RD1a | `mute8_f1_b@s2r` | 8 s 끊김에서 소켓이 시간 초과로 2.5–7.0 s 안에 닫힌다 | ≥9/10 | keepalive 2 s, 1 s × 3, 사용자 시간 초과 5 s `[소스]`, 필터 동작 `[추론]` |
| RD1b | `mute8_f1_b@s2r` | 끊김은 다음 장애 전까지 앱에 알려지지 않는다 | 0/10 | `[소스]` 3243–3249행 |
| RD1c | `mute8_f1_b@s2r` | 뒤의 로컬 QP 오류는 helper 소켓이 없어 거절된다 | ≥9/10 | `[소스]` 3010행 |
| RD1d | `mute8_f1_b@s2r` | 받는 쪽은 비동기 오류를 받지 못한다 | ≥9/10 | 규칙 4 |
| RD2 | `mute_f3_b@s2r` | 끊김 중 상대 QP 오류는 상대가 살아 있는데도 FIN/RST 사유로 거절된다 | ≥9/10 | `[소스]` 2246–2254, 3004행, 규칙 3 |
| RD3 | `mute1_f1_b@s2r` | 1 s 끊김은 소켓을 닫지 않고 복구는 투명하다 | 5/5 | 대조 |

## 4. 범위

**포함.**
- 최종 빌드 재측정: 16, 64 스레드 로컬 QP 오류, 실제 양방향 동시 시작(동시 시작 처리 켬과 끔), 장애 없는 지연과 게이트
  미세 시험.
- 받는 쪽 대기 해제.
  - 라이브러리 변경: 사용자 devComm abort 플래그. 환경변수 `NCCL_GIN_TS_USER_ABORT`, 기본값 1.
  - 해제 셀 2개, 대조 2개, 복구 재현 6개, 지연 대조 2개.
- 다시 보낼 수 없는 라운드.
  - 드라이버 get 모드를 더한다.
  - get 장애 셀, get 대조, 사본 영역을 끈 음성 대조.
- 관리망 소켓 끊김의 현재 정책.
  - 시험 전용 스위치(`SO_ATTACH_FILTER`)를 더한다.
  - 쉬는 중 소켓 닫힘 줄에 원인을 붙이고 WARN으로 올린다. 동작은 바꾸지 않는다.
  - 8 s 끊김 뒤 로컬 QP 오류, 끊김 중 상대 QP 오류, 1 s 대조.

**제외.**
- 관리망 소켓 재연결(고치기): 다음 실험이다. 이번 결과가 그 대조가 된다.
- RoCE 주소를 빼고 넣는 셀 전부(주소 장애 상한, 주소 자체 변경): 노드 네트워크 설정 변경이다.
- 문서 정리(2단계 문서의 한계 절, `summary.md`, CSV, 폴더 README의 PR 표현, `MODEL.md` 규칙 5 한계): 별도 커밋으로
  한다. 이 실험의 결과를 쓰기 전에 원자료 재집계만 반영한다.
- 빠른 경로 비용 줄이기, 요청 쪽만 재설정, 장애 난 쌍만 재설정, get 다시 보내기 지원, 쉬는 QP의 오류 감지, 3 rank 이상,
  다른 GPU 세대: 하루를 넘거나 장비가 없다.
- 드라이버 재적재가 필요한 펌웨어 명령 슬롯 회수: 금지 사항이다.

## 5. 테스트베드와 버전

| 항목 | 값 | 확인 방법과 날짜 |
|---|---|---|
| 노드 | rain(rank 0, 보내는 쪽), sunny(rank 1, 받는 쪽), 100 GbE RoCE v2 직결 | 루트 `README.md` 테스트베드 표 |
| NIC와 펌웨어 | ConnectX-6 VPI, fw 20.43.4100. rain `mlx5_1`, sunny `mlx5_0` | `[측정]` 2026-10-06, `../../completion_contract/EXPERIMENT.md` 5절. 이번 hold 스냅숏에서 다시 기록 `[미확인]` |
| 커널, OFED | rain 커널 5.15.0-97-generic. OFED 버전 | 커널은 `[측정]` 2026-10-07 작업 환경. OFED는 `[미확인]`, 첫 hold 스냅숏에서 기록 |
| GPU와 드라이버, CUDA | rain Quadro RTX 5000(sm_75), sunny RTX A4000(sm_86), PeerMappingOverride=1, CUDA 12.8(`/usr/local/cuda-12.8`) | GPU는 `[측정]` 2026-10-01 `gate_test.txt`. CUDA 경로는 `[소스]` `../scripts/ts2/build_driver.sh` |
| 최종 빌드 | libnccl md5 `0a32b875`, 드라이버 md5 `d4b1f082`(`$HOME/gi-bundle/gin_ts2/`) | `[측정]` 2026-10-07 md5sum, 스크래치 빌드와 같음 |
| 새 라이브러리 빌드 | libnccl md5 `ba4984bd`, 드라이버 md5 `d4b1f082`(최종 드라이버 사본). `$HOME/gi-bundle/gin_ts2/s2r/` | `[측정]` 2026-10-07 19:05 배포 때 두 노드에서 원본과 같음([deploy_check.txt](deploy_check.txt)) |
| get 드라이버 빌드 | libnccl md5 `ba4984bd`, get 모드 드라이버 md5 `f3de7a38`. `$HOME/gi-bundle/gin_ts2/s2rget/` | `[측정]` 같은 때, 같은 파일. 전체 diff [gin_transparent_s2r.diff](gin_transparent_s2r.diff)(md5 `70d31c36`)를 pristine v2.32.3-1에 적용하면 빌드 트리와 같다 |

## 6. 변수

- **독립변수.**
  - 빌드: 최종, 새 라이브러리, get 드라이버.
  - 장애: 없음, 로컬 QP 오류, 원격 접근 오류, 상대 QP 오류, 상대 프로세스 kill.
  - 트래픽: 기본 루프, 16–1024 스레드, 묶음 링, 실제 양방향, get 모드, 지연.
  - 스위치: `NCCL_GIN_TS_USER_ABORT`, `NCCL_GIN_TS_RESCUE_LAPS`, `NCCL_GIN_TS_TEST_SOCK_MUTE`, 동시 시작 처리.
- **종속변수.** 3.1의 열이다.
  - 투명 여부, 거절 사유.
  - rank별 abort 반환 여부와 시간, 받는 쪽 결과.
  - 지연 p50, 조용한 실패.
  - 소켓 닫힘 시각과 원인, 장애 전 비동기 오류.
- **통제변수.**
  - IB 타임아웃 14, GPU doorbell(PeerMappingOverride=1).
  - 기존 셀 정의는 `../scripts/ts2/batch.sh` 그대로다. 반복 수, 크기, 간격, 장애 시각 공식이 같다.
  - 시행마다 프로세스를 새로 띄운다.
  - 한 hold 안의 지연 셀은 셀을 섞어 돈다(반복 k마다 모든 셀).

## 7. 실험 셀, 반복 수, 대조군

반복 수는 사전 등록 규칙(새 셀 10, 재현 5, 대조 5)을 따른다. 지연 셀의 반복은 실행 수다(실행마다 3000번 반복).

| 셀 | 조건 | 반복 수 | 대조군 여부 |
|---|---|--:|---|
| `lat_base_4k`, `lat_base_256k`, `lat_s1off_4k`, `lat_s1off_256k`, `lat_s1on_4k`, `lat_s1on_256k`, `lat_s2off_4k`, `lat_s2off_256k`, `lat_s2on_4k`, `lat_s2on_256k`, `lat_s2sys_4k`, `lat_s2sys_256k` | 기존 정의 그대로. 2단계 셀은 최종 빌드(gpudb, 1단계, 시스템 범위 셀은 그 번들) | 각 5 | 재현 |
| 게이트 미세 시험 | `../scripts/ts2/gate_test.sh`, 일곱 설정 × 두 노드, 10 s | 14 | 재현 |
| `lat_s2r_on_4k`, `lat_s2r_on_256k` | 새 라이브러리 빌드, 투명 복구 켬, 위 지연 셀과 같은 hold에서 섞어 돈다 | 각 5 | 대조 |
| `mt16_f1_b@s2`, `mt64_f1_b@s2` | 기존 정의 | 각 5 | 재현 |
| `bidirf_sym_b@s2` | 기존 정의(4 KiB 양방향, rank 1 장애 훅 1–2 ms 먼저) | 5 | 재현 |
| `bidirf_sym_notie_b@s2` | 기존 정의(동시 시작 처리 끔) | 5 | 대조 |
| `f2rel_b@s2r` | 원격 접근 오류, `GIN_TS_RX_WAIT_S=20`, `ABORT_WD_S=40`, `GIN_TS_POST_ABORT_WAIT_S=3`, `NCCL_GIN_TS_USER_ABORT=1`, 120 × 256 KiB | 10 | 새 셀 |
| `ringf2rel_b@s2r` | 묶음 128개로 링을 채운 burst(1 KiB, 15 ms 간격, 200 반복) + 원격 접근 오류, 위 설정 | 10 | 새 셀 |
| `f2rel_off_b@s2r` | `f2rel_b`와 같고 `NCCL_GIN_TS_USER_ABORT=0` | 5 | 대조 |
| `off_f1_b@s2r` | 기존 정의(투명 복구 끔, 로컬 QP 오류) | 5 | 대조 |
| `f1_b@s2r`, `f3_b@s2r`, `f1g0_b@s2r`, `mt256_f1_b@s2r`, `bidirf_f1both_b@s2r`, `f4_b@s2r` | 기존 정의 | 각 5 | 재현 |
| `get_f1_b@s2rget` | get 모드(`GIN_TS_GET=1`, 256 KiB put과 signal 뒤 64 KiB get, 그다음 flush), 로컬 QP 오류(기존 시각 공식 500–1199 ms), `GIN_TS_RX_WAIT_S=20`, `ABORT_WD_S=40`, 120 반복 | 10 | 새 셀 |
| `get_none_b@s2rget` | get 모드, 장애 없음, 120 반복 | 5 | 대조 |
| `mt1024_norescue_b@s2r` | 1024 스레드 로컬 QP 오류(기존 `mt1024_f1_b` 정의와 트리거 공식), 두 rank `NCCL_GIN_TS_RESCUE_LAPS=0`, `GIN_TS_RX_WAIT_S=20`, `ABORT_WD_S=40` | 5 | 대조(음성) |
| `mute8_f1_b@s2r` | 두 rank `NCCL_GIN_TS_TEST_SOCK_MUTE=500:8000`, 로컬 QP 오류 12 000 ms, 16 KiB × 1000(15 ms 간격), `GIN_TS_RX_WAIT_S=10`, `ABORT_WD_S=20`, `WATCHDOG_S=60` | 10 | 새 셀 |
| `mute_f3_b@s2r` | 두 rank `MUTE=300:30000`, 상대 QP 오류 6000 ms, 16 KiB × 1000, 위와 같은 대기 설정 | 10 | 새 셀 |
| `mute1_f1_b@s2r` | 두 rank `MUTE=500:1000`, 로컬 QP 오류 3000 ms, 16 KiB × 300 | 5 | 대조 |

**합계.**

| 종류 | 셀 시행 | 지연 실행 | 기타 |
|---|--:|--:|---|
| 새 셀 | 50 | | |
| 재현 | 45 | 60 | 게이트 14 |
| 대조 | 30 | 10 | |
| 합 | 125 | 70 | 게이트 14 |

**빌드 키.**
- 셀 이름 뒤의 키는 1절 머리의 빌드 키다.
- 지연 셀은 `batch.sh` 정의가 정한 번들을 쓴다. 새 라이브러리 지연 셀만 새 번들이다.

**스위치 의미.**
- `NCCL_GIN_TS_TEST_SOCK_MUTE=<시작 ms>:<길이 ms>`의 시각은 그 rank helper 소켓 준비가 끝난 때부터 잰다.
- 장애 훅 시각(`INJECT`)은 기존과 같이 devComm 생성부터 잰다.

## 8. 제외 기준과 중단 기준

**제외 기준.** 제외한 시행은 셀별로 따로 세어 보고한다.
- smoke 실행(`results/<날짜>_smoke/`)은 채점하지 않는다.
- NCCL 초기화 전 실패(`bind_fail == 1`, 드라이버 랑데부 포트 충돌)는 제외한다. 다음 번호로 계획한 반복 수를 채운다.
- 장애 미적용은 제외하고 다음 번호로 채운다. 해당하는 경우는 다음과 같다.
  - 로컬 QP 오류 셀에서 `n_fires_r0 == 0`.
  - 상대 QP 오류 셀에서 `n_fires_r1 == 0`.
  - `trigger_miss > 0`.
  - 상대 프로세스 kill 셀에서 kill 기록(`_kill.out`)이 없다.
  - get 장애 셀에서 `fault_after_launch_ms <= 0`(첫 get 전에 장애).
- 채우려고 다시 돈 시행이 셀마다 계획의 50%를 넘으면 그 셀은 멈추고 "자료 부족"으로 둔다.
- get 블록: smoke의 장애 없는 get 1회에서 `get_bad == 0`이 아니거나 `get_n != iters`면, get이 이 테스트베드에서 동작하지
  않는 것이다. 그 경우 get 장애 예측과 get 대조 예측(RC1a, RC1b, RC2)을 "측정 불가"로 두고 채점하지 않는다. 사본 영역
  예측(RC3a, RC3b)은 그대로 채점한다.
- 끊김 블록: smoke의 8 s 끊김 2회에서 소켓 닫힘 줄(`n_sock_close_r0 >= 1`)이 한 번도 없으면, 이 수단이 이 커널에서 동작하지
  않는 것이다. 그 경우 끊김 블록 예측(RD1a–RD3) 전체를 "측정 불가"로 둔다.

**설정 확인.** 하나라도 어긋나면 제외가 아니라 그 블록을 멈춘다.
- 새 라이브러리나 get 드라이버 빌드에서 투명 복구를 켠 시행은 `ts_on_r0 >= 1`이고 `ts_on_r1 >= 1`이어야 한다.
  - 이 줄이 없으면 abort 플래그 대입 위치가 틀려 투명 복구가 꺼진 것이다. 사용자 문맥을 abort 플래그가 null인지로 알아보기
    때문이다(`gin/gin_host.cc` 370행) `[소스]`.
- `NCCL_GIN_TS_USER_ABORT=1`인 투명 셀은 `ua_r0 >= 1`이고 `ua_r1 >= 1`이어야 한다.
- 끊김 셀은 `n_mute_on_r0 >= 1`이어야 한다.

**중단 기준.**
- **잠금.** 모든 클러스터 명령은 `harness/gpu-initiated/common/cluster_run.sh -w 10800` 안에서 돈다. 이 세션의 다른 실험 두 개가
  같은 잠금을 쓴다.
  - 10 800 s 안에 잠금이나 유휴 링크를 얻지 못하면(종료 코드 75) 그 hold를 미룬다.
  - `prio-` 작업에는 양보한다.
  - hold 하나는 15분 이하이고 `timeout -s KILL 880`으로 묶는다.
- **하지 않는 것.** 실제 link down이나 flap, 재부팅, 드라이버 재적재, 커널 모듈 적재, RoCE 주소 변경, iptables 같은 방화벽 변경.
  - 관리망 끊김은 우리 프로세스의 소켓에 붙이는 필터로만 만든다.
- **프로세스.** 우리가 띄운 프로세스만, 정확한 이름(`pkill -x gin_ts2`)이나 PID로 끈다.
  - 다른 사용자의 작업은 건드리지 않는다. 예: gds-kv, NVMe-oF, gdsio, mooncake, `prio-` 작업.
  - `left > 0`이 두 시행 연속이면 멈춘다.
- **mlx5 오류.** rain `mlx5_1`은 펌웨어 명령 슬롯 하나가 새어 있다. hold 앞뒤 스냅숏을 비교한다. 스냅숏은
  `../scripts/ts2/hold.sh`의 `snap`, `../scripts/ts1/fwcmd_snapshot.sh`와 같은 방식이다. 다음이 하나라도 보이면 그 hold
  뒤로 멈추고 12절에 기록한다.
  - 두 노드 dmesg에 새 mlx5 명령 오류 줄이 생겼다. 명령 오류 줄은 `mlx5`와 함께 `cmd` 또는 `command`, 그리고 `failed`,
    `timeout`, `leak` 중 하나를 담은 줄이다.
  - debugfs 명령 실패 계수(`failed`, `failed_mbox_status`)가 늘었다.

  명령 오류가 아닌 mlx5 줄만 늘었으면 멈추지 않고 줄 내용을 12절에 기록한다.
- **배포.** 새 번들은 새 디렉터리에만 둔다: `$HOME/gi-bundle/gin_ts2/s2r/`, `$HOME/gi-bundle/gin_ts2/s2rget/`.
  - 배포 스크립트는 대상 파일이 이미 있으면 멈춘다.
  - 배포 뒤 기존 번들 파일의 md5가 그대로인지 확인한다. 대상은 최종 libnccl `0a32b875`, 드라이버 `d4b1f082`,
    `s1/`, `base/`, `var_sys/`다.
  - 기존 번들 파일은 어떤 것도 덮어쓰지 않는다.

## 9. 실행 방법과 경로

**코드 변경.** 아직 하지 않았고 빌드도 하지 않았다. 사전 등록 뒤에 한다.
1. `src/dev_runtime.cc` `ncclDevrCommCreateInternal`: GIN 준비(`ncclGinDevCommSetup`, 1641행) 바로 뒤, devComm 복사(1716행)
   앞에 다음 두 가지를 넣는다.
   - `if (!isInternal && ncclGinTsUserAbortEnabled()) outDevComm->abortFlag = comm->abortFlagDev;`
   - WARN `GIN/TS: user devComm abort flag set rank=<r>`.
   - 접근 함수의 선언은 `extern`으로 두어 헤더를 바꾸지 않는다. 그러면 장치 코드를 다시 빌드할 필요가 없다.
2. `src/transport/net_ib/gdaki/gin_host_gdaki.cc`:
   - `NCCL_PARAM(GinTsUserAbort, "GIN_TS_USER_ABORT", 1)`와 접근 함수
     `ncclGinTsUserAbortEnabled()`(복구, 투명, 이 값이 모두 켜졌을 때 참).
   - 시험 스위치 `NCCL_GIN_TS_TEST_SOCK_MUTE`. `gdakiTsMain` 루프가 시작 시각에 상대 소켓마다 모두 버리는 고전 BPF
     필터를 `SO_ATTACH_FILTER`로 붙이고, 끝 시각에 `SO_DETACH_FILTER`로 뗀다. 3.1 형식의 WARN 두 줄을 남긴다.
   - `gdakiTsPump`가 닫힘 원인(FIN, BADMAGIC, errno)을 `gdakiTsPeer`에 남긴다. 쉬는 중 닫힘 줄(3249행)은 3.1 형식의 WARN으로
     바꾼다. 동작은 그대로다.
3. `../gin_ts2.cu`: get 모드(`GIN_TS_GET=1`, 기본 0, `GIN_TS_GET_BYTES` 기본 65536).
   - rank 1은 send 창을 `pat(i, k, 7)`로 채운다. rank 0은 recv 창을 독값으로 채운다.
   - rank 0은 반복 i마다 put과 signal 뒤에 rank 1 send 창의 i번째 64 KiB를 자기 recv 창의 같은 자리로 get하고 flush한다.
   - flush가 성공한 반복만 장치에서 비교해 kv에 `get_n`, `get_bad`를 남긴다.
   - 기존 모드는 바꾸지 않는다. 이 변경은 13절에 적는다.

**빌드.** 세션 스크래치 `$SCR`에서 한다. `$SCR`은 `/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad`다.
1. 최종 트리와 빌드 디렉터리(`$SCR/agent_ts2/nccl-src`, `$SCR/agent_ts2/build`)를 `$SCR/agent_ts2r/`로 복사한다.
   - 의존 파일(`*.d`)의 경로만 바꾼다. 최종 빌드는 그대로 둔다.
2. 변경 1과 2를 넣는다.
3. `make -n`으로 다시 컴파일되는 파일이 두 개뿐인지 확인한다.
4. 다음으로 빌드한다.
   `make -j32 -C $SCR/agent_ts2r/nccl-src src.build BUILDDIR=$SCR/agent_ts2r/build CUDA_HOME=/usr/local/cuda-12.8 NVCC_GENCODE="-gencode=arch=compute_75,code=sm_75 -gencode=arch=compute_86,code=sm_86"`
5. get 모드 드라이버는 `../scripts/ts2/build_driver.sh`의 nvcc 줄과 같이 빌드한다. 다만 출력은 `$SCR/agent_ts2r/`에 두고,
   이 폴더의 `build_s2r.sh`로 빌드한다. 기존 스크립트는 `agent_ts2`의 바이너리를 덮어쓰기 때문이다.
6. 전체 diff `gin_transparent_s2r.diff`를 만들고, pristine v2.32.3-1 + diff == 트리인지 확인한다.

**배포.** 이 폴더의 `deploy_s2r.sh`로 두 노드에 배포한다.
- 새 라이브러리 번들 `$HOME/gi-bundle/gin_ts2/s2r/`: 새 libnccl과 최종 드라이버 `d4b1f082`의 사본.
- get 드라이버 번들 `$HOME/gi-bundle/gin_ts2/s2rget/`: 새 libnccl과 get 모드 드라이버.
- 확인: 두 노드 md5가 같은지, `ldd`가 각 번들의 libnccl을 가리키는지, 기존 번들 md5가 그대로인지(8절).

**실행.**
- `../scripts/ts2/run_trial.sh`를 그대로 쓴다. `BUILD=s2r|s2rget`이면 `$HOME/gi-bundle/gin_ts2/<BUILD>`를 쓴다.
- 기존 셀은 `../scripts/ts2/batch.sh`로 돈다. 새 라이브러리 재현은 `BUILD=s2r bash batch.sh <dir> <cell> 5`다.
- 새 셀과 대조 셀은 이 폴더의 `cells.sh`가 7절 조건대로 `run_trial.sh`를 부른다.
- hold는 이 폴더의 `hold.sh`에 둔다. 각 hold를 따로 `cluster_run.sh`로 잡는다.

  ```
  bash harness/gpu-initiated/common/cluster_run.sh -w 10800 -t gsc-<hold> -- \
      timeout -s KILL 880 bash harness/gpu-initiated/gin_recovery/s2_close/hold.sh <결과 폴더> <hold>
  ```

| hold | 내용 | 추정 `[추론]` |
|---|---|---|
| H0 smoke | 새 셀과 대조 셀마다 1회, 8 s 끊김 2회, 새 라이브러리 지연 1회, 설정 확인 | 5분 |
| H1 | 게이트 미세 시험 + 지연 14셀 × 5(섞어서) | 9분 |
| H2 | 최종 빌드 재현: 16, 64 스레드, 동시 시작 두 셀 | 3분 |
| H3 | 받는 쪽 해제: 해제 셀 두 개, 대조 두 개 | 6분 |
| H4 | 새 라이브러리 재현 여섯 셀 | 4분 |
| H5 | get 장애, get 대조, 사본 영역 끔 | 4분 |
| H6 | 끊김 세 셀 | 10분 |

hold마다 잠금과 유휴 확인이 약 1분 더 든다. 클러스터 시간은 모두 45–60분이다 `[추론]`.

**채점.**
1. `../scripts/ts2/rows.py`로 hold 폴더마다 시행 CSV를 만든다.
2. 이 폴더의 `rows_extra.py`가 3.1의 열을 붙인다.
3. 이 폴더의 `score.py`가 [predictions.csv](predictions.csv)의 판정식을 3.2 문법대로 적용한다.
   - 결과는 `results/<날짜>/SCORE.md`다.
   - 예측마다 판정, 판정한 시행 수, 놓친 시행, 제외한 시행을 적는다.

**입력.** 7절 셀 정의, 위 번들.

**출력.** `results/<날짜>/<hold>/`(시행별 로그, 원시 자료)와 `results/<날짜>/trials_*.csv`, `SCORE.md`.
- 원시 로그는 Release에 올린다. 자산 이름은 `tools/pack_release.py`의 규칙을 따른다.

## 10. 완료 조건과 QA 기준

- [x] 모든 셀이 계획한 반복 수만큼 실행됐다. 제외와 실패를 따로 센 표가 있다.
- [x] 예측 28줄마다 판정(맞음, 틀림, 자료 부족, 측정 불가)과 놓친 시행 목록이 있다.
- [ ] 다른 에이전트가 `score.py`를 보지 않고 원자료에서 핵심 수치를 다시 셌다. 대상은 abort 시간, 거절 사유, 소켓 닫힘
  시각, 지연 중앙값이다.
- [x] smoke와 제외 시행이 결과에 섞이지 않았다.
- [x] 새 빌드 두 개의 md5, 전체 diff, pristine + diff 확인 결과를 5절에 적었다.
- [ ] 원자료를 Release에 올리고 `DATA.md`에 적었다.
- [x] 클러스터 hold 전후 mlx5 스냅숏에 새 명령 오류가 없었거나, 있었다면 12절에 적었다.

## 11. 작업 체크리스트

- [x] 질문, 가설, 셀 작성 (`DRAFT`)
- [x] 고정 절 완성, 상태 `PREREGISTERED`, 해시 기록을 커밋 하나로 만들고 그 커밋에 `prereg/` 태그
- [x] 코드 변경 세 가지, 빌드, 배포
- [ ] 코드 변경의 독립 리뷰
- [x] `cells.sh`, `hold.sh`, `rows_extra.py`, `score.py`
- [x] smoke 실행(채점 제외)
- [x] 본 실행 (`RUNNING`)
- [x] 채점(`score.py`, 상태 `QA`)
- [ ] 독립 재계산(다른 에이전트)
- [ ] 결과 정리, 원자료 릴리스, PR
- [ ] 결론 확정 (`COMPLETE`)

## 12. 실행 기록 (시간순)

| 시각 | 무엇을 했나 | 결과와 근거(경로, 커밋, 실행 ID) |
|---|---|---|
| 2026-10-07 | 범위 조사: 2단계의 남은 항목과 하루 가능성 정리(읽기만, 클러스터와 빌드 없음) | 세션 스크래치 문서 `design_gin_s2.md`(저장소 밖) |
| 2026-10-07 | Release `data-20261006`의 2단계 원자료를 스크래치에 받아 `../scripts/ts2/tables.sh`로 표를 다시 만듦. 16, 64 스레드와 동시 시작 셀이 중간 빌드에만 있음을 확인 | sha256 앞 12자 `f628df6c6b48`, 1절 |
| 2026-10-07 | 사용자가 네 블록(최종 빌드 재측정, 받는 쪽 해제, 다시 보낼 수 없는 라운드, 관리망 끊김)과 병렬 에이전트, QA를 승인 | |
| 2026-10-07 18:56:33 | 사전 등록 | [PREREG.txt](PREREG.txt), 태그 `prereg/gin-s2-close-v1` |
| 2026-10-07 18:57–19:06 | 코드 변경(받는 쪽 abort 플래그, 소켓 끊김 시험 스위치, 닫힘 원인 WARN, 드라이버 get 모드), 증분 빌드(다시 컴파일된 파일은 `dev_runtime.cc`, `gin_host_gdaki.cc`와 버전 표시뿐), 두 노드 배포. 새 libnccl md5 `ba4984bd`, get 모드 드라이버 `f3de7a38`, 새 라이브러리 번들의 드라이버는 최종 드라이버 사본 `d4b1f082`. 배포한 파일 md5가 두 노드에서 원본과 같고, 기존 번들 파일 12개의 md5가 두 노드에서 그대로다 `[측정]`. pristine v2.32.3-1 + 전체 diff == 트리 확인 | [build_s2r.sh](build_s2r.sh), [deploy_s2r.sh](deploy_s2r.sh), [deploy_check.txt](deploy_check.txt), [gin_transparent_s2r.diff](gin_transparent_s2r.diff), [s2r_layer.diff](s2r_layer.diff), [make_diff_s2r.sh](make_diff_s2r.sh) |
| 2026-10-07 19:07:31–19:10:10 | smoke hold H0(`gs2-H0`), 13회, 채점 제외. 관찰 `[측정]`: 해제 셀의 받는 쪽 abort 851 ms. 플래그를 끈 대조는 14 114 ms로 사전 등록 기준 15 000 ms보다 짧다(20 s 장치 대기를 SM 클록 주기로 세는데 실제 클록이 속성값보다 높은 것으로 본다 `[추론]`). 사본 영역을 끈 셀의 거절 사유는 "executed count out of range"로, 덮인 WQE 검사보다 앞의 범위 검사(`gin_host_gdaki.cc` 2600–2609행)에서 걸렸다 `[소스]`. get 모드 장애 없음 120/120 일치, get 장애 거절 사유 mask 0x6. 8 s 끊김에서 소켓이 ETIMEDOUT으로 닫혔다. mlx5 명령 오류 줄은 hold 전후 rain 2, sunny 0으로 그대로. smoke 뒤 셀 설정, 예측, 판정식은 바꾸지 않았다 | `results/20261007_smoke/` (원시 파일은 Release 예정), `results/20261007_smoke/hold_H0.out` |
| 2026-10-07 19:11:16 | 본 실행 시작(상태 `RUNNING`). H1–H6을 [chain.sh](chain.sh)로 차례로 잡는다(`cluster_run.sh -w 10800`, 태그 `gs2-H<k>`). H1은 19:12:08에 잠금, 19:12:39에 유휴 링크를 얻었다 | `results/20261007/chain.out` |
| 2026-10-07 19:12:39–19:20:51 | H1(`gs2-H1`): 게이트 미세 시험 14회, 지연 70회(최종 빌드 12셀과 새 라이브러리 2셀, 섞어서). 지연 2회가 드라이버 랑데부 포트 충돌로 시작하지 못했다(`lat_s2on_4k` n4, `lat_s2r_on_4k` n2). 8절에 따라 제외하고 나중에 채운다. mlx5 명령 오류 줄과 펌웨어 명령 실패 수는 전후가 같다 | `results/20261007/lat/`, `results/20261007/gate_test.txt`, `results/20261007/hold_H1.out` |
| 2026-10-07 19:29:41–19:31:23 | H2(`gs2-H2`, 잠금은 다른 실험 뒤 19:29:10): 최종 빌드 16, 64 스레드 로컬 QP 오류 5회씩, 동시 시작 양방향 5회, 동시 시작 처리 끔 5회. 모두 시작했고 제외할 시행 없음. mlx5 전후 같음 | `results/20261007/rep_s2/`, `results/20261007/hold_H2.out` |
| 2026-10-07 19:43:07–19:49:08 | H3(`gs2-H3`): 받는 쪽 해제 셀 10회, burst 해제 셀 10회, 플래그 끈 대조 5회, 투명 복구 끈 대조 5회. 모두 시작했다. mlx5 전후 같음 | `results/20261007/rel/`, `results/20261007/hold_H3.out` |
| 2026-10-07 19:54:09–19:58:18 | H4(`gs2-H4`): 새 라이브러리에서 로컬 QP 오류, 상대 QP 오류, 진행 중 연산의 로컬 QP 오류, 256 스레드, 양방향 양쪽 로컬 QP 오류, 상대 프로세스 kill 5회씩. 256 스레드 1회(n5)가 랑데부 포트 충돌로 시작하지 못해 제외, 나중에 채운다. mlx5 전후 같음 | `results/20261007/rep_s2r/`, `results/20261007/hold_H4.out` |
| 2026-10-07 20:19:16–20:21:20 | H5(`gs2-H5`): get 장애 10회, get 대조 5회, 사본 영역 끈 1024 스레드 5회. 모두 시작했다. mlx5 전후 같음 | `results/20261007/nonmsg/`, `results/20261007/hold_H5.out` |
| 2026-10-07 20:36:41–20:44:18 | H6(`gs2-H6`, 잠금은 다른 실험 뒤 20:36:11): 8 s 끊김 뒤 로컬 QP 오류 10회, 끊김 중 상대 QP 오류 10회, 1 s 끊김 5회. 모두 시작했다. mlx5 전후 같음 | `results/20261007/mute/`, `results/20261007/hold_H6.out` |
| 2026-10-07 20:44:58–20:45:12 | 채움 hold(`gs2-fill`): 랑데부 포트 충돌로 제외한 세 시행을 다음 번호(n6)로 채웠다. 최종 빌드 4 KiB 2단계 켬 지연 1회, 새 라이브러리 4 KiB 지연 1회, 새 라이브러리 256 스레드 1회. 셋 모두 시작했다. 다시 돈 시행은 셀마다 계획의 50%를 넘지 않았다. mlx5 전후 같음. 이것으로 모든 hold가 끝났고, 어느 hold도 중단 기준에 걸리지 않았다 | `results/20261007/hold_fill.out`, `results/20261007/chain.out` |
| 2026-10-07 20:49 | 채점(`score.py`): 시행 198회 중 판정 195회, 따로 센 시행 3회(모두 랑데부 포트 충돌). 예측 28줄 중 맞음 25, 틀림 3(4 KiB 지연 차이, 플래그 끈 대조의 abort 시간, 사본 영역 끈 셀의 거절 사유). 상태 `QA` | [results/20261007/SCORE.md](results/20261007/SCORE.md), [results/20261007/trials_scored.csv](results/20261007/trials_scored.csv) |
| 2026-10-07 21:00 | 2단계 문서 정리(별도 커밋, 사실만): `../results/20261001_ts2/`의 표를 Release 원자료에서 다시 만들고 중간 빌드 표를 `prev_6ff74bb6/`에 둠. `../TRANSPARENT_S2.md`의 빌드 표시, 시행 수, 한계 절, 출처 표를 원자료에 맞춤. 폴더 README의 PR 표현 수정. `MODEL.md`는 건드리지 않음 | 커밋 `92d5bda9` |

## 13. 사전 등록 이후 변경

> 기존 문장을 고치지 않고 여기에 덧붙인다. 변경이 많으면 `DEVIATIONS.md`에 두고 링크한다.

사전 등록 내용(가설, 예측, 판정식, 셀 조건, 반복 수, 제외와 중단 기준)은 바꾸지 않았다. 구현 세부, smoke에서 보고도 그대로 둔
것, 사전 등록 문서의 근거 수치가 원자료와 다른 곳은 [DEVIATIONS.md](DEVIATIONS.md)에 적었다.

| 날짜 | 무엇을 | 이유 | 영향 범위 | 커밋 |
|---|---|---|---|---|
| 2026-10-07 | 구현 세부 네 가지(get 모드를 별도 커널로, 끊김 스위치 실패 줄, 계획 수를 넘은 시행 처리, mlx5 기준을 hold 전후 증가로) | 사전 등록 문서에 없던 세부 | 판정 영향 없음 | 이 커밋들 |
| 2026-10-07 | 1절의 1024 스레드 사본 영역 수치를 원자료 값(435–597)으로 고침 | 2단계 문서에서 옮긴 값(476–593)이 원자료와 달랐다 | 근거 문장뿐, 판정식 영향 없음 | 이 커밋들 |

## 14. 원자료와 결과표

| 무엇 | 경로 또는 Release 자산 | n |
|---|---|--:|
| 채점 결과(예측별 판정, 놓친 시행, 따로 센 시행) | [results/20261007/SCORE.md](results/20261007/SCORE.md) | 예측 28 |
| 시행별 표(`rows.py` 열 + 3.1의 새 열 + 셀 키와 판정 상태) | [results/20261007/trials_scored.csv](results/20261007/trials_scored.csv) | 시행 198(판정 195, 따로 셈 3) |
| 지연과 게이트 미세 시험(H1, 채움 hold 일부) | `results/20261007/lat/`, `results/20261007/gate_test.txt` (원시, Release 예정 `[미확인]`) | 지연 72회, 게이트 14줄 |
| 최종 빌드 재현(H2) | `results/20261007/rep_s2/` (원시, Release 예정) | 20 |
| 받는 쪽 해제와 대조(H3) | `results/20261007/rel/` (원시, Release 예정) | 30 |
| 새 라이브러리 재현(H4, 채움 1회) | `results/20261007/rep_s2r/` (원시, Release 예정) | 31 |
| get과 사본 영역(H5) | `results/20261007/nonmsg/` (원시, Release 예정) | 20 |
| 관리망 소켓 끊김(H6) | `results/20261007/mute/` (원시, Release 예정) | 25 |
| hold 출력, mlx5 스냅숏 | `results/20261007/hold_*.out`, `snap_*.txt`, `fwcmd_*.txt`, `chain.out` (Release 예정) | hold 7 |
| smoke(채점 제외) | `results/20261007_smoke/` (Release 예정) | 13 |
| 배포 확인(md5, ldd, 기존 번들) | [deploy_check.txt](deploy_check.txt) | 파일 4 + 기존 12 |
| 2단계 원자료를 다시 만든 표(근거로 쓴 것) | [../results/20261001_ts2/](../results/20261001_ts2/), [../results/20261001_ts2/prev_6ff74bb6/](../results/20261001_ts2/prev_6ff74bb6/) (Release `data-20261006`에서 다시 셈) | |

## 15. 결과 요약

판정과 수치는 모두 [results/20261007/SCORE.md](results/20261007/SCORE.md)와
[results/20261007/trials_scored.csv](results/20261007/trials_scored.csv)에서 왔다 `[측정]`(원자료에서 `score.py`가 계산,
손으로 옮긴 값 없음). 범위는 따로 적지 않으면 "판정한 시행들 사이의 최솟값–최댓값"이다. 독립 재계산은 아직이다
(16절).

**판정.** 예측 28줄 중 맞음 25, 틀림 3, 자료 부족 0, 측정 불가 0. 따로 센 시행은 3회이고 모두 랑데부 포트 충돌이다(채움 hold로
다시 돌았다).

**1. 최종 빌드 재측정.** (판정: RA1, RA2a, RA2b, RA3, RA4b, RA4c 맞음, RA4a 틀림)
- 16, 64 스레드 로컬 QP 오류는 최종 빌드에서 각각 5/5 투명했다. 첫 라운드에서 다시 보낸 WQE 수(장애 난 QP, 시행 5회의 범위)는
  16 스레드 16–20, 64 스레드 30–49다. 근거: `results/20261007/rep_s2/`.
- 실제 양방향 동시 시작은 5/5 투명했고, 5/5 모두 낮은 rank가 라운드를 지키고 높은 rank가 양보했다. 동시 시작 처리를 끄면
  1/5만 투명했고 4/5는 양쪽이 "simultaneous recovery from both ends"로 거절했다(투명한 1회는 두 라운드가 겹치지 않은
  것으로 본다 `[추론]`: 동시 시작 처리를 끄면 겹친 라운드는 거절되기 때문이다).
- 장애 없는 지연. 셀마다 5회 실행한 p50의 중앙값이다.

  | 크기 | gpudb | 1단계 끔 | 1단계 켬 | 2단계 끔 | 2단계 켬 | 2단계 켬, 시스템 범위 게이트 | 새 라이브러리 켬 |
  |---|--:|--:|--:|--:|--:|--:|--:|
  | 4 KiB | 10.14 | 10.24 | 16.77 | 10.27 | 10.56 | 12.32 | 10.56 |
  | 256 KiB | 38.37 | 38.40 | 41.60 | 38.66 | 38.91 | 39.71 | 38.91 |

  - 2단계 켬과 끔의 차이는 4 KiB에서 +0.29 µs로, 예측 범위 0.30–1.20 µs 바로 밖이다(RA4a 틀림).
  - 중간 빌드의 같은 차이는 +0.67 µs였다. 최종 빌드의 2단계 켬이 더 빠르다(10.91 → 10.56 µs). 2단계 켬의 4 KiB 실행별
    p50 범위는 10.56–10.59 µs다.
  - 256 KiB 차이는 +0.25 µs다(RA4b 맞음).
  - gpudb 대비 2단계 켬의 비용은 4 KiB +4.1%(+0.42 µs), 256 KiB +1.4%(+0.54 µs)다.
  - 게이트 미세 시험은 14/14 통과했다.
- 근거: `results/20261007/lat/`, `results/20261007/gate_test.txt`.

**2. 받는 쪽 대기 해제.** (판정: RB1a, RB1b, RB1c, RB2, RB4a, RB4b, RB5, RB6a, RB6b 맞음, RB3 틀림)
- 원격 접근 오류 뒤 받는 쪽(rank 1)의 `ncclCommAbort`가 10/10 돌아왔다.
  - 걸린 시간은 862–876 ms다(시행 10회의 범위).
  - 10/10 모두 비동기 오류 2 s 뒤에도 커널이 멈춰 있었다. abort 전에는 아무것도 풀리지 않았다.
  - 보내는 쪽은 10/10 "class REM_ACCESS is not recoverable"로 거절했다.
  - 같은 셀의 최종 빌드(플래그 없음)는 0/10이었다(1절).
- 링을 채운 burst 수신 쪽도 10/10 돌아왔다. 걸린 시간은 796–811 ms다.
- 플래그를 끈 대조에서는 받는 쪽 abort가 5/5 모두 자기 수신 대기가 끝난 뒤에 돌아왔다.
  - 걸린 시간은 14 275–14 339 ms로, 사전 등록 기준 15 000 ms보다 짧다. 그래서 RB3은 틀림이다.
  - 20 s로 둔 장치 대기가 실제로는 약 16 s에 끝난 것으로 본다. 대기를 SM 클록 주기 수로 재는데 실제 클록이 속성값보다
    높기 때문이다 `[추론]`(smoke에서 먼저 봤다, [DEVIATIONS.md](DEVIATIONS.md) 3절).
- 플래그를 이어도 다음은 그대로였다.
  - 복구 셀 다섯 개(로컬 QP 오류, 상대 QP 오류, 진행 중 연산, 256 스레드, 양방향 양쪽)는 25/25 투명했다.
  - 상대 프로세스 kill은 5/5 거절되고 살아남은 쪽 abort가 돌아왔다.
  - 투명 복구를 끄면 5/5 플래그를 잇지 않았다(분류기만 동작, 종료 코드 4).
  - 4 KiB와 256 KiB 지연 중앙값이 최종 빌드와 같았다(차이 0.00 µs).
- 근거: `results/20261007/rel/`, `results/20261007/rep_s2r/`, `results/20261007/lat/`.

**3. 다시 보낼 수 없는 라운드.** (판정: RC1a, RC1b, RC2, RC3a 맞음, RC3b 틀림)
- get이 낀 라운드에서 로컬 QP 오류를 낸 시행은 10/10 거절됐다.
  - 사유는 "epoch posted a WQE the recovery cannot count or re-post (mask 0x6)"로, READ(0x4)와 get 뒤 flush의 DUMP(0x2) 표식이
    함께 섰다.
  - 조용한 실패는 0/10, 투명한 복구도 0/10이었다.
  - 장애 전에 검사한 get(시행마다 32–63회)은 모두 맞았다.
  - 받는 쪽 abort는 10/10 돌아왔다.
- 장애 없는 get 모드는 5/5 투명했고 get 120/120이 맞았다.
- 사본 영역을 끈 1024 스레드 로컬 QP 오류는 5/5 거절됐고 조용한 실패는 0/5였다.
  - 사유는 5/5 "executed count out of range"였다. 예측한 "a WQE to re-post was overwritten"은 0/5다(RC3b 틀림).
  - 사본 영역이 0이면 아직 실행되지 않은 WQE 수의 상한이 링 크기(128)로 줄어든다. 그래서 슬롯 검사보다 앞의 범위 검사가
    먼저 거절한다(`gin_host_gdaki.cc` 2600–2609행) `[소스]`.
- 근거: `results/20261007/nonmsg/`.

**4. 관리망 소켓 끊김(현재 정책).** (판정: RD1a, RD1b, RD1c, RD1d, RD2, RD3 맞음)
- 8 s 끊김에서 두 rank의 helper 소켓이 10/10 ETIMEDOUT으로 닫혔다.
  - rank 0은 끊김 시작 4 575–4 600 ms 뒤에 닫혔다(시행 10회의 범위).
  - 닫힘은 다음 장애 전까지 앱에 알려지지 않았다(장애 전 비동기 오류 0/10).
  - 12 s의 로컬 QP 오류는 10/10 "no helper socket to the peer"로 거절됐다(발화 뒤 1.6–3.3 ms).
  - 받는 쪽은 10/10 비동기 오류를 받지 못했고, 자기 수신 대기의 시간 초과로 끝났다(종료 코드 4).
- 끊김 중 상대 QP 오류는 10/10 "RETRY_EXC and the peer's socket shows FIN/RST"로 거절됐다.
  - 소켓이 닫힌 원인은 10/10 ETIMEDOUT이었다(FIN이나 RST가 아님).
  - 상대 프로세스는 10/10 거절 시각에 살아 있었다.
  - 장애 발화에서 거절까지는 3 562–3 773 ms다(재전송 소진 감지 시간).
- 1 s 끊김은 소켓을 닫지 않았고(0/5) 뒤의 로컬 QP 오류는 5/5 투명하게 복구됐다.
- 근거: `results/20261007/mute/`.

## 16. QA와 재현성

> 누가(사람 또는 에이전트) 무엇을 다시 셌고 무엇이 맞거나 달랐는지. 재현에 필요한 빌드와 커밋.

## 17. 결론

## 18. 한계

## 19. 다음 작업

## 20. 참고자료
