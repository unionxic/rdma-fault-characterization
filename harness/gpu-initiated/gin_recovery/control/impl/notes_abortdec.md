# notes_abortdec.md: 확정된 중단 결정이 상대와 나중 화신에게 간다 (SPEC3 ①을 review3 1–6으로 고친 것, 2026-10-28, 작업 기록)

상태: **코드 수정 완료 / 로컬 단위 검증 완료 / 하드웨어 pilot 7 통과**(2026-10-28, 받아들임 2/2, 대조 7/7; [../results/20261028_pilot7/PILOT.md](../results/20261028_pilot7/PILOT.md), 커밋 `d6f4cfa4`). 열린 문제 1은 닫혔고 2는 장치에서 한 번 보였다(아래).

표시: `[측정]` 돌려서 봄, `[소스]` 코드를 읽음, `[추론]` 해석, `[미확인]` 확인 안 함.

명세는 조율 세션의 `scratchpad/next/counterexample/SPEC3.md` ①절이고, `review3.md` 지적 1–6을 고칠 것으로 묶어 따랐다(아래 "review3 답").
호스트 파일 `gin_host_gdaki.cc` 하나만 바꿨고 장치 코드, driver는 0줄이다. 새 코드는 모두 `#if !NCCL_GIN_CTRL_TCP` 안이고, 고친 hk/restore
함수(`gdakiUaRaisePeer`, `gdakiTsDecline`, `gdakiHoldWatchdog`)는 `#if NCCL_GIN_CTRL_TCP` 갈래에 ln4 줄을 그대로 두었다. `gdakiHoldTold`,
`fallbackOther`(`gdakiHoldDeclineAction`), 판정 표, 장치 코드, tcp 전처리는 그대로다. 헤더 `rs_ctrl_api.h`도 그대로다(아래 "SPEC3과 다른 점" 1).
클러스터 실행은 없다.

## 트리와 산출물

- 스크래치 트리 `agent_gc_p2a2/nccl-src`: 시작 HEAD `0b622ed`, 작업 트리 깨끗함, `f53e5d2` 대비 patience diff md5 `279b5c90` = 고치기 전
  `gc_layer_int.diff` `[측정]`.
- 커밋: `05f5a97` "gin-control: confirmed abort decisions reach peers and later incarnations"(작성자 build).

| 파일 | md5 | 줄 |
|---|---|--:|
| [gc_layer_abortdec.diff](gc_layer_abortdec.diff) (`0b622ed` 대비, patience, +799 −8, hunk 24) | `87edebb14c344068a7e99e546ad5f12f` | 1 002 |
| [gc_layer_int.diff](gc_layer_int.diff) (`f53e5d2` 대비, patience; 앞 판 `279b5c90`) | `3ae8f572e991c32f60878cb740ef5e3e` | 15 745 |
| 호스트 파일 `gin_host_gdaki.cc` | `5f03db2ce947e9fbe2045fb6774f1618` | 39 052 |
| [gc_unit_abortdec.cc](gc_unit_abortdec.cc) | `729005da06ffe5087f4ef397539295e2` | 1 013 |
| [build_gc.sh](build_gc.sh) (키 `unitabortdec`, `unit`에 포함; 스크래치 `build_gc_int3.sh`도 같은 고침) | `a925784e1d62d5db6ed17e9013b3c701` | 1 113 |
| [gc_sites.tsv](gc_sites.tsv) (`#use page` 세 줄 더함) | `1f863729894b5e437c923e2dea52ca7f` | |
| libnccl `gc` (`out/gc_ad`) | `ed13666bacdf07dcc2e16ef4028561e3` | |
| libnccl `gcp` (`out/gcp_ad`) | `55ffb80e1ac74e58b05666fbd08176e8` | |
| libnccl `gct` (`out/gct_ad`) | `df1d091bb8ba6ec391604e4933c9c56d` | |

두 diff 모두 거꾸로 적용 검사 통과, 커밋 뒤 `f53e5d2` 대비 diff md5 `3ae8f572`, `0b622ed`..HEAD diff md5 `87edebb1`로 파일과 같다 `[측정]`. 라이브러리는 커밋 전 작업 트리에서 빌드했다(박힌 커밋 해시는 `0b622ed`) `[추론]`.

## 무엇을 바꿨나

