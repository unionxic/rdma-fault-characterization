# Pre-registered predictions for the cross-layer propagation campaign

Written 2026-10-06, before any run of the campaign below and before the retained raw data were
inspected for the new observables. `predictions.csv` is the machine-readable form. Both files are
fixed by the sha256 in `PREREG.txt`. After that, any change to a prediction, an acceptance rule or
the analysis is appended to `DEVIATIONS.md` with its reason, and the original stays the one that is
scored.

The analysis frame is in `REVIEW_20261006.md`: layers L0-L5, faults F0-F4, and the partition of the
fault set per layer.

## Method

- **Three kinds of cell.**
  - **R** (replication) cells were measured before. They are predicted to equal the
    `REVIEW_20261006.md` matrix and are re-run so that the final table comes from one campaign
    with one instrumentation.
  - **N** (new) cells were never measured. They are the out-of-sample test.
  - **B** (blind) cells exist in retained raw logs but were never examined for this observable.
    They are scored on the old logs and again on the new runs.
- **Basis.** Every N/B prediction names its basis: a source line, a specification, or an earlier
  measurement on another stack. Predictions follow from the analysis frame:
  - DEVX-created QPs have no async-error path;
  - the passive side of a one-sided operation gets no completion;
  - a CQE exists whenever the doorbell record is correct.
- **N per cell.** 10 for N and B cells, 5 for R cells, 5 for F0 controls. Every trial is a fresh
  process pair.
- **Acceptance.**
  - Categorical prediction: holds if at least 9/10 (or 5/5) trials show the predicted outcome and
    no trial shows an outcome outside the predicted class.
  - Timing prediction: holds if every trial lies in the stated range.
  - Partition prediction (per variant and layer): holds if the observed classes equal the
    predicted ones.
  - Every miss is reported, including misses in R cells.
