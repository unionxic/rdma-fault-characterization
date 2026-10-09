# gin-peer 채점 결과

`score.py`가 원자료(`results/20261009/`의 시행 파일)에서 만들었다. 손으로 고친 값은 없다.

- 예측 파일 sha256: `dccdf05c819976a067950aae2649cd33b8da161a506214633f64cab9402884db`. `PREREG.txt`의 값과 같다.
- 시행 수(모든 hold): 203. 판정한 시행: 203.
- 판정식 원문은 `predictions.csv`, 열과 문법은 `EXPERIMENT.md` 3절.

## 판정 요약

| 예측 | 셀 | n | 맞은 시행(조건별) | 판정 |
|---|---|--:|---|---|
| 응답 쪽(rank 1)이 커밋과 ACK 전에 다시 보내기 계획을 거부하면(NACK 15) rank 0은 계획도 세우지 않고, 어느 rank도 복구 줄이 없으며 둘 다 거절 (A1) | `pq_repost_r1_b@hq` | 10 | 10/10 | 맞음 |
| 대조(gin-handoff): 응답 쪽은 DONE 뒤에야 거부해, rank 0은 이미 다시 보내고 복구 줄을 남긴 뒤 거절 (A2) | `pq_repost_r1_b@hf` | 5 | 5/5 | 맞음 |
| 시작 쪽(rank 0)이 둘째 QP의 계획을 거부하면 아무도 다시 보내지 않고 둘 다 거절(회귀, 역할 제외 없이) (A3) | `hd_repost_f1_b@hq` | 5 | 5/5 | 맞음 |
| 랭크 2개, 8 s commit 단계: 감시가 3.0-3.5 s에 한 번 발동해 대기를 오류로 풀고, abort가 6 s 안에 돌아오며 rank 1이 거절(회귀) (B1) | `hd_fwslow_f1_b@hq` | 5 | 5/5 | 맞음 |
| 랭크 4개: rank 0의 rank 1 라운드가 commit 단계를 넘기면 그 상대만 거절되고, 뒤의 rank 2와 rank 0 라운드는 복구됨 (B2) | `pq4_fwslow@hq` | 10 | 10/10 | 맞음 |
| 그때 올라간 단어는 그 두 rank의 상대별 단어뿐이고 devComm 단어는 아무도 올리지 않음 (B3) | `pq4_fwslow@hq` | 10 | 10/10 | 맞음 |
| 간선 0>1, 1>0 말고는 모든 간선이 정상으로 끝남 (B4) | `pq4_fwslow@hq` | 10 | 10/10 | 맞음 |
| 대조(gin-handoff): 초과가 영구라 rank 0이 rank 2의 라운드를 "감시가 이미 드러냄"으로 거절하고 rank 0의 다른 간선이 실패 (B5) | `pq4_fwslow@hf` | 5 | 5/5 | 맞음 |
| 랭크 4개, rank 3 kill, 상대별 flush: 살아남은 세 rank 사이 간선 6개가 모두 정상으로 끝남 (K1) | `mr4_kill3_peer@hq` | 10 | 10/10 | 맞음 |
| 살아남은 rank마다 rank 3만 죽음 원인으로 거절하고 rank 3의 단어만 올리며 devComm 단어는 올리지 않음 (K2) | `mr4_kill3_peer@hq` | 10 | 10/10 | 맞음 |
| rank 3으로 가는 간선은 보내는 쪽이 실패하고, rank 3에서 오는 받기는 일찍 풀리지 않고 자기 한도로 끝나며, 세 rank 모두 비동기 오류를 봄 (K3) | `mr4_kill3_peer@hq` | 10 | 10/10 | 맞음 |
| 대조(gin-handoff): 살아남은 rank 사이 받는 쪽 6개가 실패하고 보내는 쪽은 끝까지 감(gin-multirank K5) (K4) | `mr4_kill3_peer@hf` | 5 | 5/5 | 맞음 |
| 문맥 전체 flush: 살아남은 rank의 보내는 쪽 6개는 여전히 실패하고, 받는 쪽 6개는 일찍 풀리지 않고 자기 한도로 끝남 (K5) | `mr4_kill3@hq` | 5 | 5/5 | 맞음 |
| rank 0의 원인(복사 상한 초과)으로 rank 1을 거절한 뒤, 살아 있는 rank 1을 빼는 중단 shrink는 순정 답을 지키고 원인 local을 적음 (H1) | `pq_copystall_shrink_b@hq` | 10 | 10/10 | 맞음 |
| 대조(gin-handoff): 같은 shrink가 넘어가 1-rank communicator와 맞는 allreduce를 돌려줌 (H2) | `pq_copystall_shrink_b@hf` | 5 | 5/5 | 맞음 |
| 원인이 rank 1(응답 쪽 복사)이면 rank 0의 원인은 peer-reported이고 shrink가 넘어감 (H3) | `pq_copystall1_shrink_b@hq` | 5 | 5/5 | 맞음 |
| 상대가 죽은 경우 원인은 peer-dead이고 shrink가 gin-handoff처럼 넘어감(회귀) (H4) | `hd_shrink_b@hq` | 5 | 5/5 | 맞음 |
| 랭크 4개, rank 3 kill: 살아남은 세 rank의 shrink가 모두 넘어가고, 3-rank 아이가 자기 devComm을 열어 간선 6개가 모두 정상 (H5) | `pq4_kill3_shrink@hq` | 10 | 10/10 | 맞음 |
| 랭크 4개: rank 0의 원인이 local이면 rank 0의 shrink는 순정 답을 지키고 아이가 생기지 않음 (H6) | `pq4_local_shrink@hq` | 5 | 5/5 | 맞음 |
| (한계) 자기 확인을 통과한 rank 2, 3은 rank 0을 기다리다 단계 한도에서 끝남 (H7) | `pq4_local_shrink@hq` | 5 | 5/5 | 맞음 |
| 대조(gin-handoff): 원인이 local이어도 rank 0이 넘어가고 세 rank 모두 3-rank 아이를 얻음 (H8) | `pq4_local_shrink@hf` | 5 | 5/5 | 맞음 |
| ACK를 기다리다 취소한 rank 0의 다시 걸기에, 이미 커밋하고 거절한 rank 1이 FAIL로 답하고 rank 0은 끊김 끝 1.5 s 안에 거절 (C1) | `pq_ackrace_f1_b@hq` | 10 | 10/10 | 맞음 |
| 대조(gin-handoff): rank 1이 다시 걸기를 닫아 rank 0은 재연결 한도를 다 쓰고 끊김 끝 5 s 이상 뒤 "모름"으로 거절 (C2) | `pq_ackrace_f1_b@hf` | 5 | 5/5 | 맞음 |
| 같은 경합을 rank 1이 시작한 경우: rank 0이 확인 접속에 FAIL로 답하고 rank 1이 끊김 끝 1.5 s 안에 거절 (C3) | `pq_ackrace_f1r1_b@hq` | 5 | 5/5 | 맞음 |
| 대조(gin-handoff): rank 0이 확인 접속에 답만 하고 다시 걸지 않아 rank 1은 끊김 끝 5 s 이상 뒤 "모름"으로 거절 (C4) | `pq_ackrace_f1r1_b@hf` | 5 | 5/5 | 맞음 |
| 본 실행의 어떤 시행도 랑데부 포트 bind에 실패하지 않음 (Q1) | `all@all` | 203 | 0/203 | 맞음 |
| 막아 둔 첫 후보 포트를 건너뛰고, rank 1이 가짜 수신 대기에 한 바이트도 보내지 않고 거부하며, 두 rank가 랑데부를 확인하고 투명 (Q2) | `pq_rdv_b@hq` | 5 | 5/5 | 맞음 |
| 랭크 4개에서도 같음(rank 1-3이 가짜를 거부, 네 rank 모두 확인, 투명) (Q3) | `pq4_rdv@hq` | 3 | 3/3 | 맞음 |
| 복구 재현 셀이 그대로 투명 (R1) | `f1_b@hq`, `f3_b@hq`, `bidirf_sym_b@hq` | 5 / 5 / 5 | 5/5; 5/5; 5/5 | 맞음 |
| 랭크 2개, 상대 kill: 2 s 안에 죽음 원인으로 거절하고, 유일한 상대라 devComm 단어도 peer-dead로 올라가며 abort가 돌아옴 (R2) | `f4_b@hq` | 5 | 5/5 | 맞음 |
| 랭크 2개, 받기만 하는 rank의 waitSignal이 보내는 쪽 kill 2 s 안에 오류로 풀림(모든 상대가 거절되어 devComm 단어) (R3) | `hd_rxdeath_b@hq` | 5 | 5/5 | 맞음 |
| 원격 접근 오류를 rank 0이 거절하고 받는 쪽 대기가 오류로 풀리며 abort가 5 s 안에 돌아옴 (R4) | `f2rel_b@hq` | 5 | 5/5 | 맞음 |
| 운영 빌드가 kill된 상대를 2 s 안에 죽음으로 거절하고 죽음 1을 세며 WARN에 정보성 줄이 없음 (R5) | `hdp_kill_b@hqp` | 5 | 5/5 | 맞음 |
| 랭크 4개, 장애 없음과 한 쌍의 로컬 QP 오류가 투명 (R6) | `mr4_none@hq`, `mr4_f1_01@hq` | 5 / 5 | 5/5; 5/5 | 맞음 |
| 통계 API가 두 rank에서 라운드 1, 복구 1, 거절 0을 셈 (R7) | `f1_b@hq` | 5 | 5/5 | 맞음 |
| 4 KiB 지연: 이 실험의 운영 빌드와 gin-handoff 운영 빌드 차이 0.40 µs 이하 (P1) | `lat_4k@hqp`, `lat_4k@hfp` | 5 / 5 | abs(10.750 - 10.690) <= 0.40 | 맞음 |
| 256 KiB 지연: 차이 0.30 µs 이하 (P2) | `lat_256k@hqp`, `lat_256k@hfp` | 5 / 5 | abs(38.880 - 38.910) <= 0.30 | 맞음 |

