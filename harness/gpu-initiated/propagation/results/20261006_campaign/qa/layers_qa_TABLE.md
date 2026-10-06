# Layer partitions, independent recount (2026-10-06)

Source: raw files under `results/20261006_campaign/` (GP and GG F4 from `results/20261006_f4rerun/`, DEVIATIONS item 10). Script `layers_qa.py`; per-trial labels `trials.csv` (440 rows = 325 trials as initiator rows, the 5 net T0s rows counted twice, and 110 GIN target rows; the 5 net T0s trials are the F0 control of both net variants). A fault label is the label of >=90% of its trials. Counts are over F0-F4 only; ND has no F0. "-" = no file records this layer.

## Number of classes per layer (F0-F4)

| variant | side | L0 | L1root | L1read | L2 | L3 | L4async | L4log | L5 |
|---|---|---|---|---|---|---|---|---|---|
| CPU | init | 4 | 4 | 4 | 5 | - | 1 | - | 1 |
| GP | init | 5 | 4 | 4 | 4 | 2 | 2 | 4 | 1 |
| GP | target | 1 | 1 | 1 | 1 | 2 | 1 | 2 | 1 |
| GG | init | 2 | - | - | - | 2 | 2 | 2 | 1 |
| GG | target | 1 | - | - | - | 2 | 1 | 1 | 2 |
| GQ | init | 2 | 4 | 2 | 4 | 2 | 2 | 4 | 1 |
| GQ | target | 1 | 1 | 1 | 1 | 2 | 1 | 1 | 2 |
| NC | init | 2 | - | - | - | 2 | - | 1 | 2 |
| NG | init | 2 | - | - | - | 1 | - | 1 | 2 |
| NX | init | 2 | - | - | - | 1 | - | 1 | 2 |
| ND-GPU | init | 2 | 3 | 3 | 1 | - | - | 1 | 1 |
| ND-CPU | init | 2 | 1 | 1 | 1 | - | - | 1 | 1 |
| NF | init | 2 | 4 | 4 | 4 | 4 | - | 5 | 1 |
| NET-stock | init | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 |
| NET-S2 | init | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 |

## Partitions (F0-F4) and modal labels

### CPU init

| layer | partition | labels (k/n) |
|---|---|---|
| L0 | F0 | F1 | F2 | F3,F4 | F0: +0 (5/5) // F1: req_cqe_error+req_cqe_flush_error (10/10) // F2: req_cqe_error+req_remote_access_errors (10/10) // F3: local_ack_timeout_err+req_cqe_error+roce_adp_retrans+roce_slow_restart_cnps+rp_cnp_handled (10/10) // F4: local_ack_timeout_err+req_cqe_error+roce_adp_retrans+roce_slow_restart_cnps+rp_cnp_handled (10/10) // X_rem_inv_req: req_cqe_error+req_remote_invalid_request (10/10) // X_rnr: req_cqe_error+rnr_nak_retry_err (10/10) // X_partial_write: req_cqe_error (10/10) |
| L1root | F0 | F1 | F2 | F3,F4 | F0: success (5/5) // F1: 5/0xf5 (10/10) // F2: 10/0x88 (10/10) // F3: 12/0x81 (10/10) // F4: 12/0x81 (10/10) // X_rem_inv_req: 9/0x8a (10/10) // X_rnr: 13/0x87 (10/10) // X_partial_write: 5/0xf5 (10/10) |
| L1read | F0 | F1 | F2 | F3,F4 | F0: success (5/5) // F1: 5/0xf5 (10/10) // F2: 10/0x88 (10/10) // F3: 12/0x81 (10/10) // F4: 12/0x81 (10/10) // X_rem_inv_req: 9/0x8a (10/10) // X_rnr: 13/0x87 (10/10) // X_partial_write: 5/0xf5 (10/10) |
| L2 | F0 | F1 | F2 | F3 | F4 | F0: success (5/5) // F1: 5/0xf5 (10/10) // F2: 10/0x88 (10/10) // F3: 12/0x81 server_qp_err (10/10) // F4: 12/0x81 proc_kill (10/10) // X_rem_inv_req: 9/0x8a (10/10) // X_rnr: 13/0x87 (10/10) // X_partial_write: 5/0xf5 (10/10) |
| L3 | not observed | F0: n/a (harness is the app) (5/5) // F1: n/a (harness is the app) (10/10) // F2: n/a (harness is the app) (10/10) // F3: n/a (harness is the app) (10/10) // F4: n/a (harness is the app) (10/10) // X_rem_inv_req: n/a (harness is the app) (10/10) // X_rnr: n/a (harness is the app) (10/10) // X_partial_write: n/a (harness is the app) (10/10) |
| L4async | F0,F1,F2,F3,F4 | F0: none (5/5) // F1: none (10/10) // F2: none (10/10) // F3: none (10/10) // F4: none (10/10) // X_rem_inv_req: none (10/10) // X_rnr: none (10/10) // X_partial_write: none (10/10) |
| L4log | not observed | F0: n/a (no library) (5/5) // F1: n/a (no library) (10/10) // F2: n/a (no library) (10/10) // F3: n/a (no library) (10/10) // F4: n/a (no library) (10/10) // X_rem_inv_req: n/a (no library) (10/10) // X_rnr: n/a (no library) (10/10) // X_partial_write: n/a (no library) (10/10) |
| L5 | F0,F1,F2,F3,F4 | F0: returned (5/5) // F1: returned (10/10) // F2: returned (10/10) // F3: returned (10/10) // F4: returned (10/10) // X_rem_inv_req: returned (10/10) // X_rnr: returned (10/10) // X_partial_write: returned (10/10) |

