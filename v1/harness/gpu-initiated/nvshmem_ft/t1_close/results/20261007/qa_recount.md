# t1_close: independent recount of the main run (QA)

Recount by a separate agent on 2026-10-07, from the raw files under `results/20261007/{A,B,C,D,E}/`. Tags: `[측정]` read from raw
files, `[추론]` interpretation, `[미확인]` not checked or not checkable from the saved files. Prediction ids are lookup keys only.

## Method

- Script: [../../qa/recount.py](../../qa/recount.py). It parses every `.meta`, `.pe0.log`, `.pe1.log`, the hold logs, the dmesg
  snapshots and the leftover files, and applies each frozen acceptance rule of `predictions.csv` itself.

  ```
  cd harness/gpu-initiated/nvshmem_ft/t1_close && python3 qa/recount.py   # optional: --csv <file> --rounds <file>
  ```

- Not used: `score.py`, `SCORE.md`, `trials_scored.csv`, and the output of `rows_t1.py` or `rows_v2.py`. I read `rows_t1.py`,
  `rows_v2.py`, `nvshmem_t1.cu` and `nvshmem_ibgda_t1close.diff` only for the log formats and the field definitions that section 3
  points to. The outcome rule (transparent, declined, failed, void) is re-implemented from that frozen definition; its code in
  `rows_t1.py` is unchanged since the tag (the post-tag diff only adds fields).
- Exposure note: the required `git diff prereg/nvshmem-t1-close-v1 -- EXPERIMENT.md` printed the new section 15 before the recount.
  All numbers below come from the script; section 15 was compared only afterwards.

## Frozen files `[측정]`

- `predictions.csv` sha256 `7f8b3204…897b` equals `PREREG.txt` and the file at the tag (annotated tag `e7af9281` on commit `9cdc27a5`).
- `PREREG.txt` and `predictions.csv` have no diff against the tag. The `EXPERIMENT.md` diff touches only the status and last-update
  rows of the header and sections 11–15. Sections 2, 3, 7 and 8 are unchanged.
- `specs/holdA.txt`, `holdB.txt`, `holdD.txt`, `holdE.txt`, `v22.txt` equal the section 7 spec lines (sorted diff empty).
  `scripts/t1/specs/lat.txt`, `run_matrix_t1.sh` and `scripts/v2/` are unchanged since the tag.

## Trial set against sections 7 and 8 `[측정]`

| hold | cells | planned | found | numbering | build in `.meta` (rain md5: binary / transport / host) |
|---|---|--:|--:|---|---|
| A | 10 cells (two recovery-time cells, seven reproduction cells, switch-off control) | 55 | 55 | 1..n per cell, no gap or duplicate | `nvshmem_t1close_b2`, `278089a4` / `b4b4115e` / `3d630308` |
| B | 5 fetch cells | 40 | 40 | same | same |
| C | 8 latency cells × 5 | 40 | 40 | same | 30 on `b2`; 10 `v22off` on `nvshmem_t1close_b2/v22ref`, `f1d4d304` / `6913dea6` / `54a9d23a` |
| C | FT v2.2 peer QP error, peer kill | 10 | 10 | same | `nvshmem_ft2`, `3d51a958` / `6913dea6` / `54a9d23a` |
| D | full GPU × 2, exit without finalize, 4 RC QPs | 35 | 35 | same | `b2` as hold A |
| E | 3 socket-outage cells | 20 | 20 | same | `b2` as hold A |

- 200 of 200 trials, no file outside the section 7 cells, every trial has its `.meta` and both PE logs.
- Every `.meta` knob matches its spec line (iterations, bytes, gap, test-skip token, fetch, fill, extra env, no-finalize, RC per peer,
  RC map, socket direction and timing, CTA and thread counts, kill time). Random fault times lie inside the line's `FAULT_LO`–`FAULT_HI`.
  The heap-overrun cell logs `bad_at=60`. Every PE 1 kernel timeout ends at its line's `KTIMEOUT` (within 1 s).
- Section 8 exclusions: void 0, fault not fired 0, wrong build 0, not run because of `STOP_AFTER_S` 0. No trial is counted apart.
- `[미확인]` The md5 values are computed on rain only. Sunny's copies are not recorded per trial; the deploy manifests are outside the
  repository. Indirect sign that sunny ran b2 in hold D: PE 1 exits 0 after `ATEXIT` in 10/10 exit-without-finalize trials (b1 aborted).
