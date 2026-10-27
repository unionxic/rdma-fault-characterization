# gin-control pilot 7 (2026-10-28 02:33–02:41, 채점 안 함)

확정된 중단 결정이 상대와 나중 화신에게 가는 고침(piece ①, 기록 57 `ABORT_DECIDED`; 라이브러리 gc `ed13666b`, [../../impl/notes_abortdec.md](../../impl/notes_abortdec.md))을 실제 RNIC, launcher, 두 노드에서 처음 돌렸다.
pilot 5 문제 1(복원된 rank 3이 기다리던 rank의 판정을 따르지 않고 watchdog까지 멈춤)을 고쳤는지가 주 질문이고, 나머지 일곱 시행은 같은 라이브러리에서 다른 셀의 결과가 바뀌지 않았는지 보는 대조다.
pilot은 본 실험에 들지 않고 채점하지 않는다. 판과 셀 env는 [VERSIONS.md](VERSIONS.md)다.

표시: `[측정]` 원자료에서 다시 셈, `[소스]` 코드를 읽음, `[추론]` 해석, `[미확인]` 확인 안 함. 시각은 그 시행의 첫 주입 줄(GPU hang 셀은 rank 3의 `GINRS gpuhang`, 조용한 셀은 `GINRS quiet`,
kill은 `GINRS killed`, SIGSTOP은 `GINRS stop`) 뒤 ms이고, sunny 줄은 meta의 노드 시계 차로 rain 시계에 옮겼다. 두 죽음 셀은 첫 kill 줄(`GINRS die rank=2`) 뒤 ms다.
사건 목록은 [events/](events/)(스크립트 [events.py](events.py): pilot 5 판에 결정 줄 일곱 꼴을 더함; 두 죽음은 pilot 6의 [twodeath.py](twodeath.py)), 시행마다의 요약은 [summary.txt](summary.txt)([summ.py](summ.py))다.

## 시도

`harness/gpu-initiated/common/cluster_run.sh` 안에서 `chain_gc.sh` → `hold_gc.sh`로 hold 셋을 돌렸고 STOP 규칙이 켜져 있었다. 시도 1번(한도 10), 클러스터 시간 02:33:09–02:40:57(약 7분 48초, 한도 3 h) `[측정: chain.out, attempts.txt]`.

| hold (파일 꼬리표) | 시각 | 시행 | 결과 |
|---|---|--:|---|
| `PCELL-gc4_gpuhang12000_waiter_hung+gc4_gpuhang12000_waiter_hung+gc4_gpuhang12000_waitpend_fence+gc4_gpuhang12000_fence+gc4_gpuhang12000_ctx1_fence` (`PCELL1`) | 02:33:09–02:37:49 | 5 | STOP 0, 건너뜀 0 |
| `PCELL-gc4_stop12000_fence+gc4_kill3_ow+gc4_quiet12000` (`PCELL2`) | 02:37:49–02:39:56 | 3 | STOP 0 |
| `PRC-gc-mi4_kill2_kill3_ow` (`PRC`) | 02:39:56–02:40:57 | 1 | STOP 0 |

- 세 hold 모두 새 mlx5 커널 줄 0, rain 펌웨어 명령 실패 합 31 그대로, rain mlx5 cmd_err 2 그대로, 남은 프로세스 0, QUERY_QP 상한 넘음 0(`qp_over.txt` 없음), launcher STOP 줄 0, launcher QP 잃음 0 `[측정: a1/snap_*, a1/mlx5_new_*, a1/trials.csv]`.
- 실행기 쪽 기록 하나: [hang_watchdog.txt](hang_watchdog.txt)(기다리는 rank도 멈춘 셀 두 시행의 rank 1이 자기 watchdog으로 끝남, 두 줄, 설계대로 STOP 아님). **`spare_wait.txt`는 생기지 않았다**(pilot 5에서는 같은 두 시행의 예비 프로세스가 watchdog).
- 실행기 고침 하나(`hold_gc.sh` `PCELL-`가 같은 이름의 반복을 n1..nk로 받음, 돌리기 전, VERSIONS.md). 라이브러리, 채점기, 셀 파일은 고치지 않았다.

## 시행마다

