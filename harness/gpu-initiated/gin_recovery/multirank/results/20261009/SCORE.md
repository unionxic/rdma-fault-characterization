# gin-multirank 채점 결과

`score.py`가 원자료(`results/20261009/`의 hold별 시행 파일)에서 만들었다. 손으로 고친 값은 없다.

- 예측 파일 sha256: `3a35b6dba9b99cde8b0d4086ad5b87ad9d0826175f625dea86d725fc192a90ee`. `PREREG.txt`의 값과 같다.
- 시행 수(모든 hold): 137. 판정한 시행: 135.
- 판정식 원문은 `predictions.csv`, 열과 문법은 `EXPERIMENT.md` 3절.

## 판정 요약

| 예측 | 셀 | n | 맞은 시행(조건별) | 판정 |
|---|---|--:|---|---|
| 랭크 4개(GPU마다 프로세스 2개)가 통신기와 문맥 12개의 devComm을 만들고, 네 랭크 모두 투명 복구가 켜짐 (I1) | `mr4_none@hd` | 10 | 10/10 | 맞음 |
| GPU 하나를 두 프로세스의 커널이 나눠 써도 교착 없이 간선 12개가 모두 정확히 전달됨 (I2) | `mr4_none@hd` | 10 | 10/10 | 맞음 |
| 장애가 없으면 복구 라운드, 거절, 감시 줄이 없음 (I3) | `mr4_none@hd` | 10 | 10/10 | 맞음 |
| 랭크 3개: 투명하고 랭크마다 게이트 QP 12개(대조) (I4) | `mr3_none@hd` | 5 | 5/5 | 맞음 |
| 새 드라이버를 랭크 2개로 돌리면 투명(대조) (I5) | `mr2_none@hd` | 5 | 5/5 | 맞음 |
| 상대별 flush도 장애 없이 투명(대조) (I6) | `mr4_none_peer@hd` | 5 | 5/5 | 맞음 |
| 간선 0>1의 로컬 QP 오류를 그 QP 하나만 다루는 라운드 하나로 복구 (A1) | `mr4_f1_01@hd` | 10 | 10/10 | 맞음 |
| 간선 0>1의 로컬 QP 오류 뒤에도 간선 12개 모두 투명 (A2) | `mr4_f1_01@hd` | 10 | 10/10 | 맞음 |
| 라운드를 거친 QP는 그 쌍뿐이고, 훅이 건드린 나머지 두 QP는 끝까지 ERR (A3) | `mr4_f1_01@hd` | 10 | 10/10 | 맞음 |
| 같은 GPU의 두 프로세스 사이(NIC loopback) 간선 0>2의 로컬 QP 오류도 쌍 범위 라운드로 투명하게 복구 (B1) | `mr4_f1_02@hd` | 10 | 10/10 | 맞음 |
| 간선 0>2: 라운드를 거친 QP는 그 쌍뿐이고 나머지 두 QP는 ERR (B2) | `mr4_f1_02@hd` | 10 | 10/10 | 맞음 |
| 상대 QP 오류(RETRY_EXC)를 쌍 범위 라운드 하나로 투명하게 복구 (C1) | `mr4_f3_01@hd` | 10 | 10/10 | 맞음 |
| 간선 0>1이 묶인 약 3.6 s 동안 rank 0의 다른 두 간선이 각각 100번 이상 진행 (C2) | `mr4_f3_01@hd` | 10 | 10/10 | 맞음 |
| 상대 QP 오류: 라운드를 거친 QP는 그 쌍뿐이고 rank 1의 나머지 두 QP는 ERR (C3) | `mr4_f3_01@hd` | 10 | 10/10 | 맞음 |
| 상대 QP 오류의 첫 분류 기록이 훅 3.0-4.5 s 뒤 (C4) | `mr4_f3_01@hd` | 10 | 10/10 | 맞음 |
| 겹치지 않는 두 쌍의 동시 장애가 독립된 두 라운드로 투명하게 복구 (D1) | `mr4_f1_01_23@hd` | 10 | 10/10 | 맞음 |
| 겹치지 않는 두 쌍: 라운드를 거친 QP는 두 쌍뿐 (D2) | `mr4_f1_01_23@hd` | 10 | 10/10 | 맞음 |
| 두 시작 쪽이 같은 응답 쪽(rank 0)으로 동시에 와도 둘 다 투명하게 복구 (E1) | `mr4_f1_10_30@hd` | 10 | 10/10 | 맞음 |
| rank 0의 helper가 두 응답 라운드를 차례로 처리(겹침 없음) (E2) | `mr4_f1_10_30@hd` | 10 | 10/10 | 맞음 |
| 두 시작 쪽: 라운드를 거친 QP는 두 쌍뿐 (E3) | `mr4_f1_10_30@hd` | 10 | 10/10 | 맞음 |
| rank 0의 모든 문맥 장애를 상대별 전체 범위 라운드 세 번으로 복구 (F1) | `mr4_f1all0@hd` | 10 | 10/10 | 맞음 |
| rank 0의 모든 문맥 장애 뒤에도 간선 12개 모두 투명 (F2) | `mr4_f1all0@hd` | 10 | 10/10 | 맞음 |
| 세 라운드가 겹치지 않고, rank 0과 각 상대 사이의 모든 QP가 라운드 한 번을 거쳐 RTS (F3) | `mr4_f1all0@hd` | 10 | 10/10 | 맞음 |
| 복구 셀에서 라운드 상한, 펌웨어 단계와 복사의 상한 초과, 소켓으로 취소된 라운드, 죽음 판정이 없음 (R1) | `mr4_f1_01@hd`, `mr4_f1_02@hd`, `mr4_f3_01@hd`, `mr4_f1_01_23@hd`, `mr4_f1_10_30@hd`, `mr4_f1all0@hd` | 10 / 10 / 10 / 10 / 10 / 10 | 10/10; 10/10; 10/10; 10/10; 10/10; 10/10 | 맞음 |
| rank 3 kill 뒤 살아남은 세 랭크가 소켓으로 rank 3의 죽음을 바로 판정하고 rank 3만 거절(문맥 전체 flush) (K1) | `mr4_kill3@hd` | 10 | 10/10 | 맞음 |
| 그 거절이 kill 0–2 s 뒤 (K2) | `mr4_kill3@hd` | 10 | 10/10 | 맞음 |
| 문맥 전체 flush에서는 거절 뒤 살아남은 랭크 사이의 간선 6개도 모두 오류로 멈춤 (K3) | `mr4_kill3@hd` | 10 | 10/10 | 맞음 |
| 상대별 flush에서도 rank 3만 거절 (K4) | `mr4_kill3_peer@hd` | 10 | 10/10 | 맞음 |
| 상대별 flush: 거절 뒤 살아남은 랭크 사이의 받는 쪽 6개는 모두 오류, 보내는 쪽 6개는 끝까지 성공 (K5) | `mr4_kill3_peer@hd` | 10 | 10/10 | 맞음 |
| 살아남은 세 랭크의 앱이 모두 통신기 비동기 오류를 봄 (K6) | `mr4_kill3@hd`, `mr4_kill3_peer@hd` | 10 / 10 | 10/10; 10/10 | 맞음 |
| 거절은 rank 3으로 가는 QP 12개만 닫음 (K7) | `mr4_kill3@hd`, `mr4_kill3_peer@hd` | 10 / 10 | 10/10; 10/10 | 맞음 |
| 순환하는 세 시작 쪽이 서로를 기다려 handshake timeout 거절이 생기고 투명하지 않음 (Y1) | `mr4_cyc_stall@hd` | 5 | 5/5 | 맞음 |
| 첫 handshake timeout이 라운드 시작 24.3-24.8 s 뒤 (Y2) | `mr4_cyc_stall@hd` | 5 | 5/5 | 맞음 |
| 그 한도 전에는 어떤 복구도 끝나지 않고(첫 복구가 첫 라운드 24 s 이상 뒤) 감시 줄도 없음 (Y3) | `mr4_cyc_stall@hd` | 5 | 5/5 | 맞음 |
| 순환이 없는 사슬은 첫 라운드 5 s 안에 두 라운드가 모두 끝나고 투명(대조) (Z1) | `mr4_chain_stall@hd` | 5 | 5/5 | 맞음 |
| 사슬에서 rank 1이 rank 0의 쌍 범위 요청을 거부하고(훅이 ERR로 둔 문맥 4의 QP) rank 0이 전체 범위로 다시 연다(대조) (Z2) | `mr4_chain_stall@hd` | 5 | 5/5 | 맞음 |
| 랭크 3개에서 간선 0>1의 로컬 QP 오류를 쌍 범위 라운드로 투명하게 복구(대조) (T1) | `mr3_f1_01@hd` | 5 | 5/5 | 맞음 |
| 랭크 2개 4 KiB p50이 10.0-12.0 µs(대조) (L1) | `mr2_lat@hd` | 5 | 5/5 | 맞음 |
| 같은 두 간선을 랭크 4개 통신기에서 돌려도 p50 차이 1.0 µs 이하(대조) (L2) | `mr4_lat_solo@hd`, `mr2_lat@hd` | 5 / 5 | abs(10.080 - 10.720) <= 1.0 | 맞음 |
| 탐색: 모든 간선이 돌 때 노드 사이 간선의 p50 중앙값이 혼자일 때의 2배 이하 (L3) | `mr4_lat@hd`, `mr4_lat_solo@hd` | 5 / 5 | 12.000 <= 2 * 10.080 | 맞음 |
| 탐색: GPU 시분할로 5회 중 4회 이상 어떤 간선에 200 µs 이상 반복 (L4) | `mr4_lat@hd` | 5 | 5/5 | 맞음 |
| 프로세스가 GPU마다 하나면 5회 중 4회 이상 200 µs 넘는 반복 없음(대조) (L5) | `mr2_lat@hd` | 5 | 5/5 | 맞음 |

