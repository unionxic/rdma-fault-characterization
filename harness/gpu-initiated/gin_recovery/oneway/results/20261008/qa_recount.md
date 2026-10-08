# gin-oneway: independent recount of the main run

Date 2026-10-08. Done by a separate agent from the raw per-trial files. Script: [`../../qa/recount.py`](../../qa/recount.py)
(`python3 qa/recount.py` from the study folder; it prints its report and writes nothing; exit code 0).

Marks: `[measured]` from raw files, `[inferred]` interpretation.

## Method

- **Not read or run:** `score.py`, `posthoc_ow.py`, `rows_ow.py`, `SCORE.md`, `trials_scored.csv`, the untracked `trials_*.csv`.
  `../scripts/ts2/rows.py`, `../s2_close/rows_extra.py` and `../pair_check/rows_pc.py` were read only for the definitions of the
  inherited columns; every column was parsed again from the logs.
- **Inputs:** `ow/`, `pcm/`, `pc/`, `lat/` (meta, both kv files, both logs, `kill.out`, `lat_raw.csv.gz`), `hold_H1.out`–`hold_H5.out`,
  `snap_*`, `mlx5_*`, `fwcmd_*`. The smoke folder was read only to check statements about it; it is not scored.
- **Columns:** the EXPERIMENT.md 3.1 definitions, written from the text (first close line, all `liveness=dead` lines, first
  reconnect, first wait line, first classifier record, first decline, `unmute_ms` as the latest mute-off on rank 0's clock).
- **Rules:** the `acceptance` strings of `predictions.csv`, evaluated per trial by my own evaluator of the 3.2 grammar (blank is
  None, any comparison or arithmetic with None is false; `per cell:` must hold in every cell).
- **Post-hoc count (DEVIATIONS.md 3):** for each `liveness=dead` line of rank r, compared with the other rank's first
  `GIN/TS: communicator teardown` line (`t0_mono_ms`), both on rank 0's clock; all dead lines count when the other rank has no such
  line. I found the teardown lines myself and repeated the split with the kv `abort_start_mono_ms` as the teardown start: same
  split in every trial.
- **Clocks:** rank 1 time minus rank 0 kv `clock_offset_ms`. `clock_rtt_ms` was 0.093–0.112 over the 125 trials.

## Pre-registration and trial set

- `predictions.csv` sha256 `8f5c0602…750add` equals `PREREG.txt` and the file at tag `prereg/gin-oneway-v1` (commit `7840c2c4`).
  28 rows. EXPERIMENT.md sections 2, 3, 7 and 8 are byte-identical to the tag; `PREREG.txt` is unchanged `[measured]`.
- DEVIATIONS.md 3 (with `posthoc_ow.py`) was committed at 15:29:48 (`b93263ba`, `c3e22843`). That is 11 s after the first main-run
  trial started (latency run, 15:29:37) but before any trial of the five cells the post-hoc count affects (first: `rc_mute8_f1_b_n1`,
  15:34:13). The text says 15:28; only the commit time can be checked `[measured]`.
- Trial set: every `cell@build` of section 7 has exactly its planned count, 105 cell trials and 20 latency runs. No extra keys.
  0 excluded under section 8 (`bind_fail` 0, `trigger_miss` 0, all hooks fired, all kills recorded, order conditions met).
  0 setup-check failures (transparent recovery, abort flag, pair check, one-way mode, test-switch lines, mute lines, hook context).
  `left` is 0 in all 125.
- Holds, from the first log timestamp of each trial: H1 latency 20 and replication 25; H2 `rc_mute8_f1_b`, `rc_mutekill_b`,
  `ow_r1in_f1_b` (ow 10, pcm 5); H3 `ow_r0in_f1r1_b` (ow 10, pcm 5) and the race cell (pc 5, ow 5); H4 `ow_kill0_b` (ow 10, pcm 5);
  H5 `ow_hello_f1_b` (ow 10, pcm 5). Matches the section 9 table.
- Bundles: for all 125 trials the folder, meta `build`, meta `bundle` path and the source line of the
  `transparent recovery ON` WARN in both logs agree (pc 4177, pcm 4204, ow 4369; each is the WARN's first line in that build's
  tree plus 4). The one-way start line is present on both ranks of all 90 ow runs (80 cell trials, 10 latency runs) and absent
  in all pc and pcm runs.
- Meta conditions (switches per rank, mute, hook time, iterations, size) match section 7 in every cell; the hook-armed lines appear
  only in the hook cells. `ABORT_WD_S`, `WATCHDOG_S` and `KILL_DELAY_MS` are not in meta. The hold log shows "SIGKILL rank0 after
  6500 ms" 15 times, and the kill came 5 644.5–5 698.1 ms after rank 0's devComm creation (15 trials). Section 7's frozen "about
  6.0 s [inferred]" was high by about 0.35 s; no rule uses it.
- All 25 kill records name the PID that appears in the killed rank's own log.

## Predictions

n is the number of scored trials (runs for L1, L2). "Post-hoc" replaces `n_dead_r0`, `n_dead_r1` by the DEVIATIONS 3 count in the
same rule; it is not a verdict.

| Prediction | id | cell@build | n | hits | frozen verdict | post-hoc |
|---|---|---|--:|--:|---|---|
| The muted rank 1 times out first; rank 0 gets its reset | A0 | `ow_r1in_f1_b@ow` | 10 | 10 | holds | |
| Rank 0 takes the reset as unknown; no dead line on either rank | A1 | same | 10 | 0 | fails | 10/10, holds |
| Each rank reconnects once; rank 0 within 1.5 s after the mute | A2 | same | 10 | 10 | holds | |
| Fault at 12 s transparent, no decline, no early async error | A3 | same | 10 | 10 | holds | |
| Reference build: rank 0 dead on ECONNRESET, declines "(ECONNRESET)" while rank 1 lives; rank 1 never reconnects | K1 | `ow_r1in_f1_b@pcm` | 5 | 5 | holds | |
| The muted rank 0 times out first; rank 1 gets its reset | B0 | `ow_r0in_f1r1_b@ow` | 10 | 10 | holds | |
| Rank 1 takes the reset as unknown; no dead line | B1 | same | 10 | 0 | fails | 10/10, holds |
| Rank 1's fault waits and the wait ends reconnected within 1.5 s | B2 | same | 10 | 10 | holds | |
| Rank 1 recovers as initiator, transparent | B3 | same | 10 | 10 | holds | |
| Reference build: rank 1 dead on the reset, declines "(ECONNRESET)" | K2 | `ow_r0in_f1r1_b@pcm` | 5 | 5 | holds | |
| Rank 1's probe refused after the mute: rank 0 dead (ECONNREFUSED), not during the mute | D1 | `ow_kill0_b@ow` | 10 | 10 | holds | |
| Rank 1's RETRY_EXC declined with ECONNREFUSED, never unknown, nothing recovered | D2 | same | 10 | 10 | holds | |
| Decline within 2 s of rank 1's first classifier record | D3 | same | 10 | 10 | holds | |
| Reference build: rank 1 declines as unknown after the 10 s bound | K3 | `ow_kill0_b@pcm` | 5 | 5 | holds | |
| Refused HELLO logged as not accepted; no dead line | E1 | `ow_hello_f1_b@ow` | 10 | 0 | fails | 10/10, holds |
| Next re-dial: each rank reconnects once; rank 0 within 2 s | E2 | same | 10 | 10 | holds | |
| Fault at 12 s transparent | E3 | same | 10 | 10 | holds | |
| Reference build: reconnect counted, refusal read as FIN death, declined "(FIN)" | K4 | `ow_hello_f1_b@pcm` | 5 | 5 | holds | |
| Without the timeout switch, pc declines the live rank 0 "(ECONNRESET)" in at least 2 of 5 | U1 | `ow_r0in_nat_f1r1_b@pc` | 5 | 5 | holds | |
| Same race on ow: transparent and no dead line | U2 | `ow_r0in_nat_f1r1_b@ow` | 5 | 0 | fails | 5/5, holds |
| Replication cells stay transparent | G1 | `f1_b`, `f3_b`, `bidirf_sym_b`, `rc_mute8_f1_b` @ow | 5 each | 5 each | holds | |
| Symmetric 8 s mute: one reconnect each within 1.5 s, no dead line | G2 | `rc_mute8_f1_b@ow` | 5 | 0 | fails | 5/5, holds |
| Kill without mute declined with a death cause; abort returns | G3 | `f4_b@ow` | 5 | 5 | holds | |
| Rank 1 killed during the mute: refused re-dial, never unknown | G4 | `rc_mutekill_b@ow` | 5 | 5 | holds | |
| Receiving rank's wait released at abort | G5 | `f2rel_b@ow` | 5 | 5 | holds | |
| After a peer QP error all QPs RTS at teardown | G6 | `f3_b@ow` | 5 | 5 | holds | |
| 4 KiB p50 difference at most 0.40 µs | L1 | `lat_ow_on_4k@ow`, `lat_pc_on_4k@pc` | 5, 5 | medians 10.56, 10.56 | holds (0.00) | |
| 256 KiB p50 difference at most 0.30 µs | L2 | `lat_ow_on_256k@ow`, `lat_pc_on_256k@pc` | 5, 5 | medians 38.91, 38.91 | holds (0.00) | |

Frozen rules: 23 hold, 5 fail, 0 insufficient data. The five failures are the rules containing
`n_dead_r0 == 0 and n_dead_r1 == 0`; in each of their 40 trials the only dead line is one `cause=FIN` line on rank 1 written after
rank 0's teardown started. Under the post-hoc count all five rules would hold.

## What the logs show

**Who timed out first, and the reset** (rank 0 clock) `[measured]`.

| cell@build | n | timed out (ETIMEDOUT) | other rank's first close | timeout after own mute start (ms) | reset line minus timeout line (ms) |
|---|--:|---|---|---|---|
| `ow_r1in_f1_b@ow` | 10 | rank 1, 10/10 | ECONNRESET unknown | 4 577.6–4 621.1 | −0.086 to −0.036 |
| `ow_r1in_f1_b@pcm` | 5 | rank 1, 5/5 | ECONNRESET dead | 4 574.8–4 620.3 | −0.066 to −0.052 |
| `ow_r0in_f1r1_b@ow` | 10 | rank 0, 10/10 | ECONNRESET unknown | 4 573.9–4 603.4 | −0.035 to 0.146 |
| `ow_r0in_f1r1_b@pcm` | 5 | rank 0, 5/5 | ECONNRESET dead | 4 577.5–4 593.5 | 0.106–0.116 |
| `ow_r0in_nat_f1r1_b@pc` | 5 | rank 0, 5/5 | ECONNRESET dead | 4 572.9–4 598.1 | 0.089–0.116 |
| `ow_r0in_nat_f1r1_b@ow` | 5 | rank 0, 5/5 | ECONNRESET unknown | 4 574.8–4 593.5 | 0.128–0.137 |

The muted rank timed out first in all 45 trials, including all 10 race trials without the timeout switch (smoke: the one pc race
trial had rank 1 time out first, both ranks ETIMEDOUT). A reset cannot be logged before the timeout that sends it, so the negative
values (all 15 `ow_r1in_f1_b` trials, one `ow_r0in_f1r1_b@ow` trial) mean the per-trial clock conversion is off by at least
0.035–0.086 ms there, in either direction `[inferred]`. Which rank timed out first is therefore read from the causes, not from the
times.

**Every close line** (counts over the scored trials of the cell) `[measured]`.

| cell@build | rank 0 | rank 1 |
|---|---|---|
| `ow_r1in_f1_b@ow` | ECONNRESET/unknown 10 | ETIMEDOUT/unknown 10, FIN/dead 10 |
| `ow_r1in_f1_b@pcm` | ECONNRESET/dead 5 | ETIMEDOUT/unknown 5 |
| `ow_r0in_f1r1_b@ow`, `ow_r0in_nat_f1r1_b@ow` | ETIMEDOUT/unknown 10, 5 | ECONNRESET/unknown 10, 5; FIN/dead 10, 5 |
| `ow_r0in_f1r1_b@pcm`, `ow_r0in_nat_f1r1_b@pc` | ETIMEDOUT/unknown 5, 5; FIN/dead 5, 5 | ECONNRESET/dead 5, 5 |
| `ow_kill0_b@ow` | ETIMEDOUT/unknown 10 | ETIMEDOUT/unknown 10, ECONNREFUSED/dead 10 |
| `ow_kill0_b@pcm` | ETIMEDOUT/unknown 5 | ETIMEDOUT/unknown 5 |
| `ow_hello_f1_b@ow` | ETIMEDOUT/unknown 10 | ETIMEDOUT/unknown 10, FIN/dead 10 |
| `ow_hello_f1_b@pcm` | ETIMEDOUT/unknown 5, FIN/dead 5 | ETIMEDOUT/unknown 5 |
| `rc_mute8_f1_b@ow` | ETIMEDOUT/unknown 5 | ETIMEDOUT/unknown 5, FIN/dead 5 |
| `rc_mutekill_b@ow` | ETIMEDOUT/unknown 5, ECONNREFUSED/dead 5 | ETIMEDOUT/unknown 5 |
| `f4_b@ow` | FIN/dead 5 | none (killed) |
| `f1_b`, `f3_b`, `bidirf_sym_b`, `f2rel_b` @ow | none | FIN/dead 5 each |
| latency, 20 runs | FIN/dead 8 | FIN/dead 2 (10 runs have no close line) |

On the ow build no reset was classified dead. In the pcm `ow_r0in_f1r1_b` and pc race trials (10/10) rank 0 also re-dialled,
logged a reconnect, read a FIN 0.18 ms later and declined its own RETRY_EXC as "RETRY_EXC and the peer's socket shows FIN"
(1.12–2.06 ms and 1.22–2.00 ms after its first classifier record). Rank 1 had already marked rank 0 dead, so it closed the new
connection `[inferred]`: the reference build lost the pair on both ranks, and the counted-before-accepted path appeared without the
HELLO switch.

**Reconnects after the mute ends** (ms, rank 0 clock; one reconnect line per rank in every ow trial listed) `[measured]`.

| cell@build | n | rank 0 | rank 1 |
|---|--:|---|---|
| `ow_r1in_f1_b@ow` | 10 | 81.6–125.0 (re-dial attempt 8) | 80.8–124.3 |
| `ow_r0in_f1r1_b@ow` | 10 | 79.3–107.5 | 78.3–106.7 |
| `ow_r0in_nat_f1r1_b@ow` | 5 | 79.3–97.9 | 78.3–97.1 |
| `ow_hello_f1_b@ow` | 10 | 582.1–606.7 (gen 2, attempt 9) | 581.1–605.8 |
| `rc_mute8_f1_b@ow` | 5 | 76.7–99.8 | 75.9–99.0 |
| `ow_r0in_f1r1_b@pcm`, `ow_r0in_nat_f1r1_b@pc` | 5, 5 | 80.1–96.9, 75.8–102.2 (then FIN death) | none |
| `ow_hello_f1_b@pcm` | 5 | 75.5–87.1 (then FIN death) | none |
| `ow_r1in_f1_b@pcm` | 5 | none | none |

Rank 1's probe answered once in 4 of 10 `ow_r1in_f1_b@ow` trials (87.3–119.0 ms after the mute, each before the reconnect line),
in 10 of 10 `ow_hello_f1_b@ow` trials (88.2–135.0 ms) and in 1 of 5 `rc_mute8_f1_b@ow` trials (78.8 ms).

**Rank 1's wait** `[measured]`. `ow_r0in_f1r1_b@ow`: rank 1's fault fired 1 999.3–2 000.1 ms before the mute ended; the wait ended
`reconnected` 10/10 after 2 069.7–2 098.2 ms; rank 1 then ran a context-1 round (1 QP, scope 0x2, commit 865–921 µs, `total_us`
2 073 408–2 101 680 including the wait) and was transparent 10/10. Race cell on ow: fire 1 986.8–1 999.7 ms before the mute end,
`reconnected` 5/5 after 2 058.2–2 095.0 ms. `ow_kill0_b@pcm`: `ended=bound` 5/5 after 10 000.1–10 000.6 ms. No wait line in
`ow_kill0_b@ow` (rank 0 was already dead when the fault surfaced), none on rank 0, and no `ended=dead` anywhere: the probe refusal
inside a wait was not exercised.

**Rank 0 killed during the mute** `[measured]`. Kill 5 346.5–5 400.5 ms after rank 0's mute start (15 trials), with both ranks
already closed ETIMEDOUT/unknown (15/15). ow (10): rank 1's probe refused 287.8–335.5 ms after its own mute ended, with the
ECONNREFUSED dead line at most 0.1 ms later; no dead line during the mute; first classifier record (RETRY_EXC) 3 582.0–3 699.2 ms
after the kill, 951.1–1 083.8 ms after rank 1's mute end and 633.0–792.0 ms after the probe refusal; decline "RETRY_EXC and the
peer's socket shows ECONNREFUSED" 1.29–2.12 ms after that record; no recovery. pcm (5): no probe lines, first record 3 661.9–3 683.4
ms after the kill, decline "unknown (ETIMEDOUT, no reconnect within 10000 ms)" 10 001.57–10 002.78 ms after it.

**HELLO refusal** `[measured]`. ow (10): one test refusal of HELLO gen 1, 80.3–105.3 ms after the mute ended; rank 0 "not
accepted (FIN)" at attempt 8, 81.2–106.3 ms; no dead line before teardown; reconnected with gen 2; 10/10 transparent. pcm (5): the
same refusal; rank 0 had already logged the reconnect, read FIN 0.19–0.21 ms after it and declined "(FIN)" 0.22–0.69 ms after its
first classifier record.

**Replication cells** `[measured]`. `f1_b`, `f3_b`, `bidirf_sym_b`, `rc_mute8_f1_b`: 5/5 transparent each. `f3_b`: QP states
`[3,3,3,3]` on both ranks 5/5. `f4_b`: decline "the peer's socket shows FIN" 5/5, 1.09–1.67 ms after rank 0's first record, abort
`no error`; the FIN dead line came 0.1–0.2 ms after the kill. `rc_mutekill_b`: decline with ECONNREFUSED 5/5 (no "unknown"),
1.10–1.58 ms after the first record; dead line 2 557.4–2 590.4 ms after the kill. `f2rel_b`: rank 1 abort `no error` in
853.0–871.4 ms, rank 1 rc 3, `async_error_kernel_stuck` 5/5.

**Latency** `[measured]`. p50 per run from rank 0 kv, recomputed from `lat_raw.csv.gz` with the program's own index rule: all 20
match. 4 KiB: ow 10.56–10.59 (median 10.56), pc 10.56–10.62 (median 10.56). 256 KiB: ow 38.91–38.94 (median 38.91), pc 38.91–38.94
(median 38.91). Ranges are over the 5 runs of each cell. All 20 runs transparent.

## Post-hoc count (DEVIATIONS.md 3)

Trials with at least one dead line before the other rank's teardown start `[measured]`:

| where | trials | lines, cause | the peer at that moment |
|---|--:|---|---|
| `f4_b@ow` | 5/5 | rank 0 FIN | killed 0.1–0.2 ms earlier |
| `rc_mutekill_b@ow` | 5/5 | rank 0 ECONNREFUSED | killed 2 557.4–2 590.4 ms earlier |
| `ow_kill0_b@ow` | 10/10 | rank 1 ECONNREFUSED | killed 2 896.8–2 979.1 ms earlier |
| `ow_r1in_f1_b@pcm` | 5/5 | rank 0 ECONNRESET | alive (reference build misjudged) |
| `ow_r0in_f1r1_b@pcm` | 5/5 | rank 1 ECONNRESET, rank 0 FIN | alive (both ranks misjudged) |
| `ow_r0in_nat_f1r1_b@pc` | 5/5 | rank 1 ECONNRESET, rank 0 FIN | alive (both ranks misjudged) |
| `ow_hello_f1_b@pcm` | 5/5 | rank 0 FIN | alive (reference build misjudged) |
| `ow_kill0_b@pcm` | 0/5 | none | rank 1 never learns the death |
| every other cell (ow one-way, race, HELLO, 8 s mute, f1, f3, bidirectional, f2rel, latency) | 0 | none | |

So dead lines before teardown appear only where the peer was really dead or where the reference build misjudged a live peer.
All other dead lines (70, one per trial, all FIN) came 0.60–1.69 ms after the other rank's teardown start. The smallest margin is
about six times the clock round trip, so the clock error cannot move a line across the boundary `[inferred]`. Smoke check of
DEVIATIONS.md 2: the six FIN lines written after the other rank's teardown came 1.20–1.77 ms after it (stated 1.2–1.8).

A1, B1, E1, U2, G2 under the post-hoc count: 10/10, 10/10, 10/10, 5/5, 5/5, all meeting their rules.

## Safety per hold

Recomputed from `mlx5_*`, `fwcmd_*` and `hold_H*.out` `[measured]`.

| hold | lock, idle link | wall (cap 880 s) | mlx5 lines rain / sunny | command-error lines rain / sunny | rain fw failures | new mlx5 lines | other GPU jobs | kills |
|---|---|---|---|---|---|---|---|---|
| H1 | yes, 0 Mb/s | 245 s | 66→66 / 509→509 | 2→2 / 0→0 | 31→31 | 0 | 0 | rank 1 × 5 (`f4_b`, own PID) |
| H2 | yes, 0 Mb/s | 468 s | 66→66 / 509→509 | 2→2 / 0→0 | 31→31 | 0 | 0 | rank 1 × 5 (`rc_mutekill_b`, own PID) |
| H3 | yes, 0 Mb/s | 476 s | 66→66 / 509→509 | 2→2 / 0→0 | 31→31 | 0 | 0 | none |
| H4 | yes, 0 Mb/s | 282 s | 66→66 / 509→509 | 2→2 / 0→0 | 31→31 | 0 | 0 | rank 0 × 15 (own PID) |
| H5 | yes, 0 Mb/s | 307 s | 66→66 / 509→509 | 2→2 / 0→0 | 31→31 | 0 | 0 | none |

Every hold ran under `timeout -s KILL 880`, exited rc 0 with `sunny_busy_after=0`, and no `STOP_mlx5` was written. H0 (smoke) also
had equal snapshots and 0 new lines.

## EXPERIMENT.md section 15 against the raw data

Read after the recount above. Every count, verdict, n and range in section 15 reproduces, except:

1. **Paragraph 2: "rank 1 got ECONNRESET within 0.1 ms" of rank 0's timeout.** Not supported as stated. The gap exceeded 0.100 ms in
   14 of 15 trials (ow −0.035 to 0.146 ms, pcm 0.106–0.116 ms). It is within the clock-conversion uncertainty, and "within 0.15 ms"
   would hold.
2. **Paragraphs 2 and 3 leave out rank 0's FIN death on the reference builds.** In all 10 pcm one-way and pc race trials rank 0 also
   marked the live rank 1 dead (FIN 0.18 ms after its counted reconnect) and declined its RETRY_EXC "(FIN)". This is an omission,
   not a contradiction; the post-hoc paragraph does count these trials.
3. **"Reason for the five failures" is phrased as a general rule.** It holds in all 60 cell trials that reached teardown with the
   helper socket connected (55 transparent ow trials and 5 `f2rel_b`), but 10 of the 20 latency runs have no such line. The
   reasoning for the five cells is unaffected.
4. **Post-hoc paragraph: "new build ... latency 20 runs".** 10 of the 20 latency runs are on pc. Wording only; neither build has a
   dead line before teardown in them.
5. **Paragraph 1: "the other 6 reconnected before that".** The logs show only that those 6 trials have no probe-answered line; the
   order is an inference.

Outside section 15: DEVIATIONS.md 1 gives 1 062–1 087 ms for the smoke kill trials; the raw values are 1 062.2, 1 075.1 and
1 087.7 ms (truncated, not rounded). Section 7's "about 6.0 s after devComm creation" for the rank 0 kill measured
5 644.5–5 698.1 ms (see above).
