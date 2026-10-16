# 준비 단계와 launcher의 리뷰 고침 (REVIEW_PREP.md, 2026-10-17)

## 단계 (계획)

1. 헤더: 받기 seam(`gdakiCtrlRecv`, `gdakiCtrlRecvOn`), REJOIN 거절 답 seam, 채널 seam 셋(`gdakiCtrlChanUp`, `gdakiCtrlPollFd`, `gdakiCtrlChanInstall`)과 세대 seam; `gdakiCtrlFd` 없앰
2. 호스트 트리: 자리마다 seam을 넣고(tcp 쪽은 ln4 글 그대로), 준비 단계 본문을 더함
3. `gc_sites.tsv`와 `build_gc.sh sites`(rdma 쪽만 보는 셈), 블록 다시 붙이기(`repaste`); api, pre, sites
4. 헤더 고칠 것: 확인 창(incNonce, 늘어남 비교), 주석, `gdakiCtrlCqFits`, nrp(probeGen, put/get), CONNECTED와 PAIR_DONE, `gdakiLnFenceOf`, 판정 서명, 범위 검사 둘, 생존 READ QP 상태 추적
5. 주인 나눔: 단계마다 하위 블록과 free hook, `r->ctrl`을 준비 끝에서 만듦, 활성화 결정의 FENCED hook
6. `gc_unit_prep.cc`: 새 장면, credit 불변식을 장면마다 한 번, aliasing 고침
7. `build_gc.sh` nit(SCR 필수, 정규화 주석)
8. 빌드 gc, gcp, gct, gctp; unit 두 빌드; pre; sites; diff; info
9. launcher: READ 중 ABORT, 손잡이 일련번호, ACCEPTED 뒤 QP 잃음, UD 주소 핸들(TC, 캐시), nit
10. launcher 단위 시험: 새 장면, 등록 oracle의 실제 경우; 빌드와 실행
11. 이 문서 마무리

## 끝난 단계 (한 줄씩)

- 1 끝: 헤더에 받기 seam 둘, REJOIN 거절 답 seam, 채널 seam 넷(`gdakiCtrlChanUp` 세 인자와 두 인자, `gdakiCtrlChanGen`, `gdakiCtrlPollFd`, `gdakiCtrlChanInstall`); `gdakiCtrlFd` 없앰
- 2 끝: 호스트 트리 자리 고침(받기 6, 답 2, 채널 있음 19, poll 3, 대입 1, 세대 2, 보내기 인자 13은 ln4 글로); 준비 영역을 단계마다 하위 영역으로; `api` 통과
- 3 끝: `gc_sites.tsv` 149행, `sites` 다시 씀(rdma 쪽 셈, tcp 갈래 32개가 ln4 글 그대로인지); `sites` 통과, `pre` gct/gctp/gctc 0 hunk, `gc` 빌드됨(시험 빌드 gc_fix_try1)
- 4 끝: 헤더 고칠 것 1–7(확인 창 서명과 늘어남 비교, 주석, CQ 셈, nrp 168 B와 put/get, CONNECTED 봉투 종류 6과 PAIR_DONE, `gdakiLnFenceOf`와 판정 값, 범위 검사, 생존 READ QP의 소프트웨어 상태)과 nit 1, 2, 3, 5
- 5 끝: 블록마다 단계 하위 블록, 준비 영역의 단계 하위 영역과 free hook 셋, `r->ctrl`을 연결 부분 앞에서 만듦(`gdakiCtrlStateOf` 없앰), 활성화 결정의 `gdakiCtrlActFenceOk`
- 6 끝: `gc_unit_prep.cc` 장면 수를 따로 셈, 루프 불변식은 장면마다 검사 하나, 받기 seam 동일성 시험 더함, 새 헤더 함수 시험; unit 두 빌드 통과(rdma 116 장면 366 검사, tcp 48 장면 174 검사, 실패 0)
- 7 끝: `build_gc.sh` SCR 필수, 정규화 주석, `repaste`, `api`의 CELLS 단독 거절 검사
- 9 끝: launcher 고칠 것 10–13과 nit 11–13(READ 버퍼 수명, 손잡이 일련번호와 닫을 때 사건 버림, ACCEPTED 뒤 QP 끊김에 abort 없음, 주소 핸들 캐시와 `--tc`, 페이지 release 저장, verbs 해제 차례, CQ 셈, CQ 오류와 UD QP 오류, 잃은 세대의 PAIR 버림); 빌드됨
- 10 끝: launcher 단위 시험 20 장면 414 검사 실패 0(장면 둘 더함, 등록 oracle은 장면 14개에 장면마다 검사 하나); 음성 대조(고치기 전 core)는 ASan heap-use-after-free와 lost_accepted 실패를 냄
- 8 끝: `gdakiTsSetup`에서 `r`가 null일 수 있어 `r->ctrl` 만들기를 `r != nullptr`로 막음(이것 뒤에 빌드 넷과 확인을 모두 다시 돌림, 아래 "빌드와 시험")

