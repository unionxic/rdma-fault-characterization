# nccl-builtin: independent recount of the main run

Date 2026-10-09. Recounted by a separate agent from the raw per-trial files of `results/20261009/` with
[`qa/recount.py`](../../qa/recount.py) (`python3 -B qa/recount.py` from the study folder; it prints the full report and
writes nothing). Markers: `[measured]` read from the raw files, `[inferred]` interpretation.

## Verdict

- **26 predictions hold, 1 fails (O4), 0 insufficient data** over the 27 rows of `predictions.csv` `[measured]`.
- 295 trials found, 0 excluded, 295 scored. The scorer's "295 trials, 295 scored, no exclusion" is **confirmed**.
- O4 fails on its 64 KiB part only: Stage 2 flag on vs flag off +3.75 % against a 3 % limit. The 16 MiB part holds
  (+0.13 %, limit 2 %).
- The 295 per-trial lines of `hold_H1.out`–`hold_H15.out` agree with this recount on every compared field (0
  differences).

## Method

**What was not used.** `score.py`, `rows_nb.py`, `SCORE.md`, `trials_scored.csv`, `trials_pilot.csv`, every other
`trials_*.csv`, and the `s2_close` scorer were neither read nor run. `cells.py` imports `rows_nb.py`; `cells.py` was read,
not run.

**What was read.**
- Raw trial files `<cfg>/<cell>.<cfg>_n<k>_{r0.log,r1.log,meta.txt}`, `hold_H*.out`, `chain.out`, `snap_*`, `mlx5_new_*`.
- `EXPERIMENT.md`, `predictions.csv`, `PREREG.txt`, the runner (`nbrun.py`, `cells.py`, `hold.sh`, `chain.sh`) and the
  driver `../perf/nccl_ct.cu`. The driver was read for its output lines.
- Log formats from the NCCL 2.32.3 tree in the session scratch (`p2p.cc`, `p2p_resiliency*.cc`, `common.cc`, `init.cc`)
  and from `../stage2/net_ib_stage2.diff`.

**Columns.** Every column of EXPERIMENT.md 3.1 is parsed again from the logs: outcome, error lines and codes, times,
status numbers, line counts, SUMMARY fields, MISMATCH, environment from meta. Interpretation choices:
- `err_r<r>`: the first driver line `[rankN] iter N async NCCL error[ after sync]: <string>` (async), or a call that
  returned an error (call). The string is mapped with `ncclGetErrorString`. All 185 error lines in the run are async
  `ncclRemoteError`.
- `wc_status_r<r>`: the first, in log order, of four forms:
  - `Got completion from peer ... status=<NAME>(<n>)` (2.32.3 stock);
  - `wc->status=(<NAME>)<n>` (2.32.3 resiliency INFO);
  - `Got completion from peer ... status=<n> ` (2.23.4 stock);
  - `incident via <x>: status=<n>(` (Stage 2).
- `t_fault`: for injection cells, the receipt time of the first hook line (only one rank fired, in every trial). For
  kill cells, meta `t_kill_req`. All times are receipt times on rain's CLOCK_MONOTONIC. Rank 1's lines include the ssh
  delay.
- `s2_rec_ms`: the `total` of the earliest `send comm: recovered` line across both ranks. Every Stage 2 recovery trial
  has exactly one.
- `outcome`: as defined in 3.1. TRANSPARENT also needs a SUMMARY line on both ranks.
- `median()` uses `statistics.median`: for n = 10, the mean of the 5th and 6th values. The O rules were also checked
  with the lower and upper median.

**Rules.** The section-8 exclusion and configuration checks were coded from the text of section 8 (and checked against
`config_status` in `cells.py`). The acceptance rules were evaluated by a separate evaluator of the s2_close 3.2 grammar
(`count`, `median`, `abs`, `has`, `nonempty`, `per cell:`). Any comparison or arithmetic with a blank value is false. The
evaluator was tested on synthetic rows, including blanks inside `not (...)` and chained comparisons.

**Git.** Only read commands: `git show <tag>:<path>`, `rev-parse`, `log`, `check-attr`. One `git status --short` ran
at the start. It changes no content, but it may refresh the index stat cache and run the clean filter on `hold.sh`.

## Integrity checks [measured]

