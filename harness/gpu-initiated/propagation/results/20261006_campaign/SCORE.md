# Campaign score

Scored by `campaign/score.py` against `PREDICTIONS.md` (tag prereg/propagation-v1).
GP and GG F4 trials come from `../20261006_f4rerun` (DEVIATIONS 10).
A miss is an outcome outside the predicted class, so any miss fails a cell.

| id | cells | n | hits | rule | verdict | Wilson 95% | misses | note |
|---|---|--:|--:|---|---|---|---|---|
| EV1a | CPU responder, F2 | 10 | 10 | 90 | **holds** | 0.72-1.00 |  |  |
| EV1b | CPU responder, rem_inv_req | 10 | 10 | 90 | **holds** | 0.72-1.00 |  |  |
| EV1c | CPU responder, rnr | 10 | 10 | 90 | **holds** | 0.72-1.00 |  |  |
| EV1d | CPU responder, F1 F3 F4 F0 partial_write | 35 | 35 | 90 | **holds** | 0.90-1.00 |  | F4: responder dead, 10 not observable, reported apart (DEVIATIONS 4) |
| EV1e | CPU requester, all faults | 75 | 75 | 90 | **holds** | 0.95-1.00 |  |  |
| EV2a | CPU responder QP state, F2 rem_inv_req | 20 | 20 | 90 | **holds** | 0.84-1.00 |  |  |
| EV2b | CPU responder QP state, rnr F1 | 20 | 20 | 90 | **holds** | 0.84-1.00 |  |  |
| EV3a | GP target, F2: async fatal event on QP (access violation) in r1 log | 10 | 10 | 90 | **holds** | 0.72-1.00 |  |  |
| EV3a-blind | retained 2026-09-23 GIN proxy F2 r1 logs | 6 | 6 | all | **holds** | 0.61-1.00 |  | not observable: no NCCL output or no REM_ACCESS on r0 (DEVIATIONS 11) 6 not observable. |
| EV3b | GP target, F2: r1 async error stays success | 10 | 10 | 90 | **holds** | 0.72-1.00 |  |  |
| EV3c | GP target, F1 F3 F4: no async QP event on r1 | 30 | 30 | 90 | **holds** | 0.89-1.00 |  |  |
| EV4 | GG GQ NC NG NX ND NF, both ranks: no QP-affiliated async error | 180 | 180 | all | **holds** | 0.98-1.00 |  |  |
| EV5a | GG GQ NF ND, both nodes: 4 error counters +0 | 150 | 150 | all | **holds** | 0.97-1.00 |  |  |
| EV5b | NC NG NX F4, both nodes: 4 error counters +0 | 15 | 15 | all | **holds** | 0.80-1.00 |  |  |
| EV5c | CPU GP requester, F3 F4: local_ack_timeout_err >= 6 and req_cqe_error >= 1 | 40 | 30 | 90 | **fails** | 0.60-0.86 | gp_F4_timeout_t1, gp_F4_timeout_t2, gp_F4_timeout_t3, gp_F4_timeout_t4, gp_F4_timeout_t5, gp_F4_timeout_t6 ... |  |
| EV5d | CPU GP requester, F1 F2: req_cqe_error >= 1 | 40 | 40 | 90 | **holds** | 0.91-1.00 |  |  |
| NET1a | NET stock path, F2: requester status 10 / 0x88 and ncclRemoteError | 10 | 10 | 90 | **holds** | 0.72-1.00 |  |  |
| NET1b | NET stock path, F2: target async fatal event and a target API error | 10 | 10 | 90 | **holds** | 0.72-1.00 |  |  |
| NET1c | NET Stage 2, F2: declined, ncclRemoteError, no replay | 10 | 9 | 90 | **fails** | 0.60-0.98 | net_F2_t1 |  |
| D1 | GG GPU doorbell, F2 F3 F4 blocking: flush success on the failed op and a host error | 30 | 21 | 90 | **fails** | 0.52-0.83 | gg_F4_blocking_t1, gg_F4_blocking_t2, gg_F4_blocking_t3, gg_F4_blocking_t4, gg_F4_blocking_t5, gg_F4_blocking_t6 ... | device -EIO is source-only; scored on the flush and the host error |
| D2 | GG blocking F4: first flush after the kill returns success | 10 | 1 | 90 | **fails** | 0.02-0.40 | gg_F4_blocking_t1, gg_F4_blocking_t2, gg_F4_blocking_t3, gg_F4_blocking_t4, gg_F4_blocking_t5, gg_F4_blocking_t6 ... |  |
| T1 | every variant, F0: no error and teardown within 5 s on both ranks | 45 | 45 | 90 | **holds** | 0.92-1.00 |  |  |
| T2 | NC NG NX, F4: PE 0 nvshmem_finalize does not return within 30 s | 15 | 15 | all | **holds** | 0.80-1.00 |  |  |
| T3 | GG GQ blocking F1-F3: r0 teardown returns, r1 does not | 40 | 40 | 90 | **holds** | 0.91-1.00 |  |  |
| T4 | NF: F1 F3 finalize returns on both PEs; F2 F4 returns after ft_abort | 20 | 20 | 90 | **holds** | 0.84-1.00 |  |  |
