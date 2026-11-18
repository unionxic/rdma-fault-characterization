# gin-control 여섯째 하드웨어 smoke (2026-10-23, 채점 안 함)

라이브러리 `impl/gc_layer_int.diff` `f4819515`(저장소 ward QP ERR 확인 뒤 활성화, 모든 GIN context의 GPU 진행 줄)와 credit READ 재시도를 넣은 launcher를 실제 RNIC에서
처음 돌린 smoke다. 셀은 여섯이고 시행마다 n 1, 본 실험과 pilot에 들지 않는다. 시도는 여섯(a1–a6, 한도 여덟)이고 모두 통과해 거기서 멈췄다. 모든 시도는
`harness/gpu-initiated/common/cluster_run.sh` 안에서 `impl/test/cells_gc.sh` → `run_gc.sh`(worktree HEAD `ce876b88` 판 그대로)로 돌았다.
라이브러리 고침과 실행기 고침은 없다(`gc_layer_smoke6fix.diff` 없음, `run_gc.sh`와 `cells_gc.json` 그대로). 표시: `[측정]` 원자료에서 다시 셈, `[소스]` 코드를 읽음, `[추론]` 해석, `[미확인]` 확인 안 함.

- 트리: 세션 스크래치 `agent_gc_p2a2/nccl-src`, HEAD `39545f5`, 작업 트리 깨끗. ln4 커밋 `f53e5d2` 대비 `git diff --diff-algorithm=patience`의 md5 `f4819515`가 worktree `impl/gc_layer_int.diff`의 md5와 같음 `[측정]`.
- 실행 스크립트(저장소 밖, 세션 스크래치 `agent_gc_smoke6/`): `run_smoke6.sh`(smoke4의 `run_smoke4.sh`에서 경로와 태그만 바꿈), `deploy_smoke4.sh`(그대로), `cols.py`(smoke4의 것에 새 열 이름만 더함),
  `postrestore.py`(복원 뒤 READ 시한 줄의 시각). 셀 env는 `cells_gc.json`의 것을 그대로 넘겼고, (f)에는 셀의 `launcher_env`를 `LAUNCHER_ENV`로 넘겼다.
- 로그는 모두 `sed -E 's/([0-9]{1,3}\.){3}[0-9]{1,3}/<addr>/g'`를 거쳐 옮겼다. 이 폴더에 IPv4 꼴 문자열 0건, 관리망 주소 0건 `[측정: grep]`.
- 시간은 시도마다 `rows_gc.py`(md5 `215bbf0b`, 각 시도의 `trials.csv`)의 열과 줄의 `mono_ms`에서 다시 셈했다. 범위는 한 시도 안의 생존 rank 셋의 범위다.
  `trials.csv`는 가린 사본에서 다시 냈고, 스크래치 원본에서 낸 것과 원자료 경로 칸 하나만 다르다 `[측정: cmp]`.

## 빌드와 묶음

| 무엇 | md5 | 비고 |
|---|---|---|
| libnccl `gc_ca2` | `ea82cd710413b2253a14654431d0152c` | 위 트리의 `build_gc.sh gc`(다른 세션, 경고 0); `agent_gc_p2a2/build/lib`의 것과 같음 `[측정]` |
| `gin_mi` | `2c57f99f3b6fa6428c5bb4c2439bfc88` | [../../impl/test/driver/gin_mi.cu](../../impl/test/driver/gin_mi.cu) `6cb4ff28`(스위치 `GC_GPUHANG_CTX`)를 `build_driver_gc.sh mi`(`MIOUT=mi_s6`)로, 머리 digest `65fdf19b`(smoke4와 같음), 매크로 켬, 경고 0 [deploy/gin_mi.build.txt](deploy/gin_mi.build.txt) |
| `gin_launcher` | `d1aceaf68f00d99eafa4d585195f3348` | 스크래치 `lb-fix/`의 것(다시 빌드 안 함): `launcher_transport_verbs.c` `1b7b70e7`, `gin_launcher.c` `5b62a1f5`; 그 빌드의 단위 기록 29 시험 784 검사 실패 0 |

묶음 `gc_smoke6`: 두 노드의 새 폴더 `~/gi-bundle/gin_ts2/gc_smoke6/{lib/gc,gctest}`와 링크 `~/rs-bundle/gc_smoke6`. 두 노드 md5 같음, `ldd`의 libnccl은 묶음의 것 [deploy/deploy.txt](deploy/deploy.txt).

