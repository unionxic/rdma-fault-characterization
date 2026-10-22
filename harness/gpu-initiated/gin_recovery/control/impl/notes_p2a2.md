# gin-control 2단계 2a-2: 링을 준비 때 만들고 seam으로 살아 있는 길에 묶기 (작업 기록)

## 단계 목록 (처음에 적은 계획, 20줄)

1. 트리 `agent_gc_p2a2/`: int+fix12 커밋, 2b와 헤더 diff 적용(충돌 해결), 커밋; `build_gc_p2a2.sh`(키 `p2a2`); 기준선 `unit`
2. 헤더 [2] 하위 블록: all-gather 칸 구조(9.6), 엄격 비교와 MTU 순수 함수, Resume 41–44 번호, 시험 스위치 이름 → `rs_ctrl_api_p2a2.diff`
3. 준비: all-gather 앞 `gdakiCtrlRdmaCreate`(UD QP, 영역), `mine`에 칸; 뒤에 엄격 비교, `active_mtu`, fork, 문턱 합의(고칠 것 4)
4. 페이지를 짝 맺기 전에 세우고 링의 `rxConsumed`를 페이지 `rxConsumed[N]`에 묶음(첫 기록 전); 그 뒤 기록 QP 첫 짝 맺기(낮은 rank)
5. seam 본문: Send(대기열), Pump(−1 한 번, `QP:NEWGEN`), Recv/RecvOn, RejoinFail(UD), ChanUp, ChanGen, PollFd(음수), ChanInstall, RecordToErr, RingFree
6. helper poll 묶음: completion channel fd, 증인 펌프 따로(BYE/FIN은 증인 소켓에서만)
7. 발견 1–2: DONE 기다림, MSG_PEEK, pollfd 둘, `gdakiMiSetupEnd`의 받기, 예비 프로세스의 대입
8. 발견 4–5: 라운드 취소와 `QP:` 원인(죽음 아님), 되살린 상대의 증인은 unknown과 다시 걸기
9. 발견 7: STATE와 rkey의 outbox(`gdakiCtrlStateRingOf`), REJOIN 세대의 `gdakiCtrlRdmaUp` 합의
10. REJOIN을 UD로: 예비 프로세스의 보내기와 다시 보내기, 생존 쪽 멱등 표, REJOIN_ACK, FAIL/WAIT/REFUSE 답
11. 생존 READ QP 짝 맺기를 UD로(helper 첫 걸음), 55번 발판 지움, `gc_sites.tsv`
12. 판정 효력: 링이 서면 증인 FIN은 창만 열고 창 판정이 반응; `NCCL_GIN_CTRL_PAGE` 기본 켬(rdma)
13. 시험 스위치 `QP_ERR`, `DROP_UD`, `CREDIT_STALL`; 증인 소켓의 `DIE_RST`, `RST_GAP`, `FD_HOLDER`(rdma만)
14. 로그 줄(제어 요약, 링 요약, PAIR, re-paired, REJOIN 다시 보냄, 스위치 줄)
15. `gc_unit_p2a2.cc`: 가짜 verbs 위의 뒤끝과 seam, 2–4 rank 장면
16. 검사: 빌드 넷, `pre`, `sites`, `api`, `unit` 두 빌드, `ident`, `diff`; 이 문서 마무리

## 끝낸 단계 (한 단계 한 줄)

- 1 끝: `agent_gc_p2a2/`(nccl-src와 빌드 넷 복사, 경로 다시 씀), 커밋 79d7e25 "gin-control int+fix12 (gc_layer_int.diff 60ca3cd9)"(ln4 커밋 대비 diff md5 60ca3cd9 확인), 2b diff는 offset만으로 15/15 적용, 헤더 diff 적용 뒤 호스트의 같은 전송 머리 정의를 지우고 다시 붙임, 커밋 2efebe3 "gin-control + 2b (gc_layer_p2b.diff fa3f1b48)"; `syn` 세 빌드 통과, 기준선 `unit` 두 빌드 통과 `[측정: logs_p2a2/syn_s0.log, unit_s0.log]`
- 2 끝: 헤더 [2] 하위 블록에 all-gather 칸 구조 `gdakiCtrlSetupAddr`(168 B), 합의 함수 `gdakiCtrlSetupAgree`(경로 44, MTU 42, 문턱), Resume 41–44 문장, REJOIN 답 코드 셋, 시험 스위치 이름 여섯, `NCCL_GIN_CTRL_PAGE` 이름과 기본 1(페이지 영역의 같은 정의는 지우고 기본값을 헤더 것으로); 다시 붙인 뒤 `api`, `syn` 통과 `[측정: logs_p2a2/api_s2.log, syn_s2.log]`

## 2a-2-A: 준비 때 링 만들기와 첫 짝 맺기 (seam 본문은 그대로)

### 단계 목록 (12줄)

1. 트리에 헤더 초안 커밋("gin-control 2a-2 header draft"), 스크립트의 head 이름과 diff 바탕(2efebe3)
2. 뒤끝 영역에서 dlopen 층(`gdakiCtrlVerbsOf`)을 따로 된 하위 영역으로 빼고, 준비용 순수 영역 "gin-control (ring): setup, pure"를 둠
3. 준비 all-gather 앞: `gdakiCtrlRdmaCreate`, `mine`의 `gdakiCtrlSetupAddr`(rdma 빌드의 `gdakiTsAddr` 칸), `active_mtu` 줄
4. all-gather 뒤: `gdakiCtrlSetupAgree`, 42와 44(문턱 어긋남 포함)는 투명 복원을 끔(줄 하나), 예비 프로세스의 엄격 비교
5. `gdakiRsLocalCheck` 입력에 41–44(40 뒤, rdma만), Resume의 사실 모으기
6. 첫 짝 맺기: helper 걸음에서 페이지의 `rxConsumed[]`를 링에 묶은 뒤 낮은 rank가 기록 QP와 생존 READ QP의 PAIR 시작
7. `ring.live = 0`, `gdakiCtrlChanUp`은 `gdakiCtrlRdmaUp`을 보되 tcp 같은 답, `gdakiCtrlRingFree` ← `gdakiCtrlRdmaDestroy`
8. 55번: 보내기 지움, 받으면 줄 하나로 버림; `gc_sites.tsv`의 `#use`
9. `gc_unit_p2a2.cc`: 가짜 verbs 위의 준비 합의, 2와 4 rank 첫 짝 맺기, credit 낱말, 55 버림; `p2a2regions`
10. 검사: `syn`, `api`, 빌드 넷, `pre`, `sites`, `unit` 두 빌드, `ident`, `diff`
11. 산출물을 작업 공간 `control/impl/`로(`gc_layer_p2a2.diff`, `rs_ctrl_api_p2a2.diff`, 시험, 표)
12. 이 절 마무리: 수, 검사 표, 2a-2-B와 2a-2-C에 남은 것, 스크립트 diff

### 끝낸 단계 (한 단계 한 줄)

