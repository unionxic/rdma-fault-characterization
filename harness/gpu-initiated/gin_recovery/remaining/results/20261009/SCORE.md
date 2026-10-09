# gin-remaining 채점 결과

`score.py`가 원자료(`results/20261009/`의 시행 파일)에서 만들었다. 손으로 고친 값은 없다.

- 예측 파일 sha256: `a63389f26f1f2e1ed9b09efb4d0460e88c1922a4116b189004c7668d51a1cb5b`. `PREREG.txt`의 값과 같다.
- 시행 수(모든 hold): 159. 판정한 시행: 159.
- 판정식 원문은 `predictions.csv`, 열과 문법은 `EXPERIMENT.md` 3절.

## 판정 요약

| 예측 | 셀 | n | 맞은 시행(조건별) | 판정 |
|---|---|--:|---|---|
| 순환하는 세 시작 쪽(0>1, 1>2, 2>0)이 handshake timeout도 거절도 없이 복구되고, 모든 간선이 정상이며, 세 쌍 모두 시작 쪽 복구 줄을 남김 (CY1) | `mr4_cyc_stall@hr` | 10 | 10/10 | 맞음 |
| 순환의 마지막 복구가 첫 라운드 줄 5000 ms 안에 끝남 (CY2) | `mr4_cyc_stall@hr` | 10 | 10/10 | 맞음 |
| 적어도 한 REQ를 다른 라운드의 ACK 기다림 안에서 답함(순환을 끊은 것이 시간 초과가 아니라 새 규칙) (CY3) | `mr4_cyc_stall@hr` | 10 | 10/10 | 맞음 |
| 대조(gin-peer 라이브러리): 순환이 여전히 ACK 한도까지 기다려 라운드 시작 24.3-24.8 s 뒤 handshake timeout으로 거절, 투명 아님 (CY4) | `mr4_cyc_stall@hq` | 5 | 5/5 | 맞음 |
| 순환이 없는 사슬(0>1, 1>2)은 그대로 투명하고 5000 ms 안에 끝남(회귀) (CY5) | `mr4_chain_stall@hr` | 5 | 5/5 | 맞음 |
| rank 3 kill, 모든 받기 대기에 시간 제한 없음: 생존 rank마다 rank 3에서 오는 받기가 그 rank의 죽음 판정 2000-3000 ms 뒤 오류로 풀림 (DG1) | `rm4_kill3_untimed@hr` | 10 | 10/10 | 맞음 |
| 생존 rank마다 word [0]의 degraded 해제 줄이 하나, 죽음 판정 줄 2000-2500 ms 뒤 (DG2) | `rm4_kill3_untimed@hr` | 10 | 10/10 | 맞음 |
| 생존 rank 사이의 상대별 보내기(put + flushAsync(peer) + wait)가 모두 끝나고, 생존 rank의 커널이 모두 끝남 (DG3) | `rm4_kill3_untimed@hr` | 10 | 10/10 | 맞음 |
| 대가: 죽음 2 s 뒤에도 기다리던 생존 rank 사이의 받기도 모두 오류로 풀림(waitSignal은 누구의 신호를 기다리는지 모름) (DG4) | `rm4_kill3_untimed@hr` | 10 | 10/10 | 맞음 |
| 대조(gin-peer 라이브러리): rank 3에서 오는 받기가 풀리지 않고, application이 비동기 오류 15 s 뒤 포기할 때까지 생존 rank의 커널이 돎 (DG5) | `rm4_kill3_untimed@hq` | 5 | 5/5 | 맞음 |
| gin-peer의 셀(받기 한도 10 s)을 hr로: 생존 rank의 보내기는 모두 성공, 받기는 한도가 아니라 degraded 단어로 실패, 생존 rank마다 degraded 줄 (DG6) | `mr4_kill3_peer@hr` | 5 | 5/5 | 맞음 |
| gin-handoff 순서(GIN 실행 뒤 첫 커널 적재, cudaMalloc, 스트림 생성; GPU 가득): 복사가 모두 NIC로 가고 복사 시간 초과 없이 투명하게 복구 (GR1) | `rh_hog_f1_b@hr` | 10 | 10/10 | 맞음 |
| 그래도 CUDA 스트림은 묶여 있었음: 두 rank 모두 새 스트림 확인 복사가 200 ms 안에 하나도 끝나지 않고 GPU 채우기 블록이 하나도 시작하지 않음 (GR2) | `rh_hog_f1_b@hr` | 10 | 10/10 | 맞음 |
| helper의 장치 상태 복사가 하나도 스트림을 쓰지 않음(정리 때 계수) (GR3) | `rh_hog_f1_b@hr` | 10 | 10/10 | 맞음 |
| 대조(gin-peer 라이브러리, 같은 드라이버): 라운드의 복사가 시간을 넘겨 거절, 투명 아님 (GC1) | `rh_hog_f1_b@hq` | 5 | 5/5 | 맞음 |
| hr 안의 대조: NCCL_GIN_TS_COPY_PATH=stream이면 같은 순서에서 복사 시간 초과로 거절 (GC2) | `rh_hog_copystream_f1_b@hr` | 5 | 5/5 | 맞음 |
| GIN 실행 뒤 첫 커널 적재만(cudaMalloc과 스트림은 앞에서): 확인 복사가 묶이고 hq 라운드가 복사 시간 초과로 거절 (GS1) | `rh_hogcall_load_f1_b@hq` | 5 | 5/5 | 맞음 |
| GIN 실행 뒤 cudaMalloc만: 확인 복사가 묶이고 hq 라운드가 복사 시간 초과로 거절 (GS2) | `rh_hogcall_malloc_f1_b@hq` | 5 | 0/5 | 틀림 |
| GIN 실행 뒤 스트림 생성만: 확인 복사가 200 ms 안에 끝나고 hq 라운드가 투명하게 복구 (GS3) | `rh_hogcall_stream_f1_b@hq` | 5 | 5/5 | 맞음 |
| hr은 세 호출 중 어느 하나만 있어도 투명하게 복구 (GS4) | `rh_hogcall_load_f1_b@hr`, `rh_hogcall_malloc_f1_b@hr`, `rh_hogcall_stream_f1_b@hr` | 3 / 3 / 3 | 3/3; 3/3; 3/3 | 맞음 |
| 복구 재현 셀이 그대로 투명 (RG1) | `f1_b@hr`, `f3_b@hr`, `bidirf_sym_b@hr` | 5 / 5 / 5 | 5/5; 5/5; 5/5 | 맞음 |
| 그 라운드들의 장치 상태 복사가 모두 NIC로 감 (RG2) | `f1_b@hr`, `f3_b@hr`, `bidirf_sym_b@hr` | 5 / 5 / 5 | 5/5; 5/5; 5/5 | 맞음 |
| 랭크 2개, 상대 kill: 2 s 안에 peer-dead로 거절, 유일한 상대라 word [0]이 바로 peer-dead로 올라감(degraded 예약 없음) (RG3) | `f4_b@hr` | 5 | 5/5 | 맞음 |
| 랭크 2개, 받기만 하는 rank의 waitSignal이 보내는 쪽 kill 2 s 안에 오류로 풀림 (RG4) | `hd_rxdeath_b@hr` | 5 | 5/5 | 맞음 |
| 원격 접근 오류: rank 0 거절, rank 1 대기 오류 해제, abort 5 s 안 (RG5) | `f2rel_b@hr` | 5 | 5/5 | 맞음 |
| 운영 빌드, 상대 kill: 2 s 안에 거절, 죽음 1, WARN에 정보성 줄 없음 (RG6) | `hdp_kill_b@hrp` | 5 | 5/5 | 맞음 |
| 통계 API가 두 rank에서 라운드 1, 복구 1, 거절 0 (RG7) | `f1_b@hr` | 5 | 5/5 | 맞음 |
| 랭크 4개, 장애 없음과 한 쌍의 로컬 QP 오류가 투명 (RG8) | `mr4_none@hr`, `mr4_f1_01@hr` | 5 / 5 | 5/5; 5/5 | 맞음 |
| 4 KiB 지연: 이 실험의 운영 빌드와 gin-peer 운영 빌드 차이 0.40 µs 이하 (LT1) | `lat_4k@hrp`, `lat_4k@hqp` | 5 / 5 | abs(10.500 - 10.750) <= 0.40 | 맞음 |
| 256 KiB 지연: 차이 0.30 µs 이하 (LT2) | `lat_256k@hrp`, `lat_256k@hqp` | 5 / 5 | abs(38.880 - 38.880) <= 0.30 | 맞음 |
| 두 플랫폼 모두 호스트 원자 연산을 기본으로 지원하지 않음(cudaDevAttrHostNativeAtomicSupported = 0) (HB1) | `hm_bench@hr` | 5 | 5/5 | 맞음 |
| 호스트 매핑 메모리의 원자적 더하기가 장치 메모리보다 400 ns 이상 느림(두 GPU 모두) (HB2) | `hm_bench@hr` | 5 | 5/5 | 맞음 |
| 경합 단계가 정상으로 끝나고 개수 절반의 장치 갱신을 잃지 않음 (HB3) | `hm_bench@hr` | 5 | 5/5 | 맞음 |
| NIC 루프백의 4 B 에폭 쓰기와 SM 64비트 원자 연산: 두 GPU 모두 쓰기 손실, 개수 손실, Dekker 위반, 정지 시간 초과가 없음 (NG1) | `nic_gate@hr` | 5 | 5/5 | 맞음 |

