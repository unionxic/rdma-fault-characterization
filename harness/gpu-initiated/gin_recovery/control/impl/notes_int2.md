# gin-control int2: 감시 스레드 고침 3, 3단계, 2a-2 A+B를 한 층으로 (작업 기록)

## 단계 목록 (12줄)

1. 트리 `agent_gc_p2a2/`: 작업 트리를 "gin-control 2a-2-B (gc_layer_p2a2.diff 414a8790)"로 커밋
2. 2efebe3 위 가지 둘(fix3, p3)을 만들고 3-way로 합침: fix3 먼저, 그다음 p3, 충돌 해결
3. 헤더: 948b3ecf에 p2b, p2a2, p3 요청 차례로, launcher 헤더 붙임을 f8e3216e의 `launcher_msg.h`로 새로 붙임, `repaste`, `api`
4. `build_gc.sh`에 키 `int2`(p2a2, p3, fix3의 몫과 `gc_unit_prep`의 "링 없음" 답), `syn`
5. 접착 1–2: 전송 표 넷(UD PAIR, launcher peer nranks + li, LAUNCHER 봉투), 받기가 `gdakiCtrlLauncherOnEnvelope`로
6. 접착 3: all-gather 칸 `AgInfo`/`AgTake`, 페이지 배치의 `nLaunchers`(`creditOff`가 `staleMs`를 가리키지 않게)
7. 접착 4–6: 활성화 덩어리의 outbox 자리, launcher 페이지 끌어 읽기 → `gdakiCtrlLaOnBeat`, Resume 41; INFO의 TODO(launcher) 풂
8. `gc_sites.tsv`, `sites`; 시험 고칠 것(덮는 범위 유지)
9. 빌드 넷(경고 0), `pre`, `unit` 두 빌드, `ident`
10. `gc_layer_int.diff` 다시 씀(ln4 대비 전체 층), 산출물 md5
11. 이 문서 마무리: 충돌과 해결, 접착 여섯, 헤더, 수, 검사 표, 2a-2-C에 남은 것, EXPERIMENT.md 11/12절 줄(안)

## 끝낸 단계 (한 단계 한 줄)

- 1 끝: 커밋 242447c "gin-control 2a-2-B (gc_layer_p2a2.diff 414a8790)"(2efebe3 대비 diff md5 414a8790 확인) `[측정]`
- 2 끝: 가지 fix3 a3fe681(2efebe3 + fix3, 그대로 적용), p3 94c3e28(2efebe3 + p3, 그대로 적용; e3faf02와 다른 것은 주석 두 줄뿐); fix3 합침 341f106 충돌 0, p3 합침 27acdf0 충돌 1(all-gather 앞 준비 블록: 링 만들기 다음 INFO) `[측정]`
- 3 끝: 헤더 948b3ecf + p2b(6c01c6ff) + p2a2(a31c85cb), p3(0eed95b6)는 `git merge-file`로 충돌 0 → 023f013d; 트리의 붙인 블록은 합침 결과와 이미 같음; launcher 헤더 붙임 544 → 554줄(fb11b235); `api`, `syn` 통과 `[측정: logs_int2/api_s3.log, syn_s3.log]`
- 4 끝: `build_gc.sh`에 키 p2b, p2a2, fix3, p3, int2(트리 `agent_gc_p2a2/` 제자리, 입력과 시험은 이 폴더); 합친 트리의 첫 `unit`에서 `gc_unit_p2a2`만 컴파일 실패(fix3의 넘기기) → 시험과 `p2a2regions` 고침, 통과 `[측정: logs_int2/unit_s4.log, unitp2a2_s4.log]`
- 5–7 끝: 접착 여섯(아래 절), `gc_unit_p3`의 INFO 장면을 답하는 launcher로, `gc_unit_p2a2`에 장면 7; `syn` 세 빌드, `unit` 두 빌드 통과 `[측정: logs_int2/syn_s9.log, unit_s8.log, unitp2a2_s9b.log, unitp3_s9b.log]`
- 8 끝: `gc_sites.tsv`는 바꿀 것 없음(2a-2-B 판 450fe8bd), `sites` 통과 `[측정: logs_int2/sites_s10.log]`
- 9 끝: 빌드 넷 경고 0, `pre` 기대대로; `unit` 첫 판(s12)은 tcp에서 내 장면 7이 `#if !NCCL_GIN_CTRL_TCP` 밖이라 컴파일 실패 → 감쌈, 다시 두 빌드 통과; `ident` 같음 `[측정: 아래 표]`
- 10 끝: `gc_layer_int.diff` c0975edb(10 948줄, ln4 커밋 f53e5d2 대비, 거꾸로 적용 확인); 그 가운데 접착(작업 트리 대 27acdf0) 991줄 md5 6ade6aa3, 611 더함 75 뺌, hunk 38, `__device__`/`__global__` 더한 줄 0 `[측정: logs_int2/diff_s12.log]`. 단계별 diff는 그대로(fix3 2f469461, p3 c755b1df, p2a2 414a8790, p2b fa3f1b48)
- 11 끝: 이 문서

