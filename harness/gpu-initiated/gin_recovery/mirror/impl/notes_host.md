# host 갈래 기록 (exp/gin-mirror-host, 2026-10-13)

[PARALLEL.md](PARALLEL.md)의 `exp/gin-mirror-host` 행(작업 묶음 셋: mirror 설정과 pool과 장애 기록, segment와 당기기, PUBLISHED와
INJECTED)의 기록이다. 통합 때 메인 세션이 12절로 옮기고 이 파일을 지운다. 줄 번호는 따로 적지 않으면
[rs_layer.diff](../../restore/impl/rs_layer.diff)(md5 `f005bb67`)의 줄이다.

## 12절에 들어갈 행

| 시각 | 무엇을 했나 | 결과와 근거(경로, 커밋, 실행 ID) |
|---|---|---|
| 2026-10-13 | host 갈래 구현(갈래 트리 `agent_mi_host/`, i5 위). (1) mirror 문맥: 문맥을 만들 때 사용자 문맥 뒤에 GIN 문맥 하나(QP, GPU 문맥, 자기 루프 쌍; allToAll 없음), pool(호스트 메모리, GIN PD, iova 0, RO 없음), 설정 기록 policyPad의 mirror 비트, 합의 뒤 helper 소켓으로 MIRROR_SETUP(48)과 mirror QP 잇기와 응답 쪽 기준, Resume 조건 34–40(지역 판정과 교환의 모음), mirror 문맥 장애 기록의 흡수(G4에서 `gdakiHoldRoute` 앞, 훑기), 정리(QP 뒤 pool 해제), 변수. (2) 체크포인트 기계의 segment: 멈춤 안 바꾸기, 자기 게시 없이 끝난 멈춤의 되돌리기, 넷째 자리면 다시 시작(PAUSED 뒤 DISARM), CKPT_STABLE, INJECTED, 짝의 새 pool 때 버리기, 10 ms 걸음의 깨짐 → DISARM과 CKPT_PULL(49), Step에서 당기기. (3) 붙잡기 기계: mirror 켬이면 복원 라운드의 게시가 사용자 QP 게이트를 홀수로 남김, RESTORED는 기록만, INJECTED(38)에서 짝수 에폭과 상태 이동, PUBLISHED 시한 min(v1, D), 되살린 rank의 INJECTED 보내기. mirror 끔이면 gin-restore의 길 그대로 | `impl/mi_layer_host.diff`, `impl/mi_unit_host.cc`, 이 파일; 커밋은 아래 "커밋" |

(빌드, 시험, 리뷰의 행은 아래 각 절의 끝에 적고 통합 때 함께 옮긴다.)

## 인터페이스 밖에서 정함

헤더 여섯이 정하지 않은 것을 이 갈래가 정했다. 통합 때 메인 세션이 받아들이거나 고친다.

1. **policyPad의 mirror 비트**는 `1u << 16`(`GDAKI_MI_PAD_MIRROR`). gin-restore의 비트(0–3, 8–11)와 겹치지 않고
   `gdakiRsDecide`는 이 비트를 보지 않는다(단위 시험이 확인). 비트는 "청함"(복원을 청하는 프로세스 + `NCCL_GIN_RESTORE_MIRROR`가 0이 아님)이고
   합의는 모든 rank의 비트 + 복원 결정 "켤 수 있음" + rank 둘 이상.
2. **조건 37에 S를 넣음**: `NCCL_GIN_RESTORE_MIRROR_SLOTS`가 2–4 밖이면 37(이유 글자 뒤 괄호에 "S n is not 2..4"). 헤더는 S 범위를 적었지만
   거절 조건 번호는 적지 않았다.
3. **조건 40의 한도는 31**: 헤더는 "사용자 문맥 + 1 ≤ 64"지만 라운드 범위 마스크(`gdakiTsScope`, 32비트; `gdakiRecForPeer`는 32 이상
   문맥을 범위와 상관없이 걷는다)에 mirror 문맥의 비트가 있어야 입력 멈춤의 "사용자만" 걷기가 mirror QP를 뺄 수 있다. 사용자 GIN 문맥이
   31을 넘으면 mirror 문맥을 만들지 않고 40(괄호에 까닭). R40 글자는 그대로다.
