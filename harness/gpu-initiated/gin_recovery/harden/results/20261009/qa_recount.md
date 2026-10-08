# gin-harden: independent recount of the main run (2026-10-09)

An agent other than the scorer recounted the main run (`results/20261009/`) from the raw per-trial files and checked the
pre-registration. The script is [../../qa/recount.py](../../qa/recount.py). It reads only and prints the whole report
(`python3 -B qa/recount.py` from the study folder, 349 lines). All numbers below are `[measured]` from that output unless
marked `[inferred]`.

**Result.** 52 predictions: 49 hold, 3 are refuted (A2, C1, P4), 0 have insufficient data. The pre-registration is
intact. The hold logs and the trial files agree line for line. The four port-bind exclusions and their single fill hold
are confirmed, and no other trial meets a section 8 exclusion.

## 1. Method

- **Not read or run:** `score.py`, `rows_hd.py`, `results/20261009/SCORE.md`, any `trials_*.csv`, `../s2_close/score.py`.
- **Read:** the per-trial files `<build>/<cell>_n<k>_{meta.txt,r0.kv,r1.kv,r0.log,r1.log,kill.out,mute.out,lat_raw.csv.gz}`,
  `hold_*.out`, `chain.out`, the `snap_*`, `mlx5_*` and `fwcmd_*` snapshots, `EXPERIMENT.md`, `predictions.csv`,
  `PREREG.txt`, `cells.sh`, `run_trial_hd.sh`, `hold.sh`, `chain.sh` and `../gin_ts2.cu`. The library source was read only
  for the meaning of two log fields.
- **Columns.** Every column is parsed again in `recount.py`.
  - Columns of `rows.py`, `rows_extra.py`, `rows_pc.py` and `rows_ow.py`: EXPERIMENT.md 3.1 says their definitions are
    those files' own. The definitions were taken from those files' headers and code, then implemented again.
  - New columns: implemented from the 3.1 table and the 3.1 log formats only.
- **Evaluator.** The script has its own evaluator of the 3.2 grammar of `../s2_close/EXPERIMENT.md`.
  - `count(E)` counts the scored trials of the cell key for which `E` holds.
  - An empty cell is a value whose every comparison is false and whose arithmetic stays empty.
  - It also covers `has`, `nonempty`, `median` over a cell key, `abs` and `per cell:`.
  - "Insufficient data" applies when a referenced cell key has fewer scored trials than planned.
  - No column name in any acceptance rule was left undefined.
- **Exclusions.** Section 8 is applied as written, in this order:
  1. `bind_fail`.
  2. Fault not applied: hook fires, `trigger_miss`, `killed`, `r0_killed`, `mute_applied`.
  3. Order not applied: `ow_r0in_f1r1_b`, `rc_mutekill_b`, `ow_kill0_b`, `hd_rround_f1_b` (both builds) and
     `hd_repost_f1_b`.
  4. Firmware overrun: all `hd` and `hdp` trials except `hd_fwslow_f1_b@hd`.
  5. The 50% fill rule.

  `hd_ref2_f1_b` is exempt from the rank 0 hook-fire rule. EXPERIMENT.md section 3 ("pilot 뒤 확정", inside the tagged
  text) dropped that requirement. All 10 of its trials have 0 hook fires `[measured]`, so without the exemption the cell
  would be "insufficient data".
- **Choices where 3.1 leaves room.** None of them changes a verdict on these data.
  - `n_fwdog_r*` counts only the `firmware command phase <p> has run <x> ms` line. Each slow-firmware trial also has a
    second watchdog line, `a firmware command phase exceeded ...`. Counting both gives 2 instead of 1.
  - `refusal_span_ms_r*` uses the earliest refusal of either kind. Each cell has refusals of only one kind.
  - `mute_applied` is 1 when `mute.out` has `mute_on_mono_ms` and no `mute_skipped`.
  - `close1_*` and `n_dead_r*` take only close lines that carry `liveness=`, as `rows_ow.py` does.
  - `r1close_after_q4_ms` takes rank 1's first close line of any form.