| 시행 | wall | 끝 | 판정(대상: 관측자 원인 시각 ms) | ABORT_DECIDED | 복원(첫 판정 → 마지막 `restored`) | 데이터 같음 |
|---|--:|---|---|---|---|---|
| 기다리는 rank도 멈춤 n1 | 60.5 s | r0, r2, 예비 rc 4(released), r1 rc 7(watchdog) | rank 3: r0, r1 STALL 10 042.0–10 042.1, r2 10 044.2. rank 1: r0 STALL 12 343.6 | r0이 정함, r2와 예비가 적용 | 186.1 ms | 0 |
| 기다리는 rank도 멈춤 n2 | 60.5 s | 같음 | rank 3: r0, r2, r1 STALL 10 057.8–10 060.0. rank 1: r2 12 355.5, r0 12 356.6 STALL | r2가 정함(예비 적용), r0도 정함(늦음 셋) | 181.3 ms | 0 |
| 셀 B (rank 1 `GC_WAITPEND`) n1 | 21.1 s | 모두 rc 0 | rank 3: r1, r0 STALL 10 081.9, r2 10 083.0. rank 1: 없음 | 없음(ad 모두 0) | 197.4 ms | 1 |
| GPU hang 대조 n1 | 21.1 s | 모두 rc 0 | rank 3: r1, r0, r2 STALL 10 016.7–10 018.8 | 없음 | 182.6 ms | 1 |
| GPU hang 문맥 1만 n1 | 21.1 s | 모두 rc 0 | rank 3: r0, r1, r2 STALL 10 073.2–10 076.5 | 없음 | 184.6 ms | 1 |
| SIGSTOP 12 s n1 | 21.1 s | 모두 rc 0 | rank 3: r0, r2 STALL_HELPER 10 090.4, r1 10 092.6 | 없음 | 187.9 ms | 1 |
| kill n1 | 11.1 s | 모두 rc 0 | rank 3: r0 FIN+STALE 21.1, r1, r2 21.2 | 없음 | 166.8 ms (`t_publish_ms` 157.0) | 1 |
| 두 죽음 n1 | 11.0 s | r0, r1, 예비 둘 rc 0 | rank 2: r0, r1, r3 FIN+STALE 20.9–21.2. rank 3: r1, r0, rank 2 화신 1 FIN+STALE 20.7–22.4(둘째 kill 뒤) | 없음 | `restore_time_ms_1` 177.3, `_2` 176.4 ms | 1 |
| 조용한 긴 계산 n1 | 22.6 s | 모두 rc 0 | 없음(의심 0) | 없음 | 없음 | 1 |

열 값은 `rows_gc.py`가 원자료에서 다시 셈한 [a1/trials.csv](a1/trials.csv)와 사건 목록에서 읽었다 `[측정]`. 아홉 시행 모두 `inject_ok` 1(두 죽음은 빈칸, gin-mirror 셀), `probe_timeout_n` 0, `witness_pairs` 6, `win_verified` 1(복원 시행)이다.
"복원"은 사건 목록의 첫 판정 줄에서 생존 rank의 마지막 `rank 3 restored as incarnation` 줄까지다. 판정 시각은 모두 pilot 5의 띠와 같은 쪽이다(GPU hang 10 016.7–10 083.0, `stop_judge_ms` 띠 10 000–10 500; SIGSTOP 10 090.4–10 092.6, 띠 10 000–10 300; kill 21.1–21.2).

## 기다리는 rank도 멈춤: 복원된 rank 3이 남의 결정으로 풀림 (n 2)

**두 시행 모두 복원된 rank 3(예비 프로세스)이 생존 rank가 보낸 `ABORT_DECIDED`를 받아 적용했고, 생존 rank와 1.2–2.6 ms 차로 `released=1`, `exit=4 xchg=released`로 끝났다. watchdog은 없다(pilot 5는 두 시행 모두 예비가 `watchdog=1 exit=7`, 약 57 s).** `[측정]`

