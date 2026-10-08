# gin-pair-check: independent recount (QA)

Date 2026-10-08. Recount by a separate agent from the raw per-trial files only. Tags: `[measured]` read from raw files,
`[source]` read from code, `[inferred]` interpretation, `[unverified]` not checked.

## 1. Method

- Script: [`../../qa/recount.py`](../../qa/recount.py). Run from the study folder: `python3 -B qa/recount.py`
  (optional `--csv <path>` writes the per-trial table elsewhere). It prints the pre-registration check, trial set,
  holds, exclusions, configuration and bundle checks, the 25 verdicts, the values below and the hold safety records.
  It writes nothing into the repository. Nothing was run on the cluster.
- Not read or run: `score.py`, `rows_pc.py` (neither the script nor its output), `SCORE.md`, `trials_scored.csv`, the
  untracked `trials_*.csv`. `EXPERIMENT.md` section 15 was read only after the recount was finished.
- Read only for log formats and definitions: `EXPERIMENT.md` 3.1, 3.2, 7, 8, 9, `../s2_close/EXPERIMENT.md` 3.1–3.2,
  `../pair_reset/EXPERIMENT.md` 3.1 and 9, `../scripts/ts2/rows.py`, `../s2_close/rows_extra.py`,
  `../scripts/ts2/run_trial.sh`, this folder's `cells.sh`, `hold.sh`, `chain.sh`, the latency statistics in
  `../gin_ts2.cu`, and the `gpc-` lines of the session's `cluster_run.log`. Nothing is imported. `transparent_ok`,
  `bind_fail`, `ua_r*` and `killed` are re-implemented from the `rows.py` and `rows_extra.py` definitions (independent in
  code, not in definition).
- Inputs: `<stem>_meta.txt`, `_r{0,1}.kv`, `_r{0,1}.log`, `_kill.out`, `_lat_raw.csv.gz` in `lat/`, `rep_pc/`, `dual/`,
  `f3/`, `conflict/`, plus `chain.out`, `hold_*.out`, `snap_*.txt`, `mlx5_*.txt`, `fwcmd_*.txt`.
- Rules: the `acceptance` text of `predictions.csv` is evaluated verbatim with a new evaluator (blank is NA, any
  comparison or arithmetic with NA is false, `per cell:` per listed cell, a two-cell rule needs both cells full).
- Parse coverage over all 222 rank logs (raw substring lines / parsed lines): fault fired 105/105, scope decision
  140/140, recovered 162/162, responder check 50/50, rerun 35/35, scope conflict 20/20, gate epochs 215/215, QP states
  185/185, pair reset 220/220, pair check 190/190, test stall 20/20, declined 15/15, device-side classification records
  110/110.
- Latency: every run's p50 was recomputed from its 3000 raw samples with the driver's rule (`v[int(0.5*(n-1)+0.5)]`).
  All 20 equal the kv `lat_p50_us`.
- Limitation: the dual-context runs keep no per-iteration times, so `dual_c1_in_win`, `dual_c1_max_in_win_us` and
  `dual_c1_end_after_win` come from the rank-0 kv as 3.1 defines them. They were checked for consistency only (window
  length and index equal `lat_max_us` and `lat_max_it`, longest overlapping context-1 iteration at most `lat1_max_us`,
  `dual_c1_end_after_win` agrees with the two end stamps): 40/40 runs consistent.

## 2. Pre-registration integrity `[measured]`

- Tag `prereg/gin-pair-check-v1` resolves to commit `27edc62c`. `sha256(predictions.csv)` = `a8a4b04602b0…`, the value
  in `PREREG.txt`. `predictions.csv` (25 rows) and `PREREG.txt` are byte-identical to the tag; no commit after the tag
  touches them.
- `EXPERIMENT.md` sections 2, 3, 7 and 8 are byte-identical to the tag. Changed since the tag: the header table and
  sections 5, 10–15.

## 3. Trial set, holds, exclusion, refill, bundles `[measured]`

- 111 trial files: 90 cell trials scored, 20 latency runs scored, 1 set apart. 18 cells, each with exactly its planned
  scored count from section 7 (10 for the four new cells, 5 for every control, replication and latency cell). No extra
  or missing cell.