- 1 끝: 커밋 968b4ba "gin-control 2a-2 header draft"(2efebe3 위, 호스트 파일만 95줄), 스크립트 `P2A2_BASE`와 diff 바탕; `syn` 세 빌드 통과 `[측정: logs_p2a2/syn_a0.log]`
- 2 끝: 뒤끝 영역 안 하위 영역 "libibverbs lookups"(dlsym에 `ibv_is_fork_initialized` 더함), 순수 영역 "gin-control (ring): setup, pure"(`gdakiCtrlSetupMine`, `gdakiCtrlSetupVerdict`, `gdakiCtrlSpareCtlMatch`, `gdakiCtrlResumeConds`, `gdakiCtrlBindWords`), 링의 `qkey`, `setup`, `bound`, `pairingStarted`, `live`; 헤더 [2]에 `GDAKI_CTRL_R44T`; `syn` 세 빌드 통과 `[측정: logs_p2a2/syn_a2.log]`
- 3 끝: `gdakiTsAddr`(rdma)에 `ctl`(168 B, 기록 56 → 224 B, static_assert; 예비 프로세스의 transcript 칸이 그만큼 커짐), all-gather 앞 `gdakiCtrlRingSetup`(링 만들기, `gdakiCtrlSetupMine`, rank마다 `control setup path=… active_mtu=…` 줄; Q_Key는 이 rank의 salt에서); `syn` 세 빌드 통과 `[측정: logs_p2a2/syn_a3.log]`
- 4 끝: all-gather와 nonce 뒤 `gdakiCtrlRingAgree`(투명 복원이 켜진 rank의 칸만 합의, 예비 프로세스는 transcript 칸과 경로와 launcher 노드 엄격 비교, 링 모형에 nonce, 상대 UD 끝점); 42와 44(문턱 어긋남은 44, 글 `R44T`)는 `why`가 되어 모든 rank에서 투명 복원을 끔, WARN 한 줄(맞으면 `setup agreement` 알림 한 줄); `syn` 세 빌드 통과 `[측정: logs_p2a2/syn_a4.log]`
- 5 끝: `gdakiRsLocalIn`에 `gc41`–`gc44`(글 또는 null), `gdakiRsLocalCheck`의 40 뒤에 41–44(rdma만), Resume의 `gdakiCtrlResumeFacts`(링의 준비 결과, launcher 짝 걸쇠; 41은 3단계가 launcher를 이름 지을 때만); `syn` 통과 `[측정: logs_p2a2/syn_a5.log]`, 옛 시험 두 빌드 통과(gin-mirror, gin-restore, prep, p1, gate_fenced, p2, p2b) `[측정: logs_p2a2/unit_a5.log]`
- 6 끝: `gdakiCtrlRingHelperStep`(페이지 helper 걸음 끝에서): 페이지가 서면 `gdakiCtrlBindWords`로 링의 소비 낱말을 페이지 `rxConsumed[N]`로 옮긴 뒤(배치가 다르면 짝 맺기 없음, 44), gated 쌍마다 계보의 화신을 두 종류에 넣고 낮은 rank가 `gdakiCtrlRdmaPairStart`(기록 QP, 생존 READ QP는 `hasQp`일 때; `CONNECT_MS`), 그 뒤 `gdakiCtrlRdmaPoll`; 예비 프로세스는 시작하지 않음; 알림 한 줄; `syn` 통과 `[측정: logs_p2a2/syn_a6.log]`
- 7 끝: 링의 `live`(늘 false, 2a-2-B가 켬), `gdakiCtrlChanUp`(r, peer, pe)은 `gdakiCtrlRdmaLiveUp`을 먼저 보고 live가 아니면 지금의 소켓 답, `gdakiCtrlRingFree` ← `gdakiCtrlRdmaDestroy`; `syn` 통과 `[측정: logs_p2a2/syn_a6.log]`
- 8 끝: 55번 발판(`gdakiCtrlProbePairing`, `ScaffoldSend`, `ScaffoldCtx`, `PairingStep`, 페이지의 `pairing`) 지움, 들어온 55는 보낸 rank마다 INFO 한 줄로 버림; `gc_sites.tsv`의 `#use` 두 행(ChanUp 1, HoldSend 1) 지움(169 → 170행, 주석 3줄); `sites` 통과 `[측정: logs_p2a2/sites_a6.log(지우기 전 MISMATCH 2), sites_a8.log]`
- 9 끝: `pin/gc_unit_p2a2.cc`(가짜 NIC: RC는 받는 쪽 RTR까지 다시 보냄, RNR, rkey와 범위를 보는 READ, Q_Key를 보는 UD; 감시 스레드의 답, 첫 화신의 계보), 스크립트 `p2a2regions`(준비 순수 영역, 고리, libibverbs 하위 영역을 뺀 뒤끝, 호스트 상태 조각); 처음 돌림에서 내 기대 둘이 틀림(CONNECTED가 seq 1로 credit 하나를 씀: 창은 소비 1 + 64, 소비 수는 기록 + 1), 고친 뒤 rdma 1 439 검사 실패 0, tcp 0 검사 `[측정: logs_p2a2/unit_t3.log(틀린 기대 6), unitp2a2_t5.log]`
- 10 멈춤(BLOCKED): 디스크가 찼다(`/` 457G 중 남은 것 1.3G → 44M; 같은 세션의 다른 에이전트 p3, fix3의 `ident`가 쓰는 중). 남의 트리는 지우지 않았다. `api`, `syn`, `sites`는 통과, 빌드 넷 가운데 `gct`만 빌드됨(`gc`, `gcp`, `gctp`는 링크 단계에서 "No space left"), `unit`은 두 번 다 디스크 때문에 중간에 멈춤(멈추기 전 시험은 모두 실패 0) `[측정: logs_p2a2/api_a10.log, syn_a10.log, sites_a8.log, build_*_a10.log, unit_a10.log, unit_a11.log]`
- 11 일부: `gc_layer_p2a2.diff`(2efebe3 대비, 729줄, md5 eb19b92d), `rs_ctrl_api_p2a2.diff`(p2b 헤더 대비, 99줄, md5 acbf33c6; 초안 + `GDAKI_CTRL_R44T` 한 줄)는 작업 공간에 씀. `gc_unit_p2a2.cc`, `gc_sites.tsv`도 `pin/`에서 복사함

### 검사 표 (이 작업에서 실행한 것만)

| 검사 | 결과 | 근거 |
|---|---|---|
| `syn` (build, build-gcp, build-gct) | 통과 | `logs_p2a2/syn_a10.log` |
| `api` | 통과 | `logs_p2a2/api_a10.log` |
| `gc` / `gcp` / `gctp` | 실패(디스크 참) | `logs_p2a2/build_{gc,gcp,gctp}_a10.log` |
| `gct` | 빌드됨, 경고 수는 아직 안 셈 | `logs_p2a2/build_gct_a10.log` |
| `pre` | 안 돌림 | – |
| `sites` | 통과(`#use` 두 행 지운 뒤) | `logs_p2a2/sites_a8.log` |
| `unit` 두 빌드 | 끝나지 않음(디스크); `gc_unit_p2a2` 단독은 두 빌드 통과(rdma 1 439 검사 실패 0, tcp 0 검사) | `logs_p2a2/unit_a11.log`, `unitp2a2_t5.log` |
| `ident` | 안 돌림 | – |

### 2a-2-B와 2a-2-C에 남은 것 `[추론: 원래 2a-2 단계 목록의 나눔]`

- 2a-2-A의 남은 몫: 위 검사(빌드 셋, `pre`, `unit` 전부, `ident`), 산출물 둘 복사; AH를 준비 때 미리(nit 11), 새 영역 `MADV_DONTFORK`
- 2a-2-B: `live = 1`과 seam 본문(Send, Pump −1과 `QP:` 원인, Recv/RecvOn, PollFd, RecordToErr), helper poll 묶음(채널 fd, 증인 펌프), 발견 1–5, FIN의 뜻 바꿈, 다시 짝 맺기 방아쇠, `helperBusy`
- 2a-2-C: REJOIN을 UD로(예비 프로세스의 짝 맺기, `gdakiCtrlRdmaOnRejoinAccepted`, FAIL/WAIT/REFUSE), 발견 7(STATE와 rkey의 outbox), 시험 스위치 여섯, 로그 줄
- 41: 3단계가 launcher를 이름 지을 때만 묻는다. 맡김 글의 "launcher 노드 어긋남 → 41"은 설계 5.1과 헤더 R44를 따라 44로 했다(충돌 기록)