## 예측별 세부

### 응답 쪽(rank 1)이 커밋과 ACK 전에 다시 보내기 계획을 거부하면(NACK 15) rank 0은 계획도 세우지 않고, 어느 rank도 복구 줄이 없으며 둘 다 거절 (A1): 맞음

- 판정식: `count(n_planrej_r1 >= 1 and n_planok_r0 == 0 and n_rec_any == 0 and declwhy_r0 == "peer NACK (its re-post plan was rejected)" and nonempty(declwhy_r1)) >= 9`
- 셀 `pq_repost_r1_b@hq`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(n_planrej_r1 >= 1 and n_planok_r0 == 0 and n_rec_any == 0 and declwhy_r0 == "peer NACK (its re-post plan was rejected)" and nonempty(declwhy_r1))` = 10/10. 조건을 만족하지 않은 시행: 없음

### 대조(gin-handoff): 응답 쪽은 DONE 뒤에야 거부해, rank 0은 이미 다시 보내고 복구 줄을 남긴 뒤 거절 (A2): 맞음

- 판정식: `count(rec_init_r0 >= 1 and n_planrej_r1 >= 1 and nonempty(declwhy_r0)) >= 4`
- 셀 `pq_repost_r1_b@hf`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(rec_init_r0 >= 1 and n_planrej_r1 >= 1 and nonempty(declwhy_r0))` = 5/5. 조건을 만족하지 않은 시행: 없음

