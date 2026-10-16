# gin-control 2단계 2b: 결정 7(mirror 끈 저장소 길), 저장소 몫의 활성화 덩어리, `gdakiStoreWardToErr`, STATE와 rkey 목록의 outbox 차례 (작업 기록)

## 단계 목록 (처음에 적은 계획)

1. `agent_gc_int/` 트리를 `agent_gc_p2b/`로 복사, 머리 커밋이 "gin-control int (gc_layer_int.diff a7600a46)"인지 확인
2. `agent_gc_p2b/build_gc_p2b.sh`(BR=p2b 키, 바탕은 int 커밋, unit에 `gc_unit_p2b.cc`)
3. 순수 영역 "gin-control (store): pure": 전송 머리, 차례 검사, 덩어리 규칙, 저장소 ERR 규칙, 메모리 셈
4. 호스트 영역 "gin-control (store): host": STATE와 rkey의 outbox 길(링이 없으면 TCP, `TODO(2a-2)`), 메모리 줄
5. ln4 줄의 `#if` 갈래: `gdakiStoreOn` 넓힘, 저장소 스레드의 ERR 일, drain 건너뜀, 덩어리 받기, FETCH 받기, 활성화 두 줄
6. `gdakiStoreWardToErr` 몸(준비 단계 자리 표시 "[2] ring" 안)
7. `syn`, `api`, `sites`
8. `gc_unit_p2b.cc`(ASan, UBSan), `unit` 두 빌드
9. 빌드 넷, `pre`, `ident`, `diff`, `info`
10. 이 문서 마무리(결정, 차례, 헤더 요청, 수, 표, EXPERIMENT 11/12절 안)

## 끝낸 단계 (한 단계 한 줄)

- 1 끝: agent_gc_p2b/ 복사(nccl-src, 빌드 넷; .d와 manifest 경로 다시 씀), 머리 b80ebda "gin-control int (gc_layer_int.diff a7600a46)"는 원본에 이미 있었음(04:06 커밋), ln4 커밋 대비 diff md5 a7600a46 확인
- 2 끝: `agent_gc_p2b/build_gc_p2b.sh`(worktree `build_gc.sh` 5eaaf11e를 복사해 BR=p2b 키, 바탕 커밋 int, `D` 고정, regions에 store 순수 영역과 rkey 목록의 TCP 글, `unit`에 `gc_unit_p2b.cc`, `unitp2b`, `info`)
- 3–6 끝: 영역 "gin-control (store)"(순수 + 호스트)를 "[2] ring" 하위 영역 끝에, 앞 선언 블록을 ctrl seams 블록 뒤에, ln4 줄의 `#if` 갈래 여섯과 `#if !NCCL_GIN_CTRL_TCP` 덧붙임 여섯, `gdakiStoreWardToErr` 자리 표시 몸 한 줄(`agent_gc_p2b/edit_host.py`)
- 7 끝: `syn` 세 빌드 통과, `api` 통과(블록 바이트 같음, 헤더 바뀜 없음), `sites` 통과(갈래 33 → 39, 모두 ln4 글 그대로)
- 8a: `gc_unit_p2b.cc` 개발 고리(`unitp2b`, rdma): 시도 다섯(restore 헤더 겹침, spare 순수 영역의 도우미 둘, 반복 XFER가 END 뒤에 남는 모형 빈틈) 뒤 11 114 검사 실패 0, 두 번 돌려 같음
- 8 끝: `unit` 두 빌드 통과(옛 시험 일곱과 gc_unit_prep, p1, gate_fenced, p2 그대로; gc_unit_p2b rdma 11 114 검사, tcp 0 검사), `logs_p2b/unit_p2b.log`
- 9a: 빌드 넷 첫 판 빌드됨(경고 0; 로그 `logs_p2b/first_build/`). 그 뒤 주석 한 줄(128자 넘음)을 줄여 같은 넷을 새 out 폴더(`*_p2b_f`)로 다시 빌드
- 9 끝: 빌드 넷 다시 빌드됨(경고 0, libnccl md5가 첫 판과 같음: 주석만 바뀜), `pre`(gct, gctp 0 hunk; gctc RST 간격 2 hunk 3줄만), `diff`(`gc_layer_p2b.diff`), 그 뒤 `unit`, `ident`, `info`(아래 표)