| check | result |
|---|---|
| `predictions.csv` sha256: working tree, tag blob, `PREREG.txt` | all `d6804c5490ba0d497a44053670bcd804d8403870e659672ddd6bc9cc95f7f515` |
| tag `prereg/nccl-builtin-v1` | annotated tag on `0ca10eb7`, which is the working tree's HEAD |
| EXPERIMENT.md sections 2, 3, 7, 8 vs `git show prereg/nccl-builtin-v1:...` | byte-identical (1 756, 12 434, 2 214 and 4 287 bytes). The whole file is identical to the tag blob |
| `PREREG.txt`, `cells.py`, `nbrun.py`, `chain.sh`, `inject_232.diff` vs tag | identical |
| `hold.sh` vs tag | differs only in line 16, the sunny ssh address. This matches the repo's `mgmtip` clean filter: the working tree holds the real address and the blob a placeholder |
| trial set vs section 7 | 34 cell keys, 295 trials (fault 195, fault-free 100). Plan parsed from the section-7 table, numbering `n1..nN` has no gaps, no extra or missing key, every trial has meta, r0 and r1 files, no stray file |
| pilot kept apart | pilot folder 34 trials dated 01:04:16–01:09:50. Every main-run trial is dated 03:21:30–06:21:54, after the pre-registration at 01:27:17 |
| holds | H1–H15 each ran exactly the keys and counts of section 9, rc 0, no `STOP_*` file |
| hold snapshots (30) | bundle md5 `9269cc75` (2.32.3), `9ed03e1d` (2.23.4), `523fd863` (driver) on both nodes in every snapshot. Ports: rain mlx5_0 DOWN, mlx5_1 ACTIVE; sunny mlx5_0 ACTIVE, mlx5_1 DOWN; fw 20.43.4100. Kernels as in section 5. No GPU process listed. INFO logs show `ndevs=1` (rain mlx5_1, sunny mlx5_0) |
| mlx5 | rain command-error lines 2, sunny 0, rain firmware-command failures 31 in all 30 snapshots, so no growth. New kernel lines: one, in H13 (sunny `mlx5_fw_tracer_handle_traces ... FWTracer: Events were lost`). Not a command error |

## Exclusions and configuration [measured]

- Launch failures 0.
- Every injected trial has exactly one hook line on the intended rank, of the intended kind. Kill and fault-free trials
  have no hook line.
- Kill trials: 40/40 kills went through the PID check. The survivor finished 40 655–45 218 iterations before it ended
  (range over the 40 kill trials; the rule needs at least 1 000). The kill's ssh command returned after 235.0–260.7 ms.
- Configuration check (section 8) failures: 0. `nb_ct` left behind before or after a trial: 0. Wall cap reached: 0.
- **Excluded 0, scored 295.** No replacement trial was run.

## Per-prediction verdicts [measured]

hits = trials that behave as predicted. For a `count(E) == 0` rule (F5, F6, F7, I1) that means E is false; for the
other count rules it means E is true. Each n is the number of trials of one cell key. All keys reached the planned n.

