# gin-harden 채점 결과

`score.py`가 원자료(`results/20261009/`의 hold별 시행 파일)에서 만들었다. 손으로 고친 값은 없다.

- 예측 파일 sha256: `0e9e3192d74ba9777e78cabbc0b822290e6db07ae83e930d41a066786096b9e0`. `PREREG.txt`의 값과 같다.
- 시행 수(모든 hold): 247. 판정한 시행: 243.
- 판정식 원문은 `predictions.csv`, 열과 문법은 `EXPERIMENT.md` 3절.

## 판정 요약

| 예측 | 셀 | n | 맞은 시행(조건별) | 판정 |
|---|---|--:|---|---|
| 죽은 상대를 바로 거절해 rank 0의 대기가 shrink 전에 오류로 풀리고, 신호 없이 성공한 대기가 없음 (A1) | `hd_shrink_b@hd` | 10 | 10/10 | 맞음 |
| NCCL_SHRINK_ABORT shrink가 1-rank 통신기를 돌려주고 allreduce 결과가 맞음 (A2) | `hd_shrink_b@hd` | 10 | 0/10 | 틀림 |
| 대조(ow 라이브러리): shrink 때 옛 커널이 아직 돎 (A3) | `hd_shrink_b@ow2` | 5 | 5/5 | 맞음 |
| 대조(ow 라이브러리): 마지막 abort가 받는 쪽 대기를 신호 없이 성공으로 풂(또는 shrink가 돌아오지 않음) (A4) | `hd_shrink_b@ow2` | 5 | 5/5 | 맞음 |
| 원격 접근 오류 셀: 받는 쪽 대기가 상대 거절 때 오류로 풀리고 abort가 돌아옴(판정 바뀜) (A5) | `f2rel_b@hd` | 5 | 5/5 | 맞음 |
| 연결 거부 한 번으로는 살아 있는 상대를 죽음으로 보지 않음 (B1) | `hd_ref1_f1_b@hd` | 10 | 10/10 | 맞음 |
| 다음 다시 걸기로 재연결되고 12 s 장애가 투명 (B2) | `hd_ref1_f1_b@hd` | 10 | 10/10 | 맞음 |
| 1 s 이상 떨어진 거부 두 번은 죽음이고 바로 거절과 대기 해제로 드러남 (B3) | `hd_ref2_f1_b@hd` | 10 | 10/10 | 맞음 |
| 틀린 고유값의 HELLO는 거부되고 받아들여지지 않음으로 남으며 죽음 판정이 없음 (B4) | `hd_nonce_f1_b@hd` | 10 | 10/10 | 맞음 |
| 다음 다시 걸기로 끊김 끝 2 s 안에 재연결되고 투명 (B5) | `hd_nonce_f1_b@hd` | 10 | 10/10 | 맞음 |
| 라운드 안의 리셋은 라운드를 취소하고 재연결 뒤 다시 돈 라운드로 투명하게 복구 (B6) | `hd_rround_f1_b@hd` | 10 | 10/10 | 맞음 |
| 대조(ow): 같은 리셋에서 REQ 보내기 실패로 거절 (B7) | `hd_rround_f1_b@ow` | 5 | 5/5 | 맞음 |
| 받기만 하는 rank가 죽은 상대를 2 s 안에 죽음으로 보고 대기가 오류로 풀림 (B8) | `hd_rxdeath_b@hd` | 10 | 10/10 | 맞음 |
| 받기만 하는 rank가 2 s 안에 비동기 오류를 받고 abort가 돌아옴 (B9) | `hd_rxdeath_b@hd` | 10 | 10/10 | 맞음 |
| 대조(ow): 받기만 하는 rank가 자기 15 s 기다림 상한까지 기다림 (B10) | `hd_rxdeath_b@ow` | 5 | 5/5 | 맞음 |
| 정상 종료의 FIN은 BYE 뒤라 떠남으로 남고 죽음 줄이 없음 (B11) | `f1_b@hd`, `f3_b@hd`, `rc_mute8_f1_b@hd` | 5 / 5 / 5 | 5/5; 5/5; 5/5 | 맞음 |
| GPU 전체를 쓰는 커널이 도는 중에도 복구가 투명하고 복사 시간 초과가 없음 (C1) | `hd_hog_f1_b@hd` | 10 | 0/10 | 틀림 |
| 8 s 펌웨어 단계에서 3.0–3.5 s에 감시가 발동해 대기를 오류로 풀고 오류를 드러냄 (C2) | `hd_fwslow_f1_b@hd` | 10 | 10/10 | 맞음 |
| helper가 아직 펌웨어 단계 안이어도 rank 0의 abort가 6 s 안에 돌아옴 (C3) | `hd_fwslow_f1_b@hd` | 10 | 10/10 | 맞음 |
| rank 1이 거절하고 abort가 돌아옴 (C4) | `hd_fwslow_f1_b@hd` | 10 | 10/10 | 맞음 |
| 대조(ow): 같은 8 s를 기다린 뒤 복구 (C5) | `hd_fwslow_f1_b@ow` | 5 | 5/5 | 맞음 |
| 멈춘 복사가 2 s 상한을 넘어 3 s 안에 거절되고 두 rank의 대기가 오류로 끝남 (C6) | `hd_copystall_f1_b@hd` | 10 | 10/10 | 맞음 |
| 두 rank의 abort가 돌아옴 (C7) | `hd_copystall_f1_b@hd` | 10 | 10/10 | 맞음 |
| 시작 쪽 rank 0의 두 번째 QP(네 QP 중) 다시 보내기 계획이 거부되면 어느 rank도 다시 보내지 않음 (D1) | `hd_repost_f1_b@hd` | 10 | 10/10 | 맞음 |
| 두 rank가 거절 (D2) | `hd_repost_f1_b@hd` | 10 | 10/10 | 맞음 |
| 다섯 장애 중 셋은 복구되고 넷째에서 상한(10 s에 3번)으로 거절 (E1) | `hd_esc_f1_b@hd` | 10 | 10/10 | 맞음 |
| rank 0이 오류를 드러내고 rank 1이 상대 거절로 거절 (E2) | `hd_esc_f1_b@hd` | 10 | 10/10 | 맞음 |
| 대조(ow): 다섯 번 모두 복구 (E3) | `hd_esc_f1_b@ow` | 5 | 5/5 | 맞음 |
| 통계 API가 두 rank에서 라운드 1, 복구 1, 거절 0을 셈 (E4) | `f1_b@hd` | 5 | 5/5 | 맞음 |
| kill 뒤 통계 API가 죽음 판정 1, 거절 1을 셈 (E5) | `f4_b@hd` | 5 | 5/5 | 맞음 |
| 복구 재현 셀이 그대로 투명 (R1) | `f1_b@hd`, `f3_b@hd`, `bidirf_sym_b@hd`, `rc_mute8_f1_b@hd` | 5 / 5 / 5 / 5 | 5/5; 5/5; 5/5; 5/5 | 맞음 |
| 상대 QP 오류 뒤 teardown 때 두 rank의 모든 QP가 RTS (R2) | `f3_b@hd` | 5 | 5/5 | 맞음 |
| 끊김 없는 kill이 죽음 원인으로 거절되고 abort가 돌아옴 (R3) | `f4_b@hd` | 5 | 5/5 | 맞음 |
| kill 뒤 2 s 안에 거절(죽음이 바로 드러남) (R4) | `f4_b@hd` | 5 | 5/5 | 맞음 |
| pair-check 동작(좁은 범위 거부, 전체 재실행)이 그대로 (R5) | `pc_dual_f1c0_r1c2_b@hd` | 5 | 5/5 | 맞음 |
| 양쪽 8 s 끊김에서 한 번씩 1.5 s 안에 재연결되고 죽음 줄이 없음 (R6) | `rc_mute8_f1_b@hd` | 5 | 5/5 | 맞음 |
| 끊김 중 kill된 rank 1이 1 s 이상 떨어진 거부 두 번 뒤 죽음으로 거절되고 모름 거절이 없음 (R7) | `rc_mutekill_b@hd` | 5 | 5/5 | 맞음 |
| rank 0이 리셋을 받는 한쪽 끊김: 모름, 죽음 없음, 1.5 s 안 재연결, 투명 (R8) | `ow_r1in_f1_b@hd` | 5 | 5/5 | 맞음 |
| rank 1이 리셋을 받는 한쪽 끊김: 모름, 재연결 기다림, 죽음 없음, 투명 (R9) | `ow_r0in_f1r1_b@hd` | 5 | 5/5 | 맞음 |
| 끊김 중 kill된 rank 0이 1 s 이상 떨어진 확인 접속 거부 두 번 뒤 죽음으로 판정되고 거절 (R10) | `ow_kill0_b@hd` | 5 | 5/5 | 맞음 |
| 거부된 재연결 HELLO가 받아들여지지 않음으로 남고 2 s 안 재연결, 투명 (R11) | `ow_hello_f1_b@hd` | 5 | 5/5 | 맞음 |
| rank 0이 원격 접근 오류를 복구할 수 없다고 거절 (R12) | `f2rel_b@hd` | 5 | 5/5 | 맞음 |
| 4 KiB 지연: 운영 빌드와 gin-oneway 차이 0.40 µs 이하 (P1) | `lat_4k@hdp`, `lat_4k@ow` | 5 / 5 | abs(10.720 - 10.590) <= 0.40 | 맞음 |
| 256 KiB 지연: 운영 빌드와 gin-oneway 차이 0.30 µs 이하 (P2) | `lat_256k@hdp`, `lat_256k@ow` | 5 / 5 | abs(38.910 - 38.910) <= 0.30 | 맞음 |
| 4 KiB 지연: 운영 빌드가 순정 NCCL보다 0.10–1.00 µs 느림 (P3) | `lat_4k@hdp`, `lat_4k@stk` | 5 / 5 | 0.10 <= 10.720 - 9.760 <= 1.00 | 맞음 |
| 256 KiB 지연: 운영 빌드가 순정 NCCL보다 0.10–1.00 µs 느림 (P4) | `lat_256k@hdp`, `lat_256k@stk` | 5 / 5 | 0.10 <= 38.910 - 37.860 <= 1.00 | 틀림 |
| 운영 빌드가 kill된 상대를 2 s 안에 죽음으로 거절하고 abort가 돌아옴 (P5) | `hdp_kill_b@hdp` | 5 | 5/5 | 맞음 |
| 운영 빌드: iptables 8 s 관리망 끊김 뒤 재연결, 죽음과 거절 없음, 투명 (P6) | `hdp_mute_b@hdp` | 5 | 5/5 | 맞음 |
| 운영 빌드는 WARN 수준에서 정보성 복구 줄을 남기지 않음 (P7) | `hdp_kill_b@hdp`, `hdp_mute_b@hdp` | 5 / 5 | 5/5; 5/5 | 맞음 |
| IB 타임아웃 20: 상대 QP 오류의 첫 분류(RETRY_EXC)가 장애 50–70 s 뒤 (T1) | `to20_f3_b@hd` | 5 | 5/5 | 맞음 |
| IB 타임아웃 20: 막는 flush가 그동안 기다리고 100 ms 이하의 한 라운드로 투명 복구 (T2) | `to20_f3_b@hd` | 5 | 5/5 | 맞음 |
| IB 타임아웃 20, 장치 쪽 8 s 시간 제한: flush가 시간 초과를 돌려주고 복구도 거절도 없음 (T3) | `to20_f3_t@hd` | 3 | 3/3 | 맞음 |

