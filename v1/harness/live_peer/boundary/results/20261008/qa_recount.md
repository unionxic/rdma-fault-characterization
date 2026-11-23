# live_boundary: independent recount (QA)

Recount of the main run of 2026-10-08 (110 trials) from raw files, done on 2026-10-08 by a separate agent that
did not read the scorer or its outputs. Labels: `[measured]` read or computed from raw files, `[inference]` interpretation,
`[unverified]` not checked. Ranges are min–max over the trials named next to them.

## Method

- **Read:** `predictions.csv`, `PREREG.txt`, `DEVIATIONS.md`, EXPERIMENT.md sections 2, 3, 7, 8 (section 15 only
  after the recount), raw files under `CP/`, `CG/`, `G/` (per-trial CSV, server log, `.pstate`, `.out`; GIN
  `*_r0.kv`, `*_r1.kv`, `*_meta.txt`, `*_r0.log`, `*_r1.log`), `trials.log`, `runner_CPU.log`, `runner_GIN.log`.
  Sources were read only for formats and clocks (`probe_client.c`, `probe_server.c`, `lp_stall.h`, `run.sh`,
  `run_points.sh`, `deploy.sh`, `cluster_run.sh`). The deploy and block records came from the session scratchpad
  (`lb_chain1.out`, `lb_chain2.out`, `lb_chain1.sh`, `lb_chain2.sh`, `cluster_run.log`).
- **Not read or run:** `score.py`, `SCORE.md`, `score.json`, `trials_scored.csv`. Nothing was run on the cluster.
  The only live reads were local and read-only on rain at 14:48: md5sum of the bundle and harness binaries,
  `pgrep`, the dmesg count, the port state.
- **Script:** [../../qa/recount.py](../../qa/recount.py). It takes the `acceptance` strings verbatim from
  `predictions.csv` and evaluates them with the section 3.0 grammar: clauses split on `; `, optional
  `<cells>:` or `pooled <cells> where <cond>:` scope, default scope from the `cells` column, and
  `ALL`, `MOST`, `NONE`, `COUNT`, `N()`, `MAX`, `MIN`. Fields follow the section 3.0 definitions.

```
cd harness/live_peer/boundary && python3 qa/recount.py results/20261008
```

- **Missing fields.** Section 3.0 says a trial with a missing field is false in `ALL`. I evaluate each
  expression left to right with short-circuit, so a field that is never reached does not count as missing.
  Only the 2995 ms GIN prediction (Gb) depends on this: its clause
  `ALL(rec_outcome=='declined' or rec_t_ack-rec_t_prep<=3001.2)` holds under this reading and fails under a
  literal "any missing field" reading, because the declined trial `g2995_t8` has no `t_ack`. The `declined or`
  form shows the clause meant to exempt declined trials, so the verdict below uses short-circuit.

## Pre-registration integrity `[measured]`

- `predictions.csv` sha256 `1a75fbf15214779024498b33cc20515a5f9f2e17aee5bf054d73c0d0ba999d7e` matches
  `PREREG.txt` and the blob in tag `prereg/live-boundary-v1`, which points to commit `0e251887`.
- EXPERIMENT.md sections 2, 3, 7 and 8 are line-for-line identical to the tagged version. Section 5 changed after
  the tag (testbed records filled in); it is not a frozen section.

## Trial set, exclusions, identity

- **Cells (section 7) `[measured]`:** every cell has exactly its planned count with contiguous `t1`..`tn`:
  PROBE-stop cells 0, 900, 990, 1040, 1100 ms with 5 each and 1008, 1024 ms with 10 each (45); fault-stop
  cells 4300, 5000 ms with 5 each and 4600 ms with 10 (20); GIN cells 2900, 2985, 2992, 3010, 3100 ms with
  5 each and 2995, 2998 ms with 10 each (45). Total 110, `rc=0` in all 110 `trials.log` lines.
- **Exclusions (section 8) `[measured]`:** fault not applied 0 (every CPU server log has `fault_applied`, every
  stop trial has `stall_end`, every GIN r0 kv has `fault ev=` and every r1 kv a `stall` record with
  `end_mono_ms`), runner failures 0 (one CSV row per CPU trial, all four kv/meta files per GIN trial), extra
  trials 0 (runner logs: `extra 0` for all 17 points).