## 리뷰 항목마다 한 것

표시: [측정] 이 작업이 돌려서 본 것, [추론] 해석. 줄 번호 NNNN은 ln4 호스트 파일(md5 `0ab4e636`)의 줄이다.

### 막는 문제

| 항목 | 한 것 |
|---|---|
| 1. 받기 자리와 REJOIN 거절 답 | 받기 seam 둘을 더했다. `gdakiCtrlRecv(r, peer, pe, out, ms, stop)`(11896 응답 쪽 DONE 기다림, 12024 `SERVE_WAIT=0`의 ACK 기다림, 22372 MIRROR_SETUP 기다림)와 `gdakiCtrlRecvOn(r, peer, ch, fd, out, ms, stop)`(10192 REJOIN_ACK `_REJOIN`, 10235 TOKEN과 10297 DONE_RS `_RECORD`). REJOIN 거절 답 seam `gdakiCtrlRejoinFail(r, fd, peer, round, what)`을 8777과 9536에 썼다(8785 PROBE, 8815 다시 걸기의 FAIL은 증인 몫으로 둠). 8765의 첫 기록 받기는 증인의 accept로 두고(HELLO, PROBE), 그 자리가 함께 받는 DATA와 REJOIN을 `accept` 행 둘로 적었다(2단계가 UD와 outbox 길을 옆에 더함). tcp 빌드에서 셋 모두 지금 호출로 펴진다. 표에 `recv` 11행, `answer` 5행, `accept` 2행을 더했고 `sites`가 그 수를 견준다 [측정: `sites_prepfix.log`]. |
| 2. `gdakiCtrlFd(pe)` 가르기 | `gdakiCtrlFd`를 없애고 넷으로 갈랐다. (가) `gdakiCtrlChanUp(r, peer, pe)`: "기록 채널이 있음" 19곳(ln4의 `pe.fd >= 0 && !pe.gone`과 그 부정 16곳, `fd`만 보는 3곳 10306, 22339, 22372). 두 인자 꼴 `gdakiCtrlChanUp(r, peer)`도 두었다(1단계가 받은 이름; `r->ts`를 거치므로 `r->ts`가 서기 전인 `gdakiMiSetupEnd` 안에서는 못 씀. 그래서 자리들은 세 인자 꼴을 쓴다). (나) `gdakiCtrlPollFd(r, peer, pe)`: poll 둘과 MSG_PEEK 하나(11950, 12035, 12041). (다) `gdakiCtrlChanInstall(r, peer, pe, fd)`: 대입 1곳(10208). (라) `gdakiCtrlChanGen(r, peer, pe)`: kept REQ의 세대 2곳(11984, 17768; 리뷰 막는 문제 2 결과 셋째). 보내기의 TCP 뒤끝 인자 13곳은 ln4의 `pe.fd` 글로 되돌렸다(행 `arg`). "채널 있음" 검사는 꼴이 자리마다 달라 매크로 하나로 ln4 글을 낼 수 없으므로, 그 19곳과 세대 2곳은 `#if NCCL_GIN_CTRL_TCP`(ln4 줄 그대로) / `#else`(seam)로 썼다. `sites`가 tcp 갈래 32개 모두 ln4의 연속된 줄 그대로인지 검사한다 [측정]. `pe.gone`, `pe.gen`, `pe.have`를 기록 길이 읽고 쓰는 자리 11개는 표의 `state` 행이다(2단계 몫). 준비 단계 본문에서 `fd`만 보던 3곳도 `fd >= 0 && !gone`이 된다: 그 셋은 라운드가 돌기 전(예비 프로세스의 helper 시작 전, 준비 끝)이라 `gone`이 소켓과 함께 참일 수 없다 [추론: `pe.gone`을 소켓을 닫지 않고 세우는 곳은 11783, 12210, 12230의 라운드뿐]. |

### 고칠 것

