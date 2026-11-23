# nccl-builtin 채점 결과

`score.py`가 원자료(`results/20261009/`의 설정별 시행 파일)에서 만들었다. 손으로 고친 값은 없다.

- 예측 파일 sha256: `d6804c5490ba0d497a44053670bcd804d8403870e659672ddd6bc9cc95f7f515`. `PREREG.txt`의 값과 같다.
- 시행 수(모든 hold): 295. 판정한 시행: 295.
- 판정식 원문은 `predictions.csv`, 열과 문법은 `EXPERIMENT.md` 3절.

## 판정 요약

| 예측 | 셀 | n | 맞은 시행(조건별) | 판정 |
|---|---|--:|---|---|
| 2.32.3 기본: 송신 QP 오류가 rank 0에서 1 s 안에 ncclRemoteError로 올라옴(원본 오류 경로, WR_FLUSH_ERR) (B1) | `sqp@off` | 10 | 10/10 | 맞음 |
| 2.32.3 기본: 수신 QP 오류가 rank 1 자신에게서 1 s 안에 ncclRemoteError로 올라옴 (B2) | `rqp@off` | 10 | 10/10 | 맞음 |
| 2.32.3 기본: 상대 SIGKILL 뒤 받는 중인 생존 rank는 12 s 반복 제한까지 오류를 보지 못함 (B3) | `kill@off` | 10 | 10/10 | 맞음 |
| 2.32.3 기본: 조용한 수신 QP 오류도 rank 1 자신이 1 s 안에 ncclRemoteError로 올림 (B4) | `slbc@off`, `slar@off` | 10 / 10 | 10/10; 10/10 | 맞음 |
| port recovery만 켜면 데이터 경로가 그대로임(원본 오류 경로, 복원력 줄과 복구 동작 없음) (R1) | `sqp@rec` | 5 | 5/5 | 맞음 |
| port failover(와 recovery): 송신 QP 오류를 곧바로 치명으로 판정하고 rank 0에 1 s 안에 ncclRemoteError, 복구 동작 없음 (F1) | `sqp@fo`, `sqp@forec` | 10 / 10 | 10/10; 10/10 | 맞음 |
| port failover(와 recovery): 수신 QP 오류도 rank 1에서 곧바로 치명, 1 s 안에 ncclRemoteError (F2) | `rqp@fo`, `rqp@forec` | 10 / 10 | 10/10; 10/10 | 맞음 |
| port failover(와 recovery): 상대 SIGKILL 뒤 생존 rank는 12 s 반복 제한까지 오류를 보지 못함 (F3) | `kill@fo`, `kill@forec` | 10 / 10 | 10/10; 10/10 | 맞음 |
| port failover(와 recovery): 조용한 수신 QP 오류를 rank 1 자신이 치명으로 판정해 1 s 안에 올림 (F4) | `slbc@fo`, `slbc@forec`, `slar@fo`, `slar@forec` | 10 / 10 / 10 / 10 | 10/10; 10/10; 10/10; 10/10 | 맞음 |
| port failover를 켠 모든 시행에서 두 rank가 연결 때 '넘겨 갈 다른 장치가 없다'고 경고함 (F5) | `sqp@fo`, `sqp@forec`, `rqp@fo`, `rqp@forec`, `kill@fo`, `kill@forec`, `slbc@fo`, `slbc@forec`, `slar@fo`, `slar@forec`, `ovh64k@fo`, `ovh64k@forec`, `ovh16m@fo`, `ovh16m@forec` | 10 / 10 / 10 / 10 / 10 / 10 / 10 / 10 / 10 / 10 / 10 / 10 / 10 / 10 | 0/10; 0/10; 0/10; 0/10; 0/10; 0/10; 0/10; 0/10; 0/10; 0/10; 0/10; 0/10; 0/10; 0/10 | 맞음 |
| 2.32.3의 어느 설정도 네 장애 중 어느 것도 투명하게 만들지 못함 (F6) | `sqp@off`, `sqp@fo`, `sqp@forec`, `rqp@off`, `rqp@fo`, `rqp@forec`, `kill@off`, `kill@fo`, `kill@forec`, `slbc@off`, `slbc@fo`, `slbc@forec`, `slar@off`, `slar@fo`, `slar@forec`, `sqp@rec` | 10 / 10 / 10 / 10 / 10 / 10 / 10 / 10 / 10 / 10 / 10 / 10 / 10 / 10 / 10 / 5 | 0/10; 0/10; 0/10; 0/10; 0/10; 0/10; 0/10; 0/10; 0/10; 0/10; 0/10; 0/10; 0/10; 0/10; 0/10; 0/5 | 맞음 |
| 2.32.3의 어느 시행에서도 장치 실패 표시, QP 교체, 확인 읽기, port recovery가 시작되지 않음 (F7) | `sqp@off`, `sqp@fo`, `sqp@forec`, `rqp@off`, `rqp@fo`, `rqp@forec`, `kill@off`, `kill@fo`, `kill@forec`, `slbc@off`, `slbc@fo`, `slbc@forec`, `slar@off`, `slar@fo`, `slar@forec`, `sqp@rec` | 10 / 10 / 10 / 10 / 10 / 10 / 10 / 10 / 10 / 10 / 10 / 10 / 10 / 10 / 10 / 5 | 0/10; 0/10; 0/10; 0/10; 0/10; 0/10; 0/10; 0/10; 0/10; 0/10; 0/10; 0/10; 0/10; 0/10; 0/10; 0/5 | 맞음 |
| 다중 요청 복구(켬)가 주입한 송신, 수신 QP 오류를 그대로 투명하게 복구함 (S1) | `sqp@s2on`, `rqp@s2on` | 5 / 5 | 5/5; 5/5 | 맞음 |
| 다중 요청 복구 시간 중앙값이 두 셀 모두 1.8–3.0 ms (S2) | `sqp@s2on`, `rqp@s2on` | 5 / 5 | 1.8 <= 2.306 <= 3.0 and 1.8 <= 2.233 <= 3.0 | 맞음 |
| 다중 요청 복구(켬)는 상대 SIGKILL을 OOB 소켓의 FIN으로 알아 1 s 안에 생존 rank에 오류를 올림 (S3) | `kill@s2on` | 5 | 5/5 | 맞음 |
| 다중 요청 복구(켬)는 조용한 오류를 rank 1에서 조용히 둠(1 s 안 오류 없음). 작업은 투명 복구 또는 멈춤 (S4) | `slbc@s2on` | 5 | 5/5 | 맞음 |
| 다중 요청 복구(켬)의 256 KiB all-reduce 조용한 오류는 12 s 반복 제한까지 멈춤 (S5) | `slar@s2on` | 5 | 5/5 | 맞음 |
| 다중 요청 복구 끔: 송신 QP 오류가 rank 0에서 1 s 안에 ncclRemoteError, 복구 없음 (S6) | `sqp@s2off` | 5 | 5/5 | 맞음 |
| 다중 요청 복구 끔: 수신 QP 오류가 rank 1에서 1 s 안에 ncclRemoteError, 복구 없음 (S7) | `rqp@s2off` | 5 | 5/5 | 맞음 |
| 다중 요청 복구 끔: 상대 SIGKILL 뒤 생존 rank는 12 s 반복 제한까지 오류를 보지 못함 (S8) | `kill@s2off` | 5 | 5/5 | 맞음 |
| 다중 요청 복구 끔: rank 1이 오류를 받은 뒤 rank 0이 장애 난 all-reduce를 틀린 결과로 오류 없이 마침 (S9) | `rqp@s2off` | 5 | 5/5 | 맞음 |
| rqp@s2off와 slar@s2on 밖의 어느 셀의 어느 시행도 틀린 결과를 내지 않음(MISMATCH 없음) (I1) | `sqp@off`, `sqp@rec`, `sqp@fo`, `sqp@forec`, `sqp@s2on`, `sqp@s2off`, `rqp@off`, `rqp@fo`, `rqp@forec`, `rqp@s2on`, `kill@off`, `kill@fo`, `kill@forec`, `kill@s2on`, `kill@s2off`, `slbc@off`, `slbc@fo`, `slbc@forec`, `slbc@s2on`, `slar@off`, `slar@fo`, `slar@forec`, `ovh64k@off`, `ovh64k@fo`, `ovh64k@forec`, `ovh64k@s2on`, `ovh64k@s2off`, `ovh16m@off`, `ovh16m@fo`, `ovh16m@forec`, `ovh16m@s2on`, `ovh16m@s2off` | 10 / 5 / 10 / 10 / 5 / 5 / 10 / 10 / 10 / 5 / 10 / 10 / 10 / 5 / 5 / 10 / 10 / 10 / 5 / 10 / 10 / 10 / 10 / 10 / 10 / 10 / 10 / 10 / 10 / 10 / 10 / 10 | 0/10; 0/5; 0/10; 0/10; 0/5; 0/5; 0/10; 0/10; 0/10; 0/5; 0/10; 0/10; 0/10; 0/5; 0/5; 0/10; 0/10; 0/10; 0/5; 0/10; 0/10; 0/10; 0/10; 0/10; 0/10; 0/10; 0/10; 0/10; 0/10; 0/10; 0/10; 0/10 | 맞음 |
| 장애 없는 16 MiB all-reduce: port failover가 rank 0 반복 시간 중앙값을 2 % 넘게 바꾸지 않음 (O1) | `ovh16m@fo`, `ovh16m@off` | 10 / 10 | abs(2.163 - 2.166) <= 0.02 * 2.166 | 맞음 |
| 장애 없는 64 KiB all-reduce: port failover가 5 % 넘게 바꾸지 않음 (O2) | `ovh64k@fo`, `ovh64k@off` | 10 / 10 | abs(0.059 - 0.058) <= 0.05 * 0.058 | 맞음 |
| failover에 port recovery를 더해도 두 크기 모두 2 % 넘게 바뀌지 않음 (O3) | `ovh16m@forec`, `ovh16m@fo`, `ovh64k@forec`, `ovh64k@fo` | 10 / 10 / 10 / 10 | abs(2.161 - 2.163) <= 0.02 * 2.163 and abs(0.058 - 0.059) <= 0.02 * 0.059 | 맞음 |
| 다중 요청 복구 켬이 끔 대비 16 MiB 2 %, 64 KiB 3 % 안 (O4) | `ovh16m@s2on`, `ovh16m@s2off`, `ovh64k@s2on`, `ovh64k@s2off` | 10 / 10 / 10 / 10 | abs(2.267 - 2.264) <= 0.02 * 2.264 and abs(0.054 - 0.052) <= 0.03 * 0.052 | 틀림 |
| 장애 없는 실행은 모두 두 rank가 모든 반복을 bit 단위로 맞게 마침 (O5) | `ovh64k@off`, `ovh64k@fo`, `ovh64k@forec`, `ovh64k@s2on`, `ovh64k@s2off`, `ovh16m@off`, `ovh16m@fo`, `ovh16m@forec`, `ovh16m@s2on`, `ovh16m@s2off` | 10 / 10 / 10 / 10 / 10 / 10 / 10 / 10 / 10 / 10 | 10/10; 10/10; 10/10; 10/10; 10/10; 10/10; 10/10; 10/10; 10/10; 10/10 | 맞음 |

