# gin-handoff 채점 결과

`score.py`가 원자료(`results/20261009/`의 빌드별 시행 파일)에서 만들었다. 손으로 고친 값은 없다.

- 예측 파일 sha256: `04ac4a66cb4c2ea64bafb9a412d49f0dbd3fff5d26c36fafeecb361ded88799a`. `PREREG.txt`의 값과 같다.
- 시행 수(모든 hold): 116. 판정한 시행: 115.
- 판정식 원문은 `predictions.csv`, 열과 문법은 `EXPERIMENT.md` 3절.

## 판정 요약

| 예측 | 셀 | n | 맞은 시행(조건별) | 판정 |
|---|---|--:|---|---|
| 죽은 rank를 뺀 중단 shrink가 1-rank 통신기를 돌려주고, 그 allreduce가 맞고, 새 통신기에 비동기 오류가 없음 (S1) | `hd_shrink_b@hf` | 10 | 10/10 | 맞음 |
| 넘김 줄이 rank 1만 적고, 유지 줄이 없으며, 부모는 shrink 뒤에도 GIN 오류를 그대로 보고함 (S2) | `hd_shrink_b@hf` | 10 | 10/10 | 맞음 |
| shrink가 500 ms 안에 돌아오고 새 통신기 해제와 부모 abort가 오류 없이 끝남 (S3) | `hd_shrink_b@hf` | 10 | 10/10 | 맞음 |
| 대조(gin-harden 라이브러리): shrink가 부모의 GIN 오류로 바로 실패함 (S4) | `hd_shrink_b@hd` | 5 | 5/5 | 맞음 |
| 대조(스위치 끔): shrink가 부모의 GIN 오류로 실패하고 유지 줄이 스위치를 사유로 적음 (S5) | `hf_shrinkoff_b@hf` | 5 | 5/5 | 맞음 |
| 운영 빌드도 같은 shrink를 넘기고, 넘김 줄은 WARN에 보이지 않음 (S6) | `hd_shrink_b@hfp` | 5 | 5/5 | 맞음 |
| 상대를 적지 않은 GIN 오류(감시가 드러낸 오류)가 있으면 순정 판정을 유지함 (S7) | `hf_hog_f1_b@hf` | 5 | 5/5 | 맞음 |
| 대조(스위치 끔): devComm을 먼저 없앤 응용은 순정 확인으로도 1-rank 통신기를 얻음 (S8) | `hf_shrinkdc_b@hf` | 5 | 5/5 | 맞음 |
| 대조: 두 커널 사이에 gin-harden의 호출(커널 적재, 할당, 스트림)이 있으면 pilot의 실패가 재현됨 (G1) | `hf_hog_f1_b@hf` | 5 | 5/5 | 맞음 |
| 그 순서에서는 GPU 채우기 커널이 GIN 커널 옆에서 전혀 시작하지 못하고 새 스트림 복사도 하나도 200 ms 안에 끝나지 않음 (G2) | `hf_hog_f1_b@hf` | 5 | 5/5 | 맞음 |
| 그 순서에서는 격자를 블록 하나 줄여도 시작하지 못하고 pilot의 실패가 재현됨 (G3) | `hf_hogslack_f1_b@hf` | 5 | 5/5 | 맞음 |
| 두 커널 사이에 아무것도 없으면 가득 채우는 격자도 시작하고 복사가 끝나며 투명하게 복구됨 (G4) | `hf_hogpre_f1_b@hf` | 5 | 5/5 | 맞음 |
| 두 커널 사이에 아무것도 없고 격자가 블록 하나 작으면 모든 블록이 시작하고 투명하게 복구됨 (G5) | `hf_hogpreslack_f1_b@hf` | 5 | 5/5 | 맞음 |
| 복구 재현 셀이 그대로 투명 (R1) | `f1_b@hf`, `f3_b@hf`, `bidirf_sym_b@hf` | 5 / 5 / 5 | 5/5; 5/5; 5/5 | 맞음 |
| 끊김 없는 kill이 2 s 안에 죽음 원인으로 거절되고 abort가 돌아옴 (R2) | `f4_b@hf` | 5 | 5/5 | 맞음 |
| 원격 접근 오류를 rank 0이 거절하고, 받는 쪽 대기가 오류로 풀리며 abort가 5 s 안에 돌아옴 (R3) | `f2rel_b@hf` | 5 | 5/5 | 맞음 |
| 받기만 하는 rank가 죽은 상대를 2 s 안에 죽음으로 보고 대기와 비동기 오류로 드러내고 abort가 돌아옴 (R4) | `hd_rxdeath_b@hf` | 5 | 5/5 | 맞음 |
| 운영 빌드가 kill된 상대를 2 s 안에 죽음으로 거절하고 abort가 돌아옴 (R5) | `hdp_kill_b@hfp` | 5 | 5/5 | 맞음 |
| 통계 API가 두 rank에서 라운드 1, 복구 1, 거절 0을 셈 (R6) | `f1_b@hf` | 5 | 5/5 | 맞음 |
| kill 뒤 통계 API가 죽음 판정 1, 거절 1을 셈 (R7) | `f4_b@hf` | 5 | 5/5 | 맞음 |
| 4 KiB 지연: 이 실험의 운영 빌드와 gin-harden 운영 빌드 차이 0.40 µs 이하 (P1) | `lat_4k@hfp`, `lat_4k@hdp` | 5 / 5 | abs(10.690 - 10.690) <= 0.40 | 맞음 |
| 256 KiB 지연: 같은 두 빌드 차이 0.30 µs 이하 (P2) | `lat_256k@hfp`, `lat_256k@hdp` | 5 / 5 | abs(38.910 - 38.880) <= 0.30 | 맞음 |
| 4 KiB 지연: 이 실험의 운영 빌드와 gin-harden 연구 빌드 차이 0.40 µs 이하 (P3) | `lat_4k@hfp`, `lat_4k@hd` | 5 / 5 | abs(10.690 - 10.690) <= 0.40 | 맞음 |
| 256 KiB 지연: 같은 두 빌드 차이 0.30 µs 이하 (P4) | `lat_256k@hfp`, `lat_256k@hd` | 5 / 5 | abs(38.910 - 38.880) <= 0.30 | 맞음 |