| 항목 | 한 것 |
|---|---|
| 1. 확인 창의 `incNonce`와 비교 | `gdakiCtrlConfirmVerdict(countable, remacc, read1Done, read2Done, incExpected, inc1, inc2, beat1, beat2)`. 차례는 REMACC, NORESP, `incNonce`가 하나라도 다르면 확인 못함, `gdakiCtrlBeatAdvanced`(감싸는 큼 비교)면 살아 있음, 아니면 STALE. 박동이 줄면 STALE, 2^64를 넘어 감싸면 살아 있음을 단위 시험이 본다. |
| 2. 머리 주석 | "기록 QP ERR가 창을 연다"를 지우고 "BYE 없는 증인 FIN이나 RST만 연다, 기록 QP ERR, 시한, 원격 접근 오류는 열지 않는다"로 고쳤다. |
| 3. `gdakiCtrlCqFits` | `gdakiCtrlWatchCqNeed = (nPeers + nLaunchers) x 4`, `gdakiCtrlHelperCqNeed`를 따로 두고 둘로 판정한다. 경계 시험: (14, 2) 64 맞음, (15, 2) 68, (16, 2) 72 안 맞음. |
| 4. REJOIN `nrp` | `probeGen`, `rsv`를 더해 168 B. `gdakiCtrlNrpPut/Get`이 `memcpy`로 넣고 꺼내며 나머지를 0으로 둔다. `offsetof(gdakiTsMsg, nrp) % 8 == 0`을 호스트 쪽 단언에 더했다. |
| 5. CONNECTED와 PAIR_DONE | rank 사이 CONNECTED는 봉투 종류 `GDAKI_CTRL_K_CONNECTED = 6`(본문 0 B, 기록 QP의 RECV 자리와 seq 1을 쓰고 기록 층에 넘기지 않음)로 정했다. 기록 번호를 쓰지 않으므로 "새 기록은 52–55 넷"이 그대로다. launcher 헤더에 `GL_ENV_KIND_CONNECTED = 6`을 rank 사이 전용으로 적고 두 헤더의 `static_assert`에 넣었다(launcher의 `gl_env_check`는 그것을 받지 않음). 생존 READ QP는 `GDAKI_CTRL_PAIR_STEP_DONE = 3`(같은 본문). |
| 6. 빠진 순수 항목 | `gdakiLnFenceOf(viewPhase, viewDead, fencedPlus1, fenceSent)`와 NONE, FENCING, FENCED, 이름 함수. 계보 보기 구조가 붙인 블록 뒤에 있어(호스트 7712) 보기의 두 칸을 값으로 받고 `GDAKI_CTRL_LN_HOLD_WAIT`를 `GDAKI_LN_HOLD_WAIT`와 단언으로 묶었다. 판정 입력 값(L 5, B 2, W 9, R 13; 1 170점), 판정 값과 원인 이름, `struct gdakiCtrlJudgement`, `gdakiCtrlJudge(L, B, W, R)`의 서명과 빈 틀("[1] page" 하위 블록, 1단계가 채움). 매개변수 이름 `GIN_CTRL_LAUNCHER_STALL_MS`(초안 1 000), `GIN_CTRL_LATER_MS`(초안 5 000, 값은 사용자 결정 목록). 범위 검사는 `struct gdakiCtrlThresholds`를 받고 `PROBE_MS <= LAUNCHER_STALL_MS`, `LATER_MS + 1000 <= NCCL_GIN_RESTORE_MS`를 더했으며 `PROBE_MS=0`이면 W 검사 둘을 하지 않는다. |
| 7. `gdakiProbeQpIsRts`의 QUERY_QP | `struct gdakiProbeQp`에 `okInGen`을 두었다. `gdakiProbeQpIsRts`는 소프트웨어 상태(`connected && !err`), `gdakiProbeQpOkInGen`(그 세대의 성공 READ 있음), `gdakiProbeQpOnSuccess(q, gen)`(다른 세대 완료는 버림), `gdakiProbeQpOnError`. QUERY_QP는 `gdakiProbeQpQueryState`라는 이름으로 남기고 준비와 진단에만 쓴다고 적었다. |
| 8. 붙인 블록과 free의 주인 | 헤더의 두 블록 안에 "[1] page", "[2] ring", "[3] launcher" 하위 블록, 호스트 준비 영역에도 같은 하위 영역 셋을 두고 단계마다의 빈 틀을 그 안으로 옮겼다(swap point 본문은 "[2] ring"). `gdakiCtrlFree`는 `gdakiCtrlPageFree`, `gdakiCtrlRingFree`, `gdakiCtrlLauncherFree`를 차례로 부른다. `r->ctrl`은 rdma `gdakiTsSetup`이 연결 부분(`gdakiTsSetupConnect`) 앞에서 늘 만든다(`gdakiMiSetupEnd`가 그 안에서 돌기 때문). `gdakiCtrlStateOf`는 없앴다. `build_gc.sh repaste`가 헤더의 두 블록을 트리에 다시 붙인다(어느 BR이든). |
| 9. 활성화 결정의 FENCED | `gdakiHoldActivateDecide`의 `d->go = true` 바로 앞에 `if (!gdakiCtrlActFenceOk(r, peer, dead)) return;`(rdma 갈래만). 주인은 1단계이고 준비 단계 본문은 true다. false면 그 걸음에 활성화하지 않고 hold 걸음이 다시 묻는다. 예비 등록이 없는 등의 fallback은 그 앞에서 지금처럼 곧바로 일어난다. |
| 10. READ 중 버퍼 해제 | 항목마다 `readBusy`, `readHandle`을 두고, 버퍼를 놓을 때(`gl_blob_release`) READ가 나가 있으면 core의 orphan 표로 옮긴다. orphan은 그 READ의 완료(손잡이와 cookie로 맞춤)나 그 QP의 `rc_close` 뒤에만 푼다. `gl_abort`, `gl_spare_fail`, `gl_entry_reset`, `gl_entry_free`, `gl_core_free`가 모두 이 길을 탄다. 장면 `abort_during_read` 셋(READ 중 ABORT 뒤 늦은 완료, READ 중 예비 프로세스 끝남과 그 칸의 다시 씀, READ 중 짝 QP 잃음) [측정: 통과]. 고치기 전 core에 같은 시험을 걸면 ASan heap-use-after-free로 멈춘다 [측정: 음성 대조]. |
| 11. 손잡이 다시 씀 | verbs 전송의 손잡이를 `(일련번호 << 8) | 칸`(22비트)으로 바꾸고, 모든 완료와 사건을 칸의 지금 손잡이와 견준다. `rc_close`는 그 손잡이의 대기열 사건을 지운다. 시험 전송에 verbs와 같은 번호 꼴(`slotMode`)과 음성 대조(`noSerial`: 칸 번호만, 대기열 사건 남김)를 두고 장면 `handle_reuse`를 더했다. 고친 꼴에서 옛 QP의 RC_ERROR와 말은 새 QP에 닿지 않고, 음성 대조에서는 새 QP를 다시 짝 맺게 만든다 [측정]. 시험 전송의 `rc_close`도 그 QP의 READ와 사건을 버린다(전송 계약). |
| 12. ACCEPTED 뒤 QP 잃음 | `gl_abort_of_peer`는 ACCEPTED 활성화를 그만두지 않는다(줄 하나만). FETCH 말은 대기열에서 기다렸다가 다시 맺은 QP로 간다. ACCEPTED 뒤의 활성화를 끝내는 것은 짝의 명시 ABORT와 FENCE뿐이다. 리뷰는 "FETCH_DONE 뒤만 빼기"를 안으로 냈으나 지시대로 ACCEPTED 전부를 뺐다(FETCH 전후 같음). 장면 `lost_accepted` 둘째 몫을 새 동작으로 바꿨다: QP 끊김 300 ms 동안 신호 0, 다시 짝 맺은 뒤 FETCH_EP가 감, 둘째 끊김 뒤 명시 ABORT에만 SIGKILL [측정]. |
| 13. UD 주소 핸들 | 주소 핸들은 목적지 (GID, LID)마다 한 번 만들어 transport를 닫을 때까지 둔다(주소 핸들은 QPN에 매이지 않으므로 리뷰의 (GID, QPN)이 아니라 (GID, LID)). `--tc`(기본 `NCCL_IB_TC`, 없으면 0)로 traffic class를 받아 UD와 RC 길 모두에 넣는다. verbs 전송은 빌드만 했다(실행 안 함). |
| 14. `.gitignore`의 `!*.tsv` | 하지 않음: `control/impl/` 밖의 파일이라 이 작업이 고칠 수 없다. 조율 세션이 경로 하나(`!harness/gpu-initiated/gin_recovery/control/impl/gc_sites.tsv`)로 좁혀야 한다. |
| 15. 둘째 매크로 이름 | 코드 이름 `NCCL_GIN_CTRL_TCP_CELLS`, 빌드 키 `gctc`를 그대로 둔다. 설계 2.0절과 v3 S3, 실험 문서 머리 빌드 키 표, 9.3절, 9.8절 표의 `NCCL_GIN_CTRL_TCP_EXT`/`gctx`를 조율 세션이 고쳐야 한다. |