## 예측별 세부

### 랭크 4개(GPU마다 프로세스 2개)가 통신기와 문맥 12개의 devComm을 만들고, 네 랭크 모두 투명 복구가 켜짐 (I1): 맞음

- 판정식: `count(init_fail == 0 and n_ts_on == 4 and gq_min == 36 and gq_max == 36 and mrge_err == 0) >= 9`
- 셀 `mr4_none@hd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(init_fail == 0 and n_ts_on == 4 and gq_min == 36 and gq_max == 36 and mrge_err == 0)` = 10/10. 조건을 만족하지 않은 시행: 없음

### GPU 하나를 두 프로세스의 커널이 나눠 써도 교착 없이 간선 12개가 모두 정확히 전달됨 (I2): 맞음

- 판정식: `count(transparent_ok == 1) >= 9`
- 셀 `mr4_none@hd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(transparent_ok == 1)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 장애가 없으면 복구 라운드, 거절, 감시 줄이 없음 (I3): 맞음

- 판정식: `count(n_rounds == 0 and n_decl == 0 and n_watchdog == 0) >= 9`
- 셀 `mr4_none@hd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(n_rounds == 0 and n_decl == 0 and n_watchdog == 0)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 랭크 3개: 투명하고 랭크마다 게이트 QP 12개(대조) (I4): 맞음