| 시각 (ms) | n1 | n2 |
|---|---|---|
| rank 3 판정(STALL) / FENCE / FENCED | 10 042.0–10 044.2 / 10 050.1 / 10 152.2 | 10 057.8–10 060.0 / 10 064.2 / 10 168.5 |
| `restored as incarnation 1`(생존 셋) | 10 227.3–10 228.1 | 10 238.2–10 239.1 |
| `wait ended (its peers resolved, no progress within G …)` | 12 238.5 (r2), 12 241.7 (r0) | 12 254.3 (r2), 12 255.6 (r0) |
| rank 1 판정(STALL) | 12 343.6 (r0) | 12 355.5 (r2), 12 356.6 (r0) |
| 자기 decline(`liveness stall judged (STALL)`) | 12 345.3 (r0) | 12 357.4 (r2), 12 359.5 (r0) |
| `confirmed abort decision no. 1 (incarnation 0): rank 1 (incarnation 0), cause STALL, … released in 2000.0 ms (sent by the helper)` | 12 345.4 (r0) | 12 357.5 (r2), 12 359.6 (r0) |
| `ABORT_DECIDED(rank 1, incarnation 0, no. 1, cause STALL) … sent to` | r0 → rank 2 (화신 0) 2 000.0 ms 남음, → rank 3 (화신 1) 1 999.9 ms 남음, 12 345.4 | r2 → rank 0, rank 3, 12 357.5; r0 → rank 2, rank 3, 12 359.6 (남은 몫 같음) |
| 받음 → `applied, waits released in L ms (no hold, no fence)` | 예비 12 347.4 (from rank 0, L 1 998.1), r2 12 348.3 (from rank 0, L 1 997.2) | 예비 12 359.5 (from rank 2, L 1 998.0) |
| 받음 → `late (this rank declined it or applied a decision about it already): no effect` | 없음 | r2 12 359.6 (r0의 것), r0 12 360.2 (r2의 것), 예비 12 360.2 (r0의 것) |
| `released=1`(걸음 157) | 예비 14 346.3, r0 14 347.5, r2 14 348.8 | 예비 14 359.5, r2 14 360.9, r0 14 362.1 |
| rank 1 끝 | launcher EXITED 57 291.2, kv `watchdog=1 exit=7` | 57 311.1, 같음 |

- **받아들임 항목별** `[측정]`.
  - 복원된 rank 3 `exit=4 xchg=released`, `watchdog` 키 없음: 2/2.
  - 그 `released=1`이 생존 rank의 `released=1`과 2 000 ms 안: 2/2(예비가 1.2–2.5 ms, 1.4–2.6 ms 먼저). 받는 쪽은 도착 시각 + 남은 ms로 해제 시각을 적으므로 세 프로세스가 첫 정한 rank의 해제 시각(결정 + 2 000 ms) 뒤 0.9–3.4 ms(n1), 2.0–4.6 ms(n2) 안에 풀렸다.
  - 예비의 probe summary `ad_rx_applied` ≥ 1이고 그 결정의 대상이 rank 1 화신 0: 2/2(n1 `peer0:ad_rx_applied=1`, n2 `peer2:ad_rx_applied=1 peer0:ad_rx_late=1`; summary는 전달자마다 세므로 대상은 받음 줄에서 읽음).
  - rank 1(멈춘 대기자)은 그대로 watchdog: 2/2(hang_watchdog.txt).
  - 생존 r0, r2: 마지막 복원 줄 뒤 rank 1 STALL 판정 2 115.5–2 117.5 ms(판정 셋, 두 시행; pilot 5 2 021.3–2 122.8), rc 4: 2/2. **"자기 decline"은 n2만 맞고 n1은 다르다**(아래).
- **n1의 r2는 rank 1을 스스로 판정하지 않았다.** r0의 결정을 12 348.3에 받아 적용했고(decline 사유 `ABORT_DECIDED(rank 1, incarnation 0, no. 1, cause STALL) of rank 0 (incarnation 0): a confirmed abort decision`), 그 뒤 r2의 rank 1 판정 줄, 결정 줄은 없다 `[측정]`.
  r2의 문은 r0보다 3.2 ms 먼저 열렸으나 판정은 probe 한 주기(100 ms) 위상에 따라 r0이 먼저 했다 `[추론]`. notes_abortdec.md 열린 문제 2("생존 rank 결과가 바뀐다")가 장치에서 보인 것이다. 결과(r2의 해제 시각, rc 4)는 r0의 결정 시각을 따랐다(r2 14 348.8; pilot 5 n1 r2 14 361.6).
  그래서 n1의 채점기 열은 `judged_ranks` `3:10042.0:3+1:12343.6:1`, `waiter_judge_n` 1, `waiter_judge_causes` `STALL:1`이다(pilot 5 n1 `FIN+STALE:1+STALL:2`). 열 정의(대기자 대상 DEAD, STALLED 줄을 낸 관측 프로세스 수)대로 센 것이고, 이 셀은 pilot 전용이라 예측이 없다.
