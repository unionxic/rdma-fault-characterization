# GIN 투명 복구: 한쪽 방향 관리망 끊김에서의 오판 고치기 (gin-oneway)

**목적:** helper 소켓의 리셋을 확인 전까지 "모름"으로 두고, 재연결은 상대의 HELLO-ACK를 받은 뒤에만 세고, 높은 rank도 낮은 rank의
생존을 확인 접속(probe)으로 알아내게 한다. 그러면 한쪽 방향만 끊긴 관리망 뒤에 살아 있는 상대를 죽었다고 하지 않는지, 정말 죽은
상대는 어느 rank에서든 죽음으로 알아내는지, 재연결 확인의 틈이 닫혔는지를 사전 등록한 예측으로 잰다.

| 항목 | 값 |
|---|---|
| 상태 | `COMPLETE` |
| 담당자 | @unionxic |
| 작성일 | 2026-10-08 |
| 기준 브랜치와 커밋 | `exp/gin-oneway` @ `f21e2cb0` (master, gin-pair-check 합친 뒤로 rebase) |
| 사전 등록 태그 | `prereg/gin-oneway-v1` (상태를 `PREREGISTERED`로 바꾼 바로 그 커밋) |
| 마지막 갱신 | 2026-10-08 16:35, 독립 재계산과 코드 리뷰, Release, PR, 상태 `COMPLETE` |

표시: `[측정]` 원자료에서 확인, `[소스]` 코드에서 읽음, `[추론]` 해석, `[미확인]` 확인 안 함.

이 문서의 소스 줄 번호는 gin-pair-check 라이브러리 트리(빌드 `pc`) 기준이다. 세션 스크래치 `agent_ts2pc/nccl-src`의
`src/transport/net_ib/gdaki/gin_host_gdaki.cc`(md5 `b12e1933`)이고, 그 트리의 `git diff`는 gin-pair-check의 `pc_layer.diff`(md5
`76ae7483`)와 같다 `[측정]`.

**용어.**
- helper 소켓: GIN 투명 복구가 rank 쌍마다 여는 관리망 TCP 소켓. 장애 때 복구 라운드의 메시지를 주고받는다.
- 낮은 rank, 높은 rank: rank 번호가 작은 쪽과 큰 쪽. 이 테스트베드에서는 rank 0(rain)과 rank 1(sunny)이다.
- 끊긴 쪽: 들어오는 helper 세그먼트를 버리는 rank. 반대쪽은 안 끊긴 쪽이다.
- 다시 걸기: 낮은 rank가 끊긴 소켓 대신 새 TCP 연결을 거는 것. 확인 접속(probe): 연결만 해 보고 HELLO 없이 닫는 것.
- 죽음, 모름: 소켓 오류로 정한 상대의 생존 상태(gin-reconnect). 죽음은 그 상대와의 복구를 끝내고, 모름은 다시 연결을 기다린다.
- 첫 분류 기록: 장애 뒤 그 rank의 장치 쪽 분류기가 남긴 첫 "device-classified error CQE" 줄. 장애 훅 발사 시각과 다르다.

장애 기호와 셀 이름은 원자료를 찾는 키로만 괄호나 표의 id 열에 둔다.

| 장애 | 기호 |
|---|---|
| 로컬 QP 오류 | F1 |
| 원격 접근 오류 | F2 |
| 상대 QP 오류 | F3 |
| 상대 프로세스 kill | F4 |

빌드 키는 세 가지다.

| 빌드 | 키 | 내용 |
|---|---|---|
| gin-pair-check 라이브러리 | `pc` | libnccl `93d9ffee`와 드라이버 `d4b1f082`(`$HOME/gi-bundle/gin_ts2/pc/`). 지연 기준과 시험 스위치 없는 경주 셀에 쓴다 |
| 기준 빌드 | `pcm` | `pc`에 시험 스위치 두 개(9절 2번)만 더한 libnccl과 같은 드라이버(`$HOME/gi-bundle/gin_ts2/pcm/`, 새 디렉터리). 시험 스위치를 켜지 않으면 `pc`와 같은 코드 경로다. 결함 재현에 쓴다 |
| 이 실험의 라이브러리 | `ow` | `pcm` 위에 9절 1번의 변경을 더한 libnccl과 같은 드라이버(`$HOME/gi-bundle/gin_ts2/ow/`, 새 디렉터리) |

## 1. 배경과 연구 질문

**지금의 동작** `[소스]`(`gin_host_gdaki.cc`, 빌드 `pc`).
- helper 소켓은 keepalive(2 s 쉼, 1 s 간격, 3회)와 `TCP_USER_TIMEOUT` 5 000 ms를 쓴다(2382–2395행).
- 쉬는 중 소켓이 끊기면 원인으로 생존을 정한다(2481–2485행, 2492–2514행).
  - ETIMEDOUT, EHOSTUNREACH, ENETUNREACH만 "모름"이다.
  - FIN, 리셋(ECONNRESET), EPIPE와 그 밖의 오류는 모두 "죽음"이다. 죽음은 영구다.
- 다시 걸기는 낮은 rank만 하고, 대상은 "모름"인 상대뿐이다(2563–2564행). 높은 rank는 받아들이기만 한다.
- 낮은 rank는 HELLO를 보내자마자 새 소켓을 설치하고 재연결로 센다(2580–2584행). 높은 rank는 그 뒤에 HELLO를 확인하고, 맞지 않으면
  소켓을 닫는다(2635–2643행).
- 높은 rank는 준비 때 모은 주소 중 자기보다 높은 rank의 주소만 보관한다(3965–3968행). 그래서 낮은 rank에 연결해 볼 방법이 없다.

**gin-reconnect 코드 리뷰가 짚은 세 결함** `[소스, 추론]`(`../reconnect/qa/code_review.md` 항목 1, 2, 4).
1. **리셋을 죽음으로 본다.** 한쪽 방향만 끊기면 먼저 시간 초과한 쪽의 커널이 리셋을 보낸다. 반대쪽은 그 리셋을 받아 살아 있는 상대를
   영구히 죽음으로 본다. 리셋을 받은 쪽이 낮은 rank면 다시 걸지 않으므로, 끊김이 끝나도 두 rank 모두 상대를 잃은 채로 남는다.
2. **낮은 rank는 높은 rank가 받아들이기 전에 재연결로 센다.** 높은 rank가 그 연결을 거부해 닫으면, 낮은 rank는 FIN을 읽고 살아 있는
   상대를 죽음으로 본다. 거부는 HELLO가 500 ms 넘게 늦거나, 높은 rank가 이미 그 상대를 거절했거나, 문맥 번호가 다를 때 생긴다.
3. **낮은 rank만 다시 건다.** 끊김 중 낮은 rank가 죽으면 높은 rank는 죽음을 알 길이 없다. 장애마다 기다림 상한(10 s)까지 기다린 뒤
   "상대 생존 모름"으로 거절한다.

**gin-reconnect가 잰 것과 재지 못한 것** `[측정]`. 근거는 `../reconnect/results/20261008/`, Release `data-20261008`이다.
- 두 rank 모두에 끊김 스위치를 건 끊김에서는 오판이 없었다(재연결은 끊김이 끝난 뒤 75.9–104.4 ms, 10회의 범위).
- 그 스위치는 두 rank로 들어오는 세그먼트를 모두 버려 리셋도 버렸다. 그래서 결함 1의 조건이 생기지 않았다(코드 리뷰 항목 1).
- kill 셀은 높은 rank만 죽였다. 결함 3은 재지 않았다. 결함 2의 경로에도 들어가지 않았다(rank 0의 재연결 20회 모두 rank 1이 받아들임, 코드 리뷰 항목 2).

**누가 먼저 시간 초과하나** `[측정]`. 두 rank 모두에 끊김 스위치를 건 시행 65회의 원시 로그에서 두 rank의 ETIMEDOUT 닫힘 시각을
비교했다. rank 1 시각은 rank 0 kv의 `clock_offset_ms`로 rank 0 시계에 옮겼다(세션 스크래치 `gow/race.py`).
- 자료: gin-reconnect 45회(Release `data-20261008`의 `harness__gpu-initiated__gin_recovery__reconnect__results__20261008.tar.xz`,
  sha256 앞 12자 `d1dd5ebd0e92`), gin-s2-close 20회(`data-20261007`의 `..._s2_close__results__20261007.tar.xz`, `f2d11a86cc83`).
- 두 rank 모두 자기 끊김 시작 4 571.6–4 833.5 ms 뒤에 닫혔다(65회, 두 rank를 합친 범위).
- rank 0이 먼저 닫힌 시행이 56회(rank 1이 1.2–45.5 ms 늦음), rank 1이 먼저인 시행이 9회(rank 1이 17.1–26.5 ms 이름)였다.
- 왜 rank 0이 대개 먼저인지는 모른다 `[미확인]`.

**한쪽 방향 끊김을 만드는 방법** `[소스, 추론]`.
- 끊김 스위치 `NCCL_GIN_TS_TEST_SOCK_MUTE=<시작 ms>:<길이 ms>`는 이 프로세스의 helper 소켓(연결, 수신 대기, 다시 걸기 소켓)에 들어오는
  세그먼트를 모두 버리는 소켓 필터를 붙인다(3740–3785행). 소켓 필터는 들어오는 방향에만 걸린다. 환경변수라서 rank마다 따로 켤 수 있다.
- 그래서 한 rank에만 켜면 그 rank로 들어오는 방향만 끊긴다. A에서 B로 가는 방향을 끊으려면 B에만 켠다. 시스템 설정은 바꾸지 않는다.
- 끊긴 쪽(B)이 먼저 시간 초과하면 B의 커널이 리셋을 보내고, B에서 A로 가는 방향은 살아 있으므로 그 리셋이 A에 닿는다(keepalive가
  끝날 때 커널이 리셋을 보낸다 `[추론]`). A에는 필터가 없으므로 A는 ECONNRESET을 본다. 결함 1의 조건이다.
- 한쪽만 끊겨도 두 rank의 시간 초과 시각은 양쪽 끊김과 같은 식으로 정해진다 `[추론]`. 끊긴 쪽의 keepalive 응답은 자기 필터에서
  버려지고, 반대쪽의 keepalive는 끊긴 쪽 필터에서 버려진다. 그래서 리셋을 누가 받는지는 수십 ms 차이의 경주로 정해진다(위의 56/65).
- 경주를 고정하려고 시험 스위치 `NCCL_GIN_TS_TEST_SOCK_UTO_MS`로 안 끊긴 쪽(A) helper 소켓의 `TCP_USER_TIMEOUT`을 20 000 ms로 늘린다.
  그러면 B가 늘 먼저 닫힌다 `[추론]`. 시험 스위치 없이 경주를 그대로 둔 셀도 따로 둔다.
- 실제 끊김과의 차이 `[추론]`: B의 소켓이 닫힌 뒤에는 그 연결에 필터가 없다. 그래서 A가 그 연결로 더 보내는 세그먼트는 B의 커널에
  닿아 리셋으로 답을 받는다. 실제 한쪽 끊김이면 그 세그먼트는 사라진다. 이 차이는 A가 리셋을 받는 시각을 당길 수 있을 뿐, B가 먼저
  닫히면 A가 리셋을 받는다는 사실은 바꾸지 않는다.

**결함 2와 3을 만드는 방법.**
- 결함 2: 시험 스위치 `NCCL_GIN_TS_TEST_REFUSE_HELLO=<n>`을 높은 rank에 건다. 높은 rank는 확인을 통과한 재연결 HELLO 중 처음 n개를
  거부하고 닫는다. 실제로 높은 rank가 연결을 거부할 때와 같은 동작이다 `[소스]`.
- 결함 3: 두 rank 모두에 끊김 스위치를 건 끊김 중에 rank 0(낮은 rank)을 kill한다. 실행기에 rank 0 kill 선택을 더한다(9절 3번).

**질문.**
1. 한쪽 방향 끊김 뒤 리셋을 받은 rank(낮은 rank, 높은 rank 각각)는 살아 있는 상대를 죽었다고 하지 않고, 끊김이 끝나면 다시 연결해
   장애를 투명하게 복구하는가.
2. 끊김 중에 낮은 rank가 죽으면 높은 rank가 확인 접속으로 죽음을 알아내고 죽음 원인으로 바로 거절하는가. 높은 rank가 죽은 경우와
   끊김 없이 죽은 경우는 여전히 죽음으로 거절되는가.
3. 높은 rank가 재연결을 거부하면 낮은 rank는 살아 있는 상대를 죽음으로 보지 않고 다시 걸어 연결하는가.
4. 기준 빌드에서 세 결함이 실제로 나타나는가. 시간 초과 시험 스위치 없이도 한쪽 끊김의 오판이 나타나는가.
5. 기존 복구, 거절, 받는 쪽 abort 해제, 장애 없는 지연은 그대로인가.

## 2. 가설