트리는 스크래치 `agent_gc_p2a2/`이고 복사하지 않고 제자리에서 했다(디스크). 역사: 79d7e25 int+fix12 → 2efebe3 +2b → 968b4ba 헤더 초안 → 61454d9 2a-2-A → 242447c 2a-2-B → 341f106 + fix3(가지 a3fe681) → 27acdf0 + p3(가지 94c3e28); 접착은 작업 트리. 호스트 파일 하나, 장치 코드 0줄. 클러스터, ssh, verbs 장치, GPU 실행 없음. 저장소에는 `git add`, commit, push를 하지 않았다. 표시: `[측정]` 돌려서 봄, `[소스]` 코드를 읽어 확인, `[추론]` 해석, `[미확인]` 확인 안 함.

## 충돌과 해결

| 자리 | 실제로 난 것 | 해결 |
|---|---|---|
| 헤더 붙임 블록 | 글자 충돌 0(두 가지의 블록 바뀜이 겹치지 않음) | 헤더를 합친 뒤 `repaste`: 트리의 블록과 바이트 같음 `[측정]` |
| 준비 영역 하위 블록(all-gather 앞) | 충돌 1: 2a-2-A의 `gdakiCtrlRingSetup`과 3단계의 `gdakiCtrlLauncherQuery`가 같은 자리 | 둘 다, 차례는 링 만들기 → INFO(규칙: setup → ring → launcher). 그 뒤 접착 3의 `mine.la` 한 줄 |
| 한 줄 끼우기 셋 | 글자 충돌 0 | 뜻을 확인함 `[소스]`: `gdakiTsStart`는 `gdakiPageSetup` → REGISTER(링은 all-gather 앞 `gdakiTsSetup`에서 이미 섬); `gdakiTsMain`은 링 펌프(`gdakiCtrlHelperLiveStep`, `gdakiCtrlPageHelperStep` 안의 링 걸음) → `gdakiCtrlLauncherStep`; `gdakiTsStop`은 LEAVING → 증인 BYE(`gdakiTsCloseAll`) → 링 해제(`gdakiCtrlFree`). 링에는 따로 BYE가 없다 |
| ring 모형 두 hunk(fix3의 연결된 적 없는 세대의 −1 없음 대 2a-2-B 펌프) | 글자 충돌 0 | fix3 글 그대로(규칙: 링 영역은 2a-2가 이기나 2a-2-B는 이 두 hunk를 고치지 않았음). `gc_unit_p2a2`(−1 한 번 기대)와 `gc_unit_p2`(fix3 판 5612fd13) 모두 통과 `[측정]` |
| page 영역(fix3) 대 `gdakiCtrlRingSetup` | 글자 충돌 0 | fix3 글 그대로. 합친 뒤 `gc_unit_p2a2`가 컴파일되지 않음: `GDAKI_CTRL_PO_*`가 순수 영역으로 옮겨 두 번 정의, `reqDone` 없음, `gdakiCtrlProbeAnswer`가 helper 펌웨어(`gdakiProbeHandHelper`)를 부름 → 아래 시험 고침 |
| `gc_sites.tsv` | 3단계는 표를 고치지 않았음(057a6da0 그대로) | 2a-2-B 판(450fe8bd) 그대로; `sites` 통과, 149행, `#if NCCL_GIN_CTRL_TCP` 갈래 44개(2a-2 39 + 3단계 5) 모두 ln4 글 `[측정]` |
| launcher 헤더 붙임 | 3단계는 897641f3을 붙임 | launcher 커밋 f8e3216e의 `launcher_msg.h`(fb11b235, 554줄)로 다시 붙임, `api`가 바이트 같음을 봄 |

