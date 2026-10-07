# gin-s2-close 채점 결과

`score.py`가 원자료(`results/20261007/`의 hold별 시행 파일)에서 만들었다. 손으로 고친 값은 없다.

- 예측 파일 sha256: `0b18ee25ccad7200d6d6518cf408fbe2038a3d6b81858c5c223df272c88bb563`. `PREREG.txt`의 값과 같다.
- 시행 수(모든 hold): 198. 판정한 시행: 195. 게이트 미세 시험 결과 줄: 14.
- 판정식과 열은 `EXPERIMENT.md` 3.1–3.2, 판정식 원문은 `predictions.csv`.

## 판정 요약

| 예측 | 셀 | n | 맞은 시행(조건별) | 판정 |
|---|---|--:|---|---|
| 16, 64 스레드 로컬 QP 오류가 최종 빌드에서 투명 (RA1) | `mt16_f1_b@s2`, `mt64_f1_b@s2` | 5 / 5 | 5/5; 5/5 | 맞음 |
| 실제 양방향 동시 시작이 최종 빌드에서 투명 (RA2a) | `bidirf_sym_b@s2` | 5 | 5/5 | 맞음 |
| 동시 시작에서 두 helper가 함께 시작해 한쪽이 양보 (RA2b) | `bidirf_sym_b@s2` | 5 | 5/5 | 맞음 |
| 동시 시작 처리를 끄면 대부분 양쪽 거절(대조) (RA3) | `bidirf_sym_notie_b@s2` | 5 | 1/5, 4/5 | 맞음 |
| 4 KiB 지연: 2단계 켬 − 끔이 0.30–1.20 µs (RA4a) | `lat_s2on_4k@s2`, `lat_s2off_4k@s2` | 5 / 5 | 0.30 <= 10.560 - 10.270 <= 1.20 | 틀림 |
| 256 KiB 지연: 2단계 켬 − 끔이 0.10–1.00 µs (RA4b) | `lat_s2on_256k@s2`, `lat_s2off_256k@s2` | 5 / 5 | 0.10 <= 38.910 - 38.660 <= 1.00 | 맞음 |
| 게이트 미세 시험 14/14 통과 (RA4c) | 게이트 미세 시험 | 14 | 14 == 14 | 맞음 |
| 거절 뒤 받는 쪽 abort가 5 s 안에 돌아옴 (RB1a) | `f2rel_b@s2r` | 10 | 10/10 | 맞음 |
| abort 전에는 받는 쪽 커널이 풀리지 않음 (RB1b) | `f2rel_b@s2r` | 10 | 10/10 | 맞음 |
| 보내는 쪽 결정(원격 접근 오류로 거절)은 그대로 (RB1c) | `f2rel_b@s2r` | 10 | 10/10 | 맞음 |
| burst 받는 쪽 abort가 8 s 안에 돌아옴 (RB2) | `ringf2rel_b@s2r` | 10 | 10/10 | 맞음 |
| abort 플래그를 끄면 받는 쪽 abort가 자기 대기를 기다림(대조) (RB3) | `f2rel_off_b@s2r` | 5 | 0/5 | 틀림 |
| abort 플래그를 이어도 복구 결과는 그대로 (RB4a) | `f1_b@s2r`, `f3_b@s2r`, `f1g0_b@s2r`, `mt256_f1_b@s2r`, `bidirf_f1both_b@s2r` | 5 / 5 / 5 / 5 / 5 | 5/5; 5/5; 5/5; 5/5; 5/5 | 맞음 |
| abort 플래그를 이어도 상대 kill은 거절되고 abort가 돌아옴 (RB4b) | `f4_b@s2r` | 5 | 5/5 | 맞음 |
| 투명 복구를 끄면 플래그를 잇지 않음(대조) (RB5) | `off_f1_b@s2r` | 5 | 5/5 | 맞음 |
| abort 플래그의 4 KiB 지연 비용 0.40 µs 이하(대조) (RB6a) | `lat_s2r_on_4k@s2r`, `lat_s2on_4k@s2` | 5 / 5 | abs(10.560 - 10.560) <= 0.40 | 맞음 |
| abort 플래그의 256 KiB 지연 비용 0.30 µs 이하(대조) (RB6b) | `lat_s2r_on_256k@s2r`, `lat_s2on_256k@s2` | 5 / 5 | abs(38.910 - 38.910) <= 0.30 | 맞음 |
| get이 낀 라운드는 READ 표식으로 거절 (RC1a) | `get_f1_b@s2rget` | 10 | 10/10 | 맞음 |
| get이 낀 라운드: 조용한 실패 0, 투명 복구 1 이하 (RC1b) | `get_f1_b@s2rget` | 10 | 0/10, 0/10 | 맞음 |
| 장애 없는 get 모드는 투명하고 get 데이터가 맞음(대조) (RC2) | `get_none_b@s2rget` | 5 | 5/5 | 맞음 |
| 사본 영역을 끄면 거절되고 조용한 실패 없음(대조) (RC3a) | `mt1024_norescue_b@s2r` | 5 | 5/5, 0/5 | 맞음 |
| 사본 영역을 끈 거절의 사유가 덮인 WQE(대조) (RC3b) | `mt1024_norescue_b@s2r` | 5 | 0/5 | 틀림 |
| 8 s 끊김에서 소켓이 시간 초과로 2.5–7.0 s 안에 닫힘 (RD1a) | `mute8_f1_b@s2r` | 10 | 10/10 | 맞음 |
| 끊김이 다음 장애 전까지 앱에 알려지지 않음 (RD1b) | `mute8_f1_b@s2r` | 10 | 0/10 | 맞음 |
| 끊김 뒤 로컬 QP 오류는 helper 소켓이 없어 거절 (RD1c) | `mute8_f1_b@s2r` | 10 | 10/10 | 맞음 |
| 끊김 뒤 받는 쪽은 비동기 오류를 받지 못함 (RD1d) | `mute8_f1_b@s2r` | 10 | 10/10 | 맞음 |
| 끊김 중 상대 QP 오류를 살아 있는 상대인데 FIN/RST 사유로 거절 (RD2) | `mute_f3_b@s2r` | 10 | 10/10 | 맞음 |
| 1 s 끊김은 소켓을 닫지 않고 복구는 투명(대조) (RD3) | `mute1_f1_b@s2r` | 5 | 5/5 | 맞음 |