### nit

| nit | 한 것 |
|---|---|
| 1 | 배치 주석을 320 B로 고침 |
| 2 | 바쁨 번호는 감시 스레드가 쥐는 `struct gdakiCtrlBusyTrack`의 일련번호(시작이 바뀌거나 쉰 걸음 뒤면 다음 번호, 0 없음). 쓰는 쪽이 하나라 원자 카운터 대신 이것을 썼다 |
| 3 | PAIR 봉투는 144 B나 256 B만 받음 |
| 4 | 코드는 64비트 그대로, 헤더에 까닭과 크기 단언. 설계 4.4절 4번의 "32비트"는 조율 세션이 고침 |
| 5 | `NCCL_GIN_CTRL_TCP_CELLS=1`인데 `NCCL_GIN_CTRL_TCP`가 아니면 `#error`; `api`가 그 꼴이 컴파일되지 않음을 본다 [측정] |
| 6 | `SCR=${SCR:?...}` |
| 7 | 정규화 주석에 빈 줄을 지운다고 적음 |
| 8 | 문서 문장 몫. 아래 12절 문장에 "장치 헤더 digest가 같아 장치 객체를 다시 빌드하지 않음"으로 씀 |
| 9 | 장면 수를 따로 세고, 루프의 같은 불변식은 장면마다 검사 하나로 셈. `memcpy`로 봉투를 옮김 |
| 10 | 등록 oracle은 장면마다 검사 하나(장면 실제 정답과 경로, 무장 비트 둘). 장면 셋을 더함(두 화신 앞의 HELLO 거절, 보기의 화신이 등록과 다름, 예비 READY): 14 장면 |
| 11 | 페이지 낱말은 모두 `__atomic_store_n`(release) |
| 12 | QP를 먼저 없앰, CQ 셈 검사(1 024에 안 들면 QP를 만들지 않음), CQ 오류는 `GL_TP_FATAL`로 launcher를 멈춤, UD QP 오류는 UD QP를 다시 세움, DEVICE_FATAL도 멈춤 |
| 13 | 낮은 세대는 QP가 있든 없든 버리고, 잃은 QP의 세대와 같은 PAIR도 버림(장면 `pairing`에 더함) |
| 14 | 표의 8439와 10208 행에 같은 사건의 두 쪽임과 rdma에서의 뜻(소켓은 두 쪽 모두 증인 몫, 기록 채널은 옆에 세움)을 적음 |
| 15, 16 | 문서 몫: 조율 세션이 고침(7.1절 `NO_EXIT_REPORT` 행, 9.1절 `rxConsumed` 이름, 페이지 차례는 헤더 기준; 7.1절 `gdakiTsSend` 갈래는 표 기준 REJOIN 2, 기록 14) |