## 접착 여섯 (notes_p3.md TODO(2a-2) 1–6, 이 통합에서 구현)

1. **전송 표 넷**(`gdakiCtrlLaTxUd/Create/Connect/Send`). 링 뒤끝에 "the launchers' record QPs" 묶음을 더함: launcher li마다 기록 QP 하나(`gdakiCtrlQpAttrLauncher`, RECV 64개를 RTR 전에, 새 PSN, 세대마다 새 QP), 봉투 kind LAUNCHER + 256 B, seq는 (QP, 방향, 세대)마다 1부터, ackSeq는 이 rank의 소비 수, 소비 낱말 `(gen << 32) | 수`는 페이지 `rxConsumedL[li]`. launcher의 창(64)을 넘으면 대기열(256), 보내기 칸 32. UD는 링 UD QP로 봉투 kind PAIR(gen, seq 0)와 launcher의 Q_Key, AH는 launcher마다 하나. 리뷰의 "링 peer 목록의 nranks + li" 대신 링 안의 따로 된 표(`g->la`, work request의 peer 칸 0xf00 + li)로 했다: rank 쌍의 코드 길(셈, 요약, 펌프)이 launcher를 rank로 세지 않게 `[추론]`
2. **받기**. UD 받기는 `from & GDAKI_CTRL_FROM_LAUNCHER`인 datagram(봉투 검사, kind PAIR, 256 B)을 `badDgrams`로 버리지 않고 링의 `laIn`에 둔다. 기록 QP의 받기는 순서(gen, seq = 마지막 + 1)를 보고 어기면 그 QP를 잃음으로. 넘기기는 CQ 고리 밖, 잠금 없이: `gdakiCtrlLauncherStep` 머리에서 `laIn`을 비워 `gdakiCtrlLauncherOnEnvelope`로(그 안에서 링크 잠금을 잡음), 그 뒤 링크의 걸음(FETCH_DONE 넘김이 같은 걸음에). helper만 부름
3. **all-gather 칸**. `gdakiTsAddr`(rdma)에 `gdakiCtrlLaAgInfo la`(72 B; 기록 56 + 168 + 72 B, static_assert), all-gather 앞 INFO 다음 `gdakiCtrlLauncherAgInfo(r, &mine.la)`, 뒤 `gdakiCtrlLauncherAgTake`. launcher 수는 새 순수 함수 `gdakiCtrlLaAgCount`(이름 붙은 서로 다른 노드)로 모든 rank가 같은 값을 얻고, 링(`gdakiCtrlRingLaunchers`: 페이지 배치 다시 계산, CQ에 맞으면 launcher QP 자리)과 페이지(`gdakiPageSetup`의 `pg->nLaunchers`)가 그 값을 쓴다. 그래서 `creditOff = creditOff0 + 8 li`는 `rxConsumedL[li]`이고 `staleMs`를 가리키지 않는다(장면 7이 `staleMsOff = rxConsumedLOff + 8`을 봄). 링크의 `ud`, `qkey`(링 UD의 것: nonce가 아니라 salt에서), `page`, `creditOff0`은 `gdakiCtrlLauncherSetup`에서 링과 페이지의 것으로
4. **활성화 덩어리의 자리**. outbox 반이 아니라 링 옆의 전용 REMOTE_READ 칸(64 KiB = `GL_U_MAX_PAYLOAD`, static_assert). 2b의 STATE나 rkey 전송이 그 칸을 덮을 수 없어서 LATER 뒤 READY가 1 000 ms 늦어도 덩어리가 남는다(REVIEW_P3 "합칠 때 볼 것" 8). rank는 한 ward의 짝이라 한 번에 활성화 하나
5. **launcher 페이지 끌어 읽기**. helper가 launcher 기록 QP로 페이지 앞 16 B(magicVer, beat)를 READ(launcher QP는 REMOTE_READ, max_dest_rd_atomic 1 `[소스: launcher_transport_verbs.c]`), 50 ms에 한 번, 하나만 진행; magic이 맞으면 `gdakiCtrlLaOnBeat`. helper 자기 걸음 사이가 문턱의 반을 넘으면 박동 시계를 다시 시작한다(느린 helper가 launcher를 잃은 것으로 보지 않게). 리뷰가 쓴 "감시 스레드가 생존 READ QP(PAIR sub PROBE)로"와 다르다: 그 QP 짝 맺기는 넘기기와 감시 스레드 칸이 필요해 2a-2-C로 남김. `pullOk`(판정 표 L)는 그대로 false
6. **Resume 41**. `gdakiCtrlResumeFacts`의 launcherNamed = 이 프로세스가 복원을 청해 launcher 링크가 있음, launcherPaired = 걸쇠. 링이 없으면 41–44 모두 없음(앞과 같음)