## 예측별 세부

### 죽은 rank를 뺀 중단 shrink가 1-rank 통신기를 돌려주고, 그 allreduce가 맞고, 새 통신기에 비동기 오류가 없음 (S1): 맞음

- 판정식: `count(ho_kernel_done_before_shrink == 1 and ho_shrink_rc == "no error" and ho_newcomm == 1 and ho_newcomm_nranks == 1 and ho_check_ok == 1 and ho_newcomm_async == "no error") >= 9`
- 셀 `hd_shrink_b@hf`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(ho_kernel_done_before_shrink == 1 and ho_shrink_rc == "no error" and ho_newcomm == 1 and ho_newcomm_nranks == 1 and ho_check_ok == 1 and ho_newcomm_async == "no error")` = 10/10. 조건을 만족하지 않은 시행: 없음

### 넘김 줄이 rank 1만 적고, 유지 줄이 없으며, 부모는 shrink 뒤에도 GIN 오류를 그대로 보고함 (S2): 맞음

- 판정식: `count(n_hoff_ok_r0 == 1 and hoff_ranks_r0 == 1 and n_hoff_keep_r0 == 0 and ho_parent_async_after == "remote process exited or there was a network error") >= 9`
- 셀 `hd_shrink_b@hf`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(n_hoff_ok_r0 == 1 and hoff_ranks_r0 == 1 and n_hoff_keep_r0 == 0 and ho_parent_async_after == "remote process exited or there was a network error")` = 10/10. 조건을 만족하지 않은 시행: 없음

### shrink가 500 ms 안에 돌아오고 새 통신기 해제와 부모 abort가 오류 없이 끝남 (S3): 맞음

