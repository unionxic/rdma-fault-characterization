# gin-control 2단계 2a-1: 링 모형, UD 짝 맺기 모형, 단위 시험, verbs 뒤끝 (작업 기록)

## 단계 목록 (처음에 적은 계획, 20줄)

1. `build_gc_p2.sh`: 작업 공간 스크립트 사본에 `p2` 키(트리 `agent_gc_p2`, diff `gc_layer_p2.diff`, unit에 `gc_unit_p2.cc`)
2. 사본으로 지금 트리(준비 단계 커밋 86bef74, 고침 없음)의 `unit` 한 번: 기준선 확인
3. 호스트 파일에 영역 "gin-control (ring): model" 뼈대(`#if !NCCL_GIN_CTRL_TCP`), `wr_id` 꼴
4. 링 상태 구조(쌍마다): 세대, 보낸 수 S, 아는 소비 수 C, 보내는 자리, 대기열(4 096까지)
5. 받는 쪽: 자리 64의 RECV 상태(세대 꼬리표), 순번 확인, inbox(4 096), 한도 때 자리 붙잡기
6. credit: 봉투 `ackSeq`, 소비 낱말, 창 닫힘 → 소비 낱말 READ 콜백(1 ms 간격)
7. 세대 바뀜: 대기열 버림(수 셈), 옛 세대 CQE 버림, 옛 RECV 다 걷기 전 새 RECV 없음, CONNECTED 전 보내기 없음
8. 짜기(framing): 봉투 + 본문을 자리에, 받는 쪽 검사(봉투, 순번, 기록 magic)
9. `gc_unit_p2.cc` 첫 판: credit 모형, inbox 한도 모형, framing(TCP 모형과 바이트 같음) → 빌드, 실행
10. UD 짝 맺기 모형: 종류 둘(기록, 생존 READ), 세대 + 1, 어느 쪽이든 시작, 엇갈림은 낮은 rank, launcher에는 rank가 이김
11. 짝 맺기의 새 PSN, 500 ms 다시 보냄과 한도, 옛 화신 버림
12. REJOIN 표: HELD일 때만 멱등, 같은 QPN은 저장한 답, 다른 QPN은 버림 + `GIN/LN` 한 줄, `nrp` 검사
13. 단위 시험에 짝 맺기 모형(잃음, 겹침, 차례 바뀜, 옛 화신, 다른 QPN) → 실행
14. park 동일: 링을 지난 기록 열이 TCP 모형과 같으면 park에 드는 열도 같음(같은 순서의 `gdakiHoldDefer` 입력) → 시험
15. verbs 뒤끝 1: `gdakiCtrlRing` 구조, helper CQ 1 024와 completion channel, 받기와 보내기 영역 MR, dlopen 기호
16. verbs 뒤끝 2: 쌍마다 기록 QP(SQ 96, RQ 64, REMOTE_READ, rnr_retry 3), RTR 전 RECV 64, 잇기, ERR로
17. verbs 뒤끝 3: CQ 걷기가 모형을 돌림, 보내기, 펌프, 소비 낱말 READ, RNR 셈
18. verbs 뒤끝 4: UD QP와 주소 핸들, PAIR 보내기와 받기; outbox 2 × 1 MiB, XFER, XFER_DONE
19. 네 빌드(gc, gcp, gct, gctp), pre(tcp hunk 0), unit 두 빌드, ident, diff
20. 이 파일: 2a-2 발견 여덟(줄 번호 확인), 남은 것, 결정, API, 헤더 요청, 스크립트 diff, EXPERIMENT 11/12절 안

## 끝낸 단계 (한 단계 한 줄)

- 1 끝: `agent_gc_p2/build_gc_p2.sh`(작업 공간 `build_gc.sh` 사본, `BR=p2`, 개발용 단계 `unitp2` 더함)
- 2, 3 끝(합침): 영역 뼈대와 `wr_id`, `gc_unit_p2.cc` 첫 판이 두 빌드에서 컴파일되고 실행됨(`unitp2`: rdma 10 000 checks 0 failed, tcp 0 checks)
- 4–8 끝: 링 모형(쌍 구조, 대기열 4 096, 보내는 자리 64, credit 세 길 가운데 봉투와 READ 콜백, 받는 자리의 세대 꼬리표, inbox 4 096, 세대 바뀜, CONNECTED, 짜기)과 `gdakiCtrlRingUp`(채널 살아 있음 술어)
- 9 끝: `gc_unit_p2.cc`의 credit 모형, inbox 한도 모형, 옛 세대 봉투와 연결 잃음 넷, framing과 park 시험이 통과(`CFG=rdma BR=p2 ./build_gc_p2.sh unitp2`: 2 366 727 checks, 0 failed; 첫 실행의 실패 둘은 시험 쪽 잘못이었음: 받는 쪽이 시작한 짝의 CONNECTED를 돌리지 않음, 기대 순번)
- 10–12 끝(빌드만, 시험 전): 짝 맺기 모형(`gdakiCtrlPairSt`, 행동 열), 새 PSN 확인, 옛 화신 버림, `nrp` put/get(memcpy), REJOIN 멱등 표, outbox 반 둘의 모형
- 13 끝: 짝 맺기 시험(잃음 0–39 %, 겹침 0–29 %, 차례 바뀜, 엇갈림, launcher 쪽, 옛 datagram 다시 보냄, 다른 화신)과 REJOIN 시험(`nrp` 왕복, 멱등 표, CONNECTED 전 보내기 없음) 통과(`unitp2` rdma: 2 781 801 checks, 0 failed)
- 14 끝(9에 합침): park 동일은 framing 시험 안에서 봄(같은 park, 같은 읽는 쪽 목록, 주인의 take도 같음)
- 15–18 끝: verbs 뒤끝 `gdakiCtrlRdma*`(helper CQ 1 024와 completion channel, UD QP와 주소 핸들, 쌍마다 기록 QP, 보내기와 받기, 소비 낱말 READ, RNR 셈, 짝 맺기 행동, outbox XFER/XFER_DONE) 빌드됨. 어디서도 부르지 않음(2a-2 몫)
- 19 끝: 아래 "결과"(네 빌드, pre, sites, api, unit 두 빌드, ident, diff)
- 20 끝: 이 문서의 아래 절들