함께 고친 것: INFO의 TODO(launcher) 풂(launcher f8e3216e가 kind 8, 9와 `GL_U_KIND_MAX` 9를 들임: rank 쪽은 `gl_unix_check`를 거친 `GL_U_INFO_ACK`만 받음, sub와 nonce 0 확인, 200 ms 한도 그대로); 링이 묶이기 전에는 launcher 짝 맺기를 하지 않음, QP 없는 PAIR를 다시 보내지 않음(만들기가 실패했으면 다시 만든 뒤에만); 끝난 TODO(2a-2) 주석과 fallback 글 "(TODO(2a-2): the ring and its outbox)" → "(no ring, or the blob does not fit its slot)"(앞머리는 같아 시험의 `strstr` 그대로).

## 헤더

948b3ecf에 `rs_ctrl_api_p2b.diff`(→ 6c01c6ff), `rs_ctrl_api_p2a2.diff`(→ a31c85cb)를 차례로, `rs_ctrl_api_p3.diff`는 6c01c6ff 대비라 `git merge-file`로 3-way(충돌 0) → 023f013d, 1 296줄. 전송 머리(`gdakiCtrlXferHdr`)는 한 번만 있음 `[측정: grep]`. 접착은 헤더를 바꾸지 않았다(새 것은 모두 호스트 영역). `GL_U_KIND_MAX`는 launcher 쪽에서 이미 9라 rank 쪽 INFO를 켰다.

## 시험 고침 (덮는 범위는 그대로이거나 넓어짐)

- `gc_unit_p2a2.cc`(7a9cd690 → 이 판): 가짜 감시 스레드가 fix3의 넘기기 순수 걸음(NEW → take → FW → done → BACK → IDLE)으로 답함, `gdakiProbeHandHelper`는 빈 몸(가짜 걸음이 한 번에 다 함); 장면 7 새로(launcher 수와 배치, 묶기 전 QP 없음, 창 64와 보내기 칸 32로 70개, launcher의 답과 소비 낱말, 박동 READ 두 번과 50 ms, datagram 양쪽과 Q_Key, 잘못된 것 하나, 덩어리 READ와 너무 큰 것, 순서 틈의 잃음 한 번, 새 세대, AH와 MR 새지 않음)
- `gc_unit_p3.cc`(e01665cd → 이 판): INFO 장면을 답하는 launcher로(f8e3216e의 core가 kind 9로 답함, `nInfo` + 1, `nBadMsg` 그대로, 등록 아님, launcher 항목 없음); 답 없는 길은 아무도 답하지 않는 socketpair로 옮겨 남김(200 ms 한도, 칸 magic 0); `gdakiCtrlLaAgCount` 검사 셋
- `build_gc.sh`의 `p2a2regions`: PO enum이 page 순수 영역에 있으면 자르지 않음

