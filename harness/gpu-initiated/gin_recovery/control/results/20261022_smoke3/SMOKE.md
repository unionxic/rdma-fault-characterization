# gin-control 셋째 하드웨어 smoke (2026-10-22, 채점 안 함)

2a-2-C 4단계(판정 효력: FIN은 확인 창만 열고, hold는 t_F + W의 표 판정이나 launcher EXITED/FENCED에서만 시작) 트리를 실제 RNIC에서 돌린 smoke다.
셀은 넷이다. (1) 장애 없는 대조 `gc4_none_ow@gc` + 따뜻한 예비 프로세스(`SPARE=1 SPARE_RANK=3`). (2) kill 셀 `gc4_kill3_ow@gc`(실행기가 rank 3을 기록한 PID로 SIGKILL).
(3) 멈춤 셀 `gc4_stop12000_fence@gc`(실행기가 rank 3을 기록한 PID로 SIGSTOP, 12 000 ms 뒤 SIGCONT, `FENCE=lineage`). (4) 증인 끈 kill 셀 `gc4_kill3_ow_nowitness@gc`(`WITNESS=0`).
시행마다 n 1이고 본 실험과 pilot에 들지 않는다. 시도는 여섯(a1–a6, 한도 여섯)이고, 모두 `harness/gpu-initiated/common/cluster_run.sh` 안에서 `cells_gc.sh` → `run_gc.sh`(고치지 않은 worktree 판)로 돌았다.

- 트리: 세션 스크래치 `agent_gc_p2a2/nccl-src`, 4단계를 커밋 54c9d22 "gin-control 2a-2-C step 4 (gc_layer_int.diff c7403c07)"로 커밋(ln4 대비 diff md5 c7403c07 확인) `[측정]`.
  고친 diff: [../../impl/gc_layer_smoke3fix.diff](../../impl/gc_layer_smoke3fix.diff)(호스트 파일 하나, 49줄 +22/−5, 장치 코드 0줄). 고친 트리의 ln4 대비 diff는 md5 bf4e142b(13 297줄); `gc_layer_int.diff`는 다시 쓰지 않았다.
- 빌드 스크립트 `agent_gc_p2a2/build_gc_int3.sh`: 머리 커밋 이름을 54c9d22의 것으로 바꾸고(`INT3_HEAD`로 덮어쓸 수 있음), int3 키에서 깨끗한 트리는 머리 커밋 그대로 빌드하게 두 줄 고침(91c70531 → 46000bf7; 원본 `build_gc_int3.sh.pre_s3`).
- 묶음: 두 노드의 새 폴더 `~/gi-bundle/gin_ts2/<set>/{lib/gc,gctest}`와 링크 `~/rs-bundle/<set>`(smoke2와 같은 배치). 배포 기록: [deploy/](deploy/).
- 실행 스크립트(저장소 밖, 세션 스크래치 `agent_gc_smoke3/`): `run_smoke3.sh`(`cluster_run.sh -w 3600 -t gc-smoke3-<시도> -- timeout -s KILL 500 bash test/cells_gc.sh <로그> <셀> gc rs 1 1 DRIVER=gin_mi <셀 env>`, `LAUNCHER_ENV=-`),
  `deploy_smoke3.sh`(smoke2의 것 그대로), `keys.sh`(줄 뽑기). 셀 env는 `cells_gc.json`의 것에 `SPARE_RANK=3`.
- 로그는 모두 `sed -E 's/([0-9]{1,3}\.){3}[0-9]{1,3}/<addr>/g'`를 거쳐 이 폴더에 옮겼다. 이 폴더에 IPv4 꼴 문자열과 관리망 주소는 0건이다 `[측정: grep]`.
- 시도마다 `rows_gc.py --stops`와 `rows_gc.py`(각 시도 폴더의 `trials.csv`)를 돌렸다. 아래 시간은 그 열과 줄의 `mono_ms`에서 다시 셈한 것이다(노드 사이는 `mono_xnode`).

## 빌드와 묶음

| 무엇 | md5 | 비고 |
|---|---|---|
| libnccl `gc_s3` | `aa790f08b791e4ad087f9efe5c65d9ff` | 4단계 그대로(커밋 54c9d22); 묶음 `gc_smoke3`(a1–a3) |
| libnccl `gc_s3f1` | `0b8fa6d78213445702f7e61aae9958b9` | + 고침 하나; 묶음 `gc_smoke3_f1`(a4–a6) |
| `gin_mi` | `cfce02c9c74ec4434737982940b6db5b` | smoke2의 바이너리 그대로(`gin_mi.cu` 556804c0, 설치된 머리 `build/include`가 smoke2의 `include_mi`와 같음 `[측정: diff -r]`) |
| `gin_launcher` | `3af84d2a654cd0f55adb7003a1a74f44` | smoke2의 바이너리 그대로(`gin_launcher.c` 5b62a1f5, `launcher_msg.h` fb11b235) |

