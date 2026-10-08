# gin-pair-check 채점 결과

`score.py`가 원자료(`results/20261008/`의 hold별 시행 파일)에서 만들었다. 손으로 고친 값은 없다.

- 예측 파일 sha256: `a8a4b04602b0acee8477a8682c222922d4aee1a1b41f238a9de50ff00c93c8e8`. `PREREG.txt`의 값과 같다.
- 시행 수(모든 hold): 111. 판정한 시행: 110.
- 판정식 원문은 `predictions.csv`, 열과 문법은 `EXPERIMENT.md` 3절.

## 판정 요약

| 예측 | 셀 | n | 맞은 시행(조건별) | 판정 |
|---|---|--:|---|---|
| 기존 훅의 상대 QP 오류(rank 1의 QP 4개 고장)가 투명하게 복구됨 (A1) | `f3_b@pc` | 10 | 10/10 | 맞음 |
| rank 1이 좁힌 범위를 한 번 거절하고 rank 0이 전체 재설정으로 다시 돎 (A2) | `f3_b@pc` | 10 | 10/10 | 맞음 |
| teardown 때 두 rank 모두 RTS가 아닌 QP가 없음 (A3) | `f3_b@pc` | 10 | 10/10 | 맞음 |
| rank 1의 쉬는 문맥 2 QP가 고장 난 채로 문맥 0 로컬 QP 오류가 투명하게 복구됨 (B1) | `pc_dual_f1c0_r1c2_b@pcd` | 10 | 10/10 | 맞음 |
| rank 1이 거절하고(범위 밖 1개) rank 0이 전체 재설정으로 다시 돎 (B2) | `pc_dual_f1c0_r1c2_b@pcd` | 10 | 10/10 | 맞음 |
| 응답 쪽 고장 셀에서 teardown 때 두 rank 모두 RTS가 아닌 QP가 없음 (B3) | `pc_dual_f1c0_r1c2_b@pcd` | 10 | 10/10 | 맞음 |
| 응답 쪽이 깨끗하면 투명하게 복구됨 (C1) | `pc_dual_f1c0_b@pcd` | 10 | 10/10 | 맞음 |
| 응답 쪽이 깨끗하면 두 rank 모두 문맥 0으로 좁혀지고 rank 1은 검사 뒤 수락함 (C2) | `pc_dual_f1c0_b@pcd` | 10 | 10/10 | 맞음 |
| 문맥 0이 묶인 동안 문맥 1이 돌고 1 ms를 넘는 반복이 없음 (C3) | `pc_dual_f1c0_b@pcd` | 10 | 10/10 | 맞음 |
| 에폭은 두 rank 모두 [2,0,…]이고 teardown 때 모든 QP가 RTS (C4) | `pc_dual_f1c0_b@pcd` | 10 | 10/10 | 맞음 |
| 시작 쪽 Commit 중앙값이 같은 hold의 pr 기준의 1.15배 이하 (T1) | `pc_dual_f1c0_b@pcd`, `pr_dual_f1c0_b@prd` | 10 / 5 | 752.500 <= 1.15 * 762.000 | 맞음 |
| 시작 쪽 라운드 전체 중앙값이 같은 hold의 pr 기준보다 1 000 µs 이하로 늚 (T2) | `pc_dual_f1c0_b@pcd`, `pr_dual_f1c0_b@prd` | 10 / 5 | 3256.500 - 2998.000 <= 1000 | 맞음 |
| 다른 범위의 동시 시작이 모두 복구되고 거절이 없음 (E1) | `pc_bidirf_conflict_b@pc` | 10 | 10/10 | 맞음 |
| 충돌 뒤 rank 1이 범위를 다시 정해 문맥 1 쌍만 돌고 에폭이 [2,2,0,0] (E2) | `pc_bidirf_conflict_b@pc` | 10 | 0/10 | 틀림 |
| 범위 충돌 셀에서 teardown 때 모든 QP가 RTS (E3) | `pc_bidirf_conflict_b@pc` | 10 | 10/10 | 맞음 |
| 검사를 끄면 좁혀지고 rank 1에 RTS가 아닌 QP 3개가 남음(대조) (K1) | `f3_b_nocheck@pc` | 5 | 5/5 | 맞음 |
| 응답 쪽 스위치를 끄면 off로 거절하고 전체 재설정으로 다시 돎(대조) (K2) | `pc_dual_f1c0_r1off_b@pcd` | 5 | 5/5 | 맞음 |
| pr 기준은 투명하고 좁혀짐(대조) (K3) | `pr_dual_f1c0_b@prd` | 5 | 5/5 | 맞음 |
| 복구 재현 셀이 그대로 투명 (G1) | `f1_b@pc`, `bidirf_sym_b@pc`, `mt256_f1_b@pc`, `pc_dual_f3c0_b@pcd`, `pc_dual_f1all_b@pcd` | 5 / 5 / 5 / 5 / 5 | 5/5; 5/5; 5/5; 5/5; 5/5 | 맞음 |
| 복구 재현 셀에서 teardown 때 모든 QP가 RTS (G2) | `f1_b@pc`, `bidirf_sym_b@pc`, `mt256_f1_b@pc`, `pc_dual_f3c0_b@pcd`, `pc_dual_f1all_b@pcd` | 5 / 5 / 5 / 5 / 5 | 5/5; 5/5; 5/5; 5/5; 5/5 | 맞음 |
| 상대 쪽 문맥 0만 깬 상대 QP 오류는 거절 없이 좁혀짐 (G3) | `pc_dual_f3c0_b@pcd` | 5 | 5/5 | 맞음 |
| 끊김 없는 kill은 죽음 원인으로 거절되고 abort가 돌아옴 (G4) | `f4_b@pc` | 5 | 5/5 | 맞음 |
| 받는 쪽 abort 해제가 그대로 (G5) | `f2rel_b@pc` | 5 | 5/5 | 맞음 |
| 4 KiB 지연 차이 0.40 µs 이하(대조) (L1) | `lat_pc_on_4k@pc`, `lat_pr_on_4k@pr` | 5 / 5 | abs(10.590 - 10.590) <= 0.40 | 맞음 |
| 256 KiB 지연 차이 0.30 µs 이하(대조) (L2) | `lat_pc_on_256k@pc`, `lat_pr_on_256k@pr` | 5 / 5 | abs(38.910 - 38.910) <= 0.30 | 맞음 |