## 예측별 세부

### 죽은 상대를 바로 거절해 rank 0의 대기가 shrink 전에 오류로 풀리고, 신호 없이 성공한 대기가 없음 (A1): 맞음

- 판정식: `count(ho_kernel_done_before_shrink == 1 and rx_rc_r0 == "remote process exited or there was a network error" and rx_phantom_r0 == 0) >= 9`
- 셀 `hd_shrink_b@hd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(ho_kernel_done_before_shrink == 1 and rx_rc_r0 == "remote process exited or there was a network error" and rx_phantom_r0 == 0)` = 10/10. 조건을 만족하지 않은 시행: 없음

### NCCL_SHRINK_ABORT shrink가 1-rank 통신기를 돌려주고 allreduce 결과가 맞음 (A2): 틀림

- 판정식: `count(ho_shrink_rc == "no error" and ho_newcomm_nranks == 1 and ho_check_ok == 1) >= 9`
- 셀 `hd_shrink_b@hd`: 판정한 시행 10회, 대입한 식 `0 >= 9` → 거짓
  - `count(ho_shrink_rc == "no error" and ho_newcomm_nranks == 1 and ho_check_ok == 1)` = 0/10. 조건을 만족하지 않은 시행: hd_shrink_b_n1, hd_shrink_b_n3, hd_shrink_b_n4, hd_shrink_b_n5, hd_shrink_b_n6, hd_shrink_b_n7, hd_shrink_b_n8, hd_shrink_b_n9, hd_shrink_b_n10, hd_shrink_b_n11

