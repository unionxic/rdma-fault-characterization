# gin-pair-reset 채점 결과

`score.py`가 원자료(`results/20261008/`의 hold별 시행 파일)에서 만들었다. 손으로 고친 값은 없다.

- 예측 파일 sha256: `dcb00afb48e7a3633b62f8f86491dda86c6c0449c8442f85cb749e8e305cf36c`. `PREREG.txt`의 값과 같다.
- 시행 수(모든 hold): 102. 판정한 시행: 100.
- 판정식 원문은 `predictions.csv`, 열과 문법은 `EXPERIMENT.md` 3절.

## 판정 요약

| 예측 | 셀 | n | 맞은 시행(조건별) | 판정 |
|---|---|--:|---|---|
| 두 문맥에 트래픽이 있을 때 문맥 0의 로컬 QP 오류가 투명하게 복구됨 (P1a) | `pr_dual_f1c0_b@prd` | 10 | 10/10 | 맞음 |
| 라운드가 한 번이고 두 rank 모두 문맥 0 하나로 좁혀짐 (P1b) | `pr_dual_f1c0_b@prd` | 10 | 10/10 | 맞음 |
| 문맥 1 게이트는 두 rank에서 그대로, 문맥 0은 한 번 공개 (P1c) | `pr_dual_f1c0_b@prd` | 10 | 10/10 | 맞음 |
| 문맥 0이 묶인 동안 문맥 1이 계속 돌고 1 ms를 넘는 반복이 없음 (P1d) | `pr_dual_f1c0_b@prd` | 10 | 10/10 | 맞음 |
| 문맥 0 쌍의 상대 QP 오류가 투명하게 복구됨 (P2a) | `pr_dual_f3c0_b@prd` | 10 | 10/10 | 맞음 |
| 재시도 초과 라운드도 두 rank에서 문맥 0으로 좁혀지고 문맥 1 게이트는 그대로 (P2b) | `pr_dual_f3c0_b@prd` | 10 | 10/10 | 맞음 |
| 재시도 기다림과 라운드 동안 문맥 1이 계속 돌고 1 ms를 넘는 반복이 없음 (P2c) | `pr_dual_f3c0_b@prd` | 10 | 10/10 | 맞음 |
| 시작 쪽 Commit 중앙값이 같은 hold의 전체 재설정의 절반 이하 (T1) | `pr_dual_f1c0_b@prd`, `pr_dual_f1c0_full_b@prd` | 10 / 5 | 768.000 <= 0.5 * 3315.000 | 맞음 |
| 시작 쪽 라운드 전체 중앙값이 같은 hold의 전체 재설정의 0.6 이하 (T2) | `pr_dual_f1c0_b@prd`, `pr_dual_f1c0_full_b@prd` | 10 / 5 | 3013.000 <= 0.6 * 11379.000 | 맞음 |
| rank 0의 모든 문맥 QP가 고장 나도 두 문맥 모두 투명하게 복구됨 (B1a) | `pr_dual_f1all_b@prd` | 10 | 10/10 | 맞음 |
| 모든 문맥 고장은 전체 재설정 한 번으로 돌아감 (B1b) | `pr_dual_f1all_b@prd` | 10 | 10/10 | 맞음 |
| 두 rank가 다른 범위로 동시에 시작해도 둘 다 복구되고 거절이 없음 (B2a) | `pr_bidirf_conflict_b@pr` | 10 | 10/10 | 맞음 |
| 높은 rank가 충돌을 한 번 보고, 문맥 0 라운드에 응답한 뒤 자기 장애를 전체 재설정으로 돔 (B2b) | `pr_bidirf_conflict_b@pr` | 10 | 10/10 | 맞음 |
| 스위치를 끄면 전체 재설정(QP 4개씩)이고 투명함(대조) (C1a) | `pr_dual_f1c0_full_b@prd` | 5 | 5/5 | 맞음 |
| 전체 재설정에서는 문맥 1도 묶여 1 ms 이상인 반복이 나옴(대조) (C1b) | `pr_dual_f1c0_full_b@prd` | 5 | 5/5 | 맞음 |
| 장애 없는 두 문맥 모드는 투명하고 라운드가 없으며 문맥 1의 최장 반복이 1 ms 이하(대조) (C2) | `pr_dual_none_b@prd` | 5 | 5/5 | 맞음 |
| 주요 복구 셀 네 개가 그대로 투명 (G1) | `f1_b@pr`, `f3_b@pr`, `bidirf_sym_b@pr`, `mt256_f1_b@pr` | 5 / 5 / 5 / 5 | 5/5; 5/5; 5/5; 5/5 | 맞음 |
| 기존 훅이 그 rank의 QP를 모두 고장 내는 셀은 두 rank 모두 전체 재설정 (G2) | `f1_b@pr`, `mt256_f1_b@pr`, `bidirf_sym_b@pr` | 5 / 5 / 5 | 5/5; 5/5; 5/5 | 맞음 |
| 기존 상대 QP 오류 셀이 문맥 0으로 좁혀짐 (G3) | `f3_b@pr` | 5 | 5/5 | 맞음 |
| 끊김 없는 kill은 죽음 원인으로 거절되고 abort가 돌아옴 (G4) | `f4_b@pr` | 5 | 5/5 | 맞음 |
| 받는 쪽 abort 해제가 그대로 (G5) | `f2rel_b@pr` | 5 | 5/5 | 맞음 |
| 4 KiB 지연 차이 0.40 µs 이하(대조) (L1) | `lat_pr_on_4k@pr`, `lat_rc_on_4k@rc` | 5 / 5 | abs(10.560 - 10.560) <= 0.40 | 맞음 |
| 256 KiB 지연 차이 0.30 µs 이하(대조) (L2) | `lat_pr_on_256k@pr`, `lat_rc_on_256k@rc` | 5 / 5 | abs(38.910 - 38.910) <= 0.30 | 맞음 |

