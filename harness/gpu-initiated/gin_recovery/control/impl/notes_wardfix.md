# gin-control wardfix: 활성화 전에 저장소 ward QP의 ERR 확인 (작업 기록, 2026-10-23)

상태: **코드 수정 완료 / 로컬 단위 검증 완료 / 하드웨어 검증 대기**.

트리는 세션 스크래치 `agent_gc_p2a2/nccl-src`이고 제자리에서 했다. 호스트 파일 `gin_host_gdaki.cc` 하나, 장치 코드 0줄.
클러스터, ssh, GPU 실행은 없다. 빌드(gc, 컴파일만)와 CPU 단위 시험만 했다. worktree에는 commit하지 않았다.
표시: `[측정]` 돌려서 봄, `[소스]` 코드를 읽어 확인, `[추론]` 해석, `[미확인]` 확인 안 함.

## 무엇이 문제였나 (Codex 리뷰 2026-10-23, diff를 읽어 확인)

- hold 시작의 `gdakiCtrlPeerToErr` → `gdakiStoreWardToErr` → `gdakiCtrlStoreWardToErrAsk`는 store thread에
  `GDAKI_CTRL_STORE_JOB_WARD_ERR` 일을 줄 끝에 넣고 돌아온다. QP를 실제로 ERR로 옮기는 것은 나중의
  `gdakiCtrlStoreWardErrRun`이고, modify가 실패하면 줄 하나와 `q->err = true`뿐이었다 `[소스]`.
- HOLDING 투표도, 활성화 gate(`gdakiCtrlActFenceOk`, FENCED만 봄)도 ward QP가 ERR에 닿았는지 보지 않았다 `[소스]`.
- 그래서 dead rank의 buddy에서 후속 incarnation의 ACTIVATE와 FETCH가 나가는 동안, 옛 incarnation의 늦은 upload
  WRITE가 아직 이 rank의 저장소에 닿을 수 있었다 `[추론]`.

## 바꾼 것 (모두 `#if !NCCL_GIN_CTRL_TCP` 안; tcp 빌드는 그대로)

| 자리 | 무엇 |
|---|---|
| 저장소 선언 블록(ctrl seams 블록 밖) | `gdakiCtrlStoreWardGateOf`, `gdakiCtrlActWardJoin` 선언 두 줄 |
| `struct gdakiStoreState`의 기존 `#if` 블록 | `wardErr`(ward마다 NONE, ASKED, DONE, FAILED), `wardErrAskMs`(마지막으로 물은 때). 둘 다 `st->mu` 아래 |
| 순수 영역 "gin-control (store): pure" | 상태 enum `GDAKI_CTRL_WERR_*`, 기다림 한도 `GDAKI_CTRL_WARD_ERR_WAIT_MS`(2000 ms), 일의 판정 `gdakiCtrlStoreWardErrOutcome`(QP 없음 또는 modify 성공: DONE, 실패: FAILED), 줄 위치 `gdakiCtrlStoreWardErrPos`, gate의 ward 부분 `gdakiCtrlStoreWardGate`, FENCED와 합치는 `gdakiCtrlActWardJoin` |
| `gdakiCtrlStoreWardErrQueueLocked`(새) | 일을 줄에 넣고 상태를 ASKED, 물은 때를 지금으로 |
| `gdakiCtrlStoreWardToErrAsk` | 위 함수를 부름(전에는 `push_back`) |
| `gdakiCtrlStoreWardErrRun` | QP가 없으면 DONE. 있으면 이미 ERR이어도 modify를 다시 함(verbs는 어느 상태에서나 ERR로 옮길 수 있다 `[추론]`, 전에는 `q->err`면 건너뜀). 판정을 `wardErr`에 씀. 단, 같은 ward의 WARD_ERR 일이 줄에 더 있으면 그 일의 판정을 기다림 |
| `gdakiCtrlStoreWardGateOf`(새) | buddy가 아니거나 store 상태가 없으면 go. 한 번도 묻지 않았으면(NONE) 지금 묻는다. teardown 중이면 fall back. 나머지는 `gdakiCtrlStoreWardGate` |
| `gdakiCtrlActFenceOk` | FENCED 판정 뒤에 ward 부분을 합친다. fall back이면 WARN `GIN/CTRL: rank %d: store ward QP of rank %d not in ERR: %s; the activation of incarnation %u falls back`, 그리고 `gdakiHoldFallback`(FENCE_NAK와 같은 길). FENCED인데 ward를 기다리면 (peer, dead)마다 한 번 NOTE |

