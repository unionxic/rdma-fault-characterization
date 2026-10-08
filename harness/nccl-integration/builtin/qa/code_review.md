# Post-run code review: nccl-builtin

Reviewer: a separate agent, 2026-10-09, after the main run (H1–H15) and `score.py`. Scope: the test-only hook
`inject_232.diff`, `build_nb.sh`, `deploy_nb.sh`, `nbrun.py`, `cells.py`, `hold.sh`, `chain.sh`, `rows_nb.py`,
`score.py`, the driver `../perf/nccl_ct.cu`, and the multi-request recovery hook in `../stage2/net_ib_stage2.diff` for
comparison. Context: `EXPERIMENT.md` sections 1–9.

How: I read the code at the tag and in the working tree, the NCCL v2.32.3-1 tree in the session scratch
(`agent_nb/nccl-232/src/transport/net_ib/`), and spot-checked the main-run raw files in `results/20261009/`
(295 trials, 590 rank logs, 295 meta files) with read-only scripts in the session scratch. I ran nothing on the
cluster and changed no file except this one.

Marks: `[측정]` counted from the raw logs in `results/20261009/` (n given), `[소스]` read in code, `[추론]` inference,
`[미확인]` not checked.

## Verdict

**No blocker, no high finding. Nothing found here changes any of the 27 frozen verdicts** (26 맞음, 1 틀림 for the
fault-free cost of multi-request recovery, O4).

- The 2.32.3 hook injects the same fault at the same point as the multi-request recovery build. Its two code
  differences are inert in this run, which the logs show: every 2.32.3 hook line reports `nqps=1`, and rank 1 has one
  recv comm in both libraries. Every hook lands in the same iteration in every configuration (section A).
- Runner, parser and scorer compute the section 3.1 columns and the section 8 exclusions as written. No verdict passes
  on an empty field.
- The scoring code and `predictions.csv` are byte-identical to `prereg/nccl-builtin-v1` (section E).

Three medium findings concern interpretation, not the verdicts:
1. At 64 KiB, the bounds of O3 and O4 sit inside the run-to-run noise. The basis of O4 was measured with another
   protocol and an older build (M1).
2. The "silent" fault reaches the sender differently in different configurations (M2).
3. The 6 s grace kill cuts off the non-faulted rank at different times in the two libraries (M3).

M2 and M3 touch only the exploratory observations of section 3.4. Keep them in mind when writing sections 15 and 17.

## A. Hook equivalence (2.32.3 hook against the multi-request recovery hook)

| Aspect | multi-request recovery build (`net_ib_stage2.diff`) | 2.32.3 hook (`inject_232.diff`) | Same? |
|---|---|---|---|
| Knobs | `NCCL_RDMA_FAULT_INJECT`, `_RECV`, `_RECV_SILENT` | same names (diff 31–33) | yes `[소스]` |
| Send trigger | process-wide count of first-time multi-sends, at the top of `ncclIbMultiSend` (diff 1253–1266, call 1333); replays use another path | process-wide count in `ncclIbIsend` right before `ncclIbMultiSend` (diff 55–65, call 116 = `p2p.cc:473`). Resiliency replays call `ncclIbMultiSend` directly (`p2p_resiliency.cc:262`) and are not counted | yes for first-time sends `[소스]` |
| Recv trigger | process-wide count in `ncclIbIrecv`, after `ncclIbGetRequest`, before the receive WR and the CTS are posted (diff 1268–1276, call 1422) | process-wide count at the top of `ncclIbIrecv`, before the WR and the CTS (diff 67–77, call 124 = `p2p.cc:561`). Between hook and post there are only error returns (`p2p.cc:561–661`) | yes: the QP is in ERR before the receive WR and the CTS in both `[소스]` |
| QPs moved to ERR | `qps[0]` | every `qps[q]`, `q < nqps` (diff 42–51) | inert: all 125 hook lines of 2.32.3 in the fault cells print `nqps=1, rc=0` `[측정, n=125]` |
| Silent arming | first recv comm *attached* with the flag on (diff 429–432) | first recv comm that *completes* a receive (diff 86–89) | inert: rank 1 has one recv comm in the single-channel cells in both libraries (one `recovery on for recv comm` line; one `Resiliency ... recv comm` line) `[측정, spot-checked]` |
| Silent count and condition | decrement per RECV_RDMA_WITH_IMM CQE; at the k-th or later fires if one other receive has not arrived (diff 597–602, 675–685) | count per RECV_RDMA_WITH_IMM CQE; at the k-th or later fires if one other RECV request still has events (diff 90–100) | same rule `[소스]`. The pending count at firing is not logged by the stage2 hook, so it cannot be compared (see M2) |
| Landing point | send and recv: after `IT 17` (iteration 18 of 150) in 20/20 `s2on` and `s2off` trials; silent: after `IT 1` (broadcast, 5/5), after `IT 99` (all-reduce, 5/5) | send and recv: after `IT 17` in 65/65 trials; silent: after `IT 1` in 30/30 broadcast and after `IT 99` in 30/30 all-reduce trials | yes `[측정, n=150]` |