- **Smoke `[measured]`:** 17 trials in `results/20261008_smoke/`, CSV stamps 14:08:01–14:09:26, kept apart from
  the main CSV stamps 14:17:46–14:28:00. Not used.
- **Settings per trial `[measured]`:** server `LIVE_STOP_MS` equals the tag in 65/65; every PROBE-stop trial with
  a stop logs `stall_begin ... on=probe` (40/40); the fault is `live_stop_probe` in 45/45 PROBE-stop and
  `live_stop_err` in 20/20 fault-stop runs; GIN r1 stall switch equals the tag with `on=req` in 45/45; meta
  `bundle=gin_recovery_gpudb_stall` 45/45; NCCL `2.32.3+cuda12.8` 45/45.
- **Build identity, CPU harness:** rain `probe_client` `a9c481f2`, `probe_server` `c3f24990` at QA time, mtime
  13:58:37, so the 65 per-trial `make` runs rebuilt nothing; sources were last modified at or before 13:58:36,
  equal HEAD, and the last commit touching them is `b5657f88` `[measured]`. The sunny copy hashed
  `3c06e360` / `413c52e6` in the deploy output at 14:03:34–14:03:37 `[measured]`. It was not re-hashed after the
  per-trial resync `[unverified]`; its logs print the `on=probe` record that exists only in the new source
  `[inference]`.
- **Build identity, GIN and evrec:** the deploy output lists `gin_rec` `fac97c8c`, `libnccl.so.2.32.3`
  `1ed8e0a1` and `evrec` `3f93b3a9` on both nodes, and `deploy.sh` exited 0 (it exits 1 on any mismatch). At QA
  time rain shows the same hashes with mtimes of 2026-10-07 19:29 `[measured]`. Sunny was not checked at QA time.
- The deploy output and the block records are only in the session scratchpad (`lb_chain1.out`,
  `lb_chain2.out`, `cluster_run.log`), not under `results/` (see discrepancy 8).

## Per-prediction verdicts

n counts trials after exclusions. "Hits" counts trials that meet the per-trial condition.

| Key | What was predicted | Scope, n | Hits | Verdict | Observed (range is over) |
|---|---|---|---|---|---|
| CPa | Stop of 0, 900, 990 ms on the PROBE: every trial answered, answer 0–5 ms after the measured stop | 3 cells, 15 | 15/15 | holds | answer − stop 0.710–1.053 ms (15 trials) |
| CPb | 1008 ms stop: at least 4 of 10 answered | 1008, 10 | 9 answered | holds | the one no-answer trial (`lb_cp1008_t3`) waited 1001.592 ms |
| CPc | 1024 ms stop: at most 6 of 10 answered | 1024, 10 | 1 answered | holds | answered trial `lb_cp1024_t1` at 1025.032 ms; 9 waits 1001.897–1021.890 ms |
| CPd | 1040, 1100 ms stop: no answer in every trial, wait 1000–1033 ms | 2 cells, 10 | 10/10 | holds | wait 1002.231–1026.570 ms (10 trials) |
| CPe | Every PROBE-stop trial decided by whichever comes first, answer or wait end | 7 cells, 45 | 45/45 | holds | – |
| CPf | Pooled no-answer trials (both CPU groups): wait 1000–1033 ms, spread at least 16 ms | pooled, 28 | 28/28 | holds | 1001.592–1027.114 ms, spread 25.522 ms (28 trials) |
| CGa | Stop from the fault: 4300 ms always answered, 5000 ms never | 2 cells, 5 + 5 | 5/5, 5/5 | holds | – |
| CGb | Stop left after the first CQE (x): x ≤ 995 ms answered, x ≥ 1034 ms no answer | pooled, 12 and 6 | 12/12, 6/6 | holds | answered x 596.672–921.550 (12); no-answer x 1014.191–1476.759 (8); 2 trials between, both no answer |
| CGc | Answered fault-stop trials: answer x − 1 to x + 6 ms after the PROBE | pooled, 12 | 11/12 | **fails** | miss `lb_cg4600_t6`: answer 913.450 ms, x 901.595 ms, window 900.595–907.595 ms |
| Ga | GIN stop of 2900, 2985, 2992 ms: all recovered, ACK 4.0–5.5 ms after the stop end (anchored at Prepare end) | 3 cells, 15 | 15/15 | holds | ACK − Prepare end − stop 4.514–4.877 ms (15 trials) |
| Gb | GIN 2995 ms: no late-end decline, at least 5 of 10 recovered, every recovered ACK within 3001.2 ms of Prepare end | 2995, 10 | 0 late-end, 9 recovered, 9/9 ACK in time | holds (short-circuit reading) | ACK − Prepare end 2999.680–3000.074 ms (9); decline `g2995_t8` at 2999.185 ms after the fault query |
| Gc | GIN 2998, 3010, 3100 ms: all declined for handshake timeout, rank 0 exit code 9 | 3 cells, 20 | 20/20, exit 9 20/20 | holds | – |
| Gd | Pooled GIN declines: all 2998.8–3002.8 ms after the fault query, at most one in ten between the two ends (2999.9–3001.7 ms) | pooled, 21 | 21/21 in range, 5 between | **fails** | 2999.185–3002.221 ms (21); between 5/21 (24%), allowed at most 2 |
| Ge | GIN 2998 ms late-end declines: rank 1 resumed before the decline; every declined trial: rank 1 handled the request after resuming | pooled, 9 and 21 | 9/9, 21/21 | holds | resumed 2.532–2.801 ms before the decline (9) |