## 예측별 세부

### 16, 64 스레드 로컬 QP 오류가 최종 빌드에서 투명 (RA1): 맞음

- 판정식: `per cell: count(transparent_ok == 1) == 5`
- 셀 `mt16_f1_b@s2`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음
- 셀 `mt64_f1_b@s2`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 실제 양방향 동시 시작이 최종 빌드에서 투명 (RA2a): 맞음

- 판정식: `count(transparent_ok == 1) == 5`
- 셀 `bidirf_sym_b@s2`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 동시 시작에서 두 helper가 함께 시작해 한쪽이 양보 (RA2b): 맞음

- 판정식: `count(tie_kept >= 1 and yielded >= 1) >= 3`
- 셀 `bidirf_sym_b@s2`: 판정한 시행 5회, 대입한 식 `5 >= 3` → 참
  - `count(tie_kept >= 1 and yielded >= 1)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 동시 시작 처리를 끄면 대부분 양쪽 거절(대조) (RA3): 맞음

- 판정식: `count(transparent_ok == 1) <= 2 and count(has(decl_r0, "simultaneous recovery from both ends") or has(decl_r1, "simultaneous recovery from both ends")) >= 3`
- 셀 `bidirf_sym_notie_b@s2`: 판정한 시행 5회, 대입한 식 `1 <= 2 and 4 >= 3` → 참
  - `count(transparent_ok == 1)` = 1/5. 조건을 만족한(예측과 반대인) 시행: bidirf_sym_notie_b_n1
  - `count(has(decl_r0, "simultaneous recovery from both ends") or has(decl_r1, "simultaneous recovery from both ends"))` = 4/5. 조건을 만족하지 않은 시행: bidirf_sym_notie_b_n1

### 4 KiB 지연: 2단계 켬 − 끔이 0.30–1.20 µs (RA4a): 틀림

- 판정식: `0.30 <= median(lat_p50_us, "lat_s2on_4k@s2") - median(lat_p50_us, "lat_s2off_4k@s2") <= 1.20`
- 셀 `lat_s2on_4k@s2`: 판정한 시행 5회, 대입한 식 `0.30 <= 10.560 - 10.270 <= 1.20` → 거짓

### 256 KiB 지연: 2단계 켬 − 끔이 0.10–1.00 µs (RA4b): 맞음

- 판정식: `0.10 <= median(lat_p50_us, "lat_s2on_256k@s2") - median(lat_p50_us, "lat_s2off_256k@s2") <= 1.00`
- 셀 `lat_s2on_256k@s2`: 판정한 시행 5회, 대입한 식 `0.10 <= 38.910 - 38.660 <= 1.00` → 참

### 게이트 미세 시험 14/14 통과 (RA4c): 맞음

- 판정식: `gate_pass == 14`
- 셀 ``: 판정한 시행 0회, 대입한 식 `14 == 14` → 참

### 거절 뒤 받는 쪽 abort가 5 s 안에 돌아옴 (RB1a): 맞음

- 판정식: `count(teardown_r1 == "no error" and r1rc != 7 and teardown_ms_r1 <= 5000) >= 9`
- 셀 `f2rel_b@s2r`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(teardown_r1 == "no error" and r1rc != 7 and teardown_ms_r1 <= 5000)` = 10/10. 조건을 만족하지 않은 시행: 없음

