# GPU 주도 라이브러리의 장애 감지를 application 호출 밖으로 (gpu-detect)

**목적:** blind-apps가 찾은 결함(GPU 주도 두 라이브러리가 application이 부르는 호출 안에서만 장애를 감지한다)을 라이브러리 계층 둘로 고치고,
수정하지 않은 두 공식 예제에서 고친 동작, 거짓 양성, 비용, 회귀를 사전 등록한 예측으로 잰다.

| 항목 | 값 |
|---|---|
| 상태 | `DRAFT` |
| 담당자 | @unionxic |
| 작성일 | 2026-10-09 |
| 기준 브랜치와 커밋 | `exp/gpu-detect` @ `02a640aa` (master) |
| 사전 등록 태그 | 없음. pilot 뒤 `prereg/gpu-detect-v1` 예정(3절) |
| 마지막 갱신 | 2026-10-09 17:40, 초안(1–12절, 계층 둘, 실행기, 채점기, 독립 리뷰와 반영) |

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
| `hw` | 이 실험의 GIN 연구 빌드: gin-remaining `hr` 위에 9.1절의 계층(파일 하나, 호스트 코드만) | 새 셀, 회귀, 지연 |
| `hwp` | 같은 소스의 운영 빌드(`-DNCCL_GIN_TS_PRODUCTION`). 빌드만 하고 배포하지 않는다 | 컴파일 확인 |
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

**질문.**
1. GIN helper가 라운드 밖에서 QP 상태를 주기적으로 읽고 ERR인 QP에 장애 기록을 만들어 넣으면, 수정하지 않은 GIN 예제의 QP 오류가 무작위 시각에서도
   투명하게 복구되는가. 감지 지연은 주기에 따라 어떻게 달라지고, 장애 없는 지연(latency)에 얼마의 비용이 드는가.
2. NVSHMEM이 작별 없는 FIN을 죽음으로 판정하고 거절 뒤 프로세스를 끝내면(fail-stop), 상대가 죽은 PE와 원격 접근이 회수된 PE가 멈추지 않고 정해 둔
   시간 안에 오류로 끝나는가. release 정책에서는 장치 대기가 실제로 풀리는가.
3. 두 계층이 거짓 양성을 만들지 않는가: 멈춘(SIGSTOP) 상대를 죽음으로 보지 않고, 장애 없는 실행과 정상 종료의 FIN을 장애로 보지 않는가.
4. 기존 GIN 셀(랭크 2개와 4개)의 판정이 그대로인가. M-A, L-C, M-C 수정이 설계대로 동작하는가.

## 2. 가설

| id | 가설 | 다음이 관측되면 틀린 것이다 |
|---|---|---|
| H1 | GIN QP 오류를 놓친 것은 감지가 application 호출 안에만 있기 때문이다. 호스트의 QP 상태 감시가 감지를 맡으면 라운드 자체는 어느 rank의 장치 스레드도 필요 없으므로 투명하게 복구된다 | `hw`의 GIN 예제 QP 오류 셀에서 투명하지 않은 시행이 2회 이상이다. 또는 감시를 끈 같은 빌드가 투명하다 |
| H2 | 감지 지연은 감시 주기의 절반 남짓과 유예(5 ms)로 정해지고, 주기 10 ms의 감시는 장애 없는 지연을 재는 정밀도(4 KiB 0.40 µs, 256 KiB 0.30 µs) 안에서 바꾸지 않는다 | 감지 지연의 중앙값이 주기 순서를 따르지 않는다. 또는 10 ms 감시의 지연 차이가 그 정밀도를 넘는다 |
| H3 | NVSHMEM kill 뒤의 멈춤은 FIN을 판정에 쓰지 않은 것과 거절이 장치 대기에 닿지 않는 것 때문이다. FIN 판정과 fail-stop을 더하면 살아남은 PE는 1 s 안에 종료 코드 70으로 끝나고, 원격 접근 회수는 두 PE가 2 s 안에 끝난다 | 그 셀에서 멈추거나 시간을 넘긴 시행이 2회 이상이다 |
| H4 | release 정책에서 장치 대기 단어는 application이 부르는 장치 대기를 풀어 프로세스가 스스로 끝나게 한다 | release 셀에서 하네스가 끝낸 시행이 2회 이상이다 |
| H5 | 두 계층은 거짓 양성을 만들지 않는다. 멈춘 프로세스의 NIC과 커널은 응답하므로 QP는 RTS이고 FIN도 없다. 정상 종료는 작별을 먼저 보낸다 | 멈춤 셀이나 장애 없는 셀에서 감시 감지, 거절, 죽음 판정이 있는 시행이 허용(1회, 장애 없는 GIN은 0회)을 넘는다 |
| H6 | 두 계층은 기존 동작을 바꾸지 않고(GIN 회귀 셀, NVSHMEM QP 오류 셀), 리뷰 세 항목의 수정은 설계대로 동작한다 | 회귀 셀이나 M-A, M-C, L-C 셀에서 예측과 다른 시행이 나온다 |

## 3. 사전 예측 (측정 전에 작성)

**고정 시점.** 예측 원문은 [predictions.csv](predictions.csv)(35줄)다. 지금은 초안이다.
- 메인 세션이 pilot(hold P1, P2, 9.6절)을 돌린 뒤 예측을 확정한다. pilot 시행은 채점하지 않고, 결과 폴더(`results/<날짜>_pilot/`)도 따로 둔다.
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
- 회귀 시행(`reg/hw/`, `reg/mr_hw/`): gin-remaining의 열 코드가 원래 정의 그대로 만들고(`../gpu-initiated/gin_recovery/remaining/score.py`를 라이브러리로
  불러 씀), `rows_gd.extra_gd2()`, `extra_gd4()`가 열을 더한다.

