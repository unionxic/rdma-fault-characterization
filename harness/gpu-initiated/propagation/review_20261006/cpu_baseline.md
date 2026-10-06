# Review: CPU-verbs baseline and CPU-side studies

Read-only review, 2026-10-06. Nothing in the repo was changed and nothing was run on the cluster.
Every number below was either recounted from raw CSVs or logs (marked "recount") or quoted from a
README (marked with its path).

Path shorthands:
- `H` = `/home/unionxic/rdma-error/harness`
- `CQ` = `H/gpu-initiated/cqe_seq`
- `FT` = `H/fingerprint_teardown`
- `AT` = `H/ack_timeout`
- `OLD` = `/home/unionxic/rdma-error/experiments/225-client`

Testbeds:
- **Current:** rain (CX-6 fw 20.43.4100, OFED 23.10, kernel 5.15) → sunny (CX-6 fw 20.43.4100, OFED 25.10, kernel 6.8). RoCE v2, PMTU 4096, T=14, retry_cnt 7, rnr_retry 6, min_rnr_timer 12. In the harness, CPU 2 is pinned on both nodes.
- **OLD:** client CX-6 fw 20.40.1000 → server CX-5 fw 16.35.8002, PMTU 1024, rnr_retry 0 for RNR. The data is from 2026-05 to 2026-07.

Status tags:
- **measured:** raw data is in the repo and I recounted it.
- **measured\*:** a README reports it as measured, but the raw data is not in the repo.
- **inferred:** derived from other cells.
- **source-only:** code reading only.

## 0. Fault inventory: how the harness faults map to F0-F4

| F | experiment and trigger (current testbed unless marked OLD) | N, date |
|---|---|---|
| F0 none | No dedicated run: `probe_client` rejects `-f none` (`H/client/probe_client.c:166`). The only F0 data is pre-fault traffic: SUCCESS CQEs in CQ, the warm-up WRITE in AT, and 300 ms of streaming in FT. | n/a |
| F1 local QP→ERR | `local_qp_err`: 32 × 4 MiB WRITEs, then the host calls modify_qp(ERR). `partial_write`: 1 × 4 MiB WRITE, then ERR mid-transfer. CQ runs local_qp_err with N∈{1,4,16,64} and 4 KiB / 64 KiB / 4 MiB WQEs. | H: 30 per run, 2026-09-23; CQ: 120 trials, 2026-09-23 |
| F2 remote access | `rem_access`: valid rkey, address past the end of the MR. Invalid rkey: only the middleware demo (`rkey=0xdeadbeef`, N=1, current) and OLD N=100. Live `ibv_dereg_mr` and a dying peer whose MR goes first: FT. | H 30; CQ 100; FT 90 dereg + 111 kill |
| F2' rem_inv_req | Atomic to a QP without REMOTE_ATOMIC. The OLD trigger was different: a WRITE to an MR without REMOTE_WRITE. | H 30; CQ 100 |
| rnr | SEND with no receive posted, rnr_retry 6 | H 30; CQ 70 |
| F3 peer QP ERR, peer alive | `retry_server_qp_err`: sunny modifies its QP to ERR on GO. FT `ctl_*destroy_qp` (live `ibv_destroy_qp`). AT: the responder QP goes to ERR (317 trials). | H 30; CQ 40; FT 20; AT 317 |
| F4 peer killed | `retry_proc_kill` is **not a SIGKILL**. The server calls `ep_close()`, so its QP is destroyed first, and it exits on GO. The client posts 300 ms later (`H/server/probe_server.c:300-305`, `probe_client.c:251-254`). Real SIGKILL: FT, 270 trials (N=10 per variant). | H 30; CQ 40; FT 270 |
| link down | Dry run only. The 5 rows in `H/results/retry_link_down_20260923_124421.csv` are `no_error_cqe` (status -1). A real link toggle is not allowed under the cluster rules. | 0 real |
| LOC_PROT 0x53/0x52/0x33 | Not in the harness. Current testbed: 0x53 N=1 (middleware demo). OLD: N=100 each. | |
| silent (no error) | FT `ctl_*cuda_free`, `ctl_gpu_cuda_reset`: GPU memory is freed while its MR is still registered. | 30, 2026-09-25 |