### abort 전에는 받는 쪽 커널이 풀리지 않음 (RB1b): 맞음

- 판정식: `count(r1_outcome == "async_error_kernel_stuck") == 10`
- 셀 `f2rel_b@s2r`: 판정한 시행 10회, 대입한 식 `10 == 10` → 참
  - `count(r1_outcome == "async_error_kernel_stuck")` = 10/10. 조건을 만족하지 않은 시행: 없음

### 보내는 쪽 결정(원격 접근 오류로 거절)은 그대로 (RB1c): 맞음

- 판정식: `count(has(decl_r0, "REM_ACCESS")) == 10`
- 셀 `f2rel_b@s2r`: 판정한 시행 10회, 대입한 식 `10 == 10` → 참
  - `count(has(decl_r0, "REM_ACCESS"))` = 10/10. 조건을 만족하지 않은 시행: 없음

### burst 받는 쪽 abort가 8 s 안에 돌아옴 (RB2): 맞음

- 판정식: `count(teardown_r1 == "no error" and r1rc != 7 and teardown_ms_r1 <= 8000) >= 9`
- 셀 `ringf2rel_b@s2r`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(teardown_r1 == "no error" and r1rc != 7 and teardown_ms_r1 <= 8000)` = 10/10. 조건을 만족하지 않은 시행: 없음

### abort 플래그를 끄면 받는 쪽 abort가 자기 대기를 기다림(대조) (RB3): 틀림

- 판정식: `count((r1rc == 7 or teardown_ms_r1 >= 15000) and ua_r1 == 0) == 5`
- 셀 `f2rel_off_b@s2r`: 판정한 시행 5회, 대입한 식 `0 == 5` → 거짓
  - `count((r1rc == 7 or teardown_ms_r1 >= 15000) and ua_r1 == 0)` = 0/5. 조건을 만족하지 않은 시행: f2rel_off_b_n1, f2rel_off_b_n2, f2rel_off_b_n3, f2rel_off_b_n4, f2rel_off_b_n5

### abort 플래그를 이어도 복구 결과는 그대로 (RB4a): 맞음

- 판정식: `per cell: count(transparent_ok == 1) == 5`
- 셀 `f1_b@s2r`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음
- 셀 `f3_b@s2r`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음
- 셀 `f1g0_b@s2r`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음
- 셀 `mt256_f1_b@s2r`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음
- 셀 `bidirf_f1both_b@s2r`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음

### abort 플래그를 이어도 상대 kill은 거절되고 abort가 돌아옴 (RB4b): 맞음

- 판정식: `count(has(decl_r0, "FIN/RST") and teardown_r0 == "no error") == 5`
- 셀 `f4_b@s2r`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(has(decl_r0, "FIN/RST") and teardown_r0 == "no error")` = 5/5. 조건을 만족하지 않은 시행: 없음

### 투명 복구를 끄면 플래그를 잇지 않음(대조) (RB5): 맞음

