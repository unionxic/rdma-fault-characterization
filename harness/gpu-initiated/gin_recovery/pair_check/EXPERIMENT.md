# GIN 투명 복구: 좁힌 라운드에서 응답 쪽 QP 검사 (gin-pair-check)

**목적:** 장애 난 QP 쌍만 재설정하는 라운드에서 응답 쪽도 자기 QP를 검사하게 한다. 범위 밖 QP가 RTS가 아니면 좁히기를 거절하고
라운드를 전체 재설정으로 다시 돌린다. 그러면 상대 쪽이 여러 QP를 잃은 장애 뒤에 고장 난 QP가 남지 않는지, 응답 쪽이 깨끗할 때는
여전히 좁혀지는지, 범위 충돌 뒤에 범위를 다시 정하는지를 사전 등록한 예측으로 잰다.

| 항목 | 값 |
|---|---|
| 상태 | `PREREGISTERED` |
| 담당자 | @unionxic |
| 작성일 | 2026-10-08 |
| 기준 브랜치와 커밋 | `exp/gin-pair-check` @ `613003e9` (master) |
| 사전 등록 태그 | `prereg/gin-pair-check-v1` (상태를 `PREREGISTERED`로 바꾼 바로 그 커밋) |
| 마지막 갱신 | 2026-10-08 13:51, 사전 등록 |

표시: `[측정]` 원자료에서 확인, `[소스]` 코드에서 읽음, `[추론]` 해석, `[미확인]` 확인 안 함.

이 문서의 소스 줄 번호는 gin-pair-reset 라이브러리 트리 기준이다. 그 트리는 pristine NCCL v2.32.3-1에
`../pair_reset/gin_transparent_pr.diff`(md5 `6d096b3d`)를 적용한 것과 같다(세션 스크래치 `agent_ts2pr/nccl-src`,
`gin_host_gdaki.cc` md5 `bf5e4eb0`, libnccl `51c2426c`).

**용어.** `../pair_reset/EXPERIMENT.md`와 같다.
- GIN 문맥: 사용자 devComm의 GDAKI 문맥 하나 안의 GIN 문맥. 문맥마다 상대 rank 하나에 QP가 하나씩 있다. 이 테스트베드에서는 4개다.
- QP 쌍: 두 rank의 같은 문맥 QP 둘.
- 범위: 한 복구 라운드가 다루는 문맥의 비트 마스크(`0x1`은 문맥 0만, `0xf`는 4개 전부).
- 좁힌 라운드: 범위가 문맥 하나인 라운드. 전체 재설정: 모든 문맥의 라운드.
- 시작 쪽: 장애를 받아 라운드를 여는 rank. 응답 쪽: REQ를 받아 따르는 rank.

장애 기호와 셀 이름은 원자료를 찾는 키로만 괄호나 표의 id 열에 둔다.

| 장애 | 기호 |
|---|---|
| 로컬 QP 오류 | F1 |
| 원격 접근 오류 | F2 |
| 상대 QP 오류 | F3 |
| 상대 프로세스 kill | F4 |

빌드 키는 네 가지다.

| 빌드 | 키 | 내용 |
|---|---|---|
| gin-pair-reset 라이브러리 | `pr` | libnccl `51c2426c`와 최종 2단계 드라이버 `d4b1f082`(`$HOME/gi-bundle/gin_ts2/pr/`). 같은 hold의 기준으로만 쓴다 |
| gin-pair-reset 라이브러리와 두 문맥 드라이버 | `prd` | 같은 libnccl과 두 문맥 드라이버 `4926edee`(`$HOME/gi-bundle/gin_ts2/prd/`). 같은 hold의 기준으로만 쓴다 |
| 이 실험의 라이브러리 | `pc` | `pr` 위에 9절의 변경을 더한 libnccl과 드라이버 `d4b1f082`(`$HOME/gi-bundle/gin_ts2/pc/`, 새 디렉터리) |
| 이 실험의 라이브러리와 두 문맥 드라이버 | `pcd` | `pc`와 같은 libnccl, 드라이버 `4926edee`(`$HOME/gi-bundle/gin_ts2/pcd/`, 새 디렉터리) |

## 1. 배경과 연구 질문

**지금의 동작** `[소스]`(`transport/net_ib/gdaki/gin_host_gdaki.cc`).
- 시작 쪽만 범위를 정한다(`gdakiTsDecideScope`, 2214–2265행). 기록의 문맥, 이 rank의 대기열과 묶음, 이 rank의 다른 QP 상태
  (QUERY_QP)를 본다. 상대의 QP 상태는 모른다.
- 응답 쪽은 REQ의 범위가 유효하면 그대로 따른다(3571–3580행). 자기 QP는 보지 않는다.
- 응답 쪽은 자기 `NCCL_GIN_TS_PAIR_RESET` 값을 보지 않는다. 그 값은 범위 결정에서만 읽는다(2220행).
- 범위 충돌 뒤 높은 rank는 자기 장애를 늘 전체 재설정으로 다시 돈다(`gdakiTsRequeueFull` 2202–2208행, 2224–2227행).

**gin-pair-reset이 잰 것** `[측정]`. 근거는 `../pair_reset/results/20261008/trials_scored.csv`, `../pair_reset/qa/code_review.md`,
Release `data-20261008`이다.
- 기존 상대 QP 오류 셀(`f3_b@pr`) 5회 모두 다음과 같았다(코드 리뷰 항목 1, 원자료에서 셈).
  - rank 1의 훅이 QP 4개를 ERR로 보냈다(`moved 4/4`). rank 0은 `scope=0x1 reason=pair`로 정했다.
  - 두 rank 모두 복구 줄은 하나, `qps=1`이었고 게이트 에폭은 두 rank 모두 `[2,0,0,0]`이었다.
  - 그래서 rank 1의 문맥 1–3 QP는 훅부터 시행 끝까지 ERR이었고 게이트는 열려 있었다 `[추론, 코드 리뷰]`. 투명 복구 판정은 5/5
    맞았다. 그 셀의 트래픽은 문맥 0만 쓰기 때문이다.
- 범위 충돌 셀 11회 모두 rank 1의 재실행이 전체 재설정이었고 두 rank 에폭은 `[4,2,2,2]`였다. rank 1의 재실행 Commit은
  3 612–3 787 µs, 좁힌 응답의 Commit은 934–998 µs였다(판정 10회의 범위, 코드 리뷰 항목 5).
- 좁힌 문맥 0 로컬 QP 오류(`pr_dual_f1c0_b@prd`)의 시작 쪽 Commit은 743–785 µs(10회, 중앙값 768), 라운드 전체는
  2 934–3 093 µs(중앙값 3 013)였다.
