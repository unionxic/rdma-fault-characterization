# notes_p1.md — gin-control 1단계 (상태 페이지, READ 감지, 펜스)

준비 단계(`gc_layer.diff` md5 `f5061a31`) 위에 1단계를 구현했다. 호스트 코드만, 장치 코드 0줄. 모든 새 코드는
`#if !NCCL_GIN_CTRL_TCP` 안이라 tcp 회귀 빌드(`gct`, `gctp`)의 전처리 결과는 ln4 그대로다. 산출물은 이 폴더의
`gc_layer_p1.diff`, `gc_unit_p1.cc`, `gate_fenced.cc`, 이 파일이다. `git add`/commit/push는 하지 않았다.

## 1. 무엇을 만들었나 (EXPERIMENT 9.8 "1" 행)

호스트 파일 `gin_host_gdaki.cc` 한 파일만 고쳤다(diff 10 hunk, 778줄). 모두 `#if !NCCL_GIN_CTRL_TCP`.

- **판정 표(순수 함수).** 새 영역 "gin-control (page): pure functions"에 입력 넷(L 다섯, B 둘, W 아홉, R 열셋)의
  enum과 `gdakiCtrlJudgeRow(L, B, W, R)`를 두었다. 설계 4.2 / EXPERIMENT 9.3의 21행을 첫 일치 우선으로 그대로 옮겼다.
  `gdakiCtrlRowVerdict`, `gdakiCtrlCauseName`(강한 증거 원인 이름 일곱)도 같은 영역.
- **확인 창.** `gdakiCtrlConfirmP1`(countable, incOk, remacc, read1/2 done, beat1/2) → alive / STALE / NORESP / REMACC /
  확인 못함. 창 열기는 READ1(t_F), READ2(t_F + W/2), 판정(t_F + W) 틀로 감시 스레드에서 돈다. W 너비는
  `gdakiCtrlConfirmW(factor, gap)`(결정 대기 5: factor 기본 10, 20–50 ms로 자름).
- **상태 페이지.** `struct gdakiCtrlPage`와 `gdakiPage*`(setup/free/beat). 줄 0의 판정 낱말(watchBeat, helperBeat,
  helperBusy, incNonce, flags)을 감시 스레드가 정렬된 8 B 저장으로 쓴다. 보고 줄의 `ver`는 아래 2절의 결정대로 첫 꼴.
- **생존 READ(probe).** `gdakiProbePeerStep`/`gdakiProbePostRead`/`gdakiProbePollOnce`가 생존 READ QP로 상대 페이지를
  읽고 정체를 `gdakiCtrlStaleOnRead`(설계 3.4, 읽는 쪽 자기 멈춤 되돌림 포함)와 분할 막이 `gdakiCtrlStallGuard`로
  재서 `gdakiCtrlRofStale`로 R 값을 낸다. 감시 스레드 hook은 `gdakiQ4Watch`의 한 줄(`gdakiCtrlPageStep`).
- **펜스.** 펜스 낱말 `fencedPlus1[]`(0 = 없음, i + 1 = 화신 i 펜스됨)과 `gdakiLnFenced`(계보 분류가 CURRENT/HELD_OLD일
  때만 `max`로 올림, 내려가지 않음). 보고 이름 `gdakiLnFenceOf`(HOLD_WAIT에서만 NONE/FENCING/FENCED). 계보 헤더
  `rs_lineage_api.h`는 바이트 그대로이고 국면 값과 `gdakiLnViewOf`는 건드리지 않았다.
- **1단계 펜스 갈래.** 멈춤 판정(14, 15행)은 `gdakiCtrlStallDecline`이 STALLED(52) 방송 뒤 거절한다(launcher도 FENCED도
  없는 1단계는 `NCCL_GIN_RESTORE_FENCE=none` 꼴). hold 시작의 `gdakiCtrlPeerToErr`는 준비 단계가 이미 걸어 두었고
  1단계는 `gdakiProbeToErr`(생존 READ QP를 요청 낱말 넘기기로 ERR)를 채웠다.
- **관문.** 순수 `gdakiCtrlActGate(launcherPaired, fenced, /proc 판정)`과 `gdakiCtrlActFenceOk(r, peer, dead)`를 두었다.
  1단계는 launcher가 없어 늘 /proc 판정이다(아래 3절 header-change 7).