**Result: 12 of 14 measured predictions hold, 2 fail: answer timing in the fault-stop group (CGc) and the
decline-time distribution (Gd).** The three source rows (S1–S3) are not scored.

## Details

### CPU harness, stop on the PROBE `[measured]`

- Answer − measured stop: 0.934–1.053 ms over the 20 answered trials in the 900, 990, 1008, 1024 ms cells. With
  no stop, PROBE to answer took 0.710–0.756 ms (n=5).
- **The wait end sits on a fixed 32 ms grid.** On rain's `CLOCK_MONOTONIC` the PROBE leaves at
  ≈ `t_post_mono_ns + cqe_ns`, so the wait ends at that time plus `probe_ms`. Modulo 32 ms, 26 of the 28
  no-answer wait ends fall at 15.991–16.038 ms. The other two (`lb_cp1100_t2`, `lb_cp1100_t3`) fall at
  20.004–20.007 ms, exactly one 4 ms tick later. The wait end is therefore set by where the PROBE falls on that grid.
  It is not an independent draw per trial.
  - Applied to answered trials, the grid puts every would-be wait end after the answer, by 0.532 ms or more
    (closest: `lb_cp1008_t5`). No trial contradicts it.
  - `[inference]` This is the timer-wheel level-1 rounding to 8-jiffy boundaries that the source prediction S1
    describes. Why two trials ended one tick late is `[unverified]`.
- Trials in the same round-robin round sit ≈ 9.7 s apart, and their PROBE phases on the grid differ by
  ≈ 0.3 ms. So no-answer waits cluster by round. Example, round 3: 1001.592, 1001.897, 1002.231 ms, and
  1006.548 ms for the late-tick trial.
- Pooled no-answer waits: 1001.592–1027.114 ms (n=28). By group: PROBE stop 1001.592–1026.570 (n=20), stop from
  the fault 1005.126–1027.114 (n=8).

### CPU harness, stop from the fault `[measured]`

- Frozen x = `stall_meas_ms − cqe_ns/1e6`. The two trials between 995 and 1034 ms (x = 1014.191 and 1032.557,
  both 4600 ms cell) were not answered: their waits ended at 1005.770 and 1026.800 ms, before the stop ended.
- GOACK to stop start on the server clock (`stall_begin − fault_applied`): 0.061–0.138 ms in 19 trials, 10.852 ms
  in `lb_cg4600_t6`.
- Answer − x: 1.034–1.128 ms in the other 11 answered trials, 11.855 ms in `lb_cg4600_t6`. Answer − (x + stop
  start delay): 0.956–1.061 ms over all 12, `lb_cg4600_t6` 1.003 ms. The late stop start alone accounts for the
  missed prediction (CGc). Why the stop started 10.85 ms late is `[unverified]`.