One difference shows after the hook and comes from the library, not the hook. In the silent all-reduce, rank 1
completes iteration 100 and stops in 101 with `off` and `s2on` (`ok_r1=101`). With `fo` and `forec` it stops in 100
(`ok_r1=100`), because the 256 pre-posted receive WRs flush at once (`p2p.cc:972–979`) `[측정, n=10 per cell]`
`[추론]`. This does not touch any rule.

**Could a hook difference explain the outcome differences between the libraries?** For the send-QP, recv-QP and kill
faults, no: the action, the count and the landing iteration are the same. For the leak of a wrong result to rank 0
(prediction S9 against I1), the logs support the source explanation of section 1 item 8, and the harness does not
confound it:

- 2.32.3: rank 1's progress thread logs exactly one `[Progress Thread]` error line after the hook (30/30 `rqp` trials).
  The abort flag reaches the sockets 6.6–13.9 ms after the hook (`abort called`), and `ncclCommAbort` returns at
  544.8–563.7 ms. So a leak window of about 0.5 s was open, and no MISMATCH came `[측정, n=30]`.
- 2.23.4 with the flag off: the progress thread keeps logging (5 error lines per trial). `abort called` comes at
  631.9–649.0 ms, and rank 0's MISMATCH at 632.3–649.5 ms `[측정, n=5]`.

## B. Driver and runner

Sound, with the points below.

- **Mismatch detection** (`nccl_ct.cu:193`, `202–213`). The result buffer is filled with NaN before every iteration
  and compared bit-exactly on the GPU. A completed iteration with an async error goes to ERROR, not MISMATCH (the
  after-sync check, 97–99). So a wrong result is only seen on iterations that complete without an error. In the 2.32.3
  recv-QP cells rank 0 never completed iteration 18: it waited until its own RETRY_EXC. So "no MISMATCH" there means
  that none was delivered, not that one was hidden `[측정]`.
- **Outcome order** (`rows_nb.py:193–204`): MISMATCH > TRANSPARENT > ERROR > HANG > OTHER. A MISMATCH after the first
  TIMEOUT is left out (190–191). An ERROR after a TIMEOUT is not (nit N6). Both rules are inert here: 0/295 trials
  have an error or a MISMATCH line after the first TIMEOUT line `[측정, n=295]`. So the rule that came after the pilot
  (`mism_pre_to`) changed no outcome.
- **Kill** (`nbrun.py:76–84`, `150–154`). The kill goes over ssh and is sent only if the PID file names a process
  whose `/proc/<pid>/comm` is `nb_ct`. The PID is the one of the shell that `exec`s into `nb_ct` (98–99), so the check
  holds after the exec. 40/40 `kill_out=killed`. The ssh round trip was 235.0–260.7 ms, and the survivor had 40 655–45 218
  iterations done `[측정, n=40]`. `t_fault` is the request time, so every kill-cell `dt` includes up to one round trip
  (L2). 295/295 `final_kill_out_r1=nokill` and `left_before` and `left_after` `0,0` `[측정]`.
- **Grace and wall cap** (`nbrun.py:155–174`). The rule matches section 3.1. Wall cap reached 0/295. Longest trial
  27.4 s (`kill@s2off`) against the 40 s cap. 40 rank-1 grace kills, all in `sqp` cells `[측정]`. See M3 for what
  the grace does to cross-library comparisons.
- **Bounds.** Driver timeout 12 s, abort watchdog 10 s, grace 6 s, cap 40 s or 15 s, `timeout -s KILL 880` per hold.
  `chain.out` shows rc 0 for H1–H15. 590 logs = 2 × 295 meta files, so no trial lost its meta file (L3).
