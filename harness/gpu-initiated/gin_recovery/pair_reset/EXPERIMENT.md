# GIN 투명 복구: 장애 난 QP 쌍만 재설정 (gin-pair-reset)

**목적:** GIN 투명 복구의 라운드를 장애 난 GIN 문맥의 QP 쌍으로 좁힌다. 그 쌍이 투명하게 복구되는지, 같은 상대의 다른 문맥
트래픽이 재설정도 멈춤도 없이 계속되는지, Commit 시간이 줄어드는지, 좁힐 수 없을 때 전체 재설정으로 돌아가는지를 사전 등록한
예측으로 잰다.

| 항목 | 값 |
|---|---|
| 상태 | `PREREGISTERED` |
| 담당자 | @unionxic |
| 작성일 | 2026-10-08 |
| 기준 브랜치와 커밋 | `exp/gin-pair-reset` @ `175aaba4` (`exp/gin-reconnect`. gin-reconnect가 master에 합쳐지면 그 위로 rebase한다) |
| 사전 등록 태그 | `prereg/gin-pair-reset-v1` (상태를 `PREREGISTERED`로 바꾼 바로 그 커밋) |
| 마지막 갱신 | 2026-10-08 12:08, 사전 등록 |

표시: `[측정]` 원자료에서 확인, `[소스]` 코드에서 읽음, `[추론]` 해석, `[미확인]` 확인 안 함.

이 문서의 소스 줄 번호는 gin-reconnect 라이브러리 트리 기준이다. 그 트리는 pristine NCCL v2.32.3-1에
`../reconnect/gin_transparent_rc.diff`(md5 `411919a4`)를 적용한 것과 같다(세션 스크래치 `agent_ts2rc/nccl-src`,
`gin_host_gdaki.cc` md5 `2b4f666a`, libnccl `8354411f`).

**용어.**
- GIN 문맥: 사용자 devComm의 GDAKI 문맥 하나 안에 GIN 문맥이 여러 개 있고, 문맥마다 상대 rank 하나에 QP가 하나씩 있다.
  장치 코드의 `ncclGin gin{devComm, ctx}`가 고르는 번호다.
- QP 쌍: 두 rank의 같은 문맥 QP 둘(서로 연결된 RC QP).
- 범위: 한 복구 라운드가 다루는 문맥의 비트 마스크. 문맥 0만이면 `0x1`, 문맥 4개 전부면 `0xf`.
- 전체 재설정: 지금의 라운드. 상대로 가는 모든 문맥의 QP를 멈추고 재설정한다.

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
| gin-reconnect 라이브러리 | `rc` | libnccl `8354411f`와 최종 2단계 드라이버 `d4b1f082`(`$HOME/gi-bundle/gin_ts2/rc/`). 같은 hold의 지연 기준으로만 쓴다 |
| 이 실험의 라이브러리 | `pr` | `rc` 위에 9절의 범위 변경을 더한 libnccl과 같은 드라이버 `d4b1f082`(`$HOME/gi-bundle/gin_ts2/pr/`, 새 디렉터리) |
| 이 실험의 라이브러리와 두 문맥 드라이버 | `prd` | `pr`과 같은 libnccl, 9절의 두 문맥 모드를 더한 드라이버(`$HOME/gi-bundle/gin_ts2/prd/`, 새 디렉터리) |

## 1. 배경과 연구 질문

**지금의 동작** `[소스]`(`transport/net_ib/gdaki/gin_host_gdaki.cc`).
- 사용자 devComm의 GDAKI 문맥에는 GIN 문맥이 4개 있고, 문맥마다 상대 하나에 QP 하나가 있다. gin-reconnect 원자료의
  "recovery ON" 줄 180개가 모두 `peer_qps=4 contexts=4`다 `[측정]`.
- 복구 라운드의 단계는 모두 `gdakiRecForPeer`(1230–1238행)로 상대의 모든 문맥 QP를 돈다.
  - 게시 멈춤(2618–2700행). 2637행에서 그 QP 전부를 ERR로 보낸다.
  - Prepare(1526–1708행), 실행 수(2559–2575행), Commit(1712–1904행), 응답 MSN 기준선(2578–2592행).
  - 재게시와 게이트 공개(2729–2990행).
- REQ와 ACK가 싣는 토큰과 실행 수 배열도 같은 순서의 전체 목록이다(2009–2022행).
- 장치 코드는 이미 QP별이다.
  - 게시와 대기는 자기 QP의 게이트 단어만 본다(`gin_gdaki.h` 280–284행).
  - 오류 플래그는 GIN 문맥별이다(`gin_gdaki_device_host_common.h` 212행).
  - 장치 쪽 분류 기록은 문맥 번호를 싣는다(`gin_gdaki.h` 828행). 장치 문맥 c의 상대 p QP는 호스트의 `gqps[c * nranks + p]`다
    (4474–4486행). 호스트가 쓰는 번호와 같다.
- 기존 장애 훅은 그 rank의 모든 문맥 QP를 ERR로 보낸다(648–679행). 그래서 지금 셀은 한 문맥만 고장 난 경우를 만들지 못한다.
- 기존 드라이버의 단방향 모드는 문맥 0만 쓴다. 양방향 모드는 방향마다 보내는 rank의 번호를 문맥으로 쓴다(`../gin_ts2.cu`
  717–720행).

**비용** `[측정, gin-reconnect 원자료에서 다시 셈]`. 근거는 `../reconnect/results/20261008/rep_rc/`, `mute/`의 rank 로그(Release
예정)다. 아래 범위는 `rc` 빌드에서 2026-10-08에 복구된 라운드 전부의 범위다.
- 복구 줄 110개(시작 쪽 55, 응답 쪽 55, 셀 9개)가 모두 `qps=4`다.
- 시작 쪽 Commit은 3 191–3 472 µs다(55라운드, 중앙값 3 344 µs). 응답 쪽 Commit은 3 597–3 906 µs다(55라운드).
- 시작 쪽 라운드 전체(게시 멈춤부터 재게시까지)는 8 363–13 515 µs다. 재연결 기다림이 라운드 시각에 들어가는 셀
  (`rc_mutef3s_b`) 10라운드를 뺀 45라운드, 중앙값 10 399 µs다.
- 범위 검토 메모(세션 스크래치, 저장소 밖)는 문맥 하나로 좁히면 Commit 3.3 ms가 약 반이 된다고 봤다 `[추론]`.

**비어 있는 것.** 한 문맥만 고장 났을 때 같은 상대의 다른 문맥 트래픽이 라운드 동안 어떻게 되는지는 잰 적이 없다 `[미확인]`.
소스로 보면 지금은 다른 문맥 QP도 게이트가 닫히고 ERR이 됐다가 다시 게시된다.

