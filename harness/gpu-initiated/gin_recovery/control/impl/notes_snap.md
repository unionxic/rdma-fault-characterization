# gin-control: mirror 끈 체크포인트 멈춤 줄이기 (GPU 안 사본, 장치 헤더 변경 없음; 작업 기록)

2026-10-22. 사용자 선택(같은 날): mirror 끈 rank의 체크포인트 멈춤 안에서는 장치 안 사본(D2D)만 찍고, 호스트로 옮기기(D2H)와 저장소 WRITE는 멈춤 뒤에 한다.
2c 설계 안(`notes_p2c.md`, 내용 검사 커널)의 "장치 코드 없는 대안"을 고른 것이다. 장치 코드 0줄, 호스트 파일 하나만 바꿨다.
표시: [소스] 코드를 읽어 확인, [측정] 이 작업이 돌려서 본 것, [추론] 해석이나 셈, [미확인] 확인 안 함.
클러스터, ssh, GPU 실행은 없다. 빌드와 CPU 단위 시험만 했다. `git add`, commit, push는 하지 않았다.

## 바탕과 트리

- 트리: 스크래치 `agent_gc_snap/nccl-src`. `agent_gc_p2a2/nccl-src`를 복사하고 45274b6("gin-control int2 (gc_layer_int.diff c0975edb)")을 꺼냄.
  ln4 커밋 대비 diff md5가 `c0975edb`임을 setup이 확인했다 `[측정: logs_snap/setup.log]`.
- 빌드 디렉터리 넷: worktree `build_gc.sh`의 `setup` 방식 그대로 ln4(`agent_mi_fix`)의 build, build-mip를 복사하고 경로를 고쳐 씀.
  스크립트는 스크래치 `agent_gc_snap/build_gc_snap.sh`(키 `snap`; worktree `build_gc.sh` 대비 diff `logs_snap/build_script.diff` 121줄).
- 입력 고정: 이 작업 중 다른 에이전트가 worktree의 `gc_unit_p2a2.cc`, `gc_sites.tsv`를 바꿨다(2a-2-C). 그래서 `rs_ctrl_api.h`, `gc_sites.tsv`,
  `gc_unit_prep.cc`, `launcher/`, 단계 시험 소스를 커밋 adf88953(`gc_layer_int.diff` c0975edb가 들어간 커밋)의 것으로 `agent_gc_snap/pin/`에 고정했다(GCPIN, GCTEST).
  바뀐 worktree 시험으로 돌린 첫 `unit`은 `gc_unit_p2a2.cc`가 이 트리에 없는 형을 불러 컴파일되지 않았다(`logs_snap/unit_1.log`; 이 작업의 결함이 아님).
- 줄 번호: 아래 "트리 N행"은 작업 트리의 호스트 파일(34 663줄, md5 `358ce06c`), "45274b6 N행"은 바탕 커밋의 것이다.
  `notes_p2c.md`의 18894–18896, 18967, 17416행은 e3faf02 기준이고, 45274b6에서는 19202–19204행(멈춤 안 D2H), 19275행(칸 WRITE), 17712행(`recvSlot`)이다 `[소스]`.

## 바뀐 것 (호스트 파일 하나, 모두 `#if !NCCL_GIN_CTRL_TCP` 안)

`gc_layer_snap.diff`: 45274b6 대비 257줄, hunk 9, 더하기 180줄, 빼기 2줄(메모리 줄의 형식 문자열 두 줄), 장치 코드 0줄 `[측정]`.