## 리뷰가 볼 것이라 한 것의 상태

REVIEW_P3 "2a-2와 합칠 때 볼 것" 열둘: 1 등록은 all-gather 뒤 그대로, INFO만 앞(맞음); 2 `nLaunchers`는 all-gather의 수(접착 3); 3 `OnEnvelope`는 helper의 `gdakiCtrlLauncherStep` 머리, 다른 잠금 없이, 링크의 걸음 앞(접착 2); 4 LEAVING → 증인 BYE → 링 해제(링 BYE 없음); 5 봉투 256 B, seq, ackSeq, `max_dest_rd_atomic` ≥ 1, PAIR_ACK 뒤 곧바로 CONNECTED(링크 그대로); 6 UD 받기가 launcher datagram을 넘김, gen/seq/incarnation 0인 봉투 받음; 7 `laOf`는 all-gather에서; 8 덩어리는 전용 칸(outbox 반이 아님); 9 끌어 읽기는 helper가 기록 QP로(감시 스레드의 PROBE QP가 아님), `pullOk`는 false 그대로; 10 Resume 41 들어옴(비용 셀은 아래 열린 것); 11 L 입력의 주인은 3단계 그대로, 판정에 묶는 것은 2a-2-C; 12 헤더 차례 p2b → p2a2 → p3 한 곳에서, `sites` 149행과 갈래 44개 다시 셈.
REVIEW_FIX12_P2B "2a-2와 3단계가 볼 것": 3단계 몫 2(`pg->nLaunchers`를 페이지와 링 배치 전에)와 5(launcher 페이지 READ)가 이 통합에서 닫힘; 2a-2 몫 10(REJOIN을 UD로), 12(시험 스위치 셋)는 2a-2-C.
notes_fix3 "합칠 때 볼 것": 1 fix3의 `gc_unit_p2.cc`(5612fd13)를 받음, 통과; 2 ring 모형 두 hunk는 글자로 겹치지 않음; 3 `GDAKI_CTRL_PO_*` 이동은 `p2a2regions`에서 처리, `gdakiCtrlProbeAnswer`는 링의 poll(링크 tick)에서만 불림. 링이 live일 때 seam의 보내기와 받기도 poll을 돈다: 그 부르는 쪽이 모두 helper인지는 2a-2-B의 규칙이고 이 작업은 다시 보지 않았다 `[미확인]`.

## 2a-2-C가 아직 할 것

- REJOIN을 UD로: 예비 프로세스의 보내기와 다시 보내기(`nrp`), 생존 쪽 멱등 표, REJOIN_ACK, FAIL/WAIT/REFUSE 답, `gdakiCtrlRdmaOnRejoinAccepted`, `gdakiCtrlRejoinFail`의 UD 몸통
- STATE와 rkey 목록을 2b의 outbox 전송으로(`gdakiCtrlStateRingOf`, 저장소 영역의 TODO(2a-2) 셋), DATA 채널
- 되살린 상대의 증인을 unknown으로 두고 다시 걸기
- 판정 효력: 링이 live면 증인 FIN은 창만 열고 창 판정이 반응(지금은 ln4처럼 FIN = 죽음), 10–12행의 반응과 `pullOk`(감시 스레드의 launcher PROBE QP 짝 맺기와 페이지의 등록 낱말 READ)
- 쌍마다의 전환 표지: live로 바뀌는 순간 TCP에 남은 늦은 기록과 링의 뒤 기록의 차례
- 시험 스위치 `DIE_RST`, `RST_GAP`, `FD_HOLDER`, 확정 체크포인트마다의 제어 요약

