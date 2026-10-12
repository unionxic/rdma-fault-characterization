# gin-restore 채점 결과 (work package 10)

`score.py`가 원자료에서 만들었다. 손으로 고친 값은 없다. 문턱과 반복 수는 2026-10-13 사전 등록으로 고정했다(EXPERIMENT.md 3, 7, 8절, 태그 `prereg/gin-restore-v1`).

- 예측 파일 sha256: `752c832926acf42a18a8b84482cc30119a283c0f6dfe7385894f516dfe26b596`. `PREREG.txt`의 값과 같다.
- 시행 수: 329. 판정한 시행: 329.
- 판정식 원문은 `predictions_rs.csv`, 문법은 `../../../s2_close/EXPERIMENT.md` 3.2.

## 판정 요약

| 예측 | 셀 | n | 판정 |
|---|---|--:|---|
| 생존 rank의 상대를 모르는 대기가 풀리지 않는다 (문턱 이상으로 돌아옴, 비동기 오류 0, 거절 줄 0) (wait_held) | `rs4_kill3@rs` | 10 | 맞음 |
| 모든 rank의 최종 상태와 받은 칸이 호스트 기준과 비트 단위로 같다 (data_equal) | `rs4_kill3@rs` | 10 | 맞음 |
| 생존 rank는 한 단계도 다시 실행하지 않는다 (no_reexec) | `rs4_kill3@rs` | 10 | 맞음 |
| 되살린 rank가 마지막 단계를 끝내고 정상 종료한다 (revived_done) | `rs4_kill3@rs` | 10 | 맞음 |
| 다시 보내기 억제가 통로마다 정확하다 (억제 수 = 누적 실행 수 - 체크포인트 때의 실행 수) (suppress_exact) | `rs4_kill3@rs` | 10 | 맞음 |
| 복원 시간(첫 죽음 판정 줄부터 마지막 생존 rank의 게이트 재개까지)이 시한 T = 2000 ms 안이다 (초안 10000 ms; pilot i4의 399.5-401.7 ms의 5배) (restore_time) | `rs4_kill3@rs` | 10 | 맞음 |
| 체크포인트 멈춤 중 kill(라이브러리 시험 스위치의 죽음 줄이 있고 생존 rank 셋이 모두 그 체크포인트의 입력 멈춤 안)도 kill 앞에 확정된 체크포인트에서 복원한다 (ckpt_kill) | `rs4_kill3_ckpt@rs` | 5 | 맞음 |
| 같은 GPU의 다른 rank가 죽어도 같다 (kill_other) | `rs4_kill1@rs` | 5 | 맞음 |
| 예비 프로세스를 등록하지 않으면 그 rank는 무장되지 않아 hk와 같은 fail-fast: 붙잡지 않고 거절 줄이 있으며 생존 rank의 대기가 죽음 판정 + 2000-2500 ms 안에 degraded로 풀린다 (nospare_failfast) | `rs4_kill3_nospare@rs` | 5 | 맞음 |
| 예비 프로세스를 등록했으나 활성화 전에 없어지면 붙잡았다가 hold 시작 뒤 약 1 s(초안 500-1500 ms)에 fallback하고 그 뒤 2000-2500 ms 안에 생존 rank의 대기가 degraded로 풀린다 (spare_absent_fallback) | `rs4_kill3_spareabsent@rs` | 5 | 맞음 |
| 복원이 없는 빌드는 죽음 판정 + 2000-2500 ms 안에 생존 rank의 대기가 degraded로 풀린다 (control_degraded) | `rs4_kill3@hk` | 5 | 맞음 |
| 장애 없음: 데이터 같음, 복원 0, 체크포인트마다 생존 rank의 입력 멈춤 10 ms 이하 (초안 5 ms; pilot 최대 5.9 ms의 약 두 배) (none_clean) | `rs4_none@rs` | 5 | 맞음 |
| hold 셀: 모든 GDAKI window MR이 strict로 강제된다 (strict_forced) | `rs4_none@rs` | 5 | 맞음 |
| 복원을 끈 셀: 강제 0 (strict_notforced) | `rs4_none_off@rs` | 5 | 맞음 |
| 켤 수 없는 설정에서 모든 rank의 Resume이 같은 이유의 오류를 돌려주고 fail-fast로 넘어간 rank가 없다 (refuse_reason) | `rs4_refuse_symgin@rs`, `rs4_refuse_gintype@rs`, `rs4_refuse_restoreoff1@rs`, `rs4_refuse_nomacro@rs` | 3 / 3 / 3 / 3 | 맞음 |
| 복원 매크로(NCCL_GIN_RESTORE_DEVICE) 없이 빌드한 프로그램이 hold 정책으로 Resume을 부르면 모든 rank가 그 매크로를 이유로 든 같은 오류를 받고, trap 없이 fail-fast로 끝까지 돌아 결과가 기준과 같다 (refuse_nomacro_clean) | `rs4_refuse_nomacro@rs` | 3 | 맞음 |
| 회귀: 장애 없는 4 rank가 복원 계층과 hold 정책에서도 투명하다 (gpu-detect RG8의 꼴) (regression_none) | `reg_mr4_none@rs`, `reg_mr4_none_hold@rs` | 5 / 5 | 맞음 |
| 회귀: rank 3 kill의 degraded 해제가 원래 판정과 같다 (gpu-detect RG9의 꼴, gin-remaining DG1과 DG3) (regression_kill3) | `reg_rm4_kill3_untimed@rs`, `reg_rm4_kill3_untimed_hold@rs` | 5 / 5 | 맞음 |
| 로그의 비용(복원 모드): 재기만 하는 모드의 로그 켬(checksum 끔)이 매크로 빌드의 fail-fast(off)보다 모든 노드와 지표에서 나쁜 쪽으로 10% 안이다 (비용 pilot 2: 256 KiB와 대역 2.5-5.3%, 4 KiB rain 9.1%, sunny 14.8%라 4 KiB에서 틀릴 가능성이 큼) (cost_log) | `cost:log:on` | - | 틀림 |
| checksum의 비용(보고만): 켬+표본 checksum과 켬+전부 checksum을 fail-fast(off)와 견줌 (기본값은 끔) (cost_checksum) | `cost:log:sampled,full` | - | 보고만(판정 없음) |
| 무장 전 hold의 비용: 로그 없는 hold 길(재기만 하는 모드, 로그 0)이 매크로 빌드의 fail-fast(off)보다 모든 노드와 지표에서 나쁜 쪽으로 10% 안이다 (비용 pilot 2: 4 KiB rain 9.1%, sunny 13.0%, 나머지 2.5-4.8%) (cost_unarmed) | `cost:log:ua-hold` | - | 틀림 |
| fail-fast의 분기 비용 없음 (이 계층 대 hk 운영 빌드): 갈리지 않음 (cost_ff) | `cost:ffbranch` | - | 틀림 |

