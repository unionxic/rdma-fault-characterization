# gin-control 1단계와 2a-1단계 고침 (REVIEW_P12 반영, 작업 기록)

## 단계 목록 (처음에 적은 계획)

1. 트리 `agent_gc_int/`의 작업 트리를 "gin-control int (gc_layer_int.diff a7600a46)"로 커밋
2. 1단계 순수 모형: CQE 분류, READ `wr_id`, 주기 READ의 한 번에 하나와 시한, SQ 단언, 확인 창 기계, R, L, W 유도, 분할 막이, 펜스 낱말 걸음; `gc_unit_p1.cc`의 표 시험을 행마다 기대 점 수로
3. 1단계 살아 있는 길(감시 스레드): 상대마다 READ 버퍼, 페이지 공개(원자), 1 ms 박동과 간격 최대, `FREEZE_PAGE`, `staleMs[]` 쓰기, 넘기기(잇기, RESET, ERR, 창 요청), `wr_id`로 완료 맞춤, 창, 판정, 우편함
4. 1단계 helper 쪽: 우편함 걸쇠(STALLED, 거절, 창 보고), 55번 발판 위의 생존 READ QP 짝 맺기(2a-1 모형), 증인 FIN/RST의 창 요청, 범위 검사, 펜스 관문(`gdakiCtrlActGate`, 걸쇠), 데이터 길 거부권 입력
5. 2a-1 모형: 계보 입력, REPEAT의 끝점 비교, 포기 뒤 세대, 보내는 자리 세대, 세대 바뀜의 inbox 보존과 잃음 사건, REJOIN 표의 생존 READ QPN
6. 2a-1 뒤끝: 행동 큐(poll 안 재진입 없음), Prepare는 걷기 뒤 세대 바꿈, outbox 초기화, channel fd non-blocking, UD RECV 오류 뒤 다시 만듦, `udIn` 한도, credit READ 원격 접근 오류, 생존 READ QP는 넘기기로만
7. `gc_unit_p2.cc` 장면(비대칭 ERR, ACK된 기록, HELD, 포기 뒤 다시 시작, 다른 QPN 먼저), `gate_fenced.cc`를 실제 프로그램으로
8. 검사: `repaste`, `api`, `syn`, 빌드 넷, `pre`, `sites`, `unit` 두 빌드, `ident`, `diff`; 이 문서 마무리

## 끝낸 단계 (한 단계 한 줄)

- 1 끝: `agent_gc_int/nccl-src`에 커밋 b80ebda "gin-control int (gc_layer_int.diff a7600a46)" (호스트 파일 `f91ffac4`, 28 143줄)
- 2–3 끝: 1단계 영역을 새로 씀(순수 모형 넷과 살아 있는 길, `merge/page_region_fix12.cc`), `gc_unit_p1.cc` 다시 씀; `syn` 세 빌드 통과, `unitp1`(rdma) 669 740 검사 실패 0 `[측정: logs_fix12/syn_s3.log, unitp1_s2.log]`
- 4 끝: helper 쪽 hook 셋(`gdakiTsMain`, `gdakiTsSocketLost`, `gdakiDetWatchStep`)과 생존 READ QP 짝 맺기 고리(`gdakiCtrlProbeLink*`, 55번 발판과 UD 둘에 같은 것); `syn` 통과 `[측정: syn_s3.log]`
- 5–6 끝: 2a-1 모형(계보 입력, REPEAT 끝점, 포기 뒤 세대, 보내는 자리 세대, 세대 끝 표시와 −1 한 번, 잃은 뒤에도 RC가 넘긴 기록은 받음, REJOIN 표의 QPN 둘)과 뒤끝(행동 큐, collect만 하는 안쪽 고리, Prepare는 걷기 뒤 세대 바꿈, outbox 초기화, channel fd non-blocking, UD QP 다시 만듦, `udIn` 한도, credit READ 끔, 생존 READ QP는 고리로); `gc_unit_p2.cc` 장면 고침, NIC 모형이 ERR QP로 낸 post를 곧바로 flush로 끝냄(verbs 규칙); `syn` 통과, `unitp2`(rdma) 3 984 398 검사 실패 0 `[측정: syn_s6.log, unitp2_s5c.log]`. 처음 판은 3 실패(옛 세대의 CONNECTED를 `gdakiCtrlRingTakeOld`가 받지 않아 그 뒤 기록을 버림) → 고침 `[측정: unitp2_s5b.log]`
- 7 끝: `gate_fenced.cc`를 실제 프로그램(fork, main thread의 pthread_exit, 둘째 thread 500 ms, /proc와 pidfd)으로; `unitp1` 통과, 첫 판은 /proc 22번째 칸을 한 칸 잘못 읽어 시작 시각 0(검사가 잡음) → 고침; 일부러 새 관문을 /proc 관문으로 바꾼 변종은 0/10으로 실패 `[측정: unitp1_s7.log, unitp1_s7b.log, gate_fenced_mutant.log]`
- 8 (검사): `repaste`, `api`, `syn` 통과; 빌드 넷 첫 판(gc, gcp)이 `-Wformat-truncation` 경고 2(`gdakiCtrlProbeRes::why` 96 B) → 192 B로 넓혀 다시 빌드, 경고 0 `[측정: build_gc_fix12.log, build_*_fix12b.log]`; 그 뒤 리뷰 중 찾은 둘(아래 "스스로 찾아 고친 것" 1, 2)을 고치고 마지막 판으로 `repaste`, `api`, `syn`, 빌드 넷, `pre`, `sites`, `unit`, `ident`, `diff`를 다시 돌림(아래 표)

## 무엇을 했나