- **Latency.** Each run's kv `lat_p50_us` was checked against the 3000-value `lat_raw.csv.gz` of that run. Both the
  driver's rule (`sorted[round(0.5(n-1))]`) and the plain median agree with the kv value in all 30 runs.

## 2. Pre-registration integrity

| Check | Result |
|---|---|
| Tag `prereg/gin-harden-v1` | commit `692ff591` (2026-10-09 03:42:57 +0900); the worktree HEAD is the same commit |
| `predictions.csv` sha256: working tree, tag blob, `PREREG.txt` | all `0e9e3192d74ba9777e78cabbc0b822290e6db07ae83e930d41a066786096b9e0`, 52 rows: PASS |
| `PREREG.txt` | identical to the tag |
| EXPERIMENT.md sections 2, 3, 7, 8 | byte-identical to the tag (2 686, 21 073, 3 934, 6 802 bytes). The whole file is identical to the tag |
| `cells.sh`, `chain.sh` | identical to the tag |
| `run_trial_hd.sh`, `hold.sh` | one differing line each, the `SUNNY_SSH` default that the repository's address clean filter rewrites. Compared without running the filter |
| Trial set against section 7 | 38 cell keys run = 38 planned, none unplanned. Scored: 213 cell trials and 30 latency runs = plan |
| Main run after the tag | trial meta files written 03:51:36–06:11:47; tag commit 03:42:57 |
| Cell conditions | the meta of every trial (env, inject, iters, bytes, kill delay, mute, IB timeout) matches `cells.sh` and section 7 |

## 3. Trial set, exclusions, fill

- 247 trial files. Excluded: 4, all `bind_fail` (rank 0 log `bind: Address already in use`, `r0rc=1`, `wall_s=0.0`):

  | cell key | excluded trial | replacement | hold |
  |---|---|---|---|
  | `hd_copystall_f1_b@hd` | n2 | n11 | fill |
  | `hd_shrink_b@hd` | n2 | n11 | fill |
  | `pc_dual_f1c0_r1c2_b@hd` | n5 | n6 | fill |
  | `hd_fwslow_f1_b@ow` | n4 | n6 | fill |

- **Fill hold.** `chain.out` records it at 06:03:30–06:11:48. It held the lock and ran 06:11:14–06:11:47, with 4 trials.
  Each cell key filled 1 trial (10% or 20% of its plan, under the 50% bound). No other trial meets any exclusion rule.
  Every cell key has exactly its planned number of scored trials.
- `hd_shrink_b@hd` n2 has a `kill.out`, because the runner killed rank 1 while it waited at the rendezvous. That gives
  `killed=1`, but the bind rule excludes the trial first `[measured]`.
- **Configuration checks** (section 8 "설정 확인"): 0 failures in 247 trials. The checks cover:
  - start lines by build;
  - old and new test-switch lines by cell;
  - mute lines by cell;
  - the hook context of `ow_r0in_f1r1_b`;
  - `left_rules`.
- **Stop criteria.**
  - No rc 139 and no illegal-address or launch-failure text in any log or kv.
  - `left=0` and `left_rules=0` in all trials.
  - No STOP files.
  - Every hold rc=0, with iptables cleanup `deleted=0 left=0` (9 of 9).
  - Every hold printed `new mlx5 kernel lines ... 0`.
  - The rain firmware-command failure sum was 31 before and after every hold.

## 4. Per-prediction verdicts

n is the number of scored trials (latency: runs) of the cell key. Hits is the number of trials meeting the acceptance
rule.

