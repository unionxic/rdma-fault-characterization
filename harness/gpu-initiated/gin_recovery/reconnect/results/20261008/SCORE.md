# gin-reconnect 채점 결과

`score.py`가 원자료(`results/20261008/`의 hold별 시행 파일)에서 만들었다. 손으로 고친 값은 없다.

- 예측 파일 sha256: `5f9b8508b814a4c67855b04580713b18cd22d998c454ce97fd9970d6e61d909a`. `PREREG.txt`의 값과 같다.
- 시행 수(모든 hold): 112. 판정한 시행: 110.
- 판정식 원문은 `predictions.csv`, 열과 문법은 `EXPERIMENT.md` 3절.

## 판정 요약

| 예측 | 셀 | n | 맞은 시행(조건별) | 판정 |
|---|---|--:|---|---|
| 8 s 끊김 뒤 로컬 QP 오류가 투명하게 복구됨 (M1a) | `rc_mute8_f1_b@rc` | 10 | 10/10 | 맞음 |
| 소켓이 시간 초과로 닫히고 '모름'으로 분류됨 (M1b) | `rc_mute8_f1_b@rc` | 10 | 10/10 | 맞음 |
| 끊김이 끝난 뒤 1.5 s 안에 다시 연결됨 (M1c) | `rc_mute8_f1_b@rc` | 10 | 10/10 | 맞음 |
| 끊김과 재연결이 장애 전까지 앱에 알려지지 않음 (M1d) | `rc_mute8_f1_b@rc` | 10 | 0/10 | 맞음 |
| 상한 안에 끝나는 끊김 중 상대 QP 오류가 투명하게 복구됨 (M2a) | `rc_mutef3s_b@rc` | 10 | 10/10 | 맞음 |
| 시작 쪽이 재연결을 기다렸고 기다림이 재연결로 끝남 (M2b) | `rc_mutef3s_b@rc` | 10 | 10/10 | 맞음 |
| 상한을 넘는 끊김 중 상대 QP 오류가 '상대 생존 모름'으로 거절됨 (M3a) | `rc_mutef3l_b@rc` | 10 | 10/10 | 맞음 |
| 긴 끊김에서 죽음 원인 문구로 거절된 시행 없음 (M3b) | `rc_mutef3l_b@rc` | 10 | 0/10 | 맞음 |
| 긴 끊김의 거절이 첫 분류 기록 뒤 10.0–11.5 s (M3c) | `rc_mutef3l_b@rc` | 10 | 10/10 | 맞음 |
| 긴 끊김의 거절 시각에 상대가 살아 있음 (M3d) | `rc_mutef3l_b@rc` | 10 | 10/10 | 맞음 |
| 끊김 중 kill된 상대가 재연결 거부(ECONNREFUSED)로 죽음 판정 (M4a) | `rc_mutekill_b@rc` | 10 | 10/10 | 맞음 |
| 끊김 중 kill: '모름' 거절과 복구가 없음 (M4b) | `rc_mutekill_b@rc` | 10 | 0/10, 0/10 | 맞음 |
| 끊김 중 kill의 거절이 첫 분류 기록 뒤 2 s 안 (M4c) | `rc_mutekill_b@rc` | 10 | 10/10 | 맞음 |
| 회귀 셀 여섯 개가 그대로 투명 (G1) | `f1_b@rc`, `f3_b@rc`, `f1g0_b@rc`, `mt256_f1_b@rc`, `bidirf_f1both_b@rc`, `bidirf_sym_b@rc` | 5 / 5 / 5 / 5 / 5 / 5 | 5/5; 5/5; 5/5; 5/5; 5/5; 5/5 | 맞음 |
| 끊김 없는 kill은 죽음 원인으로 거절되고 abort가 돌아옴 (G2) | `f4_b@rc` | 5 | 5/5 | 맞음 |
| 받는 쪽 abort 해제가 그대로 (G3) | `f2rel_b@rc` | 5 | 5/5 | 맞음 |
| 1 s 끊김: 닫힘과 재연결 없이 투명(대조) (C1) | `rc_mute1_f1_b@rc` | 5 | 5/5 | 맞음 |
| 재연결을 끄면 8 s 끊김 뒤 'no helper socket'으로 거절(대조) (C2) | `rc_mute8off_b@rc` | 5 | 5/5 | 맞음 |
| 4 KiB 지연 차이 0.40 µs 이하(대조) (L1) | `lat_rc_on_4k@rc`, `lat_s2r_on_4k@s2r` | 5 / 5 | abs(10.590 - 10.590) <= 0.40 | 맞음 |
| 256 KiB 지연 차이 0.30 µs 이하(대조) (L2) | `lat_rc_on_256k@rc`, `lat_s2r_on_256k@s2r` | 5 / 5 | abs(38.910 - 38.880) <= 0.30 | 맞음 |

