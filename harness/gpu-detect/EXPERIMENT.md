# GPU 주도 라이브러리의 장애 감지를 application 호출 밖으로 (gpu-detect)

**목적:** blind-apps가 찾은 결함(GPU 주도 두 라이브러리가 application이 부르는 호출 안에서만 장애를 감지한다)을 라이브러리 계층 둘로 고치고,
수정하지 않은 두 공식 예제에서 고친 동작, 거짓 양성, 비용, 회귀를 사전 등록한 예측으로 잰다.

| 항목 | 값 |
|---|---|
| 상태 | `COMPLETE` |
| 담당자 | @unionxic |
| 작성일 | 2026-10-09 |
| 기준 브랜치와 커밋 | `exp/gpu-detect` @ `02a640aa` (master) |
| 사전 등록 태그 | `prereg/gpu-detect-v1`: 상태를 `PREREGISTERED`로 바꾼 커밋(12절)에 단다. 고정 파일의 sha256은 [PREREG.txt](PREREG.txt) |
| 마지막 갱신 | 2026-10-09, 본 실행, 채점, QA, 마감(12절) |

표시: `[측정]` 원자료나 빌드 산출물에서 확인, `[소스]` 코드에서 읽음, `[추론]` 해석, `[미확인]` 확인 안 함.

이 문서의 코드는 함수 이름으로 가리킨다. GIN 쪽 파일은 따로 적지 않으면 `src/transport/net_ib/gdaki/gin_host_gdaki.cc`(빌드 트리는 세션
스크래치 `agent_gd/gin/nccl-src`), NVSHMEM 쪽은 `src/modules/transport/ibgda/ibgda.cpp`(트리 `agent_gd/nvs/src`)다. GIN 용어(helper, 라운드,
거절, 죽음, 사용자 devComm abort 단어, 상대별 단어, degraded, NIC 복사 경로)는 [../gpu-initiated/gin_recovery/remaining/EXPERIMENT.md](../gpu-initiated/gin_recovery/remaining/EXPERIMENT.md)
머리말과 같다. 이 실험에서 더 쓰는 말:
- QP 상태 감시(watch): GIN helper가 라운드 밖에서 주기마다 자기 GIN QP의 상태를 펌웨어 명령(QUERY_QP)으로 읽는 것(9.1절 (a)).
- 감지 지연: GIN 훅이 QP를 ERR로 옮긴 시각(훅 줄의 `done_mono_ms`)에서 대상 rank가 장애를 알아챈 줄(감시 줄, 또는 장치가 분류한 오류 CQE 줄)까지.
  같은 프로세스의 시계다.
- 작별(goodbye): NVSHMEM의 라이브러리 소켓으로 정리 중인 PE가 소켓을 닫기 전에 보내는 메시지(`T1_M_BYE`, 9.2절 (a)).
- FIN 판정: 작별 없이 라이브러리 소켓이 FIN으로 닫히면 그 상대를 죽음으로 보고 거절하는 규칙(9.2절 (a)).
- fail-stop: 거절 직후 라이브러리가 프로세스를 종료 코드 70으로 끝내는 정책(9.2절 (b), 기본).
- release: fail-stop 대신 장치 대기 단어를 올려 application이 부르는 장치 대기를 풀어 주는 정책(9.2절 (c), `NVSHMEM_IBGDA_FT_T1_FAILSTOP_MS=-1`).

예측 id, 셀 이름, 빌드 키는 원자료를 찾는 키로만 괄호나 표의 열에 둔다.

| 빌드 키 | 내용 | 쓰는 곳 |
|---|---|---|
| `hk` | 이 실험의 GIN 연구 빌드: `hw` 위에 정책 hook, 응답 쪽 틈의 고침, 시험 스위치 하나, 정리 줄(9.1절 (f)–(h), 같은 파일 하나) | 새 셀, 회귀, 지연(pilot 2부터) |
| `hkp` | `hk`와 같은 소스의 운영 빌드(`-DNCCL_GIN_TS_PRODUCTION`). 빌드만 하고 배포하지 않는다 | 컴파일 확인 |
| `hw` | 첫 GIN 계층: gin-remaining `hr` 위에 9.1절 (a)–(e)(파일 하나, 호스트 코드만). pilot 1의 빌드. 배포된 번들은 읽기만 | 응답 쪽 틈의 대조 |
| `hwp` | `hw`의 운영 빌드. 빌드만 함 | 컴파일 확인(지난 것) |
| `hr`, `hq` | gin-remaining, gin-peer의 연구 빌드(배포된 번들, 읽기만) | 대조 |
| `t1w` | 이 실험의 NVSHMEM 빌드: t1_380 위에 9.2절의 계층(파일 셋) | 새 셀 |
| `t1_380` | blind-apps가 쓴 NVSHMEM 투명 복구 빌드(배포된 번들, 읽기만) | 대조 |

## 1. 배경과 연구 질문

**blind-apps가 찾은 것.** blind-apps는 수정하지 않은 공식 예제 둘을 이 저장소의 GIN 투명 복구 빌드(`hq`)와 NVSHMEM 투명 복구 빌드(t1_380)로 돌렸다.
아래 수는 그 실험의 Release 자산(`harness__blind__results__20261009.tar.xz`, `DATA.md`)을 세션 스크래치에 풀어 이 실험의 파서(`rows_gd.py`의 정규식)로
원자료에서 다시 셌다 `[측정, n은 각 줄]`.
- GIN 예제 `09_gin_optimizations/01_ring_exchange`, 대상 rank의 GIN QP를 모두 ERR로 옮기는 훅(GDAKI 문맥 생성 뒤 8–115 ms): 16회 중 14회가
  두 rank 모두 훅 뒤 한 줄도 남기지 않고 시간 상한까지 멈췄다. 투명한 2회는 훅이 가장 늦은 두 시행(114, 115 ms)이다.
- NVSHMEM 예제 `ring-reduce`, PE 하나 SIGKILL: 유효 7회 모두 살아남은 PE가 멈췄다(1회는 장애 전에 끝나 제외). 살아남은 PE의 라이브러리 소켓은 kill
  응답 0.03–0.48 ms 뒤 FIN을 보았고(7회), DECLINE 줄은 0줄이다.
- 같은 예제, 원격 접근 권한 회수: 8회 모두 두 PE가 훅 뒤 4.9–7.6 ms에 거절(DECLINE)했는데도 8회 모두 시간 상한까지 멈췄다.

**원인** `[소스, blind-apps qa/root_cause.md 2, 3에서 읽고 이 실험의 트리에서 다시 확인]`.
- GIN: 예제 커널은 배치마다 put을 낸 뒤 `waitSignal`로 상대의 신호를 기다리고, 그다음에야 `flush`로 CQ를 읽는다. `waitSignal`(`gin__funcs.h`
  `waitRollingLessEq`)과 GIN 배리어는 신호 단어와 abort 단어만 읽는다. 오류 CQE를 분류해 helper에게 넘기는 것은 `flush`와 요청 대기(`tsPoll`)뿐이다.
  두 rank가 모두 신호를 기다리면 아무도 CQ를 읽지 않는다. 호스트 쪽에서 QP 상태를 읽는 코드(`gdakiQ4Watch`의 QPWATCH)는 진단용이고 기본이 꺼져 있다
  (`NCCL_GIN_Q4_QPWATCH_MS=0`).
- NVSHMEM: helper 루프는 FIN을 보면 로그 한 줄만 남긴다. 죽음 판정은 장치가 폴링한 오류 CQE의 기록(`t1_fault`)에서만 나온다. 살아남은 PE는 보낼
  것이 없어 오류 CQE도 없다. 거절을 해도 `nvshmem_signal_wait_until`과 배리어의 대기는 그냥 도는 루프(`nvshmemi_wait_until*`)라 풀리지 않는다.

**비어 있는 것.** 두 라이브러리 모두 application이 CQ를 읽는 호출을 부르지 않는 동안 생긴 장애를 감지할 길이 없고, NVSHMEM은 감지해도 application에
전할 길이 없다. 어떤 감지가 얼마나 빨리, 얼마의 비용으로, 거짓 양성 없이 되는지 잰 적이 없다.

**함께 고치는 것.** gin-remaining의 리뷰가 남긴 세 항목(`../gpu-initiated/gin_recovery/remaining/EXPERIMENT.md` 9.1절 (f), `qa/code_review.md`)을
같은 GIN 계층에서 다룬다(메인 세션 지시, 2026-10-09).
- 중간 M-A: 기다림 안 응답(`gdakiTsServeLower`)이 한 번 훑을 때 중첩 가능 여부를 한 번만 보고 중첩 라운드 뒤에도 다음 상대로 넘어간다. 낮은 rank의
  REQ 둘이 함께 오면 둘째 중첩이 바깥 라운드를 라운드 한도 너머로 밀 수 있다.
- 낮음 L-C: NIC 복사 경로의 자체 시험이 스트림 복사로 확인한다. application이 CUDA 스트림을 붙잡은 채 devComm을 만들면 그 복사가 시간을 넘겨 NIC 경로가
  꺼지고 `copyStuck`이 남는다.
- 중간 M-C: 앞 헤더로 빌드한 장치 코드는 상대별 대기에서도 칸 0을 읽는데 호스트는 그것을 알 수 없다. 상대 단어가 들어간 뒤 게시 전 확인은 칸 0을
  보지 않는다.

**정책 hook과 응답 쪽 틈**(사용자 승인 2026-10-09, 12절). 병렬 실험 gin-restore의 통합 정책 설계(`DESIGN_POLICY.md`)는 이 실험의 fail-fast 반응을
communicator마다 고르는 정책의 기본값으로 두고, 복원 계층이 채울 hook 아홉을 이 GIN 계층에 넣게 했다. 같은 설계가 `hw`의 틈 하나를 찾았다: 응답 쪽이
Commit한 뒤 시작 쪽을 잃으면 죽음 판정 없이 거절하므로 degraded가 예약되지 않는다. 둘 다 빌드 `hk`에 넣었다(9.1절 (f)–(h)). pilot 1은 `hw`로 돌았고,
pilot 2와 본 실행은 `hk`로 돈다.

**질문.**
1. GIN helper가 라운드 밖에서 QP 상태를 주기적으로 읽고 ERR인 QP에 장애 기록을 만들어 넣으면, 수정하지 않은 GIN 예제의 QP 오류가 무작위 시각에서도
   투명하게 복구되는가. 감지 지연은 주기에 따라 어떻게 달라지고, 장애 없는 지연(latency)에 얼마의 비용이 드는가.
2. NVSHMEM이 작별 없는 FIN을 죽음으로 판정하고 거절 뒤 프로세스를 끝내면(fail-stop), 상대가 죽은 PE와 원격 접근이 회수된 PE가 멈추지 않고 정해 둔
   시간 안에 오류로 끝나는가. release 정책에서는 장치 대기가 실제로 풀리는가.
3. 두 계층이 거짓 양성을 만들지 않는가: 멈춘(SIGSTOP) 상대를 죽음으로 보지 않고, 장애 없는 실행과 정상 종료의 FIN을 장애로 보지 않는가.
4. 기존 GIN 셀(랭크 2개와 4개)의 판정이 그대로인가. M-A, L-C, M-C 수정이 설계대로 동작하는가.
5. 정책 hook은 fail-fast에서 동작을 바꾸지 않는가(hold를 요청해도, rank마다 정책이 달라도). 응답 쪽이 Commit한 뒤 시작 쪽이 죽으면 `hw`에서는 그 응답
   쪽의 상대를 모르는 대기가 풀리지 않고, `hk`에서는 다른 생존 rank처럼 판정 뒤 약 2 s에 풀리는가.

## 2. 가설

| id | 가설 | 다음이 관측되면 틀린 것이다 |
|---|---|---|
| H1 | GIN QP 오류를 놓친 것은 감지가 application 호출 안에만 있기 때문이다. 호스트의 QP 상태 감시가 감지를 맡으면 라운드 자체는 어느 rank의 장치 스레드도 필요 없으므로 투명하게 복구된다 | `hk`(pilot 1까지는 `hw`)의 GIN 예제 QP 오류 셀에서 투명하지 않은 시행이 2회 이상이다. 또는 감시를 끈 같은 빌드에서 훅 뒤 100 ms 안에 어느 rank가 감지하거나 1 000 ms 안에 복구한 시행이 2회 이상이다. 감시 없이도 CQ를 읽는 호출이 상대의 RETRY_EXC(훅 뒤 약 3.6 s)를 읽으면 늦게 복구될 수 있고(blind-apps 16회 중 2, pilot 2의 감시 끔 1회), 이것은 H1이 말하는 호출 안의 감지라 반례가 아니다 |
| H2 | 감지 지연은 감시 주기의 절반 남짓과 유예(5 ms)로 정해지고, 주기 10 ms의 감시는 장애 없는 지연을 재는 정밀도(4 KiB 0.40 µs, 256 KiB 0.30 µs) 안에서 바꾸지 않는다 | 감지 지연의 중앙값이 주기 순서를 따르지 않는다. 또는 10 ms 감시의 지연 차이가 그 정밀도를 넘는다 |
| H3 | NVSHMEM kill 뒤의 멈춤은 FIN을 판정에 쓰지 않은 것과 거절이 장치 대기에 닿지 않는 것 때문이다. FIN 판정과 fail-stop을 더하면 살아남은 PE는 1 s 안에 종료 코드 70으로 끝나고, 원격 접근 회수는 두 PE가 2 s 안에 끝난다 | 그 셀에서 멈추거나 시간을 넘긴 시행이 2회 이상이다 |
| H4 | release 정책에서 장치 대기 단어는 application이 부르는 장치 대기를 풀어 프로세스가 스스로 끝나게 한다 | release 셀에서 하네스가 끝낸 시행이 2회 이상이다 |
| H5 | 두 계층은 거짓 양성을 만들지 않는다. 멈춘 프로세스의 NIC과 커널은 응답하므로 QP는 RTS이고 FIN도 없다. 정상 종료는 작별을 먼저 보낸다 | 멈춤 셀이나 장애 없는 셀에서 감시 감지, 거절, 죽음 판정이 있는 시행이 허용(1회, 장애 없는 GIN은 0회)을 넘는다 |
| H6 | 두 계층은 기존 동작을 바꾸지 않고(GIN 회귀 셀, NVSHMEM QP 오류 셀), 리뷰 세 항목의 수정은 설계대로 동작한다 | 회귀 셀이나 M-A, M-C, L-C 셀에서 예측과 다른 시행이 나온다 |
| H7 | 응답 쪽 Commit 뒤 죽음에서 그 응답 쪽의 대기가 풀리지 않는 것은 그 자리가 죽음 판정을 하지 않아 degraded가 예약되지 않기 때문이다. 그 자리에 idle 루프의 판정을 두면 그 응답 쪽도 다른 생존 rank처럼 자기 판정 뒤 2 000–3 000 ms에 풀린다 | `hk`의 응답 쪽 틈 셀(두 가지)에서 풀리지 않은 생존 rank가 있는 시행이 셀마다 2회 이상이다. 또는 `hw`의 대조 셀에서 응답 쪽이 풀리는 시행이 2회 이상이다 |
| H8 | 정책 hook과 정책 변수는 fail-fast에서 동작을 바꾸지 않는다: hold를 요청해도 rank마다 WARN 한 줄 뒤 fail-fast이고, rank마다 정책이 달라도 WARN 한 줄 뒤 fail-fast다 | hold 요청 셀이나 정책 불일치 셀에서 예측과 다른 시행이 나온다. 또는 `hk`로 옮긴 회귀 셀(H6)에서 예측과 다른 시행이 나온다 |

## 3. 사전 예측 (측정 전에 작성)

**고정 시점.** 예측 원문은 [predictions.csv](predictions.csv)(41줄)다. 사전 등록으로 고정했다(태그 `prereg/gpu-detect-v1`, sha256은 [PREREG.txt](PREREG.txt)).
- 메인 세션이 pilot(hold P1, P2, 9.6절)을 돌린 뒤 예측을 확정한다. pilot 시행은 채점하지 않고, 결과 폴더(`results/<날짜>_pilot/`, pilot 2는
  `results/<날짜>_pilot2/`)도 따로 둔다. pilot 1(`hw`)을 점검한 뒤 계층 `hk`와 새 셀을 더했으므로 pilot 2가 바뀐 셀과 새 셀을 덮는다(7절).
- pilot에서 고칠 수 있는 것: 읽기 오류(열 정의, 정규식), 셀 조건(장애 시각 창, 셀이 조건을 만들지 못함), 실행기 결함, 구현 결함(다시 빌드, 새
  디렉터리로 배포). 고친 것은 12절에 적고 고친 셀은 태그 전에 pilot을 한 번 더 돈다. 그때 `schedule.json`(시행 목록)은 새 시드로 다시 만든다.
- pilot에서 예측과 다른 결과가 나오면 예측 문장과 판정식을 고칠 수 있는 것은 태그 전까지이고, 고친 줄과 이유를 12절에 남긴다. 태그 뒤에는 2, 3, 7, 8절과
  `predictions.csv`, `cells.json`, `schedule.json`을 고치지 않는다.
- 사전 등록 커밋은 상태 `PREREGISTERED`, 12절 기록, `PREREG.txt`(예측, 셀, 시행 목록, 실행기와 채점기, 두 계층 diff의 sha256)를 함께 담고, 그 커밋에
  `prereg/gpu-detect-v1`을 단다.

`kind`는 N(새 동작), C(대조, 비용), R(회귀), F(거짓 양성 확인)다.

### 3.1 판정에 쓰는 열

시행마다 한 줄이다.
- app 시행(두 예제, `raw/<id>/`): [rows_gd.py](rows_gd.py)가 만든다. 결과 규칙과 결과 검사는 blind-apps(`../blind/EXPERIMENT.md` 3.1절)와 같고, 정규식에
  이 실험의 줄을 더했다. 원문은 그 파일 머리말이다.
- 회귀 시행(`reg/<빌드>/`, `reg/mr_<빌드>/`; 빌드는 `hk`, 응답 쪽 틈의 대조만 `hw`): gin-remaining의 열 코드가 원래 정의 그대로 만들고(`../gpu-initiated/gin_recovery/remaining/score.py`를 라이브러리로
  불러 씀), `rows_gd.extra_gd2()`, `extra_gd4()`가 열을 더한다.

| 열 | 정의 |
|---|---|
| `outcome`, `result` | blind-apps의 규칙: 하네스가 끝낸 살아남은 rank가 있으면 HUNG, 결과가 틀리고 오류 줄 없이 모두 0이면 SILENT_WRONG, 오류 줄이나 0이 아닌 종료가 있으면 DECLINED, 모두 0이고 결과가 맞으면 TRANSPARENT. GIN은 rank 0의 PASSED와 mismatch 줄, NVSHMEM은 세 크기 줄과 검증 줄(에이전트가 센 것 포함) |
| `n_harness_end` | 하네스가 끝낸(유예나 시간 상한) 살아남은 rank의 수 |
| `dt_err`, `dt_end` | 장애 시각(훅 발화 줄, 신호 응답)에서 살아남은 rank의 첫 오류 줄까지, 마지막 살아남은 rank의 종료까지(s, rain 수신 시각) |
| `det1_s`, `det1_by`, `det_wcq_ms` | GIN QP 오류(태그 전에 더함): 두 rank 중 어디서든 처음 나온 감지 줄(감시 줄, 또는 장치가 분류한 오류 CQE 줄) − 훅 발화 줄(둘 다 rain 수신 시각, s)과 그 출처(`r<r>:watch`, `r<r>:device`). 감시가 먼저였고 분류가 뿌리 CQE에서 왔을 때의 `det_ms`(그 밖은 빈 칸): 뿌리 CQE가 없는 창의 50 ms 기다림을 뺀 감시 자체의 지연 |
| `det_by`, `det_ms`, `det_src` | GIN QP 오류: 대상 rank에서 먼저 나온 감지 줄(`watch`: 감시 줄, `device`: 장치가 분류한 오류 CQE 줄, `none`)과, 그 줄의 `mono_ms` − 훅 줄의 `done_mono_ms`(대상 rank의 시계, ms). 감시 줄이면 그 분류가 어디서 왔는지(`cq`, `slot-wait`, `none`, `unread`) |
| `rec_ms`, `rec_rx_s` | 대상 rank의 첫 복구 줄 `t_resumed` − `done_mono_ms`(ms); 첫 복구 줄 수신 − 훅 줄 수신(s) |
| `n_watch`, `n_q4`, `n_decl`, `n_judged`, `n_rec`, `n_death` | 감시 감지 줄, 장치 분류 줄, GIN 거절 줄, 죽음 판정 줄, 복구 줄, 살아남은 rank의 죽음 줄의 수 |
| `det_cfg`, `watch_cfg`, `lb_shadow` | `hw` 시작 줄(`GIN/TS: detect=1 ...`)이 있는 rank 수와 그 `qpwatch_ms`, NIC 경로 켬 줄의 "QP struct(s) equal to the host shadow" 수의 최솟값 |
| `wq_queries`, `wq_us_mean`, `wq_us_max` | 정리 때 감시 줄: QUERY_QP 수(두 rank 합), 평균과 최대 소요(µs, 큰 rank) |
| `t1w_cfg`, `failstop_cfg` | `t1w` 시작 줄(`t1w: gpu-detect=1 ...`)이 있는 PE 수와 그 `failstop_ms` |
| `n_fin_verdict`, `verdict_s`, `surv_rc` | 살아남은 PE의 FIN 판정 줄 수, 첫 판정 줄 − kill 응답(s, rain 수신 시각), 살아남은 PE의 종료 코드 |
| `n_bye_sent`, `n_bye_seen`, `n_left`, `n_failstop`, `n_released`, `n_declines` | 작별 보냄, 작별 받음, 작별 뒤 FIN, fail-stop 종료, 장치 대기 해제, DECLINE 줄의 수(두 PE 합) |
| `ms_16m`, `ms_32m`, `ms_64m`, `n_val` | PE 0이 찍은 크기별 반복당 ms, 검증 오류 줄의 수(남긴 줄 + 에이전트가 센 줄) |
| `det_on_r*`, `det_ms_cfg`, `n_watch2` (랭크 2개 회귀) | `hw` 시작 줄의 수와 `qpwatch_ms`, 감시 감지 줄의 수 |
| `n_det_on`, `n_watch4`, `served3`, `rec01`, `decl01` (랭크 4개 회귀) | `hw` 시작 줄의 수, 감시 감지 줄의 수, rank 3이 기다림 안에서 답한 REQ("3-P"), rank 0의 상대 1 복구 줄과 거절 줄의 수 |
| `pol_cfg`, `wq_lines` (app, `hk`) | `hk` 정책 줄(`GIN/TS: fault policy ... requested=failfast ... effective=failfast`)이 있는 rank 수, 정리 때 감시 줄의 수 |
| `pol_n`, `pol_req`, `pol_agreed_min`, `pol_eff_ff`, `n_hold_warn`, `hold_warn_ranks`, `n_mix_warn`, `mix_warn_ranks` (회귀, 랭크 2개와 4개) | 정책 줄이 있는 rank 수, rank마다 요청한 정책(`r<r>:<정책>`), 일치 표시의 최솟값, 모든 정책 줄이 `effective=failfast`이면 1, hold WARN("hold requested, not available in this build") 줄 수와 그 줄이 정확히 하나인 rank 수, 불일치 WARN("differs across ranks")의 같은 두 값 |
| `gap_x`, `gap_exit_line`, `gap_rc_x` (랭크 4개) | 죽는 rank X(meta의 `kill_rank`, 없으면 ACK 뒤 종료 시험 줄이 있는 rank), X의 "TEST exit after ACK" 줄 수, X의 종료 코드 |
| `gap_resp`, `gap_hit`, `gap_cause`, `gap_lac`, `gap_judged_r` | X를 "peer closed the socket before DONE"로 거절한 첫 생존 rank(응답 쪽, 없으면 창을 맞히지 못함), 그 여부, 그 rank의 "GIN error raised for rank X cause=" 값, 그 rank의 "lost after this rank's commit" 줄 수, 그 rank가 X를 죽음으로 판정했으면 1 |
| `gap_rel_r<s>`, `gap_relms_r<s>`, `gap_n_rel`, `gap_n_rel23`, `gap_kdone`, `gap_stuck`, `gap_resp_rel`, `gap_resp_stuck`, `gap_others_rel23` | 생존 rank s의 X에서 오는 시간 제한 없는 받기가 풀렸는지(kv `rx_<X><s>_rel`)와 풀린 시각 − s의 X 판정 시각(s의 시계, ms), 풀린 생존 rank 수, 그중 판정 뒤 2 000–3 000 ms에 풀린 수, 커널이 끝난 생존 rank 수, `async_error_kernel_stuck`인 생존 rank 수, 응답 쪽의 풀림과 멈춤, 응답 쪽을 뺀 2 000–3 000 ms 수 |
| 그 밖 | `transparent_ok`, `lat_p50_us`, `rec_i`, `decl`, `n_hs`, `served`, `rel_*` 등은 gin-remaining 3.1절의 정의 그대로 |

**새 로그 줄** `[소스, 9절의 변경으로 고정]`.