- 좁힌 라운드 하나는 rank 0에서 `2RST_QP` 1개와 `QUERY_QP` 5개(그중 3개가 범위 결정)를 쓴다 `[측정, 코드 리뷰의 펌웨어 계수,
  대응은 추론]`. QUERY_QP 하나의 시간은 잰 적이 없다 `[미확인]`.

**문제** `[추론]`. 좁히기를 시작 쪽 QP만 보고 정하면, 상대 쪽이 여러 QP를 잃은 장애(상대 쪽 훅, 상대 쪽에서 문맥의 모든 QP를
오류로 만드는 사건)에서 한 쌍만 고치고 나머지를 ERR로 남긴다. 남은 쌍은 다음에 쓸 때 재시도 초과(약 3.5 s)를 거쳐서야 따로
복구되거나, 그 CQ를 아무도 보지 않으면 발견되지 않는다.

**질문.**
1. 응답 쪽이 범위 밖 자기 QP를 검사하고, RTS가 아닌 것이 있으면 좁히기를 거절해 전체 재설정으로 다시 돌게 하면, 상대 QP 오류
   셀이 어느 rank에도 RTS가 아닌 QP를 남기지 않는가.
2. 응답 쪽에만 범위 밖 고장 QP가 있는 경우(시작 쪽은 깨끗하다)도 같은가.
3. 응답 쪽이 깨끗할 때는 여전히 좁혀지고, 다른 문맥은 멈추지 않으며, Commit은 그대로이고, 검사 비용은 1 ms 이하인가.
4. 범위 충돌 뒤에 범위를 다시 정하면 높은 rank의 장애는 그 쌍만으로 복구되는가.
5. 응답 쪽이 자기 스위치(`NCCL_GIN_TS_PAIR_RESET=0`)를 따르는가.
6. 기존 복구 셀, 거절 셀, 장애 없는 지연은 그대로인가.

## 2. 가설

| id | 가설 | 다음이 관측되면 틀린 것이다 |
|---|---|---|
| H1 | 응답 쪽 검사와 거절, 전체 재설정 재실행은 상대 쪽이 여러 QP를 잃은 장애 뒤에 어느 rank에도 RTS가 아닌 QP를 남기지 않는다 | 상대 QP 오류 셀이나 응답 쪽 고장 셀에서 teardown 때 RTS가 아닌 QP가 하나라도 남은 시행이 있다. 또는 거절과 재실행이 9/10 미만이다. 또는 투명 복구가 9/10 미만이다 |
| H2 | 응답 쪽이 깨끗하면 라운드는 좁혀진 채이고 비용은 거의 그대로다 | 깨끗한 셀에서 좁혀진 시행이 9/10 미만이거나 거절이 나온다. 또는 다른 문맥이 1 ms 넘게 멈춘다. 또는 같은 hold에서 Commit 중앙값이 1.15배를 넘거나 라운드 전체 중앙값이 1 ms 넘게 는다 |
| H3 | 범위 충돌 뒤 다시 정한 범위는 높은 rank의 장애 쌍 하나다 | 충돌 셀에서 높은 rank의 재실행이 좁혀지지 않은 시행이 2회 이상이다 |
| H4 | 응답 쪽은 자기 스위치를 따른다 | 응답 쪽 스위치를 끈 대조에서 거절 없이 좁혀진 시행이 있다 |
| H5 | 기존 동작과 빠른 경로는 그대로다 | 재현 셀의 결과가 바뀐다. 또는 지연 차이가 예측 범위 밖이다 |

## 3. 사전 예측 (측정 전에 작성)

예측 원문은 [predictions.csv](predictions.csv)이고, 해시는 [PREREG.txt](PREREG.txt)에 있다. 25줄이다.
`kind`는 N(새 셀), R(재현), C(대조)다. 아래 판정 열, 로그 형식, 셀 키, 판정식 문법은 지금 고정한다.

### 3.1 판정에 쓰는 열

시행마다 한 줄이다. 열은 세 곳에서 온다.
- `../scripts/ts2/rows.py`의 열.
- gin-s2-close의 `../s2_close/rows_extra.py`가 붙이는 열. 정의는 `../s2_close/EXPERIMENT.md` 3.1절 그대로다.
- 이 폴더의 `rows_pc.py`가 붙이는 새 열.

**앞의 두 곳에서 쓰는 열.** 의미는 원래 정의 그대로다 `[소스]`.

| 열 | 내용 |
|---|---|
| `cell`, `build`, `iters` | 셀 이름, 빌드, 반복 수 |
| `transparent_ok` | 1 또는 0. 두 문맥 모드에서는 두 문맥을 합친 kv 키로 같은 정의를 적용한다(`../pair_reset/EXPERIMENT.md` 9절) |
| `r1rc`, `r1_outcome` | rank 1의 종료 코드와 드라이버 결과 |
| `decl_r0`, `decl_r1` | rank별 거절 사유. 여럿이면 `;`로 잇는다 |
| `teardown_r0`, `teardown_r1`, `teardown_ms_r1` | `ncclCommAbort` 반환 문자열(성공은 `no error`)과 걸린 시간 |
| `lat_p50_us` | 지연 p50 |
| `n_fires_r0`, `n_fires_r1`, `trigger_miss`, `bind_fail`, `ts_on_r0`, `ts_on_r1` | 장애 훅 발사 줄 수, 트리거 미도달, 랑데부 포트 충돌, 투명 복구 시작 줄 수 |
| `ua_r0`, `ua_r1`, `killed` | 받는 쪽 abort 플래그 줄 수, 상대 kill 기록 |

**`rows_pc.py`가 붙이는 열.** 새 로그 줄의 형식도 여기서 고정한다. 모든 시각은 `mono_ms`(CLOCK_MONOTONIC, ms)다. kv 파일은
`rows.py`와 같은 방법으로 읽는다(값에 빈칸이 있어도 다음 키 앞까지).

