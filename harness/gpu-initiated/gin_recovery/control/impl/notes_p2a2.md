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