| id | 가설 | 다음이 관측되면 틀린 것이다 |
|---|---|---|
| H1 | 리셋을 확인 전까지 "모름"으로 두면, 한쪽 방향 끊김 뒤에 어느 rank도 살아 있는 상대를 죽음으로 보지 않는다. 끊김이 끝나면 다시 연결되고 장애는 투명하게 복구된다. 리셋을 받은 쪽이 낮은 rank든 높은 rank든 같다 | 한쪽 끊김 셀 두 개(시험 스위치 있음)에서 어느 rank든 `liveness=dead` 줄이 나온 시행이 2회 이상이다. 또는 재연결이나 투명 복구가 9/10 미만이다. 또는 시험 스위치 없는 경주 셀에서 그런 시행이 하나라도 있다 |
| H2 | 높은 rank의 확인 접속으로 끊김 중 죽은 낮은 rank를 죽음으로 알아내고, 장애를 죽음 원인으로 바로 거절한다. 높은 rank가 죽거나 끊김 없이 죽은 경우도 여전히 죽음으로 거절한다 | 낮은 rank kill 셀에서 확인 접속 거부로 죽음을 정한 시행이 9/10 미만이다. 또는 "모름"으로 거절된 시행이 2회 이상이다. 또는 거절이 첫 분류 기록 뒤 2 s를 넘은 시행이 2회 이상이다. 또는 높은 rank kill 셀 두 개에서 죽음 원인 거절이 5/5가 아니다 |
| H3 | HELLO-ACK를 받은 뒤에만 재연결로 세면, 높은 rank가 재연결을 거부해도 낮은 rank는 상대를 죽음으로 보지 않고 다음 다시 걸기로 연결한다 | HELLO 거부 셀에서 `liveness=dead` 줄이 나온 시행이 2회 이상이다. 또는 끊김이 끝난 뒤 2 s 안에 재연결된 시행이 9/10 미만이다. 또는 투명 복구가 9/10 미만이다 |
| H4 | 기준 빌드는 세 결함을 그대로 보인다. 시간 초과 시험 스위치가 없어도 한쪽 끊김의 오판이 나타난다 | 기준 빌드 셀 네 개 중 하나라도 예측한 결함이 4/5 미만이다. 또는 `pc` 경주 셀에서 오판이 2/5 미만이다 |
| H5 | 바꾼 규칙은 기존 동작과 빠른 경로를 바꾸지 않는다 | 회귀 셀에서 예측과 다른 시행이 나온다. 또는 지연 차이가 예측 범위 밖이다 |

## 3. 사전 예측 (측정 전에 작성)

예측 원문은 [predictions.csv](predictions.csv)이고, 해시는 [PREREG.txt](PREREG.txt)에 있다. 28줄이다.
`kind`는 N(새 셀), R(재현), C(대조)다. 아래 판정 열, 로그 형식, 셀 키, 판정식 문법은 지금 고정한다.

### 3.1 판정에 쓰는 열

시행마다 한 줄이다. 열은 네 곳에서 온다.
- `../scripts/ts2/rows.py`의 열.
- gin-s2-close의 `../s2_close/rows_extra.py`가 붙이는 열. 정의는 `../s2_close/EXPERIMENT.md` 3.1절 그대로다.
- gin-pair-check의 `../pair_check/rows_pc.py`가 붙이는 열. 정의는 `../pair_check/EXPERIMENT.md` 3.1절 그대로다.
- 이 폴더의 `rows_ow.py`가 붙이는 새 열.

**앞의 세 곳에서 쓰는 열.** 의미는 원래 정의 그대로다 `[소스]`.

| 열 | 내용 |
|---|---|
| `cell`, `build`, `iters` | 셀 이름, 빌드, 반복 수 |
| `transparent_ok` | 1 또는 0. 양방향 모드에서는 두 rank 모두 모든 반복을 오류 없이 마쳐야 1이다 |
| `r1rc`, `r1_outcome` | rank 1의 종료 코드와 드라이버 결과 |
| `decl_r0`, `decl_r1` | rank별 거절 사유(`GIN/TS: declined` 줄의 `reason`). 여럿이면 `;`로 잇는다 |
| `rec_init_r1` | rank 1의 시작 쪽 복구 줄 수 |
| `teardown_r0`, `teardown_r1`, `teardown_ms_r1` | `ncclCommAbort` 반환 문자열(성공은 `no error`)과 걸린 시간 |
| `lat_p50_us` | 지연 p50 |
| `n_fires_r0`, `n_fires_r1`, `trigger_miss`, `bind_fail`, `ts_on_r0`, `ts_on_r1` | 장애 훅 발사 줄 수, 트리거 미도달, 랑데부 포트 충돌, 투명 복구 시작 줄 수 |
| `ua_r0`, `ua_r1`, `killed` | 받는 쪽 abort 플래그 줄 수, kill 기록이 있으면 1 |
| `async_before_fault` | 어느 rank든 첫 비동기 오류가 장애보다 앞서면 1 |
| `r1_alive_at_decline` | rank 0의 거절 시각에 rank 1이 살아 있었으면 1 |
| `pc_mode_r0`, `pc_mode_r1`, `inj_ctx_r1`, `n_notrts_r0`, `n_notrts_r1` | 검사 스위치 시작 줄의 값, rank 1 장애 훅의 문맥, teardown 때 RTS가 아닌 QP 수 |

**`rows_ow.py`가 붙이는 열.** 새 로그 줄의 형식도 여기서 고정한다. 모든 시각은 `mono_ms`(CLOCK_MONOTONIC, ms)다. 열 이름 끝의
`_r<r>`은 rank `r`의 로그에서 읽는다는 뜻이다. kv 파일은 `rows.py`와 같은 방법으로 읽는다.

| 열 | 출처와 정의 |
|---|---|
| `ow_mode_r0`, `ow_mode_r1` | WARN `GIN/TS: helper liveness oneway=<0\|1> rank=<r>`(`ow`의 helper 시작 줄)의 값. 줄이 없으면 빈칸 |
| `knob_uto_r0`, `knob_uto_r1`, `knob_refuse_r0`, `knob_refuse_r1` | WARN `GIN/TS: TEST socket knobs rank=<r> uto_ms=<x> refuse_hello=<n>`(`pcm`, `ow`. 두 시험 스위치 중 하나라도 켜면 helper 시작 때 한 번)의 `uto_ms`, `refuse_hello`. 줄이 없으면 빈칸 |
| `n_mute_on_r0`, `n_mute_on_r1` | `GIN/TS: TEST socket mute on rank=<r> peers=<n> mono_ms=<t>` 줄 수(`rows_extra.py`의 `n_mute_on_r0`과 같은 정의) |
| `mute_off_ms_r0`, `mute_off_ms_r1` | 첫 `GIN/TS: TEST socket mute off rank=<r> peers=<n> mono_ms=<t>`의 `mono_ms` |
| `close1_cause_r<r>`, `close1_lv_r<r>`, `close1_ms_r<r>` | 첫 닫힘 줄 `GIN/TS: rank <r>: socket to rank <p> closed cause=<NAME> mono_ms=<t> liveness=<dead\|unknown>`(gin-reconnect 형식 그대로)의 `cause`, `liveness`, `mono_ms` |
| `n_dead_r<r>`, `dead_cause_r<r>`, `dead_ms_r<r>` | `liveness=dead`인 닫힘 줄 수, 그 첫 줄의 `cause`와 `mono_ms` |
| `n_reconn_r<r>`, `reconn_ms_r<r>` | `GIN/TS: rank <r>: socket to rank <p> reconnected gen=<g> attempts=<n> mono_ms=<t>`(형식 그대로) 줄 수와 첫 줄 `mono_ms` |
| `n_notacc_r0` | rank 0의 `GIN/TS: rank <r>: re-dial to rank <p> not accepted (<why>) attempts=<n> mono_ms=<t>` 줄 수(`ow`만) |
| `n_probe_ref_r1`, `n_probe_ans_r1` | rank 1의 `GIN/TS: rank <r>: probe of rank <p> refused (ECONNREFUSED) mono_ms=<t>`, `GIN/TS: rank <r>: probe of rank <p> answered mono_ms=<t>` 줄 수(`ow`만) |
| `n_refuse_test_r1` | rank 1의 `GIN/TS: TEST refused a reconnect HELLO from rank <p> gen=<g> mono_ms=<t>` 줄 수 |
| `wait_end_r<r>`, `wait_ms_r<r>` | 첫 `GIN/TS: rank <r>: reconnect wait for rank <p> ended=<reconnected\|dead\|bound\|off> wait_ms=<x> mono_ms=<t>`(형식 그대로)의 `ended`, `wait_ms` |
| `q4_ms_r<r>` | 첫 분류 기록("device-classified error CQE" 줄)의 `mono_ms` |
| `decl_ms_r<r>` | 첫 `GIN/TS: declined` 줄의 `mono_ms` |
| `r0_killed` | 실행기 kill 기록(`kill.out`)에 `kill_mono_ms`와 `rank=0`이 있으면 1, 아니면 0 |
| `unmute_ms` | 끊김 끝 줄이 있는 rank들의 끊김 끝 시각 중 가장 늦은 것. rank 1 시각은 rank 0 kv의 `clock_offset_ms`를 빼서 rank 0 시계로 옮긴다. 없으면 빈칸 |
| `reconn_after_unmute_ms_r<r>` | `reconn_ms_r<r>`(rank 1이면 rank 0 시계로 옮긴 값) − `unmute_ms`. 둘 중 하나가 없으면 빈칸 |
| `decl_after_q4_ms_r1` | `decl_ms_r1` − `q4_ms_r1`(둘 다 rank 1 시계). 둘 중 하나가 없으면 빈칸 |

**새 로그 줄과 바뀐 줄** `[소스, 9절의 변경으로 고정]`.

| 줄 | 빌드 | 형식과 뜻 |
|---|---|---|
| 시작 | `ow` | `GIN/TS: helper liveness oneway=1 rank=<r>` |
| 시험 스위치 | `pcm`, `ow` | `GIN/TS: TEST socket knobs rank=<r> uto_ms=<x> refuse_hello=<n>`. 켜지 않은 스위치는 `uto_ms=5000`, `refuse_hello=0`으로 적는다 |
| 시험 거부 | `pcm`, `ow` | `GIN/TS: TEST refused a reconnect HELLO from rank <p> gen=<g> mono_ms=<t>` |
| 재연결 | 모두 | 형식 그대로. `ow`에서는 낮은 rank가 HELLO-ACK를 받은 뒤, 높은 rank가 HELLO-ACK를 보낸 뒤에 남긴다 |
| 받아들여지지 않은 다시 걸기 | `ow` | `GIN/TS: rank <r>: re-dial to rank <p> not accepted (<why>) attempts=<n> mono_ms=<t>`. `<why>`는 `FIN`, `ECONNRESET` 같은 원인 이름이나 `no HELLO-ACK within 1000 ms` |
| 확인 접속 | `ow` | 거부: `GIN/TS: rank <r>: probe of rank <p> refused (ECONNREFUSED) mono_ms=<t>`, 바로 뒤에 `cause=ECONNREFUSED liveness=dead` 닫힘 줄. 응답: `GIN/TS: rank <r>: probe of rank <p> answered mono_ms=<t>`(소켓을 잃을 때마다 첫 응답만) |
| 닫힘 | 모두 | 형식 그대로. `ow`에서는 9절 1번의 표대로 `liveness`가 정해진다 |

**거절 사유 문구.** gin-reconnect 3.1절의 문구 그대로다 `[소스]`.

| 경우 | 문구 |
|---|---|
| 재시도 초과, 소켓이 죽음 | `RETRY_EXC and the peer's socket shows <CAUSE>` |
| 재시도 초과, 소켓이 모름 | `RETRY_EXC and peer liveness unknown (<CAUSE>, no reconnect within <B> ms)` |
| 로컬 QP 오류, 소켓이 죽음 | `no helper socket to the peer (<CAUSE>)` |
| 로컬 QP 오류, 소켓이 모름 | `no helper socket to the peer: peer liveness unknown (<CAUSE>, no reconnect within <B> ms)` |

`ow`에서 죽음의 `<CAUSE>`는 FIN, BADMAGIC, 다시 걸기나 확인 접속이 받은 ECONNREFUSED, 표에 없는 errno 이름이다. 모름의
`<CAUSE>`에는 ECONNRESET, EPIPE, ECONNABORTED도 들어올 수 있다.

### 3.2 셀 키와 판정식 문법

셀 키(`cell@build`), 판정 대상(8절 제외를 거친 시행), "자료 부족" 규칙, 판정식 문법(`count`, 빈칸 규칙, `has`,
`nonempty`, `median`, `abs`, `per cell:`)은 `../s2_close/EXPERIMENT.md` 3.2절과 같다. `count(...)`와 `median(...)` 밖의 나머지는
Python의 산술과 비교다(`../pair_reset/EXPERIMENT.md` 3.2절과 같음). 이 실험의 `score.py`는 `../s2_close/score.py`의 판정식 평가 함수를
그대로 불러 쓴다. 두 셀 키를 쓰는 판정식은 두 셀 모두 계획한 수를 채워야 판정한다. 판정은 맞음, 틀림, 자료 부족 중 하나다.

### 3.3 예측 요약

전체 판정식은 [predictions.csv](predictions.csv)에 있다. 아래는 요약이다.

