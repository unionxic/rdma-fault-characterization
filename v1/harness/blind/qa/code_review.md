# blind-apps: post-run code review (measurement and blinding)

Reviewer: independent code-review agent, 2026-10-09. Scope: the code listed in the review request at tag
`prereg/blind-apps-v1` (commit `7a839ea7`), checked against the main run `results/20261009/` (opened seal,
`SCORE.md`, `trials_scored.csv`, `raw/`). Method: reading the code and the example sources the workloads build from,
plus read-only Python scans of the raw logs and `trial.meta` files, written in my scratchpad. I did not run any study
program, any cluster command, the address filter, or any git write. The only file written is this one.

Marks: `[measured]` recomputed here from raw files, `[source]` read in code, `[inferred]` interpretation.
No addresses are reproduced in this file.

## Verdict

1. **The machine outcomes stand.** No code defect changes a trial's outcome class. Faults were applied at the
   scheduled time and on the scheduled target in all 166 blind trials. Nothing that affects the outcome changed
   after the tag. The machine verdicts in `SCORE.md` (D1–D7, G1–G5, N1–N6, X1, X2) follow the pre-registered rules
   correctly. Two of them need a caveat when interpreted:
   - The 2 NVSHMEM silent-wrong trials come from a validation race inside the unmodified example, not from the
     recovery library (HIGH-2).
   - The management-mute cells test "existing connections dropped", not "network down for d seconds" (MEDIUM-1).
2. **The blinding was broken for library-hook trials in GIN and DDP.** Removing a hook line leaves the empty line
   that NCCL prints before every WARN line. The resulting double empty line shows which rank had the hook, and
   roughly when it fired (HIGH-1). The evaluator used this artifact as the only basis for class and target in the 14
   GIN QP-error hangs. Consequences:
   - The evaluator prediction on QP-error class (E2) cannot be reported as a plain 맞음. See the bounds in HIGH-1.
   - The other evaluator predictions (E1, E3, E4, E5) do not depend on this artifact.
   - The kill class is given away by the exit record by design (MEDIUM-2). This is the "kill timing" item.

## Findings, ranked

### HIGH-1: the stripped view keeps the empty line before each removed NCCL WARN hook line (blinding break)

- **Where.**
  - `strip_hooks.py:28-31`: `view()` drops only the lines that match `HOOK`.
  - `handoff.py:81-83` writes that view into the evaluator folder.
  - NCCL prints a newline before each WARN header. `node_agent.py:111-123` forwards that empty line as a line of its
    own, and the runner records it with its own receipt time (`blindrun.py:256-265`).
  - The hook lines are WARN lines in both libraries: Stage 2 `[FAULT-INJECT]` and the silent-mode drain line in
    DDP, and `GIN/FAULT: ... armed` and `... fired` in GIN.
- **Measured.** I counted views that contain two consecutive empty lines after stripping `[measured]`.
  - **On the hook's target rank, 42 of 42 views:**
    - GIN QP error: 16 of 16.
    - DDP send QP error: 10 of 10.
    - DDP receive QP error with notice: 10 of 10.
    - DDP silent receive QP error: 6 of 6. These have 2 sites each, against 1 for the other DDP hooks, so the
      artifact also separates the silent receive error from the notified one.
  - **Everywhere else in GIN and DDP, 0 of 198 views:** the other rank of hook trials and both ranks of every
    none, kill, stop and mute trial and reference run.
  - **NVSHMEM is not affected.** Its hook lines are plain lines with no empty neighbour, and double empty lines
    occur natively in every class.
- **Failure scenario.** From the view alone, the evaluator learns three things:
  - that a library hook existed;
  - which rank had it;
  - about when it fired, from the receipt time of the orphaned empty line, or a trailing empty line at end of
    file when the fire line was last.
  - The leak audit (`LEAK`, `strip_hooks.py:21-22`) checks line text only, so it cannot catch this.