4. **Resume 교환 기록에 칸 셋**(`miReq`, `miSlots`, `miLane`, 16 B)을 더하고 magic을 "GRS3"(0x33535247)로. 조건 39와 모음의 34(비트가 다른
   rank)를 이 칸으로 판정하고, 이유는 가장 낮은 rank로 모든 rank에 같은 글자다. mirror 끔이면 셋이 0이라 판정은 gin-restore 그대로.
   지역 판정의 순서: 34, 35, 36, 37, 38, (39는 모음), 40. mirror 문맥이 없으면 35와 38을 보지 않고(40이 말함), 37이 나쁘면 35를 보지 않음.
   예비 프로세스는 38의 MIRROR_SETUP 쪽만 보지 않고 자기 루프 쌍은 본다.
5. **MIRROR_SETUP**: 모든 rank가 먼저 모든 상대에게 보내고 그다음 읽는다(기다림 순환 없음; 한도는 `NCCL_GIN_TS_HANDSHAKE_MS` 전체).
   `on`은 이 rank의 L, S, pool이 모두 좋을 때 1. 두 기록이 모두 on일 때만 두 rank가 같은 QP 쌍을 잇는다(QP 묶음이 짝마다 대칭).
   상대의 끝점은 상대 문맥 0의 교환 정보(같은 포트)에 MIRROR_SETUP의 QPN, 받는 PSN은 상대의 sqPsn(0), LAG 포트는 문맥 0의 것.
   기다리는 동안 MIRROR_SETUP이 아닌 기록이 오면 버리고(WARN) 38, BYE면 `left`를 세운다.
6. **miUse**: 측 표를 만드는 쪽(dev)이 처음 값을 무엇으로 쓰든, 이 갈래가 바꾸기 때 그 짝의 mirror QP 항목을 읽어 0이고 이 rank가 설정에서
   이은 QP면 1을 쓰고 다시 읽는다. 예비 프로세스(재생)에서는 가져오기가 쓴 값을 그대로 믿는다. 흡수는 0, 그 짝의 복원 라운드 게시 뒤 1
   (`gdakiHoldAfterPublish`에서; 9.6절의 다시 무장).
7. **다시 시작의 DISARM은 PAUSED를 보낸 뒤**(`gdakiCkptOnPause`의 끝), `gdakiMiSegSwitch` 안이 아님. PAUSED를 못 보내면 되돌리기가
   바꾸기를 지우므로 DISARM하지 않는다.
8. **RESTORED(mirror 켬)**: `gdakiHoldApplyRestored`가 `gdakiRsTakeRestored` 뒤 `gdakiMiApplyRestored`로 가서 그 pad를 기록하고
   `gdakiCkptPeerReset`, (그 rank가 이 rank의 짝이면) `gdakiStoreOnBuddyRestored`, 스스로 DISARM을 한다. 상태, 시한, heldPeer는 그대로.
9. **INJECTED의 짝수 쓰기**는 사용자 범위에서 `gdakiCkptEmptyRound`를 그대로 쓴다(commit 낱말 = 에폭 + 2와 abandoned 확인, 에폭 + 2,
   lbase 그대로, G6의 빈 라운드 기록). 실패하면 `gdakiHoldFallback`.
10. **게시의 홀수**: hk의 `gdakiTsRepostApply`(rs 트리, 이 diff 밖의 hk 코드) 안 게시 쓰기 한 줄을 `eNew | 1`(PUBLISHING 비트 없음)로
    바꿨다(mirror 켬, 상태 COMMITTING, mirror 문맥이 아닌 QP만). `s.epoch`는 eNew로 두어 INJECTED가 eNew + 2를 쓴다. PARALLEL.md의
    "게시 7403–7404의 게이트 홀수"를 이 한 줄로 했다.
11. **INJECTED 줄의 `gate_odd_ms`** = INJECTED를 적용한 때 − hold의 게이트가 처음 홀수가 된 때(`hp.gateOddMs`): 생존 rank의 put이 쉰 전체
    시간(9.4절 "쉬는 시간은 hold 시작부터 INJECTED까지").
