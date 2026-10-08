# gin-oneway 채점 결과

`score.py`가 원자료(`results/20261008/`의 hold별 시행 파일)에서 만들었다. 손으로 고친 값은 없다.

- 예측 파일 sha256: `8f5c0602f1149102b5a0c4f50a1cb872d5f7bdf5b3d3dcbc5899ead83d750add`. `PREREG.txt`의 값과 같다.
- 시행 수(모든 hold): 125. 판정한 시행: 125.
- 판정식 원문은 `predictions.csv`, 열과 문법은 `EXPERIMENT.md` 3절.

## 판정 요약

| 예측 | 셀 | n | 맞은 시행(조건별) | 판정 |
|---|---|--:|---|---|
| 한쪽 끊김 시험이 의도대로 됨: 끊긴 rank 1이 먼저 시간 초과하고 그 리셋을 rank 0이 받음 (A0) | `ow_r1in_f1_b@ow` | 10 | 10/10 | 맞음 |
| rank 0이 리셋을 모름으로 두고 두 rank 모두 살아 있는 상대를 죽음으로 보지 않음 (A1) | `ow_r1in_f1_b@ow` | 10 | 0/10 | 틀림 |
| 두 rank가 한 번씩 다시 연결되고 rank 0은 끊김이 끝난 뒤 1.5 s 안 (A2) | `ow_r1in_f1_b@ow` | 10 | 10/10 | 맞음 |
| 12 s의 로컬 QP 오류가 투명하게 복구되고 거절과 장애 전 비동기 오류가 없음 (A3) | `ow_r1in_f1_b@ow` | 10 | 10/10 | 맞음 |
| 기준 빌드: rank 0이 리셋을 죽음으로 보고 장애를 ECONNRESET으로 거절함(rank 1은 살아 있고 다시 연결되지 않음) (K1) | `ow_r1in_f1_b@pcm` | 5 | 5/5 | 맞음 |
| 거울 방향 시험이 의도대로 됨: 끊긴 rank 0이 먼저 시간 초과하고 그 리셋을 rank 1이 받음 (B0) | `ow_r0in_f1r1_b@ow` | 10 | 10/10 | 맞음 |
| rank 1이 리셋을 모름으로 두고 두 rank 모두 살아 있는 상대를 죽음으로 보지 않음 (B1) | `ow_r0in_f1r1_b@ow` | 10 | 0/10 | 틀림 |
| 끊김 중 rank 1의 장애가 재연결을 기다리고, 끊김이 끝난 뒤 1.5 s 안에 재연결로 끝남 (B2) | `ow_r0in_f1r1_b@ow` | 10 | 10/10 | 맞음 |
| 그 뒤 rank 1이 시작 쪽으로 복구하고 투명함 (B3) | `ow_r0in_f1r1_b@ow` | 10 | 10/10 | 맞음 |
| 기준 빌드: rank 1이 리셋을 죽음으로 보고 장애를 ECONNRESET으로 거절함 (K2) | `ow_r0in_f1r1_b@pcm` | 5 | 5/5 | 맞음 |
| 끊김이 끝난 뒤 rank 1의 확인 접속이 거부되어 죽은 rank 0을 죽음으로 알아냄(끊김 중에는 죽음으로 정하지 않음) (D1) | `ow_kill0_b@ow` | 10 | 10/10 | 맞음 |
| rank 1의 재시도 초과가 죽음 원인(ECONNREFUSED)으로 거절되고 모름 거절과 복구가 없음 (D2) | `ow_kill0_b@ow` | 10 | 10/10 | 맞음 |
| 그 거절이 rank 1의 첫 분류 기록 뒤 2 s 안에 옴 (D3) | `ow_kill0_b@ow` | 10 | 10/10 | 맞음 |
| 기준 빌드: rank 1이 죽은 rank 0을 모르고 10 s 상한 뒤 모름으로 거절함 (K3) | `ow_kill0_b@pcm` | 5 | 5/5 | 맞음 |
| rank 1이 첫 재연결을 거부해도 rank 0은 받아들여지지 않음으로 남기고 아무도 상대를 죽음으로 보지 않음 (E1) | `ow_hello_f1_b@ow` | 10 | 0/10 | 틀림 |
| 다음 다시 걸기로 두 rank가 한 번씩 다시 연결되고 rank 0은 끊김이 끝난 뒤 2 s 안 (E2) | `ow_hello_f1_b@ow` | 10 | 10/10 | 맞음 |
| 12 s의 로컬 QP 오류가 투명하게 복구됨(재연결 거부 셀) (E3) | `ow_hello_f1_b@ow` | 10 | 10/10 | 맞음 |
| 기준 빌드: rank 0이 재연결로 센 뒤 거부의 FIN을 읽고 상대를 죽음으로 보며 장애를 FIN으로 거절함 (K4) | `ow_hello_f1_b@pcm` | 5 | 5/5 | 맞음 |
| 시간 초과 시험 스위치 없이 배포된 pc가 한쪽 끊김 뒤 살아 있는 rank 0을 ECONNRESET으로 거절함(5회 중 2회 이상) (U1) | `ow_r0in_nat_f1r1_b@pc` | 5 | 5/5 | 맞음 |
| 같은 경주 조건에서 새 빌드는 투명하고 아무도 상대를 죽음으로 보지 않음 (U2) | `ow_r0in_nat_f1r1_b@ow` | 5 | 0/5 | 틀림 |
| 복구 재현 셀이 그대로 투명 (G1) | `f1_b@ow`, `f3_b@ow`, `bidirf_sym_b@ow`, `rc_mute8_f1_b@ow` | 5 / 5 / 5 / 5 | 5/5; 5/5; 5/5; 5/5 | 맞음 |
| 양쪽 8 s 끊김에서 두 rank가 한 번씩 1.5 s 안에 다시 연결되고 죽음 줄이 없음 (G2) | `rc_mute8_f1_b@ow` | 5 | 0/5 | 틀림 |
| 끊김 없는 kill은 죽음 원인(FIN 또는 ECONNREFUSED)으로 거절되고 abort가 돌아옴 (G3) | `f4_b@ow` | 5 | 5/5 | 맞음 |
| 양쪽 끊김 중 kill된 rank 1은 다시 걸기 거부로 죽음 거절되고 모름 거절이 없음 (G4) | `rc_mutekill_b@ow` | 5 | 5/5 | 맞음 |
| 받는 쪽 abort 해제가 그대로 (G5) | `f2rel_b@ow` | 5 | 5/5 | 맞음 |
| 상대 QP 오류 뒤 teardown 때 두 rank의 모든 QP가 RTS (G6) | `f3_b@ow` | 5 | 5/5 | 맞음 |
| 4 KiB 지연 차이 0.40 µs 이하(대조) (L1) | `lat_ow_on_4k@ow`, `lat_pc_on_4k@pc` | 5 / 5 | abs(10.560 - 10.560) <= 0.40 | 맞음 |
| 256 KiB 지연 차이 0.30 µs 이하(대조) (L2) | `lat_ow_on_256k@ow`, `lat_pc_on_256k@pc` | 5 / 5 | abs(38.910 - 38.910) <= 0.30 | 맞음 |