## 예측별 세부

### wait_held: 맞음

- 판정식: `count(wait_held == 1) >= 9`
- 셀 `rs4_kill3@rs`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(wait_held == 1)` = 10/10. 만족하지 않은 시행: 없음

### data_equal: 맞음

- 판정식: `count(data_equal == 1) >= 9`
- 셀 `rs4_kill3@rs`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(data_equal == 1)` = 10/10. 만족하지 않은 시행: 없음

### no_reexec: 맞음

- 판정식: `count(no_reexec == 1) >= N_SCORED`
- 셀 `rs4_kill3@rs`: 판정한 시행 10회, 대입한 식 `10 >= 10` → 참
  - `count(no_reexec == 1)` = 10/10. 만족하지 않은 시행: 없음

### revived_done: 맞음

- 판정식: `count(revived_done == 1) >= 9`
- 셀 `rs4_kill3@rs`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(revived_done == 1)` = 10/10. 만족하지 않은 시행: 없음

### suppress_exact: 맞음

- 판정식: `count(suppress_ok == 1) >= 9`
- 셀 `rs4_kill3@rs`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(suppress_ok == 1)` = 10/10. 만족하지 않은 시행: 없음

### restore_time: 맞음

- 판정식: `count(restore_time_ms <= 2000) >= 9`
- 셀 `rs4_kill3@rs`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(restore_time_ms <= 2000)` = 10/10. 만족하지 않은 시행: 없음

### ckpt_kill: 맞음

- 판정식: `count(die_in_pause == 3 and wait_held == 1 and data_equal == 1 and no_reexec == 1 and revived_done == 1 and ckpt_before == 1) >= 4`
- 셀 `rs4_kill3_ckpt@rs`: 판정한 시행 5회, 대입한 식 `4 >= 4` → 참
  - `count(die_in_pause == 3 and wait_held == 1 and data_equal == 1 and no_reexec == 1 and revived_done == 1 and ckpt_before == 1)` = 4/5. 만족하지 않은 시행: rs4_kill3_ckpt_rs_n4

### kill_other: 맞음

- 판정식: `count(wait_held == 1 and data_equal == 1 and no_reexec == 1 and revived_done == 1) >= 4`
- 셀 `rs4_kill1@rs`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(wait_held == 1 and data_equal == 1 and no_reexec == 1 and revived_done == 1)` = 5/5. 만족하지 않은 시행: 없음