| 줄 | 수준(GIN 운영 빌드) | 형식 |
|---|---|---|
| GIN 시작 | 정보 | `GIN/TS: detect=1 rank=<r> qpwatch_ms=<P> grace_ms=<G> nocqe_ms=<N> nest_once=1 selftest=nic degraded_rounds=<0\|1>` |
| GIN 감시 감지 | 정보 | `GIN/TS: rank <r>: QP watch: qpn <q> (rank <p>, context <c>) is in state <ERR\|SQER> with no fault record for <x> ms; class <C> from <cq\|slot-wait\|none\|unread> (syndrome .. vendor .. err_cqes ..); fault queued (qpwatch_ms=<P> grace_ms=<G>) epoch=<e> mono_ms=<t>` |
| GIN 감시의 다른 상태 | 정보 | `GIN/TS: rank <r>: QP watch: qpn <q> (rank <p>, context <c>) is in state <RST\|INIT\|RTR\|SQD> outside a round; not acted on mono_ms=<t>`(QP마다 한 번) |
| GIN 감시, 쓰지 않은 QP | 정보 | `GIN/TS: rank <r>: QP watch: qpn <q> (rank <p>, context <c>) is in state <ERR\|SQER> and was never posted to; no record until its first post mono_ms=<t>`(QP마다 한 번) |
| GIN 정리 때 감시 | 정보 | `GIN/TS: rank <r> QP watch at teardown: qpwatch_ms=<P> queries=<n> query_fail=<f> query_us_mean=<a> query_us_max=<b> detections=<d> other_states=<o> idle_err=<i>` |
| GIN NIC 경로 켬 | 정보 | 앞 빌드의 줄에 `, <n> QP struct(s) equal to the host shadow, NIC only`가 더해짐 |
| NVSHMEM 시작 | stderr | `[nvshmem-t1] PE<p> <t> t1w: gpu-detect=1 fin_death=<0\|1> goodbye=1 failstop_ms=<ms> failstop_code=<c> wait_word=<on\|off>` |
| 작별 | stderr | `t1w: goodbye sent to <n> peer(s) before the library sockets close`(보냄), `t1w: peer <p> said goodbye (normal teardown): its FIN is not death`(받음), `t1w: peer <p> library socket closed (FIN) after its goodbye: it left` |
| FIN 판정 | stderr | `t1w: peer <p> library socket closed (FIN) without a goodbye: the peer process is gone`, 뒤에 앞 빌드의 `DECLINE peer=<p> ... reason="the peer's library socket closed (FIN) without a goodbye (peer process gone)"` |
| fail-stop | stderr | `t1w: FAILSTOP: exiting with code <c> after the decline of peer <p> (<이유>)`; 지연 종료면 먼저 `t1w: FAILSTOP armed: ...` |
| release | stderr | `t1w: device waits released: the decline of peer <p> reaches every application-facing device wait of this PE (released waits return without their data)` |
| GIN 정책(`hk`) | 정보 | `GIN/TS: fault policy rank=<r> requested=<failfast\|hold> agreed=<0\|1> effective=failfast restore_layer=0 after_commit_verdict=1` |
| GIN 정책 WARN(`hk`) | WARN | `GIN/TS: rank <r>: NCCL_GIN_FAULT_POLICY=hold requested, not available in this build (no restore layer); fail-fast`, 또는 `... NCCL_GIN_FAULT_POLICY differs across ranks (this rank <a>, rank <p> <b>); fail-fast`(rank마다 많아야 하나) |
| GIN 응답 쪽 Commit 뒤 손실(`hk`) | 정보 | `GIN/TS: rank <r>: socket to rank <p> lost after this rank's commit of round <k> (<무엇>, cause=<c>): judged as the idle loop judges it mono_ms=<t>`, 뒤에 idle 루프와 같은 판정 WARN 두 줄과 `declined ... reason="<무엇> after this rank's commit: peer judged dead"` |
| GIN 시험 스위치(`hk` 연구 빌드) | WARN | `GIN/TS: TEST exit after ACK rank=<r> peer=<p> round=<k>: the process ends (_exit 73) before its commit and DONE, without BYE mono_ms=<t>` |
| GIN 정리 때 감시(`hk`) | 정보 | 형식은 위와 같고, devComm을 먼저 지우는 application에서도 문맥마다 한 번 나온다 |

### 3.2 셀 키와 판정식 문법

셀 키는 `cell@build`다. 판정식 문법은 gin-remaining과 같다(`../gpu-initiated/gin_recovery/s2_close/EXPERIMENT.md` 3.2절, 그 `score.py`의 평가 함수를
그대로 씀). 더한 것은 하나다: `count()` 밖의 `N_SCORED`는 그 셀의 판정한 시행 수로 바뀐다. 셀마다 계획 수의 75%(올림)보다 판정한 시행이 적으면 그
예측은 "자료 부족"이다. 제외한 시행은 다시 채우지 않는다. 빈 칸은 어떤 비교도 거짓이고 산술은 실패한다.

### 3.3 예측 요약

계획 n은 7절, 전체 판정식은 [predictions.csv](predictions.csv)에 있다. "N"은 그 셀의 판정한 시행 수다.

| 무엇을 예측했나 | id | 셀 | 판정 기준(요약) | 근거 |
|---|---|---|---|---|
| GIN 예제 QP 오류(감시 10 ms): 복구 줄과 함께 투명 | GD1 | `gin_qperr@hk` | N − 1 이상 | 9.1절 (a) `[소스]`. blind-apps의 복구된 2회는 장치 스레드 없이 라운드가 끝났다 `[측정, n=2]` |
| 대상 rank가 훅 뒤 100 ms 안에 감지(감시나 장치) | GD2 | `gin_qperr@hk` | N − 1 이상 | 주기 + 유예 5 ms(뿌리 CQE가 있을 때)나 50 ms(없을 때) + QUERY_QP `[소스, 추론]` |
| 대상 rank의 라운드가 훅 뒤 1 000 ms 안에 재개 | GD3 | `gin_qperr@hk` | N − 1 이상 | 앞 실험의 랭크 2개 라운드 약 2 ms `[측정, 이전 실험]` |
| 주기 1 ms, 100 ms에서도 투명, 감지 70 ms, 200 ms 안 | GD4 | `gin_qperr_w1@hk`, `gin_qperr_w100@hk` | 셀마다 N − 1 이상 | `[소스, 추론]` |
| 뿌리 CQE로 분류한 감시 감지의 지연 중앙값이 주기 순서(1 < 10 < 100 ms) | GD5 | 셋 | 중앙값 비교 | 주기 안 위상이 고르다 `[추론]`. 뿌리 CQE가 없는 창은 주기와 상관없이 50 ms를 기다려 뺀다(리뷰 M2, 태그 전 고침) `[소스]` |
| 대조(`hr`, `hq`): 감시 없이는 빨리 감지하지 못함(어느 rank도 훅 뒤 100 ms 안에 감지하지 않고 1 000 ms 안에 복구하지 않음: 멈추거나 늦은 RETRY_EXC로 복구) | GC1 | `gin_qperr@hr`, `@hq` | 셀마다 N − 1 이상 | blind-apps 원자료 16/16(멈춤 14, 늦은 복구 2) `[측정]`, 태그 전 고침 |
| 대조(`hk`에서 감시 끔): GC1과 같은 조건, 감시 감지도 없음 | GC2 | `gin_qperr_w0@hk` | N − 1 이상 | 더한 빠른 감지는 감시뿐 `[소스]`. pilot 2 1회는 늦은 RETRY_EXC로 3.767 s에 복구 `[측정]`, 태그 전 고침 |
| GIN kill: 투명 아님, 5 s 안 오류, 감시 감지 없음 | GR1 | `gin_kill@hk` | N − 1 이상 | blind-apps 10/10 `[측정]` |
| GIN 1–8 s 멈춤: 투명, 죽음과 거절과 감시 감지 없음 | GF1 | `gin_stop@hk` | N − 1 이상 | 멈춘 프로세스의 NIC과 커널은 응답 `[추론]` |
| GIN 장애 없음: 투명, 감시 감지와 거절 없음 | GF2 | `gin_none@hk` | N 모두 | `[소스]` |
| NVSHMEM kill: FIN 판정 0.1 s 안, 살아남은 PE가 스스로 종료 코드 70으로 1 s 안 | ND1 | `nvs_kill@t1w` | N − 1 이상 | FIN 0.03–0.48 ms `[측정, blind-apps n=7]` |
| 원격 접근 회수: 두 PE가 거절하고 2 s 안에 종료 코드 70 | ND2 | `nvs_remacc@t1w` | N − 1 이상 | 거절 4.9–7.6 ms `[측정, blind-apps n=8]` |
| 대조(t1_380) kill: 오류 줄 없이 멈춤 | NC1 | `nvs_kill@t1_380` | N − 1 이상 | blind-apps 7/7 `[측정]` |
| 대조(t1_380) 원격 접근 회수: 거절하고도 멈춤 | NC2 | `nvs_remacc@t1_380` | N − 1 이상 | blind-apps 8/8 `[측정]` |
| release 정책: 장치 대기 해제 줄과 함께 모든 프로세스가 스스로 끝남 | NR1 | `nvs_kill_rel@t1w`, `nvs_remacc_rel@t1w` | 셀마다 N − 1 이상 | `[소스]`. 죽은 상대가 있을 때 `nvshmem_finalize`의 부트스트랩 `[미확인]` |
| NVSHMEM PE 0 멈춤: 투명, 죽음과 거절 없음 | NF1 | `nvs_stop@t1w` | N − 1 이상 | `[추론]` |
| NVSHMEM 장애 없음: 투명, 거절과 FIN 판정 없음, 적어도 한 PE가 작별을 보냄 | NF2 | `nvs_none@t1w` | N − 1 이상 | 먼저 정리하는 PE가 작별을 보내고, 그 작별과 FIN을 이미 읽은 PE는 보낼 곳이 없다(리뷰 H2) `[소스]` |
| 장치 대기 단어 확인의 비용: 64 MiB 반복당 ms가 t1_380의 1.10배 이하 | NO1 | `nvs_none@t1w`, `@t1_380` | 중앙값 비교 | `[소스, 추론]`. blind-apps에서 실행 속도가 둘로 갈림 `[측정]` |
| NVSHMEM QP 오류: 투명(회귀) | NQ1 | `nvs_qperr@t1w` | N − 1 이상 | blind-apps 14/14 `[측정]` |
| GIN 랭크 2개 회귀(로컬 QP 오류, 상대 QP 오류, 양방향): 투명 | RG1 | `f1_b`, `f3_b`, `bidirf_sym_b` `@hk` | 셀마다 N 모두 | gin-remaining RG1 `[문서, 다시 세지 않음]` |
| 랭크 2개 kill: 2 s 안 peer-dead 거절 | RG3 | `f4_b@hk` | N 모두 | gin-remaining RG3 `[문서]` |
| 받기만 하는 rank의 대기가 2 s 안에 풀림 | RG4 | `hd_rxdeath_b@hk` | N 모두 | gin-remaining RG4 `[문서]` |
| 원격 접근 오류: rank 0 거절, rank 1 대기 해제, abort 5 s 안 | RG5 | `f2rel_b@hk` | N 모두 | gin-remaining RG5 `[문서]`. 장치가 유예 안에 먼저 보고 `[추론]` |
| 통계 API: 라운드 1, 복구 1(감시가 두 번째 라운드를 만들지 않음) | RG7 | `f1_b@hk` | N 모두 | `[소스]` |
| 랭크 4개 장애 없음, 한 쌍 로컬 QP 오류: 투명 | RG8 | `mr4_none@hk`, `mr4_f1_01@hk` | 셀마다 N 모두 | gin-remaining RG8 `[문서]` |
| rank 3 kill, 시간 제한 없는 받기: 판정 2 000–3 000 ms 뒤 해제, 생존 rank 보내기 완료 | RG9 | `rm4_kill3_untimed@hk` | N 모두 | gin-remaining DG1, DG3 `[문서]` |
| 순환하는 시작 쪽 셋: handshake timeout도 거절도 없이 복구 | RG10 | `mr4_cyc_stall@hk` | N − 1 이상 | gin-remaining CY1 `[문서]` |
| M-A: rank 3이 낮은 rank의 REQ 둘(0, 1)에 기다림 안에서 답하고 투명 | MA1 | `mr4_twolow_stall@hk` | N − 1 이상 | 9.1절 (b) `[소스, 추론]` |
| M-C 기본 규칙: degraded 뒤 건강한 쌍 0-1의 장애는 그 쌍의 거절 | MC1 | `rm4_late01@hk` | N 모두 | 9.1절 (d) `[소스]` |
| M-C 대조(`NCCL_GIN_TS_DEGRADED_ROUNDS=1`): 같은 장애가 복구 | MC2 | `rm4_late01_rounds@hk` | N 모두 | gin-remaining 9.1절 (c) `[소스]` |
| 응답 쪽 틈 고침: rank 3이 응답 쪽 rank 0의 Commit 뒤 DONE 전에 죽음. rank 0이 FIN으로 판정해 원인 peer-dead로 거절하고, 세 생존 rank 모두 자기 판정 뒤 2 000–3 000 ms에 rank 3에서 오는 받기가 풀림, 멈춘 커널 없음 | GP1 | `rm4_gap@hk` | N − 1 이상 | 9.1절 (g) `[소스]`. 다른 생존 rank는 RG9의 길 `[문서]` |
| 대조(`hw`, 같은 조건): rank 0은 원인 unknown으로 거절하고 판정이 없으며, 받기가 풀리지 않아 application의 15 s 유예 뒤에도 커널이 돎. rank 1, 2는 판정 뒤 2 000–3 000 ms에 풀림 | GP2 | `rm4_gap@hw` | N − 1 이상 | 9.1절 (g) `[소스, 추론]` |
| 시험 스위치로 같은 창을 결정적으로: rank 3이 ACK 직후 종료 코드 73, rank 0이 peer-dead로 거절, 세 생존 rank 모두 판정 뒤 2 000–3 000 ms에 풀림 | GP3 | `rm4_gapx@hk` | N − 1 이상 | 9.1절 (g) `[소스, 추론]` |
| 모든 rank가 hold를 요청: rank마다 WARN 한 줄, 모두 effective fail-fast, rank 3 kill은 RG9와 같게 | PH1 | `rm4_kill3_hold@hk` | N 모두 | 9.1절 (f) `[소스]`, RG9 `[문서]` |
| 정책 불일치(rank 0 hold, rank 1 fail-fast): 두 rank가 WARN 한 줄씩, fail-fast, rank 1 kill은 RG3와 같게 | PH2 | `f4_mix_b@hk` | N 모두 | 9.1절 (f) `[소스]`, RG3 `[문서]` |
| L-C: 모든 rank에서 NIC 경로가 NIC만 쓴 자체 시험과 함께 켜짐 | LC1 | `gin_none@hk`, `f1_b@hk` | 셀마다 N 모두 | 9.1절 (c) `[소스]` |
| pilot 1의 로그 틈 고침: GIN 예제(devComm을 먼저 지움)도 두 rank 모두 정리 때 감시 줄을 남김 | WT1 | `gin_none@hk` | N 모두 | 9.1절 (h) `[소스]`. pilot 1은 7회 중 0 `[측정]` |
| 4 KiB 지연: 감시 10 ms와 끔의 차이 0.40 µs 이하 | LT1 | `lat_4k_w10@hk`, `lat_4k_w0@hk` | 실행 중앙값 | `[소스, 추론]` |
| 256 KiB 지연: 차이 0.30 µs 이하 | LT2 | `lat_256k_w10@hk`, `lat_256k_w0@hk` | 실행 중앙값 | 같음 |
| 4 KiB 지연: 감시 1 ms와 끔의 차이 1.0 µs 이하 | LT3 | `lat_4k_w1@hk`, `lat_4k_w0@hk` | 실행 중앙값 | 초당 QUERY_QP 약 4 000번의 영향은 잰 적 없음 `[미확인]` |
| 256 KiB 지연: 같은 비교 1.0 µs 이하 | LT4 | `lat_256k_w1@hk`, `lat_256k_w0@hk` | 실행 중앙값 | 같음 |

감시 주기 100 ms의 지연 셀은 두지 않았다(10 ms의 비용이 정밀도 안이면 100 ms도 그렇다고 본다 `[추론]`). 셀 `lat_*_w100`은 실행하고 설명용으로만 보고한다.

판정식을 읽을 때의 주의.
- GD2의 감지는 감시와 장치 중 먼저 나온 것이다. 어느 쪽이 먼저였는지(`det_by`)는 설명용으로 따로 센다. 감시가 처음 보고 유예 동안 장치가 먼저 보고하면
  감시는 기록을 만들지 않는다(9.1절 (a)).
- NVSHMEM 셀의 kill 대상은 무작위다. 멈춤 셀은 PE 0만 멈춘다(4절).
- GC1, GC2는 두 rank 어디서든 처음 나온 감지(`det1_s`)와 첫 복구 줄(`rec_rx_s`)을 본다(rain 수신 시각). 대상 rank만 보는 `det_ms`는 상대 rank의 flush가
  읽은 늦은 RETRY_EXC를 놓친다.
- GP1–GP3의 창(판정 뒤 2 000–3 000 ms)은 RG9와 같다. 응답 쪽(rank 0)의 판정은 DONE 기다림에서 FIN을 읽은 때다. 창을 맞히지 못한 시행(응답 쪽에
  Commit 뒤 손실의 거절 줄이 없음)은 제외한다(8절). PH1, PH2는 RG9, RG3의 판정식에 정책 열을 더한 것이다.
- RG1–RG10은 gin-remaining의 판정식에서 셀 키만 바꿨다. 그 수(5/5 등)는 gin-remaining `SCORE.md`의 값이고 이 문서에서 다시 세지 않았다 `[문서]`.

## 4. 범위

**포함.**
- GIN 계층 둘, 같은 파일 하나의 호스트 코드만: [hw_layer.diff](hw_layer.diff)(`hr` 트리 기준, pilot 1)과 그 위의 [hk_layer.diff](hk_layer.diff)(정책
  hook, 응답 쪽 틈의 고침, 시험 스위치 하나, 정리 줄; pilot 2와 본 실행). 각각의 운영 빌드는 컴파일 확인만 한다.
- NVSHMEM 계층 하나([t1w_layer.diff](t1w_layer.diff), t1_380 트리 기준, 파일 셋: 전송 모듈, 장치 대기 헤더, 장치와 호스트가 함께 쓰는 헤더).
- 두 공식 예제를 수정하지 않은 채 새 헤더로 다시 빌드한 실행 파일(`gd_gin_ring`, `gd_nvs_rr`). blind-apps의 부트스트랩 대체 파일(`../blind/boot/`)을
  그대로 쓴다.
- 실행기와 채점기: [apprun.py](apprun.py)(`../blind/blindrun.py`를 고쳐 쓴 사본), [cells_reg.sh](cells_reg.sh)(gin-remaining 실행기를 그대로 부름),
  [hold.sh](hold.sh), [chain.sh](chain.sh), [rows_gd.py](rows_gd.py), [score.py](score.py), [cells.json](cells.json), [schedule.json](schedule.json),
  빌드와 배포([build_gd.sh](build_gd.sh), [deploy_gd.sh](deploy_gd.sh), [make_diff_gd.sh](make_diff_gd.sh)).

**제외와 이유.**
- 눈가림: 이번 질문은 감지와 그 비용이다. 장애 종류와 시각은 시드로 뽑아 `schedule.json`에 고정하고, 판정은 기계 판정만 한다.
- 관리망 끊김(mute): 이 실험은 iptables를 쓰지 않는다. 계층이 바꾸는 판정은 FIN과 QP 상태뿐이고, RST와 시간 초과는 앞 빌드처럼 관리망 손실로 본다
  `[소스]`. 따라서 끊김 동작은 blind-apps의 결과를 그대로 둔다.
- NVSHMEM PE 1의 멈춤: 예제에 경쟁이 있다. PE 1의 호스트가 크기 경계를 넘겨 멈추면 PE 0의 다음 크기 put이 PE 1의 검증 전 결과를 덮어써 라이브러리와
  무관하게 틀린다(blind-apps `qa/root_cause.md` 1, 7회 중 2회). PE 0을 멈추면 이 경쟁이 생기지 않으므로 PE 0만 멈춘다 `[추론, n=7]`.
- GIN 원격 접근 오류를 수정하지 않은 예제로 만드는 것: 훅이 없다(blind-apps 4절). 랭크 2개 회귀 셀 `f2rel_b`가 드라이버로 다룬다.
- 장치 쪽 대안(대기 루프 안의 CQ 확인): 상대를 모르는 대기에서 모든 QP의 CQ를 봐야 하고, 동시에 도는 `flush`의 CQE를 가로채지 않으려면 게이트를
  거쳐야 하며, 빠른 경로가 길어진다(blind-apps `qa/root_cause.md` 2) `[추론]`. 이번에는 호스트 감시만 만든다.
- M-C의 게이트 깃발(새 헤더의 장치 코드만 세우는 깃발로 앞 헤더를 알아내는 것): 장치 헤더를 바꿔야 하고, 그러면 배포된 gin-remaining 드라이버를 쓸 수
  없다. 이번에는 호스트만 바꾸는 안전한 기본값(9.1절 (d))으로 두고 깃발 설계는 19절에 남긴다(메인 세션 지시의 허용 범위).
- 실제 link down, flap, 재부팅, 드라이버 재적재, 커널 모듈 적재: 하지 않는다(8절).
- PE와 rank는 2개(app 셀), 랭크 4개는 GIN 회귀 셀만. 노드마다 GPU 하나, 활성 RoCE 포트 하나.
- 정책 `hold`의 동작: 복원 계층이 없으므로 이 빌드는 hold를 요청받아도 fail-fast다. hook의 hold 갈래는 gin-restore가 채운다. 이 실험은 hook이
  fail-fast에서 동작을 바꾸지 않는다는 것만 잰다(H8).
- 응답 쪽 Commit 뒤 손실 중 reset(ECONNRESET, EPIPE)이나 시간 초과로 보인 것: `hw`처럼 원인 Unknown으로 거절한다(9.1절 (g) 충돌 표). 그런 시행을
  만드는 셀은 두지 않았다.

## 5. 테스트베드와 버전

| 항목 | 값 | 확인 방법과 날짜 |
|---|---|---|
| 노드, NIC, GPU, CUDA | blind-apps와 같다: rain(rank 0, Quadro RTX 5000, sm_75), sunny(rank 1, RTX A4000, sm_86), ConnectX-6, RoCE v2, CUDA 12.8 | `../blind/EXPERIMENT.md` 5절 `[측정, 이전 실험]` |
| GIN 기준 트리 | 스크래치 `agent_ts2hr` 작업 트리 = `hr_layer.diff`(md5 `66f61272`), 빌드 `hr` libnccl `2dee2b5b`, `hrp` `786f70bc` | `build_gd.sh gin-setup`이 md5를 확인하고 복사, 2026-10-09 `[측정]` |
| GIN 새 빌드 | `hw` libnccl `efc48ca1a8368eb7feadac5d57f8ff23`, `hwp` `d3b4a2fe704d5edfdbe154360bae9f98`(배포 안 함), `gd_gin_ring` `719dfaab5a3f4294ab89b12ea102ed5b`(SASS sm_75, sm_86). 장치 헤더의 include digest `a27dac89`가 `hr`과 같다 | `[측정]` 2026-10-09 17:33 rain, 스크래치 `agent_gd/out/build_info.txt` |
| GIN 둘째 빌드 | `hk` libnccl `2913c777aa0b05d4d566c9f7638c6a0e`, `hkp` `84209c03a497bd28206210205bfc6cf5`(배포 안 함). 기준은 스크래치 `agent_gd/gin_hk`의 "gpu-detect hw (libnccl efc48ca1)" 커밋(= `hr` + `hw_layer.diff`). include digest `a27dac89`가 `hw`와 같아 `gd_gin_ring` `719dfaab`를 그대로 쓴다 | `[측정]` 2026-10-09 21:14 rain, 스크래치 `agent_gd/out/build_info.txt` |
| NVSHMEM 기준 트리 | 스크래치 `agent_t1_380/src` 작업 트리(t1_380 diff), 설치의 전송 모듈 `d6ae3699` | `build_gd.sh nvs-setup`이 확인하고 복사 `[측정]` |
| NVSHMEM 새 빌드 | `t1w` 전송 모듈 `86c39e91e568fed0a271ca7099b1bb2c`, 호스트 라이브러리 `f3522de834c20c3ffd2044c598485e5d`, UID 부트스트랩 `26da2c31`(t1_380과 같음), `libnvshmem_device.a` `e5ec0e70`, `gd_nvs_rr` `6e93ba5938b0e8f096817dcfabe01907`(SASS sm_75, sm_86), `gd_nvs_boot.so` `e3264e83`(blind-apps의 `blind_nvs_boot.so`와 같음) | `[측정]` 같은 때 |
| 대조 번들(읽기만) | `~/gi-bundle/gin_ts2/hq`(`c1311625`), `hr`(`2dee2b5b`), `hr/gin_ts2`(`4e81d8d8`), `mr/hr/gin_mr`(`d588e9ce`), `~/blind-bundle/hq/blind_gin_ring`(`074ee68c`), `~/blind-bundle/nvs/`(`blind_nvs_rr` `26187ab9`, 전송 `d6ae3699`) | 앞 실험의 배포 확인 `[측정, 이전 실험]`. 배포 때 `deploy_gd.sh`가 두 노드에 있는지 확인 |
| 변경분 | [hw_layer.diff](hw_layer.diff)(`be0ea9ed`), [hk_layer.diff](hk_layer.diff)(`c5222c55`, `hw` 위), [t1w_layer.diff](t1w_layer.diff)(`ac24448b`). 전체 diff는 순정에 앞 계층 diff들과 이 diff들을 차례로 적용한 것(9.4절) | [make_diff_gd.sh](make_diff_gd.sh): 세 diff가 기준 커밋에 다시 적용되어 트리를 재현하고, `hr`에 `hw`와 `hk`를 차례로 적용해도 같음 `[측정]` |

## 6. 변수

- **독립변수.**
  - 빌드: GIN `hk`(pilot 1은 `hw`), `hr`, `hq`, 응답 쪽 틈의 대조만 `hw`. NVSHMEM `t1w`, `t1_380`.
  - GIN 감시 주기 `NCCL_GIN_TS_QPWATCH_MS`: 0(끔), 1, 10(기본), 100. NVSHMEM 정책 `NVSHMEM_IBGDA_FT_T1_FAILSTOP_MS`: 0(fail-stop, 기본), −1(release).
  - 장애: 없음, QP 오류 훅(GIN, NVSHMEM), 원격 접근 회수 훅(NVSHMEM), SIGKILL, SIGSTOP 1–8 s. 시각은 `schedule.json`의 `u_t`로 창 안에서 고르게.
  - 회귀 셀의 장애(gin-remaining 정의), 새 랭크 4개 셀 둘(M-A, M-C), 응답 쪽 Commit 뒤 시작 쪽의 죽음(멈춤 뒤 kill, 또는 ACK 뒤 종료).
  - GIN 정책 `NCCL_GIN_FAULT_POLICY`: 기본 failfast, 모든 rank hold, rank 0만 hold(불일치). 이 빌드에서는 셋 다 fail-fast여야 한다.
- **종속변수.** 3.1절의 열: 결과 분류, 결과 검사, 감지 줄과 감지 지연, 복구 시각, 거절과 죽음 줄, 종료 코드와 종료 시각, FIN 판정과 작별 줄, 장치 대기
  해제 줄, 감시의 QUERY_QP 수와 소요, 장애 없는 지연(p50), ring-reduce 반복당 시간.
- **통제변수.**
  - 시행마다 프로세스를 새로 띄운다. rank 0은 rain, rank 1은 sunny. 대상 rank는 0과 1 반씩(NVSHMEM 멈춤은 PE 0만).
  - GIN app: blind-apps와 같은 NCCL 환경(`NCCL_GIN_TYPE=3`, 분류, 복구, 투명 복구 켬, IB 타임아웃 14, `NCCL_DEBUG=WARN`), helper 포트는 시행마다 고른
    16개 묶음. NVSHMEM app: blind-apps와 같은 환경(t1_380의 `env_t1.sh` 설정, 대칭 heap 160 MiB, `ring-reduce -b 16M -e 64M -n 150 -w 2`).
  - 하네스: 한 rank가 끝난 뒤 유예 10 s, 시행 시간 상한 GIN 20 s, NVSHMEM 30 s(blind-apps는 20 s, 60 s). 멈춤과 해제를 가리기에 충분하다
    `[추론: GIN 트래픽 약 0.14 s, RETRY_EXC 약 3.6 s, NVSHMEM 실행 3.2–6.3 s]`.
  - 포트: rendezvous와 helper 묶음 모두 29000–30999에서 두 노드에 어떤 소켓도 없는 것.
  - 회귀 셀: gin-remaining의 실행기와 드라이버를 그대로 쓴다(빌드만 `hk`, 대조 하나는 `hw`).