두 노드 md5 같음, `ldd`는 libnccl이 묶음의 것 `[측정: deploy/]`. 빌드 경고 0. 고친 뒤 `syn` 통과, `unitp1`(`gc_unit_p1` rdma 10 285 083 검사 실패 0, `gate_fenced` 64 검사 실패 0) `[측정: agent_gc_smoke3/logs/unitp1_f1.log]`.
다른 검사(`api`, `pre`, `sites`, `ident`, 빌드 넷)는 고친 뒤 돌리지 않았다 `[미확인]`.

## 시도마다

| 시도 | 라이브러리 | 셀 | 결과 | 근거 |
|---|---|---|---|---|
| a1 | `aa790f08` | (1) 장애 없음 + 예비 프로세스 | 통과 | [a1/raw/](a1/raw/) |
| a2 | `aa790f08` | (2) kill rank 3 | 통과. 판정 launcher EXITED(3행), 복원, 데이터 같음 | [a2/raw/](a2/raw/) |
| a3 | `aa790f08` | (3) SIGSTOP 12 000 ms | 실패. 멈춤 판정(STALL_HELPER)은 났으나 반응이 1단계의 거절(펜스 없음); NOHOLD, 네 rank 끝 코드 4 | [a3/raw/](a3/raw/) |
| a4 | `0b8fa6d7` | (3) SIGSTOP 12 000 ms | 통과. 멈춤 판정 → hold → FENCE → FENCED → 복원, 데이터 같음 | [a4/raw/](a4/raw/) |
| a5 | `0b8fa6d7` | (4) kill rank 3, 증인 끔 | 판정은 통과(launcher EXITED, FIN 아님), 복원, 데이터 같음. 다만 증인 끔이 소켓을 끄지 않음(아래 요청 2) | [a5/raw/](a5/raw/) |
| a6 | `0b8fa6d7` | (2) kill rank 3 | 통과(고친 라이브러리로 셀 (2) 다시) | [a6/raw/](a6/raw/) |

셀 (1)–(3)이 모두 통과했다(셀 (1)은 `aa790f08`, 셀 (2)는 두 라이브러리 모두, 셀 (3)은 `0b8fa6d7`) `[측정, 셀마다 n 1]`. 고친 라이브러리로 셀 (1)은 다시 돌리지 않았다(시도 한도) `[미확인]`.
고침은 멈춤 판정의 반응에만 닿는다(아래); 장애 없는 셀에는 멈춤 판정이 없다 `[소스]`.

## 고친 것 (a3 → a4)

- **본 것** `[측정: a3/raw/gc4_stop12000_fence_gc_n1_r1.log]`: `GIN/RC: rank 1: rank 3 (incarnation 0) judged stalled (liveness stall judged (STALL_HELPER)); STALLED to 3 rank(s); phase 1 declines (no launcher, no fence yet)`,
  `GIN/RS: rank 1: armed rank 3 (incarnation 0) declined without a hold (weak death evidence (not a FIN without BYE, not two refused connects); …); NOHOLD to 2 rank(s)`. 세 생존 rank 모두 거절, `exit=4`.
- **까닭** `[소스]`: 멈춤 판정의 반응 `gdakiCtrlStallDecline`이 1단계 모양 그대로(STALLED 방송 뒤 언제나 거절)였다. `NCCL_GIN_RESTORE_FENCE`(헤더의 `GDAKI_CTRL_P_RESTORE_FENCE`)는 정의만 있고 어디서도 읽지 않았고,
  hold의 강한 증거 이름(`gdakiHoldStrongCause`)에 STALL, STALL_HELPER가 없어 무장된 rank도 hold로 가지 않았다(9.3절 강한 증거 일곱 가운데 둘이 빠짐).