## 1. Observations per (fault, layer) cell

The harness itself is the L2 consumer; its CSV row is the L2 output. `det` = inject → first error
CQE as polled.

| fault | layer | observation (exact codes, times) | N, date | raw source → summariser | tag |
|---|---|---|---|---|---|
| F0 | L1 | Only signaled WQEs complete. 2,057 SUCCESS CQEs, none from an unsignaled WQE. | 470 trials, 2026-09-23 | `CQ/results/raw_*.csv` → `analyze_cqe_seq.py` (recount) | measured |
| F0 | L0 | Warm-up WRITE ok in 317/317 trials. Timeout counters (`local_ack_timeout_err`, `roce_adp_retrans`) changed 0 times in the 300 ms quiet window of 152 sampled trials. | 2026-09-25 | `AT/results/20260925/*/trials.csv` (warm_ok recount); quiet window from `AT/README.md` | measured |
| F1 local_qp_err | L0 | QP state after: ERR, 120/120. `ibv_modify_qp(ERR)` takes about 217 µs. Requester `roce_adp_retrans` Δ0, 30/30. | CQ 120; H 30 (123945) | `CQ/results/trials_local_qp_err_*.csv` `qp_state_after`; `H/results/local_qp_err_20260923_123945.csv` `cnt_delta` | measured |
| F1 local_qp_err | L1 | First error CQE is 5/0xf5 (30/30), det median 224.9 µs [223.2-246.7]. Full sequence: 5/0xf5 on the head WQE, then one 5/0xf9 per trailing WQE in WQE order; the first flush comes 59.5 µs after the root, then one every 9.35 µs. **With nothing outstanding (4 KiB WQEs, or 64 KiB WQEs with N≤4) no CQE is written at all, though the QP is ERR: 60/60.** With ≥2 outstanding, the last CQE is 5/0xf9. | H 30; CQ 120 | H csv → `H/analyze.py`; `CQ/results/raw_local_qp_err_{main,supp4k,supp64k}.csv` | measured |
| F1 local_qp_err | L2 | `classify` → "WR flushed", peer_alive=1, auto_recoverable=1 (30/30). QP-only recovery median 0.79 ms; full_rebuild (QP only) median 1.79 ms (run 114031); verify 30/30. The harness reads only the first error CQE, and RESET makes libmlx5 discard the 31 remaining flush CQEs. | 30 | as above, `114031` | measured (discard: source-only, `CQ/README.md`) |
| F1 local_qp_err | L4 | No async event is expected for a software-forced ERR, but none was ever recorded. | | `H/nccl-integration/DESIGN_recovery.md:202` | source-only |
| F1 local_qp_err | L5 | The client exits 0 and `run.sh` checks the row count. Teardown was not timed. | 30 | `H/run.sh` | inferred |
| F1 partial_write | L0 | `sq_psn` advance from QUERY_QP: 265-276 PSN × 4096 = 1,085,440-1,130,496 B (30/30). | 30, 123945 | `H/results/partial_write_20260923_123945.csv` | measured |
| F1 partial_write | L1 | 5/0xf5, det median 338.3 µs [328.9-384.8]. **The error CQE carries no byte count:** `opcode`=255 and `byte_len`=0 in 6,947/6,947 error CQEs (CQ). | 30; CQ 6,947 CQEs | as above; `CQ/results/raw_*.csv` | measured |
| F1 partial_write | side | RDMA-READ readback: landed == sent in 130/130 trials across six runs on 2026-09-23 (qp_only, full_rebuild, none); 0 matching bytes outside the prefix. | 130 | `H/results/partial_write_20260923_*.csv` (recount) | measured |
| F2 rem_access | L0 | Requester QP ERR, 100/100 (CQ). Requester `roce_adp_retrans` Δ0, 30/30 (H). Requester `req_remote_access_errors` +1 and adp/ack_to/pse 0, 20/20, but only for the dereg and dying-peer triggers (FT sF), not for the out-of-bounds write. Responder QP state on the current testbed: **not measured**. OLD (CX-5 responder): responder QP → ERR 10/10. | CQ 100; H 30; FT 20; OLD 10 | `CQ/results/trials_rem_access_*.csv`; `FT/results/20260925/sF_sunny/trials.csv` `ctr_trig_to_err`; `OLD/05_counter_mapping/results/raw/qp_state_verify.csv` | measured |
| F2 rem_access | L1 | 10/0x88, 30/30. det is bimodal: 25/30 at 0.319-0.375 ms, 5/30 at 1.673-2.952 ms (median 323.5 µs). CQ N=1: 2.94-2.96 ms in 10/10, i.e. only the slow mode. The root CQE comes first, then 5/0xf9 per trailing WQE. With the bad WQE last, the last CQE is the root (60/60 together with rem_inv_req). | H 30; CQ 130 | H csv; `CQ/results/raw_rem_access_{main,supplast}.csv` | measured |
| F2 rem_access | L2 | peer_alive=1, auto=1. Since 2026-09-25 a liveness PROBE is sent. Answered: sub_cause `-` (3+3+5 trials). Ignored by the test switch: sub_cause `no_answer`, peer_alive -1, auto 0 (3/3). Recovery median 0.77 ms, verify 30/30. | 30 + 14 | `H/results/validation_20260925_*/` | measured |
| F2 rem_access (invalid rkey) | L1, L3 | Middleware demo: 0x88 → "QP recovery + MR refresh", resend ok, exit 0. | N=1, 2026-09-23 | `OLD/08_middleware/results/qa_20260923/demo_4scenarios.log` | measured (N=1) |
| F2 live dereg_mr (FT) | L1 | 10/0x88, 90/90 (80 dereg + 10 reset-then-dereg). Silence of 1.0-2.2 ms before the NAK. | 90, 2026-09-25 | `FT/results/20260925/*/trials.csv` → `summarize.py`, `qa_crosscheck.py` | measured |
| F2 live dereg_mr (FT) | L4 | Responder dmesg shows `QP <n> error: local protection error (0x3a 0x0 0x93)`, one line per dereg (91 lines). | | `FT/README.md` §C; no dmesg file in the repo | measured\* |
| rem_inv_req | L0 | Requester QP ERR, 100/100; adp Δ0. OLD: responder QP → ERR 10/10. | CQ 100; H 30 | as for rem_access | measured |
| rem_inv_req | L1 | 9/0x8a, 30/30. Bimodal: 25/30 at 0.298-0.356 ms, 5/30 at 1.602-1.714 ms (median 304.0 µs). In CQ the latency depends on the cell in a repeatable way: ~1.6 ms for N≤4, ~0.36 ms for N≥16. | H 30; CQ 130 | H csv; CQ raw | measured |
| rem_inv_req | L2 | Same as rem_access (PROBE; `no_answer` 3/3 under the test switch). Recovery median 0.77 ms. | 30 + 11 | as above | measured |
| rnr | L0 | Requester QP ERR, 70/70 (CQ); adp Δ0. **OLD: responder QP stays RTS 10/10.** | | CQ trials; `OLD/.../qp_state_verify.csv` | measured |
| rnr | L1 | 13/0x87, 30/30, det median 12.786 ms [12.106-12.801]. Flushes follow as above. | H 30; CQ 70 | H csv; CQ raw | measured |
| rnr | L2, L3 | auto=1; recovery median 0.78 ms. Middleware demo: recovered, N=1. | 30; 1 | H csv; demo log | measured |
| F3 server_qp_err | L0 | Requester QP ERR: CQ 40/40, AT 317/317 (`qp_state_after`=6). Requester `roce_adp_retrans` Δ4-7 (H). There are R-1 = 6 regular `local_ack_timeout_err` spaced I = 2 × nominal(max(T,16)) (205/205 floor-on trials). Responder port counters Δ: rcv 26-28, xmit 14 (N=5). In PROBED, `peer_rx` was 19-24. | H 30; AT; verify N=5 | `H/results/retry_server_qp_err_20260923_123945.csv`; `AT/results/20260925/*/trials.csv`; `H/results/verify_0x81_20260923.csv` | measured |
| F3 server_qp_err | L1 | 12/0x81, 30/30, det median 3.7491 s [3.7490-3.7543]. Across experiments the time depends on history: 3.49-3.75 s (H, 2026-09-25), 3.52-3.61 s (CQ), 3.50-3.76 s (AT, fresh processes). Back-to-back steady state 3661.8 ms (AT A). Flushes follow. | | H csv; AT `results/20260925/{A,fresh}` → `AT/analyze.py`, `fresh_check.py` | measured |
| F3 server_qp_err | L2 | sub_cause=`server_qp_err` 30/30 (PROBE answered). **But `peer_alive`=0 and `auto_recoverable`=0 in 30/30 rows**: classify's 0x81 default is never overridden on an answered PROBE (`probe_client.c:381-382`). | 30 | H csv (recount) | measured |
| F3 server_qp_err | L3 | Middleware demo: "probe peer then recover", resend ok (N=1). Idle-timeout bug (T=18, detect 12-14 s): before the fix a live peer was declared dead (exit 1); after the fix it recovered (exit 0); N=1 each. | 2026-09-23 | `OLD/08_middleware/results/qa_20260923/*.log` | measured (N=1) |
| F3 server_qp_err | L4 | Liveness PROBE answered within the 1 s SO_RCVTIMEO. The reply time is not recorded. | 30 | `probe_client.c:375-395` | measured (no timing) |
| F3 server_qp_err | L5 | Recovered and verified 30/30; exit 0. | | H csv | measured |
| F3 live destroy_qp (FT) | L1 | 12/0x81, 20/20 (verbs 10, DEVX 10), 3.64 s. | 20 | FT trials.csv | measured |
| F4 retry_proc_kill (graceful) | L0 | Requester adp Δ5-8, which overlaps F3. Responder port counters: rcv 23-30, xmit 12-16, also overlapping F3. | 30; N=5 | H csv; `verify_0x81_20260923.csv` | measured |
| F4 retry_proc_kill (graceful) | L1 | 12/0x81, 30/30, det median 3.7316 s [3.6021-3.7455]. | 30 | H csv | measured |
| F4 retry_proc_kill (graceful) | L2 | sub_cause=`proc_kill` 30/30 (control-socket EOF); peer_alive 0, auto 0. Before 2026-09-25 a PROBE timeout also counted as proc_kill. | 30 + 9 | H csv; validation dirs | measured |
| F4 retry_proc_kill (graceful) | L4 | The server closes its socket on GO, 300 ms before the post, so the EOF must come at least 3.9 s before the CQE. The FIN is not timestamped. | | source | inferred |
| F4 retry_proc_kill (graceful) | L5 | No recovery; one client per trial, exit 0. | 30 | `H/run.sh` | inferred |
| F4 SIGKILL (FT) | L1 | 0x81 in 159/270, 3.51-3.76 s after the last ACK; 0x88 in 111/270, 0.38-3.51 ms after the last ACK. Which one depends on which object is destroyed first: MR before QP gives 0x88 0/80 (0/83 with smoke trials); MR after QP gives 111/192 (111/161 without sunny DEVX); a DEVX QP on sunny's OFED 25.10 gives 0x81 10/10. Every error trial has n_flush=7 (≤8 outstanding) and n_other_err=0. | 270 + smoke, 2026-09-25 | `FT/results/20260925/*/trials.csv` → `qa_crosscheck.py`, `make_table.py` (recount) | measured |
| F4 SIGKILL (FT) | L0 | For dead-peer 0x88, the requester counters equal those of a live dereg 0x88: rae=1, adp=0, ack_to=0 (10 + 10). For 0x81: ack_to=6, adp 4-7 (20). | 40 (sF) | `FT/results/20260925/sF_sunny/trials.csv` | measured |
| F4 SIGKILL (FT) | L4 | The OOB socket FIN arrived before the first error CQE in 270/270 trials, with a margin of at least 0.431 ms. Responder dmesg: at most 2 lines for 40 GPU-peermem 0x88 kills on sunny, 0 for 35 on rain, so it is no death signal. | 270 | trials.csv `oob_close_ms` vs `err_ms` (recount); dmesg from `FT/README.md` | measured / measured\* |
| F4 SIGKILL (FT) | L5 | Victim reaped 2.2-101.5 ms after the SIGKILL (pidfd), by variant. | 270 | trials.csv `reap_ms` | measured |
| silent GPU free (FT) | L0-L5 | `cudaFree` or `cudaDeviceReset` with a live MR gives **no error at any layer** (30/30). About 74,000 64 KiB WRITEs per trial completed into the freed memory over 1.5 s. | 30 | FT trials.csv (`no_error_writes_ok`) | measured |
| link down | all | Not measured. Dry run: no_error_cqe 5/5. OLD contradicts itself: `docs/experiments/01` reports 3701 ± 10.3 ms (N=100; raw not in the repo, and `OLD/01_cpu_baseline/experiment1/results/` is empty), while OLD counter_mapping reports "재현 실패" (3/3 SUCCESS; `RETRY_EXC_LINK_DOWN.csv` status 0). | | | — |
| LOC_PROT 0x53 | L1, L3 | Middleware demo: 0x53, classified as an application bug, no recovery, exit 0 (N=1, current). OLD: 0x53/0x52/0x33, 100 each. | | demo log; `OLD/05_counter_mapping/results/raw/LOC_PROT_*.csv` | measured |

