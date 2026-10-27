# notes_waitpeer.md: 기다리는 rank는 원인이 풀릴 때까지 판정하지 않는다 (SPEC2, 2026-10-27, 작업 기록)

상태: **코드 수정 완료 / 로컬 단위 검증 완료 / 하드웨어 검증: pilot 5(셀 B 2/2, 기다리는 rank도 멈춤 2/2, 고리 1/1), pilot 6(두 죽음 3/3)** (채점 아님; `../results/20261027_pilot5/PILOT.md`, `../results/20261027_pilot6/PILOT.md`)

표시: `[측정]` 돌려서 봄, `[소스]` 코드를 읽음, `[추론]` 해석, `[미확인]` 확인 안 함.

명세는 조율 세션의 `scratchpad/next/counterexample/SPEC2.md`(ANALYSIS.md 3절을 review2.md로 고친 것)다. 작업 중 조율 세션의
결정(2026-10-27) 하나를 더했다: 관측한 지 STALL_MS − 2 × PROBE_MS(9 800 ms)가 안 된 어린 보기는 분할 막이의 증인이 아니다
(아래 "어린 보기"). 호스트 파일
`gin_host_gdaki.cc` 하나만 바꿨고 장치 코드는 0줄이다. 새 코드는 모두 `#if !NCCL_GIN_CTRL_TCP` 안(page 영역)이다.
`gdakiHoldTold`, `fallbackOther`, 판정 표 21행, 첫 일치 차례, 격자 1 170점은 그대로다. 클러스터 실행은 없다.

## 트리와 산출물

- 스크래치 트리 `agent_gc_p2a2/nccl-src`: 시작 HEAD `d5aec6e`, 작업 트리 깨끗함, `f53e5d2` 대비 patience diff md5
  `7a3fbd66` = 고치기 전 `gc_layer_int.diff` `[측정]`.
- 커밋: `0b622ed` "gin-control: dependent waiters are not judged while their source is unresolved"(작성자 build).

| 파일 | md5 | 줄 |
|---|---|--:|
| [gc_layer_waitpeer.diff](gc_layer_waitpeer.diff) (`d5aec6e` 대비, patience, +526 −15, hunk 18) | `0d30bee6b3d566b0d66ecf008aa83a8a` | 685 |
| [gc_layer_int.diff](gc_layer_int.diff) (`f53e5d2` 대비, patience; 앞 판 `7a3fbd66`) | `279b5c90d5bc596f5a60e0742068169b` | 14 879 |
| 호스트 파일 `gin_host_gdaki.cc` | `a4f1be412a6e1f61747e07b555a00ee6` | 38 261 |
| [gc_unit_waitpeer.cc](gc_unit_waitpeer.cc) | `4604b80354a02b13a66b2660294403d7` | 1 503 |
| [build_gc.sh](build_gc.sh) (키 `unitwaitpeer`, `unit`에 포함; 스크래치 `build_gc_int3.sh`도 같은 고침) | `02918c420dda98fcef3fe31aabaffee9` | 1 001 |
| libnccl `gc` (`out/gc_wp2`) | `54e7ddec95945a655ec87688718378f3` | |
| libnccl `gcp` (`out/gcp_wp2`) | `bbb7e334ca819797aae353e9bd083b30` | |
| libnccl `gct` (`out/gct_wp2`) | `7dbbed96e481c53cc17f8cb08a9c3502` | |

두 diff 모두 거꾸로 적용 검사 통과, 커밋 뒤 `f53e5d2` 대비 diff md5가 `279b5c90`으로 같다 `[측정]`. 라이브러리는 커밋 전 작업
트리에서 빌드했다(박힌 커밋 해시는 `d5aec6e`) `[추론]`. 결정 전 판(`out/gc_wp` 등, 로그 `*_wp.log`)은 버린 중간본이다.

## 무엇을 바꿨나

