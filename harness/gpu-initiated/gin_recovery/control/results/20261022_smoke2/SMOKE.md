# gin-control 둘째 하드웨어 smoke (2026-10-22, 채점 안 함)

통합 int3(2a-2-C 1–3단계, 첫 smoke 고침, 예비 프로세스 고침, GPU 진행 생존 낱말, mirror 끈 D2D 사본) 트리를 실제 RNIC에서 돌린 smoke다.
셀은 둘이다. (1) 장애 없는 대조 셀 `gc4_none_ow@gc`에 따뜻한 예비 프로세스를 켬(`SPARE=1 SPARE_RANK=3`). (2) kill 셀 `gc4_kill3_ow@gc`(실행기가 rank 3을
기록한 PID로 SIGKILL, 따뜻한 예비 프로세스가 복원). 시행마다 n 1이고 본 실험과 pilot에 들지 않는다. 시도는 넷(a1–a4)이고, 모두
`harness/gpu-initiated/common/cluster_run.sh` 안에서 `cells_gc.sh` → `run_gc.sh`(고치지 않은 worktree 판)로 돌았다.

- 트리와 통합: [../../impl/notes_int3.md](../../impl/notes_int3.md). 고친 diff: [../../impl/gc_layer_smoke2fix.diff](../../impl/gc_layer_smoke2fix.diff)(호스트 파일 하나, 장치 코드 0줄).
- 묶음: 두 노드의 새 폴더 `~/gi-bundle/gin_ts2/<set>/{lib/gc,gctest}`와 링크 `~/rs-bundle/<set>`(첫 smoke와 같은 배치). 배포 기록: [deploy/](deploy/).
- 실행 스크립트(저장소 밖, 세션 스크래치 `agent_gc_smoke2/`): `run_smoke2.sh`(`cluster_run.sh -w 3600 -t gc-smoke2-<시도> -- timeout -s KILL 500 bash test/cells_gc.sh <로그> <셀> gc rs 1 1 DRIVER=gin_mi <셀 env>`, `LAUNCHER_ENV=-`), `deploy_smoke2.sh`, `build_mi_test_smoke2.sh`.
- 로그는 모두 `sed -E 's/([0-9]{1,3}\.){3}[0-9]{1,3}/<addr>/g'`를 거쳐 이 폴더에 옮겼다. 이 폴더에 IPv4 꼴 문자열과 관리망 주소는 0건이다 `[측정: grep]`.
- 시도마다 `rows_gc.py --stops`(STOP 규칙)와 `rows_gc.py`(열, 각 시도 폴더의 `trials.csv`)를 돌렸다. 아래 시간은 그 열과 줄의 `mono_ms`에서 다시 셈한 것이다.

## 빌드와 묶음

| 무엇 | md5 | 비고 |
|---|---|---|
| libnccl `gc_int3` | `6e34a97a5a6268eae66aa6719fdaeddc` | 통합 int3 그대로; 묶음 `gc_smoke2`(a1, a2) |
| libnccl `gc_int3f1` | `af8b0b84d6ea1f4fe6f293a6be190f2d` | + 고침 하나; 묶음 `gc_smoke2_a3`(a3, a4) |
| `gin_mi` | `cfce02c9c74ec4434737982940b6db5b` | `gin_mi.cu` 556804c0, 매크로 켬, 머리 digest 65fdf19b(첫 smoke와 같은 소스와 머리; nvcc 출력은 바이트로 재현되지 않음) |
| `gin_launcher` | `3af84d2a654cd0f55adb7003a1a74f44` | `gin_launcher.c` 5b62a1f5(커밋 9842ac7e), `launcher_msg.h` fb11b235; `build_launcher.sh all` 28 장면 762 검사 실패 0 `[측정, n 1]` |

두 노드 md5 같음, `ldd`는 libnccl이 묶음의 것, launcher는 libibverbs.so.1 `[측정: deploy/]`. 빌드 경고 0 `[측정]`.

## 시도마다

| 시도 | 라이브러리 | 셀 | 결과 | 근거 |
|---|---|---|---|---|
| a1 | `6e34a97a` | (1) 장애 없음 + 예비 프로세스 | 통과 | [a1/raw/](a1/raw/) |
| a2 | `6e34a97a` | (2) kill rank 3 | 실패. 판정, 펜스, 활성화까지 됨. rank 0이 예비 프로세스의 UD REJOIN을 REFUSE로 되풀이 답함(아래 고침), 20 s 뒤 hold 시한, FALLBACK, rank 3 거절. 생존 rank 끝 코드 4 | [a2/raw/](a2/raw/) |
| a3 | `af8b0b84` | (2) kill rank 3 | 통과. 복원, 데이터 같음 | [a3/raw/](a3/raw/) |
| a4 | `af8b0b84` | (1) 장애 없음 + 예비 프로세스 | 통과(고친 라이브러리로 셀 (1) 다시) | [a4/raw/](a4/raw/) |