## 예측별 세부

### 2.32.3 기본: 송신 QP 오류가 rank 0에서 1 s 안에 ncclRemoteError로 올라옴(원본 오류 경로, WR_FLUSH_ERR) (B1): 맞음

- 판정식: `count(outcome == "ERROR" and errcode_r0 == "ncclRemoteError" and 0 <= dt_err_r0 <= 1000 and wc_status_r0 == 5 and stock_cqe_r0 >= 1) >= 9`
- 셀 `sqp@off`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(outcome == "ERROR" and errcode_r0 == "ncclRemoteError" and 0 <= dt_err_r0 <= 1000 and wc_status_r0 == 5 and stock_cqe_r0 >= 1)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 2.32.3 기본: 수신 QP 오류가 rank 1 자신에게서 1 s 안에 ncclRemoteError로 올라옴 (B2): 맞음

- 판정식: `count(outcome == "ERROR" and errcode_r1 == "ncclRemoteError" and 0 <= dt_err_r1 <= 1000 and wc_status_r1 == 5 and stock_cqe_r1 >= 1) >= 9`
- 셀 `rqp@off`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(outcome == "ERROR" and errcode_r1 == "ncclRemoteError" and 0 <= dt_err_r1 <= 1000 and wc_status_r1 == 5 and stock_cqe_r1 >= 1)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 2.32.3 기본: 상대 SIGKILL 뒤 받는 중인 생존 rank는 12 s 반복 제한까지 오류를 보지 못함 (B3): 맞음

