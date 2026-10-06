# Recount with the 20 re-run F4 trials (GP, GG)

Data: `results/20261006_f4rerun/{gp,gg}` for GP/GG F4; everything else from `results/20261006_campaign`. Script: `rerun.py` (reuses `recount.py` parsers). Rule: PREDICTIONS.md Method, including 'no trial shows an outcome outside the predicted class'.

## 1. Did the kill land during traffic?

| trial | r0 okit | r1 okit (of 400) | r1 DONE | r0 'peer gone at it' | kill (ms after r0 start) | first r0 error |
|---|--:|--:|---|--:|--:|---|
| gp_F4_timeout_t1 | 164 | 164 | False | 164 | 2787.5 | WARN status=10 vendor err 136 |
| gp_F4_timeout_t2 | 165 | 164 | False | 165 | 2779.9 | WARN status=10 vendor err 136 |
| gp_F4_timeout_t3 | 166 | 166 | False | 166 | 2795.4 | WARN status=10 vendor err 136 |
| gp_F4_timeout_t4 | 166 | 166 | False | 166 | 2786.8 | WARN status=10 vendor err 136 |
| gp_F4_timeout_t5 | 167 | 167 | False | 167 | 2795.8 | WARN status=10 vendor err 136 |
| gp_F4_timeout_t6 | 165 | 165 | False | 165 | 2797.9 | WARN status=10 vendor err 136 |
| gp_F4_timeout_t7 | 164 | 163 | False | 164 | 2793.6 | WARN status=10 vendor err 136 |
| gp_F4_timeout_t8 | 163 | 163 | False | 163 | 2792.3 | WARN status=10 vendor err 136 |
| gp_F4_timeout_t9 | 164 | 164 | False | 164 | 2773.3 | WARN status=10 vendor err 136 |
| gp_F4_timeout_t10 | 162 | 162 | False | 162 | 2782.9 | WARN status=10 vendor err 136 |
| gg_F4_blocking_t1 | 164 | 164 | False | 164 | 2793.4 | GIN Error detected |
| gg_F4_blocking_t2 | 167 | 167 | False | 167 | 2785.9 | GIN Error detected |
| gg_F4_blocking_t3 | 166 | 166 | False | 166 | 2798.1 | GIN Error detected |
| gg_F4_blocking_t4 | 167 | 167 | False | 167 | 2805.0 | GIN Error detected |
| gg_F4_blocking_t5 | 167 | 167 | False | 167 | 2783.0 | GIN Error detected |
| gg_F4_blocking_t6 | 164 | 164 | False | 164 | 2796.4 | GIN Error detected |
| gg_F4_blocking_t7 | 168 | 168 | False | 168 | 2800.3 | GIN Error detected |
| gg_F4_blocking_t8 | 165 | 165 | False | 165 | 2802.8 | GIN Error detected |
| gg_F4_blocking_t9 | 166 | 166 | False | 166 | 2792.5 | GIN Error detected |
| gg_F4_blocking_t10 | 166 | 165 | False | 166 | 2786.7 | GIN Error detected |

## 2. Cells (GP/GG F4 = re-run trials)

| cell | sub-cell | n | hits | misses | verdict |
|---|---|--:|--:|---|---|
| EV3c | F1 | 10 | 10 | - | HOLDS |
| EV3c | F3 | 10 | 10 | - | HOLDS |
| EV3c | F4 | 10 | 10 | - | HOLDS |
| **EV3c** | | | | | **HOLDS** |
| EV4 | GG | 40 | 40 | - | HOLDS |
| EV4 | GQ | 25 | 25 | - | HOLDS |
| EV4 | NC | 10 | 10 | - | HOLDS |
| EV4 | NG | 10 | 10 | - | HOLDS |
| EV4 | NX | 10 | 10 | - | HOLDS |
| EV4 | ND | 60 | 60 | - | HOLDS |
| EV4 | NF | 25 | 25 | - | HOLDS |
| **EV4** | | | | | **HOLDS** |
| EV5a | GG F0 | 5 | 5 | - | HOLDS |
| EV5a | GG F1 | 5 | 5 | - | HOLDS |
| EV5a | GG F2 | 10 | 10 | - | HOLDS |
| EV5a | GG F3 | 10 | 10 | - | HOLDS |
| EV5a | GG F4 | 10 | 10 | - | HOLDS |
| EV5a | GQ F0 | 5 | 5 | - | HOLDS |
| EV5a | GQ F1 | 5 | 5 | - | HOLDS |
| EV5a | GQ F2 | 5 | 5 | - | HOLDS |
| EV5a | GQ F3 | 5 | 5 | - | HOLDS |
| EV5a | GQ F4 | 5 | 5 | - | HOLDS |
| EV5a | NF F0 | 5 | 5 | - | HOLDS |
| EV5a | NF F1 | 5 | 5 | - | HOLDS |
| EV5a | NF F2 | 5 | 5 | - | HOLDS |
| EV5a | NF F3 | 5 | 5 | - | HOLDS |
| EV5a | NF F4 | 5 | 5 | - | HOLDS |
| EV5a | ND F1 | 20 | 20 | - | HOLDS |
| EV5a | ND F2 | 20 | 20 | - | HOLDS |
| EV5a | ND F3 | 20 | 20 | - | HOLDS |
| **EV5a** | | | | | **HOLDS** |
| EV5c | CPU F3 | 10 | 10 | - | HOLDS |
| EV5c | CPU F4 | 10 | 10 | - | HOLDS |
| EV5c | GP F3 | 10 | 10 | - | HOLDS |
| EV5c | GP F4 | 10 | 0 | gp_F4_timeout_t1, gp_F4_timeout_t2, gp_F4_timeout_t3, gp_F4_timeout_t4, gp_F4_timeout_t5, gp_F4_timeout_t6, gp_F4_timeout_t7, gp_F4_timeout_t8, gp_F4_timeout_t9, gp_F4_timeout_t10 | FAILS |
| **EV5c** | | | | | **FAILS** |
| D1 | F2 | 10 | 10 | - | HOLDS |
| D1 | F3 | 10 | 10 | - | HOLDS |
| D1 | F4 | 10 | 0 | gg_F4_blocking_t1, gg_F4_blocking_t2, gg_F4_blocking_t3, gg_F4_blocking_t4, gg_F4_blocking_t5, gg_F4_blocking_t6, gg_F4_blocking_t7, gg_F4_blocking_t8, gg_F4_blocking_t9, gg_F4_blocking_t10 | FAILS |
| **D1** | | | | | **FAILS** |
| D2 | F4 | 10 | 0 | gg_F4_blocking_t1, gg_F4_blocking_t2, gg_F4_blocking_t3, gg_F4_blocking_t4, gg_F4_blocking_t5, gg_F4_blocking_t6, gg_F4_blocking_t7, gg_F4_blocking_t8, gg_F4_blocking_t9, gg_F4_blocking_t10 | FAILS |
| **D2** | | | | | **FAILS** |