## 무엇을 했나

트리는 스크래치 `agent_gc_p2b/`다. `agent_gc_int/`의 nccl-src와 빌드 넷을 복사했고, 그 머리 커밋 b80ebda "gin-control int (gc_layer_int.diff a7600a46)"(고침 에이전트가 04:06에 만든 것)가 이미 int 작업 트리를 담고 있어 새로 커밋하지 않았다. ln4 커밋 대비 그 커밋의 diff md5가 `a7600a46`임을 확인했다 `[측정]`. 이 작업은 그 위의 작업 트리이고, 호스트 파일 하나만 바꾼다(장치 코드 0줄). 클러스터, ssh, verbs 장치, GPU 실행은 없다. `git add`, commit, push는 하지 않았다. 표시: [측정] 이 작업이 돌려서 본 것, [추론] 해석, [소스] 코드를 읽어 확인, [미확인] 확인 안 함.

구현한 것(rdma 빌드만; tcp 빌드에는 없음):

1. **결정 7, 저장소 길을 mirror 끔으로.** `gdakiStoreOn`이 rdma 빌드에서 `gdakiMiOn` 없이 "체크포인트 기계가 있는 프로세스"면 참이다. gin-mirror의 저장소 길은 모든 자리가 `gdakiStoreOn`으로 갈리므로(COPYING의 `gdakiStoreArm`, CONFIRMING, CKPT_STABLE의 짝 갈래, `gdakiCkptTake`의 `gdakiStoreTake`, `gdakiHoldSpareOf`의 등록, 짝의 RESTORED) mirror 끈 체크포인트도 그 길로 간다: 입력 멈춤 안 D2H, 멈춤 밖 올리기 QP의 WRITE, 늘 전체 이미지, CKPT_STABLE에 배치 `[소스]`. TCP UPLOAD와 TCP FETCH(`gdakiCkptStartUpload`, `gdakiCkptServeUpload`, `gdakiCkptServeFetch`, `gdakiCkptSpareFetch`의 TCP 부분)는 지우지 않았고 rdma 빌드에서는 닿지 않는다 `[추론]`.
2. **예비 프로세스의 저장소 FETCH와 덩어리의 저장소 칸.** 활성화 v2를 고르는 술어 `gdakiStoreActV2` = mirror 켬 또는 저장소 켬. 짝 쪽은 `gdakiHoldActivateSend`의 `mi` 한 줄, 예비 쪽은 `gdakiRsSpareActivateWait`의 `mi` 한 줄을 그 술어로(3단계 함수: 합칠 때의 자리). mirror 끔에는 비울 lane이 없어 `gdakiMiDrainStep`이 곧바로 0(drained)을 돌려주고, `gdakiMiActBlobFor`는 손대지 않았다: pool 정보가 없으므로 덩어리는 `GDAKI_MI_ACTB_F_STORE`만, 범위(extent) 0, pool rkey 0이다 `[소스]`. 예비 쪽 `gdakiMiActRecv`는 mirror 끔에서도 v2를 받고, mirror 끔인데 pool 칸이 있으면 12로 거절한다. `gdakiCkptSpareFetch`는 v2이면 RDMA FETCH의 결과(`gdakiMiSpareFetchTake`)를 쓴다. FETCH 버퍼(`NCCL_GIN_RESTORE_MIRROR_FETCH_MB`, 기본 512 MiB)는 mirror 끈 예비 프로세스에도 활성화 소켓 전에 잡힌다.
3. **`gdakiStoreWardToErr`.** hold 시작(`gdakiCtrlPeerToErr`)에서 죽은 rank가 이 rank가 맡은 ward의 주인이면(이 rank = buddy(dead)), 그 ward의 올리기 QP의 이쪽 끝을 ERR로 보낸다. QP의 주인은 저장소 스레드이므로 helper는 일(kind 3, `GDAKI_CTRL_STORE_JOB_WARD_ERR`)만 넣고 저장소 스레드가 `ibv_modify_qp(ERR)`를 한다. 기록, MR, stable 칸은 그대로라 FETCH QP의 READ는 영향이 없고, 후계자의 STORE_REQ가 옛 QP를 없애고 새로 만든다. 주인이 살아 있는 ward의 QP와 맡긴 쪽(이 rank의 짝이 죽은 경우)의 올리기 QP는 건드리지 않는다. 두 번 불러도 같다. ln4의 hold 시작은 저장소 QP를 건드리지 않는다 `[소스: grep, hold machine 영역에 저장소 QP 쓰임 0]`.
4. **STATE와 rkey 목록의 outbox 차례.** 아래 "기록과 XFER 차례". 짝의 링이 있으면 세 전송, 없으면 ln4의 자료 소켓 그대로. 지금은 `r->ctrl->ring`이 늘 null이라 늘 자료 소켓이다(`TODO(2a-2)`).
5. **메모리 보고 줄.** STORE_REQ가 나갈 때 이미지 크기가 바뀌었으면 한 줄: `GIN/CTRL: rank r: host memory added (decision 7, mirror on|off): staging .. MiB (pinned, slot .. bytes), ward stores n x 2 slots .. MiB, control .. MiB (ring up|ring not made yet), total .. MiB = 3 x image + .. MiB, image .. MiB (reported, no bound)`. 한도는 두지 않는다(2026-10-17 결정 (가): 한도는 BAR1의 것).

