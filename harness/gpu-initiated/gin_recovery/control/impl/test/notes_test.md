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
| `cells_gc.json` | 7절 27행(`rows`), cell@build 27개(`cells`: env, 주입, n, 대조 팔, 찾는 키, 시행 한도), 본 실행 hold C1–C11과 pilot hold P0–P4, 회귀(gin-mirror `cells_mi.json`의 비용 밖 hold 여덟을 `@gct`, `@gc`로), 비용 가족 probe, 로컬 항목 |
| `check_cells_gc.py` | 셀 파일과 예측 표를 EXPERIMENT.md 3, 7절에 맞춰 봄(행 수, 셀 이름, 빌드, n, 찾는 키마다 셀 하나 이상, 셀마다 예측 하나 이상) |
| `predictions_gc.csv` | 3절의 31행. 열은 gin-mirror의 `id,predicted,cells,acceptance`에 `per_trial,k_required,n_planned,control_arm,basis,todo`를 더함 |
| `launcher_gc.sh` | launcher 하나(start, info, stop). 0700 소켓 디렉터리, `--tc`, 기록한 PID와 시작 시각에만 신호 |
| `run_gc.sh` | 시행 하나. 9.9절 주입, launcher 확인, `active_mtu`, RNR 카운터, 끄는 차례 |
| `cells_gc.sh`, `hold_gc.sh`, `chain_gc.sh` | 셀의 n번, hold 하나(8절의 STOP), hold 사슬(`cluster_run.sh` 안) |
| `run_cost_gc.sh` | 비용 가족 probe의 실행 하나(팔 `probe-off`, `probe-on`은 `gcp`, `tcp`는 `gctp`) |
| `rows_gc.py`, `score_gc.py` | 시행별 열, 채점. gin-mirror의 `rows_mi.py`와 `score.py`를 고치지 않고 불러 씀 |
| `test_rows_gc.py` | 합성 로그 자체 시험 |
| `deploy_gc.sh` | 두 노드의 새 묶음 `~/rs-bundle/<RS_SET>/`에 라이브러리 다섯, driver, launcher |

## 설계에서 정한 것과 어긋남

- **launcher의 범위.** EXPERIMENT.md 5절과 9.5절은 "클러스터 hold 시작 때 한 번 띄우고(시행마다가 아님)"이고, 8절의 제외도 "시행 앞뒤의 pid와
  시작 시각"을 본다. 작업 지시는 "시행마다의 소켓 경로, 시행 폴더의 로그"였다. 둘 다 만들었다: 기본은 `LAUNCHER_SCOPE=hold`(hold마다
  노드마다 하나, 시행마다 앞뒤 pid와 시작 시각, 그 시행 구간의 launcher 줄을 시행 폴더 `<stem>_launcher_<node>.log`로 자름),
  `LAUNCHER_SCOPE=trial`이면 시행마다 새 소켓 경로로 띄우고 마지막에 끈다. 어느 쪽을 사전 등록할지는 메인 세션이 정한다.
- **hold의 launcher env는 하나.** `NO_EXIT_REPORT` 셀(`gc4_fdhold_sock_kill3_noreport`)은 hold C6에 혼자 둔다. hold가 launcher env를 섞으면
  `hold_gc.sh`가 거절한다.
- **회귀 셀은 gin-mirror의 이름, env, n 그대로.** `run_gc.sh`가 `run_mi.sh`의 kill 갈래(트래픽, 체크포인트 멈춤 hook, after_stable, seed의
  단계 kill, `SPARE_KILL_FIRST`)를 그대로 지닌다. seed 뽑기의 머리 글자도 `gin-mirror|`로 두어 같은 seed가 같은 kill 단계를 낸다.
- **둘째 죽음의 제외.** 8절과 9.5절대로 `mi4_kill2_kill3_ow@gc`류에서 `rearm_ok == 0`인 시행은 제외(`second_before_rearm`)다. gin-mirror에서는
  `rearm_ok`가 예측 `reimage_after_restore`의 일부였으므로, 이 제외 아래에서 그 예측의 다시 무장 조건은 늘 참이 된다 `[추론]`. 사전 등록 때
  다시 볼 것.
