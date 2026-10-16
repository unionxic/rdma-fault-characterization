# gin-control 통합: 고친 준비 단계 + 1단계 + 2단계 2a-1 (작업 기록)

## 단계 목록 (처음에 적은 계획)

1. `agent_gc_int/`: `agent_gc_prep`의 nccl-src와 빌드 넷을 복사, 고친 준비 단계를 "gin-control prep-fix (gc_layer.diff 0df79ae2)"로 커밋
2. `build_gc.sh`: `int` 키(머리 커밋 이름, 1단계와 2a-1 시험), `p1`, `p2` 키, `gc_unit_p1`/`gate_fenced`/`gc_unit_p2` unit 단계
3. 1단계 diff를 3-way로 적용, 충돌 풀기(붙인 블록, 준비 영역, `#if` 자리)
4. 1단계 자리 표시를 헤더 판으로 바꾸고 중복 지움(`gdakiCtrlChanUp` 두 인자, `ConfirmP1`, 판정 enum, `gdakiLnFenceOf`, `gdakiCtrlActFenceOk`)
5. 판정 함수를 헤더의 `gdakiCtrlJudge` 틀에 묶음, 21행 "닿지 않음" 주석; `gc_unit_p1.cc` 맞춤
6. 2a-1 diff를 3-way로 적용, 충돌 풀기; 지역 `#define`, 자체 nrp put/get 지우고 헤더 판 사용
7. `gc_unit_p2.cc` 맞춤(헤더 이름)
8. `repaste`, `api`, `sites`(필요하면 `gc_sites.tsv`)
9. 빌드 넷(gc, gcp, gct, gctp), 경고 0
10. `pre`(gct, gctp, gctc 0 hunk), `unit` 두 빌드, `ident`
11. `diff` → `gc_layer_int.diff`, `info`
12. 이 문서 마무리(충돌, 중복, 헤더 항목, 수, 표, 다음 단계, EXPERIMENT 11/12절 안)

## 끝낸 단계 (한 단계 한 줄)

- 1 끝: `agent_gc_int/`에 `agent_gc_prep`의 nccl-src와 빌드 넷 복사(옛 out/ 빼고), .d와 manifest의 경로 다시 씀, 작업 트리 diff가 `0df79ae2`임을 보고 "gin-control prep-fix (gc_layer.diff 0df79ae2)"로 커밋(2fc04b6)
- 3 끝: `git merge-file --diff3`(바탕 옛 준비 단계 f065d35, 우리 고친 준비 단계, 그쪽 1단계): 충돌 3(준비 영역의 "[1] page" 하위 영역, "[3] launcher" 끝, `gdakiCtrlFree`), 모두 고친 준비 단계 쪽으로
- 4–5 끝: 1단계 자리 표시와 중복을 지우고 헤더 판으로 묶음, 판정 표를 헤더 "[1] page" 하위 블록의 `gdakiCtrlJudge`로 옮김(21행 "닿지 않음" 주석), `gc_unit_p1.cc` 맞춤
- 6–7 끝: 2a-1 3-way 적용, 충돌 1(준비 영역 끝 뒤에 두 단계가 함께 넣은 자리: 1단계 영역, 그다음 2a-1 verbs 뒤끝); 지역 `#define`과 nrp put/get 지움, CONNECTED를 헤더의 봉투 종류 6으로; `gc_unit_p2.cc` 맞춤
- 2 끝: `build_gc.sh`에 `int`, `p1`, `p2` 키, unit의 1단계와 2a-1 시험, `unitp1`, `unitp2`, `syn`, `sites`의 단계 영역 셈(`#use` 줄)
- 8 끝: `repaste`(헤더 "[1] page" 하위 블록에 판정 표를 넣은 판), `api` 통과, `syn` 세 빌드 통과; `sites`는 처음에 단계 영역의 쓰임 셋에서 MISMATCH → 표에 `#use` 줄 셋을 더해 통과
- 9 끝: gc, gcp, gct, gctp 빌드됨(경고 0, 호스트 파일 하나만 다시 컴파일, 장치 객체 다시 빌드 없음)
- 10 끝(첫 판, 리뷰 전): `pre` gct, gctp 0 hunk, gctc 2 hunk 3줄(1단계의 RST 거절 간격, `NCCL_GIN_CTRL_TCP_CELLS` 뒤: 헤더 머리 주석이 정한 "gctc는 그 코드만큼 다름"), `unit` 두 빌드 통과. 로그는 `logs_int/before_review/`
- 11 끝(첫 판): `diff`를 ln4 커밋 대비 전체 층으로 고침(처음엔 머리 커밋 대비라 단계 몫만 나왔음), `tree()`가 깨끗한 int 트리에 그 diff를 다시 놓는 길(`gc_layer.diff` 거꾸로, 그다음 int diff)을 던질 worktree로 확인. 첫 판의 ident는 리뷰 통보로 멈춤(내가 띄운 것만 끔)
- 12(리뷰 통보 뒤): REVIEW_P12 "통합이 볼 것"의 통합 항목 반영: `r->ctrl` 만들기를 all-gather 앞으로, 1단계와 2a-1 영역을 준비 영역의 "[1] page", "[2] ring" 하위 영역 안으로(제자리), 생존 READ의 `wr_id`에 세대, 페이지 배치의 launcher 수 칸(`nLaunchers`), 헤더 LATER 기본 1 000, 2a-1의 `probeGen` 주석; `repaste`, `api`, `syn`, `sites`, `unit` 다시 통과
- 13: 빌드 넷, `pre`, `ident`, `diff`, `info`를 마지막 트리로 다시 돌림(아래 표)