| id | predicted | cell | n | hits | verdict |
|---|---|---|--:|--:|---|
| A1 | after rank 1's kill, rank 0's waits end with an error before the shrink; no wait succeeds without its signal | `hd_shrink_b@hd` | 10 | 10 | holds |
| A2 | the aborting shrink returns a working 1-rank communicator | `hd_shrink_b@hd` | 10 | 0 | **refuted** |
| A3 | control (gin-oneway library): the old kernel still runs at the shrink | `hd_shrink_b@ow2` | 5 | 5 | holds |
| A4 | control: the final abort releases the receiver with success and no signal, or the shrink does not return | `hd_shrink_b@ow2` | 5 | 5 | holds |
| A5 | remote access error: the receiver's wait ends with an error at its decline, no signal-less success, abort within 5 s | `f2rel_b@hd` | 5 | 5 | holds |
| B1 | one refused re-dial does not make the live peer dead | `hd_ref1_f1_b@hd` | 10 | 10 | holds |
| B2 | the next re-dial reconnects and the 12 s fault is transparent | `hd_ref1_f1_b@hd` | 10 | 10 | holds |
| B3 | two refusals at least 1 s apart make the peer dead; the decline names ECONNREFUSED; waits released as peer-dead | `hd_ref2_f1_b@hd` | 10 | 10 | holds |
| B4 | a wrong-nonce HELLO is refused and not accepted, and nobody is dead | `hd_nonce_f1_b@hd` | 10 | 10 | holds |
| B5 | the next re-dial reconnects within 2 s after the mute and the fault is transparent | `hd_nonce_f1_b@hd` | 10 | 10 | holds |
| B6 | a reset inside the round cancels it without a death; one retried round recovers transparently | `hd_rround_f1_b@hd` | 10 | 10 | holds |
| B7 | control: gin-oneway declines because the REQ cannot be sent | `hd_rround_f1_b@ow` | 5 | 5 | holds |
| B8 | the receive-only rank judges the killed sender dead; its wait ends with an error within 2 s | `hd_rxdeath_b@hd` | 10 | 10 | holds |
| B9 | the receive-only rank gets the async error within 2 s; its abort returns | `hd_rxdeath_b@hd` | 10 | 10 | holds |
| B10 | control: the gin-oneway receive-only rank waits until its own bound (timeout, at least 10 s after the kill) | `hd_rxdeath_b@ow` | 5 | 5 | holds |
| B11 | an orderly teardown's FIN is logged as "left", never as a death | `f1_b`, `f3_b`, `rc_mute8_f1_b` (`@hd`) | 5 each | 5, 5, 5 | holds |
| C1 | recovery stays transparent while every SM is held by an application kernel; no copy misses its bound | `hd_hog_f1_b@hd` | 10 | 0 | **refuted** |
| C2 | an 8 s firmware phase trips the watchdog at 3.0–3.5 s; waits released (fw-watchdog); error surfaced | `hd_fwslow_f1_b@hd` | 10 | 10 | holds |
| C3 | rank 0's abort returns within 6 s with the helper detached | `hd_fwslow_f1_b@hd` | 10 | 10 | holds |
| C4 | rank 1 declines and its abort returns | `hd_fwslow_f1_b@hd` | 10 | 10 | holds |
| C5 | control: gin-oneway waits out the 8 s and recovers | `hd_fwslow_f1_b@ow` | 5 | 5 | holds |
| C6 | a 4 s stalled copy misses the 2 s bound; decline within 3 s of the first classification; both waits end with an error | `hd_copystall_f1_b@hd` | 10 | 10 | holds |
| C7 | both aborts return | `hd_copystall_f1_b@hd` | 10 | 10 | holds |
| D1 | rank 0, as initiator, rejects the 2nd of 4 re-post plans: nothing is re-posted and no rank logs a recovery | `hd_repost_f1_b@hd` | 10 | 10 | holds |
| D2 | both ranks decline | `hd_repost_f1_b@hd` | 10 | 10 | holds |
| E1 | of five faults, three recover and the fourth escalates (cap 3 rounds in 10 s) | `hd_esc_f1_b@hd` | 10 | 10 | holds |
| E2 | rank 0 surfaces the error; rank 1 declines on the peer's FAIL | `hd_esc_f1_b@hd` | 10 | 10 | holds |
| E3 | control: gin-oneway recovers all five | `hd_esc_f1_b@ow` | 5 | 5 | holds |
| E4 | the stats API counts 1 round, 1 recovery, 0 declines on each rank | `f1_b@hd` | 5 | 5 | holds |
| E5 | after a kill the stats API counts 1 death and 1 decline | `f4_b@hd` | 5 | 5 | holds |
| R1 | the replication cells stay transparent | `f1_b`, `f3_b`, `bidirf_sym_b`, `rc_mute8_f1_b` | 5 each | 5, 5, 5, 5 | holds |
| R2 | after a peer QP error every QP is RTS at teardown | `f3_b@hd` | 5 | 5 | holds |
| R3 | a kill without a mute is declined with a death cause; the abort returns | `f4_b@hd` | 5 | 5 | holds |
| R4 | that decline comes within 2 s after the kill | `f4_b@hd` | 5 | 5 | holds |
| R5 | pair-check behaviour is unchanged | `pc_dual_f1c0_r1c2_b@hd` | 5 | 5 | holds |
| R6 | symmetric 8 s mute: one reconnect per rank within 1.5 s, no death | `rc_mute8_f1_b@hd` | 5 | 5 | holds |
| R7 | rank 1 killed during a mute: dead after two refusals at least 1 s apart, never "unknown" | `rc_mutekill_b@hd` | 5 | 5 | holds |
| R8 | one-way outage with the reset at rank 0: unknown, no death, reconnect within 1.5 s, transparent | `ow_r1in_f1_b@hd` | 5 | 5 | holds |
| R9 | mirror outage: rank 1 keeps rank 0 unknown, waits for the reconnect, transparent | `ow_r0in_f1r1_b@hd` | 5 | 5 | holds |
| R10 | rank 0 killed during a mute: two probe refusals at least 1 s apart after the mute; dead; ECONNREFUSED | `ow_kill0_b@hd` | 5 | 5 | holds |
| R11 | a refused reconnect HELLO, a reconnect within 2 s, transparent | `ow_hello_f1_b@hd` | 5 | 5 | holds |
| R12 | the remote access error is declined as not recoverable | `f2rel_b@hd` | 5 | 5 | holds |
| P1 | 4 KiB: production build and gin-oneway differ by at most 0.40 µs | `lat_4k@hdp`, `@ow` | 5+5 | 10.72 vs 10.59: 0.13 µs | holds |
| P2 | 256 KiB: they differ by at most 0.30 µs | `lat_256k@hdp`, `@ow` | 5+5 | 38.91 vs 38.91: 0.00 µs | holds |
| P3 | 4 KiB: production is 0.10–1.00 µs slower than pristine NCCL | `lat_4k@hdp`, `@stk` | 5+5 | 10.72 − 9.76 = 0.96 µs | holds |
| P4 | 256 KiB: production is 0.10–1.00 µs slower than pristine NCCL | `lat_256k@hdp`, `@stk` | 5+5 | 38.91 − 37.86 = 1.05 µs | **refuted** |
| P5 | production: a killed peer is declined with a death cause within 2 s; 1 death counted; the abort returns | `hdp_kill_b@hdp` | 5 | 5 | holds |
| P6 | production: after an 8 s iptables outage, reconnect with no death, no decline, transparent | `hdp_mute_b@hdp` | 5 | 5 | holds |
| P7 | production: no informational recovery line at WARN while recovery is on | `hdp_kill_b`, `hdp_mute_b` | 5 each | 5, 5 | holds |
| T1 | IB timeout 20: the first classification (RETRY_EXC) comes 50–70 s after the hook | `to20_f3_b@hd` | 5 | 5 | holds |
| T2 | the blocking flush holds and one round of at most 100 ms recovers transparently | `to20_f3_b@hd` | 5 | 5 | holds |
| T3 | with an 8 s device-side timeout the flush returns a timeout; no recovery or decline; a timeout dump | `to20_f3_t@hd` | 3 | 3 | holds |