### 시작 쪽(rank 0)이 둘째 QP의 계획을 거부하면 아무도 다시 보내지 않고 둘 다 거절(회귀, 역할 제외 없이) (A3): 맞음

- 판정식: `count(n_planrej_r0 >= 1 and planrej_qp_r0 == 1 and n_rec_any == 0 and nonempty(declwhy_r0) and nonempty(declwhy_r1)) == 5`
- 셀 `hd_repost_f1_b@hq`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(n_planrej_r0 >= 1 and planrej_qp_r0 == 1 and n_rec_any == 0 and nonempty(declwhy_r0) and nonempty(declwhy_r1))` = 5/5. 조건을 만족하지 않은 시행: 없음

### 랭크 2개, 8 s commit 단계: 감시가 3.0-3.5 s에 한 번 발동해 대기를 오류로 풀고, abort가 6 s 안에 돌아오며 rank 1이 거절(회귀) (B1): 맞음

- 판정식: `count(n_fwover_r0 == 1 and fwover_phase_r0 == "commit" and 3000 <= fwover_ms_r0 <= 3500 and uarel_why_r0 == "fw-watchdog" and r0_async != "none" and teardown_r0 == "no error" and teardown_ms_r0 <= 6000 and n_orphan_r0 >= 1 and nonempty(declwhy_r1)) == 5`
- 셀 `hd_fwslow_f1_b@hq`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(n_fwover_r0 == 1 and fwover_phase_r0 == "commit" and 3000 <= fwover_ms_r0 <= 3500 and uarel_why_r0 == "fw-watchdog" and r0_async != "none" and teardown_r0 == "no error" and teardown_ms_r0 <= 6000 and n_orphan_r0 >= 1 and nonempty(declwhy_r1))` = 5/5. 조건을 만족하지 않은 시행: 없음

