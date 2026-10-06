# Independent recount of the propagation campaign (QA)

Source: `results/20261006_campaign/` raw files only (smoke excluded); predictions from `PREDICTIONS.md`/`predictions.csv`. Script: `recount.py` (this folder). Not read: `campaign/score.py`, `SCORE.md`, `score.json`, EXPERIMENT.md sections 15-16.

Rule applied (as given): a cell holds if >=90% of its observable trials match; cells whose acceptance says 10/10, 5/5, 'every' or 'all' need all observable trials to match. Sub-cells are scored separately and the cell holds only if every testable sub-cell holds.

## 1. Trial counts vs plan (cells.sh)

| stack | planned | in trials.log | missing | extra | dup | rc!=0 | .out logs | evrec rain/sunny |
|---|--:|--:|--:|--:|--:|--:|--:|---|
| cpu | 75 | 75 | 0 | 0 | 0 | 0 | 75 | 75/75 |
| gp | 45 | 45 | 0 | 0 | 0 | 0 | 45 | 45/45 |
| gg | 40 | 40 | 0 | 0 | 0 | 0 | 40 | 40/40 |
| gq | 25 | 25 | 0 | 0 | 0 | 0 | 25 | 25/25 |
| nvo | 30 | 30 | 0 | 0 | 0 | 0 | 30 | 30/30 |
| nvd | 60 | 60 | 0 | 0 | 0 | 0 | 60 | 60/60 |
| nvf | 25 | 25 | 0 | 0 | 0 | 0 | 25 | 25/25 |
| net | 25 | 25 | 0 | 0 | 0 | 0 | 25 | 25/25 |
| total | 325 | 325 | | | | | | |

## Summary (24 cells; NET1c shown under two readings)

| cell | n obs | hits | misses | not obs. | verdict | alt: ineffective counted |
|---|--:|--:|--:|--:|---|---|
| EV1a | 10 | 10 | 0 | 0 | HOLDS | HOLDS |
| EV1b | 10 | 10 | 0 | 0 | HOLDS | HOLDS |
| EV1c | 10 | 10 | 0 | 0 | HOLDS | HOLDS |
| EV1d | 35 | 35 | 0 | 10 | HOLDS (testable sub-cells only) | HOLDS (testable sub-cells only) |
| EV1e | 75 | 75 | 0 | 0 | HOLDS | HOLDS |
| EV2a | 20 | 20 | 0 | 0 | HOLDS | HOLDS |
| EV2b | 20 | 20 | 0 | 0 | HOLDS | HOLDS |
| EV3a | 10 | 10 | 0 | 0 | HOLDS | HOLDS |
| EV3b | 10 | 10 | 0 | 0 | HOLDS | HOLDS |
| EV3c | 20 | 20 | 0 | 10 | HOLDS (testable sub-cells only) | HOLDS |
| EV4 | 170 | 170 | 0 | 10 | HOLDS | HOLDS |
| EV5a | 140 | 140 | 0 | 10 | HOLDS (testable sub-cells only) | HOLDS |
| EV5b | 15 | 15 | 0 | 0 | HOLDS | HOLDS |
| EV5c | 30 | 30 | 0 | 10 | HOLDS (testable sub-cells only) | FAILS |
| EV5d | 40 | 40 | 0 | 0 | HOLDS | HOLDS |
| NET1a | 10 | 10 | 0 | 0 | HOLDS | HOLDS |
| NET1b | 10 | 10 | 0 | 0 | HOLDS | HOLDS |
| NET1c-A | 10 | 9 | 1 | 0 | HOLDS | HOLDS |
| NET1c-B | 10 | 6 | 4 | 0 | FAILS | FAILS |
| D1 | 20 | 20 | 0 | 10 | HOLDS (testable sub-cells only) | FAILS |
| D2 | 0 | 0 | 0 | 10 | not testable | HOLDS |
| T1 | 45 | 45 | 0 | 1 | HOLDS (testable sub-cells only) | HOLDS (testable sub-cells only) |
| T2 | 15 | 15 | 0 | 0 | HOLDS | HOLDS |
| T3 | 40 | 40 | 0 | 0 | HOLDS | HOLDS |
| T4 | 20 | 20 | 0 | 0 | HOLDS | HOLDS |
| EV3a blind `logs` | 6 | 0 | 6 | - | FAILS (literal) | remote-access fault occurred in 0/6 |
| EV3a blind `v2/logs` | 6 | 6 | 0 | - | HOLDS | remote-access fault occurred in 6/6 |

## 2. Cells

Primary scoring: trials whose fault did not act during traffic (section 4) are not observable. 'Alt' counts them with whatever they showed. 'Strict' reads the acceptance clause 'no trial shows an outcome outside the predicted class' as: any miss fails the cell.

