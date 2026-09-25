# Transparent recovery, step S1: GIN GDAKI, one peer, one QP, one operation in flight

Patch: `gin_transparent_s1.diff`, a full diff against NCCL v2.32.3-1 (12df1a11). It holds, unchanged, the
four layers that `gin_recovery_gpudb.diff` sits on, plus S1 (see "Stack" below). Driver:
`gin_ts1.cu`, an application with no recovery code in it. Scripts: `scripts/ts1/`. Results:
`results/20260925_ts1/` (the follow-up after the external review: `v2_*` and `summary_v2.md`; the
third review: `v3_*` and `summary_v3.md`). Design this implements: `../TRANSPARENT_RECOVERY_DESIGN.md` §3, §5, §6, §13
(step S1), with the changes listed in "Where S1 departs from the design".

Tags used below: **[measured]** = counted from the per-trial logs in `results/20260925_ts1/`;
**[source]** = read in the code; **[inferred]** = reasoned, not tested here.
Fault names (as in the rest of `gpu-initiated/`): F1 = local QP error (the test hook forces the
initiator's QP to ERR); F2 = remote access error (REM_ACCESS 10/0x88); F3 = peer QP error (the peer's
QP forced to ERR, peer alive; the initiator sees RETRY_EXC 12/0x81); F4 = peer process death (SIGKILL).

## TL;DR

- **What is transparent now [measured].** The application kernel is one unmodified `put + signal;
  flush` loop and never relaunches. Four kinds of recoverable fault were run: a local QP forced to
  ERR (F1), the peer's QP forced to ERR (F3, RETRY_EXC), five faults in one run with one landing on
  the re-posted WQEs, and a local ERR inside an in-flight op. The table counts runs in which all of
  the following held:
  - every flush returned `ncclSuccess` and all iterations ran;
  - every iteration's data was bit-exact, checked on the GPU when its signal arrived and on the
    host at the end;
  - the final signal was exact;
  - both hosts saw 0 async errors over about 9 000 to 121 000 `ncclCommGetAsyncError` samples per
    run.

  | cell | runs meeting all four |
  |---|---|
  | F1, blocking flush | 30/30 |
  | F1, flush with timeout | 10/10 |
  | F3, blocking flush | 10/10 |
  | F3, flush with timeout | 5/5 |
  | F1 ×5 in one run | 10/10 (50 rounds) |
  | F1 inside an in-flight op | 30/30 |
  | fault-free | 30/30 |

  Every recovery happened inside NCCL, in a helper thread per GDAKI context.
- **Exactly-once for the signal ADD [measured].**
  - The library reads how many of the requester's WQEs the responder executed, from the responder's
    QPC (`rmsn`, DEVX `QUERY_QP`), and re-posts only the rest.
  - In the in-flight cell, 14 of 30 rounds found that the responder had **already executed the ADD**
    although the requester's completion was an error. Nothing was re-posted in those rounds, and the
    final signal was still exact.
  - The other 16 rounds, and all 115 rounds of the main matrix, re-posted the WRITE and the ADD.
  - The third case, where the responder executed the WRITE but not the ADD (n = 1), never occurred
    naturally. The follow-up forces it with a test hook: the fault fires after the WRITE completed
    and before the ADD is posted. **30/30** rounds re-posted only the ADD, and data and the final
    signal were exact (see "Follow-up", point 2).
  - The second authority agrees: the responder's `next_rcv_psn` matched the executed count in
    105/105 first rounds (65 PSNs per 256 KiB op at PMTU 4096), and in 30/30 forced n = 1 rounds.
- **Cost of a recovery [measured].**
  - The helper's round takes **9.3–9.8 ms** (median per cell): quiesce 0.2 ms (1.1 ms for F3),
    Prepare 0.5, handshake 4.2–5.3 (it includes the peer's Prepare and Commit), Commit 3.3,
    re-post and resume 0.14.
  - From the device report reaching the mailbox to the waiter being resumed: 9.5–10.3 ms.
  - The application sees one slow iteration: F1 10.4 ms, the in-flight case 10.6 ms, F3 3.60 s.
    For F3 that is the RETRY_EXC detection at IB timeout 14; recovery adds 10 ms.
- **Declined faults surface, bounded [measured].**
  - **F2 (REM_ACCESS, 30/30).** Rank 0 declined 1.5 ms after the mailbox record ("class REM_ACCESS
    is not recoverable"). The flush returned `ncclRemoteError`, and both hosts saw the async error
    (rank 1 through FAIL).
  - **F4 (SIGKILL of the peer, 10/10).** The decline came 3.78 s after the kill, median
    [3.57–3.82] ("RETRY_EXC and the peer's socket shows FIN/RST"). The flush returned the error;
    `ncclCommAbort` returned on the surviving rank.
- **How long a wait can take, and how a stalled or dead helper surfaces [measured, follow-up and
  third review].** The bound depends on which wait it is:
  - **A flush or wait with the application's timeout** ends at that timeout, parked time included.
    With a 0.5 s timeout during a 3 s recovery it returned `ncclTimeout` at 469 ms (10/10).
  - **A blocking flush or wait** (no timeout) is bounded only by the library's hold,
    `NCCL_GIN_TS_HOLD_MS` (30 s by default). When the device's give-up loses to a host that already
    passed its commit point, the bound is 2 × hold (60 s by default). Nothing the application passes
    bounds it.
  - Measured with a 4 s hold:
    - the helper stalled or died before its commit point: the flush failed at 4.0 s, 30/30;
    - the helper stalled after its commit point: the give-up lost at 4 s. When the helper published
      at 6 s the run stayed transparent (10/10, slow iteration 6.01 s). When it stayed stalled for 12 s
      the flush failed at **8.0 s = 2 × hold** (10/10), and the helper then declined instead of
      re-posting.
  - **The async error is a separate mechanism.** The flush error above comes from the device's own
    hold expiring. The watchdog only raises the async error: with a 2 s round limit,
    `ncclCommGetAsyncError` reported it 2.0 s after the stall began. The watchdog never ends a
    device wait.
  - A 3 s round under the default 25 s round limit stayed transparent, with no false alarm (10/10).
- **Communicator teardown [measured, follow-up].**
  - Before the fix, `ncclCommAbort` never stopped the helper. For a devComm the application did not
    destroy, the helper outlived the communicator.
  - With a kernel held mid-round, the abort did not return within 15 s (1 run, the first smoke of the
    fix). The inferred cause is a device synchronization in NCCL's teardown that waits for the held
    kernel; the helper's own teardown line never appeared.
  - Now the abort stops the helper and fails the gates first. It returned in 0.6–1.0 s (10/10),
    and the held kernel had exited by then.
  - Third review: the teardown freed the helper's state, while `ncclCommGetAsyncError` on another
    thread could still read it. It now frees nothing. Tested with `ncclCommGetAsyncError` in a tight
    loop that was not stopped before the abort, 20 runs: every abort returned, with no crash and no
    failed call. A median of 1 600 calls fell inside the GIN teardown, and about 95 000–495 000
    calls inside the abort.
- **Negative controls [measured].** Each removes one resync step and breaks the run exactly as
  predicted (5/5 each):
  - **No ticket rebase on the device.** The re-post executed (rank 1 received that iteration) but
    rank 0's flush polled the stale slot and timed out.
  - **No host doorbell for the re-post.** The iteration never arrived (its slot stayed poisoned) and
    the flush timed out.
- **Flag off [measured].**
  - Behaviour is identical to the gpudb v2 build under F1: the flush returns `ncclRemoteError` at
    the faulted iteration, the async error is raised at the same point, and the receiver times out.
  - Latency: +1.0% at 4 KiB (p50 10.24 vs 10.14 µs) and +0.6% at 256 KiB (38.43 vs 38.21 µs).
    Attributed to the extra gate-flag load per post and wait and the changed code layout [inferred].
- **Flag on costs a lot on the fast path [measured].**
  - Phase-1 build: p50 went from 10.24 to 16.96 µs at 4 KiB (+66%) and from 38.43 to 41.28 µs at
    256 KiB (+7.4%).
  - Follow-up build: 10.24 → 16.42 µs at 4 KiB (+60%) and 38.43 → 41.34 µs at 256 KiB (+7.6%). The
    third-review build has the same device code and measured 16.42 and 41.31 µs.
  - Cost attribution at 4 KiB, removing one mechanism at a time **cumulatively** in this order, on
    the final build (`v2_lat/`):
    - system-scope fences → GPU scope: −2.94 µs;
    - then the poster gate: −1.89 µs;
    - then the counted poll region: −1.22 µs;
    - the rest (flag loads, code layout): 0.13 µs.

    The four add up to the 6.18 µs total.
  - The phase-1 attribution (3.3 + 2.6 + 4.7 µs) removed each mechanism alone. Those removals
    overlap (each fence was counted under "fences" and again under its own mechanism), and they
    summed to more than the total. They were wrong as a split (point 4 of the follow-up).

  Reducing this is S2 work (see "Next step").
- **Found by the tests [measured].**
  - The fault hook's thread and the helper once issued `2ERR_QP` on the same QP concurrently (1 of
    30 in-flight runs).
    - The firmware command never completed. Kernel log: `2ERR_QP(0x507) No done completion …
      timeout. Will cause a leak of a command resource`, about 104 s later.
    - The waiter's 30 s hold then expired and the flush failed.
  - Fix: every QP state change by the helper is now serialized with the hook (`opMu`, which
    Prepare, Commit and the hook already used). After the fix the cell ran 30/30 with no new kernel
    messages, and 150/150 on the follow-up build (one-sided 95% upper bound on the failure rate: 1.98%;
    10/10 more on the third-review build).
  - 1/30 before against 0 after is not proof that `opMu` fixed it: at that rate the two cannot be
    told apart statistically (follow-up, point 3). The causal claim rests on the mechanism: the
    kernel log names a `2ERR_QP` that timed out, and the code had two threads that could issue it
    on the same QP. The pre-fix build was deliberately not re-run, because reproducing the hang
    would leak another firmware command slot.
  - That one command-resource slot of rain's `mlx5_1` (0000:17:00.1) stays leaked until the mlx5
    driver is reloaded, which was not done.
    - **Every run from hold G (06:56) onward, including all follow-up runs, ran with that slot
      leaked.** This is a condition of those runs, not something shown to be harmless.
    - What was measured is limited [measured]:
      - rain's Commit time (dominated by firmware commands) had a median of 3.37 ms before the leak
        (115 rounds), 3.34 ms in hold G, and 3.37 ms in the follow-up (90 rounds);
      - per-hold debugfs counters show 0 new command failures in any follow-up hold;
      - no mlx5 kernel message has appeared since 06:45:02.
    - This covers only the concurrency these tests reach, a few commands at a time. It says nothing
      about a load that needs every command slot.


## Follow-up after the external review

An external reviewer raised five points. Each was checked against the code first. **All five were
correct**; none is disputed here. Points 1–3 led to code changes and new tests. Points 4 and 5 were
errors in this write-up.

The follow-up changes were reviewed twice by the independent reviewer before any follow-up
measurement (see "Independent review"). That review found one more major bug (a false watchdog
alarm), fixed before the runs.

All follow-up numbers in this section come from the follow-up build: libnccl md5 `110440e7`, driver md5
`faa6ee2e`. They are in `results/20260925_ts1/v2_*/`, and were run in holds `ts1b-H1`…`H4`
(non-prio, ≤ 15 min each) through `../common/cluster_run.sh`. Tables:
`scripts/ts1/followup_summary.py results/20260925_ts1`.

The third review changed only host code (next section). Its regression pass on the final build
reproduced the outcomes and latencies of this section.

### Point 1: "transparent" overclaimed its bounds — correct, fixed

| sub-point | verdict | change |
|---|---|---|
| (a) `flushAsync` can block up to 60 s | correct: it parked inside, up to 2 × hold | `flushAsync` makes one attempt at the counted region. During a recovery it returns a PENDING request, and the wait takes the ticket itself under its own deadline. Exception: the MCST DUMP after a `get` goes through the poster gate (that epoch declines anyway) |
| (b) a timeout flush did not charge parked time | correct: phase 1 restarted the timeout after each park, on purpose (and the review table below described that wrongly) | one deadline covers ticket, park and poll; on expiry the call returns `ncclTimeout` wherever it is |
| (c) a parked poster spins without bound | correct | posters give up after `NCCL_GIN_TS_HOLD_MS` through the same commit point as waiters, poison the QP (`status`) and skip the post; every later post and wait on that QP fails at once |
| (d) with the helper stalled or dead the error vanished | correct: in transparent mode the watcher hands the record to the helper instead of raising it | watchdog in the Q4 watcher thread: a round longer than `NCCL_GIN_TS_ROUND_MS` (25 s), or records queued while the helper's heartbeat is more than 1 s old, sets the communicator's async error (`ncclRemoteError`); the helper then declines |

Test knobs (rank 0 only, research build):
- `NCCL_GIN_TS_TEST_STALL=<ms>@quiesce|commit`: the helper sleeps inside the round, after its quiesce
  or after both commits;
- `NCCL_GIN_TS_TEST_DIE=quiesce`: the helper thread exits mid-round.

The application's grace after an async error is `GIN_TS_ASYNC_GRACE_S` (driver side). 10 runs per
cell, all rank 0 flushes blocking unless stated. Round limit 2 s and hold 4 s in the stall/die
cells, so that the bounds are short enough to measure:

| cell | n | first flush result (app) | its latency | later flushes | watchdog after stall/death | async error seen by the app, after the fault | `ncclCommAbort` | kernel still running when abort returned |
|---|---|---|---|---|---|---|---|---|
| `stallq_b`: helper stalls 8 s after quiesce | 10 | `ncclRemoteError` 10/10 | 4000.3 ms [4000.2–4000.4] | – | 1999.8 ms | 10/10, 2012 ms [2001–2016] | 795 ms [516–958] | 0/10 |
| `stallc_b`: helper stalls 8 s after both commits | 10 | `ncclRemoteError` 10/10 | 4000.3 ms | – | 1990.0 ms | 10/10, 2012 ms | 806 ms | 0/10 |
| `die_b`: helper thread exits after quiesce (application keeps looping) | 10 | `ncclRemoteError` 10/10 | 4000.3 ms | 43–80 more flushes, each failing in ≤ 12.2 µs (QP poisoned) | 1999.8 ms | 10/10, 2013 ms | 737 ms | 0/10 |
| `tmo_t`: flush timeout 0.5 s, recovery stalled 3 s (round limit 2 s) | 10 | `ncclTimeout` 10/10 | **469.0 ms** [469.0–472.7] (≤ the app's 0.5 s) | – | none: the application aborted after its timeout (about 0.8 s after the fault), and the teardown stopped the round before the 2 s round limit | 0/10 (the app's own timeout, not an error) | 824 ms | 0/10 |
| `slow_b`: helper stalls 3 s (quiesce or commit), default limits | 10 | **transparent 10/10** | the slow iteration 3.02 s | – | none (0/10) | 0/10 | 717 ms | 0/10 |

- **Where the 4.0 s flush error comes from.** In all three stall/die cells it comes from the device
  hold expiring (4 s), not from the watchdog.
  - The stall came before the helper's re-post commit point: after quiesce in `stallq_b`; after
    Prepare/Commit but before the commit point in `stallc_b`; after quiesce in `die_b`.
  - So the device's give-up **won**, and the waiter failed at exactly 1 × hold.
  - The watchdog (round limit 2 s) only raised the async error, 2.0 s after the stall began. It does
    not end any device wait.
  - The 8 s stall is cut short at teardown, and the helper then declines.
- **None of these cells exercises the 2 × hold path** (a give-up that loses because the host
  already passed its commit point). The third review asked for it; it is measured separately in
  "Third review" (`late_ok_b`, `late_fail_b`).
- The device-side bound (hold) and the host-side watchdog are independent. In `die_b` no helper
  thread exists any more, yet the flush fails at the hold bound and the error still surfaces
  through the watcher.
- `slow_b` is the regression test for the reviewer's major finding in the follow-up code (a false
  watchdog at the end of any round longer than 1 s).