| id | 셀 | 예측 | 판정 기준(요약) | 근거 |
|---|---|---|---|---|
| A0 | `ow_r1in_f1_b@ow` | 시험이 의도대로 된다: 끊긴 rank 1이 먼저 시간 초과하고, 그 리셋을 rank 0이 받는다 | ≥9/10 | 양쪽 끊김 65회의 닫힘 시각 `[측정]`, 시간 초과 시험 스위치 |
| A1 | `ow_r1in_f1_b@ow` | rank 0은 리셋을 "모름"으로 두고, 두 rank 모두 상대를 죽음으로 보지 않는다 | ≥9/10 | 9절 1번 |
| A2 | `ow_r1in_f1_b@ow` | 두 rank가 한 번씩 다시 연결되고, rank 0은 끊김이 끝난 뒤 1.5 s 안이다 | ≥9/10 | gin-reconnect 75.9–104.4 ms `[측정]` |
| A3 | `ow_r1in_f1_b@ow` | 12 s의 로컬 QP 오류가 투명하게 복구되고, 거절과 장애 전 비동기 오류가 없다 | ≥9/10 | gin-reconnect 10/10 `[측정]` |
| K1 | `ow_r1in_f1_b@pcm` | 기준 빌드: rank 0이 ECONNRESET을 죽음으로 보고 장애를 "(ECONNRESET)"으로 거절한다. rank 1은 살아 있고 다시 연결되지 않는다 | ≥4/5 | 결함 1 `[소스]` |
| B0 | `ow_r0in_f1r1_b@ow` | 거울 방향 시험이 의도대로 된다: 끊긴 rank 0이 먼저 시간 초과하고, 그 리셋을 rank 1이 받는다 | ≥9/10 | A0와 같음 |
| B1 | `ow_r0in_f1r1_b@ow` | rank 1은 리셋을 "모름"으로 두고, 두 rank 모두 상대를 죽음으로 보지 않는다 | ≥9/10 | 9절 1번 |
| B2 | `ow_r0in_f1r1_b@ow` | 끊김 중 rank 1의 로컬 QP 오류가 재연결을 기다리고, 기다림은 끊김이 끝난 뒤 1.5 s 안에 재연결로 끝난다 | ≥9/10 | gin-reconnect 10/10 `[측정]` |
| B3 | `ow_r0in_f1r1_b@ow` | 그 뒤 rank 1이 시작 쪽으로 복구하고 투명하다 | ≥9/10 | 같음 |
| K2 | `ow_r0in_f1r1_b@pcm` | 기준 빌드: rank 1이 리셋을 죽음으로 보고 장애를 "(ECONNRESET)"으로 거절한다 | ≥4/5 | 결함 1 `[소스]` |
| D1 | `ow_kill0_b@ow` | rank 1이 끊김이 끝난 뒤 확인 접속 거부로 rank 0의 죽음을 알아낸다. 끊김 중에는 죽음으로 정하지 않는다 | ≥9/10 | 9절 1번 |
| D2 | `ow_kill0_b@ow` | rank 1의 재시도 초과는 죽음 원인(ECONNREFUSED)으로 거절되고 "모름"은 없다 | ≥9/10 | 같음 |
| D3 | `ow_kill0_b@ow` | 거절은 rank 1의 첫 분류 기록 뒤 2 s 안에 온다 | ≥9/10 | kill에서 첫 분류 기록까지 3 594.1–3 819.8 ms `[측정]` |
| K3 | `ow_kill0_b@pcm` | 기준 빌드: rank 1은 죽음을 모르고 10 s 상한 뒤 "모름"으로 거절한다 | ≥4/5 | 결함 3 `[소스]` |
| E1 | `ow_hello_f1_b@ow` | rank 1이 첫 재연결을 거부해도 rank 0은 "받아들여지지 않음"으로 남기고, 두 rank 모두 상대를 죽음으로 보지 않는다 | ≥9/10 | 9절 1번 |
| E2 | `ow_hello_f1_b@ow` | 다음 다시 걸기로 두 rank가 한 번씩 다시 연결되고, rank 0은 끊김이 끝난 뒤 2 s 안이다 | ≥9/10 | 다시 걸기 간격 500 ms |
| E3 | `ow_hello_f1_b@ow` | 12 s의 로컬 QP 오류가 투명하게 복구된다 | ≥9/10 | A3와 같음 |
| K4 | `ow_hello_f1_b@pcm` | 기준 빌드: rank 0이 재연결로 센 뒤 거부의 FIN을 읽고 상대를 죽음으로 보며, 장애를 "(FIN)"으로 거절한다 | ≥4/5 | 결함 2 `[소스]` |
| U1 | `ow_r0in_nat_f1r1_b@pc` | 시간 초과 시험 스위치가 없어도 배포된 `pc`가 한쪽 끊김 뒤 살아 있는 rank 0을 "(ECONNRESET)"으로 거절한다 | ≥2/5 | rank 0이 먼저 닫힘 56/65 `[측정]` |
| U2 | `ow_r0in_nat_f1r1_b@ow` | 같은 경주 조건에서 `ow`는 투명하고 어느 rank도 상대를 죽음으로 보지 않는다 | 5/5 | B1, B3과 같음 |
| G1 | `f1_b`, `f3_b`, `bidirf_sym_b`, `rc_mute8_f1_b`(모두 `@ow`) | 복구 재현 셀이 그대로 투명하다 | 셀마다 5/5 | `pc`와 이전 빌드 5/5 `[측정]` |
| G2 | `rc_mute8_f1_b@ow` | 양쪽 8 s 끊김은 그대로 두 rank가 한 번씩, 끊김이 끝난 뒤 1.5 s 안에 다시 연결되고 죽음 줄이 없다 | 5/5 | gin-reconnect 10/10 `[측정]` |
| G3 | `f4_b@ow` | 끊김 없는 kill은 죽음 원인(FIN, 또는 리셋을 확인한 ECONNREFUSED)으로 거절되고 살아남은 쪽 abort가 돌아온다 | 5/5 | gin-reconnect FIN 5/5 `[측정]` |
| G4 | `rc_mutekill_b@ow` | 양쪽 끊김 중 kill된 rank 1은 여전히 다시 걸기 거부(ECONNREFUSED)로 죽음 거절되고 "모름"은 없다 | 5/5 | gin-reconnect 10/10 `[측정]` |
| G5 | `f2rel_b@ow` | 받는 쪽 abort 해제가 그대로다 | 5/5 | gin-pair-check 5/5 `[측정]` |
| G6 | `f3_b@ow` | 상대 QP 오류 뒤 teardown 때 두 rank의 모든 QP가 RTS다(gin-pair-check의 동작) | 5/5 | gin-pair-check 10/10 `[측정]` |
| L1 | `lat_ow_on_4k@ow` 대 `lat_pc_on_4k@pc` | 4 KiB 지연 차이 0.40 µs 이하 | 같은 hold의 실행 중앙값 | 장치 코드와 드라이버가 같다 `[소스]` |
| L2 | `lat_ow_on_256k@ow` 대 `lat_pc_on_256k@pc` | 256 KiB 지연 차이 0.30 µs 이하 | 같음 | 같음 |

셀 조건은 7절에 있다.

## 4. 범위

**포함.**
- 9절 1번의 라이브러리 변경 하나(`gin_host_gdaki.cc` 한 파일).
  - 리셋을 확인 전까지 "모름"으로 두는 분류.
  - 재연결은 HELLO-ACK를 받은 뒤에만 센다.
  - 높은 rank가 "모름"인 낮은 rank를 확인 접속으로 확인한다.
- 9절 2번의 시험 스위치 두 개(`pcm`과 `ow` 모두): helper 소켓 시간 초과, 재연결 HELLO 거부.
- 9절 3번의 실행기 선택 하나: rank 0 kill(기본은 꺼짐, 기존 셀은 그대로).
- 7절의 셀 21개(지연 셀 4개 포함).
  - 새 셀 4개(`ow`): 낮은 rank가 리셋을 받는 한쪽 끊김, 높은 rank가 리셋을 받는 한쪽 끊김, 끊김 중 낮은 rank kill, 재연결 HELLO 거부.
  - 대조 셀 6개: 위 네 조건의 기준 빌드(`pcm`), 시험 스위치 없는 경주(`pc`, `ow`).
  - 재현 셀 7개(`ow`).
  - 지연 셀 4개.

**제외.**
- 라운드 도중(REQ, ACK, DONE을 주고받는 중) 소켓이 끊긴 경우: 지금처럼 그 라운드를 거절하고 상대를 죽음으로 둔다. 낮은 rank가
  HELLO-ACK를 놓쳐 버린 연결을 높은 rank가 아직 쓰고 있을 때도 이 경로로 간다 `[추론]`.
- gin-reconnect 코드 리뷰의 다른 항목: 문맥 번호(항목 3), 수신 대기 소켓의 막힘과 인증(항목 5), 기다림이 게시 멈춤 전에 있는 것(항목 6),
  사소한 점(항목 7, 9–12). 항목 8(연결된 소켓의 ICMP 오류)은 9절 1번의 분류에 들어간다.
- 호스트가 꺼진 경우: 다시 걸기와 확인 접속 모두 시간 초과가 되어 "모름"으로 남는다(gin-reconnect와 같음).
- 실제 관리망 장애(링크 내리기, 라우팅이나 방화벽 변경), 시스템 TCP 설정 변경, RoCE 주소 변경, 3 rank 이상, 여러 GDAKI 문맥.
- 두 번째 끊김, 기본값이 아닌 기다림 상한, 기다리는 중의 정리.

## 5. 테스트베드와 버전

| 항목 | 값 | 확인 방법과 날짜 |
|---|---|---|
| 노드 | rain(rank 0, 낮은 rank, 다시 거는 쪽), sunny(rank 1, 높은 rank, 확인 접속하는 쪽) | 루트 `README.md` 테스트베드 표 |
| NIC와 펌웨어 | ConnectX-6 VPI, fw 20.43.4100. rain `mlx5_1`, sunny `mlx5_0` | `[측정]` 2026-10-06, `../../completion_contract/EXPERIMENT.md` 5절. hold 스냅숏에서 다시 기록 |
| 커널, OFED | rain 커널 5.15.0-97-generic. sunny 커널, OFED | rain 커널 `[측정]` 2026-10-07. sunny 커널과 OFED `[미확인]`. 커널의 TCP 동작(keepalive가 끝날 때 리셋을 보냄)은 smoke에서 확인한다 |
| GPU와 CUDA | rain Quadro RTX 5000(sm_75), sunny RTX A4000(sm_86), PeerMappingOverride=1, CUDA 12.8 | gin-s2-close 5절 |
| 관리망 소켓 인터페이스 | `NCCL_SOCKET_IFNAME=eno1` | `../scripts/ts2/run_trial.sh` |
| 기준 빌드 `pc` | libnccl `93d9ffeed6d30e6467a3c5474035fd61`, 드라이버 `d4b1f082` | `[측정]` 2026-10-08 gin-pair-check 배포 때 두 노드 같음(gin-pair-check 5절, `deploy_check.txt`) |
| 이 실험의 빌드 `pcm`, `ow` | `pcm` libnccl `cd72f67a58a3a8cbc7cff8db2de229d9`, `ow` libnccl `b4af65c54b14f192803c88adcd2bf759`, 두 번들 모두 드라이버 `d4b1f082`. 변경분 [pcm_layer.diff](pcm_layer.diff)(md5 `c2fc15fb`, `pc` 트리 기준), [ow_layer.diff](ow_layer.diff)(md5 `06f450ec`, `pcm` 트리 기준). pristine 기준 전체 diff [gin_transparent_pcm.diff](gin_transparent_pcm.diff)(md5 `d42d53ef`), [gin_transparent_ow.diff](gin_transparent_ow.diff)(md5 `e681ec31`) | `[측정]` 2026-10-08 배포 때 두 노드 md5가 소스와 같음, 기존 번들 28개 파일 md5 그대로([deploy_check.txt](deploy_check.txt)). pristine v2.32.3-1에 각 전체 diff를 적용하면, 그리고 `pc` 전체 diff에 변경분을 차례로 더하면 각 빌드 트리와 같다 `[측정]`([make_diff_ow.sh](make_diff_ow.sh)). 두 빌드 모두 다시 컴파일된 파일은 `gin_host_gdaki.cc`와 버전 표시뿐([build_ow.sh](build_ow.sh)) |

## 6. 변수

- **독립변수.**
  - 빌드: `pc`, `pcm`, `ow`.
  - 끊김: 끊는 rank(rank 0만, rank 1만, 둘 다), 시작과 길이.
  - 시간 초과 시험 스위치(안 끊긴 쪽 20 000 ms 또는 없음), HELLO 거부 시험 스위치(1 또는 없음).
  - 장애 종류와 rank, 시각(로컬 QP 오류, 상대 QP 오류, 원격 접근 오류, 상대 프로세스 kill, rank 0 kill).
  - 트래픽: 기존 단방향, 양방향.