| id | prediction (short) | cell keys | n per key | hits per key | verdict |
|---|---|---|---|---|---|
| B1 | 2.32.3 off, send QP: rank 0 ncclRemoteError within 1 s, stock CQE path, status 5 | `sqp@off` | 10 | 10 (rule ≥9) | holds |
| B2 | 2.32.3 off, recv QP: rank 1 itself, the same | `rqp@off` | 10 | 10 (≥9) | holds |
| B3 | 2.32.3 off, peer kill: survivor hangs to its 12 s timeout | `kill@off` | 10 | 10 (≥9) | holds |
| B4 | 2.32.3 off, silent recv QP: rank 1 itself ncclRemoteError within 1 s, status 5 | `slbc@off`, `slar@off` | 10, 10 | 10, 10 (≥9) | holds |
| R1 | recovery variable alone behaves as off, no resiliency line | `sqp@rec` | 5 | 5 (≥4) | holds |
| F1 | failover (with or without recovery), send QP: fatal at once, rank 0 ncclRemoteError within 1 s, no stock line, no recovery activity | `sqp@fo`, `sqp@forec` | 10, 10 | 10, 10 (≥9) | holds |
| F2 | the same for the recv QP on rank 1 | `rqp@fo`, `rqp@forec` | 10, 10 | 10, 10 (≥9) | holds |
| F3 | failover, peer kill: survivor hangs | `kill@fo`, `kill@forec` | 10, 10 | 10, 10 (≥9) | holds |
| F4 | failover, silent recv QP: rank 1 fatal and ncclRemoteError within 1 s, no activity | `slbc@fo`, `slbc@forec`, `slar@fo`, `slar@forec` | 10 each | 10 each (≥9) | holds |
| F5 | single-device warning on both ranks in every failover trial | 14 keys (10 fault, 4 fault-free) | 10 each | 10 each (exceptions 0) | holds |
| F6 | no 2.32.3 fault trial is transparent | 16 keys | 10 each, `sqp@rec` 5 | all (transparent 0) | holds |
| F7 | no device-failed, QP replacement, probe or port-recovery line in 2.32.3 fault trials | 16 keys | 10 each, `sqp@rec` 5 | all (activity 0) | holds |
| S1 | Stage 2 on recovers send and recv QP faults transparently | `sqp@s2on`, `rqp@s2on` | 5, 5 | 5, 5 (==5) | holds |
| S2 | Stage 2 recovery time median 1.8–3.0 ms in both keys | `sqp@s2on`, `rqp@s2on` | 5, 5 | medians 2.306 and 2.233 ms | holds |
| S3 | Stage 2 on: survivor gets an error within 1 s of the kill, through the FIN | `kill@s2on` | 5 | 5 (==5) | holds |
| S4 | Stage 2 on, silent broadcast: no rank 1 error within 1 s; transparent or hang | `slbc@s2on` | 5 | 5 (==5) | holds |
| S5 | Stage 2 on, silent all-reduce: hang | `slar@s2on` | 5 | 5 (==5) | holds |
| S6 | Stage 2 off, send QP: ncclRemoteError within 1 s, status 5, no recovery | `sqp@s2off` | 5 | 5 (==5) | holds |
| S7 | Stage 2 off, recv QP: rank 1 ncclRemoteError within 1 s, status 5, no recovery | `rqp@s2off` | 5 | 5 (≥4) | holds |
| S8 | Stage 2 off, peer kill: survivor hangs | `kill@s2off` | 5 | 5 (≥4) | holds |
| S9 | Stage 2 off, recv QP: rank 0 ends the faulted all-reduce with wrong data and no error, after rank 1's error | `rqp@s2off` | 5 | 5 (≥4) | holds |
| I1 | no MISMATCH line in the other 32 keys | 32 keys | 10 or 5 | all (MISMATCH 0) | holds |
| O1 | failover vs off, 16 MiB, at most 2 % | `ovh16m@fo` vs `@off` | 10, 10 | −0.15 % | holds |
| O2 | failover vs off, 64 KiB, at most 5 % | `ovh64k@fo` vs `@off` | 10, 10 | +1.73 % | holds |
| O3 | failover+recovery vs failover, at most 2 % at both sizes | `ovh16m`, `ovh64k`: `@forec` vs `@fo` | 10 each | −0.07 %, −1.70 % | holds |
| O4 | Stage 2 on vs off, at most 2 % at 16 MiB and 3 % at 64 KiB | `ovh16m`, `ovh64k`: `@s2on` vs `@s2off` | 10 each | +0.13 %, **+3.75 %** | **fails** |
| O5 | every fault-free run transparent | 10 keys | 10 each | 10 each (==10) | holds |

## Key numbers [measured]

All times are ms after the fault (see Method). **Each range is min–max over the trials of that one cell key** (n in the
second column). It is never a range over several keys or a single representative trial.

### Faults: outcome, application error, recovery