### GP init

| layer | partition | labels (k/n) |
|---|---|---|
| L0 | F0 | F1 | F2 | F3 | F4 | F0: +0 (5/5) // F1: req_cqe_error+req_cqe_flush_error (10/10) // F2: req_cqe_error+req_cqe_flush_error+req_remote_access_errors (10/10) // F3: local_ack_timeout_err+req_cqe_error+req_cqe_flush_error+roce_adp_retrans+roce_slow_restart_cnps+rp_cnp_handled (10/10) // F4: req_cqe_error+req_remote_access_errors (10/10) |
| L1root | F0 | F1 | F2,F4 | F3 | F0: no error CQE logged (5/5) // F1: 5/0xf5 (10/10) // F2: 10/0x88 (10/10) // F3: 12/0x81 (10/10) // F4: 10/0x88 (10/10) |
| L1read | F0 | F1 | F2,F4 | F3 | F0: no error CQE logged (5/5) // F1: 5/0xf5 (10/10) // F2: 10/0x88 (10/10) // F3: 12/0x81 (10/10) // F4: 10/0x88 (10/10) |
| L2 | F0 | F1 | F2,F4 | F3 | F0: no error (5/5) // F1: WARN 5/0xf5 + GFD error (10/10) // F2: WARN 10/0x88 + GFD error (10/10) // F3: WARN 12/0x81 + GFD error (10/10) // F4: WARN 10/0x88 + GFD error (10/10) |
| L3 | F0 | F1,F2,F3,F4 | F0: ok (5/5) // F1: ncclTimeout (10/10) // F2: ncclTimeout (10/10) // F3: ncclTimeout (10/10) // F4: ncclTimeout (10/10) |
| L4async | F0 | F1,F2,F3,F4 | F0: none (5/5) // F1: ncclRemoteError (10/10) // F2: ncclRemoteError (10/10) // F3: ncclRemoteError (10/10) // F4: ncclRemoteError (10/10) |
| L4log | F0 | F1 | F2,F4 | F3 | F0: no WARN (5/5) // F1: GFD error / completion 5/0xf5 (10/10) // F2: GFD error / completion 10/0x88 (10/10) // F3: GFD error / completion 12/0x81 (10/10) // F4: GFD error / completion 10/0x88 (10/10) |
| L5 | F0,F1,F2,F3,F4 | F0: abort returned (5/5) // F1: abort returned (10/10) // F2: abort returned (10/10) // F3: abort returned (10/10) // F4: abort returned (10/10) |

### GP target

| layer | partition | labels (k/n) |
|---|---|---|
| L0 | F0,F1,F2,F3,F4 | F0: +0 (5/5) // F1: +0 (10/10) // F2: +0 (10/10) // F3: +0 (10/10) // F4: +0 (10/10) |
| L1root | F0,F1,F2,F3 | F0: no error CQE logged (5/5) // F1: no error CQE logged (10/10) // F2: no error CQE logged (10/10) // F3: no error CQE logged (10/10) // F4: n/a (killed) (10/10) |
| L1read | F0,F1,F2,F3 | F0: no error CQE logged (5/5) // F1: no error CQE logged (10/10) // F2: no error CQE logged (10/10) // F3: no error CQE logged (10/10) // F4: n/a (killed) (10/10) |
| L2 | F0,F1,F2,F3 | F0: no error logged (5/5) // F1: no error logged (10/10) // F2: no error logged (10/10) // F3: no error logged (10/10) // F4: n/a (killed) (10/10) |
| L3 | F0 | F1,F2,F3 | F0: ok (5/5) // F1: ncclTimeout (10/10) // F2: ncclTimeout (10/10) // F3: ncclTimeout (10/10) // F4: n/a (killed) (10/10) |
| L4async | F0,F1,F2,F3 | F0: none (5/5) // F1: none (10/10) // F2: none (10/10) // F3: none (10/10) // F4: n/a (killed) (10/10) |
| L4log | F0,F1,F3 | F2 | F0: no WARN (5/5) // F1: no WARN (10/10) // F2: async fatal event: local access violation work queue error (10/10) // F3: no WARN (10/10) // F4: n/a (killed) (10/10) |
| L5 | F0,F1,F2,F3 | F0: abort returned (5/5) // F1: abort returned (10/10) // F2: abort returned (10/10) // F3: abort returned (10/10) // F4: n/a (killed) (10/10) |

### GG init