두 셀 모두 통과해 시도 넷에서 멈췄다(한도 여섯). 마지막 라이브러리 `af8b0b84`에서 두 셀이 모두 통과했다 `[측정, 셀마다 n 1]`.

## 고친 것 (a2 → a3)

- **본 것** `[측정: a2/raw/gc4_kill3_ow_gc_n1_r0.log]`: `GIN/RC: rank 0: answered a REJOIN of rank 3 with REFUSE over UD`,
  `GIN/RS: rank 0: a REJOIN of rank 3 refused (the liveness READ QP's CONNECT toward the spare's failed (gen 1048577)); its spare dials again`(200 ms마다 되풀이).
  rank 0의 READ 요약에 `refused_lineage=1`. 예비 프로세스 쪽: `rank 0 answered the REJOIN with REFUSE over UD (try 1): sent again` → 다시 보냄 → 시한 뒤
  `rank 0 answered the REJOIN with FAIL: it is gone for this restore`, kv `resume_rc=2 resume_ms=21346.0`.
- **까닭** `[소스]`: UD REJOIN을 받는 단계(`gdakiCtrlRjAcceptStep`, 2a-2-C 2단계)가 감시 스레드에 생존 READ QP의 CONNECT를 청하고 그 답을 기다린 뒤 REJOIN_ACK를 보낸다.
  그 CONNECT를 helper의 넘기기(`gdakiProbeHandHelper`, 감시 스레드 고침 3)가 lineage로 거른다: 청한 incarnation이 CURRENT가 아니면 거절(RTS 금지). 그런데 ln4는 알려진
  incarnation을 REJOIN_ACK를 보낸 **뒤에** 올린다(`gdakiRsRejoinAccept`의 `e->knownInc = m.pad`). 그때까지 lineage는 HOLD_WAIT(dead 0, known 0)라 incarnation 1은 FUTURE이고,
  CONNECT는 늘 거절된다. 두 조각은 따로 시험됐고, CPU 시험의 가짜 감시 스레드는 넘기기 helper 몸을 비워 두어 이 조합을 부르지 않았다.
- **고침**(최소, 호스트 파일, `#if !NCCL_GIN_CTRL_TCP` 안의 page와 ring 영역; [../../impl/gc_layer_smoke2fix.diff](../../impl/gc_layer_smoke2fix.diff) 52줄, +14/−1):
  `gdakiCtrlPeerProbe::rjAccInc`(페이지 mutex 아래)를 두고, 받는 단계가 CONNECT를 청하기 바로 앞에 `m.pad`를 적는다. helper의 lineage 거름은 CURRENT, 또는
  "FUTURE이고 HOLD_WAIT이며 incarnation = dead + 1 = 받는 중인 incarnation"을 받는다. 다른 CONNECT(옛 incarnation, 다른 미래 incarnation)는 전처럼 거절한다.
  ln4의 known incarnation을 올리는 때는 바꾸지 않았다.
- 고친 뒤: `syn`, `unit` 두 빌드, 빌드 넷, `pre`, `sites`, `ident` 다시 통과(notes_int3.md 검사 표). a3에서 세 생존 rank 모두 `the REJOIN of rank 3 (incarnation 1) taken over UD` `[측정]`.

## 셀 (1) 장애 없음 + 따뜻한 예비 프로세스 (a1, a4)

| 무엇 | a1 | a4 | 줄 |
|---|---|---|---|
| go 파일까지의 기다림 | 2 818.9 ms | 2 819.5 ms | launcher `spare wait-for matched after … ms (incarnation 1): spawning` |
| 띄운 뒤 HELLO | 406.3 ms | 397.3 ms | `spawned spare said HELLO (spawn 1, incarnation 1, …, after … ms)` |
| `spare_ready`, READY | 있음 | 있음 | 예비 프로세스 `GINRS spare_ready rank=3`, launcher `spare of rank 3 incarnation 1 is READY` |
| 예비 프로세스의 Resume | 41 없이 활성화 기다림 | 같음 | `ncclGinRestoreResume: waiting for the activation (…, at most 60000 ms)` |
| 생존 rank의 무장 | rank 0, 1, 2 각 29줄 | 같음 | `rank 3 armed at its stable checkpoint K` |
| 네 rank | `resume_rc=0`, 600 step, `xchg=ok`, `x_match=1`, `sig_exact=1` | 같음 | kv |
| STOP | `la_stop_n=0 la_qp_err_n=0`, 남은 프로세스 0 | 같음 | `rows_gc.py --stops`, meta `left=0` |
| 생존 READ | 1 032/1 032 성공, 중앙값 최대 78.9 µs, 최대 31 855.0 µs | 1 032/1 032, 79.1 µs, 30 935.2 µs | `probe summary` |