## 무엇을 했나

worktree HEAD `21295000` 위에서 한 일이다. 트리는 스크래치 `agent_gc_int/`(ln4 커밋 f53e5d2, 그 위 "gin-control prep-fix (gc_layer.diff 0df79ae2)" 커밋 2fc04b6, 작업 트리에 1단계와 2a-1). 호스트 파일 하나만 바뀌고 장치 코드는 0줄이다. 클러스터, ssh, verbs 장치, GPU 실행은 없다. `git add`, commit, push는 하지 않았다. 표시: [측정] 이 작업이 돌려서 본 것, [추론] 해석, [미확인] 확인 안 함.

### 충돌과 푼 방법

| 어디 | 무엇 | 푼 방법 |
|---|---|---|
| 1단계 1 | 준비 영역 "[1] page" 하위 영역(고친 판: 자리 표시 넷; 1단계: 옛 자리 표시 지움) | 고친 준비 단계 쪽. 그 뒤 하위 영역의 자리 표시 넷을 지우고 1단계 영역 전체를 그 하위 영역 안으로 옮김(제자리 바꿈, REVIEW_P12 통합 1단계 8) |
| 1단계 2 | "[3] launcher" 하위 영역 끝(1단계가 옛 `gdakiLnFenced` 자리 표시를 지운 자리) | 고친 준비 단계 쪽(`gdakiCtrlLauncherFree`와 끝 표시) |
| 1단계 3 | `gdakiCtrlFree`(고친 판: free hook 셋; 1단계: `gdakiPageFree`) | 고친 준비 단계 쪽. 1단계의 `gdakiPageFree`는 `gdakiCtrlPageFree`로 이름을 바꿔 hook이 됨 |
| 2a-1 1 | 준비 영역 끝 바로 뒤(1단계 영역과 2a-1 verbs 뒤끝이 같은 자리에 들어옴) | 둘 다 둠. 그 뒤 2a-1의 모형 영역(처음엔 seams 블록 뒤)과 verbs 뒤끝을 준비 영역 "[2] ring" 하위 영역 끝(준비 단계의 갈아 끼우는 자리 본문 아래)으로 옮김(REVIEW_P12 통합 2a-1 4) |
| 겉으로 충돌 없음 | `#if` 자리(`gdakiHoldOnMsg`, `gdakiHoldDrain`, `gdakiTsRefused`, `gdakiQ4Watch`, `gdakiTsStart`), 붙인 블록 | 3-way가 그대로 합침. 붙인 블록은 `repaste`로 헤더 판을 다시 붙임 |

### 중복이라 지운 것 (헤더나 고친 준비 단계가 이김)