## 시도마다

| 시도 | 셀 | 결과 | 판정 원인(행) | 주입 → 판정(생존 셋) | 판정 → 게시 | READ 성공(페이지 / 장치 줄) | 근거 |
|---|---|---|---|---|---|---|---|
| a1 | (a) `gc4_none_ow` + 따뜻한 예비 프로세스 | 통과 | 판정 0 | - | - | 100 % / 100 %(장치 4 080) | [a1/](a1/) |
| a2 | (b) `gc4_kill3_ow` | 통과 | FIN+STALE ×3(4행, 확인 창) | 20.8–21.1 ms | 164.8 ms | 100 % / 100 %(3 395) | [a2/](a2/) |
| a3 | (c) `gc4_stop12000_fence` | 통과 | STALL_HELPER ×3(15행) | 10 070.9–10 072.4 ms | 174.3 ms | 100 % / 100 %(7 044) | [a3/](a3/) |
| a4 | (d) `gc4_gpuhang12000_fence` | 통과 | STALL ×3(14행), `stall_ctx=0+1` | 10 084.7–10 086.8 ms | 176.2 ms | 100 % / 100 %(6 988) | [a4/](a4/) |
| a5 | (e) `gc4_gpuhang12000_ctx1_fence`(새 셀) | 통과 | STALL ×3(14행), `stall_ctx=1` | 10 031.0–10 034.3 ms | 176.4 ms | 100 % / 100 %(6 960) | [a5/](a5/) |
| a6 | (f) `gc4_kill3_noreport_nofdhold` | 통과 | NORESP ×3(11행, READ 재시도 초과) | 3 682.4–3 684.2 ms | 74.0 ms | 99.722 % / 99.929 %(4 248/4 251) | [a6/](a6/) |

- a2–a6 모두 FENCE → FENCED → 활성화, `data_equal=1`, `ow_data_equal=1`, `wait_held=1`, `revived_done=1`, `fence_order_ok=1`, `fence_names_ok=1`, `win_verified=1`, `win_changed_after=0`, `inject_ok=1`,
  `ckpt_stable_before_inj=1`, 남은 프로세스 0, `la_stop_n=0`, `la_qp_err_n=0` `[측정: trials.csv]`.
- 여섯 시도 모두 `tcp_ctrl_bytes=0`, `ss_tx_delta_bytes=0`, `ring_live_all=1`, `active_mtu_kv_min=4096`, `probe_missing`과 `ctrlsum_missing` 빈칸. 증인 켬 다섯은 `witness_pairs=6=witness_expected`, (f)는 0=0 `[측정]`.

### 시각표 (주입 줄 뒤 ms, 대상 노드의 생존 rank 1, `rows_gc.py`)

| 시도 | 의심 | 판정 | hold 시작 | 펜스(근거) | 게시 | 첫 걸음(번호) |
|---|--:|--:|--:|---|--:|--:|
| a2 kill | 0.4 | 20.8 | 25.5 | 118.0(창, fence) | 156.2 | 359.6(139) |
| a3 STOP 12 s | 2 068.2 | 10 071.3 | 10 075.4 | 10 177.6(창, fence) | 10 215.6 | 10 433.6(140) |
| a4 GPU hang, 모든 context | 2 081.4 | 10 084.7 | 10 088.9 | 10 194.7(창, fence) | 10 231.8 | 10 403.1(156) |
| a5 GPU hang, context 1 | 2 027.2 | 10 031.0 | 10 035.1 | 10 141.2(창, fence) | 10 178.2 | 10 353.5(156) |
| a6 kill, EXITED 없음 | 611.6 | 3 682.4 | 3 686.7 | 3 689.7(창, fence) | 3 727.0 | 3 925.3(139) |

## (a) 장애 없음, 따뜻한 예비 프로세스 (a1)