## 7. 실험 셀, 반복 수, 대조군

app 셀의 원문은 [cells.json](cells.json), 회귀 셀은 [cells_reg.sh](cells_reg.sh)와 [hold.sh](hold.sh)다. 시행 목록은 `apprun.py plan`이 시드로 만든
[schedule.json](schedule.json)이다(hold 안에서 순서를 섞음, 대상과 `u_t`, `u_d`를 고르게 뽑음).

**app 셀.** 시각 창: GIN 훅은 GDAKI 문맥 생성 뒤 3–116 ms, GIN kill과 멈춤은 기준 줄(`=== Comparing GIN ...`) 뒤 0.003–0.116 s(blind-apps의
`calib.json` 그대로). NVSHMEM 훅은 연결 뒤 500–2 500 ms, kill과 멈춤은 기준 줄 뒤 0.5–2.5 s(blind-apps는 0.515–4.374 s였으나 빠른 실행 3.2 s에서
장애가 실행 뒤로 떨어져 3회가 제외되었다: blind-apps `qa/code_review.md` L6 `[측정, 이전 실험]`. 창을 빠른 실행 안으로 줄였다).

| 셀 | 조건 | 빌드와 반복 수 | 종류 |
|---|---|---|---|
| `gin_qperr` | GIN 예제, 대상 rank의 GIN QP 모두 ERR, 감시 10 ms | `@hk` 16, `@hr` 6, `@hq` 6 | 새 셀, 대조 |
| `gin_qperr_w0`, `_w1`, `_w100` | 같고 감시 0(끔), 1, 100 ms | `@hk` 4, 8, 8 | 대조, 새 셀 |
| `gin_kill`, `gin_stop`, `gin_none` | GIN 예제 kill, 1–8 s 멈춤, 장애 없음 | `@hk` 6, 8, 6 | 회귀, 거짓 양성 |
| `nvs_kill`, `nvs_remacc` | NVSHMEM 예제 kill, 원격 접근 회수(fail-stop) | `@t1w` 8, 8. `@t1_380` 4, 4 | 새 셀, 대조 |
| `nvs_kill_rel`, `nvs_remacc_rel` | 같고 release 정책. 시간 상한 60 s, 유예 50 s(풀린 뒤 예제가 틀린 원소를 모두 찍는다: 많아야 29 360 128줄, pilot 1에서 약 1.5M줄/s) | `@t1w` 5, 5 | 새 셀 |
| `nvs_stop`, `nvs_none`, `nvs_qperr` | PE 0 멈춤 1–8 s, 장애 없음, QP 오류 | `@t1w` 8, 8, 6. `nvs_none@t1_380` 6 | 거짓 양성, 비용, 회귀 |

**회귀와 지연 셀**(빌드 `hk`, 대조 하나만 `hw`; 드라이버는 gin-remaining의 것).

| 셀 | 조건 | 반복 수 | 종류 |
|---|---|--:|---|
| `f1_b`, `f3_b`, `bidirf_sym_b`, `f4_b`, `f2rel_b`, `hd_rxdeath_b` | gin-harden 정의(gin-remaining과 같음) | 각 5 | 회귀 |
| `lat_4k_w<P>`, `lat_256k_w<P>` | 장애 없음, 3 000번 왕복, 감시 P = 0, 1, 10, 100 ms(섞어서) | 각 5 | 비용 |
| `mr4_none`, `mr4_f1_01`, `rm4_kill3_untimed`, `mr4_cyc_stall` | gin-multirank, gin-remaining 정의 | 각 5 | 회귀 |
| `mr4_twolow_stall` | 랭크 4개, rank 0(QP 0>3), 1(1>3), 2(2>1), 3(3>2)에 로컬 QP 오류 6 000 ms, 네 rank에 helper 멈춤 300 ms(정지 뒤): rank 3이 rank 2를 기다리는 동안 낮은 rank 0, 1의 REQ가 함께 기다림 | 5 | 새 셀(M-A) |
| `rm4_late01`, `rm4_late01_rounds` | 랭크 4개, rank 3 kill 9 000 ms(받기 한도 10 s), rank 0의 QP 0>1에 로컬 QP 오류 13 000 ms(degraded 해제 뒤). 둘째는 `NCCL_GIN_TS_DEGRADED_ROUNDS=1` | 3, 3 | 새 셀, 대조(M-C) |
| `rm4_gap` | 랭크 4개, 시간 제한 없는 받기, 상대별 flush, application 유예 15 s. rank 3의 `ctx(3,0)`에 로컬 QP 오류 4 000 ms(문맥 뒤) → rank 3이 시작 쪽, rank 0이 응답 쪽. rank 3은 자기 Commit 뒤 8 000 ms 멈추고(`NCCL_GIN_TS_TEST_STALL=8000@commit`) 실행기가 실행 9 000 ms 뒤 kill: rank 0의 Commit 뒤 DONE 전 | `@hk` 5, `@hw` 3 | 새 셀, 대조(응답 쪽 틈) |
| `rm4_gapx` | 같은 셀에서 멈춤과 kill 대신 rank 3이 ACK 직후 스스로 끝남(`NCCL_GIN_TS_TEST_EXIT_AFTER_ACK=1`, 종료 코드 73) | `@hk` 3 | 새 셀 |
| `rm4_kill3_hold` | `rm4_kill3_untimed`과 같고 모든 rank에 `NCCL_GIN_FAULT_POLICY=hold` | `@hk` 3 | 회귀(정책) |
| `f4_mix_b` | `f4_b`와 같고 rank 0에만 `NCCL_GIN_FAULT_POLICY=hold`(rank마다 다름) | `@hk` 3 | 회귀(정책) |

**합계.** app 130회(GIN 68, NVSHMEM 62), 회귀와 지연 118회(랭크 2개 33, 지연 40, 랭크 4개 45). 셀 키 45개(app 19, 회귀와 지연 26), 예측 41줄.
대조군은 `hr`, `hq`, t1_380과 같은 빌드 안의 감시 끔, release 대 fail-stop, M-C 규칙 두 가지, 응답 쪽 틈의 `hw`다.

**시간 어림** `[추론]`. app 시행의 걸린 시간은 pilot 1의 값(`runner.log`): GIN 투명 약 1.7 s, 멈춤(상한) 20.1 s, kill 11.6 s, 정지 1.6 s + 정지 길이,
NVSHMEM fail-stop 약 2 s, 장애 없음과 QP 오류 약 6.2 s, 정지 약 10 s, release는 유예를 늘려 약 25 s(나쁜 경우 60 s). 시행 사이 약 3 s, hold마다
스냅숏과 유휴 링크 대기 약 1분. 회귀는 gin-remaining의 "시행마다 `wall_s` + 2.7 s"로, `wall_s`는 gin-remaining 본 실행의 중앙값(랭크 4개 18.1 s, `f4_b`
5.3 s 등)과 pilot 1의 값이다. 응답 쪽 틈의 `hw` 대조는 rank 0이 kill 뒤 15 s 유예를 다 쓰므로 약 26 s로 어림한다.

| hold | 내용 | 어림 |
|---|---|--:|
| P1 | pilot 2 app 10회: `hk`의 GIN 셀 모두(QP 오류 2, 감시 끔, 1 ms, 100 ms, kill, 멈춤, 장애 없음 각 1), release 셀 둘(각 1) | 3분 |
| P2 | pilot 2 회귀 13회(`hk`): `f1_b`, `f2rel_b`, 4 KiB 지연 감시 끔과 1, 10 ms, M-A 셀, M-C 셀 둘, 응답 쪽 틈 `rm4_gap`과 `rm4_gapx`, `rm4_kill3_hold`, `f4_mix_b`, 그리고 `rm4_gap@hw` | 4분 |
| G1 | GIN QP 오류 `hk` 16, 대조 16(`hr` 6, `hq` 6, 감시 끔 4) | 8.5분 |
| G2 | 주기 1, 100 ms 각 8, kill 6, 멈춤 8, 장애 없음 6 | 5.5분 |
| N1 | NVSHMEM kill과 원격 접근 회수(`t1w` 8, 8, `t1_380` 4, 4), release 5, 5 | 11.5분 |
| N2 | 멈춤 8, 장애 없음 `t1w` 8와 `t1_380` 6, QP 오류 6 | 6분 |
| R1 | 랭크 2개 회귀 30, 지연 40 | 7.5분 |
| R2 | 랭크 4개 회귀 20 | 8분 |
| R3 | M-A 5, M-C 3 + 3 | 5분 |
| R4 | 응답 쪽 틈 `hk` 5와 `hw` 3, ACK 뒤 종료 3, hold 요청 3, 정책 불일치 3 | 6.5분 |

pilot 2 약 7분, 본 실행(G1–R4) 약 60분, 나쁜 경우(대조가 모두 상한까지 멈추고 release 셀이 60 s 상한까지 가고 다시 도는 hold가 생김) 약 75분이다. N1은
나쁜 경우 800 s 예산을 넘겨 `chain.sh`가 같은 hold를 다시 돌 수 있다. 어느 hold도 880 s 한도 안이다.

## 8. 제외 기준과 중단 기준

**제외 기준.** 제외한 시행은 다시 채우지 않고 셀마다 따로 센다(`SCORE.md` 끝 표).
- pilot(`results/<날짜>_pilot/`, `results/<날짜>_pilot2/`)은 채점하지 않는다.
- app: 걸리지 않은 장애(`applied == 0`: 훅 발화 줄이 없거나 옮긴 QP가 0, 에이전트가 신호를 보내지 못함, 장애 시각 전에 끝남), 시작 실패(`void == 1`),
  설정 확인 실패(`config_ok == 0`).
- 회귀: gin-remaining 8절의 규칙(랑데부 실패, 장애 미적용, 트래픽 밖의 kill, 순환 셀의 라운드 퍼짐 > 250 ms, 펌웨어 초과). 새 셀은 같은 규칙에
  M-A 셀의 발화 "0:2;1:5;2:7;3:11"과 라운드 퍼짐 ≤ 250 ms, M-C 셀의 발화 "0:0"과 트래픽 안의 kill을 더한다(`score.py` `status4_new`).
  응답 쪽 틈 셀: 발화 "3:9"(트래픽 안), `rm4_gap`은 트래픽 안의 kill과 rank 3의 멈춤 줄 "3:8000", `rm4_gapx`는 rank 3의 ACK 뒤 종료 줄, 그리고 둘 다
  창을 맞힘(응답 쪽이 rank 3을 "peer closed the socket before DONE"로 거절, 없으면 "창 밖"으로 제외). `rm4_kill3_hold`, `f4_mix_b`는 반복하는 셀
  (`rm4_kill3_untimed`, `f4_b`)의 규칙.

**설정 확인.** 하나라도 어긋나면 그 시행은 제외되고, 메인 세션은 그 블록을 멈춘 뒤 원인을 12절에 적는다.
- GIN `hk` app 시행: 살아남은 모든 rank에 투명 복구 시작 줄, `GIN/TS: detect=1` 줄(셀의 `qpwatch_ms`), NIC 경로 켬 줄(호스트 shadow와 같은 QP 구조 1개
  이상), 정책 줄(`requested=failfast`, `effective=failfast`), 꺼짐 줄 없음. `hw`(pilot 1)는 정책 줄이 없어야 함. `hr`: `remaining=1` 줄이 있고
  `detect=1` 줄이 없음. `hq`: 둘 다 없음.
- NVSHMEM `t1w`: 모든 PE의 `t1w: gpu-detect=1` 줄(셀의 `failstop_ms`). t1_380: 그 줄이 없음. 둘 다 `transparent mode off`가 없음.
- 회귀: gin-remaining 8절의 `hr` 확인(시작 줄, 드라이버 번들 `hr`, NIC 경로) + 모든 rank의 `detect=1` 줄과 셀의 `qpwatch_ms` + `hk`이면 확인하는 모든
  rank의 정책 줄이 셀이 요청한 정책(기본 failfast, `rm4_kill3_hold`는 모두 hold, `f4_mix_b`는 rank 0 hold)과 `effective=failfast`, `hw`이면 정책 줄 없음.

**pilot에서 보이는 결함.** 태그 전이므로 고칠 수 있다. 미리 정해 둔 예:
- 감시가 장애 없는 실행이나 멈춤에서 감지 줄을 남김: 원인(시작이나 정리 때의 QP 상태)을 고치고 다시 빌드, 새 디렉터리로 배포.
- NVSHMEM 장애 없는 실행에서 FIN 판정이나 fail-stop: 작별 경로를 고친다.
- M-A 셀의 라운드가 겹치지 않음(퍼짐 > 250 ms, 또는 rank 3이 REQ 둘을 기다림 안에서 받지 않음): 멈춤 길이를 한 번 바꿀 수 있다. M-C 셀의 훅이 트래픽
  밖: `LATE_MS`를 한 번 바꿀 수 있다.
- release 셀이 `nvshmem_finalize`에서 멈춤(죽은 상대와의 부트스트랩): 예측 NR1을 kill 셀에서 고치거나 빼고 12절에 적는다.
- 응답 쪽 틈 셀이 창을 맞히지 못함(kill이 rank 3의 멈춤 밖): `GAP_KILL_MS`나 `GAP_STALL`을 한 번 바꿀 수 있다. `hw` 대조에서 rank 0이 풀리면(예측과
  다름) 그 길을 소스에서 찾아 12절에 적고 예측 GP2를 고친다.

**중단 기준.**
- **잠금.** 모든 클러스터 명령은 `../gpu-initiated/common/cluster_run.sh -w 10800` 안에서 돈다([chain.sh](chain.sh), 꼬리표 `gd-<hold>`). 10 800 s 안에 잠금이나
  유휴 링크를 얻지 못하면 그 hold를 미룬다. `prio-` 작업에는 양보한다. hold 하나는 `timeout -s KILL 880`으로 묶는다.
- **하지 않는 것.** 실제 link down이나 flap, 재부팅, 드라이버 재적재, 커널 모듈 적재, RoCE 주소 변경, 시스템 TCP 설정 변경, iptables 규칙 추가, GPU 컴퓨트
  모드 변경. 다른 사용자의 작업(gds-kv, NVMe-oF, gdsio, mooncake, `prio-`)은 건드리지 않는다. `chain.sh`는 hold 앞뒤에 `gin-`, `blind-` 꼬리표 규칙 수를
  읽기만 하고 늘었으면 `STOP_iptables`.
- **프로세스.** 이름으로는 아무것도 끄지 않는다. app 시행의 프로세스에는 그 rank의 `node_agent.py`만 신호를 보낸다(자기가 띄운 PID, 시행 끝에 그 프로세스
  그룹). 회귀 실행기는 자기가 기록한 PID만 신호한다(gin-remaining 그대로). 남은 프로세스는 이 실험의 이름(`gd_gin_ring`, `gd_nvs_rr`, `blind_gin_ring`,
  `blind_nvs_rr`, `gin_ts2`, `gin_mr`)으로 읽기만 해서 세고, 두 시행 연속이면 `STOP_left`. 다음 hold는 150 s까지 기다린다.
- **fail-stop의 종료.** `t1w`의 fail-stop은 라이브러리가 자기 프로세스를 `_exit(70)`으로 끝내는 것이다. 다른 프로세스에는 아무것도 하지 않는다 `[소스]`.
- **CUDA 메모리 오류.** 어느 rank든 종료 신호 11이나 코드 139, 로그에 illegal address, illegal memory access, unspecified launch failure가 보이면 그
  hold 뒤로 멈춘다(`STOP_cuda`). release 정책은 장치 대기를 끝낼 뿐 커널을 trap하지 않으므로 이 규칙과 겹치지 않는다 `[소스]`.
- **mlx5 오류.** hold 앞뒤에 두 노드의 mlx5 커널 줄 전체와 rain의 펌웨어 명령 계수를 남긴다. 새 명령 오류 줄이나 실패 계수 증가가 보이면 `STOP_mlx5`.
  감시는 펌웨어 명령(QUERY_QP)을 더하므로(주기 1 ms에서 rank마다 초당 약 4 000번) 이 확인이 그것의 부작용도 본다 `[추론]`.
- **배포.** 두 노드의 번들 md5가 다르면 app hold가 시행을 돌지 않는다(`STOP_md5`).
- 어느 `STOP_*` 파일이든 생기면 `chain.sh`는 다음 hold를 돌지 않는다. 메인 세션이 원인을 12절에 적고 사용자에게 알린다.

## 9. 실행 방법과 경로

### 9.1 GIN 계층 `hw` ([hw_layer.diff](hw_layer.diff))와 `hk` ([hk_layer.diff](hk_layer.diff))

파일 하나(`gin_host_gdaki.cc`), 호스트 코드만이다. 장치 헤더는 `hr`과 같으므로 `hr` 헤더로 빌드한 드라이버와 예제가 그대로 맞는다 `[소스]`. (a)–(e)는
`hw`, (f)–(h)는 그 위의 `hk`다(같은 파일, 헤더 그대로: include digest가 `hw`와 같음).

(a) **QP 상태 감시** (`gdakiDetWatchStep`, `gdakiDetRecord`, `gdakiDetQueued`) `[소스]`.
- 어디서: helper 스레드의 루프(`gdakiTsMain`)에서, 그 회에 처리할 장애 기록이 없을 때만(라운드 밖). helper가 라운드를 도는 동안 QP 상태는 helper 자신이
  바꾸므로 감시는 그 사이에 돌지 않는다. 앞 실험의 진단용 QPWATCH(분류 감시 스레드, 로그만)는 그대로 두었다.
- 무엇을: `NCCL_GIN_TS_QPWATCH_MS`(기본 10, 0은 끔)마다, 거절되지 않은 게이트 상대마다 그 상대로 가는 모든 GIN QP를 QUERY_QP로 읽는다. 다른 QUERY_QP처럼
  `opMu` 안에서 한다(훅과 라운드의 QP 상태 변경과 겹치지 않음). 라운드의 펌웨어 단계와 달리 펌웨어 감시가 재는 단계(`gdakiRecFwGuard`)로 묶지 않는다(리뷰
  M1): 그 단계 안에서 프로세스가 SIGSTOP되면 SIGCONT 직후 감시 스레드가 단계가 3 000 ms를 넘었다고 보고 건강한 상대의 단어를 올리고 오류를 드러낼 수
  있다. 감시는 몇 % 시간 그 안에 있으므로 멈춤 셀에서 거짓 양성이 된다. 끝나지 않는 QUERY_QP는 helper를 멈추게 하고, 기록이 큐에 있으면 heartbeat 확인이
  그것을 드러낸다.
- 언제 기록을 만드나: QP가 ERR이나 SQER이고, 그 QP의 현재 에폭에 helper가 받은 기록이 없고(`handled < epoch + 2`), 그 상대의 기록이 큐에 없으며,
  `NCCL_GIN_TS_QPWATCH_GRACE_MS`(기본 5 ms) 동안 그 상태로 보였을 때. 유예 동안 장치 스레드가 CQ를 폴링하면 뿌리 CQE가 든 장치 기록이 먼저 오고,
  감시는 아무것도 하지 않는다. QP와 에폭마다 한 번, 상대마다 한 회에 하나만 만든다. CQ 창에 뿌리 오류 CQE가 없으면(`none`, 복사 실패 `unread`) 그 QP가
  `NCCL_GIN_TS_QPWATCH_NOCQE_MS`(기본 50 ms) 동안 RTS 밖에 있어야 만든다(리뷰 M2): 상대가 우리 쪽으로 쓴 원격 접근 오류는 우리 QP(응답 쪽)를 CQE 없이 ERR로
  만들고, 그 오류의 CQE는 상대(요청 쪽)에 있다. 상대의 장치 스레드나 감시가 그것을 거절하고 FAIL을 보낼 시간을 준다. 그 전에 우리가 LOCAL_QP_ERR 라운드를
  열면 상대가 실패한 쓰기를 다시 내고, 거절은 늦어진다(최악은 확대 한도 8라운드). 기록을 만들기 전후에 heartbeat를 새로 쓴다(복사는 2 s로 묶임, 리뷰 L1).
- 기록의 내용: 장치가 쓰는 기록(`q4Report`)과 같은 모양. 장치 QP 구조와 CQ 링을 복사 경로(`gdakiRecD2H`: NIC 경로가 켜져 있으면 NIC 루프백, CUDA 호출
  없음)로 읽어 소비되지 않은 창 [cqe_ci, sq_rsvd_index)의 이번 바퀴 첫 오류 CQE를 뿌리로 분류한다. 창에 뿌리가 없거나 꼬리 flush(syndrome 0x05, vendor가
  0xf5가 아님)만 있으면 보내는 쪽 기록(게이트 `swErr`)을 쓴다. 둘 다 없으면 QP가 아무것도 보내지 않는 중에 ERR로 간 것(로컬 QP 오류, 또는 응답 쪽 오류)으로
  보고 LOCAL_QP_ERR로 둔다. 에폭은 QP의 현재 에폭이다. 기록은 장치 기록처럼 helper의 큐에 들어가고(`gdakiTsPushFault`), helper는 보통 라운드(분류, 상대
  liveness, 정지, 다시 내기)를 돈다.
- 왜 대상 rank만 보면 되나: 훅은 대상 rank의 QP를 ERR로 옮긴다. 상대 쪽 QP는 보낼 것이 남아 있으면 약 3.6 s 뒤 RETRY_EXC로 ERR이 되지만, 그 전에 대상
  rank의 라운드가 REQ로 상대 helper를 부른다. 라운드는 두 rank의 장치 스레드를 필요로 하지 않는다 `[소스, blind-apps의 복구된 2회에서 측정]`.
- 주기와 감지 지연: 장애가 주기 안의 고른 위치에 오면 첫 발견까지 평균 주기의 절반, 그 뒤 유예 5 ms, 다시 읽어 기록을 만들기까지 QUERY_QP 몇 번과 CQ 읽기.
  helper 루프는 소켓 poll을 1 ms로 묶는다. 10 ms 주기에서 약 10–20 ms로 어림한다 `[추론]`.
- 비용: rank마다 주기당 QUERY_QP가 (상대 수 × GIN 문맥 수)번이다. 예제와 `gin_ts2`의 랭크 2개에서는 GIN 문맥 4개로 4번 `[측정: blind-apps 훅 줄 "moved
  4/4"]`. 펌웨어 명령이므로 데이터 경로의 지연이 아니라 펌웨어와 helper 스레드의 시간을 쓴다. 지연 셀(LT1–LT4)과 정리 때 줄(QUERY_QP 수, 평균과 최대
  소요)이 이것을 잰다.
- 다른 상태: RST, INIT, RTR, SQD는 라운드 안에서만 생기므로 라운드 밖에서 보이면 QP마다 한 번 로그를 남기고 아무것도 하지 않는다. QUERY_QP 실패는 장애의
  증거로 쓰지 않고 센다.
- 한 번도 쓰지 않은 QP: ERR이어도 이번 incarnation에 예약한 WQE가 없으면(장치 QP 구조의 `sq_rsvd_index`가 0: 보낸 적이 없거나 지난 커밋이 다시 낸 것이
  없음) 기록을 만들지 않고 다음 보내기를 기다린다(QP마다 한 번 로그). 받기만 하는 QP(랭크 2개 `f3_b`의 rank 1, `hd_rxdeath_b`)는 그래서 `hr`처럼 보내는
  쪽의 RETRY_EXC(약 3.6 s)가 라운드를 연다.
  application이 그 상대로 쓰지 않는 GIN 문맥의 QP가 여기에 든다. 시험 훅은 `NCCL_GIN_FAULT_INJECT_CTX`로 문맥 하나를 고르면 그 문맥의 모든 상대 QP를
  ERR로 옮기므로(랭크 4개 셀), 이 규칙이 없으면 감시가 쓰이지 않는 QP마다 라운드를 더 돌려 회귀 셀의 라운드 구성이 바뀐다. 첫 보내기는 곧바로 flush되고 그때부터
  "쓴 QP"라 다음 회에 기록이 생긴다 `[소스, 추론]`.
- 운영 빌드: 감시는 운영 빌드에도 있다(진단이 아님). 줄은 정보 수준(INFO)이다. 감시가 만든 기록은 `gdakiQ4Handle`을 거치지 않으므로
  `ncclGinFaultQuery`에 나오지 않는다(투명 복구가 맡는 장치 기록과 같은 처지).
- 펌웨어 부하(리뷰 M4): rank마다 주기당 QUERY_QP가 4 × (rank 수 − 1) × (GIN 문맥 수 / 4)번이다. 이 테스트베드의 랭크 2개에서 10 ms면 초당 400번, 1 ms면
  4 000번이고 NIC은 다른 사용자와 같이 쓴다. 1 ms 셀은 짧게 두고(app 8회, 지연 10회) hold마다 mlx5 명령 오류와 펌웨어 실패 계수를 본다(8절). rank 수가
  많은 운영에는 주기를 QP 수에 맞추거나, 비동기 QP 사건이나 CQ 엿보기가 낫다 `[추론]`.

(b) **M-A: 기다림 안 응답은 한 번에 중첩 라운드 하나** `[소스]`. `gdakiTsServeLower`는 중첩 라운드 하나를 마치면 바로 돌아간다. 호출하는 쪽
(`gdakiTsRecvServing`)은 자기 상대의 소켓부터 다시 읽고 다시 부르며, 그때 `gdakiTsCanNest`가 새로 판단한다. 그래서 둘째 낮은 rank의 REQ는 바깥 라운드에
정지 한도와 handshake 한도(기본 합 8 000 ms)가 남아 있을 때만 중첩된다. 이 규칙은 순환을 끊는 규칙(낮은 rank에게만 답함)을 바꾸지 않는다. 경계 자체(바깥
라운드가 25 s를 넘는 경우)는 이 실험의 셀로 만들지 않았다 `[미확인, 소스로만]`. 셀 `mr4_twolow_stall`은 REQ 둘이 함께 기다리는 길이 그대로 복구되는지만
본다.

(c) **L-C: NIC 경로의 자체 시험은 NIC만 쓴다** `[소스]`. gin-remaining의 자체 시험은 NIC으로 읽고 쓴 바이트를 스트림 복사로 확인했다. 이제는:
(1) 게이트가 있는 모든 QP의 장치 QP 구조를 NIC으로 읽어, DOCA가 만들 때 정하고 바꾸지 않는 칸(SQ 번호, 링 크기와 주소, doorbell 기록, CQ 번호, 크기와 주소)이
호스트 shadow(`v->qp_cpu`, export 때 장치로 복사됨)와 같아야 한다. NIC이 장치가 쓰는 바이트를 읽는다는 확인이다. (2) 게이트의 시험 계수 칸과 사본 블록의 앞
64 B에 무늬를 NIC으로 쓰고 NIC으로 다시 읽은 뒤 0으로 되돌린다. (3) 등록한 할당마다 처음 범위(64 B까지)를 NIC으로 읽고 그대로 다시 쓰고 다시 읽는다. CUDA
호출이 없으므로 application이 스트림을 붙잡고 있어도 시험이 시간을 넘기지 않고 `copyStuck`이 생기지 않는다. 남는 점(리뷰 L3): 문맥을 만들 때의 다른
CUDA 호출(사본 블록의 할당과 0 채우기, 그 스트림 동기화는 한도 없음)이 이 시험보다 먼저 있어, 붙잡힌 스트림은 그 자리에서 devComm 생성을 늦춘다(끄지는
않음). 그래서 이 수정의 효과는 "스트림이 시험 직전에 붙잡히는" 좁은 경우에 한한다 `[소스, 추론]`. NIC과 CUDA의 교차 확인은 장치 QP 구조의 등록(shadow
비교)에만 남았다. 보내기 링, CQ 링, doorbell 기록, 사본 블록, get 표의 등록은 NIC 왕복으로만 확인하므로, NIC이 쓴 바이트를 GPU가 보는지는 그 등록들에
대해서는 확인하지 않는다 `[소스]`.