**What failed in the refuted ones** (each conjunct counted on its own):
- **Shrink returns a 1-rank communicator (A2).**
  - `ho_shrink_rc == "no error"` 0/10, `ho_newcomm_nranks == 1` 0/10, `ho_check_ok == 1` 0/10.
  - The shrink returned `remote process exited or there was a network error` after 0.0 ms in all 10, with no new
    communicator. The pilot (n=1) showed the same, and EXPERIMENT.md section 3 expected this failure.
- **Transparent recovery with the GPU full (C1).**
  - The cell condition held 10/10: the filler kernel launched (`cudaSuccess`, blocks ≥ SMs) and the hook fired inside its
    3 s window.
  - `rec_init_r0 == 1` 0/10, `transparent_ok == 1` 0/10, `rs_copy_timeouts_r0 == 0` 0/10.
  - The pilot flagged this as likely to fail.
- **256 KiB latency against pristine NCCL (P4).**
  - Medians of the 5 per-run p50 values: production 38.91 µs, pristine 37.86 µs. The difference is 1.05 µs (1.056 µs from
    the raw files), above the 1.00 µs bound.
  - At 256 KiB the production build equals gin-oneway: both medians are 38.91 µs.
  - This failure was not anticipated.

## 5. Key numbers

Each range is the min–max over the scored trials of the named cell key, one value per trial. The exception is latency,
where each value is one run's p50 and the summary is the median of 5 runs.