## 예측별 세부

### 한쪽 끊김 시험이 의도대로 됨: 끊긴 rank 1이 먼저 시간 초과하고 그 리셋을 rank 0이 받음 (A0): 맞음

- 판정식: `count(close1_cause_r0 == "ECONNRESET" and close1_cause_r1 == "ETIMEDOUT") >= 9`
- 셀 `ow_r1in_f1_b@ow`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(close1_cause_r0 == "ECONNRESET" and close1_cause_r1 == "ETIMEDOUT")` = 10/10. 조건을 만족하지 않은 시행: 없음

### rank 0이 리셋을 모름으로 두고 두 rank 모두 살아 있는 상대를 죽음으로 보지 않음 (A1): 틀림

- 판정식: `count(close1_lv_r0 == "unknown" and n_dead_r0 == 0 and n_dead_r1 == 0) >= 9`
- 셀 `ow_r1in_f1_b@ow`: 판정한 시행 10회, 대입한 식 `0 >= 9` → 거짓
  - `count(close1_lv_r0 == "unknown" and n_dead_r0 == 0 and n_dead_r1 == 0)` = 0/10. 조건을 만족하지 않은 시행: ow_r1in_f1_b_n1, ow_r1in_f1_b_n2, ow_r1in_f1_b_n3, ow_r1in_f1_b_n4, ow_r1in_f1_b_n5, ow_r1in_f1_b_n6, ow_r1in_f1_b_n7, ow_r1in_f1_b_n8, ow_r1in_f1_b_n9, ow_r1in_f1_b_n10

### 두 rank가 한 번씩 다시 연결되고 rank 0은 끊김이 끝난 뒤 1.5 s 안 (A2): 맞음

- 판정식: `count(n_reconn_r0 == 1 and n_reconn_r1 == 1 and 0 <= reconn_after_unmute_ms_r0 <= 1500) >= 9`
- 셀 `ow_r1in_f1_b@ow`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(n_reconn_r0 == 1 and n_reconn_r1 == 1 and 0 <= reconn_after_unmute_ms_r0 <= 1500)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 12 s의 로컬 QP 오류가 투명하게 복구되고 거절과 장애 전 비동기 오류가 없음 (A3): 맞음

- 판정식: `count(transparent_ok == 1 and not nonempty(decl_r0) and async_before_fault == 0) >= 9`
- 셀 `ow_r1in_f1_b@ow`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(transparent_ok == 1 and not nonempty(decl_r0) and async_before_fault == 0)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 기준 빌드: rank 0이 리셋을 죽음으로 보고 장애를 ECONNRESET으로 거절함(rank 1은 살아 있고 다시 연결되지 않음) (K1): 맞음

- 판정식: `count(close1_cause_r0 == "ECONNRESET" and close1_lv_r0 == "dead" and has(decl_r0, "no helper socket to the peer (ECONNRESET)") and r1_alive_at_decline == 1 and n_reconn_r1 == 0) >= 4`
- 셀 `ow_r1in_f1_b@pcm`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(close1_cause_r0 == "ECONNRESET" and close1_lv_r0 == "dead" and has(decl_r0, "no helper socket to the peer (ECONNRESET)") and r1_alive_at_decline == 1 and n_reconn_r1 == 0)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 거울 방향 시험이 의도대로 됨: 끊긴 rank 0이 먼저 시간 초과하고 그 리셋을 rank 1이 받음 (B0): 맞음

- 판정식: `count(close1_cause_r1 == "ECONNRESET" and close1_cause_r0 == "ETIMEDOUT") >= 9`
- 셀 `ow_r0in_f1r1_b@ow`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(close1_cause_r1 == "ECONNRESET" and close1_cause_r0 == "ETIMEDOUT")` = 10/10. 조건을 만족하지 않은 시행: 없음