| 열 | 정의 |
|---|---|
| `outcome`, `result` | blind-apps의 규칙: 하네스가 끝낸 살아남은 rank가 있으면 HUNG, 결과가 틀리고 오류 줄 없이 모두 0이면 SILENT_WRONG, 오류 줄이나 0이 아닌 종료가 있으면 DECLINED, 모두 0이고 결과가 맞으면 TRANSPARENT. GIN은 rank 0의 PASSED와 mismatch 줄, NVSHMEM은 세 크기 줄과 검증 줄(에이전트가 센 것 포함) |
| `n_harness_end` | 하네스가 끝낸(유예나 시간 상한) 살아남은 rank의 수 |
| `dt_err`, `dt_end` | 장애 시각(훅 발화 줄, 신호 응답)에서 살아남은 rank의 첫 오류 줄까지, 마지막 살아남은 rank의 종료까지(s, rain 수신 시각) |
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

### 3.2 셀 키와 판정식 문법

셀 키는 `cell@build`다. 판정식 문법은 gin-remaining과 같다(`../gpu-initiated/gin_recovery/s2_close/EXPERIMENT.md` 3.2절, 그 `score.py`의 평가 함수를
그대로 씀). 더한 것은 하나다: `count()` 밖의 `N_SCORED`는 그 셀의 판정한 시행 수로 바뀐다. 셀마다 계획 수의 75%(올림)보다 판정한 시행이 적으면 그
예측은 "자료 부족"이다. 제외한 시행은 다시 채우지 않는다. 빈 칸은 어떤 비교도 거짓이고 산술은 실패한다.

### 3.3 예측 요약

계획 n은 7절, 전체 판정식은 [predictions.csv](predictions.csv)에 있다. "N"은 그 셀의 판정한 시행 수다.

| 무엇을 예측했나 | id | 셀 | 판정 기준(요약) | 근거 |
|---|---|---|---|---|
| GIN 예제 QP 오류(감시 10 ms): 복구 줄과 함께 투명 | GD1 | `gin_qperr@hw` | N − 1 이상 | 9.1절 (a) `[소스]`. blind-apps의 복구된 2회는 장치 스레드 없이 라운드가 끝났다 `[측정, n=2]` |
| 대상 rank가 훅 뒤 100 ms 안에 감지(감시나 장치) | GD2 | `gin_qperr@hw` | N − 1 이상 | 주기 + 유예 5 ms(뿌리 CQE가 있을 때)나 50 ms(없을 때) + QUERY_QP `[소스, 추론]` |
| 대상 rank의 라운드가 훅 뒤 1 000 ms 안에 재개 | GD3 | `gin_qperr@hw` | N − 1 이상 | 앞 실험의 랭크 2개 라운드 약 2 ms `[측정, 이전 실험]` |
| 주기 1 ms, 100 ms에서도 투명, 감지 70 ms, 200 ms 안 | GD4 | `gin_qperr_w1@hw`, `gin_qperr_w100@hw` | 셀마다 N − 1 이상 | `[소스, 추론]` |
| 감지 지연의 중앙값이 주기 순서(1 < 10 < 100 ms) | GD5 | 셋 | 중앙값 비교 | 주기 안 위상이 고르다 `[추론]` |
| 대조(`hr`, `hq`): 같은 장애가 대부분 시간 상한까지 멈춤 | GC1 | `gin_qperr@hr`, `@hq` | 셀마다 N − 2 이상 | blind-apps 14/16 `[측정]` |
| 대조(`hw`에서 감시 끔): 멈춤 | GC2 | `gin_qperr_w0@hw` | N − 1 이상 | 더한 감지는 감시뿐 `[소스]` |
| GIN kill: 투명 아님, 5 s 안 오류, 감시 감지 없음 | GR1 | `gin_kill@hw` | N − 1 이상 | blind-apps 10/10 `[측정]` |
| GIN 1–8 s 멈춤: 투명, 죽음과 거절과 감시 감지 없음 | GF1 | `gin_stop@hw` | N − 1 이상 | 멈춘 프로세스의 NIC과 커널은 응답 `[추론]` |
| GIN 장애 없음: 투명, 감시 감지와 거절 없음 | GF2 | `gin_none@hw` | N 모두 | `[소스]` |
| NVSHMEM kill: FIN 판정 0.1 s 안, 살아남은 PE가 스스로 종료 코드 70으로 1 s 안 | ND1 | `nvs_kill@t1w` | N − 1 이상 | FIN 0.03–0.48 ms `[측정, blind-apps n=7]` |
| 원격 접근 회수: 두 PE가 거절하고 2 s 안에 종료 코드 70 | ND2 | `nvs_remacc@t1w` | N − 1 이상 | 거절 4.9–7.6 ms `[측정, blind-apps n=8]` |
| 대조(t1_380) kill: 오류 줄 없이 멈춤 | NC1 | `nvs_kill@t1_380` | N − 1 이상 | blind-apps 7/7 `[측정]` |
| 대조(t1_380) 원격 접근 회수: 거절하고도 멈춤 | NC2 | `nvs_remacc@t1_380` | N − 1 이상 | blind-apps 8/8 `[측정]` |
| release 정책: 장치 대기 해제 줄과 함께 모든 프로세스가 스스로 끝남 | NR1 | `nvs_kill_rel@t1w`, `nvs_remacc_rel@t1w` | 셀마다 N − 1 이상 | `[소스]`. 죽은 상대가 있을 때 `nvshmem_finalize`의 부트스트랩 `[미확인]` |
| NVSHMEM PE 0 멈춤: 투명, 죽음과 거절 없음 | NF1 | `nvs_stop@t1w` | N − 1 이상 | `[추론]` |
| NVSHMEM 장애 없음: 투명, 거절과 FIN 판정 없음, 적어도 한 PE가 작별을 보냄 | NF2 | `nvs_none@t1w` | N − 1 이상 | 먼저 정리하는 PE가 작별을 보내고, 그 작별과 FIN을 이미 읽은 PE는 보낼 곳이 없다(리뷰 H2) `[소스]` |
| 장치 대기 단어 확인의 비용: 64 MiB 반복당 ms가 t1_380의 1.10배 이하 | NO1 | `nvs_none@t1w`, `@t1_380` | 중앙값 비교 | `[소스, 추론]`. blind-apps에서 실행 속도가 둘로 갈림 `[측정]` |
| NVSHMEM QP 오류: 투명(회귀) | NQ1 | `nvs_qperr@t1w` | N − 1 이상 | blind-apps 14/14 `[측정]` |
| GIN 랭크 2개 회귀(로컬 QP 오류, 상대 QP 오류, 양방향): 투명 | RG1 | `f1_b`, `f3_b`, `bidirf_sym_b` `@hw` | 셀마다 N 모두 | gin-remaining RG1 `[문서, 다시 세지 않음]` |
| 랭크 2개 kill: 2 s 안 peer-dead 거절 | RG3 | `f4_b@hw` | N 모두 | gin-remaining RG3 `[문서]` |
| 받기만 하는 rank의 대기가 2 s 안에 풀림 | RG4 | `hd_rxdeath_b@hw` | N 모두 | gin-remaining RG4 `[문서]` |
| 원격 접근 오류: rank 0 거절, rank 1 대기 해제, abort 5 s 안 | RG5 | `f2rel_b@hw` | N 모두 | gin-remaining RG5 `[문서]`. 장치가 유예 안에 먼저 보고 `[추론]` |
| 통계 API: 라운드 1, 복구 1(감시가 두 번째 라운드를 만들지 않음) | RG7 | `f1_b@hw` | N 모두 | `[소스]` |
| 랭크 4개 장애 없음, 한 쌍 로컬 QP 오류: 투명 | RG8 | `mr4_none@hw`, `mr4_f1_01@hw` | 셀마다 N 모두 | gin-remaining RG8 `[문서]` |
| rank 3 kill, 시간 제한 없는 받기: 판정 2 000–3 000 ms 뒤 해제, 생존 rank 보내기 완료 | RG9 | `rm4_kill3_untimed@hw` | N 모두 | gin-remaining DG1, DG3 `[문서]` |
| 순환하는 시작 쪽 셋: handshake timeout도 거절도 없이 복구 | RG10 | `mr4_cyc_stall@hw` | N − 1 이상 | gin-remaining CY1 `[문서]` |
| M-A: rank 3이 낮은 rank의 REQ 둘(0, 1)에 기다림 안에서 답하고 투명 | MA1 | `mr4_twolow_stall@hw` | N − 1 이상 | 9.1절 (b) `[소스, 추론]` |
| M-C 기본 규칙: degraded 뒤 건강한 쌍 0-1의 장애는 그 쌍의 거절 | MC1 | `rm4_late01@hw` | N 모두 | 9.1절 (d) `[소스]` |
| M-C 대조(`NCCL_GIN_TS_DEGRADED_ROUNDS=1`): 같은 장애가 복구 | MC2 | `rm4_late01_rounds@hw` | N 모두 | gin-remaining 9.1절 (c) `[소스]` |
| L-C: 모든 rank에서 NIC 경로가 NIC만 쓴 자체 시험과 함께 켜짐 | LC1 | `gin_none@hw`, `f1_b@hw` | 셀마다 N 모두 | 9.1절 (c) `[소스]` |
| 4 KiB 지연: 감시 10 ms와 끔의 차이 0.40 µs 이하 | LT1 | `lat_4k_w10@hw`, `lat_4k_w0@hw` | 실행 중앙값 | `[소스, 추론]` |
| 256 KiB 지연: 차이 0.30 µs 이하 | LT2 | `lat_256k_w10@hw`, `lat_256k_w0@hw` | 실행 중앙값 | 같음 |
| 4 KiB 지연: 감시 1 ms와 끔의 차이 1.0 µs 이하 | LT3 | `lat_4k_w1@hw`, `lat_4k_w0@hw` | 실행 중앙값 | 초당 QUERY_QP 약 4 000번의 영향은 잰 적 없음 `[미확인]` |
| 256 KiB 지연: 같은 비교 1.0 µs 이하 | LT4 | `lat_256k_w1@hw`, `lat_256k_w0@hw` | 실행 중앙값 | 같음 |