## 설계의 자유 안에서 정한 것

1. 저장소 길을 켜는 조건은 "복원 켬"(체크포인트 기계 `r->hold->ckpt`가 있음)이다. rdma 빌드에서 mirror 끈 복원 프로세스는 모두 저장소를 쓴다. 저장소 상태와 그 스레드는 첫 `gdakiStoreStep`에서 만들어진다(mirror 켬과 같음).
2. 활성화 v2의 술어 하나(`gdakiStoreActV2`)를 짝과 예비 쪽이 함께 쓴다. 3단계가 활성화를 launcher 중계로 옮길 때 이 술어를 그대로 쓰면 된다(덩어리는 kind 4 ACTB로 outbox에 실을 수 있게 전송 머리에 자리를 둠).
3. mirror 끔 덩어리는 새 함수로 짓지 않고 `gdakiMiActBlobFor`를 그대로 쓴다(drain만 건너뜀). 예비 쪽 거절 12 "pool 칸 있는 덩어리를 mirror 없는 예비 프로세스가 받음"을 더했다.
4. 주소 표: mirror 끈 예비 프로세스도 v2 덩어리를 받으므로 `gdakiMiApplyAddrTable`이 돈다. 규칙은 gin-mirror 그대로(화신 0 생존 rank는 기록 주소, 되살린 rank는 표의 주소)라 첫 복원에서는 바뀌는 것이 없다 `[추론]`. gin-mirror 9.4의 "mirror 끔은 기록 주소"와 다른 점이다.
5. `gdakiStoreWardToErr`는 ERR까지만 한다(없애지 않음). 이유: QP의 주인 스레드 규칙과 "늦은 WRITE가 닿지 않음"의 목적은 ERR로 충분하고, 없애기는 후계자의 STORE_REQ가 하는 지금 차례(`gdakiStoreServe` (1))에 맡긴다.
6. STATE 차례는 **예비 프로세스가 시작한다**(STATE_REQ). 예비 프로세스는 생존 rank를 하나씩(rank 차례) 받으므로, 생존 rank의 helper 걸음은 자기 쌍에 전송이 올 때까지 "아직"(1)으로 돌아가 막히지 않는다(TCP에서는 dial과 첫 기록이 그 일을 함). 세 전송 모두 outbox XFER이고 기록이 아니므로 기록 층의 펌프와 hold 기계는 보지 않는다.
7. 전송 머리 64 B(`gdakiCtrlXferHdr`: magic "GRXH", 판, kind, from, to, 화신, nonce, ckpt, bytes, 해시). 검사는 kind, 쌍, nonce, 화신, 크기(kind의 한도), 해시 순. 머리 요청은 `rs_ctrl_api_p2b.diff`.
8. 예비 쪽 `gdakiCkptSpareDataFd`가 outbox로 받았으면 소켓 대신 `GDAKI_CTRL_XFER_NOFD`(0x7fffffff)를 돌려준다. 그 값은 `d->fds`에 넣지 않고(닫지 않음), rkey 자리의 `gdakiCtrlRkeysHandOver`가 그 값이면 outbox, 아니면 ln4의 `gdakiRsRkeysSend`로 보낸다.
9. 메모리 줄의 control 몫은 2a-1 뒤끝의 실제 할당 상수로 센다(받기와 보내기 칸 rank마다 64 × 2 KiB씩, UD 64 × 2 088 B와 64 × 2 KiB, outbox 2 MiB, READ 칸 1 MiB, 낱말 쪽 둘, 페이지 4 KiB). 링이 아직 없으면 줄에 "ring not made yet"이라 적고 몫은 계획대로 센다. ward 이미지는 모르므로 자기 이미지로 어림한다(시험 셀의 p xor 1 짝은 같은 크기 `[추론]`).