### rank 1이 리셋을 모름으로 두고 두 rank 모두 살아 있는 상대를 죽음으로 보지 않음 (B1): 틀림

- 판정식: `count(close1_lv_r1 == "unknown" and n_dead_r0 == 0 and n_dead_r1 == 0) >= 9`
- 셀 `ow_r0in_f1r1_b@ow`: 판정한 시행 10회, 대입한 식 `0 >= 9` → 거짓
  - `count(close1_lv_r1 == "unknown" and n_dead_r0 == 0 and n_dead_r1 == 0)` = 0/10. 조건을 만족하지 않은 시행: ow_r0in_f1r1_b_n1, ow_r0in_f1r1_b_n2, ow_r0in_f1r1_b_n3, ow_r0in_f1r1_b_n4, ow_r0in_f1r1_b_n5, ow_r0in_f1r1_b_n6, ow_r0in_f1r1_b_n7, ow_r0in_f1r1_b_n8, ow_r0in_f1r1_b_n9, ow_r0in_f1r1_b_n10

### 끊김 중 rank 1의 장애가 재연결을 기다리고, 끊김이 끝난 뒤 1.5 s 안에 재연결로 끝남 (B2): 맞음

- 판정식: `count(wait_end_r1 == "reconnected" and 0 <= reconn_after_unmute_ms_r1 <= 1500) >= 9`
- 셀 `ow_r0in_f1r1_b@ow`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(wait_end_r1 == "reconnected" and 0 <= reconn_after_unmute_ms_r1 <= 1500)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 그 뒤 rank 1이 시작 쪽으로 복구하고 투명함 (B3): 맞음

- 판정식: `count(transparent_ok == 1 and not nonempty(decl_r1) and rec_init_r1 >= 1) >= 9`
- 셀 `ow_r0in_f1r1_b@ow`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(transparent_ok == 1 and not nonempty(decl_r1) and rec_init_r1 >= 1)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 기준 빌드: rank 1이 리셋을 죽음으로 보고 장애를 ECONNRESET으로 거절함 (K2): 맞음