감시 주기 100 ms의 지연 셀은 두지 않았다(10 ms의 비용이 정밀도 안이면 100 ms도 그렇다고 본다 `[추론]`). 셀 `lat_*_w100`은 실행하고 설명용으로만 보고한다.

판정식을 읽을 때의 주의.
- GD2의 감지는 감시와 장치 중 먼저 나온 것이다. 어느 쪽이 먼저였는지(`det_by`)는 설명용으로 따로 센다. 감시가 처음 보고 유예 동안 장치가 먼저 보고하면
  감시는 기록을 만들지 않는다(9.1절 (a)).
- NVSHMEM 셀의 kill 대상은 무작위다. 멈춤 셀은 PE 0만 멈춘다(4절).
- RG1–RG10은 gin-remaining의 판정식에서 셀 키만 바꿨다. 그 수(5/5 등)는 gin-remaining `SCORE.md`의 값이고 이 문서에서 다시 세지 않았다 `[문서]`.

## 4. 범위

**포함.**
- GIN 계층 하나([hw_layer.diff](hw_layer.diff), `hr` 트리 기준, 파일 하나, 호스트 코드만)와 그 운영 빌드(컴파일 확인만).
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

## 5. 테스트베드와 버전

| 항목 | 값 | 확인 방법과 날짜 |
|---|---|---|
| 노드, NIC, GPU, CUDA | blind-apps와 같다: rain(rank 0, Quadro RTX 5000, sm_75), sunny(rank 1, RTX A4000, sm_86), ConnectX-6, RoCE v2, CUDA 12.8 | `../blind/EXPERIMENT.md` 5절 `[측정, 이전 실험]` |
| GIN 기준 트리 | 스크래치 `agent_ts2hr` 작업 트리 = `hr_layer.diff`(md5 `66f61272`), 빌드 `hr` libnccl `2dee2b5b`, `hrp` `786f70bc` | `build_gd.sh gin-setup`이 md5를 확인하고 복사, 2026-10-09 `[측정]` |
| GIN 새 빌드 | `hw` libnccl `efc48ca1a8368eb7feadac5d57f8ff23`, `hwp` `d3b4a2fe704d5edfdbe154360bae9f98`(배포 안 함), `gd_gin_ring` `719dfaab5a3f4294ab89b12ea102ed5b`(SASS sm_75, sm_86). 장치 헤더의 include digest `a27dac89`가 `hr`과 같다 | `[측정]` 2026-10-09 17:33 rain, 스크래치 `agent_gd/out/build_info.txt` |
| NVSHMEM 기준 트리 | 스크래치 `agent_t1_380/src` 작업 트리(t1_380 diff), 설치의 전송 모듈 `d6ae3699` | `build_gd.sh nvs-setup`이 확인하고 복사 `[측정]` |
| NVSHMEM 새 빌드 | `t1w` 전송 모듈 `86c39e91e568fed0a271ca7099b1bb2c`, 호스트 라이브러리 `f3522de834c20c3ffd2044c598485e5d`, UID 부트스트랩 `26da2c31`(t1_380과 같음), `libnvshmem_device.a` `e5ec0e70`, `gd_nvs_rr` `6e93ba5938b0e8f096817dcfabe01907`(SASS sm_75, sm_86), `gd_nvs_boot.so` `e3264e83`(blind-apps의 `blind_nvs_boot.so`와 같음) | `[측정]` 같은 때 |
| 대조 번들(읽기만) | `~/gi-bundle/gin_ts2/hq`(`c1311625`), `hr`(`2dee2b5b`), `hr/gin_ts2`(`4e81d8d8`), `mr/hr/gin_mr`(`d588e9ce`), `~/blind-bundle/hq/blind_gin_ring`(`074ee68c`), `~/blind-bundle/nvs/`(`blind_nvs_rr` `26187ab9`, 전송 `d6ae3699`) | 앞 실험의 배포 확인 `[측정, 이전 실험]`. 배포 때 `deploy_gd.sh`가 두 노드에 있는지 확인 |
| 변경분 | [hw_layer.diff](hw_layer.diff), [t1w_layer.diff](t1w_layer.diff). 전체 diff는 순정에 앞 계층 diff들과 이 diff를 차례로 적용한 것(9.4절) | [make_diff_gd.sh](make_diff_gd.sh): 두 diff가 기준 커밋에 다시 적용되어 트리를 재현함 `[측정]` |