| 자리 (트리 행) | 무엇 |
|---|---|
| 18248–18312 순수 영역 "gin-control (snap): pure" | 복사 계획 `gdakiSnapPausePlan`(영역마다 D2D 하나, 다른 것 없음), `gdakiSnapAfterPlan`(영역마다 D2H 하나, 2b와 같은 칸 offset), `gdakiSnapBytesOf`, 장치 staging 상태 `gdakiSnapStage`와 규칙 `gdakiSnapStageFits`, `gdakiSnapTaken`, `gdakiSnapReleased`, 메모리 줄 몫 `gdakiSnapDevBytes`. 단위 시험이 이 영역을 그대로 잘라 씀 |
| 18376 `gdakiStoreState::snap` | 장치 staging(application 스레드만) |
| 19195–19247 호스트 부분 | `gdakiSnapStageAlloc`(cudaMalloc, 이미지가 커질 때만 다시), `gdakiSnapStageWait`("staging busy" 기다림과 줄), `gdakiSnapRun`(계획을 copy stream에 cudaMemcpyAsync) |
| 19287–19298 `gdakiStoreTake` 묻기 전 | mirror 끔(`!gdakiMiOn(r)`)이면 busy 기다림을 고정 staging 다시 잡기(`gdakiStoreStage`)보다 먼저, 그 뒤 장치 staging 잡기 |
| 19333–19347 멈춤 안 | mirror 끔: D2D 계획만 copy stream에, 그 앞에 busy 표시. 2b의 D2H, header, blob 세 줄은 `else` 쪽에 글자 그대로(mirror 켬은 바뀌지 않음) |
| 19370–19372 | COPIED가 안 됐거나 복사 실패면 staging을 놓음(D2H 없음) |
| 19396–19425 arm 뒤, WRITE 앞 | arm이 없으면 staging을 놓음. arm이 있으면 staging → 고정 칸 D2H(영역마다), header, blob, 동기화, 놓음, 줄 하나(`GIN/CTRL: ... snapshot (mirror off): pause d2d_bytes= d2d_us= host_bytes=; after the pause d2h_bytes= d2h_us=`). D2H가 실패하면 WRITE 없이 `wDone`, `wOk = false`(CONFIRMING이 무효로 끝냄; 저장소는 준비 상태 그대로) |
| 19518–19520 `gdakiStoreFree` | 장치 staging `cudaFree` |
| 24507–24513 `gdakiCtrlStoreMemLine` | 메모리 줄 끝에 `device staging %.1f MiB (GPU memory, the pause's snapshot; 0 with the mirror on)` |

- 2b의 저장 줄(`checkpoint .. stored at buddy .. d2h_us=`)은 손대지 않았다. mirror 끔에서 그 `d2h_us`는 멈춤 안 복사 시간, 곧 D2D 시간이다. 멈춤 뒤 D2H 시간은 새 snapshot 줄에 있다 `[소스]`.
- 영역 복사는 2b처럼 `cudaMemcpyDefault`다. 장치 메모리 영역이면 D2D이고, 장치 메모리가 아닌 영역이 있으면 멈춤 안에서 그 바이트가 호스트를 지난다 `[추론]`. 시험 프로그램의 영역(window, 등록 버퍼, 신호와 카운터 표)이 모두 장치 메모리인지는 `[미확인]`.
- `rs_ctrl_api_snap.diff`는 없다. launcher나 다른 단계와 나눌 형이 없어 헤더 요청이 필요 없다.

## 장치 staging 크기

이미지의 배치 크기(`gdakiCkptLayout`의 total) 하나다. 20 MiB 이미지(영역 넷)에서 20.00 MiB `[측정: 단위 시험 5]`. mirror 끈 rank마다 GPU 메모리가 그만큼 는다. 고정 호스트 staging(칸 하나, 21.06 MiB)과 ward 저장소는 2b 그대로다.
잡는 때는 첫 체크포인트(이미지 크기가 정해지는 때)이고, 이미지가 커질 때만 다시 잡는다(2b의 고정 staging과 같은 규칙). 메모리 줄은 STORE_REQ 때 나가므로 잡기 전의 계획 값을 적는다.

## 차례 논증 (CKPT_STABLE)

2b(45274b6): DRAINED → [멈춤: D2H, header, blob, 동기화] → COPIED → helper COPYING(다시 셈, 모든 상대에 CKPT_RESUME, `gdakiStoreArm`; 16399–16430행) → application WRITE(`beginWrite`, `recvSlot`) → `wDone` → CONFIRMING(16432행–: WRITE 끝남, 모두 확인, 성공일 때만 CKPT_STABLE, 짝 먼저) `[소스]`.