## 결과 (이 작업에서 실행한 것만)

작업 공간 입력은 worktree HEAD `fa39bfdc`의 준비 단계 판을 `agent_gc_p2/pin/`에 고정해 썼다(`rs_ctrl_api.h` 5e46650e, `gc_sites.tsv`
acc0566e, `gc_unit_prep.cc` 1a468b99, `gc_layer.diff` f5061a31, `launcher/launcher_msg.h` 30a05c7f). 작업 중 다른 에이전트(준비 단계 리뷰
고침)가 worktree의 이 파일들을 고치고 있었기 때문이다. 처음 `sites`는 고쳐지던 `gc_sites.tsv`(149행)를 읽어 MISMATCH였고, 고정한 판으로
다시 돌려 통과했다. 로그는 모두 `agent_gc_p2/logs_p2/`다.

| 무엇 | 명령(`agent_gc_p2/`에서) | 결과 | 로그 |
|---|---|---|---|
| 빌드 넷 | `BR=p2 ./build_gc_p2.sh gc`, `gcp`, `gct`, `gctp` | 빌드됨, 경고 0. libnccl gc_p2 c6441659, gcp_p2 bfeb6287, gct_p2 da18c785, gctp_p2 de0dbbac | `build_{gc,gcp,gct,gctp}_p2.log` |
| 뒤끝 함수가 기계어가 되는가 | gc 컴파일 명령에 `-fkeep-static-functions`(라이브러리에는 부르는 곳이 없어 빠짐) | 빌드됨: 정의한 `gdakiCtrlRdma*` 29개가 모두 객체에 있음 | `keep_static.log`, `keep_static.o` |
| tcp 전처리 동일 | `BR=p2 ./build_gc_p2.sh pre` | gct, gctp, gctc 모두 정규화 뒤 ln4와 hunk 0(줄 수 같음: 150 748, 150 175); gc는 50 hunk(새 코드) | `pre_p2.log`, `out/pre_p2/` |
| 자리 표 | `BR=p2 ./build_gc_p2.sh sites` | 통과(고정한 `gc_sites.tsv` 120행과 트리가 같음; 새 영역은 셈에서 뺌) | `sites_p2.log` |
| 붙인 블록 | `BR=p2 ./build_gc_p2.sh api` | 통과(블록 둘이 고정 헤더와 바이트 같음) | `api_p2.log` |
| 단위 시험 두 빌드 | `BR=p2 ./build_gc_p2.sh unit` | 통과: mi_unit 다섯, rs_unit_host 348 739, rs_spare_unit 171, gc_unit_prep 1 026 745(rdma)와 7 842(tcp), gc_unit_p2 2 781 801(rdma)와 0(tcp, 모형 없음), 모두 failed 0 | `unit_p2.log` |
| 장치 동일성 | `BR=p2 ./build_gc_p2.sh ident` | 통과: 매크로 없는 프로그램 넷의 16 조합이 ln4와 SASS와 자원이 같음, 네 빌드의 장치 객체 207개씩 SASS 같음(바이트도 같음: 장치 객체는 다시 빌드되지 않음, devsync), 라이브러리 자원 사용 넷 같음 | `ident_p2.log`, `out/ident_p2/` |
| 계층 diff | `BR=p2 ./build_gc_p2.sh diff` | `impl/gc_layer_p2.diff` d571b977, 1 577줄, 호스트 파일만, 더하기만 1 552줄(지움 0), reverse apply 확인 | `diff_p2.log` |

gc_unit_p2(rdma)의 장면: credit 모형 60회(기록 648 631개, 세대 바뀜 104, 옛 세대 완료 버림 20 022, 창 닫힘 READ 22 751, RNR 0), inbox
한도(읽는 쪽이 멈추면 inbox 4 160 = 4 096 + 64에서 보내는 쪽이 멈추고, 돌아오면 7 096개가 차례대로), 옛 세대 봉투와 연결 잃음 넷(SEQ,
EARLY, BADMAGIC, BADENV), framing(gc_unit_prep.cc 생성기의 기록 10 872개: 링을 지난 바이트가 ln4 `gdakiTsSend`의 바이트와 같고 park
4 827개와 읽는 쪽 3 075개가 같음), 짝 맺기 2 000회(다시 짝 맺기 12 000, 엇갈림 4 045, launcher 쪽 286회, 모두 한 세대와 서로의 끝점에 합의,
잃은 datagram 13 901 / 73 913), REJOIN 2 000회(받아들임 각 1번, 반복 답 10 000, 다른 QPN 버림 2 972와 `GIN/LN` 줄 2 487, 옛 화신 1 937).
`[측정]` 수는 `unit_p2.log`의 출력 줄 그대로다.

## 설계의 자유 안에서 정한 것