### 대조(ow 라이브러리): shrink 때 옛 커널이 아직 돎 (A3): 맞음

- 판정식: `count(ho_kernel_done_before_shrink == 0) >= 4`
- 셀 `hd_shrink_b@ow2`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(ho_kernel_done_before_shrink == 0)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 대조(ow 라이브러리): 마지막 abort가 받는 쪽 대기를 신호 없이 성공으로 풂(또는 shrink가 돌아오지 않음) (A4): 맞음

- 판정식: `count(post_abort_rx_phantom_r0 >= 1 or not nonempty(ho_shrink_rc)) >= 4`
- 셀 `hd_shrink_b@ow2`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(post_abort_rx_phantom_r0 >= 1 or not nonempty(ho_shrink_rc))` = 5/5. 조건을 만족하지 않은 시행: 없음

### 원격 접근 오류 셀: 받는 쪽 대기가 상대 거절 때 오류로 풀리고 abort가 돌아옴(판정 바뀜) (A5): 맞음

- 판정식: `count(r1_outcome == "device_error" and rx_rc == "remote process exited or there was a network error" and rx_phantom_r1 == 0 and teardown_r1 == "no error" and teardown_ms_r1 <= 5000) == 5`
- 셀 `f2rel_b@hd`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(r1_outcome == "device_error" and rx_rc == "remote process exited or there was a network error" and rx_phantom_r1 == 0 and teardown_r1 == "no error" and teardown_ms_r1 <= 5000)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 연결 거부 한 번으로는 살아 있는 상대를 죽음으로 보지 않음 (B1): 맞음

- 판정식: `count(n_refused_dial_r0 >= 1 and n_judged_r0 == 0 and n_dead_r0 == 0 and n_dead_r1 == 0) >= 9`
- 셀 `hd_ref1_f1_b@hd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(n_refused_dial_r0 >= 1 and n_judged_r0 == 0 and n_dead_r0 == 0 and n_dead_r1 == 0)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 다음 다시 걸기로 재연결되고 12 s 장애가 투명 (B2): 맞음

- 판정식: `count(n_reconn_r0 == 1 and n_reconn_r1 == 1 and transparent_ok == 1 and not nonempty(decl_r0)) >= 9`
- 셀 `hd_ref1_f1_b@hd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(n_reconn_r0 == 1 and n_reconn_r1 == 1 and transparent_ok == 1 and not nonempty(decl_r0))` = 10/10. 조건을 만족하지 않은 시행: 없음

### 1 s 이상 떨어진 거부 두 번은 죽음이고 바로 거절과 대기 해제로 드러남 (B3): 맞음

- 판정식: `count(n_refused_dial_r0 >= 2 and judged_cause_r0 == "ECONNREFUSED" and refusal_span_ms_r0 >= 1000 and has(decl_r0, "peer judged dead: the peer's socket shows ECONNREFUSED") and uarel_why_r0 == "peer-dead") >= 9`
- 셀 `hd_ref2_f1_b@hd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(n_refused_dial_r0 >= 2 and judged_cause_r0 == "ECONNREFUSED" and refusal_span_ms_r0 >= 1000 and has(decl_r0, "peer judged dead: the peer's socket shows ECONNREFUSED") and uarel_why_r0 == "peer-dead")` = 10/10. 조건을 만족하지 않은 시행: 없음

### 틀린 고유값의 HELLO는 거부되고 받아들여지지 않음으로 남으며 죽음 판정이 없음 (B4): 맞음