## 3. What the F4 trials showed (EV5c, D1, D2)

| trial | rain d(local_ack_timeout_err) | rain d(req_cqe_error) | rain d(req_remote_access_errors) | drain rc / ms / outcome | r0 init_outcome | GIN Error surface ms | D1 L3 / L4 |
|---|--:|--:|--:|---|---|--:|---|
| gp_F4_timeout_t1 | 0 | 1 | 1 | 8/4693.9/error | error | - | - |
| gp_F4_timeout_t2 | 0 | 1 | 1 | 8/4711.6/error | error | - | - |
| gp_F4_timeout_t3 | 0 | 1 | 1 | 8/4723.2/error | error | - | - |
| gp_F4_timeout_t4 | 0 | 1 | 1 | 8/4710.9/error | error | - | - |
| gp_F4_timeout_t5 | 0 | 1 | 1 | 8/4744.3/error | error | - | - |
| gp_F4_timeout_t6 | 0 | 1 | 1 | 8/4757.3/error | error | - | - |
| gp_F4_timeout_t7 | 0 | 1 | 1 | 8/4731.3/error | error | - | - |
| gp_F4_timeout_t8 | 0 | 1 | 1 | 8/4738.6/error | error | - | - |
| gp_F4_timeout_t9 | 0 | 1 | 1 | 8/4748.9/error | error | - | - |
| gp_F4_timeout_t10 | 0 | 1 | 1 | 8/4736.4/error | error | - | - |
| gg_F4_blocking_t1 | 0 | 0 | 0 | 8/4755.8/timeout | timeout | 8079.9 | False / True |
| gg_F4_blocking_t2 | 0 | 0 | 0 | 8/4769.9/timeout | timeout | 8044.6 | False / True |
| gg_F4_blocking_t3 | 0 | 0 | 0 | 8/4743.2/timeout | timeout | 8054.7 | False / True |
| gg_F4_blocking_t4 | 0 | 0 | 0 | 8/4733.2/timeout | timeout | 8044.2 | False / True |
| gg_F4_blocking_t5 | 0 | 0 | 0 | 8/4762.9/timeout | timeout | 8048.5 | False / True |
| gg_F4_blocking_t6 | 0 | 0 | 0 | 8/4767.1/timeout | timeout | 8058.3 | False / True |
| gg_F4_blocking_t7 | 0 | 0 | 0 | 8/4783.9/timeout | timeout | 8030.3 | False / True |
| gg_F4_blocking_t8 | 0 | 0 | 0 | 8/4792.0/timeout | timeout | 8067.1 | False / True |
| gg_F4_blocking_t9 | 0 | 0 | 0 | 8/4785.0/timeout | timeout | 8053.6 | False / True |
| gg_F4_blocking_t10 | 0 | 0 | 0 | 8/4779.8/timeout | timeout | 8051.6 | False / True |

## 4. Notes

- Kill landed during traffic in 20/20: rank 1 never printed `DONE` (killed at 162-168 of 400 iterations, r1 rc 255); rank 0 lost the peer at the next barrier and then drained puts to the dead QP.
- GP F4 rank 0 WARN: `Got completion ... status=10 opcode=4 len=8 vendor err 136 (IPut)` (REM_ACCESS 0x88), i.e. the F2 class, not RETRY_EXC; hence local_ack_timeout_err +0 (EV5c needs >= +6).
- GG F4: drain_device_rc=8 is ncclTimeout (nccl.h of the gin build: `ncclTimeout = 8`). The drain put uses the bounded flush (gin_fault.cu: putKernel(..., /*useTimeout=*/1, ...)); in blocking mode the per-iteration TCP barrier sees the death first, so no blocking flush ran on a post-kill op (r0 okit = r1 okit in 9/10; t10 r0 counted one more iteration than r1, but whether that op failed cannot be determined).
- D1 F4 L4 holds 10/10 (GIN Error detected 8.03-8.08 s after the kill, at the ~10.8 s tick); L3 fails (r0 init_outcome=timeout, not a silent success); L2 not observable with the stock driver.