## 열린 것

- launcher QP를 향한 이 rank의 창은 launcher 봉투의 ackSeq로만 열린다. launcher 페이지의 credit 칸 READ(창이 닫힐 때)는 없다: rank가 launcher에 64개를 보내는 동안 launcher가 아무것도 보내지 않으면 대기열에 남는다(hold마다 rank가 보내는 것은 몇 개) `[추론]`
- Resume 41은 부를 때의 걸쇠로 판단한다: helper의 첫 launcher 짝 맺기가 끝나기 전의 Resume은 41(fail-fast)이 된다. 그리고 `NCCL_GIN_RESTORE=1` 비용 셀(notes_p3 답 4)은 launcher가 없으면 이제 fail-fast다. 측정 모드 예외와 Resume의 기다림을 둘지 조율 세션이 정한다
- hold 기계가 같은 고리에서 `gdakiCtrlLauncherStep`보다 먼저 `gdakiCtrlLaLost`를 보면 helper가 멈췄다 돌아온 직후 한 번은 옛 박동 시각으로 판단할 수 있다 `[추론]`
- UD QP를 다시 만들면(`gdakiCtrlRdmaUdRemake`) 링크의 `k.ud`는 옛 끝점 그대로다(rank 쌍은 다음 PAIR로 배움, launcher는 아님)
- 모든 것이 CPU 모형이다. launcher 길은 가짜 NIC(장면 7)과 launcher core의 프로세스 안 전송(`gc_unit_p3`)에서만 돌았다. 실제 verbs, launcher 프로그램과의 RNIC 길, 클러스터에서는 한 번도 돌지 않았다 `[미확인]`

## EXPERIMENT.md 11절과 12절에 넣을 줄 (안)

- 11절: `- [ ] 통합 int2(감시 스레드 고침 3 + 3단계 + 2a-2 A, B, 그리고 그 사이 접착: launcher 전송 표를 링의 launcher 기록 QP와 UD로, launcher 봉투 받기, all-gather의 launcher 칸과 모든 rank 같은 launcher 수의 페이지 배치, 덩어리 칸, launcher 페이지 박동 READ, Resume 41, rank 쪽 INFO 켬): 빌드와 CPU 시험까지 — 2026-10-17, impl/gc_layer_int.diff(ln4 대비 전체 층, md5는 아래 표). 2a-2-C(REJOIN을 UD로, STATE와 rkey의 outbox, 증인 다시 걸기, 판정 효력, 전환 표지)는 남음`
- 12절: `| 2026-10-17 | 통합 int2(실행 없음, CPU와 빌드만). 2a-2-B를 커밋하고 감시 스레드 고침 3(gc_layer_fix3.diff 2f469461)과 3단계(gc_layer_p3.diff c755b1df)를 3-way로 합침(충돌 하나: all-gather 앞 준비 블록, 링 만들기 다음 INFO). 접착 여섯: launcher 기록 QP와 UD 전송, launcher 봉투 받기, all-gather 칸(72 B)과 launcher 수로 페이지 배치(creditOff가 rxConsumedL), 덩어리 전용 REMOTE_READ 칸, helper의 launcher 페이지 박동 READ, Resume 41; launcher f8e3216e의 INFO로 rank 쪽 INFO 켬. 헤더 948b3ecf + p2b + p2a2 + p3. gc, gcp, gct, gctp 빌드됨(경고 0), tcp 전처리 gct, gctp hunk 0, gctc RST 간격 2 hunk [측정]. 단위 시험 두 빌드 통과(gc_unit_p2a2 장면 7 더함, gc_unit_p3 INFO 장면을 답하는 launcher로) [측정, n 1]. 장치 동일성은 아래 표. 실제 verbs와 클러스터 실행 없음 | impl/notes_int2.md, 스크래치 agent_gc_p2a2/logs_int2/ |`

## 검사 표 (이 작업이 돌린 것만; 로그는 스크래치 `agent_gc_p2a2/logs_int2/`, 모두 `build_gc.sh` BR=int2)