- 기다림은 새 스레드나 새 고리가 아니다. gate는 원래대로 helper step마다 다시 불리고(false: 다음 step에 다시), 그
  바깥 한도는 hold의 restore deadline(`NCCL_GIN_RESTORE_MS`, 기본 20000 ms)이다 `[소스]`. FENCED 기다림에는 따로 정한
  시간 한도가 없어서, 원인을 적은 WARN으로 끝내기 위해 ward 기다림에만 2000 ms 한도를 더했다(물은 때부터) `[소스]`.
  2000 ms라는 값은 정한 것이고 잰 값이 아니다 `[미확인]`.
- buddy가 아닌 rank는 `gdakiCtrlStoreWardErrDue`가 false라 gate가 바로 go다(바뀜 없음) `[소스]`.

## 일의 순서 (요청 4)

- store thread의 줄은 `std::vector` 하나이고 앞에서 꺼낸다. 이 thread가 하는 일은 SERVE(ward의 STORE_REQ: MR 등록과
  QP 만들기), FREE(MR 해제), WARD_ERR 셋뿐이다. upload WRITE 자체는 이 thread가 아니라 uploader 쪽이 낸다 `[소스]`.
- WARD_ERR 일은 이제 줄 끝이 아니라 **같은 ward의 마지막 SERVE 바로 뒤, 없으면 맨 앞**에 들어간다. 같은 ward의 SERVE는
  새 QP를 만들 수 있으므로 그 앞으로 가지 않는다(가면 새 QP가 ERR 밖에 남는다). 바꾼 줄은 `insert` 한 줄이다 `[소스]`.
- 남는 지연: 지금 돌고 있는 일 하나(다른 ward의 SERVE면 MR 등록 하나, FREE면 해제 하나)는 끝까지 간다. 그 시간은
  재지 않았다 `[미확인]`. 그 일이 2000 ms를 넘으면 hold는 원인을 적고 fall back한다.
- hold 시작 뒤에 dead incarnation의 새 STORE_REQ는 `gdakiStoreDropNow`가 버리므로(ward가 held) 그 뒤로 SERVE가 끼어들지
  않는다 `[소스]`.

## 단위 시험 `gc_unit_ward.cc` (`build_gc.sh` 키 `unitward`, `unit`에도 포함, BR=int3)

순수 영역(gc_store_pure.inc)을 잘라 쓰고, store thread는 한 번에 일 하나를 돌리는(잡아 둘 수 있는) 줄, ward QP는
가짜(있음, ERR, 섬기는 incarnation; modify를 실패시킬 수 있음)다. 검사하는 것:

1. 규칙: 판정 표, ward gate(상태 4개 × 시각 6개, 한도 경계), FENCED와의 합침.
2. 줄 위치: 무작위 줄 2000개. 같은 ward의 SERVE 앞으로 가지 않고, 마지막 그 SERVE 바로 뒤 또는 맨 앞.
3. 장면: hold 시작의 일을 잡아 둔 채 HOLDING 모두와 FENCED를 준다. 잡혀 있는 동안 gate는 지나가지 않고, 그 사이 옛
   incarnation의 늦은 WRITE는 아직 닿는다(gate가 막는 창). 일을 돌리면 먼저 넣어 둔 다른 ward의 SERVE와 FREE보다 먼저
   돌고, QP가 ERR이 되고, gate가 지나가고, 늦은 WRITE는 닿지 않는다.
