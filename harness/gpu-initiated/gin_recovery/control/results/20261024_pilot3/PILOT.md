# gin-control pilot 3 (2026-10-24 00:55–01:02, 채점 안 함)

pilot 2 뒤 라이브러리 고침 둘([../../impl/notes_pilot2fix.md](../../impl/notes_pilot2fix.md): 두 죽음의 둘째 REJOIN, 창 검사 기준을 FENCED 때로)을 실제 RNIC, launcher, 두 노드에서 처음 돌렸다.
셀은 두 죽음 셀 둘(셀마다 n 2), freeze 셀 둘, kill 셀 하나, SIGSTOP 펜스 셀 하나(셀마다 n 1)다. pilot은 본 실험에 들지 않고 채점하지 않는다.
"규칙" 열은 `score_gc.py`를 세션 스크래치 사본(`agent_gc_pilot3/sc/`)에서 pilot 표시를 끄고 계획 n을 있는 시행 수로 둔 채 돌린 결과다(`agent_gc_pilot3/score_pilot.py`, `mirror_check.py`; pilot 2의 것과 같음). 판정이 아니라 예측의 시행 조건이 이 시행에서 참인지만 본 것이다.
그때 worktree 파일: `predictions_gc.csv` `6ec5d574`, `score_gc.py` `5149e5cb`, `rows_gc.py` `8a41c326`, `cells_gc.json` `69af9e3c`(셋 다 커밋 `feb17165`의 것), `hold_gc.sh` `01f6c828`(아래 실행기 바꿈 뒤).
표시: `[측정]` 원자료에서 다시 셈, `[소스]` 코드를 읽음, `[추론]` 해석, `[미확인]` 확인 안 함. 시각과 열은 모두 `rows_gc.py`가 원자료에서 다시 셈한 값이다.

## 빌드와 배포

- 스크래치 트리 `agent_gc_p2a2/nccl-src`: HEAD `d5aec6e` "gin-control: pilot 2 fixes: two-death REJOIN …", 작업 트리 깨끗함, `f53e5d2` 대비 patience diff md5 `7a3fbd66` = [../../impl/gc_layer_int.diff](../../impl/gc_layer_int.diff) `[측정]`.
- 라이브러리는 다시 빌드하지 않았다. `chain_pf2.sh` → `pf2.sh`의 출력이 notes의 md5와 같다 `[측정]`.

| 무엇 | md5 | 비고 |
|---|---|---|
| libnccl `gc` | `39024befe7760f00f6a8bf761f28cc5a` | `out/gc_pf2`(= `build/lib`) |
| `gin_mi` | `50e03ae634bc4ed8b41ac636e2efae8c` | `impl/test/driver/build_driver_gc.sh mi`(`MIOUT=mi_pl3`, `OUTROOT=agent_gc_pilot3/drvout`), `gin_mi.cu` `6cb4ff28`, 머리 digest `65fdf19b`(pilot 2와 같음: 고침은 호스트 파일만), lib `gc_pf2` |
| `gin_launcher` | `d1aceaf68f00d99eafa4d585195f3348` | smoke 6, pilot 1, 2와 같음 |

- `gcp`, `gct`, 비용 driver, `gin_mi_nomacro`, `gin_mr`는 쓰는 셀이 없어 배포하지 않았다.
- **배포.** 묶음 `~/rs-bundle/gc_pilot3/`를 `impl/test/deploy_gc.sh`로 배포했다. 두 노드의 새 파일 md5가 서로 같고 원본과 같으며, ldd는 묶음의 libnccl을 가리킨다. 다른 묶음의 기존 파일(rain 975, sunny 1 030)은 바뀌지 않았다. 출력은 [deploy.txt](deploy.txt)다 `[측정]`.

## 시도

