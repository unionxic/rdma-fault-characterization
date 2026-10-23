# notes_pilot2fix.md: pilot 2의 두 죽음 복원과 창 기준 시점 고침 (2026-10-24)

표시: `[측정]` 원자료나 출력에서 다시 셈, `[소스]` 코드를 읽음, `[추론]` 해석, `[미확인]` 확인 안 함.

상태: **코드 수정 완료 / 로컬 검증 완료 / 하드웨어 검증 대기**

대상은 [../results/20261023_pilot2/PILOT.md](../results/20261023_pilot2/PILOT.md)의 문제 3(두 죽음)과 문제 1(freeze 셀의 창 검사)이다. 호스트 파일 하나만 바꿨고 장치 코드는 0줄이다.

## 트리와 산출물

- 스크래치 트리 `agent_gc_p2a2/nccl-src`: 시작 HEAD `e791639`, 작업 트리 깨끗함, `f53e5d2` 대비 patience diff md5 `393ed485` = 고치기 전 [gc_layer_int.diff](gc_layer_int.diff) `[측정]`.
- 커밋 `d5aec6e` "gin-control: pilot 2 fixes: two-death REJOIN (activation table UD, both incarnations' generation), window baseline at the fence"(작성자 build).

| 파일 | md5 | 줄 |
|---|---|--:|
| [gc_layer_pilot2fix.diff](gc_layer_pilot2fix.diff) (`e791639` 대비, patience, +211 −17) | `30a643fedc4c50059f65d8ff9fd0c553` | 416 |
| [gc_layer_int.diff](gc_layer_int.diff) (`f53e5d2` 대비, patience; 앞 판 `393ed485`) | `7a3fbd6672d0de1b69df16f7e20c3fe2` | 14 368 |
| [gc_unit_p2a2.cc](gc_unit_p2a2.cc) (앞 판 `3be4096a`, 3 132줄) | `68f0ac4110dcf09bf01b7a3d11c2ee23` | 3 288 |
| [gc_unit_p3.cc](gc_unit_p3.cc) | `ecd5bbc8b489d587b76f4370f8d00f01` | 1 773 |
| libnccl `gc` (`out/gc_pf2`) | `39024befe7760f00f6a8bf761f28cc5a` | |
| libnccl `gcp` (`out/gcp_pf2`) | `1b2f741a2f8f548297d953c0d42b790d` | |
| libnccl `gct` (`out/gct_pf2`, 이번에 쓰는 셀 없음) | `54f680e226e9a557533215e1599ab0c3` | |

두 diff 모두 거꾸로 적용 검사 통과 `[측정]`. 라이브러리는 커밋 전 작업 트리에서 빌드했으므로 박힌 커밋 해시는 `e791639`이다 `[추론]`.

## 고침 1: 두 죽음의 둘째 REJOIN

### 원인

셀 `mi4_kill2_kill3_ow`(a4), `mi4_train_kill2_kill3`(a6)는 rank 2를 먼저, rank 3을 다음에 죽인다. 원인은 둘이고, 둘째는 첫째에 가려 pilot에서는 드러나지 않았다.

1. **둘째 예비 프로세스가 되살린 rank 2를 옛 UD QP로 부른다** `[측정 + 소스]`.
   - rank 2의 UD QPN은 첫 화신이 1 358(a4 `r2.log`), 되살린 화신이 1 417(a4 `spare.log` `control setup ... ud_qpn=1417`)이다. a6은 2 719와 2 777이다.
   - 예비 프로세스의 링은 준비 all-gather의 transcript 칸에서 상대 UD를 받는다(`gdakiCtrlRingAgree`, 고친 뒤 25597행). 둘째 예비 프로세스(rank 3 화신 1)는 처음부터 떠 있었으므로 그 칸은 rank 2 화신 0의 1 358이다.
   - 활성화 표(`gdakiMiActAddr`, `gdakiMiApplyAddrTable`)는 TCP listen 주소만 싣는다. 그래서 `spare_2nd.log` 143행 "rank 2 (incarnation 1) is reached at the activation table's address"는 TCP 주소만 바꿨다.
   - UD REJOIN은 죽은 QP로 갔고 응답이 없었다. a4는 resent 줄 150개, a6은 149개다 `[측정: grep -c]`. 되살린 rank 2의 로그에는 그 뒤 REJOIN을 받은 줄(`answered a REJOIN`, `taken over UD`)이 없다.
   - rank 0과 1은 rank 2의 새 UD를 받았다(그 REJOIN의 nrp, `gdakiCtrlRjIntake`의 `gdakiCtrlRdmaSetUd`). 그래서 둘째 예비 프로세스만 몰랐다.