- **Log level.** INFO+NET for `sqp`, `rqp`, `slbc` and `slar`; WARN for `kill` and `ovh`. It is uniform inside every
  cell (column `debug`, 295/295), so no configuration comparison crosses levels. No INFO line repeats per iteration.
  The non-`IT` lines per rank log are 43–197 in the INFO fault cells, except `slar@s2on`, whose up to 378 lines are
  error traces printed after the TIMEOUT. So INFO did not slow the iterations or move the hook `[측정]`.
- The recovery time of the multi-request recovery was measured at INFO; its basis was at WARN. The recovery path's own
  lines are WARN (`incident via`, `recovered`), and the main-run medians were 2.306 ms (`sqp@s2on`) and 2.233 ms
  (`rqp@s2on`), inside the final build's earlier 2.152–2.400 ms. INFO did not bias this prediction (S2) in any way that
  matters `[측정, n=5 per cell]`.

## C. Parser and scorer

- **Columns** (`rows_nb.py`) match section 3.1. I checked every substring of `COUNTS` that a rule asks to be 0 against
  the v2.32.3 source:
  - `prec_activity`: `p2p_resiliency.cc:107, 381, 537`; `p2p_resiliency_recovery.cc:1262, 1281, 1295, 1547`.
  - `single_dev`: `p2p_resiliency.cc:841–842`.
  - Configuration lines: `p2p_resiliency.cc:619, 646, 650, 654`; `p2p_resiliency_recovery.cc:1483`; `common.cc:106`.

  All exist. All are `INFO(NCCL_NET, ...)` except the WARN line `marked as failed`, so all are visible in the INFO cells
  `[소스]`.

  The columns a rule asks to be nonzero are proven readable by a rule that passed with them: `stock_cqe` in the
  original-error-path predictions (B1, B2, R1), `fatal_nfd` in the fatal-verdict predictions (F1, F2, F4), `wc_status`
  in all of those plus the flag-off predictions (S6, S7), `mism` in S9, and `s2_fin` in S3 `[측정]`.
- **Exclusions** (`score.py:68–83`) match section 8: launch, fault not applied, kill not done, kill before 1 000
  iterations, configuration check. The configuration check is applied again at scoring time; during the run it was a
  STOP. 0 trials were excluded and 0 were surplus. One rule of section 8 is not in code: stop a cell key after refills
  pass 50 % of the plan. It is inert here (L3).
- **Vacuity.** The empty-field rule (`s2_close/score.py:77–90`, `133–138`) makes every comparison with an empty field
  false. Every count column is an integer, never empty. A cell short of its plan makes the prediction "자료 부족"
  (`score.py:123`), and every prediction key is in `KEYS`, so no `== 0` rule can pass on zero rows. Two clauses are
  weak by construction, and the prediction file says so (L4).
- **Overhead computation** (`predictions.csv` O1–O4; `s2_close/score.py:177–180`). The median over runs of rank 0's
  per-run median `med_ms`, as section 3.3 says. Recomputed from `trials_scored.csv` `[측정, n=10 runs per key]`:

  | comparison | median difference |
  |---|---|
  | 64 KiB, flag on against flag off (O4, bound 3 %) | +3.75 % (0.05395 against 0.05200 ms) |
  | 16 MiB, the same comparison (O4, bound 2 %) | +0.13 % |
  | 64 KiB, failover against off (O2) | +1.73 % |
  | 64 KiB, failover and recovery against failover (O3) | −1.70 % |
  | 16 MiB, failover against off (O1) | −0.15 % |
  | 16 MiB, failover and recovery against failover (O3) | −0.07 % |

  So the 틀림 of the fault-free cost of multi-request recovery (O4) is computed correctly; it fails at 64 KiB only. See
  M1 for how much weight it carries.

## D. Findings

### Blocker

None.

### High

None.

### Medium

**M1. At 64 KiB the bounds of O3 and O4 sit inside the noise, and O4's basis used another protocol and build.**
- Where:
  - `cells.py:66–67` and `cells.py:135–136`: fault-free cells run `--check every`, without `--quiet`, 2 000 and 200
    iterations, warmup 20 and 5.
  - The basis of O4 (`predictions.csv` row O4; EXPERIMENT 1 and 3.3): `../perf/completion_time.py:85`, `91–92`. It ran
    `--check last --quiet`, 200 iterations at 64 KiB and 20 at 16 MiB, warmup 20, 3 runs, on build `3b0b760d`.
