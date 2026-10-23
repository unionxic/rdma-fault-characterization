# notes_test.md — gin-control 시험 쪽(실행기, 채점기)

> **읽는 법(2026-10-23 표시).** 시간순으로 덧붙인 작업 기록이다. "단계"부터 "고침 (독립 리뷰 REVIEW_TEST 반영, 2026-10-17)"까지는 2026-10-17 초안과 그 고침의 기록이고(커밋 `afc164ff`, `4eadfe49`),
> 그 안의 "TODO 목록", "남은 `todo`", "메인 세션이 적을 것"은 그때 기준이라 지금 할 일로 읽지 않는다. 그 뒤 날짜 붙은 절이 차례로 이어지고 마지막 절이 가장 새 기록이다. "파일" 표만 2026-10-24까지 고쳐 왔다.
> 지금 상태와 할 일은 [EXPERIMENT.md](../../EXPERIMENT.md) 11절, 셀과 예측의 기준은 EXPERIMENT.md 3, 7, 8절과 `cells_gc.json`, `predictions_gc.csv`, 빌드와 실행, 채점 경로는 [NOTES.md](../../NOTES.md)에 있다.

[../../EXPERIMENT.md](../../EXPERIMENT.md) 3, 7, 8, 9.3, 9.8, 9.9절의 시험 쪽이다. gin-mirror의 시험 쪽(`../../../mirror/impl/test/`)을 틀로 썼다.
라이브러리 코드, 빌드, 클러스터 실행은 없다. 실행한 것은 로컬 Python 자체 시험과 `bash -n`, `check_cells_gc.py`뿐이다.

## 단계 (처음에 적은 계획)

1. `cells_gc.json`: 7절 27행, 셀마다 빌드 키, env, 주입, n, 대조 팔, 찾는 키
2. `check_cells_gc.py`: 3절 찾는 키 31개와 7절 27행을 셀 파일과 맞춰 봄
3. `predictions_gc.csv`: 3절 판정식을 기계가 읽는 꼴로(문턱은 3절 원문, 모르는 것은 `TODO`)
4. `launcher_gc.sh`: 노드마다 launcher 띄우기, 준비 확인, pid와 시작 시각, 끄기(기록한 PID만)
5. `run_gc.sh`: `run_mi.sh` 위에 launcher, 9.9절 주입, `active_mtu`, RNR 수, 끄는 차례
6. `cells_gc.sh`, `hold_gc.sh`, `chain_gc.sh`, `run_cost_gc.sh`: 셀, hold, 사슬, 비용
7. `rows_gc.py`: 9.3절 열
8. `score_gc.py`: 제외, STOP 줄, smoke와 pilot 따로, `SCORE.md`, `trials_scored.csv`
9. `test_rows_gc.py`: 합성 시행 일곱 꼴로 자체 시험(로컬 Python)
10. `deploy_gc.sh`: `deploy_mi.sh` 꼴, 새 빌드 키와 launcher
11. `bash -n`, `check_md.py`, 이 파일의 나머지(줄 꼴, TODO, 11, 12절 문장)

모두 끝냈다.

## 파일

| 파일 | 하는 일 |
|---|---|
| `cells_gc.json` | 7절 28행(`rows`; 2026-10-24 GPU hang 반례 셀 `gc4_gpuhang12000_ctx1_fence`를 더하기 전 27행, 2026-10-23 GPU hang 셀과 `gc4_kill3_noreport_nofdhold`를 더하기 전 25행), cell@build 26개(2026-10-24 전 25개, 그 전 23개; `cells`: env, 주입, n, 대조 팔, 찾는 키, 시행 한도), 본 실행 hold C1–C3, C5–C11과 pilot hold P0–P4, 회귀(gin-mirror `cells_mi.json`의 비용 밖 hold 여덟을 `@gc`로, `@gct`는 `regression.builds.gct.cells`의 `mi4_kill3_ow` 하나), 비용 가족 probe의 한 쌍, 로컬 항목. 2026-10-22 셀 줄임 전에는 27행, 27개, C1–C11(아래 "셀 줄임" 절) |
| `check_cells_gc.py` | 셀 파일과 예측 표를 EXPERIMENT.md 3, 7절에 맞춰 봄(행 수, 셀 이름, 빌드, n, 찾는 키마다 셀 하나 이상, 셀마다 예측 하나 이상, 회귀 빌드의 `cells` 목록) |
| `predictions_gc.csv` | 3절의 31행(2026-10-24 `gpuhang_ctx1_fence_restore`를 더하기 전 30행, 2026-10-23 `gpuhang_fence_restore`, `fdhold_sock_helper_stall`을 더하기 전 28행, 2026-10-22 셀 줄임 전 31행). 열은 gin-mirror의 `id,predicted,cells,acceptance`에 `per_trial,k_required,n_planned,control_arm,basis,todo`를 더함 |
| `remote_gc.sh` | 원격 셸에 넘기는 명령을 한 번만 따옴표로 쌈(`rcmd`, `pcmd`, `sunny_sh`), 공용 읽기 질의(`MTU_Q`, `RNR_Q`, `GID_PROBE`)와 IPv4 가림 식 |
| `launcher_gc.sh` | launcher 하나(start, stale, info, mark, table, stop). 0700 소켓 디렉터리(시작마다 새 경로), `--tc`, 예비 프로세스 옵션을 그대로 넘김, 낡은 소켓이나 프로세스면 띄우지 않음(exit 3), 기록한 PID와 시작 시각에만 신호, 준비 실패 때 스스로 끔 |
| `run_gc.sh` | 시행 하나. 9.9절 주입, 시행마다 launcher 띄우기와 끄기(예비 프로세스 명령과 환경 포함), 예비 프로세스 로그 따라 읽기, 시행 표지, 노드 시계 차, ss 스냅숏, `active_mtu`, RNR 카운터, 끄는 차례 |
| `gate_proc_gc.py` | `gate_fenced` 예측의 실제 프로세스 시험(CPU만): main thread가 먼저 끝나는 자식, 따로 잰 Z와 pidfd 시각 |
| `cells_gc.sh`, `hold_gc.sh`, `chain_gc.sh` | 셀의 n번, hold 하나(8절의 STOP), hold 사슬(`cluster_run.sh` 안) |
| `run_cost_gc.sh` | 비용 가족 probe의 실행 하나(팔 `probe-off`, `probe-on`은 `gcp`, `tcp`는 `gctp`; 2026-10-22부터 셀 파일은 `probe-off`, `probe-on`의 `lat4k`만 부름) |
| `rows_gc.py`, `score_gc.py` | 시행별 열, 채점. gin-mirror의 `rows_mi.py`와 `score.py`를 고치지 않고 불러 씀 |
| `test_rows_gc.py` | 합성 로그 자체 시험 |
| `deploy_gc.sh` | 두 노드의 새 묶음 `~/rs-bundle/<RS_SET>/`에 라이브러리 다섯, driver, launcher |

## 설계에서 정한 것과 어긋남

- **launcher의 범위.** 2026-10-22부터 시행마다 노드마다 하나다(조율 세션 결정; EXPERIMENT.md 5, 8, 9.5절; 아래 "launcher 데몬의 예비 프로세스" 절).
  그 전(2026-10-17 결정)에는 hold마다 하나였고 시행 시작 때 등록 표가 비었는지 보았다(exit 7). 비용 실행(`run_cost_gc.sh`)은 처음부터 실행마다였다.
- **launcher env는 셀마다.** 시행의 launcher가 셀의 `launcher_env`로 뜬다(`hold_gc.sh`가 `LAUNCHER_ENV`로 넘김). hold의 env 섞음 거절은 없앴다.
  `NO_EXIT_REPORT` 셀(`gc4_fdhold_sock_kill3_noreport`)은 hold C6에 혼자 그대로다.
- **회귀 셀은 gin-mirror의 이름, env, n 그대로.** `run_gc.sh`가 `run_mi.sh`의 kill 갈래(트래픽, 체크포인트 멈춤 hook, after_stable, seed의
  단계 kill, `SPARE_KILL_FIRST`)를 그대로 지닌다. seed 뽑기의 머리 글자도 `gin-mirror|`로 두어 같은 seed가 같은 kill 단계를 낸다.
- **둘째 죽음은 빼지 않는다.** 2026-10-17 메인 세션 결정(REVIEW_TEST B3)으로 `@gct`, `@gc` 모두 gin-mirror 8절의 사전 등록 규칙을 쓴다: 둘째 kill이
  다시 무장 전, 첫 복원 실패, 다시 무장 없음은 조건 불충족으로 센다. 8절 초안의 그 제외 문장은 메인 세션이 고칠 것(아래 "고침" 끝의 8절 목록).
- **3절에 수치가 없는 것.** 판정식의 문턱은 모두 3절 원문에서 옮겼다. 3절에 수치나 목록이 없는 여섯은 리뷰 D3–D8의 권고 값을 넣고
  `predictions_gc.csv`의 `todo` 열 표시를 남겼다(아래 "고침" 끝의 3절 목록).
- **셀 값의 자리 표시.** 3절과 7절에 없는 주입 매개변수(`DIE_RST` 3 000 ms, `RST_GAP` 시작 3 000 ms, 멈춤과 끊김 셀의 `STEPS`,
  `QP_ERR`, `CREDIT_STALL`, `DROP_UD` 값 꼴)는 `cells_gc.json`의 `todo`에 단계 이름과 함께 적었다.
- **떨어진 두 노드의 시각.** 같은 프로세스 안의 간격은 줄의 `mono_ms`, 같은 노드의 두 프로세스는 두 `mono_ms`, 노드 사이는 두 `mono_ms`를
  실행기가 시행 앞뒤로 잰 시계 차(한 ssh 세션의 왕복 열 번 가운데 가장 짧은 것; 왕복 시간을 함께 남김)로 rain 시계에 옮겨 견준다(`mono_xnode`).
  시계 차가 없거나 줄에 `mono_ms`가 없을 때만 수신 시계다. 열 `kill_judge_clock`, `judge_spread_clock`, `publish_clock`이 어느 쪽인지 적는다.

## 라이브러리 쪽이 낼 줄 (정확한 문자열)

`rows_gc.py`가 읽는다. 모든 줄 끝에 ` mono_ms=%.3f`(프로세스의 CLOCK_MONOTONIC, ms)가 붙는다. "있음"은 지금 트리에 있는 줄, `TODO(pN)`은
N단계가 이 꼴 그대로 내야 하는 줄이다. `%s`는 공백 없는 낱말이다.

| 줄 | 꼴 | 상태 |
|---|---|---|
| 죽음 판정 | `GIN/TS: rank %d: rank %d judged dead (cause=%s)` | 있음(ln4). rdma 빌드의 원인은 `EXITED`, `FIN+STALE`, `FIN+NORESP`, `REMACC+FIN`, `NORESP`, `LINKDOWN` `TODO(p1)` |
| 멈춤 판정 | `GIN/RC: rank %d: rank %d (incarnation %u) judged stalled (liveness stall judged (STALL\|STALL_HELPER)); ...` | 있음(1단계). 3단계가 뒤 글을 바꿔도 앞은 그대로 |
| 증인 닫힘 | `GIN/TS: rank %d: socket to rank %d closed cause=%s` (`FIN`, `ECONNRESET`) | 있음(ln4) |
| 상태 페이지 | `GIN/RC: rank %d: status page up (%u B in use, probe_ms=%d stall_ms=%d W=%d)` | 있음(1단계) |
| 확인 창 열림 | `GIN/RC: rank %d: confirm window for rank %d opened by FIN\|RST W=%d` | `TODO(p1)` |
| 확인 창 끝 | `GIN/RC: rank %d: confirm window for rank %d closed: alive\|STALE\|NORESP\|REMACC\|unconfirmed` | `TODO(p1)` |
| 의심 | `GIN/RC: rank %d: rank %d suspected (kind=watch\|helper stale_ms=%.1f)` | `TODO(p1)` |
| READ 시한 | `GIN/RC: rank %d: probe of rank %d timed out (no CQE in %d ms)` | `TODO(p1)` |
| READ 요약 | `GIN/RC: rank %d: probe summary peer=%d reads=%u ok=%u remacc=%u noresp=%u timeout=%u gen=%u lat_med_us=%.1f lat_max_us=%.1f beat_gap_max_ms=%.1f torn=%u after_end_reads=%u after_end_ok=%u` (끝낼 때, 상대마다; `after_end_*`는 상대의 BYE, LEFT, 판정 뒤 READ이고 `reads`, `ok`에 든 채 따로 셈) | `TODO(p1)` |
| 증인 잃음 | `GIN/RC: rank %d: witness of rank %d lost; liveness alive` (판정 표 8행) | `TODO(p1)` |
| 시험 스위치 | `GIN/TS: rank %d: test switch DIE_RST: linger 0 on %d socket(s); SIGKILL now` | `TODO(p1)` |
| | `GIN/TS: rank %d: test switch RST_GAP: %d socket(s) reset, listener closed for %d ms` | `TODO(p1)` |
| | `GIN/TS: rank %d: test switch FD_HOLDER=sock\|uverbs: child gin_fdhold pid=%d holds %d fd(s)` (증인을 끈 셀은 0) | `TODO(p1)` |
| | `GIN/RC: rank %d: test switch FREEZE_PAGE=%d[:helper]: %s frozen` (멈춤 시작) | `TODO(p1)` |
| | `GIN/TS: TEST socket mute on\|off rank=%d peers=%d` | 있음(gin-harden) |
| 제어 요약 | `GIN/RC: rank %d: control summary tcp_record_bytes=%llu tcp_data_bytes=%llu tcp_conns=%u witness_conns=%u records_lost=%u records_dup=%u repairs=%u sendq_deferred=%u sendq_max=%u rnr=%u async=%u active_mtu=%u` (끝낼 때와 확정 체크포인트마다, 모든 프로세스; 채점은 프로세스마다 마지막 줄; `tcp_conns`, `witness_conns`는 그 줄 때 열려 있는 수) | `TODO(p2)` |
| 링 요약 | `GIN/RC: rank %d: ring summary peer=%d gen=%u sent=%llu received=%llu lost=%u dup=%u` | `TODO(p2)` |
| 짝 맺기 | `GIN/RC: rank %d: PAIR(record, gen %u) to rank %d (local ERR)` | `TODO(p2)` |
| | `GIN/RC: rank %d: record QP\|liveness READ QP to rank %d re-paired (gen %u)` | `TODO(p2)` |
| | `GIN/RC: rank %d: REJOIN to rank %d resent (try %u)` (예비 프로세스) | `TODO(p2)` |
| | `GIN/RC: rank %d: test switch QP_ERR: record QP to rank %d moved to ERR` | `TODO(p2)` |
| | `GIN/RC: rank %d: test switch CREDIT_STALL: no RECV re-posted for %d ms` | `TODO(p2)` |
| | `GIN/RC: rank %d: test switch DROP_UD: the REJOIN datagram to rank %d dropped` | `TODO(p2)` |
| REJOIN 받아들임 | `GIN/RS: rank %d: rank %d's spare rejoined as incarnation %u (...)` | 있음(ln4) |
| 펜스 | `GIN/RC: rank %d: rank %d (incarnation %u) fence FENCING: FENCE sent to the launcher of node %u` (짝) | `TODO(p3)` |
| | `GIN/RC: rank %d: rank %d (incarnation %u) fence FENCED (by FENCED\|EXITED from node %u)` (짝, 펜스 낱말이 선 때) | `TODO(p3)` |
| 바뀐 칸 | `GIN/RC: rank %d: window check after the fence\|judgement of rank %d: changed=%u cells` (생존 rank마다) | `TODO(p3)` 또는 driver |
| 리뷰 1. 판정 줄 | rdma 빌드의 `judged dead (cause=%s)`의 원인은 공백 없는 낱말 하나(`EXITED`, `FIN+STALE`, `FIN+NORESP`, `REMACC+FIN`, `NORESP`, `LINKDOWN`). 멈춤은 `judged stalled` 줄 하나만 내고 DEAD 줄을 함께 내지 않음 | `TODO(p1)` |
| 리뷰 2. 확인 창 | 열림 줄의 시각이 t_F(증인 FIN이나 RST를 본 때)이고 `W=`를 실음; 닫힘 줄은 `alive`, `STALE`, `NORESP`, `REMACC`, `unconfirmed` 가운데 하나; 둘 다 끝에 ` mono_ms=` | `TODO(p1)` |
| 리뷰 3. READ 요약 | 위 행의 `after_end_*`; `beat_gap_max_ms`는 첫 성공 READ부터 상대의 끝 전까지; `torn`은 짝수 `ver` 줄의 찢김 수; 처음 세대 `gen`을 PAGEUP 줄이나 첫 짝 맺기 줄에 실음(기록 QP 오류 셀의 세대 + 1 확인) | `TODO(p1)` |
| 리뷰 4. 제어 요약 | 위 행; `tcp_record_bytes`, `tcp_data_bytes`는 `gdakiCtrlSend`의 TCP 갈래에서 실제 보낸 바이트; `tcp_conns`는 이 계층이 연 TCP 소켓 수를 증인 등록과 따로 셈; 받는 쪽 상대별 TCP 수신 바이트 `tcp_rx_bytes_peer<p>=`; `async`는 `async_rec=`, `async_read=`, `async_la=`로 나눔; kv에 `active_mtu=` | `TODO(p2)` |
| 리뷰 5. launcher 소켓 끊김 | `GIN/RC: rank %d: launcher Unix socket closed (%s)` (rank나 예비 프로세스가 launcher 연결을 잃을 때; 8절 STOP_launcher의 "그 Unix 소켓이 끊김") | `TODO(p3)` |
| 리뷰 6. fd를 쥔 자식 | 자식은 넘겨받은 fd 밖을 모두 닫고 0–2를 `/dev/null`로 돌림(rank 3의 출력 관을 쥐지 않음); fork 줄은 지금 꼴, 증인이 꺼지면 `holds 0 fd(s)` | `TODO(p1)` |
| 리뷰 7. 시험 스위치 시작과 끝 | `DIE_RST`는 SIGKILL 직전 줄; `FREEZE_PAGE`는 시작 줄(위 꼴)과 끝 줄 `GIN/RC: rank %d: test switch FREEZE_PAGE: beats resumed`; `RST_GAP`은 닫음 줄(위 꼴)과 다시 엶 줄 `GIN/TS: rank %d: test switch RST_GAP: listener reopened`; 줄마다 시작 기준(첫 무장 확정 체크포인트 뒤 `after_ckpt_ms=%d`) | `TODO(p1)` |
| 리뷰 8. 활성화와 무장 줄 | rdma 빌드에서도 지금 글 그대로: `GINRS step rank=R step=S released=0`, `rank P armed at its stable checkpoint K`, `every survivor holds rank P: its spare activated (…), N 'later' answers`, `restore round with rank P published`, `rank P restored as incarnation I`, `hold of rank P started`, `is given up`; 활성화 줄의 'later' 수는 launcher가 대신 답한 LATER 수 | `TODO(p3)` |
| 리뷰 9. 펜스와 바뀐 칸 | 위 FENCING, FENCED 행; 바뀐 칸 줄은 무엇과 견준 수인지 싣는다(`against=snapshot_at_judgement`) | `TODO(p3)` |
| 리뷰 10. launcher 표 | `GIN/LA: node %u: table: %d registered, %d spares` (등록 표가 바뀔 때마다). 그 전까지 `launcher_gc.sh table`이 등록, EXITED, FENCED, left, HELLO, ended 줄로 표를 읽음. 2026-10-22부터 launcher가 시행마다라 시작 검사에는 쓰지 않음(보고만) | launcher 쪽 TODO |
| 리뷰 11. 복원 끔과 fail-fast의 생존 확인 | `NCCL_GIN_RESTORE=0`, `FAULT_POLICY=failfast`인 살아 있는 RST 셀에서도 상태 페이지, READ, 확인 창이 돌고 PAGEUP 줄을 냄(돌지 않으면 그 셀은 아무것도 재지 않음) `[미확인]` | `TODO(p1)` |
| 리뷰 12. 시계 | 모든 `mono_ms=`가 CLOCK_MONOTONIC(launcher는 그렇다; rank 쪽 `gdakiQ4MonoMs`의 몸체는 diff 밖 `[미확인]`) | `TODO(p1)` 확인 |
| 관문 프로그램 | `../gate_fenced.cc`에 `--pid <pid>` 모드: 실제 pid에 `gdakiRsActExamine`(옛 관문)과 `gdakiCtrlActGate`(FENCED)를 걸고 `old GO mono_ms=%.3f`, `FENCED GO mono_ms=%.3f`를 냄(`gate_proc_gc.py --gate-bin`) | 그 파일 주인의 TODO |

