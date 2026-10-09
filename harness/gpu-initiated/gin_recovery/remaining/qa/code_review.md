# gin-remaining: code review of the measurement code after the main run

Reviewer: an independent agent, 2026-10-09, after holds H1–H5 (`results/20261009/`, 159 trials and runs, scored
15:33:59).

Scope: the drivers, runners, holds, deploy scripts, parsers and scorer of this study. The library was re-read only where a
scored column depends on it (log lines, copy counters, the degraded release). The layer itself was reviewed twice before
the run (EXPERIMENT.md 9.1 (f), 12).

Read-only review:
- No study program, runner, scorer or cluster command was run, and there was no git write.
- Python and awk were used only to read the raw per-trial files and `trials_scored.csv`.
- The tag was read with `git show prereg/gin-remaining-v1:<path>`. Early on I also ran `git status` and one
  `git diff --stat` against the working tree. These paths carry the `mgmtip` filter attribute, so git may have run the
  clean filter on stat-dirty files. Nothing from it was printed and nothing changed.
- `~/.config/rdma-error/` was not read. Deployed bundle checksums were read on rain only (local `md5sum`); sunny was not
  re-checked after the run.

Marks: `[source]` read in code; `[measured]` counted by this reviewer from the raw per-trial files (`*_meta.txt`,
`*_r*.kv`, `*_r*.log`, `*_rain.kv`, `*_sunny.kv`, `hold_*.out`), not copied from `SCORE.md`; `[inferred]`; `[unverified]`.

Paths: scripts without a folder are in this study folder. The two-rank driver is `../gin_ts2.cu`. "Tree" is
`agent_ts2hr/nccl-src` in the session scratch, and `gin_host_gdaki.cc` is `src/transport/net_ib/gdaki/gin_host_gdaki.cc`
there.

## Verdict

**The scored verdicts stand. No blocker, no high finding.**
- 33 of the 34 predictions hold, and the cudaMalloc-only prediction (GS2) fails, exactly as the pre-registered rules read
  on the raw files.
- No prediction passes vacuously: an empty field makes every comparison false (`../s2_close/score.py` `Nil`), and every
  passing trial has the columns its formula needs.
- Nothing that produced `SCORE.md` changed after the tag (Focus 4).
- The main-run folder holds only trials written after the tag.
- The spot recounts agree with `SCORE.md` (last section).

**Two medium findings limit what the conclusions may say.** They do not change any verdict.
- **M1.** In the cells where the kernel load comes after the GIN launch, no GPU-filling block ran during the fault or the
  recovery. These are the GPU-full cell with its two controls (GR1–GR3, GC1, GC2) and the load-only cells (GS1, and the
  load cell of GS4). There "GPU full" means "every CUDA stream held by the application's kernel load", not "SMs
  occupied".
- **M2.** The cudaMalloc-only cell makes an 8-byte allocation. Its failure (GS2) refutes the CUDA guide's allocation rule
  only for that small size.

**Low findings, none of which changes a verdict:**
- The re-review items L-A (refusals counted as served) and L-B (the degraded clock starts at the decline) are checked
  against the raw files below; neither has an effect here.
- DG6's "not on the bound" part is not in its formula.
- After a degraded release, the end-of-run receive check is not synchronized with the senders.
- The benchmark's race has about two effective device contenders, and HB2 passes with a small margin.
- NG1's strength is stated as a measured bound.
- Section 8's stop and refill rules are applied after the run only.
- The benchmark and NIC gate runners count no leftover processes.
- The hq controls run device code built with the hr headers.

## What was checked