예비 프로세스의 끝 코드 137은 launcher shutdown의 `the unused spare of rank 3 incarnation 1 is SIGKILLed through its pidfd`다 `[측정]`. 첫 smoke의 두 결함(기록보다 먼저 뜸,
예비 프로세스의 조건 41)은 두 시도 모두 나지 않았다.

## 셀 (2) kill rank 3, 따뜻한 예비 프로세스가 복원 (a3, 통과)

시각은 줄의 `mono_ms`. 노드 사이는 실행기가 잰 시계 차로 옮긴 값(`rows_gc.py`의 `mono_xnode`, 왕복 0.169 ms)이다 `[측정, n 1]`.

| 단계 | 시간 | 줄(정확한 글, 앞부분) |
|---|---|---|
| kill | 0 | 실행기 `GINRS killed rank=3 node=sunny pid=… which=first` |
| kill → 판정 | 0.312–0.423 ms(생존 셋의 범위), 판정 퍼짐 0.111 ms | `GIN/TS: rank 0: rank 3 judged dead (cause=FIN)` (셋 모두 `cause=FIN`) |
| 확인 창 | 판정 뒤 3.7 ms에 닫힘 | `confirm window for rank 3 opened by FIN W=20 over the device line`, `closed: unconfirmed (… READ1 +0.144, READ2 not done …)`, `confirm window of rank 3: table row 9; phase 1 reports it (the reaction stays ln4's socket rule …)` |
| hold 시작 | kill 뒤 4.8 ms(가장 이른 것) | `hold of rank 3 started: …, deadline in 19995 ms, HOLDING to buddy rank 2` |
| 펜스 | FENCE 보냄 → FENCED 113.1 ms | rank 2 `fence FENCING: FENCE sent to the launcher of node 1` → launcher `FENCE of rank 3 incarnation 0 from rank 2: SIGKILL sent through its pidfd` → `rank 3 incarnation 0 FENCED: the group ended 113.009 ms after SIGKILL` → rank 2 `fence FENCED (by FENCED from node 1)` |
| 활성화(launcher를 거침) | hold 시작 뒤 122.0 ms, LATER 0 | launcher `activation of rank 3 incarnation 1 handed to its spare (432 blob bytes)`, `… for rank 2: ACCEPTED`; rank 2 `every survivor holds rank 3: its spare activated (incarnation 1, 122.0 ms after this rank's hold start), 0 'later' answers` |
| UD REJOIN 받아들임 | hold 시작 뒤 134.0, 147.5, 158.8 ms(rank 0, 1, 2) | `the REJOIN of rank 3 (incarnation 1) taken over UD: record QP gen 1048577, liveness READ QP gen 1048577, REJOIN_ACK sent`; 예비 프로세스 `REJOIN_ACK of rank 0 taken over UD (try 1)` (셋 모두 try 1) |
| STATE(outbox, 링 길) | 0.1, 0.1, 18.7 ms(보내는 쪽), 받는 쪽 0.5–0.7 ms | `state of checkpoint 120 sent to rank 3's spare over the outbox (3008 bytes of log, 6 rkeys back, …, 0 step(s) waited for the ring)`; 예비 프로세스 `state of checkpoint 120 from rank 0 over the outbox` |
| 복원 끝 | 판정 → 게시 186.2 ms, kill → 게시 186.5 ms; hold 최대 181.7 ms | `rank 3 restored as incarnation 1 (on time; 186.2 ms after the hold start, …)`; 예비 프로세스 `restored as incarnation 1 from checkpoint 120 (blob 24 bytes); the communicator is armed`, 그 뒤 `the records go on the ring from now (live)` |
| 데이터 | 다섯 프로세스 `x_match=1`, `sig_exact=1`, 600 step, `xchg=ok`; 열 `data_equal=1`, `ow_data_equal=1` | kv, `trials.csv` |
| STOP | `la_stop_n=0 la_qp_err_n=0`, 남은 프로세스 0 | `rows_gc.py --stops` |

