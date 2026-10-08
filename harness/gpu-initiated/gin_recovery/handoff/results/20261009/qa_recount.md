# gin-handoff: independent recount of the main run (2026-10-09)

Independent agent, 2026-10-09. Scope: the main run in this folder (holds H1–H4 and the fill hold), recounted from the raw
per-trial files. The pilot (`../20261009_pilot/`) is not scored; it is read only to check statements about it.

Marks: `[measured]` read from the raw files by [../../qa/recount.py](../../qa/recount.py), `[inferred]` interpretation,
`[source]` read in the library or driver source.

## 1. Method

- **Script.** `python3 qa/recount.py` (from the study folder) prints the whole recount as Markdown. It only reads files.
  Its only git calls are `git rev-parse` and `git cat-file -p prereg/gin-handoff-v1:<path>`, which apply no filter.
- **Read.**
  - Data: every `<stem>_meta.txt`, `_r0.kv`, `_r1.kv`, `_r0.log`, `_r1.log`, `_kill.out` and `_lat_raw.csv.gz` under
    `hf/`, `hfp/`, `hd/`, `hdp/`. Also `hold_*.out`, `chain.out`, `snap_*`, `mlx5_*` and `fwcmd_*`.
  - Study files: `EXPERIMENT.md`, `predictions.csv`, `PREREG.txt`, `cells.sh`, `hold.sh` and `chain.sh`.
  - Older study files: `../harden/cells.sh`, `../harden/run_trial_hd.sh`, `../harden/EXPERIMENT.md` sections 3.1, 3.2
    and 8, and `../s2_close/EXPERIMENT.md` 3.2 (the rule grammar).
  - Column definitions of the older columns: `../scripts/ts2/rows.py`, `../s2_close/rows_extra.py` and
    `../oneway/rows_ow.py`.
  - Source: the driver `../gin_ts2.cu` (kv keys, the p50 formula) and the library tree in the session scratch
    `agent_ts2hf/nccl-src` (log formats).
- **Not read.** `score.py`, `rows_hf.py`, `../harden/score.py`, `../harden/rows_hd.py`, `SCORE.md` and any
  `trials_*.csv`.
- **Columns.** The script parses every column again from the logs and kv files.
  - The kv reader follows rows.py's rule: a value runs, blanks included, up to the next ` <word>=`.
  - The older columns follow their definition files: `transparent_ok`, `rec_init_r0`, `decl_r*`, `teardown_*`,
    `n_fires_*`, `trigger_miss`, `bind_fail`, `killed`, `r0_killed`, `ua_r*` and `ow_mode_r*`.
  - The gin-harden columns follow `../harden/EXPERIMENT.md` 3.1: `hd_on`, `prod`, `n_judged`, `n_copyto`, `n_fwdog`,
    `rs_*`, `rx_phantom`, `ho_*`, `hog_*`, `fault_after_launch_r0_ms`, `decl_after_kill_ms_r0`,
    `release_after_kill_ms_r1` and `async_after_kill_ms_r1`. The clock offset is `clock_offset_ms` (rank 1 − rank 0)
    from rank 0's kv.
  - This study's columns follow EXPERIMENT.md 3.1: `hf_on`, `hf_switch`, `n_hoff_ok_r0`, `hoff_ranks_r0`,
    `n_hoff_keep_r0`, `hoff_why_r0`, `n_surface_r*`, `n_late_copy_r*` and the `ho_*`, `hog_*`, `probe_*` kv keys. Each
    log line is matched with the format string in the library source.
- **Rule evaluator.** I wrote my own AST evaluator for the grammar of `../s2_close/EXPERIMENT.md` 3.2.
  - Supported forms: `count`, `has`, `nonempty`, `median`, `abs` and `per cell:`.
  - Values that read as numbers are floats, blanks are None, and any comparison or arithmetic with None is false.
  - Chained comparisons such as `0 <= x < 500` need every pair to hold.
  - A rule is judged only when the cell key has its planned number of judged trials (section 7).
- **Exclusions.** The script applies section 8 in this order: bind failure, fault not applied, order not applied (the
  GPU-full cells only), firmware overrun. One choice of mine: a blank `rs_fw_overruns_r*` (a killed rank writes no
  statistics) counts as no overrun.