| Area | How | Result |
|---|---|---|
| Driver sources vs builds | `md5sum` of the committed sources against `agent_ts2hr/out/build_info.txt` and `out/ngt/build_info.txt` | `../gin_ts2.cu` `1779db9d`, `gin_mr.cu` `a6a526ad`, `hm_bench.cu` `9b13a4b8`, `nic_gate_test.cu` `4d87f2b8`: equal. `hr_layer.diff` `66f61272` and `gin_transparent_hr.diff` `de986325` as in §12 `[measured]` |
| Deployed bundles (rain, after the run) | `md5sum ~/gi-bundle/gin_ts2/...` | hr libnccl `2dee2b5b`, hr and hrp `gin_ts2` `4e81d8d8`, `hm_bench` `a00094b0`, hrp libnccl `786f70bc`, `mr/hr/gin_mr` `d588e9ce`, `ngt/nic_gate_test` `abb2af4c`, hq `c1311625`, hqp `4fa076e1` with its `gin_ts2` `3e053ff2`: all as in §5 and §12 `[measured]`. sunny: deploy-time check only (`deploy_check.txt`, `deploy_ngt_check.txt`) `[unverified after the run]` |
| Post-tag changes | `git show <tag>:<path>` blob md5 against the working file. For files whose md5 differs, a line diff that drops the ssh-target default line, printing only a count | See Focus 4 |
| Main-run folder | mtimes of the 159 `*_meta.txt` files | 14:53:34–15:33:13, all after the tag commit (14:49:16); `SCORE.md` and `trials_scored.csv` 15:33:59; no pilot trial in it `[measured]` |
| Hold safety records | `chain.out`, `hold_H*.out`, `snap_*`, `mlx5_new_*`, STOP files, `LEFT_STREAK` | See Focus 2 |
| Spot recount | raw logs and kv of the cells listed in the last section | agrees with `SCORE.md` |

## Focus 1: drivers

### 1.1 The split of the three calls (`../gin_ts2.cu`) `[source]`

- **Parsing** (1155–1162). `GIN_TS_HOG_CALLS` is split on commas into load, malloc and stream. "all" or an empty value
  keeps gin-harden's order, and `GIN_TS_HOG_PREALLOC=1` still means none. A misspelled list yields
  `hog_calls_after=none`, which the scorer's configuration check rejects for every GPU-full cell (`score.py:183–184`).
- **Before the GIN launch** (1190–1198), each call not listed is made: the occupancy query plus an attribute read of
  `hogKernel` (load), `cudaMalloc` of the 8-byte sink, and the stream. Kv `hog_calls_after` (1199–1205) records the list.
- **After the launch** (1280–1285), the listed calls are made in gin-harden's order, then the hog launch (1293) and the
  probe (1298–1329).
- **Equivalence.** Without the variable, the program makes the same calls in the same places as before, plus one kv line.
  The PREALLOC path is unchanged.
- **Measured.** Every hog trial's kv `hog_calls_after` equals its cell on both ranks (also a config check). So each
  single-call cell has exactly one call between the two launches `[measured]`. Two qualifications:
  - The malloc call is 8 bytes (M2).
  - "Load" is the first use of `hogKernel`, which is an occupancy query (L1).

### 1.2 Is the GPU-filling fill real?

- **Malloc-only and stream-only cells (16 trials, H2): yes.**
  - At the probe, 20 ms after the hog launch, 191 of 192 blocks were resident on rain and 287 of 288 on sunny. The missing
    slot is the GIN kernel's CTA.
  - The probe copies completed 8/8 within 200 ms on both ranks.
  - The hog spins 3 000 ms from 0.2 ms after the GIN launch, and the fault came 582.8–1146.8 ms after the GIN launch. So the
    SMs were full during the fault and the round `[measured]`.
- **The 28 trials whose load comes after the GIN launch: no.** These are `rh_hog_f1_b` @hr 10 and @hq 5,
  `rh_hog_copystream_f1_b` @hr 5, and `rh_hogcall_load_f1_b` @hq 5 and @hr 3.
  - Computed as the first hog block's start, minus the node's constant globaltimer offset, minus that rank's GIN kernel
    time, the result is −1.1 to −0.2 ms on rank 0 and −2.9 to +0.2 ms on rank 1.
  - The offset comes from the 16 immediate-start trials of the same hold: rain 3 398.0–3 398.1 ms, sunny
    3 781.7–3 783.3 ms.
  - So the first hog block started when the GIN kernel ended (1 816.5–2 064.4 ms on rank 0), after the round. During the
    round only the GIN kernel's CTA was on the GPU `[measured]`. See M1.

### 1.3 Per-edge outcomes under the degraded rule (`gin_mr.cu`, `rows_hr.py`, `../multirank/rows_mr.py`) `[source]`

- **The untimed wait.** A receive edge waits with the untimed `waitSignal` (`gin_mr.cu:330–331`). If it returns with the
  signal still below the target, thread 0 counts a release (332–336):
  - the edge's rc becomes `ncclRemoteError`, set by the driver, not returned by the library;
  - a host-mapped flag `rel[edge] = it + 1` is set and fenced to the system.