| layer | partition | labels (k/n) |
|---|---|---|
| L0 | F0,F1,F2 | F3,F4 | F0: +0 (5/5) // F1: +0 (5/5) // F2: +0 (10/10) // F3: rp_cnp_handled (10/10) // F4: rp_cnp_handled (10/10) |
| L1root | not observed | F0: not observed (5/5) // F1: not observed (5/5) // F2: not observed (10/10) // F3: not observed (10/10) // F4: not observed (10/10) |
| L1read | not observed | F0: not observed (5/5) // F1: not observed (5/5) // F2: not observed (10/10) // F3: not observed (10/10) // F4: not observed (10/10) |
| L2 | not observed | F0: not observed (5/5) // F1: not observed (5/5) // F2: not observed (10/10) // F3: not observed (10/10) // F4: not observed (10/10) |
| L3 | F0,F1,F2,F3 | F4 | F0: ok (5/5) // F1: ok (5/5) // F2: ok (10/10) // F3: ok (10/10) // F4: ncclTimeout (10/10) |
| L4async | F0 | F1,F2,F3,F4 | F0: none (5/5) // F1: ncclRemoteError (5/5) // F2: ncclRemoteError (10/10) // F3: ncclRemoteError (10/10) // F4: ncclRemoteError (10/10) |
| L4log | F0 | F1,F2,F3,F4 | F0: no WARN (5/5) // F1: GIN Error detected (5/5) // F2: GIN Error detected (10/10) // F3: GIN Error detected (10/10) // F4: GIN Error detected (10/10) |
| L5 | F0,F1,F2,F3,F4 | F0: abort returned (5/5) // F1: abort returned (5/5) // F2: abort returned (10/10) // F3: abort returned (10/10) // F4: abort returned (10/10) |

### GG target

| layer | partition | labels (k/n) |
|---|---|---|
| L0 | F0,F1,F2,F3,F4 | F0: +0 (5/5) // F1: +0 (5/5) // F2: +0 (10/10) // F3: +0 (10/10) // F4: +0 (10/10) |
| L1root | not observed | F0: not observed (5/5) // F1: not observed (5/5) // F2: not observed (10/10) // F3: not observed (10/10) // F4: n/a (killed) (10/10) |
| L1read | not observed | F0: not observed (5/5) // F1: not observed (5/5) // F2: not observed (10/10) // F3: not observed (10/10) // F4: n/a (killed) (10/10) |
| L2 | not observed | F0: not observed (5/5) // F1: not observed (5/5) // F2: not observed (10/10) // F3: not observed (10/10) // F4: n/a (killed) (10/10) |
| L3 | F0 | F1,F2,F3 | F0: ok (5/5) // F1: hang (device wait never returned) (5/5) // F2: hang (device wait never returned) (10/10) // F3: hang (device wait never returned) (10/10) // F4: n/a (killed) (10/10) |
| L4async | F0,F1,F2,F3 | F0: none (5/5) // F1: none (5/5) // F2: none (10/10) // F3: none (10/10) // F4: n/a (killed) (10/10) |
| L4log | F0,F1,F2,F3 | F0: no WARN (5/5) // F1: no WARN (5/5) // F2: no WARN (10/10) // F3: no WARN (10/10) // F4: n/a (killed) (10/10) |
| L5 | F0 | F1,F2,F3 | F0: abort returned (5/5) // F1: abort hang (30 s) (5/5) // F2: abort hang (30 s) (10/10) // F3: abort hang (30 s) (10/10) // F4: n/a (killed) (10/10) |

### GQ init

| layer | partition | labels (k/n) |
|---|---|---|
| L0 | F0,F1,F2 | F3,F4 | F0: +0 (5/5) // F1: +0 (5/5) // F2: +0 (5/5) // F3: rp_cnp_handled (5/5) // F4: rp_cnp_handled (5/5) |
| L1root | F0 | F1 | F2 | F3,F4 | F0: no error CQE logged (5/5) // F1: 5/0xf5 (5/5) // F2: 10/0x88 (5/5) // F3: 12/0x81 (5/5) // F4: 12/0x81 (5/5) |
| L1read | F0 | F1,F2,F3,F4 | F0: no error CQE logged (5/5) // F1: 5/0xf9 (5/5) // F2: 5/0xf9 (5/5) // F3: 5/0xf9 (5/5) // F4: 5/0xf9 (5/5) |
| L2 | F0 | F1 | F2 | F3,F4 | F0: no error (5/5) // F1: LOCAL_QP_ERR (5/5) // F2: REM_ACCESS (5/5) // F3: RETRY_EXC (5/5) // F4: RETRY_EXC (5/5) |
| L3 | F0 | F1,F2,F3,F4 | F0: ok (5/5) // F1: ncclRemoteError (5/5) // F2: ncclRemoteError (5/5) // F3: ncclRemoteError (5/5) // F4: ncclRemoteError (5/5) |
| L4async | F0 | F1,F2,F3,F4 | F0: none (5/5) // F1: ncclRemoteError (5/5) // F2: ncclRemoteError (5/5) // F3: ncclRemoteError (5/5) // F4: ncclRemoteError (5/5) |
| L4log | F0 | F1 | F2 | F3,F4 | F0: no WARN (5/5) // F1: GIN Error detected / Q4 class=LOCAL_QP_ERR / QUERY_QP ERR (5/5) // F2: GIN Error detected / Q4 class=REM_ACCESS / QUERY_QP ERR (5/5) // F3: GIN Error detected / Q4 class=RETRY_EXC / QUERY_QP ERR (5/5) // F4: GIN Error detected / Q4 class=RETRY_EXC / QUERY_QP ERR (5/5) |
| L5 | F0,F1,F2,F3,F4 | F0: abort returned (5/5) // F1: abort returned (5/5) // F2: abort returned (5/5) // F3: abort returned (5/5) // F4: abort returned (5/5) |