- **기록 52–55.** `gdakiCtrlOnRecord`가 STALLED(52), DISPUTE(53), FENCED(54, 3단계 relay), PROBE_SETUP(55)을 처리한다.
  `gdakiHoldOnMsg`/`gdakiHoldDrain`에 `#if !NCCL_GIN_CTRL_TCP` 갈래로만 걸었다(tcp는 ln4 그대로, `#else`로 원문 유지).
- **55 PROBE_SETUP 발판.** `gdakiCtrlProbeSetupSend/Recv` + `struct gdakiCtrlProbeSetupNrp`가 생존 READ QP 끝점과 페이지
  영역을 helper TCP 소켓으로 나눈다. 한 블록에 모았고 주석으로 "발판, 2단계 합류 시 55번과 함께 제거"로 표시했다.
- **tcp 대조 RST 간격.** `gdakiTsRefused`의 `>= 1000.0`을 `#if NCCL_GIN_CTRL_TCP && NCCL_GIN_CTRL_TCP_CELLS`에서만
  `>= (double)ncclParamGinTsRstRefusalGapMs()`로(기본 1000, RST 셀 100), 아니면 ln4의 `1000.0` 그대로. 그래서 `gct`는
  ln4와 같고 `gctc`만 2 hunk 다르다.

**장치 바뀜 없음:** `gdakiPageSetup`의 실제 MR/QP 생성은 `NCCL_GIN_CTRL_PAGE=1`일 때만 돈다(발판은 기본 꺼짐). 페이지
생성은 준비 스레드의 `gdakiTsStart`에서 한 번만 한다(REVIEW_PREP 6). 클러스터/verbs/GPU 실행은 없다.

## 2. 설계의 자유 안에서 정한 것

- **확인 창 W 너비(결정 대기 5).** factor 기본 **10×**(장애 없는 `watchBeat` 간격 최대), 20–50 ms로 자름,
  `NCCL_GIN_CTRL_CONFIRM_FACTOR`. 작업 지시가 10×를 못박았다. 설계 기본은 5×였다(아래 4절 deviation).
- **보고 줄 꼴(REVIEW_PREP 1단계 1).** 본문 7칸을 유지하고 원격 스냅숏은 짝수 `ver`(`gdakiCtrlLineSnapshotOk`)로만
  판정한다. w[6]에 `ver`를 되풀이하는 둘째 꼴(`gdakiCtrlLineSnapshotOk2`)은 **쓰지 않는다**: 지금 `gdakiCtrlLineWrite`가
  만들지 못하고 본문을 6칸으로 줄인다. 판정은 어차피 보고 줄을 읽지 않고(정렬 8 B 낱말만), 보고 줄은 보고용이며
  찢긴 줄은 버린다(`page_torn_n`).
- **결정 대기 기본값.** 모두 한 행/한 매개변수로 두고 `/* 결정 대기 N */` 주석을 달아 뒤집기 쉽게 했다.
  1 helper-only 멈춤 펜스(15행 = 14행), 2 11행 hold(증인 꺼짐 + 정보 없음 + 응답 없음 → 펜스 확인), 3 launcher-page
  EXITED는 "정보 없음"(끝남 아님; L 유도에서), 4 LATER 뒤 한도 이름만(`GDAKI_CTRL_P_LATER_MS` 기본 1000), 5 위의 W
  factor, 6 예비 없음 셀은 1단계에서 아무것도 안 함, 7 EXITED가 박동 늚을 이김(3행이 20행보다 앞), 8 펜스는 보고 이름
  (`gdakiLnFenceOf`).
- **발판 기본 꺼짐.** `NCCL_GIN_CTRL_PAGE` 기본 0. 1단계 혼자서는 상태 페이지를 켜지 않는다(링은 2단계, launcher는
  3단계라 혼자 돌릴 수 없음). 켜면 55번으로 생존 READ QP를 세운다.

## 3. 코디네이터에게 요청하는 헤더/seam 변경 (통합 때 묶을 것)

준비 단계 헤더 `rs_ctrl_api.h`는 고정이라 고치지 않았다. 아래는 통합 때 그 헤더(또는 prep-fix 에이전트의 seam)에
묶어야 하는 것이다.