이 작업: DRAINED → [멈춤: D2D, 동기화] → COPIED → COPYING(같음) → arm → **D2H, header, blob, 동기화** → WRITE → `wDone` → CONFIRMING(같음).

1. 멈춤 안에는 D2D만 있다. 고정 칸은 멈춤 안에서 쓰이지 않는다(단위 시험 1: 10 851 멈춤에서 칸 바이트가 멈춤 앞뒤로 같음) `[측정]`.
2. 사본의 내용은 멈춤 때의 이미지다. D2D는 COPIED 전에 동기화되고, COPIED가 있어야 CKPT_RESUME이 나간다. 멈춤 뒤 장치가 영역을 다시 써도 staging은 바뀌지 않는다 `[소스, 측정: 단위 시험 2의 멈춤 뒤 쓰기]`.
3. CKPT_STABLE(k)는 CONFIRMING이 `wDone && wOk`(k)를 볼 때만 나간다. `wOk`는 WRITE가 끝난 뒤에만 참이고, WRITE는 D2H 동기화가 성공한 뒤에만 시작한다. D2H 실패는 `wOk = false`다. 그래서 차례는 2b와 같고, 시각만 D2H만큼 늦다 `[소스]`.
4. 받는 칸은 2b 그대로 `recvSlot`(안정 칸의 다른 쪽)이다. 안정 칸은 CKPT_STABLE 전에는 덮이지 않으므로 늘 온전한 이미지 하나를 갖는다 `[소스, 측정: 단위 시험 2]`.
5. CONFIRMING의 한도는 max(30 s, 4 × 멈춤 한도)라 멈춤 뒤 D2H(20 MiB에서 약 1.6 ms)가 그 안에 든다 `[소스, 추론]`.
6. staging busy: busy는 첫 D2D를 넣을 때 서고, copy stream이 비었다고 알 때(D2H 뒤 동기화 성공, 또는 D2H 없이 끝날 때 멈춤의 동기화 성공) 내린다. 다음 체크포인트는 고정 staging을 다시 잡거나 멈춤을 묻기 전에 busy면 stream을 기다리고 줄을 남긴다. 기다림도 실패하면 체크포인트를 미룬다(backOff). 소비자는 같은 호출 안의 같은 스레드라, 건강한 프로세스에서 기다림은 동기화가 실패한 뒤에만 생긴다 `[추론]`.
7. 처음 판에서 busy 기다림이 `gdakiStoreStage` 뒤에 있었다. 단위 시험 3이 ASan의 해제 뒤 쓰기로 잡았다(실패한 D2H가 남긴 복사가 다시 잡힌 고정 staging에 씀). 기다림을 앞으로 옮겼다 `[측정]`.

## 멈춤 바이트 모형 (20 MiB 이미지, 영역 넷: 16 MiB, 4 MiB − 8 KiB, 4 KiB, 4 KiB)

| | 2b 멈춤 | 이 작업의 멈춤 | 멈춤 뒤 |
|---|---|---|---|
| 호스트 쪽(D2H) 바이트 | 20 971 520 | 0 | 20 971 520 (이 작업), 0 (2b) |
| D2D 바이트 | 0 | 20 971 520 | 0 |
| 호스트 메모리 쓰기(header, blob 4 KiB) | 39 032 | 0 | 39 032 (이 작업) |

`[측정: 단위 시험 5, logs_snap/unit_2.log]`. 호스트 쪽 바이트 비율 0/20 971 520 = 0, D2D 바이트는 이미지와 같다.
시간 어림 `[추론]`: 2b 멈춤 안 D2H 약 1.60 ms(gin-mirror 확인 3의 D2H 13.1 GB/s `[측정, gin-mirror]`로 셈). D2D는 장치 대역에 달려 약 0.1–0.2 ms `[추론, 미확인: 이 GPU의 D2D 대역을 재지 않음]`.
그래서 20 MiB에서 멈춤이 약 1.4–1.5 ms 짧아진다. 4 KiB 셀처럼 이미지가 작으면 차이도 작다.

## 확인 표 (로그는 스크래치 `agent_gc_snap/logs_snap/`)