**Decline after a kill** (rank 0's first decline minus the kill, on rank 0's clock):

| cell key | n | range | decline reason |
|---|--:|---|---|
| `f4_b@hd` | 5 | 1.44–1.75 ms | `peer judged dead: the peer's socket shows FIN` |
| `hdp_kill_b@hdp` | 5 | 1.51–1.60 ms | same |
| `hd_shrink_b@hd` | 10 | 1.49–1.65 ms | (rank 0's waits ended before the shrink in 10/10) |

**Receive-only rank after rank 0's kill** (rank 1's clock):

| cell key | n | kernel end after the kill | async error after the kill | `rx_rc` |
|---|--:|---|---|---|
| `hd_rxdeath_b@hd` | 10 | 20.3–21.7 ms | 1.8–2.1 ms | `remote process exited or there was a network error` |
| `hd_rxdeath_b@ow` | 5 | 12 351.4–12 458.6 ms | none | `timeout` |

**Refusals:**

| cell key | n | refusals per trial | first refusal after the rank's own mute end | judged dead minus first refusal | decline minus judged dead |
|---|--:|---|---|---|---|
| `hd_ref1_f1_b@hd` | 10 | 1 re-dial | 80.1–105.4 ms | (never judged dead) | (no decline) |
| `hd_ref2_f1_b@hd` | 10 | 2 re-dial | 78.0–106.5 ms | 1 001.1–1 002.2 ms | 2.25–2.35 ms |
| `rc_mutekill_b@hd` | 5 | 2 re-dial | 286.6–303.4 ms | 1 001.2–1 001.7 ms | 2.26–2.30 ms |
| `ow_kill0_b@hd` (rank 1) | 5 | 2 probe | (judged dead 1 279.4–1 335.7 ms after the mute end) | 1 001.2–1 002.2 ms | (not computed) |

**Reconnect after the mute** (the reconnect line minus the later of the two ranks' mute ends, on rank 0's clock):

| cell key | n | range |
|---|--:|---|
| `rc_mute8_f1_b@hd` | 5 | 81.2–106.5 ms |
| `ow_r1in_f1_b@hd` | 5 | 91.1–129.4 ms |
| `ow_r0in_f1r1_b@hd` (rank 1) | 5 | 85.5–96.1 ms |
| `hd_nonce_f1_b@hd` | 10 | 578.0–607.3 ms |
| `ow_hello_f1_b@hd` | 5 | 580.4–605.0 ms |
| `hd_ref1_f1_b@hd` | 10 | 1 081.5–1 107.8 ms |
| `hdp_mute_b@hdp` | 5 | `rs_reconnects` 1 on each rank in 5/5 (at WARN the production build shows no close or reconnect line) |