- 판정식: `count(close1_cause_r1 == "ECONNRESET" and close1_lv_r1 == "dead" and has(decl_r1, "no helper socket to the peer (ECONNRESET)")) >= 4`
- 셀 `ow_r0in_f1r1_b@pcm`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(close1_cause_r1 == "ECONNRESET" and close1_lv_r1 == "dead" and has(decl_r1, "no helper socket to the peer (ECONNRESET)"))` = 5/5. 조건을 만족하지 않은 시행: 없음

### 끊김이 끝난 뒤 rank 1의 확인 접속이 거부되어 죽은 rank 0을 죽음으로 알아냄(끊김 중에는 죽음으로 정하지 않음) (D1): 맞음

- 판정식: `count(n_probe_ref_r1 >= 1 and dead_cause_r1 == "ECONNREFUSED" and dead_ms_r1 >= mute_off_ms_r1) >= 9`
- 셀 `ow_kill0_b@ow`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(n_probe_ref_r1 >= 1 and dead_cause_r1 == "ECONNREFUSED" and dead_ms_r1 >= mute_off_ms_r1)` = 10/10. 조건을 만족하지 않은 시행: 없음

### rank 1의 재시도 초과가 죽음 원인(ECONNREFUSED)으로 거절되고 모름 거절과 복구가 없음 (D2): 맞음

- 판정식: `count(has(decl_r1, "RETRY_EXC and the peer's socket shows ECONNREFUSED") and not has(decl_r1, "unknown") and rec_init_r1 == 0) >= 9`
- 셀 `ow_kill0_b@ow`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(has(decl_r1, "RETRY_EXC and the peer's socket shows ECONNREFUSED") and not has(decl_r1, "unknown") and rec_init_r1 == 0)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 그 거절이 rank 1의 첫 분류 기록 뒤 2 s 안에 옴 (D3): 맞음

- 판정식: `count(0 <= decl_after_q4_ms_r1 <= 2000) >= 9`
- 셀 `ow_kill0_b@ow`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(0 <= decl_after_q4_ms_r1 <= 2000)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 기준 빌드: rank 1이 죽은 rank 0을 모르고 10 s 상한 뒤 모름으로 거절함 (K3): 맞음

- 판정식: `count(has(decl_r1, "RETRY_EXC and peer liveness unknown (ETIMEDOUT, no reconnect within 10000 ms)")) >= 4`
- 셀 `ow_kill0_b@pcm`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(has(decl_r1, "RETRY_EXC and peer liveness unknown (ETIMEDOUT, no reconnect within 10000 ms)"))` = 5/5. 조건을 만족하지 않은 시행: 없음

### rank 1이 첫 재연결을 거부해도 rank 0은 받아들여지지 않음으로 남기고 아무도 상대를 죽음으로 보지 않음 (E1): 틀림

- 판정식: `count(n_refuse_test_r1 >= 1 and n_notacc_r0 >= 1 and n_dead_r0 == 0 and n_dead_r1 == 0) >= 9`
- 셀 `ow_hello_f1_b@ow`: 판정한 시행 10회, 대입한 식 `0 >= 9` → 거짓
  - `count(n_refuse_test_r1 >= 1 and n_notacc_r0 >= 1 and n_dead_r0 == 0 and n_dead_r1 == 0)` = 0/10. 조건을 만족하지 않은 시행: ow_hello_f1_b_n1, ow_hello_f1_b_n2, ow_hello_f1_b_n3, ow_hello_f1_b_n4, ow_hello_f1_b_n5, ow_hello_f1_b_n6, ow_hello_f1_b_n7, ow_hello_f1_b_n8, ow_hello_f1_b_n9, ow_hello_f1_b_n10

### 다음 다시 걸기로 두 rank가 한 번씩 다시 연결되고 rank 0은 끊김이 끝난 뒤 2 s 안 (E2): 맞음

- 판정식: `count(n_reconn_r0 == 1 and n_reconn_r1 == 1 and 0 <= reconn_after_unmute_ms_r0 <= 2000) >= 9`
- 셀 `ow_hello_f1_b@ow`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(n_reconn_r0 == 1 and n_reconn_r1 == 1 and 0 <= reconn_after_unmute_ms_r0 <= 2000)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 12 s의 로컬 QP 오류가 투명하게 복구됨(재연결 거부 셀) (E3): 맞음

- 판정식: `count(transparent_ok == 1 and not nonempty(decl_r0)) >= 9`
- 셀 `ow_hello_f1_b@ow`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(transparent_ok == 1 and not nonempty(decl_r0))` = 10/10. 조건을 만족하지 않은 시행: 없음