| 열 | 출처와 정의 |
|---|---|
| `pr_mode_r0`, `pr_mode_r1` | rank별 `GIN/TS: pair reset=<0\|1> rank=<r>`(gin-pair-reset의 시작 줄)의 값 |
| `pc_mode_r0`, `pc_mode_r1` | rank별 `GIN/TS: pair check=<0\|1> rank=<r>`(이 실험의 시작 줄)의 값. 줄이 없으면 빈칸 |
| `scope_r0`, `scope_reason_r0` | rank 0 첫 범위 결정 줄 `GIN/TS: rank <r>: round <n> peer <p> scope=<0x..> qps=<k> reason=<word> mono_ms=<t>`의 `scope`(문자열)와 `reason` |
| `n_dec_r0`, `last_reason_r0`, `n_dec_r1`, `last_reason_r1` | rank별 범위 결정 줄 수와 마지막 줄의 `reason` |
| `rec_scope_r0`, `rec_qps_r0`, `rec_scope_r1`, `rec_qps_r1` | rank별 첫 복구 줄(`GIN/TS: recovered`, 역할 무관)의 `scope`(문자열)와 `qps` |
| `n_rec_r0`, `n_rec_r1` | rank별 복구 줄 수(역할 무관) |
| `init_qps_r1` | rank 1의 첫 시작 쪽 복구 줄(`role=initiator`)의 `qps` |
| `commit_us_r0`, `total_us_r0` | rank 0의 첫 시작 쪽 복구 줄의 `commit_us`, `total_us`. 거절 뒤 재실행한 시행에서는 재실행 라운드의 값이다(거절된 시도는 복구 줄을 남기지 않는다) |
| `n_checked_r0`, `n_checked_r1` | rank별 응답 쪽 검사 수락 줄 수(아래 형식, `accepted`) |
| `check_us_r1` | rank 1의 첫 수락 줄의 `check_us` |
| `n_refused_r0`, `n_refused_r1` | rank별 응답 쪽 거절 줄 수(아래 형식, `refused`) |
| `refuse_reason_r1`, `not_rts_r1` | rank 1 첫 거절 줄의 `reason`과 `not_rts` |
| `n_rerun_r0` | rank 0의 재실행 줄 수(아래 형식) |
| `conflict_r1` | rank 1의 `GIN/TS: rank=<r> scope conflict:` 줄 수 |
| `ep_c<c>_r<r>` | rank r의 teardown 줄 `GIN/TS: rank <r> gate epochs to rank <p>: [<e0>,<e1>,...]`에서 문맥 c의 값(gin-pair-reset의 줄 그대로) |
| `qpst_r0`, `qpst_r1` | rank별 teardown 줄 `GIN/TS: rank <r> qp states to rank <p>: [<s0>,<s1>,...]`의 목록(문자열) |
| `n_notrts_r0`, `n_notrts_r1` | 위 목록에서 `3`(PRM의 RTS)이 아닌 항목 수(질의 실패 `?` 포함). 줄이 없으면 빈칸 |
| `inj_ctx_r0`, `inj_ctx_r1` | rank별 첫 장애 훅 발사 줄의 `context=<c>`. 없으면 빈칸(모든 문맥) |
| `r1_q4_in_stall` | 범위 충돌 셀만. 정의는 `../pair_reset/EXPERIMENT.md` 3.1절 그대로다 |
| `r1_fire_before_dec` | 응답 쪽 고장 셀만. rank 1의 첫 훅 발사 시각에서 `clock_offset_ms`(rank 0 kv)를 뺀 값이 rank 0의 첫 범위 결정 줄보다 앞서면 1, 아니면 0. 두 줄 중 하나가 없으면 빈칸 |
| `dual_r0`, `dual_r1` | rank별 kv `dual` |
| `dual_c1_in_win`, `dual_c1_max_in_win_us`, `dual_c1_end_after_win` | rank 0 kv의 같은 이름 키. 정의는 `../pair_reset/EXPERIMENT.md` 3.1절 그대로다 |
| `dual_c1_done`, `dual_c1_rc` | rank 0 kv의 문맥 1 완료 반복 수와 결과 문자열(성공은 `no error`) |

**새 로그 줄** `[소스, 9절의 변경으로 고정]`.

| 줄 | 형식 |
|---|---|
| 시작 | `GIN/TS: pair check=<0\|1> rank=<r>` |
| 범위 결정(시작 쪽) | gin-pair-reset 형식 그대로. `reason`은 `pair`, `off`, `ctx`, `queued`, `qp_state`, `peer`(응답 쪽 거절 뒤 재실행), `requeued`(같은 기록의 두 번째 충돌) 중 하나 |
| 응답 쪽 검사 수락 | `GIN/TS: rank <r>: REQ round <n> from rank <p> scope=<0x..> checked=<k> not_rts=0 check_us=<x> accepted mono_ms=<t>` |
| 응답 쪽 거절 | `GIN/TS: rank <r>: REQ round <n> from rank <p> scope=<0x..> checked=<k> not_rts=<j> check_us=<x> refused reason=<not_rts\|off> mono_ms=<t>`. `off`이면 검사하지 않으므로 `checked=0 not_rts=0 check_us=0` |
| 재실행(시작 쪽) | `GIN/TS: rank <r>: peer <p> refused the scope of round <n>; rerunning as a full reset mono_ms=<t>` |
| 범위 충돌(높은 rank) | `GIN/TS: rank=<r> scope conflict: REQ round <n> from rank <p> scope=<0x..>, ours scope=<0x..> round <m>; ours is requeued <for a new scope decision\|as a full reset>` |
| teardown QP 상태 | `GIN/TS: rank <r> qp states to rank <p>: [<s0>,<s1>,...]`. QUERY_QP의 PRM 상태(3은 RTS, 6은 ERR, 질의 실패는 `?`), 문맥 순서. 에폭 줄과 함께, 게이트를 막기 전에 남긴다 |

거절은 NACK 코드 12로 보낸다. 다른 거절 사유 문구는 그대로다.

### 3.2 셀 키와 판정식 문법

셀 키(`cell@build`), 판정 대상(8절 제외를 거친 시행), "자료 부족" 규칙, 판정식 문법(`count`, 빈칸 규칙, `has`,
`nonempty`, `median`, `abs`, `per cell:`)은 `../s2_close/EXPERIMENT.md` 3.2절과 같다. `count(...)`와 `median(...)` 밖의 나머지는
Python의 산술과 비교다(`../pair_reset/EXPERIMENT.md` 3.2절과 같음). 이 실험의 `score.py`는 `../s2_close/score.py`의 판정식 평가 함수를
그대로 불러 쓴다. 두 셀 키를 쓰는 판정식은 두 셀 모두 계획한 수를 채워야 판정한다. 판정은 맞음, 틀림, 자료 부족 중 하나다.

### 3.3 예측 요약

전체 판정식은 [predictions.csv](predictions.csv)에 있다. 아래는 요약이다.