- Holds (window from `hold_<H>.out`, trial placed by its first log stamp and by its meta file time; the two agree for
  all 111):

  | hold | run window | trials | cells |
  |---|---|--:|---|
  | H1 | 13:59:23–14:03:03 | 45 | 20 latency runs (pr 4 KiB, pr 256 KiB, pc 4 KiB, pc 256 KiB in turn, 5 rounds), then the five replication cells on `pc` |
  | H2 | 14:04:08–14:07:29 | 30 | clean responder n1–n10 interleaved 2:1 with the `pr` reference n1–n5, then responder-broken n1–n10, responder switch off n1–n5 |
  | H3 | 14:10:07–14:13:56 | 25 | `f3_b@pc` n1–n10 interleaved 2:1 with the check-off control n1–n5, then the two dual replication cells |
  | H4 | 14:16:35–14:17:14 | 10 | conflict cell n1–n10 |
  | fill | 14:39:28–14:39:35 | 1 | clean responder n11 |

- Exclusion (section 8, applied anew): one trial, `dual/pc_dual_f1c0_b_n10` (H2), `bind: Address already in use` in the
  rank-0 log, `r0rc=1`, `r1rc=7`, no kv results. It is the only exclusion. No trial failed a fault-applied rule
  (every hook fired, `trigger_miss` 0, all 5 kills recorded), no clean-responder trial had context 1 finish before the
  held window (`dual_c1_end_after_win` 1 in all 10 scored), every responder-broken trial had rank 1's hook fire before
  rank 0's first scope decision (`r1_fire_before_dec` 1, lead 99.9–101.0 ms, n=10), every conflict trial had
  `r1_q4_in_stall` 1 (n=10).
- Refill: n11, the next number, in its own hold `fill`. It passes every exclusion rule. Refills are 1 of 10 planned
  (limit 50%). `chain.out` shows a first `fill` start at 14:17:31 with no rc line and a second at 14:34:25 with rc 0;
  the session `cluster_run.log` has no `gpc-fill` line before 14:38:57 (the lock was held by another study's runs from
  14:17:14 to 14:38:57).
- Configuration checks of section 8: none fails on the 110 scored trials (`ts_on` and abort-flag lines on both ranks;
  `pair reset` 1 on both ranks except rank 1 of the switch-off cell, 0; `pair check` 1 on both ranks except the
  check-off control, 0; `dual=1` on both ranks of every `pcd` and `prd` trial; fault context as required per cell).
- Bundle per trial: meta `bundle=` is `.../gin_ts2/pc` for all 60 `pc` trials, `/pcd` for 35, `/pr` for 10, `/prd` for 5.
  Consistent with the logs: every `pc` and `pcd` trial has the `pair check` start line on both ranks, no `pr` or `prd`
  trial has it, and only `pcd` and `prd` trials have kv `dual=1`. Library md5 per trial is not in the raw files
  `[unverified]`.
- `left=0` in all 111 meta files and all hold outputs.

## 4. Predictions `[measured]`

n is the scored trials (or runs) of the cell. Ranges are over those n trials, one value per trial, unless stated.