- **종속변수.** 3.1의 열이다.
  - 소켓 닫힘 원인과 생존 분류, 죽음 줄 수와 원인.
  - 재연결 수와 끊김 끝으로부터의 시각, 받아들여지지 않은 다시 걸기, 확인 접속 결과.
  - 기다림의 끝과 길이, 투명 여부, 거절 사유와 첫 분류 기록으로부터의 시각.
  - teardown 때 QP 상태, 지연 p50.
- **통제변수.**
  - IB 타임아웃 14, GPU doorbell, 재연결 스위치 기본값(1), 기다림 상한 기본값(10 000 ms), 범위 스위치와 검사 스위치 기본값(1).
  - 기존 셀 정의는 `../scripts/ts2/batch.sh`, `../reconnect/cells.sh`, `../pair_check/cells.sh` 그대로다(빌드만 바꿈).
  - 끊김 셀은 gin-reconnect 끊김 셀과 크기(16 KiB × 1000, 15 ms 간격)를 맞췄다.
  - 시행마다 프로세스를 새로 띄운다.

## 7. 실험 셀, 반복 수, 대조군

반복 수는 사전 등록 규칙(새 셀 10, 재현 5, 대조 5)을 따른다. 지연 셀의 반복은 실행 수다(실행마다 3000번 반복).
끊김 스위치 시각은 각 rank의 helper 시작부터, 장애 훅 시각은 각 rank의 devComm 생성부터 잰다. gin-s2-close 끊김 셀 25회에서 끊김 시작
줄은 devComm 생성 기준으로 설정보다 0–15 ms 일렀다 `[측정]`(gin-reconnect 7절). rank 0 kill의 `KILL_DELAY_MS`는 실행기가 rank 0을
띄운 때부터 잰다. 시간 초과 시험 스위치는 `NCCL_GIN_TS_TEST_SOCK_UTO_MS=20000`, HELLO 거부 시험 스위치는
`NCCL_GIN_TS_TEST_REFUSE_HELLO=1`이다. 아래 "끊김 X:Y"는 `NCCL_GIN_TS_TEST_SOCK_MUTE=X:Y`다. 양방향 셀은 `APP=bidir`,
`GIN_TS_BIDIR_FUSED=1`, `GAP_US=15000`이다(방향마다 보내는 rank 번호의 문맥을 쓴다).

| 셀 | 조건 | 빌드와 반복 수 | 종류 |
|---|---|---|---|
| `ow_r1in_f1_b` | rank 1만 끊김 500:8000(rank 0에서 rank 1로 가는 방향이 끊김). rank 0에 시간 초과 시험 스위치. rank 0 로컬 QP 오류 12 000 ms. 16 KiB × 1000, `GIN_TS_RX_WAIT_S=10`, `ABORT_WD_S=20`, `WATCHDOG_S=60` | `@ow` 10 | 새 셀 |
| | 같음 | `@pcm` 5 | 대조(기준 빌드) |
| `ow_r0in_f1r1_b` | rank 0만 끊김 500:8000(rank 1에서 rank 0으로 가는 방향이 끊김). rank 1에 시간 초과 시험 스위치. 양방향. rank 1 로컬 QP 오류 6 500 ms, 문맥 1만(`NCCL_GIN_FAULT_INJECT=local_err:6500`, `NCCL_GIN_FAULT_INJECT_CTX=1`). 16 KiB × 1000, `GIN_TS_RX_WAIT_S=30`, `ABORT_WD_S=20`, `WATCHDOG_S=60` | `@ow` 10 | 새 셀 |
| | 같음 | `@pcm` 5 | 대조(기준 빌드) |
| `ow_kill0_b` | 두 rank 끊김 300:8000. 양방향. rank 0 kill(`KILL_R0=1`, `KILL_DELAY_MS=6500`, devComm 생성 뒤 약 6.0 s `[추론]`). 훅 없음. 16 KiB × 1000, `GIN_TS_RX_WAIT_S=30`, `ABORT_WD_S=20`, `WATCHDOG_S=60` | `@ow` 10 | 새 셀 |
| | 같음 | `@pcm` 5 | 대조(기준 빌드) |
| `ow_hello_f1_b` | 두 rank 끊김 500:8000. rank 1에 HELLO 거부 시험 스위치. rank 0 로컬 QP 오류 12 000 ms. 16 KiB × 1000, `GIN_TS_RX_WAIT_S=10`, `ABORT_WD_S=20`, `WATCHDOG_S=60` | `@ow` 10 | 새 셀 |
| | 같음 | `@pcm` 5 | 대조(기준 빌드) |
| `ow_r0in_nat_f1r1_b` | `ow_r0in_f1r1_b`와 같고 시간 초과 시험 스위치 없음(누가 먼저 시간 초과할지 경주) | `@pc` 5, `@ow` 5 | 대조 |
| `f1_b`, `f3_b`, `bidirf_sym_b`, `f4_b` | `batch.sh`의 기존 정의 | `@ow` 각 5 | 재현 |
| `f2rel_b` | `../pair_check/cells.sh`의 `f2rel_b`와 같은 조건, 빌드만 `ow` | `@ow` 5 | 재현 |
| `rc_mute8_f1_b`, `rc_mutekill_b` | `../reconnect/cells.sh`의 정의, 빌드만 `ow`(두 rank 끊김. 앞의 것은 로컬 QP 오류 12 000 ms, 뒤의 것은 끊김 중 rank 1 kill) | `@ow` 각 5 | 재현 |
| `lat_pc_on_4k`, `lat_pc_on_256k` | `../pair_check/cells.sh`의 정의. 아래 두 셀과 같은 hold에서 섞어 돈다 | `@pc` 각 5 | 재현(지연 기준) |
| `lat_ow_on_4k`, `lat_ow_on_256k` | 투명 복구 켬, 장애 없음, 3000번 반복 | `@ow` 각 5 | 대조 |

**합계.**

| 종류 | 셀 시행 | 지연 실행 |
|---|--:|--:|
| 새 셀 | 40 | |
| 재현 | 35 | 10 |
| 대조 | 30 | 10 |
| 합 | 105 | 20 |

## 8. 제외 기준과 중단 기준

**제외 기준.** 제외한 시행은 셀별로 따로 세어 보고한다.
- smoke 실행(`results/<날짜>_smoke/`)은 채점하지 않는다.
- NCCL 초기화 전 실패(`bind_fail == 1`)는 제외하고 다음 번호로 계획한 반복 수를 채운다.
- 장애 미적용은 제외하고 다음 번호로 채운다.
  - rank 0 훅 셀(`ow_r1in_f1_b`, `ow_hello_f1_b`, `f1_b`, `rc_mute8_f1_b`)에서 `n_fires_r0 == 0`.
  - rank 1 훅 셀(`ow_r0in_f1r1_b`, `ow_r0in_nat_f1r1_b`, `f3_b`)에서 `n_fires_r1 == 0`.
  - 두 rank 훅 셀(`bidirf_sym_b`)에서 `n_fires_r0 == 0` 또는 `n_fires_r1 == 0`.
  - `trigger_miss > 0`.
  - rank 1 kill 셀(`f4_b`, `rc_mutekill_b`)에서 `killed != 1`.
  - rank 0 kill 셀(`ow_kill0_b`)에서 `r0_killed != 1`이거나 rank 1의 첫 분류 기록이 없음(`q4_ms_r1`이 빈칸).
- 순서 미적용은 제외하고 다음 번호로 채운다. 이 셀들의 조건은 "소켓을 이미 잃은 뒤의 장애"이기 때문이다.
  - `ow_r0in_f1r1_b`, `ow_r0in_nat_f1r1_b`, `ow_kill0_b`에서 rank 1의 닫힘 줄이 없거나 첫 분류 기록이 첫 닫힘보다 앞섬
    (`close1_ms_r1`이 빈칸이거나 `q4_ms_r1 < close1_ms_r1`).
  - `rc_mutekill_b`는 gin-reconnect 8절 그대로다(`q4_mono_r0 < sock_close_ms_r0`이거나 rank 0 닫힘 줄 없음).
- 채우려고 다시 돈 시행이 셀 키마다 계획의 50%를 넘으면 그 셀 키는 멈추고 "자료 부족"으로 둔다.

**설정 확인.** 하나라도 어긋나면 제외가 아니라 그 블록을 멈춘다.
- 투명 복구를 켠 시행은 `ts_on_r0 >= 1`, `ts_on_r1 >= 1`, `ua_r0 >= 1`, `ua_r1 >= 1`이어야 한다.
- 모든 시행은 `pc_mode_r0 == 1`, `pc_mode_r1 == 1`이어야 한다.
- `ow` 시행은 `ow_mode_r0 == 1`, `ow_mode_r1 == 1`이고, `pc`, `pcm` 시행은 둘 다 빈칸이어야 한다.
- 시험 스위치 줄(`knob_*`):
  - `ow_r1in_f1_b`는 `knob_uto_r0 == 20000`이고 rank 1에는 줄이 없다.
  - `ow_r0in_f1r1_b`는 `knob_uto_r1 == 20000`이고 rank 0에는 줄이 없다.
  - `ow_hello_f1_b`는 `knob_refuse_r1 == 1`이고 rank 0에는 줄이 없다.
  - 나머지 셀은 두 rank 모두 줄이 없다.
- 끊김 줄: `ow_r1in_f1_b`는 `n_mute_on_r1 >= 1`, `n_mute_on_r0 == 0`이다. `ow_r0in_f1r1_b`와 `ow_r0in_nat_f1r1_b`는
  `n_mute_on_r0 >= 1`, `n_mute_on_r1 == 0`이다. 두 rank 끊김 셀(`ow_kill0_b`, `ow_hello_f1_b`, `rc_mute8_f1_b`, `rc_mutekill_b`)은
  두 rank 모두 1 이상이다.
- 훅 문맥: `ow_r0in_f1r1_b`와 `ow_r0in_nat_f1r1_b`는 `inj_ctx_r1 == 1`이다.

**smoke에서 보이는 결함.** 본 실행 전에 고칠 수 있고, 그 변경은 `DEVIATIONS.md`에 적는다. 예측, 판정식, 셀 조건은 바꾸지 않는다.
- 구현 결함(`ow`): 한쪽 끊김 셀이나 HELLO 거부 셀에서 `liveness=dead` 줄이 나온다. 또는 `rc_mute8_f1_b@ow`가 다시 연결되지 않는다.
  또는 `ow_kill0_b@ow`에 확인 접속 줄이 없다.
- 시험 조건(`pcm`): `ow_r1in_f1_b`와 `ow_r0in_f1r1_b`의 smoke 2회 모두에서 안 끊긴 쪽의 첫 닫힘 원인이 ECONNRESET이 아니면, 시간 초과
  시험 스위치 값이나 끊김 시작을 본 실행 전에 한 번 바꿀 수 있다. 그래도 안 되면 그 셀들은 돌지 않고 관련 예측을 "자료 부족"으로 둔다.
- kill 시각: `ow_kill0_b`의 smoke 2회 모두에서 rank 1의 첫 분류 기록이 rank 1의 끊김 끝보다 1.5 s 넘게 앞서거나 없으면
  `KILL_DELAY_MS`를 한 번 바꿀 수 있다.
- 바꾼 값과 시각, 이유는 `DEVIATIONS.md`에 적는다.

**중단 기준.**
- **잠금.** 모든 클러스터 명령은 `harness/gpu-initiated/common/cluster_run.sh -w 10800` 안에서 돈다. 다른 실험(살아 있는 상대 경계
  실험, GIN 후속 실험)이 같은 잠금을 쓴다.
  - 10 800 s 안에 잠금이나 유휴 링크를 얻지 못하면(종료 코드 75) 그 hold를 미룬다.
  - `prio-` 작업에는 양보한다.
  - hold 하나는 15분 이하이고 `timeout -s KILL 880`으로 묶는다.
- **하지 않는 것.** 실제 link down이나 flap, 재부팅, 드라이버 재적재, 커널 모듈 적재, RoCE 주소 변경, iptables 같은 방화벽 변경,
  시스템 TCP 설정(sysctl) 변경.
  - 관리망 끊김은 우리 프로세스의 helper 소켓에 붙이는 소켓 필터로만 만든다. 필터는 그 프로세스의 소켓에만 걸리고 프로세스가 끝나면
    사라진다. 시간 초과 시험 스위치도 우리 소켓의 소켓 옵션만 바꾼다.
- **프로세스.** 우리가 띄운 프로세스만 정확한 이름(`pkill -x gin_ts2`)이나 PID로 끈다.
  - rank 0 kill은 실행기가 띄운 rank 0 프로세스를 PID로 찾아 끈다(9절 3번).
  - 다른 사용자의 작업은 건드리지 않는다. 예: gds-kv, NVMe-oF, gdsio, mooncake, `prio-` 작업.
  - `left > 0`이 두 시행 연속이면 멈춘다.