Timing model for RETRY_EXC detection (AT, measured, 2026-09-25):
- **Floor on:** detect = t_L1 + (R-2)·I, with I = 2 × 4.096 µs × 2^max(T,16).
- **Floor off** (`min_ack_timeout_limit_disabled=1`): detect = t1 + (R+1) × nominal.
- **Medians:**
  - T=14, R=7, floor on, back-to-back: 3661.8 ms.
  - T=14, R=7, floor on, fresh process: 3.50-3.76 s.
  - T=20, R=7, floor on: 59.77 s back-to-back; 58.46-58.79 s fresh; 57.69-58.24 s fresh with traffic first.
  - Floor off, R=7: T=8 9.49 ms; T=14 574.9 ms; T=20 37.9 s.

## 2. Which fault classes each layer can tell apart

The seven canonical harness scenarios:

| label | fault |
|---|---|
| A | local_qp_err |
| B | partial_write |
| C | rem_inv_req |
| D | rem_access |
| E | rnr |
| F | server_qp_err |
| G | proc_kill (graceful) |

| layer / signal | partition | classes |
|---|---|---|
| L0 requester QP state | {A..G} all ERR (A, C-G measured in CQ; B inferred from A). Fault vs no fault only. `ep_qp_state` returns ERR when the query itself fails (`H/common/probe.c:287`). | 1 |
| L0 requester `roce_adp_retrans` (the only counter the harness reads) | {A,B,C,D,E} Δ0 vs {F,G} Δ4-8 | 2 |
| L0 requester sysfs counter set (OLD only; not re-measured on fw 20.43) | {A,B} {C} {D} {E} {F,G} | 5 |
| L0 responder port counters | F and G overlap | — |
| L1 status | {A,B} {C} {D} {E} {F,G} | **5** |
| L1 status + vendor_err | Same: A and B are both 0xf5, F and G both 0x81 | **5** |
| L1 last CQE of a batch with ≥1 WQE behind the failing one (collapsed slot) | All become 5/0xf9 (290/290). A with nothing outstanding gives no CQE, so it looks like F0. | 1 |
| L1 det time | A 223-247 µs and B 329-385 µs separate only because of message size. C and D overlap (bimodal). E 12.1-12.8 ms. F 3.749-3.754 s and G 3.602-3.746 s overlap. | not a cause signal |
| L2 harness `sub_cause` (liveness) | {A,B} {C} {D} {E} {F} {G} | **6** |
| L2 harness `peer_alive` / `auto_recoverable` columns | {A-E}=1/1, {F,G}=0/0. F is mislabelled and merged with G. | 2 |
| L3 middleware (CPU API, N=1) | Outcome {recovered: rnr, rem_access, retry} vs {app bug: loc_prot}. After a recovery the app sees success, so the class survives only in the log. | 2 outcomes |
| L4 | No async events are recorded anywhere in the CPU studies. Liveness via PROBE or socket EOF splits F from G. | — |