| 자리 | 무엇 |
|---|---|
| 결정의 정의 | 이 rank가 스스로 낸 communicator 낱말의 상태 전이: 첫 PEER_DEAD로 `deadMs`와 degraded 해제가 정해짐(degraded 1, 2), 또는 gated 상대 모두의 낱말이 올라 낱말 [0]이 바로 오름(every). `gdakiUaRaisePeer`가 그 전이를 `struct gdakiUaTrans`로 돌려준다(종류, 해제 시각) |
| 기록장 | rank마다 덧붙이기만 하는 목록(`gdakiAdState`, r마다 하나, 레지스트리). 항목: commHash, 세대, 대상 rank와 화신, 정한 rank와 화신, 번호(정한 rank마다 1부터), 원인, 정한 rank의 해제 시각(그 시계), 이 rank 시계의 해제 시각, 받은 곳, 상태(OWN, PENDING, DEFERRED, APPLIED, LATE, STALE, SELF). 키 (정한 rank, 화신, 번호) |
| 기록 지점 둘 | `gdakiTsDecline` 끝(helper, 정책 훅이 hold로 가져가지 않은 decline이 전이를 냈을 때)과 `gdakiHoldWatchdog`(watcher의 HELD → TIMED_OUT_HELD, 원인 DEADLINE). watcher는 적기만 한다 |
| 원인 | 1 STALL, 2 STALL_HELPER, 3 FIN 계열(EXITED, FIN+STALE, FIN+NORESP, REMACC+FIN, FIN, 거절된 연결), 4 NORESP, 5 FALLBACK, 6 every, 7 그 밖, 8 DEADLINE(watcher). decline의 `lostCause`와 사유 글에서 읽는다 |
| 기록 57 `ABORT_DECIDED` | `from`, `nonce`(`gdakiHoldSend`), `arg` 대상, `round` 대상 화신, `nqp` 번호, `pad` 원인, `executed[0..2]` 정한 rank, 그 화신, 전달자 자신의 화신, `t[0]` 남은 ms(−1 없음), `t[1]` commHash, `t[2]` 세대(비트 그대로), `t[3]` 정한 rank의 해제 시각 |
| 보내기(helper만) | 상대 q가 이 rank에서 LIVE이고 record channel이 올라 있을 때만. 대상 자신과 정한 rank의 그 화신에게는 보내지 않는다. q의 보내기 키 = (q의 화신, record channel의 세대). 첫 키는 그때까지의 기록장을 q도 아는 것으로 친다. 키가 바뀌면(새 화신과 짝 맺음, QP 재생성으로 큐가 버려짐) 아직 열린 항목(해제 시각이 지나지 않음)을 모두 다시 보낸다. 자기 항목은 만든 키에서 한 번, 받은 항목은 나중 키에서만 간다(다시 퍼뜨리지 않음). 결정 순간 helper가 round 밖이면 바로, 아니면 다음 걸음에 |
| 남은 시간 | 받는 쪽은 도착 시각 + 남은 ms를 자기 시계의 해제 시각으로 적고, 다시 보낼 때는 그 남은 몫을 싣는다 |
| activation blob | buddy가 UD 표 뒤에 "GAAD"(머리 16 B, 항목 64 B, 최대 256, launcher의 64 KiB 안)로 열린 항목을 붙인다(활성화되는 rank가 대상인 것은 뺌). 예비는 UD 표 머리의 count로 길이를 끊고(`gdakiCtrlActUdLenOf`) 나머지를 저장만 한다(PENDING) |
| 받기 | `gdakiCtrlOnRecord`에 갈래 하나(`gdakiAdOnRecord`). hold drain과 `gdakiHoldOnMsg`의 거르기에 `gdakiAdIsRecord`(57)를 더했다. 규칙 `gdakiAdRxAction`: 다른 commHash나 세대 버림, 키 중복 셈, 전달자(`from`)가 이 rank 계보에서 그 화신의 CURRENT가 아니면 버림, 대상이 자기 자신이면 줄만, 계보 보기가 아직 완성되지 않았으면 저장, 이 rank가 대상을 이미 decline했거나 그 화신에 대한 결정을 이미 적용했으면 늦음(효과 없음), 대상 계보가 CURRENT면 적용, HELD_OLD면 미룸, STALE·FUTURE면 버림. 정한 rank의 계보는 보지 않는다 |
| 계보 완성 | 생존 rank: 처음부터. 예비: blob에 항목이 있으면 그때부터 미완성, `gdakiRsSpareRun`이 모든 REJOIN_ACK 뒤(`gdakiRsSpareRejoinAll` 성공 뒤) 완성으로 바꾸고, helper의 첫 걸음이 저장된 항목을 검사한다. application 스레드는 기다리지 않는다 |
| 다시 검사 | helper 걸음마다 PENDING, DEFERRED 항목을 같은 규칙으로 다시 본다(중복 검사 없이). HELD_OLD는 hold가 끝날 때까지 그대로이고, 복원으로 끝나면 STALE(버림, 새 화신은 건드리지 않음), fallback으로 끝나면 이 rank의 decline 뒤라 늦음 |
| 적용 | `gdakiAdApply` → `gdakiTsDecline`(정책 훅 꺼짐: `gdakiAdApplyAt`이 서 있는 동안). FAIL 안 보냄. decline의 끝 효과 그대로: scope 전체, prepared면 `ncclGinRecoverAbort`, `deadJudged`·`failedPending` 지움, `nDeclined`, 비동기 오류, gate epoch과 HOST_FAILED, 쓰기 실패면 `failPending`. 훅이 먼저 하던 `gdakiCkptPauseGatesEnded`(입력 정지 길이의 끝)는 적용 함수가 부른다. 상대의 낱말 PEER_DEAD, degraded 해제는 min(도착 + 남은 ms, 이미 예약된 것), 지났으면 바로. hold와 펜스는 시작하지 않는다 |
| commHash, 세대 | commHash는 `ncclGinGdakiRestoreResume` 들어올 때(facts의 commHash, 예비의 activation보다 먼저), 세대는 setup all-gather의 rank 0 salt(예비도 transcript의 salt를 쓴다: review3 2의 확인) |
| 줄 | `confirmed abort decision no. N (incarnation I): rank T (incarnation J), cause C, waits that name no peer released in L ms (...)`, `ABORT_DECIDED(...) of rank D (incarnation I) sent to rank q` / `sent again to rank q`, `rank q's record channel is live again (...): k open abort decision(s) owed to it`, `ABORT_DECIDED(...) from rank S via record 57 / the activation blob: <결과>`, 적용이면 `applied, waits released in L ms (no hold, no fence)`, blob 줄 둘, 계보 완성 줄, 받은 해제의 `communicator degraded in L ms: a confirmed abort decision about rank T (its release kept)` |
| probe summary | 상대마다 끝에 `ad_tx ad_rx_applied ad_rx_dup ad_rx_stale ad_rx_other ad_rx_late ad_rx_deferred ad_resend`. rx는 그 상대에게서 온 것(blob은 buddy 몫), deferred는 도착 때 저장·미룸, 그 결과는 다시 검사 때 한 번 더 센다. stale에는 전달자 stale, 대상 stale, 자기 자신 대상이 들어간다 |