1단계:
- 판정 입력 enum L, B, W, R과 판정 값 V(헤더 이름으로: `W_NORMAL`→`W_OK`, `W_WINDOW`→`W_OPEN`, `W_CW_*`→`W_END_*`, `B_BYE`→`B_SEEN`, `R_RISING`→`R_ROSE`, `R_STALE_BELOW`→`R_STALE_LT_SUSPECT`, `R_STALE_GUARD`→`R_STALE_GUARDED`, `R_HELPER_GUARD`→`R_HELPER_GUARDED`, `R_HWNORESP`→`R_HW_NORESP`, `R_TIMEOUT`→`R_TIMEOUT_ONLY`, `R_CANNOT_CONFIRM`→`R_UNCONFIRMED`, `*_MAX`→`*_N`).
- `gdakiCtrlJudgeRow`, `gdakiCtrlRowVerdict`, `gdakiCtrlCauseName(row)`: 표는 헤더 `gdakiCtrlJudge`로 옮김(아래 헤더 항목). 1단계의 판정 값은 8과 20, 14와 15를 합쳤고 10을 REFUSE로 두었으므로 그대로 옮기지 않고 9.3절 판정 열대로 헤더 값(`V_ALIVE_WITNESS_LOST`, `V_UNREACHABLE`, `V_RDMA_PATH`, `V_STALL_HELPER`, `V_ALIVE`)을 씀.
- `gdakiCtrlConfirmP1`, 1단계의 `gdakiCtrlBeatAdvanced`(헤더와 같은 서명): 헤더 `gdakiCtrlConfirmVerdict`(incarnation 입력 셋).
- `gdakiLnFenceOf(view, …)`, `GDAKI_CTRL_FN_*`, 1단계의 `gdakiLnFenceName`: 헤더 `gdakiLnFenceOf(phase, dead, word, sent)`, `GDAKI_LN_FENCE_*`.
- `GDAKI_CTRL_P_LATER_MS`, `GDAKI_CTRL_LATER_MS_DEFAULT`(1000), `GDAKI_CTRL_P_LAUNCHER_STALL_MS`, `GDAKI_CTRL_LAUNCHER_STALL_MS_DEFAULT`의 재정의.
- 두 인자 `gdakiCtrlChanUp(r, peer)` 자리 표시(`gated && !gone`): 고친 준비 단계의 seam(`fd >= 0 && !gone` 판)으로.
- 준비 단계 "[1] page" 자리 표시 넷(`gdakiProbeToErr`, `gdakiLnFenced`, `gdakiCtrlActFenceOk`, `gdakiCtrlPageFree`): 1단계 몸이 같은 하위 영역 안에서 대신함. 437행 근처 앞 선언 가운데 `gdakiPageFree`.
- `gdakiCtrlStateOf`(고친 판에 없음): `r->ctrl`을 바로 쓰고 null이면 아무것도 안 함.

2a-1:
- `#define GDAKI_CTRL_PAIR_STEP_DONE 3u`: 헤더 enum.
- 자체 `gdakiCtrlNrpPut`(반환형만 달라 재정의 오류), `gdakiCtrlNrpGet(…, isAck)`: 헤더 put/get + 모형의 검사 함수 `gdakiCtrlRejoinNrpOk(n, isAck)`(gen, `probeGen` 0 아님, 끝점 셋, QPN 다름).
- 기록 QP의 CONNECTED를 PAIR 본문(step DONE)으로 실어 보내던 것: 헤더 봉투 종류 `GDAKI_CTRL_K_CONNECTED`(6, 본문 0 B, seq 1). 받는 쪽은 kind 6만 받고 기록 QP의 PAIR는 잃음(`BADPAIR`)으로. 생존 READ QP의 PAIR_DONE은 지금처럼 UD의 PAIR step 3.
- 결정 10 "두 종류 모두 max + 1": 헤더 `probeGen`(종류마다 자기 세대). 코드에는 그 셈이 없고 주석만 고침.

### 헤더 항목 (`rs_ctrl_api.h`)