### 수

- 호스트 파일 diff 729줄(2efebe3 대비, 헤더 초안 블록 포함), 헤더 패치 99줄, `gc_unit_p2a2.cc` 새 파일, `gc_sites.tsv` 169 → 170행
- 스크립트 diff: `build_gc_p2a2.sh` ec99dd7e → 611727b1(+46 −2: head 이름 `P2A2_SUBJECT`를 초안 커밋으로, `P2A2_BASE`와 diff 바탕, `p2a2regions` 채움)

### 10 다시 (디스크가 돌아온 뒤, 2026-10-17)

- 빌드 고침 한 가지(내가 낸 링크 오류): rdma의 `gc`, `gcp`가 `wrap_ibv_create_comp_channel`, `wrap_ibv_destroy_comp_channel` 정의 없음으로 링크 실패. `ibvwrap.h`는 선언하지만 `misc/ibvwrap.cc`는 정의하지 않는다 `[소스]`. 2a-2-A가 `gdakiCtrlCqCreate`를 처음 닿게 만들어서 드러났다. `ibv_create_comp_channel`, `ibv_destroy_comp_channel`을 libibverbs lookups 하위 영역에서 dlsym으로 찾고(`gdakiCtrlChannelCreate`, `gdakiCtrlChannelDestroy`), `gdakiCtrlCqCreate`/`Destroy`의 세 줄을 그것으로 바꿈(rdma만; tcp 전처리는 그대로) `[측정: logs_p2a2/build_gc_a12.log]`
- `gc_layer_p2a2.diff` 다시 씀: 780줄, md5 1eb219f2(앞 판 eb19b92d) `[측정: logs_p2a2/diff_a13.log]`

| 검사 | 결과 | 근거 |
|---|---|---|
| `syn` | 통과 | `logs_p2a2/syn_a13.log` |
| `api` | 통과 | `logs_p2a2/api_a10.log` |
| `gc` | 빌드됨, 경고 0, libnccl f5fc6672 | `logs_p2a2/build_gc_a13.log` |
| `gcp` | 빌드됨, 경고 0, libnccl 4273f55b | `logs_p2a2/build_gcp_a13.log` |
| `gct` | 빌드됨, 경고 0, libnccl b4e6cabd (고침 전 트리; 고침은 rdma만이고 tcp 전처리는 아래처럼 ln4와 같음) | `logs_p2a2/build_gct_a10.log` |
| `gctp` | 빌드됨, 경고 0, libnccl f424eccc (같음) | `logs_p2a2/build_gctp_a12.log` |
| `pre` | gct 0 hunk, gctp 0 hunk, gctc 2 hunk 3줄(RST 간격만) | `logs_p2a2/pre_a13.log`, `out/pre/gctc.norm.diff` |
| `sites` | 통과 | `logs_p2a2/sites_a13.log` |
| `unit` rdma | 통과(옛 시험 모두 실패 0, `gc_unit_p2a2` 1 437 검사 실패 0; 검사 수는 기다림 고리 때문에 실행마다 1–3 다름) | `logs_p2a2/unit_a13.log` |
| `unit` tcp | 통과(`gc_unit_p2a2` 0 검사) | `logs_p2a2/unit_a13.log` |
| `ident` | 프로그램 16/16 같음, 장치 객체 207 × 4 같음, 라이브러리 자원 넷 같음 | `logs_p2a2/ident_a13.log` |

실제 verbs나 장치에서는 한 번도 돌지 않았다 `[미확인]`. 41/44 해석(launcher 노드 어긋남 → 44, 설계 5.1)은 조율 세션이 받아들임.

## 2a-2-B: seam 본문, helper 루프의 증인 몫 읽기, `live`, 로그 줄, 시험 스위치

### 단계 목록 (12줄)

1. 트리: 작업 트리를 "gin-control 2a-2-A (gc_layer_p2a2.diff 1eb219f2)"로 커밋, 스크립트 head 이름; `unit`이 `gc_unit_prep`에 링 hook의 "링 없음" 답을 줌
2. seam 본문(`ring.live`일 때만): Send(대기열), Pump(−1 세대 바뀜마다 한 번, `QP:NEWGEN`), Recv/RecvOn(같은 시한 뜻), ChanUp, ChanGen, PollFd(음수), ChanInstall, RecordToErr(ERR + 다시 짝 맺기 요청)
3. 새 영역 "gin-control (ring): live seams": hook 넷, 증인 펌프, 셈(TCP 바이트, 대기열, 지연 보냄), `QP:` 원인 판별
4. 부르는 자리 다섯: DONE 기다림, MSG_PEEK, pollfd 둘(채널 fd와 깨우기), `gdakiMiSetupEnd`의 받기, 대입; `gc_sites.tsv`, `sites`
5. helper poll 묶음: 링이 live면 증인 소켓 + 채널 fd, 증인 펌프(BYE/FIN), 링 펌프; CancelRound/MakeUnknown/SocketLost의 `QP:` 갈래, CauseLiveness `QP:*` → unknown
6. `live = 1`(모든 gated 상대의 두 짝 맺기가 CONNECTED), 로컬 ERR 뒤 다시 짝 맺기 방아쇠와 PAIR 줄, re-paired 줄
7. 시험 스위치 `QP_ERR`, `CREDIT_STALL`, `DROP_UD`(rdma 연구 빌드만)
8. 끝낼 때 제어 요약 줄과 링 요약 줄(시험 쪽 표의 글 그대로)
9. `gc_unit_p2a2.cc`: 2와 4 rank, seam으로 양방향 기록, TCP 길과 바이트 같음, 라운드 중 세대 바뀜(−1 한 번, 취소), 상대가 시작한 다시 짝 맺기, 증인 BYE/FIN, 스위치 셋
10. 검사: `syn`, `api`, 빌드 넷(경고 0), `pre`, `sites`, `unit` 두 빌드, `ident`
11. 산출물을 작업 공간으로(`gc_layer_p2a2.diff` 2efebe3 대비 A + B, 시험, 표)
12. 이 절 마무리: 검사 표, md5, 2a-2-C에 남은 것

### 끝낸 단계 (한 단계 한 줄)