| fault | config | n | outcome | rank that took the fault: app error, ms (median) | other rank | recovery |
|---|---|--:|---|---|---|---|
| send QP ERR (rank 0) | off | 10 | ERROR 10 | ncclRemoteError 10/10, 0.041–0.103 (0.064), stock CQE line, status 5 | no error; runner grace-killed it 10/10 | none |
| | rec | 5 | ERROR 5 | 5/5, 0.050–0.091 (0.058), stock line, status 5 | grace-killed 5/5 | none |
| | fo | 10 | ERROR 10 | 10/10, 0.030–0.094 (0.076), fatal line, no stock line | grace-killed 10/10 | none |
| | forec | 10 | ERROR 10 | 10/10, 0.051–0.091 (0.067), fatal line | grace-killed 10/10 | none |
| | s2on | 5 | TRANSPARENT 5 | no app error | no app error | 5/5, send-comm total 2.270–2.482 ms (median 2.306) |
| | s2off | 5 | ERROR 5 | 5/5, 0.047–0.096 (0.068), status 5 | no error; TIMEOUT 11 998.6–11 998.7, then grace-killed | none |
| recv QP ERR (rank 1) | off | 10 | ERROR 10 | 10/10, 0.051–0.145 (0.097), status 5 | ncclRemoteError 10/10 at 3 499.0–3 768.9, status 12 | none |
| | fo | 10 | ERROR 10 | 10/10, 0.033–0.104 (0.097), fatal | 10/10 at 3 509.0–3 578.8, status 12, fatal | none |
| | forec | 10 | ERROR 10 | 10/10, 0.049–0.151 (0.094), fatal | 10/10 at 3 532.2–3 786.6, status 12, fatal | none |
| | s2on | 5 | TRANSPARENT 5 | no app error | no app error | 5/5, total 2.172–2.392 ms (median 2.233) |
| | s2off | 5 | MISMATCH 5 | 5/5, 0.053–0.103 (0.094), status 5 | no app error; wrong result (next section) | none |
| peer SIGKILL (rank 1) | off | 10 | HANG 10 | (killed) | no error; TIMEOUT 12 240.4–12 254.7 | none |
| | fo | 10 | HANG 10 | | TIMEOUT 12 240.9–12 254.1 | none |
| | forec | 10 | HANG 10 | | TIMEOUT 12 234.2–12 255.8 | none |
| | s2on | 5 | ERROR 5 | | ncclRemoteError 5/5 at 297.659–309.974 after the kill request. That is 49.241–49.292 after the kill's ssh command returned and 0.013–0.021 after rank 0's FIN line (FIN line in 5/5) | none: Stage 2 found the peer dead (FIN) and returned the stock error |
| | s2off | 5 | HANG 5 | | TIMEOUT 12 245.9–12 252.9 | none |
| silent recv QP ERR, 64 MiB broadcast | off | 10 | ERROR 10 | 10/10, 0.067–0.104 (0.099), status 5 | 10/10 at 3 523.2–3 687.8, status 12 | none |
| | fo | 10 | ERROR 10 | 10/10, 0.048–0.104 (0.078), fatal | error 1/10 (3 601.7); 9/10 grace-killed with no error CQE | none |
| | forec | 10 | ERROR 10 | 10/10, 0.053–0.151 (0.097), fatal | error 4/10 (3 532.8–3 790.5); 6/10 grace-killed | none |
| | s2on | 5 | TRANSPARENT 5 | no app error; drained without notifying 5/5 | RETRY_EXC (12), recovered 5/5; recovery line at 3 537.7–3 692.3 | 5/5, total 1.928–2.037 ms (median 1.998) |
| silent recv QP ERR, 256 KiB all-reduce | off | 10 | ERROR 10 | 10/10, 0.157–0.213 (0.164), status 5 | no error, no error CQE; grace-killed 10/10 | none |
| | fo | 10 | ERROR 10 | 10/10, 0.048–0.110 (0.053), fatal | grace-killed 10/10 | none |
| | forec | 10 | ERROR 10 | 10/10, 0.070–0.104 (0.077), fatal | grace-killed 10/10 | none |
| | s2on | 5 | HANG 5 | no app error; drained without notifying 5/5; TIMEOUT 12 000.2–12 000.3 | no error; TIMEOUT 11 999.7–12 000.1 | none; MISMATCH 0, also after the timeouts |

### The 2.23.4 recv-QP fault with recovery off (`rqp@s2off`), wrong data on rank 0

- In 5/5 trials, rank 0 finished iteration 18 (the faulted all-reduce) with no NCCL error and with wrong data
  `[measured]`.
- Each time, **524 288 of 4 194 304 elements** (1/8) were wrong. First wrong index: 3 670 016 in 4 trials, 1 572 864 in
  1.
- Timing:
  - The MISMATCH line came 632.3–649.5 ms after the hook and 632.2–649.4 ms after rank 1's ncclRemoteError.
  - Rank 1's error came 0.053–0.103 ms after the hook.
  - Rank 0's first error CQE (RETRY_EXC, 12) came 3 544.3–3 724.3 ms after the hook, while it was already aborting. It
    produced no application error line.