- **n2는 둘 다 스스로 정했다.** r2가 1.1 ms 먼저 판정해 결정을 보냈으나 r0의 받음(12 360.2)은 r0 자신의 decline(12 359.5) 뒤라 늦음이었다. 예비는 r2의 것을 적용하고 r0의 것을 늦음으로 셌다. 결정 둘, 적용 하나, 늦음 셋, dup 0 `[측정]`.
- `ABORT_DECIDED`나 `confirmed abort decision`이 든 줄은 이 두 시행의 r0, r2, 예비 로그에만 있다(합 21줄, decline과 degraded 줄 포함). 다시 보냄(`sent again`), `owed`, blob, 계보 완성 줄은 0이다 `[측정: grep]`. 이 셀의 결정은 복원 뒤에 났기 때문이다(blob 길을 거치지 않음) `[추론]`.
- 복원된 rank 3은 r0의 STALLED(rank 1)도 받았다(n1 12 344.1). pilot 5에서 보지 못한 예비의 판정이 이번에도 없고(예비 자신의 rank 1 판정 줄 0), 풀림은 결정의 적용으로만 왔다 `[측정]`.

## 대조 일곱 시행: 바뀐 것 없음

- **결정이 나지 않았다.** 일곱 시행의 생존 rank와 예비 프로세스 로그 모두 probe summary의 `ad_*` 여덟 칸이 0이고(`ad_tx`, `ad_rx_applied` 포함), 결정 줄 0이다 `[측정: summary.txt]`. 모두 hold로 가져간 판정이거나(복원) 판정이 없는 셀이라 decline 전이가 없다 `[추론]`.
- **두 죽음(`mi4_kill2_kill3_ow@gc`)**: 복원만 있는 시행에서 결정이 발화하지 않아야 한다는 조건이 맞았다. r0, r1, rank 2 화신 1(예비), rank 3 화신 1(둘째 예비)의 `ad_tx` 0, `ad_rx_applied` 0 `[측정]`.
  둘째 kill은 첫 복원 마지막 줄 뒤 1 587.5 ms, 둘째 판정 20.7–22.4 ms, `restore_time_ms_1` 177.3, `_2` 176.4 ms로 pilot 6 4 KiB(172.6–175.7 ms, pilot 3 172.8–195.6 ms)와 같은 띠다. `second_ok` 1, `ow_data_equal` 1 `[측정: a1/trials.csv, events/mi4_kill2_kill3_ow_gc_n1_twodeath.txt]`.
- **셀 B**: rank 1은 한 번도 판정되지 않았고(`waiter_judge_n` 0, `waiter_fenced` 0), `wait_peer` 3, `wait ended (progress: it left the stalled set)` r2, r0(waited 8 598.9, 8 602.7 ms), rank 1의 칸 기다림 `result=satisfied`, 복원, 데이터 같음 `[측정]`. pilot 5와 같다.
- 대조, 문맥 1, SIGSTOP, kill: 생존 셋 모두 같은 원인으로 판정, 펜스, 복원, 데이터 같음. 조용한 긴 계산: 의심, 판정, hold 0, `quiet_periods` 114, 데이터 같음, 예비 안 씀 `[측정]`.

## 예측이 이 시행에서 읽히는 것 (채점 아님)

`score_gc.py`(`7b36c065`, 바꾸지 않음)를 세션 스크래치 사본에서 pilot 5와 같은 방식(`score_pilot.py`: pilot 표시 끔, 계획 n을 있는 시행 수로)으로 돌렸다. 출력은 [score_v0/](score_v0/)다. 채점기 결함을 찾지 못해 `score_v1/`은 없다.