- **mlx5 오류.** rain `mlx5_1`은 펌웨어 명령 슬롯 하나가 새어 있다. hold 앞뒤에 두 노드의 mlx5 커널 줄 전체와 rain의 펌웨어
  명령 계수를 남기고, hold 동안 새로 생긴 mlx5 줄은 수가 아니라 내용을 12절과 `mlx5_new_<hold>.txt`에 적는다. 다음 중 하나가
  보이면 그 hold 뒤로 멈추고 12절에 기록한다.
  - 두 노드 dmesg에 새 mlx5 명령 오류 줄이 생겼다. 명령 오류 줄은 `mlx5`와 함께 `cmd` 또는 `command`, 그리고 `failed`,
    `timeout`, `leak` 중 하나를 담은 줄이다.
  - rain debugfs의 명령 실패 계수(`failed`, `failed_mbox_status`)가 늘었다.

  rain에는 이 실험 전부터 명령 오류 줄 2개(2026-09-25)가 있고 펌웨어 명령 실패 수는 31이다(2026-10-08 gin-pair-check hold 스냅숏)
  `[측정]`. hold 앞뒤의 증가로 판단한다.
- **배포.** 새 번들은 새 디렉터리 `$HOME/gi-bundle/gin_ts2/pcm/`과 `ow/`에만 둔다.
  - 대상 파일이 이미 있으면 배포 스크립트가 멈춘다.
  - 배포 뒤 기존 번들 파일(최종, `s1/`, `base/`, `var_sys/`, `s2r/`, `s2rget/`, `rc/`, `rc_smoke_1193a5f8/`, `pr/`, `prd/`, `pc/`,
    `pcd/`)의 md5가 두 노드에서 그대로인지 확인한다.

## 9. 실행 방법과 경로

**1. 라이브러리 변경(`ow`).** 아직 하지 않았고 빌드도 하지 않았다. 사전 등록 뒤에 한다. 대상은
`src/transport/net_ib/gdaki/gin_host_gdaki.cc` 하나다(헤더와 장치 코드는 그대로). 변경분은 `ow_layer.diff`(`pcm` 트리 기준)와 전체 diff
`gin_transparent_ow.diff`(pristine 기준)로 남긴다.
1. **생존 분류.** 연결된 helper 소켓이 끊긴 원인을 이렇게 나눈다. 다시 걸기와 확인 접속의 connect 결과는 따로 다룬다.

   | 경우 | 분류 |
   |---|---|
   | 연결된 소켓의 FIN, BADMAGIC, 표에 없는 errno | 죽음(지금과 같음) |
   | 연결된 소켓의 ETIMEDOUT, EHOSTUNREACH, ENETUNREACH | 모름(지금과 같음) |
   | 연결된 소켓의 ECONNRESET, EPIPE, ECONNABORTED, ECONNREFUSED, EHOSTDOWN, ENONET | 모름(새로 바뀜). 확인 전까지 죽음으로 보지 않는다 |
   | 다시 걸기나 확인 접속이 거부됨(connect의 ECONNREFUSED) | 죽음. 그 포트에 수신 대기 소켓이 없다는 뜻이다 |
   | 다시 걸기나 확인 접속의 시간 초과, 다른 실패 | 모름 그대로, 다음 시도 |

   - 모름이 된 상대는 지금처럼 낮은 rank가 다시 건다. 모름에서 죽음으로 바뀌는 길은 거부된 다시 걸기와 거부된 확인 접속뿐이다.
   - 리셋으로 모름이 된 상대에게도 바로 다시 건다. 죽은 프로세스라면 그 다시 걸기가 곧 거부된다 `[추론]`.
2. **HELLO-ACK.** 새 메시지 종류 HELLO-ACK를 둔다.
   - 낮은 rank는 다시 걸기가 연결되면 HELLO를 보내고 기다린다(대기). 같은 세대 번호와 문맥 번호를 담은 HELLO-ACK가 오면 그때
     소켓을 설치하고 재연결 줄을 남긴다.
   - 대기 중 그 소켓이 FIN, 리셋, 오류로 끝나거나 1 000 ms 안에 HELLO-ACK가 오지 않으면, 리셋으로 닫고(`SO_LINGER` 0) 모름인 채로
     다음 다시 걸기를 기다린다. "받아들여지지 않은 다시 걸기" 줄을 남긴다. 리셋으로 닫으므로, 이미 설치한 높은 rank는 FIN이 아니라
     리셋을 받아 모름이 된다.
   - HELLO의 세대 번호는 보낼 때마다 하나씩 늘린다(받아들여지지 않은 시도도 번호를 쓴다). 그래야 높은 rank가 이미 설치한 세대보다
     다음 HELLO의 번호가 늘 크다.
   - 높은 rank는 지금처럼 HELLO를 확인하고, 맞으면 HELLO-ACK를 보낸(200 ms로 묶음) 뒤 설치하고 재연결 줄을 남긴다. HELLO-ACK를 보내지
     못하면 설치하지 않고 닫는다.
3. **높은 rank의 확인 접속.**
   - 준비 때 모은 주소 중 자기보다 낮은 rank의 수신 대기 주소도 보관한다.
   - 모름인 낮은 rank마다 비차단 connect를 시작한다. 첫 시도는 소켓을 잃은 즉시, 그 뒤로는 500 ms마다다. 한 번은 500 ms로 묶는다.
   - 연결되면 확인 기록(새 메시지 종류) 하나를 보내고 바로 닫는다. 상태는 모름 그대로다(다시 걸기는 낮은 rank가 한다). 소켓을 잃을
     때마다 첫 응답에 "확인 접속 응답" 줄을 남긴다.
   - 거부되면 "확인 접속 거부" 줄과 닫힘 줄(`cause=ECONNREFUSED liveness=dead`)을 남기고 죽음으로 바꾼다.
   - 수신 대기 쪽은 받은 연결에서 확인 기록을 읽으면 조용히 닫는다(HELLO가 아니므로 지금처럼 거부한다).
4. **끊김 스위치.** 끊는 동안 새로 만드는 확인 접속 소켓에도 필터를 붙이고, 끊김이 끝나면 대기 중인 다시 걸기 소켓과 함께 뗀다.
5. **시작 줄과 정리.** helper 시작 때 `GIN/TS: helper liveness oneway=1 rank=<r>`를 남긴다. `gdakiTsStop`은 대기 중인 다시 걸기 소켓과
   확인 접속 소켓도 닫는다.
6. 기다림(`gdakiTsInitiate`의 재연결 기다림), 거절 문구, 라운드는 그대로다. 기다림 안에서도 확인 접속이 돌므로, 기다리는 중에 확인 접속이
   거부되면 기다림은 `ended=dead`로 끝난다.

**2. 시험 스위치(`pcm`, `ow`).** 기준 빌드 `pcm`은 `pc` 트리에 이것만 더한다. 변경분은 `pcm_layer.diff`(`pc` 트리 기준)와 전체 diff
`gin_transparent_pcm.diff`로 남긴다. 두 스위치 모두 꺼져 있으면 동작은 `pc`와 같다.
- `NCCL_GIN_TS_TEST_SOCK_UTO_MS=<ms>`: 이 프로세스 helper 소켓의 `TCP_USER_TIMEOUT`(기본 5 000 ms, 2388행)을 바꾼다. keepalive 설정은
  그대로다.
- `NCCL_GIN_TS_TEST_REFUSE_HELLO=<n>`: 이 rank가 확인을 통과한 재연결 HELLO 중 처음 n개를 거부하고 닫는다(그 HELLO마다 시험 거부 줄).
- 둘 중 하나라도 켜면 helper 시작 때 시험 스위치 줄을 남긴다.

**3. 실행기.** `../scripts/ts2/run_trial.sh`를 쓴다. 선택 하나를 더한다.
- `KILL_R0=1`(기본 0): rank 0을 띄운 뒤 `KILL_DELAY_MS` ms에 그 rank 0 프로세스를 끈다. 실행기가 띄운 `timeout` 프로세스의 자식
  `gin_ts2`를 PID로 찾아 SIGKILL을 보내고, `kill.out`에 `kill_mono_ms=<t> pid=<p> rank=0`을 남긴다.
- 기본값에서는 지금 동작 그대로다. 기존 rank 1 kill(`F4`)은 바꾸지 않는다.

**빌드.** 세션 스크래치 `$SCR`(`/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad`)에서 한다.
1. `agent_ts2pc`의 트리와 빌드 디렉터리를 `agent_ts2ow`로 복사한다. 의존 파일과 장치 manifest의 경로를 바꾸고 원래 시각을 돌려준다
   (gin-pair-check `build_pc.sh`와 같은 방식).
2. 스크래치 저장소에 `pc` 상태를 커밋하고 `pcm_layer.diff`를 적용한다. `make -n`으로 다시 컴파일되는 파일이 `gin_host_gdaki.cc`와
   버전 표시뿐인지 확인한 뒤 증분 빌드하고, libnccl을 `pcm` 번들로 옮긴다.
3. `pcm` 상태를 커밋하고 `ow_layer.diff`를 적용해 같은 방법으로 빌드하고, libnccl을 `ow` 번들로 옮긴다.
4. 드라이버는 새로 빌드하지 않고 `d4b1f082`를 복사한다.
5. 두 전체 diff로 pristine NCCL v2.32.3-1에서 각 트리가 재현되는지 확인한다.

이 폴더에 둘 스크립트는 `build_ow.sh`, `make_diff_ow.sh`, `deploy_ow.sh`다.

**배포.** `deploy_ow.sh`로 두 노드의 `pcm/`, `ow/`에 둔다. 대상 파일이 있으면 멈추고, 두 노드 md5, `ldd`, 기존 번들 md5를 확인한다
(8절). 확인 출력은 잘리지 않게 파일로만 받는다.

**실행.**
- 기존 셀은 `BUILD=ow bash ../scripts/ts2/batch.sh`로, `rc_mute8_f1_b`, `rc_mutekill_b`는 `../reconnect/cells.sh`의 정의를 빌드만 바꿔,
  `f2rel_b`와 `pc` 지연 셀은 `../pair_check/cells.sh`의 정의로 돈다.
- 새 셀, 대조 셀, `ow` 셀은 이 폴더의 `cells.sh`가 7절 조건대로 정의한다.
- hold는 이 폴더의 `hold.sh`에 두고, 각 hold를 `chain.sh`로 따로 `cluster_run.sh -w 10800 -t gow-<hold>`에 넣는다.

| hold | 내용 | 추정 `[추론]` |
|---|---|---|
| H0 smoke | `ow_r1in_f1_b`와 `ow_r0in_f1r1_b`는 `pcm` 2회, `ow` 1회. `ow_kill0_b`는 `ow` 2회, `pcm` 1회. `ow_hello_f1_b`는 두 빌드 1회씩. 경주 셀 `pc` 1회, `rc_mute8_f1_b@ow` 1회, 4 KiB 지연 `ow`와 `pc` 1회씩 | 7분 |
| H1 | 지연 4셀 × 5(섞어서), `f1_b`, `f3_b`, `bidirf_sym_b`, `f4_b`, `f2rel_b` × 5 | 9분 |
| H2 | `rc_mute8_f1_b`, `rc_mutekill_b` × 5, `ow_r1in_f1_b`의 `ow` 10회와 `pcm` 5회(2:1로 섞어서) | 10분 |
| H3 | `ow_r0in_f1r1_b`의 `ow` 10회와 `pcm` 5회(2:1로 섞어서), 경주 셀 `pc`와 `ow` 5회씩(1:1로 섞어서) | 10분 |
| H4 | `ow_kill0_b`의 `ow` 10회와 `pcm` 5회(2:1로 섞어서) | 7분 |
| H5 | `ow_hello_f1_b`의 `ow` 10회와 `pcm` 5회(2:1로 섞어서) | 6분 |

hold마다 잠금과 유휴 확인이 약 1분 더 든다. 클러스터 시간은 모두 55–65분이다 `[추론]`.

**채점.**
1. `../scripts/ts2/rows.py`로 hold 폴더마다 시행 CSV를 만든다.
2. `../s2_close/rows_extra.py`, `../pair_check/rows_pc.py`, 이 폴더의 `rows_ow.py`가 3.1의 열을 붙인다.
3. 이 폴더의 `score.py`가 [predictions.csv](predictions.csv)의 판정식을 3.2 문법대로 적용한다. 결과는
   `results/<날짜>/SCORE.md`와 `results/<날짜>/trials_scored.csv`다.

**출력.** 결과 폴더 `results/<날짜>/<hold 폴더>/`. 원시 로그는 Release에 올린다.

## 10. 완료 조건과 QA 기준

- [x] 모든 셀이 계획한 반복 수만큼 실행됐다. 제외와 실패를 따로 센 표가 있다.
- [x] 예측 28줄마다 판정(맞음, 틀림, 자료 부족)과 놓친 시행 목록이 있다.
- [x] 다른 에이전트가 `score.py`를 보지 않고 원자료에서 핵심 수치를 다시 셌다. 대상은 닫힘 원인과 생존 분류, 죽음 줄, 재연결 수와
  시각, 받아들여지지 않은 다시 걸기, 확인 접속, 기다림, 거절 사유와 시각, 투명 여부다.