- 판정식: `count(transparent_ok == 1 and n_ts_on == 3 and gq_min == 12 and gq_max == 12) == 5`
- 셀 `mr3_none@hd`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1 and n_ts_on == 3 and gq_min == 12 and gq_max == 12)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 새 드라이버를 랭크 2개로 돌리면 투명(대조) (I5): 맞음

- 판정식: `count(transparent_ok == 1 and n_ts_on == 2 and gq_min == 2) == 5`
- 셀 `mr2_none@hd`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1 and n_ts_on == 2 and gq_min == 2)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 상대별 flush도 장애 없이 투명(대조) (I6): 맞음

- 판정식: `count(transparent_ok == 1) == 5`
- 셀 `mr4_none_peer@hd`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 간선 0>1의 로컬 QP 오류를 그 QP 하나만 다루는 라운드 하나로 복구 (A1): 맞음

- 판정식: `count(rounds == "0>1:1:pair" and rec_i == "0-1" and rec_r == "1-0" and n_decl == 0 and n_refused == 0) >= 9`
- 셀 `mr4_f1_01@hd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(rounds == "0>1:1:pair" and rec_i == "0-1" and rec_r == "1-0" and n_decl == 0 and n_refused == 0)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 간선 0>1의 로컬 QP 오류 뒤에도 간선 12개 모두 투명 (A2): 맞음

- 판정식: `count(transparent_ok == 1) >= 9`
- 셀 `mr4_f1_01@hd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(transparent_ok == 1)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 라운드를 거친 QP는 그 쌍뿐이고, 훅이 건드린 나머지 두 QP는 끝까지 ERR (A3): 맞음