## 예측별 세부

### 순환하는 세 시작 쪽(0>1, 1>2, 2>0)이 handshake timeout도 거절도 없이 복구되고, 모든 간선이 정상이며, 세 쌍 모두 시작 쪽 복구 줄을 남김 (CY1): 맞음

- 판정식: `count(n_hs == 0 and transparent_ok == 1 and n_decl == 0 and has(rec_i, "0-1") and has(rec_i, "1-2") and has(rec_i, "2-0")) >= 9`
- 셀 `mr4_cyc_stall@hr`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(n_hs == 0 and transparent_ok == 1 and n_decl == 0 and has(rec_i, "0-1") and has(rec_i, "1-2") and has(rec_i, "2-0"))` = 10/10. 조건을 만족하지 않은 시행: 없음

### 순환의 마지막 복구가 첫 라운드 줄 5000 ms 안에 끝남 (CY2): 맞음

- 판정식: `count(nonempty(rec_last_after_round_ms) and rec_last_after_round_ms <= 5000) >= 9`
- 셀 `mr4_cyc_stall@hr`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(nonempty(rec_last_after_round_ms) and rec_last_after_round_ms <= 5000)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 적어도 한 REQ를 다른 라운드의 ACK 기다림 안에서 답함(순환을 끊은 것이 시간 초과가 아니라 새 규칙) (CY3): 맞음

- 판정식: `count(n_served >= 1) >= 9`
- 셀 `mr4_cyc_stall@hr`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(n_served >= 1)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 대조(gin-peer 라이브러리): 순환이 여전히 ACK 한도까지 기다려 라운드 시작 24.3-24.8 s 뒤 handshake timeout으로 거절, 투명 아님 (CY4): 맞음

- 판정식: `count(n_hs >= 1 and transparent_ok == 0 and 24300 <= hs_first_after_round_ms <= 24800) >= 4`
- 셀 `mr4_cyc_stall@hq`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(n_hs >= 1 and transparent_ok == 0 and 24300 <= hs_first_after_round_ms <= 24800)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 순환이 없는 사슬(0>1, 1>2)은 그대로 투명하고 5000 ms 안에 끝남(회귀) (CY5): 맞음

- 판정식: `count(transparent_ok == 1 and n_decl == 0 and nonempty(rec_last_after_round_ms) and rec_last_after_round_ms <= 5000) >= 4`
- 셀 `mr4_chain_stall@hr`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(transparent_ok == 1 and n_decl == 0 and nonempty(rec_last_after_round_ms) and rec_last_after_round_ms <= 5000)` = 5/5. 조건을 만족하지 않은 시행: 없음