- **Setting checks.** The script applies the section 8 setting checks to the ranks that were not killed.
- **Hold logs.** The script lines up each result line in `hold_*.out` with the trial that `hold.sh` runs at that
  position. It compares build, trial number, r0rc, r1rc, left, left_rules, wall_s and the kill time, and checks that
  the first log time falls inside the hold's snapshot window.

## 2. Integrity

- [measured] Tag `prereg/gin-handoff-v1` resolves to commit `c9efc7b9`.
- [measured] The sha256 of `predictions.csv` is `04ac4a66cb4c2ea64bafb9a412d49f0dbd3fff5d26c36fafeecb361ded88799a` in
  three places: the working tree, the tag's copy, and the hash written in `PREREG.txt`. `PREREG.txt` itself equals the
  tag's copy.
- [measured] EXPERIMENT.md sections 2, 3 (3.1–3.3 included), 7 and 8 are byte-identical to the tag. The whole file is
  byte-identical too (sha256 `77db9595…`).
- [measured] `cells.sh`, `chain.sh`, `../harden/cells.sh` and `../gin_ts2.cu` are identical to the tag. `hold.sh` and
  `../harden/run_trial_hd.sh` match once dotted-quad addresses are masked. The only difference is the repository's
  management-address filter, which stores a placeholder in commits.
- [measured] The md5 of `../gin_ts2.cu` is `1e4fd2f4…`, as stated in EXPERIMENT.md 5. I did not check the deployed
  binaries on the nodes (no cluster access). Every meta line names the bundle `gi-bundle/gin_ts2/<build>` that
  matches its folder.
- [measured] The trial set matches section 7.
  - There are 116 trial files: 86 cell trials and 30 latency runs.
  - Every planned cell key has its planned number of trials. `hf_hogpre_f1_b@hf` has one more (n1–n6).
  - No cell key lies outside the plan.
  - Every meta line carries the arguments that `cells.sh` or `../harden/cells.sh` gives for that trial number: app,
    fault, iterations, bytes, injection time, kill delay, `R0_ENV`, `EXTRA_ENV`, empty `R1_ENV`, `ts=1`,
    `ib_timeout=14`, no mute.
- [measured] The first log line of the main run is at 05:21:11 and the last at 06:17:50. Both come after the
  pre-registration at 05:12:42. The pilot folder is separate and holds 14 trials.

## 3. Exclusions, setting checks and stop criteria

- [measured] One trial is excluded: `hf_hogpre_f1_b_n1@hf` (bind failure). This confirms the stated exclusion.
  - Rank 0's log has a single line, `bind: Address already in use`. Rank 0's exit code is 1 and wall_s is 0.0.
  - Rank 1 waited and exited 7 on its own watchdog (`WATCHDOG: global deadline exceeded`).
  - No kv beyond the first line.
- [measured] The replacement is `hf_hogpre_f1_b_n6`, run in the fill hold with spec `hf:hf_hogpre_f1_b@hf:1:6` from
  `chain.out`.
  - The hold window was 06:17:49–06:17:57. The fill was queued at 06:11:00 and got the lock at 06:17:18.
  - The replacement number is the next free one, as section 8 requires.
  - 1 refill out of a plan of 5 is under the 50% limit.
- [measured] No other trial is excluded.
  - Every hook cell fired on the hooked rank(s), and no trigger was missed.
  - Every rank-1 kill cell has a kill time, and `hd_rxdeath_b` has `rank=0` kills.
  - In the GPU-full cells, rank 0's hook fired 583.1–1147.2 ms after the GIN launch (range over the 20 judged
    trials). The GPU-filling launch came 0.2–0.3 ms after the GIN launch, so every fault fell inside the 3 s window.
  - No firmware watchdog line appears, and no `rs_fw_overruns` is above 0.
- [measured] Every judged cell key has exactly its planned number of judged trials.
- [measured] Setting checks: all 115 judged trials pass.
  - `hf`: the gin-harden start line with `production=0`, the `handoff=1` line, the transparent recovery ON line, the
    abort-word line and `oneway=1`. `shrink_handoff=1` everywhere except rank 0 of `hf_shrinkoff_b` and
    `hf_shrinkdc_b`, where it is 0.
  - `hd`: the same lines and no `handoff` line.
  - `hfp`, `hdp`: no start line at WARN, `rs_api=1`, `rs_contexts>=1`.
  - No test-switch or mute line in any `hf` or `hd` trial.
  - `left_rules=0` and `left=0` in every trial.