| id | 셀 | 예측 | 판정 기준(요약) | 근거 |
|---|---|---|---|---|
| A1 | `f3_b@pc` | 기존 훅의 상대 QP 오류(rank 1의 QP 4개 고장)가 투명하게 복구된다 | ≥9/10 | `f3_b@pr` 5/5 `[측정]` |
| A2 | `f3_b@pc` | rank 1이 좁힌 범위를 한 번 거절하고(범위 밖 3개가 RTS 아님) rank 0이 전체 재설정으로 다시 돈다 | ≥9/10 | `f3_b@pr`에서 rank 0이 5/5 `pair`로 정함 `[측정]` |
| A3 | `f3_b@pc` | teardown 때 두 rank 모두 RTS가 아닌 QP가 없다 | 10/10 | `f3_b@pr`은 5/5 rank 1의 QP 3개를 남김 `[측정, 추론]` |
| B1 | `pc_dual_f1c0_r1c2_b@pcd` | rank 1의 쉬는 문맥 2 QP가 이미 고장 난 채로 rank 0 문맥 0 로컬 QP 오류가 투명하게 복구된다 | ≥9/10 | `pr_dual_f1c0_b@prd` 10/10 `[측정]` |
| B2 | `pc_dual_f1c0_r1c2_b@pcd` | rank 1이 거절하고(범위 밖 1개) rank 0이 전체 재설정으로 다시 돈다 | ≥9/10 | 9절 |
| B3 | `pc_dual_f1c0_r1c2_b@pcd` | teardown 때 두 rank 모두 RTS가 아닌 QP가 없다 | 10/10 | `pr`이면 rank 1 문맥 2가 남는다 `[추론]` |
| C1 | `pc_dual_f1c0_b@pcd` | 응답 쪽이 깨끗하면 투명하게 복구된다 | ≥9/10 | gin-pair-reset 10/10 `[측정]` |
| C2 | `pc_dual_f1c0_b@pcd` | 두 rank 모두 문맥 0으로 좁혀지고, rank 1은 검사 한 번 뒤 수락하며 거절은 없다 | ≥9/10 | 9절 |
| C3 | `pc_dual_f1c0_b@pcd` | 문맥 0이 묶인 동안 문맥 1이 돌고 그 창에 걸친 반복이 1 ms 이하다 | ≥9/10 | gin-pair-reset 10.7–11.2 µs `[측정]` |
| C4 | `pc_dual_f1c0_b@pcd` | 에폭은 두 rank 모두 `[2,0,…]`이고 teardown 때 모든 QP가 RTS다 | ≥9/10 | gin-pair-reset 10/10 `[측정]` |
| T1 | `pc_dual_f1c0_b@pcd` 대 `pr_dual_f1c0_b@prd` | 시작 쪽 Commit 중앙값 비 ≤ 1.15 | 같은 hold | `pr` 743–785 µs `[측정]` |
| T2 | 같음 | 시작 쪽 라운드 전체 중앙값 차이 ≤ 1 000 µs | 같은 hold | 검사는 QUERY_QP 3개 `[추론]` |
| E1 | `pc_bidirf_conflict_b@pc` | 다른 범위의 동시 시작이 모두 복구되고 거절이 없다 | ≥9/10 | gin-pair-reset 10/10 `[측정]` |
| E2 | `pc_bidirf_conflict_b@pc` | 충돌 뒤 rank 1이 범위를 다시 정해 문맥 1 쌍만 돌고, 에폭은 두 rank 모두 `[2,2,0,0]`이다 | ≥9/10 | `pr`은 11/11 `[4,2,2,2]` `[측정]` |
| E3 | `pc_bidirf_conflict_b@pc` | teardown 때 모든 QP가 RTS다 | ≥9/10 | 훅마다 QP 하나 |
| K1 | `f3_b_nocheck@pc` | 검사를 끄면 `pr`처럼 좁혀지고 rank 1에 RTS가 아닌 QP 3개가 남는다(측정이 결함을 본다) | ≥4/5 | `f3_b@pr` `[측정]` |
| K2 | `pc_dual_f1c0_r1off_b@pcd` | 응답 쪽 스위치를 끄면 `off`로 거절하고 전체 재설정으로 다시 돈다 | 5/5 | 코드 리뷰 nit 7 |
| K3 | `pr_dual_f1c0_b@prd` | `pr` 기준은 gin-pair-reset처럼 투명하고 좁혀진다 | 5/5 | gin-pair-reset `[측정]` |
| G1 | `f1_b`, `bidirf_sym_b`, `mt256_f1_b`(모두 `@pc`), `pc_dual_f3c0_b@pcd`, `pc_dual_f1all_b@pcd` | 복구 재현 셀이 그대로 투명하다 | 셀마다 5/5 | `pr` `[측정]` |
| G2 | 같음 | 복구 뒤 teardown 때 모든 QP가 RTS다 | 셀마다 5/5 | 훅이 깨는 QP를 라운드가 덮는다 |
| G3 | `pc_dual_f3c0_b@pcd` | 상대 쪽 문맥 0만 깬 상대 QP 오류는 거절 없이 좁혀진다 | 5/5 | gin-pair-reset P2b `[측정]` |
| G4 | `f4_b@pc` | 끊김 없는 kill은 죽음 원인으로 거절되고 살아남은 쪽 abort가 돌아온다 | 5/5 | `pr` 5/5 `[측정]` |
| G5 | `f2rel_b@pc` | 받는 쪽 abort 해제가 그대로다 | 5/5 | `pr` 5/5 `[측정]` |
| L1 | `lat_pc_on_4k@pc` 대 `lat_pr_on_4k@pr` | 4 KiB 지연 차이 0.40 µs 이하 | 같은 hold의 실행 중앙값 | 장치 코드와 드라이버가 같다 `[소스]` |
| L2 | `lat_pc_on_256k@pc` 대 `lat_pr_on_256k@pr` | 256 KiB 지연 차이 0.30 µs 이하 | 같음 | 같음 |

셀 조건은 7절에 있다.

## 4. 범위

**포함.**
- 9절의 라이브러리 변경 하나: 응답 쪽 검사와 거절(NACK 12), 시작 쪽의 전체 재설정 재실행, 응답 쪽 스위치 존중, 범위 충돌 뒤
  범위 다시 정하기, 모든 문맥과 같은 마스크를 0으로 바꾸기, teardown QP 상태 줄, 검사 스위치 `NCCL_GIN_TS_PAIR_CHECK`.
- 7절의 셀 18개.
  - 새 셀 4개: 기존 훅의 상대 QP 오류, 응답 쪽 고장, 깨끗한 응답 쪽, 범위 충돌.
  - 대조 셀 3개: 검사 끔, 응답 쪽 스위치 끔, `pr` 기준.
  - 재현 셀 7개.
  - 지연 셀 4개, 그중 2개는 `pr` 기준.