### nospare_failfast: 맞음

- 판정식: `count(nospare_failfast_ok == 1) >= 4`
- 셀 `rs4_kill3_nospare@rs`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(nospare_failfast_ok == 1)` = 5/5. 만족하지 않은 시행: 없음

### spare_absent_fallback: 맞음

- 판정식: `count(spare_absent_ok == 1) >= 4`
- 셀 `rs4_kill3_spareabsent@rs`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(spare_absent_ok == 1)` = 5/5. 만족하지 않은 시행: 없음

### control_degraded: 맞음

- 판정식: `count(degraded_release == 1) >= 4`
- 셀 `rs4_kill3@hk`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(degraded_release == 1)` = 5/5. 만족하지 않은 시행: 없음

### none_clean: 맞음

- 판정식: `count(data_equal == 1 and restore_count == 0 and ckpt_pause_ms <= 10) >= N_SCORED`
- 셀 `rs4_none@rs`: 판정한 시행 5회, 대입한 식 `5 >= 5` → 참
  - `count(data_equal == 1 and restore_count == 0 and ckpt_pause_ms <= 10)` = 5/5. 만족하지 않은 시행: 없음

### strict_forced: 맞음

- 판정식: `count(strict_forced > 0 and strict_notforced == 0 and strict_bad == 0) >= N_SCORED`
- 셀 `rs4_none@rs`: 판정한 시행 5회, 대입한 식 `5 >= 5` → 참
  - `count(strict_forced > 0 and strict_notforced == 0 and strict_bad == 0)` = 5/5. 만족하지 않은 시행: 없음

### strict_notforced: 맞음

- 판정식: `count(strict_notforced > 0 and strict_forced == 0 and strict_bad == 0) >= N_SCORED`
- 셀 `rs4_none_off@rs`: 판정한 시행 5회, 대입한 식 `5 >= 5` → 참
  - `count(strict_notforced > 0 and strict_forced == 0 and strict_bad == 0)` = 5/5. 만족하지 않은 시행: 없음

### refuse_reason: 맞음

- 판정식: `per cell: count(resume_err_all == 1 and reason_same == 1 and ff_fallthrough == 0) >= N_SCORED`
- 셀 `rs4_refuse_symgin@rs`: 판정한 시행 3회, 대입한 식 `3 >= 3` → 참
  - `count(resume_err_all == 1 and reason_same == 1 and ff_fallthrough == 0)` = 3/3. 만족하지 않은 시행: 없음
- 셀 `rs4_refuse_gintype@rs`: 판정한 시행 3회, 대입한 식 `3 >= 3` → 참
  - `count(resume_err_all == 1 and reason_same == 1 and ff_fallthrough == 0)` = 3/3. 만족하지 않은 시행: 없음
- 셀 `rs4_refuse_restoreoff1@rs`: 판정한 시행 3회, 대입한 식 `3 >= 3` → 참
  - `count(resume_err_all == 1 and reason_same == 1 and ff_fallthrough == 0)` = 3/3. 만족하지 않은 시행: 없음
- 셀 `rs4_refuse_nomacro@rs`: 판정한 시행 3회, 대입한 식 `3 >= 3` → 참
  - `count(resume_err_all == 1 and reason_same == 1 and ff_fallthrough == 0)` = 3/3. 만족하지 않은 시행: 없음

### refuse_nomacro_clean: 맞음

- 판정식: `count(resume_err_all == 1 and reason_same == 1 and nomacro_reason == 1 and refused_ran_ok == 1) >= N_SCORED`
- 셀 `rs4_refuse_nomacro@rs`: 판정한 시행 3회, 대입한 식 `3 >= 3` → 참
  - `count(resume_err_all == 1 and reason_same == 1 and nomacro_reason == 1 and refused_ran_ok == 1)` = 3/3. 만족하지 않은 시행: 없음

### regression_none: 맞음

- 판정식: `per cell: count(transparent_ok == 1) == N_SCORED`
- 셀 `reg_mr4_none@rs`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1)` = 5/5. 만족하지 않은 시행: 없음
- 셀 `reg_mr4_none_hold@rs`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1)` = 5/5. 만족하지 않은 시행: 없음

### regression_kill3: 맞음

- 판정식: `per cell: count(n_rel_dead == 3 and 2000 <= rel_after_dead_ms_r0 <= 3000 and 2000 <= rel_after_dead_ms_r1 <= 3000 and 2000 <= rel_after_dead_ms_r2 <= 3000 and n_surv_edges == 6 and surv_tx_ok == 6 and n_kdone_surv == 3 and n_stuck_surv == 0) == N_SCORED`
- 셀 `reg_rm4_kill3_untimed@rs`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(n_rel_dead == 3 and 2000 <= rel_after_dead_ms_r0 <= 3000 and 2000 <= rel_after_dead_ms_r1 <= 3000 and 2000 <= rel_after_dead_ms_r2 <= 3000 and n_surv_edges == 6 and surv_tx_ok == 6 and n_kdone_surv == 3 and n_stuck_surv == 0)` = 5/5. 만족하지 않은 시행: 없음
- 셀 `reg_rm4_kill3_untimed_hold@rs`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(n_rel_dead == 3 and 2000 <= rel_after_dead_ms_r0 <= 3000 and 2000 <= rel_after_dead_ms_r1 <= 3000 and 2000 <= rel_after_dead_ms_r2 <= 3000 and n_surv_edges == 6 and surv_tx_ok == 6 and n_kdone_surv == 3 and n_stuck_surv == 0)` = 5/5. 만족하지 않은 시행: 없음

### cost_log: 틀림

- 판정식: `cost: rule=within:10`

| 받는 노드 | 크기 | 팔 | n | 중앙값 | 기준 팔과의 차 | 읽기 |
|---|---|---|--:|--:|---|---|
| rain | lat4k | off | 6 | 11.260 | - | 기준 |
| rain | lat4k | on | 6 | 12.290 | +1.030 (+9.1%) | 범위 안(+9.1% ≤ 10%) |
| rain | lat256k | off | 6 | 39.940 | - | 기준 |
| rain | lat256k | on | 6 | 41.470 | +1.530 (+3.8%) | 범위 안(+3.8% ≤ 10%) |
| rain | bw256k | off | 6 | 5.461 | - | 기준 |
| rain | bw256k | on | 6 | 5.231 | +0.230 (+4.2%) | 범위 안(+4.2% ≤ 10%) |
| sunny | lat4k | off | 6 | 10.925 | - | 기준 |
| sunny | lat4k | on | 6 | 12.580 | +1.655 (+15.1%) | 범위 밖(+15.1% > 10%) |
| sunny | lat256k | off | 6 | 39.055 | - | 기준 |
| sunny | lat256k | on | 6 | 40.930 | +1.875 (+4.8%) | 범위 안(+4.8% ≤ 10%) |
| sunny | bw256k | off | 6 | 6.445 | - | 기준 |
| sunny | bw256k | on | 6 | 6.126 | +0.319 (+4.9%) | 범위 안(+4.9% ≤ 10%) |

### cost_checksum: 보고만(판정 없음)

- 판정식: `cost: rule=report`

| 받는 노드 | 크기 | 팔 | n | 중앙값 | 기준 팔과의 차 | 읽기 |
|---|---|---|--:|--:|---|---|
| rain | lat4k | off | 6 | 11.260 | - | 기준 |
| rain | lat4k | sampled | 6 | 13.310 | +2.050 (+18.2%) | 갈림(나쁨) |
| rain | lat4k | full | 6 | 30.720 | +19.460 (+172.8%) | 갈림(나쁨) |
| rain | lat256k | off | 6 | 39.940 | - | 기준 |
| rain | lat256k | sampled | 6 | 47.100 | +7.160 (+17.9%) | 갈림(나쁨) |
| rain | lat256k | full | 6 | 959.490 | +919.550 (+2302.3%) | 갈림(나쁨) |
| rain | bw256k | off | 6 | 5.461 | - | 기준 |
| rain | bw256k | sampled | 6 | 2.743 | +2.718 (+49.8%) | 갈림(나쁨) |
| rain | bw256k | full | 6 | 0.137 | +5.324 (+97.5%) | 갈림(나쁨) |
| sunny | lat4k | off | 6 | 10.925 | - | 기준 |
| sunny | lat4k | sampled | 6 | 15.970 | +5.045 (+46.2%) | 갈림(나쁨) |
| sunny | lat4k | full | 6 | 32.320 | +21.395 (+195.8%) | 갈림(나쁨) |
| sunny | lat256k | off | 6 | 39.055 | - | 기준 |
| sunny | lat256k | sampled | 6 | 45.395 | +6.340 (+16.2%) | 갈림(나쁨) |
| sunny | lat256k | full | 6 | 988.700 | +949.645 (+2431.6%) | 갈림(나쁨) |
| sunny | bw256k | off | 6 | 6.445 | - | 기준 |
| sunny | bw256k | sampled | 6 | 3.120 | +3.325 (+51.6%) | 갈림(나쁨) |
| sunny | bw256k | full | 6 | 0.150 | +6.295 (+97.7%) | 갈림(나쁨) |

### cost_unarmed: 틀림

- 판정식: `cost: rule=within:10`

| 받는 노드 | 크기 | 팔 | n | 중앙값 | 기준 팔과의 차 | 읽기 |
|---|---|---|--:|--:|---|---|
| rain | lat4k | off | 6 | 11.260 | - | 기준 |
| rain | lat4k | ua-hold | 6 | 12.290 | +1.030 (+9.1%) | 범위 안(+9.1% ≤ 10%) |
| rain | lat256k | off | 6 | 39.940 | - | 기준 |
| rain | lat256k | ua-hold | 6 | 42.495 | +2.555 (+6.4%) | 범위 안(+6.4% ≤ 10%) |
| rain | bw256k | off | 6 | 5.461 | - | 기준 |
| rain | bw256k | ua-hold | 6 | 5.319 | +0.142 (+2.6%) | 범위 안(+2.6% ≤ 10%) |
| sunny | lat4k | off | 6 | 10.925 | - | 기준 |
| sunny | lat4k | ua-hold | 6 | 12.380 | +1.455 (+13.3%) | 범위 밖(+13.3% > 10%) |
| sunny | lat256k | off | 6 | 39.055 | - | 기준 |
| sunny | lat256k | ua-hold | 6 | 40.930 | +1.875 (+4.8%) | 범위 안(+4.8% ≤ 10%) |
| sunny | bw256k | off | 6 | 6.445 | - | 기준 |
| sunny | bw256k | ua-hold | 6 | 6.239 | +0.206 (+3.2%) | 범위 안(+3.2% ≤ 10%) |

### cost_ff: 틀림

- 판정식: `cost: rule=not_separated`

| 받는 노드 | 크기 | 팔 | n | 중앙값 | 기준 팔과의 차 | 읽기 |
|---|---|---|--:|--:|---|---|
| rain | lat4k | ffb-hk | 6 | 11.260 | - | 기준 |
| rain | lat4k | ffb-rs | 6 | 11.260 | +0.000 (+0.0%) | 차이를 잴 수 없음 |
| rain | lat4k | ffb-rs-macro | 6 | 11.260 | +0.000 (+0.0%) | 차이를 잴 수 없음(보고만) |
| rain | lat256k | ffb-hk | 6 | 40.450 | - | 기준 |
| rain | lat256k | ffb-rs | 6 | 39.940 | -0.510 (-1.3%) | 차이를 잴 수 없음 |
| rain | lat256k | ffb-rs-macro | 6 | 40.450 | +0.000 (+0.0%) | 차이를 잴 수 없음(보고만) |
| sunny | lat4k | ffb-hk | 6 | 10.560 | - | 기준 |
| sunny | lat4k | ffb-rs | 6 | 10.620 | +0.060 (+0.6%) | 갈림(나쁨) |
| sunny | lat4k | ffb-rs-macro | 6 | 10.940 | +0.380 (+3.6%) | 갈림(나쁨)(보고만) |
| sunny | lat256k | ffb-hk | 6 | 38.910 | - | 기준 |
| sunny | lat256k | ffb-rs | 6 | 38.910 | +0.000 (+0.0%) | 차이를 잴 수 없음 |
| sunny | lat256k | ffb-rs-macro | 6 | 39.070 | +0.160 (+0.4%) | 차이를 잴 수 없음(보고만) |

## 셀별 시행 수와 따로 센 시행

| 셀 | 계획 | 실행 | 판정 | 따로 셈(사유: 시행) |
|---|--:|--:|--:|---|
| `cost_bw256k_full@rsp` | 12 | 12 | 12 | 없음 |
| `cost_bw256k_off@rsp` | 12 | 12 | 12 | 없음 |
| `cost_bw256k_on@rsp` | 12 | 12 | 12 | 없음 |
| `cost_bw256k_sampled@rsp` | 12 | 12 | 12 | 없음 |
| `cost_bw256k_ua-hold@rsp` | 12 | 12 | 12 | 없음 |
| `cost_lat256k_ffb-hk@hkp` | 12 | 12 | 12 | 없음 |
| `cost_lat256k_ffb-rs-macro@rsp` | 12 | 12 | 12 | 없음 |
| `cost_lat256k_ffb-rs@rsp` | 12 | 12 | 12 | 없음 |
| `cost_lat256k_full@rsp` | 12 | 12 | 12 | 없음 |
| `cost_lat256k_off@rsp` | 12 | 12 | 12 | 없음 |
| `cost_lat256k_on@rsp` | 12 | 12 | 12 | 없음 |
| `cost_lat256k_sampled@rsp` | 12 | 12 | 12 | 없음 |
| `cost_lat256k_ua-hold@rsp` | 12 | 12 | 12 | 없음 |
| `cost_lat4k_ffb-hk@hkp` | 12 | 12 | 12 | 없음 |
| `cost_lat4k_ffb-rs-macro@rsp` | 12 | 12 | 12 | 없음 |
| `cost_lat4k_ffb-rs@rsp` | 12 | 12 | 12 | 없음 |
| `cost_lat4k_full@rsp` | 12 | 12 | 12 | 없음 |
| `cost_lat4k_off@rsp` | 12 | 12 | 12 | 없음 |
| `cost_lat4k_on@rsp` | 12 | 12 | 12 | 없음 |
| `cost_lat4k_sampled@rsp` | 12 | 12 | 12 | 없음 |
| `cost_lat4k_ua-hold@rsp` | 12 | 12 | 12 | 없음 |
| `reg_mr4_none@rs` | 5 | 5 | 5 | 없음 |
| `reg_mr4_none_hold@rs` | 5 | 5 | 5 | 없음 |
| `reg_rm4_kill3_untimed@rs` | 5 | 5 | 5 | 없음 |
| `reg_rm4_kill3_untimed_hold@rs` | 5 | 5 | 5 | 없음 |
| `rs4_kill1@rs` | 5 | 5 | 5 | 없음 |
| `rs4_kill3@hk` | 5 | 5 | 5 | 없음 |
| `rs4_kill3@rs` | 10 | 10 | 10 | 없음 |
| `rs4_kill3_ckpt@rs` | 5 | 5 | 5 | 없음 |
| `rs4_kill3_nospare@rs` | 5 | 5 | 5 | 없음 |
| `rs4_kill3_spareabsent@rs` | 5 | 5 | 5 | 없음 |
| `rs4_none@rs` | 5 | 5 | 5 | 없음 |
| `rs4_none_off@rs` | 5 | 5 | 5 | 없음 |
| `rs4_refuse_gintype@rs` | 3 | 3 | 3 | 없음 |
| `rs4_refuse_nomacro@rs` | 3 | 3 | 3 | 없음 |
| `rs4_refuse_restoreoff1@rs` | 3 | 3 | 3 | 없음 |
| `rs4_refuse_symgin@rs` | 3 | 3 | 3 | 없음 |