launcher의 줄(`GIN/LA: node %u: ...`)은 `../launcher/gin_launcher.c`에 이미 있는 그대로 읽는다(EXITED, "exited; EXITED not sent", FENCE의
SIGKILL, FENCED, `(STOP_launcher)`, "refused to signal", 활성화 LATER, ACCEPTED, REFUSED, QP 잃음, "is leaving", "listening on its Unix socket").

## TODO 목록 (라이브러리 쪽과 메인 세션)

1. `TODO(p1)` 위 표의 1단계 줄: 확인 창 둘, 의심, READ 시한, READ 요약, 증인 잃음, 시험 스위치 넷의 줄, rdma 빌드의 원인 이름.
2. `TODO(p1)` 시험 스위치의 값과 시작 기준: `DIE_RST=<ms>`, `RST_GAP=<시작>:<길이>`, `FREEZE_PAGE`의 시작 시각(셀 파일은 첫 무장 체크포인트 뒤를
   가정). `FD_HOLDER=sock`에서 증인이 꺼져 있을 때 넘길 소켓이 없음을 줄의 `holds 0 fd(s)`로.
3. `TODO(p2)` 제어 요약, 링 요약, 짝 맺기 줄 셋, 시험 스위치 셋의 줄과 값 꼴(`QP_ERR=<ms>:<peer>`, `CREDIT_STALL=<시작>:<길이>`,
   `DROP_UD=rejoin:<수>`), 비동기 이벤트 수 `async=`(8절의 STOP_async).
4. `TODO(p3)` 펜스 줄 둘과 바뀐 칸 줄, launcher 소켓 끊김 줄. rank와 예비 프로세스가 launcher 소켓을 `NCCL_GIN_CTRL_LAUNCHER_SOCK`, 노드 번호를
   `NCCL_GIN_CTRL_LAUNCHER_NODE`로 읽는지(launcher 헤더의 `GL_SOCK_ENV`, `GL_NODE_ENV`). 같은 rank의 둘째 예비 프로세스가 받는 화신 변수
   (`run_gc.sh`는 `NCCL_GIN_RESTORE_SPARE_INC=2`를 줌). rdma 빌드에서 예비 프로세스가 아직 `NCCL_GIN_RESTORE_SPARE_ADDR`, `_PORT`를 읽는지.
   비용 셀의 측정 모드가 launcher 짝 맺기를 요구하는지. 끝날 때 launcher의 QP 잃음 줄 가운데 무엇이 8절의 "시험 스위치 셀 밖의 launcher QP
   ERR"인지(지금 채점기와 hold는 같은 규칙: 이 시행의 `trial_start` 표지 뒤, 첫 "is leaving" 줄 전, 대상 rank 밖의 rank에서 난 것만 셈;
   8절에 이 규칙을 고정할 것).
5. `TODO(p4)` `build_gc.sh`에 `gctc` 라이브러리 단계(지금은 전처리 검사만). gc 트리 헤더로 driver(`gin_mi`, `gin_mi_nomacro`, `gin_ts2_mi`,
   `mr/ff`, `mr/hold`)를 빌드하는 스크립트(gin-mirror의 `build_mi_test.sh`는 자기 트리만 받음; 이 묶음에 없음).
6. `TODO(pilot)` W(정해지면 `cells_gc.json` `prereg.confirm_ms`), `gc4_none_probe`의 60 s에 맞춘 `STEPS`, 멈춤과 끊김 셀의 `STEPS`,
   9.9절 끝의 채점하지 않는 12 000 ms 멈춤 셀(hold P4, 셀 `gc4_stop12000_pilot`), NCCL 자신의 bootstrap TCP 소켓 수와 트래픽 중 그 소켓의
   보낸 바이트(`no_tcp_control`의 ss 조건), 비용 문턱의 퍼짐.
7. `TODO(prereg)` `predictions_gc.csv`의 `todo` 열 여섯 줄(아래 "고침" 끝의 3절 목록).
8. 이 환경에는 `shellcheck`가 없어 셸 스크립트는 `bash -n`만 통과했다.
9. `TODO(gate_fenced.cc)` 위 표의 관문 프로그램 `--pid` 모드. 그 전까지 `gate_fenced` 예측은 자료 부족이다.

## 자체 시험 실행

```
cd harness/gpu-initiated/gin_recovery/control/impl/test
python3 check_cells_gc.py                 # 셀 파일과 예측 표를 EXPERIMENT.md 3, 7절에 맞춰 봄
python3 test_rows_gc.py                   # 임시 폴더에 합성 시행을 만들고 지움
python3 test_rows_gc.py --keep <폴더>     # 그 폴더에 남김(SCORE.md, trials_scored.csv를 볼 수 있음)
```

합성 시행: 확인 창 판정 10, launcher 보고 판정의 정상 복원 10, READ 실패 판정 5, `(STOP_launcher)` 줄과 1 s 넘는 hold 1, 제외 둘(launcher
준비 안 됨, 확정 체크포인트 전 kill)과 smoke 1, 같은 rank의 둘째 kill 둘(무장 줄 뒤, 앞), 찢긴 줄 읽기가 있는 장애 없는 시행 10과 깨끗한
장애 없는 시행 5, 원인이 FIN 하나인 판정 1, `gate_fenced` 10줄. 첫 초안 때(2026-10-17) 검사 39개, 실패 0.

고침 뒤(2026-10-17): 위에 더해 노드마다 다른 시계와 sunny 줄의 수신 지연 4 ms(시계 차가 없는 시행 하나), 등록 표, 시행 표지 앞의 앞 시행
줄, `(STOP_launcher: …)`와 QP 잃음 시행, 박동 멈춤 셀 5, RST 간격 셀 15(50 ms 10, 300 ms 5), gin-mirror 둘째 죽음 시행 1, 실제 프로세스 관문
10회(`gate_proc_gc.py`), 원격 MTU 명령과 hold 꼬리 검사(로컬 bash, ssh 없음). 결과는 아래 "고침" 기록 13.

## EXPERIMENT.md에 넣을 문장 (메인 세션이 11, 12절에 붙일 것)

> 반영됨(2026-10-23 확인, EXPERIMENT.md 읽기만): 11절의 시험 쪽 초안 줄(자체 시험 39/39)과 12절 2026-10-17 시험 쪽 초안 행. 다시 붙이지 않는다.

11절 체크리스트(있는 줄 "실행기, 채점기, 셀 파일, 예측 표 파일"을 둘로 나눔):

```
- [x] 실행기, 채점기, 셀 파일, 예측 표 파일 초안(impl/test/: cells_gc.json 7절 27행, predictions_gc.csv 3절 31행, run_gc.sh,
  hold_gc.sh, launcher_gc.sh, rows_gc.py, score_gc.py, deploy_gc.sh) — 2026-10-17, 합성 로그 자체 시험 39/39 통과, 셸은 bash -n만,
  클러스터 실행 없음(impl/test/notes_test.md)
- [ ] 라이브러리 쪽 줄 꼴(notes_test.md의 TODO(p1)–TODO(p3))과 셀 값 TODO를 맞춘 뒤 실행기와 채점기의 독립 리뷰
```

12절 실행 기록(한 행):

```
| 2026-10-17 | 시험 쪽 초안. impl/test/에 셀 파일(7절 27행, cell@build 27개, 본 실행 hold C1–C11, pilot hold P0–P4, gin-mirror 회귀
hold 여덟을 @gct와 @gc로, 비용 가족 probe), 예측 표(3절 31행; 문턱은 3절 원문, 3절에 수치가 없는 여섯은 todo 열), 셀 대조 스크립트,
실행기(run_mi.sh 위에 노드마다 launcher, 9.9절 주입을 기록한 PID로만, active_mtu, RNR 카운터, rank의 BYE 뒤 launcher를 마지막에 끔), hold(8절의
STOP_launcher, STOP_rnr, STOP_mtu, STOP_async, STOP_left 더함), 행 추출과 채점기(gin-mirror의 rows_mi.py와 score.py를 고치지 않고 씀;
smoke와 pilot은 따로 셈), 배포 스크립트. launcher 범위는 5절대로 hold마다가 기본이고 시행마다도 고를 수 있음. 라이브러리가 아직 내지 않는
줄 꼴은 notes_test.md의 표가 정함(TODO(p1)–(p3)). 합성 로그 자체 시험 39/39 통과(로컬 Python), check_cells_gc.py ok, 셸 스크립트 bash -n
(shellcheck 없음). 빌드와 클러스터 실행 없음 | impl/test/notes_test.md, impl/test/cells_gc.json, impl/test/predictions_gc.csv |
```

## 고침 (독립 리뷰 REVIEW_TEST 반영, 2026-10-17)

단계(한 단계씩, 끝날 때마다 아래 기록에 한 줄):

1. `remote_gc.sh`(새 파일): 원격 명령 따옴표(`shq`), 작은따옴표 없는 `MTU_Q`, 가림 식; 네 스크립트가 씀 (B1)
2. `launcher_gc.sh`: 덧붙이기 로그, 시행 표지(`mark`), 등록 표(`table`), 준비 실패 때 스스로 끔, 한도 860 s (B4, D1, 고칠 것 5, 6)
3. `hold_gc.sh`: hold 범위만, 실패 때 두 노드 끔, hold 쪽 STOP 검사(두 꼴, QP ERR), MTU 뒤 비교, `gin_mrr_`, pilot 폴더 규칙 (B4, 5, 16, 17)
4. `run_gc.sh`: `SUBJECT_RANK`, 표 검사(exit 7), 표지로 자르기, 노드 시계 차, fd 자식 끄기, ss 스냅숏, 짝 kill 간격 (B2, 2–4, 6, 10, 12, 14)
5. `cells_gc.sh`, `chain_gc.sh`, `deploy_gc.sh`, `run_cost_gc.sh`: exit 7, hold 출력 IPv4 가림, 실행 표지, ssh 오류문 (15, nit)
6. `cells_gc.json`: 대상 rank, pilot 전용 셀, uverbs 스위치, preds 맞춤, 사전 등록 값 자리 (B2, 16, 19)
7. `rows_gc.py`: 노드 시계, launcher 조각, `--stops`, 새 열 (1, 2, 9, 10, 13, 14, 18)
8. `gate_proc_gc.py`(새 파일): 실제 자식 프로세스로 관문 시각을 따로 잼 (고칠 것 1)
9. `score_gc.py`: 둘째 죽음 제외 없앰, 자료 부족 규칙, 묶음 키, 설정 다름, 주입 전 체크포인트, pilot과 smoke (B3, 11–14, 16)
10. `predictions_gc.csv`: 열 바로잡기와 `todo` 여섯의 리뷰 권고 (7–10, D3–D8)
11. `check_cells_gc.py`: 예측 표 셀 열과 셀 파일 preds 대조 (19)
12. `test_rows_gc.py`: 막는 문제 넷의 합성 시험
13. `bash -n`, 자체 시험, `check_cells_gc.py`, `check_md.py`; 이 파일의 줄 꼴 표, 3절과 8절 목록

기록:

- 1: `remote_gc.sh` 만듦. 로컬에서 `rcmd "$MTU_Q" mlx5_0`의 shlex 나눔이 `[bash, -c, <MTU_Q 그대로>, _, mlx5_0]`이고 가짜 `ibv_devinfo`로 4096을 읽음 `[측정]`.
- 2: `launcher_gc.sh` 고침: 원격 명령은 `rcmd`/`pcmd`, 로그는 O_APPEND, `mark`와 `table`(launcher 줄로 읽은 등록 표), 준비 실패 때 스스로 `stop`(launcher PID가 없으면 기록한 timeout PID), 한도 860 s, 끈 뒤 로그 IPv4 가림. 합성 로그로 `table`이 열린 둘 → 0, `mark` 줄 확인 `[측정]`.
- 3: `hold_gc.sh` 고침: hold 범위만(시행 범위 갈래 뺌), `GC_CHAIN=1` 요구, pilot/smoke 폴더 규칙, `gin_mrr_` 남음 셈, launcher 준비 실패 때 두 노드 모두 `stop`, 시행마다 `rows_gc.py --stops`로 두 STOP 꼴과 시험 스위치 밖 QP 잃음, MTU 앞뒤 비교, RNR 줄에 증가량과 wall, 마지막 표지 뒤 STOP 줄, 비용 exit 6은 STOP_launcher, 회귀 T1/T2에 `BAR1_AT_GATE`. `bash -n` 통과.
- 4: `run_gc.sh` 고침: `SUBJECT_RANK` 먼저, launcher는 hold 기록만(없으면 exit 6, meta에 driver와 ctrl), 시작 때 등록 표가 비지 않으면 exit 7, `trial_start`/`trial_end` 표지와 앞 시행 끝 표지부터 자르는 조각, 한 ssh 세션 왕복으로 잰 노드 시계 차(앞뒤), ss 스냅숏 둘(수와 바이트만), fd 자식은 짝의 판정 줄 + 1 s(없으면 kill + 25 s) 뒤 같은 노드 시작 tick 검사로 끔, 짝 kill 간격은 잠든 뒤 돌며 기다림, CONT 때 Z/X는 없음, `BAR1_AT_GATE`, launcher env를 meta로. `bash -n`과 `RS_DRY_CONFIG=1` 줄 확인.
- 5: `cells_gc.sh` exit 7 → STOP_launcher; `chain_gc.sh`는 hold 출력 전체를 IPv4 가림(`sed -u`)으로 보내고 `GC_CHAIN=1`을 줌(rc는 `PIPESTATUS`); `deploy_gc.sh` 첫 ssh 표준 오류 숨김; `run_cost_gc.sh`는 `remote_gc.sh`의 GID 조회와 가림. 모든 `.sh` `bash -n` 통과.
- 6: `cells_gc.json`: 시험 스위치 셀 아홉에 `SUBJECT_RANK`(박동 멈춤 둘 3, RST 간격 셋 1, 기록 QP 1, credit 2, 관리망 끊김 둘 1), pilot 전용 셀 `gc4_stop12000_pilot@gc`(`pilot_cells`, hold P4), uverbs 셀의 스위치 글 `uverbs`, `gc4_kill3_ow`의 preds에서 복원 시간 예측을 뺌, `prereg`(W는 null, PROBE_MS 100). `check_cells_gc.py` ok.
- 7: `rows_gc.py` 고침: 노드 사이 간격은 meta 시계 차로 바꾼 mono(`mono_xnode`; 판정 퍼짐과 게시 시간도), launcher 조각은 STOP 셈만 전체 나머지는 `trial_start` 뒤, `--stops <stem>`, 새 열 `hold_after_restore_n`, `probe_timeout_n`, `witness_expected`, `ss_*`, `pair_gap_ms`, `ckpt_stable_before_inj`, `probe_ms_page`, READ의 `after_end_*` 뺌, 프로세스마다 마지막 제어 요약, `gate_proc` 줄(실제 프로세스)과 `gate_real`. 모듈 불러오기 확인.
- 8: `gate_proc_gc.py` 만듦: 실제 자식 프로세스(main thread만 raw exit, 둘째 thread 500 ms 뒤 끝냄), 따로 잰 `/proc` Z 시각과 pidfd 읽힘 시각, `--gate-bin`(gate_fenced.cc 쪽 `--pid` 모드, 그 파일 주인의 TODO)이 없으면 관문 열은 빈 값. 이 머신(커널 5.15)에서 3회: Z 0.39–0.40 ms, 둘째 thread 끝 500.04–500.52 ms, pidfd 500.69–501.17 ms `[측정; smoke, 본 실험 아님]`.
- 9: `score_gc.py` 고침: 둘째 죽음 제외(`rearm_ok`, `kill2_after_armed`) 없앰(@gct, @gc 모두), 이 실험의 키는 계획 n 미만이면 자료 부족, `build:` 묶음은 들어간 셀이 모두 계획을 채울 때만, launcher env, W, READ 주기 다름은 `config`, 짝 kill 간격 > 5 ms는 `inject_late`, 예비 프로세스가 있는 주입 셀 모두에 첫 체크포인트 전 제외, P0은 smoke, `costpilot*`은 pilot, 새 열을 `LIB_COLS`에. 모듈 불러오기 확인.
- 10: `predictions_gc.csv`: 관리망 끊김에 `rec_repair_n == 0`, 복원 시간의 LATER는 `la_later_n`, 증인 없는 kill에 `hold_after_restore_n == 0`, 제어가 관리망에 없음은 라이브러리 셈을 설정과 커널의 셈에 견줌(`witness_expected`, `ss_tx_delta_bytes`), READ 실패에 시한 줄 있음, `gate_fenced`는 실제 프로세스 열, kill 판정에 gin-mirror kill 셀 여덟(k = n − 1), 회귀(rdma)에 `ow_wait_held`, mirror 끔 회귀에 rs4 셋을 더함, 회귀 두 행에 둘째 죽음은 빼지 않음; `todo` 여섯은 리뷰 권고 값과 표시 그대로, `no_tcp_control`에 pilot TODO 하나 더함. `check_cells_gc.py` ok.
- 11: `check_cells_gc.py`에 예측 표 셀 열과 셀 파일 preds 대조를 더함. 커밋된 옛 두 파일에 돌리면 리뷰가 찾은 두 어긋남(복원 시간 예측과 `gc4_kill3_ow`, 회귀 gc의 kill 판정)을 FAIL로 냄, 지금 파일은 ok `[측정]`.
- 12: `test_rows_gc.py` 다시 씀: 노드마다 다른 시계와 sunny 줄의 수신 지연 4 ms, 막는 문제 넷(MTU 원격 명령의 shlex 나눔과 가짜 `ibv_devinfo` 4096, 박동 멈춤 셀과 RST 간격 셀의 판정 "맞음", 둘째 죽음 시행이 채점되고 다시 이미지 조건이 거짓, 두 STOP 꼴의 `--stops`와 hold 꼬리 검사와 등록 표), 실제 프로세스 관문 10회. 돌리다 리뷰 밖의 결함 하나를 찾아 고침: 펜스로 끝난 대상(실행기 kill 없음)을 gin-mirror 열이 살아 있는 rank로 쳐서 펜스 셀 셋의 `ow_data_equal`이 늘 0 → `rows_gc.py fenced_subject`. 결과 62 checks, 0 failed(passed).
- 13: 마무리 확인. `bash -n` 여덟 스크립트 통과, `check_cells_gc.py` ok, 자체 시험 62 checks, 0 failed(passed; 로컬 Python, 클러스터와 ssh 없음),
  `tools/check_md.py`는 아래. 시험 쪽 파일에 IPv4 꼴 문자열 0건(grep).

### 리뷰 항목별 반영

| 항목 | 반영 | 비고 |
|---|---|---|
| B1 MTU 원격 따옴표 | 함 | `remote_gc.sh`의 `rcmd`; 작은따옴표 없는 `MTU_Q`; GID, RNR, PIDREC, INJPY, launcher 쪽 원격 명령도 같은 길 |
| B2 시험 스위치 셀의 대상 | 함 | `SUBJECT_RANK` 아홉 셀; 합성 시험에서 박동 멈춤과 RST 간격 예측이 "맞음" |
| B3 둘째 죽음 제외 | 함 | 메인 세션 결정: `@gct`, `@gc` 모두 제외 없음(gin-mirror 8절); `kill2_after_armed`도 보고만 |
| B4 STOP_launcher 두 꼴, QP ERR | 함 | hold가 `rows_gc.py --stops`(채점기와 같은 규칙), 마지막 시행 뒤 꼬리 검사 |
| 고칠 것 1 `gate_fenced` | 시험 쪽만 함 | `gate_proc_gc.py`(실제 프로세스, 따로 잰 pidfd), `gate_real`; 관문 시각은 `../gate_fenced.cc`의 `--pid` 모드가 내야 함(이 폴더 밖) |
| 2 노드 사이 시각 | 함 | 시계 차(한 ssh 세션, 왕복 최소)로 `mono_xnode` |
| 3 fd 자식의 출력 관 | 함 | 실행기는 짝의 판정 줄 + 1 s(없으면 kill + 25 s) 뒤 자식을 끔; 자식의 fd 정리는 라이브러리 요구(줄 꼴 표 6) |
| 4 자식 시작 시각 | 함 | 같은 노드의 rank 시작 tick과 견줌 |
| 5 launcher 시작 실패 정리 | 함 | `launcher_gc.sh` 스스로 stop, `la_start`는 두 노드 stop |
| 6 조각 사이 빈틈 | 함 | 시행 표지, 앞 시행 끝 표지부터 자름, hold 끝 꼬리 검사 |
| 7 관리망 끊김의 기록 QP | 함 | `rec_repair_n == 0` 더함 |
| 8 LATER 열 | 함 | `la_later_n` |
| 9 되살린 rank의 거짓 hold | 함 | `hold_after_restore_n` |
| 10 연결 수 비교 | 함 | 설정에서 센 `witness_expected`, 커널 ss 스냅숏(보낸 바이트 증가, 연결 수 보고); 받는 쪽 바이트는 라이브러리 요구 |
| 11 자료 부족 규칙 | 함 | 이 실험의 키는 계획 n 미만이면 자료 부족, 묶음 키는 들어간 셀 모두 |
| 12 설정 다름 | 함 | launcher env, W(`prereg.confirm_ms`, pilot 전 null), READ 주기 |
| 13 첫 체크포인트 전 제외 | 함 | `ckpt_stable_before_inj`, 예비 프로세스가 있는 주입 셀 모두 |
| 14 짝 kill 5 ms | 함 | 잠든 뒤 돌며 기다림, `pair_gap_ms` > 5 → `inject_late`, 같은 노드 mono로 창 판정 |
| 15 ssh 오류문의 주소 | 함 | `chain_gc.sh`가 hold 출력 전체를 가림, ssh `LogLevel=ERROR`, launcher 전체 로그도 끈 뒤 가림 |
| 16 pilot 파일 이름 | 함 | pilot/smoke 폴더 규칙, `gc4_stop12000_pilot`, `costpilot*`는 pilot |
| 17 `gin_mrr_` | 함 | |
| 18 끝난 뒤 READ | 함 | `after_end_*`를 뺌(라이브러리 요구) |
| 19 셀 열과 preds | 함 | 대조를 더하고 둘을 D7대로 고침 |
| nit 1, 2, 4, 5, 6, 9, 10, 11, 13, 14, 15, 16, 17, 19, 20 | 함 | 글, 스위치 글, exit 6 meta, P0 smoke, Z/X, 860 s, BAR1, RNR 줄, 비용 exit 6, deploy ssh, `GC_CHAIN`, 로그 가림, 시한 줄, 판정 퍼짐 시계, MTU 뒤 비교 |
| nit 3, 18 | 안 함 | 문서 쪽(메인 세션): 8절과 9.9절의 `pkill -x` 문장, `launcher_msg.h` md5 |
| nit 7 | 안 함 | 멈춤 길이 허용 1 s를 좁힐지는 사전 등록 결정(아래 8절 목록) |
| nit 8 | 요구로 | 처음 세대를 줄에 싣기(줄 꼴 표 리뷰 3) |
| nit 12 | 표시 | 비용 판정은 한쪽; `todo`와 3절 목록 |
| nit 21 | 안 함 | `build_gc.sh`의 `gctc` 단계는 이 폴더 밖(TODO(p4)) |
| D1–D8 | 함 | D1, D2는 메인 세션 결정대로; D3–D8은 권고 값을 넣고 `todo` 표시를 남김 |
| 리뷰 밖 | 함 | 펜스로 끝난 대상을 gin-mirror 열이 살아 있는 rank로 쳐 펜스 셀 셋(`stall_fence_restore`, `freeze_fence_restore`, `helper_stall_fence`)의 `ow_data_equal`이 늘 0이던 것 `[측정: 합성 시험]` → `fenced_subject` |

### 3절에 메인 세션이 적을 것

> 2026-10-23 표시: 11절의 시험 쪽 리뷰 줄(커밋 `4eadfe49`)이 3절 `todo` 여섯과 8절 규칙의 반영을 적었다. 아래 3절, 8절 목록을 항목마다 대조하지는 않았다 `[미확인]`. 지금 기준은 EXPERIMENT.md 3, 8절이다.

리뷰가 말한 대로 아래 여섯 `todo`는 3절에 수치나 목록이 실제로 없다. CSV에는 리뷰 권고 값을 넣었고 사전 등록 때 확인한다.
1. `kill_judge_rdma`: 셀 열의 "rdma 빌드의 gin-mirror kill 셀" 여덟(`mi4_kill3_ow`, `mi4_kill1_ow`, `mi4_kill3_ckpt_ow`, `mi4_seg_4k`,
   `mi4_seg_32k`, `mi4_seg_128k`, `mi4_pull`, `rs4_kill3_mion`, 모두 `@gc`)을 셀마다 k = n − 1(n 10은 9, n 5는 4)로 판정.
2. `restore_time_rdma`: n 5 셀은 ≥ 4/5; "약" 범위를 그대로 문턱으로 씀; LATER 수는 launcher 줄의 것.
3. `gate_fenced`: 실제 자식 프로세스; FENCED GO − 둘째 thread 끝 0–5 ms, 따로 잰 pidfd 시각과의 차 ≤ 5 ms, 옛 관문은 둘째 thread 끝 전 GO;
   "약 500 ms"의 차이는 보고.
4. `regression_rdma`: gin-mirror ID 열둘(`ow_wait_held`, `ow_data_equal`, `ow_no_reexec`, `ow_revived_done`, `ow_suppress_exact`, `ow_from_pool`,
   `ckpt_kill_ow`, `kill_other_ow`, `reimage_after_restore`, `second_death_restored`, `train_data_equal`, `train_second_death`); `store_rdma`와
   `train_paced_import`는 넣을지 결정 대기. 둘째 죽음 둘의 시간 몫은 gin-mirror 원래 기준.
5. `regression_rdma_mirror_off`: `rs4_kill3`, `rs4_kill3_ckpt`, `rs4_kill1`(데이터 같음, 재실행 없음), `rs4_none`(데이터 같음)을 gin-mirror의
   원래 k로; 이미지 바이트 0은 모든 유효 시행.
6. `cost_probe_lat4k`: 문턱 = max(2 %, pilot의 probe-off 두 묶음 사이 4 KiB 지연 중앙값 차의 두 배), 노드마다, 한쪽 판정(느려짐만).

그 밖에 3절 글로 고정할 것:
7. `no_tcp_control`: 연결 수는 설정에서 센 증인 수((N − 1) × 요약을 낸 프로세스 수)와 견줌; 실행기의 ss 스냅숏 둘 사이 rank 프로세스의 TCP
   보낸 바이트 증가 0 `[추론: NCCL 자신의 소켓도 조용함, pilot 확인]`; ss 연결 수는 보고(NCCL bootstrap 수를 pilot이 재면 더함).
8. `mgmt_mute_transparent`의 "기록 QP 잃음 0" = 다시 짝 맺기 0과 잃은 기록 0.
9. `kill_no_witness`의 "정상 종료 시행 끝의 hold 0" = 첫 복원 뒤 시작된 hold가 어느 rank에도 없음.
10. `finless_read_fail`: 판정 앞의 시한 줄이 있어야 함.
11. 135행 시계 문장: 노드 사이는 실행기가 시행 앞뒤로 잰 시계 차(왕복 최소, 왕복 시간 기록)로 두 `mono_ms`를 견줌.
12. `none_probe_clean`: READ 성공률은 상대의 끝(BYE, LEFT, 판정) 뒤 READ를 뺌; 박동 간격 최대는 첫 성공 READ부터 상대의 끝 전까지.
13. 134행 "판정은 유효한 시행만으로 센다"에 덧붙임: 이 실험의 셀 키는 유효 시행이 계획 n보다 적으면 "자료 부족"; 묶음 키는 들어간 셀이 모두
    계획을 채울 때만 판정.
14. 리뷰의 "CSV가 3절에 없는 조건을 더하거나 읽은 것" 목록(RST 줄이 하나도 없으면 시험 안 됨, RST tcp의 복원 성공 읽기, uverbs의 fail-fast
    읽기, 짧은 멈춤의 데이터 같음 두 열과 의심 줄이 생존 rank마다인지, 학습 모양 20 ms 뺌, 회귀(rdma)의 판정하지 않는 gin-mirror 셀은 보고만).

### 8절에 메인 세션이 적을 것

1. 제외 문장 "둘째 죽음 셀에서 둘째 kill이 그 rank의 다시 무장 줄 전인 시행"을 빼고 gin-mirror 8절 규칙으로 바꿈: 둘째 kill이 다시 무장보다 먼저
   난 시행, 첫 복원이 실패한 시행, 다시 무장이 오지 않은 시행은 빼지 않고 조건 불충족으로 셈(`@gct`, `@gc` 모두; 2026-10-17 결정).
2. launcher는 hold마다 노드마다 하나이고, 시행 시작 때 두 launcher의 등록 표가 비어 있지 않으면(앞 시행의 (rank, 화신)이나 예비 자리가 남음)
   그 시행을 돌리지 않고 STOP_launcher.
3. STOP_launcher 줄은 `(STOP_launcher)`와 `(STOP_launcher: …)` 둘 다; 시험 스위치 셀(`QP_ERR`, `DROP_UD`, `CREDIT_STALL`) 밖 launcher QP ERR의
   규칙: 이 시행의 시작 표지 뒤, 첫 "is leaving" 줄 전, 대상 밖 rank의 QP 잃음 줄.