### 하지 않은 것과 까닭

- 고칠 것 14, 15와 nit 4, 8, 15, 16의 문서 고침: `control/impl/` 밖이거나 실험 문서라 이 작업이 고칠 수 없다(위 표).
- 막는 문제 2 고침 3의 "대입을 `pe.fd = fd`로 되돌림": 지시대로 대입도 seam(`gdakiCtrlChanInstall`)으로 했다.
- 막는 문제 2 고침 1의 "fd 꼴(0 이상) 표지": 지시대로 bool `gdakiCtrlChanUp`으로 했다. 그 대신 tcp 쪽은 자리마다 `#if`로 ln4 글을 둔다.
- 알릴 것 1–12는 1단계와 2단계(일부 3단계)가 할 일이라 아래 목록에 옮기기만 했다.

## 새 수

- `gc_sites.tsv` 149행 [측정]: send 26(swapped 18, kept 8), pump 7(swapped 5, kept 2), recv 11(swapped 6, kept 5), answer 5(swapped 2, kept 3), holdsend 17, fd 56(kept 30, chanup 14, arg 9, pollfd 2, install 1), fd-other 14(chanup 5, arg 4, kept 4, pollfd 1), accept 2, state 11(changen 2, kept 9).
- seam 쓰임(트리의 rdma 쪽) [측정]: `gdakiCtrlSend` 18, `gdakiCtrlPump` 5, `gdakiCtrlRecv`와 `gdakiCtrlRecvOn` 6, `gdakiCtrlRejoinFail` 2, `gdakiCtrlChanUp` 19, `gdakiCtrlPollFd` 3, `gdakiCtrlChanInstall` 1, `gdakiCtrlChanGen` 2. 남은 `.fd` 쓰임 55(ln4 코드 줄의 `.fd` 78 − seam으로 간 23; `sites`가 표와 견줌), `pe.fd` 44.
- `gc_layer.diff` 2 123줄(호스트 파일 하나), `rs_ctrl_api.h` 1 022줄(붙이는 블록 API 749줄, seams 120줄).
- 단위 시험 [측정]: `gc_unit_prep` rdma 116 장면 366 검사, tcp 48 장면 174 검사, 실패 0. 고치기 전 보고의 rdma 1 026 745, tcp 7 842 검사는 루프마다 검사를 센 수였다(nit 9). launcher 20 장면 414 검사 실패 0(등록 oracle 14 장면, 장면마다 검사 하나). 고치기 전은 18 장면 418 검사였다.