Summary for the seven scenarios: **5 classes on status alone, 5 on status + vendor_err, 6 with liveness.**
A and B can never be split, because they are the same mechanism. If the real SIGKILL (FT) is
added as G', at L1 it lands in F's class (0x81) or in D's class (0x88), depending on teardown
order. Liveness (FIN 270/270) moves it back to a PEER_DEAD class, so the count with liveness stays
6, but only if the 0x88 class is also gated on liveness, as the harness has done since 2026-09-25.

OLD 10-scenario study (`OLD/05_counter_mapping/results/counter_mapping_findings.md` §8):
- "6/10 → 8/10 → 9/10" counts **equivalence classes**, not singletons. On status alone only 3 of the 10 are uniquely identified (WR_FLUSH, REM_INV, RNR).
- The ninth split is the ethtool non-RDMA TCP packet count (FIN vs RST, N=3), i.e. a liveness signal.
- Recount of the raw markers: each of the 10 scenarios had one fingerprint in 100/100 trials, or 30/30 for the two 0x81 scenarios.

## 3. Spot-checks (independent recount vs README text)

| # | headline | recount | README | match |
|---|---|---|---|---|
| 1 | Harness det medians (stamp 123945) | 224.9 µs, 338.3 µs, 304.0 µs, 323.5 µs, 12.786 ms, 3.749 s, 3.732 s | `H/README.md` table: 225 µs, 338 µs, 304 µs, 323 µs, 12.79 ms, 3.749 s, 3.732 s | yes |
| 2 | Bimodality | rem_access 25 at 0.319-0.375 ms + 5 at 1.673-2.952 ms; rem_inv_req 25 at 0.298-0.356 ms + 5 at 1.602-1.714 ms | "25 of 30 take 0.30-0.37 ms and 5 of 30 take 1.6-3.0 ms" | yes |
| 3 | partial_write landed == sent | 130/130 (runs of 5, 30, 5, 30, 30, 30), 0 non-prefix | "130/130 in six runs" | yes |
| 4 | 0x81 vs 0x88 for dead peers (FT) | 417 trials (+7 superseded). Kills at N=10: 270 = 159 × 0x81 + 111 × 0x88. MR-before-QP 0/80 (+3 smoke = 0/83). MR-after-QP 111/192. FIN before CQE 270/270, minimum margin 0.431 ms. | `FT/README.md`: 0/83, 111/192, 270/270, 0.43 ms | yes |
| 5 | AT out-of-sample 52/55 | 52/55 within 1.5 ms. Misses: T10R7 trial 2 −2.57 ms; T17R3 trial 2 −7.57 ms; T17R5 trial 4 −7.58 ms. 66/66 0x81 with QP ERR. | `AT/README.md` D1b | yes |
| 6 | CQ headline | 470 trials, 9,004 CQEs. last = root 120/120. last = 5/0xf9 at N−1 290/290. Root → first flush median 59.46 µs [58.19-223.1]. Spacing median 9.349 µs, p1-p99 9.239-9.775 µs, n=6,247. | `CQ/README.md` | yes |
| 7 | 0x81 counter rerun | rcv 26-28 vs 23-30; xmit 14 vs 12-16 | `H/VERIFICATION_0x81.md` re-run table | yes |
| 8 | Floor off, T=8 R=7 | median 9.49 ms [9.33-9.74] (`AT/results/20260925/qa_check.out`) | 9.49 ms | yes |