**질문.**
1. 라운드를 장애 난 문맥의 QP 쌍으로 좁히면 로컬 QP 오류와 상대 QP 오류가 투명하게 복구되는가.
2. 같은 상대의 다른 문맥 QP 쌍은 재설정되지 않고, 그 트래픽은 1 ms 넘게 멈추지 않는가.
3. 시작 쪽 Commit은 같은 hold의 전체 재설정의 절반 이하가 되는가. 라운드 전체는 0.6 이하가 되는가.
4. 좁힐 수 없을 때 전체 재설정으로 돌아가 복구되는가. 좁힐 수 없는 경우는 다음과 같다.
   - 스위치를 껐다.
   - 이 rank에서 같은 상대로 가는 다른 문맥 QP가 RTS가 아니다.
   - 다른 문맥의 장애 기록이 대기 중이다.
   - 두 rank가 서로 다른 범위로 동시에 라운드를 시작했다.
5. 기존 복구 셀, 거절 셀, 장애 없는 지연은 그대로인가.

## 2. 가설

| id | 가설 | 다음이 관측되면 틀린 것이다 |
|---|---|---|
| H1 | 장애 난 문맥의 QP 쌍만 재설정해도 투명하게 복구된다 | 문맥 0만 고장 낸 두 셀(로컬 QP 오류, 상대 QP 오류) 중 하나라도 투명 복구가 9/10 미만이다. 또는 두 rank 모두에서 라운드가 문맥 0으로 좁혀진 시행이 9/10 미만이다 |
| H2 | 같은 상대의 다른 문맥 QP 쌍은 재설정되지 않고 그 트래픽은 멈추지 않는다 | 그 두 셀에서 문맥 1 QP의 게이트가 닫히거나 새로 공개된 시행이 2회 이상이다. 또는 문맥 0이 묶인 동안 문맥 1의 반복이 하나도 끝나지 않았거나 1 ms를 넘은 시행이 2회 이상이다. 전체 재설정 대조에서 문맥 1이 묶이지 않으면(1 ms 이상인 반복이 4/5 미만) 이 측정은 민감하지 않은 것이므로 가설을 판정하지 않는다 |
| H3 | 시작 쪽 Commit은 절반 이하, 라운드 전체는 0.6 이하가 된다 | 같은 hold의 중앙값 비가 그보다 크다 |
| H4 | 좁힐 수 없으면 전체 재설정으로 돌아가고 투명 복구는 그대로다 | 대체 셀 두 개(모든 문맥 고장, 범위 충돌) 중 하나라도 투명 복구가 9/10 미만이다. 또는 대체가 일어나지 않은 시행이 2회 이상이다 |
| H5 | 기존 동작과 빠른 경로는 그대로다 | 재현 셀의 결과가 바뀐다. 또는 지연 차이가 예측 범위 밖이다 |

## 3. 사전 예측 (측정 전에 작성)

예측 원문은 [predictions.csv](predictions.csv)이고, 해시는 [PREREG.txt](PREREG.txt)에 있다. 23줄이다.
`kind`는 N(새 셀), R(재현), C(대조)다. 아래 판정 열, 로그 형식, 셀 키, 판정식 문법은 지금 고정한다.

### 3.1 판정에 쓰는 열

시행마다 한 줄이다. 열은 세 곳에서 온다.
- `../scripts/ts2/rows.py`의 열.
- gin-s2-close의 `../s2_close/rows_extra.py`가 붙이는 열. 정의는 `../s2_close/EXPERIMENT.md` 3.1절 그대로다.
- 이 폴더의 `rows_pr.py`가 붙이는 새 열.

**앞의 두 곳에서 쓰는 열.** 의미는 원래 정의 그대로다 `[소스]`.

| 열 | 내용 |
|---|---|
| `cell`, `build`, `iters` | 셀 이름, 빌드, 반복 수 |
| `transparent_ok` | 1 또는 0. 두 문맥 모드에서는 두 문맥을 합친 kv 키(9절)로 같은 정의를 적용한다 |
| `r0rc`, `r1rc`, `r0_outcome`, `r1_outcome` | rank별 종료 코드와 드라이버 결과 |
| `decl_r0`, `decl_r1` | rank별 거절 사유. 여럿이면 `;`로 잇는다 |
| `teardown_r0`, `teardown_r1`, `teardown_ms_r1` | `ncclCommAbort` 반환 문자열(성공은 `no error`)과 걸린 시간 |
| `lat_p50_us` | 지연 p50 |
| `q4_class_r0` | rank 0 장치 쪽 분류 기록의 분류 이름. 처음 4개를 `;`로 잇는다 |
| `rec_init_r0`, `rec_init_r1`, `rec_resp_r0`, `rec_resp_r1` | rank별 복구 줄 수(시작 쪽, 응답 쪽) |
| `n_fires_r0`, `n_fires_r1`, `trigger_miss`, `bind_fail`, `ts_on_r0`, `ts_on_r1` | 장애 훅 발사 줄 수, 트리거 미도달, 랑데부 포트 충돌, 투명 복구 시작 줄 수 |
| `ua_r0`, `ua_r1`, `killed` | 받는 쪽 abort 플래그 줄 수, 상대 kill 기록 |

**`rows_pr.py`가 붙이는 열.** 새 로그 줄과 kv 키의 형식도 여기서 고정한다. 모든 시각은 `mono_ms`(CLOCK_MONOTONIC, ms)다.

| 열 | 출처와 정의 |
|---|---|
| `pr_mode_r0`, `pr_mode_r1` | rank별 WARN `GIN/TS: pair reset=<0\|1> rank=<r>`(helper 시작 때 한 번)의 값. 줄이 없으면 빈칸 |
| `scope_r0`, `scope_reason_r0` | rank 0 첫 범위 결정 줄 `GIN/TS: rank <r>: round <n> peer <p> scope=<0x..> qps=<k> reason=<word> mono_ms=<t>`의 `scope`(문자열)와 `reason` |
| `rec_scope_r0`, `rec_qps_r0`, `rec_scope_r1`, `rec_qps_r1` | rank별 첫 복구 줄(`GIN/TS: recovered`, 역할 무관)의 `scope`(문자열)와 `qps` |
| `n_rec_r0`, `n_rec_r1` | rank별 복구 줄 수(역할 무관) |
| `init_qps_r1` | rank 1의 첫 시작 쪽 복구 줄(`role=initiator`)의 `qps` |
| `commit_us_r0`, `total_us_r0` | rank 0의 첫 시작 쪽 복구 줄의 `commit_us`, `total_us`(지금의 형식 그대로) |
| `conflict_r1` | rank 1의 `GIN/TS: rank=<r> scope conflict:` 줄 수 |
| `ep_c<c>_r<r>` | rank r의 teardown 줄 `GIN/TS: rank <r> gate epochs to rank <p>: [<e0>,<e1>,...]`에서 문맥 c의 값. 장치에서 읽은 게이트 단어의 에폭 반쪽이다(9절 7번). 쓰는 것은 `ep_c0_r0`, `ep_c1_r0`, `ep_c0_r1`, `ep_c1_r1` |
| `inj_ctx_r0`, `inj_ctx_r1` | rank별 첫 장애 훅 발사 줄의 `context=<c>`. 없으면 빈칸(모든 문맥) |
| `r1_q4_in_stall` | 범위 충돌 셀만. rank 1의 첫 장치 쪽 분류 기록 시각에서 `clock_offset_ms`(rank 0 kv)를 뺀 값이 rank 0의 `GIN/TS: TEST stall rank=0 <ms> ms after quiesce mono_ms=<t>` 줄의 [t, t + ms − 2] 안이면 1, 아니면 0. 두 줄 중 하나가 없으면 빈칸 |
| `dual_r0`, `dual_r1` | rank별 kv `dual`(두 문맥 모드면 1) |
| `dual_win_us`, `dual_c1_in_win`, `dual_c1_max_in_win_us`, `dual_c1_end_after_win`, `dual_c1_max_us` | rank 0 kv의 같은 이름 키. 정의는 아래 |