## 예측별 세부

### 두 문맥에 트래픽이 있을 때 문맥 0의 로컬 QP 오류가 투명하게 복구됨 (P1a): 맞음

- 판정식: `count(transparent_ok == 1) >= 9`
- 셀 `pr_dual_f1c0_b@prd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(transparent_ok == 1)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 라운드가 한 번이고 두 rank 모두 문맥 0 하나로 좁혀짐 (P1b): 맞음

- 판정식: `count(rec_scope_r0 == "0x1" and rec_qps_r0 == 1 and rec_scope_r1 == "0x1" and rec_qps_r1 == 1 and n_rec_r0 == 1 and n_rec_r1 == 1) >= 9`
- 셀 `pr_dual_f1c0_b@prd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(rec_scope_r0 == "0x1" and rec_qps_r0 == 1 and rec_scope_r1 == "0x1" and rec_qps_r1 == 1 and n_rec_r0 == 1 and n_rec_r1 == 1)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 문맥 1 게이트는 두 rank에서 그대로, 문맥 0은 한 번 공개 (P1c): 맞음

- 판정식: `count(ep_c0_r0 == 2 and ep_c1_r0 == 0 and ep_c0_r1 == 2 and ep_c1_r1 == 0) >= 9`
- 셀 `pr_dual_f1c0_b@prd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(ep_c0_r0 == 2 and ep_c1_r0 == 0 and ep_c0_r1 == 2 and ep_c1_r1 == 0)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 문맥 0이 묶인 동안 문맥 1이 계속 돌고 1 ms를 넘는 반복이 없음 (P1d): 맞음

- 판정식: `count(dual_c1_in_win >= 1 and 0 <= dual_c1_max_in_win_us <= 1000) >= 9`
- 셀 `pr_dual_f1c0_b@prd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(dual_c1_in_win >= 1 and 0 <= dual_c1_max_in_win_us <= 1000)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 문맥 0 쌍의 상대 QP 오류가 투명하게 복구됨 (P2a): 맞음

- 판정식: `count(transparent_ok == 1) >= 9`
- 셀 `pr_dual_f3c0_b@prd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(transparent_ok == 1)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 재시도 초과 라운드도 두 rank에서 문맥 0으로 좁혀지고 문맥 1 게이트는 그대로 (P2b): 맞음

- 판정식: `count(has(q4_class_r0, "RETRY_EXC") and rec_scope_r0 == "0x1" and rec_qps_r0 == 1 and rec_scope_r1 == "0x1" and rec_qps_r1 == 1 and ep_c1_r0 == 0 and ep_c1_r1 == 0) >= 9`
- 셀 `pr_dual_f3c0_b@prd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(has(q4_class_r0, "RETRY_EXC") and rec_scope_r0 == "0x1" and rec_qps_r0 == 1 and rec_scope_r1 == "0x1" and rec_qps_r1 == 1 and ep_c1_r0 == 0 and ep_c1_r1 == 0)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 재시도 기다림과 라운드 동안 문맥 1이 계속 돌고 1 ms를 넘는 반복이 없음 (P2c): 맞음