통합 트리 `agent_gc_int/`(ln4 커밋 f53e5d2, prep-fix 커밋 2fc04b6, 이 작업이 먼저 만든 커밋 b80ebda "gin-control int (gc_layer_int.diff a7600a46)") 위에서 REVIEW_P12의 막는 문제 8과 고칠 것을 고쳤다. 호스트 파일 하나만 바뀌고 장치 코드는 0줄이다. 클러스터, ssh, verbs 장치, GPU 실행은 없다. 저장소에는 `git add`, commit, push를 하지 않았다(스크래치 트리의 커밋 b80ebda 하나뿐). 다른 에이전트가 맡은 `gdakiStoreOn`, upload와 FETCH 길, `gdakiStoreWardToErr`는 건드리지 않았다(이 작업의 diff에 그 이름이 0번 나옴 `[측정: grep merge/fix12_only.diff]`). 표시: `[측정]` 이 작업이 돌려서 본 것, `[추론]` 해석, `[미확인]` 확인 안 함.

이 작업만의 diff(b80ebda 대비)는 `agent_gc_int/merge/fix12_only.diff`(`144d53a6`, 2 829줄, 59 hunk)에 두었다. 리뷰는 이것을 보면 된다.

## 막는 문제 8: 고친 것

| 번호 | 고친 것 | 자리(호스트 파일 영역) |
|---|---|---|
| 1 | 확인 창을 살아 있는 길에 묶음. helper가 증인 FIN이나 RST(BYE 없음)를 `gdakiTsSocketLost`에서 보면 그 상대의 요청 낱말에 t_F를 두고(`gdakiCtrlOnSocketLost` → `gdakiCtrlWindowRequest`), 기록 54(FENCED, 끝남 보고)는 시각 재기용 창을 연다. 감시 스레드가 창 기계(`gdakiCtrlWindowOpen/Step/OnCqe/Judge`)로 READ1을 t_F에, READ2를 t_F + W/2에 띄우고(`wr_id` = (창 READ, 상대, QP 세대, 창 번호)) t_F + W에 `gdakiCtrlConfirmVerdict`와 `gdakiCtrlJudge`로 판정한다. 판정 뒤 완료는 창 번호로 버린다. 55번 PROBE_SETUP은 setup 뒤 helper의 첫 걸음부터 낮은 rank가 보낸다(본문은 2a-1 모형의 `gdakiCtrlPairBody`). `gdakiCtrlActFenceOk`가 `gdakiCtrlActGate`를 부르고, 활성화 결정의 rdma 갈래(`gdakiHoldActivateDecide`)가 그것을 부른다 | page 영역, `gdakiTsSocketLost`(`#if !NCCL_GIN_CTRL_TCP` 한 줄), ring 영역의 짝 맺기 고리 |
| 2 | READ 버퍼를 상대마다(그리고 launcher마다 자리만) 하나씩: 한 번 등록한 MR 하나 안에 상대마다 따로 된 칸(페이지의 쓰는 부분을 64 B로 올린 것 + 창 READ 둘의 줄 0), 공유 scratch 없음. 완료는 `wr_id`의 상대와 QP 세대로 맞추고, READ한 `incNonce`가 짝 맺기 때 받은 기대값과 다르면 정체 시계에 넣지 않는다(R = (13)) | `gdakiPageSetup`, `gdakiPageRd`, `gdakiProbePeerStep` |
| 3 | 분할 막이를 설계대로: 감시 스레드가 자기 페이지 `staleMs[q]`에 자기가 본 q의 정체(두 박동 정체 가운데 큰 것)를 쓰고, p의 멈춤 판정 때 다른 생존 rank k의 페이지에서 READ로 가져온 `staleMs[p]`를 `STALL_MS − 2 × PROBE_MS`와 견준다(`gdakiCtrlPartitionGuard`). k의 값은 이 rank의 k READ가 3 × `PROBE_MS` 안이고 k가 이 rank에게 정체가 아닐 때만 쓴다. 읽을 수 있는 다른 생존 rank가 하나도 없으면(이 rank만 모두를 정체로 봄) 스스로를 의심하고 판정하지 않는다(SELF). 다른 rank가 없으면(2 rank) 통과 | `gdakiPageBeatStep`, `gdakiProbeJudge`, 순수 영역 |
| 4 | 주기 READ는 한 번에 하나: 나가 있는 동안 새 READ를 띄우지 않는다. 500 ms 시한은 줄 하나와 R = (12)로만 쓰고 READ는 완료(성공이나 오류 CQE)까지 둔다. 오류 CQE면 `gdakiProbeQpOnError`로 QP 상태를 바꾸고 helper에게 "세대 g에서 깨짐" 낱말을 남겨 2a-1 모형(`gdakiCtrlPairOnQpErr` → PAIR(g + 1))으로 다시 짝 맺는다. SQ 쓰임은 `gdakiCtrlProbeIo`가 세고 4를 넘는 post는 하지 않는다(창이 열리면 창 READ 둘의 자리를 남김). 모형 시험이 4 이하를 단언 | 순수 영역(`gdakiCtrlProbeIo`), `gdakiProbePeerStep`, ring 영역 고리 |
| 5 | CQE 분류: `IBV_WC_RETRY_EXC_ERR`, `IBV_WC_RNR_RETRY_EXC_ERR`만 "하드웨어 응답 없음"(R (11)), `IBV_WC_REM_ACCESS_ERR`는 REMACC(R (10)), flush와 로컬 오류와 원격 연산 오류는 "생존 READ QP 깨짐, 다시 짝 맺기"(R (13))라 10–12행에 닿지 않는다. 묶음 안의 CQE는 `wr_id`마다 따로 걸러지고, 그 세대의 첫 오류만 QP 상태를 바꾼다. 값은 `GDAKI_CTRL_WC_*`로 두고 `IBV_WC_*`와 같음을 `static_assert` | 순수 영역(`gdakiCtrlProbeCqeClass`), 그 뒤 static_assert |
| 6 | 감시 스레드는 helper 소켓을 쓰지 않고 helper 전용 함수(`gdakiTsDecline`, `gdakiLnOf`, 펌웨어 명령)를 부르지 않는다. 멈춤 판정은 상대마다 원자 우편함 낱말(행, 판정, 원인, 화신)에 화신마다 한 번(걸쇠) 넣고, helper가 루프 앞(`gdakiCtrlPageHelperStep`, `gdakiTsMain`의 `#if !NCCL_GIN_CTRL_TCP` 한 줄)에서 exchange로 한 번 꺼내 화신을 `gdakiLnOf`로 견준 뒤 STALLED 방송과 거절을 한다. 창의 판정도 우편함으로 helper에게 가고(8행이면 WITLOST 줄), 이 rank 자신의 화신은 `gdakiRsSelfInc`(잠금 하나, 어느 스레드든 됨)로 쓴다 | `gdakiProbeJudge`, `gdakiCtrlPageHelperStep`, `gdakiCtrlStallDecline` |
| 7 | 짝 맺기 모형이 계보 입력을 받는다: `gdakiCtrlPairOnPair/OnAck/OnDone`에 `lnOk`(= `gdakiLnClassify(gdakiLnOf(r, from), 화신)`이 CURRENT)를 넣고, HELD_OLD, STALE, FUTURE는 버리며 (화신마다) `GIN/LN` 줄 하나를 내게 한다(`lnLog`). REJOIN 받아들임 뒤 두 종류에 `gdakiCtrlPairSetPeerInc(i + 1)`를 부르는 `gdakiCtrlRdmaOnRejoinAccepted`를 두었고(2a-2가 부름), 55번 발판은 새 화신이 rank를 맡으면 고리를 새로 시작한다. 시험: HELD 중 옛 화신의 PAIR(g + 1) 다섯 → 모두 DROP, 줄 1, QP 행동 없음; FUTURE도 DROP; 받아들임 뒤 새 화신 PAIR → TAKE, 옛 화신은 여전히 DROP | ring 모형, 고리, 뒤끝의 `gdakiCtrlRdmaRunActs`, `gc_unit_p2.cc` |
| 8 | 세대가 바뀌어도 RC가 ACK한 기록은 넘긴다: (1) `gdakiCtrlRdmaPrepare`는 ERR 뒤 현재 세대인 채로 완료를 걷고(성공 RECV는 차례대로 inbox로) 그다음 세대를 바꾼다; 세대를 먼저 바꾼 경우의 옛 세대 성공 RECV도 그 세대 끝 앞에 차례대로 넣는다(`gdakiCtrlRingTakeOld`); 잃은 뒤에 온 성공 RECV도 받는다(RECV는 다시 내지 않음). (2) `gdakiCtrlRingNewGen`은 inbox를 지우지 않고 옛 세대의 끝 표시를 뒤에 남기며, 펌프는 그 세대의 RECV를 다 걷은 뒤 −1을 정확히 한 번 낸다(상대가 시작한 다시 짝 맺기도 같음; 잃음을 이미 알렸으면 표시 없음). 원인은 `QP:NEWGEN`. (3) `gdakiCtrlChanGen`을 링이 있으면 링의 세대에 묶음. (4) 시험: 기대 목록을 세대가 바뀌어도 지우지 않고, ACK된 기록(NIC 모형이 받는 쪽에 내려놓은 기록)은 옛 세대에서도 모두 받음, −1은 바뀜마다 쪽마다 한 번이고 그 세대의 기록 뒤, 한쪽만 ERR(74/110번) | ring 모형, 뒤끝, `[2] ring` 자리 표시의 `gdakiCtrlChanGen`, `gc_unit_p2.cc` |