| 예측 (ID) | 무엇을 예측했나 | 이 pilot에서 |
|---|---|---|
| 멈춘 GPU의 펜스와 복원 (`gpuhang_fence_restore`) | 생존 셋 STALL 10 000–10 500 ms, 펜스, 복원, 데이터 같음 | 대조 1/1, 셀 B 1/1 (자료 부족(n<k)) |
| 문맥 0 밖 GPU 멈춤의 펜스 (`gpuhang_ctx1_fence_restore`) | 같음, `stall_ctx` 1 | 1/1 (자료 부족(n<k)) |
| 멈춘 rank를 기다리는 정상 rank는 판정하지 않음 (`waiter_not_judged`, safety) | rank 1 판정 0, 펜스 0, 기다림과 진행 줄, 복원, 데이터 같음 | 1/1, 사본에서 "맞음" |
| 조용한 긴 계산은 판정하지 않음 (`quiet_compute_no_judge`, safety) | 의심, 판정, hold 0, `quiet_periods` ≥ 100 | 1/1, 사본에서 "맞음" |
| 긴 멈춤의 펜스 뒤 복원 (`stall_fence_restore`) | STALL_HELPER 10 000–10 300 ms, 펜스, 복원 | 1/1 (자료 부족(n<k)) |
| kill의 RDMA 판정 (`kill_judge_rdma`) | FIN+STALE, 확인 창 | `gc4_kill3_ow` 1/1 (다른 셀 없음 → 자료 부족) |
| RDMA 제어에 TCP 없음 (`no_tcp_control`, safety) | `build:gc` 묶음의 `tcp_ctrl_bytes` 0, 증인 쌍 | 7/7 (다른 셀 없음 → 자료 부족) |

기다리는 rank도 멈춘 셀 두 시행은 pilot 전용 셀이라 `config` 상태(채점 대상 아님)다.

## 문제 (고치지 않음; 라이브러리는 보고만)

1. **[라이브러리, 관찰, 결정 필요] 남의 결정이 생존 rank의 자기 판정을 앞질러 결과 열을 바꾼다**(n1, 1/2). 설계 문서가 예상한 것이다(notes_abortdec.md 열린 문제 2, review3 5).
   본 실행에서 생존 rank 둘 이상이 같은 상대를 decline하는 셀(채점기 열 `waiter_judge_causes`, `spare_absent_refused`, `fdhold_uverbs_refuse`, `stall_none_refuse`의 자기 판정 수)의 조건이 "판정한 관측자 수"를 세면 이 결정이 그 수를 줄일 수 있다 `[추론]`. 이 pilot의 그런 셀은 기다리는 rank도 멈춘 셀뿐이고 예측이 없다. 다른 셀은 재지 않았다 `[미확인]`.
2. **[미확인으로 남음] blob, 다시 보냄, 계보 완성 길은 장치에서 걸리지 않았다.** 이번 결정은 모두 복원이 끝난 뒤, 상대가 LIVE일 때 나서 record 57 첫 보냄으로 갔다. activation 전이나 REJOIN_ACK 전에 결정이 나는 셀(notes_abortdec.md 장면 A5a–A5c)은 셀 파일에 없다.
3. **[보고 열] 기다리는 rank도 멈춘 셀의 `data_equal` 0, `revived_done` 0은 그대로다.** rank 1의 decline으로 communicator가 오류로 끝나는 셀이라 그렇다(pilot 5와 같음) `[추론]`.

## 하지 않은 것

- 다시 돌린 시도 없음(STOP 0). 시도 9번, 약 2시간 52분이 남았다.
- 생존 rank의 결과가 바뀌는 다른 셀(위 문제 1)을 돌리는 것: 지시 범위 밖.

원자료는 [a1/raw/](a1/raw/)(IPv4 가림, 148 파일, 합 5.5 MB, 5 MB 넘는 로그 없음), 시행 표 [a1/trials.csv](a1/trials.csv), 사슬 기록 [chain.out](chain.out), 시도 기록 [attempts.txt](attempts.txt), 배포 출력 [deploy.txt](deploy.txt),
driver 빌드 로그 [build_drv.log](build_drv.log), hold 출력 `a1/run_*.out`, 묶는 스크립트 [pack.py](pack.py), 실행 스크립트 [hold.sh](hold.sh)다. IPv4 꼴 0건, 관리망 주소 0건 `[측정: grep]`.