## review3 지적 1–6에 대한 답

| 지적 | 이 구현 |
|---|---|
| 1 watchdog 경로와 전송 스레드 | 전이는 `gdakiUaRaisePeer`가 알려 주고 두 호출자(decline, watcher)가 적는다. watcher는 적기만 하고 보내기는 helper다. `degMs >= 0`, `why == 0`, `degradedAtMs == 0`, `deadMs == 0` 조건과 every는 그 함수의 실제 조건 그대로다. 장면: watcher가 먼저 옮기고 helper가 뒤따름(결정 하나, watcher 직후 큐 비어 있음), DEGRADED_MS 0/−1, every, 같은 호출 둘 |
| 2 계보 완성과 지연 적용 재검사 | 예비의 blob 항목은 REJOIN_ACK 뒤에만 검사한다. 미룬 항목은 적용 직전 같은 규칙으로 다시 본다. HELD_OLD = 이 rank가 그 화신을 hold 중: 끝날 때까지 미룸. 전달자는 기록 57의 `executed[2]`를 `from`의 계보로 검사하고(nonce는 communicator 공통값이라 쓰지 않음), 정한 rank는 역사적 화신 그대로 받는다 |
| 3 링 소유권, 끝점, 세대 변경 | 재생 프로토콜, 끝 표시, application 스레드의 링 돌리기는 없다. 받기와 적용은 helper가 한다. `gdakiHoldSend` 성공이 큐 적재일 뿐인 문제는 키에 record channel 세대를 넣어, QP 재생성 뒤 열린 항목을 다시 보내는 것으로 덮는다. 예비의 TOKEN, DONE_RS 수신 경로에는 끼지 않는다: 생존 rank는 그 상대의 계보가 LIVE(RESTORED 뒤, DONE_RS 뒤)일 때만 보낸다 `[소스: gdakiHoldCommitRound가 DONE_RS를 보낸 뒤 PUBLISHED, RESTORED가 LIVE로]` |
| 4 terminal 정리 | 기존 decline 함수를 정책 훅만 끄고 부른다. 단위 장면이 실제 함수로 좁은 scope, prepared, gate 쓰기 실패, COMMITTING/PUBLISHED/HELD(미룸, 아무것도 안 건드림), 다른 상대의 hold(상태 그대로)를 본다. 새 hold와 펜스 0은 확인했고, 이미 진행 중인 다른 hold가 TOLD 규칙으로 나중에 fallback할 수 있다는 것은 기존 규칙의 결과로 남긴다(장면이 TOLD 조건이 선 것까지만 확인) |
| 5 어린 보기 조건 | 없앴다. 자기 판정이 없으면 바로 적용, 있으면 늦음. 그래서 생존 rank의 결과도 바뀔 수 있다(장면 A8: 96 ms 뒤 자기 판정을 하는 생존 rank는 남의 결정으로 먼저 풀리고 자기 판정은 아무 결정도 만들지 않음). "생존 rank 불변"은 주장하지 않는다 |
| 6 남은 시간, dup/late | 항목마다 이 rank 시계의 해제 시각을 두고 보낼 때마다 남은 몫을 싣는다(중계마다 지연은 전송 시간만 더해짐). 같은 키는 dup, 같은 대상의 다른 정한 rank 결정은 late로 따로 센다. 받아들임의 "둘째 정한 rank의 것은 dup"은 late로 읽어야 한다 |