- 판정식: `count(r0rc == 4 and ua_r0 == 0 and ua_r1 == 0) == 5`
- 셀 `off_f1_b@s2r`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(r0rc == 4 and ua_r0 == 0 and ua_r1 == 0)` = 5/5. 조건을 만족하지 않은 시행: 없음

### abort 플래그의 4 KiB 지연 비용 0.40 µs 이하(대조) (RB6a): 맞음

- 판정식: `abs(median(lat_p50_us, "lat_s2r_on_4k@s2r") - median(lat_p50_us, "lat_s2on_4k@s2")) <= 0.40`
- 셀 `lat_s2r_on_4k@s2r`: 판정한 시행 5회, 대입한 식 `abs(10.560 - 10.560) <= 0.40` → 참

### abort 플래그의 256 KiB 지연 비용 0.30 µs 이하(대조) (RB6b): 맞음

- 판정식: `abs(median(lat_p50_us, "lat_s2r_on_256k@s2r") - median(lat_p50_us, "lat_s2on_256k@s2")) <= 0.30`
- 셀 `lat_s2r_on_256k@s2r`: 판정한 시행 5회, 대입한 식 `abs(38.910 - 38.910) <= 0.30` → 참

### get이 낀 라운드는 READ 표식으로 거절 (RC1a): 맞음

- 판정식: `count(has(decl_r0, "cannot count or re-post") and maskbit(decl_r0, 4)) >= 9`
- 셀 `get_f1_b@s2rget`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(has(decl_r0, "cannot count or re-post") and maskbit(decl_r0, 4))` = 10/10. 조건을 만족하지 않은 시행: 없음

### get이 낀 라운드: 조용한 실패 0, 투명 복구 1 이하 (RC1b): 맞음

- 판정식: `count(silent_bad == 1) == 0 and count(transparent_ok == 1) <= 1`
- 셀 `get_f1_b@s2rget`: 판정한 시행 10회, 대입한 식 `0 == 0 and 0 <= 1` → 참
  - `count(silent_bad == 1)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
  - `count(transparent_ok == 1)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음

### 장애 없는 get 모드는 투명하고 get 데이터가 맞음(대조) (RC2): 맞음

- 판정식: `count(transparent_ok == 1 and get_bad == 0 and get_n == iters) == 5`
- 셀 `get_none_b@s2rget`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1 and get_bad == 0 and get_n == iters)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 사본 영역을 끄면 거절되고 조용한 실패 없음(대조) (RC3a): 맞음

- 판정식: `count(nonempty(decl_r0)) == 5 and count(silent_bad == 1) == 0`
- 셀 `mt1024_norescue_b@s2r`: 판정한 시행 5회, 대입한 식 `5 == 5 and 0 == 0` → 참
  - `count(nonempty(decl_r0))` = 5/5. 조건을 만족하지 않은 시행: 없음
  - `count(silent_bad == 1)` = 0/5. 조건을 만족한(예측과 반대인) 시행: 없음

### 사본 영역을 끈 거절의 사유가 덮인 WQE(대조) (RC3b): 틀림

- 판정식: `count(has(decl_r0, "a WQE to re-post was overwritten")) >= 4`
- 셀 `mt1024_norescue_b@s2r`: 판정한 시행 5회, 대입한 식 `0 >= 4` → 거짓
  - `count(has(decl_r0, "a WQE to re-post was overwritten"))` = 0/5. 조건을 만족하지 않은 시행: mt1024_norescue_b_n1, mt1024_norescue_b_n2, mt1024_norescue_b_n3, mt1024_norescue_b_n4, mt1024_norescue_b_n5

### 8 s 끊김에서 소켓이 시간 초과로 2.5–7.0 s 안에 닫힘 (RD1a): 맞음

- 판정식: `count(sock_close_cause_r0 == "ETIMEDOUT" and 2500 <= sock_close_ms_r0 - mute_on_ms_r0 <= 7000) >= 9`
- 셀 `mute8_f1_b@s2r`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(sock_close_cause_r0 == "ETIMEDOUT" and 2500 <= sock_close_ms_r0 - mute_on_ms_r0 <= 7000)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 끊김이 다음 장애 전까지 앱에 알려지지 않음 (RD1b): 맞음

- 판정식: `count(async_before_fault == 1) == 0`
- 셀 `mute8_f1_b@s2r`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(async_before_fault == 1)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음

### 끊김 뒤 로컬 QP 오류는 helper 소켓이 없어 거절 (RD1c): 맞음

- 판정식: `count(has(decl_r0, "no helper socket to the peer")) >= 9`
- 셀 `mute8_f1_b@s2r`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(has(decl_r0, "no helper socket to the peer"))` = 10/10. 조건을 만족하지 않은 시행: 없음

### 끊김 뒤 받는 쪽은 비동기 오류를 받지 못함 (RD1d): 맞음

- 판정식: `count(r1_async == "none") >= 9`
- 셀 `mute8_f1_b@s2r`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(r1_async == "none")` = 10/10. 조건을 만족하지 않은 시행: 없음