- 판정식: `count(outcome == "HANG") >= 9`
- 셀 `kill@off`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(outcome == "HANG")` = 10/10. 조건을 만족하지 않은 시행: 없음

### 2.32.3 기본: 조용한 수신 QP 오류도 rank 1 자신이 1 s 안에 ncclRemoteError로 올림 (B4): 맞음

- 판정식: `per cell: count(errcode_r1 == "ncclRemoteError" and 0 <= dt_err_r1 <= 1000 and wc_status_r1 == 5) >= 9`
- 셀 `slbc@off`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(errcode_r1 == "ncclRemoteError" and 0 <= dt_err_r1 <= 1000 and wc_status_r1 == 5)` = 10/10. 조건을 만족하지 않은 시행: 없음
- 셀 `slar@off`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(errcode_r1 == "ncclRemoteError" and 0 <= dt_err_r1 <= 1000 and wc_status_r1 == 5)` = 10/10. 조건을 만족하지 않은 시행: 없음

### port recovery만 켜면 데이터 경로가 그대로임(원본 오류 경로, 복원력 줄과 복구 동작 없음) (R1): 맞음

- 판정식: `count(outcome == "ERROR" and errcode_r0 == "ncclRemoteError" and 0 <= dt_err_r0 <= 1000 and stock_cqe_r0 >= 1 and fatal_nfd_r0 == 0 and single_dev_r0 == 0 and single_dev_r1 == 0 and prec_activity_r0 == 0 and prec_activity_r1 == 0) >= 4`
- 셀 `sqp@rec`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(outcome == "ERROR" and errcode_r0 == "ncclRemoteError" and 0 <= dt_err_r0 <= 1000 and stock_cqe_r0 >= 1 and fatal_nfd_r0 == 0 and single_dev_r0 == 0 and single_dev_r1 == 0 and prec_activity_r0 == 0 and prec_activity_r1 == 0)` = 5/5. 조건을 만족하지 않은 시행: 없음

