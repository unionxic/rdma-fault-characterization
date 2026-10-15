# gin-mirror 채점 결과 (test 갈래)

`score.py`가 원자료에서 만들었다. 손으로 고친 값은 없다. 문턱과 반복 수는 사전 등록(태그 `prereg/gin-mirror-v1`)으로 고정했다(../../EXPERIMENT.md 3, 7, 8절).

- 예측 파일 sha256: `2db0c6941ef5e9a9829e2336585ece171775185eb60d35520ca19da995ccabbd`. `PREREG.txt`의 값과 같다.
- 시행 수: 428. 판정한 시행: 428.
- 판정식 원문은 `predictions_mi.csv`, 문법은 `../../../s2_close/EXPERIMENT.md` 3.2.

## 판정 요약

| 예측 | 셀 | n | 판정 |
|---|---|--:|---|
| 덮어쓰는 workload에서 생존 rank의 상대를 모르는 대기가 붙잡힌다 (문턱 이상으로 돌아옴, 비동기 오류 0, 거절 줄 0) (ow_wait_held) | `mi4_kill3_ow@mi` | 10 | 맞음 |
| 보낸 버퍼를 local 완료 직후 덮어써도 모든 rank의 최종 데이터가 기준과 비트 단위로 같고 독 값이 들어가지 않는다 (ow_data_equal) | `mi4_kill3_ow@mi` | 10 | 맞음 |
| 생존 rank는 한 단계도 다시 실행하지 않는다 (ow_no_reexec) | `mi4_kill3_ow@mi` | 10 | 맞음 |
| 되살린 rank가 마지막 단계를 끝내고 정상 종료한다 (ow_revived_done) | `mi4_kill3_ow@mi` | 10 | 맞음 |
| 다시 보내기 억제가 통로마다 정확하다 (ow_suppress_exact) | `mi4_kill3_ow@mi` | 10 | 맞음 |
| 재실행의 내용이 모두 pool에서 온다 (내보내기 원본 바이트 0, 가져온 pool 바이트 = 내보낸 mirror 바이트) (ow_from_pool) | `mi4_kill3_ow@mi` | 10 | 맞음 |
| 복원 시간이 2000 ms 안이다 (ow_restore_time) | `mi4_kill3_ow@mi` | 10 | 맞음 |
| 체크포인트 입력 멈춤 중 kill도 kill 앞에 확정된 체크포인트에서 비트 단위로 되살린다 (ckpt_kill_ow) | `mi4_kill3_ckpt_ow@mi` | 5 | 틀림 |
| 같은 GPU의 다른 rank가 죽어도 같다 (kill_other_ow) | `mi4_kill1_ow@mi` | 5 | 맞음 |
| 대조: mirror 없이 덮어쓰면 복원은 끝나되 데이터가 틀린다 (독 값 또는 다른 단계 값이 들어감) (nomirror_corrupt) | `mi4_kill3_ow_nomirror@mi` | 5 | 맞음 |
| 대조: checksum 표본이면 바뀐 원본을 찾아 fallback하고 생존 rank가 fallback + 2000-2500 ms에 풀린다 (nomirror_detect) | `mi4_kill3_ow_sampled@mi` | 5 | 맞음 |
| FETCH 시간이 가져온 바이트와 함께 늘고(중앙값이 바이트 순서대로) 시행마다 a + 바이트/θ의 ±15% 안이다 (a 5 µs, θ 11.88 GB/s; 확인 3), 복원 ≤ 2000 ms (seg_restore_slope) | `mi4_seg_4k@mi`, `mi4_seg_32k@mi`, `mi4_seg_128k@mi` | 5 / 5 / 5 | 맞음 |
| pool 사용은 간격에 비례하고(간격이 두 배면 최고 살아 있는 바이트의 비 2 ± 25%) 넷째 segment 자리는 쓰이지 않는다 (pool_vs_interval) | `mi4_int_10@mi`, `mi4_int_20@mi`, `mi4_int_40@mi` | 3 / 3 / 3 | 맞음 |
| 당기기가 넘침을 막는다: 장애 없음에서 20단계마다 당기기 ≥ 1, lane 깨짐과 DISARM 0 (pull_no_disarm_none) | `mi4_pull_none@mi` | 3 | 맞음 |
| 당기기 셀의 kill도 DISARM 없이 붙잡고 되살린다 (설계한 짝 보호 공백은 빼고 셈: 죽은 rank가 맡던 rank 쪽 lane의 깨짐과 DISARM을 kill부터 그 rank의 복원 뒤 첫 확정 체크포인트까지; 9.6절, 2026-10-15 DRAFT 중 고침) (pull_no_disarm_kill) | `mi4_pull@mi` | 5 | 맞음 |
| lane보다 큰 put은 넘쳐 DISARM하고 fail-fast한다 (lane 깨짐과 DISARM 줄; hold 시작 없이 죽음 판정 + 2000-2500 ms에 degraded 해제, 또는 kill 순간 잠깐 무장돼 hold가 시작되면 fallback으로 끝나 fallback + 2000-2500 ms에 해제; 2026-10-15 DRAFT 중 넓힘, 2026-10-15 사용자 확인) (overflow_failfast) | `mi4_overflow@mi` | 5 | 맞음 |
| 장애 없음: 데이터 같음, 복원 0, 입력 멈춤 ≤ 16 ms, segment 다시 시작 0 (ow_none_clean) | `mi4_none_ow@mi` | 5 | 맞음 |
| mirror와 checksum을 함께 켜면 모든 rank가 조건 36의 같은 이유로 거절하고 fail-fast로 넘어간 rank가 없다 (refuse_csum) | `mi4_refuse_csum@mi` | 3 | 맞음 |
| 한 rank만 mirror를 끄면 모든 rank가 조건 34의 같은 이유로 거절한다 (refuse_mirror1) | `mi4_refuse_mirror1@mi` | 3 | 맞음 |
| S나 L이 rank 사이에서 다르면 모든 rank가 조건 39의 같은 이유로 거절한다 (refuse_sl) | `mi4_refuse_sl@mi` | 3 | 맞음 |
| 짝이 되살아난 뒤 맡은 rank가 되살린 짝에 전체 이미지를 확정하고(그 사이 버려진 체크포인트 ≤ 1) 둘째 kill 전에 모든 생존 rank에서 다시 무장된다 (reimage_after_restore) | `mi4_kill2_kill3_ow@mi` | 5 | 맞음 |
| 그다음 맡은 rank의 죽음도 되살린 짝에서 가져와 비트 단위로 되살린다 (두 복원 모두 ≤ 2000 ms, 대기 붙잡힘, 재실행 없음) (second_death_restored) | `mi4_kill2_kill3_ow@mi` | 5 | 맞음 |
| 회귀(mirror 켬, 덮어쓰지 않는 workload): 장애 없음이 그대로 깨끗하다 (regression_none_on) | `rs4_none_mion@mi` | 5 | 맞음 |
| 회귀(mirror 켬, 덮어쓰지 않는 workload): rank 3 kill이 그대로 되살아난다 (regression_kill3_on) | `rs4_kill3_mion@mi` | 5 | 맞음 |
| 덮어쓰는 학습 모양 전송에서 최종 데이터가 기준과 같다 (대기 붙잡힘, 재실행 없음, 되살림) (train_data_equal) | `mi4_train_kill3@mi` | 10 | 맞음 |
| 단계 맞춤 가져오기가 단계마다 한 번 그 커널 전에 넣고 남은 입력 0, INJECTED가 마지막 단계 뒤 한 번 생존 셋에 간다 (train_paced_import) | `mi4_train_kill3@mi` | 10 | 맞음 |
| FETCH 시간이 a + 바이트/θ의 ±15% 안이고 복원 ≤ 1000 ms (a 5 µs, θ 11.88 GB/s; 확인 3) (train_restore_parts) | `mi4_train_kill3@mi` | 10 | 맞음 |
| segment 자리: 넷째가 필요한 다시 시작 0 (셋째 자리와 최고 바이트는 보고) (train_segments) | `mi4_train_none@mi`, `mi4_train_kill3@mi` | 5 / 10 | 맞음 |
| 설계한 짝 보호 공백(9.6절) 밖의 깨짐 0, DISARM 0 (당기기는 보고; 2026-10-15 DRAFT 중 고침) (train_pull_count) | `mi4_train_none@mi`, `mi4_train_kill3@mi` | 5 / 10 | 맞음 |
| 장애 없는 학습 모양: 데이터 같음, 복원 0, 입력 멈춤 ≤ 20 ms (train_none_clean) | `mi4_train_none@mi` | 5 | 맞음 |
| 체크포인트는 RDMA로 간다 (helper 소켓으로 보낸 이미지와 segment 바이트 0; 학습 셀 모두와 mirror 켠 4 KiB 셀) (store_rdma) | `mi4_none_ow@mi`, `mi4_kill3_ow@mi`, `mi4_kill1_ow@mi`, `mi4_kill3_ckpt_ow@mi`, `mi4_kill2_kill3_ow@mi`, `mi4_train_none@mi`, `mi4_train_kill3@mi`, `mi4_train_kill2_kill3@mi` | 5 / 10 / 5 / 5 / 5 / 5 / 10 / 5 | 맞음 |
| 학습 모양에서 둘째 죽음도 보호를 되찾고 되살린다 (두 복원 모두 ≤ 1000 ms) (train_second_death) | `mi4_train_kill2_kill3@mi` | 5 | 맞음 |
| 회귀(mirror 끔): gin-restore의 wait_held (rg_wait_held) | `rs4_kill3@mi` | 10 | 맞음 |
| 회귀(mirror 끔): gin-restore의 data_equal (rg_data_equal) | `rs4_kill3@mi` | 10 | 맞음 |
| 회귀(mirror 끔): gin-restore의 no_reexec (rg_no_reexec) | `rs4_kill3@mi` | 10 | 맞음 |
| 회귀(mirror 끔): gin-restore의 revived_done (rg_revived_done) | `rs4_kill3@mi` | 10 | 맞음 |
| 회귀(mirror 끔): gin-restore의 suppress_exact (rg_suppress_exact) | `rs4_kill3@mi` | 10 | 맞음 |
| 회귀(mirror 끔): gin-restore의 restore_time (2000 ms) (rg_restore_time) | `rs4_kill3@mi` | 10 | 맞음 |
| 회귀(mirror 끔): gin-restore의 ckpt_kill (rg_ckpt_kill) | `rs4_kill3_ckpt@mi` | 5 | 맞음 |
| 회귀(mirror 끔): gin-restore의 kill_other (rg_kill_other) | `rs4_kill1@mi` | 5 | 맞음 |
| 회귀(mirror 끔): gin-restore의 nospare_failfast (rg_nospare_failfast) | `rs4_kill3_nospare@mi` | 5 | 맞음 |
| 회귀(mirror 끔): gin-restore의 spare_absent_fallback (rg_spare_absent_fallback) | `rs4_kill3_spareabsent@mi` | 5 | 맞음 |
| 회귀(mirror 끔): gin-restore의 none_clean (rg_none_clean) | `rs4_none@mi` | 5 | 맞음 |
| 회귀(mirror 끔): gin-restore의 strict_forced (rg_strict_forced) | `rs4_none@mi` | 5 | 맞음 |
| 회귀(mirror 끔): gin-restore의 strict_notforced (rg_strict_notforced) | `rs4_none_off@mi` | 5 | 맞음 |
| 회귀(mirror 끔): gin-restore의 refuse_reason (rg_refuse_reason) | `rs4_refuse_symgin@mi`, `rs4_refuse_gintype@mi`, `rs4_refuse_restoreoff1@mi`, `rs4_refuse_nomacro@mi` | 3 / 3 / 3 / 3 | 맞음 |
| 회귀(mirror 끔): gin-restore의 refuse_nomacro_clean (rg_refuse_nomacro_clean) | `rs4_refuse_nomacro@mi` | 3 | 맞음 |
| 회귀(mirror 끔): 장애 없는 4 rank가 mirror 계층과 hold 정책에서도 투명하다 (gin-remaining 런너) (regression_restore_off) | `reg_mr4_none@mi`, `reg_mr4_none_hold@mi` | 5 / 5 | 맞음 |
| 회귀(mirror 끔): rank 3 kill의 degraded 해제가 원래 판정과 같다 (gin-remaining 런너) (regression_kill3_off) | `reg_rm4_kill3_untimed@mi`, `reg_rm4_kill3_untimed_hold@mi` | 5 / 5 | 맞음 |
| mirror의 4 KiB 지연: mirror-self, mirror-peer가 로그 켬(on)보다 노드마다 12 µs 안으로 는다 (많아야 put 하나의 지연) (cost_mirror_lat4k) | `cost:mirror:mirror-self,mirror-peer:lat4k` | - | 맞음 |
| mirror의 256 KiB 지연 (보고만) (cost_mirror_lat) | `cost:mirror:mirror-self,mirror-peer:lat256k` | - | 보고만(판정 없음) |
| mirror의 2 MiB 지연: mirror-self, mirror-peer / on이 노드마다 1.5-2.2배 (데이터 몫을 두 번 읽음) (cost_mirror_lat2m) | `cost:mirror:mirror-self,mirror-peer:lat2m` | - | 맞음 |
| mirror의 묶음 대역: mirror-peer / on이 노드마다 0.45-0.70 (같은 원본을 두 번 읽음; self는 판정하지 않음) (cost_mirror_bw) | `cost:mirror:mirror-peer:bw256k,bw2m` | - | 맞음 |