- 판정식: `count(0 <= ho_shrink_ms < 500 and ho_newcomm_destroy_rc == "no error" and teardown_r0 == "no error") >= 9`
- 셀 `hd_shrink_b@hf`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(0 <= ho_shrink_ms < 500 and ho_newcomm_destroy_rc == "no error" and teardown_r0 == "no error")` = 10/10. 조건을 만족하지 않은 시행: 없음

### 대조(gin-harden 라이브러리): shrink가 부모의 GIN 오류로 바로 실패함 (S4): 맞음

- 판정식: `count(ho_shrink_rc == "remote process exited or there was a network error" and ho_newcomm == 0 and ho_shrink_ms < 100) >= 4`
- 셀 `hd_shrink_b@hd`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(ho_shrink_rc == "remote process exited or there was a network error" and ho_newcomm == 0 and ho_shrink_ms < 100)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 대조(스위치 끔): shrink가 부모의 GIN 오류로 실패하고 유지 줄이 스위치를 사유로 적음 (S5): 맞음

- 판정식: `count(ho_shrink_rc == "remote process exited or there was a network error" and ho_newcomm == 0 and n_hoff_keep_r0 == 1 and has(hoff_why_r0, "NCCL_GIN_SHRINK_HANDOFF=0") and n_hoff_ok_r0 == 0) >= 4`
- 셀 `hf_shrinkoff_b@hf`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(ho_shrink_rc == "remote process exited or there was a network error" and ho_newcomm == 0 and n_hoff_keep_r0 == 1 and has(hoff_why_r0, "NCCL_GIN_SHRINK_HANDOFF=0") and n_hoff_ok_r0 == 0)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 운영 빌드도 같은 shrink를 넘기고, 넘김 줄은 WARN에 보이지 않음 (S6): 맞음

- 판정식: `count(ho_shrink_rc == "no error" and ho_newcomm_nranks == 1 and ho_check_ok == 1 and n_hoff_ok_r0 == 0 and n_hoff_keep_r0 == 0) >= 4`
- 셀 `hd_shrink_b@hfp`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(ho_shrink_rc == "no error" and ho_newcomm_nranks == 1 and ho_check_ok == 1 and n_hoff_ok_r0 == 0 and n_hoff_keep_r0 == 0)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 상대를 적지 않은 GIN 오류(감시가 드러낸 오류)가 있으면 순정 판정을 유지함 (S7): 맞음

- 판정식: `count(n_surface_r0 >= 1 and ho_shrink_rc == "remote process exited or there was a network error" and ho_newcomm == 0 and has(hoff_why_r0, "without a peer")) >= 4`
- 셀 `hf_hog_f1_b@hf`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(n_surface_r0 >= 1 and ho_shrink_rc == "remote process exited or there was a network error" and ho_newcomm == 0 and has(hoff_why_r0, "without a peer"))` = 5/5. 조건을 만족하지 않은 시행: 없음

### 대조(스위치 끔): devComm을 먼저 없앤 응용은 순정 확인으로도 1-rank 통신기를 얻음 (S8): 맞음

- 판정식: `count(ho_devcomm_destroy_rc == "no error" and ho_shrink_rc == "no error" and ho_newcomm_nranks == 1 and ho_check_ok == 1 and n_hoff_ok_r0 == 0 and n_hoff_keep_r0 == 0) >= 4`
- 셀 `hf_shrinkdc_b@hf`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(ho_devcomm_destroy_rc == "no error" and ho_shrink_rc == "no error" and ho_newcomm_nranks == 1 and ho_check_ok == 1 and n_hoff_ok_r0 == 0 and n_hoff_keep_r0 == 0)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 대조: 두 커널 사이에 gin-harden의 호출(커널 적재, 할당, 스트림)이 있으면 pilot의 실패가 재현됨 (G1): 맞음