### 랭크 4개: rank 0의 rank 1 라운드가 commit 단계를 넘기면 그 상대만 거절되고, 뒤의 rank 2와 rank 0 라운드는 복구됨 (B2): 맞음

- 판정식: `count(fwover == "0-1:commit" and decl == "0-1;1-0" and rec_20 == 1 and rec_02 == 1) >= 9`
- 셀 `pq4_fwslow@hq`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(fwover == "0-1:commit" and decl == "0-1;1-0" and rec_20 == 1 and rec_02 == 1)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 그때 올라간 단어는 그 두 rank의 상대별 단어뿐이고 devComm 단어는 아무도 올리지 않음 (B3): 맞음

- 판정식: `count(uapeer == "0-1;1-0" and n_uaerr == 0) >= 9`
- 셀 `pq4_fwslow@hq`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(uapeer == "0-1;1-0" and n_uaerr == 0)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 간선 0>1, 1>0 말고는 모든 간선이 정상으로 끝남 (B4): 맞음

- 판정식: `count(edges_bad == "0>1;1>0") >= 9`
- 셀 `pq4_fwslow@hq`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(edges_bad == "0>1;1>0")` = 10/10. 조건을 만족하지 않은 시행: 없음

### 대조(gin-handoff): 초과가 영구라 rank 0이 rank 2의 라운드를 "감시가 이미 드러냄"으로 거절하고 rank 0의 다른 간선이 실패 (B5): 맞음

- 판정식: `count(has(decl_reasons, "0-2=the watchdog surfaced a fault earlier") and rec_20 == 0 and n_bad_0_23 >= 1) >= 4`
- 셀 `pq4_fwslow@hf`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(has(decl_reasons, "0-2=the watchdog surfaced a fault earlier") and rec_20 == 0 and n_bad_0_23 >= 1)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 랭크 4개, rank 3 kill, 상대별 flush: 살아남은 세 rank 사이 간선 6개가 모두 정상으로 끝남 (K1): 맞음

- 판정식: `count(n_surv_edges == 6 and surv_edges_ok == 6) >= 9`
- 셀 `mr4_kill3_peer@hq`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(n_surv_edges == 6 and surv_edges_ok == 6)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 살아남은 rank마다 rank 3만 죽음 원인으로 거절하고 rank 3의 단어만 올리며 devComm 단어는 올리지 않음 (K2): 맞음

- 판정식: `count(decl == "0-3;1-3;2-3" and n_cause_peerdead == 3 and uapeer == "0-3;1-3;2-3" and n_uaerr == 0) >= 9`
- 셀 `mr4_kill3_peer@hq`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(decl == "0-3;1-3;2-3" and n_cause_peerdead == 3 and uapeer == "0-3;1-3;2-3" and n_uaerr == 0)` = 10/10. 조건을 만족하지 않은 시행: 없음

### rank 3으로 가는 간선은 보내는 쪽이 실패하고, rank 3에서 오는 받기는 일찍 풀리지 않고 자기 한도로 끝나며, 세 rank 모두 비동기 오류를 봄 (K3): 맞음

- 판정식: `count(dead_tx_failed == 3 and dead_rx_timeout == 3 and async_ranks == "r0,r1,r2") >= 9`
- 셀 `mr4_kill3_peer@hq`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(dead_tx_failed == 3 and dead_rx_timeout == 3 and async_ranks == "r0,r1,r2")` = 10/10. 조건을 만족하지 않은 시행: 없음

### 대조(gin-handoff): 살아남은 rank 사이 받는 쪽 6개가 실패하고 보내는 쪽은 끝까지 감(gin-multirank K5) (K4): 맞음

- 판정식: `count(n_surv_edges == 6 and surv_rx_failed == 6 and surv_tx_failed == 0) >= 4`
- 셀 `mr4_kill3_peer@hf`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(n_surv_edges == 6 and surv_rx_failed == 6 and surv_tx_failed == 0)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 문맥 전체 flush: 살아남은 rank의 보내는 쪽 6개는 여전히 실패하고, 받는 쪽 6개는 일찍 풀리지 않고 자기 한도로 끝남 (K5): 맞음

- 판정식: `count(n_surv_edges == 6 and surv_tx_failed == 6 and surv_rx_timeout == 6) >= 4`
- 셀 `mr4_kill3@hq`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(n_surv_edges == 6 and surv_tx_failed == 6 and surv_rx_timeout == 6)` = 5/5. 조건을 만족하지 않은 시행: 없음

### rank 0의 원인(복사 상한 초과)으로 rank 1을 거절한 뒤, 살아 있는 rank 1을 빼는 중단 shrink는 순정 답을 지키고 원인 local을 적음 (H1): 맞음

