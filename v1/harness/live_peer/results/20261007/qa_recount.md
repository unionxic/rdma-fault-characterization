# live_peer: independent recount of the main run (2026-10-07)

Recount of the 125 scored trials (part A 95, part B 30) from raw files only. Written without reading or running
`score.py`, `SCORE.md`, `score.json` or `trials_scored.csv`. Nothing was run on the cluster and no existing file was
changed. Script: [../../qa/recount.py](../../qa/recount.py), run from `harness/live_peer` as
`python3 qa/recount.py results/20261007` (read-only, prints every check below).

Disclosure: before the recount, `git diff prereg/live-peer-v1 -- EXPERIMENT.md` (run to check the fixed sections)
printed the section 15 text, and the section 12 log row and the last commit message state "33 of 34 hold, B2a
fails". The recount below is mechanical (frozen rule text evaluated on raw fields), so this did not change any
count, but the recount was not blind to the headline.

## Method

- **Frozen inputs.** `predictions.csv` sha256 `877aa1d4…48a27bd` equals `PREREG.txt`; `predictions.csv` and
  `PREREG.txt` have no diff against tag `prereg/live-peer-v1` (commit `4a9fcf71`). EXPERIMENT.md sections 2, 3, 7, 8
  are byte-identical to the tag (diff hunks touch only the header, sections 5, 11, 12–15). 42 rows: 34 measured
  (24 N, 7 R, 3 C), 8 source rows not scored.
- **Fields (section 3.0).** Part A: the one CSV row per `A/runs/<tag>/`, the server log, `A/evrec/<tag>.evrec.*`.
  Part B: first `fault ev=` and `rec ev=` records of the r0 kv, last `iters_ok=` record of each kv, `r0rc` from meta,
  `r1_stall_end_r0clock` = r1 `stall` `end_mono_ms` minus r0 `clock_offset_ms`, `rxrec` records after the `stall`
  record. Counters: end minus start of `hw_counters/<name>` in each evrec; sample fields from the `smp` lines against
  the evrec start and end snapshots.
- **Rules (section 3.0).** Each quantifier body is taken verbatim from `predictions.csv` and evaluated per trial as a
  Python expression. ALL = true in every trial; MOST = true in at least ceil(0.9 n) and false in 0 trials whose fields
  are all recorded; NONE = true in 0. Multi-cell rows per cell, all must hold. K rows count only trials with an evrec
  end record on the node(s) the row reads; K2 only `status==12`; O rows only trials with `truth_alive` 0 or 1 (part A)
  or an r1 kv (part B).
- **Interpretation choices.** `?`, `-` and `-1` are recorded values, not empty fields (A8 predicts
  `srv_qp_state=='?'` literally). A field that is absent (for example `rec_outcome` in B3, which has no `rec ev=`
  record) counts as unobservable; this occurred only in O3 for B3 under NONE, where it cannot change the result.

## 1. Trial set and exclusions

- [measured] 16 cells, counts as planned in section 7: A0 5, A1 5, A2 5, A3–A9 10 each, A10 5, A11 5, B0 5, B1 10,
  B2 10, B3 5. Tags `t1..tn` contiguous in every cell, no duplicates, no extra trials; `trials.log` has 125 entries,
  all `rc=0`, one per raw trial. Each part A run directory has exactly one CSV with one row and one server log.
- [measured] Fresh process pair per trial: 95 distinct `probe_server` PIDs, 30 distinct rank 0 PIDs.
- [measured] Section 8 exclusion conditions: none met. `fault_applied` with the cell's fault 70/70 in A1, A3–A9,
  A11; `[server] proc_sigkill` line 5/5 in A2; `stall_end` 20/20 in A7, A8 (stall 8000 ms configured, measured
  8000.05–8000.13 ms over the 20 trials); `fault ev=` 25/25 in B0–B2 (all RETRY_EXC, 12/0x81); `stall` record 25/25
  in B1–B3 with the planned setting (B1 1000 ms on request, B2 6000 ms on request, B3 6000 ms at iteration 60), none
  in B0. All 250 evrec records have an end record; ground truth determined in 125/125. So no trial should have been
  counted apart or re-run.
- [measured] Configuration: `LIVE_STOP_MS=8000 LIVE_TRANSIENT_MS=1250` and recovery `qp_only` in 95/95 server logs and
  CSVs; A6 re-arm 1250.6–1250.7 ms after `fault_applied` (n=10). Part B meta: inject 600, wait timeout, 120
  iterations, bundle `gin_recovery_gpudb_stall` in 30/30.
- Smoke runs exist in `results/20261007_smoke/` (A 12, B 4) and were not read for scoring.