12. **`gdakiMiPoolRekey`는 라운드를 실패시키지 않는다**: 칸을 못 쓰면 그 lane을 깨짐으로(DISARM) 하고 ncclSuccess. d가 이 rank 자신이면
    아무것도 하지 않고 ncclSuccess(이 rank가 되살린 짝의 맡긴 rank일 때). rank 범위 밖만 ncclInvalidUsage.
13. **자기 루프 오류**: 맡은 rank가 있는 rank의 helper가 Resume 뒤 100 ms마다 mirror 자기 루프 QP(요청 쪽)를 QUERY_QP(opMu 안), RTS가
    아니면 그 lane들을 실행 끝까지 깨짐(칸 무효, DISARM).
14. **`gdakiMiPoll`은 helper 걸음마다 부른다**(로그 poll 블록 밖: 그 블록은 재기만 하는 모드에서 돌지 않음). 칸 읽기는 10 ms마다
    (`GDAKI_HOLD_LOG_POLL_MS`), DISARM은 깨짐 묶음마다 한 번이고 segment가 바뀌면 다시. 당기기는 segment마다 한 번.
15. **당기기를 Step이 먹는 때**: 체크포인트 기계가 쉬고(요청 없음, 올리기 없음, 단계 IDLE) 물러섬(haveRetry)도 지났을 때만 먹는다.
    그 밖에는 남겨 둔다(헤더의 "체크포인트 중의 당기기는 다음 Step 몫").
16. **재기만 하는 모드의 mirror 팔**(`NCCL_GIN_RESTORE_LOG_MEASURE_MIRROR`=self|peer, getenv로 읽는 낱말): 첫 helper 걸음에 칸을 한 번
    유효로 쓰고(self: 이 rank의 pool, 자기 루프; peer: 받는 rank의 pool, 그 rank로 가는 mirror QP; 그 pool의 첫 맡은 rank의 고정
    lane), 매 측정 주기에 커서가 L/2를 넘은 칸을 0으로 되돌린다(내용은 읽지 않음). 다른 갈래 표에 이 일이 없어 이 갈래가 했다.
17. **`struct gdakiMiSegView`**(rs_mirror_api.h에서 붙이는 블록 밖)를 주인인 이 갈래가 host 파일에 헤더 그대로 정의했다.
    뷰의 `openBroken`은 열린 segment가 열릴 때의 누적 깨짐 값(장치의 지금 값에서 뺄 기준)이고, 호스트 쪽 깨짐(QP 포기, 자기 루프)은
    `cellValid` false로 드러난다. 닫힌 segment의 `broken`은 장치 증가분 + 호스트 깨짐.
18. **요약 줄의 뜻**: `max_live_bytes`는 받는 rank 하나의 lane이 지닌 살아 있는 바이트(닫힌 채움 + min(커서, L))의 최대(바꾸기와 poll 때),
    `third_slot`은 바꾸기 뒤 살아 있는 segment가 셋 이상이던 횟수, `broken`은 lane 깨짐 사건(장치 묶음 + 호스트), `absorbed`는 흡수한
    장애 기록 수 + 처음 포기한 QP(훑기, 자기 루프).
19. **`NCCL_GIN_RESTORE_MIRROR`**: 0이 아니면 청함.

## 메인 세션에 알릴 것

- **다른 갈래가 해야 이 갈래 길이 돈다**: dev의 `gdakiRsStart`가 측 표 머리에 `miOn = gdakiMiOn(r)`, `miCtx = r->mi.ctx`, 칸 배열과
  `miCellsOff`를 쓰고 mirror QP를 `rsLogged`에서 빼야 한다(아니면 이 갈래의 측 표 확인이 실패해 mirror를 쓰지 않음, WARN 한 줄).
  dev의 `gdakiRsQpsOfPeer` 좁힘이 없으면 mirror 켬의 입력 멈춤은 QP 수가 어긋나 BUSY(이 갈래만으로는 mirror 켬 체크포인트 없음).
  dev의 가져오기가 `gdakiMiInjectedReady`를 불러야 생존 rank가 PUBLISHED를 끝낸다(아니면 min(v1, D)에서 fallback).
- spare: `gdakiRsSwapRkeys`의 pool 항목에서 되살린 rank의 맡은 rank마다 `gdakiMiPoolRekey`(이 rank 자신은 그냥 넘어감). 셈 무효 같은
  깨짐은 `gdakiMiAbsorbQp(r, qpIdx, why)`로 하면 이 갈래의 포기 길(miUse 0, 칸 무효, DISARM)을 탄다. `gdakiMiSegViewOf`의 뜻은 위 17.