- 판정식: `count(dual_c1_in_win >= 1 and 0 <= dual_c1_max_in_win_us <= 1000) >= 9`
- 셀 `pr_dual_f3c0_b@prd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(dual_c1_in_win >= 1 and 0 <= dual_c1_max_in_win_us <= 1000)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 시작 쪽 Commit 중앙값이 같은 hold의 전체 재설정의 절반 이하 (T1): 맞음

- 판정식: `median(commit_us_r0, "pr_dual_f1c0_b@prd") <= 0.5 * median(commit_us_r0, "pr_dual_f1c0_full_b@prd")`
- 셀 `pr_dual_f1c0_b@prd`: 판정한 시행 10회, 대입한 식 `768.000 <= 0.5 * 3315.000` → 참

### 시작 쪽 라운드 전체 중앙값이 같은 hold의 전체 재설정의 0.6 이하 (T2): 맞음

- 판정식: `median(total_us_r0, "pr_dual_f1c0_b@prd") <= 0.6 * median(total_us_r0, "pr_dual_f1c0_full_b@prd")`
- 셀 `pr_dual_f1c0_b@prd`: 판정한 시행 10회, 대입한 식 `3013.000 <= 0.6 * 11379.000` → 참

### rank 0의 모든 문맥 QP가 고장 나도 두 문맥 모두 투명하게 복구됨 (B1a): 맞음

- 판정식: `count(transparent_ok == 1) >= 9`
- 셀 `pr_dual_f1all_b@prd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(transparent_ok == 1)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 모든 문맥 고장은 전체 재설정 한 번으로 돌아감 (B1b): 맞음

- 판정식: `count(rec_init_r0 == 1 and rec_qps_r0 == 4 and rec_qps_r1 == 4 and (scope_reason_r0 == "qp_state" or scope_reason_r0 == "queued")) >= 9`
- 셀 `pr_dual_f1all_b@prd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(rec_init_r0 == 1 and rec_qps_r0 == 4 and rec_qps_r1 == 4 and (scope_reason_r0 == "qp_state" or scope_reason_r0 == "queued"))` = 10/10. 조건을 만족하지 않은 시행: 없음

### 두 rank가 다른 범위로 동시에 시작해도 둘 다 복구되고 거절이 없음 (B2a): 맞음

- 판정식: `count(transparent_ok == 1 and not nonempty(decl_r0) and not nonempty(decl_r1)) >= 9`
- 셀 `pr_bidirf_conflict_b@pr`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(transparent_ok == 1 and not nonempty(decl_r0) and not nonempty(decl_r1))` = 10/10. 조건을 만족하지 않은 시행: 없음

### 높은 rank가 충돌을 한 번 보고, 문맥 0 라운드에 응답한 뒤 자기 장애를 전체 재설정으로 돔 (B2b): 맞음

- 판정식: `count(conflict_r1 == 1 and rec_init_r0 == 1 and rec_resp_r0 == 1 and rec_resp_r1 == 1 and rec_init_r1 == 1 and init_qps_r1 == 4) >= 9`
- 셀 `pr_bidirf_conflict_b@pr`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(conflict_r1 == 1 and rec_init_r0 == 1 and rec_resp_r0 == 1 and rec_resp_r1 == 1 and rec_init_r1 == 1 and init_qps_r1 == 4)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 스위치를 끄면 전체 재설정(QP 4개씩)이고 투명함(대조) (C1a): 맞음

- 판정식: `count(transparent_ok == 1 and pr_mode_r0 == 0 and rec_qps_r0 == 4 and rec_qps_r1 == 4) == 5`
- 셀 `pr_dual_f1c0_full_b@prd`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1 and pr_mode_r0 == 0 and rec_qps_r0 == 4 and rec_qps_r1 == 4)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 전체 재설정에서는 문맥 1도 묶여 1 ms 이상인 반복이 나옴(대조) (C1b): 맞음

- 판정식: `count(dual_c1_max_in_win_us >= 1000) >= 4`
- 셀 `pr_dual_f1c0_full_b@prd`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(dual_c1_max_in_win_us >= 1000)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 장애 없는 두 문맥 모드는 투명하고 라운드가 없으며 문맥 1의 최장 반복이 1 ms 이하(대조) (C2): 맞음

- 판정식: `count(transparent_ok == 1 and n_rec_r0 == 0 and n_rec_r1 == 0 and 0 <= dual_c1_max_us <= 1000) == 5`
- 셀 `pr_dual_none_b@prd`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1 and n_rec_r0 == 0 and n_rec_r1 == 0 and 0 <= dual_c1_max_us <= 1000)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 주요 복구 셀 네 개가 그대로 투명 (G1): 맞음

- 판정식: `per cell: count(transparent_ok == 1) == 5`
- 셀 `f1_b@pr`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음
- 셀 `f3_b@pr`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음
- 셀 `bidirf_sym_b@pr`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음
- 셀 `mt256_f1_b@pr`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 기존 훅이 그 rank의 QP를 모두 고장 내는 셀은 두 rank 모두 전체 재설정 (G2): 맞음

- 판정식: `per cell: count(rec_qps_r0 == 4 and rec_qps_r1 == 4) == 5`
- 셀 `f1_b@pr`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(rec_qps_r0 == 4 and rec_qps_r1 == 4)` = 5/5. 조건을 만족하지 않은 시행: 없음
- 셀 `mt256_f1_b@pr`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(rec_qps_r0 == 4 and rec_qps_r1 == 4)` = 5/5. 조건을 만족하지 않은 시행: 없음
- 셀 `bidirf_sym_b@pr`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(rec_qps_r0 == 4 and rec_qps_r1 == 4)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 기존 상대 QP 오류 셀이 문맥 0으로 좁혀짐 (G3): 맞음

- 판정식: `count(rec_scope_r0 == "0x1" and rec_qps_r0 == 1 and rec_qps_r1 == 1) == 5`
- 셀 `f3_b@pr`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(rec_scope_r0 == "0x1" and rec_qps_r0 == 1 and rec_qps_r1 == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 끊김 없는 kill은 죽음 원인으로 거절되고 abort가 돌아옴 (G4): 맞음

- 판정식: `count((has(decl_r0, "peer's socket shows FIN") or has(decl_r0, "peer's socket shows ECONNRESET")) and teardown_r0 == "no error") == 5`
- 셀 `f4_b@pr`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count((has(decl_r0, "peer's socket shows FIN") or has(decl_r0, "peer's socket shows ECONNRESET")) and teardown_r0 == "no error")` = 5/5. 조건을 만족하지 않은 시행: 없음