1. **판정 함수/입력 enum을 공유 헤더로.** 설계 7.1은 `gdakiCtrlJudge`의 서명을 준비 단계 헤더에 두게 했으나 준비
   단계 헤더에는 없다. 1단계는 `gdakiCtrlJudgeRow` + L/B/W/R enum + `GDAKI_CTRL_V_*` + `gdakiCtrlCauseName`/`RowVerdict`를
   내 영역(cut `gc_page_pure.inc`)에 두었다. 2·3단계와 채점기가 공유하도록 헤더로 올려 달라.
2. **`gdakiLnFenceOf` + `GDAKI_CTRL_FN_*`도 헤더로.** 같은 이유.
3. **확인 창 순수 함수 보강(REVIEW_PREP 4).** 헤더의 `gdakiCtrlConfirmVerdict`는 incNonce 입력이 없고 박동을 `!=`로
   본다. 1단계는 `gdakiCtrlConfirmP1`(incOk 입력, 감싸는 큰지 `gdakiCtrlBeatAdvanced`)을 내 영역에 두어 썼다. 헤더
   함수를 incNonce + 감싸는 비교로 고치고, "a record-QP ERR opens the window" 주석을 v3대로("창을 열지 않음") 고쳐
   달라.
4. **보고 줄 꼴 정리(REVIEW_PREP 1단계 1).** w[6] 둘째 꼴(`gdakiCtrlLineSnapshotOk2`)을 헤더에서 빼고 첫 꼴만 남긴다
   (1단계가 그 꼴을 골랐다).
5. **보고 줄 칸(REVIEW_PREP 1단계 2·3).** 계보 보기와 hold 요약은 64비트 한 낱말에 안 든다. 상대마다 두 낱말로 하고
   `gdakiCtrlPageLayoutOf`의 "7개씩"과 페이지 판 번호를 고쳐야 한다. 1단계는 보고 줄을 쓰지 않아 닿지 않았으니
   2단계/헤더가 정한다.
6. **채널-업 seam(REVIEW_PREP 1단계 1/6).** `gdakiCtrlFd`에 기대지 않았고 다시 정의하지도 않았다. "그 쌍의 기록 채널이
   섰나"는 내 영역의 `gdakiCtrlChanUp(r, peer)` placeholder로 불렀다(지금은 `gated && !gone`). prep-fix의 채널-업 seam에
   통합 때 묶어 달라.
7. **활성화 펜스 관문(REVIEW_PREP 본문 고칠 것 9).** `gdakiCtrlActFenceOk(r, peer, dead)`를 1단계가 채웠다(launcher-paired면
   fence 낱말 = dead + 1, 1단계는 launcher 없어 true). prep-fix가 `gdakiHoldActivateDecide`의 `#if !NCCL_GIN_CTRL_TCP`
   갈래에서 `if (!gdakiCtrlActFenceOk(...)) return;`을 부르게 묶고, 3단계가 launcher-paired 깃발을 세운다. `gdakiRsActExamine`
   자리(spare /proc 관문)는 tcp 전처리 동일성을 깨지 않으려고 고치지 않았다(1단계 = /proc).
8. **둘째 매크로/빌드 키 이름(REVIEW_PREP nit 15).** 코드·12절은 `NCCL_GIN_CTRL_TCP_CELLS`/`gctc`, 설계·머리·9.3절은
   `NCCL_GIN_CTRL_TCP_EXT`/`gctx`로 엇갈린다. 1단계는 준비 단계 코드가 쓴 `TCP_CELLS`/`gctc`에 맞춰 RST 간격을 걸었다.
   문서·코드 이름을 하나로 맞춰 달라.

## 4. 설계와 다르게 한 것 (이유)

- **W factor 10×.** 설계 기본은 5×(결정 (가)). 작업 지시가 10×를 기본으로 지정해 따랐다. 매개변수라 5×로 뒤집기 쉽다. (고침 2026-10-17,
  REVIEW_P12 nit 5: 10×는 2026-10-17 새벽 사용자 결정 5다. 고침 뒤 라이브러리는 W를 정하지 않고 간격 최대와 그 규칙의 W를 보고만 한다.)