**두 문맥 모드의 kv 키(rank 0)** `[이 실험에서 고정]`. 반복 i의 시작 시각 `s_c[i]`은 게시 직전, 끝 시각 `e_c[i]`은 flush가
돌아온 직후의 globaltimer(ns)이고, c는 문맥이다. 끝난 반복만 센다.
- 묶인 창 W: 문맥 0에서 가장 긴 반복 m의 `[s_0[m], e_0[m]]`. `dual_win_us`는 그 길이(µs)다.
- `dual_c1_in_win`: `s_1[i] >= W 시작`이고 `e_1[i] <= W 끝`인 문맥 1 반복 수.
- `dual_c1_max_in_win_us`: `e_1[i] > W 시작`이고 `s_1[i] < W 끝`인 문맥 1 반복 중 가장 긴 것(µs). 없으면 −1.
- `dual_c1_end_after_win`: 문맥 1의 마지막 반복이 W 끝보다 늦게 끝났으면 1, 아니면 0.
- `dual_c1_max_us`: 문맥 1 반복 전체의 최댓값(µs).

**새 로그 줄** `[소스, 9절의 변경으로 고정]`.

| 줄 | 형식 |
|---|---|
| 시작 | `GIN/TS: pair reset=<0\|1> rank=<r>` |
| 범위 결정(시작 쪽, 게시 멈춤 전) | `GIN/TS: rank <r>: round <n> peer <p> scope=<0x..> qps=<k> reason=<pair\|off\|ctx\|queued\|qp_state\|requeued> mono_ms=<t>` |
| 복구 줄(두 역할) | 지금 줄에서 `qps=<n>` 바로 뒤에 ` scope=<0x..>`를 더한다 |
| 범위 충돌(높은 rank) | `GIN/TS: rank=<r> scope conflict: REQ round <n> from rank <p> scope=<0x..>, ours scope=<0x..> round <m>; ours is requeued as a full reset` |
| teardown | `GIN/TS: rank <r> gate epochs to rank <p>: [<e0>,<e1>,...]` |
| 장애 훅(문맥 지정 시) | `GIN/FAULT: GDAKI fault fired<tag>: moved <a>/<b> GIN QP(s) to ERR context=<c> fire_mono_ms=<t> done_mono_ms=<t>`. 지정하지 않으면 지금 그대로 |

**새 거절 사유.** 응답 쪽 `invalid scope in REQ`(NACK 11), 시작 쪽 `scope mismatch in ACK`. 나머지 문구는 그대로다.

### 3.2 셀 키와 판정식 문법

셀 키(`cell@build`), 판정 대상(8절 제외를 거친 시행), "자료 부족" 규칙, 판정식 문법(`count`, 빈칸 규칙, `has`,
`nonempty`, `median`, `abs`, `per cell:`)은 `../s2_close/EXPERIMENT.md` 3.2절과 같다. 이 실험의 `score.py`는 그 구현
(`../s2_close/score.py`의 판정식 평가 함수)을 그대로 불러 쓴다. `count(...)`와 `median(...)` 밖의 나머지는 Python의 산술과
비교다(예: `0.5 * median(...)`). 판정은 맞음, 틀림, 자료 부족 중 하나다. 두 셀 키를 쓰는 판정식은 두 셀 모두 계획한 수를
채워야 판정한다.

### 3.3 예측 요약

전체 판정식은 [predictions.csv](predictions.csv)에 있다. 아래는 요약이다.