- **Edge indexing is correct.** One CTA serves one edge; sends come first, then receives (`gin_mr.cu:649–673`). The host
  polls `hRel[nTx..nE)`, which is the same index.
- **Late, never early.** If a signal lands between the abort return and thread 0's read, the next iteration's wait returns
  at once and records the release there.
- **Host-side timing.** The host polls the flags every 0.5 ms before the async error and every 1 ms during the grace period
  (944–966). `rx_<ab>_rel_mono_ms` is therefore the host's first sight of the flag, within about 1 ms of the device write.
- **Column definitions.**
  - `rel_dead_r<s>` reads `rx_3s_rel`, and `rel_after_dead_ms_r<s>` subtracts the survivor's first judged-dead line, on
    its own clock (`rows_hr.py:219–229`).
  - `n_rel_surv` counts the flags of the six survivor-to-survivor edges.
  - `surv_tx_ok` counts sender `done == iters` with rc "no error".
  - `surv_rx_failed` (`rows_mr.py`) counts receiver rc ≠ "no error".
- **Survivor receives are released by the degraded rule.** Only rank 3 declines, so a survivor's word 0 can go up only
  through the degraded rule here: not every peer is down, and the application calls abort only after its kernel ends or
  after the 15 s or 40 s grace.
- **Measured.** All 90 receive edges of the 10 untimed hr trials released (`rx_*_rel=1`). The host saw each release
  0.2–8.0 ms after the rank's degraded release line (n=90) `[measured]`.
- **Caveat.** "Failed" on a released edge means the application's wait returned early, not that data was lost (L5).

### 1.4 NIC gate test (`nic_gate_test.cu`)

**What it detects** `[source]`:
- The host writes the odd epoch as a 4-byte NIC write next to 16 384 (phase a) or 2 048 (phase b) threads doing 64-bit
  atomics on the same word (345).
- It reads the word back over the NIC before anything else (350–355).
- A 64-bit atomic that read the word before the write and wrote it back afterwards leaves a stale high half. That half
  stays stale, because only the host writes it, so the next read-back sees it: a lost write (FAIL).
- If the NIC write instead disturbed the low half, the end-of-phase count would be non-zero (`lost_inc`), or quiescing
  would time out.
- The Dekker check compares `entered[epoch]` snapshots across the hold and the next even epoch (366–392).
- The line check compares the two index words with the enter count (412).
- The write and read paths are those of `gdakiLbXfer`: a WRITE, then an 8-byte READ of the same word, signaled
  (`nic_gate_test.cu:260–301` against `gin_host_gdaki.cc:1586–1668`).

**It cannot pass vacuously.** PASS needs all of the following (413–414):
- rounds > 0, enters > 0 and backouts > 0;
- the final high half, read by `cudaMemcpy` and not over the NIC, equal to the last NIC write;
- zero lost writes, Dekker violations, threads inside during an odd epoch, quiesce timeouts and lost increments;
- index words intact.

NG1 also requires at least 1 000 rounds in each phase.

**Measured:**
- Backouts equal rounds × threads in every phase of every run: 16 384 per round in phase a, 2 048 in phase b. Every
  thread saw every odd epoch the NIC wrote.
- `max_count` was 16 384 in phase a and 2 048 in phase b in every run.
- Over the 5 runs there were 87 793 odd-epoch writes on rain (a 43 730, b 44 063) and 87 351 on sunny (a 43 379, b
  43 972), with 0 lost.

See L8 for what this bounds.

**Cleanup** `[source]`:
- On the normal path the program destroys the QPs, CQ, MRs and PD and closes the device (561–567).
- The error paths `_exit`. The kernel's uverbs teardown and the CUDA context teardown release the MRs (including the dmabuf
  MR), the QPs and the GPU buffer.
- If the stop flag could never be written, the 75 s program watchdog and the runner's `timeout -s KILL 90` end the run. It
  would then be excluded (exit 7), not scored as FAIL. That needs 100 consecutive lost rewrites (395–403).
- Nothing persistent changes: no GID or port change, loopback only.

### 1.5 Does `hm_bench` measure what it claims?

- **Latency: yes** `[source]`.
  - One thread does 20 000 dependent operations: the next address depends on the previous result (51–72). Before the timed
    run there is a 64-operation warm-up.
  - It is timed with `%globaltimer`, whose 32 ns step is negligible over 3.6–12 ms.
  - The `host_atom` variant is gpu-scope on mapped host memory, and `host_atom_sys` is the sys-scope form. A host gate would
    need the sys scope, which is about 9–12 ns slower and therefore strengthens HB2 `[measured]`.
