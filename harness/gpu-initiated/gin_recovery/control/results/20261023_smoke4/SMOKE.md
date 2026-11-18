# gin-control 넷째 하드웨어 smoke (2026-10-23, 채점 안 함)

커밋된 라이브러리(worktree HEAD `16016519`, `impl/gc_layer_int.diff` `5ed121f4`: 창이 호스트 박동을 읽음, 증인 끔 = 소켓 증거 없음, launcher 쪽 READ 하나, REJOIN 받아들임 재시도,
제어 요약의 TCP live 앞뒤 나눔)를 실제 RNIC에서 처음 돌린 smoke다. 셀은 여섯이고 시행마다 n 1, 본 실험과 pilot에 들지 않는다. 시도는 여섯(a1–a6, 한도 여덟)이고 모두
`harness/gpu-initiated/common/cluster_run.sh` 안에서 `impl/test/cells_gc.sh` → `run_gc.sh`(worktree 판 그대로)로 돌았다. 셀 1, 2, 5, 6이 통과해 거기서 멈췄다.
라이브러리 고침은 없다(`gc_layer_smoke4fix.diff` 없음). 표시: `[측정]` 원자료에서 다시 셈, `[소스]` 코드를 읽음, `[추론]` 해석, `[미확인]` 확인 안 함.

- 트리: 세션 스크래치 `agent_gc_p2a2/nccl-src`. 작업 트리를 ln4 커밋(`gin-mirror ln4 (mi_layer.diff dcd30859)`)에 `patch`로 `gc_layer_int.diff`를 적용한 결과와 `cmp`로 견줘 같음, `git diff --diff-algorithm=patience`의 md5도 `5ed121f4` `[측정]`.
- 빌드: `s4.sh gc`(`chain_s7.sh`의 머리 이름, `GCOUT=gc_sm4`), 경고 0. driver는 이 실험의 사본 [../../impl/test/driver/gin_mi.cu](../../impl/test/driver/gin_mi.cu)(새 스위치 `GC_GPUHANG_IT`)를
  [../../impl/test/driver/build_driver_gc.sh](../../impl/test/driver/build_driver_gc.sh) `mi`로. launcher는 `impl/launcher/build_launcher.sh all`(단위 28 시험 762 검사 실패 0) `[측정]`.
- 묶음 `gc_smoke4`: 두 노드의 새 폴더 `~/gi-bundle/gin_ts2/gc_smoke4/{lib/gc,gctest}`와 링크 `~/rs-bundle/gc_smoke4`(smoke3와 같은 배치). 두 노드 md5 같음, `ldd`의 libnccl은 묶음의 것 [deploy/deploy_a1.txt](deploy/deploy_a1.txt).
- 실행 스크립트(저장소 밖, 세션 스크래치 `agent_gc_smoke4/`): `run_smoke4.sh`(smoke3의 것에서 `LAUNCHER_ENV`를 부르는 쪽이 넘기게만 바꿈), `deploy_smoke4.sh`(smoke3의 것 그대로), `cols.py`(`rows_gc.py`를 돌리고 열을 뽑음).
- 로그는 모두 `sed -E 's/([0-9]{1,3}\.){3}[0-9]{1,3}/<addr>/g'`를 거쳐 옮겼다. 이 폴더에 IPv4 꼴 문자열 0건, 관리망 주소 0건 `[측정: grep]`.
- 아래 시간은 시도마다 `rows_gc.py`(각 시도의 `trials.csv`)의 열과 줄의 `mono_ms`에서 다시 셈한 것이다. 범위는 한 시도 안의 생존 rank 셋의 범위다.

## 빌드와 묶음

| 무엇 | md5 | 비고 |
|---|---|---|
| libnccl `gc_sm4` | `3b901b12391b4b15234950f43486db32` | 커밋된 트리 그대로; s7 빌드와 같은 md5 |
| `gin_mi` | `563cb460ea0b78c6f614028032934fe9` | `gin_mi.cu` 사본 `9f4568d9`(원본 gin-mirror `556804c0`), 머리 digest `65fdf19b`, 매크로 켬 |
| `gin_launcher` | `3af84d2a654cd0f55adb7003a1a74f44` | `gin_launcher.c` `5b62a1f5`; smoke2, smoke3의 바이너리와 같은 md5 |