## SPEC3과 다른 점 (결정 필요한 것 포함)

1. 기록 57은 헤더(`rs_ctrl_api.h`)의 `gdakiCtrlIsRecord`, 이름표에 넣지 않고 선언 영역의 `GDAKI_TS_CTRL_ABORT_DECIDED`, `gdakiAdIsRecord`로 두 호출 자리에서
   받는다(헤더와 repaste를 건드리지 않으려고). 헤더에 넣을지 결정이 필요하다.
2. 끝 표시와 500 ms 재생 대기(SPEC3 (b)(2), (3))는 review3 3대로 없다. 결정이 activation 전이면 blob, 뒤면 LIVE 때 재전송이다.
3. 받은 결정은 다시 퍼뜨리지 않지만, 나중 키(새 화신, QP 재생성)에는 전달한다(review3의 "현재 전달자가 과거 결정을 재생").
4. DEGRADED_MS가 음수면 PEER_DEAD 전이가 없어(기존 조건) 결정도 없다. 받는 쪽 DEGRADED_MS가 음수면 decline만 하고 낱말 [0]은 올리지 않는다.
5. 원인 8 DEADLINE을 더했다(watcher의 경로).
6. every의 결정은 남은 시간 0이고, 그 rank의 gated 상대가 모두 decline된 상태라 보낼 곳이 사실상 없다 `[추론]`.

## CPU 모형 `gc_unit_abortdec.cc` (`build_gc.sh` 키 `unitabortdec`, `unit`에 포함, BR=int3)

호스트 파일에서 그대로 잘라 쓴다(`gc_ad_cut_a.inc`, `gc_ad_decl.inc`, `gc_ad_cut_u.inc`, `gc_ad_cut_b.inc`): 세 abort decisions 영역, `gdakiTsDecline`,
`gdakiUaRaisePeer`(rdma 정의), `gdakiUaDegradedStep`, `ncclGinTsUserAbortRaise`, `gdakiHoldWatchdog`, `gdakiTsToComm`, `gdakiRecForPeer`, UD 표 조각,
`struct gdakiTsMsg`, `struct gdakiTsPeer`. 모형이 만드는 것: 네 rank의 프로세스(가짜 QP, gate, hold 칸, 아는 화신, 진짜 레지스트리의 user devComm 낱말),
현재 프로세스 사이 record channel(지연 0.05–3 ms, CONNECTED 전 붙잡힌 큐, 큐를 버리는 QP 재생성), hold의 decline 훅 개요(ARMED이고 아직 알린 것이 없으면
hold 시작), rank의 복원(펜스, buddy의 blob이 있는 activation, activation 표와 REJOIN_ACK, RESTORED), watcher, 장치의 이름 없는 대기(낱말 [0], 60 s
watchdog). 0.25 ms 걸음.