- **Race: partly** (L6).
  - Lost host writes are real and a lower bound. The host reads its own store back 64 times, and any other value can only
    come from a device read-modify-write that wrote back a stale high half.
  - The device side is 2 blocks of 32 threads, which in effect act as about two contenders `[inferred]`.

## Focus 2: runner safety

- **Ports.** `portpick.sh` is gin-peer's copy (29000–30999, checked on both nodes). 149 of 149 runner trials took the first
  candidate with nothing skipped. `bind_fail` was 0 in all 149. The benchmark and the NIC gate test use no port
  `[measured]`.
- **Kills.**
  - Rank 1 (two ranks) is killed by `os.kill` on the `gin_ts2` child of the recorded remote `timeout` PID, after checking
    that PID's command line for the trial's unique tag (`run_trial_hr.sh:109–110`). Rank 0 is killed as the child of its
    recorded `timeout` (125–128).
  - At cleanup, only the recorded remote PID and its children are signalled, after the same tag check (149–150).
  - N ranks: the target is verified through `/proc/<pid>/stat`, by name and parent (`run_mr_hr.sh`, `PYK`).
  - `hold.sh` and the benchmark and NIC runners kill nothing. Only these lines differ from gin-peer's runners: `DRVKEY`,
    `drvbin`, file prefixes and `runner=` `[source]`.
- **Bounded times.**
  - Every rank runs under `timeout -s KILL` (watchdog + 20 s). The benchmark and the NIC gate test run under
    `timeout -s KILL 90` on each node, plus their own 60 s and 75 s watchdogs.
  - Every hold runs under `timeout -s KILL 880`. The longest hold, H2, took at most 636 s from start to rc, including the
    idle-link wait. The lock wait is outside that bound (`-w 10800`) `[measured: chain.out]`.
- **STOP rules.**
  - STOP_left: the streak in `cells.sh:32–42` and the 150 s stale wait in `hold.sh:38–45`.
  - STOP_mlx5: new command-error lines, or growth of the firmware-command failure counters.
  - STOP_cuda: rc 139, or an illegal-address or launch-failure line in a meta, log or kv file of the hold.
  - STOP_iptables: in `chain.sh`.
  - Results: no STOP file; `LEFT_STREAK` 0; `left=0` in 149 of 149 runner trials; 0 new mlx5 lines in each hold; rain
    cmd_err 2, sunny 0 and rain firmware failures 31, the same before and after every hold; iptables `gin-` rules 0 before
    and 0 after; all five holds rc 0 `[measured]`.
  - Gap: the benchmark and NIC runners write no `left=` (L10).
- **NIC loopback resources.** See 1.4. The test touches only its own PD, CQ and QPs on the node's HCA; no traffic leaves
  the NIC.

## Focus 3: parser and scorer

- **Columns match the §3.1 definitions** `[source]`. Checked in `rows_hr.py`:
  - START, LBON, LBOFF and TDCOPY lines; `served`, `kept` and `served_rec`; `n_degraded`, `degr_ranks` and
    `degr_after_dead_ms`;
  - the kill-cell columns (1.3); `bench_row`; `ngt_row` (the minimum rounds over the two phases, sums of the violation
    counts, and `ng_result` from the final `result=`, not the phase `a_result`).

  The regexes match the library's format strings (`gin_host_gdaki.cc:7072–7078` for the teardown line, `1409` and `1656`
  for both copy-timeout forms). Inherited parsers: `../harden/rows_hd.py:80` (`device-state copy \(.*\) not complete
  after`) counts the NIC form `(over the NIC, <dir>, <n> B)` as well, so `n_copyto` is not blind on hr.
- **`td_stream_copies` covers every helper stream copy** `[source]`. `nStreamCopies` is incremented in all three
  helper-thread stream paths: D2H 1689, H2D 1699 and fill 4293. The other `cudaMemcpyAsync` and `cudaMemsetAsync` calls in
  the file run only off the helper:
  - the application-thread recovery API, behind `!gdakiTsInHelper` (2398–2401, 2437–2442, 2497–2499);
  - setup (6798);
  - the fault hook's own stream (2016).

  So GR3 and RG2 cannot pass while a round copy used the stream.