## 예측별 세부

### 8 s 끊김 뒤 로컬 QP 오류가 투명하게 복구됨 (M1a): 맞음

- 판정식: `count(transparent_ok == 1) >= 9`
- 셀 `rc_mute8_f1_b@rc`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(transparent_ok == 1)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 소켓이 시간 초과로 닫히고 '모름'으로 분류됨 (M1b): 맞음

- 판정식: `count(sock_close_cause_r0 == "ETIMEDOUT" and sock_close_liveness_r0 == "unknown") >= 9`
- 셀 `rc_mute8_f1_b@rc`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(sock_close_cause_r0 == "ETIMEDOUT" and sock_close_liveness_r0 == "unknown")` = 10/10. 조건을 만족하지 않은 시행: 없음

### 끊김이 끝난 뒤 1.5 s 안에 다시 연결됨 (M1c): 맞음

- 판정식: `count(n_reconnect_r0 >= 1 and 0 <= reconnect_ms_r0 - mute_off_ms_r0 <= 1500) >= 9`
- 셀 `rc_mute8_f1_b@rc`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(n_reconnect_r0 >= 1 and 0 <= reconnect_ms_r0 - mute_off_ms_r0 <= 1500)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 끊김과 재연결이 장애 전까지 앱에 알려지지 않음 (M1d): 맞음

- 판정식: `count(async_before_fault == 1) == 0`
- 셀 `rc_mute8_f1_b@rc`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(async_before_fault == 1)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음

### 상한 안에 끝나는 끊김 중 상대 QP 오류가 투명하게 복구됨 (M2a): 맞음

- 판정식: `count(transparent_ok == 1) >= 9`
- 셀 `rc_mutef3s_b@rc`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(transparent_ok == 1)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 시작 쪽이 재연결을 기다렸고 기다림이 재연결로 끝남 (M2b): 맞음

- 판정식: `count(rc_wait_end_r0 == "reconnected" and 0 < rc_wait_ms_r0 <= 10000) >= 9`
- 셀 `rc_mutef3s_b@rc`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(rc_wait_end_r0 == "reconnected" and 0 < rc_wait_ms_r0 <= 10000)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 상한을 넘는 끊김 중 상대 QP 오류가 '상대 생존 모름'으로 거절됨 (M3a): 맞음

- 판정식: `count(has(decl_r0, "peer liveness unknown")) >= 9`
- 셀 `rc_mutef3l_b@rc`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(has(decl_r0, "peer liveness unknown"))` = 10/10. 조건을 만족하지 않은 시행: 없음

### 긴 끊김에서 죽음 원인 문구로 거절된 시행 없음 (M3b): 맞음

- 판정식: `count(has(decl_r0, "peer's socket shows")) == 0`
- 셀 `rc_mutef3l_b@rc`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(has(decl_r0, "peer's socket shows"))` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음

### 긴 끊김의 거절이 첫 분류 기록 뒤 10.0–11.5 s (M3c): 맞음

- 판정식: `count(10000 <= decl_mono_r0 - q4_mono_r0 <= 11500) >= 9`
- 셀 `rc_mutef3l_b@rc`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(10000 <= decl_mono_r0 - q4_mono_r0 <= 11500)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 긴 끊김의 거절 시각에 상대가 살아 있음 (M3d): 맞음

- 판정식: `count(r1_alive_at_decline == 1) >= 9`
- 셀 `rc_mutef3l_b@rc`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(r1_alive_at_decline == 1)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 끊김 중 kill된 상대가 재연결 거부(ECONNREFUSED)로 죽음 판정 (M4a): 맞음

- 판정식: `count(has(decl_r0, "ECONNREFUSED")) >= 9`
- 셀 `rc_mutekill_b@rc`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(has(decl_r0, "ECONNREFUSED"))` = 10/10. 조건을 만족하지 않은 시행: 없음

### 끊김 중 kill: '모름' 거절과 복구가 없음 (M4b): 맞음

- 판정식: `count(has(decl_r0, "peer liveness unknown")) == 0 and count(transparent_ok == 1) == 0`
- 셀 `rc_mutekill_b@rc`: 판정한 시행 10회, 대입한 식 `0 == 0 and 0 == 0` → 참
  - `count(has(decl_r0, "peer liveness unknown"))` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
  - `count(transparent_ok == 1)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음

### 끊김 중 kill의 거절이 첫 분류 기록 뒤 2 s 안 (M4c): 맞음

- 판정식: `count(decl_mono_r0 - q4_mono_r0 <= 2000) >= 9`
- 셀 `rc_mutekill_b@rc`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(decl_mono_r0 - q4_mono_r0 <= 2000)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 회귀 셀 여섯 개가 그대로 투명 (G1): 맞음

- 판정식: `per cell: count(transparent_ok == 1) == 5`
- 셀 `f1_b@rc`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음
- 셀 `f3_b@rc`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음
- 셀 `f1g0_b@rc`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음
- 셀 `mt256_f1_b@rc`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음
- 셀 `bidirf_f1both_b@rc`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음
- 셀 `bidirf_sym_b@rc`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 끊김 없는 kill은 죽음 원인으로 거절되고 abort가 돌아옴 (G2): 맞음

- 판정식: `count((has(decl_r0, "peer's socket shows FIN") or has(decl_r0, "peer's socket shows ECONNRESET")) and teardown_r0 == "no error") == 5`
- 셀 `f4_b@rc`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count((has(decl_r0, "peer's socket shows FIN") or has(decl_r0, "peer's socket shows ECONNRESET")) and teardown_r0 == "no error")` = 5/5. 조건을 만족하지 않은 시행: 없음