No headline number failed to reproduce. The problems are in interpretation (§4).

## 4. Results invalidated or corrected, and claims stronger than the data

**Invalidated or corrected (each is acknowledged somewhere in the repo):**
1. `H/results/*_20260915_171332.csv`: legacy schema, PMTU 1024. partial_write `bytes_landed` was sq_psn × PMTU checked against itself; it was replaced by RDMA-READ readback.
2. `*_20260916_145104.csv`: the RETRY sub_cause was derived from `peer_rx` (36-52 vs −1). The claim "peer_rx separates the causes" was withdrawn (`H/VERIFICATION_0x81.md`); liveness is now the discriminator. The first verification's xmit 5 vs 0 was an artifact of the verify READ.
3. Run `113252`: a QP-only recovery tail of 12.8-17.2 ms appeared under load (rain load average ~7.8). It is not used.
4. The `no_answer` path could never fire before 2026-09-25: `perror` changed errno to EINVAL. Before that fix, a PROBE timeout was also counted as proc_kill.
5. FT: the session `superseded_smoke1_underflow` hit a requester underflow and is not used. The fd-order / GPU-free hypothesis was refuted.
6. AT: the claim that GIN's 57-59 s was "within range" of the model was retracted (the model gives 59.77 s). The window lock check failed open and was fixed. Trial 1 of every cell is off the model; that effect is characterised but its cause is unknown.
7. OLD:
   - Process kill 5.13 s was an artifact of signal plus `sleep(1)`.
   - A/B recovery 42.7 ms was a delayed-ACK artifact.
   - Invalid lkey ~1.5 ms was corrected to 319 µs.
   - N=10 NAK latencies were warm-up biased.
   - Server-QP-ERR baseline: only N=1 was saved.