- Cross-check from the PROBE-stop group: stop start − GOACK − first CQE time = 0.248–0.326 ms (n=40), the delay
  from the CQE to the PROBE reaching the server. When the stop starts on time, the frozen x is right to within
  ≈ 0.3 ms.
- First CQE time over all 65 CPU trials: 3501.5–3746.2 ms.

### GIN `[measured]`

- **Recovered trials** (n=24: all 15 in 2900–2992 plus 9 in 2995):
  - ACK − Prepare end − measured stop: 4.514–4.981 ms.
  - ACK − rank 1 stop end, on rank 0's clock (`clock_offset_ms`, RTT 0.099–0.109 ms): 4.229–4.659 ms. The two
    differ because rank 1's stop starts 1.223–1.585 ms after the fault query (45 trials), while Prepare ends
    1.066–1.200 ms after it (24 trials).
  - The ACK reaches rank 0 0.017–0.147 ms after rank 1's commit ends: rank 1 answers after its own prepare and
    commit.
- **Declines** (n=21), measured from the fault query:

  | Cell | Early end (≤ 2999.9 ms) | Between | Late end (≥ 3001.7 ms) |
  |---|---|---|---|
  | 2995 | 2999.185 | – | – |
  | 2998 | – | 3000.958 | 9 trials: 3002.108–3002.221 |
  | 3010 | – | 3001.498 | 4 trials: 3001.738–3002.188 |
  | 3100 | – | 3000.236, 3001.124, 3001.386 | 2 trials: 3002.177, 3002.211 |

  Totals: early end 1, between 5, late end 15. Three of the five between-end declines are in the 3100 ms cell.
- **2998 ms late-end declines** (n=9): rank 1 had resumed 2.532–2.801 ms before the decline, and its commit
  ended (ACK sent) 1.630–2.088 ms after the decline record.
- **All 21 declines:** rank 1 logged exactly one `rxrec` (ACK) record after its stop. In the 3010 and 3100 ms
  late-end declines, rank 1 resumed 9.275–10.010 and 99.226–101.094 ms after the decline, respectively. That is
  expected, and the first clause of Ge does not cover those cells.
- `g2900_t1` has fault query − kernel return = 13.112 ms; the other 44 GIN trials have 0.008–0.104 ms. The trial
  recovered, and no frozen field uses the kernel-return time, so no verdict changes.

## Safety records

- `[measured]` `.pstate` shows `state T seen` for sunny `probe_server` in all 60 stop trials.
- `[measured]` Neither runner log has a SIGCONT, STOP, leftover or extra-trial line. There is no `STOP` file, and
  both parts end with `part ... finished`.
- `[inference]` The runner logs only when it acts (`run_points.sh` `check_after`), so these logs mean:
  - after every trial, no process of ours was in state `T` on either node;
  - nothing of ours was left after 5 s;
  - the rain dmesg mlx5 command-error count never rose above its starting value of 2;
  - both ports stayed ACTIVE.

  Per-trial counts are not logged.
- `[measured]` Sunny `dmesg` was unreadable without sudo (`sunny=unreadable` at both starts), so only rain was
  checked, as section 8 allows.
- `[measured]` `cluster_run.log` shows all five blocks (deploy, CPU smoke, GIN smoke, CPU, GIN) with the lock
  held, an idle link (0 Mb/s), `rc=0` and `sunny_busy_after=0`. The chain scripts pass `-w 10800`.
- `[measured]` Every CPU trial has `verify_ok=1` (65/65). Every GIN r1 kv has `data_check=ok` and every meta
  `left=0` (45/45).
- `[measured]` QA-time read-only check on rain at 14:48 found none of `probe_server`, `probe_client`, `gin_rec`,
  `lp_stall` or `evrec` running, a dmesg count of 2, and port `mlx5_1` ACTIVE. Sunny was not checked.

## EXPERIMENT.md section 15 against the raw data