| id | 셀 | 예측 | 판정 기준(요약) | 근거 |
|---|---|---|---|---|
| P1a | `pr_dual_f1c0_b@prd` | 두 문맥에 트래픽이 있을 때 문맥 0의 로컬 QP 오류가 투명하게 복구된다 | ≥9/10 | 전체 재설정으로는 오늘 `rc`의 회귀 셀 30/30 `[측정]` |
| P1b | `pr_dual_f1c0_b@prd` | 라운드는 한 번이고 두 rank 모두 문맥 0 하나(QP 1개)로 좁혀진다 | ≥9/10 | 9절의 결정 규칙 |
| P1c | `pr_dual_f1c0_b@prd` | 문맥 1 QP의 게이트는 두 rank에서 한 번도 닫히거나 새로 공개되지 않는다. 문맥 0은 한 번 공개된다 | ≥9/10 | 오늘 `rc`의 복구 줄 110개 모두 `qps=4` `[측정]` |
| P1d | `pr_dual_f1c0_b@prd` | 문맥 0이 묶인 동안 문맥 1의 반복이 1개 이상 끝나고, 그 창에 걸친 반복은 모두 1 ms 이하다 | ≥9/10 | 장애 없는 4 KiB 반복 최댓값 15.5–21.7 µs(실행 5개의 범위) `[측정]` |
| P2a | `pr_dual_f3c0_b@prd` | 문맥 0 쌍의 상대 QP 오류(rank 0에서 재시도 초과)가 투명하게 복구된다 | ≥9/10 | 오늘 `rc`의 `f3_b` 5/5 `[측정]` |
| P2b | `pr_dual_f3c0_b@prd` | 그 라운드도 두 rank에서 문맥 0으로 좁혀지고 문맥 1의 게이트는 그대로다 | ≥9/10 | 9절 |
| P2c | `pr_dual_f3c0_b@prd` | 재시도 기다림과 라운드 내내 문맥 1이 계속 돈다(P1d와 같은 기준) | ≥9/10 | 재시도는 문맥 0 QP에서만 일어난다 `[추론]` |
| T1 | `pr_dual_f1c0_b@prd` 대 `pr_dual_f1c0_full_b@prd` | 시작 쪽 Commit 중앙값이 같은 hold의 전체 재설정의 절반 이하다 | 비 ≤ 0.5 | 오늘 `rc` 3 191–3 472 µs, QP마다 펌웨어 명령 5개 `[측정, 소스]` |
| T2 | 같음 | 시작 쪽 라운드 전체 중앙값이 0.6 이하다 | 비 ≤ 0.6 | 오늘 `rc` 8 363–13 515 µs `[측정]` |
| B1a | `pr_dual_f1all_b@prd` | rank 0의 모든 문맥 QP가 고장 나도(기존 훅) 두 문맥 모두 투명하게 복구된다 | ≥9/10 | P1a와 같음 |
| B1b | `pr_dual_f1all_b@prd` | 다른 QP가 RTS가 아니거나 문맥 1의 기록이 대기 중이라 전체 재설정 한 번으로 돌아간다 | ≥9/10 | 9절 |
| B2a | `pr_bidirf_conflict_b@pr` | 두 rank가 다른 범위로 동시에 시작해도 둘 다 복구되고 거절이 없다 | ≥9/10 | 오늘 `rc`의 동시 시작 셀 5/5 `[측정]` |
| B2b | `pr_bidirf_conflict_b@pr` | 높은 rank가 충돌을 한 번 보고, 낮은 rank의 문맥 0 라운드에 응답한 뒤 자기 장애를 전체 재설정으로 돈다 | ≥9/10 | 9절의 충돌 규칙 |
| C1a | `pr_dual_f1c0_full_b@prd` | 스위치를 끄면 전체 재설정(QP 4개씩)이고 투명하다 | 5/5 | `rc`의 동작 |
| C1b | `pr_dual_f1c0_full_b@prd` | 전체 재설정에서는 문맥 1도 묶여 1 ms 이상인 반복이 나온다 | ≥4/5 | 전체 라운드 약 10 ms `[측정]`, 모든 게이트를 닫음 `[소스]` |
| C2 | `pr_dual_none_b@prd` | 장애 없이는 두 문맥 모드가 투명하고 라운드가 없으며 문맥 1의 최장 반복이 1 ms 이하다 | 5/5 | 위 지연 최댓값 |
| G1 | `f1_b`, `f3_b`, `bidirf_sym_b`, `mt256_f1_b`(모두 `@pr`) | 주요 복구 셀이 그대로 투명하다 | 셀마다 5/5 | 오늘 `rc` 셀마다 5/5 `[측정]` |
| G2 | `f1_b`, `mt256_f1_b`, `bidirf_sym_b`(모두 `@pr`) | 기존 훅이 그 rank의 QP를 모두 고장 내므로 두 rank 모두 전체 재설정이다 | 셀마다 5/5 | 9절의 대체 규칙 |
| G3 | `f3_b@pr` | 기존 상대 QP 오류 셀은 이제 문맥 0으로 좁혀진다 | 5/5 | 기존 훅은 rank 1의 QP만 고장 낸다 `[소스]` |
| G4 | `f4_b@pr` | 끊김 없는 kill은 죽음 원인으로 거절되고 살아남은 쪽 abort가 돌아온다 | 5/5 | 오늘 `rc` 5/5 `[측정]` |
| G5 | `f2rel_b@pr` | 받는 쪽 abort 해제가 그대로다 | 5/5 | 오늘 `rc` 5/5 `[측정]` |
| L1 | `lat_pr_on_4k@pr` 대 `lat_rc_on_4k@rc` | 4 KiB 지연 차이 0.40 µs 이하 | 같은 hold의 실행 중앙값 | 장치 코드와 드라이버가 같다 `[소스]` |
| L2 | `lat_pr_on_256k@pr` 대 `lat_rc_on_256k@rc` | 256 KiB 지연 차이 0.30 µs 이하 | 같음 | 같음 |

셀 조건은 7절에 있다.

## 4. 범위

**포함.**
- 9절의 라이브러리 변경 하나(라운드 범위, 범위 결정 규칙, REQ와 ACK의 범위, 동시 시작의 범위 충돌 규칙, 로그 줄).
- 시험 스위치 두 개: 장애 훅의 문맥 지정(`NCCL_GIN_FAULT_INJECT_CTX`), 두 문맥 드라이버 모드(`GIN_TS_DUAL=1`).
- 7절의 셀 18개.
  - 새 셀 4개: 문맥 0만 로컬 QP 오류, 문맥 0만 상대 QP 오류, rank 0의 모든 문맥 고장, 범위 충돌.
  - 대조 셀 2개: 전체 재설정 기준, 장애 없음.
  - 재현 셀 6개.
  - 지연 셀 4개, 그중 2개는 `rc` 기준.

**제외.**
- 장치 코드 변경. 장치 쪽은 이미 QP별이라 필요 없다 `[소스]`.
- 문맥 여러 개(전부는 아닌)로 좁히기. 범위는 문맥 하나 아니면 전체다.
- 응답 쪽의 건강 검사. 응답 쪽은 REQ의 범위를 그대로 따른다. 응답 쪽의 다른 쌍이 이미 고장 나 있으면 그 쌍은 쓸 때 따로
  복구된다(지금도 쉬는 QP의 오류는 다음 사용 때 복구된다).
- 요청 쪽만 재설정(설계 문서 항목 C4), 3 rank 이상, 여러 GDAKI 문맥.
- 실제 관리망 장애, 링크 내리기, RoCE 주소 변경.

## 5. 테스트베드와 버전

| 항목 | 값 | 확인 방법과 날짜 |
|---|---|---|
| 노드 | rain(rank 0, 보내는 쪽), sunny(rank 1, 받는 쪽) | 루트 `README.md` 테스트베드 표 |
| NIC와 펌웨어 | ConnectX-6 VPI, fw 20.43.4100. rain `mlx5_1`, sunny `mlx5_0` | `[측정]` 2026-10-06, `../../completion_contract/EXPERIMENT.md` 5절. hold 스냅숏에서 다시 기록 |
| 커널, OFED | rain 커널 5.15.0-97-generic. OFED | 커널 `[측정]` 2026-10-07. OFED `[미확인]` |
| GPU와 CUDA | rain Quadro RTX 5000(sm_75), sunny RTX A4000(sm_86), PeerMappingOverride=1, CUDA 12.8 | gin-s2-close 5절 |
| GIN 문맥 | 사용자 devComm의 GDAKI 문맥 하나에 GIN 문맥 4개, 문맥마다 상대 QP 1개 | `[측정]` 2026-10-08 gin-reconnect 로그 180줄 |
| 기준 라이브러리 `rc` | libnccl `8354411f`, 드라이버 `d4b1f082` | `[측정]` 2026-10-08 배포 때 두 노드 같음(`../reconnect/deploy_check.txt`) |
| 이 실험의 빌드 `pr`, `prd` | libnccl md5, `prd` 드라이버 md5, 배포 확인 | `[미확인]` 빌드 전. 배포 때 기록 |

## 6. 변수

- **독립변수.**
  - 빌드: `rc`, `pr`, `prd`.
  - 범위 스위치 `NCCL_GIN_TS_PAIR_RESET`(1 기본, 0).
  - 장애 종류, 장애 난 문맥(훅의 문맥 지정 유무), 장애 시각.
  - 트래픽: 두 문맥 모드, 기존 단방향, 양방향.
- **종속변수.** 3.1의 열이다.
  - 투명 여부, 거절 사유.
  - 라운드 범위와 QP 수, 범위 결정 이유, 게이트 에폭.
  - 장애 난 문맥이 묶인 창 동안 다른 문맥의 반복 수와 최장 반복.
  - 시작 쪽 Commit과 라운드 전체 시간, 지연 p50.