### port failover(와 recovery): 송신 QP 오류를 곧바로 치명으로 판정하고 rank 0에 1 s 안에 ncclRemoteError, 복구 동작 없음 (F1): 맞음

- 판정식: `per cell: count(outcome == "ERROR" and errcode_r0 == "ncclRemoteError" and 0 <= dt_err_r0 <= 1000 and wc_status_r0 == 5 and fatal_nfd_r0 >= 1 and stock_cqe_r0 == 0 and prec_activity_r0 == 0 and prec_activity_r1 == 0) >= 9`
- 셀 `sqp@fo`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(outcome == "ERROR" and errcode_r0 == "ncclRemoteError" and 0 <= dt_err_r0 <= 1000 and wc_status_r0 == 5 and fatal_nfd_r0 >= 1 and stock_cqe_r0 == 0 and prec_activity_r0 == 0 and prec_activity_r1 == 0)` = 10/10. 조건을 만족하지 않은 시행: 없음
- 셀 `sqp@forec`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(outcome == "ERROR" and errcode_r0 == "ncclRemoteError" and 0 <= dt_err_r0 <= 1000 and wc_status_r0 == 5 and fatal_nfd_r0 >= 1 and stock_cqe_r0 == 0 and prec_activity_r0 == 0 and prec_activity_r1 == 0)` = 10/10. 조건을 만족하지 않은 시행: 없음

### port failover(와 recovery): 수신 QP 오류도 rank 1에서 곧바로 치명, 1 s 안에 ncclRemoteError (F2): 맞음

- 판정식: `per cell: count(outcome == "ERROR" and errcode_r1 == "ncclRemoteError" and 0 <= dt_err_r1 <= 1000 and wc_status_r1 == 5 and fatal_nfd_r1 >= 1 and stock_cqe_r1 == 0 and prec_activity_r0 == 0 and prec_activity_r1 == 0) >= 9`
- 셀 `rqp@fo`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(outcome == "ERROR" and errcode_r1 == "ncclRemoteError" and 0 <= dt_err_r1 <= 1000 and wc_status_r1 == 5 and fatal_nfd_r1 >= 1 and stock_cqe_r1 == 0 and prec_activity_r0 == 0 and prec_activity_r1 == 0)` = 10/10. 조건을 만족하지 않은 시행: 없음
- 셀 `rqp@forec`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(outcome == "ERROR" and errcode_r1 == "ncclRemoteError" and 0 <= dt_err_r1 <= 1000 and wc_status_r1 == 5 and fatal_nfd_r1 >= 1 and stock_cqe_r1 == 0 and prec_activity_r0 == 0 and prec_activity_r1 == 0)` = 10/10. 조건을 만족하지 않은 시행: 없음

### port failover(와 recovery): 상대 SIGKILL 뒤 생존 rank는 12 s 반복 제한까지 오류를 보지 못함 (F3): 맞음

- 판정식: `per cell: count(outcome == "HANG") >= 9`
- 셀 `kill@fo`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(outcome == "HANG")` = 10/10. 조건을 만족하지 않은 시행: 없음
- 셀 `kill@forec`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(outcome == "HANG")` = 10/10. 조건을 만족하지 않은 시행: 없음

### port failover(와 recovery): 조용한 수신 QP 오류를 rank 1 자신이 치명으로 판정해 1 s 안에 올림 (F4): 맞음

- 판정식: `per cell: count(errcode_r1 == "ncclRemoteError" and 0 <= dt_err_r1 <= 1000 and fatal_nfd_r1 >= 1 and prec_activity_r1 == 0) >= 9`
- 셀 `slbc@fo`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(errcode_r1 == "ncclRemoteError" and 0 <= dt_err_r1 <= 1000 and fatal_nfd_r1 >= 1 and prec_activity_r1 == 0)` = 10/10. 조건을 만족하지 않은 시행: 없음
- 셀 `slbc@forec`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(errcode_r1 == "ncclRemoteError" and 0 <= dt_err_r1 <= 1000 and fatal_nfd_r1 >= 1 and prec_activity_r1 == 0)` = 10/10. 조건을 만족하지 않은 시행: 없음
- 셀 `slar@fo`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(errcode_r1 == "ncclRemoteError" and 0 <= dt_err_r1 <= 1000 and fatal_nfd_r1 >= 1 and prec_activity_r1 == 0)` = 10/10. 조건을 만족하지 않은 시행: 없음
- 셀 `slar@forec`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(errcode_r1 == "ncclRemoteError" and 0 <= dt_err_r1 <= 1000 and fatal_nfd_r1 >= 1 and prec_activity_r1 == 0)` = 10/10. 조건을 만족하지 않은 시행: 없음

### port failover를 켠 모든 시행에서 두 rank가 연결 때 '넘겨 갈 다른 장치가 없다'고 경고함 (F5): 맞음