## 예측별 세부

### ow_wait_held: 맞음

- 판정식: `count(wait_held == 1) >= 9`
- 셀 `mi4_kill3_ow@mi`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(wait_held == 1)` = 10/10. 만족하지 않은 시행: 없음

### ow_data_equal: 맞음

- 판정식: `count(ow_data_equal == 1) >= 9`
- 셀 `mi4_kill3_ow@mi`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(ow_data_equal == 1)` = 10/10. 만족하지 않은 시행: 없음

### ow_no_reexec: 맞음

- 판정식: `count(no_reexec == 1) >= N_SCORED`
- 셀 `mi4_kill3_ow@mi`: 판정한 시행 10회, 대입한 식 `10 >= 10` → 참
  - `count(no_reexec == 1)` = 10/10. 만족하지 않은 시행: 없음

### ow_revived_done: 맞음

- 판정식: `count(revived_done == 1) >= 9`
- 셀 `mi4_kill3_ow@mi`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(revived_done == 1)` = 10/10. 만족하지 않은 시행: 없음

### ow_suppress_exact: 맞음

- 판정식: `count(suppress_ok == 1) >= 9`
- 셀 `mi4_kill3_ow@mi`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(suppress_ok == 1)` = 10/10. 만족하지 않은 시행: 없음