- **통제변수.**
  - IB 타임아웃 14, GPU doorbell, 재연결 스위치 기본값(1).
  - 기존 셀 정의는 `../scripts/ts2/batch.sh`와 `../reconnect/cells.sh` 그대로다(빌드만 `pr`).
  - 두 문맥 모드의 문맥 0과 1은 같은 크기(4 KiB), 같은 반복 수, 같은 간격이다.
  - 시행마다 프로세스를 새로 띄운다.

## 7. 실험 셀, 반복 수, 대조군

반복 수는 사전 등록 규칙(새 셀 10, 재현 5, 대조 5)을 따른다. 지연 셀의 반복은 실행 수다(실행마다 3000번 반복).
장애 훅의 지연은 각 rank의 GDAKI 문맥 생성부터 잰다. 오늘 `f1_b@rc` 5회에서 커널은 그 기준 뒤 35.5–36.2 ms에 시작했다 `[측정]`.
오늘 `f3_b@rc` 5회에서 상대 QP 오류의 반복은 3.54–3.65 s 걸렸다(재시도 초과까지) `[측정]`. 아래 `inj`는 시행 번호 k에 대해
`400 + (k × 137) mod 700` ms다.

| 셀 | 조건 | 반복 수 | 대조군 여부 |
|---|---|--:|---|
| `pr_dual_f1c0_b@prd` | 두 문맥 모드(`GIN_TS_DUAL=1`), 문맥마다 4 KiB × 3000, 간격 500 µs(약 1.54 s). rank 0 `local_err:inj`, `NCCL_GIN_FAULT_INJECT_CTX=0` | 10 | 새 셀 |
| `pr_dual_f3c0_b@prd` | 두 문맥 모드, 4 KiB × 3000, 간격 2000 µs(약 6.0 s). rank 1 `peer_err:inj`, `NCCL_GIN_FAULT_INJECT_CTX=0`. `WATCHDOG_S=60` | 10 | 새 셀 |
| `pr_dual_f1all_b@prd` | `pr_dual_f1c0_b`와 같고 문맥 지정이 없다(기존 훅: rank 0의 모든 문맥 QP) | 10 | 새 셀 |
| `pr_bidirf_conflict_b@pr` | 양방향 한 커널 모드(`GIN_TS_BIDIR_FUSED=1`), 4 KiB × 8000, 간격 0. rank 0 `local_err:i0`, 문맥 0 지정, `NCCL_GIN_TS_TEST_STALL=20@quiesce`. rank 1 `local_err:i0+5`, 문맥 1 지정. `i0 = 60 + (k × 7) mod 50` ms | 10 | 새 셀 |
| `pr_dual_f1c0_full_b@prd` | `pr_dual_f1c0_b`와 같고 두 rank에 `NCCL_GIN_TS_PAIR_RESET=0`. 같은 hold에서 `pr_dual_f1c0_b`와 섞어 돈다 | 5 | 대조 |
| `pr_dual_none_b@prd` | 두 문맥 모드, 4 KiB × 3000, 간격 500 µs, 장애 없음 | 5 | 대조 |
| `f1_b@pr`, `f3_b@pr`, `bidirf_sym_b@pr`, `mt256_f1_b@pr`, `f4_b@pr` | `batch.sh`의 기존 정의, 빌드만 `pr` | 각 5 | 재현 |
| `f2rel_b@pr` | `../reconnect/cells.sh`의 `f2rel_b`와 같은 조건, 빌드만 `pr` | 5 | 재현 |
| `lat_rc_on_4k@rc`, `lat_rc_on_256k@rc` | `../reconnect/cells.sh`의 정의. 아래 두 셀과 같은 hold에서 섞어 돈다 | 각 5 | 재현(지연 기준) |
| `lat_pr_on_4k@pr`, `lat_pr_on_256k@pr` | 투명 복구 켬, 장애 없음, 3000번 반복 | 각 5 | 대조 |

두 문맥 모드의 창은 송신, 수신 각각 2 × 3000 × 4 KiB = 24 MiB다. 범위 검토 메모(세션 스크래치)의 B12 항목은 rain에서 GIN 창이
약 50 MiB까지만 등록된다고 적었다 `[미확인]`. 오늘 `f1_b@rc`는 창 30 MiB(256 KiB × 120)로 돌았다 `[측정]`.

**합계.**

| 종류 | 셀 시행 | 지연 실행 |
|---|--:|--:|
| 새 셀 | 40 | |
| 재현 | 30 | 10 |
| 대조 | 10 | 10 |
| 합 | 80 | 20 |

## 8. 제외 기준과 중단 기준

**제외 기준.** 제외한 시행은 셀별로 따로 세어 보고한다.
- smoke 실행(`results/<날짜>_smoke/`)은 채점하지 않는다.
- NCCL 초기화 전 실패(`bind_fail == 1`)는 제외하고 다음 번호로 계획한 반복 수를 채운다.
- 장애 미적용은 제외하고 다음 번호로 채운다.
  - 로컬 QP 오류 셀(`pr_dual_f1c0_b`, `pr_dual_f1c0_full_b`, `pr_dual_f1all_b`, `f1_b`, `mt256_f1_b`)에서 `n_fires_r0 == 0`.
  - 상대 QP 오류 셀(`pr_dual_f3c0_b`, `f3_b`)에서 `n_fires_r1 == 0`.
  - 두 rank 훅 셀(`pr_bidirf_conflict_b`, `bidirf_sym_b`)에서 `n_fires_r0 == 0` 또는 `n_fires_r1 == 0`.
  - `trigger_miss > 0`. kill 셀에서 `killed != 1`.
- 조건 미적용은 제외하고 다음 번호로 채운다.
  - 문맥 0 장애의 두 문맥 셀(`pr_dual_f1c0_b`, `pr_dual_f1c0_full_b`, `pr_dual_f3c0_b`)에서 `dual_c1_end_after_win != 1`(빈칸
    포함). 문맥 1이 묶인 창보다 먼저 끝나면 다른 문맥이 계속 도는지를 잴 수 없다.
  - 범위 충돌 셀에서 `r1_q4_in_stall != 1`. rank 1의 장애가 rank 0의 라운드가 멈춘 동안 오지 않으면 동시 시작이 만들어지지
    않는다.
- 채우려고 다시 돈 시행이 셀마다 계획의 50%를 넘으면 그 셀은 멈추고 "자료 부족"으로 둔다.

**설정 확인.** 하나라도 어긋나면 제외가 아니라 그 블록을 멈춘다.
- 투명 복구를 켠 시행은 `ts_on_r0 >= 1`, `ts_on_r1 >= 1`, `ua_r0 >= 1`, `ua_r1 >= 1`이어야 한다.
- `pr`, `prd` 시행은 `pr_mode_r0`, `pr_mode_r1`이 `pr_dual_f1c0_full_b`에서는 0, 나머지에서는 1이어야 한다.
- `prd` 시행은 `dual_r0 == 1`, `dual_r1 == 1`이어야 한다.
- 문맥 지정: `pr_dual_f1c0_b`, `pr_dual_f1c0_full_b`는 `inj_ctx_r0 == 0`, `pr_dual_f3c0_b`는 `inj_ctx_r1 == 0`,
  `pr_bidirf_conflict_b`는 `inj_ctx_r0 == 0`이고 `inj_ctx_r1 == 1`, `pr_dual_f1all_b`는 `inj_ctx_r0`가 빈칸이어야 한다.