### GQ target

| layer | partition | labels (k/n) |
|---|---|---|
| L0 | F0,F1,F2,F3,F4 | F0: +0 (5/5) // F1: +0 (5/5) // F2: +0 (5/5) // F3: +0 (5/5) // F4: +0 (5/5) |
| L1root | F0,F1,F2,F3 | F0: no error CQE logged (5/5) // F1: no error CQE logged (5/5) // F2: no error CQE logged (5/5) // F3: no error CQE logged (5/5) // F4: n/a (killed) (5/5) |
| L1read | F0,F1,F2,F3 | F0: no error CQE logged (5/5) // F1: no error CQE logged (5/5) // F2: no error CQE logged (5/5) // F3: no error CQE logged (5/5) // F4: n/a (killed) (5/5) |
| L2 | F0,F1,F2,F3 | F0: no error (5/5) // F1: no error (5/5) // F2: no error (5/5) // F3: no error (5/5) // F4: n/a (killed) (5/5) |
| L3 | F0 | F1,F2,F3 | F0: ok (5/5) // F1: hang (device wait never returned) (5/5) // F2: hang (device wait never returned) (5/5) // F3: hang (device wait never returned) (5/5) // F4: n/a (killed) (5/5) |
| L4async | F0,F1,F2,F3 | F0: none (5/5) // F1: none (5/5) // F2: none (5/5) // F3: none (5/5) // F4: n/a (killed) (5/5) |
| L4log | F0,F1,F2,F3 | F0: no WARN (5/5) // F1: no WARN (5/5) // F2: no WARN (5/5) // F3: no WARN (5/5) // F4: n/a (killed) (5/5) |
| L5 | F0 | F1,F2,F3 | F0: abort returned (5/5) // F1: abort hang (30 s) (5/5) // F2: abort hang (30 s) (5/5) // F3: abort hang (30 s) (5/5) // F4: n/a (killed) (5/5) |

### NC init

| layer | partition | labels (k/n) |
|---|---|---|
| L0 | F0 | F4 | F0: +0 (5/5) // F4: rp_cnp_handled (5/5) |
| L1root | not observed | F0: not observed (5/5) // F4: not observed (5/5) |
| L1read | not observed | F0: not observed (5/5) // F4: not observed (5/5) |
| L2 | not observed | F0: not observed (5/5) // F4: not observed (5/5) |
| L3 | F0 | F4 | F0: returned (5/5) // F4: hang (quiet > 30 s) (5/5) |
| L4async | not observed | F0: n/a (no async-error API) (5/5) // F4: n/a (no async-error API) (5/5) |
| L4log | F0,F4 | F0: no WARN (5/5) // F4: no WARN (5/5) |
| L5 | F0 | F4 | F0: finalize returned (5/5) // F4: finalize hang (30 s) (5/5) |

### NG init

| layer | partition | labels (k/n) |
|---|---|---|
| L0 | F0 | F4 | F0: +0 (5/5) // F4: rp_cnp_handled (5/5) |
| L1root | not observed | F0: not observed (5/5) // F4: not observed (5/5) |
| L1read | not observed | F0: not observed (5/5) // F4: not observed (5/5) |
| L2 | not observed | F0: not observed (5/5) // F4: not observed (5/5) |
| L3 | F0,F4 | F0: returned (5/5) // F4: returned (5/5) |
| L4async | not observed | F0: n/a (no async-error API) (5/5) // F4: n/a (no async-error API) (5/5) |
| L4log | F0,F4 | F0: no WARN (5/5) // F4: no WARN (5/5) |
| L5 | F0 | F4 | F0: finalize returned (5/5) // F4: finalize hang (30 s) (5/5) |

### NX init

| layer | partition | labels (k/n) |
|---|---|---|
| L0 | F0 | F4 | F0: +0 (5/5) // F4: rp_cnp_handled (5/5) |
| L1root | not observed | F0: not observed (5/5) // F4: not observed (5/5) |
| L1read | not observed | F0: not observed (5/5) // F4: not observed (5/5) |
| L2 | not observed | F0: not observed (5/5) // F4: not observed (5/5) |
| L3 | F0,F4 | F0: returned (5/5) // F4: returned (5/5) |
| L4async | not observed | F0: n/a (no async-error API) (5/5) // F4: n/a (no async-error API) (5/5) |
| L4log | F0,F4 | F0: no WARN (5/5) // F4: no WARN (5/5) |
| L5 | F0 | F4 | F0: finalize returned (5/5) // F4: finalize hang (30 s) (5/5) |

### ND-GPU init