- 판정식: `count(n_badnonce_sent_r0 >= 1 and n_nonce_ref_r1 >= 1 and n_notacc_r0 >= 1 and n_dead_r0 == 0 and n_dead_r1 == 0 and n_judged_r0 == 0 and n_judged_r1 == 0) >= 9`
- 셀 `hd_nonce_f1_b@hd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(n_badnonce_sent_r0 >= 1 and n_nonce_ref_r1 >= 1 and n_notacc_r0 >= 1 and n_dead_r0 == 0 and n_dead_r1 == 0 and n_judged_r0 == 0 and n_judged_r1 == 0)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 다음 다시 걸기로 끊김 끝 2 s 안에 재연결되고 투명 (B5): 맞음

- 판정식: `count(n_reconn_r0 == 1 and n_reconn_r1 == 1 and 0 <= reconn_after_unmute_ms_r0 <= 2000 and transparent_ok == 1) >= 9`
- 셀 `hd_nonce_f1_b@hd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(n_reconn_r0 == 1 and n_reconn_r1 == 1 and 0 <= reconn_after_unmute_ms_r0 <= 2000 and transparent_ok == 1)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 라운드 안의 리셋은 라운드를 취소하고 재연결 뒤 다시 돈 라운드로 투명하게 복구 (B6): 맞음

- 판정식: `count(n_cancel_r0 >= 1 and n_dead_r0 == 0 and n_dead_r1 == 0 and rec_init_r0 == 1 and sock_retries_max_r0 == 1 and transparent_ok == 1) >= 9`
- 셀 `hd_rround_f1_b@hd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(n_cancel_r0 >= 1 and n_dead_r0 == 0 and n_dead_r1 == 0 and rec_init_r0 == 1 and sock_retries_max_r0 == 1 and transparent_ok == 1)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 대조(ow): 같은 리셋에서 REQ 보내기 실패로 거절 (B7): 맞음

- 판정식: `count(has(decl_r0, "cannot send REQ") and transparent_ok == 0) >= 4`
- 셀 `hd_rround_f1_b@ow`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(has(decl_r0, "cannot send REQ") and transparent_ok == 0)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 받기만 하는 rank가 죽은 상대를 2 s 안에 죽음으로 보고 대기가 오류로 풀림 (B8): 맞음

- 판정식: `count(n_judged_r1 >= 1 and rx_rc == "remote process exited or there was a network error" and 0 <= release_after_kill_ms_r1 <= 2000) >= 9`
- 셀 `hd_rxdeath_b@hd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(n_judged_r1 >= 1 and rx_rc == "remote process exited or there was a network error" and 0 <= release_after_kill_ms_r1 <= 2000)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 받기만 하는 rank가 2 s 안에 비동기 오류를 받고 abort가 돌아옴 (B9): 맞음

- 판정식: `count(0 <= async_after_kill_ms_r1 <= 2000 and teardown_r1 == "no error") >= 9`
- 셀 `hd_rxdeath_b@hd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(0 <= async_after_kill_ms_r1 <= 2000 and teardown_r1 == "no error")` = 10/10. 조건을 만족하지 않은 시행: 없음

### 대조(ow): 받기만 하는 rank가 자기 15 s 기다림 상한까지 기다림 (B10): 맞음

- 판정식: `count(rx_rc == "timeout" and release_after_kill_ms_r1 >= 10000) >= 4`
- 셀 `hd_rxdeath_b@ow`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(rx_rc == "timeout" and release_after_kill_ms_r1 >= 10000)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 정상 종료의 FIN은 BYE 뒤라 떠남으로 남고 죽음 줄이 없음 (B11): 맞음