(d) **M-C: degraded 뒤 게시 전 확인의 안전한 기본값** `[소스]`. `NCCL_GIN_TS_DEGRADED_ROUNDS`(기본 0)가 0이면 `gdakiUaPeerRaised`는 상대 단어가 들어갔어도
칸 0을 센다(gin-peer 이전의 규칙). 칸 0이 올라가면(degraded, 또는 모든 상대 거절) 어느 상대와의 라운드도 게시하지 않고 그 쌍을 거절한다. 앞 헤더로 빌드한
장치 코드(상대별 대기에서 칸 0을 읽음)가 칸 0으로 실패를 알린 연산을 그 상대와의 라운드가 다시 내는 일을 막는다. 대가: degraded 뒤에는 건강한 쌍의 장애도
복구되지 않는다. degraded는 이미 application에게 shrink나 abort를 하라는 신호이므로 이 대가를 기본으로 둔다. `=1`이면 gin-remaining의 규칙(새 헤더의
application에서 건강한 쌍의 라운드가 계속됨)이다. 장치 코드의 헤더 판별(게이트 깃발)은 하지 않았다(19절). 리뷰 M3이 짚은 또 하나의 대가: 그 거절은 원인이
이 rank 쪽(Local)이라, 죽은 rank만 빼는 중단 shrink의 넘김(gin-handoff 규칙: 빼는 상대의 상대 쪽 원인만 넘김)을 막는다. 그 shrink는 일반 실패로 돌아가고
application은 건강한 상대까지 빼거나 abort해야 한다. degraded 뒤 건강한 쌍에 장애가 없으면 이 일은 생기지 않는다 `[소스]`.

(e) **의미와 비용 요약.**

| 동작 | `hr` | `hw` |
|---|---|---|
| 장치 스레드가 CQ를 읽지 않는 동안의 QP 오류 | 감지 없음(상대가 보내던 중이면 약 3.6 s 뒤 RETRY_EXC가 `flush`에서 읽힐 때만) | 감시가 주기 + 유예 안에 감지하고 보통 라운드 |
| 장치 스레드가 CQ를 읽는 중의 QP 오류 | 장치 기록 | 같음(감시는 유예 동안 기다렸다 기록을 보고 물러남) |
| 거절된 상대, 죽은 상대 | 해당 없음 | 감시하지 않음 |
| 낮은 rank REQ 둘 | 한 번 훑을 때 둘 다 중첩될 수 있음 | 중첩 하나마다 다시 판단 |
| NIC 경로 자체 시험 | 스트림 복사와 비교 | NIC만, QP 구조와 shadow 비교 |
| degraded 뒤 건강한 쌍의 라운드 | 계속 | 기본은 거절(`=1`이면 계속) |
| 비용 | 없음 | rank마다 10 ms당 QUERY_QP 4번(랭크 2개, 문맥 4개). 감지 때 장치 QP 구조와 CQ 링 읽기(뿌리 CQE가 없으면 50 ms까지 회마다 다시) |

(f) **정책 hook 아홉(빌드 `hk`)** `[소스]`. 사용자 승인(2026-10-09)으로 `hw` 위에 gin-restore의 통합 정책 설계(`DESIGN_POLICY.md` 4.10절, gin-restore
worktree `harness/gpu-initiated/gin_recovery/restore/`)가 정한 hook을 같은 파일에 넣는다. 감지는 두 정책에 공통이고 반응만 communicator마다의 정책이다.
복원 계층이 없으므로 이 빌드의 유효 정책은 늘 fail-fast이고, 모든 hook은 fail-fast에서 `hw`가 하던 일을 그대로 한다. hook은 복원 계층이 나중에
채울 얇은 자리다. 줄 번호는 `hw`의 `gin_host_gdaki.cc`다.

| hook | 자리(hw 줄) | fail-fast(이 빌드) | 복원 계층이 채울 것 |
|---|---|---|---|
| 정책 칸(G1) | `gdakiTsSetup` 6438–, 설정 all-gather 레코드 6458–6518 | `NCCL_GIN_FAULT_POLICY`(기본 `failfast`, `hold`)를 읽어 레코드에 싣는다(48 B → 56 B). `hold`이면 WARN 한 줄("hold requested, not available in this build; fail-fast"), 이 helper의 rank 사이에서 다르면 그 대신 불일치 WARN 한 줄, 둘 다 fail-fast. 다른 값이면 WARN 한 줄 더. WARN은 투명 복구가 켜진 GDAKI 문맥마다 한 번이다(이 실험의 셀은 rank마다 문맥 하나, 꺼진 문맥은 꺼짐 WARN만). 유효 정책을 문맥과 communicator 등록부(`gdakiUa`)에 둔다. 레코드가 커지므로 한 job의 모든 rank는 같은 라이브러리여야 한다(지금도 같은 전제) | hold의 무장 |
| 거절 hook(G2) | `gdakiTsDecline` 4941 맨 앞 | 거짓을 돌려 거절은 그대로. 상대의 `lostAfterCommit`(아래 (g))을 읽을 수 있다 | 붙잡은 상대의 fallback, hold 시작 |
| 감시 hook(G3) | `gdakiDetWatchStep`의 상대 거르기 6094 | 참(감시함) | 붙잡은 상대(HELD, COMMITTING)를 뺌 |
| 기록 처리 hook(G4) | helper의 기록 루프 6405 | 참(라운드를 연다). 뒷정리(`ts->batch`, heartbeat, `nQueued`)는 hook 밖에서 그대로 돈다 | 흡수, fallback 표시 |
| 훑기 hook(G5) | `gdakiTsScan`의 유실 검사 5923 | 검사함 | 붙잡은 상대에서 건너뜀 |
| 에폭 기준(G6) | 6066, 6139, 그리고 hr에서 물려받은 5460, 3361 | `gdakiTsCoveredEpoch(s)`가 `s.epoch`를 돌려준다(빈 라운드가 없음) | 빈 라운드의 기준 |
| rmsn 전달(G7) | 감시의 QUERY_QP 6111 | 같은 펌웨어 명령이 rmsn 칸도 돌려주고(DOCA `query_seq`는 한 명령의 출력에서 칸을 고를 뿐) hook은 아무것도 하지 않는다 | 누적 실행 수 |
| 감시 스레드 걸음(G8) | `gdakiTsWatchdog` 3490(`gdakiUaDegradedStep` 옆) | 아무것도 하지 않음(붙잡은 상대가 없음) | 복원 시한 |
| 펌웨어 초과의 책임 원인(G9) | 3530 | Local 그대로 | 붙잡은 상대면 PeerDead |

같은 설계가 문서로만 정한 것: `NCCL_GIN_TS_DEGRADED_MS`, `NCCL_GIN_TS_DEGRADED_ROUNDS`는 fail-fast 반응의 변수이고, QP 감시의 변수(`NCCL_GIN_TS_QPWATCH_MS`,
`_GRACE_MS`, `_NOCQE_MS`)는 감지의 변수라 두 정책에 같다. hold 정책에서 앞의 둘은 거절(fallback)이 일어난 뒤에만 효과가 있다.

(g) **응답 쪽 Commit 뒤 소켓 손실(빌드 `hk`)** `[소스]`. 응답 쪽(`gdakiTsRespondPrepared` 5206–)이 Commit(5253)한 뒤 ACK를 못 보내거나(5285–5292) DONE을
기다리다 소켓을 잃으면(5298–5303) `hw`는 죽음 판정 없이 `pe.gone`을 세우고 원인 Unknown, 단어 이유 `GDAKI_UA_DECLINED`로 거절한다. degraded는
`GDAKI_UA_PEER_DEAD`의 거절에서만 예약되고(`gdakiUaRaisePeer` 2833–2847), `pe.gone`이 다시 걸기를 막아 그 죽음은 이 rank에서 다른 길로도 판정되지
않는다. 그래서 랭크 3개 이상에서 이 rank의 상대를 모르는 대기(`waitSignal` 등, 칸 0만 읽음)는 풀리지 않는다. 랭크 2개에서는 "모든 상대 거절" 규칙(2820–2831)이
칸 0을 바로 올린다. 같은 죽음을 FIN으로 본 다른 생존 rank는 판정하고 degraded가 되므로 이 rank 하나만 남는다.
- 고침: 두 자리 모두 맨 먼저(판정과 어느 돌아가기보다 앞) 상대별 새 칸 `pe.lostAfterCommit = true`를 세운다(gin-restore와 정한 이름: 거절 hook이 읽는
  약한 증거, hold 정책에서도 붙잡지 않음). DONE 기다림에서 잃었으면 그 받기가 남긴 원인(`gdakiTsPump`의 `pe.closeCause`)에 idle 루프와 같은 판정 규칙
  (`gdakiTsCauseLiveness` 3737–3743, BYE 뒤면 떠남)을 부작용 없이 먼저 적용한다. 죽음(BYE 없는 FIN, BADMAGIC, 모름 목록 밖의 errno)이면
  `gdakiTsSocketLost`(3771–3802)로 판정하고(idle 루프와 같은 WARN 두 줄, 죽음 계수, 소켓 닫음) 원인 PeerDead, 단어 이유 `GDAKI_UA_PEER_DEAD`로 거절한다.
  그 밖(reset과 시간 초과는 모름, BYE 뒤)은 `hw` 그대로다. ACK 보내기 실패는 죽음으로 판정하지 않는다: 보내기는 연결이 reset되거나 시간을 넘긴 뒤(모름)나 이
  rank 쪽 소켓 상태 때문에만 실패하고, 상대의 FIN만으로는 보낼 수 있다. 그래서 그 errno를 `pe.closeCause`에 이름으로 남기고(`gdakiTsSend`는 원인을 쓰지
  않음, `hw`의 다른 보내기 실패 5606, 5749와 같게) `hw` 그대로 거절한다. 실패한 보내기가 소켓 오류를 가져가므로 그 뒤 받는 쪽을 엿보면 reset이 FIN으로
  읽힌다(독립 리뷰가 찾음, 12절). `pe.lostAfterCommit`은 그 상대로 연결을 다시 설치할 때만 지운다(`gdakiTsInstall` 3884–3897; gin-restore 설계 D4의 REJOIN도 이것으로
  설치할 예정 `[미확인]`). 거절된 상대는 다시 걸지 않으므로 이 빌드에서 선 깃발은 그대로 남는다.
- 시험 스위치(연구 빌드만, `#ifndef NCCL_GIN_TS_PRODUCTION`): `NCCL_GIN_TS_TEST_EXIT_AFTER_ACK=<k>`이면 그 GDAKI 문맥의 시작 쪽이 k번째로 받은 ACK 직후
  (자기 Commit과 DONE 전, 5717 앞) WARN 한 줄을 쓰고 `_exit(73)`으로 끝난다. BYE를 보내지 않으므로 커널이 소켓을 FIN으로 닫는다(받는 버퍼가 비어 있음: ACK는 읽었고 응답 쪽은
  DONE을 기다리며 아무것도 보내지 않음).

**충돌 표**(구현 전에 작성). 고침이 닿는 기존 장치마다 지금과 고친 뒤를 비교했다.

| 기존 장치(hw 줄) | 지금(`hw`) | 고친 뒤(`hk`) | 충돌 | 해결과 근거 |
|---|---|---|---|---|
| 시작 쪽 재시도와 NACK 2(`gdakiTsCancelRound` 5152–5171, 거절된 상대의 REQ에 NACK 2 5785) | Commit 뒤 손실은 거절. 시작 쪽이 살아서 다시 오면 NACK 2(원인 Unknown) | DONE 기다림의 죽음 판정이면 소켓을 닫아 재시도가 올 길이 없음. ACK 자리와 모름은 같음 | 없음 | DONE 기다림에서 죽음으로 보는 원인은 그 받기가 남긴 것이고 idle 루프도 같은 원인을 죽음으로 보고 소켓을 닫는다(3771–3802). 살아 있는 시작 쪽에서 BADMAGIC이 난 경우 그 쪽이 이 rank의 FIN을 죽음으로 보는 사슬도 idle 루프와 같다 |
| `pe.gone`과 다시 걸지 않음(다시 걸기와 탐침이 `declined`를 거름 3997, 4094; idle 루프가 `gone`을 거름 6346, 6356) | gone, 소켓은 정리 때까지 열림, 재연결 없음 | 죽음: 소켓 닫고 gone. 모름: 같음 | 없음 | 둘 다 재연결이 없다(거절은 종단) |
| 취소 길(`gdakiTsCancelRound` 5152–5171, `gdakiTsCancelResponder` 5177–5198, Commit 전 엿보기 3863–) | Commit 전 손실은 취소(상대 모름, 시작 쪽 재시도) | 바꾸지 않음 | 없음 | 고친 자리는 Commit 뒤 두 곳뿐 |
| 재연결 기계와 liveness 판정(3737–3743, 3749–3766, 3771–3802, `gdakiTsRefused` 3809–3835) | 이 창에서는 판정을 부르지 않음 | DONE 기다림: 그 받기의 원인을 같은 규칙으로 먼저 분류하고 죽음일 때만 `gdakiTsSocketLost`. ACK 자리: 판정하지 않음. 모름이면 `gdakiTsMakeUnknown`을 부르지 않음 | 없음 | 판정 규칙은 그대로. 모름을 재연결 기계에 넘기지 않는 것은 `hw`와 같다(거절된 상대는 다시 걸지 않음). 그래서 reset으로 보인 죽음(죽은 프로세스의 소켓에 읽지 않은 자료가 있었을 때)은 이 창에서 여전히 degraded 없이 거절된다(18절) |
| 시작 쪽 ACK 기다림, DONE 보내기 실패(5611–5716, 5746–5753) | 그대로 | 그대로 | 없음 | 시험 스위치만 5717 앞에 들어간다(연구 빌드) |
| 보내기 실패의 원인(`gdakiTsSend`는 `pe.closeCause`를 쓰지 않음, `gdakiTsInstall`이 지움 3892; `hw`의 다른 보내기 실패는 errno를 먼저 옮김 5606, 5749) | ACK 자리는 원인을 남기지 않음 | ACK 자리도 errno를 이름으로 남김("send failed": 시간 초과나 이름 목록 밖의 errno, `hw`의 다른 보내기 실패와 같은 규칙) | 없음 | 원인 칸은 거절된 상대에게 다시 읽히지 않는다. 판정에 쓰지 않음(위) |
| 닫을 때의 reset(`gdakiTsMakeUnknown`의 SO_LINGER 0 3751–3755, `gdakiTsAbortClose` 3899–3904: 산 상대가 ECONNRESET으로 "모름"을 읽게 함) | 해당 없음 | 시작 쪽이 Commit 창에서 라운드를 취소해 소켓을 reset하면: DONE 기다림은 ECONNRESET(모름)으로 `hw` 그대로, ACK 자리는 판정하지 않으므로 `hw` 그대로 | 없음 | 산 시작 쪽을 죽음으로 보지 않는다. 받는 쪽을 엿보는 판정(첫 구현)은 이 reset을 FIN으로 읽어 충돌이었고 지웠다(12절) |
| degraded와 "모든 상대 거절"(2820–2831, 2833–2847, `gdakiUaDegradedStep` 2874–2901) | 단어 이유 DECLINED: 그 상대 단어만, degraded 예약 없음. 랭크 2개는 칸 0이 바로 | 죽음: 이유 PEER_DEAD. 첫 죽음이면 `NCCL_GIN_TS_DEGRADED_MS`(2 000 ms) 뒤 칸 0. 랭크 2개는 지금처럼 바로(이유 값만 peer-dead) | 없음(의도한 변화) | 같은 죽음을 판정한 다른 생존 rank와 같아진다 |
| M-C 게시 전 확인(`gdakiUaPeerRaised` 2918–2925, `NCCL_GIN_TS_DEGRADED_ROUNDS=0`) | 이 rank는 degraded가 안 되어 건강한 상대와의 라운드가 계속 게시됨 | degraded 뒤 건강한 쌍의 라운드는 거절(원인 Local) | 없음 | 다른 죽음 뒤와 같은 대가(9.1절 (d)), 규칙은 그대로 |
| 책임 원인과 shrink 넘김(`gdakiBlameNote` 841–859, 거절의 기록 4962, `ncclGinTsBlameQuery` 865–885) | Unknown은 상대 쪽 원인이 아니라 질의가 −3, 그 상대를 빼는 중단 shrink는 일반 실패 | 죽음: PeerDead(상대 쪽 원인)라 넘김이 통과. 모름: 같음 | 없음 | 넘김 규칙은 그대로, 원인만 맞게 적힘 |
| QP 감시(6094), 훑기(5909) | 거절된 상대는 다루지 않음 | 같음 | 없음 | |
| 통계 계수(`cDeclined` 4953, `cDeaths` 3798, `ncclGinGetRecoveryStats` 7454–) | 거절 +1 | 죽음: 거절 +1, 죽음 판정 +1 | 없음 | 판정이 있었으므로 맞는 수. 기존 회귀 셀은 이 창을 지나지 않음 |
| 비동기 오류(4964–4967) | 거절이 세움 | 같음 | 없음 | |
| FAIL(거절의 FAIL 4970–4979, 거절한 상대의 재연결에 FAIL 3935–3948, 4201–4205, 4229–4232) | 이 거절은 FAIL을 보내지 않음 | 같음(죽음이면 소켓도 닫힘) | 없음 | |
| 정리의 BYE(`gdakiTsCloseAll` 3637–3660: gone이면 BYE 없이 close) | 정리 때 BYE 없이 닫힘 | 죽음: 판정 때 이미 닫힘 | 없음 | 상대가 살아 있었다면 FIN을 보는 때만 앞당겨진다(둘 다 BYE 없음) |
| helper 루프의 죽음 거절(6380–6386, `deadJudged`) | 해당 없음 | `gdakiTsSocketLost`가 세운 `deadJudged`를 바로 뒤의 거절이 지움(4948) | 없음 | 두 번 거절하지 않음 |
| 기다림 안 응답과 미룬 REQ(`gdakiTsServeLower` 5341–5407, `gdakiTsRecvServing` 5422–, 미룬 REQ 6308–6341) | 중첩 응답 라운드도 같은 거절 | 같은 함수라 같은 고침. 닫힌 소켓은 바깥 기다림의 poll 목록(fd < 0, gone을 거름)과 미룬 REQ(6312)가 이미 다룸 | 없음 | |
| 양보한 시작 쪽(`gdakiTsRespondPrepared`의 `yf`) | 같은 거절, 자기 장애는 다시 줄에 서지 않음 | 원인만 바뀜 | 없음 | |
| 거절 hook과 새 칸 `pe.lostAfterCommit` | 없음 | 그 길의 맨 먼저 세움, 거절 hook이 거절 안에서 읽을 수 있음(fail-fast에서는 거절 그대로). 지우는 곳은 `gdakiTsInstall`뿐 | 없음 | 이 빌드에서 깃발이 선 상대는 거절된 상대(종단)라 다시 설치되지 않으므로(다시 걸기 3997, 4006과 받기 4229–4239가 거절된 상대를 거름) 선 깃발은 지워지지 않는다. gin-restore 설계의 "지우는 곳은 REJOIN뿐"과 같은 뜻이 된다. 설계 D4대로 REJOIN이 `gdakiTsInstall`로 설치하면 그때 지워진다 `[미확인: 복원 계층은 아직 없음]`. `gdakiTsInstall`은 `lostCause`를 지우지 않으므로 REJOIN이 따로 지워야 한다(복원 계층에 남기는 메모) |
| 라운드 한도(3542–3550), 펌웨어 단계 감시(3497–3541) | 해당 없음 | 라운드 안에서 소켓 close 하나가 더해질 뿐, 펌웨어 명령은 더하지 않음 | 없음 | |
| 장치 쪽(`gin_gdaki.h`) | 그대로 | 그대로. 칸 0이 degraded로 오르면 상대를 모르는 대기가 오류로 돌아온다(gin-remaining 규칙) | 없음 | |
| 기존 열과 셀(`n_judged`, `n_death`, gin-remaining의 `judged`; GIN app kill, `f4_b`, `rm4_kill3_untimed`) | | 이 창의 죽음은 이제 "judged dead" 줄을 남긴다 | 없음 | 기존 셀의 kill은 라운드 밖이라 이 창을 지나지 않는다. 새 셀만 지난다 |

**어느 rank가 멈추고 왜인가**(새 셀 `rm4_gap`, `rm4_gapx`, 실행 전에 작성) `[소스, 추론]`. 랭크 4개(짝수 rain, 홀수 sunny), 모든 방향의 간선, 시간 제한 없는
받기(`GIN_MR_RX_UNTIMED=1`), 상대별 flush, 장애 뒤 application의 유예 15 s(`GIN_MR_GRACE_S=15`). rank 3의 문맥 `ctx(3, 0)`에 로컬 QP 오류를 넣어 rank 3이
시작 쪽, rank 0이 응답 쪽인 라운드를 만든다.
- `rm4_gap`(두 빌드에 같은 조건): rank 3에 `NCCL_GIN_TS_TEST_STALL=8000@commit`(시작 쪽이 자기 Commit 뒤 DONE 전에 8 s 멈춤, `hw`에 이미 있는 스위치),
  장애 4 000 ms(문맥 뒤), 실행기가 rank 3을 SIGKILL 9 000 ms(실행 뒤). pilot에서 실행 뒤 9 000 ms의 kill은 devComm 뒤 8.02 s였으므로 kill은 멈춤 창
  (devComm 뒤 약 4.1–12 s) 가운데에 든다 `[측정: pilot 1, n=1]`. 창에 든 시행은 rank 0의 로그에 "peer closed the socket before DONE" 거절 줄이 있다.
- `rm4_gapx`(`hk`만): rank 3에 `NCCL_GIN_TS_TEST_EXIT_AFTER_ACK=1`. 창을 결정적으로 맞춘다.
- rank 0(응답 쪽): Commit 뒤 DONE 기다림에서 FIN. `hw`: 원인 Unknown 거절, 판정과 degraded 없음 → rank 3에서 오는 받기는 칸 0을 기다리며 풀리지 않고,
  application은 비동기 오류를 본 뒤 15 s 유예가 지나도 커널이 끝나지 않아 `async_error_kernel_stuck`(종료 코드 3)로 abort한다. `hk`: 죽음 판정(cause=FIN),
  PeerDead 거절, 2 000 ms 뒤 칸 0 → 받기가 풀리고 커널이 끝난다.
- rank 1, 2: rank 3의 helper 소켓에서 BYE 없는 FIN을 idle 루프에서 보고 판정, PeerDead 거절, 2 000 ms 뒤 칸 0(두 빌드 같음, gin-remaining RG9와 같은 길).
- 그래서 `hw`에서는 rank 0만 멈추고, `hk`에서는 세 생존 rank 모두 자기 판정 뒤 2 000–3 000 ms에 rank 3에서 오는 받기가 풀린다. 랭크 2개라면 두 빌드 모두 바로 풀린다.

(h) **정리 때 감시 줄(빌드 `hk`)** `[소스]`. 감시의 정리 줄(QUERY_QP 수와 소요)은 `ncclGinGdakiTsCommTeardown`이 등록된 문맥에만 썼다. GIN 예제는
communicator보다 devComm을 먼저 지우므로(`ncclDevCommDestroy` → `gdakiRecFree` → `gdakiTsFree`) 그 줄이 나오지 않았다(pilot 1, 12절). `hk`는 그 줄을
`gdakiTsFree`에서도 쓴다(문맥마다 한 번; 정리가 기다림을 포기했다가 그 뒤 끝난 helper의 문맥도 이제 줄을 남긴다). 로그만 바뀐다.

### 9.2 NVSHMEM 계층 `t1w` ([t1w_layer.diff](t1w_layer.diff))

(a) **작별과 FIN 판정** `[소스]`.
- 정리(`t1_fini`, `nvshmem_finalize`의 배리어 뒤 전송 모듈 정리)는 helper를 멈춘 뒤 살아 있는 모든 라이브러리 소켓에 `T1_M_BYE`를 보내고 나서 닫는다.
- 받는 쪽은 그 소켓의 어느 읽기(`t1_recv`: helper 루프든 라운드든)에서든 BYE를 보면 그 상대를 "떠남"으로 표시한다. TCP 순서상 BYE는 FIN보다 먼저
  읽힌다.
- helper 루프는 FIN을 본 상대(어느 읽기가 보았든)마다 한 번: 작별이 있었으면 "떠남" 줄만, 없으면 그 상대를 죽음으로 보고 바로 거절한다(`t1_decline`, 이유
  "the peer's library socket closed (FIN) without a goodbye (peer process gone)"). `NVSHMEM_IBGDA_FT_T1_FIN_DEATH=0`이면 t1_380처럼 판정하지 않는다.
- 버퍼에 읽혀 있으나 아직 해석하지 않은 BYE(앞 메시지와 함께 온 것)는 FIN을 엿보는 `t1_peer_fin`이 먼저 찾아 표시한다(리뷰 L7: 그렇지 않으면 정리 중의
  장치 기록 하나가 정상 종료를 죽음으로 판정할 수 있었다).
- FIN은 그 프로세스가 끝날 때 커널이 보낸다. `nvshmem_finalize` 없이 끝난 프로세스(kill, 충돌, 일찍 끝냄)는 작별을 보내지 않으므로 판정된다. RST와
  시간 초과는 앞 빌드처럼 관리망 손실(다시 연결)이고 판정하지 않는다. SIGSTOP된 프로세스는 소켓을 닫지 않고 커널이 TCP에 답하므로 FIN도 시간 초과도 없다
  `[추론]`.

(b) **fail-stop** (`t1w_after_decline`, `t1w_failstop_exit`) `[소스]`. 모든 T1 거절(`t1_decline`)의 끝에서, `NVSHMEM_IBGDA_FT_T1_FAILSTOP_MS`가 0(기본)이면
DECLINE 줄, 호스트 기록, "marked failed" 줄, 상대에게 FAIL(보낼 수 있으면)을 마친 뒤 `_exit(70)`(`NVSHMEM_IBGDA_FT_T1_FAILSTOP_CODE`)으로 끝난다. 마지막
줄은 stdio 잠금 없이 `write(2)` 한 번으로 쓰고 PE 번호는 init 때 저장한 값을 쓴다(리뷰 L8, L9: stderr에 막힌 application 스레드나 정리 뒤의 전송 구조가
종료를 늦추지 않게). stdout은 잠금을 얻을 수 있을 때만 비운다. `_exit`는 atexit 처리기와 정적 소멸자를 건너뛴다(그것들은 helper나
끝나지 않는 커널을 기다릴 수 있다). 상대는 FAIL이나 작별 없는 FIN을 보고 거절하므로 같은 길로 끝난다. 0보다 크면 장치 대기 단어를 올리고 그만큼 뒤에
끝난다(application이 먼저 끝나면 그것으로 끝). −1이면 끝내지 않는다(release).