`harness/gpu-initiated/common/cluster_run.sh` 안에서 `chain_gc.sh` → `hold_gc.sh`로 돌렸고 hold의 STOP 규칙이 켜져 있었다.
- 시도는 2번(한도 8)이다. 클러스터 시간은 00:55:48–01:01:48, 약 6분이고 hold는 148 s, 147 s다.
- 두 hold 모두 STOP 0, 새 mlx5 커널 줄 0, rain 펌웨어 명령 실패 합 31 그대로, 남은 프로세스 0, QUERY_QP 상한 넘음 0(`qp_over.txt` 없음) `[측정]`.

| 시도 | hold | 시행 | 결과 |
|---|---|--:|---|
| [a1](a1/) | `PCELL-gc4_freeze12000_fence+gc4_helper_freeze12000+gc4_kill3_ow+gc4_stop12000_fence` | 4 | 통과 |
| [a2](a2/) | `PRC-gc-mi4_kill2_kill3_ow+mi4_train_kill2_kill3+mi4_kill2_kill3_ow+mi4_train_kill2_kill3`(새 hold 꼴, 아래) | 4 | 통과 |

## 시행마다 (n 1씩, 두 죽음 셀은 n 2)

시각표는 주입 줄 뒤 ms이고 대상 노드의 생존 rank 기준이다: 의심 / 판정 / hold 시작 / 펜스 / 게시 / 첫 걸음. 펜스 칸은 `rows_gc.py`의 `t_fenced_ms`이고 괄호는 launcher의 FENCED 줄(`t_la_fenced_ms`)이다(문제 1).
모든 시행의 사본 상태는 "채점"(제외 0)이고, 모든 시행이 `win_verified` 1, `win_lines_n` 3, `win_changed_after` 0, `wait_held` 1, `ow_data_equal` 1, `data_equal` 1, `no_reexec` 1, `revived_done` 1, `tcp_ctrl_bytes` 0, READ 성공 100 %, `probe_timeout_n` 0, `la_qp_err_n` 0, `la_stop_n` 0이다 `[측정]`.

| 셀 | 판정 원인 | 시각표 (ms) | 펜스와 복원 | 규칙(시행 하나) |
|---|---|---|---|---|
| `gc4_freeze12000_fence` | STALL_HELPER ×3 | 2 001.9 / 10 005.8 / 10 010.1 / 10 174.3 (10 141.2) / 10 186.3 / 10 378.0 | 판정은 FREEZE_PAGE 줄 뒤 10 005.8–10 006.9 ms, SIGKILL → FENCED 128.4 ms, 판정 → 게시 210.4 ms, 입력 멈춤 15.4 ms | 살아 도는 프로세스의 펜스(`freeze_fence_restore`) 맞음(pilot 2에서 거짓이던 창 항 포함) |
| `gc4_helper_freeze12000` | STALL_HELPER ×3 | 2 004.5 / 10 008.2 / 10 012.5 / 10 168.0 (10 135.3) / 10 179.7 / 10 271.2 | 판정 10 007.1–10 008.2 ms, SIGKILL → FENCED 122.7 ms, 판정 → 게시 202.0 ms, 입력 멈춤 23.1 ms | helper 멈춤의 펜스(`helper_stall_fence`) 맞음 |
| `gc4_kill3_ow` | FIN+STALE ×3 | 0.5 / 20.8 / 25.0 / 163.4 (137.2) / 175.0 / 388.4 | kill → 판정 20.8–21.1 ms, launcher SIGKILL → FENCED 111.2 ms, 복원 183.4 ms, kill → 게시 204.3 ms | kill의 RDMA 판정(`kill_judge_rdma`) 이 셀 1/1 |
| `gc4_stop12000_fence` | STALL_HELPER ×3 | 2 037.6 / 10 040.8 / 10 045.0 / 10 192.2 (10 164.1) / 10 204.9 / 10 405.2 | 판정 10 040.8–10 044.0 ms, SIGKILL → FENCED 113.9 ms, 판정 → 게시 194.3 ms | 긴 멈춤의 펜스 뒤 복원(`stall_fence_restore`) 맞음 |
| `mi4_kill2_kill3_ow` n1 | FIN+STALE ×3 (둘째도) | 0.4 / 20.9 / 24.7 / 138.2 (123.9) / 148.5 / 251.7 | 첫 복원 174.3 ms, **둘째 복원 195.6 ms**, kill → 판정 20.9–21.8 ms, FENCED 96.5 ms(rank 2), 92.2 ms(rank 3) | 아래 두 죽음 절 |
| `mi4_kill2_kill3_ow` n2 | FIN+STALE ×3 (둘째도) | 0.6 / 21.2 / 24.6 / 141.4 (126.7) / 151.6 / 297.4 | 첫 176.6 ms, **둘째 172.8 ms**, kill → 판정 20.9–21.4 ms, FENCED 99.3, 83.5 ms | 같음 |
| `mi4_train_kill2_kill3` n1 | FIN+STALE ×3 (둘째도) | 0.3 / 21.1 / 26.3 / 219.2 (188.0) / 229.8 / 374.9 | 첫 252.2 ms, **둘째 259.3 ms**, kill → 판정 20.8–21.1 ms, FENCED 159.6, 153.6 ms | 같음 |
| `mi4_train_kill2_kill3` n2 | FIN+STALE ×3 (둘째도) | 0.3 / 20.5 / 25.8 / 216.4 (187.9) / 227.0 / 319.9 | 첫 249.7 ms, **둘째 261.0 ms**, kill → 판정 20.5–20.9 ms, FENCED 160.0, 152.0 ms | 같음 |