- Failure scenario.
  - Run-to-run spread of `med_ms_r0` ((max−min)/median, 10 runs): 64 KiB 4.8–18.0 % across the five configurations
    (`s2on` 18.0 %, `off` 9.7 %, `forec` 6.4 %, `fo` 4.9 %, `s2off` 4.8 %); 16 MiB 0.8–1.9 % `[측정]`. The basis spread
    (flag off, eight keys, 3 runs each, section 1) was 0.2–1.7 %.
  - Bootstrap 95 % intervals of the median difference (my offline resampling, 20 000 draws, not pre-registered)
    `[측정, 추론]`:
    - flag on against off at 64 KiB: [+0.8, +10.4] % (permutation p ≈ 0.02);
    - failover against off at 64 KiB: [−0.6, +4.1] %;
    - failover and recovery against failover at 64 KiB: [−4.6, +0.5] %.

    The 3 % bound of O4 and the 2 % bound of O3 fall inside their intervals, so the 64 KiB parts of O3 (맞음) and O4
    (틀림) could flip with modest noise. The 5 % bound of O2 lies above its interval, so the O2 pass is better
    supported.
  - The O4 failure comes from the second hold. H1 alone: +1.9 %. H2 alone: +9.3 %. The `s2on` median moved from
    0.0532 ms (H1) to 0.0566 ms (H2), while `s2off` stayed at 0.0522 and 0.0518 ms `[측정, n=5 per hold]`.
  - Per iteration, the protocol also differs from the basis:
    - It prints an `IT` line that rank 1 sends over ssh (`nccl_ct.cu:216`).
    - It runs the check kernel (`202–213`) outside the timed region. Rank 0's timed region (`195–201`) still absorbs
      any lag of rank 1 in starting the next iteration.
  - The build differs too. `9ed03e1d` = `a037de42` + the inert F2 hook, against the basis `3b0b760d`. The FIN rule,
    the keepalive and OOB-loss handling, and the RST rule came in between (`../stage2/NOTES.md:38–43`). They act only
    with the flag on `[소스]`.
- Effect on the results.
  - The O4 verdict stands as frozen: it was correctly computed on the planned runs.
  - Do not report "multi-request recovery costs more than 3 % at 64 KiB" as a measured cost without the interval and
    the per-hold split.
  - Do not report the 64 KiB pass of O3 as "no cost" either.
  - The 16 MiB comparisons are tight (intervals within ±0.8 %) and unaffected.
  - The cross-library difference (`s2off` 10.0 % faster than `off` at 64 KiB, 4.5 % slower at 16 MiB) was not predicted
    and also mixes the protocol effects above.

**M2. The silent fault reaches the sender differently in different configurations.**
- Where: `inject_232.diff:90–101` (fire when one other receive is pending), against stage2 `net_ib_stage2.diff:675–685`.
- Failure scenario.
  - "Pending" means that the request has been posted. It does not guarantee that its CTS has reached rank 0.
  - At firing in `slbc`, the 2.32.3 hook reports `pending=3` in 10/10 `off` trials and `pending=2` in 10/10 `fo` and
    10/10 `forec` trials. The pilot reported 4, 5, 6 for the same three keys `[측정]`. The stage2 hook does not log
    the pending count.
  - Afterwards rank 0 (the broadcast sender) got an error CQE (RETRY_EXC) in 10/10 `off`, 1/10 `fo`, 4/10 `forec` and
    5/5 `s2on` trials. That is where `s2on`'s transparent recovery comes from. In the other `fo` and `forec` trials,
    rank 0 had no error CQE at all before its grace kill: `Got completion with error` count 0 `[측정]`. So it never
    wrote into the dead QP.
  - Whether failover itself or the firing moment (CTS still queued when the QP went to ERR) causes this is `[미확인]`.
    The earlier stage2 run C6 saw the same split: rank 0 was exposed in 1/3.