- 판정식: `count(ep_nz == "0-1-0=2;1-0-0=2" and notrts == "0-2-0=6;0-3-0=6") >= 9`
- 셀 `mr4_f1_01@hd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(ep_nz == "0-1-0=2;1-0-0=2" and notrts == "0-2-0=6;0-3-0=6")` = 10/10. 조건을 만족하지 않은 시행: 없음

### 같은 GPU의 두 프로세스 사이(NIC loopback) 간선 0>2의 로컬 QP 오류도 쌍 범위 라운드로 투명하게 복구 (B1): 맞음

- 판정식: `count(rounds == "0>2:1:pair" and rec_i == "0-2" and rec_r == "2-0" and n_decl == 0 and transparent_ok == 1) >= 9`
- 셀 `mr4_f1_02@hd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(rounds == "0>2:1:pair" and rec_i == "0-2" and rec_r == "2-0" and n_decl == 0 and transparent_ok == 1)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 간선 0>2: 라운드를 거친 QP는 그 쌍뿐이고 나머지 두 QP는 ERR (B2): 맞음

- 판정식: `count(ep_nz == "0-2-1=2;2-0-1=2" and notrts == "0-1-1=6;0-3-1=6") >= 9`
- 셀 `mr4_f1_02@hd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(ep_nz == "0-2-1=2;2-0-1=2" and notrts == "0-1-1=6;0-3-1=6")` = 10/10. 조건을 만족하지 않은 시행: 없음

### 상대 QP 오류(RETRY_EXC)를 쌍 범위 라운드 하나로 투명하게 복구 (C1): 맞음

- 판정식: `count(has(q4_first, "0:RETRY_EXC") and rounds == "0>1:1:pair" and rec_i == "0-1" and rec_r == "1-0" and n_decl == 0 and transparent_ok == 1) >= 9`
- 셀 `mr4_f3_01@hd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(has(q4_first, "0:RETRY_EXC") and rounds == "0>1:1:pair" and rec_i == "0-1" and rec_r == "1-0" and n_decl == 0 and transparent_ok == 1)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 간선 0>1이 묶인 약 3.6 s 동안 rank 0의 다른 두 간선이 각각 100번 이상 진행 (C2): 맞음

- 판정식: `count(win_edge_r0 == "0>1" and w_02_in >= 100 and w_03_in >= 100) >= 9`
- 셀 `mr4_f3_01@hd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(win_edge_r0 == "0>1" and w_02_in >= 100 and w_03_in >= 100)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 상대 QP 오류: 라운드를 거친 QP는 그 쌍뿐이고 rank 1의 나머지 두 QP는 ERR (C3): 맞음

- 판정식: `count(ep_nz == "0-1-0=2;1-0-0=2" and notrts == "1-2-0=6;1-3-0=6") >= 9`
- 셀 `mr4_f3_01@hd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(ep_nz == "0-1-0=2;1-0-0=2" and notrts == "1-2-0=6;1-3-0=6")` = 10/10. 조건을 만족하지 않은 시행: 없음

### 상대 QP 오류의 첫 분류 기록이 훅 3.0-4.5 s 뒤 (C4): 맞음

- 판정식: `count(3000 <= f3_detect_ms <= 4500) >= 9`
- 셀 `mr4_f3_01@hd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(3000 <= f3_detect_ms <= 4500)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 겹치지 않는 두 쌍의 동시 장애가 독립된 두 라운드로 투명하게 복구 (D1): 맞음