(c) **장치 대기 단어** `[소스]`.
- 호스트: `t1_init`이 호스트에 매핑된 64 B(`cudaHostAllocMapped`)를 잡고, 장치 주소를 FT 장치 블록의 새 칸 `nvshmemi_ibgda_ft_dev_t::t1w_abort`에 쓴다.
  release와 지연 fail-stop에서 거절이 이 단어를 1로 올린다(평범한 저장, CUDA 호출 없음).
- 장치: `nvshmemi_wait_until*`(`wait_until`, `signal_wait_until`, 배리어와 집합 연산의 pSync 대기가 쓰는 함수 일곱)의 루프가 1 024번 돌 때마다 단어를 한
  번 읽고(PCIe 읽기 하나), 올라가 있으면 조건이 참인 것처럼 돌아간다. application이 닿는 호출 위치(BARRIER*, *WAIT_UNTIL*, WAIT_NE)에서만 읽고, proxy
  채널의 대기(PROXY_*, AMO_FETCH_*, G_WAIT_FLAG)에서는 읽지 않는다(그 대기가 일찍 끝나면 채널이 깨진다). T1이 꺼져 있으면 상수 메모리의 깃발 하나만 본다.
- 헤더: 이 함수들은 application에 컴파일되므로 예제를 새 헤더로 다시 빌드했다(소스는 그대로). FT 장치 블록의 크기가 8 B 늘었다(칸은 끝에 붙였다). 장치
  코드는 `t1w` 전송 모듈만 세우는 깃발 `NVSHMEMI_IBGDA_FT_FLAG_T1W`가 있을 때만 그 칸을 읽는다(리뷰 L5: 새 헤더의 application을 앞 전송 모듈과 쓰면 블록
  끝 너머를 읽을 뻔했다). t1_380 헤더로 빌드한 application은 이 칸을 모르므로 단어를 읽지 않는다(t1_380처럼 돈다). 두 함수는 `NVSHMEMI_STATIC`이다(리뷰
  L4) `[소스]`.
- 풀지 않는 대기(리뷰 L10): `nvshmem_test`로 스스로 도는 `wait_until_any`, `_any_vector`, `_some`, 그리고 대기의 반환값을 보고 다시 기다리는 application
  루프. ring-reduce는 풀리는 대기만 쓴다 `[소스]`.

(d) **정책별 의미.**

| 상황 | t1_380 | `t1w` fail-stop(기본) | `t1w` release(−1) |
|---|---|---|---|
| 상대 kill, 보낼 것 없음 | FIN 로그만, 멈춤 | FIN 판정 → 거절 → 종료 코드 70 | FIN 판정 → 거절 → 장치 대기가 풀림. 받지 못한 데이터는 틀린 값 그대로, application은 호스트 질의로 알아야 함 |
| 원격 접근 회수 | 두 PE 거절, 멈춤 | 두 PE 거절 → 종료 코드 70 | 거절 → 대기가 풀림, 이후 put은 게이트에서 바로 실패(보내지 않음) |
| 상대 멈춤(SIGSTOP), 관리망 끊김 | 판정 없음 | 같음 | 같음 |
| 정상 종료 | FIN 로그 | 작별 뒤 FIN: 떠남 | 같음 |
| QP 오류 | 투명 복구 | 같음 | 같음 |

(e) **비용과 한계** `[소스, 추론]`. 장치 대기마다 계수 하나와 비교 하나, 1 024번에 한 번 상수 메모리 둘과 PCIe 읽기 하나(잰 것은 NO1). fail-stop은 거절을
처리하는 application(호스트 질의로 거절을 알고 정리하는 프로그램)도 끝낸다. 그런 application은 −1이나 양수를 써야 한다. fail-stop의 종료 코드 70은
`nvshmem_global_exit`가 정한 코드를 덮는다. 정리(`nvshmem_finalize`) 중에도 helper가 멈추기 전이면 작별 없는 FIN이 판정되어 70으로 끝날 수 있다(그 상대는
죽은 것이다). RST로 끝난 연결(죽은 프로세스의
소켓에 읽지 않은 데이터가 있었을 때)은 판정하지 않는다(19절). release는 상대를 모르는 대기를 한꺼번에 푼다(어느 PE를 기다리던 대기인지 장치는 모름).

(f) **반응 변수와 감지 변수** `[소스]`. gin-restore의 통합 정책 설계(9.1절 (f))에서 NVSHMEM의 정책은 fail-fast 하나이고(복원은 그 설계의 범위
밖, hold 정책의 프로세스는 NVSHMEM을 쓰지 않음), 이 계층의 `NVSHMEM_IBGDA_FT_T1_FIN_DEATH`, `NVSHMEM_IBGDA_FT_T1_FAILSTOP_MS`,
`NVSHMEM_IBGDA_FT_T1_FAILSTOP_CODE`는 그 fail-fast 반응의 변수다. GIN 쪽에서 같은 자리에 있는 것은 `NCCL_GIN_TS_DEGRADED_MS`, `NCCL_GIN_TS_DEGRADED_ROUNDS`
(fail-fast 반응)와 `NCCL_GIN_TS_QPWATCH_MS`, `NCCL_GIN_TS_QPWATCH_GRACE_MS`, `NCCL_GIN_TS_QPWATCH_NOCQE_MS`(감지, 두 정책에 같음)다. NVSHMEM에 hold를 넣는다면
`t1_decline` 맨 앞에 GIN의 거절 hook 같은 자리를 두는 것이 같은 구조다(이 실험의 범위 밖). `t1w` 코드는 바뀌지 않았다.

### 9.3 실행기

- [apprun.py](apprun.py): `../blind/blindrun.py`의 사본을 고친 것(원본은 그대로). 눈가림을 뺐고, 빌드 선택(`BUILDS`: `hk`, `hw`, `hr`, `hq`, `t1w`,
  t1_380), 셀의 환경 변수, 29000–30999 포트, 작업마다 시간 상한과 유예를 더했다. 셀은 자기 `wall_s`와 `grace_s`를 둘 수 있다(pilot 1 뒤 release 셀에 유예
  50 s). 에이전트는 blind-apps의 `node_agent.py`와 바이트 단위로 같은 사본(`~/gd-bundle/agent/`)이다. 시행 파일과 줄 형식은 blind-apps와 같다. 시행 목록은
  `apprun.py plan --seed <hex>`가 [cells.json](cells.json)에서 만든 [schedule.json](schedule.json)이고, 실행기는 그 파일의 `cells_sha256`이 지금의
  `cells.json`과 다르면 돌지 않는다. hold마다 두 노드의 번들 md5를 비교하는 파일 목록에 `hk` libnccl이 들어 있다.
- [cells_reg.sh](cells_reg.sh): gin-remaining의 `run_trial_hr.sh`, `run_mr_hr.sh`를 그 폴더에서 그대로 부른다(빌드는 인자, 드라이버 번들 `hr`). 셀 정의는
  gin-remaining의 `cells.sh`에서 옮겼고 새 셀(지연 감시 주기, M-A, M-C 둘, 응답 쪽 틈 `rm4_gap`, `rm4_gapx`, 정책 `rm4_kill3_hold`, `f4_mix_b`)을 더했다.
  응답 쪽 틈의 시각은 `GAP_F_MS`(4 000), `GAP_STALL`(8 000), `GAP_KILL_MS`(9 000)다.
- [hold.sh](hold.sh): 스냅숏, 남은 프로세스 기다림, STOP 규칙은 blind-apps와 gin-remaining의 hold와 같다. 회귀 셀은 빌드를 받아(`c <셀> [n] [시작] [빌드]`,
  기본 `hk`) `reg/<빌드>/`, `reg/mr_<빌드>/`에 둔다. [chain.sh](chain.sh): hold마다 `cluster_run.sh -w 10800 -t gd-<hold>` 안에서 `timeout -s KILL 880`.
  app hold에 결과 없는 시행이 남으면 같은 hold를 두 번까지 다시 돈다.

### 9.4 빌드 ([build_gd.sh](build_gd.sh), 세션 스크래치 `agent_gd`)

1. `gin-setup`: `agent_ts2hr`의 소스, `build/`, `build-hrp/`를 `agent_gd/gin`으로 복사(`build-hrp/`는 `build-hwp/`), 의존 파일과 장치 manifest의 경로를
   바꾸고 시각을 돌려준다. `hr` 작업 트리를 스크래치 저장소에 "gin-remaining hr" 커밋으로 남긴다. 복사 직후 `make -n`은 버전 표시 하나만 컴파일한다.
2. `gin-hw`, `gin-hwp`: 이 계층을 작업 트리에 두고 증분 빌드. 바뀐 파일은 `gin_host_gdaki.cc` 하나다.
3. `gin-app`: 예제(`main.cu`, `kernels.cuh` 그대로)와 `../blind/boot/gin_boot.cc`를 `hw` 헤더로 빌드 → `gd_gin_ring`.
4. `nvs-setup`: `agent_t1_380/src`를 `agent_gd/nvs/src`로 복사, t1_380 작업 트리를 "t1_380" 커밋으로 남기고, t1_380의 cmake 설정 그대로 새 빌드 디렉터리를
   만든다. `nvs-lib`: 계층을 두고 빌드(장치 헤더가 바뀌므로 전체 빌드, 약 15분), 설치.
5. `nvs-app`: `ring-reduce.cu`(그대로)를 `t1w` 설치로 빌드 → `gd_nvs_rr`, 부트스트랩 플러그인 → `gd_nvs_boot.so`.
6. `hk-setup`: `agent_gd/gin`의 소스와 두 빌드 디렉터리를 `agent_gd/gin_hk`로 복사(`hw_layer.diff` md5 `be0ea9ed`, 빌드 `efc48ca1`, `d3b4a2fe`인지 먼저 확인),
   경로를 바꾸고, `hw` 작업 트리를 "gpu-detect hw (libnccl efc48ca1)" 커밋으로 남긴다. `hw` 트리와 그 빌드는 그대로 둔다(pilot 1의 증거).
   `gin-hk`, `gin-hkp`: `hk_layer.diff`를 그 위에 두고 증분 빌드. 바뀐 파일은 같은 하나다. 장치 헤더가 같으므로 예제는 다시 빌드하지 않는다.
7. `info`: `agent_gd/out/build_info.txt`. [make_diff_gd.sh](make_diff_gd.sh): diff 셋을 쓰고, 기준 커밋을 복제한 곳에 다시 적용해 트리와 같은지 확인한다.
   `hk`는 `hr` 커밋에 `hw_layer.diff`와 `hk_layer.diff`를 차례로 적용한 결과도 확인한다(`make_diff_gd.sh hk`는 `hk`만).

재현: GIN은 순정 NCCL v2.32.3-1 + `../gpu-initiated/gin_recovery/remaining/gin_transparent_hr.diff` + `hw_layer.diff`(+ `hk_layer.diff`). NVSHMEM은
공식 v3.8.0-0 + `../gpu-initiated/nvshmem/nvshmem_ibgda_fault_inject.diff` + `../gpu-initiated/nvshmem_rootcause/nvshmem_nrc_proxy_sq_dbr.diff` +
`../gpu-initiated/nvshmem_ft/t1_380/nvshmem_ibgda_t1_380.diff` + `t1w_layer.diff`. 모든 컴파일은 nice 19, 유휴 I/O 우선순위다.

### 9.5 배포 ([deploy_gd.sh](deploy_gd.sh), 메인 세션)

첫 배포(2026-10-09 17:36, 모드 `first`)는 `~/gi-bundle/gin_ts2/hw/`와 `~/gd-bundle/{gin,nvs,nvs/lib,agent}/`를 두었다. 이제 기본 모드 `hk`는 두 노드의 새
디렉터리 `~/gi-bundle/gin_ts2/hk/`(libnccl과 링크)에만 쓴다. 그 디렉터리가 비어 있지 않으면 멈추고, 소스가 `WANT_HK`가 아니면 멈춘다. 읽기만 하는 대조
파일과 첫 배포의 파일(`hw` libnccl, `gd_gin_ring`, NVSHMEM 파일, 에이전트)이 두 노드에 기록된 md5로 있는지 확인한다. 배포 뒤 새 파일의 md5가 두 노드와
소스에서 같은지, `ldd`가 `hk/` 안의 libnccl을 찾는지, 기존 번들(`~/gi-bundle`의 `hk/` 밖, `~/blind-bundle`, `~/gd-bundle`)의 모든 파일 md5가 그대로인지
확인한다. 확인은 파일로만 받는다. GPU 프로그램도 RDMA 트래픽도 없다.

### 9.6 메인 세션의 명령(순서대로)

경로는 이 worktree 기준이다. `D=harness/gpu-detect`, `R=$D/results`, `S=<세션 스크래치>`(빌드 산출물이 있는 곳, 스크립트의 `SCR`).

1. **배포 전 확인**(읽기만, 1분 안): `md5sum $S/agent_gd/out/hk/libnccl.so.2.32.3`(12절의 `hk` 값), `ls -A ~/gi-bundle/gin_ts2/hk`와
   `ssh -n "$SUNNY_SSH" 'ls -A ~/gi-bundle/gin_ts2/hk'`(둘 다 없거나 비어 있어야 함), `git status --short`(작업 트리에 이 실험의 커밋 밖 변경 없음).
2. **배포**(약 1분): `bash $D/deploy_gd.sh $D/deploy_check_hk.txt hk`. 확인 파일에 "new files: rain == sunny (1 files)", "source == deployed:
   hk/libnccl.so.2.32.3", "first-deploy files on both nodes with their recorded md5: 7", 두 노드의 "gin hk: libnccl.so.2 => .../gi-bundle/gin_ts2/hk/
   libnccl.so.2", "existing bundles unchanged"가 있어야 한다. 확인 파일은 커밋한다.
3. **pilot 2**(약 7분, 나쁜 경우 10분, 채점 안 함): `bash $D/chain.sh $R/<날짜>_pilot2 P1 P2`.
4. **pilot 2 점검**(읽기만): `python3 $D/rows_gd.py $R/<날짜>_pilot2 --progress`, `python3 $D/rows_gd.py $R/<날짜>_pilot2 --out $S/gd_pilot2/trials_app.csv`,
   `cp -a $R/<날짜>_pilot2 $S/gd_pilot2/copy && python3 $D/score.py $S/gd_pilot2/copy`(pilot 폴더에는 쓰지 않는다). 볼 것:
   - `chain.out`의 두 hold 모두 rc=0, STOP 파일 없음, iptables 0 → 0, 새 mlx5 줄 0, 펌웨어 명령 실패 합 그대로.
   - P1: 10회 모두 장애가 걸리고 설정 확인 통과(`hk`의 `detect=1`, 정책 줄 `requested=failfast effective=failfast`, NIC 경로). `gin_qperr@hk` 투명, 감지
     100 ms 안, 복구 1 000 ms 안. 감시 끔은 멈춤, 1 ms와 100 ms는 투명. kill은 5 s 안 오류. 멈춤과 장애 없음은 투명, 감시 감지와 거절 없음.
     `gin_none@hk`의 `wq_lines` 2(정리 줄 고침). release 셀 둘은 해제 줄이 있고 하네스가 끝낸 PE가 없어야 함(유예 고침).
   - P2: `f1_b`, `f2rel_b`, 지연 셋, M-A(rank 3이 0, 1에 답함), M-C 둘이 pilot 1과 같은 모습이고 정책 줄이 있음. `rm4_gap@hw`: `gap_hit` 1,
     `gap_cause` unknown, `gap_resp_stuck` 1, `gap_others_rel23` 2. `rm4_gap@hk`: `gap_hit` 1, `gap_cause` peer-dead, `gap_lac` 1, `gap_n_rel23` 3,
     `gap_stuck` 0. `rm4_gapx@hk`: `gap_exit_line` 1, `gap_rc_x` 73과 같은 모습. `rm4_kill3_hold@hk`: `hold_warn_ranks` 4, `pol_eff_ff` 1, RG9의 열.
     `f4_mix_b@hk`: `mix_warn_ranks` 2, `pol_agreed_min` 0, RG3의 열. 새 셀의 상태가 모두 판정 가능(`cond_window_gap`, `config_policy` 없음).
5. **pilot 2 뒤**: 고친 것을 12절에 적고(3절 규칙), 셀을 바꿨다면 `python3 $D/apprun.py plan --seed $(od -An -N8 -tx8 /dev/urandom | tr -d ' \n')`로
   `schedule.json`을 다시 만든다. 응답 쪽 틈 셀이 창을 맞히지 못하면 `GAP_KILL_MS`나 `GAP_STALL`을 한 번 바꾼다(8절).
6. **사전 등록**: `cd $D && { echo "gpu-detect pre-registration"; for f in predictions.csv cells.json schedule.json apprun.py rows_gd.py score.py cells_reg.sh hold.sh chain.sh hw_layer.diff hk_layer.diff t1w_layer.diff; do echo "$f sha256 $(sha256sum < $f | cut -c1-64)"; done; } > PREREG.txt`.
   상태 `PREREGISTERED`, 12절 기록과 함께 커밋 하나, 그 커밋에 `prereg/gpu-detect-v1`.
7. **본 실행**(약 60분, 나쁜 경우 75분): `bash $D/chain.sh $R/<날짜> G1 G2 N1 N2 R1 R2 R3 R4`.
8. **채점**: `python3 $D/score.py $R/<날짜>` → `SCORE.md`, `trials_scored.csv`. 원자료는 Release에 올린다.

### 9.7 출력

- app 시행: `results/<날짜>/raw/<id>/{r0.log,r1.log,a0.log,a1.log,trial.meta}`(줄마다 rain 수신 시각). 회귀: `results/<날짜>/reg/<빌드>/`,
  `reg/mr_<빌드>/`(gin-remaining 실행기의 파일, 빌드 `hk`와 대조의 `hw`). hold마다 스냅숏, `runner.log`, `chain.out`, `hold_*.out`. 원자료는 커밋하지 않고
  Release에 올린다.

## 10. 완료 조건과 QA 기준

- [x] pilot(P1, P2)을 돌리고 12절에 적은 뒤 고칠 것을 고치고 태그를 달았다(pilot 1 `hw`, pilot 2 `hk`). 태그는 사전 등록 커밋 `1891614e`에 있다(12절).
- [x] 모든 셀이 계획한 반복 수만큼 실행됐다. 제외를 셀마다 따로 센 표가 있다(`SCORE.md` 끝 표). 시행 248, 제외 0.
- [x] 예측 41줄마다 판정(맞음, 틀림, 자료 부족)과 조건을 만족하지 않은 시행 목록이 있다([SCORE.md](results/20261009/SCORE.md)).
- [x] 다른 에이전트가 `score.py`를 보지 않고 원자료에서 핵심 수치를 다시 셌다(결과 분류, 감지 지연, FIN 판정과 종료 시각, 지연 중앙값, 회귀 판정)
  ([qa_recount.md](results/20261009/qa_recount.md)).
- [x] 다른 에이전트가 두 계층을 읽고 리뷰했다(12절).
- [x] 다른 에이전트가 실행기와 채점기를 리뷰했다([qa/code_review.md](qa/code_review.md)).
- [x] pilot과 제외 시행이 결과에 섞이지 않았다(pilot은 다른 결과 폴더, 본 실행 폴더의 시행 파일은 모두 태그 뒤에 생김, 제외 0).
- [x] 새 빌드의 md5, diff 셋, 재적용 확인을 5절과 12절에 적었다.
- [x] 다른 에이전트가 정책 hook과 응답 쪽 틈의 고침을 충돌 표와 함께 리뷰했다(12절).
- [x] 원자료를 Release에 올리고 `DATA.md`에 적었다(`data-20261009`, 14절).
- [x] hold 전후 mlx5 스냅숏에 새 명령 오류가 없었고, iptables 규칙이 늘지 않았고, CUDA 메모리 오류가 없었다(여덟 hold, 12절).

## 11. 작업 체크리스트

- [x] blind-apps 원자료에서 기준 수치를 다시 셈(1절)
- [x] GIN 계층(감시, M-A, L-C, M-C), 빌드 `hw`, `hwp`, 예제 `gd_gin_ring`
- [x] NVSHMEM 계층(작별과 FIN 판정, fail-stop, 장치 대기 단어), 빌드 `t1w`, 예제 `gd_nvs_rr`
- [x] 두 diff와 재적용 확인
- [x] 실행기, 셀, hold, chain, 배포, 파서, 채점기, 예측 초안
- [x] 채점기 합성 시험(실제 측정 아님, 12절)
- [x] 독립 리뷰(두 계층)와 반영(12절)
- [x] 질문, 가설, 셀, 예측 초안 (`DRAFT`)
- [x] 배포(메인 세션, `hw`와 `t1w`)
- [x] pilot P1, P2(메인 세션, 채점 안 함)
- [x] pilot 1 점검(12절)
- [x] 응답 쪽 틈의 충돌 표(9.1절 (g), 구현 전)
- [x] 정책 hook, 응답 쪽 틈의 고침, 빌드 `hk`, `hkp`, 독립 충돌 리뷰(두 번, 마지막 판정 "열린 충돌 없음")
- [x] 하네스, 예측(41줄), `schedule.json`(시드 `f739ae41811c2212`), 채점기 합성 시험
- [x] 배포 `hk`, pilot 2(메인 세션), 점검(12절)
- [x] 태그 전 고침: GC1, GC2, GD5, H1의 반증 문장, 열 셋(12절)
- [x] 고정 절 완성, 상태 `PREREGISTERED`, 해시 기록을 커밋 하나로(태그 `prereg/gpu-detect-v1`은 메인 세션이 그 커밋에 단다)
- [x] 본 실행 G1–R3 (`RUNNING`). 실제로는 R4까지 돌았다(G1–R4, 21:35:03–22:20:41, 12절, 13절)
- [x] 채점 (`QA`), 독립 재계산과 측정 코드 리뷰
- [x] 결과 정리, 원자료 Release(`data-20261009`). PR은 메인 세션이 연다
- [x] 결론 확정 (`COMPLETE`)

## 12. 실행 기록 (시간순)