1. `wr_id` = 종류 4비트 | 상대 12비트(rank, 뒤에 launcher) | 세대 32비트 | 자리 16비트. 옛 세대 완료는 `wr_id`만으로 가린다.
2. (고침 2026-10-17, REVIEW_P12 nit 13: 통합 뒤 기록 QP의 CONNECTED는 헤더의 봉투 kind 6 `GDAKI_CTRL_K_CONNECTED`, 본문 0 B다. 아래는
   단계 때의 결정이다.) CONNECTED와 PAIR_DONE의 운반: 봉투 kind PAIR + `gdakiCtrlPairBody`의 step DONE(3). 기록 QP에서는 그 세대의 첫 RC SEND(seq 1, credit
   하나를 씀), 생존 READ QP에서는 UD datagram. 헤더에 step이 없어 모형 영역에 `#define GDAKI_CTRL_PAIR_STEP_DONE 3u`를 두었다(헤더 요청 1이
   들어가면 이 줄을 지운다).
3. credit: 받는 쪽 소비 수 = 기록을 받아 RECV를 다시 낸 수(처음 K개는 세지 않음). 봉투 `ackSeq`가 그 수를 싣는다. 32비트 수는 "보낸 수보다
   많을 수 없음"으로 64비트로 펼친다.
4. 보내는 버퍼: 쌍마다 64칸, credit이 아니라 SEND 완료에 비운다. SEND는 모두 signaled(SQ 96 = SEND 64 + READ 16 + 여유 16).
5. inbox 한도: 도착한 기록은 늘 inbox로 옮기고, inbox가 4 096을 넘으면 그 자리의 RECV를 다시 내지 않는다(차례대로 기다림). 그래서 inbox는
   4 096 + 64까지다.
6. 세대가 바뀌면 보내는 대기열과 inbox의 안 읽은 것을 버린다(TCP에서 옛 소켓을 닫는 것과 같음). 부른 쪽은 연결 잃음으로 "보내기 실패"를 안다.
7. 창 닫힘 READ: 한 번에 하나, 1 ms 간격, 대상은 상대 페이지의 `rxConsumed[me]`(`gdakiCtrlPageLayoutOf`의 자리). 1단계 페이지가 묶이기 전에는
   PAIR의 page 칸이 0이라 이 길이 꺼지고 credit은 봉투로만 돈다(한 방향 64개 뒤 막힘: 2a-2에서 페이지를 먼저 묶어야 함).
8. 엇갈림에서 진 높은 rank는 자기가 같은 세대로 INIT에 둔 QP를 그대로 답에 쓴다(RESET 없음, PSN은 이미 새것).
9. 다시 짝 맺기의 방아쇠(ERR 봄 → PAIR)는 poll이 아니라 부르는 쪽(`gdakiCtrlRdmaPairOnErr`)이 당긴다. hold 시작의 `RecordToErr`가 죽은 상대와
   다시 짝 맺기를 시작하지 않게 하기 위함이다.
10. REJOIN의 세대: 헤더 `gdakiCtrlRejoinNrp`에 생존 READ QP 세대가 없어(요청 2) 그 전까지는 두 종류를 같은 세대 max(기록, 생존 READ) + 1로 연다.
11. REJOIN의 다른 QPN 버림은 QPN마다 한 번만 `GIN/LN` 줄(UD 반복이 줄을 넘치게 하지 않음).
12. ibvwrap에 없는 `ibv_create_ah`, `ibv_destroy_ah`, `ibv_get_cq_event`, `ibv_ack_cq_events`는 NCCL이 이미 연 libibverbs에서 `dlopen(RTLD_NOLOAD)`과
    `dlsym`으로 찾는다. `req_notify_cq`는 `ctx->ops`로 부른다.
13. 기록 QP 다시 쓰기: ERR → 옛 세대 완료를 200 ms까지 걷음 → RESET → INIT(새 PSN). 다 걷지 못하면 QP를 없애고 새로 만든다.
14. 상대 UD 끝점의 주소 핸들은 캐시하고 끝점이 바뀌면 다시 만든다.
15. outbox 받기는 1 MiB 받는 버퍼로 READ한 뒤 복사한다. 빈 전송은 0바이트 XFER 하나(END)다.

## phase 3가 부를 짝 맺기 API

- 모형(순수): `gdakiCtrlPairInit`, `gdakiCtrlPairSetPeerInc`, `gdakiCtrlPairStart`, `gdakiCtrlPairOnQpErr`, `gdakiCtrlPairOnPair`, `gdakiCtrlPairOnAck`,
  `gdakiCtrlPairOnDone`, `gdakiCtrlPairTick`, `gdakiCtrlPairStoreAck`, `gdakiCtrlPairPsnFresh`; 행동 `GDAKI_CTRL_PA_*`(SEND_PAIR, RESEND_PAIR, TAKE,
  RESEND_ACK, CONNECT, RESEND_DONE, UP, GIVE_UP, DROP). launcher의 `from`(0x40000000 | 노드)은 어떤 rank보다 커서 엇갈림에서 rank가 이긴다(시험함).
  본문 도우미 `gdakiCtrlPairBodyOf`, `gdakiCtrlPairBodyOk`는 rank 사이 본문(144 B)용이고 launcher의 `glPairBody`(112 B)는 phase 3가 옮긴다.