- **Reporting.** Per cell: n, count, Wilson 95% interval, the timing distribution (median and
  range). Misses are listed individually (Hoefler & Belli, SC'15 rules 1-6).

## Instrumentation added for this campaign (none of it changes a data path)

1. **`evrec`, run on both nodes for every trial.** It opens the RoCE device and records port-level
   async events with timestamps, and the port `hw_counters` at trial start and end. It sees only
   port events: QP-affiliated events go to the context that owns the QP.
2. **CPU harness.**
   - An async-event thread in `probe_client` and `probe_server`, for QP-affiliated events on both
     sides.
   - A `none` (F0) scenario.
   - A real SIGKILL scenario.
   - A server-side QUERY_QP after the fault.
   - Teardown timing.
3. **Test drivers (GIN, NVSHMEM `kill_repro`).**
   - Teardown (`ncclCommAbort` / `nvshmem_finalize`) is timed on both ranks, with a 30 s bound.
   - The target's library log is kept at `NCCL_DEBUG=WARN` or higher.

## Variants

| id | stack | build | doorbell |
|---|---|---|---|
| CPU | harness verbs RC | this repo | CPU |
| GP | NCCL 2.32.3 GIN proxy | stock bundle `gin` | CPU (verbs) |
| GG | NCCL 2.32.3 GIN GDAKI | stock bundle `gin` | GPU |
| GQ | GDAKI + Q4 | bundle `gin_q4` | GPU |
| NC / NG / NX | NVSHMEM IBGDA CPU proxy / GPU handler / CPU proxy + 2-line fix | official v3.8.0-0 (`official380/`) | CPU / GPU / CPU |
| ND | NVSHMEM devel 7bb2e99 + fault-inject diff (F1-F3 only) | `gi-bundle/nvshmem` | CPU and GPU handler |
| NF | NVSHMEM FT v2.2 | `gi-bundle/nvshmem_ft2` | GPU |
| NET | NCCL 2.23.4 net_ib, stock and Stage 2 | `nccl-integration` | CPU |

Faults per variant:
- CPU: F0, F1, F2 (out-of-MR write), rem_inv_req, rnr, F3, F4 (SIGKILL), partial_write.
- GP, GG, GQ: F0-F4, in timeout and blocking wait modes.
- NC/NG/NX: F0 and F4 (public API only).
- ND: F1-F3.
- NF: F0-F4.
- NET: F0 and F2.

## New and blind predictions

### Channels that exist below the API (principle 2)

| id | cells | prediction | basis | kind |
|---|---|---|---|---|
| EV1 | CPU, responder side, QP-affiliated async events | F2 → `IBV_EVENT_QP_ACCESS_ERR`; rem_inv_req → `IBV_EVENT_QP_REQ_ERR`; rnr, F1, F3, F4, F0 → none. Requester side: no QP-affiliated event in any fault (its errors arrive as CQEs). | verbs async-event semantics (`ibv_get_async_event(3)`); old CX-5 responder states (`OLD/05_counter_mapping/results/raw/qp_state_verify.csv`) | N |
| EV2 | CPU, responder QP state after the fault | F2, rem_inv_req → ERR; rnr → RTS; F1 → RTS (peer untouched); F3 → ERR (by construction) | same | N |
| EV3 | GP, target rank (r1) log and async error | F2 → r1 log has `NET/IB : ... async fatal event on QP ... local access violation work queue error`, but r1 `ncclCommGetAsyncError` stays `ncclSuccess` until its own wait ends (timeout or hang). F1, F3, F4 → no async QP event on r1. | `net_ib/common.cc:187-201` marks the QP fatal; no GIN path calls `ncclIbStatsCheckFatalCount` (only `p2p.cc`) | B + N |
| EV4 | GG, GQ, NC, NG, NX, ND, NF, both ranks | no QP-affiliated async error ever, for any fault; no `async fatal event` line | GIN/NVSHMEM QPs are DEVX objects; DOCA subscribes its DEVX channel to completion events only (`doca_verbs_cq.cpp:978`); NVSHMEM 3.8.0 has no async-event code | N |
| EV5 | port `hw_counters` per trial, both nodes | DEVX variants: `req_cqe_error`, `req_cqe_flush_error`, `local_ack_timeout_err`, `req_remote_access_errors` all +0 in every fault. Verbs variants (CPU, GP): F3/F4 → requester `local_ack_timeout_err` ≥ +6 and `req_cqe_error` ≥ +1; F1, F2 → `req_cqe_error` ≥ +1. | official380 (+0 for DEVX, once); NVIDIA/nvshmem#64; verbs QPs use the port q counter | N (R for NC/NG/NX F4) |
| NET1 | NET, F2 | Stock: requester WARN with status 10 / vendor 0x88, API `ncclRemoteError`; target: `async fatal event on QP` WARN **and** a target API error, because the target's own test/irecv calls `ncclIbStatsCheckFatalCount`. Stage 2: declined (REM_ACCESS), `ncclRemoteError`, no replay. | v2.23.4 `p2p` fatal-count checks; Stage 2 decline rule (`DESIGN_recovery.md`) | N |

EV3 and NET1 together predict a contrast. The same NCCL async-event code reaches the target's API
in the two-sided net_ib protocol, but not in one-sided GIN.

### Doorbell contract (principle 1)

| id | cells | prediction | basis | kind |
|---|---|---|---|---|
| D1 | GG with GPU doorbells, F2, F3, F4 | Same as the CPU-doorbell runs: device `-EIO` (L2), blocking flush returns success on the failed op (L3), host `GIN Error detected` at the next 10 s tick (L4) | DOCA writes doorbell-record word 1 before the UAR in either mode, so the CQE is generated regardless of who rings | N |
| D2 | GG blocking, F4 | the initiator's flush returns success in the first iteration after the kill (silent) | same void wait as F1-F3; F4 gives 12/0x81 on sunny's DEVX QPs | N |

### Passive side and teardown (principle 2, passive side)

| id | cells | prediction | basis | kind |
|---|---|---|---|---|
| T1 | every variant, F0 | no error at any layer on either rank; teardown returns on both ranks within 5 s | - | N |
| T2 | NC, NG, NX, F4 | PE 0 `nvshmem_finalize` does not return within 30 s | devel: hangs after any QP error (`nvshmem/`) | N on 3.8.0 |
| T3 | GG, GQ, blocking F1-F3 | r0 teardown returns, r1 does not (30 s bound) | `gin.md` §1b/1c | R |
| T4 | NF, F1/F3 (recovered) | finalize returns on both PEs; F2/F4 (declined) return only after the driver's `ft_abort` | `nvshmem.md` §2 | R |

### Predicted partitions (R cells, and the frame for scoring)

The partitions are the rows of `REVIEW_20261006.md` "Partition of {F0..F4} per layer", with two
additions:
- for GG and GQ, the target rank has one class at L3/L4 for F1-F3 (EV4);
- for GP, the target rank at L4-log splits F2 from the rest (EV3).

## What would count against the frame

- **An async error on a DEVX-QP stack (EV4).** It would mean that an error channel exists which
  the frame says is absent.
- **A target-side API error in GIN (EV3).** It would mean the passive side is not blind.
- **A GPU-doorbell GDAKI run that loses the CQE (D1).** It would mean CQE generation depends on
  the doorbell path, not only on the doorbell record.
- **Any layer whose partition is finer than the layer below it without an added channel.** That
  is the core claim of principle 2.