4. "kill이 첫 확정 무장 체크포인트 전" 제외를 예비 프로세스가 있는 주입 셀 모두(STOP, FREEZE_PAGE, DIE_RST)로 넓힘.
5. "셀이 정한 설정과 다르게 돈 시행"에 launcher env, W, READ 주기를 더함.
6. "정한 시각보다 1 s 넘게 어긋난 시행"에 예비 프로세스 없음 셀의 두 kill 간격 > 5 ms를 더함; 멈춤 길이 허용 1 s를 좁힐지(리뷰 권고 50 ms) 결정.
7. STOP_mtu에 "시행 뒤 `active_mtu`가 시행 앞과 다름"을 더함.
8. fd 자식 정리는 `pkill -x gin_fdhold`가 아니라 fork 줄의 PID와 uid, 이름, 같은 노드의 시작 tick으로(9.9절 984행도).
9. pilot과 smoke는 이름이 pilot이나 smoke로 시작하는 결과 폴더에서만 돌고, P0은 smoke로 따로 셈.
10. 결정 대기: FENCE_NAK이 난 시행을 제외로 칠지 실패로 셀지(지금 채점기는 셈).

### 남은 `todo`

- `TODO(prereg)` 여섯(위 3절 목록 1–6; 권고 값이 들어가 있음).
- `TODO(pilot)`: `stall_fence_restore`의 사전 등록 여부(9.9절 끝 pilot 셀, 3절이 정말로 미룸), `no_tcp_control`의 ss 가정과 NCCL bootstrap 수,
  W(`cells_gc.json` `prereg.confirm_ms`), `STEPS`, 셀 스위치 값의 자리 표시.
- `TODO(gate_fenced.cc)`: `--pid` 모드(그 전까지 `gate_fenced`는 자료 부족).

### 12절 실행 기록에 넣을 행 (제안)

> 반영됨(2026-10-23 확인, EXPERIMENT.md 읽기만): 12절 2026-10-17 시험 쪽 독립 리뷰 행과 11절의 시험 쪽 리뷰 줄(자체 시험 62/62). 다시 붙이지 않는다.

```
| 2026-10-17 | 시험 쪽 독립 리뷰(REVIEW_TEST: 막는 문제 4, 고칠 것 19, nit 21) 반영. 원격 명령 따옴표(remote_gc.sh), 시험 스위치 셀의 대상 rank,
둘째 죽음은 빼지 않음(@gct, @gc; 메인 세션 결정), hold 쪽 STOP_launcher 두 꼴과 QP ERR, launcher는 hold마다 하나 + 시행 시작 때 등록 표 검사,
시행 표지로 자른 launcher 조각, 노드 시계 차, fd 자식 끄기, ss 스냅숏, 자료 부족 규칙, 실제 프로세스 관문 시험(gate_proc_gc.py). 리뷰 밖 결함
하나(펜스로 끝난 대상의 데이터 같음 열) 고침. 자체 시험 62/62 통과(로컬 Python), check_cells_gc.py ok, 셸은 bash -n만. 클러스터 실행 없음 |
impl/test/notes_test.md(고침) |
```

## 셀 줄임 (2026-10-22, 사용자 결정 "실험을 위한 실험을 줄임")

사전 등록 전이라 EXPERIMENT.md 3, 7, 8절과 이 폴더의 셀 파일, 예측 표를 그 자리에서 고쳤다(EXPERIMENT.md 12절 2026-10-22 셀 줄임 행). 코드(`hold_gc.sh`, `score_gc.py`,
`run_cost_gc.sh`, `test_rows_gc.py` 등)는 고치지 않았다.

| 무엇 | 줄임 전 | 줄임 뒤 |
|---|---|---|
| 7절 행(`rows`) | 27 | 25(옛 7행 `gct4_rstgap_live*`, 옛 10행 `gct4_fdhold_sock_kill3`을 빼고 번호를 다시 매김) |
| cell@build(`cells`) | 27, 185 시행 | 23, 155 시행 |
| 예측(`predictions_gc.csv`) | 31 | 28(`rst_judge_tcp`, `rstgap_live_tcp`, `finless_tcp_baseline`을 뺌) |
| 빌드 키(`builds`) | `gc`, `gct`, `gctc`, `gcp`, `gctp` | `gc`, `gct`, `gcp`(`gctc`, `gctp`는 `builds_unused`에 까닭만) |
| hold | C1–C11 | C4 없앰(tcp 대조 셀만 있었음), C5는 `gc4_fdhold_uverbs_kill3@gc`만, P2는 `gct4_mgmt_mute8@gct`만 |
| tcp 회귀 | gin-mirror hold 여덟 전부 `@gct`(188 시행) | `regression.builds.gct.cells` = `mi4_kill3_ow`(10 시행); `regression_tcp`는 그 셀만 보는 gin-mirror 예측 일곱 |
| 비용 | 팔 셋 × 지표 셋 × 6 × 노드 둘 = 108 실행 | `probe-off`, `probe-on` × `lat4k` × 6 × 노드 둘 = 24 실행; `cost_probe_lat4k`의 셀 열은 `cost:probe:probe-on:lat4k` |

- 대조 팔을 바꾼 것: `gc4_rst_kill3@gc`와 `rst_judge_rdma`는 `gc4_kill3_ow@gc`, `gc4_rstgap_live300@gc`와 `rstgap_live_rdma`는 `gc4_none_ow@gc`, `gc4_fdhold_sock_kill3@gc`와
  `finless_exit_report`는 `gc4_kill3_ow@gc`(앞의 대조 팔이 빠진 셀이었음; 대조 팔 열은 채점에 쓰이지 않음 `[소스: score_gc.py]`).
- `check_cells_gc.py`: 행 수를 박아 둔 곳은 없었고(독스트링만 27), 회귀 빌드의 `cells` 목록 검사를 더함. 실행 결과 `section 7 rows 25, cells 23, section 3 keys 28 ... ok`.
- `TODO(code)`: `hold_gc.sh`의 `json_hold`(`RG-` hold)와 `score_gc.py`의 `regression_entries`가 `regression.builds.<b>.cells`를 아직 읽지 않는다. 고치기 전에는 `RG-gct-G1`이 G1 일곱 셀을
  모두 돌고 채점기가 `@gct`에 hold 여덟을 계획하므로 `RG-gct-*` hold를 돌리지 않는다. `hold_gc.sh`의 비용 hold 설명(팔 셋 × 지표 셋)은 주석만 옛것이고 실제 팔과 지표는 셀 파일에서 읽는다.
- `test_rows_gc.py`(고치지 않음)는 줄임 뒤 62검사 가운데 1 실패다: 빠진 예측 `rstgap_live_tcp`의 판정을 "맞음"으로 기대하는 검사(예측 표에 그 행이 없어 판정 None).
  나머지 61은 통과. 그 기대 하나를 지우거나 빠진 예측을 기대 목록에서 빼는 것이 남은 코드 몫이다(`TODO(code)`). 합성 시행의 `gctc` 셀 이름은 합성 자료라 그대로 둬도 된다 `[추론]`.
- 고침(2026-10-22 뒤따름, 위 `TODO(code)` 둘을 닫음): `json_hold`와 `regression_entries`가 `regression.builds.<b>.cells`를 읽어 `RG-gct-G1`은 `mi4_kill3_ow`만 돌고 다른 `RG-gct-*`는 셀 없음으로 멈추며, 채점기는 `@gct`에 그 셀만 계획한다(`@gc`는 그대로).
  `test_rows_gc.py`는 `rstgap_live_tcp` 기대를 지우고 이 계획 검사 하나를 더해 62검사 0 실패, `check_cells_gc.py`는 셀이 쓰는 빌드 키가 EXPERIMENT.md 빌드 키 표에 있는지 검사(잘못 넣은 `gctc`로 FAIL 확인) `[측정: 로컬 실행]`.

## launcher 데몬의 예비 프로세스 (2026-10-22, 조율 세션 지시)

launcher가 노드마다 예비 프로세스 하나를 스스로 띄우고 활성화 뒤 다음 화신을 띄운다([../launcher/README_launcher.md](../launcher/README_launcher.md) "따뜻한 예비 프로세스",
커밋 10bc65af). 그 README의 "실행기 쪽에 필요한 바꿈" 여덟을 이 폴더에 적용했다. 조율 세션의 결정: launcher는 **시행마다**(예비 프로세스 명령에 시행마다의 값이 있음; 그 README 6의 (가)).

| 무엇 | 바꾼 것 |
|---|---|
| `launcher_gc.sh start` | `--spare-cmd`, `--spare-env`(되풀이), `--spare-log`, `--spare`, `--spare-hello-ms`, `--spare-respawn-max`를 그대로 넘김. launcher가 받지 않는 `--spare-env`(기록, 시험 kill, 소켓, 노드 변수)는 여기서 먼저 거절(exit 2). 띄우기 전에 노드의 낡은 소켓(`/tmp/gc_la.??????/launcher.sock`, 이 uid)과 이 uid의 `gin_launcher` 프로세스를 셈: 하나라도 있으면 띄우지 않고 `stale sock=N proc=L`, exit 3. 새 읽기 전용 op `stale`. 명령과 환경은 파일에 쓰지 않음(rec에는 `spare`, `spare_log`, `spare_env_n`, `spare_respawn_max`만) |
| `run_gc.sh` | rdma 길(`LAUNCHER_SCOPE=trial`): 시행 폴더에 `spare/`와 `spare_exec.sh`(bash → stdbuf → driver의 exec 사슬, kv는 `spare_i<화신>.kv`)를 만들고 rank보다 먼저 두 launcher를 띄움. 낡음은 exit 7, 안 뜸은 exit 6(둘 다 meta만, STOP_launcher). 실행기의 `start_spare`는 tcp 길에서만. 노드마다 따라 읽기 하나가 `spare/`의 띄울 때마다의 로그를 받는 때 시각을 붙여 `spare.log`, `spare_2nd.log`(그 밖의 화신은 `spare_<node>_i<화신>.log`)로; 준비됨은 거기의 `GINRS spare_ready`; kill 대상(`SPARE_KILL_FIRST`, `spare_then_rank`, 같은 rank의 둘째 kill)은 HELLO 줄의 hello pid(부모는 launcher pid로 검사). 예비 프로세스 없음 셀 둘은 `--spare-respawn-max 0`. 끝: 활성화된 띄움마다 launcher의 끝 줄을 기다리고(T0 + WATCHDOG_S + 20 s까지, 넘으면 그 hello pid로 kill, `which=bound`), 멈춘 프로세스 정리, 표지, launcher 끄기, 따라 읽기 끝, kv와 종료 코드(launcher 끝 줄: signal n → 128 + n), launcher 로그 전체 복사. 같은 노드의 다른 두 rank에 예비 프로세스가 필요한 셀은 거절(exit 1) |
| `hold_gc.sh`, `cells_gc.sh` | hold는 launcher를 띄우지 않음(셀의 `launcher_env`를 `LAUNCHER_ENV`로 넘김), 마지막 시행 뒤 꼬리 검사는 없앰(시행 로그 전체가 시행의 것). exit 6, 7의 글 |
| `rows_gc.py` | 시행 launcher 로그 전체; 새 열 `launcher_scope`, `launcher_stale`, `la_spare_spawn_n`, `la_spare_respawn_n`, `la_spare_cap_expected_n`, `spare_hello_after_ms`, `spare2_inc_want`, `spare2_inc_got`, `spare2_daemon_ok`; 예비 프로세스 없음 셀의 한도 줄 하나는 `la_stop_n` 밖; `--stops`에 `la_not_up`, `la_stale_n` |
| `score_gc.py` | 제외 `launcher_stale`; 둘째 예비 프로세스가 launcher의 것이 아니면(`spare2_daemon_ok` 0) `spare_start_fail`; SCORE.md에 예상된 한도 줄 수와 launcher가 안 뜨거나 낡은 시행 |
| `test_rows_gc.py` | 장면 I: 같은 rank 둘째 죽음의 데몬 화신 2(있음, 없음), 낡은 소켓 시행, 예비 프로세스 없음 셀의 한도 줄(다른 셀에서는 STOP), `launcher_gc.sh stale`와 `start`의 거절(스크래치 뿌리, 진짜 `/tmp`는 건드리지 않음) |