- **판정 함수 등을 헤더가 아닌 내 영역에.** 준비 단계 헤더가 고정이라 못 고친다. 위 3절 1–3이 통합 요청이다.
- **활성화 관문 live 자리 미수정.** `gdakiRsActExamine` 호출부를 바꾸면 `gct` 전처리가 ln4와 달라진다. 순수
  `gdakiCtrlActGate`/`gdakiCtrlActFenceOk`로만 두고 1단계는 /proc(launcher 없음)로 둔다. 설계 의도(launcher 있을 때만
  FENCED)와 같다.

## 5. REVIEW_PREP "1단계와 2단계에 알릴 것" 적용

1. 적용 — `gdakiCtrlFd` 안 씀/안 고침, `gdakiCtrlChanUp` placeholder 사용(3절 6).
2. 적용 — 보고 줄 첫 꼴 선택(2절, 3절 4).
3. 미해당(보고 줄 안 씀) — 3절 5로 올림.
4. 적용 — `gdakiCtrlConfirmP1`(incNonce + 감싸는 비교), 창은 ERR로 안 엶(판정 표가 기록 QP ERR를 W 입력으로 받지
   않음), 헤더 주석 수정 요청(3절 3).
5. 적용 — 제자리 `#if`로 가른 세 함수(`gdakiTsSetupConnect`, `gdakiRsSpareRun`/`...RejoinAll`/`ActivateWait`,
   `gdakiHoldActivate`/`...Decide`/`...Send`)의 본문을 고치지 않았다. 페이지 생성은 `gdakiTsStart`에서 한다.
6. 적용 — `ctrl` 포인터/페이지는 준비 스레드(`gdakiTsStart`)에서만 만든다. 정리 차례: `gdakiCtrlFree`가 `gdakiPageFree`를
   먼저 불러 MR/QP를 없앤다(helper·감시 스레드가 선 뒤). `gdakiRecFree`가 collComm 닫기에 견주어 언제 도는지는
   `[미확인]`이라 저장소 QP 정리(`gdakiStoreFree`)와 같은 차례인지 2단계가 확인.
7. 적용 — PROBE_SETUP 받기에서 계보 분류(CURRENT/HELD_OLD)를 먼저 하고 받아들인다. `gdakiCtrlPairResolve`는 1단계에서
   안 쓴다.
8. 적용 — 감시 스레드 hot path에서 `gdakiProbeQpIsRts`(QUERY_QP) 안 부르고 `qp.connected && !q->err`로 소프트웨어
   추적.

## 6. 측정 결과 (CPU만, ASan·UBSan)

- **판정 격자.** `gc_unit_p1`의 `testJudge`: 입력 격자 **1 170**점(5 × 2 × 9 × 13), 21행에 닿는 점 **0**, 1–20행 모두
  ≥ 1, 독립 참조 matcher가 1 170점 모두 일치, floor 성질(hold/거절 행은 모두 launcher 끝남·창 확인·응답 없음·멈춤 중
  하나) 참, 강한 증거 원인 이름 일곱. 셀 시나리오(kill FIN+NORESP → 5행, FIN+STALE → 4, REMACC+FIN → 6, EXITED → 3,
  FIN 없는 READ 실패 → 11, LINKDOWN → 10, 멈춤 → 14, helper 멈춤 → 15, 살아 있는 RST → 8, BYE/LEFT 우선)도 확인.
- **gc_unit_p1 전체:** 83 467 checks, 0 failed. (판정 낱말 모형 400 000 reads 0 inconsistent; 보고 줄 seqlock 찢김 0;
  정체 모형(읽는 쪽 멈춤 되돌림, 분할 막이); 확인 창 40 000 무작위 완료 시각, 판정 늘 t_F + W, incNonce·감싸는 비교;
  펜스 oracle 576점, 관문 차이 40점 전부 HOLD_WAIT.)
- **gate_fenced:** 10/10 — 옛 관문(Z = GO)은 0 ms, FENCED 관문은 약 500 ms에 GO(둘째 thread 497–503 ms). 24 checks 0 fail.
- **기존 단위 시험(준비 단계 헤더 f5061a31, 두 빌드).** `gc_unit_prep` rdma 1 026 745 / tcp 7 842, `mi_unit_{dev,host,
  store,spare,lineage}`·`rs_unit_host`·`rs_spare_unit` 모두 0 failed(헤더가 prep-fix로 바뀌는 중이라 `git HEAD`의 기준
  헤더 snapshot으로 돌림; 7절).