- [measured] Hold logs against the trial files: all 116 result lines match their trials on every field compared. No
  mismatch.
- [measured] Stop criteria, holds H1–H4 and fill (each compared before and after the hold):
  - New mlx5 kernel lines: 0.
  - mlx5 command-error lines: rain 2 → 2, sunny 0 → 0.
  - rain firmware-command failures: 31 → 31.
  - `gin-harden-` iptables rules: 0 → 0.
  - No STOP file.
  - No exit code 139 and no illegal-address or launch-failure text in any of the 116 trials' logs or kv.

## 4. Predictions

Verdict counts: **24 hold, 0 fail, 0 insufficient data** (24 predictions).

All verdicts are `[measured]`. "n" is the number of judged trials and "hits" the trials where the rule's inner
expression is true. No trial misses any count rule.

| id | what was predicted | cell key | n | hits | rule | verdict |
|---|---|---|--:|--:|---|---|
| S1 | The aborting shrink that excludes the killed rank returns a 1-rank communicator; its allreduce is right and it shows no async error | `hd_shrink_b@hf` | 10 | 10 | ≥ 9 | holds |
| S2 | One hand-off line naming rank 1 only, no keep line; the parent still reports its GIN error after the shrink | `hd_shrink_b@hf` | 10 | 10 | ≥ 9 | holds |
| S3 | The shrink returns within 500 ms; the child is destroyed and the parent aborted without error | `hd_shrink_b@hf` | 10 | 10 | ≥ 9 | holds |
| S4 | Control: with gin-harden's library the same shrink fails within 100 ms with the parent's GIN error | `hd_shrink_b@hd` | 5 | 5 | ≥ 4 | holds |
| S5 | Control: with the switch off the shrink fails and the keep line names the switch | `hf_shrinkoff_b@hf` | 5 | 5 | ≥ 4 | holds |
| S6 | The production build hands off the same way; the hand-off line does not show at WARN | `hd_shrink_b@hfp` | 5 | 5 | ≥ 4 | holds |
| S7 | After the watchdog raised the error without a peer, the shrink excluding live rank 1 keeps the stock answer ("without a peer") | `hf_hog_f1_b@hf` | 5 | 5 | ≥ 4 | holds |
| S8 | Control (switch off): destroying the devComm first lets the stock check pass (1-rank communicator, no hand-off or keep line) | `hf_shrinkdc_b@hf` | 5 | 5 | ≥ 4 | holds |
| G1 | With gin-harden's calls between the two launches, rank 0's device-state copy misses its 2 s bound and nothing is recovered | `hf_hog_f1_b@hf` | 5 | 5 | ≥ 4 | holds |
| G2 | In that order no GPU-filling block starts next to the GIN kernel on either rank, no probe copy finishes within 200 ms, and all finish by the end | `hf_hog_f1_b@hf` | 5 | 5 | ≥ 4 | holds |
| G3 | One block smaller, the same order still starts no block and the failure returns | `hf_hogslack_f1_b@hf` | 5 | 5 | ≥ 4 | holds |
| G4 | With nothing between the launches the full grid starts (all but at most one block), the probes finish within 200 ms, and recovery is transparent without a copy timeout | `hf_hogpre_f1_b@hf` | 5 | 5 | ≥ 4 | holds |
| G5 | With nothing between the launches and one block fewer, every block starts at once, the probes finish, and recovery is transparent | `hf_hogpreslack_f1_b@hf` | 5 | 5 | ≥ 4 | holds |
| R1 | Recovery cells stay transparent (per cell) | `f1_b@hf`, `f3_b@hf`, `bidirf_sym_b@hf` | 5 each | 5 each | = 5 each | holds |
| R2 | A kill is declined with a death cause within 2 s and the survivor's abort returns | `f4_b@hf` | 5 | 5 | = 5 | holds |
| R3 | A remote access error is declined; rank 1's wait ends with an error and no wait succeeds without its signal; rank 1's abort returns within 5 s | `f2rel_b@hf` | 5 | 5 | = 5 | holds |
| R4 | A receive-only rank judges its killed sender dead; the wait and the async error show within 2 s; the abort returns | `hd_rxdeath_b@hf` | 5 | 5 | ≥ 4 | holds |
| R5 | The production build declines the killed peer within 2 s with a death cause and counts one death | `hdp_kill_b@hfp` | 5 | 5 | = 5 | holds |
| R6 | The statistics API counts 1 round and 1 recovery on each rank and no decline | `f1_b@hf` | 5 | 5 | = 5 | holds |
| R7 | After the kill the statistics API counts 1 death and 1 decline | `f4_b@hf` | 5 | 5 | = 5 | holds |
| P1 | 4 KiB p50, this study's production build against gin-harden's: medians 10.69 vs 10.69 µs, difference 0.00 | `lat_4k@hfp` vs `@hdp` | 5 / 5 | – | ≤ 0.40 µs | holds |
| P2 | 256 KiB p50, the same two builds: medians 38.91 vs 38.88 µs, difference 0.03 | `lat_256k@hfp` vs `@hdp` | 5 / 5 | – | ≤ 0.30 µs | holds |
| P3 | 4 KiB p50, this study's production build against gin-harden's research build: medians 10.69 vs 10.69 µs, difference 0.00 | `lat_4k@hfp` vs `@hd` | 5 / 5 | – | ≤ 0.40 µs | holds |
| P4 | 256 KiB p50, the same two builds: medians 38.91 vs 38.88 µs, difference 0.03 | `lat_256k@hfp` vs `@hd` | 5 / 5 | – | ≤ 0.30 µs | holds |