| cell | sub-cell | n obs | hits | misses (trial ids) | not observable | verdict | alt (ineffective counted) | strict |
|---|---|--:|--:|---|---|---|---|---|
| EV1a | F2 | 10 | 10 | - | 0 | HOLDS | HOLDS | HOLDS |
| | **cell verdict** | | | | | **HOLDS** | **HOLDS** | **HOLDS** |
| EV1b | rem_inv_req | 10 | 10 | - | 0 | HOLDS | HOLDS | HOLDS |
| | **cell verdict** | | | | | **HOLDS** | **HOLDS** | **HOLDS** |
| EV1c | rnr | 10 | 10 | - | 0 | HOLDS | HOLDS | HOLDS |
| | **cell verdict** | | | | | **HOLDS** | **HOLDS** | **HOLDS** |
| EV1d | F0 | 5 | 5 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | F1 | 10 | 10 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | F3 | 10 | 10 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | F4 | 0 | 0 | - | 10: responder SIGKILLed; srv_async '-' | not testable (n=0) | not testable (n=0) | not testable (n=0) |
|  | partial_write | 10 | 10 | - | 0 | HOLDS | HOLDS | HOLDS |
| | **cell verdict** | | | | | **HOLDS (testable sub-cells only)** | **HOLDS (testable sub-cells only)** | **HOLDS (testable sub-cells only)** |
| EV1e | F0 | 5 | 5 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | F1 | 10 | 10 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | F2 | 10 | 10 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | rem_inv_req | 10 | 10 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | rnr | 10 | 10 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | F3 | 10 | 10 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | F4 | 10 | 10 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | partial_write | 10 | 10 | - | 0 | HOLDS | HOLDS | HOLDS |
| | **cell verdict** | | | | | **HOLDS** | **HOLDS** | **HOLDS** |
| EV2a | F2 | 10 | 10 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | rem_inv_req | 10 | 10 | - | 0 | HOLDS | HOLDS | HOLDS |
| | **cell verdict** | | | | | **HOLDS** | **HOLDS** | **HOLDS** |
| EV2b | F1 | 10 | 10 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | rnr | 10 | 10 | - | 0 | HOLDS | HOLDS | HOLDS |
| | **cell verdict** | | | | | **HOLDS** | **HOLDS** | **HOLDS** |
| EV3a | F2 new | 10 | 10 | - | 0 | HOLDS | HOLDS | HOLDS |
| | **cell verdict** | | | | | **HOLDS** | **HOLDS** | **HOLDS** |
| EV3b | F2 | 10 | 10 | - | 0 | HOLDS | HOLDS | HOLDS |
| | **cell verdict** | | | | | **HOLDS** | **HOLDS** | **HOLDS** |
| EV3c | F1 | 10 | 10 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | F3 | 10 | 10 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | F4 | 0 | 0 | - | 10: fault ineffective (would be 10 hit / 0 miss) | not testable (n=0) | HOLDS | not testable (n=0) |
| | **cell verdict** | | | | | **HOLDS (testable sub-cells only)** | **HOLDS** | **HOLDS (testable sub-cells only)** |
| EV4 | GG | 30 | 30 | - | 10: fault ineffective (would be 10 hit / 0 miss) | HOLDS | HOLDS | HOLDS |
|  | GQ | 25 | 25 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | NC | 10 | 10 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | NG | 10 | 10 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | NX | 10 | 10 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | ND | 60 | 60 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | NF | 25 | 25 | - | 0 | HOLDS | HOLDS | HOLDS |
| | **cell verdict** | | | | | **HOLDS** | **HOLDS** | **HOLDS** |
| EV5a | GG F0 | 5 | 5 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | GG F1 | 5 | 5 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | GG F2 | 10 | 10 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | GG F3 | 10 | 10 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | GG F4 | 0 | 0 | - | 10: fault ineffective (would be 10 hit / 0 miss) | not testable (n=0) | HOLDS | not testable (n=0) |
|  | GQ F0 | 5 | 5 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | GQ F1 | 5 | 5 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | GQ F2 | 5 | 5 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | GQ F3 | 5 | 5 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | GQ F4 | 5 | 5 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | NF F0 | 5 | 5 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | NF F1 | 5 | 5 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | NF F2 | 5 | 5 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | NF F3 | 5 | 5 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | NF F4 | 5 | 5 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | ND F1 | 20 | 20 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | ND F2 | 20 | 20 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | ND F3 | 20 | 20 | - | 0 | HOLDS | HOLDS | HOLDS |
| | **cell verdict** | | | | | **HOLDS (testable sub-cells only)** | **HOLDS** | **HOLDS (testable sub-cells only)** |
| EV5b | NC | 5 | 5 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | NG | 5 | 5 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | NX | 5 | 5 | - | 0 | HOLDS | HOLDS | HOLDS |
| | **cell verdict** | | | | | **HOLDS** | **HOLDS** | **HOLDS** |
| EV5c | CPU F3 | 10 | 10 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | CPU F4 | 10 | 10 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | GP F3 | 10 | 10 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | GP F4 | 0 | 0 | - | 10: fault ineffective (would be 0 hit / 10 miss) | not testable (n=0) | FAILS | not testable (n=0) |
| | **cell verdict** | | | | | **HOLDS (testable sub-cells only)** | **FAILS** | **HOLDS (testable sub-cells only)** |
| EV5d | CPU F1 | 10 | 10 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | CPU F2 | 10 | 10 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | GP F1 | 10 | 10 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | GP F2 | 10 | 10 | - | 0 | HOLDS | HOLDS | HOLDS |
| | **cell verdict** | | | | | **HOLDS** | **HOLDS** | **HOLDS** |
| NET1a | F2stock | 10 | 10 | - | 0 | HOLDS | HOLDS | HOLDS |
| | **cell verdict** | | | | | **HOLDS** | **HOLDS** | **HOLDS** |
| NET1b | F2stock | 10 | 10 | - | 0 | HOLDS | HOLDS | HOLDS |
| | **cell verdict** | | | | | **HOLDS** | **HOLDS** | **HOLDS** |
| NET1c-A | F2 | 10 | 9 | net_F2_t1 | 0 | HOLDS | HOLDS | FAILS |
| | **cell verdict** | | | | | **HOLDS** | **HOLDS** | **FAILS** |
| NET1c-B | F2 | 10 | 6 | net_F2_t1, net_F2_t7, net_F2_t8, net_F2_t9 | 0 | FAILS | FAILS | FAILS |
| | **cell verdict** | | | | | **FAILS** | **FAILS** | **FAILS** |
| D1 | F2 | 10 | 10 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | F3 | 10 | 10 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | F4 | 0 | 0 | - | 10: fault ineffective (would be 0 hit / 10 miss) | not testable (n=0) | FAILS | not testable (n=0) |
| | **cell verdict** | | | | | **HOLDS (testable sub-cells only)** | **FAILS** | **HOLDS (testable sub-cells only)** |
| D2 | F4 | 0 | 0 | - | 10: fault ineffective (would be 10 hit / 0 miss) | not testable (n=0) | HOLDS | not testable (n=0) |
| | **cell verdict** | | | | | **not testable** | **HOLDS** | **not testable** |
| T1 | CPU (client teardown only) | 5 | 5 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | GP | 5 | 5 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | GG | 5 | 5 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | GQ | 5 | 5 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | NC | 5 | 5 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | NG | 5 | 5 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | NX | 5 | 5 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | ND | 0 | 0 | - | 1: no F0 trial planned for ND (cells.sh nvd runs F1/F2b/F3 only) | not testable (n=0) | not testable (n=0) | not testable (n=0) |
|  | NF | 5 | 5 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | NET (T0s; teardown bounded by whole-run wall_s) | 5 | 5 | - | 0 | HOLDS | HOLDS | HOLDS |
| | **cell verdict** | | | | | **HOLDS (testable sub-cells only)** | **HOLDS (testable sub-cells only)** | **HOLDS (testable sub-cells only)** |
| T2 | NC | 5 | 5 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | NG | 5 | 5 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | NX | 5 | 5 | - | 0 | HOLDS | HOLDS | HOLDS |
| | **cell verdict** | | | | | **HOLDS** | **HOLDS** | **HOLDS** |
| T3 | GG F1 | 5 | 5 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | GG F2 | 10 | 10 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | GG F3 | 10 | 10 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | GQ F1 | 5 | 5 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | GQ F2 | 5 | 5 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | GQ F3 | 5 | 5 | - | 0 | HOLDS | HOLDS | HOLDS |
| | **cell verdict** | | | | | **HOLDS** | **HOLDS** | **HOLDS** |
| T4 | F1 | 5 | 5 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | F2 | 5 | 5 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | F3 | 5 | 5 | - | 0 | HOLDS | HOLDS | HOLDS |
|  | F4 (PE0; PE1 killed) | 5 | 5 | - | 0 | HOLDS | HOLDS | HOLDS |
| | **cell verdict** | | | | | **HOLDS** | **HOLDS** | **HOLDS** |