- 판정식: `count(cause_r0 == "local" and n_hoff_keep_r0 == 1 and has(hoff_why_r0, "with a cause that is not the peer's (local)") and n_hoff_ok_r0 == 0 and ho_newcomm == 0 and ho_shrink_rc == "remote process exited or there was a network error") >= 9`
- 셀 `pq_copystall_shrink_b@hq`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(cause_r0 == "local" and n_hoff_keep_r0 == 1 and has(hoff_why_r0, "with a cause that is not the peer's (local)") and n_hoff_ok_r0 == 0 and ho_newcomm == 0 and ho_shrink_rc == "remote process exited or there was a network error")` = 10/10. 조건을 만족하지 않은 시행: 없음

### 대조(gin-handoff): 같은 shrink가 넘어가 1-rank communicator와 맞는 allreduce를 돌려줌 (H2): 맞음

- 판정식: `count(n_hoff_ok_r0 == 1 and ho_newcomm == 1 and ho_newcomm_nranks == 1 and ho_check_ok == 1) >= 4`
- 셀 `pq_copystall_shrink_b@hf`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(n_hoff_ok_r0 == 1 and ho_newcomm == 1 and ho_newcomm_nranks == 1 and ho_check_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 원인이 rank 1(응답 쪽 복사)이면 rank 0의 원인은 peer-reported이고 shrink가 넘어감 (H3): 맞음

- 판정식: `count(cause_r0 == "peer-reported" and cause_r1 == "local" and n_hoff_ok_r0 == 1 and ho_newcomm == 1 and ho_check_ok == 1) >= 4`
- 셀 `pq_copystall1_shrink_b@hq`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(cause_r0 == "peer-reported" and cause_r1 == "local" and n_hoff_ok_r0 == 1 and ho_newcomm == 1 and ho_check_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 상대가 죽은 경우 원인은 peer-dead이고 shrink가 gin-handoff처럼 넘어감(회귀) (H4): 맞음

- 판정식: `count(cause_r0 == "peer-dead" and n_hoff_ok_r0 == 1 and ho_shrink_rc == "no error" and ho_newcomm_nranks == 1 and ho_check_ok == 1) >= 4`
- 셀 `hd_shrink_b@hq`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(cause_r0 == "peer-dead" and n_hoff_ok_r0 == 1 and ho_shrink_rc == "no error" and ho_newcomm_nranks == 1 and ho_check_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 랭크 4개, rank 3 kill: 살아남은 세 rank의 shrink가 모두 넘어가고, 3-rank 아이가 자기 devComm을 열어 간선 6개가 모두 정상 (H5): 맞음

- 판정식: `count(n_hoff_ok == 3 and n_hoff_keep == 0 and ch_ok_ranks == 3 and ch_tx_ok_sum == 6 and ch_rx_ok_sum == 6) >= 9`
- 셀 `pq4_kill3_shrink@hq`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(n_hoff_ok == 3 and n_hoff_keep == 0 and ch_ok_ranks == 3 and ch_tx_ok_sum == 6 and ch_rx_ok_sum == 6)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 랭크 4개: rank 0의 원인이 local이면 rank 0의 shrink는 순정 답을 지키고 아이가 생기지 않음 (H6): 맞음

- 판정식: `count(n_cause_local >= 1 and has(keep_why_r0, "(local)") and ch_shrink_fail_r0 == 1 and ch_created_ranks == 0) >= 4`
- 셀 `pq4_local_shrink@hq`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(n_cause_local >= 1 and has(keep_why_r0, "(local)") and ch_shrink_fail_r0 == 1 and ch_created_ranks == 0)` = 5/5. 조건을 만족하지 않은 시행: 없음

### (한계) 자기 확인을 통과한 rank 2, 3은 rank 0을 기다리다 단계 한도에서 끝남 (H7): 맞음

- 판정식: `count(ch_timeout_ranks == 2) >= 4`
- 셀 `pq4_local_shrink@hq`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(ch_timeout_ranks == 2)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 대조(gin-handoff): 원인이 local이어도 rank 0이 넘어가고 세 rank 모두 3-rank 아이를 얻음 (H8): 맞음

