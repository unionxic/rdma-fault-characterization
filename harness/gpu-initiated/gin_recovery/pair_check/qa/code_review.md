# Code review: responder pair-check layer (gin-pair-check)

Independent review, 2026-10-08. Read-only: no file of the study was changed (only this file was added), nothing was built or run
on the cluster.

**What was reviewed** [measured].
- [pc_layer.diff](../pc_layer.diff) (md5 `76ae7483`) on top of the gin-pair-reset layer, read in full context in the session scratch
  tree `agent_ts2pc/nccl-src`. `git diff` of that tree against its `pr` commit `842a7fa` is byte-identical to `pc_layer.diff`; the
  file's blob `e968f07` is the one named in [gin_transparent_pc.diff](../gin_transparent_pc.diff) (md5 `a22f091d`). Source mtime
  13:53:32 precedes the object (13:53:39) and the library (13:53:40); the built `libnccl.so.2.32.3` has md5 `93d9ffee`, the deployed
  one ([deploy_check.txt](../deploy_check.txt)).
- The QUERY_QP helper the check relies on, `doca_verbs_qp_open::query_seq` (`doca-gpunetio/src/doca_verbs_qp.cpp` 1297–1317): one
  DEVX QUERY_QP, `prm_state` is the QPC `state` field (3 RTS, 6 ERR), no bound of its own.
- Raw logs, kv files and rain's firmware command counters under `results/20261008/` (110 judged trials and the port-collision
  trial).

Line numbers are in `src/transport/net_ib/gdaki/gin_host_gdaki.cc` of that tree unless a file is named. Tags: [measured] counted
from the raw logs, [source] read in the code, [inferred] reasoning, [unverified].

## Summary, ranked

| # | Severity | Where | Finding | Could it have changed the measured results? |
|---|---|---|---|---|
| 1 | risk (medium, design) | 3557–3571, 3666–3672, 2288–2311 | In a scope conflict the higher rank answers the lower rank's narrowed REQ through the pair check after its own aborted Prepare has put its own scope's QPs in ERR, so the check always refuses. The higher rank's re-decided round can then never run as a pair round, in any ordering. With the check on, every conflict with a narrowed lower-rank scope ends as one full round; the re-decision can never yield a pair round | Yes: this is why the prediction "after the conflict rank 1 re-decides and runs only the context-1 pair" (E2) failed 0/10. The outcome itself is correct: transparent, all QPs RTS |
| 2 | risk (low) | 4245–4257 | The teardown QP-state line issues one QUERY_QP per QP and gated peer inside `ncclCommAbort`, by default. Before this layer the teardown issued no firmware command. A hung command interface now delays the abort; the count grows as peers × contexts | No. Exactly +4 QUERY_QP per `pc` trial on rain, failure counters unchanged, no `?` in any line |
| 3 | risk (low) | 3666–3684, 3578–3601 | The check is a snapshot taken before Quiesce, with `opMu` released in between; a responder QP that leaves RTS after an accept stays broken after the narrowed round. A requester that is still retrying reads RTS | No. Every accepted round (15) ended with all QPs RTS on both ranks |
| 4 | nit (latency) | 3541, 3809, 3832 | "Rerun at once" waits for the helper's next 1 ms `poll`: 1.03–1.08 ms from the rerun line to the rerun decision in all 35 refusal trials, with the initiator's gate closed. That is more than half of the ≈1.8 ms a refusal costs | Cost only |
| 5 | nit | 3534–3545, 2293 | Interop: a `pr`-build initiator treats NACK 12 as "peer NACK" and declines; NACK 12 carries no reason and no mask; an initiator keeps narrowing toward a peer that refuses with "off" | No (same build and switches on both ranks) |
| 6 | nit | 2212–2223, 3562–3567, 3541 | Requeue bookkeeping: `fullWhy == 0` never clears `full`, so log lines can contradict the next decision; "front" is ahead of the queue but not of the rest of the batch being handled | No (paths not run) |
| 7 | nit | 4247–4257 | The QP-state line shows the local QPC state at one instant: a QP whose partner is broken reads 3; `?` counts as not RTS in scoring; the list is cut silently past ≈79 contexts | No. The lines agree with every decision and decline (below) |
| 8 | nit | 3558–3561, 1976–1979 | Comments and counters: "Our fault runs after it" no longer holds when the answer is a refusal; "a second conflict runs as a full reset" is never what the higher rank does; `rounds=` now counts refused attempts | No |