2. **UD가 닿아도 세대 검사가 거절한다** `[소스 + 단위 시험]`.
   - 되살린 rank 2의 rank 3 쌍은 자기 REJOIN의 세대 (1 << 20) + 1 = 1 048 577이다(a4 `spare.log` 183행 "REJOIN_ACK of rank 3 taken over UD (try 1): record QP gen 1048577", 그 뒤 "liveness READ QP to rank 3 re-paired (gen 1048577)").
   - 둘째 예비 프로세스의 REJOIN도 `gdakiCtrlRjGenOf(1)` = 1 048 577이다. `gdakiCtrlRjAcceptStep`(고친 뒤 26522행)은 `n.gen <= recTop`이면 "the REJOIN's generations ... are not above the pair's"로 REFUSE를 낸다.
   - 원래 화신(rank 0, 1)은 그 쌍이 세대 1이라 거절하지 않는다. 두 화신 모두 1인 쌍에서만 충돌한다.
- 요청에 적힌 "되살린 rank의 REJOIN 표가 초기화되지 않음"은 아니었다. rank 2 화신 1의 표(`gdakiCtrlRejoinHold`, `gdakiCtrlRjOnHoldStart`)는 hold 시작에서 보통대로 섰다 `[소스]`.

### 고침 (최소, rdma 갈래만)

- **활성화 표의 UD 꼬리.** 짝(buddy)의 `gdakiCtrlLaHostBlob`이 gin-mirror blob 뒤에 꼬리를 붙인다.
  - 꼬리는 `gdakiCtrlActUdHdr`(8 B, magic "GAUD", count)와 `gdakiCtrlActUd`(rank, 표의 화신, UD endpoint; 48 B)다. 순수 영역 "setup, pure"의 `gdakiCtrlActUdPut`/`Get`이 만들고 읽는다.
  - 항목은 화신이 0보다 큰 생존 rank만이다. 그 UD는 짝의 링이 쥔 것(그 REJOIN의 nrp에서 온 것)이고, 짝 자신이면 `udLocal`이다(`gdakiCtrlActUdOf`).
  - 예비 프로세스의 `gdakiCtrlLaSpareBlobRecv`가 `gdakiMiActRecv` 뒤 socketpair의 나머지(EOF까지)를 읽어 링에 둔다(`actHave`, `actInc`, `actUd`). 꼬리가 없으면 항목 없음, 망가졌으면 REFUSED 13이다.
  - launcher는 blob을 그대로 나른다. 4 rank에서 56 B가 늘고 `GL_U_MAX_PAYLOAD` 65 536 안이다 `[소스: gin_launcher.c 1189]`. launcher 바이너리는 바꾸지 않았다.
- **REJOIN 직전 적용(`gdakiCtrlRjActApply`, `gdakiCtrlRjSpareBegin` 첫머리).** 되살린 생존 rank는 표의 UD로 바꾸고 줄 하나를 낸다: `rank %d (incarnation %u) is reached over UD at the activation table's endpoint (UD QPN %u; the transcript's %u)`. 항목이 없으면 UD를 버리고 TCP REJOIN으로 간다(WARN 한 줄; 이 길은 하드웨어에서 돌린 적 없음 `[미확인]`).
- **세대.** 예비 프로세스의 쌍 세대를 `gdakiCtrlRjGenOf(inc + 표의 그 생존 rank 화신)`으로 한다.
  - 쌍의 REJOIN마다 두 화신의 합이 오르므로 앞선 모든 세대보다 크다. 화신 0인 상대에게는 (inc << 20) + 1로 전과 같다.
  - 다를 때 줄 하나: `the REJOIN to rank %d (incarnation %u, restored before) starts gen %u`. 기존 요약 줄 "REJOIN over UD to … (… gen %u)"는 화신 0 상대의 세대 그대로다.
  - STATE 차례의 합의 세대(`gdakiCtrlStateWayOf`)는 예비 쪽이 `GenOf(inc + peerInc)`, 생존 쪽이 받아들인 REJOIN의 세대(`rj.takenInc/takenGen`, `gdakiCtrlRjAccepted`에서 적음)다.