| 자리 | 무엇 |
|---|---|
| page 순수 영역 | 원소 `gdakiCtrlDevElemOf`, 원소 시계 `gdakiCtrlDevElemOnRead`(복원 commit의 (0, 0) 다시 쓰기를 문의 대상 원소에서는 남은 일로 붙잡음, 찢긴 (0, polled) READ도 진행 아님, READ 공백 200 ms 규칙 그대로), 한 rank의 줄 `gdakiCtrlStallTargets`(T(X), 원시 정체와 그 context, 가장 오랜 원점), T_z = SUSPECT_MS − 2 × PROBE_MS, 분류기 `gdakiCtrlStallRoles`(한 스냅숏, SOURCE / DEPENDENT / CYCLE), 문 `gdakiCtrlWaitGateStep`, 판정 몫 `gdakiCtrlWaitCap`(닫힌 문: STALL_MS − 1), 페이지 몫 `gdakiCtrlWaitPageGpu`(닫힌 문: 9 799 ms), helper용 역할 낱말과 `gdakiCtrlStallMailFirst`/`Keep` |
| 원소 시계 | 상대마다 devCtxN × nranks개(context 우선). 줄 READ 완료마다 갱신(`gdakiProbeDevElemRead`). context 시계는 그대로 두고 보고용(`waiting` 줄의 `ctx_stale_ms`)이다. R (2)–(5)의 GPU 정체는 이제 원소 최댓값이다 |
| 자기 줄 | helper가 PROBE_MS마다 자기 GPU의 장치 QP 배열을 NIC 복사 경로(`gdakiLbXfer`, CUDA 호출 없음, READ 아님)로 읽어 감시 스레드에 넘긴다(`gdakiCtrlSelfLineStep`/`Take`). 같은 원소 규칙으로 자기 Z를 정한다. 경로가 없으면 자기 줄은 빈 것(옛 규칙과 같음)이고 줄 하나가 그렇게 말한다 |
| 스냅숏 | 판정마다 모든 rank의 줄(유효 보기: 이름 댄 context 모두 이 세대에 읽음, 마지막 READ 3 × PROBE_MS 안, 이 화신의 페이지)과 자기 줄로 분류하고, 모든 상대의 문을 한 걸음 옮기고, 역할 낱말을 게시한다(`gdakiCtrlWaitStep`) |
| 해소 사건 | 상대 k마다 `wEv`: 지난번과 다른 화신의 줄이 이름 대어짐, 이 rank의 k hold가 끝남(held 상태를 떠남). CONNECT로 지우지 않는다 |
| 판정 | `gdakiProbeJudge`: 문이 닫혀 있으면 GPU 몫을 STALL_MS − 1로(18행까지, latch 없음). 문이 열렸거나 SOURCE/CYCLE이면 원시값으로 10 s 규칙 그대로(막이, 거부권, latch) |
| 페이지 낱말 | `staleMs[X]`의 GPU 몫 = now − 원소의 가장 오랜 원점, 문이 닫혀 있으면 9 799 ms 이하. 호스트 박동 몫은 그대로 |
| helper | 한 걸음의 stall 메일을 모두 받은 뒤, 먼저 SOURCE/CYCLE과 GPU 정체가 아닌 메일, 다음 DEPENDENT 메일을 처리 직전에 역할 낱말을 다시 읽어 문이 닫혀 있으면 버린다(줄 하나, latch를 다시 연다: 다음 READ가 다시 만든다). 하드 상한을 넘은 메일은 늘 처리한다 |
| 어린 보기(결정) | 관측자마다 상대 X의 보기 나이 = 이 짝 맺기에서 X 페이지를 처음 읽은 뒤의 시간(`viewSinceMs`, CONNECT마다 다시). 9 800 ms 미만이면 페이지 낱말 `staleMs[X]`의 bit 62를 세운다(값은 그대로; 표시 없는 낱말은 전과 같은 뜻: `gdakiCtrlStaleWordAged`, `gdakiCtrlStaleYoungOfWord`, `gdakiCtrlViewAgeOk`). 분할 막이는 어린 보기를 무효 보기처럼 건너뛴다(FRESH도 PASS도 아님; 모두 건너뛰면 지금처럼 SELF). 페이지 배치는 그대로다 |
| 다시 쓰기 붙잡음 | 문이 닫혔을 때뿐 아니라 열린 뒤에도(X가 Z를 떠나 문이 끝날 때까지) 대상 쪽 원소에 둔다. 하드 상한으로 연 뒤 commit이 오면 X가 숨던 길((라)3)을 막는다 |
| 줄 | `rank X waiting (peer=…) (stale_ms ctx ctx_stale_ms …)`, `rank X wait ended (progress… / its peers resolved, no progress within G… / the hard bound…)`, `stall verdict of rank X … dropped: it is dependent now`, `own device line read locally …` 또는 `… not read locally (…)` |
| probe summary | 끝에 `wait_n`(닫힌 문 수), `wait_ms_max`(가장 긴 기다림), `role_src_n`, `role_dep_n`, `role_cycle_n`(그 상대가 Z에 있고 보기가 유효했던 판정 수, 실효 역할별). `rows_gc.py`의 key=value 읽기에 맞는다 `[소스: rows_gc.py kvd]` |