- 확인: `python3 test_rows_gc.py` 72 checks, 0 failed, `python3 check_cells_gc.py` ok, 셸 여덟 `bash -n` 통과 `[측정: 로컬 실행]`. `run_gc.sh`의 launcher 줄 읽기(LAPY), 따라 읽기 둘(FOLLOWPY, SPLITPY), `spare_exec.sh`는 가짜 로그와 가짜 driver로 로컬에서 한 번 돌려 봄(화신 2의 kv 경로, exec 뒤 같은 pid) `[측정: 로컬 smoke, n 1]`. 클러스터, ssh, 실제 launcher 실행 없음.
- 한도 줄을 세지 않는 예외는 이 폴더의 선택이다: 다시 띄우기를 두면 실행기가 끝낸 예비 프로세스가 곧바로 다시 떠 `rs4_kill3_spareabsent`(kill이 수 초 뒤)는 복원이 되어 버리고, `gc4_kill3_ow_spareabsent`는 다시 띄운 것의 HELLO와 ACTIVATE의 경주가 된다 `[추론: gin_launcher.c 1112–1114행(HELLO 없는 자리는 REFUSED), 912–937행(다시 띄우기)]`. EXPERIMENT.md 8절에 적었다.
- `[미확인]`: 기록 파일이 아직 없을 때 띄운 예비 프로세스가 기다리는지(그 README 7), rdma 빌드의 예비 프로세스가 아직 `NCCL_GIN_RESTORE_SPARE_PORT`를 쓰는지(쓰면 같은 rank의 화신 2가 같은 포트). 따라 읽기의 받는 때 시각은 읽은 때라, 따라 읽기가 읽기 전에 쓰인 줄은 늦게 찍힌다(`mono_ms`가 있는 줄은 그것을 씀).
- 남은 것: EXPERIMENT.md 9.8절 파일 표의 `hold_gc.sh` 행 글("노드마다 launcher 하나 띄우고 끄기")은 이번 범위(5, 8, 9.5절) 밖이라 그대로다.
- sparefix의 실행기 몫(2026-10-22, [../notes_sparefix.md](../notes_sparefix.md) 1절의 권함): `run_gc.sh`의 `spare_opts`에 `--spare-wait-for "<노드의 spare 폴더>/.go" --spare-hello-ms 30000`을 더하고, rdma 길에서 예비 프로세스가 있는 rank마다 그 rank 로그에 `GINRS resume` 줄이 나오면(60 s까지) 그 노드에서 `.go`를 만든다(a6 진단 사본 넷째 hunk 그대로, 둘째 hunk인 `spare_exec.sh`의 기다림은 넣지 않음). 시행 끝 `.end` 앞에서 `.go`를 지운다. `launcher_gc.sh start`는 `--spare-wait-for`를 그대로 넘긴다.
- 확인: 셸 여덟 `bash -n` 통과, `python3 test_rows_gc.py` 72 checks 0 failed, `python3 check_cells_gc.py` ok `[측정: 로컬 실행]`. 클러스터 실행 없음이라 launcher가 `.go`를 기다렸다가 띄우는지는 `[미확인]`.
- **REVIEW_INT3 B1, B3, F6, F7 (2026-10-22, 조율 세션 지시, 시험 쪽).** `rows_gc.py`: PAGEUP은 `probe_ms=`, `W=`를 괄호 안 어디서나 읽고 뒤 글(`, device line …`)을 가리지 않으며, CONF_OPEN은 smoke3에 있는 `opened by END`도 받는다. 다른 정규식은 smoke3 원자료 줄과 모두 맞았다(안 맞은 것은 다른 꼴의 줄뿐: `communicator degraded … judged dead`, 예비 프로세스의 `restored as`, launcher의 `handed to its spare`) `[측정: 로컬 대조]`. B3: rdma 빌드의 `tcp_ctrl_bytes`는 프로세스마다 링이 live가 된 뒤의 바이트(제어 요약의 `tcp_record_bytes_live=`나 `_prelive=`, `tcp_data_bytes_live=`나 `_prelive=`; 총합 0이면 0)이고, live 전은 `tcp_record_bytes_prelive`, 가를 수 없으면 `tcp_record_bytes_unsplit`에 넣고 `tcp_ctrl_bytes`는 빈칸이다(`TODO(p2)`: 라이브러리가 그 칸을 내야 판정됨). `tcp_ctrl_conn_n`, `witness_pairs`는 마지막 세대(복원하고 live가 된 예비 프로세스가 그 rank의 옛 프로세스를 갈음)의 쌍 가운데 두 끝이 소켓을 연 쌍(live 줄, `reconnected`, `unknown, re-dialled`, REJOIN 줄; fd −1 설치의 `reconnected gen=1 attempts=0`은 바로 뒤 re-dialled가 지움), `witness_expected` = `ring_live_pairs`(두 끝이 live), 증인 끄면 둘 다 0; 라이브러리 셈은 `tcp_conns_lib`, `witness_conns_lib`로 보고만 한다. `predictions_gc.csv`의 `no_tcp_control` 행(키 같음)의 판정식과 글을 그 뜻으로 바꿨다. F6: rank와 예비 프로세스 로그의 `(STOP_launcher`와 `launcher Unix socket closed (` 줄(trial_end 표지 전)을 `la_stop_n`에 더한다(`rank_stop_n`, `rank_la_sock_lost_n`; `--stops`도 같음). F7: rank마다 첫 줄에서 `LIVE_BOUND_MS`(10 000 ms, `TODO(prereg)`) 안의 live 줄(`ring_live_n`, `ring_live_all`); 한 rank라도 없으면 `score_gc.py`가 `ring_not_live`로 제외하고 SCORE.md에 수와 시행을 적는다.
- 확인: `python3 test_rows_gc.py` 83 checks 0 failed(새 검사 11: 새 PAGEUP 꼴, UD 복원의 증인 셈과 바이트 셋, 다시 걸지 않은 증인, rank 쪽 STOP 두 꼴, live 없음과 한도 넘음), `python3 check_cells_gc.py` ok, 셸 여덟 `bash -n` 통과 `[측정: 로컬 실행]`. smoke3 a1–a6(시도마다 n 1, smoke)을 세션 스크래치로 다시 뽑았다: `confirm_w_ms` 20, `probe_ms_page` 100, `suspect_n` a3 6, a4 3, 나머지 0, `witness_lost_n`과 `confirm_alive_n`은 kill 시도 a2, a5, a6에서 3, `ring_live_all` 1, `witness_pairs` = `witness_expected` = 6(증인 끈 a5는 0 = 0), `tcp_ctrl_bytes`는 빈칸(요약이 live 앞뒤를 가르지 않음; `tcp_record_bytes_unsplit` 16 848–29 952 B) `[측정]`. 결과 폴더의 `trials.csv`는 다시 쓰지 않았다. 클러스터 실행 없음.
- **예측 표 파일을 3절(커밋 b3d83222)에 맞춤 (2026-10-22, 조율 세션 지시, 시험 쪽).** 3절과 달랐던 여섯 행을 고쳤다. 멈춤 셋(`stall_fence_restore`, `stall_none_refuse`, `freeze_fence_restore`)은 판정 원인 열을 `n_judge_stall`(STALL, 14행)에서 `n_judge_stall_helper`(STALL_HELPER, 15행)로 바꿨다. `fdhold_uverbs_refuse`는 EXITED에 더해 박동 정체 길의 두 원인을 모두 받는다(`n_judge_exited + n_judge_stall_helper + n_judge_stall == n_judge`; 어느 쪽인지는 3절의 `[미확인]`). `kill_judge_rdma`와 `rst_judge_rdma`는 확인 창 띠를 W–W + 1 ms에서 W–W + 2 ms로, EXITED 길을 102–206 ms에서 100–150 ms로 바꿨다. `finless_exit_report`, `kill_no_witness`(100–150 ms), `finless_read_fail`(3.5–4.5 s), `no_tcp_control`(세 조건)은 이미 3절과 같았다. `todo` 열의 `TODO(...)` 표시는 그대로 두었다(3절이 아직 `[초안]`).
- `check_cells_gc.py`에 drift 검사를 더했다: 행마다 판정식이 쓰는 원인 열과 3절 행의 "시행마다의 조건" 열이 이름 붙인 원인이 서로 같은지, 이름에 `ms`가 든 열의 띠(`a <= x <= b`, `a <= x_min and x_max <= b`, W 기준 `_dev_` 띠)와 홀로 선 상한이 3절 행의 수와 같은지(부등호 `<`와 `≤`도) 본다. 3절 글의 `[...]` 메모와 "2026-10-22 전에는 …"(다음 `;`나 `)`까지)는 먼저 지운다. 고치기 전 파일에서 27줄을 냈다(행으로 여섯) `[측정: 로컬 실행]`. k, 같음 조건, `ms`가 없는 열은 견주지 않는다.
- `test_rows_gc.py`: 합성 멈춤 줄(D, B2 freeze)을 smoke3의 실제 꼴 `judged stalled (liveness stall judged (STALL_HELPER))`로 바꿨다. J 검사 20개를 더했다: 멈춤 규칙은 STALL_HELPER를 받고 STALL 사본은 떨어뜨림, uverbs 규칙, EXITED 101, 120, 149 ms는 들고 99, 151, 160 ms는 빠짐(`kill_judge_rdma`, `finless_exit_report`, `kill_no_witness`), 확인 창 W + 1.5, 2.0 ms는 들고 2.5 ms는 빠짐, drift 검사가 지금 행에서 0이고 옛 꼴 여섯 사본을 모두 잡음.
- 확인: `python3 test_rows_gc.py` 103 checks 0 failed, `python3 check_cells_gc.py` ok(drift 0), 셸 여덟 `bash -n` 통과 `[측정: 로컬 실행]`. 클러스터 실행 없음.
- 남은 것: 8절에는 링이 live가 되지 않은 시행의 제외(`ring_not_live`, 한도 `LIVE_BOUND_MS` 10 000 ms 자리 표시) 줄이 없다. 그 규칙은 `rows_gc.py`, `score_gc.py`와 11절 할 일(F7: "8절에 한 줄")에만 있다 `[소스]`. 세대마다 증인 셈은 8절에 있고 `no_tcp_control` 행과 같다. 고치지 않은 행 가운데 `restore_time_rdma`, `gate_fenced`, `cost_probe_lat4k`, `regression_rdma`, `regression_rdma_mirror_off`의 `todo` 글은 "3절에 k(또는 목록, 규칙, 수치)가 없음"이라고 하지만 지금 3절은 그 값을 `[초안: 사전 등록 전 확정]`으로 적었다. 판정식은 3절과 같아 이번에는 그대로 두었다.

## GPU hang 셀과 driver 사본 (2026-10-23, 사용자 결정)

- **driver 사본.** `driver/gin_mi.cu`는 gin-mirror의 `../../../mirror/impl/test/gin_mi.cu`(md5 `556804c0b5e627b7d3d09203c8ef0679`, 커밋 `980a0752`)를 복사하고 스위치 하나만 더한 것이다
  (사본 md5 `9f4568d98c4faf084db9a2277297b4c7`, 원본 대비 바뀐 줄 50, gin-mirror 파일은 고치지 않음). `GC_GPUHANG_IT=<N>`: 예비 프로세스가 아닌 프로세스에서 걸음 N의 보내는 CTA가 put을 post한 뒤
  flush(poll) 전에, 아무도 쓰지 않는 장치 낱말에서 돈다. spin 직전에 매핑된 호스트 낱말을 쓰고, 호스트가 `GINRS gpuhang rank=R step=N spin=1 wait_ms=W mono_ms=M`을 내고(2 000 ms 안에 못 보면 spin=0),
  kv `gpuhang_it`, `gpuhang_step`, `gpuhang_seen`을 남긴다. `RS_TRAIN`과 함께면 usage error(exit 1). 바뀐 장치 코드는 이 시험 driver의 것뿐이고 라이브러리 장치 코드는 0줄이다.
- **빌드.** `driver/build_driver_gc.sh`(md5 `07dc8ab0`; gin-mirror `build_mi_test.sh`의 `mi` 단계를 잘라 옮김): 머리와 라이브러리는 `agent_gc_p2a2/build`(머리 digest `65fdf19b`), 출력 `agent_gc_smoke4/test/out/mi/gin_mi`
  md5 `563cb460ea0b78c6f614028032934fe9`, 경고 0 `[측정]`.
- **셀과 예측.** `cells_gc.json`: 7절 16행 `gc4_gpuhang12000_fence@gc`(n 5, `R3_ENV=GC_GPUHANG_IT=155`, `SUBJECT_RANK=3`, `FENCE=lineage`, 주입 kind `gpuhang`), hold C10(멈춤과 freeze 셀과 함께), pilot P1에 n 1;
  뒤 행 번호 하나씩 밀림. 걸음 155는 smoke3의 걸음 시간(약 7.9 ms, live 뒤 걸음 100이 1.57 s)에서 live 뒤 약 2 s로 잡은 자리 표시다(todo). `predictions_gc.csv`: `gpuhang_fence_restore`
  (`n_judge_stall == n_judge`, `stop_judge_ms` 10 000–10 500, FENCE SIGKILL과 FENCED, `fence_order_ok`, 바뀐 칸 0, 복원과 데이터 같음, ≥ 4/5).
- **채점기.** `rows_gc.py`: `SW_GPUHANG`(`GINRS gpuhang rank=R step=S spin=1 `)이 주입 기록이다. 셀 env에 `GC_GPUHANG_IT`가 있으면 그 줄이 `inject_ok`의 조건이고, `ckpt_stable_before_inj`와
  `stop_judge_ms_min/max`의 시작이다(STOP, FREEZE_PAGE 줄 다음 차례).
- **자체 시험.** `test_rows_gc.py` B5: 합성 GPU hang 시행 다섯(판정 STALL, hang 줄 뒤 10 100 ms, FENCE → FENCED → 활성화). 열 검사, 규칙이 STALL만 받고 STALL_HELPER 사본과 10 600 ms는 거짓, 판정 "맞음".
- 확인: `python3 test_rows_gc.py` 106 checks 0 failed, `python3 check_cells_gc.py` ok(7절 26행, 셀 24, 3절 키 29, drift 0) `[측정: 로컬 실행]`.
- **넷째 smoke.** 같은 셀이 실제 NIC에서 한 번 돌았다(a6): STALL ×3이 hang 줄 뒤 10 032–10 033 ms, FENCE → FENCED 106.9 ms, 복원, 데이터 같음 `[측정, n 1, 채점 아님]`(`../../results/20261023_smoke4/SMOKE.md`).

## 다섯째 smoke의 실행기 몫 (2026-10-23, 조율 세션 지시)

넷째 smoke a4(`NO_EXIT_REPORT` + FD_HOLDER, 죽은 rank 3의 페이지 READ가 10 s 성공)를 가르려고 실행기와 셀 파일만 고쳤다. 라이브러리, driver, launcher는 그대로다.

- **`RES_CAPTURE=1`(기본 0) 자원 캡처.** traffic kill 갈래에서 kill 직전에 죽일 rank의 노드에 읽기 전용 python(`CAPPY`) 하나를 띄우고, 그 "before" 줄이 나온 뒤에 kill한다
  (smoke5에서 kill이 계획보다 652–676 ms 늦음, smoke4는 284 ms). 그 뒤 죽음(`/proc/<pid>/stat`이 없거나 Z/X, 1 ms마다 봄) + 500, 2 000, 5 000, 9 000 ms, 짝의 첫 판정 줄(실행기가
  `<prefix>.judged`를 만듦), 자식이 있으면 자식 kill + 500 ms(`<prefix>.fdkill`)에 잰다. 재는 것: 장치(sunny `mlx5_0`)의 `rdma -j res show` 수(앞뒤 두 번)와
  `rdma -j res show ctx|pd|cq|qp|mr` 목록(pid별, pid 없음), rank와 자식의 fd 목록, `/proc/<pid>/maps`의 uverbs와 nvidia 줄 수, PPid. 출력은 `<stem>_rescap.out`, meta에 `res_capture`.
  `CAP_BOUND_S`(40)가 한도다. sunny 커널 6.8에서는 주인이 죽은 자원이 pid 없이 목록에 남는다(`kern` 열; 숨은 수 `hidden`은 smoke5 캡처 모두 0) `[측정]`.
- **판정 줄 기다림 고침.** fd 자식을 끄는 기다림의 정규식 `GIN/(TS|RC): ...`은 잡음 묶음이 있어 `WAITPY`가 그것을 걸음 수로 `int()`하다 ValueError로 늘 놓쳤다.
  그래서 FD_HOLDER 셀의 자식은 판정과 상관없이 늘 kill + 25 s(`why=bound`)에 꺼졌다(smoke4 a4 `fdhold_killed … why=bound`, kill + 25.3 s) `[측정]`.
  잡지 않는 묶음 `(?:…)`으로 바꿔 판정 + 1 s(`why=judged`)에 끈다(smoke5 a3, a4: kill + 11.37 s) `[측정]`.
- **셀.** `cells_gc.json`의 `pilot_cells`에 `gc4_kill3_noreport_nofdhold@gc`(n 2, 예측 없음, 채점 안 함): `gc4_fdhold_sock_kill3_noreport`에서 `FDHOLD`와 `R3_ENV`만 뺐다.
- 확인: `bash -n run_gc.sh`, `python3 check_cells_gc.py` ok(7절 26행, 셀 24; pilot 셀은 행 검사 밖), `python3 test_rows_gc.py` 124 checks 0 failed `[측정: 로컬 실행]`.
  그 시험은 같은 때 다른 세션이 고치던 `rows_gc.py`, `test_rows_gc.py`(이 고침 밖) 위에서 돌았다. 처음 한 번은 그 고침 중간에 `TypeError`로 멈췄다.
- 결과: [../../results/20261023_smoke5/SMOKE.md](../../results/20261023_smoke5/SMOKE.md).

## 채점기 고침 (독립 리뷰 Codex 2026-10-23 반영)

리뷰가 짚은 여섯 가지를 코드에서 먼저 확인하고 `rows_gc.py`, `score_gc.py`, `predictions_gc.csv`(`kind` 열), `check_cells_gc.py`, `test_rows_gc.py`만 고쳤다.
EXPERIMENT.md, 라이브러리 diff, launcher, driver, 실행기는 그대로다. 위 절의 `TypeError: keywords must be strings`는 이 고침을 쓰는 도중의 시험 파일이었고 지금은 없다 `[측정: 로컬 실행]`.

| 항목 | 확인 | 고침 |
|---|---|---|
| 1 MTU 단위 | 맞음. kv에는 `active_mtu`가 없고 제어 요약의 `active_mtu=5`(ibv_mtu enum)가 그대로 `active_mtu_kv_min`이 되어 모든 smoke에서 5였다 `[측정]` | `mtu_bytes`: 1–5는 256–4096 B, 256 이상은 그대로. driver의 바이트 값(meta)도 같은 함수 |
| 2 장애 없는 시행의 데이터 같음 | 맞음. gin-restore와 gin-mirror의 열이 `_spare.kv`가 있으면 예비 프로세스의 `revived=1`을 요구해, 쓰이지 않은 따뜻한 예비 프로세스가 장애 없는 시행과 투명 셀을 0으로 만들었다(smoke4 a1 등 6시행) `[측정]` | `final_data`: 마지막 세대의 활성 프로세스만 견줌(죽은 rank는 그 rank로 되살아난 예비 프로세스, 쓰이지 않은 예비 프로세스는 빠짐). 열 `spare_state`, `final_gen_n`. 둘째 죽음 시행은 gin-mirror 열 그대로 |
| 3 창 검사 | 맞음. `changed=`만 더하고 `unreadable=`와 생존 rank의 줄 빠짐을 보지 않았다 `[소스]` | `win_unreadable`, `win_checked`, `win_lines_n`, `win_missing`, `win_verified`. 읽지 못한 칸이 있거나 줄이 빠지면 `win_changed_after`는 빈 값 |
| 4 Resume 거절과 링 live 실패 | 맞음. 둘 다 무조건 제외였고 뒤 후보가 채웠다. smoke1 a1(조건 41, launcher 짝 맺기 전 Resume)이 그렇게 `config`로 빠졌다 `[측정]` | 설정 이유(`CONFIG_REFUSALS`)만 `config`, 나머지는 `prep_failure`(계획 n 안의 자리를 차지, 채우지 않음). 예측마다 계획, 실행, 사유별 제외, 준비 실패, 판정 n, 조건부와 전체 성공률 |
| 5 안전과 성능 | 해당. 규칙 하나가 데이터 같음과 시간 띠를 한 `count()`에 묶어 ≥ k/n이면 데이터 불일치 하나가 지나간다 `[소스]` | `kind` 열(safety, perf, cost). safety는 판정한 시행 실패 0일 때만 맞음. perf 규칙 안의 안전 조건은 시행별로 보고만 |
| 6 사건 시각표 | 열이 없었다 | `tl_*`, `t_*_ms`(아래) |