## 고칠 것 18: 반영과 거절

| 번호 | 처리 | 내용 또는 까닭 |
|---|---|---|
| 1 | 반영 | `helperStale`을 씀, 바쁨 낱말을 읽는 쪽 시계로 잼(`gdakiCtrlBusySeen`), 데이터 길 거부권을 helper의 QP 감시(`gdakiDetWatchStep`의 QUERY_QP 응답 MSN이 움직인 시각, `gdakiCtrlVetoObserve`)로 넣음, 늚을 감싸는 큰지로, R의 차례를 순수 함수 `gdakiCtrlRDerive`로 적고 시험(아래 "설계에 올릴 문장" 1) |
| 2 | 반영 | `gdakiCtrlLOf`, `gdakiCtrlWOf`; L은 launcher가 없으니 무응답이고 10–12행에는 반응을 걸지 않는다고 주석과 줄로 못 박음; 처음 판정 행 13 |
| 3 | 반영 | 페이지를 다 만든 뒤 release 저장으로 공개, `up`과 launcher 걸쇠는 원자; helper는 감시 스레드가 다시 만들 수 있는 `qp.q` 대신 setup 때 고정되는 `hasQp`를 읽음 |
| 4 | 반영(일부) | `watchBeat` 간격 최대를 재어 probe summary에 `beat_gap_max_ms`와 그 규칙의 W(`W_rule`, `gdakiCtrlConfirmW`)를 W 옆에 남김(라이브러리는 W를 정하지 않음); `CONFIRM_FACTOR` 매개변수를 지우고 상수로; `gdakiCtrlThresholdsOk`를 `gdakiPageSetup`에서 부르고 어긋나면 페이지를 켜지 않음(WARN); 20 아래 W를 조용히 올리던 것을 지움. 모든 rank가 같은 값인지의 합의는 준비 합의(all-gather) 몫이라 2a-2에 남김 |
| 5 | 반영(일부) | launcher 짝 맺음을 걸쇠로(`gdakiCtrlLauncherPairedLatch`, 내려가지 않음, 3단계가 부름). rdma 빌드의 `/proc` 갈래 지움은 3단계가 합쳐진 뒤의 일이라 남김 |
| 6 | 반영 | 판정 표 시험을 21행 자료와 일반 첫 일치로, 행마다 손으로 센 점 수(234, 468, 117, 39 × 6, 3, 1, 5, 9 × 5, 36, 9, 18, 0)를 단언; 창 시험을 창 기계의 시계로(판정 시각이 코드의 성질이 됨); 펜스 장면(`gdakiLnFencedStep`으로 빼서 FUTURE, STALE, max, 내려가지 않음, hold 전의 EXITED(0) 뒤 활성화); 출력은 장면 수로 |
| 7 | 반영 | `gate_fenced.cc`를 실제 프로그램으로(위 단계 7); 10/10, 일부러 틀린 변종 0/10 |
| 8 | 반영(일부) | `FREEZE_PAGE=<ms>[:helper][@<after ms>]`(연구 빌드만, communicator가 처음 무장된 때부터, 줄 `test switch FREEZE_PAGE=...: ... frozen`). 거절: `DIE_RST`, `RST_GAP`, `FD_HOLDER` — rdma 쪽은 증인 소켓이 기록 소켓과 갈린 뒤(2a-2)에야 뜻이 서고, tcp 쪽 갈래를 넣으면 `gctc`의 전처리 차이가 RST 간격 2 hunk를 넘어 이 작업의 검사 조건(gctc는 RST 간격 2 hunk만)과 어긋난다. 2a-2 뒤 시험 스위치 묶음으로 남김 |
| 9 | 반영 | UD 받기와 tick이 고른 행동은 `g->acts`에 담아 CQ 고리 밖에서 처리; 안쪽 고리(`gdakiCtrlRdmaCollect`)는 CQ만; 겹친 poll은 걷기만(`inPoll`); 보내는 자리마다 세대(`sendGen`) |
| 10 | 반영 | 같은 세대의 PAIR가 다른 끝점(QPN, PSN)에서 오면 저장한 답이 아니라 다시 TAKE(`retaken`); 시작은 늘 `max(cur, 마지막 시도) + 1`; 장면 시험 |
| 11 | 반영(일부) | 표가 생존 READ QPN도 견줌, 다른 QPN 쌍마다 줄 하나(nit 7). 시도 번호는 거절: REJOIN nrp에 칸이 없어 헤더와 예비 프로세스 쪽을 바꿔야 한다. 대신 "예비 프로세스는 한 복원 동안 QP를 다시 만들지 않는다"를 표의 전제로 주석에 적고, 시험은 모든 datagram을 섞어 그 전제 아래 첫 도착이 늘 맞음을 봄 |
| 12 | 반영 | 생존 READ QP의 PREPARE, CONNECT, ERR는 helper의 요청과 감시 스레드의 답(페이지 뮤텍스 아래)으로만; PAIR, PAIR_ACK, PAIR_DONE은 답이 온 뒤 그 끝점으로 보냄(`gdakiCtrlProbeLink*`, 55번과 UD에 같은 것); 리셋 전에 flush를 걷고(한도 100 ms, 넘으면 새 QP), 열린 창은 "확인 못함"으로 |
| 13 | 반영 | channel fd를 `O_NONBLOCK`으로(EAGAIN은 사건 없음); UD RECV가 오류로 끝나면 다시 내지 않고 묶음 뒤 UD QP를 다시 만들고 줄 하나; `udIn`은 rank마다 64개 |
| 14 | 반영(일부) | credit READ가 원격 접근 오류면 그 길을 끄고 줄 하나, 다음 PAIR의 페이지 영역에서 다시 켬(봉투 `ackSeq` 길로 돎). RC에서 오류 완료는 그 QP를 ERR로 만들므로 "기록 길을 죽이지 않음"은 할 수 없다 `[추론]`: 그 QP는 다시 짝 맺기로 돌아온다. PAIR의 페이지 칸은 이제 1단계 페이지(켜졌을 때)를 싣는다 |
| 15 | 반영 | 세대가 바뀌면 그 쌍의 outbox 상태와 `xferIn`을 비움(`gdakiCtrlRdmaNewGen`), 옛 세대의 XFER는 inbox에서 버림, XFER_DONE을 못 넣으면 실패를 돌려줌 |
| 16 | 이미 됨 | 통합 때 `nLaunchers` 하나로 두 배치를 맞춤(그대로) |
| 17 | 반영(일부) | 세대 바뀜의 기대 목록 지움 없앰, 한쪽 ERR, HELD, 포기 뒤 다시 시작, 섞인 REJOIN, 90 % 합격선 없앰, 장면 수로 보고. 가짜 verbs로 뒤끝(`gdakiCtrlRdma*`)을 그대로 돌리는 시험은 거절: 뒤끝이 `wrap_ibv_*`를 바로 부르므로 그 층을 함수 표로 빼야 하고, 리뷰도 "2a-2 전에"로 둔 일이라 2a-2의 첫 단계로 남김 |
| 18 | 이미 됨 | 통합 때 헤더 LATER 기본 1 000(그대로) |