- **무엇이 판정했나.** ln4의 증인 소켓 규칙(FIN → 죽음)이 판정했다(`judge_causes=FIN:3`, 확인 창 판정 0, launcher EXITED 판정 0). 판정 표는 기록 길에서 아직 보고만 한다:
  확인 창은 READ2 전에 닫혀 `unconfirmed`, 표 9행으로 보고만 남겼다 `[측정]`.
- **launcher EXITED/LEFT 보고.** 죽은 incarnation 0에 대한 launcher의 `EXITED` 줄은 없다. FENCE가 kill 뒤 5.8 ms에 왔고(그룹은 그 뒤 113 ms에 끝남), launcher는 그 끝을 FENCED로 알렸다
  `[측정: la_exited_n=0, la_fenced_n=1]`. 그래서 맡김 글의 "EXITED 보고"는 이 시행에서 FENCED 보고로 나왔다. LEFT는 끝에서 `rank 3 incarnation 1 left (LEAVING, then the group ended)`
  (복원된 incarnation)로 나왔다 `[측정]`. FIN이 그룹 끝보다 113 ms 앞서는 까닭(CUDA 프로세스의 정리 시간)은 `[추론]`이다.
- **예비 프로세스 쪽 시간.** HELLO는 띄운 뒤 384.0 ms, 활성화는 188.5 ms(`spare_activate_ms`), 활성화 뒤 게시까지 63.7 ms, 예비 프로세스의 `resume_ms=1339.8`(READY 기다림 포함) `[측정]`.
  활성화 뒤 다음 예비 프로세스(incarnation 2)를 곧바로 띄웠고 509.7 ms 뒤 HELLO, 끝에 shutdown이 SIGKILL했다.
- **끝의 launcher 줄.** `record QP of rank 3 (incarnation 1, generation 1) lost: the QP reported an error`가 rank 3 incarnation 1의 LEAVING과 LEFT 뒤에 한 번 나왔다. STOP 규칙(첫 "is leaving" 전, 대상 밖 rank)에 들지 않는다 `[측정]`.

## a2(실패)에서 잰 것

kill → 판정 0.307–0.376 ms(셋, `cause=FIN`), FENCE → FENCED 115.4 ms, 활성화 hold 시작 뒤 124.0 ms(LATER 0) `[측정, n 1]`. rank 1, 2는 예비 프로세스가 rank 0의 답을 기다리는 동안 REJOIN을
받지 않았다(예비 프로세스는 rank 0부터 차례로 답을 기다림 `[추론: 예비 프로세스 줄이 rank 0의 답만 있음]`). 시한 20 s 뒤 FALLBACK, rank 3 거절, 생존 rank `exit=4`, `x_match=0`.
그 뒤 rank 1의 `GIN/LN: … LEFT of rank 3 incarnation 1 from node 1 is not this lineage's (FUTURE or STALE)` 한 줄.

## 남은 것과 요청 (고치지 않음)

- 생존 rank의 제어 요약 `witness_conns=2`(복원 뒤 rank 3의 증인 소켓이 요약 때 세지지 않음), 열 `witness_pairs=9`/12. 다시 걸기 줄(`unknown, re-dialled`)은 셋 모두 있다. 다시 걸기가 끝났는지 `[미확인]`.
- `tcp_record_bytes`: a3 생존 rank 5 616–7 488 B(rank 1, 2는 1 872 B 하나 더), 복원된 rank 3은 0. 장애 없는 셀은 rank마다 7 488 B(합 29 952). 링 live 전 기록과 복원 뒤의 것이 무엇인지 `[미확인]`.
- 낡은 줄 글(라이브러리 쪽, 이 고침 밖): `first pairing over UD started … (the records stay on the helper socket until phase 2a-2-B)`, `table row 9; phase 1 reports it (the reaction stays ln4's socket rule until phase 2a-2 moves the records off the socket)`.
- launcher(요청): FENCE가 그룹 끝보다 먼저 오면 EXITED는 나오지 않는다. 채점이 "launcher 보고"를 EXITED로만 세면 이 셀의 `kill_judge`를 다시 볼 것.
- 아직 실제 NIC에서 돌지 않은 것: 다른 장애 주입(SIGSTOP, RST, fd 자식, 관리망 끊김, 시험 스위치), 확인 창이 READ2까지 가서 판정하는 경우, `gct`/`gcp`, 채점.