- 판정식: `per cell: count(single_dev_r0 == 0 or single_dev_r1 == 0) == 0`
- 셀 `sqp@fo`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(single_dev_r0 == 0 or single_dev_r1 == 0)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `sqp@forec`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(single_dev_r0 == 0 or single_dev_r1 == 0)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `rqp@fo`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(single_dev_r0 == 0 or single_dev_r1 == 0)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `rqp@forec`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(single_dev_r0 == 0 or single_dev_r1 == 0)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `kill@fo`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(single_dev_r0 == 0 or single_dev_r1 == 0)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `kill@forec`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(single_dev_r0 == 0 or single_dev_r1 == 0)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `slbc@fo`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(single_dev_r0 == 0 or single_dev_r1 == 0)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `slbc@forec`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(single_dev_r0 == 0 or single_dev_r1 == 0)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `slar@fo`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(single_dev_r0 == 0 or single_dev_r1 == 0)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `slar@forec`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(single_dev_r0 == 0 or single_dev_r1 == 0)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `ovh64k@fo`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(single_dev_r0 == 0 or single_dev_r1 == 0)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `ovh64k@forec`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(single_dev_r0 == 0 or single_dev_r1 == 0)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `ovh16m@fo`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(single_dev_r0 == 0 or single_dev_r1 == 0)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `ovh16m@forec`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(single_dev_r0 == 0 or single_dev_r1 == 0)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음

### 2.32.3의 어느 설정도 네 장애 중 어느 것도 투명하게 만들지 못함 (F6): 맞음

- 판정식: `per cell: count(outcome == "TRANSPARENT") == 0`
- 셀 `sqp@off`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(outcome == "TRANSPARENT")` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `sqp@fo`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(outcome == "TRANSPARENT")` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `sqp@forec`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(outcome == "TRANSPARENT")` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `rqp@off`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(outcome == "TRANSPARENT")` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `rqp@fo`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(outcome == "TRANSPARENT")` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `rqp@forec`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(outcome == "TRANSPARENT")` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `kill@off`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(outcome == "TRANSPARENT")` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `kill@fo`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(outcome == "TRANSPARENT")` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `kill@forec`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(outcome == "TRANSPARENT")` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `slbc@off`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(outcome == "TRANSPARENT")` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `slbc@fo`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(outcome == "TRANSPARENT")` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `slbc@forec`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(outcome == "TRANSPARENT")` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `slar@off`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(outcome == "TRANSPARENT")` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `slar@fo`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(outcome == "TRANSPARENT")` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `slar@forec`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(outcome == "TRANSPARENT")` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `sqp@rec`: 판정한 시행 5회, 대입한 식 `0 == 0` → 참
  - `count(outcome == "TRANSPARENT")` = 0/5. 조건을 만족한(예측과 반대인) 시행: 없음

### 2.32.3의 어느 시행에서도 장치 실패 표시, QP 교체, 확인 읽기, port recovery가 시작되지 않음 (F7): 맞음

- 판정식: `per cell: count(prec_activity_r0 > 0 or prec_activity_r1 > 0) == 0`
- 셀 `sqp@off`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(prec_activity_r0 > 0 or prec_activity_r1 > 0)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `sqp@fo`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(prec_activity_r0 > 0 or prec_activity_r1 > 0)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `sqp@forec`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(prec_activity_r0 > 0 or prec_activity_r1 > 0)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `rqp@off`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(prec_activity_r0 > 0 or prec_activity_r1 > 0)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `rqp@fo`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(prec_activity_r0 > 0 or prec_activity_r1 > 0)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `rqp@forec`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(prec_activity_r0 > 0 or prec_activity_r1 > 0)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `kill@off`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(prec_activity_r0 > 0 or prec_activity_r1 > 0)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `kill@fo`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(prec_activity_r0 > 0 or prec_activity_r1 > 0)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `kill@forec`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(prec_activity_r0 > 0 or prec_activity_r1 > 0)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `slbc@off`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(prec_activity_r0 > 0 or prec_activity_r1 > 0)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `slbc@fo`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(prec_activity_r0 > 0 or prec_activity_r1 > 0)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `slbc@forec`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(prec_activity_r0 > 0 or prec_activity_r1 > 0)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `slar@off`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(prec_activity_r0 > 0 or prec_activity_r1 > 0)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `slar@fo`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(prec_activity_r0 > 0 or prec_activity_r1 > 0)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `slar@forec`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(prec_activity_r0 > 0 or prec_activity_r1 > 0)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `sqp@rec`: 판정한 시행 5회, 대입한 식 `0 == 0` → 참
  - `count(prec_activity_r0 > 0 or prec_activity_r1 > 0)` = 0/5. 조건을 만족한(예측과 반대인) 시행: 없음

### 다중 요청 복구(켬)가 주입한 송신, 수신 QP 오류를 그대로 투명하게 복구함 (S1): 맞음

- 판정식: `per cell: count(outcome == "TRANSPARENT" and s2_rec >= 1) == 5`
- 셀 `sqp@s2on`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(outcome == "TRANSPARENT" and s2_rec >= 1)` = 5/5. 조건을 만족하지 않은 시행: 없음
- 셀 `rqp@s2on`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(outcome == "TRANSPARENT" and s2_rec >= 1)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 다중 요청 복구 시간 중앙값이 두 셀 모두 1.8–3.0 ms (S2): 맞음