| layer | partition | labels (k/n) |
|---|---|---|
| L0 | F1,F2 | F3 | F1: +0 (10/10) // F2: +0 (10/10) // F3: rp_cnp_handled (10/10) |
| L1root | F1 | F2 | F3 | F1: 5/0xf5 (10/10) // F2: 10/0x88 (10/10) // F3: 12/0x81 (10/10) |
| L1read | F1 | F2 | F3 | F1: 5/0xf5 (10/10) // F2: 10/0x88 (10/10) // F3: 12/0x81 (10/10) |
| L2 | F1,F2,F3 | F1: REQ_ERR seen (driver poll) (10/10) // F2: REQ_ERR seen (driver poll) (10/10) // F3: REQ_ERR seen (driver poll) (10/10) |
| L3 | not observed | F1: not observed (timeout mode bypasses the library API) (10/10) // F2: not observed (timeout mode bypasses the library API) (10/10) // F3: not observed (timeout mode bypasses the library API) (10/10) |
| L4async | not observed | F1: n/a (no async-error API) (10/10) // F2: n/a (no async-error API) (10/10) // F3: n/a (no async-error API) (10/10) |
| L4log | F1,F2,F3 | F1: no WARN (10/10) // F2: no WARN (10/10) // F3: no WARN (10/10) |
| L5 | F1,F2,F3 | F1: finalize hang (15 s watchdog) (10/10) // F2: finalize hang (15 s watchdog) (10/10) // F3: finalize hang (15 s watchdog) (10/10) |

### ND-CPU init

| layer | partition | labels (k/n) |
|---|---|---|
| L0 | F1,F2 | F3 | F1: +0 (10/10) // F2: +0 (10/10) // F3: rp_cnp_handled (10/10) |
| L1root | F1,F2,F3 | F1: no error CQE in CQ scan (10/10) // F2: no error CQE in CQ scan (10/10) // F3: no error CQE in CQ scan (10/10) |
| L1read | F1,F2,F3 | F1: no new CQE (slot unchanged) (10/10) // F2: no new CQE (slot unchanged) (10/10) // F3: no new CQE (slot unchanged) (10/10) |
| L2 | F1,F2,F3 | F1: timeout (driver poll) (10/10) // F2: timeout (driver poll) (10/10) // F3: timeout (driver poll) (10/10) |
| L3 | not observed | F1: not observed (timeout mode bypasses the library API) (10/10) // F2: not observed (timeout mode bypasses the library API) (10/10) // F3: not observed (timeout mode bypasses the library API) (10/10) |
| L4async | not observed | F1: n/a (no async-error API) (10/10) // F2: n/a (no async-error API) (10/10) // F3: n/a (no async-error API) (10/10) |
| L4log | F1,F2,F3 | F1: no WARN (10/10) // F2: no WARN (10/10) // F3: no WARN (10/10) |
| L5 | F1,F2,F3 | F1: finalize hang (15 s watchdog) (10/10) // F2: finalize hang (15 s watchdog) (10/10) // F3: finalize hang (15 s watchdog) (10/10) |

### NF init

| layer | partition | labels (k/n) |
|---|---|---|
| L0 | F0,F1,F2 | F3,F4 | F0: +0 (5/5) // F1: +0 (5/5) // F2: +0 (5/5) // F3: rp_cnp_handled (5/5) // F4: rp_cnp_handled (5/5) |
| L1root | F0 | F1 | F2 | F3,F4 | F0: no error CQE (5/5) // F1: 5/0xf5 (5/5) // F2: 10/0x88 (5/5) // F3: 12/0x81 (5/5) // F4: 12/0x81 (5/5) |
| L1read | F0 | F1 | F2 | F3,F4 | F0: no error CQE (5/5) // F1: 5/0xf5 (5/5) // F2: 10/0x88 (5/5) // F3: 12/0x81 (5/5) // F4: 12/0x81 (5/5) |
| L2 | F0 | F1 | F2 | F3,F4 | F0: no error (5/5) // F1: LOCAL_QP_ERR (5/5) // F2: REM_ACCESS (5/5) // F3: RETRY_EXC (5/5) // F4: RETRY_EXC (5/5) |
| L3 | F0 | F1 | F2 | F3,F4 | F0: rc=0 (5/5) // F1: rc=-1 FT.query class=LOCAL_QP_ERR (5/5) // F2: rc=-1 FT.query class=REM_ACCESS (5/5) // F3: rc=-1 FT.query class=RETRY_EXC (5/5) // F4: rc=-1 FT.query class=RETRY_EXC (5/5) |
| L4async | not observed | F0: n/a (no async-error API) (5/5) // F1: n/a (no async-error API) (5/5) // F2: n/a (no async-error API) (5/5) // F3: n/a (no async-error API) (5/5) // F4: n/a (no async-error API) (5/5) |
| L4log | F0 | F1 | F2 | F3 | F4 | F0: no ft line (5/5) // F1: ft class=LOCAL_QP_ERR / QUERY_QP ERR (5/5) // F2: ft class=REM_ACCESS / QUERY_QP ERR / marked failed (5/5) // F3: ft class=RETRY_EXC / QUERY_QP ERR (5/5) // F4: ft class=RETRY_EXC / QUERY_QP ERR / marked failed (5/5) |
| L5 | F0,F1,F2,F3,F4 | F0: finalize returned (5/5) // F1: finalize returned (5/5) // F2: finalize returned (5/5) // F3: finalize returned (5/5) // F4: finalize returned (5/5) |