- **Effect on the results.**
  - **The evaluator relied on it.** Its evidence for 1f3a059c, 2985f04b, 46548938 and the other 11 GIN QP-error
    hangs reads "injector-removal artifacts on rank N only ... class from in-process artifact plus a silent hang".
    Its working script `blind_eval_work/blanks.py` (in the scratchpad) searches for exactly this artifact.
    Target rank for GIN QP errors was 16 of 16 correct; target rank is not scored.
  - **QP-error class prediction (E2): 80% of 50 trials, as scored 50 of 50.** Bounds `[measured]`:
    - As scored: 맞음.
    - Counting the 14 artifact-based judgments as wrong: 36 of 50 = 72%, which is under the 40 needed, so 틀림.
    - Dropping them as contaminated: n = 36, which is under the pre-registered minimum of 38, so 자료 부족.
    - Without the artifact, the evaluator might still have reached "QP error" by elimination: a silent hang of both
      ranks with no signal fits no other class. That counterfactual is `[inferred]` and cannot be checked after the
      reveal.
  - **DDP.** The evaluator's DDP class and target evidence cites the library's own recovery lines (which side saw
    `WR_FLUSH_ERR 0xf5`, "notify never arrived"). The artifact was there but was not cited.
  - **Outcome judgments (E1): no effect.** The outcome of the 14 hangs comes from `exit.txt` (wall-clock cap).
- **Fix for later studies.**
  - Drop an empty line that directly precedes a dropped hook line, or drop all empty lines in every view.
  - Add a pilot audit that compares the structure of the views across demo classes (counts of empty lines, line
    counts per rank). Matching line text alone is not enough.

### HIGH-2: the 2 NVSHMEM stop silent-wrong trials are a validation race inside the unmodified example

This does not change any count. It changes what the X1 and N5 failures mean.

- **Where.**
  - NVSHMEM `examples/ring-reduce.cu` (scratch copy under `agent_t1_380/src/examples/`), lines 227-259. Each size
    ends with `cudaStreamSynchronize`, then a host-side validation (`cudaMemcpy` of `dst` at line 254, and a loop
    that prints `PE p error, data[i]`). The next size starts right after with no barrier between the two.
  - In the next size's warmup kernel, PE 0 puts its `src` (values `i`) into PE 1's `dst` without waiting for a
    signal.
  - Classification: `rows_blind.py:208-212` (result) and `rows_blind.py:221-222` (rule).
- **Measured in 37bd4c3d and 800579c9.** Both trials stopped rank 1 `[measured]`.
  - The stop of PE 1 began before PE 0 printed its 32 MiB line: stop at 2.245 s and 2.057 s, 32 MiB line at
    3.166 s and 2.402 s.
  - PE 0 therefore finished all 150 iterations of 32 MiB while PE 1's host was stopped. PE 1's GPU kept running
    the kernels it had already queued.
  - PE 1 printed its first validation line 9–10 ms after SIGCONT.
  - Error count: 200 lines kept plus 8,388,407 suppressed (`a1.log`) = 8,388,607, which is every element of the
    32 MiB buffer except index 0.
  - The values are `data[i] = i` with `2i` expected, i.e. exactly PE 0's `src`.
  - PE 0's own 32 MiB check passed, so PE 1 had sent the correct sum.
  - Both PEs passed the 64 MiB check later.
- **Counter-check.**
  - The other two rank-1 stops (a4be5433, e392a0dd) began after PE 0's 32 MiB line. No later size followed to
    overwrite the buffer, and both were transparent.
  - A stop of rank 0 cannot race in this way: PE 1 writes into PE 0 only after PE 0 has launched the next size.
    The 4 rank-0 stops were all transparent.
- **Effect.**
  - By the pre-registered rule, SILENT_WRONG is the correct class. The no-silent-wrong prediction for GIN and
    NVSHMEM (X1) and the NVSHMEM stop prediction (N5) are 틀림 as scored.
  - The cause is the example's oracle: it is racy when PE 1's host stalls across a size boundary. Such a stall
    would do the same with stock NVSHMEM. The cause is not data corruption in the recovery library `[inferred,
    strong]`.
  - The conclusion should say so. A control with the stock library and the same stop would confirm it.
    Rescoring is not needed.

### MEDIUM-1: "mute applied" means rules were inserted, not that the management network was down for d seconds