- 판정식: `1.8 <= median(s2_rec_ms, "sqp@s2on") <= 3.0 and 1.8 <= median(s2_rec_ms, "rqp@s2on") <= 3.0`
- 셀 `sqp@s2on`: 판정한 시행 5회, 대입한 식 `1.8 <= 2.306 <= 3.0 and 1.8 <= 2.233 <= 3.0` → 참

### 다중 요청 복구(켬)는 상대 SIGKILL을 OOB 소켓의 FIN으로 알아 1 s 안에 생존 rank에 오류를 올림 (S3): 맞음

- 판정식: `count(outcome == "ERROR" and nonempty(err_r0) and 0 <= dt_err_r0 <= 1000 and s2_fin_r0 >= 1) == 5`
- 셀 `kill@s2on`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(outcome == "ERROR" and nonempty(err_r0) and 0 <= dt_err_r0 <= 1000 and s2_fin_r0 >= 1)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 다중 요청 복구(켬)는 조용한 오류를 rank 1에서 조용히 둠(1 s 안 오류 없음). 작업은 투명 복구 또는 멈춤 (S4): 맞음

- 판정식: `count(not (nonempty(err_r1) and dt_err_r1 <= 1000) and (outcome == "TRANSPARENT" or outcome == "HANG")) == 5`
- 셀 `slbc@s2on`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(not (nonempty(err_r1) and dt_err_r1 <= 1000) and (outcome == "TRANSPARENT" or outcome == "HANG"))` = 5/5. 조건을 만족하지 않은 시행: 없음

### 다중 요청 복구(켬)의 256 KiB all-reduce 조용한 오류는 12 s 반복 제한까지 멈춤 (S5): 맞음

- 판정식: `count(outcome == "HANG") == 5`
- 셀 `slar@s2on`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(outcome == "HANG")` = 5/5. 조건을 만족하지 않은 시행: 없음

### 다중 요청 복구 끔: 송신 QP 오류가 rank 0에서 1 s 안에 ncclRemoteError, 복구 없음 (S6): 맞음

- 판정식: `count(outcome == "ERROR" and errcode_r0 == "ncclRemoteError" and 0 <= dt_err_r0 <= 1000 and wc_status_r0 == 5 and s2_rec == 0) == 5`
- 셀 `sqp@s2off`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(outcome == "ERROR" and errcode_r0 == "ncclRemoteError" and 0 <= dt_err_r0 <= 1000 and wc_status_r0 == 5 and s2_rec == 0)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 다중 요청 복구 끔: 수신 QP 오류가 rank 1에서 1 s 안에 ncclRemoteError, 복구 없음 (S7): 맞음

- 판정식: `count(errcode_r1 == "ncclRemoteError" and 0 <= dt_err_r1 <= 1000 and wc_status_r1 == 5 and s2_rec == 0) >= 4`
- 셀 `rqp@s2off`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(errcode_r1 == "ncclRemoteError" and 0 <= dt_err_r1 <= 1000 and wc_status_r1 == 5 and s2_rec == 0)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 다중 요청 복구 끔: 상대 SIGKILL 뒤 생존 rank는 12 s 반복 제한까지 오류를 보지 못함 (S8): 맞음

- 판정식: `count(outcome == "HANG") >= 4`
- 셀 `kill@s2off`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(outcome == "HANG")` = 5/5. 조건을 만족하지 않은 시행: 없음

### 다중 요청 복구 끔: rank 1이 오류를 받은 뒤 rank 0이 장애 난 all-reduce를 틀린 결과로 오류 없이 마침 (S9): 맞음

- 판정식: `count(mism_r0 >= 1 and mism_r1 == 0 and errcode_r1 == "ncclRemoteError" and 0 <= dt_err_r1 <= 1000 and dt_err_r1 < dt_mism_r0 and not nonempty(err_r0) and s2_rec == 0) >= 4`
- 셀 `rqp@s2off`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(mism_r0 >= 1 and mism_r1 == 0 and errcode_r1 == "ncclRemoteError" and 0 <= dt_err_r1 <= 1000 and dt_err_r1 < dt_mism_r0 and not nonempty(err_r0) and s2_rec == 0)` = 5/5. 조건을 만족하지 않은 시행: 없음

### rqp@s2off와 slar@s2on 밖의 어느 셀의 어느 시행도 틀린 결과를 내지 않음(MISMATCH 없음) (I1): 맞음