- store: 이 갈래의 영역에 `gdakiStoreOnBuddyRestored`의 자리표시 정의(`// placeholder (integration replaces)`)가 있다. mirror 켬의
  RESTORED는 v1 몸통으로 가지 않으므로 store 갈래가 v1 몸통의 `gdakiCkptPeerReset` 뒤에 넣는 줄은 mirror 끔 길만 덮고, mirror 켬은
  `gdakiMiApplyRestored`가 짝일 때 부른다. 합칠 때 겹치는 곳: `gdakiCkptOnStable`의 8249 한 줄(store의 8236–8248 바로 뒤).
- R40의 글자("…the user's are 64")와 실제 한도 31이 다르다(위 3). 헤더 글자를 고칠지 메인 세션이 정한다.
- 열린 것: MIRROR_SETUP이 한쪽에서만 시간을 넘기면(다른 쪽은 받아 이음) 그 짝의 rec QP 묶음이 비대칭이 된다. 그 짝의 투명 복구 라운드는
  QP 수가 달라 거절된다. Resume은 38로 거절하므로 복원은 켜지지 않는다. 드문 설정 실패이고 고치려면 확인 기록이 하나 더 필요하다.
- 전체 다시 빌드(공용 헤더가 바뀌어 장치 객체를 다시 만듦)에서 NCCL 원본 `scheduler/symmetric_sched.cc:327`의 경고 하나가 나온다.
  gin-restore의 전체 빌드(i1, i3)에도 있던 것이고 이 갈래가 고친 파일이 아니다.

## 빌드와 시험

- **빌드됨** (2026-10-13, 이 노드에서 컴파일만; GPU와 RDMA 프로그램 실행 없음). 리뷰 반영 뒤의 최종 출력:
  - `mi_host2` libnccl md5 `2a3fe39f`(연구 빌드), `mip_host2` libnccl md5 `a882eed5`(운영 빌드, `-DNCCL_GIN_TS_PRODUCTION`)
  - 둘 다 gin_host_gdaki.cc만 다시 컴파일했고 경고 0이다. 리뷰 전 첫 빌드(`mi_host` `d3d37da9`, `mip_host` `e3feac41`)는 공용 헤더가
    바뀌어 장치 객체를 모두 다시 만들었다. 그때 경고는 둘이었다.
    - NCCL 원본 `scheduler/symmetric_sched.cc:327`의 `-Wextra` 하나. gin-restore 전체 빌드(i1, i3)에도 있었다.
    - 이 갈래의 `-Wformat-truncation` 하나. 고친 뒤 -O3 컴파일에서 두 변형 모두 0이다.
  - 출력 경로: 갈래 트리 `agent_mi_host/out/`. 정보: `agent_mi_host/out/build_info.txt`
    - working tree diff md5 `7f313c32` = `impl/mi_layer_host.diff`
    - i5 커밋 diff md5 `f005bb67` = rs_layer.diff
- **`api` 통과**: 붙인 블록 다섯이 헤더와 바이트 단위로 같다. hold 공유 글자는 v2, 체크포인트 공유 글자는 v1이다. 헤더 여섯은 함께
  `g++ -fsyntax-only`를 통과한다(선언 있을 때와 없을 때 모두).
