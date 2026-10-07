# live_peer 채점 결과

`score.py`가 `predictions.csv`(태그 `prereg/live-peer-v1`)의 판정식을 EXPERIMENT.md 3.0절 규칙 그대로 적용한 결과다. 원자료: `live_peer/results/20261007` 아래 `A/`, `B/`(Release). 소스 예측 8줄은 채점하지 않는다. 시행별 값은 [trials_scored.csv](trials_scored.csv).

측정 예측 34줄 중 맞음 33, 틀림 1, 자료 없음 0.

## 시행 수

| 셀 | 시행 | 채점 | 장애 미적용 | 실행기 실패 | 카운터 관측 불가 | 실제 생존 미정 |
|---|--:|--:|--:|--:|--:|--:|
| 장애 없음 (A0) | 5 | 5 | 0 | 0 | 0 | 0 |
| 응답 QP 오류, 프로세스 응답 (A1) | 5 | 5 | 0 | 0 | 0 | 0 |
| 응답 프로세스 SIGKILL (A2) | 5 | 5 | 0 | 0 | 0 | 0 |
| 응답 QP RESET (A3) | 10 | 10 | 0 | 0 | 0 | 0 |
| 응답 QP INIT (A4) | 10 | 10 | 0 | 0 | 0 | 0 |
| 응답 QP RTR (A5) | 10 | 10 | 0 | 0 | 0 | 0 |
| 1250 ms 준비 안 됨 뒤 재무장 (A6) | 10 | 10 | 0 | 0 | 0 | 0 |
| QP 오류 + 8 s 정지 (A7) | 10 | 10 | 0 | 0 | 0 | 0 |
| 정상 QP + 8 s 정지 (A8) | 10 | 10 | 0 | 0 | 0 | 0 |
| QP 오류 + 제어 연결만 닫음 (A9) | 10 | 10 | 0 | 0 | 0 | 0 |
| 수신 버퍼 없음 (A10) | 5 | 5 | 0 | 0 | 0 | 0 |
| QP 파괴 뒤 새 QP (A11) | 5 | 5 | 0 | 0 | 0 | 0 |
| GIN 상대 QP 오류, 정지 없음 (B0) | 5 | 5 | 0 | 0 | 0 | 0 |
| GIN 상대 QP 오류 + 1 s 정지 (B1) | 10 | 10 | 0 | 0 | 0 | 0 |
| GIN 상대 QP 오류 + 6 s 정지 (B2) | 10 | 10 | 0 | 0 | 0 | 0 |
| GIN 장애 없음 + 6 s 정지 (B3) | 5 | 5 | 0 | 0 | 0 | 0 |

따로 센 시행: 없음.

## 예측별 판정