**Claims stronger than the data:**
1. `H/README.md` ("Each (status, vendor_err) pair is unique except ... 0x81") and `H/QA_20260923.md` ("fingerprints unique") are wrong: local_qp_err and partial_write share 5/0xf5.
2. `H/README.md` calls server_qp_err "auto-recoverable", but the CSV has `auto_recoverable=0` and `peer_alive=0` in 30/30 server_qp_err rows (and in every 0x81 row in the validation runs). The README also says "an answered PROBE leaves the CQE classification unchanged", which contradicts the first statement. This is an L2 labelling bug.
3. `H/README.md` still quotes the first verification's port counters (rcv 40-52, xmit 0). The PMTU-4096 rerun gave rcv 23-30, xmit 12-16, and the canonical PROBED `peer_rx` is 19-24. The conclusion stands; the numbers are stale.
4. `H/README.md` gives RETRY detection as "3.749 s ± 0.35 ms", the "~3.75 s firmware floor". The narrow CI hides the history dependence (3.49-3.77 s across H, CQ and AT). The bimodality of rem_* is attributed (OLD) to the scheduler, but in CQ the slow mode is repeatable per cell (N=1 rem_access 2.94-2.96 ms in 10/10). It was not investigated.
5. Root `README.md`, "10가지 장애를 오류 코드만으로 6개, vendor_err 8개, 생존 여부 9개": this is OLD-cluster data and is not reproduced on the current testbed (the harness has no LOC_PROT ×3 and no invalid-rkey runs; 0x53 and invalid rkey are N=1 each). It also omits the dead-peer 0x88 path from FT, so 0x88 is not purely an access class.
6. Root `README.md`, "2.8 ms에 복구 (드라이버 재적재 7.9 s), 다른 연결에는 영향이 없다": these are OLD numbers (RETRY_EXC, N=10). The current testbed gives QP-only 0.77-0.81 ms median and QP-only full_rebuild 1.79-1.81 ms. Driver reload and multi-QP isolation were never run on the current testbed.
7. Root `README.md`, "NCCL 기본값(timeout 20)에서는 59.8 s이고, floor를 풀면 9.5 ms":
   - 59.8 s is the CPU back-to-back figure; fresh processes give 58.46-58.79 s, and the NCCL GIN measurement was 57.1-58.4 s.
   - 9.5 ms is T=8 with the floor off; at T=20 with the floor off it is 37.9 s.
   - Turning the floor off is a NIC-function-wide register change.
