# Code review: pair-reset layer and two-context driver (gin-pair-reset)

Independent review, 2026-10-08. Read-only: no file of the study was changed (only this file was added), nothing was built or run
on the cluster.

**What was reviewed** [measured].
- [pr_layer.diff](../pr_layer.diff) (md5 `53b3f219`) on top of the gin-reconnect layer, read in full context in the session scratch
  tree `agent_ts2pr/nccl-src`. `git diff` of that tree against its `rc` commit `9832602` is byte-identical to `pr_layer.diff`; the
  file's blob `20a785f` is the one named in [gin_transparent_pr.diff](../gin_transparent_pr.diff) (md5 `6d096b3d`), which differs
  from the `rc` full diff only in that file. Source mtime 12:14:55 is before the library (12:15:03); the built
  `libnccl.so.2.32.3` has md5 `51c2426c`, the deployed one ([deploy_check.txt](../deploy_check.txt)).
- The two-context driver mode, commit `35c79868` (`../gin_ts2.cu`). The committed file is unchanged since its mtime 12:14:33, which
  is before the scratch binary (12:15:38, md5 `4926edee`, the deployed `prd/gin_ts2`).
- For the scoring side of the driver question: `../score.py` and `../rows_pr.py` (status and window columns only).

Line numbers are in `src/transport/net_ib/gdaki/gin_host_gdaki.cc` of that tree unless a file is named. Tags: [measured] counted
from the raw logs under `results/20261008/`, [source] read in the code, [inferred] reasoning, [unverified].

## Summary, ranked