- 범위는 모두 그 시행의 생존 셋 사이 최소–최대다. 두 죽음 셀의 첫째 열은 첫 죽음(rank 2) 것이고, 둘째 복원은 `restore_time_ms_2`다 `[측정]`.
- 복원 시간 여덟(첫 복원 기준)은 4 KiB 174.3–183.4 ms, 학습 249.7–252.2 ms로 pilot 2(154.7–186.8, 250.1–254.0 ms)와 같은 띠다 `[측정]`.

## 고침 1: 두 죽음의 둘째 REJOIN (4/4 복원)

네 시행 모두 둘째 예비 프로세스(rank 3 화신 1)가 활성화 표의 UD로 되살린 rank 2(화신 1)에 닿았고 둘째 죽음이 복원됐다(`second_ok` 1, `reimage_ok` 1). pilot 2는 0/2였다 `[측정]`.

| 시행 | 표 줄의 UD QPN (transcript의 옛 값) | 세대 줄 | rank 2 화신 1 쪽 받아들임 | 예비 쪽 rank 2의 REJOIN_ACK |
|---|---|---|---|---|
| `mi4_kill2_kill3_ow` n1 | 5 233 (5 175) | gen 2 097 153 | "the REJOIN of rank 3 (incarnation 1) taken over UD: record QP gen 2097153, liveness READ QP gen 2097153, REJOIN_ACK sent" | try 1, gen 2 097 153 |
| `mi4_kill2_kill3_ow` n2 | 5 622 (5 564) | 같음 | 같음 | try 1, 같음 |
| `mi4_train_kill2_kill3` n1 | 5 795 (5 736) | 같음 | 같음 | try 1, 같음 |
| `mi4_train_kill2_kill3` n2 | 5 968 (5 910) | 같음 | 같음 | try 1, 같음 |