- Rank 1 had no MISMATCH. Both ranks ended with ABORT-HANG (rc 7) in 5/5.
- In the whole main run there are 5 MISMATCH lines, all in this key.

### Did failover or recovery code act? [measured]

- Resiliency activity lines (the seven patterns of `prec_activity`): **0** in 295 trials.
- A wider net also found 0 lines:
  - the "error is not fatal" branch;
  - device marked failed (also "already marked");
  - recovery queue, port recovery start, success or failure;
  - QP replacement, probe posting;
  - the sender and receiver handlers;
  - "unsupported status".
- At close, all 168 recovery-queue close requests removed 0 items.
- The resiliency error handler was entered 105 times ("Got completion with error"), all in `fo` and `forec`. Each entry
  ended in 105 "The error is fatal (No functional devices left)" lines:
  - 80 on the faulting rank, in 80/80 failover QP-fault trials;
  - 20 on rank 0 of `rqp@fo` and `rqp@forec`;
  - 5 on rank 0 of `slbc@fo` and `slbc@forec`.
- Stock CQE lines in failover trials: 0. Failover kill trials: no error CQE and no fatal line (20/20). Those cells log at
  WARN.

### ncclCommAbort [measured]

A rank log called abort when its SUMMARY has rc ≠ 0.

| library | abort called | returned | ABORT-HANG (10 s watchdog) | neither |
|---|--:|--:|--:|--:|
| 2.32.3 | 200 | 200, 516.9–563.7 ms after SUMMARY (range over the 200 rank logs) | 0 | 0 |
| 2.23.4 (Stage 2 build) | 40 | 0 | 35 (`rqp@s2off` 10, `slar@s2on` 10, `sqp@s2off` 5, `kill@s2on` 5, `kill@s2off` 5) | 5 (`sqp@s2off` rank 1, grace-killed while aborting) |

### Fault-free all-reduce time [measured]

Each run gives rank 0's SUMMARY `med_ms`. In 100 of 100 runs this value was recomputed from the IT lines with the
driver's upper-median rule and matched. Cell value = median over the 10 runs. The range is min–max over the 10 runs of
that key. H1 holds runs n1–n5 of each key, H2 holds n6–n10.

| size | config | n | median (ms) | range over runs | H1 median | H2 median |
|---|---|--:|--:|---|--:|--:|
| 64 KiB | off | 10 | 0.0578 | 0.0533–0.0589 | 0.0585 | 0.0574 |
| 64 KiB | fo | 10 | 0.0588 | 0.0571–0.0600 | 0.0594 | 0.0580 |
| 64 KiB | forec | 10 | 0.0578 | 0.0559–0.0596 | 0.0582 | 0.0574 |
| 64 KiB | s2on | 10 | 0.0539 | 0.0512–0.0609 | 0.0532 | 0.0566 |
| 64 KiB | s2off | 10 | 0.0520 | 0.0511–0.0536 | 0.0522 | 0.0518 |
| 16 MiB | off | 10 | 2.1658 | 2.1561–2.1906 | 2.1644 | 2.1673 |
| 16 MiB | fo | 10 | 2.1626 | 2.1477–2.1895 | 2.1659 | 2.1606 |
| 16 MiB | forec | 10 | 2.1611 | 2.1475–2.1673 | 2.1617 | 2.1608 |
| 16 MiB | s2on | 10 | 2.2668 | 2.2595–2.2767 | 2.2667 | 2.2669 |
| 16 MiB | s2off | 10 | 2.2639 | 2.2559–2.2979 | 2.2638 | 2.2655 |

**O4 recomputed.**
- 16 MiB: 2.2668 vs 2.2639 ms is +0.13 % (limit 2 %), within.
- 64 KiB: 0.0539 vs 0.0520 ms is **+3.75 %** (limit 3 %), outside. With the lower or upper median of 10 instead, it is
  +3.28 % or +4.21 %, so the failure does not depend on the median definition `[measured]`.
- Per run, `ovh64k@s2on` in run order: 0.0512, 0.0532, 0.0609, 0.0513, 0.0535 (H1), then 0.0570, 0.0566, 0.0544, 0.0574,
  0.0533 (H2). `ovh64k@s2off`: 0.0515–0.0536 in both holds.