- Order: holds A, B and the latency part of C ran round robin; D, E and the v2 part of C ran cell after cell, as section 7 fixes.
- Smoke runs exist and are not scored: `results/20261007_smoke/smoke/` (9 trials, build b1) and `results/20261007_smoke/b2/smoke/`
  (9 trials, b2). The smoke hold output `results/smoke_hold.out` sits one level above the smoke folder.

## Per prediction `[측정]`

n = valid trials / trials run. Hits = valid trials meeting the per-trial part of the rule. Every range is over the unit named in the cell.

| prediction | id | n | hits | verdict | values |
|---|---|--:|--:|---|---|
| local QP error, new build: transparent, round median ≤ 5.5 ms, max ≤ 10 ms | N1 | 10/10 | 10 | **fail** | 10/10 transparent with one round. Initiator round total: median 5.793 ms, 4.306–6.928 ms over the 10 rounds (one per trial). Fails on the median |
| same, old sleep-poll wait: transparent, median ≥ 6.5 ms | C4 | 5/5 | 5 | pass | median 8.036 ms, 7.989–8.140 ms over 5 rounds |
| peer QP error + fetch every iteration: transparent, executed fetch 0, re-posted ≥ 1 | N2 | 10/10 | 10 | pass | fetches / exact / PE 1 counter = 1000 / 1000 / 1000 in 10/10; executed 0, re-posted 1, fetches in the unfinished range 1 in every trial; opcodes of that range `08-15-12-23` |
| local QP error between operations + fetch: transparent, executed fetch 0 | N3 | 10/10 | 10 | pass | 160 / 160 / 160 in 10/10; executed 0, re-posted 1 |
| local QP error in flight + fetch: outcome matches whether the responder executed the fetch | N4 | 10/10 | 10 | pass | 7 transparent (executed 0, counter 16000 = fetches); 3 declined (t6, t7, t10: executed 1, counter = exact + 1 with exact 4130, 2313, 2569, reason "executed by the responder"); failed 0 |
| as peer QP error + fetch, old fetch rule: declined, fetch not executed | C2 | 5/5 | 5 | pass | 5/5 declined "cannot be re-posted"; counter = exact (46, 66, 67, 68, 79) |
| as in-flight + fetch, executed fetch also re-posted (negative control) | C3 | 5/5 | 5 | pass | part with an executed fetch: 2 trials (t1, t2), both failed, counter 16001 = fetches + 1, final signal exact, one round. Part without: 3 trials, transparent |
| socket outage, packets into PE 0 only, then local QP error: transparent, PE 0 re-dials, PE 1 re-accepts | N5 | 10/10 | 10 | pass | lost, re-dialed, re-accepted 1/1/1 per trial; one round; iptables rule left 0 in 10/10. See note 2 |
| full GPU with 32 connections: transparent ≥ 8/10 is pass, copy-bound declines ≥ 8/10 is fail | N6 | 10/10 | 0 | **fail** | 0/10 transparent, 10/10 declined by the copy bound; record to decline 210.4–1150.2 ms over 10 trials; filler 191 CTAs |
| exit without finalize: transparent, both PEs join within 5 s, none detached | N7 | 10/10 | 10 | pass | rc 0/0 in 10/10; `ATEXIT` minus `T1EXIT` 2.159–2.279 ms over 20 PE exits; `join_ms` 2.1–2.2; joined 20/20; no `T1END` line (as expected without finalize) |
| 4 RC QPs per peer: transparent, one round with 4 QPs | N8 | 10/10 | 10 | pass | `nqps=4` in 10/10 initiator rounds, 4 per-QP field groups per line, responder rounds also 4; round total median 16.659 ms, 14.501–18.354 ms over 10 rounds |
| no fault: transparent, no round | R1 | 5/5 | 5 | pass | rounds 0 |
| local QP error in flight: transparent, one round | R3 | 5/5 | 5 | pass | round median 4.446 ms, 4.276–4.563 ms over 5 rounds |
| peer QP error: transparent, one round | R4 | 5/5 | 5 | pass | round median 5.720 ms, 5.288–6.003 ms over 5 rounds |
| five local QP errors, third inside the commit: transparent, 5 rounds | R5 | 5/5 | 5 | pass | 5 time-stamped shot lines per trial, one of them the in-commit shot; 5 rounds per trial |
| 4 CTAs × 8 threads, one RC QP: transparent | R6 | 5/5 | 5 | pass | one round each, 6.871–11.804 ms over 5 rounds |
| application's put past the heap: declined, finalize ≤ 1000 ms | R7 | 5/5 | 5 | pass | reason "class REM_ACCESS is not recoverable"; PE 0 finalize 20.8–22.7 ms over 5 trials |
| peer SIGKILL: declined, finalize ≤ 1000 ms | R8 | 5/5 | 5 | pass | reason "peer's library socket shows FIN"; finalize 24.0–24.8 ms |
| socket outage both ways, no fault: transparent | R9 | 5/5 | 5 | pass | lost, re-dialed, re-accepted 1/1/1; PE 1 logs no loss (0/5); rules left 0 |
| same outage, then local QP error: transparent | R10 | 5/5 | 5 | pass | as R9, one round; PE 1 logs no loss (0/5) |
| full GPU, default connections: declined ≤ 3000 ms after the record, finalize ≤ 1000 ms | R11 | 5/5 | 5 | pass | record to decline 423.5–1050.3 ms over 5 trials; finalize 23.3–24.1 ms |
| fault-free latency, 8 cells: three best-run p50 differences inside fixed bands | R12 | 40/40 runs | 3 of 3 bands | pass | 4 KiB switch on minus v2.2 off +2.208 µs [1.0, 2.6]; 4 KiB this build off minus v2.2 off +0.864 [0.2, 1.2]; 256 KiB on minus v2.2 off +2.144 [0.8, 2.4]. Bases: v2.2 off 12.352 µs (4 KiB), 40.064 µs (256 KiB) |
| FT v2.2, peer QP error: recovered, every operation verified | R13 | 5/5 | 5 | pass | rc 0/0; first record RETRY_EXC, `12/0x81`; 1 recovery round; ok iterations 200/200 on both PEs; final signal 200 = expected; 200 PE 1 ITER lines, 0 not ok; teardown returned; PE 0 finalize 22.4–23.7 ms |
| FT v2.2, peer kill: declined (peer dead), teardown returns | R14 | 5/5 | 5 | pass | reason "RETRY_EXC with the peer dead" 5/5; teardown returned; finalize 19.4–19.8 ms |
| switch off, local QP error: application sees the error | C1 | 5/5 | 5 | pass | status_bad 44–82 over 5 trials; rounds 0; failed 5/5; PE 0 killed at the 25 s run bound (rc 137), PE 1 kernel timeout (rc 4) |