| 예측 | id | n | 맞은 시행 | 판정 | 놓친 시행 |
|---|---|--:|--:|---|---|
| 장애 없음: 10 ms 안에 정상 완료, 생존 확인 없음 | (A0) | 5 | 5 | 맞음 | - |
| 응답 QP 오류, 프로세스 응답(재현): 12/0x81, 3.40–3.90 s, 살아 있음 판정, QP 상태 ERR | (A1) | 5 | 5 | 맞음 | - |
| 응답 프로세스 SIGKILL(재현): 12/0x81, 죽음 판정, 실제로 죽음 | (A2) | 5 | 5 | 맞음 | - |
| 응답 QP RESET: 12/0x81, 3.40–3.90 s | (A3a) | 10 | 10 | 맞음 | - |
| 응답 QP RESET: 살아 있음 판정, QP 상태 RESET, 응답 쪽 비동기 이벤트 없음 | (A3b) | 10 | 10 | 맞음 | - |
| 응답 QP INIT: 12/0x81, 3.40–3.90 s | (A4a) | 10 | 10 | 맞음 | - |
| 응답 QP INIT: 살아 있음 판정, QP 상태 INIT, 응답 쪽 비동기 이벤트 없음 | (A4b) | 10 | 10 | 맞음 | - |
| 응답 QP를 같은 PSN으로 RTR까지만: 10 ms 안에 정상 완료, QP 상태 RTR | (A5) | 10 | 10 | 맞음 | - |
| 응답 QP를 1250 ms 동안 준비 안 됨으로 둔 뒤 재무장: 1.25–1.80 s에 정상 완료, QP 상태 RTS | (A6) | 10 | 10 | 맞음 | - |
| 응답 QP 오류 + 프로세스 8 s 정지: 12/0x81, 3.40–3.90 s | (A7a) | 10 | 10 | 맞음 | - |
| 응답 QP 오류 + 프로세스 8 s 정지: 응답 없음 판정(죽음 0), 재개 뒤 복구, 실제로 살아 있음 | (A7b) | 10 | 10 | 맞음 | - |
| 정상 QP + 프로세스 8 s 정지: 10 ms 안에 정상 완료, 상태 조회 응답 없음, 판정 없음, 재개 뒤 복구 | (A8) | 10 | 10 | 맞음 | - |
| 응답 QP 오류 + 제어 연결만 닫음: 12/0x81, 3.40–3.90 s | (A9a) | 10 | 10 | 맞음 | - |
| 응답 QP 오류 + 제어 연결만 닫음: 죽음 판정, 새 연결의 생존 질의에 같은 프로세스가 답함 | (A9b) | 10 | 10 | 맞음 | - |
| 수신 버퍼 없음(재현): 13/0x87, 11.5–13.5 ms, 생존 확인 없음 | (A10) | 5 | 5 | 맞음 | - |
| 응답 QP 파괴 뒤 새 QP INIT(재현): 12/0x81, 3.40–3.90 s, 살아 있음 판정, QP 상태 INIT | (A11) | 5 | 5 | 맞음 | - |
| GIN 상대 QP 오류, 정지 없음(재현): 복구, ACK는 Prepare 뒤 500 ms 안 | (B0) | 5 | 5 | 맞음 | - |
| GIN 상대 QP 오류 + 복구 요청 때 1 s 정지: 복구, ACK는 Prepare 뒤 1000–1500 ms | (B1) | 10 | 10 | 맞음 | - |
| GIN 상대 QP 오류 + 복구 요청 때 6 s 정지: 핸드셰이크 시간 초과로 거절(3000–3500 ms), rank 0 종료 코드 9 | (B2a) | 10 | 8 | 틀림 | `b2_t1`, `b2_t5` |
| GIN 상대 QP 오류 + 복구 요청 때 6 s 정지: rank 1이 거절 뒤 재개해 요청을 처리 | (B2b) | 10 | 10 | 맞음 | - |
| GIN 장애 없음 + 반복 60에서 6 s 정지: 장애 기록과 복구 없이 120회 모두 정확 | (B3) | 5 | 5 | 맞음 | - |
| 죽음 오판은 제어 연결만 닫은 셀에만 생긴다 | (O1) | 90 | 90 | 맞음 | - |
| 복구 불가 오판은 정지 + QP 오류 셀과 제어 연결을 닫은 셀에만 생긴다 | (O2) | 90 | 90 | 맞음 | - |
| GIN 거절 오판은 6 s 정지 셀에만 생긴다 | (O3) | 30 | 30 | 맞음 | - |
| 놓친 정지: 정상 QP + 정지와 GIN 장애 없음 + 정지에서 오류도 판정도 없다 | (O4) | 15 | 15 | 맞음 | - |
| 실제 혼잡 신호(np_cnp_sent, np_ecn_marked_roce_packets, rp_cnp_ignored) 모든 시행 +0 | (K1) | 125 | 125 | 맞음 | - |
| CPU 하네스 재시도 초과: rp_cnp_handled = roce_slow_restart_cnps = 적응 재전송 + 정규 타임아웃 - 1, 정규 타임아웃 6 | (K2) | 55 | 55 | 맞음 | - |
| 일시 장애: 오류 완료 없이 rp_cnp_handled가 오르고 roce_slow_restart_cnps와 같다 | (K3a) | 10 | 10 | 맞음 | - |
| 일시 장애: rp_cnp_handled = 적응 재전송 + 정규 타임아웃(재전송마다 하나) | (K3b) | 10 | 10 | 맞음 | - |
| 일시 장애: 정규 타임아웃 2 | (K3c) | 10 | 10 | 맞음 | - |
| ACK 타임아웃 없는 셀: rp_cnp_handled, roce_slow_restart_cnps, local_ack_timeout_err +0 | (K4) | 35 | 35 | 맞음 | - |
| 1부 sunny: rp_cnp_handled +0 | (K5) | 95 | 95 | 맞음 | - |
| GIN 상대 QP 오류: rain rp_cnp_handled 8 이상, q 카운터 +0, sunny +0 | (K6) | 25 | 25 | 맞음 | - |
| 50 ms 표본: 두 카운터 차이 1 이하, 게시와 첫 CQE + 100 ms 사이에만 증가 | (K7) | 25 | 25 | 맞음 | - |

n은 줄이 적용된 셀들의 채점 시행 수 합이고, 맞은 시행은 셀마다 판정식 항목 중 가장 적게 맞은 항목의 수를 더한 값이다. 판정식 항목별 수는 아래에 있다.

## 판정식 항목별 수