### Observables used

- **EV1a**: prediction applied: "CPU responder F2 -> IBV_EVENT_QP_ACCESS_ERR; >=9/10 and no other QP event". Observable: cpu/logs/cpu_rem_access_t*.out '[trial 0]' field srv_async (= csv column srv_async).
- **EV1b**: prediction applied: "CPU responder rem_inv_req -> IBV_EVENT_QP_REQ_ERR; >=9/10 and no other QP event". Observable: cpu_rem_inv_req_t*.out field srv_async.
- **EV1c**: prediction applied: "CPU responder rnr -> none; 10/10". Observable: cpu_rnr_t*.out field srv_async == none.
- **EV1d**: prediction applied: "CPU responder F1;F3;F4;F0;partial_write -> none; 10/10 per fault". Observable: srv_async == none; srv_async '-' (responder dead, DEVIATIONS 4) = not observable.
- **EV1e**: prediction applied: "CPU requester, all faults -> no QP-affiliated event; 10/10 per fault". Observable: field cli_async == none.
- **EV2a**: prediction applied: "CPU responder QP state after F2;rem_inv_req -> ERR; >=9/10". Observable: field srv_qp == ERR.
- **EV2b**: prediction applied: "CPU responder QP state after rnr;F1 -> RTS; >=9/10". Observable: field srv_qp == RTS.
- **EV3a**: prediction applied: "GP r1 F2: '"async fatal event on QP" with local access violation'; >=9/10 (new)". Observable: gp/logs/proxy_F2_timeout_t*_r1.log line containing 'async fatal event on QP' and 'local access violation'.
- **EV3b**: prediction applied: "GP r1 F2: ncclCommGetAsyncError 'ncclSuccess until its own wait ends'; >=9/10". Observable: proxy_F2_*_r1.kv host_error=none (driver polls ncclCommGetAsyncError through the wait and a 15 s post-fault poll) .
- **EV3c**: prediction applied: "GP r1 F1;F3;F4: no NCCL async QP event; 10/10 per fault". Observable: no line matching /async fatal event|IBV_EVENT_|ncclIbAsyncThreadMain|async event/i in r1 log.
- **EV4**: prediction applied: "GG;GQ;NC;NG;NX;ND;NF both ranks, all faults: no QP-affiliated async error or NCCL async fatal line; every trial". Observable: both rank logs: no /async fatal event|IBV_EVENT_|ncclIbAsyncThreadMain|async event/i; evrec events=0 on both nodes (DEVIATIONS 9).
- **EV5a**: prediction applied: "GG;GQ;NF;ND both nodes, all faults: the 4 counters +0 each; every trial". Observable: evrec <tag>.evrec.{rain,sunny} hw_counters end-start for req_cqe_error, req_cqe_flush_error, local_ack_timeout_err, req_remote_access_errors.
- **EV5b**: prediction applied: "NC;NG;NX both nodes F4: same counters +0 each; every trial". Observable: as EV5a.
- **EV5c**: prediction applied: "CPU;GP requester node F3;F4: local_ack_timeout_err >=+6 and req_cqe_error >=+1; >=9/10". Observable: evrec <tag>.evrec.rain hw_counters end-start.
- **EV5d**: prediction applied: "CPU;GP requester node F1;F2: req_cqe_error >=+1; >=9/10". Observable: evrec rain hw_counters end-start.
- **NET1a**: prediction applied: "NET stock F2 requester: 10/0x88 in WARN; ncclRemoteError; >=9/10". Observable: runs/F2stock_t*/F2stock_0_r0.log: 'NCCL WARN NET/IB: Got completion ... status=10 ... vendor err 136' and '[rank0] iter N async NCCL error: remote process exited or there was a network error'.
- **NET1b**: prediction applied: "NET stock F2 target: 'async fatal event on QP' WARN and a target API error; >=9/10". Observable: F2stock_0_r1.log: 'async fatal event on QP' WARN and '[rank1] iter N async NCCL error: ...'.
- **NET1c-A**: prediction applied: "NET stage2 F2 'both': declined (REM_ACCESS); ncclRemoteError; no replay; >=9/10 -- reading A: decline and API judged on the requester (rank 0)". Observable: F2_0_r0.log: 'incident via cqe: status=10(REM_ACCESS_ERR)' + 'fault class not recoverable'; rank 0 API string = ncclRemoteError; no /recovered|replay|lead a recovery/ on either rank.
- **NET1c-B**: prediction applied: "same, reading B: ncclRemoteError required on both ranks (csv rank column 'both')". Observable: as NET1c-A plus rank 1 API string = ncclRemoteError.
- **D1**: prediction applied: "GG GPU doorbell F2;F3;F4 initiator: -EIO (L2); blocking flush success on failed op (L3); GIN Error detected at next 10 s tick (L4); >=9/10 per fault". Observable: L2 not observable in the stock driver; L3: r0 kv init_outcome=ok and r0 okit > r1 okit; L4: r0 log 'GIN Error detected' and host_error_ms - fault time <= 10.05 s (CSV columns of gg.csv, recomputed from kv: host_error_ms and fault time).
- **D2**: prediction applied: "GG blocking F4: initiator's flush returns success in the first iteration after the kill; >=9/10". Observable: r0 okit beyond r1's last iteration after kill_mono_ms; requires r0 iterations after the kill.
- **T1**: prediction applied: "every variant F0: no error at any layer on either rank; teardown returns within 5 s on both ranks; 5/5 per variant". Observable: CPU: [trial 0] status=success, srv_qp=RTS, srv_async=none, cli_async=none, client 'teardown (ep_close) returned after X ms' < 5000 (server teardown not recorded); GP/GG/GQ: both kv init_outcome=ok, host_error=none, teardown=clean teardown_ms<5000, r1 data_check=ok, no 'GIN Error'/'Got completion' line; NC/NG/NX kill0: pe0/pe1 rc 0, 40/40 iterations, 'nvshmem_finalize returned after X ms' < 5000 on both PEs, no error lines; NF none: SUMMARY rc=0 and 'TEARDOWN rank N ... returned=1' both PEs; NET T0s: SUMMARY rc=0 both ranks, no API error, no ABORT-HANG, whole-run wall_s < 5.
- **T2**: prediction applied: "NC;NG;NX F4: PE0 nvshmem_finalize does not return within 30 s; 5/5 per variant". Observable: nvo/runs/*_kill1_t*.pe0.log 'PE 0: nvshmem_finalize did not return after 30 s'.
- **T3**: prediction applied: "GG;GQ blocking F1;F2;F3: r0 ncclCommAbort returns; r1 does not within 30 s; 5/5 per cell". Observable: r0 kv teardown=clean; r1 kv 'teardown=hang teardown_bound_s=30'.
- **T4**: prediction applied: "NF F1;F3: finalize returns on both PEs; F2;F4: return only after the driver's ft_abort; 5/5 per cell". Observable: TEARDOWN rank N ... returned=1; for F2/F4 'marked failed (recovery declined/aborted)' (printed by nvshmemt_ibgda_ft_abort) before the TEARDOWN line.

## 3. EV3a blind part (2026-09-23 GIN logs)

- `logs`: 0/6 r1 logs carry the line. Rank 0 saw status=10 (remote access) in 0/6; r1 silent_success flags: ['1', '1', '1', '1', '1', '1']; r1 host_error: ['none'].
- `v2/logs`: 6/6 r1 logs carry the line. Rank 0 saw status=10 (remote access) in 6/6; r1 silent_success flags: ['0', '0', '0', '0', '0', '0']; r1 host_error: ['none'].
- `ref60/logs`: no proxy F2 r1 logs.

Blind EV3c (proxy F1/F3/F4 r1 logs, no async event line): `logs` 19/19; `v2/logs` 18/18; `ref60/logs` 4/4

## 4. Fault effectiveness

Ineffective fault trials: 20

- gp F4 (10): gp_F4_timeout_t1, gp_F4_timeout_t2, gp_F4_timeout_t3, gp_F4_timeout_t4, gp_F4_timeout_t5, gp_F4_timeout_t6, gp_F4_timeout_t7, gp_F4_timeout_t8, gp_F4_timeout_t9, gp_F4_timeout_t10. Evidence: rank1 printed 'DONE okIters=120' before SIGKILL; rank0 120/120 ok, no peer loss.
- gg F4 (10): gg_F4_blocking_t1, gg_F4_blocking_t2, gg_F4_blocking_t3, gg_F4_blocking_t4, gg_F4_blocking_t5, gg_F4_blocking_t6, gg_F4_blocking_t7, gg_F4_blocking_t8, gg_F4_blocking_t9, gg_F4_blocking_t10. Evidence: rank1 printed 'DONE okIters=120' before SIGKILL; rank0 120/120 ok, no peer loss.

## 5. Per-trial details used in the verdicts

GP/GG F4 kill vs workload (rank 1 finished all 120 iterations before the SIGKILL):

| trial | r0 iters ok | r1 'DONE okIters=120' | r0 peer gone | r0 host_error |
|---|--:|---|---|---|
| gp_F4_timeout_t1 | 120 | True | False | none |
| gp_F4_timeout_t2 | 120 | True | False | none |
| gp_F4_timeout_t3 | 120 | True | False | none |
| gp_F4_timeout_t4 | 120 | True | False | none |
| gp_F4_timeout_t5 | 120 | True | False | none |
| gp_F4_timeout_t6 | 120 | True | False | none |
| gp_F4_timeout_t7 | 120 | True | False | none |
| gp_F4_timeout_t8 | 120 | True | False | none |
| gp_F4_timeout_t9 | 120 | True | False | none |
| gp_F4_timeout_t10 | 120 | True | False | none |
| gg_F4_blocking_t1 | 120 | True | False | none |
| gg_F4_blocking_t2 | 120 | True | False | none |
| gg_F4_blocking_t3 | 120 | True | False | none |
| gg_F4_blocking_t4 | 120 | True | False | none |
| gg_F4_blocking_t5 | 120 | True | False | none |
| gg_F4_blocking_t6 | 120 | True | False | none |
| gg_F4_blocking_t7 | 120 | True | False | none |
| gg_F4_blocking_t8 | 120 | True | False | none |
| gg_F4_blocking_t9 | 120 | True | False | none |
| gg_F4_blocking_t10 | 120 | True | False | none |

Requester-node (rain) counter deltas, EV5c/EV5d (req_cqe_error/req_cqe_flush_error/local_ack_timeout_err/req_remote_access_errors):

- cpu_local_qp_err_t1: 32/31/0/0
- cpu_local_qp_err_t2: 32/31/0/0
- cpu_local_qp_err_t3: 32/31/0/0
- cpu_local_qp_err_t4: 32/31/0/0
- cpu_local_qp_err_t5: 32/31/0/0
- cpu_local_qp_err_t6: 32/31/0/0
- cpu_local_qp_err_t7: 32/31/0/0
- cpu_local_qp_err_t8: 32/31/0/0
- cpu_local_qp_err_t9: 32/31/0/0
- cpu_local_qp_err_t10: 32/31/0/0
- cpu_rem_access_t1: 1/0/0/1
- cpu_rem_access_t2: 1/0/0/1
- cpu_rem_access_t3: 1/0/0/1
- cpu_rem_access_t4: 1/0/0/1
- cpu_rem_access_t5: 1/0/0/1
- cpu_rem_access_t6: 1/0/0/1
- cpu_rem_access_t7: 1/0/0/1
- cpu_rem_access_t8: 1/0/0/1
- cpu_rem_access_t9: 1/0/0/1
- cpu_rem_access_t10: 1/0/0/1
- cpu_retry_server_qp_err_t1: 1/0/6/0
- cpu_retry_server_qp_err_t2: 1/0/6/0
- cpu_retry_server_qp_err_t3: 1/0/6/0
- cpu_retry_server_qp_err_t4: 1/0/6/0
- cpu_retry_server_qp_err_t5: 1/0/6/0
- cpu_retry_server_qp_err_t6: 1/0/6/0
- cpu_retry_server_qp_err_t7: 1/0/6/0
- cpu_retry_server_qp_err_t8: 1/0/6/0
- cpu_retry_server_qp_err_t9: 1/0/6/0
- cpu_retry_server_qp_err_t10: 1/0/6/0
- cpu_retry_proc_sigkill_t1: 1/0/6/0
- cpu_retry_proc_sigkill_t2: 1/0/6/0
- cpu_retry_proc_sigkill_t3: 1/0/6/0
- cpu_retry_proc_sigkill_t4: 1/0/6/0
- cpu_retry_proc_sigkill_t5: 1/0/6/0
- cpu_retry_proc_sigkill_t6: 1/0/6/0
- cpu_retry_proc_sigkill_t7: 1/0/6/0
- cpu_retry_proc_sigkill_t8: 1/0/6/0
- cpu_retry_proc_sigkill_t9: 1/0/6/0
- cpu_retry_proc_sigkill_t10: 1/0/6/0
- gp_F1_timeout_t1: 2/1/0/0
- gp_F1_timeout_t2: 2/1/0/0
- gp_F1_timeout_t3: 2/1/0/0
- gp_F1_timeout_t4: 2/1/0/0
- gp_F1_timeout_t5: 2/1/0/0
- gp_F1_timeout_t6: 2/1/0/0
- gp_F1_timeout_t7: 2/1/0/0
- gp_F1_timeout_t8: 2/1/0/0
- gp_F1_timeout_t9: 2/1/0/0
- gp_F1_timeout_t10: 2/1/0/0
- gp_F2_timeout_t1: 2/1/0/1
- gp_F2_timeout_t2: 2/1/0/1
- gp_F2_timeout_t3: 2/1/0/1
- gp_F2_timeout_t4: 2/1/0/1
- gp_F2_timeout_t5: 2/1/0/1
- gp_F2_timeout_t6: 2/1/0/1
- gp_F2_timeout_t7: 2/1/0/1
- gp_F2_timeout_t8: 2/1/0/1
- gp_F2_timeout_t9: 2/1/0/1
- gp_F2_timeout_t10: 2/1/0/1
- gp_F3_timeout_t1: 2/1/6/0
- gp_F3_timeout_t2: 2/1/6/0
- gp_F3_timeout_t3: 2/1/6/0
- gp_F3_timeout_t4: 2/1/6/0
- gp_F3_timeout_t5: 2/1/6/0
- gp_F3_timeout_t6: 2/1/6/0
- gp_F3_timeout_t7: 2/1/6/0
- gp_F3_timeout_t8: 2/1/6/0
- gp_F3_timeout_t9: 2/1/6/0
- gp_F3_timeout_t10: 2/1/6/0
- gp_F4_timeout_t1: 0/0/0/0
- gp_F4_timeout_t2: 0/0/0/0
- gp_F4_timeout_t3: 0/0/0/0
- gp_F4_timeout_t4: 0/0/0/0
- gp_F4_timeout_t5: 0/0/0/0
- gp_F4_timeout_t6: 0/0/0/0
- gp_F4_timeout_t7: 0/0/0/0
- gp_F4_timeout_t8: 0/0/0/0
- gp_F4_timeout_t9: 0/0/0/0
- gp_F4_timeout_t10: 0/0/0/0

Non-zero 4-counter deltas on any node in DEVX trials (EV5a/EV5b):

- none

NET F2 (Stage 2) per trial: r0 status source / declined-by-class / r0 API / r1 API / r1 async fatal / replay:

- net_F2_t1: status=None (None), declined_by_class=False, r0 fail reason='peer failed or declined', r0_api='remote process exited or there was a network error', r1_api='unhandled system error (run with NCCL_DEBUG=INFO for details)', r1_async_fatal=True, replay=False, r1 API before async line=False
- net_F2_t2: status=10 (FR2 line), declined_by_class=True, r0 fail reason='fault class not recoverable', r0_api='remote process exited or there was a network error', r1_api='remote process exited or there was a network error', r1_async_fatal=True, replay=False, r1 API before async line=False
- net_F2_t3: status=10 (FR2 line), declined_by_class=True, r0 fail reason='fault class not recoverable', r0_api='remote process exited or there was a network error', r1_api='remote process exited or there was a network error', r1_async_fatal=True, replay=False, r1 API before async line=True
- net_F2_t4: status=10 (FR2 line), declined_by_class=True, r0 fail reason='fault class not recoverable', r0_api='remote process exited or there was a network error', r1_api='remote process exited or there was a network error', r1_async_fatal=True, replay=False, r1 API before async line=True
- net_F2_t5: status=10 (FR2 line), declined_by_class=True, r0 fail reason='fault class not recoverable', r0_api='remote process exited or there was a network error', r1_api='remote process exited or there was a network error', r1_async_fatal=True, replay=False, r1 API before async line=True
- net_F2_t6: status=10 (FR2 line), declined_by_class=True, r0 fail reason='fault class not recoverable', r0_api='remote process exited or there was a network error', r1_api='remote process exited or there was a network error', r1_async_fatal=True, replay=False, r1 API before async line=False
- net_F2_t7: status=10 (FR2 line), declined_by_class=True, r0 fail reason='fault class not recoverable', r0_api='remote process exited or there was a network error', r1_api='unhandled system error (run with NCCL_DEBUG=INFO for details)', r1_async_fatal=True, replay=False, r1 API before async line=False
- net_F2_t8: status=10 (FR2 line), declined_by_class=True, r0 fail reason='fault class not recoverable', r0_api='remote process exited or there was a network error', r1_api='unhandled system error (run with NCCL_DEBUG=INFO for details)', r1_async_fatal=True, replay=False, r1 API before async line=False
- net_F2_t9: status=10 (FR2 line), declined_by_class=True, r0 fail reason='fault class not recoverable', r0_api='remote process exited or there was a network error', r1_api='unhandled system error (run with NCCL_DEBUG=INFO for details)', r1_async_fatal=True, replay=False, r1 API before async line=False
- net_F2_t10: status=10 (FR2 line), declined_by_class=True, r0 fail reason='fault class not recoverable', r0_api='remote process exited or there was a network error', r1_api='remote process exited or there was a network error', r1_async_fatal=True, replay=False, r1 API before async line=True
- net_F2stock_t1: status=10 (stock WARN), declined_by_class=False, r0 fail reason='None', r0_api='remote process exited or there was a network error', r1_api='remote process exited or there was a network error', r1_async_fatal=True, replay=False, r1 API before async line=True
- net_F2stock_t2: status=10 (stock WARN), declined_by_class=False, r0 fail reason='None', r0_api='remote process exited or there was a network error', r1_api='remote process exited or there was a network error', r1_async_fatal=True, replay=False, r1 API before async line=True
- net_F2stock_t3: status=10 (stock WARN), declined_by_class=False, r0 fail reason='None', r0_api='remote process exited or there was a network error', r1_api='remote process exited or there was a network error', r1_async_fatal=True, replay=False, r1 API before async line=True
- net_F2stock_t4: status=10 (stock WARN), declined_by_class=False, r0 fail reason='None', r0_api='remote process exited or there was a network error', r1_api='remote process exited or there was a network error', r1_async_fatal=True, replay=False, r1 API before async line=True
- net_F2stock_t5: status=10 (stock WARN), declined_by_class=False, r0 fail reason='None', r0_api='remote process exited or there was a network error', r1_api='remote process exited or there was a network error', r1_async_fatal=True, replay=False, r1 API before async line=True
- net_F2stock_t6: status=10 (stock WARN), declined_by_class=False, r0 fail reason='None', r0_api='remote process exited or there was a network error', r1_api='remote process exited or there was a network error', r1_async_fatal=True, replay=False, r1 API before async line=False
- net_F2stock_t7: status=10 (stock WARN), declined_by_class=False, r0 fail reason='None', r0_api='remote process exited or there was a network error', r1_api='remote process exited or there was a network error', r1_async_fatal=True, replay=False, r1 API before async line=True
- net_F2stock_t8: status=10 (stock WARN), declined_by_class=False, r0 fail reason='None', r0_api='remote process exited or there was a network error', r1_api='remote process exited or there was a network error', r1_async_fatal=True, replay=False, r1 API before async line=True
- net_F2stock_t9: status=10 (stock WARN), declined_by_class=False, r0 fail reason='None', r0_api='remote process exited or there was a network error', r1_api='remote process exited or there was a network error', r1_async_fatal=True, replay=False, r1 API before async line=True
- net_F2stock_t10: status=10 (stock WARN), declined_by_class=False, r0 fail reason='None', r0_api='remote process exited or there was a network error', r1_api='remote process exited or there was a network error', r1_async_fatal=True, replay=False, r1 API before async line=True

NET target (rank 1) ordering, F2stock: own flushed Recv CQE -> API error -> async fatal WARN (us):

- net_F2stock_t1: r1 CQE status=5, API-CQE=48 us, API-asyncWARN=-107 us
- net_F2stock_t2: r1 CQE status=5, API-CQE=47 us, API-asyncWARN=-55 us
- net_F2stock_t3: r1 CQE status=5, API-CQE=35 us, API-asyncWARN=-113 us
- net_F2stock_t4: r1 CQE status=5, API-CQE=44 us, API-asyncWARN=-112 us
- net_F2stock_t5: r1 CQE status=5, API-CQE=47 us, API-asyncWARN=-54 us
- net_F2stock_t6: r1 CQE status=5, API-CQE=128 us, API-asyncWARN=8 us
- net_F2stock_t7: r1 CQE status=5, API-CQE=45 us, API-asyncWARN=-112 us
- net_F2stock_t8: r1 CQE status=5, API-CQE=46 us, API-asyncWARN=-109 us
- net_F2stock_t9: r1 CQE status=5, API-CQE=93 us, API-asyncWARN=-54 us
- net_F2stock_t10: r1 CQE status=5, API-CQE=49 us, API-asyncWARN=-111 us

Target API error before the async fatal WARN: 9/10 F2stock trials; own flush CQE before the API error: 10/10.

GG D1 per trial (L3 silent flush, L4 GIN Error, surface ms):

- gg_F2_blocking_t1: L3=True L4=True surface_ms=9999.4
- gg_F2_blocking_t2: L3=True L4=True surface_ms=10000.3
- gg_F2_blocking_t3: L3=True L4=True surface_ms=9999.8
- gg_F2_blocking_t4: L3=True L4=True surface_ms=10000.3
- gg_F2_blocking_t5: L3=True L4=True surface_ms=9999.7
- gg_F2_blocking_t6: L3=True L4=True surface_ms=10000.6
- gg_F2_blocking_t7: L3=True L4=True surface_ms=10000.1
- gg_F2_blocking_t8: L3=True L4=True surface_ms=10000.0
- gg_F2_blocking_t9: L3=True L4=True surface_ms=10000.3
- gg_F2_blocking_t10: L3=True L4=True surface_ms=10000.2
- gg_F3_blocking_t1: L3=True L4=True surface_ms=9403.6
- gg_F3_blocking_t2: L3=True L4=True surface_ms=9403.8
- gg_F3_blocking_t3: L3=True L4=True surface_ms=9402.9
- gg_F3_blocking_t4: L3=True L4=True surface_ms=9404.0
- gg_F3_blocking_t5: L3=True L4=True surface_ms=9404.0
- gg_F3_blocking_t6: L3=True L4=True surface_ms=9403.4
- gg_F3_blocking_t7: L3=True L4=True surface_ms=9404.9
- gg_F3_blocking_t8: L3=True L4=True surface_ms=9403.3
- gg_F3_blocking_t9: L3=True L4=True surface_ms=9403.7
- gg_F3_blocking_t10: L3=True L4=True surface_ms=9403.9
- gg_F4_blocking_t1: L3=False L4=False surface_ms=None
- gg_F4_blocking_t2: L3=False L4=False surface_ms=None
- gg_F4_blocking_t3: L3=False L4=False surface_ms=None
- gg_F4_blocking_t4: L3=False L4=False surface_ms=None
- gg_F4_blocking_t5: L3=False L4=False surface_ms=None
- gg_F4_blocking_t6: L3=False L4=False surface_ms=None
- gg_F4_blocking_t7: L3=False L4=False surface_ms=None
- gg_F4_blocking_t8: L3=False L4=False surface_ms=None
- gg_F4_blocking_t9: L3=False L4=False surface_ms=None
- gg_F4_blocking_t10: L3=False L4=False surface_ms=None

## 6. Ambiguities that change a verdict

1. **Ineffective F4 in GP and GG (20 trials).** Excluding them (primary) vs counting them (alt): EV5c HOLDS (testable sub-cells only) vs FAILS (GP F4 0/10 on rain counters); D1 HOLDS (testable sub-cells only) (F4 untestable) vs FAILS (F4 0/10); D2 not testable vs HOLDS (10/10 only because nothing failed). EV3c F4, EV4 GG F4 and EV5a GG F4 hold either way, but those 30 hits are trivial.
2. **Acceptance clause 'no trial shows an outcome outside the predicted class'.** Read as 'any miss fails', NET1c-A goes from HOLDS (9/10) to FAILS. No other cell has a 9/10.
3. **NET1c rank scope.** The csv rank column says 'both'. ncclRemoteError on both ranks: FAILS (6/10; rank 1 returned 'unhandled system error' in t1, t7, t8, t9). Requester only: 9/10 (t1 failed through rank 1's async-event FAIL before rank 0 saw REM_ACCESS).
4. **EV3a blind part: which retained logs.** `logs` 0/6; `v2/logs` 6/6. The `logs/` runs used the old in-MR overrun (rank 0 saw no status=10, rank 1 reports SILENT-SUCCESS with the signal delivered), so no remote access fault happened. 'Every retained r1 F2 log' read literally over both folders: 6/12, fails; with the `logs/` trials as not observable: 6/6, holds.
5. **NET1b mechanism.** Literal prediction ('async fatal WARN and a target API error') holds 10/10. The stated reason (target API error raised by the fatal-count check) is not what produced it: the target's API error follows its own flushed Recv CQE (status 5) and precedes the async WARN in 9/10.
6. **Not verdict-changing but untested parts:** D1 L2 (device -EIO) is not observable with the stock driver and the GPU-doorbell mode is not logged (PeerMappingOverride=1 on rain at QA time); T4 'only after ft_abort' has no no-abort control; T1 has no ND F0 run, no CPU server teardown time, and NET teardown is bounded only by the whole-run wall time (<1.6 s); EV1d F4 is not observable (DEVIATIONS 4); EV4 'async error' means the verbs QP-affiliated event: GG/GQ do raise ncclCommGetAsyncError ('GIN Error detected'), which D1 itself predicts.