### rank 3 kill, 모든 받기 대기에 시간 제한 없음: 생존 rank마다 rank 3에서 오는 받기가 그 rank의 죽음 판정 2000-3000 ms 뒤 오류로 풀림 (DG1): 맞음

- 판정식: `count(n_rel_dead == 3 and 2000 <= rel_after_dead_ms_r0 <= 3000 and 2000 <= rel_after_dead_ms_r1 <= 3000 and 2000 <= rel_after_dead_ms_r2 <= 3000) >= 9`
- 셀 `rm4_kill3_untimed@hr`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(n_rel_dead == 3 and 2000 <= rel_after_dead_ms_r0 <= 3000 and 2000 <= rel_after_dead_ms_r1 <= 3000 and 2000 <= rel_after_dead_ms_r2 <= 3000)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 생존 rank마다 word [0]의 degraded 해제 줄이 하나, 죽음 판정 줄 2000-2500 ms 뒤 (DG2): 맞음

- 판정식: `count(n_degraded == 3 and degr_ranks == "r0,r1,r2" and 2000 <= degr_after_dead_ms_r0 <= 2500 and 2000 <= degr_after_dead_ms_r1 <= 2500 and 2000 <= degr_after_dead_ms_r2 <= 2500) >= 9`
- 셀 `rm4_kill3_untimed@hr`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(n_degraded == 3 and degr_ranks == "r0,r1,r2" and 2000 <= degr_after_dead_ms_r0 <= 2500 and 2000 <= degr_after_dead_ms_r1 <= 2500 and 2000 <= degr_after_dead_ms_r2 <= 2500)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 생존 rank 사이의 상대별 보내기(put + flushAsync(peer) + wait)가 모두 끝나고, 생존 rank의 커널이 모두 끝남 (DG3): 맞음