- **3절에 수치가 없는 것.** 판정식의 문턱은 모두 3절 원문에서 옮겼다. 3절에 수치가 없어 이 파일이 정한 것은 `predictions_gc.csv`의
  `todo` 열에 적었다: `restore_time_rdma`의 n 5 셀 k 4, `gate_fenced`의 490–510 ms(`gate_fenced.cc`의 검사에서 옮김), `regression_rdma`의
  gin-mirror ID 열하나, `regression_rdma_mirror_off`의 셀과 k, `kill_judge_rdma`가 gin-mirror kill 셀을 판정하지 않는 것, `cost_probe_lat4k`의
  2 %(3절의 `[초안]`).
- **셀 값의 자리 표시.** 3절과 7절에 없는 주입 매개변수(`DIE_RST` 3 000 ms, `RST_GAP` 시작 3 000 ms, 멈춤과 끊김 셀의 `STEPS`,
  `QP_ERR`, `CREDIT_STALL`, `DROP_UD` 값 꼴)는 `cells_gc.json`의 `todo`에 단계 이름과 함께 적었다.
- **떨어진 두 노드의 시각.** 같은 프로세스 안의 간격은 줄의 `mono_ms`, 같은 노드의 두 프로세스는 두 `mono_ms`, 노드 사이는 수신 시계(rain의
  CLOCK_MONOTONIC)다. sunny 줄은 ssh로 오므로 노드 사이 간격에는 그 지연이 든다. 열 `kill_judge_clock`이 어느 시계였는지 적는다.

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
| READ 요약 | `GIN/RC: rank %d: probe summary peer=%d reads=%u ok=%u remacc=%u noresp=%u timeout=%u gen=%u lat_med_us=%.1f lat_max_us=%.1f beat_gap_max_ms=%.1f torn=%u` (끝낼 때, 상대마다) | `TODO(p1)` |
| 증인 잃음 | `GIN/RC: rank %d: witness of rank %d lost; liveness alive` (판정 표 8행) | `TODO(p1)` |
| 시험 스위치 | `GIN/TS: rank %d: test switch DIE_RST: linger 0 on %d socket(s); SIGKILL now` | `TODO(p1)` |
| | `GIN/TS: rank %d: test switch RST_GAP: %d socket(s) reset, listener closed for %d ms` | `TODO(p1)` |
| | `GIN/TS: rank %d: test switch FD_HOLDER=sock\|uverbs: child gin_fdhold pid=%d holds %d fd(s)` (증인을 끈 셀은 0) | `TODO(p1)` |
| | `GIN/RC: rank %d: test switch FREEZE_PAGE=%d[:helper]: %s frozen` (멈춤 시작) | `TODO(p1)` |
| | `GIN/TS: TEST socket mute on\|off rank=%d peers=%d` | 있음(gin-harden) |
| 제어 요약 | `GIN/RC: rank %d: control summary tcp_record_bytes=%llu tcp_data_bytes=%llu tcp_conns=%u witness_conns=%u records_lost=%u records_dup=%u repairs=%u sendq_deferred=%u sendq_max=%u rnr=%u async=%u active_mtu=%u` (끝낼 때, 모든 프로세스) | `TODO(p2)` |
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

launcher의 줄(`GIN/LA: node %u: ...`)은 `../launcher/gin_launcher.c`에 이미 있는 그대로 읽는다(EXITED, "exited; EXITED not sent", FENCE의
SIGKILL, FENCED, `(STOP_launcher)`, "refused to signal", 활성화 LATER, ACCEPTED, REFUSED, QP 잃음, "is leaving", "listening on its Unix socket").

## TODO 목록 (라이브러리 쪽과 메인 세션)