- 판정식: `per cell: count(n_dead_r0 == 0 and n_dead_r1 == 0 and n_left_r0 + n_left_r1 >= 1) >= 4`
- 셀 `f1_b@hd`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(n_dead_r0 == 0 and n_dead_r1 == 0 and n_left_r0 + n_left_r1 >= 1)` = 5/5. 조건을 만족하지 않은 시행: 없음
- 셀 `f3_b@hd`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(n_dead_r0 == 0 and n_dead_r1 == 0 and n_left_r0 + n_left_r1 >= 1)` = 5/5. 조건을 만족하지 않은 시행: 없음
- 셀 `rc_mute8_f1_b@hd`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(n_dead_r0 == 0 and n_dead_r1 == 0 and n_left_r0 + n_left_r1 >= 1)` = 5/5. 조건을 만족하지 않은 시행: 없음

### GPU 전체를 쓰는 커널이 도는 중에도 복구가 투명하고 복사 시간 초과가 없음 (C1): 틀림

- 판정식: `count(hog_launch_err_r0 == "cudaSuccess" and hog_blocks_r0 >= hog_sms_r0 and hog_launch_after_launch_ms_r0 < fault_after_launch_r0_ms < hog_launch_after_launch_ms_r0 + 3000 and rec_init_r0 == 1 and transparent_ok == 1 and rs_copy_timeouts_r0 == 0) >= 9`
- 셀 `hd_hog_f1_b@hd`: 판정한 시행 10회, 대입한 식 `0 >= 9` → 거짓
  - `count(hog_launch_err_r0 == "cudaSuccess" and hog_blocks_r0 >= hog_sms_r0 and hog_launch_after_launch_ms_r0 < fault_after_launch_r0_ms < hog_launch_after_launch_ms_r0 + 3000 and rec_init_r0 == 1 and transparent_ok == 1 and rs_copy_timeouts_r0 == 0)` = 0/10. 조건을 만족하지 않은 시행: hd_hog_f1_b_n1, hd_hog_f1_b_n2, hd_hog_f1_b_n3, hd_hog_f1_b_n4, hd_hog_f1_b_n5, hd_hog_f1_b_n6, hd_hog_f1_b_n7, hd_hog_f1_b_n8, hd_hog_f1_b_n9, hd_hog_f1_b_n10

### 8 s 펌웨어 단계에서 3.0–3.5 s에 감시가 발동해 대기를 오류로 풀고 오류를 드러냄 (C2): 맞음

- 판정식: `count(n_fwdog_r0 >= 1 and 3000 <= fwdog_run_ms_r0 <= 3500 and uarel_why_r0 == "fw-watchdog" and r0_async != "none") >= 9`
- 셀 `hd_fwslow_f1_b@hd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(n_fwdog_r0 >= 1 and 3000 <= fwdog_run_ms_r0 <= 3500 and uarel_why_r0 == "fw-watchdog" and r0_async != "none")` = 10/10. 조건을 만족하지 않은 시행: 없음

### helper가 아직 펌웨어 단계 안이어도 rank 0의 abort가 6 s 안에 돌아옴 (C3): 맞음

- 판정식: `count(teardown_r0 == "no error" and teardown_ms_r0 <= 6000 and n_orphan_r0 >= 1) >= 9`
- 셀 `hd_fwslow_f1_b@hd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(teardown_r0 == "no error" and teardown_ms_r0 <= 6000 and n_orphan_r0 >= 1)` = 10/10. 조건을 만족하지 않은 시행: 없음

### rank 1이 거절하고 abort가 돌아옴 (C4): 맞음

- 판정식: `count(nonempty(decl_r1) and teardown_r1 == "no error") >= 9`
- 셀 `hd_fwslow_f1_b@hd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(nonempty(decl_r1) and teardown_r1 == "no error")` = 10/10. 조건을 만족하지 않은 시행: 없음

### 대조(ow): 같은 8 s를 기다린 뒤 복구 (C5): 맞음

- 판정식: `count(transparent_ok == 1 and rec_total_us_r0 >= 8000000) >= 4`
- 셀 `hd_fwslow_f1_b@ow`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(transparent_ok == 1 and rec_total_us_r0 >= 8000000)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 멈춘 복사가 2 s 상한을 넘어 3 s 안에 거절되고 두 rank의 대기가 오류로 끝남 (C6): 맞음

- 판정식: `count(n_copyto_r0 >= 1 and rs_copy_timeouts_r0 >= 1 and 0 <= decl_after_q4_ms_r0 <= 3000 and tx_rc == "remote process exited or there was a network error" and rx_rc == "remote process exited or there was a network error") >= 9`
- 셀 `hd_copystall_f1_b@hd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(n_copyto_r0 >= 1 and rs_copy_timeouts_r0 >= 1 and 0 <= decl_after_q4_ms_r0 <= 3000 and tx_rc == "remote process exited or there was a network error" and rx_rc == "remote process exited or there was a network error")` = 10/10. 조건을 만족하지 않은 시행: 없음

### 두 rank의 abort가 돌아옴 (C7): 맞음

- 판정식: `count(teardown_r0 == "no error" and teardown_r1 == "no error") >= 9`
- 셀 `hd_copystall_f1_b@hd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(teardown_r0 == "no error" and teardown_r1 == "no error")` = 10/10. 조건을 만족하지 않은 시행: 없음

### 시작 쪽 rank 0의 두 번째 QP(네 QP 중) 다시 보내기 계획이 거부되면 어느 rank도 다시 보내지 않음 (D1): 맞음

- 판정식: `count(n_plan_rej_r0 >= 1 and plan_rej_qp_r0 == 1 and plan_rej_total_r0 >= 2 and n_rec_r0 == 0 and n_rec_r1 == 0) >= 9`
- 셀 `hd_repost_f1_b@hd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(n_plan_rej_r0 >= 1 and plan_rej_qp_r0 == 1 and plan_rej_total_r0 >= 2 and n_rec_r0 == 0 and n_rec_r1 == 0)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 두 rank가 거절 (D2): 맞음

- 판정식: `count(nonempty(decl_r0) and nonempty(decl_r1)) >= 9`
- 셀 `hd_repost_f1_b@hd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(nonempty(decl_r0) and nonempty(decl_r1))` = 10/10. 조건을 만족하지 않은 시행: 없음

### 다섯 장애 중 셋은 복구되고 넷째에서 상한(10 s에 3번)으로 거절 (E1): 맞음

- 판정식: `count(rec_init_r0 == 3 and n_esc_r0 == 1 and has(decl_r0, "escalation: more than 3 recovery rounds within 10000 ms") and rs_escalations_r0 == 1 and rs_recovered_r0 == 3) >= 9`
- 셀 `hd_esc_f1_b@hd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(rec_init_r0 == 3 and n_esc_r0 == 1 and has(decl_r0, "escalation: more than 3 recovery rounds within 10000 ms") and rs_escalations_r0 == 1 and rs_recovered_r0 == 3)` = 10/10. 조건을 만족하지 않은 시행: 없음

### rank 0이 오류를 드러내고 rank 1이 상대 거절로 거절 (E2): 맞음

- 판정식: `count(r0_async != "none" and has(decl_r1, "the peer declined")) >= 9`
- 셀 `hd_esc_f1_b@hd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(r0_async != "none" and has(decl_r1, "the peer declined"))` = 10/10. 조건을 만족하지 않은 시행: 없음

### 대조(ow): 다섯 번 모두 복구 (E3): 맞음

