# live_boundary 채점 결과

`score.py`가 `predictions.csv`(태그 `prereg/live-boundary-v1`)의 판정식을 EXPERIMENT.md 3.0절 규칙 그대로 적용한 결과다. 원자료는 `CP/`, `CG/`, `G/`(Release). 소스 예측 3줄은 채점하지 않는다. 시행별 값은 [trials_scored.csv](trials_scored.csv).

측정 예측 14줄 중 맞음 12, 틀림 2, 자료 없음 0.

## 시행 수

| 점 | 시행 | 채점 | 장애 미적용 | 실행기 실패 |
|---|--:|--:|--:|--:|
| CPU, PROBE 정지 없음 (CP0) | 5 | 5 | 0 | 0 |
| CPU, PROBE 받을 때 900 ms 정지 (CP900) | 5 | 5 | 0 | 0 |
| CPU, PROBE 받을 때 990 ms 정지 (CP990) | 5 | 5 | 0 | 0 |
| CPU, PROBE 받을 때 1008 ms 정지 (CP1008) | 10 | 10 | 0 | 0 |
| CPU, PROBE 받을 때 1024 ms 정지 (CP1024) | 10 | 10 | 0 | 0 |
| CPU, PROBE 받을 때 1040 ms 정지 (CP1040) | 5 | 5 | 0 | 0 |
| CPU, PROBE 받을 때 1100 ms 정지 (CP1100) | 5 | 5 | 0 | 0 |
| CPU, 장애 순간부터 4300 ms 정지 (CG4300) | 5 | 5 | 0 | 0 |
| CPU, 장애 순간부터 4600 ms 정지 (CG4600) | 10 | 10 | 0 | 0 |
| CPU, 장애 순간부터 5000 ms 정지 (CG5000) | 5 | 5 | 0 | 0 |
| GIN, 복구 요청 때 2900 ms 정지 (G2900) | 5 | 5 | 0 | 0 |
| GIN, 복구 요청 때 2985 ms 정지 (G2985) | 5 | 5 | 0 | 0 |
| GIN, 복구 요청 때 2992 ms 정지 (G2992) | 5 | 5 | 0 | 0 |
| GIN, 복구 요청 때 2995 ms 정지 (G2995) | 10 | 10 | 0 | 0 |
| GIN, 복구 요청 때 2998 ms 정지 (G2998) | 10 | 10 | 0 | 0 |
| GIN, 복구 요청 때 3010 ms 정지 (G3010) | 5 | 5 | 0 | 0 |
| GIN, 복구 요청 때 3100 ms 정지 (G3100) | 5 | 5 | 0 | 0 |

따로 센 시행: 없음.

## 예측별 판정

| 예측 | id | n | 판정 | 놓친 시행 |
|---|---|--:|---|---|
| PROBE 정지 0, 900, 990 ms: 모두 살아 있음, 답은 정지 끝 뒤 0–5 ms | (CPa) | 15 | 맞음 | - |
| PROBE 정지 1008 ms: 10회 중 4회 이상 살아 있음 | (CPb) | 10 | 맞음 | - |
| PROBE 정지 1024 ms: 10회 중 6회 이하 살아 있음 | (CPc) | 10 | 맞음 | - |
| PROBE 정지 1040, 1100 ms: 모두 응답 없음, 대기 1000–1033 ms | (CPd) | 10 | 맞음 | - |
| PROBE 정지 셀 전체: 답과 대기 끝 중 먼저 오는 쪽이 판정을 정한다 | (CPe) | 45 | 맞음 | - |
| 응답 없음 시행 전체: 대기 끝 1000–1033 ms, 퍼짐 16 ms 이상 | (CPf) | 28 | 맞음 | - |
| 장애 순간 정지 4300 ms는 모두 살아 있음, 5000 ms는 모두 응답 없음 | (CGa) | 10 | 맞음 | - |
| 장애 순간 정지: 첫 CQE 뒤 남은 정지 995 ms 이하면 살아 있음, 1034 ms 이상이면 응답 없음 | (CGb) | 18 | 맞음 | - |
| 장애 순간 정지, 살아 있음 시행: 답은 PROBE 뒤 (x - 1)–(x + 6) ms | (CGc) | 12 | 틀림 | `lb_cg4600_t6` |
| GIN 정지 2900, 2985, 2992 ms: 모두 복구, ACK는 정지 끝 뒤 4.0–5.5 ms | (Ga) | 15 | 맞음 | - |
| GIN 정지 2995 ms: 뒤 끝 거절 0, 5회 이상 복구, 복구 ACK는 Prepare 뒤 3001.2 ms 안 | (Gb) | 10 | 맞음 | - |
| GIN 정지 2998, 3010, 3100 ms: 모두 핸드셰이크 시간 초과로 거절, rank 0 종료 코드 9 | (Gc) | 20 | 맞음 | - |
| GIN 거절 전체: 장애 조회 뒤 2998.8–3002.8 ms, 두 끝 사이는 10% 이하 | (Gd) | 21 | 틀림 | - |
| GIN 2998 ms 뒤 끝 거절에서 rank 1은 거절 전에 깨어 있음, 거절마다 rank 1이 요청 처리 | (Ge) | 30 | 맞음 | - |