- **Exclusions match §8** (`score.py` `status2`, `status4`, `statusb`, `statusg`): bind failure; hook or kill not applied,
  including fires outside traffic and the expected fire sets; trigger miss; the 3 s hog window; cycle spread empty or
  over 250 ms; firmware overrun; benchmark rc ≠ 0; NIC gate test without a verdict (rc not 0 or 1). Configuration checks:
  - build start lines, driver bundle, copy path and NIC-off lines, test switches, `hog_calls_after`;
  - stall switch lines, `rx_untimed` in the untimed cell, and dmabuf with a link-local GID for the NIC gate test.

  Two §8 rules are not coded (L9). In this run 0 trials were excluded, 0 failed a configuration check, and 159 of 159 were
  scored.
- **Vacuous passes: none found.** Empty fields evaluate false, and every formula that could have passed on an empty column
  had its column filled in every scored trial:
  - GR2's probe was present (`probe_n` 8);
  - GR3 and RG2 had the teardown line in every log;
  - DG5 and HB1 had their kv files.

  NG1 and HB3 require activity: rounds, `race_dev_ops > 0`.
- **L-A (CY3 counts refusals as served)** `[measured]`.
  - The scorer counts `n_served`, as pre-registered.
  - Strict reading, recounted: every hr cycle trial has 3–4 in-wait answer lines and the same number of "back to round"
    lines. In 9 trials, 2 of the nested rounds ended in the responder's recovery with that peer before the back line, and
    1 did in n3, so count(`n_served_rec` ≥ 1) = 10/10.
  - The chain's one in-wait answer was a refusal in 5/5.
  - CY3 therefore also holds when only nested recoveries count. Report `n_served_rec` next to CY3 (L2).
- **L-B (the degraded clock starts at the decline)** `[measured]`.
  - The columns measure from the first judged-dead line (`rows_hr.py:214–229`).
  - From the survivors' logs: the decline of rank 3 came 5.4–8.5 ms after the judged-dead line, and the degraded release
    line 2 000.0–2 000.1 ms after the decline. That is 45 survivor-runs: 30 in the untimed cell and 15 in gin-peer's cell.
  - The scored values (DG1 2 006.7–2 013.0 ms, DG2 2 005.4–2 008.5 ms, DG6 2 005.9–2 008.4 ms) satisfy the 2 000 ms lower
    bounds from either start (L3).

## Focus 4: changes after the tag

- `prereg/gin-remaining-v1` is an annotated tag on `b0489048`, which is HEAD of `exp/gin-remaining`. `git diff
  prereg/gin-remaining-v1 HEAD` is empty.
- The tagged blob and the working file are byte-identical for all of these:
  - this study's `score.py`, `rows_hr.py`, `predictions.csv`, `PREREG.txt`, `cells.sh`, `chain.sh`, `portpick.sh`,
    `gin_mr.cu`, `hm_bench.cu`, `nic_gate_test.cu` and `EXPERIMENT.md`, and `../gin_ts2.cu`;
  - every module the scorer imports: `../s2_close/score.py`, `../s2_close/rows_extra.py`, `../scripts/ts2/rows.py`,
    `../pair_check/rows_pc.py`, `../oneway/rows_ow.py`, `../harden/rows_hd.py`, `../handoff/rows_hf.py`,
    `../multirank/rows_mr.py` and `../peer/rows_pq.py`.
- `hold.sh`, the four runners and the two deploy scripts differ from their tagged blobs only in the ssh-target default line
  that the repository's filter rewrites (0 other differing lines).
- `predictions.csv` sha256 `a63389f2…` equals `PREREG.txt`.
- Untracked or ignored: `results/`, `__pycache__/` (compiled 15:33:20 from the tagged `rows_hr.py`) and `qa/`
  `[measured]`.
- No change affects scoring.

## Findings

### Blocker

None.

### High

None.

### Medium

**M1. "GPU full" is not the condition of the load-after cells.**

- **Where:**
  - `cells.sh:31,52,54,56` (cells);
  - `../gin_ts2.cu:1280–1293` (the calls after the launch, then the hog on `st3`) and `1298–1329` (the probe);
  - the GR1 label in `score.py:84` ("GPU 가득");
  - `EXPERIMENT.md:175` (3.3, GR1 row), `:262` (§7 cell table) and `:95` (H3's "GPU 가득 참 셀").
- **What happened:**
  - With the kernel load after the GIN launch, the load waits for the running GIN kernel, and every later command on every
    stream queues behind it: the hog launch and the probe copies.
  - In all 28 load-after trials, the first hog block started 0–3 ms around the GIN kernel's end, after the fault (582.8–1
    146.8 ms after the GIN launch) and after the round (1.2) `[measured]`.
  - During the hr recovery the SMs were idle apart from the GIN kernel's CTA.