| 검사 | 결과 | 근거 |
|---|---|---|
| `api` | 붙인 블록 둘 = `rs_ctrl_api.h` 023f013d, launcher 헤더 붙임 = `launcher_msg.h` fb11b235(554줄), 헤더 단독 컴파일 rdma와 tcp, `TCP_CELLS` 단독 거절: 통과 | `api_s14.log` |
| `syn` | build, build-gcp, build-gct 통과 | `syn_s9.log` |
| `gc` / `gcp` / `gct` / `gctp` | 빌드됨, 경고 0; libnccl c4ec0803 / 2a7b8d08 / 4f4b2ec8 / e4e698c8 | `build_{gc,gcp,gct,gctp}_s11.log`, `out/*_int2/` |
| `pre` | gct 0 hunk, gctp 0 hunk, gctc 2 hunk 3줄(RST 간격), gc 100 hunk(기록용) | `pre_s11.log`, `out/pre/` |
| `sites` | 149행 모두 맞음, `#use` 넷 맞음, `#if NCCL_GIN_CTRL_TCP` 갈래 44개 모두 ln4 글, page 1 256, ring 2 742 코드 줄: 통과 | `sites_s10.log` |
| `unit` rdma | mi_unit 다섯, rs_unit_host 348 739, rs_spare_unit 171, gc_unit_prep 116 장면 366, gc_unit_p1 10 248 976, gate_fenced 10/10 64, gc_unit_p2 3 993 471, gc_unit_p2b 11 114, gc_unit_p2a2 4 452, gc_unit_p3 16 장면 473: 모두 실패 0 `[n 1]` | `unit_s13.log` |
| `unit` tcp | 옛 일곱 실패 0, gc_unit_prep 48 장면 174, p1, p2, p2b, p2a2 0 검사, p3는 rdma만: 통과 | `unit_s13.log` |
| `ident` (IDTAG int2) | 설치 헤더 ln4와 같음, 프로그램 16/16 같음, 장치 객체 넷 모두 207/207 SASS 같음(바이트 같음 207), 라이브러리 넷 자원 같음 | `ident_s12.log`, `out/ident_int2/` |
| `diff`, `info` | 위 10 | `diff_s12.log`, `info_s14.log` |

검사 수의 `gc_unit_p2a2`는 기다림 고리 때문에 실행마다 몇 개 다르다(4 436–4 452). 실제 verbs, launcher 프로그램, GPU, 클러스터에서는 돌지 않았다 `[미확인]`.

## 수와 파일 md5 (worktree `control/impl/`)

| 파일 | md5 | 줄 |
|---|---|---|
| `gc_layer_int.diff` (ln4 대비 전체 층) | `c0975edb1c06adc9fbeeb9b0908fbfe3` | 10 948 |
| `rs_ctrl_api.h` (948b3ecf + p2b + p2a2 + p3) | `023f013d2f86d7b5fd76f9c012a74c99` | 1 296 |
| `build_gc.sh` (5eaaf11e 대비 키 p2b, p2a2, fix3, p3, int2) | `fe2936d8bcc8ffc61e9b8b65d0b53163` | 947 |
| `gc_sites.tsv` (바뀜 없음) | `450fe8bd7b14e7993cf706ce88fe9ddb` | 176 |
| `gc_unit_p2a2.cc` (7a9cd690 대비) | `601e3d537b3e7e9e87403d768d798405` | 1 758 |
| `gc_unit_p3.cc` (e01665cd 대비) | `895e393386ac635347038f7280b28d6d` | 1 702 |
| 스크래치 호스트 파일 | `d68e6b5b6be0429c0618d8ea239cefc1` | 34 485 |

입력(바꾸지 않음): `launcher/launcher_msg.h` fb11b235, `launcher/gin_launcher.c` bf418a65(커밋 f8e3216e), 단계별 diff와 헤더 요청 셋, `test/*`, `EXPERIMENT.md`, `../../mirror/*`.