### Point 2: the exactly-once boundary was never observed — correct, test built

The n = 1 case occurred 0/30 times in phase 1: the responder executed the WRITE but not the ADD. It
is now forced with `NCCL_GIN_TS_TEST_SPLIT=k` (rank 0, research build):
1. The k-th put+signal is split: the device posts the WRITE alone and waits for its CQE, so the
   responder has executed it.
2. A host test thread then fires the local fault, under `opMu`, and acknowledges.
3. Only then does the device post the ADD, into the ERR QP, so it is flushed.

k was spread over 25..98 (30 distinct values), with the unmodified application otherwise.

| n | transparent | split fired, fault acknowledged | S = 2k, U = 2k−1, n = 1 (only the ADD re-posted) | `next_rcv_psn` agrees | final signal exact | bad slots (GPU/host) | async errors r0/r1 |
|---|---|---|---|---|---|---|---|
| 30 | **30/30** | 30/30 | **30/30** | 30/30 | 30/30 | 0/0 | 0/0 |

So all three cases of the executed-prefix rule have now been run: n = 0, 1 and 2.

### Point 3: the `opMu` fix and the production form of the race — correct, analysed and fixed

- **Rate on the final build.** The in-flight F1 cell (`f1g0_b`: 4 KiB back to back, fault inside
  an op) was run in three holds (H1, H3, H4; 50 runs each):

  | n | transparent | failures | 95% upper bound, one-sided (Clopper–Pearson) | 95% CI, two-sided | re-posted n = 0 / 1 / 2 | `next_rcv_psn` agrees |
  |---|---|---|---|---|---|---|
  | 150 | **150/150** | 0 | **1.98%** | 0–2.43% | 73 / 0 / 77 | 150/150 |

  Fault after launch: 49 ms [20–74]. Fault → resumed: 11.5 ms [11.1–12.0].
  - Before the fix: 1/30, whose two-sided 95% CI is 0.08%–17%.
  - If the fixed build still failed at the pre-fix point estimate (3.3%), 0/150 would have
    probability 0.6%. Rates below about 2% are not excluded.
  - That is a bound on the fixed build, not a proof of the cause (see TL;DR).
- **Production form: helper round against communicator teardown.** Reading the code found two
  real problems. Both are fixed.
  1. **The helper outlived the communicator [source].**
     - In NCCL 2.32, `ncclCommDestroy`/`ncclCommAbort` never destroy the GIN contexts of a
       devComm the application did not destroy with `ncclDevCommDestroy`. `ncclGinHostFinalize`
       only joins the proxy threads and closes the collComms.
     - So the helper, the Q4 watcher and the fault hook kept running after the teardown. They
       used the freed collComm (`nranks`), the freed communicator (`ncclGinRecoverAbort`) and the
       async-result slot in the freed `sharedRes`.
     - This is a use-after-free, and a source of QP state changes during teardown.
     - Fix: `ncclGinGdakiTsCommTeardown(comm)`, called from `ncclCommAbort` and from
       `ncclGinHostFinalize`. For every transparent context of the communicator it:
       - stops the watcher, then joins the helper (a round in progress declines at its next
         bounded wait), the test thread and the hook;
       - poisons every gate;
       - removes the context from the registry.
     - The contexts themselves stay until `ncclDevCommDestroy`, as in stock NCCL.
  2. **`ncclCommAbort` hung with a kernel held mid-round [measured, 1 run; cause inferred].**
     - NCCL's abort flag does not reach GIN waits of a user devComm. The held kernel therefore kept
       waiting (hold 30 s).
     - The teardown blocked, inferred to be a device synchronization. In the first smoke of fix 1
       it did not return within the driver's 15 s alarm (`v2_smoke2_pre_abort_hook/`).
     - Fix: the teardown runs from `ncclCommAbort` right after the abort flags are set, before
       anything is freed. The poisoned gates release the held kernel at once.

  Test `abortmid_b` (10 runs): the helper stalls 8 s in a round, the hold is 30 s, and the
  application aborts about 0.6 s after the async error. That is `ncclCommAbort` without
  `ncclDevCommDestroy`, while the kernel is held and the round is in progress.

  | n | abort returned | abort time | teardown found a round in progress | helper, watcher and hook joined in | gates poisoned | kernel still running when abort returned |
  |---|---|---|---|---|---|---|
  | 10 | 10/10 | 730 ms [588–1010] | 10/10 | 2.9 ms [2.1–3.6] | 4/4 per run | 0/10 |

  Every other follow-up cell also ends in `ncclCommAbort`: the teardown line appears in each, with
  a round in progress in every stall/die/timeout run. Flag off prints nothing (`off_f1_b`,
  unchanged path).