- 뒤끝: `gdakiCtrlRdmaPairStart(g, peer, kind, boundMs)`, `gdakiCtrlRdmaPairOnErr(g, peer, kind, gen, boundMs)`, `gdakiCtrlRdmaSetUd`, `gdakiCtrlRdmaUdSend`,
  `gdakiCtrlRdmaPoll`, `gdakiCtrlRdmaOnWake`, `gdakiCtrlRdmaChannelFd`, `gdakiCtrlRdmaUp`, `gdakiCtrlRdmaSend`, `gdakiCtrlRdmaRecv`, `gdakiCtrlRdmaXferSend/Recv`,
  `gdakiCtrlRdmaRecordToErr`, `gdakiCtrlRdmaRnr`. 지금 `peers`는 rank만이다: launcher QP 둘(9.1)은 `peers`를 nranks + nLaunchers로 늘리고 UD 받기의
  `from` 검사(지금 launcher datagram은 `badDgrams`)를 넓혀야 한다.
- REJOIN: `gdakiCtrlNrpPut/Get`(memcpy), `gdakiCtrlRejoinHold/End/On/Accepted`(`GDAKI_CTRL_RJ_*`). UD로 온 RECORD(REJOIN, REJOIN_ACK)는 `g->udIn`에 쌓인다.

## 헤더 변경 요청 (`impl/rs_ctrl_api_p2.diff`, 고정 헤더 5e46650e에 대해)

1. `GDAKI_CTRL_PAIR_STEP_DONE = 3`(CONNECTED와 PAIR_DONE). 들어가면 모형 영역의 `#define`을 지운다.
2. `gdakiCtrlRejoinNrp`에 `genPrb`(생존 READ QP의 세대)와 `rsv`: 160 → 168 B(≤ 256). `gc_unit_prep.cc`의 `sizeof == 160` 검사도 168로.
   준비 단계 리뷰 고침(`notes_prepfix.md` 4번 "nrp(probeGen, put/get), CONNECTED와 PAIR_DONE")과 겹친다: 그쪽 판이 들어가면 이 요청은 그것으로 갈음하고
   모형의 이름만 맞춘다.
- 패치한 헤더는 gin-mirror 헤더 일곱과 함께 `g++ -std=c++17 -Wall -Wextra -Werror -fsyntax-only`로 컴파일됨(`agent_gc_p2/hdr/`).

## 2a-2(부르는 자리 잇기)에 남긴 것

줄 번호는 준비 단계 트리(86bef74, 호스트 파일 md5 890e2122)와 이 트리(p2)의 것이다. 29개 모두 두 파일에서 같은 줄임을 확인했다 `[소스]`.

1. `gdakiTsRespondPrepared`(prep 12524)의 DONE 기다림(prep 12619, p2 13321)은 `gdakiTsRecv`를 `pe.fd`로 직접 부르고 `gc_sites.tsv`에 없다(그 표의
   `gdakiTsRecv` 행은 8267 backend 하나).
2. 값이 소켓 호출로 가는 자리는 `gdakiCtrlFd` lvalue로 모자란다: `recv(MSG_PEEK)` prep 12673(p2 13375, `gdakiTsServeLower`), pollfd prep 12758과
   12764(p2 13460, 13466, `gdakiTsRecvServing`), `gdakiTsRecv` prep 23509(p2 25061, `gdakiMiSetupEnd`), 대입 prep 10915(p2 11617,
   `gdakiRsSpareRejoinAll`). 자리마다 rdma 갈래를 다시 써야 한다.
3. 펌프가 inbox를 읽으면 증인 소켓의 BYE/FIN을 아무도 읽지 않는다: helper 루프의 poll 묶음(prep 18851–18886, p2 20403–20438, `gdakiTsMain`)에
   증인 펌프를 따로 두고 completion channel fd(`gdakiCtrlRdmaChannelFd`)를 더한 rdma 갈래가 필요하다(깨면 `gdakiCtrlRdmaOnWake`).
4. `gdakiTsCancelRound`(prep 12430, p2 13132)가 `gdakiTsMakeUnknown`(prep 8975, p2 9677; 부름 prep 12438, 12463)으로 증인 소켓을 reset하고,
   `gdakiTsCauseLiveness`(prep 8963, p2 9665)는 모르는 원인 문자열을 DEAD로 친다. 이 뒤끝의 원인은 "QP:<원인>"이므로 기록 QP 원인은 따로 된 갈래가
   필요하다(죽음이 아님; 쓰는 곳 prep 12503, p2 13205).
5. 되살린 상대는 UD REJOIN 뒤 증인 소켓이 없고 `gdakiTsPeerLiveness`(prep 9064, p2 9766)는 `pe.fd < 0`이면 DEAD(prep 9069, p2 9771)다. 증인을
   unknown으로 두고 다시 걸어야 한다.
6. 새 all-gather 칸은 `gdakiTsSetup` 1부의 `cComm->allGather`(prep 19098, p2 20650) 전에 `mine`에 있어야 한다. 그래서 UD QP와 영역(`gdakiCtrlRdmaCreate`)은
   `gdakiTsSetupConnect`(prep 19209, p2 20761)가 아니라 all-gather 전에 만들고, 예비 프로세스의 transcript 칸이 rdma 기록만큼 커진다.
7. STATE 전달은 mirror 두 모드 모두 TCP다: `gdakiHoldTransferStep`(prep 16151, p2 16853)의 dial(prep 16164, p2 16866), `gdakiCkptSpareDataFd`(prep 16371,
   p2 17073)의 accept(prep 16386, p2 17088), `gdakiRsRkeysSend`(prep 10408, p2 11110; 부름 10935, p2 11637)와 `gdakiRsRkeysRecv`(prep 10387, p2 11089; 부름
   16218, p2 16920). 양쪽 다 링 기록과 outbox XFER(`gdakiCtrlRdmaXferSend/Recv`)가 된다.