## 2. Per-prediction recount

Hits are trials where the row's condition holds, over the scored trials. Ranges are min–max over the trials named
in the "range over" column. All values `[measured]` from the raw files.

| id | prediction | cell(s) | n | hits | verdict | observed (range over) |
|---|---|---|--:|---|---|---|
| A0 | no fault: success within 10 ms, no liveness verdict | A0 | 5 | 5/5 all parts | holds | first CQE 3.1–12.9 µs (A0, n=5) |
| A1 | responder QP ERR: 12/0x81 at 3.40–3.90 s, "alive, QP error", state ERR | A1 | 5 | 5/5 all parts | holds | detect 3551.7–3712.1 ms (A1, n=5) |
| A2 | SIGKILL: 12/0x81, death verdict, truly dead | A2 | 5 | 5/5 all parts | holds | 12/0x81 5/5, `proc_kill` 5/5, connection refused 5/5; detect 3567.0–3705.1 ms |
| A3a | QP RESET: 12/0x81, 3.40–3.90 s | A3 | 10 | 10/10, 10/10 | holds | detect 3494.7–3752.0 ms (A3, n=10) |
| A3b | QP RESET: "alive, QP error", never death or no answer, state RESET, no async event | A3 | 10 | 10/10, 0 true for NONE, 10/10, 10/10 | holds | |
| A4a | QP INIT: 12/0x81, 3.40–3.90 s | A4 | 10 | 10/10, 10/10 | holds | detect 3500.4–3642.8 ms (A4, n=10) |
| A4b | QP INIT: as A3b with state INIT | A4 | 10 | 10/10, 0, 10/10, 10/10 | holds | |
| A5 | QP left in RTR: success within 10 ms, state RTR | A5 | 10 | 10/10 all parts | holds | first CQE 3.5–4.5 µs (A5, n=10); unpredicted: responder async event `IBV_EVENT_COMM_EST` 10/10 |
| A6 | 1250 ms not ready, then RTS: success at 1.25–1.80 s, state RTS | A6 | 10 | 10/10 all parts | holds | first CQE 1352.5–1513.7 ms (A6, n=10) |
| A7a | QP ERR + 8 s stop: 12/0x81, 3.40–3.90 s | A7 | 10 | 10/10, 10/10 | holds | detect 3517.1–3755.9 ms (A7, n=10) |
| A7b | QP ERR + 8 s stop: "no answer", never death, recovered and verified, alive | A7 | 10 | 10/10, 0, 10/10, 10/10 | holds | resync 1198–1466 ms, 2 late lines dropped 10/10 |
| A8 | healthy QP + 8 s stop: success within 10 ms, state query unanswered, no verdict, recovered | A8 | 10 | 10/10 all parts | holds | first CQE 3.7–8.2 µs; resync 5957–5985 ms (A8, n=10) |
| A9a | QP ERR + control connection closed: 12/0x81, 3.40–3.90 s | A9 | 10 | 10/10, 10/10 | holds | detect 3519.3–3718.0 ms (A9, n=10) |
| A9b | death verdict while the same process answers `ALIVE?` | A9 | 10 | 10/10, 10/10 | holds | answering PID = server PID 10/10 (server and client logs) |
| A10 | no receive buffer: 13/0x87 at 11.5–13.5 ms, no probe | A10 | 5 | 5/5 all parts | holds | detect 12.43–12.80 ms (A10, n=5) |
| A11 | QP recreated in INIT: 12/0x81, 3.40–3.90 s, "alive, QP error", INIT | A11 | 5 | 5/5 all parts | holds | detect 3503.4–3614.3 ms (A11, n=5) |
| B0 | GIN peer QP error: recovered, ACK within 500 ms of Prepare | B0 | 5 | 5/5, 5/5 | holds | ACK minus Prepare 4.2–4.3 ms (B0, n=5) |
| B1 | 1 s stop: recovered, never declined, ACK 1000–1500 ms after Prepare | B1 | 10 | 10/10, 0, 10/10 | holds | ACK minus Prepare 1004.5–1005.0 ms (B1, n=10) |
| **B2a** | 6 s stop: declined for handshake timeout 3000–3500 ms after the fault query, never recovered, rank 0 exit 9 | B2 | 10 | 10/10, 0, **8/10**, 10/10 | **fails** | decline minus fault query 2999.2–3002.2 ms (B2, n=10); misses `b2_t1` 2999.33 ms, `b2_t5` 2999.24 ms |
| B2b | rank 1 resumes after the decline and handles the request | B2 | 10 | 10/10, 10/10 | holds | rank 1 stop end minus decline 2999.2–3002.2 ms; one `rxrec` after the stop 10/10 |
| B3 | no fault + 6 s stop: no fault or recovery record, 120/120 exact, exit 0 | B3 | 5 | 5/5 all parts | holds | |
| O1 | death misjudgment only where the control connection is closed | A9; 10 other cells (A2 left out) | 10; 80 | 10/10; 0/80 | holds | per cell 0 in A0, A1, A3–A8, A10, A11 |
| O2 | unrecoverable misjudgment only in QP ERR + stop and control-close cells | A7, A9; 9 other cells | 10, 10; 70 | 10/10, 10/10; 0/70 | holds | |
| O3 | GIN decline misjudgment only in the 6 s stop cell | B2; B0, B1, B3 | 10; 20 | 10/10; 0/20 declined | holds | B3 has no recovery record (5 unobservable for `rec_outcome`, none can be true) |
| O4 | missed stop: no error and no verdict | A8; B3 | 10; 5 | 10/10; 5/5 | holds | |
| K1 | real congestion counters +0 | 16 cells, both nodes | 125 trials, 250 records | 250/250 | holds | `np_cnp_sent`, `np_ecn_marked_roce_packets`, `rp_cnp_ignored` all 0 |
| K2 | retry exhausted: `rp_cnp_handled` = `roce_slow_restart_cnps` = adaptive + regular retransmission timeouts - 1, regular 6 | A1, A2, A3, A4, A7, A9, A11 (status 12) | 55 | 55/55, 55/55, 55/55 | holds | rain `rp_cnp_handled` 10–13, `roce_adp_retrans` 5–8, `local_ack_timeout_err` 6 (55 trials pooled) |
| K3a | 1250 ms not ready: no error CQE, yet `rp_cnp_handled` rises and equals `roce_slow_restart_cnps` | A6 | 10 | 10/10 | holds | rain `rp_cnp_handled` 8–10, `req_cqe_error` 0 (A6, n=10) |
| K3b | one per retransmission: = adaptive + regular | A6 | 10 | 10/10 | holds | `roce_adp_retrans` 6–8, `local_ack_timeout_err` 2; tuples (8,6,2), (9,7,2), (10,8,2) |
| K3c | 2 regular timeouts (1–3 allowed) | A6 | 10 | 10/10, 10/10 | holds | 2 in 10/10 |
| K4 | no ACK timeout: three counters +0 on rain | A0, A5, A8, A10, B3 | 35 | 35/35 | holds | A10 shows `rnr_nak_retry_err` +7, `req_cqe_error` +1 (RNR, not timeouts) |
| K5 | part A, sunny `rp_cnp_handled` +0 | 12 A cells | 95 | 95/95 | holds | |
| K6 | GIN peer QP error: rain `rp_cnp_handled` >= 8, q counters +0, sunny +0 | B0, B1, B2 | 25 | 25/25 | holds | rain `rp_cnp_handled` 9–12, `roce_slow_restart_cnps` 0, `local_ack_timeout_err` 0, `roce_adp_retrans` 0 (25 pooled) |
| K7 | 50 ms samples: counters differ by at most 1; increase only between the post and first CQE + 100 ms | A1, A3, A6 | 25 | 25/25 ×3 | holds | max sample difference 0 (25/25); first rise 6.7–69.1 ms after the post (25 pooled) |