| 요청 | 상태 |
|---|---|
| `rs_ctrl_api_p2.diff` 1: `GDAKI_CTRL_PAIR_STEP_DONE = 3` | 이미 있음(고친 헤더) |
| `rs_ctrl_api_p2.diff` 2: nrp 생존 READ 세대 칸, 168 B | 이미 있음(`probeGen`, `rsv`; `genPrb`와 같은 자리). diff는 적용하지 않음 |
| notes_p1 3절 1: 판정 함수와 입력 enum을 헤더로 | enum과 틀은 있었음. 표의 몸은 없었으므로 **헤더를 고침**: "[1] page" 하위 블록에 `gdakiCtrlJudgementOfRow(row)`(행 → 판정 값, 원인), `gdakiCtrlJudge(L, B, W, R)`(21행, 첫 일치; 21행에 "닿지 않음" 주석), `gdakiCtrlCauseName(cause)` |
| 3절 2: `gdakiLnFenceOf`와 이름 | 이미 있음 |
| 3절 3: 확인 창 incNonce와 감싸는 비교, 주석 | 이미 있음 |
| 3절 4: 보고 줄 둘째 꼴(`gdakiCtrlLineSnapshotOk2`) 빼기 | 하지 않음: `gc_unit_prep.cc`가 그 함수를 시험함(540–542행). 1단계는 첫 꼴을 씀. 빼기는 조율 세션 결정으로 남김 |
| 3절 5: 보고 줄 칸(상대마다 두 낱말) | 하지 않음: 1단계가 보고 줄을 쓰지 않음. 2단계와 헤더 몫으로 남김 |
| 3절 6: 채널 seam | 묶음(고친 준비 단계의 두 인자 seam) |
| 3절 7: 활성화 관문 | 이미 묶여 있었음(고친 준비 단계가 `gdakiHoldActivateDecide`에서 부름). 1단계 몸이 대신함; `launcherPaired`는 3단계 |
| 3절 8: 둘째 매크로 이름 | 코드는 `NCCL_GIN_CTRL_TCP_CELLS`/`gctc` 그대로; 문서 고침은 조율 세션(prep-fix 고칠 것 15와 같음) |
| REVIEW_P12 고칠 것 18: LATER 기본 | **헤더를 고침**: `GDAKI_CTRL_LATER_MS_DEFAULT` 5000 → 1000(조율 세션 지시), 1단계 재정의 지움 |

헤더 판: `998b493b`(1 022줄) → `948b3ecf`(1 080줄). 바뀐 곳은 "[1] page" 하위 블록과 LATER 기본 한 줄뿐이다. API 블록 390행의 "(a frame until then)" 주석은 하위 블록 밖이라 그대로 두었다(조율 세션이 고칠 nit).

### REVIEW_P12 "통합이 볼 것" 가운데 반영한 것과 남긴 것

반영:
- 1단계 1–4, 6–9: 위 중복 목록. `gdakiCtrlWofConfirm`은 `W_END_ALIVE + cw`.
- 1단계 10: 생존 READ QP 상태를 `gdakiProbeQpIsRts`로 보고, `wr_id` = (상대 << 32) | 그 QP의 세대, 성공 CQE에 `gdakiProbeQpOnSuccess(&qp, wr_id의 세대)`, 오류 CQE에 `gdakiProbeQpOnError`.
- 1단계 5의 LATER(고칠 것 18). `NCCL_PARAM(GinCtrlWitness)`는 트리에 한 곳(1단계 영역)뿐임 [측정: grep 1].
- 2a-1 1–3: 위 목록.
- 2a-1 4: 모형과 뒤끝 영역을 "[2] ring" 하위 영역 안으로. `sites`의 영역 정규식에 `(page|ring)`.
- 2a-1 6: `r->ctrl` 만들기를 `gdakiTsSetup`의 all-gather 바로 앞으로 옮김(`#if !NCCL_GIN_CTRL_TCP`, tcp 전처리 그대로). 풀기는 그대로 `gdakiRecFree`의 `gdakiCtrlFree`(모든 길). ring은 2a-2가 그 자리에서 만듦.
- 2a-1 7의 배치 앞부분(고칠 것 16): `gdakiCtrlPage::nLaunchers`를 두고 1단계도 `gdakiCtrlPageLayoutOf(nranks, nLaunchers)`로 부름. 값의 출처(준비 합의의 launcher 수)는 3단계가 정하므로 지금은 0이다. 링의 `rxConsumed`와 페이지 영역을 1단계 페이지에 묶는 것은 2a-2.
- 공통: `gc_unit_p1`, `gate_fenced`를 `build_gc.sh unit`에 넣음. `gc_unit_p1`은 tcp 빌드에서도 컴파일되고 0 검사(1단계는 rdma만), `gate_fenced`는 rdma만(tcp 빌드는 ln4의 `/proc` 관문).