- 판정식: `count(n_hoff_ok == 1 and n_hoff_keep == 0 and ch_created_ranks == 3) >= 4`
- 셀 `pq4_local_shrink@hf`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(n_hoff_ok == 1 and n_hoff_keep == 0 and ch_created_ranks == 3)` = 5/5. 조건을 만족하지 않은 시행: 없음

### ACK를 기다리다 취소한 rank 0의 다시 걸기에, 이미 커밋하고 거절한 rank 1이 FAIL로 답하고 rank 0은 끊김 끝 1.5 s 안에 거절 (C1): 맞음

- 판정식: `count(n_cancel_ack_r0 >= 1 and has(failans_r1, "re-dial") and declwhy_r0 == "the peer declined this pair (FAIL on reconnect)" and 0 <= decl_after_unmute_ms_r0 <= 1500) >= 9`
- 셀 `pq_ackrace_f1_b@hq`: 판정한 시행 10회, 대입한 식 `10 >= 9` → 참
  - `count(n_cancel_ack_r0 >= 1 and has(failans_r1, "re-dial") and declwhy_r0 == "the peer declined this pair (FAIL on reconnect)" and 0 <= decl_after_unmute_ms_r0 <= 1500)` = 10/10. 조건을 만족하지 않은 시행: 없음

### 대조(gin-handoff): rank 1이 다시 걸기를 닫아 rank 0은 재연결 한도를 다 쓰고 끊김 끝 5 s 이상 뒤 "모름"으로 거절 (C2): 맞음

- 판정식: `count(n_cancel_ack_r0 >= 1 and has(declwhy_r0, "liveness unknown") and decl_after_unmute_ms_r0 >= 5000) >= 4`
- 셀 `pq_ackrace_f1_b@hf`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(n_cancel_ack_r0 >= 1 and has(declwhy_r0, "liveness unknown") and decl_after_unmute_ms_r0 >= 5000)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 같은 경합을 rank 1이 시작한 경우: rank 0이 확인 접속에 FAIL로 답하고 rank 1이 끊김 끝 1.5 s 안에 거절 (C3): 맞음

- 판정식: `count(n_cancel_ack_r1 >= 1 and has(failans_r0, "probe") and declwhy_r1 == "the peer declined this pair (FAIL on reconnect)" and 0 <= decl_after_unmute_ms_r1 <= 1500) >= 4`
- 셀 `pq_ackrace_f1r1_b@hq`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(n_cancel_ack_r1 >= 1 and has(failans_r0, "probe") and declwhy_r1 == "the peer declined this pair (FAIL on reconnect)" and 0 <= decl_after_unmute_ms_r1 <= 1500)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 대조(gin-handoff): rank 0이 확인 접속에 답만 하고 다시 걸지 않아 rank 1은 끊김 끝 5 s 이상 뒤 "모름"으로 거절 (C4): 맞음

- 판정식: `count(n_cancel_ack_r1 >= 1 and has(declwhy_r1, "liveness unknown") and decl_after_unmute_ms_r1 >= 5000) >= 4`
- 셀 `pq_ackrace_f1r1_b@hf`: 판정한 시행 5회, 대입한 식 `5 >= 4` → 참
  - `count(n_cancel_ack_r1 >= 1 and has(declwhy_r1, "liveness unknown") and decl_after_unmute_ms_r1 >= 5000)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 본 실행의 어떤 시행도 랑데부 포트 bind에 실패하지 않음 (Q1): 맞음

- 판정식: `count(bind_fail == 1) == 0`
- 셀 `all@all`: 판정한 시행 203회, 대입한 식 `0 == 0` → 참
  - `count(bind_fail == 1)` = 0/203. 조건을 만족한(예측과 반대인) 시행: 없음

### 막아 둔 첫 후보 포트를 건너뛰고, rank 1이 가짜 수신 대기에 한 바이트도 보내지 않고 거부하며, 두 rank가 랑데부를 확인하고 투명 (Q2): 맞음