| 시각 | 무엇을 했나 | 결과와 근거(경로, 커밋, 실행 ID) |
|---|---|---|
| 2026-10-09 | worktree `~/rdma-error-wt/gpu-detect`(`exp/gpu-detect`)를 master `02a640aa`(blind-apps, gin-remaining이 합쳐진 뒤)로 fast-forward. blind-apps의 `qa/root_cause.md`, `qa/code_review.md`, `results/20261009/qa_recount.md`, gin-remaining 9.1절과 리뷰를 읽음 | `[소스]` 1, 4절의 근거 |
| 2026-10-09 | blind-apps Release 자산을 세션 스크래치(`gd_selftest/`)에 풀어 `rows_gd.py`의 정규식으로 다시 셈: GIN QP 오류 16회 중 멈춤 14(훅 8–104 ms), 투명 2(114, 115 ms); NVSHMEM kill 유효 7(제외 1) 모두 멈춤, FIN 0.03–0.48 ms 뒤, DECLINE 0; 원격 접근 회수 8회 모두 멈춤, 두 PE 거절 8/8, 첫 DECLINE 4.9–7.6 ms 뒤 | `[측정]` 1절 |
| 2026-10-09 | 스크래치 준비: `build_gd.sh gin-setup`(`agent_ts2hr` 확인 후 복사, "gin-remaining hr" 커밋 `382bbb4`, 복사 직후 `make -n` 컴파일 1개), `nvs-setup`(`agent_t1_380/src` 복사, "t1_380" 커밋 `67ac5bb`, 9개 파일, cmake 3.1 s) | `[측정]` |
| 2026-10-09 | 메인 세션의 추가 지시: gin-remaining 리뷰의 M-A, L-C, M-C를 같은 GIN 계층에 넣을 것(셀이나 회귀 확인을 함께, M-C가 크거나 위험하면 문서로) | 9.1절 (b)–(d), 7절 |
| 2026-10-09 | 계층 구현(9.1, 9.2절), 실행기와 채점기, 예측 초안 | 이 폴더 |
| 2026-10-09 | 첫 빌드(리뷰 전): `hw`, `hwp` 경고 0, `gd_gin_ring`; `t1w` 전체 빌드 14분 30초, 경고는 nvcc의 오래된 아키텍처 안내 3줄(t1_380 빌드와 같은 수); `gd_nvs_rr`, `gd_nvs_boot.so` `e3264e83`(blind-apps의 `blind_nvs_boot.so`와 같은 md5) | `[측정]` 스크래치 `agent_gd/*.log`, `agent_gd/nvs/build_lib.log` |
| 2026-10-09 | 채점기 합성 시험(측정 아님): blind-apps와 gin-remaining 본 실행의 실제 시행을 이 실험의 폴더 꼴로 옮기고 빌드 이름과 `hw`, `t1w` 시작 줄, 감시와 복구 줄 몇 개를 붙인 폴더(스크래치 `gd_selftest/res`, 만든 스크립트 `gd_selftest/make_synth.py`)로 `rows_gd.py`와 `score.py`를 돌림. 예외 없이 35줄을 모두 평가했고, 붙인 줄에서 나온 열이 기대값과 같았다(`det_by` watch, `det_ms` 12.0, `rec_ms` 15.0, `n_bye_sent` 2, `lb_shadow` 4). 실제 시행에서 나온 열도 blind-apps와 같은 결과 분류를 냈다(GIN QP 오류 첫 6회 중 멈춤 4, NVSHMEM kill 유효 5 모두 멈춤, 장애 없는 NVSHMEM 6회 투명). gin-remaining 시행의 RG3, RG5, RG7 판정식이 돌아 맞음 | `[측정: 채점기 동작만]` |
| 2026-10-09 | `apprun.py plan --seed 2255c64c3f6cd621`: P1 14, G1 32, G2 36, N1 34, N2 28. 셀마다 대상 rank와 `u_t`를 뽑음. 클러스터 없이 셀마다 rank 환경과 경로를 확인(리뷰 반영 뒤 새 시드로 다시 만듦, 아래) | 스크래치 |
| 2026-10-09 | 리뷰 전에 더한 규칙: 감시는 이번 incarnation에 예약한 WQE가 없는 ERR QP에 기록을 만들지 않음(9.1절 (a)). 시험 훅이 문맥 하나의 모든 상대 QP를 옮기는 랭크 4개 셀에서 쓰지 않는 QP마다 라운드가 더 생기는 것을 막으려고 | `[소스]` |
| 2026-10-09 | 독립 리뷰(다른 에이전트, 읽기만, 두 계층, 리뷰 도중 바뀐 트리도 읽음). 판정 "고치면 실행 가능", 막는 결함 없음. 높음 2: H1 diff가 마지막 빌드(쓰지 않은 QP 규칙)와 다르고 `hwp`가 낡음, H2 장애 없는 NVSHMEM 예측(NF2)이 "두 PE 모두 작별"을 요구하나 둘째 PE는 첫 PE의 작별과 FIN을 읽은 뒤라 보낼 곳이 없음. 중간 5: M1 감시를 펌웨어 단계로 묶어 SIGSTOP 직후 건강한 쌍이 풀릴 수 있음, M2 응답 쪽 오류(CQE 없음)를 LOCAL_QP_ERR로 복구하려 함, M3 M-C 기본 규칙이 shrink 넘김을 막음, M4 펌웨어 명령 부하, M5 release kill 셀의 정리와 출력 양. 낮음 11, 사소 2. 맞다고 확인: M-A의 반환, 중복 제거(에폭, `handled`, 큐), 잠금 순서, CQ 창과 분류가 `q4Report`와 같음, 자체 시험의 shadow 비교, BYE와 FIN 처리, `_exit` 경로, 호출 위치 분류, 대조 번들의 일관성 | 리뷰 보고는 이 세션의 에이전트 응답(파일 없음) |
| 2026-10-09 | 리뷰 반영. GIN: M1 감시의 펌웨어 단계 묶음 뺌, M2 뿌리 CQE가 없으면 50 ms 기다림(`NCCL_GIN_TS_QPWATCH_NOCQE_MS`), L1 기록 전후 heartbeat, 쓰지 않은 QP 규칙과 `ncclGinFaultQuery`의 범위를 주석과 9.1절에, 사소 둘(링 CQ만, 큰 CQ는 `unread`)을 주석에. NVSHMEM: L4 `NVSHMEMI_STATIC`, L5 깃발 `T1W`로 칸 읽기를 막음, L7 FIN을 엿보기 전에 버퍼의 BYE를 찾음, L8과 L9 fail-stop 줄을 `write(2)`와 저장한 PE 번호로. 하네스: H2 NF2를 "적어도 한 PE의 작별"로, M5 release 셀의 시간 상한 60 s(`cells.json`, `apprun.py`), GD2와 GD4의 감지 한도를 50 ms 기다림에 맞춰 100 ms, 70 ms, 200 ms로, 열 `det_src`. 문서로만 둔 것: M3(9.1절 (d)), M4(9.1절 (a), 8절), L3(9.1절 (c)), L6(19절), L10(9.2절 (c)), L9의 종료 코드(9.2절 (e)), 낮음 11의 둘째(훅이 펌웨어 명령에 갇히면 쉬는 helper도 `opMu`에서 기다림: 연구 빌드의 훅만) | `hw_layer.diff`, `t1w_layer.diff` |
| 2026-10-09 17:33 | 리뷰 반영 뒤 마지막 빌드: `hw` `efc48ca1`, `hwp` `d3b4a2fe`(둘 다 경고 0), `t1w` 전송 모듈 `86c39e91`, 호스트 `f3522de8`(전체 빌드 14분 25초, 경고는 nvcc의 아키텍처 안내뿐), `gd_nvs_rr` `6e93ba59`. `gd_gin_ring` `719dfaab`는 다시 빌드하지 않음(헤더가 같다). `make_diff_gd.sh`: `hw_layer.diff` md5 `be0ea9ed`(546줄, 파일 하나 +358/−39), `t1w_layer.diff` `ac24448b`(427줄, 파일 셋), 둘 다 VERIFIED. 기대 md5는 [deploy_gd.sh](deploy_gd.sh)에. 채점기 합성 시험을 다시 돌려 35줄 모두 평가됨. `schedule.json`을 새 시드 `677fa4700b478c9c`로 다시 만듦(셀 파일이 바뀜) | `[측정]` 스크래치 `agent_gd/out/build_info.txt` |
| 2026-10-09 | 초안까지 클러스터에서는 아무것도 돌리지 않았다(배포, pilot, 본 실행은 메인 세션). rain에서는 컴파일, 정적 확인, 합성 채점 시험만 | 이 커밋 |
| 2026-10-09 17:36–17:37 | 메인 세션이 배포(`deploy_gd.sh`): 빌드 `hw`(libnccl `efc48ca1`, `hw_layer.diff` md5 `be0ea9ed`), `gd_gin_ring` `719dfaab`, `t1w`(전송 모듈 `86c39e91`, 호스트 `f3522de8`), `gd_nvs_rr` `6e93ba59`를 두 노드의 새 디렉터리 `~/gi-bundle/gin_ts2/hw/`, `~/gd-bundle/`에 둠 | `[측정]` [deploy_check.txt](deploy_check.txt): "new files: rain == sunny (11 files)", 파일 11개 모두 "source == deployed", ldd가 번들 안의 libnccl과 libnvshmem_host를 찾음, "existing bundles unchanged (rain 311 files, sunny 363 files)" |
| 2026-10-09 17:37–17:41:41 | 메인 세션이 pilot P1(app 14회), P2(회귀와 지연 8회)를 `chain.sh`로 돌림. 채점하지 않음. 빌드 `hw` `efc48ca1`과 `t1w`에 묶인 증거다 | `[측정]` `results/20261009_pilot/`(커밋 안 함, 원자료는 Release 예정). `chain.out`: P1 17:37:10–17:39:44, P2 17:39:44–17:41:41, 두 hold 모두 rc=0, iptables 규칙(gin-, blind-) 0 → 0. 네 스냅숏 모두 새 mlx5 줄 0, rain 펌웨어 명령 실패 합 31 → 31, 남은 프로세스 0, STOP 파일 없음 |
| 2026-10-09 | 사용자 결정으로 보류. 이 실험의 fail-fast 반응(NVSHMEM fail-stop, GIN degraded 해제와 `NCCL_GIN_TS_DEGRADED_ROUNDS=0`, QP 감시에서 라운드나 거절로 가는 길)이 병렬 실험 gin-restore의 설계(대기를 붙잡고 예비 프로세스로 죽은 rank를 되살림)와 충돌했다. 규칙: 설계 충돌이 남아 있는 동안 아무것도 구현하지 않는다 | 사용자 지시(2026-10-09). 보류 동안 pilot을 검토하지 않았고 빌드도 하지 않았다 |
| 2026-10-09 | 통합 정책 설계 `DESIGN_POLICY.md`(gin-restore worktree `harness/gpu-initiated/gin_recovery/restore/`, 이 실험은 읽기만): 감지는 두 정책에 공통, 반응은 communicator마다의 정책(기본 fail-fast). 그 문서의 독립 검토 마지막 판정은 "복원 계층 안의 막는 문제 넷 밖에 풀리지 않은 충돌 없음". 사용자 승인: GIN 계층에 정책 hook 아홉(G1–G9)을 넣고, 응답 쪽 틈을 고치고, pilot을 다시 돈 뒤 사전 등록하고 실행한다. 사용자가 정한 복원 계층의 키 읽기 자리(B4 (나))는 복원 계층의 일이라 이 실험의 장치 코드는 바뀌지 않는다 | `DESIGN_POLICY.md` 2, 3, 4.10절 `[소스]` |
| 2026-10-09 | pilot 1 점검(채점 안 함). `rows_gd.py`의 출력은 세션 스크래치 `gd_pilot1/trials_app.csv`로, `score.py`는 pilot 폴더의 사본 `gd_pilot1/copy`에 돌렸다. pilot 폴더에는 아무것도 쓰지 않았다. P1 14회 모두 장애가 걸렸고(시작 실패 0), 설정 확인을 통과했다(`hw` 시작 줄과 셀의 감시 주기, NIC 경로의 QP 구조 비교 4개, `t1w` 줄과 셀의 `failstop_ms`) | `[측정, 셀마다 1–2회]` |
| 2026-10-09 | pilot 1, GIN. QP 오류 `hw` 2회: 투명, 대상 rank에서 감시가 먼저 감지(분류 출처 CQ) 훅 뒤 11.9, 14.9 ms, 복구 줄 23.2, 27.1 ms. 감시 100 ms 1회: 투명, 105.3 ms, 116.6 ms. `hr` 1회: 시간 상한까지 멈춤, 감지 줄 없음. 장애 없음 1회와 멈춤 4.9 s 1회: 투명, 감시 감지, 거절, 죽음 줄 없음. kill 1회: 살아남은 rank의 첫 오류 줄 0.000 s(FIN으로 죽음 판정, 랭크 2개라 대기가 바로 풀림), 그 뒤 예제가 다음 단계에 머물러 하네스 유예로 끝남(blind-apps와 같은 모습, 예측 GR1이 허용) | `[측정]` 위 파일 |
| 2026-10-09 | pilot 1, NVSHMEM. kill 1회: FIN 판정 kill 뒤 0.1 ms, 살아남은 PE 종료 코드 70, kill 뒤 0.096 s. 원격 접근 회수 1회: 두 PE 종료 코드 70, 0.102 s. 장애 없음 1회: 투명, 작별 보냄 1, 받음 1, 떠남 1, 거절과 FIN 판정 0. PE 0 멈춤 4.9 s 1회, QP 오류 1회: 투명(QP 오류는 복구 줄 2). release 셀 2회: 해제 줄은 있으나(1, 2) 결과 분류가 HUNG. 살아남은 PE가 틀린 원소 줄을 찍는 중에 하네스 유예(첫 프로세스가 끝난 뒤 10 s)로 끝났다. kill 셀은 kill 뒤 10.2 s에 PE 1이 16 049 814줄(에이전트가 센 수), 원격 접근 셀은 PE 0이 8 388 408줄 뒤 스스로 0으로 끝나고 PE 1이 24 337 704줄에서 끊김. 원소는 세 크기 합 29 360 128개, 관측 속도 약 1.5M줄/s라 끝까지 약 20 s | `[측정]` 에이전트 줄 `AGENT suppressed name=validation count=...`. 원소 수는 `[소스: ring-reduce 16M, 32M, 64M int]` |
| 2026-10-09 | pilot 1, 회귀(P2). `f1_b`: 투명, 통계 API 라운드 1 복구 1(두 rank). `f2rel_b`: rank 0 거절(REM_ACCESS), rank 1 장치 오류로 대기 해제, 정리 762 ms. 4 KiB 지연 p50: 감시 끔 10.91, 1 ms 10.50, 10 ms 10.50 µs(각 1회). 감시의 QUERY_QP(두 rank 합) 0, 2 136, 260번, 평균 53–68 µs, 최대 93 µs. M-A 셀: rank 3이 rank 0, 1의 REQ에 기다림 안에서 답함, 라운드 퍼짐 4.2 ms, 투명. M-C 기본 규칙: 쌍 0-1 거절 1, 복구 0. M-C 대조(`=1`): 복구 1, 거절 0. 두 M-C 셀 모두 발화와 kill이 트래픽 안 | `[측정]` 사본의 `trials_scored.csv` |
| 2026-10-09 | pilot 1에서 찾은 결함(태그 전, 3절 규칙). (1) 셀 조건: release 셀은 60 s 상한만 두고 유예는 두지 않아, 유예 10 s가 살아남은 PE를 끊었다 → 셀마다 `grace_s`를 두고 release 셀은 50 s(`cells.json`, `apprun.py`). (2) 구현: GIN app 7회 모두 정리 때 감시 줄이 없어 `wq_*` 열이 비었다(9.1절 (h)) → 새 빌드에서 고침. 판정식은 이 열을 쓰지 않는다. (3) 문서: 9.6절 2번의 "nvs_none의 두 PE가 작별을 보냄"은 리뷰 H2 뒤의 예측(적어도 한 PE)과 어긋남 → 고침. 설명용 관찰: 4 KiB 지연의 감시 10 ms와 끔의 차이 0.41 µs(예측 LT1 한도 0.40)이나 느린 쪽이 감시 끔이고 각 1회라 예측은 바꾸지 않는다. 걸린 시간: P1 2분 34초(어림 4분), P2 1분 57초(어림 3분) | 고친 것은 아래 줄 |
| 2026-10-09 | 응답 쪽 틈의 충돌 표와 정책 hook 계획을 구현 전에 9.1절 (f)–(h)에 씀. 고침이 닿는 기존 장치 20줄 모두 충돌 없음(해결과 근거 열). 줄 번호는 `hw` 트리에서 다시 확인 | 9.1절 `[소스]` |
| 2026-10-09 | 구현(빌드 `hk`): `build_gd.sh hk-setup`으로 `hw` 트리를 `agent_gd/gin_hk`에 복사("gpu-detect hw (libnccl efc48ca1)" 커밋 `acd1fcd`, 복사 직후 `make -n` 컴파일 1개; `hw` 트리는 그대로 `be0ea9ed`, `efc48ca1`). 그 위에 정책 hook 아홉, 응답 쪽 Commit 뒤 손실의 판정과 깃발 `pe.lostAfterCommit`, 시험 스위치 `NCCL_GIN_TS_TEST_EXIT_AFTER_ACK`, 정리 줄(9.1절 (f)–(h)) | `[소스]` 스크래치 `agent_gd/gin_hk` |
| 2026-10-09 | 첫 빌드: `hk` `7ed2c8e8`, `hkp` `9f4a9d40`(둘 다 경고 0, 운영 빌드에 시험 스위치 문자열 없음), `hk_layer.diff` 457줄 `c76a4b97` 재적용 확인 | `[측정]` 스크래치 `agent_gd/gin_hk_build.log` |
| 2026-10-09 | 독립 충돌 리뷰 1(다른 에이전트, 읽기만; diff, `DESIGN_POLICY.md`, 충돌 표만 받음). 판정 "열린 충돌 1". 높음 1: ACK 보내기 실패 자리에서 받는 쪽을 엿보는 판정이 reset과 시간 초과를 FIN으로 읽음(실패한 보내기가 소켓 오류를 가져가고 받는 쪽은 닫혀 있어 엿보기가 0을 돌려줌). 산 시작 쪽이 Commit 창에서 라운드를 취소하며 보내는 reset(`gdakiTsMakeUnknown`의 SO_LINGER 0)이 그 길로 죽음 판정이 되어 degraded와 PeerDead 책임이 생길 수 있음. 중간 1: 충돌 표의 두 줄이 그 자리에 대해 틀렸고, 보내기 실패의 원인 칸(`gdakiTsSend`는 원인을 쓰지 않음)과 닫을 때의 reset 두 줄이 빠짐. 낮음 1: 깃발을 `gdakiTsMakeUnknown`에서도 지움(설계는 REJOIN뿐). 사소: 줄 번호 셋, WARN과 시험 스위치는 문맥마다, 고아였다 끝난 helper의 정리 줄. 맞다고 확인: hook 아홉의 자리와 fail-fast 동치(G7은 같은 QUERY_QP 하나), all-gather 레코드(48 → 56 B, 초기화, 같은 stride끼리 비교), 잠금 순서, DONE 기다림의 판정, 두 번 거절 없음, 운영 빌드에서 시험 스위치가 불가능함(문자열과 `_exit` 없음) | 리뷰 보고는 이 세션의 에이전트 응답(파일 없음). 받은 것: 스크래치 `gd_review/hk_layer.diff`, `gd_review/conflict_table.md` |
| 2026-10-09 | 리뷰 1 반영: ACK 자리는 판정하지 않고 errno를 원인 칸에 이름으로 남긴 뒤 `hw`처럼 거절(깃발은 맨 먼저), 판정은 DONE 기다림만. 깃발은 `gdakiTsInstall`에서만 지움(gin-restore 설계의 계약 문단과 맞음: REJOIN이 그것으로 설치). 충돌 표 고침과 두 줄 추가, 사소한 것은 9.1절 (f)–(h)에 적음. 응답 쪽의 다른 출구에 깃발을 세우는 것(설계에서 선택)은 하지 않음 | 9.1절 (g) |
| 2026-10-09 | 다시 빌드: `hk` `2913c777aa0b05d4d566c9f7638c6a0e`, `hkp` `84209c03a497bd28206210205bfc6cf5`(둘 다 경고 0, `hkp`에 시험 스위치 문자열 0), include digest `a27dac89`가 `hw`와 같아 `gd_gin_ring`은 다시 빌드하지 않음. `make_diff_gd.sh`: `hk_layer.diff` 460줄 md5 `c5222c55`, "gpu-detect hw" 커밋에 다시 적용되고, `hr` 커밋에 `hw_layer.diff`와 차례로 적용해도 `hk` 트리와 같음. `hw_layer.diff` `be0ea9ed`, `t1w_layer.diff` `ac24448b`는 그대로 | `[측정]` 스크래치 `agent_gd/gin_hk_build2.log`, `agent_gd/out/build_info.txt` |
| 2026-10-09 | 독립 충돌 리뷰 2(같은 에이전트, 읽기만; 고친 diff `c5222c55`, 고친 충돌 표, gin-restore 설계의 깃발 계약 문단). 판정 "열린 충돌 없음". 확인: ACK 자리는 깃발과 원인 문자열 밖에는 `hw`와 글자 그대로 같고 그 문자열은 거절된 상대에게 다시 읽히지 않음, DONE 기다림의 판정은 그대로 맞음, 시작 쪽이 Commit 창에서 보낸 reset은 두 자리 모두 `hw`의 거절, 계약(깃발을 맨 먼저, errno를 먼저 원인 칸에)과 맞음, 1판과 2판 사이에 다른 동작 변화 없음, `gdakiTsMakeUnknown`의 지움을 뺀 것은 효과 없음, 고친 표의 줄과 줄 번호 맞음, 운영 빌드에서 시험 스위치 불가능. 사소 셋(막지 않음): 표의 "send failed" 문구, 복원 계층의 REJOIN에 대한 문장은 `[미확인]`이고 `gdakiTsInstall`은 `lostCause`를 지우지 않음, 빌드 기록에 `hk` 값을 넣을 것. 앞의 둘은 표에 반영, 셋째는 이미 `build_info.txt`(21:14)에 있음 | 리뷰 보고는 이 세션의 에이전트 응답(파일 없음). 받은 것: 스크래치 `gd_review/hk_layer_v2.diff`, `gd_review/conflict_table_v2.md` |
| 2026-10-09 | 하네스: `apprun.py`(빌드 `hk`, 셀마다 `grace_s`, md5 목록), `cells.json`(GIN app 셀을 `hk`로, release 셀 유예 50 s, P1을 pilot 2용 10회로), `cells_reg.sh`(새 셀 넷), `hold.sh`(빌드 인자, `reg/<빌드>/`, P2를 pilot 2용 13회로, 새 hold R4), `rows_gd.py`(정책 열, 응답 쪽 틈 열, 정리 줄 수, `hk` 설정 확인), `score.py`(계획 수, 새 셀의 상태 규칙, 정책 확인), `predictions.csv`(셀 키를 `@hk`로, 새 줄 여섯: GP1–GP3, PH1, PH2, WT1, 모두 41줄), `deploy_gd.sh`(모드 `hk`: 새 디렉터리 `~/gi-bundle/gin_ts2/hk/`만) | 커밋 `e17a7e7a`, `25f51c2a`, `9981506f`와 이 줄의 커밋 |
| 2026-10-09 | `apprun.py plan --seed f739ae41811c2212`: P1 10, G1 32, G2 36, N1 34, N2 28(release 항목 12개 모두 유예 50 s). 클러스터 없이 140개 항목의 빌드 경로와 rank 환경을 확인 | 스크래치 |
| 2026-10-09 | 채점기 합성 시험(측정 아님): 스크래치 `gd_selftest/make_synth2.py`가 gin-remaining과 blind-apps 본 실행의 실제 시행을 `hk` 꼴로 옮기고 정책 줄, 응답 쪽 틈의 줄과 kv 값(대조는 rank 0의 판정을 지우고 받기를 풀리지 않게), 정리 줄을 붙인 폴더(`gd_selftest/res2`). 41줄 모두 예외 없이 평가, 새 여섯 줄은 맞음(그 자료를 그렇게 만들었음), 나머지는 합성 자료가 없어 자료 부족. 반대 방향: 고친 빌드의 GP1 조건은 대조 시행 3회 모두에서 거짓, 대조의 GP2 조건은 고친 시행 5회 모두에서 거짓. 새 셀의 상태는 모두 판정 가능 | `[측정: 채점기 동작만]` |
| 2026-10-09 | 메인 세션이 `hk`를 배포(`deploy_gd.sh ... hk`): "new files: rain == sunny (1 files)", "source == deployed: hk/libnccl.so.2.32.3", 첫 배포의 파일 7개가 두 노드에 기록된 md5로 있음, 두 노드에서 `ldd`가 `hk/` 안의 libnccl을 찾음, "existing bundles unchanged (rain 322 files, sunny 374 files)" | `[측정]` [deploy_check_hk.txt](deploy_check_hk.txt), 커밋 `5262bbb1` |
| 2026-10-09 21:19:34–21:24:57 | 메인 세션이 pilot 2(`chain.sh $R/20261009_pilot2 P1 P2`)를 돌림. 채점하지 않음. P1 21:19:34–21:21:25(1분 51초, 어림 3분), P2 21:21:25–21:24:57(3분 32초, 어림 4분), 두 hold 모두 첫 회에 rc=0, iptables 규칙 0 → 0, 새 mlx5 줄 0, rain 펌웨어 명령 실패 합 31 → 31, STOP 파일 없음, 남은 프로세스 0 | `[측정]` `results/20261009_pilot2/`(커밋 안 함). 읽기는 사본 스크래치 `gd_pilot2b/` |
| 2026-10-09 | pilot 2 점검, app(셀마다 1–2회, 모두 장애 걸림, 설정 확인 통과, 정책 줄 두 rank). `hk` QP 오류 2회 투명: 대상 rank의 감시가 먼저 감지, 56.7 ms(뿌리 CQE 없음: 50 ms 기다림), 8.3 ms(CQ), 복구 68.0, 19.4 ms. 감시 1 ms: 4.5 ms, 16.5 ms. 100 ms: 94.3 ms, 105.8 ms. 감시 끔(훅 11 ms): 투명. 감시 감지 없이 rank 1(대상 아님)의 장치 경로가 RETRY_EXC를 훅 뒤 3.757 s에 분류하고 라운드를 열어 3.767 s에 복구(rain 수신 시각). kill: 첫 오류 줄 0.000 s, 하네스 유예로 끝남(pilot 1과 같음). 멈춤 3.0 s, 장애 없음: 투명, 감시 감지와 거절 없음, 장애 없음의 정리 줄 2(QUERY_QP 120번, 평균 69 µs, 최대 95 µs). release 둘: 하네스가 끝낸 PE 0. kill 셀은 살아남은 PE가 kill 뒤 16.07 s에 종료 코드 0(틀린 원소 25 165 822줄), 원격 접근 셀은 두 PE가 10.4 s 안에 종료 코드 0(16 777 215줄) | `[측정]` 사본의 `trials_scored.csv` |
| 2026-10-09 | pilot 2 점검, 회귀(각 1회, `hk`, 정책 줄이 모든 rank에 있고 셀이 요청한 값). `f1_b` 투명, 통계 라운드 1 복구 1. `f2rel_b` pilot 1과 같음(정리 763 ms). 4 KiB 지연 p50: 감시 끔, 1 ms, 10 ms 모두 10.50 µs. M-A: rank 3이 0, 1에 기다림 안에서 답함, 퍼짐 13.5 ms, 투명. M-C 기본: 쌍 0-1 거절 1, 복구 0. M-C `=1`: 복구 1, 거절 0. 응답 쪽 틈 `hw`(대조): rank 0이 원인 unknown으로 거절, 판정 없음, 15 s 유예 뒤에도 커널이 돌아 종료 코드 3(시행 25.5 s), rank 1, 2는 판정 뒤 2 007.7, 2 009.8 ms에 풀림. `hk`: rank 0이 Commit 뒤 손실 줄 1과 판정, 원인 peer-dead, 세 생존 rank가 판정 뒤 2 012.8, 2 009.6, 2 011.1 ms에 풀림, 멈춘 커널 0. ACK 뒤 종료: rank 3의 종료 줄 1, 종료 코드 73, 2 011.7, 2 009.0, 2 012.9 ms. hold 요청: hold WARN이 네 rank에 하나씩, 모두 effective fail-fast, 2 010.0, 2 007.4, 2 011.5 ms, 생존 rank 보내기 6/6. 정책 불일치: agreed 0, 두 rank에 불일치 WARN 하나씩, rank 0이 kill 뒤 1.5 ms에 peer-dead로 거절 | `[측정]` 같은 파일 |
| 2026-10-09 | pilot 2의 시행마다 그 셀 예측의 시행 조건(`count()` 안의 식)을 채점기의 평가 함수로 따짐: GD1–GD4, GR1, GF1, GF2, NR1, RG1, RG5, RG7, MA1, MC1, MC2, GP1–GP3, PH1, PH2, LC1, WT1의 조건이 해당 시행 모두에서 참. 거짓은 감시 끔의 GC2 하나(멈춤을 요구했으나 늦게 복구). 중앙값 예측(GD5, LT1, LT3)은 값만 위에 적음. 모든 시행의 상태가 판정 가능(제외 없음) | `[측정: 채점기 동작]` |
| 2026-10-09 | 태그 전 고침(3절 규칙) 1: GC2, GC1, H1의 반증 문장. 대조의 목적은 "감시 없이는 아무것도 장애를 빨리 감지하지 못한다"인데 문장이 "멈춤"으로 적혀 있어, 감시가 없어도 앱의 CQ를 읽는 호출이 상대의 RETRY_EXC(약 3.6 s)를 읽어 늦게 복구하는 기존 길(H1이 말하는 호출 안의 감지)을 반례로 셌다. 새 조건: 감시 감지 없음, 어느 rank도 훅 뒤 100 ms 안에 감지하지 않음, 1 000 ms 안에 복구하지 않음(GD2, GD3의 한도). GC2는 N − 1 그대로, GC1은 N − 2에서 N − 1로(N − 2는 늦은 복구 둘을 실패로 세던 여유였고 새 조건은 그것을 길로 덮음). 근거: blind-apps 원자료를 이 파서로 다시 셈(스크래치 `gd_blind_recount/`, `hq`, n=16): 멈춤 14(훅 8–104 ms, 두 rank 모두 감지 줄 없음), 투명 2(훅 114, 115 ms; 대상 아닌 rank의 장치 경로가 3.679, 3.544 s에 감지, 3.689, 3.554 s에 복구). pilot 2 `gin_qperr_w0.hk.n1`(훅 11 ms)은 같은 길로 3.757 s에 감지, 3.767 s에 복구: 늦은 길은 훅 시각에 묶이지 않음. 새 조건을 따져 봄: pilot 2 감시 끔 1/1, pilot 1 `hr` 1/1, blind-apps 16/16 참이고, 감시를 켠 pilot 시행 7회는 모두 거짓(빠른 감지를 가려냄). 열 `det1_s`, `det1_by`를 더함(두 rank 중 첫 감지, rain 수신 시각) | `predictions.csv` GC1, GC2, 2절 H1, `rows_gd.py` |
| 2026-10-09 | 태그 전 고침 2: GD5. 근거 문장("주기의 절반 + 유예 5 ms")이 리뷰 M2의 50 ms 기다림(뿌리 CQE가 없는 창은 주기와 상관없이 50 ms를 기다림)보다 먼저 쓰였고, 그때 GD2, GD4의 한도는 고쳤으나 GD5는 고치지 않았다. pilot 2에서 감시 감지 4회 중 1회가 그 경우(56.7 ms, 주기 10 ms). 그런 시행이 섞이면 중앙값이 주기가 아니라 섞인 비율을 따르므로, 감시가 먼저였고 분류가 뿌리 CQE에서 온 시행의 지연(열 `det_wcq_ms`)으로 비교한다 | `predictions.csv` GD5, `rows_gd.py` |
| 2026-10-09 | 셀은 바뀌지 않았다: `cells.json`, `schedule.json`(시드 `f739ae41811c2212`) 그대로. 바뀐 것은 파서의 열 셋과 예측 셋, H1의 반증 문장이다. 새 열은 pilot 1, pilot 2(사본), blind-apps 원자료에서 다시 계산해 위 값을 냈으므로 pilot을 다시 돌 필요는 없다고 본다 `[추론]`. 채점기 합성 시험을 다시 돌림: 41줄 모두 예외 없이 평가, 새 여섯 줄 맞음, 합성 폴더의 `hq` 시행(blind-apps 실제 6회, 늦은 복구 2 포함)에서 새 GC1 조건 6/6 참 | `[측정: 채점기 동작만]` 스크래치 `gd_selftest/res2` |
| 2026-10-09 | 사전 등록(이 커밋 하나): 고정 절 2(가설 H1–H8), 3(예측 41줄, 판정식 원문 `predictions.csv`), 7(셀 45개: app 19, 회귀와 지연 26; app 130회, 회귀와 지연 118회; hold P1, P2와 본 실행 G1, G2, N1, N2, R1–R4), 8(제외와 중단 기준). 시행 목록 `schedule.json`(시드 `f739ae41811c2212`, `cells.json`의 sha256이 머리에 있음). [PREREG.txt](PREREG.txt)에 예측, 셀, 시행 목록, 실행기, 파서, 채점기, 회귀 실행기, hold, chain, 세 계층 diff의 sha256과 배포된 빌드의 md5. 측정 전 확인: `results/`에는 채점하지 않는 pilot 폴더 둘(`20261009_pilot`, `20261009_pilot2`)뿐이고 본 실행은 아직 없다. 태그 `prereg/gpu-detect-v1`은 메인 세션이 이 커밋에 달고 push한다. PR을 rebase로 합친 뒤 `git diff prereg/gpu-detect-v1 <master 커밋> -- harness/gpu-detect/predictions.csv cells.json schedule.json`(그리고 PREREG.txt의 나머지)이 비어 있는지 확인해 이 절에 적는다 | 이 커밋, [PREREG.txt](PREREG.txt) |
| 2026-10-09 21:34:56 | 메인 세션이 사전 등록 커밋 `1891614e`(21:33:54)에 annotated 태그 `prereg/gpu-detect-v1`을 닮 | `git rev-parse prereg/gpu-detect-v1^{commit}` = `1891614e`, 태그 날짜 21:34:56 `[측정]` |
| 2026-10-09 21:35:03–22:20:41 | 본 실행(메인 세션): `bash $D/chain.sh $R/20261009 G1 G2 N1 N2 R1 R2 R3 R4`. 여덟 hold 모두 첫 회에 rc=0: G1 21:35:03–21:41:50(6분 47초, app 32회), G2 –21:45:39(3분 49초, 36회), N1 –21:52:16(6분 37초, 34회), N2 –21:56:38(4분 22초, 28회), R1 –22:02:51(6분 13초), R2 –22:10:15(7분 24초), R3 –22:14:36(4분 21초), R4 –22:20:41(6분 5초). 합계 45분 38초(어림 약 60분, 7절). 다시 돈 hold와 다시 돈 시행 0, 880 s KILL 0. iptables 규칙(`gin-`, `blind-`) 여덟 hold 모두 0 → 0. 새 mlx5 줄 0(`mlx5_new_*` 여덟 파일 모두 빈 파일), 스냅숏 16개 모두 rain 명령 오류 줄 2, sunny 0, rain 펌웨어 명령 실패 합 31. STOP 파일 없음, `LEFT_STREAK` 0, 모든 시행의 남은 프로세스 0. 시행 파일 1 495개에 illegal address, illegal memory access, unspecified launch failure 0. app hold 넷의 `schedule.json` sha256이 모두 `7a5e4875…`(= PREREG). 본 실행의 첫 시행 파일은 21:35:41로 태그 뒤다. 시행 248(app 130, 회귀와 지연 118). 본 실행 동안 문서 커밋은 없었다(상태는 태그 커밋의 `PREREGISTERED` 그대로였고 채점 뒤 `QA`로 바꿈) | `[측정]` `results/20261009/`(`chain.out`, `hold_*_p1.out`, `schedule_sha256.txt`, `snap_*`, `mlx5_*`, `fwcmd_*`; 원자료는 Release, 14절) |
| 2026-10-09 21:53(본 실행 중) | 측정 코드 리뷰(다른 에이전트, 읽기만; 실행기, 파서, 채점기, 셀과 시행 목록, 부르는 gin-remaining 실행기와 blind-apps 에이전트). 막는 결함과 높음 없음. 중간 4: M1 GD5는 걸러 낸 시행의 중앙값이라 빈 셀이면 기계적으로 "틀림", M2 LC1과 PH1의 정책 항은 빠진 줄이 설정 확인 제외가 되므로 "틀림"이 될 수 없음, M3 NC1, NC2 판정식이 예측 문장보다 약함, M4 880 s KILL이 rain의 application을 남기고 hold 뒤 확인을 건너뜀. 낮음 10(L1 GD2의 아래 한도와 음의 지연, L2 응답 쪽 틈의 창 밖 제외, L3 SIGCONT 응답을 보지 않음, L4 다시 돈 시행, L5 채점 때의 해시 확인, L6 빠진 열의 NameError, L7 랭크 4개 감시 시작 줄 수, L8 hk로 처음 도는 회귀 셀, L9 대상 rank의 균형, L10 iptables 확인). 리뷰가 고정 파일 12개의 sha256을 PREREG.txt와 대 보았고 같았다 | [qa/code_review.md](qa/code_review.md), 처리는 13, 16절 |
| 2026-10-09 22:21 | 채점(메인 세션): `python3 harness/gpu-detect/score.py harness/gpu-detect/results/20261009`. 시행 248, 판정 248, 제외 0(설정 확인 실패 0). 예측 41개 모두 맞음. N − 1 허용을 쓴 것은 감시 끔 대조(GC2)의 `gin_qperr_w0.hk.n3` 하나뿐 `[측정]` | [SCORE.md](results/20261009/SCORE.md), [trials_scored.csv](results/20261009/trials_scored.csv). 중간 표 `trials_reg_hk.csv`는 행이 모두 `trials_scored.csv`에 있어 커밋하지 않음 |
| 2026-10-09 22:26–22:34 | 독립 재계산(다른 에이전트; `score.py`, `rows_gd.py`, `SCORE.md`, 채점된 CSV를 열지 않고 자기 정규식으로 원자료에서 열을 다시 뽑음). 41개 판정 모두 채점과 같음. 문장과 판정식의 차이와 눈여겨볼 것 일곱: GC2의 `n3`(감시 없이 장치가 훅 도중 감지하고 빠르게 복구), 음의 감지 지연 둘, GD5의 거른 중앙값과 50 ms 기다림, NC1과 NC2의 문장 확인, 대상 rank의 균형, NVSHMEM 실행 속도 둘, release 시행의 틀린 결과(13, 16절) | [qa_recount.md](results/20261009/qa_recount.md), 스크립트 [qa/app_recount.py](qa/app_recount.py), [qa/reg_recount.py](qa/reg_recount.py), [qa/verdicts.py](qa/verdicts.py). 세 스크립트에 관리망 주소나 IPv4 꼴의 문자열 없음(grep) |
| 2026-10-09 | 내 확인(이 에이전트, 독립 확인 아님): 고정 파일 12개의 sha256 = PREREG.txt, `git diff prereg/gpu-detect-v1 -- harness/gpu-detect/predictions.csv harness/gpu-detect/cells.json harness/gpu-detect/schedule.json`과 `-- harness/gpu-initiated harness/blind` 모두 비어 있음, rain의 배포된 `hk` libnccl md5 `2913c777…`(= PREREG; sunny는 다시 보지 않음). 재계산 스크립트 셋을 결과 폴더 밖에서 다시 돌려 재계산 에이전트의 출력과 바이트 단위로 같은 파일을 얻음. `trials_scored.csv`와 원시 로그에서 15절의 수치를 따로 셈(재계산과 같음). 채점기와 재계산의 정의가 다른 열 둘(`n_bye_sent`, `release_after_kill_ms_r1`, 13절). stop 셀 16회의 SIGCONT 응답 모두 rc=0, 다시 돈 app 시행 0 | 이 커밋 `[측정]` |
| 2026-10-09 22:37 | Release `data-20261009`에 원자료 세 묶음(본 실행 1 579개, pilot 1 151개, pilot 2 176개)을 더함(메인 세션). `SHA256SUMS`는 19줄. 메인 세션이 내려받아 `sha256sum -c` 통과, 묶음의 모든 파일이 관리망 주소를 바꾼 것 말고 작업 트리의 파일과 바이트 단위로 같음(1 579, 151, 176개, 다름 0, 빠짐 0), 실제 주소 접두 0. release 설명에 빠져 있던 blind-apps와 gin-remaining 폴더도 더함 | 14절, [DATA.md](../../DATA.md)(파일 수와 크기는 release의 자산 목록에서 다시 셈) |
| 2026-10-09 | 마감: 13–20절, [README.md](README.md), [NOTES.md](NOTES.md), 상태 `COMPLETE`. 루트 README는 따로 커밋 | 이 커밋 |