- **고침**(최소, 호스트 파일, `#if !NCCL_GIN_CTRL_TCP` 안의 page 영역): `gdakiCtrlStallFenceOn`(env `NCCL_GIN_RESTORE_FENCE`가 없거나 `lineage`이고 launcher와 짝을 맺었음)이 참이면
  `gdakiCtrlStallDecline`이 그 상대의 `lostCause`에 판정 원인(STALL 또는 STALL_HELPER)을 적고 같은 `gdakiTsDecline`을 부른다; `gdakiHoldStrongCause`의 rdma 이름에 STALL, STALL_HELPER를 더함.
  그래서 무장됐으면 hold가 시작되고, 활성화 관문(9.4절)이 FENCE를 보내고 FENCED를 기다린다. `none`, launcher 없음, 무장 아님은 전처럼 거절. 판정 줄의 끝 글만 바뀜
  (`the hold when armed, then FENCE and the restore (fence=lineage, launcher paired)` 또는 `declined (fence=none or no launcher)`). tcp 빌드는 바뀌지 않음 `[소스: 바뀐 줄이 모두 #if !NCCL_GIN_CTRL_TCP 안]`.

## 셀 (1) 장애 없음 + 따뜻한 예비 프로세스 (a1)

| 무엇 | 값 | 줄 |
|---|---|---|
| go 파일까지의 기다림, 띄운 뒤 HELLO | 2 718.6 ms, 417.3 ms | launcher `spare wait-for matched after …`, `spawned spare said HELLO (…, after … ms)` |
| READY | 있음 | launcher `spare of rank 3 incarnation 1 is READY` |
| 판정 효력 줄 | 네 rank 모두 | `the judgement table decides an exit from now: a witness FIN or RST opens the confirm window (W=20 ms) …` |
| 판정 | 0(죽음, 멈춤, 창 모두 없음) | `judged dead`, `judged stalled`, `confirm window` 0줄 |
| 네 rank | `resume_rc=0`, 600 step, `xchg=ok`, `x_match=1`, `sig_exact=1` | kv |
| STOP | `la_stop_n=0 la_qp_err_n=0`, 남은 프로세스 0 | `rows_gc.py --stops`, meta `left=0` |
| 생존 READ | 1 032/1 032 성공, 박동 간격 최대 1.085–1.096 ms(rank마다), `W=20 W_rule=20` | `probe summary` |

W 규칙(10 × 장애 없는 박동 간격 최대, 20–50 ms로 자름)은 10.96 ms → 20 ms이고 쓰인 W와 같다 `[측정]`. 예비 프로세스의 끝 코드 137은 launcher shutdown의 SIGKILL이다.

## 셀 (2) kill rank 3 (a2, a6 통과)

시각은 줄의 `mono_ms`, 노드 사이는 `mono_xnode`. 범위는 세 생존 rank의 범위(시도 하나 안)다 `[측정, 시도마다 n 1]`.

| 단계 | a2 | a6 | 줄(정확한 글, 앞부분) |
|---|---|---|---|
| kill → FIN | 0.28 ms(rank 1, 같은 노드) | 1.24 ms(rank 1) | 실행기 `GINRS killed rank=3 …`; `socket to rank 3 closed cause=FIN … liveness=pending (the confirm window judges: W=20 ms)` |
| 확인 창 | t_F + 20 ms에 `alive`(셋 모두), 표 8행 | 같음 | `confirm window for rank 3 opened by FIN W=20 over the device line`, `closed: alive (…, READ1 +0.176, READ2 +10.137, W=20 …)`, `witness of rank 3 lost; liveness alive (table row 8; the witness is re-dialled)` |
| launcher 끝 보고 | kill 뒤 102.0 ms EXITED | 105.3 ms EXITED | launcher `rank 3 incarnation 0 EXITED (its pidfd is readable: the thread group ended)` |
| kill → 판정 | 101.9–102.7 ms, 퍼짐 0.80 ms | 105.4–106.0 ms, 퍼짐 0.64 ms | `rank 3 judged dead (cause=EXITED)`, `ended by the judgement table (row 3: the launcher's end)` (셋 모두) |
| hold 시작 | kill 뒤 105.8 ms(가장 이른 것) | 110.0 ms | `is held for a restore instead of a decline (peer judged dead: the judgement table shows EXITED; cause=EXITED)`, `hold of rank 3 started` |
| 펜스 | FENCE 보내지 않음: EXITED가 펜스 끝 | 같음 | rank 2 `fence FENCED (by EXITED from node 1)` |
| UD REJOIN | 셋 모두 받아들임 | 같음 | `the REJOIN of rank 3 (incarnation 1) taken over UD …` |
| 복원 끝 | 판정 → 게시 74.2 ms, kill → 게시 176.1 ms, hold 최대 70.4 ms | 72.7 ms, 178.1 ms, 68.1 ms | `rank 3 restored as incarnation 1 (on time; 74.1 ms after the hold start …)`; 예비 프로세스 `restored as incarnation 1 from checkpoint 120` |
| 데이터 | `data_equal=1`, `ow_data_equal=1` | 같음 | `trials.csv` |
| STOP | `la_stop_n=0 la_qp_err_n=0`, 남은 프로세스 0 | 같음 | `rows_gc.py --stops` |