### ow_from_pool: 맞음

- 판정식: `count(from_pool_ok == 1 and export_source_bytes == 0) >= 9`
- 셀 `mi4_kill3_ow@mi`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(from_pool_ok == 1 and export_source_bytes == 0)` = 10/10. 만족하지 않은 시행: 없음

### ow_restore_time: 맞음

- 판정식: `count(restore_time_ms <= 2000) >= 9`
- 셀 `mi4_kill3_ow@mi`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(restore_time_ms <= 2000)` = 10/10. 만족하지 않은 시행: 없음

### ckpt_kill_ow: 틀림

- 판정식: `count(die_in_pause == 3 and wait_held == 1 and ow_data_equal == 1 and no_reexec == 1 and revived_done == 1 and ckpt_before == 1) >= 4`
- 셀 `mi4_kill3_ckpt_ow@mi`: 판정한 시행 5회, 대입한 식 `1 >= 4` → 거짓
  - `count(die_in_pause == 3 and wait_held == 1 and ow_data_equal == 1 and no_reexec == 1 and revived_done == 1 and ckpt_before == 1)` = 1/5. 만족하지 않은 시행: mi4_kill3_ckpt_ow_mi_n1, mi4_kill3_ckpt_ow_mi_n2, mi4_kill3_ckpt_ow_mi_n3, mi4_kill3_ckpt_ow_mi_n5

### kill_other_ow: 맞음

- 판정식: `count(wait_held == 1 and ow_data_equal == 1 and no_reexec == 1 and revived_done == 1) >= 4`
- 셀 `mi4_kill1_ow@mi`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(wait_held == 1 and ow_data_equal == 1 and no_reexec == 1 and revived_done == 1)` = 5/5. 만족하지 않은 시행: 없음

### nomirror_corrupt: 맞음

- 판정식: `count(nomirror_corrupt == 1) >= 4`
- 셀 `mi4_kill3_ow_nomirror@mi`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(nomirror_corrupt == 1)` = 5/5. 만족하지 않은 시행: 없음

### nomirror_detect: 맞음