- [x] 다른 에이전트가 `pcm_layer.diff`와 `ow_layer.diff`, 실행기 변경을 읽고 리뷰했다.
- [x] smoke와 제외 시행이 결과에 섞이지 않았다.
- [x] 새 빌드의 md5, 전체 diff, pristine + diff 확인 결과를 5절에 적었다.
- [x] 원자료를 Release에 올리고 `DATA.md`에 적었다.
- [x] hold 전후 mlx5 스냅숏에 새 명령 오류가 없었거나, 있었다면 그 줄의 내용을 12절에 적었다.

## 11. 작업 체크리스트

- [x] 질문, 가설, 셀 작성 (`DRAFT`)
- [x] 고정 절 완성, 상태 `PREREGISTERED`, 해시 기록을 커밋 하나로 만들고 그 커밋에 `prereg/` 태그
- [x] 코드 변경(시험 스위치, 생존 규칙, 실행기), 빌드, 배포
- [x] `cells.sh`, `hold.sh`, `chain.sh`, `rows_ow.py`, `score.py`
- [x] smoke 실행(채점 제외)
- [x] 본 실행 (`RUNNING`)
- [x] 채점 (`QA`)
- [x] 독립 재계산과 코드 리뷰
- [x] 결과 정리, 원자료 릴리스, PR
- [x] 결론 확정 (`COMPLETE`)

## 12. 실행 기록 (시간순)

| 시각 | 무엇을 했나 | 결과와 근거(경로, 커밋, 실행 ID) |
|---|---|---|
| 2026-10-08 | gin-reconnect 코드 리뷰 항목 1, 2, 4와 `pc` 트리의 소켓 코드를 읽고 설계를 정함 `[소스, 추론]` | 1절, 9절 |
| 2026-10-08 | Release 원자료에서 양쪽 끊김 65회의 닫힘 시각을 다시 셈 `[측정]`. rank 0이 먼저 닫힘 56회, rank 1이 먼저 9회. 닫힘은 자기 끊김 시작 4 571.6–4 833.5 ms 뒤. gin-reconnect kill 셀 15회에서 kill부터 첫 분류 기록까지 3 594.1–3 819.8 ms | `data-20261008`(`d1dd5ebd0e92`), `data-20261007`(`f2d11a86cc83`), `../reconnect/results/20261008/trials_scored.csv`, 세션 스크래치 `gow/race.py` |
| 2026-10-08 | 사용자가 이 후속 실험을 승인 | |
| 2026-10-08 15:13:18 | 사전 등록 | [PREREG.txt](PREREG.txt), 태그 `prereg/gin-oneway-v1` |
| 2026-10-08 15:14–15:17 | 시험 스위치 계층과 생존 규칙 계층 작성(`gin_host_gdaki.cc` 한 파일), 차례로 증분 빌드(두 번 모두 다시 컴파일된 파일은 `gin_host_gdaki.cc`와 버전 표시뿐). libnccl `pcm` `cd72f67a`, `ow` `b4af65c5`. 두 전체 diff로 pristine에서 각 트리 재현 확인. 실행기에 `KILL_R0` 선택 추가 | [build_ow.sh](build_ow.sh), [make_diff_ow.sh](make_diff_ow.sh), [pcm_layer.diff](pcm_layer.diff), [ow_layer.diff](ow_layer.diff), `../scripts/ts2/run_trial.sh` |
| 2026-10-08 15:18:42 | 두 노드의 새 디렉터리 `pcm/`, `ow/`에 배포. 두 노드 md5가 소스와 같고, 기존 번들 28개 파일의 md5가 배포 전후 같다 `[측정]`. 확인 출력은 파일로만 받았다 | [deploy_check.txt](deploy_check.txt), [deploy_ow.sh](deploy_ow.sh) |
| 2026-10-08 15:22:49–15:27:15 | smoke(`gow-H0`, 잠금 15:22:18), 15회, 채점 제외. 시험 조건은 의도대로 만들어졌다: 기준 빌드 한쪽 끊김 4회 모두 안 끊긴 쪽이 ECONNRESET을 받아 죽음으로 보고 장애를 거절했다. 새 빌드는 같은 조건에서 "모름"으로 두고 다시 연결해 투명했다. rank 0 kill 2회는 끊김이 끝난 뒤 rank 1의 확인 접속이 거부되어(ECONNREFUSED) 분류 기록 뒤 1.8, 2.1 ms에 거절했다. HELLO 거부는 새 빌드에서 다음 다시 걸기로 연결되고(끊김 끝 뒤 607 ms), 기준 빌드에서 FIN 죽음으로 거절됐다 `[측정]`. 8절의 구현 결함 조건과 시험 조건 변경에는 하나도 해당하지 않았다. 정상 종료 때 상대의 FIN이 죽음 줄로 남는 것을 보았다([DEVIATIONS.md](DEVIATIONS.md) 2절). mlx5 명령 오류 줄(rain 2, sunny 0)과 rain 펌웨어 명령 실패 수(31)는 전후가 같고 새 mlx5 줄은 0이다 | `results/20261008_smoke/`, `hold_H0.out`, `mlx5_new_H0.txt` |
| 2026-10-08 15:28 | smoke를 본 뒤 사후 분석 열(상대 정리 전 죽음 줄)을 정의하고 계산 스크립트를 둠. 판정식은 그대로 | [DEVIATIONS.md](DEVIATIONS.md) 2, 3절, [posthoc_ow.py](posthoc_ow.py) |
| 2026-10-08 15:29:04 | 본 실행 시작(상태 `RUNNING`). H1–H5를 [chain.sh](chain.sh)로 차례로 잡는다(`cluster_run.sh -w 10800`, 태그 `gow-H<k>`) | `results/20261008/chain.out` |
| 2026-10-08 15:29:35–15:33:40 | H1(`gow-H1`, 잠금 15:29:04): 지연 20회(`ow`와 `pc` 섞어서), 재현 셀 25회(`f1_b`, `f3_b`, `bidirf_sym_b`, `f4_b`, `f2rel_b`, 모두 `ow`). 8절 제외와 설정 확인 실패 0, 시작 실패 0, `left > 0` 0 `[측정]`. mlx5 명령 오류 줄(rain 2, sunny 0)과 rain 펌웨어 명령 실패 수(31)는 전후가 같고 새 mlx5 줄은 0이다 | `results/20261008/lat/`, `results/20261008/ow/`, `hold_H1.out`, `mlx5_new_H1.txt` |
| 2026-10-08 15:34:11–15:41:59 | H2(`gow-H2`, 잠금 15:33:40): 양쪽 8 s 끊김 재현 5회, 양쪽 끊김 중 rank 1 kill 재현 5회, 낮은 rank가 리셋을 받는 한쪽 끊김 `ow` 10회와 `pcm` 5회(2:1로 섞어서). 8절 제외와 설정 확인 실패 0, 시작 실패 0, `left > 0` 0 `[측정]`. mlx5 명령 오류 줄(rain 2, sunny 0)과 rain 펌웨어 명령 실패 수(31)는 전후가 같고 새 mlx5 줄은 0이다 | `results/20261008/ow/`, `results/20261008/pcm/`, `hold_H2.out`, `mlx5_new_H2.txt` |
| 2026-10-08 15:42:29–15:50:25 | H3(`gow-H3`, 잠금 15:41:59): 높은 rank가 리셋을 받는 한쪽 끊김 `ow` 10회와 `pcm` 5회(2:1로 섞어서), 시간 초과 시험 스위치 없는 경주 셀 `pc` 5회와 `ow` 5회(1:1로 섞어서). 8절 제외와 설정 확인 실패 0, 시작 실패 0, `left > 0` 0 `[측정]`. mlx5 명령 오류 줄(rain 2, sunny 0)과 rain 펌웨어 명령 실패 수(31)는 전후가 같고 새 mlx5 줄은 0이다 | `results/20261008/ow/`, `results/20261008/pcm/`, `results/20261008/pc/`, `hold_H3.out`, `mlx5_new_H3.txt` |
| 2026-10-08 15:50:56–15:55:38 | H4(`gow-H4`, 잠금 15:50:26): 양쪽 끊김 중 rank 0 kill `ow` 10회와 `pcm` 5회(2:1로 섞어서). 15회 모두 rank 0 kill 기록이 있고 rank 1에 첫 분류 기록이 있다. 8절 제외와 설정 확인 실패 0, `left > 0` 0 `[측정]`. mlx5 명령 오류 줄(rain 2, sunny 0)과 rain 펌웨어 명령 실패 수(31)는 전후가 같고 새 mlx5 줄은 0이다 | `results/20261008/ow/`, `results/20261008/pcm/`, `hold_H4.out`, `mlx5_new_H4.txt` |
| 2026-10-08 15:56:09–16:01:16 | H5(`gow-H5`, 잠금 15:55:38): 재연결 HELLO 거부 `ow` 10회와 `pcm` 5회(2:1로 섞어서). 8절 제외와 설정 확인 실패 0, 시작 실패 0, `left > 0` 0 `[측정]`. 본 실행 125회(셀 시행 105, 지연 20) 모두 제외 없이 계획 수를 채워 채우기 hold는 없다. mlx5 명령 오류 줄(rain 2, sunny 0)과 rain 펌웨어 명령 실패 수(31)는 전후가 같고 새 mlx5 줄은 0이다 | `results/20261008/ow/`, `results/20261008/pcm/`, `hold_H5.out`, `mlx5_new_H5.txt` |
| 2026-10-08 16:01:32 | `score.py`로 채점. 125회 모두 판정, 따로 셈 0. 예측 28줄 중 23줄 맞음, 5줄 틀림(죽음 줄이 없다는 다섯 예측. 정상 종료 FIN이 세어짐). 사후 분석 열로 다시 세면 그 다섯도 모두 판정식을 채운다(사전 등록 아님). 상태 `QA` | [SCORE.md](results/20261008/SCORE.md), [trials_scored.csv](results/20261008/trials_scored.csv), [posthoc_ow.py](posthoc_ow.py) |
| 2026-10-08 16:05–16:20 | 15절 수치를 원시 로그에서 따로 다시 셈(`score.py`의 열을 쓰지 않는 세션 스크래치 스크립트). 기다림, 재연결 시각, 거절 시각 8개 열의 범위가 `trials_scored.csv`와 같다 `[측정]`. 다른 에이전트의 독립 재계산은 아직이다 | 15절 |
| 2026-10-08 16:21:32 | 다른 에이전트가 원시 로그에서 독립 재계산. 판정 같음(23/28). 사후 집계도 따로 계산해 같음. 15절 서술 다섯 곳을 고치고, 사후 정의의 커밋 시각을 DEVIATIONS 3에 적음 | [results/20261008/qa_recount.md](results/20261008/qa_recount.md) |
| 2026-10-08 16:26:20 | 다른 에이전트가 두 계층과 실행기 변경을 리뷰. 측정 결과를 바꾼 것은 없음. 위험은 18절 | [qa/code_review.md](qa/code_review.md) |
| 2026-10-08 16:26:59 | 원자료 묶음 2개(본 실행 729파일, smoke 92파일)를 Release `data-20261008`에 올림. 받아서 체크섬 확인(릴리스 전체 12개), 원본과 주소 치환 외 차이 없음(821파일) | [DATA.md](../../../../DATA.md) |
| 2026-10-08 16:35 | 16–19절, README, 상위 문서 링크. 15절의 사후 정의 고정 시점 서술("본 실행 전")을 커밋 시각에 맞게 고침. 상태 `COMPLETE`, PR | 이 PR |
| 2026-10-09 | 용어: 본문의 "통신기"를 "communicator"로 바꿈(사용자 요청). 고정 절(2, 3, 7, 8절)과 `predictions.csv`, 채점기가 만든 `SCORE.md`는 그대로 둠 | 이 PR |

## 13. 사전 등록 이후 변경

> 기존 문장을 고치지 않고 여기에 덧붙인다. 변경이 많으면 `DEVIATIONS.md`에 두고 링크한다.

| 날짜 | 무엇을 | 이유 | 영향 범위 | 커밋 |
|---|---|---|---|---|
| 2026-10-08 | 사전 등록 뒤 정한 구현 세부, smoke에서 본 것(정상 종료 FIN이 죽음 줄로 세어짐), 사후 분석 열 | 각 행은 [DEVIATIONS.md](DEVIATIONS.md)에 있다 | 가설, 예측, 판정식, 셀, 반복 수, 제외 기준은 그대로 | `DEVIATIONS.md`의 git 기록 |

## 14. 원자료와 결과표