- 네 rank `resume_rc=0`, 600 step, `xchg=ok`, `x_match=1`, `sig_exact=1`, `dev_bad=0`. 판정, 의심, 확인 창 0줄. 박동 간격 최대 1.107 ms, `W=20 W_rule=20` `[측정]`.
- 예비 프로세스: wait-for가 2 720.6 ms 뒤 맞아 띄움, HELLO 404.8 ms, READY. 끝 코드 137은 launcher shutdown의 SIGKILL이다.
- **context마다 READ.** 상태 페이지 줄은 rank마다 `device line named 1184 B, contexts=4 page_read=384 B`이고, 상대마다 `device progress line named (ctx=c of 4 …)` 넷이다.
  probe 요약 12줄(rank 넷 × 상대 셋) 모두 `reads=86 ok=86 dev_reads=340 dev_ok=340 dev_ctx=4 dev_reads_ctx=85/85/85/85 dev_ok_ctx=85/85/85/85 dev_peer_more=0`이다 `[측정]`.
  곧 주기마다 상대 하나에 READ 1 + 4 = 5(페이지 하나, context 줄 넷)다. `sq_max=2`, `pair_max=2`로 사슬이 동시 READ를 2 이하로 지켰다 `[측정]`. 이 driver는 `ginContextCount = N`(4)이다 `[소스]`.
- READ 성공 100 %(페이지 1 032/1 032, 장치 4 080/4 080) `[측정: trials.csv]`.

## (b) kill rank 3 (a2): 확인 창과 ward ERR gate

- 창: FIN 0.4 ms, 판정 20.8–21.1 ms(FIN+STALE ×3, 4행), FIN → 판정 − W = 0.43–0.73 ms. smoke4 a2(20.8–21.2 ms)와 같다 `[측정]`.
- FENCE → launcher SIGKILL → FENCED 91.1 ms, 판정 → 게시 164.8 ms, kill → 게시 185.6 ms, hold 최대 160.8 ms `[측정]`.
- **ward ERR gate.** buddy rank 2의 줄 차례: hold 시작 → `the store's upload QP of ward rank 3 (qpn 0x1f467) moved to ERR at its hold start` 0.49 ms → FENCE 보냄 → FENCED(ERR 뒤 91.1 ms) → 활성화.
  ERR이 FENCED보다 먼저 끝나서 "the activation waits for the store's upload QP" 줄과 fall back 줄은 없다 `[측정]`.
  같은 셈을 다섯 시도(a2–a6)에 하면 hold → ERR 0.35–0.49 ms, ERR 줄은 다섯 모두 `moved to ERR`(실패 0), 기다림 줄 0, fall back 0이다 `[측정]`.

| buddy rank 2의 FENCED → 활성화(`its spare activated` 줄) | 값 |
|---|---|
| smoke6(gate 있음) a2, a3, a4, a5, a6 | 4.04, 3.66, 3.63, 3.65, 3.54 ms |
| smoke4(gate 없음) a2, a5, a6 | 3.56, 3.38, 3.24 ms |

  gate가 활성화를 눈에 띄게 늦추지 않았다: 차이는 0.1–0.5 ms 꼴이다(n 5 대 n 3, smoke) `[측정]`. 그 차이가 gate 때문인지는 가르지 않았다 `[미확인]`.

## (c) SIGSTOP 12 000 ms, 펜스와 복원 (a3)

- STOP → 판정 10 070.9–10 072.4 ms(STALL_HELPER ×3, 15행), 퍼짐 1.57 ms, 의심 줄 셋(`kind=watch`). FENCE → FENCED 99.4 ms, 판정 → 게시 174.3 ms, hold 최대 170.7 ms.
  SIGCONT 12 006.0 ms 뒤 `present=0`(펜스가 이미 끝냄), `subject_fenced=1`, 데이터 같음 `[측정]`. smoke4 a5는 10 008.3–10 010.3 ms였다.

## (d) GPU hang, 모든 보내는 CTA (a4)

- rank 3 `GINRS gpuhang rank=3 step=155 spin=1 ctx=all wait_ms=2.203`, kv `gpuhang_it=155 gpuhang_ctx=all gpuhang_seen=1` `[측정]`.
- 의심 2 081 ms 셋 모두 `(kind=gpu stale_ms=2000.7–2000.8 ctx=0) (partition guard: another survivor sees it fresh)`. 판정 10 084.7–10 086.8 ms, STALL ×3(14행), STALL_HELPER 0.
  판정 줄의 context는 rank 0 `ctx=1`, rank 1과 2 `ctx=0`이라 `stall_ctx=0+1`이다 `[측정]`. 보내는 CTA 셋(context 0, 1, 2)이 함께 멈춰 정체가 거의 같고, 가장 큰 정체의 context(같으면 낮은 번호)를 대는 규칙에서
  읽는 때에 따라 갈린 것으로 본다 `[추론: 규칙은 notes_ctxall.md]`. 이 셀의 예측(`gpuhang_fence_restore`)은 `stall_ctx`를 쓰지 않는다.