### 기준 빌드: rank 0이 재연결로 센 뒤 거부의 FIN을 읽고 상대를 죽음으로 보며 장애를 FIN으로 거절함 (K4): 맞음

- 판정식: `count(n_reconn_r0 >= 1 and dead_cause_r0 == "FIN" and has(decl_r0, "no helper socket to the peer (FIN)")) >= 4`
- 셀 `ow_hello_f1_b@pcm`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(n_reconn_r0 >= 1 and dead_cause_r0 == "FIN" and has(decl_r0, "no helper socket to the peer (FIN)"))` = 5/5. 조건을 만족하지 않은 시행: 없음

### 시간 초과 시험 스위치 없이 배포된 pc가 한쪽 끊김 뒤 살아 있는 rank 0을 ECONNRESET으로 거절함(5회 중 2회 이상) (U1): 맞음

- 판정식: `count(close1_cause_r1 == "ECONNRESET" and has(decl_r1, "no helper socket to the peer (ECONNRESET)")) >= 2`
- 셀 `ow_r0in_nat_f1r1_b@pc`: 판정한 시행 5회, 대입한 식 `5 >= 2` → 참
  - `count(close1_cause_r1 == "ECONNRESET" and has(decl_r1, "no helper socket to the peer (ECONNRESET)"))` = 5/5. 조건을 만족하지 않은 시행: 없음

### 같은 경주 조건에서 새 빌드는 투명하고 아무도 상대를 죽음으로 보지 않음 (U2): 틀림

- 판정식: `count(transparent_ok == 1 and n_dead_r0 == 0 and n_dead_r1 == 0) == 5`
- 셀 `ow_r0in_nat_f1r1_b@ow`: 판정한 시행 5회, 대입한 식 `0 == 5` → 거짓
  - `count(transparent_ok == 1 and n_dead_r0 == 0 and n_dead_r1 == 0)` = 0/5. 조건을 만족하지 않은 시행: ow_r0in_nat_f1r1_b_n1, ow_r0in_nat_f1r1_b_n2, ow_r0in_nat_f1r1_b_n3, ow_r0in_nat_f1r1_b_n4, ow_r0in_nat_f1r1_b_n5

### 복구 재현 셀이 그대로 투명 (G1): 맞음

- 판정식: `per cell: count(transparent_ok == 1) == 5`
- 셀 `f1_b@ow`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음
- 셀 `f3_b@ow`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음
- 셀 `bidirf_sym_b@ow`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음
- 셀 `rc_mute8_f1_b@ow`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 양쪽 8 s 끊김에서 두 rank가 한 번씩 1.5 s 안에 다시 연결되고 죽음 줄이 없음 (G2): 틀림

- 판정식: `count(n_reconn_r0 == 1 and n_reconn_r1 == 1 and 0 <= reconn_after_unmute_ms_r0 <= 1500 and n_dead_r0 == 0 and n_dead_r1 == 0) == 5`
- 셀 `rc_mute8_f1_b@ow`: 판정한 시행 5회, 대입한 식 `0 == 5` → 거짓
  - `count(n_reconn_r0 == 1 and n_reconn_r1 == 1 and 0 <= reconn_after_unmute_ms_r0 <= 1500 and n_dead_r0 == 0 and n_dead_r1 == 0)` = 0/5. 조건을 만족하지 않은 시행: rc_mute8_f1_b_n1, rc_mute8_f1_b_n2, rc_mute8_f1_b_n3, rc_mute8_f1_b_n4, rc_mute8_f1_b_n5

### 끊김 없는 kill은 죽음 원인(FIN 또는 ECONNREFUSED)으로 거절되고 abort가 돌아옴 (G3): 맞음

- 판정식: `count((has(decl_r0, "the peer's socket shows FIN") or has(decl_r0, "the peer's socket shows ECONNREFUSED")) and teardown_r0 == "no error") == 5`
- 셀 `f4_b@ow`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count((has(decl_r0, "the peer's socket shows FIN") or has(decl_r0, "the peer's socket shows ECONNREFUSED")) and teardown_r0 == "no error")` = 5/5. 조건을 만족하지 않은 시행: 없음