**`CONFIG_REFUSALS`**(Resume 거절 이유 중 설정을 말하는 것; 원문은 `../gc_layer_int.diff`의 `GDAKI_CTRL_R42`–`R44T`, gin-mirror `mi_layer.diff`의 `GDAKI_MI_R36`, `R37`, `R39`,
gin-restore `rs_layer.diff`의 `GDAKI_RS_L` 줄 중 환경변수, 빌드 매크로, HCA를 이름하는 것): MTU 2048 미만(42), `ibv_is_fork_initialized()`(43), 제어 경로나 launcher 노드가 다름(44),
생존 판정 문턱이 다름(44), MIRROR와 CHECKSUM 둘 다 켬, MIRROR_LANE 배수 아님, MIRROR_SLOTS나 LANE이 rank마다 다름, `NCCL_GIN_NCONNECTIONS`, host RMA 켬, `NCCL_RUNTIME_CONNECT` 끔,
NVLS 켬, `NCCL_GIN_FAULT_RECOVERY` 끔, `NCCL_GIN_TS_RECONNECT` 1 아님, QP watch 끔, 로그 측정 모드, `NCCL_GIN_RESTORE_DEVICE` 없이 빌드, `NCCL_GIN_RESTORE_RECORD` 없음, HCA atomic 부족.
그 밖(조건 41 launcher 짝 맺기, pool, mirror QP, side table, NIC 복사 길, atomic 준비, replay)은 준비 실패다. 링 live 실패는 어느 rank의 setup agreement 줄이
조건 42나 44로 꺼졌다고 하면 `config`, 아니면 준비 실패다.

**`kind` 배정**(문서 주인이 3절에 옮길 제안): safety는 `fdhold_uverbs_refuse`, `stall_none_refuse`, `ud_drop_rejoin`, `credit_stall_no_loss`, `long_hold_lane`, `gate_fenced`,
`no_tcp_control`, `regression_rdma_mirror_off`; cost는 `cost_probe_lat4k`; 나머지 20행은 perf다. perf 중 안전 조건을 함께 묶은 행(`finless_exit_report`, `finless_read_fail`,
`stop_transparent`, `stall_fence_restore`, `freeze_fence_restore`, `helper_stall_fence`, `gpuhang_fence_restore`, `mgmt_mute_transparent`, `mgmt_mute_tcp`, `qp_err_repair`, `kill_no_witness`,
`restore_time_rdma`, `regression_tcp`, `regression_rdma`)은 안전 조건을 따로 떼어 safety 행으로 두어야 실패 0 규칙이 그 조건에 걸린다 `[추론]`. 지금은 SCORE.md에 보고만 한다.

### 새 열의 꼴

- `active_mtu_kv_min`, `active_mtu_rain`, `active_mtu_sunny`: 바이트(4096). 라이브러리의 `active_mtu=`와 `min_active_mtu=`는 enum이다.
- `data_equal`, `ow_data_equal`: 한 죽음 시행에서 덮어씀(위 2). `spare_state`: 예비 프로세스마다 `unused`, `restored`, `restored_bad`, `not_restored`, `revived_unexpected`를 `+`로 이음. `final_gen_n`: 견준 프로세스 수.
- `win_changed_after`: `changed=` 합(표본이 완전하거나 바뀐 칸이 보였을 때만, 아니면 빈 값). `win_lines_n`, `win_missing`(줄이 없는 생존 rank, 예: `0+2`), `win_unreadable`, `win_checked`(줄에 `checked=`가 없으면 빈 값),
  `win_verified`(모든 생존 rank의 줄, unreadable 0, changed 0일 때 1). 창 줄에는 지금 incarnation과 검사한 칸 수가 없다: 대상 rank 이름만 맞춘다 `[소스: gdakiCtrlLaWindowLine]`.
- `resume_refusal`(`config`, `prep`, 빈 값), `resume_why_refused`(거절 이유, 머리 "the restore cannot be enabled …" 뺌), `ring_not_live_class`(`config`, `prep`).
- 시각표(대상 노드의 생존 rank, 대상 xor 2; 주입 줄 뒤 ms, 그 노드의 CLOCK_MONOTONIC): `tl_rank`, `tl_inject`, `tl_clock`, `t_suspect_ms`(SUSPECT, 확인 창 열림, READ time-out 중 첫 줄),
  `t_judge_ms`, `t_block_ms`(hold 시작 줄; QP를 ERR로 옮기는 줄은 라이브러리에 없다), `t_fenced_ms`와 `t_fenced_src`(그 rank의 FENCED 줄, 없으면 창 줄 `window_fence` | `window_judgement`),
  `t_la_fenced_ms`(그 노드 launcher의 FENCED 줄), `t_publish_ms`, `t_first_ok_ms`와 `t_first_ok_step`(publish 뒤 첫 `GINRS step … released=0 tx_err=0` 줄).
  driver는 걸음마다 검사 결과를 찍지 않는다(장치 검사 `dev_bad`는 끝의 kv에 합쳐짐): 그래서 그 rank의 kv가 `dev_bad=0`일 때만 채운다 `[소스: gin_mi.cu]`.
- 채점기: 상태 `prep_failure`, SCORE.md 예측별 표(키, 계획, 실행, 제외(사유), 준비 실패, 판정 n, 조건, 조건부 성공, 전체 성공), 안전 예측의 실패 줄, perf 안의 안전 조건 줄.
  표준 출력은 예측마다 `id: 판정` 다음에 `[kind] key planned= run= excluded= prep_failure= scored= cond= whole=` 줄.

### 시각표 (다시 셈, smoke, n 1씩, 채점 아님)

rank 1의 줄, 주입 줄(실행기의 kill과 stop 줄, rank 3의 gpuhang 줄)도 sunny 줄이라 한 노드 시계다 `[측정: rows_gc.py]`.

| 시도 | 셀 | 의심 | 판정 | hold 시작 | 펜스(근거) | 게시 | 첫 걸음(번호) |
|---|---|--:|--:|--:|---|--:|--:|
| smoke4 a2 | kill | 0.4 | 20.8 | 24.7 | 118.9(창, fence) | 155.6 | 350.0(139) |
| smoke4 a3 | kill, 증인 끔 | 없음 | 110.9 | 115.5 | 115.0(창, judgement) | 155.1 | 354.3(137) |
| smoke4 a5 | STOP 12 s | 2 007.3 | 10 010.0 | 10 014.1 | 10 139.8(창, fence) | 10 177.1 | 10 364.6(138) |
| smoke4 a6 | GPU hang | 2 029.5 | 10 033.3 | 10 037.1 | 10 146.4(창, fence) | 10 183.7 | 10 359.5(156) |
| smoke3 a2 | kill | 0.4 | 102.2 | 107.4 | 106.7(창, judgement) | 146.6 | 339.7(138) |
| smoke3 a4 | STOP 12 s | 2 091.2 | 10 094.4 | 10 098.6 | 10 222.2(창, fence) | 10 260.7 | 10 458.7(139) |
| smoke3 a5 | kill, 증인 끔 | 0.4 | 103.5 | 108.0 | 107.5(창, judgement) | 146.4 | 363.7(140) |
| smoke3 a6 | kill | 1.3 | 105.4 | 110.0 | 109.4(창, judgement) | 148.9 | 350.3(138) |

smoke3 a3(STOP, 펜스 없는 옛 라이브러리)은 의심 2 050.1, 판정 10 053.8에서 멈춘다(hold 없음). smoke3 a5의 의심 0.4는 증인 끔이 창을 열던 옛 라이브러리의 FIN 창이다(smoke3 요청 2).

### 다시 돌린 결과 (smoke 폴더 다섯의 사본, 원자료는 읽기만)

- 폴더: smoke1 a1–a4, a6; smoke2 a1–a4; smoke3 a1–a6; smoke4 a1–a6; smoke5 a1–a4(이 고침 중에 생긴 폴더). 사본은 세션 스크래치에서 돌렸고 결과 폴더에는 쓰지 않았다.
- 바뀐 것: `active_mtu_kv_min` 5 → 4096(25시행 모두); `data_equal`과 `ow_data_equal` 0 → 1(쓰이지 않은 예비 프로세스가 있는 장애 없는 시행 6: smoke1 a4, a6, smoke2 a1, a4, smoke3 a1, smoke4 a1);
  smoke1 a1 `config` → `prep_failure`(조건 41). smoke2 a2, a3은 `win_verified` 0(실제로 바뀐 칸 3, 6). 판정은 모두 그대로 "자료 부족"(n 1) `[측정]`.
- 시험: `python3 test_rows_gc.py` 124 checks 0 failed(이전 106; 새 18: MTU enum과 실제 요약 줄, 쓰이지 않은 예비 프로세스, 되살아나지 않은 예비 프로세스, `unreadable=48`, 빠진 생존 rank 줄,
  거절 41과 42, 링 live 실패 둘, 회귀 셀의 준비 실패, 준비 실패가 채워지지 않음, 안전 사본 틀림과 perf 사본 맞음, 출력과 SCORE.md의 셈, `kind` 열, 시각표). INT3 F7 시험은 `ring_not_live` 대신
  `prep_failure`를 기대하게 바꿨다. `python3 check_cells_gc.py` ok(drift 0; `kind` 검사 추가: 잘못된 값 하나를 넣은 사본에서 FAIL) `[측정: 로컬 실행]`.

### 3절과 8절에 문서 주인이 정할 것

> 2026-10-23 표시: 3절의 둘(perf 행 안의 안전성 항, 창 조건 `win_verified == 1`)은 같은 날 정해졌다(아래 "사전 등록 초안 고침 셋" 절, EXPERIMENT.md 12절 2026-10-23 끝 행). 나머지는 확인하지 않았다 `[미확인]`.

- 3절: 각 행의 종류(위 배정)와, 안전 조건을 묶은 perf 행을 나눌지. 창 조건을 `win_changed_after == 0`에서 `win_verified == 1`로 바꿀지(지금도 불완전한 창은 빈 값이라 거짓이다).
- 8절: "Resume 거절 = config 제외"를 설정 이유로 좁히는 문장과 이유 목록, 링 live 실패가 준비 실패라는 문장, 준비 실패가 판정에 어떻게 드는지(지금: 판정은 판정 n 위의 조건부, 전체 성공률은 보고만; 계획 n에서 준비 실패 수를 뺀 n이 있어야 "자료 부족"이 아님).
- 8절과 9.3절: 쓰이지 않은 예비 프로세스는 데이터 같음에 들지 않는다는 문장.

## 사전 등록 초안 고침 셋 (2026-10-23, smoke 5와 채점기 리뷰 뒤; EXPERIMENT 12절 그날 끝 행)

- **예측 바꿈.** `finless_read_fail`의 셀을 `gc4_kill3_noreport_nofdhold@gc`로 옮김(`pilot_cells`에서 `cells`로, n 2 → 5, env와 주입은 smoke 5가 돈 그대로, 대조 `gc4_kill3_ow_nowitness@gc`,
  hold C6에 `gc4_fdhold_sock_kill3_noreport@gc`와 함께, pilot P3에 n 1). `gc4_fdhold_sock_kill3_noreport@gc`는 새 예측 `fdhold_sock_helper_stall`(perf; 대조 `gc4_kill3_noreport_nofdhold@gc`).
  `rows` 9행을 넣고 뒤 행 번호를 하나씩 밀었다(로컬 항목 26, 27; 회귀와 비용 `about`의 행 번호도). 남은 것: `hold_gc.sh` 머리 주석의 "P3 the noreport cell"은 이 고침의 범위 밖이라 그대로.
- **새 열 `probe_fail_n`**(`rows_gc.py`): 판정 앞의 READ 실패 줄(`liveness READ of rank P[ (device line)]: …`, 대상 이름) 수. smoke 5 원자료(읽기만): a1, a2 6(생존 rank마다 재시도 초과 줄과 장치 줄 flush 줄),
  a3, a4 0 `[측정: rows_gc.all_rows]`. 같은 원자료에서 a3, a4는 새 예측의 조건을, a1, a2는 `finless_read_fail`의 조건을 모두 채운다(smoke, n 1씩, 채점 아님).
- **perf 안의 안전성 항**(`score_gc.py`): `SAFETY_TERMS`(열 이름 그대로: `data_equal`, `ow_data_equal`, `no_reexec`, `rec_lost_n`, `rec_dup_n`, `rejoin_accept_dup_n`, `fence_order_ok`, `fence_names_ok`,
  `win_verified`, `win_changed_after`, `wait_held`, `revived_done`, `subject_fenced`; "FENCED 전 활성화"는 `fence_order_ok`가 맡고 따로 된 열은 없음). `safety_parts`가 판정식을 부분마다 그 키로 나누고
  ("mirror:" 부분은 gin-mirror 판정식을 그 셀 키로), `perf_safety_terms`가 판정한 시행마다 항을 본다. 거짓인 시행이 하나라도 있으면 맞음이나 틀림이 `재검토(안전성 항 어긋남 k/n)`가 된다(자료 부족, 자료 없음은 그대로).
  SCORE.md: 항마다 "성능 예측 안의 안전성 항(어긋나면 재검토, 8절)" 줄과 "안전성 항 어긋남(재검토)" 줄(시행 ID와 항). 이 규칙을 받는 perf 행 16개(위 "kind 배정"의 14개 목록은 `rst_judge_rdma`를 빠뜨렸음).
- **창 조건**: 판정식 다섯의 `win_changed_after == 0` → `win_verified == 1`(per_trial 글은 "window 검사 완료, 바뀐 칸 0"). `win_verified`를 `LIB_COLS`에 더함: 창 줄이 하나도 없으면 두 열 모두 비어 자료 부족
  (합성 D 시행의 `stall_fence_restore`가 그 예; 더하지 않으면 틀림 → 재검토가 됐음).
- **시험**: `python3 test_rows_gc.py` 130 checks 0 failed(전 124). 바뀐 것: C를 fd 보관 없는 셀로, 새 C2(fd 보관 셀, STALL_HELPER kill + 10.07 s, 판정 뒤 READ 실패 줄 하나는 세지 않음),
  창 규칙 다섯이 `win_verified`, perf 행 둘(문턱을 넘는 것과 못 넘는 것)이 데이터 다름 하나로 재검토, 안전성 항 없는 perf 행은 맞음 그대로. `python3 check_cells_gc.py` ok, drift 0 `[측정: 로컬 실행]`.

## 제어 요약과 창 줄의 빠진 값 (2026-10-23, Codex 리뷰)

- **고친 것**(`rows_gc.py`). 제어 요약 열은 있는 요약만 더하고 빠진 키를 0으로 쳤다. 그래서 요약 줄이 없는 프로세스가 있거나 요약에 계수가 빠진 시행도 `no_tcp_control`, `credit_stall_no_loss`를 채울 수 있었다.
  이제 요약이 있어야 할 프로세스를 `ctrlsum_required`가 정한다: 마지막 세대(죽지 않은 rank는 자기 프로세스, 활성화된 예비 프로세스는 그 rank; 둘이면 높은 화신; 쓰이지 않은 예비 프로세스와 예비 없이 죽은 rank는 없음; `final_data`와 같은 규칙).
  그 가운데 하나라도 요약이 없으면 요약에서 나온 열이 모두 비고 `ctrlsum_missing`에 이름이 남는다(자료 부족). 필요한 요약에 열이 읽는 계수가 없으면 그 열만 비고 `ctrlsum_fields_missing`에 `proc:field`가 남는다. 0으로 메우지 않는다.
  창 줄도 고쳤다. `changed=`나 `unreadable=`이 없는 줄이 하나라도 있으면 창이 불완전하다: `win_verified` 0, `win_changed_after` 빈칸, 빠진 합도 빈칸, `win_missing`에 `rank:field`가 남는다.
  시험 합성 줄 둘(B2 freeze, B5 GPU hang의 창 줄)에는 실제 줄처럼 `unreadable=0`을 넣었다.
- **새 시험 셋**(`ctrlsum_checks`). (1) rank 1의 요약이 없음: 요약 열이 비고 두 판정 모두 자료 부족. (2) rank 0 요약에 `records_lost`가 없음: `rec_lost_n` 빈칸, `credit_stall_no_loss` 자료 부족. (3) rank 1의 창 줄에 `unreadable=`이 없음: `win_verified` 0, 창 판정 거짓.
  고치기 전 `rows_gc.py`로 같은 시험을 돌리면 셋 다 실패한다(맞음, 맞음, `win_verified` 1) `[측정: 로컬 실행]`.
- **smoke 다시 계산.** smoke1–5의 `a*/raw` 25시행 사본(세션 스크래치, 원자료는 읽기만)에서 고치기 전과 뒤를 견줬다. 기존 열이 바뀐 시행은 0이다. 실제로 요약이 빠진 시행도 없다(`ctrlsum_missing` 모두 빈칸).
  새 열 `ctrlsum_fields_missing`은 smoke1–3의 15시행에서 `r<k>:tcp_record_bytes_live`를 보인다. 이 요약들에는 live 앞뒤 구분이 없어서 `tcp_ctrl_bytes`가 원래 빈칸이었고, 그 값은 그대로다. smoke4, smoke5에서는 빈칸이다 `[측정: rows_gc.all_rows]`.