8. "proc_kill" in the harness, CQ and RESULTS means a graceful exit in one teardown order (QP first) plus 300 ms of silence. A real SIGKILL gives 0x88 in 111/270. Root README, "커널이 verbs 객체를 지우는 순서": order is necessary but not sufficient (it is a race; host 8 MiB qpfirst gives 0x88 in 1/10 on sunny and 7/10 on rain), and the DEVX-first rule is specific to OFED 25.10.
9. OLD "counter signatures 100 % deterministic (roce_adp_retrans +8)" does not carry over: on the current testbed adp is 4-8 per trial.
10. Minor: `OLD/08_middleware/results/qa_20260923/README.md` says GID index 4 was forced, but the log prints "Using GID index 2" (unexplained).

## 5. Gaps that matter for a cross-layer table

- **F0 as its own scenario:** never run. There is no baseline row for L0 QP state and counters, L4 events or L5 teardown time.
- **L0:**
  - The harness never queries the QP state after an error; only CQ and AT do (requester side).
  - The responder QP state per fault was never measured on the current testbed (OLD CX-5: ERR for 0x8a/0x88, RTS for RNR).
  - There was no per-fault sweep of the hw_counters on fw 20.43.4100 (only `roce_adp_retrans` in H, 6 counters in FT sF, timeout counters in AT).
  - Per-QP q counters (`rdma statistic`) were never used.