- **시험함**: `BR=host build_mi.sh unit`, ASan과 UBSan, `impl/mi_unit_host.cc`. 시험 함수 16개, 검사 1 561 826개, 실패 0.
  - Resume 지역 판정: mirror 끔에서 gin-restore 조건 33개의 번호와 글자가 그대로이고 mirror 사실이 아무것도 바꾸지 않는다. mirror 켬에서
    34–38과 40을 하나씩, 우선순위, 예비 프로세스 모드를 본다.
  - Resume 모음: mirror 끔 판정과 글자, 34(비트가 다름), 39(S나 L이 다름), 지역 거절 먼저.
  - 합의 비트와 `gdakiRsDecide`가 그 비트를 무시함. 조건 37(L, S, pool 한도). MIRROR_SETUP 검사와 연결의 대칭(두 쪽 사실 4 096 조합).
  - segment 상태 기계: 바꾸기, 닫기, 셋째 자리, 다시 시작, 되돌리기, 버리기 셋, 뷰와 `gdakiMiSegOfPos`.
  - 무작위 모델 둘.
    - segment: 살아 있는 수 ≤ S, 이어진 번호, 겹치지 않는 lane 자리.
    - 장부와 칸 모델: 멈춤 중 호스트 깨짐과 CKPT_STABLE, 되돌리기 뒤 칸과 장부가 정확함, 호스트가 보는 유효 = 장치의 유효.
  - poll(묶음마다 DISARM 한 번, segment마다 당기기 한 번), 흡수 판정(낡은 기록 포함), 섬기는 받는 rank, 사용자 범위 마스크.
  - PUBLISHED 시한 규칙: 홀수면 min(v1, D), 아니면 v1. INJECTED 판정을 모든 상태에 대해 본다.
  - 칸 위 경로 여섯: 제때, 시한 뒤 INJECTED 먼저, 시한 뒤 fallback 먼저, RESTORED 전 INJECTED, RESTORED 전 시한, mirror 끔.
    INJECTED와 mirror 끔의 RESTORED는 OFF로 간다.
  - 게시 낱말(사용자 QP 홀수, mirror QP 짝수), 당기기 소비, INJECTED 다시 보내기, PAUSED 무장 가능(끔이면 gin-restore 판정), 재기만
    하는 모드의 팔.
- 시험하지 않은 것(`[미확인]`): 실제 NIC과 GPU에서의 동작 전부. 문맥 만들기, MIRROR_SETUP 교환, pool 등록, 측 표 쓰기, 게시와 INJECTED의
  게이트, 흡수. dev 갈래의 측 표(miOn, 칸 배열)와 통합하기 전에는 mirror 켬 길이 돌 수 없다(아래 "메인 세션에 알릴 것").

| 시각 | 무엇을 했나 | 결과와 근거(경로, 커밋, 실행 ID) |
|---|---|---|
| 2026-10-13 | host 갈래 빌드(`mi`, `mip`)와 `api`, CPU 단위 시험 | 빌드됨: `mi_host2` `2a3fe39f`, `mip_host2` `a882eed5`, 경고 0(이 갈래 파일). 시험함: 16함수, 1 561 826검사, 실패 0. `agent_mi_host/out/build_info.txt`, `impl/mi_unit_host.cc` |

## 독립 리뷰

같은 모델의 다른 에이전트 하나가 읽기만 했다(2026-10-13; 대상: 리뷰 전 working tree, 그 diff는 `agent_mi_host/review/mi_host_wip.diff`).
찾은 것은 11개(중간 2, 낮음 9)다. 확인된 것은 셋이다.

- mirror 끔에서 회귀 없음.
- 장치 쪽 대기와 홀수 게시, INJECTED의 commit이 `tsParkStable`, `tsGiveUp`의 `next`와 맞음.
- 다른 갈래 소유를 침범하지 않음.

