# t1_380 independent recount (QA)

Recount of the main run `results/20261008/{A,B,C}` (200 trials) from the raw `.meta`, `.pe0.log` and `.pe1.log`,
2026-10-08, by a separate agent. Script: [../../qa/recount.py](../../qa/recount.py) (`python3 qa/recount.py --md` from `t1_380/`).
Every number below is `[measured]` from the raw files unless marked `[inference]` or `[unverified]`.

## Method

- Not read or run: `score.py`, `SCORE.md`, `trials_scored.csv`, output of `rows_t1.py`. `rows_t1.py`, `run_trial_t1.sh`,
  `nvshmem_t1.cu` and the hold scripts were read only to learn the log formats and the field definitions that section 3
  fixes ("the fields are the output of rows_t1.py").
- `recount.py` has its own parser for the `.meta` key=value lines, `T1APP`, `T1RESULT`, `T1FETCH`, `T1EXIT`, `T1STATUS`,
  `T1END`, `LAT`, fault-inject `shot` lines, `device-classified error CQE` lines, `[nvshmem-ft] PE<p> enabled: ... handler=`,
  and `[nvshmem-t1]` `enabled: gates=`, `transparent mode stays off`, `RECOVERED <role>`, `DECLINE`, `ATEXIT` lines. It
  re-derives outcome (transparent, declined, failed, void) with the section 3 definitions and applies each
  `predictions.csv` acceptance string literally.