## 13. 사전 등록 이후 변경

> 기존 문장을 고치지 않고 여기에 덧붙인다. 태그 뒤 이 실험의 셀, 시행 목록, 실행기, 파서, 채점기, 예측, 세 계층 diff는 바뀌지 않았다(고정 파일 12개의
> sha256 = [PREREG.txt](PREREG.txt), 16절). 아래는 모두 판정을 바꾸지 않는 덧붙임과 정정이다.

| 날짜 | 무엇을 | 이유 | 영향 범위 | 커밋 |
|---|---|---|---|---|
| 2026-10-09 | 덧붙임(6절 "대상 rank는 0과 1 반씩", 7절 "대상과 `u_t`, `u_d`를 고르게 뽑음"): `apprun.py plan`은 시행마다 대상을 따로 고르게 뽑으므로 셀 안의 대상이 반씩이 아니다. 고정한 `schedule.json`이 정한 대로 돌았다. rank 0 : rank 1 = `gin_qperr@hk` 8:8, `gin_qperr_w0@hk` 2:2, `nvs_kill@t1_380` 2:2, `gin_qperr@hr` 1:5, `gin_qperr@hq` 2:4, `gin_qperr_w1@hk` 3:5, `gin_qperr_w100@hk` 6:2, `gin_kill@hk` 2:4, `gin_stop@hk` 2:6, `nvs_kill@t1w` 5:3, `nvs_remacc@t1w` 3:5, `nvs_remacc@t1_380` 0:4, `nvs_kill_rel@t1w` 1:4, `nvs_remacc_rel@t1w` 4:1, `nvs_qperr@t1w` 1:5. `nvs_stop@t1w`은 설계대로 8:0, 장애 없는 셀은 대상 없음 `[측정]` | 리뷰 L9, 재계산 3절 5번 | 판정식은 대상 rank를 보지 않는다. 대상이 한쪽에 몰린 셀의 범위는 그 rank의 범위에 가깝다 | 마감 커밋 |
| 2026-10-09 | 덧붙임(3절 GC2 문장, 2절 H1의 반증 조건): GC2는 4회 중 3회로 N − 1 허용 안에서 맞았다. `gin_qperr_w0.hk.n3`(훅이 문맥 생성 뒤 16 ms)에서 대상 rank 0의 장치 경로가 훅 발화 0.90 ms 뒤, 훅이 아직 QP를 옮기는 중에 LOCAL_QP_ERR를 분류했고 라운드가 11.1 ms에 재개되어 투명이었다 `[측정]`. 예측 문장 "감시를 끄면 아무것도 장애를 빨리 감지하지 못한다"는 이 시행에서 틀렸다. 이 시행은 멈춤도 늦은 RETRY_EXC도 아니다. 나머지 3회는 두 rank 모두 감지 줄 없이 20 s 상한까지 멈췄다. 빠른 감지나 복구가 1회라 H1의 반증 조건(2회 이상)에는 닿지 않는다 | 재계산 3절 1번 | 15, 17절(H1) | 마감 커밋 |
| 2026-10-09 | 덧붙임(3.1절 `det_ms`, 3절 GD2, GD4): 감지 지연은 훅 줄의 `done_mono_ms`(훅이 QP 넷을 다 옮긴 때)부터 잰다. 장치가 훅 도중에 분류하면 음수가 된다: `gin_qperr_w1.hk.n1` −0.085 ms(발화 뒤 1.28 ms), `gin_qperr_w0.hk.n3` −0.364 ms(발화 뒤 0.90 ms) `[측정]`. GD4의 판정식에는 아래 한도가 없어 첫째는 그 조건을 만족했다. GD2 셀(`gin_qperr@hk`)에는 음수가 없다(최솟값 0.208 ms). 둘째는 GC2 셀이다. 위 두 시행에서 `det1_s`(두 rank 중 첫 감지, 훅 줄 수신 뒤)는 빈 칸이다: 장치 줄이 훅 줄보다 먼저 왔기 때문이다 `[측정, 소스: 3.1절 정의]` | 리뷰 L1, 재계산 3절 2번 | 판정 영향 없음. GC2의 `n3`은 `rec_rx_s` 0.011 s로 조건에서 빠졌다 | 마감 커밋 |
| 2026-10-09 | 해석의 범위(3절 GD5, 2절 H2): GD5의 중앙값에 든 시행(감시가 먼저, 뿌리 CQE로 분류)은 주기 1 ms 3/8, 10 ms 14/16, 100 ms 8/8로 빈 셀이 없다(리뷰 M1의 걱정은 일어나지 않음). 그런데 그중 8회도 감시 줄의 "ERR로 본 시간"이 48.9–51.3 ms로 뿌리 CQE가 없는 창의 50 ms 기다림을 거쳤다(10 ms의 n8, n9, n16, 100 ms의 n1, n3, n5, n6, n8) `[측정]`. 처음 본 때는 창에 뿌리 CQE가 없었고 기다리는 동안 생겼다고 보지만 확인하지 않았다 `[추론, 미확인]`. 이 8회를 빼도 순서는 같다(6.20 < 14.82 < 91.36 ms, n=3, 11, 3). 모든 시행의 감지 지연 중앙값은 주기 순서가 아니다(1 ms 41.19, 10 ms 18.55, 100 ms 91.75 ms, n=8, 16, 8). H2의 반증 문장은 이 거름을 두지 않았으므로 17절은 H2를 고정 문장 그대로 판정한다 | 재계산 3절 3번, 리뷰 M1 | 17절 H2(반증) | 마감 커밋 |
| 2026-10-09 | 덧붙임(3절 NC1, NC2): 판정식이 문장보다 약하다(NC1은 죽음 줄만 보고, NC2는 한 PE의 거절과 유예 종료도 통과). 시행마다 문장대로 따졌다. NC1 4회: 살아남은 PE의 오류 줄 0, 죽음 줄 0, 하네스 유예로 끝남(시행마다 "library socket closed (FIN)" 줄 하나, blind-apps의 정의로 오류 줄이 아님). NC2 4회: 두 PE가 한 번씩 거절, 두 PE 모두 30 s 상한으로 끝남 `[측정]` | 리뷰 M3, 재계산 3절 4번 | 판정 영향 없음, 문장도 맞음 | 마감 커밋 |
| 2026-10-09 | 덧붙임(3절 LC1, PH1; 8절 설정 확인): NIC 경로 줄이나 정책 줄이 빠진 rank는 설정 확인 실패로 제외되므로 LC1과 PH1의 정책 항은 "맞음"이나 "자료 부족"만 될 수 있다. 본 실행에서 `gin_none@hk`, `f1_b@hk`, `rm4_kill3_hold@hk`의 설정 확인 제외는 0이다(248회 전체도 0) `[측정]`. 숨은 반례가 없다 | 리뷰 M2 | 판정 영향 없음 | 마감 커밋 |
| 2026-10-09 | 덧붙임(3.1절 `n_bye_sent`, RG4의 `release_after_kill_ms_r1`): 채점기와 재계산의 정의가 다른 열 둘. `n_bye_sent`: 채점기는 "goodbye sent to N peer(s)" 줄 중 N ≥ 1인 줄, 재계산은 모든 줄을 센다. 장애 없는 셀 8회 모두 먼저 정리한 PE가 1 peer에, 다른 PE가 0 peer에 보냈다고 적었다(채점기 1, 재계산 2). `release_after_kill_ms_r1`: 채점기는 gin-harden의 정의(받기만 하는 rank의 커널 끝, kill 뒤 20.6–21.4 ms), 재계산은 devComm 단어 해제 줄(1.70–1.84 ms) `[측정]` | 내 확인(12절) | 판정 영향 없음(두 정의 모두 조건을 만족) | 마감 커밋 |
| 2026-10-09 | 덧붙임(8절 실행): 880 s KILL 없음(여덟 hold 모두 첫 회 rc=0, 가장 긴 hold 7분 24초), 응답 쪽 틈 셀의 창 밖 제외 0(11회 모두 rank 0이 "peer closed the socket before DONE"로 거절), stop 셀 16회의 SIGCONT 응답 모두 rc=0, 다시 돈 app 시행 0 `[측정]`. iptables 확인이 sudo 실패와 규칙 없음을 가르지 못하는 점은 확인하지 않았다 `[미확인]` | 리뷰 M4, L2–L4, L10 | 영향 없음 | 마감 커밋 |
| 2026-10-09 | 정정(11절 "본 실행 G1–R3"): hold R4를 더하기 전의 문구다. 본 실행은 G1–R4였다(7절, 12절). 상자 끝에 덧붙였다 | 내 확인 | 문구뿐 | 마감 커밋 |
| 2026-10-09 | 정정(18절 첫 줄, 사전 등록 때의 "`hk`는 아직 클러스터에서 돌지 않았다"): pilot 2와 본 실행이 `hk`로 돌았다. 18절은 마감 때의 한계로 다시 썼다 | 마감 | 문구뿐 | 마감 커밋 |

## 14. 원자료와 결과표

| 무엇 | 경로 또는 Release 자산 | n |
|---|---|--:|
| 채점표(예측별 판정, 놓친 시행, 셀별 제외) | [results/20261009/SCORE.md](results/20261009/SCORE.md) | 예측 41 |
| 시행별 값(채점 상태 포함) | [results/20261009/trials_scored.csv](results/20261009/trials_scored.csv) | 248(판정 248) |
| 독립 재계산 | [results/20261009/qa_recount.md](results/20261009/qa_recount.md), 스크립트 [qa/app_recount.py](qa/app_recount.py), [qa/reg_recount.py](qa/reg_recount.py), [qa/verdicts.py](qa/verdicts.py) | 248 |
| 측정 코드 리뷰(본 실행 중) | [qa/code_review.md](qa/code_review.md) | |
| 본 실행 원자료(app 시행 `raw/<id>/`, 회귀와 지연 `reg/hk/`, `reg/mr_hk/`, `reg/mr_hw/`, `chain.out`, `hold_*_p1.out`, 스냅숏) | Release `data-20261009`, `harness__gpu-detect__results__20261009.tar.xz`(파일 1 579개, 709 504 B, sha256 앞 12자리 `ce1b710ed93a`). 풀면 `results/20261009/` | 248 |
| pilot 1 원자료(`hw`, 채점 안 함) | Release `data-20261009`, `harness__gpu-detect__results__20261009_pilot.tar.xz`(151개, 78 304 B, `6de4f10ea9d8`) | 22 |
| pilot 2 원자료(`hk`, 채점 안 함) | Release `data-20261009`, `harness__gpu-detect__results__20261009_pilot2.tar.xz`(176개, 88 436 B, `0e7ae195cfe2`) | 23 |
| 배포 확인 | [deploy_check.txt](deploy_check.txt), [deploy_check_hk.txt](deploy_check_hk.txt) | |
| 사전 등록 | [predictions.csv](predictions.csv), [PREREG.txt](PREREG.txt), 태그 `prereg/gpu-detect-v1`(`1891614e`) | 41 |

Release 자산은 2026-10-09 22:37에 올라갔고, 메인 세션이 내려받아 `sha256sum -c`와 작업 트리 파일과의 바이트 비교(관리망 주소를 바꾼 것 말고 같음)로
확인했다(12절). 체크섬 전체는 [DATA.md](../../DATA.md)와 그 release의 `SHA256SUMS`에 있다.

## 15. 결과 요약

판정: **예측 41개 모두 맞음**(시행 248, 판정 248, 제외 0). 채점 [SCORE.md](results/20261009/SCORE.md), 독립 재계산도 41/41
([qa_recount.md](results/20261009/qa_recount.md)) `[측정]`. N − 1 허용을 쓴 것은 감시 끔 대조 하나다(13절). 범위는 따로 적지 않으면 그 셀 키의 판정
시행 전체에 걸친 범위이고, 수치는 채점표, 재계산, 내가 `trials_scored.csv`와 원시 로그에서 다시 센 값이 모두 같다(정의가 다른 열 둘은 13절).

**1. 수정하지 않은 GIN 예제, 대상 rank의 GIN QP 넷을 모두 ERR로**(훅은 GDAKI 문맥 생성 뒤 8–114 ms, 무작위) `[측정]`

| 조건 | 셀 키 | n | 결과 | 예측 |
|---|---|--:|---|---|
| 감시 10 ms(기본) | `gin_qperr@hk` | 16 | 투명 16/16(복구 줄, 결과 맞음). 대상 rank에서 먼저 감지한 것: 감시 15(분류 출처 뿌리 CQE 14, 없음 1), 장치 1. 감지 지연 0.208–58.18 ms(중앙값 18.55), 재개 11.6–69.5 ms(중앙값 30.3) | 감지 100 ms 안(GD2), 재개 1 000 ms 안(GD3), 투명(GD1) 맞음 |
| 감시 1 ms | `gin_qperr_w1@hk` | 8 | 투명 8/8. 감지 −0.085–50.98 ms(중앙값 41.19): 감시 뿌리 CQE 3(4.8–31.7 ms), 감시 뿌리 CQE 없음 4(50.6–51.0 ms), 장치 1(−0.085 ms). 재개 11.9–63.5 ms | 투명, 감지 70 ms 안(GD4) 맞음 |
| 감시 100 ms | `gin_qperr_w100@hk` | 8 | 투명 8/8. 감지 20.9–116.2 ms(중앙값 91.75), 모두 감시와 뿌리 CQE. 재개 32.4–127.5 ms | 투명, 감지 200 ms 안(GD4) 맞음 |
| 감시 끔(같은 빌드) | `gin_qperr_w0@hk` | 4 | 3회는 두 rank 모두 감지 줄 없이 20 s 상한까지 멈춤. 1회(`n3`)는 장치가 훅 도중에 감지하고 11.1 ms에 재개, 투명 | 빠른 감지 없음(GC2) 맞음, N − 1 |
| 감시 없는 앞 빌드(gin-remaining) | `gin_qperr@hr` | 6 | 6/6 두 rank 모두 감지와 복구 줄 없이 20 s 상한까지 멈춤 | GC1 맞음 |
| 감시 없는 앞 빌드(gin-peer) | `gin_qperr@hq` | 6 | 6/6 같음 | GC1 맞음 |

- **감지 지연과 주기**(GD5): 감시가 먼저 보고 뿌리 CQE로 분류한 시행의 중앙값은 1 ms 6.20(n=3), 10 ms 18.55(n=14), 100 ms 91.75 ms(n=8)로 주기
  순서다. 그러나 그 25회 중 8회는 감시가 약 50 ms(48.9–51.3 ms)를 기다린 뒤였다. 1 ms 셀에서는 8회 중 4회가 뿌리 CQE 없이 50 ms를 기다렸다. 그래서
  모든 시행의 중앙값은 1 ms 41.19, 10 ms 18.55, 100 ms 91.75 ms로 주기 순서가 아니다(13절, 17절 H2).
- **감지에서 재개까지**: 감시가 감지한 30회에서 11.1–12.5 ms(중앙값 11.4), 장치가 감지한 3회에서 11.4–12.0 ms.
- **장치 경로가 먼저 감지한 세 시행**(`gin_qperr.hk.n5`, `gin_qperr_w1.hk.n1`, `gin_qperr_w0.hk.n3`)은 훅이 문맥 생성 뒤 13, 24, 16 ms였다. 셋 모두
  분류 줄이 훅 발화 0.90–1.43 ms 뒤, 훅이 끝나기 0.36 ms 전에서 0.21 ms 뒤 사이에 나왔다 `[측정]`. 훅이 장치 스레드가 CQ를 읽는 호출 안에 걸렸다고
  본다 `[추론]`. 같은 무렵(8–22 ms)의 다른 훅 일곱은 장치가 먼저 감지하지 않았다.
- **감시의 비용**(정리 때 줄, 두 rank 합): 장애 없는 GIN 예제 6회에서 QUERY_QP 104–124번, 평균 67.0–70.3 µs, 최대 85.3–97.7 µs. 멈춤 셀에서 한
  번의 최대 1.49 ms(멈춤 7.4 s 시행의 멈추지 않은 rank).

**2. GIN 예제의 kill, 멈춤, 장애 없음**(감시 10 ms) `[측정]`

| 조건 | 셀 키 | n | 결과 | 예측 |
|---|---|--:|---|---|
| 한 rank SIGKILL | `gin_kill@hk` | 6 | 살아남은 rank의 첫 오류 줄 kill 0.2–7.1 ms 뒤, 감시 감지 0. 결과는 6/6 멈춤: 예제가 끝나지 않아 하네스 유예로 끝남(kill 10.26–10.28 s 뒤) | 투명 아님, 5 s 안 오류(GR1) 맞음 |
| 한 rank 1.4–7.4 s 멈춤 | `gin_stop@hk` | 8 | 투명 8/8. 죽음 판정, 거절, 감시 감지 0 | GF1 맞음 |
| 장애 없음 | `gin_none@hk` | 6 | 투명 6/6, 감시 감지와 거절 0. 두 rank 모두 정리 때 감시 줄 6/6. NIC 경로가 켜지고 호스트 shadow와 같은 QP 구조 4개 6/6 | GF2, WT1, LC1 맞음 |

**3. 수정하지 않은 NVSHMEM 예제(ring-reduce)** `[측정]`