| # | 찾은 것 | 반영 |
|---|---|---|
| 1 | (중간) MIRROR_SETUP 뒤 쌍의 mirror QP 묶음이 비대칭일 수 있음(한쪽만 시간 초과, 보내기 실패, 잇기 실패). hk 라운드가 QP 수 차이로 상대를 거절해 mirror 실패가 application 실패가 됨 | 고침. 잇지 않은 쪽이 on = 0인 둘째 기록을 보내고, 받은 쪽은 helper에서(`gdakiMiPoll`) 그 QP를 `used` false, miUse 0으로 내림. 판정을 pure로(`gdakiMiSetupConnects`, `SendsOff`, `Demotes`), 두 쪽 사실 4 096 조합 시험(둘째 기록이 가면 늘 대칭) |
| 2 | (중간) mirror 켬에서 v1의 "restored as incarnation" 줄이 없어 복원 시간 채점기가 0건을 셈 | 고침. RESTORED를 받을 때 v1 줄을 글자 그대로 찍음(상태 칸은 그대로인 published) |
| 3 | (낮음) 흡수에 G6 낡은 기록 검사가 없어 옛 epoch 기록이 다시 켠 mirror QP를 다시 포기시킴 | 고침. 낡으면 handled만 올리고 `nStale`(`gdakiMiAbsorbVerdict`) |
| 4 | (낮음) `gdakiRecRegister`의 실패 길 둘이 mirror 상태와 pool을 흘림 | 고침. 그 길에서 `gdakiMiFree`(아직 장치 쓰기 없음) |
| 5 | (낮음) `gdakiMiTakePool`이 helper가 멈추기 전에 pool 포인터를 비움 | 고침. 포인터는 `gdakiMiFree`까지 두고 `poolTaken`만 세움, 해제는 Destroy가 QP 뒤에 |
| 6 | (낮음) 주기로 이미 due인 Step이 당기기를 먹지 않아 다음 Step에 쓸데없는 체크포인트 | 고침. 한가하면 due와 상관없이 먹음(`gdakiMiPullConsumes`) |
| 7 | (낮음) INJECTED 보내기가 load와 store 사이 요청을 잃고, 화신 0이면 버리고, 실패한 rank에 다시 보내지 않음 | 고침. `exchange`, 화신 0이면 다음 걸음까지 남김, 실패한 rank는 20 ms마다 50번까지 다시 |
| 8 | (낮음) 걸린 바꾸기 동안의 호스트 깨짐이 되돌리기 복사본에 없어 장부가 틀림 | 고침. 장부를 pure로 뺌(`gdakiMiLedger*`), 깨짐은 복사본에도 세고 되돌릴 칸도 무효로. 칸 모델 무작위 시험 |
| 9 | (낮음, 명세) INJECTED에서 ARMED로 올리며 닫힌 segment를 버림 | 해당 없음. `gdakiHoldRespareRegistered`가 늘 false라 INJECTED(와 v1의 RESTORED)는 OFF로 가고 다음 확정에서 무장(시험이 확인) |
| 10 | (낮음) 한도 31과 R40 글자 "64"가 다름, 다른 까닭도 R40 글자로 | notes에 적음(위 "인터페이스 밖에서 정함" 3, 아래 "메인 세션에 알릴 것") |
| 11 | (낮음) 시험이 주장만큼 보지 않음(되돌리기가 대입 확인뿐, 경로 4가 0과 같음, 연결 대칭과 게시 낱말과 낡은 기록과 소비 규칙이 빠짐) | 고침. 시험 함수 셋 추가, 경로 넷째를 "RESTORED 전 시한"으로 |

| 시각 | 무엇을 했나 | 결과와 근거(경로, 커밋, 실행 ID) |
|---|---|---|
| 2026-10-13 | host 갈래 독립 리뷰(다른 Opus 에이전트, 읽기만)와 반영 | 11개 중 10개 고침, 1개 해당 없음(위 표). 반영 뒤 다시 빌드와 시험(위 행) |

## 반영으로 더 정한 것 (인터페이스 밖)

20. **MIRROR_SETUP의 둘째 기록**: 자기 쪽이 on인데 상대에게 잇지 않은 rank는 기다림이 끝난 뒤 그 상대에게 on = 0인 48을 한 번 더 보낸다.
    상대는 helper에서 그것을 읽고 자기가 이었던 mirror QP를 쓰지 않음으로 내린다(`rq.used` false, miUse 0). 남는 비대칭은 둘째 기록조차
    못 보낸 경우뿐이다(그 쌍의 소켓이 망가짐; Resume은 38로 거절). 둘째 기록이 helper가 처리하기 전의 아주 짧은 창은 그대로다.
21. **INJECTED 줄에 `unsent=`를 더함**: `INJECTED sent step= survivors= unsent=`(survivors는 보낸 rank 수, unsent는 50번 다시 보낸 뒤에도
    못 보낸 수).
22. mirror 켬의 RESTORED는 v1 줄("rank P restored as incarnation …; state published")을 찍고 GIN/MI 줄은 없다.

## 커밋

- `3fff14a0` 인터페이스 커밋(`build_mi.sh paste`의 결과를 `mi_layer_host.diff`로)
- `da2b4f30` host 갈래 mirror 계층(`mi_layer_host.diff` md5 `7f313c32`)과 `mi_unit_host.cc`
- 이 파일을 더한 커밋(아래 다음 커밋)