### 단위 장면 (`gc_unit_p2a2.cc` 10c, `testRejoinTwoDeaths`)

순서는 다음과 같다.
1. 4 rank. rank 3이 죽고 예비 프로세스(화신 1)가 rank 0–2에 REJOIN해 live가 된다.
2. rank 2가 죽고 생존 rank는 0, 1과 되살린 3이다.
3. rank 2의 예비 프로세스는 첫 화신들의 준비 기록을 transcript로 받는다.

- 표 없이(옛 길): rank 3으로 가는 REJOIN이 옛 UD QPN으로 가 버려진다(intake 0, 가짜 NIC UD dropped 1). rank 0, 1은 세대 1 048 577로 받아들인다.
- 표와 함께: 짝(되살린 rank 3, 자기 UD)과 rank 0의 표 항목이 같다. 꼬리를 만들고 읽는다(빈 꼬리, 잘림, 같은 rank 둘, magic, 범위 밖은 거절).
  - 적용 뒤 rank 3 쪽 UD가 새 QPN이 되고 세대 2 097 153(rank 0, 1 쪽은 1 048 577)이다.
  - 되살린 rank 3이 park, TAKE, REJOIN_ACK를 하고, 예비 프로세스가 설치하고 live가 된다.
  - 두 쪽 STATE 차례가 UP이다.
- 출력 `[측정: logs_p2a2/unitp2a2_pf2b.log]`: "transcript only … UD QPN 425 (first incarnation's 425, restored 438), gen 1048577: no answer (intake 0, UD dropped 1)", "with the activation table … UD QPN 462 (first incarnation's 449, restored 462), gen 2097153: taken (intake 1, UD dropped 0)".
- **변이 검사** `[측정]`:
  - M1은 `gdakiCtrlRjActApply` 부르기를 뺀 것이다(옛 UD). 3 실패이고 "no answer (intake 0, UD dropped 1)"다(`logs_p2a2/unitp2a2_pf2_mutM1.log`).
  - M2는 세대를 옛 `GenOf(inc)`로 둔 것이다. 3 실패이고 "gen 1048577: no answer (intake 1, UD dropped 0)", 즉 받았으나 거절이다(`unitp2a2_pf2_mutM2.log`).
  - 두 원인 모두 따로 장면을 깬다. 변이 뒤 호스트 파일은 원래 md5로 되돌렸다.

## 고침 2: 창 검사의 기준 시점

### 원인

- freeze 두 셀의 창 줄은 `changed=` 2, 2, 2칸(`gc4_freeze12000_fence`, r0 2330행, r1 2327행, r2 2335행)과 1, 1, 1칸(`gc4_helper_freeze12000`)이다 `[측정: a1/raw grep]`.
- **충돌 기록.** PILOT.md 문제 1과 a1 표는 앞 셀을 "2, 1, 2"로 적었으나 원자료는 2, 2, 2다. 원자료를 따른다.
- 기준은 판정 때의 사본(`gdakiCtrlLaOnJudgement`)이고 견줌은 FENCED 순간이었다(`gdakiCtrlLaWindowLine`, 옛 28983행). freeze에서는 옛 화신이 펜스(SIGKILL)까지 살아 있으므로 그 사이 쓰기가 셈에 든다 `[추론]`. 그 쓰기가 옛 화신의 것인지 다른 생존 rank의 것인지는 가르지 못했다 `[미확인]`.

### 고침 (launcher link 영역과 호스트 고리 하나, rdma만)

- 낱말이 서는 때(FENCED 또는 EXITED: 옛 프로세스가 없음) `gdakiCtrlLaFenceReport`가 줄 대신 기준 사본을 찍는다(`gdakiCtrlLaFenceBase`, `snapF`, hold마다 한 번).
- 견줄 나중 사본은 둘 가운데 먼저 오는 쪽이다.
  - 이 rank가 새 화신의 REJOIN을 받아들일 때, REJOIN_ACK 전(`gdakiRsRejoinAccept`에서 lineage와 view 검사 뒤 `gdakiCtrlOnRejoinTaken` → `gdakiCtrlLaOnRejoinTaken`, `sample=rejoin`). 새 화신은 그 전에 이 rank에 쓸 수 없다 `[추론]`.
  - hold의 끝, 곧 FALLBACK이나 CANCELLED(`gdakiCtrlLaOnHoldEnd`, `sample=hold_end`).