## 예측별 세부

### 기존 훅의 상대 QP 오류(rank 1의 QP 4개 고장)가 투명하게 복구됨 (A1): 맞음

- 판정식: `count(transparent_ok == 1) >= 9`
- 셀 `f3_b@pc`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(transparent_ok == 1)` = 10/10. 조건을 만족하지 않은 시행: 없음

### rank 1이 좁힌 범위를 한 번 거절하고 rank 0이 전체 재설정으로 다시 돎 (A2): 맞음

- 판정식: `count(n_refused_r1 == 1 and refuse_reason_r1 == "not_rts" and not_rts_r1 == 3 and n_rerun_r0 == 1 and last_reason_r0 == "peer" and rec_qps_r0 == 4 and rec_qps_r1 == 4) >= 9`
- 셀 `f3_b@pc`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(n_refused_r1 == 1 and refuse_reason_r1 == "not_rts" and not_rts_r1 == 3 and n_rerun_r0 == 1 and last_reason_r0 == "peer" and rec_qps_r0 == 4 and rec_qps_r1 == 4)` = 10/10. 조건을 만족하지 않은 시행: 없음

### teardown 때 두 rank 모두 RTS가 아닌 QP가 없음 (A3): 맞음

- 판정식: `count(n_notrts_r0 == 0 and n_notrts_r1 == 0) == 10`
- 셀 `f3_b@pc`: 판정한 시행 10회, 대입한 식 `10 == 10` → 참
  - `count(n_notrts_r0 == 0 and n_notrts_r1 == 0)` = 10/10. 조건을 만족하지 않은 시행: 없음

### rank 1의 쉬는 문맥 2 QP가 고장 난 채로 문맥 0 로컬 QP 오류가 투명하게 복구됨 (B1): 맞음

- 판정식: `count(transparent_ok == 1) >= 9`
- 셀 `pc_dual_f1c0_r1c2_b@pcd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(transparent_ok == 1)` = 10/10. 조건을 만족하지 않은 시행: 없음

### rank 1이 거절하고(범위 밖 1개) rank 0이 전체 재설정으로 다시 돎 (B2): 맞음