- **L1:**
  - The harness keeps only the first error CQE, and recovery's RESET discards the rest. The full sequence exists only in CQ (N≤64, one QP).
  - Raw mlx5 syndrome fields beyond `vendor_err` were never read on CPU.
  - The F4 SIGKILL CQE sequence was recorded only as n_flush=7.
- **L3:** the only CPU API-level data is the middleware demo, N=1 per scenario. There are no API-level runs for local_qp_err, rem_inv_req, partial_write or SIGKILL, and no N≥30.
- **L4:**
  - `ibv_get_async_event` is not used in any CPU experiment, on either side. The expected `IBV_EVENT_QP_ACCESS_ERR` / `QP_REQ_ERR` on the responder is source-only (NCCL doc).
  - The requester's dmesg was never checked.
  - The responder dmesg counts have no raw file in the repo.
  - PROBE reply times and FIN times are not timestamped in H (only in FT).
  - `no_answer` was tested only with a test switch (3/3), never with a really hung peer.
- **L5:** requester teardown (destroying a QP in ERR, closing the context) was never timed. The only timings are FT `ACT` on a live victim (`destroy_qp` 0.55-0.60 ms) and FT reap times.
- **Faults never measured on the current testbed:**
  - real link down (dry run only; not allowed);
  - address or GID faults (none in the CPU harness);
  - LOC_PROT 0x52/0x33;
  - invalid rkey at N>1;
  - REM_OP_ERR;
  - dead-peer 0x8a (marked "inferred, not measured" in FT);
  - SIGKILL inside the harness with its recovery path;
  - more than one fault at a time;
  - multi-QP isolation;
  - RNR with rnr_retry=7 (NCCL's default: expected to hang with no CQE).
- **Signals that never reach L1:** a GPU free under a live MR (30/30 silent), and how many bytes a partial write landed (only `sq_psn` via QUERY_QP or a readback shows it). A local ERR with nothing outstanding produces no CQE (60/60). A cross-layer table needs a row for "fault with no L1 signal".