**제외.**
- 장치 코드와 드라이버 변경. `pcd`는 gin-pair-reset의 두 문맥 드라이버를 그대로 쓴다.
- RETRY_EXC를 늘 전체로 보는 규칙(코드 리뷰 항목 1의 다른 제안). 재시도 중인 요청 쪽 QP는 RTS이므로 QUERY_QP로는 보이지
  않는다. 이 실험은 QP 상태만 본다.
- 범위를 정한 뒤 GID가 옮겨진 경우(코드 리뷰 항목 2). 주소 변경은 하지 않는다.
- 다른 코드 리뷰 nit(32개 넘는 문맥, 시험 스위치의 숫자 검사, 이전 빌드와 섞어 쓰기).
- 3 rank 이상, 여러 GDAKI 문맥, 실제 관리망 장애, 링크 내리기, RoCE 주소 변경.
- 전제: 두 rank가 같은 devComm의 GIN 문맥에 같은 번호를 쓴다(`../pair_reset/EXPERIMENT.md` 4절). 드라이버는 communicator 하나만
  만든다.

## 5. 테스트베드와 버전

| 항목 | 값 | 확인 방법과 날짜 |
|---|---|---|
| 노드 | rain(rank 0, 보내는 쪽), sunny(rank 1, 받는 쪽) | 루트 `README.md` 테스트베드 표 |
| NIC와 펌웨어 | ConnectX-6 VPI, fw 20.43.4100. rain `mlx5_1`, sunny `mlx5_0` | `[측정]` 2026-10-06, `../../completion_contract/EXPERIMENT.md` 5절. hold 스냅숏에서 다시 기록 |
| 커널, OFED | rain 커널 5.15.0-97-generic. OFED | 커널 `[측정]` 2026-10-07. OFED `[미확인]` |
| GPU와 CUDA | rain Quadro RTX 5000(sm_75), sunny RTX A4000(sm_86), PeerMappingOverride=1, CUDA 12.8 | gin-s2-close 5절 |
| GIN 문맥 | 사용자 devComm의 GDAKI 문맥 하나에 GIN 문맥 4개, 문맥마다 상대 QP 1개 | `[측정]` gin-pair-reset 5절 |
| 기준 빌드 `pr`, `prd` | libnccl `51c2426c`, 드라이버 `d4b1f082`, `4926edee` | `[측정]` 2026-10-08 배포 때 두 노드 같음(`../pair_reset/deploy_check.txt`) |
| 이 실험의 빌드 `pc`, `pcd` | libnccl md5와 배포 확인 | `[미확인]` 빌드 전. 배포 때 기록 |

## 6. 변수

- **독립변수.**
  - 빌드: `pr`, `prd`, `pc`, `pcd`.
  - 검사 스위치 `NCCL_GIN_TS_PAIR_CHECK`(1 기본, 0). 범위 스위치 `NCCL_GIN_TS_PAIR_RESET`(rank별).
  - 장애 종류, 고장 낸 문맥과 rank(훅의 문맥 지정 유무), 장애 시각.
  - 트래픽: 두 문맥 모드, 기존 단방향, 양방향.
- **종속변수.** 3.1의 열이다.
  - 투명 여부, 거절 사유.
  - 범위 결정 줄, 응답 쪽 검사와 거절, 재실행, 복구 줄의 범위와 QP 수.
  - teardown 때 게이트 에폭과 QP 상태.
  - 다른 문맥의 창 안 반복, Commit과 라운드 시간, 검사 시간, 지연 p50.
- **통제변수.**
  - IB 타임아웃 14, GPU doorbell, 재연결 스위치 기본값(1).
  - 기존 셀 정의는 `../scripts/ts2/batch.sh`와 `../pair_reset/cells.sh` 그대로다(빌드만 `pc`, `pcd`).
  - 시행마다 프로세스를 새로 띄운다.

## 7. 실험 셀, 반복 수, 대조군

반복 수는 사전 등록 규칙(새 셀 10, 재현 5, 대조 5)을 따른다. 지연 셀의 반복은 실행 수다(실행마다 3000번 반복).
장애 훅의 지연은 각 rank의 GDAKI 문맥 생성부터 잰다. 두 rank의 문맥 생성은 수 ms 어긋날 수 있다. gin-pair-reset 범위 충돌 셀에서
같은 차이(5 ms)를 준 두 훅이 rank 0 시계로 5.8 ms와 19 ms 떨어져 발사됐다(n9, n10) `[측정]`. 아래 `inj`는 시행 번호 k에 대해
`400 + (k × 137) mod 700` ms다(두 문맥 셀). 기존 셀은 `batch.sh`의 정의를 따른다.

| 셀 | 조건 | 반복 수 | 대조군 여부 |
|---|---|--:|---|
| `f3_b@pc` | `batch.sh`의 `f3_b`(rank 1 `peer_err`, 문맥 지정 없음: rank 1의 QP 4개), 빌드 `pc`. 같은 hold에서 `f3_b_nocheck@pc`와 2:1로 섞어 돈다 | 10 | 새 셀 |
| `pc_dual_f1c0_r1c2_b@pcd` | 두 문맥 모드, 문맥마다 4 KiB × 3000, 간격 500 µs. rank 0 `local_err:inj`, 문맥 0 지정. rank 1 `local_err:inj−100`, 문맥 2 지정(트래픽 없는 QP) | 10 | 새 셀 |
| `pc_dual_f1c0_b@pcd` | `../pair_reset/cells.sh`의 `pr_dual_f1c0_b`와 같은 조건, 빌드 `pcd`. 같은 hold에서 `pr_dual_f1c0_b@prd`와 2:1로 섞어 돈다 | 10 | 새 셀 |
| `pc_bidirf_conflict_b@pc` | `../pair_reset/cells.sh`의 `pr_bidirf_conflict_b`와 같은 조건(rank 1 훅은 rank 0보다 5 ms 뒤), 빌드 `pc` | 10 | 새 셀 |
| `f3_b_nocheck@pc` | `f3_b@pc`와 같고 두 rank에 `NCCL_GIN_TS_PAIR_CHECK=0` | 5 | 대조 |
| `pc_dual_f1c0_r1off_b@pcd` | `pc_dual_f1c0_b@pcd`와 같고 rank 1에만 `NCCL_GIN_TS_PAIR_RESET=0` | 5 | 대조 |
| `pr_dual_f1c0_b@prd` | `../pair_reset/cells.sh`의 정의 그대로(`pr` 기준) | 5 | 대조 |
| `f1_b@pc`, `bidirf_sym_b@pc`, `mt256_f1_b@pc`, `f4_b@pc` | `batch.sh`의 기존 정의, 빌드 `pc` | 각 5 | 재현 |
| `f2rel_b@pc` | `../pair_reset/cells.sh`의 `f2rel_b`와 같은 조건, 빌드 `pc` | 5 | 재현 |
| `pc_dual_f3c0_b@pcd`, `pc_dual_f1all_b@pcd` | `../pair_reset/cells.sh`의 `pr_dual_f3c0_b`, `pr_dual_f1all_b`와 같은 조건, 빌드 `pcd` | 각 5 | 재현 |
| `lat_pr_on_4k@pr`, `lat_pr_on_256k@pr` | `../pair_reset/cells.sh`의 정의. 아래 두 셀과 같은 hold에서 섞어 돈다 | 각 5 | 재현(지연 기준) |
| `lat_pc_on_4k@pc`, `lat_pc_on_256k@pc` | 투명 복구 켬, 장애 없음, 3000번 반복 | 각 5 | 대조 |