- 판정식: `count(n_refused_r1 == 1 and not_rts_r1 == 1 and n_rerun_r0 == 1 and rec_qps_r0 == 4 and rec_qps_r1 == 4) >= 9`
- 셀 `pc_dual_f1c0_r1c2_b@pcd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(n_refused_r1 == 1 and not_rts_r1 == 1 and n_rerun_r0 == 1 and rec_qps_r0 == 4 and rec_qps_r1 == 4)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 응답 쪽 고장 셀에서 teardown 때 두 rank 모두 RTS가 아닌 QP가 없음 (B3): 맞음

- 판정식: `count(n_notrts_r0 == 0 and n_notrts_r1 == 0) == 10`
- 셀 `pc_dual_f1c0_r1c2_b@pcd`: 판정한 시행 10회, 대입한 식 `10 == 10` → 참
  - `count(n_notrts_r0 == 0 and n_notrts_r1 == 0)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 응답 쪽이 깨끗하면 투명하게 복구됨 (C1): 맞음

- 판정식: `count(transparent_ok == 1) >= 9`
- 셀 `pc_dual_f1c0_b@pcd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(transparent_ok == 1)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 응답 쪽이 깨끗하면 두 rank 모두 문맥 0으로 좁혀지고 rank 1은 검사 뒤 수락함 (C2): 맞음

- 판정식: `count(rec_scope_r0 == "0x1" and rec_qps_r0 == 1 and rec_scope_r1 == "0x1" and rec_qps_r1 == 1 and n_rec_r0 == 1 and n_rec_r1 == 1 and n_refused_r1 == 0 and n_checked_r1 == 1) >= 9`
- 셀 `pc_dual_f1c0_b@pcd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(rec_scope_r0 == "0x1" and rec_qps_r0 == 1 and rec_scope_r1 == "0x1" and rec_qps_r1 == 1 and n_rec_r0 == 1 and n_rec_r1 == 1 and n_refused_r1 == 0 and n_checked_r1 == 1)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 문맥 0이 묶인 동안 문맥 1이 돌고 1 ms를 넘는 반복이 없음 (C3): 맞음

- 판정식: `count(dual_c1_in_win >= 1 and 0 <= dual_c1_max_in_win_us <= 1000) >= 9`
- 셀 `pc_dual_f1c0_b@pcd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(dual_c1_in_win >= 1 and 0 <= dual_c1_max_in_win_us <= 1000)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 에폭은 두 rank 모두 [2,0,…]이고 teardown 때 모든 QP가 RTS (C4): 맞음

- 판정식: `count(ep_c0_r0 == 2 and ep_c1_r0 == 0 and ep_c0_r1 == 2 and ep_c1_r1 == 0 and n_notrts_r0 == 0 and n_notrts_r1 == 0) >= 9`
- 셀 `pc_dual_f1c0_b@pcd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(ep_c0_r0 == 2 and ep_c1_r0 == 0 and ep_c0_r1 == 2 and ep_c1_r1 == 0 and n_notrts_r0 == 0 and n_notrts_r1 == 0)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 시작 쪽 Commit 중앙값이 같은 hold의 pr 기준의 1.15배 이하 (T1): 맞음

- 판정식: `median(commit_us_r0, "pc_dual_f1c0_b@pcd") <= 1.15 * median(commit_us_r0, "pr_dual_f1c0_b@prd")`
- 셀 `pc_dual_f1c0_b@pcd`: 판정한 시행 10회, 대입한 식 `752.500 <= 1.15 * 762.000` → 참

### 시작 쪽 라운드 전체 중앙값이 같은 hold의 pr 기준보다 1 000 µs 이하로 늚 (T2): 맞음

- 판정식: `median(total_us_r0, "pc_dual_f1c0_b@pcd") - median(total_us_r0, "pr_dual_f1c0_b@prd") <= 1000`
- 셀 `pc_dual_f1c0_b@pcd`: 판정한 시행 10회, 대입한 식 `3256.500 - 2998.000 <= 1000` → 참

### 다른 범위의 동시 시작이 모두 복구되고 거절이 없음 (E1): 맞음