| prediction | id | cell | n | hits | verdict | recomputed values |
|---|---|---|--:|--:|---|---|
| The stock peer-QP-error hook (all four of rank 1's QPs to ERR) is recovered transparently | A1 | `f3_b@pc` | 10 | 10 | holds | rank 1 hook `moved 4/4` in 10/10 |
| Rank 1 refuses the narrowed scope once (3 QPs not RTS) and rank 0 reruns as a full reset (4 QPs each rank) | A2 | `f3_b@pc` | 10 | 10 | holds | decisions `0x1 pair` then `0xf peer`; refusal `checked=3 not_rts=3`, check 232–299 µs (median 259); one rerun line; one recovery line per rank, `scope=0xf qps=4` |
| No QP left outside RTS on either rank at teardown | A3 | `f3_b@pc` | 10 | 10 | holds | QP states `[3,3,3,3]` both ranks; epochs `[2,2,2,2]` both ranks |
| Rank 0's context-0 local error recovered transparently while rank 1's idle context-2 QP is already broken | B1 | `pc_dual_f1c0_r1c2_b@pcd` | 10 | 10 | holds | rank 1 hook `context=2` in 10/10 |
| Rank 1 refuses (one QP outside the scope not RTS) and rank 0 reruns as a full reset | B2 | same | 10 | 10 | holds | refusal `checked=3 not_rts=1`, check 234–282 µs (median 242); one rerun; `scope=0xf qps=4` both ranks |
| No QP left outside RTS at teardown (rank 1's context 2 included) | B3 | same | 10 | 10 | holds | QP states `[3,3,3,3]`, epochs `[2,2,2,2]`, both ranks |
| Clean responder: context-0 local error recovered transparently | C1 | `pc_dual_f1c0_b@pcd` | 10 | 10 | holds | n1–n9 (H2) and n11 (fill) |
| Clean responder: round stays narrowed to context 0 on both ranks; rank 1 checks once, accepts, no refusal | C2 | same | 10 | 10 | holds | one recovery line per rank, `scope=0x1 qps=1`; one accept line, `checked=3`, check 222–245 µs (median 231.5); 0 refusals |
| Context 1 keeps completing iterations while context 0 is held, none overlapping the window longer than 1 ms | C3 | same | 10 | 10 | holds | context-1 iterations inside the window 7–9; longest overlapping iteration 10.6–11.2 µs |
| Untouched pair stays at epoch 0, faulted pair published once, every QP RTS at teardown | C4 | same | 10 | 10 | holds | epochs `[2,0,0,0]` both ranks; QP states `[3,3,3,3]` both ranks |
| Initiator commit median at most 1.15 x that of the `pr` build in the same hold | T1 | `pc_dual_f1c0_b@pcd` vs `pr_dual_f1c0_b@prd` | 10 / 5 | – | holds | medians 752.5 vs 762 µs, ratio 0.988 (pc 737–794, pr 747–772) |
| Initiator round median at most 1000 µs above `pr` (same hold) | T2 | same | 10 / 5 | – | holds | medians 3256.5 vs 2998 µs, difference 258.5 (pc 3132–3290, pr 2969–3049) |
| Simultaneous rounds with different scopes both recovered, nothing declined | E1 | `pc_bidirf_conflict_b@pc` | 10 | 10 | holds | transparent 10/10; `decl_r0`, `decl_r1` blank in 10/10 |
| After the conflict rank 1 re-decides and runs only the context-1 pair; contexts 2 and 3 never reset | E2 | same | 10 | 0 | **fails** | see section 5 |
| Every QP RTS at teardown on both ranks | E3 | same | 10 | 10 | holds | QP states `[3,3,3,3]` both ranks |
| Check off: narrowed, transparent, rank 1's three other QPs left not RTS (the measure sees the defect) | K1 | `f3_b_nocheck@pc` | 5 | 5 | holds | `scope=0x1 qps=1` both ranks; QP states rank 0 `[3,3,3,3]`, rank 1 `[3,6,6,6]`; epochs `[2,0,0,0]`; no check lines |
| Responder's own pair reset off: refuses with reason off, round reruns as a full reset | K2 | `pc_dual_f1c0_r1off_b@pcd` | 5 | 5 | holds | refusal `reason=off checked=0 check_us=0`; one rerun; `qps=4` both ranks; transparent 5/5 |
| `pr` reference transparent and narrowed | K3 | `pr_dual_f1c0_b@prd` | 5 | 5 | holds | `scope=0x1 qps=1` both ranks |
| Recovered replication cells stay transparent | G1 | `f1_b`, `bidirf_sym_b`, `mt256_f1_b` (`@pc`), `pc_dual_f3c0_b`, `pc_dual_f1all_b` (`@pcd`) | 5 each | 5 each | holds | |
| Every QP RTS at teardown after recovery | G2 | same | 5 each | 5 each | holds | QP states `[3,3,3,3]` both ranks in all 25 |
| Dual peer-QP error on rank 1's context 0 stays narrowed, no refusal | G3 | `pc_dual_f3c0_b@pcd` | 5 | 5 | holds | `scope=0x1 qps=1` both ranks; rank 1 accepted, `checked=3`, check 233–251 µs |
| Kill without a mute declined with a death cause, surviving rank's abort returns | G4 | `f4_b@pc` | 5 | 5 | holds | `decl_r0` "RETRY_EXC and the peer's socket shows FIN" 5/5; abort `no error` |
| Receiving rank's own wait released at abort | G5 | `f2rel_b@pc` | 5 | 5 | holds | abort `no error`, `r1rc` 3, rank 1 abort 856.6–867.1 ms, outcome `async_error_kernel_stuck` |
| Fault-free 4 KiB latency differs by at most 0.40 µs | L1 | `lat_pc_on_4k@pc` vs `lat_pr_on_4k@pr` | 5 / 5 runs | – | holds | median of run p50s 10.59 vs 10.59 (both 10.56–10.59 over 5 runs) |
| Fault-free 256 KiB latency differs by at most 0.30 µs | L2 | `lat_pc_on_256k@pc` vs `lat_pr_on_256k@pr` | 5 / 5 runs | – | holds | 38.91 vs 38.91 (pc 38.91 in all 5, pr 38.88–38.91) |

Total: 24 hold, 1 fails (E2), 0 insufficient data.

**Same-hold comparison without the refill (T1, T2).** The `pc` cell's n11 ran in the fill hold, the `pr` cell only in
H2. With n11 left out (n=9, all H2): commit median 752 µs, ratio 0.987; round median 3261 µs, difference 263 µs. Both
still hold. n11 alone: commit 757 µs, round 3233 µs, check 237 µs, 9 context-1 iterations in the window, longest 11.1 µs,
all inside the H2 ranges.

**Refusal and rerun pairing.** Over all 110 scored trials the number of rank-1 refusals equals the number of rank-0 rerun
lines in every trial (one each in the 35 trials of the four refusing cells, zero elsewhere). Rank 0 never wrote a check
line.

## 5. The conflict cell and the failing prediction (E2) `[measured]`

E2 predicted that after the scope conflict rank 1 would re-decide its own fault, run it as a context-1 pair round as
initiator, with one conflict line and epochs `[2,2,0,0]` on both ranks. All 10 trials followed one identical path:

| step | rank 0 | rank 1 |
|---|---|---|
| 1 | hook on context 0; decides round 1 `scope=0x1 reason=pair`; test stall 20 ms after quiesce | hook on context 1 (5.6–5.8 ms after rank 0's, rank 0 clock); decides round 1 `scope=0x2 reason=pair` |
| 2 | keeps its round (tie-break) | conflict line 1: REQ `0x1` vs ours `0x2`, "requeued for a new scope decision" |
| 3 | | checks rank 0's `0x1` REQ: `checked=3 not_rts=1`, refused `not_rts` (211–243 µs) |
| 4 | rerun line; decides round 2 `scope=0xf reason=peer` | re-decides its own fault: round 2 `scope=0x2 reason=pair` |
| 5 | keeps its round again (tie-break line twice per trial, 10/10) | conflict line 2: REQ `0xf` vs ours `0x2`, "requeued as a full reset"; answers the full REQ |
| 6 | one recovery line, initiator, `scope=0xf qps=4` | one recovery line, responder, `scope=0xf qps=4`; no further decision or initiator line |
| end | epochs `[2,2,2,2]`, QP states `[3,3,3,3]` | epochs `[2,2,2,2]`, QP states `[3,3,3,3]` |

E2 sub-conditions met (of 10): `conflict_r1 == 1` 0 (2 in all), `init_qps_r1 == 1` 0 (blank, rank 1 never recovered as
initiator), `last_reason_r1 == "pair"` 10, `ep_c0`/`ep_c1 == 2` on both ranks 10, `ep_c2`/`ep_c3 == 0` on both ranks 0.
So rank 1 did re-decide a pair scope; the pair round never ran because rank 1's own refusal of the narrowed REQ made rank 0
rerun as a full reset, which collided with the re-decided round and recovered both faults at once. Why rank 1's record,
requeued as a full reset, opened no third round is not logged; the epoch check discarding a covered record would explain
it `[inferred]`. Timing on rank 0: first decision to rerun line 20.86–20.96 ms, to second decision 21.93–22.04 ms, to
resume 52.99–53.33 ms; two test stalls per trial.

## 6. Safety per hold `[measured]`

Recomputed from the before and after snapshots (set difference of mlx5 lines per node; command-error lines are mlx5 lines
with `cmd` or `command` and `failed`, `timeout` or `leak`; firmware failure sum is `failed` + `failed_mbox_status` over
rain's command counters).

| hold | trials | mlx5 lines rain / sunny (before = after) | new mlx5 lines | command-error lines rain / sunny | rain firmware failures | QUERY_QP / 2RST_QP added | GPU process lines in snapshots | `left>0` |
|---|--:|---|--:|---|---|---|--:|--:|
| H1 | 45 | 66 / 509 | 0 | 2 / 0, unchanged | 31 → 31 | 1543 / 424 | 0 | 0 |
| H2 | 30 | 66 / 509 | 0 | 2 / 0, unchanged | 31 → 31 | 1158 / 306 | 0 | 0 |
| H3 | 25 | 66 / 509 | 0 | 2 / 0, unchanged | 31 → 31 | 1011 / 270 | 0 | 0 |
| H4 | 10 | 66 / 509 | 0 | 2 / 0, unchanged | 31 → 31 | 440 / 120 | 0 | 0 |
| fill | 1 | 66 / 509 | 0 | 2 / 0, unchanged | 31 → 31 | 37 / 9 | 0 | 0 |

The two rain command-error lines are the 2026-09-25 `2ERR_QP` timeout lines that predate this study. No `STOP_mlx5`
file. `mlx5_new_<hold>.txt` is empty for all five holds. An empty GPU process list could also mean the query returned
nothing `[unverified]`.

## 7. EXPERIMENT.md section 15 against the raw data

Every verdict, n and hit count in the section 15 table matches the recount. Every range and median in 15.1–15.9 was
recomputed and matches (to the stated rounding), including the timing values (hook to first classification record,
first decision to rerun, to second decision, to resume, context-1 overlap in the refusing cells, conflict-cell timings).
The section 15.3 inference that the 258.5 µs round difference comes from the serial check is consistent with the
initiator `handshake_us` medians, 1949 (pc, n=10) vs 1722 µs (pr, n=5), a 227 µs difference `[measured]`.

Not supported or imprecise:

1. **Smoke count.** Section 15 (also 12 and 14) says 14 smoke trials. `results/20261008_smoke/smoke/` has 13 trial meta
   files and `hold_H0.out` 13 trial result lines; `hold.sh` H0 schedules 13 (9 from this folder, 1 `pr` dual, 1 `pr`
   latency, 2 `f3_b@pc`).
2. **"270 values identical to `trials_scored.csv`".** Over the 110 scored trials the raw logs hold 175 non-blank values of
   these three columns (80 rank-0 commit, 80 rank-0 round, 15 rank-1 accepted check). 270 equals 90 non-latency trials x
   3 columns, so the count apparently includes 95 blank cells `[inferred]`. The comparison itself was not repeated here
   (`trials_scored.csv` not read).
3. **Rounded medians.** 15.1 gives the full-rerun round median as 10 154 µs; it is 10 154.5. 15.3 gives the accept-check
   median as 232 µs; it is 231.5. Both are rounding only.
4. **Tag in 15.6 step 2.** "rank 1's own context-1 QP is in ERR outside the scope" is marked `[measured]`, but the refusal
   line gives only `checked=3 not_rts=1`, not which context. That it is context 1 follows from rank 1's hook line
   (`context=1`) and should carry `[inferred]`.

Not checkable from the raw data (DEVIATIONS.md 4): the 14:17:22 file times of the intermediate `SCORE.md` and
`trials_scored.csv` (since overwritten, and not read here), the empty `hold_fill.out` of the first fill attempt (the file
was overwritten by the second attempt), and "no `gin_ts2` process on rain or sunny at 14:28" `[unverified]`. The
lock record and `chain.out` agree that the first attempt never reached the lock.
