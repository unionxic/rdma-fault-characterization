# notes_test.md — gin-control 시험 쪽(실행기, 채점기)

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
| `cells_gc.json` | 7절 25행(`rows`), cell@build 23개(`cells`: env, 주입, n, 대조 팔, 찾는 키, 시행 한도), 본 실행 hold C1–C3, C5–C11과 pilot hold P0–P4, 회귀(gin-mirror `cells_mi.json`의 비용 밖 hold 여덟을 `@gc`로, `@gct`는 `regression.builds.gct.cells`의 `mi4_kill3_ow` 하나), 비용 가족 probe의 한 쌍, 로컬 항목. 2026-10-22 셀 줄임 전에는 27행, 27개, C1–C11(아래 "셀 줄임" 절) |
| `check_cells_gc.py` | 셀 파일과 예측 표를 EXPERIMENT.md 3, 7절에 맞춰 봄(행 수, 셀 이름, 빌드, n, 찾는 키마다 셀 하나 이상, 셀마다 예측 하나 이상, 회귀 빌드의 `cells` 목록) |
| `predictions_gc.csv` | 3절의 28행(2026-10-22 셀 줄임 전 31행). 열은 gin-mirror의 `id,predicted,cells,acceptance`에 `per_trial,k_required,n_planned,control_arm,basis,todo`를 더함 |
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
