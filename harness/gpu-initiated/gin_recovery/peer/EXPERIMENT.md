# GIN 투명 복구: 상대별 대기 해제와 남은 리뷰 지적 고치기 (gin-peer)

**목적:** 한 상대에 대한 거절이 그 상대에 걸린 장치 대기만 풀게 하고, gin-harden 독립 리뷰의 중간 지적 셋과 gin-handoff 리뷰의
원인 문제를 한 계층으로 고치며, 실행기의 랑데부 포트 문제를 고친 뒤, 고친 동작과 바뀌지 않아야 할 동작을 사전 등록한 예측으로 잰다.

| 항목 | 값 |
|---|---|
| 상태 | `COMPLETE` |
| 담당자 | @unionxic |
| 작성일 | 2026-10-09 |
| 기준 브랜치와 커밋 | `exp/gin-peer` @ `45a5588b` (master) |
| 사전 등록 태그 | `prereg/gin-peer-v1` (`551c796f`, 상태를 `PREREGISTERED`로 바꾼 바로 그 커밋) |
| 마지막 갱신 | 2026-10-09, 마감: 본 실행 H1–H8, 채점(37/37 맞음), 독립 재계산, 코드 리뷰, Release(10–20절) |

표시: `[측정]` 원자료나 시행별 표에서 확인, `[소스]` 코드에서 읽음, `[추론]` 해석, `[미확인]` 확인 안 함.

이 문서의 코드는 함수 이름으로 가리킨다. 파일은 따로 적지 않으면 `src/transport/net_ib/gdaki/gin_host_gdaki.cc`(빌드 트리는 세션 스크래치
`agent_ts2hq/nccl-src`)다. 용어(helper, 사용자 devComm, abort 단어, 거절, 죽음, 라운드, 커밋, 펌웨어 명령 단계, 첫 분류 기록, 중단 shrink, 오류
올림)는 [../harden/EXPERIMENT.md](../harden/EXPERIMENT.md)와 [../handoff/EXPERIMENT.md](../handoff/EXPERIMENT.md) 머리말과 같다. 이 실험에서 더
쓰는 말:
- 상대별 단어: 이 계층에서 communicator마다 두는 abort 단어 배열의 칸 하나. 칸 0은 사용자 devComm의 abort 단어(상대를 모르는 대기가 읽음), 칸
  1 + p는 GIN 상대 p의 단어(그 상대로 가는 QP의 게이트가 주소를 들고 있고, 그 QP에서 기다리거나 보내는 장치 스레드가 읽음).
- 다시 보내기 계획: 라운드가 커밋한 뒤 상대가 실행하지 못한 WQE를 다시 보내기 위해, 그 WQE들을 읽고 범위와 opcode를 검사해 만드는 목록
  (gin-harden 9절 1번 (d)의 첫째 단계).
- 원인 분류: 오류 올림마다 적는 원인. 상대 쪽(죽음, 떠남, 상대가 알린 실패)과 이 rank 쪽(local), 가릴 수 없음(unknown).
- 간선 a>b, 생존 rank: [../multirank/EXPERIMENT.md](../multirank/EXPERIMENT.md) 머리말과 같다.

예측 id, 셀 이름, 빌드 키는 원자료를 찾는 키로만 괄호나 표의 열에 둔다.

빌드 키는 넷이고 드라이버 키가 하나 더 있다. 모두 번들 디렉터리 `$HOME/gi-bundle/gin_ts2/<키>/`다.

| 키 | 내용 | 쓰는 곳 |
|---|---|---|
| `hq` | 이 실험의 연구 빌드: gin-handoff `hf` 소스 위에 9절 1번의 계층. 이 실험의 `gin_ts2` | 새 셀, 회귀 셀 |
| `hqp` | 같은 소스를 `-DNCCL_GIN_TS_PRODUCTION`으로 컴파일한 운영 빌드. 같은 `gin_ts2` | 운영 kill, 지연 |
| `hf`, `hfp` | gin-handoff 연구, 운영 빌드(배포된 번들 그대로: libnccl `b6372d86`, `1ae4ce9a`, 드라이버 `9493584d`) | 대조, 지연 기준 |
| `mr/hq` | 이 실험의 `gin_mr`(이 폴더의 `gin_mr.cu`, `hq` 헤더로 빌드). libnccl은 실행기가 고른 번들(`hq` 또는 `hf`)에서 씀 | 랭크 4개 셀 전부 |

## 1. 배경과 연구 질문

사용자가 지금 고치라고 한 것은 넷이다. 모두 앞 실험의 측정이나 리뷰가 짚은 것이고, 줄과 수는 그 자리에서 다시 확인했다.

**1. 랑데부 포트.** 실행기 셋(`../harden/run_trial_hd.sh`, `../multirank/run_mr.sh`, 그리고 그 드라이버)이 랑데부 포트를 46000–48999에서 고르고,
gin-harden의 운영 셀은 helper 포트 51700–51715를 고정했다. 두 범위 모두 두 노드의 임시 포트 범위(32768–60999) 안이다. rain에서 다시 확인했다:
`ip_local_port_range`는 32768–60999, 예약 포트는 없다 `[측정, 2026-10-09]`. 어젯밤 본 실행에서 "bind: Address already in use"로 따로 센 시행이
7회였다: gin-harden 4회(247회 중), gin-handoff 1회(116회 중), gin-multirank 2회(137회 중) `[측정: 세 실험의 trials_scored.csv에서 다시 셈]`. 또
드라이버의 랑데부에는 확인이 없어, 그 포트를 다른 프로세스가 듣고 있었다면 rank 1–3이 자기 rank 번호 4바이트를 그 소켓에 썼을 수 있다
(`../multirank/EXPERIMENT.md` 18절, `../handoff/qa/code_review.md` L1) `[소스]`.

**2. 상대 하나의 거절이 communicator 전체의 대기를 푼다.** gin-harden의 사용자 abort 단어는 communicator마다 하나다(`ncclGinTsUserAbortRaise`).
거절, 죽음, 펌웨어 감시가 그 단어를 올리면, 장치의 모든 대기(`waitSignal` 포함)가 오류로 끝나고, 게이트에서 쉬던 대기는 자기 QP를 실패로 표시한다
(`gin_gdaki.h` `tsParkStable`) `[소스]`. gin-multirank가 그 결과를 쟀다: 랭크 4개에서 rank 3을 kill하면 상대별 flush에서 살아남은 rank 사이의 받는 쪽
6개가 10회 모두 실패했고 보내는 쪽 6개는 10회 모두 끝까지 갔으며, 문맥 전체 flush에서는 보내는 쪽 6개가 10회 모두 실패했다
`[측정: ../multirank/results/20261009/trials_scored.csv에서 다시 셈, 셀마다 n=10]`.

**3. gin-harden 독립 리뷰의 중간 지적 셋**(`../harden/EXPERIMENT.md` 9절 1번 (g)).
- (a) 다시 보내기 계획의 검사가 rank마다다. 시작 쪽은 ACK를 받은 뒤 검사하고 다시 보낸 다음 DONE을 보내는데, 응답 쪽은 DONE을 받은 뒤에야 검사한다.
  응답 쪽이 거부하면 시작 쪽은 이미 다시 보냈다. gin-harden은 이 경우(거부한 rank 0이 응답 쪽인 시행)를 8절에서 제외로만 다뤘다 `[소스]`.
- (b) 펌웨어 감시가 문맥마다 한 번 발동하면 영구다. 명령 하나가 3 s를 넘으면 communicator 단어가 올라가고 `surfaced`가 서서 그 뒤 라운드는 모두
  거절된다(`gdakiTsWatchdog`, `gdakiTsFwCheck`, `gdakiTsSurface`) `[소스]`. gin-harden과 gin-handoff는 이 때문에 펌웨어 초과 시행을 제외 규칙으로
  뺐다.
- (c) ACK를 기다리다 취소한 라운드가 이미 커밋한 응답 쪽과 엇갈리면, 응답 쪽은 거절하고 그 뒤 시작 쪽의 다시 걸기(HELLO)를 닫거나(높은 rank)
  확인 접속(PROBE)에 답만 하고 다시 걸지 않아(낮은 rank), 다시 넣은 장애는 재연결 기다림(`NCCL_GIN_TS_RECONNECT_MS`, 10 s)을 다 쓴 뒤에야
  "모름"으로 거절된다 `[소스]`.
- 낮은 지적 셋도 함께 고친다: 오래된 첫 거부도 죽음 판정에 센다(시간 창 없음), 상한 넘김이 다시 시도와 범위 재실행도 라운드로 센다, 취소 계수가
  역할마다 다르다(시작 쪽은 다시 넣은 것만, 응답 쪽은 모두) `[소스]`.

**4. shrink 넘기기가 원인을 보지 않는다**(`../handoff/qa/code_review.md` M1). gin-handoff의 규칙은 오류가 *누구를 위해* 올라갔는지만 본다. 거절은
그 원인이 이 rank 쪽이어도(커밋 실패, 펌웨어 초과, 라운드 안의 복사 상한 초과) 거절한 상대를 적으므로, 랭크 3개 이상에서는 그 상대를 빼는 중단
shrink가 원인이 로컬인데도 넘어간다 `[소스]`. 같은 리뷰의 M2: 넘긴 뒤의 아이 communicator가 자기 devComm(GIN 문맥)을 여는 경우는 돌려 본 적이
없다 `[미확인]`.

**질문.**
1. 랑데부 포트를 임시 포트 범위 밖에서 고르고 두 노드에서 비어 있는지 확인하며 랑데부를 확인하면, bind 실패가 없어지고 다른 프로세스의 수신 대기에
   아무것도 보내지 않는가.
2. 상대별 단어로, rank 3의 죽음이 살아남은 rank 사이의 대기를 풀지 않고 그 간선들이 끝까지 정상인가. 상대를 모르는 대기(`waitSignal`)는 어떻게
   되는가.
3. (a) 응답 쪽이 커밋과 ACK 전에 계획을 검사하면, 응답 쪽이 거부할 때 어느 rank도 다시 보내지 않는가. (b) 펌웨어 초과가 그 라운드만 거절하고,
   명령이 돌아온 뒤 다른 상대와의 라운드는 복구되는가. (c) 거절한 상대가 다시 걸기나 확인 접속에 FAIL로 답하면, 취소된 라운드의 다시 시도가 재연결
   한도를 기다리지 않고 바로 끝나는가.
4. 원인을 보는 넘김 규칙이 로컬 원인의 shrink는 막고 상대 쪽 원인의 shrink는 넘기는가. 넘긴 뒤 아이가 자기 devComm을 열어 통신하는가.
5. 이 계층이 기존 셀의 판정과 빠른 경로의 지연을 바꾸지 않는가.

## 2. 가설

| id | 가설 | 다음이 관측되면 틀린 것이다 |
|---|---|---|
| H1 | 상대별 단어를 두면 한 상대의 거절은 그 상대의 QP에 걸린 장치 스레드만 풀고, 상대를 모르는 대기는 communicator 전체의 일(abort, 중단 shrink, revoke, 모든 상대의 거절)에만 풀린다. 그래서 랭크 4개에서 죽은 rank 하나 때문에 살아남은 rank 사이의 상대별 통신이 끊기지 않는다 | rank 3 kill 셀(상대별 flush)에서 살아남은 간선 6개가 모두 정상인 시행이 9/10 미만이다. 또는 생존 rank가 devComm 단어를 올린 시행이 2회 이상이다 |
| H2 | 다시 보내기 계획을 두 rank 모두 자기 커밋 전에 검사하면, 어느 쪽이 거부하든 아무도 다시 보내지 않는다 | 응답 쪽 거부 셀에서 복구 줄이 있거나 rank 0이 계획을 세운 시행이 2회 이상이다 |
| H3 | 펌웨어 감시의 판정을 라운드와 상대 단위로 하면, 초과는 그 라운드의 상대만 거절하고 뒤의 라운드는 복구된다 | 랭크 4개 펌웨어 셀에서 rank 2와 rank 0의 라운드가 복구되지 않거나, rank 0이 rank 1 말고 다른 상대를 거절한 시행이 2회 이상이다 |
| H4 | 거절한 rank가 상대의 다시 걸기나 확인 접속에 FAIL로 답하면, 취소된 라운드를 다시 시도하는 rank는 재연결 한도를 기다리지 않는다 | 경합 셀에서 끊김 끝 1.5 s 안에 그 이유로 거절하지 않은 시행이 2회 이상이다(HELLO 형태), 1회 이상이다(PROBE 형태, n=5) |
| H5 | 오류 올림마다 원인을 적고 상대 쪽 원인만 넘기면, 로컬 원인의 shrink는 순정 답을 지키고 상대 쪽 원인의 shrink는 넘어가며, 넘어간 아이는 자기 devComm으로 통신한다 | 로컬 원인 셀에서 shrink가 넘어간 시행이 2회 이상이다. 또는 상대 쪽 원인 셀(상대가 알림, 죽음)에서 넘어가지 않은 시행이 2회 이상이다. 또는 랭크 4개 kill 뒤 아이의 devComm 통신이 9/10 미만이다 |
| H6 | 임시 포트 범위 밖의 확인된 포트와 확인하는 랑데부로 bind 실패와 남의 소켓으로 보내는 바이트가 없어진다 | 본 실행에서 bind 실패가 1회라도 있다. 또는 가짜 수신 대기가 우리 rank에게서 1바이트라도 받는다 |
| H7 | 이 계층은 상대가 하나뿐인 랭크 2개에서 앞 빌드와 같게 동작하고 빠른 경로의 지연을 바꾸지 않는다 | 회귀 셀에서 예측과 다른 시행이 나온다. 또는 지연 차이가 예측 범위 밖이다 |

## 3. 사전 예측 (측정 전에 작성)

**고정 시점.** 예측은 pilot(9절의 hold P0, P1, 2026-10-09) 뒤에 확정했다. pilot 22회(랭크 2개 14회, 랭크 4개 8회)를 시행마다 로그와 kv로
대조했고, 무엇을 보고 무엇을 고쳤는지는 12절에 있다. pilot 뒤에 예측 문장, 판정식, 기준 수, 셀 키, 반복 수는 하나도 바꾸지 않았다
([predictions.csv](predictions.csv) sha256 `dccdf05c819976a067950aae2649cd33b8da161a506214633f64cab9402884db`, 초안 커밋과 같음). 바꾼 것은 경합
셀 두 개의 조건(응답 쪽이 12 s 머묾)과 그것을 확인하는 설정 확인 하나다(7, 8절). 8절의 규칙대로 바뀐 두 셀은 태그 전에 pilot P2로 한 번 더
돌린다. 예측은 태그 `prereg/gin-peer-v1`을 단 커밋에서 고정된다. pilot 시행은 채점하지 않으며, 그 결과 폴더(`results/20261009_pilot/`)는 채점
대상 폴더와 따로 둔다. 태그 뒤에는 2, 3, 7, 8절과 `predictions.csv`를 고치지 않는다.

**pilot이 남긴 의심.** pilot은 셀마다 1회라 판정이 아니다.
- 경합 셀의 예측 넷(C1–C4)은 pilot 4회 모두에서 조건과 달랐다. 원인은 하네스였다: 응답 쪽이 거절 0.34–0.38 s 뒤 끝나, 시작 쪽의 다시 걸기와 확인
  접속이 모두 연결 거부를 받고 상대를 죽음으로 거절했다 `[측정]`. 셀을 고쳤고 예측은 그대로 두었다. 고친 셀의 pilot P2(4회, 12절)에서는 네
  예측의 조건이 모두 맞았다: `hq`는 응답 쪽이 FAIL로 답하고 시작 쪽이 끊김 끝 233 ms와 272 ms 뒤 거절했고, `hf`는 끊김 끝 8 375 ms와 8 270 ms 뒤
  "liveness unknown"으로 거절했다 `[측정, 셀마다 n=1]`. P2로 읽기 오류는 드러나지 않아 예측은 바꾸지 않았다.
- pilot 시행이 있는 나머지 예측 23개(A1, A2, B1–B5, K1–K4, H1–H3, H5–H8, Q2, Q3, R1의 `f1_b`, R7, P1)는 그 1회에서 조건이 맞았다 `[측정, n=1]`.
- pilot 시행이 없는 예측: A3, K5, H4, R1의 `f3_b`와 `bidirf_sym_b`, R2–R6, P2. Q1은 본 실행 전체에서 센다(pilot 22회에서 bind 실패 0).

예측 원문은 [predictions.csv](predictions.csv)이고 37줄이다. `kind`는 N(새 동작), C(대조), R(회귀)다.

### 3.1 판정에 쓰는 열

시행마다 한 줄이다.
- 랭크 2개 시행: 열은 `../scripts/ts2/rows.py`, `../s2_close/rows_extra.py`, `../pair_check/rows_pc.py`, `../oneway/rows_ow.py`,
  `../harden/rows_hd.py`, `../handoff/rows_hf.py`가 원래 정의 그대로 만들고(각 실험 3.1절), 이 폴더의 [rows_pq.py](rows_pq.py) `extra_pq2()`가
  새 열을 붙인다.
- 랭크 4개 시행: `../multirank/rows_mr.py`의 `rows_of()`(정의는 `../multirank/EXPERIMENT.md` 3.1절)에 `extra_pq4()`가 새 열을 붙인다.
- 새 열의 정의 원문은 `rows_pq.py` 머리말이다. 요약:

| 열 | 정의 |
|---|---|
| `pq_on_r*`, `n_pq_on` | 이 실험 시작 줄 `GIN/TS: peer=1 rank=<r> per_peer_words=1 ...`이 있는 rank |
| `n_uapeer_r*`, `uapeer_r*`, `n_uapeer`, `uapeer` | 상대별 단어 줄 `GIN/TS: user devComm waits on rank <p> released rank=<r> why=<w>`의 수와 "R-P" 목록 |
| `n_uaerr_r*`, `uaerr_why_r*`, `n_uaerr` | devComm 단어 줄 `GIN/TS: user devComm waits released rank=<r> why=<w>` 중 why가 declined, peer-dead, fw-watchdog인 줄(abort, revoke, shrink는 communicator 자신의 정리라 세지 않음) |
| `causes_r*`, `cause_r*`, `causes`, `n_cause_peerdead`, `n_cause_local` | 원인 줄 `GIN/TS: rank <r>: GIN error raised for rank <p> cause=<c>`의 "p:c" 목록, 첫 원인, 원인별 수 |
| `n_failans_r*`, `failans_r*`, `n_peerfail_r*`, `peerfail_r*` | `answered a <re-dial\|probe> of declined rank <p> with FAIL` 줄과 `rank <p> declined this pair (FAIL on <re-dial\|probe>)` 줄 |
| `n_planok_r*`, `planok_role_r*`, `n_planrej_r*`, `planrej_qp_r*` | 계획 검사 통과 줄 `re-post plan to rank <p> validated: ... role=<role>, before this rank's commit`과 거부 줄(형식은 gin-harden 그대로) |
| `n_fwover_r*`, `fwover_phase_r*`, `fwover_ms_r*`, `fwover_peer_r*`, `fwover`, `n_fwold*` | 이 계층의 감시 줄(`firmware command phase <ph> has run <x> ms, ... device waits on rank <p> are released`)의 수, 단계, 시간, 상대, "R-P:단계" 목록. `n_fwold`는 앞 빌드 형식의 감시 줄 수 |
| `n_cancel_ack_r*`, `cancel_ms_r*`, `declwhy_r*`, `decl_ms_r*`, `muteoff_ms_r*`, `decl_after_unmute_ms_r*` | ACK 기다림 중 취소 줄 수와 첫 취소 시각, 첫 거절의 사유와 시각, 첫 끊김 끝 시각, 첫 거절 − 끊김 끝(같은 rank의 시계) |
| `n_rec_any`, `rec_20`, `rec_02` | 두 rank의 복구 줄 수. rank 2의 시작 쪽 복구(상대 0), rank 0의 응답 쪽 복구(상대 2) |
| `n_bad_0_23`, `dead_rx_timeout`, `dead_tx_failed`, `surv_rx_timeout` | 간선 0>2, 0>3, 2>0, 3>0 중 정상이 아닌 수. kill 셀: 죽은 rank에서 오는 받기가 "timeout"으로 끝난 수, 죽은 rank로 가는 보내기가 실패한 수, 생존 rank 사이 받기가 "timeout"으로 끝난 수 |
| `n_hoff_ok`, `n_hoff_keep`, `keep_why_r0` | 넘김 줄과 유지 줄 수(모든 rank), rank 0의 첫 유지 사유 |
| `ch_ok_ranks`, `ch_created_ranks`, `ch_timeout_ranks`, `ch_shrink_fail_r0`, `ch_tx_ok_sum`, `ch_rx_ok_sum` | 드라이버 kv(9절 2번): 아이 통신이 정상인 rank 수, 아이가 n − 1 rank로 생긴 rank 수, 단계 한도에 걸린 rank 수, rank 0의 shrink 실패, 아이 간선 결과의 합 |
| `rdv_r*`, `rdv_decoy_r1`, `n_rdv_verified`, `n_decoy_rejected`, `decoy_conns`, `decoy_bytes`, `occupy_skipped` | 드라이버 kv의 랑데부 확인 결과, 가짜 수신 대기(`<stem>_decoy.out`)가 받은 연결과 바이트, 실행기 meta의 "막아 둔 첫 후보를 건너뜀" |

**새 로그 줄과 바뀐 줄** `[소스, 9절의 변경으로 고정]`. 연구 빌드(`hq`)에서는 모두 WARN이다. 운영 빌드(`hqp`)에서 "정보" 줄은 INFO다.

| 줄 | 수준(운영) | 형식 |
|---|---|---|
| 시작 | 정보 | `GIN/TS: peer=1 rank=<r> per_peer_words=1 fw_watchdog=per_round plan_before_commit=1 fail_on_reconnect=1 handoff_rule=cause refusal_forget_ms=5000` |
| 상대별 해제 | WARN | `GIN/TS: user devComm waits on rank <p> released rank=<r> why=<declined\|peer-dead\|fw-watchdog> mono_ms=<t>` |
| devComm 단어 | WARN(abort, revoke, shrink는 정보) | 형식 그대로. 거절과 죽음, 초과에서는 이 rank의 모든 상대 단어가 올라간 뒤에만 나오고, 바로 뒤에 정보 줄 `every peer of this rank is declined` |
| 원인 | 정보 | `GIN/TS: rank <r>: GIN error raised for rank <p> cause=<local\|peer-dead\|peer-left\|peer-reported\|unknown>[ (firmware overrun)] mono_ms=<t>`. peer-reported는 상대가 NACK나 FAIL에 자기 쪽 원인(local)을 실어 보낸 경우만이다(9절 1번 (e)) |
| 감시 | WARN | `GIN/TS: watchdog rank=<r>: firmware command phase <ph> has run <x> ms, more than NCCL_GIN_TS_FW_MS=<n>; device waits on rank <p> are released with an error and that round declines when the command returns (round <k>; later rounds are not affected) mono_ms=<t>`. 앞 빌드의 `the fault surfaces` 줄은 초과에서 더는 나오지 않는다 |
| 계획 통과 | 정보 | `GIN/TS: rank <r>: re-post plan to rank <p> validated: <q> qp(s), <w> WQE(s), role=<initiator\|responder>, before this rank's commit mono_ms=<t>` |
| FAIL 답 | 정보 | `GIN/TS: rank <r>: answered a <re-dial\|probe> of declined rank <p> with FAIL mono_ms=<t>`, 받는 쪽 `GIN/TS: rank <r>: rank <p> declined this pair (FAIL on <re-dial\|probe>) mono_ms=<t>` |
| 거부 잊기 | 정보 | `GIN/TS: rank <r>: refusal by rank <p> from <x> ms ago forgotten (older than 5000 ms) mono_ms=<t>` |
| 유지(넘김) | WARN | 형식 그대로. 새 사유: `it was raised for rank <w> (GIN rank <p>) with a cause that is not the peer's (<local\|unknown>)` |
| 거절 | WARN | 형식 그대로. 새 사유: `peer NACK (its re-post plan was rejected)`, `peer NACK (its waits on this rank were already released)`, `the peer declined this pair (FAIL on reconnect)`, `the device waits on the peer were already released` |

**드라이버 kv**(9절 2번): 랭크 2개 `rdv`, `rdv_rejected`, `rdv_foreign`, `rdv_port`, `rdv_decoy`. 랭크 N개는 같은 랑데부 키와 `ch_shrink_rc`,
`ch_shrink_ms`, `ch_newcomm`, `ch_parent_async_after`, `ch_nranks`, `ch_rank`, `ch_devcomm_rc`, `ch_tx_<ab>_*`, `ch_rx_<ab>_*`, `ch_tx_ok`, `ch_rx_ok`,
`ch_async`, `ch_destroy_rc`, `ch_outcome`(ok, created, shrink_failed, devcomm_failed, traffic_failed, timeout).

### 3.2 셀 키와 판정식 문법

셀 키(`cell@build`, 랭크 4개는 `build` = libnccl 키), 판정 대상(8절 제외를 거친 시행), "자료 부족" 규칙, 판정식 문법은
`../harden/EXPERIMENT.md` 3.2절과 같다(곧 `../s2_close/EXPERIMENT.md` 3.2절). [score.py](score.py)는 `../s2_close/score.py`의 판정식 평가 함수를
그대로 불러 쓴다. 하나를 더한다: 가짜 셀 키 `all@all`은 결과 폴더의 모든 시행(제외와 남는 시행 포함)이고 계획 수가 0이라 "자료 부족"이 되지
않는다(Q1). 판정은 맞음, 틀림, 자료 부족 중 하나다.

### 3.3 예측 요약

전체 판정식은 [predictions.csv](predictions.csv)에 있다. "n"은 계획한 판정 시행 수다.

| 무엇을 예측했나 | id | 셀 | 판정 기준(요약) | 근거 |
|---|---|---|---|---|
| 응답 쪽이 커밋 전에 계획을 거부하면 rank 0은 계획을 세우지 않고 아무도 복구 줄을 남기지 않으며 둘 다 거절(rank 0은 NACK 사유) | A1 | `pq_repost_r1_b@hq` | ≥9/10 | 9절 1번 (c) `[소스]` |
| 대조: 응답 쪽이 DONE 뒤에 거부해 rank 0은 이미 다시 보내고 복구 줄을 남긴 뒤 거절 | A2 | `pq_repost_r1_b@hf` | ≥4/5 | gin-harden 리뷰 첫 지적 `[소스]` |
| 회귀: 시작 쪽이 둘째 QP를 거부하면 아무도 다시 보내지 않음(역할 제외 없이) | A3 | `hd_repost_f1_b@hq` | 5/5 | gin-harden 10/10 `[측정, 이전 실험]` |
| 회귀(랭크 2개): 8 s commit 단계에서 감시가 3.0–3.5 s에 한 번 발동, 대기 해제, abort 6 s 안, rank 1 거절 | B1 | `hd_fwslow_f1_b@hq` | 5/5 | gin-harden 10/10 `[측정, 이전 실험]` |
| 랭크 4개: rank 0의 rank 1 라운드 초과는 그 상대만 거절하고, 뒤의 rank 2와 rank 0 라운드는 복구 | B2 | `pq4_fwslow@hq` | ≥9/10 | 9절 1번 (d) `[소스]` |
| 그때 올라간 단어는 두 rank의 상대별 단어뿐 | B3 | `pq4_fwslow@hq` | ≥9/10 | `[소스]` |
| 간선 0>1, 1>0 말고는 모두 정상 | B4 | `pq4_fwslow@hq` | ≥9/10 | `[소스, 추론]` |
| 대조: 초과가 영구라 rank 0이 rank 2의 라운드를 거절하고 rank 0의 다른 간선이 실패 | B5 | `pq4_fwslow@hf` | ≥4/5 | gin-harden 리뷰 둘째 지적 `[소스]` |
| rank 3 kill, 상대별 flush: 생존 rank 사이 간선 6개가 모두 정상 | K1 | `mr4_kill3_peer@hq` | ≥9/10 | 9절 1번 (b) `[소스]`. gin-multirank는 0/10 `[측정]` |
| 생존 rank마다 rank 3만 죽음 원인으로 거절, rank 3의 단어만 올리고 devComm 단어는 올리지 않음 | K2 | `mr4_kill3_peer@hq` | ≥9/10 | `[소스]` |
| rank 3으로 가는 보내기는 실패, rank 3에서 오는 받기는 자기 한도(timeout)로 끝남, 세 rank 모두 비동기 오류를 봄 | K3 | `mr4_kill3_peer@hq` | ≥9/10 | `waitSignal`은 상대를 모름 `[소스]` |
| 대조: 생존 rank 사이 받기 6개가 실패하고 보내기는 끝까지 감 | K4 | `mr4_kill3_peer@hf` | ≥4/5 | gin-multirank 10/10 `[측정]` |
| 문맥 전체 flush: 생존 rank의 보내기 6개는 여전히 실패, 받기 6개는 자기 한도로 끝남 | K5 | `mr4_kill3@hq` | ≥4/5 | `[소스]` |
| rank 0 쪽 원인(복사 상한 초과)으로 rank 1을 거절한 뒤 rank 1을 빼는 shrink는 순정 답을 지키고 원인 local을 적음 | H1 | `pq_copystall_shrink_b@hq` | ≥9/10 | 9절 1번 (f) `[소스]` |
| 대조: 같은 shrink가 넘어가 1-rank communicator와 맞는 allreduce | H2 | `pq_copystall_shrink_b@hf` | ≥4/5 | gin-handoff 리뷰 M1 `[소스]` |
| 원인이 rank 1 쪽이면 rank 0의 원인은 peer-reported이고 shrink가 넘어감 | H3 | `pq_copystall1_shrink_b@hq` | ≥4/5 | `[소스]` |
| 회귀: 상대의 죽음은 peer-dead이고 shrink가 넘어감 | H4 | `hd_shrink_b@hq` | ≥4/5 | gin-handoff 10/10 `[측정]` |
| 랭크 4개, rank 3 kill: 세 생존 rank의 shrink가 넘어가고 3-rank 아이가 자기 devComm으로 간선 6개를 정상으로 통신 | H5 | `pq4_kill3_shrink@hq` | ≥9/10 | 리뷰 M2 `[미확인]` |
| 랭크 4개, rank 0 쪽 원인: rank 0의 shrink는 순정 답을 지키고 아이가 없음 | H6 | `pq4_local_shrink@hq` | ≥4/5 | `[소스]` |
| (한계) 자기 확인을 통과한 rank 2, 3은 rank 0을 기다리다 단계 한도(12 s)에서 끝남 | H7 | `pq4_local_shrink@hq` | ≥4/5 | 판정은 rank마다(gin-handoff 9절 1번 (d)) `[추론]` |
| 대조: rank 0이 넘어가고 세 rank 모두 3-rank 아이를 얻음 | H8 | `pq4_local_shrink@hf` | ≥4/5 | `[소스]` |
| ACK 기다림 중 취소한 rank 0의 다시 걸기에 rank 1이 FAIL로 답하고, rank 0은 끊김 끝 1.5 s 안에 거절 | C1 | `pq_ackrace_f1_b@hq` | ≥9/10 | 9절 1번 (e) `[소스]` |
| 대조: rank 0이 재연결 한도를 다 쓰고 끊김 끝 5 s 이상 뒤 "모름"으로 거절 | C2 | `pq_ackrace_f1_b@hf` | ≥4/5 | gin-harden 리뷰 셋째 지적 `[소스]` |
| 같은 경합을 rank 1이 시작: rank 0이 확인 접속에 FAIL로 답하고 rank 1이 끊김 끝 1.5 s 안에 거절 | C3 | `pq_ackrace_f1r1_b@hq` | ≥4/5 | `[소스]` |
| 대조: rank 1이 끊김 끝 5 s 이상 뒤 "모름"으로 거절 | C4 | `pq_ackrace_f1r1_b@hf` | ≥4/5 | `[소스]` |
| 본 실행의 어떤 시행도 랑데부 포트 bind에 실패하지 않음 | Q1 | `all@all` | 0회 | 9절 3번 `[소스]`. 이전 실험 7/500 `[측정]` |
| 막아 둔 첫 후보를 건너뛰고, rank 1이 가짜 수신 대기에 한 바이트도 보내지 않고 거부, 두 rank가 랑데부 확인, 투명 | Q2 | `pq_rdv_b@hq` | 5/5 | `[소스]` |
| 랭크 4개에서도 같음 | Q3 | `pq4_rdv@hq` | 3/3 | `[소스]` |
| 복구 재현 셀이 그대로 투명 | R1 | `f1_b`, `f3_b`, `bidirf_sym_b`(`@hq`) | 셀마다 5/5 | gin-handoff 5/5 `[측정]` |
| 랭크 2개 kill: 2 s 안에 peer-dead로 거절하고, 유일한 상대라 devComm 단어도 올라감 | R2 | `f4_b@hq` | 5/5 | `[소스]`, gin-harden R3, R4 `[측정]` |
| 랭크 2개, 받기만 하는 rank의 `waitSignal`이 보내는 쪽 kill 2 s 안에 오류로 풀림 | R3 | `hd_rxdeath_b@hq` | 5/5 | gin-harden B8, B9 `[측정]` |
| 원격 접근 오류: 거절, 받는 쪽 오류 해제, abort 5 s 안 | R4 | `f2rel_b@hq` | 5/5 | gin-handoff R3 `[측정]` |
| 운영 빌드 kill: 2 s 안 죽음 거절, 죽음 1, WARN에 정보성 줄 없음 | R5 | `hdp_kill_b@hqp` | 5/5 | gin-harden P5, P7 `[측정]` |
| 랭크 4개 장애 없음, 한 쌍 로컬 QP 오류: 투명 | R6 | `mr4_none@hq`, `mr4_f1_01@hq` | 셀마다 5/5 | gin-multirank 10/10 `[측정]` |
| 통계 API: 라운드 1, 복구 1, 거절 0 | R7 | `f1_b@hq` | 5/5 | gin-harden E4 `[측정]` |
| 4 KiB 지연: 운영 빌드와 gin-handoff 운영 빌드 차이 0.40 µs 이하 | P1 | `lat_4k@hqp` 대 `@hfp` | 실행 중앙값 | 장치 변경은 빠른 경로 밖 `[소스]` |
| 256 KiB 지연: 차이 0.30 µs 이하 | P2 | `lat_256k@hqp` 대 `@hfp` | 실행 중앙값 | 같음 |

셀 조건은 7절에 있다.

## 4. 범위

**포함.**
- 9절 1번의 라이브러리 계층 하나([hq_layer.diff](hq_layer.diff), `hf` 트리 기준, 5개 파일)와 그 운영 빌드.
- 드라이버 둘의 확인하는 랑데부(`../gin_ts2.cu`, 이 폴더의 [gin_mr.cu](gin_mr.cu))와 `gin_mr`의 shrink, 아이 devComm 단계.
- 이 실험의 실행기 둘([run_trial_hq.sh](run_trial_hq.sh), [run_mr_hq.sh](run_mr_hq.sh))과 포트 고르기([portpick.sh](portpick.sh)). 앞 실험의
  실행기는 고치지 않는다.
- 7절의 셀 키 35개: 랭크 2개 새 셀과 대조 10개, 회귀 10개, 지연 4개, 랭크 4개 새 셀과 대조 9개, 회귀 2개.

**제외와 이 테스트베드가 할 수 없는 것.**
- 실제 link down, flap, 재부팅, 드라이버 재적재, 커널 모듈 적재, RoCE 주소 변경, iptables: 하지 않는다(8절). 관리망 끊김은 우리 helper 소켓에 붙이는
  필터(시험 스위치)로만 만든다.
- 상대를 모르는 대기(`waitSignal`, `waitCounter`, 배리어)를 상대별로 푸는 것: 장치 API가 그 대기의 상대를 모른다(신호는 어느 rank든 더할 수 있다)
  `[소스]`. 이 계층은 그런 대기를 모든 상대가 거절됐을 때나 communicator 전체의 일에서만 푼다. 응용은 비동기 오류로 알고 abort나 shrink를 부른다.
- 문맥 전체 flush를 상대별로 하는 것: 그 flush는 정의상 문맥의 모든 상대의 QP를 덮는다(GIN 문맥마다 모든 rank로 가는 QP가 있다) `[소스]`.
- 판정이 rank마다라서 생기는 일(한 rank는 순정 답, 다른 rank는 넘김)을 rank 사이에서 맞추는 것: 다음 실험의 몫이다. 이 실험은 그 결과를 잰다
  (H7).
- 순환 대기(gin-multirank Y1–Y3), 실제로 멈춘 펌웨어 명령, GPU가 가득 찬 동안의 복사: 이 계층이 고치지 않는다.
- 낮은 지적 셋(거부 잊기, 상한 넘김의 재실행, 취소 계수)은 코드로만 고치고 셀은 두지 않는다(시간 예산). 이 셋은 소스와 합성 시험으로만 확인한다
  `[미확인: 측정]`.