| 단계 | 결과 | 로그 |
|---|---|---|
| `syn` | build, build-gcp, build-gct에서 호스트 파일 `-fsyntax-only` 통과 [측정] | `syn_3.log` |
| `api` (pin) | 붙인 블록 둘이 헤더와 바이트 같음(ctrl API `8f132e67`, seams `5f225e8c`), launcher wire 같음, 헤더 단독 컴파일 rdma와 tcp, `TCP_CELLS` 단독 거절: 통과 [측정] | `api_2.log` |
| `gc`, `gcp`, `gct`, `gctp` | 넷 모두 빌드됨. 호스트 파일의 경고 0. libnccl gc `aeab5439`, gcp `69dcea20`, gct `2cae5fae`, gctp `d46c05f7` [측정]. 아래 메모 | `build_*_1.log`, `build_gct_r.log` |
| `pre` | gct, gctp 정규화 뒤 ln4와 0 hunk(줄 수 150 748, 150 175 같음); gctc 2 hunk 3줄(RST 간격, 정규화 md5 `b1b76e0e`로 int2와 같음); gc 106 hunk(새 코드, 기록용) [측정] | `pre_1.log` |
| `sites` (pin) | 149행 셈 모두 같음, `#if NCCL_GIN_CTRL_TCP` 갈래 44개 모두 ln4 글 그대로; 로그가 int2의 `sites_s10.log`와 바이트 같음 [측정] | `sites_2.log` |
| `unit` rdma (pin) | 옛 시험 일곱, gc_unit_prep 366, p1 10 248 976, gate_fenced 10/10, p2 3 993 471, p2b 11 114, p2a2 4 447, p3 473, **gc_unit_snap 453 402 검사**, 모두 실패 0 [측정, n 1] | `unit_2.log` |
| `unit` tcp | 옛 일곱 실패 0, gc_unit_prep 174, 단계 시험과 gc_unit_snap 0 검사 [측정] | `unit_2.log` |
| `ident` | 설치 헤더 ln4와 같음; 매크로 없음/있음 프로그램 16/16 SASS와 자원 같음; 네 빌드의 장치 객체 207개씩: SASS 같음 205, 컴파일 해시만 가리면 같음 2(`onerank.cu.o`, `device_glue.o`), 다름 0; 라이브러리 넷의 자원 사용 같음: 통과 [측정]. 바이트 같은 객체가 0인 것은 장치 객체를 다시 컴파일했기 때문(아래 빌드 메모) [추론] | `ident_1.log`, `out/ident_snap/` |
| `diff` | `gc_layer_snap.diff` `17892f1f`, 257줄, 45274b6 대비, 거꾸로 적용 확인 [측정] | `diff_1.log` |
| `info` | `agent_gc_snap/out/build_info.txt`(호스트 파일 md5 `358ce06c`, 작업 트리 diff md5 `17892f1f`) [측정] | `info_1.log` |
| 합칠 때 | 다른 에이전트의 `agent_gc_p2a2` 호스트 파일(16:16 스냅숏, md5 `01c048df`, 작업 트리 +438/−70) 위에 `patch --dry-run`: hunk 9/9 적용(마지막 하나만 offset 180) [측정]. 그 스냅숏에 대해서만의 뜻이다 | `merge_dryrun.log` |

빌드 메모: 복사한 nccl-src의 파일 시각이 ln4 객체보다 새 것이 있어 gcp, gct, gctp는 410개, gc는 147개 파일을 다시 컴파일했다(장치 객체 포함; `devsync` 해시는 같음; gc의 나머지는 이 작업이 중간에 멈춘 앞의 두 판이 이미 컴파일함).
경고는 gcp, gct, gctp에 하나씩, 모두 NCCL 원본 `scheduler/symmetric_sched.cc:327`의 `-Wextra` 경고다. ln4 자신의 전체 빌드 로그에도 같은 줄이 있다(`agent_mi_fix/build_mip_i3.log`) `[측정]`. 이 작업의 파일 경고는 0이다.
gct 첫 판은 라이브러리를 만든 뒤 스크립트를 실행 중에 고쳐 끝에서 문법 오류(rc 2)로 끝났다. 같은 트리로 다시 돌린 `gct_snap_r`은 다시 컴파일 0, libnccl md5가 같다 `[측정]`.

