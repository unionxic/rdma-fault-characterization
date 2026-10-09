# GIN 투명 복구: 운영 수준으로 다지기 (gin-harden)

**목적:** 비판적 리뷰 다섯 건이 짚은 정확성, 생존 판정, 상한, 운영 문제를 한 계층으로 고치고, 고친 동작과 바뀌지 않아야 할 동작을
사전 등록한 예측으로 잰다. 시험 스위치가 없는 운영 빌드의 지연과 장애 동작, 기본 IB 타임아웃에서의 동작도 함께 잰다.

| 항목 | 값 |
|---|---|
| 상태 | `COMPLETE` |
| 담당자 | @unionxic |
| 작성일 | 2026-10-09 |
| 기준 브랜치와 커밋 | `exp/gin-harden` @ `d834f86c` (master) |
| 사전 등록 태그 | `prereg/gin-harden-v1` (상태를 `PREREGISTERED`로 바꾼 바로 그 커밋) |
| 마지막 갱신 | 2026-10-09, 본 실행, 채점, 독립 재계산, 코드 리뷰, Release, 결론(13–19절) |

표시: `[측정]` 원자료에서 확인, `[소스]` 코드에서 읽음, `[추론]` 해석, `[미확인]` 확인 안 함.

이 문서의 `ow.diff N행`은 gin-oneway의 전체 diff [../oneway/gin_transparent_ow.diff](../oneway/gin_transparent_ow.diff)의 줄 번호다. 리뷰가 그
번호로 문제를 짚었고, 아래 1절의 줄은 모두 그 파일에서 다시 확인했다 `[소스]`. 이 실험의 코드는 함수 이름으로 가리킨다(파일은
`src/transport/net_ib/gdaki/gin_host_gdaki.cc`, 다른 파일은 이름을 적는다).

**용어.**
- helper: GIN 투명 복구가 GDAKI 문맥마다 띄우는 호스트 스레드. 장치 쪽 오류 분류기가 남긴 장애 기록을 받아 상대와 복구 라운드를 돈다.
- helper 소켓: helper가 rank 쌍마다 여는 관리망 TCP 소켓.
- 사용자 devComm: application이 `ncclDevCommCreate`로 만든 장치 communicator. 그 커널의 GIN 대기(`waitSignal`, `flush`, `wait`)가 abort 단어를
  읽는다.
- abort 단어: 장치 대기가 주기적으로 읽는 32비트 값. 0이 아니면 대기를 끝낸다. 지금은 사용자 devComm이 communicator 전체의 단어를 같이 쓴다.
- 죽음, 모름: helper가 소켓으로 정하는 상대의 생존 상태(gin-reconnect, gin-oneway). 이 실험에서 "떠남"을 더한다: 상대가 떠난다고
  알린(BYE) 뒤의 소켓 끝.
- 고유값(nonce): 문맥을 만들 때 모든 rank가 낸 난수를 섞은 64비트 값. 모든 rank에서 같고 문맥마다 새로 정해진다.
- 라운드: 한 장애를 위해 두 rank가 주고받는 REQ, ACK, DONE과 그 사이의 QP 리셋, 재연결, 다시 보내기. 커밋은 그 rank가 QP를 리셋해
  새 incarnation으로 연결한 순간이다(되돌릴 수 없다).
- 펌웨어 명령 단계: QP 상태 바꾸기(2ERR, 2RST, INIT/RTR/RTS)와 QUERY_QP처럼 NIC 펌웨어 명령으로 가는 호출들. 중간에 끊을 수 없다.
- 첫 분류 기록: 장애 뒤 그 rank의 장치 쪽 오류 분류기가 남긴 첫 "device-classified error CQE" 줄.

장애 기호, 셀 이름, 예측 id는 원자료를 찾는 키로만 괄호나 표의 열에 둔다.

| 장애 | 기호 |
|---|---|
| 로컬 QP 오류 | F1 |
| 원격 접근 오류 | F2 |
| 상대 QP 오류 | F3 |
| 상대 프로세스 kill | F4 |

빌드 키는 다섯 가지다. 모두 번들 디렉터리 `$HOME/gi-bundle/gin_ts2/<키>/`다.

| 키 | 내용 | 쓰는 곳 |
|---|---|---|
| `ow` | gin-oneway의 libnccl `b4af65c5`와 드라이버 `d4b1f082`(배포된 번들, 그대로) | 대조 셀, 지연 기준 |
| `hd` | 이 실험의 연구 빌드: `ow` 위에 9절 1번의 계층. 시험 스위치와 장애 훅이 있다. 이 실험의 새 드라이버 | 새 셀, 회귀 셀, IB 타임아웃 셀 |
| `hdp` | 같은 소스를 `-DNCCL_GIN_TS_PRODUCTION`으로 컴파일한 운영 빌드. 같은 드라이버 | 지연, 훅 없는 kill과 관리망 끊김 |
| `ow2` | `ow`의 libnccl과 이 실험의 새 드라이버(shrink를 부르는 대조) | shrink 대조 |
| `stk` | 순정 NCCL v2.32.3-1과 그 헤더로 빌드한 드라이버 | 지연 기준 |

`base` 번들은 순정이 아니다: libnccl `1ed8e0a1`은 gpudb v2 빌드(장애 훅, 분류기, 복구 v1, gpudb v2 네 diff)다 `[측정]`
(`../TRANSPARENT_S2.md` provenance 표, `../NOTES.md` 466행, `../pair_check/deploy_check.txt`의 `./base/libnccl.so.2.32.3`). 그래서
순정 기준은 이 실험에서 새로 빌드한 `stk`이고, 그 소스 트리는 상위 NCCL의 태그 `v2.32.3-1`(`12df1a11`)과 파일 단위로 같다 `[측정]`
(9절 빌드 4번).

## 1. 배경과 연구 질문

gin-oneway까지의 투명 복구는 2 rank, 노드 한 쌍에서 로컬 QP 오류, 상대 QP 오류, 관리망 끊김을 application 모르게 복구했다
(`../oneway/EXPERIMENT.md` 15절). 비판적 리뷰 다섯 건이 그 코드에서 아래 문제를 짚었다. 줄은 모두 다시 확인했다 `[소스]`.

**1. 정확성.**
- (a) 사용자 devComm이 communicator의 abort 단어를 같이 쓴다(ow.diff 32–35행, `dev_runtime.cc`). 그래서 `ncclCommShrink`의 abort,
  `ncclCommRevoke`, 그룹 실패도 사용자 대기를 푼다. 풀린 대기는 `ncclSuccess`를 돌려준다(ow.diff 1005–1009행, `gin__funcs.h` 101행).
  커널은 도착하지 않은 신호를 받은 것으로 알고 다음으로 간다(`../s2_close/qa/code_review.md` R1, R2).
- (b) 생존 판정.
  - 연결 거부 한 번이 죽음이다(ow.diff 3891행). 방화벽 거부나 다시 여는 중인 수신 대기 소켓도 거부한다.
  - HELLO, HELLO-ACK, PROBE에 고유값이 없다. 같은 포트를 다른 프로세스가 쓰면 잘못 연결되거나 죽은 상대가 계속 모름으로 남는다
    (`../oneway/qa/code_review.md` 항목 4).
  - 라운드 안의 리셋이나 FIN은 영구 거절이다(ow.diff 5104, 5122, 4917, 4927행).
  - 쉬는 중 FIN은 상대를 `gone`으로 표시할 뿐이다(ow.diff 5462–5467행). 보내지 않고 받기만 하는 rank는 자기 장애가 없으니 거절도 없고,
    자기 대기 상한까지 기다린다.
- (c) 상한.
  - 장치 상태 복사가 `cudaStreamSynchronize`로 끝없이 기다린다(ow.diff 2537–2551, 4205–4221행).
  - `ncclCommAbort`가 helper를 기다린 뒤 복사와 펌웨어 명령을 내고, 진단용 QUERY_QP도 낸다(ow.diff 5877–5926행, 5910행). helper가
    펌웨어 명령 안에서 멈추면 abort도 멈춘다.
  - 펌웨어 명령은 끊을 수 없는데, 라운드의 펌웨어 단계에 상한이 없다.
- (d) 한 라운드의 다시 보내기를 QP마다 검사하고 바로 보낸다(ow.diff 4475–4683행). 뒤 QP가 거절되어도 앞 QP는 이미 다시 보냈다.
- (e) HELLO에 담는 문맥 번호가 프로세스 전체의 계수기다(ow.diff 5566, 5619–5621행).

**2. 운영.**
- (a) 시험 스위치, 장애 훅, 진단 코드가 라이브러리에 들어 있다. 정보성 줄이 WARN이다.
- (b) 복구 계수를 application이 볼 방법이 없다.
- (c) 장애가 계속 와도 끝없이 복구한다. 상위 계층(예: PyTorch 감시)이 노드를 뺄 신호가 없다.

**3. shrink 넘기기.** 복구가 거절한 장애(상대 kill) 뒤 application은 `ncclCommShrink`로 죽은 rank를 빼고 이어 가야 한다. 지금은 그때 풀리는
대기가 성공을 돌려준다(1a).

**4. 기본 IB 타임아웃.** GDAKI QP는 `NCCL_IB_TIMEOUT`과 `NCCL_IB_RETRY_CNT`를 그대로 쓴다(`gdakiConnectQp`의 ack timeout과 retry
count 설정) `[소스]`. 기본값 20에서 상대 QP 오류는 약 58 s 뒤에야 보인다: verbs 새 프로세스 58.46–58.79 s
(n=10, `../../../ack_timeout/README.md` 46행), GIN GDAKI는 QP가 ERR이 되기까지 약 57 s, 호스트가 알기까지 59.4 s(기준 실행 1회, `../../gin/NOTES.md` 268–269행) `[측정, 이전 실험. 원자료에서 다시 세지 않음]`. NCCL 2.31.2부터 GIN
장치 API에 시간 제한 판(`flush`, `wait`, `waitSignal`, `waitCounter`의 `timeoutCycles` 인자)이 생겼다 `[소스]`(상위 태그 비교:
`gin__funcs.h`의 `timeoutCycles`가 v2.30.3-1에 0개, v2.31.2-1에 12개).

**질문.**
1. 사용자 devComm에 따로 둔 abort 단어로, 복구 거절, 죽음, abort가 사용자 대기를 오류로 풀고 성공으로 풀지 않는가. 그 뒤
   `ncclCommShrink`가 쓸 수 있는 communicator를 돌려주는가.
2. 거부 한 번에는 죽음으로 보지 않고 1 s 이상 떨어진 두 번에는 죽음으로 보는가. 고유값이 틀린 재연결은 연결로도 죽음으로도 세지
   않는가. 라운드 안의 리셋 뒤 재연결하고 라운드를 다시 돌아 복구하는가. 받기만 하는 rank에 상대의 죽음이 2 s 안에 드러나는가.
3. GPU 전체를 application 커널이 쓰는 중에도 복구가 되는가. 멈춘 복사, 느린 펌웨어 단계, 멈춘 helper에서도 거절과 abort가 상한 안에 끝나는가.
   라운드의 시작 쪽이 다시 보내기 대상 하나를 거부하면 어느 rank도 다시 보내지 않는가.
4. 상한(정한 시간 안의 라운드 수)을 넘으면 거절하고 복구를 멈추는가. 통계 API가 라운드, 복구, 거절, 죽음을 바로 세는가.
5. 시험 스위치를 뺀 운영 빌드는 gin-oneway, 순정 NCCL과 지연이 얼마나 다르고, 훅 없는 kill과 실제 관리망 끊김(iptables)을 바르게
   다루는가.
6. 기존 셀(gin-oneway, gin-reconnect, gin-pair-check)은 바뀐 줄을 빼면 판정이 그대로인가.
7. IB 타임아웃 20에서 상대 QP 오류는 언제 보이고, 막는 대기와 장치 쪽 시간 제한 대기는 투명 복구와 어떻게 맞물리는가.

## 2. 가설

| id | 가설 | 다음이 관측되면 틀린 것이다 |
|---|---|---|
| H1 | 사용자 devComm의 따로 둔 단어는 거절, 죽음, abort, 중단하는 shrink에서만 올라가고, 그 단어로 풀린 대기는 오류를 돌려준다. 죽은 상대를 뺀 shrink는 쓸 수 있는 1-rank 통신기를 돌려준다 | shrink 셀에서 신호 없이 성공한 대기가 하나라도 있다. 또는 shrink나 그 통신기의 allreduce가 9/10 미만으로 된다. 또는 원격 접근 오류 셀에서 받는 쪽 대기가 오류로 풀리지 않는다 |
| H2 | 생존 판정은 거부 두 번(1 s 이상 간격), BYE, 고유값으로 살아 있는 상대를 죽음으로 보지 않고, 죽은 상대는 받기만 하는 rank에서도 2 s 안에 드러낸다. 라운드 안의 리셋은 재연결 뒤 다시 돈 라운드로 복구된다 | 거부 한 번, 틀린 고유값, 라운드 안 리셋 셀에서 죽음 줄이 2회 이상이다. 또는 각 셀의 복구가 9/10 미만이다. 또는 받기만 하는 rank의 해제가 2 s를 넘은 시행이 2회 이상이다 |
| H3 | 복사, 펌웨어 단계, abort의 helper 대기에 상한을 두면 멈춘 복사와 느린 펌웨어 단계도 정한 시간 안에 거절과 대기 해제로 끝나고, GPU가 가득 찬 정상 복구는 그대로다 | GPU가 가득 찬 셀의 투명 복구가 9/10 미만이다. 또는 느린 펌웨어 셀에서 감시가 3.0–3.5 s 밖에서 발동하거나 abort가 6 s를 넘은 시행이 2회 이상이다. 또는 멈춘 복사 셀의 거절이 3 s를 넘은 시행이 2회 이상이다 |
| H4 | 다시 보내기 계획을 모든 QP에서 먼저 검사하면, 라운드의 시작 쪽이 하나를 거부할 때 어느 rank도 아무것도 다시 보내지 않는다 | 계획 거부 셀(거부한 rank 0이 시작 쪽인 시행)에서 어느 rank든 복구 줄이 나온 시행이 2회 이상이다 |
| H5 | 상한과 계수, 운영 스위치는 기존 동작과 빠른 경로를 바꾸지 않는다. 운영 빌드는 훅 없이도 kill과 관리망 끊김을 바르게 다룬다 | 회귀 셀에서 예측과 다른 시행이 나온다. 또는 지연 차이가 예측 범위 밖이다. 또는 운영 빌드의 kill, 끊김 셀이 5/5가 아니다 |
| H6 | IB 타임아웃 20에서 상대 QP 오류는 50–70 s 뒤 분류되고, 막는 flush는 그만큼 기다린 뒤 투명하게 복구된다. 장치 쪽 시간 제한이 그보다 짧으면 대기는 시간 초과로 끝나고 복구는 시작되지 않는다 | 분류가 50–70 s 밖인 시행이 있다. 또는 막는 셀의 투명 복구가 4/5 미만이다. 또는 시간 제한 셀에서 복구나 거절이 나온다 |

## 3. 사전 예측 (측정 전에 작성)

**고정 시점.** 예측은 메인 세션이 pilot(9절의 hold H0)을 돌린 뒤 태그 `prereg/gin-harden-v1`을 단 커밋에서만 고정된다. 그 전까지 이 절과
[predictions.csv](predictions.csv)는 고칠 수 있다(pilot에서 셀 조건이 의도대로 만들어지지 않으면 셀 조건이나 판정식을 고친다). pilot 시행은
채점하지 않는다. 그 결과 폴더(`results/<날짜>_pilot/`)는 채점 대상 폴더와 따로 두고, 무엇을 보고 무엇을 고쳤는지 12절과 13절에 적는다.
태그 뒤에는 2, 3, 7, 8절과 `predictions.csv`를 고치지 않는다.

**pilot 뒤 확정 (2026-10-09).** 예측과 셀, 반복 수, 제외 기준은 pilot H0(03:24:59–03:31:02 KST, 25회, 채점 안 함, 12절) 뒤에 확정했다. pilot을 보고
바꾼 것은 셀 사실의 정정과 채점 규칙, 실행 스크립트뿐이다.
- D1 판정식의 QP 수: `plan_rej_total_r0 == 2`를 `>= 2`로. 이 셀의 라운드는 상대와의 QP 4개(GIN 문맥 4개)를 덮는다. 설계 때 2개로 잘못 셌다
  (pilot의 훅 줄 "4 context(s)", 라운드 줄 `qps=4`, 거부 줄 "qp 1 of 4") `[측정]`. 예측한 동작(두 번째 QP에서 거부, 아무것도 다시 보내지
  않음)은 그대로다.