합계 18: 반영 10(1, 2, 3, 6, 7, 9, 10, 12, 13, 15), 일부 반영 6(4, 5, 8, 11, 14, 17), 이미 됨 2(16, 18), 통째로 거절 0. 일부의 남은 몫은 위 까닭과 함께 아래 2a-2와 3단계 목록에 넣었다.

## nit 16

반영: 1(박동을 1 ms마다, 간격 최대를 잼), 3(주석), 4(처음 행 13), 5(`notes_p1.md` 88행에 고침 한 줄), 6(`memcpy`), 7(QPN 쌍 집합), 8(본문의 from, gen, 화신을 봉투와 견줌), 9(PSN이 지난 것과 다르게), 12(쓰는 쪽 하나 규칙을 낱말마다로 주석), 13(`notes_p2.md` 결정 2에 고침 한 줄), 14(`NCCL_IBVERBS_LIB` 지움), 15(DISPUTE 주석), 16(`notes_p2.md`의 세션 스크래치 경로를 `<세션 스크래치>`로). 남김: 2(`incNonce`에 rank: 헤더와 선 위의 뜻을 바꿈), 10(설계 2.1, 3.5절의 MR과 메모리 셈: 설계 문서 몫, 아래 "설계에 올릴 문장"), 11(AH를 준비 때 미리: 2a-2가 setup에 묶을 때).

## 스스로 찾아 고친 것 (리뷰에 없던 것)