장면(m0) `[측정: logs_p2a2/unit_ad.log]`:

| 장면 | 실행 | 실패 | 확인 |
|---|--:|--:|---|
| A1 기다리는 rank도 멈춤(pilot 5 모양) | 40 | 0 | 복원된 rank 3이 r0 해제 시각 + 한 전송 안에 풀림(watchdog 아님), r2도, r0의 결정 하나(STALL), r2·예비의 자기 결정 0, 적용에서 훅 0, hold 0, FAIL 0, 예비가 rank 1의 두 context QP를 ERR |
| A2 낡은 화신의 결정 | 1 | 0 | rank 3 화신 1(자기 자신)과 rank 3을 복원한 생존 rank가 (3, 0)을 버림 |
| A3 중복, 둘째 정한 rank | 1 | 0 | 적용 한 번, dup 1, late 1, 해제 시각 그대로 |
| A4 풀린 뒤 늦은 결정 | 1 | 0 | 낱말, 예약 그대로, 줄 하나 |
| A5a activation 전 결정(표가 필요) | 20 | 0 | rank 1이 전에 복원돼 (1, 1)인 결정, 예비의 transcript는 rank 1을 0으로 앎: blob에 저장, REJOIN_ACK 뒤 적용, 해제는 정한 rank의 시각 |
| A5b blob 뒤, REJOIN_ACK 전 결정 | 20 | 0 | LIVE 때 재전송으로 적용 |
| A5c REJOIN_ACK와 RESTORED 사이 결정 | 20 | 0 | 같음 |
| A6 다른 communicator, 세대 | 1 | 0 | 둘 다 버림 |
| A7 두 대상, 번호 거꾸로 | 1 | 0 | 둘 다 적용, 해제는 이른 쪽 |
| A8 96 ms 뒤의 자기 판정 | 10 | 0 | 바로 적용, 해제는 정한 rank의 시각, 자기 판정은 결정을 만들지 않음 |
| A9 받는 쪽에서 대상 ARMED | 5 | 0 | hold 시작 0, 훅 0 |
| watcher 먼저, helper 뒤 | 5 | 0 | 결정 하나(DEADLINE), watcher 직후 큐 비어 있음, helper가 보냄, hold 중인 rank는 미뤘다가 자기 기한에 늦음 |
| DEGRADED_MS 0, −1, every, 같은 호출 | 3 | 0 | 0: 남은 0, 받는 쪽 바로; −1: 결정 0; every: 결정 하나, 보낸 것 0; 같은 raise 둘·decline 둘·둘째 죽음: 결정 하나 |
| 받음 → 대상 REJOIN → 다시 검사 | 5 | 0 | HELD_OLD로 미룸, REJOIN 뒤에도 미룸, 복원 뒤 STALE, 새 화신 QP 그대로 |
| 역사적 정한 rank | 10 | 0 | rank 0 화신 0이 정하고 rank 0이 화신 1로 복원된 뒤, rank 3의 예비가 buddy의 blob으로 받아 적용, rank 0의 새 화신도 전임자의 결정을 받음 |
| 큐 적재 뒤 QP 재생성 | 10 | 0 | 다시 보냄 1, 받는 쪽 해제는 정한 rank의 시각 |
| 두 중계, 남은 시간 | 20 | 0 | 결정 500 ms 뒤 rank 3 복원(중계 1), 그 뒤 rank 2 복원(buddy가 rank 3의 예비: 중계 2), 모두 정한 rank의 시각 + 전송들 안 |
| 실제 decline의 끝 효과 | 1 | 0 | 좁은 scope에서도 두 context, prepared abort, deadJudged·failedPending 지움, gate 쓰기 실패면 failPending, epoch, 비동기 오류, FAIL 0, 다른 상대의 COMMITTING hold 그대로(TOLD 조건은 섬); COMMITTING·PUBLISHED·HELD 대상은 미룸(아무것도 안 건드림) |