8. Resume 조건 41–44는 `gdakiRsLocalCheck` 입력(prep 24470–24603, p2 26022–26155; gin-mirror 34–40은 prep 24538, p2 26090) 안 40 뒤에 rdma 갈래로
   들어간다. 42(MTU)와 44(경로 어긋남)는 준비 때 투명 복원을 끈다.

조율 세션이 전한 준비 단계 리뷰(REVIEW_PREP.md)의 것(2a-2가 묶음; ln4 줄 번호는 ln4 호스트 파일 0ab4e636에서 확인함 `[소스]`):

- 받기 seam `gdakiCtrlRecv`/`gdakiCtrlRecvOn`과 REJOIN 답 seam: 응답 쪽 DONE 기다림 ln4 11896, `serveWait` 0의 ACK 기다림 12024, MIRROR_SETUP 기다림 22372,
  예비 프로세스의 REJOIN_ACK/TOKEN/DONE_RS 받기 10192/10235/10297, 듣는 소켓의 REJOIN과 DATA 받기 8765, FAIL 답 8777/9536. 이 뒤끝의 받기는
  `gdakiCtrlRdmaRecv`(쌍의 다음 기록), UD로 온 REJOIN 계열은 `g->udIn`.
- `gdakiCtrlFd(pe)`를 (r, peer)를 받는 seam 셋으로: `gdakiCtrlChanUp`(19곳) ← `gdakiCtrlRdmaUp`/`gdakiCtrlRingUp`, `gdakiCtrlPollFd`(3곳) ←
  `gdakiCtrlRdmaChannelFd`, 대입(1곳) ← `gdakiCtrlRdmaPrepare`/짝 맺기.
- 박동 비교는 "늘어남"(wrapping), REJOIN `nrp`는 생존 READ QP 세대를 싣고 memcpy put/get(이 모형의 `gdakiCtrlNrpPut/Get`; 세대 칸은 헤더 요청 2).
- CONNECTED/PAIR_DONE 운반은 위 결정 2.

그 밖에 2a-2가 할 것: `r->ctrl->ring` 만들기와 없애기(`gdakiCtrlFree` 전에 `gdakiCtrlRdmaDestroy`), 1단계 페이지의 `rxConsumed`와 page 영역 묶기(결정 7),
생존 READ QP의 짝 맺기를 감시 스레드의 넘기기 낱말로 감싸기(지금 `gdakiCtrlRdmaPairAct`는 준비 단계의 `gdakiProbeQp*`를 직접 부름), 준비 단계 자리 표시
`gdakiCtrlRecordToErr`를 `gdakiCtrlRdmaRecordToErr`로, 준비 때 낮은 rank의 `gdakiCtrlRdmaPairStart`와 `NCCL_GIN_TS_CONNECT_MS` 한도, 다시 짝 맺기
`NCCL_GIN_TS_RECONNECT_MS`.

## 2b에 남은 것

- 결정 7: `gdakiStoreOn`을 mirror 끔으로 넓힘, mirror 끈 올리기와 FETCH를 저장소로, 덩어리의 저장소 칸, `gdakiStoreWardToErr`.
- 시험 스위치 `NCCL_GIN_CTRL_TEST_QP_ERR`, `..._DROP_UD`, `..._CREDIT_STALL`(연구 빌드만).
- `gdakiTsSetupConnect`의 MTU(`active_mtu` ≥ 2048)와 fork 검사, `gdakiTsCloseAll`의 BYE 차례(링 BYE 완료를 본 뒤 증인 BYE).
- launcher QP 둘을 helper CQ에(phase 3와 함께), UD 받기의 launcher `from`.
- 이 뒤끝은 verbs 장치에서 한 번도 실행되지 않았다 `[미확인]`: UD GRH 40 B, `get_cq_event`의 dlsym, AH의 RoCE 주소, RTR 전 RECV 64가 실제 NIC에서 맞는지는
  2a-2 뒤 첫 smoke에서 본다.

## 빌드 스크립트 diff (`agent_gc_p2/build_gc_p2.sh` 0a847b32, 작업 공간 `build_gc.sh` 2eb95784 대비)

바뀐 것: `BR=p2` 받음, `D`를 worktree 경로로 고정(사본이 `agent_gc_p2/`에 있음), 입력을 `pin/`(`DI`)에서 읽음, p2의 `PREP_MD5` 기본값, unit과 pre 출력 폴더
`unit_p2_*`, `pre_p2`, `unit`에 `gc_unit_p2.cc`(모형 영역과 `gc_unit_prep.cc` 생성기를 잘라 씀), 개발용 단계 `unitp2`(gc_unit_p2만)와 `syn`(호스트 파일
-fsyntax-only, 세 빌드 플래그), `sites`가 "gin-control (ring)" 영역을 셈에서 뺌, `info`가 고정 입력과 p2 파일의 md5를 적음. 전문은
`agent_gc_p2/logs_p2/build_script.diff`(180줄).

## EXPERIMENT.md 11절과 12절에 넣을 줄 (안)

- 11절: `- [ ] 2단계 2a-1: 링과 짝 맺기 모형, CPU 단위 시험, verbs 뒤끝(빌드만) — 2026-10-17, 부르는 자리 잇기(2a-2)와 2b는 남음`
  (2a-1만 끝난 것이라 "링과 기록" 칸 자체는 체크하지 않음)