- 판정식: `count(hog_launch_err_r0 == "cudaSuccess" and hog_prealloc_r0 == 0 and n_copyto_r0 >= 1 and rec_init_r0 == 0 and transparent_ok == 0) >= 4`
- 셀 `hf_hog_f1_b@hf`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(hog_launch_err_r0 == "cudaSuccess" and hog_prealloc_r0 == 0 and n_copyto_r0 >= 1 and rec_init_r0 == 0 and transparent_ok == 0)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 그 순서에서는 GPU 채우기 커널이 GIN 커널 옆에서 전혀 시작하지 못하고 새 스트림 복사도 하나도 200 ms 안에 끝나지 않음 (G2): 맞음

- 판정식: `count(hog_started_probe_r0 == 0 and hog_started_probe_r1 == 0 and probe_done_200ms_r0 == 0 and probe_done_200ms_r1 == 0 and probe_done_end_r0 == probe_n_r0 and probe_done_end_r1 == probe_n_r1) >= 4`
- 셀 `hf_hog_f1_b@hf`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(hog_started_probe_r0 == 0 and hog_started_probe_r1 == 0 and probe_done_200ms_r0 == 0 and probe_done_200ms_r1 == 0 and probe_done_end_r0 == probe_n_r0 and probe_done_end_r1 == probe_n_r1)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 그 순서에서는 격자를 블록 하나 줄여도 시작하지 못하고 pilot의 실패가 재현됨 (G3): 맞음

- 판정식: `count(hog_slack_r0 == 1 and hog_started_probe_r0 == 0 and hog_started_probe_r1 == 0 and n_copyto_r0 >= 1 and rec_init_r0 == 0) >= 4`
- 셀 `hf_hogslack_f1_b@hf`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(hog_slack_r0 == 1 and hog_started_probe_r0 == 0 and hog_started_probe_r1 == 0 and n_copyto_r0 >= 1 and rec_init_r0 == 0)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 두 커널 사이에 아무것도 없으면 가득 채우는 격자도 시작하고 복사가 끝나며 투명하게 복구됨 (G4): 맞음

- 판정식: `count(hog_prealloc_r0 == 1 and hog_started_probe_r0 >= hog_blocks_r0 - 1 and hog_started_probe_r1 >= hog_blocks_r1 - 1 and probe_done_200ms_r0 == probe_n_r0 and probe_done_200ms_r1 == probe_n_r1 and rec_init_r0 == 1 and transparent_ok == 1 and rs_copy_timeouts_r0 == 0 and rs_copy_timeouts_r1 == 0) >= 4`
- 셀 `hf_hogpre_f1_b@hf`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(hog_prealloc_r0 == 1 and hog_started_probe_r0 >= hog_blocks_r0 - 1 and hog_started_probe_r1 >= hog_blocks_r1 - 1 and probe_done_200ms_r0 == probe_n_r0 and probe_done_200ms_r1 == probe_n_r1 and rec_init_r0 == 1 and transparent_ok == 1 and rs_copy_timeouts_r0 == 0 and rs_copy_timeouts_r1 == 0)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 두 커널 사이에 아무것도 없고 격자가 블록 하나 작으면 모든 블록이 시작하고 투명하게 복구됨 (G5): 맞음

- 판정식: `count(hog_started_probe_r0 == hog_blocks_r0 and hog_started_probe_r1 == hog_blocks_r1 and probe_done_200ms_r0 == probe_n_r0 and probe_done_200ms_r1 == probe_n_r1 and rec_init_r0 == 1 and transparent_ok == 1 and rs_copy_timeouts_r0 == 0 and rs_copy_timeouts_r1 == 0) >= 4`
- 셀 `hf_hogpreslack_f1_b@hf`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(hog_started_probe_r0 == hog_blocks_r0 and hog_started_probe_r1 == hog_blocks_r1 and probe_done_200ms_r0 == probe_n_r0 and probe_done_200ms_r1 == probe_n_r1 and rec_init_r0 == 1 and transparent_ok == 1 and rs_copy_timeouts_r0 == 0 and rs_copy_timeouts_r1 == 0)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 복구 재현 셀이 그대로 투명 (R1): 맞음