- **What remains [source]:**
  - An abort that arrives while the helper is inside a firmware command waits for that command.
  - A concurrent `ncclDevCommDestroy` of the same communicator from another thread is API misuse,
    as for the rest of NCCL.
  - Pre-existing in layer 2 (Q4 on, transparent off), not changed because the flag-off path must
    stay identical: the Q4 watcher of such a context also outlives the communicator.

### Point 4: the attribution rows overlapped — correct

- The three phase-1 variants each removed one mechanism alone:
  - GPU-scope fences (both fences);
  - no gate (the gate *and its fence*);
  - no poll counting (the counter *and its fence*).
- The fences were therefore counted twice, and 3.3 + 2.6 + 4.7 = 10.6 µs exceeded the 6.7 µs total.
- The follow-up measures cumulative removal on the final build: 5 interleaved runs × 2900
  iterations per cell, `v2_lat/`, unsafe variants compiled into the driver only.

| 4 KiB | p50 µs | step | cumulative |
|---|---|---|---|
| flag on | 16.42 | – | – |
| − system-scope fences (→ GPU scope) | 13.47 | 2.94 | 2.94 |
| − the poster gate | 11.58 | 1.89 | 4.83 |
| − the poll-region counting | 10.37 | 1.22 | 6.05 |
| flag off | 10.24 | 0.13 | 6.18 |
| gpudb v2 build | 10.21 | 0.03 | 6.21 |

| 256 KiB | p50 µs | step | cumulative |
|---|---|---|---|
| flag on | 41.34 | – | – |
| − system-scope fences | 40.48 | 0.86 | 0.86 |
| − the poster gate | 39.46 | 1.02 | 1.89 |
| − the poll-region counting | 38.59 | 0.86 | 2.75 |
| flag off | 38.43 | 0.16 | 2.91 |
| gpudb v2 build (4 runs; 1 lost to a driver port collision) | 38.27 | 0.16 | 3.07 |

- The steps add up by construction.
- A cumulative split depends on the order of removal. In this order the fences are the largest
  part at 4 KiB (48%), and the three mechanisms are similar at 256 KiB.
- The flag-on p50 of the final build (16.42 µs) is lower than phase 1's (16.96 µs). The build
  changed: the gate now also loads `status`, and `flushAsync` makes one attempt instead of parking.
  Only the final build's numbers are used here.

### Regression on the final build

Every phase-1 cell was re-run on the final build (`v2_confirm/`, 2–3 runs each). The outcomes are
the same as in phase 1:
- none, F1 blocking and with timeout, F3 blocking and with timeout: transparent (3/3 each);
- F1 ×5: 3/3, 15 rounds;
- F2 and F4: declined (3/3), with the same reasons;
- both negative controls failed as predicted (2/2);
- flag off and the gpudb build: `ncclRemoteError` at the fault (2/2 each), with no teardown line.

The phase-1 limit about F2 is unchanged: rank 1's `ncclCommAbort` still does not return (exit 7).
That rank's kernel spins on the application's own `waitSignal`, which no GIN mechanism can release.
The teardown hook runs there, but it has nothing to release.

### Point 5: the leaked firmware command slot — correct

- "All later runs were unaffected" was not supported, and it is withdrawn.
- Stated as a condition instead: from 06:45:02, one command slot of rain `mlx5_1` is leaked. Every
  later hold ran with it: hold G, and every follow-up run.
- What was measured [measured; `scripts/ts1/fwcmd_delta.py results/20260925_ts1/v2_fwcmd`, read-only
  debugfs and dmesg snapshots taken inside each hold, before and after]:
  - the rain-side Commit (4 contexts × 2RST/INIT/RTR/RTS) has a median of 3.37 ms before the leak
    (holds A–E, 115 rounds), 3.34 ms in hold G (55 rounds), and 3.37 ms in the follow-up (90
    rounds);
  - no new command failure (`failed`, `failed_mbox_status`) in any follow-up hold;
  - per-hold mean command latencies are steady across the six follow-up holds: `2ERR_QP` 118–152 µs,
    `RST2INIT` 146 µs, `INIT2RTR` 156–158 µs, `RTR2RTS` 83 µs, `QUERY_QP` 51–52 µs. `2RST_QP`
    varies from 198 to 367 µs with the mix of cells;
  - no new mlx5 kernel message after 06:45:02.
- This shows no measurable effect at the concurrency these tests reach, a few commands in flight.
  It does not show that the device behaves normally when all command slots are needed.

## Third review (re-check of the follow-up)

The external reviewer re-checked the follow-up and raised four points. All were correct.

The results come from the third-review build: libnccl md5 `f19cbcfe`, driver md5 `b67f9b36`. Runs
were made in holds `ts1b-smoke3`, `ts1b-H5` and `ts1b-H6`, and are in `results/20260925_ts1/v3_*`.
Tables come from `scripts/ts1/followup3_summary.py`; see also `summary_v3.md`.

The independent reviewer read the code changes (`fix_v2final_to_v3`) and found nothing at major or
minor level. Its one optional nit is listed under Limits and Next step.

### 1. Two explanations disagreed with the logs — corrected

- **(a) Where the 4.0 s flush error comes from.**
  - The follow-up text said the watchdog's decline "wins" in the stall cells. It does not.
  - In `stallq_b`, `stallc_b` and `die_b` the stall came before the commit point. The device's
    give-up won, so the waiter failed at 1 × hold. The watchdog only raised the async error, 2 s
    after the stall began. The text is fixed.
  - The 2 × hold path (a give-up that loses) was measured by no cell. It is now measured by two
    cells.
  - New stall stage `NCCL_GIN_TS_TEST_STALL=<ms>@replay` stalls the helper *after* its commit point
    and before any re-post. Settings: hold 4 s, round limit 25 s, handshake 10 s (so the responder's
    DONE wait outlasts the stall).

  | cell | n | transparent | first flush result | latency | helper | async error |
  |---|---|---|---|---|---|---|
  | `late_ok_b`: stall 6 s after the commit point | 10 | **10/10** | ok | slow iteration **6012 ms** [6012–6013] (the give-up lost at 4 s, the waiter kept waiting, the publication came at 6 s) | recovered, re-posted the 2 WQEs | none |
  | `late_fail_b`: stall 12 s after the commit point | 10 | 0/10 | `ncclRemoteError` 10/10 | **8000.3 ms** [8000.2–8000.4] = 2 × hold | declined *before re-posting* (10/10: "a device thread failed the QP after the commit point"), nothing re-posted | 10/10, 12.03 s after the fault (when the stalled helper resumed) |

  - Two host changes make `late_fail_b` end this way:
    - the helper checks every gate's `status` right before it re-posts;
    - the idle scan also declines on a gate that a device thread poisoned.
  - Before these changes, a device failure after a lost give-up was invisible to
    `ncclCommGetAsyncError`: `abandoned` equals the new stable epoch after the publication, so the
    scan did not flag it. The host would also have re-posted an operation the application had
    already been told had failed.
  - A residual race remains between the pre-re-post check and the publication (Limits).
  - Rank 1's decline reads "DONE timeout" in `late_fail_b`. That is its DONE wait being interrupted
    by its own teardown: its receiver had timed out on the missing iterations. The receive helper
    reports that like a timeout; it is cosmetic.
- **(b) The timeout cell.** The row said the watchdog did not fire "because 3 s < round limit". That
  was wrong: the round limit in `tmo_t` was 2 s. The application got `ncclTimeout` at 469 ms and
  aborted about 0.8 s after the fault. The teardown then stopped the round before its 2 s limit.
  The row is fixed.

### 2. The bound of a blocking flush — stated

A blocking `flush()`/`wait()` is bounded only by the library's hold:
- 30 s by default;
- 60 s when the device's give-up loses to a host past its commit point, measured above as
  2 × hold;
- set only through `NCCL_GIN_TS_HOLD_MS`, never by the application's call.

Only a flush or wait with a timeout ends at the application's own bound. The TL;DR, "Bounds and
giving up" and Limits now say this, and "every wait is bounded" was removed.

### 3. Use-after-free between the teardown and `ncclCommGetAsyncError` — correct, fixed

- **The race.** `ncclGinGdakiQueryLastError` reads the helper state (`rec->ts`) without a lock. It
  is reached from `ncclCommGetAsyncError` on any thread, including while `ncclCommAbort` runs. The
  follow-up teardown deleted that state.
- **The fix.** The teardown now frees nothing.
  - It joins the threads, closes the sockets, poisons the gates and unregisters the context.
  - The helper state stays, with `active` still set, so a late query takes the transparent branch.
    That branch reads only this state and the Q4 host flag. The Q4 host is stopped at teardown but
    freed only with the context.
  - The split-test block, which a running kernel may read, stays as well.
  - Both are freed with the context, in `ncclDevCommDestroy`. That runs only after
    `ncclGinDevCommFree` has unlinked the devComm under the devComm write lock, which excludes
    `ncclGinQueryLastError`.
  - If the application never destroys the devComm, they leak, as stock NCCL leaks the context.
- **The test.** Each run was `abortmid_b` plus a monitor thread calling `ncclCommGetAsyncError` in a
  tight loop (`GIN_ASYNC_POLL_US=0`). The monitor was **not stopped before `ncclCommAbort`**:
  - it kept running 200 ms into the abort (`abortmon_b`);
  - or until `ncclCommAbort` returned (`abortmonfull_b`).

  Rank 0 aborts while its helper is mid-round and the kernel is held. The library counts the queries
  that overlapped its teardown.

  | cell | n | abort returned | abort time | teardown found a round in progress | GIN teardown time | error queries inside the GIN teardown | monitor calls during the abort | failed calls / crashes | kernel running when abort returned |
  |---|---|---|---|---|---|---|---|---|---|
  | `abortmon_b` | 10 | 10/10 | 715 ms [589–995] | 10/10 | 3.3 ms [2.3–50.5] | 1600 [1066–18138] | 95 331 | 0 / 0 | 0/10 |
  | `abortmonfull_b` | 10 | 10/10 | 728 ms [580–1002] | 10/10 | 4.8 ms [2.6–45.4] | 2322 [1265–16339] | 495 473 | 0 / 0 | 0/10 |

  The GIN teardown starts about 3 µs after `ncclCommAbort` is entered.