- 판정식: `count(rounds == "0>1:1:pair;2>3:1:pair" and rec_i == "0-1;2-3" and rec_r == "1-0;3-2" and n_decl == 0 and transparent_ok == 1) >= 9`
- 셀 `mr4_f1_01_23@hd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(rounds == "0>1:1:pair;2>3:1:pair" and rec_i == "0-1;2-3" and rec_r == "1-0;3-2" and n_decl == 0 and transparent_ok == 1)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 겹치지 않는 두 쌍: 라운드를 거친 QP는 두 쌍뿐 (D2): 맞음

- 판정식: `count(ep_nz == "0-1-0=2;1-0-0=2;2-3-8=2;3-2-8=2" and notrts == "0-2-0=6;0-3-0=6;2-0-8=6;2-1-8=6") >= 9`
- 셀 `mr4_f1_01_23@hd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(ep_nz == "0-1-0=2;1-0-0=2;2-3-8=2;3-2-8=2" and notrts == "0-2-0=6;0-3-0=6;2-0-8=6;2-1-8=6")` = 10/10. 조건을 만족하지 않은 시행: 없음

### 두 시작 쪽이 같은 응답 쪽(rank 0)으로 동시에 와도 둘 다 투명하게 복구 (E1): 맞음

- 판정식: `count(rounds == "1>0:1:pair;3>0:1:pair" and rec_i == "1-0;3-0" and rec_r == "0-1;0-3" and n_decl == 0 and transparent_ok == 1) >= 9`
- 셀 `mr4_f1_10_30@hd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(rounds == "1>0:1:pair;3>0:1:pair" and rec_i == "1-0;3-0" and rec_r == "0-1;0-3" and n_decl == 0 and transparent_ok == 1)` = 10/10. 조건을 만족하지 않은 시행: 없음

### rank 0의 helper가 두 응답 라운드를 차례로 처리(겹침 없음) (E2): 맞음

- 판정식: `count(resp_overlap_r0 == 0) == 10`
- 셀 `mr4_f1_10_30@hd`: 판정한 시행 10회, 대입한 식 `10 == 10` → 참
  - `count(resp_overlap_r0 == 0)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 두 시작 쪽: 라운드를 거친 QP는 두 쌍뿐 (E3): 맞음

- 판정식: `count(ep_nz == "0-1-3=2;0-3-9=2;1-0-3=2;3-0-9=2" and notrts == "1-2-3=6;1-3-3=6;3-1-9=6;3-2-9=6") >= 9`
- 셀 `mr4_f1_10_30@hd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(ep_nz == "0-1-3=2;0-3-9=2;1-0-3=2;3-0-9=2" and notrts == "1-2-3=6;1-3-3=6;3-1-9=6;3-2-9=6")` = 10/10. 조건을 만족하지 않은 시행: 없음

### rank 0의 모든 문맥 장애를 상대별 전체 범위 라운드 세 번으로 복구 (F1): 맞음

- 판정식: `count(rounds == "0>1:12:qp_state;0>2:12:qp_state;0>3:12:qp_state" and rec_i == "0-1;0-2;0-3" and rec_r == "1-0;2-0;3-0" and n_decl == 0) >= 9`
- 셀 `mr4_f1all0@hd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(rounds == "0>1:12:qp_state;0>2:12:qp_state;0>3:12:qp_state" and rec_i == "0-1;0-2;0-3" and rec_r == "1-0;2-0;3-0" and n_decl == 0)` = 10/10. 조건을 만족하지 않은 시행: 없음

### rank 0의 모든 문맥 장애 뒤에도 간선 12개 모두 투명 (F2): 맞음

- 판정식: `count(transparent_ok == 1) >= 9`
- 셀 `mr4_f1all0@hd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(transparent_ok == 1)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 세 라운드가 겹치지 않고, rank 0과 각 상대 사이의 모든 QP가 라운드 한 번을 거쳐 RTS (F3): 맞음

- 판정식: `count(init_overlap_r0 == 0 and n_ep_nz == 72 and n_notrts == 0) >= 9`
- 셀 `mr4_f1all0@hd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(init_overlap_r0 == 0 and n_ep_nz == 72 and n_notrts == 0)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 복구 셀에서 라운드 상한, 펌웨어 단계와 복사의 상한 초과, 소켓으로 취소된 라운드, 죽음 판정이 없음 (R1): 맞음