1. 이 rank가 자기 생존 READ QP를 리셋하는 동안 열린 창이 있으면, 창 READ가 flush로 걷혀 답이 없으므로 t_F + W에 거짓 NORESP(5행, 끝남)가 날 뻔했다. 리셋과 ERR 요청에서 열린 창은 "확인 못함"으로 둔다 `[추론: 코드 읽기]`.
2. helper가 감시 스레드가 다시 만들 수 있는 `qp.q`를 읽던 자리(경합) → setup 때 고정되는 `hasQp`.
3. 옛 세대의 CONNECTED가 세대를 바꾼 뒤 걷히면 `gdakiCtrlRingTakeOld`가 받지 않아 그 뒤 기록을 버렸다 → CONNECTED도 그 세대의 seq로 받음 `[측정: unitp2_s5b.log 3 실패 → unitp2_s5c.log 0]`.
4. 시험의 NIC 모형이 ERR인 QP로의 post를 받아 두었다(verbs는 곧바로 flush로 끝냄) → 모형을 고침.
5. `gate_fenced.cc` 첫 판이 /proc stat의 22번째 칸을 한 칸 앞에서 읽었다(시작 시각 0) → 검사가 잡았고 고침.
6. `-Wformat-truncation` 경고 2(빌드 첫 판) → `why` 192 B.

## 부르는 곳이 0이던 것의 살아 있는 부름 (마지막 트리) `[측정: grep, 정의와 선언을 뺀 부름 수]`

| 함수 또는 칸 | 부르는 곳(사슬) |
|---|---|
| `gdakiCtrlConfirmVerdict` | `gdakiCtrlWindowJudge` ← `gdakiProbeWindowEnd` ← `gdakiProbePeerStep` ← `gdakiCtrlPageStep` ← `gdakiQ4Watch`(감시 스레드) |
| `gdakiCtrlWofConfirm` | `gdakiCtrlWOf` ← `gdakiProbeJudge` |
| `gdakiCtrlActGate` | `gdakiCtrlActFenceOk` ← `gdakiHoldActivateDecide`의 rdma 갈래 |
| `gdakiCtrlConfirmW` | `gdakiCtrlProbeSummary` ← `gdakiCtrlPageFree` ← `gdakiCtrlFree`(teardown) |
| `gdakiCtrlActFenceOk` | `gdakiHoldActivateDecide`(그대로 1) |
| `gapMaxMs` | 씀: `gdakiPageBeatStep`; 읽음: `gdakiCtrlProbeSummary` |
| `gdakiCtrlProbeSetupSend` | 지움. 대신 `gdakiCtrlProbeScaffoldSend`(함수 포인터) ← `gdakiCtrlProbeLinkSend` ← `gdakiCtrlProbeLinkPoll/Act` ← `gdakiCtrlProbePairingStep` ← `gdakiCtrlPageHelperStep` ← `gdakiTsMain`; 받기 `gdakiCtrlProbeSetupRecv` ← `gdakiCtrlOnRecord` ← `gdakiHoldOnMsg` ← `gdakiHoldDrain` |
| `helperStale` | `gdakiProbePeerStep`(READ마다), `gdakiProbeJudge`(R), `gdakiPageBeatStep`(`staleMs[]`) |
| `gdakiCtrlThresholdsOk` | `gdakiPageSetup` ← `gdakiTsStart` |
| `gdakiLnFenceOf` | `gdakiCtrlActFenceOk`의 기다림 줄 |
| `gdakiCtrlJudge` | `gdakiProbeJudge`(주기 READ 완료, 시한, 창 끝) |
| 2a-1 짝 맺기 모형(`gdakiCtrlPairInit/Start/OnPair/OnAck/OnDone/OnQpErr/Tick/BodyOf/BodyOk/StoreAck/PsnFresh/SetPeerInc`) | 생존 READ QP 고리 ← 55번 발판 ← `gdakiCtrlPageHelperStep` |

모두 `NCCL_GIN_CTRL_PAGE=1`일 때만 돈다(기본 0: 페이지를 만들지 않아 모두 곧바로 돌아감). 아직 0인 것: 2a-1 뒤끝 전부(`gdakiCtrlRdmaCreate` 0이 입구, `r->ctrl->ring`은 늘 null; 그 안의 `gdakiCtrlRdmaOnRejoinAccepted`도), 링 모형(`gdakiCtrlRing*`), REJOIN 표, outbox, `gdakiCtrlLauncherPairedLatch`(3단계).

## 수 (마지막 트리)

- `gc_unit_p1` (rdma): 669 740 검사, 실패 0. 장면: 판정 격자 1 170점(행마다 손 센 수와 같음, 21행 0), 창 6 000장면(살아 있음 185, STALE 174, NORESP 3 628, REMACC 146, 확인 못함 1 867; t_F + W 판정 4 183, 곧바로 1 817, 늦은 완료 버림 5 908), 죽은 상대 1(시한 501 ms에 한 번 17행, 3 660 ms 재시도 초과 R (11) → 10행), 무작위 READ 흐름 200판 60만 걸음(SQ 4 이하), R 차례, 분할 막이 네 장면(한 rank 멈춤: 멈춤 뒤 10 000 ms에 판정; 읽는 쪽만 고립: 판정 없음; 다른 rank가 신선하게 봄: 판정 없음; 2 rank: 10 000 ms), 펜스 격자 576점과 4.4절 장면. 검사 수가 큰 것은 무작위 흐름의 걸음마다 단언 때문이다 `[측정: unit_final.log]`
- `gate_fenced` (rdma): 실제 프로세스 10/10, 64 검사 실패 0; 마지막 판(n 10)에서 두 관문 차 500.2–501.1 ms, 옛 관문(Z)은 main thread 끝 뒤 0.5–1.4 ms, 새 관문(pidfd)은 마지막 thread 끝 뒤 0.8–1.7 ms. 범위는 이 한 번의 실행 안 10번의 범위다 `[측정: unit_final.log, 다시 셈]`
- `gc_unit_p2` (rdma): 3 984 398 검사, 실패 0. 장면: credit 60판(세대 바뀜 110, 그 가운데 한쪽 ERR 74, 잃음 사건 220 = 바뀜마다 쪽마다 한 번, 옛 세대 기록을 바뀜 뒤에 받음 3 429), inbox 1, framing 20판, 짝 맺기 2 000판(다시 짝 맺기 12 000, 모두 합의), HELD 장면 1(옛 화신 PAIR 5 버림, 줄 1), 포기 뒤 다시 시작 장면 3, REJOIN 2 000번 `[측정: unit_final.log]`
- tcp 빌드: `gc_unit_p1` 0 검사, `gc_unit_p2` 0 검사(rdma만), `gate_fenced`는 rdma만; 옛 시험 일곱과 `gc_unit_prep`(tcp 174 검사) 실패 0 `[측정: unit_final.log]`
- 줄 수: 호스트 파일 28 143 → 29 464줄(`f91ffac4` → `dbe44658`), `gc_unit_p1.cc` 402 → 821, `gc_unit_p2.cc` 872 → 1 019, `gate_fenced.cc` 99 → 204, `gc_sites.tsv` 167 → 169