4. modify 실패: FAILED, gate는 fall back(FENCED여도). 한도를 넘게 잡아 둠: fall back.
5. hold 전에 들어온 같은 ward의 SERVE 뒤에 ERR이 가서 그 SERVE가 만든 QP를 ERR로. 두 번 물음(첫 일의 판정은 둘째를
   기다림). 묻지 않음(gate가 물음). QP 없음(DONE). buddy 아님(바로 go). teardown(fall back).
6. 무작위 3000회: gate가 go일 때 ward QP는 없거나 ERR이고, go 뒤에 늦은 WRITE는 닿지 않는다.

변이 시험: 합침을 `fenceGo ? 1 : 0`(ward 무시, 고치기 전과 같음)로 바꾼 잘린 영역으로 돌리면 192 907 검사 중 8 678개가
실패했다 `[측정]`. 시험이 이 결함을 잡는다는 뜻이다.

## 결과

| 항목 | 값 |
|---|---|
| `gc_layer_int.diff` (ln4 commit 대비, patience; histogram도 같음) | md5 `9c16b732`, 13 830줄 `[측정]` (전 `5ed121f4`, 13 706줄) |
| `gc_layer_wardfix.diff` (전 트리 상태, 곧 ln4 대비 `5ed121f4`인 작업 트리 대비) | md5 `e5d1f442`, 228줄, hunk 8, 더하기 141, 빼기 17, 장치 코드 0줄 `[측정]`; 역적용 검사 통과 |
| 호스트 파일 | md5 `079cce5f`, 37 226줄 (전 `384f16fc`) `[측정]` |
| libnccl gc (`build_gc.sh gc`, 키 출력 `gc_wf`) | md5 `cca75dbb`, 빌드 경고 0 `[측정: logs_p2a2/build_gc_wf.log]` |
| `syn` (build, build-gcp, build-gct의 -fsyntax-only) | 셋 모두 통과, 경고 0 `[측정: logs_p2a2/syn_wf.log]` |
| `gc_unit_ward` | rdma 165 735 검사 0 실패, tcp 0 검사(영역 없음) `[측정: logs_p2a2/unitward_wf2.log]` |
| `unit` 전체(rdma, tcp) | rc 0, 모든 시험 0 실패. rdma: mi_unit 다섯, rs_unit_host, rs_spare_unit, gc_unit_prep, gc_unit_p1 (10 376 867), gate_fenced (10/10), gc_unit_p2, gc_unit_p2b (11 114), gc_unit_p2a2, gc_unit_p3, gc_unit_live, gc_unit_snap (453 402), gc_unit_ward (165 735). tcp: 같은 목록, gc 시험은 영역이 없어 0 검사(gate_fenced, p3는 rdma만) `[측정: logs_p2a2/unit_wf.log]` |
| 스크래치 트리 commit | `2040fe5` "gin-control: ward QP ERR confirmed before activation" (ln4 대비 diff `9c16b732`, 작업 트리 깨끗) |
| `gc_unit_ward.cc` | md5 `4ea99fbb`, 433줄 |
| `build_gc.sh` | md5 `750525f9`, 982줄 (키 `unitward`, `unitwardone`, `unit`과 `info`에 추가; diff 20줄) |

빌드와 시험은 스크래치 `agent_gc_p2a2/chain_wf.sh`(chain_s7.sh와 같은 head, 출력 `*_wf`)로 돌렸다. 스크래치
`build_gc_int3.sh`에도 같은 고침을 넣었다(worktree `build_gc.sh`와의 차이는 전과 같은 두 곳).

## 하지 않은 것

- gcp, gct, gctp 빌드, `pre`, `sites`, `ident`는 돌리지 않았다(요청 범위 밖) `[미확인]`.
- 하드웨어 검증: 늦은 WRITE가 실제로 닿는 창, ERR 일의 지연, modify 실패의 경로는 클러스터에서 보지 않았다 `[미확인]`.
- HOLDING 투표에는 손대지 않았다(gate만 막음).