## 기록과 XFER 차례 (STATE, rkey 목록; 두 mirror 모드 모두)

REJOIN이 받아들여지고 쌍 (생존 rank s, 예비 프로세스 d)의 링이 새 세대로 선 뒤. 모두 outbox 전송 하나(`gdakiCtrlRdmaXferSend/Recv`: 반 하나 이상, 마지막에 END, 반마다 XFER_DONE)이고 앞에 64 B 머리가 붙는다.

| 차례 | 방향 | kind | 본문(ln4 자료 소켓의 바이트 그대로) | 머리의 화신, ckpt | 받는 쪽 검사 |
|---|---|---|---|---|---|
| 1 | d → s | STATE_REQ(1) | DATA 답 기록 1 872 B(type DATA, from d, arg d, round K, pad 0; magic 찍음) | d의 화신, K | 머리; 기록의 magic, type, from, nonce(ln4 검사), round = K, pad = 0(아니면 거절); s의 cut K |
| 2 | s → d | STATE(2) | `uint64 n` 다음 n바이트 export(v1, mirror면 v2) | s가 아는 d의 화신(계보의 현재), K | 머리; ckpt = d의 K; n ≤ 1 GiB이고 본문 길이 = 8 + n |
| 3 | d → s | RKEYS(3) | `gdakiRsRkeysHdr` 32 B + count × 16 B | d의 화신, 0 | 머리; magic, 판 1, count ≤ 4 096, 길이 = 32 + 16 × count |

- 생존 쪽(`gdakiHoldTransferStep` 맨 앞): 링이 없으면 2를 돌려 ln4 길로. 있으면 쌍에 전송이 없을 때 1(아직), 있으면 1을 읽고 export, 2를 보내고, 3을 받아 `hp.rkeys`에 둔 뒤 0. 실패는 -1(fallback).
- 예비 쪽(`gdakiCkptSpareDataFd`, FETCH 뒤): 링이 없으면 ln4 길. 있으면 1을 보내고 2를 받아 `exports[peer]`에 두고 `GDAKI_CTRL_XFER_NOFD`. rkey 자리(`gdakiRsSpareRejoinAll`)에서 3.
- 바이트 동일: 1의 본문은 ln4 `gdakiTsSend`가 소켓에 쓰는 답 기록과 같고, 2의 본문은 ln4가 소켓에 쓰는 `n`과 export와 같고, 3의 본문은 `gdakiRsRkeysSend`가 쓰는 바이트와 같다(단위 시험 3이 AF_UNIX 쌍으로 대조) `[측정]`.
- 2a-2가 맞출 것: 두 쪽이 같은 조건(`gdakiCtrlRdmaUp`)으로 길을 고르므로, 한쪽만 링이 섰다고 보면 두 쪽 다 한도까지 기다린 뒤 fallback한다(안전하나 느림) `[추론]`. REJOIN 세대에서 두 쪽의 CONNECTED가 같은 때 서게 해야 한다.