| 예측 | 셀 | n | 항목 | 맞은 시행 | 결과 |
|---|---|--:|---|--:|---|
| (A0) | 장애 없음 (A0) | 5 | `ALL(status==0)` | 5 | 맞음 |
| (A0) | 장애 없음 (A0) | 5 | `ALL(cqe_ns<10000000)` | 5 | 맞음 |
| (A0) | 장애 없음 (A0) | 5 | `ALL(sub_cause=='-')` | 5 | 맞음 |
| (A1) | 응답 QP 오류, 프로세스 응답 (A1) | 5 | `ALL(status==12 and vendor_err=='0x81')` | 5 | 맞음 |
| (A1) | 응답 QP 오류, 프로세스 응답 (A1) | 5 | `ALL(3400000000<=detect_ns<=3900000000)` | 5 | 맞음 |
| (A1) | 응답 QP 오류, 프로세스 응답 (A1) | 5 | `ALL(sub_cause=='server_qp_err')` | 5 | 맞음 |
| (A1) | 응답 QP 오류, 프로세스 응답 (A1) | 5 | `ALL(srv_qp_state=='ERR')` | 5 | 맞음 |
| (A2) | 응답 프로세스 SIGKILL (A2) | 5 | `ALL(status==12 and vendor_err=='0x81')` | 5 | 맞음 |
| (A2) | 응답 프로세스 SIGKILL (A2) | 5 | `ALL(sub_cause=='proc_kill')` | 5 | 맞음 |
| (A2) | 응답 프로세스 SIGKILL (A2) | 5 | `ALL(truth_alive==0)` | 5 | 맞음 |
| (A3a) | 응답 QP RESET (A3) | 10 | `MOST(status==12 and vendor_err=='0x81')` | 10 | 맞음 |
| (A3a) | 응답 QP RESET (A3) | 10 | `ALL(3400000000<=detect_ns<=3900000000)` | 10 | 맞음 |
| (A3b) | 응답 QP RESET (A3) | 10 | `MOST(sub_cause=='server_qp_err')` | 10 | 맞음 |
| (A3b) | 응답 QP RESET (A3) | 10 | `NONE(sub_cause in ('proc_kill','no_answer'))` | 10 | 맞음 |
| (A3b) | 응답 QP RESET (A3) | 10 | `MOST(srv_qp_state=='RESET')` | 10 | 맞음 |
| (A3b) | 응답 QP RESET (A3) | 10 | `ALL(srv_async=='none')` | 10 | 맞음 |
| (A4a) | 응답 QP INIT (A4) | 10 | `MOST(status==12 and vendor_err=='0x81')` | 10 | 맞음 |
| (A4a) | 응답 QP INIT (A4) | 10 | `ALL(3400000000<=detect_ns<=3900000000)` | 10 | 맞음 |
| (A4b) | 응답 QP INIT (A4) | 10 | `MOST(sub_cause=='server_qp_err')` | 10 | 맞음 |
| (A4b) | 응답 QP INIT (A4) | 10 | `NONE(sub_cause in ('proc_kill','no_answer'))` | 10 | 맞음 |
| (A4b) | 응답 QP INIT (A4) | 10 | `MOST(srv_qp_state=='INIT')` | 10 | 맞음 |
| (A4b) | 응답 QP INIT (A4) | 10 | `ALL(srv_async=='none')` | 10 | 맞음 |
| (A5) | 응답 QP RTR (A5) | 10 | `ALL(status==0)` | 10 | 맞음 |
| (A5) | 응답 QP RTR (A5) | 10 | `ALL(cqe_ns<10000000)` | 10 | 맞음 |
| (A5) | 응답 QP RTR (A5) | 10 | `MOST(srv_qp_state=='RTR')` | 10 | 맞음 |
| (A6) | 1250 ms 준비 안 됨 뒤 재무장 (A6) | 10 | `ALL(status==0)` | 10 | 맞음 |
| (A6) | 1250 ms 준비 안 됨 뒤 재무장 (A6) | 10 | `ALL(1250000000<=cqe_ns<=1800000000)` | 10 | 맞음 |
| (A6) | 1250 ms 준비 안 됨 뒤 재무장 (A6) | 10 | `MOST(srv_qp_state=='RTS')` | 10 | 맞음 |
| (A7a) | QP 오류 + 8 s 정지 (A7) | 10 | `MOST(status==12 and vendor_err=='0x81')` | 10 | 맞음 |
| (A7a) | QP 오류 + 8 s 정지 (A7) | 10 | `ALL(3400000000<=detect_ns<=3900000000)` | 10 | 맞음 |
| (A7b) | QP 오류 + 8 s 정지 (A7) | 10 | `MOST(sub_cause=='no_answer')` | 10 | 맞음 |
| (A7b) | QP 오류 + 8 s 정지 (A7) | 10 | `NONE(sub_cause=='proc_kill')` | 10 | 맞음 |
| (A7b) | QP 오류 + 8 s 정지 (A7) | 10 | `MOST(verify_ok==1)` | 10 | 맞음 |
| (A7b) | QP 오류 + 8 s 정지 (A7) | 10 | `ALL(truth_alive==1)` | 10 | 맞음 |
| (A8) | 정상 QP + 8 s 정지 (A8) | 10 | `ALL(status==0)` | 10 | 맞음 |
| (A8) | 정상 QP + 8 s 정지 (A8) | 10 | `ALL(cqe_ns<10000000)` | 10 | 맞음 |
| (A8) | 정상 QP + 8 s 정지 (A8) | 10 | `MOST(srv_qp_state=='?')` | 10 | 맞음 |
| (A8) | 정상 QP + 8 s 정지 (A8) | 10 | `ALL(sub_cause=='-')` | 10 | 맞음 |
| (A8) | 정상 QP + 8 s 정지 (A8) | 10 | `MOST(verify_ok==1)` | 10 | 맞음 |
| (A9a) | QP 오류 + 제어 연결만 닫음 (A9) | 10 | `MOST(status==12 and vendor_err=='0x81')` | 10 | 맞음 |
| (A9a) | QP 오류 + 제어 연결만 닫음 (A9) | 10 | `ALL(3400000000<=detect_ns<=3900000000)` | 10 | 맞음 |
| (A9b) | QP 오류 + 제어 연결만 닫음 (A9) | 10 | `MOST(sub_cause=='proc_kill')` | 10 | 맞음 |
| (A9b) | QP 오류 + 제어 연결만 닫음 (A9) | 10 | `MOST(truth_alive==1 and truth_how=='alive_q')` | 10 | 맞음 |
| (A10) | 수신 버퍼 없음 (A10) | 5 | `ALL(status==13 and vendor_err=='0x87')` | 5 | 맞음 |
| (A10) | 수신 버퍼 없음 (A10) | 5 | `ALL(11500000<=detect_ns<=13500000)` | 5 | 맞음 |
| (A10) | 수신 버퍼 없음 (A10) | 5 | `ALL(sub_cause=='-')` | 5 | 맞음 |
| (A10) | 수신 버퍼 없음 (A10) | 5 | `ALL(peer_alive==1)` | 5 | 맞음 |
| (A11) | QP 파괴 뒤 새 QP (A11) | 5 | `ALL(status==12 and vendor_err=='0x81')` | 5 | 맞음 |
| (A11) | QP 파괴 뒤 새 QP (A11) | 5 | `ALL(3400000000<=detect_ns<=3900000000)` | 5 | 맞음 |
| (A11) | QP 파괴 뒤 새 QP (A11) | 5 | `ALL(sub_cause=='server_qp_err')` | 5 | 맞음 |
| (A11) | QP 파괴 뒤 새 QP (A11) | 5 | `ALL(srv_qp_state=='INIT')` | 5 | 맞음 |
| (B0) | GIN 상대 QP 오류, 정지 없음 (B0) | 5 | `ALL(rec_outcome=='recovered')` | 5 | 맞음 |
| (B0) | GIN 상대 QP 오류, 정지 없음 (B0) | 5 | `ALL(rec_t_ack-rec_t_prep<500)` | 5 | 맞음 |
| (B1) | GIN 상대 QP 오류 + 1 s 정지 (B1) | 10 | `MOST(rec_outcome=='recovered')` | 10 | 맞음 |
| (B1) | GIN 상대 QP 오류 + 1 s 정지 (B1) | 10 | `NONE(rec_outcome=='declined')` | 10 | 맞음 |
| (B1) | GIN 상대 QP 오류 + 1 s 정지 (B1) | 10 | `ALL(1000<=rec_t_ack-rec_t_prep<=1500)` | 10 | 맞음 |
| (B2a) | GIN 상대 QP 오류 + 6 s 정지 (B2) | 10 | `MOST(rec_outcome=='declined' and rec_reason=='handshake_timeout')` | 10 | 맞음 |
| (B2a) | GIN 상대 QP 오류 + 6 s 정지 (B2) | 10 | `NONE(rec_outcome=='recovered')` | 10 | 맞음 |
| (B2a) | GIN 상대 QP 오류 + 6 s 정지 (B2) | 10 | `ALL(3000<=rec_t_decl-fault_t_query<=3500)` | 8 | 틀림 |
| (B2a) | GIN 상대 QP 오류 + 6 s 정지 (B2) | 10 | `MOST(r0rc==9)` | 10 | 맞음 |
| (B2b) | GIN 상대 QP 오류 + 6 s 정지 (B2) | 10 | `MOST(r1_stall_end_r0clock>rec_t_decl)` | 10 | 맞음 |
| (B2b) | GIN 상대 QP 오류 + 6 s 정지 (B2) | 10 | `MOST(r1_n_rxrec_after_stall>=1)` | 10 | 맞음 |
| (B3) | GIN 장애 없음 + 6 s 정지 (B3) | 5 | `ALL(n_fault_ev==0 and n_rec_ev==0)` | 5 | 맞음 |
| (B3) | GIN 장애 없음 + 6 s 정지 (B3) | 5 | `ALL(r0_iters_ok==120 and r1_iters_ok==120 and r1_data_check=='ok')` | 5 | 맞음 |
| (B3) | GIN 장애 없음 + 6 s 정지 (B3) | 5 | `ALL(r0rc==0)` | 5 | 맞음 |
| (O1) | QP 오류 + 제어 연결만 닫음 (A9) | 10 | `MOST(truth_alive==1 and sub_cause=='proc_kill')` | 10 | 맞음 |
| (O1) | 장애 없음 (A0) | 5 | `NONE(truth_alive==1 and sub_cause=='proc_kill')` | 5 | 맞음 |
| (O1) | 응답 QP 오류, 프로세스 응답 (A1) | 5 | `NONE(truth_alive==1 and sub_cause=='proc_kill')` | 5 | 맞음 |
| (O1) | 응답 QP RESET (A3) | 10 | `NONE(truth_alive==1 and sub_cause=='proc_kill')` | 10 | 맞음 |
| (O1) | 응답 QP INIT (A4) | 10 | `NONE(truth_alive==1 and sub_cause=='proc_kill')` | 10 | 맞음 |
| (O1) | 응답 QP RTR (A5) | 10 | `NONE(truth_alive==1 and sub_cause=='proc_kill')` | 10 | 맞음 |
| (O1) | 1250 ms 준비 안 됨 뒤 재무장 (A6) | 10 | `NONE(truth_alive==1 and sub_cause=='proc_kill')` | 10 | 맞음 |
| (O1) | QP 오류 + 8 s 정지 (A7) | 10 | `NONE(truth_alive==1 and sub_cause=='proc_kill')` | 10 | 맞음 |
| (O1) | 정상 QP + 8 s 정지 (A8) | 10 | `NONE(truth_alive==1 and sub_cause=='proc_kill')` | 10 | 맞음 |
| (O1) | 수신 버퍼 없음 (A10) | 5 | `NONE(truth_alive==1 and sub_cause=='proc_kill')` | 5 | 맞음 |
| (O1) | QP 파괴 뒤 새 QP (A11) | 5 | `NONE(truth_alive==1 and sub_cause=='proc_kill')` | 5 | 맞음 |
| (O2) | QP 오류 + 8 s 정지 (A7) | 10 | `MOST(truth_alive==1 and sub_cause in ('proc_kill','no_answer'))` | 10 | 맞음 |
| (O2) | QP 오류 + 제어 연결만 닫음 (A9) | 10 | `MOST(truth_alive==1 and sub_cause in ('proc_kill','no_answer'))` | 10 | 맞음 |
| (O2) | 장애 없음 (A0) | 5 | `NONE(truth_alive==1 and sub_cause in ('proc_kill','no_answer'))` | 5 | 맞음 |
| (O2) | 응답 QP 오류, 프로세스 응답 (A1) | 5 | `NONE(truth_alive==1 and sub_cause in ('proc_kill','no_answer'))` | 5 | 맞음 |
| (O2) | 응답 QP RESET (A3) | 10 | `NONE(truth_alive==1 and sub_cause in ('proc_kill','no_answer'))` | 10 | 맞음 |
| (O2) | 응답 QP INIT (A4) | 10 | `NONE(truth_alive==1 and sub_cause in ('proc_kill','no_answer'))` | 10 | 맞음 |
| (O2) | 응답 QP RTR (A5) | 10 | `NONE(truth_alive==1 and sub_cause in ('proc_kill','no_answer'))` | 10 | 맞음 |
| (O2) | 1250 ms 준비 안 됨 뒤 재무장 (A6) | 10 | `NONE(truth_alive==1 and sub_cause in ('proc_kill','no_answer'))` | 10 | 맞음 |
| (O2) | 정상 QP + 8 s 정지 (A8) | 10 | `NONE(truth_alive==1 and sub_cause in ('proc_kill','no_answer'))` | 10 | 맞음 |
| (O2) | 수신 버퍼 없음 (A10) | 5 | `NONE(truth_alive==1 and sub_cause in ('proc_kill','no_answer'))` | 5 | 맞음 |
| (O2) | QP 파괴 뒤 새 QP (A11) | 5 | `NONE(truth_alive==1 and sub_cause in ('proc_kill','no_answer'))` | 5 | 맞음 |
| (O3) | GIN 상대 QP 오류 + 6 s 정지 (B2) | 10 | `MOST(rec_outcome=='declined' and r1_stall_end_r0clock>rec_t_decl)` | 10 | 맞음 |
| (O3) | GIN 상대 QP 오류, 정지 없음 (B0) | 5 | `NONE(rec_outcome=='declined')` | 5 | 맞음 |
| (O3) | GIN 상대 QP 오류 + 1 s 정지 (B1) | 10 | `NONE(rec_outcome=='declined')` | 10 | 맞음 |
| (O3) | GIN 장애 없음 + 6 s 정지 (B3) | 5 | `NONE(rec_outcome=='declined')` | 5 | 맞음 |
| (O4) | 정상 QP + 8 s 정지 (A8) | 10 | `ALL(status==0 and sub_cause=='-')` | 10 | 맞음 |
| (O4) | GIN 장애 없음 + 6 s 정지 (B3) | 5 | `ALL(n_fault_ev==0 and n_rec_ev==0 and r0rc==0)` | 5 | 맞음 |
| (K1) | 장애 없음 (A0) | 5 | `ALL(rain.np_cnp_sent==0 and rain.np_ecn_marked_roce_packets==0 and rain.rp_cnp_ignored==0 and sunny.np_cnp_sent==0 and sunny.np_ecn_marked_roce_packets==0 and sunny.rp_cnp_ignored==0)` | 5 | 맞음 |
| (K1) | 응답 QP 오류, 프로세스 응답 (A1) | 5 | `ALL(rain.np_cnp_sent==0 and rain.np_ecn_marked_roce_packets==0 and rain.rp_cnp_ignored==0 and sunny.np_cnp_sent==0 and sunny.np_ecn_marked_roce_packets==0 and sunny.rp_cnp_ignored==0)` | 5 | 맞음 |
| (K1) | 응답 프로세스 SIGKILL (A2) | 5 | `ALL(rain.np_cnp_sent==0 and rain.np_ecn_marked_roce_packets==0 and rain.rp_cnp_ignored==0 and sunny.np_cnp_sent==0 and sunny.np_ecn_marked_roce_packets==0 and sunny.rp_cnp_ignored==0)` | 5 | 맞음 |
| (K1) | 응답 QP RESET (A3) | 10 | `ALL(rain.np_cnp_sent==0 and rain.np_ecn_marked_roce_packets==0 and rain.rp_cnp_ignored==0 and sunny.np_cnp_sent==0 and sunny.np_ecn_marked_roce_packets==0 and sunny.rp_cnp_ignored==0)` | 10 | 맞음 |
| (K1) | 응답 QP INIT (A4) | 10 | `ALL(rain.np_cnp_sent==0 and rain.np_ecn_marked_roce_packets==0 and rain.rp_cnp_ignored==0 and sunny.np_cnp_sent==0 and sunny.np_ecn_marked_roce_packets==0 and sunny.rp_cnp_ignored==0)` | 10 | 맞음 |
| (K1) | 응답 QP RTR (A5) | 10 | `ALL(rain.np_cnp_sent==0 and rain.np_ecn_marked_roce_packets==0 and rain.rp_cnp_ignored==0 and sunny.np_cnp_sent==0 and sunny.np_ecn_marked_roce_packets==0 and sunny.rp_cnp_ignored==0)` | 10 | 맞음 |
| (K1) | 1250 ms 준비 안 됨 뒤 재무장 (A6) | 10 | `ALL(rain.np_cnp_sent==0 and rain.np_ecn_marked_roce_packets==0 and rain.rp_cnp_ignored==0 and sunny.np_cnp_sent==0 and sunny.np_ecn_marked_roce_packets==0 and sunny.rp_cnp_ignored==0)` | 10 | 맞음 |
| (K1) | QP 오류 + 8 s 정지 (A7) | 10 | `ALL(rain.np_cnp_sent==0 and rain.np_ecn_marked_roce_packets==0 and rain.rp_cnp_ignored==0 and sunny.np_cnp_sent==0 and sunny.np_ecn_marked_roce_packets==0 and sunny.rp_cnp_ignored==0)` | 10 | 맞음 |
| (K1) | 정상 QP + 8 s 정지 (A8) | 10 | `ALL(rain.np_cnp_sent==0 and rain.np_ecn_marked_roce_packets==0 and rain.rp_cnp_ignored==0 and sunny.np_cnp_sent==0 and sunny.np_ecn_marked_roce_packets==0 and sunny.rp_cnp_ignored==0)` | 10 | 맞음 |
| (K1) | QP 오류 + 제어 연결만 닫음 (A9) | 10 | `ALL(rain.np_cnp_sent==0 and rain.np_ecn_marked_roce_packets==0 and rain.rp_cnp_ignored==0 and sunny.np_cnp_sent==0 and sunny.np_ecn_marked_roce_packets==0 and sunny.rp_cnp_ignored==0)` | 10 | 맞음 |
| (K1) | 수신 버퍼 없음 (A10) | 5 | `ALL(rain.np_cnp_sent==0 and rain.np_ecn_marked_roce_packets==0 and rain.rp_cnp_ignored==0 and sunny.np_cnp_sent==0 and sunny.np_ecn_marked_roce_packets==0 and sunny.rp_cnp_ignored==0)` | 5 | 맞음 |
| (K1) | QP 파괴 뒤 새 QP (A11) | 5 | `ALL(rain.np_cnp_sent==0 and rain.np_ecn_marked_roce_packets==0 and rain.rp_cnp_ignored==0 and sunny.np_cnp_sent==0 and sunny.np_ecn_marked_roce_packets==0 and sunny.rp_cnp_ignored==0)` | 5 | 맞음 |
| (K1) | GIN 상대 QP 오류, 정지 없음 (B0) | 5 | `ALL(rain.np_cnp_sent==0 and rain.np_ecn_marked_roce_packets==0 and rain.rp_cnp_ignored==0 and sunny.np_cnp_sent==0 and sunny.np_ecn_marked_roce_packets==0 and sunny.rp_cnp_ignored==0)` | 5 | 맞음 |
| (K1) | GIN 상대 QP 오류 + 1 s 정지 (B1) | 10 | `ALL(rain.np_cnp_sent==0 and rain.np_ecn_marked_roce_packets==0 and rain.rp_cnp_ignored==0 and sunny.np_cnp_sent==0 and sunny.np_ecn_marked_roce_packets==0 and sunny.rp_cnp_ignored==0)` | 10 | 맞음 |
| (K1) | GIN 상대 QP 오류 + 6 s 정지 (B2) | 10 | `ALL(rain.np_cnp_sent==0 and rain.np_ecn_marked_roce_packets==0 and rain.rp_cnp_ignored==0 and sunny.np_cnp_sent==0 and sunny.np_ecn_marked_roce_packets==0 and sunny.rp_cnp_ignored==0)` | 10 | 맞음 |
| (K1) | GIN 장애 없음 + 6 s 정지 (B3) | 5 | `ALL(rain.np_cnp_sent==0 and rain.np_ecn_marked_roce_packets==0 and rain.rp_cnp_ignored==0 and sunny.np_cnp_sent==0 and sunny.np_ecn_marked_roce_packets==0 and sunny.rp_cnp_ignored==0)` | 5 | 맞음 |
| (K2) | 응답 QP 오류, 프로세스 응답 (A1) | 5 | `ALL(rain.rp_cnp_handled==rain.roce_slow_restart_cnps)` | 5 | 맞음 |
| (K2) | 응답 QP 오류, 프로세스 응답 (A1) | 5 | `MOST(rain.rp_cnp_handled==rain.roce_adp_retrans+rain.local_ack_timeout_err-1)` | 5 | 맞음 |
| (K2) | 응답 QP 오류, 프로세스 응답 (A1) | 5 | `MOST(rain.local_ack_timeout_err==6)` | 5 | 맞음 |
| (K2) | 응답 프로세스 SIGKILL (A2) | 5 | `ALL(rain.rp_cnp_handled==rain.roce_slow_restart_cnps)` | 5 | 맞음 |
| (K2) | 응답 프로세스 SIGKILL (A2) | 5 | `MOST(rain.rp_cnp_handled==rain.roce_adp_retrans+rain.local_ack_timeout_err-1)` | 5 | 맞음 |
| (K2) | 응답 프로세스 SIGKILL (A2) | 5 | `MOST(rain.local_ack_timeout_err==6)` | 5 | 맞음 |
| (K2) | 응답 QP RESET (A3) | 10 | `ALL(rain.rp_cnp_handled==rain.roce_slow_restart_cnps)` | 10 | 맞음 |
| (K2) | 응답 QP RESET (A3) | 10 | `MOST(rain.rp_cnp_handled==rain.roce_adp_retrans+rain.local_ack_timeout_err-1)` | 10 | 맞음 |
| (K2) | 응답 QP RESET (A3) | 10 | `MOST(rain.local_ack_timeout_err==6)` | 10 | 맞음 |
| (K2) | 응답 QP INIT (A4) | 10 | `ALL(rain.rp_cnp_handled==rain.roce_slow_restart_cnps)` | 10 | 맞음 |
| (K2) | 응답 QP INIT (A4) | 10 | `MOST(rain.rp_cnp_handled==rain.roce_adp_retrans+rain.local_ack_timeout_err-1)` | 10 | 맞음 |
| (K2) | 응답 QP INIT (A4) | 10 | `MOST(rain.local_ack_timeout_err==6)` | 10 | 맞음 |
| (K2) | QP 오류 + 8 s 정지 (A7) | 10 | `ALL(rain.rp_cnp_handled==rain.roce_slow_restart_cnps)` | 10 | 맞음 |
| (K2) | QP 오류 + 8 s 정지 (A7) | 10 | `MOST(rain.rp_cnp_handled==rain.roce_adp_retrans+rain.local_ack_timeout_err-1)` | 10 | 맞음 |
| (K2) | QP 오류 + 8 s 정지 (A7) | 10 | `MOST(rain.local_ack_timeout_err==6)` | 10 | 맞음 |
| (K2) | QP 오류 + 제어 연결만 닫음 (A9) | 10 | `ALL(rain.rp_cnp_handled==rain.roce_slow_restart_cnps)` | 10 | 맞음 |
| (K2) | QP 오류 + 제어 연결만 닫음 (A9) | 10 | `MOST(rain.rp_cnp_handled==rain.roce_adp_retrans+rain.local_ack_timeout_err-1)` | 10 | 맞음 |
| (K2) | QP 오류 + 제어 연결만 닫음 (A9) | 10 | `MOST(rain.local_ack_timeout_err==6)` | 10 | 맞음 |
| (K2) | QP 파괴 뒤 새 QP (A11) | 5 | `ALL(rain.rp_cnp_handled==rain.roce_slow_restart_cnps)` | 5 | 맞음 |
| (K2) | QP 파괴 뒤 새 QP (A11) | 5 | `MOST(rain.rp_cnp_handled==rain.roce_adp_retrans+rain.local_ack_timeout_err-1)` | 5 | 맞음 |
| (K2) | QP 파괴 뒤 새 QP (A11) | 5 | `MOST(rain.local_ack_timeout_err==6)` | 5 | 맞음 |
| (K3a) | 1250 ms 준비 안 됨 뒤 재무장 (A6) | 10 | `ALL(rain.req_cqe_error==0 and rain.rp_cnp_handled>=1 and rain.rp_cnp_handled==rain.roce_slow_restart_cnps)` | 10 | 맞음 |
| (K3b) | 1250 ms 준비 안 됨 뒤 재무장 (A6) | 10 | `MOST(rain.rp_cnp_handled==rain.roce_adp_retrans+rain.local_ack_timeout_err)` | 10 | 맞음 |
| (K3c) | 1250 ms 준비 안 됨 뒤 재무장 (A6) | 10 | `MOST(rain.local_ack_timeout_err==2)` | 10 | 맞음 |
| (K3c) | 1250 ms 준비 안 됨 뒤 재무장 (A6) | 10 | `ALL(1<=rain.local_ack_timeout_err<=3)` | 10 | 맞음 |
| (K4) | 장애 없음 (A0) | 5 | `ALL(rain.rp_cnp_handled==0 and rain.roce_slow_restart_cnps==0 and rain.local_ack_timeout_err==0)` | 5 | 맞음 |
| (K4) | 응답 QP RTR (A5) | 10 | `ALL(rain.rp_cnp_handled==0 and rain.roce_slow_restart_cnps==0 and rain.local_ack_timeout_err==0)` | 10 | 맞음 |
| (K4) | 정상 QP + 8 s 정지 (A8) | 10 | `ALL(rain.rp_cnp_handled==0 and rain.roce_slow_restart_cnps==0 and rain.local_ack_timeout_err==0)` | 10 | 맞음 |
| (K4) | 수신 버퍼 없음 (A10) | 5 | `ALL(rain.rp_cnp_handled==0 and rain.roce_slow_restart_cnps==0 and rain.local_ack_timeout_err==0)` | 5 | 맞음 |
| (K4) | GIN 장애 없음 + 6 s 정지 (B3) | 5 | `ALL(rain.rp_cnp_handled==0 and rain.roce_slow_restart_cnps==0 and rain.local_ack_timeout_err==0)` | 5 | 맞음 |
| (K5) | 장애 없음 (A0) | 5 | `ALL(sunny.rp_cnp_handled==0)` | 5 | 맞음 |
| (K5) | 응답 QP 오류, 프로세스 응답 (A1) | 5 | `ALL(sunny.rp_cnp_handled==0)` | 5 | 맞음 |
| (K5) | 응답 프로세스 SIGKILL (A2) | 5 | `ALL(sunny.rp_cnp_handled==0)` | 5 | 맞음 |
| (K5) | 응답 QP RESET (A3) | 10 | `ALL(sunny.rp_cnp_handled==0)` | 10 | 맞음 |
| (K5) | 응답 QP INIT (A4) | 10 | `ALL(sunny.rp_cnp_handled==0)` | 10 | 맞음 |
| (K5) | 응답 QP RTR (A5) | 10 | `ALL(sunny.rp_cnp_handled==0)` | 10 | 맞음 |
| (K5) | 1250 ms 준비 안 됨 뒤 재무장 (A6) | 10 | `ALL(sunny.rp_cnp_handled==0)` | 10 | 맞음 |
| (K5) | QP 오류 + 8 s 정지 (A7) | 10 | `ALL(sunny.rp_cnp_handled==0)` | 10 | 맞음 |
| (K5) | 정상 QP + 8 s 정지 (A8) | 10 | `ALL(sunny.rp_cnp_handled==0)` | 10 | 맞음 |
| (K5) | QP 오류 + 제어 연결만 닫음 (A9) | 10 | `ALL(sunny.rp_cnp_handled==0)` | 10 | 맞음 |
| (K5) | 수신 버퍼 없음 (A10) | 5 | `ALL(sunny.rp_cnp_handled==0)` | 5 | 맞음 |
| (K5) | QP 파괴 뒤 새 QP (A11) | 5 | `ALL(sunny.rp_cnp_handled==0)` | 5 | 맞음 |
| (K6) | GIN 상대 QP 오류, 정지 없음 (B0) | 5 | `ALL(rain.rp_cnp_handled>=8 and rain.roce_slow_restart_cnps==0 and rain.local_ack_timeout_err==0 and sunny.rp_cnp_handled==0)` | 5 | 맞음 |
| (K6) | GIN 상대 QP 오류 + 1 s 정지 (B1) | 10 | `ALL(rain.rp_cnp_handled>=8 and rain.roce_slow_restart_cnps==0 and rain.local_ack_timeout_err==0 and sunny.rp_cnp_handled==0)` | 10 | 맞음 |
| (K6) | GIN 상대 QP 오류 + 6 s 정지 (B2) | 10 | `ALL(rain.rp_cnp_handled>=8 and rain.roce_slow_restart_cnps==0 and rain.local_ack_timeout_err==0 and sunny.rp_cnp_handled==0)` | 10 | 맞음 |
| (K7) | 응답 QP 오류, 프로세스 응답 (A1) | 5 | `ALL(smp_diff_max<=1)` | 5 | 맞음 |
| (K7) | 응답 QP 오류, 프로세스 응답 (A1) | 5 | `ALL(smp_first_inc_ns>=t_post_mono_ns)` | 5 | 맞음 |
| (K7) | 응답 QP 오류, 프로세스 응답 (A1) | 5 | `ALL(smp_last_inc_ns<=t_post_mono_ns+cqe_ns+100000000)` | 5 | 맞음 |
| (K7) | 응답 QP RESET (A3) | 10 | `ALL(smp_diff_max<=1)` | 10 | 맞음 |
| (K7) | 응답 QP RESET (A3) | 10 | `ALL(smp_first_inc_ns>=t_post_mono_ns)` | 10 | 맞음 |
| (K7) | 응답 QP RESET (A3) | 10 | `ALL(smp_last_inc_ns<=t_post_mono_ns+cqe_ns+100000000)` | 10 | 맞음 |
| (K7) | 1250 ms 준비 안 됨 뒤 재무장 (A6) | 10 | `ALL(smp_diff_max<=1)` | 10 | 맞음 |
| (K7) | 1250 ms 준비 안 됨 뒤 재무장 (A6) | 10 | `ALL(smp_first_inc_ns>=t_post_mono_ns)` | 10 | 맞음 |
| (K7) | 1250 ms 준비 안 됨 뒤 재무장 (A6) | 10 | `ALL(smp_last_inc_ns<=t_post_mono_ns+cqe_ns+100000000)` | 10 | 맞음 |