Totals: 33 hold, 1 fails (B2a), 0 without data. Same as the verdict count stated in section 12.

**Misjudgment summary** (section 6 definitions; truth from `truth_alive`, cross-checked against the server log):
death misjudgment 10/10 in A9, 0/80 in the other ten live cells; unrecoverable misjudgment 10/10 in A7 and 10/10 in A9,
0/70 in the other nine live cells; GIN decline of a live peer 10/10 in B2, 0/20 in B0, B1, B3; missed stop 10/10 in
A8, 5/5 in B3. [measured] Independent ground-truth check: in all 90 trials with `truth_alive=1` the server log shows
the server handling a command after the fault (`QUERIED`, `RESYNCED`, `bye` or the `ALIVE` answer); in the 5 A2
trials the server log ends at the SIGKILL line.

**Counter details.** [measured] In K7, the sample where `rp_cnp_handled` first reached its end value came 503.8–533.2 ms
before the first CQE in A1 (n=5) and 495.9–512.1 ms before it in A3 (n=10), but 2.0–49.1 ms after it in A6 (n=10).
[inference] This matches one regular timeout (about 537 ms) without a retransmission at retry exhaustion, the
"- 1" in K2, and the absence of that last timeout in the transient cell. Sunny: apart from `rx_write_requests` and
`rx_read_requests`, the only sunny hw counter that moved in any of the 125 trials was `out_of_buffer` +7 in A10 (5/5).