- Effect on the results.
  - None on the scored rules: the silent-fault predictions (B4, F4, S4) judge only rank 1, or the outcome.
  - The comparison "multi-request recovery recovers the silent broadcast fault transparently; 2.32.3 errors" holds:
    the 2.32.3 error is rank 1's own, and it does not need sender exposure.
  - Do not attribute the rank-0 difference between `off` and `fo` or `forec` (section 3.4, the non-faulted rank) to
    failover without that check.
  - `s2on`'s 5/5 transparency depends on the sender being exposed. With exposure like `fo`'s it would have stopped, as
    in C6 2/3 `[추론]`.

**M3. The 6 s grace kill censors the non-faulted rank at different times in the two libraries.**
- Where: `nbrun.py:23`, `155–166`, combined with the abort behaviour.
  - 2.32.3's `ncclCommAbort` returns, and the faulted rank exits 0.64–0.67 s after the hook in the recv-QP cells.
  - 2.23.4's abort hangs until the 10 s watchdog (`nccl_ct.cu:231–240`) `[측정]`.
- Failure scenario.
  - The other rank is killed about 6.6 s after the fault in 2.32.3, but only after about 16 s in 2.23.4.
  - Example, send-QP cells. Rank 1 was grace-killed with no error and no TIMEOUT in 35/35 2.32.3 trials. In `sqp@s2off`
    it reached its own TIMEOUT at 11 998.6–11 998.7 ms and was then grace-killed `[측정]`.
  - Likewise rank 0 of `slar@off`, `fo` and `forec` was grace-killed with no error in 30/30. In `slar@s2on` both ranks
    reached the TIMEOUT.
  - An error the non-faulted rank would have raised between 6.6 s and 12 s is never seen in 2.32.3. RETRY_EXC came at
    3.5–3.8 s wherever it came, so it fits inside the grace.
- Effect on the results.
  - None on the scored rules: they judge the faulted rank, the outcome, or rank 0 in the kill cells, where the grace
    does not apply (`nbrun.py:158`).
  - For the exploratory section 3.4 item (does the non-faulted rank end by itself or by the 6 s grace), the answer
    differs between libraries because of the abort duration and the harness. Do not read it as a library property
    beyond about 6.6 s.

### Low

**L1. In the WARN cells, rank 1's library and the multi-request recovery flag are checked only through the
environment.**
- Where: `cells.py:100–101`. The WARN path stops after version, environment, single-device warning and hooks; `ver_r0`
  covers rank 0 only (`rows_nb.py:129–130`).
- Scenario.
  - Rank 1 of `kill@off`, `kill@s2on`, `kill@s2off` and every `ovh@{off,s2on,s2off}` run has no log line naming its
    library.
  - `ovh@s2on` has no line showing that the flag took effect on either rank (3 non-`IT` lines per rank log, the same as
    `s2off`) `[측정]`.
- Mitigation: the bundle path is explicit in the remote command (`nbrun.py:98–99`). `deploy_check.txt` shows `ldd`
  resolving inside each bundle. The per-hold md5 snapshots matched.
- Effect: unlikely to matter. Still, the fault-free cost predictions (O1–O4) rest on the environment in the meta files
  for the `off`, `s2on` and `s2off` side.

**L2. Sub-millisecond `dt` values are receipt-time differences.**
- Where: `nbrun.py:111–117`, `rows_nb.py:141`, `161`.
- Scenario.
  - The hook line reaches the runner 0.270–0.321 ms after the hook's own clock reading on rank 0 `[측정, n=35]`.
  - Rank 1 lines arrive over ssh, and no clock is shared.
  - Kill cells take `t_fault` before the 235–261 ms ssh round trip.
  - So error times such as 0.030–0.103 ms (`sqp`) or 297.7–310.0 ms (`kill@s2on`) carry pipe and ssh offsets.
    Comparisons across ranks, or with library-internal times like `s2_rec_ms`, are not like for like.
- Effect: none on the 1 000 ms bounds. Avoid sub-millisecond comparisons between configurations or libraries in the
  write-up. Example: `slar@off` 0.157–0.213 ms against `fo` 0.048–0.110 ms partly reflects how many WARN lines each
  path prints before it returns.

**L3. Two exclusion paths are not in code.**
- The refill stop (more than 50 % of the plan per cell key, section 8) is not implemented in `score.py`.
- A trial whose meta file is missing (for example, the hold killed mid-trial) would be invisible to `rows_nb.rows()`
  (`rows_nb.py:209–214`). `hold.sh:49` would reuse its number.