- 판정식: `per cell: count(transparent_ok == 1) == 5`
- 셀 `f1_b@hf`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음
- 셀 `f3_b@hf`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음
- 셀 `bidirf_sym_b@hf`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 끊김 없는 kill이 2 s 안에 죽음 원인으로 거절되고 abort가 돌아옴 (R2): 맞음

- 판정식: `count((has(decl_r0, "the peer's socket shows FIN") or has(decl_r0, "the peer's socket shows ECONNREFUSED")) and teardown_r0 == "no error" and 0 <= decl_after_kill_ms_r0 <= 2000) == 5`
- 셀 `f4_b@hf`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count((has(decl_r0, "the peer's socket shows FIN") or has(decl_r0, "the peer's socket shows ECONNREFUSED")) and teardown_r0 == "no error" and 0 <= decl_after_kill_ms_r0 <= 2000)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 원격 접근 오류를 rank 0이 거절하고, 받는 쪽 대기가 오류로 풀리며 abort가 5 s 안에 돌아옴 (R3): 맞음

- 판정식: `count(has(decl_r0, "REM_ACCESS is not recoverable") and r1_outcome == "device_error" and rx_rc == "remote process exited or there was a network error" and rx_phantom_r1 == 0 and teardown_r1 == "no error" and teardown_ms_r1 <= 5000) == 5`
- 셀 `f2rel_b@hf`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(has(decl_r0, "REM_ACCESS is not recoverable") and r1_outcome == "device_error" and rx_rc == "remote process exited or there was a network error" and rx_phantom_r1 == 0 and teardown_r1 == "no error" and teardown_ms_r1 <= 5000)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 받기만 하는 rank가 죽은 상대를 2 s 안에 죽음으로 보고 대기와 비동기 오류로 드러내고 abort가 돌아옴 (R4): 맞음