- **빌드.** `gc`, `gct`, `gcp`, `gctp` 빌드됨(경고 0, `-Werror`). 클러스터 실행 없음.
- **동일성.** 장치 기계어: 매크로 없는 프로그램 16/16 동일, 장치 객체 207 × 4 ln4와 바이트 동일, 설치 헤더 ln4와
  같음, 라이브러리 resource usage 동일. tcp 전처리: `gct`·`gctp` 정규화 0 hunk(ln4와 같음), `gctc`만 2 hunk/3줄
  (TCP_CELLS RST 간격). → 장치 코드 0줄 확인.

파일(줄 수·md5): `gc_layer_p1.diff` 778줄 `2fc1ad01`, `gc_unit_p1.cc` 372줄 `11bf9a4f`, `gate_fenced.cc` 99줄 `a0817ab0`.

## 7. 준비 단계 헤더가 작업 중 바뀐 것 (주의)

작업 중 prep-fix 에이전트가 worktree의 `rs_ctrl_api.h`(gdakiCtrlThresholdsOk를 구조체 인자로), `build_gc.sh`,
`gc_sites.tsv`, `launcher/launcher_msg.h`를 고쳤다(커밋 안 됨, working tree M). 내 1단계는 고정 기준 `f5061a31`
(= `git HEAD`의 헤더, md5 `5e46650e`) 위에서 만들었고, 빌드/동일성/단위는 그 기준 헤더 snapshot으로 냈다. 통합 때
새 준비 단계 위로 rebase하면서 위 3절 seam들을 묶으면 된다. `gc_layer_p1.diff`는 `f5061a31` 위 호스트 파일 diff다.

## 8. EXPERIMENT.md에 넣을 문장 (코디네이터가 11·12절에 붙일 것; 다른 실험 문서는 사실만)

**11절 체크리스트(한 줄 추가):**

```
- [x] 1단계(상태 페이지, READ 감지, 판정 표 21행, 확인 창, 펜스 낱말과 보고 이름, 기록 52–55, 관문 순수 함수):
  구현·빌드(gc, gct, gcp, gctp), CPU 단위 시험(gc_unit_p1 83 467 checks, gate_fenced 10/10), 기계어 비교(207×4 동일),
  tcp 전처리 동일(gct, gctp 0 hunk) — 2026-10-17 (notes_p1.md; 독립 리뷰와 2·3단계 통합은 남음)
```

**12절 실행 기록(한 행 추가):**

```
| 2026-10-17 | 1단계 구현. 준비 단계(gc_layer.diff f5061a31) 위 impl/gc_layer_p1.diff(2fc1ad01, 778줄, 호스트 파일만,
장치 0줄). 새 gdakiPage*·gdakiProbe*, 감시 스레드 hook, 판정 표 21행 순수 함수(입력 격자 1 170점에서 21행 0점·모든
행 ≥ 1·floor 성질), 확인 창(t_F·t_F+W/2·t_F+W; incNonce와 감싸는 박동 비교), 펜스 낱말 fencedPlus1과 보고 이름
gdakiLnFenceOf(계보 헤더 그대로), 기록 52–55와 55번 PROBE_SETUP 발판, 1단계 멈춤 거절, 관문 순수 함수
gdakiCtrlActGate(1단계는 /proc), tcp 대조 RST 간격(NCCL_GIN_CTRL_TCP_CELLS). gc·gct·gcp·gctp 빌드됨(경고 0).
CPU 단위 시험 두 빌드 통과: gc_unit_p1 83 467, gate_fenced 10/10, 기존 단위(gc_unit_prep 1 026 745/7 842, mi·rs
단위) 0 실패. 장치 객체 207×4·프로그램 16/16 ln4와 동일, gct·gctp 전처리 0 hunk. 결정 대기 여덟은 설계 v3 기본으로
한 행/한 매개변수씩 두고 /* 결정 대기 N */ 표시. 헤더로 올릴 것과 seam은 notes_p1.md 3절. 클러스터 실행 없음 |
impl/gc_layer_p1.diff, impl/gc_unit_p1.cc, impl/gate_fenced.cc, impl/notes_p1.md |
```