## 3. The 6 s GIN stop timing (B2a)

- [measured] The scored time is `rec_t_decl - fault_t_query`, both rank 0 `monoMs()` values from the r0 kv (`rec ev=`
  and `fault ev=` records). Values are bimodal: 2999.24 and 2999.33 ms (`b2_t5`, `b2_t1`) and 3002.14–3002.23 ms in
  the other eight. Decline minus kernel return: 2999.3–3002.3 ms. Reason `handshake_timeout` 10/10, rank 0 exit 9
  10/10 (rank 1 also exited 9 in 10/10).
- [source] `gin_rec.cu:482-489`: the 3000 ms deadline is armed after `ncclGinRecoverPrepare` and the request send,
  not at the fault query. The wait truncates the remaining time to integer ms twice: `:492` in the handshake loop and
  `:172` inside `recv()` before `poll`. `t_decl` is logged after `ncclGinRecoverAbort` (`:500`, then `:447-448`).
- [measured] Prepare took 1.03–1.18 ms after the fault query in B0 and B1 (n=15; not logged on a decline). Rank 1
  entered its stop 1.21–1.46 ms after the fault query (B2, n=10, rank 0 clock).
- [inference] So the two early trials ended about 1.7–1.9 ms before the armed 3000 ms deadline. That needs both
  truncations near their maximum (each below 1 ms). The miss is real under the frozen rule (`ALL`, 8/10).
- [unconfirmed] Why the eight others land about 1 ms after the deadline and the values form two clusters about 2.9 ms
  apart. Truncation alone gives a spread, not two clusters.

## 4. Safety records

- [measured] `A/runner.log`, `B/runner.log`: no `SIGCONT to stopped`, no `STOP` lines, so the runner's check after
  every trial found no stopped or leftover process of ours. No `STOP` line in either `trials.log`. B meta `left=0` in
  30/30. `.pstate` files: state `T` seen 20/20, PID equal to the trial's `probe_server` PID 20/20.
- [measured] dmesg: each part logs the start count `rain=2 sunny=unreadable`; no STOP line means the rain count never
  rose after a trial. [unconfirmed] The per-trial and end counts are not written to any file, so "still 2 after the
  block" (section 12) is supported only indirectly. Sunny was not checked (allowed by section 8 when unreadable).
- [measured] Port state `active` at start and end in all 250 evrec records (both nodes). No `verify_ok=0`; rank 1
  `data_check` is `ok` in 30/30. No stop criterion fired.

## 5. Section 15 and other documents against the raw data

Section 15 was read after the recount. Its counts and ranges reproduce, including 3.495–3.756 s pooled over the seven
12/0x81 cells (55 trials), 0/80 and 0/70, 55/55 for the K2 identities, the 35 trials with +0, and 25/25 for the
samples. The following statements are not supported or are overstated:

1. **B2a explanation.** Section 15 says integer truncation can make the wait "close to 1 ms" short. The measured
   shortfall against the armed deadline is about 1.7–1.9 ms in the two early trials. That takes two truncations
   (`:492` and `:172`). The prediction's time base is also part of the cause: it is anchored at the fault query, about
   1 ms before the deadline is armed. Section 15 also gives the range without saying that the values are bimodal.
2. **A7 counted as an unrecoverable misjudgment "because `auto_recoverable=0`".** Section 6 counts it from
   `truth_alive==1` with `sub_cause` `no_answer` and says the `auto_recoverable` column is not used. The count of 10/10 is
   right; the stated reason is not the frozen rule.
3. **"The misjudgment boundary was predicted from the source constants".** The cells put one stop on each side of the
   GIN 3 s deadline (1 s and 6 s) and test only an 8 s stop against the CPU harness's 1 s probe timeout. The position
   of either boundary was not measured, and the one failed prediction (B2a) is the timing at that boundary. Supported
   only as "each side behaved as predicted".
4. Minor, no verdict affected: "part A sunny +0 in 95/95" holds for `rp_cnp_handled` only (sunny `out_of_buffer`
   +7 in A10). "From the post" holds for all cells: `cqe_ns` and `detect_ns` start right after `post_write` returns
   (`probe_client.c:397`, `:449`, `:475`), in new and existing faults alike.

Outside section 15: DEVIATIONS 6 says the new `cqe_ns` and `t_post_mono_ns` fields enter the acceptance rules only for
no fault and the new faults. K7 uses both in A1 (`retry_server_qp_err`, an existing fault). There `t_post_mono_ns`
is the inject time taken right after `post_write` (`probe_client.c:449`, `:474`), so the difference is microseconds
and K7 is unaffected.