- 판정식: `count(nomirror_detect == 1) >= 4`
- 셀 `mi4_kill3_ow_sampled@mi`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(nomirror_detect == 1)` = 5/5. 만족하지 않은 시행: 없음

### seg_restore_slope: 맞음

- 판정식: `per cell: count(fetch_us > 0 and abs(fetch_us - (5.0 + fetch_bytes / 11880.0)) <= 0.15 * (5.0 + fetch_bytes / 11880.0) and restore_time_ms <= 2000) >= N_SCORED and median(fetch_us, "mi4_seg_32k@mi") > median(fetch_us, "mi4_seg_4k@mi") and median(fetch_us, "mi4_seg_128k@mi") > median(fetch_us, "mi4_seg_32k@mi")`
- 셀 `mi4_seg_4k@mi`: 판정한 시행 5회, 대입한 식 `5 >= 5 and 2408.000 > 1273.000 and 2942.000 > 2408.000` → 참
  - `count(fetch_us > 0 and abs(fetch_us - (5.0 + fetch_bytes / 11880.0)) <= 0.15 * (5.0 + fetch_bytes / 11880.0) and restore_time_ms <= 2000)` = 5/5. 만족하지 않은 시행: 없음
- 셀 `mi4_seg_32k@mi`: 판정한 시행 5회, 대입한 식 `5 >= 5 and 2408.000 > 1273.000 and 2942.000 > 2408.000` → 참
  - `count(fetch_us > 0 and abs(fetch_us - (5.0 + fetch_bytes / 11880.0)) <= 0.15 * (5.0 + fetch_bytes / 11880.0) and restore_time_ms <= 2000)` = 5/5. 만족하지 않은 시행: 없음
- 셀 `mi4_seg_128k@mi`: 판정한 시행 5회, 대입한 식 `5 >= 5 and 2408.000 > 1273.000 and 2942.000 > 2408.000` → 참
  - `count(fetch_us > 0 and abs(fetch_us - (5.0 + fetch_bytes / 11880.0)) <= 0.15 * (5.0 + fetch_bytes / 11880.0) and restore_time_ms <= 2000)` = 5/5. 만족하지 않은 시행: 없음

### pool_vs_interval: 맞음

- 판정식: `per cell: count(restarts == 0 and pool_max_bytes > 0) == N_SCORED and abs(median(pool_max_bytes, "mi4_int_20@mi") / median(pool_max_bytes, "mi4_int_10@mi") - 2) <= 0.5 and abs(median(pool_max_bytes, "mi4_int_40@mi") / median(pool_max_bytes, "mi4_int_20@mi") - 2) <= 0.5`
- 셀 `mi4_int_10@mi`: 판정한 시행 3회, 대입한 식 `3 == 3 and abs(81920.000 / 45056.000 - 2) <= 0.5 and abs(167936.000 / 81920.000 - 2) <= 0.5` → 참
  - `count(restarts == 0 and pool_max_bytes > 0)` = 3/3. 만족하지 않은 시행: 없음
- 셀 `mi4_int_20@mi`: 판정한 시행 3회, 대입한 식 `3 == 3 and abs(81920.000 / 45056.000 - 2) <= 0.5 and abs(167936.000 / 81920.000 - 2) <= 0.5` → 참
  - `count(restarts == 0 and pool_max_bytes > 0)` = 3/3. 만족하지 않은 시행: 없음
- 셀 `mi4_int_40@mi`: 판정한 시행 3회, 대입한 식 `3 == 3 and abs(81920.000 / 45056.000 - 2) <= 0.5 and abs(167936.000 / 81920.000 - 2) <= 0.5` → 참
  - `count(restarts == 0 and pool_max_bytes > 0)` = 3/3. 만족하지 않은 시행: 없음

### pull_no_disarm_none: 맞음

- 판정식: `count(pulls_sent >= steps / 20 and disarm_n == 0 and lane_broken == 0) >= N_SCORED`
- 셀 `mi4_pull_none@mi`: 판정한 시행 3회, 대입한 식 `3 >= 3` → 참
  - `count(pulls_sent >= steps / 20 and disarm_n == 0 and lane_broken == 0)` = 3/3. 만족하지 않은 시행: 없음

### pull_no_disarm_kill: 맞음

- 판정식: `count(wait_held == 1 and ow_data_equal == 1 and disarm_other == 0 and lane_broken_other == 0) >= 4`
- 셀 `mi4_pull@mi`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(wait_held == 1 and ow_data_equal == 1 and disarm_other == 0 and lane_broken_other == 0)` = 5/5. 만족하지 않은 시행: 없음

### overflow_failfast: 맞음

- 판정식: `count(lane_broken >= 1 and ((hold_started == 0 and degraded_release == 1) or (hold_started >= 1 and fallback_release == 1))) >= 4`
- 셀 `mi4_overflow@mi`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(lane_broken >= 1 and ((hold_started == 0 and degraded_release == 1) or (hold_started >= 1 and fallback_release == 1)))` = 5/5. 만족하지 않은 시행: 없음

### ow_none_clean: 맞음

- 판정식: `count(data_equal == 1 and ow_data_equal == 1 and restore_count == 0 and ckpt_pause_ms <= 16 and seg_restart_n == 0) >= N_SCORED`
- 셀 `mi4_none_ow@mi`: 판정한 시행 5회, 대입한 식 `5 >= 5` → 참
  - `count(data_equal == 1 and ow_data_equal == 1 and restore_count == 0 and ckpt_pause_ms <= 16 and seg_restart_n == 0)` = 5/5. 만족하지 않은 시행: 없음

### refuse_csum: 맞음

- 판정식: `count(resume_err_all == 1 and reason_same == 1 and ff_fallthrough == 0 and has(resume_why0, "CHECKSUM_are_both_on")) >= N_SCORED`
- 셀 `mi4_refuse_csum@mi`: 판정한 시행 3회, 대입한 식 `3 >= 3` → 참
  - `count(resume_err_all == 1 and reason_same == 1 and ff_fallthrough == 0 and has(resume_why0, "CHECKSUM_are_both_on"))` = 3/3. 만족하지 않은 시행: 없음

### refuse_mirror1: 맞음

- 판정식: `count(resume_err_all == 1 and reason_same == 1 and ff_fallthrough == 0 and has(resume_why0, "turned_it_off")) >= N_SCORED`
- 셀 `mi4_refuse_mirror1@mi`: 판정한 시행 3회, 대입한 식 `3 >= 3` → 참
  - `count(resume_err_all == 1 and reason_same == 1 and ff_fallthrough == 0 and has(resume_why0, "turned_it_off"))` = 3/3. 만족하지 않은 시행: 없음

### refuse_sl: 맞음

- 판정식: `count(resume_err_all == 1 and reason_same == 1 and ff_fallthrough == 0 and has(resume_why0, "differs_between_ranks")) >= N_SCORED`
- 셀 `mi4_refuse_sl@mi`: 판정한 시행 3회, 대입한 식 `3 >= 3` → 참
  - `count(resume_err_all == 1 and reason_same == 1 and ff_fallthrough == 0 and has(resume_why0, "differs_between_ranks"))` = 3/3. 만족하지 않은 시행: 없음

### reimage_after_restore: 맞음

- 판정식: `count(reimage_ok == 1) >= 4`
- 셀 `mi4_kill2_kill3_ow@mi`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(reimage_ok == 1)` = 5/5. 만족하지 않은 시행: 없음