- 판정식: `count(n_judged_r1 >= 1 and rx_rc == "remote process exited or there was a network error" and 0 <= release_after_kill_ms_r1 <= 2000 and 0 <= async_after_kill_ms_r1 <= 2000 and teardown_r1 == "no error") >= 4`
- 셀 `hd_rxdeath_b@hf`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(n_judged_r1 >= 1 and rx_rc == "remote process exited or there was a network error" and 0 <= release_after_kill_ms_r1 <= 2000 and 0 <= async_after_kill_ms_r1 <= 2000 and teardown_r1 == "no error")` = 5/5. 조건을 만족하지 않은 시행: 없음

### 운영 빌드가 kill된 상대를 2 s 안에 죽음으로 거절하고 abort가 돌아옴 (R5): 맞음

- 판정식: `count(has(decl_r0, "the peer's socket shows") and teardown_r0 == "no error" and rs_deaths_r0 == 1 and 0 <= decl_after_kill_ms_r0 <= 2000) == 5`
- 셀 `hdp_kill_b@hfp`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(has(decl_r0, "the peer's socket shows") and teardown_r0 == "no error" and rs_deaths_r0 == 1 and 0 <= decl_after_kill_ms_r0 <= 2000)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 통계 API가 두 rank에서 라운드 1, 복구 1, 거절 0을 셈 (R6): 맞음

- 판정식: `count(rs_api_r0 == 1 and rs_rounds_r0 == 1 and rs_recovered_r0 == 1 and rs_declined_r0 == 0 and rs_api_r1 == 1 and rs_rounds_r1 == 1 and rs_recovered_r1 == 1) == 5`
- 셀 `f1_b@hf`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(rs_api_r0 == 1 and rs_rounds_r0 == 1 and rs_recovered_r0 == 1 and rs_declined_r0 == 0 and rs_api_r1 == 1 and rs_rounds_r1 == 1 and rs_recovered_r1 == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음

### kill 뒤 통계 API가 죽음 판정 1, 거절 1을 셈 (R7): 맞음

- 판정식: `count(rs_deaths_r0 == 1 and rs_declined_r0 == 1) == 5`
- 셀 `f4_b@hf`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(rs_deaths_r0 == 1 and rs_declined_r0 == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 4 KiB 지연: 이 실험의 운영 빌드와 gin-harden 운영 빌드 차이 0.40 µs 이하 (P1): 맞음

- 판정식: `abs(median(lat_p50_us, "lat_4k@hfp") - median(lat_p50_us, "lat_4k@hdp")) <= 0.40`
- 셀 `lat_4k@hfp`: 판정한 시행 5회, 대입한 식 `abs(10.690 - 10.690) <= 0.40` → 참

### 256 KiB 지연: 같은 두 빌드 차이 0.30 µs 이하 (P2): 맞음

- 판정식: `abs(median(lat_p50_us, "lat_256k@hfp") - median(lat_p50_us, "lat_256k@hdp")) <= 0.30`
- 셀 `lat_256k@hfp`: 판정한 시행 5회, 대입한 식 `abs(38.910 - 38.880) <= 0.30` → 참

### 4 KiB 지연: 이 실험의 운영 빌드와 gin-harden 연구 빌드 차이 0.40 µs 이하 (P3): 맞음

- 판정식: `abs(median(lat_p50_us, "lat_4k@hfp") - median(lat_p50_us, "lat_4k@hd")) <= 0.40`
- 셀 `lat_4k@hfp`: 판정한 시행 5회, 대입한 식 `abs(10.690 - 10.690) <= 0.40` → 참

### 256 KiB 지연: 같은 두 빌드 차이 0.30 µs 이하 (P4): 맞음

- 판정식: `abs(median(lat_p50_us, "lat_256k@hfp") - median(lat_p50_us, "lat_256k@hd")) <= 0.30`
- 셀 `lat_256k@hfp`: 판정한 시행 5회, 대입한 식 `abs(38.910 - 38.880) <= 0.30` → 참

## 셀별 시행 수와 따로 센 시행

| 셀 | 계획 | 실행 | 판정 | 따로 셈(사유: 시행) |
|---|--:|--:|--:|---|
| `bidirf_sym_b@hf` | 5 | 5 | 5 | 없음 |
| `f1_b@hf` | 5 | 5 | 5 | 없음 |
| `f2rel_b@hf` | 5 | 5 | 5 | 없음 |
| `f3_b@hf` | 5 | 5 | 5 | 없음 |
| `f4_b@hf` | 5 | 5 | 5 | 없음 |
| `hd_rxdeath_b@hf` | 5 | 5 | 5 | 없음 |
| `hd_shrink_b@hd` | 5 | 5 | 5 | 없음 |
| `hd_shrink_b@hf` | 10 | 10 | 10 | 없음 |
| `hd_shrink_b@hfp` | 5 | 5 | 5 | 없음 |
| `hdp_kill_b@hfp` | 5 | 5 | 5 | 없음 |
| `hf_hog_f1_b@hf` | 5 | 5 | 5 | 없음 |
| `hf_hogpre_f1_b@hf` | 5 | 6 | 5 | 드라이버 랑데부 포트 충돌: hf_hogpre_f1_b_n1 |
| `hf_hogpreslack_f1_b@hf` | 5 | 5 | 5 | 없음 |
| `hf_hogslack_f1_b@hf` | 5 | 5 | 5 | 없음 |
| `hf_shrinkdc_b@hf` | 5 | 5 | 5 | 없음 |
| `hf_shrinkoff_b@hf` | 5 | 5 | 5 | 없음 |
| `lat_256k@hd` | 5 | 5 | 5 | 없음 |
| `lat_256k@hdp` | 5 | 5 | 5 | 없음 |
| `lat_256k@hfp` | 5 | 5 | 5 | 없음 |
| `lat_4k@hd` | 5 | 5 | 5 | 없음 |
| `lat_4k@hdp` | 5 | 5 | 5 | 없음 |
| `lat_4k@hfp` | 5 | 5 | 5 | 없음 |