- 판정식: `count(occupy_skipped == 1 and decoy_conns >= 1 and decoy_bytes == 0 and rdv_decoy_r1 == "rejected" and rdv_r0 == "verified" and rdv_r1 == "verified" and transparent_ok == 1) == 5`
- 셀 `pq_rdv_b@hq`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(occupy_skipped == 1 and decoy_conns >= 1 and decoy_bytes == 0 and rdv_decoy_r1 == "rejected" and rdv_r0 == "verified" and rdv_r1 == "verified" and transparent_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 랭크 4개에서도 같음(rank 1-3이 가짜를 거부, 네 rank 모두 확인, 투명) (Q3): 맞음

- 판정식: `count(occupy_skipped == 1 and decoy_conns >= 3 and decoy_bytes == 0 and n_decoy_rejected == 3 and n_rdv_verified == 4 and transparent_ok == 1) == 3`
- 셀 `pq4_rdv@hq`: 판정한 시행 3회, 대입한 식 `3 == 3` → 참
  - `count(occupy_skipped == 1 and decoy_conns >= 3 and decoy_bytes == 0 and n_decoy_rejected == 3 and n_rdv_verified == 4 and transparent_ok == 1)` = 3/3. 조건을 만족하지 않은 시행: 없음

### 복구 재현 셀이 그대로 투명 (R1): 맞음

- 판정식: `per cell: count(transparent_ok == 1) == 5`
- 셀 `f1_b@hq`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음
- 셀 `f3_b@hq`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음
- 셀 `bidirf_sym_b@hq`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 랭크 2개, 상대 kill: 2 s 안에 죽음 원인으로 거절하고, 유일한 상대라 devComm 단어도 peer-dead로 올라가며 abort가 돌아옴 (R2): 맞음

- 판정식: `count(has(declwhy_r0, "the peer's socket shows") and cause_r0 == "peer-dead" and 0 <= decl_after_kill_ms_r0 <= 2000 and teardown_r0 == "no error" and uaerr_why_r0 == "peer-dead") == 5`
- 셀 `f4_b@hq`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(has(declwhy_r0, "the peer's socket shows") and cause_r0 == "peer-dead" and 0 <= decl_after_kill_ms_r0 <= 2000 and teardown_r0 == "no error" and uaerr_why_r0 == "peer-dead")` = 5/5. 조건을 만족하지 않은 시행: 없음

### 랭크 2개, 받기만 하는 rank의 waitSignal이 보내는 쪽 kill 2 s 안에 오류로 풀림(모든 상대가 거절되어 devComm 단어) (R3): 맞음

- 판정식: `count(n_judged_r1 >= 1 and rx_rc == "remote process exited or there was a network error" and 0 <= release_after_kill_ms_r1 <= 2000 and 0 <= async_after_kill_ms_r1 <= 2000 and teardown_r1 == "no error") == 5`
- 셀 `hd_rxdeath_b@hq`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(n_judged_r1 >= 1 and rx_rc == "remote process exited or there was a network error" and 0 <= release_after_kill_ms_r1 <= 2000 and 0 <= async_after_kill_ms_r1 <= 2000 and teardown_r1 == "no error")` = 5/5. 조건을 만족하지 않은 시행: 없음

### 원격 접근 오류를 rank 0이 거절하고 받는 쪽 대기가 오류로 풀리며 abort가 5 s 안에 돌아옴 (R4): 맞음

- 판정식: `count(has(decl_r0, "REM_ACCESS is not recoverable") and r1_outcome == "device_error" and rx_rc == "remote process exited or there was a network error" and rx_phantom_r1 == 0 and teardown_r1 == "no error" and teardown_ms_r1 <= 5000) == 5`
- 셀 `f2rel_b@hq`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(has(decl_r0, "REM_ACCESS is not recoverable") and r1_outcome == "device_error" and rx_rc == "remote process exited or there was a network error" and rx_phantom_r1 == 0 and teardown_r1 == "no error" and teardown_ms_r1 <= 5000)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 운영 빌드가 kill된 상대를 2 s 안에 죽음으로 거절하고 죽음 1을 세며 WARN에 정보성 줄이 없음 (R5): 맞음

- 판정식: `count(has(decl_r0, "the peer's socket shows") and teardown_r0 == "no error" and rs_deaths_r0 == 1 and 0 <= decl_after_kill_ms_r0 <= 2000 and ts_on_r0 == 0 and ts_on_r1 == 0 and rs_api_r0 == 1) == 5`
- 셀 `hdp_kill_b@hqp`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(has(decl_r0, "the peer's socket shows") and teardown_r0 == "no error" and rs_deaths_r0 == 1 and 0 <= decl_after_kill_ms_r0 <= 2000 and ts_on_r0 == 0 and ts_on_r1 == 0 and rs_api_r0 == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 랭크 4개, 장애 없음과 한 쌍의 로컬 QP 오류가 투명 (R6): 맞음

- 판정식: `per cell: count(transparent_ok == 1) == 5`
- 셀 `mr4_none@hq`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음
- 셀 `mr4_f1_01@hq`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(transparent_ok == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 통계 API가 두 rank에서 라운드 1, 복구 1, 거절 0을 셈 (R7): 맞음

- 판정식: `count(rs_api_r0 == 1 and rs_rounds_r0 == 1 and rs_recovered_r0 == 1 and rs_declined_r0 == 0 and rs_rounds_r1 == 1 and rs_recovered_r1 == 1) == 5`
- 셀 `f1_b@hq`: 판정한 시행 5회, 대입한 식 `5 == 5` → 참
  - `count(rs_api_r0 == 1 and rs_rounds_r0 == 1 and rs_recovered_r0 == 1 and rs_declined_r0 == 0 and rs_rounds_r1 == 1 and rs_recovered_r1 == 1)` = 5/5. 조건을 만족하지 않은 시행: 없음

### 4 KiB 지연: 이 실험의 운영 빌드와 gin-handoff 운영 빌드 차이 0.40 µs 이하 (P1): 맞음

- 판정식: `abs(median(lat_p50_us, "lat_4k@hqp") - median(lat_p50_us, "lat_4k@hfp")) <= 0.40`
- 셀 `lat_4k@hqp`: 판정한 시행 5회, 대입한 식 `abs(10.750 - 10.690) <= 0.40` → 참

### 256 KiB 지연: 차이 0.30 µs 이하 (P2): 맞음

- 판정식: `abs(median(lat_p50_us, "lat_256k@hqp") - median(lat_p50_us, "lat_256k@hfp")) <= 0.30`
- 셀 `lat_256k@hqp`: 판정한 시행 5회, 대입한 식 `abs(38.880 - 38.910) <= 0.30` → 참

## 셀별 시행 수와 따로 센 시행

| 셀 | 계획 | 실행 | 판정 | 따로 셈(사유: 시행) |
|---|--:|--:|--:|---|
| `bidirf_sym_b@hq` | 5 | 5 | 5 | 없음 |
| `f1_b@hq` | 5 | 5 | 5 | 없음 |
| `f2rel_b@hq` | 5 | 5 | 5 | 없음 |
| `f3_b@hq` | 5 | 5 | 5 | 없음 |
| `f4_b@hq` | 5 | 5 | 5 | 없음 |
| `hd_fwslow_f1_b@hq` | 5 | 5 | 5 | 없음 |
| `hd_repost_f1_b@hq` | 5 | 5 | 5 | 없음 |
| `hd_rxdeath_b@hq` | 5 | 5 | 5 | 없음 |
| `hd_shrink_b@hq` | 5 | 5 | 5 | 없음 |
| `hdp_kill_b@hqp` | 5 | 5 | 5 | 없음 |
| `lat_256k@hfp` | 5 | 5 | 5 | 없음 |
| `lat_256k@hqp` | 5 | 5 | 5 | 없음 |
| `lat_4k@hfp` | 5 | 5 | 5 | 없음 |
| `lat_4k@hqp` | 5 | 5 | 5 | 없음 |
| `mr4_f1_01@hq` | 5 | 5 | 5 | 없음 |
| `mr4_kill3@hq` | 5 | 5 | 5 | 없음 |
| `mr4_kill3_peer@hf` | 5 | 5 | 5 | 없음 |
| `mr4_kill3_peer@hq` | 10 | 10 | 10 | 없음 |
| `mr4_none@hq` | 5 | 5 | 5 | 없음 |
| `pq4_fwslow@hf` | 5 | 5 | 5 | 없음 |
| `pq4_fwslow@hq` | 10 | 10 | 10 | 없음 |
| `pq4_kill3_shrink@hq` | 10 | 10 | 10 | 없음 |
| `pq4_local_shrink@hf` | 5 | 5 | 5 | 없음 |
| `pq4_local_shrink@hq` | 5 | 5 | 5 | 없음 |
| `pq4_rdv@hq` | 3 | 3 | 3 | 없음 |
| `pq_ackrace_f1_b@hf` | 5 | 5 | 5 | 없음 |
| `pq_ackrace_f1_b@hq` | 10 | 10 | 10 | 없음 |
| `pq_ackrace_f1r1_b@hf` | 5 | 5 | 5 | 없음 |
| `pq_ackrace_f1r1_b@hq` | 5 | 5 | 5 | 없음 |
| `pq_copystall1_shrink_b@hq` | 5 | 5 | 5 | 없음 |
| `pq_copystall_shrink_b@hf` | 5 | 5 | 5 | 없음 |
| `pq_copystall_shrink_b@hq` | 10 | 10 | 10 | 없음 |
| `pq_rdv_b@hq` | 5 | 5 | 5 | 없음 |
| `pq_repost_r1_b@hf` | 5 | 5 | 5 | 없음 |
| `pq_repost_r1_b@hq` | 10 | 10 | 10 | 없음 |