## 5. 테스트베드와 버전

| 항목 | 값 | 확인 방법과 날짜 |
|---|---|---|
| 노드, NIC, 펌웨어, GPU, CUDA | gin-harden, gin-multirank와 같다: rain(rank 0, 랭크 4개에서는 0과 2, Quadro RTX 5000), sunny(rank 1, 랭크 4개에서는 1과 3, RTX A4000), ConnectX-6 fw 20.43.4100, CUDA 12.8 | `../harden/EXPERIMENT.md` 5절, `../multirank/EXPERIMENT.md` 5절 |
| 임시 포트 범위 | rain 32768–60999, 예약 없음. rain에서 수신 대기 중인 TCP 포트는 22, 53, 80, 111, 631, 2377, 7946, 12865, 39109이고 20000–32767에는 어떤 상태의 TCP 소켓도 없었다. sunny에서는 로컬 포트가 29000–30999인 TCP 소켓 0개, 원격 포트가 그 범위인 소켓 1개(다른 호스트로 나가는 연결, 이 실험의 수신 대기와 겹치지 않음) | `[측정]` 2026-10-09 rain(`/proc/sys/net/ipv4/ip_local_port_range`, `ss -ltn`, `ss -tan`). sunny는 메인 세션이 08:36에 읽기만 해서 확인 `[측정, 메인 세션]` |
| `hf`, `hfp` 번들 | libnccl `b6372d8622f6a7eceb9fd4528c00e707`, `1ae4ce9aecb1727248db7eb3699ad110`, 드라이버 `9493584d5a321277c61863f4ed6ac379` | gin-handoff 배포 확인(`../handoff/deploy_check.txt`) `[측정, 이전 실험]`. rain의 스크래치 `agent_ts2hf/out/`에서 같은 md5 `[측정]` 2026-10-09 |
| `hq`, `hqp`, 새 드라이버 | libnccl `hq` `c1311625c7a06c785bc313558504f982`, `hqp` `4fa076e113e43774a9dc2f46298df43b`, `gin_ts2` `3e053ff2ab069ec64198ed4e0f6e237a`, `gin_mr` `7f0fc272962b293da0bd0d3655aacc4d`. [deploy_hq.sh](deploy_hq.sh)의 기대 md5와 같다. 배포 뒤 두 노드 md5는 `deploy_check.txt`에 남긴다 | `[측정]` 2026-10-09 빌드 때 rain(세션 스크래치 `agent_ts2hq/out/`, `out/build_info.txt`) |
| 변경분 | [hq_layer.diff](hq_layer.diff)(`hf` 트리 기준, md5 `34ab6201`), 전체 diff [gin_transparent_hq.diff](gin_transparent_hq.diff)(pristine 기준, md5 `5b7c3049`). 순정에 전체 diff를, 그리고 gin-oneway 전체 diff + gin-harden 계층 + gin-handoff 계층 + 이 계층을 더하면 각각 이 트리와 같다 | `[측정]` [make_diff_hq.sh](make_diff_hq.sh), 12절 |

## 6. 변수

- **독립변수.**
  - 빌드: `hq`, `hqp`, `hf`, `hfp`(랭크 4개는 드라이버 `mr/hq`에 libnccl `hq` 또는 `hf`).
  - 장애: 로컬 QP 오류(rank 0, rank 1, 문맥 하나 또는 전부), 상대 QP 오류, 원격 접근 오류, rank 1 kill, rank 0 kill, rank 3 kill(랭크 4개).
  - 시험 스위치: 응답 쪽 또는 시작 쪽의 계획 거부, commit 단계 4 s와 8 s, 첫 라운드 복사 4 s 묶기(rank 0 또는 rank 1), 시작 쪽 helper 소켓의 수신
    끊김(0.5–8.5 s).
  - 응용: flush 방식(문맥 전체, 상대별), 중단 shrink(랭크 2개는 rank 0, 랭크 4개는 생존 rank 모두), 아이 devComm 통신.
  - 실행기: 막아 둔 첫 후보 포트, 가짜 수신 대기.
- **종속변수.** 3.1의 열: 상대별 해제와 devComm 단어, 원인, 거절 대상과 사유와 시각, 간선마다 결과, 계획 검사의 위치, 감시 발동, FAIL 답과 거절
  시각, 넘김과 유지, 아이 통신, 랑데부 확인, 지연 p50.
- **통제변수.** gin-harden, gin-multirank와 같다: IB 타임아웃 14, GPU doorbell, 투명 복구 스위치 기본값(handshake 3 000 ms, hold 30 000 ms, 라운드
  25 000 ms, 재연결 10 000 ms, 복사 2 000 ms, 펌웨어 단계 3 000 ms, abort의 helper 대기 3 000 ms). 기존 셀 정의는 `../harden/cells.sh`,
  `../multirank/cells.sh` 그대로다(실행기만 바꿈). 시행마다 프로세스를 새로 띄운다. 랑데부 포트는 29000–30999.

## 7. 실험 셀, 반복 수, 대조군

반복 수: 새 셀 10(랭크 2개 PROBE 형태와 원인 셀 일부는 5), 대조 5, 회귀 5, 포트 셀 5와 3. 지연 셀의 반복은 실행 수다(실행마다 3000번). 정의 원문은
[cells.sh](cells.sh)다. 훅 시각은 GDAKI 문맥 생성부터, kill 시각은 실행기가 그 rank를 띄운 때부터, 끊김 시각은 그 rank의 helper 시작부터 잰다.

| 셀 | 조건 | 빌드와 반복 수 | 종류 |
|---|---|---|---|
| `pq_repost_r1_b` | 양방향, 범위 좁히기 끔(전체 재설정, QP 4개), rank 0 로컬 QP 오류, rank 1(응답 쪽)의 계획이 둘째 QP를 거부(`NCCL_GIN_TS_TEST_BAD_REPOST=1`). 16 KiB × 400 | `@hq` 10, `@hf` 5 | 새 셀, 대조 |
| `hd_repost_f1_b` | gin-harden 정의(rank 0의 계획이 거부) | `@hq` 5 | 회귀 |
| `hd_fwslow_f1_b` | gin-harden 정의(rank 0의 commit 단계 8 s) | `@hq` 5 | 회귀 |
| `pq_ackrace_f1_b` | rank 0 helper 소켓 수신 끊김 500:8000, rank 0 로컬 QP 오류 1 500 ms. REQ는 나가고 ACK와 TCP 확인이 돌아오지 못해 라운드 5.23–5.26 s 뒤 두 소켓이 ETIMEDOUT(pilot 4회 `[측정]`). 응답 쪽(rank 1)은 커널이 끝난 뒤 12 s 머문 뒤 정리한다(`GIN_TS_END_WAIT_S=12`, pilot 뒤 추가, 12절). 16 KiB × 1000 | `@hq` 10, `@hf` 5 | 새 셀, 대조 |
| `pq_ackrace_f1r1_b` | 같은 경합을 rank 1이 시작: 양방향, rank 1 helper 소켓 끊김 500:8000, rank 1 로컬 QP 오류 1 500 ms(문맥 1). 응답 쪽(rank 0)이 12 s 머묾(같은 스위치) | `@hq` 5, `@hf` 5 | 새 셀, 대조 |
| `pq_copystall_shrink_b` | `f1_b`에 rank 0의 첫 라운드 스트림 4 s 묶기(`NCCL_GIN_TS_TEST_COPY_STALL=4000`)와 rank 0의 중단 shrink(살아 있는 rank 1 제외) | `@hq` 10, `@hf` 5 | 새 셀, 대조 |
| `pq_copystall1_shrink_b` | 같고 묶기는 rank 1(응답 쪽) | `@hq` 5 | 새 셀 |
| `hd_shrink_b` | gin-harden 정의(rank 1 kill, rank 0 중단 shrink) | `@hq` 5 | 회귀 |
| `pq_rdv_b` | `f1_b`에 막아 둔 첫 후보 포트(`PORT_OCCUPY=1`)와 가짜 수신 대기(`RDV_DECOY=1`) | `@hq` 5 | 새 셀 |
| `f1_b`, `f3_b`, `bidirf_sym_b`, `f4_b`, `f2rel_b`, `hd_rxdeath_b` | gin-harden 정의 | `@hq` 각 5 | 회귀 |
| `hdp_kill_b` | gin-harden 정의 | `@hqp` 5 | 회귀 |
| `lat_4k`, `lat_256k` | 장애 없음, 3000번. 같은 hold에서 두 빌드를 섞어 돈다 | `@hqp`, `@hfp` 각 5 | 대조 |
| `mr4_kill3_peer` | 랭크 4개, rank 3 SIGKILL 9 000 ms, 상대별 flush, 앱의 커널 기다림 40 s(gin-multirank 정의) | `@hq` 10, `@hf` 5 | 새 셀, 대조 |
| `mr4_kill3` | 같고 문맥 전체 flush | `@hq` 5 | 새 셀 |
| `pq4_fwslow` | 랭크 4개, 상대별 flush. rank 0 문맥 0(간선 0>1)에 로컬 QP 오류 6 000 ms와 commit 단계 4 s(`NCCL_GIN_TS_TEST_FW_DELAY=4000@commit`), rank 2 문맥 6(간선 2>0)에 로컬 QP 오류 11 500 ms | `@hq` 10, `@hf` 5 | 새 셀, 대조 |
| `pq4_kill3_shrink` | `mr4_kill3_peer`에 생존 rank의 중단 shrink(rank 3 제외)와 아이 devComm 통신(간선 6개, 4 KiB × 200, 2 ms 간격, 상대별 flush). 단계 한도 40 s | `@hq` 10 | 새 셀 |
| `pq4_local_shrink` | 랭크 4개, 상대별 flush, rank 0 문맥 0에 로컬 QP 오류 6 000 ms와 첫 라운드 스트림 4 s 묶기. 트래픽 뒤 rank 0, 2, 3이 rank 1을 빼는 중단 shrink(아이 통신 없음). 단계 한도 12 s | `@hq` 5, `@hf` 5 | 새 셀, 대조 |
| `pq4_rdv` | `mr4_none`에 막아 둔 첫 후보와 가짜 수신 대기 | `@hq` 3 | 새 셀 |
| `mr4_none`, `mr4_f1_01` | gin-multirank 정의 | `@hq` 각 5 | 회귀 |

**합계.**

| 종류 | 랭크 2개 시행 | 랭크 4개 시행 | 지연 실행 |
|---|--:|--:|--:|
| 새 셀(`hq`) | 45 | 43 | |
| 대조(`hf`) | 20 | 15 | 20(`hqp` 10, `hfp` 10) |
| 회귀(`hq`, `hqp`) | 50 | 10 | |
| 합 | 115 | 68 | 20 |

셀 키 35개(지연 4개 포함). 예측 37줄: 새 동작 18, 대조 9(지연 2 포함), 회귀 10.

## 8. 제외 기준과 중단 기준

**제외 기준.** 제외한 시행은 셀별로 따로 세어 보고한다([score.py](score.py) `status2`, `status4`).
- pilot(`results/<날짜>_pilot/`)은 채점하지 않는다.
- NCCL 초기화 전 실패(`bind_fail == 1`)는 제외하고 다음 번호로 채운다. 단, Q1은 이 제외와 상관없이 모든 시행을 센다.
- 장애 미적용은 제외하고 채운다: 훅 셀에서 그 rank의 훅 발사가 없음(랭크 4개는 `fires`가 셀의 기대 "0:0", "0:0;2:6"과 다르거나 트래픽 밖),
  `trigger_miss > 0`, kill 셀에서 kill 기록이 없음(랭크 4개는 트래픽 밖의 kill도).
- 조건 미적용은 제외하고 채운다.
  - `pq_repost_r1_b`: 계획을 거부한 rank 1이 시작 쪽(`n_init_round_r1 > 0`).
  - `pq_ackrace_f1_b`, `pq_ackrace_f1r1_b`: 끊긴 rank가 ACK 기다림 중 취소하지 않았거나(`n_cancel_ack == 0`), 상대 rank의 첫 거절이 커밋 뒤의
    거절(`peer closed the socket before DONE`, `DONE timeout`, `cannot send ACK`)이 아님. 이 셀의 주제는 그 뒤의 재연결이다.
  - 복사 묶기 셀: 묶은 rank에 복사 상한 초과가 없음. 펌웨어 셀: 감시 줄이 없음.
- 펌웨어 초과는 제외하고 채운다: 펌웨어 셀(`hd_fwslow_f1_b`, `pq4_fwslow`)이 아닌 시행에서 어느 rank든 감시 줄이나 `rs_fw_overruns`가 0이 아님. 이
  계층에서는 초과가 영구가 아니지만, 테스트베드 사정(rain의 펌웨어 명령 슬롯 누수)이 셀의 주제를 가리는 것은 같다.
- 채우려고 다시 돈 시행이 셀 키마다 계획의 50%를 넘으면 그 셀 키는 멈추고 "자료 부족"으로 둔다.

**설정 확인.** 하나라도 어긋나면 제외가 아니라 그 블록을 멈춘다.
- `hq` 시행(랭크 2개): 두 rank(kill된 rank 빼고)에 gin-harden 시작 줄(`production=0`), gin-handoff 시작 줄, 이 실험 시작 줄, 투명 복구 시작 줄,
  사용자 devComm abort 단어 줄. `hf` 시행: 이 실험 시작 줄만 없음. `hqp`, `hfp`: 시작 줄이 WARN에 없고 kv에 `rs_api=1`, `rs_contexts >= 1`.
- 시험 스위치 줄이 셀과 같다(gin-harden 스위치 줄의 값: 계획 거부, 펌웨어 지연, 복사 묶기가 그 셀의 그 rank에만). 끊김 줄은 경합 셀의 끊긴 rank에만.
- 랭크 4개: 모든 rank의 투명 복구 시작 줄과 abort 단어 줄이 n 이상(아이 devComm이 줄을 더함), 이 실험 시작 줄이 `hq`에서 n, `hf`에서 0.
- 경합 셀: 응답 쪽 rank의 환경에 `GIN_TS_END_WAIT_S=12`(실행기 meta의 `r<r>env`, `rows_pq.py`의 `end_wait_r*`). pilot 뒤에 더했다.

**pilot에서 보이는 결함.** 태그 전이므로 고칠 수 있다. 고친 것은 12절에 적고, 고친 뒤에는 그 셀의 pilot을 다시 돈다. pilot P0, P1에서 실제로 나온
결함은 경합 셀 두 개의 응답 쪽이 너무 일찍 끝나는 것 하나였다(12절). 아래는 미리 정해 둔 예다:
- 경합 셀: 취소가 ACK 기다림이 아닌 단계(REQ 전)에서 생김, 또는 응답 쪽이 커밋 전에 끊김을 봄. 장애 시각(1 500 ms)이나 끊김 창을 한 번 바꿀 수
  있다.
- `pq4_fwslow`: rank 2의 장애가 rank 0의 거절 전에 옴. 둘째 장애 시각(11 500 ms)을 한 번 바꿀 수 있다.
- 구현 결함: 회귀 셀이나 새 셀에서 예측과 다른 동작이 구현 탓으로 보이면 고치고 다시 빌드, 배포(새 디렉터리)한다.

**중단 기준.**
- **잠금.** 모든 클러스터 명령은 `harness/gpu-initiated/common/cluster_run.sh -w 10800` 안에서 돈다([chain.sh](chain.sh), 꼬리표 `gpq-<hold>`).
  10 800 s 안에 잠금이나 유휴 링크를 얻지 못하면 그 hold를 미룬다. `prio-` 작업에는 양보한다. hold 하나는 15분 이하이고 `timeout -s KILL 880`으로
  묶는다.
- **하지 않는 것.** 실제 link down이나 flap, 재부팅, 드라이버 재적재, 커널 모듈 적재, RoCE 주소 변경, 시스템 TCP 설정 변경, iptables 규칙 추가, GPU
  컴퓨트 모드 변경. `chain.sh`는 hold 앞뒤에 `gin-` 꼬리표 iptables 규칙 수를 읽기만 하고, 늘었으면 `STOP_iptables`로 멈춘다.
- **프로세스.** 이름으로는 아무것도 끄지 않는다(`pkill`, `killall` 없음). 실행기는 자기가 기록한 PID와 그 자식만 신호한다(rank 0의 `timeout`,
  rank 1의 원격 셸이 남긴 PID, kill 대상 rank의 `gin_mr` PID와 부모, 포트 시험의 `timeout` 래퍼). 시행 뒤 남은 프로세스는 읽기만 해서 세고, 두 시행
  연속이면 `STOP_left`. 다음 hold는 남은 `gin_ts2`, `gin_mr`가 없어질 때까지 150 s까지 기다리고, 그래도 있으면 시행을 돌지 않는다.
- **CUDA 메모리 오류.** hold 안의 어느 시행이든 rank 종료 코드 139이거나 로그나 kv에 illegal address, illegal memory access, unspecified launch
  failure가 보이면 그 hold 뒤로 멈춘다(`STOP_cuda`).
- **mlx5 오류.** hold 앞뒤에 두 노드의 mlx5 커널 줄 전체와 rain의 펌웨어 명령 계수를 남긴다. 새 명령 오류 줄이나 펌웨어 명령 실패 계수 증가가 보이면
  그 hold 뒤로 멈춘다(`STOP_mlx5`).
- **배포.** 새 번들은 새 디렉터리 `hq/`, `hqp/`, `mr/hq/`에만 둔다. 대상 파일이 이미 있거나 소스가 기대 md5와 다르면 배포 스크립트가 멈춘다. 배포 뒤
  기존 번들 파일의 md5가 두 노드에서 그대로인지 확인한다. `hf/`, `hfp/`는 읽기만 한다.

## 9. 실행 방법과 경로

### 1. 라이브러리 계층 (`hq`, `hqp`)

[hq_layer.diff](hq_layer.diff)(`hf` 트리 기준)와 전체 diff [gin_transparent_hq.diff](gin_transparent_hq.diff). 바뀐 파일:

| 파일 | 무엇 |
|---|---|
| `src/transport/net_ib/gdaki/gin_host_gdaki.cc` | 거의 모든 변경 |
| `src/include/nccl_device/gin/gdaki/gin_gdaki.h` | 게이트에서 쉬는 대기와 폴링이 상대별 단어도 읽음 |
| `src/include/nccl_device/gin/gdaki/gin_gdaki_device_host_common.h` | 게이트 `test` 칸의 새 쓰임(주석만) |
| `src/dev_runtime.cc` | 단어 배열의 크기(rank 수)를 넘김, 시작 줄에 `per_peer=1` |
| `src/init.cc` | 원인을 보는 넘김 규칙 |