[measured] The script produces every column name that appears in the rules. None of the rules evaluated a missing
column as None.

## 5. Key numbers

All numbers are `[measured]` and come from judged trials only. Each range says what it is a range of.

**Shrink (rank 0).** The shrink and allreduce columns are ranges over the judged trials of each cell key.

| cell key | n | shrink result | shrink time | 1-rank allreduce (done / right) | new communicator async error | parent async error after the shrink | hand-off / keep lines | child destroy | parent abort |
|---|--:|---|---|---|---|---|---|---|---|
| `hd_shrink_b@hf` | 10 | no error 10/10 | 17.0–17.3 ms | 10 / 10 (check 0.3 ms) | none 10/10 | `ncclRemoteError` 10/10 | 10 / 0 | 502.0–502.8 ms | no error 10/10 |
| `hd_shrink_b@hfp` | 5 | no error 5/5 | 16.9–17.3 ms | 5 / 5 (0.3 ms) | none 5/5 | `ncclRemoteError` 5/5 | 0 / 0 at WARN | 502.4–502.9 ms | no error 5/5 |
| `hd_shrink_b@hd` (gin-harden control) | 5 | `ncclRemoteError` 5/5 | 0.0 ms | no communicator | – | not logged by this driver | 0 / 0 | – | no error 5/5 |
| `hf_shrinkoff_b@hf` (switch off) | 5 | `ncclRemoteError` 5/5 | 0.0 ms | no communicator | – | `ncclRemoteError` 5/5 | 0 / 5 (reason `NCCL_GIN_SHRINK_HANDOFF=0`) | – | no error 5/5 |
| `hf_shrinkdc_b@hf` (devComm destroyed first) | 5 | no error 5/5 | 16.4–16.9 ms | 5 / 5 (0.3 ms) | none 5/5 | no error 5/5 | 0 / 0 | 503.1–503.2 ms | no error 5/5 |
| `hf_hog_f1_b@hf` (live rank 1 excluded) | 5 | `ncclRemoteError` 5/5 | 0.0 ms | no communicator | – | `ncclRemoteError` 5/5 | 0 / 5 (reason "a GIN error was raised without a peer") | – | no error 5/5 |

- The hand-off line in `hd_shrink_b@hf` names rank 1 only, in 10/10 trials.
- Successful shrinks, pooled over the three cell keys that succeed: 16.4–17.3 ms (range over 20 trials).
- In `hf_shrinkdc_b@hf`, the devComm destroy took 10.8–11.1 ms with no error (range over 5 trials), and the driver
  skipped the final signal read (5/5).
- The child communicator always had 1 rank. The allreduce result was right in every successful shrink: 20/20 across
  `@hf`, `@hfp` and the devComm-first cell.