남긴 것(통합 몫이 아니거나 기계적이지 않음):
- 1단계 11(생존 READ QP의 CQ: 지금 자기 CQ), 12(`gdakiCtrlThresholdsOk`를 준비 합의에서 부르기), 13(55번 발판은 2a-2의 PAIR(PRB)가 들어올 때 지움).
- 2a-1 5(seam 묶기: 2a-2), 7의 뒷부분, 8(`pr.probe`를 1단계 `qp`로, 넘기기 낱말로만).

### 막는 문제 (REVIEW_P12, 고치지 않음: 고침 에이전트 몫)

1. [1단계] 확인 창과 발판이 살아 있는 코드에 없다(창의 READ1, READ2, t_F + W 판정 없음; 55번을 보내는 곳 없음).
2. [1단계] 모든 상대의 생존 READ가 한 scratch 버퍼에 떨어진다.
3. [1단계] 분할 막이의 뜻이 거꾸로다(이 rank가 본 다른 상대의 정체를 견줌; 페이지 `staleMs[]`를 쓰지 않음).
4. [1단계] 시한 뒤 다음 READ를 또 띄워 SQ 4가 넘치고 재시도 초과 CQE를 걷지 못한다.
5. [1단계] REM_ACCESS가 아닌 모든 오류 CQE를 하드웨어 응답 없음으로 친다(재시도 초과만이어야 함).
6. [1단계] 감시 스레드가 STALLED 방송과 `gdakiTsDecline`을 직접 부른다(helper 소켓, `opMu`, `gdakiLnOf` 스레드 규칙).
7. [2a-1] 짝 맺기 모형에 HELD 입력이 없어 HELD rank의 옛 화신 PAIR를 받는다.
8. [2a-1] 세대가 바뀌면 RC가 ACK한 기록을 버리고, 상대가 시작한 다시 짝 맺기는 기록 층에 잃음 사건을 남기지 않는다.

고칠 것 1–17과 nit 1–16도 그대로 남았다(고칠 것 16, 18만 위처럼 반영). 고칠 것 7(`gate_fenced`는 시간표 모형이라 예측 `gate_fenced`의 프로그램이 아님)에 따라 아래 표의 gate_fenced 10/10은 모형의 결과다.

### 부르는 곳이 0인 코드 (지우지 않고, 잇지 않음)

[측정: grep, 마지막 트리; 정의와 선언을 뺀 부름 수]
- 1단계: `gdakiCtrlWofConfirm` 0, `gdakiCtrlConfirmW` 0, `gdakiCtrlActGate` 0, `gdakiCtrlProbeSetupSend` 0(그래서 `gdakiCtrlProbeSetupRecv`의 `pendConnect`는 늘 거짓), `gdakiCtrlPage::gapMaxMs`는 쓰는 곳 없음(늘 0), `helperStale` 쓰는 곳 없음.
- 헤더의 것: `gdakiCtrlConfirmVerdict` 0, `gdakiCtrlThresholdsOk` 0, `gdakiLnFenceOf` 0(호스트 파일에서; 단위 시험만 부름).
- 2a-1: 모형과 뒤끝 전부(`gdakiCtrlRdmaCreate` 0이 입구라 `gdakiCtrlRdma*`, `gdakiCtrlRing*`, `gdakiCtrlPair*`가 모두 살아 있는 길에서 0). `r->ctrl->ring`은 늘 null.
- 부르는 곳이 있는 것: `gdakiCtrlActFenceOk` 1(활성화 결정; `launcherPaired = false`라 늘 true), `gdakiCtrlJudge` 3(감시 스레드의 주기 READ, `NCCL_GIN_CTRL_PAGE=1`일 때만), `gdakiCtrlStallGuard` 1.

### 1단계 판정 표 21행