- 두 번 거부 셀(`hd_ref2_f1_b`)의 훅 요구를 뺐다: 상대가 약 9.6 s에 죽음으로 판정되어 거절되므로 12 s 훅 전에 실행이 끝난다(pilot에서 "장애
  미적용"으로 잘못 제외됨).
- 실행기의 남은 프로세스 계수 버그(모든 시행이 `left=1`), CUDA 메모리 오류 중단 기준(`STOP_cuda`) 추가. 예측과 판정식에는 영향이 없다.

pilot이 소스 해석과 어긋난 예측 둘은 고치지 않고 그대로 두며 의심을 적는다(`predictions.csv`의 basis 열에도 적음).
- GPU가 가득 찬 동안의 투명 복구(C1): pilot 1회에서 두 rank helper의 4 B 장치 상태 복사가 2 s 안에 끝나지 않았고, 응용의 GIN 커널이 끝난 순간에
  끝났다. 그래서 두 rank가 거절했다 `[측정]`. 복사가 이 GPU에서 빈 SM 자리를 필요로 하는 것으로 보인다 `[추론]`. 원인은 `[미확인]`이다. 이
  예측은 틀릴 가능성이 높다.
- shrink 넘기기(A2): pilot에서 두 빌드(`hd`, `ow2`) 모두 `ncclCommShrink`가 0 ms에 `ncclRemoteError`를 돌려주었다 `[측정]`. 원인은 순정 NCCL의
  `ncclCommInitChildComm`이 `ncclCommEnsureReady`를 불러 부모의 GIN 비동기 오류를 그대로 돌려주는 것이다 `[소스]`(이 계층이 바꾸지 않은 코드).
  설계 때 이 확인을 놓쳤다. 이 예측도 틀릴 것으로 본다. shrink가 되게 하려면 라이브러리 수정이 필요하다(19절).
- 4 KiB 지연의 순정 대비 차이(P3): pilot 1실행씩에서 0.93 µs로 예측 범위(0.10–1.00 µs)의 위쪽 끝 근처다 `[측정]`. 범위는 그대로 둔다.

예측 원문은 [predictions.csv](predictions.csv)이고 52줄이다. `kind`는 N(새 동작), R(회귀), C(대조)다. 아래 판정 열, 로그 형식, 셀 키,
판정식 문법은 태그에서 고정한다.

### 3.1 판정에 쓰는 열

시행마다 한 줄이다. 열은 다섯 곳에서 온다. 앞의 네 곳의 열은 원래 정의 그대로다 `[소스]`.
- `../scripts/ts2/rows.py`: `transparent_ok`, `r1_outcome`, `tx_rc`(rank 0 보내는 쪽), `rx_rc`(rank 1 받는 쪽), `rx_rc_r0`(양방향의 rank 0
  받는 쪽), `r0_async`, `decl_r0`, `decl_r1`, `rec_init_r0`, `teardown_r*`, `teardown_ms_r*`, `lat_p50_us`, `q4_class_r0`, `ts_on_r*`,
  `n_fires_r*`, `killed`, `bind_fail`, `trigger_miss`, `fault_mono_r0`.
- `../s2_close/rows_extra.py`: `ua_r*`(사용자 devComm abort 단어 줄 수).
- `../pair_check/rows_pc.py`: `n_notrts_r*`, `n_refused_r1`, `n_rerun_r0`, `n_rec_r*`, `inj_ctx_r*`, `pr_mode_r*`.
- `../oneway/rows_ow.py`(정의는 `../oneway/EXPERIMENT.md` 3.1절): `ow_mode_r*`, `knob_uto_r*`, `knob_refuse_r*`, `n_mute_on_r*`,
  `mute_off_ms_r*`, `close1_cause_r*`, `close1_lv_r*`, `close1_ms_r*`, `n_dead_r*`, `n_reconn_r*`, `reconn_after_unmute_ms_r*`,
  `wait_end_r1`, `n_notacc_r0`, `n_probe_ref_r1`, `n_refuse_test_r1`, `q4_ms_r*`, `r0_killed`. 이 실험의 닫힘 줄은 `liveness=left`를 더
  가질 수 있다. `n_dead_r*`는 그대로 `liveness=dead`만 센다.
- 이 폴더의 [rows_hd.py](rows_hd.py)가 붙이는 새 열. 정의는 그 파일 머리말이 원문이다. 요약:

| 열 | 정의 |
|---|---|
| `hd_on_r*`, `prod_r*` | `GIN/TS: harden=1 rank=<r> ... production=<0\|1>` 줄이 있으면 1, 그 `production` 값 |
| `hk_gap_r*`, `hk_badnonce_r*`, `hk_fwdelay_r*`, `hk_copystall_r*`, `hk_badrepost_r*` | `GIN/TS: TEST harden knobs ...` 줄의 값 |
| `n_judged_r*`, `judged_cause_r*`, `judged_ms_r*` | `GIN/TS: rank <r>: rank <p> judged dead (cause=<C>) mono_ms=<t>` 줄 수, 첫 줄의 원인과 시각 |
| `n_left_r*` | `GIN/TS: rank <r>: rank <p> left the communicator (BYE)` 줄 수 |
| `n_refused_dial_r*`, `n_probe_refused_r*` | 다시 걸기와 확인 접속의 거부 줄 수(`... refused (ECONNREFUSED) mono_ms=<t> refusal=<n>`) |
| `refusal_span_ms_r*` | 죽음 판정 시각 − 그 rank의 첫 거부 시각 |
| `n_nonce_ref_r*`, `n_badnonce_sent_r*`, `n_probe_noans_r*` | 고유값이 틀린 재연결 거부 줄, 틀린 고유값을 보낸 시험 줄, 응답 없는 확인 접속 줄 수 |
| `n_cancel_r*`, `sock_retries_max_r*` | 라운드 취소 줄 수, 시작 쪽 복구 줄의 `sock_retries` 최댓값 |
| `rec_total_us_r*` | 그 rank의 첫 시작 쪽 복구 줄의 `total_us` |
| `n_fwdog_r*`, `fwdog_run_ms_r*`, `fwdog_phase_r*` | 펌웨어 단계 감시 줄 수, 첫 줄의 `has run <x> ms`와 단계 이름 |
| `n_uarel_r*`, `uarel_why_r*` | `GIN/TS: user devComm waits released rank=<r> why=<w>` 줄 수와 첫 `why` |
| `n_copyto_r*`, `n_esc_r*`, `n_orphan_r*`, `n_dump_r*` | 복사 상한 초과, 상한 넘김(escalation), 떼어 낸 helper, 장치 대기 시간 초과 기록 줄 수 |
| `n_plan_rej_r*`, `plan_rej_qp_r*`, `plan_rej_total_r*`, `plan_rej_ms_r*` | `re-post plan to rank <p> rejected at qp <i> of <n> (...); nothing re-posted mono_ms=<t>` 줄 수와 첫 줄의 `i`, `n`, `t` |
| `n_init_round_r*` | 시작 쪽 라운드 줄(`GIN/TS: rank <r>: round <n> peer <p> scope=.. qps=.. reason=.. mono_ms=<t>`, 라운드의 시작 쪽만 남긴다) 수 |
| `plan_rej_init_r0` | rank 0이 첫 계획 거부 시각 이전에 시작 쪽 라운드 줄을 남겼으면 1(거부한 rank 0이 그 라운드의 시작 쪽. 낮은 rank는 자기 라운드를 양보하지 않는다), 거부는 있는데 그 줄이 없으면 0(응답 쪽), 거부가 없으면 빈칸 |
| `rs_*_r*` | 드라이버 kv의 `ncclGinGetRecoveryStats` 값(`rs_api`, `rs_rounds`, `rs_recovered`, `rs_declined`, `rs_reconnects`, `rs_deaths`, `rs_escalations`, `rs_cancelled`, `rs_fw_overruns`, `rs_copy_timeouts`, `rs_contexts`) |
| `rx_phantom_r*`, `post_abort_rx_phantom_r*` | 드라이버 kv: 성공을 돌려준 신호 대기 중 그때 읽은 신호 값이 목표보다 작은 반복 수(통상 읽기, 마지막 abort 뒤 다시 읽기) |
| `ho_*` | 드라이버 kv(shrink 넘기기, rank 0): shrink 전 커널 끝남, shrink 결과, 새 통신기 rank 수, allreduce 확인 |
| `hog_*_r*`, `fault_after_launch_r0_ms` | GPU를 채우는 커널의 kv(블록 수, SM 수, 띄운 시각, 오류 이름), rank 0 훅 발사 − 커널 시작 |
| `q4_after_fault_ms_r0`, `decl_after_q4_ms_r0` | 첫 분류 기록 − 장애 시각(rank 0 시계), 첫 거절 − 첫 분류 기록 |
| `release_after_kill_ms_r1`, `async_after_kill_ms_r1` | rank 0 kill을 rank 1 시계로 옮긴 시각에서 rank 1 커널 끝, 첫 비동기 오류까지 |
| `decl_after_kill_ms_r0` | rank 1 kill을 rank 0 시계로 옮긴 시각에서 rank 0의 첫 거절까지 |
| `r1close_after_q4_ms` | rank 1 첫 소켓 닫힘(rank 0 시계) − rank 0 첫 분류 기록 |
| `mute_applied`, `mute_rules_on`, `mute_rules_left`, `left_rules` | 운영 빌드 관리망 끊김의 iptables 적용 기록(`mute.out`, 실행기 meta) |

**새 로그 줄과 바뀐 줄** `[소스, 9절의 변경으로 고정]`. 연구 빌드(`hd`)에서는 모두 WARN이다. 운영 빌드(`hdp`)에서는 "정보" 줄이 INFO라
`NCCL_DEBUG=WARN`에서는 보이지 않는다.

| 줄 | 수준(운영) | 형식 |
|---|---|---|
| 시작 | 정보 | `GIN/TS: harden=1 rank=<r> nonce=<x> fw_ms=<n> copy_ms=<n> join_ms=<n> join_max_ms=<n> escalate=<k>/<w> port=<p> sock_retries=3 production=<0\|1>` |
| 거부 | 정보 | `GIN/TS: rank <r>: re-dial to rank <p> refused (ECONNREFUSED) mono_ms=<t> refusal=<n>`, `... probe of rank <p> refused (ECONNREFUSED) mono_ms=<t> refusal=<n>` |
| 죽음 판정 | WARN | `GIN/TS: rank <r>: rank <p> judged dead (cause=<C>) mono_ms=<t>`. 바로 뒤에 거절 `reason="peer judged dead: the peer's socket shows <C>"` |
| 떠남 | 정보 | `GIN/TS: rank <r>: rank <p> left the communicator (BYE) mono_ms=<t>`. 그 뒤 닫힘 줄은 `liveness=left`(설치 전 연결의 BYE면 닫힘 줄 없음) |
| 고유값 | 정보 | `GIN/TS: rank <r>: refused a reconnect from rank <p> (nonce mismatch) gen=<g> mono_ms=<t>`, `... probe of rank <p> not answered by the peer (<why>)` |
| 라운드 취소 | WARN | `GIN/TS: rank <r>: round <n> with rank <p> cancelled (<stage>, socket <C>) before the commit; the fault is retried after the reconnect (retry <i> of 3)`, 응답 쪽 `... round <n> from rank <p> cancelled before the commit (socket <C>)` |
| 복구 | 정보 | 형식 그대로, 시작 쪽 줄 끝에 `sock_retries=<n>` |
| 대기 해제 | WARN(abort, revoke, shrink는 정보) | `GIN/TS: user devComm waits released rank=<r> why=<abort\|revoke\|shrink\|declined\|peer-dead\|fw-watchdog> mono_ms=<t>` |
| 복사 상한 | WARN | `GIN/TS: rank <r>: device-state copy (<dir>, <n> B) not complete after <ms> ms (NCCL_GIN_TS_COPY_MS); the round declines` |
| 펌웨어 감시 | WARN | `GIN/TS: watchdog rank=<r>: firmware command phase <phase> has run <x> ms, more than NCCL_GIN_TS_FW_MS=<n>; ...` |
| helper 떼어 냄 | WARN | `GIN/TS: communicator teardown rank=<r>: the recovery helper did not stop within <ms> ms ...`(`<ms>`는 실제로 기다린 시간) |
| 계획 거부 | WARN | `GIN/TS: rank <r>: re-post plan to rank <p> rejected at qp <i> of <n> (<why>); nothing re-posted` |
| 상한 넘김 | WARN | `GIN/TS: escalated rank=<r>: more than <k> recovery rounds within <w> ms (...); recovery stops on this communicator`, 거절 `reason="escalation: more than <k> recovery rounds within <w> ms"` |
| 요약 | INFO | `GIN/TS: summary rank=<r> rounds=.. recovered=.. declined=.. cancelled=.. reconnects=.. deaths=.. escalations=.. fw_overruns=.. copy_timeouts=.. orphan=<0\|1>` |
| 시험 스위치 | 연구 빌드만 | `GIN/TS: TEST harden knobs rank=<r> listen_gap=<a>:<b> bad_nonce=<n> fw_delay=<ms>@<phase> copy_stall=<ms> bad_repost=<k>`, `GIN/TS: TEST listen gap on/off ...`, `GIN/TS: TEST sent a wrong nonce in <HELLO\|PROBE> ...`, `GIN/TS: TEST firmware delay ...`, `GIN/TS: TEST copy stall ...`, `GIN/TS: TEST re-post plan of qp <i> ... rejected` |

**드라이버 kv**(이 실험의 드라이버, 9절 3번): `rx_phantom`, `rx_phantom_first`, `post_abort_read`, `post_abort_rx_done`, `post_abort_rx_rc`,
`post_abort_rx_phantom`, `ho_kernel_done_before_shrink`, `ho_shrink_rc`, `ho_shrink_ms`, `ho_newcomm`, `ho_newcomm_nranks`, `ho_allreduce_rc`,
`ho_check_ok`, `ho_old_kernel_done`, `hog_ms`, `hog_sms`, `hog_blocks`, `hog_launch_after_launch_ms`, `hog_launch_err`, `rs_api`과 `rs_*`.

### 3.2 셀 키와 판정식 문법

셀 키(`cell@build`), 판정 대상(8절 제외를 거친 시행), "자료 부족" 규칙, 판정식 문법(`count`, 빈칸 규칙, `has`, `nonempty`, `median`,
`abs`, `per cell:`)은 `../s2_close/EXPERIMENT.md` 3.2절과 같다. `count(...)`와 `median(...)` 밖의 나머지는 Python의 산술과 비교다
(`../pair_reset/EXPERIMENT.md` 3.2절과 같음). 이 실험의 [score.py](score.py)는 `../s2_close/score.py`의 판정식 평가 함수를 그대로 불러
쓴다. 두 셀 키를 쓰는 판정식은 두 셀 모두 계획한 수를 채워야 판정한다. 판정은 맞음, 틀림, 자료 부족 중 하나다.

### 3.3 예측 요약

전체 판정식은 [predictions.csv](predictions.csv)에 있다. 아래는 요약이다. "n"은 계획한 판정 시행 수다.

| 예측 | id | 셀 | 판정 기준(요약) | 근거 |
|---|---|---|---|---|
| 상대 kill 뒤 rank 0의 대기가 shrink 전에 오류로 풀리고, 신호 없이 성공한 대기가 없다 | A1 | `hd_shrink_b@hd` | ≥9/10 | 죽음 즉시 거절과 따로 둔 단어 `[소스]` |
| `NCCL_SHRINK_ABORT` shrink가 1-rank 통신기를 돌려주고 그 allreduce가 맞다 | A2 | `hd_shrink_b@hd` | ≥9/10 | 이 테스트베드에서 처음 `[미확인]`. pilot 뒤 의심: 순정 `ncclCommEnsureReady`가 GIN 오류로 shrink를 막음(3절 머리) |
| 대조(ow 라이브러리): shrink 때 옛 커널이 아직 돈다 | A3 | `hd_shrink_b@ow2` | ≥4/5 | 쉬는 중 FIN은 표시만(ow.diff 5462–5467행) `[소스]` |
| 대조: 마지막 abort가 받는 쪽 대기를 신호 없이 성공으로 풀거나, shrink가 돌아오지 않는다 | A4 | `hd_shrink_b@ow2` | ≥4/5 | ow.diff 1005–1009행, `gin__funcs.h` 101행 `[소스]` |
| 원격 접근 오류 셀: 받는 쪽 대기가 상대 거절 때 오류로 풀리고 abort가 5 s 안에 돌아온다(gin-oneway의 회귀 판정을 일부러 바꿈) | A5 | `f2rel_b@hd` | 5/5 | gin-oneway는 abort까지 커널이 멈춤 5/5 `[측정]` |
| 거부 한 번으로는 살아 있는 상대를 죽음으로 보지 않는다 | B1 | `hd_ref1_f1_b@hd` | ≥9/10 | 거부 두 번 규칙 `[소스]` |
| 1 s 뒤 다시 걸기로 재연결되고 12 s 장애가 투명하다 | B2 | `hd_ref1_f1_b@hd` | ≥9/10 | gin-oneway HELLO 거부 셀 10/10 `[측정]` |
| 1 s 이상 떨어진 거부 두 번은 죽음이고 바로 거절과 대기 해제로 드러난다 | B3 | `hd_ref2_f1_b@hd` | ≥9/10 | `[소스]` |
| 틀린 고유값의 HELLO는 거부되고 받아들여지지 않음으로 남으며 죽음 판정이 없다 | B4 | `hd_nonce_f1_b@hd` | ≥9/10 | `[소스]` |
| 다음 다시 걸기로 끊김 끝 2 s 안에 재연결되고 투명하다 | B5 | `hd_nonce_f1_b@hd` | ≥9/10 | gin-oneway 582.1–606.7 ms(n=10) `[측정]` |
| 라운드 안의 리셋은 라운드를 취소하고, 재연결 뒤 다시 돈 라운드로 투명하게 복구된다 | B6 | `hd_rround_f1_b@hd` | ≥9/10 | `[소스]`, 한쪽 끊김의 리셋 25/25 `[측정]` |
| 대조(ow): 같은 리셋에서 REQ 보내기 실패로 거절한다 | B7 | `hd_rround_f1_b@ow` | ≥4/5 | ow.diff 5104행 `[소스]` |
| 받기만 하는 rank가 죽은 보내는 쪽을 죽음으로 보고 대기가 kill 뒤 2 s 안에 오류로 풀린다 | B8 | `hd_rxdeath_b@hd` | ≥9/10 | `[소스]` |
| 받기만 하는 rank가 kill 뒤 2 s 안에 비동기 오류를 받고 abort가 돌아온다 | B9 | `hd_rxdeath_b@hd` | ≥9/10 | `[소스]` |
| 대조(ow): 받기만 하는 rank는 자기 15 s 대기 상한까지 기다린다 | B10 | `hd_rxdeath_b@ow` | ≥4/5 | `[소스]` |
| 정상 종료의 FIN은 BYE 뒤라 떠남으로 남고 죽음 줄이 없다 | B11 | `f1_b`, `f3_b`, `rc_mute8_f1_b`(모두 `@hd`) | 셀마다 ≥4/5 | gin-oneway는 정상 종료 60/60에 죽음 줄 `[측정]` |
| GPU 전체를 쓰는 커널이 도는 중에도 투명하게 복구되고 복사 상한 초과가 없다 | C1 | `hd_hog_f1_b@hd` | ≥9/10 | 복구는 복사만 쓴다 `[소스, 추론]`. pilot 뒤 의심: 복사가 응용 커널이 끝날 때까지 끝나지 않음(3절 머리) |
| 8 s 펌웨어 단계에서 3.0–3.5 s에 감시가 발동해 대기를 오류로 풀고 오류를 드러낸다 | C2 | `hd_fwslow_f1_b@hd` | ≥9/10 | `NCCL_GIN_TS_FW_MS=3000` `[소스]` |
| helper가 아직 그 단계 안이어도 rank 0의 abort가 6 s 안에 돌아온다(helper를 떼어 냄) | C3 | `hd_fwslow_f1_b@hd` | ≥9/10 | `NCCL_GIN_TS_ABORT_JOIN_MS=3000` `[소스]` |
| rank 1이 거절하고 abort가 돌아온다 | C4 | `hd_fwslow_f1_b@hd` | ≥9/10 | `[소스]` |
| 대조(ow): 같은 8 s를 라운드 안에서 기다린 뒤 복구한다 | C5 | `hd_fwslow_f1_b@ow` | ≥4/5 | `[소스]` |
| 멈춘 복사가 2 s 상한을 넘어 첫 분류 기록 뒤 3 s 안에 거절되고, 두 rank의 대기가 오류로 끝난다 | C6 | `hd_copystall_f1_b@hd` | ≥9/10 | `NCCL_GIN_TS_COPY_MS=2000` `[소스]` |
| 두 rank의 abort가 돌아온다 | C7 | `hd_copystall_f1_b@hd` | ≥9/10 | `[소스]` |
| 시작 쪽 rank 0의 네 QP 중 두 번째 계획이 거부되면 어느 rank도 다시 보내지 않는다(거부한 rank 0이 응답 쪽인 시행은 8절에서 제외) | D1 | `hd_repost_f1_b@hd` | ≥9/10 | `[소스]`, 독립 리뷰 문제 1 |
| 두 rank가 거절한다 | D2 | `hd_repost_f1_b@hd` | ≥9/10 | `[소스]` |
| 다섯 장애 중 셋은 복구되고 넷째에서 상한(10 s에 3번)으로 거절한다 | E1 | `hd_esc_f1_b@hd` | ≥9/10 | `[소스]` |
| rank 0이 오류를 드러내고 rank 1이 상대 거절로 거절한다 | E2 | `hd_esc_f1_b@hd` | ≥9/10 | `[소스]` |
| 대조(ow): 다섯 번 모두 복구한다 | E3 | `hd_esc_f1_b@ow` | ≥4/5 | `[소스]` |
| 통계 API가 두 rank에서 라운드 1, 복구 1, 거절 0을 센다 | E4 | `f1_b@hd` | 5/5 | `[소스]` |
| kill 뒤 통계 API가 죽음 1, 거절 1을 센다 | E5 | `f4_b@hd` | 5/5 | `[소스]` |
| 복구 재현 셀이 그대로 투명하다 | R1 | `f1_b`, `f3_b`, `bidirf_sym_b`, `rc_mute8_f1_b`(모두 `@hd`) | 셀마다 5/5 | gin-oneway 5/5 `[측정]` |
| 상대 QP 오류 뒤 teardown 때 모든 QP가 RTS다 | R2 | `f3_b@hd` | 5/5 | gin-oneway 5/5 `[측정]` |
| 끊김 없는 kill은 죽음 원인으로 거절되고 abort가 돌아온다 | R3 | `f4_b@hd` | 5/5 | gin-oneway 5/5 `[측정]` |
| 그 거절이 kill 뒤 2 s 안에 온다(gin-oneway는 kill 약 3.6 s 뒤 첫 분류 기록에서 거절) | R4 | `f4_b@hd` | 5/5 | `[소스]`, gin-reconnect `[측정]` |
| pair-check 동작(좁은 범위 거부, 전체 재실행, teardown 때 모두 RTS)이 그대로다 | R5 | `pc_dual_f1c0_r1c2_b@hd` | 5/5 | gin-pair-check `[측정]` |
| 양쪽 8 s 끊김에서 한 번씩 1.5 s 안에 재연결되고 죽음 줄이 없다(정상 종료 포함) | R6 | `rc_mute8_f1_b@hd` | 5/5 | gin-oneway `[측정]` |
| 끊김 중 kill된 rank 1은 1 s 이상 떨어진 다시 걸기 거부 두 번 뒤 죽음으로 거절되고 모름 거절이 없다 | R7 | `rc_mutekill_b@hd` | 5/5 | gin-oneway 5/5 `[측정]` |
| rank 0이 리셋을 받는 한쪽 끊김: 모름, 죽음 없음, 1.5 s 안 재연결, 투명 | R8 | `ow_r1in_f1_b@hd` | 5/5 | gin-oneway 10/10 `[측정]` |
| rank 1이 리셋을 받는 한쪽 끊김: 모름, 재연결 기다림, 죽음 없음, 투명 | R9 | `ow_r0in_f1r1_b@hd` | 5/5 | gin-oneway 10/10 `[측정]` |
| 끊김 중 kill된 rank 0이 1 s 이상 떨어진 확인 접속 거부 두 번 뒤 죽음으로 판정되고 거절된다 | R10 | `ow_kill0_b@hd` | 5/5 | gin-oneway 10/10 `[측정]` |
| 거부된 재연결 HELLO가 받아들여지지 않음으로 남고 2 s 안 재연결, 투명 | R11 | `ow_hello_f1_b@hd` | 5/5 | gin-oneway 10/10 `[측정]` |
| rank 0이 원격 접근 오류를 복구할 수 없다고 거절한다 | R12 | `f2rel_b@hd` | 5/5 | gin-oneway `[측정]` |
| 4 KiB 지연: 운영 빌드와 gin-oneway 차이 0.40 µs 이하 | P1 | `lat_4k@hdp` 대 `lat_4k@ow` | 같은 hold의 실행 중앙값 | gin-oneway 10.56 µs `[측정]` |
| 256 KiB 지연: 차이 0.30 µs 이하 | P2 | `lat_256k@hdp` 대 `lat_256k@ow` | 같음 | 38.91 µs `[측정]` |
| 4 KiB 지연: 운영 빌드가 순정 NCCL보다 0.10–1.00 µs 느리다 | P3 | `lat_4k@hdp` 대 `lat_4k@stk` | 같음 | 복구 켬 − 끔 +0.29 µs, gpudb → 켬 +0.42 µs `[측정]`. pilot 1실행씩 0.93 µs |
| 256 KiB 지연: 0.10–1.00 µs 느리다 | P4 | `lat_256k@hdp` 대 `lat_256k@stk` | 같음 | +0.25, +0.54 µs `[측정]` |
| 운영 빌드가 kill된 상대를 2 s 안에 죽음 원인으로 거절하고 죽음 1을 세며 abort가 돌아온다 | P5 | `hdp_kill_b@hdp` | 5/5 | `[소스]` |
| 운영 빌드: iptables로 만든 8 s 관리망 끊김 뒤 재연결, 죽음과 거절 없음, 투명 | P6 | `hdp_mute_b@hdp` | 5/5 | `[추론]`, gin-oneway 한쪽 끊김 `[측정]` |
| 운영 빌드는 WARN 수준에서 정보성 복구 줄을 남기지 않으면서 복구는 켜져 있다 | P7 | `hdp_kill_b`, `hdp_mute_b`(`@hdp`) | 셀마다 5/5 | `[소스]` |
| IB 타임아웃 20: 상대 QP 오류의 첫 분류(RETRY_EXC)가 장애 50–70 s 뒤 | T1 | `to20_f3_b@hd` | 5/5 | verbs 58.46–58.79 s(n=10), GDAKI QP ERR 약 57 s(1회) `[측정, 이전 실험. 다시 세지 않음]` |
| 막는 flush가 그동안 기다리고 100 ms 이하의 한 라운드로 투명하게 복구된다 | T2 | `to20_f3_b@hd` | ≥4/5 | 9절 5번 `[소스]` |
| 장치 쪽 8 s 시간 제한에서 flush가 시간 초과를 돌려주고 복구도 거절도 없다 | T3 | `to20_f3_t@hd` | 3/3 | 9절 5번 `[소스]` |

셀 조건은 7절에 있다.

## 4. 범위

**포함.**
- 9절 1번의 라이브러리 계층 하나([hd_layer.diff](hd_layer.diff), `ow` 트리 기준)와 그 운영 빌드. 바뀌는 파일은 9절 1번의 표에 있다.
- 9절 3번의 드라이버 선택(신호 없이 성공한 대기 세기, GPU 채우기, shrink 넘기기, 통계)과 9절 4번의 실행기.
- 7절의 셀: 회귀 12셀, 새 셀 11개, 대조 5개, 운영 빌드 셀 2개와 지연 6셀, IB 타임아웃 20 셀 2개.

**제외와 이 테스트베드가 할 수 없는 것.**
- 실제 링크 내리기나 flap: 클러스터 규칙으로 금지다(링크를 공유하는 다른 사용자의 저장 장치가 있다). RoCE 주소 변경, 드라이버 재적재, 재부팅도
  하지 않는다. 그래서 링크 장애 뒤의 복구는 이 실험이 재지 않는다. 관리망 끊김은 우리 소켓에 붙이는 필터(연구 빌드)와 우리 포트에만 거는
  iptables 규칙(운영 빌드)으로만 만든다.
- 더 새로운 GPU와 NIC: 이 테스트베드에는 Turing(sm_75)과 Ampere(sm_86), ConnectX-6뿐이다. Hopper 이후(TMA, BlueFlame 장치 doorbell,
  CPU proxy가 없는 다른 doorbell 경로)와 ConnectX-7 이후의 동작은 재지 않는다.
- 3 rank 이상: 다른 실험(gin-multirank)이다. 이 실험의 코드는 rank 수를 가정하지 않게 썼지만 2 rank로만 잰다.
- 실제 펌웨어 명령의 멈춤: 시험 스위치의 잠으로 흉내 낸다. 실제로 멈춘 펌웨어 명령에서는 helper 스레드가 그 명령이 돌아올 때까지 남는다(9절
  1번 (c)).
- 그룹 실패와 split/shrink로 공유하는 abort 플래그가 사용자 대기를 풀지 않게 된 것은 코드로만 확인한다(`ncclCommRevoke`와 그룹 실패 셀은
  없다).
- 정보성 줄을 INFO로 낮춘 운영 빌드의 로그 전체 비교, 64 rank 규모의 계수 오버헤드.

## 5. 테스트베드와 버전

| 항목 | 값 | 확인 방법과 날짜 |
|---|---|---|
| 노드 | rain(rank 0, 낮은 rank), sunny(rank 1, 높은 rank) | 루트 `README.md` 테스트베드 표 |
| NIC와 펌웨어 | ConnectX-6 VPI, fw 20.43.4100. rain `mlx5_1`, sunny `mlx5_0` | `[측정]` 2026-10-06(`../../completion_contract/EXPERIMENT.md` 5절). hold 스냅숏에서 다시 기록 |
| 커널 | rain 5.15.0-97-generic | `[측정]` 2026-10-09(이 세션). sunny 커널과 OFED `[미확인]` |
| GPU와 CUDA | rain Quadro RTX 5000(sm_75), sunny RTX A4000(sm_86), PeerMappingOverride=1, CUDA 12.8 | gin-s2-close 5절 |
| 관리망 소켓 | `NCCL_SOCKET_IFNAME=eno1` | [run_trial_hd.sh](run_trial_hd.sh) |
| `ow` 번들 | libnccl `b4af65c54b14f192803c88adcd2bf759`, 드라이버 `d4b1f082` | `[측정]` 2026-10-09 rain에서 md5(gin-oneway `deploy_check.txt`와 같음) |
| `hd`, `hdp`, `stk`, 새 드라이버 | libnccl `hd` `e209032310a2cefd5d71e86533674bd6`, `hdp` `4818e30bb9c4b935edd1604fec0c3f6a`, `stk` `b380e622d299c25ab073417e3ee79aec`. 드라이버 `hd` 헤더판 `c0b73e0966c8350209d8dc71c8fa8c3b`(`hd`, `hdp`, `ow2`가 씀), 순정 헤더판 `472602a2b39bb4735c13b8d62a8ca888`(`stk`). 같은 소스를 다시 컴파일하면 드라이버 md5가 바뀐다(nvcc 출력이 재현되지 않음): 배포 확인은 `out/`의 파일과 비교한다. 소스 `../gin_ts2.cu` md5 `f34e65f0bc712090bbfe939855790aa1`. 배포 뒤 두 노드 md5는 [deploy_check.txt](deploy_check.txt)에 남겼다 | `[측정]` 2026-10-09 빌드 때 rain(세션 스크래치 `agent_ts2hd/out/`). 배포 2026-10-09 02:18:27–02:18:57: 두 노드 md5가 소스와 같고, 기존 번들 33개 파일은 그대로 |
| 변경분 | [hd_layer.diff](hd_layer.diff)(`ow` 트리 기준, md5 `2226872e`, 10개 파일 +1675/−329), 전체 diff [gin_transparent_hd.diff](gin_transparent_hd.diff)(pristine 기준, md5 `a9894def`). 순정에 전체 diff를, 그리고 gin-oneway 전체 diff에 이 계층을 더하면 각각 이 트리와 같다 | `[측정]` 2026-10-09 [make_diff_hd.sh](make_diff_hd.sh) |

## 6. 변수

- **독립변수.**
  - 빌드: `hd`, `hdp`, `ow`, `ow2`, `stk`.
  - 장애: 로컬 QP 오류(rank 0 훅, 다섯 번 연속 포함), 상대 QP 오류(rank 1 훅), 원격 접근 오류, rank 0 kill, rank 1 kill.
  - 관리망: 우리 소켓 필터 끊김(한쪽, 양쪽), 우리 포트 iptables 끊김(운영 빌드), 수신 대기 소켓 닫기(1.2 s, 3 s).
  - 시험 스위치: 틀린 고유값 1회, 라운드 안 4 s 멈춤(기존), 8 s 펌웨어 단계, 4 s 멈춘 복사 스트림, 계획 거부, 상한(10 s에 3번).
  - GPU 채우기(3 s), shrink 넘기기, IB 타임아웃(14, 20), 장치 쪽 시간 제한(없음, 8 s).
- **종속변수.** 3.1의 열: 생존 판정과 원인, 거부 수와 간격, 재연결, 라운드 취소와 재시도, 복구와 거절과 사유, 대기 해제의 원인과 시각,
  드라이버의 대기 결과와 신호 없이 성공한 대기 수, shrink 결과, abort 시간, 통계 API 값, 지연 p50.
- **통제변수.**
  - IB 타임아웃 14(IB 타임아웃 셀 빼고), GPU doorbell, 재연결 스위치와 기다림 상한, 범위와 검사 스위치 기본값(1).
  - 새 상한의 기본값: 복사 2 000 ms, 펌웨어 단계 3 000 ms, abort의 helper 대기 3 000 ms, 상한 넘김 60 000 ms에 8번(상한 셀만 10 000 ms에 3번).
  - 기존 셀 정의는 `../scripts/ts2/batch.sh`, `../reconnect/cells.sh`, `../oneway/cells.sh`, `../pair_check/cells.sh`의 값 그대로다(빌드와
    실행기만 바꿈).
  - 시행마다 프로세스를 새로 띄운다.

## 7. 실험 셀, 반복 수, 대조군

반복 수: 새 셀 10, 회귀 5, 대조 5, IB 타임아웃 20의 막는 셀 5와 시간 제한 셀 3. 지연 셀의 반복은 실행 수다(실행마다 3000번). 끊김
스위치와 수신 대기 닫기 시각은 각 rank helper 시작부터, 훅 시각은 devComm 생성부터, kill 지연은 실행기가 그 rank를 띄운 때부터 잰다.
"끊김 X:Y"는 `NCCL_GIN_TS_TEST_SOCK_MUTE=X:Y`다. 정의 원문은 [cells.sh](cells.sh)다.

| 셀 | 조건 | 빌드와 반복 수 | 종류 |
|---|---|---|---|
| `f1_b`, `f3_b`, `bidirf_sym_b`, `f4_b`, `f2rel_b`, `pc_dual_f1c0_r1c2_b`, `rc_mute8_f1_b`, `rc_mutekill_b`, `ow_r1in_f1_b`, `ow_r0in_f1r1_b`, `ow_kill0_b`, `ow_hello_f1_b` | 기존 정의 그대로 | `@hd` 각 5 | 회귀 |
| `hd_ref1_f1_b` | 두 rank 끊김 500:8000. rank 1이 8 000 ms부터 1 200 ms 동안 수신 대기 소켓을 닫는다(`NCCL_GIN_TS_TEST_LISTEN_GAP=8000:1200`). rank 0 로컬 QP 오류 12 000 ms. 16 KiB × 1000 | `@hd` 10 | 새 셀 |
| `hd_ref2_f1_b` | 같고 닫는 시간 3 000 ms | `@hd` 10 | 새 셀 |
| `hd_nonce_f1_b` | 두 rank 끊김 500:8000. rank 0의 첫 재연결 HELLO에 틀린 고유값(`NCCL_GIN_TS_TEST_BAD_NONCE=1`). rank 0 로컬 QP 오류 12 000 ms | `@hd` 10 | 새 셀 |
| `hd_rround_f1_b` | rank 1만 끊김 500:8000, rank 0 소켓 시간 초과 20 000 ms, rank 0 로컬 QP 오류 3 000 ms, rank 0 라운드가 정지 뒤 4 000 ms 멈춤(`NCCL_GIN_TS_TEST_STALL=4000@quiesce`). rank 1의 리셋이 그 사이에 온다 | `@hd` 10, `@ow` 5 | 새 셀, 대조 |
| `hd_rxdeath_b` | rank 0(보내는 쪽) kill(`KILL_R0=1`, 3 000 ms). rank 1은 받기만 하고 대기마다 15 s 상한. 끊김 없음 | `@hd` 10, `@ow` 5 | 새 셀, 대조 |
| `hd_hog_f1_b` | `f1_b`와 같고 두 rank가 첫 반복 뒤 모든 SM을 3 s 채우는 커널을 띄운다(`GIN_TS_HOG_MS=3000`) | `@hd` 10 | 새 셀 |
| `hd_fwslow_f1_b` | `f1_b`와 같고 rank 0의 커밋 단계가 8 s 걸린다(`hd`: `NCCL_GIN_TS_TEST_FW_DELAY=8000@commit`, `ow`: 기존 `NCCL_GIN_TS_TEST_STALL=8000@commit`) | `@hd` 10, `@ow` 5 | 새 셀, 대조 |
| `hd_copystall_f1_b` | `f1_b`와 같고 rank 0의 첫 라운드 스트림이 4 s 묶인다(`NCCL_GIN_TS_TEST_COPY_STALL=4000`) | `@hd` 10 | 새 셀 |
| `hd_repost_f1_b` | 양방향, 두 rank 범위 좁히기 끔(전체 재설정: 상대와의 QP 4개, GIN 문맥마다 하나), rank 0 로컬 QP 오류, rank 0 계획이 두 번째 QP를 거부(`NCCL_GIN_TS_TEST_BAD_REPOST=1`). 16 KiB × 400 | `@hd` 10 | 새 셀 |
| `hd_esc_f1_b` | rank 0 로컬 QP 오류 다섯 번(800 ms, 그 뒤 앞 커밋 300 ms 뒤마다), 두 rank 상한 10 000 ms에 3번. 200번 반복 | `@hd` 10, `@ow` 5 | 새 셀, 대조 |
| `hd_shrink_b` | 양방향, rank 1 kill 3 500 ms, rank 0이 `GIN_TS_SHRINK=1`(9절 3번). 대기마다 60 s 상한. 16 KiB × 400 | `@hd` 10, `@ow2` 5 | 새 셀, 대조 |
| `lat_4k`, `lat_256k` | 투명 복구 켬(`stk`는 해당 없음), 장애 없음, 3000번 반복. 같은 hold에서 세 빌드를 섞어 돈다 | `@hdp`, `@ow`, `@stk` 각 5 | 대조 |
| `hdp_kill_b` | `f4_b`와 같다(훅 없음) | `@hdp` 5 | 새 셀 |
| `hdp_mute_b` | 장애 없음. 두 rank helper 포트 51700(`NCCL_GIN_TS_PORT`). rank 0 커널 시작 2 s 뒤부터 8 s 동안 rain이 sunny 관리망 주소에서 오는 포트 51700–51715 TCP를 버린다(iptables 규칙 2개, 9절 4번). 16 KiB × 1000 | `@hdp` 5 | 새 셀 |
| `to20_f3_b` | `NCCL_IB_TIMEOUT=20`, rank 1 상대 QP 오류 700 ms, 막는 대기, 받는 대기 상한 120 s, 감시 110 s | `@hd` 5 | 새 셀 |
| `to20_f3_t` | 같고 시간 제한 대기(`DEV_TIMEOUT_S=8`), 받는 대기 상한 20 s | `@hd` 3 | 새 셀 |

**합계.**

| 종류 | 셀 시행 | 지연 실행 |
|---|--:|--:|
| 회귀(`hd`) | 60 | |
| 새 셀(`hd`, `hdp`) | 128 | |
| 대조(`ow`, `ow2`) | 25 | 30 |
| 합 | 213 | 30 |

새 셀 128은 `hd` 새 셀 110, `hdp` 셀 10, IB 타임아웃 셀 8이다.

## 8. 제외 기준과 중단 기준

**제외 기준.** 제외한 시행은 셀별로 따로 세어 보고한다([score.py](score.py) `status_of`).
- pilot(`results/<날짜>_pilot/`)은 채점하지 않는다.
- NCCL 초기화 전 실패(`bind_fail == 1`)는 제외하고 다음 번호로 계획한 반복 수를 채운다.
- 장애 미적용은 제외하고 다음 번호로 채운다.
  - rank 0 훅 셀에서 `n_fires_r0 == 0`, rank 1 훅 셀에서 `n_fires_r1 == 0`, 두 rank 훅 셀에서 어느 하나가 0. `trigger_miss > 0`.
  - rank 1 kill 셀(`f4_b`, `rc_mutekill_b`, `hd_shrink_b`, `hdp_kill_b`)에서 `killed != 1`, rank 0 kill 셀(`ow_kill0_b`, `hd_rxdeath_b`)에서
    `r0_killed != 1`.
  - `hdp_mute_b`에서 iptables 끊김이 걸리지 않음(`mute_applied != 1`: sudo 실패, 포트를 다른 프로세스가 씀, 커널 시작 없음).
- 순서 미적용은 제외하고 다음 번호로 채운다.
  - `ow_r0in_f1r1_b`: gin-oneway 8절 그대로(rank 1 닫힘 줄이 없거나 첫 분류 기록이 그보다 앞섬).
  - `rc_mutekill_b`, `ow_kill0_b`: 살아남은 rank(각각 rank 0, rank 1)의 닫힘 줄이 없거나, 첫 분류 기록이 있고 닫힘보다 앞섬. 이 실험에서는
    죽음이 장애보다 먼저 거절될 수 있어 첫 분류 기록은 없어도 된다.
  - `hd_rround_f1_b`: rank 1의 리셋이 rank 0 라운드 안에 오지 않음(`r1close_after_q4_ms`가 0 초과 4 000 미만이 아님).
  - `hd_repost_f1_b`: 계획을 거부한 rank 0이 그 라운드의 응답 쪽(`n_plan_rej_r0 >= 1`이고 `plan_rej_init_r0 == 0`). 응답 쪽은 DONE 뒤에
    검사하므로 시작 쪽이 이미 다시 보냈다(9절 1번 (g) 첫 줄). 태그 전에 더함(12절).
- 펌웨어 초과는 제외하고 다음 번호로 채운다: `hd_fwslow_f1_b@hd`가 아닌 `hd`, `hdp` 시행에서 어느 rank든 펌웨어 감시 줄(`n_fwdog_r*`)이나
  `rs_fw_overruns_r*`가 0이 아님. 명령 하나가 3 s를 넘으면 감시가 그 문맥에 영구히 발동해 그 뒤 라운드가 모두 거절되므로, 테스트베드 사정(rain의
  펌웨어 명령 슬롯 누수 같은)이 셀의 주제를 가린다(9절 1번 (g) 둘째 줄). 제외한 시행은 셀별로 따로 세고, 단계 이름과 시간(`fwdog_phase_r*`,
  `fwdog_run_ms_r*`)을 12절에 적는다. 태그 전에 더함(12절).
- 채우려고 다시 돈 시행이 셀 키마다 계획의 50%를 넘으면 그 셀 키는 멈추고 "자료 부족"으로 둔다.

**설정 확인.** 하나라도 어긋나면 제외가 아니라 그 블록을 멈춘다.
- `hd` 시행: 두 rank(kill된 rank 빼고)에 시작 줄 `harden=1 ... production=0`, 투명 복구 시작 줄, 사용자 devComm abort 단어 줄,
  `oneway=1` 줄이 있다.
- `hdp` 시행: 시작 줄이 WARN에 없고(`hd_on == 0`), kv에 `rs_api=1`, `rs_contexts >= 1`.
- `ow`, `ow2` 시행: `oneway=1` 줄, 투명 복구 시작 줄, abort 단어 줄이 있고 `harden` 줄이 없다. `stk` 시행: 셋 다 없다.
- 시험 스위치 줄이 셀과 같다: 기존 스위치 줄은 gin-oneway 8절과 같은 규칙(`hd_rround_f1_b`는 rank 0에 `uto_ms=20000`). 이 실험의 스위치 줄은
  `hd_ref1_f1_b`(rank 1 `listen_gap=8000:1200`), `hd_ref2_f1_b`(rank 1 `8000:3000`), `hd_nonce_f1_b`(rank 0 `bad_nonce=1`),
  `hd_fwslow_f1_b@hd`(rank 0 `fw_delay=8000@commit`), `hd_copystall_f1_b`(rank 0 `copy_stall=4000`), `hd_repost_f1_b`(rank 0 `bad_repost=1`)에만
  있고 다른 `hd` 셀에는 없다.
- 끊김 줄: 두 rank 끊김 셀은 두 rank 모두, 한쪽 끊김 셀은 그 rank만, 나머지는 없다. `ow_r0in_f1r1_b`는 훅 문맥이 1이다.
- 실행기 meta의 `left_rules`(시행 뒤 남은 이 실험의 iptables 규칙)가 0이다.

**pilot에서 보이는 결함.** 태그 전이므로 고칠 수 있다. 고친 것은 12절과 13절에 적고, 고친 뒤에는 그 셀의 pilot을 다시 돈다. 예:
- 시험 조건이 만들어지지 않음: `hd_ref1_f1_b`에서 거부가 0번(수신 대기 닫기 창과 다시 걸기 시각이 어긋남), `hd_rround_f1_b`에서 리셋이 라운드
  밖, `hd_hog_f1_b`에서 훅이 GPU 채우기 창 밖, `hdp_mute_b`에서 소켓이 끊기지 않음. 시각 값을 한 번 바꿀 수 있다.
- 구현 결함: 회귀 셀이나 새 셀에서 예측과 다른 동작이 구현 탓으로 보이면 고치고 다시 빌드, 배포(새 디렉터리)한다.

**중단 기준.**
- **잠금.** 모든 클러스터 명령은 `harness/gpu-initiated/common/cluster_run.sh -w 10800` 안에서 돈다. 10 800 s 안에 잠금이나 유휴 링크를 얻지
  못하면(종료 코드 75) 그 hold를 미룬다. `prio-` 작업에는 양보한다. hold 하나는 15분 이하이고 `timeout -s KILL 880`으로 묶는다.
- **하지 않는 것.** 실제 link down이나 flap, 재부팅, 드라이버 재적재, 커널 모듈 적재, RoCE 주소 변경, 시스템 TCP 설정(sysctl) 변경.
  iptables는 `hdp_mute_b`에서만, rain에서만, sunny 관리망 주소에서 오는 포트 51700–51715 TCP에만, 규칙 2개를 주석 `gin-harden-<pid>`로 붙여 8 s
  동안 건다. 실행기가 끝에서, 종료 trap에서 지우고 남았는지 센다. `chain.sh`가 hold마다 남은 `gin-harden-` 규칙을 다시 지우고, 하나라도 지우지
  못하면 `STOP_iptables`로 멈춘다.
- **프로세스.** 우리가 띄운 프로세스만 그 PID로 끈다. 이름으로 끄지 않는다(`pkill`, `killall` 없음). 실행기는 rank 0의 `timeout` PID와 rank 1
  원격 셸이 남긴 PID를 기록하고, 그 PID와 자식만 신호한다. 원격 PID는 명령줄에 그 시행의 고유 꼬리표가 있을 때만 신호한다(재사용된 PID를 건드리지
  않음). 같은 Unix 계정의 다른 사용자 작업(gds-kv, NVMe-oF, gdsio, mooncake, `prio-` 작업, VS Code)은 건드리지 않는다. `left > 0`이 두 시행
  연속이면 멈춘다.
- **CUDA 메모리 오류.** hold 안의 어느 시행이든 rank 종료 코드 139이거나 로그나 kv에 illegal address, illegal memory access, unspecified
  launch failure가 보이면 그 hold 뒤로 멈춘다(`STOP_cuda`, [hold.sh](hold.sh)). 통신기와 함께 풀리는 사용자 devComm 단어를 커널이 아직 읽는
  경우를 잡는다(11절 pilot 확인 3). pilot 뒤에 더함.
- **mlx5 오류.** hold 앞뒤에 두 노드의 mlx5 커널 줄 전체와 rain의 펌웨어 명령 계수를 남긴다. 새 mlx5 명령 오류 줄이나 펌웨어 명령 실패 계수
  증가가 보이면 그 hold 뒤로 멈춘다(`STOP_mlx5`). 판정은 gin-oneway 8절과 같다.
- **배포.** 새 번들은 새 디렉터리 `hd/`, `hdp/`, `ow2/`, `stk/`에만 둔다. 대상 파일이 이미 있으면 배포 스크립트가 멈춘다. 배포 뒤 기존 번들
  파일의 md5가 두 노드에서 그대로인지 확인한다.

## 9. 실행 방법과 경로

### 1. 라이브러리 계층 (`hd`, `hdp`)

[hd_layer.diff](hd_layer.diff)(`ow` 트리 기준)와 전체 diff [gin_transparent_hd.diff](gin_transparent_hd.diff). 바뀐 파일(+/−줄):

| 파일 | +/− | 무엇 |
|---|--:|---|
| `src/transport/net_ib/gdaki/gin_host_gdaki.cc` | +1548/−321 | 거의 모든 변경 |
| `src/include/nccl_device/utility.h` | +17/−0 | `NCCL_DEVCOMM_ABORT_ERROR`, `abortIsError` |
| `src/include/nccl_device/impl/gin__funcs.h` | +4/−1 | 신호, 계수 대기가 오류 비트로 풀리면 `ncclRemoteError` |
| `src/include/nccl_device/gin/gdaki/gin_gdaki.h` | +31/−0 | 대기와 flush의 해제 결과, 게이트에서 쉬는 대기와 보내는 스레드의 해제 |
| `src/include/nccl_device/gin/gdaki/gin_gdaki_device_host_common.h` | +2/−1 | 게이트 `test` 칸의 새 쓰임(주석만) |
| `src/dev_runtime.cc` | +16/−2 | 사용자 devComm에 따로 둔 단어 |
| `src/init.cc` | +17/−1 | abort, revoke, 중단하는 shrink가 그 단어를 올림. communicator와 함께 해제 |
| `src/gin/gin_host.cc` | +12/−3 | 떼어 낸 helper가 쓰는 collComm은 닫지 않음 |
| `src/nccl.h.in` | +24/−0 | `ncclGinGetRecoveryStats`(실험용) |
| `src/transport/net_ib/gin.cc` | +4/−0 | 운영 빌드에서 proxy 장애 훅 제거 |

(a) **사용자 devComm의 단어.** communicator마다 host-pinned 단어 하나를 둔다(`ncclGinTsUserAbortWord`, 첫 사용자 devComm 때 만들고
`commFree`에서 푼다). `ncclCommAbort`, `ncclCommRevoke`, `NCCL_SHRINK_ABORT`인 `ncclCommShrink`, 복구의 거절(`gdakiTsDecline`), 죽음 판정,
펌웨어 단계 감시가 `NCCL_DEVCOMM_ABORT_ERROR | 원인`을 쓴다(`ncclGinTsUserAbortRaise`, 한 번, 지우지 않음). 장치 쪽은 이 비트로 풀린 대기를
오류로 끝낸다: `waitRollingLessEq`(`waitSignal`, `waitCounter`)는 `ncclRemoteError`, 게이트 대기(`tsPoll`)와 게이트에서 쉬는 대기
(`tsParkStable`, 64번마다 확인)는 QP를 장치 쪽에서 실패로 표시하고 `ncclRemoteError`. 게이트에서 쉬는 *보내는* 스레드도 같은 단어를 본다: helper가
단어의 주소에 비트 0을 붙여 게이트의 `test` 칸에 써 둔다(4바이트 복사 두 번, 위 절반 먼저. 장치는 비트 0이 선 뒤에만 그 값을 쓴다.
분할 시험 스위치를 켠 때만 그 칸이 시험용이라 빠진다. 구조체 배치는 그대로라
`ow` 라이브러리에서는 칸이 0이고 아무것도 바뀌지 않는다). NCCL 자신의 단어(0 또는 1)는 그대로 성공이다. 그룹 실패와 shrink가 잠깐 올리는
communicator 플래그는 이제 사용자 대기를 풀지 않는다. CPU 저장 한 번이라 복사나 펌웨어 명령 없이 쉬는 장치 스레드까지 푼다.
남는 점: 값을 반환하지 않는 대기(`waitSignal`과 `waitCounter`의 void 판, `wait`, `flush`의 void 판, LSA와 CFT 배리어, ll_a2a, GIN proxy 경로)는
같은 단어에 풀리면서 오류를 돌려줄 수 없다. 이제 이 단어는 abort 때만이 아니라 application이 도는 중의 거절, 죽음, 펌웨어 단계 감시에서도 올라가므로,
그런 대기는 짝 없이 끝난 것처럼 보일 수 있다. 같은 순간에 비동기 오류가 서므로 application은 `ncclCommGetAsyncError`로 알아야 한다.

(b) **생존 판정.**
- 거부: 다시 걸기나 확인 접속이 거부되면 한 번째는 기록만 하고 다음 시도를 1 000 ms 뒤로 미룬다. 첫 거부 뒤 1 000 ms 이상 지나 다시 거부되면
  죽음이다(`gdakiTsRefused`). 연결이 되면 거부 수를 지운다.
- 고유값: 각 rank가 준비 all-gather에 64비트 난수를 넣고, 모든 rank가 같은 순서로 섞어 문맥의 고유값을 정한다. HELLO, HELLO-ACK, PROBE,
  PROBE-ACK와 BYE가 싣는다. 받는 쪽은 고유값이 다른 HELLO를 리셋으로 닫는다(다시 거는 쪽에는 "받아들여지지 않음"). 확인 접속은 이제 응답
  (PROBE-ACK)을 기다리고, 고유값이 같은 응답만 "응답"으로 센다. 다른 값이나 무응답은 그대로 모름이다. 프로세스 전체 계수기였던 문맥 번호는
  쓰지 않는다(HELLO의 `arg`는 표시용).
- BYE: 죽지 않은 rank가 연결된 helper 소켓을 닫을 때는 언제나 BYE를 먼저 보낸다: 정상 정리(`gdakiTsStop`), 떼어 낸 helper가 끝날 때, 준비나
  시작이 실패해 이 rank의 복구가 꺼질 때, HELLO를 보낸 다시 걸기. 수신 대기 소켓을 닫기 전에는 backlog에 남은 연결도 받아 BYE로 닫는다(닫기만
  하면 리셋이 간다). 상대는 그 뒤의 FIN을 "떠남"으로 남긴다(죽음이 아니고 드러내지 않는다). 설치 전의 다시 걸기나 확인 접속이 BYE를 받아도
  떠남이다: 그 뒤로는 다시 걸지도 확인하지도 않고, 거부를 세지 않는다.
- 라운드 안의 소켓 끊김: 시작 쪽은 REQ 전에 소켓을 엿보고(FIN이나 오류), REQ 보내기 실패와 ACK 기다림 중 FIN이나 오류도 같게 다룬다. 라운드를
  취소하고(준비한 QP를 놓음, QP는 ERR, 게이트는 닫힌 채), 상대를 모름으로 두고(리셋으로 닫음), 장애를 큐 맨 앞에 다시 넣는다. 그 장애는 재연결
  기다림(`NCCL_GIN_TS_RECONNECT_MS`) 뒤 새 라운드를 돈다. 한 장애에 3번까지. 응답 쪽은 커밋 직전에 소켓을 엿보고, 끊겼으면 준비를 놓고 모름으로
  두며 거절하지 않는다(시작 쪽이 다시 돈다). 동시 시작에서 자기 라운드를 양보한 높은 rank는 자기 장애도 다시 큐에 넣는다. 커밋 뒤의 끊김은
  되돌릴 수 없어 지금처럼 거절한다. 그사이 거절한 상대는 다시 연결되지 않으므로(거절한 높은 rank는 HELLO를 거부하고, 거절한 낮은 rank는 다시
  걸지 않는다) 다시 넣은 장애는 재연결 기다림이 끝난 뒤 "모름"으로 거절된다. 다시 시도와 그 기다림이 `NCCL_GIN_TS_HOLD_MS`보다 길어지면
  쉬던 장치 스레드가 먼저 포기하고, 다시 돈 라운드는 그 때문에 거절된다.
- 죽음은 바로 드러난다: 죽음 판정(BYE 없는 FIN, 거부 두 번)은 helper 루프가 곧바로 거절한다: 비동기 오류, QP를 ERR로, 게이트 실패, 사용자
  devComm 단어. 받기만 하는 rank도 상대의 죽음을 바로 안다.

(c) **상한.**
- 장치 상태 복사: 비동기 복사 뒤 event를 기록해 `NCCL_GIN_TS_COPY_MS`(2 000 ms)까지 확인한다(`gdakiRecCopyWait`). 넘으면 그 라운드는 거절한다.
  늦은 복사는 스트림에 남아 staging 버퍼를 쓸 수 있으므로, 그 event가 끝날 때까지 다음 복사는 바로 실패한다(`gdakiRecCopyBlocked`).
- 펌웨어 단계: 라운드의 QP 상태 바꾸기와 QUERY_QP를 단계로 감싼다(`gdakiRecFwGuard`: 2ERR, commit, QUERY_QP). 단계 안의 펌웨어 명령 하나하나와
  복사 하나하나가 시계를 다시 맞춘다(`gdakiRecFwMark`). 그래서 감시는 단계 전체가 아니라 명령 하나의 시간을 본다. 복사는 자기 상한(2 000 ms)이
  더 짧아 단계 초과로 세지 않는다. 분류기 감시 스레드가 매 확인마다 그 시간을 보고, `NCCL_GIN_TS_FW_MS`(3 000 ms)를 넘으면 사용자 devComm
  단어를 올려 장치 대기를 오류로 풀고 비동기 오류를 드러낸다. 명령이 돌아오면 라운드는 거절한다(`gdakiTsFwCheck`, REQ를 보내기 직전에도 확인).
  초과 표시는 한 번 서면 지우지 않는다(그때 단어가 올라가므로 이후 라운드는 모두 거절된다).
- 거절의 순서: 먼저 QP를 ERR로 바꾼다(펌웨어 명령. 오래 걸리면 감시가 단어와 비동기 오류를 대신 올린다). 그래서 오류로 풀린 대기는 NIC가 그
  상대의 QP에서 더는 일하지 않는다는 뜻이다(단어가 communicator마다 하나라서, 건강한 상대와의 QP는 RTS인 채 그 대기도 오류로 풀린다). 다음으로 복사
  없이 할 수 있는 것: 사용자 devComm 단어, 비동기 오류, 상대에게 FAIL, 거절 줄. 마지막이 게이트 실패와 장치 오류 상태(상한 있는 복사)다. 복사가
  막혀 못 쓴 것은 helper의 100 ms 점검(`gdakiTsScan`)이 복사가 풀리는 대로 다시 쓴다. 복사 상한은 펌웨어 감시 상한보다 짧게 고정한다
  (`NCCL_GIN_TS_COPY_MS`가 `NCCL_GIN_TS_FW_MS` 이상이면 그 절반으로).
- `ncclCommAbort`: helper의 지금 펌웨어 명령 하나가 `NCCL_GIN_TS_ABORT_JOIN_MS`(3 000 ms)를 넘을 때까지, 전체로는
  `NCCL_GIN_TS_ABORT_JOIN_MAX_MS`(15 000 ms)까지 기다린다(`gdakiTsJoinBounded`. 펌웨어 명령 밖의 기다림은 모두 상한이 있고, 멈추라는 신호 뒤
  helper는 새 장애를 잡지 않는다). 넘으면 떼어 낸다. 떼어 낸 helper의 collComm은 어느 정리 경로에서 떼어 냈든 기록해 닫지 않는다. helper의 끝("끝남")과 정리의 포기("떼어 냄")는
  비교 후 교환 한 번씩이라 둘 중 하나만 이긴다. 떼어 냄은 helper가 communicator에 쓰는 자물쇠(`gdakiTsToComm`: 비동기 오류 칸, 사용자 devComm 단어)
  안에서 정해지므로, 그 뒤 helper는 communicator에 아무것도 쓰지 않는다. 떼어 낸 helper는 명령이 돌아오면 루프를 나가며 자기 소켓을 BYE와 함께 닫는다.
  정리 쪽은 복사를 내지 않고(장치 대기와 쉬는 보내는 스레드는 abort의 단어로 풀림), 그 collComm을 닫지 않는다(`ncclGinHostFinalize`). 나중의
  `ncclDevCommDestroy`는 helper가 10 s 안에 끝나지 않거나 늦은 복사가 10 s 뒤에도 스트림에 있으면 그 GDAKI 문맥(QP, 스트림, staging, 분류기
  상태)을 통째로 남긴다(해제하지 않음). 진단용 게이트 읽기와 QUERY_QP는 연구 빌드에서만, helper가 제때 끝나고 상한을 넘은
  복사나 단계가 없었을 때만 한다. 운영 빌드에는 없다.
- 남는 점: 멈춘 펌웨어 명령 자체는 끊을 수 없다. 그 helper 스레드와 문맥, collComm은 명령이 돌아올 때까지(또는 프로세스 끝까지) 남는다. 연구
  빌드의 정리 때 진단 QUERY_QP는 감시 밖의 펌웨어 명령이고, 떼어 낸 뒤에도 정리가 기다리는 장애 훅과 분할 시험 스레드는 막 발사하려던 참이면
  helper가 쥔 QP 자물쇠를 기다린다(연구 빌드만. 이 실험의 셀에서는 훅이 이미 끝나 있다). 죽음은 문맥마다 판정하지만 사용자 devComm 단어는 communicator마다 하나라서, 관리망
  끊김 중에 한 rank가 devComm 하나만 없애면(그 소켓은 이미 닫혀 BYE가 갈 길이 없다) 상대는 거부 두 번 뒤 죽음으로 보고 communicator 전체의 대기를
  푼다.

(d) **다시 보내기 계획.** `gdakiTsReplayResume`을 두 번에 나눈다. 첫째, 커밋 지점 전에 라운드의 모든 QP에서 범위, 덮인 슬롯, 사본 영역,
opcode를 검사해 다시 보낼 WQE를 모두 만든다. 하나라도 거부되면 아무것도 보내지 않고 거절한다. 둘째, QP마다 보내고, doorbell을 울리고, 새
에폭을 낸다. 둘째 단계의 실패는 복사나 doorbell의 실패다. 이 보장은 rank마다다. 라운드 전체는 아니다: 시작 쪽은 DONE 전에, 응답 쪽은 DONE 뒤에
검사한다((g) 첫 줄).

(e) **상한 넘김과 계수.** 시작과 응답 라운드(응답 쪽은 범위 검사를 통과한 것만)의 시작 시각을 창(`NCCL_GIN_TS_ESCALATE_WINDOW_MS`, 60 000)에 모아, 이미 `NCCL_GIN_TS_ESCALATE_ROUNDS`
(8)번이면 새 라운드 대신 상한 넘김이다: 거절(사유에 상한을 적음, `ncclGetLastError`에도 그 WARN이 남음), 비동기 오류, 그 문맥의 복구를 멈춤.
`ncclGinGetRecoveryStats(comm, &stats)`(실험용, `nccl.h`)는 시작한 라운드(두 역할), 복구, 거절, 재연결, 죽음 판정, 상한 넘김, 취소, 펌웨어
단계 초과, 복사 초과를 돌려준다. communicator에 등록된 문맥만 세므로 `ncclCommAbort`나 `ncclCommDestroy` 전에 불러야 한다(이 실험의 드라이버는 정리
전에 부른다). 정리 때 INFO 요약 줄 하나를 남긴다.

(f) **운영 스위치.** `-DNCCL_GIN_TS_PRODUCTION`은 장애 훅(`NCCL_GIN_FAULT_INJECT*`, proxy 훅 포함), 모든 시험 스위치
(`NCCL_GIN_TS_TEST_*`), 음성 대조(`NCCL_GIN_TS_DIAG`, `NCCL_GIN_RECOVERY_DIAG`), 진단(`NCCL_GIN_Q4_QPWATCH_MS`, `NCCL_GIN_Q4_LATE_READ_US`,
`NCCL_GIN_GDAKI_CQ_TYPE`, 분류 줄의 QUERY_QP, 정리 때의 게이트 읽기와 QUERY_QP)를 지우고, 정보성 줄(`GIN_TS_NOTE`)을 INFO로 낮춘다. 장치
헤더의 분할 시험 분기는 남는다(호스트가 그 표시를 켜지 않으면 닿지 않음). `NCCL_GIN_TS_PORT=<p>`(헬퍼 수신 대기 포트, 기본 0)는 운영 옵션이다.
helper 소켓은 이제 `FD_CLOEXEC`다.

(g) **알려진 문제.** 독립 리뷰(2026-10-09, 다른 에이전트가 `hd_layer.diff`와 빌드 트리를 읽음)의 판정은 "조건부로 예"이고 막는 문제는 없다.
아래는 그 리뷰가 남긴 것이다. 줄 번호는 빌드 트리의 `gin_host_gdaki.cc`다(다른 파일은 이름을 붙임). 이 실험에서는 고치지 않는다: pilot이 지금
빌드로 대기 중이고, 메커니즘을 바꾸면 빌드와 배포를 다시 해야 한다. 고칠 방법은 19절에 옮겼다.

| 등급 | 문제 | 이 실험의 셀에 미치는 영향 | 처리 |
|---|---|---|---|
| 중간 | 다시 보내기 계획의 검사는 rank마다이고 라운드 전체가 아니다(4685, 4692행 대 4403행). 시작 쪽은 두 단계를 모두 마치고 다시 보낸 뒤 DONE을 보내고, 응답 쪽은 DONE 뒤에야 검사한다. 거부한 rank가 응답 쪽이면 시작 쪽은 이미 다시 보내고 복구 줄을 남긴 뒤 FAIL을 받고 거절한다 | 계획 거부 셀(D1)은 거부한 rank 0이 그 라운드의 시작 쪽일 때만 성립한다. rank 0은 낮은 rank라 동시 시작에서도 시작 쪽을 지키므로 거의 언제나 그렇다 `[추론]` | 8절에 제외 조건을 더하고 D1 문장, H4, 질문 3을 좁힘. 판정식은 그대로 |
| 중간 | 펌웨어 감시는 문맥마다 한 번 발동하면 영구적이다(2761–2776, 2552, 4494행). 명령 하나가 3 s를 넘으면 사용자 단어가 올라가고 `surfaced`가 서서 그 뒤 라운드는 모두 거절된다 | rain의 펌웨어 명령 슬롯 누수 같은 테스트베드 사정으로 명령 하나가 느려지면, 투명해야 할 셀이 메커니즘과 무관하게 거절될 수 있다 | 8절에 제외 조건을 더함 |
| 중간 | ACK를 기다리다 취소한 라운드가 이미 커밋한 응답 쪽과 엇갈릴 수 있다(시작 쪽 4585행, 응답 쪽 4375–4392행). 응답 쪽은 거절하고, 거절한 낮은 rank는 다시 걸지 않으며(3193행) 거절한 높은 rank는 HELLO를 닫는다(3409–3414행). 다시 넣은 장애는 `NCCL_GIN_TS_RECONNECT_MS`(10 s)를 다 기다린 뒤 "모름"으로 거절되고, 세 번이면 `NCCL_GIN_TS_HOLD_MS`에 닿는다. 멈춤이 아니라 늦어짐이다 | 라운드 안 리셋 셀(B6)은 리셋이 REQ 전에 오게 만들었다(정지 뒤 4 s 멈춤 중). REQ 직전 확인에서 취소되므로 응답 쪽은 그 REQ를 보지 않는다 `[소스]` | 문서 |
| 낮음 | 오래된 첫 거부도 죽음 판정에 센다(3043–3064행). 거부 수는 연결이나 PROBE-ACK 때만 지우고(3122, 3226, 3304행) 시간이 지나도 지우지 않는다 | 지금 셀 중 해당하는 것이 없다 `[소스]` | 문서 |
| 낮음 | 상한 넘김은 다시 시도와 범위 재실행도 라운드로 센다(`gdakiTsEscalated` 4211행, 4498, 4751행에서 부름). 취소 계수는 비대칭이다: 시작 쪽은 다시 넣은 것만(4271행), 응답 쪽은 모든 취소를 센다(4293행) | 상한 넘김 셀(E1)은 영향 없음. 취소 계수는 판정식에 쓰지 않는다 `[소스]` | 문서 |
| 낮음 | 라운드 안의 BYE 없는 FIN은 이제 죽음이 아니라 모름이다(4554, 4338행). 라운드 중 kill된 상대는 다시 시도의 재연결 기다림 중 1 s 이상 떨어진 거부 두 번으로만 죽음이 된다. 죽은 호스트가 아예 답하지 않으면 10 s 뒤 "모름"으로 거절된다 | kill 셀은 모두 쉬는 중(라운드 밖)에 kill한다 `[소스]`. 라운드 중 kill은 재지 않는다 | 문서 |
| 낮음 | 사용자 단어는 communicator마다 하나다(2262행). 쉬던 대기는 오류 비트를 보면 자기 QP를 실패로 표시하므로(`gin_gdaki.h` 236–239행), 상대 하나에 대한 거절이 건강한 상대와의 게이트도 실패시킨다 | 2 rank라 상대가 하나뿐이다 | (a)와 (c)에 적음 |
| 낮음 | 연구 빌드의 정리에는 상한 없는 단계가 남는다: 진단 QUERY_QP(5612행 이후)는 초과가 있었을 때만 건너뛰고, 장애 훅과 분할 시험 스레드의 join은 QP 자물쇠를 기다린다 | 운영 빌드는 해당 없음. 연구 빌드의 abort 시간 예측(A5, C3)은 정리 때 펌웨어가 정상이라는 전제다 | 문서 |
| 낮음 | 쉬는 보내는 스레드는 사용자 단어의 주소를 쉬기 시작할 때 한 번 읽는다(`gin_gdaki.h` 282행) | 단어가 생기기 전에 쉬기 시작한 스레드만 해당하고, 실제로는 그 창이 생기지 않는다 `[추론]` | 문서 |
| pilot | (본 실행 뒤 정정: GPU가 가득 찬 적이 없었고 원인은 드라이버의 호출 순서다, 13절) GPU가 가득 차면 helper의 장치 상태 복사가 끝나지 않는다. pilot 1회에서 두 rank의 4 B 복사(쉬는 중의 게이트 점검)가 application의 GIN 커널이 끝난 순간에야 끝났다. 그사이 분류기 감시가 "helper가 1 s 넘게 돌지 않음"으로 오류를 드러냈고, 복사 상한(2 s)이 지나 두 rank가 거절했다 `[측정]` | GPU 채우기 셀(C1)은 틀릴 가능성이 높다. 상한 덕분에 멈춤이 아니라 2 s 안팎의 거절로 끝난다. 거절 뒤 늦은 복사가 끝나자 helper 점검이 게이트를 실패로 다시 썼다(2차 리뷰 수정이 동작함) `[측정]` | 예측은 그대로. 원인 `[미확인]`(빈 SM 자리가 필요한 복사로 보임 `[추론]`) |
| pilot | (본 실행 뒤 정정: "그 오류를 가진 devComm이 아직 등록된 동안", 13절) 순정 NCCL은 GIN 비동기 오류가 있는 communicator의 shrink를 막는다: `ncclCommInitChildComm`이 `ncclCommEnsureReady`로 부모의 비동기 오류를 그대로 돌려준다(`init.cc`, 순정 코드) `[소스]`. pilot에서 `hd`와 `ow2` 모두 `ncclCommShrink`가 0 ms에 `ncclRemoteError`였다 `[측정]` | shrink 넘기기(A2)는 틀릴 것으로 본다. 대기 해제(A1)와 대조(A3, A4)는 영향 없음 | 예측은 그대로. 고치려면 라이브러리 수정이 필요(19절) |

리뷰가 본 대로 정리한 주장별 상태:
- 있음: 따로 둔 abort 단어(revoke, 중단하는 shrink, 펌웨어 감시도 올림), 고유값, 복사 상한, 운영 빌드(시험 스위치, 진단, 로그 수준만
  다름), 통계 API(abort 전에 불러야 함), 상한 넘김.
- 부분: "풀린 대기가 오류를 돌려준다"(void 대기, LSA와 CFT 배리어, ll_a2a, proxy 경로는 조용히 끝남), 리셋 뒤 다시 시도(셋째 줄), abort가
  멈추지 않음(운영 빌드는 그렇고 연구 빌드는 여덟째 줄), 다시 보내기 검사(첫째 줄).
- 리뷰가 확인하지 못한 것 셋은 pilot에서 본다(11절).

### 2. 시험 스위치 (`hd`만)

기존 스위치(gin-oneway까지)는 그대로다. 새 스위치는 다섯이다. 하나라도 켜면 helper 시작 때 `TEST harden knobs` 줄을 남긴다.
- `NCCL_GIN_TS_TEST_LISTEN_GAP=<시작 ms>:<길이 ms>`: 그때 수신 대기 소켓을 닫고 길이 뒤 같은 주소와 포트로 다시 연다.
- `NCCL_GIN_TS_TEST_BAD_NONCE=<n>`: 이 rank가 보내는 재연결 HELLO나 PROBE 중 처음 n개에 틀린 고유값.
- `NCCL_GIN_TS_TEST_FW_DELAY=<ms>@<commit|2ERR|QUERY_QP>`: 그 펌웨어 단계에 처음 들어갈 때 그 안에서 <ms> 잔다(정리 때도 깨지 않음).
- `NCCL_GIN_TS_TEST_COPY_STALL=<ms>`: 첫 라운드의 정지 전에 복구 스트림에 <ms> 자는 호스트 콜백을 넣는다.
- `NCCL_GIN_TS_TEST_BAD_REPOST=<k>`: 다시 보내기 계획이 k번째 QP를 거부한다.

### 3. 드라이버 (`../gin_ts2.cu`)

application 코드에 복구는 넣지 않는다. 선택 몇 개만 더했다(설정하지 않으면 동작은 그대로다).
- `rx_phantom`: 받는 쪽(한 스레드 루프)이 성공을 받은 반복 중 그때 읽은 신호 값(`sigSeen`)이 목표보다 작은 반복 수. 1a가 막으려는 "도착하지 않은
  신호를 받은 것으로 앎"을 직접 센다.
- `GIN_TS_HOG_MS`: GIN 커널이 첫 반복을 마친 뒤(상주한 뒤) SM 수 × SM당 블록 수(점유율 계산기, 256 스레드)인 커널을 다른 스트림에 띄워 그
  시간 동안 돈다. (본 실행 뒤 정정, 13절: 이 커널의 점유율 질의(커널 적재), `cudaMalloc`, 스트림 생성이 GIN 커널을 띄운 뒤에 있어, 이 커널은
  GIN 커널 옆에서 시작하지 않았다.)
- `GIN_TS_SHRINK=1`(rank 0): 주 대기 뒤 `ncclCommShrink(comm, {1}, NCCL_SHRINK_ABORT)`. 새 communicator가 오면 1024개 float `ncclAllReduce`로
  확인(5 s 상한)하고 없앤다. 옛 커널을 `GIN_TS_HO_WAIT_S`(3 s) 기다리고, 마지막 `ncclCommAbort` 뒤 받는 쪽 결과를 다시 읽는다.
- `rs_*`: 정리 전 `ncclGinGetRecoveryStats`(실행 때 `dlsym`으로 찾아 `ow` 라이브러리에서도 같은 바이너리가 돈다).
- `-DGIN_TS_STOCK_API`: 순정 헤더에서 막는 `flush`가 값을 돌려주지 않는 것만 맞춘다(`stk` 드라이버).
- `ow2` 대조: 이 드라이버의 장치 코드는 `hd` 헤더로 컴파일된다. 장치와 호스트 사이 구조체의 배치는 바꾸지 않았다. 바뀐 장치 분기는 오류 비트와
  게이트 `test` 칸의 비트 0에서만 달라지는데, `ow` 라이브러리는 그 비트를 쓰지 않고 그 칸을 0으로 둔다(분할 시험 스위치를 켠 때만 시험용
  포인터). 그래서 `ow2`의 대기 해제는 `ow`와 같다 `[소스]`.

### 4. 실행기 ([run_trial_hd.sh](run_trial_hd.sh))

`../scripts/ts2/run_trial.sh`에서 갈라졌다. 같은 인자, 같은 시행 파일, meta에 몇 키를 더한다. 다른 점:
- 프로세스는 기록한 PID로만 끈다(8절 프로세스). rank 1 파일은 시행마다 고유한 이름이다.
- 주소 흔들기와 보조 GID는 없다. rank 0의 관리망 주소는 sunny 관리망 주소로 가는 경로의 출발 주소로 실행 때 찾는다(주소를 적지 않음).
- `MGMT_MUTE=<시작 ms>:<길이 ms>`, `MGMT_PORT=<p>`: 8절의 iptables 끊김. 걸기 전에 `sudo -n iptables`와 포트 범위의 소켓 주인을 확인한다.

### 5. IB 타임아웃 20과 장치 쪽 시간 제한 (소스에서 한 예측)

- 막는 대기(`flush(coop)`): 투명 복구에서 `tsPoll`은 CQE를 기다리는 동안 게이트의 계수 영역 안에서 폴링하고, 상한은 호출자의 시간 제한(없음)과
  abort뿐이다. 게이트의 대기 상한(`NCCL_GIN_TS_HOLD_MS`)은 복구 중 *쉬는* 시간에만 걸린다. 그래서 상대 QP 오류는 재시도가 다 끝나는 약 58 s
  뒤 RETRY_EXC로 분류되고, 그때 상대가 살아 있으면(소켓이 멀쩡함) 보통의 라운드로 복구된다. 투명 복구는 감지 시간을 줄이지 않는다
  (예측 T1, T2).
- 시간 제한 대기(NCCL 2.31.2부터의 `timeoutCycles` 판): 시간 제한이 감지 시간보다 짧으면 `tsPoll`은 제한 시각에 시간 초과 기록(분류는
  "오류 CQE 없음")을 남기고 `ncclTimeout`을 돌려준다. 오류 CQE를 보고 기록을 내는 것은 장치 대기뿐이라, 커널이 끝나면 58 s 뒤의 오류 CQE를
  아무도 읽지 않는다. 복구도 거절도 시작되지 않고 application은 시간 초과만 본다(예측 T3). application이 같은 QP에서 다시 기다리면 그때 분류되어 복구될
  것이다 `[추론]`. 시간 제한이 감지 시간보다 길면 막는 대기와 같다. 복구 중 쉬는 시간은 호출자의 시간 제한에 들어가므로, 제한이 라운드보다
  짧으면 그 대기는 시간 초과로 끝나고 작업은 나중에 완료될 수 있다(gin-s2 설계 그대로).
- 운영 권고 `[추론]`: 장치 쪽 시간 제한은 IB 재시도 시간(타임아웃 20이면 약 60 s)보다 길게 두거나, 시간 초과를 받은 application이 같은 QP에서 다시
  기다려야 투명 복구가 장애를 본다.

### 빌드 ([build_hd.sh](build_hd.sh), 세션 스크래치)

1. `setup`: `agent_ts2ow`의 소스와 빌드 디렉터리를 `agent_ts2hd`로 복사하고, 의존 파일과 장치 manifest의 경로를 바꾸고 원래 시각을 돌려준다.
   `agent_ts2ow` 작업 트리(= `ow_layer.diff`, md5 `06f450ec`, 빌드 libnccl `b4af65c5`)를 스크래치 저장소에 "gin-oneway ow" 커밋으로 남긴다.
2. `hd`: 이 계층을 작업 트리에 두고 증분 빌드(장치 헤더가 바뀌어 장치 객체도 다시 컴파일). libnccl → `out/hd`.
3. `hdp`: `build/`를 `build-hdp/`로 복사(경로 바꿈, 시각 유지), 호스트 객체를 모두 지우고 `CXXFLAGS=-DNCCL_GIN_TS_PRODUCTION`으로 빌드. `make -n`에
   장치 객체가 하나도 없어야 한다(스위치는 호스트 파일만 읽음). libnccl → `out/hdp`.
4. `stock`: 스크래치 저장소의 루트 커밋을 세션의 NCCL 클론(읽기만)의 태그 `v2.32.3-1`(`12df1a11`)과 파일 단위로 비교하고, 같으면 git worktree로
   꺼내 처음부터 빌드한다. libnccl → `out/stk`.
5. `drivers`: `../gin_ts2.cu`를 `build/` 헤더로(→ `out/drv`, `hd`, `hdp`, `ow2`가 씀), `build-stock/` 헤더와 `-DGIN_TS_STOCK_API`로(→ `out/drv-stk`)
   컴파일한다.

### 배포 ([deploy_hd.sh](deploy_hd.sh))

두 노드의 새 디렉터리 `hd/`, `hdp/`, `ow2/`, `stk/`에 둔다(8절 배포). 확인 출력은 파일로만 받는다.

### 실행 ([hold.sh](hold.sh), [chain.sh](chain.sh), [cells.sh](cells.sh))

hold마다 `chain.sh`가 `cluster_run.sh -w 10800 -t ghd-<hold>`에 넣는다. 결과 폴더 아래 빌드별 폴더(`hd/`, `ow/`, `ow2/`, `hdp/`, `stk/`)에 시행 파일이 쌓인다.

| hold | 내용 | 추정 `[추론]` |
|---|---|---|
| H0 pilot | 새 셀 11개 `hd` 1회씩, 대조 5개 1회씩, `hdp_kill_b`, `hdp_mute_b`, 세 빌드 4 KiB 지연 1회씩, IB 타임아웃 셀 2개 1회씩, `rc_mute8_f1_b`와 `ow_kill0_b` `hd` 1회씩(25회). 채점 안 함 | 실제 6분 3초 `[측정]` |
| H1 | 회귀 6셀(`f1_b`, `f3_b`, `bidirf_sym_b`, `f4_b`, `f2rel_b`, `pc_dual_f1c0_r1c2_b`) × 5, 지연 30실행(섞어서) | 5분 |
| H2 | 회귀 5셀(`rc_mute8_f1_b`, `rc_mutekill_b`, `ow_r1in_f1_b`, `ow_r0in_f1r1_b`, `ow_kill0_b`) × 5 | 7분 |
| H3 | `ow_hello_f1_b` × 5, `hd_ref1_f1_b`, `hd_ref2_f1_b` × 10 | 7분 |
| H4 | `hd_nonce_f1_b` × 10, `hd_rround_f1_b` `hd` 10과 `ow` 5(2:1로 섞어서) | 11분 |
| H5 | `hd_rxdeath_b`(2:1), `hd_hog_f1_b` × 10, `hd_fwslow_f1_b`(2:1) | 7분 |
| H6 | `hd_esc_f1_b`(2:1), `hd_shrink_b`(`hd` 10, `ow2` 5, 2:1), `hd_copystall_f1_b`, `hd_repost_f1_b` × 10 | 6분 |
| H7 | `hdp_kill_b`, `hdp_mute_b` × 5, `to20_f3_t` × 3 | 4분 |
| H8 | `to20_f3_b` × 5(시행마다 약 61 s, 감시 상한 110 s) | 5–10분 |

시행 시간은 pilot의 시행별 시간(시행 파일이 생긴 간격, n=1씩)으로 어림했다 `[측정]`: 두 rank 끊김 셀 15–19 s, 라운드 안 리셋 셀 28 s(`hd`),
31 s(`ow`), kill과 거절 셀 4–9 s, 지연 3–4 s, 막는 IB 타임아웃 셀 61 s. pilot에 없는 회귀 셀은 gin-oneway의 hold 기록(짧은 셀 약 5 s,
`../oneway/EXPERIMENT.md` 12절)으로 어림했다. hold마다 잠금과 유휴 확인이 약 30 s 더 든다. 가장 긴 H4도 880 s 상한 안이다. 본 실행(H1–H8)의
클러스터 시간은 잠금 대기를 빼고 50–60분이다 `[추론]`.

### 채점

1. `../scripts/ts2/rows.py`로 hold 폴더마다 시행 CSV를 만든다.
2. `../s2_close/rows_extra.py`, `../pair_check/rows_pc.py`, `../oneway/rows_ow.py`, 이 폴더의 `rows_hd.py`가 3.1의 열을 붙인다.
3. `score.py`가 [predictions.csv](predictions.csv)의 판정식을 3.2 문법대로 적용한다. 결과는 `results/<날짜>/SCORE.md`와
   `results/<날짜>/trials_scored.csv`다.

**출력.** 결과 폴더 `results/<날짜>/<빌드>/`. 원시 로그는 Release에 올린다.

## 10. 완료 조건과 QA 기준

- [x] 메인 세션이 pilot(H0)을 돌리고 결과를 12절에 적은 뒤, 고칠 것을 고치고 태그를 달았다.
- [x] 모든 셀이 계획한 반복 수만큼 실행됐다. 제외와 실패를 따로 센 표가 있다([SCORE.md](results/20261009/SCORE.md) 마지막 표).
- [x] 예측 52줄마다 판정(맞음, 틀림, 자료 부족)과 놓친 시행 목록이 있다([SCORE.md](results/20261009/SCORE.md)).
- [x] 다른 에이전트가 `score.py`를 보지 않고 원자료에서 핵심 수치를 다시 셌다(생존 판정과 원인, 거부 수와 간격, 취소와 재시도, 대기 해제 원인과
  시각, 신호 없이 성공한 대기, shrink 결과, abort 시간, 통계 값, 지연).
- [x] 다른 에이전트가 `hd_layer.diff`, 드라이버와 실행기 변경을 읽고 리뷰했다(라이브러리 계층은 설계 단계 리뷰 두 번과 독립 리뷰, 12절과 9절 1번
  (g). 드라이버, 실행기, 채점 코드는 [qa/code_review.md](qa/code_review.md)).
- [x] smoke와 pilot, 제외 시행이 결과에 섞이지 않았다(pilot은 `results/20261009_pilot/`, 제외 4회는 bind 실패).
- [x] 새 빌드의 md5, 전체 diff, pristine + diff 확인, 운영 빌드의 strings 확인을 5절과 12절에 적었다.
- [x] 원자료를 Release `data-20261009`에 올렸다. `DATA.md` 기록은 메인 세션이 상위 문서와 같은 PR에서 한다.
- [x] hold 전후 mlx5 스냅숏에 새 명령 오류가 없었다. hold 밖(H8과 채우기 사이)의 sunny "FWTracer: Events were lost" 한 줄은 12절에 적었다. 남은
  iptables 규칙이 0이었다.
- [x] 모든 시행에서 CUDA 메모리 오류(종료 코드 139, illegal address)가 없었다(`STOP_cuda` 없음).

## 11. 작업 체크리스트

- [x] 리뷰가 짚은 줄 확인, 설계(1, 9절)
- [x] 라이브러리 계층, 운영 스위치, 드라이버, 실행기 구현
- [x] 빌드: `hd`, `hdp`, `stk`, 드라이버 두 개. pristine + diff 확인, 운영 빌드 strings 확인
- [x] 설계 단계 코드 리뷰 1차(다른 에이전트)와 반영
- [x] 고친 부분의 2차 리뷰(다른 에이전트)와 반영
- [x] `cells.sh`, `hold.sh`, `chain.sh`, `deploy_hd.sh`, `rows_hd.py`, `score.py`, `predictions.csv`
- [x] 질문, 가설, 셀, 예측 초안 (`DRAFT`)
- [x] 배포(메인 세션, 2026-10-09 02:18:27–02:18:57)
- [x] pilot H0(메인 세션, 03:24:59–03:31:02, 채점 안 함), 결과로 고칠 것 고치기(12절)
- [x] pilot 확인 1(리뷰가 확인하지 못함), 결과 "됨": 끊긴 쪽의 소켓 필터가 RST도 버리는가. `hd_ref1_f1_b`, `hd_ref2_f1_b` pilot에서 rank 0의 첫 다시 걸기
  거부(`refusal1_ms_r0`)가 rank 0 끊김 끝(`mute_off_ms_r0`) 뒤이고, `hd_ref1_f1_b`의 거부(`n_refused_dial_r0`)가 한 번뿐이다. 끊김 중에 거부가
  나오면 거부 셀의 전제가 무너지므로, 수신 대기 닫기 창을 끊김 끝 뒤로 옮긴다(8절의 시각 값 변경, 12절과 13절에 기록)
- [x] pilot 확인 2(리뷰가 확인하지 못함), 결과 "안 됨"(본 실행 뒤 정정: GPU가 가득 찬 적이 없었다, 13절): GPU가 가득 찬 동안 작은 복사가 2 s 상한 안에 끝나는가. `hd_hog_f1_b` pilot에서 `n_copyto_r*`와
  `rs_copy_timeouts_r*`가 0이고, 훅 발사가 채우기 창 안(`fault_after_launch_r0_ms`가 `hog_launch_after_launch_ms_r0` 뒤 3 000 ms 안)이다
- [x] pilot 확인 3(리뷰가 확인하지 못함), 결과 "불분명": `commFree`가 사용자 커널이 끝난 뒤에 사용자 단어를 푸는가. abort 때 커널이 남을 수 있는 `hd` pilot
  시행(`hd_shrink_b`, `hd_rxdeath_b`, `hd_fwslow_f1_b`, `hd_copystall_f1_b`)에서 두 rank의 종료 코드(meta `r0rc`, `r1rc`)가 139가 아니고, 로그와
  kv에 CUDA `illegal address` 오류가 없으며, `teardown_r*`가 `no error`다
- [x] pilot에서 펌웨어 초과 제외(8절)에 해당하는 시행 수와 단계 이름(`fwdog_phase_r*`)을 12절에 적는다(0회)
- [x] 고정 절 완성, 상태 `PREREGISTERED`, 해시 기록을 커밋 하나로 만들고 그 커밋에 `prereg/` 태그
- [x] 본 실행 H1–H8과 채우기 hold (`RUNNING`)
- [x] 채점 (`QA`)
- [x] 독립 재계산과 코드 리뷰
- [x] 결과 정리, 원자료 Release `data-20261009`. PR은 메인 세션이 `DATA.md`, 상위 README와 함께 낸다
- [x] 결론 확정 (`COMPLETE`)

## 12. 실행 기록 (시간순)

| 시각 | 무엇을 했나 | 결과와 근거(경로, 커밋, 실행 ID) |
|---|---|---|
| 2026-10-09 | 리뷰가 짚은 ow.diff 줄을 모두 다시 읽어 확인 `[소스]`. `base` 번들이 순정이 아님을 확인(gpudb v2, libnccl `1ed8e0a1`) `[측정]` | 1절, 이 문서 머리 |
| 2026-10-09 | 스크래치 `agent_ts2hd` 준비: `agent_ts2ow`(작업 트리 = `ow_layer.diff` md5 `06f450ec`, 빌드 `b4af65c5`) 복사, 경로 바꿈, "gin-oneway ow" 커밋. 복사 직후 `make -n`이 버전 표시만 다시 컴파일함을 확인 `[측정]` | [build_hd.sh](build_hd.sh) `setup` |
| 2026-10-09 | 계층 구현(9절 1번), 드라이버 선택(9절 3번), 실행기(9절 4번). 연구와 운영 두 변형 모두 경고 없이 컴파일. 운영 객체에 시험 스위치 이름 0개, 연구 객체 20개 `[측정]` | [hd_layer.diff](hd_layer.diff) |
| 2026-10-09 | 순정 빌드: 스크래치 루트 커밋이 상위 태그 `v2.32.3-1`(`12df1a11`)과 파일 단위로 같음(VERIFIED), 처음부터 빌드 4분 `[측정]`. libnccl `stk` `b380e622` | `build_hd.sh stock` |
| 2026-10-09 | 드라이버를 `hd` 헤더와 순정 헤더(`-DGIN_TS_STOCK_API`) 두 쪽으로 경고 없이 컴파일 `[측정]` | `build_hd.sh drivers` |
| 2026-10-09 | 설계 단계 코드 리뷰 1차(다른 에이전트, 코드만 읽음): 16건. 버그 3(떼어 낸 helper가 도는 중 `ncclDevCommDestroy`가 문맥을 해제함, 거절의 장치 오류 상태 쓰기가 상한 없이 막힌 복사를 기다림, BYE 없이 닫는 경로가 남아 상대가 고장 없는 communicator를 죽음으로 거절함), 위험 8, 사소 5 | 9절 1번 (a)–(e)에 반영 |
| 2026-10-09 | 반영: helper의 끝과 떼어 냄을 비교 후 교환 한 번으로 정함, communicator 쓰기를 자물쇠 안으로, 떼어 낸 helper가 쓰는 문맥은 해제하지 않음, 늦은 복사가 남은 staging은 해제하지 않음, 장치 오류 상태 쓰기에 복사 상한, 거절에서 복사 없는 단계를 먼저, 못 쓴 게이트는 helper 점검이 다시 씀, 펌웨어 감시를 명령 하나 단위로, 쉬는 보내는 스레드도 사용자 단어를 봄(게이트 `test` 칸), 모든 닫기 경로에 BYE와 backlog 비우기, 양보한 장애를 다시 큐에, 응답 쪽 상한 넘김 계수를 범위 검사 뒤로, REQ 직전 펌웨어 확인, 취소 계수는 다시 시도할 때만. 문서로 남긴 것: 값을 반환하지 않는 대기, 연구 빌드의 정리 때 QUERY_QP, 문맥 단위 죽음과 communicator 단위 단어 | [hd_layer.diff](hd_layer.diff) |
| 2026-10-09 | 고친 부분의 2차 리뷰(다른 에이전트, 코드만 읽음): 문제 10건. 반영: 떼어 낸 helper의 collComm을 두 정리 경로 모두에서 기록(`ncclDevCommDestroy` 경로에서 닫히던 문제), 설치 전 연결(다시 걸기, 확인 접속)이 받은 BYE를 떠남으로 처리하고 떠난 상대의 거부는 세지 않음(떠난 상대가 죽음으로 판정되던 문제), 기다림 상한을 "명령 하나가 3 s"로(진행 중인 helper를 떼어 내던 문제), 멈추라는 신호 뒤 새 장애를 잡지 않음, 보내는 스레드용 단어를 4바이트 두 번으로 씀, 거절에서 QP를 ERR로 먼저, 복사 상한을 펌웨어 상한 아래로 고정, 시작 실패 때 늦은 복사를 기다림, 늦은 복사가 남으면 문맥을 통째로 남김, 낡은 주석. 연구 빌드만의 남는 점(정리가 기다리는 훅과 시험 스레드)은 문서로 남김 | 9절 1번 (a)–(c) |
| 2026-10-09 | 다시 빌드(빌드됨, 실행 안 함). `hd` libnccl `e2090323`, `hdp` `4818e30b`(`make -n`의 장치 객체 0), 드라이버 `c0b73e09`(`hd` 헤더), `472602a2`(순정 헤더). 컴파일 경고는 이 계층이 고치지 않은 `scheduler/symmetric_sched.cc` 하나뿐 `[측정]` | 세션 스크래치 `hd_work/build_hd4.log`, `build_hdp2.log`, `build_drv2.log` |
| 2026-10-09 | 운영 빌드 확인: `strings`에서 `NCCL_GIN_TS_TEST`, `GIN_FAULT_INJECT`, `GIN/FAULT`, `GIN_TS_DIAG`, `GIN_RECOVERY_DIAG`, `Q4_QPWATCH`, `Q4_LATE_READ`, `GDAKI_CQ_TYPE`, `GIN/TS: TEST`가 `hdp`에 0개(`hd`에는 각각 16, 4, 11, 1, 2, 1, 1, 3, 23개). 두 빌드 모두 `ncclGinGetRecoveryStats`를 내보냄(`nm -D`) `[측정]` | |
| 2026-10-09 | `make_diff_hd.sh`: 두 재현 확인 VERIFIED. `hd_layer.diff` md5 `2226872e`(10개 파일 +1675/−329), 전체 diff md5 `a9894def` `[측정]` | [make_diff_hd.sh](make_diff_hd.sh) |
| 2026-10-09 | 채점 스크립트 합성 시험: 라이브러리의 printf 형식 문자열로 시행 파일 11개(셀 9개와 지연 2개)를 만들어 `score.py`에 넣음. 3.1의 열이 모두 뽑히고, 해당 판정식의 조건이 시행마다 1/1로 셈. 설정 확인과 제외는 0건(의도대로) `[측정]`. 실제 로그가 아니므로 형식 일치만 보인다 | 세션 스크래치 `hd_work/synth/fab.py` |
| 2026-10-09 | 마지막 hold를 둘로 나눔(H7: 운영 빌드 셀과 장치 시간 제한 셀, H8: 막는 flush 셀). 막는 셀이 감시 상한(110 s)까지 가도 hold 하나가 880 s 안에 들도록 | [hold.sh](hold.sh) |
| 2026-10-09 | 클러스터에서는 아무것도 돌리지 않았다. 배포, pilot, 본 실행은 메인 세션이 한다 | |
| 2026-10-09 | 독립 리뷰(다른 에이전트가 `hd_layer.diff`와 빌드 트리를 읽음, 코드만): 판정 "조건부로 예", 막는 문제 없음. 중간 3건(다시 보내기 검사가 rank마다, 펌웨어 감시가 영구, 취소와 이미 커밋한 응답 쪽의 엇갈림), 낮음 6건. 확인하지 못한 것 3가지(끊긴 쪽 필터가 RST를 버리는지, GPU가 가득 찬 동안 복사 상한, `commFree`가 사용자 커널을 기다리는지)는 pilot에서 본다. pilot H0은 다른 사용자의 잠금 뒤에 대기 중이고, 그 pilot이 읽는 라이브러리와 실행 스크립트는 바꾸지 않았다 | 9절 1번 (g), 11절 |
| 2026-10-09 | 태그 전 변경(리뷰 반영, 메커니즘과 실행 스크립트는 그대로): 8절에 제외 둘(계획을 거부한 rank 0이 그 라운드의 응답 쪽, 펌웨어 감시 셀이 아닌 `hd`와 `hdp` 시행의 펌웨어 초과). `rows_hd.py`에 열 넷(`n_init_round_r*`, `plan_rej_ms_r*`, `plan_rej_init_r0`, `fwdog_phase_r*`). D1의 문장과 근거, H4, 질문 3을 시작 쪽의 거부로 좁힘(D1 판정식은 그대로). `predictions.csv` sha256 앞 12자리 `62fb04a71cd0`. 합성 시행으로 두 제외가 의도대로 걸리고 다른 시행은 그대로 판정되는 것을 확인 `[측정]`(실제 로그 아님) | [score.py](score.py), [rows_hd.py](rows_hd.py), [predictions.csv](predictions.csv), 세션 스크래치 `hd_work/synth/fab.py` |
| 2026-10-09 02:18:27–02:18:57 | 배포(메인 세션, `deploy_hd.sh`, rc 0): 새 디렉터리 `hd/`, `hdp/`, `ow2/`, `stk/`. 두 노드 md5가 소스와 같고(libnccl `e2090323`, `4818e30b`, `b4af65c5`, `b380e622`, 드라이버 `c0b73e09`, `472602a2`), 기존 번들 33개 파일 md5 그대로, 드라이버마다 자기 번들의 libnccl을 씀 `[측정]` | [deploy_check.txt](deploy_check.txt) |
| 2026-10-09 03:24:59–03:31:02 | pilot H0(메인 세션, `chain.sh results/20261009_pilot H0`, 02:19:04에 대기 시작, 다른 사용자의 잠금이 03:15:20까지, 그 뒤 다른 실험 두 hold, rc 0). 25회, 채점 안 함. mlx5 새 줄 0, 명령 오류 줄(rain 2, sunny 0)과 rain 펌웨어 명령 실패 수(31) 전후 같음, iptables 정리 deleted=0 left=0, 끝난 뒤 두 노드에 `gin_ts2` 없음 `[측정]` | `results/20261009_pilot/`(hold_H0.out, chain.out, mlx5_new_H0.txt, 빌드별 시행 파일. 원자료는 Release 예정) |
| 2026-10-09 | pilot 분석(`rows.py`와 네 추출기, `score.py`를 계획 수 1로 돌림, 시행 25회 모두 로그와 대조). 셀마다 1회라 판정이 아니라 조건 확인이다. 예측 조건과 맞음: 거부 1회(거부 1번, 투명), 거부 2회(간격 1 001.3 ms, 바로 거절), 틀린 고유값(재연결 끊김 끝 606.7 ms 뒤, 투명), 라운드 안 리셋(리셋이 첫 분류 기록 2 075.8 ms 뒤, 취소 1, 다시 시도 1로 투명), 받기만 하는 rank(kill 뒤 20.2 ms에 대기 오류 해제, 1.9 ms에 비동기 오류), 느린 펌웨어(감시 3 000 ms, 대기 해제, helper 떼어 냄, abort 912 ms), 멈춘 복사(첫 분류 기록 2 000.8 ms 뒤 거절), 계획 거부(시작 쪽 rank 0, 복구 줄 없음, 두 rank 거절), 상한(셋 복구, 넷째 거절), shrink 셀의 대기 해제(신호 없이 성공한 대기 0), 대조 다섯(gin-oneway: REQ 보내기 실패 거절, 받기만 하는 rank 15 s 대기 상한, 8 s 기다린 뒤 복구, 다섯 모두 복구, shrink 때 옛 커널이 돌고 마지막 abort 뒤 받는 쪽 202회가 신호 없이 성공), 운영 빌드(kill 뒤 1.6 ms 거절, iptables 끊김 뒤 재연결과 투명, WARN에 정보성 줄 없음), IB 타임아웃 20(첫 분류 56.0 s 뒤, 10 ms 한 라운드로 투명. 8 s 시간 제한은 시간 초과만), 회귀 둘. 4 KiB 지연 p50: 운영 10.69, gin-oneway 10.56, 순정 9.76 µs `[측정]`. 어긋난 것: GPU 채우기 셀(두 rank 거절), shrink(두 빌드 모두 `ncclRemoteError`), 계획 거부 셀의 QP 수(4개), 두 번 거부 셀이 "장애 미적용"으로 제외됨 | 세션 스크래치 `hd_work/pilot/`(복사본, `SCORE.md`, `trials_scored.csv`) |
| 2026-10-09 | pilot 확인 넷. (1) 됨: 거부 1회 셀에서 rank 0의 다시 걸기 9번 중 7번째가 rank 1의 수신 대기 닫힘 뒤, rank 0 끊김 끝 약 0.4 s 전에 있었고(시도 수와 500 ms 간격으로 셈, 닫힘 88 ms 뒤) 거부로 기록되지 않았다. 첫 거부는 끊김 끝 93.6 ms 뒤, 두 번 거부 셀은 98.6 ms 뒤 `[측정]` `[추론: 끊긴 쪽 필터가 RST를 버림]`. (2) 안 됨: GPU 채우기 셀에서 두 rank의 4 B 복사가 2 s 안에 끝나지 않고 application GIN 커널이 끝날 때 끝남. 감시가 1 s 뒤 오류를 드러내고 두 rank 거절 `[측정]`. (3) 불분명: 25회 모두 종료 코드 139나 illegal address 없음, 그러나 `hd` 시행 중 abort 때 사용자 커널이 아직 돌던 경우가 없어 그 경로를 지나지 않음(커널이 돌던 1회는 `ow2`) `[측정]`. (4) 펌웨어 초과: 느린 펌웨어 셀 1회(단계 commit, 3 000 ms)뿐, 제외에 해당하는 시행 0 `[측정]` | 9절 1번 (g), 11절 |
| 2026-10-09 | 실행기 `left=1` 원인: 남은 프로세스를 셀 때 원격 명령 `pgrep -f <tag>; rm -f <tag>.pid`를 돌리는 원격 셸의 명령줄 자체에 tag가 들어 있어, `pgrep`이 자기 부모 셸을 셌다(`pgrep`은 자기 자신만 뺀다). 계수 버그이고 실제로 남은 프로세스는 없었다(메인 세션 확인과 일치) `[소스, 측정]` | [run_trial_hd.sh](run_trial_hd.sh) |
| 2026-10-09 | pilot 뒤 변경(태그 전). 실행 스크립트: `left` 계수가 자기 셸에 걸리지 않는 정규식으로(`[g]in_hd_...`), 원격 pid 파일은 정리 단계에서 지움. `hold.sh`와 `chain.sh`에 CUDA 메모리 오류 중단(`STOP_cuda`, pilot 사본에 돌려 0건 확인). 채점: 두 번 거부 셀의 훅 요구 제거. 예측: D1 판정식 `plan_rej_total_r0 == 2`를 `>= 2`로(셀 사실 정정, 3절 머리), C1, A2, P3의 basis에 pilot 의심을 덧붙임(판정식은 그대로). 시각 값은 바꾸지 않음: 거부 1회 셀의 두 번째 다시 걸기는 수신 대기 다시 열림 393 ms 뒤, 두 번 거부 셀의 두 번째 거부는 다시 열림 1 400 ms 전, 라운드 안 리셋은 4 000 ms 창의 2 076 ms, GPU 채우기 훅은 채우기 시작 599 ms 뒤(3 000 ms 창 안) `[측정]`. 고친 채점으로 pilot 사본을 다시 셈: 제외 0, 조건 불일치는 GPU 채우기(C1)와 shrink(A2)뿐. 라이브러리와 번들은 그대로. 확정한 `predictions.csv` sha256 `0e9e3192d74ba9777e78cabbc0b822290e6db07ae83e930d41a066786096b9e0`(52줄) | [score.py](score.py), [predictions.csv](predictions.csv), [hold.sh](hold.sh), [chain.sh](chain.sh), [run_trial_hd.sh](run_trial_hd.sh) |
| 2026-10-09 03:42:57 | 사전 등록 | [PREREG.txt](PREREG.txt), 태그 `prereg/gin-harden-v1` |
| 2026-10-09 03:43:04 | 본 실행 시작(메인 세션, 상태 `RUNNING`): `chain.sh results/20261009 H1 … H8`. hold는 다른 실험의 hold와 번갈아 잠금을 잡았다 | `results/20261009/chain.out` |
| 2026-10-09 03:50:59–06:02:56 | H1–H8. 잠금, 실행 구간(시행 수): H1 03:50:59, 03:51:30–03:56:48(60). H2 04:03:55, 04:04:26–04:11:30(25). H3 04:21:48, 04:22:19–04:29:29(25). H4 04:41:56, 04:42:27–04:52:53(25). H5 05:05:54, 05:06:25–05:13:40(40). H6 05:24:28, 05:24:59–05:31:36(50). H7 05:45:09, 05:45:40–05:48:50(13). H8 05:57:04, 05:57:35–06:02:56(5). 실행 구간 합 52분 21초. 모든 hold rc 0, STOP 파일 없음, hold마다 iptables 정리 `deleted=0 left=0`, 새 mlx5 줄 0, rain 펌웨어 명령 실패 수 31 그대로, 모든 시행 `left=0`, `left_rules=0` `[측정]` | `cluster_run.sh` 기록(태그 `ghd-H1`–`ghd-H8`, 세션 스크래치 `cluster_run.log`), `chain.out`, `hold_H*.out`, `mlx5_new_H*.txt` |
| 2026-10-09 | 제외 4회, 모두 드라이버 랑데부 포트 bind 실패(8절 첫 규칙): `pc_dual_f1c0_r1c2_b@hd` n5(H1, 포트 48340), `hd_fwslow_f1_b@ow` n4(H5, 46209), `hd_shrink_b@hd` n2(H6, 46814), `hd_copystall_f1_b@hd` n2(H6, 46410). 다른 제외와 설정 확인 실패는 0 `[측정]` | [SCORE.md](results/20261009/SCORE.md) 마지막 표, [qa_recount.md](results/20261009/qa_recount.md) 3절, [qa/code_review.md](qa/code_review.md) M1 |
| 2026-10-09 06:10:43–06:11:48 | 채우기 hold `fill:hd:hd_copystall_f1_b@hd:1:11,hd:hd_shrink_b@hd:1:11,hd:pc_dual_f1c0_r1c2_b@hd:1:6,ow:hd_fwslow_f1_b@ow:1:6`: 잠금 06:10:43, 실행 06:11:14–06:11:47, 4회. 셀 키마다 1회(계획의 10–20%, 50% 안). 8절의 채우기이고 `fill:` 방식은 태그 때 이미 `hold.sh`에 있었으므로 사전 등록 뒤 변경이 아니다 | `chain.out`, `hold_fill.out` |
| 2026-10-09 | 채점(`score.py`, 상태 `QA`): 247회, 판정 243회(셀 시행 213, 지연 실행 30). 예측 52줄 중 49 맞음, 3 틀림, 자료 부족 0. 틀린 셋: shrink 넘기기(A2, 0/10), GPU 채우기 셀의 투명 복구(C1, 0/10), 256 KiB 순정 대비 지연(P4, +1.05 µs > 1.00). 예측 파일 sha256이 `PREREG.txt`와 같음 `[측정]` | [SCORE.md](results/20261009/SCORE.md), [trials_scored.csv](results/20261009/trials_scored.csv) |
| 2026-10-09 | 독립 재계산(다른 에이전트, `score.py`와 추출기를 읽지도 돌리지도 않고 원자료에서 다시 셈): 49 맞음, 3 틀림, 0 자료 부족으로 같음. 사전 등록 온전(예측 파일 해시, 2, 3, 7, 8절이 태그와 바이트 단위로 같음, 시행 파일은 03:51:36–06:11:47에 씀), 제외 4회와 채우기 확인, hold 출력과 시행 파일이 줄마다 맞음. 관찰: H8과 채우기 사이(hold 밖) sunny dmesg에 "FWTracer: Events were lost" 한 줄(명령 오류 줄 아님). 운영 빌드가 WARN에서 `NCCL_GIN_TS_PATH_WAIT_MS ... clamped` 줄을 rank마다 한 줄 남김 `[측정]` | [qa_recount.md](results/20261009/qa_recount.md), [qa/recount.py](qa/recount.py) |
| 2026-10-09 | 측정 코드 리뷰(다른 에이전트, 읽기만): 쓸 수 있음, 막는 문제 없음, 태그 뒤 채점에 영향 주는 변경 없음. 높음 1(GPU 채우기 셀에 GPU가 가득 찬 적이 없음), 중간 3(랑데부 포트가 임시 포트 범위 안, shrink가 GIN 오류를 가진 devComm이 등록된 채 불림, 초기화 실패가 제외로 빠질 수 있음), 낮음 8 | [qa/code_review.md](qa/code_review.md), 13절 |
| 2026-10-09 06:23:50 | Release `data-20261009`(메인 세션). 본 실행 `harness__gpu-initiated__gin_recovery__harden__results__20261009.tar.xz`(1 419개 파일, 0.48 MB, sha256 앞 12자리 `1aa4e4028a10`), pilot `harness__gpu-initiated__gin_recovery__harden__results__20261009_pilot.tar.xz`(146개 파일, 0.06 MB, `17c66b513608`, 채점 안 함). 내려받아 `sha256sum -c` 통과, 주소를 바꾼 것 말고는 원본과 같고 실제 주소 접두사 없음 `[측정, 메인 세션]` | Release `data-20261009`, [DATA.md](../../../../DATA.md)(메인 세션이 같은 PR에서 적음) |
| 2026-10-09 | 결과 정리. 15절 범위를 `trials_scored.csv`에서 다시 세어 독립 재계산의 값과 같음을 확인 `[측정]`. 2, 3, 7, 8절은 고치지 않고 정정은 13절에 둠. 상태 `COMPLETE` | 13–19절, [README.md](README.md) |
| 2026-10-09 | 용어: 본문의 "통신기"를 "communicator"로 바꿈(사용자 요청). 고정 절(2, 3, 7, 8절)과 `predictions.csv`, 채점기가 만든 `SCORE.md`는 그대로 둠 | 이 PR |
| 2026-10-09 | 용어: 본문의 "응용"을 "application"으로 바꿈(사용자 요청). 고정 절(2, 3, 7, 8절)과 채점 코드, 채점기가 만든 `SCORE.md`는 그대로 둠 | 이 PR |

## 13. 사전 등록 이후 변경

> 기존 문장을 고치지 않고 여기에 덧붙인다. 고정 절(2, 3, 7, 8절)의 문장 정정도 여기에 둔다. 판정식, 셀, 반복 수, 제외 기준은 하나도 바꾸지 않았다.

| 날짜 | 무엇을 | 이유 | 영향 범위 | 커밋 |
|---|---|---|---|---|
| 2026-10-09 | **GPU 채우기 셀(C1)의 조건 정정.** 3.3의 C1 줄 "GPU 전체를 쓰는 커널이 도는 중에도", 7절 `hd_hog_f1_b` 줄 "모든 SM을 3 s 채우는 커널", 3절 머리의 "복사가 이 GPU에서 빈 SM 자리를 필요로 하는 것으로 보인다 `[추론]`"은 이 셀에서 생긴 일이 아니다. 드라이버는 GIN 커널을 띄운 뒤, 채우기 커널을 띄우기 전에 그 커널의 점유율을 묻고(이때 커널이 지연 적재됨) `cudaMalloc`과 스트림 생성을 했다(`../gin_ts2.cu` 1080–1083행) `[소스]`. 이 순서에서 채우기 커널은 GIN 커널 옆에서 시작하지 않았다: rank 1의 abort가 GIN 커널이 끝난 뒤 3 299.2–3 300.3 ms에 시작했다(채우기 3 000 ms와 끝 기다림 300 ms, n=10. `f1_b`는 353.9–379.3 ms, n=5) `[측정]`. 12절의 "GPU 채우기 훅은 채우기 시작 599 ms 뒤"와 11절 pilot 확인 2의 창도 채우기 커널의 launch 호출부터 잰 값이다. 다른 실험 gin-handoff에서 같은 순서는 시작한 채우기 블록 0, 새 스트림의 4 B 복사 200 ms 안 완료 0/8이었고, 세 호출을 GIN 커널 전에 하면 블록 191/192, 287/288, 복사 8/8, 투명 복구 5/5였다 `[측정, 다른 실험, 그 실험의 QA 전]` | 코드 리뷰 H1 | C1의 판정(틀림, 0/10)은 고정 규칙대로 그대로다. 이 셀이 잰 것은 "application이 GIN 커널이 도는 중에 커널 적재와 할당을 한 뒤의 복구"다. H3의 "GPU가 가득 찬 정상 복구" 조항은 이 실행으로 시험되지 않았다. 9절 3번, 9절 1번 (g), 11절에는 정정 표시를 달았다 | 이 정리 커밋 |
| 2026-10-09 | **shrink 넘기기(A2)의 원인 문장을 좁힘.** 3절 머리, 9절 1번 (g)의 "순정 NCCL은 GIN 비동기 오류가 있는 communicator의 shrink를 막는다"는 "그 GIN 오류를 가진 devComm이 아직 등록된 동안"으로 좁혀야 한다. 드라이버는 그 devComm을 없애지 않고 `ncclCommShrink(NCCL_SHRINK_ABORT)`를 불렀다(`../gin_ts2.cu` 1117–1131행) `[소스]`. gin-handoff의 대조(같은 드라이버, devComm을 먼저 없앰, 그 실험의 계층은 끔)에서는 shrink, 1-rank communicator, allreduce 확인이 5/5 됐다 `[측정, 다른 실험, 그 실험의 QA 전]` | 코드 리뷰 M2 | A2의 판정(틀림, 0/10)은 고정 셀(이 호출 순서 포함)대로 그대로다. A1, A3, A4는 영향 없음. 결론(17절)은 좁힌 문장을 쓴다 | 이 정리 커밋 |
| 2026-10-09 | **받기만 하는 rank의 "15 s 대기 상한" 정정.** 3.3 B10 줄과 7절 `hd_rxdeath_b` 줄의 15 s는 sunny에서 약 12.4 s였다: 장치 대기 상한은 `cudaDevAttrClockRate` 기준 cycle 수로 세는데 sunny에서는 약 17% 일찍 끝난다. 대조의 대기는 kill 뒤 12 351.4–12 458.6 ms에 끝났다(n=5) `[측정]` | 코드 리뷰 L6 | B10의 기준(kill 뒤 10 000 ms 이상)은 충족, 판정 그대로 | 이 정리 커밋 |
| 2026-10-09 | **운영 빌드의 WARN 줄(P7) 문장이 판정식보다 넓음.** 판정식은 "transparent recovery ON" 시작 줄만 센다. 운영 빌드도 WARN에서 `NCCL_GIN_TS_PATH_WAIT_MS=30000 exceeds ... clamped to 21000 ms` 줄을 rank마다 시행마다 한 줄 남긴다. 이 줄은 이 계층보다 오래됐고 `ow`, `hd`에도 있다 `[측정]` | 코드 리뷰 L2, 독립 재계산 6절 | P7 판정(맞음)은 그대로. "정보성 복구 줄을 남기지 않는다"는 이 줄을 빼고 읽는다 | 이 정리 커밋 |
| 2026-10-09 | **3.1의 `fault_after_launch_r0_ms` 정의.** "rank 0 훅 발사 − 커널 시작"의 기준은 실제로 kv `launch_mono_ms`(launch 직전 호스트 시각)다 `[소스]` | 코드 리뷰 nit | 판정 영향 없음 | 이 정리 커밋 |
| 2026-10-09 | **기록만(변경 아님).** bind 실패 4회의 제외와 채우기 hold는 8절 규칙 그대로다. 원인은 랑데부 포트 46000–48999가 rain의 임시 포트 범위(32768–60999) 안이라는 것이다 `[측정, 추론]`. 재계산이 짚은 두 모호성(`n_fwdog_r*`가 감시 줄 하나를 세는지 둘을 세는지, A4의 `or` 가지가 빈 값에도 참이 됨)은 이 자료에서 판정을 바꾸지 않는다 | 코드 리뷰 M1, L1, 독립 재계산 1절 | 없음 | 이 정리 커밋 |

## 14. 원자료와 결과표

| 무엇 | 경로 |
|---|---|
| 채점표 | [results/20261009/SCORE.md](results/20261009/SCORE.md) |
| 시행별 값(243회 판정, 247회 전체) | [results/20261009/trials_scored.csv](results/20261009/trials_scored.csv) |
| 독립 재계산 보고와 스크립트 | [results/20261009/qa_recount.md](results/20261009/qa_recount.md), [qa/recount.py](qa/recount.py) |
| 측정 코드 리뷰 | [qa/code_review.md](qa/code_review.md) |
| 사전 등록 | [PREREG.txt](PREREG.txt), [predictions.csv](predictions.csv), 태그 `prereg/gin-harden-v1`(`692ff591`) |
| 원자료(시행별 로그, kv, hold 출력, 스냅숏) | Release `data-20261009`: 본 실행 `harness__gpu-initiated__gin_recovery__harden__results__20261009.tar.xz`(sha256 앞 12자리 `1aa4e4028a10`), pilot `..._20261009_pilot.tar.xz`(`17c66b513608`, 채점 안 함). [DATA.md](../../../../DATA.md) |
| 배포 확인 | [deploy_check.txt](deploy_check.txt) |

## 15. 결과 요약

**판정.** 예측 52줄 중 49 맞음, 3 틀림, 자료 부족 0. 판정한 시행은 243회(셀 시행 213, 지연 실행 30)이고 bind 실패 4회를 빼고 채웠다
`[측정]`([SCORE.md](results/20261009/SCORE.md), 독립 재계산도 같음).

| 묶음 | 맞음/전체 | 틀림 |
|---|--:|---|
| 사용자 devComm의 abort 단어와 shrink 넘기기(A) | 4/5 | shrink(A2) |
| 생존 판정(B) | 11/11 | |
| 상한(C) | 6/7 | GPU 채우기 셀(C1) |
| 다시 보내기 계획 검사(D) | 2/2 | |
| 상한 넘김과 통계(E) | 5/5 | |
| 회귀(R) | 12/12 | |
| 운영 빌드(P) | 6/7 | 256 KiB 순정 대비 지연(P4) |
| IB 타임아웃 20(T) | 3/3 | |

**핵심 수치.** 범위는 따로 적지 않으면 그 셀 키의 판정한 시행 전체에 걸친 최소–최대이고 시행마다 값 하나다. 지연은 실행마다 p50 하나, 다섯
실행의 중앙값이다. 모두 `[측정]`이고, 채점 경로(`trials_scored.csv`)와 독립 재계산에서 같은 값이다.

| 조건 | 이 빌드(`hd`, `hdp`) | 대조(gin-oneway `ow`, `ow2`) | n(이 빌드, 대조) |
|---|---|---|--:|
| 상대 kill 뒤 거절(rank 0 시계, kill부터) | 1.44–1.75 ms(`f4_b`), 1.51–1.60 ms(운영 빌드), 1.49–1.65 ms(shrink 셀) | | 5, 5, 10 |
| 받기만 하는 rank, 보내는 rank kill 뒤 | 대기가 20.3–21.7 ms에 오류로 풀림, 비동기 오류 1.8–2.1 ms | 자기 대기 상한까지 기다림, 12.35–12.46 s에 시간 초과 | 10, 5 |
| shrink 셀, 상대 kill 뒤 대기 | shrink 전에 오류로 풀림, 신호 없이 성공한 대기 0 | shrink 때 커널이 아직 돎, 마지막 abort 뒤 201–204회가 신호 없이 성공 | 10, 5 |
| `NCCL_SHRINK_ABORT` shrink | 0.0 ms에 `ncclRemoteError`, 새 communicator 없음 | 같음 | 10, 5 |
| 원격 접근 오류, 받는 쪽 | 상대 거절 때 대기가 오류로 풀림, abort 769.1–777.4 ms | | 5 |
| 거부 한 번(수신 대기 1.2 s 닫힘) | 거부 1번, 죽음 판정 없음, 끊김 끝 1 081.5–1 107.8 ms 뒤 재연결, 투명 | | 10 |
| 거부 두 번 | 1 001.1–1 002.2 ms 간격의 거부 둘 뒤 죽음, 2.25–2.35 ms 뒤 거절 | | 10 |
| 끊김 중 kill(rank 1, rank 0) | 거부 간격 1 001.2–1 001.7 ms, 1 001.2–1 002.2 ms 뒤 죽음, ECONNREFUSED로 거절 | | 5, 5 |
| 틀린 고유값 HELLO | 거부됨, 받아들여지지 않음, 끊김 끝 578.0–607.3 ms 뒤 재연결, 투명 | | 10 |
| 라운드 안 리셋(첫 분류 뒤 2 074.6–2 120.2 ms) | 취소 1, 다시 돈 한 라운드로 투명(라운드 5 512–5 514 ms) | REQ 보내기 실패로 거절 | 10, 5 |
| 양쪽 8 s 끊김, 한쪽 끊김 둘 | 끊김 끝 81.2–106.5 ms, 91.1–129.4 ms, 85.5–96.1 ms 뒤 재연결, 투명 | | 5, 5, 5 |
| 펌웨어 단계 8 s | 3 000 ms에 감시, 첫 분류 뒤 3 007.2–3 008.0 ms에 대기 오류 해제, helper 떼어 냄, rank 0 abort 510.6–950.3 ms | 8.012–8.013 s 기다린 뒤 복구 | 10, 5 |
| 멈춘 복사 4 s | 첫 분류 뒤 2 000.7–2 001.5 ms에 거절, rank 0 abort 1 721.1–1 722.3 ms | | 10 |
| GPU 채우기 셀(13절: 실제로는 GIN 커널 뒤 할당과 커널 적재) | 두 rank의 4 B 복사가 자기 커널 launch 뒤 2 062.5–2 066.2 ms에 복사 상한 초과, 두 rank 거절, 투명 0/10 | | 10 |
| 다시 보내기 계획 거부 | 시작 쪽 rank 0이 4개 중 둘째에서 거부, 복구 줄 0, 두 rank 거절 | | 10 |
| 다섯 장애, 상한 10 s에 3번 | 셋 복구 뒤 넷째에서 상한 넘김 거절(다섯째 훅은 오지 않음) | 다섯 모두 복구 | 10, 5 |
| 통계 API | 시행마다 예측한 계수와 같음(복구 1, 죽음 1, 취소 1, 펌웨어 초과 1, 복사 초과 1 등) | `ow2`, `stk`는 `rs_api=0`(API 없음) | 셀마다 5–10 |
| 운영 빌드, iptables 8 s 관리망 끊김 | 규칙 2개가 launch 뒤 2 050.5–2 086.7 ms에 걸려 8 056.0–8 056.7 ms 유지, rank마다 재연결 1, 투명, 남은 규칙 0 | | 5 |
| IB 타임아웃 20, 상대 QP 오류, 막는 flush | 첫 분류(RETRY_EXC)가 장애 56.36–59.29 s 뒤, 10.0–10.4 ms 한 라운드로 투명 | | 5 |
| IB 타임아웃 20, 장치 쪽 8 s 시간 제한 | 시간 초과만, 복구와 거절 없음 | | 3 |
| 회귀 12셀 | 판정 모두 그대로(복구 재현 셀 투명, pair-check, 끊김과 kill 셀) | gin-oneway 판정과 같음 | 60 |

| 장애 없는 지연 p50(다섯 실행 중앙값) | 운영 `hdp` | gin-oneway `ow` | 순정 `stk` | `hdp` − `ow` | `hdp` − `stk` |
|---|--:|--:|--:|--:|--:|
| 4 KiB | 10.72 µs | 10.59 µs | 9.76 µs | +0.13 µs | +0.96 µs |
| 256 KiB | 38.91 µs | 38.91 µs | 37.86 µs | 0.00 µs | +1.05 µs |

**틀린 셋.**
- **shrink 넘기기(A2).** 0/10. shrink가 0.0 ms에 `remote process exited or there was a network error`를 돌려주고 새 communicator가 없었다. pilot과
  사전 등록 문서(3절 머리)가 예상한 실패다. 원인은 13절: 그 GIN 오류를 가진 devComm이 등록된 채 shrink를 불렀기 때문이다 `[소스, 다른 실험 측정]`.
- **GPU 채우기 셀의 투명 복구(C1).** 0/10. 셀의 판정 조건(채우기 커널 launch 성공, 훅이 그 창 안)은 10/10 섰지만, 채우기 커널은 GIN 커널 옆에서
  돈 적이 없다(13절). 두 rank의 쉬는 중 게이트 점검 복사가 GIN 커널이 끝날 때까지 끝나지 않아 복사 상한(2 s)에 걸렸고, rank 0은 분류기 감시가
  먼저 오류를 드러낸 탓에, rank 1은 상대 거절로 거절했다 `[측정]`.
- **256 KiB 순정 대비 지연(P4).** +1.05 µs(원자료 1.056 µs)로 범위(0.10–1.00 µs) 위다. 256 KiB에서 운영 빌드는 gin-oneway와 같다(둘 다 38.91 µs).
  예상하지 못한 실패다. 4 KiB(P3)는 +0.96 µs로 범위 안이지만 위쪽 끝 근처다(pilot 0.93 µs).

## 16. QA와 재현성

- **사전 등록.** 예측 파일 sha256 `0e9e3192…`가 작업 트리, 태그, `PREREG.txt`에서 같다. 2, 3, 7, 8절은 태그와 바이트 단위로 같다(이 정리 커밋
  뒤에도. 정정은 13절). 본 실행 시행 파일은 태그(03:42:57) 뒤인 03:51:36–06:11:47에 써졌다. `cells.sh`, `chain.sh`는 태그와 같고
  `run_trial_hd.sh`, `hold.sh`는 저장소 주소 필터가 바꾸는 한 줄만 다르다 `[측정]`([qa_recount.md](results/20261009/qa_recount.md) 2절).
- **독립 재계산.** 다른 에이전트가 채점 코드를 읽지도 돌리지도 않고 원자료에서 열과 판정식을 다시 구현해 49, 3, 0으로 같은 판정을 냈다.
  hold 출력 247줄과 시행 파일 247개가 하나씩 맞았다. 이 문서의 15절 범위는 `trials_scored.csv`에서 다시 세어 재계산의 값과 같음을 확인했다.
- **코드 리뷰.** 측정 코드(드라이버, 실행기, 채점)는 "쓸 수 있음, 막는 문제 없음"이다([qa/code_review.md](qa/code_review.md)). 해석을 좁힌
  것(H1, M2)은 13절에, 고칠 것은 19절에 있다. 라이브러리 계층은 설계 단계 리뷰 두 번과 독립 리뷰를 거쳤다(9절 1번 (g), 12절).
- **안전.** 모든 hold가 880 s 안(33–625 s), rc 0, STOP 파일 없음, iptables 남은 규칙 0, 종료 코드 139나 CUDA illegal address 없음, 남은 프로세스
  0, 새 mlx5 명령 오류 0 `[측정]`. hold 밖의 sunny "FWTracer: Events were lost" 한 줄은 명령 오류 줄이 아니다.
- **재현.** [gin_transparent_hd.diff](gin_transparent_hd.diff)(pristine NCCL v2.32.3-1 기준)로 만든다. `hdp`는 같은 소스에
  `-DNCCL_GIN_TS_PRODUCTION`. 빌드 절차는 [build_hd.sh](build_hd.sh), 배포된 파일의 md5는 5절과 [deploy_check.txt](deploy_check.txt).

## 17. 결론

비판적 리뷰가 짚은 항목마다 이 실행이 보인 것이다. "됨"은 사전 등록한 예측이 맞았다는 뜻이다.

- **사용자 대기가 성공 대신 오류로 풀린다(1a): 됨.** 상대의 죽음, 거절, 펌웨어 감시, abort가 사용자 devComm의 따로 둔 단어를 올리고, 풀린 대기는
  오류를 돌려줬다. 신호 없이 성공한 대기는 0이었고, 같은 조건의 이전 빌드는 마지막 abort 뒤 약 200회를 신호 없이 성공으로 돌려줬다. 값을
  돌려주지 않는 대기(void 판, 배리어, proxy 경로)는 재지 않았고 여전히 조용히 끝난다 `[소스]`.
- **생존 판정(1b): 됨.** 거부 한 번은 죽음이 아니고, 1 s 이상 떨어진 거부 두 번은 죽음이다. 틀린 고유값의 연결은 받아들이지 않고 죽음으로도
  세지 않는다. 라운드 안의 리셋은 라운드를 취소하고 다시 돌아 투명하게 복구한다. 받기만 하는 rank도 보내는 쪽의 죽음을 kill 뒤 20.3–21.7 ms에 오류로
  받는다. 이전 빌드는 같은 조건에서 자기 대기 상한(약 12.4 s)까지 기다렸다.
- **상한(1c): 됨, 한 경우 빼고.** 멈춘 복사는 2 s에 거절되고, 3 s를 넘는 펌웨어 단계는 감시가 대기를 풀며, 그 단계 안에 helper가 갇혀 있어도
  abort가 1 s 안에 돌아온다. application이 GIN 커널을 돌리는 중에 할당과 커널 적재를 하면 helper의 복사가 그 커널이 끝날 때까지 끝나지 않아, 장애가
  투명하게 복구되지 않고 2 s 상한에서 거절된다 `[측정]`. 멈추지는 않지만 투명 복구는 깨진다. GPU가 가득 찬 동안의 복구는 이 실행에서 시험되지
  않았다(13절). 다른 실험(gin-handoff)은 그 호출을 GIN 커널 전에 하면 GPU를 거의 다 채워도 투명함을 보였다 `[측정, 다른 실험, QA 전]`.
- **다시 보내기 계획 검사(1d): 됨, rank 단위로.** 시작 쪽이 계획 하나를 거부하면 어느 rank도 다시 보내지 않았다. 응답 쪽은 DONE 뒤에 검사하므로
  라운드 전체의 보장은 아니다 `[소스]`.
- **문맥마다의 고유값(1e): 됨.** 프로세스 전체 계수기 대신 문맥마다의 고유값을 싣고, 틀린 값을 거부했다.
- **운영 스위치(2a): 됨, 지연 하나 빼고.** 운영 빌드에는 시험 스위치와 장애 훅 문자열이 없고, 훅 없는 kill과 실제 iptables 관리망 끊김을 바르게
  다뤘다. 지연은 gin-oneway와 같거나 0.13 µs 차이이고, 순정 NCCL보다 4 KiB 0.96 µs, 256 KiB 1.05 µs 느리다. 256 KiB는 예측 범위(1.00 µs)를
  넘었다.
- **통계 API(2b): 됨.** 라운드, 복구, 거절, 죽음, 재연결, 취소, 펌웨어 초과, 복사 초과가 시행마다 맞게 셌다.
- **상한 넘김(2c): 됨.** 10 s에 3번을 넘는 넷째 장애를 상한을 적은 사유로 거절하고 복구를 멈췄다. 이전 빌드는 다섯 번 모두 복구했다.
- **shrink 넘기기(3): 절반.** 죽은 상대 때문에 풀린 대기는 shrink 전에 오류로 끝났다. 그러나 shrink 자체는 10번 모두 실패했다: 순정 NCCL은
  GIN 오류를 가진 devComm이 등록된 동안 shrink를 거부한다. devComm을 먼저 없애는 순서는 다른 실험(gin-handoff)에서 됐다.
- **기본 IB 타임아웃(4): 소스에서 한 예측대로.** 상대 QP 오류는 약 56–59 s 뒤에야 분류되고, 막는 flush는 그동안 기다린 뒤 10 ms 한 라운드로
  투명하게 복구됐다. 장치 쪽 시간 제한(8 s)이 그보다 짧으면 시간 초과만 남고 복구도 거절도 시작되지 않는다. 투명 복구를 쓰려면 장치 쪽 시간
  제한을 IB 재시도 시간보다 길게 둬야 한다 `[추론]`.
- **바뀌지 않아야 할 것: 그대로.** 앞 실험들의 회귀 셀 12개(60회)가 모두 같은 판정이었다.

## 18. 한계

- 2 rank, 노드 한 쌍, Turing과 Ampere GPU, ConnectX-6에서만 쟀다. 실제 링크 장애는 만들지 않았다(4절).
- GPU가 가득 찬 동안의 복구는 시험되지 않았다. GPU 채우기 셀은 application이 GIN 커널 뒤에 할당과 커널 적재를 하는 경우를 쟀다(13절).
- 사용자 devComm 단어가 communicator마다 하나라, 상대 하나에 대한 거절이 건강한 상대와의 대기까지 오류로 끝낸다. 2 rank에서는 드러나지 않는다.
- 값을 돌려주지 않는 대기, 배리어, proxy 경로는 풀려도 오류를 돌려줄 수 없다(재지 않음).
- 펌웨어 감시는 한 번 발동하면 그 문맥에 영구적이고, 다시 보내기 계획 검사는 rank 단위다(9절 1번 (g)).
- 운영 빌드도 WARN에서 오래된 설정 경고 한 줄을 남긴다. 순정 NCCL 대비 지연은 약 1 µs다.
- 드라이버의 장치 대기 상한은 sunny에서 약 17% 짧게 끝난다. 랑데부 포트와 helper 포트가 임시 포트 범위 안이라 bind 실패 4회가 있었다(판정 영향
  없음).
- shrink가 성공하는 경로(1-rank allreduce 확인)는 한 번도 돌지 않았다.
- 연구 빌드에는 시험 스위치가 있다. 운영 빌드는 시험 스위치 없이 kill과 관리망 끊김만 쟀다.

## 19. 다음 작업

- **라이브러리 계층.**
  - 응답 쪽도 Commit과 ACK 전에 시작 쪽의 실행 수(`req.executed`)로 계획 검사 첫 단계를 돌리고, 거부하면 NACK한다(9절 1번 (g) 첫 줄).
  - 펌웨어 감시가 발동한 문맥을 다시 쓸 수 있게 하거나, 판정을 문맥 단위로 좁힌다(둘째 줄).
  - 거절한 상대가 거부한 HELLO나 PROBE에 FAIL이나 BYE로 답해, 다시 시도가 재연결 기다림을 다 쓰지 않게 한다(셋째 줄).
  - 약 5 s 지난 거부는 잊는다. 상한 넘김에서 다시 시도와 범위 재실행을 빼고, 취소 계수를 두 역할에서 같게 센다.
  - 사용자 devComm 단어를 communicator 하나가 아니라 상대나 문맥 단위로: 한 상대의 거절이나 죽음이 살아 있는 상대와의 통신까지 끝내지 않게
    (gin-multirank가 랭크 4개에서 이 문제를 쟀다).
  - helper의 장치 상태 복사가 application의 CUDA 호출에 막히지 않는 경로(예: 호스트에 매핑된 게이트를 CPU가 직접 읽고 쓰기). 그 전까지는 application이 할당과
    커널 적재를 GIN 커널을 띄우기 전에 마치도록 문서에 적는다.
  - shrink 넘기기: 오류를 가진 devComm을 먼저 없애는 순서를 application 쪽 절차로 정하거나, 라이브러리가 그 순서를 대신한다(gin-handoff).
- **측정 코드.**
  - 랑데부 포트와 helper 포트를 32768 아래로(코드 리뷰 M1, L5).
  - GPU 채우기 셀: 세 호출을 GIN 커널 전에 하고, 시작한 블록 수를 셀 조건 열로(H1. gin-handoff가 이 방식으로 다시 쟀다).
  - 초기화 실패를 따로 세고 블록을 멈추는 상태(M3), `mute_applied`를 규칙 2개 확인으로(L3), 글로만 있는 중단 규칙을 코드로(L4), shrink 성공
    경로의 할당을 미리(L7).
- 3 rank 이상(gin-multirank), 실제로 멈춘 펌웨어 명령에서 떼어 낸 helper가 남기는 자원의 정리.

## 20. 참고자료

- `../oneway/EXPERIMENT.md`, `../oneway/qa/code_review.md`(gin-oneway, 기준 빌드 `ow`)
- `../s2_close/qa/code_review.md` R1, R2(사용자 devComm의 abort 단어)
- `../reconnect/EXPERIMENT.md`, `../pair_check/EXPERIMENT.md`(회귀 셀)
- `../s2_close/EXPERIMENT.md` 3.2절(판정식 문법)
- `../../../ack_timeout/README.md`(IB 타임아웃과 재시도 시간)
- gin-handoff(브랜치 `exp/gin-handoff`, `handoff/`): GPU 채우기 호출 순서와 devComm을 먼저 없애는 shrink의 대조. 이 문서가 인용한 값은 코드
  리뷰가 그 원자료에서 다시 센 것이고, 그 실험은 QA 전이다.
- gin-multirank(브랜치 `exp/gin-multirank`, `multirank/`): 랭크 4개에서 communicator 단위 abort 단어의 영향