## 시도마다

| 시도 | 셀 | 결과 | 판정 원인(행) | 근거 |
|---|---|---|---|---|
| a1 | (1) `gc4_none_ow` + 따뜻한 예비 프로세스 | 통과 | 판정 0 | [a1/raw/](a1/raw/) |
| a2 | (2) `gc4_kill3_ow` | 통과 | FIN+STALE ×3(4행, 확인 창) | [a2/raw/](a2/raw/) |
| a3 | (3) `gc4_kill3_ow_nowitness` | 통과 | EXITED ×3(3행, launcher 보고) | [a3/raw/](a3/raw/) |
| a4 | (4) `gc4_fdhold_sock_kill3_noreport`(`NO_EXIT_REPORT`) | 예측과 다름(통과 셀 아님) | STALL_HELPER ×3(15행), READ 실패 길이 아님 | [a4/raw/](a4/raw/) |
| a5 | (5) `gc4_stop12000_fence` | 통과 | STALL_HELPER ×3(15행) | [a5/raw/](a5/raw/) |
| a6 | (6) `gc4_gpuhang12000_fence`(새 셀) | 통과 | STALL ×3(14행) | [a6/raw/](a6/raw/) |

## 셀 (1) 장애 없음 (a1)

- 네 rank `resume_rc=0`, 600 step, `xchg=ok`, `x_match=1`, `sig_exact=1`. 판정, 의심, 확인 창 0줄. 생존 READ 성공 100 %, 박동 간격 최대 1.359 ms, `W=20 W_rule=20` `[측정]`.
- 예비 프로세스: go 파일까지 2 819.1 ms, 띄운 뒤 HELLO 399.1 ms, READY. 예비 프로세스의 끝 코드 137은 launcher shutdown의 SIGKILL이다.
- STOP: `la_stop_n=0 la_qp_err_n=0`, 남은 프로세스 0.

## 셀 (2) kill rank 3 (a2)

| 단계 | kill = 0 | 줄(앞부분) |
|---|---|---|
| FIN과 창 열림 | 약 0.3 ms(rank 1, 같은 노드) | `socket to rank 3 closed cause=FIN … liveness=pending`, `confirm window for rank 3 opened by FIN W=20 over the watch beat` |
| 창 닫힘과 판정 | 20.8–21.2 ms; FIN → 판정 − W = 0.37–0.78 ms | `closed: STALE (… READ1 +0.178, READ2 +10.111, W=20 …)`, `rank 3 judged dead (cause=FIN+STALE)`, `ended by the judgement table (table row 4, 20.494 ms after the FIN)` |
| FENCE | 26.6 ms에 launcher SIGKILL | `FENCE of rank 3 incarnation 0 from rank 2: SIGKILL sent through its pidfd` |
| FENCED | SIGKILL 뒤 91.6 ms | `rank 3 incarnation 0 FENCED: the group ended 91.619 ms after SIGKILL` |
| 복원 | 판정 → 게시 164.3 ms, kill → 게시 185.1 ms, hold 최대 160.4 ms | `rank 3 restored as incarnation 1 (on time; 164.3 ms after the hold start …)` |
| 데이터 | `data_equal=1`, `ow_data_equal=1`, `wait_held=1`, `revived_done=1` | `trials.csv` |

- **어느 쪽이 먼저였나.** 확인 창의 FIN+STALE(W + 2 ms 안)이다. launcher EXITED는 오지 않았다: 판정 뒤 hold가 FENCE를 보냈고 launcher의 끝 보고는 FENCED였다 `[측정]`.
  smoke3의 창은 GPU 줄을 읽어 `alive`(8행)였고 판정은 EXITED(약 102–106 ms)였다. 창이 호스트 박동(`over the watch beat`)을 읽는 지금 라이브러리는 9.3절 어림대로 4행으로 판정했다.

## 셀 (3) kill rank 3, 증인 끔 (a3)