## 단위 시험 `gc_unit_snap.cc` (665줄, ASan과 UBSan)

가짜 CUDA(복사를 쌓고 동기화 때 실행; 실패한 동기화는 복사를 남김)와 가짜 저장소(buddy의 두 칸 MR, 안정 칸을 가진 옛 MR 보관)로, 트리에서 자른 `gc_snap_pure.inc`, `mi_pure_store.inc`(`gdakiStoreUp`의 칸 번갈이, ward 기록), `rs_ckpt_pure.inc`(`gdakiCkptLayout`)를 쓴다.

1. 멈춤에는 D2D만: 10 851 멈춤, 복사 27 113개 모두 계획의 D2D, 고정 칸 바이트 그대로 `[측정]`.
2. 무작위 열 400개 × 체크포인트 30(200개는 2b와 견줌, 200개는 이 길만의 실패까지): 생성기는 `gc_unit_p2b.cc` 올리기 시험의 것을 본떠 이 파일에 다시 씀(파일을 포함하지 않음; 블록 바뀜, blob, 새 배치, 되살린 buddy, WRITE 실패)에 영역 여러 개, 건너뜀, 포기, 멈춤 복사 실패, arm 없음, D2H 실패, 확인 없음, 멈춤 뒤 쓰기를 더함.
   안정 7 399, 무효 3 452, 미룸 1 149, busy 기다림 940. 모든 CKPT_STABLE이 D2H와 성공한 WRITE 뒤, WRITE는 안정 칸에 안 감, 안정 칸은 늘 그 체크포인트의 멈춤 때 이미지 `[측정]`.
3. staging busy 장면: D2H 동기화 실패 → busy; 다음 체크포인트에서 stream이 또 실패하면 멈춤 없음(ASK도 없음); 그 다음은 옛 복사를 끝낸 뒤 멈춤; arm 없음과 포기는 곧바로 놓음; 이미지가 커질 때 기다림이 먼저 `[측정]`.
4. 2b와 바이트 같음: WRITE 4 330개를 견줌. 읽는 쪽이 읽는 바이트(header 칸, 모든 영역, blob)는 모두 같음. 칸 전체가 바이트까지 같은 것은 4 244개이고, 86개는 영역 사이와 이미지 뒤의 채움(padding) 바이트만 다르다.
   까닭: 2b는 무효가 된 체크포인트에서도 멈춤 안 D2H로 고정 칸을 쓰고, 이 길은 arm 뒤에만 쓴다. 그래서 배치가 바뀐 뒤 채움 자리에 남은 옛 바이트가 다를 수 있다. 채움은 어느 FETCH도 해석하지 않는다 `[측정, 소스]`. 안정 칸 5 657번 같음(같은 기준).
5. 멈춤 바이트 모형과 메모리 줄 몫(위 표).

## EXPERIMENT.md 3절에 넣을 다시 예측 (안; mirror 끈 셀, 사전 등록 전)