## Details

### 1. The conflict-path check always refuses; the re-decision cannot produce a pair round (risk, medium, design)

- [source] Before the conflict branch (3557) the higher rank has quiesced its own scope (gate odd at 2787, every scope QP to ERR at
  2799–2801) and prepared it (ERR again, 1633–1644). `ncclGinRecoverAbort` (1919–1938) only resets the state and resumes the proxy;
  those QPs stay in ERR. `gdakiTsRespond` then checks the lower rank's scope (3670). The two scopes differ (that is the conflict), so
  at least one of the higher rank's own just-aborted QPs is outside the lower rank's scope and not RTS: NACK 12 follows by
  construction, whatever the fault. If the higher rank had decided the full scope, every QP but the lower rank's context is out of
  scope and in ERR. A conflict whose lower-rank scope is narrowed therefore never runs the lower rank's narrowed round.
- [source] The record is requeued before the answer (3567) on the assumption written at 3558–3561 that the lower rank's round runs
  first and makes the record stale. A refusal returns at once, so both helpers start their next round from the same event, each
  after one main-loop iteration that polls for up to 1 ms (3809).
- [inferred] No ordering lets the higher rank's re-decided pair round run:
  - its REQ crosses the lower rank's full rerun: second conflict (3562), record requeued full, the higher rank answers the full
    round, the record is stale (3399);
  - its REQ reaches the lower rank while that helper is idle: the lower rank's own faulted QP is in ERR (its fault and its aborted
    Prepare) and out of scope, so the lower rank refuses and the higher rank reruns full (`reason=peer`);
  - it is taken after the lower rank's full round: stale.

  So with `NCCL_GIN_TS_PAIR_CHECK=1` the re-decision of section 9 item 5 cannot help in any two-fault conflict. It would behave as
  the prediction assumed only with the check off (no conflict cell ran with the check off). The code does what section 9 items 2
  and 5 say; the prediction was unreachable under that design.
- [measured] All 10 conflict trials (`conflict/`):
  - rank 1 decided `scope=0x2 reason=pair` twice; its refusal of rank 0's round had `checked=3 not_rts=1` (211–243 µs);
  - after the refusal, rank 0's rerun decision came at 1.18–1.24 ms and rank 1's second decision at 1.32–1.33 ms, 0.08–0.14 ms apart
    (rank 1 times moved to rank 0's clock with the kv `clock_offset_ms`; offset error not measured). Rank 0's second 20 ms test
    stall began later (2.24–2.39 ms), so the stall does not cause the second conflict;
  - rank 1: two conflict lines, no initiator recovered line, one responder line `qps=4 scope=0xf`, `rounds=2 recovered=1`;
    epochs `[2,2,2,2]` and QP states `[3,3,3,3]` on both ranks.
- Against `pr` the outcome is no worse: context 0 is reset once instead of twice (`[2,2,2,2]` against `[4,2,2,2]`).
- **Intended fallback or defect?** The second-conflict fallback did what it was written for, and the result is correct. The defect
  is one step earlier: the check cannot tell "not RTS because this rank holds it for its own requeued record" from "not RTS and
  nobody will recover it".
- **Suggestion.** Mark the QPs an aborted attempt leaves closed (conflict path, yield-path refusal) as owned by the requeued record
  and let the check skip them; that record's next decision covers them (its `qp_state` condition sees them). The lower rank's pair
  round then runs inside `gdakiTsRespond`, and the higher rank's record runs after it as its own pair round. Otherwise drop the
  re-decision, fix 3558–3561, and state in the results that with the check on a scope conflict always ends as one full round.

### 2. The teardown line puts firmware commands into the abort path (risk, low)

- [source] 4250–4256 call `doca_verbs_qp_query_seq` for every QP to every gated peer, unconditionally, in
  `ncclGinGdakiTsCommTeardown`, which `ncclCommAbort` calls as soon as the abort flags are set (4183–4186) and before the gates are
  poisoned (4259–4268). Until this layer that function only read and wrote device memory.
- **Scenario** [inferred]. An application aborts because the NIC's command interface is in trouble (rain, 2026-09-25: a 2ERR_QP got
  no completion, timed out and leaked a command slot). Each QUERY_QP now waits for the driver's command timeout, in series, before
  the parked device threads are released by the poison. At 1 024 ranks with 4 contexts it is 4 092 commands and 1 023 WARN lines per
  rank on a healthy NIC.