**합계.**

| 종류 | 셀 시행 | 지연 실행 |
|---|--:|--:|
| 새 셀 | 40 | |
| 재현 | 35 | 10 |
| 대조 | 15 | 10 |
| 합 | 90 | 20 |

## 8. 제외 기준과 중단 기준

**제외 기준.** 제외한 시행은 셀별로 따로 세어 보고한다.
- smoke 실행(`results/<날짜>_smoke/`)은 채점하지 않는다.
- NCCL 초기화 전 실패(`bind_fail == 1`)는 제외하고 다음 번호로 계획한 반복 수를 채운다.
- 장애 미적용은 제외하고 다음 번호로 채운다.
  - 로컬 QP 오류 셀(rank 0 훅 하나: `pc_dual_f1c0_b`, `pc_dual_f1c0_r1off_b`, `pr_dual_f1c0_b`, `pc_dual_f1all_b`, `f1_b`,
    `mt256_f1_b`)에서 `n_fires_r0 == 0`.
  - 상대 QP 오류 셀(`f3_b`, `f3_b_nocheck`, `pc_dual_f3c0_b`)에서 `n_fires_r1 == 0`.
  - 두 rank 훅 셀(`pc_dual_f1c0_r1c2_b`, `pc_bidirf_conflict_b`, `bidirf_sym_b`)에서 `n_fires_r0 == 0` 또는 `n_fires_r1 == 0`.
  - `trigger_miss > 0`. kill 셀에서 `killed != 1`.
- 조건 미적용은 제외하고 다음 번호로 채운다.
  - `pc_dual_f1c0_b`에서 문맥 1이 모든 반복을 성공으로 마쳤는데(`dual_c1_done == iters`, `dual_c1_rc == "no error"`) 그
    마지막 반복이 묶인 창보다 먼저 끝났다(`dual_c1_end_after_win == 0`). 문맥 1이 실패했거나 kv 키가 없으면 제외하지 않고 예측에
    반하는 시행으로 센다(gin-pair-reset 코드 리뷰 항목 3).
  - `pc_bidirf_conflict_b`에서 `r1_q4_in_stall != 1`.
  - `pc_dual_f1c0_r1c2_b`에서 `r1_fire_before_dec != 1`. rank 1의 문맥 2가 rank 0의 범위 결정 전에 고장 나지 않으면 이 셀의
    조건이 만들어지지 않는다.
- 채우려고 다시 돈 시행이 셀마다 계획의 50%를 넘으면 그 셀은 멈추고 "자료 부족"으로 둔다.

**설정 확인.** 하나라도 어긋나면 제외가 아니라 그 블록을 멈춘다.
- 투명 복구를 켠 시행은 `ts_on_r0 >= 1`, `ts_on_r1 >= 1`, `ua_r0 >= 1`, `ua_r1 >= 1`이어야 한다.
- `pc`, `pcd`, `pr`, `prd` 시행은 `pr_mode_r0 == 1`이어야 하고, `pr_mode_r1`은 `pc_dual_f1c0_r1off_b`에서 0, 나머지에서 1이어야 한다.
- `pc`, `pcd` 시행은 `pc_mode_r0`, `pc_mode_r1`이 `f3_b_nocheck`에서 0, 나머지에서 1이어야 한다.
- `pcd`, `prd` 시행은 `dual_r0 == 1`, `dual_r1 == 1`이어야 한다.
- 문맥 지정: `pc_dual_f1c0_b`, `pc_dual_f1c0_r1off_b`, `pr_dual_f1c0_b`는 `inj_ctx_r0 == 0`, `pc_dual_f3c0_b`는 `inj_ctx_r1 == 0`,
  `pc_dual_f1c0_r1c2_b`는 `inj_ctx_r0 == 0`이고 `inj_ctx_r1 == 2`, `pc_bidirf_conflict_b`는 `inj_ctx_r0 == 0`이고 `inj_ctx_r1 == 1`,
  `pc_dual_f1all_b`, `f3_b`, `f3_b_nocheck`는 훅을 단 rank의 `inj_ctx`가 빈칸이어야 한다.

**smoke에서 구현 결함이 보일 때.** 다음 중 하나가 보이면 구현 결함으로 본다. 본 실행 전에 코드를 고칠 수 있고, 그 변경은
`DEVIATIONS.md`에 적는다. 예측, 판정식, 셀 조건은 바꾸지 않는다.
- `f3_b@pc` smoke에서 거절과 재실행이 없거나, teardown 때 RTS가 아닌 QP가 남았다.
- `pc_dual_f1c0_b@pcd` smoke 2회 모두 좁혀지지 않았다.
- teardown QP 상태 줄이 없다.

예외로, 응답 쪽 고장 셀의 smoke 2회 모두 `r1_fire_before_dec != 1`이면 rank 1 훅의 앞섬(100 ms)을 본 실행 전에 한 번 바꿀 수 있다.
범위 충돌 셀도 smoke 2회 모두 `r1_q4_in_stall != 1`이면 rank 1 훅의 지연(5 ms)을 한 번 바꿀 수 있다. 바꾼 값과 시각, 이유는
`DEVIATIONS.md`에 적는다.