- 새 행 "mirror 끈 체크포인트의 멈춤 안 호스트 바이트 0": 셀 `rs4_kill3`, `rs4_kill3_ckpt`, `rs4_kill1`, `rs4_none`(모두 `@gc`). 시행마다 snapshot 줄의 `host_bytes`가 모두 0이고 `d2d_bytes`가 이미지 크기와 같음, `d2h_bytes`가 멈춤 뒤 줄에 있음. 구조적 성질이라 모든 유효 시행 `[초안: 사전 등록 전 확정]`. 찾는 키 안 `snap_pause_d2d`.
- 멈춤 길이: `rs4_none@gc`의 입력 멈춤 상한은 gin-mirror 장애 없음 고정값 16 ms(4 KiB 셀)를 그대로 쓴다. 2b 판이었다면 멈춤 안 D2H(이미지 I에서 I / 13.1 GB/s, 20 MiB에서 약 1.6 ms)가 더해졌을 것이고, 이 판에서는 D2D(20 MiB에서 약 0.1–0.2 ms `[추론, 미확인]`)만 더해진다. 시행마다 snapshot 줄의 `d2d_us`와 `d2h_us`를 보고한다. 이 셀들의 이미지 크기는 `[미확인]`(pilot에서 줄로 읽음).
- 복원 시간: mirror 끈 셀의 kill → 마지막 게시는 2b와 같은 범위로 둔다. FETCH가 읽는 안정 칸의 바이트와 크기가 2b와 같기 때문이다(단위 시험 4). 바뀌는 것은 안정 확정의 시각뿐이다: CKPT_STABLE이 멈춤 뒤 D2H만큼(20 MiB에서 약 1.6 ms) 늦고, 그 사이의 kill은 한 체크포인트 앞으로 복원된다(2b에서 WRITE 중의 kill과 같은 꼴). 재실행 단계 수는 gin-restore의 원래 판정식 그대로다 `[추론]`.
- 5절 "장치 코드 0줄"은 그대로 참이다(GPU 메모리가 이미지만큼 는 것만 적음).

## EXPERIMENT.md 11절과 12절에 넣을 줄 (안)

- 11절: `- [ ] mirror 끈 체크포인트 멈춤 줄이기(GPU 안 사본: 멈춤 안 D2D만, D2H와 WRITE는 멈춤 뒤): 빌드와 CPU 시험까지 — 2026-10-22, impl/gc_layer_snap.diff 17892f1f(45274b6 위). 클러스터에서 멈춤 길이와 D2D 시간은 안 잼`
- 12절: `| 2026-10-22 | mirror 끈 체크포인트 멈춤 줄이기 구현(실행 없음, CPU와 빌드만; 사용자 선택 2026-10-22). int2 커밋 45274b6 위의 impl/gc_layer_snap.diff(17892f1f, 257줄, 호스트 파일만, 더하기 180줄, 장치 코드 0줄): mirror 끈 rank는 멈춤 안에서 영역마다 D2D 하나로 장치 staging(이미지 크기, 20 MiB에서 20.00 MiB GPU 메모리)에 사본을 찍고, arm(CKPT_RESUME) 뒤 D2H, header, blob, 2b의 WRITE; CKPT_STABLE은 WRITE 뒤 그대로; 다음 멈춤은 staging이 빈 뒤(busy 기다림과 줄); mirror 켬과 tcp 빌드는 그대로. gc, gcp, gct, gctp 빌드됨(이 작업의 경고 0). tcp 전처리는 정규화 뒤 ln4와 hunk 0(gct, gctp), gctc는 RST 간격 2 hunk만 [측정]. 단위 시험 두 빌드 통과, gc_unit_snap 453 402 검사 실패 0(rdma): 멈춤 안 호스트 바이트 0, 무작위 열 400개에서 CKPT_STABLE 차례, staging busy, 읽는 바이트가 2b와 같음 [측정]. 장치 동일성: 프로그램 16 조합 같음, 장치 객체 207개 × 4가 SASS로 ln4와 같음(해시만 다른 것 2개씩) [측정]. 클러스터 실행 없음 | impl/notes_snap.md, 스크래치 agent_gc_snap/logs_snap/ |`

## 파일 md5

| 파일 | md5 | 줄 |
|---|---|---|
| `gc_layer_snap.diff` | `17892f1ffc9c525cfa1ab7b74d3f1a2e` | 257 |
| `gc_unit_snap.cc` | `43eabeaf94e6491ab0366e78127d1e88` | 665 |
| `notes_snap.md` | (이 문서) | |
| 스크래치 `agent_gc_snap/build_gc_snap.sh` | `a492ba8f6d2ae702db34572ec5bb2993` | 981 |

바탕(고치지 않음): `rs_ctrl_api.h`(adf88953 판), `gc_layer_int.diff` `c0975edb`, worktree `build_gc.sh` `fe2936d8`. `EXPERIMENT.md`, `launcher/*`, `test/*`, 다른 단계의 `gc_layer*.diff`와 시험은 이 작업이 고치지 않았다.