- **시험.** `python3 test_rows_gc.py` 134 checks, 0 failed(이전 130). `python3 check_cells_gc.py` ok, drift 0 `[측정: 로컬 실행]`.
- **남은 것** `[미확인]`. 쓰이지 않은 예비 프로세스의 요약에 빠진 계수는 아직 판정하지 않는다(필요 집합 밖이라 그대로 더함). 두 번째 죽음에서 첫 예비 프로세스가 죽으면, 높은 화신 하나만 요구하는 규칙은 아직 시험하지 않았다.
- **다시 확인 고침(Codex 2026-10-23).** `ctrlsum_required`가 예비 프로세스를 있는 `.log`에서만 찾아서, 활성화된 예비의 `.log`가 통째로 없으면(kv는 `revived=1`) 필요 목록에서 빠지고 요약 열이 숫자로 남았다. 이제 `_spare*.kv`와 `_spare*.log`를 함께 보고, `.log`가 없는 필요 프로세스는 `ctrlsum_missing`에 `spare:nolog`처럼 남고 요약 열이 모두 빈다. 죽은 원래 rank는 필요 목록 밖에 두되 `.log`가 없으면 새 열 `dead_log_missing`(`r3`)에 남긴다.
  새 시험 둘(활성 예비 `.log` 지움: `spare:nolog`, 두 판정 자료 부족; 죽은 rank `.log` 지움: `dead_log_missing` r3). 고치기 전 규칙을 되살린 변이에서 첫 시험이 실패한다(빈칸, 맞음, 맞음). `test_rows_gc.py` 136 checks, 0 failed, `check_cells_gc.py` ok, drift 0; smoke1–5 사본 25시행에서 기존 열 변화 0, `dead_log_missing` 모두 빈칸 `[측정: 로컬 실행]`.

## GPU hang 반례: 문맥 하나만 멈춤 (2026-10-24, 사용자 결정 가)

모든 GIN 문맥의 진행 줄을 등록하는 라이브러리 조각(다른 세션)의 시험 쪽이다. 라이브러리, 빌드, 클러스터 실행은 없다.

- **문맥 대응(소스에서 확인, `driver/gin_mi.cu` md5 `6cb4ff28`의 줄 번호).** 머리 주석 70–73행: rank마다 받는 문맥 하나(ctx = 받는 rank), 목적지 d로 가는 put은 문맥 d. `stepKernel` 268행
  `const int d = k < me ? k : k + 1;`(CTA k의 목적지), 278행 `ncclGin gin{devComm, d};`(보내는 CTA의 문맥 = 목적지), 302행 `ncclGin gin{devComm, me};`(받는 CTA의 문맥 = 자기 rank),
  752행 `reqs.ginContextCount = N;`. 그래서 rank 3에서 문맥 0을 쓰는 것은 rank 0으로 가는 보내는 CTA 하나이고, 문맥 3(자기 rank)을 쓰는 보내는 CTA는 없다 `[소스]`.
- **driver 스위치 `GC_GPUHANG_CTX=<k>`.** `GC_GPUHANG_IT`와 함께, 목적지가 문맥 k를 쓰는 보내는 CTA만 put을 post한 뒤 flush 전에 돈다(283행의 조건 `hangCtx < 0 || hangCtx == d`; d는 CTA마다 같아서
  `__syncthreads()`가 갈리지 않음). 없거나 빈 값이면 지금처럼 모든 보내는 CTA(`ctx=all`). k가 숫자가 아니거나 0..N−1 밖이거나 자기 rank면 kv `usage_error=gpuhang_ctx`, exit 1.
  hang 줄은 `GINRS gpuhang rank=R step=S spin=1 ctx=all|k wait_ms=W mono_ms=M`, 시작 kv는 `gpuhang_it=.. gpuhang_ctx=all|k|-`(스위치가 없으면 `-`). 원본 gin-mirror 파일 대비 바뀐 줄 78(2026-10-23 사본은 50).
  **빌드 안 함**(소스만; `build_driver_gc.sh`는 그대로 쓸 수 있고 머리 주석만 고침). 다음 smoke 전에 새 `MIOUT`으로 빌드한다.
- **셀과 예측.** `cells_gc.json`: 7절 18행 `gc4_gpuhang12000_ctx1_fence@gc`(n 5, `R3_ENV=GC_GPUHANG_IT=155 GC_GPUHANG_CTX=1`, `SUBJECT_RANK=3`, `FENCE=lineage`, 주입 kind `gpuhang`, 대조 `gc4_gpuhang12000_fence@gc`),
  hold C10과 pilot P1(n 1)에 GPU hang 셀 바로 뒤; 뒤 행 번호 하나씩 밀림(회귀 24–25, 비용 26, 빌드 검사 27, `gate_fenced` 28). `predictions_gc.csv`: `gpuhang_ctx1_fence_restore`(perf; GPU hang 행에
  `stall_ctx == 1`을 더함, ≥ 4/5). `cost_probe_lat4k`의 `per_trial`에 READ 수(상대마다 1 + 문맥 수, 4 rank면 5) 글. 셈: 예측 31(perf 22, safety 8, cost 1), 7절 28행, 셀 26, 시행 170 `[측정: 셀 파일과 예측 표에서 셈]`.
- **채점기**(`rows_gc.py`). 새 열 `stall_ctx`: 생존 rank마다 대상의 STALL 판정 줄의 `ctx=`, 없으면 그 앞 마지막 의심 줄의 `ctx=`; 서로 다른 값을 `+`로 잇고, 문맥을 이름 대지 않은 STALL 판정은 `none`.
  규칙은 `stall_ctx == 1`이라 "1+none", "0+1"은 거짓이다. 의심 줄 꼴은 괄호 안 `kind=`와 `stale_ms=` 사이나 뒤에 다른 낱말(`ctx=`)이 있어도 읽는다. 셀 env에 `GC_GPUHANG_CTX=k`가 있으면 hang 줄에
  `ctx=k`가 있어야 주입 기록(`inject_ok`)이다. 라이브러리 줄의 `ctx=` 자리는 조각이 정한다(`TODO(lib)`): 이 열은 줄 어디의 `ctx=<숫자>`든 읽는다.
- **자체 시험** B6: 합성 반례 시행 다섯(n1, n3–n5는 판정 줄에, n2는 의심 줄에만 `ctx=1`), `stall_ctx` "1", 판정 "맞음"; GPU hang 셀(B5)은 `none`; 규칙이 "1+none", "0+1", 빈 값, 0, `none`, STALL_HELPER 사본,
  9 900 ms를 거짓으로; 따로 만든 시행에서 생존 rank 하나가 문맥 0을 대면 "0+1", 문맥이 없으면 "1+none", hang 줄이 `ctx=all`이면 `inject_ok` 0. 창 규칙 수 검사는 5에서 6으로.
- 확인: `python3 test_rows_gc.py` 142 checks, 0 failed(이전 136), `python3 check_cells_gc.py` ok(7절 28행, 셀 26, 3절 키 31, drift 0) `[측정: 로컬 실행]`. 클러스터 실행 없음.
- **남은 것.** 라이브러리 조각의 줄 꼴(`ctx=`의 자리)과 이 열을 맞춰 보기, driver 빌드, 반례 셀의 하드웨어 한 번. `hold_gc.sh` 머리 주석의 "section 7 rows 23, 24"는 이제 24, 25다(이 작업의 고칠 범위 밖이라 그대로).

## READ 성공률의 장치 줄 READ와 비용 팔의 probe 증거 (2026-10-23, Codex 지적 둘)

`rows_gc.py`와 `test_rows_gc.py`만 고쳤다. `predictions_gc.csv`, `score_gc.py`, 라이브러리, 클러스터 실행은 없다.

- **지적 1: READ 성공률.** `read_success_pct`가 probe summary의 페이지 `reads`/`ok`만 더했고, 장치 줄 READ(`dev_reads`/`dev_ok`, ctxall부터 문맥마다)는 빠졌다. 요약이 빠진 프로세스도 보지 않았다.
  이제 `read_success_pct` = (페이지 ok + 장치 ok) / (페이지 READ + 장치 READ)이다. 페이지 READ는 전처럼 `reads − after_end_reads`, 장치 READ는 `dev_reads`(모든 문맥의 합)다.
  새 열은 `dev_read_n`, `dev_read_ok_n`, `read_page_success_pct`, `read_dev_success_pct`, `probe_missing`이다. 합은 모든 rank와 예비 프로세스의 로그에서 낸다(`_spare*.log` 전부).
- **필요 조건.** 최종 세대의 프로세스(`required_procs`, 제어 요약의 `ctrlsum_required`와 같은 규칙)마다 최종 세대의 다른 rank 하나에 요약 하나가 있어야 한다. 라이브러리는 teardown에서 READ QP가 있는 상대마다 한 줄을 쓴다 `[소스: gc_layer_smokefix.diff, gc_layer_ctxall.diff]`.
  상대가 장치 줄을 이름 댔으면(요약의 `dev_line=1`, 또는 그 상대의 status page 줄 "device line named") `dev_reads=`, `dev_ok=`가 있어야 한다. `dev_ctx=`나 상대 페이지의 `contexts=`가 1보다 크면 그 수만큼 값이 든 `dev_reads_ctx=`, `dev_ok_ctx=`도 있어야 한다.
  빠진 것은 `probe_missing`에 `proc:p<상대>`(요약)나 `proc:p<상대>:<칸>`(계수)로 남는다. 요약이 빠지면 모든 수와 비율이, 계수가 빠지면 그쪽 수와 비율이, 무엇이든 빠지면 `read_success_pct`가 빈칸이 된다. 0으로 채우지 않는다.
  status page 줄도 요약도 없는 시행(tcp 빌드)은 전처럼 이 열들이 빈칸이다.
- **지적 2: 비용 팔.** `runner costgc` 경로는 mirror의 파서만 불러서, READ가 한 번도 없던 probe-on 시행도 유효였다. 새 `cost_probe`가 시행의 `_r0.log`, `_r1.log`(수신 시각 없는 원래 출력)를 읽는다.
  probe-on은 rank마다 상대에 대한 요약이 있어야 하고, 그 요약의 페이지 READ와 장치 READ가 0보다 커야 한다(장치 줄이 켜져 있을 때 문맥마다). probe-off는 요약이 없거나 `reads`, `after_end_reads`, `dev_reads`가 모두 0이어야 한다. tcp 팔은 보지 않는다.
  시간 창: driver kv의 `launch_mono_ms`부터 `launch_mono_ms + kernel_ms`까지다. rank의 status page 줄(없으면 첫 `mono_ms` 줄)이 창 끝 이하이고 요약이 창 시작 이상이면 겹친다(`covers` 또는 `overlaps`), 아니면 `outside`로 무효다.
  `launch_mono_ms`나 줄의 `mono_ms`가 없으면 `no_time`으로 적고 무효로 하지 않는다. 어긋나면 `cost_valid` 0이고, 채점기는 기존 표시 `cost_invalid`로 센다. 새 열은 `cost_probe_evidence`(`ok` 또는 이유)와 `cost_probe_window`다.
- **시험.** `probe_checks` 8개, `cost_checks` 12개를 더했다. 합성 probe summary를 rank마다 상대 셋에 한 줄씩(예비 프로세스 포함)으로 바꿨다(라이브러리 꼴). 결과는 다음과 같다 `[측정: 로컬 실행]`.
  - 장치 줄이 켜진 깨끗한 자료: `none_probe_clean` 맞음.
  - 한 시행의 장치 READ 실패 하나: 페이지 비율은 100 %(옛 식), 전체는 100 % 아래, 틀림.
  - rank 1의 상대 2 요약을 모든 시행에서 지움: 자료 부족. 같은 것을 한 시행에서만 지움: 틀림(아래 남은 것).
  - 장치 줄이 켜진 채 `dev_ok=`를 지움: 자료 부족.
  - 활성 예비 프로세스의 요약이 없음, 상대 페이지는 named인데 요약에 `dev_*`가 없음, `dev_ctx=2`인데 `dev_ok_ctx` 값이 하나: 셋 다 빈칸이고 이름이 남는다.
  - 비용: 요약 지움, 페이지 READ 0, 장치 READ 0, 문맥 하나의 READ 0, 창 앞의 요약, probe-off의 READ 15는 무효다. 깨끗한 probe-on, 시각 없음, probe-off의 요약 없음과 READ 0, tcp 팔은 유효다.
  - 변이: 옛 식(페이지만, 필요 조건 없음)을 되살리면 `probe_checks` 8개 중 7개가 실패하고, 증거 검사를 끄면 `cost_checks` 12개 중 7개가 실패한다.
  - `python3 test_rows_gc.py` 162 checks, 0 failed(이전 142). `python3 check_cells_gc.py` ok, drift 0.
- **smoke 다시 계산.** smoke1–5의 `a*/raw` 사본 25시행(세션 스크래치, 원자료는 읽기만)에서 고치기 전과 뒤를 견줬다. 비용 시행은 smoke에 없다(모두 `runner gcr`). 결과는 다음과 같다 `[측정: rows_gc.all_rows]`.
  - `read_success_pct`가 바뀐 시행은 넷이다. 넷 모두 장치 READ 실패 3개가 새로 들어갔다.
    - smoke3 a2: 99.654 → 99.651.
    - smoke3 a5: 99.652 → 99.649.
    - smoke5 a1: 99.716 → 99.714.
    - smoke5 a2: 99.718 → 99.716.
  - 고치기 전에도 100 % 아래였으므로 판정 방향은 같다.
  - smoke1 a1, a2는 `probe_missing`이 열두 칸 모두다(teardown 요약 고침 전 빌드라 요약이 없음). `read_success_pct`는 전에도 빈칸이었다.
  - smoke1 a3, a4, a6은 장치 줄이 없는 빌드여서 `dev_read_n` 0이다.
  - 나머지 smoke2–5 시행은 장치 READ가 모두 성공했고, `probe_missing`이 빈칸이다.
- **남은 것.**
  - `[미확인]` 한 시행만 빈칸이면 `score_gc.py`는 그 시행을 거짓으로 세어 "틀림"이 된다. 자료 부족(`LIB_COLS`)은 열이 모든 시행에서 빈칸일 때뿐이다. 한 시행의 빈칸을 자료 부족이나 다시 채움으로 보려면 `score_gc.py` 또는 8절 고침이 필요하다(이 작업 범위 밖).
  - `[미확인]` 새 열은 `LIB_COLS`에 없다.
  - `[미확인]` gin_ts2_mi kv의 `kernel_ms`가 실제로 있는지 확인하지 않았다(harden의 `recount.py`가 같은 계통 kv에서 읽음). 없으면 창 시작만 본다.
  - `[추론]` 라이브러리 `mono_ms`와 driver의 `launch_mono_ms`는 같은 프로세스의 CLOCK_MONOTONIC이다.
  - `dev_reads_ctx`의 합과 `dev_reads`가 같은지는 보지 않는다.
- **다시 확인 고침(Codex 2026-10-23, 비용 창).** 고친 첫 판에는 구멍이 둘 있었다.
  - 시각이 없으면 `no_time`으로 적고 유효로 남겼다.
  - 페이지 생성부터 끝 요약까지 구간이 창에 걸치기만 하면 통과했다. 그래서 READ가 모두 창 앞이나 뒤에 있어도 `covers`였다.
- **이제 시각이 없으면 무효다.** kv `launch_mono_ms`, kv `kernel_ms`, rank의 status page 줄, 요약의 `mono_ms` 가운데 하나라도 없으면 `no_time`이다. 창 W는 `launch_mono_ms`부터 `launch_mono_ms + kernel_ms`까지다.
  두 값은 `gin_ts2.cu`의 `tLaunch`와 `tEnd − tLaunch`이고, 둘 다 CLOCK_MONOTONIC이다. 라이브러리의 `gdakiQ4MonoMs`도 같은 시계다 `[소스: gin_ts2.cu 141–146, 1231, 1437행]`. smoke 원자료에는 비용 시행이 없어서 kv 키를 자료로는 확인하지 못했다 `[미확인]`.
- **창 안 READ는 하한으로 증명한다.** 요약에는 합계만 있다. 구간 S는 status page 줄부터 요약까지다. 주기 P는 page 줄의 `probe_ms=`이고, 0이면 무효다. 주기당 READ 수 `per`는 장치 줄이 켜져 있으면 1 + 문맥 수, 꺼져 있으면 1이다. 상대는 하나다.
  - 창 밖 READ의 상한: S에서 W 밖인 두 조각마다 (floor(L/P) + 1) × `per`. 길이 L인 구간에 들어갈 수 있는 주기 READ의 최대이고, 규칙의 ceil(L/P) 이상이다.
  - `cost_probe_inwindow_lb`: 총 READ(페이지 + 장치)에서 이 상한을 뺀 값.
  - `cost_probe_expected`: max(1, floor(|W|/P) × `per` × 0.5). 지시문 식에 `per`를 곱했다. 문맥마다 READ가 있으므로 같은 기준으로 센다.
  - 하한이 기대값 이상이면 `covers`, 아니면 `reads_outside_window`로 무효다. S와 W가 겹치지 않으면 `no_overlap`으로 무효다.