(a) **설계의 출발점.** 장치에서 상대별로 풀 수 있는 대기는 QP 하나에 걸린 대기뿐이다. `waitSignal`과 `waitCounter`는 장치 메모리의 칸 하나를 기다릴
뿐 어느 rank가 그 칸을 올릴지 모르고, 문맥 전체 flush는 정의상 모든 상대의 QP를 덮는다 `[소스]`. 그래서 상대별 해제는 "그 상대의 QP에 걸린 장치
스레드"로 정하고, 상대를 모르는 대기는 communicator 전체의 일에만 풀리게 한다.

(b) **상대별 abort 단어 (항목 2).**
- 배열: communicator마다 host-pinned 단어 `1 + nRanks`개(`ncclGinTsUserAbortWord`, `dev_runtime.cc`가 `comm->nRanks`를 넘김). 칸 0은 사용자
  devComm의 `abortFlag`이고, 칸 1 + p는 GIN 상대 p의 것이다.
- 게이트: helper가 상대 p로 가는 QP마다 게이트 `test` 칸에 칸 1 + p의 주소 | 1을 쓴다(`gdakiTsPosterWordStep`, gin-harden과 같은 4바이트 복사
  두 번).
- 장치(`gin_gdaki.h`): 게이트에서 쉬는 보내는 스레드는 이미 이 칸을 읽었다. 이제 쉬는 대기(`tsParkStable`, 64번마다)와 계수 영역 안의 폴링
  (`tsPoll`, abort 확인 주기인 10 000번마다)도 자기 QP의 단어를 읽는다(`tsQpWordError`). 빠른 경로(게이트 한 번의 원자적 더하기)는 그대로다.
- 올리기:
  - 거절, 죽음, 펌웨어 초과는 그 상대의 칸만 올린다(`gdakiUaRaisePeer`).
  - 칸 0은 그 communicator의 helper가 게이트를 단 상대 모두의 칸이 올라갔을 때만 따라 올라간다("every peer"). 랭크 2개에서는 첫 거절이 곧 모든
    상대라 앞 빌드와 같다.
  - `ncclCommAbort`, 중단 shrink, revoke는 모든 칸을 올린다(`ncclGinTsUserAbortRaise`).
  - 단어는 한 번 올라가면 지우지 않는다.
- 거절은 이제 모든 문맥의 장치 오류 상태(blocking `flush()`와 `wait()`가 돌려주는 문맥별 sticky 표시)를 올리지 않는다. 거절된 상대의 QP에 닿는 대기는
  스스로 실패하며(게이트 실패나 상대 단어) 자기 문맥의 sticky를 올린다. sticky는 문맥마다 하나라, 한 번 올라가면 같은 문맥의 뒤 blocking `wait()`와
  `flush()`는 건강한 상대에 대한 요청에도 오류를 돌려준다(리뷰 M3). 상대별인 것은 게이트에서 쉬는 대기와 폴링, 그리고 시간 제한 판 `wait`다
  `[소스]`. `gin_mr`의 상대별 flush는 시간 제한 판을 쓴다 `[소스]`.
- 이 변경의 가장자리: 거절 뒤에 낸 대기 중 기다릴 WQE가 없는 것(`sq_rsvd_index` 0)은 이제 성공을 돌려준다. 실패한 게이트에 닿는 다음 동작은 여전히
  실패한다 `[소스, 리뷰]`.
- 상대별 단어는 communicator 단위다. 한 communicator에 devComm이 둘이면, 한 helper가 상대 p를 거절할 때 다른 devComm의 p 쪽 QP 대기도 풀리고,
  그 helper의 다음 p 라운드는 원인 local로 거절된다(리뷰 L3, 과하게 막는 쪽. 앞 빌드에서는 모든 대기가 풀렸다).

장치 API별로, 상대 p를 거절했을 때(이 계층):

| 장치 API | p에 걸렸으면 | 다른 상대 q에만 걸렸으면 |
|---|---|---|
| `put`, `signal` 등 보내기(게이트) | 보내지 않음(게이트 실패나 p의 단어). 뒤의 대기가 오류 | 영향 없음 |
| `flushAsync(peer)` + 시간 제한 `wait` | 오류 | 영향 없음 |
| blocking `wait(request)`, blocking `flush`(결과 = 문맥의 sticky) | 오류 | 같은 문맥에서 앞서 실패한 대기가 없으면 영향 없음. 있으면 오류(문맥별) |
| 문맥 전체 `flush`(시간 제한 판 포함) | 오류(문맥마다 p로 가는 QP가 있음) | 해당 없음(언제나 p를 덮음) |
| `waitSignal`, `waitCounter`(void, 시간 제한 판) | 상대를 모름: 칸 0(abort, 중단 shrink, revoke, 모든 상대의 거절)이나 자기 시간 제한까지 기다림 | 같음 |
| LSA, CFT 배리어, ll_a2a, GIN proxy 경로 | 앞 빌드와 같이 칸 0만 읽음(값을 돌려주지 않는 대기) | 같음 |

(c) **다시 보내기 계획을 커밋 전에 두 rank에서 (3a).** gin-harden의 `gdakiTsReplayResume`을 둘로 나눴다.
- `gdakiTsRepostPlanAll`: 첫째 단계(범위, 덮인 슬롯, 사본 영역, opcode 검사와 WQE 복사)만 한다.
- `gdakiTsRepostApply`: 커밋 지점, PUBLISHING 표시, 다시 보내기, 새 에폭.
- 응답 쪽은 REQ의 실행 수로 계획을 세운 뒤에 커밋하고 ACK한다. 거부하면 NACK 15를 보내고 거절한다. 시작 쪽은 NACK 15를 받으면 커밋하지 않고 거절한다.
- 시작 쪽은 ACK의 실행 수로 계획을 세운 뒤에 커밋한다. 거부하면 FAIL과 함께 거절하고, DONE을 기다리던 응답 쪽은 다시 보내지 않고 거절한다.
- 계획은 링과 사본 영역을 한 번 읽어 만든다. 커밋은 QP를 리셋할 뿐 링을 고치지 않고, 게이트가 닫혀 있어 보내는 스레드가 들어오지 못하므로, 커밋 뒤의
  둘째 단계는 같은 계획을 쓴다 `[소스]`. 그래서 두 rank 모두 계획이 통과해야 누구든 다시 보낸다.
- 남는 점: 상대가 이미 다시 보낸 뒤의 응답 쪽 둘째 단계에서 복사나 doorbell이 실패할 수는 있다. 이것은 거부가 아니라 입출력 실패다.

(d) **펌웨어 감시를 라운드와 상대 단위로 (3b).**
- 상태: `fwOverrun`(한 번 서면 영구)을 없애고 라운드 번호(`fwRound`, 두 역할 모두 라운드 시작에 1 증가), 초과한 라운드 번호(`ovRound`), 바깥
  단계 번호(`fwPhaseSeq`, 바깥 단계마다 1 증가)와 마지막으로 매긴 단계 번호(`ovPhaseSeq`)를 둔다. 감시는 단계 하나를 한 번만 매긴다. 라운드 밖의
  단계(거절의 QP 오류 전환 등, 마지막 라운드 번호를 다시 씀)도 따로 매겨지므로, 두 상대가 연달아 느린 명령에 걸려도 각 상대의 단어가 올라간다(리뷰
  M2 반영. 처음 구현은 라운드 번호 하나에 한 번만 매겨 둘째 초과를 놓쳤다).
- 단계 시작: 감싸는 단계(`gdakiRecFwGuard`)는 시작할 때 상대를 적는다. 바깥 단계의 시작과 끝은 감시의 판정과 같은 자물쇠(`fwMu`) 안에서 일어나므로,
  초과는 언제나 그 단계가 속한 라운드와 상대에 매겨진다.
- 감시: 그 상대의 단어만 올리고, 비동기 오류를 원인 local로 올린다. `surfaced`는 세우지 않는다. 명령이 돌아오면 그 라운드만 거절한다
  (`gdakiTsFwCheck`, 커밋 뒤 마지막 QUERY_QP 뒤에도 확인). 다음 라운드는 새 번호라 영향이 없다.
- 라운드를 마치기 전에 상대의 단어가 이미 올라가 있으면(라운드 밖 단계에 매겨진 초과 등) 그 라운드는 게시하지 않고 거절한다(`gdakiUaPeerRaised`).
  응답 쪽은 REQ를 받자마자도 확인해 NACK 16으로 거절한다(정지와 준비를 헛되이 하지 않음, 리뷰 지적).
- **언제 꺼진 채로 남나.**
  - 명령이 돌아오지 않는 동안: helper가 그 라운드 안에 있어 다른 장애는 큐에서 기다리고, 그 장치 스레드는 `NCCL_GIN_TS_HOLD_MS`(30 s)까지 쉰다.
  - 그 라운드가 `NCCL_GIN_TS_ROUND_MS`(25 s)를 넘으면: 앞 빌드의 감시가 상대 없이 오류를 드러내고(`surfaced`), 그때부터 그 문맥의 모든 라운드가
    거절된다.
  - `ncclCommAbort`가 helper를 떼어 냈으면(명령 하나가 3 s 넘게 도는 중) 그 문맥은 더 쓰이지 않는다.
  - 상한 넘김(`NCCL_GIN_TS_ESCALATE_*`)은 앞 빌드처럼 영구다.
- 랭크 2개에서는 초과한 라운드의 상대가 유일한 상대라 결과(그 상대의 거절)가 앞 빌드와 같다. 개선은 상대가 둘 이상일 때만 보인다(B2–B5).

(e) **거절한 rank가 다시 걸기와 확인 접속에 FAIL로 답함 (3c).**
- 거절한 rank: 그 상대의 HELLO(낮은 rank의 다시 걸기)나 PROBE(높은 rank의 확인 접속)에 고유값이 맞으면 FAIL을 보내고 닫는다(`gdakiTsAnswerFail`).
  앞 빌드는 HELLO를 닫고 PROBE에는 답만 했다.
- 받은 쪽: `peerFailed`로 표시한다(`gdakiTsPeerFailedUninstalled`). 죽음이 아니고 더 다시 걸거나 확인하지 않는다. 재연결을 기다리던 장애는 바로
  "the peer declined this pair (FAIL on reconnect)"로 거절하고(원인 peer-reported), 기다리던 장애가 없으면 helper 루프가 바로 거절한다.
- 거절과 FAIL, 모든 NACK에는 이제 고유값을 싣는다.
- FAIL과 NACK는 보내는 쪽의 원인 분류도 싣는다(`pad` = 1 + 원인, 리뷰 M1 반영). FAIL은 그 거절의 원인(재연결의 FAIL은 처음 거절할 때 적어 둔
  원인), NACK 2는 적어 둔 원인, NACK 11(범위가 틀림)과 15(계획 거부)는 unknown, NACK 1과 12(거절이 아님)는 없음, 나머지 NACK는 local이다.
  받는 쪽은 보낸 쪽의 원인이 local일 때만 peer-reported로, 아니면 unknown으로 적는다(`gdakiTsRemoteCause`).
- NACK 15는 이제 계획을 실제로 거부한 경우만이다. 계획을 세우지 않은 경우(감시가 이미 드러냄, 정리 중, 그 상대의 단어가 이미 올라감)는 새 NACK
  16이다(리뷰 L2 반영). 계획 거부의 원인은 두 역할 모두 unknown이다(어느 rank의 실행 수나 링 탓인지 가릴 수 없음).

(f) **원인을 보는 넘김 (항목 4).**
- 기록: 오류 올림마다 원인을 함께 적는다(`gdakiBlameNote(slot, peer, cause)`).
  - 상대 쪽: peer-dead(BYE 없는 FIN, 거부 두 번), peer-left(BYE), peer-reported(상대가 NACK, FAIL, 재연결의 FAIL에 local 원인을 실어 보냄).
  - local: 커밋, 복사, QUERY_QP, 준비의 실패, 펌웨어 초과, 계획을 세우지 않음, 상한 넘김, 장치 대기의 포기, 메일박스 넘침.
  - unknown: 재연결 없음, handshake 시간 초과, 복구할 수 없는 분류, 투명 복구 없는 분류 기록, 감시의 드러냄, 계획 거부, 상대가 local이 아닌 원인이나
    원인 없이 보낸 NACK와 FAIL.
- 규칙(`commShrinkAbortReady`): 넘김 줄의 조건에 "모든 올림의 원인이 상대 쪽"을 더했다. 상대 쪽이 아닌 올림이 하나라도 있으면 유지 줄에 그 rank와
  원인을 적고 순정 답을 돌려준다(`ncclGinTsBlameQuery`의 −3).
- 거절 줄 바로 뒤에 원인 줄이 하나 나온다.

(g) **낮은 지적.**
- 첫 거부 뒤 5 000 ms가 지나면 그 거부를 잊는다(죽음은 1–5 s 사이의 거부 두 번).
- 다시 시도와 범위 재실행은 상한 넘김에서 새 라운드로 세지 않는다. REQ의 `t[3] = 1`이 응답 쪽에 알린다(REQ에서 쓰지 않던 칸).
- 시작 쪽도 취소한 라운드를 모두 센다(앞 빌드는 다시 넣은 것만).

(h) **남는 점** `[소스, 추론]`.
- 상대를 모르는 대기는 랭크 3개 이상에서 상대 하나의 죽음에 바로 풀리지 않는다(리뷰 M4). `waitSignal`, `waitCounter`, GIN 배리어(LSA, CFT,
  rail, world), ll_a2a, void 판이 그렇다. 그 상대에서 오는 신호를 기다리는 대기나 죽은 rank를 포함한 배리어는 자기 시간 제한까지, 시간 제한이 없으면
  응용이 abort나 shrink를 부를 때까지 기다린다. 앞 빌드에서는 바로 풀렸다. 비동기 오류는 올라가지만, 스트림 동기화에 막힌 host 스레드는 그것을
  볼 수 없으므로 응용은 장치 쪽 시간 제한을 두거나 다른 스레드에서 오류를 보고 abort를 불러야 한다 `[추론]`. 랭크 2개에서는 상대가 하나라 칸 0이 바로
  올라간다. K3, K5가 이 동작을 잰다.
- 상대별 단어가 게이트에 닿기 전에는(devComm을 만든 직후 helper의 다음 루프까지, 또는 복사가 계속 막히면 끝까지) 거절된 상대의 QP에서 쉬는 대기와
  폴링이 게이트 실패나 `NCCL_GIN_TS_HOLD_MS`로만 풀린다(리뷰 L4). 앞 빌드 헤더로 만든 장치 코드도 같다.
- 감시의 판정은 라운드 단위지만, 펌웨어 명령 자체는 여전히 끊을 수 없다. 돌아오지 않는 명령의 helper는 (d)의 마지막과 같다.
- 넘김 판정은 rank마다다. 원인이 local인 rank는 순정 답을 지키고 다른 rank는 자기 확인을 통과해 아이 생성에서 그 rank를 기다린다(H7이 잰다).
- 원인 분류는 이 rank가 본 증거다(리뷰 L1). 이 rank의 소켓 오류(BADMAGIC, EBADF, ENOTCONN, 대응 없는 errno)와 이 rank의 거부 규칙이 만든
  ECONNREFUSED 두 번은 peer-dead가 된다. 상대가 local로 알린 실패(peer-reported)도 그 원인이 이 rank의 관리망 문제였을 수 있다. 반대로 unknown이나
  local로 매겨 막는 쪽(복구할 수 없는 분류, 범위 불일치, 상한 넘김, 죽음 거절 안의 느린 QP 오류 전환이 더하는 local)은 순정 답을 돌려주므로 안전하다.
- 응답 쪽은 REQ 전에 취소되었거나 범위 검사에서 거부된 뒤 다시 돈 라운드(`t[3] = 1`)를 상한 넘김에서 세지 않는다(리뷰 L5). 상한은 안전망이라 영향이
  작다 `[추론]`.
- FAIL 답은 재연결 처리에서만 보낸다. 거절한 rank의 helper가 셋째 상대와 긴 라운드 중이면 답이 늦다(리뷰 L6). C1, C3는 랭크 2개라 해당 없다
  `[추론]`.
- 응답 쪽의 범위 검사 명령은 라운드 감시(`NCCL_GIN_TS_ROUND_MS`) 밖에서 돈다(앞 빌드부터, 리뷰 L7). 펌웨어 감시는 그 단계도 매긴다.
- 로그 변화(리뷰 L8): 상대별 해제 줄이 devComm 단어 줄보다 먼저 나온다. 랭크 2개 펌웨어 초과의 넘김 유지 줄은 이제 "(local)"로 끝난다. 초과가
  `surfaced`를 세우지 않으므로, `NCCL_GIN_TS_ROUND_MS`보다 긴 명령은 상대 없는 드러냄도 낸다(B1의 8 s는 해당 없음).

### 2. 드라이버

- `../gin_ts2.cu`(gin-harden, gin-handoff가 고쳐 온 공용 드라이버를 같은 자리에서 고침): `GIN_RDV_NONCE`가 있으면 확인하는 랑데부. rank 0은 연결마다
  16바이트 인사(magic "GINRDV01" + 고유값)를 먼저 보내고, 같은 기록과 rank 1을 답한 연결만 받는다. rank 1은 그 인사를 읽고 확인하기 전에는 아무것도
  보내지 않는다(틀리면 닫고 200 ms 뒤 다시). `GIN_RDV_TEST_DECOY_PORT`(시험)는 진짜 랑데부 전에 가짜 수신 대기에 한 번 연결해 같은 확인으로
  거부하는지 본다. 이 변수가 없으면 앞 드라이버와 같다. kv `rdv`, `rdv_rejected`, `rdv_foreign`, `rdv_port`, `rdv_decoy`.
- [gin_mr.cu](gin_mr.cu)(`../multirank/gin_mr.cu`의 복사본, 그 파일은 고치지 않음): 같은 확인하는 랑데부(rank r > 0 모두), 그리고
  `GIN_MR_SHRINK=<k>`, `GIN_MR_CHILD=1`.
  - 주 단계가 끝나면 k가 아닌 rank가 모두 `ncclCommShrink(comm, {k}, NCCL_SHRINK_ABORT)`를 부른다.
  - `GIN_MR_CHILD=1`이면 아이 communicator에 창과 GIN 문맥 devComm을 만들고, 아이 rank 사이 모든 간선에서 주 단계와 같은 커널로 통신한 뒤 검사하고,
    아이의 모든 것을 해제한다.
  - 단계 전체를 `GIN_MR_PHASE_S`로 묶는다. 넘으면 `ch_outcome=timeout`을 쓰고 종료 코드 8로 끝난다.