### 끊김 중 상대 QP 오류를 살아 있는 상대인데 FIN/RST 사유로 거절 (RD2): 맞음

- 판정식: `count(has(decl_r0, "RETRY_EXC and the peer's socket shows FIN/RST") and sock_close_cause_r0 == "ETIMEDOUT" and r1_alive_at_decline == 1) >= 9`
- 셀 `mute_f3_b@s2r`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(has(decl_r0, "RETRY_EXC and the peer's socket shows FIN/RST") and sock_close_cause_r0 == "ETIMEDOUT" and r1_alive_at_decline == 1)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 1 s 끊김은 소켓을 닫지 않고 복구는 투명(대조) (RD3): 맞음

- 판정식: `count(transparent_ok == 1 and n_mute_on_r0 >= 1 and n_sock_close_r0 == 0) == 5`
- 셀 `mute1_f1_b@s2r`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1 and n_mute_on_r0 >= 1 and n_sock_close_r0 == 0)` = 5/5. 조건을 만족하지 않은 시행: 없음

## 셀별 시행 수와 따로 센 시행

| 셀 | 계획 | 실행 | 판정 | 따로 셈(사유: 시행) |
|---|--:|--:|--:|---|
| `bidirf_f1both_b@s2r` | 5 | 5 | 5 | 없음 |
| `bidirf_sym_b@s2` | 5 | 5 | 5 | 없음 |
| `bidirf_sym_notie_b@s2` | 5 | 5 | 5 | 없음 |
| `f1_b@s2r` | 5 | 5 | 5 | 없음 |
| `f1g0_b@s2r` | 5 | 5 | 5 | 없음 |
| `f2rel_b@s2r` | 10 | 10 | 10 | 없음 |
| `f2rel_off_b@s2r` | 5 | 5 | 5 | 없음 |
| `f3_b@s2r` | 5 | 5 | 5 | 없음 |
| `f4_b@s2r` | 5 | 5 | 5 | 없음 |
| `get_f1_b@s2rget` | 10 | 10 | 10 | 없음 |
| `get_none_b@s2rget` | 5 | 5 | 5 | 없음 |
| `lat_base_256k@base` | 5 | 5 | 5 | 없음 |
| `lat_base_4k@base` | 5 | 5 | 5 | 없음 |
| `lat_s1off_256k@s1` | 5 | 5 | 5 | 없음 |
| `lat_s1off_4k@s1` | 5 | 5 | 5 | 없음 |
| `lat_s1on_256k@s1` | 5 | 5 | 5 | 없음 |
| `lat_s1on_4k@s1` | 5 | 5 | 5 | 없음 |
| `lat_s2off_256k@s2` | 5 | 5 | 5 | 없음 |
| `lat_s2off_4k@s2` | 5 | 5 | 5 | 없음 |
| `lat_s2on_256k@s2` | 5 | 5 | 5 | 없음 |
| `lat_s2on_4k@s2` | 5 | 6 | 5 | 드라이버 랑데부 포트 충돌: lat_s2on_4k_n4 |
| `lat_s2r_on_256k@s2r` | 5 | 5 | 5 | 없음 |
| `lat_s2r_on_4k@s2r` | 5 | 6 | 5 | 드라이버 랑데부 포트 충돌: lat_s2r_on_4k_n2 |
| `lat_s2sys_256k@var_sys` | 5 | 5 | 5 | 없음 |
| `lat_s2sys_4k@var_sys` | 5 | 5 | 5 | 없음 |
| `mt1024_norescue_b@s2r` | 5 | 5 | 5 | 없음 |
| `mt16_f1_b@s2` | 5 | 5 | 5 | 없음 |
| `mt256_f1_b@s2r` | 5 | 6 | 5 | 드라이버 랑데부 포트 충돌: mt256_f1_b_n5 |
| `mt64_f1_b@s2` | 5 | 5 | 5 | 없음 |
| `mute1_f1_b@s2r` | 5 | 5 | 5 | 없음 |
| `mute8_f1_b@s2r` | 10 | 10 | 10 | 없음 |
| `mute_f3_b@s2r` | 10 | 10 | 10 | 없음 |
| `off_f1_b@s2r` | 5 | 5 | 5 | 없음 |
| `ringf2rel_b@s2r` | 10 | 10 | 10 | 없음 |