**중단 기준.**
- **잠금.** 모든 클러스터 명령은 `harness/gpu-initiated/common/cluster_run.sh -w 10800` 안에서 돈다. 다른 실험(살아 있는 상대 경계
  실험의 CPU 하네스와 GIN v2)이 같은 잠금을 쓴다.
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

  rain에는 이 실험 전부터 명령 오류 줄 2개(2026-09-25)가 있고 펌웨어 명령 실패 수는 31이다(2026-10-08 gin-pair-reset hold 스냅숏)
  `[측정]`. hold 앞뒤의 증가로 판단한다.
- **배포.** 새 번들은 새 디렉터리 `$HOME/gi-bundle/gin_ts2/pc/`와 `pcd/`에만 둔다.
  - 대상 파일이 이미 있으면 배포 스크립트가 멈춘다.
  - 배포 뒤 기존 번들 파일(최종, `s1/`, `base/`, `var_sys/`, `s2r/`, `s2rget/`, `rc/`, `rc_smoke_1193a5f8/`, `pr/`, `prd/`)의 md5가 두
    노드에서 그대로인지 확인한다.

## 9. 실행 방법과 경로

**라이브러리 변경.** 아직 하지 않았고 빌드도 하지 않았다. 사전 등록 뒤에 한다. 대상은 `src/transport/net_ib/gdaki/gin_host_gdaki.cc`
하나다(헤더와 장치 코드는 그대로). 변경분은 `pc_layer.diff`(`pr` 트리 기준)와 전체 diff `gin_transparent_pc.diff`(pristine 기준)로
남긴다.
1. **스위치와 시작 줄.** `NCCL_GIN_TS_PAIR_CHECK=0|1`(기본 1). helper 시작 때 시작 줄(3.1)을 남긴다.
2. **응답 쪽 검사.** 좁힌 범위(REQ의 범위가 0이 아님)의 REQ에 응답하기 전, 게시 멈춤 전에 한다.
   - 자기 `NCCL_GIN_TS_PAIR_RESET`이 0이면 검사 없이 거절한다(`reason=off`).
   - 검사 스위치가 1이면 같은 상대로 가는 자기 QP 중 범위 밖의 것을 모두 QUERY_QP로 본다(`opMu` 안에서, 시작 쪽의 범위 결정과
     같은 방법). PRM 상태가 RTS가 아니거나 질의가 실패한 것이 하나라도 있으면 거절한다(`reason=not_rts`). 모두 RTS면 수락 줄을
     남기고 지금처럼 응답한다.
   - 검사 스위치가 0이면 검사하지 않고 지금처럼 응답한다.
   - 거절은 NACK 코드 12를 그 REQ의 라운드 번호로 보내는 것뿐이다. 거절하는 쪽은 아무것도 멈추거나 바꾸지 않고, 그 상대를
     거절(decline)하지도 않는다. 거절 줄(3.1)을 남긴다.
3. **시작 쪽의 재실행.** ACK를 기다리다 자기 라운드에 대한 NACK 12를 받으면, 그리고 그 라운드가 좁힌 라운드였으면 다음을 한다.
   - 자기 Prepare를 푼다(`ncclGinRecoverAbort`). 범위 안 QP는 ERR이고 게이트는 닫힌 채다.
   - 재실행 줄(3.1)을 남기고, 그 장애 기록에 "상대가 거절함" 표시를 달아 대기열 앞에 다시 넣는다.
   - 다음 helper 반복에서 그 기록은 범위 결정에서 늘 전체가 된다(`reason=peer`). 전체 REQ(범위 0)는 응답 쪽이 거절하지 않는다.
   - 좁히지 않은 라운드에 NACK 12가 오면 지금처럼 "peer NACK"으로 거절한다.
4. **토큰 일관성** `[소스, 추론]`. 거절은 응답 쪽이 Prepare 전에 하므로, 두 rank가 서로 다른 범위로 Prepare한 상태는 생기지 않는다.
   재실행은 새 라운드 번호와 새 토큰으로 처음부터 한다. Commit의 토큰 검사(1740–1758행)는 그대로다.
5. **동시 시작.**
   - 높은 rank가 같은 범위로 물러날 때(gin-pair-reset의 물러남 경로, 3510–3513행): 물러나기 전에 2번의 검사를 한다. 거절하면
     자기 Prepare를 풀고, 자기 기록을 다시 정하도록 대기열에 넣고, 낮은 rank에 NACK 12를 보낸다. 낮은 rank는 3번대로 전체로 다시 돈다.
   - 범위가 다를 때(충돌 경로, 3491–3503행): 지금처럼 자기 Prepare를 풀고 낮은 rank의 REQ에 처음부터 응답한다. 이 응답에도 2번의
     검사가 적용된다.
   - 다시 넣는 자기 기록은 "전체" 표시 없이 충돌 횟수만 하나 올린다. 다음 범위 결정은 보통 규칙대로 한다(코드 리뷰 항목 5).
     같은 기록이 두 번째 충돌을 만나면 그때는 전체로 한다(`reason=requeued`). 충돌 줄의 끝 문구가 둘을 구분한다(3.1).
6. **마스크 정리.** 범위 결정이 모든 문맥과 같은 마스크를 내면(문맥이 하나인 경우) 범위 0(전체)으로 보낸다(코드 리뷰 nit 7).
7. **teardown QP 상태 줄.** gin-pair-reset의 에폭 줄 바로 뒤, 게이트를 막기 전에 gated 상대마다 그 상대로 가는 QP를 모두 QUERY_QP로
   읽어 남긴다(3.1). helper, watcher, 훅 스레드를 모두 기다린 뒤라 QP 상태 변경과 겹치지 않는다.

**드라이버.** 바꾸지 않는다. `pc`는 `d4b1f082`, `pcd`는 gin-pair-reset의 두 문맥 드라이버 `4926edee`를 복사한다.

**빌드.** 세션 스크래치 `$SCR`(`/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad`)에서 한다.
1. `agent_ts2pr`의 트리와 빌드 디렉터리를 `agent_ts2pc`로 복사한다. 의존 파일과 장치 manifest의 경로를 바꾸고 원래 시각을
   돌려준다(gin-pair-reset `build_pr.sh`와 같은 방식).
2. 스크래치 저장소에 `pr` 상태를 커밋하고 `pc_layer.diff`를 적용한다.
3. `make -n`으로 다시 컴파일되는 파일이 `gin_host_gdaki.cc`와 버전 표시뿐인지 확인한 뒤 증분 빌드한다.

이 폴더에 둘 스크립트는 `build_pc.sh`, `make_diff_pc.sh`, `deploy_pc.sh`다. 전체 diff로 pristine에서 트리가 재현되는지 확인한다.