- 판정식: `per cell: count(mism > 0) == 0`
- 셀 `sqp@off`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(mism > 0)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `sqp@rec`: 판정한 시행 5회, 대입한 식 `0 == 0` → 참
  - `count(mism > 0)` = 0/5. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `sqp@fo`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(mism > 0)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `sqp@forec`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(mism > 0)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `sqp@s2on`: 판정한 시행 5회, 대입한 식 `0 == 0` → 참
  - `count(mism > 0)` = 0/5. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `sqp@s2off`: 판정한 시행 5회, 대입한 식 `0 == 0` → 참
  - `count(mism > 0)` = 0/5. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `rqp@off`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(mism > 0)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `rqp@fo`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(mism > 0)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `rqp@forec`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(mism > 0)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `rqp@s2on`: 판정한 시행 5회, 대입한 식 `0 == 0` → 참
  - `count(mism > 0)` = 0/5. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `kill@off`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(mism > 0)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `kill@fo`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(mism > 0)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `kill@forec`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(mism > 0)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `kill@s2on`: 판정한 시행 5회, 대입한 식 `0 == 0` → 참
  - `count(mism > 0)` = 0/5. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `kill@s2off`: 판정한 시행 5회, 대입한 식 `0 == 0` → 참
  - `count(mism > 0)` = 0/5. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `slbc@off`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(mism > 0)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `slbc@fo`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(mism > 0)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `slbc@forec`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(mism > 0)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `slbc@s2on`: 판정한 시행 5회, 대입한 식 `0 == 0` → 참
  - `count(mism > 0)` = 0/5. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `slar@off`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(mism > 0)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `slar@fo`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(mism > 0)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `slar@forec`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(mism > 0)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `ovh64k@off`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(mism > 0)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `ovh64k@fo`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(mism > 0)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `ovh64k@forec`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(mism > 0)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `ovh64k@s2on`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(mism > 0)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `ovh64k@s2off`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(mism > 0)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `ovh16m@off`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(mism > 0)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `ovh16m@fo`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(mism > 0)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `ovh16m@forec`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(mism > 0)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `ovh16m@s2on`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(mism > 0)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음
- 셀 `ovh16m@s2off`: 판정한 시행 10회, 대입한 식 `0 == 0` → 참
  - `count(mism > 0)` = 0/10. 조건을 만족한(예측과 반대인) 시행: 없음

### 장애 없는 16 MiB all-reduce: port failover가 rank 0 반복 시간 중앙값을 2 % 넘게 바꾸지 않음 (O1): 맞음

- 판정식: `abs(median(med_ms_r0, "ovh16m@fo") - median(med_ms_r0, "ovh16m@off")) <= 0.02 * median(med_ms_r0, "ovh16m@off")`
- 셀 `ovh16m@fo`: 판정한 시행 10회, 대입한 식 `abs(2.163 - 2.166) <= 0.02 * 2.166` → 참

### 장애 없는 64 KiB all-reduce: port failover가 5 % 넘게 바꾸지 않음 (O2): 맞음

- 판정식: `abs(median(med_ms_r0, "ovh64k@fo") - median(med_ms_r0, "ovh64k@off")) <= 0.05 * median(med_ms_r0, "ovh64k@off")`
- 셀 `ovh64k@fo`: 판정한 시행 10회, 대입한 식 `abs(0.059 - 0.058) <= 0.05 * 0.058` → 참

### failover에 port recovery를 더해도 두 크기 모두 2 % 넘게 바뀌지 않음 (O3): 맞음

- 판정식: `abs(median(med_ms_r0, "ovh16m@forec") - median(med_ms_r0, "ovh16m@fo")) <= 0.02 * median(med_ms_r0, "ovh16m@fo") and abs(median(med_ms_r0, "ovh64k@forec") - median(med_ms_r0, "ovh64k@fo")) <= 0.02 * median(med_ms_r0, "ovh64k@fo")`
- 셀 `ovh16m@forec`: 판정한 시행 10회, 대입한 식 `abs(2.161 - 2.163) <= 0.02 * 2.163 and abs(0.058 - 0.059) <= 0.02 * 0.059` → 참

### 다중 요청 복구 켬이 끔 대비 16 MiB 2 %, 64 KiB 3 % 안 (O4): 틀림

- 판정식: `abs(median(med_ms_r0, "ovh16m@s2on") - median(med_ms_r0, "ovh16m@s2off")) <= 0.02 * median(med_ms_r0, "ovh16m@s2off") and abs(median(med_ms_r0, "ovh64k@s2on") - median(med_ms_r0, "ovh64k@s2off")) <= 0.03 * median(med_ms_r0, "ovh64k@s2off")`
- 셀 `ovh16m@s2on`: 판정한 시행 10회, 대입한 식 `abs(2.267 - 2.264) <= 0.02 * 2.264 and abs(0.054 - 0.052) <= 0.03 * 0.052` → 거짓

### 장애 없는 실행은 모두 두 rank가 모든 반복을 bit 단위로 맞게 마침 (O5): 맞음