- **무엇이 판정했나.** 표 3행(launcher EXITED, 원인 EXITED)이다(`judge_causes=EXITED:3`, 두 시도 모두). FIN은 창만 열었고 FIN 하나로 판정하거나 hold를 시작한 rank는 없다 `[측정]`.
  창은 6개 모두(두 시도 × 셋; a5까지 9개) `alive`로 닫혀 8행(증인 다시 걸기, `ECONNREFUSED` 한 번)이 됐다. 9.3절이 어림한 FIN+NORESP(kill 뒤 20–51 ms)는 나오지 않았고
  판정은 launcher 보고 쪽(20–250 ms 안)으로 왔다. 창의 READ2가 kill 뒤 약 10 ms에 끝나 "박동이 늘었음"을 읽었다. 창은 "over the device line"(GPU 진행 줄)을 읽는데, SIGKILL 뒤
  스레드 그룹이 끝나기까지(약 102 ms) GPU 커널이 진행 줄을 계속 쓴 것으로 보인다 `[추론: READ2 성공과 박동 늚, 그룹 끝 102–105 ms]`. 아래 요청 1.
- smoke2(4단계 전, FIN = 죽음)의 판정은 kill 뒤 0.31–0.42 ms, 복원 kill → 게시 186.5 ms였다. 4단계로 판정은 약 102 ms 늦고, kill → 게시는 176–178 ms로 비슷하다(활성화를 FENCED가 아니라 EXITED에서 곧바로 받음) `[측정, n 1씩]`.

## 셀 (3) SIGSTOP 12 000 ms, 펜스와 복원 (a4 통과; a3 실패)

| 단계 | a4 시간(멈춤 = 0) | 줄 |
|---|---|---|
| 멈춤 | 0 | 실행기 `GINRS stop rank=3 pid=… stop_ms=12000` |
| 의심(문턱 아래) | 2 091 ms(rank 1), 셋 모두 `kind=watch stale_ms=2000.x` | `rank 3 suspected (kind=watch stale_ms=2000.8) (partition guard: another survivor sees it fresh)` |
| 멈춤 판정 | 10 094.3–10 096.5 ms(셋), 퍼짐 2.2 ms | `rank 3 (incarnation 0) judged stalled (liveness stall judged (STALL_HELPER)); STALLED to 3 rank(s); the hold when armed, then FENCE and the restore (fence=lineage, launcher paired)` |
| hold | 판정 뒤 0.1 ms에 셋 모두 | `is held for a restore instead of a decline (liveness stall judged (STALL_HELPER); cause=STALL_HELPER)`, `hold of rank 3 started` |
| FENCE | 버디 rank 2가 hold 뒤 0.6 ms에 보냄; launcher SIGKILL은 멈춤 뒤 10 103.0 ms | rank 2 `fence FENCING: FENCE sent to the launcher of node 1`, `the activation waits for FENCED`; launcher `FENCE of rank 3 incarnation 0 from rank 2: SIGKILL sent through its pidfd` |
| FENCED | SIGKILL 뒤 118.7 ms(`fence_sent_to_fenced_ms=118.719`) | launcher `rank 3 incarnation 0 FENCED: the group ended 118.664 ms after SIGKILL`; rank 2 `fence FENCED (by FENCED from node 1)` |
| 펜스 중의 FIN | SIGKILL 뒤 약 0.2 ms, 창은 곧바로 `unconfirmed`(이 세대 READ 없음), 9행 | `confirm window of rank 3: table row 9, no verdict (1.086 ms after the FIN) …` (hold 중이라 반응 없음) |
| 활성화, REJOIN | FENCED 뒤 1.8 ms에 활성화, UD REJOIN 셋 모두 | launcher `activation of rank 3 incarnation 1 handed to its spare`; `the REJOIN of rank 3 (incarnation 1) taken over UD` |
| 복원 끝 | 판정 → 게시 195.3 ms, hold 최대 191.8 ms; 멈춤 → 게시 약 10 290 ms | `rank 3 restored as incarnation 1 (on time; 195.3 ms after the hold start …)` |
| SIGCONT | 12 003.0 ms, `present=0`(펜스가 이미 끝냄) | 실행기 `GINRS cont rank=3 … present=0` |
| 데이터 | `data_equal=1`, `ow_data_equal=1`, 생존 rank와 예비 프로세스 `resume_rc=0` | `trials.csv`, kv |
| STOP | `la_stop_n=0 la_qp_err_n=0`, 남은 프로세스 0 | `rows_gc.py --stops` |