Totals: 23 pass, 2 fail (N1 on the median, N6), 0 insufficient or undecided. Excluded or separately counted trials: 0.

### How the latency bands are applied (R12)

Each run prints five `LAT rep` lines on PE 0 (2000 ops each). Run statistic = median of the five p50 values. Cell value = minimum of
that over the 5 runs. The three differences use the v2.2-off cell of the same size. The bands are fixed numbers in `predictions.csv`;
the basis (four earlier sessions: 1.856–1.952, 0.672–0.928, 1.504–1.696 µs) lies inside them. Per-run medians (µs):

| cell | runs 1–5 | best |
|---|---|--:|
| 4 KiB v2.2 off | 14.080, 12.352, 12.416, 12.416, 12.384 | 12.352 |
| 4 KiB this build off | 14.336, 13.216, 13.376, 13.568, 15.424 | 13.216 |
| 4 KiB switch on | 14.560, 14.560, 14.656, 15.840, 16.448 | 14.560 |
| 256 KiB v2.2 off | 40.064, 40.096, 40.352, 40.288, 40.256 | 40.064 |
| 256 KiB switch on | 42.208, 42.208, 42.368, 42.336, 43.840 | 42.208 |

Sensitivity, not the frozen statistic: with the median of run medians the 4 KiB build-off difference is 1.152 µs, close to the 1.2
upper bound; with the minimum of all 25 p50 values it is 0.864. The two scored switch-on differences stay inside their bands either way.

## Safety records per hold `[측정]`

| hold | dmesg rain: lines before / after / new | dmesg sunny | mlx5 command errors | `t1sock` rules left | leftover files at hold end |
|---|---|---|--:|--:|---|
| A | 4360 / 4360 / 0 | 4296 / 4296 / 0 | 0 | 0 | rain 0, sunny 0 and 0 |
| B | 4360 / 4360 / 0 | 4296 / 4296 / 0 | 0 | 0 | 0 |
| C | 4360 / 4360 / 0 | 4297 / 4297 / 0 | 0 | 0 | 0 (latency part); v2 part has no hold-level file |
| D | 4360 / 4360 / 0 | 4297 / 4297 / 0 | 0 | 0 | 0 |
| E | 4360 / 4360 / 0 | 4297 / 4297 / 0 | 0 | 0 | 0 |

