# gin-control pilot 8 (2026-10-28 02:52–02:54, 채점 안 함)

pilot 7 문제 1(남의 확정된 중단 결정이 생존 rank의 자기 판정을 앞질러 결과 열을 바꿈)이 거절 셀 셋에서도 일어나는지 본 pilot이다. 라이브러리는 piece ①(기록 57 `ABORT_DECIDED`, gc `ed13666b`)이고 pilot 7의 묶음 `gc_pilot7`을 다시 배포하지 않고 썼다([VERSIONS.md](VERSIONS.md)).
질문: 생존 rank가 자기 판정보다 먼저 다른 생존 rank의 결정을 적용해서, 채점기의 `n_judge`(대상을 이름한 자기 DEAD 또는 STALLED 줄을 낸 생존 rank 수)가 `n_surv`보다 작아지거나 세 예측의 시행 조건이 깨지는가.
pilot은 본 실험에 들지 않고 채점하지 않는다.

표시: `[측정]` 원자료에서 다시 셈, `[소스]` 코드를 읽음, `[추론]` 해석, `[미확인]` 확인 안 함. 시각은 그 시행의 첫 주입 줄 뒤 ms다(kill 셀은 rank 3의 `GINRS killed`, 예비 없음 셀은 rank 3의 kill이고 예비 kill은 −5.0 ms; SIGSTOP 셀은 `GINRS stop`).
sunny 줄(rank 1, rank 3, sunny launcher)은 meta의 노드 시계 차로 rain 시계에 옮겼다(왕복 0.154–0.196 ms, 세 시행의 범위). **한 프로세스 안의 앞뒤(자기 판정 줄 대 받음 줄)는 한 시계라 이 오차가 없다.**
사건 목록은 [events/](events/)(스크립트 [events.py](events.py): pilot 7 판에 예비 kill 줄을 `spare_kill`로 더함, 결정 줄 일곱 꼴 그대로), 시행마다의 요약은 [summary.txt](summary.txt)([summ.py](summ.py))다.

## 시도

`harness/gpu-initiated/common/cluster_run.sh` 안에서 `chain_gc.sh` → `hold_gc.sh`로 hold 하나를 돌렸고 STOP 규칙이 켜져 있었다. 시도 1번, 클러스터 시간 02:52:04–02:53:51(락 02:52:04, 링크 한가 02:52:35, hold 74 s) `[측정: chain.out, attempts.txt, a1/run_PCELL.out]`.

| hold (파일 꼬리표) | 시행 | 결과 |
|---|--:|---|
| `PCELL-gc4_fdhold_uverbs_kill3+gc4_kill3_ow_spareabsent+gc4_stop12000_none` (`PCELL`) | 3 (n 1씩) | STOP 0 |

- 새 mlx5 커널 줄 0, rain 펌웨어 명령 실패 합 31 그대로, rain mlx5 cmd_err 2 그대로, 남은 프로세스 0(`left=0 stopped=0 fdhold=0` 세 시행), `qp_over.txt` 없음, `la_stop_n` 0, `la_qp_err_n` 0 `[측정: a1/snap_*, a1/mlx5_new_PCELL.txt, a1/run_PCELL.out, a1/trials.csv]`.
- 시작 전 `pgrep -af cluster_run.sh`에 다른 실행 없음. 라이브러리, 채점기, 셀, 예측, 실행기는 고치지 않았다.
- 세 시행 모두 `status` scored, `inject_ok` 1, `probe_timeout_n` 0, `witness_pairs` 6, `tcp_ctrl_bytes` 0 `[측정: a1/trials.csv]`.

## 시행마다

### 자식이 uverbs fd까지 쥔 kill (`gc4_fdhold_uverbs_kill3`, n1, wall 5.0 s)

launcher `EXITED` 60.4. 생존 셋 모두 스스로 판정하고 스스로 decline했다. 받은 결정은 모두 늦음이다 `[측정: events/gc4_fdhold_uverbs_kill3_gc_n1.txt, 33줄]`.