- 판정식: `count(transparent_ok == 1 and not nonempty(decl_r0) and not nonempty(decl_r1)) >= 9`
- 셀 `pc_bidirf_conflict_b@pc`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(transparent_ok == 1 and not nonempty(decl_r0) and not nonempty(decl_r1))` = 10/10. 조건을 만족하지 않은 시행: 없음

### 충돌 뒤 rank 1이 범위를 다시 정해 문맥 1 쌍만 돌고 에폭이 [2,2,0,0] (E2): 틀림

- 판정식: `count(conflict_r1 == 1 and init_qps_r1 == 1 and last_reason_r1 == "pair" and ep_c0_r0 == 2 and ep_c1_r0 == 2 and ep_c2_r0 == 0 and ep_c3_r0 == 0 and ep_c0_r1 == 2 and ep_c1_r1 == 2 and ep_c2_r1 == 0 and ep_c3_r1 == 0) >= 9`
- 셀 `pc_bidirf_conflict_b@pc`: 판정한 시행 10회, 대입한 식 `0 >= 9` → 거짓
  - `count(conflict_r1 == 1 and init_qps_r1 == 1 and last_reason_r1 == "pair" and ep_c0_r0 == 2 and ep_c1_r0 == 2 and ep_c2_r0 == 0 and ep_c3_r0 == 0 and ep_c0_r1 == 2 and ep_c1_r1 == 2 and ep_c2_r1 == 0 and ep_c3_r1 == 0)` = 0/10. 조건을 만족하지 않은 시행: pc_bidirf_conflict_b_n1, pc_bidirf_conflict_b_n2, pc_bidirf_conflict_b_n3, pc_bidirf_conflict_b_n4, pc_bidirf_conflict_b_n5, pc_bidirf_conflict_b_n6, pc_bidirf_conflict_b_n7, pc_bidirf_conflict_b_n8, pc_bidirf_conflict_b_n9, pc_bidirf_conflict_b_n10

### 범위 충돌 셀에서 teardown 때 모든 QP가 RTS (E3): 맞음

- 판정식: `count(n_notrts_r0 == 0 and n_notrts_r1 == 0) >= 9`
- 셀 `pc_bidirf_conflict_b@pc`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(n_notrts_r0 == 0 and n_notrts_r1 == 0)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 검사를 끄면 좁혀지고 rank 1에 RTS가 아닌 QP 3개가 남음(대조) (K1): 맞음

- 판정식: `count(transparent_ok == 1 and rec_qps_r0 == 1 and rec_qps_r1 == 1 and n_notrts_r0 == 0 and n_notrts_r1 == 3) >= 4`
- 셀 `f3_b_nocheck@pc`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(transparent_ok == 1 and rec_qps_r0 == 1 and rec_qps_r1 == 1 and n_notrts_r0 == 0 and n_notrts_r1 == 3)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 응답 쪽 스위치를 끄면 off로 거절하고 전체 재설정으로 다시 돎(대조) (K2): 맞음

- 판정식: `count(transparent_ok == 1 and n_refused_r1 == 1 and refuse_reason_r1 == "off" and n_rerun_r0 == 1 and rec_qps_r0 == 4 and rec_qps_r1 == 4) == 5`
- 셀 `pc_dual_f1c0_r1off_b@pcd`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1 and n_refused_r1 == 1 and refuse_reason_r1 == "off" and n_rerun_r0 == 1 and rec_qps_r0 == 4 and rec_qps_r1 == 4)` = 5/5. 조건을 만족하지 않은 시행: 없음

### pr 기준은 투명하고 좁혀짐(대조) (K3): 맞음

- 판정식: `count(transparent_ok == 1 and rec_qps_r0 == 1 and rec_qps_r1 == 1) == 5`
- 셀 `pr_dual_f1c0_b@prd`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1 and rec_qps_r0 == 1 and rec_qps_r1 == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 복구 재현 셀이 그대로 투명 (G1): 맞음

- 판정식: `per cell: count(transparent_ok == 1) == 5`
- 셀 `f1_b@pc`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음
- 셀 `bidirf_sym_b@pc`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음
- 셀 `mt256_f1_b@pc`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음
- 셀 `pc_dual_f3c0_b@pcd`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음
- 셀 `pc_dual_f1all_b@pcd`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 복구 재현 셀에서 teardown 때 모든 QP가 RTS (G2): 맞음

- 판정식: `per cell: count(n_notrts_r0 == 0 and n_notrts_r1 == 0) == 5`
- 셀 `f1_b@pc`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(n_notrts_r0 == 0 and n_notrts_r1 == 0)` = 5/5. 조건을 만족하지 않은 시행: 없음
- 셀 `bidirf_sym_b@pc`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(n_notrts_r0 == 0 and n_notrts_r1 == 0)` = 5/5. 조건을 만족하지 않은 시행: 없음
- 셀 `mt256_f1_b@pc`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(n_notrts_r0 == 0 and n_notrts_r1 == 0)` = 5/5. 조건을 만족하지 않은 시행: 없음
- 셀 `pc_dual_f3c0_b@pcd`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(n_notrts_r0 == 0 and n_notrts_r1 == 0)` = 5/5. 조건을 만족하지 않은 시행: 없음
- 셀 `pc_dual_f1all_b@pcd`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(n_notrts_r0 == 0 and n_notrts_r1 == 0)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 상대 쪽 문맥 0만 깬 상대 QP 오류는 거절 없이 좁혀짐 (G3): 맞음