- FENCE → FENCED 102.2 ms, 판정 → 게시 176.2 ms, hold 최대 172.1 ms, 데이터 같음, `subject_fenced=1` `[측정]`. smoke4 a6은 10 032.1–10 033.3 ms였다.

## (e) GPU hang, context 1만 (a5, 새 셀)

| 단계 | hang 줄 = 0 | 줄(앞부분) |
|---|---|---|
| hang 시작 | 0(걸음 155, spin을 0.1 ms에 봄) | rank 3 `GINRS gpuhang rank=3 step=155 spin=1 ctx=1 wait_ms=0.109`; kv `gpuhang_it=155 gpuhang_ctx=1 gpuhang_seen=1` |
| 의심 | 2 027 ms, 셋 모두 | `rank 3 suspected (kind=gpu stale_ms=2000.7 ctx=1) (partition guard: another survivor sees it fresh)` |
| 멈춤 판정 | 10 031.0–10 034.3 ms, 퍼짐 3.31 ms | `rank 3 (incarnation 0) judged stalled (liveness stall judged (STALL)); STALLED to 3 rank(s); ctx=1; the hold when armed, then FENCE …` |
| FENCE → FENCED | 100.6 ms | launcher SIGKILL, 그룹 끝 |
| 복원 | 판정 → 게시 176.4 ms, hold 최대 172.2 ms | `rank 3 restored as incarnation 1 (on time; …)` |
| 데이터 | `data_equal=1`, `ow_data_equal=1`, `wait_held=1`, `revived_done=1`, `subject_fenced=1` | `trials.csv` |

- 생존 셋 모두 판정 줄과 의심 줄에 `ctx=1`이고 `stall_ctx=1`이다. 판정 원인은 STALL(14행)이고 18행(데이터 경로 거부권)에 머문 생존 rank는 없다. 거부권이나 18행을 말하는 줄은 0이다 `[측정: grep]`.
  예측 `gpuhang_ctx1_fence_restore`의 시행 조건(GPU hang 행 + `stall_ctx == 1`)을 이 시행이 만족한다 `[측정, n 1, 채점 아님]`.
- **18절 (라)의 물음은 이 셀로 답해지지 않는다.** rank 3의 마지막 걸음 줄은 154이다 `[측정]`. 걸음 155에서 context 0과 2의 보내는 CTA는 그 걸음을 끝내지만 kernel이 끝나지 않으므로 다음 걸음의 context 0 트래픽이 없다 `[추론: gin_mi.cu의 걸음 구조]`.
  그래서 판정까지 10 s 동안 판정하는 rank에 context 0 트래픽이 닿지 않았고, 거부권이 걸릴 입력이 없었다 `[추론]`. "context 0 트래픽이 계속 닿는 동안 context 1만 멈춤"은 이 driver로 만들 수 없고, 그 장면은 단위 시험("veto held")에만 있다.
- 라이브러리 줄의 `ctx=` 꼴(판정 줄 `STALLED to N rank(s); ctx=k;`, 의심 줄 괄호 안 `ctx=k`)을 `rows_gc.py`가 그대로 읽었다(`stall_ctx`) `[측정]`.

## (f) kill, EXITED 보고 없음, fd 보관 없음 (a6)

- launcher `rank 3 incarnation 0 exited; EXITED not sent (test switch NO_EXIT_REPORT)`, `la_exit_silent_n=1`, 증인 끔 `[측정]`.
- rank 1 쪽(kill + ms, 같은 노드 시계): READ 시한 줄 611.6, `liveness READ of rank 3: retry exceeded (no response) (status 12)` 3 681.6, 같은 때 장치 줄 READ `probe QP broken (flush or local error) (status 5)`, 판정 3 682.4(NORESP), 복원 3 756.6 `[측정]`.
- kill → 판정 3 682.4–3 684.2 ms(NORESP ×3, 11행), FENCE → launcher `already ended; FENCED` 0.03 ms, 판정 → 게시 74.0 ms, `probe_fail_n=6`, 데이터 같음 `[측정]`. smoke5 a1, a2(3 595.8–3 746.2 ms)와 같은 길이다.
- 장치 줄 READ 실패 3(생존 rank마다 context 0의 flush 하나, `dev_reads_ctx=66/65/65/65 dev_ok_ctx=65/65/65/65`)이 `read_dev_success_pct`에 들어 99.929 %다 `[측정]`.

## launcher credit READ 재시도