| 생존 rank | 자기 판정 (원인, ms) | decline (ms, 사유) | 결정 기록 (`confirmed abort decision no. 1`) | 보냄 | 받음 (보낸 rank: ms, 결과) | probe summary `ad_*` | 순서 |
|---|---|---|---|---|---|---|---|
| r0 | EXITED 60.904 | 63.373, 자기 판정 ("the judgement table shows EXITED") | 63.402, cause FIN, 2 000.0 ms | → r1, r2 1 999.9 ms 남음 | r1: 63.505 늦음, r2: 63.514 늦음 | `peer1:ad_tx=1 ad_rx_late=1`, `peer2:ad_tx=1 ad_rx_late=1` | 판정 → decline → 받음 |
| r1 | EXITED 60.521 | 62.312, 자기 판정 | 62.363, cause FIN, 1 999.9 ms | → r0, r2 1 999.9 ms 남음 | r0: 63.455 늦음, r2: 63.488 늦음 | 같은 꼴 (peer0, peer2) | 판정 → decline → 받음 |
| r2 | EXITED 60.801 | 63.370, 자기 판정 | 63.396, cause FIN, 2 000.0 ms | → r0, r1 1 999.9 ms 남음 | r0: 63.445 늦음, r1: 63.492 늦음 | 같은 꼴 (peer0, peer1) | 판정 → decline → 받음 |

- `released=1`: r0 2 063.5, r1 2 063.7, r2 2 064.3. 셋 모두 `exit=4 xchg=released` `[측정]`.
- 결정 셋, 적용 0, 늦음 여섯. 가장 이른 결정(r1, 62.363)은 r0, r2에 그들의 decline 0.132 ms, 0.122 ms 뒤에 닿았다(같은 프로세스 시계) `[측정]`. 닿은 것이 decline보다 일렀어도 DEAD 줄(60.8–60.9)은 2.5 ms 앞이라 `n_judge`는 같았을 것이다 `[추론]`.
- 결정 줄의 cause는 `FIN`이고 판정 원인은 `EXITED`다 `[측정]`. 결정이 판정 원인을 어떤 이름으로 싣는지는 이 pilot에서 확인하지 않았다 `[미확인]`.

| 열 | 값 |
|---|---|
| `n_judge` / `n_surv` | 3 / 3 |
| `judge_causes` | `EXITED:3` (`n_judge_exited` 3, `n_judge_stall_helper` 0, `n_judge_stall` 0) |
| `decline_n` | 9 |
| `surv_released` | 3 |
| `subject_fenced` | 0 |
| `restore_count` | 0 |
| `la_act_refused_why`, `fenced_to_fallback_ms` | 빈칸 (예비 없는 셀) |
| `kill_judge_ms_min`–`max` | 60.521–60.904 |

### 무장 뒤 예비가 없음 (`gc4_kill3_ow_spareabsent`, n1, wall 8.6 s)

예비 kill −5.0, rank 3 kill 0.0(`pair_gap_ms` 5.017, 한도 10 ms 안). 생존 셋 모두 FIN+STALE로 스스로 판정해 hold했고, launcher가 활성화를 거절한 뒤 fallback으로 decline했다. 받은 결정은 모두 늦음이다 `[측정: events/gc4_kill3_ow_spareabsent_gc_n1.txt, 48줄]`.
launcher: FENCE SIGKILL 27.3, FENCED 194.0, 활성화 REFUSED 195.7("the spare exited").

| 생존 rank | 자기 판정 (원인, ms) | hold → 포기 | decline (ms, 사유) | 결정 기록 | 보냄 | 받음 | probe summary `ad_*` | 순서 |
|---|---|---|---|---|---|---|---|---|
| r0 | FIN+STALE 22.320 | 22.360 → 196.314 (`FALLBACK(rank 3, incarnation 0) from rank 2`) | 196.506, "restore fallback: FALLBACK(rank 3, incarnation 0) from rank 2" | 196.531, cause FALLBACK, 2 000.0 ms | → r1 2 000.0, r2 1 999.9 ms 남음 | r2: 196.905 늦음, r1: 196.920 늦음 | `peer1:ad_tx=1 ad_rx_late=1`, `peer2:ad_tx=1 ad_rx_late=1` | 판정 → decline → 받음 |
| r1 | FIN+STALE 20.490 | 20.574 → 196.325 (같음, from rank 2) | 196.641, 같은 사유 | 196.690, 1 999.9 ms | → r0, r2 1 999.9 ms 남음 | r0: 197.347 늦음, r2: 197.366 늦음 | 같은 꼴 | 판정 → decline → 받음 |
| r2 | FIN+STALE 22.325 | 22.360 → 196.275 (launcher: the spare exited) | 196.483, "restore fallback: the peer's spare refused the activation (launcher: the spare exited)" | 196.510, 2 000.0 ms | → r0, r1 1 999.9 ms 남음 | r0: 196.917 늦음, r1: 196.940 늦음 | 같은 꼴 | 판정 → decline → 받음 |