- 1 끝: 커밋 61454d9 "gin-control 2a-2-A (gc_layer_p2a2.diff 1eb219f2)"(968b4ba 위), 스크립트 `P2A2_SUBJECT`를 그 커밋으로; `unit`은 `gc_unit_prep`의 seam 넷 앞에 링 hook 넷의 "링 없음" 답(false, 셈 없음)을 붙임(그 시험은 r = nullptr로 부름); `p2a2regions`가 live 영역, seam 본문, TCP 셈 구조, CauseLiveness/MakeUnknown을 자름 `[측정: logs_p2a2/syn_b1.log, unit_b1.log]`
- 2 끝: "[2] ring" 자리 표시의 seam 본문: Send/Pump/Recv/RecvOn은 hook을 먼저 묻고 아니면 TCP(바이트를 셈, errno 보존), ChanUp은 live면 링, ChanGen은 그대로(링 세대), PollFd는 live면 -1, ChanInstall은 소켓 대입만(링 몫 없음), RecordToErr는 QP를 ERR로(다시 짝 맺기는 helper 걸음), RingFree는 A 그대로; `syn` 세 빌드 통과 `[측정: logs_p2a2/syn_b1.log]`
- 3 끝: 새 영역 "gin-control (ring): live seams"(hook 넷, `QP:` 판별, 증인 펌프, live 걸음, 요약 줄)와 "the helper's live loop"; 뒤끝에 CREDIT_STALL의 RECV 완료 붙잡기(`gdakiCtrlRdmaOnRecvWc`로 뺌)와 DROP_UD(UD 보내기), 스위치 읽기; `gdakiRecHost`에 TCP 셈(rdma만); 옛 `gc_unit_p2a2` 통과(1 429 검사), `unit` 두 빌드 통과 `[측정: logs_p2a2/unitp2a2_b1.log, unit_b1.log]`
- 4 끝: 다섯 자리는 준비 단계 고침에서 이미 seam을 부른다(DONE 기다림 `gdakiCtrlRecv`, peek와 pollfd 둘 `gdakiCtrlPollFd`, `gdakiMiSetupEnd` `gdakiCtrlRecv`, 대입 `gdakiCtrlChanInstall`); rdma 갈래로 더한 것은 `gdakiTsRecvServing`의 채널 fd와 깨우기(두 줄); 표의 행 여섯에 2a-2-B 뜻, `#use` ring `.fd` 2 → 7, `gdakiCtrlChanUp` 1, `gdakiCtrlPump` 1, `gdakiTsPump` 1; `sites` 통과(tcp 갈래 39개 ln4 글 그대로) `[측정: logs_p2a2/sites_b1.log(MISMATCH 4), sites_b2.log]`
- 5 끝: helper poll 묶음의 rdma 갈래(`gdakiCtrlHelperLiveStep`: 링이 live면 증인 소켓 + 채널 fd 한 poll, 증인 펌프, 상대마다 링 펌프와 idle 처리; 아니면 ln4 묶음 그대로); `gdakiTsCauseLiveness`는 `QP:*`를 unknown, `gdakiTsMakeUnknown`은 `QP:` 원인이면 증인을 건드리지 않음, `gdakiTsCancelRound`는 그때 "record connection ... lost in a round" 줄, `gdakiTsSocketLost`는 `QP:` 원인이면 줄 하나와 unknown만(창 없음, 죽음 없음); `syn` 통과 `[측정: logs_p2a2/syn_b1.log 뒤 판은 아래 10]`
- 6 끝: `gdakiCtrlRingLiveStep`(링 helper 걸음 끝 한 줄): 모든 gated 상대의 기록 QP와 생존 READ QP가 UP이면 `live = 1`(줄 하나, 예비 프로세스는 2a-2-C까지 아님), 로컬 잃음(`ring.lost`, 계보 LIVE, 거절/떠남/죽음 아님)에 `gdakiCtrlRdmaPairOnErr`와 "PAIR(record, gen %u) to rank %d (local ERR)", 세대 > 1로 다시 서면 "record QP|liveness READ QP to rank %d re-paired (gen %u)"
- 7 끝: 스위치 `QP_ERR=<ms>:<peer>`, `CREDIT_STALL=<start>:<len>`(그동안 RECV 완료를 붙잡아 다시 내지 않음: credit 안 돌아감), `DROP_UD=rejoin:<n>`(UD 보내기에서 REJOIN 기록만), 기점은 첫 무장(복원 없으면 live), `#ifndef NCCL_GIN_TS_PRODUCTION`, 줄은 시험 쪽 표 글 그대로
- 8 끝: helper 끝에서 `gdakiCtrlRingSummary`: "control summary tcp_record_bytes=… active_mtu=%u" 뒤에 `tcp_rx_bytes_peer<p>=`, `async_rec=`, `async_read=`, `async_la=0`, `tcp_late_records=`, `live=`, `mono_ms=`; 상대마다 "ring summary peer=%d gen=%u sent=%llu received=%llu lost=%u dup=%u"
- 9 끝: `gc_unit_p2a2.cc` 장면 5(2와 4 rank), 6(스위치 넷); 처음 돌림 3 실패(내 기대 둘: q의 -1 원인은 펌프와 다시 짝 맺기 중 먼저 온 쪽에 따라 TOERR나 NEWGEN, 2 rank의 보낸 수에 증인 장면 기록 하나) → 기대 고침, rdma 3 983 검사 실패 0, 다섯 번 더 실패 0 `[측정: logs_p2a2/unitp2a2_b2.log, unitp2a2_b4.log]`
- 10 끝: 첫 빌드에서 `gc` 경고 1(`-O3` 인라인 뒤 2a-1의 `gdakiCtrlRdmaRecv`가 내 24 B 버퍼에 "QP:%s"를 씀: format-truncation) → 받는 버퍼 48 B, `closeCause`에는 잘라 복사; 다시 돌린 검사 모두 통과(아래 표) `[측정: logs_p2a2/build_gc_b10.log(경고 1), chain_b12.log]`
- 11 끝: `gc_layer_p2a2.diff`(2efebe3 대비 A + B, 1 444줄, md5 414a8790), `gc_unit_p2a2.cc`, `gc_sites.tsv`를 작업 공간에; 헤더는 바꾸지 않아 `rs_ctrl_api_p2a2.diff`는 그대로(acbf33c6) `[측정: logs_p2a2/diff_b12.log]`
- 12 끝: 이 절

### 검사 표 (2a-2-B, 이 작업에서 실행한 것만)

| 검사 | 결과 | 근거 |
|---|---|---|
| `syn` (build, build-gcp, build-gct) | 통과 | `logs_p2a2/syn_b12.log` |
| `api` | 통과(헤더 블록 바뀜 없음) | `logs_p2a2/api_b12.log` |
| `gc` / `gcp` / `gct` / `gctp` | 빌드됨, 경고 0; libnccl d7222a24 / c9f5f101 / 851d6c7b / c9fe0ba5 | `logs_p2a2/build_{gc,gcp,gct,gctp}_b12.log`, `out/*_p2a2b/` |
| `pre` | gct 0 hunk, gctp 0 hunk, gctc 2 hunk 3줄(RST 간격만) | `logs_p2a2/pre_b12.log` |
| `sites` | 통과(149행, `#use` 넷 맞음, tcp 갈래 39개 ln4 글 그대로) | `logs_p2a2/sites_b12.log` |
| `unit` rdma | 통과(옛 시험 모두 실패 0, `gc_unit_prep` 116 장면 366 검사, `gc_unit_p2a2` 3 976 검사; 검사 수는 기다림 고리 때문에 실행마다 몇 개 다름) | `logs_p2a2/unit_b12.log` |
| `unit` tcp | 통과(`gc_unit_prep` 48 장면 174 검사, `gc_unit_p2a2` 0 검사) | `logs_p2a2/unit_b12.log` |
| `ident` | 프로그램 16/16 같음, 장치 객체 207 × 4 같음(바이트도), 라이브러리 자원 넷 같음 | `logs_p2a2/ident_b12.log` |

실제 verbs, GPU, 클러스터에서는 돌지 않았다 `[미확인]`. 시험은 가짜 NIC 위의 in-process rank다(n 1 실행 + `gc_unit_p2a2` 단독 5번).

### 정한 것과 발견 `[추론]`