- 대조 빌드의 드라이버: 랭크 2개 대조(`hf`, `hfp`)는 gin-handoff 번들의 드라이버(`9493584d`)를 그대로 쓴다. 이 드라이버는 `GIN_RDV_NONCE`를 모르고
  앞 방식으로 랑데부한다. 실행기의 포트 고르기는 같다. 두 드라이버의 차이는 NCCL 초기화 전의 랑데부뿐이라 대조는 라이브러리만 다르다 `[소스]`.
- 랭크 4개 대조(`hf`)는 `mr/hq` 드라이버(이 실험의 헤더로 빌드)를 `hf` libnccl과 쓴다. 장치 코드의 차이는 게이트 `test` 칸의 단어를 대기도 읽는
  것뿐인데, `hf` 라이브러리는 그 칸에 communicator 단어(= devComm 단어)를 쓰므로 대기의 해제는 `hf`의 것과 같다 `[소스]`.

### 3. 실행기와 포트 고치기

- [run_trial_hq.sh](run_trial_hq.sh)(랭크 2개), [run_mr_hq.sh](run_mr_hq.sh)(랭크 N개): 각각 `../harden/run_trial_hd.sh`, `../multirank/run_mr.sh`의
  복사본이고 원본은 고치지 않는다.
- 포트([portpick.sh](portpick.sh)):
  - 범위 29000–30999(임시 포트 범위 밖이라 커널이 나가는 연결에 주지 않는다). 첫 후보는 실행기 PID와 난수로 정한다.
  - rain과 sunny 모두에서 어떤 상태의 TCP 소켓도 그 포트를 쓰지 않을 때만 고르고, 아니면 다음 후보로 간다(32개까지).
  - 시행마다 64비트 난수 고유값을 모든 rank에 준다(`GIN_RDV_NONCE`).
  - rank 0의 관리망 주소는 실행 때 찾는다(`run_mr.sh`가 적어 두던 주소를 빼고 gin-harden 실행기처럼 경로에서).
- 시험: `PORT_OCCUPY=1`은 첫 후보에 수신 대기를 띄워 막은 뒤 고르게 해 그 포트를 건너뛰는지 보고, `RDV_DECOY=1`은 다른 빈 포트에 가짜 수신
  대기(틀린 인사를 보내고 받은 바이트를 셈)를 띄운다. 둘 다 `timeout` 래퍼 안에서 돌고 기록한 PID로 멈춘다.
- 이 실험은 iptables를 쓰지 않는다(`MGMT_MUTE` 없음). helper 포트를 고정하지 않으므로 helper 수신 대기는 커널이 고르는 임시 포트다(충돌하지 않음).

### 빌드 ([build_hq.sh](build_hq.sh), 세션 스크래치)

1. `setup`: `agent_ts2hf`의 소스, `build/`, `build-hfp/`를 `agent_ts2hq`로 복사한다(`build-hfp/`는 `build-hqp/`가 됨). 의존 파일과 장치 manifest의
   경로를 바꾸고 원래 시각을 돌려준다. `agent_ts2hf` 작업 트리(= `../handoff/hf_layer.diff`, md5 `a2bcaf69`)를 스크래치 저장소에 "gin-handoff hf
   (libnccl b6372d86)" 커밋으로 남긴다. 복사 직후 `make -n`은 버전 표시만 다시 컴파일한다 `[측정]`.
2. `hq`: 이 계층을 작업 트리에 두고 증분 빌드. 바뀐 장치 헤더(`gin_gdaki.h`)는 NCCL 자신의 장치 객체가 포함하지 않아(의존 파일에 없음) 장치 객체는
   다시 컴파일하지 않는다 `[측정]`. libnccl → `out/hq`.
3. `hqp`: `build-hqp/`에서 `CXXFLAGS=-DNCCL_GIN_TS_PRODUCTION`으로 증분 빌드. 두 빌드의 설치된 장치 헤더가 같은지 확인한다. libnccl → `out/hqp`.
4. `drivers`: `../gin_ts2.cu`와 `gin_mr.cu`를 `build/` 헤더로 컴파일(경고를 오류로). `out/drv/gin_ts2`, `out/mr/gin_mr`, `out/build_info.txt`.

빌드는 nice 19, 유휴 I/O 우선순위, 8 작업으로 돌렸다(다른 실험이 같은 노드에서 돈다).

### 배포 ([deploy_hq.sh](deploy_hq.sh), 메인 세션)

두 노드의 새 디렉터리 `hq/`, `hqp/`, `mr/hq/`에 둔다(8절 배포). 확인 출력은 파일로만 받는다. 배포 전에 sunny에서 포트 범위가 비어 있는지 읽기만 해서
확인한다(5절). 2026-10-09에 메인 세션이 확인하고 배포했다(29 s, 12절).

```
ssh <sunny> "ss -Htan '( sport >= :29000 and sport <= :30999 )' | wc -l; ss -ltn"   # 0이어야 함(메인 세션)
cd /home/unionxic/rdma-error-wt/gin-peer/harness/gpu-initiated/gin_recovery/peer
bash deploy_hq.sh deploy_check.txt
```

### 실행 ([hold.sh](hold.sh), [chain.sh](chain.sh), [cells.sh](cells.sh))

hold마다 `chain.sh`가 `cluster_run.sh -w 10800 -t gpq-<hold>`에 넣는다. 결과 폴더 아래 랭크 2개 시행은 빌드별 폴더(`hq/`, `hf/`, `hqp/`, `hfp/`)에,
랭크 4개 시행은 `mr_hq/`, `mr_hf/`에 쌓인다.

| hold | 내용 | 시간 |
|---|---|---|
| P0 pilot | 랭크 2개 새 셀과 대조 1회씩, `hd_fwslow_f1_b`, `pq_copystall1_shrink_b`, `pq_rdv_b`, `f1_b` 1회씩, 4 KiB 지연 두 빌드 1회씩(14회). 채점 안 함 | 실행 118 s `[측정]` |
| P1 pilot | 랭크 4개 새 셀과 대조 1회씩(8회). 채점 안 함 | 실행 187 s `[측정]` |
| P2 pilot | pilot 뒤 바꾼 경합 셀 두 개를 빌드마다 1회씩(4회). 채점 안 함. 태그 전에 돈다(8절) | 실행 92 s `[측정]` |
| H1 | 랭크 2개 회귀 6셀 × 5, `hdp_kill_b` 5, 지연 20실행 | 약 6.5분 |
| H2 | `pq_repost_r1_b`(`hq` 10, `hf` 5, 2:1), `hd_repost_f1_b` 5, `hd_fwslow_f1_b` 5, `pq_rdv_b` 5 | 약 3.5분 |
| H3 | `pq_ackrace_f1_b`(2:1), `pq_ackrace_f1r1_b`(1:1) | 약 10분 |
| H4 | `pq_copystall_shrink_b`(2:1), `pq_copystall1_shrink_b` 5, `hd_shrink_b` 5 | 약 4분 |
| H5 | `mr4_kill3_peer`(2:1), `mr4_kill3` 5 | 약 8분 |
| H6 | `pq4_fwslow`(2:1) | 약 6.5분 |
| H7 | `pq4_kill3_shrink` 10, `mr4_none` 5, `mr4_f1_01` 5 | 약 8분 |
| H8 | `pq4_local_shrink`(1:1), `pq4_rdv` 3 | 약 6분 |

시간 어림 `[측정, 추론]`. hold 하나 = 시행마다 (`wall_s` + 2.7 s) + 31 s다.
- 2.7 s는 pilot에서 잰 시행 사이 비용이다(포트 고르기, 원격 실행, 스냅숏; P0 (118 − 81.5) s / 14회 = 2.6 s, P1 (187 − 165.1) s / 8회 = 2.7 s).
- 31 s는 hold마다 유휴 링크를 기다린 시간이다(P0 30 s, P1 31 s).
- `wall_s`:
  - pilot에서 잰 셀: `pq_repost_r1_b` 2.8 s, `hd_fwslow_f1_b` 5.8 s, `pq_copystall_shrink_b` 5.6 s와 6.8 s, `pq_copystall1_shrink_b` 5.3 s, `pq_rdv_b`
    3.8 s, `mr4_kill3_peer` 20.1 s와 18.1 s, `pq4_fwslow` 22.0 s와 18.1 s, `pq4_kill3_shrink` 21.1 s, `pq4_local_shrink` 29.1 s와 18.6 s, `pq4_rdv`
    18.0 s(각 n=1, `hq`와 `hf` 순).
  - 회귀 셀은 gin-harden과 gin-handoff 본 실행의 중앙값이다(`f3_b` 7.3 s, `f4_b`와 `hdp_kill_b` 5.3 s 등, 각 n=5).
  - `mr4_none`, `mr4_f1_01`은 gin-multirank 18.0–18.1 s(각 n=10)다.
  - 바뀐 경합 셀은 약 20 s다 `[추론]`: 응답 쪽 거절이 helper 시작 뒤 약 6.3 s, 그 뒤 12 s 머묾과 정리.
  - `mr4_kill3`은 약 20 s다 `[추론]`: kill 9 s, 생존 rank 받기의 한도 10 s.

가장 긴 H3도 880 s 안이다. 본 실행(H1–H8)의 클러스터 시간은 잠금 대기를 빼고 약 52분이다 `[추론]`.

```
cd /home/unionxic/rdma-error-wt/gin-peer/harness/gpu-initiated/gin_recovery/peer
bash chain.sh results/20261009_pilot P0 P1                  # pilot(끝남), 채점 안 함
bash chain.sh results/20261009_pilot2 P2                    # 바뀐 경합 셀의 pilot, 태그 전, 채점 안 함
bash chain.sh results/<날짜> H1 H2 H3 H4 H5 H6 H7 H8          # 본 실행(태그 뒤)
bash chain.sh results/<날짜> fill:<폴더>:<셀>@<빌드>:<수>:<시작번호>[,...]   # 제외된 시행 채우기
```

### 채점

```
python3 score.py results/<날짜>
```

`results/<날짜>/SCORE.md`와 `results/<날짜>/trials_scored.csv`가 나온다. 원시 로그는 Release에 올린다.

## 10. 완료 조건과 QA 기준

- [x] 메인 세션이 pilot(P0, P1, P2)을 돌리고 결과를 12절에 적은 뒤, 고칠 것을 고치고 태그를 달았다(pilot 셋과 그 반영은 끝남, 태그 남음). 태그는
  사전 등록 커밋 `551c796f`에 달렸다(13절).
- [x] 모든 셀이 계획한 반복 수만큼 실행됐다. 제외와 실패를 따로 센 표가 있다([SCORE.md](results/20261009/SCORE.md) 끝 표). 시행 203, 제외 0.
- [x] 예측 37줄마다 판정(맞음, 틀림, 자료 부족)과 놓친 시행 목록이 있다([SCORE.md](results/20261009/SCORE.md)).
- [x] 다른 에이전트가 `score.py`를 보지 않고 원자료에서 핵심 수치를 다시 셌다(생존 간선의 결과, 거절 대상과 원인, 상대별 해제 줄, 감시 발동과
  복구, 계획 검사의 위치, FAIL 답과 거절 시각, 넘김과 유지, 아이 통신, 랑데부 확인, 지연)([qa_recount.md](results/20261009/qa_recount.md)).
- [x] 다른 에이전트가 `hq_layer.diff`를 읽고 리뷰했다(12절).
- [x] 다른 에이전트가 드라이버, 실행기, 채점 코드를 리뷰했다([qa/code_review.md](qa/code_review.md)).
- [x] smoke와 pilot, 제외 시행이 결과에 섞이지 않았다(pilot은 다른 결과 폴더, 본 실행 폴더의 파일은 모두 사전 등록 뒤에 생김).
- [x] 새 빌드의 md5, 전체 diff, pristine + diff 확인, 운영 빌드의 strings 확인을 5절과 12절에 적었다.
- [x] 원자료를 Release에 올리고 `DATA.md`에 적었다(`data-20261009`, 14절).
- [x] hold 전후 mlx5 스냅숏에 새 명령 오류가 없었다(새 줄은 H1의 sunny "FWTracer: Events were lost" 하나, 명령 오류 아님). iptables 규칙이 늘지
  않았다. CUDA 메모리 오류가 없었다.

## 11. 작업 체크리스트

- [x] 앞 실험의 지적과 측정 다시 확인(1절)
- [x] 라이브러리 계층, 드라이버 두 개의 랑데부, `gin_mr`의 shrink와 아이 단계 구현
- [x] 빌드: `hq`, `hqp`, 드라이버 두 개. pristine + diff 확인(12절)
- [x] 독립 리뷰(다른 에이전트)와 반영(12절)
- [x] `run_trial_hq.sh`, `run_mr_hq.sh`, `portpick.sh`, `cells.sh`, `hold.sh`, `chain.sh`, `deploy_hq.sh`, `rows_pq.py`, `score.py`,
  `predictions.csv`
- [x] 채점 스크립트 합성 시험(실제 측정 아님, 12절)
- [x] 질문, 가설, 셀, 예측 초안 (`DRAFT`)
- [x] sunny 포트 범위 확인과 배포(메인 세션, 12절)
- [x] pilot P0, P1(메인 세션, 채점 안 함), 결과로 고칠 것 고치기(12절)
- [x] pilot P2: 바뀐 경합 셀 두 개(메인 세션, 태그 전, 12절)
- [x] 고정 절 완성, 상태 `PREREGISTERED`, 해시 기록을 커밋 하나로 만들고 그 커밋에 `prereg/` 태그
- [x] 본 실행 H1–H8 (`RUNNING`, 09:01:02–09:51:37)
- [x] 채점 (`QA`)
- [x] 독립 재계산과 측정 코드 리뷰
- [x] 결과 정리, 원자료 Release(`data-20261009`). PR은 메인 세션이 연다
- [x] 결론 확정 (`COMPLETE`)

## 12. 실행 기록 (시간순)

