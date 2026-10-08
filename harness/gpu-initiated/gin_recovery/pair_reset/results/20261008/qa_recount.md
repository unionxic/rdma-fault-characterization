# gin-pair-reset: independent recount (QA)

Date 2026-10-08. Recount by a separate agent from the raw per-trial files only. Tags: `[measured]` read from raw files,
`[source]` read from code, `[inferred]` interpretation, `[unverified]` not checked.

## 1. Method

- Script: [`../../qa/recount.py`](../../qa/recount.py). Run from the study folder: `python3 -B qa/recount.py`. It prints
  the pre-registration check, trial set, exclusions, setup and cell-condition checks, the 23 verdicts, the values below
  and the hold safety records. It writes nothing.
- Not read or run: `score.py`, the output of `rows_pr.py`, `SCORE.md`, `trials_scored.csv`, the untracked `trials_*.csv`.
  `rows_pr.py` itself was not opened either. `EXPERIMENT.md` section 15 was read only after the recount was finished.
- Read only for log formats and definitions: `EXPERIMENT.md` 3.1, `../s2_close/EXPERIMENT.md` 3.2,
  `../scripts/ts2/rows.py`, `../s2_close/rows_extra.py`, `../scripts/ts2/run_trial.sh` and `batch.sh`,
  `../reconnect/cells.sh`, this folder's `cells.sh`, `hold.sh`, `chain.sh`, and in `../gin_ts2.cu` the latency
  statistics and the dual-context window code. Nothing is imported. Columns whose meaning 3.1 delegates to `rows.py` or
  `rows_extra.py` (`transparent_ok`, `bind_fail`, `ua_r*`, `killed`) are re-implemented from those definitions, so they
  are independent in code, not in definition.
- Inputs: `<stem>_meta.txt`, `_r{0,1}.kv`, `_r{0,1}.log`, `_kill.out`, `_lat_raw.csv.gz` in `dual/`, `conflict/`,
  `rep_pr/`, `lat/`, plus `chain.out`, `hold_*.out`, `snap_*.txt`, `mlx5_*.txt`, `fwcmd_*.txt`.
- Rules: the `acceptance` text of `predictions.csv` is evaluated verbatim (blank is NA, any comparison or arithmetic with
  NA is false; `per cell:` applied per listed cell; two-cell rules need both cells full). As a second check every rule is
  also hand-coded on typed values. The two agree on 23/23.
- Parse coverage, raw substring count against parsed lines over all 204 rank logs: fault fired 82/82, scope decision
  92/92, recovered 154/154, scope conflict 11/11, gate epochs 177/177, pair reset 182/182, test stall 11/11, declined
  15/15, device-classified records 103/103.
- Latency: every run's p50 was recomputed from its 3000 raw samples with the driver's rank rule
  (`v[int(0.5*(n-1)+0.5)]`). All 20 match the kv `lat_p50_us`.
- Limitation: the dual-context runs keep no per-iteration timestamps. `dual_c1_in_win`, `dual_c1_max_in_win_us`,
  `dual_c1_end_after_win` and `dual_c1_max_us` are therefore taken from the rank-0 kv, as 3.1 defines them, and could only
  be checked for consistency (section 5.3), not recomputed from iterations.

## 2. Pre-registration integrity `[measured]`

- `sha256(predictions.csv)` = `dcb00afb48e7…`, the value in `PREREG.txt`. Tag `prereg/gin-pair-reset-v1` resolves to
  commit `09f2b3e2`. `predictions.csv` (23 rows) and `PREREG.txt` are byte-identical to the tag.
- `EXPERIMENT.md` sections 2, 3, 7 and 8 are byte-identical to the tag. Changed since the tag: the header table and
  sections 4, 5, 10–15.

## 3. Trial set, exclusions, refills, bundles `[measured]`

- 102 trial meta files: `dual/` 40, `conflict/` 11, `rep_pr/` 31, `lat/` 20. All 16 cell keys of section 7 are present
  and no other. Scored: 100 (80 cell trials, 20 latency runs), each cell exactly at its planned count.