### second_death_restored: 맞음

- 판정식: `count(second_ok == 1 and restore_time_ms_1 <= 2000 and restore_time_ms_2 <= 2000 and wait_held == 1 and ow_data_equal == 1 and no_reexec == 1) >= 4`
- 셀 `mi4_kill2_kill3_ow@mi`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(second_ok == 1 and restore_time_ms_1 <= 2000 and restore_time_ms_2 <= 2000 and wait_held == 1 and ow_data_equal == 1 and no_reexec == 1)` = 5/5. 만족하지 않은 시행: 없음

### regression_none_on: 맞음

- 판정식: `count(data_equal == 1 and restore_count == 0) >= N_SCORED`
- 셀 `rs4_none_mion@mi`: 판정한 시행 5회, 대입한 식 `5 >= 5` → 참
  - `count(data_equal == 1 and restore_count == 0)` = 5/5. 만족하지 않은 시행: 없음

### regression_kill3_on: 맞음

- 판정식: `count(wait_held == 1 and data_equal == 1 and no_reexec == 1 and revived_done == 1) >= 4`
- 셀 `rs4_kill3_mion@mi`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(wait_held == 1 and data_equal == 1 and no_reexec == 1 and revived_done == 1)` = 5/5. 만족하지 않은 시행: 없음

### train_data_equal: 맞음

- 판정식: `count(ow_data_equal == 1 and wait_held == 1 and no_reexec == 1 and revived_done == 1) >= 9`
- 셀 `mi4_train_kill3@mi`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(ow_data_equal == 1 and wait_held == 1 and no_reexec == 1 and revived_done == 1)` = 10/10. 만족하지 않은 시행: 없음

### train_paced_import: 맞음

- 판정식: `count(paced_ok == 1 and inj_from_n == 3) >= 9`
- 셀 `mi4_train_kill3@mi`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(paced_ok == 1 and inj_from_n == 3)` = 10/10. 만족하지 않은 시행: 없음

### train_restore_parts: 맞음

- 판정식: `count(fetch_us > 0 and abs(fetch_us - (5.0 + fetch_bytes / 11880.0)) <= 0.15 * (5.0 + fetch_bytes / 11880.0) and restore_time_ms <= 1000) >= 9`
- 셀 `mi4_train_kill3@mi`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(fetch_us > 0 and abs(fetch_us - (5.0 + fetch_bytes / 11880.0)) <= 0.15 * (5.0 + fetch_bytes / 11880.0) and restore_time_ms <= 1000)` = 10/10. 만족하지 않은 시행: 없음

### train_segments: 맞음

- 판정식: `per cell: count(restarts == 0) == N_SCORED`
- 셀 `mi4_train_none@mi`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(restarts == 0)` = 5/5. 만족하지 않은 시행: 없음
- 셀 `mi4_train_kill3@mi`: 판정한 시행 10회, 대입한 식 `10 == 10` → 참
  - `count(restarts == 0)` = 10/10. 만족하지 않은 시행: 없음

### train_pull_count: 맞음

- 판정식: `per cell: count(lane_broken_other == 0 and broken_other == 0 and disarm_other == 0) == N_SCORED`
- 셀 `mi4_train_none@mi`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(lane_broken_other == 0 and broken_other == 0 and disarm_other == 0)` = 5/5. 만족하지 않은 시행: 없음
- 셀 `mi4_train_kill3@mi`: 판정한 시행 10회, 대입한 식 `10 == 10` → 참
  - `count(lane_broken_other == 0 and broken_other == 0 and disarm_other == 0)` = 10/10. 만족하지 않은 시행: 없음

### train_none_clean: 맞음

- 판정식: `count(ow_data_equal == 1 and restore_count == 0 and ckpt_pause_ms <= 20) >= N_SCORED`
- 셀 `mi4_train_none@mi`: 판정한 시행 5회, 대입한 식 `5 >= 5` → 참
  - `count(ow_data_equal == 1 and restore_count == 0 and ckpt_pause_ms <= 20)` = 5/5. 만족하지 않은 시행: 없음

### store_rdma: 맞음

- 판정식: `per cell: count(tcp_image_bytes == 0 and tcp_segment_bytes == 0) >= N_SCORED`
- 셀 `mi4_none_ow@mi`: 판정한 시행 5회, 대입한 식 `5 >= 5` → 참
  - `count(tcp_image_bytes == 0 and tcp_segment_bytes == 0)` = 5/5. 만족하지 않은 시행: 없음
- 셀 `mi4_kill3_ow@mi`: 판정한 시행 10회, 대입한 식 `10 >= 10` → 참
  - `count(tcp_image_bytes == 0 and tcp_segment_bytes == 0)` = 10/10. 만족하지 않은 시행: 없음
- 셀 `mi4_kill1_ow@mi`: 판정한 시행 5회, 대입한 식 `5 >= 5` → 참
  - `count(tcp_image_bytes == 0 and tcp_segment_bytes == 0)` = 5/5. 만족하지 않은 시행: 없음
- 셀 `mi4_kill3_ckpt_ow@mi`: 판정한 시행 5회, 대입한 식 `5 >= 5` → 참
  - `count(tcp_image_bytes == 0 and tcp_segment_bytes == 0)` = 5/5. 만족하지 않은 시행: 없음
- 셀 `mi4_kill2_kill3_ow@mi`: 판정한 시행 5회, 대입한 식 `5 >= 5` → 참
  - `count(tcp_image_bytes == 0 and tcp_segment_bytes == 0)` = 5/5. 만족하지 않은 시행: 없음
- 셀 `mi4_train_none@mi`: 판정한 시행 5회, 대입한 식 `5 >= 5` → 참
  - `count(tcp_image_bytes == 0 and tcp_segment_bytes == 0)` = 5/5. 만족하지 않은 시행: 없음
- 셀 `mi4_train_kill3@mi`: 판정한 시행 10회, 대입한 식 `10 >= 10` → 참
  - `count(tcp_image_bytes == 0 and tcp_segment_bytes == 0)` = 10/10. 만족하지 않은 시행: 없음
- 셀 `mi4_train_kill2_kill3@mi`: 판정한 시행 5회, 대입한 식 `5 >= 5` → 참
  - `count(tcp_image_bytes == 0 and tcp_segment_bytes == 0)` = 5/5. 만족하지 않은 시행: 없음

### train_second_death: 맞음

- 판정식: `count(reimage_ok == 1 and second_ok == 1 and restore_time_ms_1 <= 1000 and restore_time_ms_2 <= 1000 and wait_held == 1 and ow_data_equal == 1 and no_reexec == 1) >= 4`
- 셀 `mi4_train_kill2_kill3@mi`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(reimage_ok == 1 and second_ok == 1 and restore_time_ms_1 <= 1000 and restore_time_ms_2 <= 1000 and wait_held == 1 and ow_data_equal == 1 and no_reexec == 1)` = 5/5. 만족하지 않은 시행: 없음