| 무엇 | 경로 또는 Release 자산 | n |
|---|---|--:|
| 채점 결과(예측별 판정, 놓친 시행, 셀별 시행 수와 따로 센 시행) | [results/20261008/SCORE.md](results/20261008/SCORE.md) | 예측 28줄 |
| 시행별 표(3.1의 열, 상태) | [results/20261008/trials_scored.csv](results/20261008/trials_scored.csv) | 시행 125(판정 125, 따로 셈 0) |
| 새 빌드 시행 파일(H1–H5) | `results/20261008/ow/` | 시행 80 |
| 기준 빌드 시행 파일(H2–H5) | `results/20261008/pcm/` | 시행 20 |
| 배포된 `pc` 경주 셀 시행 파일(H3) | `results/20261008/pc/` | 시행 5 |
| 지연 실행 파일(H1) | `results/20261008/lat/` | 실행 20 |
| hold 출력, 잠금 순서, mlx5 스냅숏 | `results/20261008/chain.out`, `hold_H1.out`–`hold_H5.out`, `snap_*.txt`, `mlx5_*_{rain,sunny}.txt`, `fwcmd_*.txt`, `mlx5_new_*.txt` | hold 5 |
| smoke(채점 제외) | Release `data-20261008`의 `..._oneway__results__20261008_smoke.tar.xz` | 시행 15 |
| 사후 분석(사전 등록 아님) | [posthoc_ow.py](posthoc_ow.py), 정의는 [DEVIATIONS.md](DEVIATIONS.md) 3절 | |
| 원자료 Release 자산 | Release `data-20261008`의 `harness__gpu-initiated__gin_recovery__oneway__results__20261008.tar.xz` | |
| 독립 재계산, 코드 리뷰 | [results/20261008/qa_recount.md](results/20261008/qa_recount.md), [qa/recount.py](qa/recount.py), [qa/code_review.md](qa/code_review.md) | |

시행 파일(`*_r0.log`, `*_r1.log`, `*.kv`, `*_meta.txt`, `*_kill.out`)과 hold 출력은 커밋하지 않는다. 커밋한 것은 `SCORE.md`와 `trials_scored.csv`뿐이다.

## 15. 결과 요약

> 예측별 판정과 핵심 수치. 수치마다 n과 근거 링크를 붙인다. 아직이면 `[미확인]`.

**채점.** 2026-10-08 16:01:32에 `score.py`가 사전 등록한 판정식을 그대로 적용했다
([SCORE.md](results/20261008/SCORE.md), [trials_scored.csv](results/20261008/trials_scored.csv)). 본 실행 125회(셀 시행 105, 지연 20)를 모두
판정했고, 8절로 따로 센 시행은 없다. smoke 15회는 채점하지 않았다. 예측 파일 sha256은 `PREREG.txt`와 같다. 예측 28줄 중 23줄이 맞았고
5줄이 틀렸다 `[측정]`. 틀린 5줄은 모두 "어느 rank도 죽음 줄이 없다"(`n_dead_r0 == 0 and n_dead_r1 == 0`)를 담은 예측이고, 그 이유는 표 아래에 있다.

| 예측 | id | 셀 | n | 맞은 시행 | 판정 |
|---|---|---|--:|---|---|
| 한쪽 끊김 시험이 의도대로 됨: 끊긴 rank 1이 먼저 시간 초과하고 그 리셋을 rank 0이 받음 | A0 | `ow_r1in_f1_b@ow` | 10 | 10/10 | 맞음 |
| rank 0이 리셋을 모름으로 두고, 두 rank 모두 죽음 줄이 없음 | A1 | 같음 | 10 | 0/10 | 틀림 |
| 두 rank가 한 번씩 다시 연결되고 rank 0은 끊김이 끝난 뒤 1.5 s 안 | A2 | 같음 | 10 | 10/10 | 맞음 |
| 12 s의 로컬 QP 오류가 투명하게 복구되고 거절과 장애 전 비동기 오류가 없음 | A3 | 같음 | 10 | 10/10 | 맞음 |
| 기준 빌드: rank 0이 리셋을 죽음으로 보고 장애를 "(ECONNRESET)"으로 거절함. rank 1은 살아 있고 다시 연결되지 않음 | K1 | `ow_r1in_f1_b@pcm` | 5 | 5/5 | 맞음 |
| 거울 방향 시험이 의도대로 됨: 끊긴 rank 0이 먼저 시간 초과하고 그 리셋을 rank 1이 받음 | B0 | `ow_r0in_f1r1_b@ow` | 10 | 10/10 | 맞음 |
| rank 1이 리셋을 모름으로 두고, 두 rank 모두 죽음 줄이 없음 | B1 | 같음 | 10 | 0/10 | 틀림 |
| 끊김 중 rank 1의 장애가 재연결을 기다리고, 끊김이 끝난 뒤 1.5 s 안에 재연결로 끝남 | B2 | 같음 | 10 | 10/10 | 맞음 |
| 그 뒤 rank 1이 시작 쪽으로 복구하고 투명함 | B3 | 같음 | 10 | 10/10 | 맞음 |
| 기준 빌드: rank 1이 리셋을 죽음으로 보고 장애를 "(ECONNRESET)"으로 거절함 | K2 | `ow_r0in_f1r1_b@pcm` | 5 | 5/5 | 맞음 |
| 끊김이 끝난 뒤 rank 1의 확인 접속이 거부되어 죽은 rank 0을 죽음으로 알아냄. 끊김 중에는 죽음으로 정하지 않음 | D1 | `ow_kill0_b@ow` | 10 | 10/10 | 맞음 |
| rank 1의 재시도 초과가 죽음 원인(ECONNREFUSED)으로 거절되고 "모름" 거절과 복구가 없음 | D2 | 같음 | 10 | 10/10 | 맞음 |
| 그 거절이 rank 1의 첫 분류 기록 뒤 2 s 안에 옴 | D3 | 같음 | 10 | 10/10 | 맞음 |
| 기준 빌드: rank 1이 죽은 rank 0을 모르고 10 s 상한 뒤 "모름"으로 거절함 | K3 | `ow_kill0_b@pcm` | 5 | 5/5 | 맞음 |
| rank 1이 첫 재연결을 거부해도 rank 0은 "받아들여지지 않음"으로 남기고, 두 rank 모두 죽음 줄이 없음 | E1 | `ow_hello_f1_b@ow` | 10 | 0/10 | 틀림 |
| 다음 다시 걸기로 두 rank가 한 번씩 다시 연결되고 rank 0은 끊김이 끝난 뒤 2 s 안 | E2 | 같음 | 10 | 10/10 | 맞음 |
| 12 s의 로컬 QP 오류가 투명하게 복구됨 | E3 | 같음 | 10 | 10/10 | 맞음 |
| 기준 빌드: rank 0이 재연결로 센 뒤 거부의 FIN을 읽고 상대를 죽음으로 보며 장애를 "(FIN)"으로 거절함 | K4 | `ow_hello_f1_b@pcm` | 5 | 5/5 | 맞음 |
| 시간 초과 시험 스위치 없이도 배포된 `pc`가 한쪽 끊김 뒤 살아 있는 rank 0을 "(ECONNRESET)"으로 거절함(5회 중 2회 이상) | U1 | `ow_r0in_nat_f1r1_b@pc` | 5 | 5/5 | 맞음 |
| 같은 경주 조건에서 새 빌드는 투명하고 두 rank 모두 죽음 줄이 없음 | U2 | `ow_r0in_nat_f1r1_b@ow` | 5 | 0/5 | 틀림 |
| 복구 재현 셀이 그대로 투명 | G1 | `f1_b`, `f3_b`, `bidirf_sym_b`, `rc_mute8_f1_b`(모두 `@ow`) | 셀마다 5 | 셀마다 5/5 | 맞음 |
| 양쪽 8 s 끊김에서 두 rank가 한 번씩 1.5 s 안에 다시 연결되고 죽음 줄이 없음 | G2 | `rc_mute8_f1_b@ow` | 5 | 0/5 | 틀림 |
| 끊김 없는 kill은 죽음 원인(FIN 또는 ECONNREFUSED)으로 거절되고 abort가 돌아옴 | G3 | `f4_b@ow` | 5 | 5/5 | 맞음 |
| 양쪽 끊김 중 kill된 rank 1은 다시 걸기 거부로 죽음 거절되고 "모름" 거절이 없음 | G4 | `rc_mutekill_b@ow` | 5 | 5/5 | 맞음 |
| 받는 쪽 abort 해제가 그대로 | G5 | `f2rel_b@ow` | 5 | 5/5 | 맞음 |
| 상대 QP 오류 뒤 teardown 때 두 rank의 모든 QP가 RTS | G6 | `f3_b@ow` | 5 | 5/5 | 맞음 |
| 4 KiB 지연 차이 0.40 µs 이하 | L1 | `lat_ow_on_4k@ow`, `lat_pc_on_4k@pc` | 실행 5 / 5 | 10.56 − 10.56 = 0 | 맞음 |
| 256 KiB 지연 차이 0.30 µs 이하 | L2 | `lat_ow_on_256k@ow`, `lat_pc_on_256k@pc` | 실행 5 / 5 | 38.91 − 38.91 = 0 | 맞음 |

**틀린 5줄의 이유** `[측정]`. 소켓이 이어진 채 정리 단계에 들어간 셀 시행 60회 모두에서(지연 실행은 20회 중 10회), 먼저 끝난 rank가 communicator를 정리하며 helper 소켓을 닫고, 아직 돌고 있는 다른 rank가
그 FIN을 `cause=FIN liveness=dead` 닫힘 줄로 남긴다. 사전 등록한 `n_dead_r<r>` 열은 이 줄도 센다. smoke에서 이것을 보았고, 판정식은 바꾸지
않았다([DEVIATIONS.md](DEVIATIONS.md) 2절). 그래서 위 다섯 셀은 정상으로 끝난 모든 시행에서 죽음 줄이 하나씩 있어 0/10, 0/5가 되었다.
- 사후 분석(사전 등록 아님, 정의는 이 다섯 셀의 첫 시행 전에 [DEVIATIONS.md](DEVIATIONS.md) 3절에 고정, 본 실행 첫 지연 실행보다는 11 s 뒤)으로 다른 rank의 communicator 정리 시작보다 앞선 죽음
  줄만 세면, 다섯 셀 모두 그런 줄이 하나도 없다. 같은 판정식에 이 열을 넣으면 A1 10/10, B1 10/10, E1 10/10, U2 5/5, G2 5/5다
  ([posthoc_ow.py](posthoc_ow.py) 출력).
- 같은 사후 열로 보면, 상대 정리 전에 죽음 줄이 있는 시행은 실제로 상대가 죽은 셀(`f4_b@ow` 5/5, `rc_mutekill_b@ow` 5/5, `ow_kill0_b@ow` 10/10)과
  기준 빌드가 살아 있는 상대를 죽음으로 본 셀(`pcm`의 한쪽 끊김 두 셀과 HELLO 거부 셀 15/15, `pc` 경주 셀 5/5)뿐이다. 기준 빌드의 낮은 rank kill 셀은
  0/5다(rank 1이 죽은 rank 0을 끝내 죽음으로 정하지 못함). 새 빌드의 한쪽 끊김, HELLO 거부, 경주, 양쪽 끊김 셀(40회)과 재현 셀 20회,
  지연 실행 20회(새 빌드 10, `pc` 10)에는 없다.
- 이 다섯 줄의 사전 등록 판정은 틀림 그대로 둔다. 예측이 측정하려던 것(살아 있는 상대를 죽음으로 보지 않음)은 사후 열로만 확인됐다 `[추론]`.

**수치를 다시 센 방법.** 아래 수치는 판정한 125회의 원시 로그(`<stem>_r0.log`, `<stem>_r1.log`, rank 0 kv, `kill.out`)를 `score.py`와 따로
읽어 셌다(세션 스크래치 `gow/recount_ow.py`). 기다림, 재연결 시각, 거절 시각 8개 열의 범위는 `trials_scored.csv`와 같았다 `[측정]`.
rank 1 시각은 rank 0 kv의 `clock_offset_ms`로 rank 0 시계에 옮겼다(보정 오차는 재지 않았다 `[미확인]`). 범위는 따로 적지 않으면 그 셀의 판정한
시행마다 하나씩 나온 값의 범위다. 시각은 다음을 나눠 적는다.
- 장애 훅 발사(`GIN/FAULT: GDAKI fault fired`의 `fire_mono_ms`)와 kill 시각(`kill.out`): 장애를 만든 때.
- 첫 분류 기록(그 rank의 첫 `device-classified error CQE` 줄): 라이브러리가 장애를 처음 본 때.
- 소켓 닫힘, 재연결, 확인 접속, 거절 줄의 `mono_ms`.

**1. 낮은 rank가 리셋을 받는 한쪽 끊김** (`ow_r1in_f1_b`, H2, `ow` n=10, `pcm` n=5) `[측정]`.
- 두 빌드 15회 모두 rank 1(끊긴 쪽)이 자기 끊김 시작 4 574.8–4 621.1 ms 뒤 ETIMEDOUT으로 닫혔고, rank 0은 그와 0.15 ms 안에(rank 0 시계,
  시계 보정 오차 범위) ECONNRESET을 받았다. 두 줄이 거의 같은 순간이라, 리셋은 rank 1의 keepalive가 끝날 때 커널이 보낸 것으로 본다 `[추론]`.
- `ow` 10회: rank 0은 리셋을 "모름"으로 두고 다시 걸어, rank 1의 끊김이 끝난 뒤 81.6–125.0 ms에 재연결했다(시도 8회, HELLO-ACK를 받은 뒤).
  rank 1도 같은 재연결 줄을 남겼다. rank 1의 확인 접속 응답 줄은 4회에 있었다(끊김 끝 뒤 87.3–119.0 ms). 나머지 6회에는 그 줄이 없다. 그 전에 재연결됐기 때문으로 본다 `[추론]`.