## 6. 변수

- **독립변수.**
  - 빌드: GIN `hw`, `hr`, `hq`. NVSHMEM `t1w`, `t1_380`.
  - GIN 감시 주기 `NCCL_GIN_TS_QPWATCH_MS`: 0(끔), 1, 10(기본), 100. NVSHMEM 정책 `NVSHMEM_IBGDA_FT_T1_FAILSTOP_MS`: 0(fail-stop, 기본), −1(release).
  - 장애: 없음, QP 오류 훅(GIN, NVSHMEM), 원격 접근 회수 훅(NVSHMEM), SIGKILL, SIGSTOP 1–8 s. 시각은 `schedule.json`의 `u_t`로 창 안에서 고르게.
  - 회귀 셀의 장애(gin-remaining 정의), 새 랭크 4개 셀 둘(M-A, M-C).
- **종속변수.** 3.1절의 열: 결과 분류, 결과 검사, 감지 줄과 감지 지연, 복구 시각, 거절과 죽음 줄, 종료 코드와 종료 시각, FIN 판정과 작별 줄, 장치 대기
  해제 줄, 감시의 QUERY_QP 수와 소요, 장애 없는 지연(p50), ring-reduce 반복당 시간.
- **통제변수.**
  - 시행마다 프로세스를 새로 띄운다. rank 0은 rain, rank 1은 sunny. 대상 rank는 0과 1 반씩(NVSHMEM 멈춤은 PE 0만).
  - GIN app: blind-apps와 같은 NCCL 환경(`NCCL_GIN_TYPE=3`, 분류, 복구, 투명 복구 켬, IB 타임아웃 14, `NCCL_DEBUG=WARN`), helper 포트는 시행마다 고른
    16개 묶음. NVSHMEM app: blind-apps와 같은 환경(t1_380의 `env_t1.sh` 설정, 대칭 heap 160 MiB, `ring-reduce -b 16M -e 64M -n 150 -w 2`).
  - 하네스: 한 rank가 끝난 뒤 유예 10 s, 시행 시간 상한 GIN 20 s, NVSHMEM 30 s(blind-apps는 20 s, 60 s). 멈춤과 해제를 가리기에 충분하다
    `[추론: GIN 트래픽 약 0.14 s, RETRY_EXC 약 3.6 s, NVSHMEM 실행 3.2–6.3 s]`.
  - 포트: rendezvous와 helper 묶음 모두 29000–30999에서 두 노드에 어떤 소켓도 없는 것.
  - 회귀 셀: gin-remaining의 실행기와 드라이버를 그대로 쓴다(빌드만 `hw`).

## 7. 실험 셀, 반복 수, 대조군

app 셀의 원문은 [cells.json](cells.json), 회귀 셀은 [cells_reg.sh](cells_reg.sh)와 [hold.sh](hold.sh)다. 시행 목록은 `apprun.py plan`이 시드로 만든
[schedule.json](schedule.json)이다(hold 안에서 순서를 섞음, 대상과 `u_t`, `u_d`를 고르게 뽑음).