| 시각 | 무엇을 했나 | 결과와 근거(경로, 커밋, 실행 ID) |
|---|---|---|
| 2026-10-09 | 앞 실험의 지적과 측정을 다시 확인: bind 실패 7회(gin-harden 4, gin-handoff 1, gin-multirank 2), gin-multirank kill 셀의 생존 받기 실패 10/10과 보내기 실패 10/10 `[측정: 세 실험의 trials_scored.csv에서 다시 셈]`. rain 임시 포트 범위와 수신 대기 포트 `[측정]` | 1절, 5절 |
| 2026-10-09 | 스크래치 `agent_ts2hq` 준비(`build_hq.sh setup`): `agent_ts2hf`(작업 트리 md5 `a2bcaf69`, 빌드 `b6372d86`, 운영 빌드 `1ae4ce9a`) 복사, 경로 바꿈, "gin-handoff hf" 커밋. 복사 직후 `make -n`의 컴파일 명령 1개(버전 표시) `[측정]` | [build_hq.sh](build_hq.sh) |
| 2026-10-09 | 계층 구현(9절 1번), 드라이버 둘(9절 2번), 실행기와 포트 고르기(9절 3번), 셀, hold, 채점기, 예측 초안 | 이 폴더 |
| 2026-10-09 | 첫 빌드(리뷰 전) `hq`, `hqp`, 드라이버. 중간에 끊긴 make 하나가 객체 일부를 바꿔 두어 host 객체 184개를 모두 다시 컴파일했고, 같은 소스의 `hq` libnccl md5가 두 번 모두 `68f63571`이었다 `[측정]` | 세션 스크래치 `hq_work/build_*.log` |
| 2026-10-09 | 독립 리뷰(다른 에이전트, 읽기만, 빌드 안 함): 판정 "usable with fixes". blocker와 high 없음, 중간 4, 낮음 8, 사소 4. 코드로 반영: M1(FAIL과 NACK에 보낸 쪽 원인, 받는 쪽은 local일 때만 peer-reported), M2(펌웨어 감시가 단계마다 한 번 매김), L2(NACK 16), 사소 넷(`ovPeer` 삭제, 중복 선언 삭제, 응답 쪽 NACK의 고유값, REQ를 받을 때 단어 확인). 문서로만: M3(sticky는 문맥별), M4(상대를 모르는 대기), L1, L3–L8(9절 1번 (b), (d), (e), (f), (h)). 셀과 예측은 바꾸지 않았다. 영향 확인 `[소스]`: A1과 C1에서 rank 0의 원인이 peer-reported에서 unknown이 되지만 두 예측은 원인을 보지 않는다. H3은 rank 1의 NACK(정지 실패, 코드 3)가 local을 실어 rank 0이 그대로 peer-reported다 | 9절 1번 |
| 2026-10-09 | 리뷰 반영 빌드: 증분 빌드가 컴파일한 객체 2개(장치 0), 컴파일 경고 0. libnccl `hq` `c1311625`, `hqp` `4fa076e1`, `gin_ts2` `3e053ff2`, `gin_mr` `7f0fc272`. [make_diff_hq.sh](make_diff_hq.sh): `hq_layer.diff` `34ab6201`(5개 파일, +565/−147줄), 전체 diff `5b7c3049`, VERIFIED 둘(순정 + 전체 diff, 순정 + 네 계층 diff가 각각 빌드 트리와 같음). strings: `NCCL_GIN_TS_TEST_` 문자열이 `hq`에 16개, `hqp`에 0개. `hqp`에 이 실험 시작 줄 형식 1개 `[측정]` | 5절, `agent_ts2hq/out/build_info.txt` |
| 2026-10-09 | 채점기 합성 시험(측정 아님). 세션 스크래치 폴더에 세 가지를 두고 `score.py`를 돌렸다: gin-handoff 본 실행의 실제 `f1_b@hf` 시행 5개, 실제 gin-handoff `f1_b` 시행에 이 계층 형식의 줄을 손으로 붙인 랭크 2개 시행 1개, 실제 gin-multirank `mr4_kill3_peer` 시행에 이 계층 줄과 아이 kv를 붙인 랭크 4개 시행 1개. 결과: 예외 없이 37줄을 모두 평가했다(Q1 맞음, 나머지는 계획 수 부족으로 자료 부족). 붙인 줄에서 나온 열이 모두 기대값과 같았다(예: `planrej_qp_r1` 1, `fwover_ms_r1` 3012, `decl_after_unmute_ms_r0` 100, `uapeer` "0-3;1-3;2-3", `ch_ok_ranks` 3, `ch_tx_ok_sum` 6). 감시 줄을 붙인 랭크 2개 시행은 펌웨어 초과로 제외되어 제외 규칙도 동작했다. 예측 37줄의 판정식이 쓰는 열 이름은 모두 그 시행 종류의 행에 있다 | 세션 스크래치 `hq_work/make_synth.py`, `hq_work/synth_res/` |
| 2026-10-09 | (초안까지) 클러스터에서는 아무것도 돌리지 않았다. 배포, pilot, 본 실행은 메인 세션이 한다 | |
| 2026-10-09 08:36 | sunny 포트 범위 확인(메인 세션, 읽기만): 로컬 포트가 29000–30999인 TCP 소켓 0개, 원격 포트가 그 범위인 소켓 1개(다른 호스트로 나가는 연결). rain은 양쪽 모두 0 `[측정, 메인 세션]` | 5절 |
| 2026-10-09 08:36:53–08:37:22 | 배포(메인 세션) `bash deploy_hq.sh deploy_check.txt`, rc 0. "deployed md5 == source on both nodes", "existing bundle unchanged on both nodes (46 files each)". 두 노드의 md5 5개가 5절과 같다 `[측정]` | [deploy_check.txt](deploy_check.txt)(128줄, 주소 없음) |
| 2026-10-09 08:37:26–08:43:32 | pilot(메인 세션) `bash chain.sh results/20261009_pilot P0 P1`. P0: 잠금 08:37:26, 유휴 링크 08:37:56, 끝 08:39:54(실행 118 s, 14회). P1: 잠금 08:39:54, 유휴 링크 08:40:25, 끝 08:43:32(실행 187 s, 8회). 두 hold 모두 rc 0. hold 앞뒤 `gin-` iptables 규칙 0, 새 mlx5 줄 0, cmd_err rain 2와 sunny 0, rain 펌웨어 명령 실패 합 31로 그대로, 남은 프로세스 0, STOP 파일 없음. rank 종료 코드: 의도한 거절 셀 4, 투명 셀 0, kill된 rank 255(3회), 단계 한도의 rank 8(2회) `[측정]` | `results/20261009_pilot/`(`chain.out`, `hold_P0.out`, `hold_P1.out`, `snap_*`), 세션 스크래치 `cluster_run.log` 1669–1674줄 |
| 2026-10-09 | pilot 검토(채점 아님). `score.py`를 pilot 사본에 돌려 열을 만들고, 22회 모두 로그와 kv를 직접 대조했다(아래 표). 하네스 결함 하나: 경합 셀 두 개에서 응답 쪽이 거절 0.34–0.38 s 뒤 끝나(드라이버 기본 끝 대기 0.3 s), 시작 쪽의 끊김 끝 0.24–0.27 s 뒤 첫 다시 걸기나 확인 접속이 연결 거부를 받고 1.24–1.28 s 뒤 상대를 죽음으로 거절했다(4회 모두). 그래서 FAIL 답 경로는 돌지 않았다. 다른 셀의 시행 18회는 해당 예측 조건과 맞았다. 파서 결함은 찾지 못했다 `[측정]` | 아래 pilot 표, 세션 스크래치 `hq_work/pilot_eval.py` |
| 2026-10-09 | pilot 뒤 변경. 예측은 바꾸지 않았다(`predictions.csv` sha256 `dccdf05c…`, 초안과 같음). (1) [cells.sh](cells.sh): 경합 셀 두 개의 응답 쪽에 `GIN_TS_END_WAIT_S=12`(드라이버 스위치, 두 번들의 드라이버에 있음). 12 s는 시작 쪽의 재연결 한도(취소에서 10 s)에 2 s를 더한 값이다. 끊김 끝은 취소 1.73–1.77 s 뒤였다. (2) [rows_pq.py](rows_pq.py) `end_wait_r*`, [score.py](score.py) 설정 확인 `config_linger`. pilot 경합 시행 4회는 이 확인에 걸린다. (3) [hold.sh](hold.sh) P2. (4) 시각 값은 측정으로 확인하고 그대로 두었다: 경합 셀의 장애 1 500 ms와 끊김 500:8000(4회 모두 ACK 기다림 중 취소, 응답 쪽은 커밋 뒤 거절), `pq4_fwslow` 둘째 장애 11 500 ms(rank 0 거절 1.43 s 뒤, 두 빌드), `pq4_local_shrink` 단계 한도 12 s, `pq4_kill3_shrink` 40 s(아이 단계 전체 3 s 미만). (5) 9절 hold 시간을 측정값으로 다시 어림했다: 본 실행 약 52분 | 3, 7, 8, 9절 |
| 2026-10-09 08:56:53–08:58:56 | pilot P2(메인 세션) `bash chain.sh results/20261009_pilot2 P2`, rc 0. 잠금 08:56:53, 유휴 링크 08:57:24, 끝 08:58:56(실행 92 s, 4회). hold 앞뒤 `gin-` iptables 규칙 0, 새 mlx5 줄 0, cmd_err rain 2와 sunny 0, rain 펌웨어 명령 실패 합 31로 그대로, 남은 프로세스 0. 네 시행 모두 응답 쪽이 거절 12.04–12.07 s 뒤 정리했고(`GIN_TS_END_WAIT_S=12`), 설정 확인 `config_linger`를 통과했으며, ACK 기다림 중 취소와 응답 쪽의 커밋 뒤 거절이 함께 생겼다(제외 없음). `hq` HELLO 형태: rank 1 "answered a re-dial of declined rank 0 with FAIL", rank 0 "rank 1 declined this pair (FAIL on re-dial)" 뒤 끊김 끝 233 ms에 "the peer declined this pair (FAIL on reconnect)"로 거절(원인 unknown). `hq` PROBE 형태: rank 0 "answered a probe of declined rank 1 with FAIL", rank 1이 끊김 끝 272 ms에 같은 사유로 거절. `hf` HELLO 형태: 다시 걸기 16번이 "not accepted (FIN)"이고, 끊김 끝 8 375 ms에 "peer liveness unknown (ETIMEDOUT, no reconnect within 10000 ms)"로 거절. `hf` PROBE 형태: 확인 접속은 답을 받았으나 rank 0이 다시 걸지 않아, 끊김 끝 8 270 ms에 같은 사유로 거절. 네 예측(C1–C4)의 조건이 각 1회에서 맞았다. 시각은 모두 거절한 rank 자신의 시계다. 읽기 오류는 없어 예측은 그대로다(`predictions.csv` sha256 `dccdf05c…`) `[측정]` | `results/20261009_pilot2/`(`chain.out`, `hold_P2.out`, 시행 로그) |
| 2026-10-09 09:00:54 | 사전 등록 | [PREREG.txt](PREREG.txt), 태그 `prereg/gin-peer-v1` |
| 2026-10-09 09:01:02 | 본 실행 시작(메인 세션, `bash chain.sh results/20261009 H1 H2 H3 H4 H5 H6 H7 H8`). chain 09:01:02–09:51:37. hold마다 잠금은 앞 hold가 끝난 즉시 얻었고 유휴 링크를 31 s 기다렸다 | `results/20261009/chain.out`, 세션 스크래치 `cluster_run.log` 1678–1701줄 |
| 2026-10-09 09:01:33–09:06:29 | H1(4분 56초, rc 0): 랭크 2개 회귀 30회(`f1_b`, `f3_b`, `bidirf_sym_b`, `f4_b`, `f2rel_b`, `hd_rxdeath_b` 각 5), 운영 빌드 kill 5회, 지연 20실행 `[측정]` | `hold_H1.out`, 꼬리표 `gpq-H1` |
| 2026-10-09 09:07:00–09:09:54 | H2(2분 54초, rc 0): 응답 쪽 계획 거부 `hq` 10과 `hf` 5, 시작 쪽 계획 거부 5, 랭크 2개 펌웨어 감시 5, 포트 셀 5 `[측정]` | `hold_H2.out`, `gpq-H2` |
| 2026-10-09 09:10:25–09:19:43 | H3(9분 18초, rc 0, 880 s 한도 안): ACK 경합 HELLO 형태 `hq` 10과 `hf` 5, PROBE 형태 `hq` 5와 `hf` 5 `[측정]` | `hold_H3.out`, `gpq-H3` |
| 2026-10-09 09:20:14–09:23:31 | H4(3분 17초, rc 0): 원인 rank 0 shrink `hq` 10과 `hf` 5, 원인 rank 1 shrink 5, 상대 죽음 shrink 5 `[측정]` | `hold_H4.out`, `gpq-H4` |
| 2026-10-09 09:24:02–09:31:23 | H5(7분 21초, rc 0): 랭크 4개 rank 3 kill, 상대별 flush `hq` 10과 `hf` 5, 문맥 전체 flush 5 `[측정]` | `hold_H5.out`, `gpq-H5` |
| 2026-10-09 09:31:54–09:37:43 | H6(5분 49초, rc 0): 랭크 4개 펌웨어 감시 `hq` 10, `hf` 5 `[측정]` | `hold_H6.out`, `gpq-H6` |
| 2026-10-09 09:38:14–09:45:38 | H7(7분 24초, rc 0): rank 3 kill 뒤 shrink와 아이 devComm 10, 랭크 4개 회귀 10 `[측정]` | `hold_H7.out`, `gpq-H7` |
| 2026-10-09 09:46:09–09:51:37 | H8(5분 28초, rc 0): 랭크 4개 원인 rank 0 shrink `hq` 5와 `hf` 5, 랭크 4개 포트 셀 3 `[측정]` | `hold_H8.out`, `gpq-H8` |
| 2026-10-09 | 본 실행 전체: hold 여덟 모두 rc 0, STOP 파일 없음, 채우기 hold 없음. hold 안 시간 합 46분 27초, 잠금에서 끝까지 50분 35초(9절 어림 약 52분). 모든 hold 앞뒤로 명령 오류 줄 rain 2와 sunny 0, rain 펌웨어 명령 실패 합 31로 그대로, `gin-` iptables 규칙 0, 모든 시행 `left=0`, 종료 코드 139나 illegal address 없음. 새 mlx5 줄은 H1의 sunny "FWTracer: Events were lost" 하나뿐이다(명령 오류 줄 아님) `[측정]` | hold 출력, `mlx5_new_H1.txt`, [qa_recount.md](results/20261009/qa_recount.md) 3절 |
| 2026-10-09 | 채점(메인 세션, `python3 score.py results/20261009`): 시행 203개(랭크 2개 115, 지연 20, 랭크 4개 68), 판정 203, 제외 0. 예측 37개 모두 맞음 `[측정]` | [SCORE.md](results/20261009/SCORE.md), [trials_scored.csv](results/20261009/trials_scored.csv) |
| 2026-10-09 | 독립 재계산(다른 에이전트가 `score.py`, `rows_pq.py`, `SCORE.md`, `trials_*.csv`, 앞 실험의 열 추출기를 보지 않고 원자료에서 열을 다시 뽑아 자기 판정식 평가기로 셈): 맞음 37, 틀림 0, 자료 부족 0. 무결성(태그가 `551c796f`, `predictions.csv` sha256이 작업 트리, 태그, `PREREG.txt`에서 같음, 고정 절과 셀, 실행기, 드라이버 소스가 태그와 같음. 실행기 셋은 주소 필터가 넣는 한 줄만 다름), 제외 0과 설정 확인 0건 확인, hold 출력 203줄이 시행 파일과 모두 맞음. 같은 이름의 다른 빌드 셀에 각 규칙의 조건을 대면 19쌍 모두 0건이라 규칙이 비어 있지 않다. 지연 p50을 원시 3000개에서 다시 계산해 kv와 20/20 같음. 문서와 다른 점 넷(이 문서에 본 실행 기록이 없었음, 10절 첫 상자 문구, pilot 표의 "8 ms", 9절 시간 어림)은 판정을 바꾸지 않으며 13절에 옮김 `[측정]` | [qa/recount.py](qa/recount.py), [qa_recount.md](results/20261009/qa_recount.md) |
| 2026-10-09 | 본 실행 뒤 코드 리뷰(다른 에이전트, 읽기만): 막는 것과 높음 없음. 37개 판정을 치우치게 한 것은 없고, 잰 범위 안에서 네 변경은 맞고 안전하며, 태그에서 HEAD까지 바뀐 것이 없다. 중간 하나(M1: 랭크 3개 이상에서 상대를 모르는 대기가 한 상대의 죽음에 풀리지 않는 설계의 대가, 시간 제한 형태만 잼), 낮음 아홉(L1 shrink 순간의 경합, L2 채점기에 없는 8절 규칙 넷, L3 포트 확인과 bind 사이, L4 FAIL 결과가 응답 쪽을 머물게 한 스위치에 기댐, L5 장치가 단어 배열을 읽는 길이 늘어남, L6 9절 2번의 대조 드라이버 문장, L7 가짜 수신 대기가 틀린 magic만 시험, L8 ssh 연결 시간 제한 없음, L9 NACK 1과 12의 고유값과 주석), 사소 여섯. 처리는 13, 17, 18, 19절 `[소스, 측정]` | [qa/code_review.md](qa/code_review.md) |
| 2026-10-09 | 나도 채점기 출력과 원시 kv, 로그에서 핵심 수치를 따로 셈: FAIL 답의 거절 시각(네 셀), 랭크 4개 kill 뒤 첫 거절(네 셀), 생존 간선과 올라간 단어, 랭크 2개 kill 거절, 받기만 하는 rank, 원격 접근 오류의 rank 1 abort, 랭크 2개 감시의 abort, 랭크 4개 펌웨어 셀의 거절과 둘째 장애 사이, shrink 시간, 아이 devComm 시간과 문맥 수, 지연 p50, 포트 범위와 후보 수, 확인한 랑데부 수, 가짜 수신 대기. 독립 재계산의 값과 모두 같음 `[측정]`. 이것은 독립 확인이 아니다 | [trials_scored.csv](results/20261009/trials_scored.csv), `results/20261009/mr_hq/*_r*.kv`, `*_r*.log` |
| 2026-10-09 10:22:02 | Release `data-20261009`(메인 세션): 본 실행 자산(파일 1 454개, 0.56 MB)과 pilot 자산 둘(파일 171개, 0.07 MB와 32개, 0.02 MB)을 내려받아 확인. `sha256sum -c` 통과, 주소를 바꾼 뒤 원본과 같고 실제 주소 접두가 없음 `[측정]` | 14절, [DATA.md](../../../../DATA.md) |
| 2026-10-09 | 마감: 상태 `COMPLETE`, 10, 11, 13–20절, 폴더 [README.md](README.md), `DATA.md`의 `data-20261009` 항목, 상위 README 두 개. 고정 절(2, 3, 7, 8절)은 고치지 않고 정정과 해석의 범위는 13절에 둠. 이 마감에서 클러스터 명령은 돌리지 않음 | 정리 커밋(이 실험의 PR) |

### pilot 시행별 확인 (채점 아님, 셀마다 n=1)

`[측정]` `results/20261009_pilot/`의 로그와 kv에서 직접 읽었다. "맞음"은 그 시행 하나가 해당 예측의 조건을 만족했다는 뜻이다.

| 셀@빌드 | 원자료에서 본 것 | 예측 조건 |
|---|---|---|
| `pq_repost_r1_b@hq` | rank 1이 커밋 전에 계획을 거부했다(QP 4개 중 둘째). rank 0에는 계획 검사 줄이 없고, 라운드 3.5 ms 뒤 NACK 15 사유로 거절했다. 두 rank 모두 복구 줄 0, 원인 unknown | 맞음 (A1) |
| `pq_repost_r1_b@hf` | rank 0이 복구 줄을 남기고 WQE 2개를 다시 보낸 뒤, rank 1의 FAIL로 거절했다 | 맞음 (A2) |
| `pq_ackrace_f1_b@hq`, `@hf` | rank 0이 ACK 기다림 중 취소했다(라운드 5.26 s 뒤 ETIMEDOUT). rank 1은 커밋 뒤 "peer closed the socket before DONE (ETIMEDOUT)"로 거절하고 0.35–0.38 s 뒤 끝났다. 끊김 끝 0.26–0.27 s 뒤 첫 다시 걸기부터 연결 거부, 1.27–1.28 s 뒤 죽음으로 거절 | 아님, 하네스 (C1, C2) |
| `pq_ackrace_f1r1_b@hq`, `@hf` | 같은 꼴을 rank 1이 시작했다(취소 5.23 s). rank 0은 거절 0.34–0.35 s 뒤 끝났고, 확인 접속이 거부되어 끊김 끝 1.24 s 뒤 죽음으로 거절 | 아님, 하네스 (C3, C4) |
| `pq_copystall_shrink_b@hq` | 첫 복사가 2 000 ms 상한을 넘겨 rank 0이 원인 local로 거절했다. shrink는 유지 줄("(local)")과 순정 답(remote error). rank 1은 FAIL을 받아 원인 peer-reported | 맞음 (H1) |
| `pq_copystall_shrink_b@hf` | shrink가 넘어가 1-rank communicator의 allreduce가 맞았다 | 맞음 (H2) |
| `hd_fwslow_f1_b@hq` | 감시가 commit 단계 3 000 ms에 한 번 발동했다. rank 1의 단어 다음 devComm 단어(fw-watchdog)가 올라가고 원인 local. abort 937.5 ms, helper 떼어 냄, rank 1 거절 | 맞음 (B1) |
| `pq_copystall1_shrink_b@hq` | rank 1이 복사 초과로 NACK(정지 실패)를 보내고 local로 거절했다. rank 0은 "peer NACK", peer-reported로 거절했다. shrink가 넘어가 1-rank allreduce가 맞았다 | 맞음 (H3) |
| `pq_rdv_b@hq` | 막아 둔 첫 후보 29342를 건너뛰고 29343을 썼다. 가짜 수신 대기(29344)는 연결 1, 바이트 0. rank 1 거부, 두 rank 확인, 투명 | 맞음 (Q2) |
| `f1_b@hq` | 투명. 통계 API는 두 rank 모두 라운드 1, 복구 1, 거절 0 | 맞음 (R1의 `f1_b`, R7) |
| `lat_4k@hqp`, `@hfp` | p50 10.75 µs와 10.69 µs, 차이 0.06 µs(각 1실행) | 맞음 (P1) |
| `mr4_kill3_peer@hq` | kill 9 000 ms. 세 생존 rank가 FIN을 보고 8 ms 안에 rank 3을 peer-dead로 거절했고, rank 3의 단어만 올렸다(devComm 단어는 정리 때 abort뿐). 생존 간선 6개 1 000회 정상, rank 3으로 보내기 3개 실패, rank 3에서 받기 3개 timeout, 세 rank 비동기 오류 | 맞음 (K1, K2, K3) |
| `mr4_kill3_peer@hf` | 생존 받기 6개 실패, 생존 보내기 실패 0 | 맞음 (K4) |
| `pq4_fwslow@hq` | rank 0의 rank 1 라운드가 commit 3 000 ms를 한 번 넘겼고, 장애 4.07 s 뒤 rank 1만 거절했다. rank 2의 장애는 그 1.43 s 뒤 왔다. rank 0이 좁힌 범위를 거부(rank 1 쪽 QP가 RTS 아님)해 전체 재설정으로 다시 돌았고, rank 2 시작, rank 0 응답으로 복구됐다. 나쁜 간선은 0>1, 1>0뿐, 올라간 단어는 0-1, 1-0뿐, devComm 단어 없음 | 맞음 (B2, B3, B4) |
| `pq4_fwslow@hf` | 감시가 오류를 드러내 rank 0이 rank 2의 라운드를 "the watchdog surfaced a fault earlier"로 거절했다. 간선 0>2, 0>3, 2>0, 3>0 중 3개 실패 | 맞음 (B5) |
| `pq4_kill3_shrink@hq` | 세 생존 rank의 shrink가 넘어갔다(10–1 191 ms). 3-rank 아이가 GIN 문맥 6개의 devComm을 163 ms에 열고 간선 6개 200회 정상 | 맞음 (H5) |
| `pq4_local_shrink@hq` | rank 0이 복사 초과로 local 거절, shrink 유지("(local)"), 아이 없음. rank 2, 3은 단계 한도 12 s에서 끝남(종료 코드 8) | 맞음 (H6, H7) |
| `pq4_local_shrink@hf` | rank 0의 shrink가 넘어가고 세 rank 모두 3-rank 아이를 얻음 | 맞음 (H8) |
| `pq4_rdv@hq` | 막아 둔 후보 30088을 건너뜀. 가짜 수신 대기는 연결 3, 바이트 0. rank 1–3 거부, 네 rank 확인, 투명 | 맞음 (Q3) |