## 2a-2가 다음에 묶을 것

1. 막는 문제 7, 8의 모형 쪽은 들어갔다. 그 위에 seam을 묶는다(`gdakiCtrlChanUp` ← `gdakiCtrlRdmaUp`, `gdakiCtrlPump`/`gdakiCtrlRecv` ← `gdakiCtrlRdmaRecv`, `gdakiCtrlPollFd` ← `gdakiCtrlRdmaChannelFd` 한 칸, `gdakiCtrlRecordToErr` ← `gdakiCtrlRdmaRecordToErr`, `gdakiCtrlRingFree` ← `gdakiCtrlRdmaDestroy` 등, notes_int의 목록 그대로). `gdakiCtrlChanGen`은 이미 링이 있으면 링의 세대다.
2. 펌프의 −1(`QP:NEWGEN` 또는 `QP:<원인>`)은 증인 소켓을 닫지 않고 라운드만 취소한다: `gdakiTsSocketLost`, `gdakiTsMakeUnknown`, `gdakiTsCauseLiveness`가 "QP:" 원인을 죽음으로 치지 않게.
3. 기록이 소켓을 떠나면 증인 FIN의 뜻을 바꾼다: 지금은 ln4 규칙(FIN = 죽음, 곧바로 거절)이 그대로이고 창은 같은 FIN에서 판정을 보고만 한다. 2a-2부터 FIN은 창만 열고 t_F + W의 판정(4–6행 hold 또는 거절, 8행 증인 다시 걸기와 WITLOST 줄, 9행 기다림)이 반응한다. 그 반응 자리는 `gdakiCtrlPageHelperStep`의 창 우편함이다.
4. 다시 짝 맺기의 방아쇠: 링이 lost이고 그 상대가 HELD도 거절도 아닐 때만 `gdakiCtrlRdmaPairOnErr`(CQ 고리 밖에서). hold 시작의 `RecordToErr`는 부르지 않는다.
5. 생존 READ QP 짝 맺기를 UD로: 고리(`gdakiCtrlProbeLink*`)는 준비됐고 링이 있으면 55번 발판(`gdakiCtrlProbePairingStep`)은 스스로 물러난다. 링의 poll이 고리의 tick을 돈다. 그다음 55번(PROBE_SETUP)과 `gdakiCtrlProbeScaffoldSend`, `gdakiCtrlProbeSetupRecv`를 지운다.
6. 링의 `rxConsumed[]`를 페이지의 `rxConsumed[N]` 자리에 묶은 뒤 기록 길을 켠다(`gdakiCtrlRdmaPageRegion`은 이제 켜진 페이지를 PAIR에 싣는다). 쓰는 쪽은 낱말마다 하나(helper는 `rxConsumed[]`만).
7. REJOIN 받아들임에서 `gdakiCtrlRdmaOnRejoinAccepted(g, peer, i + 1)`; REJOIN 답(UD의 FAIL, WAIT)의 뜻; 받아들인 화신과 같은 늦은 REJOIN은 버림.
8. 보내는 쪽 sleep 고리 동안 `helperBusy`(설계 3.1의 자리 목록); `gdakiCtrlProbeLinkAsk`의 50 ms 기다림도 그 목록에 든다.
9. 뒤끝을 가짜 verbs로 그대로 돌리는 시험(고칠 것 17의 남은 몫): `wrap_ibv_*`를 함수 표로 빼서 `PairAct`, `Prepare`, `Collect`, `Poll`을 모형 NIC 위에서.
10. 준비 합의에 `gdakiCtrlThresholds`를 실어 모든 rank가 같은 값인지 본다(고칠 것 4의 남은 몫). AH를 all-gather 뒤에 미리 만든다(nit 11).
11. 첫 smoke에서 볼 것(장치에서 한 번도 돌지 않음 `[미확인]`): REVIEW_P12의 목록에 더해, 감시 스레드가 하는 RESET과 RTR/RTS(펌웨어 명령, 다시 짝 맺기 때만), UD QP 다시 만들기, channel fd non-blocking의 EAGAIN, 창 READ와 주기 READ가 SQ 4를 나눠 쓰는 것.
12. 생존 READ QP의 CQ는 지금 QP마다 자기 것이다(감시 스레드가 상대마다 한 번 poll). 공유 감시 CQ로 바꿀지 정하고, 바꾸지 않으면 헤더의 `gdakiCtrlWatchCqNeed`와 설계 2.1절 문장을 고친다.
13. 시험 스위치 `DIE_RST`, `RST_GAP`, `FD_HOLDER`(증인 소켓이 따로 선 뒤; tcp 쪽 갈래는 `gctc` 뒤), rdma 빌드의 DEAD 줄 원인 이름(`rows_gc.py` TODO(p1)).

## 3단계가 묶을 것

1. launcher와 짝을 맺으면 `gdakiCtrlLauncherPairedLatch`(한 번, 내려가지 않음); 3단계가 합쳐진 뒤 rdma 빌드의 `/proc` 갈래를 지우고 FENCED만.
2. `gdakiCtrlLOf`의 입력(LEFT와 EXITED 말, 끌어 읽기 결과, 등록 낱말)을 채우면 10–12행이 갈린다. 그때까지 10–12행에는 반응이 없다.
3. launcher의 EXITED, FENCED를 `gdakiLnFenced`(`gdakiLnFencedStep`)로, 시각 재기 창(`GDAKI_CTRL_WSRC_ENDED`)도 함께; `fenceSent`를 세움.
4. launcher 페이지 끌어 읽기: READ 버퍼에 launcher 칸(`GDAKI_CTRL_PAGE_MAX_LAUNCHERS`개)이 이미 있다.