- 12절: `| 2026-10-17 | 2단계 2a-1 구현. 준비 단계(gc_layer.diff f5061a31) 위의 impl/gc_layer_p2.diff(d571b977, 1 577줄, 호스트 파일만, 더하기 1 552줄,
  장치 코드 0줄): 영역 "gin-control (ring): model"(링 credit과 세대, 대기열 4 096, inbox 4 096, UD 짝 맺기, REJOIN 멱등 표, outbox)과
  "gin-control (ring): verbs back end"(gdakiCtrlRdma*, 부르는 곳 없음). gc, gcp, gct, gctp 빌드됨(경고 0). tcp 전처리는 정규화 뒤 ln4와 hunk 0(gct,
  gctp, gctc) [측정]. 단위 시험 두 빌드 통과, gc_unit_p2 2 781 801 checks failed 0(rdma) [측정]. 장치 동일성: 프로그램 16 조합과 장치 객체 207개 × 4가 ln4와 같음 [측정]. 헤더 요청은
  impl/rs_ctrl_api_p2.diff. 클러스터 실행 없음, verbs 장치에서 실행 안 함 | impl/notes_p2.md, 스크래치 agent_gc_p2/logs_p2/ |`

### 전문

```diff
--- build_gc.sh
+++ build_gc_p2.sh
@@ -46,10 +46,17 @@
 # All compiles run at nice 19 and idle I/O priority (other studies use this node).
 set -euo pipefail
 STAGE=${1:?stage}
-BR=${BR:?BR=<prep|page|ring|launcher|int>}
-case "$BR" in prep | page | ring | launcher | int) ;; *) echo "unknown work package $BR" >&2; exit 2 ;; esac
+BR=${BR:?BR=<prep|page|ring|launcher|int|p2>}
+case "$BR" in prep | page | ring | launcher | int | p2) ;; *) echo "unknown work package $BR" >&2; exit 2 ;; esac
 SCR=${SCR:-<세션 스크래치>}
-D=$(cd "$(dirname "$0")" && pwd)          # this worktree's control/impl
+# p2 (scratch copy of the worktree's build_gc.sh, phase 2a-1): the worktree's control/impl, fixed (this copy lives in
+# agent_gc_p2/, not there)
+D=${GCD:-/home/unionxic/rdma-error-wt/gin-control/harness/gpu-initiated/gin_recovery/control/impl}
+# p2: the preparation stage's inputs, pinned (the worktree's HEAD fa39bfdc: rs_ctrl_api.h 5e46650e, gc_sites.tsv acc0566e,
+# gc_unit_prep.cc 1a468b99, gc_layer.diff f5061a31, launcher/launcher_msg.h 30a05c7f), copied by `git show HEAD:` into
+# agent_gc_p2/pin/ (the worktree's working copies change under a parallel agent); only gc_unit_p2.cc and the outputs
+# (gc_layer_p2.diff) are the worktree's
+DI=${GCPIN:-<세션 스크래치>/agent_gc_p2/pin}
 MID=$(cd "$D/../../mirror/impl" && pwd)   # gin-mirror's impl (read only)
 RSD=$(cd "$D/../../restore/impl" && pwd)  # gin-restore's impl (read only)
 CUDA=/usr/local/cuda-12.8
@@ -63,6 +70,7 @@
 LAYER=$D/gc_layer_$BR.diff
 [ "$BR" != prep ] || LAYER=$D/gc_layer.diff
 INFO=${INFO:-}
+UTAG=${UTAG:-$BR}  # p2: out/unit_<tag>_<cfg>, out/pre_<tag> (the preparation stage's copied out/unit_*, out/pre stay)
 LN4=$SCR/agent_mi_fix  # gin-mirror's tree, build ln4 (read only)
 W=$SCR/agent_gc_$BR
 OUT=$W/out
@@ -74,6 +82,7 @@
 LN4_HOST=0ab4e636fb19ec5c5a6759edf3ea2d40
 LN4_LIB=c74e6ffb60b9ab8e959a7cfc89b7f55c
 LN4_LIBP=21b0be95b04f4ebeeafd0e6e92eecba0
+[ "$BR" = p2 ] && PREP_MD5=${PREP_MD5:-f5061a31bf8760ad4cbb3b607fa5d19a}  # p2: the pinned preparation stage
 PREP_MD5=${PREP_MD5:-}  # impl/gc_layer.diff's md5 the phases start from (the main session pins it with the prep commit)
 LG() { git -C "$LN4/nccl-src" "$@"; }
 MG() { git -C "$W/nccl-src" -c user.name=build -c user.email=build@localhost "$@"; }
@@ -199,8 +208,8 @@
 } ncclGinRecoverToken_t;'
 api() {
   head_ok
-  same "ctrl API" '^// ---- gin-control: ctrl API [(]begin' '^// ---- gin-control: ctrl API [(]end' "$HOSTF" "$D/rs_ctrl_api.h"
-  same "ctrl seams" '^// ---- gin-control: ctrl seams [(]begin' '^// ---- gin-control: ctrl seams [(]end' "$HOSTF" "$D/rs_ctrl_api.h"
+  same "ctrl API" '^// ---- gin-control: ctrl API [(]begin' '^// ---- gin-control: ctrl API [(]end' "$HOSTF" "$DI/rs_ctrl_api.h"
+  same "ctrl seams" '^// ---- gin-control: ctrl seams [(]begin' '^// ---- gin-control: ctrl seams [(]end' "$HOSTF" "$DI/rs_ctrl_api.h"
   local o=$OUT/api; mkdir -p "$o"
   { echo "$PRELUDE"
     for h in rs_hold_api.h rs_mirror_api.h rs_log_api.h rs_ckpt_api.h rs_store_api.h rs_spare_api.h rs_lineage_api.h; do
@@ -210,9 +219,9 @@
     echo 'int main() { return 0; }'; } > "$o/headers.cc"
   local f
   for f in "" "-DNCCL_GIN_CTRL_TCP=1"; do
-    g++ -std=c++17 -Wall -Wextra -Werror -Wno-unused-function $f -fsyntax-only -I"$D" -I"$MID" "$o/headers.cc"
+    g++ -std=c++17 -Wall -Wextra -Werror -Wno-unused-function $f -fsyntax-only -I"$DI" -I"$MID" "$o/headers.cc"
     g++ -std=c++17 -Wall -Wextra -Werror -Wno-unused-function $f -DGDAKI_MI_API_NO_ENTRY_DECLS -DGDAKI_HOLD_API_NO_ENTRY_DECLS \
-      -DGDAKI_CTRL_API_NO_ENTRY_DECLS -fsyntax-only -I"$D" -I"$MID" "$o/headers.cc"
+      -DGDAKI_CTRL_API_NO_ENTRY_DECLS -fsyntax-only -I"$DI" -I"$MID" "$o/headers.cc"
   done
   echo "api: rs_ctrl_api.h compiles with gin-mirror's seven headers (g++ -fsyntax-only; rdma and tcp; with and without the" \
        "entry-point declarations); launcher/launcher_msg.h $( [ -f "$D/launcher/launcher_msg.h" ] && echo "present: its envelope checked" || echo absent)"
@@ -266,9 +275,9 @@
 }
 unit1() {  # unit1 <cfg rdma|tcp> <label> <source> [extra g++ args]: one CPU unit test against the cut regions
   local c=$1 n=$2 src=$3; shift 3
-  local o=$OUT/unit_$c f=""
+  local o=$OUT/unit_${UTAG}_$c f=""
   [ "$c" = tcp ] && f="-DNCCL_GIN_CTRL_TCP=1"
-  GXX $f "$@" -I"$o" -I"$D" -I"$MID" -I"$W/nccl-src/src/include" "$src" -o "$o/$n"
+  GXX $f "$@" -I"$o" -I"$DI" -I"$MID" -I"$W/nccl-src/src/include" "$src" -o "$o/$n"
   "$o/$n"
 }
 unit() {
@@ -276,7 +285,7 @@
   local cfgs="${CFG:-both}" c
   [ "$cfgs" = both ] && cfgs="rdma tcp"
   for c in $cfgs; do
-    local o=$OUT/unit_$c; mkdir -p "$o"
+    local o=$OUT/unit_${UTAG}_$c; mkdir -p "$o"
     regions "$o"
     echo "== unit ($c build: $([ "$c" = tcp ] && echo "-DNCCL_GIN_CTRL_TCP=1" || echo "no switch"))"
     local x
@@ -304,7 +313,32 @@
     else
       echo "unit ($c): the tree's TCP back end differs from ln4's" >&2; exit 1
     fi
-    unit1 "$c" gc_unit_prep "$D/gc_unit_prep.cc" -DGDAKI_CTRL_API_NO_ENTRY_DECLS
+    unit1 "$c" gc_unit_prep "$DI/gc_unit_prep.cc" -DGDAKI_CTRL_API_NO_ENTRY_DECLS
+    if [ "$BR" = p2 ]; then
+      # gc_unit_p2.cc (phase 2a-1): the tree's ring and pairing models (rdma build only; empty in the tcp build), the
+      # record generator of gc_unit_prep.cc (kTypes and fillRandom, cut as they are) and ln4's TCP back end
+      # (gc_ln4_sock.inc above)
+      # (the region is inside #if !NCCL_GIN_CTRL_TCP: empty in the tcp build)
+      cut1 "$o/gc_ring_model.inc" '^// ==== gin-control [(]ring[)]: model [(]begin' '^// ==== gin-control [(]ring[)]: model [(]end'
+      region '^static const uint32_t kTypes' '^}$' "$DI/gc_unit_prep.cc" > "$o/gc_prep_gen.inc"
+      [ "$(grep -c '^static void fillRandom(' "$o/gc_prep_gen.inc")" = 1 ] || { echo "unit: gc_unit_prep.cc's generator not found" >&2; exit 1; }
+      unit1 "$c" gc_unit_p2 "$D/gc_unit_p2.cc" -DGDAKI_CTRL_API_NO_ENTRY_DECLS
+    fi
+  done
+}
+unitp2() {  # p2 only: gc_unit_p2.cc alone (the development loop; `unit` runs it after every other test)
+  head_ok
+  local cfgs="${CFG:-both}" c
+  [ "$cfgs" = both ] && cfgs="rdma tcp"
+  for c in $cfgs; do
+    local o=$OUT/unit_${UTAG}_$c; mkdir -p "$o"
+    regions "$o"
+    cutdefs "$LN4/nccl-src/$HOSTF" "$o/gc_ln4_sock.inc" '#define GDAKI_TS_MAGIC ' 'struct gdakiTsMsg {' 'struct gdakiTsPeer {' \
+      'static const char* gdakiTsErrName(' 'static int gdakiTsSend(' 'static int gdakiTsPumpRaw(' 'static int gdakiTsPump('
+    cut1 "$o/gc_ring_model.inc" '^// ==== gin-control [(]ring[)]: model [(]begin' '^// ==== gin-control [(]ring[)]: model [(]end'
+    region '^static const uint32_t kTypes' '^}$' "$DI/gc_unit_prep.cc" > "$o/gc_prep_gen.inc"
+    echo "== unitp2 ($c build)"
+    unit1 "$c" gc_unit_p2 "$D/gc_unit_p2.cc" -DGDAKI_CTRL_API_NO_ENTRY_DECLS
   done
 }
 cutdefs() {  # cutdefs <host file> <out> <start>...: for each start (a line prefix): a #define line as it is, a struct up to
@@ -345,7 +379,7 @@
     grep -v '^[[:space:]]*$' > "$2"
 }
 pre1() {  # pre1 <label> <build dir> <CXXFLAGS of that build>
-  local lab=$1 b=$2 fl=$3 o=$OUT/pre
+  local lab=$1 b=$2 fl=$3 o=$OUT/pre_${UTAG}
   mkdir -p "$o"
   local cmd; cmd=$(precmd "$W/$b" "$fl")
   [ -n "$cmd" ] || { echo "pre: no compile command of the host file for $b (make -n)" >&2; exit 1; }
@@ -364,6 +398,13 @@
        "raw diff $(grep -c '^[<>]' "$o/${lab}.raw.diff") lines; normalized: ln4 $(md5 "$o/${lab}_ln4.n.i"), ours $(md5 "$o/${lab}.n.i")," \
        "$(grep -c '^@@' "$o/${lab}.norm.diff" || true) hunks, $(grep -c '^[-+][^-+]' "$o/${lab}.norm.diff" || true) changed lines"
 }
+syn() {  # p2 only: the host file's compile command of build dir $1 with flags $2, -fsyntax-only (the development loop)
+  head_ok
+  local cmd; cmd=$(precmd "$W/$1" "$2")
+  [ -n "$cmd" ] || { echo "syn: no compile command for $1" >&2; exit 1; }
+  cmd=$(echo "$cmd" | sed -E 's# -c transport/net_ib/gdaki/gin_host_gdaki\.cc# -fsyntax-only transport/net_ib/gdaki/gin_host_gdaki.cc#; s# -o [^ ]+\.o##')
+  (cd "$W/nccl-src/src" && eval "nice -n 19 $cmd") && echo "syn $1: the host file compiles (-fsyntax-only)"
+}
 pre() {
   head_ok
   pre1 gct build-gct "-DNCCL_GIN_CTRL_TCP=1"
@@ -381,7 +422,7 @@
     echo "sites: $s( lines: ln4 $(grep -cE "\\b$s\\(" "$l" || true), tree $(grep -cE "\\b$s\\(" "$f" || true)"
   done
   echo "sites: pe.fd lines: ln4 $(grep -cE '\bpe\.fd\b' "$l"), tree $(grep -cE '\bpe\.fd\b' "$f")"
-  python3 - "$D/gc_sites.tsv" "$l" "$f" <<'PY2'
+  python3 - "$DI/gc_sites.tsv" "$l" "$f" <<'PY2'
 import re, sys
 from collections import Counter
 tsv, ln4, tree = sys.argv[1:4]
@@ -392,7 +433,7 @@
 def code(lines):  # the code lines of the tree outside the pasted blocks and the preparation stage's own region
     out, skip = [], False
     for l in lines:
-        if re.match(r'^// (----|====) gin-control(:| \(prep\))', l): skip = '(begin' in l
+        if re.match(r'^// (----|====) gin-control(:| \((prep|ring)\))', l): skip = '(begin' in l
         elif not skip and not l.lstrip().startswith('//') and not l.lstrip().startswith('#define'): out.append(l)
     return out
 C = code(T)
@@ -539,8 +580,10 @@
     echo "include_digest build $(cd "$W/build/include" && find . -type f | LC_ALL=C sort | xargs md5sum | md5sum | cut -c1-32)"
     echo "include_digest ln4 $(cd "$LN4/build/include" && find . -type f | LC_ALL=C sort | xargs md5sum | md5sum | cut -c1-32)"
     for f in rs_ctrl_api.h gc_sites.tsv build_gc.sh gc_unit_prep.cc launcher/launcher_msg.h; do
-      [ -f "$D/$f" ] && echo "$f $(md5 "$D/$f") $(wc -l < "$D/$f") lines"
+      [ -f "$DI/$f" ] && echo "pinned $f $(md5 "$DI/$f") $(wc -l < "$DI/$f") lines"
     done
+    for f in gc_unit_p2.cc notes_p2.md; do [ -f "$D/$f" ] && echo "$f $(md5 "$D/$f") $(wc -l < "$D/$f") lines"; done
+    echo "build_gc_p2.sh $(md5 "$0") $(wc -l < "$0") lines"
   } > "${INFO:-$OUT/build_info.txt}"
   cat "${INFO:-$OUT/build_info.txt}"
 }
@@ -553,7 +596,9 @@
   gct) lib build-gct "$GCTOUT" "-DNCCL_GIN_CTRL_TCP=1" ;;
   gctp) lib build-gctp "$GCTPOUT" "-DNCCL_GIN_TS_PRODUCTION -DNCCL_GIN_CTRL_TCP=1" ;;
   unit) unit ;;
+  unitp2) [ "$BR" = p2 ] || { echo "unitp2 is p2's" >&2; exit 2; }; unitp2 ;;
   pre) pre ;;
+  syn) [ "$BR" = p2 ] || exit 2; syn build "" && syn build-gcp "-DNCCL_GIN_TS_PRODUCTION" && syn build-gct "-DNCCL_GIN_CTRL_TCP=1" ;;
   sites) sites ;;
   ident) ident ;;
   diff) mkdiff ;;
```