- `ow` 10회: 12 s의 rank 0 장애 훅부터 rank 0 첫 분류 기록까지 1.29–4.07 ms. 전체 재설정(QP 4개)으로 복구했고(시작 쪽 라운드 전체
  10 336–10 858 µs) 10/10 투명했다.
- `pcm` 5회: rank 0은 리셋을 죽음으로 보았다. 장애 훅부터 첫 분류 기록까지 1.86–2.27 ms, 그 뒤 0.51–0.91 ms에 "no helper socket to the peer
  (ECONNRESET)"로 거절했다. 거절 시각에 rank 1은 살아 있었고(5/5), 두 rank 모두 재연결 줄이 없었다.

**2. 높은 rank가 리셋을 받는 한쪽 끊김** (`ow_r0in_f1r1_b`, H3, `ow` n=10, `pcm` n=5) `[측정]`.
- 두 빌드 15회 모두 rank 0(끊긴 쪽)이 자기 끊김 시작 4 573.9–4 603.4 ms 뒤 ETIMEDOUT으로 닫혔고, rank 1은 그와 0.15 ms 안에(시계 보정 오차 범위) ECONNRESET을 받았다.
- 6.5 s의 rank 1 장애 훅(문맥 1)부터 rank 1 첫 분류 기록까지는 `ow` 5.37–14.10 ms, `pcm` 3.90–9.75 ms였다.
- `ow` 10회: rank 1은 리셋을 "모름"으로 두고 재연결을 기다렸다. 기다림은 2 069.7–2 098.2 ms였고 10/10 `ended=reconnected`로 끝났다.
  재연결은 rank 0의 끊김이 끝난 뒤 78.3–106.7 ms(rank 1 줄, rank 0 시계)였다. rank 1이 문맥 1만 좁힌 라운드(QP 1개, Commit 865–921 µs)로
  복구했고 10/10 투명했다. 복구 줄의 `total_us`(2 073 408–2 101 680 µs)는 이 기다림을 포함한다.
- `pcm` 5회: rank 1은 리셋을 죽음으로 보고, 첫 분류 기록 뒤 1.48–2.05 ms에 "no helper socket to the peer (ECONNRESET)"로 거절했다.
  이때 rank 0도 다시 연결한 직후(0.18 ms 뒤) FIN을 읽고 살아 있는 rank 1을 죽음으로 보아 자기 재시도 초과를 "(FIN)"으로 거절했다. HELLO 거부
  시험 스위치 없이도 재연결 확인 빈틈이 드러난 경우다. 같은 일이 `pc` 경주 셀 5회에도 있었다.

**3. 시간 초과 시험 스위치 없는 경주** (`ow_r0in_nat_f1r1_b`, H3, `pc` n=5, `ow` n=5) `[측정]`.
- 10회 모두 rank 0(끊긴 쪽)이 먼저 시간 초과했고 rank 1이 리셋을 받았다. 양쪽 끊김 65회에서 rank 0이 먼저였던 비율(56/65)과 어긋나지 않는다
  `[추론]`. smoke 1회(`pc`)는 rank 1이 먼저였다.
- 배포된 `pc` 5회는 모두 rank 1이 살아 있는 rank 0을 죽음으로 보고 첫 분류 기록 뒤 1.58–2.05 ms에 "(ECONNRESET)"으로 거절했다.
- `ow` 5회는 모두 "모름"으로 두고 2 058.2–2 095.0 ms 기다린 뒤 재연결(rank 1 줄, 끊김 끝 뒤 78.3–97.1 ms)로 복구해 투명했다.

**4. 끊김 중 낮은 rank kill** (`ow_kill0_b`, H4, `ow` n=10, `pcm` n=5) `[측정]`.
- rank 0은 자기 끊김 시작 5 346.5–5 400.5 ms 뒤에 kill됐다(15회). 그 전에 두 rank 모두 ETIMEDOUT("모름")으로 닫혔다.
- kill부터 rank 1의 첫 분류 기록(재시도 초과)까지 3 582.0–3 699.2 ms(`ow`), 3 661.9–3 683.4 ms(`pcm`)였다. 첫 분류 기록은 rank 1의 끊김
  끝 뒤 951.1–1 083.8 ms(`ow`)에 왔다.
- `ow` 10회: rank 1의 확인 접속이 자기 끊김 끝 뒤 287.8–335.5 ms에 거부되어(ECONNREFUSED) rank 0을 죽음으로 정했다. 끊김 중에는 죽음 줄이
  없었다. 재시도 초과는 첫 분류 기록 뒤 1.29–2.12 ms에 "RETRY_EXC and the peer's socket shows ECONNREFUSED"로 거절됐다.
- `pcm` 5회: rank 1은 10 000.1–10 000.6 ms 기다리다 상한에 닿아(`ended=bound`) 첫 분류 기록 뒤 10 001.6–10 002.8 ms에 "peer liveness unknown
  (ETIMEDOUT, no reconnect within 10000 ms)"로 거절했다.

**5. 재연결 HELLO 거부** (`ow_hello_f1_b`, H5, `ow` n=10, `pcm` n=5) `[측정]`.
- 두 rank 모두 자기 끊김 시작 4 572.7–4 629.4 ms 뒤 ETIMEDOUT으로 닫혔다(15회).
- `ow` 10회: rank 1이 끊김이 끝난 뒤 80.3–105.3 ms에 첫 재연결 HELLO를 거부했고, rank 0은 81.2–106.3 ms에 "받아들여지지 않음(FIN)"으로 남기고
  "모름" 그대로였다. 다음 다시 걸기로 끊김 끝 뒤 582.1–606.7 ms에 재연결했다(시도 9회). 12 s의 장애는 10/10 투명했다.
- `pcm` 5회: rank 0은 HELLO를 보내자마자 재연결로 셌고(끊김 끝 뒤 75.5–87.1 ms), rank 1의 거부를 FIN으로 읽어 죽음으로 보았다. 12 s의 장애는
  첫 분류 기록 뒤 0.22–0.69 ms에 "no helper socket to the peer (FIN)"으로 거절됐다. rank 1에는 재연결 줄이 없었다.

**6. 재현 셀** (H1, H2, `ow` 셀마다 n=5) `[측정]`.
- `f1_b`, `f3_b`, `bidirf_sym_b`, `rc_mute8_f1_b`는 셀마다 5/5 투명했다. `f3_b`는 teardown 때 두 rank의 QP 상태가 모두 `[3,3,3,3]`이었다.
- `rc_mute8_f1_b`: 두 rank가 한 번씩, 끊김이 끝난 뒤 76.7–99.8 ms(rank 0)에 재연결했다.
- `f4_b`: 5/5 "RETRY_EXC and the peer's socket shows FIN"으로 첫 분류 기록 뒤 1.09–1.67 ms에 거절했고, rank 0 abort는 `no error`였다.
- `rc_mutekill_b`: 5/5 "RETRY_EXC and the peer's socket shows ECONNREFUSED"로 첫 분류 기록 뒤 1.10–1.58 ms에 거절했다.
- `f2rel_b`: rank 1 abort 853.0–871.4 ms, 5/5 `async_error_kernel_stuck`, `no error`.

**7. 장애 없는 지연** (H1, 셀마다 실행 5회, 실행마다 3000번 반복의 p50) `[측정]`. 범위는 실행 5회의 p50 범위다.
- 4 KiB: `ow` 10.56–10.59 µs(중앙값 10.56), `pc` 10.56–10.62 µs(중앙값 10.56).
- 256 KiB: `ow` 38.91–38.94 µs(중앙값 38.91), `pc` 38.91–38.94 µs(중앙값 38.91).

**8. mlx5** `[측정]`. 여섯 hold(H0 smoke, H1–H5) 모두 전후 값이 같았다. 명령 오류 줄은 rain 2, sunny 0, rain 펌웨어 명령 실패 수는 31, 새 mlx5
커널 줄은 0이다(`mlx5_new_*.txt`).

**다른 날의 자료.** 1절의 양쪽 끊김 65회는 2026-10-07, 2026-10-08의 다른 빌드(`s2r`, `rc`)와 다른 hold에서 잰 것이다. 이 절의 셀과 같은 셀로 놓고
비교하지 않는다.

**QA 뒤 덧붙임.** 다른 에이전트의 독립 재계산과 코드 리뷰, 원자료 Release는 끝났다(12절, 16절). 위 서술 다섯 곳은 재계산에 따라 고쳤다.

## 16. QA와 재현성

- **독립 재계산:** 다른 에이전트가 `score.py`, `posthoc_ow.py`, 채점 결과를 보지 않고 원시 로그에서 다시 셌다
  ([results/20261008/qa_recount.md](results/20261008/qa_recount.md), [qa/recount.py](qa/recount.py)). 사전 등록 판정이 같다(28줄 중 23줄 맞음).
  각 rank의 정리 시작 시각을 로그에서 직접 찾아 사후 집계도 다시 했고, 결과가 같다. 고정 파일과 2, 3, 7, 8절은 태그 뒤 바뀌지 않았다.
  - 사후 정의의 커밋 시각은 본 실행 첫 시행(지연 실행)보다 11 s 늦었다. 그 정의가 영향을 주는 첫 시행보다는 앞이다([DEVIATIONS.md](DEVIATIONS.md) 3).
  - 바로잡은 서술: 리셋을 받은 시각의 범위(0.15 ms), 기준 빌드에서 낮은 rank도 살아 있는 상대를 FIN으로 죽음 처리한 사실, FIN 죽음 줄이 생기는
    범위(셀 60회 전부, 지연 20회 중 10회), 지연 실행의 빌드 구성, 확인 접속 줄이 없는 6회의 해석(`[추론]`).
- **코드 리뷰:** 다른 에이전트가 `pcm_layer.diff`, `ow_layer.diff`, 실행기 변경을 읽었다([qa/code_review.md](qa/code_review.md)). 측정 결과를 바꾼
  것은 없다. 위험은 18절에 적었다.
- **재현:** [gin_transparent_ow.diff](gin_transparent_ow.diff)(pristine NCCL v2.32.3-1 기준)로 만든다. libnccl md5 `b4af65c5`, 기준 `pcm` md5 `cd72f67a`([deploy_check.txt](deploy_check.txt)).

## 17. 결론

- **한쪽 방향으로만 끊겨도 살아 있는 상대를 죽었다고 보지 않게 됐다.** 리셋을 "모름"으로 두고 다시 연결해, 어느 방향이 끊겨도 재연결 뒤 투명하게
  복구했다. 기준 빌드는 같은 상황에서 살아 있는 상대를 리셋 때문에 죽음으로 보고 거절했고, 시험 스위치 없는 실제 경주에서도 같은 오판이 나왔다.
- **진짜 죽은 상대는 어느 rank에서든 죽음으로 판정했다.** 낮은 rank가 죽으면 높은 rank의 확인 접속이 거부되어, 첫 분류 기록 뒤 1.29–2.12 ms에
  거절했다. 기준 빌드는 10 s를 기다린 뒤 "모름"으로 거절했다.
- **재연결 확인 빈틈을 막았다.** 상대가 HELLO를 거부해도 죽음으로 보지 않고 다음 시도에서 다시 연결했다.
- 사전 등록 예측 28개 중 23개가 맞았다. 틀린 5개는 실행이 정상으로 끝날 때의 FIN까지 센 판정식의 실수 때문이고, 상대가 정리를 시작하기 전의
  죽음 판정만 세는 사후 집계로는 5개 모두 맞았다 `[추론]`.

## 18. 한계

- 연결 거부 한 번을 죽음의 확인으로 본다. 방화벽이 연결을 거부하는 환경에서는 살아 있는 상대도 죽음으로 볼 수 있다(코드 리뷰).
- 복구 라운드 도중에 받은 리셋은 여전히 최종 거절로 이어진다. HELLO-ACK가 1 s 상한 뒤에 도착하는 경우처럼, 이 수정으로 새로 생긴 경로도 있다
  (코드 리뷰, 이번 시행에는 없었다).
- HELLO와 확인 접속에 고유값(nonce)이 없어, 같은 포트를 다른 프로세스가 쓰면 잘못 연결되거나 죽은 상대가 계속 "모름"으로 남을 수 있다.
- 두 시험 스위치가 새 빌드에 들어 있어 이 빌드는 시험용이다. 2 rank, 노드 한 쌍이다.

## 19. 다음 작업

- 연결 거부를 두 번, 시간을 두고 확인하거나 오류 큐로 네트워크 거부와 호스트 거부를 가른다.
- 라운드 안의 리셋도 "모름"으로 두고 장애를 다시 넣어 재연결을 기다리게 한다.
- HELLO, HELLO-ACK, 확인 접속에 communicator별 고유값을 싣는다.

## 20. 참고자료

- `../reconnect/EXPERIMENT.md`, `../reconnect/qa/code_review.md`(gin-reconnect, 항목 1, 2, 4)
- `../pair_check/EXPERIMENT.md`(gin-pair-check, 기준 빌드 `pc`)
- `../pair_reset/EXPERIMENT.md`(gin-pair-reset)
- `../s2_close/EXPERIMENT.md` 3.2절(판정식 문법)