- kill → launcher EXITED 110.9 ms, kill → 판정 110.7–110.9 ms(셋 모두 `cause=EXITED`, 3행), 퍼짐 0.19 ms. FENCE 없음(EXITED가 펜스 끝). 판정 → 게시 73.5 ms, kill → 게시 184.2 ms, 데이터 같음 `[측정]`.
- 증인 끔: 소켓 FIN 줄 3개 모두 `liveness=ignored (the witness is off: no window, no judgement; …)`, 확인 창이 FIN으로 열린 줄 0, `witness_pairs=0` `[측정]`. smoke3 요청 2(증인 끔이 창을 엶)는 이 라이브러리에서 닫혔다.

## 셀 (4) `NO_EXIT_REPORT` (a4): 예측한 두 길 어느 쪽도 아님

- kill → launcher `exited; EXITED not sent (test switch NO_EXIT_REPORT)` 63.4 ms. 증인 끔이라 FIN은 `liveness=ignored`. 그 뒤 판정은 READ 실패(3.5–4.5 s)가 아니라 kill 뒤
  10 091.5–10 094.9 ms의 멈춤 판정 STALL_HELPER ×3(15행)였다. 판정 앞에 READ 시한 줄 0, 의심 줄 `kind=watch stale_ms=2000.x` 셋 `[측정]`.
- 생존 rank 셋의 rank 3 쪽 probe 요약: `reads=169 ok=169 timeout=1`, 장치 줄 `dev_reads=167 dev_ok=167 dev_quiet=167` `[측정]`. 곧 죽은 프로세스의 페이지와 장치 줄 READ가 10 s 내내 성공했고
  호스트 박동만 멈춰 15행이 됐다. 판정 뒤 FENCE → launcher `already ended; FENCED`(0.03 ms) → 활성화, 판정 → 게시 78.4 ms, 데이터 같음.
- 까닭은 `[미확인]`. 같은 시행에 FD_HOLDER 자식(`gin_fdhold`, `holds 0 fd(s)`)이 판정 뒤까지 살아 있었다(실행기가 판정 뒤 정리, `fdhold_killed … why=bound`). 자식은 fork 뒤 3 이상의 fd를 닫는다 `[소스]`.
  죽은 프로세스의 QP와 MR이 왜 READ에 답했는지(fork가 물려준 무엇이 자원을 붙잡는지)는 이 smoke로 가르지 못했다. 아래 요청 1.

## 셀 (5) SIGSTOP 12 000 ms, 펜스와 복원 (a5)

- STOP → 판정 10 008.3–10 010.3 ms(STALL_HELPER ×3, 15행), 퍼짐 1.96 ms, 의심 줄 셋. FENCE SIGKILL → FENCED 123.9 ms, 판정 → 게시 197.5 ms, hold 최대 193.7 ms.
  SIGCONT 12 000.9 ms 뒤 `present=0`(펜스가 이미 끝냄), 펜스 뒤 바뀐 칸 0, 데이터 같음, `subject_fenced=1` `[측정]`.

## 셀 (6) GPU hang, 펜스와 복원 (a6, 새 셀)

| 단계 | hang 줄 = 0 | 줄(앞부분) |
|---|---|---|
| hang 시작 | 0(실행 뒤 2.2 ms에 spin을 봄, 걸음 155) | rank 3 `GINRS gpuhang rank=3 step=155 spin=1 wait_ms=2.208`; kv `gpuhang_it=155 gpuhang_step=155 gpuhang_seen=1` |
| 의심 | 약 2 030 ms, 셋 모두 `kind=gpu` | `rank 3 suspected (kind=gpu stale_ms=2000.x)` |
| 멈춤 판정 | 10 032.1–10 033.3 ms, 퍼짐 1.23 ms | `rank 3 (incarnation 0) judged stalled (liveness stall judged (STALL)); STALLED to 3 rank(s); the hold when armed, then FENCE …` |
| FENCE | 10 038.9 ms에 launcher SIGKILL | `FENCE of rank 3 incarnation 0 from rank 2: SIGKILL sent through its pidfd` |
| FENCED | SIGKILL 뒤 106.9 ms | `rank 3 incarnation 0 FENCED: the group ended 106.927 ms after SIGKILL` |
| 복원 | 판정 → 게시 180.5 ms, hold 최대 177.5 ms | `rank 3 restored as incarnation 1 (on time; 179.3–181.4 ms after the hold start …)` |
| 데이터 | `data_equal=1`, `ow_data_equal=1`, `wait_held=1`, `revived_done=1`, 펜스 뒤 바뀐 칸 0 | `trials.csv` |