- 판정식: `count(rec_scope_r0 == "0x1" and rec_qps_r0 == 1 and rec_qps_r1 == 1 and n_refused_r1 == 0) == 5`
- 셀 `pc_dual_f3c0_b@pcd`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(rec_scope_r0 == "0x1" and rec_qps_r0 == 1 and rec_qps_r1 == 1 and n_refused_r1 == 0)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 끊김 없는 kill은 죽음 원인으로 거절되고 abort가 돌아옴 (G4): 맞음

- 판정식: `count((has(decl_r0, "peer's socket shows FIN") or has(decl_r0, "peer's socket shows ECONNRESET")) and teardown_r0 == "no error") == 5`
- 셀 `f4_b@pc`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count((has(decl_r0, "peer's socket shows FIN") or has(decl_r0, "peer's socket shows ECONNRESET")) and teardown_r0 == "no error")` = 5/5. 조건을 만족하지 않은 시행: 없음

### 받는 쪽 abort 해제가 그대로 (G5): 맞음

- 판정식: `count(teardown_r1 == "no error" and r1rc != 7 and teardown_ms_r1 <= 5000 and r1_outcome == "async_error_kernel_stuck") == 5`
- 셀 `f2rel_b@pc`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(teardown_r1 == "no error" and r1rc != 7 and teardown_ms_r1 <= 5000 and r1_outcome == "async_error_kernel_stuck")` = 5/5. 조건을 만족하지 않은 시행: 없음

### 4 KiB 지연 차이 0.40 µs 이하(대조) (L1): 맞음

- 판정식: `abs(median(lat_p50_us, "lat_pc_on_4k@pc") - median(lat_p50_us, "lat_pr_on_4k@pr")) <= 0.40`
- 셀 `lat_pc_on_4k@pc`: 판정한 시행 5회, 대입한 식 `abs(10.590 - 10.590) <= 0.40` → 참

### 256 KiB 지연 차이 0.30 µs 이하(대조) (L2): 맞음

- 판정식: `abs(median(lat_p50_us, "lat_pc_on_256k@pc") - median(lat_p50_us, "lat_pr_on_256k@pr")) <= 0.30`
- 셀 `lat_pc_on_256k@pc`: 판정한 시행 5회, 대입한 식 `abs(38.910 - 38.910) <= 0.30` → 참

## 셀별 시행 수와 따로 센 시행

| 셀 | 계획 | 실행 | 판정 | 따로 셈(사유: 시행) |
|---|--:|--:|--:|---|
| `bidirf_sym_b@pc` | 5 | 5 | 5 | 없음 |
| `f1_b@pc` | 5 | 5 | 5 | 없음 |
| `f2rel_b@pc` | 5 | 5 | 5 | 없음 |
| `f3_b@pc` | 10 | 10 | 10 | 없음 |
| `f3_b_nocheck@pc` | 5 | 5 | 5 | 없음 |
| `f4_b@pc` | 5 | 5 | 5 | 없음 |
| `lat_pc_on_256k@pc` | 5 | 5 | 5 | 없음 |
| `lat_pc_on_4k@pc` | 5 | 5 | 5 | 없음 |
| `lat_pr_on_256k@pr` | 5 | 5 | 5 | 없음 |
| `lat_pr_on_4k@pr` | 5 | 5 | 5 | 없음 |
| `mt256_f1_b@pc` | 5 | 5 | 5 | 없음 |
| `pc_bidirf_conflict_b@pc` | 10 | 10 | 10 | 없음 |
| `pc_dual_f1all_b@pcd` | 5 | 5 | 5 | 없음 |
| `pc_dual_f1c0_b@pcd` | 10 | 11 | 10 | 드라이버 랑데부 포트 충돌: pc_dual_f1c0_b_n10 |
| `pc_dual_f1c0_r1c2_b@pcd` | 10 | 10 | 10 | 없음 |
| `pc_dual_f1c0_r1off_b@pcd` | 5 | 5 | 5 | 없음 |
| `pc_dual_f3c0_b@pcd` | 5 | 5 | 5 | 없음 |
| `pr_dual_f1c0_b@prd` | 5 | 5 | 5 | 없음 |