| 조건 | 셀 키 | n | 결과 | 예측 |
|---|---|--:|---|---|
| PE 하나 SIGKILL, fail-stop | `nvs_kill@t1w` | 8 | 살아남은 PE가 kill 응답 0.027–0.494 ms 뒤 작별 없는 FIN으로 판정해 거절, 종료 코드 70으로 kill 73.0–95.4 ms 뒤 스스로 끝남 8/8 | ND1 맞음 |
| 원격 접근 회수, fail-stop | `nvs_remacc@t1w` | 8 | 두 PE가 훅 3.3–11.2 ms 뒤 거절, 두 PE 모두 종료 코드 70으로 86–106 ms 뒤 끝남 8/8 | ND2 맞음 |
| kill, 앞 빌드(t1_380) | `nvs_kill@t1_380` | 4 | 살아남은 PE가 오류 줄 없이 멈춤, 하네스 유예로 끝남 4/4 | NC1 맞음 |
| 원격 접근 회수, 앞 빌드 | `nvs_remacc@t1_380` | 4 | 두 PE가 훅 4.3–6.0 ms 뒤 거절하고도 30 s 상한까지 멈춤 4/4 | NC2 맞음 |
| kill, release | `nvs_kill_rel@t1w` | 5 | 살아남은 PE가 장치 대기 해제 줄을 남기고 종료 코드 0으로 스스로 끝남 5/5(kill 0.17–10.4 s 뒤). 결과는 4회 틀림(틀린 원소 줄 8 388 608–16 777 215), 1회 맞음(kill 0.165 s 뒤 끝난 시행) | NR1 맞음 |
| 원격 접근 회수, release | `nvs_remacc_rel@t1w` | 5 | 두 PE 모두 해제 줄, 종료 코드 0으로 스스로 끝남 5/5(훅 0.17–18.5 s 뒤). 결과 5/5 틀림(16 777 215–46 137 341줄, 두 PE 합) | NR1 맞음 |
| PE 0 1.4–7.5 s 멈춤 | `nvs_stop@t1w` | 8 | 투명 8/8, 죽음 판정과 거절 0 | NF1 맞음 |
| 장애 없음 | `nvs_none@t1w` | 8 | 투명 8/8, 거절과 FIN 판정 0. 먼저 정리한 PE가 작별을 보내고 상대가 받아 그 FIN을 "떠남"으로 봄 8/8 | NF2 맞음 |
| QP 오류 | `nvs_qperr@t1w` | 6 | 투명 6/6, 복구 줄 2씩 | NQ1 맞음 |
| 장치 대기 단어 확인의 비용 | `nvs_none@t1w` / `@t1_380` | 8 / 6 | 64 MiB 반복당 ms 중앙값 18.9605 / 18.9704, 비 0.9995 | 1.10배 이하(NO1) 맞음 |

- 실행 속도가 둘로 갈린다(64 MiB 반복당 약 11.5 ms와 약 19.0 ms). `t1w` 8회 중 빠름 3, t1_380 6회 중 빠름 1. 같은 속도끼리 중앙값의 비는 빠름
  1.0074, 느림 0.9991이다. 비용은 어느 쪽으로도 1% 안이다 `[측정]`.
- release의 틀린 결과는 예제가 풀린 대기 뒤 받지 못한 결과를 검증한 것이다(9.2절 (d)) `[추론]`.

**4. GIN 회귀와 리뷰 항목**(빌드 `hk`, 시행 5씩, M-C 셀 3씩) `[측정]`

- 투명: `f1_b`, `f3_b`, `bidirf_sym_b`(RG1), `mr4_none`, `mr4_f1_01`(RG8). 통계 API: `f1_b`에서 두 rank가 라운드 1, 복구 1, rank 0 거절 0(RG7).
  감시는 두 번째 라운드를 만들지 않았다.
- `f4_b`: kill 1.64–1.79 ms 뒤 peer-dead 거절(RG3). `hd_rxdeath_b`: 받기만 하는 rank의 비동기 오류 kill 2.02–2.12 ms 뒤, 커널 끝 20.6–21.4 ms
  뒤(RG4). `f2rel_b`: rank 0 REM_ACCESS 거절, rank 1 device_error, abort 725.3–753.0 ms(RG5).
- `rm4_kill3_untimed`: 생존 rank의 rank 3 받기가 각자의 판정 2 006.4–2 013.9 ms 뒤 풀림(값 15), 생존 rank 사이 보내기 6/6, 커널 3/3 끝남(RG9).
- 순환 셋(`mr4_cyc_stall`): 투명, handshake timeout과 거절 0, 복구 0-1, 1-2, 2-0, 라운드 퍼짐 1.5–16.8 ms(RG10).
- M-A(`mr4_twolow_stall`): rank 3이 rank 0과 1의 REQ에 ACK 기다림 안에서 답함 5/5, 투명, 시간 초과와 거절 0, 퍼짐 2.3–17.6 ms(MA1).
- M-C: 기본 규칙(`rm4_late01`)은 degraded 뒤 건강한 쌍 0-1의 장애를 거절 1, 복구 0(3/3, MC1). `NCCL_GIN_TS_DEGRADED_ROUNDS=1`(`rm4_late01_rounds`)은
  복구 1, 거절 0(3/3, MC2). 기본 규칙 셀 3회 중 2회는 rank 0의 감시가 그 QP 오류를 6.0, 6.2 ms에 기록했다.
- L-C: NIC 경로가 켜지고 NIC으로 읽은 장치 QP 구조 4개가 호스트 shadow와 같음, `gin_none` 6/6, `f1_b` 5/5(LC1). 설정 확인 제외 0.
- 회귀 셀의 감시 감지 줄은 M-C 기본 규칙 셀 2회뿐이다. 랭크 2개 회귀 33회와 지연 40회에서는 0이다. 장애를 넣은 랭크 2개와 4개 셀에서는 드라이버가
  CQ를 계속 읽어 장치가 먼저 보고했다고 본다 `[추론]`.

**5. 응답 쪽 Commit 뒤 손실과 정책 hook**(랭크 4개, 시간 제한 없는 받기, rank 3이 시작 쪽, rank 0이 응답 쪽) `[측정]`

| 조건 | 셀 키 | n | 결과 | 예측 |
|---|---|--:|---|---|
| rank 3이 자기 Commit 뒤 멈추고 kill됨, `hk` | `rm4_gap@hk` | 5 | 5/5 창에 듦(rank 0이 "peer closed the socket before DONE"로 거절). rank 0이 Commit 뒤 손실 줄 1, rank 3을 죽음으로 판정, 원인 peer-dead. 세 생존 rank의 rank 3 받기가 각자의 판정 2 007.7–2 013.0 ms 뒤 풀림(값 15), 멈춘 커널 0 | GP1 맞음 |
| 같음, `hw` | `rm4_gap@hw` | 3 | rank 0이 원인 unknown으로 거절, 판정 없음, 받기가 풀리지 않아 application의 15 s 유예 뒤에도 커널이 돌아 종료 코드 3(3/3). rank 1, 2는 2 007.8–2 012.3 ms 뒤 풀림(값 6) | GP2 맞음 |
| rank 3이 ACK 직후 스스로 끝남(시험 스위치) | `rm4_gapx@hk` | 3 | rank 3 종료 코드 73, rank 0 peer-dead, 세 생존 rank 2 008.1–2 012.5 ms(값 9), 멈춘 커널 0 | GP3 맞음 |
| 모든 rank가 hold 요청, rank 3 kill | `rm4_kill3_hold@hk` | 3 | rank마다 hold WARN 하나(4 rank), 모두 effective fail-fast. 받기 해제 2 007.1–2 013.0 ms(값 9), 생존 rank 사이 보내기 6/6 | PH1 맞음 |
| 정책 불일치(rank 0만 hold), rank 1 kill | `f4_mix_b@hk` | 3 | agreed 0, 두 rank에 불일치 WARN 하나씩, hold WARN 0, fail-fast. rank 0이 kill 1.54–1.76 ms 뒤 peer-dead로 거절 | PH2 맞음 |

**6. 장애 없는 지연**(rank 0 p50, 실행마다 3 000번 왕복, 실행 5의 중앙값과 범위) `[측정]`

| 크기 | 감시 끔 | 1 ms | 10 ms | 100 ms | 예측 |
|---|---|---|---|---|---|
| 4 KiB | 10.50 µs(10.46–10.50) | 10.50(5/5) | 10.50(10.46–10.53) | 10.50(5/5) | 10 ms와 끔의 차이 0.00 ≤ 0.40(LT1), 1 ms와 끔 0.00 ≤ 1.0(LT3) 맞음 |
| 256 KiB | 38.88 µs(5/5) | 38.88(5/5) | 38.88(38.88–38.91) | 38.88(5/5) | 0.00 ≤ 0.30(LT2), 0.00 ≤ 1.0(LT4) 맞음 |

- 재계산이 원시 지연 3 000개에서 다시 구한 p50 중앙값도 모든 주기에서 같다(10.4960, 38.8800 µs).
- 실행마다 QUERY_QP(정리 때, 두 rank 합): 1 ms 2 136–2 148(4 KiB), 2 660–2 696(256 KiB); 10 ms 260, 324; 100 ms 32, 40. 한 번에 평균 65.1–70.8 µs,
  최대 78.1–108.0 µs.

**안전** `[측정]`: 여덟 hold 모두 새 mlx5 줄 0. 스냅숏 16개에서 rain 명령 오류 줄 2와 펌웨어 명령 실패 합 31이 그대로이고 sunny 명령 오류 0이다. 주기
1 ms의 감시를 돌린 hold(G2, R1)에서도 펌웨어 명령 실패가 늘지 않았다. iptables 규칙 0 → 0, CUDA 메모리 오류 0.

## 16. QA와 재현성

- **채점.** 메인 세션이 `score.py`로 셈: 시행 248, 판정 248, 제외 0, 예측 41개 모두 맞음 `[측정]`.
- **독립 재계산.** 다른 에이전트가 `score.py`, `rows_gd.py`, `SCORE.md`, 채점된 CSV를 열지 않고 자기 정규식으로 원자료에서 열을 다시 뽑아 41개
  판정식을 다시 판정했다([qa_recount.md](results/20261009/qa_recount.md), 스크립트 [qa/](qa/)).
  - 맞은 것: 판정 41/41, app 제외 0(8절 규칙을 다시 구현), 15절의 핵심 수치(감지와 재개 지연, FIN 판정과 종료 시각, release의 해제 줄과 결과,
    지연 중앙값과 원시 지연의 p50, 회귀와 응답 쪽 틈의 해제 시각).
  - 문장과 판정식의 차이 일곱: GC2의 `n3`, 음의 감지 지연 둘, GD5의 거른 중앙값과 50 ms 기다림, NC1과 NC2의 문장 확인(문장도 맞음), 대상 rank의
    균형, NVSHMEM 실행 속도 둘, release 시행의 틀린 결과. 판정을 바꾸는 것은 없다. 13절과 15절에 옮겼다.
  - 한계: 회귀 스크립트는 8절의 제외 규칙을 다시 구현하지 않고 118회를 모두 썼다. 회귀의 제외 0은 채점기의 값과 같다는 것까지다.
- **코드 리뷰.** 설계 단계 리뷰 셋(두 계층 1회, 정책 hook과 응답 쪽 틈 2회, 12절)과 본 실행 중 측정 코드 리뷰([qa/code_review.md](qa/code_review.md)).
  측정 코드 리뷰에 막는 결함과 높음이 없다. 중간 넷과 낮음 열의 확인과 처리는 그 문서 끝 절과 13절에 있다.
- **고정 파일.** `predictions.csv`, `cells.json`, `schedule.json`, `apprun.py`, `rows_gd.py`, `score.py`, `cells_reg.sh`, `hold.sh`, `chain.sh`, 세
  계층 diff의 sha256이 [PREREG.txt](PREREG.txt)와 같다. `git diff prereg/gpu-detect-v1 -- harness/gpu-detect/predictions.csv
  harness/gpu-detect/cells.json harness/gpu-detect/schedule.json`과 `-- harness/gpu-initiated harness/blind`가 비어 있다. 이 문서의 2, 3, 7, 8절은 태그와
  같다. rain에 배포된 `hk` libnccl의 md5가 `2913c777…`(PREREG)다 `[측정]`. sunny의 번들은 마감 때 다시 보지 않았다 `[미확인]`.
- **내 확인.** 재계산 스크립트를 다시 돌려 같은 출력을 얻었고, `trials_scored.csv`와 원시 로그에서 15절의 수치를 따로 셌다(12절). 이것은 독립 확인이
  아니다.
- **재현.** GIN은 순정 NCCL v2.32.3-1 + `../gpu-initiated/gin_recovery/remaining/gin_transparent_hr.diff` + [hw_layer.diff](hw_layer.diff) +
  [hk_layer.diff](hk_layer.diff), NVSHMEM은 9.4절의 diff 넷 + [t1w_layer.diff](t1w_layer.diff). 빌드는 [build_gd.sh](build_gd.sh), 확인은
  [make_diff_gd.sh](make_diff_gd.sh), 배포는 [deploy_gd.sh](deploy_gd.sh), 실행 순서는 9.6절, 빌드 md5는 5절. 요약은 [NOTES.md](NOTES.md).

## 17. 결론

가설마다 2절의 반증 조건을 그대로 대 보았다.

- **H1(감지가 호출 안에만 있어 놓쳤고, 호스트 감시가 맡으면 투명하게 복구된다): 지지.** 감시를 켠 `hk`의 GIN 예제 QP 오류는 주기 1, 10, 100 ms 모두
  투명했다(32/32, 반증 조건은 투명 아님 2회 이상). 그중 감시가 먼저 감지한 30회 모두 라운드가 끝났다. 감시가 없으면 앞 빌드 둘은 12/12, 같은 빌드의 감시 끔은
  3/4가 두 rank 모두 아무 줄 없이 멈췄다 `[측정]`. 감시 끔에서 빠르게 감지하고 복구한 시행은 1회(`n3`)로 반증 조건(2회 이상)에 닿지 않는다. 그
  시행은 장치 스레드가 CQ를 읽는 호출 안에 훅이 걸려 바로 분류된 것이므로, H1이 말하는 "호출 안의 감지"가 빠르게 된 경우다 `[추론]`. 다만 예측
  GC2의 문장("감시 없이는 아무것도 빨리 감지하지 못한다")은 그 시행에서 틀렸다(13절).
- **H2(감지 지연은 주기의 절반 남짓과 유예 5 ms로 정해지고, 10 ms 감시는 지연을 정밀도 안에서 바꾸지 않는다): 반증(감지 지연 부분). 지연 부분은
  지지.** 반증 조건의 첫 줄 "감지 지연의 중앙값이 주기 순서를 따르지 않는다"가 모든 시행의 중앙값에서 성립했다: 1 ms 41.19 > 10 ms 18.55 < 100 ms
  91.75 ms `[측정]`. 짧은 주기에서는 주기가 아니라 뿌리 CQE가 없는 창의 50 ms 기다림(리뷰 M2로 태그 전에 넣은 것)이 지연을 정했다. 1 ms 셀의 절반이
  그 기다림을 거쳤고, 뿌리 CQE로 분류한 감시 감지 25회 중 8회도 그랬다. 사전 등록한 예측 GD5는 그 기다림을 빼려고 뿌리 CQE 감지만 비교했고 맞았으나
  (6.20 < 18.55 < 91.75 ms), 가설의 반증 문장은 그 거름을 두지 않았다. 지연 쪽 반증 조건(10 ms 감시의 차이가 정밀도를 넘음)은 성립하지 않았다:
  4 KiB, 256 KiB 모두 차이 0.00 µs, 1 ms 감시도 0.00 µs `[측정]`.
- **H3(NVSHMEM kill 뒤의 멈춤은 FIN을 쓰지 않은 것과 거절이 대기에 닿지 않는 것 때문이고, FIN 판정과 fail-stop을 더하면 1 s, 2 s 안에 끝난다):
  지지.** kill 셀 8/8이 0.1 s 안에, 원격 접근 회수 셀 8/8이 0.11 s 안에 종료 코드 70으로 끝났다(반증 조건은 멈추거나 시간을 넘긴 시행 2회 이상).
  같은 장애에서 앞 빌드는 4/4, 4/4 멈췄고, 원격 접근 회수에서는 거절하고도 멈췄다 `[측정]`. 원인의 두 부분은 대조로만 갈랐다 `[추론]`.
- **H4(release 정책의 장치 대기 단어가 대기를 풀어 프로세스가 스스로 끝나게 한다): 지지.** release 셀 10회 모두 하네스가 끝낸 프로세스가 없고, 살아남은
  프로세스마다 해제 줄을 남겼다(반증 조건은 하네스가 끝낸 시행 2회 이상) `[측정]`. 그러나 결과는 10회 중 9회 틀렸다. release는 멈춤을 풀 뿐
  데이터를 주지 않으며, application이 호스트 질의로 거절을 알고 처리해야 한다.
- **H5(두 계층은 거짓 양성을 만들지 않는다): 지지.** 멈춤과 장애 없는 셀 30회(GIN 14, NVSHMEM 16)에서 감시 감지, 거절, 죽음 판정이 0이다(허용은 1회,
  장애 없는 GIN은 0회). 지연 셀 40회와 랭크 2개 회귀에서도 감시 감지가 없었다. 장애 없는 NVSHMEM 실행의 FIN은 8/8 작별로 "떠남"이 되었다 `[측정]`.
  멈춘 프로세스의 NIC과 커널이 응답해 QP가 RTS로 남는다는 이유는 확인하지 않았다 `[추론]`.
- **H6(기존 동작은 그대로이고 리뷰 세 항목의 수정은 설계대로 동작한다): 지지.** 회귀 셀(RG1, RG3–RG5, RG7–RG10, NQ1, GR1, WT1)과 M-A, M-C 두 가지,
  L-C 셀의 모든 시행이 예측대로였다(반증 조건은 예측과 다른 시행 하나). LC1은 구조상 "틀림"이 될 수 없는 판정식이지만 설정 확인 제외가 0이라 숨은
  반례도 없다(13절). M-A의 경계(바깥 라운드가 25 s를 넘는 경우)는 재지 않았다.
- **H7(응답 쪽 Commit 뒤 죽음에서 그 응답 쪽 대기가 풀리지 않는 것은 죽음 판정이 없어 degraded가 예약되지 않기 때문이다): 지지.** `hk`의 두 셀
  8/8에서 응답 쪽 rank 0이 죽음을 판정하고 peer-dead로 거절했고 세 생존 rank가 모두 자기 판정 2 007.7–2 013.0 ms 뒤 풀렸다. `hw` 대조 3/3에서는 rank 0이 원인
  unknown으로 판정 없이 거절했고 풀리지 않았다(반증 조건은 셀마다 2회 이상) `[측정]`. 다른 원인(reset, ACK 보내기 실패)은 셀이 없다.
- **H8(정책 hook과 정책 변수는 fail-fast에서 동작을 바꾸지 않는다): 지지.** hold 요청 3/3, 정책 불일치 3/3이 WARN 한 줄 뒤 fail-fast였고, kill의
  결과가 RG9, RG3과 같았다. `hk`로 옮긴 회귀 셀도 모두 예측대로였다 `[측정]`. hook의 hold 갈래는 이 빌드에 없으므로 잰 것은 fail-fast의 동치뿐이다.

정리하면, 수정하지 않은 두 공식 예제에서 GPU 주도 라이브러리의 장애 감지를 application 호출 밖으로 옮기는 데 성공했다. GIN은 QP 상태 감시로
멈추던 QP 오류를 복구했고, NVSHMEM은 FIN 판정과 fail-stop으로 멈추던 kill과 원격 접근 회수를 0.11 s 안의 오류 종료로 바꿨다. 남은 것은 감지 지연이
짧은 주기에서도 50 ms 기다림에 묶인다는 점과, release 정책은 멈춤을 풀어도 데이터를 주지 못한다는 점이다.

## 18. 한계

- **감지 지연.** 창에 뿌리 CQE가 없으면 감시는 상대의 거절을 50 ms 기다린다(리뷰 M2). 그래서 주기를 1 ms로 줄여도 감지 지연 중앙값이 41 ms다. 그
  기다림은 상대의 거절이 50 ms 안에 온다는 가정이고, 상대가 그 안에 보고하지 못하면 LOCAL_QP_ERR 라운드가 실패한 쓰기를 다시 낼 수 있다 `[추론]`.
  뿌리 CQE로 분류한 감지 8회가 왜 50 ms를 기다렸는지는 확인하지 않았다 `[미확인]`.
- **감시가 보지 못하는 장애.** 감시는 장애를 이 rank의 QP 상태로만 본다. 상대만 망가진 경우(상대 QP 오류, 보낼 것 없음)는 상대의 감시나 RETRY_EXC를
  기다린다. 받기만 하는 QP와 예약한 WQE가 없는 QP는 다루지 않는다(9.1절 (a)). 이 실험의 훅은 대상 rank의 QP를 모두 옮겼다.
- **GIN kill.** 살아남은 rank는 kill 7.1 ms 안에 오류를 보았지만 예제는 끝나지 않아 6/6 하네스 유예로 끝났다. 이 실험은 그 원인을 따로 보지 않았다
  `[미확인]`. blind-apps는 부트스트랩 대체가 실행기의 "함께 끝나기"를 없앤 탓일 수 있다고 적었다.
- **release.** 대기를 풀 뿐 데이터를 주지 않는다(10회 중 9회 틀린 결과). 확인하지 않는 application은 틀린 값으로 계속한다. 풀지 않는 대기(`wait_until_any`
  등)도 있다(9.2절 (c)).
- **fail-stop.** 거절을 스스로 처리하는 application도 끝낸다. 종료 코드 70은 `nvshmem_global_exit`의 코드를 덮는다(9.2절 (e)).
- **응답 쪽 Commit 뒤 손실.** 죽음으로 판정하는 것은 DONE 기다림의 BYE 없는 FIN(과 BADMAGIC, 목록 밖 errno)뿐이다. reset이나 ACK 보내기 실패는 `hw`처럼
  원인 Unknown으로 거절되어 그 rank의 상대를 모르는 대기는 degraded 없이 남는다(9.1절 (g)). 셀은 FIN 경우만 만들었다. 응답 쪽의 다른 출구에는 깃발을
  세우지 않았다.
- **정책 hook.** fail-fast에서 값만 돌려주는 자리다. hold 갈래는 복원 계층이 채우므로 잰 것은 hook이 동작을 바꾸지 않는다는 것뿐이다(H8).
- **M-C 기본 규칙.** degraded 뒤 건강한 쌍의 장애를 거절하고, 그 거절은 죽은 rank만 빼는 shrink의 넘김을 막는다(리뷰 M3, 9.1절 (d)).
- **펌웨어 부하.** 랭크 2개, GIN 문맥 4개에서만 쟀다. 주기 1 ms에서도 지연과 펌웨어 명령 실패가 그대로였지만, rank 수가 많으면 QUERY_QP가 비례해 는다
  (9.1절 (a)). NIC을 같이 쓰는 다른 작업에 대한 영향은 재지 않았다.
- **L-C.** NIC과 CUDA의 교차 확인은 장치 QP 구조의 등록에만 남았다(9.1절 (c)).
- **판정식.** LC1과 PH1의 정책 항은 구조상 틀림이 될 수 없고(리뷰 M2), NC1과 NC2의 판정식은 문장보다 약하다(리뷰 M3). 본 실행에서는 제외 0과 문장
  확인으로 메웠다(13절). iptables 확인이 sudo 실패와 규칙 없음을 가르지 못한다(리뷰 L10, 확인 안 함).
- **표본과 장비.** 셀마다 시행 3–16회, 대상 rank가 셀 안에서 고르지 않다(13절). 노드 한 쌍, 랭크 4개는 GPU 둘을 프로세스 둘씩 나눠 썼다. 장애는
  소프트웨어로 주입했다. 연구 빌드에는 시험 스위치가 있다. 회귀 판정식의 근거(gin-remaining의 5/5 등)는 그 실험의 `SCORE.md`에서 옮겼다.

## 19. 다음 작업

- **50 ms 기다림 줄이기.** 뿌리 CQE가 없는 창에서 상대의 거절을 시간으로 기다리는 대신 helper 소켓으로 상대에게 그 QP의 상태를 묻는다. 뿌리 CQE로
  분류한 감지가 50 ms를 기다린 8회의 원인(처음 본 때의 CQ 창)을 로그로 확인한다.
- **GIN kill 뒤 예제가 끝나지 않는 원인.** 살아남은 rank가 오류를 본 뒤 예제가 어디서 기다리는지 확인한다.
- **release 뒤의 데이터.** 풀린 대기가 오류 값을 돌려주게 하거나, application이 풀린 뒤 호스트 질의로 확인하는 예를 만든다.
- **M-C의 게이트 깃발.** 새 헤더의 장치 코드가 상대 단어를 처음 읽을 때 게이트에 깃발을 세우고, 호스트는 깃발이 있는 QP만 칸 0을 빼고 센다(장치 헤더
  변경, 드라이버 다시 빌드).
- **NVSHMEM의 RST 판정.** 죽은 프로세스의 소켓에 읽지 않은 데이터가 있으면 커널이 RST를 보낸다. 지금은 관리망 손실로 보고 다시 연결만 한다. 거부된
  재연결 두 번을 죽음으로 보는 GIN의 규칙(gin-harden)을 옮길 수 있다.
- **GIN 장치 쪽 감지**(대기 루프 안의 CQ 확인)와 호스트 감시의 비교.
- **응답 쪽 Commit 뒤 reset으로 보인 죽음.** 거절을 미루고 재연결 기계의 판정(거부 둘)을 기다리는 길은 "Commit은 되돌릴 수 없다"는 규칙과 부딪히므로
  따로 설계해야 한다.
- **복원 계층(gin-restore).** 이 실험의 GIN 계층 `hk`에 넣은 정책 hook 아홉(G1–G9)과 상대별 칸 `pe.lostAfterCommit`은 병렬 실험 gin-restore의 통합 정책
  설계가 이 계층에 넣으라고 한 자리다(`~/rdma-error-wt/gin-restore/harness/gpu-initiated/gin_recovery/restore/DESIGN_POLICY.md` 4.10절, 읽기만 함)
  `[소스: 그 문서]`. 복원 계층이 hook의 hold 갈래를 채우고, 그때 `pe.lostAfterCommit`은 약한 증거로만 쓰인다. 이 실험은 gin-restore의 결과를 해석하지 않는다.

## 20. 참고자료

- `../blind/qa/root_cause.md` 2, 3절, `../blind/qa/code_review.md`, `../blind/results/20261009/qa_recount.md`, `../blind/EXPERIMENT.md`
- `../gpu-initiated/gin_recovery/remaining/EXPERIMENT.md` 9.1절, `qa/code_review.md`
- `../gpu-initiated/nvshmem_ft/t1_380/EXPERIMENT.md`, `../gpu-initiated/nvshmem_ft/TRANSPARENT_T1.md`
- gin-restore worktree의 `harness/gpu-initiated/gin_recovery/restore/DESIGN_POLICY.md` 2, 3, 4.10절(정책 hook의 근거, 읽기만)
- 이 실험의 QA: [qa/code_review.md](qa/code_review.md), [results/20261009/qa_recount.md](results/20261009/qa_recount.md)