## 설계와 실험 문서에 올릴 문장 (조율 세션; 이 작업은 고치지 않음)

1. 설계 4.2절 R의 차례: `PROBE_MS=0`이면 (13); 마지막 주기 READ의 오류(REMACC (10), 재시도 초과 (11), 깨진 QP (13)); 시한 지난 READ (12); 이 세대에 성공 없음이나 다른 프로세스의 페이지 (13); `watchBeat`가 늘지 않으면 (2)–(5); 늘면 helper 쪽: 한도 안의 바쁨 (6), 정체 (7)–(9)(바쁨 한도가 끝난 때부터), `SUSPECT_MS` 아래 (1).
2. 설계 3.4절 분할 막이: `staleMs[q]`는 이 rank가 본 q의 두 박동 정체 가운데 큰 것; 다른 생존 rank k의 값은 그 READ가 3 × `PROBE_MS` 안이고 k가 이 rank에게 정체가 아닐 때만 쓴다; 쓸 수 있는 k가 없으면(이 rank만 모두를 정체로 봄) 판정하지 않는다; 다른 rank가 없는 2 rank는 막이 없이 이 rank의 보기만으로 판정한다.
3. 설계 4.3절: W는 라이브러리가 정하지 않는다. 라이브러리는 장애 없는 셀의 `watchBeat` 간격 최대(`beat_gap_max_ms`)와 10배 규칙의 W(`W_rule`)를 probe summary에 남기고, pilot이 `NCCL_GIN_CTRL_CONFIRM_MS`를 고정한다.
4. 설계 4.2절 확인 창: 이 rank가 자기 생존 READ QP를 다시 짝 맺는 동안 열린 창은 "확인 못함"이다.
5. 설계 2.4절 둘째 행: "ACK 안 된 기록과 대기열이 사라짐"의 구현 뜻(받는 쪽 inbox와 RC가 넘긴 옛 세대 RECV는 차례대로 넘기고 그 뒤 −1 한 번).
6. 설계 2.1, 3.5절의 MR과 메모리 셈(nit 10): READ 버퍼는 이제 MR 하나에 (rank 수 + launcher 칸 16) × 칸 크기(페이지의 쓰는 부분을 64 B로 올린 것 + 128 B)를 4 KiB로 올린 것이다. 4 rank, launcher 0이면 칸 448 B × 20 = 8 960 B → 12 KiB `[추론: 셈]`.
7. 9.3절 표 21행에 "닿지 않음(CPU 모형 1 170점에서 0, 행마다 손 센 수와 같음)".

## 검사 (마지막 트리, 이 작업이 돌린 것만)

모두 `SCR=<세션 스크래치> BR=int INT_BASE="gin-control int (gc_layer_int.diff a7600a46)" ./build_gc.sh <단계>`로 돌렸다(`INT_BASE`는 이 작업이 `build_gc.sh`에 더한 칸: 머리 커밋이 b80ebda일 때). 로그는 `agent_gc_int/logs_fix12/`. ssh, 클러스터, verbs 장치, GPU 실행 없음.

| 단계 | 결과 | 로그 |
|---|---|---|
| `repaste`, `api` | 헤더는 바꾸지 않음(`948b3ecf` 그대로). 블록 둘이 헤더와 바이트 같음, 헤더 단독 컴파일 rdma와 tcp, 진입점 선언 있음과 없음, `NCCL_GIN_CTRL_TCP_CELLS=1` 단독은 `#error`로 거절: 통과 `[측정]` | `repaste_final.log`, `api_final.log` |
| `syn` | build, build-gcp, build-gct에서 호스트 파일 `-fsyntax-only` 통과 `[측정]` | `syn_final.log` |
| `gc`, `gcp`, `gct`, `gctp` | 넷 모두 빌드됨, 경고 0, 다시 컴파일한 것은 호스트 파일 하나, 장치 객체 다시 빌드 없음(devsync 0). libnccl gc `b298a2b3`, gcp `2493d221`, gct `090fc37e`, gctp `1e552100` `[측정]`(앞 판 `*_fix12`는 경고 2라 버림, `*_fix12b`는 리뷰 중 고친 둘 앞의 판) | `build_{gc,gcp,gct,gctp}_final.log`, `out/*_fix12c/` |
| `pre` | gct, gctp 정규화 뒤 ln4와 0 hunk(150 748, 150 175줄). gctc 2 hunk 3줄(1단계의 RST 거절 간격 매개변수 정의 한 줄과 `>= 1000.0`이 그것이 된 한 줄). gc 72 hunk(새 코드, 기록용) `[측정]` | `pre_final.log`, `out/pre/` |
| `sites` | 표 149행과 트리의 rdma 쪽 셈이 모두 같음, `#if NCCL_GIN_CTRL_TCP` 갈래 33개 모두 ln4 글 그대로, 단계 영역의 `#use` 셋이 같음(page 1 102 코드 줄, ring 1 828). `gc_sites.tsv`의 `#use` 줄 셋을 고침(55번 보내기가 page에서 ring 영역의 고리로 옮김, ring의 `.fd` 2) `[측정]` | `sites_final.log` |
| `unit` (rdma) | mi_unit 다섯, rs_unit_host 348 739, rs_spare_unit 171 실패 0; `gc_unit_prep` 116 장면 366 검사; `gc_unit_p1` 669 740 검사; `gate_fenced` 10/10, 64 검사; `gc_unit_p2` 3 984 398 검사; 모두 실패 0 `[측정, n 1]` | `unit_final.log` |
| `unit` (tcp) | 옛 시험 일곱 실패 0; `gc_unit_prep` 48 장면 174 검사; `gc_unit_p1` 0 검사, `gc_unit_p2` 0 검사(rdma만), `gate_fenced`는 돌리지 않음(rdma만) `[측정]` | `unit_final.log` |
| `ident` (IDTAG=fix12c) | 설치 헤더가 ln4와 같음; 매크로 없는 프로그램 16/16 SASS와 자원 같음; 네 빌드 디렉터리의 장치 객체 207개씩 SASS 같음(바이트도 같음 207); 마지막 라이브러리 넷(`*_fix12c`)의 자원 사용 같음: 통과 `[측정]` | `ident_final.log`, `out/ident_fix12c/` |
| `diff` | `gc_layer_int.diff` `60ca3cd9`, 5 654줄, 호스트 파일 하나, ln4 커밋 f53e5d2 대비(거꾸로 적용 확인); 이 작업만의 몫(b80ebda 대비) 2 829줄 `144d53a6`. 트리 호스트 파일 `dbe44658`, 29 464줄 `[측정]` | `diff_final.log`, `merge/fix12_only.diff` |
| 덧 | `gate_fenced`의 새 관문을 `/proc` 관문으로 바꾼 변종은 0/10, 21 실패(시험이 틀릴 수 있음) `[측정]` | `gate_fenced_mutant.log` |