- 판정식: `count(n_surv_edges == 6 and surv_tx_ok == 6 and n_kdone_surv == 3 and n_stuck_surv == 0) >= 9`
- 셀 `rm4_kill3_untimed@hr`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(n_surv_edges == 6 and surv_tx_ok == 6 and n_kdone_surv == 3 and n_stuck_surv == 0)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 대가: 죽음 2 s 뒤에도 기다리던 생존 rank 사이의 받기도 모두 오류로 풀림(waitSignal은 누구의 신호를 기다리는지 모름) (DG4): 맞음

- 판정식: `count(n_rel_surv == 6) >= 9`
- 셀 `rm4_kill3_untimed@hr`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(n_rel_surv == 6)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 대조(gin-peer 라이브러리): rank 3에서 오는 받기가 풀리지 않고, application이 비동기 오류 15 s 뒤 포기할 때까지 생존 rank의 커널이 돎 (DG5): 맞음

- 판정식: `count(n_rel_dead == 0 and n_kdone_surv == 0 and n_stuck_surv == 3 and n_degraded == 0) >= 4`
- 셀 `rm4_kill3_untimed@hq`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(n_rel_dead == 0 and n_kdone_surv == 0 and n_stuck_surv == 3 and n_degraded == 0)` = 5/5. 조건을 만족하지 않은 시행: 없음

### gin-peer의 셀(받기 한도 10 s)을 hr로: 생존 rank의 보내기는 모두 성공, 받기는 한도가 아니라 degraded 단어로 실패, 생존 rank마다 degraded 줄 (DG6): 맞음

- 판정식: `count(n_surv_edges == 6 and surv_tx_failed == 0 and surv_rx_failed == 6 and n_degraded == 3) >= 4`
- 셀 `mr4_kill3_peer@hr`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(n_surv_edges == 6 and surv_tx_failed == 0 and surv_rx_failed == 6 and n_degraded == 3)` = 5/5. 조건을 만족하지 않은 시행: 없음

### gin-handoff 순서(GIN 실행 뒤 첫 커널 적재, cudaMalloc, 스트림 생성; GPU 가득): 복사가 모두 NIC로 가고 복사 시간 초과 없이 투명하게 복구 (GR1): 맞음

- 판정식: `count(transparent_ok == 1 and rec_init_r0 >= 1 and n_copyto_r0 == 0 and n_copyto_r1 == 0 and hog_calls_after_r0 == "load,malloc,stream" and copy_path_r0 == "nic" and copy_path_r1 == "nic") >= 9`
- 셀 `rh_hog_f1_b@hr`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(transparent_ok == 1 and rec_init_r0 >= 1 and n_copyto_r0 == 0 and n_copyto_r1 == 0 and hog_calls_after_r0 == "load,malloc,stream" and copy_path_r0 == "nic" and copy_path_r1 == "nic")` = 10/10. 조건을 만족하지 않은 시행: 없음

### 그래도 CUDA 스트림은 묶여 있었음: 두 rank 모두 새 스트림 확인 복사가 200 ms 안에 하나도 끝나지 않고 GPU 채우기 블록이 하나도 시작하지 않음 (GR2): 맞음

- 판정식: `count(probe_done_200ms_r0 == 0 and probe_done_200ms_r1 == 0 and hog_started_probe_r0 == 0 and hog_started_probe_r1 == 0) >= 9`
- 셀 `rh_hog_f1_b@hr`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(probe_done_200ms_r0 == 0 and probe_done_200ms_r1 == 0 and hog_started_probe_r0 == 0 and hog_started_probe_r1 == 0)` = 10/10. 조건을 만족하지 않은 시행: 없음