## TODO(2a-2)로 남긴 것

- `r->ctrl->ring` 만들기: 지금 `gdakiCtrlStateRingOf`는 늘 null을 돌려 STATE와 rkey 목록이 자료 소켓으로 간다(코드의 `TODO(2a-2)` 둘: 그 함수와 메모리 줄의 링 표시).
- 예비 프로세스는 helper 없이 `gdakiCtrlRdmaXferSend/Recv`의 poll로 링을 돌린다. 2a-2가 REJOIN으로 예비 프로세스의 기록 QP를 세우면 그대로 쓰인다.
- 생존 쪽 `gdakiCtrlXferPending`은 helper 걸음에서 `gdakiCtrlRdmaPoll`과 `gdakiCtrlRdmaTakeXfers`를 부른다(같은 helper 스레드; 기록은 inbox에 그대로 둠). 2a-2의 helper 루프가 같은 poll을 돌려도 겹침은 없다 `[추론]`.
- 2a-1의 `gdakiCtrlRdmaXferSend`는 마지막 XFER_DONE까지 기다린다. 생존 쪽 2(STATE)는 예비 프로세스가 곧바로 읽으므로 짧지만, 크면 helper 걸음이 그만큼 길다(TCP의 export 보내기와 같은 꼴) `[추론]`.

## 이 작업이 하지 않은 것 (notes_p2.md "2b에 남은 것" 가운데)

- 시험 스위치 `NCCL_GIN_CTRL_TEST_QP_ERR`, `..._DROP_UD`, `..._CREDIT_STALL`, `gdakiTsSetupConnect`의 MTU와 fork 검사, `gdakiTsCloseAll`의 BYE 차례, launcher QP 둘. 이번 지시의 범위(결정 7, 덩어리의 저장소 칸, `gdakiStoreWardToErr`, rkey와 STATE의 outbox, 메모리 줄) 밖이라 손대지 않았다.
- verbs 장치와 GPU에서 한 번도 돌지 않았다 `[미확인]`: mirror 끈 저장소 길(STORE_REQ/ACK, WRITE, FETCH)이 실제 NIC에서 mirror 켬과 같이 도는지, `ibv_modify_qp(ERR)` 뒤 늦은 WRITE가 원격 오류로 끝나는지, 메모리 줄의 실제 값.
- 바뀌는 사전 예측(설계 v3 2.8: `none_clean`의 멈춤 ≤ 10 ms, `rg_*`)은 문서 몫이다. mirror 끈 rdma 빌드의 멈춤은 D2H만큼 는다 `[추론]`.

## 헤더 요청 (`impl/rs_ctrl_api_p2b.diff`, 고정 헤더 948b3ecf에 대해)

- ctrl API 블록 "[2] ring" 하위 블록에 전송 머리(`GDAKI_CTRL_XFERH_MAGIC`, `_VERSION`, kind 넷, `struct gdakiCtrlXferHdr` 64 B와 단언). launcher(3단계, ACTB)와 나누기 위함. 들어가면 호스트 영역 "gin-control (store): pure"의 같은 정의를 지운다. 패치한 헤더는 gin-mirror 헤더 일곱과 함께 `g++ -std=c++17 -Wall -Wextra -Werror -fsyntax-only`로 rdma와 tcp에서 컴파일됨(`agent_gc_p2b/hdr/`; launcher 헤더 대조는 그 폴더에 launcher/가 없어 건너뜀) `[측정]`.
- 이 작업의 트리는 헤더를 바꾸지 않았다(`api` 통과: 붙인 블록이 948b3ecf와 바이트 같음).

## 빌드 스크립트 diff (`agent_gc_p2b/build_gc_p2b.sh`, worktree `build_gc.sh` 5eaaf11e 대비)