**Reset inside the round:**
- `hd_rround_f1_b@hd` (n=10):
  - rank 1's reset came 2 074.6–2 120.2 ms after rank 0's first classification, inside the 4 000 ms stall;
  - 1 cancel line, 1 initiator recovery with `sock_retries=1`, no decline;
  - the retried round's `total_us` was 5 512 437–5 513 693 µs.
- `@ow` (n=5): the reset came 2 064.0–2 127.3 ms after the first classification; the decline was
  `cannot send REQ (ECONNRESET)` in 5/5.

**Firmware watchdog, copy bound, abort:**
- **Slow firmware phase, `hd_fwslow_f1_b@hd` (n=10).**
  - The watchdog `has run` was 3 000 ms (phase `commit`).
  - The first user-wait release was `fw-watchdog`, 3 007.2–3 008.0 ms after the first classification.
  - Rank 0's abort took 510.6–950.3 ms, with one helper-detached line per trial. That line reports the join waited 0 ms
    because the current command had already run 3 301 ms.
  - Rank 0 logged no decline (`rs_declined_r0=0`, `rs_fw_overruns_r0=1`).
  - Rank 1 declined `peer closed the socket before DONE (FIN)`; its abort took 619.1–635.1 ms.
- **Control, `@ow` (n=5):** the recovery `total_us` was 8 011 911–8 012 520 µs.
- **Stalled copy, `hd_copystall_f1_b@hd` (n=10).**
  - One copy-bound line per trial; `rs_copy_timeouts_r0=1`.
  - The decline came 2 000.7–2 001.5 ms after the first classification.
  - Aborts: rank 0 1 721.1–1 722.3 ms, rank 1 560.2–960.0 ms.
- **GPU filler, `hd_hog_f1_b@hd` (n=10).**
  - The filler launched 0.2 ms after the GIN kernel; the hook fired 584.8–1 147.7 ms after launch.
  - Both ranks logged one copy-bound line for a 4 B device-to-host copy, 2 062.5–2 066.2 ms after their own kernel launch,
    whatever the hook time. `rs_copy_timeouts=1` on both ranks.
  - Rank 0 declined `the watchdog surfaced a fault earlier`, 904.9–1 476.9 ms after the first classification. Rank 1
    declined `the peer declined`.
  - 0/10 transparent.
  - `[inferred]` The copy that missed its bound started about 63 ms after the launch, before the fault: the helper's idle
    check stalled as soon as the filler ran. Why the copy stalls is `[unverified]`.

**Re-post plan, `hd_repost_f1_b@hd` (n=10):** the rejection was at qp 1 of 4, with rank 0 as the round's initiator, in
10/10 (so nothing was excluded under section 8). There were 0 recovery lines on either rank.

**Escalation:**
- `hd_esc_f1_b@hd` (n=10):
  - 4 hook fires (the fifth never fires), 3 initiator recoveries, 1 escalation line;
  - stats on rank 0: rounds 3, recovered 3, declined 1, escalations 1;
  - stats on rank 1: rounds 3, recovered 3, declined 1, escalations 0.
- `@ow` (n=5): 5 fires and 5 recoveries.

**Shrink:**
- `@hd` (n=10):
  - `ho_kernel_done_before_shrink=1` and `rx_phantom_r0=0`;
  - the shrink returned `remote process exited or there was a network error` after 0.0 ms, with no new communicator.
- `@ow2` (n=5):
  - `ho_kernel_done_before_shrink=0`;
  - the same shrink error after 0.0 ms;
  - `post_abort_rx_phantom_r0` was 201–204.