- **What this does not show.**
  - The test shows the window was exercised thousands of times per run without a crash. It cannot
    show the absence of a use-after-free by itself: reading freed heap memory rarely crashes, and
    the follow-up code's window was a few microseconds.
  - The fix is by construction: nothing is freed in that window.
- **Stock NCCL [source].** Stock `commFree` deletes `sharedRes` and frees the communicator inside
  `ncclCommAbort`, and a concurrent `ncclCommGetAsyncError` reads both.
  - `abortmonfull_b` ran through those frees 10 times without a crash, but that is not a guarantee
    in any build.
  - An application must stop calling `ncclCommGetAsyncError` on a communicator before
    `ncclCommAbort` can free it.

### 4. "Not packed yet" — fixed

The Files section now says that every result directory is stored as `<dir>.tar.xz`, and that they
must be unpacked before the scripts are re-run.

### Regression on the third-review build (`v3_confirm/`, `v3_lat/`)

Every cell was run 1–2 times, and the in-flight cell 10 times. The outcomes match the follow-up:
- none, F1 blocking and with timeout, F3, F1 ×5, the split test and the 3 s slow round: all
  transparent;
- in-flight F1: 10/10;
- F2 and F4: declined;
- stallq, die and abortmid: errors within their bounds;
- tmo: `ncclTimeout`;
- both negative controls failed as predicted;
- flag off and the gpudb build: `ncclRemoteError`, with no teardown line.

Latency p50 (3 runs each) is unchanged, as expected: the third-review changes are host-only.

| size | off | on |
|---|---|---|
| 4 KiB | 10.24 µs | 16.42 µs |
| 256 KiB | 38.50 µs | 41.31 µs |

Firmware-command counters show 0 new failures in these holds, and there is no new mlx5 kernel
message. One command slot is still leaked (point 5 of the follow-up).

## What the application does, and what it sees

`gin_ts1.cu` is the kind of program a GIN user writes. Nothing in it knows about faults:

- Rank 0 launches **one** kernel for the whole loop: `for i: put(slot i, 256 KiB) + signal ADD 1;
  flush; 15 ms gap`. It stores every flush's return code.
- Rank 1 launches **one** kernel: `for i: waitSignal(base+i+1); check slot i bit-exact on the GPU`.
  At the end its host copies every slot back, checks each one again, and reads the final signal,
  which must be exactly `base + iters`.
- Both hosts poll `ncclCommGetAsyncError` every 200 µs for the whole run (about 9 000 to 121 000
  samples per run).

A run counts as **transparent** only if all of the following hold:
- every flush returned `ncclSuccess` and all iterations ran;
- every slot is bit-exact, both on the GPU when its signal arrived and on the host at the end;
- the final signal is exact;
- neither host ever saw an async error.

It has no relaunch, fault query, handshake or checkpoint, so a fault that is not hidden inside
NCCL shows up as an error code, a hang, or a data or signal mismatch.

Faults are injected by NCCL's existing test hook (`gin_fault_inject.diff`), or by the runner
(SIGKILL), or by the application's own bug (F2):
- **F1:** rank 0's QPs are forced to ERR mid-loop (LOCAL_QP_ERR 5/0xf5).
- **F3:** rank 1's QPs are forced to ERR. Rank 0 then gets RETRY_EXC 12/0x81 after about 3.6 s.
- **F2:** iteration 10 puts to an offset outside the window (REM_ACCESS 10/0x88).
- **F4:** SIGKILL of rank 1 (RETRY_EXC with the peer dead).
- **F1 ×5:** five local faults in one run. The third fires inside the previous recovery's commit,
  so it hits the re-posted WQEs.

## How it works

### Device (`gin_gdaki.h`, `gin_gdaki_device_host_common.h`)

The gate lives in padding the DOCA device QP struct already has, so no struct changes size:
- `struct ncclGinTsGate` (64 B) in `reserved2`;
- `struct ncclGinTsGate2` (8 B) in `reserved1`.

DOCA allocates the host shadow with `calloc` and copies it to the device array, so every gate is
zero (off) unless the host enables it [source]. DOCA's device code never touches either field
[source].

| word | written by | read by | meaning |
|---|---|---|---|
| `flags` | host, once at init | every post/flush/wait (plain load) | `ON`; the `NOREBASE` negative control |
| `pause` | host | posters | 1 while a recovery owns the QP |
| `epoch` | host | waiters, posters inside the gate | even = stable, odd = recovery in progress |
| `status` | host | waiters | 1 = declined (terminal) |
| `lbase` | host (while the epoch is odd) | waiters inside the counted region | logical index of physical WQE 0 of the current epoch |
| `commit` | host | waiters that give up | the epoch the host is about to publish (commit point) |
| `active` | posters (atomics) | host | posters inside the post critical section |
| `pollers` | waiters (atomics) | host | waiters inside the counted poll region |
| `abandoned` | waiters (atomicMax) | host | the highest epoch a waiter stopped waiting for |
| `nonmsg` | posters | host | a NOP/DUMP/READ was posted this epoch (S1 cannot count or re-post it) |
| `reported` | waiters | waiters, host scan | dedupes fault records per epoch |

- **Pause gate (posters).** Every post goes through `tsGateEnter`/`tsGateLeave`: `put`, `signal`,
  `putValue`, `get`, and the MCST DUMP of `flushAsync`.
  - Enter: `atomicAdd(active, 1)`; `__threadfence_system()` (fence.sc.sys); `ld.acquire.sys pause`.
    If `pause` is set, the poster backs out (`red.release.sys` −1) and parks until pause is 0.
  - Leave: `red.release.sys` −1 on `active`.
  - Host: one copy writes `{pause = 1, epoch = odd}`, the stream is synchronised, then a copy reads
    `active`.
  - Why this is enough (Dekker): the fence orders the poster's increment before its load of
    pause. So either the host reads `active > 0` and waits, or the poster reads `pause = 1` and
    backs out. A parked poster holds no WQE slot, and when `active == 0` the reserved, ready and
    submitted indices are equal, which Prepare checks again.
  - Both sides meet at the GPU's L2, the coherence point for device memory:
    - the SM performs its atomics there, and its `.sys` loads bypass L1 and are served there;
    - the copy engine writes into and reads from device memory through it.
  - The copy engine is not a PTX thread, so this rests on hardware behaviour, not on the formal
    model [inferred]. It was exercised only with one posting thread (see Limits).
- **Counted poll region (waiters).** A waiter polls the CQ, and may advance `cq_sq.cqe_ci`, only
  inside a region counted in `pollers`. It enters the same way (add, fence.sc.sys, epoch
  unchanged and even) and parks outside the region while the epoch is odd.
  - Host order: make the epoch odd, move the QPs to ERR, wait for `active == 0 && pollers == 0`,
    and only then rewrite `cqe_ci`, `cqe_rsvd`, the indices or `lbase`.
  - Without this, a waiter that read the old CQ mapping could `atomicMax` an old-epoch `cqe_ci`
    over the reset value. Every new-epoch poll at or below that value would then return "done"
    (found in review).
- **Logical tickets.** A waiter holds a logical WQE index: `lbase + physical index` at the time
  the ticket was taken, read inside the region.
  - A recovery publishes `lbase_new = lbase_old + U`, where `[0, U)` of the ending epoch were
    executed by the responder and `[U, S)` are re-posted at physical `[0, S−U)`.
  - The logical index of an operation never changes, so on every (re)entry the waiter maps it:
    `logical < lbase` means done (executed before a recovery); otherwise
    `physical = logical − lbase`.
  - `flushAsync` stores the logical count in the request (the 8-byte index field). The epoch
    field sits in the struct's alignment padding and only marks an invalid ticket.
  - This replaces the design's "ticket rebase table" (§6.3). The probe had shown that after
    `2RST` the NIC restarts its WQE counter at 0 and that the CQE's `wqe_counter` comes from that
    counter, not from the ctrl index field (`transparent_probe/results/run2/wqeidx`: override 1000
    → counters 0..3), so logical indices cannot be kept on the wire.