1. `TODO(p1)` 위 표의 1단계 줄: 확인 창 둘, 의심, READ 시한, READ 요약, 증인 잃음, 시험 스위치 넷의 줄, rdma 빌드의 원인 이름.
2. `TODO(p1)` 시험 스위치의 값과 시작 기준: `DIE_RST=<ms>`, `RST_GAP=<시작>:<길이>`, `FREEZE_PAGE`의 시작 시각(셀 파일은 첫 무장 체크포인트 뒤를
   가정). `FD_HOLDER=sock`에서 증인이 꺼져 있을 때 넘길 소켓이 없음을 줄의 `holds 0 fd(s)`로.
3. `TODO(p2)` 제어 요약, 링 요약, 짝 맺기 줄 셋, 시험 스위치 셋의 줄과 값 꼴(`QP_ERR=<ms>:<peer>`, `CREDIT_STALL=<시작>:<길이>`,
   `DROP_UD=rejoin:<수>`), 비동기 이벤트 수 `async=`(8절의 STOP_async).
4. `TODO(p3)` 펜스 줄 둘과 바뀐 칸 줄. rank와 예비 프로세스가 launcher 소켓을 `NCCL_GIN_CTRL_LAUNCHER_SOCK`, 노드 번호를
   `NCCL_GIN_CTRL_LAUNCHER_NODE`로 읽는지(launcher 헤더의 `GL_SOCK_ENV`, `GL_NODE_ENV`). 같은 rank의 둘째 예비 프로세스가 받는 화신 변수
   (`run_gc.sh`는 `NCCL_GIN_RESTORE_SPARE_INC=2`를 줌). rdma 빌드에서 예비 프로세스가 아직 `NCCL_GIN_RESTORE_SPARE_ADDR`, `_PORT`를 읽는지.
   비용 셀의 측정 모드가 launcher 짝 맺기를 요구하는지. 끝날 때 launcher의 QP 잃음 줄 가운데 무엇이 8절의 "시험 스위치 셀 밖의 launcher QP
   ERR"인지(지금 채점기는 첫 "is leaving" 줄 전에 대상 rank 밖의 rank에서 난 것만 셈).
5. `TODO(p4)` `build_gc.sh`에 `gctc` 라이브러리 단계(지금은 전처리 검사만). gc 트리 헤더로 driver(`gin_mi`, `gin_mi_nomacro`, `gin_ts2_mi`,
   `mr/ff`, `mr/hold`)를 빌드하는 스크립트(gin-mirror의 `build_mi_test.sh`는 자기 트리만 받음; 이 묶음에 없음).
6. `TODO(pilot)` W, `gc4_none_probe`의 60 s에 맞춘 `STEPS`, 멈춤과 끊김 셀의 `STEPS`, 9.9절 끝의 채점하지 않는 12 000 ms 멈춤 셀(hold P4).
7. `TODO(prereg)` `predictions_gc.csv`의 `todo` 열 여섯 줄(위 "3절에 수치가 없는 것").
8. 이 환경에는 `shellcheck`가 없어 셸 스크립트는 `bash -n`만 통과했다.

## 자체 시험 실행

```
cd harness/gpu-initiated/gin_recovery/control/impl/test
python3 check_cells_gc.py                 # 셀 파일과 예측 표를 EXPERIMENT.md 3, 7절에 맞춰 봄
python3 test_rows_gc.py                   # 임시 폴더에 합성 시행을 만들고 지움
python3 test_rows_gc.py --keep <폴더>     # 그 폴더에 남김(SCORE.md, trials_scored.csv를 볼 수 있음)
```

합성 시행: 확인 창 판정 10, launcher 보고 판정의 정상 복원 10, READ 실패 판정 5, `(STOP_launcher)` 줄과 1 s 넘는 hold 1, 제외 둘(launcher
준비 안 됨, 확정 체크포인트 전 kill)과 smoke 1, 같은 rank의 둘째 kill 둘(무장 줄 뒤, 앞), 찢긴 줄 읽기가 있는 장애 없는 시행 10과 깨끗한
장애 없는 시행 5, 원인이 FIN 하나인 판정 1, `gate_fenced` 10줄. 2026-10-17 이 세션에서 돌린 결과: 검사 39개, 실패 0(passed). 확인
`check_cells_gc.py`: 7절 27행, 셀 27, 3절 키 31, ok.

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