## 13. 사전 등록 이후 변경

> 기존 문장을 고치지 않고 여기에 덧붙인다. 태그 뒤 이 실험의 셀, 실행기, 채점기, 예측, 라이브러리, 번들은 바뀌지 않았다(독립 재계산 2절, 리뷰 Focus 4).

| 날짜 | 무엇을 | 이유 | 영향 범위 | 커밋 |
|---|---|---|---|---|
| 2026-10-09 | 정정(10절 첫 상자): "태그 남음"은 사전 등록 커밋 자체에 적힌 문장이다. 태그 `prereg/gin-peer-v1`은 그 커밋 `551c796f`에 달렸다. 상자를 채우고 이 사실을 덧붙였다 | 독립 재계산 6절 2번 | 문구뿐 | 정리 커밋(이 실험의 PR) |
| 2026-10-09 | 정정(12절 pilot 표, `mr4_kill3_peer@hq`): "FIN을 보고 8 ms 안에 거절"은 8.5 ms 안이다. FIN 줄에서 거절 줄까지 rank 0, 1, 2에서 8.15, 6.21, 8.50 ms(pilot 1회, 같은 rank의 시계) `[측정]` | 독립 재계산 6절 3번 | 예측과 무관 | 정리 커밋(이 실험의 PR) |
| 2026-10-09 | 정정(9절 시간 어림): 바뀐 경합 셀을 "약 20 s"로 어림했으나, `wall_s`는 rank 0의 수명이라 HELLO 형태 `hq`에서 10.8 s(10회 모두), `hf`에서 18.8–18.9 s(5회), PROBE 형태에서 20.3–20.8 s(10회)였다 `[측정]`. HELLO 형태에서는 rank 0이 빨리 거절하고 끝나며 12 s 머무는 쪽은 rank 1이다 `[추론]`. hold 시간(잠금에서 끝)은 H1 5.45분(어림 6.5분)이고 나머지 일곱은 어림과 0.2분 안이었다. 본 실행 전체 50분 35초(어림 약 52분) `[측정]` | 독립 재계산 6절 4번, 리뷰 2.7 | 계획 수치뿐 | 정리 커밋(이 실험의 PR) |
| 2026-10-09 | 덧붙임(7절 조건 문구, 고정): `pq_ackrace_f1_b`의 "라운드 5.23–5.26 s 뒤 ETIMEDOUT"은 pilot 4회의 값이다. 본 실행 경합 시행 25회에서는 취소가 라운드 5.22–5.45 s 뒤, 끊김 끝이 취소 1.54–1.78 s 뒤였고, 셀 조건(ACK 기다림 중 취소, 응답 쪽의 커밋 뒤 거절)은 25/25 섰다 `[측정]` | 독립 재계산 6절 끝 | 판정 영향 없음 | 정리 커밋(이 실험의 PR) |
| 2026-10-09 | 덧붙임(3절 판정 경계, 고정): 랭크 2개 펌웨어 감시의 "3 000–3 500 ms"에서 감시 줄은 소수점 아래를 반올림한 ms를 찍고, 5회 모두 "3000"이라 아래 경계에 붙어 있다(랭크 4개 셀 10회도 "3000"). 감시는 3 000 ms를 넘은 첫 점검에서 매긴다 `[측정, 소스]` | 독립 재계산 4절 | 판정은 맞음 그대로. 여유가 없다는 사실만 적는다 | 정리 커밋(이 실험의 PR) |
| 2026-10-09 | 덧붙임(8절 실행, 고정): 8절 규칙 넷은 채점기가 자동으로 하지 않는다. 설정 확인 실패는 `config_*`로 표시만 하고 블록을 멈추지 않는다. 채움이 50%를 넘을 때의 자료 부족은 없다. 랭크 4개에는 시험 스위치 줄 확인이 없다. 랭크 4개 원인 rank 0 셀의 복사 조건은 모든 rank의 합으로 본다. 본 실행에서는 넷 다 해당하지 않았고 손으로 확인했다: 제외와 `config_*` 0, 채움 없음, `fw_delay=4000@commit`은 랭크 4개 펌웨어 셀 15회 모두 rank 0에만, `copy_stall=4000`은 랭크 4개 원인 rank 0 셀 10회 모두 rank 0에만 있고 `hq` 5회 모두 rank 0이 복사 시간 초과를 남김 `[측정, 리뷰]` | 리뷰 L2 | 영향 없음 | 정리 커밋(이 실험의 PR) |
| 2026-10-09 | 정정(9절 2번, 대조 드라이버): 랭크 2개 대조는 "라이브러리만 다르다"고 적었으나 틀렸다. `gin_gdaki.h`는 드라이버에 컴파일되는 장치 코드라, 쉬는 대기와 폴링이 상대별 단어를 읽는 부분은 이 실험의 `gin_ts2`(`3e053ff2`)에 있고 gin-handoff 드라이버(`9493584d`)에는 없다 `[소스]`. 랭크 2개 대조의 차이는 "라이브러리와 드라이버의 장치 코드"다. 랭크 4개 대조(`mr/hq` 드라이버에 `hf` libnccl)는 9절 2번대로 `hf`처럼 동작한다(`hf`가 게이트에 넣는 단어가 호출자의 단어와 같아 건너뜀) | 리뷰 L6 | 판정 영향 없음. 지연 비교(P1, P2)는 장치 변경까지 포함한 비교다 | 정리 커밋(이 실험의 PR) |
| 2026-10-09 | 정정(9절 1번 (e)): "모든 NACK에 고유값을 싣는다"는 틀렸다. `gdakiTsInitiate`가 만드는 NACK 1(동시 시작 규칙 끔)과 NACK 12(양보하는 시작 쪽의 범위 거부)에는 고유값이 없다(`gin_host_gdaki.cc` 5033–5039, 5073–5079). 설치된 소켓은 고유값을 확인하지 않아 영향이 없다. `gdakiTsEscalated`의 주석(4596–4598)도 실제 동작(이미 상한에 걸린 뒤에만 재실행을 막음)과 다르게 적혀 있다 `[소스]` | 리뷰 L9 | 영향 없음. 소스는 다음 계층에서 고친다(19절) | 정리 커밋(이 실험의 PR) |
| 2026-10-09 | 해석의 범위(2절 H1, 고정): 상대를 모르는 대기(`waitSignal`, `waitCounter`, 배리어, void 판)는 랭크 3개 이상에서 한 상대의 죽음에 풀리지 않는다. 이 실험은 그런 대기를 장치 시간 제한(10 s)이 있는 형태로만 쟀다(`gin_mr`). 시간 제한 없는 대기는 응용이 abort하거나 shrink할 때까지 돈다. gin-handoff에서는 바로 오류로 풀렸다 `[소스]` | 리뷰 M1(설계 단계 리뷰 M4) | 결론과 README의 문장을 이 범위로 썼다(17, 18절) | 정리 커밋(이 실험의 PR) |
| 2026-10-09 | 해석의 범위(2절 H4, H5, 고정): FAIL 답의 결과는 거절한 rank가 살아 있을 때의 결과다. 경합 셀은 응답 쪽을 12 s 머물게 해서 그 조건을 만들었다(pilot 뒤 추가, 12절). 그 경합 뒤 FAIL은 응답 쪽의 원인 unknown을 싣고, 두 rank의 원인이 모두 unknown이라 어느 쪽의 중단 shrink도 넘어가지 않는다(`hq` 경합 시행 15/15 두 rank 모두 unknown) `[측정]` | 리뷰 L4 | 17, 18절 | 정리 커밋(이 실험의 PR) |

## 14. 원자료와 결과표

| 무엇 | 경로 또는 Release 자산 | n |
|---|---|--:|
| 채점표(예측별 판정, 놓친 시행, 셀별 제외) | [results/20261009/SCORE.md](results/20261009/SCORE.md) | 예측 37 |
| 시행별 값(채점 상태 포함) | [results/20261009/trials_scored.csv](results/20261009/trials_scored.csv) | 203(판정 203) |
| 독립 재계산 | [results/20261009/qa_recount.md](results/20261009/qa_recount.md), 스크립트 [qa/recount.py](qa/recount.py) | 203 |
| 본 실행 뒤 코드 리뷰 | [qa/code_review.md](qa/code_review.md) | |
| 본 실행 원자료(빌드별 시행 로그와 kv, hold 출력, 스냅숏) | Release `data-20261009`, `harness__gpu-initiated__gin_recovery__peer__results__20261009.tar.xz`(파일 1 454개, 0.56 MB, sha256 앞 12자리 `3521f5bf229c`) | 203 |
| pilot P0, P1 원자료(채점 안 함) | Release `data-20261009`, `harness__gpu-initiated__gin_recovery__peer__results__20261009_pilot.tar.xz`(파일 171개, 0.07 MB, `b726295b203f`) | 22 |
| pilot P2 원자료(채점 안 함) | Release `data-20261009`, `harness__gpu-initiated__gin_recovery__peer__results__20261009_pilot2.tar.xz`(파일 32개, 0.02 MB, `5deb8bad60d7`) | 4 |
| 배포 확인 | [deploy_check.txt](deploy_check.txt) | |
| 사전 등록 | [predictions.csv](predictions.csv), [PREREG.txt](PREREG.txt), 태그 `prereg/gin-peer-v1`(`551c796f`) | 37 |

빌드별 중간 표(`trials_hq.csv` 등)는 `trials_scored.csv`에 모두 들어 있어 커밋하지 않았다. Release 자산은 메인 세션이 10:22:02에 내려받아
확인했다(12절).

## 15. 결과 요약

판정: **예측 37개 모두 맞음**(시행 203, 판정 203, 제외 0). 채점 [SCORE.md](results/20261009/SCORE.md), 독립 재계산도 37/37
([qa_recount.md](results/20261009/qa_recount.md)) `[측정]`. 아래 범위는 따로 적지 않으면 그 셀 키의 판정 시행 전체에 걸친 범위다.

**1. 랑데부 포트** `[측정]`
- 본 실행 203회에서 bind 실패 0. 고른 포트는 29019–30999(203회, 서로 다른 값 193개)로 모두 29000–30999 안이다.
- 첫 후보를 쓴 시행 195회, 후보 2개를 본 시행 7회, 4개를 본 시행 1회. 여러 후보를 본 8회는 모두 첫 후보를 막아 둔 포트 셀이고, 막은 포트를
  8/8 건너뛰었다. 4개를 본 1회는 같은 hold 앞 시행의 랑데부와 가짜 수신 대기 포트가 아직 TIME_WAIT였던 것으로 본다 `[추론]`.
- 가짜 수신 대기: 랭크 2개 5회는 각 연결 1, 랭크 4개 3회는 각 연결 3이었고 받은 바이트는 8회 모두 0이었다. 연결한 rank가 모두 거부했다(rank 1
  5/5, rank 1–3 3/3).
- 확인한 랑데부(rank별 kv): 이 실험 드라이버의 rank 파일 482개가 모두 `verified`(랭크 2개 연구 빌드 180, 운영 빌드 30, 랭크 4개 `hq` libnccl 212,
  `hf` libnccl 60). gin-handoff 드라이버를 쓰는 랭크 2개 대조 60개 rank 파일은 확인 없는 앞 방식이다.

**2. 상대별 abort 단어: 랭크 4개, rank 3 SIGKILL**(kill 9 000 ms, 생존 rank 0, 1, 2) `[측정]`

| 조건 | 셀 키 | n | 생존 간선 6개 | rank 3으로 보내기, rank 3에서 받기 | 올라간 단어 | kill 뒤 첫 거절(rank 0 시계) | 예측 |
|---|---|--:|---|---|---|---|---|
| 상대별 flush, 이 실험 | `mr4_kill3_peer@hq` | 10 | 6/6 정상 10/10 | 보내기 3 실패, 받기 3 timeout(10 s 한도) | rank 3의 상대별 단어만("0-3;1-3;2-3"), devComm 단어 오류 줄 0 | 6.1–18.5 ms(n=30, 생존 3 × 10회) | K1–K3 맞음 |
| 같음, gin-handoff | `mr4_kill3_peer@hf` | 5 | 0/6: 받기 6 실패, 보내기 실패 0 | 보내기 3 실패, 받기 3 오류 | devComm 단어 오류 줄 생존마다 1 | 6.5–8.9 ms(n=15) | K4 맞음 |
| 문맥 전체 flush, 이 실험 | `mr4_kill3@hq` | 5 | 0/6: 보내기 6 실패, 받기 6 timeout | 같음 | 상대별 단어만 | 6.3–15.2 ms(n=15) | K5 맞음 |
| 상대별 flush, shrink 셀 | `pq4_kill3_shrink@hq` | 10 | 6/6 정상 10/10 | 같음 | 상대별 단어만 | 5.8–8.9 ms(n=30) | (H5의 셀) |

- 생존 rank는 모두 rank 3만 원인 peer-dead로 거절했고, 세 rank 모두 비동기 오류를 봤다(모든 kill 시행).

**3. gin-harden 리뷰의 세 지적** `[측정]`

| 지적 | 셀 키 | n | 결과 | 예측 |
|---|---|--:|---|---|
| (a) 응답 쪽이 커밋 전에 계획 거부 | `pq_repost_r1_b@hq` | 10 | rank 1이 QP 4개 중 둘째에서 거부, rank 0 계획 없음, 두 rank 복구 줄 0, rank 0이 "peer NACK (its re-post plan was rejected)"로 거절. 10/10 | A1 맞음 |
| (a) 같음, gin-handoff | `pq_repost_r1_b@hf` | 5 | rank 1이 DONE 뒤 거부, rank 0은 이미 다시 보내 복구 줄 1개를 남긴 뒤 "the peer declined"로 거절. 5/5 | A2 맞음 |
| (a) 시작 쪽이 계획 거부(회귀) | `hd_repost_f1_b@hq` | 5 | rank 0이 둘째 QP에서 거부, 복구 줄 0, rank 1 "peer FAIL before DONE". 5/5 | A3 맞음 |
| (b) 랭크 2개, commit 단계 8 s(회귀) | `hd_fwslow_f1_b@hq` | 5 | 감시 한 번, "3000 ms"(13절), devComm 단어 why fw-watchdog, abort 650.6–1 002.2 ms, helper 떼어 냄, rank 1 거절 | B1 맞음 |
| (b) 랭크 4개, rank 0의 rank 1 라운드 commit 4 s | `pq4_fwslow@hq` | 10 | 감시 한 번(rank 0, 상대 1, commit). rank 0이 장애 4 057–4 067 ms 뒤 rank 1만 거절, rank 1은 "peer FAIL before DONE"으로 rank 0만 거절. rank 2의 장애는 그 거절 1 433–1 443 ms 뒤였고, rank 2(시작)와 rank 0(응답)의 라운드가 복구됨 10/10. 올라간 단어 0-1, 1-0뿐, devComm 단어 오류 줄 0, 나쁜 간선 0>1, 1>0뿐 | B2–B4 맞음 |
| (b) 같음, gin-handoff | `pq4_fwslow@hf` | 5 | 감시가 오류를 드러내 rank 0이 rank 2의 라운드를 "the watchdog surfaced a fault earlier"로 거절, 복구 0, 간선 0>2, 0>3, 2>0, 3>0 중 3개 실패. 5/5 | B5 맞음 |

(c) 거절한 rank의 FAIL 답(시작 쪽의 거절 시각은 같은 rank의 끊김 끝부터) `[측정]`

| 형태 | 셀 키 | n | 일어난 일 | 끊김 끝 뒤 거절 | 예측 |
|---|---|--:|---|---|---|
| 다시 걸기(낮은 rank가 시작), 이 실험 | `pq_ackrace_f1_b@hq` | 10 | rank 1이 FAIL로 답 10/10, rank 0 "the peer declined this pair (FAIL on reconnect)" | 234–437 ms(중앙값 370) | C1 맞음 |
| 같음, gin-handoff | `pq_ackrace_f1_b@hf` | 5 | rank 1이 다시 걸기 16번을 닫고 rank 0은 재연결 한도(취소에서 10 s)를 다 씀, "peer liveness unknown" | 8 254–8 458 ms(중앙값 8 317) | C2 맞음 |
| 확인 접속(높은 rank가 시작), 이 실험 | `pq_ackrace_f1r1_b@hq` | 5 | rank 0이 FAIL로 답 5/5, rank 1 같은 사유 | 227–276 ms(중앙값 259) | C3 맞음 |
| 같음, gin-handoff | `pq_ackrace_f1r1_b@hf` | 5 | rank 0이 확인 접속에 답만 하고 다시 걸지 않음, "peer liveness unknown" | 8 231–8 285 ms(중앙값 8 246) | C4 맞음 |