- Build group per trial = the `.meta` md5 triple (transport, host, driver; rain's copy) against the section 3 table.
  Group P and the S driver have no md5 in the frozen table ("written in section 12 at deploy"), so the section 12 values
  are used: P = `d6ae3699`, `825443f8`, `e309d516`; S driver `4dae151f`.
- Smoke `results/20261008_smoke/` exists (15 `.meta`); not scored.

## Frozen files

- `predictions.csv` sha256 `ff428525...` equals the hash in `PREREG.txt`; 18 rows (12 R, 5 N, 1 C).
- `git diff prereg/nvshmem-t1-380-v1` (tag commit `0fab6c67`) is empty for `predictions.csv` and `PREREG.txt`.
- `EXPERIMENT.md` sections 2, 3, 7, 8 are byte-identical to the tag. The diff touches only the header (status, last
  update) and sections 11 onward.
- `specs/hold{A,B,C}.txt` cell lines are identical to the section 7 code block (25 lines).

## Trial set (section 7) and exclusions (section 8)

- 25 cells, 200 trials: A 55, B 25, C 120. Every cell has exactly its planned n, trial indices 1 to n, no duplicate,
  no gap, no cell outside section 7. Every trial ran in the hold section 7 names.
- Run order in each `hold.log` equals the round-robin (INTERLEAVE=1) queue; `STOP_AFTER_S` never reached; pe0/pe1 rc in
  `hold.log` equal the `.meta`.
- `.meta` parameters equal the spec line for every trial (fault, mode, ft, t1, iters, bytes, gap_us, fetch, nofin,
  rc_per_pe, rc_map, handler, bin, bundle, reps, ctas, threads, burst, kill_ms; F1/F3 fault delay inside
  [FAULT_LO, FAULT_HI]). KTIMEOUT, PROC_TIMEOUT and SYM are not in the `.meta` `[unverified]`; the observed timeouts
  (10.0 s kernel limit in the CPU-proxy cell, 25 s kill in the switch-off control) match the spec.
- Build groups: P 110 trials (one triple `d6ae3699f95b` / `825443f85d59` / `e309d5164c01`, bundle `nvshmem_t1_380`),
  D 50 (`b4b4115ed0e5` / `3d63030802d5` / `278089a4eeda`), S 20 (`4aa4dda2a490` / `80eea986b645` / `4dae151fdc76`),
  V 20 (`6913dea69930` / `54a9d23acf0e` / `f1d4d304bd29`). Every trial is in its cell's group. PE0's config banner agrees in all 200: P `3.8.0` built
  Oct 8 10:44:56, S `3.8.0` built Oct 1 17:29:34, D `3.9.0.dev0` built Oct 1 14:49:35, V `3.9.0.dev0` built Sep 25.
- Exclusions: void 0, build mismatch 0, fault not fired 0, not run 0. Excluded count 0 in every prediction.

## Predictions

n = valid trials (or runs) / trials in the cell. Ranges are over all valid trials or rounds of that cell unless stated.

| prediction | id | n | hits | verdict | values (what the range is over) |
|---|---|--:|--:|---|---|
| no fault: transparent, no recovery round | R1 | 5/5 | 5 | holds | 5 transparent, 0 initiator rounds each, rc 0/0 |
| local QP error with operations in flight, port: transparent, one round | R2 | 10/10 | 10 | holds | 10 transparent, 1 round each; initiator round 4.213–5.410 ms (10 rounds) |
| same cell, devel build b2, same hold: transparent, one round | R3 | 10/10 | 10 | holds | 10 transparent, 1 round each; initiator round 4.291–4.603 ms (10 rounds) |
| recovery time port equals devel (median difference at most 1.0 ms) | N1 | 10+10 | | holds | median 4.790 vs 4.418 ms, difference 0.372 ms |
| peer QP error: transparent, one round | R4 | 5/5 | 5 | holds | initiator round 6.143–6.373 ms (5 rounds) |
| peer QP error with a fetch every iteration: transparent, fetch not executed and re-posted | R5 | 5/5 | 5 | holds | fetch_exec 0 and reposted 1 in all 5; fetches = exact = counter = 1000, poison 0, stale 0 |
| local QP error between operations with fetch: transparent, fetch not executed | R6 | 5/5 | 5 | holds | fetch_exec 0; fetches = exact = counter = 160 |
| in-flight local QP error with fetch: outcome concordant with responder execution | R7 | 5/5 | 5 | holds | 5 transparent, fetch_exec 0, counter = fetches = 16000; 0 declined (declined branch not exercised) |
| application's put past the heap: declined, finalize returns | R8 | 5/5 | 5 | holds | 5 declined ("class REM_ACCESS is not recoverable"), 0 rounds, PE0 finalize 22.2–22.6 ms, rc 3/4 |
| peer killed: declined, finalize returns | R9 | 5/5 | 5 | holds | 5 declined (peer socket FIN), PE0 finalize 24.5–25.5 ms, rc 3/255 |
| exit without finalize: transparent, helper joined within 5 s | R10 | 5/5 | 5 | holds | ATEXIT minus T1EXIT: PE0 2.157–2.190 ms, PE1 2.237–2.267 ms (5 each); helper joined on both PEs in all 5 |
| 4 RC QPs per peer: one round over 4 QPs | R11 | 5/5 | 5 | holds | 1 round each, nqps 4 in all 5; initiator round 15.056–18.132 ms |
| transparent switch off: application sees the error | C1 | 5/5 | 5 | holds | status_bad 44–82, 0 rounds, outcome failed; rc 137/4 (PE0 killed at the 25 s process limit) |
| CPU proxy: both PEs refuse transparent recovery | N2 | 10/10 | 10 | holds | "stays off" line on both PEs, no enabled line, handler CPU-proxy on both, 0 rounds (either role), 10 failed |
| CPU proxy: no device record, PE0 kernel times out | N3 | 10/10 | 10 | holds | 0 device-record lines on PE0, 0 error-CQE lines of any kind on either PE; kernel timeout on both PEs; PE0 after 10002.5–10003.8 ms; rc 7/4; fault fired once in all 10 |
| fault-free latency, unmodified 3.8.0 equals devel v2.2 baseline (both sizes within 0.5 µs) | N4 | 10/10 per cell | 1 of 2 pairs | **fails** | 4 KiB −0.160 µs, 256 KiB −0.512 µs |
| fault-free latency, port equals devel b2 (four pairs within 0.5 µs) | N5 | 10/10 per cell | 3 of 4 pairs | **fails** | 4 KiB FT off +0.672, switch on −0.032; 256 KiB FT off +0.384, switch on +0.160 µs |
| port cost over unmodified 3.8.0 inside the t1_close bands | R12 | 10/10 per cell | 1 of 3 bands | **fails** | 4 KiB on +2.400 in [1.0, 2.6]; 4 KiB off +1.824 not in [0.2, 1.2]; 256 KiB on +2.848 not in [0.8, 2.4] |

Total: 15 hold, 3 fail, 0 insufficient data.

**Recovery time (N1).** One initiator round per valid trial. Port, trial order 1 to 10: 4.758, 4.226, 4.956, 4.822, 4.893,
5.023, 5.410, 4.213, 4.360, 4.322 ms. Devel: 4.477, 4.291, 4.562, 4.429, 4.297, 4.406, 4.603, 4.455, 4.325, 4.303 ms.
Medians 4.790 and 4.418 (each the mean of the 5th and 6th of 10), difference 0.372 ms, limit 1.0 ms. Not in the rule:
the port is slower in 8 of 10 interleaved pairs (paired difference −0.242 to +0.807 ms); the devel median sits inside
the t1_close basis 4.45 [4.28–4.56], the port median above it.

## Latency (hold C)

Statistic exactly as section 3 and predictions.csv define it: per run, the median of its 5 `LAT rep` p50 values; per
cell, best = the minimum over the valid runs (10 of 10 valid in every cell). µs; bold = the run that gives the best.

| cell | run 1 | run 2 | run 3 | run 4 | run 5 | run 6 | run 7 | run 8 | run 9 | run 10 | best |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| `lat4k_stock` | 13.472 | **12.224** | 13.504 | **12.224** | **12.224** | 12.256 | 12.288 | 12.288 | 12.288 | 12.288 | 12.224 |
| `lat4k_t1off` | 15.552 | 15.552 | **14.048** | 15.552 | 15.552 | 14.720 | 15.520 | 15.584 | 15.584 | 15.520 | 14.048 |
| `lat4k_t1on` | 15.936 | 16.544 | 16.832 | 14.816 | 16.448 | **14.624** | 16.416 | 16.416 | 14.752 | 14.752 | 14.624 |
| `lat4k_dv22off` | **12.384** | **12.384** | 12.768 | 12.416 | 12.416 | **12.384** | 12.512 | 12.512 | 12.480 | 13.952 | 12.384 |
| `lat4k_dt1off` | 13.408 | 13.856 | 13.568 | **13.376** | 13.408 | 15.104 | 13.600 | 13.760 | 13.600 | 13.600 | 13.376 |
| `lat4k_dt1on` | 16.512 | **14.656** | 16.000 | 16.448 | 16.448 | **14.656** | 16.416 | 14.816 | 16.512 | 16.512 | 14.656 |
| `lat256k_stock` | **39.648** | 39.680 | 39.712 | 39.712 | 39.712 | 41.216 | 39.808 | 39.776 | 39.776 | 39.744 | 39.648 |
| `lat256k_t1off` | **41.344** | 41.408 | **41.344** | 41.440 | 41.504 | 41.408 | 41.568 | 41.568 | 41.568 | 41.568 | 41.344 |
| `lat256k_t1on` | **42.496** | 42.528 | **42.496** | 42.528 | 42.656 | 42.656 | 42.624 | 42.624 | 42.816 | 42.816 | 42.496 |
| `lat256k_dv22off` | 40.224 | 40.288 | **40.160** | 40.192 | **40.160** | 40.384 | 40.352 | 40.352 | 40.352 | 40.384 | 40.160 |
| `lat256k_dt1off` | 41.280 | 41.152 | 41.088 | 43.008 | 40.992 | **40.960** | 42.240 | 43.008 | 42.784 | **40.960** | 40.960 |
| `lat256k_dt1on` | 43.808 | 42.944 | **42.336** | 43.584 | **42.336** | 43.904 | 43.744 | 42.432 | 42.464 | 42.464 | 42.336 |

Every p50 value is a multiple of 0.032 µs (timer step), so best-run differences move in 0.032 µs steps.

**Robustness** (leave-one-run-out: drop each of the 20 runs of a pair once and recompute the rule's difference; "median
of runs" = difference of the two cells' medians over their 10 run values, not part of any rule):

| comparison | rule value | leave-one-out range | drops that flip | median of runs | reading |
|---|--:|---|--:|--:|---|
| unmodified vs devel v2.2, 256 KiB (N4, miss) | −0.512 | −0.512 to −0.480 | 1 of 20 | −0.592 | the miss rests on one run: dropping unmodified run 1 (39.648) gives −0.480, a hold. The miss is one timer step past the limit. The direction is not one run: 9 of 10 unmodified runs (39.648–39.808) are below every v2.2 run (40.160–40.384) |
| unmodified vs devel v2.2, 4 KiB (N4, hold) | −0.160 | −0.160 | 0 | −0.160 | stable |
| port vs devel, 4 KiB FT off (N5, miss) | +0.672 | +0.640 to +1.344 | 0 | +1.952 | robust: all 10 port runs (14.048–15.584) are above 9 of 10 devel runs (13.376–13.856); 8 port runs sit at 15.520–15.584 |
| port vs devel, 4 KiB switch on (N5, hold) | −0.032 | −0.032 to +0.096 | 0 | −0.256 | stable |
| port vs devel, 256 KiB FT off (N5, hold) | +0.384 | +0.384 | 0 | +0.256 | stable |
| port vs devel, 256 KiB switch on (N5, hold) | +0.160 | +0.160 | 0 | −0.080 | stable |
| port cost, 4 KiB switch on (R12, hold, band 1.0–2.6) | +2.400 | +2.400 to +2.528 | 0 | +3.888 | holds on the best-run statistic only: the port cell is bimodal (4 runs 14.624–14.816, 6 runs 15.936–16.832); 4 of 10 port runs alone are in the band |
| port cost, 4 KiB FT off (R12, miss, band 0.2–1.2) | +1.824 | +1.824 to +2.496 | 0 | +3.264 | robust: no port run is in the band |
| port cost, 256 KiB switch on (R12, miss, band 0.8–2.4) | +2.848 | +2.816 to +2.848 | 0 | +2.896 | robust: no port run is in the band |

So the 4 KiB FT-off failures (N5 and R12) and the 256 KiB switch-on cost failure (R12) are robust; the N4 failure is a
one-step miss that depends on a single unmodified-release run, although the cell medians differ by more than 0.5 µs too.

## Safety records

| hold | dmesg rain / sunny (before = after) | new lines | mlx5 command errors | iptables `t1sock` left | study processes left at hold end | per-trial `.meta` leftover (rain, sunny) | lock |
|---|---|--:|--:|--:|---|---|---|
| A | 4360 / 4297 lines, identical | 0 / 0 | 0 / 0 | 0 | rain 0, sunny 0 | (1, 0) in all 5 switch-off trials, (0, 0) in 50 | `t1x-A` 10:54:42, idle 10:55:13, rc 0 at 11:01:47 |
| B | 4360 / 4297, identical | 0 / 0 | 0 / 0 | 0 | 0, 0 | (0, 0) in 25 | `t1x-B` 11:08:04, idle 11:08:35, rc 0 at 11:13:10 |
| C | 4360 / 4297, identical | 0 / 0 | 0 / 0 | 0 | 0, 0 | (0, 0) in 120 | `t1x-C` 11:19:27, idle 11:19:59, rc 0 at 11:24:05 |

- The dmesg snapshots are byte-identical before and after every hold and across the three holds (same md5): no kernel
  message on either node from 10:55 to 11:24. The last rain lines are old NVRM Xid 31 lines of another program
  (`nvs_kill_repro`), present before hold A.
- The switch-off control trials (C1) record `leftover_rain=1`: PE0 is SIGKILLed at the 25 s process limit (rc 137, no
  `T1END` after `T1STATUS`), and the count right after `pkill -x nvt1_drv` still sees it. The next trial started in the
  same second and begins with `pkill -x`; the following no-fault trials were all transparent, and the hold-end count is 0.
  `[inference]` a process still exiting, not a leak. This is not a rule breach, but "0 processes left" holds only at
  hold level.
- Gate race test in hold A: 2 of 2 PASS (`A/holdA/gate_race_test.out`).

## Section 15 of EXPERIMENT.md against the raw data

Read after the recount. Every number in section 15 matches the recount: the 200/0/0 counts, smoke 15, all ranges and
medians in the fault table (R2 4.21–5.41 median 4.79, R3 4.29–4.60 median 4.42, N1 +0.37, R4 6.14–6.37, R8 22.2–22.6,
R9 24.5–25.5, R10 2.16–2.27, R11 15.06–18.13, C1 44–82, N3 rc 7/4), the 12 best-run values, the N4, N5 and R12
differences, the 4 KiB FT-off run split (8 runs 15.52–15.58, 2 runs 14.05 and 14.72) and the devel FT-off range
(13.38–13.86, one 15.10). Statements the raw data do not support, or support only in part:

1. "공식 v3.8.0-0의 CPU 프록시 record 버그가 옮긴 빌드에도 그대로 있다는 뜻이다" sits under the section's blanket `[측정]`.
   The raw data show no device-record line, no error-CQE line on either PE and a kernel timeout; attributing that to the
   doorbell-record bug is an inference (no record or doorbell trace in these logs) and should carry `[추론]`.
2. "투명, 거절, fetch 규칙, ... 모두 같은 결과였다" (same as t1_close). For the in-flight fetch cell (R7) all 5 trials were
   transparent; t1_close had 7 transparent and 3 declined. The rule holds, but the declined branch (fetch executed by
   the responder, decline with reason) was not exercised by the port, so "same fetch rule" is shown only for the
   transparent branch. The table row says so; the bullet does not.
3. "옮긴 빌드는 FT를 꺼도 투명 켬과 거의 같은 지연을 보였다": the port's 4 KiB FT off is 0.576 µs below its switch-on on the
   best run (14.048 vs 14.624) and 0.624 µs below on the median of runs (15.552 vs 16.176), more than the 0.5 µs
   equivalence margin of N5. "Closer to switch-on than devel FT off is" is supported; "almost the same" is not.
4. N4 256 KiB ("0.012 µs 넘음", "0.51 µs 빨랐다"): correct, but the section does not say the miss is one 0.032 µs timer
   step and that it flips to a hold if unmodified run 1 is dropped (median-of-runs gap −0.592 µs). Missing context, not a
   contradiction.
5. "독립 재계산은 아직이다": now done (this file).

Outside section 15: section 12's hold A row says "재현 칸 7개"; hold A has 6 five-trial reproduction cells (R1, R4, R8, R9,
R10, R11): 6 x 5 + 2 x 10 + 5 = 55. Its "남은 프로세스 0" is true at hold level (see the C1 note above).

## Limits

- md5s in `.meta` are of rain's files only; sunny's copies are not checked per trial `[unverified]` (section 12 reports a
  two-node md5 comparison at deploy).
- DEVIATIONS.md item 3 (another study's `libnccl` md5 change) has no raw file in `results/` and was not checked
  `[unverified]`.
- t1_close numbers (bands, 4.45 ms basis) are taken from the frozen predictions as stated; `../t1_close/results` was not
  recounted.