바뀐 것: `BR=p2b` 받음, `D`를 worktree 경로로 고정(`GCIMPL`로 바꿀 수 있음), p2b의 머리 커밋 "gin-control int (gc_layer_int.diff a7600a46)", `regions`가 p2b에서 1단계와 2a-1 영역을 int처럼 자르고 "gin-control (store): pure"(`gc_store_pure.inc`)와 rkey 목록의 TCP 함수 셋(`gc_p2b_rs.inc`: `gdakiRsIoAll`, `gdakiRsRkeysRecv`, `gdakiRsRkeysSend`; 형은 gin-mirror `rs_spare_api.h`의 공유 글)을 더 자름, `unit`이 p2b에서 int의 시험 다음에 `gc_unit_p2b.cc`, 개발용 `unitp2b`, `info`가 p2b 파일과 스크립트의 md5를 적음. `diff`는 p2b에서 작업 트리 대 머리 커밋(int). 전문은 `agent_gc_p2b/logs_p2b/build_script.diff`(90줄).
- 9b: worktree의 `gc_unit_p1.cc`, `gc_unit_p2.cc`, `gate_fenced.cc`, `gc_sites.tsv`를 고침 에이전트가 이 작업 중에 바꿨다(그쪽 트리의 새 함수를 부름). 그래서 마지막 `unit`은 worktree HEAD의 시험 소스를 `agent_gc_p2b/testpin/`(GCTEST), `api`, `sites`, `unit`, `info`는 HEAD의 입력(`rs_ctrl_api.h`, `gc_sites.tsv`, `gc_unit_prep.cc`, `launcher/launcher_msg.h`)을 `agent_gc_p2b/pin/`(GCPIN, 스크립트에 p2b 줄 하나 더함)으로 고정해 다시 돌렸다. 바뀐 worktree 시험으로 돌린 판은 `gc_unit_p1.cc`가 이 트리에 없는 함수를 불러 컴파일되지 않음(`logs_p2b/dev/unit_p2b_worktree_tests_moved.log`, 이 작업의 결함이 아님)

## 수 (이 작업이 센 것)

- `gc_layer_p2b.diff`: int 커밋 대비 639줄, hunk 15, 호스트 파일 하나, 더하기 512줄, 빼기 5줄(`gdakiStoreWardToErr` 자리 표시 몸 4줄과 그 주석 1줄), 장치 코드 0줄 `[측정]`.
- 그 가운데 영역 "gin-control (store)" 428줄(순수 228줄, 호스트 187줄), 앞 선언 블록 20줄, ln4 줄의 `#if NCCL_GIN_CTRL_TCP` 갈래 여섯(`gdakiStoreOn`, `gdakiMiActRecv`의 거절 8, `gdakiCkptSpareFetch`, 활성화의 `mi` 둘, rkey 자리)과 `#if !NCCL_GIN_CTRL_TCP` 덧붙임 여섯(저장소 스레드 일, 저장소 상태의 낱말, 메모리 줄 부름, drain 건너뜀, 거절 12, STATE 갈림 둘) `[측정]`.
- 호스트 파일 28 143 → 28 652줄, md5 `9cf313bd` `[측정]`.
- 고침 에이전트 트리(04:46 무렵의 스냅숏, 호스트 파일 md5 `c258d4c9`, 작업 트리 +1 721/−410) 위에 `patch --dry-run -p1`: hunk 15/15 적용(offset만) `[측정]`. 합칠 때 충돌 없을 것이라는 뜻은 그 스냅숏에 대해서만이다.
- `gc_unit_p2b.cc` 828줄, rdma 11 114 검사(머리 5 218, outbox 268, STATE 1 535, ward ERR 1 126, 올리기 같음, 덩어리, 메모리), tcp 0 검사 `[측정, n 1]`.
- 올리기 같음 시험: 같은 체크포인트 열에서 두 길 모두 stable이 된 체크포인트 125개를 견줌. 올린 바이트는 TCP 42 042 638(바뀐 블록), 저장소 94 806 977(늘 전체 칸) `[측정: unit_p2b.log]`.
- 메모리 셈(rank 4, I = 20 MiB): staging 21.06 MiB, ward 저장소 42.12 MiB(2 칸), control 4.26 MiB, 합 67.45 MiB = 3I + 7.45 MiB `[측정: 셈]`. 설계 v3 3.5의 "약 3I + 5 MiB"보다 큰 까닭: 칸 하나가 I + 64 KiB 머리 + 1 MiB 덩어리 자리라 3칸이면 3I + 3.2 MiB, 2a-1 뒤끝의 실제 할당이 설계 표의 2.9 MiB보다 큼(받기와 보내기 칸 1 MiB, outbox 2 MiB, READ 칸 1 MiB, UD 0.26 MiB) `[추론]`.