### helper의 장치 상태 복사가 하나도 스트림을 쓰지 않음(정리 때 계수) (GR3): 맞음

- 판정식: `count(td_path_r0 == "nic" and td_path_r1 == "nic" and td_stream_copies_r0 == 0 and td_stream_copies_r1 == 0) >= 9`
- 셀 `rh_hog_f1_b@hr`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(td_path_r0 == "nic" and td_path_r1 == "nic" and td_stream_copies_r0 == 0 and td_stream_copies_r1 == 0)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 대조(gin-peer 라이브러리, 같은 드라이버): 라운드의 복사가 시간을 넘겨 거절, 투명 아님 (GC1): 맞음

- 판정식: `count(n_copyto_r0 >= 1 and rec_init_r0 == 0 and transparent_ok == 0) >= 4`
- 셀 `rh_hog_f1_b@hq`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(n_copyto_r0 >= 1 and rec_init_r0 == 0 and transparent_ok == 0)` = 5/5. 조건을 만족하지 않은 시행: 없음

### hr 안의 대조: NCCL_GIN_TS_COPY_PATH=stream이면 같은 순서에서 복사 시간 초과로 거절 (GC2): 맞음

- 판정식: `count(copy_path_r0 == "stream" and n_copyto_r0 >= 1 and rec_init_r0 == 0 and transparent_ok == 0) >= 4`
- 셀 `rh_hog_copystream_f1_b@hr`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(copy_path_r0 == "stream" and n_copyto_r0 >= 1 and rec_init_r0 == 0 and transparent_ok == 0)` = 5/5. 조건을 만족하지 않은 시행: 없음

### GIN 실행 뒤 첫 커널 적재만(cudaMalloc과 스트림은 앞에서): 확인 복사가 묶이고 hq 라운드가 복사 시간 초과로 거절 (GS1): 맞음