### rg_wait_held: 맞음

- 판정식: `count(wait_held == 1) >= 9`
- 셀 `rs4_kill3@mi`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(wait_held == 1)` = 10/10. 만족하지 않은 시행: 없음

### rg_data_equal: 맞음

- 판정식: `count(data_equal == 1) >= 9`
- 셀 `rs4_kill3@mi`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(data_equal == 1)` = 10/10. 만족하지 않은 시행: 없음

### rg_no_reexec: 맞음

- 판정식: `count(no_reexec == 1) >= N_SCORED`
- 셀 `rs4_kill3@mi`: 판정한 시행 10회, 대입한 식 `10 >= 10` → 참
  - `count(no_reexec == 1)` = 10/10. 만족하지 않은 시행: 없음

### rg_revived_done: 맞음

- 판정식: `count(revived_done == 1) >= 9`
- 셀 `rs4_kill3@mi`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(revived_done == 1)` = 10/10. 만족하지 않은 시행: 없음

### rg_suppress_exact: 맞음

- 판정식: `count(suppress_ok == 1) >= 9`
- 셀 `rs4_kill3@mi`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(suppress_ok == 1)` = 10/10. 만족하지 않은 시행: 없음

### rg_restore_time: 맞음

- 판정식: `count(restore_time_ms <= 2000) >= 9`
- 셀 `rs4_kill3@mi`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(restore_time_ms <= 2000)` = 10/10. 만족하지 않은 시행: 없음

### rg_ckpt_kill: 맞음

- 판정식: `count(die_in_pause == 3 and wait_held == 1 and data_equal == 1 and no_reexec == 1 and revived_done == 1 and ckpt_before == 1) >= 4`
- 셀 `rs4_kill3_ckpt@mi`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(die_in_pause == 3 and wait_held == 1 and data_equal == 1 and no_reexec == 1 and revived_done == 1 and ckpt_before == 1)` = 5/5. 만족하지 않은 시행: 없음

### rg_kill_other: 맞음

- 판정식: `count(wait_held == 1 and data_equal == 1 and no_reexec == 1 and revived_done == 1) >= 4`
- 셀 `rs4_kill1@mi`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(wait_held == 1 and data_equal == 1 and no_reexec == 1 and revived_done == 1)` = 5/5. 만족하지 않은 시행: 없음

### rg_nospare_failfast: 맞음

- 판정식: `count(nospare_failfast_ok == 1) >= 4`
- 셀 `rs4_kill3_nospare@mi`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(nospare_failfast_ok == 1)` = 5/5. 만족하지 않은 시행: 없음

### rg_spare_absent_fallback: 맞음