- 셈의 뜻: `records_lost` = 세대 바뀜에 버린 대기열 + 옛 세대의 받지 못한 성공 RECV, `records_dup` = 새 세대 RECV에 온 옛 세대 봉투(버림), `tcp_conns`는 live가 아니면 열린 helper 소켓 수(기록도 실음), live면 0; `witness_conns`는 열린 helper 소켓 수. 제어 요약은 끝낼 때만 낸다(확정 체크포인트마다 내는 몫은 남음).
- live 전환은 rank마다 따로다: 상대가 먼저 live가 되어 링으로 보낸 기록은 이쪽 inbox에서 이쪽이 live가 될 때까지 기다리고, 이쪽이 아직 TCP로 보낸 기록은 상대의 증인 펌프가 기록으로 넘긴다(`tcp_late_records`). 바뀌는 순간 TCP에 남은 기록과 링의 뒤 기록의 차례는 보장하지 않는다(쌍마다 전환 표지가 필요; 라운드는 helper 루프 사이에서만 돌아 창은 짧다). 2a-2-C나 리뷰가 정할 것.
- 로컬 잃음 뒤 -1의 원인은 펌프와 다시 짝 맺기 중 먼저 온 쪽에 따라 `QP:<원인>`이나 `QP:NEWGEN`이다(한 번인 것은 같음; 모형의 세대 끝 표시가 원인을 싣지 않음).
- `gdakiTsSocketLost`에도 `QP:` 갈래를 두었다(부르는 자리가 펌프 -1 뒤에 그것을 부르므로: 줄 하나, unknown, 창 없음, 증인 그대로).
- 작업 공간의 `launcher/*` 바뀜은 이 작업의 것이 아니다(다른 에이전트).

### 2a-2-C에 남은 것

- REJOIN을 UD로(`nrp`, 예비 프로세스의 짝 맺기, `gdakiCtrlRdmaOnRejoinAccepted`, FAIL/WAIT/REFUSE 답, `gdakiCtrlRejoinFail`의 UD 몸통, REJOIN 다시 보냄 줄; DROP_UD는 그 보내기를 이미 막음)
- STATE와 rkey를 2b의 outbox 전송으로(`gdakiCtrlStateRingOf`), DATA 채널
- 되살린 상대의 증인: unknown으로 두고 다시 걸기(`gdakiTsPeerLiveness`의 `pe.fd < 0` = DEAD)
- 판정 효력: 링이 live면 증인 FIN은 창만 열고 창 판정이 반응(지금은 ln4처럼 FIN = 죽음)
- Resume 41(3단계와 함께), 확정 체크포인트마다의 제어 요약, live 전환 표지

### 파일 md5 (2a-2-B 끝)

| 파일 | md5 |
|---|---|
| `gc_layer_p2a2.diff` (1 444줄, 2efebe3 대비) | `414a87908f98db1e143d28657d794914` |
| `gc_unit_p2a2.cc` (1 510줄) | `7a9cd690` |
| `gc_sites.tsv` (176줄, 149행) | `450fe8bd` |
| `rs_ctrl_api_p2a2.diff` (바뀜 없음) | `acbf33c6` |
| `agent_gc_p2a2/build_gc_p2a2.sh` | `e32322a9`(2a-2-A 판 대비: head 이름, `gc_unit_prep`의 hook 넷 "링 없음" 답, `p2a2regions`의 자르기 넷) |

## 2a-2-C: 쌍마다의 길 표지, UD REJOIN, STATE와 rkey의 outbox, 판정 효력, launcher 페이지 credit, Resume 41, 시험 스위치 셋

### 단계 목록 (12줄)

1. 트리 `agent_gc_p2a2/`: 작업 트리(int2 접착)를 "gin-control int2 (gc_layer_int.diff c0975edb)"로 커밋, 스크립트 키 `p2a2c`
2. 쌍마다 (길 ring|socket, 세대) 표지; seam이 실행 때 그 쌍의 길을 봄; 바뀔 때 옛 세대 기록을 비우거나 버리고 줄 하나
3. UD REJOIN과 REJOIN_ACK(`nrp`의 새 끝점), 답 FAIL/WAIT/REFUSE, REJOIN 다시 보냄 줄, `gdakiCtrlRdmaOnRejoinAccepted`
4. 되살린 상대의 증인 소켓: unknown으로 두고 다시 걸기(소켓이 없다고 죽음으로 치지 않음)
5. STATE와 rkey를 2b의 outbox 전송으로: `gdakiCtrlStateRingOf`가 live 링, 두 쪽이 REJOIN 세대로 "링 섬"을 정함
6. 판정 효력: launcher 페이지 끌어 읽기로 `pullOk`, 10–12행과 확인 창 판정이 반응, `NCCL_GIN_CTRL_PAGE` 기본 1(rdma), 전환 줄
7. launcher 페이지 credit READ: launcher를 향한 창이 닫히면 페이지의 소비 낱말을 READ(credit만 나르는 SEND 없음)
8. Resume 41: 복원을 청했고 own launcher가 아직 짝이 아니면 `NCCL_GIN_CTRL_LATER_MS`까지 기다린 뒤 답(측정 모드는 그대로)
9. 시험 스위치 `DIE_RST`, `RST_GAP`, `FD_HOLDER`(rdma 연구 빌드, `notes_test.md`의 줄 그대로)
10. `gc_unit_p2a2.cc` 장면(REJOIN과 nrp, 답 셋, outbox와 링 섬 합의, 판정 효력, 표지 차례, 스위치 셋), `gc_sites.tsv`
11. 검사: `syn`, `api`, 빌드 넷(경고 0), `pre`, `sites`, `unit` 두 빌드, `ident`; `gc_layer_int.diff` 다시 씀
12. 이 절 마무리: 정한 것, 수, 검사 표, 4단계와 후속(degraded mode, mirror 끈 멈춤 줄이기, daemon의 예비 관리)에 남은 것

### 끝낸 단계 (한 단계 한 줄)