순수 검사: 원인, 기록 57과 blob 양방향(남은 시간, 손상), UD 표 길이, 받기 규칙, 키, 보내기 규칙. 합계 `gc_unit_abortdec (rdma): 1 307 checks, 0 failed`, tcp 0 검사.

변이(잘라 온 코드의 글자를 바꿔 다시 빌드, 모든 장면을 돌림) `[측정]`:

| 변이 | 바꾼 것 | 깨져야 할 장면(깨진 실행) |
|---|---|---|
| m1 처리 끔(watchdog 길) | `gdakiAdOnRecord`가 바로 돌아감 | A1 (40/40, 예비가 watchdog까지) |
| m2 계보 완성 전 적용 | PEND 규칙과 완성 조건 제거 | A5a (20/20) |
| m3 다시 검사 없음 | 다시 볼 때 대상을 CURRENT로 | 받음 → REJOIN → 다시 검사 (5/5) |
| m4 LIVE 때 재전송 없음 | `gdakiAdTxWhat`의 재전송 끔 | 큐 적재 뒤 재생성, A5b (10/10, 20/20) |
| m5 중복 검사 끔 | 키 검사 제거 | A3 (1/1) |
| m6 communicator 검사 끔 | OTHER 규칙 제거 | A6 (1/1) |
| m7 남은 시간 무시 | 도착 + DEGRADED_MS | 두 중계 (20/20) |
| m8 적용에 정책 훅 | 훅 조건에서 `adAt == nullptr` 제거 | A9 (5/5) |
| m9 watcher 전이 안 적음 | watchdog의 기록 호출 제거 | watcher 먼저 (5/5) |

`mutations caught: 9 of 9` `[측정]`.

## 검사 (`agent_gc_p2a2/ad.sh`, 머리 이름 `0b622ed`의 제목; 로그 `logs_p2a2/*_ad.log`)

| 단계 | 결과 `[측정]` |
|---|---|
| `syn` | 통과(build, build-gcp, build-gct) |
| 빌드 `gc`, `gcp`, `gct` | 빌드됨, 경고 0(`gctp`는 빌드하지 않음, 앞 판과 같음) |
| `pre` | `gct` 0 hunk, `gctp` 0 hunk, `gctc` 2 hunk 3줄(전과 같음), `gc` 122 hunk(기록용, 앞 판 114). tcp 전처리 바뀜 없음 |
| `sites` | 통과. `#use page` 세 줄(gdakiCtrlChanGen 2, gdakiCtrlChanUp 1, gdakiHoldSend 1)을 표에 더함. 트리 밖 `#if NCCL_GIN_CTRL_TCP` 갈래 53개(앞 판 49)가 ln4 줄 그대로 |
| `unit` | rdma, tcp 모두 실패 0, "checks, 0 failed" 줄 38개(앞 판 36 + `gc_unit_abortdec` 두 빌드). `gc_unit_p1` 10 376 867(격자 1 170점 포함), `gc_unit_livectx` 1 078 020, `gc_unit_live` 293 382, `gc_unit_waitpeer` 29 056, `gc_unit_abortdec` 1 307 검사, 앞의 넷은 전과 같은 수. 변이 9 of 9 |
| `ident` | 설치 헤더 ln4와 같음, 매크로 없는 프로그램 16/16 SASS와 자원 같음, 장치 객체 207 × 4 바이트 같음, 라이브러리 자원 같음(`gc_ad`, `gct_ad`, `gcp_ad`; `gctp`는 빌드하지 않아 없음) |

첫 `unitabortdec`(`unitad_1.log` 앞부분)은 모형의 가짜 함수가 잘라 온 UA 조각보다 먼저 와서 컴파일되지 않았다. 잘라 온 것을 둘로 나눴다(`gc_ad_cut_u.inc`). 시험과
빌드 스크립트만 고쳤다.

## 열린 문제

1. **하드웨어 확인** — 2026-10-28 pilot 7로 닫힘 `[측정: results/20261028_pilot7/PILOT.md]`. 기다리는 rank도 멈춤 셀 2/2: 복원된 rank 3 `exit=4 xchg=released`, watchdog 없음,
   `released=1`이 생존 rank보다 1.2–2.6 ms 먼저, `ABORT_DECIDED(rank 1, incarnation 0, no. 1, cause STALL) … applied`, 예비의 `ad_rx_applied` 1; 복원만 있는 일곱 시행(두 죽음 포함)의 `ad_*` 모두 0.
   걸리지 않은 길 `[미확인]`: 다시 보냄(`sent again`), activation blob의 "GAAD", 계보 완성 뒤 적용(결정이 모두 복원 뒤에 났음).