## 1단계와 2단계(와 3단계)가 묶을 seam

선언은 헤더의 seams 블록에 있고, 준비 단계 본문은 호스트 파일 준비 영역의 그 단계 하위 영역에 있다. 단계는 자기 하위 영역의 본문만 바꾸고, 새 선언은 헤더 두 블록의 자기 "[n]" 하위 블록에만 더한 뒤 `build_gc.sh repaste`로 트리에 붙인다(`api`가 같음을 본다). 붙인 블록과 준비 영역의 나머지 줄은 고치지 않는다.

- **1단계 ("[1] page")**
  - `gdakiProbeToErr(r, peer)`: 생존 READ QP를 감시 스레드의 요청 낱말로 ERR로.
  - `gdakiLnFenced(r, peer, inc)`: FENCED를 펜스 낱말 `gdakiCtrlFenceWord(inc)`로(올리기만).
  - `gdakiCtrlActFenceOk(r, peer, dead)`: 활성화 결정의 마지막 조건(`gdakiCtrlFencedIs(word, dead)`; launcher와 짝 맺지 않은 문맥의 길은 1단계가 정함).
  - `gdakiCtrlPageFree(r)`: `r->ctrl->page`를 풀고 null로.
  - `gdakiCtrlJudge(L, B, W, R)`: 헤더 API 블록 "[1] page" 하위 블록의 빈 틀을 21행 표로 바꿈.
  - 부르기만 하는 것: 생존 READ QP API(`gdakiProbeQpCreate`, `Endpoint`, `Connect`, `Reconnect`, `IsRts`, `OkInGen`, `OnSuccess`, `OnError`, `Destroy`; `QueryState`는 진단만), `gdakiCtrlConfirmVerdict`(새 서명), `gdakiCtrlBusyOf`(추적 구조), `gdakiCtrlThresholdsOk(struct gdakiCtrlThresholds)`, `gdakiLnFenceOf`, `gdakiCtrlChanUp(r, peer)`(두 인자; `gdakiMiSetupEnd` 안 말고), `gdakiCtrlLauncherSend`.
- **2단계 ("[2] ring")**
  - swap point 본문: `gdakiCtrlSend`, `gdakiCtrlPump`, `gdakiCtrlRecv`, `gdakiCtrlRecvOn`, `gdakiCtrlRejoinFail`(UD 답; WAIT, REFUSE와 FAIL을 가르는 꼴도 2단계, 알릴 것 9).
  - 기록 채널 상태: `gdakiCtrlChanUp(r, peer, pe)`(두 인자 꼴은 이것을 부름), `gdakiCtrlChanGen(r, peer, pe)`, `gdakiCtrlPollFd(r, peer, pe)`(음수면 poll이 무시하고 peek가 실패해 pump가 읽음), `gdakiCtrlChanInstall(r, peer, pe, fd)`.
  - hook: `gdakiCtrlRecordToErr`, `gdakiStoreWardToErr`, `gdakiCtrlRingFree`.
  - 표의 `state` 행 11개와 `accept` 행 2개(8765의 DATA와 REJOIN 옆 길)는 2단계가 링 몫 상태를 둘 자리다. 링의 받기 실패에서 `gdakiTsSocketLost`를 부르지 않게 하는 것(알릴 것 6)도 이 seam들 안에서 한다(`gdakiCtrlPump`가 링 잃음에 -1을 돌려주지 않음 등).
  - 봉투 종류 6 CONNECTED(본문 0 B), `GDAKI_CTRL_PAIR_STEP_DONE`, `gdakiCtrlNrpPut/Get`(세대 둘)을 쓴다.