## EXPERIMENT.md에 넣을 문장 (조율 세션용)

**11절(작업 체크리스트)**

- [x] REVIEW_P12의 막는 문제 8과 고칠 것 18을 통합 트리 위에서 고침(반영 10, 일부 6, 이미 됨 2): 확인 창과 55번 발판이 살아 있는 길에 묶임, 상대마다 READ 칸, 분할 막이가 다른 rank의 `staleMs[p]`를 봄, 주기 READ 한 번에 하나, 재시도 초과만 하드웨어 응답 없음, 감시 스레드는 우편함만(helper가 STALLED와 거절), 짝 맺기의 계보 입력, 세대가 바뀌어도 RC가 ACK한 기록은 넘기고 −1 한 번. `impl/gc_layer_int.diff` `60ca3cd9`(ln4 대비 5 654줄, 호스트 파일만, 장치 0줄). 근거 `impl/notes_fix12.md`.
- [ ] 2a-2: seam 묶기, FIN의 뜻 바꿈(창이 반응), 생존 READ QP 짝 맺기를 UD로 옮기고 55번 지움, 가짜 verbs 시험, 시험 스위치 `DIE_RST`, `RST_GAP`, `FD_HOLDER`(`impl/notes_fix12.md` "2a-2가 다음에 묶을 것").

**12절(실행 기록)**

- 2026-10-17, gin-control 1단계와 2a-1 고침(실행 없음, CPU와 빌드만). REVIEW_P12의 막는 문제 8을 모두, 고칠 것 18 가운데 10을 다, 6을 일부 고쳤고 2는 통합 때 이미 됐다(거절한 몫과 까닭은 notes_fix12.md). 네 빌드가 빌드됨, 경고 0 `[측정: impl/notes_fix12.md, logs_fix12/build_*_final.log]`. tcp 전처리는 gct, gctp가 ln4와 0 hunk, gctc는 RST 거절 간격만큼(2 hunk 3줄) 다르다 `[측정: pre_final.log]`. 장치 쪽은 매크로 없는 프로그램 16/16과 장치 객체 207개 × 4가 ln4와 같다 `[측정: ident_final.log]`. 단위 시험은 두 빌드에서 통과했다: `gc_unit_p1` 669 740 검사(판정 격자 1 170점의 행마다 점 수가 손으로 센 수와 같고 21행 0; 창 6 000장면에서 판정은 늘 t_F + W이거나 확인 못함이면 곧바로; 죽은 상대는 시한 500 ms 뒤 3 660 ms의 재시도 초과가 R (11); 네 rank 분할 막이: 한 rank 멈춤은 10 000 ms에 판정, 읽는 쪽만 고립이면 판정 없음); `gate_fenced` 실제 프로세스 10/10(두 관문 차 500.2–501.1 ms, 이 실행 안 10번의 범위), 일부러 틀린 변종 0/10; `gc_unit_p2` 3 984 398 검사(세대 바뀜 110번, 그 가운데 한쪽 ERR 74번, ACK된 기록 모두 받음, 잃음 사건은 바뀜마다 쪽마다 한 번; HELD 중 옛 화신 PAIR는 버림) `[측정: unit_final.log, n 1]`. 살아 있는 길은 `NCCL_GIN_CTRL_PAGE=1`일 때만 돌고 장치에서 한 번도 돌지 않았다 `[미확인]`. 확인 창의 판정은 지금 보고만 하고(반응은 2a-2가 FIN의 뜻을 바꾼 뒤), 멈춤 판정은 거절만 한다(펜스는 3단계).

## 파일 md5 (worktree `control/impl/`)

| 파일 | md5 | 바뀜 |
|---|---|---|
| `gc_layer_int.diff` (5 654줄) | `60ca3cd9d7205f787bdad9804a6f28ec` | `build_gc.sh diff`로 다시 만듦(ln4 대비 전체 층) |
| `gc_unit_p1.cc` (821줄) | `02d929576de7eb000126a7435629aff6` | 다시 씀 |
| `gc_unit_p2.cc` (1 019줄) | `85236a44d8bd132a3f40b58dfef6ce93` | 새 서명, 장면 |
| `gate_fenced.cc` (204줄) | `3915182948604dc04f00cdc702675ba9` | 실제 프로그램 |
| `gc_sites.tsv` (169줄) | `057a6da0227199e418ba99594b420e8d` | `#use` 셋 |
| `build_gc.sh` (783줄) | `5eaaf11e05fe752798c8a3f094e0147d` | `INT_BASE` 칸 하나(머리 커밋 이름) |
| `rs_ctrl_api.h` | `948b3ecff7b5782620d9a53b92a3aaa1` | 그대로(헤더 바꿈 없음) |
| `notes_p1.md`, `notes_p2.md` | `757613a2`, `31d1d333` | nit 5, 13, 16의 고침 줄 |
| `notes_int.md`, `gc_unit_prep.cc`, `launcher/*`, `test/*`, `../../mirror/*`, `EXPERIMENT.md` | | 고치지 않음(`test/*`의 바뀜은 다른 에이전트의 것) |