- 판정식: `count(hog_calls_after_r0 == "load" and probe_done_200ms_r0 == 0 and n_copyto_r0 >= 1 and transparent_ok == 0) >= 4`
- 셀 `rh_hogcall_load_f1_b@hq`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(hog_calls_after_r0 == "load" and probe_done_200ms_r0 == 0 and n_copyto_r0 >= 1 and transparent_ok == 0)` = 5/5. 조건을 만족하지 않은 시행: 없음

### GIN 실행 뒤 cudaMalloc만: 확인 복사가 묶이고 hq 라운드가 복사 시간 초과로 거절 (GS2): 틀림

- 판정식: `count(hog_calls_after_r0 == "malloc" and probe_done_200ms_r0 == 0 and n_copyto_r0 >= 1 and transparent_ok == 0) >= 4`
- 셀 `rh_hogcall_malloc_f1_b@hq`: 판정한 시행 5회, 대입한 식 `0 >= 4` → 거짓
  - `count(hog_calls_after_r0 == "malloc" and probe_done_200ms_r0 == 0 and n_copyto_r0 >= 1 and transparent_ok == 0)` = 0/5. 조건을 만족하지 않은 시행: rh_hogcall_malloc_f1_b_n1, rh_hogcall_malloc_f1_b_n2, rh_hogcall_malloc_f1_b_n3, rh_hogcall_malloc_f1_b_n4, rh_hogcall_malloc_f1_b_n5

### GIN 실행 뒤 스트림 생성만: 확인 복사가 200 ms 안에 끝나고 hq 라운드가 투명하게 복구 (GS3): 맞음

- 판정식: `count(hog_calls_after_r0 == "stream" and probe_done_200ms_r0 == probe_n_r0 and n_copyto_r0 == 0 and transparent_ok == 1) >= 4`
- 셀 `rh_hogcall_stream_f1_b@hq`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(hog_calls_after_r0 == "stream" and probe_done_200ms_r0 == probe_n_r0 and n_copyto_r0 == 0 and transparent_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음

### hr은 세 호출 중 어느 하나만 있어도 투명하게 복구 (GS4): 맞음

- 판정식: `per cell: count(transparent_ok == 1 and n_copyto_r0 == 0 and n_copyto_r1 == 0) == 3`
- 셀 `rh_hogcall_load_f1_b@hr`: 판정한 시행 3회, 대입한 식 `3 == 3` → 참
  - `count(transparent_ok == 1 and n_copyto_r0 == 0 and n_copyto_r1 == 0)` = 3/3. 조건을 만족하지 않은 시행: 없음
- 셀 `rh_hogcall_malloc_f1_b@hr`: 판정한 시행 3회, 대입한 식 `3 == 3` → 참
  - `count(transparent_ok == 1 and n_copyto_r0 == 0 and n_copyto_r1 == 0)` = 3/3. 조건을 만족하지 않은 시행: 없음
- 셀 `rh_hogcall_stream_f1_b@hr`: 판정한 시행 3회, 대입한 식 `3 == 3` → 참
  - `count(transparent_ok == 1 and n_copyto_r0 == 0 and n_copyto_r1 == 0)` = 3/3. 조건을 만족하지 않은 시행: 없음

### 복구 재현 셀이 그대로 투명 (RG1): 맞음

- 판정식: `per cell: count(transparent_ok == 1) == 5`
- 셀 `f1_b@hr`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음
- 셀 `f3_b@hr`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음
- 셀 `bidirf_sym_b@hr`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 그 라운드들의 장치 상태 복사가 모두 NIC로 감 (RG2): 맞음

- 판정식: `per cell: count(td_path_r0 == "nic" and td_path_r1 == "nic" and td_stream_copies_r0 == 0 and td_stream_copies_r1 == 0) == 5`
- 셀 `f1_b@hr`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(td_path_r0 == "nic" and td_path_r1 == "nic" and td_stream_copies_r0 == 0 and td_stream_copies_r1 == 0)` = 5/5. 조건을 만족하지 않은 시행: 없음
- 셀 `f3_b@hr`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(td_path_r0 == "nic" and td_path_r1 == "nic" and td_stream_copies_r0 == 0 and td_stream_copies_r1 == 0)` = 5/5. 조건을 만족하지 않은 시행: 없음
- 셀 `bidirf_sym_b@hr`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(td_path_r0 == "nic" and td_path_r1 == "nic" and td_stream_copies_r0 == 0 and td_stream_copies_r1 == 0)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 랭크 2개, 상대 kill: 2 s 안에 peer-dead로 거절, 유일한 상대라 word [0]이 바로 peer-dead로 올라감(degraded 예약 없음) (RG3): 맞음

- 판정식: `count(has(declwhy_r0, "the peer's socket shows") and cause_r0 == "peer-dead" and 0 <= decl_after_kill_ms_r0 <= 2000 and teardown_r0 == "no error" and uaerr_why_r0 == "peer-dead") == 5`
- 셀 `f4_b@hr`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(has(declwhy_r0, "the peer's socket shows") and cause_r0 == "peer-dead" and 0 <= decl_after_kill_ms_r0 <= 2000 and teardown_r0 == "no error" and uaerr_why_r0 == "peer-dead")` = 5/5. 조건을 만족하지 않은 시행: 없음

### 랭크 2개, 받기만 하는 rank의 waitSignal이 보내는 쪽 kill 2 s 안에 오류로 풀림 (RG4): 맞음