## 확인 표 (이 작업이 돌린 것만; 로그는 `agent_gc_p2b/logs_p2b/`)

| 단계 | 결과 | 로그 |
|---|---|---|
| `syn` | build, build-gcp, build-gct에서 호스트 파일 `-fsyntax-only` 통과 [측정] | `syn_p2b.log` |
| `api` (GCPIN) | 붙인 블록 둘이 헤더 948b3ecf와 바이트 같음(ctrl API `5df6bf40`, seams `1d1a4950`), 헤더 단독 컴파일 rdma와 tcp, 진입점 선언 있음/없음, `NCCL_GIN_CTRL_TCP_CELLS=1` 단독 거절: 통과 [측정] | `api_p2b.log` |
| `sites` (GCPIN, tsv 6cd637e5) | 149행과 트리의 rdma 쪽 셈이 모두 같음, `#if NCCL_GIN_CTRL_TCP` 갈래 39개(int 33 + 이 작업 6) 모두 ln4 글 그대로, 단계 영역 `#use` 같음(page 413, ring 1 381 코드 줄): 통과 [측정] | `sites_p2b.log` |
| `gc`, `gcp`, `gct`, `gctp` | 넷 모두 빌드됨, 경고 0, 다시 컴파일한 것은 호스트 파일(와 git_version) 하나, 장치 객체 다시 빌드 없음. libnccl gc `0faa344d`, gcp `51b3e750`, gct `07f5dfbc`, gctp `294fa21c`; 첫 판과 주석 한 줄 고친 판이 같은 md5 [측정]. gct, gctp의 md5가 int(`130af8dd`, `2c2ea799`)와 다른 것은 줄 번호(`__LINE__`)가 밀렸기 때문으로 본다 [추론: 정규화한 전처리 결과는 ln4와 같음] | `build_{gc,gcp,gct,gctp}_p2b.log`, `out/*_p2b_f/` |
| `pre` | gct, gctp 정규화 뒤 ln4와 0 hunk(줄 수 같음 150 748, 150 175); gctc 2 hunk 3줄(1단계 RST 거절 간격 매개변수 정의 한 줄과 `>= 1000.0` 한 줄, int와 같음); gc 78 hunk(새 코드, 기록용) [측정] | `pre_p2b.log`, `out/pre/` |
| `unit` (GCPIN, GCTEST) rdma | mi_unit 다섯, rs_unit_host 348 739, rs_spare_unit 171 실패 0; gc_unit_prep 366, gc_unit_p1 84 672, gate_fenced 10/10 24 검사, gc_unit_p2 2 781 807 실패 0(int와 같은 수); gc_unit_p2b 11 114 실패 0: 통과 [측정, n 1] | `unit_p2b.log` |
| `unit` tcp | 옛 일곱 실패 0, gc_unit_prep 174, gc_unit_p1과 p2와 p2b 0 검사: 통과 [측정] | `unit_p2b.log` |
| `ident` (IDTAG=p2b) | 설치 헤더 ln4와 같음; 매크로 없는 프로그램 16/16 SASS와 자원 같음; 네 빌드 디렉터리의 장치 객체 207개씩 SASS 같음(바이트도 207); 라이브러리 넷의 자원 사용 같음: 통과 [측정] | `ident_p2b.log`, `out/ident_p2b/` |
| `diff`, `info` | `gc_layer_p2b.diff` `fa3f1b48`, 639줄, int 커밋 b80ebda 대비, 거꾸로 적용 확인 [측정] | `diff_p2b.log`, `info_p2b.txt` |
| 헤더 요청 | 패치한 헤더가 rdma와 tcp에서 `-Werror -fsyntax-only` 통과 [측정] | `agent_gc_p2b/hdr/` |