- 판정식: `per cell: count(n_esc == 0 and n_fw_over == 0 and n_copy_to == 0 and n_cancel == 0 and n_judged_dead == 0) >= 9`
- 셀 `mr4_f1_01@hd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(n_esc == 0 and n_fw_over == 0 and n_copy_to == 0 and n_cancel == 0 and n_judged_dead == 0)` = 10/10. 조건을 만족하지 않은 시행: 없음
- 셀 `mr4_f1_02@hd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(n_esc == 0 and n_fw_over == 0 and n_copy_to == 0 and n_cancel == 0 and n_judged_dead == 0)` = 10/10. 조건을 만족하지 않은 시행: 없음
- 셀 `mr4_f3_01@hd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(n_esc == 0 and n_fw_over == 0 and n_copy_to == 0 and n_cancel == 0 and n_judged_dead == 0)` = 10/10. 조건을 만족하지 않은 시행: 없음
- 셀 `mr4_f1_01_23@hd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(n_esc == 0 and n_fw_over == 0 and n_copy_to == 0 and n_cancel == 0 and n_judged_dead == 0)` = 10/10. 조건을 만족하지 않은 시행: 없음
- 셀 `mr4_f1_10_30@hd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(n_esc == 0 and n_fw_over == 0 and n_copy_to == 0 and n_cancel == 0 and n_judged_dead == 0)` = 10/10. 조건을 만족하지 않은 시행: 없음
- 셀 `mr4_f1all0@hd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(n_esc == 0 and n_fw_over == 0 and n_copy_to == 0 and n_cancel == 0 and n_judged_dead == 0)` = 10/10. 조건을 만족하지 않은 시행: 없음

### rank 3 kill 뒤 살아남은 세 랭크가 소켓으로 rank 3의 죽음을 바로 판정하고 rank 3만 거절(문맥 전체 flush) (K1): 맞음

- 판정식: `count(decl == "0-3;1-3;2-3" and has(decl_reasons, "0-3=peer judged dead: the peer's socket shows") and has(decl_reasons, "1-3=peer judged dead: the peer's socket shows") and has(decl_reasons, "2-3=peer judged dead: the peer's socket shows")) >= 9`
- 셀 `mr4_kill3@hd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(decl == "0-3;1-3;2-3" and has(decl_reasons, "0-3=peer judged dead: the peer's socket shows") and has(decl_reasons, "1-3=peer judged dead: the peer's socket shows") and has(decl_reasons, "2-3=peer judged dead: the peer's socket shows"))` = 10/10. 조건을 만족하지 않은 시행: 없음

### 그 거절이 kill 0–2 s 뒤 (K2): 맞음

- 판정식: `count(0 <= decl_after_kill_ms_r0 <= 2000 and 0 <= decl_after_kill_ms_r1 <= 2000 and 0 <= decl_after_kill_ms_r2 <= 2000) >= 9`
- 셀 `mr4_kill3@hd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(0 <= decl_after_kill_ms_r0 <= 2000 and 0 <= decl_after_kill_ms_r1 <= 2000 and 0 <= decl_after_kill_ms_r2 <= 2000)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 문맥 전체 flush에서는 거절 뒤 살아남은 랭크 사이의 간선 6개도 모두 오류로 멈춤 (K3): 맞음

- 판정식: `count(n_surv_edges == 6 and surv_tx_failed == 6 and surv_edges_ok == 0) >= 9`
- 셀 `mr4_kill3@hd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(n_surv_edges == 6 and surv_tx_failed == 6 and surv_edges_ok == 0)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 상대별 flush에서도 rank 3만 거절 (K4): 맞음

- 판정식: `count(decl == "0-3;1-3;2-3" and has(decl_reasons, "0-3=peer judged dead: the peer's socket shows") and has(decl_reasons, "1-3=peer judged dead: the peer's socket shows") and has(decl_reasons, "2-3=peer judged dead: the peer's socket shows")) >= 9`
- 셀 `mr4_kill3_peer@hd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(decl == "0-3;1-3;2-3" and has(decl_reasons, "0-3=peer judged dead: the peer's socket shows") and has(decl_reasons, "1-3=peer judged dead: the peer's socket shows") and has(decl_reasons, "2-3=peer judged dead: the peer's socket shows"))` = 10/10. 조건을 만족하지 않은 시행: 없음