- 판정식: `per cell: count(outcome == "TRANSPARENT") == 10`
- 셀 `ovh64k@off`: 판정한 시행 10회, 대입한 식 `10 == 10` → 참
  - `count(outcome == "TRANSPARENT")` = 10/10. 조건을 만족하지 않은 시행: 없음
- 셀 `ovh64k@fo`: 판정한 시행 10회, 대입한 식 `10 == 10` → 참
  - `count(outcome == "TRANSPARENT")` = 10/10. 조건을 만족하지 않은 시행: 없음
- 셀 `ovh64k@forec`: 판정한 시행 10회, 대입한 식 `10 == 10` → 참
  - `count(outcome == "TRANSPARENT")` = 10/10. 조건을 만족하지 않은 시행: 없음
- 셀 `ovh64k@s2on`: 판정한 시행 10회, 대입한 식 `10 == 10` → 참
  - `count(outcome == "TRANSPARENT")` = 10/10. 조건을 만족하지 않은 시행: 없음
- 셀 `ovh64k@s2off`: 판정한 시행 10회, 대입한 식 `10 == 10` → 참
  - `count(outcome == "TRANSPARENT")` = 10/10. 조건을 만족하지 않은 시행: 없음
- 셀 `ovh16m@off`: 판정한 시행 10회, 대입한 식 `10 == 10` → 참
  - `count(outcome == "TRANSPARENT")` = 10/10. 조건을 만족하지 않은 시행: 없음
- 셀 `ovh16m@fo`: 판정한 시행 10회, 대입한 식 `10 == 10` → 참
  - `count(outcome == "TRANSPARENT")` = 10/10. 조건을 만족하지 않은 시행: 없음
- 셀 `ovh16m@forec`: 판정한 시행 10회, 대입한 식 `10 == 10` → 참
  - `count(outcome == "TRANSPARENT")` = 10/10. 조건을 만족하지 않은 시행: 없음
- 셀 `ovh16m@s2on`: 판정한 시행 10회, 대입한 식 `10 == 10` → 참
  - `count(outcome == "TRANSPARENT")` = 10/10. 조건을 만족하지 않은 시행: 없음
- 셀 `ovh16m@s2off`: 판정한 시행 10회, 대입한 식 `10 == 10` → 참
  - `count(outcome == "TRANSPARENT")` = 10/10. 조건을 만족하지 않은 시행: 없음

## 셀별 시행 수와 따로 센 시행

| 셀 | 계획 | 실행 | 판정 | 따로 셈(사유: 시행) |
|---|--:|--:|--:|---|
| `kill@fo` | 10 | 10 | 10 | 없음 |
| `kill@forec` | 10 | 10 | 10 | 없음 |
| `kill@off` | 10 | 10 | 10 | 없음 |
| `kill@s2off` | 5 | 5 | 5 | 없음 |
| `kill@s2on` | 5 | 5 | 5 | 없음 |
| `ovh16m@fo` | 10 | 10 | 10 | 없음 |
| `ovh16m@forec` | 10 | 10 | 10 | 없음 |
| `ovh16m@off` | 10 | 10 | 10 | 없음 |
| `ovh16m@s2off` | 10 | 10 | 10 | 없음 |
| `ovh16m@s2on` | 10 | 10 | 10 | 없음 |
| `ovh64k@fo` | 10 | 10 | 10 | 없음 |
| `ovh64k@forec` | 10 | 10 | 10 | 없음 |
| `ovh64k@off` | 10 | 10 | 10 | 없음 |
| `ovh64k@s2off` | 10 | 10 | 10 | 없음 |
| `ovh64k@s2on` | 10 | 10 | 10 | 없음 |
| `rqp@fo` | 10 | 10 | 10 | 없음 |
| `rqp@forec` | 10 | 10 | 10 | 없음 |
| `rqp@off` | 10 | 10 | 10 | 없음 |
| `rqp@s2off` | 5 | 5 | 5 | 없음 |
| `rqp@s2on` | 5 | 5 | 5 | 없음 |
| `slar@fo` | 10 | 10 | 10 | 없음 |
| `slar@forec` | 10 | 10 | 10 | 없음 |
| `slar@off` | 10 | 10 | 10 | 없음 |
| `slar@s2on` | 5 | 5 | 5 | 없음 |
| `slbc@fo` | 10 | 10 | 10 | 없음 |
| `slbc@forec` | 10 | 10 | 10 | 없음 |
| `slbc@off` | 10 | 10 | 10 | 없음 |
| `slbc@s2on` | 5 | 5 | 5 | 없음 |
| `sqp@fo` | 10 | 10 | 10 | 없음 |
| `sqp@forec` | 10 | 10 | 10 | 없음 |
| `sqp@off` | 10 | 10 | 10 | 없음 |
| `sqp@rec` | 5 | 5 | 5 | 없음 |
| `sqp@s2off` | 5 | 5 | 5 | 없음 |
| `sqp@s2on` | 5 | 5 | 5 | 없음 |