**배포.** `deploy_pc.sh`로 두 노드의 `pc/`, `pcd/`에 둔다. 대상 파일이 있으면 멈추고, 두 노드 md5, `ldd`, 기존 번들 md5를
확인한다(8절). 확인 출력은 잘리지 않게 파일로만 받는다.

**실행.**
- `../scripts/ts2/run_trial.sh`를 그대로 쓴다. 두 문맥 모드는 `EXTRA_ENV="GIN_TS_DUAL=1"`로, 문맥 지정은 `R0_ENV`나 `R1_ENV`로 준다.
- 기존 셀은 `BUILD=pc bash ../scripts/ts2/batch.sh`로, `pr`과 `prd` 기준 셀은 `../pair_reset/cells.sh`로 돈다.
- 새 셀, 대조 셀, `pc`와 `pcd` 셀, `f2rel_b@pc`는 이 폴더의 `cells.sh`가 7절 조건대로 정의한다.
- hold는 이 폴더의 `hold.sh`에 두고, 각 hold를 `chain.sh`로 따로 `cluster_run.sh -w 10800 -t gpc-<hold>`에 넣는다.

| hold | 내용 | 추정 `[추론]` |
|---|---|---|
| H0 smoke | 새 셀 4개(응답 쪽 고장과 범위 충돌은 2회, 깨끗한 응답 쪽 2회), 대조 셀 3개, `f3_b@pc` 2회, 지연 `pc`와 `pr` 4 KiB 1회씩 | 5분 |
| H1 | 지연 4셀 × 5(섞어서), 재현 셀 `f1_b`, `bidirf_sym_b`, `mt256_f1_b`, `f4_b`, `f2rel_b` × 5 | 7분 |
| H2 | `pc_dual_f1c0_b` 10회와 `pr_dual_f1c0_b` 5회(2:1로 섞어서), `pc_dual_f1c0_r1c2_b` 10회, `pc_dual_f1c0_r1off_b` 5회 | 4분 |
| H3 | `f3_b@pc` 10회와 `f3_b_nocheck@pc` 5회(2:1로 섞어서), `pc_dual_f3c0_b` 5회, `pc_dual_f1all_b` 5회 | 6분 |
| H4 | `pc_bidirf_conflict_b` 10회 | 2분 |

hold마다 잠금과 유휴 확인이 약 1분 더 든다. 클러스터 시간은 모두 30–40분이다 `[추론]`.

**채점.**
1. `../scripts/ts2/rows.py`로 hold 폴더마다 시행 CSV를 만든다.
2. `../s2_close/rows_extra.py`와 이 폴더의 `rows_pc.py`가 3.1의 열을 붙인다.
3. 이 폴더의 `score.py`가 [predictions.csv](predictions.csv)의 판정식을 3.2 문법대로 적용한다. 결과는
   `results/<날짜>/SCORE.md`와 `results/<날짜>/trials_scored.csv`다.

**출력.** 결과 폴더 `results/<날짜>/<hold 폴더>/`. 원시 로그는 Release에 올린다.

## 10. 완료 조건과 QA 기준

- [ ] 모든 셀이 계획한 반복 수만큼 실행됐다. 제외와 실패를 따로 센 표가 있다.
- [ ] 예측 25줄마다 판정(맞음, 틀림, 자료 부족)과 놓친 시행 목록이 있다.
- [ ] 다른 에이전트가 `score.py`를 보지 않고 원자료에서 핵심 수치를 다시 셌다. 대상은 거절과 재실행, 범위와 QP 수, teardown
  QP 상태와 에폭, 문맥 1의 창 안 반복, Commit과 라운드 시간, 투명 여부다.
- [ ] 다른 에이전트가 `pc_layer.diff`를 읽고 리뷰했다.
- [ ] smoke와 제외 시행이 결과에 섞이지 않았다.
- [ ] 새 빌드의 md5, 전체 diff, pristine + diff 확인 결과를 5절에 적었다.
- [ ] 원자료를 Release에 올리고 `DATA.md`에 적었다.
- [ ] hold 전후 mlx5 스냅숏에 새 명령 오류가 없었거나, 있었다면 그 줄의 내용을 12절에 적었다.

## 11. 작업 체크리스트

- [x] 질문, 가설, 셀 작성 (`DRAFT`)
- [x] 고정 절 완성, 상태 `PREREGISTERED`, 해시 기록을 커밋 하나로 만들고 그 커밋에 `prereg/` 태그
- [ ] 코드 변경, 빌드, 배포
- [ ] `cells.sh`, `hold.sh`, `chain.sh`, `rows_pc.py`, `score.py`
- [ ] smoke 실행(채점 제외)
- [ ] 본 실행 (`RUNNING`)
- [ ] 채점 (`QA`)
- [ ] 독립 재계산과 코드 리뷰
- [ ] 결과 정리, 원자료 릴리스, PR
- [ ] 결론 확정 (`COMPLETE`)

## 12. 실행 기록 (시간순)

| 시각 | 무엇을 했나 | 결과와 근거(경로, 커밋, 실행 ID) |
|---|---|---|
| 2026-10-08 | gin-pair-reset의 결과표와 코드 리뷰에서 기준 수치를 다시 셈 `[측정]`. `f3_b@pr` 5회는 두 rank 에폭 `[2,0,0,0]`, `qps=1`. `pr_dual_f1c0_b@prd` 10회의 시작 쪽 Commit 743–785 µs(중앙값 768), 라운드 전체 2 934–3 093 µs(중앙값 3 013). 범위 충돌 rank 1 재실행 Commit 3 612–3 787 µs와 에폭 `[4,2,2,2]`(코드 리뷰 항목 5) | `../pair_reset/results/20261008/trials_scored.csv`, `../pair_reset/qa/code_review.md` |
| 2026-10-08 | 코드를 읽고 설계를 정함 `[추론]`. 응답 쪽이 Prepare 전에 거절하면 두 rank가 다른 범위로 Prepare한 상태가 생기지 않으므로, 넓혀서 답하기보다 거절과 재실행을 택했다 | 9절 |
| 2026-10-08 | 사용자가 이 후속 실험을 승인 | |
| 2026-10-08 13:51:48 | 사전 등록 | [PREREG.txt](PREREG.txt), 태그 `prereg/gin-pair-check-v1` |

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

- `../pair_reset/EXPERIMENT.md`, `../pair_reset/qa/code_review.md`(gin-pair-reset, 이 실험의 기준 빌드 `pr`)
- `../reconnect/EXPERIMENT.md`(gin-reconnect)
- `../s2_close/EXPERIMENT.md` 3.2절(판정식 문법)