- **Effect on the results:**
  - No verdict changes. GR2 itself requires `hog_started_probe == 0`, and the GR, GC and GS1 formulas do not depend on SM
    occupancy.
  - What GR1 shows is "a round recovers transparently over the NIC while the application's kernel load holds every CUDA
    stream", not "while the GPU is full".
  - Only the malloc-only and stream-only cells have the SMs full:
    - hq recovered over the stream, 10/10;
    - hr recovered over the NIC, 6/6.
  - No cell has both conditions at once. With this driver the held streams also keep the hog from starting.
- **Recommendation:**
  - In §15–17 and the README, describe GR1 by the held streams and cite the malloc and stream cells for the full-SM case.
  - Keep `rh_hog` only as a key.

**M2. The cudaMalloc-only cell tests an 8-byte allocation.**

- **Where:**
  - `../gin_ts2.cu:1197,1284` (`cudaMalloc(&hogSink, sizeof(unsigned long long))`);
  - earlier small allocations in the same process, e.g. the probe word at 1181, and NCCL's own;
  - `predictions.csv:19` (GS2) and `EXPERIMENT.md:96` (H4).
- **What happened:**
  - An 8-byte request after other allocations is probably served from device memory the driver has already mapped. Then
    no mapping changes, and no implicit synchronization follows `[inferred: allocator internals are not documented]`.
  - Measured, hq: the probe completed 8/8 within 200 ms on both ranks, with 191 and 287 hog blocks resident, transparent
    5/5 and no copy timeout. hr: transparent 3/3.
- **Effect on the results:**
  - GS2 "틀림" (0/5) is the correct score for the cell as registered.
  - The conclusion may say that the 8-byte cudaMalloc that gin-harden's driver makes did not hold the streams. It may not
    say that cudaMalloc does not synchronize.
  - An allocation that maps new memory, and `cudaFree`, are untested `[unverified]`.
  - H4 then reads: the kernel load held the streams; stream creation and an 8-byte cudaMalloc did not.

### Low

**L1. The load cell does not separate "occupancy query" from "module load".**
- **Where:** `../gin_ts2.cu:1280–1283`. Before the launch, the load path also reads the kernel's attributes (1190–1195).
- **What happened:**
  - The call that held the streams is the first use of `hogKernel`, an occupancy query, after the GIN launch.
  - The attribution to lazy loading is inferred. It fits two facts:
    - the hog started exactly when the GIN kernel ended (M1);
    - earlier `CUDA_MODULE_LOADING=EAGER` cells behaved differently (`../scripts/ts2/batch.sh:162–167`).
  - No cell separates the two, for example by loading the kernel before the launch and querying after it.
- **Effect:** wording only. Write "the first use of a not-yet-loaded kernel after the GIN launch" and mark lazy loading
  as `[inferred]`.

**L2. CY3 counts refusals as served (re-review L-A).**
- **Where:** `predictions.csv:4`; `rows_hr.py:36–39`, `101–109` and `128–132`.
- **What could happen:** a trial whose only in-wait answers were NACKs would pass CY3.
- **Effect:** none here (Focus 3: `n_served_rec` ≥ 1 in 10/10). Report `n_served_rec` with CY3.

**L3. The degraded columns start at the judged-dead line, not at the decline (re-review L-B).**
- **Where:** `rows_hr.py:213–217`, `227–229`.
- **What could happen:** measured from judgment, a degraded release up to 8.5 ms early would still pass the 2 000 ms lower
  bound.
- **Effect:** none. The decline-based recount gives 2 000.0–2 000.1 ms in 45 of 45 survivor-runs (Focus 3). Report it next
  to DG1 and DG2.

**L4. DG6's "not on their bound" is not in its formula.**
- **Where:** `predictions.csv:12` uses `surv_rx_failed == 6`. `../multirank/rows_mr.py` counts any receiver rc that is not
  "no error", so a 10 s bound timeout would also count.
- **Measured:**
  - All 30 survivor receive edges of `mr4_kill3_peer@hr` (5 trials) ended with "remote process exited or there was a
    network error" at iteration 651–659 of 1 000.
  - Their senders were still sending every 15 ms (all 1 000 sends completed), so the per-wait 10 s bound could not have
    expired.