## 파일 md5 (worktree `control/impl/`, 이 작업이 만든 것)

| 파일 | md5 | 줄 |
|---|---|---|
| `gc_layer_p2b.diff` | `fa3f1b48de823d9e5ff62efc0031221a` | 639 |
| `gc_unit_p2b.cc` | `2c3c2812c22ddeac2dd3d20d683f352a` | 828 |
| `rs_ctrl_api_p2b.diff` | `216ba84afde29b94f08d55c5a30db57f` | 30 |
| `notes_p2b.md` | (이 문서) | |
| 스크래치 `agent_gc_p2b/build_gc_p2b.sh` | `b820d481e3fcb927b38f9e1c57bd143c` | 821 |

바탕(고치지 않음): `rs_ctrl_api.h` `948b3ecf`, `gc_layer_int.diff` `a7600a46`, worktree `build_gc.sh` `5eaaf11e`(이 작업 동안 고침 에이전트가 바꾼 판), `gc_sites.tsv` HEAD `6cd637e5`, `gc_unit_prep.cc` `f2264508`, HEAD의 `gc_unit_p1.cc` `3350519e`, `gc_unit_p2.cc` `b1ea84fd`, `gate_fenced.cc` `a0817ab0`. `EXPERIMENT.md`, `launcher/*`, `test/*`, `../../mirror/*`, `rs_ctrl_api.h`, `gc_layer*.diff`(이 작업의 새 파일 빼고), `build_gc.sh`는 이 작업이 고치지 않았다.

## EXPERIMENT.md 11절과 12절에 넣을 줄 (안)

- 11절: `- [ ] 2단계 2b(결정 7, 덩어리의 저장소 칸, gdakiStoreWardToErr, STATE와 rkey 목록의 outbox 차례, 메모리 보고 줄): 빌드와 CPU 시험까지 — 2026-10-17, impl/gc_layer_p2b.diff fa3f1b48(int 커밋 위). 링 만들기(2a-2) 전에는 STATE와 rkey가 자료 소켓으로 감; 시험 스위치 셋, MTU와 fork 검사, BYE 차례, launcher QP는 남음`
- 12절: `| 2026-10-17 | 2단계 2b 구현(실행 없음, CPU와 빌드만). int 커밋(gc_layer_int.diff a7600a46) 위의 impl/gc_layer_p2b.diff(fa3f1b48, 639줄, 호스트 파일만, 더하기 512줄, 장치 코드 0줄): rdma 빌드의 gdakiStoreOn을 복원 켬 전체로(mirror 끈 체크포인트도 저장소 WRITE, 예비 프로세스는 활성화 v2와 FETCH QP의 READ, 덩어리는 저장소 칸만), gdakiStoreWardToErr(죽은 rank가 주인인 ward의 올리기 QP를 저장소 스레드가 ERR로), STATE와 rkey 목록의 outbox 세 전송(예비 프로세스가 차례를 시작; 바이트는 ln4 자료 소켓과 같음; 링 전에는 자료 소켓, TODO(2a-2)), 메모리 보고 줄(rank 4, I = 20 MiB에서 3I + 7.45 MiB, 한도 없음). gc, gcp, gct, gctp 빌드됨(경고 0). tcp 전처리는 정규화 뒤 ln4와 hunk 0(gct, gctp), gctc는 RST 간격 2 hunk만 [측정]. 단위 시험 두 빌드 통과, gc_unit_p2b 11 114 검사 실패 0(rdma) [측정]. 장치 동일성: 프로그램 16 조합과 장치 객체 207개 × 4가 ln4와 같음 [측정]. 헤더 요청은 impl/rs_ctrl_api_p2b.diff(전송 머리). 클러스터 실행 없음, verbs 장치에서 실행 안 함 | impl/notes_p2b.md, 스크래치 agent_gc_p2b/logs_p2b/ |`