**app 셀.** 시각 창: GIN 훅은 GDAKI 문맥 생성 뒤 3–116 ms, GIN kill과 멈춤은 기준 줄(`=== Comparing GIN ...`) 뒤 0.003–0.116 s(blind-apps의
`calib.json` 그대로). NVSHMEM 훅은 연결 뒤 500–2 500 ms, kill과 멈춤은 기준 줄 뒤 0.5–2.5 s(blind-apps는 0.515–4.374 s였으나 빠른 실행 3.2 s에서
장애가 실행 뒤로 떨어져 3회가 제외되었다: blind-apps `qa/code_review.md` L6 `[측정, 이전 실험]`. 창을 빠른 실행 안으로 줄였다).

| 셀 | 조건 | 빌드와 반복 수 | 종류 |
|---|---|---|---|
| `gin_qperr` | GIN 예제, 대상 rank의 GIN QP 모두 ERR, 감시 10 ms | `@hw` 16, `@hr` 6, `@hq` 6 | 새 셀, 대조 |
| `gin_qperr_w0`, `_w1`, `_w100` | 같고 감시 0(끔), 1, 100 ms | `@hw` 4, 8, 8 | 대조, 새 셀 |
| `gin_kill`, `gin_stop`, `gin_none` | GIN 예제 kill, 1–8 s 멈춤, 장애 없음 | `@hw` 6, 8, 6 | 회귀, 거짓 양성 |
| `nvs_kill`, `nvs_remacc` | NVSHMEM 예제 kill, 원격 접근 회수(fail-stop) | `@t1w` 8, 8. `@t1_380` 4, 4 | 새 셀, 대조 |
| `nvs_kill_rel`, `nvs_remacc_rel` | 같고 release 정책. 시간 상한 60 s(풀린 뒤 예제가 틀린 원소를 모두 찍는다) | `@t1w` 5, 5 | 새 셀 |
| `nvs_stop`, `nvs_none`, `nvs_qperr` | PE 0 멈춤 1–8 s, 장애 없음, QP 오류 | `@t1w` 8, 8, 6. `nvs_none@t1_380` 6 | 거짓 양성, 비용, 회귀 |

**회귀와 지연 셀**(빌드 `hw`, 드라이버는 gin-remaining의 것).

| 셀 | 조건 | 반복 수 | 종류 |
|---|---|--:|---|
| `f1_b`, `f3_b`, `bidirf_sym_b`, `f4_b`, `f2rel_b`, `hd_rxdeath_b` | gin-harden 정의(gin-remaining과 같음) | 각 5 | 회귀 |
| `lat_4k_w<P>`, `lat_256k_w<P>` | 장애 없음, 3 000번 왕복, 감시 P = 0, 1, 10, 100 ms(섞어서) | 각 5 | 비용 |
| `mr4_none`, `mr4_f1_01`, `rm4_kill3_untimed`, `mr4_cyc_stall` | gin-multirank, gin-remaining 정의 | 각 5 | 회귀 |
| `mr4_twolow_stall` | 랭크 4개, rank 0(QP 0>3), 1(1>3), 2(2>1), 3(3>2)에 로컬 QP 오류 6 000 ms, 네 rank에 helper 멈춤 300 ms(정지 뒤): rank 3이 rank 2를 기다리는 동안 낮은 rank 0, 1의 REQ가 함께 기다림 | 5 | 새 셀(M-A) |
| `rm4_late01`, `rm4_late01_rounds` | 랭크 4개, rank 3 kill 9 000 ms(받기 한도 10 s), rank 0의 QP 0>1에 로컬 QP 오류 13 000 ms(degraded 해제 뒤). 둘째는 `NCCL_GIN_TS_DEGRADED_ROUNDS=1` | 3, 3 | 새 셀, 대조(M-C) |

**합계.** app 130회(GIN 68, NVSHMEM 62), 회귀와 지연 101회(랭크 2개 30, 지연 40, 랭크 4개 31). 셀 키 40개(app 19, 회귀와 지연 21), 예측 35줄. 대조군은 `hr`, `hq`, t1_380과
같은 빌드 안의 감시 끔, release 대 fail-stop, M-C 규칙 두 가지다.

**시간 어림** `[추론]`. 시행 사이 비용 약 3 s, hold마다 스냅숏과 유휴 링크 대기 약 1분. app 시행은 GIN 투명 약 7 s, 멈춤 23 s, NVSHMEM 약 10 s,
멈춤 33 s(blind-apps pilot과 본 실행의 값에서). 회귀는 gin-remaining의 "시행마다 `wall_s` + 2.7 s"로.

| hold | 내용 | 어림 |
|---|---|--:|
| P1 | pilot app 14회(9.6절) | 4분 |
| P2 | pilot 회귀 8회(`f1_b`, `f2rel_b`, 4 KiB 지연 감시 끔과 1, 10 ms, M-A 셀, M-C 셀 둘) | 3분 |
| G1 | GIN QP 오류 `hw` 16, 대조 16(`hr` 6, `hq` 6, 감시 끔 4) | 9분 |
| G2 | 주기 1, 100 ms 각 8, kill 6, 멈춤 8, 장애 없음 6 | 7분 |
| N1 | NVSHMEM kill과 원격 접근 회수(`t1w` 8, 8, `t1_380` 4, 4), release 5, 5 | 8–12분 |
| N2 | 멈춤 8, 장애 없음 `t1w` 8와 `t1_380` 6, QP 오류 6 | 6.5분 |
| R1 | 랭크 2개 회귀 30, 지연 40 | 7.5분 |
| R2 | 랭크 4개 회귀 20 | 8.5분 |
| R3 | M-A 5, M-C 3 + 3 | 5분 |

pilot 약 7분, 본 실행(G1–R3) 약 52분, 나쁜 경우(대조가 모두 상한까지 멈추고 release 셀이 60 s 상한까지 가고 다시 도는 hold가 생김) 약 70분이다. N1은
나쁜 경우 800 s 예산을 넘겨 `chain.sh`가 같은 hold를 다시 돌 수 있다. 어느 hold도 880 s 한도 안이다.