**Decline after the kill.** Rank 0's first decline minus the rank-1 kill, with the kill moved to rank 0's clock. Ranges
are over the judged trials of each cell key.

| cell key | n | decline cause | decline after the kill |
|---|--:|---|---|
| `hd_shrink_b@hf` | 10 | the peer's socket shows FIN, 10/10 | 1.53–1.75 ms |
| `hd_shrink_b@hfp` | 5 | FIN 5/5 | 1.61–1.70 ms |
| `hd_shrink_b@hd` | 5 | FIN 5/5 | 1.57–1.75 ms |
| `hf_shrinkoff_b@hf` | 5 | FIN 5/5 | 1.61–1.71 ms |
| `hf_shrinkdc_b@hf` | 5 | FIN 5/5 | 1.57–1.86 ms |
| `f4_b@hf` | 5 | FIN 5/5 | 1.58–1.67 ms |
| `hdp_kill_b@hfp` | 5 | FIN 5/5 | 1.51–1.60 ms |

- Pooled over the seven kill cell keys (40 trials): 1.51–1.86 ms.
- Receive-only rank, `hd_rxdeath_b@hf` (rank 0 killed, n=5): rank 1 judged rank 0 dead in 5/5. Rank 1's wait was
  released 19.5–21.7 ms after the kill and the async error showed 1.9–2.2 ms after the kill (ranges over the 5
  trials).

**GPU-full 2 × 2.** Rank 0 is rain (48 SMs × 4 blocks = 192); rank 1 is sunny (48 × 6 = 288). Each cell has n=5 and
8 probe copies per rank in every trial. The probes were issued 20.0–20.1 ms after the GPU-filling launch (range over
the 40 rank-trials).