| # | Severity | Where | Finding | Could it have changed the measured results? |
|---|---|---|---|---|
| 1 | risk (high) | 2214–2265, 3571–3580 | The scope is chosen from the initiator's own QP states only, and the responder follows it without looking at its own QPs. A fault that broke several of the responder's QPs is "recovered" with only one pair reset; the others stay in ERR, gates open, with no record and no round, until each is next used (then a retry-exceeded stall of ≈3.5 s and one more round per context). Measured in `f3_b@pr`, 5/5 | Not the verdicts (that cell's traffic uses context 0 only). But the peer-QP-error replication result "now narrowed to context 0" (G3) also means 3 QP pairs per trial were left broken until teardown |
| 2 | risk (low) | 3197–3234, 3263, 3524 | The GID re-lookup in a scoped round moves the context-wide `g->gid_index` and the shared AH; the out-of-scope QPs keep the old source GID index in their QPC | No (path not run) |
| 3 | risk (low, scoring) | `score.py` 88–89; `gin_ts2.cu` 1005–1036 | The window-condition exclusion also fires when context 1 failed or hung inside the window, or when the kernel never finished (no dual keys at all): the worst outcome for the "other context keeps running" predictions would be excluded and refilled, not failed | No. 40/40 dual trials scored; the only exclusions were a port collision and one conflict trial |
| 4 | nit | `gin_ts2.cu` 562–601, 1018–1035 | Sensitivity of the window criteria: "≥ 1 context-1 iteration inside W" also holds under the full reset; context 1 samples the link once per ≈0.51 ms (≈2.01 ms in the peer-error cell), so the 1 ms threshold bounds a stall only to threshold + gap | No. The observed values are far below the bound, and the gate epochs show context 1 untouched independently |
| 5 | nit | 2202–2208, 2224–2227, 3491–3503 | After a scope conflict the higher rank's fault always reruns as a full reset; a re-decided round would usually be the faulted pair alone | No (cost only: one extra full round, measured below) |
| 6 | nit | 3401, 3461–3462, 3581 | The conflict path nests a second round inside the first: the round watchdog and round budget restart, and the higher rank's own faulted QP stays gated across its ACK wait, the lower rank's round and its rerun | No. Record to resume 29.8–31.1 ms with a 20 ms test stall |
| 7 | nit | 2220, 3411, 3475, 3571–3580 | The switch acts only on rounds a rank initiates; an old-build responder echoes scope 0 and the round declines after the responder committed; with one GIN context a single-bit "pair" scope and a full scope 0 count as different | No (both ranks always ran the same build and switch) |
| 8 | nit | 1246, 2186, 3409 | Contexts 32 and above are never masked, so with more than 32 GIN contexts a "pair" round also resets all of them while logging `qps=1` | No (4 contexts) |
| 9 | nit | 659–684, 1391–1394, 2285–2289 | Test knob: a non-numeric value means context 0; an out-of-range context logs "fault fired" with `moved 0/0`; the self-report knob and the WQE/signal trigger still assume context 0 | No. Every knob line shows `moved 1/1` with the requested context |
| 10 | nit | 1849–1853, 4144 | The commit failure comment still says "every QP of this peer" (now the scope; the decline that follows covers the rest). The teardown epoch line masks the host-failed bit, so a decline reads like a published round | No |

## Details

### 1. One-sided scope decision; the responder never checks its own QPs (risk, high)

- [source] `gdakiTsDecideScope` (2214–2265) looks at the record, this rank's queue and batch, and `QUERY_QP` of this rank's other QPs
  to the peer. Nothing learns the peer's QP states. The responder accepts any valid mask (3571–3580) and recovers only those QPs.
  `EXPERIMENT.md` section 4 excludes a responder health check on purpose and says such pairs are recovered "when used".
- [measured] In all 5 `f3_b@pr` trials the stock hook on rank 1 logged `moved 4/4 GIN QP(s) to ERR`. Rank 0 decided `scope=0x1
  qps=1 reason=pair`; both ranks logged one recovered line with `qps=1 scope=0x1`; rank 1's teardown line says `rounds=0
  recovered=1 declined=0`; both ranks' epochs are `[2,0,0,0]`. So rank 1's QPs of contexts 1–3 were in ERR, with open gates (epoch 0),
  from the hook to the end of every trial [inferred: no command touched them after the hook]. On the `rc` build the full round reset
  all four.
- **Scenario** [inferred]. An application that uses contexts 0 and 1, and a peer-side fault that hits both QPs of the peer (the stock
  hook, or a peer-side event that errors every QP of the context) while only context 0 has traffic in flight.
  - Rank 0 decides "pair": its own context-1 QP is RTS. Rank 1 answers the context-0 round only.
  - The next put on context 1 goes to a peer QP in ERR, which drops it silently. Rank 0 retries until retry exceeded (3.52–3.79 s
    from hook to record over this study's two peer-error cells, `EXPERIMENT.md` 15, not recounted here), then runs a second round.
    Each further broken context costs the same.
  - If the poster never polls that CQ (posts without flush, waits only on a signal), nothing is classified and the error is found
    only when the send ring fills.
- The same holds without the peer: a requester whose packets are being retransmitted (path loss, peer unreachable) is still RTS, so
  the `qp_state` condition cannot see a fault of the RETRY_EXC kind on another context before its own retry limit.
- **Suggestion.** Let the responder `QUERY_QP` its out-of-scope QPs to the initiator (it already serializes on `opMu`) and, if any is
  not RTS, answer with a new NACK code that makes the initiator rerun the round as a full reset instead of declining; or treat a
  RETRY_EXC record as full scope. At minimum, state in the results and limits that the narrowed peer-QP-error cell left three
  broken pairs per trial.

### 2. GID re-lookup changes context-wide state inside a scoped round (risk, low)

- [source] `gdakiTsResolveGid` runs in every round (initiator 3524, responder 3263). If the local GID moved, it sets the new index on
  the context's single AH (3225) and in `g->gid_index` (3231). Only the round's QPs are then reconnected (`gdakiConnectQp` at
  RTR); the other QPs to the peer keep the old source GID index in their QPC.
- **Scenario** [inferred]. An address removal and re-add moves the GID (the case the S2 path wait was built for) while only
  context 0 carries traffic. The pair round fixes context 0. Contexts 1–3 stay RTS with a source index that is now empty or holds
  another address, and each fails on its next use, as in 1.
- **Suggestion.** In `gdakiTsDecideScope`, choose the full scope when `gdakiTsFindGid(r)` is not the current index.

### 3. The window exclusion can hide a context-1 failure (risk, low, scoring)

- [source] `status_of` (`score.py` 88–89) excludes a trial of the three window cells when `dual_c1_end_after_win != "1"`, before
  any configuration check and regardless of `tx_rc`. The driver writes the dual keys only when the kernel finished (`gin_ts2.cu`
  1005), and `dual_c1_end_after_win` compares the end of context 1's last *successful* iteration with the end of W (1032–1035).
- **Scenario.** A bug stalls context 1 inside W and its flush fails, or the kernel hangs and the watchdog ends the trial. Context
  1's last good iteration ends before W ends, or there are no dual keys. The trial becomes "condition not met" and is refilled,
  while it should count against the transparency and "other context keeps running" predictions (P1a, P1d, P2a, P2c).
- The rule is pre-registered (section 8), so it cannot change for this run. [measured] It never fired: all 40 trials of the dual
  cells were scored (`results/20261008/trials_scored.csv`). The QA section should say so.
- **Suggestion** for later studies: exclude only when context 1 completed every iteration successfully before W ended; count a
  context-1 error or a missing key as a failure.

### 4. What the window criteria can and cannot see (nit)

- [source] Each context-1 iteration is put + flush (≈10 µs), then a busy gap of 500 µs (2 000 µs in the peer-error cell) that is
  outside `[t0, t1]` (`gin_ts2.cu` 572–599). Both CTAs read the same GPU's globaltimer, so W and the context-1 intervals share one
  clock; no cross-host offset enters the dual keys. The overlap rules (1028–1029) match `EXPERIMENT.md` 3.1. If context 1 completes
  no iteration, or context 0 none, no dual key is written (1021), which feeds finding 3.
- [measured] Under the full reset (`pr_dual_f1c0_full_b`) `dual_c1_in_win` is 1–2: context 1 completes iterations in the first
  part of W, before the round closes any gate. So "context 1 keeps completing iterations" (the first clause of P1d and P2c) is not
  discriminating by itself; the discriminating clause is the longest overlapping iteration (10 732–11 532 µs full vs 10.7–11.2 µs
  pair). The in-window count still separates the two (6–9 vs 1–2).
- [inferred] A stall S that overlaps a context-1 post shows up as an iteration of at least S − gap. With the observed maximum of
  10.7–12.3 µs, a stall during W is bounded by ≈0.51 ms (local-error cell) and ≈2.0 ms (peer-error cell); a shorter stall that fits
  inside a gap is invisible. The 1 ms threshold of the criterion itself bounds S only to ≈1.5 ms and ≈3 ms. The gate epochs (context 1
  always 0) independently show that no gate of context 1 was closed or republished.
- Only the rank 0 to rank 1 direction of context 1 is timed. Rank 1's own posts during its commit of context 0 are not measured.

### 5. A conflict always reruns the higher rank's fault as a full reset (nit)

- [source] `gdakiTsRequeueFull` sets `full`, and `gdakiTsDecideScope` turns it into the full scope (2224–2227). Nothing in the
  conflict needs that: after the lower rank's round, the higher rank's faulted QP is the only one it touched, and a re-decided round
  would normally be that pair alone (or stale, if the lower rank's scope covered it).
- [measured] All 11 conflict trials (10 scored and the excluded n10) end with epochs `[4,2,2,2]` on both ranks: context 0 reset twice,
  contexts 2–3 reset with no fault. Rank 1's rerun took commit 3 612–3 787 µs against 934–998 µs for its pair answer (scored 10,
  recounted from the rank 1 logs; equal to `EXPERIMENT.md` 15).
- **Suggestion.** Requeue without `full`, keeping a counter so that a second conflict on the same record falls back to full.

### 6. Nested rounds in the conflict path (nit)

- [source] `gdakiTsRespond` creates its own `gdakiTsBusy` (3581) inside the initiator's (3401): the round watchdog and
  `gdakiTsRoundLeftMs` restart from the conflict. The higher rank's own faulted QP stays in ERR with its gate closed through its ACK
  wait (bounded by `gdakiTsRoundLeftMs(handshake + quiesce + drain + path wait)`, up to ≈24.5 s with defaults), the lower rank's
  round, and its rerun, which may itself wait up to `NCCL_GIN_TS_RECONNECT_MS` for a lost socket (now with the gate closed, unlike
  the first attempt). With slow steps the sum can pass the 30 s device hold, and the rerun then declines "a device waiter already
  gave up". [measured] From rank 1's first classified record to the resume of its rerun: 29.8–31.1 ms (scored 10, recounted),
  including rank 0's 20 ms test stall.

### 7–10. Nits

- **7.** [source]
  - `ts->pairReset` is read only in `gdakiTsDecideScope` (2220); a responder with the switch off follows a scoped REQ (3571–3580).
    The control cell set the switch on both ranks, so the measurement is unaffected; document that it must match.
  - A responder built before this change zeroes `pad` in its ACK, so the initiator declines "scope mismatch in ACK" (3475) after
    the responder already committed.
  - With one GIN context the decision returns the single-bit mask `0x1` (reason "pair") while a full decision sends 0; simultaneous
    rounds then take the conflict path for identical QP sets. Normalize a mask equal to `gdakiTsAllMask` to 0 before sending.
- **8.** [source] `if (c < 32 && ...)` (1246) walks every context 32 and above whatever the scope; `gdakiTsAllMask` (2186) and the
  `qps=` of the decision line (3409, popcount) ignore them.
- **9.** [source] `atoi` turns a non-numeric `NCCL_GIN_FAULT_INJECT_CTX` into context 0; a context beyond `nContexts` moves nothing
  but still logs "fault fired", which is what the fault-applied exclusion counts. `NCCL_GIN_TS_TEST_SELF_REPORT` always reports
  context 0 with context 0's epoch (2285–2289) and the WQE trigger polls context 0's QP (1391–1394); combined with a context other
  than 0 they would report or time the wrong QP. [measured] Not used together here: the 36 `context=0` and 11 `context=1` hook lines
  all say `moved 1/1`; the 35 stock-hook lines say `moved 4/4`.
- **10.** [source] Commit's failure path (1849–1853) now moves only the scope's QPs to ERR; the comment still says every QP of the
  peer (the decline that always follows moves the rest). The teardown line prints `(w >> 32) & NCCL_GIN_TS_W_EPOCH_MASK` (4144), so
  a declined QP (host-failed bit, epoch + 2) and a republished one both read 2. The study reads it correctly for the decline cells;
  printing the flag bits would make the line self-describing.

## Checked and found correct [source]

- **Every step of a round is restricted.** Quiesce (2725–2807: gate write, move to ERR, count wait, abandoned check, unrung ring),
  Prepare (1538–1720: config, snapshot, ERR, drain, token), non-message check (2810–2820), executed counts (2666–2682), Commit
  (1724–1916: token check, reset, doorbell record, device struct, get tickets, reconnect), baseline (2685–2699), commit point and
  abandoned (2639–2663), the publishing mark, re-post and publish (2836–3097) all walk `gdakiRecForPeer`. Nothing else in a round
  touches a QP. The proxy pause is context-wide but has no effect with GPU doorbells, which transparent recovery requires at setup.
- **Untouched pairs.** Their epoch, `lbase`, `rmsn0`, CQ mapping, rescue area and get tickets (per context and peer) are neither read
  nor written by a scoped round. Their `rmsn0` stays at their own last baseline and their epoch WQE count keeps growing across rounds;
  the executed and in-flight arithmetic is modulo 2^24 and stays correct while in-flight is below ring × (1 + rescue laps).
- **Token and count order.** Both sides walk the same mask in context order, so `executed[idx]`, `nrp`, the token QPN lists and the
  re-post index line up; Commit's token check rejects any mismatch before touching a QP.
- **Scope reset on every exit.** Both round entry points use `gdakiTsScopeGuard`; `gdakiTsDecline` resets the scope first, so a
  decline is full as before; the conflict path resets it before answering; `gdakiTsDecideScope` runs before the guard and therefore
  walks every context. Every `gdakiTsDecline` inside a round is followed by a return.
- **Conflict protocol.** The higher rank sends its REQ before it can see the lower rank's REQ, and its ACK only after, so the lower
  rank always reads (and drops) the higher rank's REQ before the ACK; no circular wait; the requeued record is a copy with
  `nQueued` raised before the original is counted down; a lower-rank scope that covered the higher rank's context makes the rerun
  stale (3343). Ranks never both act as the higher rank.
- **Fallback conditions.** `queued` scans the rest of the batch and the queue under `qMu`, ignoring stale records with the same epoch
  test as the stale check; the `qp_state` query is `QUERY_QP` under `opMu` and PRM state 3 is RTS (`doca_verbs_qp.cpp` 1298–1317);
  a failed query falls back to full.
- **Threads.** `gdakiTsScope` is thread-local and only the helper changes it; `ts->batch` points at the helper's own vector and is
  read only by the helper; the teardown epoch read runs after the watcher, helper, test and hook threads are joined.
- **Driver.** The usual kv keys combine both contexts, so `transparent_ok` covers both; the final per-context signal check would fail
  if the two contexts shared a signal; W, the in-window count and the overlap maximum follow `EXPERIMENT.md` 3.1; a context 1 that
  is blocked by context 0 (shared flush or non-co-resident CTAs) fails the criteria instead of passing them.

## Firmware command counts on rain [measured, mapping inferred]

Deltas of rain's mlx5_1 command counters over each hold (`fwcmd_before-H*.txt`, `fwcmd_after-H*.txt`), against the commands the code
issues on rank 0 per trial. A constant outside the rounds (8 `2RST_QP`, 28 `QUERY_QP`, 32 of each connect step per trial, from
creation and teardown) fits all three holds.

| Hold (trials) | `2ERR_QP` | Expected | `2RST_QP` | Expected | `QUERY_QP` | Expected |
|---|--:|---|--:|---|--:|---|
| H2 (10 pair, 5 full, 5 none) | 75 | 10 × 3 + 5 × 9 | 190 | 160 + 10 × 1 + 5 × 4 | 650 | 560 + 10 × 5 + 5 × 8 |
| H3 (10 peer error pair, 10 all contexts) | 140 | 10 × 2 + 10 × 12 | 210 | 160 + 10 × 1 + 10 × 4 | 691 | 560 + 10 × 5 + 9 × 8 + 1 × 9 |
| H4 (10 conflict) | 110 | 10 × (1 + 2 + 8) | 130 | 80 + 10 × 5 | 410 | 280 + 10 × 13 |

All nine match exactly. A pair round costs rank 0 one `2RST_QP` and 5 `QUERY_QP` (3 of them the scope decision); the one
all-contexts trial that fell back on `qp_state` stopped after one query. No double move to ERR and no extra reset comes from the
conflict path on rank 0. The failure counters did not grow (31 before and after every hold, `EXPERIMENT.md` 12).

## Effect on the measured results [measured]

Nothing above changes a verdict. Counted from `results/20261008/` (dual, conflict, rep_pr, lat):
- Decision lines: `pair` 47, `qp_state` 20, `queued` 9, `requeued` 11, `off` 5. No `invalid scope in REQ`, no `scope mismatch in ACK`,
  no "ignoring ... while waiting for ACK".
- Decline lines: 15, all in the two decline cells (`f4_b` 5 logs, `f2rel_b` 10 logs); none in the dual or conflict cells.
- Conflict cell: one conflict line on rank 1 and `[4,2,2,2]` on both ranks in all 11 trials.
- Dual cells: 40/40 scored, none excluded by the window rule.
- Finding 1 is visible in `f3_b@pr` (5/5) but does not change its verdicts: its traffic uses context 0 only.

## Paths no trial ran

- A conflict where the lower rank's scope covers the higher rank's context (the rerun is stale), or where the higher rank had decided
  the full scope.
- A responder whose out-of-scope QPs are in ERR and are used afterwards (finding 1).
- A GID move during a scoped round (finding 2).
- A decline inside a scoped round, which moves the out-of-scope QPs to ERR while their gates are open.
- A requeued record that waits for a socket reconnect; a teardown during a conflict.
- `invalid scope in REQ` and `scope mismatch in ACK`; mixed switch settings or builds; one GIN context or more than 32; more than
  two ranks.