- **Effect:** none on the verdict. The "not on the bound" claim rests on the rc strings and timing, not on the formula.

**L5. After a degraded release, the end-of-run receive check is not synchronized with the senders.**
- **Where:** `gin_mr.cu:1040–1066`. The host reads the receive window and the final signal as soon as its own kernel ends.
  See also 330–336.
- **What happened:**
  - Once a rank's receives are released, its kernel ends when its own sends finish.
  - Ranks 0 and 2 share rain's GPU and finish about 205 ms after rank 1 on sunny: `kernel_ms` 15 357.6–15 365.7 against
    15 152.0–15 156.2 in the untimed cell `[measured]`.
  - Rank 1 therefore checks its window before ranks 0 and 2 have sent their last iterations.
- **Measured** in 15 of 15 trials (10 untimed, 5 gin-peer cell):
  - On rank 1, the edges 0>1 and 2>1 show a final signal of 989–990 of 1 000, with 12–13 slots still holding the poison
    pattern.
  - The senders report 1 000/1 000 sends with no error.
  - The edges into ranks 0 and 2 read 1 000/1 000 with no bad slot.
- **Effect:** no prediction reads these columns. Still, do not cite a released edge's `hostbad`, `missing` or `sigexact` as
  data loss: the senders' completions say the data landed `[inferred]`. Do not cite them as "data intact" for rank 1
  either. Claiming delivery would need a barrier before the receive check.

**L6. The benchmark's race has about two effective device contenders.**
- **Where:** `hm_bench.cu:75–85,148`: 2 blocks × 32 threads on one 8-byte host word.
- **What happened:**
  - `race_dev_ops` is 89.1–103.6 M per 2 s, about 19–22 ns per counted operation.
  - One dependent host atomic costs 586–609 ns.
  - This fits the 32 lanes of a warp being combined into one PCIe read-modify-write `[inferred]`, so about two concurrent
    device RMW streams.
  - `race_lost_host_writes` counts only what the 64 read-backs see, so it is a lower bound.
- **Effect:** HB3 ("no device update of the count lost") is a weak test of device-to-device atomicity on host memory. Its
  verdict is unaffected. The strong result for H6's safety part is the lost host writes: 4 132–4 739 of 26 001–26 434
  writes per run, 15.7–18.2% `[measured]`.

**L7. HB2 passes by a small margin.**
- **Where:** `predictions.csv:33`.
- **Measured:** host atomic minus device atomic is 407.9–423.9 ns over 10 node-runs, against the 400 ns bound. With the sys
  scope it is 416.7–434.8 ns.
- **Effect:** the verdict holds. Report about 0.41–0.42 µs more per dependent atomic, and do not present 400 ns as a
  comfortable floor.

**L8. What NG1 bounds.**
- **Where:** `nic_gate_test.cu:345–360` and `412–414`.
- **Measured:** 0 lost writes in 87 793 (rain) and 87 351 (sunny) odd-epoch NIC writes made under atomic traffic (1.4). By
  the rule of three, the per-write loss probability is below about 3.4 × 10⁻⁵ per GPU at 95%.
- **Scope:**
  - Only odd-epoch writes race the SM atomics. Even-epoch writes land while the threads park on loads, as in the library's
    protocol.
  - Not covered: the layer's rare `atomicOr` and CAS paths, and its sys-scope parked reads (9.5).
- **Effect:** NG1 holds. 9.1 (d)'s `[미확인]` becomes "no loss in about 87 000 contended writes per GPU". That is a bound,
  not a proof.

**L9. Two §8 rules are applied after the run only.**
- **Where:** `score.py:152–185`, `205–221` and `229–237`.
- **What could happen:**
  - A configuration mismatch gets a `config_*` status, and the trial is set apart. Nothing stops the block during the run,
    although §8 (`EXPERIMENT.md:304`) says the block stops.
  - The 50% refill limit (`EXPERIMENT.md:302`) is not coded.
- **Effect:** none in this run: 0 configuration failures, 0 exclusions, 0 refills.

**L10. The benchmark and NIC gate runners count no leftover processes.**
- **Where:** `run_bench_hr.sh:28` and `run_ngt_hr.sh:31` write no `left=`, so `cells.sh:33–41` resets the streak. §8
  (`EXPERIMENT.md:329`) says leftovers are counted after every trial.