- Counted apart: 2 trials.
  - `bidirf_sym_b@pr` n4 (hold H1): `bind: Address already in use` in the rank-0 log, `r0rc=1`, `r1rc=7`, no NCCL line.
    Excluded as `bind_fail`. Refilled by n6 in the first fill hold.
  - `pr_bidirf_conflict_b@pr` n10 (hold H4): rank 1's first device record, moved to rank 0's clock, is 18.197 ms after
    rank 0's stall line, 0.197 ms past the window end `t + 20 − 2`. `r1_q4_in_stall = 0`, excluded as "condition not
    applied". The other ten conflict trials (n1–n9, n11) sit 12.56–13.43 ms inside the window end. Refilled by n11 in
    the second fill hold. n10 itself was transparent and took the same conflict path.
  - Each refill is the next number, 1 of 5 and 1 of 10 planned (at most 50%). No other exclusion rule fires: every
    local-error cell fired on rank 0, every peer-error cell on rank 1, both conflict-cell ranks fired, no trigger miss,
    every kill trial has a kill record, `dual_c1_end_after_win = 1` in all 25 context-0 dual trials.
- Setup checks of section 8 pass on all 101 trials that started: transparent recovery on and the abort flag set on both
  ranks; pair-reset start line 0 on both ranks in `pr_dual_f1c0_full_b`, 1 elsewhere on `pr`/`prd`; kv `dual=1` on both
  ranks of every `prd` trial; fault-hook context 0 on rank 0 (`f1c0`, `f1c0_full`), 0 on rank 1 (`f3c0`), 0 and 1
  (conflict), none (`f1all`).
- Bundle per trial: every `prd` trial ran from `gin_ts2/prd` and its kv carries the dual-context keys; every `pr` trial
  ran from `gin_ts2/pr` with no dual keys; the 10 `rc` latency runs ran from `gin_ts2/rc` and have no pair-reset start
  line, all 91 started `pr`/`prd` trials have one. Meta fields match section 7 and `cells.sh` (size, iterations, gap,
  env, injection instant per trial number); the armed hook delay in each log equals meta `inject`/`inject1`.
- Holds (from `chain.out` and log timestamps): H1 latency 20 runs (interleaved rc 4 KiB, rc 256 KiB, pr 4 KiB, pr 256 KiB
  per round) and the replication cells; H2 `f1c0` 10 and `f1c0_full` 5 interleaved 2:1 (on n1, n2, off n1, ...), then
  `none` 5; H3 `f3c0` 10, `f1all` 10; H4 conflict 10; fill 1 `bidirf_sym_b` n6; fill 2 conflict n11. `left=0` in all 102.

## 4. Verdicts

All 23 hold. n is the scored trials (or runs) of the cell; ranges are over those trials unless stated.