- 판정식: `count(rec_init_r0 == 5 and transparent_ok == 1) >= 4`
- 셀 `hd_esc_f1_b@ow`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(rec_init_r0 == 5 and transparent_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 통계 API가 두 rank에서 라운드 1, 복구 1, 거절 0을 셈 (E4): 맞음

- 판정식: `count(rs_api_r0 == 1 and rs_rounds_r0 == 1 and rs_recovered_r0 == 1 and rs_declined_r0 == 0 and rs_api_r1 == 1 and rs_rounds_r1 == 1 and rs_recovered_r1 == 1) == 5`
- 셀 `f1_b@hd`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(rs_api_r0 == 1 and rs_rounds_r0 == 1 and rs_recovered_r0 == 1 and rs_declined_r0 == 0 and rs_api_r1 == 1 and rs_rounds_r1 == 1 and rs_recovered_r1 == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음

### kill 뒤 통계 API가 죽음 판정 1, 거절 1을 셈 (E5): 맞음

- 판정식: `count(rs_deaths_r0 == 1 and rs_declined_r0 == 1) == 5`
- 셀 `f4_b@hd`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(rs_deaths_r0 == 1 and rs_declined_r0 == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 복구 재현 셀이 그대로 투명 (R1): 맞음

- 판정식: `per cell: count(transparent_ok == 1) == 5`
- 셀 `f1_b@hd`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음
- 셀 `f3_b@hd`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음
- 셀 `bidirf_sym_b@hd`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음
- 셀 `rc_mute8_f1_b@hd`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 상대 QP 오류 뒤 teardown 때 두 rank의 모든 QP가 RTS (R2): 맞음

- 판정식: `count(n_notrts_r0 == 0 and n_notrts_r1 == 0) == 5`
- 셀 `f3_b@hd`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(n_notrts_r0 == 0 and n_notrts_r1 == 0)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 끊김 없는 kill이 죽음 원인으로 거절되고 abort가 돌아옴 (R3): 맞음

- 판정식: `count((has(decl_r0, "the peer's socket shows FIN") or has(decl_r0, "the peer's socket shows ECONNREFUSED")) and teardown_r0 == "no error") == 5`
- 셀 `f4_b@hd`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count((has(decl_r0, "the peer's socket shows FIN") or has(decl_r0, "the peer's socket shows ECONNREFUSED")) and teardown_r0 == "no error")` = 5/5. 조건을 만족하지 않은 시행: 없음

### kill 뒤 2 s 안에 거절(죽음이 바로 드러남) (R4): 맞음

- 판정식: `count(0 <= decl_after_kill_ms_r0 <= 2000) == 5`
- 셀 `f4_b@hd`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(0 <= decl_after_kill_ms_r0 <= 2000)` = 5/5. 조건을 만족하지 않은 시행: 없음

### pair-check 동작(좁은 범위 거부, 전체 재실행)이 그대로 (R5): 맞음

- 판정식: `count(transparent_ok == 1 and n_refused_r1 >= 1 and n_rerun_r0 >= 1 and n_notrts_r0 == 0 and n_notrts_r1 == 0) == 5`
- 셀 `pc_dual_f1c0_r1c2_b@hd`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1 and n_refused_r1 >= 1 and n_rerun_r0 >= 1 and n_notrts_r0 == 0 and n_notrts_r1 == 0)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 양쪽 8 s 끊김에서 한 번씩 1.5 s 안에 재연결되고 죽음 줄이 없음 (R6): 맞음

- 판정식: `count(n_reconn_r0 == 1 and n_reconn_r1 == 1 and 0 <= reconn_after_unmute_ms_r0 <= 1500 and n_dead_r0 == 0 and n_dead_r1 == 0) == 5`
- 셀 `rc_mute8_f1_b@hd`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(n_reconn_r0 == 1 and n_reconn_r1 == 1 and 0 <= reconn_after_unmute_ms_r0 <= 1500 and n_dead_r0 == 0 and n_dead_r1 == 0)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 끊김 중 kill된 rank 1이 1 s 이상 떨어진 거부 두 번 뒤 죽음으로 거절되고 모름 거절이 없음 (R7): 맞음

- 판정식: `count(has(decl_r0, "the peer's socket shows ECONNREFUSED") and not has(decl_r0, "unknown") and n_refused_dial_r0 >= 2 and refusal_span_ms_r0 >= 1000) == 5`
- 셀 `rc_mutekill_b@hd`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(has(decl_r0, "the peer's socket shows ECONNREFUSED") and not has(decl_r0, "unknown") and n_refused_dial_r0 >= 2 and refusal_span_ms_r0 >= 1000)` = 5/5. 조건을 만족하지 않은 시행: 없음

### rank 0이 리셋을 받는 한쪽 끊김: 모름, 죽음 없음, 1.5 s 안 재연결, 투명 (R8): 맞음

- 판정식: `count(close1_cause_r0 == "ECONNRESET" and close1_lv_r0 == "unknown" and n_dead_r0 == 0 and n_dead_r1 == 0 and n_reconn_r0 == 1 and 0 <= reconn_after_unmute_ms_r0 <= 1500 and transparent_ok == 1) == 5`
- 셀 `ow_r1in_f1_b@hd`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(close1_cause_r0 == "ECONNRESET" and close1_lv_r0 == "unknown" and n_dead_r0 == 0 and n_dead_r1 == 0 and n_reconn_r0 == 1 and 0 <= reconn_after_unmute_ms_r0 <= 1500 and transparent_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음

### rank 1이 리셋을 받는 한쪽 끊김: 모름, 재연결 기다림, 죽음 없음, 투명 (R9): 맞음

- 판정식: `count(close1_lv_r1 == "unknown" and wait_end_r1 == "reconnected" and 0 <= reconn_after_unmute_ms_r1 <= 1500 and n_dead_r0 == 0 and n_dead_r1 == 0 and transparent_ok == 1) == 5`
- 셀 `ow_r0in_f1r1_b@hd`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(close1_lv_r1 == "unknown" and wait_end_r1 == "reconnected" and 0 <= reconn_after_unmute_ms_r1 <= 1500 and n_dead_r0 == 0 and n_dead_r1 == 0 and transparent_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 끊김 중 kill된 rank 0이 1 s 이상 떨어진 확인 접속 거부 두 번 뒤 죽음으로 판정되고 거절 (R10): 맞음

- 판정식: `count(n_probe_ref_r1 >= 2 and judged_cause_r1 == "ECONNREFUSED" and judged_ms_r1 >= mute_off_ms_r1 and refusal_span_ms_r1 >= 1000 and has(decl_r1, "the peer's socket shows ECONNREFUSED") and not has(decl_r1, "unknown")) == 5`
- 셀 `ow_kill0_b@hd`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(n_probe_ref_r1 >= 2 and judged_cause_r1 == "ECONNREFUSED" and judged_ms_r1 >= mute_off_ms_r1 and refusal_span_ms_r1 >= 1000 and has(decl_r1, "the peer's socket shows ECONNREFUSED") and not has(decl_r1, "unknown"))` = 5/5. 조건을 만족하지 않은 시행: 없음

### 거부된 재연결 HELLO가 받아들여지지 않음으로 남고 2 s 안 재연결, 투명 (R11): 맞음

- 판정식: `count(n_refuse_test_r1 >= 1 and n_notacc_r0 >= 1 and n_dead_r0 == 0 and n_dead_r1 == 0 and n_reconn_r0 == 1 and 0 <= reconn_after_unmute_ms_r0 <= 2000 and transparent_ok == 1) == 5`
- 셀 `ow_hello_f1_b@hd`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(n_refuse_test_r1 >= 1 and n_notacc_r0 >= 1 and n_dead_r0 == 0 and n_dead_r1 == 0 and n_reconn_r0 == 1 and 0 <= reconn_after_unmute_ms_r0 <= 2000 and transparent_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음

### rank 0이 원격 접근 오류를 복구할 수 없다고 거절 (R12): 맞음

- 판정식: `count(has(decl_r0, "REM_ACCESS is not recoverable")) == 5`
- 셀 `f2rel_b@hd`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(has(decl_r0, "REM_ACCESS is not recoverable"))` = 5/5. 조건을 만족하지 않은 시행: 없음

### 4 KiB 지연: 운영 빌드와 gin-oneway 차이 0.40 µs 이하 (P1): 맞음

- 판정식: `abs(median(lat_p50_us, "lat_4k@hdp") - median(lat_p50_us, "lat_4k@ow")) <= 0.40`
- 셀 `lat_4k@hdp`: 판정한 시행 5회, 대입한 식 `abs(10.720 - 10.590) <= 0.40` → 참

### 256 KiB 지연: 운영 빌드와 gin-oneway 차이 0.30 µs 이하 (P2): 맞음

- 판정식: `abs(median(lat_p50_us, "lat_256k@hdp") - median(lat_p50_us, "lat_256k@ow")) <= 0.30`
- 셀 `lat_256k@hdp`: 판정한 시행 5회, 대입한 식 `abs(38.910 - 38.910) <= 0.30` → 참

### 4 KiB 지연: 운영 빌드가 순정 NCCL보다 0.10–1.00 µs 느림 (P3): 맞음

- 판정식: `0.10 <= median(lat_p50_us, "lat_4k@hdp") - median(lat_p50_us, "lat_4k@stk") <= 1.00`
- 셀 `lat_4k@hdp`: 판정한 시행 5회, 대입한 식 `0.10 <= 10.720 - 9.760 <= 1.00` → 참

### 256 KiB 지연: 운영 빌드가 순정 NCCL보다 0.10–1.00 µs 느림 (P4): 틀림

- 판정식: `0.10 <= median(lat_p50_us, "lat_256k@hdp") - median(lat_p50_us, "lat_256k@stk") <= 1.00`
- 셀 `lat_256k@hdp`: 판정한 시행 5회, 대입한 식 `0.10 <= 38.910 - 37.860 <= 1.00` → 거짓

### 운영 빌드가 kill된 상대를 2 s 안에 죽음으로 거절하고 abort가 돌아옴 (P5): 맞음

- 판정식: `count(has(decl_r0, "the peer's socket shows") and teardown_r0 == "no error" and rs_deaths_r0 == 1 and 0 <= decl_after_kill_ms_r0 <= 2000) == 5`
- 셀 `hdp_kill_b@hdp`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(has(decl_r0, "the peer's socket shows") and teardown_r0 == "no error" and rs_deaths_r0 == 1 and 0 <= decl_after_kill_ms_r0 <= 2000)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 운영 빌드: iptables 8 s 관리망 끊김 뒤 재연결, 죽음과 거절 없음, 투명 (P6): 맞음

- 판정식: `count(transparent_ok == 1 and rs_reconnects_r0 >= 1 and rs_reconnects_r1 >= 1 and rs_deaths_r0 == 0 and rs_deaths_r1 == 0 and not nonempty(decl_r0) and not nonempty(decl_r1)) == 5`
- 셀 `hdp_mute_b@hdp`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1 and rs_reconnects_r0 >= 1 and rs_reconnects_r1 >= 1 and rs_deaths_r0 == 0 and rs_deaths_r1 == 0 and not nonempty(decl_r0) and not nonempty(decl_r1))` = 5/5. 조건을 만족하지 않은 시행: 없음

### 운영 빌드는 WARN 수준에서 정보성 복구 줄을 남기지 않음 (P7): 맞음

- 판정식: `per cell: count(ts_on_r0 == 0 and ts_on_r1 == 0 and rs_api_r0 == 1 and rs_contexts_r0 >= 1) == 5`
- 셀 `hdp_kill_b@hdp`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(ts_on_r0 == 0 and ts_on_r1 == 0 and rs_api_r0 == 1 and rs_contexts_r0 >= 1)` = 5/5. 조건을 만족하지 않은 시행: 없음
- 셀 `hdp_mute_b@hdp`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(ts_on_r0 == 0 and ts_on_r1 == 0 and rs_api_r0 == 1 and rs_contexts_r0 >= 1)` = 5/5. 조건을 만족하지 않은 시행: 없음

### IB 타임아웃 20: 상대 QP 오류의 첫 분류(RETRY_EXC)가 장애 50–70 s 뒤 (T1): 맞음

- 판정식: `count(50000 <= q4_after_fault_ms_r0 <= 70000 and has(q4_class_r0, "RETRY_EXC")) == 5`
- 셀 `to20_f3_b@hd`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(50000 <= q4_after_fault_ms_r0 <= 70000 and has(q4_class_r0, "RETRY_EXC"))` = 5/5. 조건을 만족하지 않은 시행: 없음

### IB 타임아웃 20: 막는 flush가 그동안 기다리고 100 ms 이하의 한 라운드로 투명 복구 (T2): 맞음

- 판정식: `count(rec_init_r0 == 1 and transparent_ok == 1 and rec_total_us_r0 <= 100000) >= 4`
- 셀 `to20_f3_b@hd`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(rec_init_r0 == 1 and transparent_ok == 1 and rec_total_us_r0 <= 100000)` = 5/5. 조건을 만족하지 않은 시행: 없음

### IB 타임아웃 20, 장치 쪽 8 s 시간 제한: flush가 시간 초과를 돌려주고 복구도 거절도 없음 (T3): 맞음

- 판정식: `count(tx_rc == "timeout" and rec_init_r0 == 0 and not nonempty(decl_r0) and n_dump_r0 >= 1) == 3`
- 셀 `to20_f3_t@hd`: 판정한 시행 3회, 대입한 식 `3 == 3` → 참
  - `count(tx_rc == "timeout" and rec_init_r0 == 0 and not nonempty(decl_r0) and n_dump_r0 >= 1)` = 3/3. 조건을 만족하지 않은 시행: 없음

## 셀별 시행 수와 따로 센 시행

| 셀 | 계획 | 실행 | 판정 | 따로 셈(사유: 시행) |
|---|--:|--:|--:|---|
| `bidirf_sym_b@hd` | 5 | 5 | 5 | 없음 |
| `f1_b@hd` | 5 | 5 | 5 | 없음 |
| `f2rel_b@hd` | 5 | 5 | 5 | 없음 |
| `f3_b@hd` | 5 | 5 | 5 | 없음 |
| `f4_b@hd` | 5 | 5 | 5 | 없음 |
| `hd_copystall_f1_b@hd` | 10 | 11 | 10 | 드라이버 랑데부 포트 충돌: hd_copystall_f1_b_n2 |
| `hd_esc_f1_b@hd` | 10 | 10 | 10 | 없음 |
| `hd_esc_f1_b@ow` | 5 | 5 | 5 | 없음 |
| `hd_fwslow_f1_b@hd` | 10 | 10 | 10 | 없음 |
| `hd_fwslow_f1_b@ow` | 5 | 6 | 5 | 드라이버 랑데부 포트 충돌: hd_fwslow_f1_b_n4 |
| `hd_hog_f1_b@hd` | 10 | 10 | 10 | 없음 |
| `hd_nonce_f1_b@hd` | 10 | 10 | 10 | 없음 |
| `hd_ref1_f1_b@hd` | 10 | 10 | 10 | 없음 |
| `hd_ref2_f1_b@hd` | 10 | 10 | 10 | 없음 |
| `hd_repost_f1_b@hd` | 10 | 10 | 10 | 없음 |
| `hd_rround_f1_b@hd` | 10 | 10 | 10 | 없음 |
| `hd_rround_f1_b@ow` | 5 | 5 | 5 | 없음 |
| `hd_rxdeath_b@hd` | 10 | 10 | 10 | 없음 |
| `hd_rxdeath_b@ow` | 5 | 5 | 5 | 없음 |
| `hd_shrink_b@hd` | 10 | 11 | 10 | 드라이버 랑데부 포트 충돌: hd_shrink_b_n2 |
| `hd_shrink_b@ow2` | 5 | 5 | 5 | 없음 |
| `hdp_kill_b@hdp` | 5 | 5 | 5 | 없음 |
| `hdp_mute_b@hdp` | 5 | 5 | 5 | 없음 |
| `lat_256k@hdp` | 5 | 5 | 5 | 없음 |
| `lat_256k@ow` | 5 | 5 | 5 | 없음 |
| `lat_256k@stk` | 5 | 5 | 5 | 없음 |
| `lat_4k@hdp` | 5 | 5 | 5 | 없음 |
| `lat_4k@ow` | 5 | 5 | 5 | 없음 |
| `lat_4k@stk` | 5 | 5 | 5 | 없음 |
| `ow_hello_f1_b@hd` | 5 | 5 | 5 | 없음 |
| `ow_kill0_b@hd` | 5 | 5 | 5 | 없음 |
| `ow_r0in_f1r1_b@hd` | 5 | 5 | 5 | 없음 |
| `ow_r1in_f1_b@hd` | 5 | 5 | 5 | 없음 |
| `pc_dual_f1c0_r1c2_b@hd` | 5 | 6 | 5 | 드라이버 랑데부 포트 충돌: pc_dual_f1c0_r1c2_b_n5 |
| `rc_mute8_f1_b@hd` | 5 | 5 | 5 | 없음 |
| `rc_mutekill_b@hd` | 5 | 5 | 5 | 없음 |
| `to20_f3_b@hd` | 5 | 5 | 5 | 없음 |
| `to20_f3_t@hd` | 3 | 3 | 3 | 없음 |