- **무엇이 판정했나.** 표 15행(STALL_HELPER: 호스트 멈춤, GPU는 진행 또는 조용; notes_live.md의 뜻)이다(`judge_causes=STALL_HELPER:3`). 14행(GPU 멈춤)은 아니다. 멈춤 뒤
  10 000 ms 문턱 + 판정 pass로 9.3절 어림 10 000–10 300 ms 안이다 `[측정, n 1]`. 멈춤 동안 문턱 아래에서 판정은 없었다(의심 줄만).
- a3(고치기 전): 멈춤 판정 10 053.8–10 055.7 ms(STALL_HELPER, 셋), 그 뒤 거절, 멈춤 뒤 약 14 s에 `kind=gpu` 의심 줄 하나씩, SIGCONT `present=1` `[측정]`.

## 셀 (4) kill rank 3, 증인 끔 (a5)

- kill → 판정 103.4–103.5 ms, 셋 모두 `cause=EXITED`(3행, launcher 보고), 퍼짐 0.16 ms. hold는 kill 뒤 108.0 ms, 판정 → 게시 73.1 ms, kill → 게시 176.4 ms, `data_equal=1` `[측정, n 1]`.
  예측한 두 길(launcher 보고 또는 READ 실패 3.5–4.5 s) 가운데 launcher 보고이고, FIN이 판정하지 않았다.
- 그러나 `WITNESS=0`(run_gc.sh가 `NCCL_GIN_CTRL_WITNESS=0`을 넘김, meta `witness=0`)에서도 관리망 소켓이 열려 있었고 kill 뒤 FIN이 창을 열었다
  (`socket to rank 3 closed cause=FIN … liveness=pending`, `closed: alive`, `table row 8; the witness is re-dialled`). 라이브러리는 그 값을 페이지의 `witnessOn`(표의 W 입력)으로만 읽는다 `[소스]`.

## 남은 것과 요청 (고치지 않음)

1. **확인 창이 죽은 프로세스를 `alive`로 봄**(9/9 창, a2, a5, a6). 창이 GPU 진행 줄을 읽고 그 줄이 SIGKILL 뒤 그룹 끝까지 오르는 것으로 보인다 `[추론]`. 그래서 kill 판정은
   4–6행이 아니라 3행(launcher, 약 102–106 ms)이다. 9.3절 어림(FIN+NORESP, 20–51 ms)과 다르다. 창이 호스트 `watchBeat`를 읽어야 하는지, 둘 다 읽어야 하는지 결정 요청.
   launcher 보고를 잃으면 판정이 READ 실패 길(3.5–4.5 s)로 밀린다 `[추론]`.
2. **증인 끔이 소켓을 끄지 않음**(a5). `WITNESS=0`의 FIN이 창을 열고 8행이 다시 건다. 증인 끔에서 소켓 FIN이 창을 열지 않게 할지, 셀 4행의 뜻을 바꿀지 결정 요청.
3. kill 셀에서 FENCE는 한 번도 보내지 않았다: launcher EXITED가 hold 전에 와서 그것이 펜스 끝이다(`fence FENCED (by EXITED from node 1)`, `la_fence_sigkill_n=0`). FENCE → FENCED는 멈춤 셀에서만 나왔다.
   채점이 kill 셀에서 FENCE를 요구하면 다시 볼 것.
4. 낡은 주석: `gdakiCtrlStallDecline` 위의 "Phase 1's reaction … no launcher and no FENCED in phase 1"은 고침 뒤에도 남았다(새 주석을 그 아래에 덧붙임).
5. `cells_gc.json`의 `gc4_stop12000_fence@gc` todo(pilot이 사전 등록 여부를 정함)는 그대로다. `test/*`, `launcher/*`, EXPERIMENT.md는 고치지 않았다.
6. 아직 실제 NIC에서 돌지 않은 것: `gc4_stop12000_none`(거절), 1 500–8 000 ms 멈춤(투명), RST, fd 자식, 관리망 끊김, `NO_EXIT_REPORT`(READ 실패 길), `gct`/`gcp`, 채점.