n은 줄의 모든 범위에서 센 시행 수의 합이다(같은 시행이 여러 범위에 들어가면 여러 번 센다).

## 범위와 항목별 값

| id | 범위 | n | 항목 | 값 | 맞은 시행 | 결과 |
|---|---|--:|---|---|--:|---|
| (CPa) | CP0 | 5 | `ALL(sub_cause=='server_qp_err')` | True | 5 | 맞음 |
| (CPa) | CP0 | 5 | `ALL(stall_meas_ms<=probe_ms<=stall_meas_ms+5)` | True | 5 | 맞음 |
| (CPa) | CP900 | 5 | `ALL(sub_cause=='server_qp_err')` | True | 5 | 맞음 |
| (CPa) | CP900 | 5 | `ALL(stall_meas_ms<=probe_ms<=stall_meas_ms+5)` | True | 5 | 맞음 |
| (CPa) | CP990 | 5 | `ALL(sub_cause=='server_qp_err')` | True | 5 | 맞음 |
| (CPa) | CP990 | 5 | `ALL(stall_meas_ms<=probe_ms<=stall_meas_ms+5)` | True | 5 | 맞음 |
| (CPb) | CP1008 | 10 | `COUNT(sub_cause=='server_qp_err')` | 9 | 9 | 맞음 |
| (CPc) | CP1024 | 10 | `COUNT(sub_cause=='server_qp_err')` | 1 | 1 | 맞음 |
| (CPd) | CP1040 | 5 | `ALL(sub_cause=='no_answer')` | True | 5 | 맞음 |
| (CPd) | CP1040 | 5 | `ALL(1000<=probe_ms<=1033)` | True | 5 | 맞음 |
| (CPd) | CP1100 | 5 | `ALL(sub_cause=='no_answer')` | True | 5 | 맞음 |
| (CPd) | CP1100 | 5 | `ALL(1000<=probe_ms<=1033)` | True | 5 | 맞음 |
| (CPe) | CP0 | 5 | `ALL((sub_cause=='server_qp_err' and stall_meas_ms<=probe_ms<=stall_meas_ms+5 and probe_ms<=1033) or (sub_cause=='no_answer' and 1000<=probe_ms<=1033 and probe_ms<=stall_meas_ms+5))` | True | 5 | 맞음 |
| (CPe) | CP900 | 5 | `ALL((sub_cause=='server_qp_err' and stall_meas_ms<=probe_ms<=stall_meas_ms+5 and probe_ms<=1033) or (sub_cause=='no_answer' and 1000<=probe_ms<=1033 and probe_ms<=stall_meas_ms+5))` | True | 5 | 맞음 |
| (CPe) | CP990 | 5 | `ALL((sub_cause=='server_qp_err' and stall_meas_ms<=probe_ms<=stall_meas_ms+5 and probe_ms<=1033) or (sub_cause=='no_answer' and 1000<=probe_ms<=1033 and probe_ms<=stall_meas_ms+5))` | True | 5 | 맞음 |
| (CPe) | CP1008 | 10 | `ALL((sub_cause=='server_qp_err' and stall_meas_ms<=probe_ms<=stall_meas_ms+5 and probe_ms<=1033) or (sub_cause=='no_answer' and 1000<=probe_ms<=1033 and probe_ms<=stall_meas_ms+5))` | True | 10 | 맞음 |
| (CPe) | CP1024 | 10 | `ALL((sub_cause=='server_qp_err' and stall_meas_ms<=probe_ms<=stall_meas_ms+5 and probe_ms<=1033) or (sub_cause=='no_answer' and 1000<=probe_ms<=1033 and probe_ms<=stall_meas_ms+5))` | True | 10 | 맞음 |
| (CPe) | CP1040 | 5 | `ALL((sub_cause=='server_qp_err' and stall_meas_ms<=probe_ms<=stall_meas_ms+5 and probe_ms<=1033) or (sub_cause=='no_answer' and 1000<=probe_ms<=1033 and probe_ms<=stall_meas_ms+5))` | True | 5 | 맞음 |
| (CPe) | CP1100 | 5 | `ALL((sub_cause=='server_qp_err' and stall_meas_ms<=probe_ms<=stall_meas_ms+5 and probe_ms<=1033) or (sub_cause=='no_answer' and 1000<=probe_ms<=1033 and probe_ms<=stall_meas_ms+5))` | True | 5 | 맞음 |
| (CPf) | pooled CP0, CP900, CP990, CP1008, CP1024, CP1040, CP1100, CG4300, CG4600, CG5000 where sub_cause=='no_answer' | 28 | `ALL(1000<=probe_ms<=1033)` | True | 28 | 맞음 |
| (CPf) | pooled CP0, CP900, CP990, CP1008, CP1024, CP1040, CP1100, CG4300, CG4600, CG5000 where sub_cause=='no_answer' | 28 | `MAX(probe_ms)` | 1027.114 |  | 맞음 |
| (CPf) | pooled CP0, CP900, CP990, CP1008, CP1024, CP1040, CP1100, CG4300, CG4600, CG5000 where sub_cause=='no_answer' | 28 | `MIN(probe_ms)` | 1001.592 |  | 맞음 |
| (CGa) | CG4300 | 5 | `ALL(sub_cause=='server_qp_err')` | True | 5 | 맞음 |
| (CGa) | CG5000 | 5 | `ALL(sub_cause=='no_answer')` | True | 5 | 맞음 |
| (CGb) | pooled CG4300, CG4600, CG5000 where stall_meas_ms-cqe_ns/1e6<=995 | 12 | `ALL(sub_cause=='server_qp_err')` | True | 12 | 맞음 |
| (CGb) | pooled CG4300, CG4600, CG5000 where stall_meas_ms-cqe_ns/1e6>=1034 | 6 | `ALL(sub_cause=='no_answer')` | True | 6 | 맞음 |
| (CGc) | pooled CG4300, CG4600, CG5000 where sub_cause=='server_qp_err' | 12 | `ALL(stall_meas_ms-cqe_ns/1e6-1<=probe_ms<=stall_meas_ms-cqe_ns/1e6+6)` | False | 11 | 틀림 |
| (Ga) | G2900 | 5 | `ALL(rec_outcome=='recovered')` | True | 5 | 맞음 |
| (Ga) | G2900 | 5 | `ALL(4.0<=rec_t_ack-rec_t_prep-r1_stall_ms<=5.5)` | True | 5 | 맞음 |
| (Ga) | G2985 | 5 | `ALL(rec_outcome=='recovered')` | True | 5 | 맞음 |
| (Ga) | G2985 | 5 | `ALL(4.0<=rec_t_ack-rec_t_prep-r1_stall_ms<=5.5)` | True | 5 | 맞음 |
| (Ga) | G2992 | 5 | `ALL(rec_outcome=='recovered')` | True | 5 | 맞음 |
| (Ga) | G2992 | 5 | `ALL(4.0<=rec_t_ack-rec_t_prep-r1_stall_ms<=5.5)` | True | 5 | 맞음 |
| (Gb) | G2995 | 10 | `NONE(rec_outcome=='declined' and rec_t_decl-fault_t_query>=3001.7)` | True | 10 | 맞음 |
| (Gb) | G2995 | 10 | `COUNT(rec_outcome=='recovered')` | 9 | 9 | 맞음 |
| (Gb) | G2995 | 10 | `ALL(rec_outcome=='declined' or rec_t_ack-rec_t_prep<=3001.2)` | True | 10 | 맞음 |
| (Gc) | G2998 | 10 | `ALL(rec_outcome=='declined' and rec_reason=='handshake_timeout')` | True | 10 | 맞음 |
| (Gc) | G2998 | 10 | `MOST(r0rc==9)` | True | 10 | 맞음 |
| (Gc) | G3010 | 5 | `ALL(rec_outcome=='declined' and rec_reason=='handshake_timeout')` | True | 5 | 맞음 |
| (Gc) | G3010 | 5 | `MOST(r0rc==9)` | True | 5 | 맞음 |
| (Gc) | G3100 | 5 | `ALL(rec_outcome=='declined' and rec_reason=='handshake_timeout')` | True | 5 | 맞음 |
| (Gc) | G3100 | 5 | `MOST(r0rc==9)` | True | 5 | 맞음 |
| (Gd) | pooled G2900, G2985, G2992, G2995, G2998, G3010, G3100 where rec_outcome=='declined' | 21 | `ALL(2998.8<=rec_t_decl-fault_t_query<=3002.8)` | True | 21 | 틀림 |
| (Gd) | pooled G2900, G2985, G2992, G2995, G2998, G3010, G3100 where rec_outcome=='declined' | 21 | `COUNT(2999.9<rec_t_decl-fault_t_query<3001.7)` | 5 | 5 | 틀림 |
| (Gd) | pooled G2900, G2985, G2992, G2995, G2998, G3010, G3100 where rec_outcome=='declined' | 21 | `N()` | 21 |  | 틀림 |
| (Ge) | pooled G2998 where rec_outcome=='declined' and rec_t_decl-fault_t_query>=3001.7 | 9 | `ALL(r1_stall_end_r0clock<rec_t_decl)` | True | 9 | 맞음 |
| (Ge) | pooled G2900, G2985, G2992, G2995, G2998, G3010, G3100 where rec_outcome=='declined' | 21 | `ALL(r1_n_rxrec_after_stall>=1)` | True | 21 | 맞음 |