- 판정식: `count(spare_absent_ok == 1) >= 4`
- 셀 `rs4_kill3_spareabsent@mi`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(spare_absent_ok == 1)` = 5/5. 만족하지 않은 시행: 없음

### rg_none_clean: 맞음

- 판정식: `count(data_equal == 1 and restore_count == 0 and ckpt_pause_ms <= 10) >= N_SCORED`
- 셀 `rs4_none@mi`: 판정한 시행 5회, 대입한 식 `5 >= 5` → 참
  - `count(data_equal == 1 and restore_count == 0 and ckpt_pause_ms <= 10)` = 5/5. 만족하지 않은 시행: 없음

### rg_strict_forced: 맞음

- 판정식: `count(strict_forced > 0 and strict_notforced == 0 and strict_bad == 0) >= N_SCORED`
- 셀 `rs4_none@mi`: 판정한 시행 5회, 대입한 식 `5 >= 5` → 참
  - `count(strict_forced > 0 and strict_notforced == 0 and strict_bad == 0)` = 5/5. 만족하지 않은 시행: 없음

### rg_strict_notforced: 맞음

- 판정식: `count(strict_notforced > 0 and strict_forced == 0 and strict_bad == 0) >= N_SCORED`
- 셀 `rs4_none_off@mi`: 판정한 시행 5회, 대입한 식 `5 >= 5` → 참
  - `count(strict_notforced > 0 and strict_forced == 0 and strict_bad == 0)` = 5/5. 만족하지 않은 시행: 없음

### rg_refuse_reason: 맞음

- 판정식: `per cell: count(resume_err_all == 1 and reason_same == 1 and ff_fallthrough == 0) >= N_SCORED`
- 셀 `rs4_refuse_symgin@mi`: 판정한 시행 3회, 대입한 식 `3 >= 3` → 참
  - `count(resume_err_all == 1 and reason_same == 1 and ff_fallthrough == 0)` = 3/3. 만족하지 않은 시행: 없음
- 셀 `rs4_refuse_gintype@mi`: 판정한 시행 3회, 대입한 식 `3 >= 3` → 참
  - `count(resume_err_all == 1 and reason_same == 1 and ff_fallthrough == 0)` = 3/3. 만족하지 않은 시행: 없음
- 셀 `rs4_refuse_restoreoff1@mi`: 판정한 시행 3회, 대입한 식 `3 >= 3` → 참
  - `count(resume_err_all == 1 and reason_same == 1 and ff_fallthrough == 0)` = 3/3. 만족하지 않은 시행: 없음
- 셀 `rs4_refuse_nomacro@mi`: 판정한 시행 3회, 대입한 식 `3 >= 3` → 참
  - `count(resume_err_all == 1 and reason_same == 1 and ff_fallthrough == 0)` = 3/3. 만족하지 않은 시행: 없음

### rg_refuse_nomacro_clean: 맞음

- 판정식: `count(resume_err_all == 1 and reason_same == 1 and nomacro_reason == 1 and refused_ran_ok == 1) >= N_SCORED`
- 셀 `rs4_refuse_nomacro@mi`: 판정한 시행 3회, 대입한 식 `3 >= 3` → 참
  - `count(resume_err_all == 1 and reason_same == 1 and nomacro_reason == 1 and refused_ran_ok == 1)` = 3/3. 만족하지 않은 시행: 없음

### regression_restore_off: 맞음

- 판정식: `per cell: count(transparent_ok == 1) == N_SCORED`
- 셀 `reg_mr4_none@mi`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1)` = 5/5. 만족하지 않은 시행: 없음
- 셀 `reg_mr4_none_hold@mi`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1)` = 5/5. 만족하지 않은 시행: 없음

### regression_kill3_off: 맞음

- 판정식: `per cell: count(n_rel_dead == 3 and 2000 <= rel_after_dead_ms_r0 <= 3000 and 2000 <= rel_after_dead_ms_r1 <= 3000 and 2000 <= rel_after_dead_ms_r2 <= 3000 and n_surv_edges == 6 and surv_tx_ok == 6 and n_kdone_surv == 3 and n_stuck_surv == 0) == N_SCORED`
- 셀 `reg_rm4_kill3_untimed@mi`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(n_rel_dead == 3 and 2000 <= rel_after_dead_ms_r0 <= 3000 and 2000 <= rel_after_dead_ms_r1 <= 3000 and 2000 <= rel_after_dead_ms_r2 <= 3000 and n_surv_edges == 6 and surv_tx_ok == 6 and n_kdone_surv == 3 and n_stuck_surv == 0)` = 5/5. 만족하지 않은 시행: 없음
- 셀 `reg_rm4_kill3_untimed_hold@mi`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(n_rel_dead == 3 and 2000 <= rel_after_dead_ms_r0 <= 3000 and 2000 <= rel_after_dead_ms_r1 <= 3000 and 2000 <= rel_after_dead_ms_r2 <= 3000 and n_surv_edges == 6 and surv_tx_ok == 6 and n_kdone_surv == 3 and n_stuck_surv == 0)` = 5/5. 만족하지 않은 시행: 없음

### cost_mirror_lat4k: 맞음

- 판정식: `cost: rule=within_us:12`

| 받는 노드 | 크기 | 팔 | n | 중앙값 | 기준 팔과의 차 | 읽기 |
|---|---|---|--:|--:|---|---|
| rain | lat4k | on | 6 | 13.310 | - | 기준 |
| rain | lat4k | mirror-self | 6 | 20.480 | +7.170 (+53.9%) | 범위 안 +7.170 (≤ 12) |
| rain | lat4k | mirror-peer | 6 | 21.500 | +8.190 (+61.5%) | 범위 안 +8.190 (≤ 12) |
| sunny | lat4k | on | 6 | 13.760 | - | 기준 |
| sunny | lat4k | mirror-self | 6 | 22.340 | +8.580 (+62.4%) | 범위 안 +8.580 (≤ 12) |
| sunny | lat4k | mirror-peer | 6 | 22.560 | +8.800 (+64.0%) | 범위 안 +8.800 (≤ 12) |

### cost_mirror_lat: 보고만(판정 없음)

- 판정식: `cost: rule=report`

| 받는 노드 | 크기 | 팔 | n | 중앙값 | 기준 팔과의 차 | 읽기 |
|---|---|---|--:|--:|---|---|
| rain | lat256k | on | 6 | 43.010 | - | 기준 |
| rain | lat256k | mirror-self | 6 | 74.240 | +31.230 (+72.6%) | 비 1.726 |
| rain | lat256k | mirror-peer | 6 | 71.170 | +28.160 (+65.5%) | 비 1.655 |
| sunny | lat256k | on | 6 | 41.395 | - | 기준 |
| sunny | lat256k | mirror-self | 6 | 74.320 | +32.925 (+79.5%) | 비 1.795 |
| sunny | lat256k | mirror-peer | 6 | 70.255 | +28.860 (+69.7%) | 비 1.697 |

### cost_mirror_lat2m: 맞음

- 판정식: `cost: rule=ratio:1.5-2.2`

| 받는 노드 | 크기 | 팔 | n | 중앙값 | 기준 팔과의 차 | 읽기 |
|---|---|---|--:|--:|---|---|
| rain | lat2m | on | 6 | 223.230 | - | 기준 |
| rain | lat2m | mirror-self | 6 | 430.590 | +207.360 (+92.9%) | 범위 안 비 1.929 (1.5–2.2) |
| rain | lat2m | mirror-peer | 6 | 417.280 | +194.050 (+86.9%) | 범위 안 비 1.869 (1.5–2.2) |
| sunny | lat2m | on | 6 | 222.560 | - | 기준 |
| sunny | lat2m | mirror-self | 6 | 426.270 | +203.710 (+91.5%) | 범위 안 비 1.915 (1.5–2.2) |
| sunny | lat2m | mirror-peer | 6 | 413.630 | +191.070 (+85.9%) | 범위 안 비 1.859 (1.5–2.2) |

### cost_mirror_bw: 맞음

- 판정식: `cost: rule=ratio:0.45-0.70`

| 받는 노드 | 크기 | 팔 | n | 중앙값 | 기준 팔과의 차 | 읽기 |
|---|---|---|--:|--:|---|---|
| rain | bw256k | on | 6 | 5.172 | - | 기준 |
| rain | bw256k | mirror-peer | 6 | 3.282 | +1.890 (+36.5%) | 범위 안 비 0.635 (0.45–0.7) |
| rain | bw2m | on | 6 | 5.891 | - | 기준 |
| rain | bw2m | mirror-peer | 6 | 3.283 | +2.608 (+44.3%) | 범위 안 비 0.557 (0.45–0.7) |
| sunny | bw256k | on | 6 | 6.021 | - | 기준 |
| sunny | bw256k | mirror-peer | 6 | 3.799 | +2.222 (+36.9%) | 범위 안 비 0.631 (0.45–0.7) |
| sunny | bw2m | on | 6 | 7.027 | - | 기준 |
| sunny | bw2m | mirror-peer | 6 | 3.877 | +3.150 (+44.8%) | 범위 안 비 0.552 (0.45–0.7) |

## 셀별 시행 수와 따로 센 시행

| 셀 | 계획 | 실행 | 판정 | 따로 셈(사유: 시행) |
|---|--:|--:|--:|---|
| `cost_bw256k_mirror-peer@mip` | 12 | 12 | 12 | 없음 |
| `cost_bw256k_mirror-self@mip` | 12 | 12 | 12 | 없음 |
| `cost_bw256k_off@mip` | 12 | 12 | 12 | 없음 |
| `cost_bw256k_on@mip` | 12 | 12 | 12 | 없음 |
| `cost_bw2m_mirror-peer@mip` | 12 | 12 | 12 | 없음 |
| `cost_bw2m_mirror-self@mip` | 12 | 12 | 12 | 없음 |
| `cost_bw2m_off@mip` | 12 | 12 | 12 | 없음 |
| `cost_bw2m_on@mip` | 12 | 12 | 12 | 없음 |
| `cost_lat256k_mirror-peer@mip` | 12 | 12 | 12 | 없음 |
| `cost_lat256k_mirror-self@mip` | 12 | 12 | 12 | 없음 |
| `cost_lat256k_off@mip` | 12 | 12 | 12 | 없음 |
| `cost_lat256k_on@mip` | 12 | 12 | 12 | 없음 |
| `cost_lat2m_mirror-peer@mip` | 12 | 12 | 12 | 없음 |
| `cost_lat2m_mirror-self@mip` | 12 | 12 | 12 | 없음 |
| `cost_lat2m_off@mip` | 12 | 12 | 12 | 없음 |
| `cost_lat2m_on@mip` | 12 | 12 | 12 | 없음 |
| `cost_lat4k_mirror-peer@mip` | 12 | 12 | 12 | 없음 |
| `cost_lat4k_mirror-self@mip` | 12 | 12 | 12 | 없음 |
| `cost_lat4k_off@mip` | 12 | 12 | 12 | 없음 |
| `cost_lat4k_on@mip` | 12 | 12 | 12 | 없음 |
| `mi4_int_10@mi` | 3 | 3 | 3 | 없음 |
| `mi4_int_20@mi` | 3 | 3 | 3 | 없음 |
| `mi4_int_40@mi` | 3 | 3 | 3 | 없음 |
| `mi4_kill1_ow@mi` | 5 | 5 | 5 | 없음 |
| `mi4_kill2_kill3_ow@mi` | 5 | 5 | 5 | 없음 |
| `mi4_kill3_ckpt_ow@mi` | 5 | 5 | 5 | 없음 |
| `mi4_kill3_ow@mi` | 10 | 10 | 10 | 없음 |
| `mi4_kill3_ow_nomirror@mi` | 5 | 5 | 5 | 없음 |
| `mi4_kill3_ow_sampled@mi` | 5 | 5 | 5 | 없음 |
| `mi4_none_ow@mi` | 5 | 5 | 5 | 없음 |
| `mi4_overflow@mi` | 5 | 5 | 5 | 없음 |
| `mi4_pull@mi` | 5 | 5 | 5 | 없음 |
| `mi4_pull_none@mi` | 3 | 3 | 3 | 없음 |
| `mi4_refuse_csum@mi` | 3 | 3 | 3 | 없음 |
| `mi4_refuse_mirror1@mi` | 3 | 3 | 3 | 없음 |
| `mi4_refuse_sl@mi` | 3 | 3 | 3 | 없음 |
| `mi4_seg_128k@mi` | 5 | 5 | 5 | 없음 |
| `mi4_seg_32k@mi` | 5 | 5 | 5 | 없음 |
| `mi4_seg_4k@mi` | 5 | 5 | 5 | 없음 |
| `mi4_train_kill2_kill3@mi` | 5 | 5 | 5 | 없음 |
| `mi4_train_kill3@mi` | 10 | 10 | 10 | 없음 |
| `mi4_train_none@mi` | 5 | 5 | 5 | 없음 |
| `reg_mr4_none@mi` | 5 | 5 | 5 | 없음 |
| `reg_mr4_none_hold@mi` | 5 | 5 | 5 | 없음 |
| `reg_rm4_kill3_untimed@mi` | 5 | 5 | 5 | 없음 |
| `reg_rm4_kill3_untimed_hold@mi` | 5 | 5 | 5 | 없음 |
| `rs4_kill1@mi` | 5 | 5 | 5 | 없음 |
| `rs4_kill3@mi` | 10 | 10 | 10 | 없음 |
| `rs4_kill3_ckpt@mi` | 5 | 5 | 5 | 없음 |
| `rs4_kill3_mion@mi` | 5 | 5 | 5 | 없음 |
| `rs4_kill3_nospare@mi` | 5 | 5 | 5 | 없음 |
| `rs4_kill3_spareabsent@mi` | 5 | 5 | 5 | 없음 |
| `rs4_none@mi` | 5 | 5 | 5 | 없음 |
| `rs4_none_mion@mi` | 5 | 5 | 5 | 없음 |
| `rs4_none_off@mi` | 5 | 5 | 5 | 없음 |
| `rs4_refuse_gintype@mi` | 3 | 3 | 3 | 없음 |
| `rs4_refuse_nomacro@mi` | 3 | 3 | 3 | 없음 |
| `rs4_refuse_restoreoff1@mi` | 3 | 3 | 3 | 없음 |
| `rs4_refuse_symgin@mi` | 3 | 3 | 3 | 없음 |