- **3단계 ("[3] launcher")**: `gdakiCtrlOnHoldStart`, `gdakiCtrlLauncherSend`, `gdakiCtrlLauncherFree`; 그리고 지금처럼 `gdakiHoldActivateSend`, `gdakiRsSpareActivateWait`의 본문.
- **모두**: `r->ctrl`은 연결 부분 앞에서 만들어지고(`r`가 있을 때) 그 전과 helper 없는 문맥에서는 null이다. `gdakiCtrlStateOf`는 없다. 리뷰의 알릴 것 1–5, 7, 8, 10–12(보고 줄의 둘째 꼴, 칸 크기, 페이지 배치는 헤더 기준, 본문을 함께 쓰는 다섯 함수, 화신과 HELD 입력 없는 `gdakiCtrlPairResolve`, UD launcher 봉투, BYE 자리 셋, hook 멱등, launcher의 쌓인 말)는 그대로 유효하다.

## 빌드와 시험

모두 이 worktree의 `control/impl/`에서, `SCR=<세션 스크래치>`와 `BR=prep`로 돌렸다. 로그는 `agent_gc_prep/` 아래(아래 경로는 그 폴더 기준), 마지막 판의 것만 적는다. ssh, 클러스터, verbs 장치, GPU 실행 없음.

| 명령 | 결과 | 로그 |
|---|---|---|
| `build_gc.sh repaste`, `api` | 두 블록이 헤더와 바이트 그대로(ctrl API `a80a46b8`, ctrl seams `1d1a4950`), 헤더 단독 컴파일 rdma와 tcp, 진입점 선언 있음/없음; `NCCL_GIN_CTRL_TCP_CELLS=1` 단독은 `#error`로 거절 [측정] | `api_prepfix2.log` |
| `GCOUT=gc_prepfix2 build_gc.sh gc` (gcp, gct, gctp 같은 꼴) | 넷 모두 빌드됨, 경고 0. libnccl gc `3da00c44`, gcp `c7071fde`, gct `53839937`, gctp `9cc633ab` [측정] | `build_{gc,gcp,gct,gctp}_prepfix2.log`, `out/*_prepfix2/` |
| `build_gc.sh pre` | gct, gctp, gctc 정규화 뒤 0 hunk, 줄 수 ln4와 같음(150 748, 150 175); gc는 62 hunk(새 코드, 기록용) [측정] | `pre_prepfix2.log`, `out/pre/` |
| `build_gc.sh sites` | 표 149행과 트리의 rdma 쪽 셈이 모두 같음, tcp 갈래 32개 모두 ln4 글 그대로 [측정] | `sites_prepfix2.log` |
| `build_gc.sh unit` | 두 빌드 통과. gin-mirror 다섯, gin-restore 둘은 고침 없이 실패 0. `gc_unit_prep` rdma 116 장면 366 검사, tcp 48 장면 174 검사, 실패 0 [측정] | `unit_prepfix2.log` |
| `IDTAG=prepfix2 build_gc.sh ident` | 매크로 없는 프로그램 16/16 SASS와 자원 같음; 네 빌드 디렉터리의 장치 객체 207개씩 ln4와 같음(장치 헤더 digest가 같아 다시 빌드되지 않은 사본: 바이트도 같음); 라이브러리 넷의 자원 사용 같음 [측정] | `ident_prepfix2.log`, `out/ident_prepfix2/` |
| `build_gc.sh diff`, `info` | `gc_layer.diff` `0df79ae2`, 2 123줄, 호스트 파일 하나 | `diff_prepfix2.log`, `out/build_info_prepfix.txt` |
| `OUT=…/scratchpad/launcher_build2 launcher/build_launcher.sh all` 후 `unit` 두 번 더 | 빌드됨(verbs 전송 포함, 실행하지 않음; `gin_launcher` `3011dbd4`, `launcher_unit` `2c3a1a82`), 단위 시험 3/3 실행 통과: 20 장면 414 검사 실패 0 [측정] | `launcher_build2/unit_run1–3.log` |
| 음성 대조: 고치기 전 `gin_launcher.c`(HEAD) + 새 `launcher_unit.cc` | `lost_accepted` 실패, `abort_during_read`에서 ASan heap-use-after-free로 멈춤 [측정] | `scratchpad/launcher_negctl/unit_old.log` |