- r0, r1의 decline 사유는 기존 FALLBACK 기록(r2가 보냄)이지 `ABORT_DECIDED`가 아니다. 결정은 fallback decline 뒤에만 났고 판정 줄은 그 174 ms 앞이다 `[측정]`.
- `released=1`: r0 2 196.7, r1 2 198.3, r2 2 198.6. 셋 모두 `exit=4 xchg=released` `[측정]`.

| 열 | 값 |
|---|---|
| `n_judge` / `n_surv` | 3 / 3 |
| `judge_causes` | `FIN+STALE:3` |
| `decline_n` | 9 |
| `surv_released` | 3 |
| `subject_fenced` | 0 |
| `la_act_refused_why` | `the spare exited` |
| `fenced_to_fallback_ms` | 2.296 |
| `kill_judge_ms_min`–`max` | 20.49–22.325 |

### 펜스 끈 12 s 멈춤 (`gc4_stop12000_none`, n1, wall 22.5 s)

**r2는 rank 3을 스스로 판정하지 않았다. r0의 결정을 받아 적용한 것이 r2의 decline이다** `[측정: events/gc4_stop12000_none_gc_n1.txt, 46줄; a1/raw/gc4_stop12000_none_gc_n1_r2.log, 501줄]`.

| 생존 rank | 의심 (ms) | 자기 판정 (원인, ms) | decline (ms, 사유) | 결정 기록 | 보냄 | 받음 | probe summary `ad_*` | 순서 |
|---|---|---|---|---|---|---|---|---|
| r0 | 2 068.9 | STALL_HELPER 10 072.063 | 10 073.8, 자기 판정 ("liveness stall judged (STALL_HELPER)") | 10 073.9, cause STALL_HELPER, 2 000.0 ms | → r1 2 000.0, r2 1 999.9 ms 남음, 10 073.9 | r1: 10 074.2 늦음 | `peer1:ad_tx=1 ad_rx_late=1`, `peer2:ad_tx=1` | 판정 → decline → 받음 |
| r1 | 2 068.8 | STALL_HELPER 10 071.993 | 10 074.0, 자기 판정 | 10 074.2, 1 999.8 ms | → r0, r2 1 999.7 ms 남음, 10 074.2 | r0: 10 074.3 늦음 | `peer0:ad_tx=1 ad_rx_late=1`, `peer2:ad_tx=1` | 판정 → decline → 받음 |
| r2 | 2 071.1 | **없음** | 10 076.7, `ABORT_DECIDED(rank 3, incarnation 0, no. 1, cause STALL_HELPER) of rank 0 (incarnation 0): a confirmed abort decision` | 없음 | 없음 | r0: 10 076.8 **적용**(`waits released in 1997.1 ms (no hold, no fence)`), r1: 10 076.8 늦음 | `peer0:ad_rx_applied=1`, `peer1:ad_rx_late=1` | 결정 적용, 자기 판정 끝내 없음 |

- r2가 그 사이 받은 것: r1의 `STALLED(rank 3)` 10 072.0, r1의 NOHOLD 10 072.1, r0의 `STALLED(rank 3)` 10 072.1. 그 뒤 10 076.7까지 r2 로그에 줄이 없고, 시행 끝까지 r2의 rank 3 판정 줄은 0이다 `[측정]`.
- **간격**: r2의 적용(10 076.7)은 r1, r0의 자기 판정 4.7 ms, 4.6 ms 뒤, r0의 보냄(10 073.958) 2.9 ms 뒤다(r0, r2 모두 rain, 한 시계). r2 자신의 판정이 없으므로 "자기 판정 − 적용" 간격은 정의되지 않는다 `[측정]`.
  r2의 의심 줄은 r0, r1보다 2.2–2.3 ms 늦었다. 같은 셀의 지난 두 시행에서 마지막 생존 rank의 자기 판정은 첫 판정 1.2–1.3 ms 뒤였고 남의 STALLED를 받은 뒤에도 나왔다(아래 비교).
  이번 r2가 10 072.2–10 076.7 사이에 판정하지 않은 까닭(probe 주기 위상, helper가 다른 일 중)은 원자료로 가리지 못했다 `[미확인]`.
- `released=1`: r0 12 074.7, r1 12 075.9, r2 12 076.3. r2의 해제 시각은 r0의 결정을 따랐다(10 076.8 + 1 997.1) `[측정]`.
- rank 3: SIGCONT 12 011.7(`stopped_ms` 12 011.726), 그 뒤 rank 2, 1, 0을 decline(15 601.8–15 606.8, "RETRY_EXC and the peer's socket shows BYE"), `confirmed abort decision no. 1 (incarnation 0): rank 0 (incarnation 0), cause every, … released in 0.0 ms` 한 줄(15 606.8), 보냄 줄 0, probe summary `ad_*` 모두 0, `released=1` 15 614.0, `exit=4` `[측정]`.