2. **생존 rank 결과가 바뀐다** — pilot 7 n1에서 한 번 보임 `[측정]`: r2가 rank 1을 스스로 판정하기 전에 r0의 결정을 적용해(r0 결정 12 345.4 ms, r2 적용 12 348.3 ms) decline 사유가
   `ABORT_DECIDED(...)`가 되고 `waiter_judge_n` 1(pilot 5 n1은 2). n2는 둘 다 스스로 정했고 늦게 온 것은 "late"로 셌다. 거절 셀(`spare_absent_refused`, `fdhold_uverbs_refuse`,
   `stall_none_refuse`)의 자기 판정 수에 미치는지는 pilot 8(거절 셀 셋 n 1씩)에서 본다(EXPERIMENT.md 11.1). 채점기는 고치지 않았다.
   2026-11-18: pilot 8 펜스 끈 멈춤 셀에서도 한 번 보였고(`n_judge` 2/3), 사용자 결정 (가)로 채점기에 열 `n_judge_taken`을 더해 `fdhold_uverbs_refuse`가
   남의 결정을 적용한 생존 rank를 판정을 마친 것으로 센다(EXPERIMENT.md 12절 그날 "채점기 고침 둘(검수 뒤)" 행). 라이브러리는 그대로다.
3. **진행 중인 다른 hold** `[추론]`. 적용이 상대의 낱말과 degraded 예약, 비동기 오류를 올리므로 이 rank가 다른 상대를 hold 중이면 다음 걸음의 TOLD
   규칙(`gdakiHoldTold`)이 그 hold를 fallback한다. 기존 규칙이고 바꾸지 않았다. 모형은 TOLD 조건이 서는 것까지만 본다.
4. **모형의 hold는 개요다**. A5a, 두 중계 장면은 결정이 난 뒤에도 다른 rank의 복원이 끝난다고 놓았다. 실제로는 3번의 TOLD 규칙으로 그 복원이 먼저
   fallback할 수 있다 `[추론]`. 장면이 보는 것은 결정의 전달 장치(blob, 저장, 계보 완성 뒤 적용, 남은 시간)다.
5. 해제 시각이 지난 항목은 다시 보내지 않는다. 남은 시간 0인 결정(DEGRADED_MS 0, every)의 첫 보내기가 QP 재생성에 잃으면 그 상대는 받지 못한다 `[추론]`.
6. commHash는 Resume 때 정해진다. Resume 전에 난 결정은 commHash 0을 실어 받는 쪽에서 다른 communicator로 버려진다 `[추론]`. 이 셀들은 Resume 뒤에만
   판정한다.
7. hold 상태가 없는 프로세스(복원을 요청하지 않음)는 57을 hold drain으로 받지 않는다(STALLED와 같음). 보내는 쪽은 보낸다 `[소스]`.
8. 실제 링에서 57이 TOKEN·DONE_RS 수신 경로에 끼지 않는다는 것은 "LIVE일 때만 보냄"과 쌍마다의 순서에 기댄다. 클러스터에서 확인할 것 `[미확인]`.
9. **낡은 전달자의 사본이 키를 차지한다** `[소스: gc_layer_abortdec.diff gdakiAdCheck, gdakiAdRxAction]`. 전달자가 이 rank 계보에서 그 화신의 CURRENT가 아닌
   기록 57(FWD_STALE)도 상태 STALE로 기록장에 들어가고, 도착 때의 중복 검사(`gdakiAdSameKey`)는 상태를 가리지 않으므로, 같은 키(정한 rank, 화신, 번호)를
   CURRENT 전달자가 나중에 보내면 중복으로 버려진다. probe summary도 FWD_STALE을 `ad_rx_stale`에 섞어 센다. 2026-11-18 채점기 검수의 지적 3이고,
   사전 등록 전에는 고치지 않고 후속으로 미룬다(EXPERIMENT.md 18절 (사), 12절 2026-11-18 행). 하드웨어에서 걸린 적은 없다 `[미확인]`.