**smoke에서 구현 결함이 보일 때.** 다음 중 하나가 보이면 구현 결함으로 본다. 본 실행 전에 코드를 고칠 수 있고, 그 변경은
`DEVIATIONS.md`에 적는다. 예측, 판정식, 셀 조건은 바꾸지 않는다.
- `pr_dual_f1c0_b` smoke 2회 모두 라운드가 문맥 0으로 좁혀지지 않았다.
- 두 문맥 모드의 장애 없는 smoke가 투명하지 않다.
- 범위 충돌 smoke 2회 모두 `r1_q4_in_stall == 1`인데 충돌 줄이 없다.

예외로, 범위 충돌 smoke 2회 모두 `r1_q4_in_stall != 1`이면 rank 1 훅의 지연(`i0 + 5`)을 본 실행 전에 한 번 바꿀 수 있다.
바꾼 값과 이유는 `DEVIATIONS.md`에 적는다.

**중단 기준.**
- **잠금.** 모든 클러스터 명령은 `harness/gpu-initiated/common/cluster_run.sh -w 10800` 안에서 돈다. 다른 실험(예: NVSHMEM 3.8.0
  이식 실험)이 같은 잠금을 쓴다.
  - 10 800 s 안에 잠금이나 유휴 링크를 얻지 못하면(종료 코드 75) 그 hold를 미룬다.
  - `prio-` 작업에는 양보한다.
  - hold 하나는 15분 이하이고 `timeout -s KILL 880`으로 묶는다.
- **하지 않는 것.** 실제 link down이나 flap, 재부팅, 드라이버 재적재, 커널 모듈 적재, RoCE 주소 변경, iptables 같은 방화벽 변경.
  - 장애는 우리 프로세스의 QP를 ERR로 보내는 훅과 상대 프로세스 kill로만 만든다.
- **프로세스.** 우리가 띄운 프로세스만 정확한 이름(`pkill -x gin_ts2`)이나 PID로 끈다.
  - 다른 사용자의 작업은 건드리지 않는다. 예: gds-kv, NVMe-oF, gdsio, mooncake, `prio-` 작업.
  - `left > 0`이 두 시행 연속이면 멈춘다.
- **mlx5 오류.** rain `mlx5_1`은 펌웨어 명령 슬롯 하나가 새어 있다. hold 앞뒤에 두 노드의 mlx5 커널 줄 전체와 rain의 펌웨어
  명령 계수를 남기고, hold 동안 새로 생긴 mlx5 줄은 수가 아니라 내용을 12절과 `mlx5_new_<hold>.txt`에 적는다. 다음 중 하나가
  보이면 그 hold 뒤로 멈추고 12절에 기록한다.
  - 두 노드 dmesg에 새 mlx5 명령 오류 줄이 생겼다. 명령 오류 줄은 `mlx5`와 함께 `cmd` 또는 `command`, 그리고 `failed`,
    `timeout`, `leak` 중 하나를 담은 줄이다.
  - rain debugfs의 명령 실패 계수(`failed`, `failed_mbox_status`)가 늘었다.

  rain에는 이 실험 전부터 명령 오류 줄 2개(2026-09-25)가 있고 펌웨어 명령 실패 수는 31이다(2026-10-08 hold 스냅숏) `[측정]`.
  hold 앞뒤의 증가로 판단한다.
- **배포.** 새 번들은 새 디렉터리 `$HOME/gi-bundle/gin_ts2/pr/`와 `prd/`에만 둔다.
  - 대상 파일이 이미 있으면 배포 스크립트가 멈춘다.
  - 배포 뒤 기존 번들 파일(최종, `s1/`, `base/`, `var_sys/`, `s2r/`, `s2rget/`, `rc/`, `rc_smoke_1193a5f8/`)의 md5가 두 노드에서
    그대로인지 확인한다.

## 9. 실행 방법과 경로

**라이브러리 변경.** 아직 하지 않았고 빌드도 하지 않았다. 사전 등록 뒤에 한다. 대상은 `src/transport/net_ib/gdaki/gin_host_gdaki.cc`
하나다(헤더와 장치 코드는 그대로). 변경분은 `pr_layer.diff`(`rc` 트리 기준)와 전체 diff `gin_transparent_pr.diff`(pristine 기준)로
남긴다.
1. **범위 마스크.**
   - helper 스레드 전용 thread_local 마스크(기본 "모든 문맥")를 둔다. `gdakiRecForPeer`(1230–1238행)는 helper 안에서 마스크에
     없는 문맥을 건너뛴다.
   - 라운드의 모든 단계(게시 멈춤, Prepare, 실행 수, Commit, 기준선, commit point, 재게시와 공개, 포기 검사)가 이 함수 하나로
     QP를 돌므로 한 곳에서 좁혀진다 `[소스]`.
   - 라운드를 시작할 때 마스크를 정하고, 모든 반환 경로에서 되돌린다.
   - 거절(`gdakiTsDecline`, 2994–3028행)은 시작할 때 마스크를 "모든 문맥"으로 되돌린다. 거절은 지금처럼 상대 전체에 대해 한다.
     유휴 검사(3467–3490행)와 teardown은 라운드 밖이라 늘 전체다.
2. **스위치.** `NCCL_GIN_TS_PAIR_RESET=0|1`(기본 1). helper 시작 때 시작 줄(3.1)을 남긴다.
3. **범위 결정**(시작 쪽, 생존 확인과 재연결 기다림 뒤, 게시 멈춤 전). 아래를 모두 만족하면 범위는 기록의 문맥 하나
   (`1 << ctx_id`), 아니면 전체다. 결정 줄(3.1)의 `reason`은 처음 걸린 조건이다.
   1. 스위치가 1이다(아니면 `off`).
   2. 범위 충돌로 다시 넣은 기록이 아니다(아니면 `requeued`).
   3. 기록의 문맥 번호가 GIN 문맥 수보다 작고, 그 문맥에 이 상대로 가는 QP가 있다(아니면 `ctx`).
   4. 같은 상대, 다른 문맥의 장애 기록이 대기열이나 지금 처리 중인 묶음에 없다(아니면 `queued`).
   5. 이 rank에서 같은 상대로 가는 다른 문맥 QP가 모두 QUERY_QP로 RTS다(아니면 `qp_state`). 질의는 QP 상태 변경과 겹치지
      않게 `opMu` 안에서 한다. 질의 실패도 RTS가 아님으로 본다.

   모두 만족하면 `reason=pair`다.