21행("판정 없음, 줄 하나")은 닿지 않는다. 헤더 `gdakiCtrlJudge`의 마지막 `else` 자리에 "21행: 닿지 않음" 주석을 두었다. 근거: `gc_unit_p1`의 격자 1 170점(5 × 2 × 9 × 13)에서 21행에 닿는 점 0, 1–20행은 모두 한 점 이상 [측정: `unit_int.log`]. 문서(9.3절 표의 21행)에 "닿지 않음(CPU 모형 1 170점에서 0)"을 적을 것을 조율 세션에 넘긴다.

## 빌드와 시험 (마지막 트리, 이 작업이 돌린 것만)

모두 worktree `control/impl/`에서 `SCR=<세션 스크래치> BR=int ./build_gc.sh <단계>`로 돌렸다. 로그는 `agent_gc_int/logs_int/`(아래 이름), 리뷰 통보 전 첫 판의 로그는 `logs_int/before_review/`(쓰지 않음). ssh, 클러스터, verbs 장치, GPU 실행 없음.

| 단계 | 결과 | 로그 |
|---|---|---|
| `repaste`, `api` | 블록 둘이 헤더와 바이트 같음(ctrl API `5df6bf40`, ctrl seams `1d1a4950`), 헤더 단독 컴파일 rdma와 tcp, 진입점 선언 있음/없음; `NCCL_GIN_CTRL_TCP_CELLS=1` 단독은 `#error`로 거절: 통과 [측정] | `repaste_int.log`, `api_int.log` |
| `syn` | build, build-gcp, build-gct에서 호스트 파일 `-fsyntax-only` 통과 [측정] | `syn_int.log` |
| `gc`, `gcp`, `gct`, `gctp` | 넷 모두 빌드됨, 경고 0, 다시 컴파일한 것은 호스트 파일 하나, 장치 객체 다시 빌드 없음(devsync 0). libnccl gc `7da89dc1`, gcp `f23cdaa4`, gct `130af8dd`, gctp `2c2ea799` [측정] | `build_{gc,gcp,gct,gctp}_int.log`, `out/*_int/` |
| `pre` | gct, gctp 정규화 뒤 ln4와 0 hunk(줄 수 같음 150 748, 150 175). gctc 2 hunk 3줄: 1단계의 RST 거절 간격 매개변수(`ncclParamGinTsRstRefusalGapMs` 정의 한 줄, `>= 1000.0`이 그 매개변수가 된 한 줄; 헤더 머리가 정한 "gctc는 tcp 대조 셀 코드만큼 다름", 리뷰도 "gctc는 RST 간격 2 hunk만"). gc 69 hunk(새 코드, 기록용) [측정] | `pre_int.log`, `out/pre/` |
| `sites` | 표 149행과 트리의 rdma 쪽 셈이 모두 같음, `#if NCCL_GIN_CTRL_TCP` 갈래 33개(준비 32 + 1단계 `gdakiHoldDrain` 1) 모두 ln4 글 그대로, 단계 영역 `#use` 셋이 같음(page 413 코드 줄, ring 1 381): 통과 [측정] | `sites_int.log` |
| `unit` (rdma) | mi_unit 다섯, rs_unit_host 348 739, rs_spare_unit 171 실패 0; `gc_unit_prep` 116 장면 366 검사 실패 0; `gc_unit_p1` 84 672 검사 실패 0(격자 1 170점, 21행 0점, 1–20행 모두 ≥ 1); `gate_fenced` 10/10, 24 검사 실패 0(시간표 모형); `gc_unit_p2` 2 781 807 검사 실패 0: 통과 [측정, n 1] | `unit_int.log` |
| `unit` (tcp) | 일곱 옛 시험 실패 0; `gc_unit_prep` 48 장면 174 검사 실패 0; `gc_unit_p1` 0 검사(rdma만), `gate_fenced`는 돌리지 않음(rdma만), `gc_unit_p2` 0 검사(rdma만): 통과 [측정] | `unit_int.log` |
| `ident` (IDTAG=int) | 설치 헤더가 ln4와 같음; 매크로 없는 프로그램 16/16 SASS와 자원 같음; 네 빌드 디렉터리의 장치 객체 207개씩 SASS 같음(바이트도 같음 207); 라이브러리 넷의 자원 사용 같음: 통과 [측정] | `ident_int.log`, `out/ident_int/` |
| `diff`, `info` | `gc_layer_int.diff` `a7600a46`, 4 312줄, 호스트 파일 하나, ln4 커밋 f53e5d2 대비(reverse apply 확인); 그 가운데 단계 몫(prep-fix 커밋 대비) 2 281줄 `2790d892`. 트리 호스트 파일 `f91ffac4`, 28 143줄 [측정] | `diff_int.log`, `out/build_info_int.txt` |