- 낱말 없이 끝난 hold는 전처럼 판정 사본과 견준다(`base=judgement`).
- 줄 꼴: `GIN/RC: rank %d: window check after the fence|judgement of rank %d: changed=%u cells against=snapshot_at_fence|snapshot_at_judgement base=fenced|judgement sample=rejoin|hold_end unreadable=%u`.
  - `changed=`와 `unreadable=`는 그대로다. `rows_gc.py`의 `WINCHG`는 나머지를 key=value로 읽으므로 `base`, `sample`도 그 표에 들어간다 `[소스: rows_gc.py 259, kvd]`. 이것을 쓰는 채점 쪽 바꿈은 하지 않았다.
- 펜스 낱말 없이 복원이 끝난 생존 rank는 전처럼 줄이 없다.
- 줄 시각이 FENCED에서 REJOIN 받아들임으로 옮겨 간다(pilot 1–2 kill 셀 기준 FENCED 뒤 수 ms–수십 ms `[추론]`).

### 단위 장면 (`gc_unit_p3.cc`)

- 새 `sceneFenceFrozen`의 흐름: 판정 사본 → 살아 있는 자식이 창 전체를 씀(얼어붙은 페이지의 옛 화신) → FENCE → launcher SIGKILL → FENCED.
  - 판정 사본 대비로는 16칸이 바뀐다(옛 줄이 냈을 값).
  - 기준은 FENCED 때 찍히고 줄은 아직 없다.
  - REJOIN 사본은 `changed=0 … base=fenced sample=rejoin`이고 한 번만 나온다.
  - 둘째 hold에서는 기준 뒤 이 rank의 창이 바뀌면 hold 끝 줄이 `changed=16 … base=fenced sample=hold_end`다.
- 기존 장면 셋의 기대를 새 꼴로 바꿨다. kill(EXITED)은 `after the judgement … base=fenced sample=rejoin`이고, 앞선 화신 번호의 REJOIN은 줄을 내지 않는다. SIGSTOP 펜스는 `after the fence … base=fenced sample=rejoin`이다. 낱말 없는 늦은 쓰기는 `base=judgement sample=hold_end changed=16 unreadable=16`이다.
- `logs_p2a2/unitp3_pf2a.log`: 17 장면, 503 검사, 실패 0 `[측정]`.
- **변이 M3**(기준을 판정 사본으로 되돌림)은 4 실패다(`unitp3_pf2_mutM3.log`) `[측정]`.

## 검사 (`agent_gc_p2a2/chain_pf2.sh` → `pf2.sh`, 머리 이름 `e791639`의 제목; 로그 `logs_p2a2/*_pf2.log`)

| 단계 | 결과 `[측정]` |
|---|---|
| `syn`, `api` | 통과 |
| 빌드 `gc`, `gcp`, `gct` | 빌드됨, 경고 0. `gctp`는 빌드하지 않음(쓰는 셀 없음, sf1과 같음) |
| `pre` | `gct` 0 hunk, `gctp` 0 hunk(정규화 md5 ln4와 같음), `gctc` 2 hunk 3줄(전과 같음). tcp 전처리 바뀜 없음 |
| `sites` | 149행, 트리 밖 `#if NCCL_GIN_CTRL_TCP` 갈래 49개가 ln4 줄 그대로 |
| `unit` | rdma, tcp 모두 실패 0. "0 failed" 줄 34개로 sf1과 같음. `gc_unit_p2a2` rdma 5 907, `gc_unit_p3` 503, `gc_unit_p1` 10 376 867, `gc_unit_live` 293 382 검사 |
| `ident` | 매크로 없는 프로그램 16/16 SASS와 자원 ln4와 같음. 장치 객체 207 × 4 바이트 같음. 자원 사용 같음, 설치 헤더 ln4와 같음 |

- 실제 RNIC, launcher, 두 노드에서는 돌리지 않았다 `[미확인]`. 확인할 셀은 두 죽음 셀 둘(둘째 REJOIN의 표 줄과 세대 2 097 153 줄, rank 3 화신 1의 REJOIN_ACK)과 freeze 셀 둘(`base=fenced sample=rejoin changed=0`)이다.
- `rows_gc.py`의 `la_qp_err_n`이 KILL2_RANK를 빼지 않는 것(PILOT 문제 4)은 이 고침의 범위 밖이다.