- 판정식: `count(n_judged_r1 >= 1 and rx_rc == "remote process exited or there was a network error" and 0 <= release_after_kill_ms_r1 <= 2000 and 0 <= async_after_kill_ms_r1 <= 2000 and teardown_r1 == "no error") == 5`
- 셀 `hd_rxdeath_b@hr`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(n_judged_r1 >= 1 and rx_rc == "remote process exited or there was a network error" and 0 <= release_after_kill_ms_r1 <= 2000 and 0 <= async_after_kill_ms_r1 <= 2000 and teardown_r1 == "no error")` = 5/5. 조건을 만족하지 않은 시행: 없음

### 원격 접근 오류: rank 0 거절, rank 1 대기 오류 해제, abort 5 s 안 (RG5): 맞음

- 판정식: `count(has(decl_r0, "REM_ACCESS is not recoverable") and r1_outcome == "device_error" and rx_rc == "remote process exited or there was a network error" and rx_phantom_r1 == 0 and teardown_r1 == "no error" and teardown_ms_r1 <= 5000) == 5`
- 셀 `f2rel_b@hr`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(has(decl_r0, "REM_ACCESS is not recoverable") and r1_outcome == "device_error" and rx_rc == "remote process exited or there was a network error" and rx_phantom_r1 == 0 and teardown_r1 == "no error" and teardown_ms_r1 <= 5000)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 운영 빌드, 상대 kill: 2 s 안에 거절, 죽음 1, WARN에 정보성 줄 없음 (RG6): 맞음

- 판정식: `count(has(decl_r0, "the peer's socket shows") and teardown_r0 == "no error" and rs_deaths_r0 == 1 and 0 <= decl_after_kill_ms_r0 <= 2000 and ts_on_r0 == 0 and ts_on_r1 == 0 and hr_on_r0 == 0 and rs_api_r0 == 1) == 5`
- 셀 `hdp_kill_b@hrp`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(has(decl_r0, "the peer's socket shows") and teardown_r0 == "no error" and rs_deaths_r0 == 1 and 0 <= decl_after_kill_ms_r0 <= 2000 and ts_on_r0 == 0 and ts_on_r1 == 0 and hr_on_r0 == 0 and rs_api_r0 == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 통계 API가 두 rank에서 라운드 1, 복구 1, 거절 0 (RG7): 맞음

- 판정식: `count(rs_api_r0 == 1 and rs_rounds_r0 == 1 and rs_recovered_r0 == 1 and rs_declined_r0 == 0 and rs_rounds_r1 == 1 and rs_recovered_r1 == 1) == 5`
- 셀 `f1_b@hr`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(rs_api_r0 == 1 and rs_rounds_r0 == 1 and rs_recovered_r0 == 1 and rs_declined_r0 == 0 and rs_rounds_r1 == 1 and rs_recovered_r1 == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 랭크 4개, 장애 없음과 한 쌍의 로컬 QP 오류가 투명 (RG8): 맞음

- 판정식: `per cell: count(transparent_ok == 1) == 5`
- 셀 `mr4_none@hr`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음
- 셀 `mr4_f1_01@hr`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 4 KiB 지연: 이 실험의 운영 빌드와 gin-peer 운영 빌드 차이 0.40 µs 이하 (LT1): 맞음

- 판정식: `abs(median(lat_p50_us, "lat_4k@hrp") - median(lat_p50_us, "lat_4k@hqp")) <= 0.40`
- 셀 `lat_4k@hrp`: 판정한 시행 5회, 대입한 식 `abs(10.500 - 10.750) <= 0.40` → 참

### 256 KiB 지연: 차이 0.30 µs 이하 (LT2): 맞음

- 판정식: `abs(median(lat_p50_us, "lat_256k@hrp") - median(lat_p50_us, "lat_256k@hqp")) <= 0.30`
- 셀 `lat_256k@hrp`: 판정한 시행 5회, 대입한 식 `abs(38.880 - 38.880) <= 0.30` → 참

### 두 플랫폼 모두 호스트 원자 연산을 기본으로 지원하지 않음(cudaDevAttrHostNativeAtomicSupported = 0) (HB1): 맞음

- 판정식: `count(host_native_atomic_rain == 0 and host_native_atomic_sunny == 0) == 5`
- 셀 `hm_bench@hr`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(host_native_atomic_rain == 0 and host_native_atomic_sunny == 0)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 호스트 매핑 메모리의 원자적 더하기가 장치 메모리보다 400 ns 이상 느림(두 GPU 모두) (HB2): 맞음

- 판정식: `count(lat_host_atom_ns_rain - lat_dev_atom_ns_rain >= 400 and lat_host_atom_ns_sunny - lat_dev_atom_ns_sunny >= 400) == 5`
- 셀 `hm_bench@hr`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(lat_host_atom_ns_rain - lat_dev_atom_ns_rain >= 400 and lat_host_atom_ns_sunny - lat_dev_atom_ns_sunny >= 400)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 경합 단계가 정상으로 끝나고 개수 절반의 장치 갱신을 잃지 않음 (HB3): 맞음

- 판정식: `count(race_final_low_rain == 0 and race_final_low_sunny == 0 and race_rc_rain == "cudaSuccess" and race_rc_sunny == "cudaSuccess" and race_dev_ops_rain > 0 and race_dev_ops_sunny > 0) == 5`
- 셀 `hm_bench@hr`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(race_final_low_rain == 0 and race_final_low_sunny == 0 and race_rc_rain == "cudaSuccess" and race_rc_sunny == "cudaSuccess" and race_dev_ops_rain > 0 and race_dev_ops_sunny > 0)` = 5/5. 조건을 만족하지 않은 시행: 없음