4. **REQ와 ACK의 범위.**
   - `gdakiTsMsg.pad`(2016행, 지금은 0)에 범위를 싣는다. 0은 "모든 문맥"이고 바꾸기 전과 같은 뜻이다.
   - 응답 쪽은 REQ의 범위를 그대로 쓴다. 범위에 그 상대 QP가 없는 문맥이 있으면 NACK 11을 보내고 `invalid scope in REQ`로
     거절한다. ACK에 같은 범위를 싣는다.
   - 시작 쪽은 ACK의 범위가 자기 범위와 다르면 `scope mismatch in ACK`로 거절한다.
   - Commit의 토큰 검사(1737–1746행)가 양쪽 QP 목록이 같은지 다시 확인한다. 범위가 어긋나면 재설정 없이 거절로 끝난다 `[소스]`.
5. **동시 시작의 범위 충돌**(2단계 tie-break, 3356–3377행).
   - 낮은 rank는 지금처럼 자기 라운드를 지킨다.
   - 높은 rank는 상대 REQ의 범위가 자기 범위와 같으면 지금처럼 물러나 자기 Prepare로 응답한다.
   - 다르면 높은 rank는 다음을 한다.
     - 자기 Prepare를 푼다(`ncclGinRecoverAbort`). QP는 ERR이고 게이트는 닫힌 채다.
     - 자기 장애 기록에 "전체" 표시를 달아 대기열에 다시 넣는다.
     - 낮은 rank의 REQ에 처음부터 응답한다(그 범위로 게시 멈춤, Prepare, Commit).
     - 그 라운드가 끝나면 다시 넣은 기록이 전체 재설정 라운드를 시작한다. 낮은 rank의 범위가 자기 문맥을 이미 덮었으면 그 기록은
       오래된 기록으로 버려진다(3231행의 에폭 검사).
   - 높은 rank는 충돌 줄(3.1)을 남긴다.
6. **복구 줄.** 시작 쪽과 응답 쪽 복구 줄에 범위를 더한다(3.1).
7. **teardown 에폭 줄.** 게이트를 막기 전에 gated 상대마다 에폭 줄(3.1)을 남긴다. 값은 장치에서 읽은 게이트 단어의 에폭 반쪽
   (`NCCL_GIN_TS_W_EPOCH_MASK`)이고 문맥 순서다. 닫혀 있으면 홀수, 공개된 라운드마다 2씩 는다(2624행, 2958–2980행).
8. **시험 스위치 `NCCL_GIN_FAULT_INJECT_CTX=<c>`.** 장애 훅(648–679행)이 문맥 c의 상대 QP만 ERR로 보낸다. 발사 줄은 3.1 형식이다.
   지정하지 않으면 지금 그대로다. 시험 전용이다.

**안전 논증** `[소스, 추론]`.
- QP별 상태: 장치 인덱스와 CQ 위치, 게이트 단어와 게이트 구조, 재게시용 보관 영역, 응답 MSN 기준선, get 표(문맥과 상대별),
  에폭, PSN. 범위 밖 QP의 이 값들은 라운드가 읽지도 쓰지도 않는다.
- GIN 문맥별 상태: 장치 오류 플래그. 거절할 때만 켜고, 거절은 전체다.
- GDAKI 문맥 하나에 공유하는 것: helper 스레드와 소켓, Prepare 상태(`state`, `preparedPeer`), proxy 진행 멈춤, 분류 기록
  우편함, 거절.
  - proxy 진행 멈춤은 GPU doorbell 모드에서 효과가 없다. 진행 함수가 CPU proxy QP만 돈다(4840–4874행).
  - Prepare 상태는 한 라운드에 하나라 범위와 관계없다.
- 양쪽 범위가 같다는 것은 4번의 검사와 Commit의 토큰 검사가 보장한다.
- 범위 밖 다른 쌍이 이미 고장 나 있어도 이 라운드의 정확성에는 영향이 없다. 그 쌍의 장애는 쓸 때 자기 기록으로 따로 라운드를
  연다. 이 rank 쪽에서 그런 쌍이 보이면(3번의 4, 5) 한 번에 고치려고 전체로 간다.

**두 문맥 드라이버 모드**(`../gin_ts2.cu`, `GIN_TS_DUAL=1`, 모드 `none`에서만, rank 0이 보내고 rank 1이 받는다).
- rank 0: 커널 하나에 CTA 2개. CTA c는 문맥 c로 `for i: put(문맥 c의 슬롯 i, bytes) + signal ADD(문맥 c의 신호 0) ; flush ; [gap]`를
  돈다. 슬롯 영역은 문맥마다 따로다. 반복마다 시작과 끝의 globaltimer를 기록하고, 끝난 뒤 호스트가 3.1의 키를 계산한다.
- rank 1: 커널 하나에 CTA 2개. CTA c는 문맥 c의 신호 0을 기다리고 그 반복의 슬롯을 장치에서 검사한다(패턴 seed c + 1).
  끝나면 호스트가 모든 슬롯과 두 문맥의 최종 신호를 검사한다.
- 기존 kv 키는 두 문맥을 합쳐 쓴다(`tx_done`은 작은 쪽, `tx_rc`는 먼저 난 오류, 슬롯과 신호 검사는 합). 그래서 `rows.py`의
  `transparent_ok` 정의가 그대로 적용된다. 두 문맥 전용 키는 3.1에 있다.
- 다른 모드의 코드는 그대로다. 새 드라이버는 `prd` 번들에만 둔다. 지연과 재현 셀은 `pr` 번들(`rc`와 같은 드라이버
  `d4b1f082`)로 돈다.

**빌드.** 세션 스크래치 `$SCR`(`/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad`)에서 한다.
1. `agent_ts2rc`의 트리와 빌드 디렉터리를 `agent_ts2pr`로 복사한다. 의존 파일과 장치 manifest의 경로를 바꾸고 원래 시각을
   돌려준다(gin-reconnect `build_rc.sh`와 같은 방식).
2. 스크래치 저장소에 `rc` 상태를 커밋하고 `pr_layer.diff`를 적용한다.
3. `make -n`으로 다시 컴파일되는 파일이 `gin_host_gdaki.cc`와 버전 표시뿐인지 확인한 뒤 증분 빌드한다.
4. 드라이버: `pr`은 `d4b1f082`를 복사한다. `prd`는 두 문맥 모드를 더한 `../gin_ts2.cu`를 `agent_ts2pr` 빌드에 대고
   `../scripts/ts2/build_driver.sh`와 같은 명령으로 빌드한다.

이 폴더에 둘 스크립트는 `build_pr.sh`, `make_diff_pr.sh`, `deploy_pr.sh`다. 전체 diff로 pristine에서 트리가 재현되는지 확인한다.

**배포.** `deploy_pr.sh`로 두 노드의 `pr/`, `prd/`에 둔다. 대상 파일이 있으면 멈추고, 두 노드 md5, `ldd`, 기존 번들 md5를
확인한다(8절).