| 열 | 값 |
|---|---|
| `n_judge` / `n_surv` | **2 / 3** |
| `judge_causes` | **`STALL_HELPER:2`** (`n_judge_stall_helper` 2) |
| `decline_n` | 16 |
| `surv_released` | 4 (생존 셋 + rank 3) |
| `subject_fenced` | 0 |
| `la_act_refused_why`, `fenced_to_fallback_ms` | 빈칸 (펜스 끈 셀) |
| `stop_judge_ms_min`–`max` | 10 071.993–10 072.063 (자기 판정 둘만), `judge_spread_ms` 0.07 |

## 예측의 시행 조건 (채점 아님)

`score_gc.py`(`7b36c065`, 바꾸지 않음)를 세션 스크래치 사본에서 pilot 7과 같은 방식([score_v0/score_pilot.py](score_v0/score_pilot.py): pilot 표시 끔, 계획 n을 있는 시행 수로)으로 돌렸다. 출력은 [score_v0/](score_v0/)다.

| 예측 (ID) | 시행 조건 (predictions_gc.csv의 `acceptance` 안쪽) | 이 시행 |
|---|---|---|
| 자식이 uverbs fd까지 쥐면 거절만 (`fdhold_uverbs_refuse`) | `n_judge == n_surv and n_judge_exited + n_judge_stall_helper + n_judge_stall == n_judge and restore_count == 0 and decline_n >= 1 and surv_released == n_surv` | 1/1 |
| 무장됐으나 활성화 때 예비 프로세스가 없음의 곧바른 fallback (`spare_absent_refused`) | `(has(la_act_refused_why, "the spare exited") or has(la_act_refused_why, "could not hand over")) and fenced_to_fallback_ms <= 100 and surv_released == n_surv` | 1/1 |
| 긴 멈춤, 펜스 끔 (`stall_none_refuse`) | `n_judge_stall_helper >= 1 and decline_n >= 1 and surv_released >= n_surv and subject_fenced == 0` | 1/1 (`n_judge` 2여도 조건에 `n_judge == n_surv`가 없음) |
| RDMA 제어에 TCP 없음 (`no_tcp_control`) | `build:gc`: `tcp_ctrl_bytes == 0 and witness_pairs == witness_expected and …` | 3/3 |

세 예측 모두 판정은 자료 부족(n<k)이다(n 1, k 4) `[측정: score_v0/score_out.txt]`. 채점기 결함은 찾지 못해 `score_v1/`은 없다. `n_judge`는 열 정의(자기 DEAD, STALLED 줄)대로 2를 셌고, 결정의 적용을 세는 열은 없다(pilot 7 notes_test.md의 관찰과 같음).

## 지난 시행과 비교 (같은 셀, 옛 라이브러리)

| 셀 | 시행 | `n_judge`/`n_surv` | `judge_causes` | `decline_n` | `surv_released` | `subject_fenced` | `la_act_refused_why` | `fenced_to_fallback_ms` | 판정 시각 띠 (ms) |
|---|---|---|---|--:|--:|--:|---|--:|---|
| fd 자식 uverbs | pilot 1 a3 n1 | 3/3 | `EXITED:3` | 9 | 3 | 0 | | | 76.863–76.951 |
| fd 자식 uverbs | **pilot 8 n1** | 3/3 | `EXITED:3` | 9 | 3 | 0 | | | 60.521–60.904 |
| 예비 없음 | pilot 1 a3 n1 | 3/3 | `FIN+STALE:3` | 9 | 3 | 0 | the spare exited | 2.235 | 21.117–21.567 |
| 예비 없음 | pilot 2 a1 n1 | 3/3 | `FIN+STALE:3` | 9 | 3 | 0 | could not hand over to the spare | 2.399 | 20.735–21.088 |
| 예비 없음 | **pilot 8 n1** | 3/3 | `FIN+STALE:3` | 9 | 3 | 0 | the spare exited | 2.296 | 20.49–22.325 |
| 펜스 끈 멈춤 | pilot 1 a3 n1 | 3/3 | `STALL_HELPER:3` | 16 | 4 | 0 | | | 10 004.037–10 005.295 |
| 펜스 끈 멈춤 | pilot 2 a1 n1 | 3/3 | `STALL_HELPER:3` | 16 | 4 | 0 | | | 10 090.688–10 091.889 |
| 펜스 끈 멈춤 | **pilot 8 n1** | **2/3** | **`STALL_HELPER:2`** | 16 | 4 | 0 | | | 10 071.993–10 072.063 (둘) |