### 양쪽 끊김 중 kill된 rank 1은 다시 걸기 거부로 죽음 거절되고 모름 거절이 없음 (G4): 맞음

- 판정식: `count(has(decl_r0, "RETRY_EXC and the peer's socket shows ECONNREFUSED") and not has(decl_r0, "unknown")) == 5`
- 셀 `rc_mutekill_b@ow`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(has(decl_r0, "RETRY_EXC and the peer's socket shows ECONNREFUSED") and not has(decl_r0, "unknown"))` = 5/5. 조건을 만족하지 않은 시행: 없음

### 받는 쪽 abort 해제가 그대로 (G5): 맞음

- 판정식: `count(teardown_r1 == "no error" and r1rc != 7 and teardown_ms_r1 <= 5000 and r1_outcome == "async_error_kernel_stuck") == 5`
- 셀 `f2rel_b@ow`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(teardown_r1 == "no error" and r1rc != 7 and teardown_ms_r1 <= 5000 and r1_outcome == "async_error_kernel_stuck")` = 5/5. 조건을 만족하지 않은 시행: 없음

### 상대 QP 오류 뒤 teardown 때 두 rank의 모든 QP가 RTS (G6): 맞음

- 판정식: `count(n_notrts_r0 == 0 and n_notrts_r1 == 0) == 5`
- 셀 `f3_b@ow`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(n_notrts_r0 == 0 and n_notrts_r1 == 0)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 4 KiB 지연 차이 0.40 µs 이하(대조) (L1): 맞음

- 판정식: `abs(median(lat_p50_us, "lat_ow_on_4k@ow") - median(lat_p50_us, "lat_pc_on_4k@pc")) <= 0.40`
- 셀 `lat_ow_on_4k@ow`: 판정한 시행 5회, 대입한 식 `abs(10.560 - 10.560) <= 0.40` → 참

### 256 KiB 지연 차이 0.30 µs 이하(대조) (L2): 맞음

- 판정식: `abs(median(lat_p50_us, "lat_ow_on_256k@ow") - median(lat_p50_us, "lat_pc_on_256k@pc")) <= 0.30`
- 셀 `lat_ow_on_256k@ow`: 판정한 시행 5회, 대입한 식 `abs(38.910 - 38.910) <= 0.30` → 참

## 셀별 시행 수와 따로 센 시행

| 셀 | 계획 | 실행 | 판정 | 따로 셈(사유: 시행) |
|---|--:|--:|--:|---|
| `bidirf_sym_b@ow` | 5 | 5 | 5 | 없음 |
| `f1_b@ow` | 5 | 5 | 5 | 없음 |
| `f2rel_b@ow` | 5 | 5 | 5 | 없음 |
| `f3_b@ow` | 5 | 5 | 5 | 없음 |
| `f4_b@ow` | 5 | 5 | 5 | 없음 |
| `lat_ow_on_256k@ow` | 5 | 5 | 5 | 없음 |
| `lat_ow_on_4k@ow` | 5 | 5 | 5 | 없음 |
| `lat_pc_on_256k@pc` | 5 | 5 | 5 | 없음 |
| `lat_pc_on_4k@pc` | 5 | 5 | 5 | 없음 |
| `ow_hello_f1_b@ow` | 10 | 10 | 10 | 없음 |
| `ow_hello_f1_b@pcm` | 5 | 5 | 5 | 없음 |
| `ow_kill0_b@ow` | 10 | 10 | 10 | 없음 |
| `ow_kill0_b@pcm` | 5 | 5 | 5 | 없음 |
| `ow_r0in_f1r1_b@ow` | 10 | 10 | 10 | 없음 |
| `ow_r0in_f1r1_b@pcm` | 5 | 5 | 5 | 없음 |
| `ow_r0in_nat_f1r1_b@ow` | 5 | 5 | 5 | 없음 |
| `ow_r0in_nat_f1r1_b@pc` | 5 | 5 | 5 | 없음 |
| `ow_r1in_f1_b@ow` | 10 | 10 | 10 | 없음 |
| `ow_r1in_f1_b@pcm` | 5 | 5 | 5 | 없음 |
| `rc_mute8_f1_b@ow` | 5 | 5 | 5 | 없음 |
| `rc_mutekill_b@ow` | 5 | 5 | 5 | 없음 |