- 여섯 시도의 launcher 로그와 rank 로그에 창이 닫힌 줄 `send window to a rank exhausted (seq …, its ack …): queued`가 0줄이다 `[측정: grep]`.
  재시도 자체(timerfd, 다시 READ)에는 줄이 없고, 이 줄이 창이 닫혀 재시도가 걸릴 수 있는 유일한 표시다 `[소스: launcher_transport_verbs.c 681행]`.
  곧 이 smoke에서 재시도는 한 번도 필요하지 않았고, 실제 RNIC에서 재시도가 동작하는지는 아직 보지 않았다 `[미확인]`. 창을 채우는 셀(`CREDIT_STALL` 등)이 있어야 볼 수 있다.

## 복원 뒤 READ 시한 줄 (앞 smoke의 열린 관찰)

- 복원이 있는 다섯 시도 모두 생존 rank마다 `probe of rank 3 timed out (no CQE in 500 ms)` 한 줄이 복원 뒤 4 963.2–5 250.2 ms(다섯 시도 생존 셋의 범위)에 난다 `[측정: postrestore.py]`.
- 같은 노드 시계(sunny의 rank 1과 예비 프로세스)로 보면 그 줄은 예비 프로세스(복원된 화신)의 communicator teardown 시작 뒤 1 220.7–1 312.5 ms, 그 마지막 probe 요약 줄 뒤 654.4–745.3 ms에 난다.
  곧 시한이 걸린 READ는 예비 프로세스가 teardown을 시작한 뒤 720–813 ms에 나갔다 `[측정에서 셈: 시한 500 ms]`. 예비 프로세스의 teardown은 자기 `GINRS end` 뒤 0.0 ms에 시작하고, 원래 rank는 끝 뒤 3 000 ms(`RS_END_GRACE_MS`)를 기다린 뒤 teardown한다 `[측정]`.
  driver는 예비 프로세스에서 이 기다림을 건너뛴다(`if (!spare && endGraceMs > 0) usleep(...)`) `[소스: gin_mi.cu 1011행]`.
- 같은 셈이 smoke4 a2, a6, smoke5 a1, a3에서도 같다(예비 프로세스 teardown → 시한 줄 1 244.3, 1 311.8, 1 250.7, 1 448.3 ms) `[측정: 그 폴더의 원자료, 읽기만]`.
- 맺음 `[추론]`: 이 시한은 실행 끝의 순서 때문이다. 복원된 화신이 먼저 끝나 QP와 페이지를 없애고, 끝 유예 중인 생존 rank의 probe가 그 화신을 한 번 더 읽어 시한이 난다. 복원의 결함이 아니다.
  "복원 뒤 4.7–5.2 s"는 복원 걸음(139–156)부터 600 걸음까지 남은 시간이다. 이 줄은 판정 뒤라 `probe_timeout_n`에 들지 않는다(a2–a5 0, a6 3은 판정 앞의 것) `[측정]`.

## 남은 것과 요청 (고치지 않음)

1. 18절 (라): context 0 트래픽이 이어지는 동안 context 1만 멈추는 장면은 이 driver로 만들 수 없다(위 (e)). 걸음 안에서 context 0의 보내는 CTA가 계속 post하는 driver 변형이 있어야 하드웨어에서 거부권의 영향을 잴 수 있다.
2. ward ERR gate의 기다림 길과 fall back 길(modify 실패, 2 000 ms 초과)은 실제 NIC에서 나지 않았다. ERR이 FENCED보다 91–105 ms 먼저 끝났다(a2–a5; a6은 FENCED가 0.2 ms 뒤) `[측정]`.
3. launcher credit READ 재시도는 이 smoke에서 걸리지 않았다(위 절).
4. a4의 `stall_ctx=0+1`: 모든 context가 멈추는 셀에서 생존 rank마다 다른 context를 댈 수 있다. 그 셀의 예측은 이 열을 쓰지 않아 영향이 없다.
5. 끝의 READ 시한(위 절)을 없애려면 예비 프로세스도 끝 유예를 기다리게 하거나 생존 rank의 끝 요약에서 화신의 teardown 뒤 READ를 따로 세면 된다. 이 smoke는 어느 쪽도 고치지 않았다.
6. `refused SPAWN of rank 3 (incarnation 1): spawn not built; no fallback on it` 줄은 smoke4와 같다(따뜻한 예비 프로세스가 있는 셀에서 launcher가 SPAWN을 거절하고 예비 프로세스를 씀).