### NET-stock init

| layer | partition | labels (k/n) |
|---|---|---|
| L0 | F0 | F2 | F0: +0 (5/5) // F2: req_cqe_error+req_cqe_flush_error+req_remote_access_errors (10/10) |
| L1root | F0 | F2 | F0: no CQE logged (5/5) // F2: 10/0x88 (10/10) |
| L1read | F0 | F2 | F0: no CQE logged (5/5) // F2: 10/0x88 (10/10) |
| L2 | F0 | F2 | F0: no error (5/5) // F2: stock: WARN completion error (10/10) |
| L3 | F0 | F2 | F0: ok (5/5) // F2: ncclRemoteError (10/10) |
| L4async | F0 | F2 | F0: none (5/5) // F2: ncclRemoteError (10/10) |
| L4log | F0 | F2 | F0: no WARN (5/5) // F2: completion 10/0x88 / completion 5/0xf9 (10/10) |
| L5 | F0 | F2 | F0: no abort (destroy, not timed); rc=0 (5/5) // F2: abort hang (20 s watchdog) (10/10) |

### NET-S2 init

| layer | partition | labels (k/n) |
|---|---|---|
| L0 | F0 | F2 | F0: +0 (5/5) // F2: req_cqe_error+req_cqe_flush_error+req_remote_access_errors (10/10) |
| L1root | F0 | F2 | F0: no CQE logged (5/5) // F2: 10/0x88 (9/10) |
| L1read | F0 | F2 | F0: no CQE logged (5/5) // F2: 10/0x88 (9/10) |
| L2 | F0 | F2 | F0: no error (5/5) // F2: Stage2: declined by class (9/10) |
| L3 | F0 | F2 | F0: ok (5/5) // F2: ncclRemoteError (10/10) |
| L4async | F0 | F2 | F0: none (5/5) // F2: ncclRemoteError (10/10) |
| L4log | F0 | F2 | F0: no WARN (5/5) // F2: FR2 FAILED / FR2 incident 10/0x88 (9/10) |
| L5 | F0 | F2 | F0: no abort (destroy, not timed); rc=0 (5/5) // F2: abort hang (20 s watchdog) (10/10) |

## Arrival: trials whose label differs from the F0 control (ND: from "no error")