분류기의 CYCLE: SOURCE에 닿지 않는 Z의 원소다. Z에 SOURCE가 없으면 Z 전부(SPEC2 문장)이고, SOURCE가 있어도 거기 닿지
않는 떨어진 고리는 CYCLE이다(ANALYSIS 2절 정의; SPEC2 문장은 SOURCE가 없는 경우만 말함) `[소스]`.

## review2 지적 1–9에 대한 답

| 지적 | 이 구현 |
|---|---|
| 1 자기 금지가 정상 대기자의 HOLDING을 막음 | 자기 금지 없음. 자기 Z는 자기 줄의 로컬 읽기로만 정하고 다른 rank의 분류에만 쓴다. 셀 B 모든 실행에서 rank 1이 rank 3을 판정하고 생존자 셋이 hold를 세워 복원된다(정답 주입 없음) `[측정]` |
| 2 9 999는 PASS | 닫힌 문의 페이지 GPU 몫은 9 799. 순수 검사: 9 799 FRESH, 9 800과 9 999 PASS. 장면 (나)1에서 관측자 0의 막이가 FRESH로 대기자 판정을 막는다. 호스트 몫만 큰 반대자는 PASS(한계, 낱말 하나의 범위) |
| 3 q ∉ Z의 즉시 열림과 G의 충돌 | 문은 끈적하다(닫히면 역할이 SOURCE로 보여도 닫힌 채). 대상을 이 rank가 HELD, COMMITTING, TIMED_OUT_HELD로 붙잡은 동안은 해소가 아니다. G는 모든 대상이 해소된 마지막 시각부터. 문(닫힘, 열림) 대상 원소의 (0, 0) 다시 쓰기는 진행이 아니다. 별도 `STALL:resume` 없음 |
| 4 helper 재유예와 READ 공백 | 되돌려 두기 없음(버리고 latch를 연다). 하드 상한 2 × STALL_MS는 ARMED, HELD와 무관하게 문을 열고 그 메일은 늘 처리한다. "되돌리지 않음"은 분류 때문에 되돌리지 않는다는 뜻이고 READ 공백 규칙은 그대로다 |
| 5 정보 부족, G 계약 | 장면 (바): 정상과 장애 두 뜻의 관측이 해소 전까지 같다. 주장 범위는 SPEC2의 사전 등록 문장 그대로(G는 application 계약) |
| 6 사슬과 복수 원인 | 직접 대상 T(X)를 모두 보존(닫힌 동안 늘어난 대상도), 대상마다 해소, 모두 해소된 뒤 G. 다시 쓰기 붙잡음은 직접 대상 쪽 원소만 |
| 7 상한 | SPEC2의 조건부 상한을 쓴다. 모형이 그 상한을 깨는 길 둘을 찾았다: 하나(예비 화신의 어린 보기)는 결정으로 고쳤고, 하나(문 없는 고리 원소)는 한계로 남긴다(열린 문제 1, 2) |
| 8 단위 장면 | 아래 장면 표. m2가 셀 B에서 살아남는다는 지적대로, m2와 m3은 "고리가 helper 한 걸음 안에 SOURCE로 바뀜" 장면에서 잡힌다. m8(원시)과 m9(9 999)는 둘 다 막이를 통과해 (나)1에서 잡힌다 |
| 9 ANALYSIS 1절 부호 | 코드 문제가 아니다. review2가 맞다(부호 반대; 원점은 값이 바뀐 READ). 원소 시계도 같은 규칙이다 |

## CPU 모형 `gc_unit_waitpeer.cc` (`build_gc.sh` 키 `unitwaitpeer`, `unit`에 포함, BR=int3)