## 8. 제외 기준과 중단 기준

**제외 기준.** 제외한 시행은 다시 채우지 않고 셀마다 따로 센다(`SCORE.md` 끝 표).
- pilot(`results/<날짜>_pilot/`)은 채점하지 않는다.
- app: 걸리지 않은 장애(`applied == 0`: 훅 발화 줄이 없거나 옮긴 QP가 0, 에이전트가 신호를 보내지 못함, 장애 시각 전에 끝남), 시작 실패(`void == 1`),
  설정 확인 실패(`config_ok == 0`).
- 회귀: gin-remaining 8절의 규칙(랑데부 실패, 장애 미적용, 트래픽 밖의 kill, 순환 셀의 라운드 퍼짐 > 250 ms, 펌웨어 초과). 새 셀은 같은 규칙에
  M-A 셀의 발화 "0:2;1:5;2:7;3:11"과 라운드 퍼짐 ≤ 250 ms, M-C 셀의 발화 "0:0"과 트래픽 안의 kill을 더한다(`score.py` `status4_new`).

**설정 확인.** 하나라도 어긋나면 그 시행은 제외되고, 메인 세션은 그 블록을 멈춘 뒤 원인을 12절에 적는다.
- GIN `hw` app 시행: 살아남은 모든 rank에 투명 복구 시작 줄, `GIN/TS: detect=1` 줄(셀의 `qpwatch_ms`), NIC 경로 켬 줄(호스트 shadow와 같은 QP 구조 1개
  이상), 꺼짐 줄 없음. `hr`: `remaining=1` 줄이 있고 `detect=1` 줄이 없음. `hq`: 둘 다 없음.
- NVSHMEM `t1w`: 모든 PE의 `t1w: gpu-detect=1` 줄(셀의 `failstop_ms`). t1_380: 그 줄이 없음. 둘 다 `transparent mode off`가 없음.
- 회귀: gin-remaining 8절의 `hr` 확인(시작 줄, 드라이버 번들 `hr`, NIC 경로) + 모든 rank의 `detect=1` 줄과 셀의 `qpwatch_ms`.

**pilot에서 보이는 결함.** 태그 전이므로 고칠 수 있다. 미리 정해 둔 예:
- 감시가 장애 없는 실행이나 멈춤에서 감지 줄을 남김: 원인(시작이나 정리 때의 QP 상태)을 고치고 다시 빌드, 새 디렉터리로 배포.
- NVSHMEM 장애 없는 실행에서 FIN 판정이나 fail-stop: 작별 경로를 고친다.
- M-A 셀의 라운드가 겹치지 않음(퍼짐 > 250 ms, 또는 rank 3이 REQ 둘을 기다림 안에서 받지 않음): 멈춤 길이를 한 번 바꿀 수 있다. M-C 셀의 훅이 트래픽
  밖: `LATE_MS`를 한 번 바꿀 수 있다.
- release 셀이 `nvshmem_finalize`에서 멈춤(죽은 상대와의 부트스트랩): 예측 NR1을 kill 셀에서 고치거나 빼고 12절에 적는다.

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

### 9.1 GIN 계층 `hw` ([hw_layer.diff](hw_layer.diff))

파일 하나(`gin_host_gdaki.cc`), 호스트 코드만이다. 장치 헤더는 `hr`과 같으므로 `hr` 헤더로 빌드한 드라이버와 예제가 그대로 맞는다 `[소스]`.

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

### 9.3 실행기

- [apprun.py](apprun.py): `../blind/blindrun.py`의 사본을 고친 것(원본은 그대로). 눈가림을 뺐고, 빌드 선택(`BUILDS`), 셀의 환경 변수, 29000–30999 포트,
  작업마다 시간 상한과 유예를 더했다. 에이전트는 blind-apps의 `node_agent.py`와 바이트 단위로 같은 사본(`~/gd-bundle/agent/`)이다. 시행 파일과 줄 형식은
  blind-apps와 같다. 시행 목록은 `apprun.py plan --seed <hex>`가 [cells.json](cells.json)에서 만든 [schedule.json](schedule.json)이고, 실행기는 그
  파일의 `cells_sha256`이 지금의 `cells.json`과 다르면 돌지 않는다.
- [cells_reg.sh](cells_reg.sh): gin-remaining의 `run_trial_hr.sh`, `run_mr_hr.sh`를 그 폴더에서 그대로 부른다(빌드 `hw`, 드라이버 번들 `hr`). 셀 정의는
  gin-remaining의 `cells.sh`에서 옮겼고 새 셀 넷(지연 감시 주기, M-A, M-C 둘)을 더했다.
- [hold.sh](hold.sh): 스냅숏, 남은 프로세스 기다림, STOP 규칙은 blind-apps와 gin-remaining의 hold와 같다. [chain.sh](chain.sh): hold마다
  `cluster_run.sh -w 10800 -t gd-<hold>` 안에서 `timeout -s KILL 880`. app hold에 결과 없는 시행이 남으면 같은 hold를 두 번까지 다시 돈다.

### 9.4 빌드 ([build_gd.sh](build_gd.sh), 세션 스크래치 `agent_gd`)

1. `gin-setup`: `agent_ts2hr`의 소스, `build/`, `build-hrp/`를 `agent_gd/gin`으로 복사(`build-hrp/`는 `build-hwp/`), 의존 파일과 장치 manifest의 경로를
   바꾸고 시각을 돌려준다. `hr` 작업 트리를 스크래치 저장소에 "gin-remaining hr" 커밋으로 남긴다. 복사 직후 `make -n`은 버전 표시 하나만 컴파일한다.