값은 `rows_gc.py`가 원자료에서 다시 셈한 각 폴더의 `trials.csv`다(`results/20261023_pilot1/a3/trials.csv`, `results/20261023_pilot2/a1/trials.csv`, [a1/trials.csv](a1/trials.csv)) `[측정]`. pilot 2에는 fd 자식 셀이 없다. pilot 1 a3의 예비 없음 시행은 그때의 간격 한도로 `inject_late` 제외였다.
지난 시행의 판정 순서는 pilot 8 events.py로 다시 뽑았다: 펜스 끈 멈춤의 자기 판정 셋이 pilot 1 r0 10 004.0, r2 10 005.1, r1 10 005.3, pilot 2 r2 10 090.7, r0 10 091.8, r1 10 091.9로 마지막이 첫 판정 1.2–1.3 ms 뒤였다(`judge_spread_ms` 1.258, 1.201) `[측정]`.

## 답

- **`n_judge`는 펜스 끈 멈춤 셀에서만 바뀌었다(3 → 2)** `[측정]`. r2가 자기 판정 전에 r0의 결정을 받아 적용했고(r0의 자기 판정 4.6 ms 뒤, r0의 보냄 2.9 ms 뒤), 그 뒤 r2의 자기 판정 줄은 없다. `judge_causes`도 `STALL_HELPER:2`가 됐다.
- 그 셀의 예측 조건(`stall_none_refuse`)은 `n_judge_stall_helper >= 1`만 보므로 그대로 맞다(1/1) `[측정]`.
- fd 자식 셀과 예비 없음 셀은 바뀌지 않았다(3/3, 결정 여섯씩 모두 늦음) `[측정]`. 두 셀은 판정이 launcher 보고나 FIN으로 0.4 ms, 1.8 ms 안에 모두 나고, 결정은 decline 뒤에만 나므로(판정 뒤 1.5 ms, 174 ms) 판정 줄을 앞지를 틈이 없다 `[추론]`.
  STALL 길의 판정은 생존 rank마다 probe 주기의 위상으로 갈리므로 거기서만 결정이 판정을 앞지른다 `[추론]`. pilot 7의 기다리는 rank도 멈춘 셀 n1과 같은 꼴이다.

## 문제 (고치지 않음; 라이브러리와 채점기는 보고만)

1. **[라이브러리 또는 채점 규칙, 결정 필요] STALL 길의 decline에서 남의 결정이 자기 판정을 앞질러 `n_judge`를 줄인다**(이번 1/1, pilot 7 기다리는 셀 1/2).
   이번 세 예측 중 `n_judge == n_surv`를 요구하는 것은 `fdhold_uverbs_refuse`뿐이다. 그 셀은 EXITED 길이면 영향이 없으나, 조건이 받아 주는 박동 정체 길(STALL_HELPER, STALL)로 판정되면 같은 일이 일어나 조건이 깨질 수 있다 `[추론]`. 다른 셀의 STALL decline은 재지 않았다 `[미확인]`.
2. **[관찰] 멈췄다 풀린 rank 3이 rank 0에 대한 결정(cause `every`, 0.0 ms)을 기록했고 보내지 않았다**(보냄 줄 0, `ad_*` 0) `[측정]`. 셀 결과(`surv_released` 4, rc 4)는 지난 시행과 같다. 이 줄의 뜻은 확인하지 않았다 `[미확인]`.
3. **[관찰] fd 자식 셀의 결정 cause는 `FIN`, 판정 원인은 `EXITED`다** `[측정]`. 결정 이름표가 판정 표 원인과 다른 이름을 쓰는 까닭은 소스로 보지 않았다 `[미확인]`.

## 하지 않은 것

- 다시 돌린 시도 없음(STOP 0). 다른 클러스터 실행 없음.
- 셀 n을 늘려 STALL 길의 비율을 재는 것: 지시 범위 밖.

원자료는 [a1/raw/](a1/raw/)(IPv4 가림, 48 파일, 5 991줄, 폴더 전체 1.1 MB, 5 MB 넘는 파일 없음), 시행 표 [a1/trials.csv](a1/trials.csv), 사슬 기록 [chain.out](chain.out), 시도 기록 [attempts.txt](attempts.txt), 묶음 md5 [md5chk.txt](md5chk.txt),
hold 출력 [a1/run_PCELL.out](a1/run_PCELL.out), 묶는 스크립트 [pack.py](pack.py), 실행 스크립트 [hold.sh](hold.sh)다. IPv4 꼴 0건, 관리망 주소 0건 `[측정: grep]`.