- 1 끝: 커밋 45274b6 "gin-control int2 (gc_layer_int.diff c0975edb)"(ln4 커밋 대비 diff md5 c0975edb 확인), 스크립트 `build_gc_p2a2.sh` = worktree `build_gc.sh` fe2936d8 + 키 `p2a2c`(int2의 단계, 머리 이름만 다름, 출력 `*_p2a2c`); `syn` 세 빌드 통과 `[측정: logs_p2a2/syn_c0.log]`
- 2 끝: 쌍마다 길 표지(path ring|socket, gen, recordsSentBeforeSwitch). 표지는 링 RECORD 봉투의 예약 16 B에 싣고, 소켓 길은 봉투가 없어 전환 뒤 첫 기록으로 표지 기록 56(`GDAKI_TS_CTRL_PATH`)을 보냄(이름은 `rs_ctrl_api_p2a2c.diff`에 요청, `pathMark`). seam 일곱은 전역 `live` 대신 쌍의 길을 봄(보내기, ChanUp, ChanGen, PollFd는 이쪽 선택, 읽기 셋은 받는 쪽 차례 규칙). 받는 쪽은 옛 길의 센 기록을 다 받거나, 옛 길이 닫히거나, 1 000 ms가 지나야 새 길 기록을 넘기고, 그 뒤 옛 길 기록은 전환마다 줄 하나와 함께 버림. 세대가 길을 건너 거꾸로 보일 수 있어 대기 세대는 세대 순서로 둠. live 전환은 gated 쌍마다 길을 링으로 바꿈. 실행 중 소켓 전환은 후속. 단위 시험 8번 장면에서 ring→socket→ring 79기록이 중복과 뒤바뀜 없이 오고, 센 기록 1개를 1 001 ms 기다린 뒤 줄 하나, 늦은 사본은 버림 `[측정: logs_p2a2/unit_c4.log, unitp_c3.log]`. 기존 시험 셋을 새 뜻에 맞춤(첫 짝 맺기의 LiveUp 토글, 증인 늦은 기록은 버림, QP_ERR의 -1은 이쪽 길이 링일 때). 검사: syn, api, 빌드 넷 경고 0, pre(gct, gctp 0 hunk, gctc 2 hunk), sites, unit 두 빌드, ident(프로그램 16/16, 장치 객체 207 × 4 바이트 같음) 통과 `[측정: logs_p2a2/*_c3.log, sites_c4.log, unit_c4.log]`. 실제 verbs와 GPU에서는 안 돌림 `[미확인]`.
- 2 md5: `gc_layer_int.diff` 3219c376(11 331줄, ln4 대비; int2 커밋 대비 접착 dce4aadf 732줄), `gc_unit_p2a2.cc` 80e29c16(1 906줄), `gc_sites.tsv` b470d169(177줄, ring `#use` .fd 10, gdakiTsPump 2, gdakiTsSend 2), `rs_ctrl_api_p2a2c.diff` 4650226c, `agent_gc_p2a2/build_gc_p2a2.sh` 7d91f553(`gc_unit_prep`의 send hook 막대에 fd 인자, p2a2c만); libnccl gc 3d905124, gcp e02f8981, gct 78ee39c5, gctp 95433525.
- 3, 4 끝(UD REJOIN과 되살린 상대의 증인; 작업 차례로는 step 2): 커밋 acfede7 "gin-control 2a-2-C step 1 (gc_layer_int.diff 3219c376)" 위에서. 예비 프로세스의 REJOIN과 생존 rank의 REJOIN_ACK는 UD 문맥 QP로 가고 `nrp`(`gdakiCtrlNrpPut/Get`)에 기록 QP, 생존 READ QP, UD, 페이지, outbox, 두 세대((화신 << 20) + 1)를 싣는다. 두 짝 맺기는 모형 그대로 REJOIN을 PAIR로 삼음(생존 rank가 TAKE, `gdakiCtrlRdmaOnRejoinAccepted` 먼저; 예비 프로세스는 STARTED, REJOIN_ACK나 먼저 온 PAIR_ACK에 CONNECT, CONNECTED가 첫 SEND). 안 받는 답은 UD의 FAIL 기록(arg FAIL/WAIT/REFUSE, `gdakiCtrlRejoinFail`의 UD 몸통, WAIT는 hold 전 UD intake, REFUSE는 받아들임의 거절). 다시 보냄 줄 `REJOIN to rank %d resent (try %u)`(200 ms, 같은 끝점). 받아들임 뒤 쌍의 길을 새로 시작해 TOKEN/READY/DONE_RS가 링으로(TOKEN은 CONNECTED까지 대기열), 증인은 unknown과 다시 걸기, 증인 소켓 없음은 죽음 아님(`gdakiCtrlNoWitnessLv`). 예비 프로세스의 링은 REJOIN을 다 받은 뒤 live(`spareRejoined`). TCP REJOIN은 tcp 빌드와 링 없는 rdma에 그대로. 시험 9, 10번 장면(2와 4 rank, 답 셋, 잃은 REJOIN 한 번 다시 보냄, 반복과 다른 QPN, 링 위 TOKEN/READY/DONE_RS, 증인 상태). 검사: syn, api, 빌드 넷 경고 0, pre(gct, gctp 0 hunk, gctc 2 hunk), sites(149행, `#use` ring .fd 11, gdakiCtrlRejoinFail 1), unit 두 빌드(`gc_unit_p2a2` rdma 4 837 검사 실패 0), ident(프로그램 16/16, 장치 객체 207 × 4 바이트 같음) 통과 `[측정: logs_p2a2/*_e3.log]`. 실제 verbs와 GPU, 호스트의 `gdakiRsRejoinAccept`/`gdakiRsSpareRejoinAll` 자체는 안 돌림(시험은 그 부르는 차례를 따라 링 함수를 부름) `[미확인]`.
- 3, 4 md5: `gc_layer_int.diff` 3bf9aaf6(12 018줄, ln4 대비; step 1 커밋 대비 f2896bdb 838줄), `gc_unit_p2a2.cc` be7714c1(2 238줄), `gc_sites.tsv` 440d9437(178줄), `rs_ctrl_api_p2a2c.diff` 8beca7bf(step 3 주석 요청을 덧붙임), `agent_gc_p2a2/build_gc_p2a2.sh` 4fff6fea(머리 이름을 step 1 커밋으로, `gc_seam_bodies.inc`에 `gdakiCtrlRejoinFail`); libnccl gc 0b55ece2, gcp 976bec4d, gct dab57f26, gctp a12c1bcc.
- 5 끝(STATE와 rkey를 outbox로; 작업 차례로는 step 3): 커밋 03fc077 "gin-control 2a-2-C step 2 (gc_layer_int.diff 3bf9aaf6)" 위에서. STATE 차례의 길은 두 쪽 모두 REJOIN이 간 길이다(`gdakiCtrlStateWayRule`, `gdakiCtrlStateWayOf`, `gdakiCtrlStateRingOf`): UD였으면 링, 쌍의 기록 QP가 REJOIN 세대((inc << 20) + 1) 이상에서 서기 전에는 "아직"(1; 생존 rank는 예비 프로세스의 CONNECTED 전, 예비 프로세스는 설치 전), 결코 소켓으로 가지 않음; 자료 소켓은 쌍에 링이 없을 때만(문맥에 링 없음, REJOIN이 TCP; tcp 빌드는 링 자체 없음). 세 전송(STATE_REQ, STATE, RKEYS, 64 B 머리)은 막지 않는 걸음(`gdakiCtrlRdmaXOutStep`/`XInStep`이 2a-1의 막는 `XferSend`/`XferRecv`를 대신함, 링의 READ 칸은 한 번에 한 쌍 `inStageBy`, 새 세대는 전송을 실패시킴)과 쌍의 차례 기계(`gdakiCtrlStateSurvivorTurn`, `gdakiCtrlStateSpareTurn`, `gdakiCtrlRkeysSpareTurn`; live seams 영역)로 가고, 호스트 쪽은 export 콜백과 예비 프로세스의 시한 고리만 남김(양쪽 줄 하나씩). 시험 11, 12번 장면(규칙 표, 2와 4 rank: 한쪽 세대가 뒤질 때 두 쪽 다 "아직", STATE_REQ 기록, STATE 흐름, rkey 바이트가 TCP 길과 같음(gc_unit_p2b.cc의 AF_UNIX 대조), rkey 왕복, 0 B, 100 B, 3 반(3 MiB) export, 중간의 새 세대, 링 없음과 TCP REJOIN의 fallback). 헤더 요청은 주석만(`rs_ctrl_api_p2a2c.diff`에 덧붙임). 검사: syn, api, 빌드 넷 경고 0, pre(gct, gctp 0 hunk, gctc 2 hunk 3줄), sites(149행, 표 바뀜 없음), unit 두 빌드(`gc_unit_p2a2` rdma 5 262 검사 실패 0, `gc_unit_p2b` 11 114 실패 0), ident(프로그램 16/16, 장치 객체 207 × 4 바이트 같음, 자원 넷 같음) 통과 `[측정: logs_p2a2/*_f4.log, chain_c.log]`. 실제 verbs와 GPU, 호스트의 `gdakiHoldTransferStep`/`gdakiCkptSpareDataFd` 자체는 안 돌림(시험은 차례 기계를 부르는 차례대로 부름) `[미확인]`.
- 5 md5: `gc_layer_int.diff` c884c86c(12 288줄, ln4 대비; step 2 커밋 대비 b6bd7ed0 821줄), `gc_unit_p2a2.cc` e9fe6ade(2 578줄), `gc_sites.tsv` 440d9437(바뀜 없음), `rs_ctrl_api_p2a2c.diff` ebcb1090(117줄), `agent_gc_p2a2/build_gc_p2a2.sh` 23977026(머리 이름을 step 2 커밋으로); libnccl gc 409f1ac6, gcp f46727a0, gct 7bdb9027, gctp 5e73eedb.
- 6 끝(판정 효력; 작업 차례로는 step 4): 작업 트리가 smoke2 고침을 담고 있어(0f6c96f 대비 2e4cc6d0, ln4 대비 907116f3 확인) 커밋 334c124 "gin-control int3 + smoke2fix (gc_layer_int.diff 907116f3)" 위에서, 스크립트 `agent_gc_p2a2/build_gc_int3.sh`(키 `int3`). 쌍의 기록이 live 링에 있고 페이지와 생존 READ QP가 서면(`gdakiCtrlEffOn`) 증인 FIN은 창만 연다(소켓은 닫고 판정 전에는 다시 걸지 않음, 줄 `liveness=pending`; RST는 ln4대로 unknown이고 그 창도 반응). hold(무장 아니면 거절)는 t_F + W의 표 판정 3–6행(원인 EXITED, FIN+STALE, FIN+NORESP, REMACC+FIN이 `lostCause`, `gdakiHoldStrongCause`의 rdma 이름) 또는 그 화신의 launcher EXITED/FENCED(펜스 낱말, envelope 뒤 곧바로)에서만 시작하고 FIN 하나로는 시작하지 않음; 8행은 증인 다시 걸기, 9행과 W + `PROBE_TIMEOUT_MS` 안에 판정 없는 창은 증인 unknown(launcher 보고, 마지막은 ln4의 거절 둘). 라운드의 생존 확인(`gdakiTsPeerLiveness`)도 먼저 판정을 받음(`gdakiCtrlEffPoll`). launcher의 끝 말은 시각 재기 창도 염. tcp 빌드와 live 링 없는 쌍은 ln4 규칙 그대로(창은 보고만, 낡은 줄 글 고침). `pullOk`: launcher 박동 READ를 2 048 B(머리와 등록 칸 62)로 넓힌 끌어 읽기(`gdakiCtrlLaPageRegOf`, `gdakiCtrlLaPullOk`), L의 등록 낱말은 페이지의 것이고 (ALIVE, p, i)가 아니면 정보 없음이라 10–12행이 갈림. `NCCL_GIN_CTRL_PAGE`는 헤더에서 이미 기본 1(낡은 주석 둘 고침). live 전환 때 줄 하나 `the judgement table decides an exit from now`. 헤더 요청은 주석과 `gdakiCtrlLaPullInputs` 선언(`rs_ctrl_api_p2a2c.diff`에 d6b329a2 대비로 덧붙임). 시험 `gc_unit_p1.cc` 11, 12번: kill 장면 4 000(창 판정으로 끝 2 664, 모두 t_F + W 뒤 2.013 ms 안; launcher 보고로 끝 1 019, 그 가운데 t_F + W 전 464; 끝 없음 317은 살아 있는 창과 보고 없음; FIN만으로 끝난 장면 0), 격자 1 170점 행마다 수 그대로이고 끝내는 234점은 모두 launcher 끝이나 확인된 창, 끌어 읽기 R (11)에서 10행 3, 11행 3, 12행 9(pullOk 거짓이면 11, 12행 0). 검사: syn, api, 빌드 넷 경고 0, pre(gct, gctp 0 hunk, gctc 2 hunk 3줄), sites(149행 MISMATCH 0, 표 바뀜 없음), unit 두 빌드(`gc_unit_p1` rdma 10 285 083 검사 실패 0, 다른 시험 실패 0), ident(프로그램 16/16, 장치 객체 207 × 4 바이트 같음, 자원 넷 같음) 통과 `[측정: logs_p2a2/*_g1.log, unitp1_g1.log]`. 실제 verbs와 GPU, 호스트의 `gdakiTsSocketLost`/`gdakiCtrlEffPoll`/끌어 읽기 자체와 smoke2 재현은 안 돌림(시험은 순수 함수와 창 모형) `[미확인]`.
- 6 md5: `gc_layer_int.diff` c7403c07(13 280줄, ln4 대비; 334c124 대비 27bb39c0 646줄), `gc_unit_p1.cc` c56efe04(1 602줄), `gc_sites.tsv` 440d9437(바뀜 없음), `rs_ctrl_api_p2a2c.diff` 48b19084(148줄), `agent_gc_p2a2/build_gc_int3.sh` 91c70531(worktree `build_gc.sh` 6a79837d, int3 머리 이름만 334c124로); libnccl gc 05260efd, gcp c3ee83cc, gct bf550054, gctp 8633cfef.
- smoke3(2026-10-22, 채점 안 함, 시도 여섯, 셀마다 n 1): 4단계를 커밋 54c9d22 "gin-control 2a-2-C step 4 (gc_layer_int.diff c7403c07)"로 커밋하고 실제 RNIC에서 돌림. 장애 없음 통과; kill rank 3은 FIN이 창만 열고(창 6/6 `alive`, 8행) 판정은 launcher EXITED(3행) kill 뒤 101.9–106.0 ms, 복원 판정 → 게시 72.7–74.2 ms, 데이터 같음; SIGSTOP 12 000 ms는 고친 뒤 STALL_HELPER(15행) 멈춤 뒤 10 094–10 096 ms → hold → FENCE → FENCED(SIGKILL 뒤 118.7 ms) → 복원 195.3 ms, 데이터 같음; 증인 끈 kill은 EXITED 103.4–103.5 ms(FIN 판정 아님) `[측정: ../results/20261022_smoke3/SMOKE.md]`.
- smoke3 고침과 요청: 멈춤 판정이 1단계 거절 그대로이고 `NCCL_GIN_RESTORE_FENCE`를 읽지 않던 것을 고침(`gdakiCtrlStallFenceOn`, `gdakiHoldStrongCause`에 STALL, STALL_HELPER; `gc_layer_smoke3fix.diff` 62d48a11, 49줄, libnccl gc 0b8fa6d7, `unitp1` 실패 0, 다른 검사는 안 돌림 `[미확인]`); 요청: 창이 GPU 진행 줄을 읽어 SIGKILL 뒤 약 100 ms 동안 `alive`로 봄 `[추론]`, `WITNESS=0`이 관리망 소켓을 닫지 않아 그 FIN이 창을 엶.
- smoke3 요청과 5단계(작업 차례로는 step 5, launcher 페이지 credit): 작업 트리의 smoke3 고침(`gc_layer_smoke3fix.diff`와 바이트 같음)을 커밋 68bc1a6 "gin-control step 4 + smoke3fix"로 커밋하고 그 위에서, 스크립트 `agent_gc_p2a2/s4.sh`(`INT3_HEAD`를 그 이름으로, 출력 `*_s4`). (1) 확인 창의 READ1, READ2는 언제나 줄 0의 `watchBeat`(호스트 박동)를 읽음: 창의 장치 줄 모드(`dev`, `quiet2`)와 창용 장치 줄 칸 둘을 없앰, 장치 줄은 멈춤 행(14, 15)의 입력으로만 남음. `gc_unit_live` 5번을 박동 창으로 바꿈: kill 장면 2 000(장치 줄이 FIN 뒤 100 ms 동안 오르고 READ1과 READ2 사이에 2 000/2 000 바뀜)이 모두 FIN+STALE(4행), t_F + W + 0.009–1.836 ms; 살아 있는 장면 2 000이 모두 alive(8행); 격자 1 170점 행마다 수 그대로. (2) `WITNESS=0`: 실효 쌍에서 증인 소켓의 끝(FIN, RST, 오류, 거절)은 창을 열지 않고 판정에 들지 않음(`gdakiCtrlWitnessMuted`, `gdakiCtrlWitnessOffLost`: RST로 닫고 다시 걸지 않음, 줄 `liveness=ignored`, 증거 없음; `gdakiCtrlNoWitnessLv`도 증거 없음). READ 실패 길이 실제로 판정하도록 주기 판정의 10, 11행을 우편함으로 helper에 넘겨 끝냄(`gdakiCtrlEffOnReadRow`, 화신마다 한 번; 11행 NORESP는 hold, 10행 LINKDOWN은 거절), `gdakiHoldStrongCause`에 NORESP(9.3절 강한 증거 일곱의 마지막). `gc_unit_p1` 13번: kill 장면 3 000에서 launcher 보고(3행) 1 811, 11행 901(kill 뒤 3 619–4 028 ms), 10행 288(3 642–4 029 ms), FIN에서 끝난 장면 0, 4–9행 0. (3) launcher 페이지 credit READ: launcher를 향한 창이 닫히고 대기열이 있으면 PAIR/PAIR_ACK의 `creditOff`(검사 `gdakiCtrlLaCreditOffOk`)의 소비 낱말을 READ(slot 1, 한 번에 하나, 1 ms마다 많아야, `gdakiCtrlLaLearnAck`: 이 세대, 보낸 수 이하, 뒤로 가지 않음), credit만 나르는 SEND 없음. `gc_unit_p2a2` 7번에 장면(뒤진 값, 다른 세대, 80: 대기 12개가 순서대로, READ 3), `gc_unit_p3`에 PAIR_ACK의 `creditOff` 보관 검사. (4) 시험 스위치 `DIE_RST`, `RST_GAP`, `FD_HOLDER`는 하지 않음(이 작업에서 구현하지 않았고 트리에 없음). 헤더 요청은 주석 하나(`rs_ctrl_api_p2a2c.diff`에 덧붙임). 검사: syn, api, 빌드 넷 경고 0, pre(gct, gctp 0 hunk, gctc 2 hunk 3줄), sites(149행, 표 바뀜 없음), unit 두 빌드(번들 아홉 실패 0; `gc_unit_p1` rdma 10 376 867, `gc_unit_live` 293 382, `gc_unit_p2a2` 5 478, `gc_unit_p3` 475 검사), ident(프로그램 16/16, 장치 객체 207 × 4 바이트 같음, 자원 넷 같음) 통과 `[측정: logs_p2a2/*_s5.log, unit_s6.log]`. 실제 verbs와 GPU, 호스트의 창 읽기, 증인 끔 길, 10, 11행 반응, credit READ 자체는 안 돌림 `[미확인]`.
- smoke3 요청과 5단계 md5: `gc_layer_int.diff` 571e604e(13 416줄, ln4 대비; 68bc1a6 대비 d36733f9 458줄), `gc_unit_p1.cc` b02a9503(1 741줄), `gc_unit_live.cc` 085b18a8(615줄), `gc_unit_p2a2.cc` fa8654a1(2 658줄), `gc_unit_p3.cc` 9ac5d787, `gc_sites.tsv` 440d9437(바뀜 없음), `rs_ctrl_api_p2a2c.diff` c3653c8a(158줄); libnccl gc 0a821c7e, gcp a6fc9689, gct 54e118c8, gctp 32572a3d.
- 시험 스위치 셋(9번; 작업 차례로는 step 6): 작업 트리를 커밋 799bd4f "gin-control window/witness/credit (gc_layer_int.diff 571e604e)"로 커밋하고 그 위에서, `agent_gc_p2a2/chain_s6.sh`(`s4.sh`의 `INT3_HEAD`를 그 이름으로, 출력 `*_s6`). rdma 연구 빌드만(`#ifndef NCCL_GIN_TS_PRODUCTION`, live seams 영역), 시작 기준은 `QP_ERR`과 같은 원점(live 뒤 첫 무장): `DIE_RST=<ms>`는 열린 증인 소켓마다 `SO_LINGER {1, 0}`, 줄 `test switch DIE_RST: linger 0 on %d socket(s); SIGKILL now after_ckpt_ms=%d`, 소켓을 닫고(RST) `gdakiCtrlTestDieNow`(SIGKILL); `RST_GAP=<시작>:<길이>`는 줄만 냄(`0 socket(s) reset, listener closed for 0 ms (the line only in this build; asked S:L)`): 소켓 리셋과 수신 대기 닫기는 아직 없어 `gc4_rstgap_live300`은 주입 없이 `inject_ok` 1이 됨, 그 셀은 돌리지 않음; `FD_HOLDER=sock|uverbs`는 원점에서 fork, 자식 `gin_fdhold`(비동기 시그널 안전 호출만, CUDA와 verbs 없음)는 0–2를 `/dev/null`로, 나머지 fd를 닫고 socketpair의 SCM_RIGHTS로 증인 소켓(증인을 끄면 0개)과 uverbs면 net_ib 문맥의 `cmd_fd`, `async_fd`를 받아 60 s 쥠; 줄 `child gin_fdhold pid=%d holds %d fd(s)`. `gc_unit_p2a2` 6번에 장면 다섯(DIE_RST: loopback TCP 쌍에서 상대가 ECONNRESET, die hook 한 번; RST_GAP 줄만; FD_HOLDER sock, uverbs, 증인 끔: `run_gc.sh`와 `rows_gc.py`의 정규식으로 pid를 읽고, comm, fd 수 3 + 1, 3 + 3, 3 + 0, kill 전에는 상대 쪽 끝이 안 보임), 잘못된 값 셋. 검사: syn, api, 빌드 넷 경고 0, pre(gct, gctp 0 hunk, gctc 2 hunk 3줄), sites(149행, ring `.fd` 11 → 16), unit 두 빌드(실패 0; `gc_unit_p2a2` rdma 5 593 검사), ident(프로그램 16/16, 장치 객체 207 × 4 바이트 같음, 자원 넷 같음) 통과 `[측정: logs_p2a2/*_s6.log, unit_s6b.log]`. 실제 RNIC에서 스위치를 돌리지 않았고, DOCA가 따로 연 verbs 문맥이 있는지는 모름 `[미확인]`.
- 시험 스위치 셋 md5: `gc_layer_int.diff` 31bd7e7b(13 616줄, ln4 대비; 799bd4f 대비 a534f4b3 266줄), `gc_unit_p2a2.cc` 5b412fe4(2 888줄), `gc_sites.tsv` ac621fb8(178줄, ring `.fd` 16); libnccl gc 175ea542, gcp 199bfc69, gct d5fd8dc9, gctp e5651981.