- Effect: inert in this run. No exclusions, no refills, 590 logs = 2 × 295 meta files, every hold rc 0.

**L4. Some "nothing happened" clauses are weak by construction.**
- In the kill cells (WARN), only `marked as failed` of the seven recovery-activity strings is visible. The rule that
  no device is marked failed and no recovery starts (F7) is therefore weak there; the prediction file says so.
- The rank-1 clause `prec_activity_r1 == 0` of the immediate fatal-verdict prediction for the send-QP fault (F1) is
  also weak. Rank 1 never got an error CQE before its grace kill, so its resiliency code was never entered `[측정]`.
- Effect: those clauses add little evidence. The fatal-verdict count (`fatal_nfd >= 1`) is what carries F1, F2 and F4.

**L5. The hold snapshots record no traffic counters.**
- Where: `hold.sh:24` lists error counters only. `cluster_run.sh` checks for an idle link at the start of a hold only
  (`cluster_run.sh:49–51`).
- Scenario: foreign RDMA traffic during a fault-free hold could not be detected afterwards. This is relevant to M1's H2
  shift. No GPU process of another user appears in any snapshot `[측정]`; other traffic is `[미확인]`.
- Effect: one more possible source of the 64 KiB noise.

## E. Changes after the tag

- `prereg/nccl-builtin-v1` = `0ca10eb7` = HEAD; there is no commit after the tag.
- Compared blob by blob with `git show prereg/nccl-builtin-v1:<path>` and `cmp`. Byte-identical to the tag: these
  scripts, `predictions.csv`, `PREREG.txt`, `EXPERIMENT.md`, `../perf/nccl_ct.cu`, `../stage2/net_ib_stage2.diff`
  and `../../gpu-initiated/gin_recovery/s2_close/score.py`.
- `hold.sh:16` and `deploy_nb.sh:13` differ only by the smudge filter's address substitution: the working tree holds
  the real management address, the blob the documentation address. This does not affect scoring.
- The run used the tagged code.
  - All script mtimes (00:31–01:20) are before the tag (01:27:17).
  - The bytecode of `nbrun` and `rows_nb` was compiled at 03:21:29, the start of H1. `SCORE.md` and
    `trials_scored.csv` were written at 06:22:32.
  - The sha256 of `predictions.csv` (`d6804c54…`) equals the one in `PREREG.txt`.
- Two rules were changed after the pilot and before the tag; both are documented in section 12.
  - Under the pre-pilot rule, the prediction that the recv-QP fault surfaces on rank 1 within 1 s with the flag off
    (S7) would have scored 0/5, because the outcome of all five trials is MISMATCH.
  - The rule that leaves MISMATCH after a TIMEOUT out of the outcome changed nothing (section B).

## F. Nits

- **N1** `build_nb.sh:31`: the tree check (`git diff v2.32.3-1 -- src`) does not see untracked files under `src/`.
  `git status --porcelain src` would. The hook lines in every injection trial show that the built library contains the
  hook.
- **N2** `SCORE.md`, from `s2_close/score.py:192–193`: medians are shown with 3 decimals. At 64 KiB that hides a 2 %
  step: `abs(0.054 - 0.052)` stands for 0.05395 against 0.05200. For `== 0` rules, the summary column "맞은 시행" shows
  the number of violating trials ("0/10" = none), which reads backwards. Consider 5 significant digits and a column
  label per rule direction.
- **N3** `rows_nb.py:184–186`: `s2_rec_ms` takes the first send-comm `recovered` line in rank order (rank 0, then rank
  1), not in time order. Section 3.1 says "첫". The result is the same here.
- **N4** `rows_nb.py:193–204`: ERROR ranks above HANG even when the error line comes after a TIMEOUT. This is not
  symmetric with the MISMATCH rule. Inert here (0/295).
- **N5** `inject_232.diff:62–63`, `74–75`, `104–106`: the hook line prints only `qps[0]`'s QP number while it moves
  every QP. Cosmetic, since `nqps=1`.
- **N6** The stage2 silent hook line logs neither the completion number nor the pending count (`net_ib_stage2.diff:684`).
  That is why equivalence at firing (M2) can only be shown by the landing iteration.
- **N7** `EXPERIMENT.md:519`: section 13 still says "아직 사전 등록 전이다" in the tagged text. Section 13 is not a
  fixed section, so replace the sentence when adding the first post-tag entry.