| variant | side | fault | L0 | L1root | L1read | L2 | L3 | L4async | L4log | L5 |
|---|---|---|---|---|---|---|---|---|---|---|
| CPU | init | F1 | 10/10 | 10/10 | 10/10 | 10/10 | - | 0/10 | - | 0/10 |
| CPU | init | F2 | 10/10 | 10/10 | 10/10 | 10/10 | - | 0/10 | - | 0/10 |
| CPU | init | F3 | 10/10 | 10/10 | 10/10 | 10/10 | - | 0/10 | - | 0/10 |
| CPU | init | F4 | 10/10 | 10/10 | 10/10 | 10/10 | - | 0/10 | - | 0/10 |
| CPU | init | X_rem_inv_req | 10/10 | 10/10 | 10/10 | 10/10 | - | 0/10 | - | 0/10 |
| CPU | init | X_rnr | 10/10 | 10/10 | 10/10 | 10/10 | - | 0/10 | - | 0/10 |
| CPU | init | X_partial_write | 10/10 | 10/10 | 10/10 | 10/10 | - | 0/10 | - | 0/10 |
| GP | init | F1 | 10/10 | 10/10 | 10/10 | 10/10 | 10/10 | 10/10 | 10/10 | 0/10 |
| GP | init | F2 | 10/10 | 10/10 | 10/10 | 10/10 | 10/10 | 10/10 | 10/10 | 0/10 |
| GP | init | F3 | 10/10 | 10/10 | 10/10 | 10/10 | 10/10 | 10/10 | 10/10 | 0/10 |
| GP | init | F4 | 10/10 | 10/10 | 10/10 | 10/10 | 10/10 | 10/10 | 10/10 | 0/10 |
| GP | target | F1 | 0/10 | 0/10 | 0/10 | 0/10 | 10/10 | 0/10 | 0/10 | 0/10 |
| GP | target | F2 | 0/10 | 0/10 | 0/10 | 0/10 | 10/10 | 0/10 | 10/10 | 0/10 |
| GP | target | F3 | 0/10 | 0/10 | 0/10 | 0/10 | 10/10 | 0/10 | 0/10 | 0/10 |
| GP | target | F4 | 0/10 | - | - | - | - | - | - | - |
| GG | init | F1 | 0/5 | - | - | - | 0/5 | 5/5 | 5/5 | 0/5 |
| GG | init | F2 | 0/10 | - | - | - | 0/10 | 10/10 | 10/10 | 0/10 |
| GG | init | F3 | 10/10 | - | - | - | 0/10 | 10/10 | 10/10 | 0/10 |
| GG | init | F4 | 10/10 | - | - | - | 10/10 | 10/10 | 10/10 | 0/10 |
| GG | target | F1 | 0/5 | - | - | - | 5/5 | 0/5 | 0/5 | 5/5 |
| GG | target | F2 | 0/10 | - | - | - | 10/10 | 0/10 | 0/10 | 10/10 |
| GG | target | F3 | 0/10 | - | - | - | 10/10 | 0/10 | 0/10 | 10/10 |
| GG | target | F4 | 0/10 | - | - | - | - | - | - | - |
| GQ | init | F1 | 0/5 | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 | 0/5 |
| GQ | init | F2 | 0/5 | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 | 0/5 |
| GQ | init | F3 | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 | 0/5 |
| GQ | init | F4 | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 | 0/5 |
| GQ | target | F1 | 0/5 | 0/5 | 0/5 | 0/5 | 5/5 | 0/5 | 0/5 | 5/5 |
| GQ | target | F2 | 0/5 | 0/5 | 0/5 | 0/5 | 5/5 | 0/5 | 0/5 | 5/5 |
| GQ | target | F3 | 0/5 | 0/5 | 0/5 | 0/5 | 5/5 | 0/5 | 0/5 | 5/5 |
| GQ | target | F4 | 0/5 | - | - | - | - | - | - | - |
| NC | init | F4 | 5/5 | - | - | - | 5/5 | - | 0/5 | 5/5 |
| NG | init | F4 | 5/5 | - | - | - | 0/5 | - | 0/5 | 5/5 |
| NX | init | F4 | 5/5 | - | - | - | 0/5 | - | 0/5 | 5/5 |
| ND-GPU | init | F1 | 0/10 | 10/10 | 10/10 | 10/10 | - | - | 0/10 | 10/10 |
| ND-GPU | init | F2 | 0/10 | 10/10 | 10/10 | 10/10 | - | - | 0/10 | 10/10 |
| ND-GPU | init | F3 | 10/10 | 10/10 | 10/10 | 10/10 | - | - | 0/10 | 10/10 |
| ND-CPU | init | F1 | 0/10 | 0/10 | 0/10 | 10/10 | - | - | 0/10 | 10/10 |
| ND-CPU | init | F2 | 0/10 | 0/10 | 0/10 | 10/10 | - | - | 0/10 | 10/10 |
| ND-CPU | init | F3 | 10/10 | 0/10 | 0/10 | 10/10 | - | - | 0/10 | 10/10 |
| NF | init | F1 | 0/5 | 5/5 | 5/5 | 5/5 | 5/5 | - | 5/5 | 0/5 |
| NF | init | F2 | 0/5 | 5/5 | 5/5 | 5/5 | 5/5 | - | 5/5 | 0/5 |
| NF | init | F3 | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 | - | 5/5 | 0/5 |
| NF | init | F4 | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 | - | 5/5 | 0/5 |
| NET-stock | init | F2 | 10/10 | 10/10 | 10/10 | 10/10 | 10/10 | 10/10 | 10/10 | 10/10 |
| NET-S2 | init | F2 | 10/10 | 9/10 | 9/10 | 10/10 | 10/10 | 10/10 | 10/10 | 10/10 |

## Higher layer separates a pair that the nearest observed lower layer merges

| variant | side | higher > lower | pairs |
|---|---|---|---|
| CPU | init | L2 > L1read | F3/F4 |
| GP | init | L4 > L3 | F1/F2 F1/F3 F1/F4 F2/F3 F3/F4 |
| GP | init | L4log > L3 | F1/F2 F1/F3 F1/F4 F2/F3 F3/F4 |
| GP | target | L3 > L2 | F0/F1 F0/F2 F0/F3 |
| GP | target | L4 > L3 | F1/F2 F2/F3 |
| GP | target | L4log > L3 | F1/F2 F2/F3 |
| GP | target | L4log > L2 | F0/F2 F1/F2 F2/F3 |
| GG | init | L3 > L0 | F3/F4 |
| GG | init | L4 > L3 | F0/F1 F0/F2 F0/F3 |
| GG | init | L4async > L3 | F0/F1 F0/F2 F0/F3 |
| GG | init | L4log > L3 | F0/F1 F0/F2 F0/F3 |
| GG | init | L4async > L0 | F0/F1 F0/F2 |
| GG | init | L4log > L0 | F0/F1 F0/F2 |
| GG | target | L3 > L0 | F0/F1 F0/F2 F0/F3 |
| GG | target | L5 > L4 | F0/F1 F0/F2 F0/F3 |
| GQ | init | L1root > L0 | F0/F1 F0/F2 F1/F2 |
| GQ | init | L2 > L1read | F1/F2 F1/F3 F1/F4 F2/F3 F2/F4 |
| GQ | init | L4 > L3 | F1/F2 F1/F3 F1/F4 F2/F3 F2/F4 |
| GQ | init | L4log > L3 | F1/F2 F1/F3 F1/F4 F2/F3 F2/F4 |
| GQ | target | L3 > L2 | F0/F1 F0/F2 F0/F3 |
| GQ | target | L5 > L4 | F0/F1 F0/F2 F0/F3 |
| NC | init | L5 > L4 | F0/F4 |
| NG | init | L5 > L4 | F0/F4 |
| NX | init | L5 > L4 | F0/F4 |
| ND-GPU | init | L1root > L0 | F1/F2 |
| NF | init | L1root > L0 | F0/F1 F0/F2 F1/F2 |
| NF | init | L4 > L3 | F3/F4 |
| NF | init | L4log > L3 | F3/F4 |
| NF | init | L4log > L2 | F3/F4 |