**IB timeout 20:**
- `to20_f3_b@hd` (n=5):
  - the first classification (`RETRY_EXC`) came 56 360.3–59 288.9 ms after the hook (rank 1's hook moved to rank 0's
    clock);
  - one initiator round of 10 022–10 428 µs;
  - transparent 5/5.
- `to20_f3_t@hd` (n=3): `tx_rc=timeout`, 1 wait-timeout dump each, no recovery and no decline.

**Latency p50.** Values are µs, one per run, n=5 runs per build; each run has 3000 iterations:

| size | production `hdp` | gin-oneway `ow` | pristine `stk` | hdp − ow | hdp − stk |
|---|---|---|---|---|---|
| 4 KiB | 10.69, 10.72, 10.72, 10.72, 10.72 (median 10.72) | 10.59 ×5 (10.59) | 9.76, 9.82, 9.73, 9.76, 9.82 (9.76) | +0.13 | +0.96 |
| 256 KiB | 38.91, 38.88, 38.91, 38.91, 38.91 (38.91) | 38.91 ×5 (38.91) | 38.11, 37.86, 37.82, 37.92, 37.79 (37.86) | 0.00 | +1.05 |

**Recovery-stats counters** (`ncclGinGetRecoveryStats`). Each pattern holds in every scored trial of the cell:

| cell key | rank 0 | rank 1 |
|---|---|---|
| `f1_b@hd` | rounds 1, recovered 1, declined 0 | same |
| `f4_b@hd`, `hdp_kill_b@hdp`, `hd_shrink_b@hd` | rounds 0, declined 1, deaths 1 | killed (no stats) |
| `hd_rxdeath_b@hd` | killed (no stats) | rounds 0, declined 1, deaths 1 |
| `hdp_mute_b@hdp` | reconnects 1, nothing else | reconnects 1, nothing else |
| `hd_rround_f1_b@hd` | rounds 2, recovered 1, reconnects 1, cancelled 1 | rounds 1, recovered 1, reconnects 1 |
| `hd_copystall_f1_b@hd` | rounds 1, declined 1, copy timeouts 1 | declined 1 |
| `hd_fwslow_f1_b@hd` | rounds 1, declined 0, fw overruns 1 | rounds 1, declined 1 |

Every listed trial reports `api=1, contexts=1`.

**iptables mute, `hdp_mute_b@hdp` (n=5):**
- `mute.out`:
  - `mute_rules_on=2`, `mute_rules_left=0`, ports 51700–51715 in 5/5;
  - the rules went on 2 050.5–2 086.7 ms after rank 0's kernel launch (planned 2 000);
  - they were removed 8 056.0–8 056.7 ms later (planned 8 000).
- Meta `left_rules=0` in 5/5.
- `chain.out` cleanup was `deleted=0 left=0` after every hold.

## 6. Disagreements and observations

**With the hold logs: none.** Every runner line printed in `hold_*.out` matches a trial file, and every trial file
matches a printed line:
- 247 of 247 result lines (rc, left, `left_rules`, wall, DONE lines);
- 247 of 247 start lines (gids, inject, bytes, iters);
- 51 of 51 kill lines (`kill.out` content and delay).

Per-hold trial counts: H1 60, H2 25, H3 25, H4 25, H5 40, H6 50, H7 13, H8 5, fill 4.

**With EXPERIMENT.md: no statement contradicted by the raw files.** Details:
1. **The document does not record the main run yet.** It is unchanged since the tag:
   - status `PREREGISTERED`;
   - the section 11 checkbox "본 실행 H1–H8" is unchecked;
   - section 12 ends at 03:42:57;
   - section 13 is empty;
   - sections 14 and 15 say "아직 없다" and "아직 측정 전".

   What to record: H1–H8 ran 03:51:30–06:02:55 (from the snapshots; `chain.out` 03:43:04–06:02:56), and the fill hold
   ran 06:11:14–06:11:47. The fill is a section 8 replacement, and the `fill:` mode was already in `hold.sh` at the tag,
   so it is not a deviation.