- **Where.**
  - `blindrun.py:388-402`: DDP and NVSHMEM drop only the local ports of the connections that are established at
    insert time (`own_ports`).
  - `blindrun.py:376-387`: GIN drops the 16-port helper range.
  - `blindrun.py:411`: the window ends at d seconds or at the end of the trial.
  - `rows_blind.py:141-144` and `blindrun.py:491` define "applied" as at least one rule inserted. No packet
    counters are recorded.
- **NVSHMEM, 6 of 6 applied.** The library lost its socket 3.2–4.8 s after the rules went on. It then re-dialed
  from a new local port that no rule covered, and resumed while the rules were still in place (for example
  01b1e4de: rules from 2.88 s to 9.16 s, re-dial at 6.04 s) `[measured]`. The effective outage was shorter than
  the scheduled 5.4–8.4 s.
- **DDP, 6 trials.**
  - 3 of 6 printed "OOB socket lost ... recovery disabled for this comm, it continues as stock" on every comm of
    both ranks (25277b30, a6a93f41, e031cd26). They count as TRANSPARENT, but the recovery layer was off for the
    rest of the run.
  - The other 3 had their window cut by the end of the trial: 3.1–5.1 s of a scheduled 8.0–13.7 s, with no line
    to show for it.
- **GIN, 12 of 12.** The rules lived 0.33–0.47 s, from about 1.25 s until the trial ended about 1.7 s, against a
  scheduled 2.1–7.9 s. There was no helper-socket event in any of them `[measured]`.
- **Effect.** The mute predictions for DDP, GIN and NVSHMEM (D7, G5, N6) are 맞음 for the fault as implemented. They
  do not show survival of a management outage of the stated length. The doc's section 18 already notes the
  truncation for GIN and DDP. It does not mention the re-dial bypass or the disabled recovery in DDP.
- **For a later study.**
  - Block by peer address and ports (excluding ssh) so that re-dials are also dropped.
  - Record `iptables -v -x` counters at removal.
  - Report the effective window.

### MEDIUM-2: the exit record identifies every applied kill (the reported "kill timing" item)

- **Where.**
  - `handoff.py:41-50` and `handoff.py:92-94` write each rank's exit status, with or without "ended by the
    harness".
  - The schedule's kill goes through the same agent as the harness's own grace and wall kills
    (`blindrun.py:497-501` against `blindrun.py:526-535`). Only the second kind is labelled.
- **Effect.**
  - A scheduled kill always shows as "terminated by signal 9; not ended by the harness" on the target rank. That
    gives class and target directly. The killed rank's last line gives the time.
  - In GIN, every kill fell 12–106 ms after the comparison header (the window from `calib.json`). The evaluator's
    notes say "right after case header" for all 10.
  - The kill-class prediction (E3, 25 of 25) therefore measures the harness's exit record, not what the libraries
    print. The prediction's rationale expected this ("종료 신호 9"), and the label is needed to judge "hung", so this
    is not a code bug. It should be kept in mind for the observability question (H5).
  - I found no other timing channel from the harness. Line times are relative to the runner's own start, and the
    runner's log, `trial.meta` and the agent lines are not copied into the evaluator folder `[source]`.

## Low

- **L1. A harness pattern strips an application line.** `strip_hooks.py:19-20` has `BLIND_` with `re.I`, which
  also matches nanoGPT's line "Overriding: out_dir = /tmp/blind_ddp_out". That line is removed from every DDP
  view, on both ranks, in every class, so it carries no bias `[measured]`. It would also remove any crash line
  naming `blind_gin_ring`, `blind_nvs_rr` or `blind_nvs_boot.so`; none occurred.
- **L2. Run order is recoverable.** GIN WARN lines carry wall-clock timestamps, and kept lines carry `host:pid:tid`,
  so the evaluator can sort trials into run order. The order within a workload is a random shuffle, so it says
  nothing about class.
  - A weak side channel exists. The PID gap between consecutive rank-0 processes grows with the processes the
    runner spawns on rain, and a mute adds sudo and iptables processes. Median gaps: GIN mute 82, GIN none 55,
    with overlapping ranges 50–103 and 31–122 `[measured]`.
  - The evaluator did not use it: it judged all 12 GIN mutes as none.