The raw data reproduces every count and range in section 15: 110 trials, 12 of 14 holding, 28 waits
1001.6–1027.1 ms with a spread of 25.5 ms, 9/10 and 1/10 answered, 0.710–0.756 and 0.934–1.053 ms, both x ranges,
the CQE range 3501.5–3746.2 ms, 1.03–1.13 against 11.86 ms, the 10.85 ms delay against 0.06–0.14 ms,
4.51–4.88 ms as ACK − Prepare end − stop, 2999.68–3000.07, the 2999.19 ms decline, 20/20 declined with exit 9,
2.53–2.80 ms, 21/21 rank-1 handling, and 2999.19–3002.22 with 5 between, 1 early and 15 late. The ≈ 1% figure is
the correct arithmetic under its own assumption ((27.1/32)^28 = 0.0095). The statements below go beyond the raw
data or mislabel it.

1. **"≈ 1% if uniform" and "why the top 5 ms is empty `[미확인]`" (item 1).**
   - The 1% figure treats the 28 waits as independent uniform draws, but the waits are locked to a 32 ms grid and
     correlated within rounds. Counting each of the 15 rounds that had a no-answer trial as one draw already gives
     ≈ 8% `[inference]`, and the rounds themselves drift smoothly.
   - On the grid, an empty top 5 ms only means that no PROBE fell in the one 4.9 ms phase window (8.0–12.9 ms
     modulo 32) that gives waits above 1027.1 ms `[measured]`. With phases correlated within rounds, that is not
     unusual.
2. **"Spread over about 30 ms after 1000 ms" (item 1 heading) and "PROBE + 1000–1027 ms" (item 1, inference).**
   The measured waits span 25.5 ms, from 1001.6 to 1027.1 ms. 32 ms is the source model's width, and 1000 is the
   source floor, not a measured value.
3. **The composition of the 0.710–0.756 ms (item 1).** "Two port-counter reads, a port-state query and the round
   trip" comes from reading the source (`probe_server.c:477-481`). It was not measured, yet section 15 says all
   of its content is `[측정]` unless tagged otherwise.
4. **"ACK 4.51–4.88 ms after the stop end" (item 3) and "4.5–4.9 ms of work" (item 3, inference).** The raw data
   supports these as ACK − Prepare end − measured stop. Measured directly against rank 1's stop end on rank 0's
   clock, the ACK came 4.229–4.617 ms later (n=15) and 4.229–4.659 ms over all 24 recovered trials, because
   rank 1's stop starts 0.116–0.379 ms after Prepare ends (n=24).
5. **"The source range (expiry 2998.0–3001.0 ms after) was right" (item 3, Gd inference).**
   - Decline records carry no Prepare or poll-start time, so poll expiry is not observable in declined trials. The
     claim holds only under assumed offsets: a Prepare time of 1.066–1.200 ms taken from recovered trials, plus
     the logging time.
   - The explanation that live_peer showed only the two ends because its sample was small is untested. Between-end
     declines concentrate by cell: 3 of 5 in the 3100 ms cell, 1 of 10 in the 2998 ms cell.
6. **Item 4 carries no `[추론]` labels.** "The boundary width came from the kernel timer rounding interval" and
   "the two failing rows were about the anchor definition and the poll-expiry distribution" are interpretations.
   The first is now well supported by the grid result in this recount (point 1 above), but section 15 does not
   show that evidence.

## Other discrepancies and notes

7. **Gb verdict depends on the missing-field reading** (see Method). It holds with short-circuit and fails
   with a literal reading. Section 16 should record which reading the scorer used.
8. **Deploy and block records are outside `results/`.** The md5 lines that section 5 cites, the `-w 10800`
   chain scripts and the `cluster_run.log` lines exist only in the session scratchpad (`lb_chain1.out`,
   `lb_chain2.out`, `lb_chain1.sh`, `lb_chain2.sh`, `cluster_run.log`). They will not reach the planned
   Release unless someone copies them. Section 5 gives no path for them.
9. **Header time.** EXPERIMENT.md says "마지막 갱신 14:50", but the file was written at 14:41:17 and committed in
   `9189dafc` at 14:41:23. At this check, rain's clock read 14:48.
10. **Git hygiene.** The untracked per-trial CSVs in `CP/runs/` and `CG/runs/` match the `*.csv` allow-list in
    `.gitignore`, so a folder-level add would commit raw data. The GIN kv, meta and logs are ignored.
