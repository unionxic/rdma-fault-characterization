# Deviations and clarifications after pre-registration

`PREDICTIONS.md` and `predictions.csv` are fixed by tag `prereg/propagation-v1`. Nothing below
changes a prediction or an acceptance rule. The list records how the campaign implements them,
and every choice made after the tag.

## 2026-10-06, before the campaign

1. **Smoke runs are excluded from scoring.** Two runs checked the instrumentation on the cluster
   before the campaign (`results/20261006_smoke/`):
   - the CPU stack, one trial per fault, 14:03;
   - every GPU and net stack, one trial per cell, from 14:05.
   They are kept as a record, but are not scored. Only the campaign folder is scored.
2. **F4 on the CPU stack is a real SIGKILL.** The responder raises SIGKILL on GO (fault
   `retry_proc_sigkill`). The requester keeps the old proc-kill flow, which waits 300 ms
   before its write. The kernel has then almost always torn the responder down, so the
   0x88 teardown race (`fingerprint_teardown/`, 111/270) is unlikely to appear.
3. **When the responder's state is read (EV1, EV2).** The requester waits 10 ms after detecting
   the fault, then asks the responder for its QP state and its async events since GO. Recovery
   starts after that.
4. **EV1d for F4.** The responder is dead, so its events cannot be observed. That cell is
   reported as "not observable", not as a hit.
5. **The net F0 control is `T0s`** (recovery flag on, no fault). There is no separate stock F0
   run.
6. **GIN teardown bound.** The abort bound is 30 s (`GIN_ABORT_WATCHDOG_S=30`), and the driver
   watchdog is 120 s, so the abort bound is the one that fires.
7. **GQ uses `CLASSIFY=1` with the default CQ type.**
8. **The ND cells run 10 trials each**, as `PREDICTIONS.md` says for new cells. A runner typo
   (5) was fixed before the campaign.
9. **Which observable tests EV4.** evrec sees only port events. For the DEVX stacks, EV4 is
   therefore scored on the libraries' own logs (no async error line), together with evrec's
   port events.

## 2026-10-06, after the first scoring (QA)

The first score is kept as `results/20261006_campaign/SCORE_first.md` and `score_first.json`.
Items 10 and 11 were decided after that score had been seen.

10. **GP and GG F4 were re-run.** In all 20 campaign trials (`gp_F4_timeout_t1`-`t10`,
    `gg_F4_blocking_t1`-`t10`), rank 1 finished its 120 iterations before the SIGKILL at
    3000 ms, so no fault acted during traffic.
    - Cause: `campaign/cells.sh` called `gin/scripts/run_trial.sh` with its defaults (120
      iterations, 15 ms gap, kill at 3000 ms). The original matrix (`gin/scripts/run_matrix.sh`)
      uses 400 iterations, a 10 ms gap and a kill at 2500 ms for F4.
    - Fix: `cells.sh` now uses the matrix settings for F4 (`ONLY_FAULT` selects one fault).
    - Re-run: `campaign/rerun_f4.sh` re-ran the 20 trials, 2026-10-06 17:08-17:13, into
      `results/20261006_f4rerun/`. It ran from the working tree on commit `9effa191` plus this
      fix. Every re-run kill landed after iteration 162-168.
    - Scoring: `score.py --f4-rerun` uses the re-run trials for GP and GG F4. The first 20 trials
      are kept and reported. GQ F4 was not affected.
    - The user decided to re-run, after the first score had shown D1 20/30, D2 0/10 and EV5c 30/40.
11. **Which retained logs the blind part of EV3a uses.** `predictions.csv` says "every retained
    r1 F2 log" without naming a folder. `gin/results/20260923/` has two sets of proxy F2 r1 logs:
    - `logs/` (6): rank 1 has no NCCL output, and rank 0 saw no REM_ACCESS status. The F2 put
      raised no remote-access error there.
    - `v2/logs/` (6).
    The first score used `logs/` (0/6). The user decided, after seeing both counts, that `logs/`
    is not observable and that the blind part is judged on `v2/logs/`. `score.py` marks a log as
    not observable when rank 1 has no NCCL output or rank 0 has no `status=10`. Both counts are
    reported.
12. **The scorer now applies the whole acceptance rule.** The first `score.py` applied only the
    9/10 part of the Method's rule. It missed "no trial shows an outcome outside the predicted
    class". The independent recount found this.
    - A miss is an observed outcome other than the predicted one, so any miss now fails a cell.
      Trials that are not observable count against the 9/10 only.
    - EV1d keeps its dead-responder trials outside the count, as item 4 says.
    - On the campaign data this changes one verdict: NET1c goes from holds (9/10) to fails.
      In `net_F2_t1` the receiving rank logged a flush error (5/0xf9) first. The sending rank logged
      no error CQE of its own; its send comm failed as "peer failed or declined", and recovery ended
      `CLEAN_FAIL (not declined by class)` instead of a decline for REM_ACCESS.