- **Wait across a recovery (`tsPoll`).** On an error CQE the waiter:
  1. publishes the existing Q4 mailbox record (once per epoch, with the root-cause scan, but
     without setting Q4's sticky context error);
  2. leaves the region and parks until a new stable epoch appears;
  3. re-enters and re-maps its ticket.

  The flush, blocking or with a timeout, therefore returns `ncclSuccess` once the re-posted WQE
  completes. The same code serves the blocking and timeout flush and wait paths.
- **Bounds and giving up** (rewritten in the follow-up; the phase-1 version had the gaps the external
  review listed, see "Follow-up"). Every device-side wait that can park across a recovery now has a
  bound, and each bound ends in a defined result. For a blocking call that bound is the library's
  hold, not anything the application sets:
  - **The caller's own timeout covers parked time.** `flush`/`wait` with a timeout carry one deadline
    (`clock64` start + the caller's cycles, as the stock timeout paths) through ticket-taking, parking
    and polling. When it expires the call returns `ncclTimeout` wherever it is, parked or polling. It
    does not abandon the operation: as with a stock timeout, the operation may still complete later
    (after the recovery).
  - **`flushAsync` does not block.** It makes one attempt at the counted region. If a recovery is in
    progress it returns a PENDING request (a marker in the request's epoch field); if the QP has
    failed, a BAD one. The matching wait takes the ticket itself, under its own deadline. (Phase 1
    parked inside `flushAsync`, for up to about 2 × hold.)
    - One exception: after a `get`, `flushAsync` posts an MCST DUMP, and that post goes through the
      poster gate, so it can park for up to 2 × hold.
    - A round in an epoch with a `get` declines anyway (READ is `nonmsg`), so this only delays the
      error.
  - **Library bound for callers without a timeout, and for posters.** A parked waiter *and* a parked
    poster (`tsGateEnter`) give up after `NCCL_GIN_TS_HOLD_MS` (30 s) with no new epoch. (Phase 1
    posters had no bound.) Giving up goes through a commit point with the host (Dekker again):
    - device: `atomicMax(abandoned, next)`; fence.sc.sys; read `commit`;
    - host, before anything is re-posted: write `commit = next`, then read `abandoned`.

    Either the host sees the give-up and declines, so nothing is re-posted, or the device thread sees
    the commit and waits one more bound for the publication. After that it fails regardless.
    - So a blocking call is bounded by 1 × hold when the give-up wins and 2 × hold when it loses
      (30 s / 60 s by default). The application cannot shorten it except through the environment.
    - Third review: a device thread that fails after its second bound poisons the QP. The host now
      checks every gate's `status` right before it re-posts, and declines instead of re-posting an
      operation the application was already told had failed.
    - A failure that lands after that check (a window of microseconds against a 30 s bound) is still
      surfaced, by the idle scan, which now also declines on a poisoned gate. The re-post may then
      have executed; the operation's outcome is unknown, as after a stock timeout.
  - **Failing poisons the QP.** A won give-up writes `status = 1` and Q4's sticky error. Every later
    wait on that QP returns `ncclRemoteError` at once, instead of each waiting out its own bound.
    - Every later post checks `status` in the gate and is dropped, as is the post of a poster that
      gave up. The next flush/wait on that QP reports the failure. A poisoned QP can still be
      healthy on the NIC, so without the check it would keep executing posts whose waits all fail;
      the check was added after the follow-up review.
    - The host's periodic scan sees `abandoned` and declines, so `ncclCommGetAsyncError` reports it
      too.
  - A declined QP (`status`) returns `ncclRemoteError` and raises Q4's sticky error, so the blocking
    `flush()`/`wait()` API reports it as in Q4.

### Host (`gin_host_gdaki.cc`): a helper thread inside NCCL

There is one helper thread per GDAKI context of a user devComm, not the application. The Q4
watcher hands it every device-classified error record that belongs to a gated QP. In transparent
mode the watcher does not raise the async error for a record it hands over, and
`ncclGinGdakiQueryLastError` reports only declined faults, so a QP that is in ERR while it is being
recovered is never reported [source; measured: 0 async errors in the recovered runs].

- **Watchdog (follow-up).** Because the watcher hands the error over instead of raising it, a helper
  that stalls or dies would make the error disappear. The watcher (a separate thread) therefore
  checks the helper on every poll:
  - a round that has been running longer than `NCCL_GIN_TS_ROUND_MS` (25 s by default; a normal
    round takes 10 ms);
  - or fault records queued while the helper's heartbeat is older than 1 s (the helper is dead or
    stuck outside a round).

  Either one surfaces the error: the Q4 host error flag, and `ncclRemoteError` as the communicator's
  GIN async result, so `ncclCommGetAsyncError` reports it. A WARN names the reason. From then on the
  helper declines instead of continuing: it checks before the commit point, and at the start of each
  initiator or responder round. The device side has its own bound (above), so the kernel is released
  even when no host thread acts.
  - The heartbeat is refreshed when a round ends, before the round is marked finished.
    - The first version refreshed it only at the top of the helper loop. The end of any round longer
      than 1 s, with stale records queued, then looked like a dead helper. Stale records are the
      normal case: the round's own quiesce produces flush errors.
    - This produced a false `ncclRemoteError`. The follow-up review found it before any
      measurement; the `slow_b` cell below tests it.
  - If the watchdog fires after the helper passed the re-post commit point (a round longer than
    `ROUND_MS` that then completes), the round still publishes. The application then has an async
    error while its data is intact. That is fail-safe, but it is a false positive in that case.
- **Communicator teardown (follow-up, third review).** `ncclGinGdakiTsCommTeardown` runs from
  `ncclCommAbort` as soon as the abort flags are set, and from `ncclGinHostFinalize` for
  `ncclCommDestroy`.
  - It stops the watcher, joins the helper, the test thread and the hook, poisons every gate and
    unregisters the context.
  - It frees nothing: the helper state and the test block live until `ncclDevCommDestroy`.
  - See "Follow-up", point 3, and "Third review", point 3, for the races and the measurements.

- **Channel: a library-owned TCP socket per (GDAKI context, peer).**
  - It is opened at context creation on the `NCCL_SOCKET_IFNAME` interface (the management
    network here, `eno1`). Its address is exchanged with one all-gather over the GIN collComm that
    context creation already uses. The lower rank connects and the higher rank accepts, bounded by
    `NCCL_GIN_TS_CONNECT_MS`.
  - Options: TCP_NODELAY, keepalive (2 s idle, 3 × 1 s) and `TCP_USER_TIMEOUT` 5 s. Every call is
    non-blocking.
  - **Why not bootstrap point-to-point:** `bootstrapRecv` has no per-call deadline and shares
    NCCL's own bootstrap traffic. Also, the bootstrap connects per message, so it gives no
    liveness signal.
  - A persistent connection gives FIN or RST when the process dies, and a keepalive or user
    timeout when the host dies. It also does not share the RoCE link that faulted.
  - The channel carries fixed 2 KB records: HELLO, REQ, ACK, NACK, DONE, FAIL.
- **Policy** (moved from the application driver into the library, unchanged):
  - LOCAL_QP_ERR: recover.
  - RETRY_EXC: recover if the socket shows no FIN/RST (`recv(MSG_PEEK|MSG_DONTWAIT)`); if the peer
    is dead, decline without a handshake.
  - Anything else: decline, and send FAIL.
- **Initiator round** (the rank whose device reported):
  1. Quiesce: `{pause = 1, epoch = odd}` on every QP to the peer; move them to ERR; wait
     (≤ `NCCL_GIN_TS_QUIESCE_MS`) for `active == 0 && pollers == 0`; check `abandoned`.
  2. `ncclGinRecoverPrepare`: the existing gin_recovery v1+v2 code, unchanged. It runs the
     quiescence check against the GPU indices and the doorbell record, moves the QPs to ERR,
     drains the CQE of the last WQE, and draws a fresh 24-bit PSN.
  3. Decline if any gate's `nonmsg` is set.
  4. `QUERY_QP` (DEVX, new `doca_verbs_qp_query_seq`) of this rank's QPs: `rmsn` minus the
     baseline = the number of the **peer's** request messages this QP executed.
  5. Send REQ {token, executed counts}. Wait for ACK, bounded by handshake + quiesce + drain. A
     simultaneous REQ from the peer is answered with NACK and both sides decline (S1 has one
     initiator per pair).
  6. `ncclGinRecoverCommit` with the peer's token: `2RST`, doorbell record 0, device struct,
     `cqe_rsvd += S`, get tickets, INIT/RTR/RTS with the exchanged PSNs. It is the existing code,
     with three helper-path-only changes:
     - it writes only the fields it owns (`[0, reserved1)` and `cq_sq`), never the gate;
     - it zeroes with copies from pinned memory instead of `cudaMemsetAsync` (a memset may need a
       kernel slot that the application's persistent kernel holds);
     - it does not clear the Q4 error state (a declined peer's error must stay surfaced).
  7. Take the new `rmsn` baseline (no traffic can flow yet).
  8. Re-post and resume (`gdakiTsReplayResume`):
     - Commit point: `commit = stable+2` on every QP, then check `abandoned`.
     - Per QP: `in-flight = (S − executed) mod 2^24` must be ≤ S and ≤ the ring size. Copy WQEs
       `[U, S)` from the old ring slots to physical `[0, n)`, rewriting the ctrl-segment WQE index
       (only RDMA_WRITE and ATOMIC_FA may be re-posted).
     - Set `sq_rsvd = sq_ready = sq_wqe_pi = n` and `lbase += U`.
     - Write the doorbell record (in GPU memory, `htobe32(n)`), then ring the UAR from the host
       (the UAR is mapped on the host as well, which is where DOCA's CPU proxy rings it). With GPU
       doorbells no GPU thread would ring for these WQEs.
     - Clear `nonmsg`, then publish `{pause = 0, epoch = stable+2}`.
  9. Send DONE.
- **Responder round** (on REQ):
  - quiesce, Prepare, then report the executed counts of its own QPs;
  - Commit with the initiator's token; take the baseline; send ACK;
  - wait for DONE (≤ 2× handshake), so its own posters and any re-post only start after the
    initiator reached RTR;
  - re-post and resume with the initiator's counts.
- **Which WQEs executed.** For S1, "minimal correct rule" means the responder's message sequence
  number, from the same `QUERY_QP` that the probe used for `next_rcv_psn`.
  - Every WQE of the epoch is exactly one request message (the device declines otherwise through
    `nonmsg`), and RC executes in order. So the executed prefix is the first `rmsn − rmsn0` WQEs,
    and `rmsn0` is taken at connect and after every commit.
  - This avoids per-WQE PSN accounting, which would need every WQE's byte count since the start
    of the epoch, and the ring has overwritten most of them.
  - The probe had validated `rmsn` against memory together with `next_rcv_psn` (`Q1_MATCH`, 10/10,
    `rmsn = prefix`).
  - Here every recovery also logs the responder's `next_rcv_psn`, which lets the two authorities
    be cross-checked (below).
  - The signal ADD is re-posted only if the responder did not execute it, so it is applied
    exactly once.
- **Decline:**
  - QPs to ERR; `status = 1`; `epoch` moved past any held epoch; `pause = 0`.
  - The Q4 sticky error, the host flag and the GIN async result are set, so waiters return
    `ncclRemoteError` and `ncclCommGetAsyncError` reports it.
  - FAIL is sent to the peer, whose helper declines too.
- **Lost records.** Every 100 ms while idle, the helper reads each gate.
  - Case 1: a waiter gave up with no round running (`abandoned`).
  - Case 2: a fault record never arrived; `reported` has been ahead of the records taken for two
    scans, e.g. because the 16-slot mailbox overflowed.

  Both cases would otherwise leave the host unaware, so the helper declines, which surfaces the
  error.

## Stack

| layer | file | what S1 uses from it |
|---|---|---|
| 1 | `../gin/gin_fault_inject.diff` | the F1/F3 hook (`NCCL_GIN_FAULT_INJECT`), multi-shot with recovery |
| 2 | `../gin_q4/gin_q4_classify.diff` | device root-cause classification, host mailbox + watcher |
| 3 | `gin_recovery.diff` | Prepare / Commit / Abort, reconnect with fresh PSNs, resync inventory |
| 4 | `gin_recovery_gpudb.diff` | GPU_SM_DB doorbell mode in Prepare/Commit |
| 5 | S1 (in `gin_transparent_s1.diff`) | gate, logical tickets, hold-and-rebase waits, helper thread, socket, re-post + host doorbell, `doca_verbs_qp_query_seq`; follow-up: bounded posters and `flushAsync`, deadline over parking, watchdog, teardown hooks in `init.cc` (`ncclCommAbort`) and `gin/gin_host.cc` (`ncclGinHostFinalize`), test knobs |

- **Checked on the scratch trees:**
  - `gin_transparent_s1.diff` applied to a pristine `git archive v2.32.3-1` reproduces the
    source tree exactly (re-checked on the final follow-up tree).
  - So do layers 1–4 followed by the S1 layer alone.
  - Layers 1–4 applied to pristine reproduce the gpudb v2 worktree (`gi/gin_recovery/nccl-src-gpudb`).
- **Build:**
  - The tree is `$SCR/agent_ts1/nccl-src`; the build is `$SCR/agent_ts1/build`, a copy of the
    gpudb build directory with its paths rewritten, then built incrementally.
  - `make src.build CUDA_HOME=/usr/local/cuda-12.8 NVCC_GENCODE="-gencode=arch=compute_75,code=sm_75 -gencode=arch=compute_86,code=sm_86"`.
  - The driver is built with `-Wall -Wextra -Werror` against this tree
    (`scripts/ts1/build_driver.sh`), and also against the untouched gpudb tree (`BASE=1`) for the
    equivalence baseline.
- **Bundle:** `~/gi-bundle/gin_ts1/` on rain and sunny (md5 and `ldd` checked by
  `scripts/ts1/deploy.sh`). `base/` holds the gpudb libnccl, copied read-only, with the driver
  compiled against it.
- **Size of the S1 layer** (after the third review; phase 1 in parentheses):
  - 8 files, +2056 / −16 lines including comments (6 files, +1554 / −14).
  - Device: 407 non-comment added lines in 2 headers (265).
  - Host: 1233 non-comment lines in `gin_host_gdaki.cc` (990).
  - Teardown hooks in `init.cc` and `gin/gin_host.cc`: 7.
  - DOCA extension (`doca_verbs_qp_query_seq`): 28 (unchanged).
  - About 100 of the follow-up lines are test-only knobs: the split, the stall and die knobs, and
    the test thread.

## Tests

Run through `../common/cluster_run.sh` in 7 measurement holds of 3.5–11 min each
(`scripts/ts1/matrix.sh`, `holdE.sh`, `holdF.sh`, `holdG.sh`).
- Rank 0 = rain (put initiator, Quadro RTX 5000, `mlx5_1`); rank 1 = sunny (A4000, `mlx5_0`).
- Every QP uses GPU-rung doorbells (`GPU_SM_DB`, logged per context).
- IB timeout 14.
- 256 KiB per op with a 15 ms gap unless stated.

Every table is regenerated from the raw per-trial logs by `scripts/ts1/rows.py` → `summarize.py`,
`lat_summary.py` and `psn_check.py` (`results/20260925_ts1/summary.md`).

Builds:
- Main matrix (`runs/`, `lat/`, `lat_attr/`): libnccl `203e364e`.
- The in-flight cell and a confirmation pass over every cell (`runs/f1g0_b_*`, `confirm/`,
  `confirm_lat/`): the final libnccl `59c283ff`, which adds the `opMu` serialization.
- Driver `gin_ts1` `0a686a08` throughout.
- gpudb baseline: libnccl `1ed8e0a1` + the same driver source (`14463ed0`).
- Follow-up (`v2_*`): libnccl `110440e7` (the follow-up build, with the bounds, the watchdog, the teardown
  hooks and the review fixes), driver `faa6ee2e` (adds `GIN_TS_ASYNC_GRACE_S`,
  `GIN_TS_POST_ABORT_WAIT_S`, continue-after-error mode), baseline driver `a999772c`. The phase-1
  tables above were not re-measured on this build, except as listed under "Follow-up" and the
  regression pass (`v2_confirm/`).
- Third review (`v3_*`): libnccl `f19cbcfe` (host-only changes: teardown frees nothing, check before
  re-posting, scan on a poisoned gate, stall stage `@replay`), driver `b67f9b36` (monitor through
  the abort, `GIN_TS_END_WAIT_S`). The regression pass (`v3_confirm/`, `v3_lat/`) re-ran every cell
  on it. The diff in `gin_transparent_s1.diff` is this build.

6 trials (listed in `summary.md`) failed before NCCL started because the driver's own rendezvous
port was taken (`bind: Address already in use`). They are excluded and re-run.

### Outcomes

| cell | fault, flush | n | transparent | flush rc ≠ ok | slots bad | final signal exact | async error r0/r1 | rounds (init/resp) | declined |
|---|---|---|---|---|---|---|---|---|---|
| none_b | none, blocking | 30 | **30/30** | 0 | 0 | 30/30 | 0/0 | 0/0 | 0 |
| f1_b | F1, blocking | 30 | **30/30** | 0 | 0 | 30/30 | 0/0 | 30/30 | 0 |
| f1_t | F1, timeout (8 s) | 10 | **10/10** | 0 | 0 | 10/10 | 0/0 | 10/10 | 0 |
| f3_b | F3, blocking | 10 | **10/10** | 0 | 0 | 10/10 | 0/0 | 10/10 | 0 |
| f3_t | F3, timeout | 5 | **5/5** | 0 | 0 | 5/5 | 0/0 | 5/5 | 0 |
| f1x5_b | F1 ×5, blocking (160 iterations) | 10 | **10/10** | 0 | 0 | 10/10 | 0/0 | 50/50 | 0 |
| f1g0_b (final build) | F1 inside an in-flight op, 4 KiB × 8000, no gap | 30 | **30/30** | 0 | 0 | 30/30 | 0/0 | 30/30 | 0 |
| f2_b | REM_ACCESS (app's bad offset at iteration 10) | 30 | 0/30, declined | 30 (`ncclRemoteError`) | 0 | – | 30/30 | 0/0 | 30/30 |
| f4_b | SIGKILL of rank 1 | 10 | 0/10, declined | 10 | – | – | 10/– | 0/0 | 10/10 |
| neg_norebase_t | F1, waiters keep the stale ticket | 5 | 0/5 (as predicted) | 5 (`ncclTimeout`) | 5 | 0/5 | 0/0 | 5/5 | 0 |
| neg_noring_t | F1, no host doorbell for the re-post | 5 | 0/5 (as predicted) | 5 (`ncclTimeout`) | 5 | 0/5 | 0/0 | 5/5 | 0 |
| off_f1_b | F1, S1 build, flag off | 5 | 0/5 (Q4 behaviour) | 5 (`ncclRemoteError`) | 5 | 0/5 | 5/0 | 0/0 | – |
| base_f1_b | F1, gpudb v2 build | 5 | 0/5 (Q4 behaviour) | 5 (`ncclRemoteError`) | 5 | 0/5 | 5/0 | 0/0 | – |

- **Confirmation pass on the final build** (`confirm/`, 1–3 each): the same outcome in every cell.
  none 2/2, F1 2/2 and 3/3, F3 3/3, F1 ×5 3/3 (15 rounds), F2 3/3 declined, F4 3/3 declined, both
  negative controls failing as predicted, flag-off 2/2 error.
- **Leftovers:** no process was left on either node in any trial except the pre-fix hung trial
  (follow-up: 0 in all 272 trials of `v2_split`, `v2_f1g0`, `v2_bounds` and `v2_confirm`).
- **Teardown:**
  - `ncclCommAbort` returned on rank 0 in every trial.
  - On rank 1 in F2 it did not return within 5 s (exit 7). That rank's own `waitSignal` kernel
    still waits for a signal that will never come, and a user devComm has no abort flag. This is
    the same finding as gin_recovery's "Decline is clean only because the driver releases its own
    blocking waiter"; this driver deliberately does not.
- **Where the fault landed:** 518–1141 ms after launch (256 KiB cells, loop ≈ 1.8 s) and 17–63 ms
  after launch (in-flight cell, loop ≈ 135 ms).
- **What was re-posted.** `S/U/n` of the faulted QP is: WQEs of the epoch / executed by the
  responder / re-posted. The other three GIN contexts' QPs were always 0/0/0.
  - Main-matrix rounds all had n = 2 (the fault landed in the gap before a put; its WRITE and ADD
    were flushed).
  - In F1 ×5, 10 rounds had `S = n = 2`: a fault fired inside the previous commit, hit the
    re-posted WQEs themselves, and they were re-posted again.
  - In the in-flight cell, n = 0 in 14 rounds and n = 2 in 16. n = 1 (WRITE executed, ADD not) did
    not occur.

### Time (ms, median [min–max] over rounds; rank-0 helper line, host CLOCK_MONOTONIC)

| cell | rounds | quiesce | Prepare | REQ→ACK | Commit | re-post + publish | helper total | mailbox → resumed | fault → resumed | the held flush (app) |
|---|---|---|---|---|---|---|---|---|---|---|
| F1 | 30 | 0.22 | 0.48 | 5.28 | 3.33 | 0.14 | **9.46** [9.21–9.71] | 10.12 | 17.2 [13.5–20.8] | 10.4 [9.9–11.0] |
| F1, timeout | 10 | 0.24 | 0.50 | 5.29 | 3.40 | 0.14 | 9.57 | 10.03 | 17.4 | 10.4 |
| F1 ×5 | 50 | 0.23 | 0.46 | 5.20 | 3.37 | 0.14 | 9.41 [8.91–10.64] | 10.12 | 16.4 (first) | 22.1 (two rounds back to back) |
| F1 in-flight | 30 | 0.47 [0.22–1.06] | 0.49 | 5.29 | 3.34 | 0.14 | 9.76 | 10.33 | **10.8** [10.6–11.1] | 10.6 |
| F3 | 10 | 1.11 | 0.49 | 4.18 | 3.38 | 0.14 | 9.27 | 9.51 | 3608 [3533–3773] | 3604 |
| F3, timeout | 5 | 1.14 | 0.48 | 4.27 | 3.38 | 0.14 | 9.40 | 9.85 | 3616 | 3612 |

How to read the table:
- **Fault → resumed:**
  - For F1 it includes up to one 15 ms gap: the fault usually lands while no op is in flight, and
    the next put finds it. The in-flight cell has no gap: 10.8 ms.
  - For F3 it is the RETRY_EXC detection (IB timeout 14), as in all earlier runs, plus 10 ms.
- **Quiesce:** moves the QPs to ERR. It is cheap where the hook had already done so; in F3 the
  initiator's three idle contexts must first be moved to ERR.
- **REQ→ACK** covers the responder's quiesce (0.06–0.3 ms), Prepare (0.5–1.5 ms), executed-count
  query and Commit (3.3 ms).
- **Commit:** four GIN contexts × (2RST + INIT/RTR/RTS) of firmware commands, the same cost as
  gin_recovery. Resetting only the faulted pair would halve it.
- **Detection to mailbox** is unchanged from Q4, since the classifier is the same.

### Declines (bounded, error surfaced)

| cell | n | rank 0 decision | rank 1 | flush rc | error visible on the host |
|---|---|---|---|---|---|
| F2 | 30 | "class REM_ACCESS is not recoverable", 1.49 ms after the mailbox record | "the peer declined" (FAIL) | `ncclRemoteError` at iteration 10 | both ranks, 154 ms after launch (iteration 10) |
| F4 | 10 | "RETRY_EXC and the peer's socket shows FIN/RST", 3.78 s [3.57–3.82] after the kill, 1.33 ms after the record | killed | `ncclRemoteError` | rank 0 |

### Fault-free latency (put + signal + flush of the unmodified loop, GPU %globaltimer, 15 runs × 2900 iterations per cell, interleaved)

| bytes | gpudb v2 build | S1 build, flag off | S1 build, flag on |
|---|---|---|---|
| 4 KiB p50 / p99 / mean (µs) | 10.14 / 10.34 / 9.99 | 10.24 / 11.42 / 10.24 | **16.96** / 18.46 / 17.16 |
| 256 KiB p50 / p99 / mean (µs) | 38.21 / 38.94 / 38.14 | 38.43 / 38.94 / 38.36 | **41.28** / 42.78 / 41.43 |
| per-run p50 range, 4 KiB | 10.08–10.18 | 10.24–10.24 | 16.96–16.99 |

- The phase-1 final build (`confirm_lat/`, 3 runs each) gave the same: 4 KiB off 10.24 / on 16.96;
  256 KiB off 38.40 / on 41.25.
- The final follow-up build (`v2_lat/`, 5 runs each, interleaved) gave:

  | size | gpudb | off | on |
  |---|---|---|---|
  | 4 KiB | 10.21 | 10.24 | 16.42 |
  | 256 KiB | 38.27 | 38.43 | 41.34 |

**Cost attribution.** Superseded by the cumulative measurement in "Follow-up", point 4, which is
the one to use.
- The phase-1 table (`lat_attr/`: GPU-scope fences 13.66, no gate 14.37, no poll counting 12.29 µs
  against flag on 16.96) removed each mechanism **alone**. Those removals overlap: each fence is
  inside two of the variants. So the rows (3.3 + 2.6 + 4.7 µs) must not be added, and they do not
  split the 6.7 µs total.
- In the cumulative split on the final build, the two system-scope SC fences are the largest part
  at 4 KiB, at 2.94 of 6.18 µs [measured].
- Why they cost this much is [inferred]: the waiter-side fence follows the posted MMIO doorbell
  write. The rest is also [inferred]: the extra `.sys` loads and releases, and the out-of-line calls.
- The design's §10 target (≤ 1–2%) is **not met** by S1; see "Next step".

### Cross-check of the two executed-prefix authorities

On the first round of every run the responder's receive PSN starts at 0. Its `next_rcv_psn` equals
65·⌊E/2⌋ (+64 if E is odd), where E is the executed count from `rmsn`: **105/105** agree
(`psn_check.py`). So the executed-WQE count S1 uses and the PSN authority the probe validated name
the same prefix on this hardware.


## Where S1 departs from the design (`../TRANSPARENT_RECOVERY_DESIGN.md`)

- **Executed prefix.** S1 uses the responder's `rmsn` (messages) rather than `next_rcv_psn`
  (packets), as described above, with a device-side guard that declines when a WQE is not one
  message. Both come from the same `QUERY_QP`; each recovery logs both.
- **Tickets.** The design kept logical producer indices on the wire and fell back to a rebase
  table if the NIC rejected them. The probe showed the NIC ignores the index field, so S1 keeps
  physical indices on the device and gives waiters a logical ticket instead. One `lbase` per QP
  replaces the rebase table.
- **Waiters are counted too.** The design paused only posters. The review showed that waiters
  also write QP state (`cqe_ci`), so they poll inside a counted region as well.
- **Commit point.** The design's waits were only "bounded". S1 adds the abandoned/commit
  handshake, so a waiter that stops waiting can never be followed by a re-post of its operation.
- **Replay by the host with a host doorbell.** This matches §6.4 "by host". With GPU doorbells
  the host must ring the UAR itself.

## Independent review (before the final runs)

A separate reviewer agent read the layer three times (read-only) and then did a final pass. After
the external review, it read the follow-up changes twice more, before the follow-up measurements.
Every finding was fixed, or is listed under Limits:

| round | findings | fixed |
|---|---|---|
| v1 | 7 major, 6 minor, nits | major: the whole-struct Commit write racing live waiters and parked posters (`cqe_ci` and `active` clobbered); responder quiesce deadlock with traffic in both directions (QPs now go to ERR before the wait); `flushAsync` dropping a failed ticket; device give-up not coordinated with a host re-post; a recovery with one peer clearing another peer's declined error; two contexts on one communicator; use-after-free of the recovery host by the Q4 watcher at teardown. minor: nonmsg never cleared, baseline failure ignored, faults on ungated QPs swallowed, `cudaMemsetAsync` on the helper path, fast-path fences, lbase re-check |
| v2 | 1 new major, 1 major at scale, 2 minor | `tsTicket` retries starving the host's `pollers == 0` read (parking without counter traffic); lost mailbox records (periodic gate scan); check-then-act between give-up and re-post (commit point); the 4-entry lbase ring (logical tickets) |
| v3 | 0 major, 1 minor, nits | the timeout's start was made explicit: phase 1 restarted the caller's timeout after each park, so parked time was *not* charged. An earlier version of this row said the opposite, which was wrong; the follow-up now charges it. Wording |
| v4 | nothing that is not a documented limit | – |
| follow-up v1 (after the external review's changes) | 1 major, 2 minor, 3 nits | major: a false watchdog error at the end of any round longer than 1 s with records queued (heartbeat not refreshed at round end). minor: a device-poisoned but healthy QP still took posts (gate now checks `status`); a poster's give-up could compute its target epoch from a later load and poison a just-recovered QP (now only from an odd epoch). nits: the MCST `flushAsync` path can still park (documented); a torn-down context stayed in the registry with a null key (now removed); teardown vs a concurrent `ncclDevCommDestroy` (API misuse, documented) |
| follow-up v2 | the fixes checked: correct, nothing new | – |
| third review (after the external re-check) | nothing at major or minor level; 1 optional nit | the nit: the check before re-posting can still race with a device thread whose second hold expires inside the window between that check and the publication; a second Dekker handshake (device `failing` against host `publishing`) would close it. Not implemented: the residual is surfaced by the idle scan and documented under Limits; listed under Next step |

## What is still not transparent (S1 limits)

- **Declined faults are visible by design.** REM_ACCESS and the other deterministic classes, a
  dead peer, a deadline, a lost mailbox record or a waiter that gave up all end as
  `ncclRemoteError` from the device wait and `ncclRemoteError` from `ncclCommGetAsyncError`.
  - A kernel spinning on the application's own `waitSignal` cannot be released by the library.
  - Measured: the F2 receiver's `ncclCommAbort` did not return while that kernel spun.
- **The stall is visible.** The faulted operation takes 10 ms longer (F1) or 3.6 s (RETRY_EXC).
  An application flush timeout shorter than the detection time, or shorter than the recovery, still
  returns `ncclTimeout`, as in stock NCCL. Since the follow-up, time spent held during a recovery
  counts against the caller's timeout (measured in `tmo_t`, below). The operation itself may then
  still complete after the recovery, which is what a stock timeout means as well.
- **One operation in flight per QP, one posting thread [measured scope].** The mechanism is
  written for more: re-posting `[U, S)` up to the ring size, logical tickets per waiter, counted
  posters and pollers. But only the single-op case was run.
  - The Dekker gates were never run with concurrent posters or pollers.
  - The inferred L2-coherence argument for the copy-engine side is untested under contention.
- **WQE kinds.** An epoch that posted a 0-byte put (NOP), a `get` (READ) or the MCST DUMP makes
  the round decline (`nonmsg`). Only RDMA WRITE and ATOMIC_FA are re-posted.
- **Configurations:**
  - GPU_SM_DB doorbells, ring CQ, no companion (counter) QPs;
  - the flag must be set on every rank (context creation adds one collective all-gather and a TCP
    connection per peer);
  - DOCA's "open" (DEVX) QPs only;
  - not tested: CPU-proxy doorbells (turned off), collapsed CQs, Hopper, more than 2 ranks.
- **One initiator per QP pair.** Overlapping rounds from both ends are NACKed and both sides
  decline. The helper serializes rounds, so several failing peers queue behind each other.
- **Detection only through a device wait.**
  - A QP that errs while idle is recovered only when it is next used.
  - In transparent mode `ncclGinGdakiQueryLastError` no longer reports QP-state errors, only
    declines.
- **Bounds that remain (after the follow-up):**
  - **A blocking `flush()`/`wait()` is not bounded by anything the application sets.** Such a call,
    and every parked poster, is bounded only by the library's hold: 30 s by default, 60 s when the
    device's give-up loses to a host that already passed its commit point. The hold is
    `NCCL_GIN_TS_HOLD_MS`, an environment variable read at context creation.
  - Only a flush/wait with a timeout ends at the application's own bound (parked time included).
  - Measured with a 4 s hold: before the commit point the failure came at 4.0 s (30/30); after it,
    at 8.0 s (10/10, `late_fail_b`).
  - The phase-1 gaps are closed: unbounded posters, a `flushAsync` that could block for about
    2 × hold, and parked time not charged to a timeout.
  - The watchdog surfaces a stalled or dead helper after `NCCL_GIN_TS_ROUND_MS` (25 s) of one round,
    or 1 s of missed heartbeat with records queued. It cannot tell a slow firmware command inside a
    round from a stuck one: a round that legitimately takes longer than `ROUND_MS` is failed.
  - After a lost give-up, the host checks for a device failure right before it re-posts. A device
    thread whose second hold expires between that check and the publication (a window of
    milliseconds, against a 30 s bound) fails while its operation is re-posted anyway. The idle scan
    then surfaces the error, but the operation's outcome is unknown to the application. A second
    Dekker handshake would close this (Next step).
  - `ncclCommAbort` joins the helper. If the helper is inside a firmware command at that moment,
    the abort waits for that command. The command is bounded only by the mlx5 driver's command
    timeout. In the 06:45 hang the driver reported the timeout about 104 s after the command.
  - A kernel spinning on the application's own `waitSignal` (not a GIN QP wait) is not released by
    the library (unchanged; see Declined faults).
- **Scale:**
  - The idle scan does two small device-to-host copies per gated QP every 100 ms.
  - Mailbox overflow (16 slots) becomes a decline instead of a recovery.
- **Fast-path cost** with the flag on: +66% at 4 KiB, above.

## Measured vs inferred

- **Measured:**
  - every table and number above: outcomes, bit-exact data, exact signals, async-error samples;
  - the timings (host CLOCK_MONOTONIC; the application's flush latency from `%globaltimer`);
  - the executed-prefix counts and the PSN cross-check;
  - the decline paths;
  - the negative controls;
  - the cost attribution;
  - the concurrent-`2ERR_QP` hang and its kernel log;
  - (follow-up) the forced n = 1 boundary, the bounds under a stalled or dead helper, the application
    timeout shorter than the recovery, the abort with a round in progress, the in-flight rate with
    its confidence bound, the cumulative cost split, and per-hold firmware-command counters;
  - (third review) the 2 × hold path (a lost give-up, then success at 6 s or failure at 8 s), and
    `ncclCommAbort` with `ncclCommGetAsyncError` running concurrently in a tight loop;
  - the doorbell mode per QP (log line);
  - md5 provenance.
- **From source:**
  - DOCA zero-initializes the gate padding;
  - DOCA's device code never touches `reserved1`/`reserved2`;
  - the NIC reads the doorbell record only on doorbell recovery;
  - the host UAR mapping is the one DOCA's CPU proxy rings;
  - one CQE per WQE on the ring CQ.
- **A condition of the runs, not a result:** every run from hold G (06:56) onward ran with one
  leaked firmware command slot on rain `mlx5_1` (TL;DR, follow-up point 5).
- **Inferred, not tested:**
  - that no use-after-free remains between the teardown and `ncclCommGetAsyncError`: this holds by
    construction (nothing is freed there), and the concurrent test cannot detect a silent read of
    freed memory;
  - the residual race after a lost give-up (a device failure between the pre-re-post check and the
    publication), which was not triggered;
  - that `opMu` was the cause of the phase-1 hang (mechanism plus 0 recurrences, not a controlled
    before/after comparison);
  - why the unhooked `ncclCommAbort` blocked with a held kernel (a device synchronization in the
    teardown);
  - that the Dekker handshakes hold under contention (the argument is about L2 as the coherence
    point shared by SM atomics, `.sys` loads and copy-engine accesses; the copy engine is outside
    the PTX memory model);
  - behaviour with more than one op in flight, more than two ranks, symmetric faults, and a peer
    host that dies without FIN (covered only by keepalive/`TCP_USER_TIMEOUT` and the handshake
    deadline).

## Next step: S2 (many operations in flight on one QP)

1. **Cheaper gate.**
   - Put the epoch (high 32 bits) and the poster/poller count (low 32 bits) in one 64-bit gate
     word. Entry becomes one acquire atomic add whose return value carries the epoch: a
     single-location check, so no SC fence is needed. Leave is one release add.
   - The host keeps its copy-engine write of the epoch half and its read of the count.
   - By the cumulative split (follow-up, point 4), the fences and the two counted regions are 6.05
     of the 6.18 µs at 4 KiB, so this targets nearly all of it. Correctness of a copy-engine
     partial write racing an L2 atomic on the same word needs a targeted micro-test first.
2. **Bursts.** Many unsignaled `put`s (`AggregateRequests`) then one flush, and many threads/CTAs
   posting to one QP.
   - Inject mid-burst, and verify every op's data and every signal exactly once from the executed
     prefix. `[U, S)` re-post already handles n > 2.
   - Stress the two Dekker gates with 16–1024 threads.
3. **NOP and READ.**
   - Count executed messages from `next_rcv_psn` with a device-kept per-epoch PSN counter (it
     already agrees with `rmsn` 105/105), so NOPs no longer force a decline.
   - READs and fetching atomics that were executed but not acknowledged: decline, or re-issue
     within the duplicate window the probe measured (`dup`: absorbed at depth 16, NAKed at 64).
4. Close the post-commit-point residual: a second Dekker handshake between a device thread that is
   about to fail after its second hold (`failing = next`, fence, read `publishing`) and the host before
   its first re-post (`publishing = next`, then read every `failing`).
5. Rounds for several peers without head-of-line blocking; a tie-break for symmetric initiation;
   a host-side classification from the CQ when the mailbox overflows.
6. Reset only the faulted QP pairs, to halve the 3.3 ms Commit, and measure Mode A: re-drive only
   the requester with `sq_psn = next_rcv_psn`.

## Files

| path | what |
|---|---|
| `gin_transparent_s1.diff` | full patch vs v2.32.3-1 (4 earlier layers + S1) |
| `gin_ts1.cu` | the unmodified application driver |
| `scripts/ts1/build_driver.sh`, `deploy.sh`, `make_diff.sh` | build (also `BASE=1` against the gpudb tree), deploy with md5/ldd checks, regenerate the diff |
| `scripts/ts1/run_trial.sh`, `batch.sh`, `lat_batch.sh`, `matrix.sh`, `holdE.sh`, `holdF.sh`, `holdG.sh`, `smoke*.sh` | one trial / one cell / the holds (all inside `../common/cluster_run.sh`) |
| `scripts/ts1/rows.py`, `summarize.py`, `lat_summary.py`, `psn_check.py` | raw logs → CSV → tables |
| `scripts/ts1/followup_hold.sh`, `chain_followup.sh`, `smokeW.sh`, `smoke_check.py` | follow-up holds H1–H4 (non-prio `ts1b-*`), run in order after an automatic smoke gate |
| `scripts/ts1/followup_summary.py`, `fwcmd_delta.py`, `fwcmd_snapshot.sh` | follow-up tables (split, in-flight rate with Clopper–Pearson bounds, bounds, cumulative latency, regression); read-only firmware-command counters per hold |
| `scripts/ts1/followup3_hold.sh`, `chain_followup3.sh`, `smokeX.sh`, `followup3_summary.py` | third review: holds H5 (stall after the commit point) and H6 (monitor through `ncclCommAbort`, regression), and their tables |
| `results/20260925_ts1/` | `runs/` (main matrix + in-flight cell), `confirm/` + `confirm_lat/` (final build), `lat/`, `lat_attr/`, `f1g0_before_opmu_fix/` (the hang), `smoke*/`, `trials*.csv`, `rounds*.csv`, `summary.md`, hold outputs. Each per-trial directory is stored as `<dir>.tar.xz` (55 MB of logs, mostly repeated warning lines, pack to 1.6 MB; the archives round-trip byte for byte). Run `for a in *.tar.xz; do tar xJf $a; done` in that directory before re-running the scripts below |

Follow-up results: `results/20260925_ts1/v2_split`, `v2_f1g0`, `v2_bounds`, `v2_lat`, `v2_confirm`,
`v2_smoke`, `v2_smoke2`, `v2_smoke2_pre_abort_hook` and `v2_fwcmd`. Each of these is stored as
`<dir>.tar.xz`, like the phase-1 directories; unpack before re-running the scripts. Alongside them
are the hold outputs `v2_hold_H*.out` and `v2_chain.out`, `trials_v2_*.csv` and `summary_v2.md`.
Third-review results: `v3_smoke`, `v3_late`, `v3_abortmon`, `v3_confirm`, `v3_lat` and `v3_fwcmd`, with
`v3_hold_H5.out`, `v3_hold_H6.out`, `v3_chain.out`, `trials_v3_*.csv` and `summary_v3.md`. They were
written as plain directories and are packed to `<dir>.tar.xz` like the rest; where a directory is
missing, unpack its archive.

Scratch (not in the repo): tree `$SCR/agent_ts1/nccl-src` (git: pristine → 4 layers → S1 working
changes); build `$SCR/agent_ts1/build`; variants `$SCR/agent_ts1/var/`. The cumulative variants
`c1gpufence`, `c2nogate`, `c3nopoll` are the final header plus `var/<v>.hdr.diff`. Bundle
`~/gi-bundle/gin_ts1/` on both nodes (`base/`, `var_*/`).

Reproduce (each line is one cluster hold; `CR=../common/cluster_run.sh`, `R=$PWD/results/20260925_ts1`):

```
bash scripts/ts1/matrix.sh $R                                   # holds A-D (runs/, lat/)
$CR -t prio-ts1-E -- timeout 840 bash scripts/ts1/holdE.sh $R   # cost attribution + re-runs
$CR -t prio-ts1-G -- timeout 870 bash scripts/ts1/holdG.sh $R   # in-flight cell + confirmation (final build)
python3 scripts/ts1/rows.py $R/runs --out $R/trials.csv --rounds $R/rounds.csv
python3 scripts/ts1/rows.py $R/confirm --out $R/trials_confirm.csv --rounds $R/rounds_confirm.csv
python3 scripts/ts1/summarize.py $R/trials.csv $R/rounds.csv; python3 scripts/ts1/psn_check.py $R/trials.csv $R/runs
python3 scripts/ts1/lat_summary.py $R/lat; python3 scripts/ts1/lat_summary.py $R/lat_attr
bash scripts/ts1/chain_followup.sh                              # follow-up: smoke gate, then holds ts1b-H1..H4
python3 scripts/ts1/followup_summary.py $R; python3 scripts/ts1/fwcmd_delta.py $R/v2_fwcmd
```