| cell key (calls between the launches, grid) | blocks started at the probe (r0 / r1) | blocks started by the end | probe copies done within 200 ms (r0 / r1) | probe copies done at the end | copy timeout lines (r0 / r1) | outcome |
|---|---|---|---|---|---|---|
| `hf_hog_f1_b` (gin-harden's calls, full) | 0/192 / 0/288 in 5/5 | all, 5/5 | 0/8 / 0/8 in 5/5 | 8/8 / 8/8 in 5/5 | 1 / 1 in 5/5 | rank 0 declined in 5/5, transparent 0/5 |
| `hf_hogslack_f1_b` (gin-harden's calls, one fewer) | 0/191 / 0/287 in 5/5 | all, 5/5 | 0/8 / 0/8 in 5/5 | 8/8 / 8/8 in 5/5 | 1 / 1 in 5/5 | rank 0 declined in 5/5, transparent 0/5 |
| `hf_hogpre_f1_b` (nothing between, full) | 191/192 / 287/288 in 5/5 | all, 5/5 | 8/8 / 8/8 in 5/5 | 8/8 / 8/8 | 0 / 0 | recovered (rank 0 initiator round) and transparent 5/5, no decline |
| `hf_hogpreslack_f1_b` (nothing between, one fewer) | 191/191 / 287/287 in 5/5 | all, 5/5 | 8/8 / 8/8 in 5/5 | 8/8 / 8/8 | 0 / 0 | recovered and transparent 5/5, no decline |

- Start spread, meaning the last block start minus the first, ranges over the 5 trials of each cell:
  - gin-harden order, both grid sizes: 0.0 ms on both ranks. All blocks started together.
  - `hf_hogpre_f1_b`: rain 1816.4–1816.6 ms, sunny 1801.4–1801.6 ms. The GIN kernel times were rain 1816.9–1817.1 ms
    and sunny 1801.9–1802.4 ms, so the one block left over started when the GIN kernel ended.
  - `hf_hogpreslack_f1_b`: 0.0 ms.
- Slowest probe copy among those that finished within 200 ms, over both ranks and the 5 trials of each cell:
  0.033–0.080 ms in `hf_hogpre_f1_b` and 0.034–0.104 ms in `hf_hogpreslack_f1_b`.
- [inferred] In the gin-harden-order cells the first GPU-filling block started when the GIN kernel ended. I took each
  block's start relative to the host clock, subtracted the node's offset from the at-once cell, added the launch
  delay, and subtracted the GIN kernel time. The result is −1.8 to −0.2 ms in `hf_hog_f1_b` and −1.6 to 0.0 ms in
  `hf_hogslack_f1_b` (10 rank-trials each).
- What rank 0 logged in the gin-harden-order cells (10 trials):
  - The watchdog surfaced the fault 11.8–461.9 ms after the hook fired. The reason in 10/10 was "fault records are
    queued and the recovery helper is not running".
  - The copy timeout line came 915.0–1463.0 ms after the hook fired.
  - The decline came 1.24–1.30 ms after the copy timeout line, with the reason "the watchdog surfaced a fault
    earlier".
  - Rank 1 declined with "the peer declined" in 10/10 and never surfaced.

**Latency p50 (rank 0, 3000 iterations per run, hold H4, n=5 runs per cell key).** The per-run values come from the kv
files. The script also recomputed each p50 from the raw latencies (`_lat_raw.csv.gz`, 3000 values each) with the
driver's formula; every recomputed value equals its kv value.

| cell key | p50 per run (µs) | median of the runs | range over the runs |
|---|---|--:|---|
| `lat_4k@hfp` | 10.69, 10.69, 10.72, 10.72, 10.69 | 10.69 | 10.69–10.72 |
| `lat_4k@hdp` | 10.69 × 5 | 10.69 | 10.69 |
| `lat_4k@hd` | 10.69, 10.69, 10.69, 10.72, 10.72 | 10.69 | 10.69–10.72 |
| `lat_256k@hfp` | 38.88, 38.91, 38.91, 38.91, 38.91 | 38.91 | 38.88–38.91 |
| `lat_256k@hdp` | 38.91, 38.88, 38.88, 38.88, 38.91 | 38.88 | 38.88–38.91 |
| `lat_256k@hd` | 38.88, 38.88, 38.88, 38.91, 38.88 | 38.88 | 38.88–38.91 |

Median differences, `hfp` minus the baseline: at 4 KiB +0.00 µs against both `hdp` and `hd`; at 256 KiB +0.03 µs
against both. All 90 000 raw latencies are multiples of 32 ns, so 0.03 µs is one timer step.

**Regression cells (n=5 each).**

| cell key | outcome |
|---|---|
| `f1_b@hf` | transparent 5/5. Statistics: rank 0 counted 1 round, 1 recovery and 0 declines in 5/5; rank 1 counted 1 round and 1 recovery in 5/5 |
| `f3_b@hf` | transparent 5/5 (rank 0 ran the initiator round) |
| `bidirf_sym_b@hf` | transparent 5/5. One rank-0 initiator round in all 5 trials, plus one on rank 1 in 1 trial |
| `f4_b@hf` | declined because the peer's socket showed FIN, 5/5, 1.58–1.67 ms after the kill. Statistics: 1 death and 1 decline in 5/5. Abort: no error |
| `f2rel_b@hf` | rank 0 declined "class REM_ACCESS is not recoverable" in 5/5. Rank 1: `device_error`, wait rc `ncclRemoteError`, 0 waits passed without their signal, abort with no error in 773.3–796.7 ms (range over the 5 trials) |
| `hd_rxdeath_b@hf` | rank 1 judged rank 0 dead, wait rc `ncclRemoteError` and abort with no error, 5/5 (times above) |
| `hdp_kill_b@hfp` | declined because the peer's socket showed FIN, 5/5, 1.51–1.60 ms after the kill. Statistics: 1 death and 1 decline in 5/5. Abort: no error |

## 6. Disagreements and observations

**Disagreements with the hold logs.** None `[measured]`.
- All 116 result lines match their trial files on build, trial number, r0rc, r1rc, left, left_rules, wall_s and kill
  time.
- Every first log time lies inside its hold's window.
- Each hold's trial count and order match `hold.sh`.

**Disagreements with EXPERIMENT.md.** None changes a verdict.

1. `[measured]` **EXPERIMENT.md has not recorded the main run yet.** The file is byte-identical to the tag.
   - The status is still `PREREGISTERED`.
   - The section 11 boxes for the main run are unchecked.
   - Section 12 has no rows for H1–H4 or the fill hold, and sections 14 and 15 are empty.
   - The bind-failure exclusion and the fill hold (n6) appear nowhere in the document. The exclusion follows the
     section 8 rule, so it needs a run-log row, not a section 13 deviation `[inferred]`.
2. `[measured]` **The node clock offset in `hog_first_start_rel_ms` drifts.** Section 3.1 (fixed) calls it a constant
   per-node clock difference: rain 3358.6–3358.7 ms and sunny 3672.6 ms in the pilot at 05:05. In the main run the
   same quantity, read where the blocks started at once, was:
   - rain 3361.8–3362.2 ms and sunny 3692.7–3693.5 ms in H2 (05:42–05:45; 9 trials: `hf_hogpre_f1_b` n2–n5 and
     `hf_hogpreslack_f1_b` n1–n5);
   - rain 3372.8 ms and sunny 3699.2 ms in the fill trial at 06:17.

   Within H2 it rose by 0.1 ms per trial on rain, so it is not constant across the session. No rule uses this column;
   the inferred block-start calculation in section 5 uses the H2 offset for H2 trials.
3. `[measured]` **The decline reason in the gin-harden-order GPU-full cells.** Section 3 (fixed) says of the pilot that
   the recovery "was declined by the copy timeout" (복사 시간 초과로 거절됐다).
   - Pilot and main run agree on the order of events. The copy timeout line ("...; the round declines") comes first.
     Rank 0's decline line follows 1.24–1.30 ms later (main run, 10 trials).
   - The reason that decline line records is "the watchdog surfaced a fault earlier", in the pilot and in 10/10
     main-run trials.
   - The description is right about the trigger. The logged reason differs. G1 is unaffected: it checks for a copy
     timeout line and no recovery, not for the reason text.

**Other observations** (not disagreements).

4. `[measured]` A new sunny mlx5 kernel line appeared between H3 and H4: `mlx5_fw_tracer_handle_traces ... FWTracer:
   Events were lost`. It was absent at H3's after-snapshot (05:57:03) and present at H4's before-snapshot (06:08:57).
   - It lies outside every hold window.
   - It is not a command-error line, and the command-error counts stayed 0.
   - `hold.sh` compares only within a hold, so it does not report this line.
5. `[measured]` Every gin-harden-order GPU-full trial (10/10) logs "GIN/TS: cannot set the device error state" on at
   least one rank, and later "the gates to declined rank N failed after the late copy".
   - `[source]` In `gdakiTsDecline` the device sticky-state write is itself a device copy (`gdakiTsZeroDev`). While
     copies are blocked it fails, and `failPending` writes the gates once the late copy completes.
   - Rank 0 of `hf_hog_f1_b` n2 and n5 lacks the line. Its late copy completed 0.008–0.009 ms after the decline.
   - EXPERIMENT.md does not mention this line. No rule depends on it.
6. `[inferred]` Hold H2 took 3 min 4 s against an estimate of 3 min. The bind-failure trial accounts for most of the
   difference: rank 0 exited at once, while the runner waited for rank 1 to reach its own watchdog.
7. `[measured]` I checked the pilot statements in EXPERIMENT.md sections 3 and 12 against `../20261009_pilot/`, and
   they agree:
   - 14 trials, hold 05:04:28–05:05:52, no exclusion, every setting check passes.
   - Shrink 17.3, 17.2 and 16.5 ms; child destroy 502.0 ms; devComm destroy 11.1 ms, after which the parent's async
     error reads "no error".
   - Decline 1.54–1.64 ms after the kill (n=6).
   - Progress 195–199/400 in the shrink cells and 41/120 in the gin-harden-order GPU-full cells.
   - Blocks 191/192 and 287/288 at the probe, with spreads of 1816.9 and 1801.9 ms against GIN kernel times of 1817.5
     and 1802.6 ms.
   - Probe copies finished within 0.08 ms.
   - 4 KiB p50 of 10.69 µs on all three builds.

## 7. Limits of this recount

- The deployed binaries were not re-checked on the nodes; the recount trusts `deploy_check.txt` and the bundle path in
  each meta line.
- I re-implemented the gin-harden and gin-handoff columns from the summaries in EXPERIMENT.md 3.1 and the log formats
  in the source, without reading `rows_hd.py` or `rows_hf.py`. Where a summary left room I made three choices:
  - the setting checks skip the killed rank;
  - `hfp` and `hdp` statistics are checked on the surviving ranks;
  - a blank `rs_fw_overruns` (a killed rank) is no overrun.

  None of these choices touches a trial whose verdict could change.
- `SCORE.md` was not compared, by rule.