page 영역과 hold 순수 영역(`gdakiHoldDeclineAction`)을 잘라 그 위에서 돈다. 모형은 rank마다 프로세스(관측자) 하나: 멈춘
rank의 프로세스(호스트는 살아 있음)와 복원된 화신도 관측자다. 상대마다 READ 위상과 자기 줄 읽기 위상을 0–100 ms에서
뽑는다. 다른 관측자의 페이지 낱말은 읽는 순간 그 관측자의 상태로 계산한다. helper는 메일을 0.2–1.5 ms 뒤 한 걸음에
모아 처리하고 decline 하나에 1.8–3.7 ms가 걸린다. hold 쪽은 `gdakiHoldDeclineAction`과 TOLD(degraded 예약, 비동기 오류),
NOHOLD와 FALLBACK 전파, 모든 생존자 HOLDING → FENCE → FENCED → 예비 화신 → 생존자마다 commit(그 rank의 q쪽 QP가
(0, 0)) → PUBLISHED → 다시 짝 맺기 → hold 끝, 첫 HOLDING부터 20 s 기한이다. 멈춤 차는 0–300 ms다.

장면 결과(m0, 구현한 규칙; 셀 B 1 000번씩, 나머지 200번씩) `[측정: logs_p2a2/unit_wp3.log]`:

| 장면 | 실행 | 실패 |
|---|--:|--:|
| B1 waiter leads | 1000 | 0 |
| B2 source ahead | 1000 | 0 |
| B3 waiter > source | 1000 | 0 |
| stuck waiter (spare's page unread) | 200 | 0 |
| stuck waiter (spare's view counted) | 200 | 0 |
| (사) cycle 1<->3 of four | 200 | 0 |
| (사) cycle of a two-rank communicator | 200 | 0 |
| chain 0->1->2 | 200 | 0 |
| (마) middle only | 200 | 0 |
| (마) end waiter only | 200 | 0 |
| (마) two sources | 200 | 0 |
| (마) cycle with a branch to a source | 200 | 0 |
| (라)1 q moves every 2.5 s | 200 | 0 |
| (라)2 20 s, q armed, no hold | 200 | 0 |
| (라)3 HELD just before | 200 | 0 |
| (라)4 one observer's READ gaps | 200 | 0 |
| (라)4 every observer's READ gaps | 200 | 0 |
| (나)1 valid opponent | 200 | 0 |
| (나)2 invalid opponent (residual) | 200 | 0 |
| (바) one trace, two meanings | 200 | 0 |
| race: a cycle turns into a source in one helper step | 1 | 0 |
| (다) restore phase, 5 events in every order | 960 | 0 |

- 장면마다 확인하는 것(요약): 셀 B 셋(대기자 위상 앞섬, 원인 한 주기 앞섬, 번호 바꿈): 원인을 생존자 셋 모두 9 990–10 400 ms에
  판정, hold 셋, 복원, 대기자 판정 0, degraded 예약 0, hold 아닌 decline 0, 기다림 문 둘 이상. 대기자도 멈춤: 복원 뒤
  restoredAt + G 와 + G + 700 ms 사이에 판정(예비 화신의 페이지를 읽든 안 읽든). 고리: 원인 쪽 9 990–10 400 ms, 둘째는 같은
  창이거나 복원이 먼저(아래 잔여). 사슬과 (마): 원인만 판정, 대기자 0, 복원; 두 원인(예비 없음): 둘 다 판정, 대기자는 하드
  상한 d + 19 990–20 500 ms이고 그 문은 두 대상을 모두 쥠. (라)1–3: 대기자가 하드 상한 창에서 판정, (라)2는 q 판정 0과 hold 0,
  (라)3은 hold가 먼저 서고 생존자 둘의 문이 하드 상한으로 열림. (라)4 둘: 판정 없음(기록). (나)1: 관측자 0이 대기자를 판정하지
  않음; (나)2: 눈먼 관측자 둘이 대기자를 판정, rank 3은 않음(잔여, 기록). (바): 10 s 전까지 두 뜻의 판정 기록이 같고, 그 뒤
  정상은 판정 0, 멈춤은 판정. 경쟁: 관측자 0의 rank 1 메일이 10 050 ms에 만들어지고 버려짐, 복원, degraded 0. (다): 다섯 사건
  120 차례 × 정상/멈춤 × 뽑기 4, q를 붙잡은 동안 문 열림 0, 정상 판정 0, 멈춤은 hold 끝 + G 뒤 한 주기 안.
- `residuals (recorded, not failures): the cycle's second member not judged because the restore came first: two-rank communicator 70 of 200 (its observer fenced), four ranks 16 of 200 (its own commit rewrote its QP to (0, 0) before its mark: hidden, a limitation); (라)3 the waiter judged in 200 of 200`
- `ring allreduce shape (failure 1, report only): 8 runs, every rank judged in 7, restored in 1 (every rank is a CYCLE: judged at STALL_MS, fallback)`
- 합계 `gc_unit_waitpeer (rdma): 29056 checks, 0 failed`(rdma), tcp 0 검사.

순수 검사: 원소 시계(다시 쓰기 붙잡음, 찢긴 READ, 공백 규칙, 첫 post), T_z 1 800, 분류기(셀 B, 고리, 사슬, 가지 있는 고리,
떨어진 고리, 자기 QP, 링), 문(끈적함, 붙잡힌 대상, G, 하드 상한, 대상 둘), 판정 몫 9 999와 페이지 몫 9 799, 어린 보기 표시(값
그대로, 옛 낱말 그대로, 나이 9 800 ms), 메일 순서와 재분류.

변이(각각 장면 묶음을 다시 돌림, 셀 B 20번, 나머지 4번씩) `[측정]`:

| 변이 | 깨진 장면 실행 | 어디서 |
|---|--:|---|
| m1 옛 규칙(context 합, 분류 없음, 원시 낱말, helper rank 순) | 108 | B1 waiter leads 20/20; B2 source ahead 20/20; B3 waiter > source 20/20; stuck waiter (spare's page unread) 4/4; stuck waiter (spare's view counted) 4/4; chain 0->1->2 4/4; (마) middle only 3/4; (마) two sources 4/4; (마) cycle with a branch to a source 4/4; (라)1 q moves every 2.5 s 4/4; (라)2 20 s, q armed, no hold 4/4; (라)3 HELD just before 4/4; (나)1 valid opponent 4/4; (나)2 invalid opponent (residual) 4/4; (바) one trace, two meanings 4/4; race: a cycle turns into a source in one helper step 1/1 |
| m2 helper rank 순, 버림 없음 | 1 | race: a cycle turns into a source in one helper step 1/1 |
| m3 판정한 상대의 역할과 문만(스냅숏 없음) | 1 | race: a cycle turns into a source in one helper step 1/1 |
| m4 다시 쓰기를 조용함으로(다시 움직임 확인 끔) | 496 | stuck waiter (spare's page unread) 4/4; stuck waiter (spare's view counted) 4/4; (라)3 HELD just before 4/4; (바) one trace, two meanings 4/4; (다) restore phase, 5 events in every order 480/960 |
| m5 멈춘 상대면 면제(CYCLE 없음) | 9 | (사) cycle 1<->3 of four 4/4; (사) cycle of a two-rank communicator 4/4; race: a cycle turns into a source in one helper step 1/1 |
| m6 한 단계만 | 4 | chain 0->1->2 1/4; (마) cycle with a branch to a source 3/4 |
| m7 대상이 Z를 나가면 X 시계를 되돌림 | 13 | stuck waiter (spare's page unread) 4/4; stuck waiter (spare's view counted) 4/4; (라)1 q moves every 2.5 s 4/4; (바) one trace, two meanings 1/4 |
| m8 페이지 낱말 원시 | 4 | (나)1 valid opponent 4/4 |
| m9 페이지 낱말 9 999 | 4 | (나)1 valid opponent 4/4 |
| m10 하드 상한 끔 | 16 | (마) two sources 4/4; (라)1 q moves every 2.5 s 4/4; (라)2 20 s, q armed, no hold 4/4; (라)3 HELD just before 4/4 |
| m11 어린 보기도 증인 | 4 | stuck waiter (spare's view counted) 4/4 |

`mutations caught: 11 of 11` `[측정]`. m2와 m3은 경쟁 장면 하나로만 잡힌다(review2 8의 예상대로 셀 B에서는 막이와 끈적한 문이 가린다).

## 열린 문제

1. **복원된 화신의 어린 보기(결정으로 고침)** `[측정: 모형]`. 예비 화신은 X의 줄을 복원 뒤 처음 읽고, commit이 X의 q쪽
   원소를 (0, 0)으로 만들었으므로 그 화신에게 X는 조용하다. 고치기 전 모형에서는 그 작은 낱말이 모든 생존 rank의 막이에서
   FRESH가 되어, 정말 멈춘 대기자가 GPU 행으로 판정되지 않았다(40번 중 0번). 결정대로 어린 보기를 증인에서 빼니 해소 + G
   뒤 700 ms 안에 판정된다("stuck waiter (spare's view counted)", 변이 m11이 이것을 깬다). (라)3도 하드 상한 판정이 모든
   실행에서 난다(열린 문의 다시 쓰기 붙잡음과 함께). 남은 것: 9 800 ms보다 어린 보기만 있는 관측자 집합에서는 막이가 SELF라
   판정이 늦어진다(셋업 직후, 모두 다시 짝 맺은 직후) `[추론]`.
2. **문 없는 고리 원소의 다시 쓰기(한계, 바꾸지 않음)** `[측정: 모형]`. 다시 쓰기 붙잡음은 문이 있는 X의 대상 원소에만 있다.
   네 rank의 1↔3 고리에서 둘째 원소의 10 s 전에 복원 commit이 오면 그 QP가 (0, 0)이 되어 조용해지고, 그 rank는 숨는다
   (1 000번 장면 기준 아래 잔여 수). 결정대로 기록만 한다.
3. 자기 줄 로컬 읽기는 helper와 NIC 복사 경로에 기댄다. 경로가 꺼졌거나 그 범위가 등록되지 않았거나 helper가 300 ms
   넘게 바쁘면 자기 줄이 비어 옛 규칙처럼 된다. 장치에서 돈 적 없다 `[미확인]`.
4. R (2)–(5)가 원소 시계라서, 같은 context의 다른 QP는 진행하는데 한 QP만 남은 일을 둔 채 그대로인 경우도 이제 GPU 멈춤이다
   (review2 8의 "원소 시계의 새 검출 범위"). 정상 workload에서 이런 QP가 있는지 `[미확인]`.
5. 한 관측자의 READ 공백 반복은 그 관측자의 시계를 계속 되돌려 그 작은 낱말(짝 맺기는 오래되어 어린 보기 표시 없음)이 다른 관측자의 막이에서 FRESH가 되므로 모든 판정을 막는다((라)4, 기존 공백 규칙과 막이의 결과, 기록만).
6. 보기 갈림(두 관측자가 q를 못 봄)은 대기자 판정과 fallback이다((나)2, 잔여로 기록).
7. 링 allreduce 모양(실패 1)은 모든 rank가 CYCLE이라 STALL_MS에 판정되고 fallback이다(보고만).
8. 비용: 상대마다 원소 시계 devCtxN × nranks개, 판정마다 스냅숏 하나. 4 rank에서는 작고, 112 rank에서는 재지 않았다 `[미확인]`.

## 검사 (`agent_gc_p2a2/chain_wp2.sh` → `wp2.sh`, 머리 이름 `d5aec6e`의 제목; 로그 `logs_p2a2/*_wp2.log`, `unit_wp3.log`)

| 단계 | 결과 `[측정]` |
|---|---|
| `syn`, `api` | 통과 |
| 빌드 `gc`, `gcp`, `gct` | 빌드됨, 경고 0(`gctp`는 빌드하지 않음, pf2와 같음) |
| `pre` | `gct` 0 hunk, `gctp` 0 hunk, `gctc` 2 hunk 3줄(전과 같음), `gc` 114 hunk(기록용). tcp 전처리 바뀜 없음 |
| `sites` | 149행, 트리 밖 `#if NCCL_GIN_CTRL_TCP` 갈래 49개가 ln4 줄 그대로 |
| `unit` | rdma, tcp 모두 실패 0, "0 failed" 줄 36개(pf2의 34 + `gc_unit_waitpeer` 두 빌드). `gc_unit_livectx` 1 078 020, `gc_unit_live` 293 382, `gc_unit_p1` 10 376 867(격자 1 170점 포함) 검사, 전과 같은 수 |
| `ident` | 설치 헤더 ln4와 같음, 매크로 없는 프로그램 16/16 SASS와 자원 같음, 장치 객체 207 × 4 바이트 같음, 라이브러리 자원 같음 |

첫 `unit`(`unit_wp.log`)은 고리 장면 하나의 기대(복원 뒤 둘째 판정을 실패로 셈)가 틀려 2번 실패했고, 둘째(`unit_wp2.log`)는
tcp 빌드에서 쓰지 않는 변수 경고로 컴파일이 멈췄다. 둘 다 시험 파일만 고쳤다.

실제 RNIC, launcher, 두 노드에서는 돌리지 않았다 `[미확인]`. pilot 5 셀 B에서 볼 것: `waiting (peer=3)`과 `wait ended
(progress…)`, rank 1 판정 0, `own device line read locally`, probe summary의 `wait_n`.