### 받는 쪽 abort 해제가 그대로 (G5): 맞음

- 판정식: `count(teardown_r1 == "no error" and r1rc != 7 and teardown_ms_r1 <= 5000 and r1_outcome == "async_error_kernel_stuck") == 5`
- 셀 `f2rel_b@pr`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(teardown_r1 == "no error" and r1rc != 7 and teardown_ms_r1 <= 5000 and r1_outcome == "async_error_kernel_stuck")` = 5/5. 조건을 만족하지 않은 시행: 없음

### 4 KiB 지연 차이 0.40 µs 이하(대조) (L1): 맞음

- 판정식: `abs(median(lat_p50_us, "lat_pr_on_4k@pr") - median(lat_p50_us, "lat_rc_on_4k@rc")) <= 0.40`
- 셀 `lat_pr_on_4k@pr`: 판정한 시행 5회, 대입한 식 `abs(10.560 - 10.560) <= 0.40` → 참

### 256 KiB 지연 차이 0.30 µs 이하(대조) (L2): 맞음

- 판정식: `abs(median(lat_p50_us, "lat_pr_on_256k@pr") - median(lat_p50_us, "lat_rc_on_256k@rc")) <= 0.30`
- 셀 `lat_pr_on_256k@pr`: 판정한 시행 5회, 대입한 식 `abs(38.910 - 38.910) <= 0.30` → 참

## 셀별 시행 수와 따로 센 시행

| 셀 | 계획 | 실행 | 판정 | 따로 셈(사유: 시행) |
|---|--:|--:|--:|---|
| `bidirf_sym_b@pr` | 5 | 6 | 5 | 드라이버 랑데부 포트 충돌: bidirf_sym_b_n4 |
| `f1_b@pr` | 5 | 5 | 5 | 없음 |
| `f2rel_b@pr` | 5 | 5 | 5 | 없음 |
| `f3_b@pr` | 5 | 5 | 5 | 없음 |
| `f4_b@pr` | 5 | 5 | 5 | 없음 |
| `lat_pr_on_256k@pr` | 5 | 5 | 5 | 없음 |
| `lat_pr_on_4k@pr` | 5 | 5 | 5 | 없음 |
| `lat_rc_on_256k@rc` | 5 | 5 | 5 | 없음 |
| `lat_rc_on_4k@rc` | 5 | 5 | 5 | 없음 |
| `mt256_f1_b@pr` | 5 | 5 | 5 | 없음 |
| `pr_bidirf_conflict_b@pr` | 10 | 11 | 10 | 조건 미적용(rank 1의 장애가 rank 0의 멈춤 안에 오지 않음): pr_bidirf_conflict_b_n10 |
| `pr_dual_f1all_b@prd` | 10 | 10 | 10 | 없음 |
| `pr_dual_f1c0_b@prd` | 10 | 10 | 10 | 없음 |
| `pr_dual_f1c0_full_b@prd` | 5 | 5 | 5 | 없음 |
| `pr_dual_f3c0_b@prd` | 10 | 10 | 10 | 없음 |
| `pr_dual_none_b@prd` | 5 | 5 | 5 | 없음 |