- **What could happen:** only the next hold's stale check (`hold.sh:38–45`) would see a leftover, and H5 was the last hold.
- **Effect:** none on results. rc was 0 on both nodes in 10 of 10 runs, and `timeout -s KILL 90` bounds every run.

**L11. The hq controls run device code built with the hr headers.**
- **Where:** `cells.sh:18` (`DRV=hr` for hq), `run_trial_hr.sh:43–46,102,119`, and `run_mr_hr.sh` with `MRKEY=hr`.
  Documented in §9.2.
- **What happens:** with the hq library, the hr header's `tsWaitWord` makes a per-QP wait read the peer's word, which hq
  raises on a decline, instead of word 0.
- **Effect:** none of the control predictions reads a per-QP wait result:
  - CY4 reads the library's round lines and `transparent_ok`;
  - DG5 reads the untimed `waitSignal`, which reads word 0 under either header;
  - GC1 and GS1–GS3 read copy timeouts and probes.

  The verdicts are unaffected. A statement about how a pure-hq application's per-peer sends or flushes end after a decline
  cannot be taken from these controls.

## Nits

- `rows_hr.py:126` keeps only the last copy-path-at-teardown line of a log. Every main-run log has exactly one, because each
  rank has one GDAKI context. A second context's stream copies would be hidden.
- `rows_hr.py:101–109` pairs a responder recovery with the open in-wait answer until a back line. The back count equals the
  in-wait answer count in all 10 hr cycle trials, so no stray pairing occurred.
- `score.py:173` checks five test switches for the two-rank cells but not the helper-stall switch, which no two-rank cell
  sets. `score.py:220` checks `rx_untimed` only for the untimed cell; `mr4_kill3_peer` has `rx_untimed=0` by its
  environment (meta).
- In hrp the start and NIC-path lines are INFO, so the production build's copy path is not visible in the WARN logs (0
  NIC-on lines in `hrp/`). RG6 and the latency cells do not depend on it.
- `hog_first_start_rel_ms` carries a per-node globaltimer offset: rain 3 398.0–3 398.1 ms and sunny 3 781.7–3 783.3 ms in
  H2, as gin-handoff recorded. Subtract it before quoting.
- At teardown, rank 1 made 724 NIC operations in the hr load-after cells against 508 in the hr malloc and stream cells.
  Rank 0 made 373 in all of them. This is unexplained and not used `[measured]`.
- The latency p50 values lie on 32 ns globaltimer steps (`*_lat_raw.csv.gz`). The 256 KiB p50 is 38.88 µs in all 10 runs,
  so LT2's 0.000 difference means "no difference at one timer step".
- `nic_gate_test.cu` never frees its GPU buffer or streams explicitly; process exit does.

## Spot recount (raw files, `[measured]`)

| What | Recount | `SCORE.md` |
|---|---|---|
| Cycle, hr: decline lines, handshake timeouts | 0 and 0 in 10 trials; 3–4 in-wait answer lines and the same number of back lines per trial | CY1 10/10 |
| Cycle, hq: handshake-timeout declines | 15 (3 per trial); first 24 504.7–24 507.3 ms after the round | CY4 5/5 |
| Untimed kill, hr: release flags | 90/90 receive edges (rank 3 to survivors 30, between survivors 60) | DG1, DG4 10/10 |
| Decline to degraded release line | 2 000.0–2 000.1 ms (45 survivor-runs) | (DG2 from judged-dead 2 005.4–2 008.5) |
| gin-peer kill cell on hr: survivor receive rc | 30/30 "remote process exited or there was a network error", iteration 651–659 | DG6 5/5 |
| GPU-full order: first hog block vs GIN kernel end | −2.9 to +0.2 ms (28 trials) | GR2 10/10 (no block at the probe) |
| Malloc and stream cells: resident hog blocks at the probe | 191/192 and 287/288; probe 8/8 (16 trials) | GS2 0/5, GS3 5/5 |
| NIC copy-path lines in hr | 258 lines, all `gid_index 1 (link-local)`, peermem 0 | config pass |
| NIC gate test | 0 lost writes, odd writes rain 87 793 and sunny 87 351; backouts = rounds × threads | NG1 5/5 |
| Benchmark | host − device atomic 407.9–423.9 ns; lost host writes 15.7–18.2% | HB2, HB3 5/5 |