수의 바뀜: `gc_unit_p1`은 1단계 보고 83 467에서 84 672(행마다 판정 값과 원인 검사, 9.3절 판정 열 표 대조, 원인 이름 검사를 더함). `gc_unit_p2`는 2 781 801에서 2 781 807(nrp put 검사 다섯과 `probeGen` 0 장면 하나를 더함). 줄 수: `gc_unit_p1.cc` 372 → 402, `gc_unit_p2.cc` 862 → 872, `gc_sites.tsv` 161 → 167줄(행 149 그대로, `#use` 셋과 주석 셋).

## 2a-2, 2b, 3단계가 다음에 묶을 것

- **2a-2**: 위 막는 문제 7, 8을 먼저 고친다. 그다음 "[2] ring" 하위 영역의 갈아 끼우는 자리 본문을 뒤끝에: `gdakiCtrlChanUp(r, peer, pe)` ← `gdakiCtrlRdmaUp`, `gdakiCtrlChanGen` ← 그 쌍의 `ring.gen`, `gdakiCtrlPump`/`gdakiCtrlRecv` ← `gdakiCtrlRdmaRecv`(stop과 completion channel 기다림), `gdakiCtrlRecvOn` ← `g->udIn`과 예비 프로세스의 `gdakiCtrlRdmaRecv`, `gdakiCtrlRejoinFail` ← UD FAIL, `gdakiCtrlPollFd` ← `gdakiCtrlRdmaChannelFd`(한 칸만), `gdakiCtrlChanInstall` ← nrp로 QP 잇기, `gdakiCtrlRecordToErr` ← `gdakiCtrlRdmaRecordToErr`, `gdakiCtrlRingFree` ← `gdakiCtrlRdmaDestroy`. `r->ctrl->ring`은 all-gather 앞(이제 `r->ctrl`이 서는 자리)에서 만들고 UD 끝점과 영역을 `mine`에 싣는다. 링의 `rxConsumed`와 페이지 영역을 1단계 페이지(같은 `nLaunchers` 배치)에 묶은 뒤에 기록 길을 켠다. 생존 READ QP 짝 맺기는 감시 스레드의 넘기기 낱말로(고칠 것 12), 그 뒤 55번 발판을 지운다. notes_p2.md의 2a-2 발견 여덟.
- **2b**: notes_p2.md "2b에 남은 것"(저장소 몫, 시험 스위치 셋, MTU와 fork 검사, BYE 차례, launcher QP 둘). 고칠 것 8의 1단계 시험 스위치(`DIE_RST`, `RST_GAP`, `FD_HOLDER`, `FREEZE_PAGE`)도 아직 0건.
- **3단계**: `gdakiCtrlActFenceOk`의 `launcherPaired`(지금 상수 false, 고칠 것 5), `gdakiLnFenced`에 launcher의 EXITED와 FENCED를 넣는 길(54번 중계 자리), L의 유도, `gdakiCtrlPage::nLaunchers`와 링의 nL을 준비 합의의 launcher 수 하나로, "[3] launcher" 하위 영역의 `gdakiCtrlOnHoldStart`, `gdakiCtrlLauncherSend`, `gdakiCtrlLauncherFree`.
- **고침 에이전트(이 트리 위)**: 막는 문제 1–8, 고칠 것 1–15와 17, 그리고 위 "부르는 곳이 0인 코드"를 잇는 것(확인 창, `gdakiCtrlThresholdsOk`, 발판 또는 PAIR(PRB)).

## 파일 md5 (worktree `control/impl/`)