- 표 줄(`spare_2nd.log`): `GIN/RC: rank 3: rank 2 (incarnation 1) is reached over UD at the activation table's endpoint (UD QPN 5233; the transcript's 5175)`.
- 세대 줄: `GIN/RC: rank 3: the REJOIN to rank 2 (incarnation 1, restored before) starts gen 2097153: above the pair's generations of both incarnations`. rank 0, 1에는 전처럼 gen 1 048 577이다.
- REJOIN 다시 보냄 줄은 0이다(pilot 2는 150, 149개). 셋 모두 첫 시도에 REJOIN_ACK가 왔다 `[측정: grep]`.
- 네 시행 모두 `wall_s` 11.0 s(4 KiB), 35.1 s(학습)로 끝까지 돌았다. pilot 2의 STALL_HELPER fallback과 Resume rc=2는 없다.
- gin-mirror 규칙의 시행 조건 `[측정: agent_gc_pilot3/mirror_check.py]`: 다시 이미지(`reimage_after_restore`) 2/2, 둘째 죽음 복원(`second_death_restored`: `second_ok`, 두 복원 ≤ 2 000 ms, 대기 붙잡힘, 데이터 같음, 재실행 없음) 2/2, 학습 둘째 죽음(`train_second_death`, ≤ 1 000 ms) 2/2. 스크립트의 "틀림"은 gin-mirror의 k를 n 2에 댄 것이라 뜻이 없다.
- launcher 기록 QP 잃음은 네 시행 모두 0이다(`la_qp_err_n` 0; 2026-10-24 채점기 고침 뒤 둘째 kill의 rank 3 줄이 빠짐). 그래서 pilot 2와 달리 `launcher_changed` 제외 없이 채점 상태다.
- `surv_unfinished` 1은 네 시행 모두 같고, 둘째로 죽은 rank 3 화신 0으로 본다 `[추론]`. gin-mirror 규칙은 이 열을 쓰지 않는다.

## 고침 2: 창 검사의 기준 시점

- 줄 꼴은 notes의 새 꼴 그대로다: `window check after the fence of rank 3: changed=0 cells against=snapshot_at_fence base=fenced sample=rejoin unreadable=0` `[측정]`.
- freeze 셀 둘은 생존 셋 모두 changed=0이고 `win_verified` 1이다. pilot 2는 같은 셀에서 changed 2, 2, 2칸과 1, 1, 1칸이었다.
- 줄 수 `[측정: grep]`: 단일 죽음 시행마다 3줄(대상 rank 3), 두 죽음 시행마다 6줄(rank 2에 3줄: r0, r1, r3 화신 0; rank 3에 3줄: r0, r1, rank 2 화신 1). 모두 `sample=rejoin`이고 `sample=hold_end`와 `base=judgement` 줄은 0이다.
- **채점기의 겹침 셈.** 한 생존 rank가 같은 대상에 REJOIN 줄과 hold_end 줄을 둘 다 낸 시행은 없었다. `win_lines_n`은 대상을 부른 생존 rank의 집합이라 그런 두 줄도 한 번만 센다. 반면 `win_changed_after`의 합은 대상과 상관없이 모든 줄을 더한다 `[소스: rows_gc.py 1152–1171]`. 이번에는 모든 줄이 0이라 값이 같다. 두 죽음 셀에서는 둘째 대상의 줄도 합에 든다.
- kill 셀의 줄은 기대한 "after the judgement"가 아니라 "after the fence"다. 판정이 FIN+STALE이었고 launcher가 그 죽은 프로세스 묶음에 SIGKILL 펜스를 보내 FENCED 낱말이 섰기 때문이다 `[측정: launcher_sunny.log "FENCE of rank 3 … SIGKILL sent", "FENCED: the group ended 111.169 ms after SIGKILL"]`. pilot 1의 같은 셀도 "after the fence"였다. EXITED 낱말의 길(`after the judgement … base=fenced sample=rejoin`)은 이 pilot에서 걸리지 않았다 `[미확인]`.
- SIGSTOP 펜스 셀도 새 기준으로 changed=0, `win_verified` 1이다.

## 문제 (고치지 않음, 결정 필요)

1. **`t_fenced_ms`가 REJOIN 받아들임 때로 옮겨 갔다(채점기의 보고 열).**
   - 생존 rank에는 "fence FENCED" 줄이 없어 `rows_gc.py`가 창 줄 시각을 펜스로 쓴다(`t_fenced_src` `window_fence`, 여덟 모두) `[소스: rows_gc.py 1409–1414; 측정]`.
   - 창 줄이 FENCED 순간에서 REJOIN 받아들임으로 옮겨 가서, 그 열이 launcher FENCED보다 14.2–33.1 ms 늦다(여덟 시행의 범위) `[측정]`.
   - 이 열을 쓰는 예측은 없어 판정은 바뀌지 않는다 `[소스: predictions_gc.csv grep]`. 시각표의 펜스를 `t_la_fenced_ms`로 읽을지 정해야 한다. 창 줄 꼴이 채점을 깨지는 않아 `rows_gc.py`는 고치지 않았다.