| Prediction | id | Cell (n) | Hits | Verdict | Values |
|---|---|---|--:|---|---|
| Context-0 local QP error, both contexts busy, recovered transparently | P1a | `pr_dual_f1c0_b@prd` (10) | 10 | holds | per-context completion, slots and both final signals exact 10/10 |
| One round, restricted to context 0 (one QP) on both ranks | P1b | same (10) | 10 | holds | first recovered line `scope=0x1 qps=1` on both ranks, one recovered line per rank, rank-0 decision `reason=pair`, all 10 |
| Untouched pair's gates never closed or republished; faulted pair's published once | P1c | same (10) | 10 | holds | teardown epochs `[2,0,0,0]` on both ranks, all 10 |
| Context 1 completes iterations in context 0's held window, none overlapping it longer than 1 ms | P1d | same (10) | 10 | holds | iterations fully inside the window 6–9; longest overlapping 10.7–11.2 µs; window 3349.4–4195.1 µs |
| Context-0 peer QP error recovered transparently | P2a | `pr_dual_f3c0_b@prd` (10) | 10 | holds | per-context checks exact 10/10 |
| Retry-exceeded round restricted to context 0 on both ranks, context 1's gates untouched | P2b | same (10) | 10 | holds | rank-0 records `RETRY_EXC`, context 0 only; `scope=0x1 qps=1` both ranks; context-1 epoch 0 both ranks |
| Context 1 keeps going through the retry wait and the round | P2c | same (10) | 10 | holds | inside the window 1759–1871; longest overlapping 11.2–12.3 µs; window 3.539–3.764 s (see 5.3) |
| Initiator Commit at most half of the full reset, same hold | T1 | `f1c0` (10) vs `f1c0_full` (5), both H2 | | holds | rank 0 first (only) initiator line: medians 768 µs (743–785) vs 3315 µs (3283–3510), ratio 0.232 |
| Initiator whole round at most 0.6 of the full reset | T2 | same | | holds | medians 3013 µs (2934–3093) vs 11379 µs (11215–11645), ratio 0.265 |
| Every context of rank 0 broken (stock hook), both contexts recovered transparently | B1a | `pr_dual_f1all_b@prd` (10) | 10 | holds | |
| That case falls back to one full reset | B1b | same (10) | 10 | holds | one initiator line on rank 0, `qps=4` on both ranks; reason `queued` 9, `qp_state` 1 |
| Simultaneous rounds with different scopes both recover, no decline | B2a | `pr_bidirf_conflict_b@pr` (10) | 10 | holds | declines 0 on both ranks |
| Higher rank sees the conflict once, answers rank 0's context-0 round, then runs its fault as a full reset | B2b | same (10) | 10 | holds | conflict line 1 on rank 1; one initiator and one responder line on each rank; rank 1 initiator `qps=4` |
| Switch off: full reset (4 QPs each rank), transparent | C1a | `pr_dual_f1c0_full_b@prd` (5) | 5 | holds | rank-0 decision `reason=off` 5/5 |
| Under the full reset context 1 is held at least 1 ms | C1b | same (5) | 5 | holds | longest overlapping context-1 iteration 10732.4–11532.3 µs |
| No fault: transparent, no round, context 1 longest under 1 ms | C2 | `pr_dual_none_b@prd` (5) | 5 | holds | context 1 longest 15.9–16.4 µs; epochs `[0,0,0,0]` |
| Four recovered replication cells stay transparent | G1 | `f1_b`, `f3_b`, `bidirf_sym_b`, `mt256_f1_b` @pr (5 each) | 5 each | holds | |
| Stock-hook cells keep the full reset on both ranks | G2 | `f1_b`, `mt256_f1_b`, `bidirf_sym_b` @pr (5 each) | 5 each | holds | `qps=4` both ranks; rank-0 decision `qp_state` in 14 of 14 decision lines (`bidirf_sym_b` n1: rank 1 initiated, rank 0 has no decision line) |
| Existing peer QP error cell now restricted to context 0 | G3 | `f3_b@pr` (5) | 5 | holds | `scope=0x1`, `qps=1` both ranks, `reason=pair`, epochs `[2,0,0,0]` |
| Kill without mute declined with a death cause, survivor's abort returns | G4 | `f4_b@pr` (5) | 5 | holds | "RETRY_EXC and the peer's socket shows FIN" 5/5; rank-0 abort `no error` |
| Receiving rank's wait released at abort | G5 | `f2rel_b@pr` (5) | 5 | holds | rank-1 abort `no error`, `r1rc=3`, 859.0–871.8 ms, `async_error_kernel_stuck` |
| 4 KiB latency, pr vs rc, within 0.40 µs | L1 | 5 + 5 runs, H1 | | holds | medians 10.56 vs 10.56 µs, difference 0.00; per-run p50 10.56–10.59 on both builds |
| 256 KiB latency, pr vs rc, within 0.30 µs | L2 | 5 + 5 runs, H1 | | holds | medians 38.91 vs 38.91 µs, difference 0.00; per-run p50 38.88–38.91 on both builds |

## 5. Detail

### 5.1 Round scope and QP count `[measured]`

First recovered line per rank (scope, QPs), all trials of the cell:
- `f1c0`, `f3c0`, `f3_b`: `0x1`/1 on both ranks; rank 0 initiator, rank 1 responder, one round.
- `f1all`, `f1c0_full`, `f1_b`, `mt256_f1_b`, `bidirf_sym_b`: `0xf`/4 on both ranks, one round.
- conflict: two rounds on each rank, first `0x1`/1, second `0xf`/4. `none`, `f4_b`, `f2rel_b`: no round.
- NIC cross-check: on rain (rank 0), per hold, the firmware counter growth minus the QPs that rank 0's recovered lines
  report as reset is exactly 8 `2RST_QP` and 32 `RST2INIT_QP` per trial that created QPs, in all six holds (H2: 190 and
  670 against 30 resets = 10 × 1 + 5 × 4; H3: 50 = 10 × 1 + 10 × 4; H4: 50 = 10 × (1 + 4)). So the per-round QP counts
  in the logs match what the NIC executed.

### 5.2 Gate epochs at teardown `[measured]`

Both ranks: `f1c0`, `f3c0`, `f3_b` `[2,0,0,0]`; `f1all`, `f1c0_full`, `f1_b`, `mt256_f1_b`, `bidirf_sym_b`, `f2rel_b`
`[2,2,2,2]`; conflict `[4,2,2,2]`; `none` `[0,0,0,0]`; `f4_b` rank 0 `[2,2,2,2]` (rank 1 killed, no line).