## Comparison with the predicted partitions (REVIEW_20261006 table + the two PREDICTIONS rules)

Same unless listed. "n.o." = not observed in the campaign files.

| variant | layer | predicted | observed | verdict and reason |
|---|---|---|---|---|
| CPU | L1, L2, L4 | F0/F1/F2/F3,F4; +liveness 5; no async event | same (L4: cli_async=none 75/75) | same |
| CPU | L5 | not timed | ep_close returned 75/75 | no prediction |
| GP | L1-L4 | F0/F1/F2,F4/F3; L3 F0/F1..F4; async 2, log 4 | same (F4 rerun: 10/0x88 10/10) | same |
| GP target | L4 log | F2 split from the rest | F0,F1,F3 / F2 (async fatal event 10/10) | same |
| GG | L1, L2 | 4; 2 (trailing 5/0xf9); 2 (-EIO) | n.o. (stock GDAKI logs no CQE, driver records no -EIO) | not testable |
| GG | L3 | blocking F0..F3 silent; D2: F4 silent too | F0,F1,F2,F3 (silent 25/25) / F4 ncclTimeout 10/10 | different for F4: the app's TCP barrier saw the peer die first (10/10), and the drain then used a timeout-mode put; the blocking flush was never run on F4 |
| GG, GQ | L4, L5, target L3/L4 | F0/F1..F4; r0 returns, r1 hangs; target F1-F3 one class | same | same |
| GQ | L1 read | root found by scan-back (4) | device poll reads the trailing flush 5/0xf9 in 20/20 (2 classes); the root is recovered by the classifier at L2 | definition only: same if the scan-back is counted at L1 |
| GQ | L1 root, L2-L4 | 4, 4, 2, async 2 / log 4 | same | same |
| NC | L1, L2 | nothing; F0/F4 (spin) | n.o. | not testable |
| NC, NG, NX | L3, L4, L5 | NC hang, NG/NX one class (silent); 1; F4 hang | same | same (NG and NX F4 quiet returns after 3.5-3.8 s, 5/5 each) |
| ND-GPU | L1 read | one class (trailing 5/0xf9) | root 5/0xf5, 10/0x88, 12/0x81 (3 classes) | different: the timeout mode is the driver's own poll, which stops on the first REQ_ERR and reads the slot before trailing flushes; the predicted row is the library's poll |
| ND-GPU, ND-CPU | L1 root, L2, L4, L5 | 3 / nothing; 1; 1; hang | same | same (no F0 control) |
| ND | L3 | silent (GPU) / hang (CPU) | n.o. (timeout mode never calls nvshmem_quiet) | not testable |
| NF | L1-L4 | 4, 4, 4, 4, log 4/5 | 4, 4, 4, 4 (FT query class), log 5 | same |
| NF | L5 | returns with ft_abort | finalize returned 25/25 | same |
| NET | all | NET1: 10/0x88, ncclRemoteError | F0/F2 at every layer; S2 L1 9/10 (t1 logged no CQE, got the peer FAIL first) | same |

## Explanations of the higher-finer cases

- CPU L2 > L1 (F3/F4): the harness asks the responder over TCP (server_qp_err vs proc_kill). Added liveness channel.
- GP init L4 log > L3: the log is the proxy thread's WARN (L2), not finer than L2. The API (ncclTimeout) drops it.
- GP target L3 > L2: the target only sees that the expected signal never arrives (timeout). Data dependency, not an error channel.
- GP target L4 log > L3 (F2): verbs QP async event on the responder (IBV_EVENT_QP_ACCESS_ERR, "async fatal event"). Added channel (EV3).
- GG init L3 > L0 (F3/F4): F4's ncclTimeout comes from the drain the app starts after its TCP barrier fails. Added liveness channel plus a different wait mode.
- GG init L4 > L3 (F0/F1..F3): the host error tick ("GIN Error detected", ncclRemoteError ≈10.8 s) sees what the blocking wait dropped. Separate host channel; L1/L2 not observed.
- GG/GQ/NF/ND init L1 or L4 > L0 (F0/F1/F2): L0 port error counters do not count DEVX QPs. Instrument blind spot, not a new channel.
- GQ L2 > L1 read: Q4 classifier scans back to the root CQE. Added read channel.
- GQ init L4 log > L3: Q4 mailbox/log carries the class; the API value is ncclRemoteError for all. Not finer than L2.
- GG/GQ target L3 > L2/L0, L5 > L4: missing signal (hang), then abort hangs on the stuck kernel. No error channel on the passive side.
- NC/NG/NX L5 > L4 (F0/F4), NG/NX also L5 > L3: finalize needs the dead peer. Implicit liveness through teardown.
- NF L4 log > L3, L2 (F3/F4): "marked failed" follows the driver's decline, which uses TCP FIN liveness (dead(FIN) 5/5, alive 15/15). Added liveness channel.