- **L3. The bootstrap shims do more than move the unique ID.** `boot/gin_boot.cc:28-49` replaces `run_parallel`
  and `cleanup` of the MPI build (`common/src/utils.cc:233`, `:318`). It drops the `MPI_Barrier` after the example
  and the `MPI_Finalize`. With no launcher, there is no launcher fate-sharing: under mpirun or a PMI launcher, a
  killed rank usually brings down the job. This is why GIN and NVSHMEM survivors of a kill wait for the harness's
  grace kill (HUNG).
  - `boot/nvs_boot.cc:62` runs the UID module's pre-init a second time (the loader already called it through
    line 50); no effect was seen.
  - The NVSHMEM bootstrap runs over management TCP, so it is among the connections the mute drops.
  - No effect on fault-free runs: GIN and NVSHMEM none trials were 8 of 8 each, and all 12 reference runs had
    correct results.
  - Section 9.2's "고유 ID만 옮긴다" understates the change. The paragraph should say so.
- **L4. Latent: a runtime "off" line would silently exclude a trial.** In `rows_blind.py:59-61`, `CONFIG_OFF`
  includes messages a fault can produce at runtime: GIN `GIN/REC: .*recovery disabled`, and NVSHMEM `transparent
  mode (stays )?off`, which is also an error pattern. A fault that triggered them would mark the trial
  `config_ok = 0`, so it would be excluded instead of counted as DECLINED. This did not happen: every applied
  GIN and NVSHMEM trial is valid. DDP's runtime "recovery disabled for this comm" is correctly not matched.
- **L5. Latent: the GIN oracle cannot produce SILENT_WRONG.** The example returns 1 when validation fails
  (`main.cu:267-269`, `:308`), and the rule (`rows_blind.py:221-224`) then gives DECLINED. The GIN half of the
  no-silent-wrong prediction (X1) is therefore insensitive by construction. No GIN trial had a wrong result
  `[measured]`. Report `result == wrong` counts per cell, whatever the outcome.
- **L6. NVSHMEM runs had two speeds.** Anchor to last size line was 3.2 s in some runs and 5.13 s in others
  `[measured]`. `calib.json` used the slow pilot runs (T = 5.146 s). In fast runs a late draw lands after the end,
  which explains 3 of the 4 exclusions:
  - kill 20579d16, stop dcd30cbc, mute 1bcf6936: ended before the fault, each about 4.3 s of wall time.
  - The 4th, mute 6c4d85ca, was skipped because of a foreign socket.
  - These exclusions do not depend on the outcome, so they introduce no bias. They do leave the NVSHMEM mute cell
    exactly at its minimum (n = 6).
- **L7. Fault-time latency** `[measured]`:
  - Kill and stop: within 0.6 ms of the schedule.
  - Mute setup took 71–76 ms in DDP, which is 1–4 training iterations after the scheduled `iter <n>`, and about
    40 ms in NVSHMEM.
  - For rank-1 targets the reference time is when rain received the agent's ack over ssh, a few ms late.
  - None of these matter at the 3–5 s thresholds.
- **L8. The NVSHMEM kill prediction (N4) turned on a regex choice made before the tag.** The survivor's only
  line, "library socket closed (FIN)", is neither an error nor a death line (`rows_blind.py:47-48`; section 12).
  The same text appears at normal teardown. The choice made the prediction fail rather than rescuing it, so it is
  not a confirming bias.
- **L9. Injected QP errors carry a signature.** A QP moved to ERR by software gives vendor syndrome 0xf5, and the
  libraries' own classifier prints it. The evaluator used it to tell QP errors from revoked remote access. This is
  legitimate library output, but QP-error identification here may not carry over to QP errors from hardware
  faults.

## Checks that passed