- Inside one hold the 64 KiB difference is +1.92 % (H1) and +9.27 % (H2), 5 runs each. At 16 MiB it is +0.13 % and
  +0.06 %.
- Run-to-run spread (max−min)/median at 64 KiB in this run: off 9.7 %, s2off 4.8 %. At 16 MiB: off 1.6 %, s2off 1.9 %.
- `[inferred]` The 64 KiB failure comes mostly from the H2 runs of `s2on`. Its size is of the same order as this run's
  scatter between runs of one key, so these data cannot tell a stable cost from drift. The prediction still fails as
  registered.

All 100 fault-free runs: TRANSPARENT, rc 0/0, ok = iters on both ranks.

## Disagreements and differences

**With the hold logs: none.** On all 295 per-trial lines, the hold logs and this recount agree on outcome, rc, hook
counts, error kind and code, `dt_err` (to 0.0015 ms), wall time, leftover processes and configuration status.

**With the scorer's reported totals: none.** 295 trials, 295 scored, no exclusion.

**With EXPERIMENT.md.** Sections 2, 3, 7 and 8 match the data's design: trial set, counts, holds. The differences
below are between EXPERIMENT.md text and the main-run data. None of them changes a verdict except item 1.

1. **O4 (section 3.3) fails** at 64 KiB (+3.75 % vs ≤3 %). Section 1's earlier measurement (+1.27 % at 64 KiB, 3 runs
   per key, `../perf`) was not reproduced. The 16 MiB part (+0.13 %; earlier −0.22 %) agrees.
2. **Section 12, pilot review**, says that with the silent broadcast fault rank 0 also got RETRY_EXC 3 591–3 684 ms
   after the hook. That was 3 pilot trials, one per 2.32.3 configuration. In the main run this holds for `slbc@off`
   (10/10). It does not hold with failover on: `slbc@fo` 1/10, `slbc@forec` 4/10. In the other 15 trials rank 0 saw no
   error CQE before the runner's 6 s grace kill (rc −9). This is an exploratory observable (3.4), not a prediction. The
   cause is `[unverified]`.
3. **Section 3.4** cites the pilot: all 7 2.23.4 rank logs that called abort ended at the watchdog. In the main run,
   35 of 40 ended at the watchdog. The other 5 (`sqp@s2off` rank 1) were grace-killed by the runner while aborting. The
   main run has no return of `ncclCommAbort` in 2.23.4 (0/40). In 2.32.3 every call returned (200/200).
4. **Section 12, pilot overhead**: `forec` was 4.0 % (64 KiB) and 4.7 % (16 MiB) slower than `fo` in one run each. With
   10 runs each the difference is −1.70 % and −0.07 % (O3 holds). The pilot difference did not reproduce, as the section
   itself cautioned.
5. **Section 1, earlier Stage 2 silent-broadcast result** (C6): RETRY_EXC and recovery in 1/3, no error in 2/3. The
   main run's `slbc@s2on` recovered transparently in 5/5. S4 allows either outcome.
6. **Record keeping, not a number.**
   - EXPERIMENT.md is unchanged since the tag: status `PREREGISTERED`, no main-run row in section 12. Sections 11, 14 and
     15 still say the main run has not happened. Yet the main run ran 03:21–06:22 (chain started 01:27:33; first lock
     03:20:56).
   - Section 8 asks for new mlx5 kernel lines to be written by content into section 12. The one new line of H13 (sunny
     FWTracer "Events were lost") is in `mlx5_new_H13.txt` but not yet in EXPERIMENT.md.
7. **Section 9 hold-time estimates** were all met or beaten.
   - Snapshot to snapshot, each hold took 1:48–4:56 min.
   - Summed from lock to exit, the 15 holds took 52.5 min, under the 65 min estimate. The span 03:20:56–06:22:25 is
     longer only because of lock waits between holds.

## Files

- Script: [`qa/recount.py`](../../qa/recount.py)
- Raw data: this folder, `off/`, `rec/`, `fo/`, `forec/`, `s2on/`, `s2off/` (295 trials × 3 files), `hold_H1.out`–`hold_H15.out`,
  `chain.out`, `snap_*`, `mlx5_*`, `fwcmd_*` (not committed; for the Release)
- Pre-registration: tag `prereg/nccl-builtin-v1` (`0ca10eb7`), [`PREREG.txt`](../../PREREG.txt),
  [`predictions.csv`](../../predictions.csv)