- 셀 조건은 25회 모두 섰다: 라운드 5.22–5.45 s 뒤 ACK 기다림 중 취소, 응답 쪽은 커밋 뒤 거절, 응답 쪽은 거절 12.04–12.08 s 뒤 정리
  (`GIN_TS_END_WAIT_S=12`). `hq` 경합 시행 15회에서 두 rank의 원인은 모두 unknown이었다.
- 낮은 지적 셋(오래된 거부 잊기, 재실행을 상한에 세지 않기, 취소 계수)은 본 실행 로그에 "refusal ... forgotten" 줄과 상한 넘김 줄이 하나도 없어
  측정되지 않았다 `[미확인: 측정]`.

**4. 원인을 보는 shrink 넘김** `[측정]`

| 조건 | 셀 키 | n | 결과 | 예측 |
|---|---|--:|---|---|
| 랭크 2개, 원인 rank 0(복사 상한 초과), 이 실험 | `pq_copystall_shrink_b@hq` | 10 | 원인 rank 0 local, rank 1 peer-reported. rank 0의 shrink는 유지 줄 "(local)"과 순정 답(`ncclRemoteError`, 0.0 ms), 아이 없음. 10/10 | H1 맞음 |
| 같음, gin-handoff | `pq_copystall_shrink_b@hf` | 5 | 넘어감 17.0–17.3 ms, 1-rank communicator의 allreduce 맞음. 5/5 | H2 맞음 |
| 랭크 2개, 원인 rank 1 | `pq_copystall1_shrink_b@hq` | 5 | 원인 rank 0 peer-reported, rank 1 local. 넘어감 16.9–17.8 ms, allreduce 맞음. 5/5 | H3 맞음 |
| 랭크 2개, 상대 죽음(회귀) | `hd_shrink_b@hq` | 5 | 원인 peer-dead, kill 뒤 거절 1.31–1.36 ms, 넘어감 16.9–18.0 ms, allreduce 맞음. 5/5 | H4 맞음 |
| 랭크 4개, rank 3 kill | `pq4_kill3_shrink@hq` | 10 | 생존 셋 모두 넘어감(shrink 10.0–1 297.6 ms, n=30). 3-rank 아이가 GIN 문맥 6개의 devComm을 158.4–169.7 ms에 열고(n=30) 간선 6개 200회 정상. 10/10 | H5 맞음 |
| 랭크 4개, 원인 rank 0 | `pq4_local_shrink@hq` | 5 | rank 0의 shrink 실패(0.1 ms, 유지 "(local)"), 아이 없음. rank 2, 3은 아이 생성에서 rank 0을 기다리다 12 s 단계 한도로 끝남(종료 코드 8). 5/5 | H6, H7 맞음 |
| 같음, gin-handoff | `pq4_local_shrink@hf` | 5 | rank 0이 넘어가고 세 rank 모두 3-rank 아이를 얻음. 5/5 | H8 맞음 |

**회귀** `[측정]`(n=5씩)
- 투명 5/5: `f1_b`, `f3_b`, `bidirf_sym_b`, `mr4_none`, `mr4_f1_01`(R1, R6). 통계 API: `f1_b`에서 두 rank가 라운드 1, 복구 1, 거절 0(R7).
- kill: `f4_b` kill 뒤 거절 1.58–1.70 ms, 원인 peer-dead, devComm 단어 why peer-dead(R2). 운영 빌드 `hdp_kill_b@hqp` 1.43–1.68 ms, 죽음 1, WARN에 시작
  줄과 정보성 줄 없음(R5).
- 받기만 하는 rank(`hd_rxdeath_b`): kill 뒤 대기 해제 19.9–20.7 ms, 비동기 오류 1.8–2.1 ms(R3).
- 원격 접근 오류(`f2rel_b`): rank 0 거절, rank 1 device_error, 신호 없이 성공한 대기 0, rank 1 abort 723.0–747.1 ms(R4).

**지연**(rank 0 p50, 실행마다 3000번) `[측정]`

| 크기 | 이 실험 운영 빌드 | gin-handoff 운영 빌드 | 차이(실행 5의 중앙값) | 예측 |
|---|---|---|--:|---|
| 4 KiB | 10.75 µs(5/5 실행) | 10.69 µs(5/5) | +0.06 µs | P1 맞음(0.40 이하) |
| 256 KiB | 38.88–38.91 µs(중앙값 38.88) | 38.88–38.91 µs(중앙값 38.91) | −0.03 µs | P2 맞음(0.30 이하) |

p50은 원시 지연에서 다시 계산해도 kv와 같다(재계산, 20/20).

## 16. QA와 재현성

- **채점.** 메인 세션이 `score.py`로 셈: 시행 203, 판정 203, 예측 37 맞음 `[측정]`.
- **독립 재계산.** 다른 에이전트가 `score.py`, `rows_pq.py`, `SCORE.md`, `trials_*.csv`, 앞 실험의 열 추출기를 읽지 않고 원시 로그와 kv에서 모든
  열을 다시 뽑고, 자기 판정식 평가기로 셌다([qa/recount.py](qa/recount.py), [qa_recount.md](results/20261009/qa_recount.md)).
  - 맞은 것: 판정 37/37, 제외 0, 설정 확인 0건, hold 출력 203줄과 시행 파일, SIGKILL 줄 50개와 `kill.out` 50개, 멈춤 기준(STOP 없음, 139 없음, 명령
    오류와 펌웨어 실패 수 그대로, iptables 규칙 0), 지연 p50(원시 3000개에서 다시 계산). 각 새 규칙과 대조 규칙의 조건을 같은 이름의 다른 빌드
    셀에 대면 19쌍 모두 0건이라 규칙이 비어 있지 않다.
  - 무결성: 태그 `prereg/gin-peer-v1`이 커밋 `551c796f`, `predictions.csv` sha256이 작업 트리, 태그, `PREREG.txt` 세 곳에서 같음, 고정 절과
    `cells.sh`, `chain.sh`, `portpick.sh`, 드라이버 소스가 태그와 같음(실행기 셋은 관리망 주소 필터가 넣는 한 줄만 다름). 본 실행의 첫 로그 09:01:36은
    사전 등록 09:00:54 뒤.
  - 다른 것: 13절에 옮긴 넷. 판정을 바꾸는 것은 없다.
  - 한계: `rows.py` 계열을 읽지 않아 그 열은 드라이버와 문서에서 다시 정의했다. 규칙이 쓰는 값은 모두 경계에서 멀다. 예외는 랭크 2개 감시 시각(13절)이다.
- **코드 리뷰.** 설계 단계 리뷰(12절)와 본 실행 뒤 리뷰([qa/code_review.md](qa/code_review.md)). 본 실행 뒤 리뷰는 스크래치 트리가 `hq_layer.diff`와
  같고 드라이버 소스와 바이너리 md5가 5절과 같음을 확인했다(노드의 바이너리는 `deploy_check.txt`만). 찾은 것과 처리는 13, 17, 18, 19절.
- **내 확인.** 채점기 출력과 원시 kv, 로그에서 핵심 수치를 따로 세어 재계산과 같음을 확인했다(12절). 이것은 독립 확인이 아니다.
- **재현.** [gin_transparent_hq.diff](gin_transparent_hq.diff)(pristine NCCL v2.32.3-1 기준)로 만든다. `hqp`는 같은 소스에
  `-DNCCL_GIN_TS_PRODUCTION`. 빌드 절차는 [build_hq.sh](build_hq.sh), 배포는 [deploy_hq.sh](deploy_hq.sh)(md5 확인), 실행은 9절. 빌드 md5는 5절.

## 17. 결론

1. **랑데부 포트 문제가 없어졌다.** 포트를 임시 포트 범위 밖(29000–30999)에서, 두 노드 모두에서 어떤 TCP 소켓도 쓰지 않는 것만 고르고, rank가
   rank 0의 인사(고유값 포함)를 확인하기 전에는 아무것도 보내지 않게 했다. 본 실행 203회에서 bind 실패가 없었고(앞 세 실험 500회 중 7회), 막아 둔
   후보는 8/8 건너뛰었으며, 가짜 수신 대기는 8회 모두 0바이트를 받았다 `[측정]`. 다만 앞의 실패율로도 203회 무실패는 약 6% 확률로 나올 수 있어,
   주장은 수치보다 메커니즘(커널이 이 범위를 나가는 연결에 주지 않음)에 기댄다(리뷰 L3). 가짜 수신 대기는 틀린 magic만 시험했다(리뷰 L7).
2. **한 상대의 거절이 그 상대에 걸린 장치 대기만 푼다.** 랭크 4개에서 rank 3을 kill해도 살아남은 세 rank 사이 간선 6개가 10회 모두 끝까지 정상이었다
   (gin-handoff는 0/6, 받기 6개 실패). 생존 rank는 rank 3만 죽음으로 거절했고 rank 3의 단어만 올렸다 `[측정]`. 랭크 2개는 앞 빌드와 같다(첫 거절이 곧
   모든 상대).
   - **대가(리뷰 M1).** 상대를 지정하지 않는 대기(`waitSignal`, `waitCounter`, 배리어)는 랭크 3개 이상에서 한 상대가 죽어도 풀리지 않는다. 이
     실험은 그 대기를 10 s 장치 시간 제한으로만 쟀다(rank 3에서 받기가 한도로 끝남 10/10, 5/5). 시간 제한이 없으면 응용이 abort나 shrink를 부를
     때까지 돈다. gin-handoff에서는 바로 오류로 풀렸다. 스트림 동기화에 막힌 호스트 스레드는 비동기 오류를 볼 수 없으므로, 응용을 고치지 않는다는
     목표에서는 랭크 3개 이상의 멈춤이 될 수 있다 `[소스, 추론]`. 그래서 생존 결과는 "상대별 보내기와 flush가 계속 된다"는 뜻이지, "응용이 끝까지
     간다"는 뜻이 아니다. 상대를 모르는 대기에 시간 제한을 두는 응용에서만 그렇다.
   - blocking `wait()`와 `flush()`의 결과는 문맥마다 하나라, 죽은 상대와 같은 문맥에서는 여전히 실패한다. 문맥 전체 flush에서 생존 보내기 6개가
     모두 실패했다(5/5) `[측정]`.
3. **gin-harden 리뷰의 세 지적이 고쳐졌다.**
   - 다시 보내기 계획을 두 rank가 자기 커밋 전에 검사하자, 응답 쪽이 거부할 때 아무도 다시 보내지 않았다(10/10. gin-handoff는 rank 0이 다시 보낸 뒤
     거절 5/5) `[측정]`.
   - 펌웨어 감시를 라운드와 상대 단위로 하자, 랭크 4개에서 한 라운드의 초과는 그 상대만 거절했고 뒤의 다른 상대 라운드는 복구됐다(10/10.
     gin-handoff는 다음 라운드를 거절 5/5) `[측정]`. 초과는 시험 스위치의 잠으로 만들었고, 돌아오지 않는 명령은 재지 않았다(리뷰 N6).
   - 거절한 rank가 다시 걸기와 확인 접속에 FAIL로 답하자, 취소된 라운드를 다시 시도하던 rank가 끊김 끝 227–437 ms 안에 거절했다(15/15.
     gin-handoff는 재연결 한도를 다 써 8.2–8.5 s) `[측정]`. 거절한 rank가 살아 있을 때의 결과다(경합 셀은 응답 쪽을 12 s 머물게 했다, 리뷰 L4). 그
     경합 뒤에는 두 rank의 원인이 모두 unknown이라 어느 쪽의 shrink도 넘어가지 않는다(보수적).
   - 낮은 지적 셋은 본 실행에서 한 번도 일어나지 않아 소스로만 확인했다 `[미확인: 측정]`.
4. **shrink 넘김이 원인을 본다.** 원인이 자기 rank에 있는 거절 뒤에는 그 상대를 빼는 중단 shrink가 순정 답을 지켰고(랭크 2개 10/10, 랭크 4개
   5/5. gin-handoff는 넘어감 5/5, 5/5), 원인이 상대 쪽이면(상대가 알린 local, 죽음) 넘어갔다(5/5, 5/5, 랭크 4개 생존 rank 30/30) `[측정]`. 넘어간 3-rank
   아이는 자기 devComm(GIN 문맥 6개)을 열고 간선 6개로 통신했다(10/10). gin-handoff 리뷰가 남긴 두 미확인(원인, 아이 devComm)이 풀렸다.
   - 판정은 rank마다다. 원인이 local인 rank 0이 순정 답을 지키는 동안 자기 확인을 통과한 rank 2, 3은 아이 생성에서 12 s 한도까지 기다렸다(5/5)
     `[측정]`. rank 사이에 판정을 맞추는 일은 남았다.
   - shrink 순간 다른 rank의 라운드가 "이미 풀림"으로 local 거절되어 넘김을 막는 좁은 경합이 소스에 있다(리뷰 L1, 본 실행에서 0회) `[소스]`.
5. **기존 동작과 지연은 그대로다.** 회귀 예측 10개가 모두 맞았고(시행 60), 운영 빌드의 지연은 gin-handoff 운영 빌드와 4 KiB에서 +0.06 µs, 256 KiB에서
   −0.03 µs 달랐다 `[측정]`. 이 지연 비교는 라이브러리와 드라이버의 장치 코드를 함께 바꾼 비교다(13절).

## 18. 한계

- **상대를 지정하지 않는 대기(리뷰 M1).** 랭크 3개 이상에서 한 상대가 죽어도 `waitSignal`, `waitCounter`, 배리어, void 판은 풀리지 않는다.
  10 s 장치 시간 제한이 있는 형태로만 쟀다. 시간 제한 없는 대기는 응용이 abort할 때까지 돌고, 앞 빌드에서는 바로 풀렸다.
- **포트(리뷰 L3, L7).** 포트를 확인한 뒤 bind할 때까지 약 1 s 동안 아무것도 잡아 두지 않고, 로컬 `ss`가 실패하면 빈 포트로 읽는다. 203회 무실패는
  앞 비율로도 약 6% 확률로 나온다. 가짜 수신 대기는 틀린 magic만 시험했다. 같은 magic에 다른 고유값을 쓰는 옛 rank 0(현실의 충돌)은 재지 않았고,
  `rdv_decoy=rejected`는 시간 초과에도 찍힌다.
- **FAIL 답(리뷰 L4).** 거절한 rank가 살아 있을 때의 결과다. 경합 셀은 응답 쪽을 12 s 머물게 한 하네스 스위치로 그 조건을 만들었다. 그 경합 뒤에는
  두 rank의 원인이 모두 unknown이라 shrink가 넘어가지 않는다.
- **펌웨어 감시.** 초과는 commit 단계 안의 잠(시험 스위치)이다. 실제로 느리거나 돌아오지 않는 펌웨어 명령은 재지 않았다(리뷰 N6). 랭크 2개 감시 시각은
  판정 경계에 붙어 있다(13절).
- **shrink.** 판정이 rank마다라 엇갈릴 수 있다(H7가 잰 한계). shrink 순간의 경합(리뷰 L1)은 소스로만 안다.
- **문맥과 devComm.** blocking `wait()`와 `flush()`의 오류는 문맥마다 하나다(설계 단계 리뷰 M3). 한 communicator에 devComm이 둘이면 상대별 단어를
  함께 쓴다(설계 단계 리뷰 L3). 장치가 단어 배열을 읽는 길이 늘었다(리뷰 L5, 해제 시점은 그대로).
- **측정되지 않은 것.** 낮은 지적 셋(오래된 거부 잊기, 재실행 세기, 취소 계수)은 한 번도 일어나지 않았다(리뷰 N5).
- **장비와 장애.** 노드 한 쌍, 랭크 4개는 GPU 둘을 프로세스 둘씩 나눠 썼다. 장애는 소프트웨어로 주입했고 관리망 끊김은 helper 소켓 필터로만 만들었다.
- **채점과 실행기.** 8절 규칙 넷은 자동이 아니다(해당 없음, 리뷰 L2). 운영 빌드의 설정 확인은 `hqp`와 `hfp`를 가르지 못한다(리뷰 N1, 메타의 번들
  경로로는 갈림). ssh에 연결 시간 제한이 없다(리뷰 L8). 랭크 4개 실행기는 남은 프로세스를 이름으로 센다(읽기만, 리뷰 N2).
- **빌드.** 연구용 패치다. 연구 빌드에는 시험 스위치가 있다.

## 19. 다음 작업

- **상대를 지정하지 않는 대기(리뷰 M1).** 랭크 3개 이상에서 한 상대가 죽었을 때 그런 대기를 어떻게 끝낼지 정한다. 후보: 상대 하나의 죽음이 확인되면
  일정 시간 뒤 devComm 단어도 올리기, 대기에 기다리는 상대를 알리는 API, 응용 쪽 시간 제한 안내. 시간 제한 없는 `waitSignal`로 랭크 4개 kill을 잰다.
- **shrink 순간의 경합(리뷰 L1).** 준비 확인을 단어를 올리기 전에 찍거나, shrink 자신의 올림은 "이미 풀림" 검사에서 뺀다.
- **rank 사이 shrink 판정 맞추기.** 원인이 local인 rank가 있으면 다른 rank도 같은 답을 내게 한다(H7의 12 s 대기 없애기).
- **포트(리뷰 L3, L7, L8).** 드라이버 안의 bind 재시도나 미리 bind한 소켓 넘기기, 같은 magic에 다른 고유값을 쓰는 가짜 수신 대기, ssh 연결 시간 제한.
- **채점기(리뷰 L2, N1).** 8절 규칙 넷과 운영 빌드 구분을 넣는다.
- **측정되지 않은 것.** 낮은 지적 셋을 실제로 일으키는 셀, 실제로 느리거나 돌아오지 않는 펌웨어 명령.
- **소스 정리(리뷰 L9).** NACK 1, 12에도 고유값을 싣고, 상한 넘김 주석을 고친다.

## 20. 참고자료

- `../harden/EXPERIMENT.md` 9절 1번 (g)(독립 리뷰의 중간, 낮은 지적), 19절
- `../handoff/qa/code_review.md` M1, M2, L1(원인과 아이 devComm, 포트)
- `../multirank/EXPERIMENT.md` 15, 18, 19절(랭크 4개 kill의 결과, 포트, 거절 범위)
- `../s2_close/EXPERIMENT.md` 3.2절(판정식 문법)
- [qa/code_review.md](qa/code_review.md), [results/20261009/qa_recount.md](results/20261009/qa_recount.md)(이 실험의 QA)