| 파일 | md5 | 바뀜 |
|---|---|---|
| `gc_layer_int.diff` (4 312줄) | `a7600a46bb8953d79ac4df4ac2757218` | 새 파일 |
| `rs_ctrl_api.h` (1 080줄) | `948b3ecff7b5782620d9a53b92a3aaa1` | "[1] page" 하위 블록(판정 표), LATER 기본 |
| `build_gc.sh` (780줄) | `fad463dbf65321f93731507bd668aa6f` | `int`, `p1`, `p2` 키 등 |
| `gc_sites.tsv` (167줄) | `6cd637e5dc9cf23dc7ef46afdcbb2b97` | `#use` 셋 |
| `gc_unit_p1.cc` (402줄) | `3350519efe681576a33762351ceb5343` | 헤더 이름과 판정 값 |
| `gc_unit_p2.cc` (872줄) | `b1ea84fd59a407afc0f824df762fd5a4` | 헤더 nrp put/get, `probeGen` |
| `gate_fenced.cc` | `a0817ab08954863fab473eb733035349` | 그대로 |
| `gc_layer.diff`, `gc_layer_p1.diff`, `gc_layer_p2.diff` | `0df79ae2`, `2fc1ad01`, `d571b977` | 그대로(기록) |
| `gc_unit_prep.cc`, `launcher/*`, `test/*`, `../../mirror/*`, `EXPERIMENT.md` | | 이 작업은 고치지 않음(`git status`의 `test/*` M은 다른 에이전트의 것) |

`build_gc.sh`의 `p1`, `p2` 키는 넣기만 했고 돌리지 않았다 [미확인]: 고정 입력(`impl_base/`, `agent_gc_p2/pin/`)의 옛 헤더에는 지금 시험 소스가 맞지 않으므로 그 키의 `unit`은 `GCTEST=`(단계 때 소스, `git show 73be8802:`, `494cd666:`)가 있어야 한다.

## EXPERIMENT.md에 넣을 문장 (조율 세션용)

**11절(작업 체크리스트)**

- [x] 1단계와 2단계 2a-1을 고친 준비 단계(`gc_layer.diff` `0df79ae2`) 위로 다시 올림: 한 트리(준비 + 1단계 + 2a-1), `impl/gc_layer_int.diff` `a7600a46`(ln4 대비 4 312줄, 호스트 파일만, 장치 0줄). 판정 표는 헤더 `gdakiCtrlJudge`로, 중복은 헤더 판으로, CONNECTED는 봉투 종류 6, `r->ctrl`은 all-gather 앞. 근거 `impl/notes_int.md`.
- [ ] REVIEW_P12의 막는 문제 8과 고칠 것을 고침(통합 트리 위, 고침 에이전트).

**12절(실행 기록)**

- 2026-10-17, gin-control 통합(실행 없음, CPU와 빌드만). 고친 준비 단계 위에 1단계와 2a-1을 3-way로 합쳤다(충돌 넷, 모두 고친 준비 단계 쪽이나 둘 다 둠). 네 빌드(gc, gcp, gct, gctp)가 빌드됨, 경고 0 `[측정: impl/notes_int.md, logs_int/build_*_int.log]`. tcp 전처리는 gct, gctp가 ln4와 0 hunk, gctc는 1단계의 RST 거절 간격만큼(2 hunk 3줄) 다르다 `[측정: pre_int.log]`. 장치 쪽은 매크로 없는 프로그램 16/16과 장치 객체 207개 × 4가 ln4와 같다 `[측정: ident_int.log]`. 단위 시험은 두 빌드에서 통과했다: `gc_unit_prep` rdma 366, tcp 174 검사; `gc_unit_p1` 84 672 검사(판정 격자 1 170점에서 21행 0점, 1–20행 모두 ≥ 1); `gate_fenced` 10/10(시간표 모형); `gc_unit_p2` 2 781 807 검사; gin-mirror와 gin-restore의 일곱은 고침 없이 실패 0 `[측정: unit_int.log, n 1]`. 확인 창, 범위 검사, 2a-1 뒤끝은 부르는 곳이 0이다(잇는 것은 고침 에이전트와 2a-2). 9.3절 표 21행은 "닿지 않음"으로 적는다.