### 5.3 The held window

- Definition `[source]`: W is context 0's longest completed iteration (post to flush return, device globaltimer);
  `dual_c1_in_win` counts context-1 iterations with start and end inside W, `dual_c1_max_in_win_us` is the longest
  context-1 iteration that overlaps W. The driver code matches 3.1.
- kv consistency `[measured]`, 40/40 dual trials: W length equals `end_gt − start_gt` and context 0's `lat_max_us`
  (same iteration index); `dual_c1_max_us` equals `lat1_max_us`; the overlapping maximum does not exceed it;
  `dual_c1_end_after_win` agrees with the last context-1 end time. The in-window count is within 1.25 of
  W / (gap + mean context-1 iteration) in `f1c0` and `f3c0`.
- W against the round `[measured]`, mapped to rank 0's monotonic clock through rank 0's first device record (which
  carries both clocks; uncertainty of tens of µs): in `f1c0` W starts 0.20–1.10 ms before the round start and ends
  0.050–0.105 ms after re-post, covering the round in 10/10. In `f1c0_full` it covers in 4/5 (n1 ends 0.007 ms before
  re-post, inside the anchor uncertainty).
- `f3c0` `[measured]`: W is 3.539–3.764 s and starts 3536–3761 ms before the round; the round (decision to re-post
  2.61–2.71 ms) is its last part. The in-window count (1759–1871) therefore comes almost entirely from the retry wait.
  That context 1 also completed iterations during the round itself is `[inferred]`: its period is 2.01 ms (gap 2000 µs),
  shorter than the round, it was still running after W in all 10, and no overlapping iteration exceeded 12.3 µs.
- Context-1 p50 and p99 per trial: `f1c0` 10.53–10.69 and 11.17–12.38 µs, `none` 10.62–10.66 and 11.17–12.06 µs.

### 5.4 Times (rank 0's clock, rank 1 moved with `clock_offset_ms`) `[measured]`

- `f1c0`: hook fire to rank 0's first record 0.405–0.708 ms, record to decision 0.250–1.175 ms, decision to re-post
  2.747–2.906 ms; responder Commit 861–903 µs. Full reset: responder Commit 3755–3848 µs (median ratio 882.5/3805 = 0.232,
  not predicted).
- `f3c0`: rank 1 fire to rank 0's retry-exceeded record 3535.7–3762.3 ms, decision to re-post 2.609–2.706 ms; initiator
  Commit 755–780 µs, responder 882–926 µs. `f1all` initiator Commit 3255–3413 µs, round 10343–11233 µs.