2. `gin-hw`, `gin-hwp`: 이 계층을 작업 트리에 두고 증분 빌드. 바뀐 파일은 `gin_host_gdaki.cc` 하나다.
3. `gin-app`: 예제(`main.cu`, `kernels.cuh` 그대로)와 `../blind/boot/gin_boot.cc`를 `hw` 헤더로 빌드 → `gd_gin_ring`.
4. `nvs-setup`: `agent_t1_380/src`를 `agent_gd/nvs/src`로 복사, t1_380 작업 트리를 "t1_380" 커밋으로 남기고, t1_380의 cmake 설정 그대로 새 빌드 디렉터리를
   만든다. `nvs-lib`: 계층을 두고 빌드(장치 헤더가 바뀌므로 전체 빌드, 약 15분), 설치.
5. `nvs-app`: `ring-reduce.cu`(그대로)를 `t1w` 설치로 빌드 → `gd_nvs_rr`, 부트스트랩 플러그인 → `gd_nvs_boot.so`.
6. `info`: `agent_gd/out/build_info.txt`. [make_diff_gd.sh](make_diff_gd.sh): 두 diff를 쓰고, 기준 커밋을 복제한 곳에 다시 적용해 트리와 같은지 확인한다.

재현: GIN은 순정 NCCL v2.32.3-1 + `../gpu-initiated/gin_recovery/remaining/gin_transparent_hr.diff` + `hw_layer.diff`. NVSHMEM은 공식 v3.8.0-0 +
`../gpu-initiated/nvshmem/nvshmem_ibgda_fault_inject.diff` + `../gpu-initiated/nvshmem_rootcause/nvshmem_nrc_proxy_sq_dbr.diff` +
`../gpu-initiated/nvshmem_ft/t1_380/nvshmem_ibgda_t1_380.diff` + `t1w_layer.diff`. 모든 컴파일은 nice 19, 유휴 I/O 우선순위다.

### 9.5 배포 ([deploy_gd.sh](deploy_gd.sh), 메인 세션)

두 노드의 새 디렉터리에만 둔다: `~/gi-bundle/gin_ts2/hw/`(libnccl과 링크), `~/gd-bundle/{gin,nvs,nvs/lib,agent}/`. 대상이 있으면 멈춘다. 소스가 기대
md5와 다르면 멈춘다(기대값은 스크립트의 `WANT_*`, 12절의 마지막 빌드). 읽기만 하는 대조 파일이 두 노드에 있는지 확인한다. 배포 뒤 새 파일의 md5가 두
노드와 소스에서 같은지, `ldd`가 번들 안의 라이브러리를 찾는지, 기존 번들(`~/gi-bundle`의 `hw/` 밖, `~/blind-bundle`)의 모든 파일 md5가 그대로인지 확인한다.
확인은 파일로만 받는다. GPU 프로그램도 RDMA 트래픽도 없다.

### 9.6 메인 세션의 명령(순서대로)

경로는 이 worktree 기준이다. `D=harness/gpu-detect`, `R=$D/results`.

1. **배포**(약 2분): `bash $D/deploy_gd.sh $D/deploy_check.txt`. 확인 파일에 "new files: rain == sunny", 모든 "source == deployed", "existing bundles
   unchanged"가 있어야 한다. 배포 전에 sunny에서 읽기만: `ssh <sunny> 'ls -d ~/gd-bundle ~/gi-bundle/gin_ts2/hw 2>&1'`(둘 다 없어야 함).
2. **pilot**(약 7분, 채점 안 함): `bash $D/chain.sh $R/<날짜>_pilot P1 P2`. 확인: P1의 각 셀이 설정 확인을 통과하고 장애가 걸림, `gin_none`과 `nvs_none`에
   감시 감지와 거절이 없음, `nvs_none`의 두 PE가 작별을 보냄, `gin_qperr@hw`의 감지 줄과 복구, `nvs_kill@t1w`의 FIN 판정과 종료 코드 70, release 셀이
   스스로 끝남, P2의 M-A 셀에서 rank 3의 기다림 안 응답 둘, M-C 셀 두 개의 발화와 kill이 트래픽 안. 읽기: `python3 $D/rows_gd.py $R/<날짜>_pilot`과
   pilot 폴더의 사본에 `score.py`.
3. **pilot 뒤**: 고친 것을 12절에 적고(3절 규칙), 셀을 바꿨다면 `python3 $D/apprun.py plan --seed $(od -An -N8 -tx8 /dev/urandom | tr -d ' \n')`로
   `schedule.json`을 다시 만든다.
4. **사전 등록**: `cd $D && { echo "gpu-detect pre-registration"; for f in predictions.csv cells.json schedule.json apprun.py rows_gd.py score.py cells_reg.sh hold.sh chain.sh hw_layer.diff t1w_layer.diff; do echo "$f sha256 $(sha256sum < $f | cut -c1-64)"; done; } > PREREG.txt`.
   상태 `PREREGISTERED`, 12절 기록과 함께 커밋 하나, 그 커밋에 `prereg/gpu-detect-v1`.
5. **본 실행**(약 52분, 나쁜 경우 65분): `bash $D/chain.sh $R/<날짜> G1 G2 N1 N2 R1 R2 R3`.
6. **채점**: `python3 $D/score.py $R/<날짜>` → `SCORE.md`, `trials_scored.csv`. 원자료는 Release에 올린다.

### 9.7 출력

- app 시행: `results/<날짜>/raw/<id>/{r0.log,r1.log,a0.log,a1.log,trial.meta}`(줄마다 rain 수신 시각). 회귀: `results/<날짜>/reg/hw/`,
  `reg/mr_hw/`(gin-remaining 실행기의 파일). hold마다 스냅숏, `runner.log`, `chain.out`, `hold_*.out`. 원자료는 커밋하지 않고 Release에 올린다.

## 10. 완료 조건과 QA 기준