### 받는 쪽 abort 해제가 그대로 (G3): 맞음

- 판정식: `count(teardown_r1 == "no error" and r1rc != 7 and teardown_ms_r1 <= 5000 and r1_outcome == "async_error_kernel_stuck") == 5`
- 셀 `f2rel_b@rc`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(teardown_r1 == "no error" and r1rc != 7 and teardown_ms_r1 <= 5000 and r1_outcome == "async_error_kernel_stuck")` = 5/5. 조건을 만족하지 않은 시행: 없음

### 1 s 끊김: 닫힘과 재연결 없이 투명(대조) (C1): 맞음

- 판정식: `count(transparent_ok == 1 and n_mute_on_r0 >= 1 and n_sock_close_r0 == 0 and n_reconnect_r0 == 0) == 5`
- 셀 `rc_mute1_f1_b@rc`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1 and n_mute_on_r0 >= 1 and n_sock_close_r0 == 0 and n_reconnect_r0 == 0)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 재연결을 끄면 8 s 끊김 뒤 'no helper socket'으로 거절(대조) (C2): 맞음

- 판정식: `count(has(decl_r0, "no helper socket to the peer") and n_reconnect_r0 == 0) == 5`
- 셀 `rc_mute8off_b@rc`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(has(decl_r0, "no helper socket to the peer") and n_reconnect_r0 == 0)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 4 KiB 지연 차이 0.40 µs 이하(대조) (L1): 맞음

- 판정식: `abs(median(lat_p50_us, "lat_rc_on_4k@rc") - median(lat_p50_us, "lat_s2r_on_4k@s2r")) <= 0.40`
- 셀 `lat_rc_on_4k@rc`: 판정한 시행 5회, 대입한 식 `abs(10.590 - 10.590) <= 0.40` → 참

### 256 KiB 지연 차이 0.30 µs 이하(대조) (L2): 맞음

- 판정식: `abs(median(lat_p50_us, "lat_rc_on_256k@rc") - median(lat_p50_us, "lat_s2r_on_256k@s2r")) <= 0.30`
- 셀 `lat_rc_on_256k@rc`: 판정한 시행 5회, 대입한 식 `abs(38.910 - 38.880) <= 0.30` → 참

## 셀별 시행 수와 따로 센 시행

| 셀 | 계획 | 실행 | 판정 | 따로 셈(사유: 시행) |
|---|--:|--:|--:|---|
| `bidirf_f1both_b@rc` | 5 | 5 | 5 | 없음 |
| `bidirf_sym_b@rc` | 5 | 5 | 5 | 없음 |
| `f1_b@rc` | 5 | 5 | 5 | 없음 |
| `f1g0_b@rc` | 5 | 5 | 5 | 없음 |
| `f2rel_b@rc` | 5 | 5 | 5 | 없음 |
| `f3_b@rc` | 5 | 6 | 5 | 드라이버 랑데부 포트 충돌: f3_b_n2 |
| `f4_b@rc` | 5 | 5 | 5 | 없음 |
| `lat_rc_on_256k@rc` | 5 | 5 | 5 | 없음 |
| `lat_rc_on_4k@rc` | 5 | 5 | 5 | 없음 |
| `lat_s2r_on_256k@s2r` | 5 | 5 | 5 | 없음 |
| `lat_s2r_on_4k@s2r` | 5 | 5 | 5 | 없음 |
| `mt256_f1_b@rc` | 5 | 5 | 5 | 없음 |
| `rc_mute1_f1_b@rc` | 5 | 5 | 5 | 없음 |
| `rc_mute8_f1_b@rc` | 10 | 10 | 10 | 없음 |
| `rc_mute8off_b@rc` | 5 | 5 | 5 | 없음 |
| `rc_mutef3l_b@rc` | 10 | 11 | 10 | 드라이버 랑데부 포트 충돌: rc_mutef3l_b_n10 |
| `rc_mutef3s_b@rc` | 10 | 10 | 10 | 없음 |
| `rc_mutekill_b@rc` | 10 | 10 | 10 | 없음 |