### 상대별 flush: 거절 뒤 살아남은 랭크 사이의 받는 쪽 6개는 모두 오류, 보내는 쪽 6개는 끝까지 성공 (K5): 맞음

- 판정식: `count(n_surv_edges == 6 and surv_edges_ok == 0 and surv_rx_failed == 6 and surv_tx_failed == 0) >= 9`
- 셀 `mr4_kill3_peer@hd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(n_surv_edges == 6 and surv_edges_ok == 0 and surv_rx_failed == 6 and surv_tx_failed == 0)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 살아남은 세 랭크의 앱이 모두 통신기 비동기 오류를 봄 (K6): 맞음

- 판정식: `per cell: count(async_ranks == "r0,r1,r2") >= 9`
- 셀 `mr4_kill3@hd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(async_ranks == "r0,r1,r2")` = 10/10. 조건을 만족하지 않은 시행: 없음
- 셀 `mr4_kill3_peer@hd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(async_ranks == "r0,r1,r2")` = 10/10. 조건을 만족하지 않은 시행: 없음

### 거절은 rank 3으로 가는 QP 12개만 닫음 (K7): 맞음

- 판정식: `per cell: count(n_ep_nz == 36 and ep_peers == "p3" and n_notrts == 36 and notrts_peers == "p3") >= 9`
- 셀 `mr4_kill3@hd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(n_ep_nz == 36 and ep_peers == "p3" and n_notrts == 36 and notrts_peers == "p3")` = 10/10. 조건을 만족하지 않은 시행: 없음
- 셀 `mr4_kill3_peer@hd`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(n_ep_nz == 36 and ep_peers == "p3" and n_notrts == 36 and notrts_peers == "p3")` = 10/10. 조건을 만족하지 않은 시행: 없음

### 순환하는 세 시작 쪽이 서로를 기다려 handshake timeout 거절이 생기고 투명하지 않음 (Y1): 맞음

- 판정식: `count(n_hs >= 1 and transparent_ok == 0) >= 4`
- 셀 `mr4_cyc_stall@hd`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(n_hs >= 1 and transparent_ok == 0)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 첫 handshake timeout이 라운드 시작 24.3-24.8 s 뒤 (Y2): 맞음

- 판정식: `count(24300 <= hs_first_after_round_ms <= 24800) >= 4`
- 셀 `mr4_cyc_stall@hd`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(24300 <= hs_first_after_round_ms <= 24800)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 그 한도 전에는 어떤 복구도 끝나지 않고(첫 복구가 첫 라운드 24 s 이상 뒤) 감시 줄도 없음 (Y3): 맞음

- 판정식: `count((n_rec_i == 0 or rec_first_after_round_ms >= 24000) and n_watchdog == 0) >= 4`
- 셀 `mr4_cyc_stall@hd`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count((n_rec_i == 0 or rec_first_after_round_ms >= 24000) and n_watchdog == 0)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 순환이 없는 사슬은 첫 라운드 5 s 안에 두 라운드가 모두 끝나고 투명(대조) (Z1): 맞음

- 판정식: `count(transparent_ok == 1 and rec_i == "0-1;1-2" and n_decl == 0 and rec_last_after_round_ms <= 5000) >= 4`
- 셀 `mr4_chain_stall@hd`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(transparent_ok == 1 and rec_i == "0-1;1-2" and n_decl == 0 and rec_last_after_round_ms <= 5000)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 사슬에서 rank 1이 rank 0의 쌍 범위 요청을 거부하고(훅이 ERR로 둔 문맥 4의 QP) rank 0이 전체 범위로 다시 연다(대조) (Z2): 맞음