2. **Three predictions are refuted:**
   - shrink hand-off (A2);
   - transparent recovery with the GPU full (C1);
   - the 256 KiB latency against pristine NCCL (P4).

   Section 3 expected A2 and C1 to fail. P4 is a new failure: +1.05 µs against a 1.00 µs bound. The 4 KiB case (P3)
   holds at +0.96 µs, near its bound, as the pilot's 0.93 µs suggested.
3. **The pilot statements in sections 3 and 12 all reproduce** from `results/20261009_pilot/` (25 trials, never scored):

   | statement | recomputed |
   |---|---|
   | gap between the two refusals | 1 001.3 ms |
   | wrong-nonce reconnect after the mute | 606.7 ms |
   | reset after the first classification | 2 075.8 ms (1 cancel, 1 retry, transparent) |
   | receive-only rank: wait released / async error after the kill | 20.2 ms / 1.9 ms |
   | watchdog run time | 3 000 ms |
   | slow-firmware abort | 912.3 ms |
   | stalled-copy decline after the first classification | 2 000.8 ms |
   | re-post plan rejection | qp 1 of 4, rank 0 initiator, no recovery line |
   | escalation | 3 recoveries, then escalation |
   | `ow2` signal-less successes after the final abort | 202 |
   | shrink on both builds | `ncclRemoteError` at 0 ms |
   | production-build decline after the kill | 1.6 ms |
   | IB timeout 20: first classification after the hook | 56.0 s (56 023.9 ms) |
   | IB timeout 20: recovery round | one 10 ms round, transparent |
   | 4 KiB p50: production, gin-oneway, pristine | 10.69, 10.56, 9.76 µs |
   | first refusal after the mute end: one-refusal cell, two-refusal cell | 93.6 ms, 98.6 ms |
   | hook after the filler start | 599.5 ms |
   | next re-dial after the re-listen | 393.1 ms |
   | second refusal before the re-listen | 1 400.6 ms |
   | two-refusal cell excluded for 0 hook fires | 0 fires |
   | snapshots and cleanup | 03:24:59–03:31:01, new mlx5 lines 0, iptables `deleted=0 left=0` |

**Observations** (not disagreements):
- **sunny dmesg between holds.** The sunny mlx5 dmesg count went from 510 to 511 between H8's after-snapshot
  (06:02:55) and the fill's before-snapshot (06:11:14). The new line is `mlx5_fw_tracer_handle_traces ... FWTracer: Events
  were lost`. It is outside every hold and not a command-error line, so no hold reported it.
- **Production WARN output.**
  - At `NCCL_DEBUG=WARN` the production build still prints the `NCCL_GIN_TS_PATH_WAIT_MS ... clamped` line, one per rank
    per trial. This line is older than this layer and is not in the 3.1 table.
  - In the iptables cell it shows no close or reconnect lines, because they are INFO. Recovery there is visible only
    through `rs_reconnects`. P7 counts only the "transparent recovery ON" line, so it is unaffected.
- **gin-oneway receive-only control.** The kernel ended 12.35–12.46 s after the kill, not 15 s. `[inferred]` The 15 s
  per-wait bound started before the kill; rank 1 was already waiting. B10's acceptance (at least 10 s) is met.
- **`n_fwdog_r*` ambiguity.** If the scorer counts both watchdog lines, `n_fwdog_r0` is 2 instead of 1 in the slow
  firmware cell. C2 needs at least 1, so the verdict is the same, and no other cell has either line.

## 7. Files

- [../../qa/recount.py](../../qa/recount.py): the recount (reads only; prints this report's numbers).
- This file.
- Evidence:
  - this folder's `hd/`, `hdp/`, `ow/`, `ow2/`, `stk/` trial files;
  - `hold_*.out` and `chain.out`;
  - `snap_*`, `mlx5_*` and `fwcmd_*`;
  - tag `prereg/gin-harden-v1` (`692ff591`).