- New lines are recounted as lines of the after snapshot not in the before snapshot; the saved `*_new.txt` files are empty, as `hold.log` says.
- The rain snapshot is byte-identical in all five holds and in the smoke. It starts with the boot lines, and its last line is at uptime
  2505321 s, about 5 h before hold A (PE 0 clock 2523646 s). Rain logged nothing during the study `[측정]`.
- Sunny gained one line between holds B and C (FWTracer "Events were lost", uptime 1393934 s, about 19:44), outside any hold.
- Per-trial `.meta`: `iptables_left=0` in 20/20 socket trials. `leftover_rain=1` in 5/5 switch-off trials (C1), all other trials 0/0.
  The 5 "Killed" lines in hold A's log are those C1 PE 0 processes.
- `[미확인]` The hold-level `leftover_rain.txt` counts `nvt1_drv` only, not `nvt1v22_drv`; the per-trial `.meta` of the 10 v2.2-off
  latency runs shows 0 for that binary.

## Discrepancies and notes

1. **Recovery-time comparison (N1, C4).** Section 15 says the two cells alternated in one hold and differ by 2.25 ms. The medians give
   8.036 − 5.793 = 2.243 ms. Only N1 trials 1–5 alternated with C4; trials 6–10 ran back to back after the other cells of hold A had
   finished (round robin with unequal n). Paired difference over the five alternated rounds: median 1.72 ms, 1.09–2.31 ms over 5 pairs.
   N1 round time also depends on position: trials 1–6 (first in the hold or right after a C1 trial) 5.76–6.93 ms, median 6.08;
   trials 7–10 (after another N1 trial) 4.31–5.10 ms, median 4.58. The gap is in the handshake (2.99–3.47 vs 2.15–2.63 ms) and in the
   part of the total not split into phases (1.52–1.82 vs 1.08–1.40 ms). Cause `[미확인]`. The frozen rule covers all 10 rounds, so the
   verdict stays fail.
2. **Socket outage into PE 0 only (N5).** The prediction says PE 1 re-accepts "although its old connection never failed". In 10/10
   trials PE 1 logged `library socket lost (Connection reset by peer)` within 1 ms of PE 0's loss and re-dial (clocks aligned with
   the logged offset). The state the cell meant to create appears instead in the both-way cells (R9, R10): PE 1 logged no loss in 10/10 and
   re-accepted. The frozen N5 rule does not test this, so the verdict stays pass. Section 15 does not mention it.
3. **Outage length (N5, R9, R10).** In 20/20 socket trials PE 0 re-dialed 3.49–3.53 s into the 8 s rule window and the new connection
   worked. The rule matches the old local port only `[추론]`, so the library socket was down for about 3.5 s, not 8 s.
4. **Leftover processes.** Section 12 says no process of this study was left on either node. That holds at every hold end. Right after
   each C1 trial, the per-trial check still found 1 `nvt1_drv` on rain (5/5), the PE 0 killed at the run bound. Whether it was gone
   before the next trial's PE 0 started is `[미확인]`. Section 15 mentions rc 137 but not this count.
5. **Full GPU with 32 connections (N6).** `.meta` shows `xenv=CUDA_DEVICE_MAX_CONNECTIONS=32` in 10/10 and the runner exports it in
   both processes. No log line shows that the CUDA runtime used it `[미확인]`. Section 15's reading of the work-queue hypothesis rests on it.
6. **Exit without finalize (N7).** It passes on build b2, made after smoke 1 showed this cell aborting (rc 134/255; DEVIATIONS 1). In my
   recount of the smoke folders, smoke 1 is failed and smoke 2 transparent for this cell. The rule and the log format were not changed.
7. All other numbers of section 15 match the recount: counts per cell, round medians and ranges (C4, N8, R3, R4, the handshake
   median 3.01 ms with 2.15–3.47 ms), the N1 phase medians (prepare 0.117, commit 0.819, finish 0.026 ms), fetch values and counters,
   decline times, finalize ranges, `ATEXIT` gaps, latency differences, the v2.2 baselines, and status_bad 44–82.