- 판정식: `count(rounds == "0>1:12:peer;0>1:1:pair;1>2:1:pair" and n_refused == 1 and notrts == "0-2-0=6;0-3-0=6;1-3-4=6") >= 4`
- 셀 `mr4_chain_stall@hd`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(rounds == "0>1:12:peer;0>1:1:pair;1>2:1:pair" and n_refused == 1 and notrts == "0-2-0=6;0-3-0=6;1-3-4=6")` = 5/5. 조건을 만족하지 않은 시행: 없음

### 랭크 3개에서 간선 0>1의 로컬 QP 오류를 쌍 범위 라운드로 투명하게 복구(대조) (T1): 맞음

- 판정식: `count(rounds == "0>1:1:pair" and rec_i == "0-1" and rec_r == "1-0" and n_decl == 0 and transparent_ok == 1 and ep_nz == "0-1-0=2;1-0-0=2" and notrts == "0-2-0=6") >= 4`
- 셀 `mr3_f1_01@hd`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(rounds == "0>1:1:pair" and rec_i == "0-1" and rec_r == "1-0" and n_decl == 0 and transparent_ok == 1 and ep_nz == "0-1-0=2;1-0-0=2" and notrts == "0-2-0=6")` = 5/5. 조건을 만족하지 않은 시행: 없음

### 랭크 2개 4 KiB p50이 10.0-12.0 µs(대조) (L1): 맞음

- 판정식: `count(10.0 <= p50_01 <= 12.0) >= 4`
- 셀 `mr2_lat@hd`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(10.0 <= p50_01 <= 12.0)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 같은 두 간선을 랭크 4개 통신기에서 돌려도 p50 차이 1.0 µs 이하(대조) (L2): 맞음

- 판정식: `abs(median(p50_01, "mr4_lat_solo@hd") - median(p50_01, "mr2_lat@hd")) <= 1.0`
- 셀 `mr4_lat_solo@hd`: 판정한 시행 5회, 대입한 식 `abs(10.080 - 10.720) <= 1.0` → 참

### 탐색: 모든 간선이 돌 때 노드 사이 간선의 p50 중앙값이 혼자일 때의 2배 이하 (L3): 맞음

- 판정식: `median(p50_inter_med, "mr4_lat@hd") <= 2 * median(p50_01, "mr4_lat_solo@hd")`
- 셀 `mr4_lat@hd`: 판정한 시행 5회, 대입한 식 `12.000 <= 2 * 10.080` → 참

### 탐색: GPU 시분할로 5회 중 4회 이상 어떤 간선에 200 µs 이상 반복 (L4): 맞음

- 판정식: `count(max_all >= 200) >= 4`
- 셀 `mr4_lat@hd`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(max_all >= 200)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 프로세스가 GPU마다 하나면 5회 중 4회 이상 200 µs 넘는 반복 없음(대조) (L5): 맞음

- 판정식: `count(max_all < 200) >= 4`
- 셀 `mr2_lat@hd`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(max_all < 200)` = 5/5. 조건을 만족하지 않은 시행: 없음

## 셀별 시행 수와 따로 센 시행

| 셀 | 계획 | 실행 | 판정 | 따로 셈(사유: 시행) |
|---|--:|--:|--:|---|
| `mr2_lat@hd` | 5 | 5 | 5 | 없음 |
| `mr2_none@hd` | 5 | 5 | 5 | 없음 |
| `mr3_f1_01@hd` | 5 | 5 | 5 | 없음 |
| `mr3_none@hd` | 5 | 5 | 5 | 없음 |
| `mr4_chain_stall@hd` | 5 | 5 | 5 | 없음 |
| `mr4_cyc_stall@hd` | 5 | 5 | 5 | 없음 |
| `mr4_f1_01@hd` | 10 | 11 | 10 | 드라이버 랑데부 포트 충돌: mr4_f1_01_n4 |
| `mr4_f1_01_23@hd` | 10 | 10 | 10 | 없음 |
| `mr4_f1_02@hd` | 10 | 10 | 10 | 없음 |
| `mr4_f1_10_30@hd` | 10 | 10 | 10 | 없음 |
| `mr4_f1all0@hd` | 10 | 11 | 10 | 드라이버 랑데부 포트 충돌: mr4_f1all0_n3 |
| `mr4_f3_01@hd` | 10 | 10 | 10 | 없음 |
| `mr4_kill3@hd` | 10 | 10 | 10 | 없음 |
| `mr4_kill3_peer@hd` | 10 | 10 | 10 | 없음 |
| `mr4_lat@hd` | 5 | 5 | 5 | 없음 |
| `mr4_lat_solo@hd` | 5 | 5 | 5 | 없음 |
| `mr4_none@hd` | 10 | 10 | 10 | 없음 |
| `mr4_none_peer@hd` | 5 | 5 | 5 | 없음 |