- 앞선 시도: `ident_prepfix.log`는 돌던 중 `build_gc.sh`를 고쳐 스크립트 끝에서 문법 오류로 끝났다(비교 줄은 모두 같음). 그 판은 쓰지 않고 위의 `prepfix2`로 다시 돌렸다. `*_prepfix.log`(접미 2 없음)는 null 막기 전 판이다.
- `gc_unit_prep`의 셈이 앞 보고(rdma 1 026 745, tcp 7 842)보다 작은 것은 같은 불변식을 걸음마다 세던 것을 장면마다 하나로 바꿨기 때문이다(nit 9).

## 파일 md5 (worktree `control/impl/`)

| 파일 | md5 |
|---|---|
| `rs_ctrl_api.h` (1 022줄) | `998b493b8e40f79a85cb5423cb4045b0` |
| `gc_layer.diff` (2 123줄) | `0df79ae2c8b3a285383a48adbbf5ebad` |
| `gc_sites.tsv` (161줄, 149행) | `2487fe82a352536cce2c5f48b830d58b` |
| `build_gc.sh` | `3c819bb2b55e114dee1fa556cd4618c3` |
| `gc_unit_prep.cc` | `f2264508a2f8a669c17f78c688a5c140` |
| `launcher/gin_launcher.c` | `56c10d8ebc62255bf378d859e387ed31` |
| `launcher/launcher_transport_verbs.c` | `172385319a49b5de5e5ecbeec5a8aa5a` |
| `launcher/launcher_transport.h` | `c3db8baf1d803fec035dc5fca4f2b91a` |
| `launcher/launcher_msg.h` | `897641f3ee15407f597fa4f1523a5302` |
| `launcher/launcher_unit.cc` | `c4ba9dc530d160b7bbdbf0fe5d6df160` |
| `launcher/README_launcher.md` | `76e2fb550271d8e7707f1f2d12268941` |
| `launcher/gin_launcher.h`, `build_launcher.sh` | 바뀌지 않음 (`e80ac5d0`, `22069678`) |
| `../../mirror/impl/mi_layer.diff` | `dcd30859ac6db214e37475c527c37e2f` (바뀌지 않음) |

## EXPERIMENT.md에 넣을 문장 (조율 세션용)

**11절(작업 체크리스트)**

- [x] 준비 단계 리뷰(REVIEW_PREP: 막는 문제 2, 고칠 것 15, nit 16) 고침: 받기 seam 둘과 REJOIN 거절 답 seam, 기록 채널 seam 넷(`gdakiCtrlChanUp`, `gdakiCtrlChanGen`, `gdakiCtrlPollFd`, `gdakiCtrlChanInstall`), 헤더 고칠 것 1–9, launcher 고칠 것 10–13. 고칠 것 14(`.gitignore`), 15(둘째 매크로 이름을 문서에서 `NCCL_GIN_CTRL_TCP_CELLS`, `gctc`로)와 nit 4, 8, 15, 16의 문서 고침은 남음. 근거 `impl/notes_prepfix.md`.
- [ ] 1단계와 2단계 트리를 고친 준비 단계(`gc_layer.diff` `0df79ae2`) 위로 다시 올림.

**12절(실행 기록)**

- 2026-10-17, 준비 단계와 launcher의 리뷰 고침(실행 없음, CPU와 빌드만). 네 빌드(gc, gcp, gct, gctp)가 빌드됨 `[측정: impl/notes_prepfix.md, build_*_prepfix2.log]`. tcp 빌드 셋(gct, gctp, gctc)의 전처리 결과는 경로와 `__LINE__`을 맞춘 뒤 ln4와 0 hunk다 `[측정: pre_prepfix2.log]`. 장치 쪽은 매크로 없는 프로그램 16/16이 ln4와 SASS가 같고, 장치 헤더 digest가 같아 장치 객체 207개는 다시 빌드되지 않았다(사본이라 바이트도 같음) `[측정: ident_prepfix2.log]`. 단위 시험은 두 빌드에서 통과했다: `gc_unit_prep` rdma 116 장면 366 검사, tcp 48 장면 174 검사, gin-mirror와 gin-restore의 일곱은 고침 없이 실패 0 `[측정: unit_prepfix2.log, n 1]`. 앞 보고의 1 026 745와 7 842는 같은 불변식을 걸음마다 센 수였다. launcher 단위 시험은 20 장면 414 검사로 3/3 실행 통과했고(ASan, UBSan; 등록 oracle은 14 장면에 장면마다 검사 하나), 고치기 전 core에 같은 시험을 걸면 READ 중 ABORT 장면에서 ASan heap-use-after-free가 난다 `[측정: launcher_build2/unit_run1–3.log, launcher_negctl/unit_old.log]`. verbs 전송은 빌드만 했다.