- [ ] pilot(P1, P2)을 돌리고 12절에 적은 뒤 고칠 것을 고치고 태그를 달았다.
- [ ] 모든 셀이 계획한 반복 수만큼 실행됐다. 제외를 셀마다 따로 센 표가 있다(`SCORE.md` 끝 표).
- [ ] 예측 35줄마다 판정(맞음, 틀림, 자료 부족)과 조건을 만족하지 않은 시행 목록이 있다.
- [ ] 다른 에이전트가 `score.py`를 보지 않고 원자료에서 핵심 수치를 다시 셌다(결과 분류, 감지 지연, FIN 판정과 종료 시각, 지연 중앙값, 회귀 판정).
- [x] 다른 에이전트가 두 계층을 읽고 리뷰했다(12절).
- [ ] 다른 에이전트가 실행기와 채점기를 리뷰했다.
- [ ] pilot과 제외 시행이 결과에 섞이지 않았다.
- [ ] 새 빌드의 md5, 두 diff, 재적용 확인을 5절과 12절에 적었다.
- [ ] 원자료를 Release에 올리고 `DATA.md`에 적었다.
- [ ] hold 전후 mlx5 스냅숏에 새 명령 오류가 없었고, iptables 규칙이 늘지 않았고, CUDA 메모리 오류가 없었다.

## 11. 작업 체크리스트

- [x] blind-apps 원자료에서 기준 수치를 다시 셈(1절)
- [x] GIN 계층(감시, M-A, L-C, M-C), 빌드 `hw`, `hwp`, 예제 `gd_gin_ring`
- [x] NVSHMEM 계층(작별과 FIN 판정, fail-stop, 장치 대기 단어), 빌드 `t1w`, 예제 `gd_nvs_rr`
- [x] 두 diff와 재적용 확인
- [x] 실행기, 셀, hold, chain, 배포, 파서, 채점기, 예측 초안
- [x] 채점기 합성 시험(실제 측정 아님, 12절)
- [x] 독립 리뷰(두 계층)와 반영(12절)
- [x] 질문, 가설, 셀, 예측 초안 (`DRAFT`)
- [ ] 배포(메인 세션)
- [ ] pilot P1, P2(메인 세션, 채점 안 함), 점검
- [ ] 고정 절 완성, 상태 `PREREGISTERED`, 해시 기록을 커밋 하나로 만들고 그 커밋에 `prereg/` 태그
- [ ] 본 실행 G1–R3 (`RUNNING`)
- [ ] 채점 (`QA`), 독립 재계산과 측정 코드 리뷰
- [ ] 결과 정리, 원자료 Release, PR
- [ ] 결론 확정 (`COMPLETE`)

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

## 13. 사전 등록 이후 변경

> 기존 문장을 고치지 않고 여기에 덧붙인다.

| 날짜 | 무엇을 | 이유 | 영향 범위 | 커밋 |
|---|---|---|---|---|

## 14. 원자료와 결과표

| 무엇 | 경로 또는 Release 자산 | n |
|---|---|--:|

## 15. 결과 요약

`[미확인]` 아직 측정 전이다.

## 16. QA와 재현성

`[미확인]` 아직 측정 전이다. 재현은 9.4절.

## 17. 결론

## 18. 한계

- 이 문서의 계층 동작은 모두 `[소스]`이고 클러스터에서는 아직 아무것도 돌리지 않았다.
- 회귀 판정식의 근거(gin-remaining의 5/5 등)는 그 실험의 `SCORE.md`에서 옮겼고 다시 세지 않았다.
- 감시는 장애를 QP 상태로만 본다. 이 rank의 QP가 RTS인 채 상대만 망가진 경우(상대 QP 오류, 보낼 것 없음)는 상대의 감시나 RETRY_EXC를 기다린다. 받기만 하는
  QP와 예약한 WQE가 없는 QP는 감시가 다루지 않는다(9.1절 (a)).
- 응답 쪽 오류의 50 ms 기다림(리뷰 M2)은 상대의 거절이 그 안에 온다는 가정이다. 상대의 장치 스레드도 감시도 그 안에 보고하지 못하면 LOCAL_QP_ERR 라운드가
  실패한 쓰기를 다시 낼 수 있다 `[추론]`.
- M-C의 기본 규칙은 degraded 뒤 건강한 쌍의 장애를 거절하고, 그 거절은 죽은 rank만 빼는 shrink의 넘김을 막는다(리뷰 M3, 9.1절 (d)).
- 감시는 펌웨어 명령을 더한다(주기 1 ms에서 rank마다 초당 약 4 000번). 공유 NIC에서의 영향은 이 실험의 지연 셀과 mlx5 확인으로만 본다(리뷰 M4).
- L-C 수정 뒤 NIC과 CUDA의 교차 확인은 장치 QP 구조의 등록에만 남았다(9.1절 (c)).
- release 정책은 대기를 풀 뿐 데이터를 주지 않는다. 확인하지 않는 application은 틀린 값으로 계속한다(9.2절 (d)).

## 19. 다음 작업

- M-C의 게이트 깃발: 새 헤더의 장치 코드가 상대 단어를 처음 읽을 때 게이트에 깃발을 세우고, 호스트는 깃발이 있는 QP만 칸 0을 빼고 센다(장치 헤더 변경,
  드라이버 다시 빌드).
- NVSHMEM의 RST 판정: 죽은 프로세스의 소켓에 읽지 않은 데이터가 있으면 커널이 RST를 보낸다. 지금은 관리망 손실로 보고 다시 연결만 한다. 거부된 재연결 두 번을
  죽음으로 보는 GIN의 규칙(gin-harden)을 옮길 수 있다.
- GIN 장치 쪽 감지(대기 루프 안의 CQ 확인)와 호스트 감시의 비교.

## 20. 참고자료

- `../blind/qa/root_cause.md` 2, 3절, `../blind/qa/code_review.md`, `../blind/results/20261009/qa_recount.md`, `../blind/EXPERIMENT.md`
- `../gpu-initiated/gin_recovery/remaining/EXPERIMENT.md` 9.1절, `qa/code_review.md`
- `../gpu-initiated/nvshmem_ft/t1_380/EXPERIMENT.md`, `../gpu-initiated/nvshmem_ft/TRANSPARENT_T1.md`