### NIC 루프백의 4 B 에폭 쓰기와 SM 64비트 원자 연산: 두 GPU 모두 쓰기 손실, 개수 손실, Dekker 위반, 정지 시간 초과가 없음 (NG1): 맞음

- 판정식: `count(ng_result_rain == "PASS" and ng_result_sunny == "PASS" and ng_rounds_rain >= 1000 and ng_rounds_sunny >= 1000) == 5`
- 셀 `nic_gate@hr`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(ng_result_rain == "PASS" and ng_result_sunny == "PASS" and ng_rounds_rain >= 1000 and ng_rounds_sunny >= 1000)` = 5/5. 조건을 만족하지 않은 시행: 없음

## 셀별 시행 수와 따로 센 시행

| 셀 | 계획 | 실행 | 판정 | 따로 셈(사유: 시행) |
|---|--:|--:|--:|---|
| `bidirf_sym_b@hr` | 5 | 5 | 5 | 없음 |
| `f1_b@hr` | 5 | 5 | 5 | 없음 |
| `f2rel_b@hr` | 5 | 5 | 5 | 없음 |
| `f3_b@hr` | 5 | 5 | 5 | 없음 |
| `f4_b@hr` | 5 | 5 | 5 | 없음 |
| `hd_rxdeath_b@hr` | 5 | 5 | 5 | 없음 |
| `hdp_kill_b@hrp` | 5 | 5 | 5 | 없음 |
| `hm_bench@hr` | 5 | 5 | 5 | 없음 |
| `lat_256k@hqp` | 5 | 5 | 5 | 없음 |
| `lat_256k@hrp` | 5 | 5 | 5 | 없음 |
| `lat_4k@hqp` | 5 | 5 | 5 | 없음 |
| `lat_4k@hrp` | 5 | 5 | 5 | 없음 |
| `mr4_chain_stall@hr` | 5 | 5 | 5 | 없음 |
| `mr4_cyc_stall@hq` | 5 | 5 | 5 | 없음 |
| `mr4_cyc_stall@hr` | 10 | 10 | 10 | 없음 |
| `mr4_f1_01@hr` | 5 | 5 | 5 | 없음 |
| `mr4_kill3_peer@hr` | 5 | 5 | 5 | 없음 |
| `mr4_none@hr` | 5 | 5 | 5 | 없음 |
| `nic_gate@hr` | 5 | 5 | 5 | 없음 |
| `rh_hog_copystream_f1_b@hr` | 5 | 5 | 5 | 없음 |
| `rh_hog_f1_b@hq` | 5 | 5 | 5 | 없음 |
| `rh_hog_f1_b@hr` | 10 | 10 | 10 | 없음 |
| `rh_hogcall_load_f1_b@hq` | 5 | 5 | 5 | 없음 |
| `rh_hogcall_load_f1_b@hr` | 3 | 3 | 3 | 없음 |
| `rh_hogcall_malloc_f1_b@hq` | 5 | 5 | 5 | 없음 |
| `rh_hogcall_malloc_f1_b@hr` | 3 | 3 | 3 | 없음 |
| `rh_hogcall_stream_f1_b@hq` | 5 | 5 | 5 | 없음 |
| `rh_hogcall_stream_f1_b@hr` | 3 | 3 | 3 | 없음 |
| `rm4_kill3_untimed@hq` | 5 | 5 | 5 | 없음 |
| `rm4_kill3_untimed@hr` | 10 | 10 | 10 | 없음 |