**실행.**
- `../scripts/ts2/run_trial.sh`를 그대로 쓴다. 두 문맥 모드는 `EXTRA_ENV="GIN_TS_DUAL=1"`로, 문맥 지정은 `R0_ENV`나 `R1_ENV`로 준다.
- 재현 셀은 `BUILD=pr bash ../scripts/ts2/batch.sh`로, `rc` 지연 셀은 `../reconnect/cells.sh`로 돈다.
- 새 셀, 대조 셀, `pr` 지연 셀, `f2rel_b@pr`는 이 폴더의 `cells.sh`가 7절 조건대로 정의한다.
- hold는 이 폴더의 `hold.sh`에 두고, 각 hold를 `chain.sh`로 따로 `cluster_run.sh -w 10800 -t gpr-<hold>`에 넣는다.

| hold | 내용 | 추정 `[추론]` |
|---|---|---|
| H0 smoke | `pr_dual_f1c0_b` 2회, 범위 충돌 2회, 나머지 새 셀과 대조 셀 1회씩, `f3_b@pr` 1회, 지연 `pr`과 `rc` 4 KiB 1회씩 | 5분 |
| H1 | 지연 4셀 × 5(섞어서), 재현 셀 6개 × 5 | 8분 |
| H2 | `pr_dual_f1c0_b` 10회와 `pr_dual_f1c0_full_b` 5회(2:1로 섞어서), `pr_dual_none_b` 5회 | 6분 |
| H3 | `pr_dual_f3c0_b` 10회, `pr_dual_f1all_b` 10회 | 7분 |
| H4 | `pr_bidirf_conflict_b` 10회 | 3분 |

hold마다 잠금과 유휴 확인이 약 1분 더 든다. 클러스터 시간은 모두 35–45분이다 `[추론]`.

**채점.**
1. `../scripts/ts2/rows.py`로 hold 폴더마다 시행 CSV를 만든다.
2. `../s2_close/rows_extra.py`와 이 폴더의 `rows_pr.py`가 3.1의 열을 붙인다.
3. 이 폴더의 `score.py`가 [predictions.csv](predictions.csv)의 판정식을 3.2 문법대로 적용한다. 결과는
   `results/<날짜>/SCORE.md`와 `results/<날짜>/trials_scored.csv`다.

**출력.** 결과 폴더 `results/<날짜>/<hold 폴더>/`. 원시 로그는 Release에 올린다.

## 10. 완료 조건과 QA 기준

- [ ] 모든 셀이 계획한 반복 수만큼 실행됐다. 제외와 실패를 따로 센 표가 있다.
- [ ] 예측 23줄마다 판정(맞음, 틀림, 자료 부족)과 놓친 시행 목록이 있다.
- [ ] 다른 에이전트가 `score.py`를 보지 않고 원자료에서 핵심 수치를 다시 셌다. 대상은 라운드 범위와 QP 수, 게이트 에폭, 문맥
  1의 창 안 반복, Commit과 라운드 시간, 투명 여부다.
- [ ] 다른 에이전트가 `pr_layer.diff`와 두 문맥 모드 diff를 읽고 리뷰했다.
- [ ] smoke와 제외 시행이 결과에 섞이지 않았다.
- [ ] 새 빌드의 md5, 전체 diff, pristine + diff 확인 결과를 5절에 적었다.
- [ ] 원자료를 Release에 올리고 `DATA.md`에 적었다.
- [ ] hold 전후 mlx5 스냅숏에 새 명령 오류가 없었거나, 있었다면 그 줄의 내용을 12절에 적었다.

## 11. 작업 체크리스트

- [x] 질문, 가설, 셀 작성 (`DRAFT`)
- [x] 고정 절 완성, 상태 `PREREGISTERED`, 해시 기록을 커밋 하나로 만들고 그 커밋에 `prereg/` 태그
- [ ] 코드 변경(라이브러리, 시험 스위치, 두 문맥 모드), 빌드, 배포
- [ ] `cells.sh`, `hold.sh`, `chain.sh`, `rows_pr.py`, `score.py`
- [ ] smoke 실행(채점 제외)
- [ ] 본 실행 (`RUNNING`)
- [ ] 채점 (`QA`)
- [ ] 독립 재계산과 코드 리뷰
- [ ] 결과 정리, 원자료 릴리스, PR
- [ ] 결론 확정 (`COMPLETE`)

## 12. 실행 기록 (시간순)

| 시각 | 무엇을 했나 | 결과와 근거(경로, 커밋, 실행 ID) |
|---|---|---|
| 2026-10-08 | gin-reconnect 원자료(`rc` 빌드)에서 기준 수치를 다시 셈 `[측정]`. 복구 줄 110개 모두 `qps=4`, "recovery ON" 줄 180개 모두 `contexts=4`. 시작 쪽 Commit 3 191–3 472 µs(55라운드), 응답 쪽 3 597–3 906 µs(55라운드), 시작 쪽 라운드 전체 8 363–13 515 µs(45라운드). `f1_b@rc` 커널 시작은 훅 기준 뒤 35.5–36.2 ms(5회), `f3_b@rc` 장애 반복 3.54–3.65 s(5회), `lat_rc_on_4k@rc` 반복 최댓값 15.5–21.7 µs(실행 5개) | `../reconnect/results/20261008/rep_rc/`, `mute/`, `lat/`(Release 예정), `../reconnect/results/20261008/trials_scored.csv` |
| 2026-10-08 | 코드를 읽고 범위를 다시 봄 `[추론]`. 범위 검토 메모는 1.5–2일로 봤다. 장치 코드는 이미 QP별이고 호스트의 모든 QP 순회가 `gdakiRecForPeer` 하나를 지나므로 약 하루로 본다. 가장 큰 새 부분은 동시 시작의 범위 충돌 규칙이다 | 1절, 9절 |
| 2026-10-08 | 사용자가 이 후속 실험을 승인 | |
| 2026-10-08 12:08:13 | 사전 등록 | [PREREG.txt](PREREG.txt), 태그 `prereg/gin-pair-reset-v1` |

## 13. 사전 등록 이후 변경

> 기존 문장을 고치지 않고 여기에 덧붙인다. 변경이 많으면 `DEVIATIONS.md`에 두고 링크한다.

| 날짜 | 무엇을 | 이유 | 영향 범위 | 커밋 |
|---|---|---|---|---|

## 14. 원자료와 결과표

| 무엇 | 경로 또는 Release 자산 | n |
|---|---|--:|

## 15. 결과 요약

> 예측별 판정과 핵심 수치. 수치마다 n과 근거 링크를 붙인다. 아직이면 `[미확인]`.

## 16. QA와 재현성

> 누가(사람 또는 에이전트) 무엇을 다시 셌고 무엇이 맞거나 달랐는지. 재현에 필요한 빌드와 커밋.

## 17. 결론

## 18. 한계

## 19. 다음 작업

## 20. 참고자료

- `../reconnect/EXPERIMENT.md`(gin-reconnect, 이 실험의 기준 빌드 `rc`)
- `../s2_close/EXPERIMENT.md` 3.2절(판정식 문법)
- `../TRANSPARENT_S2.md`(투명 복구 2단계 설계와 측정)