- **Nothing outcome-relevant changed after the tag** `[measured]`.
  - The sha256 of all 17 files in `PREREG.txt` matches the working files.
  - `git diff prereg/blind-apps-v1^{commit}..HEAD` contains only `results/20261009/judgments.csv`.
  - The seal header records `git_head` `85147b24`, the last harness commit (13:51:45). It also records the
    predictions, config and generator sha256, and all three match the current files.
  - Order of events: seal created 13:52:28, tag 13:52:59, first runner read of the seal 13:55:33. Under relatime
    the seal's atime is 13:55:33, so nothing read the seal between its creation and the first hold.
  - Bundle:
    - The 13 files of `~/blind-bundle` on rain match the md5 in `deploy_check.txt`, and none is newer than the
      tag.
    - The deployed `node_agent.py` and `ddp_entry.py` equal the repository's copies.
    - Every runner start had `md5_match=1` (15 of 15), so the sunny bundle matched rain at each hold.
- **Reveal order** `[measured]`. Judgments committed 15:42:00 (sha256 `afb3ae06`, as in `SCORE.md`), seal copied
  15:42:09, scorer run 15:42:15.
- **Fault application** `[measured]`:
  - `derive(entry, calib.json)` equals the recorded parameters in 166 of 166 trials.
  - Hook variables were set on the scheduled target only.
  - Hook lines appeared only in the target rank's log, with no mismatch.
  - The PID in every kill and stop ack equals the target's application PID (50 of 50).
  - DDP kills and stops fired at the scheduled iteration (16 of 16).
  - Mute rules: `rules_left` was 0 in 24 of 24 trials, and `chain.sh` cleanup reported `deleted=0 left=0` after
    every hold.
  - Signals went by PID (`node_agent.py:88-102`). The process group was killed at EXIT, EOF or exit
    (`node_agent.py:70-77`). No process was left after any trial.
- **"Fault not applied" exclusions.** The 4 excluded trials (L6) were handled correctly. They have `applied = 0`
  and therefore `valid = 0`. Each is counted in its own cell's column in `SCORE.md` and was not refilled, and none
  enters a prediction.
- **Outcome order** (`rows_blind.py:214-229`).
  - None of the 36 harness-ended trials had a correct result (GIN kill 7, GIN QP error 14, NVSHMEM kill 7,
    NVSHMEM remote-access 8). So no trial that was slow but finished was called HUNG.
  - **GIN QP-error hangs (14).** In each, the hook fired 8–104 ms after the header and moved 4 of 4 QPs. Neither
    rank printed any line after the header, and both were wall-capped at 60 s. HUNG is correct. The 2 recovered
    trials fired at 113–115 ms.
  - **Error patterns.** A scan of every TRANSPARENT trial for error-like words found only teardown lines ("abort
    called", "Abort COMPLETE", "user devComm abort flag set"), recovery lines and management-loss lines. No error
    line was missed.

## Nits

- **Section 12 timestamps are inconsistent.** Its rows "13:55 정규식 수정" and "13:55 첫 봉인 폐기 결정" carry
  times after the new seal (13:52:28) and the tag (13:52:59). Git shows the regex fix committed at 13:51:45, so
  the actual order was correct; only the row times are wrong.
- **`schedule_gen.py verify` checks less than its docstring says.** It checks only the config sha256
  (`schedule_gen.py:122-134`), not the predictions or generator hashes. I checked those by hand; both match.
- **`score.py` does not re-derive the fault parameters** from the seal and `calib.json`. I did (see above).
- **`exit.txt` carries no times.** The evaluator infers kill and harness-end times from the last lines. That is
  fine, but say so in the brief.
- **IPv4 defaults in scripts.** `hold.sh:20`, `chain.sh:14` and `deploy_blind.sh:24` have an IPv4 literal as the
  `SUNNY_SSH` default. 37 other harness scripts on master use the same pattern. I did not run the address filter
  to check whether this is allowed.
- **Labelled pilot views sit beside the evaluator folder.** The pilot's demo views (`blind_pilot_view/demo/...`,
  named by class) are in the same scratchpad as the evaluator's folder, and only the brief keeps the evaluator out.
  The evaluator's scripts refer only to `blind_eval`. The atimes of those files cannot show later reads under
  relatime. The same limit applies to `raw/*/trial.meta`, as already noted in section 18.