- `f3_b@pr`: rank 1 fire to rank 0's record 3523.3–3791.3 ms; initiator Commit 756–775 µs. Rank 1's stock hook moved
  4/4 of its QPs to ERR; only context 0 was reset, rank 1's contexts 1–3 keep epoch 0 `[inferred: left in ERR, by the
  design of section 4]`.

### 5.5 All-contexts fallback `[measured]`

Reason `queued` in n1, n2, n4–n10, `qp_state` in n3. Every trial: one round, one initiator line, `qps=4` both ranks,
teardown `rounds=1`, two device records on rank 0 (contexts 0 and 1, 0.07–0.43 ms apart). The decision line came before
the stock hook's `done_mono_ms` in n1, n6, n7, n8, n10, and rank 0's first device record was context 1's in n2 and n4.

### 5.6 Scope conflict sequence (all 11, including n10) `[measured]`

Rank 1: hook fire (context 1), device record, decision `scope=0x2 reason=pair`, conflict line ("REQ round 1 from rank 0
scope=0x1, ours scope=0x2"), `recovery aborted`, responder line `scope=0x1 qps=1`, decision round 2 `scope=0xf
reason=requeued`, initiator line `scope=0xf qps=4`. Rank 0: decision `0x1 pair`, stall line, "the lower rank keeps the
initiator role", initiator `0x1`/1 (`tie_kept=1`), then responder `0xf`/4. No decline, epochs `[4,2,2,2]` on both ranks.
Rank 1 responder Commit 934–998 µs, its full-round Commit 3612–3787 µs, its first record to its full-round re-post
29.79–31.13 ms (scored 10).

### 5.7 Replication paths `[measured]`

`f1_b`, `mt256_f1_b`: rank 0 initiates, `qp_state`, full. `bidirf_sym_b`: rank 0 initiates in 4 (both ranks log a
`qp_state` decision), rank 1 in n1; full on both ranks. `f3_b`: `pair`, context 0. `f4_b`: rank 0 declines (FIN), no
decision line, `r0rc=4`, `r1rc=255`. `f2rel_b`: rank 0 declines (`REM_ACCESS` not recoverable), rank 1 "the peer
declined", no decision line.

## 6. Safety per hold `[measured]`

| Hold | rain mlx5 lines | sunny mlx5 lines | new lines | command-error lines (rain, sunny) | rain firmware failed sum | GPU users listed | `left` |
|---|---|---|--:|---|---|--:|---|
| H1 | 66 → 66 | 509 → 509 | 0 | 2 → 2, 0 → 0 | 31 → 31 | 0 | 0 (50 trials) |
| H2 | 66 → 66 | 509 → 509 | 0 | 2 → 2, 0 → 0 | 31 → 31 | 0 | 0 (20) |
| H3 | 66 → 66 | 509 → 509 | 0 | 2 → 2, 0 → 0 | 31 → 31 | 0 | 0 (20) |
| H4 | 66 → 66 | 509 → 509 | 0 | 2 → 2, 0 → 0 | 31 → 31 | 0 | 0 (10) |
| fill 1 | 66 → 66 | 509 → 509 | 0 | 2 → 2, 0 → 0 | 31 → 31 | 0 | 0 (1) |
| fill 2 | 66 → 66 | 509 → 509 | 0 | 2 → 2, 0 → 0 | 31 → 31 | 0 | 0 (1) |

New lines are recomputed as the multiset difference of the before and after files; every `mlx5_new_*.txt` is empty.
`sunny_busy_after=0` in every `hold_*.out`, no `STOP_mlx5`. Smoke (not scored): 11 trials, all transparent, no new mlx5
line; both smoke conflict trials have `r1_q4_in_stall = 1` (12.8–12.9 ms inside), as `DEVIATIONS.md` 1 says.

## 7. Section 15 against the raw data

Supported `[measured]`: every number in the verdict table, the per-cell time lines (hook to record, record to decision,
decision to re-post, Commit and round ranges on both roles, window lengths, in-window counts and maxima, conflict
29.8–31.1 ms), the reason split 9/1, the replication paths (14 `qp_state` decisions, `bidirf_sym_b_n1` without a
rank-0 decision), the latency per-run ranges, and the mlx5 paragraph. The T1/T2 ratios and L1/L2 differences use
same-hold cells only. No other day's or other study's data is presented as the same cell; the 0.8 ms per QP and "about
half" in the interpretation are labelled as inference from section 1.

Discrepancies and unsupported statements:
1. n10 exclusion margin. Sections 12 and 15 say rank 1's first record was 0.15 ms after the window end. By the 3.1
   definition (rank-1 `mono_ms` minus rank 0's `clock_offset_ms`, window `[t, t + 18]`) it is 0.197 ms. The exclusion
   itself is unchanged. How 0.15 was obtained is `[unverified]`.
2. All-contexts bullet: "(문맥 1의 기록이 같은 묶음에 있었다)". In n2 and n4 rank 0's first device record was context 1's,
   so the other record found pending was presumably context 0's `[inferred]`. Whether it was in the helper's current
   batch or in the queue is not in the logs `[unverified]`.
3. Interpretation: "그래서 그 경우 QUERY_QP는 대개 돌지 않았다". Not visible in the logs; rain's `QUERY_QP` counter has a
   per-trial component that does not separate cleanly by cell `[unverified]`.
4. Interpretation: the in-window context-1 maximum (10.7–12.3 µs, over 6–9 iterations in `f1c0`) is compared with the
   no-fault maximum over 3000 iterations (15.9–16.4 µs). The sample sizes differ; the conclusion still holds against the
   no-fault p99 (11.17–12.06 µs).
5. Table row for the peer error ("재시도 기다림과 라운드 내내 문맥 1이 돈다"): the measured in-window count is the retry wait;
   the round part rests on the inference in 5.3, and none of the window keys can be recomputed from iterations (section 1).

Outside section 15 (facts only): the section 4 premise paragraph added after the tag is labelled inline as a
post-registration addition but is not listed in section 13 or `DEVIATIONS.md`. It does not touch the frozen sections.