- [measured] On rain the line costs exactly 4 QUERY_QP per `pc` trial (table below), no failure counter moved, and the teardown
  took 0.4–1.6 ms in the clean responder cell against 0.1–1.2 ms for the `pr` baseline (both ranks; n=10 including the fill-hold
  trial, and n=5 from the same hold).
- **Suggestion.** Make the line a test knob, or move it after the poison so a slow command never holds device threads.

### 3. The check is a snapshot (risk, low)

- [source] The plain responder checks at 3670, releases `opMu`, then quiesces (3684) and prepares. The fault hook takes `opMu` per
  fire (1443, 1484) and can move an out-of-scope QP to ERR right after an accept. The initiator's own `qp_state` condition
  (2264–2273) has the same window. QUERY_QP reports ERR, not retries: a requester retrying toward a broken responder QP is RTS until
  its retry limit (section 4 excludes this).
- **Scenario.** A peer-side event breaks the responder's context-2 QP 1 ms after it accepted a context-0 round. Context 2 stays in
  ERR with its gate open and, without traffic, no record: the gap of the `pr` review's finding 1, now limited to that window.
- [measured] Not hit. In the responder-fault cell the responder hook fired about 100 ms before the decision (`EXPERIMENT.md` 15, not
  recounted); every accepted round (10 clean responder, 5 context-0 peer error) ended with `[3,3,3,3]` on both ranks.

### 4. The rerun waits for a poll (nit, latency)

- [source] After NACK 12 the record goes to the front of the queue (3541) and `gdakiTsInitiate` returns. The helper finishes the
  batch, then polls the sockets for up to 1 ms (3809) before it swaps the queue (3832).
- [measured] From the rerun line to the rerun decision: 1.079–1.083 ms (peer QP error, n=10), 1.071–1.074 ms (responder fault, n=10),
  1.027–1.073 ms (responder switch off, n=5), 1.067–1.072 ms (conflict, n=10). The first decision to the rerun decision is
  1.81–1.95 ms in the first two cells (`EXPERIMENT.md` 15).
- **Suggestion.** Poll with timeout 0 while `nQueued > 0`.

### 5. Interop and switches (nit)

- A `pr`-build initiator has no NACK 12 branch: it declines "peer NACK", so the application sees an error a `pr` responder would
  have hidden. With a `pc` responder at `NCCL_GIN_TS_PAIR_RESET=0`, every narrowed fault of a `pr` initiator declines. Mixed builds
  are out of scope (section 4), and nothing detects them (no capability bit in HELLO).
- NACK 12 carries neither the reason nor the not-RTS contexts, so the initiator can only log "refused" and rerun the full scope where
  the scope plus the responder's bad contexts would do.
- The initiator does not remember an "off" refusal: each narrowed fault toward such a peer pays a refused attempt (0.487–0.524 ms
  from the first decision to the rerun line in the switch-off cell, `EXPERIMENT.md` 15) plus the poll of item 4.

### 6. Requeue bookkeeping (nit)