- **시험.** 비용 경우를 14개로 늘렸다.
  - 무효: 시각 없음, `kernel_ms` 없음, 창 앞에서 끝난 구간, 창 뒤에서 시작한 구간, 주기의 3분의 1 READ(문맥 둘).
  - 유효: 문맥 둘의 전 주기 READ. 하한 84, 기대 45.
  - 변이: 하한 검사를 끄면(`COST_PEERS` 0) 셋이 실패한다.
  - `python3 test_rows_gc.py` 167 checks, 0 failed(이전 162). `python3 check_cells_gc.py` ok, drift 0 `[측정: 로컬 실행]`.

## 여섯째 smoke에서 본 시험 쪽 사실 (2026-10-23, 실행기 고침 없음)

- driver `gin_mi.cu` `6cb4ff28`를 `build_driver_gc.sh mi`(`MIOUT=mi_s6`, 머리 `gc_ca2`)로 처음 빌드했다: `gin_mi` `2c57f99f`, 경고 0 `[측정]`.
- 반례 셀 `gc4_gpuhang12000_ctx1_fence` n 1: hang 줄 `ctx=1`(`inject_ok=1`), 생존 셋의 의심 줄 `(kind=gpu stale_ms=2000.7 ctx=1)`와 판정 줄 `STALLED to 3 rank(s); ctx=1;`을 `rows_gc.py`가 읽어
  `stall_ctx=1`이다. 위 절의 `TODO(lib)`(줄의 `ctx=` 자리)는 실제 줄과 맞다 `[측정: ../../results/20261023_smoke6/SMOKE.md (e)]`. 모든 context가 멈추는 셀은 `stall_ctx=0+1`이었다(그 예측은 이 열을 쓰지 않음).
- 새 열 `dev_read_n`, `dev_read_ok_n`, `read_page_success_pct`, `read_dev_success_pct`, `probe_missing`이 context 넷인 실제 요약 줄(`dev_ctx=4 dev_reads_ctx=a/b/c/d`)에서 채워졌고 `probe_missing`은 여섯 시도 모두 빈칸이다 `[측정]`.
- 복원 뒤 4.7–5.2 s의 READ 시한 줄은 driver가 예비 프로세스에서 끝 유예를 건너뛰어(`gin_mi.cu` 1011행) 복원된 화신이 먼저 teardown하기 때문으로 본다 `[추론: 같은 SMOKE.md 절]`. 판정 뒤라 `probe_timeout_n`에 들지 않는다.

## pilot 1의 실행기 몫 (2026-10-23)

- `hold_gc.sh`: pilot 회귀 hold `PRG-<b>-<mirror hold>`(`RG-`와 같은 셀을 n 1로; `P`로 시작하므로 pilot 폴더에서만). P0–P4에 tcp 회귀 대조 `mi4_kill3_ow@gct`가 없어서 더했고, `PRG-gct-G1`이 pilot 1 a7에서 돌았다 `[측정]`.
- `deploy_gc.sh`: 기존 묶음의 md5 목록(`EXIST`)이 폴더를 가리키는 링크(`~/rs-bundle/gc_smoke*`)에 `md5sum`을 걸어 오류가 났고, `set -e`로 쓰기 전에 멈췄다. 이제 일반 파일만 md5를 내고 링크는 `경로 -> 대상`으로 적는다. 고친 판으로 `gc_pilot1`을 배포했다 `[측정]`.
- 결과와 셀 값 문제(`gc4_none_probe`의 창 크기, freeze 셀의 시작과 길이, credit 셀, `qperr_rec_gen_delta`의 셈, 비용 probe-on 팔의 증거, QUERY_QP 한도)는 [../../results/20261023_pilot1/PILOT.md](../../results/20261023_pilot1/PILOT.md)에 있다.

## 사전 등록 전 확정의 시험 쪽 몫 (2026-10-24, pilot 1 뒤 조율 세션 결정)

EXPERIMENT.md 12절 그날 "사전 등록 전 확정" 행의 시험 쪽이다. 라이브러리, launcher, 클러스터 실행은 없다. pilot 1 원자료는 읽기만 했다.

- **셀 env의 꼴(이번에 바꾼 것).**
  - `gc4_none_probe`: `STEPS=6000`(12 000은 받는 창 148 897 792 B가 rain에서 등록 실패, PILOT.md 문제 1).
  - freeze 셀 둘: `R3_ENV=NCCL_GIN_TS_TEST_FREEZE_PAGE=12000@2000`, `...=12000:helper@2000`, `STEPS=3000`. 값 꼴은 `<ms>[:helper][@<after ms>]`이고 `@`는 `:helper` 뒤다 `[소스: gc_layer_int.diff gdakiCtrlFreezeParse]`.
  - `gc4_credit_stall`: 바꾸지 않음(`R2_ENV=NCCL_GIN_CTRL_TEST_CREDIT_STALL=3000:500`, 꼴 `<start ms>:<length ms>`). 아래 셈.
  - `cells_gc.json` `prereg`: `confirm_ms` 20, `probe_ms` 100, `live_bound_ms` 10000, `launcher_stall_ms` 1000, `stop_len_tol_ms` 50, `pair_gap_limit_ms` 10, `query_qp_per_s` 4000과 근거.
  - `cells_gc.json` `cost.iters`: `{"lat4k": 150000}`. `run_cost_gc.sh`가 지표마다 읽고, 없으면 옛 값(3 000, 12)이다.
- **freeze의 셈** `[측정: pilot 1 a3 rank 3 로그]`.
  - 무장(`GINRS resume`) → FREEZE_PAGE 줄 0.4 ms, → ring live 줄 4.1 ms, → 걸음 0 약 840 ms. 600 걸음 약 4.71 s, 걸음당 7.86 ms.
  - `@2000`이면 멈춤은 live 뒤 약 1 996 ms, 걸음 약 148에서 시작한다(첫 확정 체크포인트는 걸음 약 20). 판정은 그 10 000–10 300 ms 뒤다.
  - `STEPS` 3000은 걸음 0 뒤 약 23.6 s다. 판정(live 뒤 약 12.0–12.3 s), 펜스와 복원(약 0.4 s) 뒤 약 11 s가 남는다 `[추론]`.
  - 주입 기록은 실제 시작 때 나는 FREEZE_PAGE 줄이라 `stop_judge_ms_min/max`의 기준은 바뀌지 않는다.
- **credit의 셈(창을 채우는 셀 값이 없음).**
  - 스위치: rank 2의 RECV 완료를 `<start>` ms 뒤부터 `<len>` ms 쥐고, 그동안 RECV를 다시 내지 않는다(credit이 돌아가지 않음) `[소스: gdakiCtrlRingSwOf, gdakiCtrlStallNow, gdakiCtrlRdmaCollect]`. pilot 1에서 그 줄은 rank 2의 live 줄 뒤 3 001 ms였다.
  - 기록 수: 상대마다 150(600 걸음, `CKPT_STEPS` 20, 체크포인트 30), 곧 체크포인트마다 상대마다 5, 초당 약 28 `[측정: a3 ring summary]`. 64칸을 넘기려면 한 받는 rank로 답 없는 기록 65개, 그 속도로 약 2.3 s다.
  - 그러나 걸음이 멈춤과 함께 선다. rank 0과 2 모두 걸음 375(멈춤 시작 + 57 ms) → 383(+530 ms)이고, 멈춤 끝(+500 ms) 뒤에 다시 간다 `[측정: a3 걸음 줄]`. 체크포인트마다 입력이 그 rank의 기록을 기다리기 때문으로 본다 `[추론]`.
  - 그래서 멈춤을 늘려도 나가는 기록이 늘지 않는다. pilot 1의 제어 요약 88줄(12 000 ms SIGSTOP 셀 포함)이 모두 `sendq_max=0 sendq_deferred=0`이다 `[측정: grep]`.
  - 남은 고를 것(조율 세션): 라이브러리가 CREDIT_STALL 동안 채움 기록을 보내는 스위치, 또는 `sendq_deferred >= 1`을 보고만 하는 예측 바꿈.
- **비용 kernel.** 3 000회는 kernel 45.4–46.5 ms, 회당 15.1–15.5 µs였다. 150 000회는 약 2.27–2.33 s라 100 ms 주기 22개가 든다 `[추론]`. lat 모드는 같은 칸을 다시 쓰므로 창 크기는 그대로이고, 장치 배열은 회마다 8 B × 3이다 `[소스: gin_ts2.cu 995–1083행]`.
- **채점기.**
  - `rows_gc.py`: `qperr_rec_gen_delta` = 다시 짝 맺은 기록 세대의 최대 − `REC_GEN0`(1). gen 0은 "짝 없음"이고 다시 짝 맺기 없는 상대의 ring summary는 모두 gen=1이다 `[소스, 측정: a3]`. `LIVE_BOUND_MS` 주석은 확정으로 바꿈.
  - `score_gc.py`: `inject_late`의 멈춤 길이 한도 `STOP_LEN_TOL_MS` 50(전에는 `inject_dur_off_ms > 1000`), 간격 한도 `PAIR_GAP_LIMIT_MS` 10(전에는 셀의 `SPARE_GAP_MS` 5). 둘 다 `prereg`에 있으면 그 값을 쓴다.
  - `score_gc.py` 비용 규칙: `cost: rule=within:<pct> judged_nodes=<n,...>`. 이름 댄 수신 노드만 판정하고 자료 부족도 그 노드로만 센다. 다른 노드는 "보고만: 이 수신 노드는 판정 밖"이다.
  - `predictions_gc.csv`: `finless_exit_report` 40–200 ms, `stall_none_refuse` `count(n_judge_stall_helper >= 1 and decline_n >= 1 and surv_released >= n_surv and subject_fenced == 0) >= 4`, `cost_probe_lat4k` `judged_nodes=sunny`, `no_tcp_control` todo의 bootstrap 34(보고만), `freeze_fence_restore` todo의 시작 기준.
- **실행기.**
  - `hold_gc.sh`: QUERY_QP 상한 = `RS_QUERY_RATE`(4000) × 시행 meta `wall_s`(올림). `run_gc.sh` 시행과 비용 실행에 건다. meta wall이 없으면 `RS_QUERY_CAP` 50 000, gin-remaining 회귀는 150 000 그대로다. 넘음 줄에 `(<rate> x wall <s> s)`를 붙인다.
  - pilot 1의 여덟 시행(50 000 넘음)은 새 상한 아래다: 초당 2 710–3 118회 `[측정: a3, a4, a5 qp_over.txt와 meta]`. 50 000 아래였던 짧은 시행 하나하나의 증가는 기록이 없어 보지 못했다 `[미확인]`. hold 평균은 초당 2 459–2 692회다.
  - `run_cost_gc.sh`: `cells_gc.json` `cost.iters.<metric>`를 읽음.
- **자체 시험** `test_rows_gc.py`: 186 checks, 0 failed(이전 172) `[측정: 로컬 실행]`.
  - 합성 시행은 W 30이라, `main()`이 채점 전에 `load_cells`를 감싸 `prereg.confirm_ms`를 비운다. 고정값 자체는 `prereg_checks`가 본다.
  - `prereg_checks` K: prereg 값, W 30은 `config`이고 W 20은 아님, 멈춤 길이 12.2와 50 ms는 남고 50.1, 400 ms는 `inject_late`, 간격 5.032와 10 ms는 남고 10.2 ms는 `inject_late`, 비용 규칙은 sunny만 판정(rain +7.7 %는 보고만, 두 노드 판정이면 틀림).
  - `qperr_checks` K2: 다시 짝 맺기 한 번은 차이 1, 두 번은 2. `qp_err_repair`는 한 번에서만 참이고, 옛 열 값 2에서는 거짓.
  - J: `finless_exit_report` 40, 62, 127, 200 ms는 들고 39, 201 ms는 빠짐. `kill_judge_rdma`, `kill_no_witness`의 100–150 ms 검사는 그대로. `stall_none_refuse`는 풀림 4 대 3과 창 줄 없음에서 참이고, 풀림 2, 펜스된 대상, 거절 없음에서 거짓.
  - review 3: 창 규칙은 여섯에서 다섯(`stall_none_refuse`가 빠짐).
- **pilot 1 사본 재채점**(세션 스크래치에 a3 사본, `smoke_of`를 꺼 pilot 표시 끔, 계획 n 1; 원자료는 읽기만) `[측정: 로컬 실행]`.
  - 시행 조건: `qp_err_repair` 0/1 → 1/1(`qperr_rec_gen_delta` 2 → 1), `stall_none_refuse` 0/1 → 1/1(풀림 4, 생존 3, `subject_fenced` 0), `finless_exit_report` 0/1 → 1/1(62.0 ms).
  - `spare_absent_refused`의 시행은 `inject_late` 제외에서 채점(조건 1/1)으로 바뀜.
  - 판정은 모두 "자료 부족(n<k)"이다. k는 고치지 않았다.
- 확인: `python3 check_cells_gc.py` ok(drift 0, 7절 28행, 셀 26, 3절 키 31), 셸 `bash -n`(`hold_gc.sh`, `run_cost_gc.sh`) `[측정: 로컬 실행]`.

## pilot 2의 실행기 몫 (2026-10-23)

결과와 셀마다의 해설은 [../../results/20261023_pilot2/PILOT.md](../../results/20261023_pilot2/PILOT.md)에 있다. 라이브러리, launcher, 채점기, 셀과 예측 파일은 고치지 않았다.

- `hold_gc.sh`에 pilot 전용 hold 꼴 셋을 더했다(모두 `P`로 시작하거나 `COSTPILOT-`라 pilot 폴더에서만 돈다).
  - `PCELL-<셀>[+<셀>…]`: `cells_gc.json`의 `cells`나 `pilot_cells`에서 이름이 같은 항목 하나를 n 1로. 셀 env와 `launcher_env`, `bound_s`는 그 항목의 것. pilot 2 a1에서 바뀐 셀 여덟을 한 hold로 돌렸다 `[측정]`.
  - `PRG-<빌드>-<h1>+<h2>…`: gin-mirror hold 여럿의 셀을 pilot hold 하나에 n 1로(본 실행 꼴 `RG-`는 그대로 hold 하나). a4–a7에서 돌았다.
  - `COSTPILOT-<노드>-<묶음 수>`(1–6): 비용 묶음 여러 번, 짝수 묶음은 팔 차례를 뒤집음(`cost_family`의 기존 규칙). a2, a3에서 2묶음씩 돌았다.
- `hold_gc.sh` `gc_after_trial`: gin-mirror의 두 죽음 셀(`*_kill2_kill3*`)에서 launcher 기록 QP 잃음 줄은 STOP_launcher 대신 `<결과>/la_qp_twokill.txt`에 적는다.
  - 까닭: `rows_gc.py --stops`의 `la_qp_err_n`은 `subject_rank`(첫 kill)만 빼서 둘째 kill(KILL2_RANK 3)의 줄을 센다 `[소스: rows_gc.py la_counts]`. pilot 2 a4가 이것으로 STOP였다(`mi4_kill2_kill3_ow`, 줄 2, 모두 rank 3).
  - 고친 뒤 a6의 `mi4_train_kill2_kill3`에서 같은 줄 2를 적기만 했다 `[측정]`. 채점기의 `launcher_changed` 제외는 그대로라 두 시행은 제외된다. TODO(scorer): `la_counts`가 KILL2_RANK도 빼야 한다.
  - 고침은 새 파일을 쓰고 옮겨(rename) 넣었다. a5(돌던 hold)는 옛 파일을 읽던 중이었고 그 hold에는 두 죽음 셀 시행이 남지 않았다.
- 확인: `bash -n hold_gc.sh` `[측정: 로컬 실행]`. 자체 시험(`test_rows_gc.py`)은 실행기 파일을 읽지 않아 다시 돌리지 않았다.
- 실행기 쪽에서 본 남은 일(PILOT.md 문제 5): `run_gc.sh`의 ss 두 스냅숏은 이른 kill 셀에서 죽은 rank의 소켓이 닫혀 `ss_tx_delta_bytes`가 음수(−23 712, −19 969)이거나 둘째 스냅숏이 없어 빈칸이 된다(유효 rdma 시행 35개 중 6). 소켓마다의 차로 바꿀지, kill 앞에서 잴지는 결정 대기다(고치지 않음).