2. **두 죽음 셀이 장애 없는 제어 예측(`no_tcp_control`)의 `build:gc` 항을 깬다(채점기).**
   - `witness_pairs` 5 대 `witness_expected` 6이라 사본 채점에서 `build:gc` 항이 4/8, 안전 예측의 실패로 나온다 `[측정: agent_gc_pilot3/sc/SCORE.md]`.
   - 빠진 쌍은 rank 2 화신 1과 rank 3 화신 1이다. 소켓은 열렸다(`spare_2nd.log` "socket to rank 2 reconnected gen=4 attempts=0", `spare.log` "socket to rank 3 reconnected gen=4") `[측정]`.
   - `witness_view`는 둘째 예비 프로세스의 로그에서 rank 2의 화신을 알 길이 없어 그 소켓을 화신 0에 매긴다. `final_generation`은 rank 2를 화신 1로 보므로 짝이 맞지 않는다 `[소스: rows_gc.py 555–624; 측정: 사본에서 그 표를 찍음]`.
   - pilot 2에서는 이 시행들이 `launcher_changed`로 제외돼 드러나지 않았다. 새 줄 "rank 2 (incarnation 1) is reached over UD at the activation table's endpoint"를 화신 표지로 읽는 고침이 맞아 보이나 `[추론]`, 이번 고칠 범위(창 줄 꼴) 밖이라 고치지 않았다.
3. **둘째 셈 키가 없다.** `rows_gc.py`의 판정 시각 열(`kill_judge_ms_*`, 시각표)은 첫 죽음만 본다. 둘째 죽음의 판정과 펜스는 이 문서에 로그에서 손으로 옮겼다(r0 "rank 3 judged dead", launcher FENCED 줄) `[측정: grep]`.

## 실행기 쪽 바꿈 (이번에 돌았음)

- `impl/test/hold_gc.sh`에 pilot hold 꼴 `PRC-<빌드>-<셀>[+<셀>…]`를 더했다. 회귀 hold(`cells_gc.json` `regression.holds`)의 gin-mirror 셀에서 이름이 같은 항목 하나를 그 빌드로 돌리고, 같은 이름을 k번 쓰면 시행 k개(n1–nk)다. `PRG-`는 hold 전체(G1 일곱 셀)를 돌려서 두 죽음 셀만 두 번 돌릴 길이 없었다.
  - 메마른 점검: 위 hold가 `mi4_kill2_kill3_ow` n 2(G1, bound 60), `mi4_train_kill2_kill3` n 2(T2, bound 150)를 내고, `PRC-gct-mi4_kill2_kill3_ow`는 @gct에서 돌지 않는 셀이라 거절한다. `bash -n` 통과 `[측정: 로컬 실행]`. a2에서 돌았다.
- 라이브러리, launcher, `rows_gc.py`, `score_gc.py`, 셀과 예측 파일은 고치지 않았다. `test_rows_gc.py`는 198 검사 실패 0 그대로다 `[측정: 로컬 실행]`.

## 하지 않은 것

- 다시 돌린 시도 없음(STOP 0). 시도 한도 6번, 시간 약 1 h 50 min이 남았다.
- tcp 회귀 대조, GPU hang 셀, 예비 프로세스 없음 셀, `gc4_none_probe`는 이번 범위 밖이다.

원자료는 `aN/raw/`에 있고 시행 표는 `aN/trials.csv`다(스크래치 사본 채점의 상태 열 포함). 모두 IPv4 가림을 거쳤다(IPv4 꼴 0건, 관리망 주소 0건 `[측정: grep]`).
이 폴더 루트에는 사슬 기록 [chain.out](chain.out), 시도 기록 [attempts.txt](attempts.txt), 배포 출력 [deploy.txt](deploy.txt)가 있다.