- 판정 원인은 셋 모두 STALL(14행)이고 STALL_HELPER는 0이다. 판정받은 rank는 rank 3 하나뿐이다: 생존 rank가 서로를 14행으로 본 줄 0(`notes_live.md` 7절 1의 위험은 이 시행에서 나지 않음) `[측정]`.
  예측 `gpuhang_fence_restore`의 시행 조건(10 000–10 500 ms, FENCE → FENCED → 활성화, 데이터 같음)을 이 시행이 만족한다 `[측정, n 1, 채점 아님]`.
- 호스트 박동은 계속 올랐고(의심 원인이 `gpu`, 판정이 STALL) 펜스의 SIGKILL이 spin 중인 프로세스를 끝냈다(그룹 끝까지 106.9 ms).

## 제어 요약의 TCP 나눔 (a1–a6, 프로세스마다 마지막 요약 줄)

- rank 프로세스마다 `tcp_record_bytes=7488`(a1) 또는 그 시도의 값이고, 모두 `tcp_record_bytes_prelive`(live 전)이며 `tcp_record_bytes_live=0`, `tcp_data_bytes_prelive=0`, `tcp_data_bytes_live=0` `[측정: a1 요약 줄 넷]`.
  시도마다 `rows_gc.py`의 `tcp_ctrl_bytes`(live 뒤 몫)는 6/6 시도에서 0, `tcp_record_bytes_prelive` 합은 a1 29 952, a2 16 848, a3 16 848, a4 20 592, a5 16 848, a6 16 848 B `[측정]`.
- `ss_tx_delta_bytes=0`, `witness_pairs == witness_expected`(증인 켬 6, 끔 0), `ring_live_all=1` 모든 시도 `[측정]`.

## 남은 것과 요청 (고치지 않음)

1. **a4: 죽은 프로세스의 페이지 READ가 10 s 성공.** `NO_EXIT_REPORT` 셀이 READ 실패 길(11행, 3.5–4.5 s)이 아니라 15행으로 판정됐다. FD_HOLDER 자식이 무엇을 쥐어 QP와 MR이 남는지
   보지 못했다 `[미확인]`. 이대로면 3절 `finless_read_fail`(원인 NORESP)은 이 셀에서 참일 수 없다. FD_HOLDER 없는 kill + `NO_EXIT_REPORT`로 갈라 볼 것을 제안.
2. `active_mtu_kv_min`이 5다(라이브러리 요약이 `ibv_mtu` 열거값 5 = 4 096을 냄). `no_tcp_control`의 `active_mtu_kv_min == 4096`은 이대로 거짓이 된다(smoke3 열도 5). 채점기나 줄 꼴 중 하나를 맞출 것.
3. `rows_gc.py`의 `data_equal`, `ow_data_equal`은 장애 없는 시행에서 0이다(smoke3 a1도 같음). 셀 1의 데이터는 kv(`x_match`, `sig_exact`, `xchg=ok`)로 읽었다.
4. `trials.csv`에는 `tcp_record_bytes_live`, `tcp_data_bytes_prelive`, `tcp_data_bytes_live` 열이 없다(`tcp_record_bytes_prelive`와 live 뒤 몫 `tcp_ctrl_bytes`만). 위 TCP 나눔의 live 값은 요약 줄에서 읽었다.
5. 아직 실제 NIC에서 돌지 않은 것: `gc4_stop12000_none`, 짧은 멈춤 셋, `DIE_RST`, `RST_GAP`, `FREEZE_PAGE` 두 꼴, `QP_ERR`, `DROP_UD`, `CREDIT_STALL`, 관리망 끊김, `gct`/`gcp`, 채점.