- `gdakiTsRequeue` copies the record and sets `full` only when `fullWhy != 0` (2215–2218). A record already made full by a refusal
  that then meets a conflict (lower rank narrowed, this rank's rerun full) is requeued still full while 3563–3565 log "for a new
  scope decision"; a second conflict overwrites `fullWhy` 1 with 2, so the next decision says `requeued` instead of `peer`. Logging
  only.
- `front` (3541) is ahead of the queue, not of the rest of the batch being handled (3837–3846). A second record for the same peer
  and context later in that batch is not "live" for the `queued` test (same context excluded, 2248), so it would start one more
  narrowed attempt and be refused again before the rerun. Bounded, cost only. [measured] Not hit: rank 0 has exactly two decision
  lines in each of the 35 refusal trials.

### 7. What the QP-state line can and cannot show (nit)

- [source] The helper, watcher, test and hook threads are joined before the line (4219–4228), so no host thread changes a QP state
  during it; the NIC can still move a QP to ERR on a completion error. Each value is the local QPC state: a QP whose partner is in
  ERR or destroyed reads 3 until it next sends and exhausts its retries. A pair is RTS only if both ranks' lines say 3, which is how
  the predictions use it (both `n_notrts` columns, and an absent line fails).
- A failed query prints `?`, which `rows_pc.py` (119) counts as not RTS: a conservative miss, never a false pass.
- 160-byte buffer and 1–2 characters per entry: past ≈79 contexts the list is cut without a marker (same as the epoch line).

### 8. Comments and counters (nit)

- 3558–3561 "Our fault runs after it" does not hold when the answer is a refusal (item 1).
- 1978–1979 "a second conflict on it runs as a full reset": the record is requeued full, but in all 10 trials it went stale; the full
  reset was the lower rank's round.
- `nRounds` counts refused and conflict-aborted attempts: `rounds=2 recovered=1` on rank 0 in every refusal trial and on rank 1 in
  every conflict trial. No scoring script reads it.
- `EXPERIMENT.md` 9 item 4 says the refusal comes before Prepare. On the yield path (3578–3597) the higher rank refuses after its own
  Prepare, but aborts it before NACK 12, so the conclusion (never prepared with different scopes) holds.

## Checked and found correct [source]

- **Scopes and tokens.** No path leaves the two ranks prepared with different scopes. The plain responder refuses before any gate
  write or QP change (3666–3672). The yield path is reached only with equal scopes and aborts its own Prepare before NACK 12
  (3578–3596). The conflict path aborts before answering (3566). The initiator acts on NACK 12 only for its own round and a narrowed
  scope (3534), aborts, and reruns with a new round, Prepare and token. TCP order guarantees the lower rank reads the higher rank's
  REQ before its NACK 12. The ACK scope echo (3531) and Commit's token check (1741–1758) are unchanged.
- **Records.** Each refusal or conflict branch requeues exactly one copy before it returns; `nQueued` rises with the copy and falls
  for the original (3845). The aborted attempt leaves `ts->qs[].epoch` alone, so the stale test (3399) does not drop the rerun, and
  a round that does cover the context makes it stale, as it should.
- **Gates.** After the abort the scope's gates stay odd and its QPs in ERR; Quiesce rewrites the same odd value (2787), the second
  host ring is a no-op, and the rerun's Prepare takes a fresh snapshot and drain. Device waiters keep holding (bounded by the hold).
- **Termination.** A full REQ is never refused; a refused record reruns full; a conflicted record falls back to full on the second
  conflict. Every refusal and conflict sequence traced here ends in one full round; there is no loop.
- **Threads and locks.** `gdakiTsCheckScope` runs only on the helper, saves and restores the thread-local scope, and is never called
  with `opMu` held (Prepare's locks are released on return, 1560), so there is no self-deadlock. `pairCheck` is set before the helper
  starts (4112, 4171). The teardown queries run after every thread that changes QP state is joined.
- **Switches and lines.** `NCCL_GIN_TS_PAIR_RESET=0` refuses before `NCCL_GIN_TS_PAIR_CHECK` is read (`checked=0 check_us=0`);
  with the check off nothing is logged on accept. A single-context mask is sent as 0 (2280) and is then never checked. Every new
  line's format matches `EXPERIMENT.md` 3.1.

## Firmware command counts on rain [measured, mapping inferred]

Deltas of rain's mlx5_1 counters over each hold (`fwcmd_before-*.txt`, `fwcmd_after-*.txt`) against the commands the code issues on
rank 0. Per trial outside the rounds: 8 `2RST_QP`, 32 of each connect step, and 28 `QUERY_QP` (`pr`) or 32 (`pc`, the 4 extra
being the teardown line). A refused narrowed attempt costs 2 `2ERR_QP` and 4 `QUERY_QP` (3 of them the decision); a full round 8
`2ERR_QP`, 4 `2RST_QP`, 4 of each connect step and 8 `QUERY_QP`, plus 1 decision query after a `qp_state` fallback and none for a
record already full; an accepted pair round 2, 1, 1 and 5. The hook adds one `2ERR_QP` per QP it moves, a decline 4.

| Hold (trials started) | `2ERR_QP` | `2RST_QP` | Connect steps | `QUERY_QP` |
|---|---|---|---|---|
| H1 (10 `pc` and 10 `pr` latency, 15 full-round replications with one extra responder round, 10 declines) | 228 = 3 × 60 + 8 + 10 × 4 | 424 = 45 × 8 + 16 × 4 | 1 504 = 45 × 32 + 64 | 1 543 = 35 × 32 + 10 × 28 + 15 × 9 + 8 |
| H2 (9 clean, 5 `pr`, 10 responder fault, 5 switch off) | 207 = 14 × 3 + 15 × 11 | 306 = 29 × 8 + 14 + 15 × 4 | 1 002 = 29 × 32 + 14 + 60 | 1 158 = 24 × 32 + 5 × 28 + 14 × 5 + 15 × 12 |
| H3 (10 peer error, 5 check off, 5 context-0 peer error, 5 all contexts) | 180 = 10 × 10 + 10 × 2 + 5 × 12 | 270 = 25 × 8 + 40 + 10 + 20 | 870 = 25 × 32 + 70 | 1 011 = 25 × 32 + 10 × 12 + 10 × 5 + 5 × 8 + 1 |
| H4 (10 conflict) | 110 = 10 × (1 + 2 + 8) | 120 = 10 × (8 + 4) | 360 = 10 × (32 + 4) | 440 = 10 × (32 + 4 + 8) |
| Fill (1 clean) | 3 | 9 | 33 | 37 = 32 + 5 |

All 20 deltas match exactly. Rank 0 never ran the check (no check line in any rank 0 log), so rain's counters contain no check
query; the check's queries ran on sunny, which has no counters here. The port-collision trial issued none. The failure counters
(16 and 15) did not move in any hold.

## Effect on the measured results [measured]

Only finding 1 touches a verdict, and it explains it. Counted from `results/20261008/`:
- Decision lines: `pair` 60 (20 of them rank 1's `0x2` in the conflict cell), `peer` 35, `qp_state` 21, `queued` 4.
- Check lines, all on rank 1 with `scope=0x1`: accepted 15 (`checked=3`), refused `not_rts=1` 20, `not_rts=3` 10, `off` 5. Check time
  222–245 µs (clean responder, n=10), 233–251 (context-0 peer error, n=5), 234–282 (responder fault, n=10), 232–299 (peer QP error,
  n=10), 211–243 (conflict, n=10).
- Rerun lines 35, each followed by exactly one full round; "recovery aborted" lines 55 (35 refusals, 20 conflict aborts). No
  "ignoring ... while waiting for ACK", "invalid scope in REQ", "scope mismatch in ACK" or "peer NACK". Declines 15, only in the two
  decline cells.
- QP-state lines: `[3,3,3,3]` on both ranks in every recovered trial; `[3,6,6,6]` on rank 1 in the 5 check-off trials;
  `[6,6,6,6]` where a decline moved every QP to ERR (kill cell rank 0, abort-release cell both ranks); none on the killed rank, the
  `pr` builds, or the port-collision trial; no `?`.

## Paths no trial ran

- The yield-path check (equal narrowed scopes from both ranks). The 4 yields of the symmetric cell were full scope.
- The check on rank 0 (rain); a failed QUERY_QP in the check or the teardown.
- A re-decided pair round that runs (finding 1: unreachable with the check on); a conflict with the check off.
- A full record meeting a conflict; a second same-context record in a refused batch (finding 6).
- Mixed `NCCL_GIN_TS_PAIR_CHECK` across ranks; mixed `pr` and `pc` builds; one GIN context (the mask sent as 0); more than two ranks.
